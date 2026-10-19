"""Face grooves, such as O-ring grooves (``docs/DRAWINGS.md`` 9): an annular planar
floor with a coaxial concave outer wall and convex inner wall, opening on a planar
face. A groove is never a hole or a counterbore."""

from __future__ import annotations

from .. import keys
from ..facegraph import BrepModel, Cylinder, Plane
from ..types import Axis, Frame, Groove
from ._common import add, dot, edges_by_face, extent, mul
from .holes import _axis_word, _on_axis, _position, _sort_key


def recognise_grooves(model: BrepModel, frame: Frame, claimed: dict[int, str]) -> list[Groove]:
    out = []
    by_face = edges_by_face(model)
    tol = model.tolerance * 10
    for group in model.axis_groups:
        A, P = group.direction, group.point
        walls = {i: model.faces[i] for i in group.faces if isinstance(model.faces[i].surface, Cylinder)}
        floors = set()
        for i in walls:
            for n in model.faces[i].neighbours:
                f = model.faces[n]
                if (
                    isinstance(f.surface, Plane)
                    and len(f.loops) == 2
                    and abs(abs(dot(f.surface.normal, A)) - 1) < 1e-6
                ):
                    floors.add(n)
        for n in sorted(floors):
            if n in claimed:
                continue
            floor = model.faces[n]
            edges = by_face.get(n, [])
            if not edges or not all(_on_axis(e, P, A, tol) for e in edges):
                continue
            radii = sorted({round(e.curve.radius, 12) for e in edges})
            if len(radii) != 2:
                continue
            ri, ro = radii
            outer = inner = None
            for e in edges:
                for m in e.faces:
                    w = walls.get(m)
                    if w is None:
                        continue
                    if abs(w.surface.radius - ro) <= tol and w.surface.concave:
                        outer = w
                    if abs(w.surface.radius - ri) <= tol and not w.surface.concave:
                        inner = w
            if outer is None or inner is None or outer.index in claimed or inner.index in claimed:
                continue
            fl = dot(floor.surface.origin, A)
            lo, hi = extent(model, outer, A)
            depth = hi - lo
            top = hi if abs(lo - fl) <= abs(hi - fl) else lo
            opens_on = -1
            for e in by_face.get(outer.index, []):
                if all(abs(dot(p, A) - top) <= tol * 10 for p in (e.points[0], e.points[-1])):
                    opens_on = next((m for m in e.faces if m != outer.index), -1)
            centre = add(P, mul(A, top - dot(P, A)))
            normal = floor.surface.normal
            d = keys.descriptor(
                "Groove",
                {"inner": 2 * ri, "outer": 2 * ro, "depth": depth},
                {"opens": _axis_word(normal, frame)},
                _position(centre, A, frame),
            )
            faces = tuple(sorted((n, outer.index, inner.index)))
            out.append(
                (
                    Groove(faces, d, True, Axis(centre, normal), 2 * ri, 2 * ro, ro - ri, depth, opens_on),
                    _sort_key(centre, frame),
                )
            )
            for k in faces:
                claimed[k] = "groove"
    out.sort(key=lambda g: g[1])
    return [g for g, _k in out]


__all__ = ["recognise_grooves"]
