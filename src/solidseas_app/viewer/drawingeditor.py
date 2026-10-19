"""The drawing editor (``docs/DRAWINGS.md`` 15.4): a window per drawing, with the edits
of 10.12, saving under 12.6, signing, release and revisions under 13, and Email PDF
under 15.5.

:class:`DrawingEditor` is a ``QMainWindow`` opened on a ``.ssdrw`` on disk:

* **Centre:** the sheet in a :class:`~.drawingscene.SheetView` of a
  :class:`~.drawingscene.SheetScene`, picked and hovered by owner. Dragging a
  dimension is ``edit.move``: the scene's drop, in sheet millimetres, becomes the
  dimension's offset along its line and across it (:func:`placement_delta`).
* **Left:** the dimensions grouped by view, each with a tick box (unticking removes a
  generated dimension and deletes one the user added; ticking restores), its text,
  kind, band and badges (:data:`BADGES`).
* **Right:** Properties of what is selected: a dimension's measured value
  (read-only), precision and band, prefix and suffix, value override with its
  warning, tolerance, the frame editor, Reset Position and Flip; a note's text; the
  title fields when nothing else is selected.
* **Add Dimension (D):** features picked on the sheet (through the dimensions drawn
  for them, ``owners_of_feature``) or ticked in a list; the planner's candidates with
  their values (``worker.candidates``); Add.
* **Checks:** the checklist of 20.1, each row selecting what it is about and offering
  its fixes as buttons; rows that block release are marked.
* **An assembly's drawing** (``docs/drawings/assemblies.md``) has its parts list and
  balloons on the sheet, and its overall size for reference: a balloon is dragged
  to a new place, its leader following (``edit.move_balloon``, undoable); Add
  Dimension, Remove Dimension, Reset Position and Tolerance Block are off, their
  tooltips saying why; the title fields,
  notes, sheet and scale, units, signing, release and Update from Model are as for a
  part.
* **Status bar:** the status and revision, and the model: "Model unchanged", "The
  model has changed. Update Drawing", "Model not found. Find...".

**Nothing runs on the UI thread but Qt.** Every library request goes to the
:class:`~.drawingproc.DrawingWorker` the editor is given (a child process), from a
thread of the application's pool (never one of the window's own, which would make
closing the window wait), one step at a time in the order asked
(:meth:`DrawingEditor.wait` lets a test or the self-test wait for them). Reading the
``.ssdrw``, looking for the model's file (``locate.find_model``, which hashes it),
saving and writing exports are file work on that thread too; the window imports only
the quick and pure parts of the library.

**The model.** Opening a drawing attaches its model (``worker.attach`` with the
drawing's path, 13.6). When no file with the drawing's hash is found the drawing is
view-only: the bar says whether a changed model was found (Update Drawing takes it)
or none (Find... chooses the model's file). An edit answered ``ModelNotFoundError``
(the child was started again) attaches again and asks once more. The child lets go of
the model after five idle minutes (8.12, ``worker.forget``), and the next edit
attaches it again.

**Saving** follows 12.6. Save replaces only the drawing's own unchanged file: the
editor keeps the SHA-256 of the file as it read or last saved it and gives it to
``document.save_target`` as ``loaded_sha256``; anything else gets a new name and the
editor carries on with that file. With ``replace_own_files`` off every save is a new
file. With "keep preliminary exports up to date" on, Save rewrites the PRELIMINARY PDF
and DXF ``outputs`` lists when they are this drawing's own unchanged files, and leaves
any other file alone. Released exports are created new, never replaced. The two
switches are read from the current Drawing Settings (the user's answer), the rest of
the snapshot from the drawing. A refused folder never sends a file elsewhere: Save
opens Save As with the reason, and an export asks for another folder.

**Undo and Redo** are a ``QUndoStack`` of the drawings before and after each edit; a
save marks the stack clean and undo keeps working after it. The records of the files
written (``outputs``) are facts about the disk, not edits, so undo keeps them.
Release empties the stack: a RELEASED drawing is read-only but for Start Revision.

**What asks the user** goes through methods a test or the self-test replaces on the
instance: :meth:`~DrawingEditor.ask_save_path`, :meth:`~DrawingEditor.ask_folder`,
:meth:`~DrawingEditor.ask_model_path`, :meth:`~DrawingEditor.ask_question`,
:meth:`~DrawingEditor.ask_close`, :meth:`~DrawingEditor.tell` and
:meth:`~DrawingEditor.run_dialog` (each command's small dialog, whose fields are in
``dialog.fields``). Each command also takes its answers as arguments, so it can be
driven without a dialog.
"""

from __future__ import annotations

import math
import os
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from solidseas.drawing import display as D
from solidseas.drawing import document, locate, release, standards
from solidseas.drawing import numbers as dnumbers
from solidseas.drawing import settings as drawing_settings
from solidseas.drawing.assembly import is_assembly
from solidseas.drawing.types import SHEET_CHOICES, FrameCell
from solidseas.errors import InvalidArgumentError, ModelNotFoundError, SolidSeasError

from . import experimental, mail
from .drawingproc import ProcessStopped
from .drawingscene import SheetScene, SheetView

IDLE_SECONDS = 300  # 8.12: the child lets go of the model after five idle minutes
MODEL_UNCHANGED = "Model unchanged"
MODEL_CHANGED = "The model has changed. Update Drawing"
MODEL_NOT_FOUND = "Model not found. Find..."
MODEL_LOOKING = "Looking for the model..."
VIEW_ONLY = "This drawing is view-only: its model was not found. Find... the model to edit it."
VIEW_ONLY_CHANGED = "The model has changed since the drawing was made: Update from Model before editing."
READ_ONLY = "The drawing is RELEASED and read-only: Start Revision to change it."
LATER = "coming in a later release"
ASSEMBLY_OFF = ("add", "remove", "reset", "block")  # what an assembly's drawing has no use for
NO_DIMENSIONS = (
    "An assembly's drawing gives only its overall size, for reference: its parts list and balloons "
    "name its parts, and each part's own drawing gives its dimensions."
)
BADGES = ("new", "changed", "needs attention", "reference", "overridden", "basic")
# Checks the release refuses on, besides every error: COV.unclaimed until accepted with a
# reason, and the material and signatures, which are errors at release (20.1).
BLOCKING_AT_RELEASE = ("COV.unclaimed", "R6.material", "R6.signatures")
# A dimension's placement moves it (layout/place.py): a linear one along and across its
# line, a leader item's shoulder; an ordinate stays in its row and an angle where it is.
MOVABLE = ("linear", "diameter", "radius", "hole_callout", "chamfer", "leader_note")
TITLE_FIELDS = (
    ("title", "Title"),
    ("number", "Drawing number"),
    ("part_number", "Part number"),
    ("revision", "Revision"),
    ("model_revision", "Model revision"),
    ("material", "Material"),
    ("finish", "Finish"),
)
KIND_WORDS = {
    "linear": "linear",
    "diameter": "diameter",
    "radius": "radius",
    "angle": "angle",
    "ordinate": "ordinate",
    "chamfer": "chamfer",
    "hole_callout": "hole callout",
    "leader_note": "leader note",
    "datum_feature": "datum feature",
    "frame": "frame",
}
TOLERANCE_WORDS = (
    ("block", "From the block"),
    ("basic", "Basic"),
    ("reference", "Reference"),
    ("symmetric", "Plus and minus"),
    ("deviations", "Deviations"),
    ("limits", "Limits"),
    ("max", "MAX"),
    ("min", "MIN"),
)
OVERRIDE_WARNING = (
    "An overridden value is not the model's. Check R2.override is an error until it is "
    "accepted with a typed reason at Release, and the dimension carries a badge."
)
PICKED_COLOUR = QColor("#2e7d32")
_MODEL_OK = ("unchanged", "geometry", "looking")
_IN_FLIGHT: set = set()  # the steps running, held until they report back
_KINDS = {"pdf": "PDF", "dxf": "DXF"}


# --------------------------------------------------------------------------- words (no Qt)
def _unit(drawing: Any) -> str:
    unit = getattr(drawing.options, "units", "mm")
    return unit if unit in ("in", "mm") else "mm"


def _snapshot(drawing: Any) -> drawing_settings.DrawingSettings:
    s = getattr(drawing, "settings", None)
    return s if isinstance(s, drawing_settings.DrawingSettings) else drawing_settings.DrawingSettings()


def view_names(drawing: Any) -> dict[str, str]:
    """Each view id of the drawing with words for it: the principal views by their names
    (the frozen view set names them in the order their ids were given), else the
    view's label on the sheet, else its id."""
    out: dict[str, str] = {}
    views = drawing.options.views
    if isinstance(views, tuple):
        for k, name in enumerate(views, 1):
            out[f"v-{k}"] = f"{name.capitalize()} view"
    sheet = drawing.sheet
    for vp in getattr(sheet, "views", ()) or ():
        if getattr(vp, "label", "") and vp.view not in out:
            out[vp.view] = vp.label
    return out


def _value_words(drawing: Any, dim: Any) -> str:
    if dim.kind == "angle":
        return dnumbers.number(math.degrees(dim.value), max(0, dim.places), "mm") + standards.SYMBOL_DEGREE
    unit = _unit(drawing)
    return dnumbers.number(dnumbers.in_unit(dim.value, unit), max(0, dim.places), unit)


def dimension_text(drawing: Any, dim: Any, annotation: Any = None) -> str:
    """A dimension's text as the list shows it: as the sheet draws it when it is on the
    sheet, else its prefix, value (or override) and suffix; a datum feature by its
    letter."""
    if dim.kind == "datum_feature":
        letter = dim.key.split("/")[-1].upper() if dim.key.startswith("datum/") else ""
        return f"Datum {letter}".strip()
    if annotation is not None and isinstance(getattr(annotation, "text", None), D.DimText):
        t = annotation.text
        words = t.prefix + t.value + (" " + t.after if t.after else "")
        if t.upper or t.lower:
            words += f" {t.upper}/{t.lower}"
        words = " ".join(p for p in (words.strip(), *t.suffix) if p)
        if words:
            return words
    override = getattr(dim, "override", None)
    value = override if override else _value_words(drawing, dim)
    return " ".join(p for p in (dim.prefix, value, *dim.suffix) if p)


def measured_text(drawing: Any, dim: Any) -> str:
    """The value the model measures, in the drawing's unit (degrees for an angle), to
    more places than any drawing shows."""
    if dim.kind in ("datum_feature", "frame"):
        return ""
    if dim.kind == "angle":
        return f"{math.degrees(dim.value):.4f}{standards.SYMBOL_DEGREE}"
    unit = _unit(drawing)
    return f"{dnumbers.number(dnumbers.in_unit(dim.value, unit), 5 if unit == 'in' else 4, unit)} {unit}"


def band_text(drawing: Any, dim: Any) -> str:
    """The tolerance band a dimension falls in (10.8): the general block's row for its
    precision, ``basic``, ``reference``, or its explicit tolerance."""
    if dim.kind in ("datum_feature", "frame"):
        return ""
    tol = dim.tolerance
    if tol in ("basic", "reference"):
        return tol
    unit = _unit(drawing)
    settings = _snapshot(drawing)
    if dim.kind == "angle" and tol in ("block", "derived"):
        return f"{standards.SYMBOL_PLUS_MINUS}{settings.tolerances.angle:g}{standards.SYMBOL_DEGREE}"
    if tol in ("block", "derived"):
        pm = dnumbers.block_plus_minus(unit, dim.places, settings.block(unit))
        return dnumbers.band_text(pm, unit) if pm is not None else "no row of the block"
    up, lo = dim.tolerance_values
    places = max(0, dim.places)
    if tol == "symmetric":
        return standards.SYMBOL_PLUS_MINUS + dnumbers.number(up, places, unit)
    if tol in ("max", "min"):
        return tol.upper()
    return f"{tol} {dnumbers.number(up, places, unit)}, {dnumbers.number(lo, places, unit)}"


def badges(dim: Any) -> tuple[str, ...]:
    """A dimension's badges, in the order of :data:`BADGES`."""
    flags = getattr(dim, "flags", ()) or ()
    found = {
        "new": "new" in flags,
        "changed": "changed" in flags,
        "needs attention": "needs_attention" in flags,
        "reference": dim.tolerance == "reference",
        "overridden": bool(getattr(dim, "override", None)),
        "basic": dim.tolerance == "basic",
    }
    return tuple(b for b in BADGES if found[b])


