"""Key dimensions only (docs/DRAWINGS.md 10.10): a part that asks for more dimensions than
a sheet shows clearly gets a drawing of the key ones (the overall size, the datums, the
holes with their locations and the larger features) and leaves the rest to the model,
with the model-governs note; a layout that still puts text on text is laid out once
more with fewer, kept when it collides less."""

import functools
from dataclasses import replace

import drawing_parts
from drawing_golden_support import settings, source_stage
from solidseas.drawing import orchestrate, pipeline
from solidseas.drawing.facegraph import OtherSurface
from solidseas.drawing.layout.checks import LayoutCheck
from solidseas.drawing.limits import DrawingLimits
from solidseas.drawing.plan import keep, make_plan
from solidseas.drawing.plan.context import Context
from solidseas.drawing.types import DrawingOptions, Pocket, Width

MM = 1e-3
OPTIONS = DrawingOptions(units="mm")


def _stage():
    xt, truth = drawing_parts.pockets_plate()
    return source_stage("pockets", xt, truth)


@functools.cache
def _views() -> pipeline.Run:
    """The pockets plate up to its views, made once."""
    return pipeline.run(
        None, options=OPTIONS, settings=settings(), stages={"source": _stage()}, until="views"
    )


def _draw(**kw) -> orchestrate.Orchestrated:
    run = _views()
    return orchestrate.run(run.source, run.model, run.features, run.views, OPTIONS, settings(), **kw)


def _depths(fs, which) -> list[float]:
    """The depths (mm) of the pockets among the features ``which`` (indices)."""
    return sorted(round(fs.features[k].depth / MM, 3) for k in which if isinstance(fs.features[k], Pocket))


def _reduced(plan) -> bool:
    return any(n.text.startswith("REDUCED-DIMENSION DRAWING") for n in plan.notes)


def test_engraved_letters_are_left_to_the_model_but_for_their_depth():
    # pockets cut to one depth from one face, with a font's free-form walls, read as
    # lettering: no stroke widths or places, one depth with its count
    xt, truth = drawing_parts.letters_plate()
    stage = source_stage("letters", xt, truth)
    run = pipeline.run(None, options=OPTIONS, settings=settings(), stages={"source": stage}, until="views")
    fs = run.features
    pockets = frozenset(k for k, f in enumerate(fs.features) if isinstance(f, Pocket))
    assert len(pockets) == 4
    plain = Context(run.model, fs, tuple(run.views), OPTIONS, settings())
    assert keep.lettering(plain) is plain  # four plain pockets are pockets
    faces = list(run.model.faces)
    for k in pockets:
        w = fs.features[k].walls[0]
        faces[w] = replace(faces[w], surface=OtherSurface("b_surface"))
    model = replace(run.model, faces=tuple(faces))
    ctx = keep.lettering(Context(model, fs, tuple(run.views), OPTIONS, settings()))
    assert ctx.features.lettering == pockets
    assert pockets < ctx.features.model_defined  # with the widths across them
    plan = make_plan(ctx).plan
    depths = [d for d in plan.dimensions if d.key.startswith("depth/")]
    assert len(depths) == 1
    (depth,) = depths
    assert depth.kind == "linear" or depth.suffix[0].startswith("4X ")
    left = {ctx.ids[k] for k in ctx.features.model_defined}
    assert not [d for d in plan.dimensions if d is not depth and set(d.features) & left]
    assert _reduced(plan)


def test_a_plan_within_the_budget_is_drawn_whole():
    done = _draw()
    fs = done.planned.detail.ctx.features
    assert len(done.planned.plan.dimensions) <= keep.BUDGET
    assert fs.model_defined == frozenset() and fs.coverage.complete and not fs.unclaimed
    assert not _reduced(done.planned.plan)


