"""Guided drawings (``solidseas_app.viewer.drawingguided``; ``docs/DRAWINGS.md`` 10.4b).

The Guided wizard asks its questions in turn and sends the New Drawing wizard's
request, so these tests read what each answer puts in the options and fields the
stand-in drawing process is asked to make, as ``test_viewer_drawing_wizard`` does, with
its stand-in and canned answers. Finish writes into each test's temporary folder only,
from a copy of o02 under a fictional name. Everything runs offscreen and is skipped
without PySide6; no dialog is opened.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import replace

import pytest

try:
    import PySide6.QtWidgets  # noqa: F401
except ImportError:  # the window's tests need the [app] extra
    pytest.skip("PySide6 is not installed: the Guided wizard is not tested", allow_module_level=True)

from PySide6.QtWidgets import QApplication

from solidseas import drawing
from solidseas.drawing import document
from solidseas.drawing import settings as S
from solidseas.drawing.numbers import UnitGuess
from solidseas_app.viewer.drawingproc import AssemblyProbe
from support import fixture_path
from test_viewer_drawing_wizard import (
    GUESSED,
    PDF,
    StandIn,
    answer_of,
    holes_answer,
    people_settings,
    probe_of,
    settle,
)


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from solidseas_app.viewer.app import use_system_fonts

    use_system_fonts()
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def G(app):
    from solidseas_app.viewer import drawingguided

    return drawingguided


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    """o02's drawing as the library makes it (number SS-1), as the stand-in answers."""
    root = tmp_path_factory.mktemp("guided-canned")
    part = root / "bracket.SLDPRT"
    shutil.copyfile(fixture_path("o02_boxA.SLDPRT"), part)
    fields = {"number": "SS-1", "drawn_by": "Ann Bee", "finish": "NONE"}
    d = drawing.make_drawing(str(part), fields=fields, settings=people_settings())
    data = document.dumps(d)
    loaded, problems = document.loads(data)
    assert problems == []
    return d, data, loaded


@pytest.fixture
def open_guided(app, G, tmp_path):
    """``open_guided(worker, settings=None, source="o02_boxA.SLDPRT", name="bracket.SLDPRT")``:
    a Guided wizard of a copy of ``source`` under ``name`` in the test's folder, shown and
    with its part read; closed after the test."""
    made_wizards = []
    (tmp_path / "parts").mkdir()

    def make(worker, settings=None, source="o02_boxA.SLDPRT", name="bracket.SLDPRT"):
        part = tmp_path / "parts" / name
        shutil.copyfile(fixture_path(source), part)
        w = G.GuidedWizard(
            None,
            worker,
            str(part),
            settings=people_settings() if settings is None else settings,
            settings_path=str(tmp_path / "Drawing.json"),
        )
        w.preview_delay_ms = 0
        w.ask = lambda title, text: False
        w.edit_settings = lambda page: None
        w.pick_folder = lambda start: ""
        made_wizards.append(w)
        w.show()
        settle(app, w)
        return w

    yield make
    for w in made_wizards:
        w.done(0)
        w.pool.waitForDone(10_000)
        w.deleteLater()
    app.processEvents()


def walk(app, w, until: int) -> list[int]:
    """Next until page ``until``; the pages shown on the way."""
    shown = [w.currentId()]
    while w.currentId() != until:
        before = w.currentId()
        w.next()
        settle(app, w)
        assert w.currentId() != before, w.guided_problems(before) or w.page_problems(before)
        shown.append(w.currentId())
    return shown


def request(w):
    r = w.current_request()
    assert r is not None
    return r


