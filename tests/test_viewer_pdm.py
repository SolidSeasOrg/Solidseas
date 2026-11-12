"""The viewer's PDM menu (``solidseas_app.viewer.pdmaction``) and the History tab of a
file in a library (``solidseas_app.viewer.history``).

Every library is made in ``tmp_path``: a folder ``CAD`` with ``Jobs/1042`` holding
synthetic 3MF boxes (``mesh_writers``). The project check builds crafted assemblies
beside copies of o02 (``builders``), as ``test_pdm_check.py`` does. The dialogs open
without blocking; the one confirmation goes through ``PdmController.ask``, which the
tests stand in for.
"""

import os
import time
from pathlib import Path

import pytest

from mesh_writers import png, threemf
from model_writers import box
from solidseas import pdm, versions

try:
    import PySide6.QtWidgets  # noqa: F401

    HAVE_QT = True
except ImportError:  # pragma: no cover - CI installs PySide6
    HAVE_QT = False

needs_qt = pytest.mark.skipif(not HAVE_QT, reason="PySide6 is not installed")


def part(height: float) -> bytes:
    """A 3MF box 10 x 20 x ``height`` mm with a stored thumbnail."""
    return threemf(box(10.0, 20.0, height), thumbnail=png(16, 12))


def _state(folder: Path) -> list[tuple]:
    """Every file below ``folder`` but the library's own ``.solidseas`` folder."""
    return sorted(
        (str(p.relative_to(folder)), p.stat().st_size, p.stat().st_mtime_ns)
        for p in folder.rglob("*")
        if ".solidseas" not in p.relative_to(folder).parts
    )


def library(tmp_path: Path, *, make: bool = True) -> Path:
    cad = tmp_path / "CAD"
    job = cad / "Jobs" / "1042"
    job.mkdir(parents=True)
    (job / "box.3mf").write_bytes(part(30))
    (job / "lid.3mf").write_bytes(part(5))
    if make:
        pdm.init(cad)
    return cad


# --------------------------------------------------------------------------- without a window
def test_a_library_file_lists_its_check_ins(tmp_path):
    from solidseas_app.viewer import history

    cad = library(tmp_path)
    path = cad / "Jobs" / "1042" / "box.3mf"
    vault = pdm.open(cad)
    vault.checkin([path], "first box")
    path.write_bytes(part(31))
    vault.checkin([path], "taller", revision="B", state="released")
    got = history.file_history(str(path))
    assert got.library == str(cad)
    rows = got.rows
    assert [(r.label, r.kind, r.note, r.revision, r.state) for r in rows] == [
        ("v2", "vault", "taller", "B", "released"),
        ("v1", "vault", "first box", None, None),
    ]
    assert rows[0].source == "Library" and history.note_text(rows[0]) == "taller (rev B, released)"
    assert history.previous_of(rows, 0) is rows[1]
    path.write_bytes(part(32))
    rows = history.file_history(str(path)).rows
    assert (rows[0].kind, rows[0].note) == (
        "working",
        "Changed since the newest library version, not checked in",
    )
    diff = history.compare_work(str(path), rows[2].ref, rows[1].ref, **rows[1].options())(None, lambda: False)
    assert history.diff_caption(diff["diff"], library=True).startswith("Changes from v1 (library version, ")


def test_a_library_file_with_no_check_in_lists_its_working_copy(tmp_path):
    from solidseas_app.viewer import history

    cad = library(tmp_path)
    got = history.file_history(str(cad / "Jobs" / "1042" / "box.3mf"))
    assert [(r.kind, r.note) for r in got.rows] == [("working", "Not checked in yet")]
    assert got.library == str(cad)


def test_a_project_store_s_snapshots_are_listed_with_the_user_s(tmp_path):
    from solidseas_app.viewer import history

    folder = tmp_path / "Job"
    folder.mkdir()
    path = folder / "box.3mf"
    path.write_bytes(part(30))
    versions.snapshot(path, note="mine")
    time.sleep(1.1)  # the times are to the second
    path.write_bytes(part(31))
    versions.snapshot(path, project=folder, note="the project's")
    got = history.file_history(str(path))
    assert got.library is None
    assert [(r.source, r.note) for r in got.rows] == [
        ("Project snapshot", "the project's"),
        ("Snapshot", "mine"),
    ]
    assert history.previous_of(got.rows, 0) is None  # another store: nothing to compare with
    path.write_bytes(part(32))
    rows = history.file_history(str(path)).rows
    assert rows[0].kind == "working" and rows[0].note == "Changed since the newest snapshot"
    assert history.previous_of(rows, 0) is rows[1]


