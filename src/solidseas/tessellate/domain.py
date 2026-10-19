"""A face's (u, v) domain: its loops unwrapped across seams, opened at poles and cut
into simple polygons that a 2D triangulator can take.

* **Unwrap.** Along each loop, whole periods are added so that every step is at
  most half a period; the net change over each periodic direction is the
  loop's winding.
* **Poles.** A point at a pole has no u. It becomes two points on the pole
  line, at the u of the point before and of the point after, with the same
  point id; a run of pole points (boundary samples within a collapsed row's
  reach) is spread along the pole line between those two u, every one kept.
  Along the pole line the outer boundary of a counter-clockwise
  domain runs towards -u at a top pole and +u at a bottom one (the other way
  for a clockwise domain), which fixes how far it turns.
* **Cases.** Every loop (0, 0): the outer loop is the one with the largest area
  whose sign is the face's orientation, the others are holes, shifted by whole
  periods next to it; when no loop has that sign the face is a closed surface
  with holes, or, on a surface that does not close or with loops that reach all
  the way round a closed one (no surface is left outside them), a face whose
  loops all run against it: it keeps its sense, its loops are read the other way
  round (``reversed``) and its largest loop is the outer one. Two loops winding
  opposite ways along one direction: a band, cut
  from one loop to the other with a straight (u, v) segment that appears twice,
  a period apart, with the same point ids. One wrapping loop with a pole on the
  face's side: a cap, cut from the loop to the pole line (on a surface periodic
  in v too, the first pole line beyond the loop, whole periods on). No loop: the whole
  closed surface (on one that does not close, a plane, the face fails with
  ``no_boundary``). Anything else fails with ``seam_configuration``.

Everything here works on lists of ``(u, v, point id)``.
"""

import math

from ._vec import dist, wrap_near
from .topology import FaceFailed

MAX_CUT_POINTS = 2048
MAX_POLE_POINTS = 4096


def area(ring, ku: float = 1.0, kv: float = 1.0) -> float:
    """The signed area of a ring of (u, v, id) in scaled coordinates (positive when
    counter-clockwise)."""
    s = 0.0
    n = len(ring)
    for k in range(n):
        a, b = ring[k], ring[(k + 1) % n]
        s += a[0] * b[1] - b[0] * a[1]
    return 0.5 * s * ku * kv


def unwrap(S, o: int, loop):
    """``(points, du, dv)``: one loop made continuous in (u, v), with each pole point
    replaced by two points on its pole line, and the net change of u and v around it."""
    pu, pv = S.pu, S.pv
    n = len(loop)
    k0 = next((i for i, e in enumerate(loop) if e[0] is not None), None)
    if k0 is None:
        raise FaceFailed("degenerate", "a loop lies on a pole")
    seq = loop[k0:] + loop[:k0]
    u0, v0, p0 = seq[0]
    out = [(u0, v0, p0)]
    cu, cv = u0, v0
    pending: list = []
    for idx in range(1, n + 1):
        u, v, pid = seq[idx % n]
        if u is None:
            pending.append((u, v, pid))
            continue
        if pv is not None:
            v = wrap_near(v, cv, pv)
        if pending:
            vp = pending[0][1]
            if pu is not None:
                du = (u - cu) % pu
                top = vp > cv
                if top == (o > 0) and du > 0.0:
                    du -= pu
                u = cu + du
            # Every pole point stays, each with its own id (the next face uses them too),
            # spread along the pole line from the u before them to the u after.
            if len(pending) == 1:
                out.append((cu, vp, pending[0][2]))
                out.append((u, vp, pending[0][2]))
            else:
                last = len(pending) - 1
                out.extend((cu + (u - cu) * k / last, vp, q[2]) for k, q in enumerate(pending))
            pending = []
        elif pu is not None:
            u = wrap_near(u, cu, pu)
        if idx < n:
            out.append((u, v, pid))
        cu, cv = u, v
    if pending:  # the loop ends on pole points before its first point: handled above
        raise FaceFailed("degenerate", "a loop ends at a pole")
    return out, cu - u0, cv - v0


def winding(S, du: float, dv: float) -> tuple[int, int]:
    wu = wv = 0
    if S.pu is not None:
        wu = round(du / S.pu)
        if abs(du - wu * S.pu) > 1e-6 * S.pu:
            raise FaceFailed("seam_configuration", "a loop does not close in u")
    elif abs(du) > 1e-9 * (1.0 + abs(du)):
        raise FaceFailed("seam_configuration", "a loop does not close in u")
    if S.pv is not None:
        wv = round(dv / S.pv)
        if abs(dv - wv * S.pv) > 1e-6 * S.pv:
            raise FaceFailed("seam_configuration", "a loop does not close in v")
    elif abs(dv) > 1e-9 * (1.0 + abs(dv)):
        raise FaceFailed("seam_configuration", "a loop does not close in v")
    return wu, wv


