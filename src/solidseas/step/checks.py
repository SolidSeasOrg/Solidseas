"""The writer's own checks of a mapped body, before anything is written.

* **Loops close**: in every EDGE_LOOP each oriented edge ends where the next one
  starts.
* **Shells close**: in a CLOSED_SHELL every EDGE_CURVE is used exactly twice, once
  each way (twice in one face for a seam); in an OPEN_SHELL at most so.
* **Vertices on their curves**: each edge's start and end vertex lie on its curve as
  written.
* **Edges on the right arc**: points sampled along the source edge
  (:class:`solidseas.tessellate.edges.EdgeSampler`) lie on the written curve, and
  their parameters on it run from the start vertex's to the end vertex's in the
  direction ``same_sense`` gives, which catches the wrong arc of a circle and an
  edge running backwards.
* **Vertices on their surfaces**: each vertex of a face's loops lies on the face's
  surface as written.
* **Edges on their faces**: points along each edge as written (its samples' points,
  and points between them: :data:`BETWEEN`, more on an approximated surface) lie on
  the surface of each face it bounds, as written. This catches a surface that does not
  reach as far as its face's boundary and an edge that leaves its faces between its
  vertices.

The written geometry is evaluated from the numbers written
(:meth:`.entities.Item.evaluator`). Distances are allowed the larger of
:data:`ALLOWANCE_M`, the source vertex's or edge's own tolerance and twice an
approximation's measured deviation. A distance beyond that but within
``max_deviation_m`` is a gap of the source's own (Parasolid holds some vertices and
edges a little off their curves and surfaces without declaring a tolerance): it is
accepted, and the largest is the body's ``max_gap``, which the file's uncertainty
covers. Anything farther is the body's ``check_failed``.
"""

import math
from collections import Counter

from ..tessellate._vec import dist, dot, sub
from ..tessellate.surfaces import Torus, newton
from ..tessellate.topology import FaceFailed
from . import entities as E
from .mapper import FACTS, Refused

# Parasolid's linear resolution is 1e-8 m: an exact vertex lies within it of its edges
# and faces. Twice that, for the rounding to 15 digits and the inversion.
ALLOWANCE_M = 2e-8
# Points checked on the faces between two neighbouring samples of an edge (the sampler
# steps at most 30 degrees of turn): on an exact surface, and on an approximated one.
BETWEEN = (1, 7)
UNSAMPLED = 16  # spans along an edge the sampler could not follow


class _Stats:
    """The largest distances seen, for measuring how tight the allowance can be."""

    def __init__(self) -> None:
        self.vertex_curve = 0.0
        self.vertex_surface = 0.0
        self.sample_curve = 0.0
        self.edge_surface = 0.0
        self.gap = 0.0  # the largest gap of the source's own, beyond the allowance, accepted


def _gap(stats: _Stats, mapper, d: float, allow: float, fact: str = "undeclared_gap_accepted") -> bool:
    """Whether a distance beyond the allowance is a gap of the source's own small enough
    to accept (at most ``max_deviation_m``), which the file's uncertainty then covers:
    Parasolid holds some vertices a little off their curves and surfaces without
    declaring a tolerance."""
    if d <= allow:
        return True
    if d <= mapper.opts.max_deviation_m:
        stats.gap = max(stats.gap, d)
        FACTS[fact] += 1
        return True
    return False


def check_body(mapper, mapped, stats: _Stats | None = None) -> None:
    """Raise :class:`.mapper.Refused` (``check_failed``) when a check fails."""
    stats = stats or _Stats()
    clock = mapper.clock
    for item in mapped.items:
        shells = item.shells
        for shell in shells:
            _check_shell(shell, clock)
    faces_of: dict[int, list[E.Face]] = {}
    for face in mapped.faces:
        for loop, _o in face.bounds:
            if isinstance(loop, E.EdgeLoop):
                for e, _ in loop.edges:
                    got = faces_of.setdefault(id(e), [])
                    if face not in got:
                        got.append(face)
    for edge in mapped.edges:
        clock.tick()
        along = _check_edge(mapper, edge, stats)
        if along is not None:
            _check_edge_on_faces(mapper, edge, along, faces_of.get(id(edge), ()), stats)
    for face in mapped.faces:
        clock.tick()
        _check_face(mapper, face, stats)
    mapped.max_gap = stats.gap


def _fail(message: str):
    raise Refused("check_failed", message)


