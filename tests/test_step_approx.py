"""STEP export: geometry STEP cannot hold exactly, on synthetic bodies.

Each body is written, re-read and checked by ``step_support`` (which shares no code
with the writer): an intersection curve and an SP-curve fitted by B-splines within
their measured deviation, an SP-curve along an iso-parameter line written exactly,
and a rolling blend approximated by a rational B-spline surface whose side is
taken from the faces it meets. The file's uncertainty covers each deviation, every
vertex lies on its curves and surfaces within it, and ``exact_only`` refuses what
would have to be approximated.
"""

import math

import pytest

import step_support as T
import xt_bodies as X
from solidseas.errors import NotRepresentableError
from solidseas.step import step_bytes, step_transmit, uncertainty

STAMP = "2026-10-03T00:00:00Z"


def _numbered(xt):
    for n in xt.nodes:
        if n.type in (14, 16, 18):
            n.vals[0] = n.index
    return xt


def _bcurve2(xt, cps, degree, knots, mults, rational=False, periodic=False):
    """A two-dimensional B_CURVE (for an SP-curve)."""
    flat = [float(x) for c in cps for x in c]
    verts = X.add_node(xt, 45, vertices=flat)
    verts.count = len(flat)
    kn = X.add_node(xt, 128, knots=[float(k) for k in knots])
    kn.count = len(knots)
    mu = X.add_node(xt, 127, mult=list(mults))
    mu.count = len(mults)
    nc = X.add_node(
        xt,
        136,
        degree=degree,
        n_vertices=len(cps),
        vertex_dim=len(cps[0]),
        n_knots=len(knots),
        rational=1 if rational else 0,
        periodic=1 if periodic else 0,
        bspline_vertices=verts.index,
        knot_mult=mu.index,
        knots=kn.index,
    )
    return X.add_node(xt, 134, nurbs=nc.index, sense="+")


def check(xt, **options) -> dict:
    xt = _numbered(xt)
    m = step_transmit(xt, **options)
    data = step_bytes(m, time_stamp=STAMP)
    got = T.full_check(data, m, [xt])
    got["model"] = m
    return got


def assert_sound(got, untessellated: int = 0) -> None:
    assert got["syntax"] == [] and got["topology"] == []
    assert got["geometry"]["beyond"] == []
    ori = got["orientation"]
    assert ori["disagree"] == [] and ori["far"] == 0 and ori["not_tessellated"] == untessellated
    assert got["arcs"]["wrong"] == [] and got["pieces"]["wrong"] == []


# --------------------------------------------------------------------------- intersection curves
def chart_cylinder(points: int = 64):
    """The synthetic cylinder with its bottom ring edge on an INTERSECTION of the side
    and the bottom plane: a closed chart of ``points`` points round the circle."""
    xt = X.cylinder()
    circle = next(n for n in xt.nodes if n.tname == "CIRCLE")
    r = X.field(xt, circle, "radius")
    pts = [
        (r * math.cos(2 * math.pi * k / points), r * math.sin(2 * math.pi * k / points), 0.0)
        for k in range(points)
    ]
    pts.append(pts[0])
    chart = X.add_node(xt, 40, chordal_error=1e-6, hvec=pts)
    chart.count = len(pts)
    surfaces = [n.index for n in xt.nodes if n.tname in ("PLANE", "CYLINDER")][:2]
    inter = X.add_node(xt, 38, chart=chart.index, surface=surfaces, sense="+")
    edge = next(e for e in xt.nodes if e.tname == "EDGE" and X.field(xt, e, "curve") == circle.index)
    X.set_field(xt, edge, "curve", inter.index)
    return xt


def test_an_intersection_curve_is_fitted_within_its_measured_deviation():
    got = check(chart_cylinder())
    assert_sound(got)
    m = got["model"]
    assert not m.exact and m.approximated == {"INTERSECTION": 1}
    assert 0.0 < m.max_deviation_m <= 1e-7  # the target
    assert m.uncertainty_m == uncertainty(m.max_deviation_m) >= 1.5 * m.max_deviation_m
    assert [w.code for w in m.warnings] == ["step_approximated"]
    (b,) = m.bodies
    assert b.approximated_edges == 1 and b.approximated_faces == 0
    f = got["file"]
    assert T.uncertainty_mm(f) == pytest.approx(m.uncertainty_m * 1000.0)
    # the fit is a B-spline through points on both surfaces: on the circle within it (the
    # ring it bounds the cylinder's side with is cut in two at the side's seams, each piece
    # the fit restricted to its own range)
    fits = [e for e in f.entities.values() if e.name == "B_SPLINE_CURVE_WITH_KNOTS"]
    assert len(fits) == 2
    for fit in fits:
        c = T.Curve(f, fit.id)
        lo, hi = c.bounds()
        for k in range(101):
            p = c.point(lo + (hi - lo) * k / 100)
            assert abs(math.hypot(p[0], p[1]) - 5.0) <= 1e-4 and abs(p[2]) <= 1e-4  # mm


