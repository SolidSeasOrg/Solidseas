# The STEP entities the export writes, as values that can be written and evaluated.
#
# Derived work. The Part 21 forms of the geometric and topological entities (the
# B-spline curves and surfaces with knots, rational ones as complex instances, the
# placements, edges, loops, faces, shells and solids) follow those that
# XtStepMapper writes in
#   BlinkingSun/sldprt2step, file sldprt2step_lib/step/mapper.py (emit_bspline_curve,
#   emit_bspline_surface, StepWriter.axis2, curve, _surface, convert_face,
#   convert_shell, convert_body)
#   https://github.com/BlinkingSun/sldprt2step, commit fa954124f4f126e0c465c8f96454978ac80b812e
#   Licensed under the Apache License, Version 2.0. sldprt2step is a port of
#   open-sld-to-step 0.1.0 (Apache-2.0). See NOTICE in the SolidSeas repository.
# Modified for SolidSeas (2026-10-03): each entity is a value object written once per
# file and evaluated, from the very numbers written, by SolidSeas' own curve and
# surface evaluators for the writer's checks; labels are 'NONE' as SOLIDWORKS writes
# them; a VECTOR's magnitude is 1000.0 so that a line's parameter stays in metres, as
# SOLIDWORKS writes it; B-spline knots are written as Parasolid holds them (upstream
# rescaled them); degenerate tori, offset surfaces, extrusions and revolutions carry
# their own evaluators.
"""The STEP entities the export writes, as values.

Each geometric item holds the numbers it writes, already rounded as
:mod:`.part21` writes them (lengths in millimetres), so that :meth:`evaluator`
gives SolidSeas' own evaluator (:mod:`solidseas.tessellate`, in metres) of
exactly what a reader will get. ISO 10303-42 parametrises PLANE, the analytic
surfaces, LINE, CIRCLE, ELLIPSE and the B-splines as Parasolid does; a
SURFACE_OF_REVOLUTION has the angle as u and the profile's parameter as v,
the other way round from Parasolid's SPUN_SURF.

Items compare by identity: one written edge, surface or point is one entity,
written once (:attr:`.part21.Writer.memo`), and referred to from every face that
uses it.
"""

import math

from ..tessellate import curves as xc
from ..tessellate import nurbs
from ..tessellate import surfaces as xs
from . import part21 as p21
from .bspline import euclidean, knot_groups

NONE = p21.NONE
real, logical = p21.real, p21.logical


