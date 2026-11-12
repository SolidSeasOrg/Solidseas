"""The PDM menu: a library's check-ins, changes, project check and restores in the viewer.

When the opened folder lies in a PDM library (``solidseas.pdm``, ``docs/PDM.md``), the
PDM menu, between Tools and Settings, offers:

* **Check In...**: the selected file or the folder chosen in the folder tree. A dialog
  lists what changed there and takes the note, an optional revision and an optional
  state; the check-in runs in a worker thread (``Vault.checkin``).
* **Changes**: the files below the chosen folder that are new, changed since their
  newest version, or gone (``Vault.status``), in a window of their own.
* **Check Project**: whether the project that holds the chosen folder holds every file
  its documents reference (``solidseas.pdm.check.check_project``), the findings
  grouped by result in plain words, each with the stored path and where it was found.
* **Restore Version...**: the version chosen in the History tab put back, after a
  confirmation that says the file as it is now is kept as a version first, either over
  the file or as a new file beside it (``Vault.restore``).

Outside a library the menu holds only **Make This Folder a Library...**, which says
what it creates and asks before calling ``pdm.init`` on the opened folder. The file
list's right-click menu has the same entries where they apply (:meth:`PdmController.add_to_menu`).

Every read and write runs in a worker thread. The PDM writes only in the library: its
own ``.solidseas`` folder and the file a restore puts back (``docs/PDM.md`` 7). The
dialogs open without blocking the window; the confirmations go through
:meth:`PdmController.ask`, which tests stand in for, as for the other dialogs.
"""

import os
from typing import Any

from PySide6.QtCore import QObject, Qt, QThreadPool, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QRadioButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .reading import time_text
from .wording import error_message, plural, tip
from .workers import Job

MENU_TEXT = "P&DM"
CHECKIN_TEXT = "Check &In..."
CHANGES_TEXT = "&Changes"
CHECK_TEXT = "Check &Project"
RESTORE_TEXT = "&Restore Version..."
MAKE_TEXT = "&Make This Folder a Library..."
CHECKIN_TIP = "Keep a version of each changed file with a note, in the library's history"
CHANGES_TIP = "List the files that are new, changed or gone since their newest version in the library"
CHECK_TIP = "Check that the project holds every file its assemblies, parts and drawings reference"
RESTORE_TIP = (
    "Put back the version chosen in the History tab. The file as it is now is kept as a version first"
)
MAKE_TIP = "Keep the history of the CAD files in the opened folder, with a note for each check-in"
MAKE_QUESTION = (
    "Make {folder} a library?\n\nSolidSeas adds a .solidseas folder to it, where it keeps the versions "
    "and check-ins of the CAD files inside. Nothing else in the folder changes."
)
STATE_WORDS = {"new": "New", "changed": "Changed", "gone": "Gone", "unchanged": "Unchanged"}
STATE_ORDER = ("new", "changed", "gone")

# The project check's results, in the order the window lists them, in words.
RESULT_WORDS = {
    "missing": "Not found anywhere",
    "different_document": "Another document has that name",
    "ambiguous": "Several files could be it",
    "outside": "Found only outside the project",
    "toolbox": "Toolbox hardware",
    "inside_parent": "Stored inside its assembly",
    "ok": "Found in the project",
}
RESULT_TIPS = {
    "missing": "No file of that name was found in the project, above it or in the library.",
    "different_document": (
        "SOLIDWORKS' search finds a file of that name, but it was made as another document (its stored "
        "creation time differs), so the assembly would open the wrong part."
    ),
    "ambiguous": "Several files of that name could be the one, and none of them could be chosen.",
    "outside": (
        "The file is found only outside the project folder: in the library, in another project or "
        "elsewhere. Copy it into the project to make the project self-contained."
    ),
    "toolbox": (
        "Toolbox hardware, which SOLIDWORKS loads from the installation's own Toolbox folder: no copy "
        "is needed."
    ),
    "inside_parent": "A virtual component, or one stored inside its assembly: nothing to copy.",
    "ok": "Found inside the project.",
}
PLACE_WORDS = {
    "project": "in the project",
    "library": "in the library",
    "other_project": "in another project",
    "elsewhere": "elsewhere",
}