def test_exact_only_refuses_what_would_be_approximated():
    with pytest.raises(NotRepresentableError) as exc:
        step_transmit(_numbered(chart_cylinder()), exact_only=True)
    assert [b.reason for b in exc.value.bodies] == ["approximation_refused"]


def test_a_fit_beyond_the_limit_is_refused(monkeypatch):
    from solidseas.step import approx

    monkeypatch.setattr(approx, "MAX_POINTS", 5)  # too few points to follow the circle
    with pytest.raises(NotRepresentableError) as exc:
        step_transmit(_numbered(chart_cylinder()))
    assert [b.reason for b in exc.value.bodies] == ["fit_failed"]
    assert "more than the 1e-06 m allowed" in exc.value.bodies[0].message


# --------------------------------------------------------------------------- SP-curves
def sp_cylinder(v_wobble: float = 0.0, top_plane_sp: bool = False):
    """The synthetic cylinder with its top ring edge on an SP-curve of the side: u from 0
    to 2 pi at v = h (an iso-parameter line), or with ``v_wobble`` added to every other
    control point, which makes it a curve the export fits. With ``top_plane_sp`` the
    bottom edge is an SP-curve of the bottom plane too (a rational circle in (u, v))."""
    r, h = 0.005, 0.02
    xt = X.cylinder(r, h)
    circles = [n for n in xt.nodes if n.tname == "CIRCLE"]
    top = next(c for c in circles if X.field(xt, c, "centre")[2] > 0)
    cyl = next(n for n in xt.nodes if n.tname == "CYLINDER")
    n = 9
    cps = [(2 * math.pi * k / (n - 1), h + (v_wobble if k % 2 else 0.0)) for k in range(n)]
    bc = _bcurve2(
        xt,
        cps,
        1,
        [0.0] + [k / (n - 1) for k in range(1, n - 1)] + [1.0],
        [2] + [1] * (n - 2) + [2],
        periodic=True,  # closed round the cylinder, as Parasolid flags a ring's curve
    )
    sp = X.add_node(xt, 137, surface=cyl.index, b_curve=bc.index, sense="+")
    edge = next(e for e in xt.nodes if e.tname == "EDGE" and X.field(xt, e, "curve") == top.index)
    X.set_field(xt, edge, "curve", sp.index)
    if top_plane_sp:
        bottom = next(c for c in circles if c is not top)
        plane = next(p for p in xt.nodes if p.tname == "PLANE" and X.field(xt, p, "pvec")[2] == 0.0)
        w = math.sqrt(0.5)
        ring = [
            (1, 0, 1),
            (1, 1, w),
            (0, 1, 1),
            (-1, 1, w),
            (-1, 0, 1),
            (-1, -1, w),
            (0, -1, 1),
            (1, -1, w),
            (1, 0, 1),
        ]
        cps2 = [(x * r * wt, y * r * wt, wt) for x, y, wt in ring]
        bc2 = _bcurve2(xt, cps2, 2, [0, 1, 2, 3, 4], [3, 2, 2, 2, 3], rational=True, periodic=True)
        sp2 = X.add_node(xt, 137, surface=plane.index, b_curve=bc2.index, sense="+")
        edge2 = next(e for e in xt.nodes if e.tname == "EDGE" and X.field(xt, e, "curve") == bottom.index)
        X.set_field(xt, edge2, "curve", sp2.index)
    return xt


