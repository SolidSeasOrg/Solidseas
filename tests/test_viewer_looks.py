"""Hiding, transparency and the choice of which sub-assemblies explode, in the SolidSeas
Viewer's 3D view of an assembly.

Right-clicking a component in the 3D view, a row of the Components tab, a file of
the Files table or of the legend offers Transparency, Hide, Isolate, Show all and
Reset appearance, and for a sub-assembly whether it explodes whatever the Explode
bar's level says. These tests check the choices themselves (which one decides an
instance's look, the groups an explode makes of them), the menus and the
Components tab with a stand-in for the OpenGL view, what the real view draws and
picks on the display on both drawing paths (transparent instances blended back to
front with the translucent boxes, hidden ones left out of the picture, the
picking and the camera's fit), Back and configuration switches, and the
self-test's options that check all of it by reading pixels back.

Every test that reads files checks that none of them changed.
"""

import math
import os
from array import array
from pathlib import Path

import pytest

from gl_support import run_gl, run_self_test
from solidseas_app.viewer import appearance, explode, mesh3d, opening
from solidseas_app.viewer.appearance import ALL, BOXES, FILE, ID, Look, Looks
from support import FIXTURES, fixture_path
from test_viewer import Viewer, _state, _stub_view_factory, _wait, needs_qt

O08, O15, O16 = "o08_asm_2x_boxA.SLDASM", "o15_sub_asm.SLDASM", "o16_asm_features.SLDASM"
SUB = "o15_sub_asm-1"
INNER = ("o15_sub_asm-1/o02_boxA-1", "o15_sub_asm-1/o07_boxB_h31-1")
ROTATED = "o02_boxA-2"


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


def _scene(name: str = O16, configuration: str | None = None) -> mesh3d.SceneBuffers:
    path, folder = str(fixture_path(name)), str(FIXTURES)
    return mesh3d.read_assembly_scene(path, folder, folder, 1_000_000, configuration=configuration)["data"]


def _offsets(e: explode.Explosion, ids) -> dict[str, tuple]:
    return {iid: e.offset(m, k) for m, mesh_ids in enumerate(ids) for k, iid in enumerate(mesh_ids)}


# --------------------------------------------------------------------------- the choices, no Qt
def test_the_latest_choice_that_covers_an_instance_decides():
    looks = Looks()
    assert looks.look("a-1") == Look() == appearance.SHOWN and not looks.changed
    looks.transparent((FILE, "housing"), 75)
    assert looks.look("h-1", ["housing"]).transparency == 75 and looks.look("h-1").transparency == 0
    looks.transparent((ID, "h-2"), 0)  # one instance of that file made opaque again, later
    assert (
        looks.look("h-2", ["housing"]).transparency == 0 and looks.look("h-1", ["housing"]).transparency == 75
    )
    looks.transparent((FILE, "housing"), 50)  # the file chosen again takes it along
    assert looks.look("h-2", ["housing"]).transparency == 50
    # A sub-assembly's choice covers everything under it, and a choice inside it wins after.
    looks.hide((ID, "sub-1"))
    assert looks.look("sub-1/p-1").hidden and looks.look("sub-1/inner-1/p-2").hidden
    assert not looks.look("sub-10/p-1").hidden  # the name, not a prefix of it
    looks.hide((ID, "sub-1/inner-1"), False)
    assert looks.look("sub-1/inner-1/p-2") == Look(hidden=False) and looks.look("sub-1/p-1").hidden
    # The boxes, and every instance; transparency is kept to 90 percent.
    looks.transparent((BOXES, ""), 400)
    assert looks.look("x-1", box=True).transparency == appearance.MAX_TRANSPARENCY
    assert looks.look("x-1").transparency == 0
    assert Look(transparency=75).opacity == pytest.approx(0.25)
    with pytest.raises(ValueError):
        looks.set(("nowhere", ""), appearance.HIDDEN, True)


def test_isolate_show_all_and_reset():
    looks = Looks()
    looks.transparent((ID, "a-1"), 25)
    looks.isolate((ID, "sub-1"))
    assert looks.look("a-1").hidden and not looks.look("sub-1/p-1").hidden and looks.any_hidden
    assert looks.look("a-1").transparency == 25
    looks.show_all()  # every one shown, transparency kept
    assert not looks.any_hidden and looks.look("a-1") == Look(transparency=25) and looks.changed
    looks.hide((ALL, ""))
    copy = Looks.from_state(looks.state())  # what Back keeps, and gives back
    assert copy.state() == looks.state() and copy.look("q-1").hidden
    copy.hide((ID, "q-1"), False)  # numbered after what it was given
    assert not copy.look("q-1").hidden and looks.look("q-1").hidden
    looks.reset()
    assert not looks.changed and looks.look("a-1") == Look()
    assert Looks.from_state(None).state() == {"seq": 0, "choices": []}


def test_a_sub_assemblys_choice_overrides_the_level():
    g = explode.group_of
    part, deep = "sub-1/p-1", "sub-1/inner-1/q-1"
    assert (g(part, explode.TOP), g(deep, explode.TOP)) == ("sub-1", "sub-1")
    assert (g(part, explode.PARTS), g(deep, explode.PARTS)) == (part, deep)
    # At Top-level, sub-1 switched on spreads its components; inner-1 keeps the level's default.
    on = {"sub-1": True}
    assert (g(part, explode.TOP, on), g(deep, explode.TOP, on), g("top-1", explode.TOP, on)) == (
        part,
        "sub-1/inner-1",
        "top-1",
    )
    assert g(deep, explode.TOP, {"sub-1": True, "sub-1/inner-1": True}) == deep
    # At Every part, sub-1 switched off moves as one, whatever is chosen inside it.
    assert g(deep, explode.PARTS, {"sub-1": False}) == "sub-1"
    assert g(deep, explode.PARTS, {"sub-1": False, "sub-1/inner-1": True}) == "sub-1"
    assert g(deep, explode.PARTS, {"sub-1/inner-1": False}) == "sub-1/inner-1"
    # At Top-level, inner-1 switched on is pulled out of sub-1, which stays together only by
    # the level: its components move apart, and the rest of sub-1 moves as one.
    inner_on = {"sub-1/inner-1": True}
    assert (g(deep, explode.TOP, inner_on), g(part, explode.TOP, inner_on)) == (deep, "sub-1")
    # Not through a sub-assembly chosen to stay together on the way down: f-1 stays whole.
    held = {"f-1/p-1": False, "f-1/p-1/b-1": True}
    assert g("f-1/p-1/b-1/c-1", explode.TOP, held) == "f-1" == g("f-1/q-1", explode.TOP, held)
    assert g("f-1/p-1/b-1/c-1", explode.PARTS, held) == "f-1/p-1"
    assert explode.subassemblies(deep) == ["sub-1", "sub-1/inner-1"] and explode.subassemblies("p-1") == []
    assert explode.explodes("sub-1", explode.TOP) is False and explode.explodes("sub-1", explode.PARTS)
    assert explode.explodes("sub-1", explode.PARTS, {"sub-1": False}) is False
    # A switch inside one chosen to stay together is held: it does not explode, whatever it says.
    assert explode.held_by("f-1/p-1/b-1", held) == "f-1/p-1" and explode.held_by("f-1/p-1", held) is None
    assert explode.held_by("a-1/b-1/c-1", {"a-1": False, "a-1/b-1": False}) == "a-1"  # the outermost
    assert explode.explodes("f-1/p-1/b-1", explode.TOP, held) is False
    assert explode.explodes("sub-1/inner-1", explode.TOP, inner_on) is True


def test_the_explode_follows_each_sub_assemblys_choice():
    """o16 at Top-level with o15_sub_asm-1 switched on is every part apart, as Every part
    is; at Every part with it off, its two parts move as one, as at Top-level."""
    before = _state(FIXTURES)
    scene = _scene()
    ids, bounds = scene.instance_ids, scene.bounds
    top, parts = (explode.explode(ids, bounds, level) for level in (explode.TOP, explode.PARTS))
    on = explode.explode(ids, bounds, explode.TOP, choices={SUB: True})
    off = explode.explode(ids, bounds, explode.PARTS, choices={SUB: False})
    assert (top.groups, parts.groups, on.groups, off.groups) == (11, 12, 12, 11)
    assert _offsets(on, ids) == _offsets(parts, ids) and _offsets(off, ids) == _offsets(top, ids)
    o_on, o_off = _offsets(on, ids), _offsets(off, ids)
    assert o_on[INNER[0]] != o_on[INNER[1]] and o_off[INNER[0]] == o_off[INNER[1]]
    assert _state(FIXTURES) == before


