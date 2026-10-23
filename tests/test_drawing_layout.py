"""Layout (docs/DRAWINGS.md 11, 19.2): sheet and scale, the arrangement, dimensions,
datum symbols, callouts and frames, the title block, notes and stamps, the checks,
determinism and speed, on hand-made plans of the synthetic plates."""

import math
import time
from collections import Counter
from dataclasses import replace

import pytest

import drawing_parts as P
from drawing_plan_fixtures import PATTERNS, plate
from drawing_support import tiny_png
from solidseas.drawing import display as D
from solidseas.drawing import facegraph, fonts, images, standards
from solidseas.drawing import settings as S
from solidseas.drawing.layout import arrange, layout, place, titleblock
from solidseas.drawing.layout import dimension as DM
from solidseas.drawing.layout.glyphs import Pen, text_width
from solidseas.drawing.layout.index import DIMLINE, HARD, Box, Index, segments_cross
from solidseas.drawing.layout.patterns import fit
from solidseas.drawing.layout.stamps import PRELIMINARY
from solidseas.drawing.painter import RecordingPainter, paint
from solidseas.drawing.plan import make_plan
from solidseas.drawing.svg import to_svg
from solidseas.drawing.types import DrawingOptions, Run, ViewGeometry

SCATTERED = [("scattered", [0, 1, 2, 3])]


class _Source:
    name = "FOUR-HOLES.SLDPRT"
    configuration = "Default"
    material = None
    sha256 = "cd" * 32
    hints = ()

    def property(self, *names):
        return None


def laid(name="four_holes", patterns=SCATTERED, options=None, **kw):
    ctx = plate(name, patterns=patterns, options=options)
    planned = make_plan(ctx, kw.get("source"))
    return planned, layout(planned, options=ctx.options, settings=ctx.settings, **kw)


def of(sheet, cls):
    return [a for a in sheet.annotations if isinstance(a, cls)]


# ---------------------------------------------------------------------- sheet and scale


def test_a_reduced_scale_only_while_spans_stay_eight_millimetres():
    _p, r = laid()
    # on A the plate fits clear of the title block only at 1:4 (at 1:2 the texts of its
    # short spans, outside their ends, reach into it), where its 10 mm locations would
    # be 2.5 mm on paper (C24): B at full size is chosen, and a forced A is cramped
    assert (r.sheet.name, r.sheet.scale) == ("B", (1, 1))
    _p, forced = laid(options=DrawingOptions(sheet="A"))
    assert forced.sheet.name == "A" and forced.sheet.scale == (1, 4)
    assert any(c.code == "L.cramped" for c in forced.checks)
    assert not [c for c in forced.checks if c.code in ("L.reserved", "L.outside", "L.overlap")]
    _p, fixed = laid(options=DrawingOptions(scale=(1, 1)))
    assert fixed.sheet.scale == (1, 1)


def test_the_views_are_aligned_third_angle():
    _p, r = laid()
    place = {p.view: p for p in r.sheet.views}
    front, top = place["v-1"], place["v-2"]
    assert front.origin[0] == pytest.approx(top.origin[0])  # the top sits above the front, x aligned
    assert top.origin[1] > front.origin[1]
    assert "v-4" in place and place["v-4"].scale <= front.scale  # the isometric, full scale or smaller


# ---------------------------------------------------------------------- what is drawn


def test_every_shown_dimension_is_drawn_once():
    planned, r = laid(source=_Source())
    dims = Counter(a.id for a in of(r.sheet, D.Dimension))
    shown = [d.id for d in planned.plan.dimensions if d.kind != "datum_feature"]
    assert sorted(dims) == sorted(shown) and set(dims.values()) == {1}
    datums = sorted(a.letter for a in of(r.sheet, D.DatumFeature))
    assert datums == ["A", "B", "C"]
    frames = of(r.sheet, D.FeatureControlFrame)
    assert {f.owner for f in frames} >= {f"{d.id}-frame" for d in planned.plan.dimensions if d.frame}
    assert not r.checks, [c.message for c in r.checks]


def test_linear_dimensions_carry_their_definition_points():
    planned, r = laid()
    by_id = {a.id: a for a in of(r.sheet, D.Dimension)}
    size = next(d for d in planned.plan.dimensions if d.key == "size/f-6")  # the 100 mm envelope
    ann = by_id[size.id]
    (p0, p1, on_line) = ann.points
    assert abs(p1[0] - p0[0]) == pytest.approx(100.0)  # at 1:1, the extension lines 100 mm apart
    assert ann.angle_deg == 0.0 and on_line[1] > max(p0[1], p1[1])  # the envelope above the view
    loc = next(d for d in planned.plan.dimensions if d.key == "loc/f-1/x")
    assert by_id[loc.id].flags == ("basic",) and by_id[loc.id].text.boxed


def test_text_is_winansi_and_owned():
    _p, r = laid(source=_Source())
    for item in r.sheet.painted:
        if isinstance(item, D.TextRun):
            fonts.encode(item.text)  # raises on a character the font lacks
            assert item.owner, item.text
        if isinstance(item, (D.Stroke, D.Fill)) and item.layer == "dimensions":
            assert item.owner


