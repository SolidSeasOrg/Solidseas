"""The modeling assistant's window, in Review mode and Automatic mode
(``docs/ASSISTANT.md``).

The person picks a SOLIDWORKS session and a document, describes a change or types
code, and sees what the model drafts in an editable console before anything runs; or,
with Automatic ticked, states a goal the model plans once and SolidSeas carries out:

* **Session and document.** From :class:`.session.Sessions`, listed on a worker
  thread. A part's snapshot is read when it is picked, for the model summary.
* **Draft.** The request is capped and redacted (:func:`solidseas.ai.context.prepare_request`),
  the part summarized (:func:`solidseas.ai.context.build_model_summary`, names only
  when "Send my feature and property names" is ticked), and the provider's
  ``draft_change`` called on a worker thread with a cancellation token Stop sets.
  "What the AI sees" shows the exact prompt of the next call before it is sent.
* **Console.** The draft's code goes into an editor the person may change, with the
  model's explanation beside it and, beside Run, the warning that anything the
  script does outside the SOLIDWORKS undo list cannot be reverted. Nothing runs
  until Run is pressed; then the one-writer mutex is taken, the session writes the
  safety copy and opens the undo entry, and :class:`.runner.Runner` runs the code in
  its child process, which reaches SOLIDWORKS only through the session's named
  operations. The undo entry is closed and the mutex given back however the script
  ends.
* **Automatic.** The goal and the part's summary go to the provider's ``plan_steps``
  on a worker thread; the validated plan appears in the Plan panel, every argument with
  where its value came from. A plan whose only changes to what the person has are values
  they said starts by itself; any other waits for Run plan
  (:func:`.automatic.confirmation`). :func:`.automatic.start_run` makes the checks and
  writes the safety copy, and :class:`.run.AutomaticRun` carries the steps out on a
  worker thread, each checked and journaled; Stop ends it between steps. Afterwards Keep
  keeps the part as it is and Revert takes the steps off, newest first. The machine
  policy can turn Automatic mode off; then the box is greyed with "Set by your
  administrator". When the window opens, the folders of runs that ended and have not
  changed for :data:`.automatic.KEEP_DAYS` days are removed on a thread of their own
  (:func:`.automatic.clean_old_runs`), and then each run whose process ended before Keep
  or Revert is offered, one at a time, in a box above the rest: what it was and how far
  it got, with Revert, Keep and Decide Later (:mod:`.unfinished`). Nothing is done to
  such a run until the person chooses.
* **Pictures.** "Show the AI a picture of the part", off until ticked, sends a picture
  of the part as last saved with a draft or a plan (:mod:`.picture`). In Automatic mode,
  "Show it the part after each step", usable only while the first is ticked, has the
  model look at a picture of the part after each step that passed its checks
  (:class:`.picture.ModelLook`); a look that says the part does not look right ends the
  run there. Both are greyed out under the ``DisableImages`` policy, and What the AI sees
  says what goes.
* **The provider** is built from the saved AI settings (:mod:`.aisettings`, ``AI.json``)
  through the factory, and built again whenever the AI settings page saves a change.
  With none configured every AI control is hidden; one the machine policy refuses keeps
  them visible and disabled with "Set by your administrator". Whenever drafting is not
  available the window says why, in plain text, beside a button that opens the AI
  settings page (:mod:`.settings_dialog`), which the AI Settings button opens too.
* **Plain text everywhere.** Model text, document text and script output go into
  plain-text editors and labels; tooltips are escaped. Nothing is rendered as rich
  text, so a reply cannot make the window follow a link or load an image.
* **Always on top**, never owned by a SOLIDWORKS window. While a SOLIDWORKS call has
  waited more than :data:`BUSY_SECONDS` the window drops that flag, so it never
  covers a dialog SOLIDWORKS is waiting on, and says so; the flag comes back when
  the call returns.
"""

from __future__ import annotations

import html
import threading
import time
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from solidseas import policy
from solidseas.ai.base import CallOptions
from solidseas.ai.context import build_model_summary, prepare_request
from solidseas.ai.errors import AI_ERROR_CODES, AIError
from solidseas.ai.http import Cancel
from solidseas.ai.prompts import Plan, draft_prompt, plan_prompt
from solidseas.ai.usage import DEFAULT_RUN_TOKENS, RunBudget

from . import picture
from .aisettings import ADMIN, AIConfig, AISettingsStore
from .automatic import KEEP_DAYS, RunRefused, clean_old_runs, confirmation, start_run
from .run import AutomaticRun, RunOutcome, SessionTarget, plan_text
from .runner import Runner, RunResult
from .session import LiveDocument, LiveSession, NoSessions, SessionList, Sessions
from .unfinished import UnfinishedRun, find_unfinished
from .writer import WriterBusyError, take_writer

TITLE = "SolidSeas Modeling Assistant"
BUSY_SECONDS = 3.0
WARNING = (
    "The script runs with your own rights, so read it before you press Run. Anything it does outside "
    "the SOLIDWORKS undo list, such as writing a file, changing an option or editing a custom property, "
    "cannot be reverted. Its SOLIDWORKS operations come off with one Ctrl+Z."
)
NAMES_TEXT = "Send my feature and property names"
REVIEW_TEXT = "Review mode: the model drafts code; nothing runs until you press Run."
AUTOMATIC_TEXT = (
    "Automatic mode: the model plans your goal once, and SolidSeas carries out the plan on the part, "
    "checking each step and keeping it revertible. A plan that would overwrite something you did not "
    "say waits for Run plan."
)
NO_PART_TO_PLAN = "Automatic mode works on one part: pick a part, and wait until it has been read."
NO_PART = "No part is picked: the model drafts without a summary of one."
NOT_SET_UP = (
    "No AI provider is set up, so drafting is not available. Choose one in AI Settings; code you type "
    "in the console still runs."
)


def _plain_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


def _tip(text: str) -> str:
    return html.escape(text)


def unavailable_text(provider: Any) -> str | None:
    """Why drafting is not available with ``provider``, in plain words; None when it is."""
    if provider is None:
        return NOT_SET_UP
    if getattr(provider, "name", "") != "noop":
        return None
    reason = getattr(provider, "reason", "not_configured")
    message = str(getattr(provider, "message", "") or "")
    if reason == "not_configured" and message in ("", AI_ERROR_CODES["not_configured"]):
        return NOT_SET_UP
    return f"Drafting is not available. {message}".strip()


