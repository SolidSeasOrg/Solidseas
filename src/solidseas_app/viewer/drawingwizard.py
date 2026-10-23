"""File > New Drawing...: the New Drawing wizard (``docs/DRAWINGS.md`` 15.3).

:class:`DrawingWizard` is a ``QWizard`` of six pages that makes a PRELIMINARY drawing
of one part and writes it: the ``.ssdrw`` always, and its PDF and DXF when ticked.

1. **Part:** the file, its configuration and bodies; the drawing unit, either as the
   part states it or, for a part that states none, the guess with its evidence and
   Inch and Millimetre buttons, one of which must be clicked; the overall size in both
   units; the warnings, and a part SolidSeas refuses (over the bounds, not a part)
   refused here with the reason. All of it from :meth:`DrawingWorker.probe`.
2. **Title block:** title, part number, drawing number, revision, model revision,
   material (from the part, the Drawing Settings list, or typed; one the list does
   not map is flagged, and a heat-treatable one asks for its heat treatment), finish
   (always chosen, None being a choice), and who drew it (from People).
3. **Manufacturing:** Machined (milled), 3D printed and Turned (lathe); Sheet metal
   shown as coming later. The tolerancing scheme, and for a printed part the process
   with its figures (section 10.6), layer height, infill and walls, supports and
   post-processing. Datum faces are chosen on the editor's sheet in stage 1, and the
   page says so. The suggested type is taken until the user chooses one: 3D printed
   for a printing material, Turned for a part the preview finds turned (its
   ``Answer.turned`` says why), else Machined. A turned part takes the machined
   entries of Drawing Settings (``drawing.types.settings_type``).
4. **Views and sheet:** the front direction and its turn, the projected views and
   the isometric, hidden lines, tangent edges, scale and sheet. "Make these my
   defaults" saves them to Drawing Settings (``save_settings``); nothing else here
   changes the settings. Detail and section requests are shown, disabled, as coming
   in a later release.
5. **Dimensions and holes:** the recognised features, the thread candidates (Tapped,
   Clearance, Plain) and the holes whose ends need confirming; coverage by features,
   faces and area, saying "reduced-dimension drawing" plainly when it is one; and
   the checks.
6. **Output:** the folder (next to the part by default, or the Drawing Settings
   folder), checked with ``document.folder_problem`` and refused with its reason
   before anything is written; the names (``document.drawing_file_name`` and
   ``export_name``, with the numbered name a taken one gets); the files; "Open in
   the editor".

**The preview.** From page 2 on, the side of the wizard shows the sheet in a
:class:`.drawingscene.SheetView` on an uneditable :class:`.drawingscene.SheetScene`.
It is made in the drawing child process (:meth:`DrawingWorker.make`, then the edits
the answers of page 5 make) in a worker thread, a short moment
(:data:`PREVIEW_DELAY_MS`) after the user stops changing options. A request in
progress when a newer one starts is cancelled (``DrawingWorker.cancel`` ends the
child's request; the next starts a new child). The UI thread never waits on the
child: it only starts jobs and shows their answers. A progress bar under the sheet
says each stage of the drawing as the child starts it (:data:`STAGE_WORDS`). The
preview takes the room the pages (:data:`PAGE_WIDTH`) do not need, and View
Larger... shows the same sheet in a window of its own.

**What is written, and when.** Nothing before Finish. Finish checks the folder again,
takes the preview's drawing when it was made from the options as they are (else
makes it), applies the thread and end answers of page 5 as ``confirm_thread`` and
``confirm_end`` edits and a printed part's extra notes as ``edit_notes``, has the
child export the PDF and DXF, and writes them in this process through
``document.export_target``, ``write_output`` and ``record_output``, then the drawing
through ``save_target`` and ``save`` (12.5, 12.6): every file through a temporary
name and a rename, and a name taken by any file gets " (2)", " (3)" and so on, so a
new drawing never replaces anything. Then it emits ``drawing_written(path,
open_editor)`` and closes.

**An assembly** (``docs/drawings/assemblies.md``) is made the same way: page 1 lists
its part instances in place of bodies and says how many items its parts list has
and which instances cannot be drawn; page 2 has no material or finish, which are
its parts'; pages 3 and 5, how a part is made and its dimensions, are skipped; and
page 4 starts from the assembly's own views: front, top, right and the isometric,
without hidden lines.

**First use.** When Drawing Settings still lack an answer only the user can give
(``drawingsettings.first_use_prompts``: the unit for parts that state none, the
company's name, the people who sign), the wizard offers to open Drawing Settings on
the page that lacks it before it goes on, and page 1 keeps a button for it.

The dialogs the wizard can open (the question, Drawing Settings, the folder chooser)
are attributes (:attr:`DrawingWizard.ask`, :attr:`DrawingWizard.edit_settings`,
:attr:`DrawingWizard.pick_folder`) that tests replace, so no test opens one.
"""

from __future__ import annotations

import functools
import os
import threading
from collections import Counter, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from solidseas.drawing import document, locate, standards
from solidseas.drawing import settings as drawing_settings
from solidseas.drawing.types import DIRECTIONS, DrawingOptions, settings_type
from solidseas.errors import (
    ConfigurationNotFoundError,
    InvalidArgumentError,
    ModelNotFoundError,
    OutputRefusedError,
    SolidSeasError,
)

from . import drawingsettings, experimental
from .drawingproc import ProcessStopped
from .drawingscene import SheetScene, SheetView
from .workers import Job

PART, TITLE, MANUFACTURING, VIEWS, DIMENSIONS, OUTPUT = range(6)
PAGE_TITLES = ("Part", "Title block", "Manufacturing", "Views and sheet", "Dimensions and holes", "Output")
PREVIEW_DELAY_MS = 400  # the preview is made this long after the last change
PAGE_WIDTH = 640  # pixels the pages keep beside the preview, which takes the rest of the window
PREVIEW_STRETCH = 3  # the preview's share of the room past the pages' (the pages have none)
SCREEN_SHARE = 0.9  # the wizard opens at this share of the screen's free area
# Where each stage of the drawing pipeline starts on the preview's progress bar, per cent
# (drawing the views and placing the dimensions take most of the time), and its words.
STAGE_START = {"source": 0, "model": 4, "features": 18, "views": 28, "plan": 58, "assemble": 88, "edits": 94}
STAGE_WORDS = {
    "source": "Reading the part",
    "model": "Meshing the part",
    "features": "Recognising its features",
    "views": "Drawing the views",
    "plan": "Placing the dimensions",
    "assemble": "Checking the drawing",
    "edits": "Applying your answers",
}
TITLE_CHARS = 256  # a title field (DrawingLimits.title_chars)
UNIT_NAMES = {"in": "inch", "mm": "millimetre"}
LATER = "coming in a later release"
SHEET_METAL_LATER = "coming later"
DATUM_WORDS = (
    "Datum faces A, B and C are chosen from the part's largest faces. In this release you change "
    "them by clicking faces on the drawing editor's sheet, not here."
)
BUILD_WORDS = (
    "Build direction: the model's +Z, as the process note and the build arrow say. To build the "
    "part another way, turn it in the model."
)
FIELD_KEYS = ("title", "part_number", "number", "revision", "model_revision")
FIELD_LABELS = {
    "title": "Title",
    "part_number": "Part number",
    "number": "Drawing number",
    "revision": "Revision",
    "model_revision": "Model revision",
}
PROCESS_LABELS = {"machined": "Machined (milled)", "printed": "3D printed", "turned": "Turned (lathe)"}
DETAIL_LABELS = (
    (
        "simplified",
        "Simplified",
        "The overall size, and holes and bosses by size; the model defines the rest",
    ),
    ("complex", "Complex", "Every feature sized and located, with plus/minus tolerances and no GD&T"),
    ("full", "Fully defined", "Every feature sized and located, with datums and GD&T, checked complete"),
)
DETAIL_WORDS = (
    "How much the drawing says. Simplified is a quick shop print; Fully defined is the complete "
    "engineering drawing SolidSeas checks."
)
SCHEME_LABELS = (
    ("datum", "Datum-referenced: basic locations and position tolerances"),
    ("plusminus", "Plus and minus"),
)
VIEW_CHOICES = ("top", "right", "left", "bottom", "back")
TANGENT_LABELS = (("hidden", "Not shown"), ("thin", "Thin lines"), ("phantom", "Phantom lines"))
TURN_LABELS = ("Not turned", "Turned 90 degrees", "Turned 180 degrees", "Turned 270 degrees")
AUTO = "auto"
PART_SUBTITLE = "The part the drawing is made of: its configuration, bodies and unit."
ASSEMBLY_PART_SUBTITLE = (
    "The assembly the drawing is made of: its configuration, the part instances drawn and unit."
)
BODIES_LABEL = "Bodies drawn:"
INSTANCES_LABEL = "Instances drawn:"
ASSEMBLY_TITLE_NOTE = (
    "An assembly's title block has no material or finish: its parts list names its parts, and each part's "
    "drawing gives its own."
)
ASSEMBLY_VIEWS = ("top", "right")  # with the front and the isometric (drawing.assembly.VIEWS)
ASSEMBLY_SKIPS = (MANUFACTURING, DIMENSIONS)  # how a part is made, and its dimensions
ANSWERS = ("unanswered", "tapped", "clearance", "plain")
ANSWER_LABELS = {"unanswered": "Not answered", "tapped": "Tapped", "clearance": "Clearance", "plain": "Plain"}
CONFIRM_END = "Confirm the End"
MAX_CHECK_ROWS = 200


# --------------------------------------------------------------------------- what is asked of the child
@dataclass(frozen=True)
class Request:
    """Everything a drawing is made from: the part, the options, the title and process
    fields, the Drawing Settings, and the edits that follow the make (``confirm_thread``,
    ``confirm_end`` and ``notes``, the lines a printed part adds to its notes). Two
    requests that are equal make the same drawing, so a preview made from one serves
    Finish for the other."""

    part: str
    options: DrawingOptions
    fields: tuple[tuple[str, str], ...]
    settings: Any
    edits: tuple[tuple[str, tuple], ...] = ()


@dataclass(frozen=True)
class Written:
    """What Finish wrote: the drawing's path, every file in the order written (the
    exports first), the words for names that were taken, and the drawing as saved."""

    path: str
    files: tuple[str, ...]
    words: tuple[str, ...]
    drawing: Any


class _Stale(Exception):
    """The job was cancelled, or a newer request replaced it, before it finished."""


def opening_size(parent: Any = None) -> tuple[int, int]:
    """The wizard's size as it opens: :data:`SCREEN_SHARE` of the free area of the screen
    it opens on, at least 1240 by 780 where that screen has the room."""
    screen = parent.screen() if parent is not None else QApplication.primaryScreen()
    if screen is None:
        return 1240, 780
    free = screen.availableGeometry()
    width = min(max(1240, int(free.width() * SCREEN_SHARE)), free.width())
    height = min(max(780, int(free.height() * SCREEN_SHARE)), free.height())
    return width, height