def test_callout_symbols_are_paths():
    planned, r = laid("hole_kinds", patterns=None)
    runs = [i for i in r.sheet.painted if isinstance(i, D.TextRun)]
    assert not any(ch in i.text for i in runs for ch in "⌴⌵↧")
    cbore = next(d for d in planned.plan.dimensions if "⌴ Ø11.00 ↧ 6.5" in d.suffix)
    strokes = [i for i in r.sheet.painted if isinstance(i, D.Stroke) and i.owner == cbore.id]
    assert len(strokes) >= 6  # the leader, its shoulder and the symbols' paths


def test_ordinates_in_a_crowded_band():
    _planned, r = laid("hole_kinds", patterns=None)
    ords = [a for a in of(r.sheet, D.Dimension) if a.kind == "ordinate"]
    assert len(ords) == 8 and all(len(a.points) == 3 for a in ords)
    zero = [i for i in r.sheet.painted if isinstance(i, D.TextRun) and i.text == "0"]
    assert zero  # the ordinate origin


def test_a_side_with_ordinates_keeps_its_linear_texts_past_theirs():
    # a vertical dimension's text is centred on its line: next to a row of ordinates its
    # track stands half that text beyond where the ordinates' texts end
    planned, _r = laid("hole_kinds", patterns=None)  # a plan with ordinates
    ctx = planned.detail.ctx
    ordinate = next(d for d in planned.plan.dimensions if d.kind == "ordinate")
    linear = replace(next(d for d in planned.plan.dimensions if d.kind == "linear"), role="feature_location")
    spec, geom = ctx.orthographic()[0]
    slot = arrange.Slot(spec, geom, Box(0.0, 0.0, 0.2, 0.12), 1000.0)
    sides = arrange.bands(ctx, slot, [(ordinate, 0.0, 0.03, "y", 0.0), (linear, 0.0, 0.05, "y", 0.0)])
    band = sides["left"]
    (lin,) = [d for d in band.dims if d.pd.kind == "linear"]
    ordinates_end = (
        standards.DIMENSIONS.first_row + 1.5 + max(d.text_w for d in band.dims if d.pd.kind == "ordinate")
    )
    assert band.offsets[lin.track] - lin.text_w / 2 >= ordinates_end + 1.0 - 1e-9


def test_a_row_of_close_ordinates_reaches_as_far_as_its_last_jogged_value():
    # values too close to stand at their own places are jogged apart along the row: the
    # arrangement leaves room for the row's whole reach, not only its features' span
    planned, _r = laid("hole_kinds", patterns=None)
    ctx = planned.detail.ctx
    ordinate = next(d for d in planned.plan.dimensions if d.kind == "ordinate")
    spec, geom = ctx.orthographic()[0]
    slot = arrange.Slot(spec, geom, Box(0.0, 0.0, 0.2, 0.12), 1000.0)
    # ten values a millimetre apart from a 0
    close = [(replace(ordinate, id=f"d-{k}"), 0.0, k * 0.001, "y", 0.0) for k in range(1, 11)]
    band = arrange.bands(ctx, slot, close)["left"]
    h = arrange.text_height(ctx.unit)
    pitch = h * (1.9 if ordinate.tolerance == "basic" else 1.0) + 1.4
    assert max(d.hi for d in band.dims) >= 10 * pitch - 1e-9


def test_a_horizontal_side_with_ordinates_keeps_its_sizes_texts_past_theirs():
    # a horizontal dimension's text is centred on its line as well: below a row of
    # ordinates, whose texts run out along their extension lines, its track stands its
    # half text and a clearance beyond where those texts end
    planned, _r = laid("hole_kinds", patterns=None)
    ctx = planned.detail.ctx
    ordinate = next(d for d in planned.plan.dimensions if d.kind == "ordinate")
    linear = replace(next(d for d in planned.plan.dimensions if d.kind == "linear"), role="feature_location")
    spec, geom = ctx.orthographic()[0]
    slot = arrange.Slot(spec, geom, Box(0.0, 0.0, 0.2, 0.12), 1000.0)
    band = arrange.bands(ctx, slot, [(ordinate, 0.0, 0.03, "x", 0.0), (linear, 0.0, 0.05, "x", 0.0)])["below"]
    (lin,) = [d for d in band.dims if d.pd.kind == "linear"]
    ordinates_end = (
        standards.DIMENSIONS.first_row + 1.5 + max(d.text_w for d in band.dims if d.pd.kind == "ordinate")
    )
    h = arrange.text_height(ctx.unit)
    assert band.offsets[lin.track] - h / 2 >= ordinates_end + 1.0 - 1e-9


