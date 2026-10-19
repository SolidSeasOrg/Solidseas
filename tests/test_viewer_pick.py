"""Picking a component in the SolidSeas Viewer's 3D view of an assembly.

The view finds the instance under the pointer with an id pass: each instance
drawn flat in a colour that is its number, into an offscreen framebuffer of
the few pixels round the pointer. These tests check the arithmetic (the
numbering, the shader's byte split in 32-bit floats, the narrowed projection,
the nearest hit), the selection shared with the Components tab both ways and
the double-click that opens a component's file, with a stand-in for the OpenGL
view, then the real view on the display: every instance of o16 picked where it
is drawn, collapsed and exploded, through real mouse events, the hover text,
and the self-test's ``--pick``.

Every test that reads files checks that none of them changed.
"""

import math
import os
import struct
from pathlib import Path

import pytest

from gl_support import run_gl, run_self_test
from solidseas_app.viewer import mesh3d, opening, viewmath
from support import FIXTURES, fixture_path
from test_viewer import Viewer, _state, _stub_view_factory, _wait, needs_qt

O16 = "o16_asm_features.SLDASM"
ROTATED = "o02_boxA-2"  # turned +90 degrees about Z
INNER = "o15_sub_asm-1/o07_boxB_h31-1"  # a part of the sub-assembly turned 40 degrees
VIRTUAL_INSTANCE = "Part12^o16_asm_features-1"  # stored inside o16, its mesh in o16's FaceTessellations
VIRTUAL_FILE = "Part12^o16_asm_features.SLDPRT"


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


def _f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", x))[0]


# --------------------------------------------------------------------------- the arithmetic, no Qt
def test_instances_are_numbered_in_three_bytes():
    for index in (0, 1, 254, 255, 256, 65534, 65535, 65536, 99_999, viewmath.MAX_PICK - 1):
        r, g, b = viewmath.pick_color(index)
        assert all(0 <= c <= 255 for c in (r, g, b))
        assert viewmath.pick_index(r, g, b) == index
    assert viewmath.pick_color(0) == (1, 0, 0) and viewmath.pick_color(255) == (0, 1, 0)
    assert viewmath.pick_index(0, 0, 0) is None  # the background
    for bad in (-1, viewmath.MAX_PICK):
        with pytest.raises(ValueError):
            viewmath.pick_color(bad)


def test_the_shader_splits_a_number_into_the_same_bytes():
    """The vertex shader splits ``index + 1`` with ``mod`` and ``floor`` in 32-bit floats
    and divides by 255; the framebuffer stores each channel as the nearest of 256
    steps. Done here the same way, every byte comes back."""
    for index in (*range(0, 600), 65_535, 65_536, 99_999, 4_000_000, viewmath.MAX_PICK - 1):
        n = _f32(index + 1)
        q = math.floor(_f32(n / 256.0))  # GLSL's mod(x, y) is x - y * floor(x / y)
        low = _f32(n - 256.0 * q)
        mid = _f32(q - 256.0 * math.floor(_f32(q / 256.0)))
        top = math.floor(_f32(n / 65536.0))
        stored = tuple(round(_f32(_f32(c) / 255.0) * 255.0) for c in (low, mid, top))
        assert stored == viewmath.pick_color(index), index


def test_the_pick_projection_fills_the_buffer_with_the_pixels_round_the_click():
    cam = viewmath.OrbitCamera(((-0.05, -0.12, -0.03), (0.17, 0.12, 0.03)))
    cam.aspect = 640 / 480
    cam.reset()
    width, height = 640, 480
    point = (0.02, 0.01, 0.0)
    nx, ny, _z = cam.project(point)
    x, y = (nx + 1) * width / 2, (1 - ny) * height / 2  # the pixel position it is drawn at
    cx, cy, hw, hh, side = viewmath.pick_window(x, y, width, height)
    assert side == 2 * viewmath.PICK_RADIUS + 1 == 7
    narrow = viewmath.pick_projection(cam.projection_matrix(), cx, cy, hw, hh)
    view = cam.view_matrix()

    def project(p):
        v = viewmath.mat_vec(view, (*p, 1.0))
        return viewmath.mat_vec(narrow, v)[:3]

    assert project(point)[:2] == pytest.approx((0.0, 0.0), abs=1e-9)  # the click is the middle
    assert project(point)[2] == pytest.approx(_z)  # depth is unchanged
    # A point drawn two pixels right and one up lands two and one pixels from the middle of
    # the 7-pixel buffer, where each NDC unit is 3.5 pixels.
    upp = cam.units_per_pixel(height)
    moved = tuple(point[i] + 2 * upp * cam.right[i] + upp * cam.up[i] for i in range(3))
    assert project(moved)[:2] == pytest.approx((2 / 3.5, 1 / 3.5), abs=1e-9)


