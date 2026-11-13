"""The viewer's History tab (``solidseas_app.viewer.history``): a file's versions newest
first, the chosen version's preview and its differences from the one before, Take
Snapshot and Compare with Working Copy, read in worker threads and only while the tab
is shown.

Every file is a synthetic 3MF written here (``mesh_writers``) in ``tmp_path``; every
snapshot goes to the session's temporary data folder (``conftest.py``), never beside
the file; a Git history is made with the git command line in ``tmp_path``.
"""

import os
import time
from pathlib import Path

import pytest

from mesh_writers import png, threemf
from model_writers import box
from solidseas import versions
from test_versions_git import Repo, needs_git

try:
    import PySide6.QtWidgets  # noqa: F401

    HAVE_QT = True
except ImportError:  # pragma: no cover - CI installs PySide6
    HAVE_QT = False

needs_qt = pytest.mark.skipif(not HAVE_QT, reason="PySide6 is not installed")


def part(height: float, *, title: str | None = None) -> bytes:
    """A 3MF box 10 x 20 x ``height`` mm with a stored thumbnail."""
    return threemf(
        box(10.0, 20.0, height), thumbnail=png(16, 12), metadata={"Title": title} if title else None
    )


def _state(folder: Path) -> list[tuple]:
    return sorted(
        (str(p.relative_to(folder)), p.stat().st_size, p.stat().st_mtime_ns)
        for p in folder.rglob("*")
        if ".git" not in p.relative_to(folder).parts
    )


# --------------------------------------------------------------------------- the rows and the words
def test_rows_of_a_file_with_no_history_are_its_working_copy(tmp_path):
    from solidseas_app.viewer import history

    path = tmp_path / "box.3mf"
    path.write_bytes(part(30))
    rows = history.version_rows(str(path))
    assert [(r.kind, r.ref, r.note) for r in rows] == [("working", "working", "No snapshot yet")]
    assert not history.has_history(rows) and not history.from_git(rows)
    assert not history.working_comparable(rows, 0, True)


def test_rows_of_snapshots_newest_first_with_the_working_copy_on_top(tmp_path):
    from solidseas_app.viewer import history

    path = tmp_path / "box.3mf"
    path.write_bytes(part(30))
    versions.snapshot(path, note="first")
    rows = history.version_rows(str(path))
    assert [(r.label, r.kind, r.note) for r in rows] == [("v1", "snapshot", "first")]
    assert rows[0].size == len(part(30)) and rows[0].readable and rows[0].source == "Snapshot"
    # unchanged: the newest snapshot is the working copy, nothing to compare it with
    assert not history.working_comparable(rows, 0, True)
    path.write_bytes(part(31))
    rows = history.version_rows(str(path))
    assert [(r.label, r.kind, r.note) for r in rows] == [
        ("v2", "working", "Changed since the newest snapshot"),
        ("v1", "snapshot", "first"),
    ]
    assert history.working_comparable(rows, 1, True) and not history.working_comparable(rows, 0, True)
    assert not history.working_comparable(rows, 1, False)  # the file is gone


def test_the_differences_in_words(tmp_path):
    from solidseas_app.viewer import history

    path = tmp_path / "box.3mf"
    path.write_bytes(part(30, title="Box"))
    versions.snapshot(path)
    path.write_bytes(part(31, title="Taller box"))
    diff = versions.compare(path)
    groups = dict(history.diff_groups(diff))
    assert "Geometry" in groups
    geometry = groups["Geometry"]
    assert geometry[0] == ("The model", "", "Changed")
    assert ("  Volume", "6,000 mm3", "6,200 mm3") in geometry
    assert ("  Size in z", "30 mm", "31 mm") in geometry
    caption = history.diff_caption(diff)
    assert caption.startswith("Changes from v1 (snapshot, ") and caption.endswith("to v2, the working copy.")
    same = versions.compare(path, "working", "working")
    assert history.diff_caption(same).endswith("The two versions are the same file.")


def test_a_source_of_rows_can_be_given(tmp_path):
    """The tab's one source of rows can be replaced: by a list of rows, or by a
    FileHistory with its warnings and library."""
    from solidseas_app.viewer import history

    row = history.VersionRow("abcd1234", 1, "snapshot", "2026-11-01T10:00:00Z", "checked in", 10)
    got = history.load_work(str(tmp_path / "none.3mf"), lambda p: [row])(None, lambda: False)
    assert got == {"ok": True, "rows": [row], "warnings": [], "library": None, "exists": False}
    full = history.FileHistory([row], ("The history was cut short",), str(tmp_path))
    got = history.load_work(str(tmp_path / "none.3mf"), lambda p: full)(None, lambda: False)
    assert got["warnings"] == ["The history was cut short"] and got["library"] == str(tmp_path)


