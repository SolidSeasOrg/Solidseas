"""Edge sampling, shared by the two faces of every edge so that meshes close.

Each EDGE is sampled once, into point ids from its start vertex to its end
vertex; vertices have ids of their own, so loops join exactly and both faces of
an edge use the same ids. An edge runs in its curve's natural direction times
the curve's sense; a TRIMMED_CURVE runs from ``parm_1`` to ``parm_2`` of its
basis, with no inversion. A tolerant edge has no curve of its own: it is
sampled along its first fin's curve, a trimmed SP-curve in the fin's own face,
whose (u, v) the samples keep for that face (``docs/FORMAT.md`` 10.8); a fin's
curve in a rolling blend, whose (u, v) is not known, only when no other fin has one.
With the options' ``detail`` on (drawings), the samples keep their curve
parameters too. Where a face beside an edge curves away across it faster than the
edge's samples allow (a small fillet along a long arc), the edge is sampled finer
(:data:`CROSS`), so that the triangles on its chords keep within the angle too.
"""

import math

from ._vec import TWO_PI, atan2, dist, step_angle, unit
from .curves import BCurve, Conic, Curve, Line, Polyline, SPCurve, Trimmed
from .topology import (
    BLEND_BOUND,
    BLENDED_EDGE,
    CURVE_TYPES,
    FACE,
    LOOP,
    PLANE,
    SP_CURVE,
    SURFACE_TYPES,
    TRIMMED_CURVE,
    FaceFailed,
    Topology,
)

MAX_DEPTH = 16  # halvings of one segment
# Samples of a curve closer than MERGE of the chord tolerance, or than POINT (metres, the
# tessellator's own point tolerance) but at most half the chord tolerance, to the one before
# are one, and a segment that short is not halved for its turn alone.
MERGE = 0.01
POINT = 1e-6
# An edge is sampled for the faces beside it as well as for its own course. A chord of
# the edge lies off its curve by its sagitta s, and the points inside a face keep that far
# from the chord over tan(angle) (_engine.Engine._keep_off), so that no triangle on it
# stands up off the surface. Where a face curves away across the edge with radius r (a
# small fillet along a long arc), a point that far in has already turned by
# s / (r tan(angle)), and the triangles on the chord turn with it: o11's fillet, of 1 mm
# along arcs of 5 and 6 mm, turned up to 59 degrees at the default chord. A triangle on
# the chord can keep within the angle there only when s is under angle^2 r / 2, and then
# only with its third point at one distance in; at half that, CROSS angle^2 r, it can lie
# anywhere from about 0.3 to 1.7 times angle r in, room enough for the refinement. An
# edge whose sagitta is over CROSS angle^2 r, r the smallest radius across it of the faces
# beside it at CROSS_PROBES points along it, is sampled again with that as its chord
# tolerance, but not below CROSS_FLOOR of the chord tolerance, so that an edge gets at
# most about three times its samples (the square root of the inverse) for a fillet far
# smaller than the chord. Measured with an angle of 15 degrees: the triangles on such
# chords kept within 13.8 degrees on o11 and on synthetic fillets of 0.2 to 1 mm along
# arcs of 1.35 to 50 mm, where they had turned 22 to 74 degrees; at an eighth they kept
# within 14.3 degrees with up to 16% more points, and at a half o11's still turned 20.
CROSS = 0.25
CROSS_FLOOR = 0.1
CROSS_PROBES = 3
# What a neighbour's damaged geometry raises while an edge is sampled: its face says why
# when it is done, and the edge is sampled for its own course alone.
_UNFORESEEN = (ZeroDivisionError, OverflowError, ValueError, IndexError, KeyError, TypeError, AttributeError)


class Samples:
    """An edge's samples: ``ids`` from its start to its end (a ring edge's first and last
    id are the same), and, when they come from an SP-curve, ``uv`` in the file's
    parametrisation of the surface node ``surface``. ``degenerate`` marks a ring edge
    on a line, which has no extent. ``t``, kept only when the options ask for
    ``detail``, is each sample's parameter on the curve sampled (for an intersection
    curve, its position along the chart)."""

    __slots__ = ("ids", "uv", "surface", "degenerate", "t")

    def __init__(self, ids, uv=None, surface=None, degenerate=False, t=None) -> None:
        self.ids, self.uv, self.surface, self.degenerate = ids, uv, surface, degenerate
        self.t = t


