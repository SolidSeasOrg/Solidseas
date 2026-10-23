"""The tessellation of Parasolid bodies (``solidseas.tessellate``) against SOLIDWORKS.

Every fixture part and configuration that stores a body is tessellated and
compared with what SOLIDWORKS reported (``ground_truth.json``): volume and
area within 0.5 percent, the box within the chord tolerance, the centre of
mass within it too, and every solid closed. SOLIDWORKS' own Parasolid exports
of o02, o07, o11 and o12 give the same triangles as the bodies inside the
parts, and its STL and 3MF exports of o02 the same box, area and volume (the
STL's facets the same normals).

Then the ``brep`` mesh source of ``solidseas.geometry``: the fixture assemblies
drawn from their parts' bodies alone land every instance on the box SOLIDWORKS
gave it, and the meshes' volumes and areas add up to the assembly's. A part
without a display mesh (o16's virtual part) is drawn from its bodies by
default; one that stores neither is still a box, with the reason.
"""

import json
import math
import shutil
import struct
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path

import pytest

from builders import build_modern, fixture_streams
from solidseas import geometry as geo
from solidseas import open_document
from solidseas.errors import ConfigurationNotFoundError, InvalidArgumentError
from solidseas.formats.solidworks.parasolid import read_file
from solidseas.tessellate import (
    REASONS,
    SkippedFace,
    Tessellation,
    tessellate_body,
    tessellate_document,
    tessellate_transmit,
)
from support import FIXTURES, fixture_path

GT = json.loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))
O08, O15, O16 = "o08_asm_2x_boxA.SLDASM", "o15_sub_asm.SLDASM", "o16_asm_features.SLDASM"
VIRTUAL = "Part12^o16_asm_features-1"
# Fixture part configurations that store no body: o01 is empty, and o06's OracleAlt has
# no Config-1-Partition (docs/FORMAT.md 10.1).
NO_BODY = {("o01_empty.SLDPRT", "Default"), ("o06_boxA_props_mat_cfg.SLDPRT", "OracleAlt")}
PART_CASES = [
    (name, cfg)
    for name, doc in sorted(GT.items())
    if name.upper().endswith(".SLDPRT")
    for cfg in doc["api"]["configurations"]
]
WITH_BODY = [c for c in PART_CASES if c not in NO_BODY]
ASSEMBLY_CASES = [(O08, "Default"), (O15, "Default"), (O16, "Default"), (O16, "Lite")]
TOL = 1e-6  # metres: the meshes are float32


def _flat(box) -> list[float]:
    return [*box[0], *box[1]]


def _measure(tris) -> dict:
    """Volume, area and box of triangles given as three points each."""
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
        area += 0.5 * math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2)
        pts.extend((a, b, c))
    box = [min(p[i] for p in pts) for i in range(3)] + [max(p[i] for p in pts) for i in range(3)]
    return {"volume": vol, "area": area, "box": box}


def _closed(tris) -> bool:
    edges = Counter()
    for t in tris:
        for k in range(3):
            edges[(t[k], t[(k + 1) % 3])] += 1
    return all(edges.get((b, a), 0) == n for (a, b), n in edges.items())


# --------------------------------------------------------------------------- parts against SOLIDWORKS
def test_the_cases_cover_every_fixture_part():
    assert len(WITH_BODY) == 14 and set(NO_BODY) <= set(PART_CASES)
    assert {n for n, _c in WITH_BODY} >= {"o02_boxA.SLDPRT", "o09_import_step.SLDPRT", "o11_curved.SLDPRT"}


@pytest.mark.parametrize(("name", "configuration"), WITH_BODY)
def test_every_fixture_body_has_solidworks_mass_properties(name, configuration):
    with open_document(fixture_path(name)) as doc:
        t = tessellate_document(doc, configuration)
    g = GT[name]["api"]["configurations"][configuration]
    m = t.measures()
    assert t.configuration == configuration and t.warnings == ()
    assert t.closed is True and t.truncated == () and t.skipped == () and t.reasons == {}
    assert t.counts["faces_done"] == t.counts["faces"] > 0 and t.counts["triangles"] == t.mesh.n_triangles
    assert m["volume"] == pytest.approx(g["volume_m3"], rel=5e-3)
    assert m["area"] == pytest.approx(g["surface_area_m2"], rel=5e-3)
    assert _flat(m["box"]) == pytest.approx(g["bounding_box_m"], abs=max(t.chord_m, 1e-9))
    assert list(m["centroid"]) == pytest.approx(g["center_of_mass_m"], abs=t.chord_m)
    # The display mesh: one FaceTess a face, float32, with its own vertices and normals.
    assert len(t.mesh.faces) == len(t.face_ids) == t.counts["faces_done"]
    assert all(f.offset == -1 and f.has_normals for f in t.mesh.faces)
    assert t.mesh.stream == "brep" and len(t.mesh.normals) == len(t.mesh.positions)
    assert t.mesh.volume() == pytest.approx(g["volume_m3"], rel=5e-3)


