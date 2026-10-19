"""The B-rep as a drawing reads it: ``BrepModel`` (``docs/DRAWINGS.md`` 6.3).

Built from a part's Parasolid bodies and core 1's detailed tessellation
(``detail=True``): faces with typed primitives, their frames and outward sense,
area, loops, triangles and (u, v); edges with their curve, the tessellator's
shared samples with parameters and both faces' normals, length, kind and
signature; vertices with the faces that meet there; axis groups; the box,
diagonal and tolerance; whether the shell is closed; and the faces left out.

Identity, as the slice found it must be (``docs/drawings/README.md``, C1 to C4):

- a face is its index in the mesh, an edge its key in the detail (``(body, EDGE
  node_id)``, or ``(body, -1 - node index)`` where ids are missing or repeat, as
  the tests' synthetic bodies have them); node ids are attributes only;
- each side of an edge is found through the mesh vertices the edge's samples
  are on, never through the face ids the detail records;
- every face carries its surface's frame (a plane's outward normal and offset,
  a revolved face's axis, radius, half angle and x and y directions, and whether
  it is concave);
- every vertex knows the faces that meet there.

Only the public modules of :mod:`solidseas.tessellate` are used.
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from ..errors import InvalidArgumentError
from ..formats.solidworks.parasolid import BODY_TYPES, XtTransmit
from ..tessellate import CHORD_MAX, CHORD_MIN, Tessellation, tessellate_body, tessellate_transmit
from ..tessellate.surfaces import Geometry
from ..tessellate.topology import CURVE_TYPES, EDGE, SURFACE_TYPES, FaceFailed, Topology
from . import keys
from .limits import DEFAULT_LIMITS, DrawingLimits
from .numbers import plain_sum

Vec3 = tuple[float, float, float]

TANGENT_DEGREES = 1.0  # 6.3: an edge is tangent when its faces' normals agree within this
QUALITY_CHORD = {"normal": 1e-3, "fine": 2.5e-4, "draft": 2e-3}  # of the diagonal (23)
REVOLVED = ("cylinder", "cone", "sphere", "torus")
_KINDS = {"PLANE": "plane", "CYLINDER": "cylinder", "CONE": "cone", "SPHERE": "sphere", "TORUS": "torus"}
_OTHER_KINDS = {
    "B_SURFACE": "bspline",
    "SWEPT_SURF": "swept",
    "SPUN_SURF": "spun",
    "OFFSET_SURF": "offset",
    "BLENDED_EDGE": "blend",
}


def _sub(a, b) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a) -> float:
    return math.sqrt(_dot(a, a))


def _unit(a) -> Vec3:
    n = _norm(a)
    return (a[0] / n, a[1] / n, a[2] / n) if n else (0.0, 0.0, 0.0)


def _scale(a, k) -> Vec3:
    return (a[0] * k, a[1] * k, a[2] * k)


def _add(a, b) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


# --------------------------------------------------------------------------- surfaces and curves


@dataclass(frozen=True)
class Plane:
    """A plane face: its outward unit normal, offset (normal . point), a point on it and
    its in-plane x and y."""

    normal: Vec3
    offset: float
    origin: Vec3
    x: Vec3
    y: Vec3


@dataclass(frozen=True)
class Cylinder:
    """A cylinder face. ``concave`` when the material lies outside it (a hole)."""

    point: Vec3
    axis: Vec3
    radius: float
    x: Vec3
    y: Vec3
    concave: bool


@dataclass(frozen=True)
class Cone:
    """A cone face: radius ``radius`` at ``point``, growing by tan(``half_angle``) along
    ``axis``; ``apex`` when it has one."""

    point: Vec3
    axis: Vec3
    radius: float
    half_angle: float
    x: Vec3
    y: Vec3
    concave: bool
    apex: Vec3 | None


@dataclass(frozen=True)
class Sphere:
    centre: Vec3
    radius: float
    axis: Vec3
    concave: bool


@dataclass(frozen=True)
class Torus:
    centre: Vec3
    axis: Vec3
    major: float
    minor: float
    concave: bool


@dataclass(frozen=True)
class OtherSurface:
    """A free-form face (B-spline, swept, spun, offset, rolling blend): no closed form."""

    name: str


@dataclass(frozen=True)
class Curve:
    """An edge's curve: ``line`` (point, direction), ``circle`` (centre, normal,
    radius, x), ``ellipse`` (centre, normal, x, major and minor radius), ``bspline``
    (degree, knots, control points, weights) or ``other`` (only its samples)."""

    kind: str
    point: Vec3 = (0.0, 0.0, 0.0)
    direction: Vec3 = (0.0, 0.0, 1.0)
    radius: float = 0.0
    minor: float = 0.0
    x: Vec3 = (1.0, 0.0, 0.0)
    degree: int = 0
    knots: tuple[float, ...] = ()
    points: tuple[Vec3, ...] = ()
    weights: tuple[float, ...] | None = None


# --------------------------------------------------------------------------- the model


@dataclass(frozen=True)
class Face:
    """One face, by its index in the mesh. ``vertices`` and ``triangles`` are its ranges
    in :attr:`BrepModel.points` and :attr:`BrepModel.triangles`; ``uv`` the (u, v) of
    each of its vertices, flat."""

    index: int
    body: int
    node_id: int
    kind: str
    surface: object
    sense: int
    area: float
    box: tuple[Vec3, Vec3]
    loops: tuple[tuple[tuple[int, int], ...], ...]
    vertices: tuple[int, int]
    triangles: tuple[int, int]
    signature: str
    neighbours: tuple[int, ...] = ()

    @property
    def revolved(self) -> bool:
        return self.kind in REVOLVED


@dataclass(frozen=True)
class Edge:
    """One edge, by its detail key. ``faces`` holds the face on each side (one for an
    open edge, the same face twice for a seam); ``normals`` each side's outward normal
    at every sample; ``kind`` is convex, concave, tangent, seam or open."""

    key: tuple[int, int]
    body: int
    node_id: int
    curve: Curve
    points: tuple[Vec3, ...]
    params: tuple[float, ...]
    faces: tuple[int, ...]
    normals: tuple[tuple[Vec3, ...], ...]
    length: float
    kind: str
    signature: str
    ends: tuple[Vec3, Vec3] | None  # None for a ring (a closed edge with no vertex)


@dataclass(frozen=True)
class Vertex:
    point: Vec3
    faces: tuple[int, ...]
    edges: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class AxisGroup:
    """Revolved faces whose axis lines coincide within the model's tolerance."""

    point: Vec3
    direction: Vec3
    faces: tuple[int, ...]


