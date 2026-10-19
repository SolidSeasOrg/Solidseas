"""Open and Show in File Explorer (``solidseas_app.viewer.opening``): a file handed to
the program the system opens it with, and its folder shown with it selected.

No test starts a program or opens a window of the system: ``conftest.py`` replaces
``open_file`` and ``show_file`` for the whole session, and the tests here put
recorders in their place, or call the real ones with Qt's ``openUrl`` and
``subprocess.Popen`` replaced. What Windows does with them is checked on a PC.
"""

import os
import shutil
import sys

import pytest

from solidseas_app.viewer import opening
from support import FIXTURES
from test_viewer import Viewer, _wait, needs_qt

PART = "o02_boxA.SLDPRT"
ASM = "o08_asm_2x_boxA.SLDASM"
DRAWING = "o18_drw_boxA.SLDDRW"


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from solidseas_app.viewer.app import use_system_fonts

    use_system_fonts()
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def opened(monkeypatch):
    """What the window asked to open or show: ("open" or "show", path), in order."""
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(opening, "open_file", lambda path: calls.append(("open", path)))
    monkeypatch.setattr(opening, "show_file", lambda path: calls.append(("show", path)))
    return calls


@pytest.fixture
def folder(tmp_path):
    for name in (PART, "o07_boxB_h31.SLDPRT", ASM, DRAWING):
        shutil.copy2(FIXTURES / name, tmp_path / name)
    (tmp_path / f"~${PART}").write_bytes(b"\x00" * 64)  # a SOLIDWORKS lock file
    return tmp_path


# -- what is offered -------------------------------------------------------------------
def test_a_plain_3d_file_can_be_opened(folder):
    for name in (PART, ASM, DRAWING):
        assert opening.open_problem(str(folder / name)) is None


@pytest.mark.parametrize(
    ("name", "why"),
    [
        ("notes.txt", "not a 3D file"),
        ("run.exe", "not a 3D file"),
        ("run.bat", "not a 3D file"),
        ("o02_boxA.SLDPRT.lnk", "not a 3D file"),
        (f"~${PART}", "a SOLIDWORKS lock file"),
        ("gone.SLDPRT", "not there any more"),
    ],
)
def test_what_is_not_opened_says_why(folder, name, why):
    path = folder / name
    if not path.exists() and why == "not a 3D file":
        path.write_bytes(b"MZ")
    assert opening.open_problem(str(path)) == why


def test_a_place_that_is_not_known_is_not_opened():
    assert opening.open_problem(None) == "its place is not known"
    assert opening.open_problem("") == "its place is not known"
    assert opening.open_problem(PART) == "its place is not known"  # relative: below what?
    assert opening.open_problem(os.path.abspath(PART) + "\x00.exe") == "its place is not known"


def test_a_folder_named_as_a_3d_file_is_not_opened(tmp_path):
    (tmp_path / "box.SLDPRT").mkdir()
    assert opening.open_problem(str(tmp_path / "box.SLDPRT")) == "not a file"


def test_a_link_is_never_followed(folder):
    link = folder / "link.SLDPRT"
    try:
        os.symlink(folder / PART, link)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links cannot be made here")
    assert opening.open_problem(str(link)) == "a link, which SolidSeas never follows"


def test_without_looking_only_the_path_is_judged(folder):
    gone = str(folder / "gone.SLDPRT")
    assert opening.open_problem(gone, look=False) is None  # what enables an action
    assert opening.open_problem(gone) == "not there any more"  # what the action checks
    assert opening.open_problem(str(folder / "run.exe"), look=False) == "not a 3D file"


def test_the_names_say_what_the_system_calls_its_file_manager():
    if os.name == "nt":
        expected = "Show in File Explorer"
    elif sys.platform == "darwin":
        expected = "Show in Finder"
    else:
        expected = "Show in Folder"
    assert opening.show_text() == expected and opening.OPEN_TEXT == "Open"
    assert "SOLIDWORKS" in opening.OPEN_TIP and "can save changes" in opening.OPEN_TIP


# -- how a file is handed over ---------------------------------------------------------
def test_no_test_can_open_a_file_outside_the_viewer(folder):
    """The session's guard (conftest.py) is in place under any test that does not put
    its own recorder there."""
    for start in (opening.open_file, opening.show_file):
        with pytest.raises(AssertionError, match="outside the viewer"):
            start(str(folder / PART))


@pytest.mark.skipif(os.name == "nt", reason="Windows shows the file through the shell's own call")
def test_show_on_macos_selects_the_file_with_the_path_as_one_argument(
    monkeypatch, folder, never_open_a_file_outside
):
    import subprocess

    from solidseas_app.viewer import printing

    started: list = []

    class Popen:
        def __init__(self, args, **kwargs):
            started.append((args, kwargs))

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "Popen", Popen)
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", "x")  # the packaging's own: left out
    path = str(folder / "a; rm -rf ~ $(x).SLDPRT")
    never_open_a_file_outside["show_file"](path)
    ((args, kwargs),) = started
    assert args == ["open", "-R", path] and not kwargs.get("shell")
    assert "_PYI_APPLICATION_HOME_DIR" not in kwargs["env"]
    assert kwargs["env"] == printing.launch_environment()


