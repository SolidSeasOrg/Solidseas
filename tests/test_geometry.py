"""An assembly's display geometry (``solidseas.geometry``) against what SOLIDWORKS reported.

``ground_truth.json`` holds, for every instance of the fixture assemblies o08,
o15 and o16 in each configuration, the box SOLIDWORKS gave for it in the top
assembly's frame (``Component2.GetBox``), and each configuration's own box.
Every placed instance's box, from its mesh and its placement, must equal
SOLIDWORKS' box: rotations of 90 degrees about X and about Z, a sub-assembly
turned 40 degrees about (1, 1, 1) and the parts inside it, and o16's Lite
configuration, which suppresses that sub-assembly. Both ways of getting a
mesh are checked: the meshes the assembly stores (``FaceTessellations``) and the
parts' own files, found by reference resolution in a moved copy of the folder.

Crafted trees check what a document can do to the expansion and the reads: a
sub-assembly that contains itself, a million instances, missing files, a
junction inside the folder searched, files over the limits, and the older
layout that keeps component meshes in the assembly's own display lists.
Nothing in a folder read is ever changed.
"""

import hashlib
import json
import os
import shutil
import struct
import sys
import time
from pathlib import Path

import pytest

from builders import TreeXml, assembly_with_tree, fixture_streams, rebuild, resolving_assembly
from solidseas import Root, Roots, open_document
from solidseas import geometry as geo
from solidseas.errors import InvalidArgumentError
from solidseas.formats.solidworks import facetess
from solidseas.formats.solidworks.mesh import parse_tess_tables
from solidseas.resolve import gateway as gateway_mod
from support import FIXTURES, fixture_path

WINDOWS = sys.platform == "win32"
GT = json.loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))
O08, O15, O16 = "o08_asm_2x_boxA.SLDASM", "o15_sub_asm.SLDASM", "o16_asm_features.SLDASM"
TOL = 1e-6  # metres: the meshes are float32, SOLIDWORKS' boxes float64
CASES = [(O08, "Default"), (O15, "Default"), (O16, "Default"), (O16, "Lite")]