@dataclass(frozen=True)
class Body:
    index: int
    name: str
    type: str
    faces: tuple[int, ...]
    volume: float


@dataclass(frozen=True)
class BrepModel:
    """A part as the drawing reads it (6.3)."""

    name: str
    bodies: tuple[Body, ...]
    faces: tuple[Face, ...]
    edges: dict[tuple[int, int], Edge]
    vertices: tuple[Vertex, ...]
    axis_groups: tuple[AxisGroup, ...]
    points: tuple[Vec3, ...]
    normals: tuple[Vec3, ...]
    triangles: tuple[tuple[int, int, int], ...]
    tri_face: tuple[int, ...]
    face_uv: tuple[tuple[float, ...], ...]
    box: tuple[Vec3, Vec3]
    diagonal: float
    tolerance: float
    chord: float
    closed: bool | None
    skipped: tuple[tuple[str, int, str, str], ...]
    seconds: dict[str, float] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def vertex_faces(self) -> dict[tuple[int, int, int], tuple[int, ...]]:
        """The faces at each vertex, keyed by its point rounded to 1e-9 m (C4)."""
        return {_vkey(v.point): v.faces for v in self.vertices}

    def face_edges(self, face: int) -> list[Edge]:
        """The edges bounding ``face``."""
        return [e for e in self.edges.values() if face in e.faces]

    def signatures(self) -> list[str]:
        return [f.signature for f in self.faces]


def _vkey(p) -> tuple[int, int, int]:
    return (round(p[0] * 1e9), round(p[1] * 1e9), round(p[2] * 1e9))


# --------------------------------------------------------------------------- building


def topology_counts(transmits: Sequence[XtTransmit], body_types=("solid",)) -> dict[str, int]:
    """Bodies, faces and edges of the chosen bodies from a topology walk alone, so a part
    over the bounds is refused before it is tessellated (17.1)."""
    counts = {"bodies": 0, "faces": 0, "edges": 0}
    for _k, topo, body, _name, _btype in _chosen(transmits, body_types):
        counts["bodies"] += 1
        faces = topo.faces(body)
        counts["faces"] += len(faces)
        edges: set[int] = set()
        for f in faces:
            for lp in topo.loops(f):
                for fin in topo.fins(lp):
                    e = topo.ref(fin, "edge", (EDGE,))
                    if e is not None:
                        edges.add(e.index)
        counts["edges"] += len(edges)
    return counts


def _chosen(transmits: Sequence[XtTransmit], body_types) -> list[tuple[int, Topology, object, str, str]]:
    """The bodies in the order the tessellator takes them: (index, topology, BODY node,
    name, type)."""
    out = []
    topos: dict[int, Topology] = {}
    for xt in transmits:
        topo = topos.get(id(xt))
        if topo is None:
            topo = topos[id(xt)] = Topology(xt)
        for b in topo.bodies():
            code = topo.get(b, "body_type", 0)
            btype = BODY_TYPES.get(code, "unknown") if isinstance(code, int) else "unknown"
            if btype in body_types:
                out.append((len(out), topo, b, f"body#{len(out) + 1}", btype))
    return out


def _check_counts(counts: dict[str, int], limits: DrawingLimits) -> None:
    for name in ("bodies", "faces", "edges"):
        if counts[name] > getattr(limits, name):
            raise limits.exceeded(name, limits.refuse(**{name: counts[name]}) or name)


def from_transmit(
    xt: XtTransmit,
    *,
    name: str = "",
    body_types=("solid",),
    quality: str = "normal",
    limits: DrawingLimits = DEFAULT_LIMITS,
) -> BrepModel:
    """The model of every chosen body of one transmit."""
    _check_counts(topology_counts([xt], body_types), limits)
    t0 = time.perf_counter()
    tess = tessellate_transmit(xt, body_types=body_types, **_tess_options(quality, limits))
    return build(tess, [xt], name=name, body_types=body_types, tess_seconds=time.perf_counter() - t0)


