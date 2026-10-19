"""An assembly's plan (``docs/drawings/assemblies.md``): the views as drawn, the
assembly's overall size as reference dimensions (:func:`overall_size`), the title
fields, the parts list and an item balloon for each of its lines. Each line carries
the number of the item's own drawing (:func:`drawing_number`), so the reader goes from
the assembly to each component's drawing.

**Balloons.** A line's balloon goes in the first view, in this order, where one of
its instances shows a visible edge: the isometric, the front, then the other views
in the drawing's order; the other views that show it are kept in order, for a
layout that leaves the first out. Its leader ends at the middle of a visible run
of the line's instances there (for a sub-assembly's line, of the parts inside
it), so it points at an edge of the part it names: of the runs at least a
quarter as long as the longest, the one nearest the view's outline going out
from the view's centre, so the leader is short and the leaders fan out.

**A part hidden behind others.** A line none of whose instances shows a visible
run in any view, though drawn (inside another part, or behind several), has its
instances' hidden lines drawn, dashed, in the views that draw no hidden lines
(:func:`show_hidden`), and its balloon goes as above on those hidden runs: in the
front, then the other views, since the isometric draws none. Only such parts'
hidden lines are drawn, so an assembly with none hidden is drawn as before. A line
that shows no run at all, visible or hidden, gets no balloon; the plan says so and
the checks report it.

**A parts list the BOM editor set** (the drawing's ``parts_list`` option, a
:class:`~solidseas.bomtable.BomTableSpec`) is applied to the BOM of its type
(:func:`solidseas.bomtable.apply`): its columns and headings, its order, the rows
it hides (and no balloon for them) and the cells typed over. The lines are numbered
as shown, so the balloons carry those numbers, and a DWG NO. column not typed over
holds the item's drawing number. An edit whose part is no longer in the assembly is
reported.
"""

from __future__ import annotations

import math
import os
import re
import time
from dataclasses import replace
from typing import Any

from .. import display as D
from ..limits import DEFAULT_LIMITS, DrawingLimits
from ..numbers import plain_sum
from ..types import Balloon, NoteLine, Plan, PlannedDimension
from . import PlanDetail, Planned, _Ids, _position, notes, values
from .assign import Assigner
from .context import AXES, Context
from .requirements import Pos, Requirements

_RUN_KINDS = ("edge", "silhouette")


def _de_boor(degree: int, knots, points, weights, t: float) -> tuple[float, float]:
    """A B-spline's point at ``t`` (rational when ``weights`` are given)."""
    n = len(points)
    k = degree
    span = k
    while span < n - 1 and knots[span + 1] <= t:
        span += 1
    w = weights or (1.0,) * n
    d = [(points[j][0] * w[j], points[j][1] * w[j], w[j]) for j in range(span - k, span + 1)]
    for r in range(1, k + 1):
        for j in range(k, r - 1, -1):
            i = j + span - k
            den = knots[i + k + 1 - r] - knots[i]
            a = 0.0 if den == 0 else (t - knots[i]) / den
            d[j] = tuple((1 - a) * d[j - 1][c] + a * d[j][c] for c in range(3))
    x, y, ww = d[k]
    return (x / ww, y / ww) if ww else (x, y)


def _length(pts) -> float:
    return plain_sum(math.dist(a, b) for a, b in zip(pts, pts[1:], strict=False))


def middle(prim: Any) -> tuple[tuple[float, float], float] | None:
    """The middle of a run's primitive and its length, view metres, or None."""
    if isinstance(prim, D.Segment):
        a, b = prim.p0, prim.p1
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), math.dist(a, b)
    if isinstance(prim, D.Arc):
        sweep = prim.sweep()
        return prim.point(prim.start_deg + sweep / 2), math.radians(sweep) * prim.radius
    if isinstance(prim, D.EllipseArc):
        n = 32
        pts = [prim.point(prim.t0 + (prim.t1 - prim.t0) * k / n) for k in range(n + 1)]
        return prim.point((prim.t0 + prim.t1) / 2), _length(pts)
    if isinstance(prim, D.Polyline):
        pts = list(prim.points) + ([prim.points[0]] if prim.closed and prim.points else [])
        if len(pts) < 2:
            return None
        steps = [math.dist(a, b) for a, b in zip(pts, pts[1:], strict=False)]
        total = plain_sum(steps)
        half, run = total / 2, 0.0
        for (a, b), s in zip(zip(pts, pts[1:], strict=False), steps, strict=True):
            if run + s >= half and s > 0:
                f = (half - run) / s
                return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f), total
            run += s
        return pts[-1], total
    if isinstance(prim, D.Spline):
        k = prim.degree
        lo, hi = prim.knots[k], prim.knots[len(prim.points)]
        pts = [_de_boor(k, prim.knots, prim.points, prim.weights, lo + (hi - lo) * j / 16) for j in range(17)]
        mid = _de_boor(k, prim.knots, prim.points, prim.weights, (lo + hi) / 2)
        return mid, _length(pts)
    return None


