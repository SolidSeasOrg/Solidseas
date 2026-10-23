"""File > New Drawing...: the New Drawing wizard (``solidseas_app.viewer.drawingwizard``;
``docs/DRAWINGS.md`` 15.3, 12.5 and 12.6).

Every page's fields and validation are tested with a stand-in for the drawing child
process that answers from canned answers: a probe made here, and a drawing of o02
the library made in this process once for the module, as the child makes one. The
stand-in records what the wizard asks of it, so the tests read the options, title
fields and edits the pages send. One test runs the real ``DrawingWorker`` and draws a
copy of o02 into the test's temporary folder, end to end.

Everything runs offscreen (``QT_QPA_PLATFORM=offscreen``) and is skipped without
PySide6. No test opens a dialog: the wizard's question, Drawing Settings and the
folder chooser are replaced by stand-ins. Files are written only under each test's
temporary folder, and the parts drawn are copies there. The company is the fictional
"Example Engineering Co.".
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from dataclasses import replace

import pytest

try:
    import PySide6.QtWidgets  # noqa: F401
except ImportError:  # the window's tests need the [app] extra
    pytest.skip("PySide6 is not installed: the New Drawing wizard is not tested", allow_module_level=True)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from solidseas import drawing
from solidseas.drawing import document
from solidseas.drawing import settings as S
from solidseas.drawing.numbers import UnitGuess
from solidseas.drawing.types import Coverage, DrawingOptions
from solidseas.errors import OutputRefusedError
from solidseas_app.viewer.drawingproc import Answer, Body, Check, Exported, Probe, ProcessStopped
from support import fixture_path

COMPANY = "Example Engineering Co."
STAGES = ("source", "model", "features", "views", "plan", "assemble")  # the drawing pipeline's
PDF = b"%PDF-1.7\n1 0 obj << /Producer (SolidSeas 0.2) >> endobj\n%%EOF\n"
DXF = b"999\nSolidSeas 0.2\n0\nEOF\n"


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from solidseas_app.viewer.app import use_system_fonts

    use_system_fonts()
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def dw(app):
    from solidseas_app.viewer import drawingwizard

    return drawingwizard


def people_settings(**values) -> S.DrawingSettings:
    """Drawing Settings of the fictional company, with two people and an answer for parts
    that state no unit: nothing waits for a first use."""
    s = S.with_value(S.DrawingSettings(), "company", "name", COMPANY)
    s = S.with_value(
        s, "people", "people", [{"name": "Ann Bee", "initials": "AB"}, {"name": "Carl Dee", "initials": "CD"}]
    )
    s = S.with_value(s, "standard", "unit_for_unstated", "mm")
    for path, value in values.items():
        group, key = path.split("__")
        s = S.with_value(s, group, key, value)
    return s


def probe_of(**changes) -> Probe:
    """What the child's probe says of a box of 10 by 20 by 30 mm that states millimetre."""
    base = {
        "name": "bracket.SLDPRT",
        "configuration": "Default",
        "configurations": ("Default", "Long"),
        "active_configuration": "Default",
        "bodies": (Body("Body 1", "solid", 6, True),),
        "unit": "mm",
        "unit_origin": "file",
        "stated_unit": "mm",
        "size_m": (0.01, 0.02, 0.03),
        "counts": {"bodies": 1, "faces": 6, "edges": 12, "blends": 0},
        "warnings": (),
    }
    base.update(changes)
    return Probe(**base)


GUESSED = {
    "unit": "in",
    "unit_origin": "guessed",
    "stated_unit": None,
    "evidence": UnitGuess("in", 41, 6, 35, 0, 47, True),
}


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    """o02's drawing as the library makes it (number SS-1), and its part copied under a
    fictional name."""
    root = tmp_path_factory.mktemp("wizard-canned")
    part = root / "bracket.SLDPRT"
    shutil.copyfile(fixture_path("o02_boxA.SLDPRT"), part)
    fields = {"number": "SS-1", "drawn_by": "Ann Bee", "finish": "NONE"}
    d = drawing.make_drawing(str(part), fields=fields, settings=people_settings())
    data = document.dumps(d)
    loaded, problems = document.loads(data)
    assert problems == []
    return d, data, loaded


CHECKS = (
    Check("R6.title", "error", "the title block's MATERIAL is empty", "material", ("Edit the Title Block",)),
    Check("R3.roles", "warning", "3 dimensions take their precision from their role", "R3.roles", ()),
    Check("R6.signatures", "information", "CHECKED is not signed", "CHECKED", ("Sign...",)),
)


def answer_of(made, **changes) -> Answer:
    d, data, loaded = made
    checks = changes.pop("checks", CHECKS)
    coverage = changes.pop("coverage", d.coverage)
    drawn = replace(loaded, checks=checks, coverage=coverage)
    base = {"thread_candidates": (), "seconds": {"total": 0.1}, "warnings": ()}
    base.update(changes)
    return Answer(data, drawn, {"id": d.id}, checks, coverage, **base)


class StandIn:
    """The drawing child as the wizard sees it: ``probe`` answers ``probes`` (a Probe, a
    function of the configuration, or an exception to raise), ``make`` and ``edit``
    answer ``answer``, ``export`` gives a PDF and DXF that say SolidSeas wrote them.
    Every call is recorded in ``calls``."""

    def __init__(self, answer: Answer, probes=None) -> None:
        self.answer = answer
        self.probes = probes if probes is not None else probe_of()
        self.calls: list[tuple] = []
        self.cancels = 0

    def probe(self, part, configuration=None):
        self.calls.append(("probe", part, configuration))
        if isinstance(self.probes, BaseException):
            raise self.probes
        return self.probes(configuration) if callable(self.probes) else self.probes

    def make(self, part, options, fields, settings, progress=None):
        self.calls.append(("make", part, options, dict(fields), settings))
        if progress is not None:  # each stage of the pipeline, as the child says them
            for step, stage in enumerate(STAGES, 1):
                progress({"stage": stage, "step": step, "of": len(STAGES)})
        return self.answer

    def edit(self, answer, op, args):
        self.calls.append(("edit", op, args))
        return self.answer

    def attach(self, answer, part=None, drawing_path=None):
        self.calls.append(("attach", part))

    def export(self, answer, kind):
        self.calls.append(("export", kind))
        return Exported(kind, PDF if kind == "pdf" else DXF)

    def forget(self, answer):
        self.calls.append(("forget",))

    def cancel(self) -> bool:
        self.cancels += 1
        return False

    def named(self, name: str) -> list[tuple]:
        return [c for c in self.calls if c[0] == name]

    def last_make(self) -> tuple:
        return self.named("make")[-1]


