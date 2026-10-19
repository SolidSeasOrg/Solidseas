"""Hole patterns (``docs/DRAWINGS.md`` 9, C13).

Full holes are grouped by signature (kind, diameters, depth, through or blind, the
direction they enter), then each group of two or more is tested in order:
circular (centres equidistant from the circle through three of them, within 1e-5
of the part's size, and equally spaced round it), arc (on such a circle at an equal
step that does not close it), linear (collinear at an equal pitch), grid (an
axis-aligned lattice at equal pitches), and otherwise scattered, where every
member is located on its own. Members are ordered: by angle from the first round
a pitch circle, the first being the member on a principal axis with the smallest
angle from the frame's first axis when one is on such an axis, else the one whose
angle reduced modulo the step is smallest; from one end of an arc to the other, the
first being the end on a principal axis when only one is, else the end the arc starts
from going counter-clockwise; along the line or row by row otherwise.
Angles within ``ON_AXIS`` of a whole turn are read as nought, and reduced angles that
close to the step as nought too, so a hole on the frame's first axis whose angle comes
out a hair short of 360 degrees is still the first.

An arc of three holes is a pattern only round the axis of another hole or a boss:
three holes at equal distances from one another are any isosceles triangle, which
an L of holes on a plate makes too. Four or more at an equal step stand on their own.
"""

from __future__ import annotations

import math

from .. import keys
from ..types import Axis, Frame, Hole, Pattern
from ._common import AXIS_NAMES, Vec3, dot


def _plane_axes(axis: Vec3, frame: Frame) -> tuple[Vec3, Vec3]:
    """The two frame directions square to ``axis`` (u, v), in frame order."""
    others = [d for d in frame.directions if abs(dot(d, axis)) < 0.5]
    if len(others) == 2:
        return others[0], others[1]
    return frame.directions[0], frame.directions[1]


def _signature(h: Hole) -> tuple:
    """What makes two holes the same: kind, every segment's shape and size, the depth,
    whether through, and the way they enter."""
    return (
        h.kind,
        tuple(
            (s.kind, round(s.diameter, 7), round(s.diameter_end, 7), round(s.depth, 7), round(s.angle, 5))
            for s in h.segments
        ),
        round(h.depth, 7),
        h.through,
        tuple(round(c, 6) for c in h.axis.direction),
    )


def _circle(p1, p2, p3):
    ax, ay = p1
    bx, by = p2
    cx, cy = p3
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-24:
        return None
    ux = (
        (ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)
    ) / d
    uy = (
        (ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)
    ) / d
    return (ux, uy), math.hypot(ax - ux, ay - uy)


def _progression(values: list[float], tol: float) -> float | None:
    """The common step of sorted ``values``, or None when they are not equally spaced."""
    if len(values) < 2:
        return None
    step = values[1] - values[0]
    if step <= tol:
        return None
    for a, b in zip(values, values[1:], strict=False):
        if abs((b - a) - step) > tol:
            return None
    return step


def _distinct(values: list[float], tol: float) -> list[float]:
    out: list[float] = []
    for v in sorted(values):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def recognise_patterns(
    holes: list[Hole], frame: Frame, diagonal: float, first_index: int = 0, hubs: tuple[Axis, ...] = ()
) -> list[Pattern]:
    """Patterns of the holes, whose indices in the feature set start at ``first_index``.
    ``hubs`` are the axes of other round features (bosses) an arc of three may sit round,
    besides the holes' own."""
    tol = max(diagonal * 1e-5, 1e-9)
    groups: dict[tuple, list[int]] = {}
    for k, h in enumerate(holes):
        if h.cover < 2 * math.pi - 1e-9 or h.needs_auxiliary:
            continue
        groups.setdefault(_signature(h), []).append(k)
    out = []
    for _sig, group in sorted(groups.items(), key=lambda kv: (holes[kv[1][0]].axis.point, kv[0])):
        if len(group) < 2:
            continue
        axis = holes[group[0]].axis.direction
        u, v = _plane_axes(axis, frame)
        pts = {k: (dot(holes[k].axis.point, u), dot(holes[k].axis.point, v)) for k in group}
        centres = tuple(
            (dot(a.point, u), dot(a.point, v))
            for a in [h.axis for k, h in enumerate(holes) if k not in pts] + list(hubs)
            if abs(abs(dot(a.direction, axis)) - 1.0) <= 1e-9
        )
        for pattern in _split(holes, group, pts, u, v, tol, centres):
            members = pattern["members"]
            faces = tuple(sorted({f for k in members for f in holes[k].faces}))
            size = dict(holes[members[0]].descriptor.size)
            axes = "".join(AXIS_NAMES[i] for i, dd in enumerate(frame.directions) if abs(dot(dd, axis)) > 0.5)
            d = keys.descriptor(
                "Pattern",
                {"kind": pattern["kind"], "count": len(members), "hole": size.get("diameters", ())},
                {"axis": axes},
                holes[members[0]].descriptor.position,
            )
            out.append(
                Pattern(
                    faces,
                    d,
                    True,
                    pattern["kind"],
                    tuple(first_index + k for k in members),
                    tuple(pattern.get("pitches", ())),
                    tuple(pattern.get("counts", (len(members),))),
                    pattern.get("centre"),
                    pattern.get("pcd", 0.0),
                    pattern.get("step", 0.0),
                    pattern.get("first", 0.0),
                )
            )
    return out


