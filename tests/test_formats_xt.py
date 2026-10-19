"""The Parasolid transmit reader (``docs/formats/parasolid.md``).

SOLIDWORKS' own ``.x_t`` and ``.x_b`` exports of the fixtures are read and compared
with what SOLIDWORKS reported about the parts (``ground_truth.json``) and with the
same bodies tessellated from the SLDPRT. Every body SolidSeas writes with
``solidseas parasolid`` from a fixture part is read back, in text and binary.
Synthetic bodies (``tests/xt_bodies.py``) and assemblies built here are written in
both encodings, with and without the common header. Then the header's keywords,
the refusals, the bounds, hostile transmits (cut short at 150 points, bytes
changed at random, assemblies that contain themselves) and every surface: the
listing, the command line and the service.
"""

import json
import math
import random
import time

import pytest

import xt_bodies as X
from jsonschema_subset import validate
from serve_support import Running
from solidseas import cli, export, model, open_document, scan
from solidseas.errors import (
    FormatNotSupportedError,
    NothingToExportError,
    SldFormatError,
    SldLimitError,
    SolidSeasError,
)
from solidseas.formats import Limits, open_any, open_model
from solidseas.formats._source import Clock, ReadCancelledError
from solidseas.formats.solidworks import parasolid as ps
from solidseas.formats.solidworks import xt_schema as S
from solidseas.formats.solidworks.components import Placement
from solidseas.formats.solidworks.parasolid import NULL_DOUBLE, Node, SchemaInfo, XtTransmit
from solidseas.formats.xt import ParasolidDocument, _then, extract_body, parse_header, peek_transmit
from solidseas.tessellate import tessellate_body, tessellate_transmit
from support import FIXTURES, fixture_path, within

GT = json.loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))
EXPORTS = ["o02_boxA.x_t", "o02_boxA.x_b", "o07_boxB_h31.x_b", "o11_curved.x_b", "o12_multibody.x_b"]
CURVED = ("o10", "o11")
PARTS_WITH_BODIES = sorted(
    name
    for name, doc in GT.items()
    if name.upper().endswith(".SLDPRT")
    and any(c.get("solid_bodies") for c in doc["api"]["configurations"].values())
)
ASSEMBLY, INSTANCE, BODY, FACE, POINT, TRANSFORM, WORLD = 10, 11, 12, 14, 29, 100, 101
ATT_DEF_ID, ATTRIB_DEF, ATTRIBUTE, REAL_VALUES, CHAR_VALUES, UNICODE_VALUES = 79, 80, 81, 83, 84, 98
SOLIDWORKS_GREY = (202 / 255, 209 / 255, 238 / 255, 1.0)


# --------------------------------------------------------------------------- helpers
def _codes(warnings) -> set[str]:
    return {w.code for w in warnings}


def _placed_box(scene) -> list[float]:
    lo, hi = [math.inf] * 3, [-math.inf] * 3
    for it in scene.items:
        o = scene.objects[it.object]
        p = o.positions
        for k in range(o.n_vertices):
            q = it.placement.apply((p[3 * k], p[3 * k + 1], p[3 * k + 2]))
            for i in range(3):
                lo[i], hi[i] = min(lo[i], q[i]), max(hi[i], q[i])
    return [*lo, *hi]


def _measures(scene) -> tuple[float, float]:
    vol = area = 0.0
    for it in scene.items:
        m = scene.objects[it.object].measures()
        det = _det(it.placement.rotation)
        vol += m["volume_m3"] * det
        area += m["area_m2"] * abs(det) ** (2 / 3)
    return vol, area


def _det(r) -> float:
    return (
        r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1])
        - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
        + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0])
    )


def x_t(xt: XtTransmit, header: bool = True, **header_kw) -> bytes:
    body = ps.write_text(xt) + "\n"
    if not header:
        return body.encode("latin-1")
    return (ps.text_header(xt, fmt="text", key="k", file="k.x_t", **header_kw) + body).encode("latin-1")


def x_b(xt: XtTransmit, header: bool = True) -> bytes:
    body = ps.write_binary(xt)
    if not header:
        return body
    return ps.text_header(xt, fmt="binary", key="k", file="k.x_b").encode("ascii") + body


def _shape(fn, *args) -> XtTransmit:
    xt = fn(*args)
    xt.max_types = 231  # XtBuilder leaves it unset; a written transmit carries it
    return xt


def _default(kind: str, n: int):
    one = {"p": 0, "d": 0, "n": 0, "u": 0, "l": 0, "t": 0, "c": "+", "f": NULL_DOUBLE, "v": (0.0, 0.0, 0.0)}
    if n == S.VAR:
        return [] if kind != "c" else ""
    if n == 1:
        return one.get(kind, 0)
    return [one.get(kind, 0)] * n


IDENTITY9 = (1, 0, 0, 0, 1, 0, 0, 0, 1)
ABOUT_X = (1, 0, 0, 0, 0, -1, 0, 1, 0)  # 90 degrees about x, rows: z goes to -y


class Asm:
    """A transmit whose root (index 1) is an ASSEMBLY, in the base-schema layouts:
    bodies copied in from ``xt_bodies`` shapes, sub-assemblies, instances with
    transforms, and attributes."""

    def __init__(self) -> None:
        self.nodes: dict[int, list] = {
            1: [ASSEMBLY, {"state": 1, "type": 1, "res_size": 1e3, "res_linear": 1e-8}]
        }
        self.next = 2
        self.defs: dict[str, int] = {}

    def new(self, ntype: int, **fields) -> int:
        i = self.next
        self.next += 1
        self.nodes[i] = [ntype, fields]
        return i

    def body(self, xt: XtTransmit) -> int:
        """Copy a part transmit's nodes in; returns its BODY's index."""
        base = self.next - 1
        for nd in xt.nodes:
            fields = {}
            for (name, kind, n), v in zip(xt.layouts[nd.type], nd.vals, strict=True):
                if kind == "p":
                    v = (v + base if v else 0) if n == 1 else [x + base if x else 0 for x in v]
                fields[name] = v
            self.nodes[nd.index + base] = [nd.type, fields]
        self.next = max(self.nodes) + 1
        return 1 + base

    def faces(self, body: int) -> list[int]:
        shell = self.nodes[body][1]["shell"]
        out, f = [], self.nodes[shell][1]["face"]
        while f:
            out.append(f)
            f = self.nodes[f][1].get("next", 0)
        return out

    def assembly(self) -> int:
        return self.new(ASSEMBLY, state=1, type=1, res_size=1e3, res_linear=1e-8)

    def place(self, asm: int, part: int, rot=IDENTITY9, t=(0, 0, 0), scale=1.0, transform=True) -> int:
        inst = self.new(INSTANCE, type=1, part=part, assembly=asm)
        if transform:
            tf = self.new(
                TRANSFORM,
                owner=inst,
                rotation_matrix=[float(x) for x in rot],
                translation_vector=tuple(float(x) for x in t),
                scale=float(scale),
                perspective_vector=(NULL_DOUBLE,) * 3,
            )
            self.nodes[inst][1]["transform"] = tf
        fields = self.nodes[asm][1]
        if not fields.get("sub_instance"):
            fields["sub_instance"] = inst
        else:
            last = fields["sub_instance"]
            while self.nodes[last][1].get("next_in_part"):
                last = self.nodes[last][1]["next_in_part"]
            self.nodes[last][1]["next_in_part"] = inst
            self.nodes[inst][1]["prev_in_part"] = last
        return inst

    def attribute(self, owner: int, ident: str, value) -> int:
        """An attribute of ``owner`` with one field: three reals (a colour), a str
        (CHAR_VALUES) or a list of code units (UNICODE_VALUES)."""
        if ident not in self.defs:
            name = self.new(ATT_DEF_ID, string=ident)
            self.defs[ident] = self.new(ATTRIB_DEF, identifier=name, type_id=9000, fields=[2])
        if isinstance(value, str):
            v = self.new(CHAR_VALUES, values=value)
        elif isinstance(value, list):
            v = self.new(UNICODE_VALUES, values=value)
        else:
            v = self.new(REAL_VALUES, values=[float(c) for c in value])
        return self.new(ATTRIBUTE, definition=self.defs[ident], owner=owner, fields=[v])

    def transmit(self) -> XtTransmit:
        xt = XtTransmit()
        xt.modeller = ": TRANSMIT FILE created by modeller version 3501251"
        xt.schema = "SCH_3501251_35102_13006"
        xt.base, xt.max_types, xt.usfld = 13006, 231, 0
        for idx, (ntype, fields) in sorted(self.nodes.items()):
            lay = [tuple(f[:3]) for f in S.BASE[ntype]]
            xt.layouts.setdefault(ntype, lay)
            xt.schema_info.setdefault(ntype, SchemaInfo("base"))
            vals, count = [], None
            for name, kind, n in lay:
                v = fields[name] if name in fields else _default(kind, n)
                if n == S.VAR:
                    count = len(v)
                vals.append(v)
            xt.nodes.append(Node(ntype, idx, vals, count))
        return xt


