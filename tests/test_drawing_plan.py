"""The planner (docs/DRAWINGS.md 10, 19.2): requirements, the linear and angular
graphs, the baseline tree, callouts, values and notes, on hand-made feature sets and
views of the synthetic plates."""

import math
from dataclasses import replace

import pytest

import drawing_parts as P
from drawing_golden_support import settings, source_stage
from drawing_plan_fixtures import PATTERNS, plate
from solidseas.drawing import display as D
from solidseas.drawing import pipeline
from solidseas.drawing.limits import DrawingLimits
from solidseas.drawing.plan import angular, callouts, gdt, make_plan, notes, schemes, select, values
from solidseas.drawing.plan.graph import Graph
from solidseas.drawing.plan.requirements import requirements
from solidseas.drawing.plan.values import dim_text, text_line
from solidseas.drawing.settings import with_value
from solidseas.drawing.types import (
    Axis,
    Descriptor,
    DrawingOptions,
    Hole,
    HoleSegment,
    Pattern,
    PlannedDimension,
)
from solidseas.errors import SldLimitError

MM = 1e-3
SCATTERED = [("scattered", [0, 1, 2, 3])]


def texts(planned, kind=None):
    return [
        text_line(dim_text(planned.detail.ctx, d))
        for d in planned.plan.dimensions
        if kind is None or d.kind == kind
    ]


def by_key(planned):
    return {d.key: d for d in planned.plan.dimensions}


# ---------------------------------------------------------------------- requirements


def test_positions_links_and_origins():
    ctx = plate("four_holes", patterns=SCATTERED)
    req = requirements(ctx)
    xs = sorted(round(p.value / MM, 3) for p in req.positions["x"])
    assert xs == [0.0, 12.0, 37.0, 71.0, 88.0, 100.0]
    origin = req.position("x", req.origins["x"])
    assert origin.kind == "face" and origin.value == pytest.approx(0.0)  # datum C, the left face
    # the envelope joins the two end faces: one implied link per axis
    assert [lk.key for lk in req.links["x"]] == ["size/f-6"]
    kinds = sorted(n.kind for n in req.needs)
    assert kinds == ["hole_callout", "linear", "linear", "linear"]


def test_holes_in_line_are_one_position():
    ctx = plate("hole_kinds")
    req = requirements(ctx)
    ys = sorted(round(p.value / MM, 3) for p in req.positions["y"] if p.kind == "centre")
    assert ys == [20.0, 55.0]
    row = next(p for p in req.positions["y"] if p.kind == "centre" and abs(p.value - 20 * MM) < 1e-9)
    assert len(row.points) == 5 and len(row.features) == 5


# ---------------------------------------------------------------------- the graphs


def test_baseline_locates_every_hole_from_the_datums_once():
    pl = make_plan(plate("four_holes", patterns=SCATTERED))
    keys = by_key(pl)
    for fid, (x, y) in zip(
        ("f-1", "f-2", "f-3", "f-4"), [(12, 10), (37, 48), (71, 15), (88, 44)], strict=True
    ):
        dx, dy = keys[f"loc/{fid}/x"], keys[f"loc/{fid}/y"]
        assert dx.value == pytest.approx(x * MM) and dy.value == pytest.approx(y * MM)
        assert dx.tolerance == "basic" and dx.role == "feature_location"
        assert dx.positions[0].value == pytest.approx(0.0)  # from the datum face itself
        assert dx.positions[1].centre and dx.positions[1].radius == pytest.approx(3.3 * MM)
    assert all(g.complete and not g.redundant for g in pl.plan.graphs)