def test_the_planar_bodies_are_exact_and_the_curved_ones_within_tenths_of_a_percent():
    exact = [c for c in WITH_BODY if c[0][:3] not in ("o10", "o11")]
    for name, configuration in exact:
        with open_document(fixture_path(name)) as doc:
            t = tessellate_document(doc, configuration)
        g = GT[name]["api"]["configurations"][configuration]
        m = t.measures()
        assert m["volume"] == pytest.approx(g["volume_m3"], rel=1e-9), name
        assert m["area"] == pytest.approx(g["surface_area_m2"], rel=1e-9), name
        assert t.counts["triangles"] == 2 * t.counts["faces"], name  # two triangles a rectangle
    for name, most in (("o10_import_step_cut.SLDPRT", 2e-3), ("o11_curved.SLDPRT", 1e-3)):
        with open_document(fixture_path(name)) as doc:
            t = tessellate_document(doc)
        g = GT[name]["api"]["configurations"]["Default"]
        assert abs(t.measures()["volume"] / g["volume_m3"] - 1) < most, name


@pytest.mark.parametrize(("name", "configuration"), sorted(NO_BODY))
def test_a_configuration_without_bodies_gives_an_empty_result_and_says_why(name, configuration):
    with open_document(fixture_path(name)) as doc:
        t = tessellate_document(doc, configuration)
    assert t.mesh.n_triangles == 0 and t.bodies == () and t.closed is None
    assert [w.code for w in t.warnings] == ["no_stored_bodies"]
    assert configuration in t.warnings[0].message


def test_document_tessellate_is_the_same_call_and_other_documents_give_none():
    with open_document(fixture_path("o11_curved.SLDPRT")) as doc:
        a, b = doc.tessellate(), tessellate_document(doc)
        assert a.configuration == doc.active_configuration == "Default"
    assert a.mesh.positions == b.mesh.positions and a.mesh.triangles == b.mesh.triangles
    for name in (O08, "o18_drw_boxA.SLDDRW"):
        with open_document(fixture_path(name)) as doc:
            assert doc.tessellate() is None and tessellate_document(doc) is None
    with open_document(fixture_path("o13_two_geometry_configs.SLDPRT")) as doc:
        tall = doc.tessellate("tall")  # names match as configuration() matches them
        assert tall.configuration == "Tall" and tall.measures()["box"][1][2] == pytest.approx(0.045)
        with pytest.raises(ConfigurationNotFoundError):
            doc.tessellate("Nope")


def test_solidworks_parasolid_exports_give_the_same_triangles():
    """SOLIDWORKS' own .x_b of a part is the same B-rep as the body inside the part
    (docs/FORMAT.md 10.4), so its triangles are the same too; o12's export holds both
    bodies in one transmit."""
    for xb, part in (
        ("o02_boxA.x_b", "o02_boxA.SLDPRT"),
        ("o07_boxB_h31.x_b", "o07_boxB_h31.SLDPRT"),
        ("o11_curved.x_b", "o11_curved.SLDPRT"),
        ("o12_multibody.x_b", "o12_multibody.SLDPRT"),
    ):
        x = tessellate_transmit(read_file((FIXTURES / xb).read_bytes()))
        with open_document(fixture_path(part)) as doc:
            t = tessellate_document(doc)
        mx, mt = x.measures(), t.measures()
        assert x.closed is True and x.counts["triangles"] == t.counts["triangles"], xb
        assert mx["volume"] == pytest.approx(mt["volume"], rel=1e-6), xb
        assert mx["area"] == pytest.approx(mt["area"], rel=1e-6), xb
    assert len(x.bodies) == 2 and x.bodies == ("body#1", "body#2")


def _stl(path: Path) -> list[tuple]:
    data = path.read_bytes()
    (n,) = struct.unpack_from("<I", data, 80)
    out = []
    for k in range(n):
        f = struct.unpack_from("<12f", data, 84 + 50 * k)
        out.append(
            (
                f[0:3],
                tuple(x / 1000 for x in f[3:6]),
                tuple(x / 1000 for x in f[6:9]),
                tuple(x / 1000 for x in f[9:12]),
            )
        )
    return out