def settle(app, wizard, until=None, timeout: float = 60.0) -> None:
    """Run the event loop until ``until()`` (else until the wizard has nothing in
    progress)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if until() if until is not None else not wizard.busy:
            app.processEvents()
            return
        time.sleep(0.005)
    raise AssertionError("the wizard did not settle in time")


@pytest.fixture
def open_wizard(app, dw, tmp_path):
    """``open_wizard(worker, settings=..., **kw)``: a wizard of a copy of o02 in the test's
    folder, shown, with its dialogs replaced and its part read; closed after the test."""
    made_wizards = []
    part = tmp_path / "parts" / "bracket.SLDPRT"
    part.parent.mkdir()
    shutil.copyfile(fixture_path("o02_boxA.SLDPRT"), part)

    def make(worker, settings=None, *, show=True, ask=None, edit_settings=None, **kw):
        s = people_settings() if settings is None else settings
        w = dw.DrawingWizard(
            None,
            worker,
            kw.pop("part", str(part)),
            settings=s,
            settings_path=str(tmp_path / "Drawing.json"),
            **kw,
        )
        w.preview_delay_ms = 0
        w.questions = []
        w.ask = ask or (lambda title, text: w.questions.append(text) or False)
        w.edit_settings = edit_settings or (lambda page: None)
        w.pick_folder = lambda start: ""
        made_wizards.append(w)
        if show:
            w.show()
            settle(app, w)
        return w

    yield make
    for w in made_wizards:
        w.done(0)
        w.pool.waitForDone(10_000)
        w.deleteLater()
    app.processEvents()


def go_to(app, wizard, page: int) -> None:
    while wizard.currentId() < page:
        before = wizard.currentId()
        wizard.next()
        settle(app, wizard)
        assert wizard.currentId() > before, wizard.page_problems(before)


def finish_title(wizard) -> None:
    """Page 2 as a user leaves it: the finish chosen."""
    wizard.title_page.finish.setEditText("None")


# --------------------------------------------------------------------------- page 1
def test_part_page_shows_what_the_probe_read(app, open_wizard, made):
    probe = probe_of(
        warnings=("2 rolling-sphere blend faces are not recognised as blends yet",),
        counts={"bodies": 1, "faces": 2500, "edges": 7000, "blends": 2},
    )
    asked = []

    def probes(configuration):
        asked.append(configuration)
        return replace(probe, configuration=configuration or "Default")

    worker = StandIn(answer_of(made), probes)
    w = open_wizard(worker)
    page = w.part_page
    assert asked == [None]
    from solidseas_app.viewer import experimental

    note = w.experimental_note
    assert note.text() == experimental.drawings_note() and note.isVisibleTo(w), "drawings are experimental"
    assert page.file_label.text().endswith("bracket.SLDPRT")
    assert [page.configuration.itemText(i) for i in range(page.configuration.count())] == ["Default", "Long"]
    assert page.bodies.count() == 1 and page.bodies.item(0).text() == "Body 1"
    assert page.unit_label.text() == "Unit: millimetre, stated in the part"
    assert not page.inch_button.isVisibleTo(w) and not page.mm_button.isVisibleTo(w)
    assert page.size_label.text() == "Overall size: 10.00 x 20.00 x 30.00 mm (0.394 x 0.787 x 1.181 in)"
    warnings = page.warnings_label.text()
    assert "rolling-sphere blend" in warnings
    assert "Draft quality: the part has 2,500 faces, more than the 2,000" in warnings
    assert page.isComplete() and w.page_problems(0) == []

    # another configuration is read again, and drawn
    page.configuration.setCurrentIndex(1)
    page.configuration.activated.emit(1)
    settle(app, w)
    assert asked == [None, "Long"]
    go_to(app, w, 1)
    options = worker.last_make()[2]
    assert options.configuration == "Long" and options.quality == "draft"


def test_a_part_that_states_no_unit_needs_a_unit_button(app, open_wizard, made):
    worker = StandIn(answer_of(made), probe_of(**GUESSED))
    w = open_wizard(worker)
    page = w.part_page
    assert page.unit_label.text() == (
        "Unit: not stated; looks like inch (41 of 47 sizes are whole thousandths). "
        "Click the unit the part is in."
    )
    assert page.inch_button.isVisibleTo(w) and page.mm_button.isVisibleTo(w)
    assert not page.isComplete()
    assert w.page_problems(0) == ["the part states no unit: click Inch or Millimetre"]
    w.next()
    settle(app, w)
    assert w.currentId() == 0 and worker.named("make") == []  # nothing is made before a unit is chosen
    assert w.preview_status.text() == (
        "The preview starts once page 1 is complete: the part states no unit: click Inch or Millimetre"
    )

    page.inch_button.click()
    assert page.isComplete()
    go_to(app, w, 1)
    assert worker.last_make()[2].units == "in"


def test_settings_that_fix_the_unit_ask_nothing(app, open_wizard, made):
    worker = StandIn(answer_of(made), probe_of(**GUESSED))
    w = open_wizard(worker, people_settings(standard__units="mm"))
    assert w.part_page.unit_label.text() == (
        "Unit: millimetre, as Drawing Settings > Standard and Units say (the part states none)"
    )
    assert not w.part_page.inch_button.isVisibleTo(w)
    assert w.part_page.isComplete()
    go_to(app, w, 1)
    assert worker.last_make()[2].units == "part"  # the settings' unit, as the CLI takes it


def test_the_detail_level_starts_from_drawing_settings(app, open_wizard, made):
    worker = StandIn(answer_of(made), probe_of())
    w = open_wizard(worker, people_settings(defaults__detail="simplified"))
    assert w.manufacturing_page.detail.currentData() == "simplified"
    go_to(app, w, 2)
    settle(app, w)
    assert worker.last_make()[2].detail == "simplified"


def test_a_refused_part_stops_on_page_one(app, open_wizard, made):
    refused = probe_of(
        refused="the part has 60,000 faces, more than the 50,000 a drawing takes",
        refused_code="drawing_too_complex",
        refused_rule="faces",
    )
    worker = StandIn(answer_of(made), refused)
    w = open_wizard(worker)
    assert w.part_page.refusal_label.isVisibleTo(w)
    assert w.part_page.refusal_label.text() == (
        "SolidSeas cannot draw this part: the part has 60,000 faces, more than the 50,000 a drawing takes."
    )
    assert not w.part_page.isComplete()
    w.next()
    settle(app, w)
    assert w.currentId() == 0 and worker.named("make") == []


def test_a_part_that_cannot_be_read_says_why(app, open_wizard, made):
    worker = StandIn(answer_of(made), FileNotFoundError(2, "No such file or directory"))
    w = open_wizard(worker)
    assert w.part_page.status_label.text() == "The part could not be read: No such file or directory"
    assert w.page_problems(0) == ["the part could not be read: No such file or directory"]


def test_bodies_ticked_are_the_bodies_drawn(app, open_wizard, made):
    two = probe_of(bodies=(Body("Body 1", "solid", 6, True), Body("Insert", "solid", 4, True)))
    worker = StandIn(answer_of(made), two)
    w = open_wizard(worker)
    from PySide6.QtCore import Qt

    for i in range(2):
        w.part_page.bodies.item(i).setCheckState(Qt.CheckState.Unchecked)
    assert w.page_problems(0) == ["tick at least one body to draw"]
    w.part_page.bodies.item(1).setCheckState(Qt.CheckState.Checked)
    go_to(app, w, 1)
    assert worker.last_make()[2].bodies == ("Insert",)


# --------------------------------------------------------------------------- page 2
def test_title_fields_reach_the_drawing(app, open_wizard, made):
    worker = StandIn(answer_of(made))
    w = open_wizard(worker)
    go_to(app, w, 1)
    tp = w.title_page
    assert tp.edits["title"].placeholderText() == "from the part: BRACKET"  # the part's, from the preview
    for key, text in (
        ("title", "BRACKET, MOTOR MOUNT"),
        ("part_number", "1234-001"),
        ("number", "SS-1"),
        ("revision", "b"),
        ("model_revision", "3"),
    ):
        tp.edits[key].setText(text)
    tp.material.setCurrentIndex(tp.material.findText("STEEL 1018"))
    tp.finish.setCurrentIndex(tp.finish.findText("Clear anodize"))
    tp.drawn_by.setCurrentIndex(tp.drawn_by.findText("Carl Dee"))
    assert tp.finish_note.text() == "Prints as: ANODIZE PER MIL-A-8625, TYPE II, CLASS 1, CLEAR"
    assert tp.material_note.text() == "From the materials list: STEEL 1018, ASTM A108"
    assert not tp.heat.isVisibleTo(w)
    settle(app, w)
    assert worker.last_make()[3] == {
        "title": "BRACKET, MOTOR MOUNT",
        "part_number": "1234-001",
        "number": "SS-1",
        "revision": "B",
        "model_revision": "3",
        "material": "aisi 1018",  # the list's entry, so the drawing takes the material from the list
        "finish": "ANODIZE PER MIL-A-8625, TYPE II, CLASS 1, CLEAR",
        "drawn_by": "Carl Dee",
    }
    assert [tp.drawn_by.itemText(i) for i in range(tp.drawn_by.count())] == ["Ann Bee", "Carl Dee"]


def test_the_finish_starts_as_none_or_the_parts_own_and_never_holds_the_drawing_up(app, open_wizard, made):
    """Left alone, the finish is None for a part that states none and the part's own for
    one that does; a finish the user picks is sent as its callout."""
    from dataclasses import replace

    from solidseas.drawing.types import TitleField

    base = answer_of(made)

    def with_finish(field):
        title = tuple((k, f) for k, f in base.drawing.title if k != "finish")
        title += (("finish", field),) if field is not None else ()
        return replace(base, drawing=replace(base.drawing, title=title))

    worker = StandIn(with_finish(None))  # the part states no finish
    w = open_wizard(worker)
    go_to(app, w, 1)
    tp = w.title_page
    assert w.page_problems(1) == [] and tp.finish.currentText() == "None" and tp.finish_default
    tp.edits["number"].setText("SS-9")
    settle(app, w)
    assert worker.last_make()[3]["finish"] == "NONE"
    tp.finish.setCurrentIndex(tp.finish.findText("Clear anodize"))
    settle(app, w)
    assert not tp.finish_default
    assert worker.last_make()[3]["finish"] == "ANODIZE PER MIL-A-8625, TYPE II, CLASS 1, CLEAR"
    w.reject()

    worker = StandIn(with_finish(TitleField("PAINT BLACK", "part")))  # the part's own finish
    w = open_wizard(worker)
    go_to(app, w, 1)
    tp = w.title_page
    assert tp.finish.currentText() == "PAINT BLACK" and tp.finish_default and w.page_problems(1) == []
    tp.edits["number"].setText("SS-9")
    settle(app, w)
    assert "finish" not in worker.last_make()[3]  # the part's own stands


def test_title_page_validation(app, open_wizard, made):
    worker = StandIn(answer_of(made))
    w = open_wizard(worker)
    go_to(app, w, 1)
    tp = w.title_page
    # the finish never holds the drawing up: it starts as None until the user picks one
    assert w.page_problems(1) == [] and tp.isComplete() and not tp.problems_label.isVisibleTo(w)
    assert tp.finish.currentText() == "None" and tp.finish_default
    finish_title(w)
    assert tp.isComplete()

    tp.edits["revision"].setText("I")
    assert w.page_problems(1) == ["I is not a revision mark: one to four letters, without I, O, Q, S, X or Z"]
    tp.edits["revision"].setText("AB")
    assert tp.isComplete()

    # a heat-treatable material asks for its heat treatment
    tp.material.setEditText("4140")
    assert tp.heat.isVisibleTo(w)
    assert w.page_problems(1) == ["STEEL 4140 can be heat treated: say whether it is, and to what"]
    tp.heat.setText("HARDEN TO 28-32 HRC")
    assert tp.isComplete()
    settle(app, w)
    fields = worker.last_make()[3]
    assert fields["material"] == "4140" and fields["heat_treatment"] == "HARDEN TO 28-32 HRC"

    # a material the list does not map is flagged, and goes as typed
    tp.material.setEditText("Unobtainium 7")
    assert not tp.heat.isVisibleTo(w)
    assert tp.material_note.text().startswith("Unobtainium 7 is not in the materials list")
    assert tp.isComplete()
    settle(app, w)
    assert worker.last_make()[3]["material"] == "Unobtainium 7"
    assert "heat_treatment" not in worker.last_make()[3]
    w.next()
    settle(app, w)
    assert w.currentId() == 2


def test_no_people_leaves_drawn_unsigned(app, open_wizard, made):
    worker = StandIn(answer_of(made))
    s = S.with_value(people_settings(), "people", "people", [])
    w = open_wizard(worker, s)
    go_to(app, w, 1)
    finish_title(w)
    assert not w.title_page.drawn_by.isEnabled()
    settle(app, w)
    assert "drawn_by" not in worker.last_make()[3]


# --------------------------------------------------------------------------- page 3
def test_manufacturing_page(app, open_wizard, made, dw):
    worker = StandIn(answer_of(made))
    w = open_wizard(worker)
    go_to(app, w, 1)
    finish_title(w)
    go_to(app, w, 2)
    mp = w.manufacturing_page
    assert mp.machined.isChecked()
    assert mp.turned.isEnabled() and mp.turned.text() == "Turned (lathe)"
    assert not mp.sheet_metal.isEnabled() and mp.sheet_metal.text() == "Sheet metal: coming later"
    assert "editor's sheet, not here" in mp.datum_label.text() and mp.datum_label.isVisibleTo(w)
    assert (
        mp.suggestion_label.text()
        == "Suggested: Machined (milled), because nothing about the part says otherwise."
    )
    assert not mp.printed_box.isVisibleTo(w)
    assert mp.scheme.currentData() == "datum"
    assert mp.detail.currentData() == "full" and mp.detail.count() == 3
    settle(app, w)
    assert worker.last_make()[2].process == "machined" and worker.last_make()[2].scheme == "datum"
    assert worker.last_make()[2].detail == "full"
    mp.detail.setCurrentIndex(mp.detail.findData("simplified"))
    mp.detail.activated.emit(mp.detail.currentIndex())
    settle(app, w)
    assert worker.last_make()[2].detail == "simplified"
    mp.detail.setCurrentIndex(mp.detail.findData("full"))
    mp.detail.activated.emit(mp.detail.currentIndex())

    mp.printed.click()
    assert mp.printed_box.isVisibleTo(w)
    assert mp.scheme.currentData() == "plusminus"  # Drawing Settings' scheme for printed parts
    mp.process.setCurrentIndex(mp.process.findText("SLA"))
    assert mp.figures_label.text() == (
        "SLA (vat photopolymerization): ±0.051 mm (±.002 in) in X and Y, ±0.127 mm "
        "(±.005 in) in Z, each plus 0.1 % of the nominal"
    )
    assert mp.figures_note.text() == "Service bureau figures; replace them with your own."
    mp.layer_height.setText("0.05 mm")
    mp.infill.setText("solid")
    mp.post.setText("bead blast")
    settle(app, w)
    _make, _part, options, fields, _settings = worker.last_make()
    assert options.process == "printed" and options.scheme == "plusminus"
    assert fields["process"] == "SLA" and fields["layer_height"] == "0.05 mm"
    notes = [c for c in worker.named("edit") if c[1] == "edit_notes"][-1][2]
    made_notes = [n.text for _i, n in made[2].notes]
    assert notes == [[*made_notes, "INFILL AND WALLS: SOLID", "POST-PROCESSING: BEAD BLAST"]]

    mp.process.setCurrentIndex(mp.process.findText("FDM"))
    assert mp.figures_label.text() == (
        "FDM (material extrusion): ±0.5 % of the nominal, never under ±0.500 mm (±.020 in)"
    )
    mp.scheme.setCurrentIndex(mp.scheme.findData("datum"))
    mp.scheme.activated.emit(mp.scheme.currentIndex())
    mp.machined.click()
    assert mp.scheme.currentData() == "datum"  # the user's choice stays
    settle(app, w)
    assert worker.last_make()[2].process == "machined"
    assert "process" not in worker.last_make()[3]


def test_a_printing_material_suggests_printed(app, open_wizard, made):
    worker = StandIn(answer_of(made))
    w = open_wizard(worker)
    go_to(app, w, 1)
    finish_title(w)
    w.title_page.material.setCurrentIndex(w.title_page.material.findText("PLA"))
    go_to(app, w, 2)
    mp = w.manufacturing_page
    assert mp.printed.isChecked()
    assert mp.suggestion_label.text() == (
        "Suggested: 3D printed, because PLA is a printing material in your materials list."
    )


TURNED_WHY = "every face is a face of revolution about one axis or a plane square to it"


def test_a_part_the_preview_finds_turned_suggests_turned(app, open_wizard, made):
    worker = StandIn(answer_of(made, turned=TURNED_WHY))
    w = open_wizard(worker)
    go_to(app, w, 1)
    finish_title(w)
    settle(app, w)
    assert w.turned_reason == TURNED_WHY  # from the preview page 2 made
    go_to(app, w, 2)
    mp = w.manufacturing_page
    assert mp.turned.isChecked() and mp.chosen_process() == "turned"
    assert mp.suggestion_label.text() == f"Suggested: Turned (lathe), because {TURNED_WHY}."
    assert mp.scheme.currentData() == "datum"  # the machined entry of Drawing Settings
    settle(app, w)
    assert worker.last_make()[2].process == "turned"
    mp.machined.click()  # the user's choice stays, whatever a later preview says
    settle(app, w)
    assert worker.last_make()[2].process == "machined" and mp.machined.isChecked()


def test_a_preview_that_comes_late_still_suggests_turned(app, open_wizard, made):
    worker = StandIn(answer_of(made))
    w = open_wizard(worker)
    go_to(app, w, 1)
    finish_title(w)
    go_to(app, w, 2)
    mp = w.manufacturing_page
    assert mp.machined.isChecked()
    worker.answer = answer_of(made, turned=TURNED_WHY)
    mp.detail.setCurrentIndex(mp.detail.findData("complex"))
    mp.detail.activated.emit(mp.detail.currentIndex())  # a change: another preview
    settle(app, w)
    assert mp.turned.isChecked()
    settle(app, w)
    assert worker.last_make()[2].process == "turned"


# --------------------------------------------------------------------------- page 4
def test_views_page_options(app, open_wizard, made, dw):
    worker = StandIn(answer_of(made))
    w = open_wizard(worker)
    go_to(app, w, 1)
    finish_title(w)
    go_to(app, w, 3)
    vp = w.views_page
    settle(app, w)
    assert worker.last_make()[2].views == "auto"  # the ticks are Drawing Settings' Default Views
    assert "SolidSeas chose the front looking from" in vp.chosen_label.text()
    assert not vp.turn.isEnabled()
    for button in (vp.detail_button, vp.section_button):
        assert not button.isEnabled()
    assert vp.later_label.text() == "Detail views and sections on request: coming in a later release."

    vp.front.setCurrentIndex(vp.front.findData("+y"))
    assert vp.turn.isEnabled()
    vp.turn.setCurrentIndex(1)
    vp.views["right"].setChecked(False)
    vp.views["left"].setChecked(True)
    vp.isometric.setChecked(False)
    vp.hidden.setChecked(True)
    vp.tangent.setCurrentIndex(vp.tangent.findData("phantom"))
    vp.scale.setCurrentIndex(vp.scale.findData("1:2"))
    vp.sheet.setCurrentIndex(vp.sheet.findData("B"))
    settle(app, w)
    options = worker.last_make()[2]
    assert options.views == ("front", "top", "left")
    assert (options.front, options.turn, options.hidden, options.tangent) == ("+y", 1, True, "phantom")
    assert (options.scale, options.sheet) == ((1, 2), "B")
    assert vp.isComplete()


def test_make_these_my_defaults_saves_drawing_settings(app, open_wizard, made, tmp_path):
    worker = StandIn(answer_of(made))
    w = open_wizard(worker)
    go_to(app, w, 1)
    finish_title(w)
    go_to(app, w, 3)
    vp = w.views_page
    assert not (tmp_path / "Drawing.json").exists()
    vp.views["bottom"].setChecked(True)
    vp.hidden.setChecked(True)
    vp.tangent.setCurrentIndex(vp.tangent.findData("thin"))
    vp.front.setCurrentIndex(vp.front.findData("-z"))
    vp.turn.setCurrentIndex(2)
    vp.scale.setCurrentIndex(vp.scale.findData("2:1"))
    vp.sheet.setCurrentIndex(vp.sheet.findData("C"))
    vp.defaults_button.click()
    saved, problems = S.load_settings(tmp_path / "Drawing.json")
    assert problems == []
    assert saved.defaults.views["machined"] == {
        "views": ("front", "top", "right", "bottom"),
        "isometric": True,
        "hidden": True,
        "tangent": "thin",
        "front": "-z",
    }
    assert saved.defaults.views["printed"] == S.DrawingSettings().defaults.views["printed"]
    assert saved.sheets.size == "C"
    assert saved.company.name == COMPANY  # the rest of the settings as they were
    assert w.settings == saved
    assert vp.defaults_label.text().startswith("Saved in ")
    # the controls keep what the user chose, the turn and the scale with them
    assert vp.turn.currentIndex() == 2 and vp.scale.currentData() == "2:1"
    settle(app, w)
    options = worker.last_make()[2]
    assert options.views == "auto" and options.front == "-z" and options.turn == 2 and options.scale == (2, 1)


# --------------------------------------------------------------------------- page 5
def holes_answer(made) -> Answer:
    d = made[0]
    dimension = d.dimensions[0]
    candidates = (
        {
            "feature": "f-1",
            "kind": "pattern",
            "count": 4,
            "diameter_mm": 5.0,
            "threads": ["M6 x 1"],
            "answered": False,
            "confirmed": None,
        },
        {
            "feature": "f-2",
            "kind": "hole",
            "count": 1,
            "diameter_mm": 5.1054,
            "threads": ["1/4-20 UNC"],
            "answered": False,
            "confirmed": None,
        },
        {
            "feature": "f-3",
            "kind": "hole",
            "count": 1,
            "diameter_mm": 3.3,
            "threads": ["M4 x 0.7"],
            "answered": False,
            "confirmed": None,
        },
    )
    end = Check(
        "R7.callouts",
        "warning",
        f"{dimension.id}: the hole runs into a bore, and its end is not confirmed",
        dimension.id,
        ("Confirm the End",),
    )
    coverage = Coverage(
        features=4, features_unclaimed=1, faces=10, faces_claimed=7, area=1.0, area_claimed=0.8
    )
    return answer_of(made, checks=(*CHECKS, end), coverage=coverage, thread_candidates=candidates)


def test_dimensions_page_answers_become_edits(app, open_wizard, made):
    answer = holes_answer(made)
    worker = StandIn(answer)
    w = open_wizard(worker)
    go_to(app, w, 1)
    finish_title(w)
    go_to(app, w, 4)
    dp = w.dimensions_page
    assert dp.features.topLevelItem(0).text(0) == "Width (3)"
    assert dp.threads.rowCount() == 3 and dp.threads.isVisibleTo(w)
    assert dp.threads.item(0, 0).text() == "f-1 (4 holes)" and dp.threads.item(0, 1).text() == "Ø5.00 mm"
    answer_box, thread_box, depth = dp.rows["f-1"]
    assert [answer_box.itemText(i) for i in range(answer_box.count())] == [
        "Not answered",
        "Tapped",
        "Clearance",
        "Plain",
    ]
    assert not thread_box.isEnabled()
    answer_box.setCurrentIndex(answer_box.findData("tapped"))
    assert thread_box.isEnabled() and thread_box.currentText() == "M6 x 1"
    depth.setValue(12.0)
    dp.rows["f-2"][0].setCurrentIndex(dp.rows["f-2"][0].findData("clearance"))
    dp.rows["f-3"][0].setCurrentIndex(dp.rows["f-3"][0].findData("plain"))
    fid = made[0].dimensions[0].features[0]
    item = dp.ends.item(0)
    assert item.text().startswith(f"{fid}: ") and "runs into a bore" in item.text()
    from PySide6.QtCore import Qt

    item.setCheckState(Qt.CheckState.Checked)
    settle(app, w)
    edits = [c[1:] for c in worker.named("edit")]
    last = edits[-2:]
    assert last == [
        ("confirm_thread", ["f-1", "M6 x 1-6H", pytest.approx(0.012)]),
        ("confirm_end", [fid, True]),
    ]
    assert not any(e[0] == "confirm_thread" and e[1][0] in ("f-2", "f-3") for e in edits)
    # the answers stay when the preview comes back
    assert dp.rows["f-1"][0].currentData() == "tapped" and dp.rows["f-2"][0].currentData() == "clearance"
    assert dp.ends.item(0).checkState() == Qt.CheckState.Checked

    lines = dp.coverage_label.text().splitlines()
    assert lines[:3] == [
        "By features: 4 features recognised, 1 left unclaimed",
        "By faces: 7 of 10 faces claimed by features",
        "By area: 80 % claimed",
    ]
    assert lines[3].startswith("This is a reduced-dimension drawing: 3 faces (20 % of the area, 1 feature)")
    assert dp.checks_label.text().startswith("Checks: 1 error, 2 warnings, 1 note.")
    assert dp.checks_list.item(0).text() == "error: the title block's MATERIAL is empty"


def test_a_complete_drawing_says_so(app, open_wizard, made):
    worker = StandIn(answer_of(made))
    w = open_wizard(worker)
    go_to(app, w, 1)
    finish_title(w)
    go_to(app, w, 4)
    dp = w.dimensions_page
    assert dp.coverage_label.text().splitlines()[-1] == (
        "Every recognised face is dimensioned: this is a fully dimensioned drawing."
    )
    assert not dp.threads.isVisibleTo(w) and dp.threads_none.isVisibleTo(w)
    assert dp.ends.item(0).text() == "None: every hole's ends are clear."


# --------------------------------------------------------------------------- page 6
def to_output(app, w) -> None:
    go_to(app, w, 1)
    finish_title(w)
    w.title_page.edits["number"].setText("SS-1")
    go_to(app, w, 5)
    settle(app, w)


def listing(folder) -> list[str]:
    return sorted(os.listdir(folder))


def test_output_page_defaults_and_names(app, open_wizard, made, tmp_path):
    worker = StandIn(answer_of(made))
    w = open_wizard(worker)
    to_output(app, w)
    op = w.output_page
    assert op.folder.text() == str(tmp_path / "parts")  # next to the part
    assert op.drawing_box.isChecked() and not op.drawing_box.isEnabled()
    assert op.pdf_box.isChecked() and op.dxf_box.isChecked() and op.open_editor.isChecked()
    assert op.names_label.text().splitlines() == [
        "Drawing: SS-1.ssdrw",
        "PDF: SS-1 A PRELIMINARY.pdf",
        "DXF: SS-1 A PRELIMINARY.dxf",
    ]
    assert op.isComplete()


def test_a_folder_in_settings_is_the_default(app, open_wizard, made, tmp_path):
    out = tmp_path / "drawings"
    out.mkdir()
    worker = StandIn(answer_of(made))
    w = open_wizard(worker, people_settings(files__folder=str(out)))
    assert w.output_page.folder.text() == str(out)


@pytest.mark.skipif(not hasattr(os, "symlink") or os.name == "nt", reason="a folder link needs symlink")
def test_a_refused_folder_says_why_and_nothing_is_written(app, open_wizard, made, tmp_path):
    worker = StandIn(answer_of(made))
    w = open_wizard(worker)
    to_output(app, w)
    op = w.output_page
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "linked"
    os.symlink(real, link)
    op.folder.setText(str(link))
    reason = document.FOLDER_LINKED
    assert op.folder_label.isVisibleTo(w)
    assert op.folder_label.text() == f"Refused: {reason}. Choose another folder."
    assert not op.isComplete()
    w.accept()
    settle(app, w)
    assert op.status_label.text() == f"Nothing was written: {reason}. Choose another folder."
    assert worker.named("export") == [] and listing(real) == [] and w.isVisible()

    op.folder.setText(str(tmp_path / "missing"))
    assert op.folder_label.text().startswith("Refused: the folder could not be looked at")
    assert not op.isComplete()

    chosen = tmp_path / "chosen"
    chosen.mkdir()
    w.pick_folder = lambda start: str(chosen)
    op.browse.click()
    assert op.folder.text() == str(chosen) and op.isComplete() and not op.folder_label.isVisibleTo(w)


def test_write_drawing_checks_the_folder_again(dw, made, tmp_path):
    if not hasattr(os, "symlink") or os.name == "nt":
        pytest.skip("a folder link needs symlink")
    real = tmp_path / "real"
    real.mkdir()
    os.symlink(real, tmp_path / "linked")
    with pytest.raises(OutputRefusedError, match="link"):
        dw.write_drawing(answer_of(made), str(tmp_path / "linked"), {"pdf": PDF}, str(tmp_path / "p.SLDPRT"))
    assert listing(real) == []


def test_nothing_is_written_before_finish(app, open_wizard, made, tmp_path):
    worker = StandIn(answer_of(made))
    w = open_wizard(worker)
    written = []
    w.drawing_written.connect(lambda path, editor: written.append((path, editor)))
    folder = tmp_path / "parts"
    to_output(app, w)
    w.back()
    w.next()
    settle(app, w)
    assert listing(folder) == ["bracket.SLDPRT"] and worker.named("export") == []
    makes = len(worker.named("make"))

    w.accept()
    settle(app, w, lambda: not w.isVisible())
    assert listing(folder) == [
        "SS-1 A PRELIMINARY.dxf",
        "SS-1 A PRELIMINARY.pdf",
        "SS-1.ssdrw",
        "bracket.SLDPRT",
    ]
    assert written == [(str(folder / "SS-1.ssdrw"), True)]
    assert len(worker.named("make")) == makes  # Finish took the preview made from these options
    assert [c[1] for c in worker.named("export")] == ["pdf", "dxf"]
    assert (folder / "SS-1 A PRELIMINARY.pdf").read_bytes() == PDF
    assert (folder / "SS-1 A PRELIMINARY.dxf").read_bytes() == DXF
    loaded = document.read(folder / "SS-1.ssdrw")
    d = loaded.drawing
    assert d.status == "PRELIMINARY" and d.id == made[0].id
    assert d.model["relative"] == "bracket.SLDPRT"
    assert [(o.kind, o.name, o.released) for o in d.outputs] == [
        ("pdf", "SS-1 A PRELIMINARY.pdf", False),
        ("dxf", "SS-1 A PRELIMINARY.dxf", False),
    ]
    assert d.outputs[0].sha256 == document.file_sha256(str(folder / "SS-1 A PRELIMINARY.pdf"))
    assert w.written is not None and w.written.path == str(folder / "SS-1.ssdrw")


def test_finish_without_exports_or_the_editor(app, open_wizard, made, tmp_path):
    worker = StandIn(answer_of(made))
    w = open_wizard(worker)
    written = []
    w.drawing_written.connect(lambda path, editor: written.append((path, editor)))
    to_output(app, w)
    op = w.output_page
    op.pdf_box.setChecked(False)
    op.dxf_box.setChecked(False)
    op.open_editor.setChecked(False)
    assert op.names_label.text() == "Drawing: SS-1.ssdrw"
    w.accept()
    settle(app, w, lambda: not w.isVisible())
    assert listing(tmp_path / "parts") == ["SS-1.ssdrw", "bracket.SLDPRT"]
    assert written == [(str(tmp_path / "parts" / "SS-1.ssdrw"), False)]
    assert worker.named("export") == []


def test_names_never_replace_a_file_solidseas_did_not_write(app, open_wizard, made, tmp_path):
    folder = tmp_path / "parts"
    worker = StandIn(answer_of(made))
    w = open_wizard(worker)
    theirs = {
        "SS-1.ssdrw": b"someone else's notes\n",
        "SS-1 A PRELIMINARY.pdf": b"%PDF-1.4 written by another program\n",
    }
    for name, data in theirs.items():
        (folder / name).write_bytes(data)
    to_output(app, w)
    names = w.output_page.names_label.text()
    assert (
        "SS-1.ssdrw is taken (it is not this drawing's own unchanged file), so the drawing is saved as "
        in names
    )
    assert "SS-1 (2).ssdrw" in names and "SS-1 A PRELIMINARY (2).pdf" in names

    w.accept()
    settle(app, w, lambda: not w.isVisible())
    for name, data in theirs.items():
        assert (folder / name).read_bytes() == data  # never replaced
    assert listing(folder) == [
        "SS-1 (2).ssdrw",
        "SS-1 A PRELIMINARY (2).pdf",
        "SS-1 A PRELIMINARY.dxf",
        "SS-1 A PRELIMINARY.pdf",
        "SS-1.ssdrw",
        "bracket.SLDPRT",
    ]
    assert w.written.path == str(folder / "SS-1 (2).ssdrw")
    assert len(w.written.words) == 2
    d = document.read(folder / "SS-1 (2).ssdrw").drawing
    assert [o.name for o in d.outputs] == ["SS-1 A PRELIMINARY (2).pdf", "SS-1 A PRELIMINARY.dxf"]
    assert "SS-1 (2).ssdrw" in w.output_page.status_label.text()


def test_an_error_while_writing_keeps_the_wizard_open(app, open_wizard, made, tmp_path):
    class Failing(StandIn):
        def export(self, answer, kind):
            raise ProcessStopped("timeout")

    worker = Failing(answer_of(made))
    w = open_wizard(worker)
    to_output(app, w)
    w.accept()
    settle(app, w)
    assert w.isVisible() and w.written is None
    assert w.output_page.status_label.text() == (
        "The drawing was not written: The drawing process did not finish in time and was ended."
    )
    assert listing(tmp_path / "parts") == ["bracket.SLDPRT"]
    assert w.output_page.isComplete()  # Finish may be pressed again


# --------------------------------------------------------------------------- first use
def test_first_use_offers_drawing_settings_on_the_missing_page(app, open_wizard, made):
    worker = StandIn(answer_of(made))
    pages = []

    def edit_settings(page):
        pages.append(page)
        return people_settings()

    asked = []
    w = open_wizard(
        worker,
        S.DrawingSettings(),
        ask=lambda title, text: asked.append(text) or True,
        edit_settings=edit_settings,
        show=False,
    )
    assert w.part_page.first_use_label.isVisibleTo(w) is False  # not shown yet
    w.show()
    settle(app, w)
    assert len(asked) == 1
    assert asked[0].startswith("Drawing Settings still need these before your first drawing:")
    assert "Type your company's legal name" in asked[0]
    assert pages == ["Standard and Units"]
    assert w.settings.company.name == COMPANY
    assert not w.part_page.first_use_label.isVisibleTo(w) and not w.part_page.settings_button.isVisibleTo(w)
    assert [w.title_page.drawn_by.itemText(i) for i in range(2)] == ["Ann Bee", "Carl Dee"]


def test_settings_read_from_their_file_and_their_fallbacks(app, open_wizard, made, tmp_path):
    (tmp_path / "Drawing.json").write_text(
        '{"schema": "solidseas.drawing-settings/1", "company": {"name": "Example Engineering Co.", '
        '"phone": 12}, "people": {"people": [{"name": "Ann Bee"}]}, '
        '"standard": {"unit_for_unstated": "mm"}}',
        encoding="utf-8",
    )
    worker = StandIn(answer_of(made))
    from solidseas_app.viewer import drawingwizard

    w = drawingwizard.DrawingWizard(
        None, worker, str(tmp_path / "x.SLDPRT"), settings_path=str(tmp_path / "Drawing.json")
    )
    try:
        assert w.settings.company.name == COMPANY
        assert w.settings_problems == ["company.phone: it is not text; the default is used"]
        assert w.part_page.settings_label.text().endswith(
            "company.phone: it is not text; the default is used"
        )
        assert not w.part_page.first_use_label.text()
    finally:
        w.done(0)
        w.pool.waitForDone(10_000)
        w.deleteLater()


def test_first_use_declined_keeps_the_offer_on_page_one(app, open_wizard, made):
    worker = StandIn(answer_of(made))
    pages = []
    s = S.with_value(people_settings(), "company", "name", "")

    def edit_settings(page):
        pages.append(page)
        return None  # cancelled

    w = open_wizard(worker, s, edit_settings=edit_settings)
    assert len(w.questions) == 1 and pages == []
    page = w.part_page
    assert page.first_use_label.isVisibleTo(w) and page.settings_button.isVisibleTo(w)
    assert "Type your company's legal name (Company)" in page.first_use_label.text()
    page.settings_button.click()
    assert pages == ["Company"]
    assert page.isComplete()  # the drawing can be made all the same; its checks say what is missing


# --------------------------------------------------------------------------- the preview
class Blocking(StandIn):
    """A child whose first make waits until it is cancelled, as a slow part's would."""

    def __init__(self, answer) -> None:
        super().__init__(answer)
        self.waiting = threading.Event()
        self.ended = threading.Event()

    def make(self, part, options, fields, settings, progress=None):
        self.calls.append(("make", part, options, dict(fields), settings))
        if len(self.named("make")) == 1:
            self.waiting.set()
            if not self.ended.wait(30):
                raise AssertionError("the first make was never cancelled")
            raise ProcessStopped("cancelled")
        return self.answer

    def cancel(self) -> bool:
        if self.waiting.is_set() and not self.ended.is_set():
            self.cancels += 1
            self.ended.set()
            return True
        return False


