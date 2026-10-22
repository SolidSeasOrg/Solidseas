"""Views on the sheets after a drawing's first (``docs/DRAWINGS.md`` 11.7): the isometric
put on a sheet of its own (``DrawingOptions.view_sheets``, ``edit.set_view_sheet``), laid
out there above the continuation title block, written as a page or a side-by-side sheet
of its own, kept in the drawing file, and the isometric with no room reported with the
way to give it some.

The parts are o02 and the synthetic sixteen-hole plate of the goldens, whose isometric
has no room on its sheet; the assembly is the long parts list of
``test_drawing_assembly``.
"""

from __future__ import annotations

import functools
import io
import json

import pytest

import drawing_golden_support as G
import drawing_parts
from drawing_support import fixture
from pdf_reader import PdfDocument
from solidseas import drawing
from solidseas.drawing import display as D
from solidseas.drawing import document, edit, pipeline
from solidseas.drawing import types as T
from solidseas.drawing.layout import arrange as A
from solidseas.drawing.layout import place
from solidseas.drawing.layout import sheet as SH
from solidseas.drawing.limits import DrawingLimits
from solidseas.drawing.pdf import write_pdf
from solidseas.errors import InvalidArgumentError

APART = T.DrawingOptions(view_sheets=(("isometric", 2),))


@functools.cache
def o02(view_sheets=()):
    return drawing.make_drawing(
        fixture("o02_boxA.SLDPRT"),
        fields={"number": "SS-1", "drawn_by": "Ann Example"},
        options=T.DrawingOptions(view_sheets=view_sheets),
        settings=G.settings(),
    )


@functools.cache
def plate(view_sheets=()):
    """The sixteen-hole plate in inches, as the golden draws it: its isometric has no room."""
    xt, truth = drawing_parts.sixteen_holes_plate()
    stage = G.source_stage("sixteen_holes_plate", xt, truth)
    options = T.DrawingOptions(units="in", view_sheets=view_sheets)
    return pipeline.run(None, options=options, settings=G.settings(), stages={"source": stage}).drawing


def _title(sheet) -> dict:
    return dict(next(a for a in sheet.annotations if isinstance(a, D.TitleBlock)).fields)


def _views(sheet) -> list[str]:
    return [vp.view for vp in sheet.views]


def test_the_isometric_goes_on_a_sheet_of_its_own():
    plain, apart = o02(), o02((("isometric", 2),))
    first, second = D.sheets_of(apart.sheet)
    assert len(D.sheets_of(plain.sheet)) == 1 and _views(plain.sheet) == ["v-1", "v-2", "v-4"]
    assert _views(first) == ["v-1", "v-2"] and _views(second) == ["v-4"]
    # the first sheet keeps its views where they were, at the same scale, and says 1 OF 2
    assert first.views == plain.sheet.views[:2] and first.scale == plain.sheet.scale
    assert first.geometry == tuple(g for g in plain.sheet.geometry if g.src.view != "v-4")
    assert _title(first)["sheet"] == "1 OF 2" and _title(plain.sheet)["sheet"] == "1 OF 1"
    # the second: the first's size and scale, the isometric centred above the continuation block
    assert (second.name, second.width, second.height, second.scale) == (
        first.name,
        first.width,
        first.height,
        first.scale,
    )
    fields = _title(second)
    assert fields["sheet"] == "2 OF 2" and fields["number"] == "SS-1"
    assert set(fields) == {"size", "cage", "number", "revision", "scale", "sheet"}
    tb = next(a for a in second.annotations if isinstance(a, D.TitleBlock))
    f = SH.continuation_frame(second.name, G.settings())
    boxes = [g.bounds() for g in second.geometry]
    xs = [x for b in boxes for x in (b[0], b[2])]
    ys = [y for b in boxes for y in (b[1], b[3])]
    assert min(ys) > tb.at[1] + tb.height and max(ys) < f.border.y1  # above the block, in the border
    assert (min(xs) + max(xs)) / 2 == pytest.approx((f.area.x0 + f.area.x1) / 2, abs=0.5)
    assert {type(a) for a in second.annotations} == {D.TitleBlock, D.Border, D.Stamp, D.PlotStamp}
    # nothing else moved: the notes, revision block and title block are the first's
    assert not [a for a in second.annotations if isinstance(a, (D.NotesBlock, D.ToleranceBlock, D.Dimension))]
    assert not [p for p in second.painted if p.owner == "revisions"]
    # the checks are those of the drawing as it was, and no view is said to be left out
    assert [c for c in apart.checks if c.level != "information"] == [
        c for c in plain.checks if c.level != "information"
    ]
    assert not [c for c in apart.checks if "left out" in c.message]


