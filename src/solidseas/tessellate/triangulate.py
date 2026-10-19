# Derived work. The ear clipping in this module (earcut, the hole bridging, z-order hashing
# and the filter, cure and split passes) is a Python port of mapbox/earcut
#   https://github.com/mapbox/earcut, ISC License, Copyright (c) 2026, Mapbox (v3.2.4;
#   v3.0.0 says 2016). Its full licence notice is in NOTICE in the SolidSeas repository,
#   as the licence asks. Modified for SolidSeas (2026-10-02): collinear
# points are never removed, and points at one place are merged only when they are one
# point (the same point id). The constrained Delaunay fallback and the triangle mesh are
# SolidSeas' own.
"""2D triangulation of a polygon with holes, and the triangle mesh refinement works on.

:func:`earcut` is a port of earcut (Mapbox, ISC licence, credited in NOTICE):
holes bridged to the outer ring, ear clipping with z-order hashing for rings of
more than 80 points, and earcut's three fallback passes (filter, cure local
self-intersections, split along a valid diagonal). Two changes, both needed for
meshes whose faces share their boundary samples:

* collinear points are never removed, since they are edge samples the next
  face uses too;
* only a point equal to its successor with the same point id, or a zero-width
  spike back to the same point, is filtered: points at the same (u, v) with
  different ids (seam copies, pole lines) stay.

:func:`check` compares the triangles' total area with the polygon's and wants
every triangle counter-clockwise; :func:`cdt` is the fallback, a constrained
Delaunay triangulation (incremental insertion with Lawson flips, constraints
recovered by flips, the outside removed by parity flood fill).
:class:`TriMesh` holds triangles with their edges for Delaunay flips that
keep constrained edges, point insertion and point location by walking.

Everything is in plain floats; no numpy. Every loop is bounded and ticks the
caller's clock.
"""

import math


class _Node:
    __slots__ = ("i", "x", "y", "prev", "next", "z", "prevZ", "nextZ", "steiner")

    def __init__(self, i: int, x: float, y: float) -> None:
        self.i, self.x, self.y = i, x, y
        self.prev = self.next = None
        self.z = 0
        self.prevZ = self.nextZ = None
        self.steiner = False


class _Ctx:
    __slots__ = ("pid", "tris", "minx", "miny", "inv", "clock", "budget")

    def __init__(self, pid, clock, budget) -> None:
        self.pid, self.clock, self.budget = pid, clock, budget
        self.tris: list[tuple[int, int, int]] = []
        self.minx = self.miny = 0.0
        self.inv = 0.0


class _OutOfSteps(Exception):
    pass


def _area(p, q, r) -> float:
    return (q.y - p.y) * (r.x - q.x) - (q.x - p.x) * (r.y - q.y)


def _equals(a, b) -> bool:
    return a.x == b.x and a.y == b.y


def ring_area(xy, ring) -> float:
    """Twice the signed area of ``ring`` (indices into ``xy``): positive when
    counter-clockwise."""
    s = 0.0
    n = len(ring)
    for k in range(n):
        x1, y1 = xy[ring[k]]
        x2, y2 = xy[ring[(k + 1) % n]]
        s += x1 * y2 - x2 * y1
    return s


def _insert(i, x, y, last):
    p = _Node(i, x, y)
    if last is None:
        p.prev = p.next = p
    else:
        p.next = last.next
        p.prev = last
        last.next.prev = p
        last.next = p
    return p


def _remove(p) -> None:
    p.next.prev = p.prev
    p.prev.next = p.next
    if p.prevZ is not None:
        p.prevZ.nextZ = p.nextZ
    if p.nextZ is not None:
        p.nextZ.prevZ = p.prevZ


def _linked(xy, ring, outer: bool, pid):
    """A circular list of ``ring``: counter-clockwise for the outer ring, clockwise for a
    hole (earcut's "clockwise" is in a y-down frame; its area has the opposite sign)."""
    last = None
    order = ring if outer == (ring_area(xy, ring) > 0) else list(reversed(ring))
    for i in order:
        x, y = xy[i]
        last = _insert(i, x, y, last)
    if (
        last is not None
        and last is not last.next
        and _equals(last, last.next)
        and pid[last.i] == pid[last.next.i]
    ):
        _remove(last)
        last = last.next
    return last


