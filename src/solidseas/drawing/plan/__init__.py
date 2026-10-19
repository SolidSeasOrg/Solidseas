"""The planner (``docs/DRAWINGS.md`` 10): from the features and views to the
dimensions, datums, notes and title fields of a :class:`~solidseas.drawing.types.Plan`.

:func:`make_plan` runs the steps in order:

1. :mod:`.requirements`: positions, implied links and needs;
2. :mod:`.graph`: one linear graph a frame axis, contracted by the implied links;
3. :mod:`.select`: the views the drawing keeps (8.3);
4. :mod:`.assign` and :mod:`.callouts`: each need's dimension in its view;
5. :mod:`.graph` and :mod:`.schemes`: the baseline tree of locations, baseline or
   ordinate per view and axis;
6. :mod:`.gdt`: datum feature symbols and frames;
7. the checks: each linear graph and :mod:`.angular` graph complete and not
   redundant, and what no kept view can draw;
8. :mod:`.notes` and :mod:`.values`: notes, title fields, the tolerance block and
   the tolerance bands.

What layout needs beyond the plan (the positions' points, each need, each
dimension's sheet axis) is kept in a :class:`PlanDetail` beside it.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field, replace
from typing import Any

from ..limits import DEFAULT_LIMITS, DrawingLimits
from ..types import (
    Boss,
    Datum,
    GraphResult,
    Hole,
    Pattern,
    Plan,
    PlannedDimension,
    Position,
    requirement_key,
)
from . import angular, callouts, gdt, notes, schemes, select, values
from .assign import Assigner
from .context import AXES, Context, feature_ids
from .graph import Graph, Located, baseline, witness_in
from .requirements import Need, Pos, Requirements, requirements


@dataclass
class PlanDetail:
    """What layout and the editor need beside the plan: the context, requirements and
    graphs; for each dimension id its positions, need and the sheet axis it runs
    along; the location edges; what no view could draw; warnings."""

    ctx: Context
    req: Requirements
    graphs: dict[str, Graph]
    positions: dict[str, tuple[Pos, ...]] = field(default_factory=dict)
    needs: dict[str, Need] = field(default_factory=dict)
    edges: dict[str, tuple[str, int, int]] = field(default_factory=dict)
    sheet_axis: dict[str, str] = field(default_factory=dict)
    # for a datum feature symbol, the other views its face shows as a line in, each with
    # its sheet axis, in the order the layout tries them when its own view has no room
    other_views: dict[str, tuple[tuple[str, str], ...]] = field(default_factory=dict)
    uncovered: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    title: dict[str, tuple[str, str]] = field(default_factory=dict)
    seconds: float = 0.0


@dataclass
class Planned:
    plan: Plan
    detail: PlanDetail


def _position(p: Pos) -> Position:
    return Position(p.value, p.kind != "face", p.radius, p.features)


def _hole_seen(h: Hole):
    d = h.axis.direction
    back = (-d[0], -d[1], -d[2])
    return (back, d) if h.through else (back,)


class _Ids:
    def __init__(self) -> None:
        self.n = 0

    def next(self) -> str:
        self.n += 1
        return f"d-{self.n}"


def make_plan(
    ctx: Context,
    source=None,
    fields: dict[str, str] | None = None,
    *,
    previous: frozenset = frozenset(),
    deep: frozenset[str] = frozenset(),
    limits: DrawingLimits = DEFAULT_LIMITS,
) -> Planned:
    """The plan of a drawing (10). ``previous`` holds the location keys the last plan
    drew (hysteresis); ``deep`` the ``view/axis`` pairs layout found too deep for
    baseline."""
    t0 = time.perf_counter()
    fields = dict(fields or {})
    req = requirements(ctx)
    nodes_total = sum(len(v) for v in req.positions.values())
    if len(req.needs) + nodes_total > limits.requirements:
        raise limits.exceeded("requirements", "the part needs more dimensions than a drawing allows")
    graphs = {
        ax: Graph(ax, req.positions[ax], req.links[ax], req.origins[ax]) for ax in AXES if req.positions[ax]
    }
    express = ctx.options.express
    simplified = ctx.options.detail == "simplified" or express
    # What the drawing locates: every feature, the holes alone on an Express drawing, or
    # nothing on a simplified one
    if express:
        located_graphs = express_graphs(ctx, req)
    else:
        located_graphs = {} if simplified else graphs
    keeps = express_keeps if express else simplified_keeps
    locate = [(ax, g.members[n]) for ax, g in located_graphs.items() for n in g.nodes if n != g.origin]
    if express:
        stated = copy.copy(req)  # the views an Express drawing needs are those of what it states
        stated.needs = [n for n in req.needs if keeps(ctx, n)]
        kept, _left = select.choose_views(ctx, stated, locate)
    else:
        kept, _left = select.choose_views(ctx, req, locate)
    kept_ctx = replace(ctx, views=tuple((s, g) for s, g in ctx.views if s.id in kept), ids=ctx.ids)
    detail = PlanDetail(kept_ctx, req, graphs)
    ids = _Ids()
    dims: list[PlannedDimension] = []
    assigner = Assigner(kept_ctx, kept)

    def fids(ks) -> tuple[str, ...]:
        return tuple(ctx.ids[k] for k in ks)

    # ------------------------------------------------------------------ sizes and statements
    for need in req.needs:
        if simplified and not keeps(ctx, need):
            continue  # a simplified drawing gives the overall size and its holes' and bosses' sizes
        made = _need_dimension(kept_ctx, req, need, assigner, ids, fids(need.features), detail)
        if made is None:
            detail.uncovered.append(need.req.key)
            continue
        dims.append(made)
        if len(dims) >= limits.dimensions:
            detail.warnings.append(
                "the dimension bound was reached; ordinate dimensions would need fewer tracks"
            )
            break

    # ------------------------------------------------------------------ locations
    located: dict[str, list[Located]] = {}
    for ax, g in located_graphs.items():
        found, unreached = baseline(kept_ctx, g, previous)
        located[ax] = found
        for n in unreached:
            detail.uncovered += list(g.keys(n))
    counts: dict[tuple[str, str], int] = {}
    for ax, found in located.items():
        for loc in found:
            counts[(loc.view, ax)] = counts.get((loc.view, ax), 0) + 1
    for ax, found in located.items():
        g = located_graphs[ax]
        for loc in found:
            a, b = g.pos[loc.a], g.pos[loc.b]
            kind = (
                "ordinate"
                if schemes.arrangement(kept_ctx, loc.view, ax, counts[(loc.view, ax)], deep) == "ordinate"
                else "linear"
            )
            datum = kept_ctx.scheme == "datum"
            role = "basic" if datum else ("hole_location" if b.kind != "face" else "step")
            did = ids.next()
            spec = kept_ctx.view(loc.view)[0]
            sa = kept_ctx.sheet_axis(spec, ax)
            dims.append(
                PlannedDimension(
                    loc.keys[0],
                    did,
                    kind,
                    loc.view,
                    abs(b.value - a.value),
                    axis=ax,
                    positions=(_position(a), _position(b)),
                    features=tuple(dict.fromkeys(a.features + b.features)),
                    places=values.places(kept_ctx, role),
                    tolerance="basic" if datum else "block",
                    role="feature_location",
                    serves=loc.keys,
                )
            )
            assigner.take(loc.view, b.features)
            detail.positions[did] = (a, b)
            detail.edges[did] = (ax, loc.a, loc.b)
            detail.sheet_axis[did] = sa[0] if sa else "x"

    # ------------------------------------------------------------------ datums
    reduced = bool(ctx.features.unclaimed) or simplified
    datums: tuple[Datum, ...] = ()
    if gdt.draws_datums(kept_ctx, reduced and not simplified):
        datums = tuple(ctx.features.frame.datums)
        for d in datums:
            made = _datum_dimension(kept_ctx, req, d, assigner, ids, detail)
            if made is not None:
                dims.append(made)
            else:
                detail.warnings.append(f"datum {d.letter} has no view where its face is a visible line")

    # ------------------------------------------------------------------ checks
    results: list[GraphResult] = []
    for ax, g in ({} if simplified else graphs).items():
        edges = [(pa, pb, did) for did, (eax, pa, pb) in detail.edges.items() if eax == ax]
        results.append(g.check(edges))
    results += angular.check(kept_ctx, dims)
    if detail.uncovered:
        results.append(GraphResult("views", False, False, tuple(dict.fromkeys(detail.uncovered)), ()))

    # ------------------------------------------------------------------ notes and title
    title = notes.title_fields(kept_ctx, source, fields)
    if express and "finish" not in title:
        none = none_finish(kept_ctx)
        if none:  # an Express drawing asks nothing: a part that names no finish has none
            title["finish"] = (none, "list")
    detail.title = title
    note_lines = notes.notes(kept_ctx, title, fields, fillet=req.fillet_radius, reduced=reduced)
    if express:  # not the shop's general notes: the model-governs and a printed part's process note
        note_lines = tuple(n for n in note_lines if n.text.startswith(notes.EXPRESS_NOTES))
    note_numbers = {"process": 1 + (1 if kept_ctx.scheme == "datum" else 0)}
    block = notes.tolerance_block(kept_ctx, note_numbers)
    detail.seconds = time.perf_counter() - t0
    plan = Plan(
        views=tuple(s for s, _g in kept_ctx.views),
        dimensions=tuple(dims),
        datums=datums,
        notes=note_lines,
        title=tuple((k, v) for k, (v, _src) in title.items()),
        tolerance_block=block,
        graphs=tuple(results),
        coverage=ctx.features.coverage,
        bands=values.bands(kept_ctx, dims),
    )
    return Planned(plan, detail)


def simplified_keeps(ctx: Context, need: Any) -> bool:
    """Whether a simplified drawing gives ``need``: the part's overall size, and the
    sizes of its holes, bosses and hole patterns (a count such as 4X with them)."""
    if need.role == "envelope":
        return True
    found = ctx.features.features
    return (
        any(0 <= k < len(found) and isinstance(found[k], (Hole, Boss, Pattern)) for k in need.features)
        and need.req.kind == "size"
    )


def express_keeps(ctx: Context, need: Any) -> bool:
    """Whether an Express drawing gives ``need``: the part's overall size, the sizes of
    its holes and hole patterns (with their counts), and a pattern's own pitches, pitch
    circle and clocking angle. Bosses, slots, steps, chamfers and fillets are left to
    the model."""
    if need.role == "envelope":
        return True
    found = ctx.features.features
    kinds = [found[k] for k in need.features if 0 <= k < len(found)]
    if not kinds or not all(isinstance(f, (Hole, Pattern)) for f in kinds):
        return False
    if isinstance(kinds[0], Pattern):
        return need.req.kind in ("size", "angle")
    return need.req.kind == "size"


def none_finish(ctx: Context) -> str:
    """The callout of the finish list's entry for no finish (NONE), or "" when the list
    has none."""
    for f in ctx.settings.materials.finishes:
        if " ".join(str(f.get("callout", "")).split()).casefold() == "none":
            return f["callout"]
    return ""


def hole_ids(ctx: Context) -> frozenset[str]:
    """The ids of the part's holes and hole patterns."""
    found = ctx.features.features
    return frozenset(
        ctx.ids[k] for k, f in enumerate(found) if isinstance(f, (Hole, Pattern)) and k < len(ctx.ids)
    )