def build_drawing(
    worker: Any,
    request: Request,
    cancelled: Callable[[], bool] = lambda: False,
    running: threading.Event | None = None,
    progress: Callable[[dict], None] | None = None,
) -> Any:
    """The drawing ``request`` asks for, made in the child: ``make``, then each edit of
    ``request.edits`` in turn (a ``notes`` edit is ``edit_notes`` with the made notes
    and its lines after them). A child that lost the model (it was started again) has
    it attached and is asked again. Runs in a worker thread; ``running`` is set while a
    request is with the child, so the UI thread knows a cancel ends this job's request.
    ``progress``, when given, hears each stage start (``{"stage", ...}``: the drawing
    pipeline's, then ``edits``). Raises :class:`_Stale` once ``cancelled()``."""

    def ask(fn: Callable[..., Any], *args: Any) -> Any:
        if cancelled():
            raise _Stale()
        if running is not None:
            running.set()
        try:
            return fn(*args)
        finally:
            if running is not None:
                running.clear()

    make = worker.make if progress is None else functools.partial(worker.make, progress=progress)
    answer = ask(make, request.part, request.options, dict(request.fields), request.settings)
    if request.edits and progress is not None:
        progress({"stage": "edits"})
    for op, args in request.edits:
        if op == "notes":
            op, call_args = "edit_notes", [[n.text for _i, n in answer.drawing.notes] + list(args)]
        else:
            call_args = list(args)
        try:
            answer = ask(worker.edit, answer, op, call_args)
        except ModelNotFoundError:
            ask(worker.attach, answer, request.part)
            answer = ask(worker.edit, answer, op, call_args)
    if cancelled():
        raise _Stale()
    return answer


def write_drawing(
    answer: Any,
    folder: str,
    exported: Mapping[str, bytes],
    part: str,
    opened: str | None = None,
) -> Written:
    """Write ``answer``'s drawing in ``folder`` (12.5, 12.6): the exports in
    ``exported`` (``pdf`` and ``dxf`` bytes from the child) through
    ``document.export_target`` and ``write_output``, each recorded in the drawing's
    ``outputs`` (``record_output``), then the ``.ssdrw`` through ``save_target`` and
    ``save``, naming the part as seen from the drawing (``locate.with_model_path``).
    The folder is checked again first (``document.folder_problem``, ``opened`` the
    folder the viewer has open); a refused one raises ``OutputRefusedError`` and
    nothing is written. A name taken by any file gets the next free one, so nothing is
    ever replaced."""
    problem = document.folder_problem(folder, opened)
    if problem is not None:
        raise OutputRefusedError(f"{problem}: {folder}", detail={"rule": "output_folder"})
    drawing = answer.drawing
    files: list[str] = []
    words: list[str] = []
    for kind in ("pdf", "dxf"):
        data = exported.get(kind)
        if data is None:
            continue
        target = document.export_target(drawing, folder, kind)
        saved = document.write_output(target.path, lambda fh, d=data: fh.write(d), replaces=target.replaces)
        drawing = document.record_output(drawing, kind, os.path.basename(saved.path), saved.sha256)
        files.append(saved.path)
        if target.renamed:
            words.append(target.words)
    target = document.save_target(drawing, os.path.join(folder, document.drawing_file_name(drawing)))
    drawing = locate.with_model_path(drawing, part, target.path)
    saved = document.save(drawing, target.path, replaces=target.replaces)
    if target.renamed:
        words.insert(0, target.words)
    return Written(saved.path, (*files, saved.path), tuple(words), saved.drawing)


# --------------------------------------------------------------------------- words (no Qt)
def _fold(text: str) -> str:
    return " ".join(str(text).casefold().split())


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def error_words(exc: BaseException) -> str:
    """An error as the wizard shows it: the system's reason for a system error, else the
    error's own words."""
    if isinstance(exc, OSError) and not isinstance(exc, SolidSeasError) and exc.strerror:
        return exc.strerror
    return str(exc) or type(exc).__name__


def evidence_words(guess: Any) -> str:
    """Why a part that states no unit looks like inch or millimetre (6.2, Q3)."""
    if guess is None:
        return "not stated in the part"
    both = (
        f"{guess.inch} of {guess.sizes} sizes are whole thousandths of an inch, "
        f"{guess.mm} whole hundredths of a millimetre"
    )
    if not guess.decided:
        return f"not stated; the sizes do not lean either way ({both})"
    if guess.unit == "in":
        return f"not stated; looks like inch ({guess.inch} of {guess.sizes} sizes are whole thousandths)"
    return (
        f"not stated; looks like millimetre ({guess.mm} of {guess.sizes} sizes are whole hundredths "
        "of a millimetre)"
    )


def unit_question(probe: Any, settings: Any) -> bool:
    """Whether the user must click Inch or Millimetre: the part states no unit and
    Drawing Settings draw parts in their own unit (as the CLI's ``units_unstated``)."""
    if probe is None or probe.refused is not None:
        return False
    if settings.standard.units in ("in", "mm"):
        return False
    return probe.unit_origin != "file"


def unit_words(probe: Any, settings: Any) -> str:
    """The drawing unit as page 1 says it."""
    if probe is None or probe.unit is None:
        return "Unit: not known yet"
    fixed = settings.standard.units
    if fixed in ("in", "mm"):
        said = UNIT_NAMES[probe.stated_unit] if probe.stated_unit in UNIT_NAMES else "none"
        return (
            f"Unit: {UNIT_NAMES[fixed]}, as Drawing Settings > Standard and Units say "
            f"(the part states {said})"
        )
    if probe.unit_origin == "file":
        return f"Unit: {UNIT_NAMES[probe.unit]}, stated in the part"
    return f"Unit: {evidence_words(probe.evidence)}. Click the unit the part is in."


def assembly_words(probe: Any) -> str:
    """What an assembly holds, in words: its parts list's items and the instances drawn;
    empty for a part."""
    asm = getattr(probe, "assembly", None)
    if asm is None:
        return ""
    drawn = f"{_plural(asm.instances, 'part instance')} {'is' if asm.instances == 1 else 'are'} drawn"
    words = f"The parts list has {_plural(asm.items, 'item')}; {drawn}"
    if asm.left_out:
        words += f", {len(asm.left_out)} left out (see the warnings)"
    return words + "."


def size_words(probe: Any) -> str:
    """The overall size in both units."""
    mm, inch = (None, None) if probe is None else (probe.size_mm, probe.size_in)
    if mm is None or inch is None:
        return "Overall size: not known"
    return (
        "Overall size: "
        + " x ".join(f"{v:.2f}" for v in mm)
        + " mm ("
        + " x ".join(f"{v:.3f}" for v in inch)
        + " in)"
    )


def material_entry(settings: Any, text: str | None) -> dict | None:
    """The materials list entry ``text`` names: by a model name the entry matches
    (``DrawingSettings.material``), else by its callout."""
    if not text or not text.strip():
        return None
    entry = settings.material(text)
    if entry is not None:
        return entry
    key = _fold(text)
    return next((e for e in settings.materials.entries if _fold(e["callout"]) == key), None)


def material_value(settings: Any, text: str) -> str:
    """What the wizard sends for a material: a callout of the list as the entry's first
    model name, so the drawing takes it from the list; anything else as typed."""
    text = text.strip()
    if settings.material(text) is not None:
        return text
    entry = material_entry(settings, text)
    if entry is not None and entry["names"]:
        return entry["names"][0]
    return text


def none_finish(settings: Any) -> str:
    """The finish list's entry for no finish (its callout NONE), by its name: the title
    page's default finish."""
    for f in settings.materials.finishes:
        if _fold(f["callout"]) == _fold("NONE"):
            return f["name"]
    return "None"


def finish_callout(settings: Any, text: str) -> str:
    """A finish of the list (by its name or its callout) as its callout; anything else
    as typed."""
    key = _fold(text)
    for f in settings.materials.finishes:
        if _fold(f["name"]) == key or _fold(f["callout"]) == key:
            return f["callout"]
    return text.strip()


def _amount(mm: float) -> str:
    inch = f"{mm / 25.4:.3f}"
    inch = inch[1:] if inch.startswith("0.") else inch
    return f"±{mm:.3f} mm (±{inch} in)"


def process_words(process: Mapping[str, Any]) -> str:
    """A printing process's figures (10.6) in words."""
    xy, z = float(process["xy_fixed_mm"]), float(process["z_fixed_mm"])
    rate = float(process["rate"]) * 100.0
    parts: list[str] = []
    if xy or z:
        if xy == z:
            parts.append(f"{_amount(xy)} in X, Y and Z")
        else:
            parts.append(f"{_amount(xy)} in X and Y, {_amount(z)} in Z")
        if rate:
            parts.append(f"each plus {rate:g} % of the nominal")
    elif rate:
        parts.append(f"±{rate:g} % of the nominal")
    if process.get("floor_mm"):
        parts.append(f"never under {_amount(float(process['floor_mm']))}")
    category = f" ({process['category']})" if process.get("category") else ""
    return f"{process['name']}{category}: " + (", ".join(parts) or "no figures")


def coverage_lines(coverage: Any) -> list[str]:
    """Coverage by features, faces and area (10.10, 20.2), the last line saying plainly
    whether this is a reduced-dimension drawing."""
    if coverage is None:
        return ["Coverage: not known yet"]
    share = 100.0 if coverage.area <= 0 else 100.0 * coverage.area_claimed / coverage.area
    lines = [
        f"By features: {_plural(coverage.features, 'feature')} recognised, "
        f"{coverage.features_unclaimed} left unclaimed",
        f"By faces: {coverage.faces_claimed:,} of {_plural(coverage.faces, 'face')} claimed by features",
        f"By area: {share:.0f} % claimed",
    ]
    if coverage.complete:
        lines.append("Every recognised face is dimensioned: this is a fully dimensioned drawing.")
    else:
        lines.append(
            "This is a reduced-dimension drawing: "
            + coverage.words().removeprefix("reduced-dimension drawing: ")
            + ". A note on the sheet says the model defines them."
        )
    return lines


def checks_words(checks: Sequence[Any]) -> str:
    """The checks summary: how many errors, warnings and notes."""
    n = Counter(c.level for c in checks)
    return (
        f"Checks: {_plural(n['error'], 'error')}, {_plural(n['warning'], 'warning')}, "
        f"{_plural(n['information'], 'note')}. Errors such as unsigned rows are expected before "
        "release; the editor lists each with its fixes."
    )


def thread_spec(designation: str) -> str | None:
    """A thread candidate's designation (``M6 x 1``) as the tapped hole's thread
    (``M6 x 1-6H``), or None for one SolidSeas does not list."""
    key = _fold(designation)
    for t in standards.THREADS:
        if _fold(t.designation) == key or _fold(t.internal()) == key:
            return t.internal()
    return None


def front_words(options: Any) -> str:
    """The front SolidSeas chose (8.2), from a made drawing's frozen options."""
    if options is None or options.front is None:
        return "SolidSeas chooses the front when the preview is made."
    turn = TURN_LABELS[options.turn].lower()
    return (
        f"SolidSeas chose the front looking from {options.front.upper()}, {turn}: the one showing the "
        "most features in true shape with the fewest hidden, the longest extent across."
    )


# --------------------------------------------------------------------------- small widgets
def _label(text: str = "", *, note: bool = False) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)  # part and settings text is never markup
    if note:
        font = label.font()
        font.setItalic(True)
        label.setFont(font)
    return label


def _line(max_length: int = TITLE_CHARS) -> QLineEdit:
    edit = QLineEdit()
    edit.setMaxLength(max_length)
    return edit


class _Page(QWizardPage):
    """A page whose completeness the wizard decides (:meth:`DrawingWizard.page_problems`)."""

    def __init__(self, wizard: DrawingWizard, index: int, subtitle: str) -> None:
        super().__init__()
        self.w = wizard
        self.index = index
        self.setTitle(PAGE_TITLES[index])
        self.setSubTitle(subtitle)

    def isComplete(self) -> bool:  # noqa: N802 (Qt's name)
        return not self.w.page_problems(self.index)

    def validatePage(self) -> bool:  # noqa: N802 (Qt's name)
        return self.w.validate_page(self.index)


