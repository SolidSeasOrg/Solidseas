"""Exports for 3D printing (``solidseas.export``): binary STL and 3MF against SOLIDWORKS.

o02 is exported and compared with SOLIDWORKS' own STL and 3MF exports of it:
the same box, volume and area to 1e-9 relative, and the STL the same facet
normals. Every fixture part and configuration that stores a body is exported
and its volume and area compared with what SOLIDWORKS reported
(``ground_truth.json``) within the tessellator's tolerance, the planar ones to
1e-9; the fixture assemblies' items are placed on the boxes SOLIDWORKS gave
their instances, and their totals add up to the assemblies' mass properties.
Every file written is read back strictly: a 3MF by parsing its package and its
model against the core specification's required structure, an STL byte by
byte; and every solid in it must be closed and consistently oriented, each
edge used twice, once each way.
"""

import io
import json
import math
import os
import re
import shutil
import struct
import xml.etree.ElementTree as ET
import zipfile
from array import array
from collections import Counter

import pytest

from builders import build_modern, fixture_streams
from solidseas import cli, model, open_document
from solidseas.errors import (
    ConfigurationNotFoundError,
    InvalidArgumentError,
    NothingToExportError,
    OutputRefusedError,
    SldLimitError,
)
from solidseas.export import (
    CHORD_FRACTION,
    FORMATS,
    MAX_CHORD_M,
    STL_HEADER,
    PrintItem,
    PrintModel,
    PrintObject,
    export_bytes,
    export_document,
    oriented_closed,
    print_model,
    stl_size,
    weld,
    write_export,
    write_stl,
)
from solidseas.formats.solidworks.components import IDENTITY, Placement
from support import FIXTURES, fixture_path, ground_truth

GT = ground_truth()
NO_BODY = {("o01_empty.SLDPRT", "Default"), ("o06_boxA_props_mat_cfg.SLDPRT", "OracleAlt")}
PART_CASES = [
    (name, cfg)
    for name, doc in sorted(GT.items())
    if name.upper().endswith(".SLDPRT")
    for cfg in doc["api"]["configurations"]
]
WITH_BODY = [c for c in PART_CASES if c not in NO_BODY]
CURVED = ("o10", "o11")  # the parts with curved faces; every other is planar and exact
ASSEMBLY_CASES = [
    ("o08_asm_2x_boxA.SLDASM", "Default"),
    ("o15_sub_asm.SLDASM", "Default"),
    ("o16_asm_features.SLDASM", "Default"),
    ("o16_asm_features.SLDASM", "Lite"),
]
CORE = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
# ST_Number of the 3MF core schema.
NUMBER = re.compile(r"[+-]?(\d+(\.\d+)?|\.\d+)([eE][+-]?\d+)?")


# --------------------------------------------------------------------------- strict readers
def read_3mf(data: bytes) -> dict:
    """A 3MF package read strictly: the zip, its content types and root relationship,
    and the model's required structure under the core specification. Returns the
    unit, objects ({id: (name, vertices in mm, triangles)}) and build items
    ([(object id, 3 x 4 transform rows or None)])."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.testzip() is None
        names = z.namelist()
        assert len(names) == len(set(names)), names
        assert all(not n.startswith("/") and ".." not in n.split("/") for n in names), names
        assert "[Content_Types].xml" in names and "_rels/.rels" in names
        types = ET.fromstring(z.read("[Content_Types].xml"))
        ns_ct = "{http://schemas.openxmlformats.org/package/2006/content-types}"
        assert types.tag == f"{ns_ct}Types"
        defaults = {d.get("Extension").lower(): d.get("ContentType") for d in types.iter(f"{ns_ct}Default")}
        assert defaults["rels"] == "application/vnd.openxmlformats-package.relationships+xml"
        rels = ET.fromstring(z.read("_rels/.rels"))
        ns_r = "{http://schemas.openxmlformats.org/package/2006/relationships}"
        assert rels.tag == f"{ns_r}Relationships"
        start = [
            r
            for r in rels.iter(f"{ns_r}Relationship")
            if r.get("Type") == "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
        ]
        assert len(start) == 1 and start[0].get("Id")
        target = start[0].get("Target")
        assert target.startswith("/")
        part = target[1:]
        assert part in names
        ext = part.rsplit(".", 1)[-1].lower()
        overrides = {o.get("PartName"): o.get("ContentType") for o in types.iter(f"{ns_ct}Override")}
        content_type = overrides.get(target, defaults.get(ext))
        assert content_type == "application/vnd.ms-package.3dmanufacturing-3dmodel+xml"
        raw = z.read(part)
    assert b"<!DOCTYPE" not in raw and b"<!ENTITY" not in raw
    root = ET.fromstring(raw)
    assert root.tag == f"{CORE}model"
    unit = root.get("unit", "millimeter")
    assert unit in ("micron", "millimeter", "centimeter", "inch", "foot", "meter")
    children = [c.tag for c in root if c.tag.startswith(CORE)]
    assert children.count(f"{CORE}resources") == 1 and children.count(f"{CORE}build") == 1
    assert set(children) <= {f"{CORE}metadata", f"{CORE}resources", f"{CORE}build"}
    objects: dict[int, tuple] = {}
    for obj in root.find(f"{CORE}resources"):
        assert obj.tag == f"{CORE}object", obj.tag
        oid = int(obj.get("id"))
        assert oid > 0 and oid not in objects
        assert obj.get("type", "model") == "model"
        meshes = obj.findall(f"{CORE}mesh")
        assert len(meshes) == 1 and obj.find(f"{CORE}components") is None
        mesh = meshes[0]
        verts = []
        for v in mesh.find(f"{CORE}vertices"):
            assert v.tag == f"{CORE}vertex"
            xyz = []
            for a in "xyz":
                assert NUMBER.fullmatch(v.get(a)), v.get(a)
                xyz.append(float(v.get(a)))
            assert all(math.isfinite(c) for c in xyz)
            verts.append(tuple(xyz))
        tris = []
        for t in mesh.find(f"{CORE}triangles"):
            assert t.tag == f"{CORE}triangle"
            ids = tuple(int(t.get(a)) for a in ("v1", "v2", "v3"))
            assert all(0 <= i < len(verts) for i in ids) and len(set(ids)) == 3, ids
            tris.append(ids)
        assert len(verts) >= 3 and len(tris) >= 1
        objects[oid] = (obj.get("name"), verts, tris)
    items = []
    for item in root.find(f"{CORE}build"):
        assert item.tag == f"{CORE}item"
        oid = int(item.get("objectid"))
        assert oid in objects
        transform = item.get("transform")
        rows = None
        if transform is not None:
            cells = transform.split(" ")
            assert len(cells) == 12 and all(NUMBER.fullmatch(c) for c in cells), transform
            m = [float(c) for c in cells]
            rows = [m[0:3], m[3:6], m[6:9], m[9:12]]
        items.append((oid, rows))
    assert items
    return {"unit": unit, "objects": objects, "items": items, "root": root}


def read_stl(data: bytes) -> list[tuple]:
    """A binary STL read byte by byte: the header, the count, and 50 bytes a triangle
    (normal, three vertices, a zero attribute). Returns (normal, a, b, c) in mm."""
    assert len(data) >= 84 and not data[:5].lower().startswith(b"solid")
    (n,) = struct.unpack_from("<I", data, 80)
    assert len(data) == 84 + 50 * n
    out = []
    for k in range(n):
        f = struct.unpack_from("<12fH", data, 84 + 50 * k)
        assert f[12] == 0
        assert all(math.isfinite(x) for x in f[:12])
        out.append((f[0:3], f[3:6], f[6:9], f[9:12]))
    return out


def closed_each_edge_twice(tris) -> bool:
    """Each edge used twice, once each way: every directed edge once, and its reverse."""
    edges = Counter()
    for a, b, c in tris:
        if len({a, b, c}) < 3:
            return False
        for e in ((a, b), (b, c), (c, a)):
            edges[e] += 1
    return all(n == 1 and edges.get((b, a)) == 1 for (a, b), n in edges.items())


def _measure(tris) -> dict:
    vol = area = 0.0
    pts = []
    for a, b, c in tris:
        vol += (
            a[0] * (b[1] * c[2] - b[2] * c[1])
            - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0])
        ) / 6.0
        u = [b[i] - a[i] for i in range(3)]
        v = [c[i] - a[i] for i in range(3)]
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        area += 0.5 * math.sqrt(sum(x * x for x in n))
        pts.extend((a, b, c))
    box = [min(p[i] for p in pts) for i in range(3)] + [max(p[i] for p in pts) for i in range(3)]
    return {"volume": vol, "area": area, "box": box}


def _place(rows, p):
    """A point (mm) through a 3MF transform: the row vector times the 3 x 4 matrix."""
    if rows is None:
        return tuple(p)
    return tuple(p[0] * rows[0][j] + p[1] * rows[1][j] + p[2] * rows[2][j] + rows[3][j] for j in range(3))


def _3mf_triangles(pkg: dict) -> list[tuple]:
    """Every item's triangles placed, in metres."""
    out = []
    for oid, rows in pkg["items"]:
        _name, verts, tris = pkg["objects"][oid]
        placed = [tuple(c / 1000 for c in _place(rows, v)) for v in verts]
        out.extend((placed[a], placed[b], placed[c]) for a, b, c in tris)
    return out


