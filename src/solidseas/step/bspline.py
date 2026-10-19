# Exact operations on B-spline curves and surfaces for the STEP export.
#
# Derived work. Knot insertion, the homogeneous form, clamping of curves and
# surfaces, restriction of a curve to a range and reversal come from
#   BlinkingSun/sldprt2step, files sldprt2step_lib/xt/geom.py (_insert_knot, _homog,
#   _dehomog, _clamp_curve, _clamp_h, NurbsSurface.clamped) and
#   sldprt2step_lib/step/mapper.py (_restrict_curve, _reverse_curve)
#   https://github.com/BlinkingSun/sldprt2step, commit fa954124f4f126e0c465c8f96454978ac80b812e
#   Licensed under the Apache License, Version 2.0. sldprt2step is a port of
#   open-sld-to-step 0.1.0 (Apache-2.0). See NOTICE in the SolidSeas repository.
# Modified for SolidSeas (2026-10-03, 2026-10-04): rewritten over SolidSeas' own
# B-spline type (solidseas.tessellate.nurbs, homogeneous control points as Parasolid
# stores them); a knot inserted within a hair of one that is there takes that one's
# value; a restriction of a periodic curve may run across its seam, and is moved onto
# the curve's range in one step, a range many periods away refused; Parasolid's knots
# are kept as they are (upstream rescaled them); iso-parameter curves of a surface
# added.
"""Exact operations on B-splines: knot insertion, clamping, restriction, reversal and
iso-parameter curves.

Every function takes and returns :class:`solidseas.tessellate.nurbs.BSplineCurve`
or ``BSplineSurface``, whose rational control points are homogeneous,
``(w x, w y, w z, w)``, so a knot inserted into a rational spline is inserted into
its homogeneous form and the curve does not move. Parasolid evaluates a spline
flagged periodic over ``[U[p], U[n]]`` like any other, so clamping it at those two
knots gives the same curve with ends a STEP reader takes as they are.
"""

import math
from bisect import bisect_right

from ..tessellate.nurbs import BSplineCurve, BSplineSurface

SNAP = 1e-12  # of a spline's parameter range: a knot this close to one there is that one
MAX_TURNS = 16  # periods a trimmed range may lie from a periodic curve's own range


def _span(U: list[float], n: int, p: int, t: float) -> int:
    if t >= U[n]:
        return n - 1
    if t <= U[p]:
        return p
    return bisect_right(U, t, p, n) - 1


def snap(U: list[float], t: float, p: int, n: int) -> float:
    """``t``, or the knot of ``U`` within :data:`SNAP` of the range of it."""
    tol = SNAP * max(1.0, U[n] - U[p])
    i = bisect_right(U, t)
    for j in (i - 1, i):
        if 0 <= j < len(U) and abs(U[j] - t) <= tol:
            return U[j]
    return t


def insert(p: int, h: list, U: list[float], t: float, times: int) -> tuple[list, list[float]]:
    """Insert ``t`` ``times`` into the knot vector ``U`` of degree ``p`` and control points
    ``h`` (homogeneous where rational), stopping at multiplicity ``p + 1``: Boehm's
    algorithm. Returns the new points and knots."""
    for _ in range(times):
        n = len(h)
        if sum(1 for k in U if k == t) >= p + 1:
            break
        k = _span(U, n, p, t)
        dim = len(h[0])
        out = []
        for i in range(n + 1):
            if i <= k - p:
                out.append(h[i])
            elif i <= k:
                den = U[i + p] - U[i]
                a = (t - U[i]) / den if den != 0.0 else 0.0
                pi, pj = h[i], h[i - 1]
                out.append(tuple(a * pi[d] + (1.0 - a) * pj[d] for d in range(dim)))
            else:
                out.append(h[i - 1])
        U = U[: k + 1] + [t] + U[k + 1 :]
        h = out
    return h, U


def _cut(p: int, h: list, U: list[float], a: float, b: float) -> tuple[list, list[float]]:
    """The points and knots of the piece from ``a`` to ``b`` (each a knot of
    multiplicity ``p + 1`` in ``U``)."""
    first = U.index(a)
    last = len(U) - 1 - U[::-1].index(b)
    knots = U[first : last + 1]
    pts = h[first : last - p]
    if len(knots) != len(pts) + p + 1:
        raise ValueError("cutting a B-spline gave inconsistent knots")
    return pts, knots


def _piece(c: BSplineCurve, a: float, b: float) -> BSplineCurve:
    p = c.p
    h, U = list(c.cps), list(c.U)
    a, b = snap(U, a, p, c.n), snap(U, b, p, c.n)
    for t in (a, b):
        m = sum(1 for k in U if k == t)
        if m < p + 1:
            h, U = insert(p, h, U, t, p + 1 - m)
    pts, knots = _cut(p, h, U, a, b)
    return BSplineCurve(p, pts, knots, c.rational, False)


def clamped(c: BSplineCurve) -> BSplineCurve:
    """The same curve with knots of multiplicity ``p + 1`` at both ends of its range,
    and no longer flagged periodic."""
    return _piece(c, c.lo, c.hi)