def _check_shell(shell: E.Shell, clock=None) -> None:
    uses: Counter = Counter()
    for face in shell.faces:
        if clock is not None:
            clock.tick(len(face.bounds))
        for loop, _outer in face.bounds:
            if isinstance(loop, E.VertexLoop):
                continue
            _check_loop(loop)
            for edge, o in loop.edges:
                uses[(id(edge), o)] += 1
    edges = {k[0] for k in uses}
    for e in edges:
        _check_uses(shell.closed, uses[(e, True)], uses[(e, False)])


def _check_loop(loop: E.EdgeLoop) -> None:
    """An edge loop has an edge, and each of its oriented edges ends where the next starts."""
    ends = loop.ends()
    if not ends:
        _fail("an edge loop with no edge")
    for k, (_s, e) in enumerate(ends):
        nxt = ends[(k + 1) % len(ends)][0]
        if e is not nxt:
            _fail("a loop does not close: an edge ends where the next does not start")


def _check_uses(closed: bool, f: int, b: int) -> None:
    """An edge used ``f`` times forward and ``b`` backward by a shell's loops: once each way
    in a closed shell (or not at all), at most once each way in an open one."""
    if closed:
        if (f != 1 or b != 1) and (f or b):
            _fail(f"an edge of a closed shell is used {f} time(s) forward and {b} backward")
    elif f > 1 or b > 1:
        _fail("an edge of an open shell is used twice the same way")


def _allow(*tolerances: float) -> float:
    return max(ALLOWANCE_M, *tolerances)


def _on_curve(ev, p, clock):
    """(parameter, distance) of the point of a written curve nearest ``p``."""
    t = ev.param(p, clock)
    return t, dist(ev.point(t), p)


def _near(ev, p, t: float):
    """(parameter, distance) of the point of a written curve nearest ``p`` by Newton's
    method from ``t``: the next sample along an edge is near the last one's parameter,
    so a long B-spline is not searched from end to end for each."""
    lo, hi = ev.lo, ev.hi
    for _ in range(24):
        q, d = ev.d1(t)
        g = d[0] * d[0] + d[1] * d[1] + d[2] * d[2]
        if not g > 0.0:
            break
        nt = t + ((p[0] - q[0]) * d[0] + (p[1] - q[1]) * d[1] + (p[2] - q[2]) * d[2]) / g
        if lo is not None:
            nt = min(max(nt, lo), hi)
        if abs(nt - t) <= 1e-15 * (1.0 + abs(t)):
            t = nt
            break
        t = nt
    return t, dist(ev.point(t), p)