def test_an_sp_curve_along_an_iso_line_and_one_on_a_plane_are_exact():
    assert_sound(check(sp_cylinder(top_plane_sp=True)))  # the side cut at its seams: sound too
    got = check(sp_cylinder(top_plane_sp=True), split_periodic=False)  # the edges whole, to name them
    assert_sound(got)
    m = got["model"]
    assert m.exact and m.approximated == {} and m.uncertainty_m == 1e-8
    f = got["file"]
    kinds = sorted(
        f.get(e.params[3]).name if not f.get(e.params[3]).complex else "RATIONAL" for e in f.of("EDGE_CURVE")
    )
    assert kinds == ["CIRCLE", "RATIONAL"]  # the iso-curve a circle, the plane's curve its own B-spline


def test_an_sp_curve_off_the_iso_lines_is_fitted():
    """The SP-curve zigzags 0.2 um up and down the cylinder: it is fitted, and the edge
    leaves the top plane by that much between its vertices, a gap of the source's own
    that the file's uncertainty covers."""
    got = check(sp_cylinder(v_wobble=2e-7))
    assert_sound(got)
    m = got["model"]
    assert m.approximated == {"SP_CURVE": 1} and 0.0 < m.max_deviation_m <= 1e-7
    assert m.max_gap_m == pytest.approx(2e-7, rel=0.01)
    assert m.uncertainty_m == uncertainty(m.max_gap_m) >= 1.5 * m.max_gap_m


def test_an_edge_farther_off_its_face_than_allowed_is_refused():
    """1 um and more off the top plane between its vertices: beyond max_deviation_m."""
    with pytest.raises(NotRepresentableError) as exc:
        step_transmit(_numbered(sp_cylinder(v_wobble=2e-6)))
    (b,) = exc.value.bodies
    assert b.reason == "check_failed" and "from its face's surface" in b.message


# --------------------------------------------------------------------------- rolling blends
def test_a_rolling_blend_is_approximated_and_faces_outward():
    got = check(X.filleted_box())
    # The tessellator draws the blend from the same approximation, its side taken from the
    # face's loop where the export takes it from the faces it meets: the oracle compares
    # the two.
    assert_sound(got)
    m = got["model"]
    assert m.approximated == {"BLENDED_EDGE": 1}
    assert m.max_deviation_m <= 1e-9  # a straight spine between planes: the sections loft exactly
    f = got["file"]
    (blend_face,) = [e for e in f.of("ADVANCED_FACE") if f.get(e.params[2]).complex]
    surface = T.Surface(f, blend_face.params[2])
    # The face points away from the spine, out of the material: at the middle of the
    # round its normal is (1, 0, 1) / sqrt 2.
    mid = (30.0 - 2.0 + 2.0 / math.sqrt(2.0), 10.0, 10.0 - 2.0 + 2.0 / math.sqrt(2.0))
    d, n = T.face_normal(f, blend_face, mid)
    assert d <= 1e-6 and n[0] > 0.6 and n[2] > 0.6
    # every section of the surface is the round: points at the radius from the spine
    for k in range(11):
        for j in range(5):
            p = surface.s.point(
                surface.s.ulo + (surface.s.uhi - surface.s.ulo) * k / 10,
                surface.s.vlo + (surface.s.vhi - surface.s.vlo) * j / 4,
            )
            assert math.hypot(p[0] - 28.0, p[2] - 8.0) == pytest.approx(2.0, abs=1e-9)
    assert T.planar_volume is not None


def _blend_surface(f):
    """The blend's face (the first, where a ring of blend was cut in two) and its surface."""
    faces = [e for e in f.of("ADVANCED_FACE") if f.get(e.params[2]).complex]
    assert len({e.params[2] for e in faces}) == 1  # one surface, whatever its faces
    return faces[0], T.Surface(f, faces[0].params[2])


def _canal_deviation(f, spine_point, radius_mm: float, period: float = 2.0 * math.pi) -> float:
    """The written blend surface against its true (canal) surface, by these tests' own
    evaluators: at 11 points along each of its spans and 9 across, the distance to the
    spine (``spine_point(t)``, mm, a closed curve of ``period``; its nearest point by a
    scan of 720 and a golden-section search) less the radius. In mm."""
    _face, surface = _blend_surface(f)
    S = surface.s
    knots = sorted(set(S.U))
    scan = [period * i / 720 for i in range(720)]
    pts = [spine_point(t) for t in scan]
    worst = 0.0
    k = None
    for a, b in zip(knots, knots[1:], strict=False):
        for i in range(1, 12):
            for j in range(9):
                p = S.point(a + (b - a) * i / 12, S.vlo + (S.vhi - S.vlo) * j / 8)
                near = range(720) if k is None else [(k + d) % 720 for d in range(-16, 17)]
                k = min(near, key=lambda k, p=p: T._dist(pts[k], p))
                t = T._golden(
                    lambda t, p=p: T._dist(spine_point(t), p), scan[k] - period / 720, scan[k] + period / 720
                )
                worst = max(worst, abs(T._dist(spine_point(t), p) - radius_mm))
    return worst


