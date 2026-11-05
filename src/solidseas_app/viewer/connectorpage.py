"""Settings > Connector: other apps on this PC read the open folder through SolidSeas.

The page shows and sets what :class:`.connectorsvc.ConnectorService` runs: the local API
(its option, port and status, and buttons that copy its address and a PowerShell example,
show the token file's folder and save the API description) and, for AI apps, the MCP
configuration to copy into the app. It reads no token and writes nothing into another
app's files. Saving (the Settings window's OK and Apply) hands the choices to the service,
which keeps them in the ``[Connector]`` section and starts or stops to match.

The machine policy is read the way the rest of SolidSeas reads it
(:func:`solidseas.policy.current`): under ``LocalProviderOnly`` the MCP part is greyed and
says that the policy turned it off, as ``solidseas mcp`` then refuses every tool.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from solidseas import policy

from . import connectorsvc as svc
from .documents import display_folder

GUIDE_URL = "https://github.com/SolidSeas/SolidSeas/blob/main/docs/guide/connector.md"
SHARE_TEXT = "Let other apps on this PC read the open folder"
API_NOTE = (
    "SolidSeas answers on this PC only, at 127.0.0.1, and only an app that sends the token "
    "from the token file gets an answer. It reads the open folder and its subfolders and "
    "never changes a file."
)
MCP_NOTE = (
    "An AI app such as Claude Desktop can start SolidSeas itself and read the open folder: "
    "add this to the app's MCP configuration."
)
PRIVACY_NOTE = (
    "Whatever the connected app reads, custom property values included, goes to that app "
    "and its AI model, which usually runs on someone else's servers."
)
POLICY_OFF = "Set by your administrator: the connector for AI apps is turned off on this PC."
NO_FOLDER_CONFIG = "Open a folder to see the configuration for it."


def status_text(service: Any) -> str:
    """The status line for ``service``'s state."""
    state = service.state
    if state == svc.RUNNING:
        name = display_folder(service.folder) if service.folder else ""
        return f"Running at {service.url}, reading the folder {name}."
    if state == svc.STARTING:
        return "Starting..."
    if state == svc.NO_FOLDER:
        return "Stopped: no folder is open. It starts when you open one."
    if state == svc.FAILED:
        return f"Stopped: {service.error}" if service.error else "Stopped: the service ended unexpectedly."
    return "Stopped."