def _filter(ctx: _Ctx, start, end=None):
    """Remove a point equal to its successor with the same id, and a zero-width spike
    back to the same point (earcut removes every collinear point; not here)."""
    if start is None:
        return start
    if end is None:
        end = start
    pid = ctx.pid
    p = start
    while True:
        ctx.clock.tick()
        again = False
        nxt = p.next
        dup = _equals(p, nxt) and pid[p.i] == pid[nxt.i]
        spike = (
            not p.steiner
            and p.prev is not nxt
            and pid[p.prev.i] == pid[nxt.i]
            and _equals(p.prev, nxt)
            and _area(p.prev, p, nxt) == 0
        )
        if not p.steiner and (dup or spike):
            _remove(p)
            p = end = p.prev
            if p is p.next:
                break
            again = True
        else:
            p = p.next
        if not again and p is end:
            break
    return end


def _z_order(x, y, minx, miny, inv) -> int:
    x = int((x - minx) * inv)
    y = int((y - miny) * inv)
    x = (x | (x << 8)) & 0x00FF00FF
    x = (x | (x << 4)) & 0x0F0F0F0F
    x = (x | (x << 2)) & 0x33333333
    x = (x | (x << 1)) & 0x55555555
    y = (y | (y << 8)) & 0x00FF00FF
    y = (y | (y << 4)) & 0x0F0F0F0F
    y = (y | (y << 2)) & 0x33333333
    y = (y | (y << 1)) & 0x55555555
    return x | (y << 1)


def _index_curve(ctx: _Ctx, start) -> None:
    p = start
    while True:
        if p.z == 0:
            p.z = _z_order(p.x, p.y, ctx.minx, ctx.miny, ctx.inv)
        p.prevZ = p.prev
        p.nextZ = p.next
        p = p.next
        if p is start:
            break
    p.prevZ.nextZ = None
    p.prevZ = None
    _sort_linked(ctx, p)


def _sort_linked(ctx: _Ctx, lst):
    """Simon Tatham's linked-list merge sort on z, as earcut does it."""
    in_size = 1
    while True:
        p = lst
        lst = None
        tail = None
        merges = 0
        while p is not None:
            merges += 1
            q = p
            psize = 0
            for _ in range(in_size):
                psize += 1
                q = q.nextZ
                if q is None:
                    break
            qsize = in_size
            while psize > 0 or (qsize > 0 and q is not None):
                ctx.clock.tick()
                if psize != 0 and (qsize == 0 or q is None or p.z <= q.z):
                    e = p
                    p = p.nextZ
                    psize -= 1
                else:
                    e = q
                    q = q.nextZ
                    qsize -= 1
                if tail is not None:
                    tail.nextZ = e
                else:
                    lst = e
                e.prevZ = tail
                tail = e
            p = q
        tail.nextZ = None
        in_size *= 2
        if merges <= 1:
            return lst


def _point_in_triangle(ax, ay, bx, by, cx, cy, px, py) -> bool:
    return (
        (cx - px) * (ay - py) >= (ax - px) * (cy - py)
        and (ax - px) * (by - py) >= (bx - px) * (ay - py)
        and (bx - px) * (cy - py) >= (cx - px) * (by - py)
    )


def _is_ear(ctx: _Ctx, ear) -> bool:
    a, b, c = ear.prev, ear, ear.next
    if _area(a, b, c) >= 0:
        return False
    ax, bx, cx, ay, by, cy = a.x, b.x, c.x, a.y, b.y, c.y
    x0, x1 = min(ax, bx, cx), max(ax, bx, cx)
    y0, y1 = min(ay, by, cy), max(ay, by, cy)
    p = c.next
    while p is not a:
        ctx.clock.tick()
        if (
            x0 <= p.x <= x1
            and y0 <= p.y <= y1
            and not (p.x == ax and p.y == ay)
            and _point_in_triangle(ax, ay, bx, by, cx, cy, p.x, p.y)
            and _area(p.prev, p, p.next) >= 0
        ):
            return False
        p = p.next
    return True


