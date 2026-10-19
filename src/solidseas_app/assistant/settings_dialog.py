"""AI Settings: the page where the person sets up the AI connector the modeling assistant
drafts with (``docs/ASSISTANT.md``, "The AI settings page"). The viewer opens it from
Settings > AI Settings and Tools > AI Settings, the assistant window from its own AI
Settings button.

* **Provider and model.** None, Anthropic, OpenAI, Gemini or Ollama, and the model, which
  is filled in from :data:`.aisettings.SUGGESTED_MODELS` when a provider is chosen and can
  be changed. The Ollama address is shown only for Ollama.
* **The API key.** A masked field that is never filled in and never shows a stored key;
  the page says only whether a key is stored. Typing a key and saving stores it in the
  credential store (Windows Credential Manager, ``SolidSeas/<provider>``); an empty field
  leaves the stored key as it is, and Remove Key removes it at once. The key goes into no
  settings file, log or message.
* **Test Connection** runs the provider's health check on a worker thread, with what the
  page shows (a key typed and not yet saved included), and says the result as plain text.
  Cancel stops waiting for it; the window never waits.
* **The monthly budget** in tokens and, optionally, in dollars with the model's prices, and
  this month's use from the usage file, read on a worker thread.
* **The machine policy**, read when the page opens. Under ``LocalProviderOnly`` the cloud
  providers and the key field stay visible, greyed, with "Set by your administrator". When
  the policy has an error, the page shows it with the key path.

OK and Apply save what changed (:meth:`.aisettings.AISettingsStore.update`, which leaves
fields the page did not change as another window saved them), store a typed key, and call
:func:`solidseas.ai.factory.reset`; then ``changed`` is emitted, and the windows build their
provider again. Every label is plain text and every tooltip escaped.
"""

from __future__ import annotations

import html
import math
import threading
import urllib.parse
from dataclasses import replace
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from solidseas import policy
from solidseas.ai import factory
from solidseas.ai.credentials import MemoryCredentialStore, target_name
from solidseas.ai.errors import AIError, InvalidSettingError
from solidseas.ai.factory import DISPLAY_NAMES, PROVIDER_CHOICES, AISettings
from solidseas.policy import KEY_DISPLAY, Policy

from .aisettings import ADMIN, CLOUD, SUGGESTED_MODELS, AIConfig, AISettingsFileError

TITLE = "AI Settings"
WIDTH = 660
KEY_STORED = "A key is stored"
NO_KEY = "No key is stored"
LABELS = {
    "none": "None (no AI: drafting is off)",
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "gemini": "Gemini",
    "ollama": "Ollama (a model server on this PC or your network)",
}
MODEL_NOTE = "A default you can change: check it against the models your provider offers you."
KEY_PLACEHOLDER = "Paste a new key to store it; leave empty to keep the stored one"
BUDGET_NOTE = (
    "The monthly budgets apply to cloud providers; Ollama runs on your own server and is counted, not "
    "limited. With a cost limit, set both prices for the model: without them every cloud request is "
    "refused, because its cost cannot be checked."
)
CHECKING = "Checking..."
CANCELLED = "Cancelled. A check already sent ends by itself, and its answer is ignored."


