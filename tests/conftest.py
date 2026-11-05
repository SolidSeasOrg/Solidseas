"""Shared test setup.

The fixtures folder is read-only: a session-wide guard hashes every fixture
before the tests and fails the run if any of them changed afterwards. Another
session-wide guard replaces the viewer's one launcher of programs
(``solidseas_app.viewer.printing.launch``) with one that fails the test, so no
test in any module can start a slicer: a 3D Print button pressed by a test that
does not stand in for the launcher fails instead. The service's test modules also
use ``outbound_guard``, which refuses any connection to a host other than
loopback while they run. A third keeps every catalog (``solidseas.catalog``) a
test makes in a temporary cache folder, never in the user's, and a fourth every
snapshot (``solidseas.versions``) in a temporary data folder.

For the AI connector (``docs/ASSISTANT.md``, "Tests the design requires"): no
test reaches a network, because ``connect`` and ``getaddrinfo`` fail for any
host but loopback for the whole run (``netguard``), and the run fails if
anything tried; the machine policy every test sees is "no policy" unless the
test sets one with ``policy_reader``, so the PC's own policy key never decides a
result; and the AI connector's default credential store is an empty one in
memory, so no test reads or writes the real Windows Credential Manager through
the factory.

Qt objects a test leaves in reference cycles (a window holds its controllers, and they
hold the window) are freed on the main thread after each test and each module, while
Qt is loaded: Python's cycle collector runs on whichever thread allocates when its
threshold is reached, and a Qt object it frees on a worker thread crashes the process.

A window test that leaves a modal dialog unanswered fails instead of waiting for
the run's time-out (``modalguard``).
"""

import gc
import hashlib
import os
import re
import sys
from pathlib import Path

import pytest

import modalguard
from netguard import no_outbound_connections
from support import FIXTURES, PRIVATE_PRESENT

# A test module that names a SOLIDWORKS fixture needs the private fixtures (support.py).
_NEEDS_PRIVATE = re.compile(
    r"o\d\d_\w+\.SLD|\.SLD(?:PRT|ASM|DRW)\b|fixture_path\(|\b(?:NATIVE|PARTS|DOCUMENTS|ASSEMBLY)\b"
    r"|ground_truth\(|ground_truth\.json"
)
_left_out: list[str] = []
_helpers: set[str] | None = None


def _private_helpers() -> set[str]:
    """The helper modules in tests/ (not test modules) that need the private fixtures."""
    global _helpers
    if _helpers is None:
        _helpers = set()
        for p in Path(__file__).parent.glob("*.py"):
            if p.name.startswith("test_") or p.name in ("conftest.py", "support.py"):
                continue
            if _NEEDS_PRIVATE.search(p.read_text(encoding="utf-8")):
                _helpers.add(p.stem)
    return _helpers


def pytest_ignore_collect(collection_path, config):
    """Without the private fixtures, leave out the test modules that need them: those that
    name a fixture, and those that import a helper module that does."""
    if PRIVATE_PRESENT or collection_path.suffix != ".py" or not collection_path.name.startswith("test_"):
        return None
    try:
        text = collection_path.read_text(encoding="utf-8")
    except OSError:
        return None
    imports = set(re.findall(r"^\s*(?:from|import)\s+(\w+)", text, re.M))
    if _NEEDS_PRIVATE.search(text) or imports & _private_helpers():
        _left_out.append(collection_path.name)
        return True
    return None


def pytest_terminal_summary(terminalreporter):
    if _left_out:
        terminalreporter.write_line(
            f"{len(_left_out)} test modules need the private SOLIDWORKS fixtures and were left out; "
            "scripts/fetch-fixtures.py copies them in from SolidSeas/SolidSeas-fixtures"
        )


# The service refuses a token file in a folder other accounts may write to, and on
# Linux a umask of 002 (the default on Ubuntu) makes every test's temporary folder
# group-writable. Tests that need such a folder make one on purpose.
if hasattr(os, "umask"):
    os.umask(0o022)