def test_the_nearest_hit_to_the_middle_wins():
    side = 3
    assert viewmath.nearest_hit([None] * 9, side) is None
    assert viewmath.nearest_hit([5, 5, 5, 5, 7, 5, 5, 5, 5], side) == 7  # the middle pixel
    assert viewmath.nearest_hit([None, 4, None, 9, None, None, None, None, 2], side) == 4  # first of two
    assert viewmath.nearest_hit([None, None, None, None, None, None, None, None, 2], side) == 2  # a corner


def test_each_instance_carries_its_colour_state_and_number():
    pytest.importorskip("PySide6.QtGui")
    from array import array

    from solidseas_app.viewer.view3d import SHOWN, instance_buffers

    rgb = array("f", [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]).tobytes()
    col, off = instance_buffers(rgb, base=10)
    assert list(col) == pytest.approx([0.1, 0.2, 0.3, SHOWN, 0.4, 0.5, 0.6, SHOWN])
    assert list(off) == [0, 0, 0, 11, 0, 0, 0, 12]  # numbered from 1 over the scene


@needs_qt
def test_an_id_image_is_read_back_into_instances(app):
    from PySide6.QtGui import QColor, QImage

    from solidseas_app.viewer.view3d import image_ids

    img = QImage(5, 2, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 0))
    for (x, y), index in {(0, 0): 0, (4, 0): 70_000, (2, 1): 255}.items():
        img.setPixelColor(x, y, QColor(*viewmath.pick_color(index), 255))
    ids = image_ids(img)
    assert len(ids) == 10 and ids[0] == 0 and ids[4] == 70_000 and ids[7] == 255
    assert ids.count(None) == 7


# --------------------------------------------------------------------------- the window, a stand-in view
def _show(viewer, name: str) -> None:
    from solidseas_app.viewer.details import TABS

    w = viewer.window
    w.details.tabs.setCurrentIndex(TABS.index("Preview"))
    viewer.select(name)
    _wait(viewer.app, lambda: w.details.preview.mesh_state not in ("starting", "loading") and not w.busy)


def _assembly_3d(viewer):
    w = viewer.window
    pane = w.details.preview
    made: list = []
    pane.view_factory = _stub_view_factory(made)
    pane.gl_check = lambda: (True, "test")
    viewer.open(FIXTURES)
    w.change_settings(view_3d=True)
    _show(viewer, O16)
    return w, pane, made[-1]


def _current(w) -> str | None:
    from solidseas_app.viewer.details import IDENT_ROLE

    item = w.details.instances.currentItem()
    return item.data(0, IDENT_ROLE) if item is not None else None


def _picked(pane, view) -> list[str]:
    return sorted(pane.instance_ids[g] for g in view.selected)


