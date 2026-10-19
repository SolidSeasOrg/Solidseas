"""The hidden-line engine (``docs/DRAWINGS.md`` 8.4).

For a view direction ``d`` (from the part toward the viewer):

1. every triangle is projected onto the view plane and binned in a uniform grid
   of about three triangles a cell, edge-on triangles dropped: the occluder;
2. points along each curve every 1/400 of the diagonal are tested: a point is
   hidden when a triangle covers it in front by more than a tolerance, and each
   change of visibility is bisected 12 times;
3. the own-face test: a curve carries the faces whose tessellation passes
   through it (an edge's two faces and every face at its end vertices; a
   silhouette's face and its neighbours). Hits on those count only when the point
   lies more than 3 chords behind the triangle, measured square to it, and hits on
   any other face from 1e-7 of the diagonal. A curved own face hiding a hole's far
   rim is still found, and a steep triangle beside an edge cannot hide the points
   its chord passes behind (a sphere's rim seen along its axis).

Coordinates out of here are the view plane's (right, up), in metres, before the
sheet's scale and placement.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from ..facegraph import BrepModel

Vec3 = tuple[float, float, float]

STEP_FRACTION = 1 / 400  # of the diagonal, between visibility samples
BISECT = 12
OWN_CHORDS = 3.0
OTHER_FRACTION = 1e-7


def dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


class Occluder:
    """The triangles projected onto the view plane, binned in a uniform grid.
    ``keep`` limits the triangles (a section keeps those behind its plane)."""

    def __init__(
        self, model: BrepModel, frame: tuple[Vec3, Vec3, Vec3], keep=None, budget: int | None = None
    ):
        right, up, d = frame
        self.right, self.up, self.d = right, up, d
        P = model.points
        self.p2 = [(dot(p, right), dot(p, up), dot(p, d)) for p in P]
        self.tris = []
        for ti, (a, b, c) in enumerate(model.triangles):
            if keep is not None and not keep(ti):
                continue
            pa, pb, pc = self.p2[a], self.p2[b], self.p2[c]
            area2 = (pb[0] - pa[0]) * (pc[1] - pa[1]) - (pb[1] - pa[1]) * (pc[0] - pa[0])
            if abs(area2) < 1e-20:
                continue  # edge-on
            # how squarely the triangle faces the view: its own faces' depth margin is
            # measured square to the triangle, so a steep one near an edge cannot hide
            # the points its chord passes behind
            A, B, C = P[a], P[b], P[c]
            u = (B[0] - A[0], B[1] - A[1], B[2] - A[2])
            v = (C[0] - A[0], C[1] - A[1], C[2] - A[2])
            n2 = (
                (u[1] * v[2] - u[2] * v[1]) ** 2
                + (u[2] * v[0] - u[0] * v[2]) ** 2
                + (u[0] * v[1] - u[1] * v[0]) ** 2
            )
            facing = abs(area2) / math.sqrt(n2) if n2 > 0 else 1.0
            self.tris.append((ti, pa, pb, pc, area2, facing))
        xs = [p[0] for p in self.p2] or [0.0]
        ys = [p[1] for p in self.p2] or [0.0]
        self.x0, self.y0 = min(xs), min(ys)
        w, h = (max(xs) - self.x0) or 1e-9, (max(ys) - self.y0) or 1e-9
        n = max(1, int(math.sqrt(max(1, len(self.tris)) / 3.0)))
        self.n = n
        self.cw, self.ch = w / n * (1 + 1e-9), h / n * (1 + 1e-9)
        self.grid: dict[tuple[int, int], list[int]] = {}
        for k, (_ti, pa, pb, pc, _a2, _f) in enumerate(self.tris):
            i0, i1 = self._cell(min(pa[0], pb[0], pc[0]), 0), self._cell(max(pa[0], pb[0], pc[0]), 0)
            j0, j1 = self._cell(min(pa[1], pb[1], pc[1]), 1), self._cell(max(pa[1], pb[1], pc[1]), 1)
            for i in range(i0, i1 + 1):
                for j in range(j0, j1 + 1):
                    self.grid.setdefault((i, j), []).append(k)
        self.tri_face = model.tri_face
        self.own_tol = OWN_CHORDS * model.chord
        self.other_tol = OTHER_FRACTION * model.diagonal
        self.queries = 0
        self.budget = budget

    def _cell(self, v: float, axis: int) -> int:
        if axis == 0:
            return min(self.n - 1, max(0, int((v - self.x0) / self.cw)))
        return min(self.n - 1, max(0, int((v - self.y0) / self.ch)))

    def hidden(self, x: float, y: float, depth: float, own: frozenset[int]) -> bool:
        self.queries += 1
        if self.budget is not None and self.queries > self.budget:
            raise OverflowError("visibility queries")
        for k in self.grid.get((self._cell(x, 0), self._cell(y, 1)), ()):
            ti, pa, pb, pc, a2, facing = self.tris[k]
            w0 = ((pb[0] - x) * (pc[1] - y) - (pb[1] - y) * (pc[0] - x)) / a2
            w1 = ((pc[0] - x) * (pa[1] - y) - (pc[1] - y) * (pa[0] - x)) / a2
            w2 = 1.0 - w0 - w1
            if w0 < -1e-12 or w1 < -1e-12 or w2 < -1e-12:
                continue
            ahead = w0 * pa[2] + w1 * pb[2] + w2 * pc[2] - depth
            if self.tri_face[ti] in own:
                if ahead * facing > self.own_tol:
                    return True
            elif ahead > self.other_tol:
                return True
        return False

    def visible_at(self, p: Vec3, own: frozenset[int]) -> bool:
        return not self.hidden(dot(p, self.right), dot(p, self.up), dot(p, self.d), own)


def resample(pts3: Sequence[Vec3], step: float, snap=None) -> list[tuple[Vec3, float]]:
    """``pts3`` with points added so no two follow more than ``step`` apart, each with
    its arc length along the polyline; ``snap`` puts an added point back on the exact
    curve (a point on a circle's chord lies inside the circle, where the faces beside
    it can hide it)."""
    out = [(tuple(pts3[0]), 0.0)]
    s = 0.0
    for a, b in zip(pts3, pts3[1:], strict=False):
        seg = math.dist(a, b)
        n = max(1, math.ceil(seg / step)) if step > 0 else 1
        for k in range(1, n + 1):
            f = k / n
            q = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f)
            out.append((snap(q) if snap is not None and k < n else q, s + seg * f))
        s += seg
    return out


def point_at(pts3: Sequence[Vec3], length: float, snap=None) -> Vec3:
    """The point ``length`` along the polyline, put back on the curve by ``snap``."""
    s = 0.0
    for k, (a, b) in enumerate(zip(pts3, pts3[1:], strict=False)):
        seg = math.dist(a, b)
        if s + seg >= length or k == len(pts3) - 2:
            f = 0.0 if seg == 0 else min(1.0, max(0.0, (length - s) / seg))
            q = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f)
            return snap(q) if snap is not None and 0.0 < f < 1.0 else q
        s += seg
    return tuple(pts3[-1])


def visibility(occ: Occluder, pts3: Sequence[Vec3], own: frozenset[int], step: float, snap=None):
    """Runs ``[(visible, [3D points], (s0, s1))]`` along the polyline, each change of
    visibility bisected, with the arc-length range each run covers."""
    samples = resample(pts3, step, snap)
    states = [occ.visible_at(p, own) for p, _s in samples]
    runs = []
    cur = [samples[0][0]]
    start = 0.0
    state = states[0]
    for k in range(1, len(samples)):
        p, s = samples[k]
        if states[k] == state:
            cur.append(p)
            continue
        lo, hi = samples[k - 1][1], s
        for _ in range(BISECT):
            mid = 0.5 * (lo + hi)
            if occ.visible_at(point_at(pts3, mid, snap), own) == state:
                lo = mid
            else:
                hi = mid
        cut = 0.5 * (lo + hi)
        q = point_at(pts3, cut, snap)
        cur.append(q)
        runs.append((state, cur, (start, cut)))
        cur = [q, p]
        start = cut
        state = states[k]
    runs.append((state, cur, (start, samples[-1][1])))
    return runs


def circle_snap(curve):
    """A function putting a point back on an edge's circle, or None for other curves."""
    if curve.kind != "circle" or curve.radius <= 0:
        return None
    c, n, r = curve.point, curve.direction, curve.radius

    def snap(p: Vec3) -> Vec3:
        q = (p[0] - c[0], p[1] - c[1], p[2] - c[2])
        h = q[0] * n[0] + q[1] * n[1] + q[2] * n[2]
        radial = (q[0] - n[0] * h, q[1] - n[1] * h, q[2] - n[2] * h)
        length = math.sqrt(radial[0] ** 2 + radial[1] ** 2 + radial[2] ** 2)
        if length == 0:
            return p
        k = r / length
        return (c[0] + radial[0] * k, c[1] + radial[1] * k, c[2] + radial[2] * k)

    return snap


def vertex_faces(model: BrepModel) -> dict[tuple[int, int, int], frozenset[int]]:
    """The faces with a mesh vertex at each point, rounded to 1e-9 m (C4)."""
    out: dict[tuple[int, int, int], set[int]] = {}
    for f in model.faces:
        for v in range(f.vertices[0], f.vertices[1]):
            p = model.points[v]
            out.setdefault((round(p[0] * 1e9), round(p[1] * 1e9), round(p[2] * 1e9)), set()).add(f.index)
    return {k: frozenset(v) for k, v in out.items()}


def own_faces_of_edge(edge, at_vertex) -> frozenset[int]:
    """An edge's own faces: both sides, and every face at its end points."""
    s = {f for f in edge.faces if f >= 0}
    for p in (edge.points[0], edge.points[-1]):
        s |= at_vertex.get((round(p[0] * 1e9), round(p[1] * 1e9), round(p[2] * 1e9)), frozenset())
    return frozenset(s)


__all__ = [
    "BISECT",
    "STEP_FRACTION",
    "Occluder",
    "own_faces_of_edge",
    "point_at",
    "resample",
    "vertex_faces",
    "visibility",
]