# Qt's offscreen platform finds no fonts on Windows unless told where they are
# (solidseas_app.viewer.app.use_system_fonts). The first module to make the
# QApplication decides for the whole run, so a module that made it without this (the
# assistant's tests) left every later window test measuring text with no font. The
# folder is set here, before any module can make one; Qt's Windows platform ignores it.
if os.name == "nt":
    os.environ.setdefault(
        "QT_QPA_FONTDIR",
        os.path.join(os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows", "Fonts"),
    )


def _hashes() -> dict[str, tuple[str, int]]:
    return {
        p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in sorted(FIXTURES.iterdir())
        if p.is_file()
    }


@pytest.fixture(scope="session", autouse=True)
def no_network():
    """No test reaches a network: any connection or name lookup to a host other than
    loopback fails for the whole run, and the run fails afterwards if anything tried."""
    with no_outbound_connections() as attempts:
        yield attempts
    assert attempts == [], f"outbound connections were attempted: {attempts[:5]}"


@pytest.fixture(scope="session", autouse=True)
def ai_defaults_for_tests():
    """The machine policy is "no policy" and the AI connector's default credential store is
    an empty one in memory, for every test that does not set its own."""
    from solidseas import policy
    from solidseas.ai import credentials

    previous = policy.set_reader(lambda: policy.NO_POLICY)
    real_store = credentials.default_store
    credentials.default_store = lambda: credentials.MemoryCredentialStore()
    try:
        yield
    finally:
        credentials.default_store = real_store
        policy.set_reader(previous)


@pytest.fixture
def policy_reader():
    """Set the machine policy a test sees: ``policy_reader(Policy(...))``, or a callable
    that returns one or raises. Restored after the test."""
    from solidseas import policy

    previous = policy.set_reader(None)
    policy.set_reader(previous)

    def use(value):
        policy.set_reader(value if callable(value) else (lambda: value))

    yield use
    policy.set_reader(previous)


@pytest.fixture(scope="module")
def outbound_guard():
    """For the service's test modules: any connection or name lookup to a host other than
    loopback fails while the module runs (``netguard.no_outbound_connections``), and
    afterwards the module fails if anything tried one. Tests that try on purpose remove
    their own entries from the list this yields."""
    with no_outbound_connections() as attempts:
        yield attempts
    assert attempts == [], f"outbound connections were attempted: {attempts[:5]}"


@pytest.fixture(autouse=True)
def settings_stay_out_of_the_real_folders(request, monkeypatch, tmp_path_factory):
    """Settings a test saves (Drawing Settings, the viewer's, the AI settings) go to a folder
    of the test's own, never to this account's: the settings folders follow APPDATA on
    Windows and XDG_CONFIG_HOME elsewhere. A test that sets its own keeps it. Not for the
    opt-in tests against real SOLIDWORKS (SOLIDSEAS_SWAPI_SOLIDWORKS set): SolidSeas'
    SOLIDWORKS inherits the environment and needs the account's own folders, and those
    tests read its journal and auto-recover folders there."""
    if os.environ.get("SOLIDSEAS_SWAPI_SOLIDWORKS") and request.node.path.name.startswith("test_swapi"):
        yield
        return
    home = tmp_path_factory.mktemp("settings-home")
    monkeypatch.setenv("APPDATA", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    yield


@pytest.fixture(autouse=True)
def each_test_starts_with_no_saved_folder_index(monkeypatch, tmp_path_factory):
    """The viewer keeps each folder's index (solidseas_app.viewer.savedindex); every test
    starts with none, so a window shows what its own test made, whatever ran before."""
    from solidseas_app.viewer import savedindex

    folder = str(tmp_path_factory.mktemp("indexes"))
    monkeypatch.setattr(savedindex, "index_folder", lambda: folder)


@pytest.fixture(scope="session", autouse=True)
def fixtures_stay_unchanged():
    before = _hashes()
    yield
    assert _hashes() == before, "a test modified a file in tests/fixtures"


def _real_catalogs() -> tuple[str, set[str]]:
    """The user's real catalog folder, worked out as solidseas.catalog would without
    SOLIDSEAS_CACHE_DIR, and the catalogs in it."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        folder = os.path.join(base, "SolidSeas", "catalogs")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
        folder = os.path.join(base, "solidseas", "catalogs")
    try:
        return folder, set(os.listdir(folder))
    except OSError:
        return folder, set()


@pytest.fixture(scope="session", autouse=True)
def catalogs_stay_out_of_the_real_cache(tmp_path_factory):
    """No test writes a catalog into the user's cache folder: every catalog a test makes goes
    below a temporary folder (SOLIDSEAS_CACHE_DIR), and the real catalog folder gains no
    entry during the run. The viewer indexes opened folders only in the tests that turn it
    on (solidseas_app.viewer.indexer.DEFAULT_ON)."""
    from solidseas_app.viewer import indexer  # no Qt: imports on CI too

    folder, before = _real_catalogs()
    saved = os.environ.get("SOLIDSEAS_CACHE_DIR")
    os.environ["SOLIDSEAS_CACHE_DIR"] = str(tmp_path_factory.mktemp("solidseas-cache"))
    default_on, indexer.DEFAULT_ON = indexer.DEFAULT_ON, False
    try:
        yield
    finally:
        indexer.DEFAULT_ON = default_on
        if saved is None:
            os.environ.pop("SOLIDSEAS_CACHE_DIR", None)
        else:
            os.environ["SOLIDSEAS_CACHE_DIR"] = saved
    after = _real_catalogs()[1]
    assert after <= before, f"a test wrote a catalog into the real cache folder {folder}"


def _real_snapshots() -> tuple[str, set[str]]:
    """The user's real snapshot store, worked out as solidseas.versions would without
    SOLIDSEAS_DATA_DIR, and the files whose snapshots it keeps."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        folder = os.path.join(base, "SolidSeas", "history", "files")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
        folder = os.path.join(base, "solidseas", "history", "files")
    try:
        return folder, set(os.listdir(folder))
    except OSError:
        return folder, set()


@pytest.fixture(scope="session", autouse=True)
def snapshots_stay_out_of_the_real_data_folder(tmp_path_factory):
    """No test writes a snapshot (solidseas.versions) into the user's data folder: the store
    every test uses by default is below a temporary folder (SOLIDSEAS_DATA_DIR), and the real
    store gains no file during the run."""
    folder, before = _real_snapshots()
    saved = os.environ.get("SOLIDSEAS_DATA_DIR")
    os.environ["SOLIDSEAS_DATA_DIR"] = str(tmp_path_factory.mktemp("solidseas-data"))
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("SOLIDSEAS_DATA_DIR", None)
        else:
            os.environ["SOLIDSEAS_DATA_DIR"] = saved
    after = _real_snapshots()[1]
    assert after <= before, f"a test wrote a snapshot into the real data folder {folder}"


@pytest.fixture(autouse=True)
def extensions_state_stays_out_of_the_real_one(tmp_path_factory, monkeypatch):
    """No test reads or writes the person's own Extensions.json."""
    folder = tmp_path_factory.mktemp("extensions-state")
    monkeypatch.setenv("SOLIDSEAS_EXTENSIONS_FILE", str(folder / "Extensions.json"))


@pytest.fixture(autouse=True)
def the_occt_backend_is_asked_afresh(monkeypatch):
    """IGES and BREP files are read only while the OCCT backend is available, which it keeps
    for a moment (solidseas.convert.occt). Every test starts with it not set up from a
    checkout (SOLIDSEAS_OCCT_HELPER_PYTHON), and neither its answer nor a test's leaks into
    the next test; tests/test_occt_backend.py sets it up where it needs it."""
    from solidseas.convert import occt

    monkeypatch.delenv(occt.ENV_PYTHON, raising=False)
    occt.BACKEND._checked = None
    yield
    occt.BACKEND._checked = None


@pytest.fixture(autouse=True)
def no_dialog_waits_forever():
    """Watch the modal dialogs of the test's QApplication, when one exists (Qt is never
    imported for this), and fail the test when one had to be closed for it
    (``modalguard``)."""
    widgets = sys.modules.get("PySide6.QtWidgets")
    app = widgets.QApplication.instance() if widgets is not None else None
    if app is not None:
        modalguard.watch(app)
    yield
    if modalguard.left_open:
        shown = "; ".join(modalguard.left_open)
        modalguard.left_open.clear()
        pytest.fail(f"a modal dialog waited {modalguard.LIMIT_S:g} s for an answer and was closed: {shown}")


@pytest.fixture(scope="session", autouse=True)
def never_launch_a_program():
    """No test may start a program through the 3D Print button's launcher. The window
    looks the launcher up when it starts one, so this covers windows a module-wide
    fixture built before any test's own fixtures ran."""
    from solidseas_app.viewer import printing  # no Qt: imports on CI too

    def refuse(program, path):
        raise AssertionError(f"a test tried to start {program} with {path}")

    real = printing.launch
    printing.launch = refuse
    try:
        yield
    finally:
        printing.launch = real


@pytest.fixture(scope="session", autouse=True)
def never_reach_a_live_solidworks():
    """No test attaches to a SOLIDWORKS someone may be working in: the sessions the app
    offers are none. The window looks them up when it opens, so a test's own sessions
    replace these; the fixture's value is the real function."""
    from solidseas_app.assistant import live_sessions  # no Qt: imports on CI too
    from solidseas_app.assistant.session import NoSessions

    real = live_sessions.default_sessions
    live_sessions.default_sessions = lambda: NoSessions("Tests reach no live SOLIDWORKS.")
    try:
        yield real
    finally:
        live_sessions.default_sessions = real


@pytest.fixture(scope="session", autouse=True)
def never_open_a_file_outside():
    """No test may hand a file to the system's program for it (Open) or open a file
    manager's window (Show in File Explorer). The window looks both up when it uses
    them, so a test's own fake replaces this one for that test. The fixture's value is
    the real functions, for the tests that call them with what they start replaced."""
    from solidseas_app.viewer import opening  # no Qt at module level: imports on CI too

    def refuse(path):
        raise AssertionError(f"a test tried to open {path} outside the viewer")

    real = {"open_file": opening.open_file, "show_file": opening.show_file}
    opening.open_file = opening.show_file = refuse
    try:
        yield real
    finally:
        opening.open_file, opening.show_file = real["open_file"], real["show_file"]


@pytest.fixture(scope="session", autouse=True)
def no_f3d_installed():
    """Every window sees no F3D, whatever this computer has, so its menus are the same
    everywhere; a test that offers Open in F3D puts its own fake in place. The fixture's
    value is the real function."""
    from solidseas_app.viewer import opening

    real = opening.find_f3d
    opening.find_f3d = lambda *a, **k: None
    try:
        yield real
    finally:
        opening.find_f3d = real


def _free_qt_cycles() -> None:
    """Collect now, on the main thread, once Qt is loaded (see the module notes)."""
    if "PySide6.QtCore" in sys.modules:
        gc.collect()


@pytest.fixture(autouse=True)
def qt_cycles_freed_after_each_test():
    """A window a test made and dropped is freed here, not by a later test's worker."""
    yield
    _free_qt_cycles()


@pytest.fixture(scope="module", autouse=True)
def qt_cycles_freed_after_each_module():
    """The module's own windows, dropped when its fixtures end, are freed here."""
    yield
    _free_qt_cycles()
