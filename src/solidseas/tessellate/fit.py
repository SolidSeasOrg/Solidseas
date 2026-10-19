# Curves fitted through points, and the feet of points on surfaces, with the deviation
# of every fit measured. Shared by the STEP export and the tessellator's rolling blends.
#
# Derived work. The interpolating cubic through points and tangents, the Hermite
# midpoint test and the refinement of intersection points onto both surfaces come from
#   BlinkingSun/sldprt2step, files sldprt2step_lib/step/mapper.py (intersection_points,
#   _tangents_from_surfaces, _refine_on_surfaces, _project_both, _hermite_mid) and
#   sldprt2step_lib/xt/geom.py (interpolate_cubic)
#   https://github.com/BlinkingSun/sldprt2step, commit fa954124f4f126e0c465c8f96454978ac80b812e
#   Licensed under the Apache License, Version 2.0. sldprt2step is a port of
#   open-sld-to-step 0.1.0 (Apache-2.0). See NOTICE in the SolidSeas repository.
# Modified for SolidSeas (2026-10-03, 2026-10-04): rewritten over SolidSeas' own
# surface evaluators and their seeded Newton projections (upstream searched a 41 x 41
# grid for each foot); intersection points refined by Newton on both surfaces at once;
# every fit's deviation measured at the quarter points of its spans against the true
# geometry, refined until within the target; budgets of points and a clock bound the
# work; moved here from solidseas.step.approx, so that the tessellator's rolling blends
# share it with the export (2026-10-04).
"""Fitting curves through points, and finding the feet of points on surfaces.

* :func:`fit_nodes` fits a C1 cubic B-spline (:func:`interpolate_cubic`) through
  nodes on a curve, made dense enough that each Hermite segment's midpoint lies within
  the target of the true curve, then measured span by span and split again where it
  strays, up to :data:`ROUNDS` times.
* :class:`Foot` is the nearest point of a surface and its natural normal, each search
  starting from the last foot found; :func:`refine` the point of the intersection of
  two surfaces nearest a point, by Newton's method on both at once.

What cannot be fitted raises :class:`FitFailed`, a :class:`~.topology.FaceFailed`
with a reason: the tessellator skips the face, the STEP export refuses the body.
"""

import math

from . import nurbs
from ._vec import add, cross, dist, dot, mul, norm, sub
from .surfaces import Surface
from .topology import FaceFailed

MAX_POINTS = 4096  # points of one fitted curve
MAX_DEPTH = 16  # halvings of one span
ROUNDS = 8  # passes that split the spans measured above the target
QUARTERS = (0.25, 0.5, 0.75)


class FitFailed(FaceFailed):
    """An approximation that cannot be made, measured or kept within its limit:
    ``reason`` is ``fit_failed``, ``unsupported_surface``, ``unsupported_curve``,
    ``bad_reference`` or ``orientation_conflict``, ``detail`` a sentence for people."""


def _unit(v):
    n = norm(v)
    return (v[0] / n, v[1] / n, v[2] / n) if n > 1e-300 else None


def hermite_mid(pa, ta, pb, tb):
    """The midpoint of the cubic Hermite segment from ``pa`` to ``pb`` whose end
    tangents are the unit ``ta`` and ``tb`` scaled by the chord."""
    c = dist(pa, pb)
    return add(mul(add(pa, pb), 0.5), mul(sub(ta, tb), c / 8.0))


def interpolate_cubic(points, tangents) -> nurbs.BSplineCurve:
    """A C1 cubic B-spline through ``points`` with unit ``tangents`` there: one Bezier
    segment a pair of points, parametrised by chord length, interior knots of
    multiplicity 3, ends clamped."""
    if len(points) < 2:
        raise FitFailed("fit_failed", "a curve to fit has fewer than two points")
    cps = [points[0]]
    knots = [0.0] * 4
    s = 0.0
    for i in range(len(points) - 1):
        c = dist(points[i], points[i + 1])
        if not c > 0.0:
            raise FitFailed("fit_failed", "two points of a curve to fit coincide")
        cps.append(add(points[i], mul(tangents[i], c / 3.0)))
        cps.append(sub(points[i + 1], mul(tangents[i + 1], c / 3.0)))
        cps.append(points[i + 1])
        s += c
        if i < len(points) - 2:
            knots.extend([s, s, s])
    knots.extend([s] * 4)
    return nurbs.BSplineCurve(3, cps, knots, False, False)


