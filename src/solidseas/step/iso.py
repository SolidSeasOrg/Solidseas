"""Exact iso-parameter curves of SP-curves (new in SolidSeas; upstream approximates them).

An SP_CURVE is a curve in a surface's (u, v). When all its two-dimensional control
points share u (or all share v), it runs along a line u = const (or v = const) of
the surface, and the curve in space is that surface's iso-parameter curve between
the edge's ends, which STEP holds exactly:

* CYLINDER: u const a LINE along the axis, v const a CIRCLE;
* CONE: u const a LINE along the generator (magnitude 1000 / cos a, so that its
  parameter is v), v const a CIRCLE of radius r + v tan a;
* SPHERE: u const the meridian CIRCLE, v const the parallel CIRCLE;
* TORUS (ring, apple or lemon): u const the CIRCLE of the cross-section, v const the
  CIRCLE of radius R + r cos v round the axis (x reversed where that is negative);
* B_SURFACE: the B-spline iso-curve, its homogeneous control points blended at the
  fixed parameter, restricted to the edge's range;
* SWEPT_SURF: u const a LINE along the sweep, v const the section moved by v sweep;
* SPUN_SURF: u const the CIRCLE the profile's point turns on, v const the profile
  turned by v about the axis.

Only the point set matters to an EDGE_CURVE: the moving coordinate's control points
need only be monotone, so the curve runs one way, and the item's direction is
compared with the SP-curve's at the middle of the edge to set ``same_sense``. A
circle of no radius (a parallel at a pole, a cone's apex) and a profile point on a
spun surface's axis are left to the approximations.
"""

import math

from ..tessellate import nurbs
from ..tessellate._vec import add, cross, dot, mul, norm, sub
from ..tessellate.topology import (
    B_CURVE,
    B_SURFACE,
    CIRCLE,
    CONE,
    CYLINDER,
    ELLIPSE,
    LINE,
    SPHERE,
    SPUN_SURF,
    SWEPT_SURF,
    TORUS,
    TRIMMED_CURVE,
    FaceFailed,
)
from . import bspline
from . import entities as E
from . import part21 as p21
from .mapper import CurveMap, Refused, read_bsurface

SAME = 1e-12  # of the parameter span: control points this close share a coordinate


def _unit(v):
    n = norm(v)
    return (v[0] / n, v[1] / n, v[2] / n) if n > 1e-300 else None


def _fixed(c2: nurbs.BSplineCurve):
    """``("u", value)`` when every control point shares u, ``("v", value)`` when every
    one shares v, with the other coordinate monotone; else None."""
    if c2.rational:
        pts = [(c[0] / c[2], c[1] / c[2]) for c in c2.cps]
    else:
        pts = [(c[0], c[1]) for c in c2.cps]
    for k, name in ((0, "u"), (1, "v")):
        vals = [p[k] for p in pts]
        other = [p[1 - k] for p in pts]
        span = max(abs(x) for x in other) + 1.0
        if max(vals) - min(vals) <= SAME * span:
            steps = [b - a for a, b in zip(other, other[1:], strict=False)]
            if all(s >= 0 for s in steps) or all(s <= 0 for s in steps):
                return name, sum(vals) / len(vals)
    return None


def _circle(centre, axis, x_axis, radius):
    if not radius > 1e-12:
        return None
    return E.Circle(E.Placement.make(centre, axis, x_axis), p21.mm(radius))


def _line(point, direction):
    n = norm(direction)
    if not n > 1e-12:
        return None
    return E.Line(E.point_mm(point), E.direction(direction), p21.mm(n))


def _rotate(q, axis, c, s):
    return add(add(mul(q, c), mul(cross(axis, q), s)), mul(axis, dot(axis, q) * (1.0 - c)))