# --------------------------------------------------------------------------- page 1
class PartPage(_Page):
    def __init__(self, wizard: DrawingWizard) -> None:
        super().__init__(wizard, PART, PART_SUBTITLE)
        self.first_use_label = _label()
        self.settings_label = _label(note=True)
        self.settings_button = QPushButton("Open Drawing Settings...")
        self.settings_button.clicked.connect(lambda: wizard.open_settings(None))
        self.file_label = _label()
        self.configuration = QComboBox()
        self.bodies = QListWidget()
        self.bodies.setMaximumHeight(110)
        self.unit_label = _label()
        self.inch_button = QPushButton("Inch")
        self.mm_button = QPushButton("Millimetre")
        self.unit_group = QButtonGroup(self)
        self.unit_group.setExclusive(True)
        for button in (self.inch_button, self.mm_button):
            button.setCheckable(True)
            self.unit_group.addButton(button)
        self.size_label = _label()
        self.warnings_label = _label()
        self.refusal_label = _label()
        bold = self.refusal_label.font()
        bold.setBold(True)
        self.refusal_label.setFont(bold)
        self.status_label = _label(note=True)

        units = QHBoxLayout()
        units.addWidget(self.inch_button)
        units.addWidget(self.mm_button)
        units.addStretch(1)
        form = QFormLayout()
        form.addRow("File:", self.file_label)
        form.addRow("Configuration:", self.configuration)
        self.bodies_label = QLabel(BODIES_LABEL)
        form.addRow(self.bodies_label, self.bodies)
        layout = QVBoxLayout(self)
        layout.addWidget(self.first_use_label)
        layout.addWidget(self.settings_label)
        layout.addWidget(self.settings_button)
        layout.addLayout(form)
        layout.addWidget(self.unit_label)
        layout.addLayout(units)
        layout.addWidget(self.size_label)
        layout.addWidget(self.warnings_label)
        layout.addWidget(self.refusal_label)
        layout.addWidget(self.status_label)
        layout.addStretch(1)

        self.configuration.activated.connect(lambda _i: wizard.configuration_chosen())
        self.bodies.itemChanged.connect(lambda _item: wizard.changed(PART))
        self.unit_group.buttonClicked.connect(lambda _b: wizard.changed(PART))

    def chosen_unit(self) -> str | None:
        if self.inch_button.isChecked():
            return "in"
        if self.mm_button.isChecked():
            return "mm"
        return None

    def ticked_bodies(self) -> list[str]:
        return [
            self.bodies.item(i).text()
            for i in range(self.bodies.count())
            if self.bodies.item(i).checkState() == Qt.CheckState.Checked
        ]

    def show_probe(self, probe: Any, note: str, settings: Any) -> None:
        self.bodies.blockSignals(True)
        self.configuration.blockSignals(True)
        try:
            self.configuration.clear()
            names = list(probe.configurations) or ([probe.configuration] if probe.configuration else [])
            for name in names:
                self.configuration.addItem(name)
            if probe.configuration in names:
                self.configuration.setCurrentIndex(names.index(probe.configuration))
            self.configuration.setEnabled(len(names) > 1)
            self.bodies.clear()
            asm = getattr(probe, "assembly", None) is not None
            for body in probe.bodies:
                item = QListWidgetItem(body.name)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if body.selected else Qt.CheckState.Unchecked)
                hidden = ", hidden in the model" if body.hidden else ""
                what = "part instance" if asm else f"{body.type} body"
                item.setToolTip(f"{what} of {_plural(body.faces, 'face')}{hidden}")
                self.bodies.addItem(item)
        finally:
            self.bodies.blockSignals(False)
            self.configuration.blockSignals(False)
        self.bodies_label.setText(INSTANCES_LABEL if asm else BODIES_LABEL)
        self.setSubTitle(ASSEMBLY_PART_SUBTITLE if asm else PART_SUBTITLE)
        self.show_unit(probe, settings)
        self.size_label.setText("\n".join(t for t in (size_words(probe), assembly_words(probe)) if t))
        lines = list(probe.warnings)
        faces = int(probe.counts.get("faces", 0)) if probe.counts else 0
        draft = settings.limits.draft_faces
        if faces > draft:
            lines.append(
                f"Draft quality: the part has {faces:,} faces, more than the {draft:,} of Drawing Settings > "
                "Limits, so its views are drawn coarser"
            )
        if note:
            lines.insert(0, note)
        self.warnings_label.setText("\n".join(f"Warning: {w}" for w in lines))
        self.warnings_label.setVisible(bool(lines))
        if probe.refused is not None:
            what = "assembly" if asm else "part"
            self.refusal_label.setText(f"SolidSeas cannot draw this {what}: {probe.refused}.")
        self.refusal_label.setVisible(probe.refused is not None)
        self.status_label.clear()

    def show_unit(self, probe: Any, settings: Any) -> None:
        self.unit_label.setText(unit_words(probe, settings))
        ask = unit_question(probe, settings)
        self.inch_button.setVisible(ask)
        self.mm_button.setVisible(ask)

    def show_first_use(self, prompts: Sequence[tuple[str, str]], problems: Sequence[str] = ()) -> None:
        """What Drawing Settings still wait for, and the values they could not read."""
        text = "Before your first drawing:\n" + "\n".join(t for _p, t in prompts) if prompts else ""
        self.first_use_label.setText(text)
        self.first_use_label.setVisible(bool(prompts))
        self.settings_label.setText(
            "Drawing Settings could not read these and use their defaults until you save them:\n"
            + "\n".join(problems)
            if problems
            else ""
        )
        self.settings_label.setVisible(bool(problems))
        self.settings_button.setVisible(bool(prompts) or bool(problems))


# --------------------------------------------------------------------------- page 2
class TitlePage(_Page):
    def __init__(self, wizard: DrawingWizard) -> None:
        super().__init__(
            wizard,
            TITLE,
            "What the title block says. An empty field takes the part's own value, shown greyed.",
        )
        self.edits: dict[str, QLineEdit] = {key: _line() for key in FIELD_KEYS}
        self.material = QComboBox()
        self.material.setEditable(True)
        self.material.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.material.lineEdit().setMaxLength(TITLE_CHARS)
        self.material_note = _label(note=True)
        self.heat_label = QLabel("Heat treatment:")
        self.heat = _line()
        self.heat.setPlaceholderText("for example HARDEN TO 28-32 HRC, or NONE")
        self.finish = QComboBox()
        self.finish.setEditable(True)
        self.finish.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.finish.lineEdit().setMaxLength(TITLE_CHARS)
        self.finish.lineEdit().setPlaceholderText("Choose or type the finish (None is a choice)")
        self.finish_note = _label(note=True)
        # The finish starts as None, or as the part's own once a preview shows it, until the
        # user changes it; it never holds the drawing up.
        self.finish_default = True
        self.part_finish: str | None = None  # the part's own finish; "" when it states none
        self._putting_finish = False
        self.drawn_by = QComboBox()
        self.problems_label = _label()

        self.form = form = QFormLayout()
        for key in FIELD_KEYS:
            form.addRow(FIELD_LABELS[key] + ":", self.edits[key])
        form.addRow("Material:", self.material)
        form.addRow("", self.material_note)
        form.addRow(self.heat_label, self.heat)
        form.addRow("Finish:", self.finish)
        form.addRow("", self.finish_note)
        form.addRow("Drawn by:", self.drawn_by)
        self.assembly_label = _label(ASSEMBLY_TITLE_NOTE, note=True)
        self.assembly_label.hide()
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.assembly_label)
        layout.addWidget(_label("Checker and approver sign in the editor, not here.", note=True))
        layout.addWidget(self.problems_label)
        layout.addStretch(1)

        for edit in self.edits.values():
            edit.textChanged.connect(lambda _t: wizard.changed(TITLE))
        self.material.currentTextChanged.connect(lambda _t: wizard.changed(TITLE))
        self.heat.textChanged.connect(lambda _t: wizard.changed(TITLE))
        self.finish.currentTextChanged.connect(lambda _t: self._finish_changed(wizard))
        self.drawn_by.currentIndexChanged.connect(lambda _i: wizard.changed(TITLE))

    def _finish_changed(self, wizard: DrawingWizard) -> None:
        if not self._putting_finish:
            self.finish_default = False  # the user's own choice from now on
        wizard.changed(TITLE)

    def put_finish(self, text: str) -> None:
        """Show ``text`` as the default finish, which the user has not chosen."""
        self._putting_finish = True
        try:
            self.finish.setEditText(text)
        finally:
            self._putting_finish = False

    def fill_lists(self, settings: Any) -> None:
        """The materials, finishes and people of ``settings``; what was typed or chosen
        is kept."""
        for box, items in (
            (self.material, [e["callout"] for e in settings.materials.entries]),
            (self.finish, [f["name"] for f in settings.materials.finishes]),
        ):
            text = box.currentText()
            if box is self.finish and self.finish_default and not text:
                text = self.part_finish or none_finish(settings)
            box.blockSignals(True)
            box.clear()
            box.addItems(items)
            box.setCurrentIndex(-1)
            box.setEditText(text)
            box.blockSignals(False)
        chosen = self.drawn_by.currentText()
        self.drawn_by.blockSignals(True)
        self.drawn_by.clear()
        names = [p["name"] for p in settings.people.people]
        if names:
            self.drawn_by.addItems(names)
            self.drawn_by.setCurrentIndex(names.index(chosen) if chosen in names else 0)
            self.drawn_by.setEnabled(True)
        else:
            self.drawn_by.addItem("Nobody yet: add people in Drawing Settings > People and Approvals")
            self.drawn_by.setEnabled(False)
        self.drawn_by.blockSignals(False)

    def show_assembly(self, assembly: bool) -> None:
        """An assembly's title block has no material or finish of its own: its parts
        have them."""
        for widget in (self.material, self.material_note, self.heat, self.finish, self.finish_note):
            self.form.setRowVisible(widget, not assembly)
        self.assembly_label.setVisible(assembly)

    def drawn_by_name(self, settings: Any) -> str:
        names = [p["name"] for p in settings.people.people]
        text = self.drawn_by.currentText()
        return text if text in names else ""

    def show_part(self, title: Mapping[str, Any]) -> None:
        """The part's own values (a made drawing's title fields of origin ``part`` or
        ``list``), shown greyed in the empty fields."""
        for key, edit in self.edits.items():
            f = title.get(key)
            part = f is not None and f.source != "typed"
            edit.setPlaceholderText(f"from the part: {f.text}" if part else "")
        f = title.get("material")
        self.material.lineEdit().setPlaceholderText(
            f"from the part: {f.text}" if f is not None and f.source != "typed" else "the part names none"
        )
        f = title.get("finish")
        self.finish.lineEdit().setPlaceholderText(
            f"the part says {f.text}: choose or type it (None is a choice)"
            if f is not None and f.source != "typed"
            else "Choose or type the finish (None is a choice)"
        )
        # The part's own finish has the source part; a finish the wizard sent comes back as
        # list or typed, and no finish at all means none was sent and the part states none.
        if f is None or f.source == "part":
            self.part_finish = f.text if f is not None else ""
            if self.finish_default and self.part_finish:
                self.put_finish(self.part_finish)