def _check_edge(mapper, edge: E.Edge, stats: _Stats):
    """The edge's checks; returns ``(parameters, sign, period, sampled)``: parameters of
    the written curve from the edge's start to its end (its samples' where it has them,
    ``sampled``), the way it runs, and its curve's period, for the check on its faces; or
    None for a seam."""
    ev = edge.curve.evaluator()
    clock = mapper.clock
    dev2 = 2.0 * edge.deviation
    ps, pe = edge.start.metres(), edge.end.metres()
    ts, ds = _on_curve(ev, ps, clock)
    te, de = _on_curve(ev, pe, clock)
    stats.vertex_curve = max(stats.vertex_curve, ds, de)
    if not _gap(stats, mapper, ds, _allow(edge.tolerance, edge.start.tolerance, dev2)) or not _gap(
        stats, mapper, de, _allow(edge.tolerance, edge.end.tolerance, dev2)
    ):
        _fail(f"a vertex lies {max(ds, de):.3g} m from its edge's curve as written")
    period = 2.0 * math.pi if edge.curve.closed else getattr(ev, "period", None)
    if edge.start is edge.end and period is None and ev.lo is not None:
        # A ring on a curve whose parameter does not wrap: both ends of the curve are at
        # its one vertex, or the loop it closes is an open arc.
        allow = _allow(edge.tolerance, edge.start.tolerance, dev2)
        d0, d1 = dist(ev.point(ev.lo), ps), dist(ev.point(ev.hi), pe)
        if not _gap(stats, mapper, d0, allow) or not _gap(stats, mapper, d1, allow):
            _fail(f"a ring edge's curve as written does not close at its vertex ({max(d0, d1):.3g} m)")
    node = mapper.edge_nodes.get(id(edge))
    if node is None:  # a seam: made on the surface, with no source edge to compare
        return None
    sign = 1.0 if edge.same_sense else -1.0
    ring = edge.start is edge.end
    if ring and period is None:
        # An edge that closes on one vertex, on a curve whose parameter does not wrap: the
        # vertex is at both ends of the curve, and the edge runs from one to the other.
        lo, hi = ev.lo, ev.hi
        ts, te = (lo, hi) if edge.same_sense else (hi, lo)
    elif ring:
        te = ts + sign * period
    try:
        sm = mapper.sampler.samples(node)
    except FaceFailed:
        sm = None  # a source curve the sampler cannot follow; its vertices were checked
    pts = [mapper._points.p[i] for i in sm.ids] if sm is not None else []
    if len(pts) < 3:
        return [ts, te], sign, period, False
    allow = _allow(edge.tolerance, edge.start.tolerance, edge.end.tolerance, dev2)
    ts_list = [ts]
    local = edge.curve.kind == "B_SPLINE_CURVE_WITH_KNOTS"
    for q in pts[1:-1]:
        clock.tick()
        t, d = _near(ev, q, ts_list[-1]) if local else (None, math.inf)
        if d > allow:
            t, d = _on_curve(ev, q, clock)
        stats.sample_curve = max(stats.sample_curve, d)
        if d > allow:
            _fail(f"a point of an edge lies {d:.3g} m from its curve as written")
        ts_list.append(t)
    ts_list.append(te)
    if period is None:
        for a, b in zip(ts_list, ts_list[1:], strict=False):
            if (b - a) * sign < -1e-12 * (1.0 + abs(a)):
                _fail("an edge runs against its curve's parameter as written (same_sense)")
        return ts_list, sign, period, True
    # A closed curve: every step forward (in the edge's direction) by less than half a
    # turn, and the steps adding up to the arc from the start to the end, or a whole
    # turn for a ring.
    total = 0.0
    for a, b in zip(ts_list, ts_list[1:], strict=False):
        step = ((b - a) * sign) % period
        if step > period - 1e-9 * period:
            step -= period
        if step < -1e-9 * period or step > 0.5 * period + 1e-9:
            _fail("an edge takes the wrong way round its closed curve as written")
        total += step
    want = ((te - ts) * sign) % period
    if ring or want < 1e-12:
        want = period
    if abs(total - want) > 1e-6 * period:
        _fail("an edge's points do not go once from its start to its end along its curve")
    return ts_list, sign, period, True


def _step(a: float, b: float, sign: float, period) -> float:
    """The parameter step from ``a`` to ``b`` the way the edge runs (on a closed curve,
    forward round it, never more than a turn)."""
    if period is None:
        return b - a
    d = ((b - a) * sign) % period
    if d > period - 1e-9 * period:
        d -= period
    if d <= 1e-12 * period and a != b:
        d = period  # a ring's start and end are one point a turn apart
    return sign * d


def _check_edge_on_faces(mapper, edge: E.Edge, along, faces, stats: _Stats) -> None:
    """Points of the edge as written, at its samples and between them, on the surface of
    each face the edge bounds as written."""
    params, sign, period, sampled = along
    if not faces:
        return
    ev = edge.curve.evaluator()
    clock = mapper.clock
    dense = any(f.approximated for f in faces)
    k = BETWEEN[1 if dense else 0] if sampled else UNSAMPLED * (4 if dense else 1)
    ts = []
    for a, b in zip(params, params[1:], strict=False):
        d = _step(a, b, sign, period)
        ts.extend(a + d * (i / (k + 1)) for i in range(1, k + 1))
        ts.append(a + d)
    ts = ts[:-1]  # the end vertex: checked on its faces already
    pts = [ev.point(t) for t in ts]
    # The edge's own tolerance, not its vertices': a tolerant vertex lets edges stop short
    # of it, but an exact edge's curve still lies on its faces all along.
    base = _allow(edge.tolerance, 2.0 * edge.deviation)
    for face in faces:
        sev = face.surface.evaluator()
        allow = max(base, 2.0 * face.deviation)
        hint = None
        for p in pts:
            clock.tick()
            d, hint = _surface_distance_from(sev, p, hint, clock, allow)
            if d > allow:
                d = _closer(sev, p, d, clock)
            stats.edge_surface = max(stats.edge_surface, d)
            if not _gap(stats, mapper, d, allow, "edge_off_its_face_accepted"):
                _fail(f"a point of an edge lies {d:.3g} m from its face's surface as written")