def test_the_words(tmp_path):
    from solidseas_app.viewer import pdmaction

    cad = library(tmp_path)
    st = pdm.open(cad).status(cad / "Jobs")
    assert pdmaction.status_line(st, "Jobs") == (
        "2 files in Jobs changed since the newest versions in the library: 2 new. 0 files unchanged."
    )
    pdm.open(cad).checkin([cad], "all")
    st = pdm.open(cad).status(cad)
    assert pdmaction.status_line(st, "CAD") == (
        "Nothing has changed in CAD since the newest versions in the library (2 files checked)."
    )


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
    w.pdm.shown.connect(shown.append)
    w.test_shown = shown
    history: list = []
    w.file_history.shown.connect(history.append)
    w.test_history = history
    yield w
    assert w.shutdown()
    w.close()
    w.deleteLater()
    app.processEvents()


def _open(app, w, folder: Path) -> None:
    w.open_folder(str(folder))
    _wait(app, lambda: w.listing_info is not None)


def _results(app, w, n: int, start: int | None = None) -> list:
    start = len(w.test_shown) if start is None else start
    _wait(app, lambda: len(w.test_shown) >= start + n)
    return w.test_shown[start:]


def _select(app, w, name: str) -> None:
    assert w.select_document(name), name
    _wait(app, lambda: w.file_history.path is not None and w.file_history.path.endswith(name))


def _show_history(app, w) -> None:
    start = len(w.test_history)
    w.file_history.act_history.trigger()
    _wait(app, lambda: len(w.test_history) >= start + 2)  # the list, then the newest version's details


def _rows(w) -> list[list[str]]:
    tree = w.details.history.tree
    return [[tree.topLevelItem(i).text(c) for c in (0, 2, 3)] for i in range(tree.topLevelItemCount())]


def _tops(tree) -> list[str]:
    return [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]


def _visible(w) -> list[str]:
    return [a.text() for a in w.pdm.menu.actions() if a.isVisible() and not a.isSeparator()]


@needs_qt
def test_outside_a_library_the_menu_offers_to_make_one(app, window, tmp_path, monkeypatch):
    cad = library(tmp_path, make=False)
    w = window
    menus = [a.text() for a in w.menuBar().actions()]
    assert menus.index("P&DM") == menus.index("&Tools") + 1 == menus.index("&Settings") - 1
    assert _visible(w) == ["&Make This Folder a Library..."] and not w.pdm.act_make.isEnabled()
    _open(app, w, cad)
    before = _state(cad)
    w.pdm.update_actions()
    assert _visible(w) == ["&Make This Folder a Library..."] and w.pdm.act_make.isEnabled()
    assert w.list_menu(w.proxy.mapFromSource(w.model.index(w.model.find("Jobs/1042/box.3mf"), 0))) is not None
    asked: list = []
    monkeypatch.setattr(w.pdm, "ask", lambda title, text: asked.append(text) or False)
    w.pdm.act_make.trigger()
    assert pdm.find_library(cad) is None  # asked, and the answer was no
    assert asked[0].startswith(f"Make {cad} a library?") and "Nothing else in the folder changes." in asked[0]
    monkeypatch.setattr(w.pdm, "ask", lambda title, text: True)
    w.pdm.act_make.trigger()
    assert pdm.find_library(cad) == str(cad) and w.pdm.library == str(cad)
    assert w.statusBar().currentMessage().startswith("CAD is a library now")
    assert _state(cad) == before  # only its .solidseas folder was added
    w.pdm.update_actions()
    assert _visible(w)[:3] == ["Check &In...", "&Changes", "Check &Project (choose a folder in a project)"]