def _plain(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


def _row(text: str) -> QLabel:
    """A form row's label, as plain text."""
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


def _tip(text: str) -> str:
    return html.escape(text)


# --------------------------------------------------------------------------- numbers
def whole_number(text: str, what: str) -> int:
    """``text`` as a whole number (``2,000,000`` and ``2 000 000`` too); raises
    :class:`InvalidSettingError` naming ``what``."""
    cleaned = text.strip().replace(",", "").replace("_", "").replace(" ", "")
    if not cleaned.isascii() or not cleaned.isdigit() or len(cleaned) > 15:
        raise InvalidSettingError(f"{what} is a whole number, such as 2,000,000.")
    return int(cleaned)


def money(text: str, what: str) -> float | None:
    """``text`` as dollars (``20``, ``$2.50``); None when empty. Raises
    :class:`InvalidSettingError` naming ``what``."""
    cleaned = text.strip().removeprefix("$").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        value = float(cleaned)
    except ValueError:
        raise InvalidSettingError(f"{what} is a number of dollars, such as 20 or 2.50.") from None
    if not math.isfinite(value) or value < 0:
        raise InvalidSettingError(f"{what} is a number of dollars, such as 20 or 2.50.")
    return value


def show_number(value: Any) -> str:
    """A number as the page shows it: grouped, no needless decimals; "" for None."""
    if value is None:
        return ""
    if float(value).is_integer():
        return f"{int(value):,}"
    return format(float(value), ",.12g")


def check_ollama_url(url: str) -> None:
    """Raise :class:`InvalidSettingError` unless ``url`` is an http or https address with a host."""
    try:
        parts = urllib.parse.urlsplit(url)
        scheme, host = parts.scheme, parts.hostname
        parts.port  # noqa: B018 - raises for a port that is not a number
    except ValueError:
        scheme, host = "", None
    if scheme not in ("http", "https") or not host:
        raise InvalidSettingError("The Ollama address is a URL such as http://127.0.0.1:11434.")


def policy_lines(pol: Policy) -> list[str]:
    """What the machine policy says, one sentence each, for the page."""
    lines = []
    if pol.locked:
        lines.append(f"Your administrator manages these settings, at {KEY_DISPLAY}.")
    if pol.local_only:
        hosts = ", ".join(pol.allowed_hosts)
        where = f"on this PC or on {hosts}" if hosts else "on this PC"
        lines.append(f"{ADMIN}: only an Ollama server {where} may be used.")
    if pol.automatic_disabled:
        lines.append(f"{ADMIN}: Automatic mode is turned off.")
    if pol.error:
        lines.append(f"The machine policy at {KEY_DISPLAY} is not as expected: {pol.error}.")
    return lines


def usage_text(month: Any, settings: AISettings) -> str:
    """This month's use, as the page says it."""
    requests = "1 request" if month.calls == 1 else f"{month.calls:,} requests"
    text = f"{month.tokens:,} of {settings.monthly_tokens:,} tokens, in {requests} ({month.month}, UTC)"
    if settings.monthly_cost is not None:
        text += f"; ${month.cost:,.2f} of ${settings.monthly_cost:,.2f}"
    elif month.cost:
        text += f"; ${month.cost:,.2f}"
    return text + "."


class _Signals(QObject):
    tested = Signal(object, bool, str)  # (the check's token, ok, message)
    usage = Signal(object, str)  # (the read's token, text)


class AISettingsDialog(QDialog):
    """The page. ``config`` says where the settings, the keys and the usage live."""

    changed = Signal()  # a saved change to the settings or a key; the provider is to be built again

    def __init__(self, parent: QWidget | None, config: AIConfig) -> None:
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.config = config
        self.policy = policy.current()
        self.settings = config.settings.load()
        self._models: dict[str, str] = {}
        if self.settings.provider != "none":
            self._models[self.settings.provider] = self.settings.model
        self._kind = self.settings.provider
        self._test_token: object | None = None
        self._usage_token: object | None = None
        self.sig = _Signals()
        self._build()
        self._fill()
        self.sig.tested.connect(self._tested)
        self.sig.usage.connect(self._usage_read)
        self._read_usage()

    # ----------------------------------------------------------------- building
    def _build(self) -> None:
        self.policy_box = QGroupBox("Machine policy")
        pv = QVBoxLayout(self.policy_box)
        self.policy_label = _plain()
        pv.addWidget(self.policy_label)

        self.provider_group = QGroupBox("Provider")
        form = QFormLayout(self.provider_group)
        self.provider_form = form
        self.provider = QComboBox()
        for kind in PROVIDER_CHOICES:
            self.provider.addItem(LABELS.get(kind, kind), kind)
        self.admin_note = _plain()
        self.model = QLineEdit()
        self.model.setMaxLength(128)
        self.model_note = _plain(MODEL_NOTE)
        self.ollama_url = QLineEdit()
        self.ollama_url.setMaxLength(2048)
        self.address_note = _plain()
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText(KEY_PLACEHOLDER)
        self.key.setMaxLength(1024)
        self.key_status = _plain()
        self.remove_key = QPushButton("Remove Key")
        key_row = QHBoxLayout()
        key_row.addWidget(self.key, 1)
        key_row.addWidget(self.remove_key)
        self.key_widget = QWidget()
        kv = QVBoxLayout(self.key_widget)
        kv.setContentsMargins(0, 0, 0, 0)
        kv.addLayout(key_row)
        kv.addWidget(self.key_status)
        self.test_button = QPushButton("Test Connection")
        self.test_cancel = QPushButton("Cancel")
        self.test_cancel.setEnabled(False)
        self.test_result = _plain()
        test_row = QHBoxLayout()
        test_row.addWidget(self.test_button)
        test_row.addWidget(self.test_cancel)
        test_row.addWidget(self.test_result, 1)
        self.test_widget = QWidget()
        self.test_widget.setLayout(test_row)
        test_row.setContentsMargins(0, 0, 0, 0)
        form.addRow(_row("Provider:"), self.provider)
        form.addRow(_row(""), self.admin_note)
        form.addRow(_row("Model:"), self.model)
        form.addRow(_row(""), self.model_note)
        form.addRow(_row("Ollama address:"), self.ollama_url)
        form.addRow(_row(""), self.address_note)
        form.addRow(_row("API key:"), self.key_widget)
        form.addRow(_row(""), self.test_widget)

        self.budget_group = QGroupBox("Monthly budget")
        bf = QFormLayout(self.budget_group)
        self.tokens = QLineEdit()
        self.cost = QLineEdit()
        self.cost.setPlaceholderText("No limit")
        self.price_in = QLineEdit()
        self.price_in.setPlaceholderText("Not set")
        self.price_out = QLineEdit()
        self.price_out.setPlaceholderText("Not set")
        self.usage = _plain("Reading...")
        bf.addRow(_row("Tokens a month:"), self.tokens)
        bf.addRow(_row("Cost a month (US$):"), self.cost)
        bf.addRow(_row("Price per million input tokens (US$):"), self.price_in)
        bf.addRow(_row("Price per million output tokens (US$):"), self.price_out)
        bf.addRow(_row("This month:"), self.usage)
        bf.addRow(_row(""), _plain(BUDGET_NOTE))

        self.error = _plain()
        self.error.setStyleSheet("color: #b00020;")
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        self.buttons.accepted.connect(self._ok)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.save)
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self.ollama_url.textChanged.connect(self._update_rows)
        self.remove_key.clicked.connect(self.remove_stored_key)
        self.test_button.clicked.connect(self.test_connection)
        self.test_cancel.clicked.connect(self.cancel_test)

        # The groups scroll when the screen is too short for them, so a wrapped line is never
        # squashed; the dialog is as tall as they are, up to most of the screen (_fit).
        self.content = QWidget()
        cv = QVBoxLayout(self.content)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.addWidget(self.policy_box)
        cv.addWidget(self.provider_group)
        cv.addWidget(self.budget_group)
        cv.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.content)
        layout = QVBoxLayout(self)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(self.error)
        layout.addWidget(self.buttons)
        self.resize(WIDTH, 600)

    def _fill(self) -> None:
        s = self.settings
        lines = policy_lines(self.policy)
        self.policy_label.setText("\n".join(lines))
        self.policy_box.setVisible(bool(lines))
        local_only = self.policy.local_only
        items = self.provider.model()
        for i, kind in enumerate(PROVIDER_CHOICES):
            if kind in CLOUD and local_only:
                item = items.item(i)
                item.setEnabled(False)
                item.setToolTip(_tip(f"{ADMIN}: only a local Ollama server may be used."))
        if local_only:
            self.admin_note.setText(factory.LOCAL_ONLY_MESSAGE)
        self.provider_form.setRowVisible(self.admin_note, local_only)
        self.provider.blockSignals(True)
        self.provider.setCurrentIndex(max(0, PROVIDER_CHOICES.index(s.provider)))
        self.provider.blockSignals(False)
        self.model.setText(s.model)
        self.ollama_url.setText(s.ollama_url)
        self.tokens.setText(show_number(s.monthly_tokens))
        self.cost.setText(show_number(s.monthly_cost))
        self.price_in.setText(show_number(s.price_input_per_mtok))
        self.price_out.setText(show_number(s.price_output_per_mtok))
        problems = self.config.settings.problems
        if problems:
            self.error.setText(
                "Some saved AI settings were not valid and are back to their defaults: "
                + "; ".join(problems)
                + "."
            )
        self._update_rows()

    # ----------------------------------------------------------------- the provider rows
    def provider_kind(self) -> str:
        return str(self.provider.currentData())

    def _provider_changed(self, *_: Any) -> None:
        old, new = self._kind, self.provider_kind()
        if old != "none":
            self._models[old] = self.model.text().strip()
        self._kind = new
        self.model.setText(self._models.get(new, SUGGESTED_MODELS.get(new, "")))
        self.key.clear()
        self.test_result.setText("")
        self._test_token = None
        self.test_button.setEnabled(True)
        self.test_cancel.setEnabled(False)
        self._update_rows()

    def _update_rows(self, *_: Any) -> None:
        kind = self.provider_kind()
        form = self.provider_form
        form.setRowVisible(self.model, kind != "none")
        form.setRowVisible(self.model_note, kind != "none")
        form.setRowVisible(self.ollama_url, kind == "ollama")
        form.setRowVisible(self.key_widget, kind in CLOUD)
        form.setRowVisible(self.test_widget, kind != "none")
        refused = None
        if kind == "ollama":
            try:
                candidate = AISettings(provider="ollama", ollama_url=self.ollama_url.text().strip())
                refused = factory.refusal(candidate, self.policy)
            except InvalidSettingError:
                refused = None
        self.address_note.setText(refused or "")
        form.setRowVisible(self.address_note, bool(refused))
        if kind in CLOUD:
            admin = self.policy.local_only
            self.key.setEnabled(not admin)
            self.key.setToolTip(_tip(f"{ADMIN}: no cloud provider may be used.") if admin else "")
            self.key_widget.setToolTip(_tip(f"Kept as {target_name(kind)} in Windows Credential Manager."))
            self._show_key_status()
        else:
            self.key_status.setText("")
            self.remove_key.setEnabled(False)
        self._fit()

    def _fit(self) -> None:
        """As tall as the groups need at this width, up to 90 percent of the screen."""
        layout = self.layout()
        if layout is None:
            return
        width = max(self.width(), WIDTH)
        margins = layout.contentsMargins()
        inner = width - margins.left() - margins.right()
        want = self.content.layout().totalHeightForWidth(inner) if self.content.layout() else 400
        want += self.error.sizeHint().height() + self.buttons.sizeHint().height()
        want += margins.top() + margins.bottom() + 3 * layout.spacing() + 4
        screen = self.screen()
        if screen is not None:
            want = min(want, int(screen.availableGeometry().height() * 0.9))
        self.resize(width, max(want, 240))

    def _show_key_status(self) -> None:
        kind = self.provider_kind()
        try:
            stored = self.config.key_store().is_set(kind)
        except AIError as exc:
            self.key_status.setText(str(exc))
            self.remove_key.setEnabled(False)
            return
        self.key_status.setText(KEY_STORED if stored else NO_KEY)
        self.remove_key.setEnabled(stored)

    # ----------------------------------------------------------------- reading the form
    def form_settings(self) -> AISettings:
        """The settings the page shows, checked. Raises :class:`InvalidSettingError`."""
        kind = self.provider_kind()
        name = DISPLAY_NAMES.get(kind, kind)
        model = self.model.text().strip() if kind != "none" else ""
        if kind != "none" and not model:
            raise InvalidSettingError(f"Enter a model for {name}.")
        url = self.ollama_url.text().strip() or AISettings().ollama_url
        if kind == "ollama":
            check_ollama_url(url)
        values = {
            "provider": kind,
            "model": model,
            "ollama_url": url,
            "monthly_tokens": whole_number(self.tokens.text(), "The monthly token budget"),
            "monthly_cost": money(self.cost.text(), "The monthly cost budget"),
            "price_input_per_mtok": money(self.price_in.text(), "The input price"),
            "price_output_per_mtok": money(self.price_out.text(), "The output price"),
        }
        return replace(self.settings, **values)

    def _changes(self, wanted: AISettings) -> dict[str, Any]:
        return {
            name: getattr(wanted, name)
            for name in (
                "provider",
                "model",
                "ollama_url",
                "monthly_tokens",
                "monthly_cost",
                "price_input_per_mtok",
                "price_output_per_mtok",
            )
            if getattr(wanted, name) != getattr(self.settings, name)
        }

    # ----------------------------------------------------------------- saving
    def save(self) -> bool:
        """Save what changed, store a typed key, and reset the factory. False, with the
        reason shown, when something is not valid or could not be saved."""
        self.error.setText("")
        try:
            wanted = self.form_settings()
        except InvalidSettingError as exc:
            self.error.setText(str(exc))
            return False
        kind = wanted.provider
        typed = self.key.text() if kind in CLOUD and self.key.isEnabled() else ""
        if typed.strip():
            try:
                MemoryCredentialStore({kind: typed})  # checks the key's shape before anything is saved
            except InvalidSettingError as exc:
                self.error.setText(str(exc))
                return False
        changed = False
        changes = self._changes(wanted)
        if changes:
            try:
                self.settings = self.config.settings.update(**changes)
            except (InvalidSettingError, AISettingsFileError) as exc:
                self.error.setText(str(exc))
                return False
            changed = True
        ok = True
        if typed.strip():
            try:
                self.config.key_store().set(kind, typed)
                self.key.clear()
                changed = True
            except AIError as exc:
                self.error.setText(f"The key was not stored: {exc}")
                ok = False
        if changed:
            factory.reset()
            self._fill_after_save()
            self.changed.emit()
        return ok

    def _fill_after_save(self) -> None:
        """Show the settings as saved: the file may hold another window's changes too."""
        s = self.settings
        if s.provider != "none":
            self._models[s.provider] = s.model
            self.model.setText(s.model)
        self.ollama_url.setText(s.ollama_url)
        self.tokens.setText(show_number(s.monthly_tokens))
        self.cost.setText(show_number(s.monthly_cost))
        self.price_in.setText(show_number(s.price_input_per_mtok))
        self.price_out.setText(show_number(s.price_output_per_mtok))
        self._update_rows()
        self._read_usage()

    def _ok(self) -> None:
        if self.save():
            self.accept()

    def remove_stored_key(self) -> None:
        """Remove the provider's stored key, at once."""
        kind = self.provider_kind()
        if kind not in CLOUD:
            return
        try:
            self.config.key_store().clear(kind)
        except AIError as exc:
            self.error.setText(f"The key was not removed: {exc}")
            return
        self.key.clear()
        factory.reset()
        self._show_key_status()
        self.changed.emit()

    # ----------------------------------------------------------------- testing the connection
    def test_connection(self) -> None:
        """Check the provider the page shows, on a worker thread."""
        if self._test_token is not None:
            return
        self.error.setText("")
        try:
            settings = self.form_settings()
        except InvalidSettingError as exc:
            self.test_result.setText(str(exc))
            return
        credentials = None
        typed = self.key.text() if settings.provider in CLOUD and self.key.isEnabled() else ""
        if typed.strip():
            try:
                credentials = MemoryCredentialStore({settings.provider: typed})
            except InvalidSettingError as exc:
                self.test_result.setText(str(exc))
                return
        token = object()
        self._test_token = token
        self.test_button.setEnabled(False)
        self.test_cancel.setEnabled(True)
        self.test_result.setText(CHECKING)
        config, sig = self.config, self.sig

        def work() -> None:
            try:
                provider = config.provider(settings, credentials=credentials)
                result = provider.health(refresh=True)
                ok, text = bool(result.ok), str(result.message)
            except Exception as exc:  # a check reports; it never raises into Qt
                ok, text = False, f"The check failed ({type(exc).__name__})."
            try:
                sig.tested.emit(token, ok, text)
            except RuntimeError:  # the page was closed meanwhile
                pass

        threading.Thread(target=work, daemon=True, name="ai-settings-test").start()

    def cancel_test(self) -> None:
        if self._test_token is None:
            return
        self._test_token = None
        self.test_button.setEnabled(True)
        self.test_cancel.setEnabled(False)
        self.test_result.setText(CANCELLED)

    @property
    def testing(self) -> bool:
        return self._test_token is not None

    def _tested(self, token: object, ok: bool, text: str) -> None:
        if token is not self._test_token:
            return  # cancelled, or the page moved on
        self._test_token = None
        self.test_button.setEnabled(True)
        self.test_cancel.setEnabled(False)
        self.test_result.setText(("Connected. " if ok else "Not connected. ") + text)

    # ----------------------------------------------------------------- this month's use
    def _read_usage(self) -> None:
        token = object()
        self._usage_token = token
        settings, config, sig = self.settings, self.config, self.sig

        def work() -> None:
            try:
                text = usage_text(config.usage_ledger(settings).month(), settings)
            except Exception as exc:
                text = f"This month's use could not be read ({type(exc).__name__})."
            try:
                sig.usage.emit(token, text)
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True, name="ai-settings-usage").start()

    def _usage_read(self, token: object, text: str) -> None:
        if token is self._usage_token:
            self.usage.setText(text)

    def done(self, result: int) -> None:
        self._test_token = None  # an answer still on its way is ignored
        super().done(result)


__all__ = [
    "CANCELLED",
    "CHECKING",
    "KEY_STORED",
    "NO_KEY",
    "TITLE",
    "AISettingsDialog",
    "check_ollama_url",
    "money",
    "policy_lines",
    "show_number",
    "usage_text",
    "whole_number",
]
