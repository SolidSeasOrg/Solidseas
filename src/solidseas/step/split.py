"""Faces that go all the way round a closed surface, cut in two at their seams.

Parasolid lets a face go round a closed surface (a hole's cylinder, a ring of fillet
on a torus, a cap of a sphere or a cone) with no edge where the surface's parameter
wraps: its loops wind round the surface instead (``docs/FORMAT.md`` 10.8). STEP
allows that too, but a reader that builds each face in its surface's (u, v), as
OCCT does, then has to add a seam edge of its own and compute pcurves across it,
and gets some of those faces wrong. SOLIDWORKS writes such a face as two, cut along
the surface's iso-parameter curves at u = 0 and at half a period
(``docs/FORMAT.md`` 10.9), and so does this module:

* **Which faces.** A face whose surface as written is closed in a direction (a
  cylinder, cone, sphere, ring torus, surface of revolution, an extrusion of a
  closed curve, a B-spline surface whose first and last rows of control points
  coincide), and whose loops, followed round in that surface's (u, v), wind round
  it: a band between two loops winding opposite ways, or a cap between one winding
  loop and a pole of the surface (a sphere's, a cone's apex, a profile's end on its
  axis). Anything else is written whole, as before. So is a cap whose loop passes
  within a micrometre of its pole, or within 15 % of the farthest it reaches from
  it: the pole would be a vertex of both halves that close to their other edges,
  with a seam there that short, and OCCT read the halves of such caps with no
  area, open meshes or edges it had to correct.
* **Where.** At the iso-parameter lines u = 0 and u = half a period of the winding
  direction (the start of the parameter range of a B-spline), or, when either
  would pass through a hole, cross a loop more than once, come within a
  micrometre of a vertex without meeting it, or make a seam shorter than a
  micrometre, at the first other pair of 16 evenly spaced values that does not,
  and failing those in the gaps the holes leave. A face no pair can cut (a band
  whose edge winds back and forth across every line, holes all round) is written
  whole.
* **How.** Each winding loop's edges are cut where the seams cross them (a ring
  edge's vertex, which Parasolid does not have and the export placed, goes), every
  face using a cut edge takes its pieces, and each seam is the surface's own
  iso-parameter curve between its two ends (a LINE on a cylinder, cone or
  extrusion, a CIRCLE on a sphere or torus, the profile turned into place on a
  surface of revolution, the B-spline iso-curve on a B-spline surface), so it lies
  on the surface exactly. Each half has one outer bound; holes go with the half
  they lie in.

Every cut is checked again by the export's own checks (:mod:`.checks`: loops close,
shells close, vertices on their curves and surfaces, points along every new edge
on its faces), and the halves, followed round the surface's (u, v) as written, must
each enclose an area on the face's side of its boundary and hold the holes given
them; a face whose cut fails any of these is written whole instead.
"""

import math

from ..tessellate import nurbs
from ..tessellate._vec import TWO_PI, add, cross, dist, dot, mul, norm, sub, wrap_near
from ..tessellate.topology import FaceFailed
from . import bspline
from . import entities as E
from . import part21 as p21
from .checks import _check_edge, _check_edge_on_faces, _check_face, _check_shell, _Stats
from .mapper import FACTS, Refused

AT_VERTEX_M = 1e-9  # a seam this close to a vertex meets it
MIN_PIECE_M = 1e-6  # and otherwise keeps at least this far from every vertex; no seam is shorter
POLE_M = 1e-9  # a point this close to a pole is at it
# A cap is cut only when its loop keeps at least MIN_PIECE_M, and this share of the farthest it
# reaches, from its pole. Measured with OCCT 7.9.3 on synthetic tilted sphere caps cut whatever
# their rims' distance from the pole: it read halves with edges it had to correct, open meshes
# or faces of no area where a rim came within 7 % of its reach from the pole, none from 8.4 %
# on, and none either where the rim passed close to the sphere's other pole, outside the cap.
POLE_CLEARANCE = 0.15
NO_AREA = 1e-9  # a half enclosing at most this share of the face's (u, v) area encloses none
FOOT_M = 1e-7  # a foot on the surface this close is taken without searching further
CANDIDATES = 16  # evenly spaced values tried for a seam, 0 first
MAX_EDGE_SAMPLES = 256
MAX_DEPTH = 8  # halvings of a step that turns too far round a closed direction


class _Undo(Exception):
    """A cut that cannot be made: the face is written whole."""


# --------------------------------------------------------------------------- the surface
class _Chart:
    """A written surface's (u, v), as SolidSeas' evaluator of it has them: the periods,
    the poles (lines v = const), and whether the evaluator's u and v are STEP's the
    other way round (``swapped``, a B-spline surface presented transposed, whose
    natural normal is then the reverse of STEP's)."""

    def __init__(self, item, ev, pu, pv, swapped: bool) -> None:
        self.item, self.ev, self.swapped = item, ev, swapped
        self.periods = (pu, pv)
        self.poles = tuple(getattr(ev, "poles", ()))
        self.flip = -1 if swapped else 1

    def uv(self, p, hint):
        """``(u, v, distance)``; u None at a pole."""
        return self.ev.closest(p, hint, FOOT_M, POLE_M, None)


def _closed_curve_period(curve):
    """The period of a written curve that closes: 2 pi for a circle or an ellipse, the
    parameter range of a B-spline whose ends meet; else None."""
    if isinstance(curve, (E.Circle, E.Ellipse)):
        return TWO_PI
    if isinstance(curve, E.BSplineCurve) and curve.is_closed:
        return curve.knots[-1] - curve.knots[0]
    return None


