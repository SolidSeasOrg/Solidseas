"""Silhouettes of curved faces (``docs/DRAWINGS.md`` 8.5).

- **Cylinders and cones, in closed form:** the generator angles where the normal is
  square to the view, ``n(u) . d = 0``, then each generator clipped to the face
  through its own triangles in (u, v), tried at u and u plus or minus a period
  (C3). Crossings are counted half-open, so a boundary sample lying on the
  generator is not counted twice. A cylinder seen along its axis has no
  silhouette: its circles are its outline.
- **Everything else, from the mesh:** on each triangle, where ``g = n . d``
  changes sign along its edges using the exact corner normals, interpolated, and
  chained by mesh edge.

Refinement on the exact surface (8.5's Newton steps from the stored (u, v)) is
for output only and is not done yet: mesh silhouettes are within the chord.
"""

from __future__ import annotations

import math

from ..facegraph import BrepModel, Cone, Cylinder, Face
from .hlr import dot

Vec3 = tuple[float, float, float]
TWO_PI = 2.0 * math.pi
NUDGE = 1e-9  # radians


def _uv_triangles(model: BrepModel, face: Face):
    uv = model.face_uv[face.index]
    v0 = face.vertices[0]
    out = []
    for ti in range(face.triangles[0], face.triangles[1]):
        tri = model.triangles[ti]
        out.append([(uv[2 * (v - v0)], uv[2 * (v - v0) + 1]) for v in tri])
    return out


def _clip(tri_uv, u_line: float) -> list[tuple[float, float]]:
    """The v intervals where the line u = ``u_line`` crosses the face's triangles,
    tried a period either side and a hair either side of the line itself, so a
    generator on the seam or through a boundary sample is found once and never
    counted twice (the bug the prototype hit on o11), merged."""
    intervals = []
    for shift in (-TWO_PI, 0.0, TWO_PI):
        for nudge in (-NUDGE, NUDGE):
            uu = u_line + shift + nudge
            for tri in tri_uv:
                hits = []
                for (u0, v0), (u1, v1) in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
                    if u0 != u1 and min(u0, u1) <= uu <= max(u0, u1):
                        hits.append(v0 + (v1 - v0) * (uu - u0) / (u1 - u0))
                if len(hits) >= 2:
                    intervals.append((min(hits), max(hits)))
    if not intervals:
        return []
    intervals.sort()
    merged = [list(intervals[0])]
    for lo, hi in intervals[1:]:
        if lo <= merged[-1][1] + 1e-12:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return [(lo, hi) for lo, hi in merged if hi - lo > 1e-12]


def _point(s, u: float, v: float) -> Vec3:
    c, sn = math.cos(u), math.sin(u)
    if isinstance(s, Cone):
        rho = s.radius + v * math.tan(s.half_angle)
    else:
        rho = s.radius
    return tuple(s.point[k] + s.axis[k] * v + rho * (c * s.x[k] + sn * s.y[k]) for k in range(3))


def generator_angles(s, d: Vec3) -> list[float]:
    """The angles u where a cylinder's or cone's normal is square to ``d``."""
    a, b = dot(s.x, d), dot(s.y, d)
    radial = math.hypot(a, b)
    if isinstance(s, Cone):
        c = math.tan(s.half_angle) * dot(s.axis, d)
        if radial < 1e-12 or abs(c) > radial:
            return []
        base = math.atan2(b, a)
        off = math.acos(max(-1.0, min(1.0, c / radial)))
        return [base + off, base - off] if off > 1e-12 else [base]
    if radial < 1e-9:
        return []  # seen along its axis
    base = math.atan2(-a, b)
    return [base, base + math.pi]


def analytic(model: BrepModel, face: Face, d: Vec3) -> list[list[Vec3]]:
    """The visible-or-not silhouette lines of a cylinder or cone face, as 3D segments."""
    s = face.surface
    if not isinstance(s, (Cylinder, Cone)):
        return []
    tri_uv = _uv_triangles(model, face)
    out = []
    for u in generator_angles(s, d):
        for lo, hi in _clip(tri_uv, u):
            out.append([_point(s, u, lo), _point(s, u, hi)])
    return out


def from_mesh(model: BrepModel, face: Face, d: Vec3) -> list[list[Vec3]]:
    """Where ``n . d`` changes sign across the face's triangles, chained into
    polylines by mesh edge."""
    v0, v1 = face.vertices
    g = {v: dot(model.normals[v], d) for v in range(v0, v1)}
    pieces: dict[frozenset, list] = {}
    order = []
    for ti in range(face.triangles[0], face.triangles[1]):
        tri = model.triangles[ti]
        cuts = []
        for i, j in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            gi, gj = g[i], g[j]
            if (gi < 0) != (gj < 0) and gi != gj:
                f = gi / (gi - gj)
                pi, pj = model.points[i], model.points[j]
                cuts.append((frozenset((i, j)), tuple(pi[k] + (pj[k] - pi[k]) * f for k in range(3))))
        if len(cuts) == 2:
            order.append(cuts)
            for key, _p in cuts:
                pieces.setdefault(key, []).append(len(order) - 1)
    # chain segments sharing a mesh edge
    used = [False] * len(order)
    chains = []
    for start in range(len(order)):
        if used[start]:
            continue
        used[start] = True
        (ka, pa), (kb, pb) = order[start]
        chain = [pa, pb]
        for end_key, forward in ((kb, True), (ka, False)):
            key = end_key
            while True:
                nxt = next((k for k in pieces.get(key, ()) if not used[k]), None)
                if nxt is None:
                    break
                used[nxt] = True
                (k1, p1), (k2, p2) = order[nxt]
                if k1 == key:
                    key, p = k2, p2
                else:
                    key, p = k1, p1
                if forward:
                    chain.append(p)
                else:
                    chain.insert(0, p)
        chains.append(chain)
    return chains


__all__ = ["analytic", "from_mesh", "generator_angles"]
