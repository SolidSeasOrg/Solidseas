"""Curve evaluators for the XT curve types an edge can lie on.

Each evaluator has the parametrisation XT itself uses (``docs/FORMAT.md``
10.8): a LINE is ``P + t D``, a CIRCLE ``C + r (cos t X + sin t Y)`` with
``Y = N x X``, an ELLIPSE ``C + a cos t X + b sin t Y``, a B_CURVE a B-spline
(homogeneous when rational), an SP_CURVE a surface evaluated along a B-spline
in its (u, v), a TRIMMED_CURVE its basis between ``parm_1`` and ``parm_2``,
and an INTERSECTION the polyline through its chart's points, parametrised by
point index. ``sense`` is the curve's own sense field: an edge runs in its
curve's natural direction times that sense.
"""

import math

from . import nurbs
from ._vec import TWO_PI, add, atan2, combo, cos, dist, dot, mul, orthonormal, sin, sub
from .topology import (
    B_CURVE,
    BLENDED_EDGE,
    BSPLINE_VERTICES,
    CHART,
    CIRCLE,
    CURVE_TYPES,
    ELLIPSE,
    INTERSECTION,
    KNOT_MULT,
    KNOT_SET,
    LINE,
    NURBS_CURVE,
    SP_CURVE,
    SURFACE_TYPES,
    TRIMMED_CURVE,
    FaceFailed,
    Topology,
)

MAX_CHART_POINTS = 1_000_000


class Curve:
    name = "CURVE"
    sense = 1
    period: float | None = None
    lo: float | None = None
    hi: float | None = None

    def point(self, t: float):
        raise NotImplementedError

    def d1(self, t: float):
        """The point and the first derivative, by central differences unless overridden."""
        h = 1e-7 * max(1.0, abs(t))
        a, b = self.point(t - h), self.point(t + h)
        return self.point(t), mul(sub(b, a), 0.5 / h)

    def param(self, p, clock=None) -> float:
        """The parameter of the point of the curve nearest ``p`` (within its range)."""
        raise NotImplementedError

    def radius(self) -> float | None:
        """The smallest radius of curvature, where it is known in closed form."""
        return None


class Line(Curve):
    name = "LINE"

    def __init__(self, P, D, sense: int) -> None:
        self.P, self.D, self.sense = P, D, sense

    def point(self, t):
        return combo(self.P, self.D, t, self.D, 0.0)

    def d1(self, t):
        return self.point(t), self.D

    def param(self, p, clock=None):
        return dot(sub(p, self.P), self.D) / dot(self.D, self.D)


class Conic(Curve):
    """A circle (``a == b``) or an ellipse."""

    period = TWO_PI
    lo, hi = 0.0, TWO_PI

    def __init__(self, name, C, N, X, a: float, b: float, sense: int) -> None:
        frame = orthonormal(N, X)
        if frame is None or not (a > 0.0 and b > 0.0):
            raise FaceFailed("bad_geometry", f"a degenerate {name.lower()}")
        self.name, self.C, self.N, self.X, self.Y = name, C, frame[0], frame[1], frame[2]
        self.a, self.b, self.sense = a, b, sense

    def point(self, t):
        return combo(self.C, self.X, self.a * cos(t), self.Y, self.b * sin(t))

    def d1(self, t):
        c, s = cos(t), sin(t)
        return combo(self.C, self.X, self.a * c, self.Y, self.b * s), combo(
            (0.0, 0.0, 0.0), self.X, -self.a * s, self.Y, self.b * c
        )

    def param(self, p, clock=None):
        q = sub(p, self.C)
        return atan2(dot(q, self.Y) / self.b, dot(q, self.X) / self.a)

    def radius(self):
        return min(self.a, self.b) ** 2 / max(self.a, self.b)

    def extent(self):
        """The two corners of the curve's own box."""
        e = tuple(math.hypot(self.a * self.X[i], self.b * self.Y[i]) for i in range(3))
        return [add(self.C, e), sub(self.C, e)]


