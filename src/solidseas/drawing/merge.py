"""Regeneration that keeps the user's edits (``docs/DRAWINGS.md`` 13.5).

:func:`regenerate` is the library's ``drawing.regenerate(drawing, source)``. When the
model's file hash differs from the drawing's:

1. **Geometry unchanged** (the geometry digest is the drawing's): only the model
   reference changes. The result says "model file changed, geometry unchanged" and
   carries the drawing with the new reference taken (its hashes, part number, model
   revision, and the title fields whose origin is ``part``); the editor offers it.
2. **Geometry changed**: the pipeline runs again with the drawing's frozen options
   and settings snapshot, and :func:`merge` merges the new run into the drawing.
   Until every stage of the pipeline is built this raises ``not_implemented`` with
   rule ``stage_missing`` naming the first missing stage, as ``make_drawing`` does.
   ``regenerate(drawing, new=other)`` merges a run made elsewhere (a test, or a
   branch driving its own stages).

:func:`merge` is the merge of step 3, on two drawings: the old one, with the user's
edits, and a new run's. Features are paired by :mod:`.match`; matched features keep
their ids and the user's decisions (datum letters included: a datum follows its
matched face, and a datum whose face is gone is reported and never re-picked from
the new run); new features take the next free ids. Dimension keys are compared in
the old drawing's id space: exact key matches inherit state, placement and
overrides (a placement whose view or side changed is reset and reported); new
requirements are added and marked ``new``; generated dimensions whose requirement
is gone are dropped (a removed one is forgotten, a shown one reported); a user
dimension whose features are gone is kept and marked ``needs_attention``, and stays
off the sheet. Notes and title fields are never regenerated, except title fields
whose origin is ``part``, which follow the part. The options, settings snapshot,
revisions and outputs are the old drawing's; the signatures the merge invalidates
are cleared (13.2). The report counts dimensions ("31 unchanged, 2 changed, 3 new,
1 dropped, 1 needs attention", a datum whose face is gone counting as needing
attention) and pre-fills the next revision row. A RELEASED drawing must start a
revision first.

The merged sheet is the new run's, with dimension ids renamed to the merged ones and
removed dimensions taken off; user placements and kept user dimensions are applied
when the layout stage lays the sheet out again from the merged records.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from ..errors import InvalidArgumentError, ModelNotFoundError
from . import document, match, release, types
from . import settings as settings_mod
from .assembly import same_file
from .limits import DEFAULT_LIMITS, DrawingLimits

GEOMETRY_UNCHANGED = "model file changed, geometry unchanged"
MODEL_UNCHANGED = "the model is unchanged"
# Flags a merge sets afresh each time; the editor's own flags are kept.
_MERGE_FLAGS = ("new", "changed", "needs_attention", "placement_reset")
_IDENTITY = (
    "name",
    "format",
    "configuration",
    "sha256",
    "geometry",
    "properties",
    "part_number",
    "model_revision",
    "units",
)


@dataclass(frozen=True)
class MergeReport:
    """What a regeneration did, identically for the editor and ``drawing update --json``:
    dimension counts, the features matched, resized, gone and new, and the lines to
    show. ``forgotten`` counts removed dimensions whose requirement is gone."""

    unchanged: int = 0
    changed: int = 0
    new: int = 0
    dropped: int = 0
    attention: int = 0
    forgotten: int = 0
    model_unchanged: bool = False
    geometry_unchanged: bool = False
    features_matched: int = 0
    features_resized: tuple[str, ...] = ()
    features_gone: tuple[str, ...] = ()
    features_new: tuple[str, ...] = ()
    items: tuple[str, ...] = field(default=())

    def words(self) -> str:
        """The report's sentence: "31 unchanged, 2 changed, 3 new, 1 dropped, 1 needs
        attention", or :data:`GEOMETRY_UNCHANGED`, or :data:`MODEL_UNCHANGED`."""
        if self.model_unchanged:
            return MODEL_UNCHANGED
        if self.geometry_unchanged:
            return GEOMETRY_UNCHANGED
        return (
            f"{self.unchanged} unchanged, {self.changed} changed, {self.new} new, "
            f"{self.dropped} dropped, {self.attention} needs attention"
        )

    def description(self) -> str:
        """What the next revision row's description is pre-filled with."""
        if self.model_unchanged:
            return ""
        if self.geometry_unchanged:
            return "MODEL REFERENCE UPDATED, GEOMETRY UNCHANGED"
        parts = []
        for n, what in ((self.changed, "CHANGED"), (self.new, "ADDED"), (self.dropped, "REMOVED")):
            if n:
                parts.append(f"{n} DIMENSION{'S' if n != 1 else ''} {what}")
        return "UPDATED FROM MODEL" + (": " + ", ".join(parts) if parts else "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "words": self.words(),
            "unchanged": self.unchanged,
            "changed": self.changed,
            "new": self.new,
            "dropped": self.dropped,
            "needs_attention": self.attention,
            "forgotten": self.forgotten,
            "model_unchanged": self.model_unchanged,
            "geometry_unchanged": self.geometry_unchanged,
            "features": {
                "matched": self.features_matched,
                "resized": list(self.features_resized),
                "gone": list(self.features_gone),
                "new": list(self.features_new),
            },
            "items": list(self.items),
        }