# --------------------------------------------------------------------------- page 3
class ManufacturingPage(_Page):
    def __init__(self, wizard: DrawingWizard) -> None:
        super().__init__(wizard, MANUFACTURING, "How the part is made decides how it is dimensioned (10.6).")
        self.machined = QRadioButton(PROCESS_LABELS["machined"])
        self.printed = QRadioButton(PROCESS_LABELS["printed"])
        self.turned = QRadioButton(PROCESS_LABELS["turned"])
        self.sheet_metal = QRadioButton(f"Sheet metal: {SHEET_METAL_LATER}")
        self.sheet_metal.setEnabled(False)
        self.group = QButtonGroup(self)
        for k, button in enumerate((self.machined, self.printed, self.turned, self.sheet_metal)):
            self.group.addButton(button, k)
        self.machined.setChecked(True)
        self.suggestion_label = _label(note=True)
        self.scheme = QComboBox()
        for value, text in SCHEME_LABELS:
            self.scheme.addItem(text, value)
        self.datum_label = _label(DATUM_WORDS)
        self.detail = QComboBox()
        for value, text, hint in DETAIL_LABELS:
            self.detail.addItem(text, value)
            self.detail.setItemData(self.detail.count() - 1, hint, Qt.ItemDataRole.ToolTipRole)
        self.detail.setCurrentIndex(self.detail.findData("full"))
        self.detail.setToolTip(DETAIL_WORDS)

        self.printed_box = QGroupBox("3D printing")
        self.process = QComboBox()
        self.figures_label = _label()
        self.figures_note = _label(note=True)
        self.layer_height = _line(64)
        self.layer_height.setPlaceholderText("for example 0.1 mm")
        self.infill = _line(200)
        self.infill.setPlaceholderText("for example 100 % infill, 3 walls, required")
        self.supports = _line(200)
        self.supports.setPlaceholderText("for example soluble supports allowed")
        self.post = _line(200)
        self.post.setPlaceholderText("for example bead blast all over")
        printed = QFormLayout(self.printed_box)
        printed.addRow("Process:", self.process)
        printed.addRow("", self.figures_label)
        printed.addRow("", self.figures_note)
        printed.addRow("Layer height:", self.layer_height)
        printed.addRow("Infill and walls:", self.infill)
        printed.addRow("Supports:", self.supports)
        printed.addRow("Post-processing:", self.post)
        printed.addRow("", _label(BUILD_WORDS, note=True))

        layout = QVBoxLayout(self)
        for button in (self.machined, self.printed, self.turned, self.sheet_metal):
            layout.addWidget(button)
        layout.addWidget(self.suggestion_label)
        scheme = QFormLayout()
        scheme.addRow("Detail:", self.detail)
        scheme.addRow("Tolerancing:", self.scheme)
        layout.addLayout(scheme)
        layout.addWidget(self.datum_label)
        layout.addWidget(self.printed_box)
        layout.addStretch(1)

        self.group.idClicked.connect(lambda _i: wizard.process_chosen())
        self.scheme.activated.connect(lambda _i: wizard.scheme_chosen())
        self.detail.activated.connect(lambda _i: wizard.detail_chosen())
        self.process.currentIndexChanged.connect(lambda _i: wizard.changed(MANUFACTURING))
        for edit in (self.layer_height, self.infill, self.supports, self.post):
            edit.textChanged.connect(lambda _t: wizard.changed(MANUFACTURING))

    def chosen_process(self) -> str:
        if self.printed.isChecked():
            return "printed"
        return "turned" if self.turned.isChecked() else "machined"

    def choose(self, process: str) -> None:
        """Tick the button of ``process``."""
        {"printed": self.printed, "turned": self.turned}.get(process, self.machined).setChecked(True)

    def fill_processes(self, settings: Any) -> None:
        chosen = self.process.currentText()
        self.process.blockSignals(True)
        self.process.clear()
        names = [p["name"] for p in settings.printing.processes]
        self.process.addItems(names)
        if chosen in names:
            self.process.setCurrentIndex(names.index(chosen))
        self.process.blockSignals(False)
        self.figures_note.setText(settings.printing.label)

    def chosen_figures(self, settings: Any) -> Mapping[str, Any] | None:
        name = self.process.currentText()
        return next((p for p in settings.printing.processes if p["name"] == name), None)


# --------------------------------------------------------------------------- page 4
class ViewsPage(_Page):
    def __init__(self, wizard: DrawingWizard) -> None:
        super().__init__(wizard, VIEWS, "Which views the sheet shows, how, and at what scale.")
        self.front = QComboBox()
        self.front.addItem("Chosen by SolidSeas", AUTO)
        for d in DIRECTIONS:
            self.front.addItem(f"Looking from {d.upper()}", d)
        self.turn = QComboBox()
        for k, text in enumerate(TURN_LABELS):
            self.turn.addItem(text, k)
        self.chosen_label = _label(note=True)
        self.views: dict[str, QCheckBox] = {v: QCheckBox(v.capitalize()) for v in VIEW_CHOICES}
        self.isometric = QCheckBox("Isometric")
        self.hidden = QCheckBox("Hidden lines")
        self.tangent = QComboBox()
        for value, text in TANGENT_LABELS:
            self.tangent.addItem(text, value)
        self.scale = QComboBox()
        self.sheet = QComboBox()
        self.sheet.addItem("Chosen by SolidSeas", AUTO)
        for name in standards.SHEET_ORDER:
            self.sheet.addItem(f"{name} size", name)
        self.defaults_button = QPushButton("Make these my defaults")
        self.defaults_button.setToolTip(
            "Saves the views, isometric, hidden lines, tangent edges, front direction and sheet size to "
            "Drawing Settings as the defaults for parts made this way. The turn and the scale stay with "
            "this drawing alone."
        )
        self.defaults_label = _label(note=True)
        self.detail_button = QPushButton("Add Detail View...")
        self.section_button = QPushButton("Add Section...")
        for button in (self.detail_button, self.section_button):
            button.setEnabled(False)
            button.setToolTip(f"Detail views and sections on request are {LATER}")
        self.later_label = _label(f"Detail views and sections on request: {LATER}.", note=True)

        grid = QGridLayout()
        grid.addWidget(QLabel("Front (always drawn):"), 0, 0)
        grid.addWidget(self.front, 0, 1)
        grid.addWidget(self.turn, 0, 2)
        ticks = QHBoxLayout()
        for box in (*self.views.values(), self.isometric):
            ticks.addWidget(box)
        ticks.addStretch(1)
        form = QFormLayout()
        form.addRow("Projected views:", ticks)
        form.addRow("", self.hidden)
        form.addRow("Tangent edges:", self.tangent)
        form.addRow("Scale:", self.scale)
        form.addRow("Sheet:", self.sheet)
        later = QHBoxLayout()
        later.addWidget(self.detail_button)
        later.addWidget(self.section_button)
        later.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(grid)
        layout.addWidget(self.chosen_label)
        layout.addLayout(form)
        layout.addLayout(later)
        layout.addWidget(self.later_label)
        layout.addWidget(self.defaults_button)
        layout.addWidget(self.defaults_label)
        layout.addStretch(1)

        self.front.currentIndexChanged.connect(lambda _i: wizard.views_changed(touched=True))
        self.turn.currentIndexChanged.connect(lambda _i: wizard.views_changed(touched=True))
        for box in (*self.views.values(), self.isometric, self.hidden):
            box.toggled.connect(lambda _on: wizard.views_changed(touched=True))
        self.tangent.currentIndexChanged.connect(lambda _i: wizard.views_changed(touched=True))
        self.scale.currentIndexChanged.connect(lambda _i: wizard.changed(VIEWS))
        self.sheet.currentIndexChanged.connect(lambda _i: wizard.views_changed(touched=True))
        self.defaults_button.clicked.connect(wizard.make_defaults)

    def fill_scales(self, settings: Any) -> None:
        chosen = self.scale.currentData()
        self.scale.blockSignals(True)
        self.scale.clear()
        self.scale.addItem("Chosen by SolidSeas", AUTO)
        for text in settings.sheets.scales:
            self.scale.addItem(text, text)
        index = self.scale.findData(chosen) if chosen is not None else 0
        self.scale.setCurrentIndex(max(index, 0))
        self.scale.blockSignals(False)

    def put_defaults(self, settings: Any, process: str) -> None:
        """The Default Views of ``process`` and the default sheet size, as the controls'
        values."""
        d = settings.defaults.views[settings_type(process)]
        widgets = (*self.views.values(), self.isometric, self.hidden, self.front, self.tangent, self.sheet)
        for widget in widgets:
            widget.blockSignals(True)
        try:
            for name, box in self.views.items():
                box.setChecked(name in d["views"])
            self.isometric.setChecked(bool(d["isometric"]))
            self.hidden.setChecked(bool(d["hidden"]))
            self.front.setCurrentIndex(max(self.front.findData(d["front"]), 0))
            self.tangent.setCurrentIndex(max(self.tangent.findData(d["tangent"]), 0))
            self.sheet.setCurrentIndex(max(self.sheet.findData(settings.sheets.size), 0))
        finally:
            for widget in widgets:
                widget.blockSignals(False)
        self.turn.setEnabled(self.front.currentData() != AUTO)

    def put_assembly_defaults(self) -> None:
        """An assembly's own views as the controls' values: front, top, right and the
        isometric, without hidden lines, the front seen from the assembly's front."""
        widgets = (*self.views.values(), self.isometric, self.hidden, self.front)
        for widget in widgets:
            widget.blockSignals(True)
        try:
            for name, box in self.views.items():
                box.setChecked(name in ASSEMBLY_VIEWS)
            self.isometric.setChecked(True)
            self.hidden.setChecked(False)
            self.front.setCurrentIndex(max(self.front.findData(AUTO), 0))
        finally:
            for widget in widgets:
                widget.blockSignals(False)
        self.turn.setEnabled(False)

    def ticked(self) -> list[str]:
        return [name for name, box in self.views.items() if box.isChecked()]


# --------------------------------------------------------------------------- page 5
class DimensionsPage(_Page):
    def __init__(self, wizard: DrawingWizard) -> None:
        super().__init__(
            wizard,
            DIMENSIONS,
            "What SolidSeas recognised, the holes it needs your answer on, and how much is dimensioned.",
        )
        self.status_label = _label(note=True)
        self.features = QTreeWidget()
        self.features.setHeaderLabels(["Feature", "Dimensions"])
        self.features.setMaximumHeight(150)
        self.threads = QTableWidget(0, 5)
        self.threads.setHorizontalHeaderLabels(["Hole", "Size", "Answer", "Thread", "Thread depth"])
        self.threads.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.threads.verticalHeader().setVisible(False)
        self.threads.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.threads.setMaximumHeight(150)
        self.threads_note = _label(
            "A hole whose size is a tap drill may be tapped. Tapped calls out the thread you choose; "
            "Clearance and Plain leave it a plain hole. A thread is called out only once you confirm it.",
            note=True,
        )
        self.threads_none = _label("None: no hole's size is a tap drill.", note=True)
        self.ends = QListWidget()
        self.ends.setMaximumHeight(90)
        self.coverage_label = _label()
        self.checks_label = _label()
        self.checks_list = QListWidget()
        self.checks_list.setMaximumHeight(130)
        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addWidget(QLabel("Recognised features:"))
        layout.addWidget(self.features)
        layout.addWidget(QLabel("Thread candidates:"))
        layout.addWidget(self.threads)
        layout.addWidget(self.threads_none)
        layout.addWidget(self.threads_note)
        layout.addWidget(QLabel("Holes whose ends need confirming (tick: it runs into the bore):"))
        layout.addWidget(self.ends)
        layout.addWidget(self.coverage_label)
        layout.addWidget(self.checks_label)
        layout.addWidget(self.checks_list)
        self.ends.itemChanged.connect(lambda item: wizard.end_answered(item))
        # the rows of the thread table, by feature id: (answer, thread, depth) controls
        self.rows: dict[str, tuple[QComboBox, QComboBox, QDoubleSpinBox]] = {}