def chart_of(item):
    """The :class:`_Chart` of a written surface whose faces may need cutting, or None."""
    if isinstance(item, (E.Cylinder, E.Cone, E.Sphere)):
        return _Chart(item, item.evaluator(), TWO_PI, None, False)
    if isinstance(item, E.Torus):
        if item.select_outer is not None:
            return None  # an apple or a lemon, whose poles meet the axis: left whole
        return _Chart(item, item.evaluator(), TWO_PI, TWO_PI, False)
    if isinstance(item, E.Revolution):
        return _Chart(item, item.evaluator(), TWO_PI, _closed_curve_period(item.curve), False)
    if isinstance(item, E.Extrusion):
        pu = _closed_curve_period(item.curve)
        if pu is None:
            return None
        return _Chart(item, item.evaluator(), pu, None, False)
    if isinstance(item, E.BSplineSurface):
        ev = item.evaluator()
        if ev.pu is None and ev.pv is None:
            return None
        return _Chart(item, ev, ev.pu, ev.pv, bool(getattr(ev, "swapped", False)))
    return None


# --------------------------------------------------------------------------- loops in (u, v)
class _Sample:
    __slots__ = ("k", "t", "u", "v")

    def __init__(self, k, t, u, v) -> None:
        self.k, self.t, self.u, self.v = k, t, u, v


def edge_span(e: E.Edge):
    """``(evaluator, ts, te, period)``: the written curve's parameters from the edge's
    start to its end, the way it runs (``te`` past ``ts`` by up to a period on a closed
    curve, a whole one for a ring)."""
    ev = e.curve.evaluator()
    sign = 1.0 if e.same_sense else -1.0
    period = TWO_PI if e.curve.closed else getattr(ev, "period", None)
    ts = ev.param(e.start.metres())
    if e.start is e.end:
        if period:
            return ev, ts, ts + sign * period, period
        lo, hi = ev.lo, ev.hi
        if lo is None or hi is None:
            raise _Undo("a ring on an unbounded curve")
        return (ev, lo, hi, None) if sign > 0 else (ev, hi, lo, None)
    te = ev.param(e.end.metres())
    if period:
        step = ((te - ts) * sign) % period
        if step <= 1e-12 * period:
            step = period
        te = ts + sign * step
    return ev, ts, te, period


def _count(e: E.Edge, ts: float, te: float) -> int:
    c = e.curve
    if isinstance(c, E.Line):
        return 4
    if isinstance(c, (E.Circle, E.Ellipse)):
        return max(4, min(MAX_EDGE_SAMPLES, math.ceil(abs(te - ts) / (math.pi / 16))))
    if isinstance(c, E.BSplineCurve):
        lo, hi = min(ts, te), max(ts, te)
        spans = sum(1 for a, b in zip(c.knots, c.knots[1:], strict=False) if b > lo and a < hi)
        return max(8, min(MAX_EDGE_SAMPLES, 8 * max(1, spans)))
    return 16


class _Loop:
    """One loop of a face followed round in the chart: points along each oriented edge
    (each edge's own, from its start to its end the way the loop runs), unwrapped so
    that each step is less than half a period, and the loop's windings. With ``unwrap``
    False the points are left as the chart gives them (see :func:`_outline`)."""

    def __init__(self, chart: _Chart, loop: E.EdgeLoop, clock, unwrap: bool = True) -> None:
        self.chart, self.loop = chart, loop
        self.spans = []
        self.samples: list[_Sample] = []
        self.pole = False
        hint = None
        for k, (e, o) in enumerate(loop.edges):
            clock.tick()
            ev, ts, te, _period = edge_span(e)
            if not o:
                ts, te = te, ts
            self.spans.append(ev)
            n = _count(e, ts, te)
            pts = []
            for i in range(n + 1):
                t = ts + (te - ts) * i / n
                u, v, _d = chart.uv(ev.point(t), hint)
                if u is not None:
                    hint = (u, v)
                pts.append(_Sample(k, t, u, v))
            self.samples.extend(self._refined(ev, pts, clock, 0))
        if unwrap:
            self._unwrap()

    def _refined(self, ev, pts, clock, depth: int):
        """Halve the steps that turn more than an eighth of a period round a closed
        direction, so that unwrapping cannot take a step the wrong way round."""
        pu, pv = self.chart.periods
        out = [pts[0]]
        for b in pts[1:]:
            a = out[-1]
            if depth < MAX_DEPTH and a.u is not None and b.u is not None:
                big = (pu is not None and abs(wrap_near(b.u, a.u, pu) - a.u) > pu / 8) or (
                    pv is not None and abs(wrap_near(b.v, a.v, pv) - a.v) > pv / 8
                )
                if big:
                    clock.tick()
                    tm = 0.5 * (a.t + b.t)
                    u, v, _d = self.chart.uv(ev.point(tm), (a.u, a.v))
                    out.extend(self._refined(ev, [a, _Sample(a.k, tm, u, v), b], clock, depth + 1)[1:])
                    continue
            out.append(b)
        return out

    def _unwrap(self) -> None:
        pu, pv = self.chart.periods
        last = None
        after_pole = False
        for s in self.samples:
            if s.u is None:
                self.pole = after_pole = True
                continue
            if last is not None:
                if pu is not None:
                    u = wrap_near(s.u, last.u, pu)
                    if after_pole and abs(u - last.u) > 0.4 * pu:
                        raise _Undo("a loop passes a pole half a turn round")
                    s.u = u
                if pv is not None:
                    s.v = wrap_near(s.v, last.v, pv)
            last = s
            after_pole = False
        known = [s for s in self.samples if s.u is not None]
        if len(known) < 2:
            raise _Undo("a loop with too few points off the poles")
        first, end = known[0], known[-1]
        self.wind = []
        for d, period in enumerate((pu, pv)):
            delta = (end.u - first.u) if d == 0 else (end.v - first.v)
            if period is None:
                self.wind.append(0)
                continue
            w = round(delta / period)
            if abs(delta - w * period) > 1e-6 * period:
                raise _Undo("a loop does not close in the chart")
            self.wind.append(w)
        # A vertex is one point: each edge starts exactly where the one before ended, and
        # the loop ends where it started, a whole number of periods on, so that a seam
        # through a vertex crosses the loop once, not once at each side of it.
        for a, b in zip(self.samples, self.samples[1:], strict=False):
            if a.k != b.k and a.u is not None and b.u is not None:
                b.u, b.v = a.u, a.v
        if self.samples[0].u is not None and self.samples[-1].u is not None:
            self.samples[-1].u = self.samples[0].u + self.wind[0] * (pu or 0.0)
            self.samples[-1].v = self.samples[0].v + self.wind[1] * (pv or 0.0)

    def coords(self, d: int):
        return [None if s.u is None else (s.u if d == 0 else s.v) for s in self.samples]

    def interval(self, d: int):
        xs = [x for x in self.coords(d) if x is not None]
        return min(xs), max(xs)

    def crossings(self, d: int, s: float, period: float):
        """``[(sample index, target)]``: where the loop crosses the line at ``s`` (or a
        whole number of periods from it) in direction ``d``, each crossing once."""

        def turns(x):
            # whole periods from s, a point within rounding of a line taken as on it
            q = (x - s) / period
            r = round(q)
            return math.floor(r if abs(q - r) <= 1e-12 else q)

        xs = self.coords(d)
        out = []
        for i in range(len(xs) - 1):
            a, b = xs[i], xs[i + 1]
            if a is None or b is None or self.samples[i].k != self.samples[i + 1].k:
                continue
            na, nb = turns(a), turns(b)
            for m in range(min(na, nb) + 1, max(na, nb) + 1):
                out.append((i, s + m * period))
        return out


