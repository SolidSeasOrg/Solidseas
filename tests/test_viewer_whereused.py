"""The viewer's Where Used tab, its background indexing and the filter by part number
or property (``solidseas_app.viewer.whereused`` and ``.indexer``).

The window indexes the opened folder in a child process; the catalog goes to the
session's temporary cache folder (``conftest.py``), never beside the documents,
which are copies in ``tmp_path``. Every other viewer test runs with indexing off.
"""

import os
import shutil
import time
from pathlib import Path

import pytest

from serve_support import copy_documents

try:
    import PySide6.QtWidgets  # noqa: F401

    HAVE_QT = True
except ImportError:  # pragma: no cover - CI installs PySide6
    HAVE_QT = False

needs_qt = pytest.mark.skipif(not HAVE_QT, reason="PySide6 is not installed")


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from solidseas_app.viewer.app import use_system_fonts

    use_system_fonts()
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _wait(app, condition, timeout: float = 120.0) -> None:
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            raise AssertionError("timed out waiting for the viewer")
        app.processEvents()
        time.sleep(0.005)


def _state(folder: Path) -> list[tuple]:
    return sorted(
        (str(p.relative_to(folder)), p.stat().st_size, p.stat().st_mtime_ns) for p in folder.rglob("*")
    )


@pytest.fixture
def window(app, monkeypatch):
    from solidseas_app.viewer import indexer
    from solidseas_app.viewer.window import MainWindow

    monkeypatch.setattr(indexer, "DEFAULT_ON", True)
    w = MainWindow()
    w.show()
    results: list = []
    shown: list = []
    w.where_used.indexFinished.connect(results.append)
    w.where_used.shown.connect(shown.append)
    w.test_results, w.test_shown = results, shown
    yield w
    assert w.shutdown()
    w.close()
    w.deleteLater()
    app.processEvents()


def _open_and_index(app, w, folder: Path) -> dict:
    del w.test_results[:]
    w.open_folder(str(folder))
    _wait(app, lambda: w.listing_info is not None)
    _wait(app, lambda: w.test_results)
    return w.test_results[-1]


def _select(app, w, name: str) -> dict:
    del w.test_shown[:]
    assert w.select_document(name)
    _wait(app, lambda: w.test_shown)
    return w.test_shown[-1]


def _rows(w) -> dict[str, list[list[str]]]:
    tree = w.details.where_used.tree
    out = {}
    for i in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(i)
        out[top.text(0)] = [[top.child(j).text(c) for c in range(5)] for j in range(top.childCount())]
    return out


@needs_qt
def test_where_used_after_the_folder_is_indexed(app, window, tmp_path):
    folder = tmp_path / "Job"
    copy_documents(folder)
    before = _state(folder)
    w = window
    result = _open_and_index(app, w, folder)
    assert result.get("ok"), result
    assert result["data"]["counts"]["read_ok"] == 19
    assert w.where_used.label.text() == "Indexed 19 documents"
    assert w.where_used.indexer.started == 1
    shown = _select(app, w, "o02_boxA.SLDPRT")
    assert shown["ok"] and shown["data"]["counts"]["users"] == 5
    page = w.details.pages["Where Used"]
    assert page.showing_content
    rows = _rows(w)
    assert list(rows) == ["Used directly by (4)", "Used inside (2)", "Drawings (2)"]
    assert rows["Used directly by (4)"][0] == [
        "o08_asm_2x_boxA.SLDASM",
        "Default (uses Default)",
        "2",
        "2",
        "2",
    ]
    assert ["o16_asm_features.SLDASM", "Lite (uses Default)", "1", "0", "0"] in rows["Used inside (2)"]
    assert "Indexed 19 documents" in w.details.where_used.status.text()
    assert w.where_used.act_where_used.text() == "&Where Used"
    w.where_used.act_where_used.trigger()
    assert w.details.tabs.currentWidget() is page

    # a row goes to its document, and Back returns
    tree = w.details.where_used.tree
    item = tree.topLevelItem(0).child(0)
    tree.itemActivated.emit(item, 0)
    _wait(app, lambda: w.details.title.text() == "o08_asm_2x_boxA.SLDASM")
    assert w.history and w.go_back()
    _wait(app, lambda: w.details.title.text() == "o02_boxA.SLDPRT")

    # one configuration of a part with several
    shown = _select(app, w, "o06_boxA_props_mat_cfg.SLDPRT")
    combo = w.details.where_used.config
    assert [combo.itemText(i) for i in range(combo.count())][1:] == shown["data"]["target"]["configurations"]
    del w.test_shown[:]
    combo.activated.emit(combo.findText("OracleAlt"))
    _wait(app, lambda: w.test_shown)
    assert w.test_shown[-1]["data"]["configuration"] == "OracleAlt" and w.test_shown[-1]["data"]["users"]
    shown = _select(app, w, "o19_drw_asm.SLDDRW")
    assert "No document in the indexed folders uses this file." in w.details.where_used.status.text()

    # the filter also finds what only the index knows: a description, not a name
    def listed():
        return {w.proxy.index(i, 0).data() for i in range(w.proxy.rowCount())}

    w.filter.setText("oracle")
    _wait(app, lambda: "o04_boxA_props.SLDPRT" in listed(), 30)
    found = {"o04_boxA_props.SLDPRT", "o05_boxA_props_mat.SLDPRT", "o06_boxA_props_mat_cfg.SLDPRT"}
    assert found <= listed() and "o02_boxA.SLDPRT" not in listed()
    assert w.filter.placeholderText() == "Filter by name, part number or property"
    w.filter.setText("o02")
    _wait(app, lambda: w.proxy.rowCount() == 1, 30)
    w.filter.clear()

    # opening the folder again shows its saved index and starts no scan; a re-index reads
    # the folder again and the catalog's scan reads nothing new
    _wait(app, lambda: w.where_used.job is None)
    del w.test_results[:]
    w.open_folder(str(folder))
    assert w.listing_info is not None and w.listing_info.get("saved") and w.where_used.job is None
    w.reindex()
    _wait(app, lambda: w.test_results)
    result = w.test_results[-1]
    assert result["data"]["counts"]["unchanged"] == 19 and result["data"]["counts"]["read_ok"] == 0
    assert _state(folder) == before


