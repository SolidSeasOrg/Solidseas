"""STEP B-rep to Parasolid bodies (provisional).

Each solid (``MANIFOLD_SOLID_BREP``, ``BREP_WITH_VOIDS``, a ``CLOSED_SHELL`` placed
on its own) and each shell of a ``SHELL_BASED_SURFACE_MODEL`` becomes one body in
a :class:`~.builder.BrepBuilder`, which SolidSeas' tessellator then draws. The
rules, from ISO 10303-42:

* Topology. A face (``ADVANCED_FACE``, ``FACE_SURFACE``) keeps its surface's
  normal when ``same_sense`` is true; its bounds (``FACE_OUTER_BOUND``,
  ``FACE_BOUND``) run with the face on their left seen from that normal, and a
  bound whose ``orientation`` is false runs backwards (its edges in reverse order,
  each the other way). An ``ORIENTED_EDGE`` runs along its ``EDGE_CURVE`` when its
  orientation is true; an ``EDGE_CURVE`` runs from ``edge_start`` to ``edge_end``,
  along its curve when ``same_sense`` is true. An ``ORIENTED_FACE`` or an
  oriented shell whose orientation is false turns its faces round (their normal
  and their bounds). A ``VERTEX_LOOP`` (an apex, a pole) is a loop of one vertex.
  A ``POLY_LOOP`` becomes line edges, shared by the faces that share its points.
  A shell's faces are each face once; a ``BREP_WITH_VOIDS`` adds its void shells
  to the body.
* Surfaces. ``PLANE``, ``CYLINDRICAL_SURFACE``, ``CONICAL_SURFACE`` (radius at the
  placement, semi-angle in the context's angle unit), ``SPHERICAL_SURFACE``,
  ``TOROIDAL_SURFACE`` and ``DEGENERATE_TOROIDAL_SURFACE`` map to the XT surfaces
  of the same parametrisation; B-spline surfaces (with knots, Bezier, uniform,
  quasi-uniform, rational or not; control points ``[u][v]``, which XT wants with
  v varying fastest) to B_SURFACE; ``SURFACE_OF_LINEAR_EXTRUSION`` to a swept
  surface, ``SURFACE_OF_REVOLUTION`` to a spun one turned round (STEP's u is the
  turn and v the curve's parameter, XT's the other way, so their natural normals
  are opposite), ``OFFSET_SURFACE`` to an offset one; ``RECTANGULAR_TRIMMED_SURFACE``
  and ``CURVE_BOUNDED_SURFACE`` to their basis
  surface (turned round when exactly one of a rectangular trim's senses is false).
  The curve of a swept or spun surface is built along the curve it is trimmed
  from, so a surface whose curve is a trimmed curve running against its basis
  (``sense_agreement`` false) is turned round once more. A spun surface whose
  curve is an unbounded ``LINE`` gets the line trimmed to cover the body once
  the body is built. An offset of a basis whose normal was turned round is the
  offset of the basis as built, the other way, turned round: an XT offset
  surface's normal is its basis's own.
* A loop that only runs up and down the seams of a sphere (every edge in it once
  each way, ending at the poles) is a full sphere: it becomes a vertex loop at
  each pole, as the face's boundary has no area in (u, v).
* Curves. ``LINE`` (its vector's direction), ``CIRCLE``, ``ELLIPSE``, B-spline
  curves of every form, ``POLYLINE`` (a B-spline of degree 1), ``SURFACE_CURVE``,
  ``SEAM_CURVE`` and ``INTERSECTION_CURVE`` by their 3D curve, ``TRIMMED_CURVE`` by
  its basis curve (an edge is trimmed by its vertices; the trim's
  ``sense_agreement`` is kept), and an edge whose only geometry is a ``PCURVE``
  by an SP-curve when its curve in the surface's (u, v) is a B-spline or a
  polyline. Other pcurves are not needed: the tessellator places an edge's
  points on each face's surface itself. An edge on a ``HYPERBOLA`` or a
  ``PARABOLA`` (where a plane meets a cone) is the arc between its vertices as
  the exact rational quadratic B-spline it is: an XT body has neither curve. A
  ``COMPOSITE_CURVE`` (and its subtypes) as an edge's geometry is sampled segment
  by segment, to within a ten-thousandth of its size, into a B-spline of degree 1
  of at most :data:`COMPOSITE_POINTS` points (``edge_too_long`` past them), each
  curve record sampled once a body.
* Closed B-splines. A B-spline curve or surface is marked closed when it is,
  evaluated (its ends, or its boundary curves, meet within a billionth of its
  control net), whatever the file's flag says: a closed edge of one vertex on
  such a curve then goes all the way round, and a periodic surface whose
  control rows do not repeat is known to close.

Every length is multiplied by the representation context's metres per unit and
every angle by its radians per unit. A face whose surface or one of whose
curves is not read, or holds values the builder refuses, is left out with a
reason (``unsupported_surface``, ``unsupported_curve``, ``bad_geometry``,
``non_finite``, ``bad_reference``), as the tessellator leaves faces out; a record
that cannot be parsed leaves out the face (or the shell, or the body) that needs
it, reason ``bad_reference``. Control points, curve samples and composite
segments tick the clock, so the call's time bound holds while a body is mapped.
"""

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from ...errors import SldFormatError, SldLimitError
from ..solidworks.parasolid import XtTransmit
from .builder import BrepBuilder, GeometryRefused, perpendicular
from .part21 import Part21, Record, Ref, Typed, as_bool
from .units import Context

Vec = tuple[float, float, float]
Frame = tuple[Vec, Vec, Vec, Vec]  # origin, x, y, z


class Unsupported(Exception):
    """A face that cannot be built: ``reason`` (a tessellation reason), the STEP entity
    that stopped it and a detail for people."""

    def __init__(self, reason: str, entity: str = "", detail: str = "") -> None:
        super().__init__(f"{reason}: {entity} {detail}".strip())
        self.reason, self.entity, self.detail = reason, entity, detail


SOLIDS = ("MANIFOLD_SOLID_BREP", "BREP_WITH_VOIDS")
SHELLS = ("CLOSED_SHELL", "OPEN_SHELL", "ORIENTED_CLOSED_SHELL", "ORIENTED_OPEN_SHELL", "CONNECTED_FACE_SET")
FACES = ("ADVANCED_FACE", "FACE_SURFACE")
BSPLINE_CURVES = ("B_SPLINE_CURVE_WITH_KNOTS", "BEZIER_CURVE", "UNIFORM_CURVE", "QUASI_UNIFORM_CURVE")
BSPLINE_SURFACES = (
    "B_SPLINE_SURFACE_WITH_KNOTS",
    "BEZIER_SURFACE",
    "UNIFORM_SURFACE",
    "QUASI_UNIFORM_SURFACE",
)
CLOSURE = 1e-9  # of a B-spline's control net diagonal: its ends meet within this
COMPOSITE_CURVES = ("COMPOSITE_CURVE", "COMPOSITE_CURVE_ON_SURFACE", "BOUNDARY_CURVE", "OUTER_BOUNDARY_CURVE")
COMPOSITE_POINTS = 20_000  # points of one sampled composite curve (and of each sampled piece), at most
POLE = 1e-6  # of a sphere's radius: a vertex this close to a pole is on it
CURVE_WRAPPERS = ("SURFACE_CURVE", "SEAM_CURVE", "INTERSECTION_CURVE", "BOUNDED_SURFACE_CURVE")
OPEN_CONICS = ("HYPERBOLA", "PARABOLA")
MAX_HYPERBOLA_SPAN = 60.0  # of a hyperbola's parameter: past it, cosh outgrows any model


# --------------------------------------------------------------------------- small values


@dataclass(frozen=True)
class _OpenConic:
    """A hyperbola ``o + a cosh t x + b sinh t y`` or a parabola ``o + f t^2 x + 2 f t y``
    (``a`` and ``b`` both ``f``), in metres, as ISO 10303-42 parametrises them."""

    kind: str
    o: Vec
    x: Vec
    y: Vec
    a: float
    b: float

    def _at(self, cx: float, cy: float) -> Vec:
        o, x, y = self.o, self.x, self.y
        return (o[0] + cx * x[0] + cy * y[0], o[1] + cx * x[1] + cy * y[1], o[2] + cx * x[2] + cy * y[2])

    def point(self, t: float) -> Vec:
        if self.kind == "HYPERBOLA":
            return self._at(self.a * math.cosh(t), self.b * math.sinh(t))
        return self._at(self.a * t * t, 2.0 * self.a * t)

    def parameter(self, p: Vec) -> float:
        """The parameter of a point on the conic, from its coordinate along y, which
        fixes it on the branch."""
        d = [p[i] - self.o[i] for i in range(3)]
        h = sum(d[i] * self.y[i] for i in range(3))
        t = math.asinh(h / self.b) if self.kind == "HYPERBOLA" else h / (2.0 * self.a)
        if not math.isfinite(t):
            raise Unsupported("non_finite", self.kind, "a vertex off the curve")
        return t

    def arc(self, t0: float, t1: float):
        """``(points, weights or None, knots, multiplicities)`` of the arc from ``t0`` to
        ``t1`` as a quadratic B-spline: Bezier pieces that each match the conic exactly at
        both ends, with its tangents there, and at its middle."""
        if not t1 > t0:
            raise Unsupported("degenerate", self.kind, "an edge of no length on the curve")
        if self.kind == "PARABOLA":
            # a parabola is a polynomial in t: one Bezier piece, its middle point where the
            # tangents at the ends meet
            p0, p2 = self.point(t0), self.point(t1)
            h = 0.5 * (t1 - t0)
            d0 = (2.0 * self.a * t0, 2.0 * self.a)
            p1 = self._at(self.a * t0 * t0 + h * d0[0], 2.0 * self.a * t0 + h * d0[1])
            return [p0, p1, p2], None, [0.0, 1.0], [3, 3]
        if t1 - t0 > MAX_HYPERBOLA_SPAN or max(abs(t0), abs(t1)) > MAX_HYPERBOLA_SPAN:
            raise Unsupported("bad_geometry", "HYPERBOLA", "an arc too long to represent")
        # pieces of at most one unit of t, each a rational quadratic Bezier: the middle point
        # at the parameter halfway, divided by cosh of half the piece, weighted that cosh
        n = max(1, math.ceil(t1 - t0))
        points = [self.point(t0)]
        weights = [1.0]
        for k in range(n):
            a0 = t0 + (t1 - t0) * k / n
            a1 = t0 + (t1 - t0) * (k + 1) / n
            h, m = 0.5 * (a1 - a0), 0.5 * (a0 + a1)
            ch = math.cosh(h)
            points.append(self._at(self.a * math.cosh(m) / ch, self.b * math.sinh(m) / ch))
            weights.append(ch)
            points.append(self.point(a1))
            weights.append(1.0)
        knots = [float(k) for k in range(n + 1)]
        mults = [3] + [2] * (n - 1) + [3]
        return points, weights, knots, mults