def test_hidden_instances_are_left_out_of_the_explode():
    """A hidden instance is in no group and moves by nothing; the rest spread as if it were
    not there, and neither the box nor the parting of overlaps counts it."""

    def box(c, h):
        return [c[0] - h[0], c[1] - h[1], c[2] - h[2], c[0] + h[0], c[1] + h[1], c[2] + h[2]]

    rows = [
        box((0.1, 0.0, 0.0), (0.08, 0.03, 0.03)),  # a housing
        box((0.11, 0.01, 0.0), (0.01, 0.01, 0.025)),  # a pin in it
        box((-0.1, 0.0, 0.0), (0.02, 0.02, 0.02)),
        box((5.0, 5.0, 5.0), (0.01, 0.01, 0.01)),  # far away, hidden
    ]
    ids = [["housing-1", "pin-1", "other-1", "far-1"]]
    bounds = [array("f", [v for r in rows for v in r]).tobytes()]
    shown = explode.explode([ids[0][:3]], [array("f", [v for r in rows[:3] for v in r]).tobytes()])
    hidden = explode.explode(ids, bounds, hidden=[[False, False, False, True]])
    assert hidden.groups == 3 and hidden.offset(0, 3) == (0.0, 0.0, 0.0)
    assert [hidden.offset(0, k) for k in range(3)] == [shown.offset(0, k) for k in range(3)]
    assert hidden.bbox0 == shown.bbox0 and hidden.bbox1 == shown.bbox1  # the far one is not counted
    every = explode.explode(ids, bounds, hidden=[[True] * 4])
    assert every.groups == 0 and every.moving == 0


# --------------------------------------------------------------------------- the pane, a stand-in view
def _show(viewer, name: str) -> None:
    from solidseas_app.viewer.details import TABS

    w = viewer.window
    w.details.tabs.setCurrentIndex(TABS.index("Preview"))
    viewer.select(name)
    _wait(viewer.app, lambda: w.details.preview.mesh_state not in ("starting", "loading") and not w.busy)


def _assembly_3d(viewer, name: str = O16):
    w = viewer.window
    pane = w.details.preview
    made: list = []
    pane.view_factory = _stub_view_factory(made)
    pane.gl_check = lambda: (True, "test")
    viewer.open(FIXTURES)
    w.change_settings(view_3d=True)
    _show(viewer, name)
    return w, pane, made[-1]


def _actions(menu, prefix: str = "") -> dict[str, object]:
    """A menu's actions by their text, a submenu's under ``title/text``."""
    out = {}
    for a in menu.actions():
        if a.menu() is not None:
            out.update(_actions(a.menu(), f"{prefix}{a.text()}/"))
        elif a.text():
            out[prefix + a.text()] = a
    return out


def _looks(pane, view) -> dict[str, tuple[float, bool]]:
    """What the stand-in view was asked to draw, by instance id, for the instances not as
    the file draws them."""
    return {
        iid: (round(a, 4), h)
        for iid, a, h in zip(pane.instance_ids, view.opacity, view.hidden, strict=True)
        if a != 1.0 or h
    }


@needs_qt
def test_the_3d_views_menu_makes_a_housing_see_through_and_puts_it_back(viewer):
    """The user's case: a part made 75 percent transparent from its menu in the view, then
    opaque again; its sub-assembly made transparent from the submenu; hidden, isolated,
    shown again and reset. Each is drawn as chosen and the menus say what holds now. The
    right-click that opens the menu picks the part, and the look chosen drops that pick,
    so nothing is drawn faded round the part made see-through."""
    before = _state(FIXTURES)
    w, pane, view = _assembly_3d(viewer)
    d = w.details

    def right_click(ident: str) -> dict:
        view.picked.emit(pane.instance_ids.index(ident))  # picked, as a right-click there does
        assert view.selected == {pane.instance_ids.index(ident)} and d.instances.currentItem() is not None
        return _actions(d.instance_menu(ident))

    def unpicked() -> bool:
        return pane.highlight is None and view.selected == set() and d.instances.currentItem() is None

    acts = right_click(ROTATED)
    assert [t for t in acts if t.startswith("Transparency/")] == [
        "Transparency/Opaque",
        "Transparency/25%",
        "Transparency/50%",
        "Transparency/75%",
        "Transparency/90%",
    ]
    assert acts["Transparency/Opaque"].isChecked() and not acts["Show all"].isEnabled()
    assert not acts["Reset appearance"].isEnabled()
    acts["Transparency/75%"].trigger()
    assert _looks(pane, view) == {ROTATED: (0.25, False)} and unpicked()
    acts = right_click(ROTATED)
    assert acts["Transparency/75%"].isChecked() and acts["Reset appearance"].isEnabled()
    acts["Transparency/Opaque"].trigger()  # and back
    assert _looks(pane, view) == {} and unpicked()

    # The sub-assembly a part is in, from that part's menu: its own submenu.
    acts = right_click(INNER[1])
    acts[f"Sub-assembly {SUB}/Transparency/50%"].trigger()
    assert _looks(pane, view) == {INNER[0]: (0.5, False), INNER[1]: (0.5, False)} and unpicked()
    acts = right_click(INNER[0])
    assert acts["Transparency/50%"].isChecked() and acts[f"Sub-assembly {SUB}/Transparency/50%"].isChecked()
    acts["Hide"].trigger()
    assert _looks(pane, view) == {INNER[0]: (0.5, True), INNER[1]: (0.5, False)} and unpicked()
    assert pane.pick_note.isHidden()
    # Its row picked on the Components tab: the note says it is hidden, and as it is drawn
    # nowhere, nothing is drawn picked or faded for it.
    d.instances.setCurrentItem(d.instance_item(INNER[0]))
    assert pane.highlight == ("instance", INNER[0]) and view.selected == set()
    assert pane.pick_note.text().endswith("It is hidden: Show all brings it back.")
    pane.set_hidden(("instance", INNER[0]), False)  # not from a menu: the pick stays
    assert view.selected == {pane.instance_ids.index(INNER[0])}
    pane.set_hidden(("instance", INNER[0]))
    assert view.selected == set() and pane.highlight == ("instance", INNER[0])

    # Isolate hides everything else; Show all brings it back, transparency kept; Reset.
    right_click(ROTATED)["Isolate"].trigger()
    assert unpicked()
    looks = _looks(pane, view)
    assert looks.pop(ROTATED, None) is None and len(looks) == 11 and all(h for _a, h in looks.values())
    acts = _actions(d.instance_menu(ROTATED))
    assert acts["Show all"].isEnabled()
    acts["Show all"].trigger()
    assert _looks(pane, view) == {INNER[0]: (0.5, False), INNER[1]: (0.5, False)}
    _actions(d.instance_menu(ROTATED))["Reset appearance"].trigger()
    assert _looks(pane, view) == {} and not pane.looks.changed
    assert _state(FIXTURES) == before


@needs_qt
def test_everything_hidden_says_so_and_empty_space_gives_show_all(viewer):
    from PySide6.QtCore import QPoint, QTimer
    from PySide6.QtWidgets import QApplication

    w, pane, view = _assembly_3d(viewer)
    seen: list = []

    def close_it() -> None:
        popup = QApplication.activePopupWidget()
        seen.append([a.text() for a in popup.actions() if a.isEnabled()] if popup is not None else None)
        if popup is not None:
            popup.close()

    QTimer.singleShot(200, close_it)
    view.menuRequested.emit(-1, QPoint(10, 10))  # nothing chosen yet: only 3D Print and its drawing
    assert seen == [["3D Print This Assembly", "Make Drawing of This Assembly..."]]
    seen.clear()
    for g in range(len(pane.instance_ids)):
        pane.set_hidden(("instance", pane.instance_ids[g]))
    assert all(view.hidden) and pane.pick_note.text() == (
        "Every component is hidden. Right-click the view for Show all."
    )
    QTimer.singleShot(200, close_it)
    view.menuRequested.emit(-1, QPoint(10, 10))  # empty space: what puts the view back
    assert seen == [
        ["3D Print This Assembly", "Make Drawing of This Assembly...", "", "Show all", "Reset appearance"]
    ]
    pane.show_all()
    assert not any(view.hidden) and pane.pick_note.isHidden()


