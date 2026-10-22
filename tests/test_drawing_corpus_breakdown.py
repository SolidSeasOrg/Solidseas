"""The drawing corpus sweep's own parts, on the fixtures rather than the private corpus:
a drawing made the sweep's way passes check R6.title, and the hard conflicts
(``R11.collisions``) are counted by what collides with what, by view type, against the
drawings' dimensions and for the worst drawings, in numbers and fixed words only
(``drawing_corpus_child``, ``test_drawing_corpus``)."""

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import drawing_corpus_child as child
from jsonschema_subset import validate
from solidseas import model
from solidseas.drawing import pipeline
from solidseas.drawing.checks import Check, _layout_checks, _Out
from solidseas.drawing.layout import checks as layout_checks
from solidseas.drawing.layout import measure
from solidseas.drawing.layout.index import Box
from solidseas.drawing.settings import from_dict
from solidseas.drawing.types import DIMENSION_KINDS, DrawingOptions
from support import FIXTURES

SRC = Path(__file__).resolve().parents[1] / "src"
# What the exchange takes as a measurement's name (scripts/exchange/xchg.py MEASURE_RE)
NAME = re.compile(r"\A[a-z0-9][a-z0-9_.-]{0,63}\Z")
KINDS = {
    "dimension",
    "frame",
    "datum",
    "note",
    "balloon",
    "parts_list",
    "title_block",
    "revision_block",
    "stamp",
    "border",
    "view_label",
    "build_arrow",
    "other",
}


def _copy(tmp_path, name: str) -> str:
    target = tmp_path / name
    shutil.copyfile(FIXTURES / name, target)
    return str(target)


