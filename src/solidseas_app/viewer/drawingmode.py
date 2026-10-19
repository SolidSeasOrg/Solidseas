"""The choice of how a drawing starts, and Express drawings (``docs/DRAWINGS.md``,
"Drawing modes").

Pressing Drawing (File > New Drawing, the toolbar button, Make Drawing in a right-click
menu) shows :class:`ModeDialog` unless the viewer's ``drawing_mode`` setting names a
mode already (chosen with "Remember my choice", or on the Settings window's Drawings
page):

* **Express** makes a simple drawing with no questions and opens it in the editor
  (:class:`ExpressRun`).
* **Guided** walks through the drawing a step at a time. It is shown, off, as coming
  soon.
* **Expert** opens the New Drawing wizard (:mod:`.drawingwizard`) with every option.

:class:`ExpressRun` does in a worker thread what the wizard does over its pages: reads
the part (``DrawingWorker.probe``), makes the drawing with
``solidseas.drawing.express``'s options and fields, and writes the ``.ssdrw`` in the
folder the wizard would offer (Drawing Settings' folder, else the part's own), under
the same rules (``drawingwizard.write_drawing``). It writes no PDF or DXF: the editor
exports them. The UI thread never waits on the drawing process.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QCommandLinkButton,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from . import experimental

EXPRESS, GUIDED, EXPERT = "express", "guided", "expert"
MODES = (EXPRESS, GUIDED, EXPERT)
MODE_TITLES = {EXPRESS: "Express", GUIDED: "Guided", EXPERT: "Expert"}
MODE_WORDS = {
    EXPRESS: "A simple drawing with the key sizes, straight to the editor",
    GUIDED: "Walks you through the drawing a step at a time",
    EXPERT: "Every option, in the New Drawing wizard",
}
AVAILABLE = (EXPRESS, EXPERT)  # Guided comes in a later release
REMEMBER_TEXT = "Remember my choice"
REMEMBER_TIP = "Start this kind of drawing straight away from now on. Settings > Drawings changes it."
MIN_WIDTH = 460  # pixels: each choice's words on one line or two
EXPRESS_BUSY = "An Express drawing is being made. Wait for it to open in the editor."


class ModeDialog(QDialog):
    """How to start the drawing of ``name``: Express, Guided (off, coming soon) or
    Expert, and whether to remember the choice. :attr:`chosen` is the mode clicked,
    None when cancelled; :attr:`remember` the tick."""

    def __init__(self, parent: QWidget | None, name: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"New Drawing of {name}")
        self.setMinimumWidth(MIN_WIDTH)
        self.chosen: str | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(experimental.note_label(experimental.drawings_note()))
        layout.addWidget(QLabel("How would you like to make the drawing?"))
        self.buttons: dict[str, QCommandLinkButton] = {}
        for mode in MODES:
            title = MODE_TITLES[mode] + ("" if mode in AVAILABLE else " (coming soon)")
            button = QCommandLinkButton(title, MODE_WORDS[mode])
            button.setEnabled(mode in AVAILABLE)
            button.clicked.connect(lambda _on=False, m=mode: self.choose(m))
            self.buttons[mode] = button
            layout.addWidget(button)
        self.remember_box = QCheckBox(REMEMBER_TEXT)
        self.remember_box.setToolTip(REMEMBER_TIP)
        layout.addWidget(self.remember_box)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        self.buttons[EXPRESS].setDefault(True)

    @property
    def remember(self) -> bool:
        return self.remember_box.isChecked()

    def choose(self, mode: str) -> None:
        if mode not in AVAILABLE:
            return
        self.chosen = mode
        self.accept()


def ask_mode(parent: QWidget | None, name: str) -> tuple[str | None, bool]:  # pragma: no cover - modal
    """The mode the user picks for the drawing of ``name`` and whether to remember it;
    (None, False) when cancelled."""
    dialog = ModeDialog(parent, name)
    try:
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None, False
        return dialog.chosen, dialog.remember
    finally:
        dialog.deleteLater()


def express_request(part: str, probe: Any, settings: Any) -> Any:
    """The :class:`.drawingwizard.Request` of an Express drawing of ``part``, read as
    ``probe``: the part's own unit, or for a part that states none the one SolidSeas
    guessed when Drawing Settings draw parts in their own unit; draft quality for a part
    over Drawing Settings' face count, as the wizard does."""
    from solidseas.drawing.express import express_fields, express_options

    from .drawingwizard import Request, unit_question

    units = "part"
    if unit_question(probe, settings) and probe.unit in ("in", "mm"):
        units = probe.unit
    faces = int(probe.counts.get("faces", 0)) if probe.counts else 0
    options = express_options(
        units=units,
        configuration=probe.configuration,
        quality="draft" if faces > settings.limits.draft_faces else "normal",
    )
    fields = express_fields(settings)
    return Request(part, options, tuple(sorted(fields.items())), settings)


