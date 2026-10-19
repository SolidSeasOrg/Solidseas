"""Express drawings (``solidseas.drawing.express``): the overall size, the holes by size
and location, and nothing else, on the synthetic plates of ``drawing_parts`` and on the
SOLIDWORKS fixtures. The people and the company are the fictional "Example Engineering
Co." and its staff."""

import datetime
import functools
import json
import re

import pytest

import drawing_golden_support as G
import drawing_parts
from drawing_parts import MM, box, build, cut_hole
from solidseas.drawing import checks, document, merge, pipeline, svg
from solidseas.drawing import settings as S
from solidseas.drawing.express import express_fields, express_options
from solidseas.drawing.types import DrawingOptions
from solidseas.errors import InvalidArgumentError
from support import FIXTURES


@functools.cache
def settings() -> S.DrawingSettings:
    return S.with_value(G.settings(), "people", "people", [{"name": "Alex Drafter", "initials": "AD"}])


def express(name: str, part, **kw):
    xt, truth = part
    stage = G.source_stage(name, xt, truth)
    options = express_options(units="mm", **kw)
    run = pipeline.run(
        None,
        options=options,
        fields=express_fields(settings()),
        settings=settings(),
        stages={"source": stage},
    )
    return run, stage


@functools.cache
def patterns():
    return express("patterns_plate", drawing_parts.patterns_plate())


@functools.cache
def four_holes():
    return express("four_holes_plate", drawing_parts.four_holes_plate())


def shown(drawing) -> dict[str, str]:
    return {e["key"]: e["value"] for e in G.shown_set(drawing)}


def test_express_is_the_simplified_level_in_express_mode():
    o = express_options()
    assert o.mode == "express" and o.express and o.detail == "simplified"
    assert o.effective_scheme == "plusminus" and DrawingOptions().mode == "expert"
    with pytest.raises(InvalidArgumentError):
        DrawingOptions(mode="Express")


def test_a_plate_with_hole_patterns_gets_its_size_its_holes_and_their_locations_only():
    run, _stage = patterns()
    assert shown(run.drawing) == {
        # the overall size
        "size/f-22": "200.0",
        "size/f-23": "120.0",
        "size/f-24": "10.0",
        # each hole and pattern by size, with its count
        "callout/f-15": "Ø16.00 THRU",
        "callout/f-19": "6X Ø5.50 THRU",
        "callout/f-20": "5X Ø5.50 THRU",
        "callout/f-21": "6X Ø4.50 THRU",
        # the patterns' own pitches, the bolt circle and its clocking
        "pitch/f-20/x": "4X 20.00",
        "pitch/f-21/x": "2X 15.00",
        "pitch/f-21/y": "12.00",
        "pcd/f-19": "Ø40.00",
        "angle/f-19": "15°",
        # each pattern and the bore located from the datum edges
        "loc/f-1/x": "20.00",
        "loc/f-1/y": "20.00",
        "loc/f-2/y": "70.00",
        "loc/f-15/x": "150.00",
        "loc/f-15/y": "60.00",
    }
    d = run.drawing
    assert {dim.tolerance for dim in d.dimensions} == {"block"}, "no tolerances of their own"
    assert not run.plan[0].datums and not [
        a for a in d.sheet.annotations if type(a).__name__ == "DatumFeature"
    ]


def test_scattered_holes_are_each_located():
    run, _stage = four_holes()
    got = shown(run.drawing)
    assert {k for k in got if k.startswith("loc/")} == {
        f"loc/f-{n}/{ax}" for n in (1, 2, 3, 4) for ax in "xy"
    }
    assert sorted(float(got[f"loc/f-{n}/x"]) for n in (1, 2, 3, 4)) == [12.0, 37.0, 71.0, 88.0]
    assert got["callout/f-5"] == "4X Ø6.60 THRU"
    assert sorted(k for k in got if k.startswith("size/")) == ["size/f-6", "size/f-7", "size/f-8"]


def test_a_bolt_circle_is_given_by_its_pitch_circle():
    run, _stage = express("arc_plate", drawing_parts.arc_plate([0, 90, 180, 270]))
    got = shown(run.drawing)
    assert got["pcd/f-6"] == "Ø60.00" and got["callout/f-6"] == "4X Ø5.00 THRU"
    assert got["loc/f-3/x"] == "50.00" and got["loc/f-3/y"] == "50.00", "the bore, which centres the circle"


def test_bosses_chamfers_and_fillets_are_left_to_the_model():
    for name in ("boss_block", "groove_plate", "pocket_tab_block"):
        run, _stage = express(name, getattr(drawing_parts, name)())
        roles = {d.role for d in run.drawing.dimensions}
        assert roles <= {"envelope", "feature_size", "pattern", "feature_location"}, (name, roles)
        assert not [d for d in run.drawing.dimensions if d.kind in ("chamfer", "radius")], name
        keys = [d.key for d in run.drawing.dimensions if d.role != "envelope"]
        assert all(k.split("/")[0] in ("callout", "loc", "pitch", "pcd", "angle") for k in keys), (name, keys)


