"""How the modeling assistant is opened: ``--assistant`` in the program's entry point, the
viewer's Tools > Modeling Assistant and toolbar button (one window at a time), Settings >
AI Settings, and what the packaged executable carries for it.

The entry point's tests stand in for the windows with modules of their own, so they run
everywhere; the viewer's need PySide6 and run offscreen. Nothing here calls a provider,
reaches a network or writes outside ``tmp_path``.
"""

from __future__ import annotations

import os
import re
import runpy
import sys
import time
import types
from pathlib import Path

import pytest

from ai_support import KEY
from solidseas.ai import factory
from solidseas.ai.credentials import MemoryCredentialStore
from solidseas.ai.fake import ScriptedProvider
from solidseas.ai.usage import UsageLedger

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "src" / "solidseas_app" / "__main__.py"
SPEC = ROOT / "packaging" / "SolidSeasViewer.spec"

try:
    import PySide6.QtWidgets  # noqa: F401

    HAVE_QT = True
except ImportError:  # pragma: no cover - CI installs no PySide6
    HAVE_QT = False

needs_qt = pytest.mark.skipif(not HAVE_QT, reason="PySide6 is not installed")


# --------------------------------------------------------------------------- the entry point
@pytest.fixture
def stand_ins(monkeypatch):
    """The assistant's window, the viewer and the script runner, replaced by modules that
    record how they were started."""
    started: list[tuple[str, list[str] | None]] = []

    def module(name: str, kind: str, takes_argv: bool, code: int):
        m = types.ModuleType(name)
        if takes_argv:
            m.main = lambda argv=None: (started.append((kind, argv)), code)[1]
        else:
            m.main = lambda: (started.append((kind, None)), code)[1]
        monkeypatch.setitem(sys.modules, name, m)

    module("solidseas_app.assistant.window", "assistant", True, 7)
    module("solidseas_app.viewer.app", "viewer", False, 5)
    module("solidseas_app.assistant.child", "child", False, 0)
    return started


def _entry():
    import importlib

    return importlib.import_module("solidseas_app.__main__")  # not run: its name is not __main__


def test_dash_dash_assistant_opens_the_assistant_window_on_its_own(stand_ins):
    entry = _entry()
    assert entry.main(["SolidSeasViewer.exe", "--assistant"]) == 7
    assert entry.main(["SolidSeasViewer.exe", "--assistant", "-platform", "offscreen"]) == 7
    assert stand_ins == [
        ("assistant", ["SolidSeasViewer.exe"]),
        ("assistant", ["SolidSeasViewer.exe", "-platform", "offscreen"]),
    ]


def test_without_the_flag_the_viewer_opens(stand_ins):
    entry = _entry()
    assert entry.main(["SolidSeasViewer.exe"]) == 5
    assert entry.main(["SolidSeasViewer.exe", r"C:\Parts", "--assistant"]) == 5  # only first
    assert entry.main(["SolidSeasViewer.exe", "--assistant-child"]) == 0
    assert [kind for kind, _ in stand_ins] == ["viewer", "viewer", "child"]


def test_the_entry_script_dispatches_when_run_as_the_program(stand_ins, monkeypatch):
    """As PyInstaller runs it: the file itself, as ``__main__``."""
    monkeypatch.setattr(sys, "argv", ["SolidSeasViewer.exe", "--assistant"])
    with pytest.raises(SystemExit) as done:
        runpy.run_path(str(ENTRY), run_name="__main__")
    assert done.value.code == 7 and len(stand_ins) == 1
    kind, argv = stand_ins[0]
    assert kind == "assistant" and len(argv) == 1  # the program's name, without the flag


def test_the_executable_carries_the_assistant_and_the_ai_connector():
    text = SPEC.read_text(encoding="utf-8")
    hidden = text[text.index("hiddenimports=[") : text.index("excludes=EXCLUDES")]
    for needed in (
        'collect_submodules("solidseas_app.assistant")',
        'collect_submodules("solidseas.ai")',
        '"solidseas.policy"',
        '"solidseas.swapi.live"',
        '"ssl"',
    ):
        assert needed in hidden, needed
    excludes = text[text.index("EXCLUDES = ") : text.index("# The only Qt plugins")]
    for needed in ("ssl", "_ssl", "_hashlib", "truststore"):  # HTTPS to the provider needs them
        assert not re.search(rf'"{needed}"', excludes), needed


# --------------------------------------------------------------------------- the viewer (Qt)
@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def fresh_factory():
    factory.reset()
    yield
    factory.reset()


def _wait(app, condition, timeout: float = 20.0) -> None:
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            raise AssertionError("timed out waiting")
        app.processEvents()
        time.sleep(0.01)