@needs_qt
def test_check_in_from_the_dialog_and_the_history_of_a_library_file(app, window, tmp_path):
    from solidseas_app.viewer import history

    cad = library(tmp_path)
    path = cad / "Jobs" / "1042" / "box.3mf"
    w = window
    _open(app, w, cad / "Jobs" / "1042")
    assert w.pdm.library == str(cad)
    _select(app, w, "box.3mf")
    before = _state(cad)

    dialog = w.pdm.check_in()
    got = _results(app, w, 1, 0)
    assert [words for words, _p in dialog.choices] == ["The selected file, box.3mf", "The folder 1042"]
    assert got[0]["ok"] and dialog.line.text().startswith("1 file changed since")
    assert _tops(dialog.tree) == ["New (1)"]
    assert not dialog.ok.isEnabled()  # no note yet
    dialog.note.setPlainText("first box")
    dialog.revision.setText("A")
    assert dialog.ok.isEnabled()
    start = len(w.test_shown)
    dialog.ok.click()
    got = _results(app, w, 1, start)
    assert got[0]["kind"] == "checkin" and got[0]["ok"]
    assert w.statusBar().currentMessage() == "Checked in 1 file: 1 new version stored."
    assert _state(cad) == before  # only the library's .solidseas folder was written

    path.write_bytes(part(31))
    w.pdm.checkin_now([str(cad / "Jobs" / "1042")], "taller box", None, "released")
    got = _results(app, w, 1)
    assert w.statusBar().currentMessage() == "Checked in 2 files: 2 new versions stored."

    _show_history(app, w)
    pane = w.details.history
    assert _rows(w) == [["v2", "Library", "taller box (released)"], ["v1", "Library", "first box (rev A)"]]
    assert pane.status.text().startswith("The versions of this file in the library, newest first")
    assert not pane.snapshot_button.isEnabled() and "PDM &gt; Check In" in pane.snapshot_button.toolTip()
    assert pane.diff_caption.text().startswith("Changes from v1 (library version, ")
    assert not pane.warnings.isVisible()
    assert w.pdm.restorable() is not None and w.pdm.restorable()[1].ref == w.file_history.rows[0].ref

    # the warnings line
    w.file_history.source = lambda p: history.FileHistory([], ("the git history was cut short",), None)
    start = len(w.test_history)
    w.file_history.load()
    _wait(app, lambda: len(w.test_history) > start)
    assert pane.warnings.isVisible() and pane.warnings.text() == "Note: The git history was cut short."
    w.file_history.source = None


@needs_qt
def test_restore_a_version_as_a_new_file_and_over_the_file(app, window, tmp_path):
    cad = library(tmp_path)
    folder = cad / "Jobs" / "1042"
    path = folder / "box.3mf"
    vault = pdm.open(cad)
    first = path.read_bytes()
    vault.checkin([path], "first box")
    path.write_bytes(part(31))
    second = path.read_bytes()
    vault.checkin([path], "taller box")
    w = window
    _open(app, w, folder)
    _select(app, w, "box.3mf")
    _show_history(app, w)
    assert w.pdm.restorable()[1].label == "v2"
    start = len(w.test_history)
    w.details.history.choose(1)
    _wait(app, lambda: len(w.test_history) > start)
    w.pdm.update_actions()
    assert w.pdm.act_restore.isEnabled() and w.pdm.act_restore.text() == "&Restore Version..."
    menu = w.list_menu(w.proxy.mapFromSource(w.model.index(w.model.find("box.3mf"), 0)))
    texts = [a.text() for a in menu.actions()]
    assert "Check In box.3mf..." in texts and "Restore v1..." in texts

    dialog = w.pdm.restore_version()
    assert "the file as it is now is kept as a version in the library" in dialog.line.text()
    assert dialog.name.text() == "box v1.3mf" and dialog.as_name is None
    dialog.as_new.setChecked(True)
    start = len(w.test_shown)
    dialog.ok.click()
    got = _results(app, w, 1, start)
    assert got[0]["ok"], got[0]
    assert (folder / "box v1.3mf").read_bytes() == first
    assert path.read_bytes() == second  # the file itself is as it was
    assert w.statusBar().currentMessage() == "Put back v1 as box v1.3mf."

    start = len(w.test_shown)
    w.pdm.restore_now(str(path), "v1")
    got = _results(app, w, 1, start)
    assert path.read_bytes() == first
    assert got[0]["data"]["replaced"]
    log = pdm.open(cad).log(path)
    assert sum(1 for v in log["versions"] if v["source"] == "vault") == 3  # nothing new; v1's again
    assert w.statusBar().currentMessage() == (
        "Put back v1 of box.3mf. The file as it was is kept as a version in the library."
    )


