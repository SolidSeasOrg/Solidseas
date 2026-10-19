"""The AI settings: the ``AI.json`` file, the AI settings page and how the assistant window
builds its provider from them (``docs/ASSISTANT.md``, "The AI settings page").

No test calls a real provider, reaches a network, writes the real Credential Manager or
touches the user's own ``AI.json``, ``Viewer.ini`` or usage file: keys go into a
``MemoryCredentialStore`` the test holds, files into ``tmp_path``, the machine policy comes
from ``policy_reader``, and Test Connection is tried against the scripted provider
(``solidseas.ai.fake``) through ``AIConfig.build``. The file's tests run everywhere; the
page's and the window's need PySide6 and run offscreen.
"""

from __future__ import annotations

import json
import os
import threading
import time

import pytest

from ai_support import KEY
from solidseas.ai import factory
from solidseas.ai.base import HealthResult
from solidseas.ai.credentials import MemoryCredentialStore
from solidseas.ai.errors import InvalidSettingError
from solidseas.ai.factory import PROVIDER_CHOICES, AISettings
from solidseas.ai.fake import ScriptedProvider
from solidseas.ai.usage import UsageLedger
from solidseas.policy import KEY_DISPLAY, Policy
from solidseas_app.assistant import aisettings
from solidseas_app.assistant.aisettings import (
    ADMIN,
    SCHEMA,
    SUGGESTED_MODELS,
    AIConfig,
    AISettingsFileError,
    AISettingsStore,
)

try:
    import PySide6.QtWidgets  # noqa: F401

    HAVE_QT = True
except ImportError:  # pragma: no cover - CI installs no PySide6
    HAVE_QT = False

needs_qt = pytest.mark.skipif(not HAVE_QT, reason="PySide6 is not installed")


@pytest.fixture(autouse=True)
def fresh_factory():
    factory.reset()
    yield
    factory.reset()


def _write(path, data) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


# --------------------------------------------------------------------------- the suggested models
def test_every_provider_has_a_suggested_model_that_passes_the_model_check():
    assert set(SUGGESTED_MODELS) == set(PROVIDER_CHOICES) - {"none"}
    for provider, model in SUGGESTED_MODELS.items():
        assert AISettings(provider=provider, model=model).model == model


