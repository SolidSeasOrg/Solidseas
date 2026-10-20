"""Editing a drawing (``docs/DRAWINGS.md`` 10.12, 13.2, 13.5, 15.4).

Every operation takes a :class:`~.types.Drawing` and returns ``(drawing, checks)``: a
new drawing and the checks of 20.1 on it. The drawing given is never changed, so
the viewer's undo keeps the drawings it had. An operation changes the drawing's
records (its dimensions, its features' decisions, datums, notes, title, options or
settings snapshot), lays the sheet out again from the model with those records
applied, clears the signatures the change invalidated (13.2) and runs the checks.
A RELEASED drawing refuses every operation but :func:`start_revision`.

**The model.** Laying a sheet out again needs the model: a drawing opened without
it is view-only (13.6; the geometry cache that would edit without it is stage 4).
The run that made or regenerated a drawing in this process is kept beside it
(:func:`adopt`, for at most :data:`MAX_LIVE` drawings, the most recently used
kept); :func:`attach` opens the model of a drawing read from a file and refuses one
whose file hash and geometry digest both differ from the drawing's (Update from
Model takes a changed model). Without either, an operation raises
``InvalidArgumentError`` with rule ``model_not_found``.

**Records applied** (:func:`relayout`). The plan is made with the drawing's feature
ids, decisions, datums and frozen options, and each planned dimension takes the
record with its key: its id, state, placement, side and text override, and the
user's precision, tolerance, frame, prefix and suffix where the user set them. A
removed dimension stays in the list and off the sheet; a user dimension is found
again from its features, and is kept but marked ``needs_attention`` (off the
sheet) when they no longer give it; a generated dimension whose requirement went
away (a location an edit replaced with a link) is dropped; a requirement that is
new gets the next id. Notes and title fields are the drawing's own. The linear and
angular graphs are checked again with the dimensions shown, so a removed location
is reported as missing and a user dimension that closes a loop as redundant. When
nothing the plan reads changed, the last plan is laid out again without planning.

**Decisions** a feature carries (13.1 ``features[].decisions``): ``datum`` (its
letter), ``thread`` and ``thread_depth`` (a confirmed thread), ``into_bore_note``
(a confirmed end in a cross bore), ``depth_from`` (``open`` or ``floor``),
``origin_x``, ``origin_y`` and ``origin_z`` (``centre`` or a face index: the axis is
measured from it), and ``link_x``, ``link_y`` and ``link_z`` (the feature it is
located from instead of the origin).

What stage 1 leaves out, each raising ``not_implemented`` with rule
``later_release``: sections and detail views added on request (3.3 lists on-request
detail views first among what slips to stage 2), and flag notes.
"""

from __future__ import annotations

import datetime
import math
import re
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from ..errors import InvalidArgumentError, ModelNotFoundError, UnsupportedOperationError
from . import assembly, document, release, types
from . import settings as settings_mod
from .document import DimensionRecord, NoteRecord, Placement
from .limits import DEFAULT_LIMITS, DrawingLimits
from .types import Datum, FeatureRecord, FrameCell, Position

MAX_LIVE = 8  # drawings whose model this process keeps for editing
SHOWN, REMOVED = "shown", "removed"
USER_TEXT = "user_text"  # a record flag: the prefix and suffix are the user's
USER_KEY = "user"  # the first part of a user dimension's key
TOLERANCE_KINDS = ("block", "basic", "reference", "symmetric", "deviations", "limits", "max", "min")
SIDES = ("below", "above", "left", "right")
MAX_PREFIX = 32
MAX_SUFFIX_LINES = 8
MAX_OVERRIDE = 64
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_LETTER = re.compile(r"[A-HJ-NPR-WYZ]")  # datum letters: not I, O, Q or X (Y14.5)
_THREAD = re.compile(r"[0-9A-Za-z#./ -]{1,64}")
_LAYOUT_ONLY = ("sheet", "scale")


# --------------------------------------------------------------------------- the model kept beside a drawing


@dataclass
class Live:
    """What laying a drawing out again needs, kept beside it in this process: the
    run's source, model, features and views, and the last plan made for it with the
    choices it was made from (``key``)."""

    source: Any
    model: Any
    features: Any
    views: tuple
    view_key: Any = None
    planned: Any = None
    key: Any = None


_LIVE: OrderedDict[str, Live] = OrderedDict()


def _keep(drawing_id: str, live: Live) -> None:
    _LIVE[drawing_id] = live
    _LIVE.move_to_end(drawing_id)
    while len(_LIVE) > MAX_LIVE:
        _LIVE.popitem(last=False)


def live_for(drawing: types.Drawing) -> Live | None:
    """The run kept beside ``drawing`` in this process, if any: one of the drawing's
    model, by its file hash or, for a file saved again with its geometry unchanged
    (which :func:`attach` takes), its geometry digest."""
    live = _LIVE.get(getattr(drawing, "id", None))
    if live is None:
        return None
    model = drawing.model or {}
    sha, shape = model.get("sha256"), model.get("geometry")
    have = getattr(live.source, "sha256", None)
    same_shape = bool(shape) and getattr(live.source, "geometry_digest", None) == shape
    if sha and have not in (None, sha) and not same_shape:
        return None  # kept for another model of the same drawing
    if assembly.is_assembly(model) and shape and not same_shape:
        return None  # an assembly whose parts changed under the same file
    _LIVE.move_to_end(drawing.id)
    return live


def forget(drawing: types.Drawing) -> None:
    """Drop the run kept beside ``drawing`` (the viewer calls this on closing it)."""
    _LIVE.pop(getattr(drawing, "id", None), None)


def move_live(made: types.Drawing, merged: types.Drawing) -> None:
    """Keep the run that made ``made`` (a regeneration's new run) beside ``merged``
    (the drawing it was merged into) instead."""
    live = _LIVE.pop(getattr(made, "id", None), None)
    if live is not None:
        live.planned = live.key = None
        _keep(merged.id, live)


def _view_key(options: types.DrawingOptions) -> tuple:
    return (options.views, options.front, options.turn, options.hidden, options.tangent, options.quality)


def _run_checks(drawing: types.Drawing, planned: Any, result: Any, *, at_release: bool = False) -> tuple:
    from .pipeline import ENTRY_POINTS, resolve

    try:
        run_checks = resolve("checks", ENTRY_POINTS["checks"])
    except UnsupportedOperationError:
        return tuple(getattr(result, "checks", ()) or ())
    return tuple(run_checks(drawing, planned=planned, layout=result, release=at_release))


def adopt(
    drawing: types.Drawing,
    source: Any,
    model: Any,
    features: Any,
    done: Any,
    fields: Any = None,
    *,
    limits: DrawingLimits = DEFAULT_LIMITS,
) -> types.Drawing:
    """``drawing`` laid out from its records, with its checks, and the run that made it
    (``done``, an ``orchestrate.Orchestrated``) kept beside it for editing. The
    pipeline calls this after its assemble stage: the plan stage lays the sheet out
    before the drawing's records exist, so the revision row and DRAWN's date are filled
    here, from the same plan, within the run's ``limits``."""
    live = Live(source, model, features, tuple(done.views), _view_key(drawing.options))
    live.planned, live.key = done.raw or done.planned, _plan_key(drawing)
    _keep(drawing.id, live)
    return relayout(drawing, limits=limits)[0]