def _stl_by_vertices(facets) -> list[tuple[int, int, int]]:
    """An STL's triangles over vertices shared by exact position."""
    index: dict = {}
    out = []
    for _n, *corners in facets:
        out.append(tuple(index.setdefault(tuple(c), len(index)) for c in corners))
    return out


def _f32(p) -> tuple:
    """A point as a slicer reads it: each coordinate rounded to float32."""
    return tuple(array("f", p))


def _apart(a, b, c) -> bool:
    """No two of a triangle's corners are one point, as written or as a slicer reads it."""
    return len({a, b, c}) == 3 and len({_f32(a), _f32(b), _f32(c)}) == 3


def _check_written(data: bytes, fmt: str, *, solids: bool = True) -> list[tuple]:
    """Read ``data`` strictly and check every object closed and oriented, no triangle
    with two corners at one point (in float64, or float32 as slicers read them) and
    every STL normal that of its stored corners; the placed triangles in metres."""
    if fmt == "3mf":
        pkg = read_3mf(data)
        assert pkg["unit"] == "millimeter"
        for oid, (_name, verts, tris) in pkg["objects"].items():
            assert all(_apart(verts[a], verts[b], verts[c]) for a, b, c in tris), oid
            if solids:
                assert closed_each_edge_twice(tris), oid
        return _3mf_triangles(pkg)
    facets = read_stl(data)
    if solids:
        assert closed_each_edge_twice(_stl_by_vertices(facets))
    for normal, a, b, c in facets:  # the facet normal is that of its float32 corners
        assert _apart(a, b, c), (a, b, c)
        u = [b[i] - a[i] for i in range(3)]
        v = [c[i] - a[i] for i in range(3)]
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        length = math.sqrt(sum(x * x for x in n))
        if length > 0.0:
            assert sum(x * y / length for x, y in zip(normal, n, strict=True)) > 0.999
            assert abs(math.sqrt(sum(x * x for x in normal)) - 1) < 1e-6
        else:
            assert normal == (0.0, 0.0, 0.0)
    return [tuple(tuple(x / 1000 for x in p) for p in f[1:]) for f in facets]


def _model(name: str, configuration: str | None = None, **options) -> PrintModel:
    with open_document(fixture_path(name)) as doc:
        return print_model(doc, configuration, **options)


# --------------------------------------------------------------------------- o02 against SOLIDWORKS
def _sw_stl() -> list[tuple]:
    data = (FIXTURES / "o02_boxA.STL").read_bytes()
    (n,) = struct.unpack_from("<I", data, 80)
    return [struct.unpack_from("<12f", data, 84 + 50 * k) for k in range(n)]


def _sw_3mf() -> list[tuple]:
    with zipfile.ZipFile(FIXTURES / "o02_boxA.3mf") as z:
        root = ET.fromstring(z.read("3D/3dmodel.model"))
    verts = [tuple(float(v.get(a)) / 1000 for a in "xyz") for v in root.iter(f"{CORE}vertex")]
    return [tuple(verts[int(t.get(a))] for a in ("v1", "v2", "v3")) for t in root.iter(f"{CORE}triangle")]


@pytest.mark.parametrize("fmt", FORMATS)
def test_o02_matches_solidworks_stl_and_3mf(fmt):
    m = _model("o02_boxA.SLDPRT")
    ours = _measure(_check_written(export_bytes(m, fmt), fmt))
    sw_stl = [(f[3:6], f[6:9], f[9:12]) for f in _sw_stl()]
    sw_stl = [tuple(tuple(x / 1000 for x in p) for p in t) for t in sw_stl]
    for theirs in (_measure(sw_stl), _measure(_sw_3mf())):
        assert ours["volume"] == pytest.approx(theirs["volume"], rel=1e-9)
        assert ours["area"] == pytest.approx(theirs["area"], rel=1e-9)
        assert ours["box"] == pytest.approx(theirs["box"], rel=1e-9, abs=1e-12)
    if fmt == "stl":  # the same facet normals, as a multiset: each face split in two
        facets = read_stl(export_bytes(m, "stl"))
        assert Counter(tuple(round(x, 6) + 0.0 for x in f[0]) for f in facets) == Counter(
            tuple(round(x, 6) + 0.0 for x in f[0:3]) for f in _sw_stl()
        )
        assert len(facets) == len(_sw_stl()) == 12


def test_the_stl_byte_layout_is_exact():
    m = _model("o11_curved.SLDPRT")
    data = export_bytes(m, "stl")
    assert data[:80] == STL_HEADER and len(STL_HEADER) == 80 and not STL_HEADER.startswith(b"solid")
    assert struct.unpack_from("<I", data, 80) == (m.counts["triangles"],)
    assert len(data) == stl_size(m) == 84 + 50 * m.counts["triangles"]
    obj = m.objects[0]
    for k in (0, 1, m.counts["triangles"] - 1):  # each record: the normal, the corners in mm, zero
        rec = struct.unpack_from("<12fH", data, 84 + 50 * k)
        corners = [obj.positions[3 * obj.triangles[3 * k + j] + i] * 1000 for j in range(3) for i in range(3)]
        assert list(rec[3:12]) == pytest.approx(corners, rel=1e-6, abs=1e-6) and rec[12] == 0
    assert _check_written(data, "stl")


# --------------------------------------------------------------------------- parts against SOLIDWORKS
@pytest.mark.parametrize(("name", "configuration"), WITH_BODY)
def test_every_fixture_part_has_solidworks_volume_and_area(name, configuration):
    m = _model(name, configuration)
    g = GT[name]["api"]["configurations"][configuration]
    obj = m.objects[0]
    assert m.doc_type == "part" and len(m.objects) == 1 and len(m.items) == 1
    assert obj.source == "bodies" and obj.closed and m.closed
    assert obj.chord_m == pytest.approx(min(CHORD_FRACTION * math.dist(*_box(g)), MAX_CHORD_M))
    exact = not name.startswith(CURVED)
    rel = 1e-9 if exact else 5e-3
    for fmt in FORMATS:
        written = _measure(_check_written(export_bytes(m, fmt), fmt))
        within = max(rel, 1e-6) if fmt == "stl" else rel  # an STL's corners are float32
        assert written["volume"] == pytest.approx(g["volume_m3"], rel=within)
        assert written["area"] == pytest.approx(g["surface_area_m2"], rel=within)
        assert written["box"] == pytest.approx(g["bounding_box_m"], abs=max(obj.chord_m, 1e-9))
    measures = m.measures()
    assert measures["volume_m3"] == pytest.approx(g["volume_m3"], rel=rel)
    assert measures["area_m2"] == pytest.approx(g["surface_area_m2"], rel=rel)
    assert m.warnings == () and obj.warnings == ()


def _box(g) -> tuple[list[float], list[float]]:
    b = g["bounding_box_m"]
    return b[:3], b[3:]


