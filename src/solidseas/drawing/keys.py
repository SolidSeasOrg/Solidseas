"""Geometric signatures of single B-rep entities and the descriptors matching compares
(``docs/DRAWINGS.md`` 6.4.1, 13.4).

A signature says what an entity is and where, in a form that survives a save
that changed no geometry: never a Parasolid node id (they change on every save,
and STEP and ACIS have none). Every value is rounded to a whole number of the
tolerance it is given, written as an integer, so two equal models give equal
text on any machine. ``source.geometry_digest`` hashes the signatures of every
face at 1e-7 m.

| Entity | Signature |
|---|---|
| Plane face | unit normal (canonical sign) and offset along it |
| Cylinder or cone face | axis line (canonical point and direction), radius or half angle |
| Sphere, torus | centre, axis, radii |
| Straight edge | the two end points, unordered |
| Circular edge | centre, normal, radius |
| Vertex | its point |
| Other edges and faces | type, bounding box, length or area |
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from ..errors import InvalidArgumentError
from .numbers import plain_sum
from .types import Descriptor

Vec3 = tuple[float, float, float]

DIGEST_TOLERANCE = 1e-7  # metres: what the geometry digest rounds to
ANGLE_TOLERANCE = 1e-7  # radians, and unit-vector components


def q(x: float, tol: float) -> int:
    """``x`` as a whole number of ``tol``, rounded half away from zero; -0 is 0."""
    if not math.isfinite(x):
        raise InvalidArgumentError("a signature value must be finite", detail={"parameter": "value"})
    n = math.floor(abs(x) / tol + 0.5)
    return int(n if x >= 0 else -n)


def _qv(v: Sequence[float], tol: float) -> str:
    return ",".join(str(q(c, tol)) for c in v)


def _unit(v: Sequence[float]) -> Vec3:
    n = math.sqrt(plain_sum(c * c for c in v))
    if n == 0.0:
        raise InvalidArgumentError("a direction must not be zero", detail={"parameter": "direction"})
    return (v[0] / n, v[1] / n, v[2] / n)


def canonical_direction(v: Sequence[float], tol: float = ANGLE_TOLERANCE) -> Vec3:
    """``v`` as a unit vector whose first component beyond ``tol`` is positive, so a
    line or a plane's normal has one form whichever way it was stored."""
    u = _unit(v)
    for c in u:
        if abs(c) > tol:
            return u if c > 0 else (-u[0], -u[1], -u[2])
    return u


def canonical_axis(point: Sequence[float], direction: Sequence[float]) -> tuple[Vec3, Vec3]:
    """A line as (its point nearest the origin, its canonical direction)."""
    d = canonical_direction(direction)
    t = plain_sum(p * c for p, c in zip(point, d, strict=True))
    return (point[0] - t * d[0], point[1] - t * d[1], point[2] - t * d[2]), d


def plane(normal: Sequence[float], point: Sequence[float], tol: float) -> str:
    """A plane face's signature: canonical unit normal and the offset along it."""
    n = canonical_direction(normal)
    offset = plain_sum(p * c for p, c in zip(point, n, strict=True))
    return f"plane:{_qv(n, ANGLE_TOLERANCE)}:{q(offset, tol)}"


def cylinder(point: Sequence[float], axis: Sequence[float], radius: float, tol: float) -> str:
    p, d = canonical_axis(point, axis)
    return f"cylinder:{_qv(p, tol)}:{_qv(d, ANGLE_TOLERANCE)}:{q(radius, tol)}"


def cone(point: Sequence[float], axis: Sequence[float], half_angle: float, tol: float, apex=None) -> str:
    """A cone by its axis line, half angle and, when it has one, its apex."""
    p, d = canonical_axis(point, axis)
    where = _qv(apex, tol) if apex is not None else _qv(p, tol)
    return f"cone:{where}:{_qv(d, ANGLE_TOLERANCE)}:{q(abs(half_angle), ANGLE_TOLERANCE)}"


def sphere(centre: Sequence[float], radius: float, tol: float) -> str:
    return f"sphere:{_qv(centre, tol)}:{q(radius, tol)}"