def attach(
    drawing: types.Drawing,
    part: Any = None,
    *,
    drawing_path: Any = None,
    catalog: Any = None,
    limits: DrawingLimits = DEFAULT_LIMITS,
) -> Live:
    """Open the model of ``drawing`` (a drawing read from a file) for editing: ``part``
    (a path, an open SOLIDWORKS document or a ``DrawingSource``), else the model
    found from ``drawing_path`` as 13.6 says. A model whose file hash and geometry
    digest both differ from the drawing's is refused with rule ``model_changed``:
    Update from Model takes it."""
    from . import locate, pipeline
    from .source import DrawingSource, open_source

    _check(drawing)
    if part is None:
        if drawing_path is None:
            raise ModelNotFoundError(
                "name the model, or the drawing's path to look for it from",
                detail={"parameter": "part", "rule": "model_not_found"},
            )
        found = locate.find_model(drawing_path, drawing.model or {}, catalog=catalog)
        if found.found is None:
            raise ModelNotFoundError(
                "the drawing's model was not found", detail={"parameter": "part", "rule": "model_not_found"}
            )
        part = found.found.path
    settings = _settings(drawing)
    model = drawing.model or {}
    if isinstance(part, DrawingSource):
        src = part
    else:
        units = drawing.options.units if drawing.options.units in ("in", "mm") else None
        names = tuple(
            n
            for group in (
                "part_number",
                "number",
                "title",
                "revision",
                "model_revision",
                "material",
                "finish",
            )
            for n in getattr(settings.title_sources, group)
        )
        src = open_source(
            part, configuration=model.get("configuration"), units=units, title_names=names, limits=limits
        )
    same_file = assembly.same_file(model, src)
    same_shape = bool(model.get("geometry")) and src.geometry_digest == model.get("geometry")
    if not (same_file or same_shape):
        raise InvalidArgumentError(
            "the model has changed since the drawing was made: Update from Model takes it",
            detail={"parameter": "part", "rule": "model_changed"},
        )
    run = pipeline.run(
        None,
        options=drawing.options,
        settings=settings,
        limits=limits,
        stages={"source": lambda *_a, **_k: src},
        until="views",
    )
    live = Live(src, run.model, run.features, tuple(run.views), _view_key(drawing.options))
    _keep(drawing.id, live)
    return live


def _need(drawing: types.Drawing) -> Live:
    live = live_for(drawing)
    if live is None:
        raise ModelNotFoundError(
            "the drawing's model is not open: a drawing without its model is view-only (open its model, "
            "or, when it has changed, use Update from Model, which also starts a released drawing's "
            "next revision)",
            detail={"parameter": "drawing", "rule": "model_not_found"},
        )
    return live


# --------------------------------------------------------------------------- laying out again


def _check(drawing: Any) -> None:
    if not isinstance(drawing, types.Drawing):
        raise InvalidArgumentError("drawing must be a Drawing", detail={"parameter": "drawing"})


def _settings(drawing: types.Drawing) -> settings_mod.DrawingSettings:
    s = drawing.settings
    return s if isinstance(s, settings_mod.DrawingSettings) else settings_mod.DrawingSettings()


def _features_for(drawing: types.Drawing, fs: types.FeatureSet) -> types.FeatureSet:
    """The run's feature set with the drawing's datums (letters the user moved, and
    none whose feature is gone)."""
    datums = tuple(d for d in drawing.datums if d.face >= 0)
    if not drawing.datums or datums == tuple(fs.frame.datums):
        return fs
    return replace(fs, frame=replace(fs.frame, datums=datums))


def _decisions(drawing: types.Drawing) -> dict[str, dict[str, Any]]:
    return {f.id: dict(f.decisions) for f in drawing.features if f.decisions}


def _named(drawing: types.Drawing) -> frozenset[str]:
    """The features the drawing's own dimensions name: one the user added, moved,
    overrode or removed. A plan of the key dimensions keeps them (10.10), so a re-plan
    never leaves them to the model under the user's hand."""
    out: set[str] = set()
    for r in drawing.dimensions:
        if r.origin == "user" or r.placement is not None or r.override is not None or r.state == REMOVED:
            out.update(r.features)
    return frozenset(out)


def _plan_key(drawing: types.Drawing) -> tuple:
    """What the plan reads from a drawing: an edit that changes none of it is laid out
    again without planning."""
    options = replace(drawing.options, sheet="auto", scale="auto")
    return (
        options,
        drawing.settings,
        tuple((f.id, f.decisions) for f in drawing.features),
        tuple(drawing.datums),
    )


def _title(drawing: types.Drawing) -> dict[str, str]:
    out = {k: f.text for k, f in drawing.title}
    rev = release.current_revision(drawing)
    if rev:
        out["revision"] = rev
    return out


def _signed(drawing: types.Drawing) -> dict[str, tuple[str, str]]:
    return {s.row: (s.name, s.date) for s in drawing.signatures}


def _overlay(rec: DimensionRecord, pd: types.PlannedDimension, offered=()) -> DimensionRecord:
    """A generated record laid over a new plan's dimension of its key: the plan's
    geometry and value, the user's choices kept. ``offered`` are the other views the
    plan offers a datum symbol, which the record may name when the layout drew it in
    one: the same symbol, not a move to another view."""
    flags = rec.flags
    kw: dict[str, Any] = {
        "kind": pd.kind,
        "view": pd.view,
        "value": pd.value,
        "axis": pd.axis,
        "positions": pd.positions,
        "anchor": pd.anchor,
        "radius": pd.radius,
        "features": pd.features,
        "role": pd.role,
        "serves": pd.serves,
    }
    if rec.places_source != "user":
        kw["places"] = pd.places
    if "user_tolerance" not in flags:
        kw["tolerance"] = pd.tolerance
        kw["tolerance_values"] = pd.tolerance_values
    if "user_frame" not in flags:
        kw["frame"] = pd.frame
    if USER_TEXT not in flags:
        kw["prefix"] = pd.prefix
        kw["suffix"] = pd.suffix
    moved_view = rec.view != pd.view and rec.view not in offered
    if moved_view and (rec.placement is not None and rec.placement.moved or rec.side):
        kw["placement"] = None
        kw["side"] = None
        flags = tuple(dict.fromkeys((*flags, "placement_reset")))
    return replace(rec, **kw, flags=flags)


def _pos_for(detail: Any, axis: str, fid: str):
    """The planner's position standing for feature ``fid`` along ``axis``."""
    from .plan.graph import node_of_feature

    g = detail.graphs.get(axis)
    if g is None:
        return None
    node = node_of_feature(g, fid)
    if node is None:
        return None
    centres = [pid for pid in g.members[node] if fid in g.pos[pid].features and g.pos[pid].kind == "centre"]
    own = centres or [pid for pid in g.members[node] if fid in g.pos[pid].features] or g.members[node]
    return g.pos[own[0]]