def _assembly() -> tuple[Asm, dict[str, int]]:
    """A cylinder placed twice (once turned 90 degrees about x and moved), and a
    sub-assembly that places a box twice, itself placed 0.2 m up."""
    a = Asm()
    cyl = a.body(_shape(X.cylinder, 0.005, 0.02))
    box = a.body(_shape(X.split_box, (0.03, 0.02, 0.01), 1))
    sub = a.assembly()
    a.place(sub, box)
    a.place(sub, box, t=(0.1, 0, 0))
    a.place(1, cyl)
    a.place(1, cyl, rot=ABOUT_X, t=(0, 0.05, 0))
    a.place(1, sub, t=(0, 0, 0.2))
    return a, {"cyl": cyl, "box": box, "sub": sub}


CYLINDER_BOX_VOLUME = 2 * math.pi * 0.005**2 * 0.02 + 2 * 0.03 * 0.02 * 0.01


# --------------------------------------------------------------------------- SOLIDWORKS' exports
def _gt(name: str) -> dict:
    stem = name.rsplit(".", 1)[0]
    return GT[f"{stem}.SLDPRT"]["api"]["configurations"]["Default"]


@pytest.mark.parametrize("name", EXPORTS)
def test_solidworks_exports_match_what_solidworks_reported(name):
    g = _gt(name)
    exact = not name.startswith(CURVED)
    rel = 1e-9 if exact else 5e-3
    with open_model(fixture_path(name)) as doc:
        assert (doc.format, doc.kind) == ("parasolid", "brep")
        assert doc.variant == ("text" if name.endswith(".x_t") else "binary")
        assert doc.doc_type == ("assembly" if g["solid_bodies"] > 1 else "part")
        assert doc.units == {"length": "m", "scale_m": 1.0, "source": "format"}
        assert doc.application == {"name": "SOLIDWORKS", "version": "2024-2024016"}
        assert doc.warnings == []
        scene = doc.scene()
        assert scene.counts["bodies"] == len(scene.objects) == len(scene.items) == g["solid_bodies"]
        assert scene.counts["faces"] == scene.counts["faces_done"] == sum(b["faces"] for b in g["bodies"])
        assert scene.skipped == () and scene.warnings == ()
        vol, area = _measures(scene)
        assert vol == pytest.approx(g["volume_m3"], rel=rel)
        assert area == pytest.approx(g["surface_area_m2"], rel=rel)
        assert _placed_box(scene) == pytest.approx(g["bounding_box_m"], abs=1e-9)
        # each body is named as SOLIDWORKS named it, with its own box and SOLIDWORKS' grey
        boxes = {b["name"]: b["box_m"] for b in g["bodies"]}
        assert sorted(o.name for o in scene.objects) == sorted(boxes)
        for obj in scene.objects:
            m = obj.measures()
            assert [*m["box"][0], *m["box"][1]] == pytest.approx(boxes[obj.name], abs=1e-9)
            assert obj.color == pytest.approx(SOLIDWORKS_GREY, abs=1e-9)
            assert obj.source == "bodies" and obj.normals is None
        assert doc.counts()["bodies"] == (1 if g["solid_bodies"] == 1 else None)


@pytest.mark.parametrize("name", EXPORTS)
def test_an_export_tessellates_as_the_part_it_came_from(name):
    stem = name.rsplit(".", 1)[0]
    with open_document(fixture_path(f"{stem}.SLDPRT")) as part:
        t = part.tessellate()
    theirs = t.measures()
    with open_model(fixture_path(name)) as doc:
        scene = doc.scene()
    vol, area = _measures(scene)
    assert scene.counts["triangles"] == t.counts["triangles"]
    assert vol == pytest.approx(theirs["volume"], rel=1e-9)
    assert area == pytest.approx(theirs["area"], rel=1e-9)


def test_the_display_scene_keeps_each_faces_normals():
    with open_model(fixture_path("o11_curved.x_b")) as doc:
        welded = doc.scene()
        shown = doc.scene(prefer="display")
    (w,), (s,) = welded.objects, shown.objects
    assert s.normals is not None and len(s.normals) == len(s.positions)
    assert s.n_triangles == w.n_triangles and s.n_vertices > w.n_vertices  # not welded across edges
    assert s.measures()["volume_m3"] == pytest.approx(w.measures()["volume_m3"], rel=1e-6)
    lengths = [math.sqrt(sum(c * c for c in s.normals[3 * k : 3 * k + 3])) for k in range(s.n_vertices)]
    assert min(lengths) == pytest.approx(1.0, abs=1e-5) and max(lengths) == pytest.approx(1.0, abs=1e-5)


def test_the_header_of_a_solidworks_export():
    with open_model(fixture_path("o02_boxA.x_t")) as doc:
        props = {p.name: p.value for p in doc.properties}
        assert list(props)[:3] == ["MC", "MC_MODEL", "MC_ID"]
        assert props["FORMAT"] == "text" and props["GUISE"] == "transmit" and props["KEY"] == "o02_boxA"
        assert props["SCH"] == "SCH_3501251_35102" and props["USFLD_SIZE"] == "0"
        assert props["modeller_version"] == 3501251
        assert all(p.type in ("text", "number") for p in doc.properties)
        assert doc.fields.last_saved_by is None  # USER=unknown
        assert doc.fields.last_saved_utc is None  # DATE is local time with no zone: a property only
        assert "DATE" in props
        assert doc._xt is None  # the head never parses the transmit


def test_a_multibody_export_is_an_assembly_of_its_bodies():
    g = _gt("o12_multibody.x_b")
    with open_model(fixture_path("o12_multibody.x_b")) as doc:
        tree = doc.tree()
        root, *components = tree.nodes
        assert (root.id, root.kind, root.name, root.parent) == ("1", "assembly", "o12_multibody", None)
        assert [n.kind for n in components] == ["component", "component"]
        assert sorted(n.name for n in components) == sorted(b["name"] for b in g["bodies"])
        assert sorted(n.object for n in components) == [0, 1]
        assert all(n.placement.translation_m == (0.0, 0.0, 0.0) for n in components)
        assert {it.instance for it in doc.scene().items} == {"1.1", "1.2"}
        assert doc.scene().counts["components"] == 2
        pm = export.print_model(doc)
    assert pm.doc_type == "assembly" and pm.source_format == "parasolid" and pm.closed
    assert pm.counts == {"objects": 2, "items": 2, "vertices": 16, "triangles": 24, "placed": 2, "skipped": 0}
    assert pm.measures()["volume_m3"] == pytest.approx(g["volume_m3"], rel=1e-9)