@needs_qt
def test_a_click_in_the_view_and_a_row_of_the_components_tab_pick_the_same(viewer):
    from solidseas_app.viewer.details import IDENT_ROLE, _walk

    before = _state(FIXTURES)
    w, pane, view = _assembly_3d(viewer)
    ids = pane.instance_ids
    assert len(ids) == 12 and view.describe(ids.index(ROTATED)) == f"{ROTATED} (o02_boxA.SLDPRT)"
    said: list[str] = []
    pane.instancePicked.connect(said.append)

    # A click on an instance: it alone is picked, its row becomes current, the note names it.
    view.picked.emit(ids.index(ROTATED))
    assert said == [ROTATED] and _current(w) == ROTATED and _picked(pane, view) == [ROTATED]
    assert pane.pick_note.text() == f"Picked: {ROTATED} (o02_boxA.SLDPRT). Double-click it to open its file."
    assert not pane.pick_note.isHidden()
    view.picked.emit(ids.index(INNER))  # inside the turned sub-assembly: its row is expanded to
    item = w.details.instances.currentItem()
    assert _current(w) == INNER and item.parent() is not None and item.parent().isExpanded()
    # A click on nothing picks nothing, here and there.
    view.picked.emit(-1)
    assert said[-1] == "" and _current(w) is None and view.selected == set() and pane.pick_note.isHidden()

    # A row picked on the Components tab: a sub-assembly picks its parts, a file its instances,
    # a suppressed instance nothing drawn.
    rows = {item.data(0, IDENT_ROLE): item for item in _walk(w.details.instances)}
    w.details.instances.setCurrentItem(rows["o15_sub_asm-1"])
    assert _picked(pane, view) == ["o15_sub_asm-1/o02_boxA-1", INNER]
    assert pane.pick_note.text() == "Picked: o15_sub_asm-1, 2 parts shown."
    w.details.instances.setCurrentItem(rows["o07_boxB_h31-1"])  # suppressed in Default
    assert view.selected == set() and "which is not drawn here" in pane.pick_note.text()
    files = {w.details.files.topLevelItem(i).text(0): w.details.files.topLevelItem(i) for i in range(7)}
    w.details.files.setCurrentItem(files["o07_boxB_h31.SLDPRT"])
    assert _picked(pane, view) == sorted([INNER, "o07_boxB_h31-2", "o07_boxB_h31-3", "o07_boxB_h31-4"])
    assert pane.pick_note.text() == "Picked: every instance of o07_boxB_h31.SLDPRT (4 instances shown)."

    # The pick holds while the configuration changes, on both tabs, where Lite still has it.
    view.picked.emit(ids.index("o02_boxA-1"))
    pane.config_combo.setCurrentText("Lite")
    pane.choose_configuration("Lite")
    _wait(viewer.app, lambda: pane.mesh_state == "ready" and not w.busy and view.assembly.n_instances == 10)
    assert w.details.configuration_shown() == "Lite"
    assert _current(w) == "o02_boxA-1" and _picked(pane, view) == ["o02_boxA-1"]
    assert pane.highlight == ("instance", "o02_boxA-1")
    pane.set_mode("image")
    assert pane.pick_note.isHidden()
    pane.set_mode("3d")
    assert not pane.pick_note.isHidden()
    assert _state(FIXTURES) == before


@needs_qt
def test_a_right_click_on_an_instance_gives_its_rows_menu(viewer):
    from PySide6.QtCore import QPoint, QTimer
    from PySide6.QtWidgets import QApplication

    from solidseas_app.viewer.details import TABS

    w, pane, view = _assembly_3d(viewer)
    menu = w.details.instance_menu(INNER)
    texts = [a.text() for a in menu.actions()]
    # Its row's menu, 3D Print for its part and the sub-assembly it is in
    # (tests/test_viewer_print.py has the rest), how it looks, how that sub-assembly looks
    # and whether it explodes, and what puts the view back (tests/test_viewer_looks.py).
    assert texts == [
        opening.OPEN_TEXT,
        opening.show_text(),
        "",
        "Go to file",
        "Show in folder list",
        "Show on Components tab",
        "",
        "3D Print Part o07_boxB_h31.SLDPRT",
        "3D Print Sub-assembly o15_sub_asm.SLDASM",
        "",
        "Transparency",
        "Hide",
        "Isolate",
        "",
        "Sub-assembly o15_sub_asm-1",
        "",
        "Explode sub-assembly o15_sub_asm-1",
        "",
        "Show all",
        "Reset appearance",
    ]
    assert [a.font().bold() for a in menu.actions()[:4]] == [False, False, False, True]  # Go to file
    menu.actions()[5].trigger()  # Show on Components tab
    assert w.details.tabs.currentIndex() == TABS.index("Components") and _current(w) == INNER
    menu.deleteLater()
    w.details.tabs.setCurrentIndex(TABS.index("Preview"))

    # From the view: the menu opens where the click was, with the instance picked.
    seen: list = []

    def close_it() -> None:
        popup = QApplication.activePopupWidget()
        seen.append([a.text() for a in popup.actions()] if popup is not None else None)
        if popup is not None:
            popup.close()

    QTimer.singleShot(200, close_it)
    view.menuRequested.emit(pane.instance_ids.index(ROTATED), QPoint(100, 100))
    assert seen == [  # a top-level part: no sub-assembly
        [
            *texts[:7],
            "3D Print Part o02_boxA.SLDPRT",
            "Make Drawing of Part o02_boxA.SLDPRT...",
            "",
            *texts[10:13],
            "",
            "Show all",
            "Reset appearance",
        ]
    ]
    assert _current(w) == ROTATED and _picked(pane, view) == [ROTATED]
    seen.clear()
    QTimer.singleShot(200, close_it)
    view.menuRequested.emit(-1, QPoint(100, 100))  # on nothing: 3D Print this assembly
    assert seen == [["3D Print This Assembly", "Make Drawing of This Assembly..."]]
    assert w.details.instance_menu("no-such-instance") is None


