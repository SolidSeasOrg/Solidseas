"""Feature recognition against the synthetic parts' ground truth and the fixtures
(docs/DRAWINGS.md 9, 19.2)."""

import math

import pytest

import drawing_parts as P
from drawing_support import fixture, model
from solidseas import open_document
from solidseas.drawing import facegraph
from solidseas.drawing import types as T
from solidseas.drawing.features import hints, recognise, threads
from solidseas.drawing.features._common import Rays
from solidseas.drawing.features.frame import directions, make_frame
from solidseas.drawing.limits import DrawingLimits
from solidseas.errors import SldLimitError

MM = 1e-3


def of(fs, cls):
    return [f for f in fs.features if isinstance(f, cls)]


def near(a, b, tol=1e-6):
    return abs(a - b) <= tol


@pytest.fixture(scope="module")
def kinds():
    return recognise(model("hole_kinds"))


def _hole_at(fs, x, y):
    for h in of(fs, T.Hole):
        if near(h.axis.point[0], x * MM) and near(h.axis.point[1], y * MM):
            return h
    raise AssertionError(f"no hole at {x}, {y}")


def test_every_hole_kind_is_classified(kinds):
    expect = {
        (15, 20): ("simple", ("open", "open")),
        (40, 20): ("counterbore", ("open", "open")),
        (65, 20): ("spotface", ("open", "open")),
        (90, 20): ("countersink", ("open", "open")),
        (115, 20): ("countersink", ("open", "open")),
        (30, 55): ("simple", ("open", "blind")),
        (70, 55): ("simple", ("open", "blind")),
        (110, 55): ("stepped", ("open", "open")),
    }
    assert len(of(kinds, T.Hole)) == len(expect)
    for (x, y), (kind, ends) in expect.items():
        h = _hole_at(kinds, x, y)
        assert (h.kind, h.ends) == (kind, ends), (x, y)
        assert h.entry_kind == "planar_square" and not h.needs_auxiliary
        assert h.axis.direction == pytest.approx((0.0, 0.0, -1.0))
        assert h.cover == pytest.approx(2 * math.pi)


def test_segments_from_the_entry(kinds):
    cbore = _hole_at(kinds, 40, 20)
    assert [s.kind for s in cbore.segments] == ["cylinder", "annulus", "cylinder"]
    assert cbore.segments[0].diameter == pytest.approx(11 * MM)
    assert cbore.segments[0].depth == pytest.approx(6.5 * MM)
    assert cbore.segments[2].diameter == pytest.approx(6.6 * MM) and cbore.diameter == pytest.approx(6.6 * MM)
    csk = _hole_at(kinds, 90, 20)
    assert csk.segments[0].kind == "cone" and math.degrees(csk.segments[0].angle) == pytest.approx(82.0)
    assert csk.segments[0].diameter == pytest.approx(12 * MM)
    assert math.degrees(_hole_at(kinds, 115, 20).segments[0].angle) == pytest.approx(90.0)
    step = _hole_at(kinds, 110, 55)
    assert [s.kind for s in step.segments] == ["cylinder", "cone", "cylinder"]


def test_blind_depth_is_to_the_full_diameter(kinds):
    flat = _hole_at(kinds, 30, 55)
    assert flat.segments[-1].kind == "flat_bottom" and flat.depth == pytest.approx(12 * MM)
    point = _hole_at(kinds, 70, 55)
    assert point.segments[-1].kind == "drill_point" and math.degrees(
        point.segments[-1].angle
    ) == pytest.approx(118.0)
    assert point.depth == pytest.approx(14 * MM)  # not to the tip of the point
    assert "M8 x 1.25" in point.thread  # 6.8 mm is its tap drill: a candidate only


def test_through_holes_are_as_deep_as_the_part(kinds):
    assert _hole_at(kinds, 15, 20).depth == pytest.approx(20 * MM)
    assert _hole_at(kinds, 15, 20).through


def test_holes_that_differ_are_never_one_pattern(kinds):
    # the two countersinks differ in angle, so they are not a pattern of two
    assert of(kinds, T.Pattern) == []