def test_the_questions_come_in_order_each_saying_why(app, open_guided, made, G):
    w = open_guided(StandIn(answer_of(made)))
    assert w.windowTitle() == "Guided Drawing of bracket.SLDPRT"
    shown = walk(app, w, G.SUMMARY)
    assert shown == [G.PURPOSE, G.VIEWS, G.UNITS, G.DETAIL, 1, G.SUMMARY]
    titles = [w.page(i).title() for i in shown]
    assert titles == [
        "What is the drawing for?",
        "Which views should the sheet show?",
        "Which unit should the sizes be in?",
        "How much should the drawing dimension?",
        "What should the title block say?",
        "Ready to make the drawing",
    ]
    assert all(w.page(i).subTitle() for i in shown), "each question says why it matters"
    assert w.nextId() == -1, "the last page finishes"
    # the wizard's other pages are kept as the answers' store, never shown
    assert not any(p.isVisible() for p in w.pages if p is not w.title_page)


@pytest.mark.parametrize(
    "key, process, detail, scheme",
    [
        ("quote", "machined", "simplified", "plusminus"),
        ("print", "printed", "simplified", "plusminus"),
        ("plain", "machined", "complex", "plusminus"),
        ("shop", "machined", "full", "datum"),
    ],
)
def test_each_purpose_chooses_the_process_and_detail_level(
    app, open_guided, made, key, process, detail, scheme
):
    worker = StandIn(answer_of(made))
    w = open_guided(worker)
    w.purpose_page.buttons[key].click()
    settle(app, w)
    options = worker.last_make()[2]
    assert (options.process, options.detail, options.scheme) == (process, detail, scheme)
    assert options.mode == "expert", "a Guided drawing is an ordinary drawing"
    fields = worker.last_make()[3]
    first = S.DrawingSettings().printing.processes[0]["name"]
    assert fields.get("process") == (first if key == "print" else None)


def test_the_purpose_starts_from_the_default_detail_level(app, open_guided, made):
    w = open_guided(StandIn(answer_of(made)), people_settings(defaults__detail="simplified"))
    assert w.purpose == "quote" and w.purpose_page.buttons["quote"].isChecked()
    assert request(w).options.detail == "simplified"


def test_a_printing_process_is_chosen_from_drawing_settings(app, open_guided, made):
    worker = StandIn(answer_of(made))
    w = open_guided(worker)
    pp = w.purpose_page
    assert not pp.printing.isVisibleTo(w), "asked only for a 3D print"
    pp.buttons["print"].click()
    assert pp.printing.isVisibleTo(w) and pp.process.count() == w.manufacturing_page.process.count()
    pp.process.setCurrentIndex(1)
    settle(app, w)
    name = pp.process.itemText(1)
    assert worker.last_make()[3]["process"] == name
    assert pp.figures_label.text().startswith(name)


def test_without_a_printing_process_3d_printing_is_off_and_says_why(app, open_guided, made):
    w = open_guided(StandIn(answer_of(made)), people_settings(printing__processes=[]))
    pp = w.purpose_page
    assert not pp.buttons["print"].isEnabled()
    assert pp.no_process_label.isVisibleTo(w)
    w.purpose_chosen("print")
    assert w.purpose == "quote", "nothing to print with"


def test_the_views_ticked_are_the_views_drawn(app, open_guided, made, G):
    worker = StandIn(answer_of(made))
    w = open_guided(worker)
    walk(app, w, G.VIEWS)
    vp = w.guided_views_page
    defaults = S.DrawingSettings().defaults.views["machined"]
    assert [n for n, b in vp.boxes.items() if b.isChecked()] == [v for v in defaults["views"] if v != "front"]
    assert vp.isometric.isChecked() == bool(defaults["isometric"])
    assert request(w).options.views == "auto", "the defaults, as the wizard sends them"
    vp.boxes["top"].setChecked(False)
    vp.isometric.setChecked(True)
    settle(app, w)
    assert worker.last_make()[2].views == ("front", "right", "isometric")
    # the user's views are kept when the purpose changes
    w.purpose_chosen("print")
    assert request(w).options.views == ("front", "right", "isometric")