def _is_ear_hashed(ctx: _Ctx, ear) -> bool:
    a, b, c = ear.prev, ear, ear.next
    if _area(a, b, c) >= 0:
        return False
    ax, bx, cx, ay, by, cy = a.x, b.x, c.x, a.y, b.y, c.y
    x0, x1 = min(ax, bx, cx), max(ax, bx, cx)
    y0, y1 = min(ay, by, cy), max(ay, by, cy)
    minz = _z_order(x0, y0, ctx.minx, ctx.miny, ctx.inv)
    maxz = _z_order(x1, y1, ctx.minx, ctx.miny, ctx.inv)
    p, n = ear.prevZ, ear.nextZ

    def blocks(q) -> bool:
        ctx.clock.tick()
        return (
            x0 <= q.x <= x1
            and y0 <= q.y <= y1
            and q is not a
            and q is not c
            and not (q.x == ax and q.y == ay)
            and _point_in_triangle(ax, ay, bx, by, cx, cy, q.x, q.y)
            and _area(q.prev, q, q.next) >= 0
        )

    while p is not None and p.z >= minz and n is not None and n.z <= maxz:
        if blocks(p):
            return False
        p = p.prevZ
        if blocks(n):
            return False
        n = n.nextZ
    while p is not None and p.z >= minz:
        if blocks(p):
            return False
        p = p.prevZ
    while n is not None and n.z <= maxz:
        if blocks(n):
            return False
        n = n.nextZ
    return True


def _sign(v: float) -> int:
    return 1 if v > 0 else (-1 if v < 0 else 0)


def _on_segment(p, q, r) -> bool:
    return min(p.x, r.x) <= q.x <= max(p.x, r.x) and min(p.y, r.y) <= q.y <= max(p.y, r.y)


def _intersects(p1, q1, p2, q2) -> bool:
    o1 = _sign(_area(p1, q1, p2))
    o2 = _sign(_area(p1, q1, q2))
    o3 = _sign(_area(p2, q2, p1))
    o4 = _sign(_area(p2, q2, q1))
    if o1 != o2 and o3 != o4:
        return True
    if o1 == 0 and _on_segment(p1, p2, q1):
        return True
    if o2 == 0 and _on_segment(p1, q2, q1):
        return True
    if o3 == 0 and _on_segment(p2, p1, q2):
        return True
    return o4 == 0 and _on_segment(p2, q1, q2)


def _intersects_polygon(ctx: _Ctx, a, b) -> bool:
    p = a
    while True:
        ctx.clock.tick()
        if p.i != a.i and p.next.i != a.i and p.i != b.i and p.next.i != b.i and _intersects(p, p.next, a, b):
            return True
        p = p.next
        if p is a:
            return False


def _locally_inside(a, b) -> bool:
    if _area(a.prev, a, a.next) < 0:
        return _area(a, b, a.next) >= 0 and _area(a, a.prev, b) >= 0
    return _area(a, b, a.prev) < 0 or _area(a, a.next, b) < 0


def _middle_inside(ctx: _Ctx, a, b) -> bool:
    p = a
    inside = False
    px, py = (a.x + b.x) / 2, (a.y + b.y) / 2
    while True:
        ctx.clock.tick()
        if (
            (p.y > py) != (p.next.y > py)
            and p.next.y != p.y
            and px < (p.next.x - p.x) * (py - p.y) / (p.next.y - p.y) + p.x
        ):
            inside = not inside
        p = p.next
        if p is a:
            return inside


def _valid_diagonal(ctx: _Ctx, a, b) -> bool:
    if a.next.i == b.i or a.prev.i == b.i or _intersects_polygon(ctx, a, b):
        return False
    if _locally_inside(a, b) and _locally_inside(b, a) and _middle_inside(ctx, a, b):
        return bool(_area(a.prev, a, b.prev) or _area(a, b.prev, b))
    return _equals(a, b) and _area(a.prev, a, a.next) > 0 and _area(b.prev, b, b.next) > 0


def _split_polygon(a, b):
    a2 = _Node(a.i, a.x, a.y)
    b2 = _Node(b.i, b.x, b.y)
    an, bp = a.next, b.prev
    a.next = b
    b.prev = a
    a2.next = an
    an.prev = a2
    b2.next = a2
    a2.prev = b2
    bp.next = b2
    b2.prev = bp
    return b2