def test_the_print_chord_is_finer_than_the_viewers():
    with open_document(fixture_path("o11_curved.SLDPRT")) as doc:
        viewer = doc.tessellate()
        printed = print_model(doc)
        coarse = print_model(doc, chord_m=1e-4, angle_deg=30)
    assert printed.objects[0].chord_m < viewer.chord_m / 3
    # a quarter of the viewer's would be 0.0127 mm: at most 0.01 mm
    assert (
        CHORD_FRACTION * math.dist((0, 0, 0), (0.04, 0.03, 0.01)) > MAX_CHORD_M == printed.objects[0].chord_m
    )
    assert coarse.objects[0].chord_m == 1e-4 and coarse.chord_m == 1e-4 and printed.chord_m is None
    assert coarse.counts["triangles"] < printed.counts["triangles"]
    g = GT["o11_curved.SLDPRT"]["api"]["configurations"]["Default"]
    err = [abs(m.measures()["volume_m3"] / g["volume_m3"] - 1) for m in (coarse, printed)]
    assert err[1] < err[0] and err[1] < 1e-4


def test_a_configuration_without_bodies_takes_the_active_ones_with_a_warning():
    m = _model("o06_boxA_props_mat_cfg.SLDPRT", "OracleAlt")
    assert m.configuration == "Default" and m.objects[0].source == "bodies"
    assert [w.code for w in m.warnings] == ["mesh_configuration_differs"]
    with pytest.raises(ConfigurationNotFoundError):
        _model("o02_boxA.SLDPRT", "Nope")


# --------------------------------------------------------------------------- assemblies
def _components(name: str, configuration: str) -> dict[str, dict]:
    return {c["name"]: c for c in GT[name]["api"]["configurations"][configuration]["components"]}


def _drawn(name: str, configuration: str) -> dict[str, list[float]]:
    comps = _components(name, configuration)

    def suppressed(c) -> bool:
        while c is not None:
            if c["suppressed"]:
                return True
            c = comps.get(c["parent"]) if c["parent"] else None
        return False

    return {
        n: c["box_m"]
        for n, c in comps.items()
        if c["file_name"].upper().endswith(".SLDPRT") and not suppressed(c) and not c["hidden"]
    }


@pytest.mark.parametrize(("name", "configuration"), ASSEMBLY_CASES)
def test_assemblies_are_placed_on_solidworks_boxes_and_add_up_to_its_mass_properties(name, configuration):
    m = _model(name, configuration)
    a = GT[name]["api"]["configurations"][configuration]
    expected = _drawn(name, configuration)
    assert m.doc_type == "assembly" and m.configuration == configuration and m.closed
    assert {it.instance for it in m.items} == set(expected) and m.skipped == ()
    assert all(o.source == "bodies" for o in m.objects)
    # o16's OracleAlt instances take o06's Default bodies: said of the bodies, not of a display mesh.
    assert not [w for o in m.objects for w in o.warnings if "display mesh" in w.message]
    assert m.counts["placed"] == len(expected) == m.counts["items"]
    assert m.counts["placed"] + m.counts["suppressed"] + m.counts["hidden"] == m.counts["parts"]
    # One object per component file: o16 places o02_boxA four times from one object.
    files = Counter(m.objects[it.object].file for it in m.items)
    assert len(m.objects) == len(files)
    data = export_bytes(m, "3mf")
    pkg = read_3mf(data)
    assert len(pkg["objects"]) == len(m.objects) and len(pkg["items"]) == len(m.items)
    for (oid, rows), it in zip(pkg["items"], m.items, strict=True):
        _n, verts, tris = pkg["objects"][oid]
        assert closed_each_edge_twice(tris)
        placed = [tuple(c / 1000 for c in _place(rows, v)) for v in verts]
        box = [min(p[i] for p in placed) for i in range(3)] + [max(p[i] for p in placed) for i in range(3)]
        assert box == pytest.approx(expected[it.instance], abs=1e-6), it.instance
    total = m.measures()
    for fmt, merge in (("3mf", False), ("3mf", True), ("stl", False)):
        written = _measure(_check_written(export_bytes(m, fmt, merge=merge), fmt))
        assert written["volume"] == pytest.approx(a["volume_m3"], rel=1e-6), (fmt, merge)
        assert written["area"] == pytest.approx(a["surface_area_m2"], rel=1e-6), (fmt, merge)
    assert total["volume_m3"] == pytest.approx(a["volume_m3"], rel=1e-9)
    assert total["area_m2"] == pytest.approx(a["surface_area_m2"], rel=1e-9)


def test_a_merged_3mf_is_one_object_holding_every_placed_triangle():
    m = _model("o16_asm_features.SLDASM")
    pkg = read_3mf(export_bytes(m, "3mf", merge=True))
    assert len(pkg["objects"]) == 1 and pkg["items"] == [(1, None)]
    ((name, verts, tris),) = pkg["objects"].values()
    assert name == "o16_asm_features" and len(tris) == m.counts["triangles"]
    assert closed_each_edge_twice(tris)
    separate = read_3mf(export_bytes(m, "3mf"))
    names = sorted(n for n, _v, _t in separate["objects"].values())
    assert "o02_boxA" in names and len(names) == len(set(names))


def test_object_names_come_from_the_component_files():
    m = _model("o15_sub_asm.SLDASM")
    files = {
        k: f.file_name
        for k, f in open_document(fixture_path("o15_sub_asm.SLDASM")).components().files.items()
    }
    for obj in m.objects:
        assert obj.name == os.path.splitext(files[obj.file])[0]


# --------------------------------------------------------------------------- the display mesh fallback
def _without_bodies(name: str) -> bytes:
    streams = fixture_streams(fixture_path(name))
    keep = {n: d for n, d in streams.items() if "-Partition" not in n and "LocalBodies" not in n}
    return build_modern(keep)


def test_a_part_without_bodies_is_exported_from_its_display_mesh_labelled_and_warned():
    with open_document(_without_bodies("o02_boxA.SLDPRT"), name="o02_boxA.SLDPRT") as doc:
        m = print_model(doc)
    obj = m.objects[0]
    assert obj.source == "display_mesh" and obj.name == "o02_boxA (display mesh)" and obj.chord_m is None
    assert "display_mesh_fallback" in {w.code for w in obj.warnings}
    assert obj.closed  # the box's saved mesh happens to weld into a closed solid
    g = GT["o02_boxA.SLDPRT"]["api"]["configurations"]["Default"]
    pkg = read_3mf(export_bytes(m, "3mf"))
    assert [n for n, _v, _t in pkg["objects"].values()] == ["o02_boxA (display mesh)"]
    assert m.measures()["volume_m3"] == pytest.approx(g["volume_m3"], rel=1e-6)


def test_an_open_display_mesh_says_it_is_not_closed():
    with open_document(_without_bodies("o11_curved.SLDPRT"), name="o11_curved.SLDPRT") as doc:
        mesh = doc.mesh()
        m = print_model(doc)
    obj = m.objects[0]
    codes = {w.code for w in obj.warnings}
    assert obj.source == "display_mesh" and "display_mesh_fallback" in codes
    assert obj.closed == oriented_closed(obj.triangles, obj.n_vertices)
    assert (obj.closed is False) == ("not_closed" in codes)
    pos, tris = weld(mesh)
    assert len(pos) // 3 < mesh.n_vertices  # faces share their edges' points once welded


class _Welded:
    """What weld takes: ``positions`` (xyz) and ``triangles`` (index triples)."""

    def __init__(self, positions: array, triangles: array) -> None:
        self.positions, self.triangles = positions, triangles


def _awkward_mesh(typecode: str, seed: int) -> _Welded:
    """Forty points, each repeated as many vertices, with negative and positive zeros, two
    coordinates a hair apart, triangles that repeat a vertex or a point, and vertices
    no triangle uses."""
    import random

    rng = random.Random(seed)
    points = [
        (
            rng.choice((0.0, -0.0, 1.0, 2.5)),
            rng.choice((0.0, -0.0, 3.0)),
            rng.choice((0.0, -0.0, 1e-3, 1e-3 + 2**-30)),
        )
        for _ in range(40)
    ]
    positions = array(typecode)
    for _ in range(600):
        positions.extend(rng.choice(points))
    triangles = array("I", (rng.randrange(400) for _ in range(1500)))  # vertices 400 to 599 unused
    return _Welded(positions, triangles)