def test_the_unit_offered_is_the_parts_own_and_another_is_drawn_in(app, open_guided, made, G):
    worker = StandIn(answer_of(made))
    w = open_guided(worker)
    walk(app, w, G.UNITS)
    up = w.units_page
    assert up.mm.isChecked() and not up.inch.isChecked()
    assert up.source_label.text() == "The part is modelled in millimetres."
    assert request(w).options.units == "part"
    up.inch.click()
    settle(app, w)
    assert worker.last_make()[2].units == "in"


def test_a_part_that_states_no_unit_offers_the_guess_with_its_evidence(app, open_guided, made, G):
    worker = StandIn(answer_of(made), probe_of(**GUESSED))
    w = open_guided(worker)
    walk(app, w, G.UNITS)
    up = w.units_page
    assert up.inch.isChecked()
    assert "looks like inch (41 of 47 sizes are whole thousandths)" in up.source_label.text()
    assert worker.last_make()[2].units == "in"


def test_an_unclear_guess_waits_for_a_unit(app, open_guided, made, G):
    unclear = {**GUESSED, "evidence": UnitGuess("in", 20, 6, 6, 0, 47, False)}
    worker = StandIn(answer_of(made), probe_of(**unclear))
    w = open_guided(worker)
    assert worker.named("make") == [], "nothing is made before a unit is chosen"
    assert w.preview_status.text().startswith("No preview yet: the part states no unit")
    walk(app, w, G.UNITS)
    up = w.units_page
    assert not up.inch.isChecked() and not up.mm.isChecked() and not up.isComplete()
    up.mm.click()
    settle(app, w)
    assert up.isComplete() and worker.last_make()[2].units == "mm"


def test_settings_that_fix_the_unit_offer_it_and_allow_the_other(app, open_guided, made, G):
    worker = StandIn(answer_of(made), probe_of(**GUESSED))
    w = open_guided(worker, people_settings(standard__units="mm"))
    walk(app, w, G.UNITS)
    assert w.units_page.mm.isChecked()
    assert request(w).options.units == "part"
    w.units_page.inch.click()
    assert request(w).options.units == "in"


def test_the_detail_page_changes_the_level_the_purpose_chose(app, open_guided, made, G):
    worker = StandIn(answer_of(made))
    w = open_guided(worker)
    walk(app, w, G.DETAIL)
    dp = w.detail_page
    assert dp.buttons["full"].isChecked()
    assert "datums" in dp.scheme_label.text()
    dp.buttons["complex"].click()
    settle(app, w)
    options = worker.last_make()[2]
    assert (options.detail, options.scheme) == ("complex", "plusminus")
    assert "plus and minus" in dp.scheme_label.text()


def test_the_title_block_page_is_the_wizards_own(app, open_guided, made, G):
    worker = StandIn(answer_of(made))
    w = open_guided(worker)
    walk(app, w, 1)
    w.title_page.edits["number"].setText("BR-100")
    w.title_page.edits["revision"].setText("I")
    assert not w.title_page.isComplete(), "a revision mark is checked as in the wizard"
    w.title_page.edits["revision"].setText("b")
    settle(app, w)
    fields = worker.last_make()[3]
    assert fields["number"] == "BR-100" and fields["revision"] == "B" and fields["drawn_by"] == "Ann Bee"


def test_finish_writes_the_drawing_and_a_pdf_and_opens_the_editor(app, open_guided, made, G, tmp_path):
    worker = StandIn(answer_of(made))
    w = open_guided(worker)
    written = []
    w.drawing_written.connect(lambda path, editor: written.append((path, editor)))
    walk(app, w, G.SUMMARY)
    sp = w.summary_page
    text = sp.answers_label.text().splitlines()
    assert text == [
        "Part: bracket.SLDPRT, configuration Default",
        "For: to have it machined in a shop",
        "Views: Front, top and right, and an isometric",
        "Unit: millimetre",
        "Dimensions: Every feature, fully defined",
    ]
    assert "Drawing number: SS-1" in sp.title_label.text()
    assert "Drawn by: Ann Bee" in sp.title_label.text()
    folder = tmp_path / "parts"
    assert sp.folder_label.text() == f"Saved in: {folder}"
    assert sp.pdf_box.isChecked() and not sp.dxf_box.isChecked()
    assert sp.names_label.text().splitlines() == ["Drawing: SS-1.ssdrw", "PDF: SS-1 A PRELIMINARY.pdf"]
    assert sp.isComplete()
    w.accept()
    settle(app, w, lambda: not w.isVisible())
    assert sorted(os.listdir(folder)) == ["SS-1 A PRELIMINARY.pdf", "SS-1.ssdrw", "bracket.SLDPRT"]
    assert (folder / "SS-1 A PRELIMINARY.pdf").read_bytes() == PDF
    assert written == [(str(folder / "SS-1.ssdrw"), True)]
    assert [c[1] for c in worker.named("export")] == ["pdf"]