def _cure(ctx: _Ctx, start):
    p = start
    while True:
        ctx.clock.tick()
        a, b = p.prev, p.next.next
        if (
            not _equals(a, b)
            and _intersects(a, p, p.next, b)
            and _locally_inside(a, b)
            and _locally_inside(b, a)
        ):
            ctx.tris.append((a.i, p.i, b.i))
            _remove(p)
            _remove(p.next)
            p = start = b
        p = p.next
        if p is start:
            break
    return _filter(ctx, p)


def _split_earcut(ctx: _Ctx, start, depth: int) -> bool:
    a = start
    while True:
        b = a.next.next
        while b is not a.prev:
            ctx.clock.tick()
            if a.i != b.i and _valid_diagonal(ctx, a, b):
                c = _split_polygon(a, b)
                a = _filter(ctx, a, a.next)
                c = _filter(ctx, c, c.next)
                ok1 = _earcut_linked(ctx, a, 0, depth + 1)
                ok2 = _earcut_linked(ctx, c, 0, depth + 1)
                return ok1 and ok2
            b = b.next
        a = a.next
        if a is start:
            return False


def _earcut_linked(ctx: _Ctx, ear, passno: int, depth: int = 0) -> bool:
    """True when the ring was clipped completely."""
    if ear is None:
        return True
    if depth > 64:
        return False
    if passno == 0 and ctx.inv:
        _index_curve(ctx, ear)
    stop = ear
    while ear.prev is not ear.next:
        ctx.budget -= 1
        if ctx.budget < 0:
            raise _OutOfSteps
        ctx.clock.tick()
        prev, nxt = ear.prev, ear.next
        if _is_ear_hashed(ctx, ear) if ctx.inv else _is_ear(ctx, ear):
            ctx.tris.append((prev.i, ear.i, nxt.i))
            _remove(ear)
            ear = nxt.next
            stop = nxt.next
            continue
        ear = nxt
        if ear is stop:
            if passno == 0:
                return _earcut_linked(ctx, _filter(ctx, ear), 1, depth)
            if passno == 1:
                ear = _cure(ctx, _filter(ctx, ear))
                return _earcut_linked(ctx, ear, 2, depth)
            return _split_earcut(ctx, ear, depth)
    return True


def _leftmost(start):
    p = start
    left = start
    while True:
        if p.x < left.x or (p.x == left.x and p.y < left.y):
            left = p
        p = p.next
        if p is start:
            return left


def _sector_contains_sector(m, p) -> bool:
    return _area(m.prev, m, p.prev) < 0 and _area(p.next, m, m.next) < 0


def _find_bridge(ctx: _Ctx, hole, outer):
    p = outer
    hx, hy = hole.x, hole.y
    qx = -math.inf
    m = None
    if _equals(hole, p):
        return p
    while True:
        ctx.clock.tick()
        if _equals(hole, p.next):
            return p.next
        if hy <= p.y and hy >= p.next.y and p.next.y != p.y:
            x = p.x + (hy - p.y) * (p.next.x - p.x) / (p.next.y - p.y)
            if x <= hx and x > qx:
                qx = x
                m = p if p.x < p.next.x else p.next
                if x == hx:
                    return m
        p = p.next
        if p is outer:
            break
    if m is None:
        return None
    stop = m
    mx, my = m.x, m.y
    tan_min = math.inf
    p = m
    while True:
        ctx.clock.tick()
        if (
            hx >= p.x >= mx
            and hx != p.x
            and _point_in_triangle(hx if hy < my else qx, hy, mx, my, qx if hy < my else hx, hy, p.x, p.y)
        ):
            tan = abs(hy - p.y) / (hx - p.x)
            if _locally_inside(p, hole) and (
                tan < tan_min
                or (tan == tan_min and (p.x > m.x or (p.x == m.x and _sector_contains_sector(m, p))))
            ):
                m = p
                tan_min = tan
        p = p.next
        if p is stop:
            break
    return m


def _hole_order(n):
    """Holes left to right; holes whose leftmost points meet, counter-clockwise (earcut 3)."""
    nx = n.next
    dx = nx.x - n.x
    slope = (nx.y - n.y) / dx if dx else math.copysign(math.inf, nx.y - n.y)
    return (n.x, n.y, slope)