@needs_qt
@pytest.mark.parametrize(
    ("ident", "opened"),
    [(ROTATED, "o02_boxA.SLDPRT"), (INNER, "o07_boxB_h31.SLDPRT"), ("Part12^o16_asm_features-1", None)],
)
def test_a_double_click_on_an_instance_opens_its_file_and_back_returns(viewer, ident, opened):
    """As a double-click on its row does: o02_boxA-2 (turned about Z) and the turned
    sub-assembly's o07 open their part files from the list, the virtual part opens
    from inside the assembly, in 3D from the mesh the assembly keeps of it (its own
    nested document has none); Back gives the assembly back on the Preview tab,
    exploded as it was, turned and zoomed as the user left it, with the same instance
    picked."""
    from solidseas_app.viewer.details import TABS

    before = _state(FIXTURES)
    w, pane, view = _assembly_3d(viewer)
    pane.set_explode(60)
    looked = {"yaw": 75.0, "pitch": 20.0, "target": [0.01, 0.02, 0.0], "half_height": 0.05, "fitted": False}
    view.cam = dict(looked)  # the user turned and zoomed the view
    asked: list = []
    w.details.componentRequested.connect(lambda *a: asked.append(a))
    view.activated.emit(pane.instance_ids.index(ident))
    _wait(viewer.app, lambda: not w.busy and pane.mesh_state not in ("starting", "loading"))
    _key, mode, parent, configuration = asked[-1]
    assert mode == "open" and configuration == "Default"
    assert (parent != "") == (ident == INNER)  # the sub-assembly's file key, as its row holds it
    if opened is None:  # the virtual part, stored inside o16
        assert w.apart is not None and w.details.title.text() == "Part12^o16_asm_features.SLDPRT"
        assert w.details.tabs.currentIndex() == TABS.index("Preview") and pane.mode == "3d"
        assert pane.mesh_state == "ready" and view.mesh.n_triangles == 12
        assert pane.mesh_info["stored_in"] == "assembly"
        caption = pane.caption.text()
        assert "the display mesh SOLIDWORKS keeps for this virtual part in its assembly" in caption
    else:
        assert w.apart is None and w.details.title.text() == opened
        assert w.details.tabs.currentIndex() == TABS.index("Preview") and pane.mode == "3d"
    assert w.history[-1].camera == looked and w.history[-1].explode == 60
    assert w.go_back()
    _wait(viewer.app, lambda: not w.busy and pane.mesh_state == "ready")
    assert w.details.title.text() == O16 and w.details.tabs.currentIndex() == TABS.index("Preview")
    assert _current(w) == ident and _picked(pane, view) == [ident]
    assert pane.explode_value == 60 and view.explode_calls[-1] == (0.6, False)
    assert view.cam == looked and view.camera_calls[-1] == looked  # after the explode, not the fit
    assert _state(FIXTURES) == before


@needs_qt
def test_an_instance_past_the_rows_shown_still_opens(viewer):
    """The Components tab shows at most 2,000 rows; an instance beyond them is found in
    the components section with the same file, sub-assembly and configuration."""
    from solidseas_app.viewer.details import _walk

    w, pane, _view = _assembly_3d(viewer)
    d = w.details
    links = {i: d.instance_link(i) for i in pane.instance_ids}
    assert links[INNER][1] != "" and links[ROTATED][1:] == ("", "Default")
    d.instances.clear()  # as if past the rows shown
    assert d.instance_item(ROTATED) is None and not list(_walk(d.instances))
    assert {i: d.instance_link(i) for i in pane.instance_ids} == links
    asked: list = []
    d.componentRequested.connect(lambda *a: asked.append(a))
    assert d.open_instance(INNER) and asked == [(links[INNER][0], "open", *links[INNER][1:])]
    assert not d.open_instance("no-such-instance")