# --------------------------------------------------------------------------- the window
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


@pytest.fixture
def window(app):
    from solidseas_app.viewer.window import MainWindow

    w = MainWindow()
    w.show()
    shown: list = []
    w.file_history.shown.connect(shown.append)
    w.test_shown = shown
    yield w
    assert w.shutdown()
    w.close()
    w.deleteLater()
    app.processEvents()


def _open(app, w, folder: Path) -> None:
    w.open_folder(str(folder))
    _wait(app, lambda: w.listing_info is not None)


def _results(app, w, n: int) -> list:
    """Wait for ``n`` more results of the tab, from now."""
    start = len(w.test_shown)
    _wait(app, lambda: len(w.test_shown) >= start + n)
    return w.test_shown[start:]


def _select(app, w, name: str) -> None:
    del w.test_shown[:]
    assert w.select_document(name), name
    _wait(app, lambda: w.file_history.path is not None and w.file_history.path.endswith(name))


def _show_tab(app, w) -> list:
    from solidseas_app.viewer.details import TABS

    start = len(w.test_shown)
    w.details.tabs.setCurrentIndex(TABS.index("History"))
    _wait(app, lambda: len(w.test_shown) >= start + 2)  # the list, then the newest version's details
    return w.test_shown[start:]


def _rows(w) -> list[list[str]]:
    tree = w.details.history.tree
    return [[tree.topLevelItem(i).text(c) for c in (0, 2, 3)] for i in range(tree.topLevelItemCount())]


def _diff(w) -> dict[str, list[list[str]]]:
    tree = w.details.history.diff
    out = {}
    for i in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(i)
        out[top.text(0)] = [[top.child(j).text(c) for c in range(3)] for j in range(top.childCount())]
    return out


@needs_qt
def test_history_is_read_only_while_its_tab_is_shown(app, window, tmp_path):
    from solidseas_app.viewer.details import TABS

    folder = tmp_path / "Job"
    folder.mkdir()
    (folder / "box.3mf").write_bytes(part(30))
    w = window
    _open(app, w, folder)
    w.details.tabs.setCurrentIndex(TABS.index("Overview"))
    _select(app, w, "box.3mf")
    for _ in range(50):
        app.processEvents()
        time.sleep(0.002)
    assert w.test_shown == [] and not w.file_history._loaded
    assert w.details.pages["History"].message_text == "Reading the versions of this file..."
    shown = _show_tab(app, w)
    assert shown[0]["ok"] and [r.kind for r in shown[0]["rows"]] == ["working"]


@needs_qt
def test_snapshots_their_previews_and_differences_in_the_tab(app, window, tmp_path):
    from solidseas_app.viewer import history

    folder = tmp_path / "Job"
    folder.mkdir()
    path = folder / "box.3mf"
    path.write_bytes(part(30))
    w = window
    _open(app, w, folder)
    _select(app, w, "box.3mf")
    before = _state(folder)
    pane, page, ctl = w.details.history, w.details.pages["History"], w.file_history
    _show_tab(app, w)
    assert page.showing_content
    assert pane.status.text() == history.NO_HISTORY_TEXT
    assert _rows(w) == [["v1", "Working copy", "No snapshot yet"]]
    assert pane.snapshot_button.isEnabled() and not pane.compare_button.isEnabled()
    assert pane.image.pixmap() is not None and not pane.image.pixmap().isNull()  # its stored thumbnail
    assert pane.diff_caption.text() == "This is the first version: there is none before it."

    pane.snapshot_button.click()
    got = _results(app, w, 3)  # the snapshot, the list again, the newest version's details
    assert got[0]["ok"] and got[0]["data"]["new"]
    assert w.statusBar().currentMessage() == "Took snapshot v1 of box.3mf."
    assert _rows(w) == [["v1", "Snapshot", ""]]
    assert pane.status.text().startswith("The snapshots of this file in your SolidSeas data folder")
    assert not pane.compare_button.isEnabled()  # the snapshot is the file as it is now
    assert _state(folder) == before  # nothing beside the file

    pane.snapshot_button.click()  # unchanged: nothing new is stored
    got = _results(app, w, 3)
    assert not got[0]["data"]["new"]
    assert (
        w.statusBar().currentMessage()
        == "box.3mf has not changed since its newest snapshot: nothing new was stored."
    )

    path.write_bytes(part(31))
    ctl.load()
    _results(app, w, 2)
    assert _rows(w) == [["v2", "Working copy", "Changed since the newest snapshot"], ["v1", "Snapshot", ""]]
    assert pane.chosen == 0
    assert pane.diff_caption.text().startswith("Changes from v1 (snapshot, ")
    diff = _diff(w)
    assert ["  Volume", "6,000 mm3", "6,200 mm3"] in diff["Geometry"]

    pane.choose(1)
    _results(app, w, 1)
    assert pane.diff_caption.text() == "This is the first version: there is none before it."
    assert pane.compare_button.isEnabled()
    pane.compare_button.click()
    got = _results(app, w, 1)
    assert got[0]["ok"] and got[0]["diff"]["to"]["kind"] == "working"
    assert pane.diff_caption.text().endswith("to v2, the working copy.")
    assert ["  Size in z", "30 mm", "31 mm"] in _diff(w)["Geometry"]


