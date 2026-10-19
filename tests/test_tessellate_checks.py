"""The mesh self-checks (``solidseas.tessellate.checks``, ``docs/API.md`` 3.15) on meshes
written by hand: closed cubes, a cube with a void either way round, cubes side by side and
one inside another, an open cube and a folded one; and the tessellator's own per-face
check of its (u, v) cover, fed a fold and a flap."""

from array import array

import pytest

from solidseas.tessellate import CHECKS, checks, tessellate_transmit
from solidseas.tessellate._engine import Engine, Options, _Dom
from solidseas.tessellate.surfaces import Plane
from solidseas.tessellate.topology import Clock
from support import within

# A unit cube's corners and its twelve triangles, counter-clockwise seen from outside.
_CORNERS = [(x, y, z) for x in (0.0, 1.0) for y in (0.0, 1.0) for z in (0.0, 1.0)]
_CUBE = [
    (0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1),
    (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3),
]  # fmt: skip


def _cube(scale=1.0, at=(0.0, 0.0, 0.0), *, inward=False, first=0):
    pts = [tuple(at[i] + scale * c[i] for i in range(3)) for c in _CORNERS]
    tris = [(a, c, b) if inward else (a, b, c) for a, b, c in _CUBE]
    return pts, [tuple(first + i for i in t) for t in tris]


def _mesh(*parts):
    pts, tris = [], []
    for p, t in parts:
        tris.extend(i + len(pts) for tri in t for i in tri)
        pts.extend(p)
    return pts, array("I", tris)


def _judge(pts, tris):
    groups = checks.pieces(tris, len(pts))
    found = checks.shells(pts, tris, groups)
    depth = checks.nesting(pts, tris, found)
    return found, depth, checks.inside_out(found, depth)


def test_a_closed_cube_passes_every_check():
    pts, tris = _mesh(_cube())
    assert checks.edge_use(tris) == (0, 0)
    (s,), depth, wrong = _judge(pts, tris)
    assert s.closed and s.volume == pytest.approx(1.0) and depth == [0] and wrong == []


def test_an_inside_out_cube_is_found():
    pts, tris = _mesh(_cube(inward=True))
    (s,) = checks.shells(pts, tris, checks.pieces(tris, len(pts)))
    assert s.closed and s.volume == pytest.approx(-1.0)
    assert checks.inside_out([s], [0]) == [0]
    turned = checks.turn(tris, s.ranges)
    (t,) = checks.shells(pts, turned, checks.pieces(turned, len(pts)))
    assert t.volume == pytest.approx(1.0)


@pytest.mark.parametrize(("void_inward", "wrong"), [(True, []), (False, [1])])
def test_a_void_must_face_into_itself(void_inward, wrong):
    """A cube in a cube: inside one other shell, the void must have a negative volume."""
    pts, tris = _mesh(_cube(3.0), _cube(1.0, (1.0, 1.0, 1.0), inward=void_inward))
    found, depth, got = _judge(pts, tris)
    assert [s.closed for s in found] == [True, True] and depth == [0, 1]
    assert got == wrong


def test_shells_side_by_side_are_each_outward():
    pts, tris = _mesh(_cube(), _cube(1.0, (5.0, 0.0, 0.0)))
    found, depth, wrong = _judge(pts, tris)
    assert depth == [0, 0] and wrong == []


