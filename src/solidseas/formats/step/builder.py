"""A B-rep body built in memory as a Parasolid transmit (provisional).

:class:`BrepBuilder` writes nodes in the layouts of Parasolid's base schema
(SCH_13006, ``solidseas.formats.solidworks.xt_schema.BASE``) into an
:class:`~solidseas.formats.solidworks.parasolid.XtTransmit`, so that a body read
from another format is drawn by SolidSeas' own tessellator
(:func:`solidseas.tessellate.tessellate_transmit`) and can later be written as
``.x_t`` or ``.x_b`` with the existing writers. The topology is the one XT uses
(``docs/FORMAT.md`` 10.8): a BODY first (index 1), its REGIONs and SHELLs, FACEs
chained in each shell, LOOPs of fins (HALFEDGEs) linked by ``forward`` and
``backward``, a fin's ``vertex`` its end vertex, and the fins of an edge
partners by ``other``. An edge runs along its curve times the curve's
``sense``; a fin runs along its edge when its sense is ``+``.

Every value is in metres. Every number is checked finite, every direction is
normalised (and refused when it has no length), every axis pair made
perpendicular, and every node counted against ``Limits.brep_nodes``; a refusal
raises :class:`GeometryRefused`, which the caller turns into a face left out.

Written as the STEP reader's own module to the interface the design gives the
shared builder (``body``, ``region``, ``shell``, ``face``, ``loop``, ``edge``,
``vertex``, the geometry constructors and ``transmit``), so it can move to
``solidseas.brep`` unchanged. A transmit written from a builder has not been
loaded in a Parasolid kernel.
"""

import math
from collections.abc import Sequence
from typing import Any

from ...errors import SldFormatError
from ..limits import Limits
from ..solidworks import xt_schema as S
from ..solidworks.parasolid import NULL_DOUBLE, Node, SchemaInfo, XtTransmit

BODY, SHELL, FACE, LOOP, EDGE, HALFEDGE, VERTEX, REGION, POINT = 12, 13, 14, 15, 16, 17, 18, 19, 29
LINE, CIRCLE, ELLIPSE = 30, 31, 32
BSPLINE_VERTICES = 45
PLANE, CYLINDER, CONE, SPHERE, TORUS = 50, 51, 52, 53, 54
OFFSET_SURF, SWEPT_SURF, SPUN_SURF = 60, 67, 68
B_SURFACE, NURBS_SURF, KNOT_MULT, KNOT_SET = 124, 126, 127, 128
TRIMMED_CURVE, B_CURVE, NURBS_CURVE, SP_CURVE = 133, 134, 136, 137
CURVES = frozenset((LINE, CIRCLE, ELLIPSE, TRIMMED_CURVE, B_CURVE, SP_CURVE))
SURFACES = frozenset((PLANE, CYLINDER, CONE, SPHERE, TORUS, OFFSET_SURF, SWEPT_SURF, SPUN_SURF, B_SURFACE))
BODY_TYPE_CODES = {"solid": 1, "wire": 2, "sheet": 3, "general": 6}
MODELLER = ": TRANSMIT FILE created by modeller version 1300000"
SCHEMA = "SCH_1300000_13006_13006"
MAX_NODE_ID = (1 << 31) - 1
MAX_TYPES = 231  # the node type count the transmit header states, as SOLIDWORKS' own files do


class GeometryRefused(SldFormatError):
    """A value the builder cannot use: not finite, a direction of no length, axes that
    are parallel, a B-spline whose counts disagree. ``reason`` is a tessellation reason
    (``bad_geometry`` or ``non_finite``)."""

    def __init__(self, message: str, reason: str = "bad_geometry") -> None:
        super().__init__(message)
        self.reason = reason


Vec = tuple[float, float, float]