def _num(v: Any, what: str = "a number") -> float:
    if isinstance(v, Typed):
        v = v.value
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise Unsupported("bad_geometry", "", f"{what} is not a number")
    v = float(v)
    if not math.isfinite(v):
        raise Unsupported("non_finite", "", f"{what} is not finite")
    return v


def _int(v: Any, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise Unsupported("bad_geometry", "", f"{what} is not a whole number")
    return v


def _list(v: Any, what: str) -> list:
    if not isinstance(v, list):
        raise Unsupported("bad_geometry", "", f"{what} is not a list")
    return v


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(v: Vec) -> Vec | None:
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if not n > 1e-14 or not math.isfinite(n):
        return None
    return (v[0] / n, v[1] / n, v[2] / n)


@dataclass
class MappedBody:
    """One body built from a STEP solid or shell (see the module notes)."""

    item: int
    name: str | None
    kind: str
    transmit: XtTransmit | None
    faces: int = 0
    face_ids: list[int] = field(default_factory=list)  # STEP ids of the faces built, in order
    skipped: list[tuple[int, str, str, str]] = field(
        default_factory=list
    )  # (face id, entity, reason, detail)
    box: tuple[Vec, Vec] | None = None
    shells: list[int] = field(default_factory=list)  # the body's SHELL nodes: the outer one, then the voids


class _BodyCtx:
    """One body being built: its builder, the context's scales and caches by STEP id."""

    __slots__ = (
        "b",
        "ctx",
        "vertices",
        "edges",
        "curves",
        "surfaces",
        "poly_vertices",
        "poly_edges",
        "samples",
        "open_lines",
        "conics",
        "lo",
        "hi",
    )

    def __init__(self, b: BrepBuilder, ctx: Context) -> None:
        self.b, self.ctx = b, ctx
        self.vertices: dict[int, int] = {}
        self.edges: dict[int, Any] = {}
        self.curves: dict[int, Any] = {}
        self.surfaces: dict[int, Any] = {}
        self.poly_vertices: dict[int, int] = {}
        self.poly_edges: dict[tuple[int, int], int] = {}
        self.samples: dict[int, list] = {}  # a curve record's points, sampled once
        self.open_lines: list[tuple[int, Vec, Vec, Vec, Vec]] = []  # spun lines bounded at the end
        # a circle's or ellipse's builder curve: its centre, axes and radii, for the box of
        # the part of it an edge runs along
        self.conics: dict[int, tuple[Vec, Vec, Vec, float, float]] = {}
        self.lo = [math.inf] * 3
        self.hi = [-math.inf] * 3

    def extent(self, origin: Vec, axes) -> None:
        """Take the box of ``origin`` plus or minus each ``(direction, length)``: a conic's
        or a closed surface's, which no vertex may reach."""
        for d, r in axes:
            for sign in (1.0, -1.0):
                self.take(tuple(origin[i] + sign * r * d[i] for i in range(3)))  # type: ignore[arg-type]

    def take(self, p: Vec) -> None:
        for i in range(3):
            if p[i] < self.lo[i]:
                self.lo[i] = p[i]
            if p[i] > self.hi[i]:
                self.hi[i] = p[i]


class Geometry:
    """Points, directions and placements of one file, in metres (see the module notes)."""

    def __init__(self, p21: Part21) -> None:
        self.p = p21

    def rec(self, ref: Any, *names: str) -> Record:
        r = self.p.get(ref)
        if r is None:
            raise Unsupported("bad_reference", "", f"{ref!r} does not lead to an instance")
        if names and not any(r.has(n) for n in names):
            raise Unsupported("bad_reference", r.types[0], f"#{r.id} is not a {' or '.join(names)}")
        return r

    def point(self, ref: Any, scale: float) -> Vec:
        r = self.rec(ref, "CARTESIAN_POINT")
        p = r.part("CARTESIAN_POINT")
        coords = _list(p[1] if len(p) >= 2 else None, "a point's coordinates")
        if not 1 <= len(coords) <= 3:
            raise Unsupported("bad_geometry", "CARTESIAN_POINT", "a point of more than three coordinates")
        c = [_num(x, "a coordinate") * scale for x in coords] + [0.0] * (3 - len(coords))
        return (c[0], c[1], c[2])

    def point2(self, ref: Any) -> tuple[float, float]:
        r = self.rec(ref, "CARTESIAN_POINT")
        p = r.part("CARTESIAN_POINT")
        coords = _list(p[1] if len(p) >= 2 else None, "a point's coordinates")
        if len(coords) != 2:
            raise Unsupported("bad_geometry", "CARTESIAN_POINT", "not a point of two coordinates")
        return _num(coords[0]), _num(coords[1])

    def direction(self, ref: Any) -> Vec:
        r = self.rec(ref, "DIRECTION")
        p = r.part("DIRECTION")
        ratios = _list(p[1] if len(p) >= 2 else None, "a direction")
        if not 2 <= len(ratios) <= 3:
            raise Unsupported("bad_geometry", "DIRECTION", "a direction of the wrong size")
        c = [_num(x, "a direction") for x in ratios] + [0.0] * (3 - len(ratios))
        u = _unit((c[0], c[1], c[2]))
        if u is None:
            raise Unsupported("bad_geometry", "DIRECTION", "a direction of no length")
        return u

    def vector(self, ref: Any, scale: float) -> tuple[Vec, float]:
        """A VECTOR: its unit direction and its magnitude in metres."""
        r = self.rec(ref, "VECTOR", "DIRECTION")
        if r.has("DIRECTION"):
            return self.direction(ref), 1.0 * scale
        p = r.part("VECTOR")
        if len(p) < 3:
            raise Unsupported("bad_geometry", "VECTOR", "a vector without its magnitude")
        return self.direction(p[1]), _num(p[2], "a magnitude") * scale

    def frame(self, ref: Any, scale: float) -> Frame:
        """An AXIS2_PLACEMENT_3D (or 2D) as origin and the x, y and z axes, with
        ISO 10303-42's defaults and the x axis made perpendicular to z."""
        r = self.rec(ref, "AXIS2_PLACEMENT_3D", "AXIS2_PLACEMENT_2D", "AXIS1_PLACEMENT")
        p = r.params
        origin = self.point(p[1], scale) if len(p) >= 2 else (0.0, 0.0, 0.0)
        if r.has("AXIS2_PLACEMENT_2D"):
            z: Vec = (0.0, 0.0, 1.0)
            ref_dir = self.direction(p[2]) if len(p) >= 3 and isinstance(p[2], Ref) else None
        else:
            z = self.direction(p[2]) if len(p) >= 3 and isinstance(p[2], Ref) else (0.0, 0.0, 1.0)
            ref_dir = self.direction(p[3]) if len(p) >= 4 and isinstance(p[3], Ref) else None
        x = perpendicular(z, ref_dir)
        return origin, x, _cross(z, x), z

    def axis1(self, ref: Any, scale: float) -> tuple[Vec, Vec]:
        r = self.rec(ref, "AXIS1_PLACEMENT")
        p = r.params
        origin = self.point(p[1], scale) if len(p) >= 2 else (0.0, 0.0, 0.0)
        axis = self.direction(p[2]) if len(p) >= 3 and isinstance(p[2], Ref) else (0.0, 0.0, 1.0)
        return origin, axis


def _bspline_parts(rec: Record, kind: str) -> dict[str, Any]:
    """The attributes of a B-spline curve or surface, simple or complex, by name."""
    curve = kind == "curve"
    base = "B_SPLINE_CURVE" if curve else "B_SPLINE_SURFACE"
    with_knots = base + "_WITH_KNOTS"
    out: dict[str, Any] = {"form": None, "rational": None}
    names_curve = ("degree", "points", "curve_form", "closed", "self_intersect")
    names_surface = (
        "u_degree",
        "v_degree",
        "points",
        "surface_form",
        "u_closed",
        "v_closed",
        "self_intersect",
    )
    names = names_curve if curve else names_surface
    knots = ("u_mults", "v_mults", "u_knots", "v_knots", "spec") if not curve else ("mults", "knots", "spec")
    for t, p in zip(rec.types, rec.parts, strict=True):
        if not rec.complex:
            # a simple instance: the name, then the B-spline's attributes, then its subtype's
            vals = p[1:]
            out.update(zip(names, vals, strict=False))
            if t == with_knots:
                out.update(zip(knots, vals[len(names) :], strict=False))
            out["form"] = t
            continue
        if t == base:
            out.update(zip(names, p, strict=False))
        elif t == with_knots:
            out.update(zip(knots, p, strict=False))
            out["form"] = t
        elif t in BSPLINE_CURVES + BSPLINE_SURFACES:
            out["form"] = t
        elif t in ("RATIONAL_B_SPLINE_CURVE", "RATIONAL_B_SPLINE_SURFACE"):
            out["rational"] = p[0] if p else None
    return out


def _generated_knots(form: str, n: int, degree: int) -> tuple[list[float], list[int]]:
    """The knots ISO 10303-42 gives the B-spline forms that store none."""
    if form.startswith("BEZIER"):
        segments = max(1, (n - 1) // degree)
        knots = [float(i) for i in range(segments + 1)]
        mults = [degree + 1] + [degree] * (segments - 1) + [degree + 1]
        if sum(mults) != n + degree + 1:
            raise Unsupported("bad_geometry", form, "the control points do not make whole Bezier segments")
        return knots, mults
    if form.startswith("UNIFORM"):
        return [float(k) for k in range(-degree, n + 1)], [1] * (n + degree + 1)
    if form.startswith("QUASI_UNIFORM"):
        inner = n - degree
        if inner < 1:
            raise Unsupported("bad_geometry", form, "too few control points")
        return [float(k) for k in range(inner + 1)], [degree + 1] + [1] * (inner - 1) + [degree + 1]
    raise Unsupported("unsupported_curve", form)


def _knots(
    attrs: dict[str, Any], prefix: str, form: str, n: int, degree: int
) -> tuple[list[float], list[int]]:
    if form.endswith("_WITH_KNOTS"):
        mults = [_int(m, "a knot multiplicity") for m in _list(attrs.get(prefix + "mults"), "multiplicities")]
        knots = [_num(k, "a knot") for k in _list(attrs.get(prefix + "knots"), "knots")]
        if len(mults) != len(knots):
            raise Unsupported("bad_geometry", form, "knots and multiplicities differ in number")
        total = sum(mults)
        if total == n + degree - 1 and len(mults) >= 2:
            # end knots of multiplicity p rather than p + 1, as some writers store them
            mults = [mults[0] + 1] + mults[1:-1] + [mults[-1] + 1]
        return knots, mults
    return _generated_knots(form, n, degree)


class Mapper:
    """STEP solids and shells to bodies (see the module notes). ``stats`` counts what
    was left out and why, by entity name."""

    def __init__(self, p21: Part21, limits: Any, clock: Any = None) -> None:
        self.p = p21
        self.g = Geometry(p21)
        self.limits = limits
        self.clock = clock
        self.stats: Counter = Counter()

    def tick(self, k: int = 1) -> None:
        if self.clock is not None:
            self.clock.tick(k)

    # -- bodies ---------------------------------------------------------------------------
    def kind_of(self, rid: int) -> str | None:
        """``solid`` or ``sheet`` for an item that becomes one body, else None."""
        t = self.p.type_of(rid) or ()
        if any(s in t for s in SOLIDS) or "CLOSED_SHELL" in t or "ORIENTED_CLOSED_SHELL" in t:
            return "solid"
        if "OPEN_SHELL" in t or "ORIENTED_OPEN_SHELL" in t:
            return "sheet"
        return None

    def body(self, rid: int, ctx: Context, *, kind: str | None = None, name: str | None = None) -> MappedBody:
        """The body of a solid or of one shell (``kind`` ``sheet`` for a surface model's
        shell)."""
        try:
            rec = self.g.rec(Ref(rid))
        except (Unsupported, SldFormatError) as exc:
            if isinstance(exc, SldLimitError):
                raise
            out = MappedBody(rid, name, kind or "solid", None)
            reason = exc.reason if isinstance(exc, Unsupported) else "bad_reference"
            out.skipped.append((-1, "", reason, f"the body's record could not be read: {exc}"[:200]))
            return out
        shells: list[tuple[Any, bool]] = []
        if rec.has("MANIFOLD_SOLID_BREP") or rec.has("BREP_WITH_VOIDS"):
            p = rec.part("MANIFOLD_SOLID_BREP") or rec.part("BREP_WITH_VOIDS") or rec.params
            if not rec.complex:
                outer = p[1] if len(p) >= 2 else None
                voids = p[2] if rec.has("BREP_WITH_VOIDS") and len(p) >= 3 else []
            else:
                mp = rec.part("MANIFOLD_SOLID_BREP") or []
                outer = mp[0] if mp else None
                bw = rec.part("BREP_WITH_VOIDS") or []
                voids = bw[0] if bw else []
            shells.append((outer, False))
            for v in voids if isinstance(voids, list) else []:
                shells.append((v, False))
            kind = kind or "solid"
            if name is None:
                rep_item = rec.part("REPRESENTATION_ITEM")
                raw = rep_item[0] if rep_item else (rec.params[0] if rec.params and not rec.complex else None)
                name = raw if isinstance(raw, str) else None
        else:
            shells.append((Ref(rid), False))
            kind = kind or self.kind_of(rid) or "sheet"
        b = BrepBuilder(limits=self.limits, clock=self.clock)
        body = b.body(kind)
        region = b.region(body, solid=kind == "solid")
        bc = _BodyCtx(b, ctx)
        out = MappedBody(rid, name, kind, None)
        for shell_ref, flip in shells:
            sh = b.shell(region)
            out.shells.append(sh)
            try:
                faces = self.faces_of(shell_ref, flip)
            except Unsupported as exc:  # the shell cannot be walked: the body says so as one face
                out.skipped.append((-1, exc.entity, exc.reason, exc.detail[:200]))
                self.stats[f"{exc.reason}:{exc.entity}"] += 1
                continue
            except SldLimitError:
                raise
            except SldFormatError as exc:  # a record that cannot be parsed
                out.skipped.append((-1, "", "bad_reference", f"the shell could not be read: {exc}"[:200]))
                self.stats["bad_reference:damaged"] += 1
                continue
            for face_rid, face_flip in faces:
                out.faces += 1
                self.tick()
                try:
                    self.face(bc, sh, face_rid, face_flip, out)
                except Unsupported as exc:
                    out.skipped.append((face_rid, exc.entity, exc.reason, exc.detail[:200]))
                    self.stats[f"{exc.reason}:{exc.entity}"] += 1
                except GeometryRefused as exc:
                    out.skipped.append((face_rid, "", exc.reason, str(exc)[:200]))
                    self.stats[f"{exc.reason}:builder"] += 1
                except SldLimitError:
                    raise
                except SldFormatError as exc:  # a record of the face that cannot be parsed
                    out.skipped.append(
                        (face_rid, "", "bad_reference", f"a record could not be read: {exc}"[:200])
                    )
                    self.stats["bad_reference:damaged"] += 1
        self._bound_lines(bc)
        if out.face_ids:
            out.transmit = b.transmit()
        if all(math.isfinite(x) for x in bc.lo + bc.hi):
            out.box = ((bc.lo[0], bc.lo[1], bc.lo[2]), (bc.hi[0], bc.hi[1], bc.hi[2]))
        return out

    def faces_of(self, shell_ref: Any, flip: bool, depth: int = 0) -> list[tuple[int, bool]]:
        """The faces of a shell, each once, with whether each is turned round."""
        rec = self.p.get(shell_ref)
        if rec is None or depth > 8:
            raise Unsupported(
                "bad_reference", "CLOSED_SHELL", "a shell that is not an instance, or refers to itself"
            )
        if rec.has("ORIENTED_CLOSED_SHELL") or rec.has("ORIENTED_OPEN_SHELL"):
            p = rec.params
            inner = p[2] if len(p) >= 4 else None
            turned = as_bool(p[3] if len(p) >= 4 else None) is False
            return self.faces_of(inner, flip ^ turned, depth + 1)
        p = rec.params
        faces = p[1] if len(p) >= 2 and isinstance(p[1], list) else []
        out = []
        seen: set[int] = set()
        for f in faces:
            if isinstance(f, Ref) and int(f) not in seen:
                seen.add(int(f))
                out.append((int(f), flip))
        return out

    # -- faces ------------------------------------------------------------------------------
    def face(self, bc: _BodyCtx, shell: int, rid: int, flip: bool, out: MappedBody, depth: int = 0) -> None:
        rec = self.g.rec(Ref(rid))
        if rec.has("ORIENTED_FACE"):
            p = rec.params
            if depth > 4 or len(p) < 4:
                raise Unsupported("bad_reference", "ORIENTED_FACE")
            turned = as_bool(p[3]) is False
            self.face(bc, shell, int(p[2]), flip ^ turned, out, depth + 1)
            return
        kind = next((t for t in FACES if rec.has(t)), None)
        if kind is None:
            raise Unsupported("unsupported_surface", rec.types[0], "a face with no surface")
        if rec.complex:
            raise Unsupported("unsupported_surface", kind, "a face stored as a complex instance")
        p = rec.params
        if len(p) < 4:
            raise Unsupported("bad_reference", kind, "a face without its attributes")
        surface = self.surface(bc, p[2])
        same = as_bool(p[3]) is not False
        srec = self.p.get(p[2])
        sphere = srec is not None and not srec.complex and srec.has("SPHERICAL_SURFACE")
        loops = []
        for bound in _list(p[1], "a face's bounds"):
            brec = self.g.rec(bound, "FACE_BOUND", "FACE_OUTER_BOUND")
            bp = brec.params
            if len(bp) < 3:
                raise Unsupported("bad_reference", brec.types[0])
            poles = self._seam_poles(bc, bp[1], srec) if sphere else None
            if poles is not None:
                loops.extend(([], v) for v in poles)
                continue
            forward = (as_bool(bp[2]) is not False) ^ flip
            loops.append(self.loop(bc, bp[1], forward))
        b = bc.b
        f = b.face(shell, surface, "+" if same ^ flip else "-")
        for fins, vertex in loops:
            if fins:
                b.loop(f, fins)
            else:
                b.loop(f, [], vertex=vertex)
        out.face_ids.append(rid)

    def _seam_poles(self, bc: _BodyCtx, ref: Any, srec: Record) -> list[int] | None:
        """The vertices at the poles of a sphere for an EDGE_LOOP that only runs up and down
        its seams (every edge in it once each way, every vertex at a pole), else None."""
        lrec = self.p.get(ref)
        if lrec is None or lrec.complex or not lrec.has("EDGE_LOOP") or len(lrec.params) < 2:
            return None
        uses: dict[int, list[bool]] = {}
        for oe in lrec.params[1] if isinstance(lrec.params[1], list) else []:
            r = self.p.get(oe)
            if (
                r is None
                or not r.has("ORIENTED_EDGE")
                or len(r.params) < 5
                or not isinstance(r.params[3], Ref)
            ):
                return None
            uses.setdefault(int(r.params[3]), []).append(as_bool(r.params[4]) is not False)
        if not uses or any(sorted(v) != [False, True] for v in uses.values()):
            return None
        o, _x, _y, z = self.g.frame(srec.params[1], bc.ctx.length_m)
        r = abs(_num(srec.params[2], "a radius")) * bc.ctx.length_m
        poles = [tuple(o[i] + sign * r * z[i] for i in range(3)) for sign in (1.0, -1.0)]
        refs: list[Any] = []
        for ec in uses:
            erec = self.g.rec(Ref(ec), "EDGE_CURVE")
            if len(erec.params) < 3:
                return None
            for v in erec.params[1:3]:
                if v not in refs:
                    refs.append(v)
        out = []
        for v in refs:
            vrec = self.g.rec(v, "VERTEX_POINT")
            q = self.g.point(vrec.params[1] if len(vrec.params) >= 2 else None, bc.ctx.length_m)
            if min(math.dist(q, pole) for pole in poles) > POLE * max(r, 1e-12):
                return None
            out.append(self.vertex(bc, v))
        return out

    def loop(self, bc: _BodyCtx, ref: Any, forward: bool) -> tuple[list[tuple[int, str]], int | None]:
        rec = self.g.rec(ref, "EDGE_LOOP", "VERTEX_LOOP", "POLY_LOOP")
        p = rec.params
        if rec.has("VERTEX_LOOP"):
            return [], self.vertex(bc, p[1] if len(p) >= 2 else None)
        if rec.has("POLY_LOOP"):
            pts = _list(p[1] if len(p) >= 2 else None, "a polygon")
            fins = self.polygon(bc, pts)
        else:
            fins = []
            for oe in _list(p[1] if len(p) >= 2 else None, "a loop's edges"):
                fins.append(self.oriented(bc, oe))
        if not fins:
            raise Unsupported("bad_reference", rec.types[0], "an empty loop")
        if not forward:
            fins = [(e, not s) for e, s in reversed(fins)]
        return [(e, "+" if s else "-") for e, s in fins], None

    def oriented(self, bc: _BodyCtx, ref: Any, depth: int = 0) -> tuple[int, bool]:
        rec = self.g.rec(ref, "ORIENTED_EDGE", "EDGE_CURVE")
        if rec.has("EDGE_CURVE") and not rec.has("ORIENTED_EDGE"):
            return self.edge(bc, rec), True
        p = rec.params
        if len(p) < 5 or depth > 4:
            raise Unsupported("bad_reference", "ORIENTED_EDGE")
        along = as_bool(p[4]) is not False
        e, s = self.oriented(bc, p[3], depth + 1)
        return e, s == along

    def polygon(self, bc: _BodyCtx, pts: list) -> list[tuple[int, bool]]:
        """Line edges round a POLY_LOOP, shared with any face that names the same points."""
        b = bc.b
        ids = []
        for ref in pts:
            if not isinstance(ref, Ref):
                raise Unsupported("bad_reference", "POLY_LOOP")
            v = bc.poly_vertices.get(int(ref))
            if v is None:
                q = self.g.point(ref, bc.ctx.length_m)
                bc.take(q)
                v = bc.poly_vertices[int(ref)] = b.vertex(q)
            ids.append((int(ref), v))
        if len(ids) > 1 and ids[0][0] == ids[-1][0]:
            ids.pop()
        if len(ids) < 3:
            raise Unsupported("degenerate", "POLY_LOOP", "a polygon of fewer than three points")
        fins = []
        for (ka, va), (kb, vb) in zip(ids, ids[1:] + ids[:1], strict=True):
            key = (ka, kb) if ka < kb else (kb, ka)
            e = bc.poly_edges.get(key)
            if e is None:
                v0, v1 = (va, vb) if ka < kb else (vb, va)
                p0, p1 = b.point_of(v0), b.point_of(v1)
                d = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
                if _unit(d) is None:
                    raise Unsupported("degenerate", "POLY_LOOP", "two points of a polygon coincide")
                e = bc.poly_edges[key] = b.edge(b.line(p0, d), v0, v1)
            fins.append((e, ka < kb))
        return fins

    def vertex(self, bc: _BodyCtx, ref: Any) -> int:
        if not isinstance(ref, Ref):
            raise Unsupported("bad_reference", "VERTEX_POINT", "a vertex is not a reference")
        got = bc.vertices.get(int(ref))
        if got is not None:
            return got
        rec = self.g.rec(ref, "VERTEX_POINT")
        p = rec.params
        q = self.g.point(p[1] if len(p) >= 2 else None, bc.ctx.length_m)
        bc.take(q)
        v = bc.vertices[int(ref)] = bc.b.vertex(q)
        return v

    def _arc_extent(self, bc: _BodyCtx, conic, start: Any, end: Any, along: bool) -> None:
        """Take the box of the arc of a circle or ellipse from vertex ``start`` to ``end``
        (with the curve's sense when ``along``): its ends are vertices already, so the points
        where it turns in x, y or z, those that lie on the arc; a whole one if it closes."""
        o, x, y, ra, rb = conic
        if start == end:
            bc.extent(o, ((x, ra), (y, rb)))
            return

        def angle(q: Vec) -> float:
            d = [q[i] - o[i] for i in range(3)]
            along_x, along_y = sum(d[i] * x[i] for i in range(3)), sum(d[i] * y[i] for i in range(3))
            return math.atan2(along_y / rb, along_x / ra)

        a0 = angle(self._vertex_point(bc, start))
        a1 = angle(self._vertex_point(bc, end))
        if not along:
            a0, a1 = a1, a0
        sweep = (a1 - a0) % (2 * math.pi)
        for i in range(3):
            turn = math.atan2(rb * y[i], ra * x[i])  # where coordinate i of the curve turns
            for t in (turn, turn + math.pi):
                if (t - a0) % (2 * math.pi) <= sweep:
                    bc.take(tuple(o[k] + ra * math.cos(t) * x[k] + rb * math.sin(t) * y[k] for k in range(3)))

    def _vertex_point(self, bc: _BodyCtx, ref: Any) -> Vec:
        p = self.g.rec(ref, "VERTEX_POINT").params
        return self.g.point(p[1] if len(p) >= 2 else None, bc.ctx.length_m)

    def edge(self, bc: _BodyCtx, rec: Record) -> int:
        got = bc.edges.get(rec.id)
        if isinstance(got, Unsupported):
            raise got
        if got is not None:
            return got
        try:
            p = rec.params
            if len(p) < 5:
                raise Unsupported("bad_reference", "EDGE_CURVE")
            v0 = self.vertex(bc, p[1])
            v1 = self.vertex(bc, p[2])
            curve, reversed_ = self.edge_curve(bc, p[3], ends=(p[1], p[2]))
            along = (as_bool(p[4]) is not False) ^ reversed_
            conic = bc.conics.get(curve)
            if conic is not None:
                self._arc_extent(bc, conic, p[1], p[2], along)
            e = bc.b.edge(curve, v0, v1, "+" if along else "-")
        except GeometryRefused as exc:
            got = Unsupported(exc.reason, "EDGE_CURVE", str(exc))
            bc.edges[rec.id] = got
            raise got from None
        except Unsupported as exc:
            bc.edges[rec.id] = exc
            raise
        bc.edges[rec.id] = e
        return e

    # -- curves -------------------------------------------------------------------------------
    def edge_curve(self, bc: _BodyCtx, ref: Any, depth: int = 0, ends=None) -> tuple[int, bool]:
        """The builder curve of an edge's geometry and whether it runs against the STEP
        curve entity named (a trimmed curve whose sense disagrees with its basis).
        ``ends`` are the edge's two VERTEX_POINTs, which bound a hyperbola or a parabola."""
        if depth > 8:
            raise Unsupported("unsupported_curve", "", "curves nest too deep")
        rec = self.g.rec(ref)
        t = rec.types
        if any(w in t for w in CURVE_WRAPPERS) and not rec.complex:
            p = rec.params
            if len(p) >= 2 and isinstance(p[1], Ref):
                return self.edge_curve(bc, p[1], depth + 1, ends)
            assoc = p[2] if len(p) >= 3 and isinstance(p[2], list) else []
            for a in assoc:
                if self.p.is_a(a, "PCURVE"):
                    return self.pcurve(bc, a), False
            raise Unsupported("unsupported_curve", t[0], "no 3D curve")
        if "TRIMMED_CURVE" in t and not rec.complex:
            p = rec.params
            if len(p) < 5:
                raise Unsupported("bad_reference", "TRIMMED_CURVE")
            c, rev = self.edge_curve(bc, p[1], depth + 1, ends)
            return c, rev ^ (as_bool(p[4]) is False)
        if "PCURVE" in t:
            return self.pcurve(bc, ref), False
        if any(c in t for c in COMPOSITE_CURVES) and not rec.complex:
            return self.composite(bc, rec), False
        if any(rec.has(c) for c in OPEN_CONICS) and not rec.complex and ends is not None:
            return self.open_conic(bc, rec, ends), False
        return self.curve(bc, ref), False

    # -- hyperbolas and parabolas ---------------------------------------------------------
    def _open_conic(self, bc: _BodyCtx, rec: Record) -> "_OpenConic":
        p = rec.params
        if len(p) < 3:
            raise Unsupported("bad_reference", rec.types[0])
        s = bc.ctx.length_m
        o, x, y, _z = self.g.frame(p[1], s)
        if rec.has("HYPERBOLA"):
            if len(p) < 4:
                raise Unsupported("bad_reference", "HYPERBOLA")
            a, b = _num(p[2], "a semi-axis") * s, _num(p[3], "a semi-axis") * s
            if not (a > 0 and b > 0):
                raise Unsupported("bad_geometry", "HYPERBOLA", "a semi-axis that is not positive")
            return _OpenConic("HYPERBOLA", o, x, y, a, b)
        focal = _num(p[2], "a focal distance") * s
        if focal == 0:
            raise Unsupported("bad_geometry", "PARABOLA", "a focal distance of nought")
        return _OpenConic("PARABOLA", o, x, y, focal, focal)

    def open_conic(self, bc: _BodyCtx, rec: Record, ends) -> int:
        """The arc of a hyperbola or a parabola between an edge's two vertices, as the
        exact rational quadratic B-spline it is, running the way the conic does (an XT
        body has neither curve)."""
        try:
            conic = self._open_conic(bc, rec)
            t0, t1 = sorted(conic.parameter(self._vertex_point(bc, v)) for v in ends)
            points, weights, knots, mults = conic.arc(t0, t1)
        except Unsupported as exc:
            raise Unsupported(exc.reason, exc.entity or rec.types[0], exc.detail) from None
        for q in points:
            bc.take(q)
        return bc.b.bspline_curve(2, points, knots, mults, weights=weights)

    # -- composite curves -----------------------------------------------------------------
    def composite(self, bc: _BodyCtx, rec: Record) -> int:
        """A composite curve as one curve: its segments sampled to within a ten-thousandth
        of their size and joined into a B-spline of degree 1 (an XT body has no composite
        curve), closed when it ends where it starts."""
        got = bc.curves.get(rec.id)
        if isinstance(got, Unsupported):
            raise got
        if got is not None:
            return got
        try:
            pts = self._sample(bc, rec, 0)
            # segments meet within a hair of each other: one point there, and the first
            # point again at the end of a closed curve
            size = math.dist(
                [min(q[i] for q in pts) for i in range(3)], [max(q[i] for q in pts) for i in range(3)]
            )
            hair = 1e-9 * max(size, 1e-9)
            joined: list = []
            for q in pts:
                if not joined or math.dist(q, joined[-1]) > hair:
                    joined.append(q)
            if len(joined) > 2 and math.dist(joined[0], joined[-1]) <= hair:
                joined[-1] = joined[0]
            if len(joined) < 2:
                raise Unsupported("degenerate", "COMPOSITE_CURVE", "a composite curve of no length")
            c = self._polyline(bc.b, joined, 3)
        except Unsupported as exc:
            bc.curves[rec.id] = exc
            raise
        except GeometryRefused as exc:
            err = Unsupported(exc.reason, "COMPOSITE_CURVE", str(exc))
            bc.curves[rec.id] = err
            raise err from None
        bc.curves[rec.id] = c
        return c

    def _sample(self, bc: _BodyCtx, rec: Record, depth: int) -> list:
        """Points along a bounded curve in its own direction, metres, at most
        :data:`COMPOSITE_POINTS` of them; each record is sampled once a body."""
        got = bc.samples.get(rec.id)
        if got is not None:
            return got
        if depth > 8:
            raise Unsupported("unsupported_curve", "COMPOSITE_CURVE", "curves nest too deep")
        pts = self._sample_new(bc, rec, depth)
        bc.samples[rec.id] = pts
        return pts

    def _sample_new(self, bc: _BodyCtx, rec: Record, depth: int) -> list:
        t = rec.types
        p = rec.params
        if rec.complex:
            raise Unsupported("unsupported_curve", "complex curve", "in a composite curve")
        if any(c in t for c in COMPOSITE_CURVES):
            out: list = []
            for seg_ref in _list(p[1] if len(p) >= 2 else None, "a composite curve's segments"):
                self.tick()
                seg = self.g.rec(seg_ref, "COMPOSITE_CURVE_SEGMENT", "REPARAMETRISED_COMPOSITE_CURVE_SEGMENT")
                sp = seg.params
                if len(sp) < 3:
                    raise Unsupported("bad_reference", "COMPOSITE_CURVE_SEGMENT")
                pts = self._sample(bc, self.g.rec(sp[2]), depth + 1)
                if as_bool(sp[1]) is False:
                    pts = pts[::-1]
                out.extend(pts)
                self.tick(len(pts))
                if len(out) > COMPOSITE_POINTS:
                    raise Unsupported(
                        "edge_too_long", "COMPOSITE_CURVE", "a composite curve needs too many points"
                    )
            return out
        if any(w in t for w in CURVE_WRAPPERS) and len(p) >= 2:
            return self._sample(bc, self.g.rec(p[1]), depth + 1)
        if "POLYLINE" in t:
            refs = _list(p[1] if len(p) >= 2 else None, "a polyline")
            if len(refs) > COMPOSITE_POINTS:
                raise Unsupported("edge_too_long", "POLYLINE", "a polyline of too many points")
            pts = []
            for q in refs:
                self.tick()
                pts.append(self.g.point(q, bc.ctx.length_m))
            return pts
        if "TRIMMED_CURVE" in t:
            if len(p) < 5:
                raise Unsupported("bad_reference", "TRIMMED_CURVE")
            basis = self.g.rec(p[1])
            f, lo, hi, period = self._evaluator(bc, basis)
            t0 = self._trim_value(bc, basis, f, lo, hi, p[2])
            t1 = self._trim_value(bc, basis, f, lo, hi, p[3])
            forward = as_bool(p[4]) is not False
            if period is not None:
                if forward and t1 <= t0:
                    t1 += period
                elif not forward and t1 >= t0:
                    t1 -= period
            return _adaptive_points(f, t0, t1, tick=self.tick)
        f, lo, hi, _period = self._evaluator(bc, rec)
        if lo is None or hi is None:
            raise Unsupported("unsupported_curve", t[0], "an unbounded curve in a composite curve")
        return _adaptive_points(f, lo, hi, tick=self.tick)

    def _evaluator(self, bc: _BodyCtx, rec: Record):
        """``(point(t), low, high, period)`` of a basic curve in STEP's parametrisation,
        metres (low and high None for an unbounded line)."""
        s, ang = bc.ctx.length_m, bc.ctx.angle_rad
        t = rec.types
        p = rec.params
        if rec.has("LINE") and not rec.complex:
            origin = self.g.point(p[1], s)
            d, mag = self.g.vector(p[2], s)
            return (lambda u: tuple(origin[i] + u * mag * d[i] for i in range(3))), None, None, None
        if (rec.has("CIRCLE") or rec.has("ELLIPSE")) and not rec.complex:
            o, x, y, _z = self.g.frame(p[1], s)
            ra = _num(p[2], "a radius") * s
            rb = ra if rec.has("CIRCLE") else _num(p[3], "a semi-axis") * s

            def conic(u: float):
                c, sn = math.cos(u * ang), math.sin(u * ang)
                return tuple(o[i] + ra * c * x[i] + rb * sn * y[i] for i in range(3))

            period = 2.0 * math.pi / ang
            return conic, 0.0, period, period
        if any(rec.has(c) for c in OPEN_CONICS) and not rec.complex:
            return self._open_conic(bc, rec).point, None, None, None
        if any(n in t for n in BSPLINE_CURVES) or "B_SPLINE_CURVE" in t:
            from ...tessellate import nurbs
            from ...tessellate.topology import FaceFailed

            degree, points, weights, knots, mults, _closed = self.bspline_curve(rec, s, 3)
            try:
                U = nurbs.knot_vector([float(k) for k in knots], list(mults), len(points), degree)
                curve = nurbs.BSplineCurve(
                    degree, _homogeneous(points, weights), U, weights is not None, False
                )
            except FaceFailed as exc:
                raise Unsupported(exc.reason, t[0], exc.detail) from None
            return curve.point, curve.lo, curve.hi, None
        raise Unsupported(
            "unsupported_curve", t[0] if not rec.complex else "complex curve", "in a composite curve"
        )

    def _trim_value(self, bc: _BodyCtx, basis: Record, f, lo, hi, trim) -> float:
        """A trimming select as the basis curve's parameter: a parameter value, else the
        parameter of the nearest point to a trimming point."""
        value = None
        point = None
        for sel in trim if isinstance(trim, list) else []:
            if isinstance(sel, Typed) and sel.name == "PARAMETER_VALUE":
                value = _num(sel.value, "a parameter")
            elif isinstance(sel, Ref):
                point = self.g.point(sel, bc.ctx.length_m)
        if value is not None:
            return value
        if point is None:
            raise Unsupported("bad_geometry", "TRIMMED_CURVE", "a trim with no value")
        if basis.has("LINE"):
            origin = f(0.0)
            ahead = f(1.0)
            d = tuple(ahead[i] - origin[i] for i in range(3))
            dd = sum(c * c for c in d)
            if not dd > 0:
                raise Unsupported("bad_geometry", "LINE", "a line of no length")
            return sum((point[i] - origin[i]) * d[i] for i in range(3)) / dd
        if any(basis.has(c) for c in OPEN_CONICS) and not basis.complex:
            return self._open_conic(bc, basis).parameter(point)
        # the nearest of a fine sampling, then halved steps about it
        best_t, best = lo, math.inf
        n = 512
        for k in range(n + 1):
            u = lo + (hi - lo) * k / n
            dist = math.dist(f(u), point)
            if dist < best:
                best, best_t = dist, u
        step = (hi - lo) / n
        for _ in range(40):
            step *= 0.5
            for u in (best_t - step, best_t + step):
                if lo <= u <= hi:
                    dist = math.dist(f(u), point)
                    if dist < best:
                        best, best_t = dist, u
        return best_t

    def curve(self, bc: _BodyCtx, ref: Any) -> int:
        """The builder curve of a basic curve entity, cached per body."""
        rid = int(ref) if isinstance(ref, Ref) else -1
        got = bc.curves.get(rid)
        if isinstance(got, Unsupported):
            raise got
        if got is not None:
            return got
        try:
            c = self._curve(bc, self.g.rec(ref))
        except Unsupported as exc:
            bc.curves[rid] = exc
            raise
        except GeometryRefused as exc:
            err = Unsupported(exc.reason, "", str(exc))
            bc.curves[rid] = err
            raise err from None
        bc.curves[rid] = c
        return c

    def _curve(self, bc: _BodyCtx, rec: Record) -> int:
        b, s = bc.b, bc.ctx.length_m
        t = rec.types
        g = self.g
        if rec.has("LINE") and not rec.complex:
            p = rec.params
            d, _mag = g.vector(p[2], s)
            return b.line(g.point(p[1], s), d)
        if (rec.has("CIRCLE") or rec.has("ELLIPSE")) and not rec.complex:
            p = rec.params
            o, x, y, z = g.frame(p[1], s)
            ra = _num(p[2], "a radius") * s
            rb = ra if rec.has("CIRCLE") else _num(p[3], "a semi-axis") * s
            # no extent here: a revolved arc's whole circle reaches far past the part, so an
            # edge takes the box of the part it runs along (edge)
            c = b.circle(o, z, x, ra) if rec.has("CIRCLE") else b.ellipse(o, z, x, ra, rb)
            bc.conics[c] = (o, x, y, ra, rb)
            return c
        if any(n in t for n in BSPLINE_CURVES) or "B_SPLINE_CURVE" in t:
            degree, points, weights, knots, mults, _closed = self.bspline_curve(rec, s, 3)
            for q in points:  # the control polygon bounds the curve
                bc.take(q)
            closed = _closes_curve(degree, points, weights, knots, mults)
            return b.bspline_curve(degree, points, knots, mults, weights=weights, closed=closed)
        if rec.has("POLYLINE") and not rec.complex:
            pts = [
                g.point(q, s) for q in _list(rec.params[1] if len(rec.params) >= 2 else None, "a polyline")
            ]
            return self._polyline(b, pts, 3)
        raise Unsupported("unsupported_curve", t[0] if not rec.complex else "complex curve")

    def _polyline(self, b: BrepBuilder, pts: list, dim: int) -> int:
        """A B-spline of degree 1 through ``pts`` (closed when it ends where it starts)."""
        if len(pts) < 2:
            raise Unsupported("bad_geometry", "POLYLINE", "a polyline of fewer than two points")
        n = len(pts)
        knots = [float(i) for i in range(n)]
        mults = [2] + [1] * (n - 2) + [2]
        closed = n > 2 and all(pts[0][i] == pts[-1][i] for i in range(dim))
        return b.bspline_curve(1, pts, knots, mults, dim=dim, closed=closed)

    def bspline_curve(self, rec: Record, scale: float, dim: int):
        """``(degree, points, weights or None, knots, multiplicities, closed)`` of a B-spline
        curve entity, points ``dim``-dimensional (lengths scaled when 3D)."""
        a = _bspline_parts(rec, "curve")
        form = a.get("form") or ""
        degree = _int(a.get("degree"), "a degree")
        refs = _list(a.get("points"), "control points")
        points = []
        for q in refs:
            self.tick()
            points.append(self.g.point(q, scale) if dim == 3 else self.g.point2(q))
        n = len(points)
        if not 1 <= degree <= 32 or n < degree + 1:
            raise Unsupported("bad_geometry", form, f"{n} control points of degree {degree}")
        knots, mults = _knots(a, "", form, n, degree)
        weights = None
        if a.get("rational") is not None:
            weights = [_num(w, "a weight") for w in _list(a["rational"], "weights")]
            if all(abs(w - weights[0]) <= 1e-12 * abs(weights[0]) for w in weights) and weights[0] > 0:
                weights = None  # equal weights: the same curve, not rational
        closed = as_bool(a.get("closed")) is True
        return degree, points, weights, knots, mults, closed

    def pcurve(self, bc: _BodyCtx, ref: Any) -> int:
        """An SP-curve for a PCURVE whose (u, v) curve is a B-spline or a polyline on a
        surface whose (u, v) is XT's (see the module notes)."""
        rid = int(ref) if isinstance(ref, Ref) else -1
        got = bc.curves.get(rid)
        if isinstance(got, Unsupported):
            raise got
        if got is not None:
            return got
        try:
            sp = self._pcurve(bc, self.g.rec(ref, "PCURVE"))
        except Unsupported as exc:
            bc.curves[rid] = exc
            raise
        except GeometryRefused as exc:
            err = Unsupported(exc.reason, "PCURVE", str(exc))
            bc.curves[rid] = err
            raise err from None
        bc.curves[rid] = sp
        return sp

    def _pcurve(self, bc: _BodyCtx, rec: Record) -> int:
        p = rec.params
        if len(p) < 3:
            raise Unsupported("bad_reference", "PCURVE")
        srec = self.g.rec(p[1])
        su, sv = self._uv_scales(bc, srec)
        drep = self.g.rec(p[2], "DEFINITIONAL_REPRESENTATION")
        items = drep.params[1] if len(drep.params) >= 2 and isinstance(drep.params[1], list) else []
        if len(items) != 1:
            raise Unsupported("unsupported_curve", "PCURVE", "a definitional representation of several items")
        crec = self.g.rec(items[0])
        b = bc.b
        if any(n in crec.types for n in BSPLINE_CURVES) or "B_SPLINE_CURVE" in crec.types:
            degree, points, weights, knots, mults, _closed = self.bspline_curve(crec, 1.0, 2)
            pts = [(u * su, v * sv) for u, v in points]
            uv = b.bspline_curve(degree, pts, knots, mults, weights=weights, dim=2)
        elif crec.has("POLYLINE") and not crec.complex:
            raw = [self.g.point2(q) for q in _list(crec.params[1], "a polyline")]
            uv = self._polyline(b, [(u * su, v * sv) for u, v in raw], 2)
        else:
            raise Unsupported("unsupported_curve", "PCURVE", f"a curve in (u, v) of type {crec.types[0]}")
        return b.sp_curve(self.surface(bc, p[1]), uv)

    def _uv_scales(self, bc: _BodyCtx, srec: Record) -> tuple[float, float]:
        """How a surface's STEP (u, v) becomes XT's: lengths to metres, angles to radians."""
        length, angle = bc.ctx.length_m, bc.ctx.angle_rad
        t = srec.types
        if "PLANE" in t:
            return length, length
        if "CYLINDRICAL_SURFACE" in t or "CONICAL_SURFACE" in t:
            return angle, length
        if "SPHERICAL_SURFACE" in t or "TOROIDAL_SURFACE" in t or "DEGENERATE_TOROIDAL_SURFACE" in t:
            return angle, angle
        if any(n in t for n in BSPLINE_SURFACES) or "B_SPLINE_SURFACE" in t:
            return 1.0, 1.0
        raise Unsupported("unsupported_curve", "PCURVE", f"a pcurve on a {t[0]}")

    def _against(self, ref: Any) -> bool:
        """Whether a swept or spun surface's curve runs against the curve it is built along:
        an odd number of trimmed curves with ``sense_agreement`` false on the way down
        through wrappers and trims, as :meth:`section` takes them."""
        flip = False
        r = self.p.get(ref)
        for _ in range(10):
            if r is None or r.complex:
                break
            if any(w in r.types for w in CURVE_WRAPPERS) and len(r.params) >= 2:
                r = self.p.get(r.params[1])
            elif "TRIMMED_CURVE" in r.types and len(r.params) >= 5:
                flip ^= as_bool(r.params[4]) is False
                r = self.p.get(r.params[1])
            else:
                break
        return flip

    def _profile(self, bc: _BodyCtx, ref: Any, origin: Vec, axis: Vec) -> int:
        """A spun surface's curve: :meth:`section`, except that an unbounded LINE (through
        any wrappers) becomes an XT trimmed line, bounded to cover the body once it is
        built (:meth:`_bound_lines`); a spun surface over an unbounded line cannot be
        inverted."""
        r = self.g.rec(ref)
        for _ in range(10):
            if any(w in r.types for w in CURVE_WRAPPERS) and not r.complex and len(r.params) >= 2:
                r = self.g.rec(r.params[1])
            else:
                break
        if not (r.has("LINE") and not r.complex):
            return self.section(bc, ref)
        b = bc.b
        line = self.curve(bc, Ref(r.id))
        p0, d = b.get(line, "pvec"), b.get(line, "direction")
        ends = [tuple(p0[i] + k * d[i] for i in range(3)) for k in (-1.0, 1.0)]
        trimmed = b.trimmed(line, -1.0, 1.0, ends[0], ends[1])
        bc.open_lines.append((trimmed, p0, d, origin, axis))
        return trimmed

    def _bound_lines(self, bc: _BodyCtx) -> None:
        """Trim each spun line to cover the body's box: a point of the surface within the
        box's sphere (centre c, radius R) is turned from a point of the line that lies
        within R plus twice c's distance from the axis of c."""
        if not bc.open_lines or not all(math.isfinite(x) for x in bc.lo + bc.hi):
            return
        c = tuple(0.5 * (bc.lo[i] + bc.hi[i]) for i in range(3))
        radius = 0.5 * math.dist(bc.lo, bc.hi)
        for trimmed, p0, d, origin, axis in bc.open_lines:
            w = tuple(c[i] - origin[i] for i in range(3))
            along = sum(w[i] * axis[i] for i in range(3))
            rho = math.sqrt(max(sum(x * x for x in w) - along * along, 0.0))
            reach = max(radius + 2.0 * rho, 1e-9) * (1.0 + 1e-6)
            mid = sum((c[i] - p0[i]) * d[i] for i in range(3))
            t0, t1 = mid - reach, mid + reach
            bc.b.set(
                trimmed,
                parm_1=t0,
                parm_2=t1,
                point_1=tuple(p0[i] + t0 * d[i] for i in range(3)),
                point_2=tuple(p0[i] + t1 * d[i] for i in range(3)),
            )

    def section(self, bc: _BodyCtx, ref: Any, depth: int = 0) -> int:
        """The curve of a swept or spun surface: a trimmed line or circle keeps its trim
        (as an XT trimmed curve), anything else is its basis curve."""
        if depth > 8:
            raise Unsupported("unsupported_surface", "", "curves nest too deep")
        rec = self.g.rec(ref)
        t = rec.types
        if any(w in t for w in CURVE_WRAPPERS) and not rec.complex and len(rec.params) >= 2:
            return self.section(bc, rec.params[1], depth + 1)
        if "TRIMMED_CURVE" in t and not rec.complex:
            return self._trimmed(bc, rec, depth)
        return self.curve(bc, ref)

    def _trimmed(self, bc: _BodyCtx, rec: Record, depth: int) -> int:
        p = rec.params
        if len(p) < 5:
            raise Unsupported("bad_reference", "TRIMMED_CURVE")
        basis_rec = self.g.rec(p[1])
        basis = self.section(bc, p[1], depth + 1)
        b, s, a = bc.b, bc.ctx.length_m, bc.ctx.angle_rad
        line = basis_rec.has("LINE") and not basis_rec.complex
        conic = (basis_rec.has("CIRCLE") or basis_rec.has("ELLIPSE")) and not basis_rec.complex
        if not (line or conic):
            return basis  # a B-spline's own range bounds it
        nodes = b.nodes[basis][1]
        params = []
        points = []
        for trim in (p[2], p[3]):
            t_val = None
            q = None
            for sel in trim if isinstance(trim, list) else []:
                if isinstance(sel, Typed) and sel.name == "PARAMETER_VALUE":
                    t_val = _num(sel.value, "a parameter")
                elif isinstance(sel, (int, float)) and not isinstance(sel, bool) and not isinstance(sel, Ref):
                    t_val = float(sel)
                elif isinstance(sel, Ref):
                    q = self.g.point(sel, s)
            if line:
                origin, direction = nodes["pvec"], nodes["direction"]
                _d, magnitude = self.g.vector(basis_rec.params[2], s)
                if q is not None:
                    t_xt = sum((q[i] - origin[i]) * direction[i] for i in range(3))
                elif t_val is not None:
                    t_xt = t_val * magnitude
                else:
                    raise Unsupported("bad_geometry", "TRIMMED_CURVE", "a trim with no value")
                q = tuple(origin[i] + t_xt * direction[i] for i in range(3))
            else:
                centre, x = nodes["centre"], nodes["x_axis"]
                normal = nodes["normal"]
                y = _cross(normal, x)
                if t_val is not None:
                    t_xt = t_val * a
                elif q is not None:
                    d = tuple(q[i] - centre[i] for i in range(3))
                    ra = nodes.get("radius") or nodes.get("major_radius")
                    rb = nodes.get("radius") or nodes.get("minor_radius")
                    t_xt = math.atan2(
                        sum(d[i] * y[i] for i in range(3)) / rb, sum(d[i] * x[i] for i in range(3)) / ra
                    )
                else:
                    raise Unsupported("bad_geometry", "TRIMMED_CURVE", "a trim with no value")
                ra = nodes.get("radius") or nodes.get("major_radius")
                rb = nodes.get("radius") or nodes.get("minor_radius")
                q = tuple(
                    centre[i] + ra * math.cos(t_xt) * x[i] + rb * math.sin(t_xt) * y[i] for i in range(3)
                )
            params.append(t_xt)
            points.append(q)
        t0, t1 = params
        if as_bool(p[4]) is False:  # the trimmed curve runs against its basis
            t0, t1 = t1, t0
            points.reverse()
        if conic and t1 < t0:
            t1 += 2.0 * math.pi
        return b.trimmed(basis, t0, t1, points[0], points[1])

    # -- surfaces ---------------------------------------------------------------------------
    def surface(self, bc: _BodyCtx, ref: Any) -> int:
        rid = int(ref) if isinstance(ref, Ref) else -1
        got = bc.surfaces.get(rid)
        if isinstance(got, Unsupported):
            raise got
        if got is not None:
            return got
        try:
            sf = self._surface(bc, self.g.rec(ref), 0)
        except Unsupported as exc:
            if not exc.entity:
                exc.entity = (self.p.type_of(rid) or ("",))[0]
            bc.surfaces[rid] = exc
            raise
        except GeometryRefused as exc:
            err = Unsupported(exc.reason, (self.p.type_of(rid) or ("",))[0], str(exc))
            bc.surfaces[rid] = err
            raise err from None
        bc.surfaces[rid] = sf
        return sf

    def _surface(self, bc: _BodyCtx, rec: Record, depth: int) -> int:
        if depth > 8:
            raise Unsupported("unsupported_surface", rec.types[0], "surfaces nest too deep")
        b, s, ang = bc.b, bc.ctx.length_m, bc.ctx.angle_rad
        g = self.g
        t = rec.types
        p = rec.params
        if not rec.complex:
            if "PLANE" in t:
                o, x, _y, z = g.frame(p[1], s)
                return b.plane(o, z, x)
            if "CYLINDRICAL_SURFACE" in t:
                o, x, _y, z = g.frame(p[1], s)
                return b.cylinder(o, z, _num(p[2], "a radius") * s, x)
            if "CONICAL_SURFACE" in t:
                o, x, _y, z = g.frame(p[1], s)
                semi = _num(p[3], "a semi-angle") * ang
                return b.cone(o, z, _num(p[2], "a radius") * s, math.sin(semi), math.cos(semi), x)
            if "SPHERICAL_SURFACE" in t:
                o, x, y, z = g.frame(p[1], s)
                r = _num(p[2], "a radius") * s
                bc.extent(o, ((x, r), (y, r), (z, r)))
                return b.sphere(o, r, z, x)
            if "TOROIDAL_SURFACE" in t or "DEGENERATE_TOROIDAL_SURFACE" in t:
                o, x, y, z = g.frame(p[1], s)
                big, small = _num(p[2], "a radius") * s, _num(p[3], "a radius") * s
                bc.extent(o, ((x, abs(big) + small), (y, abs(big) + small), (z, small)))
                return b.torus(o, z, big, small, x)
            if "SURFACE_OF_LINEAR_EXTRUSION" in t:
                d, mag = g.vector(p[2], s)
                swept = b.swept(self.section(bc, p[1]), (d[0] * mag, d[1] * mag, d[2] * mag))
                # the section is built along the curve it is trimmed from
                return b.reverse(swept) if self._against(p[1]) else swept
            if "SURFACE_OF_REVOLUTION" in t:
                # STEP turns the curve by u and runs along it by v; XT's spun surface the
                # other way round, so its natural normal is the opposite one (unless the
                # profile runs against the curve it is built along)
                origin, axis = g.axis1(p[2], s)
                spun = b.spun(self._profile(bc, p[1], origin, axis), origin, axis)
                return spun if self._against(p[1]) else b.reverse(spun)
            if "OFFSET_SURFACE" in t:
                base = self.surface(bc, p[1])
                dist = _num(p[2], "an offset") * s
                if b.get(base, "sense", "+") == "-":
                    # an XT offset surface's normal is its basis's own: offset the basis as
                    # built the other way, then turn the offset round
                    return b.reverse(b.offset(b.reverse(base), -dist))
                return b.offset(base, dist)
            if "RECTANGULAR_TRIMMED_SURFACE" in t:
                base = self.surface(bc, p[1])
                usense = as_bool(p[6]) if len(p) > 6 else True
                vsense = as_bool(p[7]) if len(p) > 7 else True
                if (usense is False) != (vsense is False):
                    return b.reverse(base)
                return base
            if "CURVE_BOUNDED_SURFACE" in t:
                return self.surface(bc, p[1])
        if any(n in t for n in BSPLINE_SURFACES) or "B_SPLINE_SURFACE" in t:
            return self._bspline_surface(bc, rec)
        raise Unsupported("unsupported_surface", t[0] if not rec.complex else "complex surface")

    def _bspline_surface(self, bc: _BodyCtx, rec: Record) -> int:
        a = _bspline_parts(rec, "surface")
        form = a.get("form") or ""
        pu, pv = _int(a.get("u_degree"), "a degree"), _int(a.get("v_degree"), "a degree")
        grid = _list(a.get("points"), "control points")
        rows = []
        for row in grid:
            pts = []
            for q in _list(row, "a row of control points"):
                self.tick()
                pts.append(self.g.point(q, bc.ctx.length_m))
            rows.append(pts)
        nu = len(rows)
        nv = len(rows[0]) if rows else 0
        if not nu or not nv or any(len(r) != nv for r in rows):
            raise Unsupported("bad_geometry", form, "the control points are not a grid")
        for row in rows:
            self.tick(len(row))
            for q in row:
                bc.take(q)
        if not (1 <= pu <= 32 and 1 <= pv <= 32) or nu < pu + 1 or nv < pv + 1:
            raise Unsupported("bad_geometry", form, f"{nu} x {nv} control points of degree {pu}, {pv}")
        uk, um = _knots(a, "u_", form, nu, pu)
        vk, vm = _knots(a, "v_", form, nv, pv)
        weights = None
        if a.get("rational") is not None:
            weights = []
            for row in _list(a["rational"], "weights"):
                self.tick(len(row) if isinstance(row, list) else 1)
                weights.append([_num(w, "a weight") for w in _list(row, "weights")])
            flat = [w for row in weights for w in row]
            if flat and flat[0] > 0 and all(abs(w - flat[0]) <= 1e-12 * flat[0] for w in flat):
                weights = None
        u_closed, v_closed = _closes_surface(pu, pv, rows, weights, uk, um, vk, vm)
        return bc.b.bspline_surface(
            pu, pv, rows, uk, um, vk, vm, weights=weights, u_closed=u_closed, v_closed=v_closed
        )


# --------------------------------------------------------------------------- sampled curves
def _adaptive_points(
    f, t0: float, t1: float, depth: int = 12, limit: int = COMPOSITE_POINTS, tick=None
) -> list:
    """Points along ``f`` from ``t0`` to ``t1``: 16 even steps, then each step halved while
    its midpoint lies farther than a ten-thousandth of the curve's size from the chord;
    ``tick`` is called for each point evaluated."""
    n0 = 16
    ts = [t0 + (t1 - t0) * k / n0 for k in range(n0 + 1)]
    pts = [f(t) for t in ts]
    lo = [min(q[i] for q in pts) for i in range(3)]
    hi = [max(q[i] for q in pts) for i in range(3)]
    tol = max(1e-4 * math.dist(lo, hi), 1e-9)
    out = [pts[0]]
    for k in range(n0):
        stack = [(ts[k + 1], pts[k + 1], 0)]
        ta, pa = ts[k], pts[k]
        while stack:
            tb, pb, d = stack[-1]
            tm = 0.5 * (ta + tb)
            if tick is not None:
                tick()
            pm = f(tm)
            mid = tuple(0.5 * (pa[i] + pb[i]) for i in range(3))
            if d < depth and math.dist(pm, mid) > tol:
                stack.append((tm, pm, d + 1))
                continue
            stack.pop()
            out.append(pb)
            if len(out) > limit:
                raise Unsupported(
                    "edge_too_long", "COMPOSITE_CURVE", "a composite curve needs too many points"
                )
            ta, pa = tb, pb
    for q in out:
        if not all(math.isfinite(c) for c in q):
            raise Unsupported("non_finite", "COMPOSITE_CURVE", "a point that is not finite")
    return out


# --------------------------------------------------------------------------- closed B-splines
def _homogeneous(points, weights):
    if weights is None:
        return [tuple(p) for p in points]
    return [tuple(x * w for x in p) + (w,) for p, w in zip(points, weights, strict=True)]


def _diag(points) -> float:
    lo = [min(p[i] for p in points) for i in range(3)]
    hi = [max(p[i] for p in points) for i in range(3)]
    return math.dist(lo, hi)


def _closes_curve(degree, points, weights, knots, mults) -> bool:
    """Whether a B-spline curve ends where it starts (evaluated, whatever the file's flag
    says: a closed edge on it then goes all the way round)."""
    from ...tessellate import nurbs
    from ...tessellate.topology import FaceFailed

    try:
        U = nurbs.knot_vector([float(k) for k in knots], list(mults), len(points), degree)
        c = nurbs.BSplineCurve(degree, _homogeneous(points, weights), U, weights is not None, False)
        a, b = c.point(c.lo), c.point(c.hi)
    except (FaceFailed, ZeroDivisionError, ValueError, OverflowError):
        return False
    return math.dist(a, b) <= CLOSURE * max(_diag(points), 1e-9)


def _closes_surface(pu, pv, rows, weights, uk, um, vk, vm) -> tuple[bool, bool]:
    """Whether a B-spline surface closes on itself along u and along v: its boundary
    curves at the two ends of the range evaluated at a few points, so that a periodic
    surface whose control rows do not repeat is known closed too."""
    from ...tessellate import nurbs
    from ...tessellate.topology import FaceFailed

    flat = [q for row in rows for q in row]
    try:
        U = nurbs.knot_vector([float(k) for k in uk], list(um), len(rows), pu)
        V = nurbs.knot_vector([float(k) for k in vk], list(vm), len(rows[0]), pv)
        hrows = [_homogeneous(row, None if weights is None else weights[i]) for i, row in enumerate(rows)]
        srf = nurbs.BSplineSurface(pu, pv, hrows, U, V, weights is not None, False, False)
        tol = CLOSURE * max(_diag(flat), 1e-9)
        samples = [k / 4.0 for k in range(5)]
        u_closed = all(
            math.dist(srf.point(srf.ulo, v), srf.point(srf.uhi, v)) <= tol
            for v in (srf.vlo + f * (srf.vhi - srf.vlo) for f in samples)
        )
        v_closed = all(
            math.dist(srf.point(u, srf.vlo), srf.point(u, srf.vhi)) <= tol
            for u in (srf.ulo + f * (srf.uhi - srf.ulo) for f in samples)
        )
    except (FaceFailed, ZeroDivisionError, ValueError, OverflowError):
        return False, False
    # a boundary that collapses to a point (a pole) is not a seam
    if u_closed and _collapsed(srf, "u"):
        u_closed = False
    if v_closed and _collapsed(srf, "v"):
        v_closed = False
    return u_closed, v_closed


def _collapsed(srf, direction: str) -> bool:
    """Whether the boundary curve at the low end of ``direction`` is a single point."""
    if direction == "u":
        pts = [srf.point(srf.ulo, srf.vlo + f * (srf.vhi - srf.vlo)) for f in (0.0, 0.5, 1.0)]
    else:
        pts = [srf.point(srf.ulo + f * (srf.uhi - srf.ulo), srf.vlo) for f in (0.0, 0.5, 1.0)]
    return math.dist(pts[0], pts[1]) == 0.0 and math.dist(pts[1], pts[2]) == 0.0


__all__ = [
    "BSPLINE_CURVES",
    "BSPLINE_SURFACES",
    "FACES",
    "SHELLS",
    "SOLIDS",
    "Geometry",
    "MappedBody",
    "Mapper",
    "Unsupported",
]