def from_bodies(
    bodies: Sequence,
    *,
    name: str = "",
    quality: str = "normal",
    limits: DrawingLimits = DEFAULT_LIMITS,
) -> BrepModel:
    """The model of the chosen ``ParasolidBody`` objects of a part (as
    :func:`~solidseas.tessellate.bodies_of` returns them), one tessellation each at one
    chord for the whole part, merged in the order given: body ``k`` of the model is
    ``bodies[k]``.

    A body may also be placed, as an assembly's are (:mod:`.assembly`): an object
    holding the ``ParasolidBody`` as ``body``, its own ``name`` and a ``placement``
    (``rotation`` row by row and ``translation_m``). Each part body is then
    tessellated once, at the chord of the whole assembly, and placed (:func:`place`)
    for every instance that uses it."""
    bases = [getattr(b, "body", b) for b in bodies]
    transmits = [b.transmit for b in bases]
    placed = any(getattr(b, "placement", None) is not None for b in bodies)
    counts = topology_counts(transmits, ("solid", "sheet"))
    if placed:
        # a part's bodies count once however many instances use it, its faces and edges each time
        unique = list({id(t): t for t in transmits}.values())
        counts["bodies"] = topology_counts(unique, ("solid", "sheet"))["bodies"]
    _check_counts(counts, limits)
    if not bodies:
        raise InvalidArgumentError("there is no body to draw", detail={"parameter": "bodies"})
    opts = _tess_options(quality, limits)
    diagonal = _placed_diagonal(bodies) if placed else _approx_diagonal(transmits)
    if diagonal > 0.0:
        opts.pop("chord_fraction")
        opts["chord_m"] = min(max(diagonal * QUALITY_CHORD[quality], CHORD_MIN), CHORD_MAX)
    models = []
    built: dict[int, BrepModel] = {}
    t0 = time.perf_counter()
    for body, base in zip(bodies, bases, strict=True):
        model = built.get(id(base))
        if model is None:
            left = limits.seconds_tessellation - (time.perf_counter() - t0)
            if left <= 0:
                raise limits.exceeded(
                    "seconds_tessellation", "the part took longer to tessellate than a drawing allows"
                )
            opts["max_seconds"] = left
            t1 = time.perf_counter()
            tess = tessellate_body(base, body_types=("solid", "sheet"), **opts)
            took = time.perf_counter() - t1
            model = build(
                tess, [base.transmit], body_types=("solid", "sheet"), tess_seconds=took, names=[base.name]
            )
            built[id(base)] = model
        elif getattr(body, "placement", None) is not None:
            model = replace(model, seconds={"tessellation": 0.0, "model": 0.0})
        placement = getattr(body, "placement", None)
        if placement is not None:
            model = place(model, placement)
        if body is not base:
            model = replace(model, bodies=tuple(replace(b, name=body.name) for b in model.bodies))
        models.append(model)
    return merge(models, name=name)


def from_document(
    doc,
    configuration: str | None = None,
    *,
    quality: str = "normal",
    limits: DrawingLimits = DEFAULT_LIMITS,
) -> BrepModel:
    """The model of a SOLIDWORKS part's solid bodies in one configuration, leaving out
    bodies SOLIDWORKS hides."""
    from ..tessellate import bodies_of, shown_bodies

    _name, bodies, _w, _n = bodies_of(doc, configuration)
    bodies, _hidden = shown_bodies(bodies)
    solid = [b for b in bodies if getattr(b, "body_type", "solid") in ("solid", None)]
    return from_bodies(solid, name=getattr(doc, "name", "") or "", quality=quality, limits=limits)


def _approx_box(transmits: Sequence[XtTransmit]) -> tuple[Vec3, Vec3] | None:
    """The box of the bodies' vertices, from the topology alone; None when they hold
    none."""
    lo = [math.inf] * 3
    hi = [-math.inf] * 3

    def take(p) -> None:
        for i in range(3):
            lo[i] = min(lo[i], p[i])
            hi[i] = max(hi[i], p[i])

    for _k, topo, body, _n, _t in _chosen(transmits, ("solid", "sheet")):
        for f in topo.faces(body):
            for lp in topo.loops(f):
                for fin in topo.fins(lp):
                    edge = topo.ref(fin, "edge", (EDGE,))
                    if edge is None:
                        continue
                    for v in topo.edge_ends(edge):
                        p = topo.point_of(v) if v is not None else None
                        if p is not None:
                            take(p)
    if lo[0] == math.inf:
        return None
    return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])


def _approx_diagonal(transmits: Sequence[XtTransmit]) -> float:
    """The diagonal of the box of the bodies' vertices, from the topology alone; 0 when
    they hold none."""
    box = _approx_box(transmits)
    return 0.0 if box is None else math.dist(*box)


def placed_box(bodies: Sequence, box_of=None) -> tuple[Vec3, Vec3] | None:
    """The box of placed bodies (as :func:`from_bodies` takes them): each part body's
    box measured once (``box_of(transmit)``, by default from its vertices) and its
    corners placed for every instance; None when they hold no point."""
    box_of = box_of or (lambda t: _approx_box([t]))
    boxes: dict[int, tuple[Vec3, Vec3] | None] = {}
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for b in bodies:
        base = getattr(b, "body", b)
        if id(base) not in boxes:
            boxes[id(base)] = box_of(base.transmit)
        box = boxes[id(base)]
        if box is None:
            continue
        mover = _Mover(getattr(b, "placement", None))
        for x in (box[0][0], box[1][0]):
            for y in (box[0][1], box[1][1]):
                for z in (box[0][2], box[1][2]):
                    p = mover.point((x, y, z))
                    for i in range(3):
                        lo[i] = min(lo[i], p[i])
                        hi[i] = max(hi[i], p[i])
    if lo[0] == math.inf:
        return None
    return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])


def _placed_diagonal(bodies: Sequence) -> float:
    """The diagonal of the box of placed bodies (:func:`placed_box`)."""
    box = placed_box(bodies)
    return 0.0 if box is None else math.dist(*box)


