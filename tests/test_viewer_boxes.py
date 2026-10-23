"""Boxes for the instances an assembly has no mesh for, in the SolidSeas Viewer's 3D view.

Where the library places an instance but finds no mesh to draw it with (its file
is not found, it stores no display data, a limit was reached), it gives the box
the assembly stores for it. The mesh process turns each into a matrix that takes
a unit cube to that box in the assembly (``mesh3d.BoxBuffers``), and the view
draws them as one more mesh of the scene, the last: translucent grey with dark
edges, on both drawing paths, exploded, picked and opened like any other
instance. These tests craft fixture assemblies whose own meshes are left out and
whose component files cannot be found (the stored paths point into a folder that
does not exist), so every part of them, or every one but o15's two, is drawn as
a box; each box must land on the box SOLIDWORKS reported for that instance
(``ground_truth.json``). Then the Preview tab with a stand-in for the OpenGL
view (the status line, the legend, the hover text, the setting that turns the
boxes off, picking, Back), instances read from a sub-assembly's own file that
the Components tab does not list, the real view on the display, and the
self-test's ``--boxes``.

Every test that reads files checks that none of them changed.
"""

import json
import math
import os
import re
import shutil
import time
from array import array
from pathlib import Path

import pytest

from builders import TreeXml, assembly_with_tree, build_modern, fixture_streams, rebuild
from gl_support import run_gl, run_self_test
from solidseas import open_document
from solidseas_app.viewer import explode, mesh3d, opening, wording
from support import FIXTURES, fixture_path
from test_viewer import Viewer, _state, _stub_view_factory, _wait, needs_qt

O08, O15, O16 = "o08_asm_2x_boxA.SLDASM", "o15_sub_asm.SLDASM", "o16_asm_features.SLDASM"
INNER = ("o15_sub_asm-1/o02_boxA-1", "o15_sub_asm-1/o07_boxB_h31-1")  # o15's parts in o16
VIRTUAL = "Part12^o16_asm_features-1"  # stored inside o16, with no mesh of its own (and here no bodies)
GT = json.loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))
TOL = 1e-6


def gt_boxes(name: str, configuration: str = "Default") -> dict[str, list[float]]:
    comps = GT[name]["api"]["configurations"][configuration]["components"]
    return {c["name"]: c["box_m"] for c in comps if c["box_m"] is not None}


def unreachable(name: str, gone: Path, *, own_meshes: bool = False) -> bytes:
    """Fixture assembly ``name`` with every component file's stored path moved into the
    folder ``gone``, which does not exist, so no part file is found anywhere; virtual
    components keep theirs. Without ``own_meshes`` its FaceTessellations, the meshes it
    stores of its components, are left out too, and the virtual parts stored inside it
    lose their Parasolid bodies, so that nothing draws them but a box."""
    streams = fixture_streams(fixture_path(name))
    tree = streams["swXmlContents/COMPINSTANCETREE"].decode("utf-8")

    def moved(m: re.Match) -> str:
        base = m.group(1).replace("/", "\\").rpartition("\\")[2]
        return m.group(0) if "^" in base else 'swPath="' + str(gone / base).replace('"', "") + '"'

    tree = re.sub(r'swPath="([^"]*)"', moved, tree)
    changes = {"swXmlContents/COMPINSTANCETREE": tree.encode("utf-8")}
    drop: tuple[str, ...] = ()
    if not own_meshes:
        drop = tuple(n for n in streams if n.startswith("FaceTessellations/"))
        for n, data in streams.items():
            if n.startswith("VirtualComp/"):
                inner = fixture_streams(data)
                changes[n] = build_modern({k: v for k, v in inner.items() if "-Partition" not in k})
    return rebuild(fixture_path(name), changes, drop=drop)


def crafted(tmp_path: Path, *, with_o15: bool = True, name: str = "jobs") -> Path:
    """A folder holding o16 without its meshes or any part file it names; with ``with_o15``
    also o15, whose own meshes give o15's two parts in o16. The rest of o16 is boxes."""
    folder = tmp_path / name
    folder.mkdir()
    gone = tmp_path / "gone"
    (folder / O16).write_bytes(unreachable(O16, gone))
    if with_o15:
        (folder / O15).write_bytes(unreachable(O15, gone, own_meshes=True))
    return folder


def _read(folder: Path, name: str = O16, cap: int = 1_000_000, **kw) -> dict:
    return mesh3d.read_assembly_scene(str(folder / name), str(folder), str(folder), cap, **kw)


def _boxes_of(raw: bytes) -> list[list[float]]:
    b = array("f")
    b.frombytes(raw)
    return [list(b[k : k + 6]) for k in range(0, len(b), 6)]


def _flat(box) -> list[float]:
    return [*box[0], *box[1]]


def _union(boxes: list[list[float]]) -> list[float]:
    return [min(b[i] for b in boxes) for i in range(3)] + [max(b[3 + i] for b in boxes) for i in range(3)]


def _corners(matrix, lo, hi) -> list[float]:
    """The box of ``lo``-``hi`` corners carried by the column-major ``matrix``."""
    pts = [
        [matrix[i] * x + matrix[4 + i] * y + matrix[8 + i] * z + matrix[12 + i] for i in range(3)]
        for x in (lo[0], hi[0])
        for y in (lo[1], hi[1])
        for z in (lo[2], hi[2])
    ]
    return [min(p[i] for p in pts) for i in range(3)] + [max(p[i] for p in pts) for i in range(3)]