@needs_qt
def test_files_of_other_formats_are_indexed_as_the_list_shows_them(app, window, tmp_path):
    from solidseas import catalog
    from solidseas_app.viewer import samples
    from solidseas_app.viewer.whereused import not_followed_text, not_indexed_text

    folder = tmp_path / "Mixed"
    copy_documents(folder)
    samples.write_samples(str(folder / "samples"))
    before = _state(folder)
    w = window
    assert w.settings.show_all_formats  # the default: the list shows every 3D format, and so the index
    result = _open_and_index(app, w, folder)
    assert result.get("ok"), result
    assert result["data"]["counts"]["read_ok"] == 19 + len(samples.EXPECTED)
    shown = _select(app, w, "box.stl")
    assert shown["ok"] and shown["data"]["target"]["format"] == "stl" and shown["data"]["users"] == []
    status = w.details.where_used.status.text()
    assert "No document in the indexed folders uses this file." in status
    assert not_followed_text("stl") in status and "STL" in not_followed_text("stl")
    shown = _select(app, w, "o02_boxA.SLDPRT")  # a SOLIDWORKS document's uses, as before
    assert shown["data"]["counts"]["users"] == 5
    assert "does not follow references" not in w.details.where_used.status.text()
    shown = _select(app, w, "samples/cube.AD_PRT")  # an Alibre part: the assembly that places it
    assert [u["path"] for u in shown["data"]["users"]] == ["samples/pair.AD_ASM"]
    assert _rows(w)["Used directly by (1)"][0][0] == "samples/pair.AD_ASM"
    assert "does not follow references" not in w.details.where_used.status.text()
    w.change_settings(show_unreadable=True)
    _wait(app, lambda: w.listing_info is not None and w.model.find("samples/sheet.igs") is not None)
    assert w.select_document("samples/sheet.igs")  # a format SolidSeas cannot read is not indexed
    _wait(app, lambda: w.details.pages["Where Used"].message_text == not_indexed_text("iges"), 30)
    # Turned off, the list shows SOLIDWORKS documents only, and the index follows it.
    del w.test_results[:]
    w.change_settings(show_all_formats=False)
    _wait(app, lambda: w.test_results)
    assert w.test_results[-1]["ok"]
    with catalog.open(str(folder), mode="r") as cat:
        status = cat.status()
    assert status["formats"] == ["solidworks"] and status["counts"]["formats"] == {"solidworks": 19}
    assert _state(folder) == before


@needs_qt
def test_indexing_can_be_turned_off_and_the_index_cleared(app, window, tmp_path):
    from solidseas import catalog
    from solidseas_app.viewer import indexer

    folder = tmp_path / "Job"
    folder.mkdir()
    for name in ("o02_boxA.SLDPRT", "o08_asm_2x_boxA.SLDASM"):
        shutil.copy2(Path(__file__).parent / "fixtures" / name, folder / name)
    w = window
    _open_and_index(app, w, folder)
    db = catalog.locate(str(folder))[0]
    assert os.path.isfile(db)
    assert w.where_used.clear_now() and not os.path.exists(db)
    assert w.select_document("o02_boxA.SLDPRT")  # nothing is asked of an index that is not there
    _wait(app, lambda: w.details.pages["Where Used"].message_text == "The opened folder is not indexed.", 30)
    w.where_used.act_index.setChecked(False)
    assert not indexer.load_enabled(w.store) and w.where_used.label.text() == "Index off"
    assert w.store.load_section(indexer.SECTION) == {indexer.KEY: "false"}
    w.select_document("o08_asm_2x_boxA.SLDASM")
    _wait(app, lambda: "Index Opened Folders" in w.details.pages["Where Used"].message_text, 30)
    del w.test_results[:]
    w.where_used.act_index.setChecked(True)  # turning it on indexes the opened folder
    _wait(app, lambda: w.test_results)
    assert w.test_results[-1]["ok"] and os.path.isfile(db)


