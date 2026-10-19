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
from solidseas.drawing.layout.index import Box
from solidseas.drawing.settings import from_dict
from solidseas.drawing.types import DrawingOptions
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


def _run_child(tmp_path, part: str) -> dict:
    settings = tmp_path / "Drawing.json"
    settings.write_text(json.dumps(child.SETTINGS), encoding="utf-8")
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
    assert got["conflicts"] == {"conflicts": 0, "by_kind": {}, "by_view_type": {}}


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
    }
    for broken in (None, dict(good, conflicts=1)):
        row = child.drawing_row(counts, 2, broken)
        assert row["by_kind"] == row["by_view_type"] == {"unknown": 2}
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
