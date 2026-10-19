"""Angled faces and features that need an auxiliary view (``docs/DRAWINGS.md`` 8.11, 9).

An angled face is a planar face square to no frame axis. It records its angle to
the nearest principal plane and the line it meets that plane on: through a sharp
edge, or, when a round or chamfer lies between them, a virtual sharp (the
intersection of the two planes, drawn as construction lines). Holes, slots and
pockets on an angled face, and holes whose axis is no frame axis, need an
auxiliary view; stage 1 lists them and their faces count as unclaimed with that
reason.
"""

from __future__ import annotations

import math

from .. import keys
from ..facegraph import BrepModel, Plane
from ..numbers import plain_sum
from ..types import AngledFace, Axis, Frame
from ._common import along, dot, edges_by_face
from .holes import _sort_key
from .pockets import meet_line


def recognise_angled(model: BrepModel, frame: Frame, claimed: dict[int, str]) -> list[AngledFace]:
    by_face = edges_by_face(model)
    out = []
    for f in model.faces:
        s = f.surface
        if not isinstance(s, Plane) or along(s.normal, frame.directions) is not None:
            continue
        if claimed.get(f.index) in ("hole", "slot", "groove", "chamfer"):
            continue
        cosines = [abs(dot(s.normal, d)) for d in frame.directions]
        angle = math.acos(min(1.0, max(cosines)))
        meet, virtual = _meet(model, f.index, s, frame, by_face, claimed)
        pts = model.points[f.vertices[0] : f.vertices[1]]
        centre = tuple(plain_sum(p[k] for p in pts) / max(len(pts), 1) for k in range(3))
        d = keys.descriptor(
            "AngledFace",
            {"angle": angle, "virtual_sharp": virtual},
            {"normal": tuple(round(c, 6) for c in s.normal)},
            tuple(dot(centre, dd) for dd in frame.directions),
        )
        out.append(
            (
                AngledFace((f.index,), d, True, f.index, angle, Axis(*meet) if meet else None, virtual),
                _sort_key(centre, frame),
            )
        )
        claimed.setdefault(f.index, "angled face")
    out.sort(key=lambda a: a[1])
    return [a for a, _k in out]


def _principal(model: BrepModel, index: int, frame: Frame) -> Plane | None:
    s = model.faces[index].surface
    return s if isinstance(s, Plane) and along(s.normal, frame.directions) is not None else None


def _meet(model: BrepModel, index: int, s: Plane, frame: Frame, by_face, claimed):
    """The line the angled face ``index`` meets a principal plane on, and whether it is
    a virtual sharp: the plane it is angled from, the neighbour (through a sharp edge,
    or through a round or chamfer) whose normal is nearest its own. A neighbour square
    to it, such as an end face, meets it at 90 degrees and says nothing of its angle.
    Between two equally near, as at a 45 degree corner, the larger face: the face the
    angled one is cut from, which the drawing locates it along."""
    best: tuple[float, float, bool, Plane] | None = None
    for e in by_face.get(index, []):
        other = next((m for m in e.faces if m not in (index, -1)), None)
        if other is None:
            continue
        found: list[tuple[Plane, bool, float]] = []
        g = _principal(model, other, frame)
        if g is not None and e.kind != "tangent":
            found.append((g, False, model.faces[other].area))
        elif e.kind == "tangent" and claimed.get(other) in ("blend", "chamfer", None):
            for e2 in by_face.get(other, []):
                far = next((m for m in e2.faces if m not in (other, index, -1)), None)
                h = _principal(model, far, frame) if far is not None else None
                if h is not None:
                    found.append((h, True, model.faces[far].area))
        for plane, virtual, area in found:
            score = round(abs(dot(s.normal, plane.normal)), 6)
            if score > 1e-6 and (best is None or (score, area) > best[:2]):
                best = (score, area, virtual, plane)
    if best is None:
        return None, False
    return meet_line(s, best[3]), best[2]


__all__ = ["recognise_angled"]
