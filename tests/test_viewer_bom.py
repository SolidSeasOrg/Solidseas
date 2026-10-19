"""The viewer's BOM tab and its export (``docs/API.md`` 3.16).

The details panel reads an assembly's three BOM types in one go, with the
resolution its References tab made, and shows the one chosen as SOLIDWORKS
draws its BOM tables. On fixture o16 the tab's cells equal the top-level and
indented tables SOLIDWORKS put on o19. A row goes to its file as an instance's
row does, the configuration follows the Components tab's, and Export BOM writes
the BOM shown as CSV or JSON under the viewer's write guards. Nothing read
changes.
"""

import csv
import io
import json

import pytest

from solidseas.bom import COLUMNS, table_cells
from solidseas.errors import InvalidArgumentError, OutputRefusedError
from solidseas_app.viewer import reading
from support import FIXTURES, fixture_path
from test_viewer import Viewer, _state, _wait, needs_qt

O16 = "o16_asm_features.SLDASM"
GT = json.loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))
SW_TYPES = {2: "top", 3: "indented"}
TABLES = {SW_TYPES[t["bom_type"]]: t["cells"] for t in GT["o19_drw_asm.SLDDRW"]["api"]["bom_tables"]}


@pytest.fixture(scope="module")
def app():
    import os

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


# --------------------------------------------------------------------------- reading, no Qt
def test_the_bom_section_matches_solidworks_with_the_references_resolution():
    before = _state(FIXTURES)
    path = str(fixture_path(O16))
    sections = dict(reading.read_document(path, str(FIXTURES)))
    assert list(sections) == list(reading.SECTIONS) and all(s["ok"] for s in sections.values())
    data = sections["bom"]["data"]
    assert data["kind"] == "assembly" and data["configuration"] == "Default"
    assert set(data["boms"]) == {"top", "parts", "indented"}
    for bom_type, cells in TABLES.items():
        b = data["boms"][bom_type]
        assert table_cells(b["type"], b["property_columns"], b["rows"]) == cells, bom_type
    refs = sections["references"]["data"]["references"]
    for b in data["boms"].values():  # the same files the References tab found
        assert b["resolution"] == refs["resolution"] and b["complete"]
        found = {f["key"]: f["resolution"]["match"] for f in refs["files"]}
        for r in b["rows"]:
            if r["location"] is not None:
                assert r["location"] == found[r["file"]] and r["location"]["root"] == reading.ROOT_ID
    lite = reading.read_bom(path, str(FIXTURES), "Lite")["data"]
    assert lite["configuration"] == "Lite"
    assert "o15_sub_asm" not in [r["part_number"] for r in lite["boms"]["indented"]["rows"]]
    part = dict(reading.read_document(str(fixture_path("o02_boxA.SLDPRT")), str(FIXTURES)))
    assert part["bom"] == {**part["bom"], "ok": True, "data": {"kind": "part"}}
    assert _state(FIXTURES) == before


def test_a_bom_exports_as_csv_or_json_under_the_write_guards(tmp_path):
    before = _state(FIXTURES)
    path = str(fixture_path(O16))
    data = reading.read_bom(path, str(FIXTURES), None)["data"]["boms"]["indented"]
    out = tmp_path / "out"
    out.mkdir()
    written = reading.export_bom(path, str(FIXTURES), str(out), data, fmt="csv", overwrite=False)
    target = out / "o16_asm_features_bom_indented.csv"
    assert written["output"] == str(target) and written["mime"] == "text/csv"
    raw = target.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and written["bytes"] == len(raw)
    rows = list(csv.reader(io.StringIO(raw[3:].decode("utf-8"), newline="")))
    assert [r[:4] for r in rows] == [[c[0], c[1].strip(), c[2], c[3]] for c in TABLES["indented"]]
    written = reading.export_bom(path, str(FIXTURES), str(out), data, fmt="json", overwrite=False)
    env = json.loads((out / "o16_asm_features_bom_indented.json").read_text(encoding="utf-8"))
    assert env["kind"] == "bom" and env["data"] == data and env["source"] == {"file": path}
    with pytest.raises(OutputRefusedError):  # an existing file is replaced only when asked
        reading.export_bom(path, str(FIXTURES), str(out), data, fmt="csv", overwrite=False)
    reading.export_bom(path, str(FIXTURES), str(out), data, fmt="csv", overwrite=True)
    with pytest.raises(OutputRefusedError):  # never into the opened folder
        reading.export_bom(path, str(FIXTURES), str(FIXTURES), data, fmt="csv", overwrite=True)
    with pytest.raises(InvalidArgumentError):
        reading.export_bom(path, str(FIXTURES), str(out), data, fmt="xlsx", overwrite=True)
    assert _state(FIXTURES) == before