# --------------------------------------------------------------------------- the read, no Qt
@pytest.mark.parametrize("with_o15", [True, False])
def test_each_box_lands_on_the_box_solidworks_gave_the_instance(tmp_path, with_o15):
    """o16 with no mesh of its own and no part file: o15's parts come from o15's meshes
    when o15 is there, and every other part is a box. Each box (its unit-cube matrix
    applied, and its bounds) is SOLIDWORKS' box of that instance; with nothing drawn from
    a mesh, the read still gives the boxes."""
    folder = crafted(tmp_path, with_o15=with_o15)
    before = _state(folder)
    result = _read(folder)
    assert result["state"] == "ok"
    scene, geo = result["data"], result["geometry"]
    gt = gt_boxes(O16)
    meshes = [i for ids in scene.instance_ids for i in ids]
    assert meshes == (list(INNER) if with_o15 else [])
    assert geo["placed"] == len(meshes) and not geo["too_large"]
    b = scene.boxes
    expected = {n for n in gt if n not in meshes and n != "o15_sub_asm-1"}
    assert len(b) == b.count == geo["placeholders"]["count"] == len(expected) == (10 if with_o15 else 12)
    assert set(b.ids) == expected and b.ids == geo["placeholders"]["ids"]
    reasons = dict(zip(b.ids, b.reasons, strict=True))
    assert reasons.pop(VIRTUAL) == "no_mesh" and set(reasons.values()) == {"missing"}
    names = dict(zip(b.ids, b.names, strict=True))
    assert names["o02_boxA-2"] == "o02_boxA.SLDPRT" and names[VIRTUAL] == "Part12^o16_asm_features.SLDPRT"
    m = array("f")
    m.frombytes(b.matrices)
    for k, (iid, box) in enumerate(zip(b.ids, _boxes_of(b.bounds), strict=True)):
        assert box == pytest.approx(gt[iid], abs=TOL), iid
        assert _corners(m[16 * k : 16 * k + 16], (0, 0, 0), (1, 1, 1)) == pytest.approx(gt[iid], abs=TOL), iid
    # The boxes' box holds them all; the scene's, its meshes (or the boxes, with none).
    assert _flat(b.bbox) == pytest.approx(_union([gt[i] for i in b.ids]), abs=TOL)
    drawn = [gt[i] for i in meshes] or [gt[i] for i in b.ids]
    assert _flat(scene.bbox) == pytest.approx(_union(drawn), abs=TOL)
    # Every instance not shown at all is named before those drawn as boxes: here there are none.
    assert [s["id"] for s in geo["skipped"]] == b.ids
    assert _state(folder) == before


@pytest.mark.parametrize(("name", "configuration"), [(O08, "Default"), (O15, "Default"), (O16, "Lite")])
def test_every_fixture_without_meshes_is_drawn_as_boxes_where_solidworks_put_them(
    tmp_path, name, configuration
):
    folder = tmp_path / "jobs"
    folder.mkdir()
    (folder / name).write_bytes(unreachable(name, tmp_path / "gone"))
    before = _state(folder)
    result = _read(folder, name, configuration=configuration)
    scene = result["data"]
    gt = gt_boxes(name, configuration)
    assert result["state"] == "ok" and scene.meshes == [] and scene.instance_ids == []
    assert set(scene.boxes.ids) == {n for n in gt if not n.startswith("o15_sub_asm-1") or "/" in n}
    for iid, box in zip(scene.boxes.ids, _boxes_of(scene.boxes.bounds), strict=True):
        assert box == pytest.approx(gt[iid], abs=TOL), iid
    assert _state(folder) == before


def test_a_box_matrix_takes_the_unit_cube_to_the_placed_box():
    """A placement turned 90 degrees about Z and moved, and a stored box off the origin:
    the matrix carries the unit cube's corners exactly where the placement carries the
    stored box's corners."""
    place = array("f", [0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1, 0, 0.2, 0.1, 0.05, 1])
    box = array("f", [0.01, -0.02, 0.0, 0.03, 0.02, 0.005])
    m = array("f")
    m.frombytes(mesh3d.box_matrices(place.tobytes(), box.tobytes()))
    assert len(m) == 16
    want = _corners(place, box[:3], box[3:])
    assert _corners(m, (0, 0, 0), (1, 1, 1)) == pytest.approx(want, abs=1e-6)
    assert want == pytest.approx([0.18, 0.11, 0.05, 0.22, 0.13, 0.055], abs=1e-6)
    assert mesh3d.box_buffers({"ids": []}) is None


def test_the_explode_moves_the_boxes_as_their_boxes_say(tmp_path):
    """The boxes are instances of the exploded view like the others: their groups' offsets
    come from their boxes, here equal to SOLIDWORKS' boxes, at both levels."""
    folder = crafted(tmp_path)
    scene = _read(folder)["data"]
    ids = [*scene.instance_ids, scene.boxes.ids]
    gt = gt_boxes(O16)
    gt_bounds = [array("f", [v for i in group for v in gt[i]]).tobytes() for group in ids]
    for level in explode.LEVELS:
        got = explode.explode(ids, [*scene.bounds, scene.boxes.bounds], level)
        want = explode.explode(ids, gt_bounds, level)
        assert got.groups == want.groups and got.moving == want.moving > 0
        for a, b in zip(got.offsets, want.offsets, strict=True):
            assert list(a) == pytest.approx(list(b), abs=1e-5)
    assert explode.explode(ids, gt_bounds, explode.TOP).groups == 11  # o15 and its two parts are one


def test_the_status_line_counts_the_boxes_and_names_the_rest():
    info = {
        "skipped_count": 4,
        "skipped": [
            {"id": "cut-1", "name": "cut-1", "reason": "no_placement"},
            {"id": "a-1", "name": "a-1", "reason": "missing"},
            {"id": "a-2", "name": "a-2", "reason": "missing"},
            {"id": "v-1", "name": "v-1", "reason": "no_mesh"},
        ],
        "placeholders": {
            "count": 3,
            "ids": ["a-1", "a-2", "v-1"],
            "reasons": ["missing", "missing", "no_mesh"],
        },
    }
    text, full = wording.not_shown_text(info, boxes=True)
    assert text == (
        "Drawn as boxes, with no mesh drawn: 3 instances (file not found: 2, no saved display mesh: 1). "
        "Not shown: 1 instance: cut-1 (position could not be read)."
    )
    assert full.splitlines() == [
        "drawn as a box, file not found: a-1, a-2",
        "drawn as a box, no saved display mesh: v-1",
        "position could not be read: cut-1",
    ]
    off, _ = wording.not_shown_text(info)  # the boxes turned off: all four are not shown
    assert off.startswith("Not shown: 4 instances: cut-1 (position could not be read); a-1, a-2 (file not")
    assert off.endswith("Settings > Boxes for Missing Meshes draws 3 of them as boxes.")
    # However many, the line counts the boxes by reason, and the tooltip names the first 200.
    many = {
        "skipped_count": 5000,
        "skipped": [{"id": f"p-{n}", "name": f"p-{n}", "reason": "no_mesh"} for n in range(500)],
        "placeholders": {
            "count": 5000,
            "ids": [f"p-{n}" for n in range(5000)],
            "reasons": ["no_mesh"] * 4000 + ["missing"] * 1000,
        },
    }
    text, full = wording.not_shown_text(many, boxes=True)
    assert text == (
        "Drawn as boxes, with no mesh drawn: 5,000 instances (no saved display mesh: 4,000, file not "
        "found: 1,000)."
    )
    assert full.splitlines()[0].endswith("p-59 and 3,940 more")
    assert full.endswith("p-4059 and 940 more")
    # Not shown for many reasons: six names in all, then counts.
    reasons = ("missing", "no_mesh", "unreadable", "cycle")
    spread = {
        "skipped_count": 12,
        "skipped": [{"id": f"{r}-{n}", "name": f"{r}-{n}", "reason": r} for r in reasons for n in range(3)],
    }
    text, _ = wording.not_shown_text(spread)
    assert text == (
        "Not shown: 12 instances: missing-0, missing-1, missing-2 (file not found); no_mesh-0, no_mesh-1, "
        "no_mesh-2 (no saved display mesh); 3 (file could not be read); 3 (sub-assembly contains itself)."
    )
    # Long paths are named until about 200 characters are spent, the rest counted.
    deep = [f"{'sub-1/' * 20}p-{n}" for n in range(4)]
    long = {"skipped_count": 4, "skipped": [{"id": i, "name": "p", "reason": "missing"} for i in deep]}
    text, full = wording.not_shown_text(long)
    assert text == f"Not shown: 4 instances: {deep[0]}, {deep[1]} and 2 more (file not found)."
    assert full == "file not found: " + ", ".join(deep)
    # Components shown in another configuration than the one used: one sentence for several.
    several = {
        "mesh_warnings": [
            {"file": f"p{n}.SLDPRT", "code": "mesh_configuration_differs", "message": "m"} for n in range(5)
        ]
    }
    text, full = wording.not_shown_text(several)
    assert text == (
        "5 components (p0.SLDPRT, p1.SLDPRT, p2.SLDPRT and 2 more) show the configuration their own files "
        "were saved in, which is not the one the assembly uses, so their shapes may differ."
    )
    assert full == "shape may differ, another configuration: " + ", ".join(f"p{n}.SLDPRT" for n in range(5))
    assert wording.box_text("p-1", "p.SLDPRT", "missing") == (
        "p-1 (p.SLDPRT): no mesh drawn (file not found), so it is drawn as the box its assembly stores"
    )
    assert wording.box_text("p-1", None, "an_odd_one").startswith("p-1: no mesh drawn (an odd one)")