# --------------------------------------------------------------------------- page 6
class OutputPage(_Page):
    def __init__(self, wizard: DrawingWizard) -> None:
        super().__init__(wizard, OUTPUT, "Where the drawing's files go. Nothing is written before Finish.")
        self.folder = QLineEdit()
        self.browse = QPushButton("Choose...")
        self.folder_label = _label()
        bold = self.folder_label.font()
        bold.setBold(True)
        self.folder_label.setFont(bold)
        self.names_label = _label()
        self.drawing_box = QCheckBox("The drawing (.ssdrw), always")
        self.drawing_box.setChecked(True)
        self.drawing_box.setEnabled(False)
        self.pdf_box = QCheckBox("PDF")
        self.dxf_box = QCheckBox("DXF")
        self.pdf_box.setChecked(True)
        self.dxf_box.setChecked(True)
        self.open_editor = QCheckBox("Open in the editor")
        self.open_editor.setChecked(True)
        self.status_label = _label()
        where = QHBoxLayout()
        where.addWidget(self.folder, 1)
        where.addWidget(self.browse)
        files = QHBoxLayout()
        for box in (self.drawing_box, self.pdf_box, self.dxf_box):
            files.addWidget(box)
        files.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Folder:"))
        layout.addLayout(where)
        layout.addWidget(self.folder_label)
        layout.addWidget(self.names_label)
        layout.addWidget(QLabel("Files, written as PRELIMINARY:"))
        layout.addLayout(files)
        layout.addWidget(self.open_editor)
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        self.folder.textChanged.connect(lambda _t: wizard.folder_changed())
        self.browse.clicked.connect(wizard.choose_folder)
        for box in (self.pdf_box, self.dxf_box):
            box.toggled.connect(lambda _on: wizard.folder_changed())

    def initializePage(self) -> None:  # noqa: N802 (Qt's name)
        self.w.folder_changed()