# --------------------------------------------------------------------------- planning one cut
class _Crossing:
    __slots__ = ("edge", "t", "p", "w", "vertex")

    def __init__(self, edge, t, p, w) -> None:
        self.edge, self.t, self.p, self.w = edge, t, p, w
        self.vertex = None


def _refine(L: _Loop, i: int, d: int, target: float, clock) -> _Crossing:
    """The point of the loop's edge between samples ``i`` and ``i + 1`` where the chart's
    coordinate ``d`` is ``target``, by bisection along the edge's curve."""
    a, b = L.samples[i], L.samples[i + 1]
    e = L.loop.edges[a.k][0]
    ev = L.spans[a.k]
    period = L.chart.periods[d]
    xa = a.u if d == 0 else a.v
    xb = b.u if d == 0 else b.v
    ta, tb = a.t, b.t
    hint = (a.u, a.v)
    lo, hi = ta, tb
    for _ in range(64):
        clock.tick()
        tm = 0.5 * (lo + hi)
        u, v, _dd = L.chart.uv(ev.point(tm), hint)
        if u is None:
            raise _Undo("a seam meets a loop at a pole")
        hint = (u, v)
        x = u if d == 0 else v
        est = xa + (xb - xa) * ((tm - ta) / (tb - ta) if tb != ta else 0.5)
        x = wrap_near(x, est, period)
        if (x - target) * (xb - xa) < 0.0:
            lo = tm
        else:
            hi = tm
        if lo == hi:
            break
    t = 0.5 * (lo + hi)
    p = ev.point(t)
    u, v, _dd = L.chart.uv(p, hint)
    if u is None:
        raise _Undo("a seam meets a loop at a pole")
    return _Crossing(e, t, p, v if d == 0 else u)


def _near_vertex(c: _Crossing):
    """The vertex of its edge a crossing meets, or None; raises :class:`_Undo` when it
    comes within :data:`MIN_PIECE_M` of one without meeting it."""
    e = c.edge
    if e.start is e.end:
        return None  # a ring's vertex is the export's own: it moves to the cuts
    for v in (e.start, e.end):
        dd = dist(v.metres(), c.p)
        if dd <= AT_VERTEX_M:
            return v
        if dd <= MIN_PIECE_M:
            raise _Undo("a seam passes within a micrometre of a vertex")
    return None


class _Plan:
    """Where one face is cut: ``kind`` (band or cap), the chart direction ``d`` the
    loops wind in, the two seam values, the bounds of the winding loops and their
    crossings at each seam, the pole of a cap, the side of the first loop the face
    lies on along the other direction, and whether that loop runs up ``d``."""

    def __init__(self, kind, d, values, a, b, cross_a, cross_b, pole, side, up) -> None:
        self.kind, self.d, self.values = kind, d, values
        self.a, self.b = a, b
        self.cross_a, self.cross_b = cross_a, cross_b
        self.pole, self.side, self.up = pole, side, up


def _candidates(chart: _Chart, d: int):
    """Pairs of seam values to try, (0, half a period) first."""
    period = chart.periods[d]
    base = 0.0
    item = chart.item
    if isinstance(item, E.BSplineSurface):
        s = chart.ev.s
        base = s.ulo if d == 0 else s.vlo
    elif isinstance(item, E.Extrusion) and isinstance(item.curve, E.BSplineCurve):
        base = item.curve.knots[0]
    elif isinstance(item, E.Revolution) and d == 1 and isinstance(item.curve, E.BSplineCurve):
        base = item.curve.knots[0]
    vals = [base + period * k / CANDIDATES for k in range(CANDIDATES)]
    half = CANDIDATES // 2
    pairs = [(vals[k], vals[k + half]) for k in (0, 4, 2, 6, 1, 3, 5, 7)]
    for gap in (6, 4, 2, 1):
        for k in range(CANDIDATES):
            pairs.append((vals[k], vals[(k + gap) % CANDIDATES]))
    return pairs


def _gap_pairs(period: float, holes):
    """Pairs of seam values in the gaps the holes leave round the period: the middles of
    the two widest gaps, and two values inside the widest one."""
    if not holes:
        return []
    arcs = sorted(((lo % period), (lo % period) + (hi - lo)) for lo, hi in holes)
    merged: list[list[float]] = []
    for a, b in arcs:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    if merged[-1][1] - merged[0][0] >= period:  # the holes go all the way round
        return []
    gaps = []
    for k, (_a, b) in enumerate(merged):
        nxt = merged[k + 1][0] if k + 1 < len(merged) else merged[0][0] + period
        if nxt > b:
            gaps.append((nxt - b, b))
    gaps.sort(reverse=True)
    out = []
    (w1, a1) = gaps[0]
    if len(gaps) > 1:
        w2, a2 = gaps[1]
        out.append((a1 + 0.5 * w1, a2 + 0.5 * w2))
    out.append((a1 + w1 / 3.0, a1 + 2.0 * w1 / 3.0))
    return out


