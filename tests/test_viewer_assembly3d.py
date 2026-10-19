"""The 3D view of an assembly, in the SolidSeas Viewer.

An assembly is read in the mesh process through ``solidseas.geometry``: each
component file's mesh once, and every instance with its placement. These tests
check what the read gives (counts, colours, the legend, the instances not
shown and why, the triangle limit over the whole assembly), that the mesh
process carries it whole, and what the Preview tab does with it: the legend,
the configuration list it shares with the Components tab, and the status line.
Qt's offscreen platform has no OpenGL on Windows, so the window tests use a
stand-in for the OpenGL view; one test draws on the real display, both with
instanced drawing and instance by instance, and skips where there is none.

Every test that reads files checks that none of them changed.
"""

import os
import shutil
from array import array
from pathlib import Path

import pytest

from builders import TreeXml, resolving_assembly
from gl_support import run_gl, run_self_test
from solidseas_app.viewer import mesh3d, wording
from support import ASSEMBLY, FIXTURES, fixture_path
from test_viewer import Viewer, _state, _stub_view_factory, _wait, needs_qt

O16 = "o16_asm_features.SLDASM"


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


def _read(name: str, cap: int = 1_000_000, **kw) -> dict:
    path = str(fixture_path(name))
    return mesh3d.read_assembly_scene(path, str(FIXTURES), str(FIXTURES), cap, **kw)


# --------------------------------------------------------------------------- the read, no Qt
def test_an_assembly_is_read_as_meshes_and_instances():
    before = _state(FIXTURES)
    result = _read(O16)
    assert result["state"] == "ok" and set(result["seconds"]) == {"open", "read", "build"}
    scene = result["data"]
    assert (scene.n_instances, len(scene.meshes), scene.n_triangles) == (12, 6, 144)
    for matrices, files_of, ids in zip(scene.matrices, scene.files_of, scene.instance_ids, strict=True):
        assert len(matrices) == 64 * len(ids) and len(files_of) == 4 * len(ids)
    names = [f["name"] for f in scene.files]
    assert names == [
        "o02_boxA.SLDPRT",
        "o06_boxA_props_mat_cfg.SLDPRT",
        "o07_boxB_h31.SLDPRT",
        "o09_import_step.SLDPRT",
        "o17_деталь.SLDPRT",
        "Part12^o16_asm_features.SLDPRT",
    ]
    assert [f["instances"] for f in scene.files] == [4, 1, 4, 1, 1, 1]
    assert len({f["color"] for f in scene.files}) == 6
    # The instance turned +90 degrees about Z sits where SOLIDWORKS put it.
    o02 = next(i for i, ids in enumerate(scene.instance_ids) if "o02_boxA-2" in ids)
    m = array("f")
    m.frombytes(scene.matrices[o02])
    k = scene.instance_ids[o02].index("o02_boxA-2")
    assert list(m[16 * k : 16 * k + 16]) == pytest.approx([0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1, 0, 0.1, 0, 0, 1])
    geo = result["geometry"]
    assert geo["configuration"] == "Default" and geo["sources"] == ["assembly"]
    assert geo["skipped_count"] == 0 and geo["counts"]["suppressed"] == 1
    lite = _read(O16, configuration="Lite")
    assert lite["data"].n_instances == 10 and lite["geometry"]["configuration"] == "Lite"
    assert _read("o02_boxA.SLDPRT")["state"] == "not_assembly"
    assert _state(FIXTURES) == before