def _distance(detail: Any, fa: str, fb: str, axis: str, prefer: str | None = None):
    """(pos a, pos b, view, sheet axis) of a distance between two features along
    ``axis`` that one view shows, preferring view ``prefer``."""
    from .plan.graph import witnesses

    ctx = detail.ctx
    pa, pb = _pos_for(detail, axis, fa), _pos_for(detail, axis, fb)
    if pa is None or pb is None or abs(pa.value - pb.value) <= ctx.tol:
        return None
    wa = {(w.view, w.sheet_axis): w for w in witnesses(ctx, pa)}
    shared = [
        (wb.cost + wa[(wb.view, wb.sheet_axis)].cost, wb.view, wb.sheet_axis) for wb in witnesses(ctx, pb)
    ]
    shared = [s for s in shared if (s[1], s[2]) in wa]
    if not shared:
        return None
    shared.sort(key=lambda s: (s[1] != prefer, s))
    _cost, view, sa = shared[0]
    return pa, pb, view, sa


def _position(p) -> Position:
    return Position(p.value, p.kind != "face", p.radius, p.features)


def _user_key(axis: str, fa: str, fb: str) -> str:
    return "/".join((USER_KEY, "distance", fa, fb, axis))


def _user_again(rec: DimensionRecord, detail: Any):
    """A user dimension found again in a new plan: (record, positions, sheet axis), or
    None when its features no longer give it."""
    parts = rec.key.split("/")
    if len(parts) != 5 or parts[:2] != [USER_KEY, "distance"]:
        return None
    _u, _k, fa, fb, axis = parts
    got = _distance(detail, fa, fb, axis, rec.view)
    if got is None:
        return None
    pa, pb, view, sa = got
    out = replace(
        rec,
        view=view,
        value=abs(pb.value - pa.value),
        axis=axis,
        positions=(_position(pa), _position(pb)),
        features=tuple(dict.fromkeys(pa.features + pb.features)),
        flags=tuple(f for f in rec.flags if f != "needs_attention"),
    )
    return out, (pa, pb), sa


def _apply(drawing: types.Drawing, planned: Any) -> tuple[Any, list[DimensionRecord]]:
    """The plan laid out for ``drawing``: its dimensions taking the drawing's records
    (see the module notes), the detail re-keyed to the records' ids, the graphs checked
    again with what is shown, and the drawing's notes and title fields. Returns the
    plan and the records in the drawing's order (new ones after)."""
    from .plan import Planned, angular

    plan, detail = planned.plan, planned.detail
    by_key: dict[str, DimensionRecord] = {}
    for r in drawing.dimensions:
        if r.origin == "generated":
            by_key.setdefault(r.key, document.as_record(r))
    next_d = document.next_number(drawing, "d")
    rename: dict[str, str] = {}
    made: dict[str, DimensionRecord] = {}
    fresh: list[str] = []
    for pd in plan.dimensions:
        rec = by_key.pop(pd.key, None)
        if rec is not None:
            new = _overlay(rec, pd, tuple(v for v, _sa in detail.other_views.get(pd.id, ())))
        else:
            new = replace(document.as_record(pd), id=f"d-{next_d}")
            next_d += 1
            fresh.append(new.id)
        rename[pd.id] = new.id
        made[new.id] = new

    def rekey(d: Mapping[str, Any]) -> dict[str, Any]:
        return {rename[k]: v for k, v in d.items() if k in rename}

    positions, needs = rekey(detail.positions), rekey(detail.needs)
    edges, sheet_axis = rekey(detail.edges), rekey(detail.sheet_axis)
    for r in drawing.dimensions:
        if r.origin != "user":
            continue
        rec = document.as_record(r)
        got = _user_again(rec, detail)
        if got is None:
            made[rec.id] = replace(rec, flags=tuple(dict.fromkeys((*rec.flags, "needs_attention"))))
            continue
        new, (pa, pb), sa = got
        made[new.id] = new
        positions[new.id] = (pa, pb)
        sheet_axis[new.id] = sa
        edges[new.id] = (new.axis, pa.id, pb.id)
    order = [r.id for r in drawing.dimensions if r.id in made] + fresh
    records = [made[i] for i in order]

    shown = [r for r in records if r.state == SHOWN and "needs_attention" not in r.flags]
    shown_ids = {r.id for r in shown}
    graphs = []
    for ax, g in detail.graphs.items():
        graphs.append(
            g.check([(pa, pb, did) for did, (eax, pa, pb) in edges.items() if eax == ax and did in shown_ids])
        )
    graphs += angular.check(detail.ctx, shown)
    graphs += [g for g in plan.graphs if g.graph == "views"]
    title = dict(plan.title)
    title.update(_title(drawing))
    notes = tuple(types.NoteLine(n.text, n.frames) for _id, n in drawing.notes)
    new_plan = replace(
        plan,
        dimensions=tuple(records),
        graphs=tuple(graphs),
        notes=notes,
        title=tuple(title.items()),
    )
    new_detail = replace(
        detail,
        positions=positions,
        needs=needs,
        edges=edges,
        sheet_axis=sheet_axis,
        other_views=rekey(detail.other_views),
    )
    return Planned(new_plan, new_detail), records


def relayout(
    drawing: types.Drawing, *, limits: DrawingLimits = DEFAULT_LIMITS
) -> tuple[types.Drawing, tuple]:
    """``drawing`` laid out again from its model with its records applied (see the
    module notes), its invalidated signatures cleared, and its checks. Every operation
    ends here; the viewer calls it after Use Current Drawing Settings."""
    from . import orchestrate
    from .pipeline import STAGES, resolve

    _check(drawing)
    live = _need(drawing)
    settings = _settings(drawing)
    if live.view_key != _view_key(drawing.options):
        make_views = resolve("views", dict(STAGES)["views"])
        live.views = tuple(make_views(live.model, live.features, drawing.options, settings, limits=limits))
        live.view_key = _view_key(drawing.options)
        live.planned = live.key = None
    fs = _features_for(drawing, live.features)
    ids = tuple(f.id for f in drawing.features)
    if len(ids) != len(fs.features):
        raise InvalidArgumentError(
            "the drawing's feature table does not match its model: Update from Model",
            detail={"parameter": "drawing", "rule": "model_changed"},
        )
    key = _plan_key(drawing)
    state: dict[str, Any] = {}

    def adjust(made: Any) -> Any:
        laid, records = _apply(drawing, made)
        state["records"] = records
        return laid

    done = orchestrate.run(
        live.source,
        live.model,
        fs,
        live.views,
        drawing.options,
        settings,
        _title(drawing),
        limits,
        ids=ids,
        decisions=_decisions(drawing),
        named=_named(drawing),
        planned=live.planned if live.key == key else None,
        adjust=adjust,
        revisions=drawing.revisions,
        status=drawing.status,
        signed=_signed(drawing),
    )
    live.planned, live.key = done.raw, key
    # a datum symbol drawn in another view than planned is recorded in the view it is in
    moved = done.result.views
    records = [replace(r, view=moved[r.id][0]) if r.id in moved else r for r in state["records"]]
    used = max([document.id_number(r.id, "d") or 0 for r in records], default=0)
    next_id = dict(drawing.next_id)
    next_id["d"] = max(next_id.get("d", 1), used + 1)
    out = replace(
        drawing,
        dimensions=tuple(records),
        sheet=done.result.sheet,
        next_id=tuple(next_id.items()),
        coverage=done.planned.plan.coverage,
    )
    if out.status != release.RELEASED:
        out, _cleared = release.invalidate(out)
    checks = _run_checks(out, done.planned, done.result)
    out = replace(out, checks=checks)
    return out, checks