def earcut(xy, outer, holes, pid, clock, max_steps: int = 50_000_000):
    """Triangles of the polygon ``outer`` with ``holes`` (lists of indices into
    ``xy``), counter-clockwise in ``xy``, and whether the clipping finished.
    ``pid[i]`` is the point id of index i (two indices at one position with one id
    are one point)."""
    ctx = _Ctx(pid, clock, max_steps)
    o = _linked(xy, outer, True, pid)
    if o is None or o.next is o.prev:
        return [], False
    queue = []
    for h in holes:
        if len(h) < 1:
            continue
        ln = _linked(xy, h, False, pid)
        if ln is ln.next:
            ln.steiner = True
        queue.append(_leftmost(ln))
    queue.sort(key=_hole_order)
    try:
        for h in queue:
            bridge = _find_bridge(ctx, h, o)
            if bridge is None:
                return ctx.tris, False
            rev = _split_polygon(bridge, h)
            _filter(ctx, rev, rev.next)
            o = _filter(ctx, bridge, bridge.next)
        n = len(outer) + sum(len(h) for h in holes)
        if n > 80:
            every = [i for r in (outer, *holes) for i in r]
            xs = [xy[i][0] for i in every]
            ys = [xy[i][1] for i in every]
            ctx.minx, ctx.miny = min(xs), min(ys)
            size = max(max(xs) - ctx.minx, max(ys) - ctx.miny)
            ctx.inv = 32767.0 / size if size > 0 else 0.0
        ok = _earcut_linked(ctx, o, 0)
    except _OutOfSteps:
        return ctx.tris, False
    except RecursionError:
        return ctx.tris, False
    # earcut emits (prev, ear, next) with its area < 0, which is counter-clockwise here
    return ctx.tris, ok


def tri_area2(xy, a: int, b: int, c: int) -> float:
    ax, ay = xy[a]
    bx, by = xy[b]
    cx, cy = xy[c]
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def check(xy, rings, tris, rel: float = 1e-9) -> bool:
    """The triangles cover the polygon: every one counter-clockwise (or of zero area)
    and their total area equal to the outer ring's less the holes', within ``rel``."""
    want = abs(ring_area(xy, rings[0])) - sum(abs(ring_area(xy, h)) for h in rings[1:])
    got = 0.0
    scale = 0.0
    for a, b, c in tris:
        s = tri_area2(xy, a, b, c)
        if s < 0.0:
            return False
        got += s
        scale = max(scale, abs(s))
    if want <= 0.0:
        return False
    return abs(got - want) <= rel * max(want, scale)


def covers(xy, rings, tris, tol_area: float) -> bool:
    """A looser :func:`check` for rings that touch or cross themselves by less than the
    chord tolerance (a slot whose end is tangent to an arc, a face thinner than the
    tolerance): the triangles' area, with any clockwise ones counted against it, is
    within ``tol_area`` of the polygon's."""
    want = abs(ring_area(xy, rings[0])) - sum(abs(ring_area(xy, h)) for h in rings[1:])
    pos = neg = 0.0
    for a, b, c in tris:
        s = tri_area2(xy, a, b, c)
        if s >= 0.0:
            pos += s
        else:
            neg -= s
    return want > 0.0 and 0.5 * (abs(pos - want) + 2.0 * neg) <= tol_area


def perimeter(xy, rings) -> float:
    total = 0.0
    for r in rings:
        n = len(r)
        for k in range(n):
            a, b = xy[r[k]], xy[r[(k + 1) % n]]
            total += math.hypot(b[0] - a[0], b[1] - a[1])
    return total


