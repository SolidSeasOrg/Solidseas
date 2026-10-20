"""Guided drawings (``docs/DRAWINGS.md`` 10.4b): the New Drawing wizard's choices asked
as a few plain questions, one at a time, each with a sentence on why it matters.

:class:`GuidedWizard` is a :class:`.drawingwizard.DrawingWizard` with its own pages in
place of the six. Everything else is the wizard's: the part read in the drawing process
(``probe``), the preview beside the pages, first use, the request and Finish, which
writes through ``write_drawing`` and emits ``drawing_written(path, True)`` so the
editor opens. The six pages are kept, unshown, as the store of the answers: each guided
question sets their controls, so the request is made exactly as the wizard makes it.
The title block page is the wizard's own, shown with a guided heading.

The questions, in order:

1. **What is the drawing for?** (:data:`PURPOSES`) chooses how the part is made and
   the detail level: a quote or a customer's look is a machined part at Simplified, a
   3D print a printed part at Simplified (with the printing process from Drawing
   Settings), plain sizes a machined part at Complex, and a machine shop a machined
   part Fully defined. An assembly is not asked: its drawing has no dimensions.
2. **Which views?** The projected views and the isometric, from Drawing Settings'
   Default Views for the way the part is made.
3. **Which unit?** Inch or millimetre: as Drawing Settings fix it, else as the part
   states it, else SolidSeas' guess when its evidence is clear (else one must be
   clicked).
4. **How much should it dimension?** The detail level, as the first answer set it. A
   level below Fully defined is drawn with plus and minus tolerances; Fully defined
   takes the tolerancing scheme Drawing Settings give the way the part is made. An
   assembly skips this question.
5. **Are any of these holes threaded?** Asked only of a part with thread candidates:
   the holes and hole patterns whose size is a tap drill, as the preview finds them
   (the wizard's page 5 lists the same). Each is a plain hole or one of the threads
   its drill taps, and the answer is set on the wizard's own thread table, so the
   ``confirm_thread`` edits are the wizard's. The page waits while the preview is
   being made, and is skipped once it shows no candidate. An assembly skips it.
6. **The title block**, the wizard's page.
7. **What will be made**: the answers, the title block as the preview shows it, where
   the files go, a PDF or DXF beside the drawing if ticked, and a button for another
   folder.

A Guided drawing is an ordinary drawing: its options carry no mode, as an Expert one's
do not, and Update from Model treats it the same way.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
    QWizardPage,
)

from .drawingwizard import (
    ANSWERS,
    MANUFACTURING,
    OUTPUT,
    PAGE_WIDTH,
    PART,
    TITLE,
    UNIT_NAMES,
    VIEW_CHOICES,
    DrawingWizard,
    _label,
    evidence_words,
    process_words,
    size_words,
    unit_question,
)

# The guided pages' ids, past the wizard's six (whose title block page is shown too)
PURPOSE, VIEWS, UNITS, DETAIL, SUMMARY, THREADS = 10, 11, 12, 13, 14, 15
ORDER = (PURPOSE, VIEWS, UNITS, DETAIL, THREADS, TITLE, SUMMARY)


@dataclass(frozen=True)
class Purpose:
    """An answer to "What is the drawing for?": its words, and the manufacturing type
    and detail level it chooses."""

    key: str
    label: str
    words: str
    process: str
    detail: str


PURPOSES = (
    Purpose(
        "quote",
        "To show a customer, or to get a quote",
        "The overall size and the holes, so someone can see what the part is and price it. "
        "The model defines everything else.",
        "machined",
        "simplified",
    ),
    Purpose(
        "print",
        "To have it 3D printed",
        "The printer works from the model, so the drawing gives the key sizes and the tolerances of "
        "the printing process you choose.",
        "printed",
        "simplified",
    ),
    Purpose(
        "plain",
        "To have it made from plain sizes",
        "Every feature sized and located, with plus and minus tolerances and no GD&T: easy to read "
        "for a small shop, or to make the part yourself.",
        "machined",
        "complex",
    ),
    Purpose(
        "shop",
        "To have it machined in a shop",
        "The complete engineering drawing: every feature sized and located from datums, with GD&T, "
        "and checked to define the part fully.",
        "machined",
        "full",
    ),
)
PURPOSE_BY_KEY = {p.key: p for p in PURPOSES}
# The purpose a new drawing starts from: the one of Drawing Settings' default detail level
DEFAULT_PURPOSE = {"simplified": "quote", "complex": "plain", "full": "shop"}

DETAILS = (
    (
        "simplified",
        "The key sizes",
        "The overall size, and each hole and boss by size. Nothing is located; a note says the model "
        "defines what is not dimensioned.",
    ),
    (
        "complex",
        "Every feature, with plus and minus tolerances",
        "Every feature sized and located, each size with its own plus and minus tolerance. No datums "
        "or GD&T.",
    ),
    (
        "full",
        "Every feature, fully defined",
        "Every feature sized and located from datums A, B and C, with GD&T, and checked by SolidSeas "
        "to define the part fully.",
    ),
)
DETAIL_NAMES = {key: label for key, label, _words in DETAILS}

VIEW_LABELS = {"top": "Top", "right": "Right side", "left": "Left side", "bottom": "Bottom", "back": "Back"}

QUESTIONS = {
    PURPOSE: (
        "What is the drawing for?",
        "Your answer decides how the part is made and how much the drawing says. A quote needs a few "
        "sizes; a machine shop needs every one.",
    ),
    VIEWS: (
        "Which views should the sheet show?",
        "Each view looks at the part from one side. The front is always drawn; the others show what "
        "the front cannot.",
    ),
    UNITS: (
        "Which unit should the sizes be in?",
        "Use the unit of the person who will read the drawing. Every size and tolerance is given in it.",
    ),
    DETAIL: (
        "How much should the drawing dimension?",
        "Your first answer chose this. Fewer sizes make a drawing quicker to read; more make it "
        "complete enough to make the part from.",
    ),
    THREADS: (
        "Are any of these holes threaded?",
        "These holes are the size of a tap drill, so they may be meant to take a screw. The drawing "
        "calls out a thread only when you choose one here; otherwise each is made as a plain hole.",
    ),
    TITLE: (
        "What should the title block say?",
        "The title block in the corner of the sheet names the part, its drawing number and revision, "
        "and who drew it. Leave a field empty to use the part's own value, shown greyed once the "
        "preview is made.",
    ),
    SUMMARY: (
        "Ready to make the drawing",
        "Check what will be made. Finish writes the drawing and opens it in the editor, where you can "
        "move dimensions, add more and export it.",
    ),
}
ASSEMBLY_PURPOSE = (
    "This is an assembly. Its drawing shows its views, a parts list and a balloon on each part, with "
    "its overall size for reference. How each part is made and dimensioned belongs on that part's own "
    "drawing, so there is nothing to choose here."
)
ISOMETRIC_WORDS = "Isometric: a 3D picture that helps someone see the part at a glance"
PRELIMINARY_WORDS = "Everything is written as PRELIMINARY until you release the drawing in the editor."
NOBODY = "Drawn by: nobody yet (add people in Drawing Settings)"
NO_PROCESS = "Add a printing process under Drawing Settings > Printing to choose this."
NO_THREAD = "No, a plain hole"
THREADS_WAITING = "Looking for holes that may be threaded, while the preview is made. This takes a moment."
THREADS_NONE = "No hole in this part is the size of a tap drill, so there is nothing to answer here."
THREADS_FAILED = (
    "The holes could not be checked, because the preview was not made. They will be drawn as plain "
    "holes; use Expert to call out a thread."
)
THREADS_NOTE = (
    "Choose a thread only when the hole is meant to be tapped: the shop cuts the thread you choose. "
    "Not sure? Ask whoever designed the part, since a thread cannot be added in the editor later."
)


def hole_words(candidate: Any, unit: str | None) -> str:
    """A thread candidate in words, its size in the drawing's unit: ``4 holes, Ø5.00 mm
    (f-1)``."""
    count = int(candidate.get("count", 1) or 1)
    mm = float(candidate.get("diameter_mm", 0.0))
    size = f"{mm / 25.4:.3f} in" if unit == "in" else f"{mm:.2f} mm"
    what = f"{count} holes" if count != 1 else "1 hole"
    return f"{what}, Ø{size} ({candidate.get('feature', '')})"


def views_words(ticked: list[str], isometric: bool) -> str:
    """The views drawn, in words: the front always, then the others ticked."""
    names = ["front", *ticked]
    text = ", ".join(names[:-1]) + f" and {names[-1]}" if len(names) > 1 else names[0]
    text = text[0].upper() + text[1:]
    return text + (", and an isometric" if isometric else "")


class GuidedPage(QWizardPage):
    """A guided question: its words, and its completeness as the wizard decides it
    (:meth:`GuidedWizard.guided_problems`)."""

    def __init__(self, wizard: GuidedWizard, index: int) -> None:
        super().__init__()
        self.w = wizard
        self.index = index
        title, why = QUESTIONS[index]
        self.setTitle(title)
        self.setSubTitle(why)
        self.setMinimumWidth(PAGE_WIDTH)

    def isComplete(self) -> bool:  # noqa: N802 (Qt's name)
        return not self.w.guided_problems(self.index)

    def validatePage(self) -> bool:  # noqa: N802 (Qt's name)
        return self.w.validate_guided(self.index)

    def enter(self) -> None:
        """Show the answers as they stand, each time the page is shown."""


class PurposePage(GuidedPage):
    def __init__(self, wizard: GuidedWizard) -> None:
        super().__init__(wizard, PURPOSE)
        self.status_label = _label(note=True)
        self.size_label = _label()
        self.assembly_label = _label(ASSEMBLY_PURPOSE)
        self.assembly_label.hide()
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QRadioButton] = {}
        self.words: dict[str, Any] = {}
        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addWidget(self.size_label)
        layout.addWidget(self.assembly_label)
        self.choices = QWidget()
        choices = QVBoxLayout(self.choices)
        choices.setContentsMargins(0, 0, 0, 0)
        for k, purpose in enumerate(PURPOSES):
            button = QRadioButton(purpose.label)
            words = _label(purpose.words, note=True)
            words.setContentsMargins(24, 0, 0, 6)
            self.group.addButton(button, k)
            self.buttons[purpose.key] = button
            self.words[purpose.key] = words
            choices.addWidget(button)
            choices.addWidget(words)
        self.process = QComboBox()
        self.figures_label = _label(note=True)
        self.no_process_label = _label(NO_PROCESS, note=True)
        self.printing = QWidget()  # shown once 3D printing is chosen
        printing = QFormLayout(self.printing)
        printing.setContentsMargins(24, 0, 0, 0)
        printing.addRow("Printing process:", self.process)
        printing.addRow("", self.figures_label)
        choices.addWidget(self.printing)
        choices.addWidget(self.no_process_label)
        layout.addWidget(self.choices)
        layout.addStretch(1)
        self.group.idClicked.connect(lambda k: wizard.purpose_chosen(PURPOSES[k].key))
        self.process.currentIndexChanged.connect(lambda _i: wizard.printing_chosen())

    def chosen(self) -> str | None:
        return next((key for key, b in self.buttons.items() if b.isChecked()), None)


class ViewsPage(GuidedPage):
    def __init__(self, wizard: GuidedWizard) -> None:
        super().__init__(wizard, VIEWS)
        self.boxes: dict[str, QCheckBox] = {v: QCheckBox(VIEW_LABELS[v]) for v in VIEW_CHOICES}
        self.isometric = QCheckBox(ISOMETRIC_WORDS)
        layout = QVBoxLayout(self)
        layout.addWidget(_label("Front: always drawn, looking at the side SolidSeas finds shows the most."))
        for box in self.boxes.values():
            layout.addWidget(box)
        layout.addWidget(self.isometric)
        layout.addWidget(
            _label(
                "These start as your Default Views in Drawing Settings for parts made this way. "
                "Most parts need the front, the top and one side.",
                note=True,
            )
        )
        layout.addStretch(1)
        for name, box in self.boxes.items():
            box.toggled.connect(lambda on, n=name: wizard.view_ticked(n, on))
        self.isometric.toggled.connect(lambda on: wizard.view_ticked("isometric", on))

    def enter(self) -> None:
        vp = self.w.views_page
        pairs = [(self.boxes[n], vp.views[n]) for n in VIEW_CHOICES] + [(self.isometric, vp.isometric)]
        for mine, theirs in pairs:
            mine.blockSignals(True)
            mine.setChecked(theirs.isChecked())
            mine.blockSignals(False)


class UnitsPage(GuidedPage):
    def __init__(self, wizard: GuidedWizard) -> None:
        super().__init__(wizard, UNITS)
        self.inch = QRadioButton("Inch")
        self.mm = QRadioButton("Millimetre")
        self.group = QButtonGroup(self)
        self.group.addButton(self.inch)
        self.group.addButton(self.mm)
        self.source_label = _label(note=True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.inch)
        layout.addWidget(self.mm)
        layout.addWidget(self.source_label)
        layout.addStretch(1)
        self.inch.clicked.connect(lambda: wizard.unit_chosen("in"))
        self.mm.clicked.connect(lambda: wizard.unit_chosen("mm"))

    def enter(self) -> None:
        unit = self.w.chosen_unit()
        self.group.setExclusive(False)  # so neither may be checked until one is chosen
        self.inch.setChecked(unit == "in")
        self.mm.setChecked(unit == "mm")
        self.group.setExclusive(True)
        self.source_label.setText(self.w.unit_source_words())


class DetailPage(GuidedPage):
    def __init__(self, wizard: GuidedWizard) -> None:
        super().__init__(wizard, DETAIL)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QRadioButton] = {}
        layout = QVBoxLayout(self)
        for k, (key, label, words) in enumerate(DETAILS):
            button = QRadioButton(label)
            note = _label(words, note=True)
            note.setContentsMargins(24, 0, 0, 6)
            self.group.addButton(button, k)
            self.buttons[key] = button
            layout.addWidget(button)
            layout.addWidget(note)
        self.scheme_label = _label(note=True)
        layout.addWidget(self.scheme_label)
        layout.addStretch(1)
        self.group.idClicked.connect(lambda k: wizard.detail_answered(DETAILS[k][0]))

    def enter(self) -> None:
        detail = self.w.manufacturing_page.detail.currentData()
        for key, button in self.buttons.items():
            button.setChecked(key == detail)
        self.scheme_label.setText(self.w.scheme_words())


class ThreadsPage(GuidedPage):
    def __init__(self, wizard: GuidedWizard) -> None:
        super().__init__(wizard, THREADS)
        self.status_label = _label(note=True)
        self.holes = QWidget()
        self.form = QFormLayout(self.holes)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.note_label = _label(THREADS_NOTE, note=True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addWidget(self.holes)
        layout.addWidget(self.note_label)
        layout.addStretch(1)
        self.boxes: dict[str, QComboBox] = {}  # by feature id: a plain hole, or the thread chosen
        self.shown: tuple | None = None  # the unit and candidates the rows were made for

    def enter(self) -> None:
        self.w.show_threads()


class SummaryPage(GuidedPage):
    def __init__(self, wizard: GuidedWizard) -> None:
        super().__init__(wizard, SUMMARY)
        self.answers_label = _label()
        self.title_label = _label()
        self.folder_label = _label()
        self.problem_label = _label()
        bold = self.problem_label.font()
        bold.setBold(True)
        self.problem_label.setFont(bold)
        self.names_label = _label(note=True)
        self.browse = QPushButton("Choose Another Folder...")
        self.pdf_box = QCheckBox("Also save a PDF, to print or send")
        self.dxf_box = QCheckBox("Also save a DXF, for CAM, laser or waterjet programs")
        self.status_label = _label()
        browse = QHBoxLayout()
        browse.addWidget(self.browse)
        browse.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(self.answers_label)
        layout.addWidget(self.title_label)
        layout.addWidget(self.folder_label)
        layout.addLayout(browse)
        layout.addWidget(self.problem_label)
        layout.addWidget(self.names_label)
        layout.addWidget(self.pdf_box)
        layout.addWidget(self.dxf_box)
        layout.addWidget(_label(PRELIMINARY_WORDS, note=True))
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        self.browse.clicked.connect(wizard.choose_folder)
        self.pdf_box.toggled.connect(wizard.output_page.pdf_box.setChecked)
        self.dxf_box.toggled.connect(wizard.output_page.dxf_box.setChecked)

    def enter(self) -> None:
        op = self.w.output_page
        for mine, theirs in ((self.pdf_box, op.pdf_box), (self.dxf_box, op.dxf_box)):
            mine.blockSignals(True)
            mine.setChecked(theirs.isChecked())
            mine.blockSignals(False)
        self.w.show_summary()


class GuidedWizard(DrawingWizard):
    """The Guided drawing of ``part`` (see the module notes), made with the
    :class:`.drawingwizard.DrawingWizard`'s arguments and signal."""

    def __init__(self, parent: QWidget | None, worker: Any, part: Any, **kw: Any) -> None:
        super().__init__(parent, worker, part, **kw)
        self.setWindowTitle(f"Guided Drawing of {os.path.basename(self.part)}")
        self.setStartId(PURPOSE)
        # A PDF to send comes with the drawing unless unticked; a DXF only when asked for.
        self.output_page.dxf_box.setChecked(False)
        self.purpose_chosen(DEFAULT_PURPOSE.get(self.settings.defaults.detail, "shop"))
        self.show_part_status()

    def _add_pages(self) -> None:
        self.unit: str | None = None  # the unit chosen or offered, once the part is read
        self.purpose: str | None = None
        self.purpose_page = PurposePage(self)
        self.guided_views_page = ViewsPage(self)
        self.units_page = UnitsPage(self)
        self.detail_page = DetailPage(self)
        self.threads_page = ThreadsPage(self)
        self.summary_page = SummaryPage(self)
        self.guided_pages = (
            self.purpose_page,
            self.guided_views_page,
            self.units_page,
            self.detail_page,
            self.threads_page,
            self.summary_page,
        )
        for page in self.guided_pages:
            self.setPage(page.index, page)
        title, why = QUESTIONS[TITLE]
        self.title_page.setTitle(title)
        self.title_page.setSubTitle(why)
        self.title_page.setMinimumWidth(PAGE_WIDTH)
        self.setPage(TITLE, self.title_page)
        for page in self.pages:  # the store of the answers, never shown
            if page is not self.title_page:
                page.setParent(self)
                page.hide()

    # ------------------------------------------------------------------ the order
    def order(self) -> tuple[int, ...]:
        """The questions in turn: an assembly is not asked how much to dimension or about
        threads, and a part is not asked about threads once the preview shows no hole that
        may be threaded."""
        skip = {DETAIL, THREADS} if self.is_assembly else set()
        if self.thread_candidates() == ():
            skip.add(THREADS)
        return tuple(i for i in ORDER if i not in skip)

    def nextId(self) -> int:  # noqa: N802 (Qt's name)
        order = self.order()
        current = self.currentId()
        if current not in order:
            return order[0]
        k = order.index(current) + 1
        return order[k] if k < len(order) else -1

    def _page_shown(self, index: int) -> None:
        self._widen_preview()
        page = self.page(index)
        if isinstance(page, GuidedPage):
            page.enter()
        self.request_preview()
        if index == SUMMARY:
            self.folder_changed()

    # ------------------------------------------------------------------ answers
    def purpose_chosen(self, key: str) -> None:
        """What the drawing is for: how the part is made and the detail level."""
        purpose = PURPOSE_BY_KEY[key]
        if purpose.process == "printed" and not self.settings.printing.processes:
            key, purpose = "quote", PURPOSE_BY_KEY["quote"]  # no process to print with
        self.purpose = key
        button = self.purpose_page.buttons[key]
        if not button.isChecked():
            button.setChecked(True)
        mp = self.manufacturing_page
        (mp.printed if purpose.process == "printed" else mp.machined).setChecked(True)
        self.process_chosen()
        self._show_printing()
        self.put_detail(purpose.detail)

    def put_detail(self, detail: str) -> None:
        """The detail level, and its tolerancing: plus and minus below Fully defined, else
        the scheme Drawing Settings give the way the part is made."""
        mp = self.manufacturing_page
        process = mp.chosen_process()
        scheme = self.settings.gdt.scheme.get(process, "datum") if detail == "full" else "plusminus"
        for box, value in ((mp.detail, detail), (mp.scheme, scheme)):
            box.blockSignals(True)
            box.setCurrentIndex(max(box.findData(value), 0))
            box.blockSignals(False)
        self._detail_touched = True
        self._scheme_touched = True
        self.changed(MANUFACTURING)

    def detail_answered(self, detail: str) -> None:
        self.put_detail(detail)
        self.detail_page.scheme_label.setText(self.scheme_words())

    def printing_chosen(self) -> None:
        name = self.purpose_page.process.currentText()
        box = self.manufacturing_page.process
        index = box.findText(name)
        if index >= 0 and index != box.currentIndex():
            box.setCurrentIndex(index)  # the wizard's own control: the request follows
        self._show_printing()

    def _show_printing(self) -> None:
        pp, mp = self.purpose_page, self.manufacturing_page
        printed = mp.chosen_process() == "printed"
        figures = mp.chosen_figures(self.settings)
        pp.figures_label.setText(process_words(figures) if figures is not None else "")
        pp.printing.setVisible(printed)
        has = bool(self.settings.printing.processes)
        pp.buttons["print"].setEnabled(has)
        pp.no_process_label.setVisible(not has)

    def _fill_printing(self) -> None:
        mp, box = self.manufacturing_page, self.purpose_page.process
        box.blockSignals(True)
        box.clear()
        box.addItems([mp.process.itemText(i) for i in range(mp.process.count())])
        box.setCurrentIndex(mp.process.currentIndex())
        box.blockSignals(False)
        self._show_printing()

    def view_ticked(self, name: str, on: bool) -> None:
        """A view ticked or not, set on the wizard's own views page (so it counts as the
        user's choice, kept when the purpose changes)."""
        vp = self.views_page
        box = vp.isometric if name == "isometric" else vp.views[name]
        box.setChecked(on)

    def unit_chosen(self, unit: str) -> None:
        self.unit = unit
        self.changed(PART)

    def chosen_unit(self) -> str | None:
        return self.unit

    def default_unit(self) -> str | None:
        """The unit offered: Drawing Settings' fixed unit, else the part's own, else the
        unit SolidSeas guessed when its evidence leans one way; None when one must be
        chosen."""
        probe = self.probe
        if probe is None or probe.refused is not None:
            return None
        fixed = self.settings.standard.units
        if fixed in UNIT_NAMES:
            return fixed
        if probe.unit_origin == "file" and probe.unit in UNIT_NAMES:
            return probe.unit
        guess = probe.evidence
        if guess is not None and guess.decided and guess.unit in UNIT_NAMES:
            return guess.unit
        return None

    def units_option(self) -> str:
        """The unit chosen, as the wizard sends it: ``part`` when it is the one the part
        or Drawing Settings give anyway."""
        if unit_question(self.probe, self.settings):
            return self.unit or "part"
        if self.unit is None or self.unit == self.default_unit():
            return "part"
        return self.unit

    def unit_source_words(self) -> str:
        probe, s = self.probe, self.settings
        if probe is None:
            return "The part is being read."
        fixed = s.standard.units
        if fixed in UNIT_NAMES:
            return (
                f"Drawing Settings > Standard and Units draw every part in {UNIT_NAMES[fixed]}s. "
                "Choosing the other unit draws this one in it."
            )
        if probe.unit_origin == "file" and probe.unit in UNIT_NAMES:
            return f"The part is modelled in {UNIT_NAMES[probe.unit]}s."
        guess = probe.evidence
        words = "The part does not say which unit it is modelled in; " + evidence_words(guess).removeprefix(
            "not stated; "
        )
        if guess is None or not guess.decided:
            return words + ". Choose the one it is in."
        return words + ". Check it, and choose the other if it is wrong."

    def scheme_words(self) -> str:
        mp = self.manufacturing_page
        if mp.detail.currentData() != "full":
            return "Tolerances: plus and minus, on each size, with the title block's general ones."
        if mp.scheme.currentData() == "datum":
            return "Tolerances: from datums with GD&T, as Drawing Settings give for parts made this way."
        return "Tolerances: plus and minus, as Drawing Settings give for parts made this way."

    # ------------------------------------------------------------------ what each page lacks
    def guided_problems(self, index: int) -> list[str]:
        """Why guided page ``index`` cannot go on, in words; empty when it can."""
        if index == THREADS and self.thread_candidates() is None and self.preview_error is None:
            return ["the holes are still being checked"]
        if index == PURPOSE:
            out = self.part_problems()
            mp = self.manufacturing_page
            if not out and mp.chosen_process() == "printed" and not mp.process.currentText():
                out.append("Drawing Settings > Printing lists no process to choose")
            return out
        if index == UNITS and self.probe is not None and self.chosen_unit() is None:
            return ["choose Inch or Millimetre"]
        if index == SUMMARY:
            out = self.page_problems(OUTPUT)
            if self.current_request() is None:
                out.append("the part is not ready to draw")
            return out
        return []

    def validate_guided(self, index: int) -> bool:
        if index == SUMMARY:
            if self.written is not None:
                return True
            self.folder_changed()
        return not self.guided_problems(index)

    # ------------------------------------------------------------------ threads
    def thread_candidates(self) -> tuple | None:
        """The holes and patterns whose size is a tap drill, as the latest preview found
        them (the wizard's thread table); None while no preview has been made."""
        if self.answer is None:
            return None
        return tuple(self.answer.thread_candidates)

    def tapped_holes(self) -> list[tuple[str, str]]:
        """The holes answered Tapped on the wizard's thread table: (feature id, thread)."""
        return [
            (fid, thread_box.currentText())
            for fid, (answer_box, thread_box, _depth) in self.dimensions_page.rows.items()
            if answer_box.currentData() == "tapped"
        ]

    def thread_chosen(self, fid: str, thread: str | None) -> None:
        """A hole is plain (``thread`` None) or tapped with ``thread``: set on the wizard's
        own thread table, whose answers become the drawing's ``confirm_thread`` edits."""
        row = self.dimensions_page.rows.get(fid)
        if row is None:
            return
        answer_box, thread_box, _depth = row
        if thread is not None:
            thread_box.setCurrentIndex(max(thread_box.findText(thread), 0))
        answer_box.setCurrentIndex(ANSWERS.index("tapped" if thread is not None else "plain"))

    def show_threads(self) -> None:
        """The threads page as the latest preview and the answers stand: a row for each
        candidate, made again only when the candidates or the unit change."""
        tp = self.threads_page
        candidates = self.thread_candidates()
        if candidates is None:
            tp.status_label.setText(THREADS_FAILED if self.preview_error is not None else THREADS_WAITING)
        else:
            tp.status_label.setText("" if candidates else THREADS_NONE)
        tp.status_label.setVisible(bool(tp.status_label.text()))
        tp.holes.setVisible(bool(candidates))
        tp.note_label.setVisible(bool(candidates))
        unit = self.chosen_unit()
        shown = (
            unit,
            tuple(
                (c.get("feature"), tuple(c.get("threads", ())), c.get("count"), c.get("diameter_mm"))
                for c in candidates or ()
            ),
        )
        if shown != tp.shown:
            tp.shown = shown
            while tp.form.rowCount():
                tp.form.removeRow(0)
            tp.boxes = {}
            for cand in candidates or ():
                fid = str(cand.get("feature", ""))
                box = QComboBox()
                box.addItem(NO_THREAD, None)
                for thread in cand.get("threads", ()):
                    box.addItem(f"Yes, {thread}", str(thread))
                box.currentIndexChanged.connect(
                    lambda _i, f=fid, b=box: self.thread_chosen(f, b.currentData())
                )
                tp.form.addRow(hole_words(cand, unit), box)
                tp.boxes[fid] = box
        tapped = dict(self.tapped_holes())
        for fid, box in tp.boxes.items():
            box.blockSignals(True)
            box.setCurrentIndex(max(box.findData(tapped[fid]), 0) if fid in tapped else 0)
            box.blockSignals(False)

    # ------------------------------------------------------------------ the wizard's hooks
    def _probed(self, result: dict) -> None:
        super()._probed(result)
        if self.probe is not None and self.unit is None:
            self.unit = self.default_unit()
        self.show_part_status()
        self.units_page.source_label.setText(self.unit_source_words())

    def _apply_settings(self, *, first: bool = False) -> None:
        super()._apply_settings(first=first)
        self._fill_printing()

    def refresh(self, index: int | None = None) -> None:
        super().refresh(index)
        for page in self.guided_pages:
            page.completeChanged.emit()
        if self.currentId() == SUMMARY:
            self.show_summary()

    def folder_changed(self) -> None:
        super().folder_changed()
        if self.currentId() == SUMMARY:
            self.show_summary()

    def _waiting_words(self) -> None:
        super()._waiting_words()
        if self.probe is not None and self.probe_error is None:
            problems = self.page_problems(PART)
            if problems:
                self.preview_status.setText(f"No preview yet: {problems[0]}.")

    def _show_dimensions(self, answer: Any) -> None:
        super()._show_dimensions(answer)
        self.show_threads()

    def accept(self) -> None:
        super().accept()
        self.summary_page.status_label.setText(self.output_page.status_label.text())

    def _output_done(self, result: dict) -> None:
        super()._output_done(result)
        self.summary_page.status_label.setText(self.output_page.status_label.text())

    # ------------------------------------------------------------------ words
    def show_part_status(self) -> None:
        pp = self.purpose_page
        if self.probe_error is not None:
            pp.status_label.setText(f"The part could not be read: {self.probe_error}")
        elif self.probe is None:
            pp.status_label.setText("Reading the part...")
        elif self.probe.refused is not None:
            what = "assembly" if self.is_assembly else "part"
            pp.status_label.setText(f"SolidSeas cannot draw this {what}: {self.probe.refused}.")
        else:
            problems = self.part_problems()
            pp.status_label.setText(f"To go on: {problems[0]}" if problems else "")
        pp.status_label.setVisible(bool(pp.status_label.text()))
        pp.size_label.setText(size_words(self.probe) if self.probe is not None else "")
        assembly = self.is_assembly
        pp.assembly_label.setVisible(assembly)
        pp.choices.setVisible(not assembly)

    def summary_lines(self) -> list[str]:
        """What will be made, in words."""
        mp, vp = self.manufacturing_page, self.views_page
        name = os.path.basename(self.part)
        configuration = getattr(self.probe, "configuration", None)
        lines = [f"Part: {name}" + (f", configuration {configuration}" if configuration else "")]
        if self.is_assembly:
            lines.append("For: an assembly drawing, with its parts list and balloons")
        else:
            purpose = PURPOSE_BY_KEY.get(self.purpose or "")
            if purpose is not None:
                lines.append(f"For: {purpose.label[0].lower()}{purpose.label[1:]}")
            if mp.chosen_process() == "printed" and mp.process.currentText():
                lines.append(f"Printing process: {mp.process.currentText()}")
        lines.append(f"Views: {views_words(vp.ticked(), vp.isometric.isChecked())}")
        unit = self.chosen_unit()
        lines.append(f"Unit: {UNIT_NAMES[unit]}" if unit in UNIT_NAMES else "Unit: not chosen yet")
        if not self.is_assembly:
            lines.append(f"Dimensions: {DETAIL_NAMES.get(mp.detail.currentData(), '')}")
            if self.thread_candidates():
                tapped = self.tapped_holes()
                words = ", ".join(f"{fid} as {thread}" for fid, thread in tapped)
                lines.append(f"Threaded holes: {words or 'none, all drawn plain'}")
        return lines

    def title_lines(self) -> list[str]:
        """The title block as the latest preview shows it."""
        if self.answer is None:
            return ["Title block: filled in once the preview is made."]
        title = dict(self.answer.drawing.title)
        lines = ["Title block, as the preview shows it:"]
        for key, label in (
            ("number", "Drawing number"),
            ("title", "Title"),
            ("revision", "Revision"),
            ("material", "Material"),
            ("finish", "Finish"),
        ):
            f = title.get(key)
            if f is not None and f.text:
                lines.append(f"{label}: {f.text}")
        drawn = self.title_page.drawn_by_name(self.settings)
        lines.append(f"Drawn by: {drawn}" if drawn else NOBODY)
        return lines

    def show_summary(self) -> None:
        sp, op = self.summary_page, self.output_page
        sp.answers_label.setText("\n".join(self.summary_lines()))
        sp.title_label.setText("\n".join(self.title_lines()))
        folder = op.folder.text().strip()
        sp.folder_label.setText(f"Saved in: {folder}" if folder else "Saved in: no folder chosen")
        problem = self.folder_problem()
        sp.problem_label.setText("" if problem is None else f"Refused: {problem}")
        sp.problem_label.setVisible(problem is not None)
        sp.names_label.setText(op.names_label.text())


__all__ = [
    "DETAILS",
    "ORDER",
    "PURPOSES",
    "GuidedWizard",
    "hole_words",
    "views_words",
]
