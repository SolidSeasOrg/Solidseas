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
    _wait(app, lambda: w.listing_info is not None and w.pdm.idle)


def _menu(app, w) -> None:
    """The PDM menu brought up to date, once the lookups it starts have answered."""
    w.pdm.update_actions()
    _wait(app, lambda: w.pdm.idle)


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
    _menu(app, w)
    assert _visible(w)[:3] == ["Check &In...", "&Changes", "Check &Project (choose a folder in a project)"]


@needs_qt
def test_the_library_and_the_project_are_looked_up_off_the_ui_thread(app, window, tmp_path, monkeypatch):
    """A folder on a share that is slow to answer never holds the window: the library and
    the chosen folder's project are looked up in the controller's pool, and the menu
    offers Make This Folder a Library only once the lookup says there is none."""
    import threading

    from solidseas_app.viewer import pdmaction

    cad = library(tmp_path, make=False)
    w = window
    gate = threading.Event()
    threads: list = []
    real_find, real_folders = pdm.find_library, pdmaction.project_folders

    def find_library(folder):
        threads.append(threading.current_thread())
        assert gate.wait(30)
        return real_find(folder)

    def project_folders(path):
        threads.append(threading.current_thread())
        return real_folders(path)

    monkeypatch.setattr(pdm, "find_library", find_library)
    monkeypatch.setattr(pdmaction, "project_folders", project_folders)
    w.open_folder(str(cad / "Jobs"))
    _wait(app, lambda: w.listing_info is not None)
    assert not w.pdm.answered and _visible(w) == []  # the lookup has not answered: nothing yet
    gate.set()
    _wait(app, lambda: w.pdm.idle)
    assert _visible(w) == ["&Make This Folder a Library..."] and w.pdm.library is None

    pdm.init(cad)
    gate.clear()
    w.open_folder(str(cad / "Jobs"))
    _wait(app, lambda: w.listing_info is not None)
    assert _visible(w) == []
    gate.set()
    _wait(app, lambda: w.pdm.idle)
    assert w.pdm.library == str(cad)
    assert w.pdm.act_check.text() == "Check &Project (choose a folder in a project)"
    w.tree.setCurrentItem(w._folders["1042"])  # the project's lookup starts on its own
    assert not w.pdm.idle and w.pdm.act_check.text() == "Check &Project (looking for the project...)"
    _wait(app, lambda: w.pdm.idle)
    assert w.pdm.act_check.isEnabled() and w.pdm.act_check.text() == "Check &Project"
    assert threads and threading.main_thread() not in threads


@needs_qt
def test_the_right_click_menus_never_open_the_library_on_the_ui_thread(app, window, tmp_path, monkeypatch):
    """The file list's and the folder tree's right-click menus are built from what the
    lookups answered: the vault is opened, and a folder's project found, only in a
    worker thread."""
    import threading

    from solidseas_app.viewer import pdmaction

    cad = library(tmp_path)
    vault = pdm.open(cad)
    vault.library.add(cad / "Jobs" / "1042" / "lid.3mf", "LID")
    threads: list = []
    real_open, real_folders = pdm.open, pdmaction.project_folders

    def open_vault(path):
        threads.append(threading.current_thread())
        return real_open(path)

    def project_folders(path):
        threads.append(threading.current_thread())
        return real_folders(path)

    monkeypatch.setattr(pdm, "open", open_vault)
    monkeypatch.setattr(pdmaction, "project_folders", project_folders)
    w = window
    _open(app, w, cad)
    assert threads and threading.main_thread() not in threads
    menu = w.list_menu(w.proxy.mapFromSource(w.model.index(w.model.find("Jobs/1042/box.3mf"), 0)))
    assert "Add box.3mf to the Library..." in _texts(menu) and "Check In box.3mf..." in _texts(menu)
    menu = w.list_menu(w.proxy.mapFromSource(w.model.index(w.model.find("Library/lid.3mf"), 0)))
    assert "Check In lid.3mf..." in _texts(menu) and not any("to the Library" in t for t in _texts(menu))
    menu = w.folder_menu(w._folders["Jobs/1042"])
    assert _texts(menu)[-1] == "Check Project (looking for the project...)"
    _wait(app, lambda: w.pdm.idle)
    assert _texts(w.folder_menu(w._folders["Jobs/1042"]))[-1] == "Check Project"
    # the items not known (a lookup that could not read them): Add waits for a reading
    w.pdm.item_files = None
    menu = w.list_menu(w.proxy.mapFromSource(w.model.index(w.model.find("Jobs/1042/box.3mf"), 0)))
    (add,) = [a for a in menu.actions() if "to the Library" in a.text()]
    assert add.text() == "Add box.3mf to the Library... (reading the library's items...)"
    assert not add.isEnabled()
    _wait(app, lambda: w.pdm.item_files is not None)
    assert w.pdm.is_item(str(cad / "Library" / "lid.3mf"))
    assert threading.main_thread() not in threads