def test_the_summary_ticks_choose_the_exports(app, open_guided, made, G, tmp_path):
    worker = StandIn(answer_of(made))
    w = open_guided(worker)
    walk(app, w, G.SUMMARY)
    sp = w.summary_page
    sp.pdf_box.setChecked(False)
    sp.dxf_box.setChecked(True)
    assert w.kinds() == ["dxf"]
    w.accept()
    settle(app, w, lambda: not w.isVisible())
    assert [c[1] for c in worker.named("export")] == ["dxf"]


def test_another_folder_is_chosen_from_the_summary(app, open_guided, made, G, tmp_path):
    out = tmp_path / "drawings"
    out.mkdir()
    w = open_guided(StandIn(answer_of(made)))
    w.pick_folder = lambda start: str(out)
    walk(app, w, G.SUMMARY)
    w.summary_page.browse.click()
    assert w.summary_page.folder_label.text() == f"Saved in: {out}"
    assert not w.summary_page.problem_label.isVisibleTo(w)


def test_an_assembly_is_not_asked_how_it_is_made_or_dimensioned(app, open_guided, made, G):
    probe = probe_of(assembly=AssemblyProbe(2, 2), bodies=())
    w = open_guided(StandIn(answer_of(made), probe))
    pp = w.purpose_page
    assert pp.assembly_label.isVisibleTo(w) and not pp.choices.isVisibleTo(w)
    shown = walk(app, w, G.SUMMARY)
    assert G.DETAIL not in shown
    assert "For: an assembly drawing, with its parts list and balloons" in w.summary_page.answers_label.text()


def test_a_refused_part_stops_on_the_first_question(app, open_guided, made, G):
    probe = replace(probe_of(), refused="it is larger than the drawing bounds")
    w = open_guided(StandIn(answer_of(made), probe))
    pp = w.purpose_page
    assert pp.status_label.text() == "SolidSeas cannot draw this part: it is larger than the drawing bounds."
    assert not pp.isComplete()
    w.next()
    settle(app, w)
    assert w.currentId() == G.PURPOSE