# --------------------------------------------------------------------------- OpenGL, on the real display
_GL_PICK = """
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QContextMenuEvent, QHelpEvent, QKeyEvent, QMouseEvent
from solidseas_app.viewer import mesh3d
from solidseas_app.viewer.selftest import click, double_click
scene = mesh3d.read_assembly_scene(sys.argv[1], sys.argv[2], sys.argv[2], 1_000_000)["data"]
ids = [i for m in scene.instance_ids for i in m]
out = {"gl": True}

def mouse(view, kind, x, y, button):
    p = QPointF(x, y)
    held = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else button
    event = QMouseEvent(kind, p, view.mapToGlobal(p), button, held, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(view, event)

for instanced in (True, False):
    view3d.Renderer.allow_instancing = instanced
    view = view3d.ModelView()
    view.resize(480, 360)
    view.show()
    view.set_assembly(scene)
    app.processEvents()
    r = {}
    for amount in (0.0, 1.0):
        view.explode_to(amount, animate=False)
        got = {}
        for g, iid in enumerate(ids):
            p = view.pixel_of(g)
            got[iid] = None if p is None else view.instance_at(*p)
        r[str(amount)] = got
    r["corner"] = view.instance_at(1, 1)
    # Within three pixels of an instance a click still picks it; further away, nothing.
    g = ids.index("o02_boxA-2")
    p = view.pixel_of(g)
    r["pixel"] = p
    r["error"] = view.error
    if p is None:  # recorded as data: the assertions say what is missing
        out[str(instanced)] = r
        continue
    x, y = p
    edge = x
    while view.instance_at(edge + 1, y, 0) == g:
        edge += 1
    r["near"] = [view.instance_at(edge + d, y) for d in (1, 2, 3, 4, 6)]
    # Real mouse events: a click picks, a drag does not, a double-click asks for the file,
    # a right-click asks for the menu and a right-drag pans.
    events = {"picked": [], "activated": [], "menu": []}
    view.picked.connect(events["picked"].append)
    view.activated.connect(events["activated"].append)
    view.menuRequested.connect(lambda i, _p: events["menu"].append(i))
    click(view, (x, y))
    mouse(view, QEvent.Type.MouseButtonPress, x, y, Qt.MouseButton.LeftButton)
    mouse(view, QEvent.Type.MouseMove, x + 30, y, Qt.MouseButton.LeftButton)
    mouse(view, QEvent.Type.MouseButtonRelease, x + 30, y, Qt.MouseButton.LeftButton)  # a turn
    # Where it is drawn after each move, None when it has gone from view (recorded, so the
    # assertions fail on it rather than the script).
    r["seen_at"] = seen = [view.pixel_of(g)]
    if seen[-1] is not None:
        double_click(view, seen[-1])
    for dx in (0, 25):
        seen.append(view.pixel_of(g))
        p = seen[-1]
        if p is None:
            continue
        mouse(view, QEvent.Type.MouseButtonPress, p[0], p[1], Qt.MouseButton.RightButton)
        mouse(view, QEvent.Type.MouseMove, p[0] + dx, p[1], Qt.MouseButton.RightButton)
        mouse(view, QEvent.Type.MouseButtonRelease, p[0] + dx, p[1], Qt.MouseButton.RightButton)
        q = QPoint(int(p[0] + dx), int(p[1]))
        menu = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, q, view.mapToGlobal(q))
        QApplication.sendEvent(view, menu)
    click(view, (1, 1))
    r["events"] = {k: list(v) for k, v in events.items()}
    # Picked: drawn in the selection blue, the others faded toward the background.
    view.set_highlight([])
    plain = view.grabFramebuffer()
    view.set_highlight([g])
    lit = view.grabFramebuffer()
    p = view.pixel_of(g)
    other = view.pixel_of(ids.index("o09_import_step-1"))
    seen += [p, other]

    def colours(at):
        return None if at is None else [img.pixelColor(int(at[0]), int(at[1])).name() for img in (plain, lit)]

    r["picked_px"], r["other_px"] = colours(p), colours(other)
    r["background"] = plain.pixelColor(1, 1).name()
    r["selected"] = sorted(view.selected)
    n = len(events["picked"])
    esc = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(view, esc)
    r["escape"] = events["picked"][n:]
    # Hovering names the instance under the pointer, as plain text. (Qt shows a tooltip only
    # in the active window, so what the view asks Qt to show is recorded instead.)
    tips = []

    class Tip:
        @staticmethod
        def showText(_pos, text, _widget):
            tips.append(text)

        @staticmethod
        def hideText():
            tips.append("")

    view3d.QToolTip = Tip
    view.describe = lambda i: f"<b>instance {i}</b>"
    for at in (p, (1, 1)):
        if at is None:
            continue
        q = QPoint(int(at[0]), int(at[1]))
        QApplication.sendEvent(view, QHelpEvent(QEvent.Type.ToolTip, q, view.mapToGlobal(q)))
    r["tips"] = tips
    r["error"] = view.error
    out[str(instanced)] = r
print(json.dumps(out))
"""


def _rgb(name: str) -> tuple[int, int, int]:
    return int(name[1:3], 16), int(name[3:5], 16), int(name[5:7], 16)