def merge(models: Sequence[BrepModel], *, name: str = "") -> BrepModel:
    """One model of several single-transmit models, body ``k`` being ``models[k]``:
    faces, vertices, triangles and edge keys renumbered."""
    if len(models) == 1:
        m = models[0]
        return BrepModel(**{**m.__dict__, "name": name or m.name})
    faces: list[Face] = []
    edges: dict[tuple[int, int], Edge] = {}
    points: list = []
    normals: list = []
    triangles: list = []
    tri_face: list = []
    face_uv: list = []
    bodies: list[Body] = []
    skipped: list = []
    warnings: list[str] = []
    seconds = {"tessellation": 0.0, "model": 0.0}
    at_vertex: dict[tuple[int, int, int], tuple[Vec3, set[int], list]] = {}
    closed: bool | None = None
    for k, m in enumerate(models):
        fo, po, to = len(faces), len(points), len(triangles)

        def rekey(key, k=k):
            return (k, key[1])

        for f in m.faces:
            faces.append(
                Face(
                    f.index + fo,
                    k,
                    f.node_id,
                    f.kind,
                    f.surface,
                    f.sense,
                    f.area,
                    f.box,
                    tuple(tuple(rekey(e) for e in lp) for lp in f.loops),
                    (f.vertices[0] + po, f.vertices[1] + po),
                    (f.triangles[0] + to, f.triangles[1] + to),
                    f.signature,
                    tuple(n + fo for n in f.neighbours),
                )
            )
        for key, e in m.edges.items():
            nk = rekey(key)
            sides = tuple(s + fo if s >= 0 else s for s in e.faces)
            edges[nk] = Edge(
                nk,
                k,
                e.node_id,
                e.curve,
                e.points,
                e.params,
                sides,
                e.normals,
                e.length,
                e.kind,
                e.signature,
                e.ends,
            )
        for v in m.vertices:
            entry = at_vertex.setdefault(_vkey(v.point), (v.point, set(), []))
            entry[1].update(f + fo for f in v.faces)
            entry[2].extend(rekey(e) for e in v.edges)
        points.extend(m.points)
        normals.extend(m.normals)
        triangles.extend((a + po, b + po, c + po) for a, b, c in m.triangles)
        tri_face.extend(t + fo for t in m.tri_face)
        face_uv.extend(m.face_uv)
        for b in m.bodies:
            bodies.append(Body(k, b.name, b.type, tuple(f + fo for f in b.faces), b.volume))
        skipped.extend(m.skipped)
        warnings.extend(m.warnings)
        for key in seconds:
            seconds[key] += m.seconds.get(key, 0.0)
        if m.closed is not None:
            closed = m.closed if closed is None else closed and m.closed
    box, diagonal = _box(points)
    tol = max(diagonal * 1e-6, 1e-9)
    return BrepModel(
        name=name,
        bodies=tuple(bodies),
        faces=tuple(faces),
        edges=edges,
        vertices=tuple(Vertex(p, tuple(sorted(fs)), tuple(ks)) for p, fs, ks in at_vertex.values()),
        axis_groups=_axis_groups(faces, tol),
        points=tuple(points),
        normals=tuple(normals),
        triangles=tuple(triangles),
        tri_face=tuple(tri_face),
        face_uv=tuple(face_uv),
        box=box,
        diagonal=diagonal,
        tolerance=tol,
        chord=max(m.chord for m in models),
        closed=closed,
        skipped=tuple(skipped),
        seconds=seconds,
        warnings=tuple(warnings),
    )


class _Mover:
    """A rigid placement: ``point`` and ``vector`` in the new frame. ``mirrored`` when the
    rotation turns the frame inside out (a mirrored instance)."""

    def __init__(self, placement) -> None:
        if placement is None:
            self.R = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
            self.t = (0.0, 0.0, 0.0)
        else:
            self.R = tuple(tuple(float(v) for v in row) for row in placement.rotation)
            self.t = tuple(float(v) for v in placement.translation_m)
        r = self.R
        self.mirrored = (
            r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1])
            - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
            + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0])
        ) < 0.0

    def vector(self, v) -> Vec3:
        r = self.R
        return (
            r[0][0] * v[0] + r[0][1] * v[1] + r[0][2] * v[2],
            r[1][0] * v[0] + r[1][1] * v[1] + r[1][2] * v[2],
            r[2][0] * v[0] + r[2][1] * v[1] + r[2][2] * v[2],
        )

    def point(self, p) -> Vec3:
        r, t = self.R, self.t
        return (
            r[0][0] * p[0] + r[0][1] * p[1] + r[0][2] * p[2] + t[0],
            r[1][0] * p[0] + r[1][1] * p[1] + r[1][2] * p[2] + t[1],
            r[2][0] * p[0] + r[2][1] * p[1] + r[2][2] * p[2] + t[2],
        )

    def surface(self, s):
        P, V = self.point, self.vector
        if isinstance(s, Plane):
            n, o = V(s.normal), P(s.origin)
            return Plane(n, _dot(n, o), o, V(s.x), V(s.y))
        if isinstance(s, Cylinder):
            return Cylinder(P(s.point), V(s.axis), s.radius, V(s.x), V(s.y), s.concave)
        if isinstance(s, Cone):
            apex = None if s.apex is None else P(s.apex)
            return Cone(P(s.point), V(s.axis), s.radius, s.half_angle, V(s.x), V(s.y), s.concave, apex)
        if isinstance(s, Sphere):
            return Sphere(P(s.centre), s.radius, V(s.axis), s.concave)
        if isinstance(s, Torus):
            return Torus(P(s.centre), V(s.axis), s.major, s.minor, s.concave)
        return s

    def curve(self, c: Curve) -> Curve:
        if c.kind == "line":
            return replace(c, point=self.point(c.point), direction=self.vector(c.direction))
        if c.kind in ("circle", "ellipse"):
            # mirrored, the normal turns round with the frame so a parameter names the
            # same point
            n = self.vector(c.direction)
            if self.mirrored:
                n = _scale(n, -1.0)
            return replace(c, point=self.point(c.point), direction=n, x=self.vector(c.x))
        if c.kind == "bspline":
            return replace(c, points=tuple(self.point(p) for p in c.points))
        return c


