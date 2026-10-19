"""Triangle meshes of the Parasolid bodies SOLIDWORKS stores in a part (provisional).

SOLIDWORKS keeps a display mesh of a part only when the part was saved with
one; every part still holds its bodies as a Parasolid B-rep
(:meth:`Document.parasolid`). This package turns those bodies into triangles:
each edge is sampled once and both its faces use the samples, so a solid comes
out closed; each face is triangulated in its own (u, v), with seams cut and
poles opened, and curved faces get points inside until the triangles keep
within a chord tolerance of the surface. ``docs/API.md`` section 3.15 has the
API and ``docs/FORMAT.md`` 10.8 the conventions of the XT format it rests on.

A rolling blend (BLENDED_EDGE) is drawn from the rational B-spline the STEP export
writes for it (:mod:`.blend`), fitted to a tenth of the chord tolerance.

``detail=True`` (for drawings) also returns what the tessellator knew and the mesh
does not keep (:class:`TessDetail`): each edge's samples with their curve parameters
and both faces' exact normals there, each vertex's (u, v), and the points and
normals in float64. The mesh is the same either way.

Pure Python, standard library only. Every read and computation is bounded
(faces, points, triangles, time). What a file holds never raises: a face that
cannot be done is skipped with a reason, and the result says so.
"""

import math
import time
from array import array
from dataclasses import dataclass, field

from ..errors import InvalidArgumentError, ReaderWarning
from ..formats.solidworks.mesh import Mesh
from ..formats.solidworks.parasolid import BODY_TYPES, ParasolidBody, XtTransmit
from ._engine import Engine, Options, welded_measures
from .curves import curve_extent
from .surfaces import Geometry
from .topology import BODY, CURVE_TYPES, EDGE, SURFACE_TYPES, Clock, FaceFailed, Topology

DEFAULT_ANGLE_DEG = 15.0
DEFAULT_MAX_FACES = 200_000
DEFAULT_MAX_TRIANGLES = 5_000_000
DEFAULT_MAX_FACE_POINTS = 50_000
DEFAULT_MAX_EDGE_POINTS = 10_000
DEFAULT_MAX_SECONDS = 30.0
CHORD_FRACTION = 1e-3  # of the bodies' box diagonal
CHORD_MIN, CHORD_MAX = 1e-6, 1e-3

# Why a face was not tessellated. An open set, like every enum of SolidSeas.
REASONS = {
    "unsupported_surface": "its surface type is not tessellated yet (an offset of a rolling blend, for one)",
    "unsupported_curve": "one of its edges lies on a curve type that is not sampled yet",
    "fit_failed": "its rolling blend could not be approximated within the chord tolerance, or in its time",
    "max_seconds": "the time limit ran out before it (a rolling blend, done after every other face)",
    "orientation_conflict": (
        "it lies on a rolling blend closed round its spine and meets no face tangentially "
        "to take its side from"
    ),
    "seam_configuration": "its boundary wraps round the surface in a way not handled yet",
    "no_boundary": "it has no loop, on a surface that does not close (a plane), so nothing bounds it",
    "inversion_failed": "a point of its boundary could not be placed on its surface",
    "triangulation_failed": "its (u, v) polygon could not be triangulated",
    "edge_too_long": "one of its edges needs more points than max_edge_points",
    "max_face_points": "it needs more points than max_face_points",
    "bad_reference": "a pointer of its topology or geometry leads to the wrong kind of node",
    "bad_geometry": "its geometry holds values out of range",
    "non_finite": "its geometry holds a value that is not a finite number",
    "degenerate": "it has no area, or a point where none can be",
}


# What the self-checks count (``Tessellation.checks``), each a warning of the same code when
# it is not nought. ``loops_reversed`` is a repair; the others are findings.
CHECKS = {
    "loops_reversed": (
        "{n} faces whose loops all ran against them are drawn facing the way the file says, their loops "
        "read the other way round"
    ),
    "faces_folded": "{n} faces have triangles that fold over one another, so their area is wrong there",
    "faces_coarse": (
        "{n} faces reached max_face_points with triangles still farther from their surface than the "
        "chord tolerance"
    ),
    "solids_not_closed": (
        "{n} solids are not closed: some edge of their triangles is not used once each way"
    ),
    "shells_inside_out": (
        "{n} closed shells face the wrong way for how they nest (a solid inside out, or a void facing out)"
    ),
}