def test_holes_sized_as_tap_drills_are_asked_about(app, open_guided, made, G):
    worker = StandIn(holes_answer(made))
    w = open_guided(worker)
    shown = walk(app, w, G.SUMMARY)
    assert shown == [G.PURPOSE, G.VIEWS, G.UNITS, G.DETAIL, G.THREADS, 1, G.SUMMARY]
    tp = w.threads_page
    assert tp.title() == "Are any of these holes threaded?"
    assert "tap drill" in tp.subTitle() and "plain hole" in tp.subTitle()
    assert list(tp.boxes) == ["f-1", "f-2", "f-3"]
    assert [tp.form.itemAt(k, tp.form.ItemRole.LabelRole).widget().text() for k in range(3)] == [
        "4 holes, Ø5.00 mm (f-1)",
        "1 hole, Ø5.11 mm (f-2)",
        "1 hole, Ø3.30 mm (f-3)",
    ]
    box = tp.boxes["f-1"]
    assert [box.itemText(i) for i in range(box.count())] == ["No, a plain hole", "Yes, M6 x 1"]
    assert all(b.currentIndex() == 0 for b in tp.boxes.values()), "plain until a thread is chosen"
    assert "Threaded holes: none, all drawn plain" in w.summary_page.answers_label.text().splitlines()
    w.back()
    w.back()
    settle(app, w)
    assert w.currentId() == G.THREADS
    assert tp.note_label.isVisibleTo(w) and not tp.status_label.isVisibleTo(w)
    box.setCurrentIndex(1)
    tp.boxes["f-2"].setCurrentIndex(0)
    settle(app, w)
    # the answer is the wizard's own: its thread table, its edits, the request it sends
    dp = w.dimensions_page
    assert dp.rows["f-1"][0].currentData() == "tapped" and dp.rows["f-1"][1].currentText() == "M6 x 1"
    assert w.thread_answers == {"f-1": ("tapped", "M6 x 1", 0.0)}
    assert request(w).edits == (("confirm_thread", ("f-1", "M6 x 1-6H", None)),)
    assert ("edit", "confirm_thread", ["f-1", "M6 x 1-6H", None]) in worker.calls
    # the answer stays when the preview comes back, and No takes it back
    assert tp.boxes["f-1"].currentIndex() == 1
    tp.boxes["f-1"].setCurrentIndex(0)
    settle(app, w)
    assert dp.rows["f-1"][0].currentData() == "plain" and request(w).edits == ()
    tp.boxes["f-1"].setCurrentIndex(1)
    walk(app, w, G.SUMMARY)
    assert "Threaded holes: f-1 as M6 x 1" in w.summary_page.answers_label.text().splitlines()


def test_a_part_without_tap_drill_holes_is_not_asked(app, open_guided, made, G):
    w = open_guided(StandIn(answer_of(made)))
    assert w.thread_candidates() == () and G.THREADS not in w.order()
    walk(app, w, G.SUMMARY)
    assert not any(line.startswith("Threaded") for line in w.summary_page.answers_label.text().splitlines())


def test_the_holes_wait_for_the_preview(app, open_guided, made, G):
    unclear = {**GUESSED, "evidence": UnitGuess("in", 20, 6, 6, 0, 47, False)}
    worker = StandIn(holes_answer(made), probe_of(**unclear))
    w = open_guided(worker)
    assert w.thread_candidates() is None and G.THREADS in w.order(), "not known before the preview"
    w.show_threads()
    assert not w.threads_page.isComplete()
    assert w.threads_page.status_label.text().startswith("Looking for holes that may be threaded")
    walk(app, w, G.UNITS)
    w.units_page.inch.click()
    settle(app, w)
    walk(app, w, G.THREADS)
    tp = w.threads_page
    assert tp.isComplete() and tp.boxes["f-2"].itemText(1) == "Yes, 1/4-20 UNC"
    labels = [tp.form.itemAt(k, tp.form.ItemRole.LabelRole).widget().text() for k in range(3)]
    assert labels[1] == "1 hole, Ø0.201 in (f-2)", "sized in the drawing's unit"


def test_holes_not_checked_say_so_and_go_on(app, open_guided, made, G):
    class Failing(StandIn):
        def make(self, part, options, fields, settings, progress=None):
            self.calls.append(("make", part, options, dict(fields), settings))
            raise RuntimeError("the drawing process stopped")

    w = open_guided(Failing(holes_answer(made)))
    walk(app, w, G.THREADS)
    tp = w.threads_page
    assert tp.isComplete() and tp.status_label.text().startswith("The holes could not be checked")
    assert not tp.holes.isVisibleTo(w)


def test_an_assembly_is_not_asked_about_threads(app, open_guided, made, G):
    probe = probe_of(assembly=AssemblyProbe(2, 2), bodies=())
    w = open_guided(StandIn(holes_answer(made), probe))
    assert G.THREADS not in walk(app, w, G.SUMMARY)