def _chain(loop, shift_u: float, shift_v: float, start: int):
    """The loop from point ``start`` round to the same point again, ``len(loop) + 1``
    points, the ones past the end shifted by its winding (``shift_u``, ``shift_v``)."""
    n = len(loop)
    out = []
    for k in range(n + 1):
        j = start + k
        u, v, pid = loop[j % n]
        if j >= n:
            u, v = u + shift_u, v + shift_v
        out.append((u, v, pid))
    return out


def _shifted(ring, du: float, dv: float):
    return [(u + du, v + dv, pid) for u, v, pid in ring]


def _inside(ring, u: float, v: float, clock=None) -> bool:
    inside = False
    n = len(ring)
    if clock is not None:
        clock.tick(n)
    for k in range(n):
        u1, v1 = ring[k][0], ring[k][1]
        u2, v2 = ring[(k + 1) % n][0], ring[(k + 1) % n][1]
        if (v1 > v) != (v2 > v):
            x = u1 + (v - v1) * (u2 - u1) / (v2 - v1)
            if u < x:
                inside = not inside
    return inside


class Builder:
    """Builds one face's polygon. ``ev(u, v)`` is the surface point, ``add(p)`` makes a
    point id, ``scale`` the (ku, kv) of the triangulation's frame."""

    def __init__(self, S, o: int, opts, add_point, clock) -> None:
        self.S, self.o, self.opts, self.add_point, self.clock = S, o, opts, add_point, clock
        self.ku, self.kv = 1.0, 1.0
        self.thin = False  # the face is thinner than the chord tolerance
        self.reversed = False  # every loop ran against the face: they were read the other way round
        self._outer: tuple | None = None  # (ring, its centroid and box), for placing holes

    # -- cuts
    def cut(self, a, b):
        """Points strictly between ``a`` and ``b`` along the straight (u, v) segment,
        halved while the surface strays from the chord by more than the tolerance or
        turns by more than the angle."""
        S, chord, angle = self.S, self.opts.chord, self.opts.angle
        pa = S.point(a[0], a[1])
        pb = S.point(b[0], b[1])
        out: list = []
        stack = [(1.0, pb, 0)]
        ta = 0.0
        qa = pa
        while stack:
            self.clock.tick()
            tb, qb, depth = stack[-1]
            tm = 0.5 * (ta + tb)
            um, vm = a[0] + (b[0] - a[0]) * tm, a[1] + (b[1] - a[1]) * tm
            qm = S.point(um, vm)
            mid = ((qa[0] + qb[0]) * 0.5, (qa[1] + qb[1]) * 0.5, (qa[2] + qb[2]) * 0.5)
            dev = dist(qm, mid)
            half = 0.5 * dist(qa, qb)
            bend = 2.0 * math.atan2(dev, half) if half > 0.0 else 0.0
            if depth < 12 and (dev > chord or bend > angle) and len(out) < MAX_CUT_POINTS:
                stack.append((tm, qm, depth + 1))
                continue
            stack.pop()
            if stack:
                u, v = a[0] + (b[0] - a[0]) * tb, a[1] + (b[1] - a[1]) * tb
                out.append((u, v, self.add_point(qb)))
            ta, qa = tb, qb
        return out

    # -- placing holes
    def place(self, outer, hole):
        """``hole`` shifted by whole periods so that it lies inside ``outer``. The work is
        the outer ring's length for each shift tried, so the clock ticks by it."""
        S = self.S
        if S.pu is None and S.pv is None:
            return hole  # nothing to shift
        ks = range(-2, 3) if S.pu is not None else (0,)
        ms = range(-2, 3) if S.pv is not None else (0,)
        u, v = hole[0][0], hole[0][1]
        best, best_d = None, math.inf
        if self._outer is None or self._outer[0] is not outer:
            self.clock.tick(len(outer))
            n = len(outer)
            self._outer = (
                outer,
                (sum(p[0] for p in outer) / n, sum(p[1] for p in outer) / n),
                _box(outer),
            )
        (cu, cv), (u0, u1, v0, v1) = self._outer[1], self._outer[2]
        self.clock.tick(len(hole))
        hu = sum(p[0] for p in hole) / len(hole)
        hv = sum(p[1] for p in hole) / len(hole)
        for k in ks:
            for m in ms:
                du = k * S.pu if S.pu is not None else 0.0
                dv = m * S.pv if S.pv is not None else 0.0
                if u0 <= u + du <= u1 and v0 <= v + dv <= v1 and _inside(outer, u + du, v + dv, self.clock):
                    return _shifted(hole, du, dv)
                d = abs(hu + du - cu) * self.ku + abs(hv + dv - cv) * self.kv
                if d < best_d:
                    best, best_d = (du, dv), d
        return _shifted(hole, *best)  # type: ignore[misc]

    @staticmethod
    def _gap(intervals, period: float, fallback: float):
        """A coordinate (mod ``period``) outside every interval, in the middle of the
        widest gap, or None when they cover everything."""
        if not intervals:
            return fallback
        segs = []
        for lo, hi in intervals:
            if hi - lo >= period:
                return None
            a = lo % period
            segs.append((a, a + (hi - lo)))
        segs.sort()
        merged = []
        for a, b in segs:
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        # wrap the last into the first
        best, where = -1.0, None
        for k, (_a, b) in enumerate(merged):
            na = merged[(k + 1) % len(merged)][0] + (period if k == len(merged) - 1 else 0.0)
            gap = na - b
            if gap > best:
                best, where = gap, b + 0.5 * gap
        if best <= 0.0 or where is None:
            return None
        return where % period

    # -- the cases
    def build(self, loops):
        """The polygon (outer ring first, then holes) of a face with ``loops`` (lists of
        (u or None at a pole, v, id))."""
        S, o = self.S, self.o
        if not loops:
            return self.full([])
        info = []
        for lp in loops:
            pts, du, dv = unwrap(S, o, lp)
            info.append((pts, winding(S, du, dv)))
        allpts = [p for pts, _w in info for p in pts]
        self.ku, self.kv = S.speeds(_box(allpts))
        plain = [pts for pts, w in info if w == (0, 0)]
        wrapping = [(pts, w) for pts, w in info if w != (0, 0)]
        # A loop that encloses no area (two edges along one line, a curve collapsed to
        # a point) bounds nothing: it is left out.
        plain = [p for p in plain if not self._flat(p)]
        closed_surface = S.pu is not None and (S.pv is not None or len(S.poles) >= 2)
        if not wrapping:
            if not plain:
                raise FaceFailed("degenerate", "the face has no area")
            areas = [area(p, self.ku, self.kv) for p in plain]
            cands = [k for k, a in enumerate(areas) if a * o > 0.0]
            if not cands:
                if closed_surface and self._leaves_room(plain):
                    return self.full(plain)
                # On a closed surface the loops that run against the face are holes in the
                # whole surface, unless they reach all the way round it (a torus band whose
                # one loop runs round both its rims and up and down its seam, as OCCT writes
                # a fillet): no surface is left outside them then, and the face is read as
                # on a surface that does not close.
                k = max(range(len(plain)), key=lambda j: abs(areas[j]))
                if abs(areas[k]) <= self.opts.chord * _perimeter(plain[k], self.ku, self.kv):
                    # A face thinner than the chord tolerance: sampled, its sides can cross
                    # and its loop run either way. It is tried as it is.
                    self.thin = True
                    outer = plain[k]
                    return [outer, *(self.place(outer, h) for j, h in enumerate(plain) if j != k)]
                # Every loop runs against the face, on a surface that does not close. The face
                # keeps the sense the file gives it and its loops are read the other way round,
                # its largest loop the outer one, as other readers take such a face (the files
                # met that store faces this way face outward by their sense, their loops
                # wrong). Where the face meets neighbours that disagree, the solid's own check
                # turns it to agree with them (formats.step.orient).
                self.reversed = True
                cands = [k]
            k = max(cands, key=lambda j: abs(areas[j]))
            outer = plain[k]
            holes = [self.place(outer, h) for j, h in enumerate(plain) if j != k]
            return [outer, *holes]
        if len(wrapping) == 2:
            (a, wa), (b, wb) = wrapping
            if wa == (-wb[0], -wb[1]) and (wa[0] == 0) != (wa[1] == 0) and abs(wa[0] + wa[1]) == 1:
                return self.band(a, wa, b, wb, plain)
        if len(wrapping) == 1:
            a, wa = wrapping[0]
            if wa[1] == 0 and abs(wa[0]) == 1:
                return self.cap(a, wa[0], plain)
        raise FaceFailed("seam_configuration", f"loops winding {sorted(w for _p, w in wrapping)}")

    def _leaves_room(self, holes) -> bool:
        """Whether ``holes`` leave a gap round every period of the surface, as the whole
        surface with them cut out needs (:meth:`full`)."""
        S = self.S
        if self._gap([(min(p[0] for p in h), max(p[0] for p in h)) for h in holes], S.pu, 0.0) is None:
            return False
        if S.pv is None:
            return True
        return self._gap([(min(p[1] for p in h), max(p[1] for p in h)) for h in holes], S.pv, 0.0) is not None

    def _flat(self, ring) -> bool:
        """Whether a (0, 0) loop encloses no area, relative to its size (or is a point)."""
        u0, u1, v0, v1 = _box(ring)
        size2 = ((u1 - u0) * self.ku) ** 2 + ((v1 - v0) * self.kv) ** 2
        return size2 <= (0.01 * self.opts.chord) ** 2 or abs(area(ring, self.ku, self.kv)) <= 1e-9 * size2

    def band(self, A, wa, B, wb, holes):
        S, o = self.S, self.o
        axis = 0 if wa[0] != 0 else 1
        if axis == 1:
            return [
                _swap(r)
                for r in _Swapped(self).band(
                    _swap(A), (wa[1], 0), _swap(B), (wb[1], 0), [_swap(h) for h in holes]
                )
            ]
        P = S.pu
        sa = wa[0] * P
        n, m = len(A), len(B)
        # the cut: from the A point and B point nearest each other, among A points in the
        # widest gap of the holes' u ranges when there are holes
        gap = self._gap([(min(p[0] for p in h), max(p[0] for p in h)) for h in holes], P, A[0][0])
        cands = range(n) if n <= 48 else [int(n * k / 48) for k in range(48)]
        if holes and gap is not None:
            cands = sorted(cands, key=lambda i: abs(wrap_near(A[i][0], gap, P) - gap))[:8]
        best = None
        for i in cands:
            ua, va = A[i][0], A[i][1]
            for j in range(m):
                ub = wrap_near(B[j][0], ua, P)
                vb = B[j][1] if S.pv is None else wrap_near(B[j][1], va, S.pv)
                d = math.hypot((ub - ua) * self.ku, (vb - va) * self.kv)
                if best is None or d < best[0]:
                    best = (d, i, j)
        _d, i, j = best  # type: ignore[misc]
        a = _chain(A, sa, 0.0, i)
        b0 = _chain(B, wb[0] * P, 0.0, j)
        su = round((a[-1][0] - B[j][0]) / P) * P
        options = [0.0]
        if S.pv is not None:
            base = round((a[-1][1] - B[j][1]) / S.pv) * S.pv
            options = [base, base + S.pv, base - S.pv]
        for sv in options:
            b = _shifted(b0, su, sv)
            c1 = self.cut(a[-1], b[0])
            c2 = [(u - sa, v, pid) for u, v, pid in reversed(c1)]
            ring = a + c1 + b + c2
            if area(ring) * o > 0.0:
                return [ring, *(self.place(ring, h) for h in holes)]
        raise FaceFailed("seam_configuration", "a band whose loops run the same way as the face")

    def cap(self, A, wu: int, holes):
        S, o = self.S, self.o
        P = S.pu
        top = wu * o > 0
        vs = [p[1] for p in A]
        hi, lo = max(vs), min(vs)
        candidates = S.poles
        if S.pv is not None:
            # periodic in v too (a spun circle crossing its axis): each pole's line the
            # first whole number of periods beyond the loop
            T = S.pv
            if top:
                candidates = [(v + math.ceil((hi - 1e-12 - v) / T) * T, q) for v, q in S.poles]
            else:
                candidates = [(v - math.ceil((v - lo - 1e-12) / T) * T, q) for v, q in S.poles]
        if top:
            poles = [pv for pv in candidates if pv[0] >= hi - 1e-12]
            pole = min(poles, key=lambda q: q[0]) if poles else None
        else:
            poles = [pv for pv in candidates if pv[0] <= lo + 1e-12]
            pole = max(poles, key=lambda q: q[0]) if poles else None
        if pole is None:
            raise FaceFailed(
                "seam_configuration", "one loop wraps the surface and there is no pole beyond it"
            )
        vp, point = pole
        n = len(A)
        start = 0
        if holes:
            gap = self._gap([(min(p[0] for p in h), max(p[0] for p in h)) for h in holes], P, A[0][0])
            if gap is not None:
                start = min(range(n), key=lambda i: abs(wrap_near(A[i][0], gap, P) - gap))
        a = _chain(A, wu * P, 0.0, start)
        pid = self.add_point(point)
        c1 = self.cut(a[-1], (a[-1][0], vp))
        # The pole line needs no more points than the loop has round the period: P is in
        # the surface's own parameter units (knot units for a B-spline), not radians.
        steps = max(2, min(math.ceil(P / max(self.opts.angle, 1e-3)), len(A), MAX_POLE_POINTS))
        if len(a) + 2 * len(c1) + steps + 1 > self.opts.max_face_points:
            raise FaceFailed("max_face_points", "too many points on the face's boundary")
        u1, u0 = a[-1][0], a[0][0]
        line = [(u1 + (u0 - u1) * k / steps, vp, pid) for k in range(steps + 1)]
        c2 = [(u - wu * P, v, q) for u, v, q in reversed(c1)]
        ring = a + c1 + line + c2
        return [ring, *(self.place(ring, h) for h in holes)]

    def full(self, holes):
        """The whole closed surface, as a rectangle whose seam sides share their point
        ids and whose pole sides collapse to the pole, with ``holes`` inside."""
        S = self.S
        if S.pu is None:  # a plane, say: nothing bounds it, and it has no seam to speak of
            raise FaceFailed("no_boundary", "a face with no loop on a surface that does not close")
        if S.pv is not None:
            vb, vt, poles = None, None, None
        else:
            if len(S.poles) < 2:
                raise FaceFailed("seam_configuration", "a face with no loop on a surface open in v")
            lo = min(S.poles, key=lambda q: q[0])
            hi = max(S.poles, key=lambda q: q[0])
            vb, vt, poles = lo[0], hi[0], (lo, hi)
        u0 = self._gap([(min(p[0] for p in h), max(p[0] for p in h)) for h in holes], S.pu, 0.0)
        if u0 is None:
            raise FaceFailed("seam_configuration", "holes all round the surface")
        if S.pv is not None:
            v0 = self._gap([(min(p[1] for p in h), max(p[1] for p in h)) for h in holes], S.pv, 0.0)
            if v0 is None:
                raise FaceFailed("seam_configuration", "holes all round the surface")
            vb, vt = v0, v0 + S.pv
        box = (u0, u0 + S.pu, vb, vt)
        self.ku, self.kv = S.speeds(box)
        du, dv = S.steps(box, self.opts.chord, self.opts.angle)
        ang = max(self.opts.angle, 1e-3)
        nu = max(4, math.ceil(S.pu / min(du or ang, ang)))
        nv = max(2, math.ceil((vt - vb) / (dv or (vt - vb) / 2)))
        nu, nv = min(nu, MAX_POLE_POINTS), min(nv, MAX_POLE_POINTS)
        us = [u0 + S.pu * k / nu for k in range(nu + 1)]
        vs = [vb + (vt - vb) * k / nv for k in range(nv + 1)]
        ev, add = S.point, self.add_point
        if poles is not None:
            pb, pt = add(poles[0][1]), add(poles[1][1])
            bottom = [pb] * (nu + 1)
            topids = [pt] * (nu + 1)
        else:
            corner = add(ev(u0, vb))
            bottom = [corner] + [add(ev(us[k], vb)) for k in range(1, nu)] + [corner]
            topids = bottom
        side = [add(ev(u0, vs[k])) for k in range(1, nv)]
        ring = [(us[k], vb, bottom[k]) for k in range(nu + 1)]
        ring += [(us[-1], vs[k], side[k - 1]) for k in range(1, nv)]
        ring += [(us[k], vt, topids[k]) for k in range(nu, -1, -1)]
        ring += [(us[0], vs[k], side[k - 1]) for k in range(nv - 1, 0, -1)]
        return [ring, *(self.place(ring, h) for h in holes)]


def _perimeter(ring, ku: float, kv: float) -> float:
    n = len(ring)
    return sum(
        math.hypot((ring[(k + 1) % n][0] - ring[k][0]) * ku, (ring[(k + 1) % n][1] - ring[k][1]) * kv)
        for k in range(n)
    )


def _box(pts):
    us = [p[0] for p in pts]
    vs = [p[1] for p in pts]
    return min(us), max(us), min(vs), max(vs)


def _swap(ring):
    return [(v, u, pid) for u, v, pid in ring]


class _SwappedSurface:
    """A surface seen with u and v exchanged, for a band along v."""

    def __init__(self, S) -> None:
        self.S = S
        self.pu, self.pv = S.pv, S.pu
        self.poles = ()

    def point(self, u, v):
        return self.S.point(v, u)

    def speeds(self, box):
        ku, kv = self.S.speeds((box[2], box[3], box[0], box[1]))
        return kv, ku


class _Swapped(Builder):
    def __init__(self, b: Builder) -> None:
        super().__init__(_SwappedSurface(b.S), -b.o, b.opts, b.add_point, b.clock)
        self.ku, self.kv = b.kv, b.ku