def test_the_triangle_limit_holds_for_the_whole_assembly():
    """Each mesh of o16 has 12 triangles: under a limit of 24 the meshes of the first two
    files met are read, and the instances of the others are left out and say so."""
    result = _read(O16, cap=24)
    assert result["state"] == "ok" and result["geometry"]["counts"]["triangles_read"] == 24
    geo = result["geometry"]
    assert "max_triangles" in geo["truncated"] and geo["skipped_reasons"] == {"max_triangles": 7}
    assert result["data"].n_instances == 5  # o02's and o06's instances: the rest waits for a higher limit
    text, full = wording.not_shown_text(geo, 24)
    assert text.startswith("Not shown: 7 instances: ")
    assert "(triangle limit)" in text and "Raise it under Settings > 3D View" in text
    assert full.startswith("triangle limit: o15_sub_asm-1/o07_boxB_h31-1, o07_boxB_h31-2")  # paths name them
    assert "limit of 24 triangles" in wording.not_shown_text(geo)[0]  # the limit the read had
    assert "Settings > Boxes for Missing Meshes draws 7 of them as boxes." in text
    # Each of them has a box stored in o16: drawn as boxes, they are counted, not named.
    boxed, boxed_full = wording.not_shown_text(geo, 24, boxes=True)
    assert boxed.startswith("Drawn as boxes, with no mesh drawn: 7 instances (triangle limit: 7). The 3D ")
    assert "Not shown" not in boxed
    assert boxed_full.startswith("drawn as a box, triangle limit: o15_sub_asm-1/")
    assert result["data"].boxes.ids == [s["id"] for s in geo["skipped"]]
    # Under 11 no mesh fits: nothing is drawn from a mesh, and every instance has its box.
    nothing = _read(O16, cap=11)
    assert nothing["state"] == "ok" and nothing["data"].meshes == [] and len(nothing["data"].boxes) == 12
    assert nothing["geometry"]["too_large"] and nothing["geometry"]["placed"] == 0


def test_the_triangles_drawn_are_bounded_by_the_limit_too(tmp_path, monkeypatch):
    """Fifty instances of a twelve-triangle part read twelve triangles and draw 600. Under a
    limit of 24 the view draws at most twenty times that, 480: forty instances, and the
    status line says why the other ten are not shown. The scene's box comes from the
    instance boxes, without passing over a mesh for each instance."""
    from solidseas import geometry

    assert mesh3d.drawn_budget(24) == 480 and mesh3d.drawn_budget(1_000_000) == 20_000_000
    assert mesh3d.drawn_budget(mesh3d.MAX_TRIANGLE_CAP) == mesh3d.MAX_DRAWN
    folder = tmp_path / "jobs"
    folder.mkdir()
    shutil.copy2(fixture_path("o02_boxA.SLDPRT"), folder / "p.SLDPRT")
    t = TreeXml()
    t.top("m1")
    t.file("2", "p.SLDPRT")
    t.model("m2", "2")
    for n in range(1, 51):
        t.ref("m1", "p", n, "m2", transform=f"1 0 0 0 0 1 0 0 0 0 1 0 {0.02 * n} 0 0 1")
    (folder / "asm.SLDASM").write_bytes(resolving_assembly(t))

    def no_whole_box(self, **_kw):
        raise AssertionError("the scene's box is the union of the instance boxes")

    monkeypatch.setattr(geometry.DisplayGeometry, "bbox", no_whole_box)
    before = _state(folder)
    result = mesh3d.read_assembly_scene(str(folder / "asm.SLDASM"), str(folder), str(folder), 24)
    assert result["state"] == "ok" and result["data"].n_instances == 40
    assert result["data"].n_triangles == 480
    box = result["data"].bbox
    assert [*box[0], *box[1]] == pytest.approx([0.02, 0, 0, 0.81, 0.02, 0.03], abs=1e-6)
    geo = result["geometry"]
    assert geo["truncated"] == ["max_drawn"] and geo["skipped_reasons"] == {"max_drawn": 10}
    assert geo["drawn_cap"] == 480 and geo["counts"]["triangles_read"] == 12
    text, _full = wording.not_shown_text(geo)
    assert "(limit on triangles drawn)" in text and "draws at most 480 triangles" in text
    assert "was reached before every mesh was read" not in text
    whole = mesh3d.read_assembly_scene(str(folder / "asm.SLDASM"), str(folder), str(folder), 1_000_000)
    assert whole["data"].n_instances == 50 and whole["geometry"]["truncated"] == []
    assert _state(folder) == before