def _3mf(path: Path) -> list[tuple]:
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("3D/3dmodel.model"))
    ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    scale = {"millimeter": 1e-3, "meter": 1.0}[root.get("unit", "millimeter")]
    verts = [
        tuple(float(v.get(a)) * scale for a in "xyz") for v in root.iterfind(".//m:vertices/m:vertex", ns)
    ]
    return [
        tuple(verts[int(t.get(a))] for a in ("v1", "v2", "v3"))
        for t in root.iterfind(".//m:triangles/m:triangle", ns)
    ]


def test_solidworks_stl_and_3mf_exports_agree_with_the_triangles():
    with open_document(fixture_path("o02_boxA.SLDPRT")) as doc:
        t = tessellate_document(doc)
    pos, tris = t.welded()
    ours = [
        tuple(tuple(pos[3 * tris[k + j] : 3 * tris[k + j] + 3]) for j in range(3))
        for k in range(0, len(tris), 3)
    ]
    assert _closed([tuple(tris[k : k + 3]) for k in range(0, len(tris), 3)])
    mine = _measure(ours)
    stl = _stl(FIXTURES / "o02_boxA.STL")
    for other in ([f[1:] for f in stl], _3mf(FIXTURES / "o02_boxA.3mf")):
        theirs = _measure(other)
        assert theirs["volume"] == pytest.approx(mine["volume"], rel=1e-6)
        assert theirs["area"] == pytest.approx(mine["area"], rel=1e-6)
        assert theirs["box"] == pytest.approx(mine["box"], abs=1e-9)

    # The same facet normals, as a multiset: the same faces, each split in two.
    def normal(a, b, c):
        u = [b[i] - a[i] for i in range(3)]
        v = [c[i] - a[i] for i in range(3)]
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        ln = math.sqrt(sum(x * x for x in n))
        return tuple(round(x / ln, 6) + 0.0 for x in n)

    assert Counter(normal(*tri) for tri in ours) == Counter(
        tuple(round(x, 6) + 0.0 for x in f[0]) for f in stl
    )


def test_normals_point_out_and_the_shared_vertices_close_the_solid():
    with open_document(fixture_path("o11_curved.SLDPRT")) as doc:
        t = tessellate_document(doc)
    m = t.mesh
    for f in m.faces:
        for k in range(f.first_triangle, f.first_triangle + f.n_triangles):
            a, b, c = (m.triangles[3 * k + j] for j in range(3))
            pa, pb, pc = m.vertex(a), m.vertex(b), m.vertex(c)
            u = [pb[i] - pa[i] for i in range(3)]
            v = [pc[i] - pa[i] for i in range(3)]
            tn = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            for i in (a, b, c):
                n = m.normals[3 * i : 3 * i + 3]
                assert abs(math.sqrt(sum(x * x for x in n)) - 1) < 1e-5
                assert sum(x * y for x, y in zip(n, tn, strict=True)) > 0
    pos, tris = t.welded()
    assert _closed([tuple(tris[k : k + 3]) for k in range(0, len(tris), 3)])
    assert len(pos) // 3 < m.n_vertices  # shared: each edge's samples are one set of points
    # The per-face mesh is not welded: each face has vertices of its own.
    assert not _closed([tuple(m.triangles[k : k + 3]) for k in range(0, len(m.triangles), 3)])


def test_a_finer_chord_gives_more_triangles_and_closer_mass_properties():
    g = GT["o11_curved.SLDPRT"]["api"]["configurations"]["Default"]
    with open_document(fixture_path("o11_curved.SLDPRT")) as doc:
        coarse = tessellate_document(doc, chord_m=1e-4, angle_deg=30)
        default = tessellate_document(doc)
        fine = tessellate_document(doc, chord_m=1e-6, angle_deg=5)
    assert coarse.counts["triangles"] < default.counts["triangles"] < fine.counts["triangles"]
    errs = [abs(t.measures()["volume"] / g["volume_m3"] - 1) for t in (coarse, default, fine)]
    assert errs[0] > errs[1] > errs[2] and errs[2] < 1e-4
    assert default.chord_m == pytest.approx(1e-3 * math.dist((0, 0, 0), (0.04, 0.03, 0.01)))
    assert fine.chord_m == 1e-6 and fine.angle_deg == 5