def _reach(L: _Loop, point, clock):
    """``(near, far)``: how close a loop comes to ``point`` and how far it goes from it
    (metres), over its points, the nearest then found along its edge's curve between
    the points either side of it (golden section)."""
    ds = [dist(L.spans[s.k].point(s.t), point) for s in L.samples]
    i = min(range(len(ds)), key=ds.__getitem__)
    near, far = ds[i], max(ds)
    s = L.samples[i]
    ev = L.spans[s.k]
    lo = L.samples[i - 1].t if i > 0 and L.samples[i - 1].k == s.k else s.t
    hi = L.samples[i + 1].t if i + 1 < len(ds) and L.samples[i + 1].k == s.k else s.t
    g = 0.5 * (math.sqrt(5.0) - 1.0)
    a, b = lo, hi
    for _ in range(80):
        clock.tick()
        if a == b:
            break
        c, d = b - g * (b - a), a + g * (b - a)
        dc, dd = dist(ev.point(c), point), dist(ev.point(d), point)
        near = min(near, dc, dd)
        if dc < dd:
            b = d
        else:
            a = c
    return near, far


def _blocked(s: float, period: float, holes) -> bool:
    margin = 1e-6 * period
    for lo, hi in holes:
        m = math.ceil((lo - margin - s) / period)
        if s + m * period <= hi + margin:
            return True
    return False


def plan_face(face: E.Face, chart: _Chart, clock):
    """The :class:`_Plan` of a face's cut, None when it needs none; raises
    :class:`_Undo` when it needs one that cannot be made."""
    loops = [(i, lp) for i, (lp, _o) in enumerate(face.bounds) if isinstance(lp, E.EdgeLoop)]
    if not loops:
        return None
    o = (1 if face.same_sense else -1) * chart.flip
    info = [(i, _Loop(chart, lp, clock)) for i, lp in loops]
    wrapping = [(i, L) for i, L in info if L.wind != [0, 0]]
    if not wrapping:
        return None
    if any(L.pole for _i, L in wrapping):
        raise _Undo("a winding loop passes a pole")
    plain = [L for _i, L in info if L.wind == [0, 0]]
    if len(wrapping) == 2:
        (ia, A), (ib, B) = wrapping
        wa, wb = A.wind, B.wind
        if wa != [-wb[0], -wb[1]] or (wa[0] == 0) == (wa[1] == 0) or abs(wa[0] + wa[1]) != 1:
            raise _Undo(f"loops winding {wa} and {wb}")
        d = 0 if wa[0] != 0 else 1
        kind = "band"
    elif len(wrapping) == 1:
        (ia, A), ib, B = wrapping[0], None, None
        if A.wind[1] != 0 or abs(A.wind[0]) != 1:
            raise _Undo(f"one loop winding {A.wind}")
        d, kind = 0, "cap"
    else:
        raise _Undo(f"{len(wrapping)} winding loops")
    period = chart.periods[d]
    up = A.wind[d] > 0
    # The face lies to the left of its loops in (u, v) when its normal is the natural
    # one, to the right otherwise: along the other direction, on this side of A.
    side = (1 if up else -1) * o * (1 if d == 0 else -1)
    pole = None
    if kind == "cap":
        lo, hi = A.interval(1)
        if side > 0:
            ps = [q for q in chart.poles if q[0] >= hi - 1e-12]
            pole = min(ps, key=lambda q: q[0]) if ps else None
        else:
            ps = [q for q in chart.poles if q[0] <= lo + 1e-12]
            pole = max(ps, key=lambda q: q[0]) if ps else None
        if pole is None:
            raise _Undo("one loop winds round and there is no pole on the face's side")
        # The pole is a vertex of both halves and a seam runs to it from each crossing:
        # a loop that passes close to it would leave the pole that close to the halves'
        # other edges, a seam that short there and a sliver of a half between them, and
        # a reader's own curves in (u, v) for the halves go astray there.
        near, far = _reach(A, pole[1], clock)
        if near < max(MIN_PIECE_M, POLE_CLEARANCE * far):
            FACTS[f"seam_near_pole:{face.surface.kind}"] += 1
            raise _Undo("a cap's loop passes too near its pole")
    holes = []
    for L in plain:
        if L.pole:
            raise _Undo("a hole touches a pole")
        holes.append(L.interval(d))
    winding = (A,) if B is None else (A, B)
    for s1, s2 in _candidates(chart, d) + _gap_pairs(period, holes):
        clock.tick()
        if _blocked(s1, period, holes) or _blocked(s2, period, holes):
            continue
        try:
            got = []
            for L in winding:
                per = []
                for s in (s1, s2):
                    xs = L.crossings(d, s, period)
                    if len(xs) != 1:
                        raise _Undo("a seam crosses a loop more than once")
                    c = _refine(L, xs[0][0], d, xs[0][1], clock)
                    c.vertex = _near_vertex(c)
                    per.append(c)
                got.append(per)
            if B is None:
                ends = [(c.p, pole[1]) for c in got[0]]
            else:
                ends = [(a.p, b.p) for a, b in zip(got[0], got[1], strict=True)]
            if any(dist(p, q) < MIN_PIECE_M for p, q in ends):
                raise _Undo("a seam shorter than a micrometre")
        except _Undo:
            continue
        return _Plan(kind, d, (s1, s2), ia, ib, got[0], got[1] if B is not None else None, pole, side, up)
    raise _Undo("no pair of seams keeps clear of the holes and the vertices")


# --------------------------------------------------------------------------- seams on the surface
def _line(point_m, direction) -> E.Line:
    return E.Line(E.point_mm(point_m), E.direction(direction), p21.mm(1.0))


def _circle(centre_m, axis, x, radius_m) -> E.Circle:
    if not radius_m > 1e-12:
        raise _Undo("a seam circle of no radius")
    return E.Circle(E.Placement.make(centre_m, axis, x), p21.mm(radius_m))


def _turn(q, axis, c, s):
    return add(add(mul(q, c), mul(cross(axis, q), s)), mul(axis, dot(axis, q) * (1.0 - c)))