# --------------------------------------------------------------------------- AI.json
def test_ai_json_round_trips_and_names_its_schema(tmp_path):
    path = tmp_path / "AI.json"
    settings = AISettings(
        provider="openai",
        model="gpt-5",
        monthly_tokens=1_000_000,
        monthly_cost=20.0,
        price_input_per_mtok=1.25,
        price_output_per_mtok=10,
        max_steps=10,
        protected_properties=("ERP Code",),
        always_confirm=True,
    )
    aisettings.save(settings, str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema"] == SCHEMA and data["provider"] == "openai"
    loaded, problems = aisettings.load(str(path))
    assert loaded == settings and problems == []
    assert not any("key" in name for name in data)  # never a key, nor a place for one


def test_a_missing_file_gives_the_defaults_without_a_problem(tmp_path):
    assert aisettings.load(str(tmp_path / "AI.json")) == (AISettings(), [])


def test_each_bad_value_falls_back_to_its_default_and_is_named(tmp_path):
    path = tmp_path / "AI.json"
    _write(
        path,
        {
            "schema": SCHEMA,
            "provider": "anthropic",
            "model": "not a model name",
            "monthly_tokens": True,
            "max_steps": 999,
            "price_input_per_mtok": 3.0,  # without its output price
            "run_tokens": 12_000,
            "protected_properties": ["ERP Code"],
            "api_key": "sk-should-never-be-read-1234",
        },
    )
    settings, problems = aisettings.load(str(path))
    assert settings.provider == "anthropic" and settings.run_tokens == 12_000
    assert settings.protected_properties == ("ERP Code",)
    defaults = AISettings()
    for name in ("model", "monthly_tokens", "max_steps", "price_input_per_mtok", "price_output_per_mtok"):
        assert getattr(settings, name) == getattr(defaults, name), name
    text = "\n".join(problems)
    for name in ("model", "monthly_tokens", "max_steps", "price_input_per_mtok", "'api_key'"):
        assert name in text, name
    assert "sk-should-never-be-read" not in text


def test_both_prices_are_read_together(tmp_path):
    path = tmp_path / "AI.json"
    prices = {"price_input_per_mtok": 3, "price_output_per_mtok": 15}
    _write(path, {"schema": SCHEMA, **prices, "monthly_cost": 5})
    settings, problems = aisettings.load(str(path))
    assert problems == [] and settings.budget().pricing.output_per_mtok == 15 and settings.monthly_cost == 5


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema": "solidseas.ai-settings/1", "provider": "openai", "provider": "gemini"}',
        b'{"schema": "solidseas.ai-settings/1", "monthly_cost": NaN}',
        b'{"schema": "solidseas.ai-settings/1", "monthly_cost": Infinity}',
        b'{"schema": "solidseas.ai-settings/1", "monthly_cost": 1e999}',
        b'{"schema": "solidseas.ai-settings/1", "x": ' + b"[" * 20 + b"]" * 20 + b"}",
        b"\xff\xfe not utf-8",
        b"[1, 2, 3]",
        b'{"provider": "openai"}',  # no schema: not ours
        b'{"schema": "something-else/1", "provider": "openai"}',
        b"{" + b" " * (aisettings.MAX_BYTES + 1) + b"}",
    ],
    # Named, not shown: pytest puts a test's id in the PYTEST_CURRENT_TEST variable, and
    # Windows refuses one longer than 32,767 characters, as the too-large file's would be.
    ids=[
        "duplicate_key",
        "nan",
        "infinity",
        "overflow",
        "too_deep",
        "not_utf8",
        "not_an_object",
        "no_schema",
        "another_schema",
        "too_large",
    ],
)
def test_a_file_that_is_not_strict_ai_settings_gives_the_defaults(tmp_path, raw):
    path = tmp_path / "AI.json"
    path.write_bytes(raw)
    settings, problems = aisettings.load(str(path))
    assert settings == AISettings() and len(problems) == 1


def test_a_newer_schema_is_read_with_a_note(tmp_path):
    path = tmp_path / "AI.json"
    _write(path, {"schema": "solidseas.ai-settings/2", "provider": "gemini", "model": "gemini-2.5-pro"})
    settings, problems = aisettings.load(str(path))
    assert settings.provider == "gemini" and "newer SolidSeas" in problems[0]


def test_save_writes_through_a_temporary_file_and_a_rename(tmp_path, monkeypatch):
    path = tmp_path / "SolidSeas" / "AI.json"
    renames = []
    real_replace = os.replace

    def spy(src, dst):
        renames.append((os.path.dirname(src), os.path.basename(src), dst))
        return real_replace(src, dst)

    monkeypatch.setattr(aisettings.os, "replace", spy)
    aisettings.save(AISettings(provider="ollama", model="llama3"), str(path))
    aisettings.save(AISettings(provider="ollama", model="llama3.1"), str(path))
    assert len(renames) == 2
    for folder, name, dst in renames:
        assert folder == str(path.parent) and name.startswith("AI.") and name.endswith(".tmp")
        assert dst == str(path)
    assert sorted(os.listdir(path.parent)) == ["AI.json"]  # no temporary file left
    assert aisettings.load(str(path))[0].model == "llama3.1"


def test_save_never_writes_through_a_link(tmp_path):
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text("left alone", encoding="utf-8")
    link = tmp_path / "AI.json"
    try:
        os.symlink(elsewhere, link)
    except (OSError, NotImplementedError):
        pytest.skip("this system does not let the test make a symbolic link")
    with pytest.raises(AISettingsFileError, match="link"):
        aisettings.save(AISettings(provider="ollama", model="llama3"), str(link))
    assert elsewhere.read_text(encoding="utf-8") == "left alone" and os.path.islink(link)