def test_a_stored_box_no_model_could_have_is_not_drawn(tmp_path):
    """A component model's stored box that is damaged (beyond 10 km, past what float32
    holds, or far outside the box the assembly stores for itself) would take the camera
    away from the model, or turn into a matrix of NaNs: it is not drawn, the line says
    so, and the camera fits the rest. An ordinary box beside them is drawn."""
    t = TreeXml()
    t.top("m1")
    t.models["m1"]["attrs"]["swBoundingBox"] = "0 0 0 0.05 0.05 0.05"  # the assembly's own box
    boxes = {
        "p": "0 0 0 0.01 0.02 0.03",
        "huge": "0 0 0 1e30 1e30 1e30",
        "overflow": "-1e39 0 0 0.01 0.01 0.01",
        "far": "0 0 0 1000 1000 1000",
        "near": "0 0 0 0.01 0.01 0.01",
    }
    for k, (name, box) in enumerate(boxes.items()):
        fid = str(k + 2)
        t.file(fid, f"{name}.SLDPRT")
        t.model(f"m{fid}", fid, bbox=box)
        t.ref("m1", name, 1, f"m{fid}")
    folder = tmp_path / "jobs"
    folder.mkdir()
    (folder / "top.SLDASM").write_bytes(assembly_with_tree(t))
    shutil.copy2(fixture_path("o02_boxA.SLDPRT"), folder / "p.SLDPRT")
    before = _state(folder)
    result = _read(folder, "top.SLDASM")
    scene, geometry = result["data"], result["geometry"]
    assert [i for ids in scene.instance_ids for i in ids] == ["p-1"]
    assert scene.boxes.ids == ["near-1"] and scene.boxes.count == 1
    ph = geometry["placeholders"]
    assert ph["count"] == 1 and ph["implausible"] == 3
    assert _flat(scene.bbox) == pytest.approx([0, 0, 0, 0.01, 0.02, 0.03], abs=TOL)
    assert all(math.isfinite(v) for v in array("f", scene.boxes.matrices))
    text, _ = wording.not_shown_text(geometry, boxes=True)
    assert "3 stored boxes reaching far past the assembly's own are taken as damaged and not drawn." in text
    assert "huge-1 (file not found)" in text or "huge-1, " in text  # still named, with its reason
    # The rule alone: 10 km from the origin, and ten diagonals past the assembly's own box.
    own = ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
    assert mesh3d.plausible(((9e3, 0, 0), (9.9e3, 1, 1)))
    assert not mesh3d.plausible(((0, 0, 0), (1.1e4, 1, 1)))
    assert not mesh3d.plausible(((0, 0, 0), (math.inf, 1, 1)))
    assert mesh3d.plausible(((-17, 0, 0), (1, 1, 1)), own)  # the diagonal is 1.73
    assert not mesh3d.plausible(((-18, 0, 0), (1, 1, 1)), own)
    assert _state(folder) == before


def test_a_file_read_from_a_sub_assemblys_own_file_is_drawn_as_the_file_it_is(tmp_path):
    """An assembly lists o15 without its components and o02 at the top level: o15's own
    o02, read from o15's file (where its stored path is another folder's), is the same
    file, so the legend has one row and one colour for o02 with both instances (its keys
    the top's and o15's), not two."""
    with open_document(fixture_path(O16)) as doc:
        tf = {n.id: " ".join(repr(v) for v in n.transform.stored) for n in doc.components().walk()}
    t = TreeXml()
    t.top("m1")
    t.file("2", O15, "ASSEMBLY")
    t.file("3", "o02_boxA.SLDPRT")
    t.model("m2", "2", bbox="0 -0.031 0 0.04 0.02 0.03")
    t.model("m3", "3", bbox="0 0 0 0.01 0.02 0.03")
    t.ref("m1", "o15_sub_asm", 1, "m2", transform=tf["o15_sub_asm-1"])
    t.ref("m1", "o02_boxA", 1, "m3", transform=tf["o02_boxA-1"])
    folder = tmp_path / "jobs"
    folder.mkdir()
    (folder / "top.SLDASM").write_bytes(assembly_with_tree(t))
    (folder / O15).write_bytes(unreachable(O15, tmp_path / "gone", own_meshes=True))
    shutil.copy2(fixture_path("o02_boxA.SLDPRT"), folder / "o02_boxA.SLDPRT")
    before = _state(folder)
    result = _read(folder, "top.SLDASM")
    scene = result["data"]
    names = [(f["name"], f["instances"], f["key"], len(f["keys"])) for f in scene.files]
    assert sorted(names) == [("o02_boxA.SLDPRT", 2, "3", 2), ("o07_boxB_h31.SLDPRT", 1, "2/9", 1)]
    o02 = next(f for f in scene.files if f["key"] == "3")
    assert o02["keys"][-1] == "2/6" and len({f["color"] for f in scene.files}) == 2
    assert result["geometry"]["placed"] == 3
    assert _state(folder) == before