def checks(drawing: types.Drawing, *, at_release: bool = False) -> tuple:
    """The checks of 20.1 on ``drawing`` as it is, from its model when it is open, else
    those the file can answer; ``at_release`` asks for the release-time levels."""
    _check(drawing)
    if live_for(drawing) is None:
        return _run_checks(drawing, None, None, at_release=at_release)
    from . import orchestrate

    live = _need(drawing)

    def adjust(made: Any) -> Any:
        laid, _records = _apply(drawing, made)
        return laid

    key = _plan_key(drawing)
    done = orchestrate.run(
        live.source,
        live.model,
        _features_for(drawing, live.features),
        live.views,
        drawing.options,
        _settings(drawing),
        _title(drawing),
        ids=tuple(f.id for f in drawing.features),
        decisions=_decisions(drawing),
        named=_named(drawing),
        planned=live.planned if live.key == key else None,
        adjust=adjust,
        revisions=drawing.revisions,
        status=drawing.status,
        signed=_signed(drawing),
    )
    return _run_checks(drawing, done.planned, done.result, at_release=at_release)


# --------------------------------------------------------------------------- finding things


def _editable(drawing: types.Drawing, what: str = "it cannot be changed") -> None:
    _check(drawing)
    release.require_editable(drawing, what)


def _record(drawing: types.Drawing, ident: Any) -> DimensionRecord:
    if not isinstance(ident, str):
        raise InvalidArgumentError("a dimension id is text such as d-12", detail={"parameter": "id"})
    for d in drawing.dimensions:
        if d.id == ident:
            return document.as_record(d)
    raise InvalidArgumentError(f"there is no dimension {ident[:64]!r}", detail={"parameter": "id"})


def _with_record(drawing: types.Drawing, rec: DimensionRecord) -> types.Drawing:
    return replace(drawing, dimensions=tuple(rec if d.id == rec.id else d for d in drawing.dimensions))


def _feature(drawing: types.Drawing, fid: Any) -> FeatureRecord:
    if not isinstance(fid, str):
        raise InvalidArgumentError("a feature id is text such as f-3", detail={"parameter": "feature"})
    for f in drawing.features:
        if f.id == fid:
            return f
    raise InvalidArgumentError(f"there is no feature {fid[:64]!r}", detail={"parameter": "feature"})


REMOVE = object()  # a decision taken away, where None is itself an answer


def _decide(drawing: types.Drawing, fid: str, **changes: Any) -> types.Drawing:
    """``drawing`` with feature ``fid``'s decisions changed (:data:`REMOVE` takes one
    away; None is kept, as the answer "plain" to a thread question)."""
    feature = _feature(drawing, fid)
    made = dict(feature.decisions)
    for k, v in changes.items():
        if v is REMOVE:
            made.pop(k, None)
        else:
            made[k] = v
    new = replace(feature, decisions=tuple(made.items()))
    return replace(drawing, features=tuple(new if f.id == fid else f for f in drawing.features))


def _axis(axis: Any) -> str:
    if axis not in ("x", "y", "z"):
        raise InvalidArgumentError("axis must be x, y or z", detail={"parameter": "axis"})
    return axis


def _words(value: Any, parameter: str, limit: int) -> str:
    if not isinstance(value, str) or _CONTROL.search(value) or len(value) > limit:
        raise InvalidArgumentError(
            f"{parameter} must be one line of at most {limit} characters", detail={"parameter": parameter}
        )
    return value


def _flags(rec: DimensionRecord, add: Iterable[str] = (), drop: Iterable[str] = ()) -> tuple[str, ...]:
    drop = set(drop)
    return tuple(f for f in dict.fromkeys((*rec.flags, *add)) if f not in drop)


# --------------------------------------------------------------------------- dimensions


def remove(drawing: types.Drawing, ident: str) -> tuple[types.Drawing, tuple]:
    """Take a generated dimension off the sheet. It stays in the drawing, so
    :func:`restore` brings it back and regeneration keeps it removed."""
    _editable(drawing)
    rec = _record(drawing, ident)
    if rec.origin != "generated":
        raise InvalidArgumentError(
            f"{ident} is a dimension the user added: delete it instead", detail={"parameter": "id"}
        )
    return relayout(_with_record(drawing, replace(rec, state=REMOVED)))


def restore(drawing: types.Drawing, ident: str) -> tuple[types.Drawing, tuple]:
    """Bring a removed dimension back."""
    _editable(drawing)
    rec = _record(drawing, ident)
    if rec.state != REMOVED:
        raise InvalidArgumentError(f"{ident} is not removed", detail={"parameter": "id"})
    return relayout(_with_record(drawing, replace(rec, state=SHOWN)))


def delete(drawing: types.Drawing, ident: str) -> tuple[types.Drawing, tuple]:
    """Delete a dimension the user added; a generated one is removed, not deleted."""
    _editable(drawing)
    rec = _record(drawing, ident)
    if rec.origin != "user":
        raise InvalidArgumentError(
            f"{ident} is a generated dimension: remove it instead", detail={"parameter": "id"}
        )
    return relayout(replace(drawing, dimensions=tuple(d for d in drawing.dimensions if d.id != ident)))


@dataclass(frozen=True)
class Candidate:
    """A dimension the planner offers for the features picked (10.12 Add Dimension):
    ``restore`` brings a removed generated dimension back; ``distance`` adds a user
    dimension between two features along ``axis``, in ``view``."""

    kind: str
    key: str
    value: float
    words: str
    features: tuple[str, ...]
    axis: str | None = None
    view: str | None = None
    dimension: str | None = None  # restore: the removed dimension's id


def candidates(drawing: types.Drawing, features: Sequence[str]) -> tuple[Candidate, ...]:
    """The dimensions the planner offers for one or two picked features: the removed
    dimensions about them to restore, and, for two, the distance between them along
    each axis a view shows both on. Free picking of arbitrary edges is stage 4."""
    from . import numbers

    _check(drawing)
    feats = tuple(features)
    if not 1 <= len(feats) <= 2 or len(set(feats)) != len(feats):
        raise InvalidArgumentError("pick one or two features", detail={"parameter": "features"})
    for fid in feats:
        _feature(drawing, fid)
    unit = drawing.options.units if drawing.options.units in ("in", "mm") else "mm"
    out: list[Candidate] = []
    for d in drawing.dimensions:
        if d.state == REMOVED and set(feats) <= set(d.features):
            shown = numbers.number(numbers.in_unit(d.value, unit), d.places, unit)
            out.append(
                Candidate("restore", d.key, d.value, f"restore {d.id}, {shown}", feats, d.axis, d.view, d.id)
            )
    if len(feats) == 2:
        planned = _planned_for(drawing)
        have = {d.key for d in drawing.dimensions}
        for axis in ("x", "y", "z"):
            got = _distance(planned.detail, feats[0], feats[1], axis)
            if got is None:
                continue
            pa, pb, view, _sa = got
            key = _user_key(axis, feats[0], feats[1])
            if key in have:
                continue
            value = abs(pb.value - pa.value)
            shown = numbers.number(numbers.in_unit(value, unit), 3 if unit == "in" else 2, unit)
            out.append(Candidate("distance", key, value, f"{shown} along {axis.upper()}", feats, axis, view))
    return tuple(out)