def test_shells_that_touch_are_outside_each_other_and_copies_cannot_be_told():
    """A cube against another's face, the vertex a ray was cast from lying on it: outside,
    by its box, whatever that ray would count. A cube inside a cube's box but in no part
    of it is outside by its rays. Two copies of one cube lie on each other wherever a ray
    could start: their nesting cannot be told, and neither is judged."""
    pts, tris = _mesh(_cube(2.0), _cube(1.0, (-1.0, 0.5, 0.5)))
    _found, depth, wrong = _judge(pts, tris)
    assert depth == [0, 0] and wrong == []
    ell = [(0, 0, 0), (3, 0, 0), (3, 1, 0), (1, 1, 0), (1, 3, 0), (0, 3, 0)]  # an L, extruded
    top = [(x, y, 1.0) for x, y, _z in ell]
    side = [(k, (k + 1) % 6, 6 + (k + 1) % 6) for k in range(6)]
    side += [(k, 6 + (k + 1) % 6, 6 + k) for k in range(6)]
    caps = [(0, 5, 4), (0, 4, 3), (0, 3, 1), (1, 3, 2), (6, 7, 9), (7, 8, 9), (6, 9, 10), (6, 10, 11)]
    pts, tris = _mesh(([*map(tuple, ell), *top], side + caps), _cube(1.0, (2.0, 2.0, 0.0)))
    found, depth, wrong = _judge(pts, tris)
    assert found[0].volume == pytest.approx(5.0) and depth == [0, 0] and wrong == []
    pts, tris = _mesh(_cube(), _cube(inward=True))
    _found, depth, wrong = _judge(pts, tris)
    assert depth == [None, None] and wrong == []


def test_open_and_folded_meshes_fail_the_edge_check():
    pts, tris = _mesh(_cube())
    assert checks.edge_use(tris[:-3]) == (3, 0)  # a triangle short: three edges with no partner
    twice = array("I", [*tris, *tris])  # every triangle twice: closed in count, folded
    assert checks.edge_use(twice) == (0, 36)
    found = checks.shells(pts, tris[:-3], checks.pieces(tris[:-3], len(pts)))
    assert [s.closed for s in found] == [False]
    # an open shell is not judged
    assert checks.inside_out(found, checks.nesting(pts, tris[:-3], found)) == []


