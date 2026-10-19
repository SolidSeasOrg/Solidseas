# Rolling blends approximated by rational B-spline surfaces, deviation measured. Shared by
# the tessellator and the STEP export.
#
# Derived work. The construction (the spine sampled, the feet of the sphere on its two
# supports, an exact circular arc between the feet at each spine point as a rational
# quadratic row, the rows lofted cubically along the spine through their homogeneous
# control points, sections inserted where the error is largest), the cliff-edge
# support (a pipe round the edge's curve) and the offset supports come from
#   BlinkingSun/sldprt2step, files sldprt2step_lib/step/mapper.py (blend_surface,
#   spine_samples, curve_support, _CurveSupport, _OffsetEval, _section_angle,
#   _degenerate_arc, blend_boundary_curve) and sldprt2step_lib/xt/geom.py (arc_nurbs,
#   interpolate_cubic_surface_rows, _col_tangent)
#   https://github.com/BlinkingSun/sldprt2step, commit fa954124f4f126e0c465c8f96454978ac80b812e
#   Licensed under the Apache License, Version 2.0. sldprt2step is a port of
#   open-sld-to-step 0.1.0 (Apache-2.0). See NOTICE in the SolidSeas repository.
# Modified for SolidSeas (2026-10-03, 2026-10-04): the spine's extent taken from the
# faces on the blend, so the surface covers them, and a blend whose faces go round a
# closed spine lofted round the whole of it, closing on itself; the feet found by
# SolidSeas' seeded Newton projections (upstream searched a 41 x 41 grid); the offsets'
# signs checked against the spine rather than assumed; the deviation measured as the
# distance from the surface to the true canal surface (the spine's nearest point at the
# sphere's radius) at seven points along each span and nine across, and the surface's
# sides against the true lines of contact, sections inserted until within the target,
# up to 1,024 of them; a face's orientation on the blend taken from the faces it meets
# tangentially, since Parasolid's own parametrisation of a blend is not known; the
# blend's boundary curves are the surface's own iso-curves; moved here from
# solidseas.step.blend, so that the tessellator draws blends with the export's surface
# (2026-10-04).
"""Rolling blends (BLENDED_EDGE): a B-spline surface in place of the exact canal
surface, which neither STEP nor the tessellator's evaluators have.

A rolling blend is the surface a sphere of radius r sweeps while it touches its
two supports. Its centre runs along the spine, which lies on both supports offset by
the blend's ``range`` (``docs/FORMAT.md`` 10.9). At each spine point the blend's
section is the circular arc from the sphere's foot on one support to its foot on the
other: exact, as a rational quadratic B-spline. The sections are lofted along the
spine by a C1 cubic through their homogeneous control points, so each section stays
an exact arc and only the surface between sections is approximated. Sections are
added where the surface strays from the canal surface by more than the target; the
deviation reported is the largest measured, at the fractions of every span in
:data:`ALONG` and nine points across each, together with how far the surface's two
sides lie from the true lines where the sphere touches its supports.

On a closed spine (a circle, an ellipse, a closed B-curve) the faces' loops are
followed round it: where one goes round, or they leave little of the spine
uncovered, the surface is lofted round the whole spine, its last section its first,
so it closes on itself; otherwise over the faces' extent along the spine and a
margin.

A cliff-edge blend (``blend_type`` E) rolls the sphere between a face and an edge: that
support is a degenerate blend of no range, whose spine is the edge's curve, and the
sphere touches the curve itself.

Parasolid's own (u, v) of a blend is not known, so a face's side on the
approximation is taken from a face it meets tangentially (:meth:`Blends.same_sense`),
and a curve given in the blend's (u, v), an SP-curve, cannot be evaluated.
"""

import math
from collections import Counter

from . import nurbs
from ._vec import add, dist, dot, mul, norm, sub
from .curves import BCurve, Polyline, Trimmed
from .fit import MAX_POINTS, QUARTERS, FitFailed, Foot, dedupe, fit_nodes, hermite_mid, refine
from .surfaces import BSurface
from .topology import BLEND_BOUND, BLENDED_EDGE, EDGE, INTERSECTION, Clock, FaceFailed, TimeUp

# Errors a damaged blend can raise in the arithmetic that the checks before it did not
# foresee: the tessellator refuses that blend (``degenerate``) rather than the body.
UNFORESEEN = (ZeroDivisionError, OverflowError, ValueError, IndexError, KeyError, TypeError, AttributeError)
MAX_SECTIONS = 1024
FIRST_SECTIONS = 24
ROUNDS = 8
ACROSS = 9  # points across a section where the deviation is measured
# Where along each span the deviation is measured. The loft's error vanishes at the exact
# sections at both ends; between them it peaks at the middle where the spans are even and
# the section keeps its angle, and as near as a fifth of the span from either end where
# they are not (measured at the middle alone, a blend's deviation was reported at less
# than half its true value).
ALONG = (0.15, 0.25, 0.35, 0.5, 0.65, 0.75, 0.85)
MARGIN = 0.02  # of the faces' extent along the spine, added at each end


def _densified(pts, step: float):
    """Points of edges as they were sampled (each edge's run of points), with points
    added along each straight stretch so that none is longer than ``step``."""
    out = []
    for run in pts:
        out.append(run[0])
        for a, b in zip(run, run[1:], strict=False):
            k = int(dist(a, b) / step)
            for i in range(1, k + 1):
                out.append(_lerp(a, b, i / (k + 1)))
            out.append(b)
    return out