def _moved_curve(mapper, node, offset=None, turn=None):
    """A section or profile curve node written whole, moved by ``offset`` or turned by
    ``turn`` (base, axis, angle): exactly, for lines, conics and B-curves."""
    topo = mapper.topo
    t = node.type
    if t == TRIMMED_CURVE:
        basis = topo.ref(node, "basis_curve")
        if basis is None:
            return None
        if basis.type == B_CURVE:
            p1, p2 = topo.number(node, "parm_1"), topo.number(node, "parm_2")
            spline = bspline.restricted(mapper.bcurve(basis), min(p1, p2), max(p1, p2))
            return _moved_spline(spline, offset, turn)
        node, t = basis, basis.type

    def place(p):
        if offset is not None:
            return add(p, offset)
        base, axis, ang = turn
        return add(base, _rotate(sub(p, base), axis, math.cos(ang), math.sin(ang)))

    def turn_dir(d):
        if offset is not None:
            return d
        _base, axis, ang = turn
        return _rotate(d, axis, math.cos(ang), math.sin(ang))

    if t == LINE:
        return _line(place(topo.vector(node, "pvec")), turn_dir(topo.vector(node, "direction")))
    if t in (CIRCLE, ELLIPSE):
        c = place(topo.vector(node, "centre"))
        n = turn_dir(topo.unit(node, "normal"))
        x = turn_dir(topo.vector(node, "x_axis"))
        if t == CIRCLE:
            return _circle(c, n, x, topo.number(node, "radius"))
        a, b = topo.number(node, "major_radius"), topo.number(node, "minor_radius")
        return E.Ellipse(E.Placement.make(c, n, x), p21.mm(a), p21.mm(b))
    if t == B_CURVE:
        return _moved_spline(bspline.clamped(mapper.bcurve(node)), offset, turn)
    return None


def _moved_spline(spline: nurbs.BSplineCurve, offset, turn):
    cps = []
    for c in spline.cps:
        w = c[3] if spline.rational else 1.0
        p = (c[0] / w, c[1] / w, c[2] / w)
        if offset is not None:
            q = add(p, offset)
        else:
            base, axis, ang = turn
            q = add(base, _rotate(sub(p, base), axis, math.cos(ang), math.sin(ang)))
        cps.append((q[0] * w, q[1] * w, q[2] * w, w) if spline.rational else q)
    return E.BSplineCurve(nurbs.BSplineCurve(spline.p, cps, list(spline.U), spline.rational, False))