def view_order(ctx: Context) -> list[str]:
    """The views a balloon is tried in: the isometric, the front, then the others."""
    specs = [s for s, _g in ctx.views]
    first = [s.id for s in specs if s.kind == "isometric"] + [s.id for s in specs if s.kind == "base"]
    return first + [s.id for s in specs if s.id not in first]


def _exit(p, centre, box) -> float:
    """How far ``p`` lies inside ``box`` going out from ``centre`` through it."""
    dx, dy = p[0] - centre[0], p[1] - centre[1]
    n = math.hypot(dx, dy)
    if n == 0.0:
        return min(p[0] - box[0], box[2] - p[0], p[1] - box[1], box[3] - p[1])
    ux, uy = dx / n, dy / n
    t = math.inf
    for u, q, lo, hi in ((ux, p[0], box[0], box[2]), (uy, p[1], box[1], box[3])):
        if u > 1e-12:
            t = min(t, (hi - q) / u)
        elif u < -1e-12:
            t = min(t, (lo - q) / u)
    return max(0.0, t)


def _runs(
    ctx: Context, contents: Any, style: str
) -> dict[tuple[str, str], list[tuple[float, tuple[float, float]]]]:
    """Each instance's runs of ``style`` in each view, as (length, middle)."""
    body_instance = {k: b.instance for k, b in enumerate(contents.bodies)}
    out: dict[tuple[str, str], list[tuple[float, tuple[float, float]]]] = {}
    for spec, geom in ctx.views:
        for run in geom.runs:
            if run.style != style or run.source.kind not in _RUN_KINDS:
                continue
            inst = body_instance.get(run.source.body)
            got = middle(run.primitive) if inst is not None else None
            if got is not None and got[1] > 0.0:
                out.setdefault((spec.id, inst), []).append((got[1], got[0]))
    return out


def _unseen(ctx: Context, contents: Any, lines: Any) -> list[Any]:
    """The lines drawn in some view none of whose instances shows a visible run in any."""
    seen = {inst for _view, inst in _runs(ctx, contents, "visible")}
    return [
        line
        for line in lines
        if (members := contents.instances_of(line)) and not any(i.id in seen for i in members)
    ]


def show_hidden(ctx: Context, contents: Any, lines: Any, limits: DrawingLimits = DEFAULT_LIMITS) -> Context:
    """``ctx`` with the hidden lines of the parts hidden behind others drawn, dashed, in
    each view that draws no hidden lines (:func:`solidseas.drawing.views.with_hidden`):
    the parts of the lines none of whose instances shows a visible run in any view, so
    each such line's balloon can end on one of its hidden lines, as a drafter's would.
    A view that already draws them, or hidden lines of its own, is kept as it is, and
    so is every view of an assembly with no part hidden, so its drawing is unchanged."""
    if contents is None:
        return ctx
    bodies = frozenset(
        k for line in _unseen(ctx, contents, lines) for i in contents.instances_of(line) for k in i.bodies
    )
    if not bodies:
        return ctx
    from ..views import with_hidden

    views = []
    for spec, geom in ctx.views:
        done = spec.hidden or any(r.style == "hidden" and r.source.body in bodies for r in geom.runs)
        if not done:
            geom = with_hidden(ctx.model, spec, geom, bodies, limits=limits, quality=ctx.options.quality)
        views.append((spec, geom))
    return replace(ctx, views=tuple(views), ids=ctx.ids)