def _inside(path: str, folder: str) -> bool:
    p = os.path.normcase(os.path.abspath(path))
    f = os.path.normcase(os.path.abspath(folder))
    return p == f or p.startswith(f.rstrip(os.sep) + os.sep)


# --------------------------------------------------------------------------- work, off the UI thread
def status_work(path: str):
    """A Job's work: the status of the library below ``path`` (a folder or a file)."""

    def work(_emit, _cancelled) -> dict[str, Any]:
        from solidseas import pdm

        vault = pdm.open(path)
        st = vault.status(path)
        return {"ok": True, "kind": "status", "library": vault.root, "path": path, "status": st}

    return work


def checkin_work(paths: list[str], note: str, revision: str | None, state: str | None):
    """A Job's work: one check-in of ``paths`` with ``note``."""

    def work(_emit, _cancelled) -> dict[str, Any]:
        from solidseas import pdm

        vault = pdm.open(paths[0])
        result = vault.checkin(paths, note, revision=revision, state=state)
        return {"ok": True, "kind": "checkin", "library": vault.root, "paths": paths, "data": result.data()}

    return work


def project_folders(path: str) -> tuple[str, str | None, str] | None:
    """The project that holds ``path`` (a folder or a file in a library): its folder, the
    library section's folder when there is one, and its name; None when ``path`` is in no
    project (the library section, or above a project's level)."""
    from solidseas import pdm

    vault = pdm.open(path)
    project = vault.project_of(path)
    if project is None:
        return None
    library = vault.absolute(vault.settings.library)
    return vault.absolute(project.path), library if os.path.isdir(library) else None, project.path


def check_work(path: str):
    """A Job's work: the self-contained check of the project that holds ``path``."""

    def work(_emit, _cancelled) -> dict[str, Any]:
        from pathlib import Path

        from solidseas.pdm.check import check_project

        found = project_folders(path)
        if found is None:
            return {"ok": True, "kind": "check", "project": None, "result": None}
        folder, library, name = found
        result = check_project(Path(folder), library=Path(library) if library else None)
        return {"ok": True, "kind": "check", "project": folder, "name": name, "result": result}

    return work


def restore_work(path: str, version: str, as_name: str | None):
    """A Job's work: a version of the file at ``path`` put back."""

    def work(_emit, _cancelled) -> dict[str, Any]:
        from solidseas import pdm

        vault = pdm.open(path)
        return {"ok": True, "kind": "restore", "data": vault.restore(path, version, as_name)}

    return work


# --------------------------------------------------------------------------- words
def status_line(st, scope: str = "") -> str:
    """A status in one sentence: what changed below ``scope`` (a name; "" when it goes
    without saying)."""
    c = st.counts
    where = f" in {scope}" if scope else ""
    moved = c.get("new", 0) + c.get("changed", 0) + c.get("gone", 0)
    if not moved:
        return (
            f"Nothing has changed{where} since the newest versions in the library "
            f"({plural(c.get('unchanged', 0), 'file')} checked)."
        )
    parts = [f"{c[s]:,} {s}" for s in STATE_ORDER if c.get(s)]
    return (
        f"{plural(moved, 'file')}{where} changed since the newest versions in the library: "
        f"{', '.join(parts)}. {plural(c.get('unchanged', 0), 'file')} unchanged."
    )


def checkin_summary(data: dict[str, Any]) -> str:
    """The status bar's line after a check-in."""
    files = data["files"]
    stored = data["stored"]
    if data["checkin"] is None:
        text = "Nothing was checked in."
    else:
        text = f"Checked in {plural(len(files), 'file')}: {plural(stored, 'new version')} stored."
    if data["failed"]:
        text += f" {plural(len(data['failed']), 'file')} could not be stored."
    return text


def restore_summary(data: dict[str, Any]) -> str:
    name = data["file"]["name"]
    version = f"v{data['version']['number']}"
    if not data["written"]:
        return f"{name} already is {version}: nothing was written."
    text = f"Put back {version} as {name}." if not data["replaced"] else f"Put back {version} of {name}."
    first = data.get("stored_first")
    if data["replaced"] and first:  # stored before, or already a version
        text += " The file as it was is kept as a version in the library."
    return text