def test_save_refuses_a_folder(tmp_path):
    (tmp_path / "AI.json").mkdir()
    with pytest.raises(AISettingsFileError):
        aisettings.save(AISettings(), str(tmp_path / "AI.json"))


def test_update_changes_only_the_fields_it_is_given(tmp_path):
    path = str(tmp_path / "AI.json")
    viewer, assistant = AISettingsStore(path), AISettingsStore(path)
    viewer.load(), assistant.load()  # each window read the file when it opened its page
    viewer.update(provider="ollama", model="llama3")
    assistant.update(monthly_tokens=500_000)
    settings = AISettingsStore(path).load()
    assert (settings.provider, settings.model, settings.monthly_tokens) == ("ollama", "llama3", 500_000)


def test_update_refuses_a_value_that_is_not_valid_and_writes_nothing(tmp_path):
    path = tmp_path / "AI.json"
    store = AISettingsStore(str(path))
    with pytest.raises(InvalidSettingError):
        store.update(provider="somebody-else")
    with pytest.raises(InvalidSettingError):
        store.update(price_input_per_mtok=3.0)  # without its output price
    assert not path.exists()


def test_a_store_without_a_path_keeps_the_settings_in_memory():
    store = AISettingsStore(None)
    assert store.load() == AISettings()
    store.update(provider="ollama", model="llama3")
    assert store.load().model == "llama3" and store.path is None


def test_ai_json_sits_beside_the_viewers_settings_file(tmp_path):
    ini = tmp_path / "Roaming" / "SolidSeas" / "Viewer.ini"
    assert aisettings.path_beside(str(ini)) == str(tmp_path / "Roaming" / "SolidSeas" / "AI.json")


# --------------------------------------------------------------------------- AIConfig
def test_the_config_builds_providers_through_the_factory(tmp_path, monkeypatch):
    store = MemoryCredentialStore({"anthropic": KEY})
    ledger = UsageLedger(str(tmp_path / "usage.json"))
    config = AIConfig(AISettingsStore(None), credentials=store, ledger=ledger)
    config.settings.update(provider="anthropic", model="claude-opus-5-5")
    calls = []
    real = factory.get_provider

    def spy(settings, **kwargs):
        calls.append((settings, kwargs))
        return real(settings, **kwargs)

    monkeypatch.setattr(factory, "get_provider", spy)
    provider = config.provider()
    assert type(provider).__name__ == "AnthropicProvider" and provider.model == "claude-opus-5-5"
    assert calls[0][1] == {"credentials": store, "ledger": ledger}
    assert KEY not in repr(provider)
    other = MemoryCredentialStore()
    assert config.provider(credentials=other).reason == "no_key"  # the store given wins
    assert config.key_store() is store


def test_the_config_uses_the_default_store_when_given_none():
    config = AIConfig(AISettingsStore(None))
    assert isinstance(config.key_store(), MemoryCredentialStore)  # the tests' default store
    assert config.provider().reason == "not_configured"


# --------------------------------------------------------------------------- the page (Qt)
@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _wait(app, condition, timeout: float = 20.0) -> None:
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            raise AssertionError("timed out waiting")
        app.processEvents()
        time.sleep(0.01)


class RecordingStore(MemoryCredentialStore):
    """A memory store that records what is asked of it."""

    def __init__(self, keys=None) -> None:
        self.calls: list[tuple[str, str]] = []
        super().__init__(keys)

    def set(self, provider, key):
        self.calls.append(("set", provider))
        super().set(provider, key)

    def clear(self, provider):
        self.calls.append(("clear", provider))
        return super().clear(provider)


@pytest.fixture
def config(tmp_path):
    return AIConfig(
        AISettingsStore(str(tmp_path / "AI.json")),
        credentials=RecordingStore(),
        ledger=UsageLedger(str(tmp_path / "usage.json")),
    )


