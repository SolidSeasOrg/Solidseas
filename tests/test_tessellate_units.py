"""The pieces of ``solidseas.tessellate`` on their own: the 2D triangulator, B-splines,
surface inversion, and whole synthetic solids whose volume and area are known.

The triangulator must use every boundary point (each is shared with the next
face), cover the polygon's area exactly, emit only counter-clockwise triangles
and finish within its step budget, on squares, L shapes with collinear runs,
holes (touching the outer ring and each other), combs, spirals and a ring of
10,000 points. The synthetic solids (``xt_bodies``) cover a whole sphere and a
whole torus (faces with no loop), a cylinder (two loops winding opposite ways
round it), a hemisphere and a cone (a loop with a pole beyond it) and a
cylinder whose side is a rational B-spline: each must come out closed, with
volume and area within 0.5 percent at a chord of 1e-5 m.
"""

import math
import random

import pytest

import xt_bodies
from solidseas.formats.solidworks.parasolid import validate
from solidseas.tessellate import nurbs, surfaces, tessellate_transmit
from solidseas.tessellate import triangulate as tri
from solidseas.tessellate._engine import Options
from solidseas.tessellate.domain import Builder, unwrap, winding
from solidseas.tessellate.topology import Clock, FaceFailed, TimeUp


def _polygon_case(rings):
    """Indices for the points of ``rings``; a point met twice (where a hole touches the
    outer ring or another hole) is one point id, as a shared vertex is."""
    xy, out_rings, pid, ids = [], [], [], {}
    for r in rings:
        idx = []
        for p in r:
            idx.append(len(xy))
            xy.append(p)
            pid.append(ids.setdefault(p, len(ids)))
        out_rings.append(idx)
    return xy, out_rings, pid


def _check(rings, *, cdt: bool = False):
    xy, idx, pid = _polygon_case(rings)
    if cdt:
        tris = tri.cdt(xy, idx, pid, Clock(30))
        assert tris is not None
    else:
        tris, complete = tri.earcut(xy, idx[0], idx[1:], pid, Clock(30))
        assert complete
    assert tri.check(xy, idx, tris, 1e-12)
    used = {pid[i] for t in tris for i in t}
    assert used == {pid[i] for r in idx for i in r}, "a boundary point is not used"
    assert all(tri.tri_area2(xy, *t) > 0 for t in tris)
    return tris


SQUARE = [(0, 0), (1, 0), (1, 1), (0, 1)]
L_SHAPE = [(0, 0), (1, 0), (2, 0), (2, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2), (0, 1)]  # collinear runs


def _comb(teeth: int = 12):
    pts = [(0.0, 0.0), (float(2 * teeth), 0.0)]
    for k in range(teeth, 0, -1):
        x = 2.0 * k
        pts += [(x, 5.0), (x - 1.0, 5.0), (x - 1.0, 1.0), (x - 2.0, 1.0)]
    return pts[:-1] + [(0.0, 5.0)]


def _spiral(turns: float = 3.0, n: int = 400):
    out, back = [], []
    for k in range(n + 1):
        a = turns * 2 * math.pi * k / n
        r = 1.0 + a
        out.append((r * math.cos(a), r * math.sin(a)))
        back.append(((r + 0.5) * math.cos(a), (r + 0.5) * math.sin(a)))
    return out + back[::-1]


@pytest.mark.parametrize("cdt", [False, True])
@pytest.mark.parametrize(
    "rings",
    [
        [SQUARE],
        [L_SHAPE],
        [[(0, 0), (10, 0), (10, 10), (0, 10)], [(2, 2), (2, 4), (4, 4), (4, 2)]],
        [
            [(0, 0), (10, 0), (10, 10), (0, 10)],
            [(1, 1), (1, 3), (3, 3), (3, 1)],
            [(5, 5), (5, 8), (8, 8), (8, 5)],
            [(6, 1), (6, 2), (9, 2), (9, 1)],
        ],
        [
            [(0, 0), (10, 0), (10, 10), (0, 10), (0, 5)],
            [(0, 5), (3, 7), (3, 3)],
        ],  # a hole touching the outer ring
        [
            [(0, 0), (10, 0), (10, 10), (0, 10)],
            [(2, 2), (2, 5), (5, 5)],
            [(5, 5), (8, 5), (8, 2)],
        ],  # touching holes
        [_comb()],
        [_spiral()],
    ],
    ids=["square", "L", "hole", "holes", "hole_on_outer", "touching_holes", "comb", "spiral"],
)
def test_the_triangulator_covers_every_polygon_with_every_point(rings, cdt):
    _check(rings, cdt=cdt)


def test_a_ring_of_ten_thousand_points_is_done_within_its_budget():
    n = 10_000
    ring = [
        (
            math.cos(2 * math.pi * k / n) * (1 + 0.3 * math.sin(17 * 2 * math.pi * k / n)),
            math.sin(2 * math.pi * k / n),
        )
        for k in range(n)
    ]
    tris = _check([ring])
    assert len(tris) == n - 2
    xy, idx, pid = _polygon_case([ring])
    _t, complete = tri.earcut(xy, idx[0], [], pid, Clock(30), max_steps=100)
    assert not complete  # the step budget ends the clipping, it does not loop


def test_points_at_one_place_are_one_point_only_when_their_ids_match():
    xy = [(0, 0), (1, 0), (1, 0), (2, 0), (2, 1), (0, 1)]
    # the same point twice in a row is one point
    same = [0, 1, 1, 3, 4, 5]
    tris, ok = tri.earcut(xy, list(range(6)), [], same, Clock(5))
    assert ok and len({i for t in tris for i in t} & {1, 2}) == 1 and tri.check(xy, [list(range(6))], tris)
    # two points at one place are not merged: the constrained triangulation refuses them
    assert tri.cdt(xy, [list(range(6))], [0, 1, 2, 3, 4, 5], Clock(5)) is None
    # crossing rings defeat the constrained triangulation, which says so
    bow = [(0, 0), (2, 2), (2, 0), (0, 2)]
    assert tri.cdt(bow, [[0, 1, 2, 3]], [0, 1, 2, 3], Clock(5)) is None


