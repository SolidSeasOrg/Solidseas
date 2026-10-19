"""``make_drawing``: the stages in order, each found by its dotted path
(``docs/DRAWINGS.md`` 6.9).

A stage another branch has not built yet is a capability gap: asking for it
raises ``not_implemented`` with rule ``stage_missing`` and the stage's name, so
the core is complete and testable alone and each branch drives its own stage with
hand-built inputs. A module that exists but fails to import is a bug and is
raised as it is, never taken for a gap.

The stages and what each takes and returns (the contracts are in :mod:`.types`):

| Stage | Path | Takes | Returns |
|---|---|---|---|
| source | ``solidseas.drawing.source:open_source`` | the part | ``DrawingSource`` |
| model | ``solidseas.drawing.facegraph:from_bodies`` | the source's bodies | ``BrepModel`` |
| features | ``solidseas.drawing.features:recognise`` | the model | ``FeatureSet`` |
| views | ``solidseas.drawing.views:make_views`` | model, features, options | view geometry |
| plan | ``solidseas.drawing.orchestrate:plan_and_layout`` | everything above | ``Plan`` and ``Sheet`` |
| assemble | ``solidseas.drawing.document:new_drawing`` | the plan and sheet | ``Drawing`` |

Each stage's seconds come from :class:`~.limits.DrawingLimits`; the run as a whole
stops at ``seconds_total``.

An assembly (:mod:`.assembly`) runs the same stages: its source holds the placed
bodies of its instances, which the model stage tessellates once a part; it has no
features to recognise; it takes the assembly's own view defaults
(:func:`.assembly.assembly_options`); and the plan stage plans its parts list and
balloons in place of dimensions.
"""

from __future__ import annotations

import importlib
import importlib.util
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..errors import InvalidArgumentError, UnsupportedOperationError
from .assembly import assembly_options, is_assembly
from .limits import DEFAULT_LIMITS, DrawingLimits
from .types import DrawingOptions, FeatureSet

STAGES: tuple[tuple[str, str], ...] = (
    ("source", "solidseas.drawing.source:open_source"),
    ("model", "solidseas.drawing.facegraph:from_bodies"),
    ("features", "solidseas.drawing.features:recognise"),
    ("views", "solidseas.drawing.views:make_views"),
    ("plan", "solidseas.drawing.orchestrate:plan_and_layout"),
    ("assemble", "solidseas.drawing.document:new_drawing"),
)
STAGE_SECONDS = {
    "source": "seconds_source",
    "model": "seconds_tessellation",
    "features": "seconds_features",
    "views": "seconds_views",
    "plan": "seconds_plan",
}
# Other entry points of the public API and where they will live.
ENTRY_POINTS: dict[str, str] = {
    "load": "solidseas.drawing.document:load",
    "save": "solidseas.drawing.document:save",
    "regenerate": "solidseas.drawing.merge:regenerate",
    "write_pdf": "solidseas.drawing.pdf:write_pdf",
    "write_dxf": "solidseas.drawing.dxf:write_dxf",
    "edit": "solidseas.drawing.edit",
    "checks": "solidseas.drawing.checks:run_checks",
}


def stage_missing(name: str) -> UnsupportedOperationError:
    return UnsupportedOperationError(
        f"this SolidSeas cannot make drawings yet: the {name} stage is not built",
        detail={"rule": "stage_missing", "value": name},
    )


def resolve(name: str, path: str) -> Any:
    """The object at ``path`` (``package.module:attribute``, or a module alone), or a
    ``stage_missing`` error naming ``name`` when its module or attribute does not
    exist."""
    module_name, _, attr = path.partition(":")
    try:
        found = importlib.util.find_spec(module_name)
    except ModuleNotFoundError:
        found = None
    if found is None:
        raise stage_missing(name)
    module = importlib.import_module(module_name)
    if not attr:
        return module
    obj = getattr(module, attr, None)
    if obj is None:
        raise stage_missing(name)
    return obj


def available() -> dict[str, bool]:
    """Which stages and entry points this SolidSeas has, by name."""
    out = {}
    for name, path in (*STAGES, *ENTRY_POINTS.items()):
        try:
            resolve(name, path)
            out[name] = True
        except UnsupportedOperationError:
            out[name] = False
    return out


@dataclass(frozen=True)
class Run:
    """What a run made, stage by stage, for the stages that ran: kept so a test or
    the wizard can look at each stage's output and time."""

    source: Any = None
    model: Any = None
    features: Any = None
    views: Any = None
    plan: Any = None
    drawing: Any = None
    seconds: tuple[tuple[str, float], ...] = ()
    orchestrated: Any = None  # the plan stage's run (plan detail, layout and its checks), when it kept one