def test_the_checker_names_the_features_and_the_loops():
    pl = make_plan(plate("four_holes", patterns=SCATTERED))
    g = pl.detail.graphs["x"]
    edges = [(pa, pb, did) for did, (ax, pa, pb) in pl.detail.edges.items() if ax == "x"]
    assert g.check(edges).complete
    gone = g.check(edges[1:])
    assert not gone.complete and len(gone.missing) == 1 and gone.missing[0].startswith("loc/f-")
    node = next(n for n in g.nodes if g.keys(n) == gone.missing)
    assert g.label(node, pl.detail.ctx).startswith("the Ø6.60 hole")
    # a dimension between two located holes closes a loop through the datum
    a, b = edges[0][1], edges[1][1]
    looped = g.check(edges + [(a, b, "d-99")])
    assert looped.redundant and "d-99" in looped.loops[0] and len(looped.loops[0]) == 3


def test_patterns_state_pitch_count_circle_and_angle():
    pl = make_plan(plate("patterns", patterns=PATTERNS))
    t = texts(pl)
    assert "5X Ø5.50 THRU" in t and "6X Ø4.50 THRU" in t and "6X Ø5.50 THRU" in t
    assert "[4X 20]" in t and "[2X 15]" in t and "[12]" in t  # pitches, basic under the datum scheme
    assert "[Ø40]" in t and "[15°]" in t
    keys = by_key(pl)
    assert (
        keys["pitch/f-19/x"].prefix == "4X "
        and keys["pitch/f-20/x"].prefix == "2X "
        and keys["pcd/f-21"].tolerance == "basic"
    )
    angle = keys["angle/f-21"]
    assert math.degrees(angle.value) == pytest.approx(15.0)
    # measured from X, the record's anchor on the member it measures (conventions.md 8)
    fs = plate("patterns", patterns=PATTERNS).features
    circle = fs.features[20]  # f-21
    assert angle.axis == "x" and angle.anchor == fs.features[circle.members[0]].axis.point
    assert [g.graph for g in pl.plan.graphs if g.graph.startswith("angular")] == ["angular/f-21"]
    assert all(g.complete and not g.redundant for g in pl.plan.graphs)


def test_a_member_on_a_centre_line_needs_no_angle():
    ctx = plate("patterns", patterns=PATTERNS)
    fs = ctx.features
    pk = len(fs.features) - 4  # the circular pattern
    feats = list(fs.features)
    feats[pk] = replace(feats[pk], first_angle=0.0)
    ctx = replace(ctx, features=replace(fs, features=tuple(feats)))
    pl = make_plan(ctx)
    assert not [d for d in pl.plan.dimensions if d.kind == "angle"]
    assert all(g.complete for g in pl.plan.graphs)


def _arc_run(angles):
    xt, truth = P.arc_plate(angles)
    stages = {"source": source_stage("arc_plate", xt, truth)}
    return pipeline.run(None, options=DrawingOptions(units="mm"), settings=settings(), stages=stages)


def test_an_arc_pattern_states_its_pitch_circle_count_step_and_first_angle():
    """Five holes 30 degrees apart from 20 degrees round a bore: the callout with 5X, the
    pitch circle, the first end's angle from X and the step with its four spaces, each
    member located through them and none on its own."""
    run = _arc_run([20, 50, 80, 110, 140])
    planned = run.orchestrated.planned
    t = texts(planned)
    assert "5X Ø5.00 THRU" in t and "[Ø60]" in t and "[20°]" in t and "[4X 30°]" in t
    keys = by_key(planned)
    fid = next(k.split("/")[1] for k in keys if k.startswith("step/"))
    assert keys[f"step/{fid}"].prefix == "4X " and math.degrees(keys[f"step/{fid}"].value) == pytest.approx(
        30
    )
    assert len([k for k in keys if k.startswith("loc/")]) == 2  # the bore's, along X and Y
    assert all(g.complete and not g.redundant for g in planned.plan.graphs)
    # without the step the arc's graph is incomplete, and the checks say so
    ctx = planned.detail.ctx
    rest = [d for d in planned.plan.dimensions if not d.key.startswith("step/")]
    (g,) = [g for g in angular.check(ctx, rest) if g.graph == f"angular/{fid}"]
    assert not g.complete and g.missing == (f"step/{fid}",)
    # drawn: the angle from X to the first end, the step from it to the second, and the
    # pitch circle as a centre-line arc a little past the end holes
    sheet = run.drawing.sheet
    sides = []
    for a in sheet.annotations:
        if isinstance(a, D.Dimension) and a.kind == "angle":
            c, p0, p1, _pm = a.points
            sides.append(
                sorted(round(math.degrees(math.atan2(p[1] - c[1], p[0] - c[0])), 6) for p in (p0, p1))
            )
    assert sorted(sides) == [[0.0, 20.0], [20.0, 50.0]]
    (arc,) = [g for g in sheet.geometry if isinstance(g, D.Arc) and g.style == "centre"]
    assert arc.start_deg == pytest.approx(10.0) and arc.end_deg == pytest.approx(150.0)
    assert not [c for c in run.drawing.checks if c.code.startswith(("R4", "R5"))]