def _wrapped(text: str) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class ConnectorPage(QWidget):
    """The Connector page for ``service`` (see the module notes). ``open_folder``,
    ``open_url`` and ``ask_save_path`` reach the system; tests replace them."""

    def __init__(self, service: svc.ConnectorService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        from . import mail

        self.open_folder: Callable[[str], None] = mail.open_folder
        self.open_url: Callable[[str], Any] = lambda url: QDesktopServices.openUrl(QUrl(url))
        self.ask_save_path: Callable[[], str] = self._ask_save_path

        api = QGroupBox("Local API")
        al = QVBoxLayout(api)
        self.share = QCheckBox(SHARE_TEXT)
        al.addWidget(self.share)
        al.addWidget(_wrapped(API_NOTE))
        row = QHBoxLayout()
        row.addWidget(QLabel("Port:"))
        self.port = QSpinBox()
        self.port.setRange(svc.MIN_PORT, svc.MAX_PORT)
        self.port.setToolTip("The port on 127.0.0.1 the local API listens on (8765 unless you change it)")
        row.addWidget(self.port)
        row.addStretch(1)
        al.addLayout(row)
        self.status = _wrapped("")
        al.addWidget(self.status)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(110)
        self.details.hide()
        al.addWidget(self.details)
        buttons = QHBoxLayout()
        self.copy_address = QPushButton("Copy Address")
        self.copy_address.clicked.connect(self.copy_address_clicked)
        self.show_token = QPushButton("Show Token File")
        self.show_token.setToolTip(
            "Shows the folder that holds the token file; SolidSeas never shows the token"
        )
        self.show_token.clicked.connect(self.show_token_clicked)
        self.save_description = QPushButton("Save API Description...")
        self.save_description.setToolTip("Saves the OpenAPI description of the local API, for HTTP tools")
        self.save_description.clicked.connect(self.save_description_clicked)
        self.copy_example = QPushButton("Copy Example")
        self.copy_example.setToolTip("Copies a PowerShell example that reads the token from its file")
        self.copy_example.clicked.connect(self.copy_example_clicked)
        for b in (self.copy_address, self.show_token, self.save_description, self.copy_example):
            buttons.addWidget(b)
        buttons.addStretch(1)
        al.addLayout(buttons)
        self.result = _wrapped("")
        self.result.hide()
        al.addWidget(self.result)

        self.mcp = QGroupBox("AI apps (MCP)")
        ml = QVBoxLayout(self.mcp)
        self.policy_note = _wrapped(POLICY_OFF)
        bold = self.policy_note.font()
        bold.setBold(True)
        self.policy_note.setFont(bold)
        self.policy_note.hide()
        ml.addWidget(self.policy_note)
        self.mcp_note = _wrapped(MCP_NOTE)
        ml.addWidget(self.mcp_note)
        self.config = QPlainTextEdit()
        self.config.setReadOnly(True)
        self.config.setMinimumHeight(140)
        ml.addWidget(self.config)
        copy_row = QHBoxLayout()
        self.copy_config = QPushButton("Copy Configuration")
        self.copy_config.clicked.connect(self.copy_config_clicked)
        copy_row.addWidget(self.copy_config)
        copy_row.addStretch(1)
        ml.addLayout(copy_row)
        self.privacy = _wrapped(PRIVACY_NOTE)
        ml.addWidget(self.privacy)

        self.guide = QLabel(f'<a href="{GUIDE_URL}">Connect other apps to SolidSeas</a> (the user guide)')
        self.guide.setTextFormat(Qt.TextFormat.RichText)
        self.guide.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.guide.linkActivated.connect(lambda url: self.open_url(url))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(api)
        layout.addWidget(self.mcp)
        layout.addWidget(self.guide)
        self.load(service.settings)
        service.changed.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------------ values
    def load(self, settings: svc.ConnectorSettings) -> None:
        self.share.setChecked(settings.share)
        self.port.setValue(settings.port)

    def values(self) -> svc.ConnectorSettings:
        return svc.ConnectorSettings(share=self.share.isChecked(), port=self.port.value())

    def save(self) -> bool:
        """Hand the page's choices to the service, which keeps them and starts or stops."""
        return self.service.apply(self.values())

    def restore_defaults(self) -> None:
        self.load(svc.ConnectorSettings())

    # ------------------------------------------------------------------ what it shows
    def refresh(self) -> None:
        s = self.service
        self.status.setText(status_text(s))
        failed = s.state == svc.FAILED and bool(s.details)
        self.details.setPlainText(s.details if failed else "")
        self.details.setVisible(failed)
        self.copy_address.setEnabled(s.state == svc.RUNNING)
        local_only = policy.current().local_only
        self.policy_note.setVisible(local_only)
        self.mcp_note.setEnabled(not local_only)
        self.config.setEnabled(not local_only)
        self.privacy.setEnabled(not local_only)
        if s.folder:
            self.config.setPlainText(svc.mcp_config(s.folder))
        else:
            self.config.setPlainText(NO_FOLDER_CONFIG)
        self.copy_config.setEnabled(bool(s.folder) and not local_only)

    def _said(self, text: str) -> None:
        self.result.setText(text)
        self.result.show()

    # ------------------------------------------------------------------ the buttons
    def copy_address_clicked(self) -> None:
        if self.service.url:
            QGuiApplication.clipboard().setText(self.service.url)
            self._said("The address is copied.")

    def copy_example_clicked(self) -> None:
        QGuiApplication.clipboard().setText(
            svc.powershell_example(self.service.token_file, self.service.shown_port)
        )
        self._said("The PowerShell example is copied. It reads the token from the token file.")

    def copy_config_clicked(self) -> None:
        if self.service.folder:
            QGuiApplication.clipboard().setText(svc.mcp_config(self.service.folder))
            self._said("The configuration is copied. Paste it into the app's MCP configuration.")

    def show_token_clicked(self) -> None:
        folder = os.path.dirname(self.service.token_file)
        try:
            os.makedirs(folder, mode=0o700, exist_ok=True)
            self.open_folder(folder)
        except OSError as exc:
            self._said(f"The folder could not be shown: {exc.strerror or exc}.")

    def _ask_save_path(self) -> str:  # pragma: no cover - a dialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Save API Description", "solidseas-openapi.json", "OpenAPI description (*.json)"
        )
        return path

    def save_description_clicked(self) -> None:
        path = self.ask_save_path()
        if not path:
            return
        try:
            write_openapi(path)
        except (OSError, ValueError) as exc:
            self._said(f"The API description was not saved: {getattr(exc, 'strerror', None) or exc}.")
            return
        self._said(f"Saved the API description as {os.path.basename(path)}.")


def write_openapi(path: str) -> None:
    """Write the local API's OpenAPI description to ``path`` through a temporary file
    beside it, so a failed write never leaves half a file."""
    from solidseas import model
    from solidseas.serve.openapi import build_openapi

    data = (model.dumps(build_openapi(), pretty=True) + "\n").encode("utf-8")
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".openapi.", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None:
            try:
                os.remove(tmp)
            except OSError:
                pass


__all__ = ["GUIDE_URL", "ConnectorPage", "status_text", "write_openapi"]
