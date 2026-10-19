"""The plan stage (docs/DRAWINGS.md 6.9): the pipeline runs it, it chooses the front
and draws the views again when the front moves, re-plans ordinate dimensions when a
band is too deep, keeps to its time bounds and finds the company logo."""

import hashlib
from dataclasses import replace

import pytest

from drawing_plan_fixtures import plate
from drawing_support import tiny_png
from solidseas.drawing import display as D
from solidseas.drawing import orchestrate, pipeline
from solidseas.drawing import settings as S
from solidseas.drawing.limits import DrawingLimits
from solidseas.drawing.types import DrawingOptions, Plan
from solidseas.errors import SldLimitError


class _Source:
    name = "FOUR-HOLES.SLDPRT"
    configuration = None
    material = None
    sha256 = None
    hints = ()
    properties = ()

    def __init__(self, model):
        self._model = model

    def selected_bodies(self):
        return []

    def property(self, *names):
        return None


def _stages(ctx):
    return {
        "source": lambda part, **kw: _Source(ctx.model),
        "model": lambda bodies, **kw: ctx.model,
        "features": lambda m: ctx.features,
        "views": lambda m, fs, o, s: ctx.views,
    }


def test_the_pipeline_runs_the_plan_stage():
    ctx = plate("four_holes", patterns=[("scattered", [0, 1, 2, 3])])
    assert pipeline.available()["plan"]
    run = pipeline.run("four-holes.SLDPRT", stages=_stages(ctx), until="plan")
    plan, sheet, features = run.plan
    assert isinstance(plan, Plan) and isinstance(sheet, D.Sheet) and features is ctx.features
    assert [s for s, _t in run.seconds] == ["source", "model", "features", "views", "plan"]
    assert sheet.name == "B" and any(isinstance(a, D.Dimension) for a in sheet.annotations)


def test_a_new_front_draws_the_views_again(monkeypatch):
    ctx = plate("four_holes", patterns=[("scattered", [0, 1, 2, 3])])
    # the views drawn from below: the front the planner chooses looks at the holes' entries
    upside = tuple(
        (replace(s, direction=(0.0, 0.0, -1.0)) if s.kind == "base" else s, g) for s, g in ctx.views
    )
    calls = []

    def make_views(m, fs, options, settings):
        calls.append((options.front, options.turn))
        return ctx.views

    done = orchestrate.run(
        None, ctx.model, ctx.features, upside, ctx.options, ctx.settings, make_views=make_views
    )
    assert calls == [("+z", 0)] and done.options.front == "+z"

    def missing(name, path):
        raise pipeline.stage_missing(name)

    monkeypatch.setattr(pipeline, "resolve", missing)
    kept = orchestrate.run(None, ctx.model, ctx.features, upside, ctx.options, ctx.settings, make_views=None)
    assert kept.options.front is None  # no views stage: the views drawn are kept


def test_a_band_too_deep_is_drawn_as_ordinates():
    ctx = plate("four_holes", patterns=[("scattered", [0, 1, 2, 3])])
    done = orchestrate.run(None, ctx.model, ctx.features, ctx.views, ctx.options, ctx.settings)
    kinds = {d.kind for d in done.planned.plan.dimensions if d.role == "feature_location"}
    # four locations a side, each a track deep, are more than a quarter of a 60 mm view
    assert kinds == {"ordinate"}
    base = orchestrate.run(
        None,
        ctx.model,
        ctx.features,
        ctx.views,
        DrawingOptions(arrangement=(("v-1/x", "baseline"), ("v-1/y", "baseline"))),
        ctx.settings,
    )
    assert {
        d.kind for d in base.planned.plan.dimensions if d.role == "feature_location" and d.view == "v-1"
    } == {"linear"}


def test_the_time_bounds_hold():
    ctx = plate("four_holes")
    with pytest.raises(SldLimitError) as info:
        orchestrate.run(
            None,
            ctx.model,
            ctx.features,
            ctx.views,
            ctx.options,
            ctx.settings,
            limits=DrawingLimits(seconds_plan=1e-9),
        )
    assert info.value.detail["limit"] == "seconds_plan"
    with pytest.raises(SldLimitError) as info:
        orchestrate.run(
            None,
            ctx.model,
            ctx.features,
            ctx.views,
            ctx.options,
            ctx.settings,
            limits=DrawingLimits(seconds_layout=1e-9),
        )
    assert info.value.detail["limit"] == "seconds_layout"


def test_the_logo_is_read_only_when_its_hash_matches(tmp_path, monkeypatch):
    png = tiny_png()
    (tmp_path / S.LOGO_NAME).write_bytes(png)
    monkeypatch.setattr(S, "settings_folder", lambda *a, **k: str(tmp_path))
    good = S.with_value(S.DrawingSettings(), "company", "logo", hashlib.sha256(png).hexdigest())
    assert orchestrate.read_logo(good) == png
    other = S.with_value(S.DrawingSettings(), "company", "logo", "0" * 64)
    assert orchestrate.read_logo(other) is None
    assert orchestrate.read_logo(S.DrawingSettings()) is None
    ctx = plate("four_holes")
    done = orchestrate.run(None, ctx.model, ctx.features, ctx.views, ctx.options, good)
    images = [a for a in done.result.sheet.annotations if isinstance(a, D.Image)]
    assert len(images) == 1 and images[0].png == png