def _bspline(topo: Topology, nc, dims: tuple[int, ...]) -> nurbs.BSplineCurve:
    degree = topo.get(nc, "degree")
    n = topo.get(nc, "n_vertices")
    dim = topo.get(nc, "vertex_dim")
    rational = bool(topo.get(nc, "rational", 0))
    if not isinstance(degree, int) or not isinstance(n, int) or not isinstance(dim, int):
        raise FaceFailed("bad_geometry", "a B-curve's sizes are not integers")
    if dim - (1 if rational else 0) not in dims:
        raise FaceFailed("bad_geometry", f"a B-curve of dimension {dim}")
    verts = topo.ref(nc, "bspline_vertices", (BSPLINE_VERTICES,), required=True)
    mult = topo.ref(nc, "knot_mult", (KNOT_MULT,), required=True)
    knots = topo.ref(nc, "knots", (KNOT_SET,), required=True)
    U = nurbs.knot_vector(topo.get(knots, "knots"), topo.get(mult, "mult"), n, degree)
    cps = nurbs.control_points(topo.get(verts, "vertices"), n, dim, rational)
    periodic = bool(topo.get(nc, "periodic", 0)) or bool(topo.get(nc, "closed", 0))
    return nurbs.BSplineCurve(degree, cps, U, rational, periodic)


def bspline_of(topo: Topology, node, dims=(3,)) -> nurbs.BSplineCurve:
    """The B-spline of a B_CURVE node."""
    nc = topo.ref(node, "nurbs", (NURBS_CURVE,), required=True)
    return _bspline(topo, nc, dims)


class BCurve(Curve):
    name = "B_CURVE"

    def __init__(self, spline: nurbs.BSplineCurve, sense: int) -> None:
        self.s, self.sense = spline, sense
        self.lo, self.hi, self.period = spline.lo, spline.hi, spline.period

    def point(self, t):
        return self.s.point(t)

    def d1(self, t):
        return self.s.d1(t)

    def spans(self, t0, t1):
        return self.s.spans(t0, t1)

    def param(self, p, clock=None):
        return _invert(self, p, self.lo, self.hi, 8 * max(2, self.s.n - self.s.p), clock)


class SPCurve(Curve):
    """A curve in a surface's (u, v): ``uv(t)`` in the file's parametrisation."""

    name = "SP_CURVE"

    def __init__(self, surface, surface_node, spline: nurbs.BSplineCurve, sense: int) -> None:
        self.surface, self.surface_node, self.s, self.sense = surface, surface_node, spline, sense
        self.lo, self.hi, self.period = spline.lo, spline.hi, spline.period

    def uv(self, t):
        u, v = self.s.point(t)
        return u, v

    def point(self, t):
        u, v = self.s.point(t)
        return self.surface.point(*self.surface.from_file(u, v))

    def spans(self, t0, t1):
        return self.s.spans(t0, t1)

    def param(self, p, clock=None):
        return _invert(self, p, self.lo, self.hi, 8 * max(2, self.s.n - self.s.p), clock)


class Trimmed(Curve):
    name = "TRIMMED_CURVE"

    def __init__(self, basis: Curve, t1: float, t2: float, p1, p2, sense: int) -> None:
        self.basis, self.t1, self.t2, self.p1, self.p2, self.sense = basis, t1, t2, p1, p2, sense

    def point(self, t):
        return self.basis.point(t)

    def d1(self, t):
        return self.basis.d1(t)


class Polyline(Curve):
    """An INTERSECTION: the chart's points, parametrised by index."""

    name = "INTERSECTION"

    def __init__(self, pts, sense: int, chordal_error: float) -> None:
        self.pts, self.sense, self.chordal_error = pts, sense, chordal_error
        self.lo, self.hi = 0.0, float(len(pts) - 1)
        # A closed chart can end a few microns from where it starts: closed when the gap is
        # small beside its segments (open charts end at least a segment apart).
        longest = max((dist(a, b) for a, b in zip(pts, pts[1:], strict=False)), default=0.0)
        self.closed = len(pts) > 2 and dist(pts[0], pts[-1]) <= 0.05 * longest

    def point(self, t):
        n = len(self.pts) - 1
        t = min(max(t, 0.0), float(n))
        i = min(int(t), n - 1)
        f = t - i
        a, b = self.pts[i], self.pts[i + 1]
        return (a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]), a[2] + f * (b[2] - a[2]))

    def param(self, p, clock=None):
        """The position of the point of the polyline nearest ``p``: segment index plus
        the fraction along it."""
        best, where = math.inf, 0.0
        pts = self.pts
        for i in range(len(pts) - 1):
            if clock is not None:
                clock.tick()
            a, b = pts[i], pts[i + 1]
            ab = sub(b, a)
            ll = dot(ab, ab)
            f = 0.0 if ll == 0.0 else min(1.0, max(0.0, dot(sub(p, a), ab) / ll))
            q = combo(a, ab, f, ab, 0.0)
            d = dist(p, q)
            if d < best:
                best, where = d, i + f
        return where