def _faces(n: int, faces: int) -> _Welded:
    """An n x n grid of quads on a wavy sheet in ``faces`` strips, each strip with its own
    float32 vertices, as a display mesh's faces have theirs: they repeat along the edges."""
    pos, tri = array("f"), array("I")
    rows = n // faces
    for f in range(faces):
        base = len(pos) // 3
        for r in range(f * rows, (f + 1) * rows + 1):
            for c in range(n + 1):
                x, y = c * 1e-3, r * 1e-3
                pos.extend((x, y, 5e-4 * math.sin(x * 300) * math.cos(y * 300)))
        for r in range(rows):
            for c in range(n):
                a = base + r * (n + 1) + c
                tri.extend((a, a + 1, a + n + 1, a + 1, a + n + 2, a + n + 1))
    return _Welded(pos, tri)


@pytest.mark.parametrize("typecode", ["f", "d"])
@pytest.mark.parametrize("seed", range(4))
@pytest.mark.parametrize("chunk", [7, 65_536])
def test_weld_numbers_and_places_each_point_as_welding_by_value_does(monkeypatch, typecode, seed, chunk):
    """The same points, numbered in the order the triangles first use them, each with the
    coordinates of the corner that first did (its zero's sign included), and the same
    triangles, whether the coordinates are keyed many chunks at a time or in one."""
    from solidseas import export

    monkeypatch.setattr(export, "_WELD_CHUNK", chunk)
    m = _awkward_mesh(typecode, seed)
    (pos, tris), (want_pos, want_tris) = weld(m), export._weld_by_value(m.positions, m.triangles)
    assert pos.tobytes() == want_pos.tobytes() and tris == want_tris
    assert 0 < len(tris) < len(m.triangles) and len(pos) // 3 < 40  # repeats dropped, points merged
    assert any(math.copysign(1.0, v) < 0 for v in pos if v == 0.0)  # a negative zero kept as written


def test_weld_of_coordinates_not_all_finite_is_by_value():
    """A NaN equals nothing, not even itself: such a mesh is welded corner by corner, by
    the coordinates' values, as it always was."""
    from solidseas import export

    m = _awkward_mesh("d", 1)
    m.positions[5], m.positions[10] = math.nan, math.inf
    (pos, tris), (want_pos, want_tris) = weld(m), export._weld_by_value(m.positions, m.triangles)
    assert pos.tobytes() == want_pos.tobytes() and tris == want_tris


def test_weld_takes_well_under_the_memory_welding_by_value_took():
    """weld keys each point by its coordinates' bytes and builds its result once that
    table is gone: on faces that share only their edges, as a display mesh's do, its peak
    is under three quarters of welding by value's (about 170 bytes a point against 290,
    measured on Python 3.12)."""
    import tracemalloc

    from solidseas import export

    m = _faces(180, 18)

    def peak(fn) -> int:
        tracemalloc.start()
        try:
            base = tracemalloc.get_traced_memory()[0]
            fn()
            return tracemalloc.get_traced_memory()[1] - base
        finally:
            tracemalloc.stop()

    new = peak(lambda: weld(m))
    old = peak(lambda: export._weld_by_value(m.positions, m.triangles))
    assert new < 0.75 * old, (new, old)
    assert weld(m)[1] == export._weld_by_value(m.positions, m.triangles)[1]


def test_nothing_to_export():
    for name in ("o01_empty.SLDPRT", "o18_drw_boxA.SLDDRW"):
        with open_document(fixture_path(name)) as doc, pytest.raises(NothingToExportError):
            print_model(doc)
    streams = fixture_streams(fixture_path("o02_boxA.SLDPRT"))
    bare = {n: d for n, d in streams.items() if "-Partition" not in n and n != "Contents/DisplayLists"}
    with open_document(build_modern(bare)) as doc, pytest.raises(NothingToExportError) as exc:
        print_model(doc)
    assert (
        exc.value.code == "nothing_to_export" and model.error_info(exc.value)["code"] == "nothing_to_export"
    )


def test_an_assembly_whose_files_are_missing_has_nothing_to_export(tmp_path):
    folder = tmp_path / "alone"
    folder.mkdir()
    streams = fixture_streams(fixture_path("o08_asm_2x_boxA.SLDASM"))
    drop = {n for n in streams if n.startswith("FaceTessellations/") or n == "Contents/DisplayLists"}
    (folder / "o08.SLDASM").write_bytes(build_modern({n: d for n, d in streams.items() if n not in drop}))
    with open_document(folder / "o08.SLDASM") as doc, pytest.raises(NothingToExportError) as exc:
        print_model(doc, allow_outside_roots=False)
    assert "missing 2" in str(exc.value)


def test_instances_that_cannot_be_placed_are_left_out_and_counted(tmp_path):
    folder = tmp_path / "half"
    folder.mkdir()
    shutil.copy2(fixture_path("o16_asm_features.SLDASM"), folder / "o16_asm_features.SLDASM")
    shutil.copy2(fixture_path("o02_boxA.SLDPRT"), folder / "o02_boxA.SLDPRT")
    with open_document(folder / "o16_asm_features.SLDASM") as doc:
        m = print_model(doc, allow_outside_roots=False)
    left = [w for w in m.warnings if w.code == "instances_left_out"]
    sources = Counter(o.source for o in m.objects)
    # The other part files are not there: their instances come from the assembly's own
    # meshes, labelled; o02_boxA's from its bodies.
    assert sources["bodies"] >= 1 and sources["display_mesh"] >= 1 and not left
    assert m.counts["placed"] == 12
    for obj in m.objects:
        assert (obj.source == "display_mesh") == obj.name.endswith("(display mesh)")


def test_an_instance_reports_why_its_bodies_failed_rather_than_a_later_missing_mesh():
    from solidseas.geometry import NO_MESH_NOR_BODIES, _Failed, _reported

    not_asked, brep, no_mesh = _Failed("bodies_not_asked"), _Failed("brep_failed"), _Failed("no_mesh")
    neither = _Failed("no_mesh", NO_MESH_NOR_BODIES)
    # The export's order: bodies first, then the stored meshes and the file's own.
    assert _reported(not_asked, no_mesh, "file") is not_asked
    assert _reported(brep, no_mesh, "file") is brep
    assert _reported(neither, no_mesh, "file") is neither
    # The viewer's order: the file's mesh first, the bodies last; the later says more.
    assert _reported(no_mesh, neither, "brep") is neither
    assert _reported(no_mesh, brep, "brep") is brep
    limit = _Failed("max_triangles")
    assert _reported(not_asked, limit, "file") is limit  # a limit still wins


def _bodiless_pair(tmp_path):
    """o08 with no meshes of its own, beside an o02_boxA with no display mesh: its
    instances can come only from the part's bodies."""
    folder = tmp_path / "pair"
    folder.mkdir()
    streams = fixture_streams(fixture_path("o08_asm_2x_boxA.SLDASM"))
    drop = {n for n in streams if n.startswith("FaceTessellations/") or n == "Contents/DisplayLists"}
    (folder / "o08_asm_2x_boxA.SLDASM").write_bytes(
        build_modern({n: streams[n] for n in streams if n not in drop})
    )
    part = fixture_streams(fixture_path("o02_boxA.SLDPRT"))
    (folder / "o02_boxA.SLDPRT").write_bytes(
        build_modern({n: d for n, d in part.items() if n != "Contents/DisplayLists"})
    )
    return folder


