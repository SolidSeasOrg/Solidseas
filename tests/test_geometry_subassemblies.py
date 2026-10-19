"""The parts inside sub-assemblies, in an assembly's display geometry.

Three ways a part inside a sub-assembly reaches the drawing, each checked against
the boxes SOLIDWORKS reported for o16 (``ground_truth.json``):

* the meshes a sub-assembly stores in its own file (the ``subassembly`` source),
  for an instance the top assembly holds no mesh of: o16 without its own meshes
  draws the parts of o15 from o15's, and a part three levels down comes from
  whichever sub-assembly above it stores it;
* a sub-assembly whose components the top assembly's tree does not list is
  expanded from its own file, with the same placements and limits, and named
  with a reason when that file cannot be found, read or expanded;
* an instance that stays without a mesh carries its placement and the box its
  assembly stores for it, a placeholder that lands on SOLIDWORKS' box.

Every shown leaf is placed or skipped, and placed + skipped + suppressed + hidden
equals the parts, whatever the tree and the limits. Nothing in a folder read is
ever changed.
"""

import hashlib
import json
import shutil
import struct
from pathlib import Path

import pytest

from builders import TreeXml, assembly_with_tree, fixture_streams, rebuild
from solidseas import geometry as geo
from solidseas import open_document
from solidseas.formats.solidworks import document as document_module
from solidseas.formats.solidworks.components import parse_bounding_box
from support import FIXTURES, fixture_path

GT = json.loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))
O08, O15, O16 = "o08_asm_2x_boxA.SLDASM", "o15_sub_asm.SLDASM", "o16_asm_features.SLDASM"
TOL = 1e-6
NO_FT = ("FaceTessellations/Directory", "FaceTessellations/000-000-002")
# o08's, which assembly_with_tree builds on: left out, a crafted assembly stores no mesh.
O08_MESHES = ("FaceTessellations/Directory", "FaceTessellations/000-000-001", "Contents/DisplayLists")
INNER = ("o15_sub_asm-1/o02_boxA-1", "o15_sub_asm-1/o07_boxB_h31-1")
# Parts are looked for in the folder given only: the fixtures' stored paths may exist on
# the machine that made them.
ONLY_ROOTS = {"allow_outside_roots": False}
# The sources that read stored meshes. o16's virtual part stores none and is drawn from its
# bodies by the brep source (tests/test_tessellate.py), which these tests leave out.
STORED = ("assembly", "nested", "file", "subassembly")