def express_graphs(ctx: Context, req: Requirements) -> dict[str, Graph]:
    """Each axis's graph of what an Express drawing locates: the origin (the datum edge
    the locations run from) and the centres of the holes, joined by the links the
    patterns imply, so a pattern is located once, by its first member or its centre,
    and its pitches give the rest."""
    holes = hole_ids(ctx)
    out: dict[str, Graph] = {}
    for ax in AXES:
        positions = req.positions.get(ax) or []
        origin = req.origins.get(ax)
        kept = [
            p
            for p in positions
            if p.id == origin or (p.kind == "centre" and p.features and set(p.features) <= holes)
        ]
        if len(kept) < 2 or origin is None or not any(p.id == origin for p in kept):
            continue
        out[ax] = Graph(ax, kept, req.links.get(ax, []), origin)
    return out


def _need_dimension(
    ctx: Context, req: Requirements, need: Need, assigner: Assigner, ids: _Ids, feats, detail: PlanDetail
) -> PlannedDimension | None:
    """The dimension that states one need, in its view, or None when no kept view
    can draw it."""
    r = need.req
    fs = ctx.features
    places = values.places(ctx, need.role)
    tolerance = values.tolerance_for(ctx, r.tolerance_class)
    if need.kind in ("linear", "leader_note") and need.a is not None and need.b is not None:
        a, b = req.position(need.axis, need.a), req.position(need.axis, need.b)
        hit = assigner.linear(a, b, feats)
        if hit is not None:
            view, sheet_axis = hit
            did = ids.next()
            assigner.take(view, feats)
            detail.positions[did] = (a, b)
            detail.needs[did] = need
            detail.sheet_axis[did] = sheet_axis
            prefix = f"{need.count}X " if r.role == "pattern" and need.count > 1 else ""
            return PlannedDimension(
                r.key,
                did,
                "linear",
                view,
                r.value,
                axis=need.axis,
                positions=(_position(a), _position(b)),
                features=feats,
                places=places,
                tolerance=tolerance,
                prefix=prefix,
                frame=gdt.position(ctx) if r.tolerance_class == "frame" else None,
                role=r.role,
                serves=(r.key,),
            )
        if "leader_note" not in r.satisfied_by:
            return None
        # a depth or width no view shows between visible lines: a note on its plan view
        view = assigner.facing(need, feats)
        if view is None:
            return None
        did = ids.next()
        assigner.take(view, feats)
        detail.positions[did] = (a, b)
        detail.needs[did] = need
        word = callouts.DEPTH if r.key.startswith("depth/") else ""
        text = values.length_text(ctx, r.value, need.role)
        line = callouts.words(ctx, f"{word} {text}".strip()) if word else f"{text} WIDE"
        if need.count > 1:  # equal depths from one face, stated once (requirements)
            line = values.count_prefix(need.count) + line
        return PlannedDimension(
            r.key,
            did,
            "leader_note",
            view,
            r.value,
            axis=need.axis,
            positions=(_position(a), _position(b)),
            anchor=need.anchor,
            radius=need.radius,
            features=feats,
            places=places,
            suffix=(line,),
            role=r.role,
            serves=(r.key,),
        )
    if need.kind == "leader_note":
        view = assigner.facing(need, feats)
        if view is None:
            return None
        did = ids.next()
        assigner.take(view, feats)
        detail.needs[did] = need
        text = values.length_text(ctx, r.value, need.role)
        return PlannedDimension(
            r.key,
            did,
            "leader_note",
            view,
            r.value,
            anchor=need.anchor,
            radius=need.radius,
            features=feats,
            places=places,
            suffix=(f"{text} WIDE",),
            frame=gdt.position(ctx) if r.tolerance_class == "frame" else None,
            role=r.role,
            serves=(r.key,),
        )
    if need.kind == "hole_callout":
        k = need.features[0]
        f = fs.features[k]
        hole = fs.features[f.members[0]] if isinstance(f, Pattern) else f
        view = assigner.facing(need, feats, _hole_seen(hole)) or assigner.side(need, feats)
        if view is None:
            return None
        prefix, value, suffix = callouts.hole(ctx, hole, need.count, ctx.ids[k])
        tapped = bool(ctx.decisions.get(ctx.ids[k], {}).get("thread"))
        did = ids.next()
        assigner.take(view, feats)
        detail.needs[did] = need
        return PlannedDimension(
            r.key,
            did,
            "hole_callout",
            view,
            value,
            anchor=need.anchor,
            radius=need.radius,
            features=feats,
            places=places,
            tolerance="block",
            prefix=prefix,
            suffix=suffix,
            frame=gdt.position(ctx, tapped=tapped),
            role=r.role,
            serves=(r.key,),
        )
    if need.kind in ("diameter", "radius", "angle", "chamfer"):
        seen = ()
        k0 = need.features[0] if need.features else None
        f0 = fs.features[k0] if k0 is not None else None
        if isinstance(f0, Pattern):
            first = fs.features[f0.members[0]]
            if isinstance(first, Hole):
                seen = _hole_seen(first)
        view = assigner.facing(need, feats, seen)
        if view is None and need.kind == "diameter":
            view = assigner.side(need, feats)
        if view is None:
            return None
        did = ids.next()
        assigner.take(view, feats)
        detail.needs[did] = need
        count = values.count_prefix(need.count)
        suffix: tuple[str, ...] = ()
        value = r.value
        if need.kind == "diameter":
            prefix = count + values.DIAMETER
        elif need.kind == "radius":
            prefix = count + "R"
            if need.derived:
                tolerance = "derived"
        elif need.kind == "chamfer":
            c0 = fs.features[need.features[0]]
            prefix, value, suffix = callouts.chamfer(ctx, c0.legs, c0.angle, need.count)
        else:
            prefix = count
        return PlannedDimension(
            r.key,
            did,
            need.kind,
            view,
            value,
            axis=need.axis,  # a pattern's first angle: the frame axis it is measured from
            anchor=need.anchor,
            radius=need.radius,
            features=feats,
            places=places,
            tolerance=tolerance,
            prefix=prefix,
            suffix=suffix,
            frame=gdt.position(ctx) if r.tolerance_class == "frame" else None,
            role=r.role,
            serves=(r.key,),
        )
    return None


