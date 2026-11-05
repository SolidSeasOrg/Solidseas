"""Open in F3D (``solidseas_app.viewer.opening``): a file of a format F3D reads handed
to F3D, the open source 3D viewer, when it is installed.

No test starts a program: ``conftest.py`` replaces 3D Print's launcher, which Open in
F3D goes through, and has every window see no F3D. The tests here find a fake
``f3d.exe`` (two bytes) in made-up install folders, and record what would be started.
"""

import os
import shutil
from pathlib import Path

import pytest

from solidseas_app.viewer import opening, printing
from support import FIXTURES
from test_viewer import Viewer, needs_qt

PART = "o02_boxA.SLDPRT"
STL = "o02_boxA.STL"
STEP = "o02_boxA.step"
X_B = "o02_boxA.x_b"


def _install(root: Path, rel: str) -> Path:
    exe = root / rel
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"MZ")
    exe.chmod(0o755)  # an executable outside Windows too
    return exe


@pytest.fixture
def find(no_f3d_installed):
    """The real :func:`opening.find_f3d`, as on Windows, the registry's App Paths empty."""

    def call(env, app_paths=None):
        app_paths = app_paths or {}
        return no_f3d_installed(env, app_path=lambda exe: app_paths.get(exe), windows=True)

    return call


@pytest.fixture
def folder(tmp_path):
    out = tmp_path / "models"
    out.mkdir()
    for name in (PART, STL, STEP, X_B):
        shutil.copy2(FIXTURES / name, out / name)
    return out


# -- finding F3D -----------------------------------------------------------------------
def test_f3d_is_found_in_its_install_folder(tmp_path, find):
    pf, local = tmp_path / "Program Files", tmp_path / "Local"
    env = {"ProgramFiles": str(pf), "LOCALAPPDATA": str(local)}
    assert find(env) is None
    exe = _install(pf, "F3D/bin/f3d.exe")
    assert find(env) == os.path.normpath(exe)
    exe.unlink()
    unpacked = _install(local / "Programs", "F3D-4.0.1-Windows-x86_64/bin/f3d.exe")  # the zip's layout
    assert find(env) == os.path.normpath(unpacked)


def test_f3d_is_found_by_app_paths_first_then_path(tmp_path, find):
    pf = tmp_path / "Program Files"
    installed = _install(pf, "F3D/bin/f3d.exe")
    registered = _install(tmp_path / "Elsewhere", "f3d.exe")
    env = {"ProgramFiles": str(pf)}
    assert find(env, {"f3d.exe": str(registered)}) == os.path.normpath(registered)
    gone = str(tmp_path / "gone" / "f3d.exe")
    assert find(env, {"f3d.exe": gone}) == os.path.normpath(installed)  # not there: passed over
    on_path = _install(tmp_path / "tools", "f3d.exe")
    path = os.pathsep.join(["relative\\tools", "", str(tmp_path / "empty"), str(on_path.parent)])
    assert find({"PATH": path}) == os.path.normpath(on_path)
    assert find({"PATH": "tools"}) is None  # a relative folder is never looked in


def test_f3d_is_found_only_on_windows(tmp_path, no_f3d_installed):
    pf = tmp_path / "Program Files"
    _install(pf, "F3D/bin/f3d.exe")
    assert no_f3d_installed({"ProgramFiles": str(pf)}, app_path=lambda exe: None, windows=False) is None


def test_no_window_in_a_test_sees_f3d():
    assert opening.find_f3d() is None


# -- what is offered -------------------------------------------------------------------
def test_formats_f3d_reads_are_offered_and_solidworks_documents_never(folder):
    from solidseas.formats import registry

    listed = registry.extensions("all")
    assert set(opening.F3D_EXTENSIONS) <= set(listed)  # only formats SolidSeas lists
    assert ".f3d" not in opening.F3D_EXTENSIONS  # Fusion 360's, not F3D's
    for ext in (".step", ".stp", ".iges", ".igs", ".stl", ".3mf", ".obj", ".ply", ".gltf", ".glb"):
        assert ext in opening.F3D_EXTENSIONS
    assert opening.f3d_problem(str(folder / STL)) is None
    assert opening.f3d_problem(str(folder / STEP)) is None
    assert opening.f3d_problem(str(folder / PART)) == "F3D does not read SOLIDWORKS documents"
    assert opening.f3d_problem(str(folder / X_B)) == "a format F3D does not read"
    assert opening.offers_f3d(str(folder / STL)) and not opening.offers_f3d(str(folder / PART))
    assert not opening.offers_f3d(None)


def test_what_is_not_handed_to_f3d_says_why(folder):
    (folder / "run.exe").write_bytes(b"MZ")
    assert opening.f3d_problem(str(folder / "run.exe")) == "a format F3D does not read"
    assert opening.f3d_problem(str(folder / "gone.stl")) == "not there any more"
    assert opening.f3d_problem(str(folder / "gone.stl"), look=False) is None  # only the path
    assert opening.f3d_problem(str(folder / "~$o02_boxA.stl")) == "a SOLIDWORKS lock file"
    assert opening.f3d_problem("o02_boxA.STL") == "its place is not known"
    assert opening.f3d_problem(None) == "its place is not known"


@pytest.mark.skipif(os.name == "nt", reason="making a symbolic link needs a privilege on Windows")
def test_a_link_is_never_handed_to_f3d(folder):
    link = folder / "link.stl"
    link.symlink_to(folder / STL)
    assert opening.f3d_problem(str(link)) == "a link, which SolidSeas never follows"


