"""ACIS bodies as in-memory Parasolid transmits, for SolidSeas' tessellator (provisional,
``docs/formats/alibre.md``).

Topology maps one to one: a body to a BODY, its lumps' shells to the SHELL, a face
to a FACE (sense '-' when the ACIS face is reversed), a loop to a LOOP, a coedge
to a fin (sense '-' when reversed against its edge; its end vertex the edge's end,
or its start when reversed), the coedges of an edge to partner fins, an edge to
an EDGE on a curve of its own (sense '-' when the edge runs against its curve;
a tolerant edge as an ordinary one, with no tolerance), a vertex to a VERTEX (a
``tvertex`` with its tolerance).

The ACIS normal conventions, measured against Alibre's own display mesh on four
sample files (``docs/formats/alibre.md`` has the counts): a plane's normal is
stored; a cone's (cylinders included) points away from its axis when the cosine
of its half angle is positive and towards it when negative, whatever its
reversed-u flag, and its radius grows by sine over cosine per unit along its
axis; a sphere's and a torus's point out of the surface (a negative radius,
unseen, is read as pointing in); a spline surface's is ``Su x Sv``, turned round
when the surface is reversed. Each XT surface takes the sense that gives its
natural normal that direction.

A sphere keeps its stored pole as the XT sphere's axis, except where one of its
faces has a loop of one closed circle through both poles (a solid sphere, or a
revolve about the pole's axis, cut by a plane through that axis): SolidSeas'
tessellator draws such a face wrongly (closed, but with the wrong area and
volume), so the circle's normal is taken as the axis instead and the loop becomes
the XT sphere's equator. The surface is the same; only its parameters change.

Geometry maps to the XT forms the tessellator evaluates: plane, cylinder, cone,
an elliptic cylinder as a swept ellipse, sphere, torus and B-spline surfaces;
lines, circles, ellipses and B-spline curves (an intcurve through the B-spline
it stores, within its fit tolerance). Lengths are scaled from model units to
metres. A face whose geometry is not mapped (a procedural spline surface with no
stored B-spline, an elliptic cone, an intcurve with none, a number that is not
finite once scaled) is left out and reported, as the tessellator reports a face
it cannot do.
"""

import math
from dataclasses import dataclass, field

from ...errors import ReaderWarning, SldFormatError, SldLimitError
from ...tessellate import SkippedFace
from .._source import Clock
from ..limits import Limits
from ._xt import XtWriter
from .bspline import SplineError, xt_knots
from .entities import (
    AcisError,
    Cone,
    Ellipse,
    IntCurve,
    Model,
    Plane,
    Sphere,
    Spline,
    Straight,
    Torus,
    Transform,
)

Vec = tuple[float, float, float]
_EPS = 1e-12


@dataclass
class BodyBuild:
    """One ACIS body as a transmit: ``faces`` in the ACIS body, ``skipped`` the faces left
    out (``SkippedFace``), ``face_map`` XT FACE node to ACIS face record, ``color``
    RGBA from 0 to 1 when the body or its lump carries one."""

    transmit: object
    body_type: str
    faces: int
    skipped: list[SkippedFace] = field(default_factory=list)
    warnings: list[ReaderWarning] = field(default_factory=list)
    face_map: dict[int, int] = field(default_factory=dict)
    color: tuple[float, float, float, float] | None = None
    label: str = "body"


# --------------------------------------------------------------------------- vectors
def _sub(a, b) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a) -> float:
    return math.sqrt(_dot(a, a))


def _finite(*vs) -> bool:
    return all(math.isfinite(x) for v in vs for x in (v if isinstance(v, tuple) else (v,)))


def _unit(a, what: str) -> Vec:
    n = _norm(a)
    if not (math.isfinite(n) and n > _EPS):
        raise AcisError("bad_geometry", f"{what} is not a direction")
    return (a[0] / n, a[1] / n, a[2] / n)


def _perpendicular(n: Vec) -> Vec:
    """Any unit vector perpendicular to the unit ``n``."""
    other = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
    return _unit(_cross(n, other), "a perpendicular")