@needs_qt
def test_tab_hides_the_part_under_the_pointer_and_shift_tab_shows_all(viewer):
    w, pane, view = _assembly_3d(viewer)
    assert not view.any_hidden()  # Shift+Tab then moves the focus, as elsewhere
    view.hideRequested.emit(0)
    assert _looks(pane, view) == {pane.instance_ids[0]: (1.0, True)}
    assert view.any_hidden()
    view.hideRequested.emit(len(pane.instance_ids))  # no such instance: nothing
    assert _looks(pane, view) == {pane.instance_ids[0]: (1.0, True)}
    view.showAllRequested.emit()
    assert not any(view.hidden) and not view.any_hidden()


@needs_qt
def test_the_views_tab_keys_act_only_with_something_to_hide_or_show():
    from types import SimpleNamespace

    from PySide6.QtCore import QEvent, QPoint, QRect, Qt
    from PySide6.QtGui import QKeyEvent

    from solidseas_app.viewer.view3d import ModelView

    sent: list = []
    under = {"index": 2}
    fake = SimpleNamespace(
        can_pick=True,
        any_hidden=lambda: bool(sent),
        hideRequested=SimpleNamespace(emit=lambda i: sent.append(("hide", i))),
        showAllRequested=SimpleNamespace(emit=lambda: sent.append(("show",))),
        mapFromGlobal=lambda _p: QPoint(5, 5),
        rect=lambda: QRect(0, 0, 10, 10),
        instance_at=lambda _x, _y: under["index"],
    )

    def key(k, mods=Qt.KeyboardModifier.NoModifier) -> bool:
        return ModelView._hide_key(fake, QKeyEvent(QEvent.Type.KeyPress, k, mods))

    shift = Qt.KeyboardModifier.ShiftModifier
    assert not key(Qt.Key.Key_Backtab, shift)  # nothing hidden: the focus moves back
    assert key(Qt.Key.Key_Tab) and sent == [("hide", 2)]
    assert key(Qt.Key.Key_Backtab, shift) and sent[-1] == ("show",)
    assert not key(Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)  # Ctrl+Tab is Qt's
    ctrl_shift = Qt.KeyboardModifier.ControlModifier | shift
    assert not key(Qt.Key.Key_Backtab, ctrl_shift)
    assert not key(Qt.Key.Key_Tab, Qt.KeyboardModifier.AltModifier)
    under["index"] = None
    assert not key(Qt.Key.Key_Tab)  # no part under the pointer: the focus moves on
    fake.can_pick = False
    assert not key(Qt.Key.Key_Backtab, shift)  # a part's view: nothing to hide
    fake.mapFromGlobal = lambda _p: QPoint(50, 50)
    fake.can_pick, under["index"] = True, 1
    assert not key(Qt.Key.Key_Tab)  # the pointer is elsewhere
    assert len(sent) == 2


@needs_qt
def test_the_components_tab_shows_and_offers_the_same(viewer):
    """Rows of hidden instances are greyed with an eye struck through, transparent ones
    marked with a half filled square, a sub-assembly's row only when all of its parts are
    so; a row's menu has the same items, a sub-assembly's its explode switch, a file's
    for every instance of it."""
    from PySide6.QtGui import QIcon

    from solidseas_app.viewer.details import IDENT_ROLE, _walk

    w, pane, view = _assembly_3d(viewer)
    d = w.details
    rows = {item.data(0, IDENT_ROLE): item for item in _walk(d.instances)}
    files = {
        d.files.topLevelItem(i).text(0): d.files.topLevelItem(i) for i in range(d.files.topLevelItemCount())
    }
    assert all(item.icon(0).isNull() for item in rows.values())
    menu = d.component_menu(rows[SUB])
    acts = _actions(menu)
    assert "Explode this sub-assembly" in acts and not acts["Explode this sub-assembly"].isChecked()
    acts["Hide"].trigger()
    sub, inner = rows[SUB], rows[INNER[0]]
    assert not sub.icon(0).isNull() and not inner.icon(0).isNull()
    grey = d.palette().color(d.palette().ColorGroup.Disabled, d.palette().ColorRole.Text)
    assert sub.foreground(0).color() == grey and "Hidden in the 3D view." in sub.toolTip(0)
    assert _actions(d.component_menu(sub))["Show"].text() == "Show"  # all hidden: the item shows it
    _actions(d.component_menu(sub))["Show"].trigger()
    assert sub.icon(0).isNull() and sub.foreground(0).color() != grey and "3D view" not in sub.toolTip(0)
    # A part transparent marks its row; its sub-assembly's only when every part is.
    _actions(d.component_menu(inner))["Transparency/25%"].trigger()
    assert not inner.icon(0).isNull() and sub.icon(0).isNull()
    assert "25% transparent in the 3D view." in inner.toolTip(0)
    # A file's row: every instance of that file, here and in the legend.
    o07 = files["o07_boxB_h31.SLDPRT"]
    acts = _actions(d.component_menu(o07))
    assert list(acts)[:4] == [opening.OPEN_TEXT, opening.show_text(), "Go to file", "Show in folder list"]
    assert "Explode this sub-assembly" not in acts
    acts["Hide"].trigger()
    assert not o07.icon(0).isNull() and o07.foreground(0).color() == grey
    hidden = {iid for iid, (_a, h) in _looks(pane, view).items() if h}
    assert hidden == {INNER[1], "o07_boxB_h31-2", "o07_boxB_h31-3", "o07_boxB_h31-4"}
    legend = {pane.legend.item(i).text(): pane.legend.item(i) for i in range(pane.legend.count())}
    assert legend["o07_boxB_h31.SLDPRT (4)"].foreground().color() == grey
    # A suppressed instance keeps its grey when the hidden state goes.
    suppressed = rows["o07_boxB_h31-1"]
    assert suppressed.foreground(0).color() == grey and suppressed.icon(0).isNull()
    pane.reset_appearance()
    assert suppressed.foreground(0).color() == grey and o07.foreground(0).color() != grey
    assert all(item.icon(0).isNull() for item in rows.values())
    assert isinstance(sub.icon(0), QIcon)


@needs_qt
def test_a_sub_assembly_file_covers_its_parts_and_what_is_not_drawn_is_greyed(viewer):
    """A sub-assembly's file in the Files table covers every part of every instance of it:
    hidden, made transparent and isolated as one, its row marked, its pick named. A row
    with nothing drawn (a suppressed instance, or o15 in Lite where it is suppressed)
    offers the items greyed with the reason, and Isolate there hides nothing."""
    from solidseas_app.viewer.details import IDENT_ROLE, _walk

    before = _state(FIXTURES)
    w, pane, view = _assembly_3d(viewer)
    d = w.details
    files = {
        d.files.topLevelItem(i).text(0): d.files.topLevelItem(i) for i in range(d.files.topLevelItemCount())
    }
    o15 = files[O15]
    key = o15.data(0, IDENT_ROLE)
    assert pane.component_files[SUB] == key and pane.indices_of(("file", key)) == sorted(
        pane.instance_ids.index(i) for i in INNER
    )
    d.files.setCurrentItem(o15)  # its pick: the parts drawn under it
    assert view.selected == {pane.instance_ids.index(i) for i in INNER}
    assert pane.pick_note.text() == f"Picked: every instance of {O15} (2 parts shown)."
    acts = _actions(d.component_menu(o15))
    assert acts["Hide"].isEnabled() and acts["Isolate"].isEnabled()
    acts["Hide"].trigger()
    assert _looks(pane, view) == {INNER[0]: (1.0, True), INNER[1]: (1.0, True)}
    assert d.files.currentItem() is None and not o15.icon(0).isNull()  # the pick dropped, the row marked
    acts = _actions(d.component_menu(o15))
    assert "Show" in acts and "Hide" not in acts
    acts["Show"].trigger()
    _actions(d.component_menu(o15))["Transparency/50%"].trigger()
    assert _looks(pane, view) == {INNER[0]: (0.5, False), INNER[1]: (0.5, False)}
    assert _actions(d.component_menu(o15))["Transparency/50%"].isChecked()
    assert "50% transparent in the 3D view." in o15.toolTip(0)
    _actions(d.component_menu(o15))["Isolate"].trigger()
    assert sorted(i for i, (_a, h) in _looks(pane, view).items() if not h) == sorted(INNER)
    pane.reset_appearance()

    # Nothing drawn: a suppressed instance's row.
    rows = {item.data(0, IDENT_ROLE): item for item in _walk(d.instances)}
    suppressed = "o07_boxB_h31-1"
    assert suppressed not in pane.instance_ids
    acts = _actions(d.component_menu(rows[suppressed]))
    menu_titles = {a.text(): a for a in d.component_menu(rows[suppressed]).actions()}
    assert not acts["Hide"].isEnabled() and not acts["Isolate"].isEnabled()
    assert not menu_titles["Transparency"].isEnabled()
    assert "draws none of it here" in acts["Isolate"].toolTip()
    assert not any(a.isChecked() for t, a in acts.items() if t.startswith("Transparency/"))
    pane.isolate(("instance", suppressed))  # what the item would do: nothing, not hide it all
    assert not any(view.hidden) and not pane.looks.changed

    # o15 in Lite, where it is suppressed: its file's row is greyed the same way.
    pane.config_combo.setCurrentText("Lite")
    pane.choose_configuration("Lite")
    _wait(viewer.app, lambda: pane.mesh_state == "ready" and not w.busy and view.assembly.n_instances == 10)
    files = {
        d.files.topLevelItem(i).text(0): d.files.topLevelItem(i) for i in range(d.files.topLevelItemCount())
    }
    acts = _actions(d.component_menu(files[O15]))
    assert not acts["Hide"].isEnabled() and not acts["Isolate"].isEnabled()
    assert _state(FIXTURES) == before