def _page(config):
    from solidseas_app.assistant.settings_dialog import AISettingsDialog

    dialog = AISettingsDialog(None, config)
    dialog.show()
    return dialog


def _choose(dialog, provider: str) -> None:
    dialog.provider.setCurrentIndex(PROVIDER_CHOICES.index(provider))


def _texts(widget) -> str:
    from PySide6.QtWidgets import QLabel, QLineEdit, QPlainTextEdit

    out = []
    for w in widget.findChildren(QLabel):
        out.append(w.text())
        out.append(w.toolTip())
    for w in widget.findChildren(QLineEdit):
        out += [w.text(), w.displayText(), w.placeholderText(), w.toolTip()]
    for w in widget.findChildren(QPlainTextEdit):
        out.append(w.toPlainText())
    return "\n".join(out)


@needs_qt
def test_the_key_field_never_shows_a_stored_key(app, config):
    from PySide6.QtWidgets import QLineEdit

    from solidseas_app.assistant.settings_dialog import KEY_STORED

    config.credentials.set("anthropic", KEY)
    config.settings.update(provider="anthropic", model="claude-opus-5-5")
    d = _page(config)
    try:
        assert d.key.text() == "" and d.key.echoMode() == QLineEdit.EchoMode.Password
        assert d.key_status.text() == KEY_STORED and d.remove_key.isEnabled()
        assert KEY not in _texts(d)
        d.key.setText("sk-typed-but-hidden-12345678")
        assert "sk-typed" not in d.key.displayText()  # masked as it is typed
    finally:
        d.reject()


@needs_qt
def test_storing_a_key_goes_through_the_store_given_and_into_no_file(app, config, tmp_path):
    from solidseas_app.assistant.settings_dialog import KEY_STORED, NO_KEY

    d = _page(config)
    try:
        _choose(d, "anthropic")
        assert d.key_status.text() == NO_KEY and not d.remove_key.isEnabled()
        d.key.setText(KEY)
        assert d.save(), d.error.text()
        assert config.credentials.get("anthropic").reveal() == KEY
        assert config.credentials.calls == [("set", "anthropic")]
        assert d.key.text() == "" and d.key_status.text() == KEY_STORED
        assert KEY not in _texts(d)
        for root, _dirs, files in os.walk(tmp_path):
            for name in files:
                with open(os.path.join(root, name), "rb") as fh:
                    assert KEY.encode() not in fh.read(), name
        assert AISettingsStore(config.settings.path).load().provider == "anthropic"
    finally:
        d.reject()


@needs_qt
def test_an_empty_key_field_leaves_the_stored_key_as_it_is(app, config):
    config.credentials.set("openai", KEY)
    config.credentials.calls.clear()
    config.settings.update(provider="openai", model="gpt-5")
    d = _page(config)
    try:
        d.model.setText("gpt-5-mini")
        assert d.save(), d.error.text()
        assert config.credentials.calls == []  # neither set nor cleared
        assert config.credentials.get("openai").reveal() == KEY
        assert AISettingsStore(config.settings.path).load().model == "gpt-5-mini"
    finally:
        d.reject()


@needs_qt
def test_remove_key_clears_it_through_the_store_given(app, config):
    from solidseas_app.assistant.settings_dialog import NO_KEY

    config.credentials.set("gemini", KEY)
    config.settings.update(provider="gemini", model="gemini-2.5-pro")
    d = _page(config)
    changed = []
    d.changed.connect(lambda: changed.append(True))
    try:
        d.remove_key.click()
        assert config.credentials.calls[-1] == ("clear", "gemini") and not config.credentials.is_set("gemini")
        assert d.key_status.text() == NO_KEY and not d.remove_key.isEnabled() and changed
    finally:
        d.reject()