def _x_axis(axis: Vec, x) -> Vec:
    """``x`` made perpendicular to the unit ``axis``, or any perpendicular when it is parallel."""
    p = _sub(x, tuple(axis[k] * _dot(x, axis) for k in range(3)))
    n = _norm(p)
    if not (math.isfinite(n) and n > 1e-9 * max(1.0, _norm(x))):
        return _perpendicular(axis)
    return (p[0] / n, p[1] / n, p[2] / n)


class _Frame:
    """Model units to metres, and the body's transform when it has one."""

    def __init__(self, scale_m: float, tr: Transform | None) -> None:
        self.s = scale_m
        self.tr = tr

    def point(self, p) -> Vec:
        if not _finite(tuple(p)):
            raise AcisError("non_finite", "a point is not finite")
        if self.tr is not None:
            r, t, k = self.tr.rows, self.tr.translation, self.tr.scale
            p = tuple(k * (p[0] * r[0][j] + p[1] * r[1][j] + p[2] * r[2][j]) + t[j] for j in range(3))
        return (p[0] * self.s, p[1] * self.s, p[2] * self.s)

    def vector(self, v) -> Vec:
        if not _finite(tuple(v)):
            raise AcisError("non_finite", "a vector is not finite")
        if self.tr is not None:
            r = self.tr.rows
            v = tuple(v[0] * r[0][j] + v[1] * r[1][j] + v[2] * r[2][j] for j in range(3))
        return (float(v[0]), float(v[1]), float(v[2]))

    def length(self, x: float) -> float:
        if not math.isfinite(x):
            raise AcisError("non_finite", "a length is not finite")
        k = abs(self.tr.scale) if self.tr is not None else 1.0
        return x * k * self.s


# --------------------------------------------------------------------------- surfaces
def _surface(
    w: XtWriter, m: Model, index: int, fr: _Frame, clock: Clock | None = None, pole: Vec | None = None
) -> int:
    """The XT surface of ACIS surface ``index``; ``pole`` a sphere's axis in place of
    its stored pole (see the module notes)."""
    s = m.surface(index, clock)
    if isinstance(s, Plane):
        n = _unit(fr.vector(s.normal), "a plane's normal")
        return w.plane(fr.point(s.root), n, _x_axis(n, fr.vector(s.u_dir)))
    if isinstance(s, Cone):
        if not _finite(s.ratio, s.sine, s.cosine) or abs(s.cosine) < _EPS or s.ratio <= 0:
            raise AcisError("bad_geometry", "a cone's angle or ratio is out of range")
        axis = _unit(fr.vector(s.axis), "a cone's axis")
        major = fr.vector(s.major)
        radius = fr.length(_norm(s.major))
        x = _x_axis(axis, major)
        sense = "+" if s.cosine > 0 else "-"
        circular = abs(s.ratio - 1.0) < 1e-9
        if abs(s.sine) < _EPS:
            if radius <= 0:
                raise AcisError("bad_geometry", "a cylinder has no radius")
            if circular:
                return w.cylinder(fr.point(s.centre), axis, radius, x, sense)
            section = w.ellipse(fr.point(s.centre), axis, x, radius, radius * s.ratio)
            return w.swept(section, axis, sense)
        if not circular:
            raise AcisError("unsupported_surface", "an elliptic cone")
        k = s.sine / s.cosine
        h = math.sqrt(1.0 + k * k)
        return w.cone(fr.point(s.centre), axis, radius, k / h, 1.0 / h, x, sense)
    if isinstance(s, Sphere):
        if not math.isfinite(s.radius) or s.radius == 0:
            raise AcisError("bad_geometry", "a sphere has no radius")
        if pole is None:
            pole = _unit(fr.vector(s.pole), "a sphere's pole")
        return w.sphere(
            fr.point(s.centre),
            fr.length(abs(s.radius)),
            pole,
            _x_axis(pole, fr.vector(s.u_dir)),
            "+" if s.radius > 0 else "-",
        )
    if isinstance(s, Torus):
        if not _finite(s.major, s.minor) or s.minor == 0 or s.major <= 0:
            raise AcisError("unsupported_surface", "a torus whose radii are not both positive")
        axis = _unit(fr.vector(s.axis), "a torus's axis")
        return w.torus(
            fr.point(s.centre),
            axis,
            fr.length(s.major),
            fr.length(abs(s.minor)),
            _x_axis(axis, fr.vector(s.u_dir)),
            "+" if s.minor > 0 else "-",
        )
    if isinstance(s, Spline):
        b = s.bs3
        if b is None:
            raise AcisError(
                "unsupported_surface", f"a spline surface of subtype {s.subtype[:40]} stores no B-spline"
            )
        uk, um = xt_knots(b.degree_u, b.knots_u)
        vk, vm = xt_knots(b.degree_v, b.knots_v)
        pts = []
        wts = [] if b.weights is not None else None
        for a in range(b.nu):  # XT: v varies fastest; ACIS stores u fastest
            for c in range(b.nv):
                if clock is not None:
                    clock.tick()
                k = c * b.nu + a
                pts.append(fr.point(b.points[k]))
                if wts is not None:
                    wt = b.weights[k]
                    if not (math.isfinite(wt) and wt > 0):
                        raise AcisError("bad_geometry", "a spline weight is not positive")
                    wts.append(wt)
        return w.bspline_surface(
            b.degree_u,
            b.degree_v,
            b.nu,
            b.nv,
            pts,
            wts,
            uk,
            um,
            vk,
            vm,
            uclosed=b.closure_u != 0,
            vclosed=b.closure_v != 0,
            sense="-" if s.reversed else "+",
        )
    raise AcisError("unsupported_surface", type(s).__name__)


