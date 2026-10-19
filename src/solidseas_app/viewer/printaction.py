"""The 3D Print button, its right-click entries and the Settings > 3D Print Program
menu: the Qt side of :mod:`.printing`.

3D Print exports the part or assembly the details panel shows, in the
configuration it shows, for the program chosen, and starts that program with the
file. The right-click menus of the document list, the rows of the Components, BOM
and References tabs (and of a drawing's sheets and models), the 3D view and its
legend print another model the same way (:meth:`PrintController.add_action`): each
gives a :class:`PrintTarget`, and every print goes through
:meth:`PrintController.start`. The file is written next to the model, or in the
temporary folder when Settings > Save 3D Print Files Next to the Model is off or the
model's folder cannot take it (:func:`.printing.export_for_print`); the status line
says where, with the file's full path, and why when it is not next to the model,
and which configuration was exported when a part stores no geometry of the one asked
for. It is sent in the format chosen for the program, from those it takes
(Settings > 3D Print Program, or Preferences); a STEP that cannot be made (an
assembly, a part the STEP export refuses, or a 3D file that is neither a SOLIDWORKS
part nor a Parasolid file's part) goes as 3MF, and the status line says why.

The export runs in a process of its own (:func:`.printing.export_in_process`),
waited on from a pool of the controller's own, so the details panel never waits
behind it; while it runs the button and every menu's 3D Print entry are Cancel 3D
Print (one to a menu), which ends that process at once, as closing the window does.
The program is started on the UI thread through :func:`.printing.launch`, looked up
when it is needed so that tests replace it, and the self-test's dry run never calls
it: it records the program and the arguments it would have started. Every problem is
said in plain words: a component whose file was not found has its entry off with the
reason (:meth:`PrintController.add_unavailable`), and a message box says the rest: no
program chosen or found, a program no longer where it was, an export that failed.

Any 3D file SolidSeas reads prints the same way, exported from its geometry in the
export's process, and as STEP too when it is a Parasolid file's part. With
Settings > Open 3MF and STL Files As They Are on (off by default), a 3MF or STL
file whose format the program takes is opened as it is, with nothing written, so a
slicer project keeps its plates and settings; the program then has the user's own
file open and may save over it, the second exception to the read-only rule
AGENTS.md records. A STEP is never opened as it is: a print sent as STEP is a new
file.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from PySide6.QtCore import QObject, Qt, QThreadPool, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QVBoxLayout,
)

from . import printing, reading
from .wording import error_message, plural, refusal_text, tip
from .workers import Job

TITLE = "3D Print"
PRINT_TEXT = "&3D Print..."
PRINT_TIP = "Export the selected part or assembly for 3D printing and open it in your slicer program"
CANCEL_TEXT = "Cancel &3D Print"
CANCEL_ITEM = "Cancel 3D Print"  # a menu's entry while an export runs
CANCEL_TIP = "Stop preparing the 3D print; nothing is sent to the program"
MENU_TITLE = "3D Print Pro&gram"
CHOOSE_OTHER = "Choose Another Program..."
WHERE_TO_CHANGE = "Settings > 3D Print Program changes it."
HERE_TEXT = "Save 3D Print Files &Next to the Model"
HERE_TIP = (
    "Save each 3D print file in the folder of the model it was made from, named with the date, "
    "bracket 2026-10-03.3mf; a second one that day is bracket 2026-10-03 (2).3mf, and of a name and "
    "format the highest number is the newest. Off, or where that folder cannot take it, the file goes "
    "to the system's temporary folder."
)
FORMAT_TIPS = {
    "3mf": "Triangles in millimetres, an assembly's parts placed in one file: what slicers prefer",
    "stl": "Triangles in one mesh, with no units in the file (written in millimetres)",
    "step": "The part's exact faces and edges, which the slicer turns into triangles itself, from a "
    "SOLIDWORKS part or a Parasolid file; an assembly, a part STEP cannot hold without loss, or a 3D file of "
    "another format is sent as 3MF and the status line says why",
}


@dataclass(frozen=True)
class PrintTarget:
    """What a 3D Print exports: the document at ``source`` (read as the details panel
    reads it), the opened ``folder`` an assembly's component files are found in, the
    ``configuration`` to export (None: the active one) and the document's ``name``,
    for what is said about it and, for a nested document, its file's name. ``virtual``
    names, by their stored paths, the virtual components to find inside it, one inside
    the other, when the window does not know which nested document holds them (a
    virtual part of a sub-assembly, :func:`.printing.find_virtual`). ``doc_type``,
    ``part`` or ``assembly`` when the window knows it, words the progress message: an
    assembly asked for as STEP is made as 3MF (:data:`.printing.STEP_FALLBACK`), as is
    a 3D file of a format the STEP export does not write (:attr:`model_format`).
    ``content_format`` is the registry id of what the file holds, as the listing or the
    details found it (``solidworks`` for a SOLIDWORKS document), when the window knows
    it; the export goes by the content too, whatever the file's name says."""

    source: reading.Source
    folder: str
    configuration: str | None
    name: str
    virtual: tuple[str, ...] = ()
    doc_type: str | None = None
    content_format: str | None = None

    @property
    def model_format(self) -> str | None:
        """The registry id of a 3D file of another format than SOLIDWORKS: what it holds
        (:attr:`content_format`), else what its name says when that is not known; None
        for a SOLIDWORKS document."""
        if self.source.nested:
            return None
        if self.content_format is not None:
            return None if self.content_format == "solidworks" else self.content_format
        return printing.format_of(self.source.path)


