"""The document list's quick filter: the row of type buttons under the name filter
(``solidseas_app.viewer.quickfilter``) and the type table it reads
(``solidseas_app.viewer.filetypes``).

The table and the type of each listing entry import no Qt and are tested
everywhere. The window tests open copies of the fixtures offscreen; the formats
SolidSeas does not list yet (STL, 3MF, glTF...) are rows added to the model as the
listing will report them, with their format in a ``model`` object.
"""

import json
import os
import shutil
import time
from pathlib import Path

import pytest

from solidseas import model
from solidseas_app.viewer import filetypes
from support import ASSEMBLY, fixture_path

try:
    import PySide6.QtWidgets  # noqa: F401
except ImportError:  # the window tests need the [app] extra
    HAVE_QT = False
else:
    HAVE_QT = True

needs_qt = pytest.mark.skipif(not HAVE_QT, reason="PySide6 is not installed: the viewer window is not tested")


def _entry(path: str, status: str = "ok", **fields) -> dict:
    entry = model.listing_entry(path, "file", status)
    entry.update(fields)
    return entry


# --------------------------------------------------------------------------- the table, no Qt
def test_a_document_has_the_type_the_listing_reports():
    t = filetypes.file_type
    assert t(_entry("a.SLDPRT", format="modern", doc_type="part")) == "sldprt"
    assert t(_entry("sub/b.sldasm", format="ole", doc_type="assembly")) == "sldasm"
    assert t(_entry("c.SLDDRW", format="modern", doc_type="drawing")) == "slddrw"
    # What the file says wins over its name, as in the Type column.
    assert t(_entry("misnamed.SLDPRT", format="modern", doc_type="assembly")) == "sldasm"
    # Not read (a lock file, a file that could not be read, a link): the extension says.
    assert t(_entry("~$a.SLDPRT", "skipped", reason="lock_file")) == "sldprt"
    assert t(_entry("bad.SLDASM", "error", error={"code": "truncated"})) == "sldasm"
    # A STEP file wearing a SOLIDWORKS extension is a STEP file.
    assert t(_entry("really_step.SLDPRT", "not_solidworks", detected="step")) == "step"
    assert t(model.listing_entry("sub", "folder", "ok")) is None


def test_other_formats_take_their_type_from_name_and_content():
    t = filetypes.file_type

    def read(path: str, fmt: str, doc_type: str | None = "part") -> dict:
        return _entry(path, doc_type=doc_type, model={"format": fmt})

    assert t(read("a.stp", "step", "assembly")) == "step" and t(read("a.p21", "step")) == "step"
    assert t(read("a.x_t", "parasolid")) == "x_t" and t(read("a.X_B", "parasolid")) == "x_b"
    assert t(read("a.xmt_bin", "parasolid")) == "x_b"
    assert t(read("a.gltf", "gltf")) == "gltf" and t(read("a.glb", "gltf")) == "glb"
    assert t(read("a.AD_PRT", "alibre")) == "ad_prt" and t(read("a.ad_smp", "alibre")) == "ad_prt"
    assert t(read("a.AD_ASM", "alibre", "assembly")) == "ad_asm"
    for ext in ("stl", "3mf", "obj", "ply", "amf"):
        assert t(read(f"a.{ext.upper()}", ext)) == ext
    # The content wins when the name says another format.
    assert t(read("printed.stl", "3mf")) == "3mf"
    assert t(read("box.SLDPRT", "step")) == "step"
    # OFF and ACIS have rows of their own (ACIS one for each of its two extensions).
    assert t(read("mesh.off", "off")) == "off" and t(read("body.sab", "acis")) == "sab"
    assert t(_entry("body.SAT", "unsupported", model={"format": "acis", "readable": False})) == "sat"
    # A format SolidSeas lists but cannot read is filed by its name, its kind told by it.
    for name, fmt, key in (
        ("bracket.ipt", "inventor", "ipt"),
        ("frame.IAM", "inventor", "iam"),
        ("plate.psm", "solid_edge", "psm"),
        ("scene.wrl", "vrml", "vrml"),
        ("scene.VRML", "vrml", "vrml"),
        ("sheet.ad_drw", "alibre_drawing", "ad_drw"),
    ):
        entry = _entry(name, "unsupported", detected=fmt, model={"format": fmt, "readable": False})
        assert t(entry) == key, name
    # A type no row knows is its extension, shown on a grey badge.
    assert t(_entry("odd.catpart", "error")) == "catpart"
    # One row with several extensions is one type: .igs and .iges are both IGES.
    for name in ("part.igs", "part.IGES"):
        entry = _entry(name, "unsupported", detected="iges", model={"format": "iges", "readable": False})
        assert t(entry) == "iges"
    assert t(_entry("a.stl", "error", error={"code": "truncated"})) == "stl"  # not read: its name
    assert t(_entry("no_extension", "error")) is None
    assert t(_entry("odd.name with space", "error")) is None


