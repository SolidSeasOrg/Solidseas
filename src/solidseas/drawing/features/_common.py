"""Helpers shared by the recognisers: vectors, frame axes, angular cover and a ray
index over the model's triangles (the point-in-solid index C9 asked for)."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

from ..facegraph import BrepModel, Face

Vec3 = tuple[float, float, float]
AXIS_NAMES = ("x", "y", "z")
COVER_GAP_DEG = 31.0  # a hole is complete when its walls leave no gap wider than this (9)
SQUARE_TOL = 1e-6  # |cos| within this of 1 counts as along an axis


def sub(a, b) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a, b) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def mul(a, k) -> Vec3:
    return (a[0] * k, a[1] * k, a[2] * k)


def dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a) -> float:
    return math.sqrt(dot(a, a))


def unit(a) -> Vec3:
    n = norm(a)
    return (a[0] / n, a[1] / n, a[2] / n) if n else (0.0, 0.0, 0.0)


def along(direction: Sequence[float], frame: Sequence[Vec3]) -> tuple[str, int] | None:
    """Which frame axis ``direction`` runs along, and its sign, or None."""
    for name, d in zip(AXIS_NAMES, frame, strict=True):
        c = dot(direction, d)
        if abs(abs(c) - 1.0) <= SQUARE_TOL:
            return name, 1 if c > 0 else -1
    return None


def coord(p: Sequence[float], frame: Sequence[Vec3], axis: str) -> float:
    return dot(p, frame[AXIS_NAMES.index(axis)])


def face_points(model: BrepModel, face: Face) -> list[Vec3]:
    v0, v1 = face.vertices
    return list(model.points[v0:v1])


def edges_by_face(model: BrepModel) -> dict[int, list]:
    """Each face's edges, once."""
    out: dict[int, list] = {}
    for e in model.edges.values():
        for f in set(e.faces):
            if f >= 0:
                out.setdefault(f, []).append(e)
    return out


def extent(model: BrepModel, face: Face, direction: Vec3) -> tuple[float, float]:
    vals = [dot(p, direction) for p in face_points(model, face)]
    return (min(vals), max(vals)) if vals else (0.0, 0.0)


def angular_cover(model: BrepModel, faces: Iterable[Face], point: Vec3, axis: Vec3) -> float:
    """The widest gap, in degrees, the faces' vertices leave round ``axis`` (0 for a
    complete ring, 360 for nothing)."""
    x = unit(cross(axis, (0.0, 0.0, 1.0) if abs(axis[2]) < 0.9 else (1.0, 0.0, 0.0)))
    y = cross(axis, x)
    angles = []
    for f in faces:
        for p in face_points(model, f):
            q = sub(p, point)
            angles.append(math.degrees(math.atan2(dot(q, y), dot(q, x))) % 360.0)
    if not angles:
        return 360.0
    angles.sort()
    gaps = [b - a for a, b in zip(angles, angles[1:], strict=False)]
    gaps.append(360.0 - angles[-1] + angles[0])
    return max(gaps)


def cover_degrees(gap: float) -> float:
    """The angle a set of faces covers, given the widest gap it leaves."""
    return 360.0 - gap