@needs_qt
def test_every_instance_is_picked_where_it_is_drawn_on_the_display():
    """On the real display, instanced and one by one: each of o16's twelve instances is
    picked at a pixel where the view draws it, collapsed and fully exploded; the
    corner picks nothing; a click up to three pixels off an instance still picks it;
    real mouse events pick, open, ask for the menu, and leave a turn and a pan alone."""
    before = _state(FIXTURES)
    out = run_gl(_GL_PICK, str(fixture_path(O16)), str(FIXTURES))
    folder = str(FIXTURES)
    scene = mesh3d.read_assembly_scene(str(fixture_path(O16)), folder, folder, 1_000_000)["data"]
    ids = [i for m in scene.instance_ids for i in m]
    g = ids.index(ROTATED)
    for instanced in ("True", "False"):
        r = out[instanced]
        assert r["error"] is None
        for amount in ("0.0", "1.0"):
            assert r[amount] == {iid: k for k, iid in enumerate(ids)}, (instanced, amount)
        assert r["pixel"] is not None and None not in r.get("seen_at", [None]), r  # always in view
        assert r["corner"] is None
        assert r["near"][:3] == [g, g, g] and r["near"][4] is None
        # A click, a turn (no pick), a double-click (its first click picks), a right-click, a
        # pan (no menu) and a click on nothing.
        assert r["events"] == {"picked": [g, g, -1], "activated": [g], "menu": [g]}
        assert r["selected"] == [g] and r["escape"] == [-1]
        assert r["tips"] == [f"<qt>&lt;b&gt;instance {g}&lt;/b&gt;</qt>", ""]
        plain, lit = (_rgb(c) for c in r["picked_px"])
        assert lit[2] > lit[0] + 60 and lit != plain  # the selection blue
        bg = _rgb(r["background"])
        o_plain, o_lit = (_rgb(c) for c in r["other_px"])
        assert sum(abs(a - b) for a, b in zip(o_lit, bg, strict=True)) < sum(
            abs(a - b) for a, b in zip(o_plain, bg, strict=True)
        )  # faded toward the background
    assert out["True"]["0.0"] == out["False"]["0.0"]
    assert _state(FIXTURES) == before


@needs_qt
def test_the_self_test_picks_opens_and_comes_back(tmp_path):
    """The self-test picks each instance with a click, turns the view and zooms in toward
    it, double-clicks it, and fails unless Back gives the same document, tab, row, pick,
    explode and camera; and the virtual part opens in 3D, drawn from o16's mesh of it."""
    shots = tmp_path / "shots"
    before = _state(FIXTURES)
    args = ["--self-test", str(FIXTURES), "--screenshot-dir", str(shots), "--select", O16, "--3d"]
    args += ["--explode", "100", "--pick", ROTATED, "--pick", INNER, "--pick", VIRTUAL_INSTANCE]
    report = run_self_test(args, shots, appdata=tmp_path / "Roaming")
    (doc,) = report["documents"]
    got = [
        (p["name"], p["components_tab"], p["picked"], p["outcome"], p["shown"], p["back"])
        for p in doc["picked"]
    ]
    assert got == [
        (ROTATED, ROTATED, [ROTATED], "listed", "o02_boxA.SLDPRT", True),
        (INNER, INNER, [INNER], "listed", "o07_boxB_h31.SLDPRT", True),
        (VIRTUAL_INSTANCE, VIRTUAL_INSTANCE, [VIRTUAL_INSTANCE], "apart", VIRTUAL_FILE, True),
    ]
    for p in doc["picked"]:
        assert p["explode_after_back"] == 100 and p["picked_after_back"] == [p["name"]]
        assert p["camera_after_back"] is True
    assert doc["picked"][2]["opened_3d"] == {"state": "ready", "stored_in": "assembly", "triangles": 12}
    names = [Path(p).name for p in report["screenshots"]]
    for suffix in ("", "_components", "_open", "_back"):
        assert any(n.endswith(f"o16_asm_features_pick_o02_boxA-2{suffix}.png") for n in names), suffix
    assert any(n.endswith("pick_o15_sub_asm-1_o07_boxB_h31-1_open.png") for n in names)
    assert not (tmp_path / "Roaming").exists()
    assert _state(FIXTURES) == before


@needs_qt
def test_each_pick_of_the_self_test_starts_from_the_same_view(tmp_path):
    """Each pick turns the view and zooms in toward its instance, and Back puts that camera
    back; the next pick then starts from the view before the first, so an instance far
    from the last one is still in view: here every part exploded apart in Lite, the
    small virtual part at one end after o02_boxA-2, which used to leave it out of view."""
    shots = tmp_path / "shots"
    args = ["--self-test", str(FIXTURES), "--screenshot-dir", str(shots), "--select", O16, "--3d"]
    args += ["--configuration", "Lite", "--explode", "100,parts"]
    args += ["--pick", ROTATED, "--pick", VIRTUAL_INSTANCE]
    report = run_self_test(args, shots, appdata=tmp_path / "Roaming")
    (doc,) = report["documents"]
    assert [(p["name"], p["back"]) for p in doc["picked"]] == [(ROTATED, True), (VIRTUAL_INSTANCE, True)]