def finding_rows(result) -> list[tuple[str, list[dict[str, Any]]]]:
    """A check's findings grouped by result in :data:`RESULT_WORDS` order, each finding as
    the words the window shows: the document (below the project), the stored path and
    where it was found."""
    groups: dict[str, list[dict[str, Any]]] = {}
    project = str(result.project)
    for f in result.findings:
        doc = os.path.relpath(str(f.document), project)
        if f.found is not None:
            place = PLACE_WORDS.get(f.place or "", "")
            where = str(f.found) + (f" ({place})" if place and f.place != "project" else "")
        else:
            where = "Not found"
        groups.setdefault(f.result, []).append(
            {"document": doc, "stored": f.stored_path or f.file_name or "", "where": where}
        )
    out = [(r, groups[r]) for r in RESULT_WORDS if r in groups]
    out += [(r, rows) for r, rows in groups.items() if r not in RESULT_WORDS]
    if result.unreadable:
        out.append(
            (
                "unreadable",
                [
                    {"document": os.path.relpath(str(p), project), "stored": "", "where": why}
                    for p, why in result.unreadable
                ],
            )
        )
    return out


def check_line(name: str, result) -> str:
    problems = len(result.problems()) + len(result.unreadable)
    head = f"{name}: {plural(len(result.findings), 'reference')} in {plural(result.documents, 'document')}."
    if not problems:
        return head + " The project holds every file its documents reference."
    verb = "keeps" if problems == 1 else "keep"
    return head + f" {plural(problems, 'finding')} {verb} the project from being self-contained."


# --------------------------------------------------------------------------- the windows
def _tree(headers: list[str]) -> QTreeWidget:
    tree = QTreeWidget()
    tree.setColumnCount(len(headers))
    tree.setHeaderLabels(headers)
    tree.setUniformRowHeights(True)
    tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
    tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    return tree


def _label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


def _bold(item: QTreeWidgetItem) -> None:
    f = item.font(0)
    f.setBold(True)
    item.setFont(0, f)


def fill_status(tree: QTreeWidget, st, library: str) -> None:
    """The new, changed and gone files of a status, grouped, with their paths below the
    library; and the files that could not be looked at."""
    tree.clear()
    for state in STATE_ORDER:
        files = [f for f in st.files if f.state == state]
        if not files:
            continue
        top = QTreeWidgetItem([f"{STATE_WORDS[state]} ({len(files):,})", ""])
        _bold(top)
        tree.addTopLevelItem(top)
        for f in files:
            item = QTreeWidgetItem(top, [f.path, ""])
            item.setToolTip(0, tip(os.path.join(library, *f.path.split("/"))))
        top.setExpanded(True)
    if st.skipped:
        top = QTreeWidgetItem([f"Not looked at ({len(st.skipped):,})", ""])
        _bold(top)
        tree.addTopLevelItem(top)
        for s in st.skipped:
            QTreeWidgetItem(top, [s["path"], str(s.get("reason") or "").replace("_", " ")])
        top.setExpanded(True)
    tree.resizeColumnToContents(0)


class ChangesDialog(QDialog):
    """PDM > Changes: what changed below a folder, read in a worker thread. Check In
    opens the check-in for the same folder."""

    def __init__(self, parent: QWidget, scope: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Changes")
        self.scope = scope
        self.line = _label("Looking for changes...")
        self.tree = _tree(["File", "Note"])
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.checkin_button = self.buttons.addButton("Check In...", QDialogButtonBox.ButtonRole.ActionRole)
        self.checkin_button.setEnabled(False)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.line)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.buttons)
        self.resize(640, 420)

    def show_result(self, result: dict[str, Any]) -> None:
        if not result.get("ok"):
            self.line.setText("The changes could not be read. " + error_message(result.get("error")))
            return
        st = result["status"]
        self.line.setText(status_line(st, os.path.basename(self.scope) or self.scope))
        fill_status(self.tree, st, result["library"])
        self.checkin_button.setEnabled(sum(st.counts.values()) > 0)