def fill_gaps(xy, rings, tris):
    """Boundary points the triangles skip (a T-junction against the next face) are put
    back: where a run of them lies between two points the triangles use, the triangle on
    that chord becomes a fan through them. Returns ``(triangles, filled, left)``."""
    used: set[int] = set()
    for t in tris:
        used.update(t)
    edge: dict[tuple[int, int], int] = {}
    out = [list(t) for t in tris]
    for k, (a, b, c) in enumerate(tris):
        edge[(a, b)] = k
        edge[(b, c)] = k
        edge[(c, a)] = k
    filled = left = 0
    for r in rings:
        n = len(r)
        if n < 3 or all(i in used for i in r):
            continue
        start = next((k for k in range(n) if r[k] in used), None)
        if start is None:
            left += n
            continue
        k = 0
        while k < n:
            i = r[(start + k) % n]
            j = 1
            while j < n and r[(start + k + j) % n] not in used:
                j += 1
            if j > 1:
                gap = [r[(start + k + m) % n] for m in range(1, j)]
                b = r[(start + k + j) % n]
                key = (i, b) if (i, b) in edge else ((b, i) if (b, i) in edge else None)
                t = edge.get(key) if key is not None else None
                if t is None or out[t] is None or i == b:
                    left += len(gap)
                else:
                    tri = out[t]
                    c = next(x for x in tri if x != i and x != b)
                    chain = [i, *gap, b] if key == (i, b) else [b, *reversed(gap), i]
                    out[t] = None
                    for x, y in zip(chain, chain[1:], strict=False):
                        out.append([x, y, c])
                    filled += len(gap)
                    used.update(gap)
            k += j
    return [tuple(t) for t in out if t is not None], filled, left


# --------------------------------------------------------------------------- triangle mesh
def _incircle(xy, a, b, c, d) -> float:
    ax, ay = xy[a]
    bx, by = xy[b]
    cx, cy = xy[c]
    dx, dy = xy[d]
    ax -= dx
    ay -= dy
    bx -= dx
    by -= dy
    cx -= dx
    cy -= dy
    return (
        (ax * ax + ay * ay) * (bx * cy - cx * by)
        - (bx * bx + by * by) * (ax * cy - cx * ay)
        + (cx * cx + cy * cy) * (ax * by - bx * ay)
    )


def _orient(xy, a, b, c) -> float:
    return tri_area2(xy, a, b, c)