def test_the_bodies_of_an_assembly_are_extracted_as_parts(tmp_path):
    with open_model(fixture_path("o12_multibody.x_b")) as doc:
        bodies = doc.bodies()
        scene = doc.scene()
    assert [b.body_type for b in bodies] == ["solid", "solid"]
    assert [b.node for b in bodies] == ["1.1", "1.2"]
    for body, obj in zip(bodies, scene.objects, strict=True):
        assert body.name == obj.name and body.color == obj.color
        report = ps.validate(body.transmit)
        assert report["ok"], report["errors"]
        assert body.transmit.by_index()[1].type == BODY and report["bodies"] == 1
        assert not any(n.type in (ASSEMBLY, INSTANCE, TRANSFORM) for n in body.transmit.nodes)
        alone = tessellate_transmit(body.transmit).measures()["volume"]
        assert alone == pytest.approx(obj.measures()["volume_m3"], rel=1e-12)
        with open_model(x_b(body.transmit), name="one.x_b") as again:
            assert again.doc_type == "part"
            assert again.scene().objects[0].measures()["volume_m3"] == pytest.approx(alone, rel=1e-12)
    with open_model(fixture_path("o02_boxA.x_b")) as doc:
        (body,) = doc.bodies()
        assert body.transmit is doc.transmit() and body.node == "1"


def test_extract_body_cuts_what_lies_outside_the_body():
    a, ids = _assembly()
    xt = a.transmit()
    body = xt.by_index()[ids["box"]]
    part = extract_body(xt, body)
    assert ps.validate(part)["ok"] and part.by_index()[1].type == BODY
    assert tessellate_transmit(part).counts["faces_done"] == 6


# --------------------------------------------------------------------------- files SolidSeas writes
@pytest.mark.parametrize("name", PARTS_WITH_BODIES)
def test_every_body_solidseas_writes_reads_back(name):
    configs = GT[name]["api"]["configurations"]
    with open_document(fixture_path(name)) as doc:
        result = doc.parasolid()
    assert result.bodies
    totals: dict[str, float] = {}
    for body in result.bodies:
        own = tessellate_body(body).measures()
        for data, fname, variant in ((body.x_t(), "b.x_t", "text"), (body.x_b(), "b.x_b", "binary")):
            with open_model(data, name=fname) as doc:
                assert (doc.variant, doc.doc_type) == (variant, "part")
                assert doc.application == {"name": "SolidSeas", "version": None}
                scene = doc.scene()
                vol, area = _measures(scene)
                # binary keeps every bit; text keeps 15 significant digits, which can move a
                # curved face's samples by a hair
                within = 1e-12 if variant == "binary" else 1e-5
                assert vol == pytest.approx(own["volume"], rel=within)
                assert area == pytest.approx(own["area"], rel=within)
        totals[body.configuration_name] = totals.get(body.configuration_name, 0.0) + vol
    rel = 5e-3 if name.startswith(CURVED) else 1e-9
    for cfg, vol in totals.items():
        assert vol == pytest.approx(configs[cfg]["volume_m3"], rel=rel), cfg


def test_a_partition_file_reads_as_its_bodies():
    with open_document(fixture_path("o12_multibody.SLDPRT")) as part:
        (raw,) = [r for r in part.parasolid(include_raw=True).raw if r.kind == "partition"]
    with open_model(raw.p_b(), name="session.x_b") as doc:
        assert doc.doc_type == "part" and doc.peek.kind == "partition"
        tree = doc.tree()
        assert [(n.id, n.parent, n.kind) for n in tree.nodes] == [("1", None, "body"), ("2", None, "body")]
        scene = doc.scene()
        assert [it.instance for it in scene.items] == ["1", "2"]
        assert _measures(scene)[0] == pytest.approx(8e-6, rel=1e-9)
        bodies = doc.bodies()
        assert len(bodies) == 2 and all(ps.validate(b.transmit)["ok"] for b in bodies)
        # copied out as partition_to_parts copies them, with the clock: node for node the same
        theirs, _reports = ps.partition_to_parts(doc.transmit())
    for ours, part in zip(bodies, theirs, strict=True):
        assert ours.transmit.modeller == part.modeller and ours.transmit.kind == "part"
        assert ours.transmit.layouts == part.layouts
        assert [(n.type, n.index, n.vals, n.count) for n in ours.transmit.nodes] == [
            (n.type, n.index, n.vals, n.count) for n in part.nodes
        ]


def test_a_partition_of_one_body_gives_a_part():
    with open_document(fixture_path("o02_boxA.SLDPRT")) as part:
        (raw,) = [r for r in part.parasolid(include_raw=True).raw if r.kind == "partition"]
    with open_model(raw.p_b(), name="session.x_b") as doc:
        (body,) = doc.bodies()
        assert doc.transmit().kind == "partition" and body.transmit is not doc.transmit()
        assert body.transmit.kind == "part" and body.transmit.by_index()[1].type == BODY
        assert ps.validate(body.transmit)["ok"]


def _partition(bodies: int, chain: int) -> bytes:
    """A partition whose ``bodies`` BODY nodes all lead into one chain of ``chain`` POINTs."""
    a = Asm()
    a.nodes[1] = [WORLD, {}]
    first, prev = a.next, 0
    for k in range(chain):
        i = a.new(POINT, pvec=(0.0, 0.0, float(k)), previous=prev)
        if prev:
            a.nodes[prev][1]["next"] = i
        prev = i
    for _ in range(bodies):
        a.new(BODY, body_type=1, point=first)
    xt = a.transmit()
    xt.modeller = ": TRANSMIT FILE (partition) created by modeller version 3501251"
    return x_b(xt)


def test_bodies_keep_the_time_bound_and_refuse_shared_nodes():
    with open_model(_partition(1, 6000), name="p.x_b") as doc:
        doc.tree()  # parsed and analysed: the time goes to copying the body out
        t0 = time.perf_counter()
        with pytest.raises(SldLimitError) as exc:
            doc.bodies(max_seconds=1e-6)
        assert exc.value.detail == {"limit": "seconds"} and time.perf_counter() - t0 < within(1)
        (body,) = doc.bodies()
        assert len(body.transmit.nodes) == 6001
    # 60 bodies share 5,000 nodes: copied out, they would hold 300,060 nodes, more than twice
    # the transmit's 5,061 and 100,000 more
    t0 = time.perf_counter()
    with open_model(_partition(60, 5000), name="p.x_b") as doc:
        assert len(doc.tree().nodes) == 60
        with pytest.raises(SldLimitError) as exc:
            doc.bodies()
    assert exc.value.detail == {"limit": "xt_nodes"} and "110,122 nodes" in str(exc.value)
    assert time.perf_counter() - t0 < 10


# --------------------------------------------------------------------------- synthetic bodies
SHAPES = [X.cylinder, X.sphere, X.torus, X.nurbs_cylinder, X.cone, X.hemisphere, X.split_box, X.nurbs_sphere]


@pytest.mark.parametrize("shape", SHAPES, ids=lambda f: f.__name__)
@pytest.mark.parametrize("encoding", ["text", "binary"])
@pytest.mark.parametrize("header", [True, False])
def test_synthetic_bodies_read_back_in_every_encoding(shape, encoding, header):
    xt = _shape(shape)
    direct = tessellate_transmit(xt)
    data = x_t(xt, header) if encoding == "text" else x_b(xt, header)
    with open_model(data, name="s.x_t" if encoding == "text" else "s.x_b") as doc:
        assert doc.variant == encoding and doc.doc_type == "part"
        assert [p.name for p in doc.properties][-1] == "modeller_version"
        assert len(doc.properties) == (17 if header else 1)
        scene = doc.scene()
        if encoding == "binary":  # every bit kept: the same triangles
            assert scene.counts["triangles"] == direct.counts["triangles"]
        within = 1e-12 if encoding == "binary" else 1e-3  # text: 15 digits move a NURBS face's samples
        assert _measures(scene)[0] == pytest.approx(direct.measures()["volume"], rel=within)
        (node,) = doc.tree().nodes
        assert (node.id, node.kind, node.object, node.name) == ("1", "body", 0, "s")
        pm = export.print_model(doc)
    assert pm.closed and pm.objects[0].source == "bodies"