def torus(centre: Sequence[float], axis: Sequence[float], major: float, minor: float, tol: float) -> str:
    d = canonical_direction(axis)
    return f"torus:{_qv(centre, tol)}:{_qv(d, ANGLE_TOLERANCE)}:{q(major, tol)}:{q(minor, tol)}"


def other_face(kind: str, box: tuple[Sequence[float], Sequence[float]], area: float, tol: float) -> str:
    return f"{kind}:{_qv(box[0], tol)}:{_qv(box[1], tol)}:{q(area, tol * tol)}"


def line_edge(a: Sequence[float], b: Sequence[float], tol: float) -> str:
    """A straight edge: its two end points, unordered."""
    ends = sorted((_qv(a, tol), _qv(b, tol)))
    return f"line:{ends[0]}:{ends[1]}"


def circle_edge(centre: Sequence[float], normal: Sequence[float], radius: float, tol: float) -> str:
    return f"circle:{_qv(centre, tol)}:{_qv(canonical_direction(normal), ANGLE_TOLERANCE)}:{q(radius, tol)}"


def other_edge(kind: str, box: tuple[Sequence[float], Sequence[float]], length: float, tol: float) -> str:
    return f"{kind}:{_qv(box[0], tol)}:{_qv(box[1], tol)}:{q(length, tol)}"


def vertex(p: Sequence[float], tol: float) -> str:
    return f"vertex:{_qv(p, tol)}"


def digest(signatures: Iterable[str]) -> str:
    """The SHA-256 of the sorted signatures, one a line: equal for two models whose
    entities are equal, whatever order they were stored in."""
    h = hashlib.sha256()
    for s in sorted(signatures):
        h.update(s.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def properties_digest(values: Mapping[str, Any], names: Iterable[str]) -> str:
    """The SHA-256 of the properties the title block reads (``names``, compared without
    case), so a drawing can tell when a title block refresh is due."""
    folded = {k.casefold(): v for k, v in values.items()}
    h = hashlib.sha256()
    for name in sorted({n.casefold() for n in names}):
        value = folded.get(name)
        h.update(f"{name}={'' if value is None else value}\n".encode())
    return h.hexdigest()


def _rounded(value: Any, tol: float) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        return round(q(value, tol) * tol, 12)
    if isinstance(value, (tuple, list)):
        return tuple(_rounded(v, tol) for v in value)
    raise InvalidArgumentError(
        f"a descriptor cannot hold a {type(value).__name__}", detail={"parameter": "size"}
    )


def descriptor(
    kind: str,
    size: Mapping[str, Any],
    adjacency: Mapping[str, Any] | None = None,
    position: Sequence[float] = (),
    *,
    tol: float = 1e-6,
) -> Descriptor:
    """A feature's descriptor (6.4.1), its values rounded to ``tol`` and its keys sorted,
    so the same feature gives the same descriptor."""
    return Descriptor(
        kind,
        tuple(sorted((k, _rounded(v, tol)) for k, v in size.items())),
        tuple(sorted((k, _rounded(v, tol)) for k, v in (adjacency or {}).items())),
        tuple(_rounded(float(p), tol) for p in position),
    )


def same_size(a: Descriptor, b: Descriptor, tol: float) -> bool:
    """Whether two descriptors have the same type and size signature within ``tol``
    (13.4's first matching pass)."""
    if a.type != b.type or [k for k, _ in a.size] != [k for k, _ in b.size]:
        return False
    for (_k, x), (_k2, y) in zip(a.size, b.size, strict=True):
        if not _close(x, y, tol):
            return False
    return True


def _close(x: Any, y: Any, tol: float) -> bool:
    if isinstance(x, (int, float)) and isinstance(y, (int, float)) and not isinstance(x, bool):
        return abs(x - y) <= tol
    if isinstance(x, tuple) and isinstance(y, tuple):
        return len(x) == len(y) and all(_close(a, b, tol) for a, b in zip(x, y, strict=True))
    return x == y


__all__ = [
    "DIGEST_TOLERANCE",
    "canonical_axis",
    "canonical_direction",
    "circle_edge",
    "cone",
    "cylinder",
    "descriptor",
    "digest",
    "line_edge",
    "other_edge",
    "other_face",
    "plane",
    "properties_digest",
    "q",
    "same_size",
    "sphere",
    "torus",
    "vertex",
]
