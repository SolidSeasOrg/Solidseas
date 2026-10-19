"""Views: frames, exact entities, tangent edges, centres, witnesses, limits and the
default view set (docs/DRAWINGS.md 8, 19.2)."""

import math

import pytest

from drawing_support import fixture, model
from solidseas import open_document
from solidseas.drawing import facegraph
from solidseas.drawing import types as T
from solidseas.drawing import views as V
from solidseas.drawing.display import Arc, EllipseArc, Segment
from solidseas.drawing.limits import DrawingLimits
from solidseas.drawing.settings import DrawingSettings
from solidseas.drawing.views.cleanup import Piece, cleanup, rank
from solidseas.errors import SldLimitError

MM = 1e-3


def view(m, name, **kw):
    d, up = V.view_frames()[name]
    kind = "isometric" if name == "isometric" else "base"
    kw.setdefault("hidden", False)
    return V.project(m, T.ViewSpec("v-9", kind, d, up, name, **kw))


def segments(g, style="visible"):
    out = []
    for r in g.runs:
        if r.style == style and isinstance(r.primitive, Segment):
            (a, b) = sorted([r.primitive.p0, r.primitive.p1])
            out.append(tuple(round(c / MM, 3) for c in a + b))
    return sorted(out)


@pytest.fixture(scope="module")
def o11():
    with open_document(fixture("o11_curved.SLDPRT")) as doc:
        return facegraph.from_document(doc)


def test_the_frames_are_third_angle_and_turn():
    frames = V.view_frames()
    for name in ("front", "top", "right", "isometric"):
        d, up = frames[name]
        sd, sup = T.STANDARD_VIEWS[name]
        norm = math.sqrt(sum(c * c for c in sd))
        assert d == pytest.approx(tuple(c / norm for c in sd))
        un = math.sqrt(sum(c * c for c in sup))
        assert up == pytest.approx(tuple(c / un for c in sup))
    turned = V.view_frames("+z", 1)
    assert turned["front"][1] == pytest.approx((-1.0, 0.0, 0.0))
    assert V.view_frames("+y")["front"] == ((0.0, 1.0, 0.0), (0.0, 0.0, -1.0))


def test_a_plate_with_holes_seen_from_the_front():
    g = view(model("four_holes"), "front")
    assert segments(g) == [
        (0.0, 0.0, 0.0, 60.0),
        (0.0, 0.0, 100.0, 0.0),
        (0.0, 60.0, 100.0, 60.0),
        (100.0, 0.0, 100.0, 60.0),
    ]
    arcs = [r.primitive for r in g.runs if isinstance(r.primitive, Arc)]
    assert len(arcs) == 4  # each hole once: its far rim lies under its near rim
    assert all(a.radius == pytest.approx(3.3 * MM) and a.sweep() == 360.0 for a in arcs)
    assert sorted((round(a.centre[0] / MM), round(a.centre[1] / MM)) for a in arcs) == [
        (12, 10),
        (37, 48),
        (71, 15),
        (88, 44),
    ]
    assert len(g.centre_marks) == 4 and all(r == pytest.approx(3.3 * MM) for _c, r in g.centre_marks)
    assert not [r for r in g.runs if r.style == "hidden"]


def test_hidden_lines_only_when_asked_and_never_under_visible_ones():
    m = model("four_holes")
    assert not [r for r in view(m, "top").runs if r.style == "hidden"]
    g = view(m, "top", hidden=True)
    hidden = segments(g, "hidden")
    # each hole's two silhouettes, through the thickness; its rims lie under the outline
    assert len(hidden) == 8
    xs = sorted(h[0] for h in hidden)
    assert xs == pytest.approx([8.7, 15.3, 33.7, 40.3, 67.7, 74.3, 84.7, 91.3])
    assert all(abs(h[3] - h[1]) == pytest.approx(10.0) for h in hidden)


def test_silhouettes_on_a_seam_are_found():
    # the synthetic holes' cylinders start their angle on the seam the right view's
    # generators fall on; each hole still shows both silhouettes
    g = view(model("four_holes"), "right", hidden=True)
    ys = sorted(round(r.primitive.p0[1] / MM, 3) for r in g.runs if r.source.kind == "silhouette")
    assert ys == [6.7, 11.7, 13.3, 18.3, 40.7, 44.7, 47.3, 51.3]


def test_entities_are_exact():
    m = model("four_holes")
    iso = view(m, "isometric")
    kinds = {type(r.primitive).__name__ for r in iso.runs}
    assert "EllipseArc" in kinds and "Polyline" not in kinds
    for r in iso.runs:
        if isinstance(r.primitive, EllipseArc):
            assert r.primitive.ratio == pytest.approx(1 / math.sqrt(3))
            assert math.hypot(*r.primitive.major) == pytest.approx(3.3 * MM)
    assert all(r.source.view == "v-9" and r.source.signature for r in iso.runs)


def test_the_isometric_shows_visible_lines_only_without_centres(o11):
    g = view(o11, "isometric", hidden=True)
    assert {r.style for r in g.runs} <= {"visible", "thin"}
    assert "thin" in {r.style for r in g.runs}  # its tangent edges are thin
    assert g.centre_marks == () and g.centre_lines == ()


def test_tangent_edges_are_outline_where_their_normal_is_square_to_the_view(o11):
    g = view(o11, "right")
    visible = sum(
        math.dist(r.primitive.p0, r.primitive.p1)
        for r in g.runs
        if r.style == "visible" and isinstance(r.primitive, Segment)
    )
    # without the outline rule o11's right view lost 10 mm (12 %) of its visible outline
    assert visible == pytest.approx(2 * (30 + 10) * MM, rel=0.02)
    thin = view(o11, "front", tangent="thin")
    assert "thin" in {r.style for r in thin.runs}
    phantom = view(o11, "front", tangent="phantom")
    assert "phantom" in {r.style for r in phantom.runs}


