"""Views of a part: ``project(model, spec)`` and ``make_views(model, features, options,
settings)`` (``docs/DRAWINGS.md`` 8).

``project`` draws one view: every edge on the tessellator's shared samples and
every curved face's silhouette, through the hidden-line engine (:mod:`.hlr`),
cleaned in 2D (:mod:`.cleanup`), each surviving run as its exact entity
(:mod:`.curves`) with its style and source, plus centre marks and lines
(:mod:`.centres`), the faces seen in true shape, the axes seen end-on and
side-on, virtual sharps, and the witnesses the planner asks about before it
attaches a dimension (C8).

Tangent edges follow the view's setting (left out, thin or phantom) except
where their common normal is square to the view within 2 degrees: then they are
outline and drawn visible (8.6, measured on o11). The isometric draws visible
runs only, its tangent edges thin, and no centre marks. Hidden lines are drawn
only when the view asks for them.

``make_views`` draws the default set: front, top and right (or what the options
name) and the isometric, framed from the front direction and its quarter turn.
Choosing the front and the views by coverage is the planner's (8.2, 8.3,
``dwg-plan``), which calls ``project`` for the views it picks.
"""

from __future__ import annotations

import math
import time

from ..facegraph import BrepModel, Cone, Cylinder, Plane
from ..limits import DEFAULT_LIMITS, DrawingLimits
from ..types import AngledFace, DrawingOptions, FeatureSet, Run, Source, ViewGeometry, ViewSpec, Witness
from .centres import centres
from .cleanup import Piece, cleanup, length
from .curves import edge_primitive, silhouette_primitive
from .curves import project as project_point
from .hlr import STEP_FRACTION, Occluder, circle_snap, dot, own_faces_of_edge, vertex_faces, visibility
from .silhouettes import analytic, from_mesh

SQUARE_DEG = 2.0
SHORT_FRACTION = 2e-4
DRAFT_STEP = 2.0  # Draft samples visibility half as often (8.12)

Vec3 = tuple[float, float, float]


def _cross(a, b) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a) -> Vec3:
    n = math.sqrt(dot(a, a))
    return (a[0] / n, a[1] / n, a[2] / n)


_FRONT_UP = {
    "+z": (0.0, 1.0, 0.0),
    "-z": (0.0, 1.0, 0.0),
    "+x": (0.0, 1.0, 0.0),
    "-x": (0.0, 1.0, 0.0),
    "+y": (0.0, 0.0, -1.0),
    "-y": (0.0, 0.0, 1.0),
}
_AXES = {
    "+x": (1.0, 0.0, 0.0),
    "-x": (-1.0, 0.0, 0.0),
    "+y": (0.0, 1.0, 0.0),
    "-y": (0.0, -1.0, 0.0),
    "+z": (0.0, 0.0, 1.0),
    "-z": (0.0, 0.0, -1.0),
}


def view_frames(front: str = "+z", turn: int = 0) -> dict[str, tuple[Vec3, Vec3]]:
    """(direction, up) of every principal view and the isometric, third angle, for a
    front seen from ``front`` turned by ``turn`` quarter turns."""
    d = _AXES[front]
    up = _FRONT_UP[front]
    for _ in range(turn % 4):
        up = _cross(d, up)  # a quarter turn of the sheet about the front's direction
    right = _cross(up, d)
    neg = lambda v: (-v[0], -v[1], -v[2])  # noqa: E731
    iso_d = _unit(tuple(right[k] + up[k] + d[k] for k in range(3)))
    iso_up = _unit(tuple(2 * up[k] - right[k] - d[k] for k in range(3)))
    return {
        "front": (d, up),
        "top": (up, neg(d)),
        "right": (right, up),
        "left": (neg(right), up),
        "bottom": (neg(up), d),
        "back": (neg(d), up),
        "isometric": (iso_d, iso_up),
    }


def _arc_params(edge, s0: float, s1: float) -> tuple[float, float] | None:
    """The curve parameters at arc lengths s0 and s1 along an edge's samples."""
    params = edge.params
    if not params or any(math.isnan(t) for t in params):
        return None
    cum = [0.0]
    for a, b in zip(edge.points, edge.points[1:], strict=False):
        cum.append(cum[-1] + math.dist(a, b))

    def at(s: float) -> float:
        for k in range(1, len(cum)):
            if s <= cum[k] or k == len(cum) - 1:
                span = cum[k] - cum[k - 1]
                f = 0.0 if span == 0 else min(1.0, max(0.0, (s - cum[k - 1]) / span))
                return params[k - 1] + (params[k] - params[k - 1]) * f
        return params[-1]

    return at(s0), at(s1)


