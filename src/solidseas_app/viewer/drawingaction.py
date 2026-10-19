"""File > New Drawing..., Make Drawing..., File > Open Drawing... and Settings > Drawing
Settings...: the window's side of drawings (``docs/DRAWINGS.md`` 15.1 and 15.2).

:class:`DrawingController` is owned by the window, as
:class:`.printaction.PrintController` is, and puts itself in place
(:meth:`DrawingController.install`), so the window's change is a few lines in one
place:

* **New Drawing...** (the File menu, Ctrl+D, and the Drawing button beside 3D Print on
  the toolbar) draws the part the details panel shows, in the configuration it shows,
  as 3D Print prints it (:meth:`.window.MainWindow.print_target`).
* **Make Drawing...** follows every 3D Print entry of a right-click menu: the list's
  rows, the rows of the Components, BOM and References tabs and of a drawing's sheets
  and models, the 3D view and its legend. The controller follows the print
  controller's ``add_action`` and ``add_unavailable`` rather than each menu, so each
  Make Drawing entry is built from the very resolve its 3D Print entry has, which
  gives the same :class:`.printaction.PrintTarget`: a component part is drawn from its
  assembly, and a menu that gains a 3D Print entry later gains its Make Drawing too.
  The entries are put in, each right after its 3D Print entry, when the menu opens
  (:meth:`DrawingController.fill`, on ``aboutToShow``): what a 3D Print entry would
  print is looked at only for a menu that is shown, and code that builds a menu and
  reads it without showing it (the print tests, the self-test's checks of its
  entries) sees the menu as the print controller made it.
* A part or an assembly of its own file is drawn; an assembly's drawing has its views,
  parts list and item balloons (``docs/drawings/assemblies.md``). A SOLIDWORKS drawing,
  a part or sub-assembly stored inside an assembly and a 3D file of another format
  have the entry off (:func:`refusal`), with the reason in a few words after it and in
  full in its tooltip: "Drawings are made of SOLIDWORKS parts and assemblies in this
  release." That look is taken with the window's one question (which of several
  files a reference means) answered as cancelled, so opening a menu never asks
  anything; the entry asks when it is chosen.
* **Open Drawing...** opens a ``.ssdrw`` in the drawing editor, and **Drawing
  Settings...** is the dialog of :mod:`.drawingsettings`. On first use (no company
  name, no people, no unit for parts that state none) New Drawing opens that dialog
  on the first page that lacks one, once a session, then the wizard.

Drawings are experimental (:mod:`.experimental`): New Drawing, Open Drawing and Drawing
Settings carry the tag, and the viewer's ``drawings`` setting, on unless switched off on the
Settings window's Drawings page, hides New Drawing, Open Drawing, the Drawing button and the
Make Drawing entries while it is off (:attr:`DrawingController.enabled`).

Each New Drawing and Make Drawing first chooses how the drawing starts
(:mod:`.drawingmode`): Express, which makes a simple drawing of the key sizes with no
questions and opens it in the editor; Guided (:mod:`.drawingguided`), a few plain
questions in turn that make the drawing and open it in the editor; or Expert, the
wizard. The viewer's ``drawing_mode`` setting ("Remember my choice", or the Settings
window's Drawings page) skips the chooser.

A drawing is made by the New Drawing wizard (:mod:`.drawingwizard`) and edited in the
drawing editor (:mod:`.drawingeditor`), each imported when first wanted. The window has
one drawing process (:class:`.drawingproc.DrawingWorker`), started on first use, which
the wizard and every editor share. The wizard's ``drawing_written(path, open_editor)``
opens the editor on the file it wrote. An editor stays open until it is closed or the
window is, and a drawing already open in one is brought forward rather than opened
twice. Closing the window closes the wizard and every editor first (an editor that
keeps the window open, its user choosing not to lose changes, stops the close), then
ends the drawing process.

This module writes nothing: where a drawing and its exports go, and what Save may
replace, is the wizard's, Express's and the editor's business, through
``drawing.document``'s rules (12.6). The window's process reads no part and makes no drawing here.

The wizard, the editor, the settings dialog, the file dialog, the drawing process and
the messages are attributes, so the tests and the self-test's dry run
(``--drawing-dry-run``) stand in for them; with :attr:`DrawingController.dry_run` no
dialog or message is ever shown.
"""

import os
import stat
import weakref
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QEvent, QObject, QStandardPaths, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QFileDialog, QMenu, QMessageBox, QStyle, QToolBar

from solidseas.errors import SolidSeasError

from . import experimental, reading
from .printaction import PrintTarget, item_text
from .wording import tip