@needs_qt
def test_a_key_that_is_not_valid_is_refused_without_being_repeated(app, config):
    d = _page(config)
    try:
        _choose(d, "anthropic")
        d.key.setText("sk has spaces in it")
        assert not d.save()
        assert "sk has spaces" not in d.error.text() and "printable" in d.error.text()
        assert config.credentials.calls == [] and not os.path.exists(config.settings.path)
    finally:
        d.reject()


@needs_qt
def test_reset_is_called_after_every_saved_change(app, config, monkeypatch):
    resets = []
    real = factory.reset
    monkeypatch.setattr(factory, "reset", lambda: (resets.append(True), real())[1])
    d = _page(config)
    changed = []
    d.changed.connect(lambda: changed.append(True))
    try:
        _choose(d, "anthropic")
        assert d.save() and len(resets) == 1 and len(changed) == 1  # the provider and the model
        assert d.save() and len(resets) == 1  # nothing changed: nothing saved
        d.key.setText(KEY)
        assert d.save() and len(resets) == 2  # a key alone is a change
        d.remove_key.click()
        assert len(resets) == 3 and len(changed) == 3
        d.tokens.setText("1,500,000")
        d.buttons.button(d.buttons.StandardButton.Ok).click()  # OK saves too
        assert len(resets) == 4 and AISettingsStore(config.settings.path).load().monthly_tokens == 1_500_000
    finally:
        d.reject()


@needs_qt
def test_choosing_a_provider_fills_in_its_suggested_model_and_its_rows(app, config):
    d = _page(config)
    try:
        assert not d.model.isVisible() and not d.key_widget.isVisible() and not d.test_widget.isVisible()
        _choose(d, "anthropic")
        assert d.model.text() == SUGGESTED_MODELS["anthropic"]
        assert d.key_widget.isVisible() and not d.ollama_url.isVisible() and d.test_widget.isVisible()
        d.model.setText("claude-sonnet-5-5")
        _choose(d, "openai")
        assert d.model.text() == SUGGESTED_MODELS["openai"]
        _choose(d, "anthropic")
        assert d.model.text() == "claude-sonnet-5-5"  # what the person typed comes back
        _choose(d, "ollama")
        assert d.model.text() == SUGGESTED_MODELS["ollama"]
        assert d.ollama_url.isVisible() and not d.key_widget.isVisible()
        d.ollama_url.setText("ftp://nowhere")
        assert not d.save() and "Ollama address" in d.error.text()
        d.ollama_url.setText("http://127.0.0.1:11434")
        d.model.setText("")
        assert not d.save() and "Enter a model for Ollama" in d.error.text()
    finally:
        d.reject()


@needs_qt
def test_the_monthly_budget_and_this_months_use(app, config):
    config.ledger.record("anthropic", 1000, 500)
    d = _page(config)
    try:
        _wait(app, lambda: "tokens" in d.usage.text())
        assert d.usage.text().startswith("1,500 of 2,000,000 tokens, in 1 request")
        d.tokens.setText("lots")
        assert not d.save() and "whole number" in d.error.text()
        d.tokens.setText("1,000,000")
        d.cost.setText("$20")
        d.price_in.setText("4")
        assert not d.save() and "both the input and the output price" in d.error.text()
        d.price_out.setText("20")
        assert d.save(), d.error.text()
        saved = AISettingsStore(config.settings.path).load()
        assert (saved.monthly_tokens, saved.monthly_cost) == (1_000_000, 20.0)
        assert (saved.price_input_per_mtok, saved.price_output_per_mtok) == (4.0, 20.0)
        _wait(app, lambda: "$0.00 of $20.00" in d.usage.text())  # read again: the cost budget is shown
    finally:
        d.reject()


@needs_qt
def test_saving_keeps_a_change_another_window_saved(app, config):
    d = _page(config)
    try:
        AISettingsStore(config.settings.path).update(monthly_tokens=750_000)  # the other window
        _choose(d, "ollama")
        assert d.save(), d.error.text()
        saved = AISettingsStore(config.settings.path).load()
        assert saved.provider == "ollama" and saved.monthly_tokens == 750_000
        assert d.tokens.text() == "750,000"  # the page now shows what was saved
    finally:
        d.reject()