def _check(drawing: Any, name: str) -> None:
    if not isinstance(drawing, types.Drawing):
        raise InvalidArgumentError(f"{name} must be a Drawing", detail={"parameter": name})


def _settings(drawing: types.Drawing) -> settings_mod.DrawingSettings:
    s = drawing.settings
    return s if isinstance(s, settings_mod.DrawingSettings) else settings_mod.DrawingSettings()


def _follow_part(old_title, new_title: Mapping[str, types.TitleField], items: list[str]) -> tuple:
    """Title fields: kept, except those of origin ``part``, which follow the part; a
    field the part newly gives is added."""
    out = []
    seen = set()
    for key, f in old_title:
        seen.add(key)
        if f.source != "part":
            out.append((key, f))
            continue
        nf = new_title.get(key)
        if nf is None or nf.source != "part":
            items.append(f"the title field {key} followed the part, which no longer gives it")
            continue
        if nf.text != f.text:
            items.append(f"the title field {key} follows the part: {nf.text}")
        out.append((key, nf))
    for key, nf in new_title.items():
        if key not in seen and nf.source == "part":
            items.append(f"the title field {key} comes from the part: {nf.text}")
            out.append((key, nf))
    return tuple(out)


def _identity(old_model: Mapping[str, Any], new_model: Mapping[str, Any], *, extents: bool) -> dict:
    model = dict(old_model)
    for k in _IDENTITY:
        model[k] = new_model.get(k)
    if extents:
        model["extents"] = new_model.get("extents")
    return model


def _finish(
    drawing: types.Drawing, report: MergeReport, items: list[str]
) -> tuple[types.Drawing, MergeReport]:
    drawing, cleared = release.invalidate(drawing)
    return drawing, replace(report, items=tuple(items) + tuple(cleared))


def _stem(name: Any) -> str:
    return os.path.splitext(name)[0] if isinstance(name, str) else ""


def _with_name_fields(
    drawing: types.Drawing, model: Mapping[str, Any], part_title: Mapping[str, types.TitleField]
) -> dict[str, types.TitleField]:
    """The part's title fields with those a new drawing takes from the part's file name
    when no property gives them (number, title, part number): a field that held the old
    name follows the new one, so taking a new reference never empties it."""
    out = dict(part_title)
    old, new = _stem((drawing.model or {}).get("name")), _stem(model.get("name"))
    for key, f in drawing.title:
        if f.source == "part" and key not in out and old and new and f.text.casefold() == old.casefold():
            out[key] = types.TitleField(new.upper() if f.text == f.text.upper() else new, "part")
    return out


def take_reference(
    drawing: types.Drawing, model: Mapping[str, Any], part_title: Mapping[str, types.TitleField]
) -> tuple[types.Drawing, MergeReport]:
    """Step 1 of 13.5: the drawing with a new model reference (its identity from
    ``model``, its location kept) and the part's title fields, for a model file whose
    geometry did not change."""
    release.require_editable(drawing, "it must start a revision before it takes a new model reference")
    items = [GEOMETRY_UNCHANGED]
    title = _follow_part(drawing.title, _with_name_fields(drawing, model, part_title), items)
    out = replace(drawing, model=_identity(drawing.model or {}, model, extents=False), title=title)
    return _finish(out, MergeReport(geometry_unchanged=True), items)