# -- starting it -----------------------------------------------------------------------
@pytest.fixture
def started(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(printing, "launch", lambda program, path: calls.append((program, path)))
    return calls


def test_f3d_gets_the_file_as_its_one_argument(tmp_path, folder, started):
    exe = str(_install(tmp_path / "F3D" / "bin", "f3d.exe"))
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    opening.open_in_f3d(exe, str(folder / STL))
    assert started == [(exe, str(folder / STL))]
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before  # nothing written


def test_f3d_is_never_handed_what_it_may_not_have(tmp_path, folder, started):
    exe = str(_install(tmp_path / "F3D" / "bin", "f3d.exe"))
    with pytest.raises(OSError, match="SOLIDWORKS"):
        opening.open_in_f3d(exe, str(folder / PART))
    with pytest.raises(OSError, match="not there"):
        opening.open_in_f3d(str(tmp_path / "gone" / "f3d.exe"), str(folder / STL))
    other = str(_install(tmp_path / "Other", "viewer.exe"))
    with pytest.raises(OSError, match="not F3D"):
        opening.open_in_f3d(other, str(folder / STL))
    assert started == []


def test_open_in_f3d_goes_through_the_one_launcher(tmp_path, folder):
    exe = str(_install(tmp_path / "F3D" / "bin", "f3d.exe"))
    with pytest.raises(AssertionError, match="tried to start"):  # conftest's guard
        opening.open_in_f3d(exe, str(folder / STEP))


# -- in the window ---------------------------------------------------------------------
@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from solidseas_app.viewer.app import use_system_fonts

    use_system_fonts()
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def fake_f3d(tmp_path, monkeypatch):
    """F3D found (a fake ``f3d.exe``) for every window; ``None`` in the list hides it."""
    exe = _install(tmp_path / "F3D" / "bin", "f3d.exe")
    where = [str(exe)]
    monkeypatch.setattr(opening, "find_f3d", lambda *a, **k: where[0])
    return where


@pytest.fixture
def viewer(app, folder):
    v = Viewer(app)
    v.open(folder)
    yield v
    v.close()


def _texts(menu) -> list[str]:
    return [a.text() for a in menu.actions()]


def _menu(w, name: str):
    from solidseas_app.viewer.documents import NAME

    return w.list_menu(w.proxy.mapFromSource(w.model.index(w.model.find(name), NAME)))


@needs_qt
def test_without_f3d_nothing_is_offered(viewer):
    w = viewer.window
    assert not w.act_f3d_shown.isVisible()
    viewer.select(STL)
    assert not w.act_f3d_shown.isVisible()
    menu = _menu(w, STL)
    assert opening.F3D_TEXT not in " ".join(_texts(menu))
    menu.deleteLater()


@needs_qt
def test_the_lists_menu_offers_f3d_for_a_file_it_reads(fake_f3d, viewer, folder, started):
    w = viewer.window
    stl = _menu(w, STL)
    texts = _texts(stl)
    assert texts[:3] == [opening.OPEN_TEXT, opening.show_text(), opening.F3D_TEXT]
    assert opening.F3D_TIP in stl.actions()[2].toolTip()
    stl.actions()[2].trigger()
    assert started == [(fake_f3d[0], str(folder / STL))]
    assert w.statusBar().currentMessage() == f"{STL} handed to F3D."
    part = _menu(w, PART)
    assert not any(t.startswith(opening.F3D_TEXT) for t in _texts(part))  # F3D reads no SOLIDWORKS
    xb = _menu(w, X_B)
    assert not any(t.startswith(opening.F3D_TEXT) for t in _texts(xb))
    for m in (stl, part, xb):
        m.deleteLater()


@needs_qt
def test_the_file_menu_offers_f3d_for_the_file_shown(fake_f3d, viewer, folder, started):
    w = viewer.window
    file_menu = w.menuBar().actions()[0].menu().actions()
    assert file_menu.index(w.act_f3d_shown) == file_menu.index(w.act_show_shown) + 1
    viewer.select(PART)
    assert w.act_f3d_shown.isVisible() and not w.act_f3d_shown.isEnabled()
    assert w.act_f3d_shown.toolTip() == "F3D does not read SOLIDWORKS documents."
    viewer.select(STEP)
    assert w.act_f3d_shown.isEnabled() and w.act_f3d_shown.toolTip() == opening.F3D_TIP
    w.act_f3d_shown.trigger()
    assert started == [(fake_f3d[0], str(folder / STEP))]
    assert w.act_f3d_shown not in w.toolbar.actions()  # the File menu only


@needs_qt
def test_f3d_gone_or_the_file_gone_is_said(fake_f3d, viewer, folder, started):
    w = viewer.window
    viewer.select(STL)
    (folder / STL).unlink()
    assert not w.open_in_f3d(str(folder / STL))
    assert w.statusBar().currentMessage() == f"{STL} was not opened in F3D: not there any more."
    fake_f3d[0] = None
    assert not w.open_in_f3d(str(folder / STEP))
    assert (
        w.statusBar().currentMessage() == f"{STEP} was not opened in F3D: F3D is not found on this computer."
    )
    w._update_f3d(refresh=True)
    assert not w.act_f3d_shown.isVisible()
    assert started == []