def test_the_scans_a_crafted_face_can_make_long_stop_at_the_time_limit():
    """The fallbacks that scan every triangle, edge or ring point (a failed walk, a
    constraint recovery round, an ear test) tick the clock by the work they do, so a
    face of many collinear or repeated points ends at its time limit."""
    n = 600
    xy = [(float(k), 0.0) for k in range(n)] + [(float(n), 1.0), (0.0, 1.0)]
    fan = [(0, k, k + 1) for k in range(1, n)] + [(0, n, n + 1)]
    mesh = tri.TriMesh(xy, fan, set(), Clock(-1.0))
    with pytest.raises(TimeUp):
        mesh.locate(-5.0, -5.0)  # outside: the scan visits every triangle
    with pytest.raises(TimeUp):
        tri._recover(mesh, 1, n + 1)  # one round looks at every edge
    ring = [(math.cos(2 * math.pi * k / n), math.sin(2 * math.pi * k / n)) for k in range(n)]
    pts, idx, pid = _polygon_case([ring])
    ctx = tri._Ctx(pid, Clock(-1.0), 10**9)
    head = tri._linked(pts, idx[0], True, pid)
    with pytest.raises(TimeUp):
        tri._is_ear(ctx, head)  # a convex ear looks at every other ring point


def test_a_skipped_boundary_point_is_put_back_into_the_triangles():
    xy = [(0, 0), (1, 0), (2, 0), (1, 1)]
    tris = [(0, 2, 3)]  # (1, 0) lies on the chord 0-2 and is used by no triangle
    out, filled, left = tri.fill_gaps(xy, [[0, 1, 2, 3]], tris)
    assert filled == 1 and left == 0 and sorted(out) == [(0, 1, 3), (1, 2, 3)]
    assert tri.check(xy, [[0, 1, 2, 3]], out)


def test_a_mesh_keeps_its_fixed_edges_through_delaunay_flips():
    xy = [(0, 0), (2, -0.2), (4, 0), (2, 3)]  # the long diagonal 0-2 is not Delaunay
    mesh = tri.TriMesh(xy, [(0, 1, 2), (0, 2, 3)], {(0, 2)}, Clock(5))
    mesh.make_delaunay()
    assert (0, 2) in mesh.e or (2, 0) in mesh.e
    free = tri.TriMesh(xy, [(0, 1, 2), (0, 2, 3)], set(), Clock(5))
    free.make_delaunay()
    assert sorted(map(sorted, free.triangles())) == [[0, 1, 3], [1, 2, 3]]
    xy.append((2.5, 1.0))
    k, edge = free.walk(2.5, 1.0)
    assert edge is None
    free.insert_in(4, k)
    assert len(free.triangles()) == 4 and tri.check(xy, [[0, 1, 2, 3]], free.triangles())