def test_the_table_is_complete_and_ordered():
    keys = [ft.key for ft in filetypes.FILE_TYPES]
    assert keys[:3] == ["sldprt", "sldasm", "slddrw"]
    assert keys == [
        "sldprt",
        "sldasm",
        "slddrw",
        "step",
        "stl",
        "3mf",
        "x_t",
        "x_b",
        "sab",
        "sat",
        "obj",
        "ply",
        "off",
        "gltf",
        "glb",
        "amf",
        "ad_prt",
        "ad_asm",
        "iges",
        "brep",
        "ad_drw",
        "ad_pkg",
        "ipt",
        "iam",
        "par",
        "psm",
        "asm",
        "f3d",
        "f3z",
        "eprt",
        "easm",
        "edrw",
        "3dxml",
        "vrml",
    ]
    extensions = [e for ft in filetypes.FILE_TYPES for e in ft.extensions]
    assert len(extensions) == len(set(extensions)) and all(e == e.lower() and e[0] == "." for e in extensions)
    for ft in filetypes.FILE_TYPES:
        assert ft.glyph in filetypes.GLYPHS and filetypes.parse_key(ft.key) == ft.key
        assert ft.glyph != "badge" or 1 <= len(ft.letters) <= filetypes.BADGE_LETTERS
        assert ft.color.startswith("#") and len(ft.color) == 7
    assert filetypes.TYPES["sldprt"].title == "SOLIDWORKS Part (SLDPRT)"
    assert filetypes.TYPES["step"].title == "STEP (STEP, STP, P21)"
    assert filetypes.TYPES["iges"].title == "IGES (IGS, IGES)"
    assert filetypes.TYPES["vrml"].title == "VRML (WRL, VRML)"
    other = filetypes.info("catpart")
    assert (other.title, other.glyph, other.letters, other.color) == (
        "CATPART file (CATPART)",
        "badge",
        "CATPAR",
        filetypes.GREY,
    )
    # A grey badge shows the whole extension up to six letters, then its first six.
    assert [filetypes.info(k).letters for k in ("3dxml", "ad_drw", "sldlfp", "catproduct")] == [
        "3DXML",
        "AD_DRW",
        "SLDLFP",
        "CATPRO",
    ]
    assert filetypes.info("catproduct").title == "CATPRODUCT file (CATPRODUCT)"
    # Known types in the table's order, then the others alphabetically.
    keys = ["off", "stl", "sat", "sldasm", "iges", "step", "sldprt", "stl", "zz", "aa"]
    assert filetypes.ordered(keys) == [
        "sldprt",
        "sldasm",
        "step",
        "stl",
        "sat",
        "off",
        "iges",
        "aa",
        "zz",
    ]


def test_every_format_a_listing_reports_has_a_button_named_as_its_type():
    """Each format of the registry a listing can report has rows here, and only rows
    whose names begin with the registry's name for it (the Type column's): readable ones
    in their family's colour, the others grey as the list draws their files. Every
    extension of the format is one row's."""
    from solidseas.formats import registry

    colours = {"mesh": filetypes.TEAL, "exchange": filetypes.PURPLE, "native": filetypes.BROWN}
    for spec in registry.FORMATS.values():
        if spec.id == registry.SOLIDWORKS:
            continue
        listed = [e for e in spec.extensions if e not in spec.needs_signature or spec.signature]
        rows = [ft for ft in filetypes.FILE_TYPES if spec.id in ft.formats]
        if not listed:  # NX: other programs use .prt, so it is never listed
            assert not rows, spec.id
            continue
        assert sorted(e for ft in rows for e in ft.extensions) == sorted(spec.extensions), spec.id
        for ft in rows:
            assert ft.name.startswith(spec.name), (ft.name, spec.name)
            read = registry.readable(spec.id) and not set(ft.extensions) <= filetypes.NOT_READ
            want = colours[spec.family] if read else filetypes.GREY
            assert ft.color == want, ft.key


def test_an_extension_its_reader_refuses_has_a_grey_button():
    """ACIS text files are listed as not read (the ACIS reader's rule sat_text), so their
    button is grey, as the list draws a file it could not read, and is not among the
    formats SolidSeas reads; when the reader takes them, this fails, to give the button
    ACIS's colour again."""
    from solidseas.errors import FormatNotSupportedError
    from solidseas.formats import open_model

    assert filetypes.NOT_READ == {".sat"} and filetypes.TYPES["sat"].color == filetypes.GREY
    assert filetypes.TYPES["sab"].color == filetypes.PURPLE
    text = b"700 0 1 0\n@7 SolidSeas 9 ACIS test 24 Thu Jan 01 00:00:00 2026\n10 1e-06 1e-10\n"
    with pytest.raises(FormatNotSupportedError) as err:
        open_model(text, name="part.sat")
    assert err.value.detail == {"rule": "sat_text", "value": "acis"}