class TriMesh:
    """Counter-clockwise triangles over the points ``xy`` with an index of their
    directed edges. ``fixed`` holds undirected edges that are never flipped or split."""

    def __init__(self, xy, tris, fixed, clock) -> None:
        self.xy = xy
        self.t: list[list[int] | None] = [list(t) for t in tris]
        self.fixed = fixed
        self.clock = clock
        self.e: dict[tuple[int, int], int] = {}
        for k, (a, b, c) in enumerate(self.t):  # type: ignore[misc]
            self.e[(a, b)] = k
            self.e[(b, c)] = k
            self.e[(c, a)] = k
        self.last = 0

    def is_fixed(self, a: int, b: int) -> bool:
        return (a, b) in self.fixed or (b, a) in self.fixed

    def _set(self, k: int, tri) -> None:
        old = self.t[k]
        if old is not None:
            a, b, c = old
            for e in ((a, b), (b, c), (c, a)):
                if self.e.get(e) == k:
                    del self.e[e]
        self.t[k] = list(tri)
        a, b, c = tri
        self.e[(a, b)] = k
        self.e[(b, c)] = k
        self.e[(c, a)] = k

    def _add(self, tri) -> int:
        self.t.append(None)
        k = len(self.t) - 1
        self._set(k, tri)
        return k

    def triangles(self):
        return [tuple(t) for t in self.t if t is not None]

    def legalize(self, stack) -> None:
        """Lawson flips from the edges on ``stack``: an edge whose opposite point lies
        inside the circumcircle is flipped, unless fixed or its quadrilateral is not
        strictly convex."""
        xy = self.xy
        guard = 0
        while stack:
            guard += 1
            if guard > 4_000_000:
                return
            self.clock.tick()
            a, b = stack.pop()
            if self.is_fixed(a, b):
                continue
            k1 = self.e.get((a, b))
            k2 = self.e.get((b, a))
            if k1 is None or k2 is None:
                continue
            t1, t2 = self.t[k1], self.t[k2]
            c = _third(t1, a, b)
            d = _third(t2, b, a)
            if c is None or d is None or c == d:
                continue
            if _incircle(xy, a, b, c, d) <= 0.0:
                continue
            if not self._flippable(a, b, c, d):
                continue
            self._set(k1, (c, a, d))
            self._set(k2, (d, b, c))
            stack.extend(((a, d), (d, b), (b, c), (c, a)))

    def _flippable(self, a, b, c, d) -> bool:
        """The quadrilateral a, d, b, c (a-b the diagonal) is strictly convex."""
        xy = self.xy
        return _orient(xy, c, a, d) > 0 and _orient(xy, d, b, c) > 0

    def flip(self, a, b) -> bool:
        if self.is_fixed(a, b):
            return False
        k1 = self.e.get((a, b))
        k2 = self.e.get((b, a))
        if k1 is None or k2 is None:
            return False
        c = _third(self.t[k1], a, b)
        d = _third(self.t[k2], b, a)
        if c is None or d is None or not self._flippable(a, b, c, d):
            return False
        self._set(k1, (c, a, d))
        self._set(k2, (d, b, c))
        return True

    def make_delaunay(self) -> None:
        self.legalize([e for e in list(self.e) if e[0] < e[1]])

    def insert_in(self, p: int, k: int) -> None:
        """Insert point ``p``, strictly inside triangle ``k``."""
        a, b, c = self.t[k]  # type: ignore[misc]
        self._set(k, (a, b, p))
        self._add((b, c, p))
        self._add((c, a, p))
        self.last = k
        self.legalize([(a, b), (b, c), (c, a)])

    def split_edge(self, a: int, b: int, p: int) -> bool:
        """Insert ``p`` on the interior edge a-b (both triangles beside it)."""
        k1 = self.e.get((a, b))
        k2 = self.e.get((b, a))
        if k1 is None or k2 is None or self.is_fixed(a, b):
            return False
        c = _third(self.t[k1], a, b)
        d = _third(self.t[k2], b, a)
        if c is None or d is None:
            return False
        xy = self.xy
        if not (
            _orient(xy, a, p, c) > 0
            and _orient(xy, p, b, c) > 0
            and _orient(xy, b, p, d) > 0
            and _orient(xy, p, a, d) > 0
        ):
            return False
        self._set(k1, (a, p, c))
        self._add((p, b, c))
        self._set(k2, (b, p, d))
        self._add((p, a, d))
        self.last = k1
        self.legalize([(b, c), (c, a), (a, d), (d, b)])
        return True

    def walk(self, px: float, py: float, start: int | None = None):
        """The triangle containing (px, py), by walking from ``start``: ``(k, on_edge)``
        with ``on_edge`` an edge (a, b) when the point lies on one, or None when the walk
        leaves the mesh or runs too long."""
        xy = self.xy
        k = self.last if start is None else start
        if k >= len(self.t) or self.t[k] is None:
            k = next((i for i, t in enumerate(self.t) if t is not None), None)
            if k is None:
                return None
        prev = -1
        for _ in range(len(self.t) + 8):
            self.clock.tick()
            tri = self.t[k]
            nxt = None
            edge = None
            for u, v in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
                ux, uy = xy[u]
                vx, vy = xy[v]
                d = (vx - ux) * (py - uy) - (vy - uy) * (px - ux)
                if d < 0:
                    cand = self.e.get((v, u))
                    if cand is None:
                        return None
                    if cand != prev:
                        nxt = cand
                        break
                    nxt = cand
                elif d == 0:
                    edge = (u, v)
            if nxt is None:
                return k, edge
            prev, k = k, nxt
        return None

    def locate(self, px: float, py: float):
        """``(k, edge)`` by a linear scan: the fallback of :meth:`walk`."""
        xy = self.xy
        for k, tri in enumerate(self.t):
            self.clock.tick()
            if tri is None:
                continue
            a, b, c = tri
            ds = []
            for u, v in ((a, b), (b, c), (c, a)):
                ux, uy = xy[u]
                vx, vy = xy[v]
                ds.append((vx - ux) * (py - uy) - (vy - uy) * (px - ux))
            if min(ds) >= 0:
                zero = [e for e, d in zip(((a, b), (b, c), (c, a)), ds, strict=True) if d == 0]
                return k, (zero[0] if zero else None)
        return None


def _third(tri, a, b):
    for v in tri:
        if v != a and v != b:
            return v
    return None