def test_more_dimensions_than_the_budget_keeps_the_key_ones(monkeypatch):
    monkeypatch.setattr(keep, "BUDGET", 20)
    run = pipeline.run(None, options=OPTIONS, settings=settings(), stages={"source": _stage()})
    plan = run.orchestrated.planned.plan
    fs = run.orchestrated.planned.detail.ctx.features
    assert len(plan.dimensions) <= 20
    # the overall size along each axis, the datums, and the corner holes with their pattern
    assert sum(1 for d in plan.dimensions if d.role == "envelope") == 3
    assert sum(1 for d in plan.dimensions if d.kind == "datum_feature") == 3
    assert [d.prefix[:3] for d in plan.dimensions if d.kind == "hole_callout"] == ["4X "]
    assert sum(1 for d in plan.dimensions if d.role == "pattern") == 2  # the pitches each way
    # the larger pockets are drawn and the smaller ones left to the model, the smallest among them
    kept = [k for k in range(len(fs.features)) if k not in fs.model_defined]
    every = _depths(fs, range(len(fs.features)))
    assert _depths(fs, kept) == every[: len(_depths(fs, kept))] and _depths(fs, kept)
    assert max(every) in _depths(fs, fs.model_defined)
    # a pocket is kept or left whole: with the widths across it
    for k, f in enumerate(fs.features):
        if isinstance(f, Pocket):
            across = [
                j
                for j, w in enumerate(fs.features)
                if isinstance(w, Width) and w.kind == "gap" and set(w.pair) <= set(f.walls)
            ]
            assert len(across) == 2 and {j in fs.model_defined for j in across} == {k in fs.model_defined}
    # a reduced-dimension drawing: the note, the coverage and the check that says so
    assert _reduced(plan) and not plan.coverage.complete
    assert {u.reason for u in fs.unclaimed} == {"model_defined"}
    assert plan.coverage.features_unclaimed == len(fs.model_defined)
    cov = [c for c in run.drawing.checks if c.code == "COV.unclaimed"]
    assert len(cov) == 1 and cov[0].level == "warning" and "model defined" in cov[0].message


def test_the_count_of_what_is_kept_is_the_plans():
    run = _views()
    ctx = Context(run.model, run.features, tuple(run.views), OPTIONS, settings())
    full = make_plan(ctx)
    for budget in (16, 20, 26, 32):
        trimmed = keep.trim(ctx, full, budget)
        assert trimmed is not None
        assert len(make_plan(trimmed).plan.dimensions) <= budget
    assert keep.trim(ctx, full, len(full.plan.dimensions)) is None  # everything fits: nothing left


def test_a_feature_left_to_the_model_is_neither_stated_nor_located():
    run = _views()
    fs = run.features
    k = next(k for k, f in enumerate(fs.features) if isinstance(f, Pocket))
    left = replace(fs, model_defined=frozenset({k}))
    assert [i for i, _f in left.of_type(Pocket)] == [i for i, _f in fs.of_type(Pocket) if i != k]
    whole = Context(run.model, fs, tuple(run.views), OPTIONS, settings())
    fid = whole.ids[k]
    assert any(fid in d.features for d in make_plan(whole).plan.dimensions)  # its depth
    ctx = Context(run.model, left, tuple(run.views), OPTIONS, settings())
    assert not any(fid in d.features for d in make_plan(ctx).plan.dimensions)


def test_a_feature_the_users_own_dimension_names_is_kept(monkeypatch):
    from solidseas.drawing import edit

    run = pipeline.run(None, options=OPTIONS, settings=settings(), stages={"source": _stage()})
    fs, ids = run.features, run.orchestrated.planned.detail.ctx.ids
    pockets = sorted((f.depth, k) for k, f in enumerate(fs.features) if isinstance(f, Pocket))
    smallest, largest = pockets[-1][1], pockets[0][1]
    # on the whole drawing, a distance from the largest pocket to the smallest
    distance = next(
        c for c in edit.candidates(run.drawing, (ids[largest], ids[smallest])) if c.kind == "distance"
    )
    drawing, _checks = edit.add(run.drawing, distance)
    # planned again under a budget that leaves the smallest pocket to the model
    monkeypatch.setattr(keep, "BUDGET", 20)
    edit.live_for(drawing).key = None
    drawing, _checks = edit.relayout(drawing)
    left = edit.live_for(drawing).planned.detail.ctx.features.model_defined
    assert left and smallest not in left
    (user,) = [r for r in drawing.dimensions if r.origin == "user"]
    assert user.state == "shown" and "needs_attention" not in user.flags