def test_a_blend_round_its_whole_spine_closes_on_itself():
    """A ring of blend round a closed spine: lofted from the span of its edges' points
    plus a margin, the surface stopped a sixteenth of a turn short and the face's boundary
    circles left it there. It is lofted round the whole spine, its last section the first,
    and every point of its edges lies on it."""
    got = check(X.rounded_cylinder())
    assert_sound(got)  # the ring of blend, cut in two at its seams: each half compared with the drawn blend
    m, f = got["model"], got["file"]
    assert m.approximated == {"BLENDED_EDGE": 1} and 0.0 < m.max_deviation_m <= 1e-7
    face, surface = _blend_surface(f)
    uclosed, vclosed = f.get(face.params[2]).record("B_SPLINE_SURFACE")[4:6]
    assert (uclosed, vclosed) == ("T", "F")
    assert got["geometry"]["edge_surface_max"] <= 2.0 * T.uncertainty_mm(f)
    # the torus of radii 8 and 2 mm round the spine at z = 18 mm, all the way round
    for rho, z in ((10.0, 18.0), (8.0, 20.0), (8.0 + 2.0 / math.sqrt(2.0), 18.0 + 2.0 / math.sqrt(2.0))):
        uv = "grid"
        for k in range(145):
            a = 2.0 * math.pi * k / 144
            q = (rho * math.cos(a), rho * math.sin(a), z)
            d, uv = surface.near(q, uv)  # from the last foot: at least the distance
            if d > 1.5 * m.max_deviation_m * 1000.0:
                d, uv = surface.near(q)  # across the seam: searched afresh
            assert d <= 1.5 * m.max_deviation_m * 1000.0
    true = _canal_deviation(f, lambda t: (8.0 * math.cos(t), 8.0 * math.sin(t), 18.0), 2.0)
    assert true <= 1.05 * m.max_deviation_m * 1000.0


def test_a_blend_stopping_short_of_its_face_is_refused_by_the_checks(monkeypatch):
    """The partial loft the export made before, forced: points of the edges between their
    vertices lie off the blend, which the writer's own checks refuse and these tests'
    checker finds."""
    from solidseas.step import blend, checks

    def short(loops, param, period):
        return False, -math.pi, 5.0 * math.pi / 6.0, math.pi / 6.0  # as the old span and margin gave

    monkeypatch.setattr(blend.Blends, "_cover", staticmethod(short))
    with pytest.raises(NotRepresentableError) as exc:
        step_transmit(_numbered(X.rounded_cylinder()))
    (b,) = exc.value.bodies
    assert b.reason == "check_failed" and "from its face's surface" in b.message
    monkeypatch.setattr(checks, "_check_edge_on_faces", lambda *a: None)
    got = check(X.rounded_cylinder())
    assert [k for k, *_ in got["geometry"]["beyond"]] and {k for k, *_ in got["geometry"]["beyond"]} == {
        "edge_surface"
    }
    assert got["geometry"]["edge_surface_max"] > 0.1  # mm


@pytest.mark.parametrize("theta", [30, 50])
def test_a_blends_deviation_is_measured_where_it_peaks(theta, monkeypatch):
    """Round an elliptical spine the loft's error peaks away from the middle of its spans:
    measured at the middle alone, the deviation of the cut at 50 degrees was reported as
    93 nm where it is 224 nm. Measured along each span, the reported deviation is the true
    one, as these tests' own evaluators find it."""
    from solidseas.tessellate import blend

    xt, (C, A, B, a, b) = X.tilted_cylinder(degrees=theta)

    def spine(t):
        return tuple(1000.0 * (C[i] + a * math.cos(t) * A[i] + b * math.sin(t) * B[i]) for i in range(3))

    got = check(xt)
    assert_sound(got)  # the ring of blend, cut in two at its seams: each half compared with the drawn blend
    m = got["model"]
    true = _canal_deviation(got["file"], spine, 2.0) / 1000.0
    assert 0.97 * true <= m.max_deviation_m <= 1e-7
    assert m.uncertainty_m >= 1.5 * true
    monkeypatch.setattr(blend, "ALONG", (0.5,))  # the middle alone, as before
    m = step_transmit(_numbered(X.tilted_cylinder(degrees=theta)[0]))
    f = T.read(step_bytes(m, time_stamp=STAMP))
    assert m.max_deviation_m < 0.7 * _canal_deviation(f, spine, 2.0) / 1000.0