def test_linear_grid_and_circular_patterns():
    fs = recognise(model("patterns"))
    pats = {p.kind: p for p in of(fs, T.Pattern)}
    assert set(pats) == {"linear", "grid", "circular"}
    assert pats["linear"].counts == (5,) and pats["linear"].pitches[0] == pytest.approx(20 * MM)
    assert pats["grid"].counts == (3, 2)
    assert pats["grid"].pitches == pytest.approx((15 * MM, 12 * MM))
    c = pats["circular"]
    assert c.counts == (6,) and c.pitch_diameter == pytest.approx(40 * MM)
    assert math.degrees(c.step) == pytest.approx(60.0) and math.degrees(c.first_angle) == pytest.approx(15.0)
    # members in angle order from the first, each a hole of the set
    holes = fs.features
    angles = [
        math.degrees(math.atan2(holes[m].axis.point[1] - c.centre[1], holes[m].axis.point[0] - c.centre[0]))
        % 360
        for m in c.members
    ]
    assert angles == pytest.approx([15, 75, 135, 195, 255, 315])
    assert all(isinstance(holes[m], T.Hole) for p in pats.values() for m in p.members)
    bore = [h for h in of(fs, T.Hole) if near(h.diameter, 16 * MM)]
    assert len(bore) == 1  # the bore in the middle is no member


def test_a_row_of_holes_straight_but_for_the_last_bits_is_never_a_circle():
    """Centres in a row whose coordinates carry the noise a real part's do fit a circle
    light-years across, which every member then lies on: they are a row (linear), never a
    pitch circle, which the layout once tried to bin cell by cell and never finished (the
    New Drawing preview spun until its time limit on simple parts)."""
    from solidseas.drawing.features import patterns as pat

    pts = {k: (0.02 * k, 1e-18 if k % 2 else 0.0) for k in range(5)}
    assert pat._circle(pts[0], pts[1], pts[2])[1] > 1e9  # the fit the noise allows
    tol = 1e-9
    assert pat._circular(None, list(pts), pts, None, None, tol) is None
    row = pat._linear(list(pts), pts, tol)
    assert row["kind"] == "linear" and row["counts"] == (5,) and row["pitches"][0] == pytest.approx(0.02)


def test_holes_on_a_circle_at_uneven_angles_are_no_pitch_circle():
    """The four corner holes of a rectangle, or of an isosceles trapezoid, lie on one
    circle; unevenly spaced round it they are located as the grid or the holes they are,
    never as a pitch circle round the part with its angles."""
    from solidseas.drawing.features import patterns as pat

    trapezoid = {0: (-0.03, 0.0), 1: (0.03, 0.0), 2: (-0.02, 0.02), 3: (0.02, 0.02)}
    fit = pat._circle(trapezoid[0], trapezoid[1], trapezoid[2])
    assert abs(math.dist(trapezoid[3], fit[0]) - fit[1]) < 1e-12  # all four on one circle
    assert pat._circular(None, list(trapezoid), trapezoid, None, None, 1e-9) is None
    rectangle = {0: (0.0, 0.0), 1: (0.04, 0.0), 2: (0.0, 0.02), 3: (0.04, 0.02)}
    assert pat._circular(None, list(rectangle), rectangle, None, None, 1e-9) is None
    assert pat._grid(list(rectangle), rectangle, 1e-9)["kind"] == "grid"


def arc_patterns(angles, bore=True):
    xt, _truth = P.arc_plate(angles, bore)
    fs = recognise(facegraph.from_transmit(xt, name="arc_plate"))
    return fs, of(fs, T.Pattern)


def member_angles(fs, p):
    return [
        math.degrees(
            math.atan2(fs.features[m].axis.point[1] - p.centre[1], fs.features[m].axis.point[0] - p.centre[0])
        )
        % 360
        for m in p.members
    ]


def test_five_holes_thirty_degrees_apart_are_one_arc_pattern():
    fs, pats = arc_patterns([20, 50, 80, 110, 140])
    (p,) = pats
    assert p.kind == "arc" and p.counts == (5,) and p.pitch_diameter == pytest.approx(60 * MM)
    assert math.degrees(p.step) == pytest.approx(30.0) and math.degrees(p.first_angle) == pytest.approx(20.0)
    assert p.centre[:2] == pytest.approx((50 * MM, 50 * MM))
    # from one end to the other, so the included angle is the step times the spaces
    assert member_angles(fs, p) == pytest.approx([20, 50, 80, 110, 140])


def test_an_arc_starts_at_the_end_a_centre_line_locates():
    fs, (p,) = arc_patterns([30, 60, 90])
    assert p.kind == "arc" and math.degrees(p.first_angle) == pytest.approx(90.0)
    assert member_angles(fs, p) == pytest.approx([90, 60, 30])


