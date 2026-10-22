"""The tessellation of a set of bodies: faces walked, edges sampled, domains built,
triangulated, refined and emitted into one mesh.

A face that cannot be done is skipped with a reason and the rest go on; a limit
reached stops cleanly with the faces done so far and is named in ``truncated``.

With ``Options.detail`` (drawings) the engine also keeps, for each face done, the
float64 position, normal and (u, v) of each of its vertices and, for each edge it
uses, which of its vertices each of the edge's samples is; :meth:`Engine.detail`
gathers them. They are recorded as the face is emitted and dropped with it when a
face is undone, and the mesh is the same with or without them.
"""

import math
from array import array
from collections import Counter
from dataclasses import dataclass

from ..formats.solidworks.mesh import FaceTess, Mesh
from . import checks
from ._vec import cross, dot, norm, sub, wrap_near
from .blend import Blends
from .domain import Builder, area
from .edges import EdgeSampler
from .fit import FitFailed
from .surfaces import Geometry
from .topology import BLENDED_EDGE, EDGE, SURFACE_TYPES, Clock, FaceFailed, TimeUp
from .triangulate import TriMesh, cdt, check, covers, earcut, fill_gaps, perimeter, ring_area, tri_area2

MAX_SKIPPED_LISTED = 1000
REFINE_PASSES = 8
# A face folds over itself when its triangles cover its (u, v) polygon by more than this
# fraction over, or this fraction of its area lies in flaps (no area in (u, v), some in
# space): rounding and a ring that touches itself stay under it.
FOLD = 1e-3
# The fold check trusts a face's (u, v) only when its polygon's area, in the triangulation's
# scaled (u, v), is at least this fraction of the face's area in space.
FAITHFUL = 0.1
# A boundary point the surface does not reach is carried past the edge of its parameter
# range by one Gauss-Newton step, unless the step is longer than this fraction of the range.
BEYOND = 1.0
# A triangle of a face whose (u, v) polygon touches or crosses itself is stretched when its
# area in space is more than this many times the surface's over its (u, v) triangle.
STRETCHED = 10.0
# A rolling blend's approximation (.blend) is measured at the middle of each span between
# its exact sections, at three points across, where the STEP export measures seven along
# and nine across: measured so, the export found the true deviation up to 2.4 times the
# middle's (docs/FORMAT.md 10.9). It is fitted until that is within BLEND_FIT of the chord
# tolerance, so it lies within about a tenth of it, and refused (its faces skipped,
# ``fit_failed``) beyond BLEND_LIMIT of it, about the whole of it.
BLEND_FIT = 0.04
BLEND_LIMIT = 0.4
BLEND_ALONG = (0.5,)
BLEND_ACROSS = 3
# A foot on a support is followed from the last one found however far the point asked
# about moves (the export: only while it moves less than its distance from the support),
# the support searched afresh only when that foot does not settle, jumps or is farther
# than the last. Searched afresh more often, a foot can jump to another part of the
# support: on a corpus part of 192 blend faces 96 were refused so, and none with this;
# on another 6 of 97 against 2, in less than half the time.
BLEND_REACH = 1e6
# On an intersection spine, the spine point found for a measured point is square to it
# within this fraction of the fit's target (the export: 1e-11 m).
BLEND_SLIDE = 0.01
# One blend's fit may take this share of the time allowed (max_seconds), and at most
# BLEND_SECONDS, before its best round is kept (if within BLEND_LIMIT) or it is refused
# (``fit_failed``): a blend whose spine cannot be followed can otherwise take minutes to
# fail (on one corpus part at the 3D print's chord, two took 330 s each). At the print's
# 300 s a tenth was 30 s a blend, mostly spent on blends refused anyway: on the corpus at
# the print's chord, on a machine loaded with other work, the slowest blend drawn needed
# 8.6 s to come within BLEND_LIMIT, while of the 15 that ran out of their 30 s, 12 were
# still 18 to 18,900 times the target, 2 had not finished a round and 1 had been within
# the limit (now kept). A deviation that stays put is no sign of a fit that will fail: on
# 41 blends drawn it stayed within a tenth for two to seven rounds, at up to 7,800 times
# the target, then fell below it. The share is a time, so near it the result depends on
# the machine's speed and load.
BLEND_SHARE = 0.1
BLEND_SECONDS = 15.0


@dataclass(frozen=True)
class Options:
    chord: float
    angle: float  # radians
    max_faces: int
    max_triangles: int
    max_face_points: int
    max_edge_points: int
    max_seconds: float
    # The blends' pass ends this long before the deadline: a caller that gave the
    # tessellation all of its own time (a Parasolid file's export scene) can then still
    # make meshes of a result whose blends the time ran out on.
    blend_reserve: float = 0.0
    # Keep what drawings need beside the mesh (the module notes; ``TessDetail``).
    detail: bool = False


# What damaged geometry the checks did not foresee raises in the geometry code: it costs
# the face (or the body, when its faces cannot be listed), never the tessellation. A
# reference to the wrong kind of node gives AttributeError, a crafted chain of nodes
# RecursionError.
_DAMAGE = (
    ZeroDivisionError,
    OverflowError,
    ValueError,
    IndexError,
    KeyError,
    TypeError,
    AttributeError,
    RecursionError,
)


class _Stop(Exception):
    """A limit stopped the whole tessellation (its name is in ``truncated``)."""


class PointsFull(_Stop):
    """The points reached their limit (:class:`Points`): reported as ``max_triangles``."""


class Points:
    """Every point of a tessellation: coordinates and the tolerance of the vertex or edge
    it came from (0 for exact). At most ``limit``: the points of a face that failed stay
    (edges sampled for it are shared with its neighbours), so the limit, not the
    triangles, bounds what a body of many failing faces can make."""

    def __init__(self, limit: int | None = None) -> None:
        self.p: list[tuple[float, float, float]] = []
        self.tol: list[float] = []
        self.limit = limit

    def add(self, p, tol: float = 0.0) -> int:
        if self.limit is not None and len(self.p) >= self.limit:
            raise PointsFull
        if not (math.isfinite(p[0]) and math.isfinite(p[1]) and math.isfinite(p[2])):
            raise FaceFailed("non_finite", "a point is not finite")
        self.p.append((p[0], p[1], p[2]))
        self.tol.append(tol)
        return len(self.p) - 1


