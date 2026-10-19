"""Holes and bosses (``docs/DRAWINGS.md`` 9).

A hole is a connected set of concave revolved faces on one axis, joined through
the planar faces square to that axis that lie wholly inside it (shoulders and flat
bottoms). Coaxial faces of one diameter are merged, so seam halves count once, and
the hole is complete when its smallest bore's faces leave no gap wider than 31
degrees round the axis. Concave faces covering 180 degrees or less are fillets and
slot ends, not holes; between 180 and 329 degrees a hole is partial.

Classification, from the entry: a counterbore (or a spotface, when it is 1 mm deep
or less) is a bore ending on a planar shoulder; a countersink is a cone at the
entry of 60, 82, 90, 100, 110 or 120 degrees included; stepped holes change
diameter through a cone; another cone at the entry is tapered; a 118 degree cone
(within 6) closing the far end is a drill point. A small cone or a round at the
entry, within the edge-break range, belongs to the hole as its entry break (C12).

Each end is ``open``, ``blind`` (a flat bottom or drill point) or ``into_bore``
(it ends on another hole's wall); THRU needs both open. Blind depth is to the full
diameter, never the drill point. Bosses are convex complete cylinders, by axis.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .. import keys
from ..facegraph import BrepModel, Cone, Cylinder, Face, Plane, Torus
from ..numbers import plain_sum
from ..standards import threads_for_drill
from ..types import Axis, Boss, Frame, Hole, HoleSegment
from ._common import (
    COVER_GAP_DEG,
    Rays,
    Vec3,
    add,
    along,
    angular_cover,
    dot,
    edges_by_face,
    extent,
    mul,
    norm,
    sub,
)

COUNTERSINK_ANGLES = (60.0, 82.0, 90.0, 100.0, 110.0, 120.0)
COUNTERSINK_TOL = 1.0  # degrees
DRILL_POINT = 118.0
DRILL_POINT_TOL = 6.0
SPOTFACE_MAX = 1e-3  # metres: a counterbore this shallow or less is a spotface
EDGE_BREAK_MAX = 0.5e-3  # metres: an entry cone or round this small is an edge break


@dataclass
class _Seg:
    near: float
    far: float
    kind: str
    faces: list[int]
    d0: float = 0.0
    d1: float = 0.0
    angle: float = 0.0  # included, degrees here; a HoleSegment holds it in radians (6.4)


def _on_axis(edge, point: Vec3, axis: Vec3, tol: float) -> bool:
    c = edge.curve
    if c.kind != "circle":
        return False
    rel = sub(c.point, point)
    off = sub(rel, mul(axis, dot(rel, axis)))
    return norm(off) <= tol and abs(abs(dot(c.direction, axis)) - 1.0) <= 1e-6


def _internal_plane(model: BrepModel, face: Face, point: Vec3, axis: Vec3, concave: set[int]) -> bool:
    """A planar face square to the axis bounded only by circles on it, each shared with
    a concave revolved face of the axis: a shoulder or a flat bottom inside the hole
    (a boss's top or a groove's floor borders a convex wall, so it is not one)."""
    s = face.surface
    if not isinstance(s, Plane) or abs(abs(dot(s.normal, axis)) - 1.0) > 1e-6:
        return False
    edges = [model.edges[k] for lp in face.loops for k in lp if k in model.edges]
    if not edges:
        return False
    for e in edges:
        if not _on_axis(e, point, axis, model.tolerance * 10):
            return False
        if any(f != face.index and f not in concave for f in e.faces):
            return False
    return True


def _components(model: BrepModel, members: set[int]) -> list[list[int]]:
    seen: set[int] = set()
    out = []
    for start in sorted(members):
        if start in seen:
            continue
        stack, comp = [start], []
        seen.add(start)
        while stack:
            f = stack.pop()
            comp.append(f)
            for n in model.faces[f].neighbours:
                if n in members and n not in seen:
                    seen.add(n)
                    stack.append(n)
        out.append(sorted(comp))
    return out


def _end_state(model, rays: Rays, comp_faces, axis, point, end_value, sign, diameter, others) -> str:
    """Whether a hole's end opens out, is closed, or runs into another hole."""
    tol = model.tolerance * 10
    # faces across the end loop: neighbours of the component touching the end plane
    for f in comp_faces:
        for n in f.neighbours:
            if n in others:
                continue
            g = model.faces[n]
            lo, hi = extent(model, g, axis)
            if abs(lo - end_value) > max(tol, diameter) and abs(hi - end_value) > max(tol, diameter):
                continue
            s = g.surface
            if isinstance(s, (Cylinder, Cone)) and s.concave and abs(abs(dot(s.axis, axis)) - 1.0) > 1e-6:
                return "into_bore"
    eps = max(model.diagonal * 1e-4, diameter * 0.01)
    probe = add(point, mul(axis, end_value - dot(point, axis) + sign * eps))
    direction = mul(axis, sign)
    if rays.along(direction).inside(probe):
        return "blind"
    return "open"


