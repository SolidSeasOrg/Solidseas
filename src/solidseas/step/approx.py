# Approximations of what STEP cannot hold exactly, with their deviation measured.
#
# Derived work. The interpolating cubic through points and tangents, the Hermite
# midpoint test, the refinement of intersection points onto both surfaces, the
# tangents from the two normals, the adaptive sampling of SP-curves and the
# rolling blend (exact circular sections between the feet on the supports,
# lofted cubically along the spine, sections inserted where the error is largest)
# come from
#   BlinkingSun/sldprt2step, files sldprt2step_lib/step/mapper.py (intersection_points,
#   intersection_curve, _tangents_from_surfaces, _refine_on_surfaces, _project_both,
#   _hermite_mid, sp_curve_3d, blend_surface, spine_samples, curve_support,
#   _CurveSupport, _OffsetEval, _section_angle, _degenerate_arc, blend_boundary_curve)
#   and sldprt2step_lib/xt/geom.py (interpolate_cubic, interpolate_cubic_surface_rows,
#   _col_tangent, arc_nurbs, golden)
#   https://github.com/BlinkingSun/sldprt2step, commit fa954124f4f126e0c465c8f96454978ac80b812e
#   Licensed under the Apache License, Version 2.0. sldprt2step is a port of
#   open-sld-to-step 0.1.0 (Apache-2.0). See NOTICE in the SolidSeas repository.
# Modified for SolidSeas (2026-10-03, 2026-10-04): rewritten over SolidSeas' own
# surface evaluators and their seeded Newton projections (upstream searched a 41 x 41
# grid for each foot); intersection points refined by Newton on both surfaces at once;
# every fit's deviation measured at the quarter points of its spans against the true
# geometry, refined until within the target and refused beyond the limit; budgets of
# points and sections, and a clock, bound the work; an edge fitted from its own start
# to its end, so its direction is never guessed; a blend face's orientation taken from
# the faces it meets tangentially; a blend boundary edge on a blend closed round its
# spine may cross the blend's seam; the cubic, the feet, the refinement onto two
# surfaces and the fitting loop moved to solidseas/tessellate/fit.py and the cliff
# edge's chart fit to solidseas/tessellate/blend.py, which the tessellator shares
# (2026-10-04).
"""Approximations: B-splines in place of what STEP cannot hold exactly.

* **Intersection curves**: the source edge's chart points (``docs/FORMAT.md`` 10.8)
  between its vertices, refined onto both surfaces by Newton's method on the two
  surfaces at once, with the tangent the two normals give, then points inserted
  where the cubic Hermite segment's midpoint strays from the true curve, and a C1
  cubic B-spline (Bezier segments, chord-length parameter) through them.
* **SP-curves** on curved surfaces that are not iso-parameter curves: the exact
  curve ``S(c(t))`` sampled and fitted the same way.

Every fit is measured: at the quarter points of each span, the distance from the
fit to the true curve (re-projected onto both surfaces for an intersection,
searched along ``S(c(t))`` for an SP-curve). Spans above the target
(``fit_tolerance_m``) are split again; a fit that stays above ``max_deviation_m``
is refused (``fit_failed``). The measured deviation is reported and the file's
uncertainty covers it. The fitting itself is :func:`solidseas.tessellate.fit.fit_nodes`.
"""

import math

from ..tessellate._vec import dist, dot, mul, norm, sub
from ..tessellate.fit import QUARTERS, FitFailed, Foot, fit_nodes, hermite_mid, refine
from ..tessellate.fit import dedupe as _dedupe
from ..tessellate.topology import BLEND_BOUND, BLENDED_EDGE, FaceFailed
from . import entities as E
from .mapper import CurveMap, Refused

MAX_POINTS = 4096  # points of one fitted curve


def _unit(v):
    n = norm(v)
    return (v[0] / n, v[1] / n, v[2] / n) if n > 1e-300 else None