def balloons(ctx: Context, contents: Any, lines: Any = None) -> tuple[Balloon, ...]:
    """Each parts list line's balloon (see the module notes): of ``lines``, the
    assembly's own parts list when None."""
    if contents is None:
        return ()
    lines = contents.bom if lines is None else lines
    frames: dict[str, tuple] = {}
    for spec, geom in ctx.views:
        box = geom.bounds()
        if box is not None:
            frames[spec.id] = (((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), box)
    visible = _runs(ctx, contents, "visible")
    hidden: dict | None = None  # read only when a line shows no visible run

    def anchor(runs: dict, view: str, members: list[str]) -> tuple[str, tuple[float, float]] | None:
        centre, box = frames[view]
        found = []
        for inst in members:
            mine = runs.get((view, inst), [])
            if not mine:
                continue
            longest = max(length for length, _p in mine)
            for length, p in mine:
                if length >= 0.25 * longest:
                    found.append((_exit(p, centre, box), -length, members.index(inst), inst, p))
        if not found:
            return None
        _e, _l, _k, inst, p = min(found, key=lambda f: f[:3])
        return inst, p

    out = []
    order = [v for v in view_order(ctx) if v in frames]
    for line in lines:
        members = [i.id for i in contents.instances_of(line)]
        placed = [(v, got) for v in order if (got := anchor(visible, v, members)) is not None]
        if not placed and members:
            # hidden behind other parts in every view: its leader ends on a hidden line
            hidden = _runs(ctx, contents, "hidden") if hidden is None else hidden
            placed = [(v, got) for v in order if (got := anchor(hidden, v, members)) is not None]
        if placed:
            (view, (inst, p)), rest = placed[0], placed[1:]
            others = tuple((v, i, (float(q[0]), float(q[1]))) for v, (i, q) in rest)
            out.append(Balloon(line.item, view, inst, (float(p[0]), float(p[1])), others))
    return tuple(out)


def drawing_number(line: Any, settings: Any) -> str:
    """The number of a parts list item's own drawing, as SolidSeas would give it a
    drawing of its own (:func:`.notes.title_fields`): its property among the
    Settings' drawing number names, else its file name without the extension; empty
    for an item with no file of its own (a virtual or embedded component, which is
    drawn from its own file only once saved as one)."""
    if not line.own_file:
        return ""
    folded = {k.casefold(): v for k, v in line.properties}
    for name in settings.title_sources.number:
        value = folded.get(name.casefold())
        if value is not None and value.strip():
            return value.strip()
    return os.path.splitext(line.file)[0] if line.file else line.part_number


def edited_lines(
    ctx: Context, contents: Any, detail: PlanDetail
) -> tuple[tuple, tuple[str, ...], tuple[int, ...]]:
    """The parts list's lines, headings and narrow columns from the drawing's
    ``parts_list`` (see the module notes)."""
    from ...bomtable import NUMERIC, apply
    from ..assembly import _line_of
    from ..types import parts_list_spec

    table_spec = parts_list_spec(ctx.options.parts_list)
    bom = contents.bom_of(table_spec.type)
    if bom is None:
        detail.warnings.append(
            "the parts list set in the BOM editor could not be built; the default is drawn"
        )
        return (
            tuple(replace(line, drawing=drawing_number(line, ctx.settings)) for line in contents.bom),
            (),
            (),
        )
    shown = apply(table_spec, bom)
    ids = [c.id for c in shown.columns]
    out = []
    for row in shown.rows:
        base = _line_of(row.row.source)
        number = drawing_number(base, ctx.settings)
        cells = list(row.cells)
        if "drawing" in ids and not row.overridden[ids.index("drawing")]:
            cells[ids.index("drawing")] = number
        text = dict(zip(ids, cells, strict=True))
        quantity = text.get("quantity", str(base.quantity))
        out.append(
            replace(
                base,
                item=row.item,
                part_number=text.get("part_number", base.part_number).strip(),
                description=text.get("description", base.description),
                quantity=int(quantity) if quantity.isdigit() else base.quantity,
                drawing=number,
                cells=tuple(cells),
            )
        )
    for key, column in shown.unused:
        detail.warnings.append(
            f"a parts list edit no longer applies: {column} of {key.rsplit('/', 1)[-1].split('|')[0]}"
        )
    narrow = tuple(k for k, c in enumerate(shown.columns) if c.id == "item" or c.id in NUMERIC)
    return tuple(out), tuple(shown.headings()), narrow


NOT_SHOWN = re.compile(r"ITEMS? (.+) NOT SHOWN")


def not_shown_note(items: list[str]) -> str:
    """The note that lists the parts list's items no view shows: ``ITEMS 3, 7 NOT SHOWN``."""
    return f"ITEM{'S' if len(items) > 1 else ''} {', '.join(items)} NOT SHOWN"


def not_shown_items(text: str) -> set[str]:
    """The items a :func:`not_shown_note` names, or none for any other note."""
    m = NOT_SHOWN.fullmatch(text.strip())
    return {i.strip() for i in m.group(1).split(",")} if m else set()


def overall_size(
    ctx: Context, detail: PlanDetail
) -> tuple[tuple[PlannedDimension, ...], tuple[NoteLine, ...]]:
    """The assembly's overall length, width and height along the frame's axes, each a
    reference dimension (in parentheses: it states the size, it does not set it) in a
    view that shows both ends of it as lines, the main view first. When an end is on a
    curved face (no straight line ends there in any view), the whole size is stated
    in a note instead, ``OVERALL SIZE (REF): L x W x H``."""
    points = ctx.model.points
    if not points:
        return (), ()
    views = [s.id for s, _g in ctx.views]
    assigner = Assigner(ctx, views)
    ids = _Ids()
    made = []
    sizes = []
    missing = False
    for k, axis in enumerate(AXES):
        along = [ctx.along(axis, p) for p in points]
        lo, hi = min(along), max(along)
        sizes.append(hi - lo)
        if hi - lo <= ctx.tol:
            continue
        a = Pos(2 * k, axis, lo, "face")
        b = Pos(2 * k + 1, axis, hi, "face")
        hit = assigner.linear(a, b, ())
        if hit is None:
            missing = True
            continue
        view, sheet_axis = hit
        assigner.take(view, ())
        did = ids.next()
        detail.positions[did] = (a, b)
        detail.sheet_axis[did] = sheet_axis
        made.append(
            PlannedDimension(
                f"overall/{axis}",
                did,
                "linear",
                view,
                hi - lo,
                axis=axis,
                positions=(_position(a), _position(b)),
                places=values.places(ctx, "envelope"),
                tolerance="reference",
                role="envelope",
                serves=(f"overall/{axis}",),
            )
        )
    if not missing:
        return tuple(made), ()
    # a note states the size whole, so the dimensions that could be drawn are left out
    for d in made:
        detail.positions.pop(d.id, None)
        detail.sheet_axis.pop(d.id, None)
    text = " X ".join(values.length_text(ctx, v, "envelope") for v in sizes)
    return (), (NoteLine(f"OVERALL SIZE (REF): {text}"),)


def make_plan(
    ctx: Context,
    source: Any = None,
    fields: dict[str, str] | None = None,
    *,
    limits: DrawingLimits = DEFAULT_LIMITS,
) -> Planned:
    """The plan of an assembly drawing (see the module notes)."""
    t0 = time.perf_counter()
    fields = dict(fields or {})
    contents = getattr(source, "assembly", None)
    req = Requirements()
    req.index()
    detail = PlanDetail(ctx, req, {})
    title = notes.title_fields(ctx, source, fields)
    detail.title = title
    lines = (
        tuple(replace(line, drawing=drawing_number(line, ctx.settings)) for line in contents.bom)
        if contents
        else ()
    )
    columns: tuple[str, ...] = ()
    narrow: tuple[int, ...] = ()
    if contents is not None and ctx.options.parts_list is not None:
        lines, columns, narrow = edited_lines(ctx, contents, detail)
    ctx = show_hidden(ctx, contents, lines, limits)
    detail.ctx = ctx
    made = balloons(ctx, contents, lines)
    ballooned = {b.item for b in made}
    not_shown: list[str] = []
    for line in lines:
        if line.item in ballooned:
            continue
        if contents is not None and not contents.instances_of(line):
            # not drawn in any view (hidden in the assembly, its file not found, no solid
            # bodies): said in a note, as a parts list's item not shown is
            not_shown.append(line.item)
            detail.warnings.append(
                f"item {line.item} ({line.part_number}) is not drawn in any view, so it has no "
                "balloon; a note says it is not shown"
            )
        else:
            detail.warnings.append(
                f"item {line.item} ({line.part_number}) shows no edge, visible or hidden, in any "
                "view, so it has no balloon"
            )
    sizes, size_notes = overall_size(ctx, detail)
    if not_shown:
        size_notes = (*size_notes, NoteLine(not_shown_note(not_shown)))
    detail.seconds = time.perf_counter() - t0
    plan = Plan(
        views=tuple(s for s, _g in ctx.views),
        dimensions=sizes,
        notes=size_notes,
        title=tuple((k, v) for k, (v, _src) in title.items()),
        coverage=ctx.features.coverage,
        bom=lines,
        balloons=made,
        bom_columns=columns,
        bom_narrow=narrow,
    )
    return Planned(plan, detail)


__all__ = [
    "balloons",
    "drawing_number",
    "edited_lines",
    "make_plan",
    "middle",
    "not_shown_items",
    "not_shown_note",
    "overall_size",
    "show_hidden",
    "view_order",
]