@needs_qt
def test_the_legend_has_the_files_menu(viewer):
    from PySide6.QtCore import QPoint, QTimer
    from PySide6.QtWidgets import QApplication

    w, pane, view = _assembly_3d(viewer)
    seen: list = []

    def use_it() -> None:
        popup = QApplication.activePopupWidget()
        acts = {a.text(): a for a in popup.actions()} if popup is not None else {}
        seen.append(list(acts))
        if popup is not None:
            popup.close()
            acts["Isolate"].trigger()

    key = pane.files[0]["key"]  # o02_boxA.SLDPRT: four instances
    QTimer.singleShot(200, use_it)
    pane.legend.fileMenu.emit(key, QPoint(5, 5))
    assert seen[0][:5] == [opening.OPEN_TEXT, opening.show_text(), "", "Go to file", "Show in folder list"]
    assert "Isolate" in seen[0]
    shown = [iid for iid, h in zip(pane.instance_ids, view.hidden, strict=True) if not h]
    assert sorted(shown) == sorted(["o02_boxA-1", "o02_boxA-2", "o02_boxA-3", INNER[0]])
    # The right-click picked every instance of the file, as a click does; the look chosen
    # dropped that pick, here and in the Files table.
    assert pane.highlight is None and view.selected == set() and w.details.files.currentItem() is None


@needs_qt
def test_the_explode_switch_of_a_sub_assembly(viewer):
    """The switch is offered for each sub-assembly on the part's path in the view and on
    the sub-assembly's own row; it is the bar's level until chosen, the view groups by
    it, the bar says so, and it holds across configurations and while the viewer runs,
    until Reset appearance."""
    from solidseas_app.viewer.details import IDENT_ROLE, _walk

    w, pane, view = _assembly_3d(viewer)
    d = w.details
    acts = _actions(d.instance_menu(INNER[0]))
    switch = acts[f"Explode sub-assembly {SUB}"]
    assert switch.isCheckable() and not switch.isChecked()  # Top-level: kept together
    pane.set_explode_level("parts")
    assert _actions(d.instance_menu(INNER[0]))[f"Explode sub-assembly {SUB}"].isChecked()
    pane.set_explode_level("top")
    switch.trigger()  # on
    assert pane.explode_choices == {SUB: True} and view.explode_choices == {SUB: True}
    pane.set_explode(100)
    assert pane.explode_hint.text() == f"By your choice, {SUB} explodes."
    assert "12 groups move apart" in pane.explode_percent.toolTip()
    rows = {item.data(0, IDENT_ROLE): item for item in _walk(d.instances)}
    assert _actions(d.component_menu(rows[SUB]))["Explode this sub-assembly"].isChecked()

    # Another configuration keeps it; another document has none; coming back, it is there.
    pane.config_combo.setCurrentText("Lite")
    pane.choose_configuration("Lite")
    _wait(viewer.app, lambda: pane.mesh_state == "ready" and not w.busy and view.assembly.n_instances == 10)
    assert view.explode_choices == {SUB: True} and pane.explode_choices == {SUB: True}
    # o15 is suppressed there: the bar does not name a choice that changes nothing.
    assert pane.explode_hint.isHidden() and SUB not in pane.explode_percent.toolTip()
    assert pane.explode_percent.toolTip() == "<qt>10 top-level components move apart.</qt>"
    _show(viewer, O08)
    assert pane.explode_choices == {} and pane.explode_hint.isHidden()
    _show(viewer, O16)
    assert pane.explode_choices == {SUB: True} and view.explode_choices == {SUB: True}
    _actions(d.instance_menu(ROTATED))["Reset appearance"].trigger()
    assert pane.explode_choices == {} == view.explode_choices
    _show(viewer, O08)
    _show(viewer, O16)
    assert pane.explode_choices == {}


@needs_qt
def test_nested_sub_assemblies_each_have_their_switch(app):
    """A part two sub-assemblies deep: a submenu and a switch for each, from the part up.
    The inner one switched on spreads its parts even at Top-level, pulled out of the outer
    one, whose rest moves as one; with the outer one chosen to stay together, the inner
    switch is held: greyed, unchecked, its tooltip naming the outer one, and the bar leaves
    it out."""
    from PySide6.QtWidgets import QMenu

    from solidseas_app.viewer.preview import PreviewPane

    pane = PreviewPane()
    pane.instance_ids = ["panel-1/board-1/chip-1", "panel-1/board-1/chip-2", "panel-1/cover-1", "base-1"]
    pane.doc_type = "assembly"
    pane.explode_groups = {"top": 2, "parts": 4}  # as a scene of these gives them

    def switches() -> dict:
        menu = QMenu(pane)
        pane.add_instance_actions(menu, "panel-1/board-1/chip-1", path=True)
        acts = _actions(menu)
        return {sub: acts[f"Explode sub-assembly {sub}"] for sub in ("board-1", "panel-1")}

    menu = QMenu()
    pane.add_instance_actions(menu, "panel-1/board-1/chip-1", path=True)
    texts = [a.text() for a in menu.actions() if a.text()]
    assert texts[3:] == [
        "Sub-assembly board-1",
        "Sub-assembly panel-1",
        "Explode sub-assembly board-1",
        "Explode sub-assembly panel-1",
        "Show all",
        "Reset appearance",
    ]
    _actions(menu)["Explode sub-assembly board-1"].trigger()
    assert pane.explode_pieces() == 4  # the two chips, the rest of panel-1 (its cover), the base
    assert pane.explode_hint.text() == "By your choice, board-1 explodes."
    s = switches()
    assert s["board-1"].isChecked() and s["board-1"].isEnabled() and not s["panel-1"].isChecked()
    # panel-1 kept together: board-1 moves with it, whatever its own switch says.
    pane.set_subassembly_explodes("panel-1", False)
    assert pane.explode_pieces() == 2
    assert pane.explode_hint.text() == "By your choice, panel-1 stays together."
    s = switches()
    assert not s["board-1"].isChecked() and not s["board-1"].isEnabled()
    assert "moves as one with panel-1, which you chose to keep together" in s["board-1"].toolTip()
    assert "Your choice for it, to explode, holds once panel-1 explodes." in s["board-1"].toolTip()
    pane.set_subassembly_explodes("panel-1", True)
    assert pane.explode_pieces() == 4  # the chips, the cover and the base
    assert pane.explode_hint.text() == "By your choice, panel-1 and board-1 explode."
    pane.set_explode_level("parts")
    pane.set_subassembly_explodes("panel-1/board-1", False)
    assert pane.explode_pieces() == 3
    assert pane.explode_hint.text() == "By your choice, panel-1 explodes and board-1 stays together."


