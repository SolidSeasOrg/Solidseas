# Parasolid bodies to STEP entities: the topology walk and the exact mappings.
#
# Derived work. The walk of a body (regions, shells, faces, loops, fins, edges and
# vertices) and the mapping of each Parasolid curve and surface class to its STEP
# entity come from XtStepMapper in
#   BlinkingSun/sldprt2step, file sldprt2step_lib/step/mapper.py (convert_body,
#   convert_shell, convert_face, fin_ring, vertex, synthetic_vertex, edge_curve,
#   curve, nurbs_curve, nurbs_surface, surface, _surface, _curve_param_evaluator)
#   https://github.com/BlinkingSun/sldprt2step, commit fa954124f4f126e0c465c8f96454978ac80b812e
#   Licensed under the Apache License, Version 2.0. sldprt2step is a port of
#   open-sld-to-step 0.1.0 (Apache-2.0). See NOTICE in the SolidSeas repository.
# Modified for SolidSeas (2026-10-03): rewritten to read SolidSeas' own transmits by
# field name through solidseas.tessellate.topology.Topology rather than a second
# reader; corrected where the export's measurements showed upstream wrong (the
# lemon torus's orientation, the SPUN_SURF's swapped parameters, the outer loop of a
# face found by orientation rather than by extent, negative cone half angles, a
# tolerant edge's curve taken from either fin, VECTOR magnitudes, knots kept); faces
# without loops, sheets and voids handled; every refusal carries a reason code; the
# vertex cache is per mapper (upstream shared it between mappers); a ring edge on a
# trimmed curve that does not go round it refused (2026-10-04).
"""Map one Parasolid body to STEP entities (:mod:`.entities`).

The walk follows ``docs/FORMAT.md`` 10.8: a solid's faces are its solid regions'
shells' ``face`` chains (a face held through ``front_face`` by a solid region is
refused), a face's outward normal is its surface's natural normal times the
surface's sense times the face's sense, an edge runs from ``Topology.edge_ends``
start to end, in its curve's natural direction times the curve's sense, and a fin
runs along its edge when its own sense is '+'.

Everything a body holds is one of three tiers: written exactly, approximated by a
B-spline whose deviation is measured (:mod:`.approx`), or not representable, which
raises :class:`Refused` with a reason code from :data:`REASONS`. A body is
either written whole or not at all.
"""

import math
from collections import Counter
from types import SimpleNamespace

from ..formats.solidworks.parasolid import BODY_TYPES, Node, XtTransmit
from ..tessellate import nurbs
from ..tessellate._vec import add, dist, dot, mul, norm
from ..tessellate.curves import bspline_of
from ..tessellate.edges import EdgeSampler
from ..tessellate.surfaces import Geometry
from ..tessellate.topology import (
    B_CURVE,
    B_SURFACE,
    BLEND_BOUND,
    BLENDED_EDGE,
    BSPLINE_VERTICES,
    CIRCLE,
    CONE,
    CYLINDER,
    EDGE,
    ELLIPSE,
    FACE,
    INTERSECTION,
    KNOT_MULT,
    KNOT_SET,
    LINE,
    NURBS_SURF,
    OFFSET_SURF,
    PLANE,
    REGION,
    SHELL,
    SP_CURVE,
    SPHERE,
    SPUN_SURF,
    SURFACE_TYPES,
    SWEPT_SURF,
    TORUS,
    TRIMMED_CURVE,
    VERTEX,
    Clock,
    FaceFailed,
    Topology,
)
from . import bspline
from . import entities as E
from . import part21 as p21

PE_CURVE, PE_SURF, MESH, POLYLINE = 130, 120, 201, 200

# Why a body cannot be written. An open set, like every enum of SolidSeas.
REASONS = {
    "foreign_geometry": "it holds foreign (PE) geometry, which only the system that made it can evaluate",
    "mesh_geometry": "it holds a mesh (facet) surface, which is not a B-rep surface",
    "unsupported_surface": "it holds a surface of a kind STEP cannot hold and SolidSeas cannot approximate",
    "unsupported_curve": "it holds a curve of a kind STEP cannot hold and SolidSeas cannot approximate",
    "front_face_in_solid": "a solid region holds a face by its front, which a STEP solid cannot",
    "non_manifold": "it is a general body, or an edge has more than two faces",
    "fit_failed": "an approximation stayed farther from the true geometry than allowed",
    "orientation_conflict": "an approximated curve runs against its edge",
    "bad_geometry": "its geometry holds values out of range",
    "bad_reference": "a pointer of its topology or geometry leads to the wrong kind of node",
    "check_failed": "what would be written failed the export's own checks",
    "approximation_refused": "it needs an approximation, and only exact geometry was asked for",
    "unsupported_body": "it is a wire body, which a STEP shape of solids and sheets does not hold",
}


# How often the conventions the export relies on were met, for measuring them
# (docs/FORMAT.md 10.9): counted as bodies are mapped, never read by the export.
FACTS: Counter = Counter()