@needs_qt
def test_settings_that_were_not_valid_are_said(app, config):
    with open(config.settings.path, "w", encoding="utf-8") as fh:
        json.dump({"schema": SCHEMA, "provider": "ollama", "model": "a b"}, fh)
    d = _page(config)
    try:
        assert "back to their defaults" in d.error.text() and "model" in d.error.text()
    finally:
        d.reject()


@needs_qt
def test_every_label_is_plain_text(app, config, policy_reader):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel

    policy_reader(Policy(local_only=True, locked=True, error="<b>LocalProviderOnly</b> is not a DWORD"))
    d = _page(config)
    try:
        for label in d.findChildren(QLabel):
            if label.text():
                assert label.textFormat() == Qt.TextFormat.PlainText, label.text()
        assert "<b>LocalProviderOnly</b>" in d.policy_label.text()
    finally:
        d.reject()


# --------------------------------------------------------------------------- Test Connection (Qt)
class GatedProvider(ScriptedProvider):
    """The scripted provider, whose health check waits for the test and records its thread."""

    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()
        self.threads: list[threading.Thread] = []

    def health_check(self) -> HealthResult:
        self.threads.append(threading.current_thread())
        self.release.wait(20)
        return HealthResult(True, "scripted and healthy")


@needs_qt
def test_test_connection_runs_off_the_ui_thread_and_reports_the_fake_providers_health(app, config):
    from solidseas_app.assistant.settings_dialog import CHECKING

    provider = GatedProvider()
    asked = []
    config.build = lambda settings, **kw: (asked.append((settings, kw)), provider)[1]
    d = _page(config)
    try:
        _choose(d, "ollama")
        d.test_button.click()
        assert d.test_result.text() == CHECKING and d.testing
        assert not d.test_button.isEnabled() and d.test_cancel.isEnabled()
        _wait(app, lambda: provider.threads)
        assert provider.threads[0] is not threading.main_thread()
        ticks = []
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, lambda: ticks.append(True))
        _wait(app, lambda: ticks)  # the window still handles events while the check waits
        provider.release.set()
        _wait(app, lambda: not d.testing)
        assert d.test_result.text() == "Connected. scripted and healthy"
        assert asked[0][0].provider == "ollama" and asked[0][0].model == SUGGESTED_MODELS["ollama"]
        assert not os.path.exists(config.settings.path)  # testing saves nothing
    finally:
        provider.release.set()
        d.reject()


@needs_qt
def test_cancel_stops_waiting_for_a_check(app, config):
    from solidseas_app.assistant.settings_dialog import CANCELLED

    provider = GatedProvider()
    config.build = lambda settings, **kw: provider
    d = _page(config)
    try:
        _choose(d, "ollama")
        d.test_button.click()
        _wait(app, lambda: provider.threads)
        d.test_cancel.click()
        assert d.test_result.text() == CANCELLED and d.test_button.isEnabled() and not d.testing
        provider.release.set()
        time.sleep(0.2)
        app.processEvents()
        assert d.test_result.text() == CANCELLED  # the late answer is ignored
    finally:
        provider.release.set()
        d.reject()


@needs_qt
def test_test_connection_uses_a_typed_key_without_storing_it(app, config):
    seen = []

    class Healthy(ScriptedProvider):
        def health_check(self):
            return HealthResult(True, "fine")

    config.build = lambda settings, credentials=None, ledger=None: (seen.append(credentials), Healthy())[1]
    d = _page(config)
    try:
        _choose(d, "anthropic")
        d.key.setText(KEY)
        d.test_button.click()
        _wait(app, lambda: not d.testing)
        assert d.test_result.text() == "Connected. fine"
        assert seen[0] is not config.credentials and seen[0].get("anthropic").reveal() == KEY
        assert not config.credentials.is_set("anthropic") and d.key.text() == KEY  # not stored, not cleared
    finally:
        d.reject()