def test_bad_options_are_refused():
    with open_document(fixture_path("o02_boxA.SLDPRT")) as doc:
        for bad in (
            {"chord_m": 0},
            {"chord_m": -1e-3},
            {"chord_m": float("nan")},
            {"chord_m": True},
            {"angle_deg": 0},
            {"angle_deg": 120},
            {"max_faces": -1},
            {"max_triangles": 1.5},
            {"max_face_points": 3},
            {"max_edge_points": 1},
            {"max_seconds": -1},
            {"body_types": "solid"},
        ):
            with pytest.raises(InvalidArgumentError):
                tessellate_document(doc, **bad)
        with pytest.raises(TypeError):
            tessellate_document(doc, unknown_option=1)
    with pytest.raises(InvalidArgumentError):
        tessellate_transmit(b"PS")
    with pytest.raises(InvalidArgumentError):
        tessellate_body("body")


def test_limits_stop_cleanly_and_say_so():
    with open_document(fixture_path("o11_curved.SLDPRT")) as doc:
        few = tessellate_document(doc, max_triangles=100)
        faces = tessellate_document(doc, max_faces=3)
        late = tessellate_document(doc, max_seconds=0)
        bodies = doc.parasolid().bodies
    assert few.truncated == ("max_triangles",) and few.counts["triangles"] <= 100 and few.closed is False
    assert (
        faces.truncated == ("max_faces",) and faces.counts["faces"] == 3 and faces.counts["faces_done"] == 3
    )
    assert late.truncated == ("max_seconds",) and late.counts["triangles"] == 0
    assert few.mesh.n_triangles == few.counts["triangles"] == len(few.welded()[1]) // 3
    t = tessellate_body(bodies[0])
    assert isinstance(t, Tessellation) and t.bodies == ("Config-0/body1",) and t.closed is True
    assert {k for k, _f in t.face_ids} == {0}
    # wires and general bodies are left out unless asked for
    assert tessellate_body(bodies[0], body_types=("sheet",)).counts["bodies_left_out"] == 1


def test_skipped_faces_and_reasons_are_documented():
    s = SkippedFace("body", 7, "BLENDED_EDGE", "unsupported_surface", "BLENDED_EDGE")
    assert s.reason in REASONS and all(isinstance(v, str) and v for v in REASONS.values())


# --------------------------------------------------------------------------- the brep mesh source
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
def test_assemblies_drawn_from_their_parts_bodies_alone(name, configuration):
    """Every instance of the fixture assemblies is drawn from its part's bodies, on the
    box SOLIDWORKS gave it, and the meshes' volumes and areas add up to the assembly's
    mass properties: o16 holds a part imported from STEP (its body a local body), a
    virtual part stored inside it, a pattern, and o06 in OracleAlt, which stores no
    bodies of its own and is drawn from its active configuration with a warning."""
    with open_document(fixture_path(name)) as doc:
        g = geo.display_geometry(doc, configuration, sources=("brep",), allow_outside_roots=False)
    expected = _drawn(name, configuration)
    placed = {i.id: i for i in g.instances}
    assert set(placed) == set(expected) and g.skipped == () and g.truncated == ()
    assert all(m.kind == "brep" for m in g.meshes.values())
    assert g.counts["meshes_tessellated"] == len(g.meshes) and g.counts["brep_seconds"] > 0
    vol = area = 0.0
    for iid, inst in placed.items():
        assert _flat(g.bounds(inst, exact=True)) == pytest.approx(expected[iid], abs=TOL), iid
        mesh = g.meshes[inst.mesh].mesh
        vol += mesh.volume()
        area += mesh.area()
    a = GT[name]["api"]["configurations"][configuration]
    assert vol == pytest.approx(a["volume_m3"], rel=5e-3)
    assert area == pytest.approx(a["surface_area_m2"], rel=5e-3)
    if name == O16:
        virtual = g.meshes[placed[VIRTUAL].mesh]
        assert virtual.nested == ("VirtualComp/Part12-sldprt",) and virtual.path is None
        assert virtual.stream == "Contents/Config-0-Partition"
        local = g.meshes[placed["o09_import_step-1"].mesh]
        assert local.stream.endswith("FeatureBodies/LocalBodies")
        if configuration == "Default":
            alt = g.meshes[placed["o06_boxA_props_mat_cfg-1"].mesh]
            assert alt.configuration == "Default"
            assert [w.code for w in alt.warnings] == ["mesh_configuration_differs"]