def test_types_are_read_from_what_a_person_types_and_from_the_settings_file():
    assert [filetypes.parse_key(t) for t in ("SLDPRT", ".STP", "step", "xmt_txt", " glb ", "ad_smp")] == [
        "sldprt",
        "step",
        "step",
        "x_t",
        "glb",
        "ad_prt",
    ]
    assert filetypes.parse_key("igs") == filetypes.parse_key(".IGES") == "iges"
    assert filetypes.parse_key("sat") == "sat" and filetypes.parse_key(".wrl") == "vrml"
    assert filetypes.parse_key("catpart") == "catpart"  # a type without a row: its extension
    assert filetypes.parse_key("not a type") is None and filetypes.parse_key("") is None
    assert filetypes.format_keys({"step", "sldprt"}) == "sldprt,step"
    assert filetypes.parse_keys("step, SLDPRT") == ("sldprt", "step")
    for bad in ("", None, "@Variant(\\0\\0)", "sldprt,<b>", ",".join(["a"] * 40), "x" * 1000):
        assert filetypes.parse_keys(bad) == ()


# --------------------------------------------------------------------------- the window, offscreen
@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from solidseas_app.viewer.app import use_system_fonts

    use_system_fonts()
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _wait(app, condition, timeout: float = 60.0) -> None:
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            raise AssertionError("timed out waiting for the viewer")
        app.processEvents()
        time.sleep(0.005)


@pytest.fixture
def window(app):
    from solidseas_app.viewer.window import MainWindow

    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    yield w
    assert w.shutdown()
    w.close()
    w.deleteLater()
    app.processEvents()


def _open(app, w, folder: Path) -> None:
    w.open_folder(str(folder))
    _wait(app, lambda: w.listing_info is not None and w._listing is None)


@pytest.fixture
def mixed(tmp_path: Path) -> Path:
    """Two parts, an assembly, a drawing, a STEP file wearing a part's extension and a
    subfolder with a sub-assembly and a part."""
    folder = tmp_path / "mixed"
    (folder / "sub").mkdir(parents=True)
    for name in ("o02_boxA.SLDPRT", "o07_boxB_h31.SLDPRT", ASSEMBLY, "o18_drw_boxA.SLDDRW"):
        shutil.copy2(fixture_path(name), folder / name)
    shutil.copy2(fixture_path("o02_boxA.step"), folder / "boxA_as_step.SLDPRT")
    shutil.copy2(fixture_path("o15_sub_asm.SLDASM"), folder / "sub" / "o15_sub_asm.SLDASM")
    shutil.copy2(fixture_path("o03_boxA_again.SLDPRT"), folder / "sub" / "o03_boxA_again.SLDPRT")
    return folder


def _shown(w) -> set[str]:
    p = w.proxy
    return {w.model.rows[p.mapToSource(p.index(i, 0)).row()].entry["path"] for i in range(p.rowCount())}


def _add_formats(w, *paths_and_formats: tuple[str, str]) -> None:
    """Rows of other formats, as the listing reports them once their readers are in."""
    w.model.append(
        [(_entry(path, doc_type="part", model={"format": fmt}), None) for path, fmt in paths_and_formats]
    )


@needs_qt
def test_the_row_offers_the_types_of_the_folder_in_order(app, window, mixed):
    w = window
    bar = w.quick
    assert not bar.isVisible()  # no folder yet
    _open(app, w, mixed)
    assert bar.isVisible() and bar.keys() == ["sldprt", "sldasm", "slddrw", "step"]
    assert bar.all_button.isChecked() and not bar.selected() and len(_shown(w)) == 7
    # It stands right under the name filter, above the list.
    assert bar.parentWidget() is w.filter.parentWidget()
    assert (
        w.filter.geometry().bottom()
        < bar.geometry().top()
        < bar.geometry().bottom()
        < w.list_stack.geometry().top()
    )
    _add_formats(w, ("print.3mf", "3mf"), ("mesh.off", "off"), ("plate.STL", "stl"), ("arm.x_b", "parasolid"))
    assert bar.keys() == ["sldprt", "sldasm", "slddrw", "step", "stl", "3mf", "x_b", "off"]
    assert bar.buttons["off"].file_type.letters == "OFF"
    _add_formats(w, ("a.igs", "iges"), ("b.IGES", "iges"), ("c.3dxml", "3dxml"))
    assert bar.keys()[-3:] == ["off", "iges", "3dxml"] and bar.count("iges") == 2
    assert bar.buttons["3dxml"].file_type.letters == "3DXML"
    # The Type column calls a STEP file with a part's name STEP, as the quick filter files it.
    from solidseas_app.viewer.documents import TYPE

    step = next(r for r in w.model.rows if r.name == "boxA_as_step.SLDPRT")
    assert step.file_type == "step" and step.display[TYPE] == "STEP"
    assert next(r for r in w.model.rows if r.name == "o02_boxA.SLDPRT").display[TYPE] == "Part"