# A Make Drawing entry waiting for its menu to open: given the menu and the entry to put
# it before, it puts it in. It takes the menu rather than holding it, so a menu waiting to
# open is held weakly.
Builder = Callable[[QMenu, "QAction | None"], QAction]

TITLE = "Drawing"
PARTS_ONLY = "Drawings are made of SOLIDWORKS parts and assemblies in this release."
NEW_TEXT = experimental.tagged("New &Drawing...")
NEW_SHORTCUT = "Ctrl+D"
NEW_ICON_TEXT = "Drawing"
NEW_TIP = (
    "Make a drawing of the SOLIDWORKS part or assembly shown: its views, dimensions (an assembly's parts "
    "list and balloons) and title block, saved as a SolidSeas drawing with its PDF and DXF"
)
OPEN_TEXT = experimental.tagged("Open Dra&wing...")
OPEN_TIP = "Open a SolidSeas drawing (.ssdrw) in the drawing editor"
SETTINGS_TEXT = experimental.tagged("&Drawing Settings...")
SETTINGS_TIP = (
    "Your company, the people who sign, the standard, sheets, tolerances and the other settings drawings "
    "are made with"
)
PRINT_PREFIX = "3D Print "  # how every 3D Print entry of a menu begins (.printaction)
MAKE_PREFIX = "Make Drawing of "
EXTENSION = ".ssdrw"
FILTERS = "SolidSeas drawings (*.ssdrw)"
DRAWING_SHOWN = (
    "a SOLIDWORKS drawing",
    "The document shown is a SOLIDWORKS drawing. " + PARTS_ONLY,
)
ONE_WIZARD = "A New Drawing wizard is already open: finish it or close it first."
NOT_HERE = "{what} is not in this viewer, so drawings cannot be {done} here."
STARTS = ("express", "guided", "expert")  # how a drawing can start (drawingmode.MODES)


def refusal(target: PrintTarget) -> tuple[str, str] | None:
    """Why no drawing can be made of ``target``, as a few words for a menu entry and the
    reason in full; None for a SOLIDWORKS part or assembly of its own file. A drawing,
    a part or sub-assembly stored inside an assembly (with no file of its own) and a 3D
    file of another format are refused: the drawing library reads SOLIDWORKS parts and
    assemblies in this release."""
    name = target.name
    if target.doc_type == "drawing":
        return "a SOLIDWORKS drawing", f"{name} is a SOLIDWORKS drawing. {PARTS_ONLY}"
    fmt = target.model_format
    if fmt is not None:
        label = format_label(fmt)
        return (
            "not a SOLIDWORKS part",
            f"{name} is a 3D file of another format ({label}), not a SOLIDWORKS part. {PARTS_ONLY}",
        )
    if target.source.nested or target.virtual:
        what = "an assembly" if target.doc_type == "assembly" else "a part"
        return (
            "stored inside its assembly",
            f"{name} is stored inside the assembly that uses it, with no file of its own, and a drawing is "
            f"made from its own file. Save it as {what} of its own in SOLIDWORKS to draw it.",
        )
    if target.doc_type not in (None, "part", "assembly"):
        return "not a part", f"{name} is not a part. {PARTS_ONLY}"
    return None


def format_label(fmt: str) -> str:
    """The display name of the 3D format ``fmt`` (a registry id)."""
    from solidseas.formats import registry

    spec = registry.FORMATS.get(fmt)
    return spec.name if spec is not None else fmt


def make_text(print_text: str) -> str:
    """The Make Drawing entry beside the 3D Print entry reading ``print_text``: "3D Print
    bracket.SLDPRT" gives "Make Drawing of bracket.SLDPRT...", and "3D Print This Part"
    gives "Make Drawing of This Part..."."""
    rest = print_text[len(PRINT_PREFIX) :] if print_text.startswith(PRINT_PREFIX) else ""
    return f"{MAKE_PREFIX}{rest}..." if rest else "Make Drawing..."


def said_of_drawing(text: str) -> str:
    """Why a 3D Print entry cannot print, said of a drawing instead."""
    return text.replace("cannot be 3D printed", "cannot be drawn")


def drawing_file_problem(path: str) -> str | None:
    """Why ``path`` cannot be opened as a drawing, before the editor reads it; None when
    it is a plain ``.ssdrw`` file. Only its name and ``lstat`` are looked at."""
    if not path.lower().endswith(EXTENSION):
        return "it is not a SolidSeas drawing (.ssdrw)"
    try:
        st = os.lstat(path)
    except OSError as exc:
        return f"it could not be found ({exc.strerror or exc})"
    if stat.S_ISLNK(st.st_mode) or int(getattr(st, "st_file_attributes", 0) or 0) & 0x400:
        return "it is a link, and SolidSeas opens a drawing only from a plain file"
    if not stat.S_ISREG(st.st_mode):
        return "it is not a plain file"
    return None