def place(model: BrepModel, placement) -> BrepModel:
    """``model`` where ``placement`` puts it (a component in its assembly): every point,
    normal, surface, curve, box and vertex in the new frame, and the face and edge
    signatures and axis groups worked out again there. A mirrored placement keeps
    every face's outward normal, reverses the triangles' winding and turns each
    circle's and ellipse's normal round, so (u, v) and curve parameters still hold."""
    m = _Mover(placement)
    t0 = time.perf_counter()
    points = tuple(m.point(p) for p in model.points)
    normals = tuple(m.vector(n) for n in model.normals)
    triangles = tuple((a, c, b) for a, b, c in model.triangles) if m.mirrored else model.triangles
    tol = model.tolerance
    faces = []
    for f in model.faces:
        v0, v1 = f.vertices
        if v1 > v0:
            lo = tuple(min(points[v][i] for v in range(v0, v1)) for i in range(3))
            hi = tuple(max(points[v][i] for v in range(v0, v1)) for i in range(3))
            box = (lo, hi)
        else:
            box = f.box
        surface = m.surface(f.surface)
        faces.append(
            replace(
                f,
                surface=surface,
                box=box,
                signature=_face_signature(f.kind, surface, box, f.area, tol),
            )
        )
    edges = {}
    for key, e in model.edges.items():
        curve = m.curve(e.curve)
        pts = tuple(m.point(p) for p in e.points)
        edges[key] = replace(
            e,
            curve=curve,
            points=pts,
            normals=tuple(tuple(m.vector(n) for n in side) for side in e.normals),
            signature=_edge_signature(curve, pts, e.length, tol),
            ends=None if e.ends is None else (m.point(e.ends[0]), m.point(e.ends[1])),
        )
    box, diagonal = _box(points)
    seconds = dict(model.seconds)
    seconds["model"] = seconds.get("model", 0.0) + time.perf_counter() - t0
    return replace(
        model,
        faces=tuple(faces),
        edges=edges,
        vertices=tuple(replace(v, point=m.point(v.point)) for v in model.vertices),
        axis_groups=_axis_groups(faces, tol),
        points=points,
        normals=normals,
        triangles=triangles,
        box=box,
        diagonal=diagonal,
        seconds=seconds,
    )


def _tess_options(quality: str, limits: DrawingLimits) -> dict:
    if quality not in QUALITY_CHORD:
        raise InvalidArgumentError(
            f"quality must be one of {', '.join(QUALITY_CHORD)}", detail={"parameter": "quality"}
        )
    return {
        "detail": True,
        "chord_fraction": QUALITY_CHORD[quality],
        "max_faces": limits.faces,
        "max_triangles": limits.triangles,
        "max_seconds": limits.seconds_tessellation,
    }