@needs_qt
def test_the_self_test_pick_option_is_checked(app, tmp_path, monkeypatch):
    from solidseas_app.viewer import app as viewer_app

    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    base = ["--self-test", str(FIXTURES), "--screenshot-dir", str(tmp_path / "s"), "--select", O16]
    assert viewer_app.build_parser().parse_args([*base, "--3d", "--pick", INNER]).pick == {O16: [INNER]}
    assert viewer_app.main([*base, "--pick", ROTATED]) == viewer_app.EXIT_USAGE  # needs --3d
    assert viewer_app.main(["--pick", ROTATED]) == viewer_app.EXIT_USAGE  # belongs to the self-test
    report = ["--self-test", str(FIXTURES), "--report", str(tmp_path / "r.json"), "--select-all", "--3d"]
    assert viewer_app.main([*report, "--pick", ROTATED]) == viewer_app.EXIT_USAGE
    assert not (tmp_path / "s").exists()


def _multi_body_step(folder: Path) -> Path:
    """A STEP assembly of a two-body part (duo 1) and a one-body part (box 1)."""
    from solidseas_app.viewer import samples

    f = samples._P21()
    ctx = f.context()
    duo = f.product("duo")
    duo_rep = f.shape(duo, [f.box(samples.BOX), f.box((10.0, 10.0, 10.0))], ctx)
    one = f.product("box")
    one_rep = f.shape(one, [f.box(samples.BOX)], ctx)
    top = f.product("rig")
    top_rep = f.shape(top, [], ctx)
    f.place(top, duo, top_rep, duo_rep, (0.0, 0.0, 0.0), "duo 1")
    f.place(top, one, top_rep, one_rep, (80.0, 0.0, 0.0), "box 1")
    path = folder / "rig.step"
    path.write_bytes(f.bytes("rig.step"))
    return path


@needs_qt
def test_a_click_on_either_body_of_a_multi_body_step_part_picks_its_row(viewer, tmp_path):
    """Both bodies of a two-body part in a STEP assembly stand for its one part row: a
    click on either selects that row, and the row picks both bodies back."""
    from solidseas_app.viewer.details import IDENT_ROLE, _walk

    _multi_body_step(tmp_path)
    w = viewer.window
    pane = w.details.preview
    made: list = []
    pane.view_factory = _stub_view_factory(made)
    pane.gl_check = lambda: (True, "test")
    viewer.open(tmp_path)
    w.change_settings(view_3d=True)
    _show(viewer, "rig.step")
    view = made[-1]
    ids = pane.instance_ids
    duo = [k for k, i in enumerate(ids) if i.split("/")[0] == "duo 1"]
    assert len(ids) == 3 and len(duo) == 2
    rows = {item.data(0, IDENT_ROLE): item for item in _walk(w.details.instances)}
    assert set(rows) == {"duo 1", "box 1"}
    for k in duo:
        view.picked.emit(k)
        assert _current(w) == "duo 1"
    view.picked.emit(ids.index("box 1"))
    assert _current(w) == "box 1"
    w.details.instances.setCurrentItem(rows["duo 1"])
    assert sorted(view.selected) == sorted(duo)
    assert w.details.files.topLevelItemCount() == 2


@needs_qt
def test_the_3d_view_is_made_before_the_window_turns_to_opengl(viewer):
    """With 3D on, the launcher makes the view before the window is first shown, so the
    window is an OpenGL one from the start (Windows makes a shown window again when it
    turns, which looks like the viewer closing and opening). Without OpenGL nothing is
    made, and turning 3D on makes the view at once."""
    w = viewer.window
    pane = w.details.preview
    made: list = []
    pane.view_factory = _stub_view_factory(made)
    pane.gl_check = lambda: (False, "test")
    pane.prepare_view()
    assert pane.view is None and not made
    pane.gl_result = None  # checked once per pane; this test gives OpenGL after all
    pane.gl_check = lambda: (True, "test")
    w.change_settings(view_3d=False)
    w.change_settings(view_3d=True)
    assert pane.view is made[-1] and len(made) == 1
    pane.prepare_view()  # made once
    assert len(made) == 1