class _Signals(QObject):
    listed = Signal(object)
    snapshot = Signal(object, object)  # (document, snapshot or the error text)
    drafted = Signal(object, object)  # (result or None, error text or None)
    output = Signal(str, str)
    begun = Signal(object, object)  # (safety copy path or None, error or None)
    finished = Signal(object)
    ended = Signal()  # the script's undo entry closed and the session given back
    log = Signal(str)
    planned = Signal(object, object, object)  # (result or None, summary, error text or None)
    run_started = Signal(object)  # the AutomaticRun
    run_event = Signal(str, object)  # (kind, data), from the run's thread
    run_ended = Signal(object)  # the RunOutcome, or why the run did not start
    reverted = Signal(object)  # revert's messages
    unfinished = Signal(object)  # the runs whose process ended before Keep or Revert
    offer_reverted = Signal(object, object)  # (the UnfinishedRun, its RevertResult or an error)


class AssistantWindow(QWidget):
    """The window. ``ai`` says where the AI settings, keys and usage live (settings kept
    in memory when it is None); the provider is built from them through the factory unless
    ``provider`` is given (tests), and built again after the AI settings page saves.
    ``sessions`` lists and reaches SOLIDWORKS; ``runner`` runs approved code;
    ``runs_folder`` replaces the runs folder (:func:`.automatic.runs_dir`), for tests."""

    closed = Signal()  # the window was closed

    def __init__(
        self,
        provider: Any = None,
        sessions: Sessions | None = None,
        runner: Runner | None = None,
        *,
        ai: AIConfig | None = None,
        always_confirm: bool = False,
        runs_folder: str | None = None,
    ) -> None:
        super().__init__(None)  # never parented to, or owned by, a SOLIDWORKS window
        self.always_confirm = always_confirm
        self.runs_folder = runs_folder
        self.setWindowTitle(TITLE)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.ai = ai if ai is not None else AIConfig(AISettingsStore(None))
        self.provider = provider if provider is not None else self.ai.provider()
        self.settings_dialog: Any = None
        self.sessions: Sessions = sessions or NoSessions()
        self.runner = runner or Runner(self._forward)
        if self.runner.forward is None:
            self.runner.forward = self._forward
        self.sig = _Signals()
        self._session_list = SessionList()
        self._snapshot: Any = None
        self._snapshot_of: LiveDocument | None = None
        self._cancel: Cancel | None = None
        self._drafting = False
        self._writer = None
        self._script_target: tuple[LiveSession, LiveDocument] | None = None
        self._calls: dict[int, float] = {}  # SOLIDWORKS calls in flight, by id, and when each began
        self._calls_lock = threading.Lock()
        self._next_call = 0
        self._busy = False
        self._ai_hidden = False
        self._plan: Plan | None = None
        self._plan_target: tuple[LiveSession, LiveDocument] | None = None
        self._plan_goal: Any = None  # the goal as the plan's call sent it, for the looks after steps
        self._run: AutomaticRun | None = None
        self._starting = False
        self._offers: list[UnfinishedRun] = []  # runs left open, the first one shown
        self._offer_busy = False
        self._closed = False
        self._build()
        self._wire()
        self._apply_provider()
        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(250)
        self._busy_timer.timeout.connect(self._check_busy)
        self._busy_timer.start()
        self.refresh()
        self._thread(self._look_for_unfinished)

    # ----------------------------------------------------------------- building
    def _build(self) -> None:
        top = QHBoxLayout()
        self.session_box = QComboBox()
        self.session_box.setMinimumContentsLength(18)
        self.document_box = QComboBox()
        self.document_box.setMinimumContentsLength(24)
        self.refresh_button = QPushButton("Refresh")
        self.settings_button = QPushButton("AI Settings...")
        self.settings_button.setToolTip(
            _tip("Choose the AI provider and model, store its API key and set the monthly budget")
        )
        top.addWidget(_plain_label("SOLIDWORKS:"))
        top.addWidget(self.session_box, 1)
        top.addWidget(_plain_label("Document:"))
        top.addWidget(self.document_box, 2)
        top.addWidget(self.refresh_button)
        top.addWidget(self.settings_button)
        self.status = _plain_label()
        self.mode_label = _plain_label(REVIEW_TEXT)
        self.unavailable = QWidget()
        un = QHBoxLayout(self.unavailable)
        un.setContentsMargins(0, 0, 0, 0)
        self.unavailable_text = _plain_label()
        self.setup_button = QPushButton("Open AI Settings...")
        un.addWidget(self.unavailable_text, 1)
        un.addWidget(self.setup_button, 0, Qt.AlignmentFlag.AlignTop)

        self.ai_box = QGroupBox("Ask for a change")
        ai = QVBoxLayout(self.ai_box)
        self.request = QPlainTextEdit()
        self.request.setPlaceholderText("Describe the change, for example: fillet the four top edges 2 mm")
        self.request.setMaximumBlockCount(400)
        self.names = QCheckBox(NAMES_TEXT)
        self.picture = QCheckBox(picture.PICTURE_TEXT)  # off until ticked
        self.picture.setToolTip(_tip(picture.PICTURE_TIP))
        self.step_pictures = QCheckBox(picture.STEP_TEXT)  # Automatic mode only, off until ticked
        self.step_pictures.setToolTip(_tip(picture.STEP_TIP))
        self.step_pictures.setVisible(False)
        self.automatic = QCheckBox("Automatic")
        self.automatic.setToolTip(
            _tip("Plan the goal once and carry it out on the part, each step checked and revertible")
        )
        self.draft_button = QPushButton("Draft")
        self.draft_stop = QPushButton("Stop")
        self.draft_stop.setEnabled(False)
        self.ai_note = _plain_label()
        row = QHBoxLayout()
        row.addWidget(self.names)
        row.addWidget(self.picture)
        row.addWidget(self.step_pictures)
        row.addWidget(self.automatic)
        row.addStretch(1)
        row.addWidget(self.draft_button)
        row.addWidget(self.draft_stop)
        ai.addWidget(self.request)
        ai.addLayout(row)
        ai.addWidget(self.ai_note)
        self.sees_box = QGroupBox("What the AI sees")
        sees = QVBoxLayout(self.sees_box)
        self.sees = QPlainTextEdit()
        self.sees.setReadOnly(True)
        self.sees.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        sees.addWidget(self.sees)

        self.console_box = console_box = QGroupBox("Console")
        console = QVBoxLayout(console_box)
        lang_row = QHBoxLayout()
        self.language = QComboBox()
        self.language.addItems(["python", "cadquery"])
        lang_row.addWidget(_plain_label("Language:"))
        lang_row.addWidget(self.language)
        lang_row.addStretch(1)
        self.code = QPlainTextEdit()
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.code.setFont(mono)
        self.code.setPlaceholderText("Code to run: drafted by the model, or typed here")
        self.explanation = QPlainTextEdit()
        self.explanation.setReadOnly(True)
        self.explanation.setMaximumHeight(110)
        self.explanation.setPlaceholderText("The model's explanation of its draft")
        run_row = QHBoxLayout()
        self.warning = _plain_label(WARNING)
        self.run_button = QPushButton("Run")
        self.run_stop = QPushButton("Stop")
        self.run_stop.setEnabled(False)
        run_row.addWidget(self.warning, 1)
        run_row.addWidget(self.run_button)
        run_row.addWidget(self.run_stop)
        console.addLayout(lang_row)
        console.addWidget(self.code, 3)
        console.addWidget(self.explanation, 1)
        console.addLayout(run_row)

        self.plan_box = QGroupBox("Plan")
        pb = QVBoxLayout(self.plan_box)
        self.plan_view = QPlainTextEdit()
        self.plan_view.setReadOnly(True)
        self.plan_view.setPlaceholderText(
            "The plan the model makes for your goal, step by step, before anything runs"
        )
        self.plan_note = _plain_label()
        self.plan_run = QPushButton("Run plan")
        self.plan_stop = QPushButton("Stop")
        self.plan_keep = QPushButton("Keep")
        self.plan_revert = QPushButton("Revert")
        for b in (self.plan_run, self.plan_stop, self.plan_keep, self.plan_revert):
            b.setEnabled(False)
        plan_row = QHBoxLayout()
        plan_row.addWidget(self.plan_note, 1)
        for b in (self.plan_run, self.plan_stop, self.plan_keep, self.plan_revert):
            plan_row.addWidget(b)
        pb.addWidget(self.plan_view, 1)
        pb.addLayout(plan_row)
        self.plan_box.hide()

        self.offer_box = QGroupBox("A run that did not finish")
        ob = QVBoxLayout(self.offer_box)
        self.offer_count = _plain_label()
        self.offer_text = QPlainTextEdit()
        self.offer_text.setReadOnly(True)
        self.offer_text.setMaximumHeight(220)
        self.offer_note = _plain_label()
        self.offer_revert = QPushButton("Revert")
        self.offer_revert.setToolTip(
            _tip("Take the run's steps off the part, newest first, if it is still as the run left it")
        )
        self.offer_keep = QPushButton("Keep")
        self.offer_keep.setToolTip(_tip("Leave the part as it is and close the run"))
        self.offer_later = QPushButton("Decide Later")
        self.offer_later.setToolTip(_tip("Ask again the next time the assistant opens"))
        offer_row = QHBoxLayout()
        offer_row.addWidget(self.offer_note, 1)
        for b in (self.offer_revert, self.offer_keep, self.offer_later):
            offer_row.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
        ob.addWidget(self.offer_count)
        ob.addWidget(self.offer_text)
        ob.addLayout(offer_row)
        self.offer_box.hide()

        log_box = QGroupBox("Log")
        log = QVBoxLayout(log_box)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        log.addWidget(self.log)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self.ai_box)
        lv.addWidget(console_box, 1)
        lv.addWidget(self.plan_box, 1)
        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(self.sees_box)
        right.addWidget(log_box)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.status)
        layout.addWidget(self.mode_label)
        layout.addWidget(self.unavailable)
        layout.addWidget(self.offer_box)
        layout.addWidget(split, 1)
        self.resize(1100, 720)

    def _wire(self) -> None:
        s = self.sig
        s.listed.connect(self._listed)
        s.snapshot.connect(self._snapshot_ready)
        s.drafted.connect(self._drafted)
        s.output.connect(self._output)
        s.begun.connect(self._begun)
        s.finished.connect(self._finished)
        s.ended.connect(lambda: self._set_running(False))
        s.log.connect(self.say)
        self.refresh_button.clicked.connect(self.refresh)
        self.settings_button.clicked.connect(self.open_ai_settings)
        self.setup_button.clicked.connect(self.open_ai_settings)
        self.session_box.currentIndexChanged.connect(self._session_changed)
        self.document_box.currentIndexChanged.connect(self._document_changed)
        self.draft_button.clicked.connect(self.draft)
        self.draft_stop.clicked.connect(self.stop_draft)
        self.run_button.clicked.connect(self.run)
        self.run_stop.clicked.connect(self.stop_run)
        self.request.textChanged.connect(self._preview)
        self.names.toggled.connect(self._preview)
        self.picture.toggled.connect(self._sync_step_pictures)
        self.picture.toggled.connect(self._preview)
        self.step_pictures.toggled.connect(self._preview)
        self.automatic.toggled.connect(self._mode_changed)
        s.planned.connect(self._planned)
        s.run_started.connect(self._run_started)
        s.run_event.connect(self._run_event)
        s.run_ended.connect(self._run_ended)
        s.reverted.connect(self._reverted)
        self.plan_run.clicked.connect(self.run_plan)
        self.plan_stop.clicked.connect(self.stop_plan)
        self.plan_keep.clicked.connect(self.keep_run)
        self.plan_revert.clicked.connect(self.revert_run)
        s.unfinished.connect(self._unfinished_found)
        s.offer_reverted.connect(self._offer_reverted)
        self.offer_revert.clicked.connect(self.revert_unfinished)
        self.offer_keep.clicked.connect(self.keep_unfinished)
        self.offer_later.clicked.connect(self.decide_later)

    def _apply_provider(self) -> None:
        """Hide, disable or show the AI controls from what the factory served."""
        reason = (
            getattr(self.provider, "reason", None) if getattr(self.provider, "name", "") == "noop" else None
        )
        hidden = self.provider is None or reason == "not_configured"
        self._ai_hidden = hidden
        self.ai_box.setVisible(not hidden)
        self.sees_box.setVisible(not hidden)
        usable = not hidden and reason is None
        for w in (self.request, self.names, self.draft_button):
            w.setEnabled(usable)
        self._apply_picture_policy(usable)
        self._apply_policy(usable)
        why = unavailable_text(self.provider)
        self.unavailable_text.setText(why or "")
        self.unavailable.setVisible(why is not None)
        if reason == "policy_refused":
            self.ai_note.setText(f"{ADMIN}.")
            for w in (self.request, self.names, self.draft_button):
                w.setToolTip(_tip(ADMIN))
        else:
            self.ai_note.setText("")
            for w in (self.request, self.names, self.draft_button):
                w.setToolTip("")

    def _apply_picture_policy(self, usable: bool = True) -> None:
        """The picture's tick box as the machine policy, read now, allows it: off and
        greyed out, saying why, under ``DisableImages``."""
        allowed = picture.allowed()
        if not allowed:
            self.picture.setChecked(False)
        self.picture.setEnabled(usable and allowed)
        self.picture.setToolTip(_tip(picture.PICTURE_TIP if allowed else picture.ADMIN_OFF))
        self._sync_step_pictures()

    def _sync_step_pictures(self, *_: Any) -> None:
        """The box for a look after each step: shown in Automatic mode, usable only while
        "Show the AI a picture of the part" is ticked (the person's word that pictures may
        go), and unticked with it."""
        allowed = picture.allowed()
        on = self.picture.isChecked() and self.picture.isEnabled() and allowed
        if not on:
            self.step_pictures.setChecked(False)
        self.step_pictures.setVisible(self.automatic.isChecked())
        self.step_pictures.setEnabled(on)
        tip = picture.STEP_TIP if on else (picture.ADMIN_OFF if not allowed else picture.STEP_NEEDS_PICTURE)
        self.step_pictures.setToolTip(_tip(tip))

    def _step_looks_wanted(self) -> bool:
        """Whether the next run looks at the part after each step: asked for, and allowed."""
        return (
            self.automatic.isChecked()
            and self.step_pictures.isChecked()
            and self.picture.isChecked()
            and picture.allowed()
        )

    def _picture_path(self) -> str | None:
        """The part file a picture would show, when the person asked for one and may."""
        if not self.picture.isChecked() or not picture.allowed() or self._snapshot is None:
            return None
        return self._snapshot.path or None

    def _picture(self, path: str | None):
        """The picture for this call (on the worker thread), or None; a picture that cannot
        be made is said in the panel and the request goes without it."""
        if path is None:
            return None
        try:
            return picture.saved_picture(path)
        except Exception as exc:  # the part's file could not be read or drawn
            self.sig.log.emit(f"No picture was sent: {exc}")
            return None

    def _apply_policy(self, usable: bool = True) -> None:
        """Automatic mode as the machine policy, read now, allows it."""
        refused = policy.current().automatic_disabled
        if refused and self.automatic.isChecked():
            self.automatic.setChecked(False)
        self.automatic.setEnabled(usable and not refused)
        self.automatic.setToolTip(
            _tip(ADMIN)
            if refused
            else _tip("Plan the goal once and carry it out on the part, each step checked and revertible")
        )

    def reload_provider(self) -> None:
        """Build the provider again from the saved AI settings (after they changed)."""
        self.provider = self.ai.provider()
        self._apply_provider()
        self._preview()

    def open_ai_settings(self):
        """Open the AI settings page, or bring the open one forward. Returns it."""
        from .settings_dialog import AISettingsDialog

        dialog = self.settings_dialog
        if dialog is not None:
            dialog.raise_()
            dialog.activateWindow()
            return dialog
        dialog = AISettingsDialog(self, self.ai)
        dialog.changed.connect(self.reload_provider)
        dialog.finished.connect(lambda _result, d=dialog: self._settings_closed(d))
        self.settings_dialog = dialog
        dialog.open()
        return dialog

    def _settings_closed(self, dialog) -> None:
        if self.settings_dialog is dialog:
            self.settings_dialog = None
        dialog.deleteLater()

    # ----------------------------------------------------------------- helpers
    @property
    def ai_usable(self) -> bool:
        return self.draft_button.isEnabled() and self.ai_box.isVisible()

    def say(self, text: str) -> None:
        """A line in the log, as plain text."""
        self.log.appendPlainText(text)

    def _target(self) -> tuple[LiveSession | None, LiveDocument | None]:
        si = self.session_box.currentIndex()
        sessions = self._session_list.sessions
        session = sessions[si] if 0 <= si < len(sessions) else None
        di = self.document_box.currentIndex()
        docs = session.documents if session is not None else ()
        document = docs[di] if 0 <= di < len(docs) else None
        return session, document

    def _sw_call(self, fn, *args):
        """Call into a SOLIDWORKS session from a worker thread, counted for the busy rule."""
        with self._calls_lock:
            self._next_call += 1
            cid = self._next_call
            self._calls[cid] = time.monotonic()
        try:
            return fn(*args)
        finally:
            with self._calls_lock:
                self._calls.pop(cid, None)

    def _check_busy(self) -> None:
        with self._calls_lock:
            oldest = min(self._calls.values(), default=None)
        busy = oldest is not None and time.monotonic() - oldest > BUSY_SECONDS
        if busy == self._busy:
            return
        self._busy = busy
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, not busy)
        if visible:
            self.show()  # changing a window flag hides the window
        if busy:
            self.status.setText("SOLIDWORKS is busy or showing a dialog; this window no longer stays on top.")
        else:
            self._show_status()

    @property
    def stays_on_top(self) -> bool:
        return bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

    def _thread(self, target, *args) -> threading.Thread:
        t = threading.Thread(target=target, args=args, daemon=True, name="assistant-worker")
        t.start()
        return t

    # ----------------------------------------------------------------- sessions
    def refresh(self) -> None:
        """List the SOLIDWORKS sessions again (on a worker thread)."""
        self.status.setText("Looking for SOLIDWORKS...")

        def work() -> None:
            try:
                found = self._sw_call(self.sessions.list)
            except Exception as exc:
                found = SessionList((), f"SOLIDWORKS could not be listed: {exc}")
            self.sig.listed.emit(found)

        self._thread(work)

    def _listed(self, found: SessionList) -> None:
        self._session_list = found
        self.session_box.blockSignals(True)
        self.session_box.clear()
        for s in found.sessions:
            text = f"SOLIDWORKS {s.version} (process {s.pid})"
            self.session_box.addItem(text + (f": {s.note}" if s.note else ""))
        self.session_box.blockSignals(False)
        self._session_changed()
        self._show_status()

    def _show_status(self) -> None:
        if not self._session_list.sessions:
            self.status.setText(self._session_list.why_none or "No SOLIDWORKS session was found.")
            return
        session, document = self._target()
        if document is None:
            self.status.setText("Pick a document.")
        elif document.kind != "part":
            self.status.setText(f"{document.title} is not a part: the model drafts without a summary of it.")
        else:
            self.status.setText(f"Working on {document.title}.")

    def _session_changed(self, *_: Any) -> None:
        session, _doc = self._target()
        self.document_box.blockSignals(True)
        self.document_box.clear()
        for d in session.documents if session is not None else ():
            self.document_box.addItem(d.title)
            self.document_box.setItemData(
                self.document_box.count() - 1, _tip(d.path), Qt.ItemDataRole.ToolTipRole
            )
        self.document_box.blockSignals(False)
        self._document_changed()

    def _document_changed(self, *_: Any) -> None:
        session, document = self._target()
        self._snapshot, self._snapshot_of = None, None
        self._show_status()
        self._preview()
        if session is None or document is None or document.kind != "part" or session.note:
            return

        def work() -> None:
            try:
                snap = self._sw_call(self.sessions.snapshot, session, document)
            except Exception as exc:
                snap = f"The part could not be read: {exc}"
            self.sig.snapshot.emit(document, snap)

        self._thread(work)

    def _snapshot_ready(self, document: LiveDocument, snap: Any) -> None:
        _session, current = self._target()
        if current != document:
            return  # the person has moved on
        if isinstance(snap, str):
            self.say(snap)
            return
        self._snapshot, self._snapshot_of = snap, document
        self._preview()

    # ----------------------------------------------------------------- drafting
    def _prepared(self):
        """The request and the summary as the next call sends them; raises AIError."""
        request = prepare_request(self.request.toPlainText())
        summary = None
        if self._snapshot is not None:
            summary = build_model_summary(self._snapshot, send_names=self.names.isChecked())
        return request, summary

    def _preview(self, *_: Any) -> None:
        """What the AI sees: the exact prompt of the next call, or why there is none."""
        if self._ai_hidden:
            return
        if not self.request.toPlainText().strip():
            self.sees.setPlainText("Nothing yet: type a request.")
            return
        try:
            request, summary = self._prepared()
        except AIError as exc:
            self.sees.setPlainText(f"Nothing would be sent: {exc}")
            return
        if self.automatic.isChecked():
            if summary is None:
                self.sees.setPlainText(f"Nothing would be sent: {NO_PART_TO_PLAN}")
            else:
                self.sees.setPlainText(
                    plan_prompt(request, summary).text() + self._picture_line() + self._step_look_line()
                )
            return
        prompt = draft_prompt(request, summary)
        note = "" if summary is not None else NO_PART + "\n\n"
        self.sees.setPlainText(note + prompt.text() + self._picture_line())

    def _picture_line(self) -> str:
        """The picture's line in what the AI sees, when one goes with the call."""
        if self._picture_path() is None:
            return ""
        return f"\n\n[image] {picture.CAPTION} (made from the part's file when sent)"

    def _step_look_line(self) -> str:
        """What goes after each step of the run, when the person asked for a look."""
        if not self._step_looks_wanted():
            return ""
        return (
            "\n\n[after each step that passes SolidSeas' checks, one more request]\n"
            "Your goal as above, that step as the Plan panel shows it, and\n"
            f"[image] {picture.step_caption('N')}\n"
            "The model only answers whether the part looks as the step should leave it."
        )

    def draft(self) -> None:
        """Ask the provider for a draft (on a worker thread); with Automatic ticked, a plan."""
        if self.automatic.isChecked():
            self.plan()
            return
        if self._drafting or not self.ai_usable:
            return
        try:
            request, summary = self._prepared()
        except AIError as exc:
            self.say(f"Nothing was sent: {exc}")
            return
        self._preview()
        if request.redactions:
            self.say(f"{request.redactions} numbers that looked private were removed from the request.")
        cancel = Cancel()
        self._cancel = cancel
        self._drafting = True
        self.draft_button.setEnabled(False)
        self.draft_stop.setEnabled(True)
        self.say("Asking the model for a draft...")
        provider = self.provider
        shown = self._picture_path()

        def work() -> None:
            try:
                image = self._picture(shown)
                result = provider.draft_change(summary, request, call=CallOptions(cancel=cancel), image=image)
                self.sig.drafted.emit(result, None)
            except AIError as exc:
                self.sig.drafted.emit(None, str(exc))
            except Exception as exc:  # a provider bug: said, never raised into Qt
                self.sig.drafted.emit(None, f"The draft failed: {type(exc).__name__}: {exc}")

        self._thread(work)

    def stop_draft(self) -> None:
        if self._cancel is not None:
            self._cancel.cancel()

    def _drafted(self, result: Any, error: str | None) -> None:
        self._drafting = False
        self._cancel = None
        self.draft_stop.setEnabled(False)
        self._apply_provider()
        if error is not None:
            self.say(error)
            return
        if result is None:
            self.say("This provider does not draft code.")
            return
        draft = result.value
        self.language.setCurrentText(draft.language)
        self.code.setPlainText(draft.code)
        self.explanation.setPlainText(draft.explanation)
        self.say(
            f"Draft ready ({result.input_tokens:,} tokens in, {result.output_tokens:,} out). "
            "Read it, change it if you like, and press Run to run it."
        )

    # ----------------------------------------------------------------- Automatic mode
    def _mode_changed(self, on: bool) -> None:
        self.draft_button.setText("Plan" if on else "Draft")
        self.console_box.setVisible(not on)
        self.plan_box.setVisible(on)
        self.mode_label.setText(AUTOMATIC_TEXT if on else REVIEW_TEXT)
        self._sync_step_pictures()
        self._preview()

    @property
    def run_active(self) -> bool:
        return self._starting or (self._run is not None and self._run.outcome is None)

    def plan(self) -> None:
        """Ask the provider for a plan of the goal (on a worker thread)."""
        if self._drafting or not self.ai_usable or self.run_active:
            return
        if policy.current().automatic_disabled:
            self.say(f"{ADMIN}: Automatic mode is turned off on this PC.")
            self._apply_policy()
            return
        session, document = self._target()
        if self._snapshot is None or session is None or document is None or self._snapshot_of != document:
            self.say(NO_PART_TO_PLAN)
            return
        try:
            request, summary = self._prepared()
        except AIError as exc:
            self.say(f"Nothing was sent: {exc}")
            return
        self._preview()
        cancel = Cancel()
        self._cancel = cancel
        self._drafting = True
        self.draft_button.setEnabled(False)
        self.draft_stop.setEnabled(True)
        self._plan, self._plan_target = None, (session, document)
        self._plan_goal = request
        self.plan_run.setEnabled(False)
        self.plan_view.setPlainText("")
        self.plan_note.setText("")
        self.say("Asking the model for a plan...")
        provider = self.provider
        shown = self._picture_path()

        def work() -> None:
            try:
                image = self._picture(shown)
                result = provider.plan_steps(request, summary, call=CallOptions(cancel=cancel), image=image)
                self.sig.planned.emit(result, summary, None)
            except AIError as exc:
                self.sig.planned.emit(None, summary, str(exc))
            except Exception as exc:  # a provider bug: said, never raised into Qt
                self.sig.planned.emit(None, summary, f"The plan failed: {type(exc).__name__}: {exc}")

        self._thread(work)

    def _planned(self, result: Any, summary: Any, error: str | None) -> None:
        self._drafting = False
        self._cancel = None
        self.draft_stop.setEnabled(False)
        self._apply_provider()
        if error is not None:
            self.say(error)
            return
        if result is None:
            self.say("This provider does not plan.")
            return
        plan = result.value
        self._plan = plan
        self.plan_view.setPlainText(plan_text(plan))
        gate = confirmation(plan, always_confirm=self._always_confirm())
        line = f"Plan ready: {len(plan.steps)} step{'s' if len(plan.steps) != 1 else ''}"
        line += f" ({result.input_tokens:,} tokens in, {result.output_tokens:,} out)."
        if gate.waits:
            self.plan_note.setText("It waits for Run plan. " + " ".join(gate.reasons))
            self.plan_run.setEnabled(True)
            self.say(line + " It waits for you to press Run plan.")
            return
        self.say(line + " It starts by itself.")
        self._start(confirmed=False)

    def _always_confirm(self) -> bool:
        """Whether every plan waits for Run plan: this window's own word, or the saved AI
        setting "Always confirm the plan before a run"."""
        if self.always_confirm:
            return True
        try:
            return self.ai.settings.load().always_confirm is True
        except Exception:  # unreadable settings: the default, off
            return False

    def _run_tokens(self) -> int:
        """The saved AI setting for a run's token budget, which the looks after steps share."""
        try:
            tokens = self.ai.settings.load().run_tokens
        except Exception:  # unreadable settings: the default
            return DEFAULT_RUN_TOKENS
        return tokens if type(tokens) is int and 0 <= tokens <= 1_000_000 else DEFAULT_RUN_TOKENS

    def run_plan(self) -> None:
        """Run plan: the person's confirmation of a plan that waits."""
        self._start(confirmed=True)

    def _start(self, *, confirmed: bool) -> None:
        plan, target = self._plan, self._plan_target
        if plan is None or target is None or self.run_active:
            return
        if self._target() != target:
            self.say("The picked part is not the one the plan was made for; plan again.")
            return
        if not hasattr(self.sessions, "operation"):
            self.say("Automatic mode needs SolidSeas' bridge to reach SOLIDWORKS, and there is none here.")
            return
        session, document = target
        self._starting = True
        self.plan_run.setEnabled(False)
        self.plan_stop.setEnabled(True)
        self.plan_keep.setEnabled(False)
        self.plan_revert.setEnabled(False)
        self.draft_button.setEnabled(False)
        self.say(f"Starting the run on {document.title}: checking the part and writing the safety copy...")
        always = self._always_confirm()
        provider, goal = self.provider, self._plan_goal
        looks = self._step_looks_wanted() and goal is not None
        if looks:
            self.say("After each step, the model is shown the part and asked whether it looks right.")
        tokens = self._run_tokens()

        def work() -> None:
            check = SessionTarget(self.sessions, session, document)
            try:
                start = self._sw_call(
                    lambda: start_run(
                        check, plan, confirmed=confirmed, always_confirm=always, runs_folder=self.runs_folder
                    )
                )
            except RunRefused as exc:
                self.sig.run_ended.emit(f"The run did not start: {exc}")
                return
            except Exception as exc:
                self.sig.run_ended.emit(f"The run did not start: {type(exc).__name__}: {exc}")
                return
            look = None
            if looks:
                pictures = picture.CopyPictures(self.sessions, session, document, start.folder, start.run_id)
                look = picture.ModelLook(provider, pictures, goal, len(plan.steps), budget=RunBudget(tokens))
            try:
                run = AutomaticRun(
                    self.sessions,
                    session,
                    document,
                    start,
                    baseline=check.snapshot,
                    on_event=lambda kind, data: self.sig.run_event.emit(kind, data),
                    look=look,
                    goal=goal.text if goal is not None else None,
                )
            except Exception as exc:
                start.release()
                self.sig.run_ended.emit(f"The run did not start: {type(exc).__name__}: {exc}")
                return
            self.sig.run_started.emit(run)
            self.sig.run_ended.emit(self._sw_call(run.run))

        self._thread(work)

    def _run_started(self, run: AutomaticRun) -> None:
        self._run = run
        self._starting = False
        self.say(f"Safety copy: {run.start.checkpoint}")

    def _run_event(self, kind: str, data: Any) -> None:
        if kind == "step_started":
            self.say(f"Step {data['index']} of {data['count']}: {data['op']}...")
        elif kind == "step_done":
            self.say(f"Step {data['index']} done and checked.")
        elif kind == "step_failed":
            self.say(f"Step {data['index']} was taken back: " + "; ".join(data.get("problems", ())))
        elif kind == "step_looked":
            verdict = {True: "it looks right", False: "it does not look right", None: "it cannot tell"}
            words = verdict.get(data.get("as_expected"), "it cannot tell")
            says = data.get("says", "")
            self.say(f"Step {data['index']}: the model looked at the part and says {words}: {says}")
        elif kind == "look_failed":
            why = data.get("message", "")
            self.say(f"Step {data['index']}: no look at the part ({why}). The run goes on.")
        elif kind == "step_reverted":
            self.say(f"Step {data['index']} reverted.")

    def _run_ended(self, outcome: Any) -> None:
        self._starting = False
        self.plan_stop.setEnabled(False)
        self._apply_provider()
        if not isinstance(outcome, RunOutcome):
            self.say(str(outcome))
            self.plan_run.setEnabled(self._plan is not None)
            return
        self.say(outcome.message)
        run = self._run
        if run is None:
            return
        if outcome.steps_done:
            self.plan_note.setText(
                f"{outcome.steps_done} step(s) changed the part. Keep them, or Revert to take them off, "
                f"newest first. The safety copy is {run.start.checkpoint}."
            )
            self.plan_keep.setEnabled(True)
            self.plan_revert.setEnabled(True)
        else:
            run.keep()  # nothing to take off: the session is given back
            self.plan_note.setText("The part is as it was before the run.")

    def stop_plan(self) -> None:
        run = self._run
        if run is not None and run.outcome is None:
            run.stop()
            self.say("Stopping after the current step.")

    def keep_run(self) -> None:
        run = self._run
        if run is None or run.ended:
            return
        run.keep()
        self.plan_keep.setEnabled(False)
        self.plan_revert.setEnabled(False)
        self.plan_note.setText(f"Kept. The run's folder stays for {KEEP_DAYS} days: {run.start.folder}")
        self.say("Kept: the part stays as the run left it. Save it in SOLIDWORKS when you are ready.")

    def revert_run(self) -> None:
        run = self._run
        if run is None or run.ended:
            return
        self.plan_keep.setEnabled(False)
        self.plan_revert.setEnabled(False)
        self.say("Reverting, newest step first...")

        def work() -> None:
            self.sig.reverted.emit(self._sw_call(run.revert))

        self._thread(work)

    def _reverted(self, messages: Any) -> None:
        for m in messages:
            self.say(m)
        if not messages:
            self.say("Reverted: the part is as it was before the run.")
            self.plan_note.setText("Reverted.")
        else:
            self.plan_note.setText("Revert did not finish; see the log.")

    # ----------------------------------------------------------------- runs left open
    def _look_for_unfinished(self) -> None:
        """On a worker thread when the window opens: remove the folders of runs that ended a
        week ago, then find the runs whose process ended before Keep or Revert."""
        try:
            clean_old_runs(self.runs_folder)
        except Exception:  # the next start tries again
            pass
        try:
            found = find_unfinished(self.runs_folder)
        except Exception as exc:
            found = []
            self.sig.log.emit(f"Runs that did not finish could not be looked for: {exc}")
        self.sig.unfinished.emit(found)

    def _unfinished_found(self, found: list[UnfinishedRun]) -> None:
        if self._closed:  # the window closed meanwhile: the runs are offered next time
            for offer in found:
                offer.release()
            return
        self._offers.extend(found)
        if found:
            n = len(found)
            self.say(
                f"{n} Automatic run{'s' if n != 1 else ''} did not finish: SolidSeas closed before Keep or "
                "Revert. Choose what to do above."
            )
        self._show_offer()

    @property
    def offer(self) -> UnfinishedRun | None:
        """The run left open that the window offers now."""
        return self._offers[0] if self._offers else None

    def _show_offer(self, note: str = "") -> None:
        offer = self.offer
        self.offer_box.setVisible(offer is not None)
        if offer is None:
            return
        n = len(self._offers)
        self.offer_count.setText(
            f"{n} runs did not finish; this is the oldest." if n > 1 else "One run did not finish."
        )
        self.offer_text.setPlainText(offer.describe())
        self.offer_note.setText(note)
        for b in (self.offer_revert, self.offer_keep, self.offer_later):
            b.setEnabled(not self._offer_busy)

    def _next_offer(self) -> None:
        if self._offers:
            self._offers.pop(0)
        self._show_offer()

    def revert_unfinished(self) -> None:
        """Revert for the run on offer, on a worker thread: its steps come off the part,
        newest first, only if the part is still as the run left it."""
        offer = self.offer
        if offer is None or self._offer_busy:
            return
        self._offer_busy = True
        for b in (self.offer_revert, self.offer_keep, self.offer_later):
            b.setEnabled(False)
        self.offer_note.setText("Checking the part...")
        self.say(f"Reverting the run that did not finish on {offer.title}, newest step first...")

        def work() -> None:
            try:
                result: Any = self._sw_call(offer.revert, self.sessions)
            except Exception as exc:  # said, never raised into Qt; the run stays open
                result = f"Revert failed: {type(exc).__name__}: {exc}"
            self.sig.offer_reverted.emit(offer, result)

        self._thread(work)

    def _offer_reverted(self, offer: UnfinishedRun, result: Any) -> None:
        self._offer_busy = False
        refused = result if isinstance(result, str) else result.refused
        if self._closed:
            if refused is not None:
                offer.release()
            return
        if refused is not None:
            self.say(refused)
            if offer is self.offer:
                self._show_offer(refused)
            return
        for m in result.messages:
            self.say(m)
        if result.messages:
            self.say("Revert did not finish; the run is closed. The messages above say where it stopped.")
        else:
            self.say(
                f"Reverted: {offer.title} is as it was before the run. "
                "Save it in SOLIDWORKS when you are ready."
            )
        if offer is self.offer:
            self._next_offer()

    def keep_unfinished(self) -> None:
        """Keep for the run on offer: the part stays as it is, and the run is closed."""
        offer = self.offer
        if offer is None or self._offer_busy:
            return
        try:
            offer.keep()
        except OSError as exc:
            self.say(f"The run could not be closed: {exc}")
            self._next_offer()
            return
        self.say(
            f"Kept: {offer.title} stays as it is. The run's folder stays for {KEEP_DAYS} days: {offer.folder}"
        )
        self._next_offer()

    def decide_later(self) -> None:
        """Decide Later for the run on offer: nothing is done, and it is offered again next time."""
        offer = self.offer
        if offer is None or self._offer_busy:
            return
        offer.release()
        self.say(
            f"Nothing was done to the run on {offer.title}. It is offered again the next time the assistant "
            "opens, until its folder is removed."
        )
        self._next_offer()

    # ----------------------------------------------------------------- running
    def run(self) -> None:
        """Run the console's code: the person's approval."""
        code = self.code.toPlainText()
        if not code.strip() or self.runner.running or self._writer is not None:
            return
        session, document = self._target()
        if session is not None and document is not None and not session.note:
            try:
                self._writer = take_writer(session.pid)
            except WriterBusyError as exc:
                self.say(str(exc))
                return
            self._script_target = (session, document)
            self._set_running(True)
            self.say(f"Writing a safety copy of {document.title} and opening the undo entry...")

            def work() -> None:
                try:
                    path = self._sw_call(self.sessions.begin_script, session, document)
                    self.sig.begun.emit(path, None)
                except Exception as exc:
                    self.sig.begun.emit(None, str(exc))

            self._thread(work)
            return
        self._script_target = None
        self._set_running(True)
        self.say("Running the script (no SOLIDWORKS document is picked)...")
        self._start_runner(code)

    def _begun(self, path: Any, error: str | None) -> None:
        if error is not None:
            self.say(f"The script was not run: {error}")
            self._release()
            self._set_running(False)
            return
        if path:
            self.say(f"Safety copy: {path}")
        self.say("Running the script...")
        self._start_runner(self.code.toPlainText())

    def _start_runner(self, code: str) -> None:
        try:
            self.runner.run(
                code,
                language=self.language.currentText(),
                on_output=lambda kind, text: self.sig.output.emit(kind, text),
                on_done=lambda result: self.sig.finished.emit(result),
            )
        except (RuntimeError, ValueError) as exc:
            self.say(f"The script was not run: {exc}")
            self._end_script()

    def _forward(self, op: str, args: dict) -> Any:
        """A script's request, from the runner's thread, to the picked document."""
        target = self._script_target
        if target is None:
            raise RuntimeError("no SOLIDWORKS document is picked")
        return self._sw_call(self.sessions.call, target[0], target[1], op, args)

    def stop_run(self) -> None:
        if self.runner.running:
            self.runner.stop()

    def _output(self, kind: str, text: str) -> None:
        for line in text.rstrip("\n").split("\n"):
            self.log.appendPlainText(line if kind == "out" else f"! {line}")

    def _finished(self, result: RunResult) -> None:
        words = {
            "done": "The script finished",
            "error": "The script failed",
            "memory": "The script ran out of memory",
            "timeout": "The script took too long and was ended",
            "stopped": "The script was stopped",
            "crashed": "The script's process ended unexpectedly",
            "failed": "The script could not be started",
        }
        line = f"{words.get(result.status, result.status)} after {result.seconds:.1f} s"
        if result.calls:
            line += f", with {result.calls} SOLIDWORKS requests"
        self.say(line + ".")
        if result.message and result.status not in ("done",):
            self.say(result.message)
        if result.output_dropped:
            self.say(f"{result.output_dropped:,} more characters of output were left out.")
        self._end_script()

    def _end_script(self) -> None:
        target = self._script_target
        self._script_target = None
        if target is None:
            self._release()
            self._set_running(False)
            return

        def work() -> None:
            try:
                self._sw_call(self.sessions.end_script, *target)
                self.sig.log.emit(
                    "The undo entry is closed: one Ctrl+Z in SOLIDWORKS takes the script's changes off."
                )
            except Exception as exc:
                self.sig.log.emit(f"The undo entry could not be closed: {exc}")
            finally:
                self._release()
                self.sig.ended.emit()

        self._thread(work)

    def _release(self) -> None:
        writer, self._writer = self._writer, None
        if writer is not None:
            writer.release()

    def _set_running(self, on: bool) -> None:
        self.run_button.setEnabled(not on)
        self.run_stop.setEnabled(on)
        self.code.setReadOnly(on)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self._closed = True
        for offer in self._offers:
            if not (self._offer_busy and offer is self.offer):  # a revert under way lets go when it ends
                offer.release()  # offered again next time
        self._offers = []
        self.stop_draft()
        if self.runner.running:
            self.runner.stop()
            self.runner.wait(5.0)
        self._release()
        run = self._run
        if run is not None:
            if run.outcome is None:
                run.stop()
            elif not run.ended:
                run.keep()  # closing without a choice keeps the part as it is
        close = getattr(self.sessions, "close", None)
        if callable(close):  # the bridge lets go of SOLIDWORKS off the Qt thread, ending nothing of it
            self._thread(close)
        if self.settings_dialog is not None:
            self.settings_dialog.reject()
        super().closeEvent(event)
        self.closed.emit()


def default_config() -> AIConfig:
    """The app's AI settings: ``AI.json`` beside the viewer's ``Viewer.ini``, keys in the
    default credential store, usage in the default usage file."""
    from solidseas_app.viewer.settings import default_path

    from .aisettings import path_beside

    return AIConfig(AISettingsStore(path_beside(default_path())))


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - opens the window
    """``python -m solidseas_app.assistant`` and ``SolidSeasViewer.exe --assistant``: the
    window on its own, with the provider the saved AI settings name and the SOLIDWORKS
    sessions the bridge reaches."""
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1] if argv is None else argv)
    app.setApplicationName("SolidSeas Modeling Assistant")
    try:
        from solidseas_app.viewer.app import window_icon

        app.setWindowIcon(window_icon())
    except Exception:  # the icon is a nicety; the window opens without it
        pass
    from .live_sessions import default_sessions

    window = AssistantWindow(sessions=default_sessions(), ai=default_config())
    window.show()
    return app.exec()


__all__ = [
    "ADMIN",
    "BUSY_SECONDS",
    "NAMES_TEXT",
    "NOT_SET_UP",
    "TITLE",
    "WARNING",
    "AssistantWindow",
    "default_config",
    "main",
    "plan_text",
    "unavailable_text",
]