def test_a_sheet_body_is_drawn_but_not_printed():
    xt = _shape(X.torus_band, 0.01, 0.003, -1.0, 1.0)
    with open_model(x_b(xt), name="band.x_b") as doc:
        assert doc.scene().counts["triangles"] > 0
        solids = doc.scene(body_types=("solid",))
        assert solids.items == () and len(solids.objects) == 1 and solids.objects[0].n_triangles == 0
        assert "bodies_left_out" in _codes(solids.warnings)
        assert "1 sheet" in next(w for w in solids.warnings if w.code == "bodies_left_out")
        with pytest.raises(NothingToExportError):
            export.print_model(doc)
        assert doc.bodies()[0].body_type == "sheet"


def test_a_wire_body_has_an_empty_object():
    xt = _shape(X.cylinder)
    body = xt.by_index()[1]
    body.vals[xt.field_names(BODY).index("body_type")] = 2  # say it is a wire
    with open_model(x_t(xt), name="w.x_t") as doc:
        scene = doc.scene()
        assert scene.items == () and scene.objects[0].n_triangles == 0
        assert "1 wire" in next(w for w in scene.warnings if w.code == "bodies_left_out")
        assert doc.tree().nodes[0].object == 0 and doc.bodies()[0].body_type == "wire"


# --------------------------------------------------------------------------- assemblies
@pytest.mark.parametrize("encoding", ["text", "binary"])
def test_an_assembly_places_its_instances(encoding):
    a, ids = _assembly()
    xt = a.transmit()
    assert ps.validate(xt)["ok"]
    data = x_t(xt) if encoding == "text" else x_b(xt)
    with open_model(data, name="a.x_t" if encoding == "text" else "a.x_b") as doc:
        assert doc.doc_type == "assembly" and doc.counts()["bodies"] is None
        tree = doc.tree()
        assert [(n.id, n.parent, n.kind, n.object) for n in tree.nodes] == [
            ("1", None, "assembly", None),
            ("1.1", "1", "component", 0),
            ("1.2", "1", "component", 0),
            ("1.3", "1", "component", None),
            ("1.3.1", "1.3", "component", 1),
            ("1.3.2", "1.3", "component", 1),
        ]
        by_id = {n.id: n for n in tree.nodes}
        assert by_id["1.3.2"].placement.translation_m == (0.1, 0.0, 0.0)  # relative to its parent
        scene = doc.scene()
        assert len(scene.objects) == 2 and scene.counts["components"] == 5
        placed = {it.instance: it.placement for it in scene.items}
        assert placed["1.3.2"].translation_m == pytest.approx((0.1, 0.0, 0.2))
        assert placed["1.2"].rotation == ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0))
        assert _measures(scene)[0] == pytest.approx(CYLINDER_BOX_VOLUME, rel=1e-2)
        per = [o.measures()["volume_m3"] for o in scene.objects]
        assert _measures(scene)[0] == pytest.approx(2 * per[0] + 2 * per[1], rel=1e-12)
        assert scene.warnings == ()
        # the turned cylinder runs along -y from y = 0.05: rows of the rotation act on columns
        one = [it for it in scene.items if it.instance == "1.2"]
        box = _placed_box(type(scene)(scene.objects, tuple(one), scene.counts))
        assert box == pytest.approx([-0.005, 0.03, -0.005, 0.005, 0.05, 0.005], abs=1e-9)
        assert _placed_box(scene) == pytest.approx([-0.005, -0.005, -0.005, 0.13, 0.05, 0.21], abs=1e-9)
        pm = export.print_model(doc)
    assert pm.closed and pm.counts["placed"] == 4 and pm.counts["objects"] == 2
    assert pm.measures()["volume_m3"] == pytest.approx(CYLINDER_BOX_VOLUME, rel=5e-3)  # the print chord


def test_an_assembly_exported_as_stl_reads_back(tmp_path):
    a, _ids = _assembly()
    with open_model(x_b(a.transmit()), name="a.x_b") as doc:
        pm = export.print_model(doc)
    out = tmp_path / "a.stl"
    export.write_export(pm, out, "stl")
    with open_model(out) as stl:
        assert _measures(stl.scene())[0] == pytest.approx(pm.measures()["volume_m3"], rel=1e-6)


def test_a_scaled_or_mirrored_instance_is_kept_and_warned():
    a = Asm()
    box = a.body(_shape(X.split_box, (0.01, 0.01, 0.01), 1))
    a.place(1, box, scale=2.0)
    a.place(1, box, rot=(1, 0, 0, 0, 1, 0, 0, 0, -1), t=(0.1, 0, 0))
    with open_model(x_t(a.transmit()), name="s.x_t") as doc:
        scene = doc.scene()
        assert "non_rigid_transform" in _codes(scene.warnings)
        placed = {it.instance: it.placement for it in scene.items}
        assert placed["1.1"].rotation == ((2.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 2.0))
        assert _det(placed["1.2"].rotation) == -1.0
        box = _placed_box(type(scene)(scene.objects, scene.items[:1], scene.counts))
        assert box == pytest.approx([0, 0, 0, 0.02, 0.02, 0.02], abs=1e-12)  # x' = (R x + t) s


def test_an_instance_without_a_transform_is_at_the_identity():
    a = Asm()
    box = a.body(_shape(X.split_box, (0.01, 0.01, 0.01), 1))
    a.place(1, box, transform=False)
    with open_model(x_t(a.transmit()), name="n.x_t") as doc:
        (item,) = doc.scene().items
        assert item.placement.translation_m == (0.0, 0.0, 0.0)


def test_instances_that_cannot_be_placed_are_left_out():
    a = Asm()
    box = a.body(_shape(X.split_box, (0.01, 0.01, 0.01), 1))
    a.place(1, box)
    bad = a.place(1, box)
    a.nodes[a.nodes[bad][1]["transform"]][1]["translation_vector"] = (math.nan, 0.0, 0.0)
    unset = a.place(1, box)
    a.nodes[a.nodes[unset][1]["transform"]][1]["rotation_matrix"][4] = NULL_DOUBLE
    negative = a.place(1, box)
    a.nodes[negative][1]["type"] = 2
    face = a.faces(box)[0]
    a.place(1, face)  # an instance of a face
    with open_model(x_b(a.transmit()), name="bad.x_b") as doc:
        scene = doc.scene()
        reasons = {s.instance: s.reason for s in scene.skipped}
        assert reasons == {
            "1.2": "non_finite_placement",
            "1.3": "non_finite_placement",
            "1.4": "negative_instance",
            "1.5": "bad_reference",
        }
        assert [it.instance for it in scene.items] == ["1.1"]
        pm = export.print_model(doc)
    assert pm.counts["placed"] == 1 and pm.counts["skipped"] == 4
    assert "instances_left_out" in _codes(pm.warnings)


def test_placements_compose_to_the_same_bits_as_placement_then():
    rng = random.Random(20261004)

    def any_placement() -> Placement:
        rot = tuple(tuple(rng.uniform(-3, 3) for _ in range(3)) for _ in range(3))
        return Placement(rot, tuple(rng.uniform(-1, 1) for _ in range(3)))  # type: ignore[arg-type]

    for _ in range(500):
        a, b = any_placement(), any_placement()
        assert _then(a, b) == a.then(b)