def _invert(curve: Curve, p, lo: float, hi: float, samples: int, clock=None) -> float:
    """The parameter of the point of ``curve`` nearest ``p``: the nearest of ``samples``
    points, then Gauss-Newton steps."""
    samples = max(8, min(samples, 2000))
    best_t, best = lo, math.inf
    for i in range(samples + 1):
        if clock is not None:
            clock.tick()
        t = lo + (hi - lo) * i / samples
        d = dist(curve.point(t), p)
        if d < best:
            best, best_t = d, t
    t = best_t
    for _ in range(30):
        q, dq = curve.d1(t)
        g = dot(dq, dq)
        if g <= 0.0:
            break
        step = dot(sub(p, q), dq) / g
        nt = t + step
        if curve.period is None:
            nt = min(max(nt, lo), hi)
        if abs(nt - t) <= 1e-14 * max(1.0, abs(t)):
            t = nt
            break
        t = nt
    if dist(curve.point(t), p) > best:
        return best_t
    return t


def make_curve(topo: Topology, node, surface_of, curve_of) -> Curve:
    """The evaluator of a curve node. ``surface_of(node)`` and ``curve_of(node)`` build
    the surface of an SP-curve and the basis of a trimmed curve, cached and guarded
    against a curve that refers to itself. Raises :class:`FaceFailed` for an
    unsupported or damaged curve."""
    t = node.type
    sense = topo.sense(node)
    if t == LINE:
        P, D = topo.vector(node, "pvec"), topo.vector(node, "direction")
        if not dot(D, D) > 1e-24:
            raise FaceFailed("bad_geometry", "a line has no direction")
        return Line(P, D, sense)
    if t == CIRCLE:
        r = topo.number(node, "radius")
        C, N, X = topo.vector(node, "centre"), topo.unit(node, "normal"), topo.vector(node, "x_axis")
        return Conic("CIRCLE", C, N, X, r, r, sense)
    if t == ELLIPSE:
        a, b = topo.number(node, "major_radius"), topo.number(node, "minor_radius")
        C, N, X = topo.vector(node, "centre"), topo.unit(node, "normal"), topo.vector(node, "x_axis")
        return Conic("ELLIPSE", C, N, X, a, b, sense)
    if t == B_CURVE:
        return BCurve(bspline_of(topo, node), sense)
    if t == SP_CURVE:
        snode = topo.ref(node, "surface", SURFACE_TYPES, required=True)
        if snode.type == BLENDED_EDGE:
            # Its (u, v) are Parasolid's own parameters of the blend, which are not known
            # (the blend is drawn from an approximation with parameters of its own).
            raise FaceFailed("unsupported_curve", "an SP-curve on a rolling blend")
        bc = topo.ref(node, "b_curve", (B_CURVE,), required=True)
        return SPCurve(surface_of(snode), snode, bspline_of(topo, bc, (2,)), sense)
    if t == TRIMMED_CURVE:
        bnode = topo.ref(node, "basis_curve", CURVE_TYPES, required=True)
        return Trimmed(
            curve_of(bnode),
            topo.number(node, "parm_1"),
            topo.number(node, "parm_2"),
            topo.vector(node, "point_1"),
            topo.vector(node, "point_2"),
            sense,
        )
    if t == INTERSECTION:
        chart = topo.ref(node, "chart", (CHART,), required=True)
        hv = topo.get(chart, "hvec")
        if not isinstance(hv, list) or len(hv) < 2:
            raise FaceFailed("bad_geometry", "an intersection curve has no chart")
        if len(hv) > MAX_CHART_POINTS:
            raise FaceFailed("edge_too_long", f"an intersection chart of {len(hv)} points")
        pts = []
        for h in hv:
            if not isinstance(h, tuple) or len(h) < 3 or not all(math.isfinite(x) for x in h[:3]):
                raise FaceFailed("non_finite", "a chart point is not finite")
            pts.append((h[0], h[1], h[2]))
        err = topo.get(chart, "chordal_error", 0.0)
        err = err if isinstance(err, float) and math.isfinite(err) and err > 0 else 0.0
        return Polyline(pts, sense, err)
    raise FaceFailed("unsupported_curve", node.tname)


def curve_extent(curve: Curve):
    """Points that bound a closed curve without vertices (a circle's box), or []."""
    if isinstance(curve, Conic):
        return curve.extent()
    if isinstance(curve, Trimmed):
        return [curve.p1, curve.p2]
    return []