class RayIndex:
    """Triangles binned on the plane square to one direction, so a ray along that
    direction meets only the triangles of its cell: point-in-solid by parity and the
    first face a ray reaches, in time proportional to the cell's triangles."""

    def __init__(self, model: BrepModel, direction: Vec3, cells: int | None = None) -> None:
        self.model = model
        self.d = unit(direction)
        self.u = unit(cross(self.d, (0.0, 0.0, 1.0) if abs(self.d[2]) < 0.9 else (1.0, 0.0, 0.0)))
        self.v = cross(self.d, self.u)
        P = model.points
        uv = [(dot(p, self.u), dot(p, self.v)) for p in P]
        self.uv = uv
        n = len(model.triangles)
        side = cells or max(1, int(math.sqrt(max(n, 1) / 3.0)))
        us = [q[0] for q in uv] or [0.0]
        vs = [q[1] for q in uv] or [0.0]
        self.lo = (min(us), min(vs))
        span = max(max(us) - self.lo[0], max(vs) - self.lo[1], 1e-12)
        self.size = span / side
        self.side = side
        self.grid: dict[tuple[int, int], list[int]] = {}
        for t, (a, b, c) in enumerate(model.triangles):
            ua, ub, uc = uv[a], uv[b], uv[c]
            i0, j0 = self._cell(min(ua[0], ub[0], uc[0]), min(ua[1], ub[1], uc[1]))
            i1, j1 = self._cell(max(ua[0], ub[0], uc[0]), max(ua[1], ub[1], uc[1]))
            for i in range(i0, i1 + 1):
                for j in range(j0, j1 + 1):
                    self.grid.setdefault((i, j), []).append(t)

    def _cell(self, u: float, v: float) -> tuple[int, int]:
        i = int((u - self.lo[0]) / self.size)
        j = int((v - self.lo[1]) / self.size)
        return min(max(i, 0), self.side), min(max(j, 0), self.side)

    def hits(self, origin: Vec3) -> list[tuple[float, int]]:
        """Every (distance along the direction, face) where the ray from ``origin``
        crosses a triangle, nearest first, distances possibly negative (behind)."""
        P = self.model.points
        ou, ov = dot(origin, self.u), dot(origin, self.v)
        od = dot(origin, self.d)
        out = []
        for t in self.grid.get(self._cell(ou, ov), ()):
            a, b, c = self.model.triangles[t]
            pa, pb, pc = self.uv[a], self.uv[b], self.uv[c]
            w = _barycentric((ou, ov), pa, pb, pc)
            if w is None:
                continue
            depth = w[0] * dot(P[a], self.d) + w[1] * dot(P[b], self.d) + w[2] * dot(P[c], self.d)
            out.append((depth - od, self.model.tri_face[t]))
        out.sort()
        return out

    def inside(self, p: Vec3) -> bool:
        """Whether ``p`` lies inside the solid: crossings ahead of it, counted once per
        distinct distance (a ray through a shared edge meets two triangles there)."""
        ahead = sorted({round(d, 12) for d, _f in self.hits(p) if d > 1e-12})
        return len(ahead) % 2 == 1

    def first(
        self, origin: Vec3, skip: frozenset[int] = frozenset(), after: float = 1e-12
    ) -> tuple[float, int] | None:
        for dist, f in self.hits(origin):
            if dist > after and f not in skip:
                return dist, f
        return None


def _barycentric(p, a, b, c):
    """(wa, wb, wc) of ``p`` in triangle abc in 2D, or None outside (edges half-open so a
    point on a shared edge counts once)."""
    det = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
    if abs(det) < 1e-30:
        return None
    wa = ((b[1] - c[1]) * (p[0] - c[0]) + (c[0] - b[0]) * (p[1] - c[1])) / det
    wb = ((c[1] - a[1]) * (p[0] - c[0]) + (a[0] - c[0]) * (p[1] - c[1])) / det
    wc = 1.0 - wa - wb
    eps = -1e-12
    if wa < eps or wb < eps or wc < eps:
        return None
    return wa, wb, wc


class Rays:
    """One :class:`RayIndex` per direction, made when first asked for."""

    def __init__(self, model: BrepModel) -> None:
        self.model = model
        self._by: dict[tuple[float, float, float], RayIndex] = {}

    def along(self, direction: Vec3) -> RayIndex:
        key = tuple(round(c, 9) for c in unit(direction))
        idx = self._by.get(key)
        if idx is None:
            idx = self._by[key] = RayIndex(self.model, key)
        return idx

    def inside(self, p: Vec3, direction: Vec3 = (0.0, 0.0, 1.0)) -> bool:
        return self.along(direction).inside(p)