def test_a_first_row_of_sizes_stands_past_a_datum_symbol():
    # a datum feature symbol stands between its view and the dimensions on its side: a
    # first row of linear dimensions stands beyond its reach, its texts too, an ordinate
    # row as it was (its texts start past the symbol)
    planned, _r = laid("hole_kinds", patterns=None)
    ctx = planned.detail.ctx
    ordinate = next(d for d in planned.plan.dimensions if d.kind == "ordinate")
    linear = replace(next(d for d in planned.plan.dimensions if d.kind == "linear"), role="feature_location")
    spec, geom = ctx.orthographic()[0]
    slot = arrange.Slot(spec, geom, Box(0.0, 0.0, 0.2, 0.12), 1000.0)
    reach = 11.5
    below = arrange.bands(ctx, slot, [(linear, 0.0, 0.05, "x", 0.0)], {"below": reach})["below"]
    # a horizontal row's texts are centred on its line, a boxed basic value reaching 0.95
    # of a text height past it toward the view: they stand clear of the symbol as well
    h = arrange.text_height(ctx.unit)
    assert below.offsets[0] - 0.95 * h >= reach + arrange.DATUM_CLEAR - 1e-9
    left = arrange.bands(ctx, slot, [(linear, 0.0, 0.05, "y", 0.0)], {"left": reach})["left"]
    assert left.offsets[0] - left.dims[0].text_w / 2 >= reach + arrange.DATUM_CLEAR - 1e-9
    both = [(ordinate, 0.0, 0.03, "y", 0.0), (linear, 0.0, 0.05, "y", 0.0)]
    assert (
        arrange.bands(ctx, slot, both, {"left": reach})["left"].offsets
        == arrange.bands(ctx, slot, both)["left"].offsets
    )


def test_a_datum_symbol_stands_away_from_its_faces_material():
    # a datum feature symbol stands out the way its face's outward normal shows, read
    # against its own face, even where the face lies nearer the view's other side (a
    # face within the outline); there it needs no room past the view
    planned, _r = laid()
    ctx = planned.detail.ctx
    run = place._Run(
        planned,
        ctx.options,
        ctx.settings,
        logo=None,
        logo_sha="",
        source=None,
        fields={},
        revisions=(),
        status="PRELIMINARY",
        signed={},
    )
    pd = next(d for d in planned.plan.dimensions if d.kind == "datum_feature" and d.suffix[0] == "A")
    spec, geom = ctx.view(pd.view)
    face = next(d.face for d in ctx.features.frame.datums if d.letter == "A")
    normal = ctx.model.faces[face].surface.normal  # the bottom, -Z
    name, sign = ctx.sheet_axis(spec, pd.axis)
    out = sign * (1 if sum(a * b for a, b in zip(normal, ctx.direction(pd.axis), strict=True)) > 0 else -1)
    vb = arrange.view_box(geom)
    lo, hi = (vb.y0, vb.y1) if name == "y" else (vb.x0, vb.x1)
    # the view reaching far past the face on its outward side, so the other side is nearer
    far = (lo - 10 * (hi - lo), hi) if out < 0 else (lo, hi + 10 * (hi - lo))
    wide = Box(vb.x0, far[0], vb.x1, far[1]) if name == "y" else Box(far[0], vb.y0, far[1], vb.y1)
    sa, _along, side, beyond = run._datum_side(pd, arrange.Slot(spec, geom, wide, 1000.0))
    assert sa == name
    assert side == {("y", -1): "below", ("y", 1): "above", ("x", -1): "left", ("x", 1): "right"}[(name, out)]
    assert beyond == 0.0


def test_a_views_outline_leaves_out_its_centre_lines():
    # a pattern's pitch circle may reach past the part: the view's outline, which texts
    # and symbols keep off, is the box of its other runs (the circle is a line of its own)
    geom = ViewGeometry(
        "v",
        (
            Run(D.Segment((0.0, 0.0), (0.05, 0.03)), "visible"),
            Run(D.Arc((0.025, 0.015), 0.04), "centre"),
        ),
    )
    assert arrange.outline_box(geom) == Box(0.0, 0.0, 0.05, 0.03)
    assert arrange.view_box(geom).x1 == pytest.approx(0.065)


@pytest.mark.parametrize("horizontal", [True, False])
def test_a_text_too_wide_for_its_span_stands_past_its_near_end_when_the_far_one_is_taken(horizontal):
    # two such texts meet at a view's corner (a tiny part's width and height): the
    # second stands past its other end
    def drawn(clear):
        return DM.linear(
            Pen(),
            Index(),
            did="d",
            kind="linear",
            horizontal=horizontal,
            a=0.0,
            b=2.0,
            start_a=-6.0,
            start_b=-6.0,
            gap_a=1.5,
            gap_b=1.5,
            at=10.0,
            outward=1.0,
            h=3.0,
            text=D.DimText("0.7"),
            value=0.0007,
            refs=(),
            tolerance="block",
            places=1,
            view="v",
            clear=clear,
        ).text_at[0 if horizontal else 1]

    def far_taken(box):
        return (box.x0 if horizontal else box.y0) < 0.0

    assert drawn(None) > 2.0  # past the far end
    assert drawn(far_taken) < 0.0  # the far end taken, the near one free
    assert drawn(lambda box: False) > 2.0  # both taken: the far end, as before


def test_holes_in_line_share_a_centre_line():
    _planned, r = laid("hole_kinds", patterns=None)
    lines = of(r.sheet, D.CentreLine)
    flat = [cl for cl in lines if abs(cl.p0[1] - cl.p1[1]) < 1e-6]
    assert len(flat) >= 2  # the rows at Y 20 and Y 55


def test_leaders_stand_between_15_and_75_degrees():
    planned, r = laid("patterns", PATTERNS)
    assert not [c for c in r.checks if c.code == "L.leader"]
    for a in of(r.sheet, D.Dimension):
        if a.kind in ("hole_callout", "diameter"):
            assert len(a.points) == 2