def _check_face(mapper, face: E.Face, stats: _Stats) -> None:
    seen: set[int] = set()
    for loop, _o in face.bounds:
        if isinstance(loop, E.VertexLoop):
            vs = [(loop.vertex, 0.0)]
        else:
            vs = [(v, max(e.tolerance, 2.0 * e.deviation)) for e, _ in loop.edges for v in (e.start, e.end)]
        for v, tol in vs:
            if id(v) in seen:
                continue
            seen.add(id(v))
            _check_vertex(mapper, face, v, tol, stats)


def _check_vertex(mapper, face: E.Face, v: E.Vertex, tol: float, stats: _Stats) -> None:
    """A vertex of a face lies on its surface as written, allowed its own tolerance, the
    edge's it was met on (``tol``) and twice the face's deviation."""
    ev = face.surface.evaluator()
    allow = _allow(v.tolerance, tol, 2.0 * face.deviation)
    d = _surface_distance(ev, v.metres(), mapper.clock)
    if d > allow:
        d = _closer(ev, v.metres(), d, mapper.clock)
    stats.vertex_surface = max(stats.vertex_surface, d)
    if not _gap(stats, mapper, d, allow):
        _fail(f"a vertex lies {d:.3g} m from its face's surface as written")


def _surface_distance_from(ev, p, hint, clock, tol: float = 1e-9):
    """(distance, hint): the distance from ``p`` to a written surface, searched from the
    last point's foot along an edge; a foot found there within ``tol`` is taken without
    searching further (its distance is at least the true one)."""
    try:
        u, v, d = ev.closest(p, hint, tol, 1e-9, clock)
    except FaceFailed:
        return _surface_distance(ev, p, clock), None
    return d, ((u, v) if u is not None else None)


def _closer(ev, p, d: float, clock, grid: int = 9, side: int = 64) -> float:
    """``d``, or a smaller distance from ``p`` to a surface with a parameter box (a
    B-spline's, a swept or spun surface's), searched harder before a check fails on it:
    Newton's method from a ``grid`` x ``grid`` net of starts over the box, and the nearest
    point of each side of the box (a face's edge often runs along one, where Newton's
    steps, cut short at the side, stall)."""
    box = getattr(ev, "box", None)
    if box is None:
        return d
    try:
        u0, u1, v0, v1 = box()
    except (TypeError, ValueError):
        return d
    if not all(math.isfinite(x) for x in (u0, u1, v0, v1)) or not (u1 > u0 and v1 > v0):
        return d
    for i in range(grid):
        for j in range(grid):
            clock.tick()
            u = u0 + (u1 - u0) * (i + 0.5) / grid
            v = v0 + (v1 - v0) * (j + 0.5) / grid
            d = min(d, newton(ev, p, u, v)[2])
    for fixed, lo, hi, along_u in (
        (v0, u0, u1, True),
        (v1, u0, u1, True),
        (u0, v0, v1, False),
        (u1, v0, v1, False),
    ):

        def at(t, fixed=fixed, along_u=along_u):
            return ev.d1(t, fixed) if along_u else ev.d1(fixed, t)

        ts = [lo + (hi - lo) * k / side for k in range(side + 1)]
        t = min(ts, key=lambda t: dist(at(t)[0], p))
        for _ in range(30):  # Newton along the side, on the squared distance
            clock.tick()
            q, su, sv = at(t)
            tan = su if along_u else sv
            g = dot(tan, tan)
            if not g > 0.0:
                break
            nt = min(max(t + dot(sub(p, q), tan) / g, lo), hi)
            if abs(nt - t) <= 1e-15 * (1.0 + abs(t)):
                break
            t = nt
        d = min(d, dist(at(t)[0], p))
    return d


def _surface_distance(ev, p, clock=None) -> float:
    """The distance from ``p`` to a written surface; on a torus's axis (the poles of an
    apple or a lemon) the distance to its generating circle."""
    try:
        return ev.closest(p, None, 1e-9, 1e-9, clock)[2]
    except FaceFailed:
        if isinstance(ev, Torus):
            q = (p[0] - ev.C[0], p[1] - ev.C[1], p[2] - ev.C[2])
            h = q[0] * ev.A[0] + q[1] * ev.A[1] + q[2] * ev.A[2]
            rho = math.sqrt(max(0.0, q[0] ** 2 + q[1] ** 2 + q[2] ** 2 - h * h))
            return min(abs(math.hypot(rho - ev.R, h) - ev.r), abs(math.hypot(-rho - ev.R, h) - ev.r))
        return math.inf