def _planned_for(drawing: types.Drawing) -> Any:
    """The plan of ``drawing`` with its records applied (made when the kept one is
    stale)."""
    live = _need(drawing)
    key = _plan_key(drawing)
    if live.key != key or live.planned is None:
        relayout(drawing)
    return _apply(drawing, live.planned)[0]


def add(drawing: types.Drawing, candidate: Candidate) -> tuple[types.Drawing, tuple]:
    """Add a :class:`Candidate`: restore the removed dimension, or add the distance as a
    user dimension (precision from its role, tolerance from the block)."""
    _editable(drawing)
    if not isinstance(candidate, Candidate):
        raise InvalidArgumentError("add takes one of candidates()", detail={"parameter": "candidate"})
    if candidate.kind == "restore":
        return restore(drawing, candidate.dimension or "")
    if candidate.kind != "distance" or candidate.axis is None:
        raise InvalidArgumentError("add takes one of candidates()", detail={"parameter": "candidate"})
    planned = _planned_for(drawing)
    fa, fb = candidate.features
    got = _distance(planned.detail, fa, fb, candidate.axis, candidate.view)
    if got is None:
        raise InvalidArgumentError(
            "no view shows that distance now", detail={"parameter": "candidate", "rule": "stale"}
        )
    pa, pb, view, _sa = got
    from .plan import values

    ident = f"d-{document.next_number(drawing, 'd')}"
    rec = DimensionRecord(
        candidate.key,
        ident,
        "linear",
        view,
        abs(pb.value - pa.value),
        axis=candidate.axis,
        positions=(_position(pa), _position(pb)),
        features=tuple(dict.fromkeys(pa.features + pb.features)),
        places=values.places(planned.detail.ctx, "hole_location" if pb.kind != "face" else "step"),
        role="feature_location",
        origin="user",
    )
    next_id = dict(drawing.next_id)
    next_id["d"] = document.next_number(drawing, "d") + 1
    return relayout(replace(drawing, dimensions=(*drawing.dimensions, rec), next_id=tuple(next_id.items())))


def link(drawing: types.Drawing, a: str, b: str, axis: str) -> tuple[types.Drawing, tuple]:
    """Locate feature ``b`` from feature ``a`` along ``axis`` instead of from the
    origin, keeping the tree (10.12): ``b``'s location now runs from ``a``, under the
    same key. A link onto ``b`` from a feature located from ``b`` would close a loop
    and is refused."""
    _editable(drawing)
    axis = _axis(axis)
    _feature(drawing, a)
    _feature(drawing, b)
    if a == b:
        raise InvalidArgumentError("a feature is not linked to itself", detail={"parameter": "b"})
    step, seen = a, set()
    while step is not None and step not in seen:
        seen.add(step)
        nxt = dict(_feature(drawing, step).decisions).get(f"link_{axis}")
        if nxt == b:
            raise InvalidArgumentError(
                f"{a} is located from {b} along {axis.upper()}: linking {b} to it would close a loop",
                detail={"parameter": "a", "rule": "loop"},
            )
        step = nxt if isinstance(nxt, str) else None
    return relayout(_decide(drawing, b, **{f"link_{axis}": a}))


def unlink(drawing: types.Drawing, b: str, axis: str) -> tuple[types.Drawing, tuple]:
    """Locate feature ``b`` from the origin again along ``axis``."""
    _editable(drawing)
    return relayout(_decide(drawing, b, **{f"link_{_axis(axis)}": REMOVE}))


def set_origin(
    drawing: types.Drawing, axis: str, feature: str | None, face: int | None = None
) -> tuple[types.Drawing, tuple]:
    """Measure ``axis`` from ``feature``: its centre plane, or its face ``face`` (a face
    index) when given; ``feature=None`` goes back to the datum. One origin per axis."""
    _editable(drawing)
    axis = _axis(axis)
    if face is not None and (isinstance(face, bool) or not isinstance(face, int) or face < 0):
        raise InvalidArgumentError("face is a face index", detail={"parameter": "face"})
    out = drawing
    for f in drawing.features:
        if f"origin_{axis}" in dict(f.decisions):
            out = _decide(out, f.id, **{f"origin_{axis}": REMOVE})
    if feature is not None:
        _feature(drawing, feature)
        out = _decide(out, feature, **{f"origin_{axis}": "centre" if face is None else face})
    return relayout(out)


def set_scheme(drawing: types.Drawing, view: str, axis: str, scheme: str) -> tuple[types.Drawing, tuple]:
    """Baseline or ordinate for one view and axis (10.4)."""
    _editable(drawing)
    axis = _axis(axis)
    if scheme not in types.ARRANGEMENTS:
        raise InvalidArgumentError("scheme must be baseline or ordinate", detail={"parameter": "scheme"})
    types.check_id(view, "view id")
    made = dict(drawing.options.arrangement)
    made[f"{view}/{axis}"] = scheme
    options = replace(drawing.options, arrangement=tuple(sorted(made.items())))
    return relayout(replace(drawing, options=options))


def set_depth_reference(drawing: types.Drawing, feature: str, reference: str) -> tuple[types.Drawing, tuple]:
    """A pocket's or blind feature's depth from its open face (``open``, the default) or
    its floor from the far side of the part (``floor``)."""
    _editable(drawing)
    if reference not in ("open", "floor"):
        raise InvalidArgumentError("reference must be open or floor", detail={"parameter": "reference"})
    return relayout(_decide(drawing, feature, depth_from=REMOVE if reference == "open" else "floor"))


def set_tolerance(
    drawing: types.Drawing, ident: str, kind: str, upper: float = 0.0, lower: float = 0.0
) -> tuple[types.Drawing, tuple]:
    """A dimension's tolerance: ``block`` (back to the general block, or the planner's
    choice), ``basic``, ``reference``, or explicit (``symmetric`` with ``upper`` as
    the plus and minus, ``deviations`` and ``limits`` with both, ``max``, ``min``), in
    the drawing's unit."""
    _editable(drawing)
    rec = _record(drawing, ident)
    if kind not in TOLERANCE_KINDS:
        raise InvalidArgumentError(
            f"kind must be one of {', '.join(TOLERANCE_KINDS)}", detail={"parameter": "kind"}
        )
    for name, v in (("upper", upper), ("lower", lower)):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > 1e3:
            raise InvalidArgumentError(f"{name} must be a number", detail={"parameter": name})
    if kind == "symmetric" and upper <= 0:
        raise InvalidArgumentError("a symmetric tolerance must be more than 0", detail={"parameter": "upper"})
    if kind == "block" and rec.origin == "generated":
        rec = replace(rec, flags=_flags(rec, drop=("user_tolerance",)))
        return relayout(_with_record(drawing, rec))
    rec = replace(
        rec,
        tolerance=kind,
        tolerance_values=(float(upper), float(lower)),
        flags=_flags(rec, add=("user_tolerance",)),
    )
    return relayout(_with_record(drawing, rec))


def set_precision(drawing: types.Drawing, ident: str, places: int | None) -> tuple[types.Drawing, tuple]:
    """A dimension's decimals; None goes back to its role's (10.8). The checks show the
    band the new precision falls in (R2.rounding)."""
    _editable(drawing)
    rec = _record(drawing, ident)
    if places is None:
        return relayout(_with_record(drawing, replace(rec, places_source="role")))
    if isinstance(places, bool) or not isinstance(places, int) or not 0 <= places <= 4:
        raise InvalidArgumentError("places must be 0 to 4", detail={"parameter": "places"})
    return relayout(_with_record(drawing, replace(rec, places=places, places_source="user")))