def _datum(feature: types.FeatureRecord) -> str | None:
    """The datum letter a feature's decisions give it, if any."""
    letter = dict(feature.decisions).get("datum")
    return letter if isinstance(letter, str) and letter else None


def _rekey(key: str, ids: Mapping[str, str]) -> str:
    return "/".join(ids.get(part, part) for part in key.split("/"))


def merge(old: types.Drawing, new: types.Drawing) -> tuple[types.Drawing, MergeReport]:
    """Merge a new run's drawing ``new`` into ``old``, keeping the user's edits (13.5,
    see the module notes). Returns the merged drawing and the report."""
    _check(old, "old")
    _check(new, "new")
    release.require_editable(old, "it must start a revision before Update from Model")
    om, nm = old.model or {}, new.model or {}
    if same_file(om, nm):
        return old, MergeReport(model_unchanged=True, items=(MODEL_UNCHANGED,))
    if om.get("geometry") and om.get("geometry") == nm.get("geometry"):
        return take_reference(old, nm, dict(new.title))

    items: list[str] = []
    m = match.match(old.features, new.features, old_extents=om.get("extents"), new_extents=nm.get("extents"))
    if m.greedy:
        items.append(
            "features of these kinds were too many to pair exactly and were paired nearest first: "
            + ", ".join(m.greedy)
        )
    old_for_new = m.old_for_new()
    resized_new = {p.new for p in m.pairs if p.changed_size}
    next_f = document.next_number(old, "f")
    ids: dict[str, str] = {}
    features = []
    resized, added = [], []
    for j, rec in enumerate(new.features):
        if j in old_for_new:
            o = old.features[old_for_new[j]]
            ident = o.id
            decisions = {k: v for k, v in rec.decisions if k != "datum"}
            decisions.update(dict(o.decisions))
            if j in resized_new:
                resized.append(ident)
        else:
            ident = f"f-{next_f}"
            next_f += 1
            decisions = {k: v for k, v in rec.decisions if k != "datum"}
            added.append(ident)
        ids[rec.id] = ident
        features.append(types.FeatureRecord(ident, rec.descriptor, tuple(decisions.items())))
    gone = [old.features[i] for i in m.gone]
    merged_ids = {f.id for f in features}

    # Datums follow their features; a datum whose feature is gone is never re-picked.
    attention = 0
    letters = {_datum(f): f.id for f in features if _datum(f)}
    for f in gone:
        letter = _datum(f)
        if letter:
            attention += 1
            items.append(f"datum {letter}'s feature {f.id} is gone: choose a new datum {letter}")
    new_letter_at: dict[str, types.Datum] = {}
    for rec in new.features:
        letter = _datum(rec)
        if letter:
            datum = next((d for d in new.datums if d.letter == letter), None)
            if datum is not None:
                new_letter_at[ids[rec.id]] = datum
            if letters.get(letter) not in (None, ids[rec.id]):
                items.append(
                    f"the new model would put datum {letter} on {ids[rec.id]}; it stays on {letters[letter]}"
                )
    old_reason = {d.letter: d.reason for d in old.datums}
    datums = []
    for letter in sorted(letters, key=lambda x: (len(x), x)):
        fid = letters[letter]
        found = new_letter_at.get(fid)
        datums.append(
            types.Datum(
                letter, found.face if found is not None else -1, old_reason.get(letter, "kept on its feature")
            )
        )

    # Dimensions, compared by key in the old drawing's id space.
    old_by_key: dict[str, Any] = {}
    for d in old.dimensions:
        old_by_key.setdefault(d.key, d)
    resized_ids = set(resized)
    next_d = document.next_number(old, "d")
    taken: set[str] = set()
    dims = []
    sheet_ids: dict[str, str] = {}
    off_sheet: list[str] = []
    counts = {"unchanged": 0, "changed": 0, "new": 0, "dropped": 0, "forgotten": 0}
    for raw in new.dimensions:
        nd = document.as_record(raw)
        nd = replace(
            nd,
            key=_rekey(nd.key, ids),
            features=tuple(ids.get(f, f) for f in nd.features),
            serves=tuple(_rekey(k, ids) for k in nd.serves),
            positions=tuple(
                replace(p, features=tuple(ids.get(f, f) for f in p.features)) for p in nd.positions
            ),
            flags=tuple(f for f in nd.flags if f not in _MERGE_FLAGS),
        )
        od = old_by_key.get(nd.key)
        if od is not None and nd.key not in taken:
            taken.add(nd.key)
            od = document.as_record(od)
            own = tuple(f for f in od.flags if f not in _MERGE_FLAGS)
            flags = list(own)
            placement = od.placement
            if placement is not None and (od.view != nd.view or od.side != nd.side):
                placement = None
                flags.append("placement_reset")
                items.append(f"{od.id}: its view or side changed, so its placement was reset")
            kw: dict[str, Any] = {
                "id": od.id,
                "origin": od.origin,
                "state": od.state,
                "placement": placement,
                "override": od.override,
            }
            if od.places_source == "user":
                kw.update(places=od.places, places_source="user")
            if "user_tolerance" in od.flags:
                kw.update(tolerance=od.tolerance, tolerance_values=od.tolerance_values)
            if "user_frame" in od.flags:
                kw.update(frame=od.frame)
            changed = abs(nd.value - od.value) > 1e-12 or any(f in resized_ids for f in nd.features)
            if changed:
                flags.append("changed")
                counts["changed"] += 1
            else:
                counts["unchanged"] += 1
            rec = replace(nd, flags=tuple(flags), **kw)
            if rec.state == "removed":
                off_sheet.append(raw.id)
        else:
            ident = f"d-{next_d}"
            next_d += 1
            rec = replace(nd, id=ident, placement=None, override=None, flags=(*nd.flags, "new"))
            counts["new"] += 1
        sheet_ids[raw.id] = rec.id
        dims.append(rec)
    kept_user = 0
    for od in old.dimensions:
        if od.key in taken:
            continue
        od = document.as_record(od)
        own = tuple(f for f in od.flags if f not in _MERGE_FLAGS)
        if od.origin == "user":
            refs = set(od.features) | {f for p in od.positions for f in p.features}
            if refs <= merged_ids:
                dims.append(replace(od, flags=own))
                counts["unchanged"] += 1
                kept_user += 1
            else:
                dims.append(replace(od, flags=(*own, "needs_attention")))
                attention += 1
                missing = ", ".join(sorted(refs - merged_ids))
                items.append(f"{od.id} ({od.key}) needs attention: its features are gone ({missing})")
        elif od.state == "removed":
            counts["forgotten"] += 1
        else:
            counts["dropped"] += 1
            items.append(f"{od.id} ({od.key}) was dropped: what it dimensioned is gone")
    if kept_user:
        items.append(
            f"{kept_user} user dimension{'s' if kept_user != 1 else ''} kept; "
            "the sheet shows them when it is laid out again"
        )

    sheet = document.remap_sheet(new.sheet, sheet_ids, off_sheet)
    scale = old.options.scale
    if (
        isinstance(new.sheet, document.display.Sheet)
        and scale != "auto"
        and tuple(new.sheet.scale) != tuple(scale)
    ):
        items.append(f"the frozen scale {scale[0]}:{scale[1]} no longer fits: Change Scale")
    title = _follow_part(old.title, dict(new.title), items)
    next_ids = dict(old.next_id)
    next_ids["f"] = next_f
    next_ids["d"] = next_d
    next_ids["v"] = max(next_ids.get("v", 1), dict(new.next_id).get("v", 1))
    merged = replace(
        document.as_document(old),
        model=_identity(om, nm, extents=True),
        title=title,
        features=tuple(features),
        datums=tuple(datums),
        dimensions=tuple(dims),
        next_id=tuple(next_ids.items()),
        sheet=sheet,
        checks=new.checks,
        coverage=new.coverage,
        warnings=new.warnings,
    )
    for f in gone:
        items.append(f"feature {f.id} ({f.descriptor.type}) is gone")
    report = MergeReport(
        unchanged=counts["unchanged"],
        changed=counts["changed"],
        new=counts["new"],
        dropped=counts["dropped"],
        attention=attention,
        forgotten=counts["forgotten"],
        features_matched=len(m.pairs),
        features_resized=tuple(resized),
        features_gone=tuple(f.id for f in gone),
        features_new=tuple(added),
    )
    return _finish(merged, report, items)


