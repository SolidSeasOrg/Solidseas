"""Chamfers (``docs/DRAWINGS.md`` 9).

Planar: a narrow planar face (under 10 % of the part's size across) between two
planar faces, with both long edges sharp and convex and its angles to those two
summing to 90 degrees within 1. Conical: a complete convex cone of 20 to 70
degrees half angle between convex edges (a hole's entry chamfer belongs to the
hole and never reaches here). Legs are measured from each long edge to the other
face's plane: the lengths the chamfer took off each face.
"""

from __future__ import annotations

import math

from .. import keys
from ..facegraph import BrepModel, Cone, Plane
from ..types import Chamfer, Frame
from ._common import COVER_GAP_DEG, angular_cover, dot, edges_by_face
from .holes import _sort_key

NARROW = 0.10
ANGLE_TOL = 1.0


def recognise_chamfers(model: BrepModel, frame: Frame, claimed: dict[int, str]) -> list[Chamfer]:
    by_face = edges_by_face(model)
    out = []
    for f in model.faces:
        if f.index in claimed:
            continue
        s = f.surface
        edges = by_face.get(f.index, [])
        if isinstance(s, Plane):
            long = sorted(edges, key=lambda e: -e.length)[:2]
            if len(long) < 2 or any(e.kind != "convex" for e in long):
                continue
            width = f.area / max(long[0].length, 1e-12)
            if width >= NARROW * model.diagonal:
                continue
            sides = []
            for e in long:
                other = next((m for m in e.faces if m not in (f.index, -1)), None)
                if other is None or not isinstance(model.faces[other].surface, Plane):
                    break
                sides.append((e, model.faces[other]))
            if len(sides) != 2:
                continue
            (e1, p1), (e2, p2) = sides
            a1 = math.degrees(math.acos(max(-1.0, min(1.0, dot(s.normal, p1.surface.normal)))))
            a2 = math.degrees(math.acos(max(-1.0, min(1.0, dot(s.normal, p2.surface.normal)))))
            if abs(a1 + a2 - 90.0) > ANGLE_TOL:
                continue
            # the leg on face 1 runs from the edge on it to face 2's plane, and back
            leg1 = abs(dot(e1.points[0], p2.surface.normal) - p2.surface.offset)
            leg2 = abs(dot(e2.points[0], p1.surface.normal) - p1.surface.offset)
            mid = e1.points[len(e1.points) // 2]
            d = keys.descriptor(
                "Chamfer",
                {"legs": tuple(sorted((leg1, leg2))), "angle": round(a1, 6), "shape": "planar"},
                {"between": 2},
                tuple(dot(mid, dd) for dd in frame.directions),
            )
            out.append(
                (
                    Chamfer((f.index,), d, True, (leg1, leg2), math.radians(a1), "planar"),
                    _sort_key(mid, frame),
                )
            )
            claimed[f.index] = "chamfer"
        elif isinstance(s, Cone) and not s.concave:
            half = math.degrees(abs(s.half_angle))
            if not 20.0 <= half <= 70.0 or angular_cover(model, [f], s.point, s.axis) > COVER_GAP_DEG:
                continue
            if not edges or any(e.kind != "convex" for e in edges):
                continue
            radii = sorted(e.curve.radius for e in edges if e.curve.kind == "circle")
            if len(radii) < 2:
                continue
            radial = radii[-1] - radii[0]
            axial = radial / math.tan(math.radians(half))
            mid = edges[0].points[0]
            d = keys.descriptor(
                "Chamfer",
                {"legs": tuple(sorted((radial, axial))), "angle": round(half, 6), "shape": "conical"},
                {"between": 2},
                tuple(dot(mid, dd) for dd in frame.directions),
            )
            out.append(
                (
                    Chamfer((f.index,), d, True, (radial, axial), math.radians(half), "conical"),
                    _sort_key(mid, frame),
                )
            )
            claimed[f.index] = "chamfer"
    out.sort(key=lambda c: c[1])
    return [c for c, _k in out]


__all__ = ["recognise_chamfers"]