@needs_qt
def test_a_failed_check_is_reported_as_plain_text(app, config):
    class Down(ScriptedProvider):
        def health_check(self):
            return HealthResult(False, '<a href="x">The provider could not be reached.</a>')

    config.build = lambda settings, **kw: Down()
    d = _page(config)
    try:
        _choose(d, "ollama")
        d.test_button.click()
        _wait(app, lambda: not d.testing)
        assert d.test_result.text() == 'Not connected. <a href="x">The provider could not be reached.</a>'
    finally:
        d.reject()


# --------------------------------------------------------------------------- the machine policy (Qt)
@needs_qt
def test_local_provider_only_greys_the_cloud_providers_and_the_key(app, config, policy_reader):
    policy_reader(Policy(local_only=True, locked=True))
    config.settings.update(provider="anthropic", model="claude-opus-5-5")
    d = _page(config)
    try:
        items = d.provider.model()
        enabled = {kind: items.item(i).isEnabled() for i, kind in enumerate(PROVIDER_CHOICES)}
        assert enabled == {"none": True, "anthropic": False, "openai": False, "gemini": False, "ollama": True}
        assert all(ADMIN in items.item(i).toolTip() for i in (1, 2, 3))
        assert d.provider.isVisible() and d.key.isVisible() and not d.key.isEnabled()
        assert d.admin_note.isVisible() and d.admin_note.text().startswith(ADMIN)
        assert d.policy_box.isVisible() and KEY_DISPLAY in d.policy_label.text()
        assert f"{ADMIN}: only an Ollama server on this PC may be used." in d.policy_label.text()
        d.key.setText(KEY)  # a key typed into a greyed field is never stored
        d.save()
        assert not config.credentials.is_set("anthropic")
    finally:
        d.reject()


@needs_qt
def test_an_ollama_address_the_policy_does_not_allow_is_said(app, config, policy_reader):
    policy_reader(Policy(local_only=True, allowed_hosts=("ollama.lab",), locked=True))
    d = _page(config)
    try:
        _choose(d, "ollama")
        assert not d.address_note.isVisible()  # 127.0.0.1 by default
        d.ollama_url.setText("http://192.0.2.5:11434")
        assert d.address_note.isVisible() and d.address_note.text() == factory.LOCAL_ONLY_MESSAGE
        d.ollama_url.setText("http://ollama.lab:11434")
        assert not d.address_note.isVisible()
        assert "on this PC or on ollama.lab" in d.policy_label.text()
    finally:
        d.reject()


@needs_qt
def test_a_policy_error_is_shown_with_the_key_path(app, config, policy_reader):
    policy_reader(lambda: (_ for _ in ()).throw(PermissionError("access denied")))  # the read fails
    d = _page(config)
    try:
        text = d.policy_label.text()
        assert d.policy_box.isVisible() and f"The machine policy at {KEY_DISPLAY} is not as expected" in text
        assert "PermissionError" in text and "every restriction is on" in text
        assert "Automatic mode is turned off" in text
    finally:
        d.reject()


@needs_qt
def test_without_a_policy_nothing_is_greyed(app, config):
    d = _page(config)
    try:
        assert not d.policy_box.isVisible() and not d.admin_note.isVisible()
        items = d.provider.model()
        assert all(items.item(i).isEnabled() for i in range(len(PROVIDER_CHOICES)))
        _choose(d, "gemini")
        assert d.key.isEnabled()
    finally:
        d.reject()


# --------------------------------------------------------------------------- the assistant window (Qt)
def _window(app, config, **kwargs):
    from solidseas_app.assistant.window import AssistantWindow

    w = AssistantWindow(ai=config, **kwargs)
    w.show()
    return w