# --------------------------------------------------------------------------- curves
def _curve(
    w: XtWriter, m: Model, index: int, reversed_edge: bool, fr: _Frame, clock: Clock | None = None
) -> int:
    c = m.curve(index, clock)
    if isinstance(c, Straight):
        return w.line(
            fr.point(c.root),
            _unit(fr.vector(c.direction), "a line's direction"),
            "-" if reversed_edge else "+",
        )
    if isinstance(c, Ellipse):
        if not math.isfinite(c.ratio) or c.ratio <= 0:
            raise AcisError("bad_geometry", "an ellipse's ratio is not positive")
        n = _unit(fr.vector(c.normal), "an ellipse's normal")
        a = fr.length(_norm(c.major))
        if not a > 0:
            raise AcisError("bad_geometry", "an ellipse has no radius")
        x = _x_axis(n, fr.vector(c.major))
        sense = "-" if reversed_edge else "+"
        if abs(c.ratio - 1.0) < 1e-9:
            return w.circle(fr.point(c.centre), n, x, a, sense)
        return w.ellipse(fr.point(c.centre), n, x, a, a * c.ratio, sense)
    if isinstance(c, IntCurve):
        b = c.bs3
        if b is None:
            raise AcisError(
                "unsupported_curve", f"an intcurve of subtype {c.subtype[:40]} stores no B-spline"
            )
        if len(b.points[0]) != 3:
            raise AcisError("bad_geometry", "an intcurve's B-spline is not three-dimensional")
        knots, mults = xt_knots(b.degree, b.knots)
        pts = []
        for p in b.points:
            if clock is not None:
                clock.tick()
            pts.append(fr.point(p))
        wts = None
        if b.weights is not None:
            wts = list(b.weights)
            if not all(math.isfinite(x) and x > 0 for x in wts):
                raise AcisError("bad_geometry", "a spline weight is not positive")
        span = max((_norm(_sub(p, pts[0])) for p in pts), default=0.0)
        closed = b.closure != 0 or _norm(_sub(pts[0], pts[-1])) <= 1e-9 * max(span, 1e-9)
        sense = "-" if reversed_edge != c.reversed else "+"
        return w.bspline_curve(b.degree, pts, wts, knots, mults, closed=closed, sense=sense)
    raise AcisError("unsupported_curve", type(c).__name__)