@needs_qt
def test_the_explode_bar_counts_the_groups_the_choices_make(app):
    """The bar's note and tooltip go by the groups as the choices make them: one top-level
    sub-assembly switched on at Top-level moves its parts apart, and the only one switched
    off at Every part moves nothing."""
    from solidseas_app.viewer.preview import PreviewPane

    pane = PreviewPane()
    pane.instance_ids = ["sub-1/a-1", "sub-1/b-1", "sub-1/c-1"]
    pane._no_boxes()  # as a scene of these, without boxes, leaves it
    pane.doc_type = "assembly"
    pane.explode_groups = {"top": 1, "parts": 3}
    pane.set_explode_level("top")
    pane.set_explode(100)
    single = "There is only one top-level component, so nothing moves: choose Every part."
    assert pane.explode_hint.text() == single
    pane.set_subassembly_explodes("sub-1", True)
    assert pane.explode_pieces() == 3 and pane.explode_hint.text() == "By your choice, sub-1 explodes."
    assert pane.explode_percent.toolTip() == "<qt>3 groups move apart; by your choice, sub-1 explodes.</qt>"
    pane.set_explode_level("parts")
    pane.set_subassembly_explodes("sub-1", False)
    nothing = "Nothing moves: what is shown moves as one piece (by your choice, sub-1 stays together)."
    assert pane.explode_pieces() == 1 and pane.explode_hint.text() == nothing
    assert pane.explode_percent.toolTip() == f"<qt>{nothing}</qt>"
    pane.reset_appearance()
    assert pane.explode_hint.isHidden() and pane.explode_percent.toolTip() == "<qt>3 parts move apart.</qt>"


@needs_qt
def test_the_looks_hold_across_configurations_and_back(viewer):
    """Kept by id and file across a configuration switch, for the ids still there; reset
    by another document; put back by Back with the explode switch and the camera."""
    w, pane, view = _assembly_3d(viewer)
    pane.set_transparency(("instance", SUB), 75)  # o15 is suppressed in Lite
    pane.set_hidden(("instance", "o09_import_step-1"))
    pane.set_subassembly_explodes(SUB, True)
    both = {INNER[0]: (0.25, False), INNER[1]: (0.25, False), "o09_import_step-1": (1.0, True)}
    pane.config_combo.setCurrentText("Lite")
    pane.choose_configuration("Lite")
    _wait(viewer.app, lambda: pane.mesh_state == "ready" and not w.busy and view.assembly.n_instances == 10)
    assert _looks(pane, view) == {"o09_import_step-1": (1.0, True)}
    from solidseas_app.viewer.details import IDENT_ROLE, _walk

    rows = {item.data(0, IDENT_ROLE): item for item in _walk(w.details.instances)}  # read again in Lite
    assert not rows["o09_import_step-1"].icon(0).isNull() and rows["o02_boxA-1"].icon(0).isNull()
    pane.choose_configuration("Default")
    _wait(viewer.app, lambda: pane.mesh_state == "ready" and not w.busy and view.assembly.n_instances == 12)
    assert _looks(pane, view) == both
    # Open a part from the view and come back: everything as it was.
    pane.set_explode(60)
    view.activated.emit(pane.instance_ids.index(ROTATED))
    _wait(viewer.app, lambda: not w.busy and pane.mesh_state not in ("starting", "loading"))
    assert w.details.title.text() == "o02_boxA.SLDPRT" and not pane.looks.changed
    assert w.history[-1].view["explode"] == {SUB: True}
    assert w.go_back()
    _wait(viewer.app, lambda: not w.busy and pane.mesh_state == "ready")
    assert w.details.title.text() == O16 and pane.explode_value == 60
    assert _looks(pane, view) == both
    assert view.explode_choices == {SUB: True} and view.explode_calls[-1] == (0.6, False)