def test_a_sheet_of_views_is_a_page_and_a_sheet_beside_the_first():
    import dxf_reader
    from solidseas.drawing import svg
    from solidseas.drawing.dxf import SHEET_GAP, dxf_bytes
    from solidseas.model import drawing_summary_data

    d = o02((("isometric", 2),))
    pdf = io.BytesIO()
    write_pdf(d, pdf)
    assert PdfDocument(pdf.getvalue()).page_count == 2
    second = [r.text for r in PdfDocument(pdf.getvalue(), page_index=1).text_runs()]
    assert {"SS-1", "2 OF 2", "DWG NO", "SHEET"} <= set(second) and "TITLE" not in second
    doc = dxf_reader.read(dxf_bytes(d))
    texts = [e for e in doc.entities if e.type == "TEXT"]
    stamps = [e.point(10)[0] for e in texts if e.text == "PRELIMINARY - NOT FOR MANUFACTURE"]
    k = d.sheet.scale[1] / d.sheet.scale[0]  # model millimetres a sheet millimetre
    assert len(stamps) == 2  # the same place on each sheet, the second a sheet and a gap along
    assert stamps[1] - stamps[0] == pytest.approx((d.sheet.width + SHEET_GAP) * k, abs=1e-3)
    assert len(svg.to_svgs(d.sheet)) == 2
    counts = drawing_summary_data(d)["counts"]
    assert counts["views"] == 3 and counts["sheets"] == 2


def test_the_sheet_of_a_view_is_kept_in_the_drawing_file():
    d = o02((("isometric", 2),))
    data = document.dumps(d)
    assert json.loads(data)["options"]["view_sheets"] == {"isometric": 2}
    back, problems = document.loads(data)
    assert problems == [] and back.options.view_sheets == (("isometric", 2),)
    assert document.dumps(back) == data
    assert "view_sheets" not in json.loads(document.dumps(o02()))["options"]  # written only when set
    for bad in ({"top": 2}, {"isometric": 1}, {"isometric": "2"}, [["isometric", 2]]):
        raw = json.loads(data)
        raw["options"]["view_sheets"] = bad
        read, problems = document.loads(json.dumps(raw).encode("utf-8"))
        assert read.options.view_sheets == () and any("view_sheets" in p for p in problems), bad


def test_the_option_names_a_view_that_may_stand_apart_once():
    for bad in (
        (("top", 2),),
        (("isometric", 1),),
        (("isometric", 65),),
        (("isometric", True),),
        (("isometric", 2), ("isometric", 3)),
        ("isometric", 2),
    ):
        with pytest.raises(InvalidArgumentError):
            T.DrawingOptions(view_sheets=bad)
    assert T.DrawingOptions(view_sheets=(("isometric", 64),)).view_sheets == (("isometric", 64),)


def test_set_view_sheet_moves_the_isometric_and_back():
    d = o02()
    moved, checks = edit.set_view_sheet(d, "isometric", 3)
    assert moved.options.view_sheets == (("isometric", 3),)
    sheets = D.sheets_of(moved.sheet)
    assert len(sheets) == 2 and [vp.view for vp in sheets[1].views] == ["v-4"]  # numbered from 2
    assert _title(sheets[1])["sheet"] == "2 OF 2" and tuple(checks) == moved.checks
    assert edit._plan_key(moved) == edit._plan_key(d), "where a view goes is the layout's, not the plan's"
    back, _checks = edit.set_view_sheet(moved, "isometric", 1)
    assert back.options.view_sheets == () and back.sheet == d.sheet
    with pytest.raises(InvalidArgumentError, match="only the isometric view"):
        edit.set_view_sheet(d, "top", 2)
    for sheet in (0, 65, True, "2"):
        with pytest.raises(InvalidArgumentError, match="sheet must be"):
            edit.set_view_sheet(d, "isometric", sheet)
    without, _checks = edit.remove_view(d, "isometric")
    with pytest.raises(InvalidArgumentError, match="no isometric view"):
        edit.set_view_sheet(without, "isometric", 2)


def test_the_isometric_with_no_room_is_reported_with_the_way_to_give_it_some():
    crowded = plate()
    assert "v-4" not in {vp.view for s in D.sheets_of(crowded.sheet) for vp in s.views}
    said = [c for c in crowded.checks if c.code == "R12.views" and "left out" in c.message]
    assert [(c.level, c.item, c.message, c.fixes) for c in said] == [
        (
            "information",
            "v-4",
            "the isometric has no room on the sheet, so it is left out",
            ("Move to Its Own Sheet", "Remove the View"),
        )
    ]
    # on a sheet of its own it has room, and nothing is said
    roomy = plate((("isometric", 2),))
    sheets = D.sheets_of(roomy.sheet)
    assert len(sheets) == 2 and [vp.view for vp in sheets[1].views] == ["v-4"]
    assert sheets[0].views == crowded.sheet.views
    assert not [c for c in roomy.checks if "left out" in c.message]
    # the fix, as the editor makes it, does the same
    fixed, _checks = edit.set_view_sheet(crowded, "isometric", 2)
    assert D.sheets_of(fixed.sheet)[1].views == sheets[1].views


