"""Slots, pockets, steps and their depths (``docs/DRAWINGS.md`` 9, C11, C17).

- A slot is two concave half cylinders (150 to 210 degrees) of equal radius with
  parallel axes, joined by two planar walls tangent to both and facing each other
  2r apart; through, or with a floor and a depth.
- A pocket floor is a planar face whose sharp edges are all concave; its walls are
  the faces across them, its depth is measured from the open face (a planar face
  beyond the walls facing the same way), and its corner radius is that of its
  concave cylindrical walls.
- A step is a planar face square to a frame axis with both concave and convex
  sharp edges.

Depths are records of their own (``types.Depth``): the floor, the open face, the
axis and the value, so the planner can draw one or, when every view hides it, say
it in a note.
"""

from __future__ import annotations

from .. import keys
from ..facegraph import BrepModel, Cylinder, Plane
from ..types import Depth, Frame, Pocket, Slot, Step
from ._common import Vec3, along, angular_cover, cross, dot, edges_by_face, extent, norm, sub, unit
from .holes import _position, _sort_key

SLOT_COVER = (150.0, 210.0)


def _sharp(e) -> bool:
    return e.kind in ("convex", "concave")


def _axis_name(direction: Vec3, frame: Frame) -> str | None:
    hit = along(direction, frame.directions)
    return hit[0] if hit else None


def _open_face(model: BrepModel, floor, walls, by_face) -> tuple[int, float] | None:
    """The planar face beyond the walls that faces the way the floor does, and the
    depth from it to the floor."""
    n = floor.surface.normal
    best = None
    for w in walls:
        for e in by_face.get(w, []):
            for m in e.faces:
                if m in (w, floor.index) or m < 0:
                    continue
                g = model.faces[m]
                if not isinstance(g.surface, Plane) or dot(g.surface.normal, n) < 1 - 1e-6:
                    continue
                depth = g.surface.offset - floor.surface.offset
                if depth > model.tolerance and (best is None or depth < best[1]):
                    best = (m, depth)
    return best


def recognise_slots(
    model: BrepModel, frame: Frame, claimed: dict[int, str]
) -> tuple[list[Slot], list[Depth]]:
    by_face = edges_by_face(model)
    tol = model.tolerance * 10
    halves = []
    for f in model.faces:
        s = f.surface
        if f.index in claimed or not isinstance(s, Cylinder) or not s.concave:
            continue
        cover = 360.0 - angular_cover(model, [f], s.point, s.axis)
        if SLOT_COVER[0] <= cover <= SLOT_COVER[1]:
            halves.append(f)
    slots, depths = [], []
    used: set[int] = set()
    for i, a in enumerate(halves):
        for b in halves[i + 1 :]:
            if a.index in used or b.index in used:
                continue
            sa, sb = a.surface, b.surface
            if abs(sa.radius - sb.radius) > tol or abs(abs(dot(sa.axis, sb.axis)) - 1) > 1e-6:
                continue
            walls_a = {
                m for e in by_face.get(a.index, []) if e.kind == "tangent" for m in e.faces if m != a.index
            }
            walls_b = {
                m for e in by_face.get(b.index, []) if e.kind == "tangent" for m in e.faces if m != b.index
            }
            walls = sorted(m for m in walls_a & walls_b if isinstance(model.faces[m].surface, Plane))
            if len(walls) != 2:
                continue
            w1, w2 = (model.faces[m].surface for m in walls)
            if dot(w1.normal, w2.normal) > -1 + 1e-6:
                continue
            gap = abs(w1.offset + w2.offset)  # antiparallel normals: offsets of opposite sign
            if abs(gap - 2 * sa.radius) > tol * 10:
                continue
            axis = sa.axis
            ca = sa.point
            cb = sub(sb.point, tuple(axis[k] * dot(sub(sb.point, sa.point), axis) for k in range(3)))
            direction = unit(sub(cb, ca))
            centres = norm(sub(cb, ca))
            floor = None
            for e in by_face.get(a.index, []):
                for m in e.faces:
                    g = model.faces[m] if m >= 0 else None
                    if (
                        g is not None
                        and m != a.index
                        and isinstance(g.surface, Plane)
                        and abs(abs(dot(g.surface.normal, axis)) - 1) < 1e-6
                        and e.kind == "concave"
                    ):
                        floor = g
            faces = [a.index, b.index, *walls]
            depth_value = None
            if floor is not None:
                opened = _open_face(model, floor, walls, by_face)
                if opened is not None:
                    depth_value = opened[1]
                    faces.append(floor.index)
                    depths.append(
                        Depth(
                            floor.index, opened[0], _axis_name(floor.surface.normal, frame) or "", opened[1]
                        )
                    )
            mid = tuple((ca[k] + cb[k]) / 2 for k in range(3))
            d = keys.descriptor(
                "Slot",
                {
                    "width": 2 * sa.radius,
                    "centres": centres,
                    "depth": depth_value if depth_value else 0.0,
                    "through": depth_value is None,
                },
                {
                    "axis": _axis_name(axis, frame) or "oblique",
                    "along": _axis_name(direction, frame) or "oblique",
                },
                _position(mid, axis, frame),
            )
            slots.append(
                (
                    Slot(
                        tuple(sorted(faces)),
                        d,
                        True,
                        2 * sa.radius,
                        centres,
                        (ca, cb),
                        direction,
                        depth_value,
                    ),
                    _sort_key(mid, frame),
                )
            )
            used.update((a.index, b.index))
            for k in faces:
                claimed[k] = "slot"
    slots.sort(key=lambda s: s[1])
    return [s for s, _k in slots], depths