def _lerp(a, b, f):
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f)


def _unit(v):
    n = norm(v)
    return (v[0] / n, v[1] / n, v[2] / n) if n > 1e-300 else None


class CurveFoot:
    """A curve standing in for a support (a cliff edge): the nearest point of the curve
    and the direction from it towards the point asked about."""

    def __init__(self, curve, lo: float, hi: float, clock) -> None:
        self.c, self.lo, self.hi, self.clock = curve, lo, hi, clock

    def __call__(self, p):
        t = nearest(self.c, p, self.c.param(p, self.clock))
        if self.c.period is None:
            t = min(max(t, self.lo), self.hi)
        q = self.c.point(t)
        n = _unit(sub(p, q))
        return q, n


def nearest(curve, p, t: float, iters: int = 30) -> float:
    """The parameter of the point of ``curve`` nearest ``p``, by Newton's method on
    (C(t) - p) . C'(t) from ``t``."""
    for _ in range(iters):
        q, d = curve.d1(t)
        h = 1e-6 * (1.0 + abs(t))
        _q1, d1 = curve.d1(t + h)
        _q0, d0 = curve.d1(t - h)
        dd = mul(sub(d1, d0), 0.5 / h)
        r = sub(q, p)
        f = dot(r, d)
        fp = dot(d, d) + dot(r, dd)
        if not fp > 0.0:
            break
        step = f / fp
        t -= step
        if abs(step) <= 1e-15 * (1.0 + abs(t)):
            break
    return t


class OffsetFoot:
    """A support offset by ``d`` along its natural normal times its sense."""

    def __init__(self, foot, d: float) -> None:
        self.foot, self.d = foot, d

    def __call__(self, p):
        q, n = self.foot(p)
        if n is None:
            return q, None
        return add(q, mul(n, self.d)), n


def arc_row(centre, f0, f1, nseg: int):
    """The exact arc about ``centre`` from ``f0`` to ``f1`` (the shorter way), as
    homogeneous control points of a rational quadratic of ``nseg`` segments; None when
    the feet do not make an arc."""
    a, b = sub(f0, centre), sub(f1, centre)
    r = 0.5 * (norm(a) + norm(b))
    x = _unit(a)
    if x is None or not r > 0.0:
        return None
    y = sub(b, mul(x, dot(b, x)))
    yn = _unit(y)
    if yn is None or norm(y) < 1e-9 * r:
        return None
    ang = math.atan2(dot(b, yn), dot(b, x))
    if not 0.0 < ang < math.pi:
        return None
    seg = ang / nseg
    w = math.cos(seg / 2.0)

    def pt(t, rr):
        return add(centre, add(mul(x, rr * math.cos(t)), mul(yn, rr * math.sin(t))))

    cps = []
    for k in range(nseg):
        b0 = k * seg
        if k == 0:
            p = pt(b0, r)
            cps.append((p[0], p[1], p[2], 1.0))
        m = pt(b0 + seg / 2.0, r / w)
        cps.append((m[0] * w, m[1] * w, m[2] * w, w))
        e = pt(b0 + seg, r)
        cps.append((e[0], e[1], e[2], 1.0))
    return cps, ang


def arc_knots(nseg: int) -> list[float]:
    knots = [0.0, 0.0, 0.0]
    for k in range(1, nseg):
        knots.extend([k / nseg] * 2)
    return knots + [1.0, 1.0, 1.0]


def loft(rows, params, nseg: int, closed: bool = False) -> nurbs.BSplineSurface:
    """Rows of homogeneous control points (one exact arc a spine point) lofted along u by
    a C1 cubic through them (Catmull-Rom tangents, chord-length ``params``), as one
    rational B-spline surface: u along the spine, v across the section. ``closed``: the
    last row is the first (a blend round a closed spine), and the tangent there is taken
    across the seam, so the surface closes smoothly."""
    n = len(rows)
    nv = len(rows[0])
    dim = 4

    def tangent(i):
        out = []
        for j in range(nv):
            if closed and n > 2 and i in (0, n - 1):
                a, b, c = rows[n - 2][j], rows[0][j], rows[1][j]
                ha, hb = params[n - 1] - params[n - 2], params[1] - params[0]
                out.append(
                    tuple(((c[d] - b[d]) / hb * ha + (b[d] - a[d]) / ha * hb) / (ha + hb) for d in range(dim))
                )
            elif n == 2:
                a, b = rows[0][j], rows[1][j]
                h = params[1] - params[0]
                out.append(tuple((b[d] - a[d]) / h for d in range(dim)))
            elif i == 0:
                a, b, c = rows[0][j], rows[1][j], rows[2][j]
                ha, hb = params[1] - params[0], params[2] - params[1]
                out.append(
                    tuple(
                        (b[d] - a[d]) / ha * (2 * ha + hb) / (ha + hb) - (c[d] - b[d]) / hb * ha / (ha + hb)
                        for d in range(dim)
                    )
                )
            elif i == n - 1:
                a, b, c = rows[n - 2][j], rows[n - 1][j], rows[n - 3][j]
                hb, ha = params[n - 1] - params[n - 2], params[n - 2] - params[n - 3]
                out.append(
                    tuple(
                        (b[d] - a[d]) / hb * (2 * hb + ha) / (ha + hb) - (a[d] - c[d]) / ha * hb / (ha + hb)
                        for d in range(dim)
                    )
                )
            else:
                a, b, c = rows[i - 1][j], rows[i][j], rows[i + 1][j]
                ha, hb = params[i] - params[i - 1], params[i + 1] - params[i]
                out.append(
                    tuple(((c[d] - b[d]) / hb * ha + (b[d] - a[d]) / ha * hb) / (ha + hb) for d in range(dim))
                )
        return out

    tans = [tangent(i) for i in range(n)]
    grid = [rows[0]]
    U = [params[0]] * 4
    for i in range(n - 1):
        h = params[i + 1] - params[i]
        p0, p1, t0, t1 = rows[i], rows[i + 1], tans[i], tans[i + 1]
        grid.append([tuple(p0[j][d] + t0[j][d] * h / 3.0 for d in range(dim)) for j in range(nv)])
        grid.append([tuple(p1[j][d] - t1[j][d] * h / 3.0 for d in range(dim)) for j in range(nv)])
        grid.append(p1)
        if i < n - 2:
            U.extend([params[i + 1]] * 3)
    U.extend([params[-1]] * 4)
    for row in grid:
        for c in row:
            if not c[3] > 0.0:
                raise FitFailed("fit_failed", "a blend's lofted weights are not positive")
    return nurbs.BSplineSurface(3, 2, grid, U, arc_knots(nseg), True, False, False)