def _unit(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if not n > 1e-300 or not math.isfinite(n):
        raise ValueError("a direction of no length")
    return (v[0] / n, v[1] / n, v[2] / n)


def _perp(z):
    a = (1.0, 0.0, 0.0) if abs(z[0]) < 0.9 else (0.0, 1.0, 0.0)
    d = a[0] * z[0] + a[1] * z[1] + a[2] * z[2]
    return _unit((a[0] - d * z[0], a[1] - d * z[1], a[2] - d * z[2]))


def direction(v) -> tuple[float, float, float]:
    """A unit direction as written."""
    u = _unit(v)
    return (p21.rounded(u[0]), p21.rounded(u[1]), p21.rounded(u[2]))


def point_mm(p) -> tuple[float, float, float]:
    """A point in metres as written, in millimetres."""
    return (p21.mm(p[0]), p21.mm(p[1]), p21.mm(p[2]))


def metres(p) -> tuple[float, float, float]:
    return (p[0] / p21.SCALE, p[1] / p21.SCALE, p[2] / p21.SCALE)


class Item:
    """An entity written once a file: :meth:`write` gives its id."""

    __slots__ = ("_ev",)
    kind = "ITEM"

    def write(self, w: p21.Writer) -> int:
        got = w.memo.get(self)
        if got is None:
            got = w.memo[self] = self._write(w)
        return got

    def _write(self, w: p21.Writer) -> int:
        raise NotImplementedError

    def evaluator(self):
        ev = getattr(self, "_ev", None)
        if ev is None:
            ev = self._ev = self._evaluator()
        return ev

    def _evaluator(self):
        raise NotImplementedError


# --------------------------------------------------------------------------- placements
class Placement(Item):
    """AXIS2_PLACEMENT_3D: location (mm), axis and ref_direction as written."""

    __slots__ = ("location", "axis", "ref")
    kind = "AXIS2_PLACEMENT_3D"

    def __init__(self, location, axis, ref) -> None:
        self.location, self.axis, self.ref = location, axis, ref

    @classmethod
    def make(cls, origin_m, z, x) -> "Placement":
        """From an origin in metres, an axis and an x direction, made perpendicular to the
        axis as STEP requires."""
        zz = _unit(z)
        d = x[0] * zz[0] + x[1] * zz[1] + x[2] * zz[2]
        xx = (x[0] - d * zz[0], x[1] - d * zz[1], x[2] - d * zz[2])
        n = math.sqrt(xx[0] ** 2 + xx[1] ** 2 + xx[2] ** 2)
        xx = _perp(zz) if not n > 1e-12 else (xx[0] / n, xx[1] / n, xx[2] / n)
        return cls(point_mm(origin_m), direction(zz), direction(xx))

    def _write(self, w):
        p = w.point(self.location)
        z = w.direction(self.axis)
        x = w.direction(self.ref)
        return w.add(f"AXIS2_PLACEMENT_3D({NONE},#{p},#{z},#{x})")

    def frame(self):
        """(origin in metres, axis, x direction)."""
        return metres(self.location), self.axis, self.ref


# --------------------------------------------------------------------------- curves
class Curve(Item):
    __slots__ = ()
    closed = False  # a closed curve: its parameter wraps (circle, ellipse)


class Line(Curve):
    """LINE through ``point`` (mm) along VECTOR(``direction``, ``magnitude`` mm): the
    parameter is ``magnitude`` / 1000 metres a unit, one metre for SOLIDWORKS' 1000."""

    __slots__ = ("point", "direction", "magnitude")
    kind = "LINE"

    def __init__(self, point, direction_, magnitude: float) -> None:
        self.point, self.direction, self.magnitude = point, direction_, magnitude

    def _write(self, w):
        p = w.point(self.point)
        d = w.direction(self.direction)
        v = w.add(f"VECTOR({NONE},#{d},{real(self.magnitude)})")
        return w.add(f"LINE({NONE},#{p},#{v})")

    def _evaluator(self):
        s = self.magnitude / p21.SCALE
        d = self.direction
        return xc.Line(metres(self.point), (d[0] * s, d[1] * s, d[2] * s), 1)


class Circle(Curve):
    __slots__ = ("placement", "radius")
    kind = "CIRCLE"
    closed = True

    def __init__(self, placement: Placement, radius: float) -> None:
        self.placement, self.radius = placement, radius

    def _write(self, w):
        return w.add(f"CIRCLE({NONE},#{self.placement.write(w)},{real(self.radius)})")

    def _evaluator(self):
        c, z, x = self.placement.frame()
        r = self.radius / p21.SCALE
        return xc.Conic("CIRCLE", c, z, x, r, r, 1)


class Ellipse(Curve):
    __slots__ = ("placement", "semi1", "semi2")
    kind = "ELLIPSE"
    closed = True

    def __init__(self, placement: Placement, semi1: float, semi2: float) -> None:
        self.placement, self.semi1, self.semi2 = placement, semi1, semi2

    def _write(self, w):
        return w.add(f"ELLIPSE({NONE},#{self.placement.write(w)},{real(self.semi1)},{real(self.semi2)})")

    def _evaluator(self):
        c, z, x = self.placement.frame()
        return xc.Conic("ELLIPSE", c, z, x, self.semi1 / p21.SCALE, self.semi2 / p21.SCALE, 1)


def _knots(U: list[float], degree: int) -> tuple[list[int], list[float]]:
    """A knot vector as written: distinct values rounded, multiplicities added up where
    two values round to one. Raises ``ValueError`` when that leaves a knot repeated more
    often than a B-spline of this degree allows."""
    mults, knots = knot_groups([p21.rounded(k) for k in U])
    for i, m in enumerate(mults):
        cap = degree + 1 if i in (0, len(mults) - 1) else degree
        if m > cap:
            raise ValueError(f"a knot of multiplicity {m} in a B-spline of degree {degree}")
    if len(knots) < 2:
        raise ValueError("a B-spline with no span")
    return mults, knots


class BSplineCurve(Curve):
    """B_SPLINE_CURVE_WITH_KNOTS (rational: the complex instance with
    RATIONAL_B_SPLINE_CURVE), from a clamped :class:`nurbs.BSplineCurve` in metres."""

    __slots__ = ("degree", "points", "weights", "mults", "knots", "is_closed")
    kind = "B_SPLINE_CURVE_WITH_KNOTS"

    def __init__(self, spline: nurbs.BSplineCurve) -> None:
        pts, ws = euclidean(spline.cps, spline.rational)
        if any(len(p) != 3 for p in pts):
            raise ValueError("a B-spline curve that is not three-dimensional")
        self.degree = spline.p
        self.points = [point_mm(p) for p in pts]
        self.weights = [p21.rounded(x) for x in ws] if ws is not None else None
        if self.weights is not None and not all(x > 0.0 for x in self.weights):
            raise ValueError("a weight that is not positive")
        self.mults, self.knots = _knots(spline.U, spline.p)
        if sum(self.mults) != len(self.points) + self.degree + 1:
            raise ValueError("knots and control points do not match")
        a, b = self.points[0], self.points[-1]
        self.is_closed = max(abs(a[i] - b[i]) for i in range(3)) <= 1e-9

    def _write(self, w):
        pts = p21.refs(w.point(p) for p in self.points)
        knots = f"({','.join(str(m) for m in self.mults)}),({','.join(real(k) for k in self.knots)})"
        closed = logical(self.is_closed)
        if self.weights is None:
            return w.add(
                f"B_SPLINE_CURVE_WITH_KNOTS({NONE},{self.degree},{pts},.UNSPECIFIED.,{closed},.F.,"
                f"{knots},.UNSPECIFIED.)"
            )
        ws = ",".join(real(x) for x in self.weights)
        return w.add(
            f"(BOUNDED_CURVE()B_SPLINE_CURVE({self.degree},{pts},.UNSPECIFIED.,{closed},.F.)"
            f"B_SPLINE_CURVE_WITH_KNOTS({knots},.UNSPECIFIED.)CURVE()GEOMETRIC_REPRESENTATION_ITEM()"
            f"RATIONAL_B_SPLINE_CURVE(({ws}))REPRESENTATION_ITEM({NONE}))"
        )

    def spline(self) -> nurbs.BSplineCurve:
        """The written curve in metres, homogeneous where rational."""
        U = [k for k, m in zip(self.knots, self.mults, strict=True) for _ in range(m)]
        if self.weights is None:
            cps = [metres(p) for p in self.points]
        else:
            cps = [(*(c * x for c in metres(p)), x) for p, x in zip(self.points, self.weights, strict=True)]
        return nurbs.BSplineCurve(self.degree, cps, U, self.weights is not None, False)

    def _evaluator(self):
        return xc.BCurve(self.spline(), 1)


# --------------------------------------------------------------------------- surfaces
class Surface(Item):
    __slots__ = ()


class Plane(Surface):
    __slots__ = ("placement",)
    kind = "PLANE"

    def __init__(self, placement: Placement) -> None:
        self.placement = placement

    def _write(self, w):
        return w.add(f"PLANE({NONE},#{self.placement.write(w)})")

    def _evaluator(self):
        c, z, x = self.placement.frame()
        return xs.Plane(c, z, x)


class Cylinder(Surface):
    __slots__ = ("placement", "radius")
    kind = "CYLINDRICAL_SURFACE"

    def __init__(self, placement: Placement, radius: float) -> None:
        self.placement, self.radius = placement, radius

    def _write(self, w):
        return w.add(f"CYLINDRICAL_SURFACE({NONE},#{self.placement.write(w)},{real(self.radius)})")

    def _evaluator(self):
        c, z, x = self.placement.frame()
        return xs.Cylinder(c, z, self.radius / p21.SCALE, x)


class Cone(Surface):
    """CONICAL_SURFACE: radius (mm) at the placement and the semi-angle (radians,
    0 to pi/2)."""

    __slots__ = ("placement", "radius", "angle")
    kind = "CONICAL_SURFACE"

    def __init__(self, placement: Placement, radius: float, angle: float) -> None:
        self.placement, self.radius, self.angle = placement, radius, angle

    def _write(self, w):
        return w.add(
            f"CONICAL_SURFACE({NONE},#{self.placement.write(w)},{real(self.radius)},{real(self.angle)})"
        )

    def _evaluator(self):
        c, z, x = self.placement.frame()
        return xs.Cone(c, z, self.radius / p21.SCALE, math.sin(self.angle), math.cos(self.angle), x)


class Sphere(Surface):
    __slots__ = ("placement", "radius")
    kind = "SPHERICAL_SURFACE"

    def __init__(self, placement: Placement, radius: float) -> None:
        self.placement, self.radius = placement, radius

    def _write(self, w):
        return w.add(f"SPHERICAL_SURFACE({NONE},#{self.placement.write(w)},{real(self.radius)})")

    def _evaluator(self):
        c, z, x = self.placement.frame()
        return xs.Sphere(c, self.radius / p21.SCALE, z, x)


class Torus(Surface):
    """TOROIDAL_SURFACE, or with ``select_outer`` set (True or False) the
    DEGENERATE_TOROIDAL_SURFACE of a torus whose minor radius passes its major one:
    the outer part (apple, True) or the inner part (lemon, False)."""

    __slots__ = ("placement", "major", "minor", "select_outer")

    def __init__(self, placement: Placement, major: float, minor: float, select_outer=None) -> None:
        self.placement, self.major, self.minor, self.select_outer = placement, major, minor, select_outer

    @property
    def kind(self) -> str:  # type: ignore[override]
        return "TOROIDAL_SURFACE" if self.select_outer is None else "DEGENERATE_TOROIDAL_SURFACE"

    def _write(self, w):
        a = self.placement.write(w)
        args = f"{NONE},#{a},{real(self.major)},{real(self.minor)}"
        if self.select_outer is None:
            return w.add(f"TOROIDAL_SURFACE({args})")
        return w.add(f"DEGENERATE_TOROIDAL_SURFACE({args},{logical(self.select_outer)})")

    def _evaluator(self):
        c, z, x = self.placement.frame()
        R, r = self.major / p21.SCALE, self.minor / p21.SCALE
        if self.select_outer is False:
            # The lemon: the points of the torus whose distance from the axis, R + r cos v,
            # is negative; as Parasolid writes it, the major radius negative and x turned.
            return xs.Torus(c, z, -R, r, (-x[0], -x[1], -x[2]))
        return xs.Torus(c, z, R, r, x)


class BSplineSurface(Surface):
    """B_SPLINE_SURFACE_WITH_KNOTS (rational: the complex instance), from a clamped
    :class:`nurbs.BSplineSurface` in metres."""

    __slots__ = (
        "pu",
        "pv",
        "points",
        "weights",
        "umults",
        "uknots",
        "vmults",
        "vknots",
        "uclosed",
        "vclosed",
    )
    kind = "B_SPLINE_SURFACE_WITH_KNOTS"

    def __init__(self, s: nurbs.BSplineSurface) -> None:
        self.pu, self.pv = s.pu, s.pv
        self.points = []
        self.weights = [] if s.rational else None
        for row in s.rows:
            pts, ws = euclidean(row, s.rational)
            self.points.append([point_mm(p) for p in pts])
            if ws is not None:
                wr = [p21.rounded(x) for x in ws]
                if not all(x > 0.0 for x in wr):
                    raise ValueError("a weight that is not positive")
                self.weights.append(wr)  # type: ignore[union-attr]
        self.umults, self.uknots = _knots(s.U, s.pu)
        self.vmults, self.vknots = _knots(s.V, s.pv)
        if (
            sum(self.umults) != len(self.points) + self.pu + 1
            or sum(self.vmults) != len(self.points[0]) + self.pv + 1
        ):
            raise ValueError("knots and control points do not match")

        def same(a, b):
            return max(abs(a[i] - b[i]) for i in range(3)) <= 1e-9

        self.uclosed = all(same(a, b) for a, b in zip(self.points[0], self.points[-1], strict=True))
        self.vclosed = all(same(row[0], row[-1]) for row in self.points)

    def _write(self, w):
        grid = "(" + ",".join(p21.refs(w.point(p) for p in row) for row in self.points) + ")"
        um = ",".join(str(m) for m in self.umults)
        vm = ",".join(str(m) for m in self.vmults)
        uk = ",".join(real(k) for k in self.uknots)
        vk = ",".join(real(k) for k in self.vknots)
        flags = f"{logical(self.uclosed)},{logical(self.vclosed)},.F."
        if self.weights is None:
            return w.add(
                f"B_SPLINE_SURFACE_WITH_KNOTS({NONE},{self.pu},{self.pv},{grid},.UNSPECIFIED.,{flags},"
                f"({um}),({vm}),({uk}),({vk}),.UNSPECIFIED.)"
            )
        ws = "(" + ",".join("(" + ",".join(real(x) for x in row) + ")" for row in self.weights) + ")"
        return w.add(
            f"(BOUNDED_SURFACE()B_SPLINE_SURFACE({self.pu},{self.pv},{grid},.UNSPECIFIED.,{flags})"
            f"B_SPLINE_SURFACE_WITH_KNOTS(({um}),({vm}),({uk}),({vk}),.UNSPECIFIED.)"
            f"GEOMETRIC_REPRESENTATION_ITEM()RATIONAL_B_SPLINE_SURFACE({ws})REPRESENTATION_ITEM({NONE})"
            "SURFACE())"
        )

    def spline(self) -> nurbs.BSplineSurface:
        U = [k for k, m in zip(self.uknots, self.umults, strict=True) for _ in range(m)]
        V = [k for k, m in zip(self.vknots, self.vmults, strict=True) for _ in range(m)]
        rows = []
        for i, row in enumerate(self.points):
            if self.weights is None:
                rows.append([metres(p) for p in row])
            else:
                rows.append(
                    [(*(c * x for c in metres(p)), x) for p, x in zip(row, self.weights[i], strict=True)]
                )
        return nurbs.BSplineSurface(self.pu, self.pv, rows, U, V, self.weights is not None, False, False)

    def _evaluator(self):
        return xs.BSurface(self.spline(), 1e-9)


class Extrusion(Surface):
    """SURFACE_OF_LINEAR_EXTRUSION of ``curve`` along VECTOR(``direction``,
    ``magnitude`` mm)."""

    __slots__ = ("curve", "direction", "magnitude")
    kind = "SURFACE_OF_LINEAR_EXTRUSION"

    def __init__(self, curve: Curve, direction_, magnitude: float) -> None:
        self.curve, self.direction, self.magnitude = curve, direction_, magnitude

    def _write(self, w):
        c = self.curve.write(w)
        d = w.direction(self.direction)
        v = w.add(f"VECTOR({NONE},#{d},{real(self.magnitude)})")
        return w.add(f"SURFACE_OF_LINEAR_EXTRUSION({NONE},#{c},#{v})")

    def _evaluator(self):
        s = self.magnitude / p21.SCALE
        d = self.direction
        return xs.Swept(self.curve.evaluator(), (d[0] * s, d[1] * s, d[2] * s))


class Revolution(Surface):
    """SURFACE_OF_REVOLUTION of ``curve`` about AXIS1_PLACEMENT(``location`` mm,
    ``axis``): u turns about the axis, v runs along the curve."""

    __slots__ = ("curve", "location", "axis")
    kind = "SURFACE_OF_REVOLUTION"

    def __init__(self, curve: Curve, location, axis) -> None:
        self.curve, self.location, self.axis = curve, location, axis

    def _write(self, w):
        c = self.curve.write(w)
        p = w.point(self.location)
        d = w.direction(self.axis)
        a = w.add(f"AXIS1_PLACEMENT({NONE},#{p},#{d})")
        return w.add(f"SURFACE_OF_REVOLUTION({NONE},#{c},#{a})")

    def _evaluator(self):
        return xs.Spun(self.curve.evaluator(), metres(self.location), self.axis, None, 1e-9)


class Offset(Surface):
    """OFFSET_SURFACE of ``basis`` by ``distance`` mm along the basis' natural normal."""

    __slots__ = ("basis", "distance")
    kind = "OFFSET_SURFACE"

    def __init__(self, basis: Surface, distance: float) -> None:
        self.basis, self.distance = basis, distance

    def _write(self, w):
        return w.add(f"OFFSET_SURFACE({NONE},#{self.basis.write(w)},{real(self.distance)},.F.)")

    def _evaluator(self):
        return xs.Offset(self.basis.evaluator(), self.distance / p21.SCALE, 1)


# --------------------------------------------------------------------------- topology
class Vertex(Item):
    """VERTEX_POINT at ``point`` (mm); ``tolerance`` is the source vertex's (metres, 0
    for exact)."""

    __slots__ = ("point", "tolerance", "source")
    kind = "VERTEX_POINT"

    def __init__(self, point, tolerance: float = 0.0, source: int = -1) -> None:
        self.point, self.tolerance, self.source = point, tolerance, source

    def _write(self, w):
        return w.add(f"VERTEX_POINT({NONE},#{w.point(self.point)})")

    def metres(self):
        return metres(self.point)


class Edge(Item):
    """EDGE_CURVE from ``start`` to ``end`` on ``curve``; ``same_sense`` says the edge
    runs with the curve's parameter. ``tolerance`` is the source edge's, ``deviation``
    how far a fitted curve may lie from the source's (metres, 0 when exact)."""

    __slots__ = ("start", "end", "curve", "same_sense", "tolerance", "deviation", "source")
    kind = "EDGE_CURVE"

    def __init__(self, start, end, curve, same_sense, tolerance=0.0, deviation=0.0, source=-1) -> None:
        self.start, self.end, self.curve, self.same_sense = start, end, curve, same_sense
        self.tolerance, self.deviation, self.source = tolerance, deviation, source

    def _write(self, w):
        return w.add(
            f"EDGE_CURVE({NONE},#{self.start.write(w)},#{self.end.write(w)},#{self.curve.write(w)},"
            f"{logical(self.same_sense)})"
        )


class EdgeLoop(Item):
    """EDGE_LOOP of ORIENTED_EDGEs: ``edges`` as (edge, orientation)."""

    __slots__ = ("edges",)
    kind = "EDGE_LOOP"

    def __init__(self, edges) -> None:
        self.edges = edges

    def _write(self, w):
        ids = []
        for e, o in self.edges:
            ids.append(w.add(f"ORIENTED_EDGE({NONE},*,*,#{e.write(w)},{logical(o)})"))
        return w.add(f"EDGE_LOOP({NONE},{p21.refs(ids)})")

    def ends(self):
        """Each oriented edge's (start vertex, end vertex)."""
        return [(e.start, e.end) if o else (e.end, e.start) for e, o in self.edges]


class VertexLoop(Item):
    __slots__ = ("vertex",)
    kind = "VERTEX_LOOP"

    def __init__(self, vertex: Vertex) -> None:
        self.vertex = vertex

    def _write(self, w):
        return w.add(f"VERTEX_LOOP({NONE},#{self.vertex.write(w)})")


class Face(Item):
    """ADVANCED_FACE on ``surface``: ``bounds`` as (loop, outer), ``same_sense`` its
    normal with the surface's natural normal; ``source`` the Parasolid FACE's node id."""

    __slots__ = ("bounds", "surface", "same_sense", "source", "approximated", "extent", "deviation")
    kind = "ADVANCED_FACE"

    def __init__(
        self, bounds, surface, same_sense, source=-1, approximated=False, extent=None, deviation=0.0
    ) -> None:
        self.bounds, self.surface, self.same_sense = bounds, surface, same_sense
        self.source, self.approximated = source, approximated
        self.deviation = deviation  # an approximated surface's measured deviation (metres)
        self.extent = extent  # points (mm) bounding a face without loops

    def _write(self, w):
        ids = []
        for loop, outer in self.bounds:
            name = "FACE_OUTER_BOUND" if outer else "FACE_BOUND"
            ids.append(w.add(f"{name}({NONE},#{loop.write(w)},.T.)"))
        s = self.surface.write(w)
        return w.add(f"ADVANCED_FACE({NONE},{p21.refs(ids)},#{s},{logical(self.same_sense)})")


class Shell(Item):
    """CLOSED_SHELL (``closed``) or OPEN_SHELL of ``faces``."""

    __slots__ = ("faces", "closed")

    def __init__(self, faces, closed: bool = True) -> None:
        self.faces, self.closed = faces, closed

    @property
    def kind(self) -> str:  # type: ignore[override]
        return "CLOSED_SHELL" if self.closed else "OPEN_SHELL"

    def _write(self, w):
        ids = [f.write(w) for f in self.faces]
        return w.add(f"{self.kind}({NONE},{p21.refs(ids)})")


class Solid(Item):
    """MANIFOLD_SOLID_BREP named ``name`` on its ``outer`` shell, or BREP_WITH_VOIDS
    with the ``voids`` as ORIENTED_CLOSED_SHELLs whose faces already point into the
    cavity (orientation .T.)."""

    __slots__ = ("name", "outer", "voids")

    def __init__(self, name: str, outer: Shell, voids=()) -> None:
        self.name, self.outer, self.voids = name, outer, tuple(voids)

    @property
    def kind(self) -> str:  # type: ignore[override]
        return "BREP_WITH_VOIDS" if self.voids else "MANIFOLD_SOLID_BREP"

    @property
    def shells(self):
        return (self.outer, *self.voids)

    def _write(self, w):
        outer = self.outer.write(w)
        if not self.voids:
            return w.add(f"MANIFOLD_SOLID_BREP({p21.text(self.name)},#{outer})")
        voids = [w.add(f"ORIENTED_CLOSED_SHELL({NONE},*,#{v.write(w)},.T.)") for v in self.voids]
        return w.add(f"BREP_WITH_VOIDS({p21.text(self.name)},#{outer},{p21.refs(voids)})")


class SurfaceModel(Item):
    """SHELL_BASED_SURFACE_MODEL named ``name`` of a sheet body's shells."""

    __slots__ = ("name", "shells")
    kind = "SHELL_BASED_SURFACE_MODEL"

    def __init__(self, name: str, shells) -> None:
        self.name, self.shells = name, tuple(shells)

    def _write(self, w):
        ids = [s.write(w) for s in self.shells]
        return w.add(f"SHELL_BASED_SURFACE_MODEL({p21.text(self.name)},{p21.refs(ids)})")
