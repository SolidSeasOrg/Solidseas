"""Full sections and detail views (``docs/DRAWINGS.md`` 8.9, 8.10).

A full section:

1. **Cut.** The welded mesh is cut with the plane: each vertex is classed by its
   signed distance toward the viewer, zero or more counting as the removed side
   everywhere; each crossing is keyed by the mesh edge it lies on, and pieces are
   chained from where a triangle leaves the removed side to where it enters it,
   so on a closed mesh every loop closes without joining by tolerance.
2. **Snap.** Each loop is split by the face it crosses, and each piece is drawn
   as the exact intersection where one has a closed form: a plane gives a line;
   a cylinder, cone or sphere whose axis is square to the plane gives a circle
   (an arc in the view); a cylinder whose axis lies in the plane gives lines;
   anything else the polyline itself.
3. **Hatch.** Thin parallel lines at 45 degrees (turned away from any outline
   that runs at that angle), clipped to the loops by the even-odd rule, spaced a
   paper distance apart.
4. **Behind.** What lies behind the plane is drawn with the same engine, the
   occluder keeping the triangles with any vertex behind the plane, and the cap
   hiding what projects inside it. A section draws no hidden lines.

A loop that does not close (a mesh with a face missing) refuses the hatch, and
the section says why; the planner then falls back to hidden lines.

A detail view is its parent's geometry clipped to a circle, at its own scale;
layout places and scales it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .display import Arc, EllipseArc, Polyline, Segment, Spline
from .facegraph import BrepModel, Cone, Cylinder, Plane, Sphere
from .limits import DEFAULT_LIMITS, DrawingLimits
from .types import Run, Source, ViewGeometry, ViewSpec
from .views.cleanup import Piece, cleanup
from .views.curves import edge_primitive, project, silhouette_primitive
from .views.hlr import STEP_FRACTION, Occluder, dot, own_faces_of_edge, vertex_faces, visibility
from .views.silhouettes import analytic, from_mesh

Vec3 = tuple[float, float, float]
Point = tuple[float, float]
HATCH_SPACING_M = 0.003  # 3 mm on paper at full size; layout respaces for the scale
HATCH_ANGLES = (45.0, 135.0, 30.0, 60.0, 120.0, 150.0)
PARALLEL_DEG = 2.0


@dataclass(frozen=True)
class Cut:
    """The section's loops: each a list of (3D point, face index of the piece that
    reaches it), and whether every loop closed."""

    loops: tuple[tuple[tuple[Vec3, int], ...], ...]
    closed: bool


def _weld(model: BrepModel):
    ids: dict[tuple[int, int, int], int] = {}
    points: list[Vec3] = []
    remap = []
    for p in model.points:
        key = (round(p[0] * 1e12), round(p[1] * 1e12), round(p[2] * 1e12))
        i = ids.get(key)
        if i is None:
            i = ids[key] = len(points)
            points.append(p)
        remap.append(i)
    tris = [(remap[a], remap[b], remap[c]) for a, b, c in model.triangles]
    return points, tris


def cut(model: BrepModel, point: Vec3, normal: Vec3) -> Cut:
    """The loops where the plane through ``point`` with ``normal`` (pointing to the
    removed side) cuts the model."""
    points, tris = _weld(model)
    s = [dot(p, normal) - dot(point, normal) for p in points]
    removed = [v >= 0.0 for v in s]
    starts: dict[tuple[int, int], tuple[tuple[int, int], int]] = {}

    def crossing(i: int, j: int) -> Vec3:
        t = s[i] / (s[i] - s[j])
        pi, pj = points[i], points[j]
        return tuple(pi[k] + (pj[k] - pi[k]) * t for k in range(3))

    for ti, (a, b, c) in enumerate(tris):
        sides = (removed[a], removed[b], removed[c])
        if all(sides) or not any(sides):
            continue
        leave = enter = None
        for i, j in ((a, b), (b, c), (c, a)):
            if removed[i] and not removed[j]:
                leave = (min(i, j), max(i, j))
            elif not removed[i] and removed[j]:
                enter = (min(i, j), max(i, j))
        if leave is not None and enter is not None:
            starts[leave] = (enter, model.tri_face[ti])
    loops = []
    closed = True
    seen: set[tuple[int, int]] = set()
    for first in sorted(starts):
        if first in seen:
            continue
        loop = []
        key = first
        while True:
            if key in seen:
                closed = closed and key == first
                break
            seen.add(key)
            nxt, face = starts[key]
            loop.append((crossing(*key), face))
            if nxt not in starts:
                closed = False  # the loop runs off the mesh: a face is missing
                break
            key = nxt
        loops.append(tuple(loop))
    return Cut(tuple(loops), closed)


def _snap(model: BrepModel, loop, normal: Vec3, frame) -> list:
    """The loop as display primitives in view coordinates, each piece on one face drawn
    exactly where a closed form exists."""
    pieces: list[list[tuple[Vec3, int]]] = []
    for p, f in loop:
        if pieces and pieces[-1][-1][1] == f:
            pieces[-1].append((p, f))
        else:
            pieces.append([(p, f)])
    if len(pieces) > 1 and pieces[0][0][1] == pieces[-1][-1][1]:
        pieces[0] = pieces.pop() + pieces[0]  # the loop started part way along a face
    # each piece runs from its first point to the next piece's first point
    out = []
    for k, piece in enumerate(pieces):
        nxt = pieces[(k + 1) % len(pieces)][0][0]
        pts = [p for p, _f in piece] + [nxt]
        face = model.faces[piece[0][1]] if piece[0][1] >= 0 else None
        s = face.surface if face is not None else None
        # a plane, or a cylinder or cone whose axis lies in the cutting plane: straight lines
        if isinstance(s, Plane) or (isinstance(s, (Cylinder, Cone)) and abs(dot(s.axis, normal)) < 1e-9):
            out.append(Segment(project(pts[0], frame), project(pts[-1], frame), "visible"))
            continue
        circle = None
        if isinstance(s, (Cylinder, Cone)) and abs(abs(dot(s.axis, normal)) - 1.0) < 1e-9:
            circle = s.point
        elif isinstance(s, Sphere):
            circle = s.centre
        if circle is not None:
            c2 = project(circle, frame)
            r = _exact_radius(s, pts[0], normal)
            angles = [math.atan2(project(p, frame)[1] - c2[1], project(p, frame)[0] - c2[0]) for p in pts]
            unwrapped = [angles[0]]
            for a in angles[1:]:
                while a - unwrapped[-1] > math.pi:
                    a -= 2 * math.pi
                while a - unwrapped[-1] < -math.pi:
                    a += 2 * math.pi
                unwrapped.append(a)
            a0, a1 = math.degrees(unwrapped[0]), math.degrees(unwrapped[-1])
            if abs(a1 - a0) >= 359.999:
                a0, a1 = 0.0, 360.0
            elif a1 < a0:
                a0, a1 = a1, a0
            out.append(Arc(c2, r, a0, a1, "visible"))
            continue
        out.append(Polyline(tuple(project(p, frame) for p in pts), False, "visible"))
    return out


def _exact_radius(s, p: Vec3, normal: Vec3) -> float:
    """The radius of the circle a revolved surface square to the plane cuts, at the
    plane through ``p``."""
    if isinstance(s, Cylinder):
        return s.radius
    if isinstance(s, Cone):
        along = dot(p, s.axis) - dot(s.point, s.axis)
        return max(0.0, s.radius + math.tan(s.half_angle) * along)
    h = dot(p, normal) - dot(s.centre, normal)
    return math.sqrt(max(0.0, s.radius * s.radius - h * h))


def _outline_points(loop, frame) -> list[Point]:
    return [project(p, frame) for p, _f in loop]


def _hatch_angle(outlines: list[list[Point]]) -> float:
    dirs = []
    for pts in outlines:
        for a, b in zip(pts, pts[1:] + pts[:1], strict=False):
            if math.dist(a, b) > 0:
                dirs.append(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180.0)
    for angle in HATCH_ANGLES:
        if all(min(abs(d - angle), 180.0 - abs(d - angle)) > PARALLEL_DEG for d in dirs):
            return angle
    return HATCH_ANGLES[0]


def hatch(
    outlines: list[list[Point]], spacing: float, angle: float | None = None
) -> list[tuple[Point, Point]]:
    """Hatch lines clipped to the loops by the even-odd rule."""
    if not outlines or spacing <= 0:
        return []
    angle = _hatch_angle(outlines) if angle is None else angle
    t = math.radians(angle)
    u = (math.cos(t), math.sin(t))
    n = (-u[1], u[0])
    offsets = [p[0] * n[0] + p[1] * n[1] for pts in outlines for p in pts]
    lo, hi = min(offsets), max(offsets)
    count = int((hi - lo) / spacing)
    if count > 10_000:
        spacing = (hi - lo) / 10_000
        count = 10_000
    lines = []
    edges = [(a, b) for pts in outlines for a, b in zip(pts, pts[1:] + pts[:1], strict=False)]
    for k in range(1, count + 1):
        c = lo + k * spacing
        hits = []
        for a, b in edges:
            da = a[0] * n[0] + a[1] * n[1] - c
            db = b[0] * n[0] + b[1] * n[1] - c
            if (da < 0) != (db < 0):
                f = da / (da - db)
                p = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
                hits.append(p[0] * u[0] + p[1] * u[1])
        hits.sort()
        for i in range(0, len(hits) - 1, 2):
            s0, s1 = hits[i], hits[i + 1]
            base = (n[0] * c, n[1] * c)
            lines.append(
                ((base[0] + u[0] * s0, base[1] + u[1] * s0), (base[0] + u[0] * s1, base[1] + u[1] * s1))
            )
    return lines


def _boundary_distance(outlines: list[list[Point]], p: Point) -> float:
    best = math.inf
    for pts in outlines:
        for a, b in zip(pts, pts[1:] + pts[:1], strict=False):
            ab = (b[0] - a[0], b[1] - a[1])
            l2 = ab[0] * ab[0] + ab[1] * ab[1]
            t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / l2))
            best = min(best, math.dist(p, (a[0] + ab[0] * t, a[1] + ab[1] * t)))
    return best


def _inside(outlines: list[list[Point]], p: Point) -> bool:
    c = False
    for pts in outlines:
        for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1], strict=False):
            if (ay > p[1]) != (by > p[1]) and p[0] < ax + (bx - ax) * (p[1] - ay) / (by - ay):
                c = not c
    return c


def section(
    model: BrepModel,
    spec: ViewSpec,
    *,
    limits: DrawingLimits = DEFAULT_LIMITS,
    hatch_spacing: float = HATCH_SPACING_M,
) -> tuple[ViewGeometry, str | None]:
    """A full section view: the cut outline, its hatch and what lies behind, and a
    reason when the hatch was refused (a loop that did not close)."""
    if spec.cut is None:
        raise ValueError("a section view needs its cutting plane")
    frame = spec.frame()
    right, up, d = frame
    origin, normal = spec.cut
    the_cut = cut(model, origin, normal)
    outlines = [_outline_points(loop, frame) for loop in the_cut.loops]
    side = [dot(p, normal) - dot(origin, normal) for p in model.points]
    behind = lambda ti: any(side[v] < 0 for v in model.triangles[ti])  # noqa: E731
    occ = Occluder(model, frame, keep=behind, budget=limits.visibility_queries)
    step = STEP_FRACTION * model.diagonal
    edge_tol = 2.0 * model.chord + model.tolerance
    at_vertex = vertex_faces(model)
    # the cut's outline ranks above everything behind it, so an edge lying under it goes
    pieces: list[Piece] = [Piece(list(o) + [o[0]], True, "edge", None, True, -1) for o in outlines if o]

    def kept_part(pts):
        out, cur = [], []
        for p in pts:
            if dot(p, normal) - dot(origin, normal) < 0:
                cur.append(p)
            elif cur:
                out.append(cur)
                cur = []
        if cur:
            out.append(cur)
        return [c for c in out if len(c) >= 2]

    def visible_runs(pts, own):
        runs = []
        for vis, part, _r in visibility(occ, pts, own, step):
            if not vis:
                continue
            # the cap, in front of everything behind the plane, hides what projects inside it
            cur = []
            for p in part:
                q = project(p, frame)
                if _inside(outlines, q) and _boundary_distance(outlines, q) > edge_tol:
                    if len(cur) >= 2:
                        runs.append(cur)
                    cur = []
                else:
                    cur.append(p)
            if len(cur) >= 2:
                runs.append(cur)
        return runs

    try:
        for edge in model.edges.values():
            if edge.kind in ("seam", "tangent"):
                continue
            for part in kept_part(edge.points):
                own = own_faces_of_edge(edge, at_vertex)
                for run in visible_runs(part, own):
                    pieces.append(Piece([project(p, frame) for p in run], True, "edge", (edge, run), True))
        for face in model.faces:
            if isinstance(face.surface, Plane):
                continue
            straight = isinstance(face.surface, (Cylinder, Cone))
            parts = analytic(model, face, d) if straight else from_mesh(model, face, d)
            own = frozenset({face.index, *face.neighbours})
            for piece3 in parts:
                for part in kept_part(piece3):
                    for run in visible_runs(part, own):
                        pieces.append(
                            Piece([project(p, frame) for p in run], True, "silhouette", (face, run, straight))
                        )
    except OverflowError:
        raise limits.exceeded("visibility_queries", "the section needed too many visibility tests") from None
    kept = cleanup(pieces, model.diagonal)
    runs: list[Run] = []
    for loop in the_cut.loops:
        for prim in _snap(model, loop, normal, frame):
            runs.append(Run(prim, "visible", Source(0, "section", "cut", spec.id)))
    for piece in kept:
        if piece.payload is None:
            continue  # the outline, drawn exactly below
        if piece.kind == "edge":
            edge, run = piece.payload
            prim = edge_primitive(edge.curve, run, frame, whole=False, closed=False)
            runs.append(Run(prim, "visible", Source(edge.body, "edge", edge.signature, spec.id)))
        else:
            face, run, straight = piece.payload
            runs.append(
                Run(
                    silhouette_primitive(run, frame, straight),
                    "visible",
                    Source(face.body, "silhouette", face.signature, spec.id),
                )
            )
    reason = None
    hatch_loops: tuple = ()
    if the_cut.closed and the_cut.loops:
        hatch_loops = tuple(tuple(o) for o in outlines)
        for a, b in hatch(outlines, hatch_spacing):
            runs.append(Run(Segment(a, b, "thin"), "thin", Source(0, "hatch", "hatch", spec.id)))
    elif the_cut.loops:
        reason = "a section loop does not close (a face of the mesh is missing), so it is not hatched"
    else:
        reason = "the cutting plane misses the part"
    geometry = ViewGeometry(spec.id, tuple(runs), hatch=hatch_loops)
    return geometry, reason


def section_through(axis_point: Vec3, view: ViewSpec, view_id: str, letter: str) -> ViewSpec:
    """A section replacing ``view``: the plane through ``axis_point`` square to the view's
    direction, the material toward the viewer removed."""
    return ViewSpec(
        view_id,
        "section",
        view.direction,
        view.up,
        f"section {letter}",
        parent=view.parent or view.id,
        letter=letter,
        hidden=False,
        tangent=view.tangent,
        cut=(axis_point, view.frame()[2]),
        replaces=view.id,
    )


# --------------------------------------------------------------------------- detail views


def _clip_segment(a: Point, b: Point, c: Point, r: float) -> list[tuple[Point, Point]]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    fx, fy = a[0] - c[0], a[1] - c[1]
    A = dx * dx + dy * dy
    if A == 0:
        return []
    B = 2 * (fx * dx + fy * dy)
    C = fx * fx + fy * fy - r * r
    disc = B * B - 4 * A * C
    if disc <= 0:
        return []
    sq = math.sqrt(disc)
    t0, t1 = max(0.0, (-B - sq) / (2 * A)), min(1.0, (-B + sq) / (2 * A))
    if t1 <= t0:
        return []
    return [((a[0] + dx * t0, a[1] + dy * t0), (a[0] + dx * t1, a[1] + dy * t1))]


def _clip_arc(arc: Arc, c: Point, r: float) -> list[tuple[float, float]]:
    """The angle ranges of ``arc`` inside the circle (c, r), in degrees."""
    d = math.dist(arc.centre, c)
    sweep = arc.sweep()
    if d + arc.radius <= r:
        return [(arc.start_deg, arc.start_deg + sweep)]
    if d >= arc.radius + r or d + r <= arc.radius:
        return []
    # the two angles where the arc crosses the circle
    a = (arc.radius**2 - r**2 + d * d) / (2 * d)
    base = math.degrees(math.atan2(c[1] - arc.centre[1], c[0] - arc.centre[0]))
    half = math.degrees(math.acos(max(-1.0, min(1.0, a / arc.radius))))
    lo, hi = base - half, base + half  # the part of the full circle inside
    out = []
    for shift in (-720.0, -360.0, 0.0, 360.0):
        s0, s1 = max(arc.start_deg, lo + shift), min(arc.start_deg + sweep, hi + shift)
        if s1 > s0:
            out.append((s0, s1))
    return out


def detail(parent: ViewGeometry, spec: ViewSpec, centre: Point, radius: float) -> ViewGeometry:
    """The parent view's runs clipped to the circle (``centre``, ``radius``) in the
    parent's view coordinates: the geometry of a detail view."""
    runs: list[Run] = []
    for run in parent.runs:
        p = run.primitive
        src = Source(run.source.body, run.source.kind, run.source.signature, spec.id)
        if isinstance(p, Segment):
            for a, b in _clip_segment(p.p0, p.p1, centre, radius):
                runs.append(Run(Segment(a, b, p.style, p.src), run.style, src))
        elif isinstance(p, Arc):
            for s0, s1 in _clip_arc(p, centre, radius):
                runs.append(Run(Arc(p.centre, p.radius, s0, s1, p.style, p.src), run.style, src))
        else:
            pts = _sample(p)
            cur: list[Point] = []
            for q in pts:
                if math.dist(q, centre) <= radius:
                    cur.append(q)
                else:
                    if len(cur) >= 2:
                        runs.append(Run(Polyline(tuple(cur), False, p.style, p.src), run.style, src))
                    cur = []
            if len(cur) >= 2:
                runs.append(Run(Polyline(tuple(cur), False, p.style, p.src), run.style, src))
    marks = tuple(m for m in parent.centre_marks if math.dist(m[0], centre) <= radius)
    return ViewGeometry(spec.id, tuple(runs), marks, faces_true_shape=parent.faces_true_shape)


def _sample(p) -> list[Point]:
    if isinstance(p, Polyline):
        return list(p.points)
    if isinstance(p, EllipseArc):
        n = 64
        return [p.point(p.t0 + (p.t1 - p.t0) * k / n) for k in range(n + 1)]
    if isinstance(p, Spline):
        from .painter import spline_points

        return spline_points(p, 1e-6)
    return []


__all__ = ["Cut", "cut", "detail", "hatch", "section", "section_through"]