@needs_qt
def test_the_boxes_setting_is_kept_with_the_others(tmp_path):
    from solidseas_app.viewer.settings import Settings, SettingsStore

    assert Settings().draw_boxes is True
    path = tmp_path / "Viewer.ini"
    store = SettingsStore(str(path))
    assert store.save(Settings(view_3d=True, draw_boxes=False))
    assert "draw_boxes=false" in path.read_text(encoding="utf-8")
    assert SettingsStore(str(path)).load() == Settings(view_3d=True, draw_boxes=False)
    path.write_text("[Preferences]\ndraw_boxes=sometimes\n", encoding="utf-8")
    again = SettingsStore(str(path))
    assert again.load().draw_boxes is True and again.reset_keys == ["draw_boxes"]


# --------------------------------------------------------------------------- the mesh process
@needs_qt
def test_the_mesh_process_carries_the_boxes(tmp_path):
    from solidseas_app.viewer import meshproc

    folder = crafted(tmp_path)
    alone = crafted(tmp_path, with_o15=False, name="alone")
    before = _state(tmp_path)
    reader = meshproc.MeshReader()
    try:
        for f in (folder, alone):
            got = reader.read(str(f / O16), str(f), 1_000_000, assembly=True, cache_key=str(f))
            here = _read(f)["data"]
            assert got["state"] == "ok"
            b, h = got["data"].boxes, here.boxes
            assert (b.ids, b.files, b.names, b.reasons, b.count) == (
                h.ids,
                h.files,
                h.names,
                h.reasons,
                h.count,
            )
            assert (b.matrices, b.bounds, b.bbox) == (h.matrices, h.bounds, h.bbox)
            assert got["data"].instance_ids == here.instance_ids and got["data"].bbox == here.bbox
    finally:
        reader.close()
    assert _state(tmp_path) == before


# --------------------------------------------------------------------------- the Preview tab, a stand-in view
@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from solidseas_app.viewer.app import use_system_fonts

    use_system_fonts()
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def viewer(app):
    v = Viewer(app)
    yield v
    v.close()


def _show(viewer, name: str) -> None:
    from solidseas_app.viewer.details import TABS

    w = viewer.window
    w.details.tabs.setCurrentIndex(TABS.index("Preview"))
    viewer.select(name)
    _wait(viewer.app, lambda: w.details.preview.mesh_state not in ("starting", "loading") and not w.busy)


def _in_3d(viewer, folder: Path, name: str = O16):
    w = viewer.window
    pane = w.details.preview
    made: list = []
    pane.view_factory = _stub_view_factory(made)
    pane.gl_check = lambda: (True, "test")
    viewer.open(folder)
    w.change_settings(view_3d=True)
    _show(viewer, name)
    return w, pane, made


def _current(w) -> str | None:
    from solidseas_app.viewer.details import IDENT_ROLE

    item = w.details.instances.currentItem()
    return item.data(0, IDENT_ROLE) if item is not None else None


def _legend(pane) -> list[str]:
    return [pane.legend.item(i).text() for i in range(pane.legend.count())]


@needs_qt
def test_the_preview_draws_a_box_for_each_instance_without_a_mesh(viewer, tmp_path):
    """The boxes come after the meshes' instances; the legend's last row stands for them
    and picks them all; the caption and the status line count them; a box is named on
    hover, picked with its row on the Components tab, and a row of the Files table picks
    the boxes of its file too. Settings > Boxes for Missing Meshes draws the assembly
    again without them, from the same read, keeping the camera and the pick, and saves
    the choice."""
    folder = crafted(tmp_path)
    before = _state(folder)
    w, pane, made = _in_3d(viewer, folder)
    view = made[-1]
    assert pane.mesh_state == "ready" and view.boxes is True and view.assembly.n_instances == 2
    ids = pane.instance_ids
    assert ids[:2] == list(INNER) and pane.box_from == 2 and len(ids) == 12
    assert ids[2:] == view.assembly.boxes.ids and pane.is_box(2) and not pane.is_box(1)
    assert _legend(pane)[-1] == "Box: no mesh drawn (10)" and len(_legend(pane)) == 3
    assert pane.status.text() == (
        "Drawn as boxes, with no mesh drawn: 10 instances (file not found: 9, no saved display mesh: 1)."
    )
    assert "drawn as a box, file not found: o02_boxA-1, " in pane.status.toolTip()
    assert ", and 10 boxes for instances with no mesh, read in " in pane.caption.text()
    assert pane.explode_groups == {"top": 11, "parts": 12}
    box = ids.index("o02_boxA-2")
    assert view.describe(box) == (
        "o02_boxA-2 (o02_boxA.SLDPRT): no mesh drawn (file not found), so it is drawn as the box its "
        "assembly stores"
    )
    assert view.describe(0) == f"{INNER[0]} (o02_boxA.SLDPRT)"

    # A box is picked like any instance, with its row on the Components tab.
    view.picked.emit(box)
    assert _current(w) == "o02_boxA-2" and view.selected == {box}
    assert pane.pick_note.text() == (
        "Picked: o02_boxA-2 (o02_boxA.SLDPRT): no mesh drawn (file not found), so it is drawn as the box "
        "its assembly stores. Double-click it to open its file."
    )
    ft = w.details.files
    files = {ft.topLevelItem(i).text(0): ft.topLevelItem(i) for i in range(ft.topLevelItemCount())}
    w.details.files.setCurrentItem(files["o02_boxA.SLDPRT"])  # one drawn from o15's mesh, three boxes
    assert sorted(ids[g] for g in view.selected) == sorted(
        [INNER[0], "o02_boxA-1", "o02_boxA-2", "o02_boxA-3"]
    )
    pane.legend.itemClicked.emit(pane.legend.item(pane.legend.count() - 1))  # the boxes' row
    assert view.selected == set(range(2, 12)) and pane.highlight == ("boxes", "")
    assert _current(w) is None and w.details.files.currentItem() is None
    assert pane.pick_note.text() == "Picked: every instance drawn as a box, for want of a mesh (10)."

    # Off: drawn again without the boxes, from the same read, the camera as it was.
    places = len(w.history)
    view.picked.emit(box)
    looked = {"yaw": 70.0, "pitch": 15.0, "target": [0.01, 0.0, 0.0], "half_height": 0.04, "fitted": False}
    view.cam = dict(looked)
    shown = view.assembly
    w.act_boxes.trigger()
    assert not w.settings.draw_boxes and view.boxes is False and view.assembly is shown
    assert pane.instance_ids == list(INNER) and pane.box_from == 2 and view.cam == looked
    assert _legend(pane) == ["o02_boxA.SLDPRT (1)", "o07_boxB_h31.SLDPRT (1)"]
    assert pane.status.text().startswith("Not shown: 10 instances: o02_boxA-1, o02_boxA-2, o02_boxA-3 and 6 ")
    assert pane.status.text().endswith("Settings > Boxes for Missing Meshes draws 10 of them as boxes.")
    assert "boxes" not in pane.caption.text() and pane.explode_groups == {"top": 1, "parts": 2}
    assert view.selected == set() and pane.pick_note.text() == (
        "Picked: o02_boxA-2, which has no mesh drawn; it is drawn as a box while Settings > Boxes for "
        "Missing Meshes is on, and that is off."
    )
    w.act_boxes.trigger()  # on again: the pick comes back with its box
    assert w.settings.draw_boxes and view.boxes is True and len(pane.instance_ids) == 12
    assert view.selected == {box} and len(w.history) == places  # nothing was opened or read

    # Lite suppresses o15: every part shown there is a box, and the pick holds.
    pane.config_combo.setCurrentText("Lite")
    pane.choose_configuration("Lite")
    _wait(viewer.app, lambda: pane.mesh_state == "ready" and not w.busy and pane.configuration == "Lite")
    _wait(viewer.app, lambda: w.details.configuration_shown() == "Lite" and not w.busy)
    assert view.assembly.meshes == [] and pane.box_from == 0 and len(pane.instance_ids) == 10
    assert set(pane.instance_ids) == set(gt_boxes(O16, "Lite"))
    assert _current(w) == "o02_boxA-2" and [pane.instance_ids[g] for g in view.selected] == ["o02_boxA-2"]
    assert _state(folder) == before