def test_a_part_without_a_display_mesh_is_drawn_from_its_bodies_by_default():
    """o16's virtual part stores no display mesh: the assembly's own meshes have it, and
    without them the brep source, last in the order, draws it from its bodies."""
    folder_streams = fixture_streams(fixture_path(O16))
    drop = tuple(n for n in folder_streams if n.startswith("FaceTessellations/"))
    data = build_modern({n: d for n, d in folder_streams.items() if n not in drop})
    with open_document(data) as doc:
        g = geo.display_geometry(doc, roots={"fixtures": str(FIXTURES)}, allow_outside_roots=False)
        kinds = {i.id: g.meshes[i.mesh].kind for i in g.instances}
        assert kinds[VIRTUAL] == "brep" and set(kinds.values()) == {"file", "brep"}
        assert g.skipped == () and g.counts["meshes_tessellated"] == 1
        stored = geo.display_geometry(
            doc, roots={"fixtures": str(FIXTURES)}, allow_outside_roots=False, sources=geo.SOURCES[:4]
        )
        assert {(s.id, s.reason) for s in stored.skipped} == {(VIRTUAL, "no_mesh")}
        assert geo.SOURCES[-1] == "brep" and len(geo.SOURCES) == 5


def test_a_part_with_neither_mesh_nor_bodies_is_skipped_with_the_reason(tmp_path):
    folder = tmp_path / "jobs"
    folder.mkdir()
    shutil.copy2(fixture_path(O08), folder / O08)
    part = {n: d for n, d in fixture_streams(fixture_path("o02_boxA.SLDPRT")).items()}
    bare = {n: d for n, d in part.items() if n != "Contents/DisplayLists" and "-Partition" not in n}
    (folder / "o02_boxA.SLDPRT").write_bytes(build_modern(bare))
    with open_document(folder / O08) as doc:
        g = geo.display_geometry(doc, sources=("file", "brep"), allow_outside_roots=False)
    assert g.instances == () and {s.reason for s in g.skipped} == {"no_mesh"}
    assert {s.message for s in g.skipped} == {geo.NO_MESH_NOR_BODIES}
    # Its identity read, then one read: the brep source used the document the file source opened.
    assert g.counts["files_opened"] == 2
    assert all(s.box is not None for s in g.skipped)


def test_the_brep_source_keeps_to_its_limits(tmp_path):
    folder = tmp_path / "jobs"
    folder.mkdir()
    shutil.copy2(fixture_path(O08), folder / O08)
    part = fixture_streams(fixture_path("o11_curved.SLDPRT"))
    (folder / "o02_boxA.SLDPRT").write_bytes(
        build_modern({n: d for n, d in part.items() if n != "Contents/DisplayLists"})
    )
    here = {"sources": ("brep",), "allow_outside_roots": False}
    with open_document(folder / O08) as doc:
        whole = geo.display_geometry(doc, **here)
        timed = geo.display_geometry(doc, max_brep_seconds=0, **here)
        tris = geo.display_geometry(doc, max_triangles=50, **here)
        small = geo.display_geometry(doc, max_bytes=100, **here)
        files = geo.display_geometry(doc, max_files=0, **here)
        with pytest.raises(InvalidArgumentError):
            geo.display_geometry(doc, max_brep_seconds=-1)
    assert len(whole.instances) == 2 and len(whole.meshes) == 1  # one tessellation for both
    (mesh,) = whole.meshes.values()
    assert mesh.kind == "brep" and mesh.triangles > 1000 and mesh.warnings == ()
    for g, reason in (
        (timed, "max_brep_seconds"),
        (tris, "max_triangles"),
        (small, "max_bytes"),
        (files, "max_files"),
    ):
        assert g.instances == () and {s.reason for s in g.skipped} == {reason}, reason
        assert g.truncated == (reason,), reason
    assert tris.counts["triangles_read"] == 0 and small.counts["bytes_read"] <= 100


def test_the_brep_time_limits_count_reading_the_bodies(tmp_path, monkeypatch):
    """A part's time runs from the start of reading its bodies: when the read alone
    outlasts what is left of max_brep_seconds, the part is not tessellated after it, and
    the call runs past the limit by that one read at most."""
    import solidseas.tessellate as tess

    folder = tmp_path / "jobs"
    folder.mkdir()
    shutil.copy2(fixture_path(O08), folder / O08)
    part = fixture_streams(fixture_path("o11_curved.SLDPRT"))
    (folder / "o02_boxA.SLDPRT").write_bytes(
        build_modern({n: d for n, d in part.items() if n != "Contents/DisplayLists"})
    )
    real = tess.bodies_of

    def slow(*args, **kwargs):
        time.sleep(0.4)
        return real(*args, **kwargs)

    monkeypatch.setattr(tess, "bodies_of", slow)
    with open_document(folder / O08) as doc:
        g = geo.display_geometry(doc, sources=("brep",), allow_outside_roots=False, max_brep_seconds=0.2)
    assert g.counts["meshes_tessellated"] == 0 and g.instances == ()
    assert {s.reason for s in g.skipped} == {"max_brep_seconds"} and g.truncated == ("max_brep_seconds",)
    assert 0.4 <= g.counts["brep_seconds"] < 0.2 + 0.4 + 0.3