class CheckinDialog(QDialog):
    """PDM > Check In: what to check in, what changed there, the note, the revision and
    the state. ``choices`` are (words, paths) pairs; the first is chosen."""

    def __init__(self, parent: QWidget, choices: list[tuple[str, list[str]]]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Check In")
        self.choices = choices
        self.what = QComboBox()
        for words, _paths in choices:
            self.what.addItem(words)
        self.line = _label("Looking for changes...")
        self.tree = _tree(["File", "Note"])
        self.note = QPlainTextEdit()
        self.note.setPlaceholderText("What changed, and why")
        self.note.setTabChangesFocus(True)
        self.note.setFixedHeight(72)
        self.revision = QLineEdit()
        self.revision.setMaxLength(64)
        self.revision.setPlaceholderText("Optional, such as B")
        self.state = QComboBox()
        self.state.setEditable(True)
        self.state.addItems(["", "in work", "for review", "released"])
        self.state.lineEdit().setMaxLength(64)
        self.state.lineEdit().setPlaceholderText("Optional, such as released")
        form = QFormLayout()
        form.addRow("Check in", self.what)
        form.addRow("Note", self.note)
        form.addRow("Revision", self.revision)
        form.addRow("State", self.state)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.ok = self.buttons.addButton("Check In", QDialogButtonBox.ButtonRole.AcceptRole)
        self.ok.setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.line)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.buttons)
        self.note.textChanged.connect(self._update)
        self._tracked = 0
        self.resize(600, 520)

    @property
    def paths(self) -> list[str]:
        return self.choices[max(0, self.what.currentIndex())][1]

    def values(self) -> tuple[str, str | None, str | None]:
        """The note, revision and state typed (None for an empty label)."""
        return (
            self.note.toPlainText().strip(),
            self.revision.text().strip() or None,
            self.state.currentText().strip() or None,
        )

    def looking(self) -> None:
        self._tracked = 0
        self.tree.clear()
        self.line.setText("Looking for changes...")
        self._update()

    def show_result(self, result: dict[str, Any]) -> None:
        if not result.get("ok"):
            self.line.setText("The changes could not be read. " + error_message(result.get("error")))
            self._tracked = 0
        else:
            st = result["status"]
            self._tracked = sum(st.counts.values())
            if not self._tracked:
                self.line.setText("There is no CAD file the library tracks there.")
            else:
                line = status_line(st)
                if not any(st.counts.get(s) for s in STATE_ORDER):
                    line += " A check-in records the files as they are, with your note."
                self.line.setText(line)
            fill_status(self.tree, st, result["library"])
        self._update()

    def _update(self) -> None:
        self.ok.setEnabled(self._tracked > 0 and bool(self.note.toPlainText().strip()))

    def working(self) -> None:
        self.line.setText("Checking in...")
        self.ok.setEnabled(False)
        self.what.setEnabled(False)


class CheckDialog(QDialog):
    """PDM > Check Project: the findings grouped by result, each with its document, the
    path stored in it and where the file was found."""

    def __init__(self, parent: QWidget, name: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Check Project: {name}")
        self.line = _label(
            "Reading every assembly, part and drawing in the project and following its references..."
        )
        self.tree = _tree(["Document", "Stored path", "Where it was found"])
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.line)
        layout.addWidget(self.tree, 1)
        layout.addWidget(buttons)
        self.resize(820, 480)

    def show_result(self, result: dict[str, Any]) -> None:
        self.tree.clear()
        if not result.get("ok"):
            self.line.setText("The project could not be checked. " + error_message(result.get("error")))
            return
        check = result["result"]
        if check is None:
            self.line.setText("The folder is not in a project of the library.")
            return
        self.line.setText(check_line(result["name"], check))
        fine = {"ok", "inside_parent", "toolbox"}
        for kind, rows in finding_rows(check):
            words = RESULT_WORDS.get(kind, "Could not be read" if kind == "unreadable" else kind)
            top = QTreeWidgetItem([f"{words} ({len(rows):,})", "", ""])
            _bold(top)
            top.setToolTip(
                0,
                tip(
                    RESULT_TIPS.get(kind)
                    or "These documents could not be read, so their references were not checked."
                ),
            )
            self.tree.addTopLevelItem(top)
            for r in rows:
                item = QTreeWidgetItem(top, [r["document"], r["stored"], r["where"]])
                for c, text in enumerate((r["document"], r["stored"], r["where"])):
                    if text:
                        item.setToolTip(c, tip(text))
            top.setExpanded(kind not in fine)
        for c in range(3):
            self.tree.resizeColumnToContents(c)