class EdgeSampler:
    def __init__(self, topo: Topology, geom, pts, opts, clock) -> None:
        self.topo, self.geom, self.pts, self.opts, self.clock = topo, geom, pts, opts, clock
        self.vertex_ids: dict[int, int] = {}
        self.cache: dict[int, Samples | FaceFailed] = {}
        self.count = 0
        # Sample edges for the faces beside them too (CROSS): the tessellator's options
        # say so; the STEP writer's, which want the curve as it is, do not.
        self.across = bool(getattr(opts, "across", False))
        self.finer = 0  # edges sampled again for a face that curves away across them
        self._hints: dict[int, tuple[float, float]] = {}  # a surface's last (u, v) measured

    def vertex_id(self, vertex) -> int:
        k = self.vertex_ids.get(vertex.index)
        if k is None:
            p = self.topo.point_of(vertex)
            k = self.vertex_ids[vertex.index] = self.pts.add(p, self.topo.tolerance(vertex))
        return k

    def samples(self, edge) -> Samples:
        got = self.cache.get(edge.index)
        if got is None:
            try:
                got = self._sample(edge)
                self.count += 1
            except FaceFailed as exc:
                got = exc
            self.cache[edge.index] = got
        if isinstance(got, FaceFailed):
            raise got
        return got

    def _sample(self, edge) -> Samples:
        topo = self.topo
        sv, ev = topo.edge_ends(edge)
        node = topo.ref(edge, "curve", CURVE_TYPES)
        reverse = False
        surface = None
        if node is None:
            found = []
            for fin in topo.edge_fins(edge):
                c = topo.ref(fin, "curve", CURVE_TYPES)
                if c is not None:
                    found.append((c, topo.sense(fin) < 0))
            if not found:
                raise FaceFailed("bad_reference", "an edge has no curve")
            # A fin's curve in a rolling blend's (u, v) cannot be evaluated (its parameters
            # are not known): the other face's is taken first.
            found.sort(key=lambda f: _on_blend(topo, f[0]))
            node, reverse = found[0]
        curve = self.geom.curve(node)
        ring = sv is None or ev is None
        if ring and (sv is not None or ev is not None):
            raise FaceFailed("bad_reference", "an edge with one vertex missing")
        if ring and _is_line(curve):
            return Samples([], degenerate=True)
        ps = topo.point_of(sv) if sv is not None else None
        pe = topo.point_of(ev) if ev is not None else None
        tol = max(topo.tolerance(edge), 0.0)

        def run(chord=None):
            if reverse:  # a fin's curve runs along the fin: from the edge's end to its start
                got, at = self._curve(curve, pe, ps, chord)
                got.reverse()
                at.reverse()
                return got, at
            return self._curve(curve, ps, pe, chord)

        pts, params = run()
        if self.across:
            finer = self._across(edge, curve, pts, params, tol)
            if finer is not None:
                pts, params = run(finer)
                self.finer += 1
        if len(pts) > self.opts.max_edge_points:
            raise FaceFailed("edge_too_long", f"{len(pts)} points on one edge")
        uv = None
        sp = _sp_curve(curve)
        if sp is not None:
            surface = sp.surface_node.index
            uv = [sp.uv(t) for t in params]
        add = self.pts.add
        if ring:
            first = add(pts[0], tol)
            ids = [first] + [add(p, tol) for p in pts[1:-1]] + [first]
        else:
            ids = [self.vertex_id(sv)] + [add(p, tol) for p in pts[1:-1]] + [self.vertex_id(ev)]
        return Samples(ids, uv, surface, t=params if getattr(self.opts, "detail", False) else None)

    # ------------------------------------------------------------------ the faces beside
    def _across(self, edge, curve: Curve, pts, params, tol: float):
        """A finer chord tolerance for an edge whose sagitta is more than the faces beside
        it allow for their curvature across it (:data:`CROSS`), or None. A line lies on
        its chords, and an intersection's chart points are all there is of it: both are
        left as they are."""
        if _is_line(curve) or _is_chart(curve) or len(pts) < 2:
            return None
        chord, angle = self.opts.chord, self.opts.angle
        floor = CROSS_FLOOR * chord
        sag = 0.0
        for i in range(len(pts) - 1):
            self.clock.tick()
            q = curve.point(0.5 * (params[i] + params[i + 1]))
            a, b = pts[i], pts[i + 1]
            sag = max(sag, dist(q, ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5, (a[2] + b[2]) * 0.5)))
        if not sag > floor:
            return None
        bend = self._bend(edge, curve, params, max(chord, 2.0 * tol))
        if not bend > 0.0:
            return None
        limit = max(CROSS * angle * angle / bend, floor)
        return limit if limit < sag else None

    def _bend(self, edge, curve: Curve, params, tol: float) -> float:
        """The largest curvature across the edge of the faces beside it, at
        :data:`CROSS_PROBES` points along it: a rolling blend's from its sphere's radius,
        a plane's nought, any other surface's measured where the edge lies on it
        (:meth:`.surfaces.Surface.bend_across`). A face whose geometry cannot be measured
        adds nothing: it says why when it is done."""
        topo = self.topo
        n = len(params) - 1
        probes = []
        for k in range(CROSS_PROBES):
            i = min(n - 1, int((k + 0.5) * n / CROSS_PROBES))
            q, dq = curve.d1(0.5 * (params[i] + params[i + 1]))
            t = unit(dq)
            if t is not None:
                probes.append((q, t))
        worst = 0.0
        for fin in topo.edge_fins(edge):
            try:
                loop = topo.ref(fin, "loop", (LOOP,))
                face = topo.ref(loop, "face", (FACE,)) if loop is not None else None
                snode = topo.ref(face, "surface", SURFACE_TYPES) if face is not None else None
                if snode is None or snode.type == PLANE:
                    continue
                if snode.type == BLENDED_EDGE:
                    worst = max(worst, _blend_bend(topo, snode))
                    continue
                S = self.geom.surface(snode)
                hint = self._hints.get(snode.index)
                for q, t in probes:
                    self.clock.tick()
                    got = S.bend_across(q, t, hint, tol, self.clock)
                    if got is not None:
                        k, hint = got
                        worst = max(worst, k)
                if hint is not None:
                    self._hints[snode.index] = hint
            except (FaceFailed, *_UNFORESEEN):
                continue
        return worst

    # ------------------------------------------------------------------ curves
    def _curve(self, curve: Curve, pa, pb, chord: float | None = None):
        """Points and parameters along ``curve`` from ``pa`` to ``pb`` in the edge's
        direction (both None for a ring edge), within ``chord`` of it (None: the chord
        tolerance). The first and last points are later replaced by the vertices."""
        chord = self.opts.chord if chord is None else chord
        angle = self.opts.angle
        if isinstance(curve, Trimmed):
            basis = curve.basis
            t0, t1 = (curve.t1, curve.t2) if curve.sense > 0 else (curve.t2, curve.t1)
            if isinstance(basis, Polyline):
                # An intersection's parameter grows along its chart: the trimmed part runs
                # from parm_1 to parm_2, up the chart or down it.
                qa = pa if pa is not None else (curve.p1 if curve.sense > 0 else curve.p2)
                qb = pb if pb is not None else (curve.p2 if curve.sense > 0 else curve.p1)
                way = (1 if curve.t2 >= curve.t1 else -1) * curve.sense
                return self._chart(
                    basis, qa, qb, ring=pa is None and _same(curve.p1, curve.p2), direction=way
                )
            if isinstance(basis, Line):
                return [pa or basis.point(t0), pb or basis.point(t1)], [t0, t1]
            if isinstance(basis, Conic):
                return _arc(basis, t0, t1, chord, angle, self.opts.max_edge_points)
            if isinstance(basis, Trimmed):
                raise FaceFailed("unsupported_curve", "a trimmed curve of a trimmed curve")
            return self._adaptive(basis, t0, t1, chord)
        if isinstance(curve, Line):
            return [pa, pb], [curve.param(pa), curve.param(pb)]
        if isinstance(curve, Conic):
            d = curve.sense
            if pa is None:
                return _arc(curve, 0.0, d * TWO_PI, chord, angle, self.opts.max_edge_points)
            ta = curve.param(pa)
            tb = curve.param(pb)
            sweep = ((tb - ta) * d) % TWO_PI
            if pa == pb or sweep <= 1e-12:
                sweep = TWO_PI
            return _arc(curve, ta, ta + d * sweep, chord, angle, self.opts.max_edge_points)
        if isinstance(curve, Polyline):
            return self._chart(curve, pa, pb, ring=pa is None, direction=curve.sense)
        if isinstance(curve, (BCurve, SPCurve)):
            d = curve.sense
            lo, hi = curve.lo, curve.hi
            if pa is None:
                if curve.period is None:
                    raise FaceFailed("bad_geometry", "a ring edge on an open curve")
                return self._adaptive(curve, lo if d > 0 else hi, hi if d > 0 else lo, chord)
            ta = curve.param(pa, self.clock)
            tb = curve.param(pb, self.clock)
            if curve.period is not None:
                if d > 0 and (tb <= ta or pa == pb):
                    tb += curve.period
                elif d < 0 and (tb >= ta or pa == pb):
                    tb -= curve.period
            return self._adaptive(curve, ta, tb, chord)
        raise FaceFailed("unsupported_curve", curve.name)

    def _adaptive(self, curve: Curve, t0: float, t1: float, chord: float | None = None):
        """Points and parameters from ``t0`` to ``t1``: at least two a knot span, then
        halving any segment whose midpoint lies farther than ``chord`` (None: the chord
        tolerance) from it or turns more than the angle, to a depth of :data:`MAX_DEPTH`.

        A point a halving puts within :data:`MERGE` of the chord tolerance, or within
        :data:`POINT` (but no more than half the tolerance), of the sample kept before it,
        or of the first sample after it, is left out, and a segment that short is not
        halved for its turn alone; the first samples are all kept. Where a curve stops dead
        and turns (a knot of speed nought) the turn stays whatever the segment's length,
        and halving to the depth bound piled up samples a billionth of a millimetre apart;
        stopping that halving at 2% of the chord tolerance still left points a
        ten-thousandth of a millimetre apart. Points that close cannot be told apart in a
        face's (u, v), more so when the edge lies a few micrometres off the face's
        surface, and its boundary then crossed or touched itself; they add nothing the
        chord tolerance asks for, and the polyline keeps within the tolerance and that
        distance of the curve. A sampler whose options say ``corners=False`` (the STEP
        writer's, whose checks want the curve as it is) keeps every sample and halves to
        the depth bound as it always did. The distance points are left out within is the
        chord tolerance's, whatever ``chord``."""
        angle = self.opts.angle
        near = 0.0
        if getattr(self.opts, "corners", True):
            near = min(max(MERGE * self.opts.chord, POINT), 0.5 * self.opts.chord)
        chord = self.opts.chord if chord is None else chord
        limit = self.opts.max_edge_points
        spans = curve.spans(t0, t1) if hasattr(curve, "spans") else 4
        n0 = max(4, min(2 * spans, limit))
        ts = [t0 + (t1 - t0) * i / n0 for i in range(n0 + 1)]
        ps = [curve.point(t) for t in ts]
        out_t, out_p = [ts[0]], [ps[0]]
        halved = [False]  # whether each sample kept was put in by a halving
        clock = self.clock
        for i in range(n0):
            stack = [(ts[i + 1], ps[i + 1], 0)]
            ta, pa = ts[i], ps[i]
            while stack:
                clock.tick()
                tb, pb, depth = stack[-1]
                tm = 0.5 * (ta + tb)
                pm = curve.point(tm)
                mid = ((pa[0] + pb[0]) * 0.5, (pa[1] + pb[1]) * 0.5, (pa[2] + pb[2]) * 0.5)
                dev = dist(pm, mid)
                half = 0.5 * dist(pa, pb)
                bend = 2.0 * atan2(dev, half) if half > 0.0 else (math.pi if dev > 0.0 else 0.0)
                if depth < MAX_DEPTH and (dev > chord or (bend > angle and 2.0 * half > near)):
                    stack.append((tm, pm, depth + 1))
                    continue
                stack.pop()
                ta, pa = tb, pb
                # Only a point a halving put in is left out: the first samples keep the
                # curve's course (round a periodic surface, a small arc's few samples are
                # what says which way it winds, and with them gone faces came out with no
                # area or the wrong winding).
                if near and dist(pb, out_p[-1]) <= near:
                    if stack:
                        continue
                    while halved[-1] and dist(pb, out_p[-1]) <= near:
                        del out_p[-1], out_t[-1], halved[-1]  # a first sample stays instead
                out_t.append(tb)
                out_p.append(pb)
                halved.append(bool(stack))
                if len(out_p) > limit:
                    raise FaceFailed("edge_too_long", f"more than {limit} points on one edge")
        for p in out_p:
            if not (math.isfinite(p[0]) and math.isfinite(p[1]) and math.isfinite(p[2])):
                raise FaceFailed("non_finite", "a curve point is not finite")
        return out_p, out_t

    def _chart(self, curve: Polyline, pa, pb, *, ring: bool, direction: int):
        """The chart points from ``pa`` to ``pb``: the interior points between their
        positions on the polyline, in the curve's direction (``direction`` 0: whichever
        way is shorter on an open chart)."""
        pts = curve.pts
        n = len(pts) - 1
        if ring:
            if not curve.closed:
                raise FaceFailed("bad_geometry", "a ring edge on an open intersection curve")
            seq = list(pts[:-1]) + [pts[0]]
            if direction < 0:
                seq.reverse()
            return seq, [float(i) for i in range(len(seq))]
        sa = curve.param(pa, self.clock)
        sb = curve.param(pb, self.clock)
        if pa == pb and curve.closed:  # a closed edge with one vertex: all the way round
            sb = sa
        if direction == 0:
            direction = 1 if sb >= sa else -1
        whole = pa == pb and curve.closed
        if direction > 0 and sb >= sa and not whole:
            inner = [k for k in range(math.floor(sa) + 1, math.ceil(sb)) if sa < k < sb]
        elif direction < 0 and sb <= sa and not whole:
            inner = [k for k in range(math.ceil(sa) - 1, math.floor(sb), -1) if sb < k < sa]
        elif not curve.closed:  # the curve's direction disagrees with the vertices: follow them
            lo, hi = min(sa, sb), max(sa, sb)
            inner = [k for k in range(math.floor(lo) + 1, math.ceil(hi)) if lo < k < hi]
            if sb < sa:
                inner.reverse()
        elif direction > 0:  # forward across the closing point (pts[n] is pts[0])
            inner = [k for k in range(math.floor(sa) + 1, n + 1) if k > sa]
            inner += [k for k in range(1, math.ceil(sb)) if k < sb]
        else:  # backward across it
            inner = [k for k in range(math.ceil(sa) - 1, -1, -1) if k < sa]
            inner += [k for k in range(n - 1, math.floor(sb), -1) if k > sb]
        seq = [pa] + [pts[k] for k in inner] + [pb]
        return seq, [sa] + [float(k) for k in inner] + [sb]