def placement_delta(annotation: Any, dx: float, dy: float) -> tuple[float, float]:
    """A drop of ``(dx, dy)`` sheet millimetres (y up) as ``edit.move``'s offsets: for a
    linear dimension along its line and across it (away from its view when positive);
    for a leader item the shoulder's x and y on the sheet."""
    points = getattr(annotation, "points", ())
    if getattr(annotation, "kind", "") == "linear" and len(points) >= 3:
        start, line = points[0], points[2]
        if abs(float(getattr(annotation, "angle_deg", 0.0)) - 90.0) < 1e-6:  # a vertical dimension
            outward = 1.0 if line[0] >= start[0] else -1.0
            return dy, outward * dx
        outward = 1.0 if line[1] >= start[1] else -1.0
        return dx, outward * dy
    return dx, dy


def blocks_release(check: Any) -> bool:
    """Whether a check stands in the way of Release (13.2, 20.1): every error, and the
    unclaimed geometry, material and signature checks that are errors at release."""
    return getattr(check, "level", "") == "error" or getattr(check, "code", "") in BLOCKING_AT_RELEASE


def material_needs_reason(drawing: Any) -> bool:
    """Whether Release needs the material accepted as typed: a material that the
    drawing's materials list does not map (13.2)."""
    settings = _snapshot(drawing)
    for key, f in drawing.title:
        if key == "material":
            if f.source == "list" or settings.material(f.text) is not None:
                return False
            return not any(e["callout"] == f.text for e in settings.materials.entries)
    return False


def report_text(report: Any) -> str:
    """The merge report as the editor shows it (13.5): its sentence, then its lines."""
    lines = [report.words(), *report.items]
    return "\n".join(dict.fromkeys(line for line in lines if line))


# --------------------------------------------------------------------------- the worker thread
class _Signals(QObject):
    done = Signal(object, object)  # the result, the exception


class _Runnable(QRunnable):
    """``fn()`` on a pool thread; ``done`` carries its result or its exception as it is."""

    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.fn = fn
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result, error = self.fn(), None
        except Exception as exc:  # crosses back to the window as it is, with its class
            result, error = None, exc
        self.signals.done.emit(result, error)


@dataclass
class _Ctx:
    """What a step works on, taken when it starts on the UI thread: the drawing, its
    file and that file's hash, the model's file and state, and whether the child has
    the model. ``attached`` is set on the worker thread when the step attached it."""

    drawing: Any
    path: str
    sha256: str | None
    model_path: str | None
    model: str
    attached: bool


@dataclass
class _Step:
    label: str
    work: Callable[[_Ctx], Any]
    done: Callable[[Any, _Ctx], None]
    failed: Callable[[BaseException, _Ctx], None] | None = None


class _ViewOnly(SolidSeasError):
    """An edit asked of a drawing whose model is not open."""


class _Change(QUndoCommand):
    """One edit: the drawing before and after it."""

    def __init__(self, editor: DrawingEditor, before: Any, after: Any, text: str, *, remodel: bool = False):
        super().__init__(text)
        self.editor, self.before, self.after, self.remodel = editor, before, after, remodel

    def redo(self) -> None:
        self.editor._from_history(self.after, self.remodel)

    def undo(self) -> None:
        self.editor._from_history(self.before, self.remodel)