def off_curve(p, feet) -> float:
    """How far ``p`` lies from the intersection of two surfaces: the distance to the
    intersection point Newton's method finds from it; where that fails, the larger of
    its distances to the two surfaces over the sine of the angle between them (where
    they are tangent and the point is not defined, the larger distance)."""
    got = refine(p, feet)
    if got is not None:
        return dist(got[0], p)
    q1, n1 = feet[0](p)
    q2, n2 = feet[1](p)
    if n1 is None or n2 is None:
        return math.inf
    # Within d1 of one surface and d2 of the other, a point lies within about
    # max(d1, d2) / sin(angle) of their intersection (where a surface ends, its nearest
    # point is farther than the surface's extension would be: the bound only grows).
    s = math.sqrt(max(0.0, 1.0 - dot(n1, n2) ** 2))
    d = max(dist(q1, p), dist(q2, p))
    return d / s if s > 1e-3 else d


class Approximator:
    """The approximations of one body (its :class:`.mapper.BodyMapper` ``m``)."""

    def __init__(self, mapper) -> None:
        self.m = mapper

    @property
    def tol(self) -> float:
        return self.m.opts.fit_tolerance_m

    # ------------------------------------------------------------------ helpers
    def _edge_points(self):
        """The source edge's sample points from the traversal's start to its end."""
        e, reverse = self.m.current_edge
        try:
            sm = self.m.sampler.samples(e)
        except FaceFailed as exc:
            raise Refused("fit_failed", f"the edge cannot be sampled to fit it: {exc}") from None
        pts = [self.m._points.p[i] for i in sm.ids]
        if reverse:
            pts.reverse()
        if len(pts) > MAX_POINTS:  # a long chart: every k-th point, the ends kept
            k = math.ceil(len(pts) / MAX_POINTS)
            pts = pts[::k] + ([pts[-1]] if (len(pts) - 1) % k else [])
        return pts

    def _fit(self, nodes, exact_mid, measure, cls: str, what: str):
        """``nodes`` fitted by :func:`solidseas.tessellate.fit.fit_nodes` to the export's
        target, then counted and checked against its limit (``note_approximation``).
        Returns (B-spline, deviation, nodes)."""
        try:
            fit, dev, nodes = fit_nodes(nodes, exact_mid, measure, self.tol, self.m.clock, what, MAX_POINTS)
        except FitFailed as exc:
            raise Refused(exc.reason, exc.detail) from None
        self.m.note_approximation(cls, dev, what)
        return fit, dev, nodes

    # ------------------------------------------------------------------ intersections
    def intersection(self, node, a, b, ring, trim):
        topo = self.m.topo
        surfaces = topo.get(node, "surface", [])
        if not isinstance(surfaces, list) or len(surfaces) != 2:
            raise Refused("bad_reference", "an intersection curve without its two surfaces")
        snodes = []
        for idx in surfaces:
            s = topo.nodes.get(idx) if isinstance(idx, int) else None
            if s is None:
                raise Refused("bad_reference", "an intersection curve's surface is missing")
            snodes.append(s)
        pts = self._edge_points()
        if len(pts) < 2:
            raise Refused("fit_failed", "an intersection edge with fewer than two points")
        for s in snodes:  # where a blend meets its support: its own boundary curve
            if s.type == BLEND_BOUND:
                blend = topo.ref(s, "blend")
                if blend is None or blend.type != BLENDED_EDGE:
                    raise Refused("unsupported_curve", "a blend boundary without its blend")
                return self.blend_boundary(blend, pts, ring)
        for s, other in ((snodes[0], snodes[1]), (snodes[1], snodes[0])):
            if s.type != BLENDED_EDGE:
                continue
            if other.index in (topo.get(s, "surface", []) or []):
                return self.blend_boundary(s, pts, ring)
            got = self.blend_boundary(s, pts, ring, only_if_near=True)
            if got is not None:  # a support's twin, or a blend meeting a blend along its side
                return got
        extra = 0.0  # the deviation of an approximated surface the curve lies on
        feet = []
        for s in snodes:
            if s.type == BLENDED_EDGE:
                bf = self.blends.fit(s, pts)
                extra = max(extra, bf.deviation)
                feet.append(Foot(bf.ev, self.m.clock))
                continue
            try:
                feet.append(Foot(self.m.geom.surface(s), self.m.clock))
            except FaceFailed as exc:
                raise Refused(
                    "unsupported_curve", f"an intersection curve on a surface that cannot be evaluated: {exc}"
                ) from None
        chord = sub(pts[-1], pts[0]) if dist(pts[-1], pts[0]) > 0 else sub(pts[1], pts[0])
        tans = []
        out = []
        for i, p in enumerate(pts):
            got = refine(p, feet)
            if got is None:
                if 0 < i < len(pts) - 1:
                    continue  # a chart point the surfaces' tangency makes uncertain: skipped
                got = (p, None)
            q, t = got
            if i in (0, len(pts) - 1) and dist(q, p) > self.m.opts.max_deviation_m:
                q = p  # a vertex far off the curve: the fit ends at the vertex
            out.append(q)
            tans.append(t)
        pts = out
        if len(pts) < 2:
            raise Refused("fit_failed", "an intersection curve could not be placed on its surfaces")
        # Orient each tangent along the curve's run, and fill those the normals do not give.
        for i in range(len(pts)):
            ref = sub(pts[min(i + 1, len(pts) - 1)], pts[max(i - 1, 0)])
            if norm(ref) == 0.0:
                ref = chord
            t = tans[i]
            if t is None:
                t = _unit(ref)
            elif dot(t, ref) < 0.0:
                t = mul(t, -1.0)
            tans[i] = t
        if any(t is None for t in tans):
            raise Refused("fit_failed", "an intersection curve's direction is not defined")

        def exact_mid(na, nb):
            pa, ta, pb, tb = na[0], na[1], nb[0], nb[1]
            m = hermite_mid(pa, ta, pb, tb)
            got = refine(m, feet)
            if got is None:
                return None
            q, tq = got
            if dot(tq, sub(pb, pa)) < 0.0:
                tq = mul(tq, -1.0)
            if dist(q, m) > 0.25 * dist(pa, pb):
                return None  # slid along the curve, not onto it
            return q, tq, None

        def measure(fit, _nodes):
            spans = []
            U = fit.U
            for k in range(3, len(U) - 4, 3):
                self.m.clock.check()
                s0, s1 = U[k], U[k + 1]
                worst = 0.0
                for f in QUARTERS:
                    p = fit.point(s0 + (s1 - s0) * f)
                    worst = max(worst, off_curve(p, feet))
                spans.append(worst)
            return spans

        nodes = [(pts[i], tans[i], None) for i in range(len(pts))]
        fit, dev, _n = self._fit(_dedupe(nodes), exact_mid, measure, "INTERSECTION", "intersection curve")
        dev = max(dev, extra)
        return CurveMap(E.BSplineCurve(fit), True, dev, "INTERSECTION", ring_point=pts[0] if ring else None)

    def blend_boundary(self, blend, pts, ring, only_if_near: bool = False):
        """An edge where a blend meets its support (an intersection with a BLEND_BOUND, or
        with the support itself): the approximated blend's own iso-curve along that side,
        between the edge's ends, so the edge lies on the blend as written; its deviation
        from the true edge is measured at the edge's chart points."""
        from . import bspline

        bf = self.blends.fit(blend, pts)
        s = bf.spline
        best = None
        for v in (s.vlo, s.vhi):
            iso = bspline.iso_curve(s, "v", v)
            ev = E.BSplineCurve(bspline.clamped(iso)).evaluator()
            worst = 0.0
            for p in pts:
                t = ev.param(p, self.m.clock)
                worst = max(worst, dist(ev.point(t), p))
            if best is None or worst < best[0]:
                best = (worst, iso, ev)
        worst, iso, ev = best
        if only_if_near and worst > max(self.tol, 2.0 * bf.deviation):
            return None
        dev = max(worst, bf.deviation)
        self.m.note_approximation("BLEND_BOUNDARY", dev, "blend boundary curve")
        if ring:
            c = bspline.clamped(iso)
            return CurveMap(E.BSplineCurve(c), True, dev, "BLEND_BOUNDARY", ring_point=c.point(c.lo))
        ta = ev.param(pts[0], self.m.clock)
        tb = ev.param(pts[-1], self.m.clock)
        if ta == tb:
            raise Refused("fit_failed", "a blend boundary edge of no length on the blend")
        if iso.period is not None and len(pts) > 2:
            # A blend closed round its spine: the edge may cross the seam. It runs the way
            # round from its start to its end that passes its middle point.
            P = iso.period
            tm = ev.param(pts[len(pts) // 2], self.m.clock)
            ahead = (tb - ta) % P
            if (tm - ta) % P < ahead:
                c = bspline.restricted(iso, ta, ta + ahead)
                return CurveMap(E.BSplineCurve(c), True, dev, "BLEND_BOUNDARY")
            c = bspline.restricted(iso, tb, tb + (ta - tb) % P)
            return CurveMap(E.BSplineCurve(c), False, dev, "BLEND_BOUNDARY")
        c = bspline.restricted(iso, min(ta, tb), max(ta, tb))
        return CurveMap(E.BSplineCurve(c), tb > ta, dev, "BLEND_BOUNDARY")

    # ------------------------------------------------------------------ SP-curves
    def sp_curve(self, node, snode, c2, rng, a, b, ring, forward):
        if snode.type in (BLENDED_EDGE, BLEND_BOUND):
            raise Refused("unsupported_curve", "an SP-curve on a blend")
        try:
            ev = self.m.geom.curve(node)
        except FaceFailed as exc:
            raise Refused(
                "unsupported_curve", f"an SP-curve on a surface that cannot be evaluated: {exc}"
            ) from None
        lo, hi = rng if rng is not None else (c2.lo, c2.hi)
        clock = self.m.clock

        def at(t):
            p, d = ev.d1(t)
            u = _unit(d)
            return p, u

        n0 = min(MAX_POINTS // 4, max(8, 4 * c2.n))
        grid = {lo + (hi - lo) * i / n0 for i in range(n0 + 1)}
        ts = sorted({lo, hi} | {k for k in c2.U if lo < k < hi} | grid)
        nodes = []
        for t in ts:
            clock.check()
            p, u = at(t)
            nodes.append([p, u, t])
        for i, n in enumerate(nodes):
            if n[1] is None:  # a stationary point: the chord's direction
                n[1] = _unit(sub(nodes[min(i + 1, len(nodes) - 1)][0], nodes[max(i - 1, 0)][0]))
        nodes = _dedupe([tuple(n) for n in nodes])
        if any(n[1] is None for n in nodes) or len(nodes) < 2:
            raise Refused("fit_failed", "an SP-curve of no length")

        def exact_mid(na, nb):
            tm = 0.5 * (na[2] + nb[2])
            q, u = at(tm)
            return None if u is None else (q, u, tm)

        def measure(fit, nodes):
            spans = []
            U = fit.U
            for j, k in enumerate(range(3, len(U) - 4, 3)):
                clock.check()
                s0, s1 = U[k], U[k + 1]
                t0, t1 = nodes[j][2], nodes[j + 1][2]
                worst = 0.0
                for f in QUARTERS:
                    p = fit.point(s0 + (s1 - s0) * f)
                    t = _golden(lambda tt, p=p: dist(ev.point(tt), p), min(t0, t1), max(t0, t1))
                    worst = max(worst, dist(ev.point(t), p))
                spans.append(worst)
            return spans

        fit, dev, nodes = self._fit(nodes, exact_mid, measure, "SP_CURVE", "SP-curve")
        start = nodes[0][0] if ring else None
        return CurveMap(E.BSplineCurve(fit), forward, dev, "SP_CURVE", ring_point=start)

    # ------------------------------------------------------------------ blends
    @property
    def blends(self):
        if getattr(self, "_blends", None) is None:
            from .blend import Blends

            self._blends = Blends(self)
        return self._blends

    def blend(self, s):
        return self.blends.surface(s)

    def free_curve(self, node, what):
        raise Refused("unsupported_curve", f"the {what} is a curve STEP cannot hold exactly")


def _golden(f, a: float, b: float, iters: int = 60) -> float:
    g = (math.sqrt(5.0) - 1.0) / 2.0
    c, d = b - g * (b - a), a + g * (b - a)
    fc, fd = f(c), f(d)
    for _ in range(iters):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - g * (b - a)
            fc = f(c)
        else:
            a, c, fc = c, d, fd
            d = a + g * (b - a)
            fd = f(d)
    return 0.5 * (a + b)