@needs_qt
def test_closing_does_not_wait_for_a_lookup(app, window, tmp_path, monkeypatch):
    """A lookup only reads, so a window that closes while one is held up by a slow share
    cancels it and does not wait: its answer, when it comes, changes nothing."""
    import threading

    cad = library(tmp_path)
    gate = threading.Event()
    real_find = pdm.find_library

    def find_library(folder):
        assert gate.wait(30)
        return real_find(folder)

    monkeypatch.setattr(pdm, "find_library", find_library)
    w = window
    w.open_folder(str(cad / "Jobs"))
    _wait(app, lambda: w.listing_info is not None)
    assert not w.pdm.answered
    start = time.monotonic()
    assert w.shutdown(timeout_ms=5000)
    assert time.monotonic() - start < 4
    gate.set()
    end = time.monotonic() + 2
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    assert w.pdm.library is None and not w.pdm.answered  # the late answer was ignored


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
    _wait(app, lambda: w.model.find("box v1.3mf") is not None)  # the list was read again

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


@pytest.fixture
def fake_drive_q(monkeypatch):
    """Drive Q: does not exist, whatever this machine has: stored Q:\\ paths are never touched."""
    from solidseas.resolve import gateway as gateway_mod

    real = gateway_mod._drive_type

    def drive_type(root: str) -> int:
        return gateway_mod.DRIVE_NO_ROOT_DIR if root.upper().startswith("Q:") else real(root)

    monkeypatch.setattr(gateway_mod, "_drive_type", drive_type)