class _Form(QDialog):
    """A command's small dialog: labelled fields (``fields`` by name), a note, OK and
    Cancel."""

    def __init__(self, parent: Any, title: str, note: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.fields: dict[str, Any] = {}
        layout = QVBoxLayout(self)
        if note:
            layout.addWidget(_plain(note))
        self.form = QFormLayout()
        layout.addLayout(self.form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def add(self, name: str, label: str, widget: Any) -> Any:
        self.fields[name] = widget
        self.form.addRow(_plain(label), widget)
        return widget


def _plain(text: str) -> QLabel:
    """A label that shows its text as plain text: a drawing's words are data."""
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


def _combo(items: Iterable[tuple[str, Any]], current: Any = None) -> QComboBox:
    box = QComboBox()
    for text, data in items:
        box.addItem(text, data)
    index = box.findData(current)
    if index >= 0:
        box.setCurrentIndex(index)
    return box


# --------------------------------------------------------------------------- the editor
class DrawingEditor(QMainWindow):
    """The drawing editor for the ``.ssdrw`` at ``path`` (see the module notes).
    ``worker`` is the :class:`~.drawingproc.DrawingWorker` it sends every request to
    (shared, never closed here); ``settings`` are the current Drawing Settings (read
    from ``settings_path``, else the user's file, when None) and ``settings_path`` the
    file Drawing Settings saves to."""

    changed = Signal()  # the drawing shown changed (an edit, undo, redo, save or export)

    def __init__(
        self,
        worker: Any,
        path: str | os.PathLike,
        *,
        settings: drawing_settings.DrawingSettings | None = None,
        settings_path: str | os.PathLike | None = None,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self.worker = worker
        self.path = os.path.abspath(os.fspath(path))
        self.settings = settings
        self.settings_path = os.fspath(settings_path) if settings_path is not None else None
        self.drawing: Any = None
        self.problems: tuple[str, ...] = ()  # what reading the file found
        self.messages: list[str] = []  # every status line said, the last last
        self.release_reasons: tuple[str, ...] = ()  # why the last Release was refused
        self.last_report: Any = None  # the last Update from Model's merge report
        self.last_delivery: Any = None  # what the last Email PDF did
        self.last_error: BaseException | None = None
        self.candidates: tuple[Any, ...] = ()  # Add Dimension's, for the features picked
        self.picked: list[str] = []  # Add Dimension's features
        self.adding = False  # whether Add Dimension is on: a pick picks a feature
        self.idle_ms = IDLE_SECONDS * 1000
        self.model_state = "looking"  # looking, unchanged, geometry, changed, missing
        self.model_path: str | None = None  # the model's file: found, changed or chosen
        self._sha256: str | None = None  # of the drawing's file as last read or saved
        self._attached = False  # whether the child has the model now
        self._unsaved = False  # a change outside the undo stack (outputs, release)
        self._selected = ""  # a dimension id, a note id, or "" for the title
        self._edit_log: list[str] = []
        self._reports: list[str] = []
        self._queue: deque[_Step] = deque()
        self._running: _Step | None = None
        self._runnable: _Runnable | None = None
        self._filling = False
        self._closed = False
        self._close_after_save = False
        self._settings_dialog: Any = None
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.timeout.connect(self._idle_forget)
        self.undo_stack = QUndoStack(self)
        self.undo_stack.cleanChanged.connect(lambda _clean: self._update_title())
        self.undo_stack.indexChanged.connect(lambda _i: self._update_actions())

        self._build()
        self.resize(1400, 900)
        self._sized = False
        self._update_title()
        self._update_actions()
        self._submit(_Step("Open", self._open_work, self._opened, self._open_failed))

    # ------------------------------------------------------------------ building
    def _build(self) -> None:
        self.scene = SheetScene(parent=self)
        self.view = SheetView(self.scene)
        self.setCentralWidget(self.view)
        self.scene.picked.connect(self._picked)
        self.scene.hovered.connect(self._hovered)
        self.scene.moved.connect(self._dragged)

        self.dimensions = QTreeWidget()
        self.dimensions.setColumnCount(4)
        self.dimensions.setHeaderLabels(["Dimension", "Kind", "Band", "Badges"])
        self.dimensions.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.dimensions.itemChanged.connect(self._dimension_ticked)
        self.dimensions.itemSelectionChanged.connect(self._dimension_chosen)
        self.dimensions_dock = self._dock("Dimensions", self.dimensions, Qt.DockWidgetArea.LeftDockWidgetArea)

        self.properties = _Properties(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.properties)
        self.properties_dock = self._dock("Properties", scroll, Qt.DockWidgetArea.RightDockWidgetArea)

        self.checks = QTreeWidget()
        self.checks.setColumnCount(4)
        self.checks.setHeaderLabels(["Level", "Check", "Release", "Message"])
        self.checks.setRootIsDecorated(False)
        self.checks.itemSelectionChanged.connect(self._check_chosen)
        self.fixes = QWidget()
        self.fixes_layout = QHBoxLayout(self.fixes)
        self.fixes_layout.setContentsMargins(0, 0, 0, 0)
        checks_box = QWidget()
        box = QVBoxLayout(checks_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.checks, 1)
        box.addWidget(self.fixes)
        self.checks_dock = self._dock("Checks", checks_box, Qt.DockWidgetArea.BottomDockWidgetArea)

        self.add_panel = _AddDimension(self)
        self.add_dock = self._dock("Add Dimension", self.add_panel, Qt.DockWidgetArea.RightDockWidgetArea)
        self.add_dock.hide()

        self.status_label = _plain("")
        self.status_label.setWordWrap(False)
        self.model_button = QPushButton(MODEL_LOOKING)
        self.model_button.setFlat(True)
        self.model_button.clicked.connect(self._model_clicked)
        self.statusBar().addPermanentWidget(self.status_label)
        self.statusBar().addPermanentWidget(self.model_button)
        self._actions()

    def _dock(self, title: str, widget: QWidget, area: Qt.DockWidgetArea) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(title)
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    def _action(self, menu: Any, text: str, slot: Callable[[], Any], shortcut: Any = None, tip: str = ""):
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        if tip:
            action.setToolTip(tip)
            action.setStatusTip(tip)
        action.triggered.connect(lambda _checked=False: slot())
        menu.addAction(action)
        return action

    def _actions(self) -> None:
        bar = self.menuBar()
        a: dict[str, QAction] = {}
        file = bar.addMenu("&File")
        a["save"] = self._action(file, "&Save", self.save, QKeySequence.StandardKey.Save)
        a["save_as"] = self._action(file, "Save &As...", self.save_as, QKeySequence.StandardKey.SaveAs)
        a["send"] = self._action(
            file,
            "Save a Copy to Send...",
            self.save_copy_to_send,
            tip="A copy of the drawing file that names no folder of this computer",
        )
        file.addSeparator()
        a["pdf"] = self._action(file, "Export &PDF...", self.export_pdf)
        a["dxf"] = self._action(file, "Export &DXF...", self.export_dxf)
        a["email"] = self._action(file, "&Email PDF...", self.email_pdf)
        file.addSeparator()
        a["close"] = self._action(file, "&Close", self.close, QKeySequence.StandardKey.Close)

        edit = bar.addMenu("&Edit")
        a["undo"] = self._action(edit, "&Undo", self.undo, QKeySequence.StandardKey.Undo)
        a["redo"] = self._action(edit, "&Redo", self.redo, QKeySequence.StandardKey.Redo)
        edit.addSeparator()
        a["add"] = self._action(edit, "Add &Dimension", self.toggle_add_dimension, "D")
        a["add"].setCheckable(True)
        a["remove"] = self._action(
            edit, "Remove Dimension", self.remove_selected, QKeySequence.StandardKey.Delete
        )
        a["reset"] = self._action(edit, "Reset Position", lambda: self.reset_position(self._selected))

        dwg = bar.addMenu(experimental.tagged("&Drawing"))
        a["update"] = self._action(dwg, "&Update from Model", self.update_from_model)
        a["parts"] = self._action(dwg, "Edit &Parts List...", self.edit_parts_list)
        a["parts"].setStatusTip("Choose the parts list's columns, order and text in the BOM editor")
        a["find"] = self._action(dwg, "&Find the Model...", self.find_model)
        dwg.addSeparator()
        a["sheet"] = self._action(dwg, "Sheet and Scale...", self.sheet_and_scale)
        a["units"] = self._action(dwg, "Units...", self.set_units)
        a["block"] = self._action(dwg, "Tolerance Block...", self.tolerance_block)
        a["notes"] = self._action(dwg, "Notes...", self.edit_notes)
        for key, text in (("detail", "Add Detail View"), ("section", "Add Section")):
            a[key] = self._action(dwg, f"{text} ({LATER})", lambda: None, tip=f"{text}: {LATER}")
            a[key].setEnabled(False)
        dwg.addSeparator()
        a["use_settings"] = self._action(dwg, "Use Current Drawing Settings", self.use_current_settings)
        a["settings"] = self._action(dwg, "Drawing Settings...", self.open_drawing_settings)

        status = bar.addMenu("&Status")
        a["sign"] = self._action(status, "&Sign...", self.sign)
        a["release"] = self._action(status, "&Release...", self.release)
        a["revision"] = self._action(status, "Start &Revision...", self.start_revision)

        tools = self.addToolBar("Drawing")
        tools.setObjectName("Drawing")
        for key in ("save", "undo", "redo", "add", "update", "sign", "release", "pdf", "email"):
            tools.addAction(a[key])
        self.actions_by_name = a

    # ------------------------------------------------------------------ what asks the user
    def ask_save_path(self, title: str, start: str) -> str | None:
        """A path to save a drawing file to, or None (Save As, Save a Copy to Send)."""
        path, _filter = QFileDialog.getSaveFileName(self, title, start, "SolidSeas drawings (*.ssdrw)")
        return path or None

    def ask_folder(self, title: str, start: str) -> str | None:
        """A folder to export to, or None."""
        return QFileDialog.getExistingDirectory(self, title, start) or None

    def ask_model_path(self, start: str) -> str | None:
        """The model's file (Find...), or None."""
        path, _filter = QFileDialog.getOpenFileName(
            self, "Find the Model", start, "SOLIDWORKS parts (*.sldprt *.SLDPRT)"
        )
        return path or None

    def ask_question(self, text: str) -> bool:
        """A yes or no question, such as the PRELIMINARY question of 13.2."""
        box = QMessageBox(QMessageBox.Icon.Question, "Drawing", text, parent=self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def ask_close(self) -> str:
        """``save``, ``discard`` or ``cancel`` for a drawing with unsaved changes."""
        box = QMessageBox(
            QMessageBox.Icon.Question, "Drawing", "Save the changes to the drawing?", parent=self
        )
        box.setTextFormat(Qt.TextFormat.PlainText)
        buttons = QMessageBox.StandardButton
        box.setStandardButtons(buttons.Save | buttons.Discard | buttons.Cancel)
        answer = box.exec()
        return {buttons.Save: "save", buttons.Discard: "discard"}.get(answer, "cancel")

    def tell(self, title: str, text: str) -> None:
        """Say something that needs reading (a refused release, a merge report)."""
        box = QMessageBox(QMessageBox.Icon.Information, title, text, parent=self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.exec()

    def run_dialog(self, dialog: QDialog) -> bool:
        """Show a command's dialog; whether it was accepted."""
        return dialog.exec() == QDialog.DialogCode.Accepted

    # ------------------------------------------------------------------ steps
    @property
    def busy(self) -> bool:
        """Whether a step is running or waiting."""
        return self._running is not None or bool(self._queue)

    def wait(self, timeout: float = 120.0) -> bool:
        """Let Qt run until every step asked so far has finished, at most ``timeout``
        seconds; whether they had. For tests and the self-test: a window never waits."""
        end = time.monotonic() + timeout
        app = QCoreApplication.instance()
        while self.busy:
            if time.monotonic() > end:
                return False
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
            if self.busy:
                time.sleep(0.002)
        app.processEvents()
        return True

    def _submit(self, step: _Step) -> None:
        if self._closed:
            return
        self._queue.append(step)
        self._update_actions()
        self._next()

    def _context(self) -> _Ctx:
        return _Ctx(self.drawing, self.path, self._sha256, self.model_path, self.model_state, self._attached)

    def _next(self) -> None:
        if self._running is not None or not self._queue or self._closed:
            return
        step = self._running = self._queue.popleft()
        ctx = self._context()
        runnable = _Runnable(lambda: step.work(ctx))
        runnable.signals.done.connect(lambda result, error: self._finished(step, ctx, result, error))
        self._runnable = runnable
        _IN_FLIGHT.add(runnable)  # kept until it reports back, whatever becomes of the window
        self._idle.stop()
        if step.label:
            self.statusBar().showMessage(f"{step.label}...")
        # The application's pool, not one of the window's: a pool waits for its running
        # task when it is destroyed, and a window closed during a long step must not.
        QThreadPool.globalInstance().start(runnable)

    def _finished(self, step: _Step, ctx: _Ctx, result: Any, error: BaseException | None) -> None:
        _IN_FLIGHT.discard(self._runnable)
        self._running = None
        self._runnable = None
        if self._closed:
            self._queue.clear()
            return
        if ctx.attached:
            self._attached = True
        said = len(self.messages)
        try:
            if error is None:
                step.done(result, ctx)
            else:
                self.last_error = error
                (step.failed or self._failed)(error, ctx)
        finally:
            if len(self.messages) == said and step.label:
                self.statusBar().clearMessage()  # the step's "...ing" said nothing more
            if self._attached and self.drawing is not None:
                self._idle.start(max(1, int(self.idle_ms)))
            self._update_actions()
            self._update_title()
            self._next()

    def _failed(self, error: BaseException, ctx: _Ctx, words: str = "") -> None:
        """Say why a step failed, and show the drawing as it is again (a tick box or a
        dragged dimension goes back)."""
        if isinstance(error, ModelNotFoundError):
            self._attached = False
            self._set_model("missing")
            self._say(VIEW_ONLY)
        elif isinstance(error, InvalidArgumentError) and (error.detail or {}).get("rule") == "model_changed":
            self._attached = False
            self._set_model("changed", ctx.model_path)
            self._say(VIEW_ONLY_CHANGED)
        elif (
            isinstance(error, InvalidArgumentError) and (error.detail or {}).get("rule") == "drawing_released"
        ):
            self._say(READ_ONLY)
        elif isinstance(error, _ViewOnly):
            self._say(str(error))
        elif isinstance(error, ProcessStopped):
            self._attached = False
            self._say(f"{words}: {error}" if words else str(error))
        elif isinstance(error, OSError):
            reason = error.strerror or str(error)
            self._say(f"{words}: {reason}" if words else reason)
        else:
            self._say(f"{words}: {error}" if words else str(error))
        if self.drawing is not None:
            self._show(self.drawing)

    def _say(self, text: str) -> None:
        self.messages.append(text)
        self.statusBar().showMessage(text)

    @property
    def last_message(self) -> str:
        return self.messages[-1] if self.messages else ""

    # ------------------------------------------------------------------ the model, in the thread
    def _attach(self, ctx: _Ctx) -> Any:
        if ctx.model_path:
            got = self.worker.attach(ctx.drawing, part=ctx.model_path)
        else:
            got = self.worker.attach(ctx.drawing, drawing_path=ctx.path)
        ctx.attached = True
        return got

    def _with_model(self, ctx: _Ctx, call: Callable[[Any], Any]) -> Any:
        """``call(drawing)`` with the drawing's model open in the child: attached first
        when the child has let go of it, and attached again and asked once more when the
        child answers that it has not got it."""
        if ctx.model == "changed":
            raise _ViewOnly(VIEW_ONLY_CHANGED)
        if ctx.model == "missing":
            raise _ViewOnly(VIEW_ONLY)
        if not ctx.attached:
            self._attach(ctx)
        try:
            return call(ctx.drawing)
        except ModelNotFoundError:
            self._attach(ctx)
            return call(ctx.drawing)

    # ------------------------------------------------------------------ opening
    def _open_work(self, ctx: _Ctx) -> Any:
        settings, problems = self.settings, []
        if settings is None:
            settings, problems = drawing_settings.load_settings(self.settings_path)
        loaded = document.read(ctx.path, limits=self.worker.limits)
        record: tuple[str, ...] = ()
        if loaded.drawing.status == release.RELEASED:
            folder = os.path.dirname(ctx.path)
            record = release.check_release_record(
                loaded.drawing,
                lambda name: document.file_sha256(
                    os.path.join(folder, name), self.worker.limits.output_bytes
                ),
            )
        return loaded, settings, tuple(problems), record

    def _opened(self, result: Any, ctx: _Ctx) -> None:
        loaded, settings, setting_problems, record = result
        self.settings = settings
        self._sha256 = loaded.sha256
        self.problems = tuple(loaded.problems) + tuple(f"settings: {p}" for p in setting_problems)
        self._show(loaded.drawing)
        said = [f"Opened {os.path.basename(self.path)}"]
        if record:
            said.append("; ".join(record))
        if loaded.problems:
            said.append(f"{len(loaded.problems)} value(s) of the file fell back to their defaults")
        self._say(". ".join(said))
        self._check_model()

    def _open_failed(self, error: BaseException, ctx: _Ctx) -> None:
        reason = getattr(error, "strerror", None) or str(error)
        self._set_model("missing")
        self._say(f"The drawing could not be opened: {reason}")

    def _check_model(self) -> None:
        """Attach the drawing's model from where the drawing is (13.6); say whether a
        changed model or none was found instead."""
        self._set_model("looking", self.model_path)
        self._submit(_Step("Looking for the model", self._model_work, self._model_done))

    def _model_work(self, ctx: _Ctx) -> Any:
        try:
            got = self._attach(ctx)  # the model chosen before, else from the drawing's path (13.6)
            path = ctx.model_path
            if path is None:  # where the child found it, for Save's model reference and Update
                found = locate.find_model(ctx.path, ctx.drawing.model or {}).found
                path = found.path if found is not None else None
            return "found", got, path
        except ModelNotFoundError:
            pass
        except InvalidArgumentError as exc:
            if (exc.detail or {}).get("rule") != "model_changed":
                raise
            return "changed", self.worker.checks(ctx.drawing), ctx.model_path
        lookup = locate.find_model(ctx.path, ctx.drawing.model or {})
        checks = self.worker.checks(ctx.drawing)
        if lookup.changed:
            return "changed", checks, lookup.changed[0].path
        return "missing", checks, None

    def _model_done(self, result: Any, ctx: _Ctx) -> None:
        how, got, path = result
        if how == "found":
            self._attached = True
            self._set_model("unchanged" if got.same_file else "geometry", path)
            self._show(replace(self.drawing, checks=tuple(got.checks)))
            return
        self._attached = False
        self._set_model(how, path)
        self._show(replace(self.drawing, checks=tuple(got)))
        self._say(VIEW_ONLY_CHANGED if how == "changed" else VIEW_ONLY)

    def _set_model(self, state: str, path: str | None = None) -> None:
        self.model_state = state
        if path is not None or state in ("missing",):
            self.model_path = path
        words = {
            "looking": MODEL_LOOKING,
            "unchanged": MODEL_UNCHANGED,
            "geometry": MODEL_CHANGED,
            "changed": MODEL_CHANGED,
            "missing": MODEL_NOT_FOUND,
        }[state]
        self.model_button.setText(words)
        self.model_button.setEnabled(state in ("geometry", "changed", "missing"))
        if self.model_path:
            self.model_button.setToolTip(self.model_path)
        self._update_title()
        self._update_actions()

    def _model_clicked(self) -> None:
        if self.model_state in ("geometry", "changed"):
            self.update_from_model()
        elif self.model_state == "missing":
            self.find_model()

    def find_model(self, path: str | os.PathLike | None = None) -> None:
        """Find...: attach the model from a file the user chooses. A file whose geometry
        has changed is taken by Update from Model, never here."""
        if self.drawing is None:
            return
        if path is None:
            path = self.ask_model_path(os.path.dirname(self.path))
            if not path:
                return
        chosen = os.path.abspath(os.fspath(path))

        def work(ctx: _Ctx) -> Any:
            ctx.model_path = chosen
            return self._attach(ctx)

        def done(got: Any, ctx: _Ctx) -> None:
            self._attached = True
            self._set_model("unchanged" if got.same_file else "geometry", chosen)
            self._show(replace(self.drawing, checks=tuple(got.checks)))
            self._say(f"The model is {os.path.basename(chosen)}")

        def failed(error: BaseException, ctx: _Ctx) -> None:
            if (
                isinstance(error, InvalidArgumentError)
                and (error.detail or {}).get("rule") == "model_changed"
            ):
                self._attached = False
                self._set_model("changed", chosen)
                self._say(
                    f"{os.path.basename(chosen)} has changed since the drawing was made: Update Drawing"
                )
                return
            self._failed(error, ctx, "The model could not be opened")

        self._submit(_Step("Opening the model", work, done, failed))

    def _idle_forget(self) -> None:
        """Let the child drop the model after the idle time (8.12)."""
        if self._closed or not self._attached or self.drawing is None:
            return
        if self.busy:
            self._idle.start(max(1, int(self.idle_ms)))
            return

        def work(ctx: _Ctx) -> None:
            self.worker.forget(ctx.drawing)

        def done(_result: Any, ctx: _Ctx) -> None:
            self._attached = False

        def failed(_error: BaseException, ctx: _Ctx) -> None:
            self._attached = False

        self._submit(_Step("", work, done, failed))

    # ------------------------------------------------------------------ showing a drawing
    def _show(self, drawing: Any) -> None:
        """Show ``drawing``: the sheet, the lists, the properties, the bar."""
        self.drawing = drawing
        if drawing.sheet is not None:
            try:
                self.scene.set_sheet(drawing.sheet)
            except InvalidArgumentError as exc:
                self._say(f"The sheet cannot be shown: {exc}")
        self._fill_dimensions()
        self._fill_checks()
        self.add_panel.fill()
        self.properties.show_selection()
        self._highlight_picked()
        status = drawing.status
        rev = document.current_revision(drawing) or "none"
        self.status_label.setText(f"{status}, revision {rev}")
        self._update_title()
        self._update_actions()
        self.changed.emit()

    def _set_current(self, drawing: Any) -> None:
        """A change that is not an edit (files written, saved): shown, outside Undo."""
        self._show(drawing)

    def _from_history(self, drawing: Any, remodel: bool) -> None:
        """Undo or Redo: the drawing as it was, keeping the records of the files written
        since (they are facts about the disk, not edits)."""
        if self.drawing is not None and drawing.outputs != self.drawing.outputs:
            drawing = replace(drawing, outputs=self.drawing.outputs)
        self._show(drawing)
        if remodel:  # an Update from Model undone or done again: which model is now the drawing's
            self._attached = False
            self._check_model()

    def _modified(self) -> bool:
        return self.drawing is not None and (self._unsaved or not self.undo_stack.isClean())

    def _update_title(self) -> None:
        name = os.path.basename(self.path)
        extra = ""
        if self.drawing is not None and self.drawing.status == release.RELEASED:
            extra = " (RELEASED, read-only)"
        elif self.model_state in ("changed", "missing"):
            extra = " (view-only)"
        self.setWindowTitle(f"{name}[*]{extra} - SolidSeas Drawing")
        self.setWindowModified(self._modified())

    @property
    def editable(self) -> bool:
        """Whether an edit may be asked now: a drawing that is not RELEASED, whose model
        is open or being looked for."""
        return (
            self.drawing is not None
            and self.drawing.status != release.RELEASED
            and self.model_state in _MODEL_OK
        )

    def _update_actions(self) -> None:
        a = getattr(self, "actions_by_name", None)
        if a is None:
            return
        have = self.drawing is not None
        idle = not self.busy
        released = have and self.drawing.status == release.RELEASED
        edit = self.editable
        for key in ("save", "save_as", "send", "pdf", "dxf", "email"):
            a[key].setEnabled(have)
        a["undo"].setEnabled(idle and self.undo_stack.canUndo())
        a["redo"].setEnabled(idle and self.undo_stack.canRedo())
        asm = have and is_assembly(self.drawing)
        for key in ("add", "remove", "reset", "sheet", "units", "block", "notes", "use_settings", "sign"):
            a[key].setEnabled(edit and not (asm and key in ASSEMBLY_OFF))
        for key in ASSEMBLY_OFF:  # an action without a tip of its own shows its text
            words = NO_DIMENSIONS if asm else ""
            a[key].setToolTip(words or a[key].text().replace("&", ""))
            a[key].setStatusTip(words)
        a["release"].setEnabled(edit)
        a["parts"].setEnabled(edit and asm)
        a["update"].setEnabled(  # a released drawing updates by starting its revision
            have
            and self.model_state in ("unchanged", "geometry", "changed")
            and (not released or self.model_state == "changed")
        )
        a["find"].setEnabled(have)
        a["revision"].setEnabled(released and self.model_state in (*_MODEL_OK, "changed"))
        self.properties.setEnabled(edit)

    # ------------------------------------------------------------------ the lists
    def _annotations(self) -> dict[str, Any]:
        sheet = self.drawing.sheet if self.drawing is not None else None
        return {a.id: a for a in getattr(sheet, "annotations", ()) or () if isinstance(a, D.Dimension)}

    def dimension(self, ident: str) -> Any:
        """The drawing's dimension record ``ident``, or None."""
        if self.drawing is None:
            return None
        return next((d for d in self.drawing.dimensions if d.id == ident), None)

    def _fill_dimensions(self) -> None:
        drawing = self.drawing
        names = view_names(drawing)
        annotations = self._annotations()
        self._filling = True
        try:
            self.dimensions.clear()
            groups: dict[str, QTreeWidgetItem] = {}
            order = {v: k for k, v in enumerate(names)}

            def number(d: Any) -> int:
                n = document.id_number(d.id, "d")
                return n if n is not None else 0

            for d in sorted(
                drawing.dimensions, key=lambda d: (order.get(d.view, len(order)), d.view, number(d))
            ):
                group = groups.get(d.view)
                if group is None:
                    group = QTreeWidgetItem([names.get(d.view, f"View {d.view}")])
                    group.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    groups[d.view] = group
                    self.dimensions.addTopLevelItem(group)
                text = dimension_text(drawing, d, annotations.get(d.id))
                item = QTreeWidgetItem(
                    [
                        f"{d.id}  {text}",
                        KIND_WORDS.get(d.kind, d.kind),
                        band_text(drawing, d),
                        ", ".join(badges(d)),
                    ]
                )
                item.setData(0, Qt.ItemDataRole.UserRole, d.id)
                item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable
                )
                item.setCheckState(
                    0, Qt.CheckState.Checked if d.state != "removed" else Qt.CheckState.Unchecked
                )
                if "needs_attention" in (getattr(d, "flags", ()) or ()):
                    for col in range(4):
                        item.setForeground(col, QColor("#e07b00"))
                group.addChild(item)
                if d.id == self._selected:
                    item.setSelected(True)
            self.dimensions.expandAll()
            for col in range(4):
                self.dimensions.resizeColumnToContents(col)
        finally:
            self._filling = False

    def _dimension_item(self, ident: str) -> QTreeWidgetItem | None:
        for i in range(self.dimensions.topLevelItemCount()):
            group = self.dimensions.topLevelItem(i)
            for k in range(group.childCount()):
                child = group.child(k)
                if child.data(0, Qt.ItemDataRole.UserRole) == ident:
                    return child
        return None

    def _dimension_ticked(self, item: QTreeWidgetItem, column: int) -> None:
        if self._filling or column != 0:
            return
        ident = item.data(0, Qt.ItemDataRole.UserRole)
        d = self.dimension(ident) if ident else None
        if d is None:
            return
        shown = item.checkState(0) == Qt.CheckState.Checked
        if shown and d.state == "removed":
            self.restore(ident)
        elif not shown and d.state != "removed":
            if d.origin == "user":
                self.delete(ident)
            else:
                self.remove(ident)

    def _dimension_chosen(self) -> None:
        if self._filling:
            return
        items = self.dimensions.selectedItems()
        ident = items[0].data(0, Qt.ItemDataRole.UserRole) if items else None
        if ident:
            self.select(ident)

    def _fill_checks(self) -> None:
        self.checks.clear()
        bold = QFont()
        bold.setBold(True)
        for c in self.drawing.checks or ():
            blocks = blocks_release(c)
            item = QTreeWidgetItem([c.level, c.code, "blocks release" if blocks else "", c.message])
            item.setData(0, Qt.ItemDataRole.UserRole, c)
            if blocks:
                for col in range(4):
                    item.setFont(col, bold)
            self.checks.addTopLevelItem(item)
        for col in range(3):
            self.checks.resizeColumnToContents(col)
        self._fill_fixes(None)

    def _check_chosen(self) -> None:
        items = self.checks.selectedItems()
        check = items[0].data(0, Qt.ItemDataRole.UserRole) if items else None
        self._fill_fixes(check)
        if check is not None:
            self.select_item(check.item)

    def _fill_fixes(self, check: Any) -> None:
        while self.fixes_layout.count():
            w = self.fixes_layout.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        if check is None:
            return
        for fix in check.fixes:
            button = QPushButton(fix)
            button.clicked.connect(lambda _c=False, f=fix, c=check: self.apply_fix(c, f))
            self.fixes_layout.addWidget(button)
        self.fixes_layout.addStretch(1)

    # ------------------------------------------------------------------ selection
    def _owners_of(self, ident: str) -> list[str]:
        """The sheet's owners drawn for a dimension or a note."""
        owners = [ident, f"{ident}-frame"]
        d = self.dimension(ident)
        if d is not None and d.kind == "datum_feature" and d.key.startswith("datum/"):
            owners.append("datum-" + d.key.split("/")[-1].upper())
        return [o for o in owners if self.scene.item(o) is not None]

    def _owner_thing(self, owner: str) -> str:
        """The dimension or note an owner of the sheet draws, or ""."""
        if not owner or self.drawing is None:
            return ""
        base = owner[: -len("-frame")] if owner.endswith("-frame") else owner
        if self.dimension(base) is not None:
            return base
        if owner.startswith("datum-"):
            key = "datum/" + owner[len("datum-") :].lower()
            d = next((d for d in self.drawing.dimensions if d.key == key), None)
            return d.id if d is not None else ""
        if any(nid == base for nid, _n in self.drawing.notes):
            return base
        return ""

    def select(self, ident: str) -> None:
        """Select a dimension or a note by id ("" for the title fields): on the sheet, in
        the list and in Properties."""
        self._selected = ident or ""
        self.scene.select(self._owners_of(ident) if ident else ())
        self._filling = True
        try:
            self.dimensions.clearSelection()
            item = self._dimension_item(ident) if ident else None
            if item is not None:
                item.setSelected(True)
                self.dimensions.scrollToItem(item)
        finally:
            self._filling = False
        self.properties.show_selection()

    @property
    def selected(self) -> str:
        return self._selected

    def select_item(self, item: str) -> None:
        """Select what a check is about: a dimension, a note, a feature's dimensions, or
        an owner of the sheet (a view, the title block)."""
        if not item or self.drawing is None:
            return
        if self.dimension(item) is not None or any(nid == item for nid, _n in self.drawing.notes):
            self.select(item)
            return
        owners = self.scene.owners_of_feature(item) if item.startswith("f-") else ()
        if not owners and self.scene.item(item) is not None:
            owners = (item,)
        self._selected = ""
        self.scene.select(owners)
        self.properties.show_selection()

    def _picked(self, owner: str, _modifiers: Any) -> None:
        if self.adding:
            fid = self._feature_of_owner(owner)
            if fid:
                self.pick_feature(fid)
            return
        self.select(self._owner_thing(owner))

    def _hovered(self, owner: str) -> None:
        if self.adding:
            self._highlight_picked(self._feature_of_owner(owner))

    def _dragged(self, owner: str, dx: float, dy: float) -> None:
        if owner.startswith("balloon-"):
            self.move_balloon_by(owner[len("balloon-") :], dx, dy)
            return
        d = self.dimension(owner)
        annotation = self._annotations().get(owner)
        if d is None or annotation is None:
            return
        if not self.editable:
            self._say(READ_ONLY if self.drawing.status == release.RELEASED else VIEW_ONLY)
            self._show(self.drawing)
            return
        if d.kind not in MOVABLE:
            self._say(f"{owner} stays where layout puts it: an {KIND_WORDS.get(d.kind, d.kind)} is not moved")
            self._show(self.drawing)
            return
        self.move_by(owner, dx, dy)

    def move_balloon_by(self, item: str, dx: float, dy: float) -> None:
        """Item ``item``'s balloon dropped ``(dx, dy)`` sheet millimetres (y up) from where
        it was drawn: ``edit.move_balloon``, its leader following, worked out from the
        drawing the step starts from."""
        if not self.editable:
            self._say(READ_ONLY if self.drawing.status == release.RELEASED else VIEW_ONLY)
            self._show(self.drawing)
            return

        def offset(drawing: Any) -> list:
            sheet = drawing.sheet
            drawn = next(
                (a for a in getattr(sheet, "annotations", ()) if isinstance(a, D.Balloon) and a.item == item),
                None,
            )
            if drawn is None or not drawn.leader:
                raise InvalidArgumentError(
                    f"balloon {item} is not on the sheet", detail={"parameter": "item"}
                )
            anchor = drawn.leader[0]
            ox, oy = drawn.centre[0] - anchor[0] + dx, drawn.centre[1] - anchor[1] + dy
            return [item, round(ox, 3), round(oy, 3)]

        self.edit("move_balloon", offset, f"Move balloon {item}")

    def move_by(self, ident: str, dx: float, dy: float) -> None:
        """A dimension dropped ``(dx, dy)`` sheet millimetres (y up) from where it was
        drawn: ``edit.move`` with its offsets added to those it had (:func:`placement_delta`),
        worked out from the drawing the step starts from, so two quick drags both count."""

        def offsets(drawing: Any) -> list:
            d = next((x for x in drawing.dimensions if x.id == ident), None)
            sheet = drawing.sheet
            drawn = next(
                (
                    a
                    for a in getattr(sheet, "annotations", ())
                    if isinstance(a, D.Dimension) and a.id == ident
                ),
                None,
            )
            if d is None or drawn is None:
                raise InvalidArgumentError(f"{ident} is not on the sheet", detail={"parameter": "id"})
            along, across = placement_delta(drawn, dx, dy)
            p = getattr(d, "placement", None)
            if p is not None and p.moved:
                along, across = along + p.along_mm, across + p.across_mm
            return [ident, round(along, 3), round(across, 3)]

        self.edit("move", offsets, f"Move {ident}")

    # ------------------------------------------------------------------ edits
    def edit(
        self, op: str, args: Any = (), words: str | None = None, *, then: Callable[[], None] | None = None
    ):
        """One operation of ``drawing.edit`` by name, through the worker, as an undoable
        step; ``words`` name it in Undo and the bar. ``args`` may be a function of the
        drawing the step starts from, called on the worker thread."""
        self.edits([(op, args)], words or op.replace("_", " ").capitalize(), then=then)

    def edits(
        self,
        ops: Sequence[tuple[str, Any]],
        words: str,
        *,
        then: Callable[[], None] | None = None,
        remodel: bool = False,
    ) -> None:
        """Several operations, each on the drawing the one before made, as one undoable
        step."""
        if self.drawing is None:
            return
        allowed = all(op == "start_revision" for op, _a in ops)
        if self.drawing.status == release.RELEASED and not allowed:
            self._say(READ_ONLY)
            return
        if self.model_state == "missing":
            self._say(VIEW_ONLY)
            return
        if self.model_state == "changed":
            self._say(VIEW_ONLY_CHANGED)
            return

        def work(ctx: _Ctx) -> Any:
            def run(drawing: Any) -> Any:
                got = drawing
                for op, args in ops:
                    if callable(args):  # worked out from the drawing as it is now
                        args = args(getattr(got, "drawing", got))
                    got = self.worker.edit(got, op, args)
                return got

            return self._with_model(ctx, run)

        def done(answer: Any, ctx: _Ctx) -> None:
            self._edited(answer, ctx.drawing, words, remodel=remodel)
            if then is not None:
                then()

        def failed(error: BaseException, ctx: _Ctx) -> None:
            self._failed(error, ctx, words)

        self._submit(_Step(words, work, done, failed))

    def _edited(self, answer: Any, before: Any, words: str, *, remodel: bool = False) -> None:
        after = answer.drawing
        if before is not None and after.outputs != before.outputs:
            after = replace(after, outputs=before.outputs)
        self.undo_stack.push(_Change(self, before, after, words, remodel=remodel))
        self._edit_log.append(words)
        said = [words]
        rows = {s.row for s in after.signatures}
        for s in before.signatures if before is not None else ():
            if s.row not in rows:
                said.append(f"the edit cleared the {s.row} signature of {s.name}")
        said.extend(answer.warnings[:3])
        self._say(". ".join(said))

    def undo(self) -> None:
        if self.busy:
            self._say("Wait for the drawing to finish what it is doing")
            return
        self.undo_stack.undo()

    def redo(self) -> None:
        if self.busy:
            self._say("Wait for the drawing to finish what it is doing")
            return
        self.undo_stack.redo()

    def remove(self, ident: str) -> None:
        self.edit("remove", [ident], f"Remove {ident}")

    def restore(self, ident: str) -> None:
        self.edit("restore", [ident], f"Restore {ident}")

    def delete(self, ident: str) -> None:
        self.edit("delete", [ident], f"Delete {ident}")

    def remove_selected(self) -> None:
        d = self.dimension(self._selected)
        if d is None:
            return
        if d.origin == "user":
            self.delete(d.id)
        elif d.state != "removed":
            self.remove(d.id)

    def move(self, ident: str, along_mm: float, across_mm: float) -> None:
        """Put a dimension ``along_mm`` and ``across_mm`` from its attach points."""
        self.edit("move", [ident, round(float(along_mm), 3), round(float(across_mm), 3)], f"Move {ident}")

    def reset_position(self, ident: str) -> None:
        if self.dimension(ident) is not None:
            self.edit("reset_position", [ident], f"Reset the position of {ident}")

    def flip(self, ident: str) -> None:
        self.edit("flip", [ident], f"Flip {ident}")

    def set_precision(self, ident: str, places: int | None) -> None:
        words = f"Precision of {ident} from its role" if places is None else f"Precision of {ident} {places}"
        self.edit("set_precision", [ident, places], words)

    def set_text(self, ident: str, prefix: str, suffix: Sequence[str]) -> None:
        """A dimension's prefix and suffix lines, kept apart from its value."""
        d = self.dimension(ident)
        if d is None:
            return
        ops: list[tuple[str, Any]] = []
        if prefix != d.prefix:
            ops.append(("set_prefix", [ident, prefix]))
        if tuple(suffix) != tuple(d.suffix):
            ops.append(("set_suffix", [ident, list(suffix)]))
        if ops:
            self.edits(ops, f"Text of {ident}")

    def reset_text(self, ident: str) -> None:
        self.edit("reset_text", [ident], f"Reset the text of {ident}")

    def override_value(self, ident: str, text: str | None) -> None:
        """Show ``text`` for a dimension's value (None or empty takes the override off)."""
        text = (text or "").strip() or None
        self.edit(
            "override_value", [ident, text], f"Override {ident}" if text else f"Reset the value of {ident}"
        )

    def set_tolerance(self, ident: str, kind: str, upper: float = 0.0, lower: float = 0.0) -> None:
        self.edit("set_tolerance", [ident, kind, float(upper), float(lower)], f"Tolerance of {ident}")

    def set_frame(self, ident: str, frame: FrameCell | None) -> None:
        self.edit(
            "set_frame", [ident, frame], f"Frame of {ident}" if frame else f"Remove the frame of {ident}"
        )

    def reset_frame(self, ident: str) -> None:
        self.edit("reset_frame", [ident], f"Reset the frame of {ident}")

    def set_note(self, note_id: str, text: str) -> None:
        """One note's text (an empty text deletes it)."""
        texts = [text if nid == note_id else n.text for nid, n in self.drawing.notes]
        self.edit("edit_notes", [texts], f"Note {note_id}")

    def set_title(self, values: Mapping[str, str | None]) -> None:
        """Title fields by key (:data:`TITLE_FIELDS`); None gives one back to the part."""
        current = {k: f.text for k, f in self.drawing.title}
        ops = [("set_title", [k, v]) for k, v in values.items() if (v or None) != (current.get(k) or None)]
        if ops:
            self.edits(ops, "Title block")

    # ------------------------------------------------------------------ Add Dimension
    def toggle_add_dimension(self, on: bool | None = None) -> None:
        """Add Dimension (D): pick one or two features, then one of their candidates."""
        on = not self.adding if on is None else bool(on)
        if on and not self.editable:
            self._say(
                READ_ONLY
                if self.drawing is not None and self.drawing.status == release.RELEASED
                else VIEW_ONLY
            )
            on = False
        self.adding = on
        self.add_dock.setVisible(on)
        self.actions_by_name["add"].setChecked(on)
        if not on:
            self.picked = []
            self.candidates = ()
            self.scene.highlight(())
        self.add_panel.fill()

    def _feature_of_owner(self, owner: str) -> str:
        """The feature a picked owner stands for: the feature a dimension locates or
        sizes (the last it names), or the feature carrying a datum letter."""
        ident = self._owner_thing(owner)
        d = self.dimension(ident) if ident else None
        if d is None or not d.features:
            return ""
        free = [f for f in reversed(d.features) if f not in self.picked]
        return free[0] if free else d.features[-1]

    def pick_feature(self, fid: str) -> None:
        """Pick a feature for Add Dimension (again to unpick it); a third drops the first."""
        if self.drawing is None or not any(f.id == fid for f in self.drawing.features):
            return
        if fid in self.picked:
            self.picked.remove(fid)
        else:
            self.picked.append(fid)
            del self.picked[:-2]
        self.candidates = ()
        self._highlight_picked()
        self.add_panel.fill()
        if self.picked:
            self.find_candidates(list(self.picked))

    def _highlight_picked(self, hovered: str = "") -> None:
        if not self.adding:
            return
        owners: list[str] = []
        for fid in [*self.picked, hovered]:
            if fid:
                owners.extend(self.scene.owners_of_feature(fid))
        self.scene.highlight(owners, PICKED_COLOUR)

    def find_candidates(self, features: Sequence[str]) -> None:
        """The planner's candidates for one or two features (``worker.candidates``)."""
        feats = list(features)

        def work(ctx: _Ctx) -> Any:
            return self._with_model(ctx, lambda d: self.worker.candidates(d, feats))

        def done(found: Any, ctx: _Ctx) -> None:
            if list(self.picked) == feats:
                self.candidates = tuple(found)
                self.add_panel.fill()
                if not found:
                    self._say("No dimension is offered for " + " and ".join(feats))

        self._submit(
            _Step("Finding candidates", work, done, lambda e, c: self._failed(e, c, "Add Dimension"))
        )

    def edit_parts_list(self) -> None:
        """Open the BOM editor (:mod:`.bomeditor`) on an assembly drawing's parts list:
        the model's BOMs from the drawing process (``worker.boms``), the drawing's own
        table definition if it has one; Apply makes it the parts list (``set_parts_list``)
        as one undoable step."""
        if self.drawing is None or not is_assembly(self.drawing):
            return

        def work(ctx: _Ctx) -> Any:
            return self._with_model(ctx, lambda d: self.worker.boms(d))

        def done(boms: Any, ctx: _Ctx) -> None:
            from solidseas.bomtable import spec
            from solidseas.drawing.types import parts_list_spec

            from .bomeditor import BomEditor

            text = self.drawing.options.parts_list if self.drawing is not None else None
            table = (
                parts_list_spec(text)
                if text
                else spec("top", ["item", "part_number", "drawing", "description", "quantity"])
            )
            model = self.drawing.model if self.drawing is not None else {}
            editor = BomEditor(
                boms,
                model.get("name") or "",
                self.drawing.options.configuration if self.drawing is not None else None,
                table_spec=table,
                apply_to_drawing=True,
                parent=self,
            )
            editor.setWindowFlag(Qt.WindowType.Window, True)
            editor.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            editor.applied.connect(lambda t: self.edit("set_parts_list", [t.to_json()], "Edit Parts List"))
            self.parts_editor = editor
            editor.show()

        self._submit(
            _Step("Reading the parts list", work, done, lambda e, c: self._failed(e, c, "Parts List"))
        )

    def add_candidate(self, candidate: Any) -> None:
        """Add one of :attr:`candidates`: restore a removed dimension or add a user one."""
        self.edit("add", [candidate], f"Add {candidate.words}", then=self._after_add)

    def _after_add(self) -> None:
        self.picked = []
        self.candidates = ()
        self.add_panel.fill()
        self._highlight_picked()

    # ------------------------------------------------------------------ checks and fixes
    def apply_fix(self, check: Any, fix: str) -> None:
        """Do what a check's fix says where the editor can: an edit, a command, or the
        thing selected for the user to change in Properties."""
        item = check.item
        d = self.dimension(item)
        self.select_item(item)
        if fix == "Lay Out Again":
            self.edit("relayout", [], "Lay out again")
        elif fix == "Restore":
            gone = [
                x.id
                for x in self.drawing.dimensions
                if x.state == "removed" and (item in x.features or x.id == item)
            ]
            if gone:
                self.edits([("restore", [g]) for g in gone], "Restore " + ", ".join(gone))
            else:
                self._say(f"Nothing about {item} is removed")
        elif fix == "Add":
            self.toggle_add_dimension(True)
            if item.startswith("f-") and item not in self.picked:
                self.pick_feature(item)
        elif fix in ("Sign...", "Sign Again"):
            self.sign()
        elif fix == "Edit Notes":
            self.edit_notes()
        elif fix == "Set Sheet":
            self.sheet_and_scale()
        elif fix in ("Drawing Settings", "Map the Material"):
            self.open_drawing_settings()
        elif fix in ("Accept with a Reason", "Accept as Typed"):
            self.release()
        elif d is not None and fix == "Reset Position":
            self.reset_position(d.id)
        elif d is not None and fix == "Reset the Text":
            self.reset_text(d.id)
        elif d is not None and fix == "Reset the Value":
            self.override_value(d.id, None)
        elif d is not None and fix == "Make Reference":
            self.set_tolerance(d.id, "reference")
        elif fix == "Confirm the End":
            fid = d.features[-1] if d is not None and d.features else item
            self.edit("confirm_end", [fid], f"Confirm the end of {fid}")
        elif fix == "Add Detail View":
            self._say(f"Add Detail View: {LATER}")
        elif fix == "Edit the Title Block":
            self.select("")
        else:
            self._say(f"{fix}: change {item or 'it'} in Properties")

    # ------------------------------------------------------------------ commands of the drawing
    def sheet_and_scale(self, sheet: str | None = None, scale: Any = None) -> None:
        """Sheet and Scale: the sheet size (``auto`` or A to E) and scale (``auto`` or
        (sheet, model)) for this drawing."""
        if not self._can_edit():
            return
        options = self.drawing.options
        if sheet is None and scale is None:
            dlg = _Form(self, "Sheet and Scale")
            dlg.add("sheet", "Sheet", _combo([(s, s) for s in SHEET_CHOICES], options.sheet))
            scales = [("auto", "auto")] + [(standards.scale_text(s), list(s)) for s in standards.SCALES]
            current = list(options.scale) if isinstance(options.scale, tuple) else options.scale
            dlg.add("scale", "Scale", _combo(scales, current))
            if not self.run_dialog(dlg):
                return
            sheet, scale = dlg.fields["sheet"].currentData(), dlg.fields["scale"].currentData()
        ops: list[tuple[str, Any]] = []
        if sheet is not None and sheet != options.sheet:
            ops.append(("set_sheet", [sheet]))
        if scale is not None:
            scale = list(scale) if isinstance(scale, (tuple, list)) else scale
            have = list(options.scale) if isinstance(options.scale, tuple) else options.scale
            if scale != have:
                ops.append(("set_scale", [scale]))
        if ops:
            self.edits(ops, "Sheet and scale")

    def set_units(self, units: str | None = None) -> None:
        """Units: inches or millimetres for this drawing."""
        if not self._can_edit():
            return
        if units is None:
            dlg = _Form(self, "Units")
            dlg.add(
                "units",
                "Units",
                _combo([("inches", "in"), ("millimetres", "mm")], self.drawing.options.units),
            )
            if not self.run_dialog(dlg):
                return
            units = dlg.fields["units"].currentData()
        if units != self.drawing.options.units:
            self.edit("set_units", [units], f"Units {units}")

    def tolerance_block(self, rows: Sequence[tuple[int, float]] | None = None) -> None:
        """Tolerance Block: the general block of the drawing's unit, rows of (decimals,
        plus and minus)."""
        if not self._can_edit():
            return
        unit = _unit(self.drawing)
        if rows is None:
            current = _snapshot(self.drawing).block(unit)
            dlg = _Form(
                self,
                "Tolerance Block",
                f"Your company's tolerances, in {'inches' if unit == 'in' else 'millimetres'}.",
            )
            table = QTableWidget(len(current) + 1, 2)
            table.setHorizontalHeaderLabels(["Decimals", "Plus and minus"])
            for k, row in enumerate(current):
                table.setItem(k, 0, QTableWidgetItem(str(row.places)))
                table.setItem(k, 1, QTableWidgetItem(f"{float(row.plus_minus):g}"))
            dlg.add("rows", "Rows", table)
            if not self.run_dialog(dlg):
                return
            rows = []
            for k in range(table.rowCount()):
                a, b = table.item(k, 0), table.item(k, 1)
                if a is None or b is None or not a.text().strip() or not b.text().strip():
                    continue
                try:
                    rows.append((int(a.text()), float(b.text())))
                except ValueError:
                    self._say(f"Tolerance Block: row {k + 1} is not a number of decimals and a tolerance")
                    return
        self.edit("set_tolerance_block", [[[int(p), float(v)] for p, v in rows]], "Tolerance block")

    def edit_notes(self, texts: Sequence[str] | None = None) -> None:
        """Notes: the drawing's notes in order, one a line."""
        if not self._can_edit():
            return
        if texts is None:
            dlg = _Form(self, "Notes", "One note a line, in order. An empty line is dropped.")
            box = QPlainTextEdit()
            box.setPlainText("\n".join(n.text for _nid, n in self.drawing.notes))
            dlg.add("notes", "Notes", box)
            if not self.run_dialog(dlg):
                return
            texts = box.toPlainText().split("\n")
        self.edit("edit_notes", [list(texts)], "Notes")

    def use_current_settings(self) -> None:
        """Use Current Drawing Settings: the drawing's snapshot replaced by them."""
        if self._can_edit() and self.settings is not None:
            self.edit("use_settings", {"settings": self.settings}, "Use current Drawing Settings")

    def open_drawing_settings(self) -> Any:
        """Drawing Settings: the dialog of ``drawingsettings``, saving to the editor's
        settings file; what it saves becomes the editor's current settings."""
        from .drawingsettings import DrawingSettingsDialog

        dlg = DrawingSettingsDialog(
            self, self.settings, path=self.settings_path, on_saved=self._settings_saved
        )
        self._settings_dialog = dlg
        dlg.show()
        return dlg

    def _settings_saved(self, settings: drawing_settings.DrawingSettings) -> None:
        self.settings = settings
        self._say("Drawing Settings saved: Use Current Drawing Settings puts them in this drawing")

    def _can_edit(self) -> bool:
        if self.drawing is None:
            return False
        if self.drawing.status == release.RELEASED:
            self._say(READ_ONLY)
            return False
        if self.model_state == "missing":
            self._say(VIEW_ONLY)
            return False
        if self.model_state == "changed":
            self._say(VIEW_ONLY_CHANGED)
            return False
        return True

    # ------------------------------------------------------------------ status: sign, release, revision
    def sign(self, row: str | None = None, person: str | None = None, *, today: Any = None) -> None:
        """Sign...: a row and a person from the People list (13.2)."""
        if not self._can_edit():
            return
        snapshot = _snapshot(self.drawing)
        people = [p["name"] for p in snapshot.people.people]
        if row is None or person is None:
            if not people:
                self.tell(
                    "Sign",
                    "Drawing Settings name nobody who signs drawings. Add the people in Drawing "
                    "Settings, then choose Use Current Drawing Settings.",
                )
                return
            signed = {s.row for s in self.drawing.signatures}
            rows = [r for r in snapshot.people.rows if r not in signed] or list(snapshot.people.rows)
            dlg = _Form(
                self,
                "Sign",
                "A signature records who approved the drawing and when; it is not a cryptographic signature.",
            )
            dlg.add("row", "Row", _combo([(r, r) for r in rows], row))
            dlg.add("person", "Person", _combo([(p, p) for p in people], person))
            if not self.run_dialog(dlg):
                return
            row, person = dlg.fields["row"].currentData(), dlg.fields["person"].currentData()
        self.edit("sign", [row, person, today], f"Sign {row} as {person}")

    def release(self, accepted: Mapping[str, str] | None = None, *, today: Any = None) -> None:
        """Release...: with typed reasons for the checks that may be accepted and for a
        material the list does not map; the refused reasons shown. The released PDF and
        DXF are then written as new files beside the drawing, and the drawing saved."""
        if not self._can_edit():
            return
        if accepted is None:
            dlg = self._release_dialog()
            if not self.run_dialog(dlg):
                return
            accepted = {k: w.text().strip() for k, w in dlg.fields.items() if w.text().strip()}
        folder = os.path.dirname(self.path)
        problem = document.folder_problem(folder)
        if problem is not None:
            self._say(f"Release: the drawing's folder is refused ({problem})")
            self.tell(
                "Release",
                f"The released files cannot be written beside the drawing: {problem}. "
                "Save the drawing in another folder first.",
            )
            return
        policy = self._files_policy()
        accepted = dict(accepted)

        def work(ctx: _Ctx) -> Any:
            answer = self._with_model(ctx, lambda d: self.worker.release(d, accepted, today))
            released = answer.drawing
            written = []
            for kind in ("pdf", "dxf"):
                data = self.worker.export(released, kind).data
                target = document.export_target(self._policy(released, policy), folder, kind)
                saved = document.write_output(
                    target.path, lambda fh, b=data: fh.write(b), replaces=target.replaces
                )
                released = document.record_output(released, kind, os.path.basename(saved.path), saved.sha256)
                written.append(saved.path)
            target = document.save_target(self._policy(released, policy), ctx.path, loaded_sha256=ctx.sha256)
            saved = document.save(released, target.path, replaces=target.replaces)
            return saved, target, written

        def done(result: Any, ctx: _Ctx) -> None:
            saved, target, written = result
            self.release_reasons = ()
            self.undo_stack.clear()
            self._edit_log.clear()
            self._reports.clear()
            self.path, self._sha256 = saved.path, saved.sha256
            self._unsaved = False
            self._show(saved.drawing)
            self.undo_stack.setClean()
            rev = document.current_revision(saved.drawing)
            said = [
                f"Released revision {rev}: " + ", ".join(os.path.basename(p) for p in written) + " written"
            ]
            if target.words:
                said.append(target.words)
            self._say(". ".join(said))

        def failed(error: BaseException, ctx: _Ctx) -> None:
            reasons = getattr(error, "reasons", None)
            if isinstance(error, release.ReleaseRefusedError) and reasons is not None:
                self.release_reasons = tuple(reasons)
                self._say("Release refused: " + "; ".join(self.release_reasons))
                self.tell(
                    "Release refused", "The drawing cannot be released:\n" + "\n".join(self.release_reasons)
                )
                return
            self._failed(error, ctx, "Release")

        self._submit(_Step("Releasing", work, done, failed))

    def _release_dialog(self) -> _Form:
        drawing = self.drawing
        problems = release.release_problems(drawing)
        note = "Release needs every required row signed and no error but those accepted with a typed reason."
        if problems:
            note += "\n\nAs the drawing is now:\n" + "\n".join(problems)
        dlg = _Form(self, "Release", note)
        seen = set()
        for c in drawing.checks or ():
            if c.level == "error" and c.code in release.ACCEPTABLE:
                key = c.item or c.code
                if key in seen:
                    continue
                seen.add(key)
                dlg.add(key, f"{c.code}: {c.message}. Reason for accepting", QLineEdit())
        if material_needs_reason(drawing):
            material = document.title_text(drawing, "material")
            dlg.add(
                release.MATERIAL_ITEM,
                f"Material {material!r} is not in the list. Reason for accepting it as typed",
                QLineEdit(),
            )
        return dlg

    def start_revision(
        self, description: str | None = None, *, drawn_by: str | None = None, today: Any = None
    ) -> None:
        """Start Revision: the next revision of a RELEASED drawing, its row described
        (pre-filled from the edit log and the merge reports, editable)."""
        if self.drawing is None:
            return
        if self.drawing.status != release.RELEASED:
            self._say(
                "Only a released drawing starts a revision; before the first release it is edited freely"
            )
            return
        before = [s.name for s in self.drawing.signatures if s.row == release.DRAWN]
        if drawn_by is None and before:
            drawn_by = before[0]
        if description is None:
            dlg = _Form(self, "Start Revision", "The new revision's row in the revision block.")
            text = dlg.add("description", "Description", QLineEdit(self.revision_description()))
            people = [p["name"] for p in _snapshot(self.drawing).people.people]
            names = list(dict.fromkeys([*([drawn_by] if drawn_by else []), *people]))
            dlg.add("drawn_by", "Drawn by", _combo([(n, n) for n in names], drawn_by))
            if not self.run_dialog(dlg):
                return
            description = text.text().strip()
            drawn_by = dlg.fields["drawn_by"].currentData() or drawn_by
        if not description or not description.strip():
            self._say("A revision needs a description")
            return
        args = {"description": description.strip(), "zones": [], "drawn_by": drawn_by, "today": today}

        def opened() -> None:
            self._edit_log.clear()
            self._reports.clear()

        if self.model_state == "changed":
            # the model changed since the release: the revision starts and takes the new
            # model in one step, so its sheet is laid out (and stamped) with it
            self.update_from_model(revision=args["description"], drawn_by=drawn_by, today=today)
            return
        self.edit("start_revision", args, "Start revision", then=opened)

    def revision_description(self) -> str:
        """What Start Revision's description is pre-filled with: the merge reports' and
        the edits' words since the last revision, upper case; for a released drawing,
        whose edits went into the release, what the model says has changed."""
        words = [*self._reports, *(w.upper() for w in self._edit_log)]
        text = "; ".join(dict.fromkeys(w for w in words if w))
        if not text and self.model_state == "geometry":
            text = "MODEL REFERENCE UPDATED, GEOMETRY UNCHANGED"
        elif not text and self.model_state == "changed":
            text = "UPDATED FROM MODEL"
        return text[:200]

    # ------------------------------------------------------------------ Update from Model
    def update_from_model(
        self, revision: str | None = None, *, drawn_by: str | None = None, today: Any = None
    ) -> None:
        """Update from Model (13.5): the model merged into the drawing, the user's edits
        kept, the report shown. A released drawing whose model changed starts its next
        revision in the same step (``revision``, its description, asked for through
        Start Revision when not given)."""
        if self.drawing is None:
            return
        if self.drawing.status == release.RELEASED and revision is None:
            if self.model_state == "changed":
                self.start_revision(drawn_by=drawn_by, today=today)
            else:
                self._say("A released drawing must Start Revision before Update from Model")
            return

        def work(ctx: _Ctx) -> Any:
            part = ctx.model_path
            if not part:
                # The model where the drawing says it is (13.6): the user asked for the update,
                # so a file that changed since the drawing was made is the one taken.
                lookup = locate.find_model(ctx.path, ctx.drawing.model or {})
                found = lookup.found or (lookup.changed[0] if lookup.changed else None)
                if found is None:
                    raise ModelNotFoundError(
                        "the drawing's model was not found: Find... the model first",
                        detail={"parameter": "source", "rule": "model_not_found"},
                    )
                part = found.path
            answer = self.worker.regenerate(
                ctx.drawing, part=part, revision=revision, drawn_by=drawn_by, today=today
            )
            ctx.attached = True
            return answer, part

        def done(result: Any, ctx: _Ctx) -> None:
            answer, part = result
            report = answer.merge
            self.last_report = report
            self._set_model("unchanged", part)
            if revision is not None:  # the revision started: its edits and reports start afresh
                self._edit_log.clear()
                self._reports.clear()
            if (report is None or report.model_unchanged) and revision is None:
                self._say(report.words() if report is not None else MODEL_UNCHANGED)
                return
            self.undo_stack.push(
                _Change(self, ctx.drawing, answer.drawing, "Update from Model", remodel=True)
            )
            if report.description():
                self._reports.append(report.description())
            self._say(f"Updated from the model: {report.words()}")
            self.tell("Update from Model", report_text(report))

        def failed(error: BaseException, ctx: _Ctx) -> None:
            self._failed(error, ctx, "Update from Model")

        self._submit(_Step("Updating from the model", work, done, failed))

    # ------------------------------------------------------------------ files
    def _files_policy(self) -> tuple[bool, bool] | None:
        """The two switches of 12.6 from the current Drawing Settings, or None to keep the
        drawing's own."""
        if self.settings is None:
            return None
        files = self.settings.files
        return files.replace_own_files, files.keep_preliminary_current

    @staticmethod
    def _policy(drawing: Any, policy: tuple[bool, bool] | None) -> Any:
        """``drawing`` with the switches of :meth:`_files_policy`, for ``save_target`` and
        ``export_target``, which read them from the drawing's settings."""
        s = drawing.settings
        if policy is None or not isinstance(s, drawing_settings.DrawingSettings):
            return drawing
        own, keep = policy
        if (s.files.replace_own_files, s.files.keep_preliminary_current) == (own, keep):
            return drawing
        files = replace(s.files, replace_own_files=own, keep_preliminary_current=keep)
        return replace(drawing, settings=replace(s, files=files))

    def _with_model_reference(self, drawing: Any, model_path: str | None, target: str) -> Any:
        if model_path:
            return locate.with_model_path(drawing, model_path, target)
        return drawing

    def save(self) -> None:
        """Save (12.6): this drawing's own unchanged file is replaced; any other file
        there gets a new name, and the editor carries on with that file."""
        if self.drawing is None:
            return
        problem = document.folder_problem(os.path.dirname(self.path))
        if problem is not None:
            self._say(f"The drawing cannot be saved in its folder: {problem}")
            self.save_as(reason=problem)
            return
        self._save_to(self.path, same=True)

    def save_as(self, path: str | os.PathLike | None = None, *, reason: str | None = None) -> None:
        """Save As: the drawing to a file the user names, in a folder 12.6 allows."""
        if self.drawing is None:
            return
        asked = path is None
        for _try in range(20):
            if path is None:
                title = "Save Drawing As" + (f" ({reason})" if reason else "")
                start = os.path.join(os.path.dirname(self.path), document.drawing_file_name(self.drawing))
                path = self.ask_save_path(title, start)
                if not path:
                    return
            target = os.path.abspath(os.fspath(path))
            if not target.lower().endswith(document.EXTENSION):
                target += document.EXTENSION
            problem = document.folder_problem(os.path.dirname(target))
            if problem is None:
                self._save_to(target, same=os.path.normcase(target) == os.path.normcase(self.path))
                return
            self._say(f"The drawing cannot be saved there: {problem}")
            if not asked:
                return
            path, reason = None, problem

    def _save_to(self, path: str, *, same: bool) -> None:
        policy = self._files_policy()
        folder = os.path.dirname(path)

        def work(ctx: _Ctx) -> Any:
            drawing = self._with_model_reference(ctx.drawing, ctx.model_path, path)
            drawing, refreshed = self._refresh_exports(drawing, folder, policy)
            target = document.save_target(
                self._policy(drawing, policy), path, loaded_sha256=ctx.sha256 if same else None
            )
            saved = document.save(drawing, target.path, replaces=target.replaces)
            return saved, target, refreshed

        def done(result: Any, ctx: _Ctx) -> None:
            saved, target, refreshed = result
            self.path, self._sha256 = saved.path, saved.sha256
            self._unsaved = False
            self._set_current(saved.drawing)
            self.undo_stack.setClean()
            said = [target.words or f"Saved {os.path.basename(saved.path)}"]
            said += [f"{os.path.basename(p)} kept up to date" for p in refreshed]
            self._say(". ".join(said))
            if self._close_after_save:
                self._close_after_save = False
                self.close()

        def failed(error: BaseException, ctx: _Ctx) -> None:
            self._close_after_save = False
            self._failed(error, ctx, "Save")

        self._submit(_Step("Saving", work, done, failed))

    def _refresh_exports(
        self, drawing: Any, folder: str, policy: tuple[bool, bool] | None
    ) -> tuple[Any, list[str]]:
        """Save's "keep preliminary exports up to date" (12.6): each PRELIMINARY export
        ``outputs`` lists under its current name, rewritten when it is this drawing's own
        unchanged file. In the worker thread."""
        files = self._policy(drawing, policy).settings
        files = (
            files.files if isinstance(files, drawing_settings.DrawingSettings) else drawing_settings.Files()
        )
        if drawing.status == release.RELEASED or not (
            files.replace_own_files and files.keep_preliminary_current
        ):
            return drawing, []
        rev = document.current_revision(drawing)
        refreshed = []
        for kind in ("pdf", "dxf"):
            name = document.export_name(drawing, kind)
            listed = any(
                o.kind == kind and o.name == name and not o.released and o.revision == rev
                for o in drawing.outputs
            )
            if not listed or not os.path.lexists(os.path.join(folder, name)):
                continue
            target = document.export_target(self._policy(drawing, policy), folder, kind)
            if target.replaces is None:
                continue  # not this drawing's own unchanged file: left as it is
            data = self.worker.export(drawing, kind).data
            saved = document.write_output(
                target.path, lambda fh, b=data: fh.write(b), replaces=target.replaces
            )
            drawing = document.record_output(drawing, kind, os.path.basename(saved.path), saved.sha256)
            refreshed.append(saved.path)
        return drawing, refreshed

    def save_copy_to_send(self, path: str | os.PathLike | None = None) -> None:
        """Save a Copy to Send: a new file of the drawing without the model's absolute
        path (13.1, 18); a drawing that is not RELEASED asks first (13.2)."""
        if self.drawing is None:
            return
        question = mail.preliminary_question(self.drawing.status)
        if question is not None and not self.ask_question(question):
            return
        if path is None:
            stem = document.drawing_file_name(self.drawing)[: -len(document.EXTENSION)]
            path = self.ask_save_path(
                "Save a Copy to Send", os.path.join(os.path.dirname(self.path), f"{stem} to send.ssdrw")
            )
            if not path:
                return
        target = os.path.abspath(os.fspath(path))
        if not target.lower().endswith(document.EXTENSION):
            target += document.EXTENSION
        problem = document.folder_problem(os.path.dirname(target))
        if problem is not None:
            self._say(f"The copy cannot be saved there: {problem}")
            return

        def work(ctx: _Ctx) -> Any:
            drawing = locate.for_sending(self._with_model_reference(ctx.drawing, ctx.model_path, target))
            where = target
            if os.path.lexists(where):  # a copy never replaces anything
                folder, base = os.path.split(where)
                where = document.next_free_name(folder, base[: -len(document.EXTENSION)], document.EXTENSION)
            return document.save(drawing, where)

        def done(saved: Any, ctx: _Ctx) -> None:
            self._say(
                f"A copy to send was saved as {os.path.basename(saved.path)}; "
                "it names no folder of this computer"
            )

        self._submit(
            _Step("Saving a copy to send", work, done, lambda e, c: self._failed(e, c, "Save a Copy to Send"))
        )

    def export_pdf(self, folder: str | os.PathLike | None = None) -> None:
        """Export PDF...: into a folder the user chooses (the drawing's by default)."""
        self._export("pdf", folder)

    def export_dxf(self, folder: str | os.PathLike | None = None) -> None:
        """Export DXF...: as Export PDF..."""
        self._export("dxf", folder)

    def _export(self, kind: str, folder: Any = None, then: Callable[[str], None] | None = None) -> None:
        if self.drawing is None:
            return
        asked = folder is None
        reason = None
        for _try in range(20):
            if folder is None:
                title = f"Export {_KINDS[kind]} to" + (f" ({reason})" if reason else "")
                folder = self.ask_folder(title, os.path.dirname(self.path))
                if not folder:
                    return
            folder = os.path.abspath(os.fspath(folder))
            reason = document.folder_problem(folder)
            if reason is None:
                break
            self._say(f"The {_KINDS[kind]} cannot be written there: {reason}")
            if not asked:
                return
            folder = None
        else:
            return
        policy = self._files_policy()
        where = folder

        def work(ctx: _Ctx) -> Any:
            data = self.worker.export(ctx.drawing, kind).data
            target = document.export_target(self._policy(ctx.drawing, policy), where, kind)
            saved = document.write_output(target.path, lambda fh: fh.write(data), replaces=target.replaces)
            recorded = document.record_output(ctx.drawing, kind, os.path.basename(saved.path), saved.sha256)
            return recorded, saved, target

        def done(result: Any, ctx: _Ctx) -> None:
            recorded, saved, target = result
            self._unsaved = True
            self._set_current(recorded)
            self._say(target.words or f"Exported {os.path.basename(saved.path)}")
            if then is not None:
                then(saved.path)

        self._submit(
            _Step(
                f"Exporting the {_KINDS[kind]}",
                work,
                done,
                lambda e, c: self._failed(e, c, f"Export {_KINDS[kind]}"),
            )
        )

    def email_pdf(self) -> None:
        """Email PDF (15.5): the released PDF, or the stamped preliminary one made current
        after the PRELIMINARY question; then the route Drawing Settings choose."""
        if self.drawing is None:
            return
        question = mail.preliminary_question(self.drawing.status)
        if question is not None and not self.ask_question(question):
            return
        if self.drawing.status != release.RELEASED:
            self._export("pdf", os.path.dirname(self.path), then=self._email)
            return
        rev = document.current_revision(self.drawing)
        released = [o for o in self.drawing.outputs if o.kind == "pdf" and o.released and o.revision == rev]
        if not released:
            self._say("The released PDF is not recorded in the drawing: export the PDF first")
            return
        pdf = os.path.join(os.path.dirname(self.path), released[-1].name)
        want = released[-1].sha256

        def work(ctx: _Ctx) -> Any:
            return document.file_sha256(pdf, self.worker.limits.output_bytes)

        def done(found: Any, ctx: _Ctx) -> None:
            if found != want:
                self._say(f"{os.path.basename(pdf)} is not the PDF that was released, or is not there")
                return
            self._email(pdf)

        self._submit(_Step("Finding the released PDF", work, done))

    def _email(self, pdf: str) -> None:
        settings = self.settings if self.settings is not None else _snapshot(self.drawing)
        number = document.title_text(self.drawing, "number") or document.title_text(
            self.drawing, "part_number"
        )
        title = document.title_text(self.drawing, "title")
        route = mail.choose_route(settings.email.method)
        if route.kind == mail.ATTACH:

            def work(ctx: _Ctx) -> Any:
                subject = mail.subject_text(number, title) if settings.email.prefill_subject else ""
                return mail.attach_pdf(pdf, os.path.basename(pdf), subject)

            def done(result: Any, ctx: _Ctx) -> None:
                self._deliver(pdf, number, title, settings, route, result)

            self._submit(_Step("Attaching the PDF", work, done, lambda e, c: self._failed(e, c, "Email PDF")))
            return
        self._deliver(pdf, number, title, settings, route, None)

    def _deliver(self, pdf: str, number: str, title: str, settings: Any, route: Any, attached: Any) -> None:
        try:
            delivery = mail.email_pdf(pdf, number, title, settings, route=route, attached=attached)
        except (OSError, SolidSeasError) as exc:
            self._say(f"Email PDF: {getattr(exc, 'strerror', None) or exc}")
            return
        self.last_delivery = delivery
        if delivery.status:
            self._say(delivery.status)

    def showEvent(self, event: Any) -> None:  # noqa: N802 (Qt's name)
        super().showEvent(event)
        if not self._sized:  # the docks' first sizes, once the window has its own
            self._sized = True
            self.resizeDocks(
                [self.dimensions_dock, self.properties_dock], [340, 380], Qt.Orientation.Horizontal
            )
            self.resizeDocks([self.checks_dock], [170], Qt.Orientation.Vertical)

    # ------------------------------------------------------------------ closing
    def closeEvent(self, event: Any) -> None:  # noqa: N802 (Qt's name)
        if not self._closed and self._modified():
            answer = self.ask_close()
            if answer == "cancel":
                event.ignore()
                return
            if answer == "save":
                self._close_after_save = True
                self.save()
                event.ignore()
                return
        self._shut()
        event.accept()

    def _shut(self) -> None:
        """Stop, and let the child drop the model, without waiting for it."""
        if self._closed:
            return
        self._closed = True
        self._idle.stop()
        self._queue.clear()
        if self._settings_dialog is not None:
            self._settings_dialog.close()
        drawing, worker = self.drawing, self.worker
        if drawing is not None and self._attached:

            def forget() -> None:
                try:
                    worker.forget(drawing)
                except Exception:  # the child may be gone with the viewer; nothing to keep
                    pass

            threading.Thread(target=forget, name="SolidSeas drawing forget", daemon=True).start()


# --------------------------------------------------------------------------- Properties
class _Properties(QWidget):
    """The right-hand panel: what is selected (see the module notes)."""

    def __init__(self, editor: DrawingEditor) -> None:
        super().__init__()
        self.editor = editor
        self.pages = QStackedWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.heading = _plain("")
        bold = self.heading.font()
        bold.setBold(True)
        self.heading.setFont(bold)
        layout.addWidget(self.heading)
        layout.addWidget(self.pages)
        layout.addStretch(1)
        self.pages.addWidget(self._dimension_page())
        self.pages.addWidget(self._note_page())
        self.pages.addWidget(self._title_page())

    # -- the pages
    def _dimension_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.measured = QLineEdit()
        self.measured.setReadOnly(True)
        form.addRow(_plain("Measured value"), self.measured)
        self.precision = _combo([("From its role", None)] + [(str(n), n) for n in range(5)])
        self.precision.activated.connect(self._precision_chosen)
        form.addRow(_plain("Precision (decimals)"), self.precision)
        self.band = _plain("")
        form.addRow(_plain("Band"), self.band)
        self.prefix = QLineEdit()
        self.prefix.setMaxLength(32)
        form.addRow(_plain("Prefix"), self.prefix)
        self.suffix = QPlainTextEdit()
        self.suffix.setMaximumHeight(70)
        form.addRow(_plain("Suffix lines"), self.suffix)
        text_buttons = QHBoxLayout()
        apply_text = QPushButton("Apply Text")
        apply_text.clicked.connect(self._apply_text)
        reset_text = QPushButton("Reset Text")
        reset_text.clicked.connect(lambda: self.editor.reset_text(self.editor.selected))
        text_buttons.addWidget(apply_text)
        text_buttons.addWidget(reset_text)
        form.addRow(text_buttons)

        override = QGroupBox("Value override")
        o = QVBoxLayout(override)
        self.override = QLineEdit()
        self.override.setMaxLength(64)
        self.override.setPlaceholderText("the model's value")
        o.addWidget(self.override)
        warning = _plain(OVERRIDE_WARNING)
        warning.setStyleSheet("color: #b45f06")
        o.addWidget(warning)
        apply_override = QPushButton("Apply Override")
        apply_override.clicked.connect(
            lambda: self.editor.override_value(self.editor.selected, self.override.text())
        )
        o.addWidget(apply_override)
        form.addRow(override)

        tolerance = QGroupBox("Tolerance")
        t = QFormLayout(tolerance)
        self.tolerance = _combo([(words, kind) for kind, words in TOLERANCE_WORDS])
        t.addRow(_plain("Kind"), self.tolerance)
        self.upper, self.lower = QDoubleSpinBox(), QDoubleSpinBox()
        for box in (self.upper, self.lower):
            box.setDecimals(4)
            box.setRange(-1000.0, 1000.0)
            box.setSingleStep(0.001)
        t.addRow(_plain("Upper (or plus and minus)"), self.upper)
        t.addRow(_plain("Lower"), self.lower)
        apply_tolerance = QPushButton("Apply Tolerance")
        apply_tolerance.clicked.connect(self._apply_tolerance)
        t.addRow(apply_tolerance)
        form.addRow(tolerance)

        frame = QGroupBox("Feature control frame")
        f = QFormLayout(frame)
        self.characteristic = _combo(
            [("none", None)] + [(c.name, key) for key, c in standards.CHARACTERISTICS.items()]
        )
        f.addRow(_plain("Characteristic"), self.characteristic)
        self.zone = QDoubleSpinBox()
        self.zone.setDecimals(4)
        self.zone.setRange(0.0, 1000.0)
        self.zone.setSingleStep(0.001)
        f.addRow(_plain("Zone"), self.zone)
        self.diameter = QCheckBox("Ø zone")
        f.addRow(self.diameter)
        self.modifier = _combo([("none", None), ("MMC", "mmc"), ("LMC", "lmc")])
        f.addRow(_plain("Modifier"), self.modifier)
        self.datums = [QComboBox() for _k in range(3)]
        row = QHBoxLayout()
        for box in self.datums:
            row.addWidget(box)
        f.addRow(_plain("Datums"), row)
        frame_buttons = QHBoxLayout()
        for text, slot in (
            ("Apply Frame", self._apply_frame),
            ("Remove Frame", lambda: self.editor.set_frame(self.editor.selected, None)),
            ("Reset Frame", lambda: self.editor.reset_frame(self.editor.selected)),
        ):
            button = QPushButton(text)
            button.clicked.connect(lambda _c=False, s=slot: s())
            frame_buttons.addWidget(button)
        f.addRow(frame_buttons)
        form.addRow(frame)

        place = QHBoxLayout()
        reset = QPushButton("Reset Position")
        reset.clicked.connect(lambda: self.editor.reset_position(self.editor.selected))
        flip = QPushButton("Flip")
        flip.clicked.connect(lambda: self.editor.flip(self.editor.selected))
        place.addWidget(reset)
        place.addWidget(flip)
        form.addRow(place)
        return page

    def _note_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.note = QPlainTextEdit()
        form.addRow(_plain("Text"), self.note)
        apply_note = QPushButton("Apply Note")
        apply_note.clicked.connect(
            lambda: self.editor.set_note(self.editor.selected, self.note.toPlainText().replace("\n", " "))
        )
        form.addRow(apply_note)
        return page

    def _title_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.title_fields: dict[str, QLineEdit] = {}
        for key, label in TITLE_FIELDS:
            box = QLineEdit()
            self.title_fields[key] = box
            form.addRow(_plain(label), box)
        apply_title = QPushButton("Apply Title Block")
        apply_title.clicked.connect(self._apply_title)
        form.addRow(apply_title)
        return page

    # -- showing what is selected
    def show_selection(self) -> None:
        editor = self.editor
        drawing = editor.drawing
        if drawing is None:
            return
        ident = editor.selected
        d = editor.dimension(ident) if ident else None
        if d is not None:
            self._show_dimension(drawing, d)
            return
        note = next((n for nid, n in drawing.notes if nid == ident), None) if ident else None
        if note is not None:
            self.heading.setText(f"Note {ident}")
            self.note.setPlainText(note.text)
            self.pages.setCurrentIndex(1)
            return
        self.heading.setText("Title block")
        values = {k: f.text for k, f in drawing.title}
        for key, box in self.title_fields.items():
            box.setText(values.get(key, ""))
        self.pages.setCurrentIndex(2)

    def _show_dimension(self, drawing: Any, d: Any) -> None:
        unit = _unit(drawing)
        self.heading.setText(f"Dimension {d.id}, {KIND_WORDS.get(d.kind, d.kind)} ({d.key})")
        self.measured.setText(measured_text(drawing, d))
        self.precision.setCurrentIndex(
            self.precision.findData(d.places if d.places_source == "user" else None)
        )
        self.precision.setItemText(
            0, "From its role" if d.places_source == "user" else f"From its role ({d.places})"
        )
        self.band.setText(band_text(drawing, d))
        self.prefix.setText(d.prefix)
        self.suffix.setPlainText("\n".join(d.suffix))
        self.override.setText(getattr(d, "override", None) or "")
        index = self.tolerance.findData(d.tolerance)
        self.tolerance.setCurrentIndex(index if index >= 0 else 0)
        self.upper.setValue(float(d.tolerance_values[0]))
        self.lower.setValue(float(d.tolerance_values[1]))
        letters = [""] + [x.letter for x in drawing.datums]
        frame = d.frame
        for k, box in enumerate(self.datums):
            box.clear()
            for letter in letters:
                box.addItem(letter or "none", letter or None)
            want = frame.datums[k] if frame is not None and k < len(frame.datums) else None
            box.setCurrentIndex(max(0, box.findData(want)))
        if frame is not None:
            self.characteristic.setCurrentIndex(max(0, self.characteristic.findData(frame.characteristic)))
            self.zone.setValue(dnumbers.in_unit(frame.value, unit))
            self.diameter.setChecked(bool(frame.diameter))
            self.modifier.setCurrentIndex(max(0, self.modifier.findData(frame.modifier)))
        else:
            self.characteristic.setCurrentIndex(0)
            self.zone.setValue(0.0)
            self.diameter.setChecked(False)
            self.modifier.setCurrentIndex(0)
        self.pages.setCurrentIndex(0)

    # -- applying
    def _precision_chosen(self, _index: int) -> None:
        d = self.editor.dimension(self.editor.selected)
        if d is None:
            return
        places = self.precision.currentData()
        now = d.places if d.places_source == "user" else None
        if places != now:
            self.editor.set_precision(d.id, places)

    def _apply_text(self) -> None:
        lines = [x.strip() for x in self.suffix.toPlainText().split("\n") if x.strip()]
        self.editor.set_text(self.editor.selected, self.prefix.text().strip(), lines)

    def _apply_tolerance(self) -> None:
        kind = self.tolerance.currentData()
        self.editor.set_tolerance(self.editor.selected, kind, self.upper.value(), self.lower.value())

    def _apply_frame(self) -> None:
        characteristic = self.characteristic.currentData()
        if characteristic is None:
            self.editor.set_frame(self.editor.selected, None)
            return
        unit = _unit(self.editor.drawing)
        datums = tuple(b.currentData() for b in self.datums if b.currentData())
        frame = FrameCell(
            characteristic,
            dnumbers.from_unit(self.zone.value(), unit),
            self.diameter.isChecked(),
            self.modifier.currentData(),
            datums,
        )
        self.editor.set_frame(self.editor.selected, frame)

    def _apply_title(self) -> None:
        self.editor.set_title({k: (box.text().strip() or None) for k, box in self.title_fields.items()})


# --------------------------------------------------------------------------- Add Dimension
class _AddDimension(QWidget):
    """Add Dimension's panel: the features (picked on the sheet or ticked here) and the
    planner's candidates."""

    def __init__(self, editor: DrawingEditor) -> None:
        super().__init__()
        self.editor = editor
        layout = QVBoxLayout(self)
        layout.addWidget(_plain("Pick one or two features on the sheet, or tick them here."))
        self.features = QListWidget()
        self.features.itemChanged.connect(self._ticked)
        layout.addWidget(self.features, 1)
        layout.addWidget(_plain("Candidates"))
        self.offered = QListWidget()
        self.offered.itemDoubleClicked.connect(lambda _item: self._add())
        layout.addWidget(self.offered, 1)
        buttons = QHBoxLayout()
        add = QPushButton("Add")
        add.clicked.connect(self._add)
        done = QPushButton("Done")
        done.clicked.connect(lambda: editor.toggle_add_dimension(False))
        buttons.addWidget(add)
        buttons.addWidget(done)
        layout.addLayout(buttons)
        self._filling = False

    def fill(self) -> None:
        editor = self.editor
        drawing = editor.drawing
        self._filling = True
        try:
            self.features.clear()
            for f in drawing.features if drawing is not None else ():
                item = QListWidgetItem(f"{f.id}  {f.descriptor.type}")
                item.setData(Qt.ItemDataRole.UserRole, f.id)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked if f.id in editor.picked else Qt.CheckState.Unchecked
                )
                self.features.addItem(item)
            self.offered.clear()
            for c in editor.candidates:
                item = QListWidgetItem(c.words)
                item.setData(Qt.ItemDataRole.UserRole, c)
                self.offered.addItem(item)
            if editor.candidates:
                self.offered.setCurrentRow(0)
        finally:
            self._filling = False

    def _ticked(self, item: QListWidgetItem) -> None:
        if not self._filling:
            self.editor.pick_feature(item.data(Qt.ItemDataRole.UserRole))

    def _add(self) -> None:
        item = self.offered.currentItem()
        if item is not None:
            self.editor.add_candidate(item.data(Qt.ItemDataRole.UserRole))


__all__ = [
    "BADGES",
    "IDLE_SECONDS",
    "MODEL_CHANGED",
    "MODEL_NOT_FOUND",
    "MODEL_UNCHANGED",
    "DrawingEditor",
    "badges",
    "band_text",
    "blocks_release",
    "dimension_text",
    "material_needs_reason",
    "measured_text",
    "placement_delta",
    "report_text",
    "view_names",
]