def _iso_item(mapper, snode, which: str, value: float, c2, rng):
    """The iso-curve of the surface node (in Parasolid's own (u, v)): an item, or None."""
    topo = mapper.topo
    t = snode.type
    if t in (CYLINDER, CONE):
        P, A, X = topo.vector(snode, "pvec"), topo.unit(snode, "axis"), topo.vector(snode, "x_axis")
        r = topo.number(snode, "radius")
        tan = 0.0
        if t == CONE:
            tan = topo.number(snode, "sin_half_angle") / topo.number(snode, "cos_half_angle")
        frame = _frame(A, X)
        if frame is None:
            return None
        _A, Xn, Yn = frame
        if which == "u":
            e = add(mul(Xn, math.cos(value)), mul(Yn, math.sin(value)))
            return _line(add(P, mul(e, r)), add(A, mul(e, tan)))
        return _circle(add(P, mul(A, value)), A, Xn, r + value * tan)
    if t == SPHERE:
        C, A, X = topo.vector(snode, "centre"), topo.unit(snode, "axis"), topo.vector(snode, "x_axis")
        r = topo.number(snode, "radius")
        frame = _frame(A, X)
        if frame is None:
            return None
        _A, Xn, Yn = frame
        if which == "u":
            e = add(mul(Xn, math.cos(value)), mul(Yn, math.sin(value)))
            return _circle(C, cross(e, A), e, r)
        return _circle(add(C, mul(A, r * math.sin(value))), A, Xn, r * math.cos(value))
    if t == TORUS:
        C, A, X = topo.vector(snode, "centre"), topo.unit(snode, "axis"), topo.vector(snode, "x_axis")
        R, r = topo.number(snode, "major_radius"), topo.number(snode, "minor_radius")
        frame = _frame(A, X)
        if frame is None:
            return None
        _A, Xn, Yn = frame
        if which == "u":
            e = add(mul(Xn, math.cos(value)), mul(Yn, math.sin(value)))
            return _circle(add(C, mul(e, R)), cross(e, A), e, r)
        rho = R + r * math.cos(value)
        centre = add(C, mul(A, r * math.sin(value)))
        if rho < 0.0:  # the circle runs round with x reversed
            return _circle(centre, A, mul(Xn, -1.0), -rho)
        return _circle(centre, A, Xn, rho)
    if t == B_SURFACE:
        # restricted by the caller, which knows the moving range
        return bspline.iso_curve(read_bsurface(topo, snode), which, value)
    if t == SWEPT_SURF:
        section = topo.ref(snode, "section")
        sweep = topo.vector(snode, "sweep")
        if section is None:
            return None
        if which == "u":
            p = mapper.geom.curve(section).point(value)
            return _line(p, sweep)
        return _moved_curve(mapper, section, offset=mul(sweep, value))
    if t == SPUN_SURF:
        profile = topo.ref(snode, "profile")
        if profile is None:
            return None
        B, A = topo.vector(snode, "base"), topo.unit(snode, "axis")
        if which == "u":
            q = mapper.geom.curve(profile).point(value)
            h = dot(sub(q, B), A)
            radial = sub(sub(q, B), mul(A, h))
            rr = norm(radial)
            if not rr > 1e-12:
                return None
            return _circle(add(B, mul(A, h)), A, radial, rr)
        return _moved_curve(mapper, profile, turn=(B, A, value))
    return None


def _frame(A, X):
    x = sub(X, mul(A, dot(X, A)))
    xn = _unit(x)
    if xn is None:
        return None
    return A, xn, cross(A, xn)


def iso_edge(mapper, node, snode, c2, rng, ring, forward):
    """The exact iso-curve of an SP_CURVE edge, as a :class:`.mapper.CurveMap`, or None
    when the curve is not an iso-parameter curve of an exactly written surface."""
    fixed = _fixed(c2)
    if fixed is None:
        return None
    which, value = fixed
    try:
        got = _iso_item(mapper, snode, which, value, c2, rng)
    except (FaceFailed, Refused, ValueError, ZeroDivisionError):
        return None
    if got is None:
        return None
    lo, hi = rng if rng is not None else (c2.lo, c2.hi)
    try:
        ev_sp = mapper.geom.curve(node)
    except FaceFailed:
        return None
    if isinstance(got, nurbs.BSplineCurve):
        # The B-surface's iso-curve: restricted to the moving coordinate's range on the edge.
        k = 1 if which == "u" else 0  # the coordinate that moves along the edge
        m0, m1 = c2.point(lo)[k], c2.point(hi)[k]
        if ring:
            spline = bspline.clamped(got)
        else:
            if m0 == m1:
                return None
            spline = bspline.restricted(got, min(m0, m1), max(m0, m1))
        got = E.BSplineCurve(spline)
    # Which way the item runs along the edge: compare its direction with the SP-curve's
    # at the middle of the edge's range.
    tm = 0.5 * (lo + hi)
    p, d = ev_sp.d1(tm)
    if not forward:
        d = mul(d, -1.0)
    ev = got.evaluator()
    t = ev.param(p, mapper.clock)
    q, dq = ev.d1(t)
    if norm(sub(q, p)) > 1e-9 * (1.0 + norm(p)) or not norm(d) > 0 or not norm(dq) > 0:
        return None  # not where the SP-curve is: leave it to the approximation
    ring_point = ev_sp.point(lo) if ring else None
    return CurveMap(got, dot(d, dq) > 0.0, ring_point=ring_point)