def test_a_newer_request_cancels_the_preview_in_progress(app, open_wizard, made):
    worker = Blocking(answer_of(made))
    w = open_wizard(worker, show=False)
    w.preview_delay_ms = 50
    w.show()
    settle(app, w, worker.waiting.is_set, timeout=10)  # the first preview starts on page 1
    assert w.preview_status.text() == "Making the preview..."
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(5)
    try:
        settle(app, w, lambda: len(ticks) >= 5, timeout=10)  # the window answers while the child works
    finally:
        timer.stop()
    assert w.answer is None and len(worker.named("make")) == 1
    w.title_page.edits["title"].setText("BRACKET, NEWER")
    settle(app, w)
    assert worker.cancels == 1 and w.cancelled_requests == 1
    assert len(worker.named("make")) == 2
    assert worker.last_make()[3]["title"] == "BRACKET, NEWER"
    assert w.answer is not None and dict(w.answer_request.fields)["title"] == "BRACKET, NEWER"
    assert w.preview_status.text().startswith("PRELIMINARY, as the drawing will be written.")
    assert w.scene.owners()  # the sheet is shown


def test_the_preview_follows_changes_after_a_pause(app, open_wizard, made):
    worker = StandIn(answer_of(made))
    w = open_wizard(worker)
    go_to(app, w, 1)
    makes = len(worker.named("make"))
    w.preview_delay_ms = 60_000
    for text in ("B", "BR", "BRACKET"):
        w.title_page.edits["title"].setText(text)
    app.processEvents()
    assert len(worker.named("make")) == makes and w.timer.isActive()  # not while the user types
    w.request_preview()
    settle(app, w)
    assert len(worker.named("make")) == makes + 1 and worker.last_make()[3]["title"] == "BRACKET"
    assert w.request_preview() is False  # the same options are not made twice
    assert w.preview_panel.isVisibleTo(w)
    w.back()
    assert w.preview_panel.isVisibleTo(w)  # on page 1 as well