def test_a_part_of_surfaces_only_is_said_to_be_one(tmp_path, monkeypatch):
    """The export asks for solids only. A part whose bodies are all of another type (no
    fixture has one: o02's solid stands in, with only sheets asked for) was reported as
    storing no display mesh, the last source's reason; it now says what it holds."""
    from solidseas import export
    from solidseas.geometry import display_geometry

    folder = _bodiless_pair(tmp_path)
    with open_document(folder / "o08_asm_2x_boxA.SLDASM") as doc:
        g = display_geometry(
            doc, sources=export.SOURCES, brep_options={"body_types": ("sheet",)}, allow_outside_roots=False
        )
        assert {s.reason for s in g.skipped} == {"bodies_not_asked"} and len(g.skipped) == 2
        assert "none of its bodies is of a type asked for" in g.skipped[0].message
        real = export._tess_options

        def sheets_only(*args):
            return {**real(*args), "body_types": ("sheet",)}

        monkeypatch.setattr(export, "_tess_options", sheets_only)
        with pytest.raises(NothingToExportError, match="surfaces_only 2"):
            print_model(doc, allow_outside_roots=False)
        monkeypatch.setattr(export, "_tess_options", real)
        m = print_model(doc, allow_outside_roots=False)  # solids asked for: printed from the bodies
    assert m.counts["placed"] == 2 and all(o.source == "bodies" for o in m.objects)


# --------------------------------------------------------------------------- the orientation check
def test_oriented_closed():
    tet = array("I", [0, 2, 1, 0, 1, 3, 1, 2, 3, 2, 0, 3])
    assert oriented_closed(tet, 4)
    flipped = array("I", tet)
    flipped[1], flipped[2] = flipped[2], flipped[1]
    assert not oriented_closed(flipped, 4)  # one face the wrong way: an edge used twice one way
    assert not oriented_closed(tet[:9], 4)  # a face missing
    assert not oriented_closed(array("I", [*tet, *tet[:3], 0, 1, 2]), 4)  # a face twice, both ways
    assert not oriented_closed(array("I", [0, 0, 1, *tet[3:]]), 4)  # a repeated vertex
    assert not oriented_closed(array("I"), 0) and not oriented_closed(tet, 3)  # an index out of range
    assert oriented_closed(array("I", [*tet, *(i + 4 for i in tet)]), 8)  # two solids
    assert oriented_closed(tet, 10)  # unused vertices do not matter


# --------------------------------------------------------------------------- the facing guard
_CUBE_CORNERS = [(x, y, z) for x in (0.0, 1.0) for y in (0.0, 1.0) for z in (0.0, 1.0)]
_CUBE_TRIS = [
    (0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1),
    (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3),
]  # fmt: skip


def _cubes(*cubes) -> tuple[array, array]:
    """Cubes of (size in mm, corner in mm, inside out[, its first vertex at its largest x
    rather than its smallest]) welded into one mesh, in metres."""
    pos, tris = array("d"), array("I")
    for size, at, inward, *far in cubes:
        mirrored = bool(far and far[0])
        first = len(pos) // 3
        for c in _CUBE_CORNERS:
            c = (1.0 - c[0], c[1], c[2]) if mirrored else c
            pos.extend((at[i] + size * c[i]) * 1e-3 for i in range(3))
        for a, b, c in _CUBE_TRIS:
            turn = inward != mirrored  # a mirror image runs the other way round
            tris.extend((first + a, first + c, first + b) if turn else (first + a, first + b, first + c))
    return pos, tris


@pytest.mark.parametrize(
    ("cubes", "volume_mm3", "codes"),
    [
        ([(10.0, (0, 0, 0), False)], 1000.0, set()),
        ([(10.0, (0, 0, 0), True)], 1000.0, {"shell_reoriented"}),  # a solid inside out: turned
        ([(30.0, (0, 0, 0), False), (10.0, (10, 10, 10), True)], 26000.0, set()),  # a void, facing in
        ([(30.0, (0, 0, 0), True), (10.0, (10, 10, 10), False)], 26000.0, {"shell_reoriented"}),  # both wrong
        ([(30.0, (0, 0, 0), False), (10.0, (10, 10, 10), False)], 28000.0, {"shells_inside_out"}),  # left
    ],
)
def test_the_export_guard_on_how_closed_shells_face(cubes, volume_mm3, codes):
    """A closed object's shells (its connected pieces) are judged by how they nest. One
    inside no other with a negative volume can only be a solid inside out: it is turned
    (``shell_reoriented``). One facing outward inside another is a body inside a body or a
    void turned inside out, which the mesh cannot tell apart: it is left and warned
    (``shells_inside_out``)."""
    from solidseas.export import _object

    pos, tris = _cubes(*cubes)
    obj = _object("cubes", None, None, "mesh", pos, tris, None, [])
    assert obj.closed and {w.code for w in obj.warnings} == codes
    assert obj.measures()["volume_m3"] == pytest.approx(volume_mm3 * 1e-9, rel=1e-12)
    assert oriented_closed(obj.triangles, obj.n_vertices)


@pytest.mark.parametrize(
    ("big_inward", "small_inward", "codes"),
    [
        (False, False, set()),
        (True, True, {"shell_reoriented"}),
        (False, True, {"shell_reoriented"}),
        (True, False, {"shell_reoriented"}),
    ],
)
def test_the_guard_on_shells_that_touch(big_inward, small_inward, codes):
    """A 4 mm cube against a face of a 10 mm cube, its first vertex on that face. The guard
    judged nesting by a ray from that vertex, which lay on the other cube, so the count was
    arbitrary: two right cubes warned ``shells_inside_out``, and a small cube inside out was
    taken for a void and left so, the object said to be repaired. A shell can lie inside
    another only when its box does: the small cube is outside without a ray, and whichever
    cube is inside out is turned."""
    from solidseas.export import _object

    pos, tris = _cubes((10.0, (0, 0, 0), big_inward), (4.0, (-4, 3, 3), small_inward, True))
    assert pos[3 * tris[36]] == 0.0  # the small cube's first vertex lies on the big one's face
    obj = _object("touching", None, None, "mesh", pos, tris, None, [])
    assert obj.closed and {w.code for w in obj.warnings} == codes
    assert obj.measures()["volume_m3"] == pytest.approx(1064e-9, rel=1e-12)


def test_a_void_that_touches_its_solid_is_judged_where_it_does_not():
    """A 10 mm void flush against the inside of a 30 mm cube's face: rays from that face of
    the void start on the cube and say nothing, and the void's other probes find it inside,
    so it is a void (facing in, left alone) and, facing out, a void turned inside out."""
    from solidseas.export import _object

    pos, tris = _cubes((30.0, (0, 0, 0), False), (10.0, (0, 10, 10), True))
    obj = _object("void", None, None, "mesh", pos, tris, None, [])
    assert obj.closed and obj.warnings == ()
    assert obj.measures()["volume_m3"] == pytest.approx(26000e-9, rel=1e-12)
    pos, tris = _cubes((30.0, (0, 0, 0), False), (10.0, (0, 10, 10), False))
    obj = _object("void", None, None, "mesh", pos, tris, None, [])
    assert {w.code for w in obj.warnings} == {"shells_inside_out"}


def test_shells_whose_nesting_cannot_be_told_are_warned_not_turned():
    """Two copies of one cube, one inside out: each lies on the other wherever a ray could
    start, so which lies inside which cannot be told. Neither is turned, and the warning
    says their facing was not checked; the object is not said to be repaired."""
    from solidseas.export import _object

    pos, tris = _cubes((10.0, (0, 0, 0), False), (10.0, (0, 0, 0), True))
    obj = _object("twice", None, None, "mesh", pos, tris, None, [])
    (w,) = obj.warnings
    assert w.code == "shells_inside_out" and "2 closed shells touch another" in w.message
    assert list(obj.triangles) == list(tris)