def check_warnings(checks: dict[str, int]) -> list[ReaderWarning]:
    """A warning for each self-check that found something (:data:`CHECKS`)."""
    return [
        ReaderWarning(code, text.format(n=checks[code])) for code, text in CHECKS.items() if checks.get(code)
    ]


@dataclass(frozen=True)
class SkippedFace:
    """A face that was not tessellated: ``body`` names its body, ``face`` is its FACE
    ``node_id`` (-1 when the whole body's walk failed), ``surface`` its surface type,
    ``reason`` a key of :data:`REASONS` and ``detail`` a sentence for people."""

    body: str
    face: int
    surface: str
    reason: str
    detail: str = ""


@dataclass(frozen=True)
class EdgeDetail:
    """One edge as the tessellator sampled it (``detail=True``).

    ``points`` holds the samples (float64 xyz, metres) from the edge's start vertex to
    its end vertex, the same points both faces' triangles use (a ring edge's last is
    its first); ``params`` each one's parameter on the curve sampled (for an
    intersection curve, its position along the chart). ``faces`` names the FACE
    ``node_id`` on each side that was tessellated, once per fin (a seam's one face
    twice), in the order the faces were done; for each, ``normals`` gives the face's
    unit outward normal at every sample (float64 xyz, from the surface itself; at a
    pole, the mean of the face's triangles there) and ``vertices`` the index of the
    mesh vertex of that face at every sample, or -1 (and a NaN normal) where the
    sample is no corner of the face's triangles (a point at a pole whose triangles
    all fell away)."""

    points: array
    params: array
    faces: tuple[int, ...]
    normals: tuple[array, ...]
    vertices: tuple[array, ...]


@dataclass(frozen=True)
class TessDetail:
    """What the tessellator knew beside the mesh, for drawings (``detail=True``).

    ``edges`` maps (index into ``bodies``, EDGE ``node_id``) to an :class:`EdgeDetail`
    for every edge of a face done; an edge whose ``node_id`` is missing or repeats
    another edge's of the body has -1 minus its node's index in the transmit instead.
    ``face_uv`` gives, for each face of the mesh (as ``face_ids``), the (u, v) of each
    of its vertices in order, flat float64 pairs, in the surface's own parameters as
    the tessellator evaluates it (for a rolling blend, those of its approximation).
    ``points`` and ``normals`` are the mesh's positions and corner normals in float64,
    aligned with its float32 ones."""

    edges: dict[tuple[int, int], EdgeDetail]
    face_uv: tuple[array, ...]
    points: array
    normals: array

    def nbytes(self) -> int:
        """The bytes its arrays hold (what it costs beside the mesh, roughly)."""
        n = len(self.points) * 8 + len(self.normals) * 8 + sum(len(a) * 8 for a in self.face_uv)
        for e in self.edges.values():
            n += (len(e.points) + len(e.params)) * 8
            n += sum(len(a) * 8 for a in e.normals) + sum(len(a) * a.itemsize for a in e.vertices)
        return n