def set_prefix(drawing: types.Drawing, ident: str, text: str) -> tuple[types.Drawing, tuple]:
    """A dimension's prefix (a count such as ``4X``), kept apart from the value."""
    _editable(drawing)
    rec = _record(drawing, ident)
    text = _words(text, "text", MAX_PREFIX)
    return relayout(_with_record(drawing, replace(rec, prefix=text, flags=_flags(rec, add=(USER_TEXT,)))))


def set_suffix(drawing: types.Drawing, ident: str, lines: Sequence[str]) -> tuple[types.Drawing, tuple]:
    """A dimension's suffix lines (THRU, a note), kept apart from the value."""
    _editable(drawing)
    rec = _record(drawing, ident)
    if isinstance(lines, str) or len(lines) > MAX_SUFFIX_LINES:
        raise InvalidArgumentError(
            f"lines must be at most {MAX_SUFFIX_LINES} lines", detail={"parameter": "lines"}
        )
    lines = tuple(_words(x, "lines", DEFAULT_LIMITS.note_chars) for x in lines)
    return relayout(_with_record(drawing, replace(rec, suffix=lines, flags=_flags(rec, add=(USER_TEXT,)))))


def reset_text(drawing: types.Drawing, ident: str) -> tuple[types.Drawing, tuple]:
    """A generated dimension's prefix and suffix back to the planner's."""
    _editable(drawing)
    rec = _record(drawing, ident)
    return relayout(_with_record(drawing, replace(rec, flags=_flags(rec, drop=(USER_TEXT,)))))


def override_value(drawing: types.Drawing, ident: str, text: str | None) -> tuple[types.Drawing, tuple]:
    """Show ``text`` for a dimension's value (None takes the override off). Allowed
    with R2.override: an error until accepted with a typed reason, which blocks
    release, and a badge in the editor."""
    _editable(drawing)
    rec = _record(drawing, ident)
    if text is not None:
        text = _words(text, "text", MAX_OVERRIDE).strip()
        if not text:
            raise InvalidArgumentError("an override needs text", detail={"parameter": "text"})
    return relayout(_with_record(drawing, replace(rec, override=text)))


def set_frame(drawing: types.Drawing, ident: str, frame: FrameCell | None) -> tuple[types.Drawing, tuple]:
    """A dimension's feature control frame (None removes it); the datums it names must
    exist on the drawing (R18 checks the grammar)."""
    _editable(drawing)
    rec = _record(drawing, ident)
    if frame is not None:
        if not isinstance(frame, FrameCell):
            raise InvalidArgumentError("frame must be a FrameCell", detail={"parameter": "frame"})
        letters = {d.letter for d in drawing.datums}
        missing = [x for x in frame.datums if x not in letters]
        if missing:
            raise InvalidArgumentError(
                f"datum {missing[0]} is not on the drawing", detail={"parameter": "frame", "rule": "datum"}
            )
    return relayout(_with_record(drawing, replace(rec, frame=frame, flags=_flags(rec, add=("user_frame",)))))


def reset_frame(drawing: types.Drawing, ident: str) -> tuple[types.Drawing, tuple]:
    """A dimension's frame back to the planner's."""
    _editable(drawing)
    rec = _record(drawing, ident)
    return relayout(_with_record(drawing, replace(rec, flags=_flags(rec, drop=("user_frame",)))))


def set_datum(drawing: types.Drawing, letter: str, face: int | None) -> tuple[types.Drawing, tuple]:
    """Put datum ``letter`` on planar face ``face`` (a face index of a feature in the
    table), or take it off (None). The feature claiming the face carries the letter,
    so the datum follows it through regeneration (13.4)."""
    _editable(drawing)
    if not isinstance(letter, str) or not _LETTER.fullmatch(letter):
        raise InvalidArgumentError(
            "a datum letter is one capital letter, not I, O, Q or X", detail={"parameter": "letter"}
        )
    live = _need(drawing)
    datums = [d for d in drawing.datums if d.letter != letter]
    out = drawing
    for f in drawing.features:
        if dict(f.decisions).get("datum") == letter:
            out = _decide(out, f.id, datum=REMOVE)
    if face is not None:
        if isinstance(face, bool) or not isinstance(face, int):
            raise InvalidArgumentError("face is a face index", detail={"parameter": "face"})
        if any(d.face == face for d in datums):
            raise InvalidArgumentError("that face is already a datum", detail={"parameter": "face"})
        fs = live.features
        owner = next((k for k, f in enumerate(fs.features) if face in f.faces), None)
        if owner is None or owner >= len(drawing.features):
            raise InvalidArgumentError(
                "a datum goes on a face of a feature in the drawing's table", detail={"parameter": "face"}
            )
        out = _decide(out, drawing.features[owner].id, datum=letter)
        datums.append(Datum(letter, face, "chosen by the user"))
    datums.sort(key=lambda d: (len(d.letter), d.letter))
    return relayout(replace(out, datums=tuple(datums)))


def move(
    drawing: types.Drawing, ident: str, along_mm: float, across_mm: float
) -> tuple[types.Drawing, tuple]:
    """Move a dimension relative to its attach points, paper millimetres: a linear
    dimension's text along its line and its line across (away from the view when
    positive); a leader item's shoulder by (along, across) as sheet x and y."""
    _editable(drawing)
    rec = _record(drawing, ident)
    track = rec.placement.track if rec.placement is not None else 0
    placement = Placement(float(along_mm), float(across_mm), track, True)
    return relayout(_with_record(drawing, replace(rec, placement=placement)))


def move_balloon(
    drawing: types.Drawing, item: str, dx_mm: float, dy_mm: float
) -> tuple[types.Drawing, tuple]:
    """Put item ``item``'s balloon with its centre (``dx_mm``, ``dy_mm``) paper millimetres
    from the point its leader ends on; it stays there as the views move, and the checks
    report it when it runs into something."""
    _editable(drawing)
    item = str(item)
    if item not in {b.item for b in _balloons(drawing)}:
        raise InvalidArgumentError(f"the drawing has no balloon {item[:40]!r}", detail={"parameter": "item"})
    kept = tuple(e for e in drawing.options.balloons if e[0] != item)
    moved = (*kept, (item, float(dx_mm), float(dy_mm)))
    return relayout(replace(drawing, options=replace(drawing.options, balloons=moved)))


def reset_balloon(drawing: types.Drawing, item: str) -> tuple[types.Drawing, tuple]:
    """Item ``item``'s balloon back where layout places it."""
    _editable(drawing)
    kept = tuple(e for e in drawing.options.balloons if e[0] != str(item))
    return relayout(replace(drawing, options=replace(drawing.options, balloons=kept)))


def _balloons(drawing: types.Drawing) -> list:
    from . import display as D

    sheet = drawing.sheet
    return [a for a in (sheet.annotations if sheet is not None else ()) if isinstance(a, D.Balloon)]