def test_the_guard_costs_one_pass_over_a_shell_whatever_lies_in_its_box(monkeypatch):
    """Many small shells inside a big one's box: each was judged by its own ray against
    every triangle of the big shell, 13 times the export's own cost with 60 of them. The
    rays of all of them are now counted in one pass over the big shell's triangles."""
    from solidseas.export import _object
    from solidseas.tessellate import checks

    calls = []
    real = checks._parity

    def counted(P, tris, ranges, probes, tol, span):
        calls.append((sum(n for _t, n in ranges), len(probes)))
        return real(P, tris, ranges, probes, tol, span)

    monkeypatch.setattr(checks, "_parity", counted)
    cubes = [(100.0, (0, 0, 0), False)]
    cubes += [(1.0, (10.0 + 3 * k, 50.0, 50.0), True) for k in range(20)]  # voids
    cubes += [(1.0, (10.0 + 3 * k, 20.0, 20.0), False) for k in range(20)]  # bodies inside a body
    pos, tris = _cubes(*cubes)
    obj = _object("many", None, None, "mesh", pos, tris, None, [])
    assert calls == [(12, 40 * checks.PROBES)]
    (w,) = obj.warnings
    assert w.code == "shells_inside_out" and w.message.startswith("20 closed shells face outward")


def test_an_open_object_is_only_said_to_be_open():
    """The guard judges shells only when the object is closed: an open one keeps its
    triangles and warns ``not_closed``."""
    from solidseas.export import _object

    pos, tris = _cubes((10.0, (0, 0, 0), True))
    obj = _object("open", None, None, "mesh", pos, tris[:-3], None, [])
    assert not obj.closed and [w.code for w in obj.warnings] == ["not_closed"]
    assert list(obj.triangles) == list(tris[:-3])


def test_a_step_file_exported_carries_the_readers_repairs_not_its_rejudged_checks():
    """A STEP file whose void faced out exports a closed solid of the right volume; the
    scene's own closure checks are judged again on the mesh written, not repeated."""
    import p21_writers as W
    from solidseas.formats import open_model

    f, _ids = W.part_file(lambda f: [W.void_box_brep(f, convention="inward")])
    with open_model(f.bytes(), name="v.step") as doc:
        pm = print_model(doc)
    codes = {w.code for w in pm.warnings}
    assert pm.closed and "void_reoriented" in codes and not codes & {"solids_not_closed", "shells_inside_out"}
    assert pm.measures()["volume_m3"] == pytest.approx(26000e-9, rel=1e-12)


def _double_cone(d: int) -> array:
    """A closed solid every triangle of which shares one of two apexes (0 and 1)."""
    tris = array("I")
    for i in range(d):
        a, b = 2 + i, 2 + (i + 1) % d
        tris.extend((0, a, b, 1, b, a))
    return tris


def test_oriented_closed_takes_a_fan_in_linear_time():
    """A vertex shared by 50,000 triangles: the reverse of each edge was looked for in
    that vertex's whole row, which took 38 s at 80,000 triangles; now a bisection."""
    import time

    cone = _double_cone(50_000)
    t0 = time.perf_counter()
    assert oriented_closed(cone, 50_002)
    assert time.perf_counter() - t0 < 10  # about 0.3 s
    assert not oriented_closed(cone[:-3], 50_002)  # one triangle short
    turned = array("I", cone)
    turned[1], turned[2] = turned[2], turned[1]
    assert not oriented_closed(turned, 50_002)


# --------------------------------------------------------------------------- corners a hair apart
# A tetrahedron 50 mm from the origin, its edge AB split by a vertex E a hair (1e-9 mm)
# from A: two of its six triangles have corners A and E, one point in float32 (whose steps
# are 4e-6 mm there) and in nine digits, though not in float64.
_A = (0.05, 0.05, 0.05)
_TET = [_A, (0.1, 0.05, 0.05), (0.05, 0.1, 0.05), (0.05, 0.05, 0.1), (0.05 + 1e-12, 0.05, 0.05)]
_SPLIT = (2, 1, 4, 2, 4, 0, 3, 0, 4, 3, 4, 1, 1, 2, 3, 2, 0, 3)


def _split_tetra() -> PrintObject:
    pos = array("d", [c for p in _TET for c in p])
    tris = array("I", _SPLIT)
    assert oriented_closed(tris, 5)
    return PrintObject("split", None, None, "bodies", pos, tris, True, 1e-5)


def _tetra_volume() -> float:
    a, b, c, d = _TET[:4]
    u, v, w = ([q[i] - a[i] for i in range(3)] for q in (b, c, d))
    det = (
        u[0] * (v[1] * w[2] - v[2] * w[1])
        - u[1] * (v[0] * w[2] - v[2] * w[0])
        + u[2] * (v[0] * w[1] - v[1] * w[0])
    )
    return abs(det) / 6


def test_corners_a_hair_apart_are_merged_in_the_model():
    from solidseas.export import _object

    raw = _split_tetra()
    obj = _object("t", None, None, "bodies", raw.positions, raw.triangles, 1e-5, [])
    assert obj.n_triangles == 4 and obj.n_vertices == 4 and obj.closed and obj.warnings == ()
    assert obj.measures()["volume_m3"] == pytest.approx(_tetra_volume(), rel=1e-12)


@pytest.mark.parametrize(("fmt", "merge"), [("3mf", False), ("3mf", True), ("stl", False)])
def test_no_written_triangle_has_two_corners_at_one_point(fmt, merge):
    """A model built without the merge (as a caller may build one) still never writes a
    triangle whose corners meet, in a 3MF read as float64 or float32, or in an STL; the
    edge collapse keeps it closed, its volume and its STL count right."""
    m = PrintModel(
        "t", "part", None, (_split_tetra(),), (PrintItem(0, None),), None, {"triangles": 6, "vertices": 5}
    )
    data = export_bytes(m, fmt, merge=merge)
    written = _check_written(data, fmt)  # closed, and no two corners at one point
    assert len(written) == 4 and _measure(written)["volume"] == pytest.approx(_tetra_volume(), rel=1e-6)
    assert all(_area(*tri) > 0 for tri in written)
    if fmt == "stl":  # the count put right, and the same bytes to a stream that cannot seek
        assert struct.unpack_from("<I", data, 80) == (4,) and len(data) == 84 + 50 * 4 < stl_size(m)

        class Stream(io.RawIOBase):
            def __init__(self) -> None:
                self.buf = bytearray()

            def writable(self) -> bool:
                return True

            def write(self, b) -> int:
                self.buf += bytes(b)
                return len(b)

        out = Stream()
        assert write_stl(m, out) == len(data) and bytes(out.buf) == data


def _area(a, b, c) -> float:
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    return math.sqrt(
        (u[1] * v[2] - u[2] * v[1]) ** 2 + (u[2] * v[0] - u[0] * v[2]) ** 2 + (u[0] * v[1] - u[1] * v[0]) ** 2
    )


def test_a_flat_sliver_in_a_solid_is_flipped_away():
    """The tetrahedron with a vertex M 1e-9 mm off the middle of edge AB on one face, the
    gap to the other face closed by a sliver (B, A, M): flat in float32, so in an STL and
    in a slicer, though not in float64. Its long edge AB is flipped with the triangle
    across it, which M then cuts in two: every triangle has area in both formats,
    nothing moved, and the solid is still closed."""
    from solidseas.export import _flat, _object

    pts = [*_TET[:4], (0.075, 0.05 - 1e-12, 0.05)]
    pos = array("d", [c for p in pts for c in p])
    tris = array("I", (2, 1, 4, 2, 4, 0, 1, 0, 4, 0, 1, 3, 1, 2, 3, 2, 0, 3))
    assert oriented_closed(tris, 5)
    mm = array("d", (v * 1000.0 for v in pos))
    assert _flat(mm, array("f", mm), tris) == [6]  # the sliver, flat in float32 only
    obj = _object("sliver", None, None, "bodies", pos, tris, 1e-5, [])
    assert obj.closed and obj.n_triangles == 6 and obj.warnings == ()
    assert _flat(mm, array("f", mm), obj.triangles) == []
    assert obj.measures()["volume_m3"] == pytest.approx(_tetra_volume(), rel=1e-9)
    m = PrintModel("s", "part", None, (obj,), (PrintItem(0, None),), None, {"triangles": 6, "vertices": 5})
    for fmt in FORMATS:
        assert len(_check_written(export_bytes(m, fmt), fmt)) == 6
    # In millimetres as written: the 3MF's float64 and float32 (a slicer), the STL's float32.
    ((_n, verts, tris3),) = read_3mf(export_bytes(m, "3mf"))["objects"].values()
    for view in (lambda p: p, _f32):
        assert all(_area(*(view(verts[i]) for i in tri)) > 0 for tri in tris3)
    assert all(_area(a, b, c) > 0 for _normal, a, b, c in read_stl(export_bytes(m, "stl")))