def _datum_dimension(
    ctx: Context, req: Requirements, d: Datum, assigner: Assigner, ids: _Ids, detail: PlanDetail
) -> PlannedDimension | None:
    """A datum feature symbol, in a view where its face is a visible line: the front
    first, then the least crowded. The other such views, in the same order, go in
    ``detail.other_views`` for a layout that finds no clear place in the first."""
    ax = ctx.plane_axis(d.face)
    if ax is None:
        return None
    hit = next((p for p in req.positions.get(ax, []) if d.face in p.faces), None)
    if hit is None:
        return None
    shown = []
    for v in assigner.views:
        spec, geom = ctx.view(v)
        w = witness_in(ctx, spec, geom, hit)
        if w is None:
            continue
        key = (0 if spec.kind == "base" else 1, assigner.count[v], assigner.views.index(v))
        shown.append((key, v, w.sheet_axis))
    if not shown:
        return None
    shown.sort()
    _key, view, sheet_axis = shown[0]
    did = ids.next()
    detail.positions[did] = (hit,)
    detail.sheet_axis[did] = sheet_axis
    if len(shown) > 1:
        detail.other_views[did] = tuple((v, sa) for _k, v, sa in shown[1:])
    from .requirements import _face_point

    return PlannedDimension(
        requirement_key("datum", [d.letter.lower()]),
        did,
        "datum_feature",
        view,
        hit.value,
        axis=ax,
        positions=(_position(hit),),
        anchor=_face_point(ctx, d.face),
        features=hit.features,
        suffix=(d.letter,),
        role="form",
        serves=(requirement_key("datum", [d.letter.lower()]),),
    )


__all__ = ["Context", "PlanDetail", "Planned", "feature_ids", "make_plan"]