def test_where_nothing_is_clear_a_leader_crosses_a_line_rather_than_cover_text():
    index = Index()
    index.add(HARD, Box(0.0, 0.0, 10.0, 5.0), "text")
    index.add(DIMLINE, Box(20.0, 0.0, 40.0, 0.5), "line")
    index.add_segment(DIMLINE, (50.0, -10.0), (50.0, 10.0), "leader")
    far = ((100.0, 100.0), (101.0, 101.0))
    clear = place.severity(index, Box(80.0, 80.0, 90.0, 85.0), *far)
    over_text = place.severity(index, Box(2.0, 1.0, 8.0, 4.0), *far)
    over_line = place.severity(index, Box(25.0, -1.0, 35.0, 2.0), *far)
    through_text = place.severity(index, Box(80.0, 80.0, 90.0, 85.0), (-5.0, 2.0), (15.0, 3.0))
    across_leader = place.severity(index, Box(80.0, 80.0, 90.0, 85.0), (45.0, 0.0), (55.0, 1.0))
    assert clear == 0.0
    assert over_text > over_line == through_text > across_leader > clear


def _crowded_plate(seed: int, n: int):
    """A seeded plate of ``n`` holes drawn through the pipeline as the corpus sweep draws a
    part (auto sheet and scale): some 60 dimensions round one crowded front view."""
    import drawing_golden_support as G
    from solidseas.drawing import pipeline

    xt, truth = P.random_plate(seed, n)
    stage = G.source_stage("random_plate", xt, truth)
    run = pipeline.run(None, options=DrawingOptions(), settings=G.settings(), stages={"source": stage})
    return run.orchestrated.result


def _no_clear_place(result) -> list[str]:
    return sorted(c.owner for c in result.checks if c.code == "L.placement" and c.owner.startswith("d-"))


def test_a_callout_with_no_clear_place_at_first_looks_again_and_finds_one(monkeypatch):
    """Two callouts of this plate find no clear place among the usual leader angles and
    lengths, in their usual order; the closer look between those angles and lengths, and
    the pass that places them first, find each one a place that is clear."""
    got = _crowded_plate(4, 25)
    assert _no_clear_place(got) == []
    assert not [c for c in got.checks if c.code in ("L.overlap", "L.leader")]
    monkeypatch.setattr(place, "LEADER_EXTRA", 0)  # no closer look and no further passes
    assert _no_clear_place(_crowded_plate(4, 25))
    monkeypatch.undo()
    assert to_svg(_crowded_plate(4, 25).sheet) == to_svg(got.sheet)  # the same sheet every time


def test_the_closer_look_at_leader_items_is_bounded():
    """However crowded the sheet, the closer look and the further passes stop at a fixed
    count of places looked at, never at a time, so the sheet is the same on any machine."""
    assert place.LEADER_RETRIES <= 3 and place.LEADER_EXTRA <= 50000
    from solidseas.drawing.layout.checks import LEADER_MAX, LEADER_MIN

    assert set(place.ANGLES).isdisjoint(place.FINE_ANGLES)
    for a in place.FINE_ANGLES:
        slope = math.degrees(math.atan2(abs(math.sin(math.radians(a))), abs(math.cos(math.radians(a)))))
        assert LEADER_MIN <= round(slope, 6) <= LEADER_MAX
    assert max(place.ALL_LENGTHS) == max(place.LENGTHS)


def _block_run(seed: int, **options):
    """A seeded machined block drawn through the pipeline as the corpus sweep draws a
    part."""
    import drawing_golden_support as G
    from solidseas.drawing import pipeline

    xt, truth = P.random_block(seed)
    stage = G.source_stage("random_block", xt, truth)
    return pipeline.run(
        None, options=DrawingOptions(**options), settings=G.settings(), stages={"source": stage}
    )


def _conflicts(result) -> list[tuple[str, str, str]]:
    return [(c.code, c.owner, c.other) for c in result.checks if c.code in ("L.overlap", "L.placement")]


def test_a_datum_symbol_under_a_band_stands_clear_of_its_texts():
    """This block's datum B stands up from the top of its front view, under the band of
    sizes there. The arrangement keeps the symbol its room, and the band's first row now
    stands far enough past it that its texts, centred on their lines, do too: the symbol
    finds a clear spot where it stood on a basic value's box and was reported."""
    run = _block_run(31)
    result = run.orchestrated.result
    assert _conflicts(result) == []
    (b,) = [a for a in of(result.sheet, D.DatumFeature) if a.letter == "B"]
    assert b.view == "v-1"  # in its own view, the front


@pytest.mark.parametrize("seed", [2, 64])
def test_a_band_frame_is_placed_clear_of_the_tracks_painted_after_it(seed):
    """These blocks' slot widths stand in a band with a position frame beside the value,
    reaching past its own track. Placed before the next track was painted, the frame
    looked clear and that track's text was then painted over it. Frames now go once
    every band stands, and find a clear spot."""
    result = _block_run(seed).orchestrated.result
    frames = [a for a in of(result.sheet, D.FeatureControlFrame) if a.owner.endswith("-frame")]
    assert frames
    assert _conflicts(result) == []