def _num(x: Any, what: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise GeometryRefused(f"{what} is not a number")
    x = float(x)
    if not math.isfinite(x):
        raise GeometryRefused(f"{what} is not finite", "non_finite")
    return x


def vec(v: Sequence[Any], what: str = "a point") -> Vec:
    if not isinstance(v, (tuple, list)) or len(v) != 3:
        raise GeometryRefused(f"{what} is not three numbers")
    return (_num(v[0], what), _num(v[1], what), _num(v[2], what))


def unit(v: Sequence[Any], what: str = "a direction") -> Vec:
    x, y, z = vec(v, what)
    n = math.sqrt(x * x + y * y + z * z)
    if not n > 1e-14 or not math.isfinite(n):
        raise GeometryRefused(f"{what} has no length")
    return (x / n, y / n, z / n)


def perpendicular(axis: Vec, ref: Vec | None) -> Vec:
    """``ref`` made perpendicular to the unit ``axis`` and normalised; with no ``ref`` (or one
    parallel to the axis), ISO 10303-42's default: x, or y when the axis is along x."""
    if ref is not None:
        d = ref[0] * axis[0] + ref[1] * axis[1] + ref[2] * axis[2]
        x = (ref[0] - d * axis[0], ref[1] - d * axis[1], ref[2] - d * axis[2])
        n = math.sqrt(x[0] * x[0] + x[1] * x[1] + x[2] * x[2])
        if n > 1e-9 * max(1.0, math.sqrt(ref[0] ** 2 + ref[1] ** 2 + ref[2] ** 2)):
            return (x[0] / n, x[1] / n, x[2] / n)
    v = (1.0, 0.0, 0.0) if abs(abs(axis[0]) - 1.0) > 1e-12 else (0.0, 1.0, 0.0)
    d = v[0] * axis[0] + v[1] * axis[1] + v[2] * axis[2]
    x = (v[0] - d * axis[0], v[1] - d * axis[1], v[2] - d * axis[2])
    n = math.sqrt(x[0] * x[0] + x[1] * x[1] + x[2] * x[2])
    return (x[0] / n, x[1] / n, x[2] / n)


def _default(kind: str, n: int) -> Any:
    one = {"p": 0, "d": 0, "n": 0, "u": 0, "l": 0, "t": 0, "c": "+", "f": NULL_DOUBLE, "v": (0.0, 0.0, 0.0)}
    if n == S.VAR:
        return [] if kind != "c" else ""
    if n == 1:
        return one.get(kind, 0)
    return [one.get(kind, 0)] * n


class BrepBuilder:
    """One body's nodes (see the module notes). Call :meth:`body` first, then build
    regions, shells, geometry, vertices, edges, faces and loops, then :meth:`transmit`."""

    def __init__(self, *, limits: Limits | None = None, clock: Any = None) -> None:
        self.limits = limits or Limits()
        self.clock = clock
        self.nodes: dict[int, tuple[int, dict[str, Any]]] = {}
        self.k = 1
        self._body: int | None = None
        self._last_region: int | None = None
        self._last_shell: dict[int, int] = {}  # region -> its last shell
        self._last_face: dict[int, int] = {}  # shell -> its last face
        self._last_loop: dict[int, int] = {}  # face -> its last loop
        self._edge_ends: dict[int, tuple[int, int]] = {}
        self._edge_fins: dict[int, list[int]] = {}
        self._curve_users: dict[int, int] = {}  # curve -> edges on it
        self.faces = 0

    # -- nodes ---------------------------------------------------------------------------
    def node(self, ntype: int, **fields: Any) -> int:
        idx = self.k
        if idx > self.limits.brep_nodes:
            raise self.limits.exceeded("brep_nodes", f"a body of more than {self.limits.brep_nodes:,} nodes")
        self.k += 1
        self.nodes[idx] = (ntype, fields)
        if self.clock is not None:
            self.clock.tick()
        return idx

    def set(self, idx: int, **fields: Any) -> None:
        self.nodes[idx][1].update(fields)

    def get(self, idx: int, name: str, default: Any = None) -> Any:
        return self.nodes[idx][1].get(name, default)

    def type_of(self, idx: int) -> int:
        return self.nodes[idx][0]

    # -- topology ------------------------------------------------------------------------
    def body(self, kind: str = "solid") -> int:
        if self._body is not None or self.nodes:
            raise ValueError("a builder holds one body, made first")
        code = BODY_TYPE_CODES.get(kind)
        if code is None:
            raise ValueError(f"unknown body type {kind!r}")
        self._body = self.node(BODY, body_type=code)
        return self._body

    def region(self, body: int, *, solid: bool = True) -> int:
        r = self.node(REGION, body=body, type="S" if solid else "V")
        if self._last_region is None:
            self.set(body, region=r)
        else:
            self.set(self._last_region, next=r)
            self.set(r, previous=self._last_region)
        self._last_region = r
        return r

    def shell(self, region: int) -> int:
        body = self.get(region, "body")
        s = self.node(SHELL, body=body, region=region)
        last = self._last_shell.get(region)
        if last is None:
            self.set(region, shell=s)
        else:
            self.set(last, next=s)
        self._last_shell[region] = s
        if not self.get(body, "shell"):
            self.set(body, shell=s)
        return s

    def vertex(self, point: Sequence[Any], tolerance: float | None = None) -> int:
        p = self.node(POINT, pvec=vec(point))
        tol = NULL_DOUBLE if tolerance is None else _num(tolerance, "a tolerance")
        v = self.node(VERTEX, point=p, tolerance=tol)
        self.set(p, owner=v)
        return v

    def point_of(self, vertex: int) -> Vec:
        return self.get(self.get(vertex, "point"), "pvec")

    def edge(
        self, curve: int, v0: int, v1: int, curve_sense: str = "+", tolerance: float | None = None
    ) -> int:
        """An edge on ``curve`` from vertex ``v0`` to ``v1`` (the same vertex for a closed
        edge), running along the curve when ``curve_sense`` is ``+``. A curve already
        used the other way round is copied, since the sense belongs to the curve node."""
        if self.type_of(curve) not in CURVES:
            raise ValueError("an edge needs a curve")
        if curve_sense not in ("+", "-"):
            raise ValueError("curve_sense is + or -")
        if self._curve_users.get(curve) and self.get(curve, "sense", "+") != curve_sense:
            ntype, fields = self.nodes[curve]
            curve = self.node(ntype, **{**fields, "sense": curve_sense})
        self.set(curve, sense=curve_sense)
        self._curve_users[curve] = self._curve_users.get(curve, 0) + 1
        tol = NULL_DOUBLE if tolerance is None else _num(tolerance, "a tolerance")
        e = self.node(EDGE, curve=curve, tolerance=tol)
        self._edge_ends[e] = (v0, v1)
        self._edge_fins[e] = []
        return e

    def face(self, shell: int, surface: int, sense: str = "+") -> int:
        if self.type_of(surface) not in SURFACES:
            raise ValueError("a face needs a surface")
        if sense not in ("+", "-"):
            raise ValueError("sense is + or -")
        f = self.node(FACE, shell=shell, surface=surface, sense=sense)
        last = self._last_face.get(shell)
        if last is None:
            self.set(shell, face=f)
        else:
            self.set(last, next=f)
            self.set(f, previous=last)
        self._last_face[shell] = f
        self.faces += 1
        return f

    def loop(self, face: int, fins: Sequence[tuple[int, str]], *, vertex: int | None = None) -> int:
        """A loop of ``face``: its fins as ``(edge, sense)`` in order round the loop (sense
        ``+`` when the fin runs along its edge), or, with no fins, the single ``vertex``
        of a vertex loop (an apex or a pole)."""
        lp = self.node(LOOP, face=face)
        last = self._last_loop.get(face)
        if last is None:
            self.set(face, loop=lp)
        else:
            self.set(last, next=lp)
        self._last_loop[face] = lp
        ids = []
        if not fins:
            if vertex is None:
                raise ValueError("a loop needs fins or a vertex")
            fin = self.node(HALFEDGE, loop=lp, vertex=vertex, sense="+")
            ids.append(fin)
        for e, s in fins:
            v0, v1 = self._edge_ends[e]
            fin = self.node(HALFEDGE, loop=lp, edge=e, sense=s, vertex=v1 if s == "+" else v0)
            self._edge_fins[e].append(fin)
            ids.append(fin)
        for a, b in zip(ids, ids[1:] + ids[:1], strict=True):
            self.set(a, forward=b)
            self.set(b, backward=a)
        self.set(lp, halfedge=ids[0])
        return lp

    # -- geometry: surfaces ------------------------------------------------------------------
    def plane(self, origin, normal, x_axis=None) -> int:
        n = unit(normal, "a plane's normal")
        x = perpendicular(n, None if x_axis is None else vec(x_axis, "an x axis"))
        return self.node(PLANE, pvec=vec(origin), normal=n, x_axis=x)

    def cylinder(self, origin, axis, radius, x_axis=None) -> int:
        a = unit(axis, "a cylinder's axis")
        r = _num(radius, "a radius")
        if not r > 0:
            raise GeometryRefused("a cylinder's radius is not positive")
        x = perpendicular(a, None if x_axis is None else vec(x_axis, "an x axis"))
        return self.node(CYLINDER, pvec=vec(origin), axis=a, radius=r, x_axis=x)

    def cone(self, origin, axis, radius, sin_half_angle, cos_half_angle, x_axis=None) -> int:
        a = unit(axis, "a cone's axis")
        r = _num(radius, "a radius")
        s, c = _num(sin_half_angle, "a half angle"), _num(cos_half_angle, "a half angle")
        if not r >= 0 or not c > 1e-12 or abs(math.hypot(s, c) - 1.0) > 1e-6:
            raise GeometryRefused("a cone's radius or half angle is out of range")
        x = perpendicular(a, None if x_axis is None else vec(x_axis, "an x axis"))
        return self.node(
            CONE, pvec=vec(origin), axis=a, radius=r, sin_half_angle=s, cos_half_angle=c, x_axis=x
        )

    def sphere(self, centre, radius, axis=(0.0, 0.0, 1.0), x_axis=None) -> int:
        a = unit(axis, "a sphere's axis")
        r = _num(radius, "a radius")
        if not r > 0:
            raise GeometryRefused("a sphere's radius is not positive")
        x = perpendicular(a, None if x_axis is None else vec(x_axis, "an x axis"))
        return self.node(SPHERE, centre=vec(centre), radius=r, axis=a, x_axis=x)

    def torus(self, centre, axis, major_radius, minor_radius, x_axis=None) -> int:
        a = unit(axis, "a torus's axis")
        big, small = _num(major_radius, "a radius"), _num(minor_radius, "a radius")
        if not small > 0 or not big > -small:
            raise GeometryRefused("a torus's radii are out of range")
        x = perpendicular(a, None if x_axis is None else vec(x_axis, "an x axis"))
        return self.node(TORUS, centre=vec(centre), axis=a, major_radius=big, minor_radius=small, x_axis=x)

    def bspline_surface(
        self,
        u_degree: int,
        v_degree: int,
        rows: Sequence[Sequence[Sequence[float]]],
        u_knots: Sequence[float],
        u_mults: Sequence[int],
        v_knots: Sequence[float],
        v_mults: Sequence[int],
        *,
        weights: Sequence[Sequence[float]] | None = None,
        u_closed: bool = False,
        v_closed: bool = False,
    ) -> int:
        """A B_SURFACE: ``rows[i][j]`` the Cartesian control point i along u and j along v,
        ``weights`` (the same shape) for a rational one; knots as distinct values and
        multiplicities, whose sum must be the control points plus the degree plus one."""
        nu = len(rows)
        nv = len(rows[0]) if nu else 0
        if not (nu and nv) or any(len(r) != nv for r in rows):
            raise GeometryRefused("a B-spline surface's control points are not a grid")
        uk, um = self._knots(u_knots, u_mults, nu, u_degree)
        vk, vm = self._knots(v_knots, v_mults, nv, v_degree)
        rational = weights is not None
        if rational and (len(weights) != nu or any(len(w) != nv for w in weights)):
            raise GeometryRefused("a B-spline surface's weights do not match its control points")
        flat: list[float] = []
        for i in range(nu):  # v varies fastest, as XT stores them
            if self.clock is not None:
                self.clock.tick(nv)
            for j in range(nv):
                x, y, z = vec(rows[i][j], "a control point")
                if rational:
                    w = _num(weights[i][j], "a weight")
                    if not w > 0:
                        raise GeometryRefused("a weight is not positive")
                    flat.extend((x * w, y * w, z * w, w))
                else:
                    flat.extend((x, y, z))
        verts = self.node(BSPLINE_VERTICES, vertices=flat)
        ukn = self.node(KNOT_SET, knots=uk)
        umn = self.node(KNOT_MULT, mult=um)
        vkn = self.node(KNOT_SET, knots=vk)
        vmn = self.node(KNOT_MULT, mult=vm)
        ns = self.node(
            NURBS_SURF,
            u_periodic=0,
            v_periodic=0,
            u_degree=u_degree,
            v_degree=v_degree,
            n_u_vertices=nu,
            n_v_vertices=nv,
            n_u_knots=len(uk),
            n_v_knots=len(vk),
            rational=1 if rational else 0,
            u_closed=1 if u_closed else 0,
            v_closed=1 if v_closed else 0,
            vertex_dim=4 if rational else 3,
            bspline_vertices=verts,
            u_knot_mult=umn,
            v_knot_mult=vmn,
            u_knots=ukn,
            v_knots=vkn,
        )
        return self.node(B_SURFACE, nurbs=ns)

    def _knots(self, knots, mults, n: int, degree: int) -> tuple[list[float], list[int]]:
        if isinstance(degree, bool) or not isinstance(degree, int) or not 1 <= degree <= 32:
            raise GeometryRefused("a B-spline degree is out of range")
        if len(knots) != len(mults) or not knots:
            raise GeometryRefused("knot values and multiplicities do not match")
        if len(knots) > self.limits.bspline_knots:
            raise self.limits.exceeded(
                "bspline_knots", f"a B-spline of more than {self.limits.bspline_knots:,} distinct knots"
            )
        kk = [_num(k, "a knot") for k in knots]
        mm = []
        for m in mults:
            if isinstance(m, bool) or not isinstance(m, int) or not 0 <= m <= degree + 1:
                raise GeometryRefused("a knot multiplicity is out of range")
            mm.append(m)
        if any(b < a for a, b in zip(kk, kk[1:], strict=False)):
            raise GeometryRefused("knot values decrease")
        if sum(mm) != n + degree + 1:
            raise GeometryRefused(f"{sum(mm)} knots for {n} control points of degree {degree}")
        return kk, mm

    def swept(self, section: int, sweep) -> int:
        if self.type_of(section) not in CURVES:
            raise ValueError("a swept surface needs a curve")
        w = vec(sweep, "a sweep")
        if not w[0] * w[0] + w[1] * w[1] + w[2] * w[2] > 1e-28:
            raise GeometryRefused("a swept surface has no sweep")
        return self.node(SWEPT_SURF, section=section, sweep=w, scale=NULL_DOUBLE)

    def spun(self, profile: int, origin, axis) -> int:
        if self.type_of(profile) not in CURVES:
            raise ValueError("a spun surface needs a curve")
        a = unit(axis, "a spun surface's axis")
        return self.node(SPUN_SURF, profile=profile, base=vec(origin), axis=a, x_axis=perpendicular(a, None))

    def offset(self, surface: int, distance: float) -> int:
        if self.type_of(surface) not in SURFACES:
            raise ValueError("an offset surface needs a surface")
        d = _num(distance, "an offset")
        return self.node(OFFSET_SURF, check="U", true_offset=1, surface=surface, offset=d, scale=NULL_DOUBLE)

    def reverse(self, surface: int) -> int:
        """A copy of ``surface`` whose own sense is ``-`` (its normal turned round)."""
        ntype, fields = self.nodes[surface]
        flipped = "-" if fields.get("sense", "+") == "+" else "+"
        return self.node(ntype, **{**fields, "sense": flipped})

    # -- geometry: curves --------------------------------------------------------------------
    def line(self, point, direction) -> int:
        return self.node(LINE, pvec=vec(point), direction=unit(direction, "a line's direction"))

    def circle(self, centre, normal, x_axis, radius) -> int:
        n = unit(normal, "a circle's normal")
        r = _num(radius, "a radius")
        if not r > 0:
            raise GeometryRefused("a circle's radius is not positive")
        x = perpendicular(n, None if x_axis is None else vec(x_axis, "an x axis"))
        return self.node(CIRCLE, centre=vec(centre), normal=n, x_axis=x, radius=r)

    def ellipse(self, centre, normal, x_axis, major_radius, minor_radius) -> int:
        n = unit(normal, "an ellipse's normal")
        a, b = _num(major_radius, "a radius"), _num(minor_radius, "a radius")
        if not (a > 0 and b > 0):
            raise GeometryRefused("an ellipse's radii are not positive")
        x = perpendicular(n, None if x_axis is None else vec(x_axis, "an x axis"))
        return self.node(ELLIPSE, centre=vec(centre), normal=n, x_axis=x, major_radius=a, minor_radius=b)

    def bspline_curve(
        self,
        degree: int,
        points: Sequence[Sequence[float]],
        knots: Sequence[float],
        mults: Sequence[int],
        *,
        weights: Sequence[float] | None = None,
        closed: bool = False,
        dim: int = 3,
    ) -> int:
        """A B_CURVE of Cartesian ``points`` (``dim`` 3, or 2 for the (u, v) curve of an
        SP-curve), rational with ``weights``."""
        n = len(points)
        if n < 2:
            raise GeometryRefused("a B-spline curve of fewer than two control points")
        kk, mm = self._knots(knots, mults, n, degree)
        rational = weights is not None
        if rational and len(weights) != n:
            raise GeometryRefused("a B-spline curve's weights do not match its control points")
        flat: list[float] = []
        for i, p in enumerate(points):
            if self.clock is not None:
                self.clock.tick()
            if len(p) != dim:
                raise GeometryRefused("a control point has the wrong number of coordinates")
            c = [_num(x, "a control point") for x in p]
            if rational:
                w = _num(weights[i], "a weight")
                if not w > 0:
                    raise GeometryRefused("a weight is not positive")
                flat.extend([x * w for x in c] + [w])
            else:
                flat.extend(c)
        verts = self.node(BSPLINE_VERTICES, vertices=flat)
        kn = self.node(KNOT_SET, knots=kk)
        mn = self.node(KNOT_MULT, mult=mm)
        nc = self.node(
            NURBS_CURVE,
            degree=degree,
            n_vertices=n,
            vertex_dim=dim + (1 if rational else 0),
            n_knots=len(kk),
            periodic=0,
            closed=1 if closed else 0,
            rational=1 if rational else 0,
            bspline_vertices=verts,
            knot_mult=mn,
            knots=kn,
        )
        return self.node(B_CURVE, nurbs=nc)

    def trimmed(self, basis: int, t0: float, t1: float, p0, p1) -> int:
        if self.type_of(basis) not in CURVES:
            raise ValueError("a trimmed curve needs a basis curve")
        return self.node(
            TRIMMED_CURVE,
            basis_curve=basis,
            point_1=vec(p0),
            point_2=vec(p1),
            parm_1=_num(t0, "a parameter"),
            parm_2=_num(t1, "a parameter"),
        )

    def sp_curve(self, surface: int, uv_curve: int) -> int:
        """A curve in ``surface``'s (u, v): ``uv_curve`` a two-dimensional B_CURVE."""
        if self.type_of(surface) not in SURFACES or self.type_of(uv_curve) != B_CURVE:
            raise ValueError("an SP-curve needs a surface and a B-curve")
        return self.node(SP_CURVE, surface=surface, b_curve=uv_curve, tolerance_to_original=NULL_DOUBLE)

    # -- the transmit --------------------------------------------------------------------
    def transmit(self) -> XtTransmit:
        """The body's transmit: fins partnered by ``other``, edges given their first fin."""
        if self._body is None:
            raise ValueError("no body was made")
        for e, fins in self._edge_fins.items():
            if fins:
                self.set(e, halfedge=fins[0])
            if len(fins) == 2:
                self.set(fins[0], other=fins[1])
                self.set(fins[1], other=fins[0])
            elif len(fins) > 2:  # an edge of more than two faces: a ring of partners
                for a, b in zip(fins, fins[1:] + fins[:1], strict=True):
                    self.set(a, other=b)
        xt = XtTransmit()
        xt.modeller = MODELLER
        xt.schema = SCHEMA
        xt.base = 13006
        xt.max_types = MAX_TYPES
        xt.usfld = 0
        for idx in sorted(self.nodes):
            ntype, fields = self.nodes[idx]
            lay = xt.layouts.get(ntype)
            if lay is None:
                lay = xt.layouts[ntype] = [tuple(f[:3]) for f in S.BASE[ntype]]
                xt.schema_info[ntype] = SchemaInfo("base")
            vals, count = [], None
            for name, kind, n in lay:
                v = fields[name] if name in fields else _default(kind, n)
                if n == S.VAR:
                    count = len(v)
                vals.append(v)
            if lay[0][0] == "node_id" and "node_id" not in fields:
                vals[0] = min(idx, MAX_NODE_ID)  # unique: the tessellator names faces by it
            elif ntype == BODY:
                vals[0] = min(self.k - 1, MAX_NODE_ID)  # highest_node_id
            xt.nodes.append(Node(ntype, idx, vals, count))
        return xt


__all__ = ["BODY_TYPE_CODES", "BrepBuilder", "GeometryRefused", "perpendicular", "unit", "vec"]