def item_text(text: str) -> str:
    """A menu entry's text that shows a document's name as it is: ``&`` marks a
    keyboard shortcut in Qt, so it is doubled."""
    return text.replace("&", "&&")


class ChooseProgramDialog(QDialog):
    """Which program 3D Print sends to: one found on this computer, or another one the
    user picks (``pick`` asks for its file)."""

    def __init__(self, parent, detected: list[printing.Program], pick) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose a 3D print program")
        self.chosen: printing.Program | None = None
        self._pick = pick
        text = (
            "Which program should 3D Print open the part or assembly in?"
            if detected
            else "No slicer program SolidSeas knows (Bambu Studio, OrcaSlicer, PrusaSlicer, UltiMaker Cura) "
            "was found on this computer. Choose the program to open 3D prints in."
        )
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        self.list = QListWidget()
        for p in detected:
            item = QListWidgetItem(p.name)
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(tip(p.path))
            self.list.addItem(item)
        self.list.setVisible(bool(detected))
        if detected:
            self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda _item: self._use_selected())
        other = QPushButton(CHOOSE_OTHER)
        other.clicked.connect(self._other)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(detected))
        buttons.accepted.connect(self._use_selected)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(self.list)
        layout.addWidget(other)
        note = QLabel(f"SolidSeas remembers the choice. {WHERE_TO_CHANGE}")
        note.setTextFormat(Qt.TextFormat.PlainText)
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def _use_selected(self) -> None:
        item = self.list.currentItem()
        if item is not None:
            self.chosen = item.data(Qt.ItemDataRole.UserRole)
            self.accept()

    def _other(self) -> None:
        program = self._pick(self)
        if program is not None:
            self.chosen = program
            self.accept()


