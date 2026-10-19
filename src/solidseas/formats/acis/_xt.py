"""A small writer of Parasolid nodes into an in-memory transmit, for the ACIS reader.

It writes nodes in the base-schema layouts (SCH_13006, as
``solidseas.formats.solidworks.xt_schema`` holds them) with the topology
``solidseas.tessellate`` reads: a BODY (node 1) with one REGION and SHELL, FACEs
chained by ``next``, LOOPs of fins (HALFEDGEs) linked by ``forward`` and
``backward``, a fin's ``vertex`` its end vertex, and the fins of an edge partners
by ``other``. It follows ``tests/xt_bodies.XtBuilder`` (SolidSeas' own test
builder) with what an ACIS body needs besides: ellipses, B-spline curves,
trimmed curves, swept surfaces, tolerances and a bound on the nodes written. A
clock, when given, is ticked once a B-spline control point.

Interim: the design's shared B-rep builder (``solidseas.brep``) replaces this
module when it lands. Transmits built here are read by SolidSeas' tessellator;
they have not been loaded in a Parasolid kernel.
"""

import math

from ...errors import SldFormatError
from .._source import Clock
from ..limits import Limits
from ..solidworks import xt_schema as S
from ..solidworks.parasolid import NULL_DOUBLE, Node, SchemaInfo, XtTransmit

BODY, SHELL, FACE, LOOP, EDGE, HALFEDGE, VERTEX, REGION, POINT = 12, 13, 14, 15, 16, 17, 18, 19, 29
LINE, CIRCLE, ELLIPSE, PLANE, CYLINDER, CONE, SPHERE, TORUS, SWEPT = 30, 31, 32, 50, 51, 52, 53, 54, 67
BSPLINE_VERTICES, B_SURFACE, NURBS_SURF, KNOT_MULT, KNOT_SET = 45, 124, 126, 127, 128
TRIMMED_CURVE, B_CURVE, NURBS_CURVE = 133, 134, 136
BODY_TYPE = {"solid": 1, "wire": 2, "sheet": 3, "general": 6}
_HAS_ID = {t: {f[0] for f in lay} & {"node_id"} for t, lay in S.BASE.items()}


def _default(kind: str, n: int):
    one = {"p": 0, "d": 0, "n": 0, "u": 0, "l": 0, "t": 0, "c": "+", "f": NULL_DOUBLE, "v": (0.0, 0.0, 0.0)}
    if n == S.VAR:
        return [] if kind != "c" else ""
    if n == 1:
        return one.get(kind, 0)
    return [one.get(kind, 0)] * n


def _v(p) -> tuple[float, float, float]:
    out = (float(p[0]), float(p[1]), float(p[2]))
    if not all(math.isfinite(x) for x in out):
        raise SldFormatError("a coordinate is not a finite number")
    return out


def _f(x) -> float:
    x = float(x)
    if not math.isfinite(x):
        raise SldFormatError("a number is not finite")
    return x