@needs_qt
def test_a_folder_s_menu_and_check_project(app, window, tmp_path, fake_drive_q):
    from builders import TreeXml, part_with_creation_time, resolving_assembly

    ct = 1_700_000_000
    cad = tmp_path / "CAD"
    a = cad / "Jobs" / "A"
    (a / "parts").mkdir(parents=True)
    (a / "parts" / "p.SLDPRT").write_bytes(part_with_creation_time(ct))
    (cad / "Library").mkdir(parents=True)
    (cad / "Library" / "bolt.SLDPRT").write_bytes(part_with_creation_time(ct))
    (a / "deep").mkdir()
    (a / "deep" / "far.SLDPRT").write_bytes(part_with_creation_time(ct))  # out of the search
    t = TreeXml()
    t.top("m1")
    stored_paths = ["Q:\\A\\parts\\p.SLDPRT", "Q:\\CAD\\Library\\bolt.SLDPRT", "none.SLDPRT", "far.SLDPRT"]
    for i, stored in enumerate(stored_paths, start=2):
        t.file(str(i), stored, swCreationTime=str(ct))
        t.model(f"m{i}", str(i))
        t.ref("m1", f"c{i}", 1, f"m{i}")
    (a / "asm.SLDASM").write_bytes(resolving_assembly(t))
    pdm.init(cad)
    w = window
    _open(app, w, cad / "Jobs")
    _menu(app, w)
    assert w.pdm.act_check.text().endswith("(choose a folder in a project)")
    menu = w.folder_menu(w._folders["A"])  # the folder tree's right-click menu
    # A's project has not been looked up: the entry waits for the lookup the menu started
    assert [a.text() for a in menu.actions()] == [
        "Check In A...",
        "Changes in A",
        "Check Project (looking for the project...)",
    ]
    assert not menu.actions()[2].isEnabled()
    _wait(app, lambda: w.pdm.idle)
    menu = w.folder_menu(w._folders["A"])
    assert [a.text() for a in menu.actions()] == ["Check In A...", "Changes in A", "Check Project"]
    assert menu.actions()[2].isEnabled()
    menu = w.folder_menu(w._folders[""])  # Jobs, a section: no project
    assert [a.text() for a in menu.actions()] == ["Check In Jobs...", "Changes in Jobs"]
    w.tree.setCurrentItem(w._folders["A"])
    assert w.current_folder() == str(a)
    _menu(app, w)
    assert w.pdm.act_check.isEnabled() and w.pdm.act_check.text() == "Check &Project"

    dialog = w.pdm.check_project(str(a))
    got = _results(app, w, 1, 0)
    assert got[0]["ok"], got[0]
    assert dialog.line.text().startswith("Jobs/A: 4 references in 3 documents.")
    assert dialog.line.text().endswith("3 findings keep the project from being self-contained.")
    tops = _tops(dialog.tree)
    assert tops == [
        "Not found where SOLIDWORKS looks (2)",
        "Found only outside the project (1)",
        "Found in the project (1)",
    ]
    outside = dialog.tree.topLevelItem(1).child(0)
    assert outside.text(0) == "asm.SLDASM" and outside.text(1) == "Q:\\CAD\\Library\\bolt.SLDPRT"
    assert outside.text(2) == f"{cad / 'Library' / 'bolt.SLDPRT'} (in the library)"
    missing = dialog.tree.topLevelItem(0)
    assert {missing.child(i).text(1): missing.child(i).text(2) for i in range(2)} == {
        "none.SLDPRT": "Not found",
        "far.SLDPRT": f"Out of SOLIDWORKS' search: {a / 'deep' / 'far.SLDPRT'}",
    }
    dialog.reject()


# --------------------------------------------------------------------------- the library of common parts
def _kind(app, w, kind: str, start: int) -> dict:
    """The first result of ``kind`` shown since ``start``."""
    _wait(app, lambda: any(r.get("kind") == kind for r in w.test_shown[start:]))
    return next(r for r in w.test_shown[start:] if r.get("kind") == kind)


def _library(app, w, start: int) -> dict:
    """The Library window's newest reading, once it is shown."""
    _wait(app, lambda: any(r.get("kind") == "library" and r["latest"] for r in w.test_shown[start:]))
    return next(r for r in w.test_shown[start:] if r.get("kind") == "library" and r["latest"])


def _later(path: Path) -> None:
    """A written file's time moved on, so a size and time check sees the change."""
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))


def _texts(menu) -> list[str]:
    return [a.text() for a in menu.actions()]


def test_the_library_words():
    from solidseas_app.viewer import pdmlibrary

    row = {"copy": "unchanged", "behind": False, "number": 1, "newest_number": 1}
    assert pdmlibrary.copy_state(row) == "Unchanged"
    row.update(behind=True, newest_number=2)
    assert pdmlibrary.copy_state(row) == "Behind: the copy is v1, the library has v2"
    row["copy"] = "edited"
    assert pdmlibrary.copy_state(row) == "Edited in the project. Behind: the copy is v1, the library has v2"
    assert pdmlibrary.copy_state({"copy": "gone", "behind": True}) == "Gone from the project"
    item = {"exists": True, "stored": True, "version": {"number": 3}}
    assert pdmlibrary.versions_text(item) == "3"
    assert pdmlibrary.versions_text({**item, "stored": False}) == "3, changed since"
    assert pdmlibrary.versions_text({**item, "exists": False}) == "File gone"
    fix = {"copied": [{}, {}], "failed": [{"destination": "/p/a.SLDPRT", "message": "it is there"}]}
    assert pdmlibrary.fix_line(fix) == (
        "Made 2 copies in the project. 1 copy could not be made: a.SLDPRT (it is there)."
    )
    assert pdmlibrary.problem_text({"detail": {"rule": "exists"}}).startswith(
        "A file of that name is already"
    )