def test_a_far_placement_merges_corners_float32_cannot_tell_apart():
    """Placed 100 m out, float32 steps are 8e-3 mm: an edge of 1e-3 mm is one point."""
    a = (0.0, 0.0, 0.0)
    pts = [a, (0.01, 0.0, 0.0), (0.0, 0.01, 0.0), (0.0, 0.0, 0.01), (1e-6, 0.0, 0.0)]
    pos = array("d", [c for p in pts for c in p])
    obj = PrintObject("far", None, None, "bodies", pos, array("I", _SPLIT), True, 1e-5)
    far = Placement(IDENTITY.rotation, (100.0, 0.0, 0.0))
    m = PrintModel(
        "far", "assembly", None, (obj,), (PrintItem(0, "x", far),), None, {"triangles": 6, "vertices": 5}
    )
    for fmt, merge in (("stl", False), ("3mf", True)):
        written = _check_written(export_bytes(m, fmt, merge=merge), fmt)
        assert len(written) == 4
    pkg = read_3mf(export_bytes(m, "3mf"))  # in its own frame the edge is kept; the slicer places it
    assert len(pkg["objects"][1][2]) == 6


def test_a_sliver_keeps_its_area_in_a_3mf_and_its_normal_in_an_stl():
    """Its apex 1e-8 mm off its base: nine digits made it flat in a 3MF. float32 makes it
    flat in an STL, which then gives it no normal rather than a wrong one."""
    pos = array("d", [0.01, 0.01, 0.01, 0.06, 0.01, 0.01, 0.035, 0.01 + 1e-11, 0.01])
    obj = PrintObject("sliver", None, None, "bodies", pos, array("I", [0, 1, 2]), False, None)
    m = PrintModel("s", "part", None, (obj,), (PrintItem(0, None),), None, {"triangles": 1, "vertices": 3})
    ((a, b, c),) = _check_written(export_bytes(m, "3mf"), "3mf", solids=False)
    assert _measure([(a, b, c)])["area"] == pytest.approx(0.5 * 0.05 * 1e-11, rel=1e-3)
    ((normal, *_corners),) = read_stl(export_bytes(m, "stl"))
    assert normal == (0.0, 0.0, 0.0)


def test_3mf_numbers_read_back_as_the_same_float64():
    from solidseas.export import _num

    for v in (25.000000001, 0.1 + 0.2, -1e-17, 1e300, 12.0, -0.0, 0.0, 1234567.890123):
        text = _num(v)
        assert NUMBER.fullmatch(text) and float(text) == v and text != "-0", (v, text)