def test_an_arc_past_ninety_degrees_is_angled_from_the_nearer_way_along_the_axis():
    run = _arc_run([110, 140, 170, 200, 230])
    keys = by_key(run.orchestrated.planned)
    first = next(d for k, d in keys.items() if k.startswith("angle/"))
    assert math.degrees(first.value) == pytest.approx(70.0) and first.axis == "x"


@pytest.mark.parametrize("start", [0, 90, 180, 270])
def test_a_pitch_circle_with_a_hole_on_a_centre_line_asks_for_no_angle(start):
    """Five holes round the whole circle from each principal axis: the hole on the centre
    line is the first and nothing asks for an angle to locate it. From 0 degrees the
    hole on X once came out a hair short of 360 degrees, and the 72 degree hole was taken
    as the first and given a 72 degree angle."""
    run = _arc_run([start + 72 * k for k in range(5)])
    planned = run.orchestrated.planned
    (p,) = [f for f in run.features.features if isinstance(f, Pattern)]
    assert p.kind == "circular" and math.degrees(p.first_angle) == pytest.approx(start)
    first = run.features.features[p.members[0]].axis.point
    a = math.radians(start)
    assert first[:2] == pytest.approx((50 * MM + 30 * MM * math.cos(a), 50 * MM + 30 * MM * math.sin(a)))
    assert not [d for d in planned.plan.dimensions if d.kind == "angle"]
    assert all(g.complete and not g.redundant for g in planned.plan.graphs)


def test_a_depth_no_view_shows_becomes_a_note():
    from solidseas.drawing.plan.requirements import Need
    from solidseas.drawing.types import Requirement

    ctx = plate("four_holes", patterns=SCATTERED)
    req = requirements(ctx)
    pos = req.positions["z"]
    a, b = pos[0].id, pos[-1].id
    need = Need(
        Requirement(
            "depth/f-1",
            "size",
            ("f-1",),
            8 * MM,
            "feature_size",
            axis="z",
            satisfied_by=("linear", "leader_note"),
        ),
        "linear",
        axis="z",
        a=a,
        b=b,
        anchor=(0.05, 0.03, 0.01),
        facing=(0.0, 0.0, 1.0),
        features=(0,),
        role="step",
    )
    from solidseas.drawing.plan import PlanDetail, _Ids, _need_dimension
    from solidseas.drawing.plan.assign import Assigner

    only_front = replace(ctx, views=ctx.views[:1])
    detail = PlanDetail(only_front, req, {})
    pd = _need_dimension(only_front, req, need, Assigner(only_front, ["v-1"]), _Ids(), ("f-1",), detail)
    assert pd.kind == "leader_note" and pd.suffix == ("↧ 8.0",) and pd.axis == "z"
    assert len(pd.positions) == 2  # the oracle reads the depth from them


# ---------------------------------------------------------------------- views


def test_the_view_set_keeps_only_what_draws_something():
    pl = make_plan(plate("four_holes", patterns=SCATTERED))
    assert [s.name for s in pl.plan.views] == ["front", "top", "isometric"]  # the right adds nothing
    assert {d.view for d in pl.plan.dimensions if d.axis == "z"} == {"v-2"}