def _state(folder: Path) -> dict[str, tuple[str, int]]:
    return {
        str(p.relative_to(folder)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def _flat(box) -> list[float]:
    return [*box[0], *box[1]]


def _gt_boxes(name: str, configuration: str = "Default") -> dict[str, list[float]]:
    comps = GT[name]["api"]["configurations"][configuration]["components"]
    return {c["name"]: c["box_m"] for c in comps}


def _transforms(name: str) -> dict[str, str]:
    """Each instance's stored transform in fixture ``name``, as swTransform text."""
    with open_document(fixture_path(name)) as doc:
        return {n.id: " ".join(repr(v) for v in n.transform.stored) for n in doc.components().walk()}


def _folder(tmp_path: Path, name: str, files: dict[str, bytes | str]) -> Path:
    """A folder of ``files``: bytes, or the name of a fixture to copy."""
    folder = tmp_path / name
    folder.mkdir()
    for fname, what in files.items():
        if isinstance(what, bytes):
            (folder / fname).write_bytes(what)
        else:
            shutil.copy2(fixture_path(what), folder / fname)
    return folder


def _geometry(path: Path, *args, **kw):
    with open_document(path) as doc:
        return geo.display_geometry(doc, *args, **{**ONLY_ROOTS, **kw})


def _cstring(text: str) -> bytes:
    return b"\xff\xfe\xff" + bytes([len(text)]) + text.encode("utf-16-le")


def _adds_up(g) -> bool:
    c = g.counts
    return (
        c["placed"] + c["skipped"] + c["suppressed"] + c["hidden"] == c["parts"]
        and c["placed"] == len(g.instances)
        and c["skipped"] == len(g.skipped)
    )


# --------------------------------------------------------------------------- a sub-assembly's own meshes
def test_the_parts_of_a_sub_assembly_come_from_its_own_meshes(tmp_path):
    """o16 without its FaceTessellations, in a folder holding o15 and no part: o15's
    parts are drawn from the meshes o15 stores, where SOLIDWORKS put them, and the
    other parts are named, each with a box where it would be."""
    folder = _folder(tmp_path, "jobs", {O16: rebuild(fixture_path(O16), drop=NO_FT), O15: O15})
    before = _state(folder)
    g = _geometry(folder / O16, sources=STORED)
    gt = _gt_boxes(O16)
    assert [i.id for i in g.instances] == list(INNER)
    for inst in g.instances:
        m = g.meshes[inst.mesh]
        assert m.kind == "subassembly" and m.stream.startswith("FaceTessellations/")
        assert m.path is not None and Path(m.path).name == O15 and m.nested == ()
        assert m.configuration == "Default" and m.triangles == 12 and m.warnings == ()
        assert _flat(g.bounds(inst, exact=True)) == pytest.approx(gt[inst.id], abs=TOL), inst.id
    assert g.counts["files_opened"] == 1  # o15, once for both
    # Every other part SOLIDWORKS draws is skipped, with a box on SOLIDWORKS' box.
    drawn = {n for n, b in gt.items() if b is not None and n.lower().split("/")[-1] != "o15_sub_asm-1"}
    assert {s.id for s in g.skipped} == drawn - set(INNER)
    for s in g.skipped:
        assert s.placement is not None and s.box is not None
        assert _flat(g.placeholder(s)) == pytest.approx(gt[s.id], abs=TOL), s.id
    assert _adds_up(g)
    # Without the sub-assembly source, as before: nothing is drawn.
    without = _geometry(folder / O16, sources=("assembly", "nested", "file"))
    assert without.instances == () and {s.id for s in without.skipped} == drawn
    assert _state(folder) == before


def _sub_tree(sub_config: str = "Default", o07_config: str = "Default") -> TreeXml:
    """top -> o15_sub_asm-1 (o15, turned as in o16) -> o02_boxA-1, o07_boxB_h31-1, all listed."""
    tf = _transforms(O16)
    t = TreeXml()
    t.top("m1")
    t.file("2", "o15_sub_asm.SLDASM", "ASSEMBLY")
    t.file("3", "o02_boxA.SLDPRT")
    t.file("4", "o07_boxB_h31.SLDPRT")
    t.model("m2", "2", sub_config)
    t.model("m3", "3")
    t.model("m4", "4", o07_config)
    t.ref("m1", "o15_sub_asm", 1, "m2", config=sub_config, transform=tf["o15_sub_asm-1"])
    t.ref("m2", "o02_boxA", 1, "m3", transform=tf["o15_sub_asm-1/o02_boxA-1"])
    t.ref("m2", "o07_boxB_h31", 1, "m4", config=o07_config, transform=tf["o15_sub_asm-1/o07_boxB_h31-1"])
    return t


def test_a_sub_assemblys_mesh_is_used_only_for_what_its_active_configuration_holds(tmp_path):
    """o15's meshes show its active configuration, Default, where o07 is used in
    Default. An instance that uses o07 in another configuration does not take it; the
    o02 beside it does, whatever configuration of o15 itself the top uses."""
    t = _sub_tree(o07_config="Tall")
    folder = _folder(tmp_path, "jobs", {"top.SLDASM": assembly_with_tree(t), O15: O15})
    g = _geometry(folder / "top.SLDASM")
    assert [i.id for i in g.instances] == [INNER[0]]
    assert g.meshes[g.instances[0].mesh].kind == "subassembly"
    assert _flat(g.bounds(g.instances[0], exact=True)) == pytest.approx(_gt_boxes(O16)[INNER[0]], abs=TOL)
    assert [(s.id, s.reason) for s in g.skipped] == [(INNER[1], "missing")]
    assert _adds_up(g)


def test_a_part_three_levels_down_comes_from_a_sub_assembly_that_stores_it(tmp_path):
    """top -> o16 -> o15 -> o02 and o07: o16 stores the meshes of o15's parts, so they come
    from o16, the sub-assembly nearest the top, without opening o15. Without o16 on disk
    they come from o15, the innermost. Either way they land on SOLIDWORKS' boxes."""
    tf = _transforms(O16)
    t = TreeXml()
    t.top("m1")
    t.file("2", O16, "ASSEMBLY")
    t.file("3", O15, "ASSEMBLY")
    t.file("4", "o02_boxA.SLDPRT")
    t.file("5", "o07_boxB_h31.SLDPRT")
    for mid, fid in (("m2", "2"), ("m3", "3"), ("m4", "4"), ("m5", "5")):
        t.model(mid, fid)
    t.ref("m1", "o16_asm_features", 1, "m2")
    t.ref("m2", "o15_sub_asm", 1, "m3", transform=tf["o15_sub_asm-1"])
    t.ref("m3", "o02_boxA", 1, "m4", transform=tf[INNER[0]])
    t.ref("m3", "o07_boxB_h31", 1, "m5", transform=tf[INNER[1]])
    top = assembly_with_tree(t)
    gt = _gt_boxes(O16)
    ids = [f"o16_asm_features-1/{i}" for i in INNER]
    for present, source in (((O16, O15), O16), ((O15,), O15)):
        folder = _folder(tmp_path, f"with_{len(present)}", {"top.SLDASM": top, **{n: n for n in present}})
        before = _state(folder)
        g = _geometry(folder / "top.SLDASM")
        assert [i.id for i in g.instances] == ids
        for inst, inner in zip(g.instances, INNER, strict=True):
            m = g.meshes[inst.mesh]
            assert m.kind == "subassembly" and Path(m.path).name == source
            assert _flat(g.bounds(inst, exact=True)) == pytest.approx(gt[inner], abs=TOL)
        assert g.counts["files_opened"] == 1 and g.skipped == () and _adds_up(g)
        assert _state(folder) == before


def _chain(with_s1: bool) -> TreeXml:
    """top (-> S1) -> o15_sub_asm-1 -> o02_boxA-1, o07_boxB_h31-1, all listed, o15 turned as in o16."""
    tf = _transforms(O16)
    t = TreeXml()
    t.top("m1")
    parent = "m1"
    if with_s1:
        t.file("9", "S1.SLDASM", "ASSEMBLY")
        t.model("m9", "9")
        t.ref("m1", "S1", 1, "m9")
        parent = "m9"
    t.file("2", O15, "ASSEMBLY")
    t.file("3", "o02_boxA.SLDPRT")
    t.file("4", "o07_boxB_h31.SLDPRT")
    for mid, fid in (("m2", "2"), ("m3", "3"), ("m4", "4")):
        t.model(mid, fid)
    t.ref(parent, "o15_sub_asm", 1, "m2", transform=tf["o15_sub_asm-1"])
    t.ref("m2", "o02_boxA", 1, "m3", transform=tf[INNER[0]])
    t.ref("m2", "o07_boxB_h31", 1, "m4", transform=tf[INNER[1]])
    return t


def test_a_sub_assembly_whose_stored_mesh_is_empty_passes_to_the_next_one_down(tmp_path):
    """top -> S1 -> o15 -> o02 and o07, with no part file. S1 is an older assembly whose
    display lists name o02's path with no face tables after it, so S1's section of o02
    is empty: o02 then comes from o15, the next sub-assembly down, like o07, rather than
    being named as missing."""
    lists = struct.pack("<II", 1, 1) + _cstring("o02_boxA.SLDPRT") + _cstring(O15)
    s1 = assembly_with_tree(_chain(False), {"Contents/DisplayLists": lists}, drop=O08_MESHES[:2])
    folder = _folder(
        tmp_path,
        "jobs",
        {
            "S1.SLDASM": s1,
            "top.SLDASM": assembly_with_tree(_chain(True), drop=O08_MESHES),
            O15: O15,
        },
    )
    before = _state(folder)
    g = _geometry(folder / "top.SLDASM")
    assert [i.id for i in g.instances] == [f"S1-1/{i}" for i in INNER] and g.skipped == ()
    gt = _gt_boxes(O16)
    for inst, inner in zip(g.instances, INNER, strict=True):
        m = g.meshes[inst.mesh]
        assert m.kind == "subassembly" and Path(m.path).name == O15
        assert _flat(g.bounds(inst, exact=True)) == pytest.approx(gt[inner], abs=TOL)
    assert _state(folder) == before


def test_a_byte_limit_on_stored_meshes_is_the_reason_given(tmp_path):
    """An older assembly's display lists, or a sub-assembly's directory, that the byte
    limit keeps from being read: the instance that could have taken its mesh from there
    is skipped as max_bytes, since a higher limit would draw it, not as missing."""
    o02 = fixture_streams(fixture_path("o02_boxA.SLDPRT"))["Contents/DisplayLists"]
    lists = struct.pack("<II", 1, 1) + _cstring("p.SLDPRT") + o02
    turn = "1 0 0 0 0 1 0 0 0 0 1 0 0.5 0 0 1"
    sub = TreeXml()
    sub.top("m1")
    sub.file("3", "p.SLDPRT")
    sub.model("m3", "3")
    sub.ref("m1", "p", 1, "m3", transform=turn)
    top = TreeXml()
    top.top("m1")
    top.file("9", "S1.SLDASM", "ASSEMBLY")
    top.file("3", "p.SLDPRT")
    top.model("m9", "9")
    top.model("m3", "3")
    top.ref("m1", "S1", 1, "m9", transform=turn)
    top.ref("m9", "p", 1, "m3", transform=turn)
    s1 = assembly_with_tree(sub, {"Contents/DisplayLists": lists}, drop=O08_MESHES[:2])
    for stored_in, files in (
        ("subassembly", {"S1.SLDASM": s1, "top.SLDASM": assembly_with_tree(top, drop=O08_MESHES)}),
        (
            "assembly",
            {"top.SLDASM": assembly_with_tree(top, {"Contents/DisplayLists": lists}, drop=O08_MESHES[:2])},
        ),
    ):
        folder = _folder(tmp_path, stored_in, files)
        g = _geometry(folder / "top.SLDASM")
        assert [(i.id, g.meshes[i.mesh].kind) for i in g.instances] == [("S1-1/p-1", stored_in)]
        small = _geometry(folder / "top.SLDASM", max_bytes=len(lists) - 1)
        assert [(s.id, s.reason) for s in small.skipped] == [("S1-1/p-1", "max_bytes")], stored_in
        assert small.truncated == ("max_bytes",) and small.counts["bytes_read"] == 0
    # A sub-assembly's FaceTessellations directory counts against the limit too.
    folder = _folder(tmp_path, "newer", {O16: rebuild(fixture_path(O16), drop=NO_FT), O15: O15})
    with open_document(folder / O15) as o15:
        directory = o15.container.info("FaceTessellations/Directory").size
    g = _geometry(folder / O16, sources=STORED)
    assert [i.id for i in g.instances] == list(INNER) and g.counts["bytes_read"] > directory
    none = _geometry(folder / O16, max_bytes=directory - 1, sources=STORED)
    assert none.instances == () and none.counts["bytes_read"] < directory
    assert {s.reason for s in none.skipped if s.id in INNER} == {"max_bytes"}


def test_the_part_files_come_before_the_sub_assemblies_meshes(tmp_path):
    """Two listed sub-assemblies that store nothing usable, each with a part file found:
    the part files are read first, so a limit of two files opened draws both rather than
    spending itself on the sub-assemblies."""
    t = TreeXml()
    t.top("m1")
    for k, part in ((1, "o02_boxA"), (2, "o07_boxB_h31")):
        t.file(f"s{k}", f"S{k}.SLDASM", "ASSEMBLY")
        t.file(f"p{k}", f"{part}.SLDPRT")
        t.model(f"ms{k}", f"s{k}")
        t.model(f"mp{k}", f"p{k}")
        t.ref("m1", f"S{k}", 1, f"ms{k}")
        t.ref(f"ms{k}", part, 1, f"mp{k}")
    sub = assembly_with_tree(TreeXml(), drop=O08_MESHES)
    folder = _folder(
        tmp_path,
        "jobs",
        {
            "top.SLDASM": assembly_with_tree(t, drop=O08_MESHES),
            "S1.SLDASM": sub,
            "S2.SLDASM": sub,
            "o02_boxA.SLDPRT": "o02_boxA.SLDPRT",
            "o07_boxB_h31.SLDPRT": "o07_boxB_h31.SLDPRT",
        },
    )
    g = _geometry(folder / "top.SLDASM", max_files=2)
    assert [i.id for i in g.instances] == ["S1-1/o02_boxA-1", "S2-1/o07_boxB_h31-1"] and g.skipped == ()
    assert {g.meshes[i.mesh].kind for i in g.instances} == {"file"} and g.counts["files_opened"] == 2


def test_the_sub_assemblies_trees_read_for_their_meshes_have_a_limit_named_when_reached(tmp_path):
    """top -> o16 -> o15 -> o02 and o07, with o16 and o15 on disk and no part file. To use
    o16's meshes, o16's own active tree is read, out of an allowance of max_instances
    nodes for all such trees. When that runs out before the parts are found, they are
    skipped as truncated, a limit, with max_instances named, not as missing."""
    tf = _transforms(O16)
    t = TreeXml()
    t.top("m1")
    t.file("2", O16, "ASSEMBLY")
    t.file("3", O15, "ASSEMBLY")
    t.file("4", "o02_boxA.SLDPRT")
    t.file("5", "o07_boxB_h31.SLDPRT")
    for mid, fid in (("m2", "2"), ("m3", "3"), ("m4", "4"), ("m5", "5")):
        t.model(mid, fid)
    t.ref("m1", "o16_asm_features", 1, "m2")
    t.ref("m2", "o15_sub_asm", 1, "m3", transform=tf["o15_sub_asm-1"])
    t.ref("m3", "o02_boxA", 1, "m4", transform=tf[INNER[0]])
    t.ref("m3", "o07_boxB_h31", 1, "m5", transform=tf[INNER[1]])
    folder = _folder(tmp_path, "jobs", {"top.SLDASM": assembly_with_tree(t), O16: O16, O15: O15})
    ids = [f"o16_asm_features-1/{i}" for i in INNER]
    g = _geometry(folder / "top.SLDASM")
    assert [i.id for i in g.instances] == ids and g.truncated == ()
    small = _geometry(folder / "top.SLDASM", max_instances=4)
    assert small.counts["instances"] == 4 and small.instances == ()  # the shown tree is whole
    assert [(s.id, s.reason) for s in small.skipped] == [(i, "truncated") for i in ids]
    assert all("own trees" in s.message for s in small.skipped)
    assert small.truncated == ("max_instances",) and _adds_up(small)


def test_a_sub_assembly_used_many_times_is_read_once(tmp_path, monkeypatch):
    """Fifty instances of an unlisted sub-assembly: its tree is read once, not once an
    instance. Three virtual unlisted sub-assemblies listing the same part: the folder is
    indexed once for all three resolutions, and the part file is opened and read once,
    one mesh for every instance."""
    trees: list[str] = []
    real = document_module.component_tree

    def counted(doc, *a, **kw):
        trees.append(Path(doc.path).name if doc.path else "")
        return real(doc, *a, **kw)

    monkeypatch.setattr(document_module, "component_tree", counted)
    t = _unlisted()
    for k in range(2, 51):
        t.ref("m1", "o15_sub_asm", k, "m2", transform=_transforms(O16)["o15_sub_asm-1"])
    folder = _folder(
        tmp_path,
        "many",
        {
            "top.SLDASM": assembly_with_tree(t),
            O15: O15,
            "o02_boxA.SLDPRT": "o02_boxA.SLDPRT",
            "o07_boxB_h31.SLDPRT": "o07_boxB_h31.SLDPRT",
        },
    )
    g = _geometry(folder / "top.SLDASM")
    assert g.counts["placed"] == 100 and g.skipped == () and _adds_up(g)
    assert trees.count(O15) == 1 and g.counts["files_opened"] == 3

    from solidseas import resolve

    caches = []
    real_resolve = resolve.resolve_references

    def resolving(doc, roots, **kw):
        caches.append(kw.get("cache"))
        return real_resolve(doc, roots, **kw)

    monkeypatch.setattr(resolve, "resolve_references", resolving)
    inner = TreeXml()
    inner.top("m1")
    inner.file("2", "p.SLDPRT")
    inner.model("m2", "2")
    inner.ref("m1", "p", 1, "m2")
    v = TreeXml()
    v.top("m1")
    members = {}
    for k in range(3):
        v.file(f"{k + 2}", f"V{k}^top.SLDASM", "ASSEMBLY")
        v.model(f"m{k + 2}", f"{k + 2}")
        v.ref("m1", f"V{k}^top", 1, f"m{k + 2}", virtual=True)
        members[f"VirtualComp/V{k}-sldasm"] = assembly_with_tree(inner)
    folder = _folder(
        tmp_path, "virtual", {"top.SLDASM": assembly_with_tree(v, members), "p.SLDPRT": "o02_boxA.SLDPRT"}
    )
    g = _geometry(folder / "top.SLDASM")
    assert [i.id for i in g.instances] == [f"V{k}^top-1/p-1" for k in range(3)]
    assert len({i.mesh for i in g.instances}) == 1 and g.counts["files_opened"] == 1
    assert g.counts["triangles_read"] == 12 and g.counts["triangles_drawn"] == 36
    assert len(caches) == 3 and caches[0] is not None and all(c is caches[0] for c in caches)


def test_a_sub_assembly_stored_inside_the_assembly_gives_its_meshes_too(tmp_path):
    """A virtual sub-assembly is a document inside the top assembly: its stored meshes
    are read from there, and the mesh source names the nested document followed."""
    tf = _transforms(O16)
    t = TreeXml()
    t.top("m1")
    t.file("2", "Sub^top.SLDASM", "ASSEMBLY")
    t.file("3", "o02_boxA.SLDPRT")
    t.model("m2", "2")
    t.model("m3", "3")
    t.ref("m1", "Sub^top", 1, "m2", virtual=True, transform=tf["o15_sub_asm-1"])
    t.ref("m2", "o02_boxA", 1, "m3", transform=tf[INNER[0]])
    nested = fixture_path(O15).read_bytes()
    folder = _folder(
        tmp_path, "jobs", {"top.SLDASM": assembly_with_tree(t, {"VirtualComp/Sub-sldasm": nested})}
    )
    g = _geometry(folder / "top.SLDASM")
    (inst,) = g.instances
    m = g.meshes[inst.mesh]
    assert inst.id == "Sub^top-1/o02_boxA-1" and m.kind == "subassembly"
    assert m.path is None and m.nested == ("VirtualComp/Sub-sldasm",)
    assert _flat(g.bounds(inst, exact=True)) == pytest.approx(_gt_boxes(O16)[INNER[0]], abs=TOL)
    assert g.counts["files_opened"] == 0


# --------------------------------------------------------------------------- unlisted sub-assemblies
def _unlisted(config: str = "Default", **ref) -> TreeXml:
    """top -> o15_sub_asm-1 (o15, turned as in o16), its components not listed."""
    tf = _transforms(O16)
    t = TreeXml()
    t.top("m1")
    t.file("2", "o15_sub_asm.SLDASM", "ASSEMBLY")
    t.model("m2", "2", config, bbox="0 -0.031 0 0.04 0.02 0.03")
    t.ref("m1", "o15_sub_asm", 1, "m2", config=config, transform=tf["o15_sub_asm-1"], **ref)
    return t


def test_a_sub_assembly_whose_components_are_not_listed_is_read_from_its_own_file(tmp_path):
    """The top assembly's tree names o15 and nothing inside it. o15's own file lists
    o02 and o07: they are expanded from there, placed through the top's transform and
    o15's own, drawn from the part files found for o15 (the default order tries them
    before a sub-assembly's meshes) or, without the files as a source, from o15's
    meshes, and land on SOLIDWORKS' boxes either way."""
    top = assembly_with_tree(_unlisted())
    folder = _folder(
        tmp_path,
        "jobs",
        {
            "top.SLDASM": top,
            O15: O15,
            "o02_boxA.SLDPRT": "o02_boxA.SLDPRT",
            "o07_boxB_h31.SLDPRT": "o07_boxB_h31.SLDPRT",
        },
    )
    before = _state(folder)
    gt = _gt_boxes(O16)
    for sources, kind in ((geo.SOURCES, "file"), (("assembly", "subassembly"), "subassembly")):
        g = _geometry(folder / "top.SLDASM", sources=sources)
        assert [i.id for i in g.instances] == list(INNER) and g.skipped == ()
        counted = ("instances", "parts", "placed", "suppressed", "hidden", "skipped", "meshes")
        assert [g.counts[k] for k in counted] == [3, 2, 2, 0, 0, 0, 2]  # the sub-assembly and its two parts
        for inst in g.instances:
            m = g.meshes[inst.mesh]
            assert m.kind == kind, (sources, inst.id)
            assert _flat(g.bounds(inst, exact=True)) == pytest.approx(gt[inst.id], abs=TOL), inst.id
            # Its file is o15's, keyed under the sub-assembly's key, and named.
            f = g.files[inst.file]
            assert inst.file.startswith("2/") and f.key == inst.file and f.direct is False
            assert f.file_name == ("o02_boxA.SLDPRT" if "o02" in inst.id else "o07_boxB_h31.SLDPRT")
        if kind == "file":
            assert {Path(m.path).name for m in g.meshes.values()} == {
                "o02_boxA.SLDPRT",
                "o07_boxB_h31.SLDPRT",
            }
    assert _state(folder) == before


def test_a_virtual_sub_assembly_with_unlisted_components_is_read_from_inside_the_assembly(tmp_path):
    """A virtual sub-assembly stored in the top assembly, whose components the top's tree
    does not list: its own tree (inside the top file) lists a part, which is found for
    it in the folder."""
    inner = TreeXml()
    inner.top("m1")
    inner.file("2", "p.SLDPRT")
    inner.model("m2", "2")
    inner.ref("m1", "p", 1, "m2", transform="1 0 0 0 0 1 0 0 0 0 1 0 0.5 0 0 1")
    t = TreeXml()
    t.top("m1")
    t.file("2", "Sub^top.SLDASM", "ASSEMBLY")
    t.model("m2", "2")
    t.ref("m1", "Sub^top", 1, "m2", virtual=True, transform="1 0 0 0 0 1 0 0 0 0 1 0 1 0 0 1")
    top = assembly_with_tree(t, {"VirtualComp/Sub-sldasm": assembly_with_tree(inner)})
    folder = _folder(tmp_path, "jobs", {"top.SLDASM": top, "p.SLDPRT": "o02_boxA.SLDPRT"})
    g = _geometry(folder / "top.SLDASM")
    (inst,) = g.instances
    assert inst.id == "Sub^top-1/p-1" and inst.file == "2/2" and g.files["2/2"].file_name == "p.SLDPRT"
    assert g.meshes[inst.mesh].kind == "file" and Path(g.meshes[inst.mesh].path).name == "p.SLDPRT"
    assert _flat(g.bounds(inst)) == pytest.approx([1.5, 0, 0, 1.51, 0.02, 0.03], abs=TOL)
    # An empty one (its own tree lists nothing) is named, not dropped.
    empty = TreeXml()
    empty.top("m1")
    folder2 = _folder(
        tmp_path,
        "empty",
        {"top.SLDASM": assembly_with_tree(t, {"VirtualComp/Sub-sldasm": assembly_with_tree(empty)})},
    )
    g2 = _geometry(folder2 / "top.SLDASM")
    assert g2.instances == () and [(s.id, s.reason) for s in g2.skipped] == [("Sub^top-1", "no_components")]
    assert g2.counts["parts"] == 1 and _adds_up(g2)


def test_a_sub_assembly_that_cannot_be_expanded_is_named_with_the_reason(tmp_path):
    """Its file missing, a configuration its file does not have, a file that contains
    the top assembly, the depth and instance limits: each is a skipped instance with its
    reason, its placement and the box the top stores for it, and counted once."""
    folder = _folder(tmp_path, "jobs", {O15: O15})
    gt_sub = _gt_boxes(O16)["o15_sub_asm-1"]

    def one(tree, **kw):
        (folder / "top.SLDASM").write_bytes(assembly_with_tree(tree))
        g = _geometry(folder / "top.SLDASM", **kw)
        assert g.instances == () and _adds_up(g) and g.counts["parts"] == 1
        (s,) = g.skipped
        return g, s

    gone = _unlisted()
    gone.files[1]["swPath"] = "gone.SLDASM"
    g, s = one(gone)
    assert (s.id, s.reason, s.file) == ("o15_sub_asm-1", "missing", "2")
    # Its stored box, placed: SOLIDWORKS' box of the sub-assembly (its own box carried over).
    assert s.box == ((0, -0.031, 0), (0.04, 0.02, 0.03))
    assert _flat(g.placeholder(s)) == pytest.approx(gt_sub, abs=TOL)
    assert s.matrix() is not None and s.matrix()[12:15] == pytest.approx((0, 0.1, 0))

    g, s = one(_unlisted("Nope"))
    assert (s.reason, s.code) == ("no_components", "configuration_not_found") and "'Nope'" in s.message

    g, s = one(_unlisted(), max_depth=1)
    assert s.reason == "truncated" and g.truncated == ("max_depth",)
    g, s = one(_unlisted(), max_instances=1)
    assert s.reason == "truncated" and g.truncated == ("max_instances",)

    # A sub-assembly whose own file names the top assembly, its components not listed.
    back = TreeXml()
    back.top("m1")
    back.file("2", "top.SLDASM", "ASSEMBLY")
    back.model("m2", "2")
    back.ref("m1", "top", 1, "m2")
    (folder / "sub.SLDASM").write_bytes(assembly_with_tree(back))
    t = TreeXml()
    t.top("m1")
    t.file("2", "sub.SLDASM", "ASSEMBLY")
    t.model("m2", "2")
    t.ref("m1", "sub", 1, "m2")
    (folder / "top.SLDASM").write_bytes(assembly_with_tree(t))
    g = _geometry(folder / "top.SLDASM")
    assert [(s.id, s.reason) for s in g.skipped] == [("sub-1/top-1", "cycle")]
    assert g.counts["instances"] == 2 and _adds_up(g)


def test_a_suppressed_or_hidden_unlisted_sub_assembly_is_counted_once_and_not_read(tmp_path):
    folder = _folder(tmp_path, "jobs", {O15: O15})
    for flag, count in (({"suppressed": True}, "suppressed"), ({"hidden": True}, "hidden")):
        (folder / "top.SLDASM").write_bytes(assembly_with_tree(_unlisted(**flag)))
        g = _geometry(folder / "top.SLDASM")
        assert g.instances == g.skipped == () and g.counts[count] == g.counts["parts"] == 1
        assert g.counts["files_opened"] == 0 and g.resolution is None


# --------------------------------------------------------------------------- every leaf accounted for
def _shown_leaves(doc, configuration, folder: Path, prefix: str = "", seen=()) -> set[str]:
    """The ids an assembly should place or skip, worked out here without
    display_geometry: every unsuppressed, visible leaf, a sub-assembly whose components
    the tree does not list replaced by its own file's leaves (found by name in
    ``folder``, or the document stored inside), or kept when that cannot be read."""
    tree = doc.components(configuration)
    out: set[str] = set()
    stack = [(n, False) for n in tree.children]
    while stack:
        n, off = stack.pop()
        off = off or n.suppressed or n.hidden
        if n.children:
            stack.extend((k, off) for k in n.children)
            continue
        if off:
            continue
        if n.doc_type == "assembly" and n.children_state == "described":
            f = tree.files[n.file]
            sub, opened = None, False
            if f.nested:
                sub = doc.nested(f.nested)
            elif f.file_name and (folder / f.file_name).is_file() and f.file_name not in seen:
                sub, opened = open_document(folder / f.file_name), True
            try:
                if sub is not None and sub.components(n.configuration).children:
                    out |= _shown_leaves(
                        sub, n.configuration, folder, f"{prefix}{n.id}/", (*seen, f.file_name)
                    )
                    continue
            except KeyError:  # a configuration its file does not have
                pass
            finally:
                if opened:
                    sub.close()
        out.add(prefix + n.id)
    return out


def test_every_shown_leaf_is_placed_or_skipped(tmp_path):
    """Over the fixture assemblies in every configuration and the crafted trees above,
    at the default limits and small ones: each shown leaf, expanded ones included, is
    placed or skipped, once, and placed + skipped + suppressed + hidden == parts."""
    folder = _folder(
        tmp_path,
        "jobs",
        {
            "o16_noft.SLDASM": rebuild(fixture_path(O16), drop=NO_FT),
            "unlisted.SLDASM": assembly_with_tree(_unlisted()),
            "listed.SLDASM": assembly_with_tree(_sub_tree(o07_config="Tall")),
            O08: O08,
            O15: O15,
            O16: O16,
            "o02_boxA.SLDPRT": "o02_boxA.SLDPRT",
        },
    )
    before = _state(folder)
    cases = [(O08, None), (O15, None), (O16, "Default"), (O16, "Lite"), ("o16_noft.SLDASM", None)]
    cases += [("unlisted.SLDASM", None), ("listed.SLDASM", None)]
    limits = [{}, {"max_triangles": 30}, {"max_files": 1}, {"max_instances": 2}, {"max_triangles_drawn": 20}]
    checked = 0
    for name, configuration in cases:
        with open_document(folder / name) as doc:
            expected = _shown_leaves(doc, configuration, folder)
            for kw in limits:
                g = geo.display_geometry(doc, configuration, **ONLY_ROOTS, **kw)
                assert _adds_up(g), (name, kw, g.counts)
                ids = [i.id for i in g.instances] + [s.id for s in g.skipped]
                assert len(ids) == len(set(ids)), (name, kw)
                if "max_instances" not in kw:
                    assert set(ids) == expected, (name, kw)
                checked += 1
    assert checked == len(cases) * len(limits)
    assert _state(folder) == before


# --------------------------------------------------------------------------- placeholders
def test_a_part_models_stored_box_is_its_display_mesh_box():
    """The frame and units of a part model's swBoundingBox: o02's model in o08 and in
    o16 holds the box of o02's own display mesh, in o02's coordinates, metres. A
    sub-assembly's model holds the sub-assembly's own box: o15's model in o16 is the box
    o15 stores for its active configuration, and placed where o16 puts o15 it is
    SOLIDWORKS' box of that sub-assembly."""
    with open_document(fixture_path("o02_boxA.SLDPRT")) as part:
        mesh_box = part.mesh().bbox()
    for name in (O08, O16):
        with open_document(fixture_path(name)) as doc:
            md = doc.metadata.tree
            (fid,) = [k for k, f in md["files"].items() if f["path"].endswith("o02_boxA.SLDPRT")]
            boxes = [parse_bounding_box(m["bbox"]) for m in md["models"].values() if m["file_ref"] == fid]
        assert boxes and all(_flat(b) == pytest.approx(_flat(mesh_box), abs=TOL) for b in boxes), name
    with open_document(fixture_path(O15)) as o15:
        md = o15.metadata.tree
        (cfg,) = [c for c in md["configs"] if c["name"] == o15.active_configuration]
        own = parse_bounding_box(md["models"][cfg["model_ref"]]["bbox"])
    with open_document(fixture_path(O16)) as o16:
        md = o16.metadata.tree
        (fid,) = [k for k, f in md["files"].items() if f["path"].endswith(O15)]
        (stored,) = {parse_bounding_box(m["bbox"]) for m in md["models"].values() if m["file_ref"] == fid}
        (node,) = [n for n in o16.components().walk() if n.id == "o15_sub_asm-1"]
    assert own is not None and _flat(stored) == pytest.approx(_flat(own), abs=TOL)
    placed = geo._placed_box(node.placement, stored)
    assert _flat(placed) == pytest.approx(_gt_boxes(O16)["o15_sub_asm-1"], abs=TOL)


@pytest.mark.parametrize(
    ("name", "configuration"), [(O08, "Default"), (O15, "Default"), (O16, "Default"), (O16, "Lite")]
)
def test_every_instance_without_a_mesh_has_a_box_on_solidworks_box(name, configuration, tmp_path):
    """The fixture assemblies in a folder with no part file, read from the files only:
    every part SOLIDWORKS draws is skipped, and its placeholder (the stored box of its
    model, placed) is SOLIDWORKS' box of it, rotations and the turned sub-assembly
    included."""
    folder = _folder(tmp_path, "asm", {name: name, O15: O15})
    g = _geometry(folder / name, configuration, sources=("file",))
    gt = {n: b for n, b in _gt_boxes(name, configuration).items() if b is not None}
    parts = {s.id for s in g.skipped}
    assert g.instances == () and parts <= set(gt)
    assert len(parts) == len(gt) - sum(1 for n in gt if n.split("/")[-1].startswith("o15_sub_asm"))
    for s in g.skipped:
        assert _flat(g.placeholder(s)) == pytest.approx(gt[s.id], abs=TOL), s.id


def test_a_stored_box_is_six_finite_numbers_or_nothing():
    assert parse_bounding_box("0 0 0 0.01 0.02 0.03") == ((0, 0, 0), (0.01, 0.02, 0.03))
    for bad in (
        None,
        "",
        "1 2 3",
        "0 0 0 1 1 1 1",
        "nan 0 0 1 1 1",
        "0 0 0 inf 1 1",
        "1 0 0 0 1 1",
        "a b c d e f",
    ):
        assert parse_bounding_box(bad) is None, bad
    assert parse_bounding_box("0 " * 2000) is None  # longer than any stored box: not parsed
    s = geo.SkippedInstance("p-1", "p-1", "2", "missing", "m")  # positional, as before
    assert s.placement is None and s.box is None and s.matrix() is None
    assert geo.DisplayGeometry(None, "none", (), {}, (s,), {}, (), ()).placeholder(s) is None


def test_the_sources_and_reasons_have_words():
    from solidseas_app.viewer import wording

    assert set(geo.SOURCES) <= set(wording.SOURCES)
    assert set(geo.REASONS) <= set(wording.NOT_SHOWN)
    assert "sub-assemblies" in wording.sources_text(["subassembly"])