def test_holes_on_an_arc_at_uneven_angles_are_no_arc_pattern():
    _fs, pats = arc_patterns([20, 50, 85, 110, 140])
    assert [p.kind for p in pats] == ["scattered"]


def test_holes_equally_spaced_round_the_whole_circle_are_still_a_pitch_circle():
    _fs, (p,) = arc_patterns([10, 82, 154, 226, 298])
    assert p.kind == "circular" and p.counts == (5,)
    assert math.degrees(p.step) == pytest.approx(72.0) and math.degrees(p.first_angle) == pytest.approx(10.0)


def test_the_first_hole_round_a_pitch_circle_is_the_one_on_a_centre_line():
    """Five holes from 0 degrees: the hole on X is the first though atan2 may put it a hair
    short of 360 degrees. From 90, 180 or 270 degrees, where the step does not divide the
    quarter turn, the hole on the centre line is still the first."""
    fs, (p,) = arc_patterns([0, 72, 144, 216, 288])
    assert p.kind == "circular" and p.first_angle == pytest.approx(0.0, abs=1e-9)
    assert [round(a) % 360 for a in member_angles(fs, p)] == [0, 72, 144, 216, 288]
    for start in (90, 180, 270):
        fs, (p,) = arc_patterns([start + 72 * k for k in range(5)])
        assert math.degrees(p.first_angle) == pytest.approx(start)
        assert round(member_angles(fs, p)[0]) % 360 == start


def test_two_holes_on_a_circle_are_a_pair_not_an_arc():
    _fs, (p,) = arc_patterns([20, 50])
    assert p.kind == "linear" and p.counts == (2,)


def test_three_holes_make_an_arc_only_round_another_round_feature():
    """Any isosceles triangle of holes lies on a circle at an equal step, an L of three on a
    plate among them: three are an arc only round a bore or boss, more stand alone."""
    _fs, (p,) = arc_patterns([20, 50, 80])
    assert p.kind == "arc" and p.counts == (3,)
    _fs, (p,) = arc_patterns([20, 50, 80], bore=False)
    assert p.kind == "scattered"
    _fs, (p,) = arc_patterns([20, 50, 80, 110], bore=False)
    assert p.kind == "arc" and p.counts == (4,)


def test_scattered_holes_are_each_located():
    fs = recognise(model("four_holes"))
    (p,) = of(fs, T.Pattern)
    assert p.kind == "scattered" and len(p.members) == 4
    fs16 = recognise(model("sixteen_holes"))
    (p16,) = of(fs16, T.Pattern)
    assert p16.kind == "scattered" and len(p16.members) == 16


def test_the_envelope_and_widths():
    fs = recognise(model("four_holes"))
    env = {w.axis: w.size for w in of(fs, T.Width) if w.role == "envelope"}
    assert env == pytest.approx({"x": 100 * MM, "y": 60 * MM, "z": 10 * MM})


def test_the_pocket_and_tab_are_stated_directly():
    xt, truth = P.pocket_tab_block()
    fs = recognise(facegraph.from_transmit(xt))
    (pocket,) = of(fs, T.Pocket)
    assert pocket.depth == pytest.approx(truth["pocket"]["depth"]) and pocket.open_sides == 0
    widths = of(fs, T.Width)
    gaps = sorted(round(w.size / MM, 6) for w in widths if w.kind == "gap")
    assert gaps == [12.0, 40.0]  # the pocket's width and length
    tab = [w for w in widths if w.kind == "material" and w.role == "wall" and w.axis == "x"]
    assert [round(w.size / MM, 6) for w in tab] == [6.0]
    # the walls beside the pocket are positions, never in the envelope's place (C10)
    assert {w.axis for w in widths if w.role == "envelope"} == {"x", "y", "z"}
    (depth,) = fs.depths
    assert depth.value == pytest.approx(8 * MM) and depth.axis == "z"
    assert isinstance(fs.features[depth.feature], T.Pocket)