def _state(folder: Path) -> dict[str, tuple[str, int]]:
    return {
        str(p.relative_to(folder)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def _components(name: str, configuration: str) -> list[dict]:
    return GT[name]["api"]["configurations"][configuration]["components"]


def _drawn(name: str, configuration: str) -> dict[str, list[float]]:
    """SOLIDWORKS' box of every part instance it would draw: unsuppressed, with no
    suppressed parent, visible."""
    comps = {c["name"]: c for c in _components(name, configuration)}

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


def _flat(box) -> list[float]:
    return [*box[0], *box[1]]


def _union(boxes):
    boxes = [b for b in boxes if b is not None]
    return (
        tuple(min(b[0][i] for b in boxes) for i in range(3)),
        tuple(max(b[1][i] for b in boxes) for i in range(3)),
    )


def _corners_box(place, box):
    lo, hi = box
    pts = [place.apply((x, y, z)) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    return _union([(p, p) for p in pts])


@pytest.fixture(scope="module")
def moved(tmp_path_factory) -> Path:
    """The fixture documents copied to a new folder: every stored path is stale, so each
    part file must be found by reference resolution."""
    folder = tmp_path_factory.mktemp("moved") / "Elsewhere"
    folder.mkdir()
    for p in FIXTURES.iterdir():
        if p.suffix.upper() in (".SLDPRT", ".SLDASM"):
            shutil.copy2(p, folder / p.name)
    return folder


# --------------------------------------------------------------------------- against SOLIDWORKS
@pytest.mark.parametrize(("name", "configuration"), CASES)
@pytest.mark.parametrize("sources", [geo.SOURCES, ("file",)], ids=["assembly_first", "files_only"])
def test_every_placed_instance_has_the_box_solidworks_gave_it(name, configuration, sources, moved):
    before = _state(moved)
    with open_document(moved / name) as doc:
        g = geo.display_geometry(doc, configuration, sources=sources)
    expected = _drawn(name, configuration)
    placed = {i.id: i for i in g.instances}
    virtual = {"Part12^o16_asm_features-1"}  # stores no display mesh of its own: only the assembly has one
    if sources == ("file",):
        assert set(placed) == set(expected) - virtual
        assert {(s.id, s.reason) for s in g.skipped} == ({(*virtual, "no_source")} if name == O16 else set())
        assert all(m.kind == "file" for m in g.meshes.values())
    else:
        assert set(placed) == set(expected) and g.skipped == ()
        assert all(
            m.kind == "assembly" and m.stream.startswith("FaceTessellations/") for m in g.meshes.values()
        )
        assert g.counts["files_opened"] == 0  # everything came from the assembly itself
    for iid, inst in placed.items():
        assert _flat(g.bounds(inst, exact=True)) == pytest.approx(expected[iid], abs=TOL), iid
    assert g.configuration == configuration
    assert _state(moved) == before


def test_rotated_instances_land_where_solidworks_put_them():
    with open_document(fixture_path(O16)) as doc:
        g = geo.display_geometry(doc)
    by_id = {i.id: i for i in g.instances}
    # o02_boxA-2: turned +90 degrees about Z, at (100, 0, 0) mm; its 10 x 20 mm footprint becomes 20 x 10
    assert _flat(g.bounds(by_id["o02_boxA-2"], exact=True)) == pytest.approx(
        [0.08, 0, 0, 0.1, 0.01, 0.03], abs=TOL
    )
    # inside the sub-assembly turned 40 degrees about (1, 1, 1): o07 turned +90 degrees about X there
    inner = by_id["o15_sub_asm-1/o07_boxB_h31-1"]
    assert _flat(g.bounds(inner, exact=True)) == pytest.approx(
        _components(O16, "Default")[10]["box_m"], abs=TOL
    )
    assert inner.matrix()[12:15] == pytest.approx(inner.placement.translation_m)
    with open_document(fixture_path(O15)) as doc:
        g15 = geo.display_geometry(doc)
    (o07,) = [i for i in g15.instances if i.id == "o07_boxB_h31-1"]
    assert _flat(g15.bounds(o07, exact=True)) == pytest.approx([0.03, -0.031, 0, 0.04, 0, 0.02], abs=TOL)


@pytest.mark.parametrize(("name", "configuration"), CASES)
def test_the_assembly_box_is_solidworks_box(name, configuration):
    """SOLIDWORKS' box of a sub-assembly is its own box carried into the top frame, so
    looser than its parts' boxes once it is turned; the assembly's box is the union of
    its top-level components' boxes, built here the same way from the meshes."""
    with open_document(fixture_path(name)) as doc:
        g = geo.display_geometry(doc, configuration)
        tree = doc.components(configuration)
        md = doc.metadata.tree
    by_id = {i.id: i for i in g.instances}

    def own_box(node):
        """The node's box in its own frame, from its meshes (None when nothing is drawn)."""
        if node.children:
            boxes = [_corners_box(c.transform, b) for c in node.children if (b := own_box(c)) is not None]
            return _union(boxes) if boxes else None
        inst = by_id.get(node.id)
        return g.meshes[inst.mesh].mesh.bbox() if inst else None

    tops = {n.id: n for n in tree.children}
    boxes = {}
    for nid, n in tops.items():
        b = own_box(n)
        if b is not None and not n.suppressed:
            boxes[nid] = _corners_box(n.placement, b)
    gt = {c["name"]: c["box_m"] for c in _components(name, configuration)}
    for nid, b in boxes.items():
        assert _flat(b) == pytest.approx(gt[nid], abs=TOL), nid
    whole = GT[name]["api"]["configurations"][configuration]["bounding_box_m"]
    assert _flat(_union(boxes.values())) == pytest.approx(whole, abs=TOL)
    exact = g.bbox(exact=True)
    if (name, configuration) == (O16, "Default"):  # the turned sub-assembly's box is looser than its parts'
        assert _flat(exact) != pytest.approx(whole, abs=TOL)
        assert all(whole[i] - TOL <= exact[0][i] and exact[1][i] <= whole[3 + i] + TOL for i in range(3))
    else:
        assert _flat(exact) == pytest.approx(whole, abs=TOL)
    # The box the file stores for the configuration: right for the configuration active at
    # save, and for o16's Lite a copy of Default's (Lite suppresses the turned sub-assembly).
    stored = {c["name"]: md["models"][c["model_ref"]]["bbox"] for c in md["configs"]}
    stored_box = [float(v) for v in stored[configuration].split()]
    if (name, configuration) == (O16, "Lite"):
        assert stored_box == pytest.approx(
            GT[O16]["api"]["configurations"]["Default"]["bounding_box_m"], abs=TOL
        )
        assert stored_box != pytest.approx(whole, abs=TOL)
    else:
        assert stored_box == pytest.approx(whole, abs=TOL)


def test_one_mesh_serves_every_instance_of_a_file():
    with open_document(fixture_path(O16)) as doc:
        g = geo.display_geometry(doc)
    by_id = {i.id: i for i in g.instances}
    o02 = {by_id[i].mesh for i in ("o02_boxA-1", "o02_boxA-2", "o02_boxA-3", "o15_sub_asm-1/o02_boxA-1")}
    o07 = {
        by_id[i].mesh
        for i in ("o07_boxB_h31-2", "o07_boxB_h31-3", "o07_boxB_h31-4", "o15_sub_asm-1/o07_boxB_h31-1")
    }
    assert len(o02) == len(o07) == 1 and o02 != o07
    assert g.counts | {"bytes_read": 0} == {
        "instances": 14,
        "parts": 13,
        "placed": 12,
        "suppressed": 1,
        "hidden": 0,
        "skipped": 0,
        "meshes": 6,
        "triangles_read": 72,
        "triangles_drawn": 144,
        "files_opened": 0,
        "bytes_read": 0,
        "meshes_tessellated": 0,
        "brep_seconds": 0.0,
    }
    # The configuration each mesh shows is the one its instances use: o06 in OracleAlt.
    assert g.meshes[by_id["o06_boxA_props_mat_cfg-1"].mesh].configuration == "OracleAlt"


def test_a_part_file_mesh_of_another_configuration_says_so(moved):
    with open_document(moved / O16) as doc:
        g = geo.display_geometry(doc, sources=("file",))
    (o06,) = [
        m for m in g.meshes.values() if m.file and m.path and m.path.endswith("o06_boxA_props_mat_cfg.SLDPRT")
    ]
    assert o06.configuration == "Default" and [w.code for w in o06.warnings] == ["mesh_configuration_differs"]
    assert "'OracleAlt'" in o06.warnings[0].message
    assert all(not m.warnings for m in g.meshes.values() if m is not o06)


def test_the_assemblys_meshes_are_the_part_files_meshes():
    """The mesh o08 stores for o02_boxA is the one o02_boxA.SLDPRT stores, triangle for
    triangle (the corpus agrees less often: parts change after the assembly is saved)."""
    with open_document(fixture_path(O08)) as doc:
        (m,) = geo.display_geometry(doc).meshes.values()
    with open_document(fixture_path("o02_boxA.SLDPRT")) as part:
        own = part.mesh()

    def triangles(mesh):
        return sorted(tuple(sorted(t)) for t in mesh.iter_triangles())

    assert triangles(m.mesh) == triangles(own)


def test_a_part_or_a_drawing_has_no_display_geometry():
    for name in ("o02_boxA.SLDPRT", "o18_drw_boxA.SLDDRW"):
        with open_document(fixture_path(name)) as doc:
            assert geo.display_geometry(doc) is None and doc.display_geometry() is None


def test_an_assembly_read_from_bytes_needs_no_folder_for_its_own_meshes():
    with open_document(fixture_path(O16).read_bytes(), name=O16) as doc:
        g = geo.display_geometry(doc)
        assert g.counts["placed"] == 12 and g.skipped == ()
        files = geo.display_geometry(doc, sources=("file",))
    assert files.instances == () and {s.reason for s in files.skipped} <= {"missing", "no_source"}
    assert any("no roots were given" in s.message for s in files.skipped)


# --------------------------------------------------------------------------- FaceTessellations
def test_the_directory_maps_every_instance_to_a_block():
    with open_document(fixture_path(O16)) as doc:
        d = facetess.read_directory(doc.container)
        data = doc.read_stream("FaceTessellations/000-000-002")
    assert (d.version, d.last_stream, len(d.records)) == (2, 2, 15)
    assert [r.number for r in d.records] == [n for n in range(1, 17) if n != 5]  # 5: the sub-assembly itself
    paths = {r.path: r for r in d.records}
    assert ("o15_sub_asm-1", "o02_boxA-1") in paths and ("o17_деталь-1",) in paths
    shared = paths[("o15_sub_asm-1", "o02_boxA-1")]
    assert shared.stream is None and d.mesh_record(shared) is paths[("o02_boxA-1",)]
    assert d.mesh_record(paths[("o07_boxB_h31-1",)]) is None  # suppressed: no mesh
    own = [r for r in d.records if r.stream]
    assert sorted(r.block for r in own) == list(range(6))
    ranges = facetess.block_ranges(data, own)
    assert ranges[0][0] == 0 and sorted(ranges) == list(range(6))
    for start, end, faces in ranges.values():
        assert sum(1 for t in parse_tess_tables(data) if start <= t["off"] < end) == faces == 6


def test_blocks_a_stream_lacks_cost_time_in_proportion_to_the_stream(tmp_path):
    """o16 with a thousand more directory records, each naming a block its stream does
    not hold, and that stream padded with 32 MiB of zeros. Each missing block sent a
    search to the stream's end, so the read took the stream's size times the records
    (47 s here before); the searches now stop at a few times the stream's size, and the
    twelve real instances are still drawn from their blocks."""
    streams = fixture_streams(fixture_path(O16))
    d = streams["FaceTessellations/Directory"]
    version, last, n = struct.unpack_from("<III", d, 0)
    extra = bytearray()
    for i in range(1000):
        rid = struct.pack("<Q", 0x7777000000000000 + i)
        extra += struct.pack("<I", 1000 + i) + _cstring("") + struct.pack("<H", 0) + bytes(10)
        extra += bytes(8) + rid + _cstring("000-000-002") + struct.pack("<iI", 100 + i, 0)
    directory = struct.pack("<III", version, last, n + 1000) + d[12:] + bytes(extra)
    assert facetess.parse_directory(directory) is not None
    stream = streams["FaceTessellations/000-000-002"] + bytes(32 << 20)
    path = tmp_path / O16
    path.write_bytes(
        rebuild(
            fixture_path(O16),
            {"FaceTessellations/Directory": directory, "FaceTessellations/000-000-002": stream},
        )
    )
    with open_document(path) as doc:
        start = time.perf_counter()
        g = geo.display_geometry(doc)
        took = time.perf_counter() - start
    assert g.counts["placed"] == 12 and g.skipped == ()
    assert took < 10, took
    # The bound itself: every search counted, a stream of zeros and a thousand missing blocks.
    records = facetess.parse_directory(directory).records
    searched = []
    real_find = bytes.find

    class Counting(bytes):
        def find(self, sub, start=0, end=None):
            end = len(self) if end is None else end
            searched.append(end - start)
            return real_find(self, sub, start, end)

    zeros = Counting(bytes(4 << 20))
    assert facetess.block_ranges(zeros, [r for r in records if r.stream]) == {}
    assert sum(searched) <= facetess.SEARCH_FACTOR * len(zeros) + facetess.SEARCH_SLACK


def test_a_damaged_directory_is_no_directory():
    with open_document(fixture_path(O16)) as doc:
        raw = doc.read_stream("FaceTessellations/Directory")
    assert facetess.parse_directory(raw) is not None
    for cut in range(len(raw)):
        assert facetess.parse_directory(raw[:cut]) is None
    assert facetess.parse_directory(raw + b"\0") is None
    huge = struct.pack("<III", 2, 2, 0xFFFFFFFF) + raw[12:]
    assert facetess.parse_directory(huge) is None
    assert facetess.instance_path("a-1@top/b-2@sub") == ("a-1", "b-2")


def test_an_instance_of_another_configuration_uses_the_assembly_mesh_only_for_the_same_part_configuration(
    tmp_path,
):
    """o16's stored meshes are those of Default, its active configuration. Lite made to use
    o06 in Default (Default uses OracleAlt) must not take o06's stored mesh."""
    streams = fixture_streams(fixture_path(O16))
    tree = streams["swXmlContents/COMPINSTANCETREE"].decode("utf-8")
    lite = tree.index('id="35"')
    o06_ref = tree.index('swModelRef="10"', lite)
    start, end = tree.rindex("<swReference", 0, o06_ref), tree.index("/>", o06_ref)
    element = tree[start:end].replace('swModelRef="10"', 'swModelRef="99"')
    assert element.count('swConfigurationName="OracleAlt"') == 1
    tree = tree[:start] + element.replace("OracleAlt", "Default") + tree[end:]
    model = '<swModel id="99" swName="o06_boxA_props_mat_cfg" swConfigurationName="Default" swFileRef="11"/>'
    tree = tree.replace("</swModelList>", model + "</swModelList>", 1)
    assert tree.count(model) == 1
    path = tmp_path / O16
    path.write_bytes(rebuild(fixture_path(O16), {"swXmlContents/COMPINSTANCETREE": tree.encode("utf-8")}))
    with open_document(path) as doc:
        g = geo.display_geometry(doc, "Lite", sources=("assembly",))
        default = geo.display_geometry(doc, "Default", sources=("assembly",))
    assert [(s.id, s.reason) for s in g.skipped] == [("o06_boxA_props_mat_cfg-1", "no_source")]
    assert g.counts["placed"] == 9 and default.skipped == ()


# --------------------------------------------------------------------------- crafted trees
def _cstring(text: str) -> bytes:
    raw = text.encode("utf-16-le")
    return b"\xff\xfe\xff" + bytes([len(text)]) + raw


def _part_tree(n: int = 1, *, stored: str = "p.SLDPRT", **ref) -> TreeXml:
    t = TreeXml()
    t.top("m1")
    t.file("2", stored)
    t.model("m2", "2")
    for i in range(n):
        t.ref("m1", "p", i + 1, "m2", **ref)
    return t


def _folder_with(tmp_path: Path, tree: TreeXml, parts: dict[str, str], **kw) -> Path:
    folder = tmp_path / "jobs"
    folder.mkdir(exist_ok=True)
    for name, fixture in parts.items():
        shutil.copy2(fixture_path(fixture), folder / name)
    (folder / "asm.SLDASM").write_bytes(assembly_with_tree(tree, **kw))
    return folder


def test_a_sub_assembly_that_contains_itself_is_reported_not_followed(tmp_path):
    t = TreeXml()
    t.top("m1")
    t.file("2", "s.SLDASM", "ASSEMBLY")
    t.model("m2", "2")
    t.ref("m1", "s", 1, "m2")
    t.ref("m2", "s", 1, "m2")  # the sub-assembly lists itself
    folder = _folder_with(tmp_path, t, {})
    with open_document(folder / "asm.SLDASM") as doc:
        g = geo.display_geometry(doc)
    assert g.instances == () and [(s.id, s.reason) for s in g.skipped] == [("s-1/s-1", "cycle")]


def test_a_million_instances_stop_at_the_instance_limit(tmp_path):
    t = TreeXml()
    t.top("m1")
    t.file("2", "s.SLDASM", "ASSEMBLY")
    t.file("3", "p.SLDPRT")
    t.model("m2", "2")
    t.model("m3", "3")
    for i in range(1000):
        t.ref("m1", "s", i + 1, "m2")
        t.ref("m2", "p", i + 1, "m3")
    folder = _folder_with(tmp_path, t, {"p.SLDPRT": "o02_boxA.SLDPRT"})
    before = _state(folder)
    with open_document(folder / "asm.SLDASM") as doc:
        start = time.perf_counter()
        g = geo.display_geometry(doc)
        took = time.perf_counter() - start
        small = geo.display_geometry(doc, max_instances=50)
    assert g.truncated == ("max_instances",) and g.counts["instances"] == geo.DEFAULT_MAX_INSTANCES
    # One file, its identity read once and the file read once for every instance.
    assert len(g.meshes) == 1 and g.counts["files_opened"] == 2
    assert g.counts["placed"] > 99_000 and g.counts["triangles_drawn"] == 12 * g.counts["placed"]
    assert took < 30
    assert small.counts["instances"] == 50 and small.truncated == ("max_instances",)
    assert _state(folder) == before


def test_a_mesh_box_is_measured_once_for_all_its_instances(tmp_path, monkeypatch):
    """The box of 500 instances of one part costs one pass over its vertices and eight
    corners an instance, not a pass over the vertices for every instance."""
    from solidseas.formats.solidworks.mesh import Mesh

    folder = _folder_with(tmp_path, _part_tree(500), {"p.SLDPRT": "o02_boxA.SLDPRT"})
    with open_document(folder / "asm.SLDASM") as doc:
        g = geo.display_geometry(doc)
    calls = []
    real = Mesh.bbox
    monkeypatch.setattr(Mesh, "bbox", lambda self: calls.append(1) or real(self))
    box = g.bbox()
    assert len(g.instances) == 500 and len(calls) == 1
    assert _flat(box) == pytest.approx([0, 0, 0, 0.01, 0.02, 0.03], abs=TOL)
    assert g.bounds(g.instances[7]) == g.bounds(g.instances[0]) and len(calls) == 1


def test_the_triangles_drawn_are_bounded_too(tmp_path):
    """Triangles read count each file once; triangles drawn count every instance. A
    small file of many instances of one part reads twelve triangles and would draw
    twelve for each instance: past ``max_triangles_drawn`` the rest are skipped, said
    so, and named in ``truncated``."""
    folder = _folder_with(tmp_path, _part_tree(50), {"p.SLDPRT": "o02_boxA.SLDPRT"})
    with open_document(folder / "asm.SLDASM") as doc:
        g = geo.display_geometry(doc, max_triangles_drawn=12 * 20)
        whole = geo.display_geometry(doc)
        with pytest.raises(InvalidArgumentError):
            geo.display_geometry(doc, max_triangles_drawn=-1)
    assert g.counts["placed"] == 20 and g.counts["triangles_drawn"] == 240
    assert g.counts["triangles_read"] == 12
    assert {s.reason for s in g.skipped} == {"max_drawn"} and len(g.skipped) == 30
    assert g.truncated == ("max_drawn",) and g.skipped[0].message == geo.REASONS["max_drawn"]
    assert whole.counts["placed"] == 50 and whole.truncated == ()


def test_a_limit_is_the_reason_given_when_the_next_source_fails_otherwise():
    """o16's virtual part has its mesh in the assembly; its own nested document stores
    none. When the triangle limit stops the first read, the instance says so rather than
    taking the nested document's 'no mesh': a higher limit would draw it."""
    with open_document(fixture_path(O16)) as doc:
        assert geo.display_geometry(doc).counts["placed"] == 12
        for cap in (70, 60, 40):
            g = geo.display_geometry(doc, max_triangles=cap)
            reasons = {s.id: s.reason for s in g.skipped}
            assert reasons["Part12^o16_asm_features-1"] == "max_triangles", (cap, reasons)
            assert set(reasons.values()) == {"max_triangles"} and g.truncated == ("max_triangles",)
        nested = geo.display_geometry(doc, sources=("nested",))
    assert {s.id: s.reason for s in nested.skipped}["Part12^o16_asm_features-1"] == "no_mesh"


def test_missing_files_are_named_and_the_rest_is_drawn(tmp_path):
    t = _part_tree(2)
    t.file("3", "gone.SLDPRT")
    t.model("m3", "3")
    t.ref("m1", "gone", 1, "m3")
    folder = _folder_with(tmp_path, t, {"p.SLDPRT": "o02_boxA.SLDPRT"})
    with open_document(folder / "asm.SLDASM") as doc:
        g = geo.display_geometry(doc)
    assert [i.id for i in g.instances] == ["p-1", "p-2"]
    (gone,) = g.skipped
    assert (gone.id, gone.reason, gone.message) == ("gone-1", "missing", geo.REASONS["missing"])
    assert g.resolution is not None and g.resolution.results["3"].status == "missing"


def test_suppressed_and_hidden_instances_and_their_children_are_not_drawn(tmp_path):
    t = _part_tree(1)
    t.ref("m1", "p", 2, "m2", suppressed=True)
    t.ref("m1", "p", 3, "m2", hidden=True)
    t.file("3", "s.SLDASM", "ASSEMBLY")
    t.model("m3", "3")
    t.ref("m3", "p", 1, "m2")
    t.ref("m1", "s", 1, "m3", suppressed=True)
    t.ref("m1", "s", 2, "m3", hidden=True)
    t.ref("m1", "s", 3, "m3")
    folder = _folder_with(tmp_path, t, {"p.SLDPRT": "o02_boxA.SLDPRT"})
    with open_document(folder / "asm.SLDASM") as doc:
        g = geo.display_geometry(doc)
    assert [i.id for i in g.instances] == ["p-1", "s-3/p-1"]
    assert (g.counts["parts"], g.counts["suppressed"], g.counts["hidden"]) == (6, 2, 2)


def test_a_transform_that_cannot_be_read_is_reported(tmp_path):
    t = _part_tree(1, transform="1 0 0")
    folder = _folder_with(tmp_path, t, {"p.SLDPRT": "o02_boxA.SLDPRT"})
    with open_document(folder / "asm.SLDASM") as doc:
        g = geo.display_geometry(doc)
    assert [(s.id, s.reason) for s in g.skipped] == [("p-1", "no_placement")]


@pytest.fixture
def no_fake_drives(monkeypatch):
    real = gateway_mod._drive_type
    monkeypatch.setattr(
        gateway_mod, "_drive_type", lambda root: 1 if root.upper().startswith("Q:") else real(root)
    )


@pytest.mark.skipif(not WINDOWS, reason="junctions are Windows")
def test_a_junction_inside_the_root_is_never_crossed(tmp_path, no_fake_drives, monkeypatch):
    import _winapi

    root, outside = tmp_path / "Root", tmp_path / "Outside"
    outside.mkdir()
    shutil.copy2(fixture_path("o02_boxA.SLDPRT"), outside / "p.SLDPRT")
    root.mkdir()
    _winapi.CreateJunction(str(outside), str(root / "link"))
    try:
        assert (root / "link" / "p.SLDPRT").is_file()  # control: the junction really leads outside
        t = _part_tree(1, stored="Q:\\Old\\link\\p.SLDPRT")
        (root / "asm.SLDASM").write_bytes(resolving_assembly(t, folder_at_save="Q:\\Old\\"))
        opened: list[str] = []
        real_open = geo.open_document
        monkeypatch.setattr(geo, "open_document", lambda p, **kw: opened.append(str(p)) or real_open(p, **kw))
        before = _state(outside)
        with open_document(root / "asm.SLDASM") as doc:
            g = geo.display_geometry(doc, roots=Roots([Root("r", str(root))]))
        assert g.instances == () and [(s.id, s.reason) for s in g.skipped] == [("p-1", "missing")]
        assert opened == [] and _state(outside) == before
        # The root itself may be a junction (a root is configuration): its files are found.
        link = tmp_path / "RootLink"
        _winapi.CreateJunction(str(outside), str(link))
        try:
            (outside / "asm2.SLDASM").write_bytes(resolving_assembly(_part_tree(1)))
            with open_document(link / "asm2.SLDASM") as doc:
                g2 = geo.display_geometry(doc, roots={"r": str(link)})
            assert [i.id for i in g2.instances] == ["p-1"]
            assert [os.path.normcase(p) for p in opened] == [os.path.normcase(str(link / "p.SLDPRT"))]
        finally:
            os.rmdir(link)
    finally:
        os.rmdir(root / "link")  # removes the junction, not what it points at


def test_the_limits_stop_reads_and_say_which(tmp_path):
    t = _part_tree(2)
    t.file("3", "q.SLDPRT")
    t.model("m3", "3")
    t.ref("m1", "q", 1, "m3")
    folder = _folder_with(tmp_path, t, {"p.SLDPRT": "o02_boxA.SLDPRT", "q.SLDPRT": "o07_boxB_h31.SLDPRT"})
    with open_document(folder / "asm.SLDASM") as doc:
        # Resolution reads both files' identities first, then p is read and q is not.
        files = geo.display_geometry(doc, max_files=3)
        tris = geo.display_geometry(doc, max_triangles=12)
        nothing = geo.display_geometry(doc, max_bytes=100)
        with pytest.raises(InvalidArgumentError):
            geo.display_geometry(doc, sources=("assembly", "web"))
        with pytest.raises(InvalidArgumentError):
            geo.display_geometry(doc, sources=("file", "file"))
        for bad in ({"max_files": -1}, {"max_instances": 0}, {"max_triangles": True}, {"max_depth": 65}):
            with pytest.raises(InvalidArgumentError):
                geo.display_geometry(doc, **bad)
        with pytest.raises(InvalidArgumentError):
            geo.display_geometry(doc, resolution="not one")
    for g, limit in ((files, "max_files"), (tris, "max_triangles")):
        assert [i.id for i in g.instances] == ["p-1", "p-2"]
        assert [(s.id, s.reason) for s in g.skipped] == [("q-1", limit)] and g.truncated == (limit,)
    assert files.counts["files_opened"] == 3 and tris.counts["triangles_read"] == 12
    assert nothing.instances == () and nothing.truncated == ("max_bytes",)


def test_a_resolution_already_made_is_used_as_it_is(tmp_path):
    folder = _folder_with(tmp_path, _part_tree(1), {"p.SLDPRT": "o02_boxA.SLDPRT"})
    with open_document(folder / "asm.SLDASM") as doc:
        res = doc.resolve_references({"jobs": str(folder)})
        g = geo.display_geometry(doc, roots={"jobs": str(folder)}, resolution=res)
    assert g.resolution is res and [i.id for i in g.instances] == ["p-1"]


def test_a_virtual_part_inside_a_sub_assembly_is_read_from_that_sub_assembly(tmp_path):
    folder = tmp_path / "jobs"
    folder.mkdir()
    # o16, with its virtual part's stored document replaced by one that has a display mesh
    o02 = fixture_path("o02_boxA.SLDPRT").read_bytes()
    (folder / "sub.SLDASM").write_bytes(rebuild(fixture_path(O16), {"VirtualComp/Part12-sldprt": o02}))
    t = TreeXml()
    t.top("m1")
    t.file("2", "sub.SLDASM", "ASSEMBLY")
    t.file("3", "Part12^o16_asm_features.SLDPRT")
    t.model("m2", "2")
    t.model("m3", "3")
    t.ref("m1", "sub", 1, "m2", transform="1 0 0 0 0 1 0 0 0 0 1 0 1 2 3 1")
    t.ref("m2", "Part12^o16_asm_features", 1, "m3", virtual=True)
    (folder / "top.SLDASM").write_bytes(assembly_with_tree(t))
    before = _state(folder)
    with open_document(folder / "top.SLDASM") as doc:
        assert doc.components().files["3"].embedded_in_subassembly
        g = geo.display_geometry(doc, sources=("nested",))
    (inst,) = g.instances
    m = g.meshes[inst.mesh]
    assert m.kind == "nested" and m.nested == ("VirtualComp/Part12-sldprt",) and m.path.endswith("sub.SLDASM")
    assert _flat(g.bounds(inst)) == pytest.approx([1, 2, 3, 1.01, 2.02, 3.03], abs=TOL)
    assert _state(folder) == before


def test_an_older_assembly_keeps_its_components_in_its_own_display_lists(tmp_path, no_fake_drives):
    """Before FaceTessellations, each component file's face tables follow a header that
    names the file's stored path, in the assembly's own Contents/DisplayLists. A file
    whose path opens two sections that both hold face tables is not used: which
    configuration each shows is not stored."""
    a, b, c = "Q:\\Old\\a.SLDPRT", "Q:\\Old\\b.SLDPRT", "Q:\\Old\\c.SLDPRT"
    o02 = fixture_streams(fixture_path("o02_boxA.SLDPRT"))["Contents/DisplayLists"]
    o07 = fixture_streams(fixture_path("o07_boxB_h31.SLDPRT"))["Contents/DisplayLists"]
    lists = struct.pack("<II", 1, 1) + _cstring(a) + o02 + _cstring(b) + o07 + _cstring(c)
    t = TreeXml()
    t.top("m1")
    for fid, stored, name in (("2", a, "a"), ("3", b, "b"), ("4", c, "c")):
        t.file(fid, stored)
        t.model(f"m{fid}", fid)
        t.ref("m1", name, 1, f"m{fid}", transform="1 0 0 0 0 1 0 0 0 0 1 0 0.5 0 0 1")
    folder = tmp_path / "old"
    folder.mkdir()
    drop = ("FaceTessellations/Directory", "FaceTessellations/000-000-001")
    (folder / "asm.SLDASM").write_bytes(assembly_with_tree(t, {"Contents/DisplayLists": lists}, drop=drop))
    with open_document(folder / "asm.SLDASM") as doc:
        g = geo.display_geometry(doc)
    assert [i.id for i in g.instances] == ["a-1", "b-1"]
    for inst, box in zip(
        g.instances, ([0.5, 0, 0, 0.51, 0.02, 0.03], [0.5, 0, 0, 0.51, 0.02, 0.031]), strict=True
    ):
        m = g.meshes[inst.mesh]
        assert m.kind == "assembly" and m.stream == "Contents/DisplayLists" and m.triangles == 12
        assert _flat(g.bounds(inst, exact=True)) == pytest.approx(box, abs=TOL)
    assert [(s.id, s.reason) for s in g.skipped] == [("c-1", "missing")]  # an empty section, and no file
    assert g.counts["files_opened"] == 0
    twice = lists + _cstring(a) + o02
    (folder / "twice.SLDASM").write_bytes(assembly_with_tree(t, {"Contents/DisplayLists": twice}, drop=drop))
    with open_document(folder / "twice.SLDASM") as doc:
        g2 = geo.display_geometry(doc)
    assert [i.id for i in g2.instances] == ["b-1"]

    # a's section ends at the header of the next file whatever that file is: here b, a part
    # the tree uses in two configurations, and then s, a sub-assembly, whose sections are not
    # used. Running on through their tables, a-1 would be drawn with b's and s's triangles too.
    s = "Q:\\Old\\s.SLDASM"
    mixed = struct.pack("<II", 1, 1) + _cstring(a) + o02 + _cstring(b) + o07 + _cstring(s) + o07
    m = TreeXml()
    m.top("m1")
    m.file("2", a)
    m.model("m2", "2")
    m.ref("m1", "a", 1, "m2", transform="1 0 0 0 0 1 0 0 0 0 1 0 0.5 0 0 1")
    m.file("3", b)
    m.model("m3", "3", "Default")
    m.model("m4", "3", "Tall")
    m.ref("m1", "b", 1, "m3")
    m.ref("m1", "b", 2, "m4", config="Tall")
    m.file("5", s, "ASSEMBLY")
    m.model("m5", "5")
    m.ref("m1", "s", 1, "m5")
    (folder / "mixed.SLDASM").write_bytes(assembly_with_tree(m, {"Contents/DisplayLists": mixed}, drop=drop))
    with open_document(folder / "mixed.SLDASM") as doc:
        g3 = geo.display_geometry(doc, sources=("assembly",))
    (a1,) = g3.instances
    assert a1.id == "a-1" and g3.meshes[a1.mesh].triangles == 12  # o02's own twelve, nothing of o07's
    assert _flat(g3.bounds(a1, exact=True)) == pytest.approx([0.5, 0, 0, 0.51, 0.02, 0.03], abs=TOL)
    # s lists no components here and its file is not in the folder: it is named, not dropped.
    assert {(x.id, x.reason) for x in g3.skipped} == {
        ("b-1", "no_source"),
        ("b-2", "no_source"),
        ("s-1", "missing"),
    }
    # The boundaries alone: a path given as None ends the section before it and opens none.
    spans = facetess.path_sections(mixed, {a.casefold(): "2", b.casefold(): None, s.casefold(): None})
    assert list(spans) == ["2"] and spans["2"] == [(8, 8 + len(_cstring(a)) + len(o02))]
    assert facetess.path_sections(mixed, {a.casefold(): "2"})["2"] == [(8, len(mixed))]  # without them


def test_a_section_ends_at_another_path_of_a_file_the_tree_names(tmp_path, no_fake_drives):
    """Some older display lists hold a header with a path a file of the tree had before
    it moved (its name in another folder), and that file's tables after it. The section
    before it ends there, so a part is not drawn with another file's tables. A path of
    the section's own file in another folder, or a bare file name, does not end it."""
    a, b = "Q:\\Old\\a.SLDPRT", "Q:\\Old\\b.SLDPRT"
    o02 = fixture_streams(fixture_path("o02_boxA.SLDPRT"))["Contents/DisplayLists"]
    o07 = fixture_streams(fixture_path("o07_boxB_h31.SLDPRT"))["Contents/DisplayLists"]
    head = struct.pack("<II", 1, 1)
    t = TreeXml()
    t.top("m1")
    for fid, stored, name in (("2", a, "a"), ("3", b, "b")):
        t.file(fid, stored)
        t.model(f"m{fid}", fid)
        t.ref("m1", name, 1, f"m{fid}", transform="1 0 0 0 0 1 0 0 0 0 1 0 0.5 0 0 1")
    folder = tmp_path / "old"
    folder.mkdir()
    drop = ("FaceTessellations/Directory", "FaceTessellations/000-000-001")
    moved_b = head + _cstring(a) + o02 + _cstring("R:\\Was\\b.SLDPRT") + o07 + _cstring(b) + o07
    moved_a = head + _cstring(a) + _cstring("R:\\Was\\a.SLDPRT") + o02 + _cstring(b) + o07
    for lists in (moved_b, moved_a):
        asm = assembly_with_tree(t, {"Contents/DisplayLists": lists}, drop=drop)
        (folder / "asm.SLDASM").write_bytes(asm)
        with open_document(folder / "asm.SLDASM") as doc:
            g = geo.display_geometry(doc, sources=("assembly",))
        assert [(i.id, g.meshes[i.mesh].triangles) for i in g.instances] == [("a-1", 12), ("b-1", 12)]
        assert _flat(g.bounds(g.instances[0], exact=True)) == pytest.approx(
            [0.5, 0, 0, 0.51, 0.02, 0.03], abs=TOL
        )
    paths = {a.casefold(): "2", b.casefold(): "3"}
    names = {"a.sldprt": frozenset({"2"}), "b.sldprt": frozenset({"3"})}
    first = (8, 8 + len(_cstring(a)) + len(o02))
    assert facetess.path_sections(moved_b, paths, names)["2"] == [first]
    assert facetess.path_sections(moved_b, paths)["2"] == [(8, moved_b.rindex(_cstring(b)))]  # without names
    bare = head + _cstring(a) + o02 + _cstring("b.SLDPRT") + o07
    assert facetess.path_sections(bare, paths, names)["2"] == [(8, len(bare))]
    assert facetess.base_name("Q:\\Old/Sub\\Part.SLDPRT") == "part.sldprt" and facetess.base_name("p") == "p"


def test_a_path_that_opens_several_sections_takes_the_one_with_face_tables(tmp_path, no_fake_drives):
    """In an older assembly a file's stored path can open several sections, all but one
    a mention of the path with no face tables after it (1,377 placed instances on the
    development corpus). The one with tables is the file's mesh, wherever it comes; two
    with tables are still refused (the test above), none reads as no mesh, and the
    triangle limit stops the decoding."""
    a, b, c = "Q:\\Old\\a.SLDPRT", "Q:\\Old\\b.SLDPRT", "Q:\\Old\\c.SLDPRT"
    o02 = fixture_streams(fixture_path("o02_boxA.SLDPRT"))["Contents/DisplayLists"]
    o07 = fixture_streams(fixture_path("o07_boxB_h31.SLDPRT"))["Contents/DisplayLists"]
    head = struct.pack("<II", 1, 1)
    t = TreeXml()
    t.top("m1")
    for fid, stored, name in (("2", a, "a"), ("3", b, "b"), ("4", c, "c")):
        t.file(fid, stored)
        t.model(f"m{fid}", fid)
        t.ref("m1", name, 1, f"m{fid}", transform="1 0 0 0 0 1 0 0 0 0 1 0 0.5 0 0 1")
    folder = tmp_path / "old"
    folder.mkdir()
    drop = ("FaceTessellations/Directory", "FaceTessellations/000-000-001")

    def geometry(lists: bytes, **kw):
        path = folder / "asm.SLDASM"
        path.write_bytes(assembly_with_tree(t, {"Contents/DisplayLists": lists}, drop=drop))
        with open_document(path) as doc:
            return geo.display_geometry(doc, **kw)

    tables_first = head + _cstring(a) + o02 + _cstring(b) + o07 + _cstring(a) + _cstring(c)
    mention_first = head + _cstring(a) + _cstring(b) + o07 + _cstring(a) + o02 + _cstring(c)
    for lists in (tables_first, mention_first):
        assert len(facetess.path_sections(lists, {a.casefold(): "2", b.casefold(): "3"})["2"]) == 2
        g = geometry(lists)
        assert [i.id for i in g.instances] == ["a-1", "b-1"]
        a1 = g.instances[0]
        m = g.meshes[a1.mesh]
        assert m.kind == "assembly" and m.stream == "Contents/DisplayLists" and m.triangles == 12
        assert _flat(g.bounds(a1, exact=True)) == pytest.approx([0.5, 0, 0, 0.51, 0.02, 0.03], abs=TOL)
        assert g.counts["triangles_read"] == 24 and g.counts["files_opened"] == 0
        assert [(s.id, s.reason) for s in g.skipped] == [("c-1", "missing")]
    # No tables after any of a's paths: the assembly stores no mesh of it.
    empty = geometry(
        head + _cstring(a) + _cstring(b) + o07 + _cstring(a) + _cstring(c), sources=("assembly",)
    )
    assert [i.id for i in empty.instances] == ["b-1"]
    assert {(s.id, s.reason) for s in empty.skipped} == {("a-1", "no_mesh"), ("c-1", "no_mesh")}
    # The triangle limit: a's twelve triangles are past it, and so are b's.
    small = geometry(tables_first, sources=("assembly",), max_triangles=11)
    assert small.instances == () and {s.reason for s in small.skipped} == {"max_triangles", "no_mesh"}
    assert {s.id for s in small.skipped if s.reason == "max_triangles"} == {"a-1", "b-1"}
    assert small.truncated == ("max_triangles",) and small.counts["triangles_read"] == 0