def test_the_real_child_threads_a_tap_drill_hole(app, open_guided, G, tmp_path):
    """o10's 5 mm hole is a tap drill for M6 x 1, as the wizard's thread table finds it."""
    from solidseas_app.viewer.drawingproc import DrawingWorker

    worker = DrawingWorker()
    try:
        w = open_guided(worker, source="o10_import_step_cut.SLDPRT", name="plate.SLDPRT")
        w.purpose_page.buttons["quote"].click()
        walk(app, w, G.THREADS)
        settle(app, w)
        tp = w.threads_page
        assert list(tp.boxes) == ["f-1"] and tp.boxes["f-1"].itemText(1) == "Yes, M6 x 1"
        tp.boxes["f-1"].setCurrentIndex(1)
        settle(app, w)
        assert request(w).edits == (("confirm_thread", ("f-1", "M6 x 1-6H", None)),)
        walk(app, w, 1)
        w.title_page.edits["number"].setText("SS-2")
        walk(app, w, G.SUMMARY)
        settle(app, w)
        assert "Threaded holes: f-1 as M6 x 1" in w.summary_page.answers_label.text()
        w.accept()
        settle(app, w, lambda: not w.isVisible(), timeout=120)
        saved = tmp_path / "parts" / "SS-2.ssdrw"
        d = document.read(saved).drawing
        assert dict(d.features[0].decisions)["thread"].upper() == "M6 X 1-6H"
        assert "M6 X 1-6H" in saved.read_text(encoding="utf-8").upper(), "called out on the sheet"
    finally:
        worker.close()


def test_hole_words(G):
    hole = {"feature": "f-2", "count": 1, "diameter_mm": 5.1054}
    assert G.hole_words(hole, "mm") == "1 hole, Ø5.11 mm (f-2)"
    assert G.hole_words(hole, None) == "1 hole, Ø5.11 mm (f-2)"
    assert G.hole_words({**hole, "count": 4}, "in") == "4 holes, Ø0.201 in (f-2)"


def test_the_real_child_makes_a_guided_drawing_end_to_end(app, open_guided, G, tmp_path):
    from solidseas_app.viewer.drawingproc import DrawingWorker

    worker = DrawingWorker()
    try:
        w = open_guided(worker)
        written = []
        w.drawing_written.connect(lambda path, editor: written.append((path, editor)))
        assert w.purpose_page.size_label.text().startswith("Overall size: 10.00 x 20.00 x 30.00 mm")
        w.purpose_page.buttons["quote"].click()
        walk(app, w, 1)
        w.title_page.edits["number"].setText("SS-1")
        walk(app, w, G.SUMMARY)
        settle(app, w)
        assert w.answer is not None and "Drawing number: SS-1" in w.summary_page.title_label.text()
        w.accept()
        settle(app, w, lambda: not w.isVisible(), timeout=120)
        folder = tmp_path / "parts"
        assert written == [(str(folder / "SS-1.ssdrw"), True)]
        assert sorted(os.listdir(folder)) == ["SS-1 A PRELIMINARY.pdf", "SS-1.ssdrw", "bracket.SLDPRT"]
        d = document.read(folder / "SS-1.ssdrw").drawing
        assert d.status == "PRELIMINARY" and d.options.detail == "simplified" and d.options.mode == "expert"
        assert [(s.row, s.name) for s in d.signatures] == [("DRAWN", "Ann Bee")]
    finally:
        worker.close()


def test_views_words(G):
    assert G.views_words([], False) == "Front"
    assert G.views_words(["top"], True) == "Front and top, and an isometric"
    assert G.views_words(["top", "right"], False) == "Front, top and right"


def test_the_experimental_note_shows_on_every_question(app, open_guided, made, G):
    from solidseas_app.viewer import experimental

    w = open_guided(StandIn(answer_of(made)))
    note = w.experimental_note
    assert note.text() == experimental.drawings_note()
    assert note.isVisibleTo(w), "Guided drawings are experimental, as Expert ones are"
    walk(app, w, G.SUMMARY)
    assert note.isVisibleTo(w), "and the note stays through the last question"