@needs_qt
def test_the_window_builds_its_provider_from_the_saved_settings(app, config):
    config.settings.update(provider="ollama", model="llama3.1")
    w = _window(app, config)
    try:
        assert type(w.provider).__name__ == "OllamaProvider" and w.provider.model == "llama3.1"
        assert w.ai_box.isVisible() and w.draft_button.isEnabled() and not w.unavailable.isVisible()
    finally:
        w.close()


@needs_qt
def test_with_nothing_set_up_the_window_says_so_and_offers_the_settings_page(app, config):
    from PySide6.QtCore import Qt

    from solidseas_app.assistant.session import LIVE_LATER
    from solidseas_app.assistant.window import NOT_SET_UP

    w = _window(app, config)
    try:
        assert not w.ai_box.isVisible() and not w.sees_box.isVisible()
        assert w.unavailable.isVisible() and w.unavailable_text.text() == NOT_SET_UP
        assert w.unavailable_text.textFormat() == Qt.TextFormat.PlainText
        assert w.setup_button.isVisible() and w.settings_button.isVisible()
        _wait(app, lambda: w.status.text() == LIVE_LATER)  # the note on live SOLIDWORKS stays
        w.setup_button.click()
        page = w.settings_dialog
        assert page is not None and page.isVisible() and page.config is config
        assert w.open_ai_settings() is page  # a second press brings the same page forward
        page.reject()
        _wait(app, lambda: w.settings_dialog is None)
        w.settings_button.click()
        assert w.settings_dialog is not None and w.settings_dialog is not page
        w.settings_dialog.reject()
    finally:
        w.close()


@needs_qt
def test_a_missing_key_is_said_with_the_providers_message(app, config):
    config.settings.update(provider="anthropic", model="claude-opus-5-5")
    w = _window(app, config)
    try:
        assert w.unavailable.isVisible() and w.ai_box.isVisible() and not w.draft_button.isEnabled()
        assert w.unavailable_text.text() == (
            "Drafting is not available. No API key is stored for Anthropic. Add one in settings."
        )
    finally:
        w.close()


@needs_qt
def test_the_window_builds_its_provider_again_after_the_page_saves(app, config):
    scripted = ScriptedProvider()

    def build(settings, **kw):
        return scripted if settings.provider == "ollama" else factory.get_provider(settings, **kw)

    config.build = build
    w = _window(app, config)
    try:
        assert w.unavailable.isVisible()
        page = w.open_ai_settings()
        _choose(page, "ollama")
        assert page.save(), page.error.text()
        assert w.provider is scripted and not w.unavailable.isVisible()
        assert w.ai_box.isVisible() and w.draft_button.isEnabled()
        _choose(page, "none")
        page.buttons.button(page.buttons.StandardButton.Ok).click()
        assert not w.ai_box.isVisible() and w.unavailable.isVisible()
        _wait(app, lambda: w.settings_dialog is None)
    finally:
        w.close()


@needs_qt
def test_a_provider_the_policy_refuses_stays_greyed_and_says_why(app, config, policy_reader):
    config.credentials.set("anthropic", KEY)
    config.settings.update(provider="anthropic", model="claude-opus-5-5")
    policy_reader(Policy(local_only=True, locked=True))
    w = _window(app, config)
    try:
        assert w.provider.reason == "policy_refused"
        assert w.ai_box.isVisible() and not w.draft_button.isEnabled() and not w.request.isEnabled()
        assert w.ai_note.text().startswith(ADMIN) and ADMIN in w.draft_button.toolTip()
        assert w.unavailable.isVisible() and factory.LOCAL_ONLY_MESSAGE in w.unavailable_text.text()
        assert w.setup_button.isEnabled()
    finally:
        w.close()


@needs_qt
def test_closing_the_window_closes_its_settings_page(app, config):
    w = _window(app, config)
    closed = []
    w.closed.connect(lambda: closed.append(True))
    page = w.open_ai_settings()
    w.close()
    assert closed and not page.isVisible()