def _turned(curve, base, axis, ang: float):
    """A written curve turned by ``ang`` about the line (``base``, ``axis``), exactly."""
    c, s = math.cos(ang), math.sin(ang)

    def place(p):
        return add(base, _turn(sub(p, base), axis, c, s))

    if isinstance(curve, E.Line):
        point = E.point_mm(place(E.metres(curve.point)))
        return E.Line(point, E.direction(_turn(curve.direction, axis, c, s)), curve.magnitude)
    if isinstance(curve, (E.Circle, E.Ellipse)):
        o, z, x = curve.placement.frame()
        pl = E.Placement.make(place(o), _turn(z, axis, c, s), _turn(x, axis, c, s))
        if isinstance(curve, E.Circle):
            return E.Circle(pl, curve.radius)
        return E.Ellipse(pl, curve.semi1, curve.semi2)
    if isinstance(curve, E.BSplineCurve):
        spline = curve.spline()
        cps = []
        for h in spline.cps:
            w = h[3] if spline.rational else 1.0
            q = place((h[0] / w, h[1] / w, h[2] / w))
            cps.append((q[0] * w, q[1] * w, q[2] * w, w) if spline.rational else q)
        return E.BSplineCurve(nurbs.BSplineCurve(spline.p, cps, list(spline.U), spline.rational, False))
    raise _Undo(f"a profile of kind {curve.kind}")


def _radial_frame(z, x):
    """The unit x made perpendicular to z, and y = z x x."""
    xx = sub(x, mul(z, dot(x, z)))
    n = norm(xx)
    xx = (xx[0] / n, xx[1] / n, xx[2] / n)
    return xx, cross(z, xx)


def iso_item(chart: _Chart, d: int, s: float):
    """The written surface's curve at the chart's coordinate ``d`` fixed at ``s``, its
    parameter running up the other coordinate: an item."""
    item = chart.item
    if isinstance(item, (E.Cylinder, E.Cone, E.Sphere, E.Torus)):
        c, z, x0 = item.placement.frame()
        x, y = _radial_frame(z, x0)
        if isinstance(item, E.Torus) and d == 1:
            R, r = item.major / p21.SCALE, item.minor / p21.SCALE
            return _circle(add(c, mul(z, r * math.sin(s))), z, x, R + r * math.cos(s))
        if d != 0:
            raise _Undo("a cut across a surface open that way")
        e = add(mul(x, math.cos(s)), mul(y, math.sin(s)))
        if isinstance(item, E.Cylinder):
            return _line(add(c, mul(e, item.radius / p21.SCALE)), z)
        if isinstance(item, E.Cone):
            return _line(add(c, mul(e, item.radius / p21.SCALE)), add(z, mul(e, math.tan(item.angle))))
        if isinstance(item, E.Sphere):
            return _circle(c, cross(e, z), e, item.radius / p21.SCALE)
        return _circle(add(c, mul(e, item.major / p21.SCALE)), cross(e, z), e, item.minor / p21.SCALE)
    if isinstance(item, E.Revolution):
        base, axis = E.metres(item.location), item.axis
        if d == 0:
            return _turned(item.curve, base, axis, s)
        q = item.curve.evaluator().point(s)
        h = dot(sub(q, base), axis)
        radial = sub(sub(q, base), mul(axis, h))
        return _circle(add(base, mul(axis, h)), axis, radial, norm(radial))
    if isinstance(item, E.Extrusion):
        if d != 0:
            raise _Undo("a cut along an extrusion")
        return _line(item.curve.evaluator().point(s), item.direction)
    if isinstance(item, E.BSplineSurface):
        step_d = (1 - d) if chart.swapped else d
        return E.BSplineCurve(bspline.iso_curve(item.spline(), "u" if step_d == 0 else "v", s))
    raise _Undo(f"no seam curve on a {item.kind}")


def _off(ev, p) -> float:
    return dist(ev.point(ev.param(p)), p)


def _seam(chart: _Chart, d: int, s: float, va: E.Vertex, wa: float, vb: E.Vertex, wb: float) -> E.Edge:
    """The seam at ``s`` from ``va`` (the other coordinate ``wa``) to ``vb`` (``wb``)."""
    item = iso_item(chart, d, s)
    ev = item.evaluator()
    if isinstance(item, E.BSplineCurve):
        lo, hi = ev.lo, ev.hi
        slack = 1e-9 * (hi - lo)
        if not (lo - slack <= min(wa, wb) and max(wa, wb) <= hi + slack):
            raise _Undo("a seam that runs off its B-spline's range")
    tol = max(va.tolerance, vb.tolerance, _off(ev, va.metres()), _off(ev, vb.metres()))
    return E.Edge(va, vb, item, wb > wa, tol, 0.0, -1)