def test_the_packaged_viewer_starts_through_the_system_with_its_packaging_left_out(monkeypatch, tmp_path):
    """In the packaged viewer the environment a program started through the system
    inherits is the one 3D Print gives its slicer, for the instant of the start, and
    the viewer's own comes back after."""
    bundle = str(tmp_path / "_MEI1234")
    elsewhere = str(tmp_path / "bin")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", bundle, raising=False)
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", "viewer.exe")
    monkeypatch.setenv("QT_PLUGIN_PATH", os.path.join(bundle, "PySide6", "plugins"))
    monkeypatch.setenv("PATH", os.pathsep.join([bundle, elsewhere]))
    before = dict(os.environ)
    seen: dict = {}
    with opening._clean_start():
        seen.update(os.environ)
    assert "_PYI_ARCHIVE_FILE" not in seen and "QT_PLUGIN_PATH" not in seen
    assert seen["PATH"] == elsewhere and seen["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert dict(os.environ) == before


def test_outside_the_packaged_viewer_the_environment_is_left_alone(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setenv("_PYI_SOMETHING", "kept")
    before = dict(os.environ)
    with opening._clean_start():
        assert dict(os.environ) == before


@needs_qt
def test_the_real_open_hands_the_systems_opener_a_file_url(
    app, folder, monkeypatch, never_open_a_file_outside
):
    """Open asks Qt to open the file's URL, as File Explorer's double-click does: never a
    command line."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    asked: list = []
    answer = [True]

    def open_url(url):
        asked.append(url)
        return answer[0]

    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(open_url))
    path = str(folder / PART)
    real = never_open_a_file_outside["open_file"]
    real(path)
    assert asked == [QUrl.fromLocalFile(path)] and asked[0].scheme() == "file"
    answer[0] = False
    with pytest.raises(OSError, match="could not open"):
        real(path)


# -- in the window ---------------------------------------------------------------------
@pytest.fixture
def viewer(app, folder):
    v = Viewer(app)
    v.open(folder)
    yield v
    v.close()


def _texts(menu) -> list[str]:
    return [a.text() for a in menu.actions()]


def _action(menu, text: str):
    (found,) = [a for a in menu.actions() if a.text() == text]
    return found


@needs_qt
def test_open_and_show_are_on_the_toolbar_and_in_the_file_menu(viewer, folder, opened):
    w = viewer.window
    file_menu = w.menuBar().actions()[0].menu().actions()
    for a in (w.act_open_shown, w.act_show_shown):
        assert a in w.toolbar.actions() and a in file_menu and not a.isEnabled()  # nothing shown
    assert file_menu.index(w.act_show_shown) == file_menu.index(w.act_open_shown) + 1
    assert w.act_open_shown.iconText() == "Open" and w.act_show_shown.text() == opening.show_text()
    assert w.act_open_shown.toolTip() == opening.OPEN_TIP
    viewer.select(ASM)
    assert w.act_open_shown.isEnabled() and w.act_show_shown.isEnabled()
    w.act_open_shown.trigger()
    w.act_show_shown.trigger()
    assert opened == [("open", str(folder / ASM)), ("show", str(folder / ASM))]
    assert w.statusBar().currentMessage() == f"{ASM} shown in its folder."


@needs_qt
def test_a_file_gone_since_it_was_listed_is_not_handed_over(viewer, folder, opened):
    w = viewer.window
    viewer.select(PART)
    (folder / PART).unlink()
    w.act_open_shown.trigger()
    assert opened == [] and w.statusBar().currentMessage() == f"{PART} was not opened: not there any more."


@needs_qt
def test_what_the_system_could_not_do_is_said(viewer, folder, monkeypatch):
    w = viewer.window

    def refuse(path):
        raise OSError(f"the system could not open {os.path.basename(path)}")

    monkeypatch.setattr(opening, "open_file", refuse)
    viewer.select(PART)
    assert not w.open_externally(str(folder / PART))
    assert w.statusBar().currentMessage() == f"{PART} was not opened: the system could not open {PART}."


@needs_qt
def test_open_comes_first_in_the_lists_menu(viewer, folder, opened):
    from solidseas_app.viewer.documents import NAME

    w = viewer.window
    w.set_lock_files(True)

    def menu(name: str):
        return w.list_menu(w.proxy.mapFromSource(w.model.index(w.model.find(name), NAME)))

    opens = [opening.OPEN_TEXT, opening.show_text()]
    part = menu(PART)
    assert _texts(part) == [*opens, "", f"3D Print {PART}"]
    assert "can save changes" in part.actions()[0].toolTip()
    drawing = menu(DRAWING)
    assert _texts(drawing) == opens  # a drawing opens; it is not 3D printed
    assert menu(f"~${PART}") is None  # a lock file: nothing to open
    part.actions()[0].trigger()
    part.actions()[1].trigger()
    drawing.actions()[0].trigger()
    assert opened == [
        ("open", str(folder / PART)),
        ("show", str(folder / PART)),
        ("open", str(folder / DRAWING)),
    ]
    part.deleteLater()
    drawing.deleteLater()


@needs_qt
def test_a_components_menu_opens_its_file_and_go_to_file_shows_it_here(viewer, folder, opened):
    from solidseas_app.viewer.details import TABS

    w, d = viewer.window, viewer.window.details
    viewer.select(ASM)
    d.tabs.setCurrentIndex(TABS.index("Components"))
    menu = d.component_menu(d.instances.topLevelItem(0))
    texts = _texts(menu)
    assert texts[:5] == [opening.OPEN_TEXT, opening.show_text(), "", "Go to file", "Show in folder list"]
    assert _action(menu, "Go to file").font().bold()  # what a double-click does
    _action(menu, opening.OPEN_TEXT).trigger()
    _action(menu, opening.show_text()).trigger()
    assert opened == [("open", str(folder / PART)), ("show", str(folder / PART))]
    assert d.title.text() == ASM and not w.history  # the panel stays where it was
    _action(menu, "Go to file").trigger()
    _wait(viewer.app, lambda: d.title.text() == PART)
    assert w.history and len(opened) == 2
    menu.deleteLater()


@pytest.fixture
def no_drive_q(monkeypatch):
    """Drive Q: does not exist, whatever this machine has: stored Q:\\ paths are never touched."""
    from solidseas.resolve import gateway as gateway_mod

    real = gateway_mod._drive_type

    def drive_type(root: str) -> int:
        return gateway_mod.DRIVE_NO_ROOT_DIR if root.upper().startswith("Q:") else real(root)

    monkeypatch.setattr(gateway_mod, "_drive_type", drive_type)


@needs_qt
def test_a_file_not_found_has_open_off_with_the_reason(app, tmp_path, opened, no_drive_q):
    from builders import TreeXml, resolving_assembly

    t = TreeXml()
    t.top("m1")
    t.file("2", "Q:\\Gone\\gone.SLDPRT", swCreationTime="1700000000")
    t.model("m2", "2")
    t.ref("m1", "c2", 1, "m2")
    (tmp_path / "top.SLDASM").write_bytes(resolving_assembly(t))
    v = Viewer(app)
    try:
        v.open(tmp_path)
        v.select("top.SLDASM")
        d = v.window.details
        menu = d.component_menu(d.instance_item("c2-1"))
        first = menu.actions()[:2]
        assert [a.text() for a in first] == [
            f"{opening.OPEN_TEXT} (not found)",
            f"{opening.show_text()} (not found)",
        ]
        assert not any(a.isEnabled() for a in first)
        menu.deleteLater()
    finally:
        v.close()
    assert opened == []


def _user(path: str, root: str) -> dict:
    return {
        "relation": "component",
        "depth": 1,
        "via": [],
        "warnings": [],
        "views": [],
        "uses": [
            {
                "user_configuration": "Default",
                "configuration": "Default",
                "instances": 2,
                "unsuppressed": 2,
                "in_bom": 2,
            }
        ],
        "root": root,
        "path": path,
    }


@needs_qt
def test_a_where_used_rows_menu_opens_the_document_in_the_opened_folder(viewer, folder, opened):
    w = viewer.window
    viewer.select(PART)
    pane = w.details.where_used
    data = {
        "users": [_user(ASM, "folder"), _user("elsewhere.SLDASM", "other")],
        "possible": [],
        "name_matches": [],
    }
    pane.show_data(data, "folder")
    group = pane.tree.topLevelItem(0)
    assert pane.row_menu(group) is None  # a group's title
    menu, away = pane.row_menu(group.child(0)), pane.row_menu(group.child(1))
    assert _texts(menu) == [opening.OPEN_TEXT, opening.show_text(), "", "Go to file"]
    menu.actions()[0].trigger()
    menu.actions()[1].trigger()
    assert opened == [("open", str(folder / ASM)), ("show", str(folder / ASM))]
    why = " (not in the opened folder)"
    assert _texts(away) == [opening.OPEN_TEXT + why, opening.show_text() + why, "", "Go to file" + why]
    assert not any(a.isEnabled() for a in away.actions() if a.text())
    menu.actions()[3].trigger()
    _wait(viewer.app, lambda: w.details.title.text() == ASM)
    assert w.history and len(opened) == 2
    menu.deleteLater()
    away.deleteLater()