@needs_qt
def test_buttons_show_the_union_of_their_types_and_narrow_the_other_filters(app, window, mixed):
    w = window
    bar = w.quick
    _open(app, w, mixed)
    bar.buttons["sldasm"].click()
    assert _shown(w) == {ASSEMBLY, "sub/o15_sub_asm.SLDASM"} and bar.selected() == {"sldasm"}
    assert not bar.all_button.isChecked() and bar.buttons["sldasm"].isChecked()
    bar.buttons["step"].click()
    assert _shown(w) == {ASSEMBLY, "sub/o15_sub_asm.SLDASM", "boxA_as_step.SLDPRT"}
    # The folder tree, the name filter and the index's search each narrow it further.
    w.tree.setCurrentItem(w._folders["sub"])
    assert _shown(w) == {"sub/o15_sub_asm.SLDASM"}
    w.tree.setCurrentItem(w._folders[""])
    w.filter.setText("o08")
    assert _shown(w) == {ASSEMBLY}
    w.proxy.set_also({"o02_boxA.SLDPRT", "boxA_as_step.SLDPRT"})  # what the index found for "o08"
    assert _shown(w) == {ASSEMBLY, "boxA_as_step.SLDPRT"}
    w.filter.clear()
    # A button turned off again; All turns every one off.
    bar.buttons["sldasm"].click()
    assert _shown(w) == {"boxA_as_step.SLDPRT"}
    bar.all_button.click()
    assert not bar.selected() and bar.all_button.isChecked() and len(_shown(w)) == 7
    bar.all_button.click()  # All while every type shows: it stays on
    assert bar.all_button.isChecked() and not bar.selected()
    # Folders have no type: shown only while the quick filter is off.
    w.model.append([(model.listing_entry("deep", "folder", "skipped", reason="max_depth"), None)])
    assert "deep" in _shown(w)
    bar.buttons["sldprt"].click()
    assert "deep" not in _shown(w) and all(p.endswith(".SLDPRT") for p in _shown(w))


@needs_qt
def test_tooltips_name_the_type_and_count_what_the_list_would_show(app, window, mixed):
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QHelpEvent
    from PySide6.QtWidgets import QApplication

    w = window
    bar = w.quick
    _open(app, w, mixed)

    def second_line(key: str) -> str:
        return bar.tooltip_text(key).splitlines()[1]

    text = bar.tooltip_text("sldprt")
    assert text.startswith("SOLIDWORKS Part (SLDPRT)\n3 files in the folder shown\n")
    assert second_line("step") == "1 file in the folder shown"
    w.tree.setCurrentItem(w._folders["sub"])
    assert second_line("sldprt") == "1 file in the folder shown"
    w.filter.setText("boxB")
    assert second_line("sldprt") == "0 files in the folder shown that match the filter"
    w.tree.setCurrentItem(w._folders[""])
    assert second_line("sldprt") == "1 file in the folder shown that matches the filter"
    w.filter.setText("box")
    assert second_line("sldprt") == "3 files in the folder shown that match the filter"
    # Files the listing could not read count under the type their name says, and are said.
    w.model.append([(_entry("damaged_boxC.SLDPRT", "error", error={"code": "truncated"}), None)])
    assert second_line("sldprt") == "4 files in the folder shown that match the filter; 1 could not be read"
    w.filter.clear()
    assert second_line("sldprt") == "4 files in the folder shown; 1 could not be read"
    # The count ignores the quick filter itself: it says what turning the button on adds.
    w.filter.setText("boxB")
    bar.buttons["sldasm"].click()
    assert bar.count("sldprt") == 1
    # The tooltip is worked out when it shows, and escaped like every other one.
    button = bar.buttons["sldprt"]
    QApplication.sendEvent(
        button, QHelpEvent(QEvent.Type.ToolTip, QPoint(4, 4), button.mapToGlobal(QPoint(4, 4)))
    )
    assert button.toolTip().startswith("<qt>SOLIDWORKS Part (SLDPRT)<br>1 file in the folder shown that")
    QApplication.instance().processEvents()


@needs_qt
def test_the_buttons_are_reached_with_tab_and_toggled_with_space(app, window, mixed):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QAccessible, QKeyEvent
    from PySide6.QtWidgets import QApplication

    w = window
    bar = w.quick
    _open(app, w, mixed)
    chain, at = [], w.sort_combo
    while len(chain) < 5:  # what Tab goes to after the sort list
        at = at.nextInFocusChain()
        if at.focusPolicy() & Qt.FocusPolicy.TabFocus and at.isVisible():
            chain.append(at)
    assert chain == [bar.all_button, *(bar.buttons[k] for k in ("sldprt", "sldasm", "slddrw", "step"))]
    assert all(b.focusPolicy() & Qt.FocusPolicy.TabFocus for b in chain)
    button = bar.buttons["slddrw"]
    for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        QApplication.sendEvent(button, QKeyEvent(kind, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier))
    assert bar.selected() == {"slddrw"} and _shown(w) == {"o18_drw_boxA.SLDDRW"}
    face = QAccessible.queryAccessibleInterface(button)
    assert face.text(QAccessible.Text.Name) == "SOLIDWORKS Drawing (SLDDRW)"
    assert face.state().checkable and face.state().checked
    assert QAccessible.queryAccessibleInterface(bar.all_button).text(QAccessible.Text.Name) == "All types"