@needs_qt
def test_the_library_window_adds_uses_and_updates_items(app, window, tmp_path, monkeypatch):
    cad = library(tmp_path, make=False)
    job = cad / "Jobs" / "1042"
    other = cad / "Jobs" / "1043"
    other.mkdir()
    (other / "base.3mf").write_bytes(part(2))
    pdm.init(cad)
    w = window
    _open(app, w, job)
    w.pdm.update_actions()
    assert "&Library of Common Parts..." in _visible(w) and w.pdm.act_library.isEnabled()
    _select(app, w, "box.3mf")
    menu = w.list_menu(w.proxy.mapFromSource(w.model.index(w.model.find("box.3mf"), 0)))
    assert "Add box.3mf to the Library..." in _texts(menu)
    box = (job / "box.3mf").read_bytes()

    dialog = w.pdm.open_library()
    got = _library(app, w, 0)
    assert got["ok"] and got["items"] == [] and got["projects"] == ["Jobs/1042", "Jobs/1043"]
    assert dialog.line.text().startswith("The library has no items yet.")
    assert not dialog.use_button.isEnabled() and dialog.add_button.isEnabled()

    # Add to Library, from the file selected in the list
    start = len(w.test_shown)
    add = w.pdm.add_selected()
    assert "box.3mf itself is not changed" in add.line.text()
    add.description.setText("Box  30 mm")
    add.ok.click()
    got = _kind(app, w, "library_add", start)
    assert got["ok"], got
    assert got["text"] == (
        "Added box.3mf to the library as SS-00001. The copy is Library/box.3mf; box.3mf itself is unchanged."
    )
    assert (cad / "Library" / "box.3mf").read_bytes() == box and (job / "box.3mf").read_bytes() == box
    _library(app, w, start)
    assert _tops(dialog.items) == ["SS-00001"]
    top = dialog.items.topLevelItem(0)
    assert [top.text(c) for c in range(6)] == ["SS-00001", "Box 30 mm", "Library/box.3mf", "1", "0", "No"]
    assert w.pdm.is_item(str(cad / "Library" / "box.3mf")) and not w.pdm.is_item(str(job / "box.3mf"))
    start = len(w.test_shown)
    w.pdm.add_now(str(job / "box.3mf"))  # again: a file of that name is in Library already
    got = _kind(app, w, "library_add", start)
    assert not got["ok"] and got["text"] == (
        "box.3mf was not added to the library. A file of that name is already there, and a copy never "
        "replaces a file, so nothing was copied."
    )

    # Use in Project, into a folder of 1043
    dialog.items.setCurrentItem(top)
    assert dialog.use_button.isEnabled() and dialog.show_button.isEnabled()
    assert not dialog.update_button.isEnabled()
    use = w.pdm.use_in_project()
    assert use.project.currentText() == "Jobs/1042"  # the project of the opened folder
    assert "never replaced" in use.line.text()
    use.project.setCurrentIndex(1)
    use.to.setText("parts")
    start = len(w.test_shown)
    use.ok.click()
    got = _kind(app, w, "library_use", start)
    copy = other / "parts" / "box.3mf"
    assert got["ok"] and got["text"] == f"Copied SS-00001 v1 to {copy}."
    assert copy.read_bytes() == box and w.statusBar().currentMessage() == got["text"]
    start = len(w.test_shown)
    w.pdm.use_now("SS-00001", "Jobs/1043", "parts")  # never over a file
    got = _kind(app, w, "library_use", start)
    assert not got["ok"] and "never replaces a file" in got["text"]
    _library(app, w, start)
    assert dialog.items.topLevelItem(0).text(4) == "1"

    # the library part changes: the copy is behind
    (cad / "Library" / "box.3mf").write_bytes(part(40))
    _later(cad / "Library" / "box.3mf")
    start = len(w.test_shown)
    w.pdm.refresh_library()
    _library(app, w, start)
    assert dialog.items.topLevelItem(0).text(5) == "1 of 1 copies"
    assert dialog.items.topLevelItem(0).text(3) == "1, changed since"
    dialog.items.setCurrentItem(dialog.items.topLevelItem(0))
    assert dialog.update_button.isEnabled()
    dialog.show_button.click()
    assert dialog.copies_line.text() == "SS-00001 is copied into 1 project (1 copy):"
    row = dialog.copies.topLevelItem(0)
    assert [row.text(c) for c in range(2)] == ["Jobs/1043", "Jobs/1043/parts/box.3mf"]
    assert row.text(2).startswith("Behind: the copy is v1, the library has ")

    # Update Copies: an edited copy only when the person says so
    copy.write_bytes(part(7))
    _later(copy)
    edited = copy.read_bytes()
    start = len(w.test_shown)
    w.pdm.refresh_library()
    _library(app, w, start)
    dialog.items.setCurrentItem(dialog.items.topLevelItem(0))
    asked: list = []
    monkeypatch.setattr(w.pdm, "ask", lambda title, text: asked.append(text) or False)
    w.pdm.update_copies()
    assert "Replace the edited copies with the library's version too?" in asked[0]
    assert "Jobs/1043/parts/box.3mf" in asked[0]
    assert (
        dialog.copies_line.text() == "Nothing was updated: every copy of SS-00001 that is behind was edited."
    )
    assert copy.read_bytes() == edited
    monkeypatch.setattr(w.pdm, "ask", lambda title, text: True)
    start = len(w.test_shown)
    w.pdm.update_copies()
    got = _kind(app, w, "library_update", start)
    assert got["text"] == "Updated 1 copy of SS-00001. Each was kept as a version first."
    assert copy.read_bytes() == (cad / "Library" / "box.3mf").read_bytes()
    log = pdm.open(cad).log(copy)["versions"]
    assert sum(1 for v in log if v["source"] == "vault") == 3  # the copy, as edited, and as updated
    _library(app, w, start)
    assert dialog.items.topLevelItem(0).text(5) == "No"
    dialog.reject()