def _open(widget: Any) -> bool:
    """Whether a wizard or an editor is still open: shown, and not deleted."""
    try:
        return bool(widget.isVisible())
    except (AttributeError, RuntimeError):  # deleted by Qt, or a stand-in without the method
        return False


def _insert_after(widget: QMenu | QToolBar, anchor: QAction | None, actions: list[QAction | None]) -> None:
    """Put ``actions`` (None: a separator) in ``widget`` right after ``anchor``, or at
    its end when ``anchor`` is not in it."""
    present = widget.actions()
    at = present.index(anchor) + 1 if anchor in present else len(present)
    before = present[at] if at < len(present) else None
    for action in actions:
        if action is None:
            sep = QAction(widget)
            sep.setSeparator(True)
            action = sep
        _put(widget, action, before)


def _put(widget: QMenu | QToolBar, action: QAction, before: QAction | None) -> None:
    if before is None:
        widget.addAction(action)
    else:
        widget.insertAction(before, action)


def _wizard_class() -> Any:
    from .drawingwizard import DrawingWizard

    return DrawingWizard


def _guided_class() -> Any:
    from .drawingguided import GuidedWizard

    return GuidedWizard


def _editor_class() -> Any:
    from .drawingeditor import DrawingEditor

    return DrawingEditor


def _settings_dialog_class() -> Any:
    from .drawingsettings import DrawingSettingsDialog

    return DrawingSettingsDialog


def _worker_class() -> Any:
    from .drawingproc import DrawingWorker

    return DrawingWorker


def _limits(settings: Any) -> Any:
    """The drawing process's bounds: the defaults, held to Drawing Settings' child memory."""
    from solidseas.drawing.limits import DEFAULT_LIMITS, DrawingLimits
    from solidseas.errors import InvalidArgumentError

    mb = getattr(getattr(settings, "limits", None), "child_memory_mb", None)
    if not isinstance(mb, int) or isinstance(mb, bool) or mb == DEFAULT_LIMITS.child_memory_mb:
        return DEFAULT_LIMITS
    try:
        return DrawingLimits(child_memory_mb=mb)
    except (InvalidArgumentError, TypeError, ValueError):
        return DEFAULT_LIMITS