def test_instances_not_shown_are_named_with_the_reason(tmp_path, monkeypatch):
    from solidseas.resolve import gateway as gateway_mod

    real = gateway_mod._drive_type
    monkeypatch.setattr(gateway_mod, "_drive_type", lambda r: 1 if r.upper().startswith("Q:") else real(r))
    folder = tmp_path / "jobs"
    folder.mkdir()
    shutil.copy2(fixture_path("o02_boxA.SLDPRT"), folder / "p.SLDPRT")
    t = TreeXml()
    t.top("m1")
    t.file("2", "Q:\\Old\\p.SLDPRT")
    t.file("3", "Q:\\Old\\gone.SLDPRT")
    t.model("m2", "2")
    t.model("m3", "3")
    for n in range(1, 6):
        t.ref("m1", "gone", n, "m3")
    t.ref("m1", "p", 1, "m2")
    (folder / "asm.SLDASM").write_bytes(resolving_assembly(t, folder_at_save="Q:\\Old\\"))
    before = _state(folder)
    result = mesh3d.read_assembly_scene(str(folder / "asm.SLDASM"), str(folder), str(folder), 1_000_000)
    assert result["state"] == "ok" and result["data"].n_instances == 1
    geo = result["geometry"]
    assert geo["skipped_count"] == 5 and geo["skipped"][0]["file"] == "gone.SLDPRT"
    text, full = wording.not_shown_text(geo)
    assert text == "Not shown: 5 instances: gone-1, gone-2, gone-3 and 2 more (file not found)."
    assert full == "file not found: gone-1, gone-2, gone-3, gone-4, gone-5"
    assert _state(folder) == before


def _with_missing_parts(tmp_path) -> Path:
    """An assembly of o02 (in the folder) and two instances of a part that is nowhere,
    whose model stores its box: one moved, one turned +90 degrees about Z."""
    folder = tmp_path / "jobs"
    folder.mkdir()
    shutil.copy2(fixture_path("o02_boxA.SLDPRT"), folder / "p.SLDPRT")
    t = TreeXml()
    t.top("m1")
    t.file("2", "p.SLDPRT")
    t.file("3", "gone.SLDPRT")
    t.model("m2", "2")
    t.model("m3", "3", bbox="0 0 0 0.01 0.02 0.03")
    t.ref("m1", "p", 1, "m2")
    t.ref("m1", "gone", 1, "m3", transform="1 0 0 0 0 1 0 0 0 0 1 0 0.1 0 0 1")
    t.ref("m1", "gone", 2, "m3", transform="0 1 0 0 -1 0 0 0 0 0 1 0 0.2 0 0 1")
    (folder / "asm.SLDASM").write_bytes(resolving_assembly(t))
    return folder


PLACEHOLDERS = {"gone-1": [0.1, 0, 0, 0.11, 0.02, 0.03], "gone-2": [0.18, 0, 0, 0.2, 0.01, 0.03]}


def _check_placeholders(ph: dict) -> None:
    """Each placeholder's matrix applied to its box's corners gives the expected box."""
    assert ph["count"] == len(ph["ids"]) == 2 and ph["ids"] == list(PLACEHOLDERS)
    assert ph["reasons"] == ["missing", "missing"] and ph["files"] == ["3", "3"]
    matrices, boxes = array("f"), array("f")
    matrices.frombytes(ph["matrices"])
    boxes.frombytes(ph["boxes"])
    assert len(matrices) == 32 and len(boxes) == 12
    for k, iid in enumerate(ph["ids"]):
        m, b = matrices[16 * k : 16 * k + 16], boxes[6 * k : 6 * k + 6]
        assert list(b) == pytest.approx([0, 0, 0, 0.01, 0.02, 0.03], abs=1e-7)
        corners = [
            [
                m[0] * x + m[4] * y + m[8] * z + m[12],
                m[1] * x + m[5] * y + m[9] * z + m[13],
                m[2] * x + m[6] * y + m[10] * z + m[14],
            ]
            for x in (b[0], b[3])
            for y in (b[1], b[4])
            for z in (b[2], b[5])
        ]
        placed = [min(c[i] for c in corners) for i in range(3)] + [
            max(c[i] for c in corners) for i in range(3)
        ]
        assert placed == pytest.approx(PLACEHOLDERS[iid], abs=1e-6), iid