@dataclass(frozen=True)
class Tessellation:
    """The triangles of some bodies.

    ``mesh`` holds one :class:`~solidseas.formats.solidworks.mesh.FaceTess` per face
    done (``offset`` -1), with outward normals, in metres; ``face_ids`` gives each
    one's (index into ``bodies``, FACE ``node_id``). ``counts`` has ``bodies``,
    ``bodies_skipped`` (whose walk failed), ``bodies_left_out`` (of a type not asked
    for), ``faces``, ``faces_done``, ``faces_skipped``, ``edges`` and ``triangles``;
    ``skipped`` lists the faces not done (at most 1,000; ``reasons`` counts them all).
    ``closed`` is whether every solid body came out watertight: False when a solid
    has a face not done, could not be walked, or a limit stopped the work, None when
    there was no solid. ``truncated`` names each limit that stopped the work.
    ``checks`` counts what the self-checks found (every key of :data:`CHECKS`), and
    ``warnings`` holds one warning for each that is not nought; ``face_shells`` gives
    the SHELL node index of each face done, in the order of ``face_ids``. ``detail`` is
    a :class:`TessDetail` when the call asked for it, else None."""

    mesh: Mesh
    face_ids: tuple[tuple[int, int], ...]
    configuration: str | None
    bodies: tuple[str, ...]
    chord_m: float
    angle_deg: float
    counts: dict[str, int]
    skipped: tuple[SkippedFace, ...]
    reasons: dict[str, int]
    closed: bool | None
    truncated: tuple[str, ...]
    warnings: tuple[ReaderWarning, ...]
    seconds: float = 0.0
    checks: dict[str, int] = field(default_factory=dict)
    face_shells: tuple[int, ...] = field(default=(), repr=False, compare=False)
    detail: TessDetail | None = field(default=None, repr=False, compare=False)
    _points: list = field(default_factory=list, repr=False, compare=False)
    _triangles: array = field(default_factory=lambda: array("I"), repr=False, compare=False)

    def welded(self) -> tuple[array, array]:
        """``(positions, triangles)``: the triangles over shared vertices (float64 xyz,
        metres, and uint32 index triples), as STL and 3MF want them. Faces meet on the
        same vertices, so a closed solid stays closed here."""
        remap: dict[int, int] = {}
        pos = array("d")
        tris = array("I")
        for i in self._triangles:
            j = remap.get(i)
            if j is None:
                j = remap[i] = len(remap)
                pos.extend(self._points[i])
            tris.append(j)
        return pos, tris

    def measures(self) -> dict:
        """``volume`` (m^3, meaningful for closed solids), ``area`` (m^2), ``centroid`` of
        the volume and ``box`` ((low), (high)), from the shared float64 vertices."""
        return welded_measures(self._points, self._triangles)