class Refused(Exception):
    """A body cannot be written: ``reason`` (a key of :data:`REASONS`) and a sentence."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


_FROM_FACE_FAILED = {
    "bad_reference": "bad_reference",
    "unsupported_surface": "unsupported_surface",
    "unsupported_curve": "unsupported_curve",
}


def refused_from(exc: FaceFailed) -> Refused:
    return Refused(_FROM_FACE_FAILED.get(exc.reason, "bad_geometry"), str(exc))


class Options:
    """What the export asked for, for one body."""

    def __init__(
        self,
        *,
        exact_only: bool = False,
        fit_tolerance_m: float = 1e-7,
        max_deviation_m: float = 1e-6,
        sheets: bool = False,
        split_seams: bool = True,
        include_hidden: bool = False,
    ) -> None:
        self.exact_only = exact_only
        self.fit_tolerance_m = fit_tolerance_m
        self.max_deviation_m = max_deviation_m
        self.sheets = sheets
        self.split_seams = split_seams  # cut faces round a closed surface at their seams (.split)
        self.include_hidden = include_hidden  # write bodies SOLIDWORKS hides too


class SurfaceMap:
    """A Parasolid surface as written: the item, whether the STEP surface's natural
    normal is Parasolid's (``match``), and the deviation of an approximation (None:
    exact)."""

    __slots__ = ("item", "match", "deviation", "cls")

    def __init__(self, item, match: bool, deviation: float | None = None, cls: str = "") -> None:
        self.item, self.match, self.deviation, self.cls = item, match, deviation, cls


class CurveMap:
    """A Parasolid curve as written for one edge: the item, whether the edge's traversal
    of the source curve runs with the item's parameter (``forward``), the deviation of
    an approximation (None: exact), the class approximated, and the point a ring edge's
    vertex goes at (metres)."""

    __slots__ = ("item", "forward", "deviation", "cls", "ring_point")

    def __init__(self, item, forward: bool, deviation=None, cls: str = "", ring_point=None) -> None:
        self.item, self.forward, self.deviation, self.cls, self.ring_point = (
            item,
            forward,
            deviation,
            cls,
            ring_point,
        )


class _Points:
    """The store EdgeSampler adds its points to."""

    def __init__(self) -> None:
        self.p: list = []

    def add(self, p, tol: float = 0.0) -> int:
        self.p.append(p)
        return len(self.p) - 1


class Mapped:
    """One body mapped: its ``items`` (solids, or a sheet's surface model), the faces with
    their source FACE node ids, counts, and what was approximated."""

    def __init__(self) -> None:
        self.items: list = []
        self.faces: list[E.Face] = []
        self.edges: list[E.Edge] = []
        self.edge_sources: list[tuple[E.Edge, int]] = []  # each edge and its EDGE node's index
        self.vertices: list[E.Vertex] = []
        self.approximated = Counter()  # source class -> faces and edges approximated
        self.approximated_faces = 0
        self.approximated_edges = 0
        self.max_deviation = 0.0
        self.max_tolerance = 0.0
        self.max_gap = 0.0  # the largest undeclared gap of the source the checks accepted
        self.tolerant = 0  # edges and vertices with a tolerance of their own
        self.outer_unknown = 0  # faces with several loops none of which is clearly outer
        self.seams = 0  # faces without loops, given a seam
        self.split_faces = 0  # faces round a closed surface written as two (.split)
        self.edges_added = 0  # edges the cuts added: seams, and the extra pieces of cut edges
        # each piece of a cut edge, and its EDGE node's index
        self.piece_sources: list[tuple[E.Edge, int]] = []


def body_name(xt: XtTransmit, topo: Topology, body: Node) -> str | None:
    """The body name SOLIDWORKS gives the body: its ``SWIMPLICITBODYNAME_ID_U``
    attribute's text (``docs/FORMAT.md`` 10.9), or None."""
    try:
        defs: dict[int, str] = {}
        for n in xt.nodes:
            if n.type == 80:  # ATTRIB_DEF
                ident = topo.ref(n, "identifier")
                if ident is None:
                    continue
                s = topo.get(ident, "string", None)
                if isinstance(s, list):
                    s = "".join(x if isinstance(x, str) else chr(x) for x in s)
                if isinstance(s, str):
                    defs[n.index] = s
        want = {i for i, s in defs.items() if s == "SWIMPLICITBODYNAME_ID_U"}
        if not want:
            return None
        for n in xt.nodes:
            if n.type != 81:  # ATTRIBUTE
                continue
            if topo.get(n, "definition", 0) not in want or topo.get(n, "owner", 0) != body.index:
                continue
            fields = topo.get(n, "fields", [])
            if not isinstance(fields, list) or not fields:
                continue
            values = topo.nodes.get(fields[0])
            if values is None:
                continue
            v = topo.get(values, "values", None)
            if isinstance(v, list):
                text = "".join(chr(c) if isinstance(c, int) and 0 < c < 0x110000 else "" for c in v)
            elif isinstance(v, str):
                text = v
            else:
                continue
            text = "".join(ch for ch in text if ch.isprintable())
            return text or None
    except (FaceFailed, ValueError, TypeError):
        return None
    return None


class BodyMapper:
    """Maps one BODY of a transmit. ``clock`` bounds the time (``TimeUp``)."""

    def __init__(
        self, xt: XtTransmit, body: Node, options: Options, clock: Clock, topo: Topology | None = None
    ):
        self.xt = xt
        self.topo = topo or Topology(xt)
        self.geom = Geometry(self.topo, 1e-7)
        self.body = body
        self.opts = options
        self.clock = clock
        self.surfaces: dict[int, SurfaceMap | Refused] = {}
        self.free_curves: dict[int, object] = {}
        self.vertices: dict[int, E.Vertex] = {}
        self.edges: dict[int, E.Edge] = {}
        self.edge_nodes: dict[int, Node] = {}  # id(Edge item) -> its EDGE node
        self.out = Mapped()
        self._points = _Points()
        self.sampler = EdgeSampler(
            self.topo,
            self.geom,
            self._points,
            # The writer's checks want the curve sampled as it is, corners and all: a check
            # that cannot pass refuses the part rather than writing it loose
            # (``tessellate.edges.EdgeSampler._adaptive``).
            SimpleNamespace(chord=1.0, angle=math.pi / 6, max_edge_points=4096, corners=False),
            clock,
        )
        self.approx = None  # the approximations, made when first needed
        self.current_edge: tuple[Node, bool] | None = None

    # ------------------------------------------------------------------ helpers
    def tick(self, k: int = 1) -> None:
        self.clock.tick(k)

    def chain(self, node: Node, head: str, nxt: str, types) -> list[Node]:
        out: list[Node] = []
        seen: set[int] = set()
        n = self.topo.ref(node, head, types)
        while n is not None:
            if n.index in seen:
                raise Refused("bad_reference", f"a {n.tname} chain loops")
            seen.add(n.index)
            out.append(n)
            if len(out) > self.topo.limit:
                raise Refused("bad_reference", f"a {n.tname} chain is too long")
            n = self.topo.ref(n, nxt, types)
        return out

    def note_approximation(self, cls: str, deviation: float, what: str) -> None:
        if self.opts.exact_only:
            raise Refused("approximation_refused", f"its {cls} {what} would have to be approximated")
        if deviation > self.opts.max_deviation_m:
            raise Refused(
                "fit_failed",
                f"an approximation of its {cls} {what} stays {deviation:.3g} m from it, more than the "
                f"{self.opts.max_deviation_m:g} m allowed",
            )
        self.out.approximated[cls] += 1
        self.out.max_deviation = max(self.out.max_deviation, deviation)

    def approximations(self):
        if self.approx is None:
            from .approx import Approximator

            self.approx = Approximator(self)
        return self.approx

    # ------------------------------------------------------------------ bodies
    def run(self, name: str) -> Mapped:
        try:
            return self._run(name)
        except FaceFailed as exc:
            raise refused_from(exc) from None
        except (ValueError, ZeroDivisionError, OverflowError) as exc:
            raise Refused("bad_geometry", str(exc) or type(exc).__name__) from None
        except (IndexError, KeyError, TypeError, AttributeError, RecursionError) as exc:
            # A damaged or crafted body that the checked walks above did not catch: refused
            # with the error's kind, never let out as a crash of the export.
            raise Refused("bad_reference", f"the body could not be read ({type(exc).__name__})") from None

    def _run(self, name: str) -> Mapped:
        topo = self.topo
        code = topo.get(self.body, "body_type", 0)
        kind = BODY_TYPES.get(code, "unknown") if isinstance(code, int) else "unknown"
        if kind == "solid":
            self.out.items = self.solids(name)
        elif kind == "sheet":
            self.out.items = [self.sheet(name)]
        elif kind == "general":
            raise Refused("non_manifold", "it is a general body (non-manifold)")
        else:
            raise Refused("bad_reference", f"a body of type {code!r}")
        return self.out

    def solids(self, name: str) -> list[E.Solid]:
        topo = self.topo
        out: list[E.Solid] = []
        for region in self.chain(self.body, "region", "next", (REGION,)):
            if topo.get(region, "type", "V") != "S":
                continue
            shells = []
            for sh in self.chain(region, "shell", "next", (SHELL,)):
                if topo.ref(sh, "front_face", (FACE,)) is not None:
                    raise Refused("front_face_in_solid", "a solid region's shell holds a face by its front")
                faces = self.chain(sh, "face", "next", (FACE,))
                if not faces:
                    raise Refused(
                        "non_manifold", "a shell of a solid region has no face (a wire or acorn shell)"
                    )
                items = [self.face(f) for f in faces]
                shells.append((E.Shell(items, True), self.shell_box(items)))
            if not shells:
                continue
            # The outer shell is the one whose box holds every other's: the largest.
            shells.sort(key=lambda s: -_diagonal(s[1]))
            label = name if not out else f"{name}_{len(out) + 1}"
            out.append(E.Solid(label, shells[0][0], [s for s, _b in shells[1:]]))
        if not out:
            raise Refused("bad_reference", "a solid body with no solid region")
        return out

    def sheet(self, name: str) -> E.SurfaceModel:
        """A sheet body's faces as shells: each set of faces joined by edges is one
        shell, closed when every edge of it is used twice."""
        faces = self.topo.faces(self.body)
        if not faces:
            raise Refused("bad_reference", "a sheet body with no face")
        items = [self.face(f) for f in faces]
        groups = _connected(items)
        shells = []
        for g in groups:
            uses = Counter(
                e for f in g for loop, _o in f.bounds if isinstance(loop, E.EdgeLoop) for e, _ in loop.edges
            )
            closed = bool(uses) and all(n == 2 for n in uses.values())
            shells.append(E.Shell(g, closed))
        return E.SurfaceModel(name, shells)

    def shell_box(self, faces: list[E.Face]):
        lo = [math.inf] * 3
        hi = [-math.inf] * 3
        for f in faces:
            pts = [v.point for loop, _o in f.bounds for v in _loop_vertices(loop)]
            if f.extent:
                pts = pts + list(f.extent)
            for p in pts:
                for k in range(3):
                    lo[k] = min(lo[k], p[k])
                    hi[k] = max(hi[k], p[k])
        return lo, hi

    # ------------------------------------------------------------------ faces
    def face(self, f: Node) -> E.Face:
        self.tick()
        topo = self.topo
        snode = topo.ref(f, "surface", required=True)
        sm = self.surface(snode)
        if sm.match is None:  # a blend: its side from the faces it meets
            same = self.approximations().blends.same_sense(f, snode)
        else:
            same = (topo.sense(f) == topo.sense(snode)) == sm.match
        loops = topo.loops(f)
        nid = topo.get(f, "node_id", -1)
        if not loops:
            from .seams import seam_bounds

            bounds, extent = seam_bounds(self, snode, sm)
            face = E.Face(bounds, sm.item, same, nid, sm.deviation is not None, extent, sm.deviation or 0.0)
            self.out.seams += 1
        else:
            built = [self.loop(lp) for lp in loops]
            if len(built) == 1:
                bounds = [(built[0], True)]
            else:
                outer = self.outer_loop(f, snode, loops, built)
                if outer is None:
                    self.out.outer_unknown += 1
                bounds = [(b, i == outer) for i, b in enumerate(built)]
            face = E.Face(bounds, sm.item, same, nid, sm.deviation is not None, None, sm.deviation or 0.0)
        if sm.deviation is not None:
            self.out.approximated_faces += 1
        self.out.faces.append(face)
        return face

    def loop(self, lp: Node):
        topo = self.topo
        fins = topo.fins(lp)
        first_edge = topo.ref(fins[0], "edge", (EDGE,))
        if first_edge is None:
            if len(fins) != 1:
                raise Refused("bad_reference", "a loop mixes a fin without an edge with others")
            vx = topo.ref(fins[0], "vertex", (VERTEX,))
            if vx is None:
                raise Refused("bad_reference", "an isolated loop has no vertex")
            return E.VertexLoop(self.vertex(vx))
        edges = []
        for fin in fins:
            self.tick()
            e = topo.ref(fin, "edge", (EDGE,))
            if e is None:
                raise Refused("bad_reference", "a loop mixes a fin without an edge with others")
            edges.append((self.edge(e), topo.sense(fin) > 0))
        return E.EdgeLoop(edges)

    def outer_loop(self, f: Node, snode: Node, loops: list[Node], built) -> int | None:
        """The index of the one loop that runs counter-clockwise about a planar face's
        outward normal (``docs/FORMAT.md`` 10.8), or None (not planar, or not one)."""
        if snode.type != PLANE:
            return None
        topo = self.topo
        n = topo.unit(snode, "normal")
        s = topo.sense(snode) * topo.sense(f)
        normal = mul(n, s)
        positive = []
        for i, lp in enumerate(loops):
            if isinstance(built[i], E.VertexLoop):
                continue
            pts = self.loop_points(lp)
            if pts is None:
                return None
            area = _newell(pts)
            if dot(area, normal) > 0.0:
                positive.append(i)
        return positive[0] if len(positive) == 1 else None

    def loop_points(self, lp: Node):
        """Points round a loop in its order, from the edges' samples; None when an edge
        cannot be sampled."""
        topo = self.topo
        out = []
        for fin in topo.fins(lp):
            e = topo.ref(fin, "edge", (EDGE,))
            if e is None:
                return None
            try:
                sm = self.sampler.samples(e)
            except FaceFailed:
                return None
            pts = [self._points.p[i] for i in sm.ids]
            if topo.sense(fin) < 0:
                pts.reverse()
            out.extend(pts[:-1] if len(pts) > 1 else pts)
        return out

    # ------------------------------------------------------------------ vertices and edges
    def vertex(self, vx: Node) -> E.Vertex:
        got = self.vertices.get(vx.index)
        if got is None:
            p = self.topo.point_of(vx)
            tol = self.topo.tolerance(vx)
            if tol:
                self.out.tolerant += 1
                self.out.max_tolerance = max(self.out.max_tolerance, tol)
            got = self.vertices[vx.index] = E.Vertex(E.point_mm(p), tol, self.topo.get(vx, "node_id", -1))
            self.out.vertices.append(got)
        return got

    def edge(self, e: Node) -> E.Edge:
        got = self.edges.get(e.index)
        if got is not None:
            return got
        topo = self.topo
        fins = topo.edge_fins(e)
        if len(fins) > 2:
            raise Refused("non_manifold", "an edge has more than two faces")
        sv, ev = topo.edge_ends(e)
        if (sv is None) != (ev is None):
            raise Refused("bad_reference", "an edge with one vertex missing")
        ring = sv is None
        node = topo.ref(e, "curve")
        reverse = False
        if node is None:  # a tolerant edge: its fins carry its curve (FORMAT 10.8)
            node, reverse = self.fin_curve(fins)
        ps = topo.point_of(sv) if sv is not None else None
        pe = topo.point_of(ev) if ev is not None else None
        a, b = (pe, ps) if reverse else (ps, pe)
        self.current_edge = (e, reverse)  # for an approximation, which samples the source edge
        cm = self.edge_curve(node, a, b, ring)
        tol = topo.tolerance(e)
        if tol:
            self.out.tolerant += 1
            self.out.max_tolerance = max(self.out.max_tolerance, tol)
        if ring:
            if cm.ring_point is None:
                raise Refused("bad_geometry", "a ring edge on a curve that does not close")
            start = end = E.Vertex(E.point_mm(cm.ring_point), tol, -1)
            self.out.vertices.append(start)
        else:
            start, end = self.vertex(sv), self.vertex(ev)
        item = E.Edge(
            start, end, cm.item, cm.forward != reverse, tol, cm.deviation or 0.0, topo.get(e, "node_id", -1)
        )
        if cm.deviation is not None:
            self.out.approximated_edges += 1
        self.edges[e.index] = item
        self.edge_nodes[id(item)] = e
        self.out.edges.append(item)
        self.out.edge_sources.append((item, e.index))
        return item

    def fin_curve(self, fins: list[Node]) -> tuple[Node, bool]:
        """A tolerant edge's curve: a fin's (trimmed) SP-curve, preferring one on a surface
        STEP holds exactly to one on a blend, and whether it runs against the edge."""
        topo = self.topo
        found = []
        for fin in fins:
            node = topo.ref(fin, "curve")
            if node is not None:
                found.append((node, topo.sense(fin) < 0))
        if not found:
            raise Refused("bad_reference", "an edge has no curve, and neither have its fins")

        def on_blend(node: Node) -> bool:
            n = node
            if n.type == TRIMMED_CURVE:
                n = topo.ref(n, "basis_curve") or n
            if n.type != SP_CURVE:
                return False
            s = topo.ref(n, "surface")
            return s is not None and s.type in (BLENDED_EDGE, BLEND_BOUND)

        found.sort(key=lambda c: on_blend(c[0]))
        return found[0]

    # ------------------------------------------------------------------ curves
    def free_curve(self, node: Node):
        """A curve written whole (a section, a profile, a trimmed curve's basis): its item,
        or raises :class:`Refused`. Cached a node."""
        got = self.free_curves.get(node.index)
        if got is None:
            got = self._free_curve(node)
            self.free_curves[node.index] = got
        return got

    def _free_curve(self, node: Node):
        topo = self.topo
        t = node.type
        if t == LINE:
            P = topo.vector(node, "pvec")
            D = topo.vector(node, "direction")
            n = norm(D)
            if not n > 1e-12:
                raise Refused("bad_geometry", "a line has no direction")
            return E.Line(E.point_mm(P), E.direction(D), p21.mm(n))
        if t == CIRCLE:
            r = topo.number(node, "radius")
            if not r > 0.0:
                raise Refused("bad_geometry", "a circle's radius is not positive")
            pl = E.Placement.make(
                topo.vector(node, "centre"), topo.unit(node, "normal"), topo.vector(node, "x_axis")
            )
            return E.Circle(pl, p21.mm(r))
        if t == ELLIPSE:
            a, b = topo.number(node, "major_radius"), topo.number(node, "minor_radius")
            if not (a > 0.0 and b > 0.0):
                raise Refused("bad_geometry", "an ellipse's radii are not positive")
            pl = E.Placement.make(
                topo.vector(node, "centre"), topo.unit(node, "normal"), topo.vector(node, "x_axis")
            )
            return E.Ellipse(pl, p21.mm(a), p21.mm(b))
        if t == B_CURVE:
            spline = self.bcurve(node)
            return E.BSplineCurve(bspline.clamped(spline))
        if t == TRIMMED_CURVE:
            basis = topo.ref(node, "basis_curve", required=True)
            if basis.type in (LINE, CIRCLE, ELLIPSE):
                return self.free_curve(basis)
            p1, p2 = topo.number(node, "parm_1"), topo.number(node, "parm_2")
            if basis.type == B_CURVE:
                return E.BSplineCurve(bspline.restricted(self.bcurve(basis), min(p1, p2), max(p1, p2)))
            return self.unmappable_curve(basis)
        return self.unmappable_curve(node)

    def unmappable_curve(self, node: Node):
        t = node.type
        if t == PE_CURVE:
            raise Refused("foreign_geometry", "a foreign (PE) curve")
        if t == POLYLINE:
            raise Refused("unsupported_curve", "a polyline")
        raise Refused("unsupported_curve", f"a {node.tname} where a curve written whole is needed")

    def bcurve(self, node: Node) -> nurbs.BSplineCurve:
        try:
            return bspline_of(self.topo, node, (3,))
        except FaceFailed as exc:
            if "dimension" in exc.detail:
                raise Refused(
                    "unsupported_curve", "a two-dimensional B-curve used as a curve in space"
                ) from None
            raise refused_from(exc) from None

    def edge_curve(self, node: Node, a, b, ring: bool) -> CurveMap:
        """The curve of an edge traversing ``node`` (its natural direction times its
        sense) from point ``a`` to point ``b`` (both None for a ring edge)."""
        topo = self.topo
        t = node.type
        sense = topo.sense(node) > 0
        if t in (LINE, CIRCLE, ELLIPSE):
            item = self.free_curve(node)
            if t == LINE:
                if ring:
                    raise Refused("bad_geometry", "a ring edge on a line")
                return CurveMap(item, sense)
            ring_point = None
            if ring:
                c, _z, x = item.placement.frame()
                semi = (item.radius if t == CIRCLE else item.semi1) / p21.SCALE
                ring_point = add(c, mul(x, semi))
            return CurveMap(item, sense, ring_point=ring_point)
        if t == B_CURVE:
            spline = self.bcurve(node)
            ev = self.geom.curve(node)
            if ring:
                if spline.period is None and not _closes(spline):
                    raise Refused("bad_geometry", "a ring edge on an open B-curve")
                c = bspline.clamped(spline)
                return CurveMap(E.BSplineCurve(c), sense, ring_point=c.point(c.lo))
            if spline.period is not None:
                lo, hi = self._range(ev, spline.period, a, b, sense)
                return CurveMap(E.BSplineCurve(bspline.restricted(spline, lo, hi)), sense)
            return CurveMap(self.free_curve(node), sense)
        if t == TRIMMED_CURVE:
            return self.trimmed(node, a, b, ring)
        if t == SP_CURVE:
            return self.sp_edge(node, None, a, b, ring, sense)
        if t == INTERSECTION:
            return self.approximations().intersection(node, a, b, ring, None)
        return self.unmappable_curve(node)

    def _range(self, ev, period, a, b, forward: bool) -> tuple[float, float]:
        """The parameter range of a source curve between points ``a`` and ``b``, traversed
        forward or backward, as (low, high)."""
        if period is None and dist(a, b) <= 1e-12 * (1.0 + norm(a)) and ev.lo is not None:
            return ev.lo, ev.hi  # an edge that closes on one vertex: the whole curve
        ta = ev.param(a, self.clock)
        tb = ev.param(b, self.clock)
        if forward:
            if period is not None and (tb <= ta or a == b):
                tb += period
            lo, hi = ta, tb
        else:
            if period is not None and (tb >= ta or a == b):
                tb -= period
            lo, hi = tb, ta
        if not hi > lo:
            raise Refused("bad_geometry", "an edge's vertices give it no length on its curve")
        return lo, hi

    def trimmed(self, node: Node, a, b, ring: bool) -> CurveMap:
        topo = self.topo
        basis = topo.ref(node, "basis_curve", required=True)
        p1, p2 = topo.number(node, "parm_1"), topo.number(node, "parm_2")
        if p1 == p2:
            raise Refused("bad_geometry", "a trimmed curve of no length")
        forward = (p2 > p1) == (topo.sense(node) > 0)
        lo, hi = min(p1, p2), max(p1, p2)
        point_1 = topo.vector(node, "point_1")
        bt = basis.type
        if bt in (LINE, CIRCLE, ELLIPSE):
            if bt == LINE and ring:
                raise Refused("bad_geometry", "a ring edge on a line")
            if ring:
                _ring_closes(self.geom.curve(basis).point, lo, hi)
            return CurveMap(self.free_curve(basis), forward, ring_point=point_1 if ring else None)
        if bt == B_CURVE:
            spline = self.bcurve(basis)
            _wrap_if_closed(spline, (lo, hi), spline.point)
            c = bspline.restricted(spline, lo, hi)
            if ring:
                _ring_closes(c.point, c.lo, c.hi)
            return CurveMap(E.BSplineCurve(c), forward, ring_point=c.point(c.lo) if ring else None)
        if bt == SP_CURVE:
            return self.sp_edge(basis, (lo, hi), a, b, ring, forward)
        if bt == INTERSECTION:
            return self.approximations().intersection(basis, a, b, ring, (p1, p2, topo.sense(node)))
        if bt == TRIMMED_CURVE:
            raise Refused("unsupported_curve", "a trimmed curve of a trimmed curve")
        return self.unmappable_curve(basis)

    def sp_edge(self, node: Node, rng, a, b, ring: bool, forward: bool) -> CurveMap:
        """An edge on an SP_CURVE (a curve in a surface's (u, v)): exact on a plane (the
        plane's affine map of its control points) and as an iso-parameter curve of an
        exactly written surface (:mod:`.iso`), approximated otherwise."""
        topo = self.topo
        snode = topo.ref(node, "surface", SURFACE_TYPES, required=True)
        bc = topo.ref(node, "b_curve", (B_CURVE,), required=True)
        try:
            c2 = bspline_of(topo, bc, (2,))
        except FaceFailed as exc:
            raise refused_from(exc) from None
        if rng is None and not ring:
            ev = self.geom.curve(node)
            rng = self._range(ev, c2.period, a, b, forward)
        if ring and rng is not None:
            _ring_closes(self.geom.curve(node).point, rng[0], rng[1])
        if rng is not None and c2.period is None and (rng[0] < c2.lo or rng[1] > c2.hi):
            # Trimmed across the end of a curve that closes on its surface: read it as
            # periodic, here and in the curve's own evaluator.
            ev = self.geom.curve(node)
            _wrap_if_closed(c2, rng, lambda t: ev.surface.point(*ev.surface.from_file(*c2.point(t))))
            ev.s.period = ev.period = c2.period
        if snode.type == PLANE:
            plane = self.geom.surface(snode)
            cps = []
            for c in c2.cps:
                if c2.rational:
                    w = c[2]
                    q = add(add(mul(plane.P, w), mul(plane.X, c[0])), mul(plane.Y, c[1]))
                    cps.append((q[0], q[1], q[2], w))
                else:
                    cps.append(add(add(plane.P, mul(plane.X, c[0])), mul(plane.Y, c[1])))
            spline = nurbs.BSplineCurve(c2.p, cps, list(c2.U), c2.rational, c2.period is not None)
            if ring:
                if c2.period is None and not _closes(spline):
                    raise Refused("bad_geometry", "a ring edge on an open SP-curve")
                c = bspline.clamped(spline)
            else:
                c = bspline.restricted(spline, rng[0], rng[1])
            return CurveMap(E.BSplineCurve(c), forward, ring_point=c.point(c.lo) if ring else None)
        from .iso import iso_edge

        got = iso_edge(self, node, snode, c2, rng, ring, forward)
        if got is not None:
            return got
        return self.approximations().sp_curve(node, snode, c2, rng, a, b, ring, forward)

    # ------------------------------------------------------------------ surfaces
    def surface(self, snode: Node) -> SurfaceMap:
        got = self.surfaces.get(snode.index)
        if got is None:
            try:
                got = self._surface(snode)
            except Refused as exc:
                got = exc
            except FaceFailed as exc:
                got = refused_from(exc)
            self.surfaces[snode.index] = got
        if isinstance(got, Refused):
            raise got
        return got

    def _surface(self, s: Node) -> SurfaceMap:
        topo = self.topo
        t = s.type
        if t == PLANE:
            return SurfaceMap(
                E.Plane(
                    E.Placement.make(topo.vector(s, "pvec"), topo.unit(s, "normal"), topo.vector(s, "x_axis"))
                ),
                True,
            )
        if t == CYLINDER:
            r = topo.number(s, "radius")
            if not r > 0.0:
                raise Refused("bad_geometry", "a cylinder's radius is not positive")
            pl = E.Placement.make(topo.vector(s, "pvec"), topo.unit(s, "axis"), topo.vector(s, "x_axis"))
            return SurfaceMap(E.Cylinder(pl, p21.mm(r)), True)
        if t == CONE:
            return self.cone(s)
        if t == SPHERE:
            r = topo.number(s, "radius")
            if not r > 0.0:
                raise Refused("bad_geometry", "a sphere's radius is not positive")
            pl = E.Placement.make(topo.vector(s, "centre"), topo.unit(s, "axis"), topo.vector(s, "x_axis"))
            return SurfaceMap(E.Sphere(pl, p21.mm(r)), True)
        if t == TORUS:
            return self.torus(s)
        if t == B_SURFACE:
            return SurfaceMap(E.BSplineSurface(bspline.clamped_surface(read_bsurface(topo, s))), True)
        if t == SWEPT_SURF:
            section = topo.ref(s, "section", required=True)
            curve = self.surface_curve(section, "swept surface's section")
            sweep = topo.vector(s, "sweep")
            n = norm(sweep)
            if not n > 1e-12:
                raise Refused("bad_geometry", "a swept surface has no sweep")
            return SurfaceMap(E.Extrusion(curve, E.direction(sweep), p21.mm(n)), True)
        if t == SPUN_SURF:
            profile = topo.ref(s, "profile", required=True)
            self.spun_covers_once(s, profile)
            curve = self.surface_curve(profile, "spun surface's profile")
            # SPUN_SURF is profile(u) turned by v; SURFACE_OF_REVOLUTION turns by u along
            # the profile's v: the parameters swap, and the natural normal turns round.
            return SurfaceMap(
                E.Revolution(curve, E.point_mm(topo.vector(s, "base")), E.direction(topo.unit(s, "axis"))),
                False,
            )
        if t == OFFSET_SURF:
            bnode = topo.ref(s, "surface", required=True)
            base = self.surface(bnode)
            off = topo.number(s, "offset")
            # Parasolid offsets along the base's natural normal times the base's sense;
            # STEP along the STEP basis's natural normal, which is Parasolid's when match.
            d = off * topo.sense(bnode) * (1.0 if base.match else -1.0)
            return SurfaceMap(E.Offset(base.item, p21.mm(d)), base.match, base.deviation, base.cls)
        if t == BLENDED_EDGE:
            return self.approximations().blend(s)
        if t == BLEND_BOUND:
            raise Refused("unsupported_surface", "a blend boundary surface carries a face")
        if t == PE_SURF:
            raise Refused("foreign_geometry", "a foreign (PE) surface")
        if t == MESH:
            raise Refused("mesh_geometry", "a mesh (facet) surface")
        raise Refused("unsupported_surface", f"a {s.tname} surface")

    def spun_covers_once(self, s: Node, profile: Node) -> None:
        """Refuse a spun surface that covers itself twice: a profile symmetric about the
        axis (a circle or an ellipse centred on it in a plane through it, a line across it
        at right angles) or one that crosses it (a B-curve), where each point of the
        surface has two parameters whose natural normals are opposite, so a STEP reader
        could take a face on it either way round."""
        topo = self.topo
        B, A = topo.vector(s, "base"), topo.unit(s, "axis")
        node = profile
        if node.type == TRIMMED_CURVE:
            node = topo.ref(node, "basis_curve", required=True)

        def off_axis(p) -> float:
            r = add(p, mul(B, -1.0))
            return norm(add(r, mul(A, -dot(r, A))))

        why = None
        if node.type in (CIRCLE, ELLIPSE):
            C, N = topo.vector(node, "centre"), topo.unit(node, "normal")
            if off_axis(C) <= 1e-7 and abs(dot(N, A)) <= 1e-6:
                X = topo.unit(node, "x_axis")
                if node.type == CIRCLE or abs(dot(X, A)) <= 1e-6 or abs(dot(X, A)) >= 1.0 - 1e-12:
                    why = "its profile is symmetric about the axis"
        elif node.type == LINE:
            P, D = topo.vector(node, "pvec"), topo.unit(node, "direction")
            if abs(dot(D, A)) <= 1e-9:  # at right angles: a plane, swept twice if it crosses
                h = dot(add(P, mul(B, -1.0)), A)
                foot = add(B, mul(A, h))
                r = add(P, mul(foot, -1.0))
                if norm(add(r, mul(D, -dot(r, D)))) <= 1e-7:
                    why = "its profile is a line across the axis at right angles"
        elif node.type == B_CURVE:
            spline = self.bcurve(node)
            pts = [spline.point(spline.lo + (spline.hi - spline.lo) * k / 256) for k in range(257)]
            radial = []
            for q in pts:
                r = add(q, mul(B, -1.0))
                radial.append(add(r, mul(A, -dot(r, A))))
            ref = max(radial, key=norm)
            if norm(ref) > 0.0:
                d0 = mul(ref, 1.0 / norm(ref))
                if min(dot(r, d0) for r in radial) < -1e-7:
                    why = "its profile crosses the axis"
        if why is not None:
            FACTS["spun_surface_covering_itself_twice"] += 1
            raise Refused(
                "unsupported_surface",
                f"a spun surface covers itself twice ({why}), so STEP cannot say which way its faces point",
            )

    def surface_curve(self, node: Node, what: str):
        """The curve a swept or spun surface is made from, written whole."""
        try:
            return self.free_curve(node)
        except Refused as exc:
            if exc.reason in ("unsupported_curve",):
                return self.approximations().free_curve(node, what)
            raise

    def cone(self, s: Node) -> SurfaceMap:
        topo = self.topo
        r = topo.number(s, "radius")
        sa, ca = topo.number(s, "sin_half_angle"), topo.number(s, "cos_half_angle")
        P, A, X = topo.vector(s, "pvec"), topo.unit(s, "axis"), topo.vector(s, "x_axis")
        if not r >= 0.0 or not ca > 1e-12:
            raise Refused("bad_geometry", "a cone's radius or half angle is out of range")
        half = math.atan2(sa, ca)
        if half == 0.0:
            if not r > 0.0:
                raise Refused("bad_geometry", "a cone of no angle and no radius")
            return SurfaceMap(E.Cylinder(E.Placement.make(P, A, X), p21.mm(r)), True)
        if half > 0.0:
            return SurfaceMap(E.Cone(E.Placement.make(P, A, X), p21.mm(r), p21.rounded(half)), True)
        # A negative half angle: the same cone about the reversed axis, read with u and v
        # both negated, which keeps the natural normal.
        return SurfaceMap(E.Cone(E.Placement.make(P, mul(A, -1.0), X), p21.mm(r), p21.rounded(-half)), True)

    def torus(self, s: Node) -> SurfaceMap:
        topo = self.topo
        C, A, X = topo.vector(s, "centre"), topo.unit(s, "axis"), topo.vector(s, "x_axis")
        R, r = topo.number(s, "major_radius"), topo.number(s, "minor_radius")
        if not r > 0.0 or not R > -r:
            raise Refused("bad_geometry", "a torus's radii are out of range")
        if R == 0.0:  # the torus about a point is the sphere, with the same parameters
            return SurfaceMap(E.Sphere(E.Placement.make(C, A, X), p21.mm(r)), True)
        if R > 0.0:
            outer = None if R >= r else True  # apple: the outer part of a torus meeting its axis
            return SurfaceMap(E.Torus(E.Placement.make(C, A, X), p21.mm(R), p21.mm(r), outer), True)
        # Lemon (R < 0): with x reversed and the major radius -R, the point (u, v) of
        # Parasolid's torus is the point (u, pi - v) of ISO's, whose natural normal is
        # therefore the reverse of Parasolid's.
        return SurfaceMap(E.Torus(E.Placement.make(C, A, mul(X, -1.0)), p21.mm(-R), p21.mm(r), False), False)


def read_bsurface(topo: Topology, node: Node) -> nurbs.BSplineSurface:
    """A B_SURFACE's spline as stored (not transposed, periodic flags as stored)."""
    ns = topo.ref(node, "nurbs", (NURBS_SURF,), required=True)
    get = topo.get
    pu, pv = get(ns, "u_degree"), get(ns, "v_degree")
    nu, nv = get(ns, "n_u_vertices"), get(ns, "n_v_vertices")
    dim = get(ns, "vertex_dim")
    rational = bool(get(ns, "rational", 0))
    for x in (pu, pv, nu, nv, dim):
        if not isinstance(x, int):
            raise Refused("bad_geometry", "a B-surface's sizes are not integers")
    if dim != (4 if rational else 3):
        raise Refused("bad_geometry", f"B-surface control points of {dim} values")
    if not (1 <= nu <= nurbs.MAX_CONTROL_POINTS and 1 <= nv <= nurbs.MAX_CONTROL_POINTS) or (
        nu * nv > nurbs.MAX_CONTROL_POINTS
    ):
        raise Refused("bad_geometry", f"{nu} x {nv} control points")
    U = nurbs.knot_vector(
        get(topo.ref(ns, "u_knots", (KNOT_SET,), required=True), "knots"),
        get(topo.ref(ns, "u_knot_mult", (KNOT_MULT,), required=True), "mult"),
        nu,
        pu,
    )
    V = nurbs.knot_vector(
        get(topo.ref(ns, "v_knots", (KNOT_SET,), required=True), "knots"),
        get(topo.ref(ns, "v_knot_mult", (KNOT_MULT,), required=True), "mult"),
        nv,
        pv,
    )
    cps = nurbs.control_points(
        get(topo.ref(ns, "bspline_vertices", (BSPLINE_VERTICES,), required=True), "vertices"),
        nu * nv,
        dim,
        rational,
    )
    rows = [cps[i * nv : (i + 1) * nv] for i in range(nu)]
    uper = bool(get(ns, "u_periodic", 0)) or bool(get(ns, "u_closed", 0))
    vper = bool(get(ns, "v_periodic", 0)) or bool(get(ns, "v_closed", 0))
    return nurbs.BSplineSurface(pu, pv, rows, U, V, rational, uper, vper)


def _wrap_if_closed(spline: nurbs.BSplineCurve, rng, point) -> None:
    """A trimmed range past either end of a curve's own range: when the curve closes
    (``point`` gives the same point at both ends), it is read as periodic; otherwise
    the range is refused."""
    lo, hi = spline.lo, spline.hi
    tol = 1e-12 * max(1.0, hi - lo)
    if spline.period is not None or (rng[0] >= lo - tol and rng[1] <= hi + tol):
        return
    a, b = point(lo), point(hi)
    if dist(a, b) > 1e-9 * (1.0 + norm(a)):
        raise Refused("bad_geometry", "a trimmed range runs past the end of a curve that does not close")
    spline.period = hi - lo
    FACTS["trimmed_past_the_end_of_a_closed_curve"] += 1


def _ring_closes(point, lo: float, hi: float) -> None:
    """Refuse a ring edge whose trimmed range does not go round a closed curve: its two
    ends must be one point, and its middle another."""
    a, b, m = point(lo), point(hi), point(0.5 * (lo + hi))
    tol = 1e-9 * (1.0 + norm(a))
    if dist(a, b) > tol or dist(a, m) <= tol:
        raise Refused("bad_geometry", "a ring edge on a trimmed curve that does not close")


def _closes(c: nurbs.BSplineCurve) -> bool:
    a, b = c.point(c.lo), c.point(c.hi)
    return dist(a, b) <= 1e-9 * (1.0 + norm(a))


def _diagonal(box) -> float:
    lo, hi = box
    if lo[0] > hi[0]:
        return 0.0
    return dist(lo, hi)


def _newell(pts):
    """Twice the area vector of a closed polygon."""
    x = y = z = 0.0
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        x += (a[1] - b[1]) * (a[2] + b[2])
        y += (a[2] - b[2]) * (a[0] + b[0])
        z += (a[0] - b[0]) * (a[1] + b[1])
    return (x, y, z)


def _loop_vertices(loop):
    if isinstance(loop, E.VertexLoop):
        return [loop.vertex]
    return [e.start for e, _o in loop.edges] + [e.end for e, _o in loop.edges]


def _connected(faces: list[E.Face]) -> list[list[E.Face]]:
    """Faces grouped by the edges they share, in their order."""
    parent = list(range(len(faces)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_edge: dict[int, int] = {}
    for i, f in enumerate(faces):
        for loop, _o in f.bounds:
            if not isinstance(loop, E.EdgeLoop):
                continue
            for e, _ in loop.edges:
                j = by_edge.setdefault(id(e), i)
                ra, rb = root(i), root(j)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
    groups: dict[int, list[E.Face]] = {}
    for i, f in enumerate(faces):
        groups.setdefault(root(i), []).append(f)
    return list(groups.values())


__all__ = ["REASONS", "BodyMapper", "Mapped", "Options", "Refused", "body_name", "read_bsurface"]