@pytest.mark.parametrize(
    "rot, scale",
    [
        (IDENTITY9, 0.0),
        ((0,) * 9, 1.0),
        ((1, 0, 0, 0, 1, 0, 0, 0, 0), 1.0),
        ((1, 0, 0, 1, 0, 0, 0, 0, 1), 1.0),
    ],
    ids=["scale 0", "zero rotation", "z flattened", "two equal rows"],
)
def test_a_transform_that_flattens_its_part_is_left_out(rot, scale):
    a = Asm()
    box = a.body(_shape(X.split_box, (0.03, 0.02, 0.01), 1))
    a.place(1, box, rot=rot, scale=scale, t=(0.1, 0, 0))
    a.place(1, box, t=(0.2, 0, 0))
    a.place(1, box, scale=1e-4, t=(0.3, 0, 0))  # tiny, but the shape is kept
    with open_model(x_b(a.transmit()), name="s.x_b") as doc:
        scene = doc.scene()
        assert [(s.instance, s.reason) for s in scene.skipped] == [("1.1", "degenerate_placement")]
        assert [it.instance for it in scene.items] == ["1.2", "1.3"]
        pm = export.print_model(doc)
    assert pm.counts["placed"] == 2 and pm.counts["skipped"] == 1 and pm.closed
    assert "instances_left_out" in _codes(pm.warnings)
    assert pm.measures()["volume_m3"] == pytest.approx(6e-6 * (1 + 1e-12), rel=1e-9)


def test_an_assembly_that_contains_itself_is_refused():
    a = Asm()
    box = a.body(_shape(X.split_box, (0.01, 0.01, 0.01), 1))
    sub = a.assembly()
    a.place(1, sub)
    a.place(sub, box)
    a.place(sub, sub)
    with open_model(x_t(a.transmit()), name="c.x_t") as doc, pytest.raises(SldFormatError, match="itself"):
        doc.scene()


def test_nesting_and_fan_out_are_bounded():
    a = Asm()
    box = a.body(_shape(X.split_box, (0.01, 0.01, 0.01), 1))
    parent = 1
    for _ in range(6):
        child = a.assembly()
        a.place(parent, child)
        parent = child
    a.place(parent, box)
    data = x_t(a.transmit())
    with open_model(data, name="d.x_t") as doc:
        assert len(doc.scene().items) == 1 and not doc.tree().truncated
    with open_model(data, name="d.x_t", limits=Limits(depth=4)) as doc:
        tree = doc.tree()
        assert tree.truncated and len(tree.nodes) == 4
        with pytest.raises(SldLimitError) as exc:
            doc.scene()
    assert exc.value.detail["limit"] == "depth"
    # ten levels of ten instances each would place 10**10 boxes
    a = Asm()
    box = a.body(_shape(X.split_box, (0.01, 0.01, 0.01), 1))
    level = box
    for _ in range(10):
        up = a.assembly()
        for _k in range(10):
            a.place(up, level)
        level = up
    a.place(1, level)
    t0 = time.perf_counter()
    with open_model(x_b(a.transmit()), name="f.x_b", limits=Limits(items=1000, tree_nodes=100)) as doc:
        assert doc.tree().truncated
        with pytest.raises(SldLimitError) as exc:
            doc.scene()
    assert exc.value.detail["limit"] == "items" and time.perf_counter() - t0 < 30


def _fan(fan: int, levels: int, *, bad: bool = False) -> bytes:
    """An assembly ``levels`` deep, each level placing the one below ``fan`` times, a box at
    the bottom (or, with ``bad``, ``fan`` instances whose part is not a body)."""
    a = Asm()
    box = a.body(_shape(X.split_box, (0.01, 0.01, 0.01), 1))
    level = box
    for k in range(levels):
        up = a.assembly() if k < levels - 1 else 1
        for j in range(fan):
            if bad and k == 0:
                a.place(up, a.faces(box)[0])
            else:
                a.place(up, level, t=(0.001 * j, 0, 0))
        level = up
    return x_b(a.transmit())


@pytest.mark.parametrize("fan, levels", [(10, 11), (2, 31), (1000, 2)])
def test_instances_that_place_a_part_many_times_cost_only_what_is_read(fan, levels):
    """At the default bounds: the tree stops at tree_nodes, a scene counts the parts it
    would place before placing any, and the bodies need no paths, so a small file that
    places a box 10**10 times reads in moments, however often it is asked."""
    data = _fan(fan, levels)
    t0 = time.perf_counter()
    with open_model(data, name="f.x_b") as doc:
        summary = doc.summary()
        tree = doc.tree()
        assert tree.truncated and len(tree.nodes) == 10_000
        assert summary["tree"]["truncated"] and len(summary["tree"]["nodes"]) == 10_000
        assert [n.id for n in tree.nodes[:3]] == ["1", "1.1", "1.1.1"]
        (body,) = doc.bodies()
        assert body.node == "1" + ".1" * levels  # the box's first place in the tree
        if fan**levels > 1_000_000:  # one past the items bound would do: refused before placing any
            for prefer in ("bodies", "display", "bodies"):
                with pytest.raises(SldLimitError) as exc:
                    doc.scene(prefer=prefer)
                assert exc.value.detail == {"limit": "items"}
    assert time.perf_counter() - t0 < 10


def test_a_scene_counts_what_it_would_place_and_leave_out():
    data = _fan(10, 2)
    with open_model(data, name="f.x_b", limits=Limits(items=100)) as doc:
        scene = doc.scene()
        assert len(scene.items) == 100 and scene.counts["components"] == 110
        assert [it.instance for it in scene.items[:3]] == ["1.1.1", "1.1.2", "1.1.3"]  # depth first
        assert scene.items[-1].placement.translation_m == pytest.approx((0.018, 0.0, 0.0))
    with open_model(data, name="f.x_b", limits=Limits(items=99)) as doc, pytest.raises(SldLimitError) as exc:
        doc.scene()
    assert exc.value.detail == {"limit": "items"} and "places more than 99" in str(exc.value)
    # 10 assemblies each leaving out 10 instances: 100 skipped items
    with open_model(_fan(10, 2, bad=True), name="b.x_b", limits=Limits(items=99)) as doc:
        assert len(doc.tree().nodes) == 11
        with pytest.raises(SldLimitError) as exc:
            doc.scene()
    assert exc.value.detail == {"limit": "items"} and "leaves out more than 99" in str(exc.value)
    with open_model(_fan(10, 2, bad=True), name="b.x_b") as doc:
        scene = doc.scene()
        assert scene.items == () and len(scene.skipped) == 100
        assert {s.reason for s in scene.skipped} == {"bad_reference"}


def test_an_instance_in_two_assemblies_is_damage():
    a = Asm()
    box = a.body(_shape(X.split_box, (0.01, 0.01, 0.01), 1))
    sub = a.assembly()
    a.place(1, sub)
    shared = a.place(1, box)
    a.nodes[sub][1]["sub_instance"] = shared  # the sub-assembly's chain runs into the top's
    with open_model(x_b(a.transmit()), name="s.x_b") as doc, pytest.raises(SldFormatError, match="two"):
        doc.tree()