def reset_position(drawing: types.Drawing, ident: str) -> tuple[types.Drawing, tuple]:
    """A dimension's place and side back to the ones layout chooses."""
    _editable(drawing)
    rec = _record(drawing, ident)
    return relayout(
        _with_record(
            drawing, replace(rec, placement=None, side=None, flags=_flags(rec, drop=("placement_reset",)))
        )
    )


def _shown_side(drawing: types.Drawing, rec: DimensionRecord) -> str | None:
    """The side of its view a dimension is drawn on, read from the sheet."""
    from . import display

    sheet = drawing.sheet
    if not isinstance(sheet, display.Sheet):
        return None
    ann = next((a for a in sheet.annotations if isinstance(a, display.Dimension) and a.id == rec.id), None)
    if ann is None or len(ann.points) < 2:
        return None
    if rec.kind in ("linear",):
        p0, _p1, on_line = ann.points[0], ann.points[1], ann.points[-1]
        if ann.angle_deg == 0.0:
            return "above" if on_line[1] > p0[1] else "below"
        return "right" if on_line[0] > p0[0] else "left"
    start, other = ann.points[0], ann.points[1]
    return "right" if ann.text_at[0] >= min(start[0], other[0]) else "left"


def flip(drawing: types.Drawing, ident: str) -> tuple[types.Drawing, tuple]:
    """Put a dimension on the other side: a linear dimension across its view, a leader
    item's text to the other side of its feature. Ordinate dimensions stay in their
    row."""
    _editable(drawing)
    rec = _record(drawing, ident)
    if rec.kind == "ordinate":
        raise InvalidArgumentError(
            "an ordinate dimension stays in its row; set the scheme to baseline to flip it",
            detail={"parameter": "id", "rule": "ordinate"},
        )
    side = rec.side or _shown_side(drawing, rec)
    if side is None:
        raise InvalidArgumentError(f"{ident} is not on the sheet", detail={"parameter": "id"})
    other = {"below": "above", "above": "below", "left": "right", "right": "left"}[side]
    return relayout(_with_record(drawing, replace(rec, side=other)))


# --------------------------------------------------------------------------- the sheet, views and units


def set_sheet(drawing: types.Drawing, sheet: str) -> tuple[types.Drawing, tuple]:
    """The sheet size (``A`` to ``E``, or ``auto``) for this drawing."""
    _editable(drawing)
    if sheet not in types.SHEET_CHOICES:
        raise InvalidArgumentError("sheet must be auto or A to E", detail={"parameter": "sheet"})
    return relayout(replace(drawing, options=replace(drawing.options, sheet=sheet)))


def set_scale(drawing: types.Drawing, scale: str | tuple[int, int]) -> tuple[types.Drawing, tuple]:
    """The scale, ``(sheet, model)`` such as ``(1, 2)``, or ``auto``."""
    _editable(drawing)
    if isinstance(scale, list):
        scale = tuple(scale)
    return relayout(replace(drawing, options=_options(drawing.options, scale=scale)))


def set_units(drawing: types.Drawing, units: str) -> tuple[types.Drawing, tuple]:
    """The drawing's unit, ``in`` or ``mm``; every value and the block follow."""
    _editable(drawing)
    if units not in ("in", "mm"):
        raise InvalidArgumentError("units must be in or mm", detail={"parameter": "units"})
    return relayout(replace(drawing, options=replace(drawing.options, units=units)))


def set_parts_list(drawing: types.Drawing, table: Any) -> tuple[types.Drawing, tuple]:
    """An assembly drawing's parts list as the BOM editor left it: ``table`` is a
    :class:`~solidseas.bomtable.BomTableSpec`'s JSON (``to_json``), or None for the parts
    list SolidSeas makes by default (``docs/drawings/assemblies.md``)."""
    from ..bomtable import spec_from_json

    _editable(drawing)
    if drawing.model.get("format") != "sldasm":
        raise InvalidArgumentError(
            "only an assembly's drawing has a parts list", detail={"parameter": "table"}
        )
    text = None if table is None else types.parts_list_text(spec_from_json(table))
    return relayout(replace(drawing, options=replace(drawing.options, parts_list=text)))


def boms(drawing: types.Drawing) -> dict[str, Any]:
    """The bills of materials of an assembly drawing's model, one per type, as ``bom``
    JSON (:func:`solidseas.model.bom_data`): what the BOM editor shows for the parts
    list. The model must be open (``attach``)."""
    from ..model import bom_data

    contents = getattr(_need(drawing).source, "assembly", None)
    if contents is None:
        raise InvalidArgumentError(
            "only an assembly's drawing has a parts list", detail={"parameter": "drawing"}
        )
    return {t: bom_data(b) for t, b in contents.boms if b is not None}


def _options(options: types.DrawingOptions, **kw: Any) -> types.DrawingOptions:
    return replace(options, **kw)  # DrawingOptions checks each value


def add_view(drawing: types.Drawing, name: str) -> tuple[types.Drawing, tuple]:
    """Add a principal view (``top``, ``right``, ``isometric``...). Sections and detail
    views on request come in a later release (3.3)."""
    _editable(drawing)
    if name in ("section", "detail"):
        raise UnsupportedOperationError(
            f"{name} views on request come in a later release",
            detail={"rule": "later_release", "value": name},
        )
    if name not in types.VIEW_NAMES:
        raise InvalidArgumentError(
            f"name must be one of {', '.join(types.VIEW_NAMES)}", detail={"parameter": "name"}
        )
    views = _view_names(drawing)
    if name in views:
        raise InvalidArgumentError(f"the drawing has a {name} view", detail={"parameter": "name"})
    order = {n: k for k, n in enumerate(types.VIEW_NAMES)}
    views = tuple(sorted((*views, name), key=order.__getitem__))
    return relayout(replace(drawing, options=replace(drawing.options, views=views)))


def remove_view(drawing: types.Drawing, name: str) -> tuple[types.Drawing, tuple]:
    """Take a principal view off; the front view stays. Its dimensions move to the
    views left, or are reported missing by the checks."""
    _editable(drawing)
    views = _view_names(drawing)
    if name == "front":
        raise InvalidArgumentError("the front view stays", detail={"parameter": "name"})
    if name not in views:
        raise InvalidArgumentError(f"the drawing has no {name} view", detail={"parameter": "name"})
    views = tuple(v for v in views if v != name)
    return relayout(replace(drawing, options=replace(drawing.options, views=views)))


def _view_names(drawing: types.Drawing) -> tuple[str, ...]:
    views = drawing.options.views
    if views == "auto":
        live = _need(drawing)
        views = tuple(dict.fromkeys(s.name for s, _g in live.views if s.name in types.VIEW_NAMES))
    return tuple(views)


# --------------------------------------------------------------------------- notes, title and settings


def edit_notes(drawing: types.Drawing, texts: Sequence[str]) -> tuple[types.Drawing, tuple]:
    """The drawing's notes, in order, as text: a note whose text is unchanged keeps its
    id, origin and frames; others are the user's. The settings snapshot is unchanged."""
    _editable(drawing)
    if isinstance(texts, str) or len(texts) > document.MAX_NOTES:
        raise InvalidArgumentError("texts must be a list of notes", detail={"parameter": "texts"})
    texts = [_words(t, "texts", DEFAULT_LIMITS.note_chars).strip() for t in texts]
    old = {n.text: (i, n) for i, n in reversed(drawing.notes)}
    next_n = document.next_number(drawing, "n")
    notes, taken = [], set()
    for text in texts:
        if not text:
            continue
        hit = old.get(text)
        if hit is not None and hit[0] not in taken:
            taken.add(hit[0])
            notes.append(hit)
            continue
        notes.append((f"n-{next_n}", NoteRecord(text, (), "user")))
        next_n += 1
    next_id = dict(drawing.next_id)
    next_id["n"] = next_n
    return relayout(replace(drawing, notes=tuple(notes), next_id=tuple(next_id.items())))