@needs_qt
def test_the_row_wraps_rather_than_widen_the_list(app, window, mixed):
    from solidseas_app.viewer.quickfilter import BUTTON

    w = window
    bar = w.quick
    _open(app, w, mixed)
    middle = bar.parentWidget()
    narrowest = middle.minimumSizeHint().width()
    _add_formats(
        w,
        *[(f"m.{ext}", ext) for ext in ("stl", "3mf", "obj", "ply", "amf", "off")],
        ("a.x_t", "parasolid"),
        ("a.x_b", "parasolid"),
        ("a.gltf", "gltf"),
        ("a.glb", "gltf"),
        ("a.ad_prt", "alibre"),
    )
    assert len(bar.keys()) == 15
    assert middle.minimumSizeHint().width() == narrowest  # the pane is no wider for the buttons
    w.split.setSizes([120, 220, 860])
    app.processEvents()
    assert bar.width() <= 240 and bar.height() >= 2 * BUTTON  # on more than one line
    rects = [b.geometry() for b in (bar.all_button, *bar.buttons.values())]
    assert all(bar.rect().contains(r) for r in rects)
    assert not any(a.intersects(b) for i, a in enumerate(rects) for b in rects[i + 1 :])
    assert len({r.top() for r in rects}) >= 2
    assert bar.heightForWidth(2000) == BUTTON


@needs_qt
def test_a_new_folder_keeps_the_types_it_has_and_drops_the_others(app, window, mixed, tmp_path):
    w = window
    bar = w.quick
    _open(app, w, mixed)
    bar.set_selected({"sldasm", "step"})
    parts_and_assemblies = tmp_path / "pa"
    parts_and_assemblies.mkdir()
    for name in ("o02_boxA.SLDPRT", ASSEMBLY):
        shutil.copy2(fixture_path(name), parts_and_assemblies / name)
    w.open_folder(str(parts_and_assemblies))
    # While it is listed, the row keeps its buttons and the types on keep filtering, so
    # the list says why it is filtered.
    assert bar.isVisible() and bar.keys() == ["sldprt", "sldasm", "slddrw", "step"]
    assert bar.selected() == {"sldasm", "step"}
    _wait(app, lambda: w.listing_info is not None and w._listing is None)
    assert bar.keys() == ["sldprt", "sldasm"] and bar.selected() == {"sldasm"} and _shown(w) == {ASSEMBLY}
    parts = tmp_path / "parts"
    parts.mkdir()
    shutil.copy2(fixture_path("o02_boxA.SLDPRT"), parts / "o02_boxA.SLDPRT")
    _open(app, w, parts)
    # None of the types on is here: the quick filter is off and the list shows everything.
    assert bar.keys() == ["sldprt"] and not bar.selected() and bar.all_button.isChecked()
    assert _shown(w) == {"o02_boxA.SLDPRT"}
    assert bar.set_selected({"sldasm"}) == frozenset()  # a type the folder has not: not turned on
    empty = tmp_path / "empty"
    empty.mkdir()
    _open(app, w, empty)
    assert not bar.isVisible() and bar.keys() == []


@needs_qt
@pytest.mark.parametrize("on", [(), ("sldasm",)])
def test_reload_keeps_the_row_its_buttons_and_the_keyboard_focus(app, window, mixed, on):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    w = window
    bar = w.quick
    _open(app, w, mixed)
    bar.set_selected(on)
    w.activateWindow()
    focused = bar.buttons["slddrw"]
    focused.setFocus(Qt.FocusReason.TabFocusReason)
    app.processEvents()
    assert QApplication.focusWidget() is focused
    before = dict(bar.buttons)
    top, height = w.list_stack.geometry().top(), bar.height()
    w.reload()
    # While the folder is listed again the row is as it was: the same buttons, the
    # list where it was (its rows still shown, until the new ones are read), the focus
    # where it was.
    assert w._listing is not None and w.model.rows
    assert bar.isVisible() and bar.buttons == before and bar.selected() == set(on)
    assert QApplication.focusWidget() is focused
    app.processEvents()  # lays the window out again (the listing may have ended meanwhile)
    assert bar.height() == height and w.list_stack.geometry().top() == top
    _wait(app, lambda: w.listing_info is not None and w._listing is None)
    app.processEvents()
    assert bar.buttons == before and all(bar.buttons[k] is b for k, b in before.items())
    assert QApplication.focusWidget() is focused and w.list_stack.geometry().top() == top
    assert bar.selected() == set(on) and len(_shown(w)) == (2 if on else 7)