def _number(value, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise InvalidArgumentError(
            f"{name} must be a number from {low} to {high}", detail={"parameter": name}
        )
    return float(value)


def _count(value, name: str, low: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < low:
        raise InvalidArgumentError(
            f"{name} must be a whole number of at least {low}", detail={"parameter": name}
        )
    return value


def _options(
    chord_m=None,
    angle_deg=DEFAULT_ANGLE_DEG,
    max_faces=DEFAULT_MAX_FACES,
    max_triangles=DEFAULT_MAX_TRIANGLES,
    max_face_points=DEFAULT_MAX_FACE_POINTS,
    max_edge_points=DEFAULT_MAX_EDGE_POINTS,
    max_seconds=DEFAULT_MAX_SECONDS,
    chord_fraction=CHORD_FRACTION,
    max_chord_m=CHORD_MAX,
    blend_reserve_s=0.0,
    detail=False,
):
    chord = None if chord_m is None else _number(chord_m, "chord_m", 1e-9, 1.0)
    if not isinstance(detail, bool):
        raise InvalidArgumentError("detail must be True or False", detail={"parameter": "detail"})
    return (
        chord,
        _number(angle_deg, "angle_deg", 0.5, 90.0),
        _count(max_faces, "max_faces", 0),
        _count(max_triangles, "max_triangles", 0),
        _count(max_face_points, "max_face_points", 16),
        _count(max_edge_points, "max_edge_points", 2),
        _number(max_seconds, "max_seconds", 0.0, 1e6),
        _number(chord_fraction, "chord_fraction", 1e-6, 0.1),
        _number(max_chord_m, "max_chord_m", CHORD_MIN, 1.0),
        _number(blend_reserve_s, "blend_reserve_s", 0.0, 1e6),
        detail,
    )


def _body_types(body_types) -> frozenset[str]:
    if isinstance(body_types, str) or not all(isinstance(t, str) for t in body_types):
        raise InvalidArgumentError(
            "body_types is a sequence of body type names", detail={"parameter": "body_types"}
        )
    return frozenset(body_types)


def _box_points(topo: Topology, body, clock: Clock, geom: Geometry) -> list:
    """Points that bound a body: its vertices, and for faces or ring edges without
    vertices the extent of their sphere, torus or circle."""
    out = []
    try:
        faces = topo.faces(body)
    except FaceFailed:
        return out
    for face in faces:
        clock.tick()
        try:
            loops = topo.loops(face)
            if not loops:
                snode = topo.ref(face, "surface", SURFACE_TYPES)
                if snode is not None:
                    ext = getattr(geom.surface(snode), "extent", None)
                    if ext is not None:
                        out.extend(ext())
                continue
            for lp in loops:
                for fin in topo.fins(lp):
                    clock.tick()
                    vx = topo.ref(fin, "vertex")
                    if vx is not None:
                        p = topo.point_of(vx)
                        if p is not None:
                            out.append(p)
                        continue
                    edge = topo.ref(fin, "edge", (EDGE,))
                    node = topo.ref(edge, "curve", CURVE_TYPES) if edge is not None else None
                    if node is not None:
                        out.extend(curve_extent(geom.curve(node)))
        except FaceFailed:
            continue
    return out


def _chord(points, fraction: float = CHORD_FRACTION, high: float = CHORD_MAX) -> float:
    """``fraction`` of the box diagonal of ``points``, kept from :data:`CHORD_MIN` to
    ``high``."""
    if not points:
        return min(1e-4, high)
    lo = [min(p[i] for p in points) for i in range(3)]
    hi = [max(p[i] for p in points) for i in range(3)]
    try:
        diag = math.dist(lo, hi)
    except OverflowError:
        diag = math.inf
    if not math.isfinite(diag):  # an extent too large to measure: the default chord
        return min(1e-4, high)
    return min(max(diag * fraction, CHORD_MIN), high)


def _run(items, opts_tuple, *, configuration, warnings, t0=None) -> Tessellation:
    """``items``: (label, transmit, BODY node or None for every body, body type filter).
    ``t0`` is when the work began (reading the bodies, for one): the time limit runs
    from then."""
    if t0 is None:
        t0 = time.perf_counter()
    chord, angle_deg, max_faces, max_tris, max_fp, max_ep, max_s, fraction, high, reserve, detail = opts_tuple
    clock = Clock(max_s - (time.perf_counter() - t0))
    topos: dict[int, Topology] = {}
    bodies = []
    for label, xt, node, types in items:
        topo = topos.get(id(xt))
        if topo is None:
            topo = topos[id(xt)] = Topology(xt)
        nodes = [node] if node is not None else topo.bodies()
        for k, b in enumerate(nodes, 1):
            name = label if node is not None or len(nodes) == 1 else f"{label}#{k}"
            code = topo.get(b, "body_type", 0)
            btype = BODY_TYPES.get(code, "unknown") if isinstance(code, int) else "unknown"
            bodies.append((name, topo, b, btype, btype in types))
    if chord is None:
        pts: list = []
        try:
            for _name, topo, b, _btype, keep in bodies:
                if keep:
                    pts.extend(_box_points(topo, b, clock, Geometry(topo, CHORD_MAX)))
        except Exception:  # a damaged body: its faces will say why
            pass
        chord = _chord(pts, fraction, high)
    opts = Options(
        chord, math.radians(angle_deg), max_faces, max_tris, max_fp, max_ep, max_s, reserve, detail
    )
    engine = Engine(opts, clock)
    chosen = [(name, topo, b, btype) for name, topo, b, btype, keep in bodies if keep]
    engine.counts["bodies_left_out"] = len(bodies) - len(chosen)
    engine.run(chosen)
    counts = {
        k: engine.counts.get(k, 0)
        for k in (
            "bodies",
            "bodies_skipped",
            "bodies_left_out",
            "faces",
            "faces_done",
            "faces_skipped",
            "edges",
            "triangles",
        )
    }
    skipped = tuple(SkippedFace(*s) for s in engine.skipped)
    closed = all(engine.solids_closed) if engine.solids_closed else None
    if engine.truncated and any(btype == "solid" for _n, _t, _b, btype in chosen):
        closed = False  # a limit stopped the work: some solid is not whole
    found = {k: engine.checks.get(k, 0) for k in CHECKS}
    return Tessellation(
        mesh=engine.mesh,
        face_ids=tuple(engine.face_ids),
        configuration=configuration,
        bodies=tuple(name for name, _t, _b, _bt in chosen),
        chord_m=chord,
        angle_deg=angle_deg,
        counts=counts,
        skipped=skipped,
        reasons=dict(engine.reasons),
        closed=closed,
        truncated=tuple(dict.fromkeys(engine.truncated)),
        warnings=(*warnings, *check_warnings(found)),
        seconds=time.perf_counter() - t0,
        checks=found,
        face_shells=tuple(engine.face_shells),
        detail=_detail(engine) if detail else None,
        _points=engine.pts.p,
        _triangles=engine.welded,
    )


def _detail(engine: Engine) -> TessDetail:
    """The engine's records as a :class:`TessDetail`: each edge's samples and, for each
    face done that uses it, the face's normal and vertex at every sample."""
    P, normals = engine.pts.p, engine.detail_normals
    uses: dict[tuple[int, int], list[tuple[int, array]]] = {}
    for (_body, fid), edges in zip(engine.face_ids, engine.detail_edges, strict=True):
        for key, vertices in edges:
            uses.setdefault(key, []).append((fid, vertices))
    nan = (math.nan, math.nan, math.nan)
    out: dict[tuple[int, int], EdgeDetail] = {}
    for key, sides in uses.items():
        samples = engine.edge_samples[key]
        ids = samples.ids
        points = array("d")
        for i in ids:
            points.extend(P[i])
        t = samples.t
        params = array("d", t if t is not None and len(t) == len(ids) else [math.nan] * len(ids))
        per_face = []
        for _fid, vertices in sides:
            a = array("d")
            for k in vertices:
                a.extend(nan if k < 0 else normals[3 * k : 3 * k + 3])
            per_face.append(a)
        out[key] = EdgeDetail(
            points,
            params,
            tuple(fid for fid, _v in sides),
            tuple(per_face),
            tuple(v for _f, v in sides),
        )
    return TessDetail(out, tuple(engine.detail_uv), engine.detail_points, engine.detail_normals)


def tessellate_transmit(xt: XtTransmit, *, body_types=("solid", "sheet"), **options) -> Tessellation:
    """Every BODY of a parsed transmit (a part, a partition or an .x_b/.x_t file read
    with :func:`~solidseas.formats.solidworks.parasolid.read_file`)."""
    if not isinstance(xt, XtTransmit):
        raise InvalidArgumentError("xt is a parsed XtTransmit", detail={"parameter": "xt"})
    opts = _options(**options)
    return _run([("body", xt, None, _body_types(body_types))], opts, configuration=None, warnings=())


def tessellate_body(body: ParasolidBody, *, body_types=("solid", "sheet"), **options) -> Tessellation:
    """One body that :meth:`Document.parasolid` returned."""
    if not isinstance(body, ParasolidBody):
        raise InvalidArgumentError("body is a ParasolidBody", detail={"parameter": "body"})
    opts = _options(**options)
    return _run(
        [(body.name, body.transmit, None, _body_types(body_types))],
        opts,
        configuration=body.configuration_name,
        warnings=(),
    )


def bodies_of(doc, configuration: str | None = None, *, max_bytes=None, max_total_bytes=None):
    """``(configuration name, bodies, warnings, bytes inflated)``: the Parasolid bodies of
    one configuration of a part, as :func:`tessellate_document` takes them."""
    from ..formats.solidworks.parasolid import DEFAULT_MAX_TRANSMIT_BYTES

    cfg = doc.configuration(configuration)
    name = cfg.name if cfg is not None else configuration
    warnings: list[ReaderWarning] = []
    kw = {"max_bytes": max_bytes or DEFAULT_MAX_TRANSMIT_BYTES, "max_total_bytes": max_total_bytes}
    if cfg is not None and cfg.id is not None:
        res = doc.parasolid(configurations=(cfg.id,), **kw)
        bodies = [b for b in res.bodies if b.configuration_id == cfg.id]
    else:
        res = doc.parasolid(**kw)
        ids = {b.configuration_id for b in res.bodies}
        bodies = list(res.bodies) if len(ids) == 1 else []
        if len(ids) == 1:
            warnings.append(
                ReaderWarning(
                    "configuration_assumed",
                    "the document does not say which stored configuration this is; its only one was used",
                )
            )
    for prob in res.problems:
        warnings.append(ReaderWarning("bodies_unreadable", str(prob.get("error", "")), prob.get("stream")))
    if not bodies:
        warnings.append(
            ReaderWarning("no_stored_bodies", f"the document stores no bodies for configuration {name!r}")
        )
    return name, bodies, warnings, res.bytes_inflated


def shown_bodies(bodies) -> tuple[list, int]:
    """``(bodies kept, how many were hidden)``: the bodies of a part without those
    SOLIDWORKS hides (:func:`~solidseas.formats.solidworks.parasolid.body_hidden`, as
    the STEP export decides). A body whose state is not known is kept."""
    from ..formats.solidworks.parasolid import body_hidden

    kept = []
    for b in bodies:
        xt = b.transmit
        root = xt.by_index().get(1)
        if root is None or root.type != BODY:
            root = next((n for n in xt.nodes if n.type == BODY), None)
        if root is None or body_hidden(xt, root) is not True:
            kept.append(b)
    return kept, len(bodies) - len(kept)


def hidden_message(n: int) -> str:
    return (
        f"{n} {'body is' if n == 1 else 'bodies are'} hidden in SOLIDWORKS and left out, as SOLIDWORKS "
        "leaves hidden bodies out of what it exports"
    )


def tessellate_document(
    doc,
    configuration: str | None = None,
    *,
    body_types=("solid", "sheet"),
    include_hidden: bool = True,
    **options,
) -> Tessellation | None:
    """The bodies of one configuration of a part (None: the active one), or None for an
    assembly or a drawing. A configuration whose partition the document does not store
    gives an empty result with the warning ``no_stored_bodies``: another
    configuration's bodies are never taken in its place. ``max_seconds`` counts
    reading the bodies too (a read once started runs to its end). Raises
    :class:`~solidseas.errors.InvalidArgumentError` for a bad option and
    :class:`~solidseas.errors.ConfigurationNotFoundError` for an unknown name; nothing
    in the file raises. With ``include_hidden`` False, bodies hidden in SOLIDWORKS are
    left out (:func:`shown_bodies`) with the warning ``bodies_left_out``."""
    if doc.doc_type != "part":
        return None
    opts = _options(**options)
    types = _body_types(body_types)
    t0 = time.perf_counter()
    name, bodies, warnings, _n = bodies_of(doc, configuration)
    if not include_hidden:
        bodies, hidden = shown_bodies(bodies)
        if hidden:
            warnings = [*warnings, ReaderWarning("bodies_left_out", hidden_message(hidden))]
    items = [(b.name, b.transmit, None, types) for b in bodies]
    return _run(items, opts, configuration=name, warnings=warnings, t0=t0)


__all__ = [
    "CHECKS",
    "DEFAULT_MAX_EDGE_POINTS",
    "DEFAULT_MAX_FACE_POINTS",
    "DEFAULT_MAX_FACES",
    "DEFAULT_MAX_SECONDS",
    "DEFAULT_MAX_TRIANGLES",
    "REASONS",
    "EdgeDetail",
    "SkippedFace",
    "TessDetail",
    "Tessellation",
    "bodies_of",
    "hidden_message",
    "check_warnings",
    "tessellate_body",
    "shown_bodies",
    "tessellate_document",
    "tessellate_transmit",
]