def test_the_preview_starts_on_page_1_once_the_part_is_read(app, open_wizard, made):
    # the user saw an empty window on page 1 and took the drawing for hung: page 1 shows
    # the preview as soon as the part is read, and the bar while it is read and drawn
    worker = Blocking(answer_of(made))
    w = open_wizard(worker, show=False)
    w.show()
    bar = w.preview_progress
    assert w.preview_panel.isVisibleTo(w) and bar.isVisibleTo(w) and bar.format() == "Reading the part..."
    settle(app, w, worker.waiting.is_set, timeout=10)
    assert w.currentId() == 0 and bar.isVisibleTo(w) and bar.format() == "Starting the drawing process..."
    assert w.preview_status.text() == "Making the preview..."
    w.title_page.edits["title"].setText("BRACKET, NEWER")  # a newer request ends the slow one
    settle(app, w)
    assert w.currentId() == 0 and w.answer is not None and w.scene.owners() and not bar.isVisibleTo(w)


def test_the_preview_shows_each_stage_on_its_bar(app, open_wizard, made, dw):
    worker = Blocking(answer_of(made))
    w = open_wizard(worker, show=False)
    w.show()
    settle(app, w, worker.waiting.is_set, timeout=10)  # the first make waits, as a slow part's would
    bar = w.preview_progress
    assert bar.isVisibleTo(w) and bar.value() == 0 and bar.format() == "Starting the drawing process..."
    w._preview_progress({"stage": "views", "gen": w._gen})
    assert bar.value() == dw.STAGE_START["views"] and bar.format() == "Drawing the views..."
    w._preview_progress({"stage": "plan", "gen": w._gen - 1})  # an older request's is not shown
    assert bar.format() == "Drawing the views..."
    w.title_page.edits["title"].setText("BRACKET, NEWER")  # the newer request ends this one
    settle(app, w)
    assert w.answer is not None and not bar.isVisibleTo(w)  # gone once the preview is shown


