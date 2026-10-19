"""Centre marks and centre lines (``docs/DRAWINGS.md`` 8.7).

From the model's axis groups, an axis whose revolved faces cover at least 180
degrees (a hole, a boss, a full round): seen end-on it gets a centre mark of the
feature's radius, seen side-on a centre line over its faces' axial extent. A
fillet or a broad curve covers less, and its axis, which may lie far off the
part, gets neither. Layout adds the
overshoot (a setting, about 3 mm on paper), since only it knows the scale.
Circular patterns add their pitch circle as a centre-line circle, and an arc pattern
the part of it from one end hole to the other, carried a little past each. The
isometric gets none.
"""

from __future__ import annotations

import math

from ..display import Arc
from ..facegraph import BrepModel, Cone, Cylinder, Torus
from ..types import FeatureSet, Pattern
from .curves import project
from .hlr import dot

END_ON = 1e-6
MIN_COVER_DEG = 180.0


def _cover(model: BrepModel, faces, point, axis) -> float:
    x = (1.0, 0.0, 0.0) if abs(axis[0]) < 0.9 else (0.0, 1.0, 0.0)
    xa = tuple(x[k] - axis[k] * dot(x, axis) for k in range(3))
    n = math.sqrt(dot(xa, xa))
    xa = tuple(c / n for c in xa)
    ya = (
        axis[1] * xa[2] - axis[2] * xa[1],
        axis[2] * xa[0] - axis[0] * xa[2],
        axis[0] * xa[1] - axis[1] * xa[0],
    )
    angles = []
    for f in faces:
        for v in range(f.vertices[0], f.vertices[1]):
            q = tuple(model.points[v][k] - point[k] for k in range(3))
            angles.append(math.degrees(math.atan2(dot(q, ya), dot(q, xa))) % 360.0)
    if not angles:
        return 0.0
    angles.sort()
    gaps = [b - a for a, b in zip(angles, angles[1:], strict=False)] + [360.0 - angles[-1] + angles[0]]
    return 360.0 - max(gaps)


def _radius(faces) -> float:
    """A centre mark's radius: the largest bore or boss of the axis, else its cone, else
    its torus's outer radius."""
    for kind in (Cylinder, Cone):
        radii = [f.surface.radius for f in faces if isinstance(f.surface, kind)]
        if radii:
            return max(radii)
    radii = [f.surface.major + f.surface.minor for f in faces if isinstance(f.surface, Torus)]
    return max(radii, default=0.0)


def _arc_ends(c, points) -> tuple[float, float]:
    """(start, end) in degrees, counter-clockwise on the sheet, of the arc from one end
    of ``points`` (in order along the arc) to the other about ``c``. A view seen from
    behind turns the arc the other way, so the end it starts from is read off the sheet."""
    a = [math.degrees(math.atan2(p[1] - c[1], p[0] - c[0])) % 360.0 for p in points]
    if (a[1] - a[0]) % 360.0 > 180.0:
        a.reverse()
    return a[0], a[0] + (a[-1] - a[0]) % 360.0


def centres(model: BrepModel, frame, features: FeatureSet | None = None):
    """(centre marks, centre lines, pitch circles, axes end on, axes side on) for the
    view whose (right, up, d) is ``frame``."""
    right, up, d = frame
    marks, lines, circles = [], [], []
    end_on, side_on = [], []
    for k, group in enumerate(model.axis_groups):
        a = group.direction
        faces = [
            model.faces[i] for i in group.faces if isinstance(model.faces[i].surface, (Cylinder, Cone, Torus))
        ]
        if not faces:
            continue
        c = abs(dot(a, d))
        if abs(c - 1.0) <= END_ON:
            end_on.append(k)
            if _cover(model, faces, group.point, a) >= MIN_COVER_DEG:
                r = _radius(faces)
                marks.append((project(group.point, frame), r))
        elif c <= END_ON:
            side_on.append(k)
            if _cover(model, faces, group.point, a) < MIN_COVER_DEG:
                continue
            vals = [dot(model.points[v], a) for f in faces for v in range(f.vertices[0], f.vertices[1])]
            lo, hi = min(vals), max(vals)
            base = tuple(group.point[i] - a[i] * dot(group.point, a) for i in range(3))
            p0 = tuple(base[i] + a[i] * lo for i in range(3))
            p1 = tuple(base[i] + a[i] * hi for i in range(3))
            lines.append((project(p0, frame), project(p1, frame)))
    if features is not None:
        for f in features.features:
            if isinstance(f, Pattern) and f.kind in ("circular", "arc") and f.centre is not None:
                first = features.features[f.members[0]]
                axis = first.axis.direction
                if abs(abs(dot(axis, d)) - 1.0) <= END_ON:
                    c = project(f.centre, frame)
                    start, end = 0.0, 360.0
                    if f.kind == "arc":
                        start, end = _arc_ends(
                            c, [project(features.features[m].axis.point, frame) for m in f.members]
                        )
                        past = min(math.degrees(f.step) / 3, 10.0)
                        start, end = start - past, end + past
                    circles.append(Arc(c, f.pitch_diameter / 2, start, end, "centre"))
    return marks, lines, circles, end_on, side_on


__all__ = ["centres"]