def _datum_run(seed: int, n: int, sheet: str):
    import drawing_golden_support as G
    from solidseas.drawing import pipeline

    xt, truth = P.random_plate(seed, n)
    stage = G.source_stage("random_plate", xt, truth)
    return pipeline.run(
        None, options=DrawingOptions(sheet=sheet), settings=G.settings(), stages={"source": stage}
    )


def test_a_datum_with_no_clear_place_in_its_view_is_drawn_in_another_and_recorded_there():
    """On a B sheet this plate's datum C is boxed in on the front by a tall ordinate
    column. The plan offers the other views where its face is a line, the front first;
    the layout takes the first with a clear place, and the plan, the drawing's records,
    its file, its checks and the sheet all name that view."""
    from solidseas.drawing import document, edit

    run = _datum_run(24, 20, "B")
    done = run.orchestrated
    assert not [c for c in done.result.checks if c.code == "L.placement" and c.owner.startswith("datum")]
    planned = {d.suffix[0]: d for d in done.raw.plan.dimensions if d.kind == "datum_feature"}
    drawn = {d.suffix[0]: d for d in done.planned.plan.dimensions if d.kind == "datum_feature"}
    c = drawn["C"]
    others = done.raw.detail.other_views[planned["C"].id]
    assert planned["C"].view == "v-1" and c.view == others[0][0] != "v-1"
    assert done.result.views == {c.id: others[0]}
    assert done.planned.detail.sheet_axis[c.id] == others[0][1]
    assert {a.letter: a.view for a in of(done.result.sheet, D.DatumFeature)} == {
        k: d.view for k, d in drawn.items()
    }
    records = {d.suffix[0]: d.view for d in run.drawing.dimensions if d.kind == "datum_feature"}
    assert records == {k: d.view for k, d in drawn.items()}
    again, _problems = document.loads(document.dumps(run.drawing))
    assert {d.suffix[0]: d.view for d in again.dimensions if d.kind == "datum_feature"} == records
    rec = next(d for d in run.drawing.dimensions if d.kind == "datum_feature" and d.suffix == ("C",))
    assert not [x for x in run.drawing.checks if x.item in (rec.id, "datum-C")]
    # laid out again after an edit, the plan offers the same views in the same order
    relaid, checks = edit.relayout(run.drawing)
    assert {d.suffix[0]: d.view for d in relaid.dimensions if d.kind == "datum_feature"} == records
    assert to_svg(relaid.sheet) == to_svg(run.drawing.sheet)
    assert not [x for x in checks if x.item in (rec.id, "datum-C")]
    # with no other view offered, it stays in the front with no clear place
    alone = replace(done.raw, detail=replace(done.raw.detail, other_views={}))
    got = layout(alone, options=done.options, settings=run.drawing.settings)
    assert got.views == {}
    assert "datum-C" in [x.owner for x in got.checks if x.code == "L.placement"]


def test_a_datums_views_are_offered_in_the_planners_order():
    """The planner names a datum's view, the front first and then the least crowded,
    and offers each other view where its face is a line after it, in the same order."""
    planned, _r = laid()
    ctx = planned.detail.ctx
    assert any(planned.detail.other_views.values())
    for pd in planned.plan.dimensions:
        if pd.kind != "datum_feature":
            continue
        others = planned.detail.other_views.get(pd.id, ())
        views = [pd.view, *(v for v, _sa in others)]
        assert len(set(views)) == len(views)
        assert ctx.view(pd.view)[0].kind == "base" or all(ctx.view(v)[0].kind != "base" for v in views)
        for v, sa in others:
            spec, _geom = ctx.view(v)
            assert ctx.sheet_axis(spec, pd.axis)[0] == sa


@pytest.mark.parametrize("lines", [0, 1, 2])
def test_a_callouts_frame_stays_within_the_room_its_leader_reserves(lines):
    # a leader item reserves its text lines and a feature control frame under them: the
    # frame drawn there stays inside, so what else stands below stays clear of it
    h = 3.0
    pen, index = Pen(), Index()
    item = D.FrameItem("position", "0.25", True, "mmc", ("A", "B", "C"))
    frames = []

    def draw_frame(x, y, anchor):
        box, _ann = DM.frame(pen, index, x=x, y=y - h * 1.2, h=h, item=item, anchor=anchor, owner="d-frame")
        frames.append(box)
        return box

    elbow = (50.0, 50.0)
    first = D.DimText("1.70", "2X Ø", "THRU")
    DM.leader_block(
        pen,
        index,
        did="d",
        start=(40.0, 40.0),
        elbow=elbow,
        right=True,
        h=h,
        lines=["Ø3.20 X 90°"] * lines,
        first=first,
        frame_draw=draw_frame,
    )
    top = elbow[1] + h * 0.8  # as place._Run._leader measures the block
    height = (1 + lines) * h * DM.LINE_PITCH + h * place.FRAME_ROOM
    assert frames and frames[0].y0 >= top - height - 1e-9