def test_slots_steps_and_chamfers():
    fs = recognise(model("step_slot"))
    slots = sorted(of(fs, T.Slot), key=lambda s: s.width)
    assert [round(s.width / MM, 6) for s in slots] == [6.0, 8.0]
    assert [round(s.centre_distance / MM, 6) for s in slots] == [20.0, 30.0]
    assert slots[0].depth == pytest.approx(5 * MM) and slots[1].depth is None
    chamfers = of(fs, T.Chamfer)
    assert len(chamfers) == 5
    assert all(
        c.legs == pytest.approx((3 * MM, 3 * MM)) and math.degrees(c.angle) == pytest.approx(45.0)
        for c in chamfers
    )
    steps = {(s.axis, round(s.offset / MM, 6)) for s in of(fs, T.Step)}
    assert ("y", 40.0) in steps
    assert not [w for w in of(fs, T.Width) if w.kind == "gap"]  # the slots' widths are the slots'
    assert fs.coverage.complete


def test_full_round_ends_are_derived():
    fs = recognise(model("link"))
    blends = of(fs, T.Blend)
    assert len(blends) == 2 and all(b.derived and b.kind == "round" for b in blends)
    assert all(b.radius == pytest.approx(15 * MM) for b in blends)
    (pair,) = of(fs, T.Pattern)
    assert pair.kind == "linear" and pair.pitches[0] == pytest.approx(90 * MM)


def test_bosses_and_a_hole_through_one():
    fs = recognise(model("boss"))
    (boss,) = of(fs, T.Boss)
    assert boss.diameter == pytest.approx(30 * MM) and boss.length == pytest.approx(15 * MM)
    (hole,) = of(fs, T.Hole)
    assert hole.through and hole.depth == pytest.approx(35 * MM) and hole.entry_kind == "planar_square"
    assert hole.axis.direction == pytest.approx((0.0, 0.0, -1.0))  # entered from the boss's top


def test_a_face_groove_is_neither_a_hole_nor_a_counterbore():
    fs = recognise(model("groove"))
    (g,) = of(fs, T.Groove)
    assert (g.inner, g.outer, g.depth) == pytest.approx((40 * MM, 50 * MM, 3 * MM))
    assert g.width == pytest.approx(5 * MM) and g.opens_on >= 0
    (hole,) = of(fs, T.Hole)
    assert hole.kind == "simple" and hole.diameter == pytest.approx(20 * MM)


def test_the_angled_face_meets_its_plane_at_a_virtual_sharp():
    fs = recognise(model("angled_round"))
    (a,) = of(fs, T.AngledFace)
    assert math.degrees(a.angle) == pytest.approx(30.0) and a.virtual_sharp
    _xt, truth = P.angled_round_block()
    sharp = truth["angled"]["sharp"]
    p, d = a.meet_line.point, a.meet_line.direction
    # the meet line passes through the corner the round replaced
    t = (sharp[0] - p[0]) * d[0] + (sharp[1] - p[1]) * d[1]
    assert (p[0] + t * d[0], p[1] + t * d[1]) == pytest.approx(sharp, abs=1e-9)
    (blend,) = of(fs, T.Blend)
    assert blend.radius == pytest.approx(5 * MM) and not blend.derived


def test_an_inclined_hole_needs_an_auxiliary_view():
    fs = recognise(model("inclined_hole"))
    (hole,) = of(fs, T.Hole)
    assert hole.needs_auxiliary and hole.ends == ("open", "blind")
    assert {u.reason for u in fs.unclaimed} == {"needs_auxiliary"}
    assert set(hole.faces) == {u.face for u in fs.unclaimed}
    assert not fs.coverage.complete and fs.coverage.features_unclaimed == 1
    assert "reduced-dimension drawing" in fs.coverage.words()
    assert any("auxiliary" in w for w in fs.warnings)


def test_holes_on_side_faces():
    fs = recognise(model("printed_bracket"))
    holes = of(fs, T.Hole)
    assert len(holes) == 4 and all(h.through and near(h.diameter, 5 * MM) for h in holes)
    assert sorted({tuple(round(c) for c in h.axis.direction) for h in holes}) == [(-1, 0, 0), (0, -1, 0)]
    assert sorted(p.kind for p in of(fs, T.Pattern)) == ["linear", "linear"]