# --------------------------------------------------------------------------- the body
class Splitter:
    """Cuts the faces of one mapped body (:class:`.mapper.Mapped`) face by face, each
    cut checked, and undone when its checks fail."""

    def __init__(self, mapper, mapped) -> None:
        self.mapper, self.m = mapper, mapped
        self.clock = mapper.clock
        self.loops_of: dict[int, list] = {}  # id(edge) -> the loops that use it
        self.face_of: dict[int, E.Face] = {}  # id(loop) -> its face
        self.shells_of: dict[int, list] = {}  # id(face) -> the shells that hold it
        for item in mapped.items:
            for shell in item.shells:
                for f in shell.faces:
                    self.shells_of.setdefault(id(f), []).append(shell)
        for f in mapped.faces:
            self._index(f)
        self.removed_edges: set[int] = set()
        self.added_edges: list[E.Edge] = []
        self.removed_vertices: set[int] = set()
        self.added_vertices: list[E.Vertex] = []
        self.replaced: dict[int, list[E.Face]] = {}  # id(face) -> its halves
        self.pieces: dict[int, int] = {}  # id(piece) -> the EDGE node index it is part of
        self.sources = {id(e): idx for e, idx in mapped.edge_sources}
        self.halves: list[E.Face] = []  # the halves the cut being made has made so far
        self.dead: set[int] = set()  # id(half) of the halves of undone cuts

    def _index(self, f: E.Face) -> None:
        for lp, _o in f.bounds:
            if isinstance(lp, E.EdgeLoop):
                self.face_of[id(lp)] = f
                for e, _ in lp.edges:
                    got = self.loops_of.setdefault(id(e), [])
                    if lp not in got:
                        got.append(lp)

    def live(self, f: E.Face) -> bool:
        """Whether a face is in the body: not cut in two, and not a half of an undone cut."""
        return id(f) not in self.replaced and id(f) not in self.dead

    def run(self) -> None:
        for f in list(self.m.faces):
            chart = chart_of(f.surface)
            if chart is None or not any(isinstance(lp, E.EdgeLoop) for lp, _o in f.bounds):
                continue
            self.clock.tick()
            try:
                plan = plan_face(f, chart, self.clock)
            except (_Undo, FaceFailed, ValueError, ZeroDivisionError, OverflowError):
                FACTS[f"seam_face_left_whole:{f.surface.kind}"] += 1
                continue
            if plan is None:
                continue
            log: list = []
            state = self._state()
            self.halves = []
            try:
                self._cut(f, chart, plan, log)
            except (_Undo, Refused, FaceFailed, ValueError, ZeroDivisionError, OverflowError):
                for obj, attr, old in reversed(log):
                    setattr(obj, attr, old)
                self._restore(state)
                self.dead.update(id(h) for h in self.halves)
                FACTS[f"seam_cut_undone:{f.surface.kind}"] += 1
                continue
            FACTS[f"seam_face_cut:{f.surface.kind}"] += 1
        self._commit()

    # -- bookkeeping, restored when a cut is undone
    def _state(self):
        # copied before every face: tick by its size, so the time limit bounds a body with many cuts
        self.clock.tick(len(self.removed_edges) + len(self.replaced) + len(self.pieces))
        return (
            set(self.removed_edges),
            len(self.added_edges),
            set(self.removed_vertices),
            len(self.added_vertices),
            dict(self.replaced),
            dict(self.pieces),
        )

    def _restore(self, state) -> None:
        self.removed_edges, ne, self.removed_vertices, nv, self.replaced, self.pieces = state
        del self.added_edges[ne:]
        del self.added_vertices[nv:]

    def _commit(self) -> None:
        m = self.m
        if not self.replaced:
            return
        faces = []
        for f in m.faces:
            faces.extend(self.replaced.get(id(f), (f,)))
        m.faces = faces
        m.split_faces += len(self.replaced)
        added = [e for e in self.added_edges if id(e) not in self.removed_edges]
        kept = [e for e in m.edges if id(e) not in self.removed_edges]
        m.edges_added += len(kept) + len(added) - len(m.edges)
        m.edges = kept + added
        m.edge_sources = [(e, i) for e, i in m.edge_sources if id(e) not in self.removed_edges]
        m.piece_sources = [(e, self.pieces[id(e)]) for e in added if id(e) in self.pieces]
        m.vertices = [v for v in m.vertices if id(v) not in self.removed_vertices] + [
            v for v in self.added_vertices if id(v) not in self.removed_vertices
        ]

    # -- one cut
    def _cut(self, face: E.Face, chart: _Chart, plan: _Plan, log: list) -> None:
        first_new = len(self.added_edges)
        touched: list[E.Face] = []
        crossings = list(plan.cross_a) + list(plan.cross_b or ())
        self._split_edges(crossings, log, touched)
        s1, s2 = plan.values
        a1, a2 = plan.cross_a
        arc_a12, arc_a21 = _arcs(face.bounds[plan.a][0], a1.vertex, a2.vertex)
        used = {plan.a}
        if plan.kind == "band":
            b1, b2 = plan.cross_b
            arc_b12, arc_b21 = _arcs(face.bounds[plan.b][0], b1.vertex, b2.vertex)
            w1, w2 = self._far_end(chart, plan, a1.w, b1.w), self._far_end(chart, plan, a2.w, b2.w)
            seam1 = _seam(chart, plan.d, s1, a1.vertex, a1.w, b1.vertex, w1)
            seam2 = _seam(chart, plan.d, s2, a2.vertex, a2.w, b2.vertex, w2)
            half1 = arc_a12 + [(seam2, True)] + arc_b21 + [(seam1, False)]
            half2 = arc_a21 + [(seam1, True)] + arc_b12 + [(seam2, False)]
            used.add(plan.b)
        else:
            pole_v, at = self._pole_vertex(face, plan)
            if at is not None:
                used.add(at)
            vp = plan.pole[0]
            seam1 = _seam(chart, plan.d, s1, a1.vertex, a1.w, pole_v, vp)
            seam2 = _seam(chart, plan.d, s2, a2.vertex, a2.w, pole_v, vp)
            half1 = arc_a12 + [(seam2, True), (seam1, False)]
            half2 = arc_a21 + [(seam1, True), (seam2, False)]
        self.added_edges.extend((seam1, seam2))
        # Half 1 runs along A from the seam at s1 to the seam at s2: up the cut direction
        # from s1 when A runs up it, down from s1 otherwise. Holes go with the half
        # whose stretch of that direction holds them.
        period = chart.periods[plan.d]
        lo1, width = (s1, (s2 - s1) % period) if plan.up else (s2, (s1 - s2) % period)
        bounds1 = [(E.EdgeLoop(half1), True)]
        bounds2 = [(E.EdgeLoop(half2), True)]
        for i, (lp, _o) in enumerate(face.bounds):
            if i in used:
                continue
            x = _loop_coordinate(chart, lp, plan.d)
            if x is None:
                raise _Undo("a hole the cut cannot place")
            (bounds1 if (x - lo1) % period < width else bounds2).append((lp, False))
        halves = [
            E.Face(b, face.surface, face.same_sense, face.source, face.approximated, None, face.deviation)
            for b in (bounds1, bounds2)
        ]
        shells = self.shells_of.get(id(face), [])
        for shell in shells:
            log.append((shell, "faces", shell.faces))
            new = []
            for f in shell.faces:
                new.extend(halves if f is face else (f,))
            shell.faces = new
        self.replaced[id(face)] = halves
        self.halves = halves
        for h in halves:
            self._index(h)
            self.shells_of[id(h)] = list(shells)
        self._check(halves, touched, self.added_edges[first_new:], chart, face, plan.pole)

    def _far_end(self, chart: _Chart, plan: _Plan, wa: float, wb: float) -> float:
        """The other coordinate at the far end of a band's seam: B's, reached from A the
        way the face lies (round a closed direction, the way into the face)."""
        period = chart.periods[1 - plan.d]
        if period is None:
            if (wb - wa) * plan.side <= 0.0:
                raise _Undo("a band's second loop lies on the wrong side of the first")
            return wb
        step = ((wb - wa) * plan.side) % period
        if not step > 0.0:
            raise _Undo("a band of no width")
        return wa + plan.side * step

    def _pole_vertex(self, face: E.Face, plan: _Plan):
        """The cap's vertex at its pole, a VERTEX_LOOP's there or a new one, and the index
        of that loop in the face's bounds (or None)."""
        point = plan.pole[1]
        for i, (lp, _o) in enumerate(face.bounds):
            if isinstance(lp, E.VertexLoop) and dist(lp.vertex.metres(), point) <= MIN_PIECE_M:
                return lp.vertex, i
        v = E.Vertex(E.point_mm(point), 0.0, -1)
        self.added_vertices.append(v)
        return v, None

    def _split_edges(self, crossings, log: list, touched: list) -> None:
        """Give each crossing its vertex, cutting the edge it falls on, and put the
        pieces in every loop that used a cut edge."""
        by_edge: dict[int, list[_Crossing]] = {}
        for c in crossings:
            if c.vertex is None:
                by_edge.setdefault(id(c.edge), []).append(c)
        for cs in by_edge.values():
            e = cs[0].edge
            _ev, ts, te, period = edge_span(e)
            sign = 1.0 if te >= ts else -1.0
            points: list[tuple[float, E.Vertex]] = []
            for c in cs:
                same = next((v for _pos, v in points if dist(v.metres(), c.p) <= AT_VERTEX_M), None)
                if same is not None:
                    c.vertex = same
                    continue
                pos = ((c.t - ts) * sign) % period if period else (c.t - ts) * sign
                if not 0.0 <= pos <= abs(te - ts):
                    raise _Undo("a crossing off its edge")
                v = E.Vertex(E.point_mm(c.p), max(e.tolerance, 2.0 * e.deviation), -1)
                self.added_vertices.append(v)
                c.vertex = v
                points.append((pos, v))
            points.sort(key=lambda q: q[0])
            if any(b[0] - a[0] <= 0.0 for a, b in zip(points, points[1:], strict=False)):
                raise _Undo("two cuts at one point of an edge")
            span = abs(te - ts)
            if e.start is e.end:
                chain = [*points, (points[0][0] + span, points[0][1])]
                self.removed_vertices.add(id(e.start))
            else:
                chain = [(0.0, e.start), *points, (span, e.end)]
            pieces = [
                self._piece(e, ts, sign, pa, va, pb, vb)
                for (pa, va), (pb, vb) in zip(chain, chain[1:], strict=False)
            ]
            self.removed_edges.add(id(e))
            src = self.sources.get(id(e), self.pieces.get(id(e)))
            for pc in pieces:
                self.added_edges.append(pc)
                if src is not None:
                    self.pieces[id(pc)] = src
            for lp in self.loops_of.get(id(e), ()):
                if not any(x is e for x, _o in lp.edges):
                    continue
                log.append((lp, "edges", lp.edges))
                new = []
                for x, o in lp.edges:
                    if x is not e:
                        new.append((x, o))
                    elif o:
                        new.extend((pc, True) for pc in pieces)
                    else:
                        new.extend((pc, False) for pc in reversed(pieces))
                lp.edges = new
                for pc in pieces:
                    self.loops_of.setdefault(id(pc), []).append(lp)
                f = self.face_of.get(id(lp))
                if f is not None and f not in touched:
                    touched.append(f)

    @staticmethod
    def _piece(e: E.Edge, ts: float, sign: float, pa: float, va, pb: float, vb) -> E.Edge:
        """The piece of ``e`` from position ``pa`` (vertex ``va``) to ``pb`` along it. A
        piece of a line or a conic keeps the edge's curve; a piece of a B-spline gets the
        curve restricted to its own range, so that no piece runs across the end of a
        closed curve that is not periodic (a ring's, whose own vertex goes)."""
        curve, same = e.curve, e.same_sense
        if isinstance(curve, E.BSplineCurve):
            spline = curve.spline()
            if e.start is e.end:
                spline.period = spline.hi - spline.lo
            a, b = ts + sign * pa, ts + sign * pb
            curve = E.BSplineCurve(bspline.restricted(spline, min(a, b), max(a, b)))
            same = sign > 0
        return E.Edge(va, vb, curve, same, e.tolerance, e.deviation, e.source)

    def _check(self, halves, touched, new_edges, chart=None, face=None, pole=None) -> None:
        """The export's own checks of what one cut made or changed, and that the halves
        of ``face`` tile it (:func:`_check_halves`; ``pole`` a cap's)."""
        mapper = self.mapper
        if chart is not None and face is not None:
            _check_halves(chart, face, halves, self.clock, pole)
        stats = _Stats()
        faces = list(halves) + [f for f in touched if self.live(f)]
        shells = []
        for f in faces:
            for shell in self.shells_of.get(id(f), ()):
                if shell not in shells:
                    shells.append(shell)
        for shell in shells:
            _check_shell(shell, self.clock)  # the whole shell, for each cut: ticked by its faces
        for e in new_edges:
            if id(e) in self.removed_edges:
                continue
            _check_edge(mapper, e, stats)
            _ev, ts, te, period = edge_span(e)
            on = []
            for lp in self.loops_of.get(id(e), ()):
                f = self.face_of.get(id(lp))
                if f is not None and self.live(f) and f not in on and any(x is e for x, _o in lp.edges):
                    on.append(f)
            along = ([ts, te], 1.0 if e.same_sense else -1.0, period, False)
            _check_edge_on_faces(mapper, e, along, on, stats)
        for f in faces:
            _check_face(mapper, f, stats)
        self.m.max_gap = max(self.m.max_gap, stats.gap)