@needs_qt
def test_a_component_inside_its_assembly_has_no_history(app, window):
    from solidseas_app.viewer.reading import Source

    w = window
    w.file_history.document_shown(
        {"path": "a.SLDASM"}, Source("/x/a.SLDASM", "/x", ("VirtualComp/P-sldprt",))
    )
    assert w.details.pages["History"].message_text.endswith("History covers files.")
    assert w.file_history.path is None


@needs_git
@needs_qt
def test_a_file_in_git_lists_its_commits(app, window, tmp_path):
    (tmp_path / "home").mkdir()
    repo = Repo(tmp_path / "Job", tmp_path / "home")
    repo.write("box.3mf", part(30))
    repo.commit("First box")
    repo.write("box.3mf", part(31))
    repo.commit("Make it taller")
    before = _state(repo.root)
    w = window
    _open(app, w, repo.root)
    _select(app, w, "box.3mf")
    pane = w.details.history
    _show_tab(app, w)
    assert _rows(w) == [["v2", "Git commit", "Make it taller"], ["v1", "Git commit", "First box"]]
    assert pane.status.text().startswith("The commits that changed this file in its Git repository")
    assert not pane.snapshot_button.isEnabled()  # its versions are its commits
    assert pane.diff_caption.text().startswith("Changes from v1 (Git commit, ")
    assert ["  Size in z", "30 mm", "31 mm"] in _diff(w)["Geometry"]
    assert _state(repo.root) == before


@needs_qt
def test_a_library_version_shows_the_note_of_the_check_in_that_stored_it(app, tmp_path):
    from solidseas import pdm
    from solidseas_app.viewer import history

    cad = tmp_path / "CAD"
    job = cad / "Jobs" / "1042"
    job.mkdir(parents=True)
    path = job / "box.3mf"
    path.write_bytes(part(30))
    (job / "lid.3mf").write_bytes(part(5))
    vault = pdm.init(cad)
    vault.checkin([cad], "baseline")
    (cad / "Jobs" / ".dot" / "x.3mf").parent.mkdir()
    (cad / "Jobs" / ".dot" / "x.3mf").write_bytes(part(7))
    # a whole-library check-in written the old way, naming every unchanged file
    states = vault.status(cad, unchanged=True).files
    entries, _failed = vault._store_files(states, "dot-named files", removals=True, unchanged=True)
    vault._new_checkin(entries, "dot-named files", who="D. M.")
    vault.checkin([cad], "issued for quote", revision="C", who="Pat")
    rows = history.file_history(str(path)).rows
    assert [(r.label, r.note, r.revision, r.state) for r in rows] == [("v1", "baseline", "C", None)]
    assert history.note_text(rows[0]) == "baseline (rev C)"
    assert len(rows[0].labels) == 1 and rows[0].labels[0].startswith("Revision C, ")
    assert rows[0].labels[0].endswith(" by Pat")
    pane = history.HistoryPane()
    pane.show_rows(rows)
    item = pane.tree.topLevelItem(0)
    assert item.text(3) == "baseline (rev C)"
    assert "baseline" in item.toolTip(0) and "Revision C, " in item.toolTip(0)
    assert "dot-named files" not in item.toolTip(0)
    pane.deleteLater()