# --------------------------------------------------------------------------- topology
def _chain(start, step, limit: int, what: str) -> list[int]:
    """Indices along a ``next`` chain from ``start`` (None: empty), each once."""
    out: list[int] = []
    seen: set[int] = set()
    i = start
    while i is not None:
        if i in seen:
            raise AcisError("bad_reference", f"the {what} chain loops")
        seen.add(i)
        out.append(i)
        if len(out) > limit:
            raise AcisError("bad_reference", f"the {what} chain is too long")
        i = step(i)
    return out


def _ring(m: Model, first: int, limit: int) -> list[int]:
    """The coedges of a loop, by ``next`` back to the first."""
    out = [first]
    seen = {first}
    i = m.coedge(first).next
    while i != first:
        if i is None:
            raise AcisError("bad_reference", "a loop's coedges do not close")
        if i in seen:
            raise AcisError("bad_reference", "a loop's coedges loop without reaching the first")
        seen.add(i)
        out.append(i)
        if len(out) > limit:
            raise AcisError("bad_reference", "a loop has too many coedges")
        i = m.coedge(i).next
    return out


def _walk(start, step, limit: int) -> list[int]:
    """Indices along a ``next`` chain from ``start``, each once: the walk stops where the
    chain comes round or breaks (a damaged link), keeping what it reached."""
    out: list[int] = []
    seen: set[int] = set()
    i = start
    while i is not None and i not in seen and len(out) < limit:
        seen.add(i)
        out.append(i)
        try:
            i = step(i)
        except AcisError:
            break
    return out


def body_faces(m: Model, body: int, clock: Clock | None = None) -> list[int]:
    """Every face record of ``body``: its lumps' shells' face chains, then any other face
    whose ``shell`` is one of them (faces in subshells, or past a damaged link), each
    once. Raises :class:`AcisError` when the body itself cannot be read."""
    limit = len(m.records) + 1
    b = m.body(body)

    def lump_shell(i):
        return m.lump(i).shell

    shells: list[int] = []
    for lump in _walk(b.lump, lambda i: m.lump(i).next, limit):
        try:
            first = lump_shell(lump)
        except AcisError:
            continue
        shells.extend(_walk(first, lambda i: m.shell(i).next, limit))
    faces: list[int] = []
    seen: set[int] = set()
    for sh in shells:
        try:
            first = m.shell(sh).face
        except AcisError:
            continue
        for f in _walk(first, lambda i: m.face(i).next, limit):
            if clock is not None:
                clock.tick()
            if f not in seen and 0 <= f < len(m.records) and m.type_of(f) == "face":
                seen.add(f)
                faces.append(f)
    # The faces that name one of these shells but were not on its chain, in record
    # order, from the model's index of faces by shell (built once for every body).
    by_shell = m.faces_by_shell(clock)
    stray = sorted({f for sh in shells for f in by_shell.get(sh, ()) if f not in seen})
    faces.extend(stray)
    return faces


def _plan_face(m: Model, f: int, limit: int, clock: Clock | None = None):
    """The loops of face ``f`` as ``[(coedge, edge, reversed)]`` rings, every pointer
    followed and every edge's curve decoded, before any node is written."""
    face = m.face(f)
    loops = []
    for lp in _chain(face.loop, lambda i: m.loop(i).next, limit, "loop"):
        first = m.loop(lp).coedge
        if first is None:
            continue
        ring = []
        for ce in _ring(m, first, limit):
            co = m.coedge(ce)
            if co.edge is None:
                raise AcisError("bad_reference", "a coedge has no edge")
            e = m.edge(co.edge)
            if e.curve is None:
                # A degenerate edge (an apex, a pole): no curve, one vertex. It has no
                # length, so the loop closes without it.
                if e.start is not None and e.start == e.end:
                    continue
                raise AcisError("unsupported_curve", "an edge has no curve")
            m.curve(e.curve, clock)
            for v in (e.start, e.end):
                if v is not None:
                    vx = m.vertex(v)
                    if vx.point is None:
                        raise AcisError("bad_reference", "a vertex has no point")
                    m.point(vx.point)
            ring.append((ce, co.edge, co.reversed))
        if ring:
            loops.append(ring)
    return face, loops