def test_the_stages_the_child_says_move_the_bar(app, open_wizard, made, dw):
    w = open_wizard(StandIn(answer_of(made)), show=False)
    values: list[int] = []
    w.preview_progress.valueChanged.connect(values.append)
    w.show()
    settle(app, w)  # the preview is made on page 1
    starts = [dw.STAGE_START[stage] for stage in ("model", "features", "views", "plan", "assemble")]
    assert set(starts) <= set(values) and values[-1] == dw.STAGE_START["assemble"]
    assert not w.preview_progress.isVisibleTo(w)


def test_the_preview_takes_the_room_the_pages_do_not_need(app, open_wizard, made, dw):
    w = open_wizard(StandIn(answer_of(made)))
    go_to(app, w, 1)
    w.resize(1700, 950)
    settle(app, w)
    assert w.view.width() > 900 and w.currentPage().width() < dw.PAGE_WIDTH + 100
    w.resize(1150, 800)
    settle(app, w)
    assert 460 <= w.view.width() < 600  # and it gives the room back as the window shrinks


def test_view_larger_shows_the_preview_in_its_own_window(app, open_wizard, made):
    w = open_wizard(StandIn(answer_of(made)), show=False)
    assert not w.larger_button.isEnabled()  # nothing to show before a preview
    w.show()
    settle(app, w)
    assert w.larger_button.isEnabled()
    win = w.view_larger()
    assert win.isVisible() and win.view.scene() is w.scene and win.view.fitted
    assert w.view_larger() is win  # one window, shown again
    win.close()