def _run_child(tmp_path, part: str, settings_data: dict | None = None) -> dict:
    settings = tmp_path / "Drawing.json"
    settings.write_text(json.dumps(settings_data or child.SETTINGS), encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    script = Path(child.__file__).resolve()
    proc = subprocess.run(
        [sys.executable, str(script), part, str(settings)], capture_output=True, env=env, timeout=300
    )
    return json.loads(proc.stdout.decode("utf-8"))


def _hard(drawing) -> list[Check]:
    return [c for c in drawing.checks if c.code == child.HARD_CONFLICT]


def test_a_drawing_made_the_sweeps_way_passes_r6_title(tmp_path):
    part = _copy(tmp_path, "o02_boxA.SLDPRT")
    got = _run_child(tmp_path, part)
    envelope = got["envelope"]
    assert envelope["ok"], envelope
    assert validate(envelope, model.envelope_schema("drawing_result"), strict=True) == []
    data = envelope["data"]
    assert [c for c in data["checks"] if c["code"] == "R6.title"] == []
    assert not [c for c in data["checks"] if c["level"] == "error"]
    title = data["drawing"]["title"]
    # number, title and part number from the file name; the rest typed by the sweep
    for key in ("number", "title", "part_number"):
        assert title[key] == {"text": "O02_BOXA", "from": "part"}
    for key in ("material", "finish"):
        assert title[key] == {"text": child.FIELDS[key], "from": "typed"}
    drawn = [s for s in data["drawing"]["signatures"] if s["row"] == "DRAWN"]
    assert drawn and drawn[0]["name"] == child.FIELDS["drawn_by"] and drawn[0]["date"]
    options = data["drawing"]["options"]
    assert got["conflicts"] == {
        "conflicts": 0,
        "by_kind": {},
        "by_view_type": {},
        "sheet": options["sheet"].lower(),
        "scale": [int(n) for n in options["scale"].split(":")],
        "details": [],
    }
    assert got["title"] == {"weight": 0}
    # SEE MODEL is no material of the settings' list either, which R6.material says
    assert child.title_row(data, got["title"]) == {
        "material_from": "typed",
        "weight": 0,
        "material_checks": {"warning": 1},
    }


@pytest.mark.parametrize("name", ["o05_boxA_props_mat.SLDPRT", "o14_property_types.SLDPRT"])
def test_the_sweep_keeps_a_parts_own_material(tmp_path, name):
    """A part that names its material (o05 as its own material, o14 in a Material
    property too) keeps it: nothing is typed over it, R6.title still passes, and the
    checks of the material run on the part's own (1060 Alloy is not in the default
    list, so R6.material says so and no weight is shown)."""
    got = _run_child(tmp_path, _copy(tmp_path, name))
    envelope = got["envelope"]
    assert envelope["ok"], envelope
    data = envelope["data"]
    assert data["drawing"]["title"]["material"] == {"text": "1060 Alloy", "from": "part"}
    assert data["drawing"]["title"]["finish"] == {"text": child.FIELDS["finish"], "from": "typed"}
    assert [c for c in data["checks"] if c["code"] == "R6.title"] == []
    unlisted = [c for c in data["checks"] if c["code"] == "R6.material"]
    assert [c["level"] for c in unlisted] == ["warning"] and "1060 ALLOY" in unlisted[0]["message"]
    assert got["title"] == {"weight": 0}
    assert child.title_row(data, got["title"]) == {
        "material_from": "part",
        "weight": 0,
        "material_checks": {"warning": 1},
    }


def test_a_parts_own_listed_material_gives_its_weight(tmp_path):
    """With the part's material in the settings' list, its drawing shows the list's
    callout and the calculated weight from its density: what typing a material over
    every part used to hide from the sweep."""
    entry = {"names": ["1060 alloy"], "callout": "ALUMINUM 1060", "specification": "ASTM B209"}
    listed = dict(child.SETTINGS, materials={"entries": [dict(entry, density=2705.0)]})
    got = _run_child(tmp_path, _copy(tmp_path, "o05_boxA_props_mat.SLDPRT"), listed)
    data = got["envelope"]["data"]
    assert data["drawing"]["title"]["material"] == {"text": "ALUMINUM 1060", "from": "part"}
    assert [c for c in data["checks"] if c["code"] in ("R6.title", "R6.material")] == []
    assert got["title"] == {"weight": 1}


def test_typed_fields_leave_out_only_a_material_the_part_names():
    settings, _problems = from_dict(child.SETTINGS)
    bare = SimpleNamespace(material=None, property=lambda *names: None)
    assert child.typed_fields(bare, settings) == child.FIELDS
    own = SimpleNamespace(material="AISI 304", property=lambda *names: None)
    named = SimpleNamespace(material=None, property=lambda *names: "PLA" if "Material" in names else None)
    blank = SimpleNamespace(material="  ", property=lambda *names: None)
    rest = {k: v for k, v in child.FIELDS.items() if k != "material"}
    for source in (own, named):
        assert child.typed_fields(source, settings) == rest
    assert child.typed_fields(blank, settings) == child.FIELDS


def test_title_blocks_are_summarised_in_numbers_only():
    rows = [
        {"material_from": "typed", "weight": 0, "material_checks": {}},
        {"material_from": "part", "weight": 0, "material_checks": {"warning": 1}},
        {"material_from": "part", "weight": 1, "material_checks": {}},
        {"material_from": "none", "weight": 0, "material_checks": {"warning": 1, "error": 1}},
    ]
    got = child.summarise_titles(rows)
    assert got == {
        "material_from": {"none": 1, "part": 2, "typed": 1},
        "weight_shown": 1,
        "material_checks": {"error": 1, "warning": 2},
    }
    for what, value in _names(got):
        if what == "key":
            assert NAME.match(value), value
        else:
            assert isinstance(value, int) and not isinstance(value, bool), value
    assert child.summarise_titles([]) == {"material_from": {}, "weight_shown": 0, "material_checks": {}}


def test_the_default_drawing_fails_r6_title_where_the_sweep_fills_it(tmp_path):
    """What the sweep's fields and company are for: without them R6.title fails on the
    empty company, DRAWN, material and finish of a part that names none."""
    drawing = pipeline.run(_copy(tmp_path, "o02_boxA.SLDPRT")).drawing
    items = {c.item for c in drawing.checks if c.code == "R6.title"}
    assert items == {"company", "DRAWN", "material", "finish"}
    settings, problems = from_dict(child.SETTINGS)
    assert problems == [] and settings.company.name == child.SETTINGS["company"]["name"]
    filled = pipeline.run(_copy(tmp_path, "o02_boxA.SLDPRT"), fields=child.FIELDS, settings=settings).drawing
    assert [c for c in filled.checks if c.code == "R6.title"] == []


def test_item_kinds():
    cases = {
        "d-3": "dimension",
        "d-12-frame": "frame",
        "n-2-frame": "frame",
        "n-4": "note",
        "notes": "note",
        "datum-A": "datum",
        "balloon-7": "balloon",
        "parts": "parts_list",
        "title": "title_block",
        "tolerance": "title_block",
        "projection": "title_block",
        "logo": "title_block",
        "revisions": "revision_block",
        "stamp": "stamp",
        "plot": "stamp",
        "border": "border",
        "v-2-label": "view_label",
        "build": "build_arrow",
        "R11.collisions": "other",
        "": "other",
        "d": "other",
    }
    assert {o: child.item_kind(o) for o in cases} == cases


def test_breakdown_of_a_crowded_fixture_drawing(tmp_path):
    """o10 at 5:1 on an A sheet has no room for its dimensions and datums: real
    overlaps and items with no clear place, every one of them counted once."""
    run = pipeline.run(
        _copy(tmp_path, "o10_import_step_cut.SLDPRT"), options=DrawingOptions(sheet="A", scale=(5, 1))
    )
    drawing = run.drawing
    hard = _hard(drawing)
    assert hard
    overlaps = [c for c in hard if " overlaps " in c.message]
    assert overlaps and all(c.other for c in overlaps)  # the second item is kept
    assert all(not c.other for c in hard if c not in overlaps)
    kinds = child.view_kinds(drawing)
    assert set(kinds.values()) <= set(child.VIEW_KINDS) and "base" in kinds.values()
    got = child.breakdown(drawing, kinds)
    assert got["conflicts"] == len(hard)
    assert sum(got["by_kind"].values()) == sum(got["by_view_type"].values()) == len(hard)
    for key in got["by_kind"]:
        names = key.split("-")
        if names[-1] == child.NO_PLACE:
            names = names[:-1]
        assert len(names) in (1, 2) and set(names) <= KINDS - {"other"}, key
    assert any(k.endswith(child.NO_PLACE) for k in got["by_kind"])
    assert any(not k.endswith(child.NO_PLACE) for k in got["by_kind"])
    for key in got["by_view_type"]:
        assert set(key.split("-")) <= {*child.VIEW_KINDS, "sheet"}, key


def test_breakdown_counts_each_pair_by_kind_and_view(tmp_path):
    _copy(tmp_path, "o02_boxA.SLDPRT")  # the assembly's part, beside it
    drawing = pipeline.run(_copy(tmp_path, "o08_asm_2x_boxA.SLDASM")).drawing
    kinds = child.view_kinds(drawing)
    views = {a.id: a.view for a in drawing.sheet.annotations if type(a).__name__ == "Dimension"}
    balloon = next(a.view for a in drawing.sheet.annotations if type(a).__name__ == "Balloon")
    d1, d3 = kinds[views["d-1"]], kinds[views["d-3"]]
    assert d1 != d3  # two views
    made = [
        Check("R11.collisions", "error", "'a' overlaps 'b'", "d-1", other="d-3"),
        Check("R11.collisions", "error", "'a' overlaps 'b'", "d-1", other="balloon-1"),
        Check("R11.collisions", "error", "'a' overlaps 'b'", "parts", other="d-1"),
        Check("R11.collisions", "error", "'a' overlaps 'b'", "title", other="parts"),
        Check("R11.collisions", "error", "the balloon of item 1 could not be placed clear", "balloon-1"),
        Check("R6.title", "error", "not a conflict", "company"),
    ]
    got = child.breakdown(replace(drawing, checks=tuple(made)), kinds)
    assert got["conflicts"] == 5
    assert got["by_kind"] == {
        "dimension-dimension": 1,
        "balloon-dimension": 1,
        "dimension-parts_list": 1,
        "parts_list-title_block": 1,
        "balloon-no_clear_place": 1,
    }
    expected: dict[str, int] = {}
    for sides in ({d1, d3}, {d1, kinds[balloon]}, {d1, "sheet"}, {"sheet"}, {kinds[balloon]}):
        key = "-".join(sorted(sides))
        expected[key] = expected.get(key, 0) + 1
    assert got["by_view_type"] == expected


def test_layout_overlap_keeps_the_other_item():
    pen = SimpleNamespace(
        texts=[("12.5", Box(10, 10, 20, 14), "d-1"), ("NOTE", Box(15, 11, 30, 15), "n-2")], replaced=()
    )
    far = Box(1000, 1000, 1001, 1001)
    frame = SimpleNamespace(border=Box(0, 0, 400, 300), title=far, revision=far, notes=far)
    found = layout_checks.run(pen, frame, leaders=[], unplaced=[("balloon-3", "the balloon")], cramped=[])
    overlap = next(c for c in found if c.code == "L.overlap")
    assert (overlap.owner, overlap.other) == ("d-1", "n-2")
    out = _Out()
    _layout_checks(SimpleNamespace(layout=SimpleNamespace(checks=found)), out)
    hard = [c for c in out.items if c.code == child.HARD_CONFLICT]
    assert {(c.item, c.other) for c in hard} == {("d-1", "n-2"), ("balloon-3", "")}
    # kept in memory only: never written, and not part of a check's identity
    check = next(c for c in hard if c.other)
    assert "other" not in check.to_dict()
    assert check == replace(check, other="")


def test_a_row_without_a_matching_breakdown_counts_as_unknown():
    counts = {"shown": 40, "views": 3}
    good = {"conflicts": 2, "by_kind": {"dimension-dimension": 2}, "by_view_type": {"base": 2}}
    assert child.drawing_row(counts, 2, good) == {
        "dimensions": 40,
        "views": 3,
        "conflicts": 2,
        "by_kind": {"dimension-dimension": 2},
        "by_view_type": {"base": 2},
        "details": [],
    }
    rows = [{"kind": "dimension-dimension", "cause": "overlap.band"}] * 2
    measured_ = dict(good, sheet="b", scale=[1, 1], details=rows)
    assert child.drawing_row(counts, 2, measured_) == dict(
        child.drawing_row(counts, 2, good), sheet="b", scale=[1, 1], details=rows
    )
    for broken in (None, dict(good, conflicts=1), dict(measured_, conflicts=1)):
        row = child.drawing_row(counts, 2, broken)
        assert row["by_kind"] == row["by_view_type"] == {"unknown": 2}
        assert row["details"] == []
    assert child.drawing_row(counts, 0, None)["by_kind"] == {}


def _names(value, path=""):
    """Every key below ``value`` and every leaf, for the numbers-only check."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield "key", k
            yield from _names(v, f"{path}.{k}")
    elif isinstance(value, list):
        for v in value:
            yield from _names(v, path)
    else:
        yield "leaf", value


def test_summarise_counts_and_ranks_in_numbers_only():
    rows = [
        {"dimensions": 10, "views": 2, "conflicts": 0, "by_kind": {}, "by_view_type": {}},
        {
            "dimensions": 30,
            "views": 3,
            "conflicts": 3,
            "by_kind": {"dimension-dimension": 3},
            "by_view_type": {"base": 3},
        },
        *(
            {
                "dimensions": 60 + k,
                "views": 4,
                "conflicts": 1 + k,
                "by_kind": {"dimension-note": 1, "datum-no_clear_place": k},
                "by_view_type": {"projected": 1 + k},
            }
            for k in range(12)
        ),
        {
            "dimensions": 600,
            "views": 6,
            "conflicts": 150,
            "by_kind": {"unknown": 150},
            "by_view_type": {"unknown": 150},
        },
    ]
    got = child.summarise(rows)
    assert got["hard_conflicts_by_kind"] == {
        "unknown": 150,
        "datum-no_clear_place": 66,
        "dimension-note": 12,
        "dimension-dimension": 3,
    }
    assert got["hard_conflicts_by_view_type"] == {"unknown": 150, "projected": 78, "base": 3}
    grid = got["drawings_by_dimensions_and_conflicts"]
    assert list(grid) == ["0-24", "25-49", "50-99", "100-199", "200-499", "500-up"]
    assert all(list(v) == ["0", "1-4", "5-19", "20-99", "100-up"] for v in grid.values())
    assert grid["0-24"]["0"] == 1 and grid["25-49"]["1-4"] == 1
    assert grid["50-99"] == {"0": 0, "1-4": 4, "5-19": 8, "20-99": 0, "100-up": 0}
    assert grid["500-up"]["100-up"] == 1
    assert sum(n for v in grid.values() for n in v.values()) == len(rows)
    worst = got["worst_drawings"]
    assert len(worst) == child.WORST
    assert [w["conflicts"] for w in worst] == [150, 12, 11, 10, 9, 8, 7, 6, 5, 4]
    assert worst[1] == {
        "dimensions": 71,
        "views": 4,
        "conflicts": 12,
        "by_kind": {"datum-no_clear_place": 11, "dimension-note": 1},
    }
    # rows the child measured nothing of: every conflict unmeasured, none one by one
    assert got["hard_conflicts_by_cause"] == {"unmeasured": 231}
    assert [d["conflicts"] for d in got["conflict_details"]] == [
        150,
        12,
        11,
        10,
        9,
        8,
        7,
        6,
        5,
        4,
        3,
        3,
        2,
        1,
    ]
    assert all(d["details"] == [] for d in got["conflict_details"])
    # the exchange's rules: plain lower-case names, numbers, and no slash anywhere
    for what, value in _names(got):
        if what == "key":
            assert NAME.match(value), value
        else:
            assert isinstance(value, int) and not isinstance(value, bool), value
    assert "/" not in json.dumps(got) and "\\" not in json.dumps(got)


@pytest.mark.parametrize(
    "empty", [[], [{"dimensions": 5, "views": 1, "conflicts": 0, "by_kind": {}, "by_view_type": {}}]]
)
def test_summarise_without_conflicts(empty):
    got = child.summarise(empty)
    assert got["hard_conflicts_by_kind"] == {} and got["worst_drawings"] == []
    assert got["hard_conflicts_by_cause"] == {} and got["conflict_details"] == []


def test_summarise_saves_the_measured_conflicts_one_by_one():
    """Measured rows give their causes to the counts and their conflicts one by one for
    the drawings with the most, at most DETAILS of each, sorted so that nothing of a file
    shows in their order; a row with fewer details than conflicts counts the rest as
    unmeasured."""
    leader = {"kind": "dimension-no_clear_place", "cause": "leader.leader_across_line", "looked": 9}
    datum = {"kind": "datum-no_clear_place", "cause": "datum.no_room", "free_mm": 4}
    rows = [
        {
            "dimensions": 30,
            "views": 3,
            "conflicts": 3,
            "by_kind": {"dimension-no_clear_place": 2, "datum-no_clear_place": 1},
            "by_view_type": {"base": 3},
            "details": [leader, datum, dict(leader, looked=7)],
            "sheet": "b",
            "scale": [1, 1],
        },
        {
            "dimensions": 20,
            "views": 2,
            "conflicts": 2,
            "by_kind": {"datum-no_clear_place": 2},
            "by_view_type": {"base": 2},
            "details": [datum],
        },
    ]
    got = child.summarise(rows)
    assert got["hard_conflicts_by_cause"] == {
        "datum.no_room": 2,
        "leader.leader_across_line": 2,
        "unmeasured": 1,
    }
    first, second = got["conflict_details"]
    assert (first["conflicts"], first["sheet"], first["scale"]) == (3, "b", [1, 1])
    assert first["details"] == sorted(rows[0]["details"], key=lambda d: json.dumps(d, sort_keys=True))
    assert "sheet" not in second and second["details"] == [datum]
    many = dict(rows[0], conflicts=60, details=[dict(leader, looked=k) for k in range(60)])
    kept = child.summarise([many])["conflict_details"][0]["details"]
    by_text = sorted(many["details"], key=lambda d: json.dumps(d, sort_keys=True))
    assert len(kept) == child.DETAILS and kept == by_text[: child.DETAILS]
    assert len(child.summarise([many] * (child.DETAILED + 5))["conflict_details"]) == child.DETAILED


def test_a_conflicts_cause_names_the_step_and_what_stopped_it():
    assert (
        child.cause({"overlap_mm": [1, 1], "steps": ["band.right", "band_frame"]})
        == "overlap.band-band_frame"
    )
    breaks = {"leader_across_line": {"band.above": 2}, "line_through_text": {"centre_line": 1}}
    assert child.cause({"step": "leader", "breaks": breaks}) == "leader.line_through_text"
    assert child.cause({"step": "leader", "nowhere": 1, "breaks": breaks}) == "leader.nowhere"
    assert child.cause({"step": "datum", "free_mm": 4, "reach_mm": 11.5, "spots": {"over_text": 9}}) == (
        "datum.no_room"
    )
    roomy = {"step": "datum", "free_mm": 22, "reach_mm": 11.5, "spots": {"over_text": 9, "off_sheet": 9}}
    assert child.cause(roomy) == "datum.off_sheet"  # a tie goes to the first in order of the words
    assert (
        child.cause({"step": "band_frame", "spots": {"over_line": 3, "over_text": 5}})
        == "band_frame.over_text"
    )
    assert child.cause({"step": "balloon"}) == "balloon.no_clear_place"


# --------------------------------------------------------------------------- the measure


def _measured_run(monkeypatch, *, part=None, stage=None, options=None):
    """A drawing made with every layout measuring (child.measuring), and the measured
    layout that made its sheet."""
    from solidseas.drawing import orchestrate

    monkeypatch.setattr(orchestrate, "layout", orchestrate.layout)  # put back after the test
    made = child.measuring()
    stages = {"source": stage} if stage is not None else None
    run = pipeline.run(part, options=options or DrawingOptions(), stages=stages, **_SWEEP)
    return run.drawing, child.layout_of(run.drawing, made)


_SWEEP = {"fields": child.FIELDS, "settings": from_dict(child.SETTINGS)[0]}


def _plate(seed: int, n: int):
    import drawing_golden_support as G
    import drawing_parts as P

    xt, truth = P.random_plate(seed, n)
    return G.source_stage("random_plate", xt, truth)


def test_measuring_changes_nothing_on_the_sheet(tmp_path, monkeypatch):
    """The measure only says how layout came to its conflicts: the same sheet and the same
    checks with it on as off, on a crowded drawing (o10 at 5:1 on an A sheet)."""
    from solidseas.drawing.svg import to_svg

    options = DrawingOptions(sheet="A", scale=(5, 1))
    plain_run = pipeline.run(_copy(tmp_path, "o10_import_step_cut.SLDPRT"), options=options, **_SWEEP)
    plain = plain_run.drawing
    assert all(c.facts is None for c in plain_run.orchestrated.result.checks)  # measuring is off by default
    drawing, result = _measured_run(
        monkeypatch, part=_copy(tmp_path, "o10_import_step_cut.SLDPRT"), options=options
    )
    assert result is not None
    assert to_svg(drawing.sheet) == to_svg(plain.sheet)
    assert [(c.code, c.item, c.message) for c in drawing.checks] == [
        (c.code, c.item, c.message) for c in plain.checks
    ]


def _details(drawing, result) -> list[dict]:
    return child.details(drawing, result, child.view_kinds(drawing), child.dimension_kinds(drawing))


def test_each_hard_conflict_says_how_layout_came_to_it(tmp_path, monkeypatch):
    """o10 at 5:1 on an A sheet: every hard conflict, text over text and items with no
    clear place alike, has its record, none of them unmeasured."""
    options = DrawingOptions(sheet="A", scale=(5, 1))
    drawing, result = _measured_run(
        monkeypatch, part=_copy(tmp_path, "o10_import_step_cut.SLDPRT"), options=options
    )
    got = _details(drawing, result)
    hard = _hard(drawing)
    assert len(got) == len(hard) >= 5  # the collector reads every one
    assert [d["kind"] for d in got] == [child._pair(c) for c in hard]
    assert "unmeasured" not in [d["cause"] for d in got]
    overlaps = [d for d in got if not d["kind"].endswith(child.NO_PLACE)]
    unplaced = [d for d in got if d["kind"].endswith(child.NO_PLACE)]
    assert overlaps and unplaced
    for d in overlaps:
        assert min(d["overlap_mm"]) > 0 and len(d["steps"]) == 2 and d["relation"] in measure.RELATIONS
        assert d["cause"] == "overlap." + "-".join(sorted(s.split(".")[0] for s in d["steps"]))
    for d in unplaced:
        assert d["step"] in measure.STEPS and set(d["room_mm"]) == set(measure.SIDES)
        assert d["cause"].startswith(d["step"] + ".")
        if d["step"] == "leader":
            assert d["cost"] > 0 and d["breaks"] and d["looked"] > 0 and d["anchors"] >= 1
        if d["step"] == "datum":
            assert d["tried"] > 0 and d["views"] >= 1 and sum(d["spots"].values()) >= d["tried"]


def test_the_measure_tells_a_full_sheet_from_leaders_boxed_in_by_a_band(monkeypatch):
    """A seeded plate of 28 holes on a B sheet at 1:1. Its views fit only without the
    datum symbols' room, so datum A has 4 mm past its face where its symbol reaches
    11.5 mm, and its spots are off the sheet: the sheet is too small. Two callouts have
    room above the view, but no leader from their holes gets there without crossing a
    dimension line of the band above: the band is in the way."""
    drawing, result = _measured_run(monkeypatch, stage=_plate(7, 28), options=DrawingOptions(sheet="B"))
    assert (drawing.sheet.name, drawing.sheet.scale) == ("B", (1, 1))
    got = _details(drawing, result)
    assert sorted(d["cause"] for d in got) == [
        "datum.no_room",
        "leader.leader_across_line",
        "leader.leader_across_line",
    ]
    datum = next(d for d in got if d["step"] == "datum")
    assert datum["room_kept"] == 0 and datum["free_mm"] < datum["reach_mm"]
    assert datum["spots"]["off_sheet"] > datum["tried"] / 2
    for d in (d for d in got if d["step"] == "leader"):
        assert d["item"] == "hole_callout" and d["cost"] == 1
        assert d["breaks"]["leader_across_line"].get("band.above", 0) >= 1
        assert d["room_mm"]["above"] > d["text_mm"][1]


def _words(value):
    """Every word in ``value``: its keys and its text leaves."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _words(v)
    elif isinstance(value, list):
        for v in value:
            yield from _words(v)
    elif isinstance(value, str):
        yield value


# The words a conflict's record may hold, split at dots and dashes: fixed words of the
# measure, the sweep and the drawing types, and the names of the record's own members.
VOCABULARY = {
    *KINDS,
    child.NO_PLACE,
    *child.VIEW_KINDS,
    "sheet",
    *measure.STEPS,
    *measure.SIDES,
    *measure.RULES,
    *measure.SPOT_REASONS,
    *measure.OBSTACLES,
    *measure.RELATIONS,
    *DIMENSION_KINDS,
    *"abcde",  # sheet sizes
    "no_room",
    "nowhere",
    "no_clear_place",
    "unmeasured",
    "overlap",
    *(
        "kind view item other_item cause step cost breaks looked anchors text_mm room_mm tried views "
        "spots room_kept reach_mm free_mm overlap_mm steps relation moved"
    ).split(),
}


def test_a_conflicts_record_holds_numbers_and_fixed_words_only(tmp_path, monkeypatch):
    """No name, text or id of the drawing gets into what the sweep saves of a conflict:
    every word in the records of a crowded drawing is one of the measure's fixed words
    (an owner such as d-12 or datum-A, or a dimension's text, would not be)."""
    options = DrawingOptions(sheet="A", scale=(5, 1))
    drawing, result = _measured_run(
        monkeypatch, part=_copy(tmp_path, "o10_import_step_cut.SLDPRT"), options=options
    )
    plate, plate_result = _measured_run(monkeypatch, stage=_plate(7, 28), options=DrawingOptions(sheet="B"))
    records = _details(drawing, result) + _details(plate, plate_result)
    words = list(_words(records))
    assert len(words) > 50  # the check reads something
    for word in words:
        assert NAME.match(word), word
        assert set(re.split(r"[.-]", word)) <= VOCABULARY, word
    for value in _leaves(records):
        assert isinstance(value, str) or (isinstance(value, int | float) and not isinstance(value, bool)), (
            value
        )
    for bad in ("d-12", "datum-A", "v-1", "12.5"):  # what the check refuses
        assert not (NAME.match(bad) and set(re.split(r"[.-]", bad)) <= VOCABULARY), bad


def _leaves(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from _leaves(v)
    elif isinstance(value, list):
        for v in value:
            yield from _leaves(v)
    else:
        yield value