# --------------------------------------------------------------------------- OpenGL, on the real display
_GL_LOOKS = """
import math
from array import array
from solidseas_app.viewer import mesh3d
from solidseas_app.viewer.view3d import BOX_MESH, Scene, _box_mesh

scene = mesh3d.read_assembly_scene(sys.argv[1], sys.argv[2], sys.argv[2], 1_000_000)["data"]
ids = [i for m in scene.instance_ids for i in m]
n = len(ids)
SUB = "o15_sub_asm-1"
sub = [g for g, i in enumerate(ids) if i.startswith(SUB + "/")]
out = {"gl": True, "ids": ids}


def rgb(img):
    img = img.convertToFormat(img.Format.Format_RGBA8888)
    w, h, row = img.width(), img.height(), img.bytesPerLine()
    data = bytes(img.constBits())
    return [tuple(data[y * row + 4 * x : y * row + 4 * x + 3]) for y in range(h) for x in range(w)]


def dist(a, b):
    return sum(abs(x - y) for x, y in zip(a, b))


def cube(lo, hi):
    sx, sy, sz = (hi[i] - lo[i] for i in range(3))
    m = array("f", [sx, 0, 0, 0, 0, sy, 0, 0, 0, 0, sz, 0, lo[0], lo[1], lo[2], 1])
    return m.tobytes()


for instanced in (True, False):
    view3d.Renderer.allow_instancing = instanced
    r = {}
    view = view3d.ModelView()
    view.resize(480, 360)
    view.show()
    view.set_assembly(scene)
    app.processEvents()
    r["rank_far"] = view.renderer.rank_far
    plain = rgb(view.grabFramebuffer())
    ids0 = view.ids_drawn()
    # o15's two parts 75 percent transparent: drawn over what is behind them, nearer it.
    opacity = [0.25 if g in sub else 1.0 for g in range(n)]
    clear = [0.0 if g in sub else 1.0 for g in range(n)]
    view.set_looks(clear, None)
    behind = rgb(view.grabFramebuffer())
    view.set_looks(opacity, None)
    seen = rgb(view.grabFramebuffer())
    r["image"] = seen
    own = [k for k, i in enumerate(ids0) if i in sub]
    W, H = view.width(), view.height()
    near = {
        (k // W + dy) * W + k % W + dx for k in own for dy in range(-2, 3) for dx in range(-2, 3)
    }  # its pixels and their neighbours: the edges are blended
    others = [k for k in range(W * H) if k not in near]
    r["own"] = len(own)
    r["changed"] = sum(1 for k in own if dist(seen[k], plain[k]) > 3) / len(own)
    nearer = sum(1 for k in own if dist(seen[k], behind[k]) < dist(plain[k], behind[k]))
    r["toward_behind"] = nearer / len(own)
    r["others_same"] = sum(1 for k in others if seen[k] == plain[k]) / len(others)
    r["sorted"] = view.renderer.sorted_items
    r["camera_box_same"] = list(map(list, view.camera.bbox)) == list(map(list, view.scene.bbox))
    # Still picked where it is drawn over the background.
    ids1 = view.ids_drawn()
    alone = [k for k in own if behind[k] == behind[0]]
    r["picked_alone"] = sum(1 for k in alone if ids1[k] in sub) / max(len(alone), 1)
    # Hidden: not drawn, not picked, not in the camera's box; everything hidden: the scene's box.
    hidden = [g in sub for g in range(n)]
    view.set_looks(None, hidden)
    ids2 = view.ids_drawn()
    r["hidden_picked"] = sum(1 for i in ids2 if i in sub)
    r["hidden_found"] = [view.pixel_of(g) for g in sub]
    lo, hi = [9e9] * 3, [-9e9] * 3
    g = 0
    for raw in scene.bounds:
        b = array("f")
        b.frombytes(raw)
        for k in range(len(b) // 6):
            if g not in sub:
                lo = [min(lo[i], b[6 * k + i]) for i in range(3)]
                hi = [max(hi[i], b[6 * k + 3 + i]) for i in range(3)]
            g += 1
    r["camera_box"] = [list(c) for c in view.camera.bbox]
    r["shown_box"] = [lo, hi]
    view.explode_to(1.0, animate=False)
    r["exploded_groups"] = view.explosion.groups
    r["exploded_box"] = [list(c) for c in view.camera.bbox] == [list(c) for c in view.explosion.bbox1]
    view.explode_to(0.0, animate=False)
    view.set_looks(None, [True] * n)
    blank = rgb(view.grabFramebuffer())
    r["all_hidden_blank"] = all(p == blank[0] for p in blank)
    r["all_hidden_box"] = [list(c) for c in view.camera.bbox] == [list(c) for c in view.scene.bbox]
    r["all_hidden_ids"] = sum(1 for i in view.ids_drawn() if i is not None)
    view.set_looks(None, None)
    r["back_again"] = rgb(view.grabFramebuffer()) == plain
    # The sort: each one's far side at the far end of its box along the line of sight and its
    # near side at the near end, farthest first; again, the other way, when the camera turns.
    view.set_looks(opacity, None)
    view.grabFramebuffer()
    order = list(view.renderer._order)
    back = view.camera.back

    def ends(order):
        out = []
        for m, k, side in order:
            mesh = view.renderer.meshes[m]
            c = sum(back[i] * mesh.centres[3 * k + i] for i in range(3))
            h = sum(abs(back[i]) * mesh.halves[3 * k + i] for i in range(3))
            out.append(c - h if side == view3d.FAR_SIDE else c + h)
        return out

    depth = ends(order)
    r["order_far_first"] = len(order) == 4 and depth == sorted(depth)
    r["order_far_then_near"] = all(
        [s for m, k, s in order if (m, k) == item] == [view3d.FAR_SIDE, view3d.NEAR_SIDE]
        for item in {(m, k) for m, k, _s in order}
    )
    view.camera.turn_model(180.0, 0.0)  # round the screen's vertical axis: seen from behind
    view.grabFramebuffer()
    turned = [(m, k) for m, k, _s in view.renderer._order]
    r["order_turned"] = turned == [(m, k) for m, k, _s in reversed(order)]
    out[str(instanced)] = r

    # The ranking of a transparent instance in the id pass: a closed cube (a mesh, not a box
    # for a missing one) as a housing, one inside it and one far behind it.
    cubes = [((-1, -1, -1), (1, 1, 1)), ((-0.2, -0.2, -0.2), (0.2, 0.2, 0.2))]
    cubes.append(((0.5, -0.2, -3), (0.9, 0.2, -2)))  # behind the housing, outside its box
    mesh = _box_mesh()
    faces = mesh.indices[: 4 * 36]  # the cube's triangles, without its edges: a mesh, not a box
    mesh = mesh3d.MeshBuffers(mesh.positions, mesh.normals, faces, mesh.n_vertices, 12, mesh.bbox)
    mats = [cube(lo, hi) for lo, hi in cubes]
    cols = array("f", [0.8, 0.3, 0.2, 0.2, 0.6, 0.9, 0.3, 0.8, 0.3]).tobytes()
    bounds = [view3d.instance_bounds(mesh.bbox, b"".join(mats))]
    names = [["housing-1", "inner-1", "far-1"]]
    test = Scene([mesh], [b"".join(mats)], [cols], ((-1, -1, -3), (1, 1.1, 1)), ids=names, bounds=bounds)
    v = view3d.ModelView()
    v.resize(400, 400)
    v.show()
    v.set_scene(test)
    v.set_view("front")
    app.processEvents()
    w, h = v.width(), v.height()

    def at(p):
        nx, ny, _ = v.camera.project(p)
        return (nx + 1) * w / 2, (1 - ny) * h / 2

    spots = {"inner": (0, 0, 1), "over_far": (0.7, 0, 1), "housing": (-0.7, -0.7, 1)}

    def picks():  # where the camera shows each spot now: it fits what is shown
        return {k: v.instance_at(*at(p), 0) for k, p in spots.items()}

    q = {"opaque": picks()}
    v.set_looks([0.3, 1.0, 1.0], None)
    q["transparent"] = picks()
    v.set_looks(None, [True, False, False])
    q["hidden"] = picks()
    # A transparent slab lying on a housing's face, both turned to no axis, so that the two
    # faces' depths round differently: from every side that sees the slab's top, it is one
    # colour all over, never speckled with the face it lies on (without the depth offset
    # toward the eye, up to 93 apart here).
    a, c, t = math.radians(33), math.cos(math.radians(33)), 1 - math.cos(math.radians(33))
    x, y, z = (k / math.sqrt(14) for k in (1, 2, 3))
    sn = math.sin(a)
    R = [[t * x * x + c, t * x * y - sn * z, t * x * z + sn * y],
         [t * x * y + sn * z, t * y * y + c, t * y * z - sn * x],
         [t * x * z - sn * y, t * y * z + sn * x, t * z * z + c]]

    def turned(lo, hi):
        size = [hi[i] - lo[i] for i in range(3)]
        cols = [[R[r][k] * size[k] for r in range(3)] for k in range(3)]
        move = [sum(R[r][k] * lo[k] for k in range(3)) for r in range(3)]
        return array("f", [*cols[0], 0, *cols[1], 0, *cols[2], 0, *move, 1]).tobytes()

    def on_turned(p):
        return [sum(R[r][k] * p[k] for k in range(3)) for r in range(3)]

    pair = turned((-1, -1, -1), (1, 1, 1)) + turned((-0.9, 1.0, -0.9), (0.6, 1.1, 0.7))
    two = Scene([mesh], [pair], [cols[:24]], ((-2, -2, -2), (2, 2, 2)), ids=[["housing-1", "slab-1"]],
                bounds=[view3d.instance_bounds(mesh.bbox, pair)])
    s2 = view3d.ModelView()
    s2.resize(400, 400)
    s2.show()
    s2.set_scene(two)
    app.processEvents()
    s2.set_looks([1.0, 0.5], None)
    spread = []
    for _turn in range(12):
        s2.camera.turn_model(30.0, 7.0)
        top = on_turned((0, 1, 0))
        if sum(top[i] * s2.camera.back[i] for i in range(3)) < 0.4:
            continue  # the slab's top seen edge on or from below
        img = rgb(s2.grabFramebuffer())
        face = []
        for i in range(2, 9):
            for j in range(2, 9):
                nx, ny, _ = s2.camera.project(on_turned((-0.9 + 0.15 * i, 1.1, -0.9 + 0.16 * j)))
                px, py = int((nx + 1) * s2.width() / 2), int((1 - ny) * s2.height() / 2)
                face.append(img[py * s2.width() + px])
        spread.append(max(dist(p, face[0]) for p in face))
    q["slab_spread"] = spread
    out["rank " + str(instanced)] = q
print(json.dumps({k: v for k, v in out.items() if k != "image"}, default=str))
"""


@needs_qt
def test_transparent_and_hidden_instances_on_the_display():
    """On the real display, instanced and one by one: o15's parts made 75 percent
    transparent change every pixel of theirs toward what is behind them and no other, and
    are still picked where nothing is behind them; hidden, nothing of them is drawn or
    picked and the camera fits the rest; everything hidden draws nothing and fits the
    whole; shown again, the first picture comes back. The transparent ones are drawn
    farthest first, and in the other order once the view turns round. A transparent
    housing lets a click through to a part inside its box but not to one behind it, and
    a transparent slab lying on a face is one colour all over, never speckled."""
    before = _state(FIXTURES)
    out = run_gl(_GL_LOOKS, str(fixture_path(O16)), str(FIXTURES))
    for instanced in ("True", "False"):
        r = out[instanced]
        assert r["rank_far"] and r["own"] > 500
        assert r["changed"] > 0.99 and r["toward_behind"] > 0.99 and r["others_same"] == 1.0, r
        assert r["picked_alone"] > 0.99 and r["sorted"] == 2 and r["camera_box_same"]
        assert r["hidden_picked"] == 0 and r["hidden_found"] == [None, None]
        flat = [v for c in r["camera_box"] for v in c]
        assert flat == pytest.approx([v for c in r["shown_box"] for v in c], abs=1e-6)
        assert r["exploded_groups"] == 10 and r["exploded_box"]  # 11 top-level components, o15 hidden
        assert r["all_hidden_blank"] and r["all_hidden_box"] and r["all_hidden_ids"] == 0
        assert r["back_again"] and r["order_far_first"] and r["order_far_then_near"] and r["order_turned"]
        q = out["rank " + instanced]
        assert q["opaque"] == {"inner": 0, "over_far": 0, "housing": 0}
        assert q["transparent"] == {"inner": 1, "over_far": 0, "housing": 0}  # through it, not past it
        assert q["hidden"] == {"inner": 1, "over_far": 2, "housing": None}
        assert len(q["slab_spread"]) >= 3 and max(q["slab_spread"]) <= 3, q
    assert _state(FIXTURES) == before