def test_flat_points_read_as_tuples():
    flat = array("d", [0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    p = checks.Flat(flat)
    assert p[0] == (0.0, 1.0, 2.0) and p[1] == (3.0, 4.0, 5.0)


def _engine(chord=1e-4):
    return Engine(Options(chord, 0.26, 1000, 10**6, 10**5, 10**4, 30.0), Clock(30.0))


def _plane_face(engine, uv, xyz):
    """A face's domain for ``emit``: points at ``xyz`` (metres) with (u, v) ``uv``."""
    dom = _Dom(1.0, 1.0)
    for (u, v), p in zip(uv, xyz, strict=True):
        dom.add(u, v, engine.pts.add(p))
    return dom


def test_the_tessellator_counts_a_face_whose_triangles_overlap_in_uv():
    """A square covered once, then with a third triangle over half of it again."""
    e = _engine()
    plane = Plane((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))
    s = 0.01
    uv = [(0, 0), (s, 0), (s, s), (0, s)]
    dom = _plane_face(e, uv, [(u, v, 0.0) for u, v in uv])
    e.emit(0, 1, plane, 1, dom, [(0, 1, 2), (0, 2, 3)], 1, 2 * s * s)
    assert e.checks["faces_folded"] == 0
    e.emit(0, 2, plane, 1, dom, [(0, 1, 2), (0, 2, 3), (0, 1, 3)], 1, 2 * s * s)
    assert e.checks["faces_folded"] == 1


def test_the_tessellator_counts_a_flap():
    """Three points in a line in (u, v) but not in space: a triangle with area there and
    none in (u, v), as a fan across a seam's samples made."""
    e = _engine()
    plane = Plane((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))
    s = 0.01
    uv = [(0, 0), (s, 0), (s, s), (0, s), (0, 0.5 * s)]
    xyz = [(0, 0, 0), (s, 0, 0), (s, s, 0), (0, s, 0), (0.5 * s, 0.5 * s, 0.005)]
    dom = _plane_face(e, uv, xyz)
    e.emit(0, 1, plane, 1, dom, [(0, 1, 2), (0, 2, 3), (0, 4, 3)], 1, 2 * s * s)
    assert e.checks["faces_folded"] == 1


def test_triangles_stretched_across_a_loosely_accepted_face_are_found():
    """A face whose (u, v) boundary touched itself was triangulated loosely, and on one
    corpus file triangles ran across it in space over almost no (u, v) area: each covered
    its (u, v) once and lay in the surface's tangent plane, so neither the (u, v) cover
    nor the refinement's distance from the surface saw it, and the face came out half as
    large again with no fold found. Such a face's triangles are now measured against the
    surface's own area over their (u, v) triangle; a faithful face passes."""
    e = _engine()
    plane = Plane((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))
    s = 0.01
    uv = [(0, 0), (s, 0), (s, s), (0, s), (0.5 * s, s + 1e-6)]
    xyz = [(u, v, 0.0) for u, v in uv[:4]] + [(0.5 * s, 3 * s, 0.0)]
    dom = _plane_face(e, uv, xyz)
    assert not e._stretched(plane, dom, [(0, 1, 2), (0, 2, 3)])
    assert e._stretched(plane, dom, [(0, 1, 2), (0, 2, 3), (3, 2, 4)])


def test_a_face_whose_uv_collapses_is_not_judged():
    """A face whose (u, v) polygon is a sliver beside its area in space (a surface whose
    (u, v) collapses there) has triangles of little (u, v) area whether they fold or not:
    the fold check leaves it alone."""
    e = _engine()
    plane = Plane((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))
    s = 0.01
    uv = [(0, 0), (s, 0), (s, 1e-6), (0, 1e-6)]
    xyz = [(0, 0, 0), (s, 0, 0), (s, s, 0), (0, s, 0)]
    dom = _plane_face(e, uv, xyz)
    e.emit(0, 1, plane, 1, dom, [(0, 1, 2), (0, 2, 3), (0, 1, 3)], 1, 2 * s * 1e-6)
    assert e.checks["faces_folded"] == 0


def test_boundary_points_on_one_uv_point_are_spread_towards_the_next():
    """Boundary points whose nearest point of the surface is one point of its edge (an edge
    standing off the surface there) all came out at one (u, v) point, which the
    triangulation cannot take: a run of them is spread evenly towards the next point, the
    shorter way round a periodic direction; a pole's points are left to the pole lines."""
    from solidseas.tessellate._engine import _spread

    class Open:
        pu = pv = None

    class Round:
        pu, pv = 2 * 3.141592653589793, None

    loop = [(0.0, 0.0, 1), (1.0, 0.0, 2), (1.0, 0.0, 3), (1.0, 0.0, 4), (1.0, 1.0, 5), (0.0, 1.0, 6)]
    got = _spread(Open, loop)
    assert [p[2] for p in got] == [1, 2, 3, 4, 5, 6]
    want = [(1.0, 0.0), (1.0, 1 / 3), (1.0, 2 / 3), (1.0, 1.0)]
    assert [(u, v) for u, v, _p in got[1:5]] == pytest.approx(want)
    seam = [(3.0, 0.0, 1), (3.0, 0.0, 2), (-3.0, 0.0, 3), (0.0, 1.0, 4)]
    u1 = _spread(Round, seam)[1][0]
    assert 3.0 < u1 < 3.2  # across the seam, not back through nought
    pole = [(None, 1.5, 1), (None, 1.5, 2), (0.0, 0.0, 3), (1.0, 0.0, 4)]
    assert _spread(Open, pole) == pole


def test_a_point_past_the_surface_is_carried_past_its_edge_by_one_short_step():
    """A boundary point beyond the end of a surface's parameter range is carried past
    its edge by one Gauss-Newton step, outward only; a step longer than the range (the
    surface barely moving at its edge) is not taken, and the point stays on the edge."""
    from solidseas.tessellate._engine import _beyond

    class Strip:
        """(u, v) to (k u, v, 0) on [0, 1] by [0, 1]."""

        urange = vrange = (0.0, 1.0)

        def __init__(self, k):
            self.k = k

        def d1(self, u, v):
            return (self.k * u, v, 0.0), (self.k, 0.0, 0.0), (0.0, 1.0, 0.0)

    assert _beyond(Strip(1.0), (1.2, 0.5, 0.0), 1.0, 0.5) == pytest.approx((1.2, 0.5))
    assert _beyond(Strip(1.0), (-0.3, 1.1, 0.0), 0.0, 1.0) == pytest.approx((-0.3, 1.1))
    assert _beyond(Strip(1.0), (0.5, 0.5, 0.0), 0.5, 0.5) == (0.5, 0.5)  # inside: kept
    assert _beyond(Strip(1.0), (0.9, 0.5, 0.0), 1.0, 0.5) == (1.0, 0.5)  # inward: kept
    assert _beyond(Strip(1e-9), (1e-9 + 0.1, 0.5, 0.0), 1.0, 0.5) == (1.0, 0.5)


def test_a_good_solid_reports_every_check_as_nought():
    import xt_bodies

    t = tessellate_transmit(xt_bodies.cylinder(0.005, 0.02))
    assert t.checks == dict.fromkeys(CHECKS, 0) and t.warnings == ()
    assert len(t.face_shells) == len(t.face_ids) and len(set(t.face_shells)) == 1


def test_nesting_reports_its_work_and_stops_when_the_time_is_up():
    from solidseas.tessellate.topology import TimeUp

    pts, tris = _mesh(_cube(4.0), _cube(1.0, (1.0, 1.0, 1.0)))
    found = checks.shells(pts, tris, checks.pieces(tris, len(pts)))
    work = []
    assert checks.nesting(pts, tris, found, tick=work.append) == [0, 1]
    assert work and sum(work) > 0

    def out_of_time(_n):
        raise TimeUp

    with pytest.raises(TimeUp):
        checks.nesting(pts, tris, found, tick=out_of_time)


def test_an_export_past_the_shells_judged_says_so():
    """More closed shells than nesting works out (MAX_SHELLS): none is judged, and the
    export's object says its shells' facing was not checked rather than nothing."""
    from solidseas import export

    cubes = [_cube(0.5, (2.0 * k, 0.0, 0.0)) for k in range(checks.MAX_SHELLS + 1)]
    pts, tris = _mesh(*cubes)
    flat = array("f", [c for p in pts for c in p])
    obj = export._object("many", None, None, "brep", flat, tris, 1e-4, [])
    (w,) = [w for w in obj.warnings if w.code == "shells_not_judged"]
    assert f"{checks.MAX_SHELLS + 1:,} closed shells" in w.message
    pts, tris = _mesh(*cubes[:2])
    flat = array("f", [c for p in pts for c in p])
    obj = export._object("two", None, None, "brep", flat, tris, 1e-4, [])
    assert not any(w.code == "shells_not_judged" for w in obj.warnings)


def test_spikes_round_a_loops_end_are_trimmed_in_one_pass():
    """Fin pairs meeting round the loop's end go from both ends at once: a loop of
    400,001 fins, 200,000 pairs round its end, keeps its middle fin in moments (the
    pop(0) it replaced took seconds)."""
    import time

    from solidseas.tessellate._engine import _without_spikes

    class Topo:
        def ref(self, fin, _field):
            return fin[0]

        def sense(self, fin):
            return fin[1]

    class Edge:
        def __init__(self, index):
            self.index = index

    n = 200_000
    edges = [Edge(k) for k in range(n + 1)]
    there = [(edges[k], "+") for k in range(n)]
    back = [(edges[k], "-") for k in reversed(range(n))]
    fins = [*there, (edges[n], "+"), *back]
    t0 = time.perf_counter()
    kept = _without_spikes(Topo(), fins)
    assert kept == [(edges[n], "+")]
    assert time.perf_counter() - t0 < within(1.0)