def test_the_front_faces_the_holes():
    ctx = plate("four_holes", patterns=SCATTERED)
    choice = select.choose_front(ctx)
    assert (choice.front, choice.turn) == ("+z", 0)
    assert "holes" in choice.reason and "longest side runs across" in choice.reason


# ---------------------------------------------------------------------- callouts


def _hole(kind, segments, ends=("open", "open"), depth=20 * MM, entry_break=None):
    return Hole(
        (),
        Descriptor("hole"),
        axis=Axis((0, 0, 0), (0, 0, -1)),
        segments=segments,
        kind=kind,
        ends=ends,
        depth=depth,
        entry_break=entry_break,
    )


@pytest.mark.parametrize(
    "hole, count, expect",
    [
        (_hole("simple", (HoleSegment("cylinder", 6.6 * MM),)), 4, ("4X Ø", ("THRU",))),
        (
            _hole(
                "counterbore",
                (
                    HoleSegment("cylinder", 11 * MM, depth=6.5 * MM),
                    HoleSegment("annulus"),
                    HoleSegment("cylinder", 6.6 * MM),
                ),
            ),
            1,
            ("Ø", ("THRU", "⌴ Ø11.00 ↧ 6.5")),
        ),
        (
            _hole(
                "spotface",
                (
                    HoleSegment("cylinder", 13 * MM, depth=0.5 * MM),
                    HoleSegment("annulus"),
                    HoleSegment("cylinder", 6.6 * MM),
                ),
            ),
            1,
            ("Ø", ("THRU", "⌴SF Ø13.00 ↧ 0.5")),
        ),
        (
            _hole(
                "countersink",
                (
                    HoleSegment("cone", 12 * MM, 6.6 * MM, angle=math.radians(82)),
                    HoleSegment("cylinder", 6.6 * MM),
                ),
            ),
            2,
            ("2X Ø", ("THRU", "⌵ Ø12.00 X 82°")),
        ),
        (
            _hole("simple", (HoleSegment("cylinder", 8 * MM, depth=12 * MM),), ("open", "blind"), 12 * MM),
            1,
            ("Ø", ("↧ 12.0",)),
        ),
        (
            _hole("simple", (HoleSegment("cylinder", 10 * MM),), entry_break=("round", 1 * MM, ())),
            1,
            ("Ø", ("THRU", "R1.0 AT ENTRY")),
        ),
        (
            _hole("simple", (HoleSegment("cylinder", 10 * MM),), entry_break=("round", 0.2 * MM, ())),
            1,
            ("Ø", ("THRU",)),
        ),
    ],
)
def test_hole_callouts(hole, count, expect):
    ctx = plate("four_holes")
    prefix, value, suffix = callouts.hole(ctx, hole, count, "f-1")
    assert (prefix, suffix) == expect
    assert value == pytest.approx(hole.segments[-1].diameter)


def test_a_confirmed_thread_and_words_for_symbols():
    ctx = plate("four_holes")
    blind = _hole("simple", (HoleSegment("cylinder", 6.8 * MM, depth=14 * MM),), ("open", "blind"), 14 * MM)
    ctx.decisions["f-1"] = {"thread": "M8 x 1.25 - 6H", "thread_depth": 10 * MM}
    _p, _v, suffix = callouts.hole(ctx, blind, 1, "f-1")
    assert suffix == ("↧ 14.0", "M8 x 1.25 - 6H ↧ 10.0")
    dims = dict(ctx.settings.defaults.dimensioning)
    worded = {t: {**dims[t], "symbol_words": True} for t in dims}
    wctx = replace(ctx, settings=with_value(ctx.settings, "defaults", "dimensioning", worded))
    _p, _v, suffix = callouts.hole(wctx, blind, 1, "f-1")
    assert suffix == ("DEEP 14.0", "M8 x 1.25 - 6H DEEP 10.0")
    # nothing is a thread until the user confirms it
    _p, _v, suffix = callouts.hole(plate("four_holes"), blind, 1, "f-1")
    assert suffix == ("↧ 14.0",)


