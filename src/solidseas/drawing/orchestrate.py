"""The plan and layout loop: the pipeline's ``plan`` stage (``docs/DRAWINGS.md``
6.9, 10, 11).

:func:`plan_and_layout` takes everything the earlier stages made and gives the
:class:`~solidseas.drawing.types.Plan`, the laid-out
:class:`~solidseas.drawing.display.Sheet` and the feature set the plan's ids refer
to, which the assemble stage keeps as the drawing's feature table:

1. the drawing's unit (the options, the Settings, the part);
2. the front view (8.2) when neither the options nor the Settings fix it; the
   views are drawn again when the chosen front differs from the one drawn;
3. the plan (:mod:`.plan`, an assembly's :mod:`.plan.assembly`) and its layout
   (:mod:`.layout`), of the key dimensions only when the plan asks for more than a
   sheet shows clearly (10.10, :mod:`.plan.keep`; an assembly has none);
4. once more with ordinate dimensions where layout found a band of baseline
   locations deeper than the Settings allow (10.4);
5. once more with fewer dimensions when the layout still puts text on text and the
   time bounds leave room for it, kept when it collides less.

The plan and the layout each keep to their seconds in :class:`~.limits.DrawingLimits`.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, replace

from ..errors import UnsupportedOperationError
from .assembly import is_assembly
from .layout import LayoutResult, layout
from .limits import DEFAULT_LIMITS, DrawingLimits
from .plan import Context, Planned, keep, make_plan
from .plan.assembly import make_plan as assembly_plan
from .plan.select import choose_front, frame_of
from .plan.values import unit_for
from .types import DrawingOptions, settings_type


def _front_drawn(views) -> tuple | None:
    for spec, _geom in views:
        if spec.kind == "base":
            r, u, d = spec.frame()
            return d, u
    return None


def read_logo(settings, limits: DrawingLimits = DEFAULT_LIMITS) -> bytes | None:
    """The company logo beside Drawing Settings when its hash is the one the settings
    record, else None (it is checked again by the writers)."""
    from .settings import LOGO_NAME, logo_problem, settings_folder

    sha = settings.company.logo
    if not sha:
        return None
    path = os.path.join(settings_folder(), LOGO_NAME)
    try:
        with open(path, "rb") as fh:
            data = fh.read(limits.logo_bytes + 1)
    except OSError:
        return None
    if logo_problem(data, sha) is not None:
        return None
    return data


@dataclass(frozen=True)
class Orchestrated:
    """What one plan and layout made: the plan with its detail, the layout with its
    checks, and the options and views it settled on (the front may have changed)."""

    planned: Planned
    result: LayoutResult
    options: DrawingOptions
    views: tuple
    raw: Planned | None = None  # the plan before ``adjust``, which a later layout may reuse


def run(
    source,
    model,
    features,
    views,
    options,
    settings,
    fields=None,
    limits: DrawingLimits = DEFAULT_LIMITS,
    *,
    logo: bytes | None = None,
    ids=None,
    decisions=None,
    make_views=None,
    planned: Planned | None = None,
    adjust=None,
    revisions=(),
    status: str = "PRELIMINARY",
    signed: dict[str, tuple[str, str]] | None = None,
    named=frozenset(),
) -> Orchestrated:
    """Plan and lay out a drawing, keeping everything each step made. ``make_views``
    draws the views again for a front chosen here (the views stage by default; when
    this SolidSeas has none, the views drawn are kept).

    For a drawing laid out again after an edit (:mod:`.edit`): ``planned`` is a plan
    made before with the same choices, laid out again without planning; ``adjust``
    turns each plan into the one laid out (the drawing's records applied to it); and
    ``revisions``, ``status`` and ``signed`` fill the revision block, the stamp and the
    approval rows. ``signed`` defaults to DRAWN from ``fields["drawn_by"]``. ``named``
    holds the ids of the features the drawing's own dimensions name, which a plan of
    the key dimensions keeps (:mod:`.plan.keep`)."""
    t0 = time.perf_counter()
    fields = dict(fields or {})
    unit = unit_for(source, options, settings)
    views = tuple(views)
    hints = tuple(getattr(source, "hints", ()) or ())
    ctx = Context(
        model, features, views, options, settings, unit=unit, hints=hints, decisions=dict(decisions or {})
    )
    if ids:
        ctx = Context(
            model,
            features,
            views,
            options,
            settings,
            unit=unit,
            ids=tuple(ids),
            hints=hints,
            decisions=dict(decisions or {}),
        )
    default_front = settings.defaults.views[settings_type(options.process)]["front"]
    if options.front is None and default_front == "auto":
        choice = choose_front(ctx)
        _r, up, d = frame_of(choice.front, choice.turn)
        drawn = _front_drawn(views)
        moved = drawn is not None and (
            max(abs(a - b) for a, b in zip(drawn[0], d, strict=True)) > 1e-9
            or max(abs(a - b) for a, b in zip(drawn[1], up, strict=True)) > 1e-9
        )
        if moved and make_views is None:
            from .pipeline import STAGES, resolve

            try:
                make_views = resolve("views", dict(STAGES)["views"])
            except UnsupportedOperationError:
                make_views = None
        if moved and make_views is not None:
            options = replace(options, front=choice.front, turn=choice.turn)
            views = tuple(make_views(model, features, options, settings))
            ctx = replace(ctx, views=views, options=options, ids=ctx.ids)
    reused = planned is not None
    full = None  # every requirement, which a key-dimensions plan keeps from
    if planned is None and is_assembly(source):
        planned = assembly_plan(ctx, source, fields, limits=limits)  # no dimensions to keep from
    elif planned is None:
        ctx = keep.lettering(ctx, named)
        planned = make_plan(ctx, source, fields, limits=limits)
        full = (ctx, planned)
        if len(planned.plan.dimensions) > keep.BUDGET:
            trimmed = keep.trim(ctx, planned, keep.BUDGET, named)
            if trimmed is not None:
                ctx = trimmed
                planned = make_plan(ctx, source, fields, limits=limits)
    if is_assembly(source):
        # with the hidden lines of any part hidden behind others, which its balloon ends on
        views = planned.detail.ctx.views
    if time.perf_counter() - t0 > limits.seconds_plan:
        raise limits.exceeded("seconds_plan", "planning the dimensions took longer than a drawing allows")
    if logo is None:
        logo = read_logo(settings, limits)
    sha = hashlib.sha256(logo).hexdigest() if logo else ""
    t1 = time.perf_counter()
    if signed is None:
        signed = {}
        if fields.get("drawn_by"):
            signed["DRAWN"] = (fields["drawn_by"], fields.get("drawn_date", ""))

    def lay(made: Planned) -> LayoutResult:
        return layout(
            adjust(made) if adjust is not None else made,
            options=options,
            settings=settings,
            source=source,
            fields=fields,
            logo=logo,
            logo_sha=sha,
            revisions=revisions,
            status=status,
            signed=signed,
            sheets=limits.sheets,
            seconds=limits.seconds_layout - (time.perf_counter() - t1),
        )

    raw = planned
    result = lay(planned)
    if result.deep and not reused:
        raw = make_plan(ctx, source, fields, deep=result.deep, limits=limits)
        result = lay(raw)
    # Text still on text: once more with fewer dimensions, kept when it collides less. A
    # plan and a layout of fewer dimensions cost less than what came before them, so the
    # retry runs only while each bound has at least as much left as was spent: the
    # stage's from t0 and the layouts' from t1, so that the retry keeps within both.
    drawn = len(raw.plan.dimensions)
    now = time.perf_counter()
    if (
        full is not None
        and keep.crowded(drawn, result.checks)
        and 2 * (now - t0) < limits.seconds_plan
        and 2 * (now - t1) < limits.seconds_layout
    ):
        trimmed = keep.trim(full[0], full[1], int(drawn * keep.SHRINK), named)
        if trimmed is not None:
            fewer = make_plan(trimmed, source, fields, deep=result.deep, limits=limits)
            again = lay(fewer)
            if keep.collisions(again.checks) < keep.collisions(result.checks):
                raw, result = fewer, again
    if time.perf_counter() - t1 > limits.seconds_layout:
        raise limits.exceeded("seconds_layout", "laying the drawing out took longer than a drawing allows")
    laid = adjust(raw) if adjust is not None else raw
    return Orchestrated(drawn_in(laid, result), result, options, views, raw)


def drawn_in(planned: Planned, result: LayoutResult) -> Planned:
    """``planned`` naming the view each dimension is drawn in: a datum symbol the layout
    drew in another view the plan offered (its own had no clear place) is recorded
    there, with that view's sheet axis, so that the drawing, its checks and its sheet
    agree. ``planned`` itself, which a later layout may reuse, is left as it was."""
    if not result.views:
        return planned
    moved = result.views
    plan = replace(
        planned.plan,
        dimensions=tuple(
            replace(d, view=moved[d.id][0]) if d.id in moved else d for d in planned.plan.dimensions
        ),
    )
    sheet_axis = dict(planned.detail.sheet_axis)
    sheet_axis.update({did: sa for did, (_v, sa) in moved.items()})
    return Planned(plan, replace(planned.detail, sheet_axis=sheet_axis))


class Staged(tuple):
    """The plan stage's ``(plan, sheet, features)``, carrying the :class:`Orchestrated`
    that made them as ``done``, so the pipeline can keep the run beside the drawing
    for its checks and for editing."""

    done: Orchestrated | None = None


def plan_and_layout(
    source, model, features, views, options, settings, fields=None, limits: DrawingLimits = DEFAULT_LIMITS
):
    """(plan, sheet, features): the pipeline's plan stage, as a :class:`Staged`."""
    done = run(source, model, features, views, options, settings, fields, limits)
    out = Staged((done.planned.plan, done.result.sheet, features))
    out.done = done
    return out


__all__ = ["Orchestrated", "Staged", "drawn_in", "plan_and_layout", "read_logo", "run"]