def _arcs(loop: E.EdgeLoop, v1: E.Vertex, v2: E.Vertex):
    """The loop's oriented edges from ``v1`` to ``v2``, and from ``v2`` back to ``v1``."""
    ends = loop.ends()
    i1 = [k for k, (s, _e) in enumerate(ends) if s is v1]
    i2 = [k for k, (s, _e) in enumerate(ends) if s is v2]
    if len(i1) != 1 or len(i2) != 1 or i1[0] == i2[0]:
        raise _Undo("a seam's end is not once on its loop")
    a, b = i1[0], i2[0]
    n = len(loop.edges)
    first = [loop.edges[(a + k) % n] for k in range((b - a) % n)]
    return first, [loop.edges[(b + k) % n] for k in range((a - b) % n)]


def _loop_point(lp):
    """A point of a loop (metres): its vertex, or the middle of its first edge."""
    if isinstance(lp, E.VertexLoop):
        return lp.vertex.metres()
    ev, ts, te, _period = edge_span(lp.edges[0][0])
    return ev.point(0.5 * (ts + te))


def _loop_coordinate(chart: _Chart, lp, d: int):
    """The chart coordinate ``d`` of a point of a loop that does not wind."""
    u, v, _d = chart.uv(_loop_point(lp), None)
    if u is None:
        return None
    return u if d == 0 else v