@needs_qt
def test_the_library_window_edits_an_item(app, window, tmp_path):
    cad = library(tmp_path)
    vault = pdm.open(cad)
    vault.library.add(cad / "Jobs" / "1042" / "box.3mf", "SS-00001", "box")
    vault.library.add(cad / "Jobs" / "1042" / "lid.3mf", "LID", "lid")
    vault.library.use("SS-00001", cad / "Jobs" / "1042", to="parts")
    w = window
    _open(app, w, cad)
    dialog = w.pdm.open_library()
    _library(app, w, 0)
    assert not dialog.edit_button.isEnabled()  # no item chosen
    assert dialog.choose("SS-00001") and dialog.edit_button.isEnabled()
    edit = w.pdm.edit_item()
    assert edit.item.text() == "SS-00001" and edit.description.text() == "box"
    assert "SS-00001 still finds the item" in edit.line.text()
    assert not edit.ok.isEnabled()  # nothing changed yet
    edit.item.setText("LID")  # another item's number
    start = len(w.test_shown)
    edit.ok.click()
    got = _kind(app, w, "library_edit", start)
    assert not got["ok"]
    assert got["text"] == (
        "SS-00001 was not changed. Another library item has or had that number. Choose another."
    )
    edit = w.pdm.edit_item()
    edit.item.setText("BOX-30")
    edit.description.setText("Box  30 mm")
    start = len(w.test_shown)
    edit.ok.click()
    got = _kind(app, w, "library_edit", start)
    assert got["ok"] and got["text"] == "SS-00001 is BOX-30 now. SS-00001 still finds it."
    _library(app, w, w.test_shown.index(got))  # the reading the edit asked for
    assert _tops(dialog.items) == ["BOX-30", "LID"]
    row = dialog.chosen_item()  # the edited item stays chosen
    assert row["item"] == "BOX-30" and row["description"] == "Box 30 mm" and row["aliases"] == ["SS-00001"]
    assert dialog.items.topLevelItem(0).text(4) == "1"  # its copy, made as SS-00001, is still its
    dialog.search.setText("ss-00001")  # an old number finds it
    assert [dialog.items.topLevelItem(i).isHidden() for i in range(2)] == [False, True]
    dialog.search.setText("")
    edit = w.pdm.edit_item()
    edit.description.setText("Box, 30 mm high")
    start = len(w.test_shown)
    edit.ok.click()
    assert _kind(app, w, "library_edit", start)["text"] == "Changed the description of BOX-30."
    assert pdm.open(cad).library.item("SS-00001").description == "Box, 30 mm high"
    dialog.reject()