def test_callouts_carry_a_position_frame_under_the_datum_scheme_only():
    pl = make_plan(plate("four_holes", patterns=SCATTERED))
    callout = next(d for d in pl.plan.dimensions if d.kind == "hole_callout")
    f = callout.frame
    assert (
        f.characteristic == "position" and f.diameter and f.modifier == "mmc" and f.datums == ("A", "B", "C")
    )
    assert f.value == pytest.approx(0.25 * MM)
    pm = make_plan(plate("four_holes", patterns=SCATTERED, options=DrawingOptions(scheme="plusminus")))
    assert all(d.frame is None for d in pm.plan.dimensions)
    assert not [d for d in pm.plan.dimensions if d.kind == "datum_feature"]
    assert all(d.tolerance == "block" for d in pm.plan.dimensions if d.role == "feature_location")


def test_plus_minus_draws_datums_when_the_model_governs():
    pl = make_plan(
        plate("four_holes", patterns=SCATTERED, unclaimed=2, options=DrawingOptions(scheme="plusminus"))
    )
    assert [d.suffix[0] for d in pl.plan.dimensions if d.kind == "datum_feature"] == ["A", "B", "C"]
    assert pl.plan.notes[-1].text.startswith("REDUCED-DIMENSION DRAWING")


# ---------------------------------------------------------------------- values


def test_inch_precision_by_role_and_basic_places():
    pl = make_plan(plate("four_holes", patterns=SCATTERED, unit="in"))
    t = texts(pl)
    assert "4X Ø.260 THRU" in t  # hole sizes to three places
    assert "3.94" in t and "2.36" in t and ".39" in t  # the envelope to two
    assert "[.4724]" in t  # 12 mm shown to the places it needs, at most four
    assert pl.plan.tolerance_block[0].endswith("INCHES")


def test_printed_parts_show_nominals_and_see_note():
    ctx = plate("four_holes", patterns=SCATTERED, options=DrawingOptions(process="printed"))
    pl = make_plan(ctx, fields={"process": "SLA"})
    t = texts(pl)
    assert "100" in t and "60" in t and "10" in t  # as needed, no decimal block
    assert pl.plan.tolerance_block[1] == "GENERAL TOLERANCES: SEE NOTE 1"
    assert pl.plan.notes[0].text.startswith("GENERAL TOLERANCES (SLA):")
    assert pl.plan.bands == ()


def test_bands_and_the_rounding_guard():
    pl = make_plan(plate("four_holes", patterns=SCATTERED))
    assert pl.plan.bands == (("±0.2", 3), ("±0.05", 1))
    ctx = pl.detail.ctx
    d = PlannedDimension("size/f-9", "d-1", "linear", "v-1", 10.046 * MM, places=1)
    assert values.rounding(ctx, d)  # shown as 10.0, 0.046 off a 0.4 band: over a tenth
    assert not values.rounding(ctx, replace(d, value=10.01 * MM))


def test_derived_radii_say_R_alone():
    ctx = plate("four_holes")
    pd = PlannedDimension("radius/f-1", "d-1", "radius", "v-1", 15 * MM, prefix="2X R", tolerance="derived")
    assert text_line(dim_text(ctx, pd)) == "2X R"


# ---------------------------------------------------------------------- notes and title


class _Source:
    name = "BRACKET-7.SLDPRT"
    material = "6061-T6 (SS)"
    sha256 = "ab" * 32
    configuration = None
    hints = ()

    def property(self, *names):
        table = {"description": "Mounting bracket", "revision": "C"}
        for n in names:
            if n.casefold() in table:
                return table[n.casefold()]
        return None


def test_title_fields_from_the_wizard_the_part_and_the_file():
    ctx = plate("four_holes")
    title = notes.title_fields(ctx, _Source(), {"number": "DWG-100"})
    assert title["number"] == ("DWG-100", "typed")
    assert title["title"] == ("MOUNTING BRACKET", "part")
    assert title["part_number"] == ("DWG-100", "typed")
    assert title["material"] == ("ALUMINUM 6061-T6", "list")
    assert title["model"][0] == "DWG-100 C " + "AB" * 8
    assert title["weight"][0].endswith(" KG")
    bare = notes.title_fields(ctx, None, {})
    assert bare["number"][0] == "FOUR_HOLES" and bare["revision"] == ("A", "list")