def _segments(model, comp, axis, point, entry_value, sign) -> list[_Seg]:
    """The component's faces as segments ordered from the entry; depth measured into
    the material."""
    segs: list[_Seg] = []
    for i in comp:
        f = model.faces[i]
        lo, hi = extent(model, f, axis)
        a, b = (entry_value - hi, entry_value - lo) if sign > 0 else (lo - entry_value, hi - entry_value)
        near, far = min(a, b), max(a, b)
        s = f.surface
        if isinstance(s, Cylinder):
            segs.append(_Seg(near, far, "cylinder", [i], 2 * s.radius, 2 * s.radius))
        elif isinstance(s, Cone):
            at_near = entry_value - sign * near
            at_far = entry_value - sign * far
            r_near = _cone_radius(s, at_near, axis)
            r_far = _cone_radius(s, at_far, axis)
            segs.append(
                _Seg(near, far, "cone", [i], 2 * r_near, 2 * r_far, math.degrees(2 * abs(s.half_angle)))
            )
        elif isinstance(s, Plane):
            radii = sorted(
                {round(model.edges[k].curve.radius, 12) for lp in f.loops for k in lp if k in model.edges}
            )
            if len(f.loops) >= 2 and len(radii) >= 2:
                segs.append(_Seg(near, far, "annulus", [i], 2 * radii[-1], 2 * radii[0]))
            else:
                segs.append(_Seg(near, far, "flat_bottom", [i], 2 * radii[-1] if radii else 0.0))
    segs.sort(key=lambda s: (s.near, s.kind != "annulus", s.far))
    # merge coaxial pieces of one segment (seam halves, split faces)
    merged: list[_Seg] = []
    for s in segs:
        last = merged[-1] if merged else None
        if (
            last is not None
            and last.kind == s.kind
            and abs(last.d0 - s.d0) <= model.tolerance * 10
            and abs(last.d1 - s.d1) <= model.tolerance * 10
            and s.near <= last.far + model.tolerance * 10
        ):
            last.far = max(last.far, s.far)
            last.faces += s.faces
        else:
            merged.append(s)
    return merged


def _cone_radius(s: Cone, axial: float, axis: Vec3) -> float:
    along_axis = (axial - dot(s.point, axis)) * (1.0 if dot(s.axis, axis) > 0 else -1.0)
    return max(0.0, s.radius + math.tan(s.half_angle) * along_axis)


def _kind(segs: list[_Seg], closing: str | None) -> tuple[str, tuple | None]:
    """The hole's kind and its entry break, from its segments."""
    parts: list[str] = []
    entry_break = None
    body = [s for s in segs if not (closing == "point" and s is segs[-1])]
    if body and body[0].kind == "cone":
        first = body[0]
        leg = (first.d0 - first.d1) / 2
        if leg <= EDGE_BREAK_MAX:
            entry_break = ("chamfer", leg, tuple(first.faces))
        elif any(abs(first.angle - a) <= COUNTERSINK_TOL for a in COUNTERSINK_ANGLES):
            parts.append("countersink")
        else:
            parts.append("tapered")
    for k, s in enumerate(body):
        if s.kind == "annulus" and k > 0 and body[k - 1].kind == "cylinder":
            depth = body[k - 1].far - body[k - 1].near
            name = "spotface" if depth <= SPOTFACE_MAX else "counterbore"
            if name not in parts:
                parts.insert(0, name)
        if s.kind == "cone" and 0 < k < len(body) - 1 and "stepped" not in parts:
            parts.append("stepped")
    return "+".join(parts) or "simple", entry_break