# --------------------------------------------------------------------------- names and colours
def test_colours_and_names_from_attributes():
    a = Asm()
    red_box = a.body(_shape(X.split_box, (0.01, 0.01, 0.01), 1))
    blue_cyl = a.body(_shape(X.cylinder))
    faces = a.faces(red_box)
    for f in faces[:4]:
        a.attribute(f, "SDL/TYSA_COLOUR", (1.0, 0.0, 0.0))
    for f in faces[4:]:
        a.attribute(f, "SDL/TYSA_COLOUR", (0.0, 1.0, 0.0))
    a.attribute(blue_cyl, "SDL/TYSA_COLOUR", (0.0, 0.0, 1.0))  # shown by its faces with none of their own
    a.attribute(a.faces(blue_cyl)[0], "SDL/TYSA_COLOUR", (1.0, 1.0, 0.0))
    a.attribute(a.faces(blue_cyl)[1], "SDL/TYSA_COLOUR", (2.0, 0.0, 0.0))  # out of range: not a colour
    a.attribute(red_box, "SDL/TYSA_NAME", "Red box")
    a.attribute(blue_cyl, "SWIMPLICITBODYNAME_ID_U", [ord(c) for c in "Zylinder ü"])
    a.attribute(1, "SDL/TYSA_NAME", "Top^level")
    inst = a.place(1, red_box)
    a.place(1, blue_cyl)
    a.attribute(inst, "SDL/TYSA_NAME", "First")
    with open_model(x_t(a.transmit()), name="c.x_t") as doc:
        tree = {n.id: n for n in doc.tree().nodes}
        assert tree["1"].name == "Top^level"
        assert (tree["1.1"].name, tree["1.1"].color) == ("First", (1.0, 0.0, 0.0, 1.0))
        assert (tree["1.2"].name, tree["1.2"].color) == ("Zylinder ü", (0.0, 0.0, 1.0, 1.0))
        scene = doc.scene()
        assert [(o.name, o.color) for o in scene.objects] == [
            ("Red box", (1.0, 0.0, 0.0, 1.0)),
            ("Zylinder ü", (0.0, 0.0, 1.0, 1.0)),
        ]
        assert "colors_ignored" in _codes(doc.warnings)


RED, BLUE = (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)


@pytest.mark.parametrize(
    "body, faces, drawn, warned",
    [
        (None, [RED], None, True),  # one red face of six: the other five show none
        (None, [RED] * 4, RED, True),
        (None, [RED] * 6, RED, False),
        (None, [RED] * 3, RED, True),  # three against three: the first seen
        (BLUE, [RED], BLUE, True),  # five faces show the body's blue
        (BLUE, [RED] * 6, RED, False),  # every face shows its own red
        (BLUE, [], BLUE, False),
        (None, [], None, False),
    ],
)
def test_a_body_is_drawn_in_the_colour_most_of_its_faces_show(body, faces, drawn, warned):
    a = Asm()
    box = a.body(_shape(X.split_box, (0.03, 0.02, 0.01), 1))
    if body is not None:
        a.attribute(box, "SDL/TYSA_COLOUR", body)
    for face, colour in zip(a.faces(box), faces, strict=False):
        a.attribute(face, "SDL/TYSA_COLOUR", colour)
    a.place(1, box)
    with open_model(x_b(a.transmit()), name="c.x_b") as doc:
        (obj,) = doc.scene(prefer="display").objects
        assert obj.color == (None if drawn is None else (*drawn, 1.0))
        assert doc.tree().nodes[1].color == obj.color and doc.bodies()[0].color == obj.color
        assert ("colors_ignored" in _codes(doc.warnings)) == warned


def test_a_long_name_is_cut_to_its_bound():
    a = Asm()
    box = a.body(_shape(X.split_box, (0.01, 0.01, 0.01), 1))
    a.attribute(box, "SDL/TYSA_NAME", "x" * 500)
    a.place(1, box)
    with open_model(x_b(a.transmit()), name="n.x_b", limits=Limits(text_bytes=100)) as doc:
        assert doc.scene().objects[0].name == "x" * 100
        assert "text_truncated" in _codes(doc.warnings)


# --------------------------------------------------------------------------- the common header
def _header(*records: str, part3: str = "") -> bytes:
    """A common header with these PART1 records (and a PART3 one): its preamble and end
    line are those SolidSeas writes."""
    written = ps.text_header(_shape(X.cylinder), fmt="binary", key="k", file="k.x_b").splitlines()
    lines = [*written[:2], "**PART1;", *records, "**PART2;", "SCH=SCH_3501251_35102;", "USFLD_SIZE=0;"]
    lines += ["**PART3;", *([part3] if part3 else []), written[-1]]
    return ("\n".join(lines) + "\n").encode("latin-1")


def test_header_keywords_and_their_escapes():
    xt = _shape(X.cylinder)
    head = _header(
        "APPL=Example^_CAD^_5.1;",
        "USER=some^_one;SITE=a^;b^^c^nd;",
        "KEY=wrapped^",
        "_across^_records;",
        "not a keyword;",
        part3="VENDOR_DATA=1;",
    )
    with open_model(head + ps.write_binary(xt), name="h.x_b") as doc:
        props = {p.name: p.value for p in doc.properties}
        assert props["SITE"] == "a;b^c\nd" and props["KEY"] == "wrapped across records"
        assert props["VENDOR_DATA"] == "1"
        assert doc.application == {"name": "Example CAD", "version": "5.1"}
        assert doc.fields.last_saved_by == "some one"
        assert "header_unreadable" in _codes(doc.warnings)
    keywords, bad = parse_header(head[: head.index(b"**END_OF_HEADER")])
    assert bad == 1 and ("PART3", "VENDOR_DATA", "1") in keywords


def test_an_application_without_a_version():
    with open_model(_header("APPL=kid;") + ps.write_binary(_shape(X.cylinder)), name="k.x_b") as doc:
        assert doc.application == {"name": "kid", "version": None}


def test_a_header_with_no_end_or_past_its_bound():
    body = ps.write_binary(_shape(X.cylinder))
    head = _header("APPL=kid;")
    cut = head[: head.index(b"**END_OF_HEADER")]
    with pytest.raises(SldFormatError, match="no end"):
        open_model(cut, name="h.x_b")
    with pytest.raises(SldLimitError) as exc:
        open_model(
            _header("SITE=" + "x" * 3000 + ";") + body, name="h.x_b", limits=Limits(xt_header_bytes=2048)
        )
    assert exc.value.detail["limit"] == "xt_header_bytes"
    with open_model(
        _header("SITE=" + "x" * 300 + ";") + body, name="h.x_b", limits=Limits(text_bytes=64)
    ) as doc:
        assert {p.name: p.value for p in doc.properties}["SITE"] == "x" * 64
        assert "text_truncated" in _codes(doc.warnings)


def test_peek_reads_only_the_transmits_own_header():
    xt = _shape(X.cylinder)
    pk = peek_transmit(ps.write_binary(xt)[:120])
    assert (pk.flag, pk.base, pk.usfld, pk.root, pk.modeller_version) == ("binary", 13006, 0, BODY, 3501251)
    pk = peek_transmit(x_t(xt, header=False)[:200])
    assert (pk.flag, pk.base, pk.root, pk.kind) == ("text", 13006, BODY, "part")


# --------------------------------------------------------------------------- refusals
def _refused(data: bytes, name: str) -> dict:
    with pytest.raises(FormatNotSupportedError) as exc:
        open_model(data, name=name)
    return exc.value.detail


def test_a_transmit_that_does_not_embed_its_schema_is_refused():
    for schema in ("SCH_1200000_12006", "SCH_3501251_35102_12006"):
        xt = _shape(X.cylinder)
        xt.schema = schema
        if schema.count("_") == 2:
            xt.base = None
        assert _refused(x_b(xt), "s.x_b") == {"rule": "schema_not_embedded", "value": "parasolid"}
        assert _refused(x_t(xt), "s.x_t") == {"rule": "schema_not_embedded", "value": "parasolid"}


def test_bare_binary_user_fields_and_deltas_are_refused():
    xt = _shape(X.cylinder)
    bare = b"B" + ps.write_binary(xt)[4:]
    assert _refused(bare, "b.x_b")["rule"] == "bare_binary"
    xt.usfld = 2
    assert _refused(x_b(xt), "u.x_b")["rule"] == "user_fields"
    assert _refused(x_t(xt), "u.x_t")["rule"] == "user_fields"
    xt.usfld = 0
    xt.modeller = ": TRANSMIT FILE (deltas) created by modeller version 3501251"
    assert _refused(x_b(xt), "d.x_b") == {"rule": "unsupported_variant", "value": "deltas"}


