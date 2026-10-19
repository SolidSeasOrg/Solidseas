"""Self-checks of a triangle mesh (provisional), pure Python, each one pass over the triangles.

A closed solid's mesh has three invariants that cost little to test and that a folded
or inside-out mesh breaks (``docs/API.md`` 3.15):

* every directed edge is used once, and its reverse once (:func:`edge_use`);
* every closed shell faces the right way: one that lies inside no other has a
  positive signed volume, one inside another (a void) a negative one, and so on by
  the parity of its nesting (:func:`shells`, :func:`nesting`, :func:`inside_out`).
  A shell that touches another where every probe of it lies has a nesting that
  cannot be told, and is not judged;
* each face's triangles cover its (u, v) polygon once: their absolute (u, v) areas
  add up to the polygon's, and none of them has area in space but none in (u, v)
  (a flap). The tessellator tests this one face by face as it emits triangles.

Points are (x, y, z) tuples; triangles a flat sequence of vertex index triples;
triangle ranges ``(first, count)`` in triangles, not indices.
"""

import math
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

MAX_SHELLS = 64  # closed shells whose nesting is worked out; past this none is judged
PROBES = 4  # points of a shell its nesting is judged from
# A ray direction no mesh is likely to hold an edge or a face along exactly.
_RAY = (0.9999984, 0.0011, 0.0013)
# A ray that passes this near a triangle's edge or corner (in the triangle's own
# barycentric terms) may be counted on both triangles there, or on neither.
_EDGE = 1e-9


class Flat:
    """The points of a flat ``x y z x y z...`` array, as (x, y, z) tuples by index, without
    copying them all."""

    __slots__ = ("a",)

    def __init__(self, a: Sequence[float]) -> None:
        self.a = a

    def __getitem__(self, i: int) -> tuple[float, float, float]:
        a, j = self.a, 3 * i
        return (a[j], a[j + 1], a[j + 2])