class _Dom:
    """The (u, v) points of one face's domain, their point ids and scaled coordinates."""

    __slots__ = ("u", "v", "pid", "xy", "ku", "kv")

    def __init__(self, ku: float, kv: float) -> None:
        self.u: list[float] = []
        self.v: list[float] = []
        self.pid: list[int] = []
        self.xy: list[tuple[float, float]] = []
        self.ku, self.kv = ku, kv

    def add(self, u: float, v: float, pid: int) -> int:
        self.u.append(u)
        self.v.append(v)
        self.pid.append(pid)
        self.xy.append((u * self.ku, v * self.kv))
        return len(self.u) - 1


class _Work:
    """One body being done: its faces on rolling blends, still to do, the ranges of its
    triangles in the welded list and of its faces in the mesh (the blends are done after
    every body's other faces, so a body's are not one run), and whether every face so far
    was done."""

    __slots__ = ("k", "label", "ctx", "btype", "blends", "ranges", "face_ranges", "all_done", "at")

    def __init__(self, k: int, label: str, ctx, btype: str) -> None:
        self.k, self.label, self.ctx, self.btype = k, label, ctx, btype
        self.blends: list = []
        self.ranges: list[tuple[int, int]] = []
        self.face_ranges: list[tuple[int, int]] = []  # (start, end) indices of mesh.faces
        self.all_done = True
        self.at = 0  # the face being done