def build(
    tess: Tessellation,
    transmits: Sequence[XtTransmit],
    *,
    name: str = "",
    body_types=("solid",),
    tess_seconds: float = 0.0,
    names: Sequence[str] | None = None,
) -> BrepModel:
    """A :class:`BrepModel` from a detailed tessellation of ``transmits``' chosen bodies
    (the same transmits, in the same order, with the same body types)."""
    if tess.detail is None:
        raise InvalidArgumentError(
            "the tessellation was made without detail=True", detail={"parameter": "tess"}
        )
    t0 = time.perf_counter()
    d = tess.detail
    chosen = _chosen(transmits, body_types)
    P = [(d.points[i], d.points[i + 1], d.points[i + 2]) for i in range(0, len(d.points), 3)]
    N = [(d.normals[i], d.normals[i + 1], d.normals[i + 2]) for i in range(0, len(d.normals), 3)]
    tri_flat = tess.mesh.triangles
    T = [(tri_flat[i], tri_flat[i + 1], tri_flat[i + 2]) for i in range(0, len(tri_flat), 3)]
    warnings: list[str] = []

    face_nodes = _face_nodes(tess, chosen, P, warnings)
    vertex_face = [0] * len(P)
    tri_face = [0] * len(T)
    geoms: dict[int, Geometry] = {}
    pre: list[dict] = []
    for k, fm in enumerate(tess.mesh.faces):
        body_k = tess.face_ids[k][0]
        v0, v1 = fm.first_vertex, fm.first_vertex + fm.n_vertices
        t0f, t1f = fm.first_triangle, fm.first_triangle + fm.n_triangles
        for v in range(v0, v1):
            vertex_face[v] = k
        area = 0.0
        lo = [math.inf] * 3
        hi = [-math.inf] * 3
        for ti in range(t0f, t1f):
            tri_face[ti] = k
            a, b, c = T[ti]
            area += 0.5 * _norm(_cross(_sub(P[b], P[a]), _sub(P[c], P[a])))
        for v in range(v0, v1):
            p = P[v]
            for i in range(3):
                lo[i] = min(lo[i], p[i])
                hi[i] = max(hi[i], p[i])
        node = face_nodes[k]
        surface, kind, sense = OtherSurface("unknown"), "other", 1
        if node is not None and body_k < len(chosen):
            topo = chosen[body_k][1]
            geom = geoms.get(id(topo))
            if geom is None:
                geom = geoms[id(topo)] = Geometry(topo, tess.chord_m)
            surface, kind, sense = _surface(topo, geom, node, P, N, v0)
        pre.append(
            {
                "index": k,
                "body": body_k,
                "node_id": tess.face_ids[k][1],
                "kind": kind,
                "surface": surface,
                "sense": sense,
                "area": area,
                "box": (tuple(lo), tuple(hi)) if v1 > v0 else ((0.0,) * 3, (0.0,) * 3),
                "vertices": (v0, v1),
                "triangles": (t0f, t1f),
                "node": node,
            }
        )

    box, diagonal = _box(P)
    tol = max(diagonal * 1e-6, 1e-9)
    key_of = _KeyOf()
    curve_of = _edge_curves(chosen, tess.chord_m, key_of)
    third = _third_vertices(T)
    edges: dict[tuple[int, int], Edge] = {}
    neighbours: dict[int, set[int]] = {k: set() for k in range(len(pre))}
    at_vertex: dict[tuple[int, int, int], tuple[Vec3, set[int], list]] = {}
    cos_tangent = math.cos(math.radians(TANGENT_DEGREES))
    for key, e in d.edges.items():
        pts = tuple((e.points[i], e.points[i + 1], e.points[i + 2]) for i in range(0, len(e.points), 3))
        sides = []
        normals = []
        for verts, nr in zip(e.vertices, e.normals, strict=True):
            first = next((v for v in verts if v >= 0), None)
            sides.append(vertex_face[first] if first is not None else -1)
            normals.append(tuple((nr[i], nr[i + 1], nr[i + 2]) for i in range(0, len(nr), 3)))
        length = plain_sum(_norm(_sub(pts[i + 1], pts[i])) for i in range(len(pts) - 1))
        kind = _edge_kind(sides, normals, e.vertices, pts, third, cos_tangent, P)
        curve = curve_of.get(key) or Curve("other")
        ring = len(pts) > 2 and _norm(_sub(pts[0], pts[-1])) <= tol
        ends = None if ring else (pts[0], pts[-1])
        edge = Edge(
            key,
            key[0],
            key[1] if key[1] > 0 else 0,
            curve,
            pts,
            tuple(e.params),
            tuple(sides),
            tuple(normals),
            length,
            kind,
            _edge_signature(curve, pts, length, tol),
            ends,
        )
        edges[key] = edge
        real = [s for s in sides if s >= 0]
        for s in real:
            for o in real:
                if o != s:
                    neighbours[s].add(o)
        if ends is not None:
            for p in ends:
                vk = _vkey(p)
                entry = at_vertex.setdefault(vk, (p, set(), []))
                entry[1].update(real)
                entry[2].append(key)
    vertices = tuple(Vertex(p, tuple(sorted(fs)), tuple(ks)) for p, fs, ks in at_vertex.values())

    faces = []
    for f in pre:
        loops = _loops(chosen, f["body"], f["node"], key_of) if f["node"] is not None else ()
        faces.append(
            Face(
                f["index"],
                f["body"],
                f["node_id"],
                f["kind"],
                f["surface"],
                f["sense"],
                f["area"],
                f["box"],
                loops,
                f["vertices"],
                f["triangles"],
                _face_signature(f["kind"], f["surface"], f["box"], f["area"], tol),
                tuple(sorted(neighbours[f["index"]])),
            )
        )

    body_names = list(names) if names is not None else list(tess.bodies)
    bodies = []
    for k, _topo, _b, default_name, btype in chosen:
        mine = tuple(f.index for f in faces if f.body == k)
        vol = 0.0
        for fi in mine:
            t_lo, t_hi = faces[fi].triangles
            for ti in range(t_lo, t_hi):
                a, b, c = T[ti]
                vol += _dot(P[a], _cross(P[b], P[c])) / 6.0
        bodies.append(Body(k, body_names[k] if k < len(body_names) else default_name, btype, mine, vol))

    return BrepModel(
        name=name,
        bodies=tuple(bodies),
        faces=tuple(faces),
        edges=edges,
        vertices=vertices,
        axis_groups=_axis_groups(faces, tol),
        points=tuple(P),
        normals=tuple(N),
        triangles=tuple(T),
        tri_face=tuple(tri_face),
        face_uv=tuple(tuple(a) for a in d.face_uv),
        box=box,
        diagonal=diagonal,
        tolerance=tol,
        chord=tess.chord_m,
        closed=tess.closed,
        skipped=tuple((s.body, s.face, s.surface, s.reason) for s in tess.skipped),
        seconds={"tessellation": tess_seconds, "model": time.perf_counter() - t0},
        warnings=tuple(warnings),
    )


def _box(P) -> tuple[tuple[Vec3, Vec3], float]:
    if not P:
        return ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)), 0.0
    lo = tuple(min(p[i] for p in P) for i in range(3))
    hi = tuple(max(p[i] for p in P) for i in range(3))
    return (lo, hi), math.dist(lo, hi)


def _face_nodes(tess: Tessellation, chosen, P, warnings: list[str]) -> list:
    """Each mesh face's FACE node: by node id where the body's ids are unique and
    positive, else in the body's face order, each candidate checked against the mesh
    face's first vertex so a face the tessellator left out is stepped over."""
    by_body: dict[int, tuple[dict[int, object] | None, list]] = {}
    for k, topo, body, _n, _t in chosen:
        nodes = topo.faces(body)
        ids = [topo.get(f, "node_id", None) for f in nodes]
        unique = all(isinstance(i, int) and i > 0 for i in ids) and len(set(ids)) == len(ids)
        by_body[k] = ({i: f for i, f in zip(ids, nodes, strict=True)} if unique else None, nodes)
    cursor = {k: 0 for k in by_body}
    # A body none of whose faces was left out has its mesh faces in its face order; only
    # where faces were left out is each candidate checked against the mesh.
    names = list(tess.bodies)
    gaps = {s.body for s in tess.skipped}
    out: list = []
    for k, fm in enumerate(tess.mesh.faces):
        body_k, fid = tess.face_ids[k]
        if body_k not in by_body:
            out.append(None)
            continue
        id_map, nodes = by_body[body_k]
        if id_map is not None and fid in id_map:
            out.append(id_map[fid])
            continue
        i = cursor[body_k]
        if body_k < len(names) and names[body_k] in gaps and fm.n_vertices:
            topo = chosen[body_k][1]
            geom = Geometry(topo, tess.chord_m)
            p = P[fm.first_vertex]
            j = i
            while j < len(nodes) and not _on_face(topo, geom, nodes[j], p, tess.chord_m):
                j += 1
            if j < len(nodes):
                i = j
        if i >= len(nodes):
            warnings.append(f"face {k} of the mesh could not be matched to its B-rep face")
            out.append(None)
            continue
        cursor[body_k] = i + 1
        out.append(nodes[i])
    return out