def test_a_preview_that_fails_says_why(app, open_wizard, made):
    class Failing(StandIn):
        def make(self, part, options, fields, settings, progress=None):
            self.calls.append(("make", part, options, dict(fields), settings))
            raise ProcessStopped("too_large")

    worker = Failing(answer_of(made))
    w = open_wizard(worker)
    go_to(app, w, 1)
    assert w.preview_status.text() == (
        "The preview could not be made: The drawing needed more memory than the viewer lets its drawing "
        "process use."
    )
    assert w.answer is None


def test_the_options_the_request_carries(app, open_wizard, made, dw):
    worker = StandIn(answer_of(made))
    w = open_wizard(worker)
    request = w.current_request()
    assert request.options == DrawingOptions(
        configuration="Default", scheme="datum", hidden=False, tangent="hidden"
    )
    assert request.settings == w.settings and request.edits == ()


# --------------------------------------------------------------------------- the real child
def test_the_real_child_draws_o02_end_to_end(app, open_wizard, tmp_path):
    from solidseas_app.viewer.drawingproc import DrawingWorker

    worker = DrawingWorker()
    try:
        w = open_wizard(worker)
        written = []
        w.drawing_written.connect(lambda path, editor: written.append((path, editor)))
        assert w.probe.name == "bracket.SLDPRT" and w.probe.unit_origin == "file"
        assert (
            w.part_page.size_label.text()
            == "Overall size: 10.00 x 20.00 x 30.00 mm (0.394 x 0.787 x 1.181 in)"
        )
        go_to(app, w, 1)
        finish_title(w)
        w.title_page.edits["number"].setText("SS-1")
        settle(app, w)
        assert w.answer is not None and w.scene.owners()
        go_to(app, w, 5)
        folder = tmp_path / "parts"
        assert listing(folder) == ["bracket.SLDPRT"]
        w.accept()
        settle(app, w, lambda: not w.isVisible(), timeout=120)
        assert written == [(str(folder / "SS-1.ssdrw"), True)]
        assert listing(folder) == [
            "SS-1 A PRELIMINARY.dxf",
            "SS-1 A PRELIMINARY.pdf",
            "SS-1.ssdrw",
            "bracket.SLDPRT",
        ]
        d = document.read(folder / "SS-1.ssdrw").drawing
        assert d.status == "PRELIMINARY" and document.title_text(d, "number") == "SS-1"
        assert d.model["relative"] == "bracket.SLDPRT" and d.model["stored"] is None
        assert [(s.row, s.name) for s in d.signatures] == [("DRAWN", "Ann Bee")]
        for o in d.outputs:
            path = str(folder / o.name)
            assert o.sha256 == document.file_sha256(path) and document.says_solidseas(path, o.kind)
        assert (folder / "SS-1 A PRELIMINARY.pdf").read_bytes().startswith(b"%PDF-")
    finally:
        worker.close()