def test_the_instances_not_shown_come_with_a_box_to_draw(tmp_path):
    """Each instance the 3D view cannot draw comes with where it sits and the box its
    assembly stores for it, packed for the GPU like the instances drawn."""
    folder = _with_missing_parts(tmp_path)
    before = _state(folder)
    result = mesh3d.read_assembly_scene(str(folder / "asm.SLDASM"), str(folder), str(folder), 1_000_000)
    assert result["state"] == "ok" and result["data"].n_instances == 1
    _check_placeholders(result["geometry"]["placeholders"])
    assert result["data"].info["placeholders"] is result["geometry"]["placeholders"]
    assert _state(folder) == before


def test_component_colours_stay_apart():
    colours = [mesh3d.component_color(i) for i in range(60)]
    assert len({mesh3d.color_name(c) for c in colours}) == 60
    assert all(0 <= v <= 1 for c in colours for v in c)
    assert mesh3d.color_name(mesh3d.component_color(0)) == "#4e79a7"


def test_the_words_for_what_is_not_shown():
    assert wording.not_shown_text({}) == ("", "")
    info = {
        "skipped_count": 3,
        "skipped": [
            {"name": "a-1", "reason": "no_mesh"},
            {"name": "b-1", "reason": "an_unknown_reason"},
        ],
        "truncated": ["max_instances"],
        "mesh_warnings": [{"file": "x.SLDPRT", "code": "mesh_configuration_differs", "message": "m"}],
    }
    text, _full = wording.not_shown_text(info)
    assert text.startswith(
        "Not shown: 3 instances: a-1 (no saved display mesh); b-1 (an unknown reason); 1 more."
    )
    assert "reaches the 3D view's limit on instances expanded" in text
    assert "x.SLDPRT shows the configuration its own file was saved in" in text
    assert wording.sources_text(["assembly", "file"]) == (
        "the meshes the assembly stores and the component files' own meshes"
    )


# --------------------------------------------------------------------------- the mesh process
@needs_qt
def test_the_mesh_process_reads_an_assembly_whole(tmp_path):
    from solidseas_app.viewer import meshproc

    before = _state(FIXTURES)
    reader = meshproc.MeshReader()
    try:
        path, folder = str(fixture_path(O16)), str(FIXTURES)
        result = reader.read(path, folder, 1_000_000, assembly=True, configuration="Lite", cache_key="a")
        assert result["state"] == "ok" and "transfer" in result["seconds"]
        here = _read(O16, configuration="Lite")["data"]
        scene = result["data"]
        assert scene.n_instances == here.n_instances == 10 and scene.files == here.files
        assert scene.matrices == here.matrices and scene.files_of == here.files_of
        assert [m.positions for m in scene.meshes] == [m.positions for m in here.meshes]
        assert scene.info["configuration"] == "Lite"
        part = reader.read(str(fixture_path("o02_boxA.SLDPRT")), folder, 1000)  # the same process, a part
        assert part["state"] == "ok" and part["data"].n_triangles == 12 and reader.started == 1
        wrong = reader.read(str(fixture_path("o02_boxA.SLDPRT")), folder, 1000, assembly=True)
        assert wrong["state"] == "not_assembly" and wrong["doc_type"] == "part"
        # The instances it cannot draw reach the window's process with their boxes: named in
        # the answer's JSON, their matrices and boxes in buffers of their own (JSON holds no
        # bytes, and the packed placeholders stay in the child).
        jobs = _with_missing_parts(tmp_path)
        missing = reader.read(str(jobs / "asm.SLDASM"), str(jobs), 1_000_000, assembly=True, cache_key="b")
        assert missing["state"] == "ok" and missing["data"].n_instances == 1
        for ph in (missing["geometry"]["placeholders"], missing["data"].info["placeholders"]):
            assert ph["count"] == len(ph["ids"]) == 2 and ph["ids"] == list(PLACEHOLDERS)
            assert ph["reasons"] == ["missing", "missing"] and ph["files"] == ["3", "3"]
            assert "matrices" not in ph and "boxes" not in ph
        boxes = missing["data"].boxes
        assert boxes.ids == list(PLACEHOLDERS) and boxes.reasons == ["missing", "missing"]
        bounds = array("f")
        bounds.frombytes(boxes.bounds)
        for k, iid in enumerate(boxes.ids):
            assert list(bounds[6 * k : 6 * k + 6]) == pytest.approx(PLACEHOLDERS[iid], abs=1e-6), iid
    finally:
        reader.close()
    assert _state(FIXTURES) == before