def test_a_transmit_past_its_bound_lists_but_is_not_read():
    data = fixture_path("o11_curved.x_b").read_bytes()
    lim = Limits(xt_transmit_bytes=4096)
    with open_model(data, name="big.x_b", limits=lim) as doc:
        assert doc.doc_type == "part" and doc.application["name"] == "SOLIDWORKS"
        for read in (doc.tree, doc.scene, doc.bodies):
            with pytest.raises(SldLimitError) as exc:
                read()
            assert exc.value.detail == {"limit": "xt_transmit_bytes", "value": len(data) - doc._offset}
    with (
        open_model(data, name="big.x_b", limits=Limits(xt_nodes=100)) as doc,
        pytest.raises(SldLimitError) as exc,
    ):
        doc.scene()
    assert exc.value.detail == {"limit": "xt_nodes"}


@pytest.mark.parametrize("data", [b"hello world", b"**ABCDEFGHIJ\n**END_OF_HEADER***\nZZZ", b"PS\0\1junk"])
def test_content_that_is_no_transmit_is_damaged(data):
    with pytest.raises(SldFormatError):
        open_model(data, name="x.x_t")


def test_a_transmit_named_as_another_format_is_read_as_what_it_holds():
    with open_model(fixture_path("o02_boxA.x_b").read_bytes(), name="box.stl") as doc:
        assert doc.format == "parasolid" and "extension_mismatch" in _codes(doc.warnings)


# --------------------------------------------------------------------------- hostile transmits
def _survives(data: bytes, name: str) -> str:
    """Open and read ``data`` fully: ``ok``, or the code of the SolidSeas error it raised.
    Anything else fails the test."""
    t0 = time.perf_counter()
    try:
        with open_model(data, name=name, limits=Limits(seconds=10)) as doc:
            doc.tree()
            doc.scene(max_seconds=10)
            doc.bodies()
            doc.summary()
        out = "ok"
    except SolidSeasError as exc:
        out = exc.code
    assert time.perf_counter() - t0 < 15
    return out