def _sphere_poles(m: Model, plans: list, fr: _Frame) -> dict[int, Vec]:
    """The XT axis of each sphere surface one of whose faces has a loop of one closed
    circle through both of its stored poles: that circle's normal (the module notes)."""
    out: dict[int, Vec] = {}
    for _f, face, loops in plans:
        index = face.surface
        if index in out:
            continue
        try:
            s = m.surface(index)
            if not isinstance(s, Sphere) or not _finite(s.centre, s.pole, s.radius) or s.radius == 0:
                continue
            r = abs(s.radius)
            pole = _unit(s.pole, "a sphere's pole")
            for ring in loops:
                if len(ring) != 1:
                    continue
                ed = m.edge(ring[0][1])
                if ed.start is None or ed.start != ed.end or ed.curve is None:
                    continue
                c = m.curve(ed.curve)
                if not isinstance(c, Ellipse) or not _finite(c.centre, c.normal, c.major, c.ratio):
                    continue
                if abs(c.ratio - 1.0) > 1e-9 or abs(_norm(c.major) - r) > 1e-6 * r:
                    continue  # not a circle of the sphere's radius
                normal = _unit(c.normal, "a circle's normal")
                if _norm(_sub(c.centre, s.centre)) > 1e-6 * r or abs(_dot(normal, pole)) > 1e-6:
                    continue  # not a great circle through the poles
                out[index] = _unit(fr.vector(c.normal), "a circle's normal")
                break
        except AcisError:
            continue
    return out


def build_body(
    m: Model, body: int, limits: Limits, clock: Clock | None = None, *, label: str = "body"
) -> BodyBuild:
    """One ACIS body as a :class:`BodyBuild` (see the module notes). Raises
    :class:`AcisError` for a body that cannot be walked at all and ``SldLimitError``
    past a bound; a face that cannot be mapped is skipped and reported."""
    header = m.header
    if not (math.isfinite(header.mm_per_unit) and header.mm_per_unit > 0):
        raise SldFormatError("the ACIS header's unit of length is not a positive number")
    warnings: list[ReaderWarning] = []
    b = m.body(body)
    tr = None
    if b.transform is not None:
        tr = m.transform(b.transform)
        if tr.identity:
            tr = None
        elif tr.reflect or tr.shear or not math.isfinite(tr.scale) or tr.scale == 0:
            raise AcisError("unsupported_transform", "the body's transform reflects or shears")
        else:
            warnings.append(
                ReaderWarning(
                    "transform_unverified",
                    "the body carries a transform, applied with row vectors, a convention not yet verified",
                )
            )
    fr = _Frame(header.mm_per_unit / 1000.0, tr)
    limit = len(m.records) + 1
    faces = body_faces(m, body, clock)
    # Solid or sheet, from the whole body: single-sided faces and edges used twice.
    uses: dict[int, int] = {}
    double = False
    plans: list = []
    skipped: list[SkippedFace] = []
    for f in faces:
        if clock is not None:
            clock.tick()
        try:
            face, loops = _plan_face(m, f, limit, clock)
            double = double or face.double_sided
            for ring in loops:
                for _ce, e, _rev in ring:
                    uses[e] = uses.get(e, 0) + 1
            if face.surface is None:
                raise AcisError("bad_reference", "a face has no surface")
            m.surface(face.surface, clock)
            plans.append((f, face, loops))
        except AcisError as exc:
            surf = _surface_name(m, f)
            skipped.append(SkippedFace(label, f, surf, _reason(exc.reason), exc.detail or exc.reason))
    closed = bool(plans) and all(n == 2 for n in uses.values())
    body_type = "solid" if (closed and not double) else "sheet"
    w = XtWriter(limits, body_type, clock)
    poles = _sphere_poles(m, plans, fr)
    surfaces: dict[int, int] = {}
    edges: dict[int, int] = {}
    vertices: dict[int, int] = {}
    fins_of_edge: dict[int, list[int]] = {}
    face_map: dict[int, int] = {}
    for f, face, loops in plans:
        if clock is not None:
            clock.tick()
        try:
            sid = surfaces.get(face.surface)
            if sid is None:
                sid = surfaces[face.surface] = _surface(
                    w, m, face.surface, fr, clock, poles.get(face.surface)
                )
            # curves and vertices first, so a face that fails leaves nothing behind
            for ring in loops:
                for _ce, e, _rev in ring:
                    if e not in edges:
                        ed = m.edge(e)
                        edges[e] = w.edge(_curve(w, m, ed.curve, ed.reversed, fr, clock))
                    ed = m.edge(e)
                    for v in (ed.start, ed.end):
                        if v is not None and v not in vertices:
                            vx = m.vertex(v)
                            tol = (
                                fr.length(vx.tolerance)
                                if vx.tolerance is not None and vx.tolerance > 0
                                else None
                            )
                            vertices[v] = w.vertex(fr.point(m.point(vx.point)), tol)
        except (AcisError, SplineError) as exc:
            skipped.append(
                SkippedFace(label, f, _surface_name(m, f), _reason(exc.reason), exc.detail or exc.reason)
            )
            continue
        except SldLimitError:
            raise
        except SldFormatError as exc:
            # The node writer refuses a number that is not finite (a length that
            # overflowed once scaled, say): that costs the face, as the decoders' checks do.
            skipped.append(SkippedFace(label, f, _surface_name(m, f), "non_finite", str(exc)[:200]))
            continue
        fid = w.face(sid, "-" if face.reversed else "+")
        face_map[fid] = f
        for ring in loops:
            spec = []
            for _ce, e, rev in ring:
                ed = m.edge(e)
                end = ed.start if rev else ed.end
                spec.append((edges[e], "-" if rev else "+", vertices.get(end, 0) if end is not None else 0))
            lp = w.loop(fid, spec)
            for (_ce, e, _rev), fin in zip(ring, w.fins_of(lp), strict=True):
                fins_of_edge.setdefault(e, []).append(fin)
    for _e, fins in fins_of_edge.items():
        w.pair(fins)
    if skipped and body_type == "solid":
        warnings.append(
            ReaderWarning(
                "faces_left_out",
                f"{len(skipped)} faces of the ACIS body could not be mapped and are left out",
            )
        )
    color = None
    rgb = m.rgb_color(body)
    if rgb is None and b.lump is not None:
        rgb = m.rgb_color(b.lump)
    if rgb is not None:
        color = (rgb[0], rgb[1], rgb[2], 1.0)
    return BodyBuild(w.transmit(), body_type, len(faces), skipped, warnings, face_map, color, label)