def test_notes_fill_their_tokens_and_drop_the_empty_ones():
    pl = make_plan(plate("four_holes", patterns=SCATTERED), _Source())
    words = [n.text for n in pl.plan.notes]
    assert words[0] == notes.PROFILE_WORDS and pl.plan.notes[0].frames[0].characteristic == "profile_surface"
    assert "REMOVE ALL BURRS. BREAK SHARP EDGES 0.1-0.4" in words
    assert "SURFACE FINISH RA 3.2 µm MAX." in words  # the micro sign kept, its unit as written
    assert not any("FILLETS" in w for w in words)  # no blends, so no fillet note
    assert not any("FINISH:" in w for w in words)  # no finish named
    assert notes.fill("FINISH: {finish}.", {"finish": ""}) is None


def test_the_tolerance_block():
    block = notes.tolerance_block(plate("four_holes"))
    assert block == (
        "UNLESS OTHERWISE SPECIFIED: DIMENSIONS ARE IN MILLIMETERS",
        "TOLERANCES: X ±0.5  X.X ±0.2  X.XX ±0.05",
        "ANGLES ±0.5°",
        "DIMENSIONING AND TOLERANCING PER ASME Y14.5-2018",
    )
    inch = notes.tolerance_block(plate("four_holes", unit="in"))
    assert inch[1] == "TOLERANCES: .X ±.030  .XX ±.010  .XXX ±.005"


def test_gdt_values_follow_the_unit():
    ctx = plate("four_holes", unit="in")
    pos = gdt.position(ctx)
    assert pos.value == pytest.approx(0.010 * 25.4 * MM) and gdt.zone_text(ctx, pos.value) == ".010"
    assert gdt.zone_text(plate("four_holes"), gdt.profile(plate("four_holes")).value) == "0.4"


# ---------------------------------------------------------------------- schemes and bounds


def test_ordinate_when_baseline_needs_too_many_tracks():
    pl = make_plan(plate("hole_kinds"))
    xs = [d for d in pl.plan.dimensions if d.role == "feature_location" and d.axis == "x"]
    assert len(xs) == 8 and {d.kind for d in xs} == {"ordinate"}
    ys = [d for d in pl.plan.dimensions if d.role == "feature_location" and d.axis == "y"]
    assert {d.kind for d in ys} == {"linear"}
    forced = make_plan(plate("hole_kinds", options=DrawingOptions(arrangement=(("v-1/x", "baseline"),))))
    assert {d.kind for d in forced.plan.dimensions if d.role == "feature_location" and d.axis == "x"} == {
        "linear"
    }
    assert schemes.arrangement(plate("four_holes"), "v-1", "x", 3, frozenset({"v-1/x"})) == "ordinate"
    assert schemes.arrangement(plate("four_holes"), "v-1", "x", 2, frozenset({"v-1/x"})) == "baseline"


def test_the_requirement_bound():
    with pytest.raises(SldLimitError) as info:
        make_plan(plate("patterns", patterns=PATTERNS), limits=DrawingLimits(requirements=10))
    assert info.value.detail["limit"] == "requirements"


def test_planning_twice_gives_the_same_plan():
    a = make_plan(plate("patterns", patterns=PATTERNS)).plan
    b = make_plan(plate("patterns", patterns=PATTERNS)).plan
    assert a == b
    assert [d.id for d in a.dimensions] == [f"d-{k}" for k in range(1, len(a.dimensions) + 1)]


def test_requirement_keys_name_features():
    pl = make_plan(plate("patterns", patterns=PATTERNS))
    for d in pl.plan.dimensions:
        assert d.serves and all(k.split("/")[1].startswith(("f-", "a", "b", "c")) for k in d.serves), d.key
    graph = pl.detail.graphs["y"]
    assert isinstance(graph, Graph)