class PrintController(QObject):
    """The 3D Print action, its menu of programs and formats, and the print itself.

    ``detect``, ``pick_file`` (a program's file, or "" when cancelled) and ``ask``
    (the chooser dialog) are attributes so tests can stand in for them, and so are
    ``launch`` and ``export`` (None: :func:`.printing.launch` and
    :func:`.printing.export_in_process`, looked up each time) and ``today`` (the date
    a print file is named with); ``out_base`` is the folder under which the temporary
    export folder is made (None: the system's temporary folder). With ``dry_run`` a
    print exports as usual and records what it would start in :attr:`last` instead
    of starting it; with ``confine`` (the self-test's folder) no file is written next
    to a model outside that folder: it goes to the temporary folder, which says why."""

    finished = Signal(object)  # what a print did (``last``), or why it did not

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.detect = printing.detect
        self.launch = None
        self.export = None
        self.pool = QThreadPool(self)  # waits on the export's process, apart from the details panel
        self.pool.setMaxThreadCount(1)
        self._job: Job | None = None
        self.out_base: str | None = None
        self.today: Callable[[], str] = printing.today
        self.dry_run = False
        self.confine: str | None = None
        self.last: dict[str, Any] | None = None
        self.pick_file = self._pick_file
        self.ask = self._ask
        self.busy = False
        self.said: str | None = None  # the status line's last word on a print, while it shows
        self._detected: list[printing.Program] | None = None
        style = window.style()
        self._icons = (
            style.standardIcon(QStyle.StandardPixmap.SP_ArrowForward),
            style.standardIcon(QStyle.StandardPixmap.SP_BrowserStop),
        )
        self.action = QAction(self._icons[0], PRINT_TEXT, window)
        self.action.setShortcut("Ctrl+P")
        self._show_busy(False)
        self.action.triggered.connect(self.print_selection)
        self.menu = QMenu(MENU_TITLE, window)
        self.menu.setToolTipsVisible(True)
        self.menu.aboutToShow.connect(self.fill_menu)  # programs are looked for when it opens

    # -- the program ---------------------------------------------------------------------
    def detected(self, refresh: bool = False) -> list[printing.Program]:
        if self._detected is None or refresh:
            try:
                self._detected = list(self.detect())
            except Exception:  # an unreadable registry or folder: nothing found
                self._detected = []
        return self._detected

    @property
    def choice(self) -> printing.PrintChoice:
        return printing.load_choice(self.window.store)

    def _say(self, text: str, ms: int) -> None:
        """How a print ended, on the status line, for ``ms`` or until another document is
        shown (:meth:`document_changed`)."""
        self.window.statusBar().showMessage(text, ms)
        self.said = text

    def document_changed(self) -> None:
        """Another document is shown: the line on how the last print ended, which was
        about the one before, goes, unless something else has replaced it since."""
        bar = self.window.statusBar()
        if self.said is not None and bar.currentMessage() == self.said:
            bar.clearMessage()
        self.said = None

    def _save(self, choice: printing.PrintChoice) -> None:
        if not printing.save_choice(self.window.store, choice):
            self.window.statusBar().showMessage(
                "The 3D print program could not be saved in the settings.", 8000
            )

    def current(self) -> tuple[printing.PrintChoice, printing.Program | None]:
        """The choice and the program it names; with nothing chosen, Bambu Studio when it
        is installed (not saved until it is used)."""
        choice = self.choice
        detected = self.detected()
        if choice.program is None:
            choice = printing.first_choice(detected) or choice
        return choice, printing.resolve(choice, detected)

    def describe(self) -> str:
        return printing.describe(self.choice, self.detected())

    def set_program(self, program: printing.Program) -> None:
        """Send to ``program`` from now on; a format it does not take falls back to its
        first, and the status line says so."""
        old = self.choice
        self._save(printing.with_program(old, program))
        said = f"3D Print now opens {program.name}{printing.dropped_text(old, program)}."
        self.window.statusBar().showMessage(said, 8000)
        self.fill_menu()

    def set_format(self, fmt: str) -> None:
        """Send ``fmt`` from now on, when the program takes it."""
        choice, program = self.current()
        if program is None or fmt not in program.formats:
            return
        self._save(replace(printing.with_program(choice, program), format=fmt))
        label = printing.FORMAT_LABELS[fmt]
        self.window.statusBar().showMessage(f"3D Print now sends {label} to {program.name}.", 6000)
        self.fill_menu()

    def preferences_options(self) -> dict[str, Any]:
        """What Preferences shows of the choice: the program in a line, and the formats it
        takes with the one it gets, to choose from beside it (none while no program is
        chosen or found: the line says so)."""
        choice, program = self.current()
        if program is None:
            return {"print_text": self.describe(), "print_formats": (), "print_format": None}
        return {
            "print_text": printing.describe(self.choice, self.detected(), with_format=False),
            "print_formats": program.formats,
            "print_format": printing.format_for(program, choice),
        }

    def _pick_file(self, parent) -> printing.Program | None:
        start = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles") or os.path.expanduser("~")
        filters = "Programs (*.exe)" if os.name == "nt" else "All files (*)"
        path, _ = QFileDialog.getOpenFileName(parent, "Choose the 3D print program", start, filters)
        if not path:
            return None
        path = os.path.normpath(path)
        problem = printing.program_problem(path)
        if problem is not None:
            self._message(QMessageBox.Icon.Warning, f"That program cannot be used: {problem}.\n\n{path}")
            return None
        return printing.other_program(path)

    def choose_other(self) -> None:
        program = self.pick_file(self.window)
        if program is not None:
            self.set_program(program)

    def _ask(self, detected: list[printing.Program]) -> printing.Program | None:
        dialog = ChooseProgramDialog(self.window, detected, self.pick_file)
        try:
            return dialog.chosen if dialog.exec() == QDialog.DialogCode.Accepted else None
        finally:
            dialog.deleteLater()

    def fill_menu(self) -> None:
        """The detected programs and the one chosen, Choose Another Program..., and the
        formats the program takes (none until one is chosen or found)."""
        menu = self.menu
        menu.clear()
        detected = self.detected(refresh=True)
        choice, program = self.current()
        group = QActionGroup(menu)
        entries = list(detected)
        if program is not None and program.key == printing.OTHER:
            entries.append(program)
        for p in entries:
            a = menu.addAction(p.name)
            a.setCheckable(True)
            a.setChecked(program is not None and p.key == program.key and p.path == program.path)
            a.setToolTip(tip(p.path))
            a.setStatusTip(p.path)
            a.triggered.connect(lambda _on=False, p=p: self.set_program(p))
            group.addAction(a)
        if program is not None and program.key != printing.OTHER and not program.path:
            a = menu.addAction(f"{program.name} (not found)")
            a.setCheckable(True)
            a.setChecked(True)
            a.setEnabled(False)
        if not entries:
            none = menu.addAction("No known program found")
            none.setEnabled(False)
        menu.addSeparator()
        menu.addAction(CHOOSE_OTHER, self.choose_other)
        menu.addSeparator()
        if program is None:
            return
        formats = QActionGroup(menu)
        current = printing.format_for(program, choice)
        for fmt in program.formats:  # only what the program takes
            a = menu.addAction(f"Send as {printing.FORMAT_LABELS[fmt]}")
            a.setCheckable(True)
            a.setChecked(fmt == current)
            a.setToolTip(tip(FORMAT_TIPS[fmt]))
            a.setStatusTip(FORMAT_TIPS[fmt])
            a.triggered.connect(lambda _on=False, f=fmt: self.set_format(f))
            formats.addAction(a)

    # -- printing ------------------------------------------------------------------------
    def _message(self, icon: QMessageBox.Icon, text: str) -> None:
        from .window import show_message

        show_message(self.window, icon, TITLE, text)

    def _show_busy(self, busy: bool) -> None:
        """The button is 3D Print, or Cancel 3D Print while an export runs."""
        a = self.action
        a.setIcon(self._icons[1 if busy else 0])
        a.setText(CANCEL_TEXT if busy else PRINT_TEXT)
        a.setIconText("Cancel Print" if busy else TITLE)
        a.setStatusTip(CANCEL_TIP if busy else PRINT_TIP)
        a.setToolTip(CANCEL_TIP if busy else PRINT_TIP)

    def _done(self, outcome: dict[str, Any]) -> None:
        self.last = outcome
        self.busy = False
        self._job = None
        self._show_busy(False)
        self.window._update_actions()
        self.finished.emit(outcome)

    def cancel(self) -> None:
        """Stop the export that is running: its process is ended at once."""
        if self._job is not None:
            self._job.cancel()

    def shutdown(self) -> None:
        """The window is closing: stop the export; the window waits for :attr:`pool`."""
        self.cancel()
        self.pool.clear()

    def where_text(self) -> str:
        """Where a print file goes, as the setting says, for tooltips."""
        if self.window.settings.print_next_to_model:
            return "next to the model, named with today's date"
        return "in the system's temporary folder"

    def add_action(
        self,
        menu: QMenu,
        text: str,
        resolve: Callable[[], "PrintTarget | str | None"],
        *,
        what: str = "it",
    ) -> QAction:
        """A 3D Print entry for ``menu``, reading ``text`` (a document's name in it is
        shown as it is), which prints what ``resolve`` gives once it is chosen: a
        :class:`PrintTarget`, a reason it cannot be printed, which is said in a message,
        or None for nothing (a question was cancelled). While an export runs it is
        Cancel 3D Print instead, as the button is, and a menu that has that entry
        already gets no second one (the 3D view's offers several prints). ``what``
        names the model in its tooltip."""
        if self.busy:
            for action in menu.actions():
                if action.text() == CANCEL_ITEM:
                    return action
            action = menu.addAction(self._icons[1], CANCEL_ITEM)
            action.setToolTip(tip(CANCEL_TIP))
            action.setStatusTip(CANCEL_TIP)
            action.triggered.connect(self.cancel)
            return action
        action = menu.addAction(self._icons[0], item_text(text))
        line = f"Export {what} for 3D printing, save it {self.where_text()}, and open it in your slicer"
        action.setToolTip(tip(line))
        action.setStatusTip(line)
        action.triggered.connect(lambda _on=False: self.print_resolved(resolve))
        return action

    def add_unavailable(self, menu: QMenu, text: str, reason: str, why: str) -> QAction:
        """A 3D Print entry for ``menu`` that is off, its ``reason`` in a few words after
        ``text`` and ``why`` in full in its tooltip, as Show in folder list is for a
        file that is not found. While an export runs it is that export's Cancel."""
        if self.busy:
            return self.add_action(menu, text, lambda: None)
        action = menu.addAction(self._icons[0], f"{item_text(text)} ({reason})")
        action.setEnabled(False)
        action.setToolTip(tip(why))
        action.setStatusTip(why.split("\n", 1)[0])
        return action

    def print_resolved(self, resolve: Callable[[], "PrintTarget | str | None"]) -> None:
        """Print what ``resolve`` gives (see :meth:`add_action`); while an export runs,
        cancel it."""
        if self.busy:
            self.cancel()
            return
        got = resolve()
        if isinstance(got, str):  # a component whose file cannot be found, or a document that cannot be read
            if not self.dry_run:  # a dry run never shows a dialog
                self._message(QMessageBox.Icon.Information, got)
            self._done({"ok": False, "cannot": got})
        elif got is not None:
            self.start(got)

    def print_selection(self) -> None:
        """Export what the details panel shows for the chosen program and open it there;
        while an export runs, cancel it."""
        if self.busy:
            self.cancel()
            return
        target = self.window.print_target()
        if target is not None:
            self.start(target)

    def start(self, target: PrintTarget) -> None:
        """Export ``target`` for the chosen program, asking for one the first time when
        Bambu Studio is not installed, and open it there: the one way every 3D Print
        goes, from the button, a right-click menu or the dry run."""
        if self.busy:
            return
        source, folder, configuration = target.source, target.folder, target.configuration
        dropped = ""
        detected = self.detected(refresh=True)
        choice, program = self.current()
        chosen_now = self.choice.program is None and program is not None  # Bambu Studio, not asked
        if program is None:
            if self.dry_run:  # the window would ask; a dry run never shows a dialog
                self._done({"ok": False, "would_ask": True, "detected": [p.name for p in detected]})
                return
            program = self.ask(detected)
            if program is None:
                return
            dropped = printing.dropped_text(choice, program)
            choice = printing.with_program(choice, program)
        if self.choice != choice:
            self._save(choice)  # remembered: Bambu Studio the first time, or what was asked
        problem = printing.program_problem(program.path) if program.path else "it is no longer installed"
        if problem is not None:
            self._message(
                QMessageBox.Icon.Warning,
                f"{program.name} cannot be started: {problem}.\n\nChoose the program again: {WHERE_TO_CHANGE}"
                + (f"\n\n{program.path}" if program.path else ""),
            )
            self._done({"ok": False, "program": program.name, "problem": problem})
            return
        fmt = printing.format_for(program, choice)
        # A document that cannot go as STEP goes as 3MF: a 3MF file then is the format sent,
        # and Open 3MF and STL Files As They Are opens it as it is, as when 3MF is chosen.
        made, why = printing.sent_format(fmt, target.model_format, target.doc_type)
        if (
            self.window.settings.print_as_is
            and not source.nested
            and not target.virtual
            and printing.as_is(source.path, made, target.model_format)
        ):
            self._open_as_is(target, program, made, chosen_now, asked=fmt, why=why)
            return
        request = {
            "path": source.path,
            "folder": folder,
            "fmt": fmt,
            "within": source.within,
            "nested": tuple(source.nested),
            "virtual": tuple(target.virtual),
            "name": target.name,
            "configuration": configuration,
            "out_base": self.out_base,
            "next_to_model": bool(self.window.settings.print_next_to_model),
            "confine": self.confine,
            "date": self.today(),
        }
        export = self.export or printing.export_in_process

        def work(_emit, cancelled):
            return export(request, cancelled)

        self.busy = True
        self._show_busy(True)
        self.window.statusBar().showMessage(
            f"Preparing the {printing.FORMAT_LABELS[made]} of {target.name} for {program.name}... "
            "(Cancel 3D Print stops it)"
        )
        self._job = Job(work)
        self.window._start(
            self.pool,
            self._job,
            on_finished=lambda r: self._exported(r, program, source.path, chosen_now, dropped),
        )
        self.window._update_actions()

    def _open_as_is(
        self,
        target: PrintTarget,
        program: printing.Program,
        fmt: str,
        chosen_now: bool = False,
        *,
        asked: str | None = None,
        why: str | None = None,
    ) -> None:
        """Open a 3MF or STL file in ``program``, which is sent its format, as it is: nothing
        is exported or written (a dry run records what it would start). ``asked`` is the
        format chosen and ``why`` why the file goes as ``fmt`` instead (a 3MF asked for as
        STEP)."""
        path = target.source.path
        outcome: dict[str, Any] = {
            "ok": True,
            "as_is": True,
            "program": program.name,
            "key": program.key,
            "executable": program.path,
            "arguments": [path],
            "dry_run": self.dry_run,
            "file": path,
            "format": fmt,
            "requested_format": asked or fmt,
            "format_fallback": why,
            "source": path,
            "source_format": target.model_format,
            "document": target.name,
        }
        if not self.dry_run:
            try:
                (self.launch or printing.launch)(program.path, path)
            except OSError as exc:
                self._message(
                    QMessageBox.Icon.Warning, f"{program.name} could not be started: {exc.strerror or exc}."
                )
                self._done({**outcome, "ok": False, "started": False})
                return
        opened = (
            f"{program.name} was not started (a dry run)" if self.dry_run else f"Opened it in {program.name}"
        )
        text = f"{target.name} is already {printing.A_FORMAT[fmt]} file: {opened} as it is, and nothing "
        text += "was written"
        if why:
            asked_label = printing.FORMAT_LABELS.get(asked or "", asked)
            text += f" (sent as {printing.FORMAT_LABELS[fmt]}, not {asked_label}, as {why})"
        text += (
            f"; saving in {program.name} replaces this file. Settings > Open 3MF and STL Files As They Are "
            "changes this."
        )
        if chosen_now:
            text += f" {program.name} is now the 3D Print program; {WHERE_TO_CHANGE}"
        self._say(text, 12000)
        self._done({**outcome, "started": not self.dry_run, "chosen_now": chosen_now, "note": text})

    def _exported(
        self,
        result: dict[str, Any],
        program: printing.Program,
        path: str,
        chosen_now: bool = False,
        dropped: str = "",
    ) -> None:
        self.window.statusBar().clearMessage()
        if result.get("cancelled"):
            chosen = f" {program.name} is now the 3D Print program; {WHERE_TO_CHANGE}" if chosen_now else ""
            self._say("3D Print cancelled: nothing was sent." + chosen, 6000)
            self._done({"ok": False, "program": program.name, "cancelled": True})
            return
        if not result.get("ok"):
            err = result.get("error") or {}
            if err.get("code") == "output_refused":
                text = f"Nothing was exported.\n\n{refusal_text(err)}"
            else:
                text = "The export for 3D printing failed.\n\n" + error_message(err, path=path)
            self._message(QMessageBox.Icon.Warning, text)
            self._done({"ok": False, "program": program.name, "error": err})
            return
        data = result["data"]
        outcome = {
            "ok": True,
            "program": program.name,
            "key": program.key,
            "executable": program.path,
            "arguments": [data["file"]],
            "dry_run": self.dry_run,
            "memory_peak": result.get("memory_peak"),
            "next_to_model": bool(self.window.settings.print_next_to_model),
            **data,
        }
        if not self.dry_run:
            try:
                (self.launch or printing.launch)(program.path, data["file"])
            except OSError as exc:
                self._message(
                    QMessageBox.Icon.Warning,
                    f"{program.name} could not be started: {exc.strerror or exc}.\n\n"
                    f"The export is ready to open by hand:\n{data['file']}",
                )
                self._done({**outcome, "ok": False, "started": False})
                return
        notes = []
        if data.get("format_fallback"):
            asked = printing.FORMAT_LABELS.get(data.get("requested_format") or "", "STEP")
            notes.append(
                f"sent as {printing.FORMAT_LABELS[data['format']]}, not {asked}, as {data['format_fallback']}"
            )
        step = data.get("step")
        if step and not step["exact"] and step.get("max_deviation_mm") is not None:
            deviation = step["max_deviation_mm"]
            notes.append(f"B-splines within {deviation:.3g} mm of the geometry where STEP has no exact form")
        fallback = data.get("display_mesh_objects", 0)
        content = data.get("source_format") or ("solidworks" if printing.format_of(path) is None else "")
        saved_by = "SOLIDWORKS saved" if content == "solidworks" else "the file stores"
        if fallback and data["doc_type"] == "assembly":
            notes.append(
                f"{plural(fallback, 'part')} from the display mesh {saved_by}, as the part's file was "
                "not found or has no solid body to use"
            )
        elif fallback:
            notes.append(f"made from the display mesh {saved_by}, as the part has no solid body to use")
        asked, made = data.get("requested_configuration"), data.get("configuration")
        if asked and made and asked != made:
            notes.append(f"in configuration {made}, as the part stores no geometry of {asked}")
        if not data["closed"]:
            notes.append("not closed: the slicer may have to repair it")
        if data["skipped"]:
            notes.append(f"{plural(data['skipped'], 'instance')} left out")
        text = saved_text(outcome, program.name, dry_run=self.dry_run)
        text += f" ({'; '.join(notes)})." if notes else "."
        if chosen_now:  # said once, after the send, where no later message replaces it
            text += f" {program.name} is now the 3D Print program; {WHERE_TO_CHANGE}"
        elif dropped:
            text += f" {program.name} is now the 3D Print program{dropped}."
        long = (
            chosen_now or bool(dropped or data.get("format_fallback")) or data.get("place") == printing.TEMP
        )
        self._say(text, 20000 if long else 12000)
        self._done({**outcome, "started": not self.dry_run, "chosen_now": chosen_now, "note": text})


def saved_text(data: dict[str, Any], program: str, *, dry_run: bool = False) -> str:
    """Where a print file was written, with its full path, and that it was opened in
    ``program``; why it is in the temporary folder: the model's folder could not take
    it, or the setting sends every print there. Without a full stop, for notes to
    follow."""
    opened = f"{program} was not started (a dry run)" if dry_run else f"opened it in {program}"
    if data.get("place") == printing.TEMP:
        why = data.get("fallback") or (printing.SETTING_OFF if data.get("next_to_model") is False else None)
        if why:
            return f"Saved {data['file']} in the temporary folder, not next to the model, as {why}; " + opened
    joined = "; " if dry_run else " and "
    return f"Saved {data['file']}{joined}{opened}"