def test_the_title_block_and_stamps():
    _p, r = laid(source=_Source())
    (tb,) = of(r.sheet, D.TitleBlock)
    fields = dict(tb.fields)
    assert fields["number"] == "FOUR-HOLES" and fields["size"] == "B" and fields["scale"] == "1:1"
    assert fields["status"] == "PRELIMINARY" and fields["model"].endswith("CD" * 8)
    (stamp,) = of(r.sheet, D.Stamp)
    assert stamp.text == PRELIMINARY
    (plot,) = of(r.sheet, D.PlotStamp)
    assert (
        plot.text.endswith("FOUR-HOLES.SLDPRT (Default)") and "/" not in plot.text and "\\" not in plot.text
    )
    (border,) = of(r.sheet, D.Border)
    assert (border.columns, border.rows) == (4, 2)
    ctx_planned, released = laid(source=_Source(), status="RELEASED")
    assert not of(released.sheet, D.Stamp)


def _marks_under(sheet, run):
    """The border's zone marks (single strokes) that stand under ``run`` and how far
    up each reaches."""
    cap = run.size * fonts.CAP_HEIGHT
    half = text_width(run.text, cap, True) / 2
    tops = []
    for s in sheet.painted:
        if not (isinstance(s, D.Stroke) and s.layer == "border" and len(s.path) == 2):
            continue
        (_m, xa, ya), (_l, xb, yb) = s.path
        if xa == xb and abs(xa - run.x) <= half:
            tops.append(max(ya, yb))
    return tops


def test_the_zone_marks_stop_short_of_the_preliminary_stamp():
    for size in ("A", "B"):  # an even number of zones puts a mark under the stamp's middle
        _p, r = laid(options=DrawingOptions(sheet=size), source=_Source())
        (run,) = [i for i in r.sheet.painted if isinstance(i, D.TextRun) and i.text == PRELIMINARY]
        tops = _marks_under(r.sheet, run)
        assert tops and all(top <= run.y - 1.0 + 1e-9 for top in tops), size
    _p, released = laid(options=DrawingOptions(sheet="A"), source=_Source(), status="RELEASED")
    (border,) = of(released.sheet, D.Border)
    strokes = [s for s in released.sheet.painted if isinstance(s, D.Stroke) and s.layer == "border"]
    marks = [s.path for s in strokes if len(s.path) == 2 and s.path[0][1] == s.path[1][1]]
    lengths = {round(abs(a[2] - b[2]), 6) for a, b in marks}
    assert lengths == {round(border.margin * 0.5, 6)}  # without the stamp every mark is whole


def test_notes_with_their_frame():
    _p, r = laid()
    notes = of(r.sheet, D.Note)
    assert [n.number for n in notes] == [1, 2, 3, 4]
    first = notes[0].lines[0]
    assert (
        first[0] == "UNLESS OTHERWISE SPECIFIED, ALL SURFACES"
        and first[1][0].characteristic == "profile_surface"
    )


def test_the_next_note_stands_clear_below_a_notes_frame():
    for size in ("A", "B"):
        _p, r = laid(options=DrawingOptions(sheet=size), source=_Source())
        runs = [i for i in r.sheet.painted if isinstance(i, D.TextRun) and i.layer == "notes"]
        frames = [a for a in of(r.sheet, D.FeatureControlFrame) if a.owner.startswith("n-")]
        assert frames, size
        for f in frames:
            k = int(f.owner.split("-")[1])
            after = [i for i in runs if i.owner == f"n-{k + 1}"]
            if not after:
                continue
            top = max(i.y + i.size * fonts.CAP_HEIGHT for i in after)
            assert f.at[1] - top >= 1.0 - 1e-6, (size, f.owner, f.at[1] - top)  # a millimetre clear


# ---------------------------------------------------------------------- the painted layer


def test_the_sheet_paints_and_round_trips():
    _p, r = laid("patterns", PATTERNS)
    rec = RecordingPainter()
    paint(r.sheet, rec)
    assert rec.calls[0][0] == "begin_page" and rec.calls[-1][0] == "end_page"
    assert "<svg" in to_svg(r.sheet)
    assert D.from_compact(D.to_compact(r.sheet)) == D.from_compact(
        D.to_compact(D.from_compact(D.to_compact(r.sheet)))
    )


def test_layout_twice_gives_the_same_sheet():
    _p, a = laid("patterns", PATTERNS)
    _p, b = laid("patterns", PATTERNS)
    assert a.sheet == b.sheet


def test_dashes_start_and_end_with_a_dash():
    dash = (3.0, 1.5)
    for length in (10.0, 23.7, 100.0):
        d = fit(dash, length)
        n = round((length - d[0]) / sum(d))
        assert n * sum(d) + d[0] == pytest.approx(length, rel=0.02) or d == ()
    assert fit(dash, 2.0) == ()  # too short to carry the pattern: one dash
    ring = fit(dash, 31.4, True)
    assert (31.4 / sum(ring)) == pytest.approx(round(31.4 / sum(ring)), rel=1e-3)


def test_the_index():
    idx = Index()
    idx.add("hard", Box(0, 0, 10, 10))
    assert idx.hits(Box(5, 5, 15, 15)) and not idx.hits(Box(11, 11, 15, 15))
    idx.add_segment("dimline", (0, 20), (20, 40))
    assert idx.crosses((0, 40), (20, 20), ("dimline",))
    assert not idx.crosses((30, 0), (40, 10), ("dimline",))
    assert segments_cross((0, 0), (2, 2), (0, 2), (2, 0)) and not segments_cross(
        (0, 0), (1, 1), (1, 1), (2, 0)
    )