# --------------------------------------------------------------------------- constrained Delaunay
def cdt(xy, rings, pid, clock):
    """A constrained Delaunay triangulation of the polygon ``rings`` (outer first):
    the triangles inside it, counter-clockwise, or None when it cannot be built (two
    points at one place with different ids, a constraint that cannot be recovered,
    crossing rings)."""
    idx = sorted({i for r in rings for i in r})
    if len(idx) < 3:
        return None
    # one index for each position; two different points at one position cannot be done
    first_at: dict[tuple[float, float], int] = {}
    alias: dict[int, int] = {}
    for i in idx:
        key = (xy[i][0], xy[i][1])
        j = first_at.get(key)
        if j is None:
            first_at[key] = i
            alias[i] = i
        elif pid[j] == pid[i]:
            alias[i] = j
        else:
            return None
    pts = list(first_at.values())
    xs = [xy[i][0] for i in pts]
    ys = [xy[i][1] for i in pts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    size = max(maxx - minx, maxy - miny)
    if not size > 0.0:
        return None
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    work = list(xy)
    s0 = len(work)
    big = 64.0 * size
    work.extend([(cx - big, cy - big), (cx + big, cy - big), (cx, cy + big)])
    mesh = TriMesh(work, [(s0, s0 + 1, s0 + 2)], set(), clock)
    # insert in a coarse grid order so that walks are short
    cell = size / max(1.0, math.sqrt(len(pts)))
    order = sorted(pts, key=lambda i: (int((work[i][1] - miny) / cell), work[i][0]))
    for i in order:
        x, y = work[i]
        got = mesh.walk(x, y) or mesh.locate(x, y)
        if got is None:
            return None
        k, edge = got
        if edge is None:
            mesh.insert_in(i, k)
        elif not mesh.split_edge(edge[0], edge[1], i):
            return None
    # constraints
    cons: set[tuple[int, int]] = set()
    for r in rings:
        n = len(r)
        for k in range(n):
            a, b = alias[r[k]], alias[r[(k + 1) % n]]
            if a != b:
                cons.add((a, b))
    for a, b in list(cons):
        if not _recover(mesh, a, b):
            return None
        mesh.fixed.add((a, b))  # recovered: later recoveries flip around it
    if any((a, b) not in mesh.e and (b, a) not in mesh.e for a, b in cons):
        return None  # constraints that cross each other
    # parity flood fill from the super triangle's corners
    inside: dict[int, bool] = {}
    seeds = [k for k, t in enumerate(mesh.t) if t is not None and (t[0] >= s0 or t[1] >= s0 or t[2] >= s0)]
    stack = [(k, False) for k in seeds]
    while stack:
        clock.tick()
        k, state = stack.pop()
        if k in inside:
            continue
        inside[k] = state
        a, b, c = mesh.t[k]  # type: ignore[misc]
        for u, v in ((a, b), (b, c), (c, a)):
            nk = mesh.e.get((v, u))
            if nk is None or nk in inside:
                continue
            crossing = (u, v) in cons or (v, u) in cons
            stack.append((nk, (not state) if crossing else state))
    out = []
    for k, t in enumerate(mesh.t):
        if t is None or not inside.get(k, False):
            continue
        if t[0] >= s0 or t[1] >= s0 or t[2] >= s0:
            return None
        out.append((t[0], t[1], t[2]))
    return out


def _recover(mesh: TriMesh, a: int, b: int) -> bool:
    """Make a-b an edge of the mesh by flipping the edges that cross it."""
    if (a, b) in mesh.e or (b, a) in mesh.e:
        return True
    xy = mesh.xy
    ax, ay = xy[a]
    bx, by = xy[b]

    def crosses(u, v) -> bool:
        if u in (a, b) or v in (a, b):
            return False
        ux, uy = xy[u]
        vx, vy = xy[v]
        d1 = (bx - ax) * (uy - ay) - (by - ay) * (ux - ax)
        d2 = (bx - ax) * (vy - ay) - (by - ay) * (vx - ax)
        d3 = (vx - ux) * (ay - uy) - (vy - uy) * (ax - ux)
        d4 = (vx - ux) * (by - uy) - (vy - uy) * (bx - ux)
        return d1 * d2 < 0 and d3 * d4 < 0

    for _round in range(64):
        mesh.clock.tick(len(mesh.e))  # each round scans every edge
        crossing = [e for e in mesh.e if e[0] < e[1] and crosses(e[0], e[1])]
        if not crossing:
            return (a, b) in mesh.e or (b, a) in mesh.e
        progress = False
        for u, v in crossing:
            if mesh.flip(u, v):
                progress = True
        if (a, b) in mesh.e or (b, a) in mesh.e:
            return True
        if not progress:
            return False
    return False