# --------------------------------------------------------------------------- spun surfaces
def spun_cylinder(r=0.005, h=0.02, profile_kind="line"):
    """The synthetic cylinder with its side a SPUN_SURF: a straight B-curve parallel to the
    axis turned round it. Parasolid's natural normal there points inwards (profile(u) turned
    by v), so the face's sense is '-'. ``profile_kind`` "circle" or "across" puts another
    profile in its place (a circle centred on the axis, a straight B-curve across it), whose
    surface the face does not lie on, for the refusals."""
    b = X.XtBuilder()
    bottom = b.edge(b.circle((0, 0, 0), X.Z, X.X, r))
    top = b.edge(b.circle((0, 0, h), X.Z, X.X, r))
    # the profile: a straight B-curve up the side, a little past both ends
    ends = [r, 0.0, -0.001, r, 0.0, h + 0.001]
    if profile_kind == "across":
        ends = [r, 0.0, 0.0, -r, 0.0, h]
    verts = b.node(45, vertices=ends)
    knots = b.node(128, knots=[0.0, 1.0])
    mult = b.node(127, mult=[2, 2])
    nc = b.node(
        136, degree=1, n_vertices=2, vertex_dim=3, bspline_vertices=verts, knot_mult=mult, knots=knots
    )
    profile = b.node(134, nurbs=nc, sense="+")
    if profile_kind == "circle":
        profile = b.circle((0, 0, h / 2), (0.0, 1.0, 0.0), X.X, r)
    spun = b.node(
        68, profile=profile, base=(0.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0), x_axis=(1.0, 0.0, 0.0), sense="+"
    )
    b.face(spun, "-", [[(bottom, "+")], [(top, "-")]])
    b.face(b.plane((0, 0, 0), X.Z, X.X), "-", [[(bottom, "-")]])
    b.face(b.plane((0, 0, h), X.Z, X.X), "+", [[(top, "+")]])
    return b.body([bottom, top])


def test_a_spun_surface_is_a_revolution_whose_normal_turns_round():
    got = check(spun_cylinder())
    assert_sound(got)
    f = got["file"]
    assert len(f.of("SURFACE_OF_REVOLUTION")) == 1 and got["model"].exact
    faces = [e for e in f.of("ADVANCED_FACE") if f.get(e.params[2]).name == "SURFACE_OF_REVOLUTION"]
    assert len(faces) == 2  # the side, cut at its seams: the profile turned to u = 0 and u = pi
    assert [face.params[3] for face in faces] == ["T", "T"]  # ISO's natural normal is the outward one


@pytest.mark.parametrize(
    "kind, why", [("circle", "symmetric about the axis"), ("across", "crosses the axis")]
)
def test_a_spun_surface_that_covers_itself_twice_is_refused(kind, why):
    """A profile symmetric about the axis (a circle centred on it: a sphere swept twice) or
    crossing it gives each point of the surface two parameters with opposite natural
    normals: a reader could take the face either way round."""
    with pytest.raises(NotRepresentableError) as exc:
        step_transmit(_numbered(spun_cylinder(profile_kind=kind)))
    (body,) = exc.value.bodies
    assert body.reason == "unsupported_surface" and why in body.message


def test_the_oracle_catches_a_spun_surface_written_with_parasolids_normal(monkeypatch):
    from solidseas.step import mapper

    real = mapper.BodyMapper._surface

    def upstream(self, s):
        got = real(self, s)
        if s.type == 68:
            got.match = True
        return got

    monkeypatch.setattr(mapper.BodyMapper, "_surface", upstream)
    got = check(spun_cylinder())
    # one face: written the wrong way round, its two rings lie on the wrong sides of each
    # other for a cut at its seams, which is not made
    assert len(got["orientation"]["disagree"]) == 1 and got["model"].counts["split_faces"] == 0