def recognise_holes(model: BrepModel, frame: Frame, rays: Rays, claimed: dict[int, str]):
    """Holes and bosses: (holes, bosses), each a list of (feature, sort key)."""
    holes = []
    bosses = []
    tol = model.tolerance * 10
    by_face = edges_by_face(model)
    for group in model.axis_groups:
        A, P = group.direction, group.point
        faces = [model.faces[i] for i in group.faces]
        free = [f for f in faces if f.index not in claimed]
        concave = {f.index for f in free if isinstance(f.surface, (Cylinder, Cone)) and f.surface.concave}
        convex_cyl = [f for f in free if isinstance(f.surface, Cylinder) and not f.surface.concave]
        if convex_cyl:
            gap = angular_cover(model, convex_cyl, P, A)
            if gap <= COVER_GAP_DEG:
                for r in sorted({round(f.surface.radius, 12) for f in convex_cyl}):
                    mine = [f for f in convex_cyl if abs(f.surface.radius - r) <= tol]
                    if angular_cover(model, mine, P, A) > COVER_GAP_DEG:
                        continue
                    lo = min(extent(model, f, A)[0] for f in mine)
                    hi = max(extent(model, f, A)[1] for f in mine)
                    centre = add(P, mul(A, (lo + hi) / 2 - dot(P, A)))
                    d = keys.descriptor(
                        "Boss",
                        {"diameter": 2 * r, "length": hi - lo},
                        {"axis": _axis_word(A, frame)},
                        _position(centre, A, frame),
                    )
                    boss = Boss(tuple(f.index for f in mine), d, True, Axis(centre, A), 2 * r, hi - lo)
                    bosses.append((boss, _sort_key(centre, frame)))
                    for f in mine:
                        claimed[f.index] = "boss"
        if not concave:
            continue
        internal = set()
        for i in concave:
            for n in model.faces[i].neighbours:
                if n not in claimed and _internal_plane(model, model.faces[n], P, A, concave):
                    internal.add(n)
        for comp in _components(model, concave | internal):
            cyl = [model.faces[i] for i in comp if isinstance(model.faces[i].surface, Cylinder)]
            if not cyl:
                continue
            d_min = min(f.surface.radius for f in cyl)
            bore = [f for f in cyl if abs(f.surface.radius - d_min) <= tol]
            gap = angular_cover(model, bore, P, A)
            if 360.0 - gap <= 180.0 + 1e-6:
                continue  # a fillet or a slot end
            comp_faces = [model.faces[i] for i in comp]
            lo = min(extent(model, f, A)[0] for f in comp_faces)
            hi = max(extent(model, f, A)[1] for f in comp_faces)
            closing = {}
            for value, sign in ((lo, -1), (hi, 1)):
                for f in comp_faces:
                    s = f.surface
                    flo, fhi = extent(model, f, A)
                    at_end = abs((flo if sign < 0 else fhi) - value) <= tol
                    if not at_end:
                        continue
                    if isinstance(s, Plane) and len(f.loops) == 1:
                        closing[sign] = "flat"
                    elif (
                        isinstance(s, Cone) and s.apex is not None and abs(dot(s.apex, A) - value) <= tol * 10
                    ):
                        if abs(math.degrees(2 * abs(s.half_angle)) - DRILL_POINT) <= DRILL_POINT_TOL:
                            closing[sign] = "point"
                        else:
                            closing[sign] = "cone"
            states = {}
            for value, sign in ((lo, -1), (hi, 1)):
                if sign in closing:
                    states[sign] = "blind"
                else:
                    states[sign] = _end_state(
                        model, rays, comp_faces, A, P, value, sign, 2 * d_min, set(comp)
                    )
            # the entry: the open end; of two, the wider; of equals, the one toward +axis
            open_ends = [s for s in (1, -1) if states[s] == "open"]
            if len(open_ends) == 1:
                entry_sign = open_ends[0]
            else:
                width = {}
                for value, sign in ((lo, -1), (hi, 1)):
                    width[sign] = max(
                        (2 * _radius_at_end(model.faces[i], value, A) for i in comp), default=0.0
                    )
                if abs(width[1] - width[-1]) > tol:
                    entry_sign = 1 if width[1] > width[-1] else -1
                else:
                    entry_sign = 1 if _toward_positive(A, frame) else -1
            entry_value = hi if entry_sign > 0 else lo
            far_sign = -entry_sign
            segs = _segments(model, comp, A, P, entry_value, entry_sign)
            close = closing.get(far_sign)
            kind, entry_break = _kind(segs, close)
            entry_face, entry_kind, round_break = _entry(model, comp, A, entry_value, tol, by_face)
            if round_break is not None:
                entry_break = round_break
            hole_segments = []
            for s in segs:
                if s.kind == "cone" and close == "point" and s is segs[-1]:
                    hole_segments.append(
                        HoleSegment(
                            "drill_point", s.d0, 0.0, s.far - s.near, math.radians(s.angle), tuple(s.faces)
                        )
                    )
                elif s.kind == "cone":
                    hole_segments.append(
                        HoleSegment("cone", s.d0, s.d1, s.far - s.near, math.radians(s.angle), tuple(s.faces))
                    )
                elif s.kind == "cylinder":
                    hole_segments.append(
                        HoleSegment("cylinder", s.d0, s.d0, s.far - s.near, 0.0, tuple(s.faces))
                    )
                else:
                    hole_segments.append(HoleSegment(s.kind, s.d0, s.d1, 0.0, 0.0, tuple(s.faces)))
            ends = (
                ("open", states[far_sign])
                if states[entry_sign] == "open"
                else (states[entry_sign], states[far_sign])
            )
            through = ends == ("open", "open")
            last_cyl = max((s for s in segs if s.kind == "cylinder"), key=lambda s: s.far, default=None)
            depth = (hi - lo) if through else (last_cyl.far if last_cyl else hi - lo)
            entry_point = add(P, mul(A, entry_value - dot(P, A)))
            into = mul(A, -entry_sign)
            on_frame = along(A, frame.directions) is not None
            needs_aux = not on_frame or entry_kind == "planar_oblique"
            diameter = 2 * d_min
            threads = tuple(t.designation for t in threads_for_drill(diameter)) if kind == "simple" else ()
            descriptor = keys.descriptor(
                "Hole",
                {
                    "kind": kind,
                    "diameters": tuple(
                        sorted({round(s.d0, 9) for s in segs if s.kind == "cylinder"}, reverse=True)
                    ),
                    "depth": depth,
                    "through": through,
                    "segments": tuple(s.kind for s in segs),
                },
                {"entry": _axis_word(into, frame), "entry_kind": entry_kind},
                _position(entry_point, A, frame),
            )
            all_faces = list(comp) + (list(entry_break[2]) if entry_break else [])
            hole = Hole(
                tuple(sorted(set(all_faces))),
                descriptor,
                True,
                Axis(entry_point, into),
                entry_face,
                entry_kind,
                tuple(hole_segments),
                kind,
                ends,
                depth,
                entry_face,
                2 * math.pi if gap <= COVER_GAP_DEG else math.radians(360.0 - gap),
                entry_break,
                threads,
                needs_aux,
            )
            holes.append((hole, _sort_key(entry_point, frame)))
            for i in all_faces:
                claimed[i] = "hole"
    holes.sort(key=lambda h: h[1])
    bosses.sort(key=lambda b: b[1])
    return [h for h, _k in holes], [b for b, _k in bosses]