_GL_BLEND = """
from array import array
from solidseas_app.viewer import mesh3d
from solidseas_app.viewer.view3d import BOX_EDGE, BOX_MESH, FAR_SIDE, NEAR_SIDE, ModelView, Scene, _box_mesh
from solidseas_app.viewer.explode import instance_bounds


def cube(lo, hi):
    sx, sy, sz = (hi[i] - lo[i] for i in range(3))
    return array("f", [sx, 0, 0, 0, 0, sy, 0, 0, 0, 0, sz, 0, lo[0], lo[1], lo[2], 1]).tobytes()


def rgb(img, x, y):
    c = img.pixelColor(x, y)
    return (c.red(), c.green(), c.blue())


def dist(a, b):
    return sum(abs(p - q) for p, q in zip(a, b))


mesh = _box_mesh()
faces = mesh.indices[: 4 * 36]  # the cube's triangles, without its edges: a mesh, not a box
mesh = mesh3d.MeshBuffers(mesh.positions, mesh.normals, faces, mesh.n_vertices, 12, mesh.bbox)
unit = ((0, 0, 0), (1, 1, 1))
out = {"gl": True}
for instanced in (True, False):
    view3d.Renderer.allow_instancing = instanced
    r = {}
    # A plate in front of a box drawn for a missing mesh, turned so that the box's edges cross
    # the plate: under the plate made a little transparent, they show through it, blended,
    # not drawn over it.
    plate, box = cube((-1, -1, 0.5), (1, 1, 1)), cube((-0.5, -0.5, -1), (0.5, 0.5, 0))
    scene = Scene([mesh, BOX_MESH], [plate, box],
                  [array("f", [0.8, 0.3, 0.2]).tobytes(), array("f", [0.72, 0.75, 0.78]).tobytes()],
                  ((-1, -1, -1), (1, 1, 1)), ids=[["plate-1"], ["box-1"]],
                  bounds=[instance_bounds(mesh.bbox, plate), instance_bounds(unit, box)], box_mesh=1)
    v = ModelView()
    v.resize(300, 300)
    v.show()
    v.set_scene(scene)
    v.set_view("front")
    v.camera.turn_model(20.0, 15.0)
    app.processEvents()
    edge = BOX_EDGE[False]
    edge = (edge.red(), edge.green(), edge.blue())
    v.set_looks(None, [True, False])
    alone = v.grabFramebuffer()
    r["boxes_sorted"] = v.renderer.sorted_items  # boxes alone: drawn without a sort
    v.set_looks(None, None)
    opaque = v.grabFramebuffer()
    def on_plate(x, y):  # the plate's red, where it lies over the box
        c = rgb(opaque, x, y)
        return c[0] > 150 and c[1] < 120

    pixels = [(x, y) for y in range(300) for x in range(300)]
    under = [(x, y) for x, y in pixels if dist(rgb(alone, x, y), edge) <= 6 and on_plate(x, y)]
    v.set_looks([0.9, 1.0], None)
    seen = v.grabFramebuffer()
    r["edge_pixels"] = len(under)
    r["edge_on_top"] = sum(1 for x, y in under if dist(rgb(seen, x, y), edge) <= 6)
    near = sum(1 for x, y in under if dist(rgb(seen, x, y), rgb(opaque, x, y)) < 60)
    r["near_plate"] = near / max(len(under), 1)
    r["sorted_with_box"] = v.renderer.sorted_items  # the plate and the box
    v.set_looks([0.9, 1.0], [False, True])
    v.grabFramebuffer()
    r["sorted_box_hidden"] = v.renderer.sorted_items
    # The box made 90 percent transparent fades its edges too, alone (no sort) and sorted.
    lines = [(x, y) for x, y in pixels if dist(rgb(alone, x, y), edge) <= 6]
    v.set_looks([1.0, 0.1], [True, False])
    faint = v.grabFramebuffer()
    r["edge_lines"] = len(lines)
    r["faint_edges_alone"] = sum(1 for x, y in lines if dist(rgb(faint, x, y), edge) <= 60)
    v.set_looks([0.9, 0.1], None)
    faint = v.grabFramebuffer()
    r["faint_edges_sorted"] = sum(1 for x, y in under if dist(rgb(faint, x, y), edge) <= 60)
    v.close()

    # A part inside a housing, both half transparent: from the front and from behind, the
    # housing's far side, the part's far side, its near side, then the housing's near side,
    # and the part seen through both walls the same colour either way; turned round in
    # steps, the picture never jumps.
    pm = cube((-1, -1, -1), (1, 1, 1)) + cube((-0.3, -0.3, 0.1), (0.3, 0.3, 0.7))
    colours = array("f", [0.8, 0.3, 0.2, 0.2, 0.6, 0.9]).tobytes()
    scene = Scene([mesh], [pm], [colours], ((-1, -1, -1), (1, 1, 1)),
                  ids=[["housing-1", "inner-1"]], bounds=[instance_bounds(mesh.bbox, pm)])
    v = ModelView()
    v.resize(300, 300)
    v.show()
    v.set_scene(scene)
    v.set_view("front")
    app.processEvents()
    v.set_looks([0.5, 0.5], None)
    colours, orders, steps = [], [], []
    for step in range(0, 181, 2):
        if step:
            v.camera.turn_model(2.0, 0.0)
        img = v.grabFramebuffer()
        nx, ny, _ = v.camera.project((0.0, 0.0, 0.4))
        colours.append(rgb(img, int((nx + 1) * 150), int((1 - ny) * 150)))
        if step in (0, 180):
            orders.append([[k, "far" if side == FAR_SIDE else "near"] for _m, k, side in v.renderer._order])
    r["nested_orders"] = orders
    r["nested_colours"] = [colours[0], colours[-1]]
    r["nested_largest_step"] = max(dist(a, b) for a, b in zip(colours, colours[1:]))
    v.close()
    out[str(instanced)] = r
print(json.dumps(out))
"""


@needs_qt
def test_blended_items_are_drawn_in_depth_order_on_the_display():
    """On the real display, both drawing paths: a box's edges behind a part made a little
    transparent show through it, blended, instead of being drawn over it, and a box made
    nearly clear fades its edges as well as its faces; a part inside a
    housing, both transparent, is drawn between the housing's far and near sides from
    either side, so it looks the same from the front and from behind and the picture never
    jumps as the view turns; boxes alone are drawn without a sort, and the sort covers the
    transparent parts and the boxes shown."""
    out = run_gl(_GL_BLEND)
    for instanced in ("True", "False"):
        r = out[instanced]
        assert r["edge_pixels"] > 100 and r["edge_on_top"] == 0 and r["near_plate"] > 0.99, r
        assert (r["boxes_sorted"], r["sorted_with_box"], r["sorted_box_hidden"]) == (0, 2, 1), r
        assert r["edge_lines"] > 200 and r["faint_edges_alone"] == 0 == r["faint_edges_sorted"], r
        inside = [[0, "far"], [1, "far"], [1, "near"], [0, "near"]]
        assert r["nested_orders"] == [inside, inside], r
        front, back = r["nested_colours"]
        assert sum(abs(a - b) for a, b in zip(front, back, strict=True)) <= 6, r
        assert r["nested_largest_step"] <= 60, r


_GL_SWITCH = """
from solidseas_app.viewer import mesh3d
scene = mesh3d.read_assembly_scene(sys.argv[1], sys.argv[2], sys.argv[2], 1_000_000)["data"]
ids = [i for m in scene.instance_ids for i in m]
out = {"gl": True}
for instanced in (True, False):
    view3d.Renderer.allow_instancing = instanced
    view = view3d.ModelView()
    view.resize(400, 300)
    view.set_assembly(scene)
    view.explode_to(1.0, animate=False)
    top = view.grabFramebuffer()
    view.set_explode_choices({"o15_sub_asm-1": True})
    r = {"groups": view.explosion.groups, "box": [list(c) for c in view.camera.bbox]}
    r["box1"] = [list(c) for c in view.explosion.bbox1]
    on = view.grabFramebuffer()
    r["offsets"] = [[v for k, v in enumerate(m.offsets) if k % 4 != 3] for m in view.renderer.meshes]
    r["changed"] = on != top
    view.set_explode_level("parts")
    view.set_explode_choices({"o15_sub_asm-1": False})
    r["parts_off_groups"] = view.explosion.groups
    r["parts_off_same_as_top"] = view.grabFramebuffer() == top
    r["error"] = view.error
    out[str(instanced)] = r
print(json.dumps(out))
"""