def test_the_index_rewinds_to_a_mark_and_takes_back_exactly_what_came_after():
    idx = Index()
    idx.add("hard", Box(0, 0, 10, 10), "kept")
    idx.add_segment("dimline", (0, 20), (20, 40), "kept")
    mark = idx.mark()
    idx.add("hard", Box(30, 30, 45, 45), "later")
    idx.add("hard", Box(-1e19, 0, 1e19, 1), "huge")
    idx.add_segment("dimline", (30, 0), (40, 10), "later")
    before = (list(idx.items), list(idx.segments))
    taken = idx.rewind(mark)
    assert idx.mark() == mark
    assert not idx.hits(Box(35, 35, 40, 40)) and not idx.hits(Box(500, 0.2, 501, 0.8))
    assert not idx.crosses((30, 10), (40, 0), ("dimline",))
    assert idx.hits(Box(5, 5, 6, 6)) and idx.crosses((0, 40), (20, 20), ("dimline",))
    for kind, box, owner in taken[0]:
        idx.add(kind, box, owner)
    for kind, a, b, owner in taken[1]:
        idx.add_segment(kind, a, b, owner)
    assert (idx.items, idx.segments) == before
    assert idx.hits(Box(35, 35, 40, 40)) and idx.crosses((30, 10), (40, 0), ("dimline",))


def test_the_index_keeps_a_huge_box_apart_instead_of_binning_it():
    """A box far past any sheet (a view holding a pitch circle light-years across) or one
    that is not finite is kept apart and seen by every query, and a query that large looks
    at everything: binning either cell by cell would never end."""
    import time

    idx = Index()
    t0 = time.perf_counter()
    idx.add("hard", Box(-8e18, -3e13, 8e18, 1.6e19), "huge")
    idx.add("hard", Box(0, 0, 10, 10), "small")
    idx.add("hard", Box(float("nan"), 0, 10, 10), "nan")
    idx.add_segment("dimline", (-1e20, 0), (1e20, 0))
    assert time.perf_counter() - t0 < 1.0
    assert idx.hits(Box(500, 500, 510, 510))  # inside the huge box, far from the small one
    assert idx.hits(Box(5, 5, 6, 6), ignore="huge")  # the small one, binned as before
    assert idx.crosses((50, -5), (50, 5), ("dimline",))  # the long segment, kept apart
    assert idx.hits(Box(-1e19, -1e19, 1e19, 1e19), ignore="huge")  # a huge query sees all
    assert not idx.segment_hits(Box(0, 10, 10, 20), ("dimline",))


def test_text_with_symbols_measures_and_paints():
    pen = Pen()
    box = pen.text(0.0, 0.0, 3.0, "⌴ Ø11.00 ↧ 6.5")
    assert box.width == pytest.approx(text_width("⌴ Ø11.00 ↧ 6.5", 3.0))
    assert [i.text for i in pen.items if isinstance(i, D.TextRun)] == [" Ø11.00 ", " 6.5"]
    assert len([i for i in pen.items if isinstance(i, D.Stroke)]) >= 4
    bad = Pen()
    bad.text(0, 0, 3.0, "Ω")
    assert bad.replaced == ["Ω"] and bad.items[0].text == "?"


# ---------------------------------------------------------------------- speed (11.3)


def test_two_hundred_locations_lay_out_quickly():
    xt, truth = P.random_plate(3, n=100)
    m = facegraph.from_transmit(xt)
    by_size: dict[float, list[int]] = {}
    for k, h in enumerate(truth["holes"]):
        by_size.setdefault(round(h["diameter"], 6), []).append(k)
    groups = [("scattered", ks) for ks in by_size.values() if len(ks) > 1]
    ctx = plate((m, truth), patterns=groups)
    t0 = time.perf_counter()
    planned = make_plan(ctx)
    r = layout(planned, options=ctx.options, settings=ctx.settings)
    took = time.perf_counter() - t0
    locations = [d for d in planned.plan.dimensions if d.role == "feature_location"]
    assert len(locations) >= 190
    assert took < 6.0  # the target is 3 s (11.3); measured about 1 s here
    assert all(math.isfinite(p.origin[0]) for p in r.sheet.views)


def test_title_values_stay_under_their_labels():
    _p, r = laid(options=DrawingOptions(sheet="A"), source=_Source())
    (tb,) = of(r.sheet, D.TitleBlock)
    top = tb.at[1] + tb.height
    (label,) = [i for i in r.sheet.painted if isinstance(i, D.TextRun) and i.text == "DWG NO"]
    (number,) = [
        i
        for i in r.sheet.painted
        if isinstance(i, D.TextRun) and i.text == "FOUR-HOLES" and abs(i.x - label.x) < 3.0
    ]
    cap = number.size * fonts.CAP_HEIGHT
    assert number.y + cap <= label.y + 1e-6 and label.y < top


def _title_block(fields, *, cage=""):
    """The text runs of an A sheet's title block (127 by 50 mm) in millimetres."""
    company = replace(S.DrawingSettings().company, name="Example Engineering Co.", cage=cage)
    pen = Pen()
    titleblock.title_block(
        pen,
        Box(0.0, 0.0, 127.0, 50.0),
        unit="mm",
        fields={"cage": cage, **fields},
        tolerance_lines=(),
        rows=("DRAWN",),
        signed={},
        company=company,
        logo=None,
    )
    return [i for i in pen.items if isinstance(i, D.TextRun)]