# --------------------------------------------------------------------------- the Preview tab
def _show(viewer, name: str) -> None:
    from solidseas_app.viewer.details import TABS

    w = viewer.window
    w.details.tabs.setCurrentIndex(TABS.index("Preview"))
    viewer.select(name)
    _wait(viewer.app, lambda: w.details.preview.mesh_state not in ("starting", "loading") and not w.busy)


def _ready(viewer):
    pane = viewer.window.details.preview
    _wait(
        viewer.app, lambda: pane.mesh_state not in ("starting", "loading", "idle") and not viewer.window.busy
    )


@needs_qt
def test_an_assembly_in_3d_shares_its_configuration_with_the_components_tab(viewer):
    w = viewer.window
    pane = w.details.preview
    made: list = []
    pane.view_factory = _stub_view_factory(made)
    pane.gl_check = lambda: (True, "test")
    before = _state(FIXTURES)
    viewer.open(FIXTURES)
    w.change_settings(view_3d=True)
    _show(viewer, O16)
    assert pane.mesh_state == "ready" and made[-1].assembly.n_instances == 12
    legend = [pane.legend.item(i).text() for i in range(pane.legend.count())]
    assert legend[0] == "o02_boxA.SLDPRT (4)" and len(legend) == 6 and not pane.legend.isHidden()
    combo = [pane.config_combo.itemText(i) for i in range(pane.config_combo.count())]
    assert combo == ["Default", "Lite"] and pane.config_combo.currentText() == "Default"
    assert pane.mesh_info["configuration"] == "Default" and pane.status.isHidden()

    # Lite, chosen in the 3D view's list: the view is read again, and the Components tab follows.
    reads = []
    w.meshFinished.connect(reads.append)
    pane.config_combo.setCurrentText("Lite")
    pane.choose_configuration("Lite")
    _wait(viewer.app, lambda: w.details.configuration_shown() == "Lite" and pane.mesh_state == "ready")
    _ready(viewer)
    assert made[-1].assembly.n_instances == 10 and pane.mesh_info["configuration"] == "Lite"
    assert w.details.config_combo.currentText() == "Lite" and len(reads) == 1

    # Default, chosen on the Components tab: the 3D view follows.
    w.details.config_combo.setCurrentText("Default")
    w.details.config_combo.activated.emit(w.details.config_combo.currentIndex())
    _wait(viewer.app, lambda: pane.config_combo.currentText() == "Default")
    _ready(viewer)
    assert made[-1].assembly.n_instances == 12 and pane.mesh_info["configuration"] == "Default"
    assert len(reads) == 2

    # The legend comes and goes with its button, and only for an assembly.
    pane.legend_button.click()
    assert pane.legend.isHidden()
    pane.legend_button.click()
    assert not pane.legend.isHidden()
    _show(viewer, "o02_boxA.SLDPRT")
    assert pane.legend.isHidden() and pane.legend_button.isHidden() and pane.config_combo.isHidden()
    assert made[-1].mesh.n_triangles == 12
    assert _state(FIXTURES) == before