def _radius_at_end(face: Face, value: float, axis: Vec3) -> float:
    s = face.surface
    if isinstance(s, Cylinder):
        return s.radius
    if isinstance(s, Cone):
        return _cone_radius(s, value, axis)
    return 0.0


def _entry(model: BrepModel, comp, axis, entry_value, tol, by_face):
    """The face the hole enters through, its kind, and an entry round (a convex torus
    on the axis between the hole and that face). A face counts when it shares an edge
    with the hole at the entry end."""
    members = set(comp)
    round_break = None
    candidates = []

    def at_entry(edge) -> bool:
        return all(abs(dot(p, axis) - entry_value) <= tol * 10 for p in (edge.points[0], edge.points[-1]))

    for i in comp:
        for e in by_face.get(i, ()):
            if not at_entry(e):
                continue
            for n in e.faces:
                if n < 0 or n in members:
                    continue
                g = model.faces[n]
                s = g.surface
                if isinstance(s, Torus) and abs(abs(dot(s.axis, axis)) - 1.0) <= 1e-6:
                    round_break = ("round", s.minor, (n,))
                    for e2 in by_face.get(n, ()):
                        candidates += [
                            model.faces[m] for m in e2.faces if m >= 0 and m != n and m not in members
                        ]
                else:
                    candidates.append(g)
    best = None
    for g in candidates:
        s = g.surface
        if isinstance(s, Plane):
            square = abs(abs(dot(s.normal, axis)) - 1.0) <= 1e-6
            rank = 0 if square else 1
            kind = "planar_square" if square else "planar_oblique"
        else:
            rank, kind = 2, "curved"
        if best is None or (rank, g.index) < best[0]:
            best = ((rank, g.index), g.index, kind)
    if best is None:
        return -1, "curved", round_break
    return best[1], best[2], round_break


def _toward_positive(axis: Vec3, frame: Frame) -> bool:
    hit = along(axis, frame.directions)
    if hit is not None:
        return hit[1] > 0
    return plain_sum(axis) >= 0


def _axis_word(direction: Vec3, frame: Frame) -> str:
    hit = along(direction, frame.directions)
    if hit is None:
        return "oblique"
    return ("+" if hit[1] > 0 else "-") + hit[0]


def _position(point: Vec3, axis: Vec3 | None, frame: Frame) -> tuple[float, ...]:
    """A point in the frame, measured from the frame's low extents (datum offsets come
    from the drawing), with the coordinate along ``axis`` left out."""
    out = []
    for d, (lo, _hi) in zip(frame.directions, frame.extents or ((0.0, 0.0),) * 3, strict=False):
        if axis is not None and abs(abs(dot(axis, d)) - 1.0) <= 1e-6:
            continue
        out.append(dot(point, d) - lo)
    return tuple(out)


def _sort_key(point: Vec3, frame: Frame) -> tuple:
    return tuple(round(dot(point, d), 9) for d in frame.directions)


__all__ = ["COUNTERSINK_ANGLES", "recognise_holes"]