class XtWriter:
    """Nodes of one body, numbered from 1 (the BODY) in the order they are made."""

    def __init__(self, limits: Limits, body_type: str = "solid", clock: Clock | None = None) -> None:
        self.limits = limits
        self.clock = clock
        self.nodes: dict[int, list] = {}
        self.k = 1
        self.faces: list[int] = []
        self.body = self.node(BODY, body_type=BODY_TYPE[body_type])
        self.region = self.node(REGION, body=self.body, type="S")
        self.shell = self.node(SHELL, body=self.body, region=self.region)
        self.update(self.body, region=self.region, shell=self.shell)
        self.update(self.region, shell=self.shell)

    # -- nodes ----------------------------------------------------------------------------
    def node(self, ntype: int, **fields) -> int:
        idx = self.k
        if idx > self.limits.brep_nodes:
            raise self.limits.exceeded(
                "brep_nodes", f"the body needs more than {self.limits.brep_nodes:,} nodes"
            )
        self.k += 1
        if "node_id" in _HAS_ID.get(ntype, ()):
            fields.setdefault("node_id", idx)
        self.nodes[idx] = [ntype, fields]
        return idx

    def update(self, idx: int, **fields) -> None:
        self.nodes[idx][1].update(fields)

    def set_body_type(self, body_type: str) -> None:
        self.update(self.body, body_type=BODY_TYPE[body_type])

    def transmit(self) -> XtTransmit:
        for a, b in zip(self.faces, self.faces[1:], strict=False):
            self.update(a, next=b)
        if self.faces:
            self.update(self.shell, face=self.faces[0])
        xt = XtTransmit()
        xt.modeller = ": TRANSMIT FILE created by SolidSeas from ACIS data"
        xt.schema = "SCH_1300000_13006"
        xt.base = 13006
        for idx, (ntype, fields) in self.nodes.items():
            lay = [tuple(f[:3]) for f in S.BASE[ntype]]
            xt.layouts.setdefault(ntype, lay)
            xt.schema_info.setdefault(ntype, SchemaInfo("base"))
            vals, count = [], None
            for name, kind, n in lay:
                v = fields[name] if name in fields else _default(kind, n)
                if n == S.VAR:
                    count = len(v)
                vals.append(v)
            xt.nodes.append(Node(ntype, idx, vals, count))
        return xt

    # -- geometry -------------------------------------------------------------------------
    def vertex(self, p, tolerance: float | None = None) -> int:
        pt = self.node(POINT, pvec=_v(p))
        tol = _f(tolerance) if tolerance is not None and tolerance > 0 else NULL_DOUBLE
        return self.node(VERTEX, point=pt, tolerance=tol)

    def plane(self, P, N, X, sense="+") -> int:
        return self.node(PLANE, pvec=_v(P), normal=_v(N), x_axis=_v(X), sense=sense)

    def cylinder(self, P, A, r, X, sense="+") -> int:
        return self.node(CYLINDER, pvec=_v(P), axis=_v(A), radius=_f(r), x_axis=_v(X), sense=sense)

    def cone(self, P, A, r, sin_a, cos_a, X, sense="+") -> int:
        return self.node(
            CONE,
            pvec=_v(P),
            axis=_v(A),
            radius=_f(r),
            sin_half_angle=_f(sin_a),
            cos_half_angle=_f(cos_a),
            x_axis=_v(X),
            sense=sense,
        )

    def sphere(self, C, r, A, X, sense="+") -> int:
        return self.node(SPHERE, centre=_v(C), radius=_f(r), axis=_v(A), x_axis=_v(X), sense=sense)

    def torus(self, C, A, R, r, X, sense="+") -> int:
        return self.node(
            TORUS, centre=_v(C), axis=_v(A), major_radius=_f(R), minor_radius=_f(r), x_axis=_v(X), sense=sense
        )

    def swept(self, section: int, sweep, sense="+") -> int:
        return self.node(SWEPT, section=section, sweep=_v(sweep), scale=NULL_DOUBLE, sense=sense)

    def line(self, P, D, sense="+") -> int:
        return self.node(LINE, pvec=_v(P), direction=_v(D), sense=sense)

    def circle(self, C, N, X, r, sense="+") -> int:
        return self.node(CIRCLE, centre=_v(C), normal=_v(N), x_axis=_v(X), radius=_f(r), sense=sense)

    def ellipse(self, C, N, X, a, b, sense="+") -> int:
        return self.node(
            ELLIPSE,
            centre=_v(C),
            normal=_v(N),
            x_axis=_v(X),
            major_radius=_f(a),
            minor_radius=_f(b),
            sense=sense,
        )

    def trimmed(self, basis: int, p1, p2, t1: float, t2: float) -> int:
        return self.node(
            TRIMMED_CURVE,
            basis_curve=basis,
            point_1=_v(p1),
            point_2=_v(p2),
            parm_1=_f(t1),
            parm_2=_f(t2),
            sense="+",
        )

    def _knots(self, values, mults) -> tuple[int, int]:
        ks = self.node(KNOT_SET, knots=[_f(k) for k in values])
        km = self.node(KNOT_MULT, mult=[int(m) for m in mults])
        return ks, km

    def bspline_curve(self, degree, points, weights, knots, mults, *, closed=False, sense="+") -> int:
        """A B_CURVE: Cartesian ``points`` (3D), ``weights`` or None."""
        rational = weights is not None
        flat: list[float] = []
        clock = self.clock
        for k, p in enumerate(points):
            if clock is not None:
                clock.tick()
            if rational:
                w = _f(weights[k])
                flat.extend((_f(p[0]) * w, _f(p[1]) * w, _f(p[2]) * w, w))
            else:
                flat.extend(_v(p))
        verts = self.node(BSPLINE_VERTICES, vertices=flat)
        ks, km = self._knots(knots, mults)
        nc = self.node(
            NURBS_CURVE,
            degree=int(degree),
            n_vertices=len(points),
            vertex_dim=4 if rational else 3,
            n_knots=len(knots),
            knot_type=0,
            periodic=0,
            closed=1 if closed else 0,
            rational=1 if rational else 0,
            curve_form=0,
            bspline_vertices=verts,
            knot_mult=km,
            knots=ks,
        )
        return self.node(B_CURVE, nurbs=nc, sense=sense)

    def bspline_surface(
        self,
        du,
        dv,
        nu,
        nv,
        points,
        weights,
        uknots,
        umult,
        vknots,
        vmult,
        *,
        uclosed=False,
        vclosed=False,
        sense="+",
    ) -> int:
        """A B_SURFACE: ``points[i_u * nv + i_v]`` Cartesian (v varying fastest, as XT
        stores them), ``weights`` parallel or None."""
        rational = weights is not None
        flat: list[float] = []
        clock = self.clock
        for k, p in enumerate(points):
            if clock is not None:
                clock.tick()
            if rational:
                w = _f(weights[k])
                flat.extend((_f(p[0]) * w, _f(p[1]) * w, _f(p[2]) * w, w))
            else:
                flat.extend(_v(p))
        verts = self.node(BSPLINE_VERTICES, vertices=flat)
        uk, um = self._knots(uknots, umult)
        vk, vm = self._knots(vknots, vmult)
        ns = self.node(
            NURBS_SURF,
            u_periodic=0,
            v_periodic=0,
            u_degree=int(du),
            v_degree=int(dv),
            n_u_vertices=nu,
            n_v_vertices=nv,
            n_u_knots=len(uknots),
            n_v_knots=len(vknots),
            rational=1 if rational else 0,
            u_closed=1 if uclosed else 0,
            v_closed=1 if vclosed else 0,
            vertex_dim=4 if rational else 3,
            bspline_vertices=verts,
            u_knot_mult=um,
            v_knot_mult=vm,
            u_knots=uk,
            v_knots=vk,
        )
        return self.node(B_SURFACE, nurbs=ns, sense=sense)

    # -- topology -------------------------------------------------------------------------
    def edge(self, curve: int, tolerance: float | None = None) -> int:
        tol = _f(tolerance) if tolerance is not None and tolerance > 0 else NULL_DOUBLE
        return self.node(EDGE, curve=curve, tolerance=tol)

    def face(self, surface: int, sense: str) -> int:
        f = self.node(FACE, surface=surface, sense=sense, shell=self.shell)
        self.faces.append(f)
        return f

    def loop(self, face: int, fins: list[tuple[int, str, int]]) -> int:
        """A loop of ``face``: ``(edge, fin sense, end vertex or 0)`` in order round it.
        Returns the loop; the fins are reachable from it."""
        lp = self.node(LOOP, face=face)
        ids = [self.node(HALFEDGE, loop=lp, edge=e, sense=s, vertex=v) for e, s, v in fins]
        for a, b in zip(ids, ids[1:] + ids[:1], strict=True):
            self.update(a, forward=b)
            self.update(b, backward=a)
        if ids:
            self.update(lp, halfedge=ids[0])
        fields = self.nodes[face][1]
        if "loop" in fields:  # append to the face's chain of loops
            last = fields["loop"]
            while "next" in self.nodes[last][1]:
                last = self.nodes[last][1]["next"]
            self.update(last, next=lp)
        else:
            self.update(face, loop=lp)
        return lp

    def fins_of(self, loop: int) -> list[int]:
        first = self.nodes[loop][1].get("halfedge")
        out = []
        f = first
        while f and (not out or f != first):
            out.append(f)
            f = self.nodes[f][1].get("forward")
        return out

    def pair(self, fins: list[int]) -> None:
        """Make the fins of one edge partners (a ring by ``other``) and the first the edge's."""
        if not fins:
            return
        edge = self.nodes[fins[0]][1]["edge"]
        self.update(edge, halfedge=fins[0])
        if len(fins) > 1:
            for a, b in zip(fins, fins[1:] + fins[:1], strict=True):
                self.update(a, other=b)


__all__ = ["XtWriter"]