def _cap(run):
    return run.size * fonts.CAP_HEIGHT


def test_the_logo_keeps_its_proportions_beside_the_company():
    company = replace(S.DrawingSettings().company, name="Example Engineering Co.")
    cell_width = 127.0 * 0.55  # the block's right part, the company cell's width
    for width, height in ((40, 10), (10, 10), (10, 40)):
        pen = Pen()
        out = titleblock.title_block(
            pen,
            Box(0.0, 0.0, 127.0, 50.0),
            unit="mm",
            fields={"number": "SS-1"},
            tolerance_lines=(),
            rows=("DRAWN",),
            signed={},
            company=company,
            logo=tiny_png(width, height),
        )
        (image,) = [a for a in out if isinstance(a, D.Image)]
        assert math.isclose(image.width / image.height, width / height, rel_tol=1e-9)  # never stretched
        assert image.width <= cell_width * titleblock.LOGO_SHARE + 1e-9
        assert math.isclose(image.at[0] + image.width, 127.0 - 1.0)  # against the cell's right side
        (name,) = [r for r in pen.items if isinstance(r, D.TextRun) and r.text == company.name]
        assert name.x + text_width(name.text, _cap(name), name.bold) <= image.at[0] + 1e-9


def test_a_logos_size_comes_from_its_header_alone():
    assert images.png_size(tiny_png(40, 10)) == (40, 10)
    assert images.png_size(tiny_png(40, 10)[:33]) == (40, 10)  # nothing past the header is read
    for bad in (b"not a png", tiny_png(1201, 10)):
        with pytest.raises(images.PngRefused):
            images.png_size(bad)


def test_a_long_title_goes_on_two_lines_at_the_lettering_minimum():
    title = "HOUSING, GEARBOX, LOWER, MACHINED FROM BILLET"
    runs = _title_block({"title": title, "number": "SS-1"})
    (label,) = [r for r in runs if r.text == "TITLE"]
    top, low = sorted(
        (r for r in runs if r.text in ("HOUSING, GEARBOX, LOWER,", "MACHINED FROM BILLET")),
        key=lambda r: -r.y,
    )
    assert top.text + " " + low.text == title and top.y > low.y and top.x == low.x
    assert min(_cap(top), _cap(low)) >= 3.0 - 1e-9  # one line would be 1.8 mm
    assert top.y + _cap(top) <= label.y and low.y >= 0.0
    room = 127.0 * 0.55 - 2.0
    assert max(text_width(r.text, _cap(r), True) for r in (top, low)) <= room + 1e-6
    (material,) = [r for r in runs if r.text == "MATERIAL"]
    assert material.y > 0.0  # the material row kept room for its label and value
    short = _title_block({"title": "BRACKET, MOTOR MOUNT", "number": "SS-1"})
    (one,) = [r for r in short if r.text == "BRACKET, MOTOR MOUNT"]
    assert 3.0 <= _cap(one) < 4.5  # one line set smaller, while it stays at the minimum
    (word,) = [r for r in _title_block({"title": "BRACKET", "number": "SS-1"}) if r.text == "BRACKET"]
    assert _cap(word) == pytest.approx(4.5)


def test_a_long_drawing_number_takes_the_cage_cell_when_there_is_no_cage_code():
    number = "ABCD-123456-78901"
    runs = _title_block({"title": "PLATE", "number": number})
    (shown,) = [r for r in runs if r.text == number]
    assert "CAGE" not in [r.text for r in runs] and _cap(shown) >= 3.0 - 1e-9
    caged = _title_block({"title": "PLATE", "number": number}, cage="1ABC2")
    (kept,) = [r for r in caged if r.text == number]
    assert "CAGE" in [r.text for r in caged] and _cap(kept) < 3.0  # R10.text says so
    plain = _title_block({"title": "PLATE", "number": "SS-1"})
    assert "CAGE" in [r.text for r in plain]  # a number that fits leaves the block as it was


def test_a_long_part_number_is_cut_before_the_models_revision_and_short_hash():
    part, end = "BRACKET-MOTOR-MOUNT-LEFT-HAND", " C 1A2B3C4D5E6F7A8B"
    runs = _title_block({"title": "PLATE", "number": "SS-1", "part_number": part, "model": part + end})
    (shown,) = [r for r in runs if r.text.endswith(end)]
    head = shown.text[: -len(end)]
    assert head.endswith("…") and part.startswith(head[:-1]) and len(head) > 2
    room = 127.0 * 0.55 * 0.65 - 2.0
    assert text_width(shown.text, _cap(shown), False) <= room + 1e-6
    whole = _title_block({"title": "PLATE", "number": "SS-1", "part_number": "SS-1", "model": "SS-1" + end})
    assert "SS-1" + end in [r.text for r in whole]  # a value that fits is shown whole
    # a value typed by hand, not starting with the part number, keeps its last word
    typed = _title_block({"title": "PLATE", "number": "SS-1", "model": part + " REV C 1A2B3C4D5E6F7A8B"})
    (kept,) = [r for r in typed if r.text.endswith(" 1A2B3C4D5E6F7A8B")]
    assert kept.text.startswith("BRACKET") and "…" in kept.text