class BlendFit:
    """A blend's approximation: the surface (metres), its evaluator, the deviation
    measured, the sphere's radius and how to find the spine point nearest a point."""

    def __init__(self, spline, deviation, radius, spine_near) -> None:
        self.spline = spline
        self.ev = BSurface(spline, 1e-9)
        self.deviation = deviation
        self.radius = radius
        self.spine_near = spine_near


class Blends:
    """The blends of one transmit's bodies, each fitted once, on demand (:meth:`fitted`).

    ``sampler`` (an :class:`~.edges.EdgeSampler`) samples the edges of the faces on a
    blend, whose points' coordinates are in the list ``points``; ``geom`` evaluates the
    supports; ``tol`` is every fit's target and ``max_deviation`` how far a blend's
    faces may run past the last section where its sphere still touches both supports
    (that overrun is part of the deviation). ``along`` and ``across`` say where each span
    is measured (None: :data:`ALONG` and :data:`ACROSS`, as the export measures it), and
    ``slide`` how close to square a measured point and the spine point found for it are
    on an intersection spine (None: 1e-11 m). ``reach`` is each foot's (:class:`.Foot`).
    ``give_up``: a blend some span of which cannot be measured is refused at the first such
    span, rather than after every round of refinement. ``budget``: the seconds one blend's
    fit may take; when they run out, the best round measured so far is kept if it is
    within ``max_deviation``, and the blend is refused (``fit_failed``) if it is not.
    None: as long as ``clock`` allows. ``facts`` counts how often the conventions in
    ``docs/FORMAT.md`` 10.9 were met. A subclass hears of each approximation it makes
    through :meth:`noted`."""

    def __init__(
        self,
        topo,
        geom,
        sampler,
        points,
        clock,
        tol: float,
        max_deviation: float,
        facts=None,
        along: tuple[float, ...] | None = None,
        across: int | None = None,
        reach: float = 1.0,
        slide: float | None = None,
        give_up: bool = False,
        budget: float | None = None,
    ):
        self.topo, self.geom, self.sampler, self.points, self.clock = topo, geom, sampler, points, clock
        self.tol, self.max_deviation = tol, max_deviation
        self.along, self.across, self.reach, self.slide = along, across, reach, slide
        self.give_up, self.budget = give_up, budget
        self.facts = Counter() if facts is None else facts
        self.fits: dict[int, BlendFit | FitFailed] = {}
        self._building: set[int] = set()
        self._charts: dict[int, tuple] = {}
        self._on: dict[int, list] | None = None
        self.extra = 0.0
        self._best: tuple | None = None  # BlendFit's arguments for the best round so far (budget)

    def noted(self, cls: str, deviation: float, what: str) -> None:
        """An approximation made along the way (a cliff edge's curve): the export counts it
        and refuses one beyond its limit by raising :class:`FitFailed`."""

    # ------------------------------------------------------------------ the supports
    def _support(self, snode):
        """A foot function for a support: a surface's, an approximated blend's, or a
        cliff edge's curve."""
        topo = self.topo
        if snode.type == BLENDED_EDGE:
            rng = topo.get(snode, "range", [0.0, 0.0])
            if isinstance(rng, list) and all(isinstance(x, float) and abs(x) < 1e-12 for x in rng):
                spine = topo.ref(snode, "spine", required=True)
                if spine.type == INTERSECTION:  # the cliff edge's curve, fitted first
                    spline, dev = self.fit_chart(spine)
                    self.extra = max(self.extra, dev)
                    ev = BCurve(spline, 1)
                else:
                    ev = self._spine(spine)
                lo, hi = (ev.lo, ev.hi) if ev.lo is not None else (-math.inf, math.inf)
                return CurveFoot(ev, lo, hi, self.clock), True
            bf = self.fitted(snode)
            self.extra = max(self.extra, bf.deviation)
            return Foot(bf.ev, self.clock, self.reach), False
        return Foot(self.geom.surface(snode), self.clock, self.reach), False

    def _spine(self, node):
        """The evaluator of a spine (or of a cliff edge's curve), which must find the point
        nearest a point: a trimmed curve, which cannot, is refused."""
        ev = self.geom.curve(node)
        if isinstance(ev, Trimmed):
            raise FitFailed("unsupported_curve", "a blend whose spine is a trimmed curve")
        return ev

    def fit_chart(self, node):
        """A whole INTERSECTION curve (a cliff edge's) fitted through its chart, refined
        onto its two surfaces: (B-spline, deviation). Cached a node."""
        got = self._charts.get(node.index)
        if got is not None:
            return got
        topo = self.topo
        surfaces = topo.get(node, "surface", [])
        snodes = [topo.nodes.get(i) for i in surfaces] if isinstance(surfaces, list) else []
        if len(snodes) != 2 or any(s is None or s.type in (BLENDED_EDGE, BLEND_BOUND) for s in snodes):
            raise FitFailed("unsupported_surface", "a cliff edge on a curve that cannot be fitted")
        try:
            feet = [Foot(self.geom.surface(s), self.clock, self.reach) for s in snodes]
            pts = list(self.geom.curve(node).pts)
        except FaceFailed as exc:
            why = f"a cliff edge's curve cannot be evaluated: {exc}"
            raise FitFailed("unsupported_surface", why) from None
        if len(pts) > MAX_POINTS:
            k = math.ceil(len(pts) / MAX_POINTS)
            pts = pts[::k] + ([pts[-1]] if (len(pts) - 1) % k else [])
        nodes = []
        for p in pts:
            r = refine(p, feet)
            if r is not None:
                nodes.append((r[0], r[1], None))
        if len(nodes) < 2:
            raise FitFailed("fit_failed", "a cliff edge's curve could not be placed on its surfaces")
        for i in range(len(nodes)):
            ref = sub(nodes[min(i + 1, len(nodes) - 1)][0], nodes[max(i - 1, 0)][0])
            if dot(nodes[i][1], ref) < 0.0:
                nodes[i] = (nodes[i][0], mul(nodes[i][1], -1.0), None)

        def exact_mid(na, nb):
            m = hermite_mid(na[0], na[1], nb[0], nb[1])
            r = refine(m, feet)
            if r is None or dist(r[0], m) > 0.25 * dist(na[0], nb[0]):
                return None
            t = r[1] if dot(r[1], sub(nb[0], na[0])) >= 0.0 else mul(r[1], -1.0)
            return r[0], t, None

        def measure(fit, _nodes):
            spans = []
            U = fit.U
            for k in range(3, len(U) - 4, 3):
                self.clock.check()
                worst = 0.0
                for f in QUARTERS:
                    p = fit.point(U[k] + (U[k + 1] - U[k]) * f)
                    r = refine(p, feet)
                    worst = max(worst, dist(r[0], p) if r is not None else math.inf)
                spans.append(worst)
            return spans

        fit, dev, _n = fit_nodes(dedupe(nodes), exact_mid, measure, self.tol, self.clock, "cliff edge curve")
        self.noted("INTERSECTION", dev, "cliff edge curve")
        self._charts[node.index] = (fit, dev)
        return fit, dev

    # ------------------------------------------------------------------ the spine's extent
    def _faces_on(self, s):
        """The faces whose surface is ``s``, in the transmit's order (an index built once)."""
        if self._on is None:
            on: dict[int, list] = {}
            for f in self.topo.xt.nodes:
                if f.type == 14:
                    k = self.topo.get(f, "surface", 0)
                    if isinstance(k, int):
                        on.setdefault(k, []).append(f)
            self._on = on
        return self._on.get(s.index, [])

    def _face_points(self, s):
        """The edges of every face on blend surface ``s`` as runs of points (metres), an
        isolated vertex a run of one."""
        topo = self.topo
        pts = []
        for f in self._faces_on(s):
            for lp in topo.loops(f):
                for fin in topo.fins(lp):
                    e = topo.ref(fin, "edge", (EDGE,))
                    if e is None:
                        v = topo.ref(fin, "vertex")
                        if v is not None:
                            pts.append([topo.point_of(v)])
                        continue
                    try:
                        sm = self.sampler.samples(e)
                    except FaceFailed:
                        continue
                    pts.append([self.points[i] for i in sm.ids])
        return [r for r in pts if r]

    def _face_loops(self, s):
        """The loops of every face on blend surface ``s``: ``[(points, whole)]``, the
        points in order round the loop (metres), an isolated vertex a loop of one point,
        ``whole`` false where an edge of the loop could not be sampled (it is left out,
        and the loop cannot be followed round)."""
        topo = self.topo
        loops = []
        for f in self._faces_on(s):
            for lp in topo.loops(f):
                out = []
                whole = True
                for fin in topo.fins(lp):
                    e = topo.ref(fin, "edge", (EDGE,))
                    if e is None:
                        v = topo.ref(fin, "vertex")
                        if v is not None:
                            out.append(topo.point_of(v))
                        continue
                    try:
                        sm = self.sampler.samples(e)
                    except FaceFailed:
                        whole = False
                        continue
                    run = [self.points[i] for i in sm.ids]
                    if topo.sense(fin) < 0:
                        run.reverse()
                    out.extend(run[:-1] if len(run) > 1 else run)
                if out:
                    loops.append((out, whole))
        return loops

    @staticmethod
    def _cover(loops, param, period: float):
        """How the faces' loops lie along a closed spine of ``period``: ``(winds, lo, hi,
        gap)``. Each loop is followed round in the spine's parameter, unwrapped step by
        step; ``winds`` when one goes round the spine. Otherwise the loops' extents, joined
        on the circle, leave the largest gap ``gap`` uncovered, and the faces lie from
        ``lo`` to ``hi`` (unwrapped, ``hi - lo = period - gap``)."""

        def wrapped(d):
            return (d + 0.5 * period) % period - 0.5 * period

        arcs = []
        winds = False
        for pts, closed in loops:
            ts = [param(p) for p in pts]
            u = [ts[0]]
            for t in ts[1:]:
                u.append(u[-1] + wrapped(t - u[-1]))
            if closed and len(u) > 1 and abs(u[-1] + wrapped(ts[0] - u[-1]) - u[0]) > 0.5 * period:
                winds = True
            a, b = min(u), max(u)
            if b - a >= period:
                winds = True
            arcs.append((a % period, a % period + (b - a)))
        if winds or not arcs:
            return True, 0.0, period, 0.0
        arcs.sort()
        merged = [list(arcs[0])]
        for a, b in arcs[1:]:
            if a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        while len(merged) > 1 and merged[-1][1] >= merged[0][0] + period:  # the last runs into the first
            a, b = merged.pop()
            merged[0] = [a - period, max(merged[0][1], b - period)]
        if any(b - a >= period for a, b in merged):
            return True, 0.0, period, 0.0
        gaps = [
            (merged[(k + 1) % len(merged)][0] + (period if k == len(merged) - 1 else 0.0) - b, k)
            for k, (_a, b) in enumerate(merged)
        ]
        gap, k = max(gaps)
        lo = merged[(k + 1) % len(merged)][0]
        return False, lo, lo + period - gap, gap

    @staticmethod
    def _seam(loops, param, period: float) -> float:
        """Where a surface round a whole closed spine starts and ends: the middle of the
        widest stretch of the spine between points of the faces."""
        ts = sorted(param(p) % period for pts, _c in loops for p in pts)
        if not ts:
            return 0.0
        gaps = [
            (ts[(k + 1) % len(ts)] + (period if k == len(ts) - 1 else 0.0) - t, t) for k, t in enumerate(ts)
        ]
        gap, t = max(gaps)
        return t + 0.5 * gap

    # ------------------------------------------------------------------ building
    def fitted(self, s, hint=None) -> BlendFit:
        """The approximation of blend surface ``s``, made once; raises :class:`FitFailed`
        (remembered) when it cannot be made. ``hint``: points of an edge on it, for a
        blend no face uses."""
        got = self.fits.get(s.index)
        if got is None:
            if s.index in self._building or len(self._building) > 4:
                raise FitFailed("unsupported_surface", "blends that rest on one another in a loop")
            self._building.add(s.index)
            outer, outer_best = self.clock, self._best
            if self.budget is not None:  # this blend's own share of the time left
                self.clock = Clock(min(self.budget, outer.left()))
            self._best = None
            try:
                got = self._fit(s, hint)
            except FitFailed as exc:
                got = exc
            except FaceFailed as exc:
                got = FitFailed("unsupported_surface", f"a blend whose supports cannot be evaluated: {exc}")
            except TimeUp:
                if self.budget is None or outer.left() <= 0.0:
                    raise
                if self._best is not None and self._best[1] <= self.max_deviation:
                    got = BlendFit(*self._best)  # its share ran out: its best round is close enough
                else:
                    why = f"its fit took longer than the {self.budget:.3g} s a blend may take"
                    got = FitFailed("fit_failed", why)
            finally:
                self.clock, self._best = outer, outer_best
                self._building.discard(s.index)
            self.fits[s.index] = got
        if isinstance(got, FitFailed):
            raise got
        return got

    def _fit(self, s, hint=None) -> BlendFit:
        topo = self.topo
        clock = self.clock
        tol = self.tol
        btype = topo.get(s, "blend_type", "R")
        if btype not in ("R", "E"):
            raise FitFailed("unsupported_surface", f"a blend of type {btype!r}")
        supports = topo.get(s, "surface", [])
        rng = topo.get(s, "range", [])
        if not (
            isinstance(supports, list) and len(supports) == 2 and isinstance(rng, list) and len(rng) == 2
        ):
            raise FitFailed("bad_reference", "a blend without its two supports and ranges")
        snodes = [topo.nodes.get(i) for i in supports]
        if any(n is None for n in snodes):
            raise FitFailed("bad_reference", "a blend's support is missing")
        feet, curves = [], []
        self.extra = 0.0  # the deviation of a support that is itself approximated
        for n in snodes:
            f, is_curve = self._support(n)
            feet.append(f)
            curves.append(is_curve)
        radius = max(abs(rng[0]), abs(rng[1]))
        if not radius > 0.0 or abs(abs(rng[0]) - abs(rng[1])) > 1e-9 * radius and not any(curves):
            raise FitFailed("unsupported_surface", "a blend whose two ranges differ (not a rolling sphere)")
        spine = topo.ref(s, "spine", required=True)
        spine_ev = self._spine(spine)
        runs = self._face_points(s) or ([list(hint)] if hint else [])
        pts = [p for r in runs for p in r]
        if not pts:
            raise FitFailed("unsupported_surface", "a blend no face uses")
        traced = isinstance(spine_ev, Polyline)
        tolr = max(1e-7, 1e-4 * radius)
        missed = [0.0]  # how far the worst foot was from the sphere, for the refusal

        def section_at(c):
            """The section of the sphere centred at the spine point c: (c, foot, foot), or
            None where it does not touch both supports."""
            if c is None:
                missed[0] = math.inf
                return None
            f0, _n0 = feet[0](c)
            f1, _n1 = feet[1](c)
            off = max(abs(dist(f0, c) - radius), abs(dist(f1, c) - radius))
            if off > tolr:
                missed[0] = max(missed[0], off)
                return None
            return c, f0, f1

        def refused():
            return FitFailed(
                "fit_failed",
                f"the sphere of a blend (radius {radius:.3g} m) misses a support by {missed[0]:.3g} m "
                "along its faces",
            )

        if traced:
            senses = [topo.sense(n) for n in snodes]
            offsets = self._offsets(feet, curves, rng, self._probe(spine_ev.pts, pts), senses)
            self.note = None
            self.overrun = 0.0
            samples = self._trace(offsets, runs, radius, section_at, spine_ev.pts)
            if samples is None and self.note:
                raise FitFailed(
                    "fit_failed", f"a blend's spine (an intersection) cannot be followed: {self.note}"
                )
            if samples is None:
                raise refused()
            closed = samples[0][1] is samples[-1][1]  # traced round a closed spine

            def mid(a, b):
                got = refine(_lerp(a[1], b[1], 0.5), offsets)
                sec = section_at(got[0] if got is not None else None)
                return None if sec is None else (0.5 * (a[0] + b[0]), *sec)

            def middle(a, b, f=0.5):
                """The spine point a fraction f of the way from section a to b, to start
                searches from."""
                return refine(_lerp(a[1], b[1], f), offsets)

            slide = 1e-11 if self.slide is None else self.slide

            def spine_near(p, start):
                """The spine point nearest p, from the spine point start (with its
                tangent): slid along the spine to where p is square to it (within
                ``slide``), refined onto both offsets."""
                got = start
                for _ in range(16):
                    if got is None:
                        return None
                    c, t = got
                    step = dot(sub(p, c), t)
                    if abs(step) <= slide:
                        break
                    got = refine(add(c, mul(t, step)), offsets)
                return got[0] if got is not None else None

        else:

            def param(p):
                return nearest(spine_ev, p, spine_ev.param(p, clock))

            period = spine_ev.period
            ranges = []  # spine ranges to try, each (a, b, whole turn)
            if period is None:
                ts = [param(p) for p in pts]
                lo, hi = min(ts), max(ts)
                span = hi - lo
                if not span > 0.0:
                    raise FitFailed("fit_failed", "a blend face of no length along its spine")
                for margin in (MARGIN, 0.25 * MARGIN, 0.0):
                    a, b = lo - margin * span, hi + margin * span
                    if spine_ev.lo is not None:
                        a, b = max(a, spine_ev.lo), min(b, spine_ev.hi)
                    ranges.append((a, b, False))
            else:
                # A closed spine: the loops of the faces followed round it. Where one goes
                # round (a ring of blend), or they leave little of it uncovered, the surface
                # is lofted round the whole spine and closes on itself: a surface stopping
                # short of a turn would leave a sliver of the face off it.
                loops = self._face_loops(s) or [(list(r), False) for r in runs]
                winds, lo, hi, gap = self._cover(loops, param, period)
                span = hi - lo
                followed = all(whole for _pts, whole in loops)
                if winds or gap <= 2.0 * MARGIN * span or not followed:
                    seam = self._seam(loops, param, period) if winds else hi + 0.5 * gap
                    ranges.append((seam, seam + period, True))
                if not winds:
                    if not span > 0.0:
                        raise FitFailed("fit_failed", "a blend face of no length along its spine")
                    for margin in (MARGIN, 0.25 * MARGIN, 0.0):
                        m = min(margin * span, 0.45 * gap)
                        ranges.append((lo - m, hi + m, False))
            samples = None
            closed = False
            for a, b, whole in ranges:
                got = []
                count = FIRST_SECTIONS if whole else FIRST_SECTIONS + 1
                for i in range(count):
                    clock.check()
                    t = a + (b - a) * i / FIRST_SECTIONS
                    sec = section_at(spine_ev.point(t))
                    if sec is None:
                        break
                    got.append((t, *sec))
                else:
                    if whole:  # the last section is the first, so the surface closes
                        got.append((b, *got[0][1:]))
                        self.facts["blend_lofted_round_its_closed_spine"] += 1
                    samples, closed = got, whole
                    break
            if samples is None:
                raise refused()

            def mid(a, b):
                t = 0.5 * (a[0] + b[0])
                sec = section_at(spine_ev.point(t))
                return None if sec is None else (t, *sec)

            def middle(a, b, f=0.5):
                return a[0] + (b[0] - a[0]) * f

            def spine_near(p, start):
                return spine_ev.point(nearest(spine_ev, p, start))

        angles = []
        for _t, c, f0, f1 in samples:
            got = arc_row(c, f0, f1, 1)
            if got is None:
                raise FitFailed("fit_failed", "a blend section with no arc")
            angles.append(got[1])
        nseg = max(1, math.ceil(max(angles) / (math.pi / 2) - 1e-9))

        def build(samples):
            rows = []
            params = [0.0]
            for k, (_t, c, f0, f1) in enumerate(samples):
                got = arc_row(c, f0, f1, nseg)
                if got is None:
                    raise FitFailed("fit_failed", "a blend section with no arc")
                rows.append(got[0])
                if k:
                    step = dist(samples[k - 1][1], c)
                    if not step > 0.0:
                        raise FitFailed("fit_failed", "two sections of a blend at one point")
                    params.append(params[-1] + step)
            if closed:
                rows[-1] = rows[0]
            return loft(rows, params, nseg, closed), params

        along = ALONG if self.along is None else self.along
        across = ACROSS if self.across is None else self.across

        def measure(spline, params, i):
            """How far span i strays, at each fraction of it in ``along``: the largest
            distance from the surface to the canal surface across it, and how far each of
            its two sides lies from the true line of contact with that support (the foot
            of the sphere there), which the face's edge follows."""
            worst = 0.0
            for f in along:
                um = params[i] + (params[i + 1] - params[i]) * f
                start = middle(samples[i], samples[i + 1], f)
                if start is None:
                    return math.inf
                for k in range(across):
                    p = spline.point(um, k / (across - 1))
                    c = spine_near(p, start)
                    if c is None:
                        return math.inf
                    worst = max(worst, abs(dist(p, c) - radius))
                    if k in (0, across - 1):
                        sec = section_at(c)
                        if sec is None:
                            return math.inf
                        worst = max(worst, dist(p, sec[1 if k == 0 else 2]))
            return worst

        spline, params = build(samples)
        dev = math.inf
        added = self.extra + (self.overrun if traced else 0.0)
        best = math.inf  # the least deviation a round measured (with a budget)
        for _round in range(ROUNDS + 1):
            errs = []
            for i in range(len(samples) - 1):
                clock.check()
                errs.append(measure(spline, params, i))
                if self.give_up and not math.isfinite(errs[-1]):
                    break
            dev = max(errs) if errs else 0.0
            if self.budget is not None and dev < best:
                best = dev
                self._best = (spline, dev + added, radius, spine_near)
            if dev <= tol or len(samples) >= MAX_SECTIONS or _round == ROUNDS:
                break
            if self.give_up and not math.isfinite(dev):
                break
            more = [samples[0]]
            for i, e in enumerate(errs):
                if e > tol and len(more) + (len(samples) - i) < MAX_SECTIONS:
                    m = mid(samples[i], samples[i + 1])
                    if m is not None:
                        more.append(m)
                more.append(samples[i + 1])
            if len(more) == len(samples):
                break
            samples = more
            spline, params = build(samples)
        if not math.isfinite(dev):
            raise FitFailed("fit_failed", "a blend's approximation could not be measured")
        return BlendFit(spline, dev + self.extra + (self.overrun if traced else 0.0), radius, spine_near)

    @staticmethod
    def _probe(chart, pts, count: int = 5):
        """The chart points nearest the faces' points, to test the offsets' signs on."""
        n = len(pts)
        centre = (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n, sum(p[2] for p in pts) / n)
        return sorted(chart, key=lambda q: dist(q, centre))[:count]

    def _trace(self, offsets, pts, radius, section_at, chart):
        """Sections along an intersection spine: from the spine point nearest the faces,
        stepping along its tangent and back onto both offset supports, each way until no
        point of the faces' edges lies ahead of the section within the sphere's reach (and
        one step more where the sphere still touches both supports), or round to where it
        started on a closed spine. None when the sphere leaves a support before the faces
        end."""
        clock = self.clock
        flat = [p for run in pts for p in run]
        lo = [min(p[k] for p in flat) for k in range(3)]
        hi = [max(p[k] for p in flat) for k in range(3)]
        extent = max(dist(lo, hi), radius)
        h0 = extent / FIRST_SECTIONS
        pts = _densified(pts, h0 / 2.0)
        reach = 2.0 * radius + 2.0 * h0
        n = len(pts)
        centre = (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n, sum(p[2] for p in pts) / n)
        seed = None
        for q in [centre, *sorted(chart, key=lambda q: dist(q, centre))[:8]]:
            got = refine(q, offsets)
            if got is not None and section_at(got[0]) is not None:
                seed = got
                break
        if seed is None:
            self.note = "no point of its spine near its faces"
            return None

        def ahead(c, t):
            return any(dot(sub(f, c), t) > 1e-9 * extent and dist(f, c) <= reach for f in pts)

        halves = []
        closed = False
        for way in (1.0, -1.0):
            c, t = seed[0], mul(seed[1], way)
            run = []
            h = h0
            extra = 1  # one step past the faces, where the sphere still touches both supports
            while True:
                clock.check()
                if not ahead(c, t):
                    if extra == 0:
                        break
                    extra -= 1
                if len(run) > 4 * MAX_SECTIONS:
                    self.note = "its spine is longer than the sections allowed"
                    return None
                got = None
                while h >= h0 / 64:
                    got = refine(add(c, mul(t, h)), offsets)
                    if got is not None and section_at(got[0]) is not None and dist(got[0], c) < 2.0 * h:
                        break
                    got = None
                    h *= 0.5
                if got is None:
                    if ahead(c, t) and extra > 0:  # the sphere leaves a support before the faces end
                        far = max(dot(sub(f, c), t) for f in pts if dist(f, c) <= reach)
                        if far > self.max_deviation:
                            self.note = f"the sphere leaves a support {far:.3g} m before its faces end"
                            return None
                        # the faces end within the deviation allowed of the last section:
                        # the surface stops there, and that is part of its deviation
                        self.overrun = max(self.overrun, far)
                    break
                nt = got[1] if dot(got[1], t) >= 0.0 else mul(got[1], -1.0)
                c, t = got[0], nt
                if len(run) >= 3 and dist(c, seed[0]) < 0.75 * h:
                    closed = True  # round a closed spine, back where it started
                    run.append(seed[0])
                    break
                run.append(c)
                h = min(h0, 2.0 * h)
            halves.append(run)
            if closed:
                break
        centres = [seed[0], *halves[0]] if closed else list(reversed(halves[1])) + [seed[0]] + halves[0]
        out = []
        for k, c in enumerate(centres):
            sec = section_at(c)
            if sec is None:
                self.note = "the sphere does not touch both supports at a section"
                return None
            out.append((float(k), *sec))
        return out

    def _offsets(self, feet, curves, rng, probe, senses=(1, 1)):
        """The offset supports the spine lies on: each support offset by its range, the
        sign of each checked against spine points (a cliff edge's curve is offset by the
        sphere's radius, away from it)."""
        best = None
        for s0 in (1.0, -1.0):
            for s1 in (1.0, -1.0):
                offs = [
                    OffsetFoot(feet[0], abs(rng[0]) * s0 if not curves[0] else abs(rng[1])),
                    OffsetFoot(feet[1], abs(rng[1]) * s1 if not curves[1] else abs(rng[0])),
                ]
                err = sorted(max(dist(f(p)[0], p) for f in offs) for p in probe)
                score = err[len(err) // 2]  # the median: a chart may run past a support's ends
                if best is None or score < best[0]:
                    best = (score, offs, (s0, s1))
        if not any(curves):
            expected = tuple(math.copysign(1.0, rng[k]) * senses[k] for k in range(2))
            self.facts["blend_offsets_" + ("range_times_sense" if best[2] == expected else "other")] += 1
        return best[1]

    # ------------------------------------------------------------------ faces on a blend
    def same_sense(self, f, snode) -> bool:
        """Whether a face on a blend points along the approximation's natural normal: the
        outward normal of a face it meets tangentially, at a point of their edge."""
        topo = self.topo
        bf = self.fitted(snode)
        foot = Foot(bf.ev, self.clock, self.reach)
        best = None
        for lp in topo.loops(f):
            for fin in topo.fins(lp):
                e = topo.ref(fin, "edge", (EDGE,))
                if e is None:
                    continue
                for other in topo.edge_fins(e):
                    if other is fin:
                        continue
                    lp2 = topo.ref(other, "loop")
                    f2 = topo.ref(lp2, "face") if lp2 is not None else None
                    if f2 is None or f2 is f:
                        continue
                    s2 = topo.ref(f2, "surface")
                    if s2 is None or s2.type == BLENDED_EDGE:
                        continue
                    try:
                        ev2 = self.geom.surface(s2)
                        sm = self.sampler.samples(e)
                    except FaceFailed:
                        continue
                    pts = [self.points[i] for i in sm.ids]
                    p = pts[len(pts) // 2]
                    q2, n2 = Foot(ev2, self.clock, self.reach)(p)
                    q1, n1 = foot(p)
                    if n1 is None or n2 is None:
                        continue
                    out2 = mul(n2, topo.sense(s2) * topo.sense(f2))
                    d = dot(n1, out2)
                    if best is None or abs(d) > abs(best):
                        best = d
        if best is None or abs(best) < 0.9:
            raise FitFailed(
                "orientation_conflict", "a blend face meets no face tangentially to take its side from"
            )
        self.facts[
            "blend_side_"
            + ("as_senses" if (best > 0.0) == (topo.sense(f) == topo.sense(snode)) else "reversed")
        ] += 1
        return best > 0.0

    # ------------------------------------------------------------------ for the tessellator
    def evaluator(self, s) -> BSurface:
        """The surface the tessellator triangulates for blend ``s``: the approximation's
        evaluator, refused (``fit_failed``) when it strays from the blend by more than
        ``max_deviation``. A value of the file that breaks the construction refuses the
        blend too (``degenerate``), once."""
        try:
            bf = self.fitted(s)
        except UNFORESEEN as exc:
            why = type(exc).__name__
            got = FitFailed("degenerate", f"a rolling blend's values break its construction ({why})")
            self.fits[s.index] = got
            raise got from None
        if bf.deviation > self.max_deviation:
            raise FitFailed(
                "fit_failed",
                f"the approximation of a rolling blend stays {bf.deviation:.3g} m from it, more than the "
                f"{self.max_deviation:.3g} m allowed",
            )
        return bf.ev

    def side(self, f, s) -> int:
        """+1 when face ``f`` on blend ``s`` points along the natural normal of the
        approximation's own (u, v), -1 when against it."""
        try:
            return 1 if self.same_sense(f, s) else -1
        except UNFORESEEN as exc:
            why = type(exc).__name__
            raise FitFailed("degenerate", f"a blend face's side cannot be told ({why})") from None