class Engine:
    def __init__(self, opts: Options, clock: Clock) -> None:
        self.opts, self.clock = opts, clock
        # A mesh has about half as many points as triangles; the rest is room for the
        # points of faces that failed.
        self.pts = Points(opts.max_triangles + 2 * opts.max_face_points)
        self.mesh = Mesh("brep")
        self.welded = array("I")
        self.face_ids: list[tuple[int, int]] = []
        self.counts: Counter = Counter()
        self.skipped: list[tuple[str, int, str, str, str]] = []
        self.reasons: Counter = Counter()
        self.truncated: list[str] = []
        self.solids_closed: list[bool] = []
        self.stats: Counter = Counter()
        self.checks: Counter = Counter()  # the self-checks' findings (checks.py, CHECKS)
        self.face_shells: list[int] = []  # each face done's shell, as face_ids
        self.off_surface: set[int] = set()  # the face's boundary points farther off it than the chord
        self.facts: Counter = Counter()  # how often the blends met their conventions (FORMAT.md 10.9)
        # With opts.detail: float64 positions and normals beside the mesh's float32 ones, and
        # per face done (as face_ids) its vertices' (u, v) and, for each edge it uses, the
        # edge's key and the face's vertex of each sample. ``_face_edges`` holds the edges of
        # the face being done; ``edge_samples`` every edge's samples by key.
        self.detail_points = array("d")
        self.detail_normals = array("d")
        self.detail_uv: list[array] = []
        self.detail_edges: list[list[tuple[tuple[int, int], array]]] = []
        self.edge_samples: dict[tuple[int, int], object] = {}
        self._face_edges: list[tuple[tuple[int, int], object]] = []
        self._edge_keys: dict[tuple[int, int], tuple[int, int]] = {}  # (body, node index): key
        self._edge_owners: dict[tuple[int, int], int] = {}  # (body, node_id): the node index using it

    # ------------------------------------------------------------------ bodies
    def run(self, bodies) -> None:
        """``bodies``: (label, topology, BODY node, body type) in order. Each transmit's
        topology is shared by its bodies, with one sampler and one geometry cache.

        A rolling blend costs far more than any other face (it is fitted first), so every
        body's other faces are done first and the blends after them: the time limit then
        leaves out blends, never the other faces of a body or a whole later body. Blends
        the time runs out on are skipped with the reason ``max_seconds`` (everything else
        being whole, the result is not ``truncated``), and one blend's fit may take at most
        BLEND_SHARE of the time allowed, at most BLEND_SECONDS. The blends' pass ends
        ``blend_reserve`` seconds before the deadline, for a caller that needs time to use
        the result."""
        ctxs: dict[int, tuple] = {}
        deadline = self.clock.deadline
        try:
            later = []
            for k, (label, topo, node, btype) in enumerate(bodies):
                ctx = ctxs.get(id(topo))
                if ctx is None:
                    geom = Geometry(topo, self.opts.chord)
                    sampler = EdgeSampler(topo, geom, self.pts, self.opts, self.clock)
                    chord = self.opts.chord
                    geom.blends = Blends(
                        topo,
                        geom,
                        sampler,
                        self.pts.p,
                        self.clock,
                        BLEND_FIT * chord,
                        BLEND_LIMIT * chord,
                        facts=self.facts,
                        along=BLEND_ALONG,
                        across=BLEND_ACROSS,
                        reach=BLEND_REACH,
                        slide=BLEND_SLIDE * BLEND_FIT * chord,
                        give_up=True,
                        budget=min(BLEND_SECONDS, BLEND_SHARE * self.opts.max_seconds),
                    )
                    ctx = ctxs[id(topo)] = (topo, geom, sampler)
                work = self.body(k, label, ctx, node, btype)
                if work is not None and work.blends:
                    later.append(work)
                elif work is not None:
                    self._closed_body(work)
            if later:
                self.clock.deadline = deadline - self.opts.blend_reserve
            for n, work in enumerate(later):
                try:
                    self._faces(work, work.blends)
                except TimeUp:
                    for w in later[n:]:
                        for i in range(w.at if w is work else 0, len(w.blends)):
                            self._out_of_time(w, w.blends[i], counted=w is work and i == w.at)
                        self._closed_body(w)
                    break
                self._closed_body(work)
        except PointsFull:
            self.truncated.append("max_triangles")
        except _Stop:
            pass
        except TimeUp:
            self.truncated.append("max_seconds")
        finally:
            self.clock.deadline = deadline
            self.counts["edges"] = sum(c[2].count for c in ctxs.values())

    def body(self, k: int, label: str, ctx, node, btype: str):
        """A body's faces other than its blends: the body's work, its blends still to
        do, or None when the body cannot be walked."""
        topo = ctx[0]
        self.counts["bodies"] += 1
        try:
            faces = topo.faces(node)
        except (FaceFailed, *_DAMAGE) as exc:
            failed = isinstance(exc, FaceFailed)
            reason = exc.reason if failed else "degenerate"
            detail = exc.detail if failed else type(exc).__name__
            self.counts["bodies_skipped"] += 1
            self._skip(label, -1, "", reason, detail)
            if btype == "solid":
                self.solids_closed.append(False)  # a solid with no triangles is not whole
            return None
        work = _Work(k, label, ctx, btype)
        others = []
        for face in faces:
            (work.blends if _on_blend(topo, face) else others).append(face)
        self._faces(work, others)
        return work

    def _faces(self, work: "_Work", faces) -> None:
        topo = work.ctx[0]
        first = len(self.welded)
        first_face = len(self.mesh.faces)
        try:
            for i, face in enumerate(faces):
                work.at = i
                if self.counts["faces"] >= self.opts.max_faces:
                    self.truncated.append("max_faces")
                    raise _Stop
                self.counts["faces"] += 1
                self.clock.check()
                fid = topo.get(face, "node_id", face.index)
                fid = fid if isinstance(fid, int) else face.index
                m = self.mesh
                mark = (len(m.positions), len(m.normals), len(m.triangles), len(self.welded), len(m.faces))
                surf = ""
                try:
                    snode = topo.ref(face, "surface", SURFACE_TYPES, required=True)
                    surf = snode.tname
                    self.face(work.k, fid, work.ctx, face, snode)
                    self.face_shells.append(topo.shell_of.get(face.index, -1))
                    self.counts["faces_done"] += 1
                except FaceFailed as exc:
                    self._undo(mark)
                    work.all_done = False
                    self.counts["faces_skipped"] += 1
                    self._skip(work.label, fid, surf, exc.reason, exc.detail)
                except _DAMAGE as exc:
                    # a damaged value the checks did not foresee: this face only
                    self._undo(mark)
                    work.all_done = False
                    self.counts["faces_skipped"] += 1
                    self._skip(work.label, fid, surf, "degenerate", type(exc).__name__)
                except (TimeUp, _Stop):
                    self._undo(mark)
                    raise
        finally:
            work.ranges.append((first, len(self.welded)))
            work.face_ranges.append((first_face, len(self.mesh.faces)))

    def _out_of_time(self, work: "_Work", face, counted: bool) -> None:
        """A blend face the time ran out on (``counted``: the one it ran out in)."""
        topo = work.ctx[0]
        if not counted:
            self.counts["faces"] += 1
        self.counts["faces_skipped"] += 1
        work.all_done = False
        fid = topo.get(face, "node_id", face.index)
        fid = fid if isinstance(fid, int) else face.index
        self._skip(work.label, fid, "BLENDED_EDGE", "max_seconds", "the time ran out before it was done")

    def _closed_body(self, work: "_Work") -> None:
        """A solid's closure, once all its faces are done or left out: whether it is
        watertight (``solids_closed``), and the self-checks of ``checks``: a solid whose
        triangles do not use every edge once each way is ``solids_not_closed``, and a closed
        one has its shells judged by their nesting (:meth:`_shell_signs`)."""
        if work.btype != "solid":
            return
        balanced, strict = _closed(self.welded, work.ranges)
        self.solids_closed.append(work.all_done and balanced)
        if not (work.all_done and strict):
            self.checks["solids_not_closed"] += 1
        elif any(a < b for a, b in work.face_ranges):
            self._shell_signs(work.face_ranges)

    def _shell_signs(self, face_ranges) -> None:
        """A closed solid's shells against the parity of their nesting (``checks``): one
        shell must have a positive volume; of several, each that lies inside an odd
        number of others (a void) a negative one, every other a positive one.
        ``face_ranges`` are the solid's runs of faces in the mesh, ``(start, end)``. Once
        the time is up (the bodies after a blend pass that ran out of it) nothing is
        judged: the tessellation already says it stopped at its time limit."""
        left = self.clock.left()
        if left is not None and left <= 0:
            return
        groups: dict[int, list[tuple[int, int]]] = {}
        faces = self.mesh.faces
        for start, end in face_ranges:
            for k in range(start, end):
                f = faces[k]
                if f.n_triangles:
                    groups.setdefault(self.face_shells[k], []).append((f.first_triangle, f.n_triangles))
        found = checks.shells(self.pts.p, self.welded, list(groups.values()), closed=True)
        if len(found) > 1:
            try:
                depth = checks.nesting(self.pts.p, self.welded, found, self.opts.chord, tick=self.clock.tick)
            except TimeUp:  # the time ran out while judging: nothing judged, the next face stops
                return
        else:
            depth = [0] * len(found)
        self.checks["shells_inside_out"] += len(checks.inside_out(found, depth))

    def _undo(self, mark) -> None:
        m = self.mesh
        del m.positions[mark[0] :]
        del m.normals[mark[1] :]
        del m.triangles[mark[2] :]
        del self.welded[mark[3] :]
        del m.faces[mark[4] :]
        del self.face_ids[mark[4] :]
        del self.face_shells[mark[4] :]
        if self.opts.detail:  # aligned with the mesh's positions, normals and faces
            del self.detail_points[mark[0] :]
            del self.detail_normals[mark[1] :]
            del self.detail_uv[mark[4] :]
            del self.detail_edges[mark[4] :]

    def _skip(self, label: str, fid: int, surf: str, reason: str, detail: str) -> None:
        self.reasons[reason] += 1
        if len(self.skipped) < MAX_SKIPPED_LISTED:
            self.skipped.append((label, fid, surf, reason, detail))

    # ------------------------------------------------------------------ one face
    def face(self, body_k: int, fid: int, ctx, face, snode) -> None:
        topo, geom, sampler = ctx
        opts, clock = self.opts, self.clock
        S = geom.surface(snode)
        if snode.type == BLENDED_EDGE:
            # Parasolid's own (u, v) of a blend is not known: the face's side on the
            # approximation comes from its loops (_domain), and on a blend closed round its
            # spine, whose loops wrap round it, from a face it meets tangentially.
            o = None
            if S.pu is not None or S.pv is not None or S.poles:
                o = geom.blends.side(face, snode) * S.flip
            self.stats["blend_faces"] += 1
        else:
            o = topo.sense(face) * topo.sense(snode) * S.flip
        loops = []
        detail = self.opts.detail
        if detail:
            self._face_edges = []
        for lp in topo.loops(face):
            fins = _without_spikes(topo, topo.fins(lp))
            if not fins:
                self.stats["spike_loops"] += 1
                continue
            ids: list[int] = []
            uvs: list = []
            for fin in fins:
                edge = topo.ref(fin, "edge", (EDGE,))
                if edge is None:
                    if len(fins) == 1:  # an isolated vertex: a point of the face, no boundary
                        self.stats["isolated_vertex_loops"] += 1
                        break
                    raise FaceFailed("bad_reference", "a fin without an edge")
                es = sampler.samples(edge)
                if es.degenerate:
                    self.stats["degenerate_ring_loops"] += 1
                    continue
                if detail:
                    key = self._edge_key(body_k, topo, edge)
                    self.edge_samples[key] = es
                    self._face_edges.append((key, es))
                seq = es.ids
                uv = es.uv if es.surface == snode.index else None
                if topo.sense(fin) < 0:
                    seq = seq[::-1]
                    uv = uv[::-1] if uv is not None else None
                if ids:
                    if ids[-1] != seq[0]:
                        raise FaceFailed("bad_reference", "the fins of a loop do not join")
                    seq = seq[1:]
                    uv = uv[1:] if uv is not None else None
                ids.extend(seq)
                uvs.extend(uv if uv is not None else [None] * len(seq))
            if len(ids) > 1 and ids[0] == ids[-1]:
                ids.pop()
                uvs.pop()
            if len(ids) >= 2:
                loops.append((ids, uvs))
        n_boundary = sum(len(i) for i, _u in loops)
        if n_boundary > opts.max_face_points:
            raise FaceFailed("max_face_points", f"{n_boundary} boundary points")
        # (u, v) of every boundary point, and the face's polygon. A boundary row of a
        # B-spline collapsed to within the chord tolerance is taken as a pole; when that
        # leaves a whole loop on poles (a strip about as narrow as the tolerance), the
        # face is tried again with exact poles only.
        try:
            builder, rings = self._domain(S, o, loops)
        except FaceFailed as exc:
            if exc.detail != "a loop lies on a pole" or not any(S.pole_radius):
                raise
            saved = S.pole_radius
            S.pole_radius = ()
            try:
                builder, rings = self._domain(S, o, loops)
            finally:
                S.pole_radius = saved
        o = builder.o
        dom = _Dom(builder.ku, builder.kv)
        idx_rings = [[dom.add(u, v, pid) for u, v, pid in r] for r in rings]
        if sum(len(r) for r in idx_rings) > opts.max_face_points:
            raise FaceFailed("max_face_points", "too many points on the face's boundary")
        tris, complete = earcut(dom.xy, idx_rings[0], idx_rings[1:], dom.pid, clock)
        loose = False
        if not complete or not check(dom.xy, idx_rings, tris):
            self.stats["cdt_fallback"] += 1
            alt = cdt(dom.xy, idx_rings, dom.pid, clock)
            if alt is not None and check(dom.xy, idx_rings, alt, 1e-7):
                tris = alt
            elif tris and covers(dom.xy, idx_rings, tris, opts.chord * perimeter(dom.xy, idx_rings)):
                # rings that touch or cross themselves by less than the chord tolerance
                self.stats["loose_accept"] += 1
                loose = True
            elif builder.thin:
                raise FaceFailed("degenerate", "the face is thinner than the chord tolerance")
            else:
                raise FaceFailed(
                    "triangulation_failed", "the face's (u, v) polygon could not be triangulated"
                )
        if not tris:
            raise FaceFailed("degenerate", "no triangles")
        tris, filled, left = fill_gaps(dom.xy, idx_rings, tris)
        if filled:
            self.stats["gaps_filled"] += filled
        if left:
            self.stats["gaps_left"] += left
        coarse = False
        small = self._small(dom.pid)
        if S.kind != "plane" and not small:
            tris, coarse = self.refine(S, dom, tris, idx_rings)
        # The triangles are counter-clockwise in (u, v), and they run along the outer ring
        # the way it runs when it is counter-clockwise too: then o says which way round
        # they go in space. A face thinner than the tolerance can have its outer ring run
        # the other way (its sides cross): its triangles then follow the ring, so that its
        # edges still meet its neighbours' the other way round.
        wind = o
        if builder.thin:
            wind = 1 if ring_area(dom.xy, idx_rings[0]) > 0.0 else -1
        # The polygon's area, against which the triangles are checked (none for a face
        # thinner than the tolerance, whose sides may cross, or one that fits within it,
        # whose triangles are within the tolerance however they lie).
        poly = 0.0
        if not builder.thin and not small:
            holes = sum(abs(ring_area(dom.xy, h)) for h in idx_rings[1:])
            poly = abs(ring_area(dom.xy, idx_rings[0])) - holes
        folded = self.checks["faces_folded"]
        self.emit(body_k, fid, S, o, dom, tris, wind, poly)
        if loose and poly and self.checks["faces_folded"] == folded and self._stretched(S, dom, tris):
            self.checks["faces_folded"] += 1
        if builder.reversed:
            self.checks["loops_reversed"] += 1
        if coarse:
            self.checks["faces_coarse"] += 1

    def _edge_key(self, body_k: int, topo, edge) -> tuple[int, int]:
        """An edge's key in the detail: (body, EDGE ``node_id``), or for an edge whose
        ``node_id`` is missing, not positive or already another edge's in the body (a
        file that numbers its nodes wrongly), (body, -1 - its node index), so two edges
        never share one."""
        at = (body_k, edge.index)
        key = self._edge_keys.get(at)
        if key is None:
            nid = topo.get(edge, "node_id", None)
            if (
                isinstance(nid, int)
                and nid > 0
                and self._edge_owners.setdefault((body_k, nid), edge.index) == edge.index
            ):
                key = (body_k, nid)
            else:
                key = (body_k, -1 - edge.index)
            self._edge_keys[at] = key
        return key

    def _small(self, pids) -> bool:
        """Whether the face fits within the chord tolerance: no point inside it can then
        bring the triangles closer to the surface."""
        P = self.pts.p
        lo = [math.inf] * 3
        hi = [-math.inf] * 3
        for i in pids:
            p = P[i]
            for k in range(3):
                if p[k] < lo[k]:
                    lo[k] = p[k]
                if p[k] > hi[k]:
                    hi[k] = p[k]
        return math.dist(lo, hi) <= self.opts.chord

    def _stretched(self, S, dom: _Dom, tris) -> bool:
        """Whether a face whose (u, v) polygon touches or crosses itself (its triangles
        accepted loosely) has more than :data:`FOLD` of its area in space in triangles
        stretched across it: each over :data:`STRETCHED` times the surface's own area over
        its (u, v) triangle (``|Su x Sv|`` at its middle). Such a triangle covers its (u, v)
        once and lies in the surface's tangent plane, far from the surface's point at its
        middle but not off its own plane, so neither the (u, v) cover nor the refinement's
        distance finds it; only faces accepted loosely are measured, a surface evaluation
        a triangle."""
        P, pid, u, v = self.pts.p, dom.pid, dom.u, dom.v
        total = stretched = 0.0
        for a, b, c in tris:
            self.clock.tick()
            ia, ib, ic = pid[a], pid[b], pid[c]
            if ia == ib or ib == ic or ia == ic:
                continue
            pa = P[ia]
            a3 = 0.5 * norm(cross(sub(P[ib], pa), sub(P[ic], pa)))
            total += a3
            s2 = (u[b] - u[a]) * (v[c] - v[a]) - (v[b] - v[a]) * (u[c] - u[a])
            try:
                _p, su, sv = S.d1((u[a] + u[b] + u[c]) / 3.0, (v[a] + v[b] + v[c]) / 3.0)
            except (ZeroDivisionError, OverflowError, ValueError):
                continue
            if a3 > STRETCHED * 0.5 * abs(s2) * norm(cross(su, sv)):
                stretched += a3
        return stretched > FOLD * total

    def _domain(self, S, o: int | None, loops):
        """``(builder, rings)``: the (u, v) of every boundary point, then the polygon. ``o``
        None: a blend face's side, from its loops (:func:`_side_from_loops`)."""
        opts, clock, pts = self.opts, self.clock, self.pts
        accept = 10.0 * opts.chord
        loops_uv = []
        parametric = S.kind == "parametric"
        self.off_surface = off = set()
        for ids, uvs in loops:
            out = []
            hint = None
            for pid, known in zip(ids, uvs, strict=True):
                clock.tick()
                p = pts.p[pid]
                t = pts.tol[pid]
                ptol = max(1e-6, 2.0 * t)
                seed = None
                if known is not None and parametric:
                    u, v = S.from_file(known[0], known[1])
                    vp = S.at_pole(u, v, p, ptol)
                    if vp is not None:
                        u, v = None, vp
                else:
                    # A point within the chord (or its edge's tolerance) is on the surface and
                    # taken at once; one farther, though within the ten chords accepted, is
                    # the nearest of every starting point's, not the first found.
                    u, v, d = S.closest(
                        p, hint, max(accept, 2.0 * t, 1e-7), ptol, clock, near=max(opts.chord, 2.0 * t)
                    )
                    if not d <= max(accept, 2.0 * t, 1e-7):
                        raise FaceFailed("inversion_failed", f"a boundary point {d:.3g} m from its surface")
                    if d > max(opts.chord, 2.0 * t):
                        off.add(pid)  # accepted, though farther off the surface than the chord
                        if parametric and u is not None:
                            # the next point is looked for from here, on the surface, not
                            # from past its edge, where it would be found on the edge too
                            seed = (u, v)
                            u, v = _beyond(S, p, u, v)
                out.append((u, v, pid))
                if u is not None:
                    hint = seed or (u, v)
            loops_uv.append(_spread(S, out))
        if o is None:
            o = _side_from_loops(S, loops_uv)
            self.stats["blend_side_from_loops"] += 1
        builder = Builder(S, o, opts, pts.add, clock)
        return builder, builder.build(loops_uv)

    # ------------------------------------------------------------------ refinement
    def refine(self, S, dom: _Dom, tris, rings):
        """``(triangles, coarse)``: the face's triangles with points added inside until each
        keeps within the chord tolerance and the angle (for at most :data:`REFINE_PASSES`
        passes), and whether ``max_face_points`` stopped that with triangles still out of
        it."""
        opts, clock, pts = self.opts, self.clock, self.pts
        off = self.off_surface
        fixed = set()
        for r in rings:
            n = len(r)
            for k in range(n):
                a, b = r[k], r[(k + 1) % n]
                if a != b:
                    fixed.add((a, b))
        mesh = TriMesh(dom.xy, tris, fixed, clock)
        mesh.make_delaunay()
        keep = self._keep_off(S, dom, fixed)
        u, v, pid = dom.u, dom.v, dom.pid
        box = (min(u), max(u), min(v), max(v))
        du, dv = S.steps(box, opts.chord, opts.angle)
        room = opts.max_face_points - len(u)
        if du and dv and room > 0:
            nu = max(1, math.ceil((box[1] - box[0]) / du))
            nv = max(1, math.ceil((box[3] - box[2]) / dv))
            if nu * nv > room:
                f = math.sqrt(room / (nu * nv))
                nu, nv = max(1, int(nu * f)), max(1, int(nv * f))
                # one of them rounded up to 1 can leave the other past the room by itself
                nu = min(nu, max(1, room // nv))
                nv = min(nv, max(1, room // nu))
            if nu * nv > 1:
                gap = 0.25 * min(du * dom.ku, dv * dom.kv)
                for i in range(nu):
                    uu = box[0] + (box[1] - box[0]) * (i + 0.5) / nu
                    for j in range(nv):
                        clock.tick()
                        vv = box[2] + (box[3] - box[2]) * (j + 0.5) / nv
                        if off and not _within(S, uu, vv):
                            continue  # past the surface's range, where boundary points were carried
                        x, y = uu * dom.ku, vv * dom.kv
                        got = mesh.walk(x, y)
                        if got is None or got[1] is not None:
                            continue
                        k = got[0]
                        if _near_fixed(mesh, k, x, y, gap) or _too_near(keep, mesh.t[k], x, y):
                            continue
                        q = S.point(uu, vv)
                        mesh.insert_in(dom.add(uu, vv, pts.add(q)), k)
        cos_a = math.cos(opts.angle)
        normals: dict[int, tuple | None] = {}
        on_pole = _pole_test(S)

        def nrm(i):
            got = normals.get(i, False)
            if got is False:
                got = normals[i] = None if on_pole(v[i]) else S.normal(u[i], v[i])
            return got

        P = pts.p
        min_edge2 = (4.0 * opts.chord) ** 2
        good: set[tuple[int, int, int]] = set()  # triangles already found within the tolerances
        for _pass in range(REFINE_PASSES):
            clock.check()
            inserted = 0
            for k in range(len(mesh.t)):
                tri = mesh.t[k]
                if tri is None:
                    continue
                clock.tick()
                a, b, c = tri
                key = (a, b, c) if a < b and a < c else ((b, c, a) if b < c else (c, a, b))
                if key in good:
                    continue
                ia, ib, ic = pid[a], pid[b], pid[c]
                if ia == ib or ib == ic or ia == ic:
                    continue
                pa, pb, pc = P[ia], P[ib], P[ic]
                cu = (u[a] + u[b] + u[c]) / 3.0
                cv = (v[a] + v[b] + v[c]) / 3.0
                if off and (ia in off or ib in off or ic in off):
                    # A corner on the boundary lies off the surface by more than the chord
                    # (an edge the surface does not reach): no point inside brings the
                    # triangle closer to it, and judged with it every split stays out of
                    # tolerance and is split again, without end. It is judged with that
                    # corner where it falls on the surface instead, and not split where its
                    # middle lies past the surface's range.
                    if not _within(S, cu, cv):
                        good.add(key)
                        continue
                    pa = S.point(u[a], v[a]) if ia in off else pa
                    pb = S.point(u[b], v[b]) if ib in off else pb
                    pc = S.point(u[c], v[c]) if ic in off else pc
                tn = cross(sub(pb, pa), sub(pc, pa))
                ln = norm(tn)
                if ln == 0.0:
                    continue
                q = S.point(cu, cv)
                bad = abs(dot(sub(q, pa), tn)) / ln > opts.chord
                # The normals are compared only on triangles larger than a few chord
                # tolerances: across a crease (a knot where the surface is only C0) no
                # triangle, however small, has the normals of both sides.
                if not bad and _longest2(pa, pb, pc) > min_edge2:
                    for i in (a, b, c):
                        n = nrm(i)
                        if n is not None and dot(tn, n) / ln < cos_a:
                            bad = True
                            break
                if not bad:
                    good.add(key)
                    continue
                if len(u) >= opts.max_face_points:
                    self.stats["face_point_cap"] += 1
                    return mesh.triangles(), True
                if self._split(S, dom, mesh, k, tri, cu, cv, q, keep):
                    inserted += 1
            if not inserted:
                break
        # Passes that run out while points still go in are usual (the last points sharpen
        # the normals at a crease); the point bound is not.
        return mesh.triangles(), False

    def _split(self, S, dom: _Dom, mesh: TriMesh, k: int, tri, cu: float, cv: float, q, keep=None) -> bool:
        """Refine triangle ``k``: its centroid, or, when that lies close to a fixed edge,
        the midpoint of its longest free edge. A triangle on a boundary edge gets no
        point within that edge's keep-off distance (:meth:`_keep_off`)."""
        xy = dom.xy
        a, b, c = tri
        x, y = cu * dom.ku, cv * dom.kv
        lens = [
            ((xy[i][0] - xy[j][0]) ** 2 + (xy[i][1] - xy[j][1]) ** 2, i, j)
            for i, j in ((a, b), (b, c), (c, a))
        ]
        shortest = math.sqrt(min(lens)[0])
        # A triangle on a boundary edge gets no point within that edge's keep-off distance.
        own = [e for e in ((a, b), (b, c), (c, a)) if mesh.is_fixed(*e)] if keep is not None else []
        if _near_fixed(mesh, k, x, y, 0.25 * shortest) or _off_limits(keep, own, x, y):
            for _l2, i, j in sorted(lens, reverse=True):
                if mesh.is_fixed(i, j) or (j, i) not in mesh.e:
                    continue
                um, vm = (dom.u[i] + dom.u[j]) / 2, (dom.v[i] + dom.v[j]) / 2
                if _off_limits(keep, own, um * dom.ku, vm * dom.kv):
                    continue
                idx = dom.add(um, vm, self.pts.add(S.point(um, vm)))
                if mesh.split_edge(i, j, idx):
                    return True
                _drop(dom)
                self.pts.p.pop()
                self.pts.tol.pop()
            return False
        if tri_area2(xy, a, b, c) <= 0.0:
            return False
        mesh.insert_in(dom.add(cu, cv, self.pts.add(q)), k)
        return True

    def _keep_off(self, S, dom: _Dom, fixed):
        """How far points inside the face keep from each boundary edge, or None.

        A boundary edge is a chord: it lies off the surface by its sagitta s (the
        boundary's samples are shared with the next face, so it cannot be split here).
        A triangle on it whose third point is closer than ``s / tan(angle)`` stands up
        off the surface by more than the angle, and folds over when that point falls
        outside the chord; so the first points inside keep that far from it, and
        refining a triangle on it puts none closer. The distance is at most a quarter
        of the edge's length."""
        P = self.pts.p
        u, v, pid, xy = dom.u, dom.v, dom.pid, dom.xy
        k = 1.0 / math.tan(self.opts.angle)
        widths: dict[tuple[int, int], float] = {}
        incident: dict[int, list[tuple[int, int]]] = {}
        for a, b in fixed:
            self.clock.tick()
            if pid[a] == pid[b]:
                continue
            pa, pb = P[pid[a]], P[pid[b]]
            mid = ((pa[0] + pb[0]) * 0.5, (pa[1] + pb[1]) * 0.5, (pa[2] + pb[2]) * 0.5)
            s = math.dist(S.point((u[a] + u[b]) * 0.5, (v[a] + v[b]) * 0.5), mid)
            w = min(s * k, 0.25 * math.hypot(xy[b][0] - xy[a][0], xy[b][1] - xy[a][1]))
            if not w > 0.0:
                continue
            widths[(a, b)] = w
            incident.setdefault(a, []).append((a, b))
            incident.setdefault(b, []).append((a, b))
        return (widths, incident, xy) if widths else None

    # ------------------------------------------------------------------ output
    def emit(
        self, body_k: int, fid: int, S, o: int, dom: _Dom, tris, wind: int | None = None, poly: float = 0.0
    ) -> None:
        """Add a face's triangles: ``o`` is the side its normals point to, ``wind`` the way
        round its triangles go (``o`` unless the face is thin and its ring runs back).
        ``poly``, twice the area of the face's (u, v) polygon (0: not checked), is what the
        triangles' absolute (u, v) areas must add up to; a face whose triangles cover more
        than it, or that has triangles with area in space but none in (u, v), folds over
        itself (``checks["faces_folded"]``)."""
        P = self.pts.p
        pid, u, v = dom.pid, dom.u, dom.v
        xy = dom.xy
        wind = o if wind is None else wind
        local: dict[int, int] = {}
        order: list[int] = []
        first: list[int] = []  # the (u, v) point each vertex was first met at, as order
        nrm: dict[int, tuple | None] = {}
        out: list[tuple[int, int, int]] = []
        acc: dict[int, list[float]] = {}
        area = False
        uv_cover = 0.0  # twice the triangles' absolute (u, v) area
        space = flap = 0.0  # twice their area in space, and of those with no (u, v) area
        # At a pole the surface's derivatives vanish (or, on a B-spline row collapsed to a
        # point, are rounding noise), so the normal there is the mean of the triangles'.
        on_pole = _pole_test(S)
        for a, b, c in tris:
            (ax, ay), (bx, by), (cx, cy) = xy[a], xy[b], xy[c]
            s2 = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
            uv_cover += abs(s2)
            ia, ib, ic = pid[a], pid[b], pid[c]
            if ia == ib or ib == ic or ia == ic:
                continue  # a triangle on a pole line or a seam: one point twice
            if wind < 0:
                ib, ic = ic, ib
                b, c = c, b
            pa, pb, pc = P[ia], P[ib], P[ic]
            tn = cross(sub(pb, pa), sub(pc, pa))
            # A triangle of three points in a line has no area, but its edges are edges
            # of the face's other triangles and of the next face: it stays, or the solid
            # would open there.
            area = area or tn != (0.0, 0.0, 0.0)
            if poly:
                a2 = norm(tn)
                space += a2
                longest = max(
                    (bx - ax) ** 2 + (by - ay) ** 2,
                    (cx - bx) ** 2 + (cy - by) ** 2,
                    (ax - cx) ** 2 + (ay - cy) ** 2,
                )
                if abs(s2) <= 1e-9 * longest:
                    flap += a2  # three points in a line in (u, v), but not in space
            out.append((ia, ib, ic))
            for i, di in ((ia, a), (ib, b), (ic, c)):
                if i not in local:
                    local[i] = len(order)
                    order.append(i)
                    first.append(di)
                if nrm.get(i) is None:
                    n = None if on_pole(v[di]) else S.normal(u[di], v[di])
                    nrm[i] = None if n is None else (n[0] * o, n[1] * o, n[2] * o)
                if nrm[i] is None:
                    s = acc.setdefault(i, [0.0, 0.0, 0.0])
                    s[0] += tn[0]
                    s[1] += tn[1]
                    s[2] += tn[2]
        if not area:
            raise FaceFailed("degenerate", "the face has no area")
        if self.mesh.n_triangles + len(out) > self.opts.max_triangles:
            self.truncated.append("max_triangles")
            raise _Stop
        m = self.mesh
        v0 = m.n_vertices
        t0 = m.n_triangles
        detail = self.opts.detail
        for i in order:
            p = P[i]
            m.positions.extend((p[0], p[1], p[2]))
            n = nrm.get(i)
            if n is None:
                s = acc.get(i, [0.0, 0.0, 0.0])
                ln = math.sqrt(s[0] * s[0] + s[1] * s[1] + s[2] * s[2]) or 1.0
                n = (s[0] / ln, s[1] / ln, s[2] / ln)
            m.normals.extend(n)
            if detail:
                self.detail_points.extend(p)
                self.detail_normals.extend(n)
        if detail:
            uv = array("d")
            for di in first:
                uv.append(u[di])
                uv.append(v[di])
            self.detail_uv.append(uv)
            missing = -1  # a sample that is no vertex of the face's triangles (a pole's)
            self.detail_edges.append(
                [
                    (key, array("i", [v0 + local[i] if i in local else missing for i in es.ids]))
                    for key, es in self._face_edges
                ]
            )
        for ia, ib, ic in out:
            m.triangles.extend((v0 + local[ia], v0 + local[ib], v0 + local[ic]))
            self.welded.extend((ia, ib, ic))
        m.faces.append(FaceTess(-1, v0, len(order), t0, len(out), (), True))
        self.face_ids.append((body_k, fid))
        self.counts["triangles"] += len(out)
        # A face whose (u, v) polygon is a sliver beside its area in space (a surface whose
        # (u, v) collapses there, such as a B-spline's degenerate row) is not judged: its
        # triangles have little (u, v) area whether they fold or not.
        if poly > FAITHFUL * space and (uv_cover - poly > FOLD * poly or flap > FOLD * space):
            self.checks["faces_folded"] += 1


def _spread(S, loop):
    """A loop's (u, v, point id) with each run of points that fell on one (u, v) point
    (boundary points whose nearest point of the surface is one point of its edge, an edge
    that stands off the surface there) spread evenly along the way to the next point:
    points of different ids at one place cannot be triangulated. A run at the loop's end,
    and points at a pole, are left as they are."""
    n = len(loop)
    if n < 3:
        return loop
    out = list(loop)
    k = 0
    while k < n:
        u, v, pid = out[k]
        j = k + 1
        while j < n and out[j][0] is not None and u is not None and out[j][0] == u and out[j][1] == v:
            j += 1
        if j - k > 1 and j < n and out[j][0] is not None:
            nu, nv = out[j][0], out[j][1]
            if S.pu is not None:
                nu = wrap_near(nu, u, S.pu)
            if S.pv is not None:
                nv = wrap_near(nv, v, S.pv)
            m = j - k
            for i in range(1, m):
                f = i / m
                out[k + i] = (u + (nu - u) * f, v + (nv - v) * f, out[k + i][2])
        k = max(j, k + 1)
    return out


def _within(S, u: float, v: float) -> bool:
    """Whether (u, v) lies within the surface's parameter range (a periodic direction has
    none)."""
    ur, vr = S.urange, S.vrange
    return (ur is None or ur[0] <= u <= ur[1]) and (vr is None or vr[0] <= v <= vr[1])


def _beyond(S, p, u: float, v: float) -> tuple[float, float]:
    """A boundary point the surface does not reach (its nearest point is on the edge of
    the surface's parameter range): its (u, v) carried past that edge by one step of
    Gauss-Newton, unclamped, along the coordinates that sit on the edge and only
    outward. Without it every such point of an edge lands on one (u, v) point there,
    and the face's polygon cannot be triangulated."""
    edges = []
    for k, rng in ((0, S.urange), (1, S.vrange)):
        w = (u, v)[k]
        if rng is not None and (w <= rng[0] or w >= rng[1]):
            edges.append((k, -1.0 if w <= rng[0] else 1.0))
    if not edges:
        return u, v
    q, su, sv = S.d1(u, v)
    r = sub(p, q)
    a, b, c = dot(su, su), dot(su, sv), dot(sv, sv)
    det = a * c - b * b
    if not det > 1e-24 * (a * c) or det == 0.0:
        return u, v
    g1, g2 = dot(r, su), dot(r, sv)
    step = ((c * g1 - b * g2) / det, (a * g2 - b * g1) / det)
    out = [u, v]
    ranges = (S.urange, S.vrange)
    for k, way in edges:
        lo, hi = ranges[k]
        # a step longer than BEYOND of the range is not taken: where the surface barely
        # moves at its edge (its derivative near nought) it runs off without end, and the
        # point stays on the edge
        if step[k] * way > 0.0 and abs(step[k]) <= BEYOND * (hi - lo):
            out[k] += step[k]
    return out[0], out[1]


def _without_spikes(topo, fins):
    """A loop's fins with every out-and-back pair taken out: a fin followed round the loop
    by a fin of the same edge running the other way encloses nothing (a seam run down
    to a pole and back up, a slit), and kept, it is a polygon side of no width whose
    samples the triangulation fans across (``docs/API.md`` 3.15). Pairs that meet once
    one between them is gone go too, round the loop's end as well."""
    if len(fins) < 2:
        return fins
    out: list[tuple] = []
    for fin in fins:
        edge = topo.ref(fin, "edge")
        key = (edge.index if edge is not None else None, topo.sense(fin))
        if out and key[0] is not None and out[-1][1][0] == key[0] and out[-1][1][1] != key[1]:
            out.pop()
        else:
            out.append((fin, key))
    i, j = 0, len(out) - 1  # round the loop's end: trimmed from both ends at once, not pop(0)
    while j - i >= 1 and out[i][1][0] is not None and out[i][1][0] == out[j][1][0]:
        if out[i][1][1] == out[j][1][1]:
            break
        i += 1
        j -= 1
    out = out[i : j + 1]
    if len(out) == len(fins):
        return fins
    return [fin for fin, _key in out]


def _side_from_loops(S, loops_uv) -> int:
    """The side of a face on a blend that does not close on itself: its outer loop runs
    counter-clockwise about its outward normal (``docs/FORMAT.md`` 10.8), and is the one
    of largest area in the approximation's (u, v), so the sign of that area is the side."""
    best = 0.0
    for lp in loops_uv:
        a = area(lp)
        if abs(a) > abs(best):
            best = a
    if best == 0.0:
        raise FitFailed("orientation_conflict", "a blend face whose loops enclose nothing")
    return 1 if best > 0.0 else -1


def _on_blend(topo, face) -> bool:
    try:
        s = topo.ref(face, "surface", SURFACE_TYPES)
    except FaceFailed:
        return False
    return s is not None and s.type == BLENDED_EDGE


def _pole_test(S):
    """A test of whether a (u, v) point with this v lies on one of the surface's pole
    lines (every pole line is ``v = const``)."""
    if not S.poles:
        return lambda v: False
    span = (S.vrange[1] - S.vrange[0]) if S.vrange else 1.0
    lines = [(pv, 1e-12 * (abs(pv) + abs(span) + 1e-300)) for pv, _q in S.poles]
    return lambda v: any(abs(v - pv) <= tol for pv, tol in lines)


def _longest2(a, b, c) -> float:
    def d2(p, q):
        return (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2

    return max(d2(a, b), d2(b, c), d2(c, a))


def _drop(dom: _Dom) -> None:
    dom.u.pop()
    dom.v.pop()
    dom.pid.pop()
    dom.xy.pop()


def _too_near(keep, verts, x: float, y: float) -> bool:
    """Whether (x, y) lies within the keep-off distance of a boundary edge at one of the
    points ``verts`` (those of the triangle it falls in)."""
    if keep is None:
        return False
    widths, incident, xy = keep
    for i in verts:
        for e in incident.get(i, ()):
            if _seg_dist(xy[e[0]], xy[e[1]], x, y) < widths[e]:
                return True
    return False


def _off_limits(keep, edges, x: float, y: float) -> bool:
    """Whether (x, y) lies within the keep-off distance of one of the boundary ``edges``
    (either way round)."""
    if keep is None or not edges:
        return False
    widths, _incident, xy = keep
    for a, b in edges:
        w = widths.get((a, b)) or widths.get((b, a))
        if w and _seg_dist(xy[a], xy[b], x, y) < w:
            return True
    return False


def _seg_dist(p, q, x: float, y: float) -> float:
    ax, ay = p
    dx, dy = q[0] - ax, q[1] - ay
    ll = dx * dx + dy * dy
    t = 0.0 if ll == 0.0 else min(1.0, max(0.0, ((x - ax) * dx + (y - ay) * dy) / ll))
    return math.hypot(x - ax - t * dx, y - ay - t * dy)


def _near_fixed(mesh: TriMesh, k: int, x: float, y: float, gap: float) -> bool:
    """Whether (x, y) lies within ``gap`` of a fixed edge of triangle ``k``."""
    tri = mesh.t[k]
    xy = mesh.xy
    for i, j in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
        if not mesh.is_fixed(i, j):
            continue
        ax, ay = xy[i]
        bx, by = xy[j]
        ll = math.hypot(bx - ax, by - ay)
        if ll == 0.0:
            continue
        if abs((bx - ax) * (y - ay) - (by - ay) * (x - ax)) / ll < gap:
            return True
    return False


def _closed(tris: array, ranges) -> tuple[bool, bool]:
    """``(balanced, strict)`` for the triangles in ``ranges`` (``(start, end)`` indices of
    ``tris``, one body's): every directed edge has its reverse as often; and, stricter,
    every one is used once and its reverse once (no edge used twice the same way, as
    triangles that fold over one another use them)."""
    edges: Counter = Counter()
    for first, end in ranges:
        for k in range(first, end, 3):
            a, b, c = tris[k], tris[k + 1], tris[k + 2]
            edges[(a, b)] += 1
            edges[(b, c)] += 1
            edges[(c, a)] += 1
    balanced = all(edges.get((b, a), 0) == n for (a, b), n in edges.items())
    return balanced, balanced and all(n == 1 for n in edges.values())


def welded_measures(points, tris: array) -> dict:
    """Volume, area, centroid and box of the triangles over ``points`` (doubles)."""
    vol = 0.0
    area = 0.0
    cx = cy = cz = 0.0
    used: set[int] = set()
    for k in range(0, len(tris), 3):
        a, b, c = points[tris[k]], points[tris[k + 1]], points[tris[k + 2]]
        used.update((tris[k], tris[k + 1], tris[k + 2]))
        v6 = dot(a, cross(b, c))
        vol += v6
        cx += v6 * (a[0] + b[0] + c[0])
        cy += v6 * (a[1] + b[1] + c[1])
        cz += v6 * (a[2] + b[2] + c[2])
        area += 0.5 * norm(cross(sub(b, a), sub(c, a)))
    vol /= 6.0
    centroid = (cx / (24.0 * vol), cy / (24.0 * vol), cz / (24.0 * vol)) if vol else None
    box = None
    if used:
        ps = [points[i] for i in used]
        box = (
            (min(p[0] for p in ps), min(p[1] for p in ps), min(p[2] for p in ps)),
            (max(p[0] for p in ps), max(p[1] for p in ps), max(p[2] for p in ps)),
        )
    return {"volume": vol, "area": area, "centroid": centroid, "box": box}