def test_the_o11_and_o10_fixtures():
    with open_document(fixture("o11_curved.SLDPRT")) as doc:
        fs = recognise(facegraph.from_document(doc))
    (hole,) = of(fs, T.Hole)
    assert hole.through and hole.diameter == pytest.approx(10 * MM)
    assert hole.entry_break[0] == "round" and hole.entry_break[1] == pytest.approx(1 * MM)
    rounds = of(fs, T.Blend)
    assert len(rounds) == 4 and all(b.radius == pytest.approx(3 * MM) and b.kind == "round" for b in rounds)
    assert [d.letter for d in fs.frame.datums] == ["A", "B", "C"] and fs.coverage.complete
    with open_document(fixture("o10_import_step_cut.SLDPRT")) as doc:
        fs10 = recognise(facegraph.from_document(doc))
    (h10,) = of(fs10, T.Hole)
    assert h10.through and h10.diameter == pytest.approx(5 * MM)


def test_datums_and_the_frame():
    fs = recognise(model("hole_kinds"))
    m = model("hole_kinds")
    a, b, c = fs.frame.datums
    assert a.reason == "the largest planar face" and m.faces[a.face].area == max(f.area for f in m.faces)
    assert fs.frame.model_axes and fs.frame.extents[2] == pytest.approx((0.0, 20 * MM))
    hinted = make_frame(m, fs.frame)
    assert hinted.datums == fs.frame.datums
    assert directions(m)[1] is True
    # equal faces put the datum on the low side, where the drawing's origin sits
    plate = model("four_holes")
    normals = [plate.faces[d.face].surface.normal for d in recognise(plate).frame.datums]
    assert normals == [pytest.approx(n) for n in ((0, 0, -1), (0, -1, 0), (-1, 0, 0))]


@pytest.mark.parametrize("seed", range(6))
def test_seeded_plates_find_every_hole_once(seed):
    xt, truth = P.random_plate(seed)
    fs = recognise(facegraph.from_transmit(xt))
    holes = of(fs, T.Hole)
    found = sorted(
        (round(h.axis.point[0], 7), round(h.axis.point[1], 7), round(h.diameter, 7)) for h in holes
    )
    want = sorted(
        (round(h["at"][0], 7), round(h["at"][1], 7), round(h["diameter"], 7)) for h in truth["holes"]
    )
    assert found == want
    members = [m for p in of(fs, T.Pattern) for m in p.members]
    assert len(members) == len(set(members))


def test_descriptors_hold_no_node_ids_and_survive_a_move():
    (a, _ta), (b, _tb) = P.pair_origin_moved()
    ha = of(recognise(facegraph.from_transmit(a)), T.Hole)[0]
    hb = of(recognise(facegraph.from_transmit(b)), T.Hole)[0]
    assert ha.descriptor == hb.descriptor  # measured from the part, not the model origin
    (c, _tc), (d, _td) = P.pair_midplane()
    wc = {w.axis: w for w in of(recognise(facegraph.from_transmit(c)), T.Width)}
    wd = {w.axis: w for w in of(recognise(facegraph.from_transmit(d)), T.Width)}
    assert wc["x"].size == pytest.approx(60 * MM) and wd["x"].size == pytest.approx(70 * MM)
    assert wc["y"].descriptor == wd["y"].descriptor


def test_the_ray_index_answers_inside_and_first_hits():
    m = model("four_holes")
    rays = Rays(m)
    assert rays.inside((0.05, 0.03, 0.005))
    assert not rays.inside((0.012, 0.010, 0.005))  # in a hole
    assert not rays.inside((0.05, 0.03, 0.02))  # above the plate
    first = rays.along((0.0, 0.0, 1.0)).first((0.05, 0.03, -0.01))
    assert first is not None and first[0] == pytest.approx(0.01)


def test_recognition_keeps_to_its_time():
    with pytest.raises(SldLimitError) as info:
        recognise(model("patterns"), limits=DrawingLimits(seconds_features=1e-9))
    assert info.value.detail["limit"] == "seconds_features"


def test_thread_candidates_and_hints():
    assert "tapped M6 x 1-6H" in threads.candidates(5.0 * MM)
    assert "clearance for M6 x 1" in threads.candidates(6.6 * MM)
    assert "major diameter of M6 x 1" in threads.candidates(6.0 * MM)
    assert threads.candidates(5.3 * MM) == ()
    assert hints.matches(0.0125, (12.5, 3.0), "mm")
    assert hints.matches(0.0254, (1.0,), "in")
    assert not hints.matches(0.0125, (12.0,), "mm")
    ranked = hints.rank([0.010, 0.0125, 0.020], (12.5,), "mm", lambda v: v)
    assert ranked == [0.0125, 0.010, 0.020]