class DrawingController(QObject):
    """New Drawing, Make Drawing, Open Drawing and Drawing Settings for ``window`` (see
    the module notes).

    Stand-ins: ``make_wizard`` (``DrawingWizard(parent, worker, part, *,
    configuration, settings, settings_path, folder)`` with its signal
    ``drawing_written(path, open_editor)``), ``make_guided`` (``GuidedWizard``, made
    and connected the same way), ``make_editor`` (``DrawingEditor(worker,
    path, *, settings, settings_path, parent)``), ``make_settings_dialog``
    (``DrawingSettingsDialog(parent, *, path, page, on_saved)``) and ``make_worker``
    (``DrawingWorker(limits)``), each None for the real one, imported when first
    wanted; ``pick_drawing`` (Open Drawing's file dialog: a path, or "" when
    cancelled), ``message`` (a message box), ``load_settings`` (Drawing Settings and
    the problems reading them found) and ``settings_path`` (None: the user's
    ``Drawing.json``). With ``dry_run`` nothing is shown: what a message would say is
    kept in :attr:`said`, and the first-use dialog is noted there instead of opened.
    :attr:`last` is what the last New Drawing or Make Drawing did."""

    written = Signal(str)  # the path of a drawing the wizard wrote
    opened = Signal(object)  # an editor, once it is open

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.worker: Any = None  # the window's drawing process, made on first use
        self.wizard: Any = None  # the New Drawing wizard, or the Guided one, while it is open
        self.editors: list[tuple[str, Any]] = []  # (the drawing's path as compared, its editor)
        self.make_wizard: Callable[..., Any] | None = None
        self.make_guided: Callable[..., Any] | None = None
        self.make_editor: Callable[..., Any] | None = None
        self.make_settings_dialog: Callable[..., Any] | None = None
        self.make_worker: Callable[..., Any] | None = None
        # How a drawing starts (:mod:`.drawingmode`): choose_mode(name) -> (mode or None,
        # remember), the chooser, which tests replace; make_express(...) -> an ExpressRun
        self.choose_mode: Callable[[str], tuple[str | None, bool]] = self._choose_mode
        self.make_express: Callable[..., Any] | None = None
        self.express: Any = None  # the Express drawing being made, while it is
        self.settings_path: str | None = None
        self.pick_drawing: Callable[[str], str] = self._pick_drawing
        self.message: Callable[[QMessageBox.Icon, str], None] = self._message
        self.load_settings: Callable[[], tuple[Any, list[str]]] = self._load_settings
        self.dry_run = False
        self.said: list[str] = []
        self.last: dict[str, Any] | None = None
        self._asked_first_use = False
        self._following = False
        # menus waiting to open, held weakly: a menu built and never shown must not be kept
        # alive here, to be freed later by the cycle collector on whatever thread it runs
        self._pending: weakref.WeakKeyDictionary[QMenu, list[tuple[QAction, Builder]]]
        self._pending = weakref.WeakKeyDictionary()
        self._closed = False
        self.icon = window.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)

        self.new_action = QAction(self.icon, NEW_TEXT, window)
        self.new_action.setShortcut(QKeySequence(NEW_SHORTCUT))
        self.new_action.setIconText(NEW_ICON_TEXT)
        self.new_action.setToolTip(tip(NEW_TIP))
        self.new_action.setStatusTip(NEW_TIP)
        self.new_action.triggered.connect(self.new_drawing)
        self.open_action = QAction(OPEN_TEXT, window)
        self.open_action.setToolTip(tip(OPEN_TIP))
        self.open_action.setStatusTip(OPEN_TIP)
        self.open_action.triggered.connect(self.open_drawing)
        self.settings_action = QAction(SETTINGS_TEXT, window)
        self.settings_action.setToolTip(tip(SETTINGS_TIP))
        self.settings_action.setStatusTip(SETTINGS_TIP)
        self.settings_action.triggered.connect(lambda _on=False: self.edit_settings())

    # -- in the window --------------------------------------------------------------------
    def install(self, file_menu: QMenu, settings_menu: QMenu, toolbar: QToolBar) -> None:
        """Put the entries in the window: New Drawing and Open Drawing after 3D Print in
        ``file_menu``, Drawing Settings after the AI settings in ``settings_menu``, the
        Drawing button beside 3D Print on ``toolbar``; Make Drawing beside every 3D Print
        entry of a right-click menu; New Drawing kept on or off with the document shown
        (after each of the window's own updates); and the window's close closing the
        wizard, the editors and the drawing process."""
        w = self.window
        _insert_after(file_menu, w.printer.action, [None, self.new_action, self.open_action])
        anchor = getattr(w, "act_ai_settings", None) or getattr(w, "act_preferences", None)
        _insert_after(settings_menu, anchor, [self.settings_action])
        _insert_after(toolbar, w.printer.action, [self.new_action])
        self._follow_prints(w.printer)
        # Weak references only: a closure the window held that held the window would make
        # a reference cycle of Qt objects, which Python's cycle collector may free on any
        # thread (a worker's), taking the window's widgets with it off the GUI thread.
        update, me = weakref.WeakMethod(w._update_actions), weakref.ref(self)

        def updated() -> None:  # the window's updates, then this one's
            window_update, controller = update(), me()
            if window_update is not None:
                window_update()
            if controller is not None:
                controller.update_actions()

        w._update_actions = updated
        w.installEventFilter(self)
        self.update_actions()

    def _follow_prints(self, printer) -> None:
        """Make Drawing after each 3D Print entry the print controller adds to a menu,
        from the same resolve (or off for the same reason), put in when the menu opens."""
        # weakly, as install's update: the print controller holds these closures
        add_action = weakref.WeakMethod(printer.add_action)
        add_unavailable = weakref.WeakMethod(printer.add_unavailable)
        me = weakref.ref(self)

        def action(menu: QMenu, text: str, resolve, *, what: str = "it") -> QAction:
            self, add = me(), add_action()
            if add is None:
                raise RuntimeError("the 3D Print entries' controller is gone")
            if self is None or self._following:  # the print controller's own call from add_unavailable
                return add(menu, text, resolve, what=what)
            self._following = True
            try:
                entry = add(menu, text, resolve, what=what)
            finally:
                self._following = False
            self._later(
                menu,
                entry,
                lambda m, before: me().add_action(m, make_text(text), resolve, what=what, before=before),
            )
            return entry

        def unavailable(menu: QMenu, text: str, reason: str, why: str) -> QAction:
            self, add = me(), add_unavailable()
            if add is None:
                raise RuntimeError("the 3D Print entries' controller is gone")
            if self is None or self._following:
                return add(menu, text, reason, why)
            self._following = True
            try:
                entry = add(menu, text, reason, why)
            finally:
                self._following = False
            self._later(
                menu,
                entry,
                lambda m, before: me().add_unavailable(
                    m, make_text(text), reason, said_of_drawing(why), before=before
                ),
            )
            return entry

        printer.add_action = action
        printer.add_unavailable = unavailable

    def _later(self, menu: QMenu, after: QAction, build: "Builder") -> None:
        """Note a Make Drawing entry for ``menu``, to go right after ``after`` when the
        menu opens (:meth:`fill`)."""
        pending = self._pending.get(menu)
        if pending is None:
            pending = self._pending[menu] = []
            mref, me = weakref.ref(menu), weakref.ref(self)

            def show() -> None:  # weakly: the menu holds this connection
                m, controller = mref(), me()
                if m is not None and controller is not None:
                    controller.fill(m)

            menu.aboutToShow.connect(show)
        pending.append((after, build))

    def fill(self, menu: QMenu) -> list[QAction]:
        """Put ``menu``'s Make Drawing entries in now, each right after its 3D Print entry
        (after the ones already put there, for a menu whose prints share one Cancel 3D
        Print entry); what :meth:`.QMenu.aboutToShow` does. The entries put in."""
        mine: list[QAction] = []
        pending = self._pending.pop(menu, [])
        if not self.enabled:
            return mine
        for after, build in pending:
            present = menu.actions()
            at = present.index(after) + 1 if after in present else len(present)
            while at < len(present) and present[at] in mine:
                at += 1
            mine.append(build(menu, present[at] if at < len(present) else None))
        return mine

    def _shown_type(self) -> str | None:
        """What the details panel shows: ``part``, ``assembly``, ``drawing`` or None."""
        w = self.window
        e, summary = w._entry, w.details.summary
        if summary is not None:
            return summary.get("doc_type")
        return reading.doc_type_of(e) if e else None

    def shown_refusal(self) -> tuple[str, str] | None:
        """Why New Drawing is off for the document shown, or None: it is on, or nothing
        that could be drawn is shown."""
        target = self.window.print_target()
        if target is not None:
            return refusal(target)
        return DRAWING_SHOWN if self._shown_type() == "drawing" else None

    @property
    def enabled(self) -> bool:
        """Whether drawings are switched on: the window's ``drawings`` setting, on when the
        window has none."""
        return bool(getattr(getattr(self.window, "settings", None), "drawings", True))

    def update_actions(self) -> None:
        """New Drawing on for a SOLIDWORKS part shown; off otherwise, its tooltip saying
        why for an assembly, a SOLIDWORKS drawing or a 3D file of another format. With
        drawings switched off, New Drawing and Open Drawing are not shown."""
        shown = self.enabled
        self.new_action.setVisible(shown)
        self.open_action.setVisible(shown)
        why = self.shown_refusal()
        a = self.new_action
        a.setEnabled(shown and not self._closed and why is None and self.window.print_target() is not None)
        text = NEW_TIP if why is None else why[1]
        a.setToolTip(tip(text))
        a.setStatusTip(text)

    def eventFilter(self, watched, event) -> bool:
        """The window's close: the wizard, the editors and the drawing process close
        first, and an editor that stays open keeps the window open."""
        if watched is self.window and event.type() == QEvent.Type.Close and not self._closed:
            if not self.close_all():
                event.ignore()
                return True
        return False

    # -- right-click menus -----------------------------------------------------------------
    def _peek(self, resolve: Callable[[], Any]) -> Any:
        """What ``resolve`` gives, asked without any question: the window's question of
        which of several files a reference means answers as cancelled (None), as it does
        for a print without ``ask``."""
        w = self.window
        own = vars(w)
        had, before = "choose_candidate" in own, own.get("choose_candidate")
        w.choose_candidate = lambda _t: None
        try:
            return resolve()
        except Exception:  # the entry is still offered; choosing it says what is wrong
            return None
        finally:
            if had:
                w.choose_candidate = before
            else:
                del w.choose_candidate

    def add_action(
        self,
        menu: QMenu,
        text: str,
        resolve: Callable[[], "PrintTarget | str | None"],
        *,
        what: str = "it",
        before: QAction | None = None,
    ) -> QAction:
        """A Make Drawing entry for ``menu`` (before ``before``, else at its end), reading
        ``text``, which draws what ``resolve`` gives once it is chosen (a
        :class:`.printaction.PrintTarget`, a reason it cannot be drawn, which is said, or
        None for nothing), as :meth:`.printaction.PrintController.add_action` prints it.
        Off, with the reason, when what it gives cannot be drawn (:func:`refusal`).
        ``what`` names the model in its tooltip."""
        got = self._peek(resolve)
        if isinstance(got, PrintTarget):
            why = refusal(got)
            if why is not None:
                return self.add_unavailable(menu, text, *why, before=before)
        action = QAction(self.icon, item_text(text), menu)
        line = f"Make a drawing of {what} with the New Drawing wizard"
        action.setToolTip(tip(line))
        action.setStatusTip(line)
        action.triggered.connect(lambda _on=False: self.draw_resolved(resolve))
        _put(menu, action, before)
        return action

    def add_unavailable(
        self, menu: QMenu, text: str, reason: str, why: str, *, before: QAction | None = None
    ) -> QAction:
        """A Make Drawing entry for ``menu`` (before ``before``, else at its end) that is
        off, its ``reason`` in a few words after ``text`` and ``why`` in full in its
        tooltip."""
        action = QAction(self.icon, f"{item_text(text)} ({reason})", menu)
        action.setEnabled(False)
        action.setToolTip(tip(why))
        action.setStatusTip(why.split("\n", 1)[0])
        _put(menu, action, before)
        return action

    def draw_resolved(self, resolve: Callable[[], "PrintTarget | str | None"]) -> dict[str, Any] | None:
        """Draw what ``resolve`` gives (see :meth:`add_action`)."""
        got = resolve()
        if isinstance(got, str):
            return self._cannot(said_of_drawing(got))
        if got is None:
            return None
        return self.start(got)

    # -- New Drawing ---------------------------------------------------------------------
    def new_drawing(self) -> dict[str, Any] | None:
        """File > New Drawing...: the part the details panel shows, in the configuration
        it shows."""
        if not self.enabled:
            return None
        target = self.window.print_target()
        if target is None:
            why = self.shown_refusal()
            return self._cannot(why[1]) if why is not None else None
        return self.start(target)

    def start(self, target: PrintTarget) -> dict[str, Any]:
        """Start a drawing of ``target``'s part: the one way every drawing starts, from
        the menu, the button, a right-click menu or the dry run. The mode is chosen first
        (:meth:`mode_for`): Express makes the drawing and opens it in the editor, Guided
        opens the Guided wizard, Expert the New Drawing wizard. Drawing Settings opens
        first on first use. What it did is :attr:`last`."""
        why = refusal(target)
        if why is not None:
            return self._cannot(why[1])
        if self._closed:
            return self._done({"ok": False, "closed": True})
        if self.wizard is not None and _open(self.wizard):
            self._raise(self.wizard)
            self._status(ONE_WIZARD, 8000)
            return self._done({"ok": False, "busy": True, "note": ONE_WIZARD})
        if self.express is not None and not self.express.finished:
            from .drawingmode import EXPRESS_BUSY

            self._status(EXPRESS_BUSY, 8000)
            return self._done({"ok": False, "busy": True, "note": EXPRESS_BUSY})
        mode = self.mode_for(target)
        if mode is None:
            return self._done({"ok": False, "cancelled": True})
        if mode == "express":
            return self.start_express(target)
        if mode == "guided":
            return self.start_guided(target)
        return self.start_expert(target)

    def mode_for(self, target: PrintTarget) -> str | None:
        """How the drawing of ``target`` starts: ``express``, ``guided`` or ``expert``,
        from the viewer's ``drawing_mode`` setting, else as chosen in the chooser (None:
        cancelled). "Remember my choice" saves the choice as the setting. The dry run
        always opens the wizard."""
        if self.dry_run:
            return "expert"
        settings = getattr(self.window, "settings", None)
        mode = getattr(settings, "drawing_mode", "ask")
        if mode in STARTS:
            return mode
        chosen, remember = self.choose_mode(os.path.basename(target.source.path))
        if chosen not in STARTS:
            return None
        if remember and settings is not None and callable(getattr(self.window, "apply_settings", None)):
            self.window.apply_settings(settings.but(drawing_mode=chosen))
        return chosen

    def _choose_mode(self, name: str) -> tuple[str | None, bool]:  # pragma: no cover - a modal dialog
        from .drawingmode import ask_mode

        return ask_mode(self.window, name)

    def start_express(self, target: PrintTarget) -> dict[str, Any]:
        """Make an Express drawing of ``target``'s part in the background, and open it in
        the editor once it is written (:mod:`.drawingmode`)."""
        settings, _problems = self.load_settings()
        first_use = self._first_use(settings)
        if first_use is not None:
            settings, _problems = self.load_settings()
        worker = self.ensure_worker(settings)
        part = target.source.path
        if self.make_express is not None:
            factory = self.make_express
        else:
            from .drawingmode import ExpressRun as factory
        run = factory(
            self, worker, part, configuration=target.configuration, settings=settings, folder=target.folder
        )
        run.done.connect(self._express_done)
        run.failed.connect(self._express_failed)
        self.express = run
        self._status(f"Making an Express drawing of {os.path.basename(part)}...", 0)
        run.start()
        return self._done(
            {
                "ok": True,
                "mode": "express",
                "part": part,
                "configuration": target.configuration,
                "folder": target.folder,
                "first_use": first_use,
            }
        )

    def _express_done(self, path: str) -> None:
        if self._closed:
            return
        self._written(path, True)

    def _express_failed(self, words: str) -> None:
        if self._closed:
            return
        self._cannot(f"The Express drawing was not made: {words}")

    def start_expert(self, target: PrintTarget) -> dict[str, Any]:
        """Open the New Drawing wizard on ``target``'s part, with every option."""
        try:
            factory = self.make_wizard or _wizard_class()
        except ImportError:
            return self._cannot(NOT_HERE.format(what="The New Drawing wizard", done="made"))
        return self._start_wizard(factory, target, "expert")

    def start_guided(self, target: PrintTarget) -> dict[str, Any]:
        """Open the Guided wizard on ``target``'s part: a few plain questions, then the
        editor (:mod:`.drawingguided`)."""
        try:
            factory = self.make_guided or _guided_class()
        except ImportError:
            return self._cannot(NOT_HERE.format(what="The Guided drawing", done="made"))
        return self._start_wizard(factory, target, "guided")

    def _start_wizard(self, factory: Callable[..., Any], target: PrintTarget, mode: str) -> dict[str, Any]:
        """Open the wizard ``factory`` makes on ``target``'s part, Drawing Settings first on
        first use; the wizard's ``drawing_written`` opens the editor."""
        settings, _problems = self.load_settings()
        first_use = self._first_use(settings)
        if first_use is not None:
            settings, _problems = self.load_settings()
        worker = self.ensure_worker(settings)
        part = target.source.path
        wizard = factory(
            self.window,
            worker,
            part,
            configuration=target.configuration,
            settings=settings,
            settings_path=self.settings_file(),
            folder=target.folder,
        )
        wizard.drawing_written.connect(self._written)
        self.wizard = wizard
        wizard.show()
        return self._done(
            {
                "ok": True,
                "mode": mode,
                "part": part,
                "configuration": target.configuration,
                "folder": target.folder,
                "first_use": first_use,
            }
        )

    def _first_use(self, settings: Any) -> str | None:
        """On first use, Drawing Settings on the first page that waits for an answer, once
        a session; the page, or None when nothing waits (or it was asked already)."""
        from .drawingsettings import first_use_prompts

        prompts = [p for p in first_use_prompts(settings) if p[0]]
        if not prompts or self._asked_first_use:
            return None
        self._asked_first_use = True
        page = prompts[0][0]
        if self.dry_run:
            self.said.append(f"Drawing Settings would open on {page} first.")
            return page
        self.edit_settings(page)
        return page

    def _written(self, path: str, open_editor: bool = True) -> None:
        """The wizard wrote ``path``: say so, and open it in the editor when asked."""
        self._status(f"Saved the drawing {path}", 12000)
        self.written.emit(path)
        if open_editor:
            self.open_editor(path)

    # -- the editor -------------------------------------------------------------------------
    def open_editor(self, path: str) -> Any:
        """The drawing editor on the ``.ssdrw`` at ``path``: the one already open on it,
        brought forward, or a new one. None when it could not be opened (said)."""
        if self._closed:
            return None
        path = os.path.abspath(path)
        key = os.path.normcase(path)
        self.editors = [(k, e) for k, e in self.editors if _open(e)]
        for k, editor in self.editors:
            if k == key:
                self._raise(editor)
                return editor
        try:
            factory = self.make_editor or _editor_class()
        except ImportError:
            self._cannot(NOT_HERE.format(what="The drawing editor", done="edited"))
            return None
        settings, _problems = self.load_settings()
        try:
            editor = factory(
                self.ensure_worker(settings),
                path,
                settings=settings,
                settings_path=self.settings_file(),
                parent=None,
            )
        except (OSError, ValueError, SolidSeasError) as exc:  # a file the editor refuses
            reason = getattr(exc, "strerror", None) or str(exc)
            self._cannot(f"The drawing could not be opened: {reason}\n\n{path}")
            return None
        self.editors.append((key, editor))
        editor.show()
        self.opened.emit(editor)
        return editor

    def open_drawing(self) -> Any:
        """File > Open Drawing...: a ``.ssdrw`` chosen in a file dialog, in the editor."""
        if not self.enabled:
            return None
        path = self.pick_drawing(self._start_folder())
        if not path:
            return None
        path = os.path.normpath(path)
        problem = drawing_file_problem(path)
        if problem is not None:
            self._cannot(f"{os.path.basename(path)} cannot be opened: {problem}.")
            return None
        return self.open_editor(path)

    def _start_folder(self) -> str:
        return self.window.folder or QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation
        )

    def _pick_drawing(self, start: str) -> str:
        from .window import _dialog

        return _dialog(
            lambda: QFileDialog.getOpenFileName(self.window, "Open a drawing", start, FILTERS)[0],
            remember=self.window.settings.remember_session,
        )

    # -- Drawing Settings -------------------------------------------------------------------
    def settings_file(self) -> str:
        """Where Drawing Settings are kept: :attr:`settings_path`, else the user's own."""
        if self.settings_path is not None:
            return self.settings_path
        from solidseas.drawing.settings import settings_path

        return settings_path()

    def _load_settings(self) -> tuple[Any, list[str]]:
        from solidseas.drawing.settings import load_settings

        return load_settings(self.settings_file())

    def edit_settings(self, page: str | None = None) -> None:
        """Settings > Drawing Settings...: the dialog, on ``page`` (None: the first that
        waits for an answer, else the first)."""
        if self.dry_run:
            self.said.append("Drawing Settings would open.")
            return
        if self.make_settings_dialog is None and callable(getattr(self.window, "open_settings", None)):
            # the Settings window, on Drawings or the page asked for (:mod:`.settingswindow`)
            self.window.open_settings(page or "Drawings")
            return
        factory = self.make_settings_dialog or _settings_dialog_class()
        dialog = factory(self.window, path=self.settings_file(), page=page, on_saved=self._settings_saved)
        try:
            dialog.exec()
        finally:
            inner = getattr(dialog, "dialog", None)  # the dialog the settings page wraps
            if inner is not None:
                inner.deleteLater()

    def _settings_saved(self, _settings: Any) -> None:
        self._status("Drawing Settings saved. Drawings made from now on use them.", 8000)

    # -- the drawing process ----------------------------------------------------------------
    def ensure_worker(self, settings: Any = None) -> Any:
        """The window's drawing process, made on first use (its child starts with the
        first request), bounded by Drawing Settings' child memory."""
        if self.worker is None:
            factory = self.make_worker or _worker_class()
            self.worker = factory(_limits(settings))
        # An assembly's parts are looked for in the folder the window has open at each
        # request, as 3D Print looks.
        self.worker.folder = lambda: getattr(self.window, "folder", None) or None
        return self.worker

    def close_all(self) -> bool:
        """The window is closing: close the wizard and every editor, then end the drawing
        process. False, and nothing more closed, when an editor stays open."""
        for _key, editor in list(self.editors):
            if _open(editor) and editor.close() is False:
                self._raise(editor)
                return False
        self.editors = []
        if self.wizard is not None and _open(self.wizard):
            self.wizard.close()
        self.wizard = None
        self.shutdown()
        return True

    def shutdown(self) -> None:
        """End the drawing process (a request in progress stops at once, and the wizard's
        or an editor's thread waiting on it gets ``ProcessStopped``) and take no more
        drawings."""
        self._closed = True
        self.new_action.setEnabled(False)
        if self.worker is not None:
            self.worker.close()

    # -- what is said -----------------------------------------------------------------------
    def _message(self, icon: QMessageBox.Icon, text: str) -> None:
        from .window import show_message

        show_message(self.window, icon, TITLE, text)

    def _status(self, text: str, ms: int = 8000) -> None:
        self.window.statusBar().showMessage(text, ms)

    def _cannot(self, text: str) -> dict[str, Any]:
        if self.dry_run:
            self.said.append(text)
        else:
            self.message(QMessageBox.Icon.Information, text)
        return self._done({"ok": False, "cannot": text})

    @staticmethod
    def _raise(widget: Any) -> None:
        for name in ("show", "raise_", "activateWindow"):
            fn = getattr(widget, name, None)
            if fn is not None:
                fn()

    def _done(self, outcome: dict[str, Any]) -> dict[str, Any]:
        self.last = outcome
        return outcome


__all__ = [
    "DRAWING_SHOWN",
    "NEW_SHORTCUT",
    "NEW_TEXT",
    "OPEN_TEXT",
    "PARTS_ONLY",
    "SETTINGS_TEXT",
    "DrawingController",
    "drawing_file_problem",
    "format_label",
    "make_text",
    "refusal",
    "said_of_drawing",
]