def _on_face(topo, geom, node, p, chord) -> bool:
    try:
        snode = topo.ref(node, "surface", SURFACE_TYPES, required=True)
        S = geom.surface(snode)
        result = S.closest(p, None, max(chord, 1e-9) * 4, max(chord, 1e-9) * 4)
    except (FaceFailed, ArithmeticError, ValueError, TypeError):
        return False
    dist = result[-1] if isinstance(result, tuple) else None
    return dist is not None and dist <= max(chord, 1e-9) * 4


def _surface(topo, geom, node, P, N, v0) -> tuple[object, str, int]:
    try:
        snode = topo.ref(node, "surface", SURFACE_TYPES, required=True)
    except FaceFailed:
        return OtherSurface("unknown"), "other", 1
    name = snode.tname
    try:
        S = geom.surface(snode)
    except FaceFailed:
        return OtherSurface(name), _OTHER_KINDS.get(name, name.lower()), topo.sense(node)
    sense = topo.sense(node) * topo.sense(snode) * getattr(S, "flip", 1)
    kind = _KINDS.get(name)
    p, n = (P[v0], N[v0]) if v0 < len(P) else ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    if kind == "plane":
        normal = _scale(S.N, sense)
        return Plane(normal, _dot(normal, S.P), tuple(S.P), tuple(S.X), tuple(S.Y)), kind, sense
    if kind in ("cylinder", "cone"):
        A = _unit(S.A)
        rel = _sub(p, S.P)
        radial = _sub(rel, _scale(A, _dot(rel, A)))
        concave = _dot(radial, n) < 0
        if kind == "cylinder":
            return Cylinder(tuple(S.P), A, S.r, tuple(S.X), tuple(S.Y), concave), kind, sense
        apex = None if S.t == 0.0 else _add(S.P, _scale(A, -S.r / S.t))
        return Cone(tuple(S.P), A, S.r, math.atan(S.t), tuple(S.X), tuple(S.Y), concave, apex), kind, sense
    if kind == "sphere":
        return Sphere(tuple(S.C), S.r, _unit(S.A), _dot(_sub(p, S.C), n) < 0), kind, sense
    if kind == "torus":
        A = _unit(S.A)
        rel = _sub(p, S.C)
        radial = _unit(_sub(rel, _scale(A, _dot(rel, A))))
        nearest_centre = _add(S.C, _scale(radial, S.R))
        return Torus(tuple(S.C), A, S.R, S.r, _dot(_sub(p, nearest_centre), n) < 0), kind, sense
    other = _OTHER_KINDS.get(name, name.lower())
    return OtherSurface(name), other, sense


class _KeyOf:
    """An EDGE node's detail key, assigned as the tessellator assigns it: (body, node_id)
    for the first edge to claim a positive id, else (body, -1 - node index)."""

    def __init__(self) -> None:
        self.owners: dict[tuple[int, int], int] = {}
        self.keys: dict[tuple[int, int], tuple[int, int]] = {}

    def __call__(self, body_k: int, topo, edge) -> tuple[int, int]:
        at = (body_k, edge.index)
        key = self.keys.get(at)
        if key is None:
            nid = topo.get(edge, "node_id", None)
            if (
                isinstance(nid, int)
                and nid > 0
                and self.owners.setdefault((body_k, nid), edge.index) == edge.index
            ):
                key = (body_k, nid)
            else:
                key = (body_k, -1 - edge.index)
            self.keys[at] = key
        return key


def _walk_edges(chosen, visit) -> None:
    for k, topo, body, _n, _t in chosen:
        for f in topo.faces(body):
            try:
                loops = topo.loops(f)
            except FaceFailed:
                continue
            for lp in loops:
                try:
                    fins = topo.fins(lp)
                except FaceFailed:
                    continue
                for fin in fins:
                    edge = topo.ref(fin, "edge", (EDGE,))
                    if edge is not None:
                        visit(k, topo, f, lp, edge)


def _edge_curves(chosen, chord, key_of: _KeyOf) -> dict[tuple[int, int], Curve]:
    """Every edge's curve by its key, walking the bodies in the tessellator's order so
    ``key_of`` assigns the keys it assigned."""
    out: dict[tuple[int, int], Curve] = {}
    geoms: dict[int, Geometry] = {}

    def visit(k, topo, _f, _lp, edge) -> None:
        key = key_of(k, topo, edge)
        if key in out:
            return
        geom = geoms.get(id(topo))
        if geom is None:
            geom = geoms[id(topo)] = Geometry(topo, chord)
        out[key] = _curve(topo, geom, edge)

    _walk_edges(chosen, visit)
    return out