MAX_SEARCH = 60  # members past which a group is only tested whole


def _split(holes, group, pts, u, v, tol, hubs=()) -> list[dict]:
    """A group of equal holes split into patterns: the largest pitch circle or arc first
    (three members or more, equally spaced), then rows at an equal pitch (three or
    more), and what is left as a grid, a pair, or scattered holes."""
    whole = (
        _circular(holes, group, pts, u, v, tol, hubs) or _linear(group, pts, tol) or _grid(group, pts, tol)
    )
    if whole is not None:
        return [whole]
    left = list(group)
    found: list[dict] = []
    if len(left) <= MAX_SEARCH:
        while len(left) >= 3:
            best = _best_circle(holes, left, pts, u, v, tol, hubs)
            if best is None:
                break
            found.append(best)
            left = [k for k in left if k not in best["members"]]
        while len(left) >= 3:
            best = _best_row(left, pts, tol)
            if best is None:
                break
            found.append(best)
            left = [k for k in left if k not in best["members"]]
    if len(left) >= 2:
        rest = _grid(left, pts, tol) or (_linear(left, pts, tol) if len(left) == 2 else None)
        if rest is None:
            order = sorted(left, key=lambda k: (round(pts[k][1], 9), round(pts[k][0], 9)))
            rest = {"kind": "scattered", "members": order}
        found.append(rest)
    return found


def _best_circle(holes, members, pts, u, v, tol, hubs=()):
    best = None
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            for k in range(j + 1, len(members)):
                fit = _circle(pts[members[i]], pts[members[j]], pts[members[k]])
                if fit is None:
                    continue
                (cx, cy), r = fit
                on = [m for m in members if abs(math.hypot(pts[m][0] - cx, pts[m][1] - cy) - r) <= tol]
                if len(on) < 3 or (best is not None and len(on) <= len(best["members"])):
                    continue
                pattern = _circular(holes, on, {m: pts[m] for m in on}, u, v, tol, hubs)
                if pattern is None or (len(on) == 3 and not pattern["step"]):
                    continue
                best = pattern
    return best


def _best_row(members, pts, tol):
    best = None
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            (x0, y0), (x1, y1) = pts[members[i]], pts[members[j]]
            length = math.hypot(x1 - x0, y1 - y0)
            if length <= tol:
                continue
            dx, dy = (x1 - x0) / length, (y1 - y0) / length
            on = [m for m in members if abs((pts[m][0] - x0) * dy - (pts[m][1] - y0) * dx) <= tol]
            if len(on) < 3 or (best is not None and len(on) <= len(best["members"])):
                continue
            row = _linear(on, pts, tol)
            if row is not None:
                best = row
    return best


def _collinear(points, tol: float) -> bool:
    """Whether ``points`` lie on one straight line within ``tol``: their distance from the
    line through two of them far apart (the one farthest from the first, then the one
    farthest from that)."""
    p = max(points, key=lambda q: math.dist(points[0], q))
    q = max(points, key=lambda r: math.dist(p, r))
    length = math.dist(p, q)
    if length <= tol:
        return True
    return all(
        abs((q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])) / length <= tol for r in points
    )