_GL_NOT_REMADE = """
import os, time
from dataclasses import replace
from PySide6.QtCore import QEvent, QObject
from solidseas_app.viewer.details import TABS
from solidseas_app.viewer.preview import MODEL
from solidseas_app.viewer.settings import SettingsStore
from solidseas_app.viewer.window import MainWindow

part, folder = sys.argv[1], sys.argv[2]

def pump(until, timeout):
    end = time.monotonic() + timeout
    while not until():
        if time.monotonic() > end:
            return False
        app.processEvents()
        time.sleep(0.01)
    return True

class Remade(QObject):
    n = 0

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.WinIdChange:
            self.n += 1
        return False

out = {}
for launcher in ("now", "before"):
    store = SettingsStore(os.path.join(folder, launcher, "Viewer.ini"))
    store.save(replace(store.load(), view_3d=True))
    w = MainWindow(store)
    remade = Remade()
    w.installEventFilter(remade)
    w.resize(900, 640)
    if launcher == "now":
        w.details.preview.prepare_view()  # as the launcher does before the first show
    w.show()
    pump(lambda: False, 0.5)
    handle, n = int(w.winId()), remade.n
    details = []
    w.detailsFinished.connect(details.append)
    w.open_path(os.path.dirname(part))
    pump(lambda: not w.busy and w.model.find(os.path.basename(part)) is not None, 60)
    w.select_document(os.path.basename(part))
    pump(lambda: bool(details), 60)
    w.details.tabs.setCurrentIndex(TABS.index("Preview"))
    w.details.preview.set_mode(MODEL)
    drawn = pump(lambda: w.details.preview.mesh_state == "ready", 60)
    pump(lambda: False, 0.5)
    out[launcher] = {"drawn": drawn, "same": int(w.winId()) == handle, "remade": remade.n - n}
    w.close()
    pump(lambda: False, 0.3)
print(json.dumps(out))
"""


@needs_qt
def test_the_window_is_not_made_again_when_the_first_3d_part_is_drawn(tmp_path):
    """On the real display, with 3D on at launch: the view the launcher makes before the
    first show keeps the main window's native window when the first part is drawn in 3D.
    Made only then, as the launcher did before, the window is made again, which Windows
    showed as the viewer closing and opening (SolidSeas-clx); that half shows the check
    sees it."""
    before = _state(FIXTURES)
    out = run_gl(_GL_NOT_REMADE, str(fixture_path("o02_boxA.SLDPRT")), str(tmp_path))
    assert out["now"] == {"drawn": True, "same": True, "remade": 0}
    assert out["before"]["drawn"]
    if os.name == "nt":
        assert out["before"]["remade"] > 0 and not out["before"]["same"]
    assert _state(FIXTURES) == before


@needs_qt
def test_the_3d_view_s_menu_offers_the_camera(viewer, app):
    """A right-click on the 3D view's empty space, or anywhere on a part, offers how the
    camera looks as well as 3D Print: Zoom to Fit, the standard views, Home, Set Current
    View as Home and Copy Image, each doing what its key or the view cube does."""
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    w, pane, view = _assembly_3d(viewer)
    calls: list = []
    view.set_view = lambda name, animate=False: calls.append(("view", name))
    view.go_home = lambda animate=True: calls.append(("home",))
    view.set_home = lambda current: calls.append(("set_home", current))
    view.fit = lambda: calls.append(("fit",))
    image = QImage(4, 3, QImage.Format.Format_RGB32)
    image.fill(0xFF336699)
    view.grabFramebuffer = lambda: image
    menu = pane.space_menu()
    texts = [a.text() for a in menu.actions()]
    camera = ["Zoom to Fit", "Standard Views", "Go Home", "Set Current View as Home", "", "Copy Image"]
    assert texts[-6:] == camera and texts[-7] == ""  # after 3D Print This Assembly
    actions = {a.text(): a for a in menu.actions()}
    views = actions["Standard Views"].menu()
    names = ["Front", "Back", "Left", "Right", "Top", "Bottom", "Isometric"]
    assert [a.text() for a in views.actions()] == names
    assert views.actions()[6].shortcut().toString() == "Ctrl+7"
    actions["Zoom to Fit"].trigger()
    views.actions()[4].trigger()
    actions["Go Home"].trigger()
    actions["Set Current View as Home"].trigger()
    assert calls == [("fit",), ("view", "top"), ("home",), ("set_home", True)]
    QApplication.clipboard().clear()
    actions["Copy Image"].trigger()
    assert QApplication.clipboard().image().size() == image.size()
    menu.deleteLater()
