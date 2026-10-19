"""Tools > Extensions: the Extensions page (``docs/EXTENSIONS.md`` section 4).

One row per first-party extension (:data:`solidseas_app.extensions.CATALOG`): its name
and what it does, its status (built in, added with its version, or not added), an On
switch, Details (what it adds, needs and reaches, and its notices) and, for an added
package, Remove. Get extensions... opens the releases page in the person's browser
(Windows opens the address; the viewer reaches no network for it). Add from file...
takes a package the person downloaded, checks it (:func:`~solidseas_app.extensions.check_package`)
before anything is unpacked, adds it and asks whether to switch it on.

Switches are saved at once to ``Extensions.json``. The viewer's own menus follow at
once; a chat's SolidSeas server reads the file when the chat starts it, which the page
says. A switch an administrator set (``DisableExtensions``, ``AllowedExtensions``) is
off and says so.

Every extension is experimental or still in development: each row's name carries its tag
(:func:`.experimental.extension_stage`), and the page starts with what that means.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from solidseas import policy

from .. import extensions as X
from . import experimental
from .wording import tip

CHAT_NOTE = "A chat that uses SolidSeas sees a change the next time it starts SolidSeas."
SETTING_LABELS = {
    "photos": ("Photos folder", "Where you put photos of your tools (Pictures\\Gridfinity when empty)"),
    "bins": ("Bins folder", "Where bins are saved (Documents\\Gridfinity bins when empty)"),
    "tracefinity_url": ("Tracefinity address", "Tracefinity on this PC (http://127.0.0.1:3077 when empty)"),
    "ssh": ("Tracefinity server", "user@server, when Tracefinity runs on a server of yours"),
    "ssh_key": ("SSH key file", "The key for that server (the one tracefinity-server.ps1 made when empty)"),
}


class SettingsDialog(QDialog):
    """An extension's settings (:data:`solidseas_app.extensions.SETTINGS`): one field each,
    empty for the default; a setting its environment variable sets is shown and off."""

    def __init__(self, parent: QWidget | None, extension_id: str, state: X.ExtensionState) -> None:
        super().__init__(parent)
        m = X.CATALOG[extension_id]
        self.setWindowTitle(f"{m.name} Settings")
        self.extension_id = extension_id
        self.fields: dict[str, QLineEdit] = {}
        form = QFormLayout()
        saved = state.settings.get(extension_id, {})
        for key, env in X.SETTINGS[extension_id].items():
            label, hint = SETTING_LABELS.get(key, (key, ""))
            edit = QLineEdit(saved.get(key, ""))
            edit.setPlaceholderText(hint)
            if os.environ.get(env, "").strip():
                edit.setText(os.environ[env])
                edit.setEnabled(False)
                edit.setToolTip(tip(f"Set by {env}, which comes first"))
            self.fields[key] = edit
            form.addRow(label + ":", edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def applied_to(self, state: X.ExtensionState) -> X.ExtensionState:
        for key, edit in self.fields.items():
            if edit.isEnabled():
                state = X.with_setting(state, self.extension_id, key, edit.text())
        return state


def details_text(m: X.Manifest) -> str:
    lines = [m.description, ""]
    if m.adds:
        lines.append("Adds: " + "; ".join(m.adds) + ".")
    for need in m.needs:
        lines.append(f"Needs {need['what']}. {need['missing']}")
    reach = {
        "none": "no network",
        "loopback": "only programs on this PC",
        "ssh": "this PC, and a server of yours over SSH",
    }
    lines.append(f"Reaches: {reach[m.network]}.")
    if m.folders:
        lines.append("Uses the folders " + ", ".join(m.folders) + ".")
    for notice in m.notices:
        lines += ["", notice]
    return "\n".join(lines)


class ExtensionsDialog(QDialog):
    """The Extensions page (module notes). ``root`` and ``state_file`` are where packages
    and the switches live (the person's own by default); ``accepted`` the packages this
    core takes (:data:`~solidseas_app.extensions.ACCEPTED`); ``ask_file`` and ``ask`` stand
    in for the file and question dialogs in tests."""

    changed = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        root: str | None = None,
        state_file: str | None = None,
        accepted: Any = None,
        pol: Callable[[], policy.Policy] = policy.current,
        ask_file: Callable[[], str] | None = None,
        ask: Callable[[str, str], bool] | None = None,
        open_url: Callable[[str], Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Extensions")
        self.root = root
        self.state_file = state_file
        self.accepted = accepted
        self.pol = pol
        self.ask_file = ask_file or self._ask_file
        self.ask = ask or self._ask
        self.open_url = open_url or (lambda url: QDesktopServices.openUrl(QUrl(url)))
        self.warn: Callable[[str, str], Any] = lambda title, text: QMessageBox.warning(self, title, text)
        self.said: list[str] = []
        self.switches: dict[str, QCheckBox] = {}
        self.status_labels: dict[str, QLabel] = {}
        self.remove_buttons: dict[str, QPushButton] = {}
        self.names: dict[str, QLabel] = {}  # each extension's name, with its tag

        intro = QLabel(
            "Extensions add what not everyone needs. Switch on the ones you use; a packaged one "
            "needs its package, which you download and add here."
        )
        intro.setWordWrap(True)
        self.experimental_note = experimental.note_label(experimental.extensions_note())
        get = QPushButton("Get extensions...")
        get.setToolTip(tip("Open the page where SolidSeas' extension packages are, in your browser"))
        get.clicked.connect(lambda: self.open_url(X.RELEASES_URL))
        add = QPushButton("Add from file...")
        add.setToolTip(tip("Add an extension package you downloaded (a .zip)"))
        add.clicked.connect(self.add_from_file)
        self.grid = QGridLayout()
        note = QLabel(CHAT_NOTE)
        note.setWordWrap(True)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        self.buttons = close  # hidden where the Settings window hosts the page
        top = QGridLayout()
        top.addWidget(get, 0, 0)
        top.addWidget(add, 0, 1)
        layout = QVBoxLayout(self)
        layout.addWidget(self.experimental_note)
        layout.addWidget(intro)
        layout.addLayout(top)
        layout.addLayout(self.grid)
        layout.addWidget(note)
        layout.addWidget(close)
        self._build()
        self.refresh()

    # ----------------------------------------------------------------- the rows
    def _build(self) -> None:
        for row, m in enumerate(X.CATALOG.values()):
            stage = experimental.extension_stage(m.id)
            name = QLabel(experimental.tagged(f"<b>{m.name}</b>", stage))
            name.setToolTip(tip(experimental.note(stage)))
            self.names[m.id] = name
            what = QLabel(m.description)
            what.setWordWrap(True)
            status = QLabel()
            switch = QCheckBox("On")
            switch.toggled.connect(lambda on, mid=m.id: self.switch(mid, on))
            details = QPushButton("Details")
            details.clicked.connect(
                lambda _c=False, man=m: QMessageBox.information(self, man.name, details_text(man))
            )
            self.grid.addWidget(name, row * 2, 0)
            self.grid.addWidget(status, row * 2, 1)
            self.grid.addWidget(switch, row * 2, 2)
            self.grid.addWidget(details, row * 2, 3)
            if m.id in X.SETTINGS:
                settings = QPushButton("Settings...")
                settings.clicked.connect(lambda _c=False, mid=m.id: self.edit_settings(mid))
                self.grid.addWidget(settings, row * 2, 4)
            if m.kind == "packaged":
                remove = QPushButton("Remove")
                remove.clicked.connect(lambda _c=False, mid=m.id: self.remove(mid))
                self.grid.addWidget(remove, row * 2, 4)
                self.remove_buttons[m.id] = remove
            self.grid.addWidget(what, row * 2 + 1, 0, 1, 5)
            self.switches[m.id] = switch
            self.status_labels[m.id] = status

    def state(self) -> X.ExtensionState:
        return X.read_state(self.state_file)

    def refresh(self) -> None:
        pol = self.pol()
        state = self.state()
        for s in X.statuses(state, pol=pol, root=self.root):
            mid = s.manifest.id
            if s.manifest.kind == "built_in":
                text = "Built in"
            elif s.added:
                text = f"Added, version {s.added_version}"
            else:
                text = "Not added"
            if s.blocked == "Set by your administrator":
                text += ". Set by your administrator"
            self.status_labels[mid].setText(text)
            switch = self.switches[mid]
            switch.blockSignals(True)
            switch.setChecked(mid in state.on and s.blocked is None)
            switch.setEnabled(s.blocked is None)
            switch.setToolTip(tip(s.blocked or ""))
            switch.blockSignals(False)
            if mid in self.remove_buttons:
                self.remove_buttons[mid].setEnabled(s.added)

    def _say(self, text: str) -> None:
        self.said.append(text)

    # ----------------------------------------------------------------- actions
    def switch(self, extension_id: str, on: bool) -> None:
        X.write_state(self.state_file or X.state_path(), X.switched(self.state(), extension_id, on))
        self.refresh()
        self.changed.emit()

    def edit_settings(self, extension_id: str, dialog: SettingsDialog | None = None) -> bool:
        if dialog is None:  # a test hands in one it has filled already
            dialog = SettingsDialog(self, extension_id, self.state())
            dialog.exec()
        if dialog.result() != QDialog.DialogCode.Accepted:
            return False
        try:
            state = dialog.applied_to(self.state())
        except X.ExtensionError as exc:
            self.warn("Extension Settings", str(exc))
            return False
        X.write_state(self.state_file or X.state_path(), state)
        self.changed.emit()
        return True

    def _ask_file(self) -> str:
        chosen, _f = QFileDialog.getOpenFileName(self, "Add Extension", "", "Extension package (*.zip)")
        return chosen

    def _ask(self, title: str, text: str) -> bool:
        answer = QMessageBox.question(self, title, text)
        return answer == QMessageBox.StandardButton.Yes

    def add_from_file(self) -> bool:
        path = self.ask_file()
        if not path:
            return False
        try:
            checked = X.check_package(path, accepted=self.accepted)
            X.add_package(checked, root=self.root)
        except (X.ExtensionError, OSError) as exc:
            self._say(str(exc))
            self.warn("Add Extension", f"The package was not added. {exc}")
            return False
        m = checked.manifest
        self.refresh()
        if policy.extension_allowed(self.pol(), m.id) and self.ask(
            "Add Extension", f"{m.name} {m.version} is added. Switch it on now?"
        ):
            self.switch(m.id, True)
        self.changed.emit()
        return True

    def remove(self, extension_id: str) -> bool:
        m = X.CATALOG[extension_id]
        if not self.ask("Remove Extension", f"Remove {m.name}? Its package is deleted from this PC."):
            return False
        try:
            X.remove_package(extension_id, root=self.root)
        except (X.ExtensionError, OSError) as exc:
            self.warn("Remove Extension", str(exc))
            return False
        self.switch(extension_id, False)
        return True


__all__ = ["CHAT_NOTE", "SETTING_LABELS", "ExtensionsDialog", "SettingsDialog", "details_text"]