def test_the_real_child_draws_an_assembly_end_to_end(app, open_wizard, tmp_path):
    from solidseas_app.viewer.drawingproc import DrawingWorker

    folder = tmp_path / "frame"
    folder.mkdir()
    for name in ("o15_sub_asm.SLDASM", "o02_boxA.SLDPRT", "o07_boxB_h31.SLDPRT"):
        shutil.copyfile(fixture_path(name), folder / name)  # the assembly and its parts, by their names
    worker = DrawingWorker()
    try:
        w = open_wizard(worker, part=str(folder / "o15_sub_asm.SLDASM"))
        assert w.is_assembly and (w.probe.assembly.items, w.probe.assembly.instances) == (2, 2)
        pp = w.part_page
        assert pp.bodies_label.text() == "Instances drawn:"
        assert [pp.bodies.item(i).text() for i in range(pp.bodies.count())] == [
            "o02_boxA-1",
            "o07_boxB_h31-1",
        ]
        assert pp.size_label.text().endswith("The parts list has 2 items; 2 part instances are drawn.")
        settle(app, w, lambda: w.answer is not None, timeout=120)  # the preview, from page 1
        assert w.currentId() == 0 and {"parts", "balloon-1", "balloon-2"} <= set(w.scene.owners())
        go_to(app, w, 1)
        tp = w.title_page
        assert not tp.form.isRowVisible(tp.material) and not tp.form.isRowVisible(tp.finish)
        assert tp.assembly_label.isVisibleTo(tp) and w.page_problems(1) == []  # no finish to choose
        tp.edits["number"].setText("SS-9")
        settle(app, w)
        w.next()
        settle(app, w)
        assert w.currentId() == 3  # past how a part is made
        vp = w.views_page
        assert [name for name, box in vp.views.items() if box.isChecked()] == ["top", "right"]
        assert vp.isometric.isChecked() and not vp.hidden.isChecked()
        w.next()
        settle(app, w)
        assert w.currentId() == 5  # past the dimensions
        request = w.current_request()
        fields = dict(request.fields)
        assert request.options.hidden is False and "material" not in fields and "finish" not in fields
        assert w.answer is not None and {"parts", "balloon-1", "balloon-2"} <= set(w.scene.owners())
        w.accept()
        settle(app, w, lambda: not w.isVisible(), timeout=120)
        assert listing(folder) == [
            "SS-9 A PRELIMINARY.dxf",
            "SS-9 A PRELIMINARY.pdf",
            "SS-9.ssdrw",
            "o02_boxA.SLDPRT",
            "o07_boxB_h31.SLDPRT",
            "o15_sub_asm.SLDASM",
        ]
        d = document.read(folder / "SS-9.ssdrw").drawing
        assert d.model["format"] == "sldasm" and d.model["relative"] == "o15_sub_asm.SLDASM"
        assert [len(a.rows) for a in d.sheet.annotations if type(a).__name__ == "PartsList"] == [2]
    finally:
        worker.close()