def _circular(holes, members, pts, u, v, tol, hubs=()):
    if len(members) < 3:
        return None
    # A row of centres is never a circle: three centres that are straight but for the last
    # bits of their coordinates fit a circle of enormous radius, which every member of the
    # row then lies on within tol (a pitch circle light-years across).
    if _collinear([pts[k] for k in members], tol):
        return None
    a, b, c = (pts[k] for k in members[:3])
    fit = _circle(a, b, c)
    if fit is None:
        return None
    (cx, cy), r = fit
    if any(abs(math.hypot(p[0] - cx, p[1] - cy) - r) > tol for p in pts.values()):
        return None
    angles = {k: _turn(math.atan2(pts[k][1] - cy, pts[k][0] - cx), 2 * math.pi) for k in members}
    n = len(members)
    step = 2 * math.pi / n
    # a member on a centre line needs no angle, so it is the first when there is one;
    # otherwise the member nearest the first axis counter-clockwise (C13)
    on_axis = [k for k in members if _on_axis(angles[k])]
    first = min(on_axis or members, key=lambda k: (round(_turn(angles[k], step), 9), angles[k]))
    ordered = sorted(members, key=lambda k: (angles[k] - angles[first]) % (2 * math.pi))
    spaced = all(
        abs(((angles[ordered[(i + 1) % n]] - angles[ordered[i]]) % (2 * math.pi)) - step) <= 1e-6
        for i in range(n)
    )
    kind = "circular"
    if not spaced:
        # Holes on a circle at uneven angles are no pitch circle: any rectangle's or
        # isosceles trapezoid's four corners lie on one, and drawn as a pitch circle with
        # angles they gave a dashed circle round the part and dimensions nobody asked for.
        # They may still be an arc at an equal step that leaves the rest of the circle open.
        arc = _arc(members, angles)
        if arc is None:
            return None
        if n == 3 and not any(math.hypot(h[0] - cx, h[1] - cy) <= tol for h in hubs):
            return None
        kind, ordered, step = "arc", arc[0], arc[1]
        first = ordered[0]
    w = holes[members[0]].axis.point
    along_axis = dot(w, holes[members[0]].axis.direction)
    d = holes[members[0]].axis.direction
    rest = tuple(cx * u[i] + cy * v[i] + along_axis * d[i] for i in range(3))
    return {
        "kind": kind,
        "members": ordered,
        "centre": rest,
        "pcd": 2 * r,
        "step": step,
        "first": angles[first],
        "counts": (n,),
    }


ON_AXIS = 1e-6  # radians from a principal axis: a member there is located by the centre lines


def _turn(a: float, period: float) -> float:
    """``a`` reduced into [0, ``period``), a value within ``ON_AXIS`` of ``period`` read as
    nought: atan2 puts a centre on the first axis a few ulps either side of it, and the
    side below would otherwise read as nearly a whole turn."""
    r = a % period
    return 0.0 if period - r <= ON_AXIS else r


def _on_axis(a: float) -> bool:
    return abs(math.remainder(a, math.pi / 2)) <= ON_AXIS


def _arc(members, angles) -> tuple[list[int], float] | None:
    """(members from the first end to the other, the step) of holes on a circle at one
    equal step whose widest gap leaves the circle open, or None. The arc runs
    counter-clockwise from the end after that gap, reversed when only its far end lies
    on a principal axis, so that end needs no angle."""
    n = len(members)
    order = sorted(members, key=lambda k: angles[k])
    gaps = [(angles[order[(i + 1) % n]] - angles[order[i]]) % (2 * math.pi) for i in range(n)]
    wide = max(range(n), key=lambda i: gaps[i])
    ordered = order[wide + 1 :] + order[: wide + 1]
    inner = [gaps[(wide + 1 + i) % n] for i in range(n - 1)]
    step = inner[0]
    if step <= 1e-9 or any(abs(g - step) > 1e-6 for g in inner) or gaps[wide] <= step + 1e-6:
        return None

    if _on_axis(angles[ordered[-1]]) and not _on_axis(angles[ordered[0]]):
        ordered.reverse()
    return ordered, step


def _linear(members, pts, tol):
    if len(members) < 2:
        return None
    ordered = sorted(members, key=lambda k: (pts[k][0], pts[k][1]))
    (x0, y0), (x1, y1) = pts[ordered[0]], pts[ordered[-1]]
    length = math.hypot(x1 - x0, y1 - y0)
    if length <= tol:
        return None
    dx, dy = (x1 - x0) / length, (y1 - y0) / length
    for k in ordered:
        px, py = pts[k][0] - x0, pts[k][1] - y0
        if abs(px * dy - py * dx) > tol:
            return None
    ts = [(pts[k][0] - x0) * dx + (pts[k][1] - y0) * dy for k in ordered]
    pitch = _progression(sorted(ts), tol)
    if pitch is None:
        return None
    ordered = [k for _t, k in sorted(zip(ts, ordered, strict=True))]
    return {"kind": "linear", "members": ordered, "pitches": (pitch,), "counts": (len(members),)}


def _grid(members, pts, tol):
    us = _distinct([p[0] for p in pts.values()], tol)
    vs = _distinct([p[1] for p in pts.values()], tol)
    if len(us) < 2 or len(vs) < 2 or len(us) * len(vs) != len(members):
        return None
    du, dv = _progression(us, tol), _progression(vs, tol)
    if du is None or dv is None:
        return None
    ordered = sorted(members, key=lambda k: (round(pts[k][1] / tol), round(pts[k][0] / tol)))
    return {"kind": "grid", "members": ordered, "pitches": (du, dv), "counts": (len(us), len(vs))}


__all__ = ["recognise_patterns"]