@pytest.mark.parametrize("name", ["o02_boxA.x_t", "o02_boxA.x_b", "o12_multibody.x_b"])
def test_a_transmit_cut_short_anywhere_fails_cleanly(name):
    data = fixture_path(name).read_bytes()
    outcomes = {_survives(data[:cut], name) for cut in range(0, len(data), max(1, len(data) // 150))}
    assert outcomes <= {"ok", "damaged_file", "limit_exceeded", "unknown_format"}
    assert "damaged_file" in outcomes


@pytest.mark.parametrize("name", ["o12_multibody.x_b", "o11_curved.x_b"])
def test_changed_bytes_fail_cleanly(name):
    data = fixture_path(name).read_bytes()
    start = data.index(b"**END_OF_HEADER")
    rng = random.Random(20261004)
    outcomes = set()
    for _ in range(120):
        buf = bytearray(data)
        for _k in range(rng.choice((1, 2, 8))):
            buf[rng.randrange(start, len(buf))] = rng.randrange(256)
        outcomes.add(_survives(bytes(buf), name))
    assert outcomes <= {"ok", "damaged_file", "limit_exceeded", "format_not_supported", "unknown_format"}


def test_huge_declared_lengths_fail_fast():
    a = Asm()
    box = a.body(_shape(X.split_box, (0.01, 0.01, 0.01), 1))
    a.attribute(box, "SDL/TYSA_COLOUR", (1.0, 0.0, 0.0))
    a.place(1, box)
    xt = a.transmit()
    (reals,) = [n for n in xt.nodes if n.type == REAL_VALUES]
    reals.count = 2**31 - 1  # three values follow
    for data, name in ((x_b(xt), "h.x_b"), (x_t(xt), "h.x_t")):
        t0 = time.perf_counter()
        assert _survives(data, name) == "damaged_file"
        assert time.perf_counter() - t0 < 5


@pytest.mark.parametrize(
    "tail, trailing",
    [(b"\n\x1a", 1), (b"\r\n\0\0\0\0", 4), (b"\nleft over\n", 9), (b"\r\n\r\n", 0)],
    ids=["end of file byte", "padding", "text", "blank lines"],
)
def test_bytes_on_a_line_after_the_terminator_are_trailing_data(tail, trailing):
    """Record breaks are not significant, so what follows on the next line joins the
    terminator's 0; it is trailing data, not a damaged terminator."""
    data = x_t(_shape(X.split_box, (0.03, 0.02, 0.01), 1))
    assert data.endswith(b"0 \n")  # the terminator's 0 ends the last line
    for name in ("t.x_t", "t.x_b"):  # read by content, as text, whatever the name
        with open_model(data + tail, name=name) as doc:
            assert _measures(doc.scene())[0] == pytest.approx(6e-6, rel=1e-12)
            assert doc.transmit().trailing == trailing
            got = [w.message for w in doc.warnings if w.code == "trailing_data"]
            said = f"{trailing:,} bytes follow the transmit's terminator; they were ignored"
            assert got == ([said] if trailing else [])
    with pytest.raises(SldFormatError, match="terminator"):
        open_model(data[: -len(b" \n")] + b"5 \n", name="t.x_t").scene()  # 1 05: no terminator


# --------------------------------------------------------------------------- bounds of a scene
def test_the_triangle_cap_and_bound():
    a, _ids = _assembly()
    data = x_b(a.transmit())
    with open_model(data, name="a.x_b") as doc:
        full = doc.scene()
        cut = doc.scene(max_triangles=full.objects[0].n_triangles + 1)
        assert cut.truncated == ("max_triangles",)
        assert cut.objects[0].n_triangles == full.objects[0].n_triangles
        assert {it.instance for it in cut.items} >= {"1.1", "1.2"}
    with (
        open_model(data, name="a.x_b", limits=Limits(triangles=50)) as doc,
        pytest.raises(SldLimitError) as exc,
    ):
        doc.scene()
    assert exc.value.detail["limit"] == "triangles"


def test_time_and_cancellation():
    # Large enough that half a full scene's time still leaves room for some faces on a
    # loaded runner: with 40 boxes a third of the time was 64 ms there, under the scene's
    # own start-up, so the read stopped before any face instead of drawing part of them.
    n = 120
    a = Asm()
    for k in range(n):
        a.place(1, a.body(_shape(X.split_box, (0.01, 0.01, 0.01), 8)), t=(0.02 * k, 0, 0))
    with open_model(x_b(a.transmit()), name="s.x_b") as doc:
        doc.tree()  # parsed now, so the scene's time goes to the tessellation
        t0 = time.perf_counter()
        with pytest.raises(SldLimitError) as exc:
            doc.scene(max_seconds=0.05)
        assert exc.value.detail["limit"] == "seconds" and time.perf_counter() - t0 < within(2)
        with pytest.raises(ReadCancelledError):
            doc.scene(cancelled=lambda: True)
        t0 = time.perf_counter()
        full = doc.scene(prefer="display")
        took = time.perf_counter() - t0
        assert full.truncated == () and full.counts["faces_done"] == 6 * n
        # a view or a thumbnail draws what was done in time, and says so. On a loaded runner
        # the work before the first face can take half a full scene's time on its own, which
        # stops the read with SldLimitError instead: a larger share then leaves room for faces.
        for share in (0.5, 0.7, 0.85):
            try:
                cut = doc.scene(prefer="display", max_seconds=took * share)
            except SldLimitError:
                continue
            if cut.truncated == ("max_seconds",):
                break
        else:
            pytest.fail("no share of a full scene's time drew part of it")
        assert doc.scene(prefer="display", max_seconds=took * share) is cut
        assert 0 < cut.counts["faces_done"] < 6 * n
        assert 0 < sum(o.n_triangles for o in cut.objects) < sum(o.n_triangles for o in full.objects)
        assert len(doc.scene().items) == n


class _LateClock(Clock):
    """A clock whose deadline passes just as the parse ends: its ticks never look."""

    def __init__(self) -> None:
        super().__init__(30.0)
        self.checks = 0

    def tick(self, k: int = 1) -> None:
        pass

    def check(self) -> None:
        self.checks += 1
        if self.checks > 1:
            raise SldLimitError("late", detail={"limit": "seconds"})


def _boxes_transmit(encoding: str, n: int) -> tuple[bytes, str]:
    a = Asm()
    for k in range(n):
        a.place(1, a.body(_shape(X.split_box, (0.01, 0.01, 0.01), 8)), t=(0.02 * k, 0, 0))
    xt = a.transmit()
    return (x_t(xt) + b"\n\x1a", "s.x_t") if encoding == "text" else (x_b(xt), "s.x_b")


@pytest.mark.parametrize("encoding", ["text", "binary"])
def test_a_parse_keeps_the_deadline_and_is_not_repeated_in_vain(encoding):
    """A 0.05 s deadline stops a parse well before its end. The transmit is made large
    enough that its whole parse takes at least a quarter of a second on this machine,
    and the stop is judged against half of that: a busy machine slows both alike, and
    a fast one does not make the parse too short to stop inside."""
    n, boxes = 120, 120
    while True:
        data, name = _boxes_transmit(encoding, boxes)
        with open_model(data, name=name) as doc:
            t0 = time.perf_counter()
            doc.transmit()
            whole = time.perf_counter() - t0
        if whole >= 0.25 or boxes >= 8 * n:
            break
        boxes *= 2
    assert whole > 0.1  # long enough for the deadline to stop it well before the end
    with open_model(data, name=name, limits=Limits(seconds=0.05)) as doc:
        t0 = time.perf_counter()
        with pytest.raises(SldLimitError) as exc:
            doc.tree()
        assert exc.value.detail == {"limit": "seconds"} and doc._xt is None  # not parsed: stopped inside it
        assert time.perf_counter() - t0 < 0.05 + 0.5 * whole
        # a read with no more time is refused at once (its message says so); one with more parses
        for read in (doc.tree, lambda: doc.scene(max_seconds=0.05), lambda: doc.bodies(max_seconds=0.01)):
            t0 = time.perf_counter()
            with pytest.raises(SldLimitError, match="could not be parsed in 0.05 s") as exc:
                read()
            assert exc.value.detail == {"limit": "seconds"} and time.perf_counter() - t0 < within(0.05)
        assert len(doc.bodies(max_seconds=60)) == boxes and doc._xt is not None
    # a parse that ends after the deadline is kept, and its warnings given once
    with open_model(data, name=name) as doc:
        with pytest.raises(SldLimitError, match="late"):
            doc.transmit(_LateClock())
        kept = doc._xt
        assert kept is not None and doc.transmit() is kept and doc.tree().nodes[0].kind == "assembly"
        assert [w.code for w in doc.warnings].count("trailing_data") == (encoding == "text")


# --------------------------------------------------------------------------- surfaces
@pytest.fixture(scope="module")
def folder(tmp_path_factory):
    base = tmp_path_factory.mktemp("xt") / "parts"
    base.mkdir()
    for name in ("o02_boxA.x_t", "o12_multibody.x_b", "o02_boxA.SLDPRT"):
        (base / name).write_bytes(fixture_path(name).read_bytes())
    a, _ids = _assembly()
    (base / "assembly.xmt_txt").write_bytes(x_t(a.transmit()))
    (base / "assembly.xmt_bin").write_bytes(x_b(a.transmit()))
    old = _shape(X.cylinder)
    old.schema, old.base = "SCH_1200000_12006", None
    (base / "old.x_b").write_bytes(x_b(old))
    return base


def _run(capsys, *argv: str):
    code = cli.main([*argv, "--json"])
    out, err = capsys.readouterr()
    assert err == ""
    return code, json.loads(out)


def test_a_listing_of_parasolid_files(folder):
    entries = {e["path"]: e for e in scan(folder, formats="all", include=("preview",))}
    assert sorted(entries) == [
        "assembly.xmt_bin",
        "assembly.xmt_txt",
        "o02_boxA.SLDPRT",
        "o02_boxA.x_t",
        "o12_multibody.x_b",
        "old.x_b",
    ]
    box = entries["o02_boxA.x_t"]
    assert (box["status"], box["doc_type"]) == ("ok", "part")
    assert box["model"]["format"] == "parasolid" and box["model"]["variant"] == "text"
    assert box["model"]["counts"]["bodies"] == 1 and box["model"]["preview_renderable"]
    assert box["model"]["application"] == {"name": "SOLIDWORKS", "version": "2024-2024016"}
    assert entries["assembly.xmt_bin"]["doc_type"] == "assembly"
    old = entries["old.x_b"]
    assert old["status"] == "error" and old["error"]["code"] == "format_not_supported"
    assert old["error"]["detail"] == {"rule": "schema_not_embedded", "value": "parasolid"}


def test_open_any_reads_a_transmit(folder):
    with open_any(folder / "o12_multibody.x_b", within=folder) as doc:
        assert isinstance(doc, ParasolidDocument)


def test_cli_reads_parasolid_files(folder, capsys, tmp_path):
    path = str(folder / "assembly.xmt_txt")
    code, env = _run(capsys, "info", path)
    assert code == 0 and env["kind"] == "model_summary"
    assert validate(env, model.envelope_schema("model_summary"), strict=True) == []
    data = env["data"]
    assert (data["format"], data["variant"], data["doc_type"]) == ("parasolid", "text", "assembly")
    assert [n["kind"] for n in data["tree"]["nodes"]].count("component") == 5
    code, env = _run(capsys, "preview", path, "-o", str(tmp_path))
    assert code == 0 and env["data"]["source"] == "rendered"
    assert (tmp_path / "assembly.png").read_bytes().startswith(b"\x89PNG")
    code, env = _run(capsys, "export", path, "--format", "3mf", "-o", str(tmp_path / "a.3mf"))
    assert code == 0 and env["data"]["source_format"] == "parasolid" and env["data"]["closed"]
    assert validate(env, model.envelope_schema("export_result"), strict=True) == []
    code, env = _run(capsys, "info", path, "--max-mb", "0.001")
    assert code == 1 and env["error"]["code"] == "limit_exceeded"
    assert env["error"]["detail"]["limit"] == "xt_transmit_bytes"
    code, env = _run(capsys, "info", str(folder / "old.x_b"))
    assert code == 1 and env["error"]["detail"] == {"rule": "schema_not_embedded", "value": "parasolid"}
    assert cli.main(["info", str(folder / "o02_boxA.x_t")]) == 0
    out = capsys.readouterr().out
    assert "Parasolid (text)" in out and "m" in out


@pytest.fixture(scope="module")
def served(folder):
    running = Running({"parts": folder}, workers=2, formats=("solidworks", "parasolid"))
    yield running
    running.close()


@pytest.mark.usefixtures("outbound_guard")
def test_python_cli_and_rest_give_the_same_model_summary(served, folder, capsys):
    for name in ("o02_boxA.x_t", "o12_multibody.x_b", "assembly.xmt_bin"):
        with open_model(folder / name) as doc:
            python = doc.summary(include=model.MODEL_SUMMARY_PARTS)
        _code, cli_env = _run(capsys, "info", str(folder / name))
        rest_env = served.get("document", root="parts", path=name).json()
        assert cli_env["data"] == python == rest_env["data"], name
        assert {k: v for k, v in cli_env.items() if k != "source"} == {
            k: v for k, v in rest_env.items() if k != "source"
        }
    r = served.get("preview", root="parts", path="o12_multibody.x_b")
    assert r.status == 200 and r.body.startswith(b"\x89PNG")
    r = served.get("document", root="parts", path="old.x_b")
    assert r.status == 422 and r.json()["error"]["detail"]["rule"] == "schema_not_embedded"