class RestoreDialog(QDialog):
    """PDM > Restore Version: says what happens, and offers to restore as a new file."""

    def __init__(self, parent: QWidget, path: str, row) -> None:
        super().__init__(parent)
        self.setWindowTitle("Restore Version")
        name = os.path.basename(path)
        when = time_text(row.time_utc)
        what = f"{row.label} of {name}" + (f", from {when}" if when else "")
        if row.note:
            what += f" ({row.note})"
        self.line = _label(
            f"Put back {what}.\n\nBefore anything is written, the file as it is now is kept as a "
            "version in the library, so nothing is lost."
        )
        self.replace = QRadioButton(f"Replace {name}")
        self.as_new = QRadioButton("Restore as a new file named")
        stem, ext = os.path.splitext(name)
        self.name = QLineEdit(f"{stem} {row.label}{ext}")
        group = QButtonGroup(self)
        group.addButton(self.replace)
        group.addButton(self.as_new)
        self.replace.setChecked(True)
        self.name.setEnabled(False)
        self.as_new.toggled.connect(self.name.setEnabled)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.ok = self.buttons.addButton("Restore", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.line)
        layout.addWidget(self.replace)
        layout.addWidget(self.as_new)
        layout.addWidget(self.name)
        layout.addWidget(self.buttons)

    @property
    def as_name(self) -> str | None:
        return self.name.text().strip() if self.as_new.isChecked() else None