_SURFACE_NAMES = {
    "plane-surface": "PLANE",
    "cone-surface": "CONE",
    "sphere-surface": "SPHERE",
    "torus-surface": "TORUS",
    "spline-surface": "B_SURFACE",
}
_REASONS = {
    "unsupported_surface": "unsupported_surface",
    "unsupported_curve": "unsupported_curve",
    "bad_reference": "bad_reference",
    "non_finite": "non_finite",
}


def _reason(reason: str) -> str:
    """An ACIS decoding reason as one of the tessellator's skipped-face reasons."""
    return _REASONS.get(reason, "bad_geometry")


def _surface_name(m: Model, f: int) -> str:
    try:
        s = m.face(f).surface
        return _SURFACE_NAMES.get(m.type_of(s), m.type_of(s)[:40]) if s is not None else "none"
    except (AcisError, IndexError):
        return "unknown"


def bodies(m: Model) -> list[int]:
    """The body records of a model, in file order."""
    return m.indices("body")


def tessellation_limits(sb, tess, limits: Limits) -> None:
    """What a limit that stopped a tessellation means for a scene (``sb``, a
    ``SceneBuilder``): the call's ``max_triangles`` cuts the scene short,
    ``limits.triangles`` raises, and time or the face bound leave faces out."""
    from ..base import _Truncated

    if "max_triangles" in tess.truncated:
        if sb.options.max_triangles is not None:
            raise _Truncated()
        raise limits.exceeded("triangles", f"the model has more than {limits.triangles:,} triangles")
    if tess.truncated:
        sb.warn("faces_left_out", "the tessellation stopped at a limit; faces are left out")


__all__ = ["BodyBuild", "bodies", "body_faces", "build_body", "tessellation_limits"]