def add_flag_note(drawing: types.Drawing, note: str, items: Sequence[str]) -> tuple[types.Drawing, tuple]:
    """A note referenced by flag symbols on items: flag symbols come in a later release;
    :func:`edit_notes` adds the note itself."""
    _editable(drawing)
    raise UnsupportedOperationError(
        "flag notes come in a later release; add the note with edit_notes",
        detail={"rule": "later_release", "value": "flag_note"},
    )


def set_title(drawing: types.Drawing, key: str, text: str | None) -> tuple[types.Drawing, tuple]:
    """A title field typed by the user (None gives it back to the part, or clears it);
    a material or finish in the settings' list shows as its callout."""
    _editable(drawing)
    if key not in document.TITLE_KEYS:
        raise InvalidArgumentError(
            f"key must be one of {', '.join(document.TITLE_KEYS)}", detail={"parameter": "key"}
        )
    title = dict(drawing.title)
    if text is None:
        title.pop(key, None)
    else:
        text = _words(text, "text", DEFAULT_LIMITS.title_chars).strip()
        entry = document._listed(_settings(drawing), key, text)
        title[key] = (
            types.TitleField(entry["callout"], "list")
            if entry is not None
            else types.TitleField(text, "typed")
        )
    return relayout(replace(drawing, title=tuple(title.items())))


def set_tolerance_block(
    drawing: types.Drawing, rows: Sequence[tuple[int, float]]
) -> tuple[types.Drawing, tuple]:
    """The general tolerance block of this drawing's unit, rows of (decimals, plus and
    minus), in the drawing's settings snapshot; the snapshot is otherwise unchanged."""
    _editable(drawing)
    unit = drawing.options.units if drawing.options.units in ("in", "mm") else "mm"
    key = "inch_block" if unit == "in" else "mm_block"
    settings = settings_mod.with_value(_settings(drawing), "tolerances", key, [list(r) for r in rows])
    return relayout(replace(drawing, settings=settings))


def use_settings(
    drawing: types.Drawing, settings: settings_mod.DrawingSettings
) -> tuple[types.Drawing, tuple]:
    """Use Current Drawing Settings: the snapshot replaced by ``settings``."""
    _editable(drawing)
    if not isinstance(settings, settings_mod.DrawingSettings):
        raise InvalidArgumentError("settings must be DrawingSettings", detail={"parameter": "settings"})
    return relayout(replace(drawing, settings=settings))


# --------------------------------------------------------------------------- the user's decisions


def confirm_thread(
    drawing: types.Drawing, feature: str, spec: str | None, depth: float | None = None
) -> tuple[types.Drawing, tuple]:
    """A thread the user confirmed on a hole (``1/4-20 UNC-2B``, ``M6x1.0-6H``), with its
    depth in metres for a blind one; None answers that the hole is plain (a clearance
    or plain hole, the question answered); :func:`clear_thread` takes the answer
    away. A thread is called out only once confirmed (R7.callouts)."""
    _editable(drawing)
    if spec is not None:
        if not isinstance(spec, str) or not _THREAD.fullmatch(spec.strip()):
            raise InvalidArgumentError("spec must be a thread designation", detail={"parameter": "spec"})
        spec = spec.strip().upper()
    if depth is not None and (
        isinstance(depth, bool) or not isinstance(depth, (int, float)) or not 0 < depth < 10
    ):
        raise InvalidArgumentError("depth must be a length in metres", detail={"parameter": "depth"})
    depth_answer = REMOVE if spec is None or depth is None else depth
    return relayout(_decide(drawing, feature, thread=spec, thread_depth=depth_answer))


def clear_thread(drawing: types.Drawing, feature: str) -> tuple[types.Drawing, tuple]:
    """Take a hole's thread answer away: the question is open again."""
    _editable(drawing)
    return relayout(_decide(drawing, feature, thread=REMOVE, thread_depth=REMOVE))


def confirm_end(drawing: types.Drawing, feature: str, confirmed: bool = True) -> tuple[types.Drawing, tuple]:
    """A hole that ends in another bore, confirmed: its callout says INTO BORE."""
    _editable(drawing)
    if not isinstance(confirmed, bool):
        raise InvalidArgumentError("confirmed must be true or false", detail={"parameter": "confirmed"})
    return relayout(_decide(drawing, feature, into_bore_note=True if confirmed else REMOVE))


# --------------------------------------------------------------------------- status (13.2, 13.3)


def sign(
    drawing: types.Drawing, row: str, person: str, today: str | datetime.date | None = None
) -> tuple[types.Drawing, tuple]:
    """Sign ``row`` (13.2); the title block shows the name and date. The command line
    never signs: approvals come from a person in the viewer."""
    signed, _warnings = release.sign(drawing, row, person, today)
    return relayout(signed)


def release_drawing(
    drawing: types.Drawing,
    today: str | datetime.date | None = None,
    accepted: Mapping[str, str] | None = None,
) -> tuple[types.Drawing, tuple]:
    """Release (13.2) with the release-time checks: refused with
    ``release.ReleaseRefusedError`` listing every reason; else RELEASED, laid out again
    without the stamp. The released PDF and DXF are then written as new files."""
    _editable(drawing, "it is already released")
    found = checks(drawing, at_release=True)
    released = release.release(drawing, today, accepted, checks=found)
    return relayout(released)


def start_revision(
    drawing: types.Drawing,
    description: str,
    zones: Iterable[str] = (),
    *,
    drawn_by: str | None = None,
    today: str | datetime.date | None = None,
) -> tuple[types.Drawing, tuple]:
    """Open a released drawing for its next revision (13.3): a new row, the signatures
    cleared, PRELIMINARY and stamped again."""
    opened = release.start_revision(drawing, description, zones, drawn_by=drawn_by, today=today)
    return relayout(opened)


__all__ = [
    "MAX_LIVE",
    "Candidate",
    "Live",
    "add",
    "add_flag_note",
    "add_view",
    "adopt",
    "attach",
    "boms",
    "candidates",
    "checks",
    "clear_thread",
    "confirm_end",
    "confirm_thread",
    "delete",
    "edit_notes",
    "flip",
    "forget",
    "link",
    "live_for",
    "move",
    "move_live",
    "override_value",
    "release_drawing",
    "relayout",
    "remove",
    "remove_view",
    "reset_frame",
    "reset_position",
    "reset_text",
    "restore",
    "set_datum",
    "set_depth_reference",
    "set_frame",
    "set_origin",
    "set_parts_list",
    "set_precision",
    "set_prefix",
    "set_scale",
    "set_scheme",
    "set_sheet",
    "set_suffix",
    "set_title",
    "set_tolerance",
    "set_tolerance_block",
    "set_units",
    "sign",
    "start_revision",
    "unlink",
    "use_settings",
    "move_balloon",
    "reset_balloon",
]