def dedupe(nodes):
    """Nodes (point, tangent, parameter) with consecutive duplicates (points closer than
    1e-12 m) dropped, the last kept."""
    keep = [nodes[0]]
    for n in nodes[1:]:
        if dist(n[0], keep[-1][0]) > 1e-12:
            keep.append(n)
        elif n is nodes[-1]:
            keep[-1] = n
    return keep


def fit_nodes(nodes, exact_mid, measure, tol: float, clock, what: str, max_points: int = MAX_POINTS):
    """``nodes`` are (point, unit tangent, parameter or None) along the curve, made
    dense enough that each Hermite segment's midpoint lies within ``tol`` of the true
    curve (``exact_mid(a, b)`` gives the true node between nodes ``a`` and ``b``, or
    None), fitted, and measured (``measure(fit, nodes)``: for each span the largest
    distance at its quarter points); spans above ``tol`` split again, up to
    :data:`ROUNDS` times. Returns (B-spline, deviation, nodes)."""
    out = [nodes[0]]
    stack = [(nodes[i], nodes[i + 1], 0) for i in range(len(nodes) - 2, -1, -1)]
    while stack:
        clock.check()
        na, nb, depth = stack.pop()
        if depth < MAX_DEPTH and len(out) + len(stack) < max_points and dist(na[0], nb[0]) > 1e-9:
            q = exact_mid(na, nb)
            if q is not None and dist(q[0], hermite_mid(na[0], na[1], nb[0], nb[1])) > 0.5 * tol:
                stack.append((q, nb, depth + 1))
                stack.append((na, q, depth + 1))
                continue
        out.append(nb)
    nodes = dedupe(out)
    dev = math.inf
    fit = None
    for _round in range(ROUNDS + 1):
        fit = interpolate_cubic([n[0] for n in nodes], [n[1] for n in nodes])
        spans = measure(fit, nodes)
        dev = max(spans) if spans else 0.0
        if dev <= tol or _round == ROUNDS or len(nodes) >= max_points:
            break
        more = [nodes[0]]
        for i, d in enumerate(spans):
            if d > tol and len(more) + (len(nodes) - i) < max_points:
                q = exact_mid(nodes[i], nodes[i + 1])
                if q is not None:
                    more.append(q)
            more.append(nodes[i + 1])
        if len(more) == len(nodes):
            break
        nodes = dedupe(more)
    if not math.isfinite(dev):
        raise FitFailed("fit_failed", f"the fit of its {what} could not be measured")
    return fit, dev, nodes