def test_a_mirroring_placement_keeps_the_solid_outward():
    base = _model("o02_boxA.SLDPRT")
    mirror = Placement(((-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (0.1, 0.0, 0.0))
    m = PrintModel(
        "mirrored",
        "assembly",
        None,
        base.objects,
        (PrintItem(0, "a", IDENTITY), PrintItem(0, "b", mirror)),
        None,
        {**base.counts, "items": 2, "triangles": 24},
    )
    for fmt, merge in (("stl", False), ("3mf", False), ("3mf", True)):
        written = _check_written(export_bytes(m, fmt, merge=merge), fmt)
        assert _measure(written)["volume"] == pytest.approx(2 * base.measures()["volume_m3"], rel=1e-9)
    pkg = read_3mf(export_bytes(m, "3mf"))
    assert len(pkg["objects"]) == 2 and pkg["items"][1][1] is None  # written out placed
    assert m.measures()["volume_m3"] == pytest.approx(2 * base.measures()["volume_m3"])


def test_3mf_names_are_escaped_and_numbers_plain():
    base = _model("o02_boxA.SLDPRT")
    obj = base.objects[0]
    odd = PrintObject('a<b>&"c"\x01\ud800', None, None, "bodies", obj.positions, obj.triangles, True, 1e-5)
    m = PrintModel('t"<&>', "part", None, (odd,), (PrintItem(0, None),), None, base.counts)
    pkg = read_3mf(export_bytes(m, "3mf"))
    assert [n for n, _v, _t in pkg["objects"].values()] == ['a<b>&"c"']
    assert pkg["root"].find(f"{CORE}metadata[@name='Title']").text == 't"<&>'


# --------------------------------------------------------------------------- writing safely
def test_write_export_creates_new_files_only(tmp_path):
    m = _model("o02_boxA.SLDPRT")
    out = tmp_path / "box.3mf"
    res = write_export(m, out, "3mf")
    assert res.path == str(out) and res.bytes == out.stat().st_size and res.format == "3mf"
    assert not res.merged and read_3mf(out.read_bytes())
    before = out.read_bytes()
    with pytest.raises(OutputRefusedError) as exc:
        write_export(m, out, "stl")
    assert exc.value.detail["rule"] == "exists" and out.read_bytes() == before
    res = write_export(m, out, "stl", overwrite=True)  # a new file renamed over it
    assert res.merged and read_stl(out.read_bytes()) and sorted(os.listdir(tmp_path)) == ["box.3mf"]
    with pytest.raises(OutputRefusedError):
        write_export(m, tmp_path, "3mf", overwrite=True)  # a folder is never replaced


def test_write_export_stops_at_its_byte_limit_and_leaves_nothing(tmp_path):
    m = _model("o11_curved.SLDPRT")
    for fmt in FORMATS:
        out = tmp_path / f"big.{fmt}"
        with pytest.raises(SldLimitError) as exc:
            write_export(m, out, fmt, max_bytes=2000)
        assert exc.value.detail["limit"] == "max_bytes" and not out.exists()
    out = tmp_path / "kept.stl"
    out.write_bytes(b"theirs")
    with pytest.raises(SldLimitError):
        write_export(m, out, "stl", overwrite=True, max_bytes=2000)
    assert out.read_bytes() == b"theirs" and sorted(os.listdir(tmp_path)) == ["kept.stl"]


def test_write_export_never_follows_a_link(tmp_path):
    m = _model("o02_boxA.SLDPRT")
    target = tmp_path / "elsewhere.3mf"
    target.write_bytes(b"theirs")
    link = tmp_path / "link.3mf"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot make symbolic links")
    for overwrite in (False, True):
        with pytest.raises(OutputRefusedError) as exc:
            write_export(m, link, "3mf", overwrite=overwrite)
        assert exc.value.detail["rule"] == "link"
    assert target.read_bytes() == b"theirs"


def test_bad_options_are_refused(tmp_path):
    with open_document(fixture_path("o02_boxA.SLDPRT")) as doc:
        for bad in (
            {"chord_m": 0},
            {"chord_m": 1.0},
            {"chord_m": True},
            {"angle_deg": 0},
            {"max_triangles": 0},
            {"max_seconds": -1},
            {"name": 3},
        ):
            with pytest.raises(InvalidArgumentError):
                print_model(doc, **bad)
        with pytest.raises(InvalidArgumentError):
            export_document(doc, tmp_path / "x.obj", "obj")
        m = print_model(doc)
    with pytest.raises(InvalidArgumentError):
        write_export(m, tmp_path / "x.3mf", "3mf", max_bytes=0)
    assert not list(tmp_path.iterdir())


def test_limits_stop_a_part_cleanly():
    with open_document(fixture_path("o11_curved.SLDPRT")) as doc:
        with pytest.raises(SldLimitError) as exc:
            print_model(doc, max_triangles=50)
        assert exc.value.detail["limit"] == "max_triangles"
        with pytest.raises(SldLimitError):
            print_model(doc, max_seconds=0)
    # The display mesh a part falls back on is bounded as its bodies are, before it is welded.
    with open_document(_without_bodies("o11_curved.SLDPRT"), name="o11_curved.SLDPRT") as doc:
        with pytest.raises(SldLimitError) as exc:
            print_model(doc, max_triangles=5)
        assert exc.value.detail["limit"] == "max_triangles"
        assert print_model(doc, max_triangles=10_000).objects[0].source == "display_mesh"


@pytest.mark.skipif(os.name != "nt", reason="devices and alternate data streams are Windows'")
def test_write_export_never_writes_a_device_or_a_stream(tmp_path):
    m = _model("o02_boxA.SLDPRT")
    kept = tmp_path / "kept.3mf"
    kept.write_bytes(b"theirs")
    for name, rule in (
        ("nul .x.3mf", "device_path"),  # Windows reads it as NUL, in any folder
        ("COM1 .3mf", "device_path"),
        ("kept.3mf:more", "alternate_stream"),  # would add a stream to a file that is there
    ):
        with pytest.raises(OutputRefusedError) as exc:
            write_export(m, os.path.join(str(tmp_path), name), "3mf")
        assert exc.value.detail["rule"] == rule, name
    with pytest.raises(OutputRefusedError) as exc:
        write_export(m, "\\\\?\\" + str(tmp_path / "long.3mf"), "3mf")
    assert exc.value.detail["rule"] == "device_path"
    assert sorted(os.listdir(tmp_path)) == ["kept.3mf"] and kept.read_bytes() == b"theirs"


def test_export_document_writes_what_print_model_builds(tmp_path):
    with open_document(fixture_path("o08_asm_2x_boxA.SLDASM")) as doc:
        res = export_document(doc, tmp_path / "o08.3mf", "3mf", configuration="Default")
    assert res.model.counts["items"] == 2 and len(read_3mf((tmp_path / "o08.3mf").read_bytes())["items"]) == 2


# --------------------------------------------------------------------------- the command line
def _run(capsys, *argv) -> tuple[int, dict]:
    code = cli.main([*argv, "--json"])
    out = capsys.readouterr()
    assert out.err == ""
    return code, json.loads(out.out)


def test_cli_export_writes_3mf_and_stl(capsys, tmp_path):
    from jsonschema_subset import validate

    part = str(fixture_path("o02_boxA.SLDPRT"))
    out = tmp_path / "box.3mf"
    code, env = _run(capsys, "export", part, "--format", "3mf", "-o", str(out))
    assert code == 0 and env["kind"] == "export_result" and env["source"] == {"file": part}
    data = env["data"]
    assert validate(data, model.KINDS["export_result"].schema, strict=True) == []
    assert data["output"] == str(out) and data["bytes"] == out.stat().st_size and data["format"] == "3mf"
    assert data["closed"] and data["objects"][0]["closed"] and data["objects"][0]["source"] == "bodies"
    assert data["objects"][0]["volume_mm3"] == pytest.approx(6000.0)
    assert read_3mf(out.read_bytes())
    # never over an existing file without --force, then with it
    code, env = _run(capsys, "export", part, "--format", "3mf", "-o", str(out))
    assert (
        code == 3 and env["error"]["code"] == "output_refused" and env["error"]["detail"]["rule"] == "exists"
    )
    code, env = _run(capsys, "export", part, "--format", "3mf", "-o", str(out), "--force", "--chord", "0.005")
    assert code == 0 and env["data"]["chord_mm"] == 0.005
    # a folder as -o: the document's name in it; STL
    code, env = _run(capsys, "export", part, "--format", "stl", "-o", str(tmp_path))
    assert code == 0 and env["data"]["output"] == str(tmp_path / "o02_boxA.stl") and env["data"]["merged"]
    assert read_stl((tmp_path / "o02_boxA.stl").read_bytes())


def test_cli_export_of_an_assembly(capsys, tmp_path):
    from jsonschema_subset import validate

    asm = str(fixture_path("o16_asm_features.SLDASM"))
    code, env = _run(
        capsys, "export", asm, "--format", "3mf", "-o", str(tmp_path / "a.3mf"), "--configuration", "Lite"
    )
    data = env["data"]
    assert code == 0 and data["configuration"] == "Lite" and data["counts"]["items"] == 10
    assert validate(data, model.KINDS["export_result"].schema, strict=True) == []
    code, env = _run(capsys, "export", asm, "--format", "3mf", "-o", str(tmp_path / "m.3mf"), "--merge")
    assert (
        code == 0
        and env["data"]["merged"]
        and len(read_3mf((tmp_path / "m.3mf").read_bytes())["objects"]) == 1
    )


def test_cli_export_guards_and_errors(capsys, tmp_path):
    part = str(fixture_path("o02_boxA.SLDPRT"))
    code, env = _run(capsys, "export", part, "--format", "3mf", "-o", str(FIXTURES / "x.3mf"))
    assert code == 3 and env["error"]["detail"]["rule"] == "source_folder"
    code, env = _run(capsys, "export", part, "--format", "3mf", "-o", str(tmp_path / "x.SLDPRT"))
    assert code == 3 and env["error"]["detail"]["rule"] == "solidworks_file"
    code, env = _run(capsys, "export", part, "--format", "3mf", "-o", str(tmp_path / "x.stl"))
    assert code == 3 and env["error"]["detail"]["rule"] == "output_extension"
    code, env = _run(capsys, "export", part, "--format", "obj", "-o", str(tmp_path / "x.obj"))
    assert code == 2 and env["error"]["code"] == "invalid_argument"
    code, env = _run(capsys, "export", part, "--format", "stl", "--chord", "0", "-o", str(tmp_path / "x.stl"))
    assert code == 2
    code, env = _run(
        capsys, "export", part, "--format", "stl", "--configuration", "Nope", "-o", str(tmp_path / "x.stl")
    )
    assert code == 1 and env["error"]["code"] == "configuration_not_found"
    drawing = str(fixture_path("o18_drw_boxA.SLDDRW"))
    code, env = _run(capsys, "export", drawing, "--format", "stl", "-o", str(tmp_path / "x.stl"))
    assert code == 1 and env["error"]["code"] == "nothing_to_export"
    # A name with no extension that is not a folder is refused, not made Prints.stl.
    code, env = _run(capsys, "export", part, "--format", "stl", "-o", str(tmp_path / "Prints"))
    assert code == 3 and env["error"]["detail"]["rule"] == "output_extension"
    code, env = _run(capsys, "export", part, "--format", "stl", "-o", str(tmp_path / "Prints") + os.sep)
    assert code == 3 and env["error"]["detail"]["rule"] == "output_folder"
    assert not list(tmp_path.iterdir()) and not (FIXTURES / "x.3mf").exists()


def test_cli_export_without_json(capsys, tmp_path):
    out = tmp_path / "box.stl"
    code = cli.main(["export", str(fixture_path("o02_boxA.SLDPRT")), "--format", "stl", "-o", str(out)])
    text = capsys.readouterr().out
    assert code == 0 and "wrote" in text and "12 triangles" in text and str(out) in text


def test_an_instance_placed_absurdly_far_away_is_out_of_range():
    from solidseas.export import _box, _in_range

    obj = _model("o02_boxA.SLDPRT").objects[0]
    near = Placement(IDENTITY.rotation, (1.0, 2.0, 3.0))
    far = Placement(IDENTITY.rotation, (2e6, 0.0, 0.0))  # 2,000 km
    assert _in_range(_box(obj), near) and not _in_range(_box(obj), far)


def test_a_part_of_open_surfaces_only_is_not_printed(monkeypatch):
    """A part whose bodies are all surfaces or wires prints from its display mesh only
    when that mesh is closed; an open one is refused (rule no_solid), as a model file of
    open surfaces only is, since a slicer cannot print it as a solid (o02's solid stands
    in, with only sheets asked for)."""
    from solidseas import export

    real = export._tess_options
    monkeypatch.setattr(export, "_tess_options", lambda *a: {**real(*a), "body_types": ("sheet",)})
    with open_document(fixture_path("o02_boxA.SLDPRT")) as doc:
        m = print_model(doc)  # its display mesh is closed: printed from it, and said
        assert m.objects[0].source == "display_mesh" and m.objects[0].closed
        monkeypatch.setattr(export, "oriented_closed", lambda *a: False)
        with pytest.raises(NothingToExportError) as caught:
            print_model(doc)
    assert caught.value.detail == {"rule": "no_solid"}