def project(
    model: BrepModel,
    spec: ViewSpec,
    *,
    features: FeatureSet | None = None,
    limits: DrawingLimits = DEFAULT_LIMITS,
    quality: str = "normal",
) -> ViewGeometry:
    """One view of the model (8.4 to 8.8)."""
    frame = spec.frame()
    right, up, d = frame
    iso = spec.kind == "isometric"
    hidden = spec.hidden and not iso
    tangent_mode = "thin" if iso else spec.tangent
    occ = Occluder(model, frame, budget=limits.visibility_queries)
    step = STEP_FRACTION * model.diagonal * (DRAFT_STEP if quality == "draft" else 1.0)
    at_vertex = vertex_faces(model)
    sin_sq = math.sin(math.radians(SQUARE_DEG))
    short = SHORT_FRACTION * model.diagonal
    pieces: list[Piece] = []
    try:
        for edge in model.edges.values():
            if edge.kind == "seam":
                continue
            style = "visible"
            if edge.kind == "tangent":
                ns = [n for n in edge.normals[0] if not math.isnan(n[0])]
                outline = bool(ns) and all(abs(dot(n, d)) < sin_sq for n in ns)
                if not outline:
                    if tangent_mode == "hidden":
                        continue
                    style = "thin" if tangent_mode == "thin" else "phantom"
            flat = [project_point(p, frame) for p in edge.points]
            if length(flat) < short:
                continue  # seen end on
            own = own_faces_of_edge(edge, at_vertex)
            runs = visibility(occ, edge.points, own, step, circle_snap(edge.curve))
            whole = len(runs) == 1
            for visible, part, (s0, s1) in runs:
                if not visible and not hidden:
                    continue
                pieces.append(
                    Piece(
                        [project_point(p, frame) for p in part],
                        visible,
                        "edge",
                        (edge, part, style if visible else "hidden", whole, (s0, s1)),
                        edge.curve.kind != "line",
                    )
                )
        for face in model.faces:
            if isinstance(face.surface, Plane):
                continue
            own = frozenset({face.index, *face.neighbours})
            straight = isinstance(face.surface, (Cylinder, Cone))
            parts = analytic(model, face, d) if straight else from_mesh(model, face, d)
            for piece3 in parts:
                for visible, part, _range in visibility(occ, piece3, own, step):
                    if not visible and not hidden:
                        continue
                    pieces.append(
                        Piece(
                            [project_point(p, frame) for p in part],
                            visible,
                            "silhouette",
                            (face, part, "visible" if visible else "hidden", straight),
                            not straight,
                        )
                    )
    except OverflowError:
        raise limits.exceeded(
            "visibility_queries", f"the {spec.name or spec.id} view needed too many visibility tests"
        ) from None
    kept = cleanup(pieces, model.diagonal)
    runs: list[Run] = []
    edge_visible: dict[str, bool] = {}
    for piece in kept:
        if piece.kind == "edge":
            edge, part, style, whole, (s0, s1) = piece.payload
            closed = edge.ends is None
            prim = edge_primitive(edge.curve, part, frame, whole=whole and piece.visible, closed=closed)
            src = Source(edge.body, "edge", edge.signature, spec.id)
            runs.append(Run(_styled(prim, style, src), style, src, _arc_params(edge, s0, s1)))
            edge_visible[edge.signature] = edge_visible.get(edge.signature, False) or piece.visible
        else:
            face, part, style, straight = piece.payload
            prim = silhouette_primitive(part, frame, straight)
            src = Source(model.faces[face.index].body, "silhouette", face.signature, spec.id)
            runs.append(Run(_styled(prim, style, src), style, src))
    marks, lines, circles, end_on, side_on = ((), (), (), (), ()) if iso else centres(model, frame, features)
    for c in circles:
        runs.append(Run(c, "centre", Source(0, "centre", "pitch circle", spec.id)))
    true_shape = tuple(
        f.index for f in model.faces if isinstance(f.surface, Plane) and dot(f.surface.normal, d) > 1 - 1e-9
    )
    sharps = []
    if features is not None and not iso:
        for f in features.features:
            if isinstance(f, AngledFace) and f.virtual_sharp and f.meet_line is not None:
                if abs(abs(dot(f.meet_line.direction, d)) - 1.0) <= 1e-9:
                    sharps.append(project_point(f.meet_line.point, frame))
    return ViewGeometry(
        spec.id,
        tuple(runs),
        tuple(marks),
        tuple(lines),
        (),
        tuple(sorted(edge_visible.items())),
        true_shape,
        tuple(end_on),
        tuple(side_on),
        tuple(sharps),
        _witnesses(runs, model.tolerance * 10),
    )