class Foot:
    """The nearest point of a surface (one of SolidSeas' evaluators) and the unit
    natural normal there, starting each search from the last foot found.

    ``reach``: how far, in multiples of the last point's distance from the surface, the
    point asked about may have moved for the search to start from the last foot alone."""

    def __init__(self, ev, clock, reach: float = 1.0) -> None:
        self.ev, self.clock, self.reach = ev, clock, reach
        self.hint = None
        self.last = None  # the last point asked about and its foot
        # A surface searched from seeds (B-splines, swept and spun surfaces) is searched
        # by Newton's method from the last foot alone when the point asked about is near
        # the last one and the foot settles near the last foot, nearer than it.
        self.local = type(ev).closest is Surface.closest

    def __call__(self, p):
        ev = self.ev
        got = None
        if self.local and self.last is not None and ev.pole_at(p, 1e-10) is None:
            p0, q0 = self.last
            moved = dist(p, p0)
            if moved <= self.reach * dist(p0, q0) + 1e-9:
                got = _local_newton(ev, p, self.hint[0], self.hint[1])
                if got is not None:
                    q = ev.point(got[0], got[1])
                    if (
                        dist(q, q0) > 4.0 * moved + 1e-9
                        or got[2] > dist(q0, p) + 1e-12
                        or ev.at_pole(got[0], got[1], p, 1e-10)
                    ):
                        got = None  # not plainly the same foot moved on: search widely
        if got is None:
            got = ev.closest(p, self.hint, 1e-7, 1e-10, self.clock)
        u, v, _d = got
        if u is not None:
            self.last = (p, ev.point(u, v))
        if u is None:  # a pole: the point there, no normal
            for pv, q in ev.poles:
                if pv == v:
                    return q, None
            return p, None
        self.hint = (u, v)
        n = ev.normal(u, v)
        if n is not None and ev.flip < 0:  # Parasolid's natural normal, whatever the evaluator's order
            n = (-n[0], -n[1], -n[2])
        return ev.point(u, v), n


def _local_newton(S, p, u: float, v: float, iters: int = 12):
    """The foot of p on S by Newton's method from (u, v), with the surface's second
    derivatives (by differences of its first), which converges fast however far p lies
    from the surface: (u, v, distance) once a step moves less than 1e-13 m, or None when
    it does not settle (the caller then searches widely)."""
    for _ in range(iters):
        q, su, sv = S.d1(u, v)
        hu = 1e-7 * max(1.0, abs(u))
        hv = 1e-7 * max(1.0, abs(v))
        _q, suu_, suv_ = S.d1(u + hu, v)
        _q, svu_, svv_ = S.d1(u, v + hv)
        suu = mul(sub(suu_, su), 1.0 / hu)
        svv = mul(sub(svv_, sv), 1.0 / hv)
        suv = mul(sub(svu_, su), 1.0 / hv)
        r = sub(p, q)
        g1, g2 = dot(r, su), dot(r, sv)
        a = dot(su, su) - dot(r, suu)
        b = dot(su, sv) - dot(r, suv)
        c = dot(sv, sv) - dot(r, svv)
        det = a * c - b * b
        if not det > 0.0 or not a > 0.0:  # not near a minimum of the distance
            return None
        du = (c * g1 - b * g2) / det
        dv = (a * g2 - b * g1) / det
        nu, nv = S.clamp(u + du, v + dv)
        moved = abs(nu - u) * norm(su) + abs(nv - v) * norm(sv)
        u, v = nu, nv
        if moved <= 1e-13:
            return u, v, dist(S.point(u, v), p)
    return None


def refine(x, feet, iters: int = 40):
    """The point of the intersection of two surfaces nearest ``x`` by Newton's method on
    both at once (each step the least move that reaches both tangent planes), and the
    unit tangent of the intersection there; None where the surfaces are tangent, or it
    does not converge onto both."""
    scale = 1.0 + norm(x)
    n1 = n2 = None
    last = math.inf
    for it in range(iters):
        q1, n1 = feet[0](x)
        q2, n2 = feet[1](x)
        if n1 is None or n2 is None:
            return None
        d1 = dot(n1, sub(q1, x))
        d2 = dot(n2, sub(q2, x))
        c = dot(n1, n2)
        det = 1.0 - c * c
        if det < 1e-10:
            return None
        a = (d1 - c * d2) / det
        b = (d2 - c * d1) / det
        step = add(mul(n1, a), mul(n2, b))
        x = add(x, step)
        moved = norm(step)
        if moved <= 1e-15 * scale or (it >= 3 and moved >= 0.5 * last):
            break  # settled, or no longer converging (rounding): the check below decides
        last = moved
    q1, n1 = feet[0](x)
    q2, n2 = feet[1](x)
    if n1 is None or n2 is None or dist(q1, x) > 1e-10 * scale or dist(q2, x) > 1e-10 * scale:
        return None
    t = _unit(cross(n1, n2))
    return (x, t) if t is not None else None