def express_folder(part: str, settings: Any) -> str:
    """Where an Express drawing is written: Drawing Settings' folder, else the part's."""
    return settings.files.folder or os.path.dirname(part)


def make_express(
    worker: Any,
    part: str,
    configuration: str | None,
    settings: Any,
    opened: str | None,
    cancelled: Callable[[], bool] = lambda: False,
    running: threading.Event | None = None,
) -> Any:
    """Read ``part``, make its Express drawing and write it: the
    :class:`.drawingwizard.Written`. Raises what reading, making or writing raised; a
    part SolidSeas refuses raises ``InvalidArgumentError`` with the reason."""
    from solidseas.errors import ConfigurationNotFoundError, InvalidArgumentError

    from .drawingwizard import build_drawing, write_drawing

    def ask(fn: Callable[..., Any], *args: Any) -> Any:
        if running is not None:
            running.set()
        try:
            return fn(*args)
        finally:
            if running is not None:
                running.clear()

    try:
        probe = ask(worker.probe, part, configuration)
    except ConfigurationNotFoundError:
        if configuration is None:
            raise
        probe = ask(worker.probe, part, None)
    if probe.refused is not None:
        raise InvalidArgumentError(probe.refused, detail={"rule": probe.refused_rule or "refused"})
    request = express_request(part, probe, settings)
    answer = build_drawing(worker, request, cancelled, running)
    return write_drawing(answer, express_folder(part, settings), {}, part, opened)


class ExpressRun(QObject):
    """One Express drawing in progress, in a pool thread of its own. ``done(path)`` is
    emitted once it is written; ``failed(words)`` when it could not be made or
    written."""

    done = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        parent: QObject | None,
        worker: Any,
        part: str,
        *,
        configuration: str | None,
        settings: Any,
        folder: str | None,
    ) -> None:
        super().__init__(parent)
        self.worker = worker
        self.part = os.path.abspath(part)
        self.configuration = configuration
        self.settings = settings
        self.opened = folder
        self.finished = False
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.job: Any = None

    def start(self) -> None:
        from .drawingwizard import error_words
        from .workers import Job

        running = threading.Event()

        def work(_emit: Any, cancelled: Callable[[], bool]) -> dict:
            try:
                written = make_express(
                    self.worker,
                    self.part,
                    self.configuration,
                    self.settings,
                    self.opened,
                    cancelled,
                    running,
                )
            except Exception as exc:  # said to the user, never raised in the pool
                return {"error": error_words(exc)}
            return {"path": written.path}

        self.job = Job(work)
        self.job.signals.finished.connect(self._finished)
        self.pool.start(self.job)

    def wait(self, ms: int = 600000) -> bool:
        """Wait for the pool (tests)."""
        return self.pool.waitForDone(ms)

    def _finished(self, result: Any) -> None:
        self.finished = True
        if isinstance(result, dict) and result.get("path"):
            self.done.emit(result["path"])
        else:
            error = result.get("error") if isinstance(result, dict) else None
            self.failed.emit(str(error or "the drawing could not be made"))


__all__ = [
    "AVAILABLE",
    "EXPERT",
    "EXPRESS",
    "GUIDED",
    "MODES",
    "MODE_TITLES",
    "MODE_WORDS",
    "ExpressRun",
    "ModeDialog",
    "ask_mode",
    "express_request",
    "make_express",
]