def edge_use(tris: Sequence[int], ranges=None) -> tuple[int, int]:
    """``(open, repeated)`` over the triangles (all, or those of ``ranges``): directed
    edges that are not matched by their reverse as often as they are used, and directed
    edges used more than once. A closed, consistently oriented mesh has none of either."""
    c: Counter = Counter()
    for t0, n in ranges if ranges is not None else ((0, len(tris) // 3),):
        for k in range(3 * t0, 3 * (t0 + n), 3):
            a, b, e = tris[k], tris[k + 1], tris[k + 2]
            c[(a, b)] += 1
            c[(b, e)] += 1
            c[(e, a)] += 1
    open_ = sum(1 for (a, b), m in c.items() if c.get((b, a), 0) != m)
    repeated = sum(1 for m in c.values() if m > 1)
    return open_, repeated


@dataclass
class Shell:
    """One shell of a mesh: its triangle ``ranges``, whether it is ``closed`` (every
    directed edge once, its reverse once), its signed ``volume`` (meaningful when
    closed) and its first vertex (``probe``), about which the volume is taken."""

    ranges: list
    closed: bool
    volume: float
    probe: int


def shells(P: Sequence[tuple], tris: Sequence[int], groups, *, closed: bool | None = None) -> list[Shell]:
    """One :class:`Shell` for each group of triangle ranges; ``closed``, when the caller
    knows it (the whole mesh passed :func:`edge_use`), saves counting the edges again.
    The volume is taken about the shell's first vertex, so a shell far from the origin
    loses no digits to it."""
    flat = P.a if isinstance(P, Flat) else None
    out = []
    for ranges in groups:
        c: Counter = Counter()
        count = closed is None
        vol = 0.0
        probe = -1
        ox = oy = oz = 0.0
        for t0, n in ranges:
            for k in range(3 * t0, 3 * (t0 + n), 3):
                a, b, e = tris[k], tris[k + 1], tris[k + 2]
                if count:
                    c[(a, b)] += 1
                    c[(b, e)] += 1
                    c[(e, a)] += 1
                if flat is not None:
                    i, j, m = 3 * a, 3 * b, 3 * e
                    ax, ay, az = flat[i], flat[i + 1], flat[i + 2]
                    bx, by, bz = flat[j], flat[j + 1], flat[j + 2]
                    ex, ey, ez = flat[m], flat[m + 1], flat[m + 2]
                else:
                    (ax, ay, az), (bx, by, bz), (ex, ey, ez) = P[a], P[b], P[e]
                if probe < 0:
                    probe, ox, oy, oz = a, ax, ay, az
                ax, ay, az = ax - ox, ay - oy, az - oz
                bx, by, bz = bx - ox, by - oy, bz - oz
                ex, ey, ez = ex - ox, ey - oy, ez - oz
                vol += ax * (by * ez - bz * ey) - ay * (bx * ez - bz * ex) + az * (bx * ey - by * ex)
        if count:
            whole = bool(c) and all(m == 1 and c.get((b, a)) == 1 for (a, b), m in c.items())
        else:
            whole = bool(closed) and probe >= 0
        out.append(Shell(list(ranges), whole, vol / 6.0, probe))
    return out


def _box(P, tris, ranges) -> tuple[list[float], list[float]]:
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for t0, n in ranges:
        for k in range(3 * t0, 3 * (t0 + n)):
            q = P[tris[k]]
            for i in range(3):
                if q[i] < lo[i]:
                    lo[i] = q[i]
                if q[i] > hi[i]:
                    hi[i] = q[i]
    return lo, hi


def _within(inner, outer, tol: float) -> bool:
    """Whether the box ``inner`` lies inside the box ``outer``, give or take ``tol``."""
    (ilo, ihi), (olo, ohi) = inner, outer
    return all(olo[i] - tol <= ilo[i] and ihi[i] <= ohi[i] + tol for i in range(3))


def _probes(P, tris, ranges, n: int = PROBES) -> list[tuple[float, float, float]]:
    """Up to ``n`` points on a shell, spread over its triangles: each the middle of a
    triangle with area, inside a face rather than on a vertex or an edge the shell may
    share with a shell it touches."""
    total = sum(c for _t, c in ranges)
    picks = sorted({min(total - 1, int((i + 0.5) * total / n)) for i in range(n)}) if total else []
    out = []
    seen = 0
    it = iter(picks)
    want = next(it, None)
    for t0, cnt in ranges:
        while want is not None and want < seen + cnt:
            k = t0 + want - seen
            for t in range(k, min(k + 8, t0 + cnt)):  # the first of the next few with area
                a, b, e = P[tris[3 * t]], P[tris[3 * t + 1]], P[tris[3 * t + 2]]
                ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
                vx, vy, vz = e[0] - a[0], e[1] - a[1], e[2] - a[2]
                if uy * vz - uz * vy or uz * vx - ux * vz or ux * vy - uy * vx:
                    out.append(tuple((a[i] + b[i] + e[i]) / 3.0 for i in range(3)))
                    break
            want = next(it, None)
        seen += cnt
    return out


def _dist2(p, a, b, c) -> float:
    """The square of the distance from point ``p`` to triangle ``a b c`` (Ericson,
    *Real-Time Collision Detection*, 5.1.5)."""
    abx, aby, abz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    acx, acy, acz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    apx, apy, apz = p[0] - a[0], p[1] - a[1], p[2] - a[2]
    d1 = abx * apx + aby * apy + abz * apz
    d2 = acx * apx + acy * apy + acz * apz
    if d1 <= 0.0 and d2 <= 0.0:
        q = a
    else:
        bpx, bpy, bpz = p[0] - b[0], p[1] - b[1], p[2] - b[2]
        d3 = abx * bpx + aby * bpy + abz * bpz
        d4 = acx * bpx + acy * bpy + acz * bpz
        cpx, cpy, cpz = p[0] - c[0], p[1] - c[1], p[2] - c[2]
        d5 = abx * cpx + aby * cpy + abz * cpz
        d6 = acx * cpx + acy * cpy + acz * cpz
        vc, vb, va = d1 * d4 - d3 * d2, d5 * d2 - d1 * d6, d3 * d6 - d5 * d4
        if d3 >= 0.0 and d4 <= d3:
            q = b
        elif d6 >= 0.0 and d5 <= d6:
            q = c
        elif vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
            t = d1 / (d1 - d3)
            q = (a[0] + t * abx, a[1] + t * aby, a[2] + t * abz)
        elif vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
            t = d2 / (d2 - d6)
            q = (a[0] + t * acx, a[1] + t * acy, a[2] + t * acz)
        elif va <= 0.0 and d4 - d3 >= 0.0 and d5 - d6 >= 0.0:
            t = (d4 - d3) / ((d4 - d3) + (d5 - d6))
            q = (b[0] + t * (c[0] - b[0]), b[1] + t * (c[1] - b[1]), b[2] + t * (c[2] - b[2]))
        else:
            s = va + vb + vc
            if s == 0.0:  # no area: its nearest corner will do, it is at most as near
                return min(math.dist(p, a), math.dist(p, b), math.dist(p, c)) ** 2
            v, w = vb / s, vc / s
            q = (a[0] + abx * v + acx * w, a[1] + aby * v + acy * w, a[2] + abz * v + acz * w)
    return (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2


def _parity(P, tris, ranges, probes, tol: float, span: float) -> list[int | None]:
    """For each probe point, the parity of the triangles of ``ranges`` that the ray from it
    along :data:`_RAY` crosses, or None when the probe lies within ``tol`` of one of them
    (it is on that shell, as far as the mesh can tell) or the ray passes so near a
    triangle's edge or corner that it may be counted twice or not at all. ``span`` bounds
    how far a ray goes before it leaves the shell's box. One pass over the triangles
    serves every probe: a triangle is tried only against the probes whose ray can reach
    it (the ray drifts across y and z by little more than ``span`` times a thousandth)."""
    dx, dy, dz = _RAY
    order = sorted(range(len(probes)), key=lambda i: probes[i][1])
    ys = [probes[i][1] for i in order]
    count = [0] * len(probes)
    unsure = [False] * len(probes)
    wy, wz = dy * span + tol, dz * span + tol
    tol2 = tol * tol
    for t0, cnt in ranges:
        for k in range(3 * t0, 3 * (t0 + cnt), 3):
            a, b, e = P[tris[k]], P[tris[k + 1]], P[tris[k + 2]]
            ylo, yhi = min(a[1], b[1], e[1]), max(a[1], b[1], e[1])
            i0 = bisect_left(ys, ylo - wy)
            i1 = bisect_right(ys, yhi + tol)
            if i0 >= i1:
                continue
            zlo, zhi = min(a[2], b[2], e[2]), max(a[2], b[2], e[2])
            xlo, xhi = min(a[0], b[0], e[0]), max(a[0], b[0], e[0])
            e1x, e1y, e1z = b[0] - a[0], b[1] - a[1], b[2] - a[2]
            e2x, e2y, e2z = e[0] - a[0], e[1] - a[1], e[2] - a[2]
            hx, hy, hz = dy * e2z - dz * e2y, dz * e2x - dx * e2z, dx * e2y - dy * e2x
            det = e1x * hx + e1y * hy + e1z * hz
            for j in range(i0, i1):
                q = order[j]
                if unsure[q]:
                    continue
                p = probes[q]
                px, py, pz = p
                if pz < zlo - wz or pz > zhi + tol or px > xhi + tol:
                    continue
                if (
                    px >= xlo - tol
                    and ylo - tol <= py <= yhi + tol
                    and zlo - tol <= pz
                    and _dist2(p, a, b, e) <= tol2
                ):
                    unsure[q] = True
                    continue
                if det == 0.0:
                    continue
                inv = 1.0 / det
                sx, sy, sz = px - a[0], py - a[1], pz - a[2]
                u = (sx * hx + sy * hy + sz * hz) * inv
                if u < -_EDGE or u > 1.0 + _EDGE:
                    continue
                qx, qy, qz = sy * e1z - sz * e1y, sz * e1x - sx * e1z, sx * e1y - sy * e1x
                v = (dx * qx + dy * qy + dz * qz) * inv
                if v < -_EDGE or u + v > 1.0 + _EDGE:
                    continue
                if (e2x * qx + e2y * qy + e2z * qz) * inv <= 0.0:
                    continue  # behind the probe
                if u < _EDGE or v < _EDGE or u + v > 1.0 - _EDGE:
                    unsure[q] = True
                else:
                    count[q] += 1
    return [None if unsure[i] else count[i] % 2 for i in range(len(probes))]


def nesting(
    P: Sequence[tuple], tris: Sequence[int], found: list[Shell], tol: float = 0.0, *, tick=None
) -> list[int | None]:
    """How many other closed shells each closed shell lies inside: None for an open one,
    for one whose nesting cannot be told, or for every one when there are more than
    :data:`MAX_SHELLS` closed shells.

    A shell can lie inside another only when its box does (give or take ``tol``, at
    least a ten-millionth of the mesh's size): a shell beside another, or touching it
    from outside, is outside it without a ray. Otherwise rays are cast from
    :data:`PROBES` points inside the shell's triangles (not from a vertex, which a
    touching shell may share). A probe within ``tol`` of the other shell (on it, as far
    as the mesh can tell; pass the chord tolerance for a tessellation) or whose ray
    grazes an edge says nothing, and the rest must agree: when none is left, or they
    disagree, the shell's nesting cannot be told. A ray is counted only against the
    triangles it can reach, so the whole costs about one pass over the triangles of
    each shell that holds another's box. ``tick(n)``, when given, hears of the work as it
    goes (a clock's tick, which may raise when its time is up)."""
    closed = [k for k, s in enumerate(found) if s.closed]
    depth: list[int | None] = [None] * len(found)
    if len(closed) > MAX_SHELLS:
        return depth
    if len(closed) <= 1:
        for k in closed:
            depth[k] = 0
        return depth
    boxes = {k: _box(P, tris, found[k].ranges) for k in closed}
    lo = [min(boxes[k][0][i] for k in closed) for i in range(3)]
    hi = [max(boxes[k][1][i] for k in closed) for i in range(3)]
    tol = max(tol, 1e-7 * (math.dist(lo, hi) + max(abs(c) for c in (*lo, *hi))))
    d = dict.fromkeys(closed, 0)
    unsure: set[int] = set()
    for j in closed:
        inner = [k for k in closed if k != j and _within(boxes[k], boxes[j], tol)]
        if not inner:
            continue
        probes: list[tuple[float, float, float]] = []
        owner: list[int] = []
        for k in inner:
            got = _probes(P, tris, found[k].ranges)
            probes.extend(got)
            owner.extend([k] * len(got))
        said: dict[int, set[int]] = {k: set() for k in inner}
        if tick is not None:  # a pass over shell j's triangles for each of these probes
            tick(len(probes) + sum(n for _first, n in found[j].ranges))
        span = math.dist(*boxes[j]) + 2.0 * tol
        for k, r in zip(owner, _parity(P, tris, found[j].ranges, probes, tol, span), strict=True):
            if r is not None:
                said[k].add(r)
        for k in inner:
            if len(said[k]) != 1:
                unsure.add(k)
            elif 1 in said[k]:
                d[k] += 1
    for k in closed:
        depth[k] = None if k in unsure else d[k]
    return depth


def inside_out(found: list[Shell], depth: list[int | None]) -> list[int]:
    """The closed shells whose signed volume disagrees with their nesting: positive when
    they lie inside an odd number of others, negative otherwise."""
    out = []
    for k, s in enumerate(found):
        d = depth[k]
        if d is None or not s.closed or s.volume == 0.0:
            continue
        if (s.volume > 0.0) != (d % 2 == 0):
            out.append(k)
    return out


def pieces(tris: Sequence[int], n_vertices: int) -> list[list[tuple[int, int]]]:
    """The triangles grouped by the vertices they share (each group a list of one-triangle
    ranges): a welded mesh's connected pieces, each a shell of its own."""
    parent = list(range(n_vertices))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for k in range(0, len(tris), 3):
        a, b, e = find(tris[k]), find(tris[k + 1]), find(tris[k + 2])
        if b != a:
            parent[b] = a
        e = find(e)
        if e != a:
            parent[e] = a
    groups: dict[int, list[tuple[int, int]]] = {}
    for k in range(0, len(tris) // 3):
        r = find(tris[3 * k])
        g = groups.setdefault(r, [])
        if g and g[-1][0] + g[-1][1] == k:
            g[-1] = (g[-1][0], g[-1][1] + 1)
        else:
            g.append((k, 1))
    return list(groups.values())


def turn(tris, ranges):
    """A copy of ``tris`` with the triangles of ``ranges`` turned round."""
    from array import array

    out = array("I", tris)
    for t0, n in ranges:
        for k in range(3 * t0, 3 * (t0 + n), 3):
            out[k + 1], out[k + 2] = out[k + 2], out[k + 1]
    return out


__all__ = [
    "MAX_SHELLS",
    "PROBES",
    "Flat",
    "Shell",
    "edge_use",
    "inside_out",
    "nesting",
    "pieces",
    "shells",
    "turn",
]