def _laid_out(drawing: types.Drawing, src: Any, limits: DrawingLimits) -> types.Drawing:
    """``drawing`` (a revision just started) laid out with its model, stamp and all."""
    from . import edit

    edit.attach(drawing, src, limits=limits)
    return edit.relayout(drawing, limits=limits)[0]


def regenerate(
    drawing: types.Drawing,
    source: Any = None,
    *,
    new: types.Drawing | None = None,
    drawing_path: str | os.PathLike | None = None,
    catalog: Any = None,
    limits: DrawingLimits = DEFAULT_LIMITS,
    revision: str | None = None,
    revision_zones: Iterable[str] = (),
    drawn_by: str | None = None,
    today: Any = None,
    **_kw: Any,
) -> tuple[types.Drawing, MergeReport]:
    """Update ``drawing`` from its model, keeping the user's edits (13.5). ``source`` is
    the model: a path, an open SOLIDWORKS document or a ``DrawingSource``; without it
    the model is looked for from ``drawing_path`` (:mod:`.locate`), which takes only a
    file whose hash matches; when there is none, ``ModelNotFoundError`` (an
    ``InvalidArgumentError``, code and rule ``model_not_found``) says so (a changed
    file is offered by the lookup, never taken). ``new`` merges a run made elsewhere
    instead of running the pipeline. A RELEASED drawing raises the
    ``drawing_released`` error, unless ``revision`` is given: then its next revision is
    started first (``release.start_revision`` with ``revision`` as the description,
    ``revision_zones``, ``drawn_by`` and ``today``) and laid out with the model as
    found, so a released drawing whose model changed can be revised in one step (the
    sheet of the revision is never left unstamped)."""
    from . import locate, pipeline
    from .source import DrawingSource, open_source

    _check(drawing, "drawing")
    opened = revision is not None
    if opened:
        drawing = release.start_revision(drawing, revision, revision_zones, drawn_by=drawn_by, today=today)
    release.require_editable(drawing, "it must start a revision before Update from Model")
    if new is not None:
        return merge(drawing, new)
    if source is None:
        if drawing_path is None:
            raise ModelNotFoundError(
                "name the model, or the drawing's path to look for it from",
                detail={"parameter": "source", "rule": "model_not_found"},
            )
        found = locate.find_model(drawing_path, drawing.model or {}, catalog=catalog)
        if found.found is None:
            changed = [c.path for c in found.candidates if not c.matches]
            words = "the drawing's model was not found"
            if changed:
                n = len(changed)
                words += f"; {n} file{'s' if n != 1 else ''} found changed since the drawing was made"
            raise ModelNotFoundError(words, detail={"parameter": "source", "rule": "model_not_found"})
        source = found.found.path
    settings = _settings(drawing)
    model = drawing.model or {}
    units = drawing.options.units if drawing.options.units in ("in", "mm") else None
    if isinstance(source, DrawingSource):
        src = source
    else:
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
            source, configuration=model.get("configuration"), units=units, title_names=names, limits=limits
        )
    if same_file(model, src):
        report = MergeReport(model_unchanged=True, items=(MODEL_UNCHANGED,))
        return (_laid_out(drawing, src, limits), report) if opened else (drawing, report)
    if model.get("geometry") and src.geometry_digest == model.get("geometry"):
        identity = document.model_identity(src, settings, None)
        taken, report = take_reference(drawing, identity, document.part_title_fields(src, settings, limits))
        return (_laid_out(taken, src, limits), report) if opened else (taken, report)
    typed = {k: f.text for k, f in drawing.title if f.source == "typed"}
    part = source if not isinstance(source, DrawingSource) else None
    run = pipeline.run(
        part,
        options=drawing.options,
        fields=typed,
        settings=settings,
        limits=limits,
        stages={"source": lambda *_a, **_k: src},
    )
    merged, report = merge(drawing, run.drawing)
    if run.orchestrated is None or report.model_unchanged or report.geometry_unchanged:
        return merged, report
    # the new run is kept beside the merged drawing, which is laid out again with the
    # user's placements, removals and overrides applied (the merged sheet is the new run's)
    from . import edit

    edit.move_live(run.drawing, merged)
    merged, _checks = edit.relayout(merged, limits=limits)
    return merged, report


__all__ = ["GEOMETRY_UNCHANGED", "MODEL_UNCHANGED", "MergeReport", "merge", "regenerate", "take_reference"]