@needs_qt
def test_a_listing_cut_short_keeps_the_types_on(app, window, mixed, tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    w = window
    bar = w.quick
    _open(app, w, mixed)
    bar.set_selected({"step", "slddrw"})
    for result in (
        {"ok": True, "cancelled": True, "truncated_reason": None},  # Esc or Cancel Listing
        {"ok": True, "cancelled": False, "truncated_reason": "max_entries"},  # stopped early
        {"ok": False, "error": {"code": "permission_denied"}},  # the folder could not be listed
    ):
        w.model.clear()  # what opening the folder does; the listing then gave one part
        w.model.append([(_entry("o02_boxA.SLDPRT", format="modern", doc_type="part"), None)])
        bar.listing_done(result)
        # It does not say the folder lacks STEP files or drawings: they stay on, with buttons.
        assert bar.selected() == {"step", "slddrw"} and bar.isVisible(), result
        assert bar.keys() == ["sldprt", "slddrw", "step"] and not bar.buttons["sldprt"].isChecked()
        assert bar.set_selected({"step", "sldasm"}) == {"step", "sldasm"}  # not narrowed to the rows
        bar.set_selected({"step", "slddrw"})
    # A type turned off that no row has loses its button.
    bar.buttons["slddrw"].click()
    assert bar.keys() == ["sldprt", "step"] and bar.selected() == {"step"}
    # A whole listing then drops what the folder lacks.
    parts = tmp_path / "parts"
    parts.mkdir()
    shutil.copy2(fixture_path("o02_boxA.SLDPRT"), parts / "o02_boxA.SLDPRT")
    _open(app, w, parts)
    assert bar.keys() == ["sldprt"] and not bar.selected()
    # A real cancel, in whichever state the race leaves it, never drops a type the rows have.
    _open(app, w, mixed)
    bar.set_selected({"sldasm"})
    w.activateWindow()
    bar.buttons["sldasm"].setFocus(Qt.FocusReason.TabFocusReason)
    w.reload()
    w.cancel_listing()
    _wait(app, lambda: w.listing_info is not None and w._listing is None)
    assert bar.selected() == {"sldasm"} and QApplication.focusWidget() is bar.buttons["sldasm"]


@needs_qt
def test_lock_files_give_a_type_only_while_they_are_shown(app, window, tmp_path):
    w = window
    bar = w.quick
    folder = tmp_path / "locks"
    folder.mkdir()
    shutil.copy2(fixture_path(ASSEMBLY), folder / ASSEMBLY)
    shutil.copy2(fixture_path("o02_boxA.SLDPRT"), folder / "~$o02_boxA.SLDPRT")
    _open(app, w, folder)
    assert bar.keys() == ["sldasm"]
    w.set_lock_files(True)
    assert bar.keys() == ["sldprt", "sldasm"] and bar.count("sldprt") == 1
    bar.set_selected({"sldprt"})
    assert _shown(w) == {"~$o02_boxA.SLDPRT"}
    # Hidden again, the lock file's type goes and is turned off, as in a folder without it.
    w.set_lock_files(False)
    assert bar.keys() == ["sldasm"] and not bar.selected() and bar.all_button.isChecked()
    assert _shown(w) == {ASSEMBLY}
    # A type on with a lock file's: only that one goes.
    w.set_lock_files(True)
    bar.set_selected({"sldprt", "sldasm"})
    w.set_lock_files(False)
    assert bar.selected() == {"sldasm"} and bar.buttons["sldasm"].isChecked() and _shown(w) == {ASSEMBLY}


@needs_qt
def test_selecting_a_document_turns_its_type_on_and_back_restores_the_filter(app, window, mixed):
    w = window
    bar = w.quick
    _open(app, w, mixed)
    bar.set_selected({"slddrw"})
    assert w.select_document("o02_boxA.SLDPRT")  # opening a file selects it, whatever was on
    assert bar.selected() == {"slddrw", "sldprt"} and "o02_boxA.SLDPRT" in _shown(w)
    bar.set_selected({"slddrw"})
    assert w._select_listed(ASSEMBLY)  # going to a component widens the filters just enough
    assert bar.selected() == {"slddrw", "sldasm"}
    place = w._place()
    assert place is not None and place.type_filter == {"slddrw", "sldasm"}
    bar.set_selected({"step"})
    w._history.append(place)
    assert w.go_back() and bar.selected() == {"slddrw", "sldasm"}


@needs_qt
def test_the_types_on_are_remembered_with_the_layout(app, tmp_path, mixed):
    from solidseas_app.viewer.settings import SettingsStore
    from solidseas_app.viewer.window import MainWindow

    path = tmp_path / "Viewer.ini"
    first = MainWindow(SettingsStore(str(path)))
    first.show()
    _open(app, first, mixed)
    first.quick.set_selected({"step", "sldasm"})
    first.close()  # saves the session
    assert "quick_filter=sldasm,step" in path.read_text(encoding="utf-8")
    second = MainWindow(SettingsStore(str(path)))
    try:
        assert second.restore_session() == str(mixed)
        assert second.quick.selected() == {"sldasm", "step"} and not second.quick.isVisible()
        second.show()
        second.reopen(str(mixed))
        _wait(app, lambda: second.listing_info is not None and second._listing is None)
        assert second.quick.selected() == {"sldasm", "step"}
        assert _shown(second) == {ASSEMBLY, "sub/o15_sub_asm.SLDASM", "boxA_as_step.SLDPRT"}
        second.change_settings(remember_session=False)  # forgets the folder and the layout
        assert "quick_filter" not in path.read_text(encoding="utf-8")
    finally:
        second.shutdown()
        second.close()
    third = MainWindow(SettingsStore(str(path)))
    try:
        assert third.restore_session() is None and not third.quick.selected()
    finally:
        third.shutdown()
        third.close()


@needs_qt
def test_a_forged_remembered_selection_is_dropped(app, tmp_path):
    from solidseas_app.viewer.settings import SettingsStore

    path = tmp_path / "Viewer.ini"
    path.write_text("[Session]\nquick_filter=sldprt,<img src=x>\n", encoding="utf-8")
    assert SettingsStore(str(path)).load_session().quick_filter == ()
    path.write_text("[Session]\nquick_filter=STEP,sldprt,sat\n", encoding="utf-8")
    assert SettingsStore(str(path)).load_session().quick_filter == ("sldprt", "step", "sat")


@needs_qt
@pytest.mark.parametrize("scale", [1.0, 1.25, 1.5])
def test_every_glyph_is_drawn_inside_its_square_at_any_scale(app, scale):
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QImage, QPainter

    from solidseas_app.viewer.quickfilter import GLYPH, paint_glyph

    side = round(GLYPH * scale)
    pictures = {}
    for ft in [*filetypes.FILE_TYPES, *(filetypes.info(k) for k in ("catpart", "sldlfp", "x"))]:
        img = QImage(side + 8, side + 8, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        img.setDevicePixelRatio(scale)
        p = QPainter(img)
        paint_glyph(p, QRectF(4 / scale, 4 / scale, GLYPH, GLYPH), ft)
        p.end()
        alpha = [[img.pixelColor(x, y).alpha() for x in range(img.width())] for y in range(img.height())]
        drawn = [(x, y) for y, row in enumerate(alpha) for x, a in enumerate(row) if a > 0]
        assert drawn, ft.key
        assert all(3 <= x <= side + 4 and 3 <= y <= side + 4 for x, y in drawn), (
            ft.key
        )  # inside, give or take AA
        assert len(drawn) > 0.25 * side * side, ft.key
        white = [
            (x, y) for x, y in drawn if alpha[y][x] == 255 and min(img.pixelColor(x, y).getRgb()[:3]) > 200
        ]
        if ft.glyph == "badge":  # its letters, in white
            assert white, ft.key
        if "_" in ft.letters and len(ft.letters) <= 4:  # X_T's underscore stays clear of the badge's edge
            assert max(y for _, y in white) <= max(y for _, y in drawn) - 2, ft.key
        if ft.glyph != "badge" and ft.letters:  # a tag's letters, about 6 pixels tall at 100 percent
            tag = [y for x, y in white if x > 4 + 0.35 * side and y > 4 + 0.5 * side]
            # hinting snaps the letters to whole pixels, so a font may come out a pixel short
            assert max(tag) - min(tag) + 1 >= 6 * scale - 1, ft.key
        pictures[ft.key] = bytes(img.constBits())
    assert len(set(pictures.values())) == len(pictures)  # no two types look the same


@needs_qt
def test_a_long_extension_takes_two_lines_on_its_badge(app):
    from solidseas_app.viewer.quickfilter import badge_lines

    assert badge_lines("STEP") == ["STEP"] and badge_lines("X_T") == ["X_T"]
    assert badge_lines("3DXML") == ["3D", "XML"] and badge_lines("SLDLFP") == ["SLD", "LFP"]
    assert badge_lines("AD_DRW") == ["AD", "DRW"] and badge_lines("AD_PKG") == ["AD", "PKG"]


@needs_qt
def test_a_button_that_is_on_is_framed_in_the_highlight_colour(app):
    from PySide6.QtGui import QColor, QImage, QPalette

    from solidseas_app.viewer.quickfilter import BUTTON, TypeButton

    for dark in (False, True):
        button = TypeButton(filetypes.TYPES["sldprt"])
        if dark:
            pal = button.palette()
            pal.setColor(QPalette.ColorRole.Window, QColor("#202020"))
            pal.setColor(QPalette.ColorRole.Highlight, QColor("#3d8ee8"))
            button.setPalette(pal)
        button.resize(BUTTON, BUTTON)
        shots = []
        for on in (False, True):
            button.setChecked(on)
            img = QImage(BUTTON, BUTTON, QImage.Format.Format_ARGB32)
            img.fill(button.palette().color(QPalette.ColorRole.Window))
            button.render(img)
            shots.append(img)
        hl = button.palette().color(QPalette.ColorRole.Highlight)
        edge = shots[1].pixelColor(BUTTON // 2, 0)
        assert abs(edge.red() - hl.red()) + abs(edge.green() - hl.green()) + abs(edge.blue() - hl.blue()) < 60
        assert shots[0].pixelColor(BUTTON // 2, 0) == button.palette().color(QPalette.ColorRole.Window)
        button.deleteLater()


@needs_qt
def test_the_self_test_turns_types_on_checks_the_list_and_turns_them_off(app, tmp_path, mixed):
    from PySide6.QtCore import QTimer

    from solidseas_app.viewer import app as viewer_app
    from solidseas_app.viewer.selftest import SelfTest
    from solidseas_app.viewer.window import MainWindow

    base = ["--self-test", str(mixed), "--screenshot-dir", str(tmp_path / "s")]
    args = viewer_app.build_parser().parse_args(
        [*base, "--quick-filter", "SLDDRW,.sldasm", "--quick-filter", "stp"]
    )
    assert args.quick_filter == [("sldasm", "slddrw"), ("step",)]
    assert viewer_app.main([*base, "--quick-filter", "not a type"]) == viewer_app.EXIT_USAGE
    assert viewer_app.main(["--quick-filter", "sldprt"]) == viewer_app.EXIT_USAGE  # belongs to the self-test
    report = ["--self-test", str(mixed), "--report", str(tmp_path / "r.json"), "--select-all"]
    assert viewer_app.main([*report, "--quick-filter", "sldprt"]) == viewer_app.EXIT_USAGE
    assert not (tmp_path / "s").exists()

    window = MainWindow()
    window.resize(1200, 800)
    window.show()
    shots = tmp_path / "shots"
    st = SelfTest(
        window,
        str(mixed),
        screenshot_dir=str(shots),
        select=["o02_boxA.SLDPRT"],
        quick_filters=[("sldasm", "slddrw"), ("step",), ("stl",)],
    )
    QTimer.singleShot(0, st.start)
    assert app.exec() == 1  # the folder has no STL file: that one fails
    window.shutdown()
    window.close()
    result = json.loads((shots / "selftest.json").read_text(encoding="utf-8"))
    runs = result["quick_filters"]
    assert [r["types"] for r in runs] == [["sldasm", "slddrw"], ["step"], ["stl"]]
    assert runs[0]["ok"] and (runs[0]["expected"], runs[0]["shown"]) == (3, 3)
    assert runs[1]["ok"] and (runs[1]["expected"], runs[1]["shown"]) == (1, 1)
    assert not runs[2]["ok"] and runs[2]["problems"][0] == "no button for stl"
    assert [e["where"] for e in result["errors"]] == ["quick_filter"]
    names = [Path(p).name for p in result["screenshots"]]
    assert any(n.endswith("quick_filter_sldasm_slddrw_details.png") for n in names)
    assert any(n.endswith("quick_filter_step_icons.png") for n in names)
    assert all(Path(p).stat().st_size > 0 for r in runs for p in r["screenshots"])
    assert result["documents"][0]["name"] == "o02_boxA.SLDPRT"  # the documents were still read after it
    # --quick-filter has a message of its own with --select-all: it does not need --select.
    message = _usage(viewer_app, [*report, "--quick-filter", "sldprt"])
    assert "--quick-filter does not go with --select-all" in message and "go with --select," not in message


def _usage(viewer_app, argv: list[str]) -> str:
    import contextlib
    import io

    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        assert viewer_app.main(argv) == viewer_app.EXIT_USAGE
    return err.getvalue()


@needs_qt
def test_the_self_test_catches_a_tooltip_that_counts_wrong(app, window, mixed, tmp_path, monkeypatch):
    from solidseas_app.viewer.quickfilter import QuickFilterBar
    from solidseas_app.viewer.selftest import SelfTest

    w = window
    _open(app, w, mixed)
    st = SelfTest(w, str(mixed), screenshot_dir=None, select=None, report=str(tmp_path / "r.json"))
    assert st._quick_filter(("step",))["ok"]
    right = QuickFilterBar.tooltip_text

    def eleven(bar, key):  # "11 files" where the list shows 1: a substring test would pass it
        lines = right(bar, key).splitlines()
        return "\n".join([lines[0], "1" + lines[1].replace("1 file ", "1 files ", 1), *lines[2:]])

    monkeypatch.setattr(QuickFilterBar, "tooltip_text", eleven)
    rec = st._quick_filter(("step",))
    said = "the tooltip of step says '11 files in the folder shown', not 1"
    assert not rec["ok"] and rec["problems"] == [said]
    assert st.report["errors"][-1]["where"] == "quick_filter"