def restricted(c: BSplineCurve, a: float, b: float) -> BSplineCurve:
    """The part of ``c`` from ``a`` to ``b`` (``a < b``), exactly, clamped. On a periodic
    curve the range may run across the seam (``b`` past the end of the range, or ``a``
    before its start): the two pieces are joined there."""
    if not (math.isfinite(a) and math.isfinite(b)):
        raise ValueError("a range that is not finite")
    if not a < b:
        raise ValueError("an empty range")
    lo, hi = c.lo, c.hi
    if c.period is not None:
        period = c.period
        if not period > 0.0:
            raise ValueError("a periodic curve of no period")
        # Moved onto the curve's own range in one step: a range many periods away is not
        # a trim Parasolid writes, and moving it a period at a time would never end.
        k = math.floor((a - lo + SNAP * period) / period)
        if abs(k) > MAX_TURNS:
            raise ValueError("a range far outside the curve's own")
        a, b = a - k * period, b - k * period
        if a < lo - SNAP * period:  # rounding: one period at most
            a, b = a + period, b + period
        elif a >= hi - SNAP * period:
            a, b = a - period, b - period
        if b > hi + SNAP * period:
            if b - a > period * (1.0 + SNAP):
                raise ValueError("a range longer than the curve's period")
            first = _piece(c, a, hi) if a < hi else None
            second = _piece(c, lo, b - period)
            if first is None:
                return _shifted(second, period)
            return _joined(first, _shifted(second, period))
    a, b = max(a, lo), min(b, hi)
    if not a < b:
        raise ValueError("the range lies outside the curve")
    return _piece(c, a, b)


def _shifted(c: BSplineCurve, by: float) -> BSplineCurve:
    return BSplineCurve(c.p, list(c.cps), [k + by for k in c.U], c.rational, False)


def _joined(a: BSplineCurve, b: BSplineCurve) -> BSplineCurve:
    """Two clamped curves of one degree, ``a`` ending where ``b`` starts, as one."""
    p = a.p
    hb = list(b.cps)
    if a.rational:
        s = a.cps[-1][-1] / hb[0][-1]  # the same point; scale b's weights to meet a's
        hb = [tuple(x * s for x in c) for c in hb]
    knots = a.U[:-1] + b.U[p + 1 :]
    pts = list(a.cps) + hb[1:]
    return BSplineCurve(p, pts, knots, a.rational, False)


def reversed_curve(c: BSplineCurve) -> BSplineCurve:
    lo, hi = c.U[0], c.U[-1]
    knots = [lo + hi - k for k in reversed(c.U)]
    return BSplineCurve(c.p, list(reversed(c.cps)), knots, c.rational, False)


def _clamp_line(p: int, h: list, U: list[float]) -> tuple[list, list[float]]:
    n = len(h)
    a, b = U[p], U[n]
    for t in (a, b):
        m = sum(1 for k in U if k == t)
        if m < p + 1:
            h, U = insert(p, h, U, t, p + 1 - m)
    return _cut(p, h, U, a, b)


def clamped_surface(s: BSplineSurface) -> BSplineSurface:
    """The same surface with clamped knot vectors in u and in v."""
    rows = s.rows
    # u: each column of control points (fixed v index) is a curve along u
    cols = []
    U = list(s.U)
    for j in range(s.nv):
        h, U2 = _clamp_line(s.pu, [rows[i][j] for i in range(s.nu)], list(s.U))
        cols.append(h)
        U = U2
    nu = len(cols[0])
    grid = [[cols[j][i] for j in range(s.nv)] for i in range(nu)]
    V = list(s.V)
    out = []
    for i in range(nu):
        h, V2 = _clamp_line(s.pv, grid[i], list(s.V))
        out.append(h)
        V = V2
    return BSplineSurface(s.pu, s.pv, out, U, V, s.rational, False, False)


def iso_curve(s: BSplineSurface, direction: str, value: float) -> BSplineCurve:
    """The curve of ``s`` at a fixed parameter, exactly: ``direction`` ``u`` fixes u at
    ``value`` (a curve along v), ``v`` fixes v. The fixed direction's basis functions
    blend the homogeneous control points."""
    from ..tessellate.nurbs import basis

    if direction == "u":
        value = min(max(value, s.ulo), s.uhi)
        k = _span(s.U, s.nu, s.pu, value)
        N = basis(s.U, k, value, s.pu)
        dim = len(s.rows[0][0])
        cps = []
        for j in range(s.nv):
            acc = [0.0] * dim
            for r in range(s.pu + 1):
                c = s.rows[k - s.pu + r][j]
                for d in range(dim):
                    acc[d] += N[r] * c[d]
            cps.append(tuple(acc))
        return BSplineCurve(s.pv, cps, list(s.V), s.rational, s.vperiod is not None)
    value = min(max(value, s.vlo), s.vhi)
    k = _span(s.V, s.nv, s.pv, value)
    N = basis(s.V, k, value, s.pv)
    dim = len(s.rows[0][0])
    cps = []
    for i in range(s.nu):
        acc = [0.0] * dim
        row = s.rows[i]
        for r in range(s.pv + 1):
            c = row[k - s.pv + r]
            for d in range(dim):
                acc[d] += N[r] * c[d]
        cps.append(tuple(acc))
    return BSplineCurve(s.pu, cps, list(s.U), s.rational, s.uperiod is not None)


def euclidean(cps: list, rational: bool) -> tuple[list[tuple[float, ...]], list[float] | None]:
    """Control points as points and weights (None when not rational)."""
    if not rational:
        return [tuple(c) for c in cps], None
    return [tuple(x / c[-1] for x in c[:-1]) for c in cps], [c[-1] for c in cps]


def knot_groups(U: list[float]) -> tuple[list[int], list[float]]:
    """A full knot vector as multiplicities and distinct values."""
    mults: list[int] = []
    knots: list[float] = []
    for k in U:
        if knots and k == knots[-1]:
            mults[-1] += 1
        else:
            knots.append(k)
            mults.append(1)
    return mults, knots