# --------------------------------------------------------------------------- the wizard
class DrawingWizard(QWizard):
    """File > New Drawing... (see the module notes). ``worker`` is the window's
    :class:`.drawingproc.DrawingWorker` (or a stand-in with its ``probe``, ``make``,
    ``edit``, ``attach``, ``export``, ``forget`` and ``cancel``); ``part`` the part's
    path; ``configuration`` the one to draw (None: the part's active one);
    ``settings`` the loaded Drawing Settings (None: read from ``settings_path``, the
    user's ``Drawing.json`` when that is None too); ``folder`` the folder the viewer has
    open, which ``document.folder_problem`` takes as ``opened`` (a network folder
    inside it may be written to). ``drawing_written(path, open_editor)`` is emitted
    once the files are written."""

    drawing_written = Signal(str, bool)

    def __init__(
        self,
        parent: QWidget | None,
        worker: Any,
        part: str | os.PathLike,
        *,
        configuration: str | None = None,
        settings: Any = None,
        settings_path: str | os.PathLike | None = None,
        folder: str | os.PathLike | None = None,
    ) -> None:
        super().__init__(parent)
        self.worker = worker
        self.part = os.path.abspath(os.fspath(part))
        self.settings_path = os.fspath(settings_path) if settings_path is not None else None
        self.opened = os.fspath(folder) if folder is not None else None
        self.settings_problems: list[str] = []
        if settings is None:
            settings, problems = drawing_settings.load_settings(self.settings_path)
            self.settings_problems = list(problems)
        if not isinstance(settings, drawing_settings.DrawingSettings):
            raise InvalidArgumentError("settings must be DrawingSettings", detail={"parameter": "settings"})
        self.settings = settings
        self.preview_delay_ms = PREVIEW_DELAY_MS
        # The dialogs, which tests replace: ask(title, text) -> bool; edit_settings(page)
        # -> the settings saved, or None; pick_folder(start) -> a folder, or "".
        self.ask: Callable[[str, str], bool] = self._ask
        self.edit_settings: Callable[[str | None], Any] = self._edit_settings
        self.pick_folder: Callable[[str], str] = self._pick_folder

        self.probe: Any = None
        self.probe_note = ""
        self.probe_error: str | None = None
        self.answer: Any = None  # the latest preview
        self.answer_request: Request | None = None
        self.preview_error: str | None = None
        self.written: Written | None = None
        self.cancelled_requests = 0  # requests in progress cancelled by a newer one
        self.thread_answers: dict[str, tuple[str, str, float]] = {}  # fid: (answer, designation, depth)
        self.end_answers: dict[str, str] = {}  # fid: the words of its row, for each end confirmed
        self._lock = threading.Lock()
        self._built: tuple[Request, Any] | None = None  # the last drawing a job made, for Finish
        self._requested: Request | None = None
        self._gen = 0
        self._probe_gen = 0
        self._jobs: dict[int, tuple[str, Job, threading.Event]] = {}
        self._job_ids = 0
        self._writing = False
        self._offered = False
        self._process_touched = False
        self.turned_reason: str | None = None  # why the part looks turned, from a preview
        self._scheme_touched = False
        self._detail_touched = False  # the Detail choice, else Drawing Settings' default
        self._views_touched = False
        self._finished_jobs: deque[Job] = deque(maxlen=16)  # kept while their threads return

        self.pool = QThreadPool(self)  # waits on the drawing child, one job at a time
        self.pool.setMaxThreadCount(1)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.request_preview)

        self.setWindowTitle(f"New Drawing of {os.path.basename(self.part)}")
        self.setOption(QWizard.WizardOption.IndependentPages, True)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.resize(*opening_size(parent))
        self.part_page = PartPage(self)
        self.title_page = TitlePage(self)
        self.manufacturing_page = ManufacturingPage(self)
        self.views_page = ViewsPage(self)
        self.dimensions_page = DimensionsPage(self)
        self.output_page = OutputPage(self)
        self.pages = (
            self.part_page,
            self.title_page,
            self.manufacturing_page,
            self.views_page,
            self.dimensions_page,
            self.output_page,
        )
        self._add_pages()

        self.preview_status = _label(note=True)
        self.preview_progress = QProgressBar()
        self.preview_progress.setRange(0, 100)
        self.preview_progress.hide()
        self.scene = SheetScene(editable=False)
        self.view = SheetView(self.scene)
        self.view.setMinimumSize(460, 340)
        self.larger_button = QPushButton("View Larger...")
        self.larger_button.setToolTip("The preview in a window of its own, as large as the screen")
        self.larger_button.setEnabled(False)
        self.larger_button.clicked.connect(self.view_larger)
        self.larger: QDialog | None = None  # the preview's own window, once opened
        panel = QWidget()
        side = QVBoxLayout(panel)
        side.setContentsMargins(0, 0, 0, 0)
        self.experimental_note = experimental.note_label(experimental.drawings_note())
        side.addWidget(self.experimental_note)  # drawings are experimental: said on every page
        head = QHBoxLayout()
        head.addWidget(QLabel("Preview"))
        head.addStretch(1)
        head.addWidget(self.larger_button)
        side.addLayout(head)
        side.addWidget(self.view, 1)
        side.addWidget(self.preview_progress)
        side.addWidget(self.preview_status)
        self.preview_panel = panel  # shown from page 1: the preview starts once the part is read
        self.setSideWidget(panel)
        self.currentIdChanged.connect(self._page_shown)

        self.part_page.file_label.setText(self.part)
        self.part_page.status_label.setText("Reading the part...")
        self.output_page.folder.setText(self.default_folder())
        self._apply_settings(first=True)
        self.start_probe(configuration)

    def _add_pages(self) -> None:
        """Put the six pages in the wizard. The Guided wizard (:mod:`.drawingguided`)
        puts its own questions in their place and keeps these pages, unshown, as the
        answers' store."""
        for page in self.pages:
            page.setMinimumWidth(PAGE_WIDTH)
            self.setPage(page.index, page)

    # ------------------------------------------------------------------ settings
    def default_folder(self) -> str:
        """The folder of Drawing Settings > Files, else the part's own (12.6)."""
        chosen = self.settings.files.folder
        return chosen if chosen else os.path.dirname(self.part)

    def _apply_settings(self, *, first: bool = False) -> None:
        s = self.settings
        self.title_page.fill_lists(s)
        self.manufacturing_page.fill_processes(s)
        self.views_page.fill_scales(s)
        process = self.manufacturing_page.chosen_process()
        if not self._scheme_touched:
            self._put_scheme(process)
        if not self._detail_touched:
            detail = self.manufacturing_page.detail
            detail.setCurrentIndex(max(detail.findData(s.defaults.detail), 0))
        if not self._views_touched:
            self.views_page.put_defaults(s, process)
        self.part_page.show_first_use(drawingsettings.first_use_prompts(s), self.settings_problems)
        if self.probe is not None:
            self.part_page.show_probe(self.probe, self.probe_note, s)
        self._show_figures()
        self.manufacturing_page.printed_box.setVisible(process == "printed")
        if not first:
            self.changed(None)

    def set_settings(self, settings: Any) -> None:
        """Use ``settings`` from now on (saved in Drawing Settings, or by "Make these my
        defaults"); the preview follows."""
        self.settings = settings
        self.settings_problems = []  # saved: every value is one the settings hold
        self._apply_settings()

    def first_use(self) -> list[tuple[str, str]]:
        """What Drawing Settings still wait for, as (page, prompt)."""
        return drawingsettings.first_use_prompts(self.settings)

    def offer_first_use(self) -> bool:
        """On first use, offer to open Drawing Settings on the page that lacks an answer;
        whether they were saved."""
        prompts = self.first_use()
        if not prompts:
            return False
        text = (
            "Drawing Settings still need these before your first drawing:\n\n"
            + "\n".join(p for _page, p in prompts)
            + "\n\nOpen Drawing Settings now?"
        )
        if not self.ask("New Drawing", text):
            return False
        return self.open_settings(prompts[0][0])

    def open_settings(self, page: str | None = None) -> bool:
        """Drawing Settings on ``page`` (the first one waiting for an answer when None);
        whether they were saved."""
        if page is None:
            prompts = self.first_use()
            page = prompts[0][0] if prompts else None
        saved = self.edit_settings(page)
        if saved is None:
            return False
        self.set_settings(saved)
        return True

    def _ask(self, title: str, text: str) -> bool:  # pragma: no cover - a modal dialog
        buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        answer = QMessageBox.question(self, title, text, buttons, QMessageBox.StandardButton.Yes)
        return answer == QMessageBox.StandardButton.Yes

    def _edit_settings(self, page: str | None) -> Any:  # pragma: no cover - a modal dialog
        saved: list[Any] = []
        dialog = drawingsettings.DrawingSettingsDialog(
            self,
            self.settings,
            self.settings_problems,
            path=self.settings_path,
            page=page,
            on_saved=saved.append,
        )
        dialog.exec()
        return saved[-1] if saved else None

    def _pick_folder(self, start: str) -> str:  # pragma: no cover - a system dialog
        return QFileDialog.getExistingDirectory(self, "Where the drawing's files go", start)

    def showEvent(self, event: Any) -> None:  # noqa: N802 (Qt's name)
        super().showEvent(event)
        self._widen_preview()
        if not self._offered:
            self._offered = True
            QTimer.singleShot(0, self.offer_first_use)

    # ------------------------------------------------------------------ jobs
    def _run(
        self,
        kind: str,
        work: Callable[..., dict],
        gen: int = 0,
        *,
        on_progress: Callable[[Any], None] | None = None,
    ) -> int:
        """Start ``work(running, cancelled)`` in the pool; its result, with ``kind`` and
        ``gen`` (the request's number), reaches :meth:`_finished` on the UI thread. With
        ``on_progress``, ``work`` gets a third argument, ``emit``, whose values reach
        ``on_progress`` on the UI thread. Returns the job's number."""
        self._job_ids += 1
        number = self._job_ids
        running = threading.Event()

        def run(emit: Any, cancelled: Callable[[], bool]) -> dict:
            try:
                out = work(running, cancelled) if on_progress is None else work(running, cancelled, emit)
            except _Stale:
                out = {"stale": True}
            except ProcessStopped as exc:
                stale = exc.reason == "cancelled" or cancelled()
                out = {"stale": True} if stale else {"error": error_words(exc)}
            except Exception as exc:  # shown on the page, never raised in the pool
                out = {"stale": True} if cancelled() else {"error": error_words(exc)}
            return {**out, "kind": kind, "job": number, "gen": gen}

        job = Job(run)
        self._jobs[number] = (kind, job, running)
        job.signals.finished.connect(self._finished)
        if on_progress is not None:
            job.signals.progress.connect(on_progress)
        self.pool.start(job)
        return number

    def _cancel_jobs(self, kinds: Sequence[str]) -> int:
        """Cancel the jobs of ``kinds``: each stops before its next request, and a request
        of theirs in progress is ended (the child with it). How many were stopped there."""
        ended = 0
        if "preview" in kinds:
            self._requested = None  # the next change asks again
            self.preview_progress.hide()
        for _number, (kind, job, running) in list(self._jobs.items()):
            if kind not in kinds or job.cancelled:
                continue
            job.cancel()
            if running.is_set() and self.worker.cancel():
                ended += 1
        return ended

    @property
    def busy(self) -> bool:
        """Whether a job is in progress or a preview is waiting to be asked for."""
        return bool(self._jobs) or self.timer.isActive()

    def _finished(self, result: Any) -> None:
        if not isinstance(result, dict):
            return
        entry = self._jobs.pop(result.get("job"), None)
        if entry is None:
            return
        self._finished_jobs.append(entry[1])
        kind = result.get("kind")
        if kind == "probe":
            self._probed(result)
        elif kind == "preview":
            self._previewed(result)
        elif kind == "output":
            self._output_done(result)

    # ------------------------------------------------------------------ page 1: the probe
    def start_probe(self, configuration: str | None = None) -> None:
        """Read the part (``worker.probe``) in the pool; page 1 shows it."""
        self._cancel_jobs(("probe", "preview"))
        self._probe_gen += 1
        gen = self._probe_gen
        self.probe = None
        self.probe_error = None
        self.part_page.status_label.setText("Reading the part...")
        self._waiting_words()
        self.part_page.completeChanged.emit()
        worker, part = self.worker, self.part

        def work(running: threading.Event, cancelled: Callable[[], bool]) -> dict:
            if cancelled():
                raise _Stale()
            note = ""
            running.set()
            try:
                try:
                    probe = worker.probe(part, configuration)
                except ConfigurationNotFoundError:
                    if configuration is None:
                        raise
                    probe = worker.probe(part, None)
                    note = f"the part has no configuration {configuration}; its active one is drawn"
            finally:
                running.clear()
            return {"probe": probe, "note": note}

        self._run("probe", work, gen)

    def _probed(self, result: dict) -> None:
        if result.get("stale") or result.get("gen") != self._probe_gen:
            return
        if "error" in result:
            self.probe_error = result["error"]
            self.part_page.status_label.setText(f"The part could not be read: {result['error']}")
        else:
            self.probe = result["probe"]
            self.probe_note = result.get("note", "")
            self.part_page.show_probe(self.probe, self.probe_note, self.settings)
            self.title_page.show_assembly(self.is_assembly)
            if self.is_assembly and not self._views_touched:
                self.views_page.put_assembly_defaults()
        self.part_page.completeChanged.emit()
        self.changed(PART)

    @property
    def is_assembly(self) -> bool:
        """Whether the document read is an assembly."""
        return getattr(self.probe, "assembly", None) is not None

    def nextId(self) -> int:  # noqa: N802 (Qt's name)
        """The next page, past those an assembly has no use for (how a part is made and
        its dimensions)."""
        n = super().nextId()
        while self.is_assembly and n in ASSEMBLY_SKIPS:
            n = n + 1 if n + 1 <= OUTPUT else -1
        return n

    def configuration_chosen(self) -> None:
        name = self.part_page.configuration.currentText()
        if self.probe is not None and name and name != self.probe.configuration:
            self.start_probe(name)

    # ------------------------------------------------------------------ the request
    def chosen_unit(self) -> str | None:
        """``in`` or ``mm`` as clicked on page 1; None when nothing was clicked."""
        return self.part_page.chosen_unit()

    def units_option(self) -> str:
        """The drawing's ``units`` option: the unit clicked on page 1 for a part that
        states none (when Drawing Settings draw parts in their own unit), else ``part``."""
        if unit_question(self.probe, self.settings):
            return self.chosen_unit() or "part"
        return "part"

    def current_request(self) -> Request | None:
        """The request the pages make now, or None while page 1 is not complete."""
        if self.page_problems(PART):
            return None
        probe, s = self.probe, self.settings
        units = self.units_option()
        ticked = self.part_page.ticked_bodies()
        selected = [b.name for b in probe.bodies if b.selected]
        bodies = None if ticked == selected else tuple(ticked)
        faces = int(probe.counts.get("faces", 0)) if probe.counts else 0
        process = self.manufacturing_page.chosen_process()
        vp = self.views_page
        front = vp.front.currentData()
        scale = vp.scale.currentData()
        options = DrawingOptions(
            process=process,
            scheme=self.manufacturing_page.scheme.currentData(),
            detail=self.manufacturing_page.detail.currentData() or "full",
            units=units,
            views=self._views_option(process),
            front=None if front == AUTO else front,
            turn=0 if front == AUTO else int(vp.turn.currentData()),
            hidden=vp.hidden.isChecked(),
            tangent=vp.tangent.currentData(),
            sheet=vp.sheet.currentData(),
            scale=AUTO if scale in (None, AUTO) else (standards.parse_scale(scale) or AUTO),
            bodies=bodies,
            quality="draft" if faces > s.limits.draft_faces else "normal",
            configuration=probe.configuration,
        )
        fields = self.fields()
        return Request(self.part, options, tuple(sorted(fields.items())), s, self.edits())

    def _views_option(self, process: str) -> Any:
        """``auto`` when the ticks are Drawing Settings' Default Views for ``process``,
        else the views ticked (the front always)."""
        d = self.settings.defaults.views[settings_type(process)]
        vp = self.views_page
        ticked = vp.ticked()
        same = set(ticked) == set(d["views"]) - {"front"} and vp.isometric.isChecked() == bool(d["isometric"])
        if same:
            return AUTO
        return ("front", *ticked, *(("isometric",) if vp.isometric.isChecked() else ()))

    def fields(self) -> dict[str, str]:
        """The title block's and the process's fields as typed or chosen (``make``'s
        ``fields``); empty ones are left to the part."""
        tp, s = self.title_page, self.settings
        out: dict[str, str] = {}
        for key, edit in tp.edits.items():
            text = edit.text().strip()
            if text:
                out[key] = text.upper() if key == "revision" else text
        material = "" if self.is_assembly else tp.material.currentText().strip()
        if material:
            out["material"] = material_value(s, material)
        entry = None if self.is_assembly else self.material()
        if entry is not None and entry.get("heat_treatable") and tp.heat.text().strip():
            out["heat_treatment"] = tp.heat.text().strip()
        finish = tp.finish.currentText().strip()
        if self.is_assembly:
            pass  # an assembly's title block has no finish: its parts' drawings carry theirs
        elif tp.finish_default:
            # Untouched: the part's own finish stands when it states one (and until a preview
            # shows whether it does); a part that states none is drawn with the default, None.
            if tp.part_finish == "":
                out["finish"] = finish_callout(s, finish or none_finish(s))
        elif finish:
            out["finish"] = finish_callout(s, finish)
        drawn = tp.drawn_by_name(s)
        if drawn:
            out["drawn_by"] = drawn
        mp = self.manufacturing_page
        if mp.chosen_process() == "printed":
            if mp.process.currentText():
                out["process"] = mp.process.currentText()
            if mp.layer_height.text().strip():
                out["layer_height"] = mp.layer_height.text().strip()
        return out

    def material(self) -> dict | None:
        """The materials list entry of the material typed or chosen, else of the part's."""
        text = self.title_page.material.currentText().strip()
        if not text and self.answer is not None:
            f = dict(self.answer.drawing.title).get("material")
            text = f.text if f is not None else ""
        return material_entry(self.settings, text)

    def edits(self) -> tuple[tuple[str, tuple], ...]:
        """The edits after the make: the threads answered Tapped, the ends confirmed, and a
        printed part's extra notes."""
        out: list[tuple[str, tuple]] = []
        unit = None if self.answer is None else self.answer.drawing.options.units
        per_metre = 0.0254 if unit == "in" else 0.001
        for fid, (answer, designation, depth) in sorted(self.thread_answers.items()):
            spec = thread_spec(designation) if answer == "tapped" else None
            if spec is not None:
                out.append(("confirm_thread", (fid, spec, depth * per_metre if depth > 0 else None)))
        for fid in sorted(self.end_answers):
            out.append(("confirm_end", (fid, True)))
        notes = self.printed_notes()
        if notes:
            out.append(("notes", tuple(notes)))
        return tuple(out)

    def printed_notes(self) -> list[str]:
        """The lines a printed part adds to its notes: infill and walls, supports and
        post-processing, as typed (in capitals when Drawing Settings say so)."""
        mp = self.manufacturing_page
        if mp.chosen_process() != "printed":
            return []
        lines = []
        for label, edit in (
            ("INFILL AND WALLS", mp.infill),
            ("SUPPORTS", mp.supports),
            ("POST-PROCESSING", mp.post),
        ):
            text = edit.text().strip()
            if text:
                line = f"{label}: {text}"
                lines.append(line.upper() if self.settings.standard.upper_case_notes else line)
        return lines

    # ------------------------------------------------------------------ validation
    def page_problems(self, index: int) -> list[str]:
        """Why page ``index`` cannot go on, in words; empty when it can."""
        out: list[str] = []
        if index == PART:
            out = self.part_problems()
            if not out and unit_question(self.probe, self.settings) and self.chosen_unit() is None:
                out.append("the part states no unit: click Inch or Millimetre")
        elif index == TITLE:
            revision = self.title_page.edits["revision"].text().strip().upper()
            if revision and not standards.is_revision(revision):
                out.append(
                    f"{revision} is not a revision mark: one to four letters, without I, O, Q, S, X or Z"
                )
            entry = None if self.is_assembly else self.material()  # an assembly states no material
            if entry is not None and entry.get("heat_treatable") and not self.title_page.heat.text().strip():
                out.append(f"{entry['callout']} can be heat treated: say whether it is, and to what")
        elif index == MANUFACTURING:
            mp = self.manufacturing_page
            if mp.chosen_process() == "printed" and not mp.process.currentText():
                out.append("Drawing Settings > Printing lists no process to choose")
        elif index == OUTPUT:
            problem = self.folder_problem()
            if problem is not None:
                out.append(problem)
            if self._writing:
                out.append("the files are being written")
        return out

    def part_problems(self) -> list[str]:
        """Why the part cannot be drawn yet, the unit aside: it is being read, could not
        be read or is refused, or no body is ticked."""
        if self.probe_error is not None:
            return [f"the part could not be read: {self.probe_error}"]
        if self.probe is None:
            return ["the part is being read"]
        if self.probe.refused is not None:
            return [f"SolidSeas cannot draw this part: {self.probe.refused}"]
        if self.probe.bodies and not self.part_page.ticked_bodies():
            return ["tick at least one body to draw"]
        return []

    def validate_page(self, index: int) -> bool:
        if index == OUTPUT:
            if self.written is not None:
                return True  # written: Finish closes
            self.folder_changed()
        return not self.page_problems(index)

    def folder_problem(self) -> str | None:
        """Why the files must not be written in the chosen folder (12.6), or None."""
        folder = self.output_page.folder.text().strip()
        if not folder:
            return "choose a folder"
        problem = document.folder_problem(folder, self.opened)
        return None if problem is None else f"{problem}. Choose another folder."

    # ------------------------------------------------------------------ changes
    def refresh(self, index: int | None = None) -> None:
        """Page ``index`` (every page when None) says again what it lacks."""
        if index == TITLE or index is None:
            self._show_title_notes()
        if index == MANUFACTURING or index is None:
            self._show_figures()
        for page in self.pages:
            page.completeChanged.emit()

    def changed(self, index: int | None) -> None:
        """A control of page ``index`` changed: the pages say what they now lack, and the
        preview is asked for again a moment (:attr:`preview_delay_ms`) after the last
        change."""
        self.refresh(index)
        self.timer.start(self.preview_delay_ms)

    def process_chosen(self) -> None:
        self._process_touched = True
        self._process_follows()

    def _process_follows(self) -> None:
        """What follows the manufacturing type: the printing controls, and the scheme and
        Default Views of the type unless the user chose them."""
        process = self.manufacturing_page.chosen_process()
        self.manufacturing_page.printed_box.setVisible(process == "printed")
        if not self._scheme_touched:
            self._put_scheme(process)
        if not self._views_touched:
            self.views_page.put_defaults(self.settings, process)
        self.changed(MANUFACTURING)

    def detail_chosen(self) -> None:
        self._detail_touched = True
        self.changed(MANUFACTURING)

    def scheme_chosen(self) -> None:
        self._scheme_touched = True
        self.changed(MANUFACTURING)

    def views_changed(self, *, touched: bool) -> None:
        if touched:
            self._views_touched = True
        self.views_page.turn.setEnabled(self.views_page.front.currentData() != AUTO)
        self.changed(VIEWS)

    def _put_scheme(self, process: str) -> None:
        scheme = self.settings.gdt.scheme.get(settings_type(process), "datum")
        box = self.manufacturing_page.scheme
        box.blockSignals(True)
        box.setCurrentIndex(max(box.findData(scheme), 0))
        box.blockSignals(False)

    def suggestion(self) -> tuple[str, str]:
        """The manufacturing type SolidSeas suggests and why (10.6): 3D printed for a
        printing material, Turned for a part the preview found turned, else Machined."""
        entry = self.material()
        if entry is not None and list(entry.get("types") or ()) == ["printed"]:
            return "printed", f"{entry['callout']} is a printing material in your materials list"
        if self.turned_reason:
            return "turned", self.turned_reason
        return "machined", "nothing about the part says otherwise"

    def _follow_suggestion(self) -> None:
        """Take the suggested type while the user has chosen none."""
        if self._process_touched:
            return
        mp = self.manufacturing_page
        process, _why = self.suggestion()
        if process != mp.chosen_process():
            mp.choose(process)
            self._process_follows()

    def _show_title_notes(self) -> None:
        tp, s = self.title_page, self.settings
        text = tp.material.currentText().strip()
        entry = material_entry(s, text)
        if text and entry is None:
            tp.material_note.setText(
                f"{text} is not in the materials list: it prints as typed, and Release asks you to map it "
                "or accept it as typed."
            )
        elif entry is not None:
            spec = f", {entry['specification']}" if entry.get("specification") else ""
            tp.material_note.setText(f"From the materials list: {entry['callout']}{spec}")
        else:
            part = self.material()
            part_text = None
            if self.answer is not None:
                f = dict(self.answer.drawing.title).get("material")
                part_text = f.text if f is not None else None
            if part_text and part is None:
                tp.material_note.setText(
                    f"The part's material {part_text} is not in the materials list: map it in Drawing "
                    "Settings, or accept it as typed at release."
                )
            else:
                tp.material_note.setText("Empty: the part's own material, mapped through the materials list.")
        heat = self.material()
        asked = heat is not None and bool(heat.get("heat_treatable"))
        tp.heat.setVisible(asked)
        tp.heat_label.setVisible(asked)
        finish = tp.finish.currentText().strip()
        tp.finish_note.setText(f"Prints as: {finish_callout(s, finish)}" if finish else "")
        problems = self.page_problems(TITLE)
        tp.problems_label.setText("\n".join(f"To go on: {p}" for p in problems))
        tp.problems_label.setVisible(bool(problems))
        process, why = self.suggestion()
        words = f"Suggested: {PROCESS_LABELS[process]}, because {why}."
        self.manufacturing_page.suggestion_label.setText(words)

    def _show_figures(self) -> None:
        mp = self.manufacturing_page
        figures = mp.chosen_figures(self.settings)
        mp.figures_label.setText(process_words(figures) if figures is not None else "")

    def _page_shown(self, index: int) -> None:
        self._widen_preview()
        if index == MANUFACTURING:
            self._follow_suggestion()  # the suggestion is taken until the user chooses
        self.request_preview()
        if index == OUTPUT:
            self.folder_changed()

    # ------------------------------------------------------------------ the preview
    def request_preview(self) -> bool:
        """Ask for the preview of the pages as they are, cancelling one in progress for an
        older request; whether a request was started."""
        self.timer.stop()
        request = self.current_request()
        if request is None:
            self._waiting_words()
            return False
        if request == self._requested:
            return False
        self.cancelled_requests += self._cancel_jobs(("preview",))
        self._requested = request
        self._gen += 1
        gen = self._gen
        self.preview_status.setText("Making the preview...")
        self.dimensions_page.status_label.setText("Making the preview...")
        self.preview_progress.setValue(0)
        self.preview_progress.setFormat("Starting the drawing process...")
        self.preview_progress.show()
        worker = self.worker

        def work(running: threading.Event, cancelled: Callable[[], bool], emit: Any) -> dict:
            def progress(info: dict) -> None:
                emit({**info, "gen": gen})

            answer = build_drawing(worker, request, cancelled, running, progress)
            with self._lock:
                before, self._built = self._built, (request, answer)
            old = None if before is None else before[1].drawing.id
            if old is not None and old != answer.drawing.id and not cancelled():
                try:  # the child keeps the run of the latest preview only
                    worker.forget(old)
                except Exception:  # noqa: BLE001 - best effort: the child bounds what it keeps
                    pass
            return {"answer": answer, "request": request}

        self._run("preview", work, gen, on_progress=self._preview_progress)
        return True

    def _waiting_words(self) -> None:
        """What the preview waits for while page 1 cannot make a request: the part being
        read, or an answer on page 1."""
        if self.probe is None and self.probe_error is None:
            self.preview_status.setText("Reading the part...")
            self.preview_progress.setValue(0)
            self.preview_progress.setFormat("Reading the part...")
            self.preview_progress.show()
            return
        self.preview_progress.hide()
        if self.probe_error is not None:
            self.preview_status.setText(f"No preview: the part could not be read: {self.probe_error}")
        else:
            problems = self.page_problems(PART)
            self.preview_status.setText(
                "The preview starts once page 1 is complete" + (f": {problems[0]}" if problems else ".")
            )

    def _widen_preview(self) -> None:
        """Let the preview take the room the pages do not need. QWizard holds its side
        widget in a label of its own (made once it lays itself out) that keeps one width;
        that label is made to expand, ahead of the pages (:data:`PREVIEW_STRETCH`), which
        keep :data:`PAGE_WIDTH`, so a larger window shows a larger sheet."""
        holder = self.preview_panel.parentWidget()
        if holder is None or holder is self:
            return
        policy = holder.sizePolicy()
        if (
            policy.horizontalPolicy() == QSizePolicy.Policy.Expanding
            and policy.horizontalStretch() == PREVIEW_STRETCH
        ):
            return
        wide = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        wide.setHorizontalStretch(PREVIEW_STRETCH)
        holder.setSizePolicy(wide)

    def view_larger(self) -> QDialog:
        """The preview in a window of its own, which can be made as large as the screen: a
        second view of the same sheet, so it shows each new preview as it comes."""
        if self.larger is None:
            win = QDialog(self)
            win.setWindowTitle(f"Preview of {os.path.basename(self.part)}")
            win.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
            view = SheetView(self.scene)
            box = QVBoxLayout(win)
            box.setContentsMargins(0, 0, 0, 0)
            box.addWidget(view)
            screen = self.screen() or QApplication.primaryScreen()
            if screen is not None:
                free = screen.availableGeometry()
                win.resize(int(free.width() * SCREEN_SHARE), int(free.height() * SCREEN_SHARE))
            win.view = view  # type: ignore[attr-defined]
            self.larger = win
        self.larger.show()
        self.larger.raise_()
        self.larger.activateWindow()
        self.larger.view.fit()  # type: ignore[attr-defined]
        return self.larger

    def _preview_progress(self, info: Any) -> None:
        """A stage of the preview in progress started: the bar moves to it and says it."""
        if not isinstance(info, dict) or info.get("gen") != self._gen:
            return
        stage = info.get("stage")
        if stage in STAGE_START:
            self.preview_progress.setValue(STAGE_START[stage])
            self.preview_progress.setFormat(f"{STAGE_WORDS[stage]}...")

    def _previewed(self, result: dict) -> None:
        if result.get("gen") == self._gen:
            self.preview_progress.hide()
        if result.get("stale") or result.get("gen") != self._gen:
            return
        if "error" in result:
            self.preview_error = result["error"]
            self.preview_status.setText(f"The preview could not be made: {result['error']}")
            self.dimensions_page.status_label.setText(f"No drawing yet: {result['error']}")
            self._requested = None  # asked again on the next change
            return
        self.preview_error = None
        self.answer, self.answer_request = result["answer"], result["request"]
        self.turned_reason = getattr(self.answer, "turned", None)
        self._show_answer(self.answer)
        if self.currentId() == MANUFACTURING:
            self._follow_suggestion()  # the part turned out to be turned while the page shows

    def _show_answer(self, answer: Any) -> None:
        sheet = answer.drawing.sheet
        if sheet is None:
            self.preview_status.setText("The drawing was made, but its sheet cannot be shown here.")
        else:
            first = not self.scene.owners()
            self.scene.set_sheet(sheet)
            if first:
                self.view.fit()
            self.larger_button.setEnabled(True)
            self.preview_status.setText(
                "PRELIMINARY, as the drawing will be written. It is made again a moment after you stop "
                "changing options."
            )
        self.title_page.show_part(dict(answer.drawing.title))
        self.views_page.chosen_label.setText(
            front_words(answer.drawing.options)
            + f" Sheet {answer.drawing.options.sheet}, scale "
            + (
                standards.scale_text(answer.drawing.options.scale)
                if isinstance(answer.drawing.options.scale, tuple)
                else "automatic"
            )
            + "."
        )
        self._show_dimensions(answer)
        self.refresh(None)  # showing the answer is not a change of the user's: no new preview
        self.folder_changed()

    def _show_dimensions(self, answer: Any) -> None:
        dp = self.dimensions_page
        dp.status_label.setText("From the preview.")
        drawing = answer.drawing
        counts: Counter = Counter()
        for d in drawing.dimensions:
            if getattr(d, "state", "shown") != "removed":
                for fid in d.features:
                    counts[fid] += 1
        dp.features.clear()
        groups: dict[str, list[Any]] = {}
        for rec in drawing.features:
            groups.setdefault(rec.descriptor.type, []).append(rec)
        for kind, records in groups.items():
            top = QTreeWidgetItem([f"{kind} ({len(records)})", ""])
            for rec in records:
                top.addChild(QTreeWidgetItem([rec.id, str(counts.get(rec.id, 0))]))
            dp.features.addTopLevelItem(top)
        dp.features.expandAll()

        dp.threads.setRowCount(0)
        dp.rows = {}
        known = set()
        for row, cand in enumerate(answer.thread_candidates):
            fid = str(cand.get("feature", ""))
            known.add(fid)
            threads = [str(t) for t in cand.get("threads", ())]
            count = int(cand.get("count", 1) or 1)
            what = f"{count} holes" if count != 1 else "hole"
            dp.threads.insertRow(row)
            dp.threads.setItem(row, 0, QTableWidgetItem(f"{fid} ({what})"))
            dp.threads.setItem(row, 1, QTableWidgetItem(f"Ø{float(cand.get('diameter_mm', 0.0)):.2f} mm"))
            answer_box, thread_box = QComboBox(), QComboBox()
            for value in ANSWERS:
                answer_box.addItem(ANSWER_LABELS[value], value)
            thread_box.addItems(threads)
            depth = QDoubleSpinBox()
            depth.setDecimals(3)
            depth.setRange(0.0, 1000.0)
            depth.setSpecialValueText("through, or not given")
            depth.setSuffix(f" {drawing.options.units}")
            had = self.thread_answers.get(fid)
            if had is not None:
                answer_box.setCurrentIndex(ANSWERS.index(had[0]))
                if had[1] in threads:
                    thread_box.setCurrentIndex(threads.index(had[1]))
                depth.setValue(had[2])
            elif cand.get("answered") and cand.get("confirmed"):
                answer_box.setCurrentIndex(ANSWERS.index("tapped"))
            thread_box.setEnabled(answer_box.currentData() == "tapped")
            depth.setEnabled(answer_box.currentData() == "tapped")
            dp.threads.setCellWidget(row, 2, answer_box)
            dp.threads.setCellWidget(row, 3, thread_box)
            dp.threads.setCellWidget(row, 4, depth)
            dp.rows[fid] = (answer_box, thread_box, depth)
            answer_box.currentIndexChanged.connect(lambda _i, f=fid: self.thread_answered(f))
            thread_box.currentIndexChanged.connect(lambda _i, f=fid: self.thread_answered(f))
            depth.valueChanged.connect(lambda _v, f=fid: self.thread_answered(f))
        for fid in list(self.thread_answers):
            if fid not in known:
                del self.thread_answers[fid]
        dp.threads.setVisible(bool(known))
        dp.threads_none.setVisible(not known)

        by_dimension = {d.id: d for d in drawing.dimensions}
        dp.ends.blockSignals(True)
        dp.ends.clear()
        rows: dict[str, str] = {}
        for c in answer.checks:
            if CONFIRM_END not in c.fixes:
                continue
            d = by_dimension.get(c.item)
            fid = d.features[0] if d is not None and d.features else None
            if fid is not None:
                rows.setdefault(fid, c.message)
        for fid, words in self.end_answers.items():
            rows.setdefault(fid, words)
        for fid, words in rows.items():
            item = QListWidgetItem(f"{fid}: {words}")
            item.setData(Qt.ItemDataRole.UserRole, (fid, words))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if fid in self.end_answers else Qt.CheckState.Unchecked)
            dp.ends.addItem(item)
        if not rows:
            dp.ends.addItem("None: every hole's ends are clear.")
        dp.ends.blockSignals(False)

        dp.coverage_label.setText("\n".join(coverage_lines(answer.coverage)))
        dp.checks_label.setText(checks_words(answer.checks))
        dp.checks_list.clear()
        order = {"error": 0, "warning": 1, "information": 2}
        for c in sorted(answer.checks, key=lambda c: order.get(c.level, 3))[:MAX_CHECK_ROWS]:
            dp.checks_list.addItem(f"{c.level}: {c.message}")

    def thread_answered(self, fid: str) -> None:
        row = self.dimensions_page.rows.get(fid)
        if row is None:
            return
        answer_box, thread_box, depth = row
        answer = answer_box.currentData()
        thread_box.setEnabled(answer == "tapped")
        depth.setEnabled(answer == "tapped")
        if answer == "unanswered":
            self.thread_answers.pop(fid, None)
        else:
            self.thread_answers[fid] = (answer, thread_box.currentText(), float(depth.value()))
        self.changed(DIMENSIONS)

    def end_answered(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        fid, words = data
        if item.checkState() == Qt.CheckState.Checked:
            self.end_answers[fid] = words
        else:
            self.end_answers.pop(fid, None)
        self.changed(DIMENSIONS)

    # ------------------------------------------------------------------ page 4: defaults
    def make_defaults(self) -> bool:
        """Save the views, isometric, hidden lines, tangent edges, front direction and
        sheet size as Drawing Settings' defaults for the chosen manufacturing type
        (``save_settings``; a turned part's are the machined ones); whether they were
        saved."""
        vp, s = self.views_page, self.settings
        process = settings_type(self.manufacturing_page.chosen_process())
        views = {k: dict(v) for k, v in s.defaults.views.items()}
        views[process] = {
            "views": ["front", *vp.ticked()],
            "isometric": vp.isometric.isChecked(),
            "hidden": vp.hidden.isChecked(),
            "tangent": vp.tangent.currentData(),
            "front": vp.front.currentData(),
        }
        try:
            new = drawing_settings.with_value(s, "defaults", "views", views)
            new = drawing_settings.with_value(new, "sheets", "size", vp.sheet.currentData())
            where = drawing_settings.save_settings(new, self.settings_path)
        except (OSError, SolidSeasError) as exc:
            vp.defaults_label.setText(f"The defaults were not saved: {error_words(exc)}")
            return False
        self._views_touched = True  # the controls already show them
        self.set_settings(new)
        kind = (
            "machined (milled) and turned (lathe)"
            if process == "machined"
            else PROCESS_LABELS[process].lower()
        )
        vp.defaults_label.setText(f"Saved in {where} as the defaults for {kind} parts.")
        return True

    # ------------------------------------------------------------------ page 6: output
    def choose_folder(self) -> None:
        chosen = self.pick_folder(self.output_page.folder.text().strip() or os.path.dirname(self.part))
        if chosen:
            self.output_page.folder.setText(os.path.normpath(chosen))

    def kinds(self) -> list[str]:
        op = self.output_page
        return [k for k, box in (("pdf", op.pdf_box), ("dxf", op.dxf_box)) if box.isChecked()]

    def folder_changed(self) -> None:
        """Check the folder (12.6) and say which names the files will get."""
        op = self.output_page
        problem = self.folder_problem()
        op.folder_label.setText("" if problem is None else f"Refused: {problem}")
        op.folder_label.setVisible(problem is not None)
        op.names_label.setText(self.names_words(None if problem is not None else op.folder.text().strip()))
        op.completeChanged.emit()

    def names_words(self, folder: str | None) -> str:
        """The names the files will get in ``folder``, from the latest preview: a name
        taken by another file gets the next free one, said here."""
        if self.answer is None:
            return "The names follow the drawing number once the preview is made."
        d = self.answer.drawing
        lines = [f"Drawing: {document.drawing_file_name(d)}"]
        lines += [f"{kind.upper()}: {document.export_name(d, kind)}" for kind in self.kinds()]
        if folder is not None:
            try:
                taken = [document.save_target(d, os.path.join(folder, document.drawing_file_name(d)))]
                taken += [document.export_target(d, folder, kind) for kind in self.kinds()]
            except (OSError, SolidSeasError) as exc:
                lines.append(f"The names could not be checked: {error_words(exc)}")
            else:
                lines += [t.words for t in taken if t.renamed]
        return "\n".join(lines)

    def accept(self) -> None:
        """Finish: write the files (see the module notes), then close."""
        if self.written is not None:
            super().accept()
            return
        if self._writing:
            return
        op = self.output_page
        self.folder_changed()
        problems = self.page_problems(OUTPUT)
        request = self.current_request()
        if request is None:
            problems.append("the part is not ready: see page 1")
        if problems:
            op.status_label.setText("Nothing was written: " + "; ".join(problems))
            return
        folder = op.folder.text().strip()
        kinds = self.kinds()
        open_editor = op.open_editor.isChecked()
        self.timer.stop()
        self._cancel_jobs(("preview", "probe"))
        self._writing = True
        op.status_label.setText("Writing the drawing...")
        op.completeChanged.emit()
        worker, part, opened = self.worker, self.part, self.opened

        def work(running: threading.Event, cancelled: Callable[[], bool]) -> dict:
            with self._lock:
                built = self._built
            if built is not None and built[0] == request:
                answer = built[1]
            else:
                answer = build_drawing(worker, request, cancelled, running)
            exported: dict[str, bytes] = {}
            for kind in kinds:
                if cancelled():
                    raise _Stale()
                running.set()
                try:
                    exported[kind] = worker.export(answer, kind).data
                finally:
                    running.clear()
            if cancelled():
                raise _Stale()
            written = write_drawing(answer, folder, exported, part, opened)
            return {"written": written, "open_editor": open_editor}

        self._run("output", work)

    def _output_done(self, result: dict) -> None:
        self._writing = False
        op = self.output_page
        if result.get("stale"):
            op.status_label.setText("Writing was cancelled: nothing more was written.")
        elif "error" in result:
            op.status_label.setText(f"The drawing was not written: {result['error']}")
        else:
            self.written = written = result["written"]
            words = " ".join(written.words)
            names = ", ".join(os.path.basename(f) for f in written.files)
            op.status_label.setText(f"Written: {names}. {words}".strip())
            self.drawing_written.emit(written.path, bool(result.get("open_editor")))
            super().accept()
            return
        op.completeChanged.emit()

    def done(self, result: int) -> None:  # noqa: D401 - Qt's name
        """Closing, by Finish or Cancel: what is still asked of the child is cancelled."""
        self.timer.stop()
        if self.written is None:
            self._cancel_jobs(("probe", "preview", "output"))
        super().done(result)


__all__ = [
    "ANSWERS",
    "PAGE_TITLES",
    "PREVIEW_DELAY_MS",
    "DrawingWizard",
    "Request",
    "Written",
    "build_drawing",
    "checks_words",
    "coverage_lines",
    "error_words",
    "evidence_words",
    "finish_callout",
    "material_entry",
    "material_value",
    "process_words",
    "size_words",
    "thread_spec",
    "unit_question",
    "unit_words",
    "write_drawing",
]