def run(
    part: Any,
    *,
    options: DrawingOptions | None = None,
    fields: Mapping[str, str] | None = None,
    settings: Any = None,
    limits: DrawingLimits = DEFAULT_LIMITS,
    stages: Mapping[str, Callable[..., Any]] | None = None,
    until: str | None = None,
) -> Run:
    """Run the stages on ``part`` (a path or an open SOLIDWORKS ``Document``), stopping
    after ``until`` when it is given. ``stages`` replaces a stage by name with a
    callable of the same signature (tests and branches drive their own stage)."""
    from .settings import DrawingSettings

    options = options or DrawingOptions()
    if not isinstance(options, DrawingOptions):
        raise InvalidArgumentError("options must be DrawingOptions", detail={"parameter": "options"})
    if not isinstance(limits, DrawingLimits):
        raise InvalidArgumentError("limits must be DrawingLimits", detail={"parameter": "limits"})
    settings = settings if settings is not None else DrawingSettings()
    if not isinstance(settings, DrawingSettings):
        raise InvalidArgumentError("settings must be DrawingSettings", detail={"parameter": "settings"})
    fields = dict(fields or {})
    for key, value in fields.items():
        if not isinstance(key, str) or not isinstance(value, str) or len(value) > limits.title_chars:
            raise InvalidArgumentError(
                f"title field {key!r} must be text of at most {limits.title_chars} characters",
                detail={"parameter": "fields"},
            )
    names = [n for n, _p in STAGES]
    if until is not None and until not in names:
        raise InvalidArgumentError(f"until must be one of {', '.join(names)}", detail={"parameter": "until"})
    override = dict(stages or {})
    unknown = set(override) - set(names)
    if unknown:
        raise InvalidArgumentError(
            f"there is no stage {sorted(unknown)[0]!r}", detail={"parameter": "stages"}
        )

    def stage(name: str) -> Callable[..., Any]:
        if name in override:
            return override[name]
        return resolve(name, dict(STAGES)[name])

    start = time.perf_counter()
    seconds: list[tuple[str, float]] = []
    made: dict[str, Any] = {}
    title_names = tuple(
        n
        for group in ("part_number", "number", "title", "revision", "model_revision", "material", "finish")
        for n in getattr(settings.title_sources, group)
    )
    units = None if options.units == "part" else options.units
    calls: dict[str, Callable[[], Any]] = {
        "source": lambda: stage("source")(
            part,
            configuration=options.configuration,
            bodies=options.bodies,
            units=units,
            title_names=title_names,
            limits=limits,
        ),
        "model": lambda: stage("model")(
            made["source"].selected_bodies(), name=made["source"].name, quality=options.quality, limits=limits
        ),
        "features": lambda: (
            FeatureSet()
            if is_assembly(made["source"]) and "features" not in override
            else stage("features")(made["model"])
        ),
        "views": lambda: stage("views")(made["model"], made["features"], options, settings),
        "plan": lambda: stage("plan")(
            made["source"], made["model"], made["features"], made["views"], options, settings, fields, limits
        ),
        "assemble": lambda: stage("assemble")(made["source"], made["plan"], options, settings, fields),
    }
    for name in names:
        t0 = time.perf_counter()
        made[name] = calls[name]()
        if name == "source" and is_assembly(made[name]):
            options = assembly_options(options)
        took = time.perf_counter() - t0
        seconds.append((name, took))
        bound = STAGE_SECONDS.get(name)
        if bound is not None and took > getattr(limits, bound):
            raise limits.exceeded(bound, f"the {name} stage took longer than a drawing allows")
        if time.perf_counter() - start > limits.seconds_total:
            raise limits.exceeded("seconds_total", "the drawing took longer than a drawing allows")
        if name == until:
            break
    done = getattr(made.get("plan"), "done", None)
    drawing = made.get("assemble")
    if drawing is not None and done is not None and "assemble" not in override:
        # the checks of 20.1 on the new drawing, and the run kept beside it for editing
        from . import edit

        drawing = edit.adopt(drawing, made["source"], made["model"], made["features"], done, fields)
    if drawing is not None and hasattr(drawing, "seconds") and not getattr(drawing, "seconds", ()):
        from dataclasses import replace

        drawing = replace(drawing, seconds=tuple(seconds))
    return Run(
        source=made.get("source"),
        model=made.get("model"),
        features=made.get("features"),
        views=made.get("views"),
        plan=made.get("plan"),
        drawing=drawing,
        seconds=tuple(seconds),
        orchestrated=done,
    )


def make_drawing(
    part: Any,
    *,
    options: DrawingOptions | None = None,
    fields: Mapping[str, str] | None = None,
    settings: Any = None,
    limits: DrawingLimits = DEFAULT_LIMITS,
) -> Any:
    """A PRELIMINARY drawing of ``part`` (14). Until every stage is built this raises
    ``not_implemented`` with rule ``stage_missing`` and the first missing stage."""
    return run(part, options=options, fields=fields, settings=settings, limits=limits).drawing


__all__ = ["ENTRY_POINTS", "STAGES", "Run", "available", "make_drawing", "resolve", "run", "stage_missing"]