def _arc(c: Conic, t0: float, t1: float, chord: float, angle: float, limit: int):
    step = step_angle(c.radius(), chord, angle)
    n = max(1, math.ceil(abs(t1 - t0) / step - 1e-9))
    if n > limit:
        raise FaceFailed("edge_too_long", f"{n} points on one arc")
    ts = [t0 + (t1 - t0) * i / n for i in range(n + 1)]
    return [c.point(t) for t in ts], ts


def _is_line(curve: Curve) -> bool:
    return isinstance(curve, Line) or (isinstance(curve, Trimmed) and isinstance(curve.basis, Line))


def _is_chart(curve: Curve) -> bool:
    return isinstance(curve, Polyline) or (isinstance(curve, Trimmed) and isinstance(curve.basis, Polyline))


def _blend_bend(topo: Topology, node) -> float:
    """A rolling blend's curvature across its spine: one over its sphere's radius, the
    larger of its ``range`` (``.blend``), or nought when that cannot be read."""
    rng = topo.get(node, "range", None)
    if not isinstance(rng, list) or not rng:
        return 0.0
    try:
        r = max(abs(float(x)) for x in rng)
    except (TypeError, ValueError):
        return 0.0
    return 1.0 / r if r > 0.0 and math.isfinite(r) else 0.0


def _sp_curve(curve: Curve) -> SPCurve | None:
    if isinstance(curve, SPCurve):
        return curve
    if isinstance(curve, Trimmed) and isinstance(curve.basis, SPCurve):
        return curve.basis
    return None


def _on_blend(topo: Topology, node) -> bool:
    """Whether a fin's curve is an SP-curve (trimmed or not) in a rolling blend."""
    try:
        if node.type == TRIMMED_CURVE:
            node = topo.ref(node, "basis_curve", CURVE_TYPES) or node
        if node.type != SP_CURVE:
            return False
        s = topo.ref(node, "surface")
    except FaceFailed:
        return False
    return s is not None and s.type in (BLENDED_EDGE, BLEND_BOUND)


def _same(a, b) -> bool:
    return dist(a, b) <= 1e-9 * (1.0 + abs(a[0]) + abs(a[1]) + abs(a[2]))
