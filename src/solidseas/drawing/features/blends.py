"""Fillets and rounds (``docs/DRAWINGS.md`` 9).

A blend is a curved face (cylinder, torus, sphere, cone, B-spline or rolling
blend) with at least two tangent edges to different faces that is not a complete
cylinder and not already part of a hole, slot or groove. Its radius is exact for
cylinders, tori and spheres; otherwise it comes from the chord between its two
tangent edges and the turn of the normal across it, and the blend is marked not
exact. A concave blend is a fillet, a convex one a round. A blend whose radius
is half the width between its two tangent faces, when those are parallel and face
apart, is a full-round end: ``derived``, drawn as "R" without a value.
"""

from __future__ import annotations

import math

from .. import keys
from ..facegraph import BrepModel, Cylinder, Plane, Sphere, Torus
from ..numbers import plain_sum
from ..types import Blend, Frame
from ._common import dot, edges_by_face, norm, sub
from .holes import _sort_key

CURVED = ("cylinder", "torus", "sphere", "cone", "bspline", "blend", "swept", "spun", "offset")


def _estimate(model: BrepModel, edges) -> float | None:
    """A radius from two tangent edges: the chord between them over twice the sine of
    half the turn of the face's normal across it."""
    (a, na), (b, nb) = edges
    pa = a.points[len(a.points) // 2]
    best = min(b.points, key=lambda q: norm(sub(q, pa)))
    chord = norm(sub(best, pa))
    turn = math.acos(max(-1.0, min(1.0, dot(na, nb))))
    if turn < 1e-6:
        return None
    return chord / (2 * math.sin(turn / 2))


def recognise_blends(model: BrepModel, frame: Frame, claimed: dict[int, str]) -> list[Blend]:
    by_face = edges_by_face(model)
    out = []
    for f in model.faces:
        if f.index in claimed or f.kind not in CURVED:
            continue
        tangent = [e for e in by_face.get(f.index, []) if e.kind == "tangent"]
        others = {m for e in tangent for m in e.faces if m not in (f.index, -1)}
        if len(others) < 2:
            continue
        s = f.surface
        exact = True
        if isinstance(s, Cylinder):
            radius, concave = s.radius, s.concave
        elif isinstance(s, Torus):
            radius, concave = s.minor, s.concave
        elif isinstance(s, Sphere):
            radius, concave = s.radius, s.concave
        else:
            exact = False
            pairs = []
            for e in tangent[:2]:
                side = e.faces.index(f.index)
                pairs.append((e, e.normals[side][len(e.points) // 2]))
            radius = _estimate(model, pairs) if len(pairs) == 2 else None
            if radius is None:
                continue
            e, n = pairs[0]
            v0 = f.vertices[0]
            concave = dot(sub(model.points[v0], e.points[len(e.points) // 2]), n) > 0
        derived = False
        planes = [model.faces[m] for m in others if isinstance(model.faces[m].surface, Plane)]
        for i, p in enumerate(planes):
            for q in planes[i + 1 :]:
                if dot(p.surface.normal, q.surface.normal) < -1 + 1e-6:
                    width = abs(p.surface.offset + q.surface.offset)
                    if abs(width / 2 - radius) <= model.tolerance * 10:
                        derived = True
        pts = model.points[f.vertices[0] : f.vertices[1]]
        centre = tuple(plain_sum(p[k] for p in pts) / max(len(pts), 1) for k in range(3))
        d = keys.descriptor(
            "Blend",
            {"radius": radius, "kind": "fillet" if concave else "round", "derived": derived},
            {"faces": len(others)},
            tuple(dot(centre, dd) for dd in frame.directions),
        )
        out.append(
            (
                Blend((f.index,), d, exact, radius, "fillet" if concave else "round", derived, False),
                _sort_key(centre, frame),
            )
        )
        claimed[f.index] = "blend"
    out.sort(key=lambda b: b[1])
    return [b for b, _k in out]


__all__ = ["recognise_blends"]