def test_planned_again_a_key_dimensions_drawing_leaves_the_same_features(monkeypatch):
    from solidseas.drawing import edit

    monkeypatch.setattr(keep, "BUDGET", 20)
    run = pipeline.run(None, options=OPTIONS, settings=settings(), stages={"source": _stage()})
    first = run.orchestrated.planned.detail.ctx.features.model_defined
    drawing = run.drawing
    assert first and any(dict(f.decisions).get("datum") for f in drawing.features)  # letters recorded
    edit.live_for(drawing).key = None
    drawing, _checks = edit.relayout(drawing)
    assert edit.live_for(drawing).planned.detail.ctx.features.model_defined == first


def _noisy(monkeypatch, whole: int, fewer: int):
    """Layout as it is, with ``whole`` overlaps added to a plan of every dimension and
    ``fewer`` to one of the key ones; the dimension counts laid out are returned."""
    real = orchestrate.layout
    calls: list[int] = []

    def layout(made, **kw):
        result = real(made, **kw)
        calls.append(len(made.plan.dimensions))
        n = fewer if made.detail.ctx.features.model_defined else whole
        extra = [LayoutCheck("L.overlap", "noise", f"d-{j}") for j in range(n)]
        return replace(result, checks=list(result.checks) + extra)

    monkeypatch.setattr(orchestrate, "layout", layout)
    return calls


def test_a_layout_with_text_on_text_is_laid_out_once_more_with_fewer(monkeypatch):
    calls = _noisy(monkeypatch, 100, 0)
    done = _draw()
    # the last layout is the retry, with a share of the dimensions the one before drew
    assert len(calls) >= 2 and calls[-1] <= int(calls[-2] * keep.SHRINK)
    assert len(done.planned.plan.dimensions) == calls[-1]
    assert done.planned.detail.ctx.features.model_defined and _reduced(done.planned.plan)


def test_fewer_dimensions_that_collide_no_less_are_not_kept(monkeypatch):
    calls = _noisy(monkeypatch, 100, 1000)
    done = _draw()
    assert len(calls) >= 2 and calls[-1] < calls[-2] == len(done.planned.plan.dimensions)
    assert not done.planned.detail.ctx.features.model_defined and not _reduced(done.planned.plan)


class _Clock:
    """``time`` for the orchestrator: only a layout moves it, by ``step`` seconds."""

    def __init__(self, step: float) -> None:
        self.now, self.step = 0.0, step

    def perf_counter(self) -> float:
        return self.now


def _timed(monkeypatch, step: float) -> list[int]:
    """Layout as it is, taking ``step`` seconds by the orchestrator's clock, finding no
    band too deep, with 100 overlaps added to a plan of every dimension; the dimension
    counts laid out are returned."""
    real, clock = orchestrate.layout, _Clock(step)
    calls: list[int] = []

    def layout(made, **kw):
        result = real(made, **kw)
        clock.now += clock.step
        calls.append(len(made.plan.dimensions))
        n = 0 if made.detail.ctx.features.model_defined else 100
        extra = [LayoutCheck("L.overlap", "noise", f"d-{j}") for j in range(n)]
        return replace(result, checks=list(result.checks) + extra, deep=frozenset())

    monkeypatch.setattr(orchestrate, "layout", layout)
    monkeypatch.setattr(orchestrate, "time", clock)
    return calls


def test_the_retry_waits_for_room_in_the_layouts_time(monkeypatch):
    # a layout takes 6 s: the plan's 60 s would have room for another, the layouts' 10 s not
    calls = _timed(monkeypatch, 6.0)
    done = _draw(limits=DrawingLimits(seconds_plan=60.0, seconds_layout=10.0))
    assert len(calls) == 1 and not done.planned.detail.ctx.features.model_defined


def test_the_retry_runs_with_room_in_both_times(monkeypatch):
    calls = _timed(monkeypatch, 6.0)
    done = _draw(limits=DrawingLimits(seconds_plan=60.0, seconds_layout=20.0))
    assert len(calls) == 2 and done.planned.detail.ctx.features.model_defined


def test_a_few_collisions_are_not_crowded():
    overlap = LayoutCheck("L.overlap", "", "d-1")
    placed = LayoutCheck("L.placement", "", "d-2")
    other = LayoutCheck("L.leader", "", "d-3")
    assert not keep.crowded(10, [overlap, overlap, placed])  # three never are
    assert keep.crowded(10, [overlap, overlap, placed, placed])
    assert not keep.crowded(100, [overlap] * 4 + [other] * 5)  # under a twentieth of 100
    assert keep.crowded(100, [overlap] * 5)
