"""Full sections and detail views (docs/DRAWINGS.md 8.9, 8.10, 19.2)."""

import math

import pytest

from drawing_support import model
from solidseas.drawing import sections as SE
from solidseas.drawing import types as T
from solidseas.drawing import views as V
from solidseas.drawing.display import Arc, Segment

MM = 1e-3


def spec(direction, up, point, letter="A"):
    return T.ViewSpec(
        "v-5", "section", direction, up, f"section {letter}", letter=letter, cut=(point, direction)
    )


def test_the_cut_closes_every_loop():
    c = SE.cut(model("hole_kinds"), (0.0, 0.02, 0.0), (0.0, -1.0, 0.0))
    assert c.closed and len(c.loops) == 6  # five holes split the plate's section into six
    assert all(len(loop) >= 4 for loop in c.loops)


def test_a_section_square_to_holes_draws_exact_circles():
    g, why = SE.section(model("four_holes"), spec((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (0.0, 0.0, 0.005)))
    assert why is None
    cut = [r for r in g.runs if r.source.kind == "section"]
    arcs = [r.primitive for r in cut if isinstance(r.primitive, Arc)]
    segs = [r.primitive for r in cut if isinstance(r.primitive, Segment)]
    assert len(arcs) == 4 and all(a.radius == pytest.approx(3.3 * MM) and a.sweep() == 360.0 for a in arcs)
    assert len(segs) == 4  # the outline, one segment a side
    assert len(g.hatch) == 5


def test_hatch_lies_inside_the_material():
    g, _why = SE.section(model("four_holes"), spec((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (0.0, 0.0, 0.005)))
    hatch = [r.primitive for r in g.runs if r.source.kind == "hatch"]
    assert hatch and all(r.style == "thin" for r in g.runs if r.source.kind == "hatch")
    centres = [(12, 10), (37, 48), (71, 15), (88, 44)]
    for h in hatch:
        mid = ((h.p0[0] + h.p1[0]) / 2, (h.p0[1] + h.p1[1]) / 2)
        assert 0 <= mid[0] <= 0.1 and 0 <= mid[1] <= 0.06
        assert all(math.dist(mid, (x * MM, y * MM)) >= 3.3 * MM - 1e-6 for x, y in centres)
        angle = math.degrees(math.atan2(h.p1[1] - h.p0[1], h.p1[0] - h.p0[0])) % 180
        assert angle == pytest.approx(45.0)


def test_a_section_through_hole_axes_shows_their_shape():
    m = model("hole_kinds")
    g, why = SE.section(m, spec((0.0, -1.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.02, 0.0)))
    assert why is None
    cut = [r.primitive for r in g.runs if r.source.kind == "section"]
    assert cut and all(
        isinstance(p, Segment) for p in cut
    )  # planes, bores and countersinks cut on their axes
    # the counterbore at x = 40: its 11 mm bore wall and its 6.6 mm hole wall both appear
    xs = {round(p.p0[0] / MM, 3) for p in cut if abs(p.p0[0] - p.p1[0]) < 1e-9}
    assert {34.5, 36.7, 43.3, 45.5} <= {round(abs(x), 3) for x in xs}


def test_nothing_behind_the_plane_is_hidden_or_in_front():
    g, _why = SE.section(model("four_holes"), spec((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (0.0, 0.0, 0.005)))
    assert {r.style for r in g.runs} <= {"visible", "thin"}


def test_a_plane_that_misses_the_part_says_so():
    g, why = SE.section(model("four_holes"), spec((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (0.0, 0.0, 0.5)))
    assert why == "the cutting plane misses the part" and g.hatch == ()


def test_hatch_turns_away_from_an_outline_at_45_degrees():
    square = [[(0.0, 0.0), (1.0, 1.0), (0.0, 2.0), (-1.0, 1.0)]]
    lines = SE.hatch(square, 0.1)
    assert lines
    for a, b in lines:
        angle = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180
        assert min(abs(angle - 45), abs(angle - 135)) > 2.0


def test_a_section_replacing_a_view():
    d, up = V.view_frames()["front"]
    parent = T.ViewSpec("v-2", "projected", d, up, "front", parent="v-1")
    s = SE.section_through((0.01, 0.02, 0.0), parent, "v-7", "B")
    assert s.kind == "section" and s.replaces == "v-2" and s.letter == "B" and s.cut[1] == pytest.approx(d)


def test_a_detail_clips_its_parent_to_the_circle():
    d, up = V.view_frames()["front"]
    parent = V.project(model("four_holes"), T.ViewSpec("v-1", "base", d, up, "front", hidden=False))
    detail_spec = T.ViewSpec("v-6", "detail", d, up, "detail C", parent="v-1", letter="C")
    g = SE.detail(parent, detail_spec, (0.012, 0.010), 0.015)
    arcs = [r.primitive for r in g.runs if isinstance(r.primitive, Arc)]
    segs = [r.primitive for r in g.runs if isinstance(r.primitive, Segment)]
    assert len(arcs) == 1 and arcs[0].radius == pytest.approx(3.3 * MM)
    assert len(segs) == 2  # the left and bottom edges, clipped
    for s in segs:
        for p in (s.p0, s.p1):
            assert math.dist(p, (0.012, 0.010)) <= 0.015 + 1e-12
    assert len(g.centre_marks) == 1 and all(r.source.view == "v-6" for r in g.runs)
    # an arc crossing the circle keeps only its inside
    partial = SE._clip_arc(Arc((0.0, 0.0), 1.0, 0.0, 360.0), (1.0, 0.0), 0.5)
    inside = sum(b - a for a, b in partial)
    assert inside == pytest.approx(2 * math.degrees(math.acos(0.875)))  # the arc's part within 0.5 of (1, 0)