@needs_qt
def test_the_explode_switch_moves_the_view_on_the_display():
    """Switched on at Top-level, o15's parts take the offsets Every part gives them and the
    camera follows the new box; switched off at Every part, the picture is Top-level's."""
    out = run_gl(_GL_SWITCH, str(fixture_path(O16)), str(FIXTURES))
    scene = _scene()
    parts = explode.explode(scene.instance_ids, scene.bounds, explode.PARTS)
    for r in (out["True"], out["False"]):
        assert r["error"] is None and r["groups"] == 12 and r["changed"]
        flat = [v for m in r["offsets"] for v in m]
        assert flat == pytest.approx([v for m in parts.offsets for v in m], abs=1e-9)
        assert r["box"] == r["box1"]
        assert r["parts_off_groups"] == 11 and r["parts_off_same_as_top"]


# --------------------------------------------------------------------------- the self-test
@needs_qt
def test_the_self_test_checks_transparency_hide_isolate_and_the_switch(tmp_path):
    shots = tmp_path / "shots"
    before = _state(FIXTURES)
    args = ["--self-test", str(FIXTURES), "--screenshot-dir", str(shots), "--select", O16, "--3d", "--boxes"]
    args += ["--explode", "50", "--pick", INNER[1]]
    args += ["--transparent", SUB, "--transparent", "o02_boxA-1,25", "--transparent", "o02_boxA-1,0"]
    args += ["--explode-sub", f"{SUB},on"]
    args += ["--explode-sub", f"{SUB},off", "--hide", "o06_boxA_props_mat_cfg-1", "--isolate", SUB]
    args += ["--select", O08, "--3d", "--transparent", "o02_boxA-2,90", "--isolate", "o02_boxA-1"]
    report = run_self_test(args, shots, appdata=tmp_path / "Roaming")
    o16, o08 = report["documents"]
    got = [(x["action"], x["name"], x.get("value"), "failed" in x) for x in o16["looks"]]
    assert got == [
        ("transparent", SUB, None, False),
        ("transparent", "o02_boxA-1", 25, False),
        ("transparent", "o02_boxA-1", 0, False),
        ("explode-sub", SUB, "on", False),
        ("explode-sub", SUB, "off", False),
        ("hide", "o06_boxA_props_mat_cfg-1", None, False),
        ("isolate", SUB, None, False),
    ]
    first = o16["looks"][0]
    assert first["percent"] == 75 and first["changed"] > 0.9 and first["others_same"] >= 0.99
    assert o16["looks"][2]["same"] >= 0.99  # opaque again: drawn as it is drawn opaque
    assert o16["looks"][3]["groups"] == 2 == o16["looks"][3]["offsets"] and o16["looks"][4]["offsets"] == 1
    assert o16["looks_reset"]["differ"] == 0 and o08["looks_reset"]["differ"] == 0
    assert [x["action"] for x in o08["looks"]] == ["transparent", "isolate"]
    names = [Path(p).name for p in report["screenshots"]]
    for stem in (
        f"transparent_{SUB}",
        "transparent_o02_boxA-1_25",
        f"explode-sub_{SUB}_on",
        f"isolate_{SUB}",
    ):
        assert any(n.endswith(f"o16_asm_features_{stem}.png") for n in names), stem
    for stem in ("looks_components", "looks_reset"):
        assert any(n.endswith(f"o16_asm_features_{stem}.png") for n in names), stem
    assert _state(FIXTURES) == before


@needs_qt
def test_the_self_test_look_options_are_checked(app, tmp_path, monkeypatch):
    from solidseas_app.viewer import app as viewer_app

    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    base = ["--self-test", str(FIXTURES), "--screenshot-dir", str(tmp_path / "s"), "--select", O16]
    parsed = viewer_app.build_parser().parse_args(
        [
            *base,
            "--3d",
            "--transparent",
            SUB,
            "--hide",
            "a-1",
            "--transparent",
            "b,c-1,50",
            "--explode-sub",
            "s-1,off",
        ]
    )
    assert parsed.looks == {
        O16: [
            ("transparent", SUB, None),
            ("hide", "a-1", None),
            ("transparent", "b,c-1", 50),
            ("explode-sub", "s-1", "off"),
        ]
    }
    for bad in (
        ["--transparent", "a-1,95"],
        ["--explode-sub", "s-1"],
        ["--explode-sub", "s-1,maybe"],
        ["--hide", " "],
    ):
        assert viewer_app.main([*base, "--3d", *bad]) == viewer_app.EXIT_USAGE, bad
    assert viewer_app.main([*base, "--isolate", SUB]) == viewer_app.EXIT_USAGE  # needs --3d
    assert viewer_app.main(["--hide", SUB]) == viewer_app.EXIT_USAGE  # belongs to the self-test
    report = ["--self-test", str(FIXTURES), "--report", str(tmp_path / "r.json"), "--select-all", "--3d"]
    assert viewer_app.main([*report, "--isolate", SUB]) == viewer_app.EXIT_USAGE
    assert not (tmp_path / "s").exists()
    assert math.isfinite(appearance.Look(transparency=90).opacity)


@needs_qt
def test_the_self_test_refuses_to_check_the_explode_switch_of_a_part(app):
    """``--explode-sub`` on a part has nothing under it to explode: the check fails at once,
    saying so, before it explodes the view or counts anything."""
    from solidseas_app.viewer.preview import PreviewPane
    from solidseas_app.viewer.selftest import LookCheck

    pane = PreviewPane()
    pane.instance_ids = ["sub-1/a-1", "sub-1/b-1", "p-1"]
    pane._no_boxes()
    pane.doc_type = "assembly"
    rec = LookCheck(pane, None).run("explode-sub", "p-1", "off")
    assert rec["failed"] == "it is not a sub-assembly: the view draws no part under it to explode"
    assert pane.explode_value == 0 and pane.explode_choices == {}


@needs_qt
def test_the_components_tab_gives_the_view_each_sub_assemblys_file():
    """Every level of the tree, not only the rows shown; a part is no sub-assembly, and an
    assembly's file is one even with no children read (its parts may come from its own
    file)."""
    from solidseas_app.viewer.details import component_files

    pin = {"id": "frame-1/panel-1/pin-1", "file": "k3"}
    c = {
        "files": [
            {"key": "k1", "file_name": "frame.SLDASM", "doc_type": "assembly"},
            {"key": "k2", "file_name": "panel.SLDASM", "doc_type": "assembly"},
            {"key": "k3", "file_name": "pin.SLDPRT", "doc_type": "part"},
            {"key": "k4", "file_name": None, "stored_path": "board.SLDASM", "doc_type": "assembly"},
        ],
        "children": [
            {
                "id": "frame-1",
                "file": "k1",
                "children": [
                    {"id": "frame-1/panel-1", "file": "k2", "children": [pin]},
                    {"id": "frame-1/pin-2", "file": "k3", "children": []},
                ],
            },
            {"id": "board-1", "file": "k4", "children": []},
            {"name": "pin-3", "file": "k3"},
        ],
    }
    files, names = component_files(c)
    assert files == {"frame-1": "k1", "frame-1/panel-1": "k2", "board-1": "k4"}
    assert names == {"k1": "frame.SLDASM", "k2": "panel.SLDASM", "k3": "pin.SLDPRT", "k4": "board.SLDASM"}


@needs_qt
def test_play_explodes_the_assembly_then_collapses_it(viewer):
    w, pane, view = _assembly_3d(viewer)
    assert pane.play_button.isEnabled() and pane.play_button.text() == "Play"
    pane.play_button.click()
    assert pane.explode_slider.value() == 100 and pane.play_button.text() == "Stop"
    assert view.explode_calls[-1][0] == 1.0
    pane._play_next()  # the explode has finished and been held
    assert pane.explode_slider.value() == 0 and view.explode_calls[-1][0] == 0.0
    pane._play_next()
    assert pane.play_button.text() == "Play" and not pane._play_timer.isActive()
    pane.play_button.click()
    pane.play_button.click()  # Stop while it explodes: it stays where it was heading
    assert pane.play_button.text() == "Play" and pane.explode_slider.value() == 100