def _styled(prim, style: str, src: Source):
    """The primitive with its style and source set (display primitives are frozen)."""
    from dataclasses import replace

    from ..display import Src

    return replace(prim, style=style, src=Src(src.body, src.signature, src.view))


def _witnesses(runs: list[Run], tol: float) -> tuple[Witness, ...]:
    """Visible straight runs square to a sheet axis: a vertical line is a witness at
    its x, a horizontal one at its y (C8)."""
    out = []
    for r in runs:
        if r.style not in ("visible",):
            continue
        p = r.primitive
        if type(p).__name__ != "Segment":
            continue
        (x0, y0), (x1, y1) = p.p0, p.p1
        if abs(x1 - x0) <= tol and abs(y1 - y0) > tol:
            out.append(Witness("x", (x0 + x1) / 2, min(y0, y1), max(y0, y1), r.source))
        elif abs(y1 - y0) <= tol and abs(x1 - x0) > tol:
            out.append(Witness("y", (y0 + y1) / 2, min(x0, x1), max(x0, x1), r.source))
    out.sort(key=lambda w: (w.axis, round(w.position, 12), w.low))
    return tuple(out)


def default_specs(options: DrawingOptions, settings) -> list[ViewSpec]:
    """The views ``make_views`` draws for these options and settings."""
    proc = options.process
    defaults = settings.defaults.views[proc]
    if options.views == "auto":
        names = list(defaults["views"])
        iso = defaults["isometric"]
    else:
        names = [v for v in options.views if v != "isometric"]
        iso = "isometric" in options.views
    hidden = options.hidden if options.hidden is not None else defaults["hidden"]
    tangent = options.tangent or defaults["tangent"]
    front = options.front or (defaults["front"] if defaults["front"] != "auto" else "+z")
    frames = view_frames(front, options.turn)
    if "front" not in names:
        names.insert(0, "front")
    order = ["front", "top", "right", "left", "bottom", "back"]
    names = [n for n in order if n in names]
    specs = []
    for k, name in enumerate(names, 1):
        dd, up = frames[name]
        kind = "base" if name == "front" else "projected"
        specs.append(
            ViewSpec(
                f"v-{k}",
                kind,
                dd,
                up,
                name,
                None if name == "front" else "v-1",
                hidden=hidden,
                tangent=tangent,
            )
        )
    if iso:
        dd, up = frames["isometric"]
        specs.append(
            ViewSpec(
                f"v-{len(specs) + 1}", "isometric", dd, up, "isometric", "v-1", hidden=False, tangent="thin"
            )
        )
    return specs


def make_views(
    model: BrepModel,
    features: FeatureSet | None,
    options: DrawingOptions,
    settings,
    *,
    limits: DrawingLimits = DEFAULT_LIMITS,
) -> tuple[tuple[ViewSpec, ViewGeometry], ...]:
    """The default views, each with its geometry, within ``seconds_views`` in all."""
    start = time.perf_counter()
    specs = default_specs(options, settings)
    if len(specs) > limits.views:
        raise limits.exceeded("views", "the drawing asks for more views than a sheet takes")
    out = []
    for spec in specs:
        out.append((spec, project(model, spec, features=features, limits=limits, quality=options.quality)))
        if time.perf_counter() - start > limits.seconds_views:
            raise limits.exceeded("seconds_views", "drawing the views took longer than a drawing allows")
    return tuple(out)


__all__ = ["default_specs", "make_views", "project", "view_frames"]