def _viewer(tmp_path, ai=None):
    from solidseas_app.viewer.settings import SettingsStore
    from solidseas_app.viewer.window import MainWindow

    w = MainWindow(SettingsStore(str(tmp_path / "SolidSeas" / "Viewer.ini")), ai=ai)
    w.show()
    return w


def _assistants():
    from PySide6.QtWidgets import QApplication

    from solidseas_app.assistant.window import AssistantWindow

    return [w for w in QApplication.topLevelWidgets() if isinstance(w, AssistantWindow) and w.isVisible()]


@needs_qt
def test_tools_modeling_assistant_opens_one_window(app, tmp_path):
    from PySide6.QtCore import Qt

    from solidseas_app.assistant.window import AssistantWindow

    w = _viewer(tmp_path)
    try:
        assert [a.text() for a in w.menuBar().actions()][3] == "&Tools"
        assert w.act_assistant in w.tools_menu.actions() and w.act_assistant in w.toolbar.actions()
        assert w.act_assistant.iconText() == "Assistant"
        assert w.act_assistant.shortcut().toString() == "Ctrl+Shift+A"
        assert w.assistant is None  # nothing is opened, or imported for it, until asked
        w.act_assistant.trigger()
        first = w.assistant
        assert isinstance(first, AssistantWindow) and first.isVisible() and first.parent() is None
        assert first.stays_on_top and first.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        w.act_assistant.trigger()  # again: the same window, brought forward
        first.showMinimized()
        w.open_assistant()
        assert w.assistant is first and not first.isMinimized() and _assistants() == [first]
        first.close()
        _wait(app, lambda: w.assistant is None)
        w.act_assistant.trigger()
        assert w.assistant is not None and w.assistant is not first and len(_assistants()) == 1
    finally:
        w.close()
    assert w.assistant is None and _assistants() == []  # closing the viewer closes it


@needs_qt
def test_the_assistant_from_the_viewer_reads_ai_json_beside_viewer_ini(app, tmp_path):
    from solidseas_app.assistant.aisettings import AISettingsStore

    path = tmp_path / "SolidSeas" / "AI.json"
    AISettingsStore(str(path)).update(provider="ollama", model="llama3.1")
    w = _viewer(tmp_path)
    try:
        assert w.ai_config().settings.path == str(path)
        a = w.open_assistant()
        assert type(a.provider).__name__ == "OllamaProvider" and a.provider.model == "llama3.1"
        assert a.ai_box.isVisible() and not a.unavailable.isVisible()
    finally:
        w.close()


@needs_qt
def test_a_viewer_with_its_settings_in_memory_keeps_the_ai_settings_in_memory(app):
    from solidseas_app.viewer.window import MainWindow

    w = MainWindow()
    try:
        assert w.ai_config().settings.path is None
    finally:
        w.close()


@needs_qt
def test_ai_settings_opens_from_the_settings_and_tools_menus_and_rebuilds_the_assistant(app, tmp_path):
    from solidseas_app.assistant.aisettings import AIConfig, AISettingsStore
    from solidseas_app.assistant.window import NOT_SET_UP

    scripted = ScriptedProvider()

    def build(settings, **kw):
        return scripted if settings.provider == "ollama" else factory.get_provider(settings, **kw)

    store = MemoryCredentialStore()
    ai = AIConfig(
        AISettingsStore(str(tmp_path / "AI.json")),
        credentials=store,
        ledger=UsageLedger(str(tmp_path / "usage.json")),
        build=build,
    )
    w = _viewer(tmp_path, ai)
    try:
        assert w.act_ai_settings in w.settings_menu.actions() and w.act_ai_settings in w.tools_menu.actions()
        a = w.open_assistant()
        assert a.unavailable_text.text() == NOT_SET_UP
        w.act_ai_settings.trigger()
        settings = w.settings_window  # the Settings window, on its AI Assistant page
        assert settings is not None and settings.isVisible() and settings.parent() is w
        assert settings.current_page() == "AI Assistant"
        page = settings.ai
        w.act_ai_settings.trigger()
        assert w.settings_window is settings  # one window at a time
        page.provider.setCurrentIndex(page.provider.findData("ollama"))
        assert page.save(), page.error.text()
        assert a.provider is scripted and a.draft_button.isEnabled() and not a.unavailable.isVisible()
        page.provider.setCurrentIndex(page.provider.findData("anthropic"))
        page.key.setText(KEY)
        settings.buttons.button(settings.buttons.StandardButton.Ok).click()
        assert store.get("anthropic").reveal() == KEY  # through the store the viewer was given
        assert a.provider.name == "anthropic" and a.draft_button.isEnabled()
        _wait(app, lambda: w.settings_window is None)
        assert KEY.encode() not in (tmp_path / "AI.json").read_bytes()
    finally:
        w.close()