# --------------------------------------------------------------------------- the window, offscreen
def _tab(name: str) -> int:
    from solidseas_app.viewer.details import TABS

    return TABS.index(name)


def _cells(tree) -> list[list[str]]:
    return [[tree.topLevelItem(i).text(c) for c in range(4)] for i in range(tree.topLevelItemCount())]


def _choose_type(viewer: Viewer, bom_type: str) -> None:
    d = viewer.window.details
    index = d.bom_type.findData(bom_type)
    d.bom_type.setCurrentIndex(index)
    d.bom_type.activated.emit(index)  # as a choice made with the mouse
    viewer.app.processEvents()


def _row(tree, ident: str):
    from solidseas_app.viewer.details import IDENT_ROLE, _walk

    for item in _walk(tree):
        if item.data(0, IDENT_ROLE) == ident:
            return item
    raise AssertionError(f"no row {ident}")


def _listed(viewer: Viewer) -> str | None:
    w = viewer.window
    entry = w.model.entry(w.proxy.mapToSource(w.table.selectionModel().currentIndex()))
    return entry["path"] if entry else None


@needs_qt
def test_the_bom_tab_shows_solidworks_tables_and_goes_to_files(viewer):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    w, d = viewer.window, viewer.window.details
    before = _state(FIXTURES)
    viewer.open(FIXTURES)
    viewer.select(O16)
    d.tabs.setCurrentIndex(_tab("BOM"))
    assert viewer.page("BOM").showing_content and w.act_bom.isEnabled()
    t = d.bom_tree
    assert [t.headerItem().text(c) for c in range(4)] == list(COLUMNS)
    assert d.bom_config.currentText() == "Default"
    assert [d.bom_config.itemText(i) for i in range(d.bom_config.count())] == ["Default", "Lite"]
    for bom_type, cells in TABLES.items():
        _choose_type(viewer, bom_type)
        assert _cells(t) == cells[1:], bom_type
        assert d.bom_shown()["type"] == bom_type
    _choose_type(viewer, "parts")
    first = [r[:2] for r in _cells(t)][:3]
    assert first == [["1", "o02_boxA"], ["2", "o06_boxA_props_mat_cfg"], ["3", "o07_boxB_h31"]]
    assert "6 rows, 11 instances" in d.bom_counts.text()

    # A row goes to its file, as an instance's row does, and Back returns to the row.
    _choose_type(viewer, "indented")
    item = _row(t, "bom:3.1")
    assert item.text(6) == "o02_boxA.SLDPRT" and item.text(5) == "Default"
    t.setCurrentItem(item)
    rect = t.visualItemRect(item)
    point = QPoint(rect.left() + 20, rect.center().y())
    for send in (QTest.mouseClick, QTest.mouseDClick):
        send(t.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    viewer.app.processEvents()
    _wait(viewer.app, lambda: not w.busy and _listed(viewer) == "o02_boxA.SLDPRT")
    assert d.title.text() == "o02_boxA.SLDPRT"
    w.act_back.trigger()
    _wait(viewer.app, lambda: not w.busy and d.title.text() == O16)
    assert d.tabs.currentIndex() == _tab("BOM") and d.bom_tree.currentItem().text(0) == "3.1"
    virtual = _row(d.bom_tree, "bom:7")
    menu = d.component_menu(virtual)
    show = [a for a in menu.actions() if a.text().startswith("Show in folder list")]
    assert not show[0].isEnabled() and virtual.text(6).startswith("inside this document")
    menu.deleteLater()

    # The configuration is the assembly's: a choice on the BOM tab reads the Components tab too.
    d.bom_config.setCurrentText("Lite")
    d.bom_config.activated.emit(d.bom_config.currentIndex())
    _wait(
        viewer.app,
        lambda: viewer.page("BOM").showing_content
        and d.bom_shown()["configuration"] == "Lite"
        and d.configuration_shown() == "Lite",
    )
    assert "o15_sub_asm" not in [r[1] for r in _cells(d.bom_tree)]

    # A part has no BOM, and Export BOM is off.
    viewer.select("o02_boxA.SLDPRT")
    assert "no bill of materials" in viewer.page("BOM").message_text and not w.act_bom.isEnabled()
    assert _state(FIXTURES) == before


@needs_qt
def test_export_bom_writes_the_bom_shown_or_says_why_not(viewer, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from solidseas_app.viewer import window as window_module

    shown: list[str] = []
    monkeypatch.setattr(window_module, "show_message", lambda _p, _i, _t, text: shown.append(text))
    target = {"folder": str(tmp_path), "format": "json"}

    def accept(dialog):
        dialog.folder.setText(target["folder"])
        dialog.format.setCurrentIndex(dialog.format.findData(target["format"]))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(window_module.ExportDialog, "exec", accept)
    w, d = viewer.window, viewer.window.details
    before = _state(FIXTURES)
    viewer.open(FIXTURES)
    viewer.select(O16)
    d.tabs.setCurrentIndex(_tab("BOM"))
    _choose_type(viewer, "parts")
    d.bom_export.click()  # the tab's button, as the File menu's Export BOM
    _wait(viewer.app, lambda: len(shown) == 1)
    assert shown[0].startswith("Wrote the parts only BOM of configuration Default (6 rows) to")
    env = json.loads((tmp_path / "o16_asm_features_bom_parts.json").read_text(encoding="utf-8"))
    assert env["kind"] == "bom" and env["data"] == d.bom_shown()
    target.update(folder=str(FIXTURES), format="csv")
    w.act_bom.trigger()
    _wait(viewer.app, lambda: len(shown) == 2)
    assert shown[1].startswith("Nothing was written.") and "folder you opened" in shown[1]
    assert _state(FIXTURES) == before


@needs_qt
def test_edit_bom_opens_the_editor_on_the_bom_the_tab_shows(viewer):
    w, d = viewer.window, viewer.window.details
    before = _state(FIXTURES)
    viewer.open(FIXTURES)
    viewer.select(O16)
    d.tabs.setCurrentIndex(_tab("BOM"))
    _choose_type(viewer, "parts")
    d.bom_edit.click()
    [editor] = w._bom_editors
    assert editor.spec.type == "parts" and editor.configuration == "Default"
    assert editor.table.rowCount() == len(d.bom_shown()["rows"])
    assert editor.windowTitle().startswith("o16_asm_features.SLDASM (Default)")
    editor.close()
    viewer.app.processEvents()
    from PySide6.QtCore import QCoreApplication, QEvent

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert w._bom_editors == [], "a closed editor is let go"
    assert _state(FIXTURES) == before


@needs_qt
def test_export_bom_is_off_until_the_chosen_configurations_bom_shows(viewer, tmp_path):
    """While another configuration's BOM is read, and after that read failed, the BOM
    the tab showed before is no longer offered for export as if it were the new one."""
    import shutil

    w, d = viewer.window, viewer.window.details
    folder = tmp_path / "docs"
    folder.mkdir()
    for p in FIXTURES.iterdir():
        if p.suffix.upper() in (".SLDPRT", ".SLDASM"):
            shutil.copy2(p, folder / p.name)
    good = (folder / O16).read_bytes()
    viewer.open(folder)
    viewer.select(O16)
    d.tabs.setCurrentIndex(_tab("BOM"))
    assert viewer.page("BOM").showing_content and w.act_bom.isEnabled()

    def choose(configuration: str) -> None:
        d.bom_config.setCurrentText(configuration)
        d.bom_config.activated.emit(d.bom_config.currentIndex())

    choose("Lite")  # the read is started; its answer arrives with the next events
    assert d.bom_shown() is None and not w.act_bom.isEnabled()
    assert "Reading configuration Lite" in viewer.page("BOM").message_text
    _wait(viewer.app, lambda: viewer.page("BOM").showing_content and not w.busy)
    assert d.bom_shown()["configuration"] == "Lite" and w.act_bom.isEnabled()

    (folder / O16).write_bytes(b"not a document any more")  # replaced after it was shown
    choose("Default")
    _wait(viewer.app, lambda: "could not be read" in (viewer.page("BOM").message_text or "") and not w.busy)
    assert d.bom_shown() is None and not w.act_bom.isEnabled()

    (folder / O16).write_bytes(good)  # a failed BOM is read again on the next choice
    choose("Default")
    _wait(viewer.app, lambda: viewer.page("BOM").showing_content and not w.busy)
    assert d.bom_shown()["configuration"] == "Default" and w.act_bom.isEnabled()