def _count_copies(monkeypatch) -> list:
    """Look at the time on every tick, and record each partition copied into parts: a
    read stopped while it parsed copies none."""
    from solidseas.formats.solidworks import parasolid as ps
    from solidseas.tessellate.topology import Clock

    monkeypatch.setattr(Clock, "EVERY", 1)
    copied: list = []
    real = ps.partition_to_parts

    def copy(px, **kwargs):
        copied.append(px)
        return real(px, **kwargs)

    monkeypatch.setattr(ps, "partition_to_parts", copy)
    return copied


def test_reading_the_bodies_stops_at_the_time_limit(monkeypatch):
    """max_seconds counts reading the bodies, and a read the time runs out in stops
    there rather than running to its end: nothing is tessellated, and the result names
    the limit."""
    copied = _count_copies(monkeypatch)
    with open_document(fixture_path("o11_curved.SLDPRT")) as doc:
        t = tessellate_document(doc, max_seconds=0.0, detail=True)
        assert copied == []
        whole = tessellate_document(doc)
    assert len(copied) == 1 and whole.truncated == () and whole.mesh.n_triangles > 1000
    assert t.truncated == ("max_seconds",) and t.mesh.n_triangles == 0 and t.face_ids == ()
    assert t.counts == dict.fromkeys(t.counts, 0) and t.configuration == whole.configuration
    assert t.detail is not None and t.detail.edges == {} and t.closed is False


def test_the_brep_source_stops_reading_a_part_at_its_deadline(tmp_path, monkeypatch):
    """The part's time bounds the read of its bodies too: the part's own (brep_failed)
    or, when what was left of max_brep_seconds cut it short, the call's."""
    folder = tmp_path / "jobs"
    folder.mkdir()
    shutil.copy2(fixture_path(O08), folder / O08)
    part = fixture_streams(fixture_path("o11_curved.SLDPRT"))
    (folder / "o02_boxA.SLDPRT").write_bytes(
        build_modern({n: d for n, d in part.items() if n != "Contents/DisplayLists"})
    )
    copied = _count_copies(monkeypatch)
    here = {"sources": ("brep",), "allow_outside_roots": False}
    with open_document(folder / O08) as doc:
        own = geo.display_geometry(doc, brep_options={"max_seconds": 0.0}, **here)
        call = geo.display_geometry(doc, max_brep_seconds=1e-9, **here)
        assert copied == []
        whole = geo.display_geometry(doc, **here)
    assert {(s.reason, s.message) for s in own.skipped} == {
        ("brep_failed", "reading its bodies took longer than 0 s")
    }
    assert own.truncated == () and own.counts["meshes_tessellated"] == 0
    assert {s.reason for s in call.skipped} == {"max_brep_seconds"}
    assert call.truncated == ("max_brep_seconds",)
    assert len(whole.instances) == 2 and len(copied) == 1


def test_a_part_that_runs_out_of_memory_is_skipped_and_the_rest_drawn(monkeypatch):
    """A MemoryError while one part's bodies are read or tessellated costs that part,
    as brep_failed, and not the whole assembly: the other parts are still drawn."""
    import solidseas.tessellate as tess

    here = {"sources": ("brep",), "allow_outside_roots": False}
    with open_document(fixture_path(O16)) as doc:
        whole = geo.display_geometry(doc, **here)
        real = tess._run
        calls = []

        def run(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise MemoryError
            return real(*args, **kwargs)

        monkeypatch.setattr(tess, "_run", run)
        g = geo.display_geometry(doc, **here)
    assert len(calls) == len(whole.meshes) and g.counts["meshes_tessellated"] == len(whole.meshes) - 1
    assert {(s.reason, s.message) for s in g.skipped} == {
        ("brep_failed", "reading or tessellating its bodies ran out of memory")
    }
    assert g.instances and len(g.instances) + len(g.skipped) == len(whole.instances)
    assert g.truncated == ()
