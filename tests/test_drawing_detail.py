"""A part's drawing at each detail level: simplified, complex and fully defined, on the
synthetic four-holes plate (a plate with four equal holes in a rectangle)."""

import functools
import json

import pytest

import drawing_golden_support as G
import drawing_parts
from solidseas.drawing import document, pipeline
from solidseas.drawing.types import DETAIL_LEVELS, DrawingOptions


@functools.cache
def drawn(detail: str):
    xt, truth = drawing_parts.four_holes_plate()
    stage = G.source_stage("four_holes_plate", xt, truth)
    options = DrawingOptions(units="in", detail=detail)
    return pipeline.run(None, options=options, settings=G.settings(), stages={"source": stage})


def _roles(run) -> list[str]:
    return sorted(d.role for d in run.drawing.dimensions)


def test_full_is_the_default_and_draws_as_before():
    assert DrawingOptions().detail == "full" and DETAIL_LEVELS == ("simplified", "complex", "full")
    run = drawn("full")
    assert run.drawing.options.effective_scheme == "datum" and run.plan[0].datums
    options = json.loads(document.dumps(run.drawing))["options"]
    assert "detail" not in options, "a fully defined drawing's options are as they were"


def test_complex_sizes_and_locates_every_feature_without_gdt():
    full, complex_ = drawn("full"), drawn("complex")
    assert complex_.drawing.options.effective_scheme == "plusminus" and not complex_.plan[0].datums
    assert not [d for d in complex_.drawing.dimensions if d.kind in ("datum_feature", "frame")]
    assert "feature_location" in _roles(complex_) and "feature_size" in _roles(complex_)
    assert not [d for d in complex_.drawing.dimensions if d.tolerance == "basic"]
    assert not [
        c
        for c in complex_.drawing.checks
        if c.code in ("R4.complete", "COV.unclaimed") and c.level != "information"
    ]
    assert len(complex_.drawing.dimensions) >= len(_roles(full)) - len(full.plan[0].datums) - 2


def test_simplified_gives_the_overall_size_and_the_holes_and_says_the_model_governs():
    run = drawn("simplified")
    d = run.drawing
    assert "feature_location" not in _roles(run) and d.dimensions, "sizes only, nothing located"
    assert len(d.dimensions) < len(drawn("complex").drawing.dimensions)
    assert any(n.text.startswith("REDUCED-DIMENSION DRAWING") for n in run.plan[0].notes)
    assert not run.plan[0].datums and d.options.effective_scheme == "plusminus"
    worst = {c.code: c.level for c in d.checks}
    assert worst.get("R4.complete", "information") == "information"
    back, problems = document.loads(document.dumps(d))
    assert problems == [] and back.options.detail == "simplified"


@pytest.mark.parametrize("bad", ["Simple", "", None, "full "])
def test_an_unknown_detail_level_is_refused(bad):
    from solidseas.errors import InvalidArgumentError

    with pytest.raises(InvalidArgumentError):
        DrawingOptions(detail=bad)