@needs_qt
def test_a_box_opens_its_file_and_back_returns_to_it(viewer, tmp_path):
    """A double-click on a box goes to its file through its row, as for any instance: the
    virtual part opens from inside the assembly, and Back gives the assembly with the box
    picked, exploded as it was. A box whose file is not found says why, and the right-
    click menu is its row's."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    folder = crafted(tmp_path)
    w, pane, made = _in_3d(viewer, folder)
    view = made[-1]
    pane.set_explode(60)
    menu = w.details.instance_menu("o02_boxA-2")
    texts = [a.text() for a in menu.actions()]
    assert texts[:6] == [
        f"{opening.OPEN_TEXT} (not found)",
        f"{opening.show_text()} (not found)",
        "",
        "Go to file",
        "Show in folder list (not found)",
        "Show on Components tab",
    ]
    # Its file is nowhere, as its row's menu says.
    assert [a.isEnabled() for a in menu.actions()[:5]] == [False, False, True, True, False]
    menu.deleteLater()
    asked: list = []
    w.details.componentRequested.connect(lambda *a: asked.append(a))
    view.activated.emit(pane.instance_ids.index(VIRTUAL))
    _wait(viewer.app, lambda: not w.busy and pane.mesh_state not in ("starting", "loading"))
    assert asked[-1][1] == "open" and w.apart is not None
    assert w.details.title.text() == "Part12^o16_asm_features.SLDPRT"
    assert w.go_back()
    _wait(viewer.app, lambda: not w.busy and pane.mesh_state == "ready")
    assert w.details.title.text() == O16 and _current(w) == VIRTUAL
    assert [pane.instance_ids[g] for g in view.selected] == [VIRTUAL] and pane.explode_value == 60

    # The file of o02_boxA-2 is nowhere: the window says so and stays.
    said: list = []

    def close_it() -> None:
        box = QApplication.activeModalWidget()
        said.append(box.text() if box is not None else None)
        if box is not None:
            box.close()

    QTimer.singleShot(200, close_it)
    generation = w.generation
    view.activated.emit(pane.instance_ids.index("o02_boxA-2"))
    assert said and "o02_boxA.SLDPRT cannot be opened from here" in said[0]
    assert w.generation == generation and _current(w) == "o02_boxA-2"


@needs_qt
def test_an_assembly_of_nothing_but_boxes(viewer, tmp_path):
    """With no mesh at all, the boxes are the scene; turned off, the view says there is
    nothing to draw and how to see the boxes, and turned on they are back."""
    folder = crafted(tmp_path, with_o15=False)
    w, pane, made = _in_3d(viewer, folder)
    view = made[-1]
    assert pane.mesh_state == "ready" and view.assembly.meshes == [] and len(pane.instance_ids) == 12
    assert pane.box_from == 0 and _legend(pane) == ["Box: no mesh drawn (12)"]
    assert pane.caption.text().startswith("No mesh to draw: 12 boxes stand in for the instances, read in ")
    w.change_settings(draw_boxes=False)
    assert pane.mesh_state == "no_mesh" and pane.instance_ids == []
    assert pane.model_message.text().startswith("Nothing to draw: no instance of this assembly configuration")
    assert "Settings > Boxes for Missing Meshes draws 12 of them as boxes." in pane.model_message.text()
    assert pane.model_stack.currentWidget() is pane.model_message
    w.change_settings(draw_boxes=True)
    assert pane.mesh_state == "ready" and pane.model_stack.currentWidget() is view and view.boxes is True

    # Over the triangle limit, every mesh is a box too; off, the view says the limit stopped it.
    w.settings = w.settings.but(triangle_cap=11)  # below any real setting, to see it
    viewer.open(FIXTURES)
    _show(viewer, O16)
    assert pane.mesh_state == "ready" and view.assembly.meshes == [] and len(view.assembly.boxes) == 12
    w.change_settings(draw_boxes=False)
    assert (
        pane.mesh_state == "too_large" and "more than the 3D view's limit of 11" in pane.model_message.text()
    )
    w.change_settings(triangle_cap=1_000_000)  # a higher limit reads it again
    _wait(viewer.app, lambda: pane.mesh_state == "ready" and not w.busy)
    assert view.assembly.n_instances == 12 and view.assembly.boxes is None


def _unlisted_top(tmp_path: Path, *, boxes: bool) -> Path:
    """A folder with an assembly whose tree names o15 and nothing inside it, and o15:
    o15's two parts are read from o15's own file, from its meshes or, with ``boxes``,
    as the boxes its own tree stores (o15 then has no mesh and no part file)."""
    with open_document(fixture_path(O16)) as doc:
        tf = {n.id: " ".join(repr(v) for v in n.transform.stored) for n in doc.components().walk()}
    t = TreeXml()
    t.top("m1")
    t.file("2", O15, "ASSEMBLY")
    t.model("m2", "2", bbox="0 -0.031 0 0.04 0.02 0.03")
    t.ref("m1", "o15_sub_asm", 1, "m2", transform=tf["o15_sub_asm-1"])
    folder = tmp_path / ("boxes" if boxes else "meshes")
    folder.mkdir()
    (folder / "top.SLDASM").write_bytes(assembly_with_tree(t))
    (folder / O15).write_bytes(unreachable(O15, tmp_path / "gone", own_meshes=not boxes))
    return folder


@needs_qt
@pytest.mark.parametrize("boxes", [False, True])
def test_an_instance_read_from_a_sub_assemblys_own_file_has_a_row_and_is_opened(viewer, tmp_path, boxes):
    """o15's parts, read from o15's own file, which the top assembly's tree does not list,
    get rows under o15's on the Components tab: a click picks one in the view and makes
    its row current, its menu is its own, and a double-click says its file is not in the
    folder and offers o15, which opens; Back puts the pick and its row back. Drawn from
    o15's meshes or as the boxes o15 stores, on SOLIDWORKS' boxes."""
    folder = _unlisted_top(tmp_path, boxes=boxes)
    before = _state(folder)
    w, pane, made = _in_3d(viewer, folder, "top.SLDASM")
    view = made[-1]
    assert sorted(pane.instance_ids) == sorted(INNER) and pane.box_from == (0 if boxes else 2)
    if boxes:
        gt = gt_boxes(O16)
        for iid, box in zip(view.assembly.boxes.ids, _boxes_of(view.assembly.boxes.bounds), strict=True):
            assert box == pytest.approx(gt[iid], abs=TOL), iid
    g = pane.instance_ids.index(INNER[1])
    assert "o07_boxB_h31.SLDPRT" in view.describe(g)
    host = w.details.instance_item("o15_sub_asm-1")
    assert [host.child(k).text(0) for k in range(host.childCount())] == [i.split("/")[-1] for i in INNER]
    w.details.instances.setCurrentItem(host)  # a row, to see the pick move from it
    view.picked.emit(g)
    assert view.selected == {g} and _current(w) == INNER[1] and pane.highlight == ("instance", INNER[1])
    assert pane.pick_note.text().endswith("Double-click it to open its file.")
    assert w.details.row_of(INNER[1]) == INNER[1] and w.details.row_of("nothing-1/x-1") is None
    menu = w.details.instance_menu(INNER[1])
    texts = [a.text() for a in menu.actions()]
    assert texts[:6] == [
        f"{opening.OPEN_TEXT} (not found)",
        f"{opening.show_text()} (not found)",
        "",
        "Go to file",
        "Show in folder list (not found)",
        "Show on Components tab",
    ]
    menu.deleteLater()
    told: list = []
    w.explain = lambda title, text, offer=None: told.append((text, offer)) or True  # takes the offer
    view.activated.emit(g)
    _wait(viewer.app, lambda: not w.busy and pane.mesh_state not in ("starting", "loading"))
    ((text, offer),) = told
    assert offer == "Open the Sub-assembly" and text.startswith("o07_boxB_h31.SLDPRT cannot be opened")
    assert w.details.title.text() == O15
    assert w.go_back()
    _wait(viewer.app, lambda: not w.busy and pane.mesh_state == "ready")
    assert w.details.title.text() == "top.SLDASM" and _current(w) == INNER[1]
    assert pane.highlight == ("instance", INNER[1]) and view.selected == {pane.instance_ids.index(INNER[1])}
    # The sub-assembly's row picks the parts read from its file.
    w.details.instances.setCurrentItem(w.details.instance_item("o15_sub_asm-1"))
    assert sorted(pane.instance_ids[k] for k in view.selected) == sorted(INNER)
    # A key of a file read from o15's own file picks what the file's row of the legend does.
    o02 = next(f for f in pane.files if f["name"] == "o02_boxA.SLDPRT") if not boxes else None
    if o02 is not None:
        pane.highlight_file(o02["keys"][-1])
        assert [pane.instance_ids[k] for k in view.selected] == [INNER[0]]
    assert _state(folder) == before


@needs_qt
def test_the_self_test_picks_an_instance_read_from_a_sub_assemblys_own_file(tmp_path):
    """``--pick`` of a part read from a sub-assembly's own file: the click picks it and
    makes its row current, the row the 3D view's read gave it under the sub-assembly's;
    the double-click opens the part's file, found in the folder, and Back returns to the
    pick and its row."""
    folder = _unlisted_top(tmp_path, boxes=False)
    shutil.copy2(fixture_path("o07_boxB_h31.SLDPRT"), folder / "o07_boxB_h31.SLDPRT")
    before = _state(folder)
    shots = tmp_path / "shots"
    args = ["--self-test", str(folder), "--screenshot-dir", str(shots), "--select", "top.SLDASM", "--3d"]
    args += ["--boxes", "--pick", INNER[1]]
    report = run_self_test(args, shots, appdata=tmp_path / "Roaming")
    (doc,) = report["documents"]
    assert doc["errors"] == []
    (picked,) = doc["picked"]
    assert picked["picked"] == [INNER[1]] and picked["components_tab"] == INNER[1]
    assert picked["row"] == INNER[1] and picked["outcome"] == "listed" and picked["back"]
    assert picked["shown"] == "o07_boxB_h31.SLDPRT" and picked["picked_after_back"] == [INNER[1]]
    assert _state(folder) == before


# --------------------------------------------------------------------------- OpenGL, on the real display
_GL_BOXES = """
import os
from array import array
from PySide6.QtGui import QColor
from solidseas_app.viewer import explode, mesh3d
path, folder, gt_path = sys.argv[1], sys.argv[2], sys.argv[3]
with open(gt_path, encoding="utf-8") as fh:
    gt = json.load(fh)["o16_asm_features.SLDASM"]["api"]["configurations"]["Default"]["components"]