@needs_qt
def test_the_legend_keeps_to_a_corner_and_picks_a_file(viewer, tmp_path):
    """The legend takes at most a third of the view's height and 40 percent of its width,
    scrolling past that, so it cannot hide the model behind a list of files; an assembly
    of more than twelve files starts with it hidden, until the user chooses. A click on a
    file in it picks every instance of that file, as its row of the Files table does."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from solidseas_app.viewer.preview import LEGEND_HEIGHT, LEGEND_SHOWN_UP_TO, LEGEND_WIDTH

    folder = tmp_path / "many"
    folder.mkdir()
    t = TreeXml()
    t.top("m1")
    for n in range(30):
        shutil.copy2(fixture_path("o02_boxA.SLDPRT"), folder / f"p{n}.SLDPRT")
        t.file(str(n + 2), f"p{n}.SLDPRT")
        t.model(f"m{n + 2}", str(n + 2))
        t.ref("m1", f"p{n}", 1, f"m{n + 2}", transform=f"1 0 0 0 0 1 0 0 0 0 1 0 {0.02 * n} 0 0 1")
    (folder / "many.SLDASM").write_bytes(resolving_assembly(t))
    shutil.copy2(fixture_path(O16), folder / O16)
    for name in ("o02_boxA.SLDPRT", "o06_boxA_props_mat_cfg.SLDPRT", "o07_boxB_h31.SLDPRT"):
        shutil.copy2(fixture_path(name), folder / name)
    w = viewer.window
    pane = w.details.preview
    made: list = []
    pane.view_factory = _stub_view_factory(made)
    pane.gl_check = lambda: (True, "test")
    viewer.open(folder)
    w.change_settings(view_3d=True)
    _show(viewer, "many.SLDASM")
    view, legend = made[-1], pane.legend
    assert len(pane.files) == 30 > LEGEND_SHOWN_UP_TO
    assert legend.count() == 30 and legend.isHidden() and not pane.legend_button.isChecked()
    pane.legend_button.click()  # the user shows it: it scrolls within its corner
    assert not legend.isHidden() and pane.legend_chosen
    assert legend.height() <= view.height() * LEGEND_HEIGHT + 1
    assert legend.width() <= view.width() * LEGEND_WIDTH + 1
    assert legend.verticalScrollBar().maximum() > 0
    assert legend.geometry().right() < view.width() and legend.geometry().top() >= 0
    view.resize(view.width(), 900)  # a taller view: the legend follows, a third of it
    viewer.app.processEvents()
    assert legend.height() <= 900 * LEGEND_HEIGHT + 1

    # A click on a file picks its instance, here and on the Files table.
    item = legend.item(4)
    legend.scrollToItem(item)
    at = legend.visualItemRect(item).center()
    QTest.mouseClick(legend.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
    key = pane.files[4]["key"]
    assert pane.highlight == ("file", key) and [pane.instance_ids[g] for g in view.selected] == ["p4-1"]
    assert w.details.files.currentItem() is not None and w.details.files.currentItem().text(0) == "p4.SLDPRT"
    assert pane.pick_note.text().startswith("Picked: every instance of p4.SLDPRT")

    # The user's choice holds for the next assembly, however few its files.
    _show(viewer, O16)
    assert len(pane.files) == 6 and pane.legend_button.isChecked() and not pane.legend.isHidden()
    pane.legend_button.click()
    _show(viewer, "many.SLDASM")
    assert pane.legend.isHidden() and not pane.legend_button.isChecked()


@needs_qt
def test_a_higher_limit_reads_an_assembly_the_old_one_cut_short(viewer):
    w = viewer.window
    pane = w.details.preview
    made: list = []
    pane.view_factory = _stub_view_factory(made)
    pane.gl_check = lambda: (True, "test")
    viewer.open(FIXTURES)
    w.change_settings(view_3d=True)
    w.settings = w.settings.but(triangle_cap=24)  # below any real setting, to see it
    _show(viewer, O16)
    assert pane.mesh_state == "ready" and pane.mesh_info["limited"] and made[-1].assembly.n_instances == 5
    assert not pane.status.isHidden() and "triangle limit" in pane.status.text()
    assert "o07_boxB_h31-2" in pane.status.toolTip()
    w.change_settings(triangle_cap=1_000_000)
    _wait(viewer.app, lambda: pane.mesh_state == "ready" and not pane.mesh_info.get("limited"))
    assert made[-1].assembly.n_instances == 12 and pane.status.isHidden()


@needs_qt
def test_an_assembly_with_nothing_to_draw_says_why(viewer, tmp_path, monkeypatch):
    from solidseas.resolve import gateway as gateway_mod

    real = gateway_mod._drive_type
    monkeypatch.setattr(gateway_mod, "_drive_type", lambda r: 1 if r.upper().startswith("Q:") else real(r))
    folder = tmp_path / "jobs"
    folder.mkdir()
    t = TreeXml()
    t.top("m1")
    t.file("3", "Q:\\Old\\gone.SLDPRT")
    t.model("m3", "3")
    t.ref("m1", "gone", 1, "m3")
    (folder / "asm.SLDASM").write_bytes(resolving_assembly(t, folder_at_save="Q:\\Old\\"))
    w = viewer.window
    pane = w.details.preview
    made: list = []
    pane.view_factory = _stub_view_factory(made)
    pane.gl_check = lambda: (True, "test")
    viewer.open(folder)
    w.change_settings(view_3d=True)
    _show(viewer, "asm.SLDASM")
    assert pane.mesh_state == "no_mesh" and pane.model_message.text().startswith("Nothing to draw")
    assert pane.status.text() == "Not shown: 1 instance: gone-1 (file not found)."


# --------------------------------------------------------------------------- OpenGL, on the real display
_GL_ASSEMBLY = """
from solidseas_app.viewer import mesh3d
scene = mesh3d.read_assembly_scene(sys.argv[1], sys.argv[2], sys.argv[2], 1_000_000)["data"]
out = {"gl": True}
images = []
for instanced in (True, False):
    view3d.Renderer.allow_instancing = instanced
    view = view3d.ModelView()
    view.resize(400, 300)
    view.set_assembly(scene)
    img = view.grabFramebuffer()
    bg = img.pixelColor(1, 1)
    colours = {img.pixelColor(x, y).name() for y in range(0, 300, 2) for x in range(0, 400, 2)}
    covered = sum(img.pixelColor(x, y) != bg for y in range(0, 300, 4) for x in range(0, 400, 4))
    out[str(instanced)] = {
        "error": view.error, "instanced": view.renderer.instanced, "covered": covered,
        "colours": len(colours), "triangles": view.renderer.count // 3,
    }
    images.append(img)