@needs_qt
def test_the_candidates_tab_adds_a_shared_part(app, window, tmp_path):
    cad = library(tmp_path, make=False)
    for job in ("1042", "1043"):
        (cad / "Jobs" / job).mkdir(parents=True, exist_ok=True)
        (cad / "Jobs" / job / "bolt.sldprt").write_bytes(b"the same bolt")
    pdm.init(cad)
    before = _state(cad / "Jobs")
    w = window
    _open(app, w, cad / "Jobs")
    dialog = w.pdm.open_library()
    _library(app, w, 0)
    start = len(w.test_shown)
    dialog.tabs.setCurrentIndex(1)
    got = _kind(app, w, "candidates", start)
    assert got["ok"] and _tops(dialog.candidates_tree) == ["bolt.sldprt"]
    row = dialog.candidates_tree.topLevelItem(0)
    assert [row.text(c) for c in range(4)] == ["bolt.sldprt", "2", "2", "Jobs/1042, Jobs/1043"]
    assert dialog.candidates_line.text().startswith("1 part sits in two or more projects")
    assert not dialog.candidate_button.isEnabled()
    dialog.candidates_tree.setCurrentItem(row)
    assert dialog.candidate_button.isEnabled()
    add = w.pdm.add_candidate()
    assert add.path == str(cad / "Jobs" / "1042" / "bolt.sldprt")
    add.item.setText("BOLT-1")
    start = len(w.test_shown)
    add.ok.click()
    got = _kind(app, w, "library_add", start)
    assert got["ok"] and got["data"]["item"]["item"] == "BOLT-1"
    got = _kind(app, w, "candidates", start)  # looked for again: the library holds it now
    assert got["data"]["candidates"] == [] and dialog.candidates_line.text().startswith("No part sits")
    assert _state(cad / "Jobs") == before  # the projects' files are as they were
    assert (cad / "Library" / "bolt.sldprt").read_bytes() == b"the same bolt"
    dialog.reject()


@needs_qt
def test_the_candidates_tab_adds_several_parts_at_once(app, window, tmp_path, monkeypatch):
    cad = library(tmp_path, make=False)
    for job in ("1042", "1043"):
        (cad / "Jobs" / job).mkdir(parents=True, exist_ok=True)
        (cad / "Jobs" / job / "bolt.sldprt").write_bytes(b"the same bolt")
        (cad / "Jobs" / job / "nut.sldprt").write_bytes(b"the same nut")
    pdm.init(cad)
    before = _state(cad / "Jobs")
    w = window
    _open(app, w, cad / "Jobs")
    dialog = w.pdm.open_library()
    _library(app, w, 0)
    start = len(w.test_shown)
    dialog.tabs.setCurrentIndex(1)
    _kind(app, w, "candidates", start)
    tree = dialog.candidates_tree
    assert sorted(_tops(tree)) == ["bolt.sldprt", "nut.sldprt"]
    tree.setCurrentItem(tree.topLevelItem(0))
    assert dialog.candidate_button.text() == "Add to Library..." and dialog.chosen_candidate() is not None
    tree.selectAll()
    assert dialog.candidate_button.isEnabled() and dialog.candidate_button.text() == "Add 2 to Library..."
    assert dialog.chosen_candidate() is None and len(dialog.chosen_candidates()) == 2
    asked: list = []
    monkeypatch.setattr(w.pdm, "ask", lambda title, text: asked.append(text) or False)
    assert w.pdm.add_candidate() is None
    assert asked[0].startswith("Add 2 parts to the library?") and "No project file changes" in asked[0]
    assert pdm.open(cad).library.items() == []  # the answer was no
    monkeypatch.setattr(w.pdm, "ask", lambda title, text: True)
    start = len(w.test_shown)
    w.pdm.add_candidate()
    got = _kind(app, w, "library_add_many", start)
    assert got["ok"] and [d["ok"] for d in got["done"]] == [True, True]
    names = [os.path.basename(p) for p in got["paths"]]
    assert got["text"] == "Added 2 parts to the library: SS-00001, SS-00002."
    items = {i.path: i.id for i in pdm.open(cad).library.items()}
    assert items == {f"Library/{names[0]}": "SS-00001", f"Library/{names[1]}": "SS-00002"}
    got = _kind(app, w, "candidates", start)  # looked for again: the library holds both now
    assert got["data"]["candidates"] == []
    assert _state(cad / "Jobs") == before
    dialog.reject()