# --------------------------------------------------------------------------- the halves tile the face
def _outline(chart: _Chart, loop: E.EdgeLoop, clock, pole=None):
    """A half's outer loop as a closed polygon in the chart's (u, v): its points (as
    :class:`_Loop` takes them) unwrapped so that each step is less than half a period,
    and a pole, where a cap's two seams meet, passed along the pole's line from the one
    seam to the other. A point within :data:`MIN_PIECE_M` of the cap's ``pole`` ((v,
    point)) is at it, as is one the chart puts on a pole (a B-spline's row of control
    points collapsed within a tolerance meets its seams in points that far apart).
    Raises :class:`_Undo` when the loop winds round the surface or meets a pole more
    than once."""
    pu, pv = chart.periods
    L = _Loop(chart, loop, clock, unwrap=False)
    samples = L.samples[:-1]  # the last is the first again
    if pole is not None:
        for s in samples:
            if s.u is not None and dist(L.spans[s.k].point(s.t), pole[1]) <= MIN_PIECE_M:
                s.u, s.v = None, pole[0]
    at_pole = [s.u is None for s in samples]
    if all(at_pole):
        raise _Undo("a half whose loop lies on a pole")
    visits = sum(1 for k in range(len(samples)) if at_pole[k] and not at_pole[k - 1])
    if visits > 1:
        raise _Undo("a half whose loop meets a pole twice")
    # Start just after the pole, if any, so that the points run unbroken to it.
    start = next((k for k in range(len(samples)) if not at_pole[k] and at_pole[k - 1]), 0)
    pts: list[tuple[float, float]] = []
    pole_v = None
    for s in samples[start:] + samples[:start]:
        if s.u is None:
            pole_v = s.v
            continue
        u, v = s.u, s.v
        if pts:
            u = wrap_near(u, pts[-1][0], pu) if pu else u
            v = wrap_near(v, pts[-1][1], pv) if pv else v
        pts.append((u, v))
    if pole_v is not None:
        return [*pts, (pts[-1][0], pole_v), (pts[0][0], pole_v)]
    for k, period in enumerate((pu, pv)):
        if period:
            back = wrap_near(pts[0][k], pts[-1][k], period)
            if abs(back - pts[0][k]) > 0.5 * period:
                raise _Undo("a half whose loop winds round the surface")
    return pts


def _area(poly) -> float:
    """The signed area of a closed polygon (counter-clockwise positive)."""
    u0, v0 = poly[0]
    s = 0.0
    for (ua, va), (ub, vb) in zip(poly, poly[1:] + poly[:1], strict=True):
        s += (ua - u0) * (vb - v0) - (ub - u0) * (va - v0)
    return 0.5 * s


def _inside(poly, u: float, v: float) -> bool:
    inside = False
    for (ua, va), (ub, vb) in zip(poly, poly[1:] + poly[:1], strict=True):
        if (va > v) != (vb > v) and u < ua + (v - va) * (ub - ua) / (vb - va):
            inside = not inside
    return inside


def _check_halves(chart: _Chart, face: E.Face, halves, clock, pole=None) -> None:
    """Each half of a cut face, its outer loop followed round the chart, encloses an area
    on the side the face lies on (to the left in (u, v) when its normal is the natural
    one, to the right otherwise), and holds every hole it was given, whole periods
    aside. Raises :class:`.mapper.Refused` (``check_failed``) otherwise: a seam taken
    the wrong way round its circle, a half on the wrong side of its loops or a hole
    given to the wrong half fails here. ``pole`` is a cap's (v, point)."""
    o = (1 if face.same_sense else -1) * chart.flip
    pu, pv = chart.periods
    polys = [_outline(chart, h.bounds[0][0], clock, pole) for h in halves]
    areas = [_area(p) * o for p in polys]
    total = sum(abs(a) for a in areas)
    for h, poly, a in zip(halves, polys, areas, strict=True):
        clock.tick()
        if not a > NO_AREA * total:
            raise Refused(
                "check_failed", "a half of a face cut at its seams encloses no area on the face's side"
            )
        for lp, _o in h.bounds[1:]:
            u, v, _d = chart.uv(_loop_point(lp), None)
            shifts = [(k * (pu or 0.0), m * (pv or 0.0)) for k in range(-2, 3) for m in range(-2, 3)]
            if u is None or not any(_inside(poly, u + du, v + dv) for du, dv in shifts):
                raise Refused("check_failed", "a hole lies outside the half of the cut face it was given")


def split_seams(mapper, mapped) -> None:
    """Cut the body's faces that go round a closed surface in two at their seams (see
    the module's docstring). A face whose cut fails the checks is written whole."""
    Splitter(mapper, mapped).run()
