"""Exact entities for the runs a view keeps (``docs/DRAWINGS.md`` 8.8, C6).

A run of a straight edge or a cylinder's or cone's silhouette is a ``Segment``; a
run of a circle in a plane square to the view an ``Arc``; a circle in an oblique
plane an ``EllipseArc`` (its projection is exactly an ellipse); a circle seen
edge-on a ``Segment``; a whole B-spline edge a ``Spline`` with its control points
projected (an orthographic projection is affine, so the projected curve is
exact); everything else a ``Polyline`` through the samples. Coordinates are the
view plane's, in metres.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from ..display import Arc, EllipseArc, Polyline, Segment, Spline
from ..facegraph import Curve
from .hlr import dot

Vec3 = tuple[float, float, float]
Point = tuple[float, float]
PARALLEL = 1e-9


def project(p: Vec3, frame) -> Point:
    right, up, _d = frame
    return (dot(p, right), dot(p, up))


def _unwrap(angles: list[float]) -> list[float]:
    out = [angles[0]]
    for a in angles[1:]:
        while a - out[-1] > math.pi:
            a -= 2 * math.pi
        while a - out[-1] < -math.pi:
            a += 2 * math.pi
        out.append(a)
    return out


def _cross3(a, b) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit3(a) -> Vec3:
    n = math.sqrt(dot(a, a))
    return (a[0] / n, a[1] / n, a[2] / n)


def _circle_run(curve: Curve, pts: Sequence[Vec3], frame, closed: bool):
    right, up, d = frame
    n = curve.direction
    c3 = curve.point
    centre = project(c3, frame)
    nd = dot(n, d)
    if abs(abs(nd) - 1.0) <= PARALLEL:
        if closed:
            return Arc(centre, curve.radius, 0.0, 360.0)
        ang = _unwrap([math.atan2(dot(p, up) - centre[1], dot(p, right) - centre[0]) for p in pts])
        a0, a1 = ang[0], ang[-1]
        if a1 < a0:
            a0, a1 = a1, a0
        return Arc(centre, curve.radius, math.degrees(a0), math.degrees(a1))
    if abs(nd) <= PARALLEL:
        # seen edge-on: a line along N x d, as far as the run's angles reach
        m3 = _unit3(_cross3(n, d))
        x3 = curve.x
        y3 = _cross3(n, x3)
        phi = math.atan2(dot(y3, m3), dot(x3, m3))
        rel = [tuple(p[k] - c3[k] for k in range(3)) for p in pts]
        thetas = _unwrap([math.atan2(dot(q, y3), dot(q, x3)) for q in rel])
        lo_t, hi_t = min(thetas), max(thetas)
        if closed or hi_t - lo_t >= 2 * math.pi - 1e-12:
            ends = (-curve.radius, curve.radius)
        else:
            vals = [curve.radius * math.cos(t - phi) for t in (lo_t, hi_t)]
            for extreme, target in ((curve.radius, phi), (-curve.radius, phi + math.pi)):
                k = math.ceil((lo_t - target) / (2 * math.pi))
                if target + 2 * math.pi * k <= hi_t:
                    vals.append(extreme)
            ends = (min(vals), max(vals))
        a = tuple(c3[k] + m3[k] * ends[0] for k in range(3))
        b = tuple(c3[k] + m3[k] * ends[1] for k in range(3))
        return Segment(project(a, frame), project(b, frame))
    # an oblique circle projects to an ellipse: the major axis lies along N x d
    m3 = tuple(n[(k + 1) % 3] * d[(k + 2) % 3] - n[(k + 2) % 3] * d[(k + 1) % 3] for k in range(3))
    length = math.sqrt(dot(m3, m3))
    m3 = tuple(c / length * curve.radius for c in m3)
    major = (dot(m3, right), dot(m3, up))
    ratio = abs(nd)
    minor = (-major[1] * ratio, major[0] * ratio)
    mm = major[0] ** 2 + major[1] ** 2
    nn = minor[0] ** 2 + minor[1] ** 2

    def param(p):
        q = project(p, frame)
        x, y = q[0] - centre[0], q[1] - centre[1]
        return math.atan2((x * minor[0] + y * minor[1]) / nn, (x * major[0] + y * major[1]) / mm)

    if closed:
        return EllipseArc(centre, major, ratio, 0.0, 2 * math.pi)
    ts = _unwrap([param(p) for p in pts])
    t0, t1 = ts[0], ts[-1]
    if t1 < t0:
        t0, t1 = t1, t0
    return EllipseArc(centre, major, ratio, t0, t1)


def edge_primitive(curve: Curve, pts: Sequence[Vec3], frame, *, whole: bool, closed: bool):
    """The display primitive for a run of an edge: ``pts`` are its 3D samples, ``whole``
    says the run is the whole edge, ``closed`` that the edge is a ring."""
    if curve.kind == "line" and len(pts) >= 2:
        return Segment(project(pts[0], frame), project(pts[-1], frame))
    if curve.kind == "circle" and len(pts) >= 2:
        return _circle_run(curve, pts, frame, closed and whole)
    if curve.kind == "bspline" and whole and curve.points and curve.degree >= 1:
        if len(curve.knots) == len(curve.points) + curve.degree + 1:
            return Spline(
                curve.degree,
                tuple(curve.knots),
                tuple(project(p, frame) for p in curve.points),
                curve.weights,
            )
    return Polyline(tuple(project(p, frame) for p in pts), closed and whole)


def silhouette_primitive(pts: Sequence[Vec3], frame, straight: bool):
    if straight and len(pts) >= 2:
        return Segment(project(pts[0], frame), project(pts[-1], frame))
    return Polyline(tuple(project(p, frame) for p in pts))


def straight(prim) -> tuple[Point, Point] | None:
    """A primitive's two ends when it is a straight line."""
    if isinstance(prim, Segment):
        return prim.p0, prim.p1
    return None


__all__ = ["edge_primitive", "project", "silhouette_primitive", "straight"]