out["same"] = images[0] == images[1]
print(json.dumps(out))
"""


@needs_qt
def test_the_3d_view_draws_an_assembly_with_opengl():
    """Each mesh is uploaded once and drawn for every instance: in one call with instanced
    drawing, and one instance at a time without it, to the same picture."""
    out = run_gl(_GL_ASSEMBLY, str(fixture_path(O16)), str(FIXTURES))
    one_by_one = out["False"]
    assert one_by_one["error"] is None and one_by_one["instanced"] is False
    assert one_by_one["triangles"] == 144 and one_by_one["covered"] > 100
    assert one_by_one["colours"] > 20  # six component colours, each lit in several shades
    if out["True"]["instanced"]:  # OpenGL 3.3 or later
        assert out["True"]["error"] is None and out["same"]


_GL_PLACED = """
import os
from array import array
from solidseas_app.viewer import explode, mesh3d
path, folder, configuration = sys.argv[1], sys.argv[2], sys.argv[3]
with open(os.path.join(folder, "ground_truth.json"), encoding="utf-8") as fh:
    gt = json.load(fh)[os.path.basename(path)]["api"]["configurations"][configuration]["components"]
boxes = {c["name"]: c["box_m"] for c in gt}
scene = mesh3d.read_assembly_scene(path, folder, folder, 1_000_000, configuration=configuration)["data"]
# Each instance's box as SOLIDWORKS gave it, in the scene's order, and the groups' offsets made
# from those boxes: nothing from the meshes, the placements or the view goes into them.
gt_bounds = [array("f", [v for i in ids for v in boxes[i]]).tobytes() for ids in scene.instance_ids]
out = {"gl": True}
for instanced in (True, False):
    view3d.Renderer.allow_instancing = instanced
    view = view3d.ModelView()
    view.resize(480, 360)
    view.show()
    view.set_assembly(scene)
    app.processEvents()
    for level in explode.LEVELS:
        view.set_explode_level(level)
        e = explode.explode(scene.instance_ids, gt_bounds, level)
        for t in (0.0, 1.0):
            view.explode_to(t, animate=False)
            app.processEvents()
            w, h = view.width(), view.height()
            drawn = {}
            for k, i in enumerate(view._id_pass((0.0, 0.0, 1.0, 1.0), (w, h)) or []):
                if i is not None:
                    x, y = k % w + 0.5, k // w + 0.5  # the pixel's centre
                    r = drawn.setdefault(i, [x, y, x, y])
                    r[:] = [min(r[0], x), min(r[1], y), max(r[2], x), max(r[3], y)]
            rows, g = [], 0
            for m, ids in enumerate(scene.instance_ids):
                for k, iid in enumerate(ids):
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
    out[f"{instanced} error"] = view.error