def test_centre_lines_and_axes(o11):
    front = view(o11, "front")
    assert len(front.centre_marks) == 1 and front.centre_marks[0][1] == pytest.approx(5 * MM)
    side = view(o11, "top")
    assert len(side.centre_lines) >= 1
    (a, b) = side.centre_lines[0]
    assert math.dist(a, b) > 0
    assert len(front.axes_end_on) >= 1 and len(side.axes_side_on) >= 1


def test_only_an_axis_its_faces_go_round_gets_a_centre_line(o11):
    # seen side on, the hole's axis is a centre line; the rounded corners' axes are not
    # (their faces cover a quarter turn, and a broad curve's axis may lie far off the part)
    side = view(o11, "top")
    assert len(side.centre_lines) == 1
    (a, b) = side.centre_lines[0]
    assert a[0] == pytest.approx(b[0])  # along the hole's axis, square to the plate


def test_witnesses_answer_the_planner(o11):
    g = view(model("four_holes"), "front")
    xs = sorted(round(w.position / MM, 6) for w in g.witnesses if w.axis == "x")
    ys = sorted(round(w.position / MM, 6) for w in g.witnesses if w.axis == "y")
    assert xs == [0.0, 100.0] and ys == [0.0, 60.0]
    assert g.witness_at("x", 100 * MM, 1e-6).high == pytest.approx(60 * MM)
    assert g.witness_at("x", 50 * MM, 1e-6) is None


def test_faces_in_true_shape_and_edge_visibility():
    m = model("four_holes")
    g = view(m, "front")
    (top,) = g.faces_true_shape
    assert m.faces[top].surface.normal == pytest.approx((0.0, 0.0, 1.0))
    assert all(isinstance(v, bool) for _s, v in g.edge_visible) and any(v for _s, v in g.edge_visible)


def test_the_default_set_and_options():
    m = model("boss")
    s = DrawingSettings()
    out = V.make_views(m, None, T.DrawingOptions(), s)
    assert [spec.name for spec, _g in out] == ["front", "top", "right", "isometric"]
    assert [spec.id for spec, _g in out] == ["v-1", "v-2", "v-3", "v-4"]
    assert not any(spec.hidden for spec, _g in out)  # hidden lines off by default (8.4)
    two = V.make_views(m, None, T.DrawingOptions(views=("front", "right"), hidden=True), s)
    assert [spec.name for spec, _g in two] == ["front", "right"] and all(spec.hidden for spec, _g in two)
    assert V.default_specs(T.DrawingOptions(front="+y"), s)[0].direction == (0.0, 1.0, 0.0)


def test_a_boss_seen_from_the_side():
    g = view(model("boss"), "top")
    # the boss's two silhouettes stand on the block, 15 above it
    sil = [r.primitive for r in g.runs if r.source.kind == "silhouette" and r.style == "visible"]
    xs = sorted(round(p.p0[0] / MM, 3) for p in sil)
    assert xs == [15.0, 45.0]
    assert all(abs(p.p1[1] - p.p0[1]) == pytest.approx(15 * MM, abs=1e-7) for p in sil)


def test_drawing_twice_gives_the_same_views():
    m = model("step_slot")
    a = V.make_views(m, None, T.DrawingOptions(hidden=True), DrawingSettings())
    b = V.make_views(m, None, T.DrawingOptions(hidden=True), DrawingSettings())
    assert a == b


def test_pieces_equal_but_for_their_last_bit_keep_their_order():
    # A cone's two silhouette lines in hole-kinds' isometric are this long, and their
    # lengths differ in the last bit between Windows' and Linux's sine and cosine.
    length = 0.020719711340109324
    longer = math.nextafter(length, math.inf)
    a = Piece([(0.0, 0.0), (length, 0.0)], True, "silhouette", "a")
    b = Piece([(0.0, 0.01), (longer, 0.01)], True, "silhouette", "b")
    assert rank(a) == rank(b)
    assert [p.payload for p in cleanup([a, b], 0.1)] == ["a", "b"]
    assert [p.payload for p in cleanup([b, a], 0.1)] == ["b", "a"]
    # a real difference, a nanometre or more, still puts the longer piece first
    c = Piece([(0.0, 0.02), (length + 2e-9, 0.02)], True, "silhouette", "c")
    assert [p.payload for p in cleanup([a, c], 0.1)] == ["c", "a"]


def test_the_bounds_hold():
    m = model("patterns")
    with pytest.raises(SldLimitError) as info:
        view_limits = DrawingLimits(visibility_queries=50)
        d, up = V.view_frames()["front"]
        V.project(m, T.ViewSpec("v-1", "base", d, up, "front"), limits=view_limits)
    assert info.value.detail["limit"] == "visibility_queries"
    with pytest.raises(SldLimitError):
        V.make_views(m, None, T.DrawingOptions(), DrawingSettings(), limits=DrawingLimits(views=2))
    with pytest.raises(SldLimitError):
        V.make_views(m, None, T.DrawingOptions(), DrawingSettings(), limits=DrawingLimits(seconds_views=1e-9))


def test_fixture_benchmarks_draw():
    for name in ("o02_boxA.SLDPRT", "o07_boxB_h31.SLDPRT", "o12_multibody.SLDPRT"):
        with open_document(fixture(name)) as doc:
            m = facegraph.from_document(doc)
        g = view(m, "front")
        assert len(segments(g)) >= 4 and not [r for r in g.runs if r.style == "hidden"]