# --------------------------------------------------------------------------- the controller
class PdmController(QObject):
    """The PDM menu of one window (see the module notes). ``shown`` carries each
    result a window or the status bar showed (for tests)."""

    shown = Signal(object)

    def __init__(self, window) -> None:
        super().__init__(window)
        self.w = window
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)  # a check-in's status and a project check at once
        self.library: str | None = None
        self.dialogs: list[QDialog] = []
        self._generation = 0

        def action(text: str, status: str, slot) -> QAction:
            a = QAction(text, window)
            a.setStatusTip(status)
            a.setToolTip(tip(status))
            a.triggered.connect(lambda _on=False: slot())
            return a

        self.act_checkin = action(CHECKIN_TEXT, CHECKIN_TIP, self.check_in)
        self.act_changes = action(CHANGES_TEXT, CHANGES_TIP, self.show_changes)
        self.act_check = action(CHECK_TEXT, CHECK_TIP, self.check_project)
        self.act_restore = action(RESTORE_TEXT, RESTORE_TIP, self.restore_version)
        self.act_make = action(MAKE_TEXT, MAKE_TIP, self.make_library)
        menu = QMenu(MENU_TEXT, window)
        menu.setToolTipsVisible(True)
        for a in (self.act_checkin, self.act_changes, self.act_check):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(self.act_restore)
        menu.addAction(self.act_make)
        menu.aboutToShow.connect(self.update_actions)
        window.menuBar().insertMenu(window.settings_menu.menuAction(), menu)
        self.menu = menu
        self.update_actions()

    # -- where we are ----------------------------------------------------------------
    def folder_opened(self, folder: str | None) -> None:
        """The window opened ``folder``: is it in a library?"""
        self.library = None
        if folder:
            from solidseas import pdm

            try:
                self.library = pdm.find_library(folder)
            except OSError:
                self.library = None
        self.update_actions()

    def selected_file(self) -> str | None:
        """The file selected in the list, when one is."""
        w = self.w
        if w.folder is None:
            return None
        index = w.table.selectionModel().currentIndex()
        entry = w.model.entry(w.proxy.mapToSource(index)) if index.isValid() else None
        if entry is None or entry["type"] != "file":
            return None
        from .reading import host_path

        return host_path(w.folder, entry["path"])

    def tracked(self, path: str) -> bool:
        if self.library is None or not _inside(path, self.library):
            return False
        from solidseas import pdm

        try:
            return pdm.open(self.library).tracked(path)
        except Exception:
            return False

    def project_of(self, folder: str) -> str | None:
        if self.library is None or not _inside(folder, self.library):
            return None
        try:
            found = project_folders(folder)
        except Exception:
            return None
        return None if found is None else found[0]

    def restorable(self) -> tuple[str, Any] | None:
        """The file and the version the History tab has chosen, when it is a version in
        this library that can be put back."""
        h = self.w.file_history
        row = h.chosen_row()
        if h.path is None or row is None or row.kind != "vault" or not row.readable:
            return None
        if self.library is None or row.library is None or not _inside(h.path, self.library):
            return None
        return h.path, row

    def update_actions(self) -> None:
        inside = self.library is not None
        opened = self.w.folder is not None
        for a in (self.act_checkin, self.act_changes, self.act_check, self.act_restore):
            a.setVisible(inside)
        self.act_make.setVisible(not inside)
        self.act_make.setEnabled(opened)
        if not inside:
            return
        folder = self.w.current_folder() or self.library
        self.act_checkin.setEnabled(True)
        self.act_changes.setEnabled(True)
        self.act_check.setEnabled(self.project_of(folder) is not None)
        self.act_check.setText(
            CHECK_TEXT if self.act_check.isEnabled() else CHECK_TEXT + " (choose a folder in a project)"
        )
        self.act_restore.setEnabled(self.restorable() is not None)
        self.act_restore.setText(
            RESTORE_TEXT
            if self.act_restore.isEnabled()
            else RESTORE_TEXT + " (choose a library version in the History tab)"
        )

    def add_to_menu(self, menu: QMenu, path: str, *, folder: bool) -> bool:
        """The PDM entries of the file list's right-click menu for ``path``: Check In and
        Changes for a folder or a tracked file, Check Project for a folder in a project,
        Restore Version for the file the History tab shows with a library version chosen.
        False when none applies (outside a library)."""
        if self.library is None or not _inside(path, self.library):
            return False
        if not folder and not self.tracked(path):
            return False
        menu.addSeparator()
        name = os.path.basename(path)
        a = menu.addAction(f"Check In {name}...")
        a.setToolTip(tip(CHECKIN_TIP))
        a.triggered.connect(lambda _on=False: self.check_in([path]))
        a = menu.addAction("Changes" + (f" in {name}" if folder else ""))
        a.setToolTip(tip(CHANGES_TIP))
        a.triggered.connect(lambda _on=False: self.show_changes(path))
        if folder and self.project_of(path) is not None:
            a = menu.addAction(CHECK_TEXT.replace("&", ""))
            a.setToolTip(tip(CHECK_TIP))
            a.triggered.connect(lambda _on=False: self.check_project(path))
        found = self.restorable()
        if not folder and found is not None and _inside(found[0], path) and _inside(path, found[0]):
            a = menu.addAction(f"Restore {found[1].label}...")
            a.setToolTip(tip(RESTORE_TIP))
            a.triggered.connect(lambda _on=False: self.restore_version())
        return True

    # -- asking ------------------------------------------------------------------------
    def ask(self, title: str, text: str) -> bool:
        """A yes or no question; tests stand in for it."""
        box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=self.w)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _open(self, dialog: QDialog) -> QDialog:
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.dialogs.append(dialog)
        dialog.destroyed.connect(
            lambda _o=None, d=dialog: self.dialogs.remove(d) if d in self.dialogs else None
        )
        dialog.open()
        return dialog

    def _message(self, text: str, ms: int = 10000) -> None:
        self.w.statusBar().showMessage(text, ms)

    def _start(self, work, on_finished) -> Job:
        return self.w._start(self.pool, Job(work), on_finished=on_finished)

    # -- Make This Folder a Library -----------------------------------------------------
    def make_library(self) -> None:
        folder = self.w.folder
        if folder is None or self.library is not None:
            return
        if self.ask("Make This Folder a Library", MAKE_QUESTION.format(folder=folder)):
            self.make_library_now(folder)

    def make_library_now(self, folder: str) -> bool:
        from solidseas import model, pdm

        try:
            vault = pdm.init(folder)
        except Exception as exc:
            text = "The folder could not be made a library. " + error_message(model.error_info(exc))
            self._message(text)
            self.shown.emit({"ok": False, "kind": "init", "text": text})
            return False
        self.library = vault.root
        self.update_actions()
        self.w.file_history.refresh()
        name = os.path.basename(vault.root) or vault.root
        text = f"{name} is a library now: PDM > Check In keeps a version of its files."
        self._message(text)
        self.shown.emit({"ok": True, "kind": "init", "library": vault.root, "text": text})
        return True

    # -- Changes ------------------------------------------------------------------------
    def show_changes(self, path: str | None = None) -> QDialog | None:
        if self.library is None:
            return None
        path = path or self.w.current_folder() or self.library
        dialog = ChangesDialog(self.w, path)
        dialog.checkin_button.clicked.connect(lambda: (dialog.accept(), self.check_in([path])))
        self._open(dialog)

        def done(result: dict[str, Any]) -> None:
            if dialog in self.dialogs:
                dialog.show_result(result)
            self.shown.emit(result)

        self._start(status_work(path), done)
        return dialog

    # -- Check In ---------------------------------------------------------------------
    def checkin_choices(self, paths: list[str] | None) -> list[tuple[str, list[str]]]:
        if paths:
            return [(", ".join(os.path.basename(p) or p for p in paths), list(paths))]
        out = []
        selected = self.selected_file()
        if selected is not None and self.tracked(selected):
            out.append((f"The selected file, {os.path.basename(selected)}", [selected]))
        folder = self.w.current_folder() or self.library
        if folder is not None and _inside(folder, self.library):
            out.append((f"The folder {os.path.basename(folder) or folder}", [folder]))
        return out

    def check_in(self, paths: list[str] | None = None) -> QDialog | None:
        """The check-in dialog for ``paths`` (default: the selected file, or the chosen
        folder): it lists what changed there and takes the note."""
        if self.library is None:
            return None
        choices = self.checkin_choices(paths)
        if not choices:
            return None
        dialog = CheckinDialog(self.w, choices)
        self._open(dialog)

        def look() -> None:
            dialog.looking()
            self._generation += 1
            g = self._generation
            target = dialog.paths[0]

            def done(result: dict[str, Any]) -> None:
                if dialog in self.dialogs and g == self._generation:
                    dialog.show_result(result)
                self.shown.emit(result)

            self._start(status_work(target), done)

        def accepted() -> None:
            note, revision, state = dialog.values()
            self.checkin_now(dialog.paths, note, revision, state)

        dialog.what.currentIndexChanged.connect(lambda _i: look())
        dialog.accepted.connect(accepted)
        look()
        return dialog

    def checkin_now(
        self, paths: list[str], note: str, revision: str | None = None, state: str | None = None
    ) -> None:
        """Check ``paths`` in with ``note``, in a worker thread; the status bar says how it went."""
        self._message("Checking in...", 0)

        def done(result: dict[str, Any]) -> None:
            if result.get("ok"):
                text = checkin_summary(result["data"])
            else:
                text = "The check-in failed. " + error_message(result.get("error"))
            result["text"] = text
            self._message(text)
            self.w.file_history.refresh(paths)
            self.shown.emit(result)

        self._start(checkin_work(list(paths), note, revision, state), done)

    # -- Check Project -----------------------------------------------------------------
    def check_project(self, path: str | None = None) -> QDialog | None:
        if self.library is None:
            return None
        path = path or self.w.current_folder() or self.library
        project = self.project_of(path)
        if project is None:
            return None
        dialog = CheckDialog(self.w, os.path.basename(project))
        self._open(dialog)

        def done(result: dict[str, Any]) -> None:
            if dialog in self.dialogs:
                dialog.show_result(result)
            self.shown.emit(result)

        self._start(check_work(project), done)
        return dialog

    # -- Restore Version ------------------------------------------------------------------
    def restore_version(self) -> QDialog | None:
        found = self.restorable()
        if found is None:
            return None
        path, row = found
        dialog = RestoreDialog(self.w, path, row)
        dialog.accepted.connect(lambda: self.restore_now(path, row.ref, dialog.as_name))
        self._open(dialog)
        return dialog

    def restore_now(self, path: str, version: str, as_name: str | None = None) -> None:
        """Put ``version`` of the file back, in a worker thread (the current file is kept
        as a version first, by the vault)."""
        self._message("Putting the version back...", 0)

        def done(result: dict[str, Any]) -> None:
            if result.get("ok"):
                text = restore_summary(result["data"])
            else:
                text = "The version could not be put back. " + error_message(result.get("error"), path=path)
            result["text"] = text
            self._message(text)
            self.w.file_history.refresh([path])
            self.shown.emit(result)

        self._start(restore_work(path, version, as_name), done)

    def stop(self) -> None:
        """The window is closing: queued work is dropped; the window waits for :attr:`pool`."""
        self.pool.clear()
        for d in list(self.dialogs):
            d.close()


__all__ = ["PdmController", "finding_rows", "restore_summary", "status_line"]