def test_an_assemblys_isometric_takes_its_balloons_to_its_sheet():
    from solidseas.drawing.checks import run_checks
    from solidseas.model import drawing_summary_data
    from test_drawing_assembly import FIELDS, _lists, _settings, _synthetic_assembly

    parts = [
        (
            str(k + 1),
            f"plate{k + 1:03d}",
            drawing_parts.box(20 * drawing_parts.MM, 10 * drawing_parts.MM, 5 * drawing_parts.MM),
            ((k % 8) * 25 * drawing_parts.MM, (k // 8) * 15 * drawing_parts.MM, 0),
        )
        for k in range(70)
    ]
    run = pipeline.run(
        None,
        settings=_settings(),
        fields=FIELDS,
        options=T.DrawingOptions(sheet="A", view_sheets=(("isometric", 2),)),
        stages={"source": _synthetic_assembly(parts)},
        limits=DrawingLimits(bodies=256),
    )
    d = run.drawing
    sheets = D.sheets_of(d.sheet)
    # the views and the list's start; the isometric with its balloons; then the rest of the list
    assert [_title(s)["sheet"] for s in sheets] == ["1 OF 4", "2 OF 4", "3 OF 4", "4 OF 4"]
    assert [[vp.view for vp in s.views] for s in sheets] == [["v-1", "v-2", "v-3"], ["v-4"], [], []]
    balloons = [[a.item for a in s.annotations if isinstance(a, D.Balloon)] for s in sheets]
    assert balloons[0] == [] and sorted(balloons[1], key=int) == [str(n) for n in range(1, 71)]
    assert balloons[2] == balloons[3] == []
    assert [bool(_lists(s)) for s in sheets] == [True, False, True, True]
    rows = [r[0] for s in sheets for pl in _lists(s) for r in pl.rows]
    assert rows == [str(n) for n in range(1, 71)]
    # the checks read the balloons on every sheet: none is said to be missing
    assert not [c for c in run_checks(d) if c.code in ("ASM.balloons", "ASM.parts", "R8.sheet")]
    counts = drawing_summary_data(d)["counts"]
    assert (counts["views"], counts["balloons"], counts["items"], counts["sheets"]) == (4, 70, 70, 4)


def test_a_drawing_held_to_one_sheet_keeps_its_isometric_on_it():
    held = drawing.make_drawing(
        fixture("o02_boxA.SLDPRT"),
        fields={"number": "SS-1", "drawn_by": "Ann Example"},
        options=APART,
        settings=G.settings(),
        limits=DrawingLimits(sheets=1),
    )
    assert D.sheets_of(held.sheet) == (held.sheet,) and "v-4" in {vp.view for vp in held.sheet.views}


def test_sheet_views_groups_and_numbers_the_sheets_asked_for():
    iso = T.ViewSpec("v-4", "isometric", (1.0, 1.0, 1.0), (0.0, 1.0, 0.0), "isometric")
    front = T.ViewSpec("v-1", "base", (0.0, 0.0, 1.0), (0.0, 1.0, 0.0), "front")
    plan = T.Plan(views=(front, iso))
    assert place.sheet_views(plan, T.DrawingOptions()) == ()
    assert place.sheet_views(plan, T.DrawingOptions(view_sheets=(("isometric", 5),))) == (("v-4",),)
    assert place.sheet_views(plan, T.DrawingOptions(view_sheets=(("isometric", 5),)), sheets=1) == ()
    no_iso = T.Plan(views=(front,))
    assert place.sheet_views(no_iso, T.DrawingOptions(view_sheets=(("isometric", 2),))) == ()


def test_the_isometric_apart_is_centred_and_made_smaller_only_to_fit():
    from solidseas.drawing.layout.index import Box

    f = SH.continuation_frame("A", G.settings())
    spec = T.ViewSpec("v-4", "isometric", (1.0, 1.0, 1.0), (0.0, 1.0, 0.0), "isometric")

    def slot(size_m: float) -> A.Slot:
        geom = T.ViewGeometry("v-4", ())
        return A.Slot(spec, geom, Box(0.0, 0.0, size_m, size_m * 0.5), 1000.0)

    small = A.arrange_apart(f, {"v-4": slot(0.08)})
    s = small.slots["v-4"]
    assert small.iso == "v-4" and small.iso_factor == 1.0 and s.k == 1000.0
    room = Box(f.area.x0, f.title.y1 + SH.GAP, f.area.x1, f.area.y1)
    b = s.box
    assert (b.x0 + b.x1) / 2 == pytest.approx((room.x0 + room.x1) / 2)
    assert (b.y0 + b.y1) / 2 == pytest.approx((room.y0 + room.y1) / 2)
    large = A.arrange_apart(f, {"v-4": slot(0.4)})  # 400 mm at full size: smaller to fit an A sheet
    assert large.iso == "v-4" and large.iso_factor in A.ISO_FACTORS and large.iso_factor < 1.0
    assert large.slots["v-4"].box.inside(f.area)
    none = A.arrange_apart(f, {"v-4": slot(2.0)})  # too large at any factor
    assert none.iso is None and none.iso_factor == 0.0 and none.slots["v-4"].k == 1000.0