print(json.dumps(out))
"""


@needs_qt
@pytest.mark.parametrize("configuration", ["Default", "Lite"])
def test_every_instance_is_drawn_inside_the_box_solidworks_gave_it(configuration):
    """An independent check of what the GPU draws: each instance's box as SOLIDWORKS
    reported it (ground_truth.json), moved by the explode offset made from those boxes,
    is projected with the view's camera; every pixel the id pass gives that instance
    must lie inside that rectangle (to a pixel), and a click at its middle must pick it.
    Collapsed and fully exploded, at both levels, instanced and one instance at a time,
    on o16 in Default and Lite: a shader that turned an instance the wrong way, or moved
    it by the wrong amount, fails here."""
    out = run_gl(_GL_PLACED, str(fixture_path(O16)), str(FIXTURES), configuration)
    n = 12 if configuration == "Default" else 10
    tol = 1.0  # pixels: the boxes are float64, the meshes and the GPU float32
    for instanced in ("True", "False"):
        assert out[f"{instanced} error"] is None
        for level in ("top", "parts"):
            for t in ("0.0", "1.0"):
                rows = out[f"{instanced} {level} {t}"]
                assert len(rows) == n
                for g, r in enumerate(rows):
                    where = (instanced, level, t, r["id"])
                    assert r["drawn"] is not None, where  # every instance is in view
                    (x0, y0, x1, y1), (a0, b0, a1, b1) = r["drawn"], r["want"]
                    assert a0 - tol <= x0 and x1 <= a1 + tol and b0 - tol <= y0 and y1 <= b1 + tol, (where, r)
                    # and it fills its rectangle: drawn somewhere near each side of it
                    assert x0 <= a0 + 0.5 * (a1 - a0) <= x1 and y0 <= b0 + 0.5 * (b1 - b0) <= y1, (where, r)
                    assert r["at_centre"] == g, where


@needs_qt
def test_the_self_test_draws_an_assembly_in_another_configuration(tmp_path):
    """On the real display: the self-test draws o16 in 3D, then chooses Lite in the 3D
    view's list and draws it again, with the Components tab showing Lite too."""
    shots = tmp_path / "shots"
    args = ["--self-test", str(FIXTURES), "--screenshot-dir", str(shots), "--select", O16]
    report = run_self_test([*args, "--configuration", "Lite", "--3d"], shots, appdata=tmp_path / "Roaming")
    (doc,) = report["documents"]
    assert doc["mesh"]["instances"] == 12 and doc["mesh"]["configuration"] == "Default"
    (lite,) = doc["mesh_configurations"]
    assert (lite["chosen"], lite["components_tab"], lite["configuration"]) == ("Lite", "Lite", "Lite")
    assert lite["instances"] == 10 and lite["frame_s"] > 0
    names = [Path(p).name for p in report["screenshots"]]
    assert any(n.endswith("o16_asm_features_preview_3d.png") for n in names)
    assert any(n.endswith("o16_asm_features_preview_3d_Lite.png") for n in names)
    assert not (tmp_path / "Roaming").exists()


def test_the_assembly_fixture_is_still_an_assembly():
    assert ASSEMBLY.endswith(".SLDASM")