# --------------------------------------------------------------------------- B-splines
def test_knot_vectors_are_checked_and_their_padding_ignored():
    assert nurbs.knot_vector([0.0, 1.0, 0.0], [3, 3, 0], 3, 2) == [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    for knots, mults, n, p in (
        ([0.0, 1.0], [3, 2], 3, 2),  # wrong length
        ([1.0, 0.0], [3, 3], 3, 2),  # decreasing
        ([0.0, 0.0], [3, 3], 3, 2),  # no span of positive length
        ([0.0, float("nan")], [3, 3], 3, 2),
        ([0.0, 1.0], [3, 3], 3, 100),  # degree out of range
        ([0.0, 1.0], [3, 3], 10**7, 2),  # far too many control points
        ([0.0, 1.0], [-1, 7], 3, 2),
    ):
        with pytest.raises(FaceFailed):
            nurbs.knot_vector(knots, mults, n, p)
    with pytest.raises(FaceFailed):
        nurbs.control_points([1.0, 2.0, 3.0, -1.0], 1, 4, True)  # a weight that is not positive
    with pytest.raises(FaceFailed):
        nurbs.control_points([1.0, float("inf"), 3.0], 1, 3, False)


def test_basis_functions_sum_to_one_and_their_derivatives_match_differences():
    U = nurbs.knot_vector([0.0, 0.3, 0.5, 1.0], [4, 1, 2, 4], 7, 3)
    for u in (0.0, 0.1, 0.3, 0.42, 0.5, 0.77, 1.0):
        span = nurbs.find_span(U, 7, 3, u)
        N, dN = nurbs.basis_d1(U, span, u, 3)
        assert sum(N) == pytest.approx(1.0, abs=1e-12) and sum(dN) == pytest.approx(0.0, abs=1e-9)
        assert N == pytest.approx(nurbs.basis(U, span, u, 3), abs=1e-15)
    rng = random.Random(7)
    cps = [(rng.random(), rng.random(), rng.random()) for _ in range(7)]
    c = nurbs.BSplineCurve(3, cps, U, False, False)
    for t in (0.05, 0.4, 0.6, 0.95):
        h = 1e-6
        _p, d = c.d1(t)
        fd = [(a - b) / (2 * h) for a, b in zip(c.point(t + h), c.point(t - h), strict=True)]
        assert d == pytest.approx(fd, abs=1e-5)


def test_the_rational_cylinder_lies_on_its_circle_and_points_find_their_parameters():
    xt = xt_bodies.nurbs_cylinder(0.005, 0.02)
    from solidseas.tessellate.surfaces import Geometry
    from solidseas.tessellate.topology import Topology

    topo = Topology(xt)
    side = next(n for n in xt.nodes if n.type == xt_bodies.B_SURFACE)
    S = Geometry(topo, 1e-5).surface(side)
    assert S.pu == pytest.approx(4.0) and S.pv is None and S.poles == ()
    rng = random.Random(3)
    for _ in range(50):
        u, v = rng.uniform(0, 4), rng.uniform(0, 1)
        p = S.point(u, v)
        assert math.hypot(p[0], p[1]) == pytest.approx(0.005, abs=1e-12) and p[2] == pytest.approx(0.02 * v)
        uu, vv, d = S.closest(p, None, 1e-9, 1e-7)
        assert d < 1e-9 and math.dist(S.point(uu, vv), p) < 1e-9
        n = S.normal(u, v)  # the natural normal points out
        assert n[0] * p[0] + n[1] * p[1] > 0


@pytest.mark.parametrize(
    "surface",
    [
        surfaces.Plane((0.1, 0, 0), (0, 0, 1), (1, 1, 0)),
        surfaces.Cylinder((0, 0, 0), (0, 1, 0), 0.02, (1, 0, 0)),
        surfaces.Cone((0, 0, 0), (0, 0, 1), 0.01, math.sin(0.3), math.cos(0.3), (1, 0, 0)),
        surfaces.Sphere((0, 0, 0.1), 0.03, (0, 0, 1), (0, 1, 0)),
        surfaces.Torus((0, 0, 0), (0, 0, 1), 0.05, 0.01, (1, 0, 0)),
    ],
    ids=["plane", "cylinder", "cone", "sphere", "torus"],
)
def test_analytic_surfaces_invert_their_own_points(surface):
    rng = random.Random(11)
    for _ in range(100):
        u, v = rng.uniform(-3, 3), rng.uniform(-0.04, 0.04) if surface.name != "TORUS" else rng.uniform(-3, 3)
        if surface.name == "SPHERE":
            v = rng.uniform(-1.4, 1.4)
        p = surface.point(u, v)
        uu, vv, d = surface.closest(p, None, 1e-9, 1e-9)
        assert d < 1e-12
        assert math.dist(surface.point(uu, vv), p) < 1e-12
        # the derivatives agree with differences
        _q, su, sv = surface.d1(u, v)
        h = 1e-7
        fd = [
            (a - b) / (2 * h) for a, b in zip(surface.point(u + h, v), surface.point(u - h, v), strict=True)
        ]
        assert su == pytest.approx(fd, abs=1e-6)


def test_an_offset_surface_lies_along_its_base_normal_times_the_base_sense():
    """VERIFIED on the corpus (``docs/FORMAT.md`` 10.8): an OFFSET_SURF over a base of
    sense '-' lies on the other side of it."""
    base = surfaces.Sphere((0, 0, 0), 0.01, (0, 0, 1), (1, 0, 0))
    out, inward = surfaces.Offset(base, 0.002, 1), surfaces.Offset(base, 0.002, -1)
    for surface, radius in ((out, 0.012), (inward, 0.008)):
        p = surface.point(0.3, 0.2)
        assert math.hypot(*p) == pytest.approx(radius)
        u, v, d = surface.closest(p, None, 1e-9, 1e-9)
        assert d < 1e-9 and math.dist(surface.point(u, v), p) < 1e-9


def _hairpin_surface(chord: float = 1e-4):
    from solidseas.tessellate.surfaces import Geometry
    from solidseas.tessellate.topology import Topology

    xt = xt_bodies.hairpin_sheet()
    side = next(n for n in xt.nodes if n.type == xt_bodies.B_SURFACE)
    return Geometry(Topology(xt), chord).surface(side)


def test_inversion_keeps_the_nearest_point_not_the_first_found_within_the_tolerance():
    """On the hairpin the control point nearest a point of the far wall is on the near
    wall, five chords across the gap, and Newton from it stops at the near wall's foot.
    Taken as the first point within ten chords it is wrong; with ``near`` the chord, the
    other starting points are tried and the far wall's own point, at no distance, kept."""
    S = _hairpin_surface()
    p = (0.012, 5e-4, 0.005)  # on the far wall, beside the hole
    u, v, d = S.closest(p, None, 1e-3, 1e-6)  # without near: the first within ten chords
    assert d == pytest.approx(5e-4) and S.point(u, v)[1] == pytest.approx(0.0, abs=1e-12)
    u, v, d = S.closest(p, None, 1e-3, 1e-6, near=1e-4)
    assert d < 1e-12 and math.dist(S.point(u, v), p) < 1e-12
    # a starting point already within near is taken at once
    assert S.closest(p, (u, v), 1e-3, 1e-6, near=1e-4) == pytest.approx((u, v, 0.0), abs=1e-12)


def _covers(tris3, x: float, z: float) -> bool:
    """Whether a triangle of ``tris3`` (corners as points) covers (x, z) seen along y."""
    for a, b, c in tris3:
        d1 = (b[0] - a[0]) * (z - a[2]) - (b[2] - a[2]) * (x - a[0])
        d2 = (c[0] - b[0]) * (z - b[2]) - (c[2] - b[2]) * (x - b[0])
        d3 = (a[0] - c[0]) * (z - c[2]) - (a[2] - c[2]) * (x - c[0])
        if (d1 >= 0 and d2 >= 0 and d3 >= 0) or (d1 <= 0 and d2 <= 0 and d3 <= 0):
            return True
    return False


def test_a_hole_in_the_far_wall_of_a_fold_is_cut_from_the_far_wall():
    """The hole's loop starts with no hint, and its first point is inverted from the
    nearest control point, on the near wall: kept there, the hole fell on the near wall's
    part of the face's (u, v) and the face could not be triangulated. The nearest point
    over every starting point puts it on the far wall."""
    L, gap, H, hole = 0.02, 5e-4, 0.01, 0.002
    t = tessellate_transmit(xt_bodies.hairpin_sheet(L, gap, H, hole), chord_m=1e-4)
    assert t.counts["faces_done"] == 1 and t.reasons == {}
    assert t.measures()["area"] == pytest.approx((2 * L + gap) * H - math.pi * hole**2, rel=5e-3)
    pos, tris = t.welded()
    at = [tuple(pos[3 * i : 3 * i + 3]) for i in range(len(pos) // 3)]
    near, far = [], []
    for k in range(0, len(tris), 3):
        corners = [at[i] for i in tris[k : k + 3]]
        ys = [p[1] for p in corners]
        assert not (min(ys) < 1e-9 and max(ys) > gap - 1e-9 and min(p[0] for p in corners) < L - 1e-9)
        if max(ys) < 1e-9:
            near.append(corners)
        elif min(ys) > gap - 1e-9:
            far.append(corners)
    assert _covers(near, L / 2, H / 2) and not _covers(far, L / 2, H / 2)


def test_a_loop_round_a_cylinder_winds_once_and_one_across_its_seam_does_not():
    S = surfaces.Cylinder((0, 0, 0), (0, 0, 1), 1.0, (1, 0, 0))
    ring = [(2 * math.pi * k / 24 - math.pi, 0.0, k) for k in range(24)]
    pts, du, dv = unwrap(S, 1, ring)
    assert winding(S, du, dv) == (1, 0)
    patch = [(3.0, 0.0, 0), (3.3, 0.0, 1), (3.3, 1.0, 2), (3.0, 1.0, 3)]  # across u = pi
    patch = [(u if u <= math.pi else u - 2 * math.pi, v, k) for u, v, k in patch]
    pts, du, dv = unwrap(S, 1, patch)
    assert winding(S, du, dv) == (0, 0) and max(p[0] for p in pts) - min(p[0] for p in pts) == pytest.approx(
        0.3
    )


# --------------------------------------------------------------------------- whole synthetic solids
R, RT, RC, H = 0.01, 0.003, 0.005, 0.02
SHAPES = {
    "sphere": (xt_bodies.sphere(R), 4 / 3 * math.pi * R**3, 4 * math.pi * R * R),
    "torus": (xt_bodies.torus(R, RT), 2 * math.pi**2 * R * RT * RT, 4 * math.pi**2 * R * RT),
    "cylinder": (
        xt_bodies.cylinder(RC, H),
        math.pi * RC * RC * H,
        2 * math.pi * RC * H + 2 * math.pi * RC * RC,
    ),
    "hemisphere": (xt_bodies.hemisphere(R), 2 / 3 * math.pi * R**3, 3 * math.pi * R * R),
    "cone": (
        xt_bodies.cone(0.005, 0.01),
        math.pi * 0.005**2 * 0.01 / 3,
        math.pi * 0.005 * math.hypot(0.005, 0.01) + math.pi * 0.005**2,
    ),
    "nurbs_cylinder": (
        xt_bodies.nurbs_cylinder(RC, H),
        math.pi * RC * RC * H,
        2 * math.pi * RC * H + 2 * math.pi * RC * RC,
    ),
    "nurbs_sphere": (xt_bodies.nurbs_sphere(R), 4 / 3 * math.pi * R**3, 4 * math.pi * R * R),
}


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_synthetic_solids_come_out_closed_with_their_volume_and_area(name):
    xt, volume, area = SHAPES[name]
    assert validate(xt)["ok"]
    t = tessellate_transmit(xt, chord_m=1e-5)
    m = t.measures()
    assert t.closed is True and t.skipped == () and t.truncated == ()
    assert m["volume"] == pytest.approx(volume, rel=5e-3)
    assert m["area"] == pytest.approx(area, rel=5e-3)
    finer = tessellate_transmit(xt, chord_m=1e-6, angle_deg=5).measures()
    assert abs(finer["volume"] / volume - 1) < abs(m["volume"] / volume - 1) + 1e-12


@pytest.mark.parametrize("up", [True, False], ids=["up", "down"])
@pytest.mark.parametrize("R", [0.003, 0.005, -0.002], ids=["apple", "horn", "lemon"])
def test_a_dome_on_a_torus_that_meets_its_axis_is_capped_at_its_pole(R, up):
    """A torus whose major radius is at most its minor one meets its axis where
    R + r cos v is nought: those are its poles, and a face whose loop wraps it once with
    such a point beyond it is a cap. Without them it failed as seam_configuration (one
    loop wraps the surface and there is no pole beyond it)."""
    r = 0.005
    t = tessellate_transmit(xt_bodies.torus_dome(R, r, up), chord_m=1e-5)
    vp = math.acos(-R / r)
    n = 20_000
    volume = math.pi * sum(
        (R + r * math.cos(v)) ** 2 * r * math.cos(v) * vp / n for v in (vp * (k + 0.5) / n for k in range(n))
    )
    area = 2 * math.pi * r * (R * vp + r * math.sin(vp)) + math.pi * (R + r) ** 2
    m = t.measures()
    assert t.reasons == {} and t.closed is True and not any(t.checks.values())
    assert m["volume"] == pytest.approx(volume, rel=6e-3)
    assert m["area"] == pytest.approx(area, rel=5e-3)
    S = surfaces.Torus((0, 0, 0), (0, 0, 1), R, r, (1, 0, 0))
    for v_pole, point in S.poles:
        assert math.hypot(point[0], point[1]) == 0.0
        assert S.closest(point, None, 1e-9, 1e-9) == (None, v_pole, pytest.approx(0.0, abs=1e-12))


def test_unwrap_keeps_every_point_of_a_run_at_a_pole():
    """Boundary samples within a collapsed row's reach are pole points with ids of their
    own, which the next face uses too: each stays, in order along the pole line."""
    S = surfaces.Sphere((0, 0, 0), 1.0, (0, 0, 1), (1, 0, 0))
    top = math.pi / 2
    loop = [(0.0, 0.5, 1), (0.4, 0.8, 2), (None, top, 10), (None, top, 11), (None, top, 12)]
    loop += [(1.4, 0.8, 3), (1.6, 0.5, 4), (3.5, 0.2, 5)]
    pts, _du, _dv = unwrap(S, 1, loop)
    assert {p[2] for p in pts} == {e[2] for e in loop}
    line = [p for p in pts if p[1] == top]
    assert [p[2] for p in line] == [10, 11, 12]
    assert line[0][0] == pytest.approx(0.4) and line[-1][0] == pytest.approx(1.4 - 2 * math.pi)
    assert line[0][0] > line[1][0] > line[2][0]  # along the pole line, the way round it goes
    one = [(0.0, 0.5, 1), (0.4, 0.8, 2), (None, top, 10), (1.4, 0.8, 3), (3.5, 0.2, 5)]
    pts, _du, _dv = unwrap(S, 1, one)
    assert [p[2] for p in pts if p[1] == top] == [10, 10]  # one pole point opens into a line


def _opts(**kw):
    base = dict(
        chord=1e-5,
        angle=math.radians(15),
        max_faces=10,
        max_triangles=10_000,
        max_face_points=50_000,
        max_edge_points=10_000,
        max_seconds=1.0,
    )
    base.update(kw)
    return Options(**base)


def _stopping_curve():
    """A cubic B-spline along x on uneven knots that stops dead at one of them (a control
    point three times over, so it turns there with its speed nought) between two of the
    sampler's first samples."""
    from solidseas.tessellate.curves import BCurve

    cps = [(0.001 * k, 0.0005 * math.sin(k), 0.0) for k in range(12)]
    cps[5:6] = [cps[5]] * 3
    n = len(cps)
    knots = [0.0, 1.37, 2.11, 3.53, 4.29, 5.71, 6.05, 7.43, 8.17, 9.61, 10.39, 11.0]
    U = nurbs.knot_vector(knots, [4] + [1] * (n - 4) + [4], n, 3)
    return BCurve(nurbs.BSplineCurve(3, cps, U, False, False), 1)


def _edge_sampler(chord: float, corners: bool = True):
    from types import SimpleNamespace

    from solidseas.tessellate.edges import EdgeSampler

    opts = SimpleNamespace(chord=chord, angle=math.radians(15), max_edge_points=10_000, corners=corners)
    return EdgeSampler(None, None, None, opts, Clock(30.0))


def test_an_edge_is_not_halved_into_points_closer_than_a_micrometre():
    """Where a curve stops dead and turns, the turn stays whatever the segment's length,
    and the sampler halved it to the depth bound, piling samples a billionth of a
    millimetre apart. Stopping such halving at 2% of the chord tolerance still left
    points a ten-thousandth of a millimetre apart, closer than their (u, v) on a face can
    be told apart: on one corpus file such a run crossed its face's own boundary in
    (u, v), and the face came out 52% too large with no fold found. A point a halving
    puts within a micrometre (or a hundredth of the chord tolerance) of the one before is
    now left out, and no segment that short is halved for its turn alone; the polyline
    still keeps within the chord tolerance and that distance of the curve. The STEP
    writer's sampler, whose checks want the curve as it is, halves as it always did: here
    past ``max_edge_points``, so the writer refuses such an edge rather than write it loose."""
    curve = _stopping_curve()
    chord, near = 1e-5, 1e-6
    pts, ts = _edge_sampler(chord)._adaptive(curve, curve.lo, curve.hi)
    assert len(pts) == len(ts) and pts[0] == curve.point(curve.lo) and pts[-1] == curve.point(curve.hi)
    assert min(math.dist(pts[k], pts[k + 1]) for k in range(len(pts) - 1)) > near
    for k in range(len(pts) - 1):
        a, b, ta, tb = pts[k], pts[k + 1], ts[k], ts[k + 1]
        ab = [b[i] - a[i] for i in range(3)]
        for f in (0.25, 0.5, 0.75):
            q = curve.point(ta + f * (tb - ta))
            s = sum((q[i] - a[i]) * ab[i] for i in range(3)) / (sum(c * c for c in ab) or 1.0)
            s = max(0.0, min(1.0, s))
            assert math.dist(q, [a[i] + s * ab[i] for i in range(3)]) <= chord + 2 * near
    with pytest.raises(FaceFailed, match="edge_too_long"):
        _edge_sampler(chord, corners=False)._adaptive(curve, curve.lo, curve.hi)


def test_a_closed_edge_smaller_than_the_merge_distance_keeps_its_samples():
    """A closed edge whose whole round is within the distance at which a halving's points
    are left out keeps its first samples: merged into its one vertex it would bound
    nothing (a small sheet face drawn before came out as ``no_boundary``)."""
    from solidseas.tessellate.curves import BCurve

    r = 1e-7
    ring = [(r * math.cos(2 * math.pi * k / 8), r * math.sin(2 * math.pi * k / 8), 0.0) for k in range(8)]
    ring += ring[:3]  # periodic: the first degree points again
    n = len(ring)
    U = [float(k) for k in range(n + 4)]
    curve = BCurve(nurbs.BSplineCurve(3, ring, U, False, True), 1)
    pts, _ts = _edge_sampler(1e-4)._adaptive(curve, curve.lo, curve.hi)
    assert len(pts) >= 4 and math.dist(pts[0], pts[-1]) < 1e-12


def test_placing_holes_ticks_the_clock_and_is_free_on_an_open_surface():
    """The work of placing a hole is the outer ring's length for each period tried: the
    clock ticks by it, so a face with a long ring and many holes stops at the limit."""
    ring = [(2 * math.pi * k / 4000, 0.0 if k % 2 else 0.001, k) for k in range(4000)]
    hole = [(3.0, 0.5, 9001), (3.1, 0.5, 9002), (3.05, 0.6, 9003)]
    cyl = surfaces.Cylinder((0, 0, 0), (0, 0, 1), 0.01, (1, 0, 0))
    late = Builder(cyl, 1, _opts(), lambda p: 0, Clock(-1.0))
    with pytest.raises(TimeUp):
        late.place(ring, hole)
    plane = surfaces.Plane((0, 0, 0), (0, 0, 1), (1, 0, 0))
    assert Builder(plane, 1, _opts(), lambda p: 0, Clock(-1.0)).place(ring, hole) is hole


def test_the_nearest_control_points_of_a_large_net_are_found_within_the_clock():
    """A net of more than SEED_FULL points is searched coarsely, then around the nearest:
    on a flat net the nearest control point is still the one found, and the search ticks
    the clock."""
    n = 300
    U = [0.0] + [k / (n - 1) for k in range(n)] + [1.0]
    rows = [[(i / (n - 1), j / (n - 1), 0.0) for j in range(n)] for i in range(n)]
    s = nurbs.BSplineSurface(1, 1, rows, U, U, False, False, False)
    assert n * n > nurbs.SEED_FULL
    for p in ((0.4137, 0.7219, 0.001), (0.0, 1.0, -0.2), (0.99, 0.013, 0.0)):
        i, j = round(p[0] * (n - 1)), round(p[1] * (n - 1))
        assert s.seeds(p)[0] == pytest.approx((i / (n - 1), j / (n - 1)))
    with pytest.raises(TimeUp):
        s.seeds((0.5, 0.5, 0.0), clock=Clock(-1.0))


@pytest.mark.parametrize(
    ("axis", "angle", "splits"),
    [
        ((0.0, 0.0, 1.0), 0.0, 3),
        ((-0.6423795875451945, 0.6104007527689248, 0.4634213919581139), 0.801322977421273, 5),
        ((0.9038329516201631, -0.0961274846597221, -0.4169478411727048), 0.6595924772825, 5),
        ((0.3372355268463094, 0.8482083958988174, 0.408429573561278), 1.657596691978795, 4),
    ],
)
def test_runs_of_boundary_points_in_a_line_keep_a_box_closed(axis, angle, splits):
    """Three points in a line can make a triangle with no area; its edges are edges of the
    face's other triangles and of the next face's, so it stays and the box stays closed."""
    t = tessellate_transmit(xt_bodies.split_box(splits=splits, axis=axis, angle=angle))
    m = t.measures()
    assert t.closed is True and t.reasons == {}
    assert m["volume"] == pytest.approx(0.03 * 0.02 * 0.01, rel=1e-9)
    assert m["area"] == pytest.approx(2 * (0.03 * 0.02 + 0.03 * 0.01 + 0.02 * 0.01), rel=1e-9)


@pytest.mark.parametrize("turn", [0.0, 0.1, 0.37])
@pytest.mark.parametrize("gap", [0.0, -1e-7, -5e-6], ids=["touching", "crossing 0.1 um", "crossing 5 um"])
def test_a_solid_whose_face_boundary_touches_itself_comes_out_closed(gap, turn, monkeypatch):
    """A hole tangent to the disc's rim, or crossing it by less than the chord tolerance:
    sampled, the top and bottom faces' loops touch or cross, which no triangulation of
    the polygon can take, and accepted loosely their triangles left some boundary unused
    and the solid open. The points on the wrong side are moved just across in the
    triangulation's (u, v) alone, and every boundary segment is used once each way."""
    from solidseas.tessellate import _engine

    seen = []
    real = _engine.Engine._untangled

    def untangled(self, dom, rings):
        got = real(self, dom, rings)
        seen.append(got is not None)
        return got

    monkeypatch.setattr(_engine.Engine, "_untangled", untangled)
    R, H, hole = 0.01, 0.004, 0.003
    t = tessellate_transmit(xt_bodies.holed_disc(R, H, hole, gap, turn), chord_m=1e-5)
    assert seen == [True, True]  # the top and the bottom
    assert t.closed is True and t.reasons == {} and not any(t.checks.values())
    assert t.measures()["volume"] == pytest.approx(math.pi * (R * R - hole * hole) * H, rel=2e-3)


def test_untangling_moves_only_what_lies_on_the_wrong_side():
    """A square hole poking a hair out of a square outer ring: its two corners outside are
    moved just inside, along the outer side's normal; a corner the two rings share (one
    point id) stays; and rings that do not touch are left as they are."""
    xy = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    xy += [(0.4, 0.2), (0.6, 0.2), (0.6, 1.0 + 1e-6), (0.4, 1.0 + 1e-6)]
    pid = list(range(8))
    rings = [[0, 1, 2, 3], [7, 6, 5, 4]]
    assert tri.untangle(xy, rings, pid, 1e-4, Clock(30)) == 2
    assert xy[6] == pytest.approx((0.6, 1.0 - 1e-7)) and xy[7] == pytest.approx((0.4, 1.0 - 1e-7))
    assert xy[4] == (0.4, 0.2) and xy[0] == (0.0, 0.0)
    tris, complete = tri.earcut(xy, rings[0], rings[1:], pid, Clock(30))
    assert complete and tri.check(xy, rings, tris)
    apart = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.4, 0.2), (0.6, 0.2), (0.6, 0.8), (0.4, 0.8)]
    assert tri.untangle(list(apart), rings, pid, 1e-4, Clock(30)) == 0
    shared = list(xy)
    shared[7] = (0.0, 1.0)
    assert tri.untangle(shared, rings, [0, 1, 2, 3, 4, 5, 6, 3], 1e-4, Clock(30)) <= 1  # 7 is 3: stays
    assert shared[7] == (0.0, 1.0)


def test_a_face_thinner_than_the_tolerance_follows_its_loop():
    """A sliver whose loop runs against its normal (its sides cross within the tolerance):
    its triangles run the loop's way, so its edges meet the next face's the other way."""
    b = xt_bodies.XtBuilder()
    pts = [(0.0, 0.0, 0.0), (0.01, 0.0, 0.0), (0.005, -1e-8, 0.0)]  # clockwise seen from +z
    vs = [b.vertex(p) for p in pts]
    edges = []
    for k in range(3):
        a, c = pts[k], pts[(k + 1) % 3]
        edges.append(b.edge(b.line(a, tuple(c[i] - a[i] for i in range(3))), vs[k], vs[(k + 1) % 3]))
    b.face(b.plane((0, 0, 0), (0, 0, 1), (1, 0, 0)), "+", [[(e, "+") for e in edges]])
    t = tessellate_transmit(b.body(edges, body_type=3), chord_m=1e-5)
    assert t.counts["faces_done"] == 1
    pos, tris = t.welded()
    at = [tuple(pos[3 * i : 3 * i + 3]) for i in range(len(pos) // 3)]
    directed = {
        (at[tris[k + j]], at[tris[k + (j + 1) % 3]]) for k in range(0, len(tris), 3) for j in range(3)
    }
    rim = {e for e in directed if (e[1], e[0]) not in directed}
    assert rim == {(pts[k], pts[(k + 1) % 3]) for k in range(3)}


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _angles_to_normals(mesh):
    """Per vertex, the angle between its normal and the mean of its triangles' normals."""
    P, N, T = mesh.positions, mesh.normals, mesh.triangles
    acc: dict[int, list[float]] = {}
    for k in range(0, len(T), 3):
        a, b, c = (tuple(P[3 * i : 3 * i + 3]) for i in T[k : k + 3])
        n = _cross(_sub(b, a), _sub(c, a))
        for i in T[k : k + 3]:
            s = acc.setdefault(i, [0.0, 0.0, 0.0])
            for j in range(3):
                s[j] += n[j]
    out = []
    for i, s in acc.items():
        vn = tuple(N[3 * i : 3 * i + 3])
        ls = math.hypot(*s)
        if ls > 0.0:
            cos = sum(x * y for x, y in zip(s, vn, strict=True)) / (ls * math.hypot(*vn))
            out.append(math.degrees(math.acos(max(-1.0, min(1.0, cos)))))
    return out


def test_vertex_normals_at_the_poles_of_a_b_spline_are_their_triangles_mean():
    """At a B-spline row collapsed to a point the derivatives are rounding noise: the
    normal there is the mean of the triangles round it, not the noise's."""
    t = tessellate_transmit(xt_bodies.nurbs_sphere(0.01), chord_m=1e-5)
    assert t.closed is True
    assert max(_angles_to_normals(t.mesh)) < 15.0


def test_triangles_beside_a_curved_boundary_keep_to_the_surface():
    """A small fillet's boundary circle is a chord polygon lying off the surface by its
    sagitta; points inside keep far enough from each chord that no triangle on it stands
    up off the surface or faces back. With the circles sampled for the fillet's curvature
    across them, its area is within 0.5 percent (1.5 percent over, before)."""
    R, r = 0.00135, 0.0002
    t = tessellate_transmit(xt_bodies.torus_band(R, r, -math.pi / 2, 0.0), chord_m=3.1e-5)
    pos, tris = t.welded()
    at = [tuple(pos[3 * i : 3 * i + 3]) for i in range(len(pos) // 3)]
    worst = 0.0
    for k in range(0, len(tris), 3):
        a, b, c = (at[i] for i in tris[k : k + 3])
        n = _cross(_sub(b, a), _sub(c, a))
        ln = math.hypot(*n)
        g = tuple((a[i] + b[i] + c[i]) / 3 for i in range(3))
        rho = math.hypot(g[0], g[1])
        out = (g[0] - R * g[0] / rho, g[1] - R * g[1] / rho, g[2])  # from the centre circle
        cos = sum(x * y for x, y in zip(n, out, strict=True)) / (ln * math.hypot(*out))
        worst = max(worst, math.degrees(math.acos(max(-1.0, min(1.0, cos)))))
    assert worst < 30.0
    exact = 2 * math.pi * r * (R * math.pi / 2 + r)
    assert t.measures()["area"] == pytest.approx(exact, rel=5e-3)


def _turns(t, face: int | None = None) -> tuple[float, float]:
    """``(on a boundary chord, anywhere)``: the largest angle, in degrees, between a
    triangle's normal and the vertex normals (the surface's own) at its corners, over the
    faces of ``t`` (or the one whose FACE ``node_id`` is ``face``). A boundary chord is an
    edge of a face's triangles that no other triangle of the face uses."""
    m = t.mesh
    P, N, T = m.positions, m.normals, m.triangles
    on_chord = anywhere = 0.0
    for f, (_body, fid) in zip(m.faces, t.face_ids, strict=True):
        if face is not None and fid != face:
            continue
        first, last = f.first_triangle, f.first_triangle + f.n_triangles
        tris = [tuple(T[3 * k : 3 * k + 3]) for k in range(first, last)]
        used = {(t3[j], t3[(j + 1) % 3]) for t3 in tris for j in range(3)}
        for t3 in tris:
            a, b, c = (tuple(P[3 * i : 3 * i + 3]) for i in t3)
            n = _cross(_sub(b, a), _sub(c, a))
            ln = math.hypot(*n)
            if ln == 0.0:
                continue
            w = 0.0
            for i in t3:
                vn = tuple(N[3 * i : 3 * i + 3])
                cos = sum(x * y for x, y in zip(n, vn, strict=True)) / (ln * math.hypot(*vn))
                w = max(w, math.degrees(math.acos(max(-1.0, min(1.0, cos)))))
            anywhere = max(anywhere, w)
            if any((t3[(j + 1) % 3], t3[j]) not in used for j in range(3)):
                on_chord = max(on_chord, w)
    return on_chord, anywhere


SMALL_FILLETS = {
    # (body, chord): a torus band of 0.5 mm along a 50 mm arc, of 1 mm along 20 mm, and a
    # cylinder of 50 mm whose top edge is rounded by 1 mm, as a rolling blend and as a torus
    "band 50/0.5": (lambda: xt_bodies.torus_band(0.05, 0.0005, -math.pi / 2, 0.0), 1e-4),
    "band 20/1": (lambda: xt_bodies.torus_band(0.02, 0.001, -math.pi / 2, 0.0), 5e-5),
    "blend 50/1": (lambda: xt_bodies.rounded_cylinder(0.05, 0.02, 0.001), None),
    "torus 50/1": (lambda: xt_bodies.rounded_cylinder(0.05, 0.02, 0.001, torus=True), None),
}


@pytest.mark.parametrize("name", sorted(SMALL_FILLETS))
def test_an_edge_beside_a_small_fillet_is_sampled_for_the_fillet_too(name):
    """Along a long arc, an edge's chords lie off it by up to the chord tolerance, and the
    points inside a small fillet beside it keep that far over tan(angle) from them: the
    fillet has turned well past the angle there, and the triangles on those chords turned
    22 to 73 degrees. Sampled for the fillet's curvature across it (a rolling blend's from
    its radius), none turns past the angle; solids stay closed."""
    make, chord = SMALL_FILLETS[name]
    t = tessellate_transmit(make(), **({} if chord is None else {"chord_m": chord}))
    on_chord, _anywhere = _turns(t)
    assert on_chord < t.angle_deg
    assert t.reasons == {} and t.closed in (True, None)


def test_o11s_fillet_keeps_within_the_angle():
    """o11's fillet, a torus of radii 6 and 1 mm between arcs of 6 and 5 mm: at the
    default chord its triangles on those arcs turned up to 59 degrees from the surface.
    With the arcs sampled for its curvature across them, no triangle of the part turns
    past the angle, with fewer triangles than before (1,790)."""
    from solidseas import open_document
    from solidseas.tessellate import tessellate_document
    from support import fixture_path

    with open_document(fixture_path("o11_curved.SLDPRT")) as doc:
        t = tessellate_document(doc)
    on_chord, anywhere = _turns(t)
    assert on_chord < t.angle_deg and anywhere < t.angle_deg + 0.5
    assert t.closed is True and t.counts["triangles"] < 1790


def test_a_fillet_far_smaller_than_the_chord_costs_its_edges_three_times_their_samples_at_most(monkeypatch):
    """The finer sampling stops at a tenth of the chord tolerance (CROSS_FLOOR): beside a
    fillet of 0.05 mm at a chord of 0.1 mm a rim of 50 mm gets about the square root of
    ten times the samples it had, no more."""
    from solidseas.tessellate import edges

    def rims(t):
        return sorted(len(e.points) for e in t.detail.edges.values())

    body = xt_bodies.torus_band(0.05, 0.00005, -math.pi / 2, 0.0)
    finer = rims(tessellate_transmit(body, chord_m=1e-4, detail=True))
    monkeypatch.setattr(edges, "CROSS_FLOOR", 2.0)  # over the chord: the edges sampled for themselves
    plain = rims(tessellate_transmit(body, chord_m=1e-4, detail=True))
    assert len(finer) == len(plain) == 2
    for a, b in zip(finer, plain, strict=True):
        assert 2.5 * b <= a <= math.sqrt(10.0) * b + 2


@pytest.mark.parametrize(
    ("surface", "t", "expected"),
    [
        # across a circle round a cylinder it is straight; across a line along it, round
        (surfaces.Cylinder((0, 0, 0), (0, 0, 1), 0.02, (1, 0, 0)), (0.0, 1.0, 0.0), 0.0),
        (surfaces.Cylinder((0, 0, 0), (0, 0, 1), 0.02, (1, 0, 0)), (0.0, 0.0, 1.0), 50.0),
        (surfaces.Sphere((0, 0, 0), 0.01, (0, 0, 1), (1, 0, 0)), (0.0, 1.0, 0.0), 100.0),
        # a torus across a circle round its axis: its tube's own curvature
        (surfaces.Torus((0, 0, 0), (0, 0, 1), 0.05, 0.01, (1, 0, 0)), (0.0, 1.0, 0.0), 100.0),
        (surfaces.Plane((0, 0, 0), (0, 0, 1), (1, 0, 0)), (0.0, 1.0, 0.0), 0.0),
    ],
    ids=["cylinder along", "cylinder across", "sphere", "torus", "plane"],
)
def test_a_surface_measures_its_curvature_across_a_curve(surface, t, expected):
    p = surface.point(0.0, 0.0)  # on the x axis, where t is a tangent of each
    k, _uv = surface.bend_across(p, t, None, 1e-6)
    assert k == pytest.approx(expected, abs=1e-3)


def test_a_b_spline_surface_measures_its_curvature_across_a_curve_on_its_edge():
    """Measured at a curve on the surface's own edge (the end circles of a B-spline
    cylinder), the differences stay inside its parameter range: across the circle the
    cylinder is straight, and across a line along it as round as its radius."""
    xt = xt_bodies.nurbs_cylinder(0.005, 0.02)
    from solidseas.tessellate.surfaces import Geometry
    from solidseas.tessellate.topology import Topology

    side = next(n for n in xt.nodes if n.type == xt_bodies.B_SURFACE)
    S = Geometry(Topology(xt), 1e-5).surface(side)
    for v in (0.0, 0.5, 1.0):
        p = S.point(0.3, v)
        tangent = _unit(S.d1(0.3, v)[1])
        assert S.bend_across(p, tangent, None, 1e-6)[0] == pytest.approx(0.0, abs=1e-3)
        assert S.bend_across(p, (0.0, 0.0, 1.0), None, 1e-6)[0] == pytest.approx(200.0, rel=1e-3)


def _unit(a):
    n = math.hypot(*a)
    return (a[0] / n, a[1] / n, a[2] / n)


@pytest.mark.parametrize("error", [AttributeError, RecursionError])
def test_damage_the_checks_did_not_foresee_costs_a_face_or_a_body_not_the_tessellation(monkeypatch, error):
    """A reference to the wrong kind of node (AttributeError) or a crafted chain of
    nodes (RecursionError) in the geometry code: the face is skipped as degenerate, and
    a body whose faces cannot be listed is skipped, as tessellate_transmit promises."""
    from solidseas.tessellate import _engine
    from solidseas.tessellate.topology import Topology

    real_face = _engine.Engine.face
    calls = []

    def face(self, *args, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise error("crafted")
        return real_face(self, *args, **kw)

    monkeypatch.setattr(_engine.Engine, "face", face)
    t = tessellate_transmit(xt_bodies.split_box(splits=1))
    assert [(s.reason, s.detail) for s in t.skipped] == [("degenerate", error.__name__)]
    assert t.counts["faces_done"] == t.counts["faces"] - 1
    monkeypatch.undo()

    def faces(self, node):
        raise error("crafted")

    monkeypatch.setattr(Topology, "faces", faces)
    t = tessellate_transmit(xt_bodies.split_box(splits=1))
    assert t.counts["bodies_skipped"] == 1 and [s.reason for s in t.skipped] == ["degenerate"]


def test_the_points_kept_are_bounded_and_reaching_the_bound_stops_as_the_triangles_do(monkeypatch):
    from solidseas.tessellate import _engine

    pts = _engine.Points(limit=2)
    pts.add((0.0, 0.0, 0.0))
    pts.add((1.0, 0.0, 0.0))
    with pytest.raises(_engine.PointsFull):
        pts.add((2.0, 0.0, 0.0))
    real_init = _engine.Engine.__init__

    def small(self, opts, clock):
        real_init(self, opts, clock)
        self.pts.limit = 20  # far fewer than a cylinder's faces need

    monkeypatch.setattr(_engine.Engine, "__init__", small)
    t = tessellate_transmit(xt_bodies.cylinder(0.005, 0.02), chord_m=1e-5)
    assert t.truncated == ("max_triangles",)


def test_an_extent_too_large_to_measure_gives_the_default_chord():
    from solidseas.tessellate import CHORD_FRACTION, _chord

    assert _chord([(-1e308, -1e308, -1e308), (1e308, 1e308, 1e308)]) == 1e-4  # not inf or NaN
    assert _chord([(0.0, 0.0, 0.0), (0.5, 0.0, 0.0)]) == pytest.approx(0.5 * CHORD_FRACTION)