def _curve(topo, geom, edge) -> Curve:
    try:
        node = topo.ref(edge, "curve", CURVE_TYPES)
        if node is None:
            return Curve("other")
        C = geom.curve(node)
    except (FaceFailed, ArithmeticError, ValueError):
        return Curve("other")
    while type(C).__name__ == "Trimmed":
        C = C.basis
    name = getattr(C, "name", "")
    if name == "LINE":
        return Curve("line", tuple(C.P), _unit(C.D))
    if name == "CIRCLE":
        return Curve("circle", tuple(C.C), tuple(C.N), C.a, C.a, tuple(C.X))
    if name == "ELLIPSE":
        return Curve("ellipse", tuple(C.C), tuple(C.N), C.a, C.b, tuple(C.X))
    if name == "B_CURVE":
        s = C.s
        if s.rational:
            pts = tuple(tuple(c[i] / c[-1] for i in range(3)) for c in s.cps)
            weights = tuple(c[-1] for c in s.cps)
        else:
            pts, weights = tuple(tuple(c[:3]) for c in s.cps), None
        return Curve("bspline", degree=s.p, knots=tuple(s.U), points=pts, weights=weights)
    return Curve("other")


def _third_vertices(T) -> dict[tuple[int, int], list[int]]:
    """For each mesh edge (as a sorted vertex pair) the third vertex of each triangle on
    it."""
    out: dict[tuple[int, int], list[int]] = {}
    for a, b, c in T:
        for u, v, w in ((a, b, c), (b, c, a), (c, a, b)):
            out.setdefault((u, v) if u < v else (v, u), []).append(w)
    return out


def _edge_kind(sides, normals, vertices, pts, third, cos_tangent, P) -> str:
    real = [s for s in sides if s >= 0]
    if len(real) < 2:
        return "open"
    if real[0] == real[1]:
        return "seam"
    n0, n1 = normals[0], normals[1]
    pairs = [(a, b) for a, b in zip(n0, n1, strict=False) if not (math.isnan(a[0]) or math.isnan(b[0]))]
    if pairs and all(_dot(a, b) >= cos_tangent for a, b in pairs):
        return "tangent"
    # Convex when side 0, leaving the edge square to it within its own tangent plane,
    # goes behind side 1's tangent plane. The triangle on the edge only says which way
    # side 0 lies; the test itself is local, so a long triangle cannot mislead it.
    verts = vertices[0]
    m = len(pts) // 2
    for i in (m, m - 1, 0):
        if not (0 <= i < len(pts) - 1 and verts[i] >= 0 and verts[i + 1] >= 0):
            continue
        n0i, n1i = n0[i], n1[i]
        if math.isnan(n0i[0]) or math.isnan(n1i[0]):
            continue
        t = _unit(_sub(pts[i + 1], pts[i]))
        across = _unit(_cross(n0i, t))
        pair = (verts[i], verts[i + 1]) if verts[i] < verts[i + 1] else (verts[i + 1], verts[i])
        for w in third.get(pair, ()):
            if _dot(_sub(P[w], pts[i]), across) < 0:
                across = _scale(across, -1.0)
            return "convex" if _dot(across, n1i) < 0 else "concave"
    return "convex"


def _edge_signature(curve: Curve, pts, length: float, tol: float) -> str:
    if curve.kind == "line" and len(pts) >= 2:
        return keys.line_edge(pts[0], pts[-1], tol)
    if curve.kind == "circle":
        return keys.circle_edge(curve.point, curve.direction, curve.radius, tol)
    lo = tuple(min(p[i] for p in pts) for i in range(3))
    hi = tuple(max(p[i] for p in pts) for i in range(3))
    return keys.other_edge(curve.kind, (lo, hi), length, tol)


def _face_signature(kind, surface, box, area, tol) -> str:
    if isinstance(surface, Plane):
        return keys.plane(surface.normal, surface.origin, tol)
    if isinstance(surface, Cylinder):
        return keys.cylinder(surface.point, surface.axis, surface.radius, tol)
    if isinstance(surface, Cone):
        return keys.cone(surface.point, surface.axis, surface.half_angle, tol, surface.apex)
    if isinstance(surface, Sphere):
        return keys.sphere(surface.centre, surface.radius, tol)
    if isinstance(surface, Torus):
        return keys.torus(surface.centre, surface.axis, surface.major, surface.minor, tol)
    return keys.other_face(kind, box, area, tol)


def _loops(chosen, body_k, node, key_of: _KeyOf) -> tuple[tuple[tuple[int, int], ...], ...]:
    topo = chosen[body_k][1]
    out = []
    try:
        for lp in topo.loops(node):
            ring = []
            for fin in topo.fins(lp):
                edge = topo.ref(fin, "edge", (EDGE,))
                if edge is not None:
                    ring.append(key_of(body_k, topo, edge))
            out.append(tuple(ring))
    except FaceFailed:
        return ()
    return tuple(out)


def _axis_groups(faces: Sequence[Face], tol: float) -> tuple[AxisGroup, ...]:
    groups: list[tuple[Vec3, Vec3, list[int]]] = []
    for f in faces:
        s = f.surface
        if isinstance(s, (Cylinder, Cone)):
            point, axis = s.point, s.axis
        elif isinstance(s, Torus):
            point, axis = s.centre, s.axis
        else:
            continue
        p, d = keys.canonical_axis(point, axis)
        for gp, gd, members in groups:
            if abs(abs(_dot(gd, d)) - 1.0) <= 1e-9 and _norm(_sub(gp, p)) <= tol:
                members.append(f.index)
                break
        else:
            groups.append((p, d, [f.index]))
    return tuple(AxisGroup(p, d, tuple(m)) for p, d, m in groups)


__all__ = [
    "QUALITY_CHORD",
    "AxisGroup",
    "Body",
    "BrepModel",
    "Cone",
    "Curve",
    "Cylinder",
    "Edge",
    "Face",
    "OtherSurface",
    "Plane",
    "Sphere",
    "Torus",
    "Vertex",
    "build",
    "from_bodies",
    "from_document",
    "from_transmit",
    "merge",
    "place",
    "placed_box",
    "topology_counts",
]