boxes = {c["name"]: c["box_m"] for c in gt}
scene = mesh3d.read_assembly_scene(path, folder, folder, 1_000_000)["data"]
ids = [*scene.instance_ids, scene.boxes.ids]
gt_bounds = [array("f", [v for i in group for v in boxes[i]]).tobytes() for group in ids]
flat = [i for group in ids for i in group]
out = {"gl": True, "ids": flat}
for instanced in (True, False):
    view3d.Renderer.allow_instancing = instanced
    view = view3d.ModelView()
    view.resize(480, 360)
    view.show()
    view.set_assembly(scene)
    app.processEvents()
    for level in explode.LEVELS:
        view.set_explode_level(level)
        e = explode.explode(ids, gt_bounds, level)
        for t in (0.0, 1.0):
            view.explode_to(t, animate=False)
            app.processEvents()
            w, h = view.width(), view.height()
            drawn = {}
            for k, i in enumerate(view._id_pass((0.0, 0.0, 1.0, 1.0), (w, h)) or []):
                if i is not None:
                    x, y = k % w + 0.5, k // w + 0.5
                    r = drawn.setdefault(i, [x, y, x, y])
                    r[:] = [min(r[0], x), min(r[1], y), max(r[2], x), max(r[3], y)]
            rows, g = [], 0
            for m, group in enumerate(ids):
                for k, iid in enumerate(group):
                    b, d = boxes[iid], e.offset(m, k)
                    px = []
                    for x in (b[0], b[3]):
                        for y in (b[1], b[4]):
                            for z in (b[2], b[5]):
                                nx, ny, _ = view.camera.project((x + t * d[0], y + t * d[1], z + t * d[2]))
                                px.append(((nx + 1) * w / 2, (1 - ny) * h / 2))
                    xs, ys = [p[0] for p in px], [p[1] for p in px]
                    want = [min(xs), min(ys), max(xs), max(ys)]
                    hit = view.instance_at((want[0] + want[2]) / 2, (want[1] + want[3]) / 2)
                    rows.append({"id": iid, "drawn": drawn.get(g), "want": want, "at_centre": hit})
                    g += 1
            out[f"{instanced} {level} {t}"] = rows
            out[f"{instanced} {level} {t} report"] = view.box_report()
    # How a box looks, collapsed: grey faces between the background and its dark edges.
    view.explode_to(0.0, animate=False)
    img = view.grabFramebuffer()
    k = scene.n_instances + scene.boxes.ids.index("o06_boxA_props_mat_cfg-1")
    p = view.pixel_of(k)
    out[f"{instanced} look"] = {
        "face": img.pixelColor(int(p[0]), int(p[1])).name(),
        "background": img.pixelColor(1, 1).name(),
        "colours": sorted({img.pixelColor(x, y).name() for y in range(0, 360, 2) for x in range(0, 480, 2)}),
        "instanced": view.renderer.instanced,
        "boxes": view.renderer.boxes,
        "error": view.error,
    }
    view.set_assembly(scene, boxes=False)
    app.processEvents()
    view.grabFramebuffer()  # a frame, even where the window is never shown (an SSH session)
    report = view.box_report()
    r = view.renderer
    out[f"{instanced} off"] = {"boxes": r.boxes, "report": report, "instances": r.instances}