def recognise_pockets(
    model: BrepModel, frame: Frame, claimed: dict[int, str]
) -> tuple[list[Pocket], list[Depth]]:
    by_face = edges_by_face(model)
    pockets, depths = [], []
    for f in model.faces:
        s = f.surface
        if f.index in claimed or not isinstance(s, Plane) or _axis_name(s.normal, frame) is None:
            continue
        sharp = [e for e in by_face.get(f.index, []) if _sharp(e)]
        if not sharp or any(e.kind != "concave" for e in sharp):
            continue
        walls = sorted({m for e in by_face.get(f.index, []) for m in e.faces if m not in (f.index, -1)})
        opened = _open_face(model, f, walls, by_face)
        if opened is None:
            continue
        corners = [
            model.faces[w].surface.radius
            for w in walls
            if isinstance(model.faces[w].surface, Cylinder) and model.faces[w].surface.concave
        ]
        open_sides = sum(1 for e in by_face.get(f.index, []) if e.kind == "convex")
        axis = _axis_name(s.normal, frame)
        lo = [extent(model, f, d) for d in frame.directions]
        centre = tuple((a + b) / 2 for a, b in lo)
        d = keys.descriptor(
            "Pocket",
            {"depth": opened[1], "corner": min(corners) if corners else 0.0, "walls": len(walls)},
            {"opens": ("+" if dot(s.normal, frame.directions["xyz".index(axis)]) > 0 else "-") + axis},
            _position(centre, s.normal, frame),
        )
        pockets.append(
            (
                Pocket(
                    (f.index, *walls),
                    d,
                    True,
                    f.index,
                    tuple(walls),
                    opened[1],
                    min(corners) if corners else 0.0,
                    open_sides,
                ),
                _sort_key(centre, frame),
            )
        )
        depths.append(Depth(f.index, opened[0], axis, opened[1]))
        claimed[f.index] = "pocket floor"
        for w in walls:
            if not isinstance(model.faces[w].surface, Plane):
                claimed.setdefault(w, "pocket wall")
    pockets.sort(key=lambda p: p[1])
    return [p for p, _k in pockets], depths


def recognise_steps(model: BrepModel, frame: Frame, claimed: dict[int, str]) -> list[Step]:
    by_face = edges_by_face(model)
    out = []
    for f in model.faces:
        s = f.surface
        if claimed.get(f.index) in ("hole", "groove", "slot", "pocket floor") or not isinstance(s, Plane):
            continue
        axis = _axis_name(s.normal, frame)
        if axis is None:
            continue
        kinds = {e.kind for e in by_face.get(f.index, [])}
        if "concave" in kinds and "convex" in kinds:
            k = "xyz".index(axis)
            offset = dot(s.origin, frame.directions[k])
            d = keys.descriptor(
                "Step",
                {"offset": offset - (frame.extents[k][0] if frame.extents else 0.0)},
                {"faces": ("+" if dot(s.normal, frame.directions[k]) > 0 else "-") + axis},
            )
            out.append(Step((f.index,), d, True, f.index, axis, offset))
            claimed.setdefault(f.index, "step")
    return out


def meet_line(p1: Plane, p2: Plane):
    """The line two planes meet on, (point, direction), or None when parallel."""
    direction = cross(p1.normal, p2.normal)
    n = norm(direction)
    if n < 1e-9:
        return None
    direction = tuple(c / n for c in direction)
    # the point on the line nearest the origin
    a, b = p1.normal, p2.normal
    ab = dot(a, b)
    det = 1 - ab * ab
    c1 = (p1.offset - p2.offset * ab) / det
    c2 = (p2.offset - p1.offset * ab) / det
    point = tuple(c1 * a[k] + c2 * b[k] for k in range(3))
    return point, direction


__all__ = ["meet_line", "recognise_pockets", "recognise_slots", "recognise_steps"]