@needs_qt
def test_changes_lists_new_changed_and_gone_files(app, window, tmp_path):
    cad = library(tmp_path)
    folder = cad / "Jobs" / "1042"
    pdm.open(cad).checkin([folder], "both")
    (folder / "box.3mf").write_bytes(part(31))
    (folder / "lid.3mf").unlink()
    (folder / "base.3mf").write_bytes(part(2))
    w = window
    _open(app, w, folder)
    dialog = w.pdm.show_changes()
    _results(app, w, 1, 0)
    assert dialog.line.text() == (
        "3 files in 1042 changed since the newest versions in the library: 1 new, 1 changed, 1 gone. "
        "0 files unchanged."
    )
    assert _tops(dialog.tree) == ["New (1)", "Changed (1)", "Gone (1)"]
    assert dialog.tree.topLevelItem(2).child(0).text(0) == "Jobs/1042/lid.3mf"
    assert dialog.checkin_button.isEnabled()
    dialog.reject()


@needs_qt
def test_a_folder_s_menu_and_check_project(app, window, tmp_path):
    from builders import TreeXml, part_with_creation_time, resolving_assembly

    ct = 1_700_000_000
    cad = tmp_path / "CAD"
    a = cad / "Jobs" / "A"
    (a / "parts").mkdir(parents=True)
    (a / "parts" / "p.SLDPRT").write_bytes(part_with_creation_time(ct))
    (cad / "Library").mkdir(parents=True)
    (cad / "Library" / "bolt.SLDPRT").write_bytes(part_with_creation_time(ct))
    t = TreeXml()
    t.top("m1")
    for i, stored in enumerate(["parts\\p.SLDPRT", "bolt.SLDPRT", "none.SLDPRT"], start=2):
        t.file(str(i), stored, swCreationTime=str(ct))
        t.model(f"m{i}", str(i))
        t.ref("m1", f"c{i}", 1, f"m{i}")
    (a / "asm.SLDASM").write_bytes(resolving_assembly(t))
    pdm.init(cad)
    w = window
    _open(app, w, cad / "Jobs")
    w.pdm.update_actions()
    assert w.pdm.act_check.text().endswith("(choose a folder in a project)")
    menu = w.folder_menu(w._folders["A"])  # the folder tree's right-click menu
    assert [a.text() for a in menu.actions()] == ["Check In A...", "Changes in A", "Check Project"]
    menu = w.folder_menu(w._folders[""])  # Jobs, a section: no project
    assert [a.text() for a in menu.actions()] == ["Check In Jobs...", "Changes in Jobs"]
    w.tree.setCurrentItem(w._folders["A"])
    assert w.current_folder() == str(a)
    w.pdm.update_actions()
    assert w.pdm.act_check.isEnabled() and w.pdm.act_check.text() == "Check &Project"

    dialog = w.pdm.check_project(str(a))
    got = _results(app, w, 1, 0)
    assert got[0]["ok"], got[0]
    assert dialog.line.text().startswith("Jobs/A: 3 references in 2 documents.")
    assert dialog.line.text().endswith("2 findings keep the project from being self-contained.")
    tops = _tops(dialog.tree)
    assert tops == [
        "Not found anywhere (1)",
        "Found only outside the project (1)",
        "Found in the project (1)",
    ]
    outside = dialog.tree.topLevelItem(1).child(0)
    assert outside.text(0) == "asm.SLDASM" and outside.text(1) == "bolt.SLDPRT"
    assert outside.text(2) == f"{cad / 'Library' / 'bolt.SLDPRT'} (in the library)"
    assert dialog.tree.topLevelItem(0).child(0).text(2) == "Not found"
    dialog.reject()