print(json.dumps(out))
"""


def _rgb(name: str) -> tuple[int, int, int]:
    return int(name[1:3], 16), int(name[3:5], 16), int(name[5:7], 16)


@needs_qt
def test_the_boxes_are_drawn_on_solidworks_boxes_on_the_display(tmp_path):
    """On the real display, instanced and one instance at a time: every instance, the two
    meshes and the ten boxes, is drawn inside SOLIDWORKS' box of it projected with the
    view's camera (moved by the explode offset made from those boxes), collapsed and fully
    exploded at both levels, and a click at its middle picks it. A box is a light grey,
    neither a component colour nor the background, with darker edges; turned off, no box
    is drawn."""
    folder = crafted(tmp_path)
    before = _state(folder)
    out = run_gl(_GL_BOXES, str(folder / O16), str(folder), str(FIXTURES / "ground_truth.json"))
    tol = 1.0
    for instanced in ("True", "False"):
        for level in ("top", "parts"):
            for t in ("0.0", "1.0"):
                rows = out[f"{instanced} {level} {t}"]
                assert len(rows) == 12
                for g, r in enumerate(rows):
                    where = (instanced, level, t, r["id"])
                    assert r["drawn"] is not None, where
                    (x0, y0, x1, y1), (a0, b0, a1, b1) = r["drawn"], r["want"]
                    assert a0 - tol <= x0 and x1 <= a1 + tol and b0 - tol <= y0 and y1 <= b1 + tol, (where, r)
                    assert x0 <= a0 + 0.5 * (a1 - a0) <= x1 and y0 <= b0 + 0.5 * (b1 - b0) <= y1, (where, r)
                    assert r["at_centre"] == g, where
                report = out[f"{instanced} {level} {t} report"]
                assert report == {"boxes": 10, "visible": 10, "outside": [], "subpixel": [], "missing": []}
        look = out[f"{instanced} look"]
        assert look["error"] is None and look["boxes"] == 10
        face, bg = _rgb(look["face"]), _rgb(look["background"])
        assert max(face) - min(face) < 30 and face != bg  # grey, not the background
        # Dark grey lines: the component colours, however shaded, are never grey.
        assert any(max(c) < min(bg) - 60 and max(c) - min(c) < 20 for c in map(_rgb, look["colours"]))
        off = out[f"{instanced} off"]
        assert off == {
            "boxes": 0,
            "report": {"boxes": 0, "visible": 0, "outside": [], "subpixel": [], "missing": []},
            "instances": 2,
        }
    assert out["False look"]["instanced"] is False
    assert _state(folder) == before


_GL_FRONT = """
from array import array
from solidseas_app.viewer import mesh3d
from solidseas_app.viewer.explode import instance_bounds

cube = view3d.BOX_MESH  # a unit cube, 0 to 1, as the one mesh
ident = array("f", (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)).tobytes()
bounds = instance_bounds(cube.bbox, ident)
out = {"gl": True}


def box_scene(boxes):
    ph = {
        "count": len(boxes),
        "ids": [f"b-{k}" for k in range(len(boxes))],
        "files": ["b"] * len(boxes),
        "names": ["b.SLDPRT"] * len(boxes),
        "reasons": ["missing"] * len(boxes),
        "matrices": array("f", (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1) * len(boxes)).tobytes(),
        "boxes": array("f", [v for b in boxes for v in b]).tobytes(),
    }
    b = mesh3d.box_buffers(ph)
    scene = mesh3d.SceneBuffers(
        meshes=[cube],
        matrices=[ident],
        files_of=[array("I", [0]).tobytes()],
        instance_ids=[["plate-1"]],
        files=[{"key": "p", "keys": ["p"], "name": "plate.SLDPRT", "instances": 1, "color": "#4e79a7"}],
        bbox=mesh3d.bounds_box([bounds, b.bounds]),
        n_instances=1,
        n_triangles=12,
        bounds=[bounds],
    )
    scene.boxes = b
    return scene