def test_only_the_model_governs_note_in_capitals():
    run, _stage = four_holes()
    (note,) = [n.text for _i, n in run.drawing.notes]
    assert note.startswith("REDUCED-DIMENSION DRAWING OF MODEL FOUR_HOLES_PLATE ") and note == note.upper()


@pytest.mark.parametrize("which", [patterns, four_holes])
def test_no_error_and_what_express_leaves_out_is_information(which):
    run, _stage = which()
    d = run.drawing
    assert [c for c in d.checks if c.level == "error"] == []
    assert G.hard_conflicts(d.checks) == []
    levels = {(c.code, c.item): c.level for c in d.checks}
    assert levels.get(("R14.notes", "R14.notes")) == "information"
    assert levels.get(("R13.plusminus", "R13.plusminus")) == "information"
    assert "an Express drawing" in next(c.message for c in d.checks if c.code == "R14.notes")
    # Release asks for everything: what Express left out is found again at its own level.
    released = checks.run_checks(d, release=True)
    assert any(c.code == "R15.process" and c.level == "error" for c in released)


def test_the_same_checks_keep_their_levels_on_an_expert_drawing():
    xt, truth = drawing_parts.four_holes_plate()
    stage = G.source_stage("four_holes_plate", xt, truth)
    options = DrawingOptions(units="mm", detail="simplified")
    run = pipeline.run(None, options=options, settings=settings(), stages={"source": stage})
    levels = {(c.code, c.item): c.level for c in run.drawing.checks}
    assert levels.get(("R6.title", "material")) == "error", "the expert's empty material is an error"
    assert not any("Express" in c.message for c in run.drawing.checks)


def test_the_title_block_is_filled_from_the_parts_properties():
    path = FIXTURES / "o05_boxA_props_mat.SLDPRT"
    d = pipeline.make_drawing(
        str(path), options=express_options(), fields=express_fields(settings()), settings=settings()
    )
    title = {k: (f.text, f.source) for k, f in d.title}
    assert title["part_number"] == ("ORACLE-PN-123", "part")
    assert title["title"] == ("Oracle test box", "part")
    assert title["material"] == ("1060 Alloy", "part")
    assert title["finish"][0] == "NONE", "a part that names no finish has none"
    (drawn,) = [g for g in d.signatures if g.row == "DRAWN"]
    assert drawn.name == "Alex Drafter" and drawn.date == datetime.date.today().isoformat()
    assert re.search(r">[0-9]+:[0-9]+<", svg.to_svg(d.sheet)), "the scale is in the title block"
    assert d.options.mode == "express"


def test_nobody_in_people_leaves_drawn_empty_with_a_warning():
    assert express_fields(G.settings()) == {}
    xt, truth = drawing_parts.four_holes_plate()
    stage = G.source_stage("four_holes_plate", xt, truth)
    run = pipeline.run(None, options=express_options(), settings=G.settings(), stages={"source": stage})
    drawn = [c for c in run.drawing.checks if c.code == "R6.title" and c.item == "DRAWN"]
    assert drawn and drawn[0].level == "warning"


def test_the_mode_is_kept_in_the_file_and_only_when_express():
    run, _stage = four_holes()
    options = json.loads(document.dumps(run.drawing))["options"]
    assert options["mode"] == "express" and options["detail"] == "simplified"
    back, problems = document.loads(document.dumps(run.drawing))
    assert problems == [] and back.options.mode == "express"
    plain = pipeline.run(
        None,
        options=DrawingOptions(units="mm"),
        settings=settings(),
        stages={"source": G.source_stage("four_holes_plate", *drawing_parts.four_holes_plate())},
    )
    assert "mode" not in json.loads(document.dumps(plain.drawing))["options"], "expert files are as they were"


def test_a_mode_this_solidseas_does_not_know_falls_back_to_expert_and_says_so():
    run, _stage = four_holes()
    raw = json.loads(document.dumps(run.drawing))
    raw["options"]["mode"] = "guided"
    back, problems = document.loads(json.dumps(raw).encode("utf-8"))
    assert back.options.mode == "expert" and any("options.mode" in p for p in problems)


def test_update_from_model_keeps_the_mode_and_locates_a_new_hole():
    run, _stage = four_holes()
    t = 10 * MM
    p = box(100 * MM, 60 * MM, t)
    for k, (x, y) in enumerate([(12, 10), (37, 48), (71, 15), (88, 44)]):
        p = cut_hole(p, (x * MM, y * MM, t), "-z", [("bore", 6.6 * MM, None)], f"h{k}")
    p = cut_hole(p, (55 * MM, 30 * MM, t), "-z", [("bore", 10 * MM, None)], "new")
    xt, truth = build(p)
    source = G.source_stage("four_holes_plate", xt, truth)()
    new, _report = merge.regenerate(run.drawing, source)
    assert new.options.mode == "express" and new.options.detail == "simplified"
    got = shown(new)
    assert "Ø10.00 THRU" in got.values()
    assert sum(1 for k in got if k.startswith("loc/")) > sum(
        1 for k in shown(run.drawing) if k.startswith("loc/")
    )
    assert all(k.split("/")[0] in ("callout", "loc", "size") for k in got)
    assert [c for c in new.checks if c.level == "error"] == []