@needs_qt
def test_check_project_makes_the_planned_copies(app, window, tmp_path, monkeypatch, fake_drive_q):
    from builders import TreeXml, part_with_creation_time, resolving_assembly

    ct = 1_700_000_000
    cad = tmp_path / "CAD"
    a = cad / "Jobs" / "A"
    a.mkdir(parents=True)
    (cad / "Library").mkdir(parents=True)
    bolt = part_with_creation_time(ct)
    (cad / "Library" / "bolt.SLDPRT").write_bytes(bolt)
    t = TreeXml()
    t.top("m1")
    t.file("2", "Q:\\CAD\\Library\\bolt.SLDPRT", swCreationTime=str(ct))
    t.model("m2", "2")
    t.ref("m1", "c2", 1, "m2")
    (a / "asm.SLDASM").write_bytes(resolving_assembly(t))
    asm = (a / "asm.SLDASM").read_bytes()
    vault = pdm.init(cad)
    vault.library.add(cad / "Library" / "bolt.SLDPRT", "BOLT-1")
    w = window
    _open(app, w, a)
    dialog = w.pdm.check_project(str(a))
    got = _kind(app, w, "check", 0)
    assert got["ok"] and dialog.make_button.isEnabled()
    assert _tops(dialog.tree)[0] == "Found only outside the project (1)"

    plan = w.pdm.plan_copies(dialog)
    assert _tops(plan.tree) == ["Copies to make (1)"]
    row = plan.tree.topLevelItem(0).child(0)
    assert [row.text(c) for c in range(3)] == [
        str(cad / "Library" / "bolt.SLDPRT"),
        "bolt.SLDPRT",
        "Used by asm.SLDASM; found in the library; library item BOLT-1",
    ]
    assert plan.ok.text() == "Make 1 Copy" and plan.ok.isEnabled()
    asked: list = []
    monkeypatch.setattr(w.pdm, "ask", lambda title, text: asked.append(text) or False)
    plan.ok.click()
    assert asked[0].startswith("Copy 1 file into Jobs/A?")
    assert "Nothing already in the project is replaced" in asked[0]
    assert not (a / "bolt.SLDPRT").exists()  # the answer was no

    plan = w.pdm.plan_copies(dialog)
    monkeypatch.setattr(w.pdm, "ask", lambda title, text: True)
    start = len(w.test_shown)
    plan.ok.click()
    got = _kind(app, w, "check", start)
    assert got["ok"] and got["fix"]["copied"][0]["item"] == "BOLT-1"
    assert (a / "bolt.SLDPRT").read_bytes() == bolt and (a / "asm.SLDASM").read_bytes() == asm
    assert dialog.line.text().startswith("Made 1 copy in the project. Jobs/A: 1 reference in 2 documents.")
    assert dialog.line.text().endswith("The project holds every file its documents reference.")
    assert _tops(dialog.tree) == ["Found in the project (1)"]
    links = pdm.open(cad).library.updates(all_links=True)["links"]
    assert [(r["item"], r["path"]) for r in links] == [("BOLT-1", "Jobs/A/bolt.SLDPRT")]
    assert not dialog.make_button.isEnabled()
    dialog.reject()