@needs_qt
def test_closing_the_window_stops_the_indexer(app, tmp_path, monkeypatch):
    from solidseas_app.viewer import indexer
    from solidseas_app.viewer.window import MainWindow

    monkeypatch.setattr(indexer, "DEFAULT_ON", True)
    root = tmp_path / "Big"
    for i in range(15):
        copy_documents(root / f"job{i:02d}")
    w = MainWindow()
    w.show()
    w.open_folder(str(root))
    _wait(app, lambda: w.listing_info is not None)
    _wait(app, lambda: w.where_used.indexer.running, 60)
    t = time.monotonic()
    assert w.shutdown()
    assert time.monotonic() - t < indexer.STOP_WAIT_S + 3
    assert not w.where_used.indexer.running
    w.close()
    w.deleteLater()
    app.processEvents()


def test_the_setting_reads_back_whatever_the_file_says():
    from solidseas_app.viewer import indexer

    class Store:
        def __init__(self, values):
            self.values = values

        def load_section(self, name):
            return dict(self.values) if name == indexer.SECTION else {}

    assert indexer.load_enabled(Store({})) == indexer.DEFAULT_ON
    assert indexer.load_enabled(Store({indexer.KEY: "false"})) is False
    assert indexer.load_enabled(Store({indexer.KEY: " Off "})) is False
    assert indexer.load_enabled(Store({indexer.KEY: "true"})) is True
    assert indexer.load_enabled(Store({indexer.KEY: "perhaps"})) is True


def test_ago_reads_like_a_person():
    from solidseas_app.viewer.wording import ago  # no Qt: runs where PySide6 is not installed

    now = 1_790_000_000.0
    import datetime

    def iso(seconds_ago):
        return datetime.datetime.fromtimestamp(now - seconds_ago, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    assert ago(iso(5), now) == "just now"
    assert ago(iso(120), now) == "2 minutes ago"
    assert ago(iso(3 * 3600), now) == "3 hours ago"
    assert ago(iso(86400), now) == "1 day ago"
    assert ago(None, now) == "never"


@needs_qt
def test_a_catalog_the_command_line_made_keeps_its_library_roots(app, window, tmp_path):
    from solidseas import Root, Roots, catalog

    fixtures = Path(__file__).parent / "fixtures"
    project, library = tmp_path / "Job", tmp_path / "Library"
    project.mkdir()
    library.mkdir()
    shutil.copy2(fixtures / "o08_asm_2x_boxA.SLDASM", project / "o08_asm_2x_boxA.SLDASM")
    shutil.copy2(fixtures / "o02_boxA.SLDPRT", library / "o02_boxA.SLDPRT")
    roots = Roots([Root("project", str(project)), Root("library1", str(library), role="library")])
    with catalog.open(roots) as cat:
        cat.scan(workers=1)
    w = window
    result = _open_and_index(app, w, project)
    assert result["ok"] and result["data"]["removed_roots"] == []
    with catalog.open(project, mode="r") as cat:
        assert [r.id for r in cat.roots] == ["project", "library1"]
        used = cat.where_used("library1", "o02_boxA.SLDPRT")
    assert [u["path"] for u in used["users"]] == ["o08_asm_2x_boxA.SLDASM"]
    shown = _select(app, w, "o08_asm_2x_boxA.SLDASM")
    assert shown["ok"] and shown["folder_root"] == "project" and shown["data"]["users"] == []


@needs_qt
def test_the_notes_column_cuts_a_long_note_at_its_end_and_tips_it_whole(app):
    """Paths in the tree are cut in the middle to keep both ends; a note is a sentence, so
    one too long for the Notes column is cut at its end, and its tooltip holds all of it."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QStyleOptionViewItem

    from solidseas_app.viewer.whereused import NOTES_COLUMN, WhereUsedPane

    pane = WhereUsedPane()
    note = ("the quantity is not known for this configuration " * 4).strip()
    user = {
        "root": "project",
        "path": "a/very/long/folder/name/top.SLDASM",
        "relation": "component",
        "depth": 1,
        "via": [],
        "warnings": [{"code": "quantity_unknown", "message": note}],
        "uses": [],
        "views": [],
    }
    pane.show_data({"users": [user], "possible": [], "name_matches": [], "counts": {"users": 1}}, "project")
    tree = pane.tree
    item = tree.topLevelItem(0).child(0)
    assert item.text(NOTES_COLUMN) == note and note in item.toolTip(NOTES_COLUMN)
    option = QStyleOptionViewItem()
    tree.itemDelegateForColumn(NOTES_COLUMN).initStyleOption(option, tree.indexFromItem(item, NOTES_COLUMN))
    assert option.textElideMode == Qt.TextElideMode.ElideRight
    assert tree.textElideMode() == Qt.TextElideMode.ElideMiddle  # the paths keep both ends
    pane.deleteLater()