for instanced in (True, False):
    view3d.Renderer.allow_instancing = instanced
    view = view3d.ModelView()
    view.resize(600, 600)
    view.show()
    rec = {}
    # A box nearer the isometric eye than the cube: a click on it picks the box.
    view.set_assembly(box_scene([(1.2, 1.2, 1.2, 1.4, 1.4, 1.4)]))
    app.processEvents()
    w, h = view.width(), view.height()
    nx, ny, _ = view.camera.project((1.3, 1.3, 1.3))
    rec["front"] = view.instance_at((nx + 1) * w / 2, (1 - ny) * h / 2)
    rec["front_pixel"] = view.pixel_of(1) is not None
    # A box round the cube, larger: the cube is picked through it, the box beside it.
    view.set_assembly(box_scene([(-0.5, -0.5, -0.5, 1.5, 1.5, 1.5)]))
    app.processEvents()
    nx, ny, _ = view.camera.project((0.5, 0.5, 0.5))
    rec["inside"] = view.instance_at((nx + 1) * w / 2, (1 - ny) * h / 2)
    nx, ny, _ = view.camera.project((1.5, -0.3, 1.3))  # on the box's face, clear of its outline
    rec["beside"] = view.instance_at((nx + 1) * w / 2, (1 - ny) * h / 2, radius=0)
    rec["box_pixel"] = view.pixel_of(1) is not None
    # A box far smaller than a pixel: no failure of the boxes' check, a subpixel one.
    view.set_assembly(box_scene([(0.5, 0.5, 2.0, 0.5000001, 0.5000001, 2.0000001)]))
    app.processEvents()
    rec["tiny"] = view.box_report()
    out[str(instanced)] = rec
    view.close()
print(json.dumps(out))
"""


@needs_qt
def test_a_box_in_front_is_picked_and_a_mesh_inside_one_is_picked_through_it():
    """On the real display, both drawing paths: a box nearer the eye than a mesh is
    picked where it covers it, a mesh inside a box is picked through it while the box is
    picked beside it, and a box too small to cover a pixel is reported as such."""
    out = run_gl(_GL_FRONT)
    for instanced in ("True", "False"):
        r = out[instanced]
        assert r["front"] == 1 and r["front_pixel"], r
        assert r["inside"] == 0 and r["beside"] == 1 and r["box_pixel"], r
        assert r["tiny"]["missing"] == [] and r["tiny"]["subpixel"] == [1], r


@needs_qt
def test_the_self_test_checks_and_saves_the_boxes(tmp_path):
    """``--boxes``: every box drawn where it belongs (collapsed and exploded), the view saved
    with the boxes picked and with them turned off (when none may be drawn), then on
    again. A box picked with a click is the Components tab's row; one whose file is
    nowhere gives a message and leaves the camera as it was for the next pick, and the
    virtual part opens from inside the assembly, Back returning to the same pick; the
    part drawn from o15's mesh, its file nowhere either, is picked like the boxes."""
    folder = crafted(tmp_path)
    before = _state(folder)
    shots = tmp_path / "shots"
    args = ["--self-test", str(folder), "--screenshot-dir", str(shots), "--select", O16, "--3d", "--boxes"]
    args += [
        "--explode",
        "100,parts",
        "--pick",
        "o06_boxA_props_mat_cfg-1",
        "--pick",
        VIRTUAL,
        "--pick",
        INNER[1],
    ]
    report = run_self_test(args, shots, appdata=tmp_path / "Roaming")
    (doc,) = report["documents"]
    assert doc["mesh"]["instances"] == 2 and doc["mesh"]["boxes"] == {
        "with_box": 10,
        "drawn": 10,
        "visible": 10,
        "not_drawn": 0,
        "drawn_when_off": 0,
        "drawn_on_again": 10,
    }
    (exploded,) = doc["explode"]
    assert exploded["boxes"] == {"with_box": 10, "drawn": 10, "visible": 10, "not_drawn": 0}
    assert doc["errors"] == []
    for picked in doc["picked"]:
        assert picked["components_tab"] == picked["name"] and picked["picked"] == [picked["name"]]
    assert [p["outcome"] for p in doc["picked"]] == ["dialog", "apart", "dialog"]  # o07's file is nowhere
    assert doc["picked"][1]["back"] and doc["picked"][1]["picked_after_back"] == [VIRTUAL]
    names = [Path(p).name for p in report["screenshots"]]
    assert any(n.endswith("o16_asm_features_preview_3d_boxes.png") for n in names)
    assert any(n.endswith("o16_asm_features_preview_3d_boxes_off.png") for n in names)
    assert _state(folder) == before


@needs_qt
def test_the_self_test_boxes_option_is_checked(app, tmp_path, monkeypatch):
    from solidseas_app.viewer import app as viewer_app
    from solidseas_app.viewer.selftest import box_failures

    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    base = ["--self-test", str(FIXTURES), "--screenshot-dir", str(tmp_path / "s"), "--select", O16]
    assert viewer_app.build_parser().parse_args([*base, "--3d", "--boxes"]).boxes is True
    assert viewer_app.main([*base, "--boxes"]) == viewer_app.EXIT_USAGE  # needs --3d
    assert viewer_app.main(["--boxes"]) == viewer_app.EXIT_USAGE  # belongs to the self-test
    report = ["--self-test", str(FIXTURES), "--report", str(tmp_path / "r.json"), "--select-all", "--3d"]
    assert viewer_app.main([*report, "--boxes"]) == viewer_app.EXIT_USAGE
    assert not (tmp_path / "s").exists()
    # What fails the run: a box the view lacks, one missing where it should be or off the view.
    clean = {"boxes": 2, "visible": 2, "outside": [], "subpixel": [], "missing": [], "first": 5}
    assert box_failures(["a-1", "b-1"], ["a-1", "b-1"], clean) == []
    assert box_failures(["a-1", "b-1"], ["a-1"], {**clean, "boxes": 1}) == ["b-1"]
    assert box_failures(["a-1", "b-1"], ["a-1", "b-1"], {**clean, "missing": [6]}) == ["b-1"]
    assert box_failures(["a-1", "b-1"], ["a-1", "b-1"], {**clean, "outside": [5]}) == ["a-1"]
    assert box_failures(["a-1"], [], None) == ["a-1"] and box_failures([], [], None) == []
    # A box too small to cover a pixel draws nothing there, and that is no failure.
    assert box_failures(["a-1", "b-1"], ["a-1", "b-1"], {**clean, "visible": 1, "subpixel": [6]}) == []
    # Linear in the boxes: a hundred thousand check in well under a second.
    many = [f"p-{k}" for k in range(100_000)]
    start = time.perf_counter()
    lost = {**clean, "boxes": len(many), "missing": [5 + k for k in range(0, 100_000, 2)]}
    assert box_failures(many, many, lost) == many[::2]
    assert time.perf_counter() - start < 5.0
