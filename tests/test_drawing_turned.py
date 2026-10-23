"""Turned (lathe) parts (docs/DRAWINGS.md 10.5, 10.6; stage 2's ``dwg-turned``): which
parts are turned, their profile and datums, and their drawings under the turned rules.

The parts are the synthetic ones of ``tests/turned_parts.py``, revolved about z, and a
flange of ``drawing_parts`` with bolt holes off the axis, which is mixed."""

from __future__ import annotations

import math
import os
from dataclasses import replace

import pytest

import drawing_golden_support as G
import drawing_parts as P
import turned_parts as T
from drawing_support import fixture
from solidseas import cli
from solidseas.drawing import facegraph, make_drawing, pipeline
from solidseas.drawing import load as load_drawing
from solidseas.drawing import regenerate as regenerate_drawing
from solidseas.drawing import save as save_drawing
from solidseas.drawing.features import recognise
from solidseas.drawing.features import turned as TU
from solidseas.drawing.plan.values import dim_text, text_line
from solidseas.drawing.types import Boss, DrawingOptions, FeatureSet, settings_type
from solidseas.formats.solidworks import parasolid as ps

MM = 1e-3
FIELDS = {"drawn_by": "Ann Bee", "material": "6061-T6", "finish": "None"}


def _model(name: str):
    xt, _truth = T.PARTS[name]()
    return facegraph.from_transmit(xt, name=name)


def _profile(name: str):
    m = _model(name)
    return m, recognise(m).turned


def _run(name: str, unit: str = "mm", **options):
    xt, truth = T.PARTS[name]()
    stage = G.source_stage(name, xt, truth)
    opts = DrawingOptions(units=unit, process=options.pop("process", "turned"), **options)
    return pipeline.run(None, options=opts, settings=G.settings(), fields=FIELDS, stages={"source": stage})


def _texts(run) -> dict[str, tuple[str, object]]:
    """Each planned dimension's key: its text on one line and its frame."""
    ctx = run.orchestrated.planned.detail.ctx
    return {
        pd.key: (text_line(dim_text(ctx, pd)), pd.frame) for pd in run.orchestrated.planned.plan.dimensions
    }


def _x_t(xt, path: str) -> str:
    with open(path, "w", encoding="latin-1", newline="") as fh:
        fh.write(
            ps.text_header(xt, fmt="text", key="k", file=os.path.basename(path)) + ps.write_text(xt) + "\n"
        )
    return path


def _errors(drawing, *codes) -> list:
    return [
        (c.code, c.message) for c in drawing.checks if c.level in ("error", "warning") and c.code in codes
    ]


# --------------------------------------------------------------------------- recognition
def test_a_stepped_shaft_is_turned_with_its_profile_from_the_larger_end():
    m, t = _profile("stepped_shaft")
    assert t is not None and not t.mixed and t.share == pytest.approx(1.0)
    assert t.frame_axis == "z" and t.axis.direction == (0.0, 0.0, 1.0)
    assert t.length == pytest.approx(65 * MM)
    rows = [
        (s.kind, round(s.start / MM, 6), round(s.end / MM, 6), round(s.diameter / MM, 6)) for s in t.segments
    ]
    assert rows == [
        ("cylinder", 0.0, 20.0, 20.0),
        ("cylinder", 20.0, 50.0, 12.0),
        ("cylinder", 50.0, 64.0, 8.0),
        ("cone", 64.0, 65.0, 8.0),
    ]
    assert t.segments[-1].diameter_end == pytest.approx(6 * MM)  # the chamfer's small end
    # A on the longest cylinder, B on the end face at the larger end
    assert t.cylinder_of(t.datum_a).diameter == pytest.approx(12 * MM)
    assert t.datum_b == t.ends[0] and m.faces[t.datum_b].surface.normal == (0.0, 0.0, -1.0)
    assert m.faces[t.ends[1]].surface.normal == (0.0, 0.0, 1.0)
    assert t.reason == TU.TURNED_REASON


def test_the_larger_end_decides_which_way_the_axis_points():
    m, t = _profile("small_end_first_shaft")
    assert t.axis.direction == (0.0, 0.0, -1.0) and t.axis.point[2] == pytest.approx(65 * MM)
    assert t.segments[0].diameter == pytest.approx(20 * MM) and t.segments[0].start == pytest.approx(0.0)
    assert m.faces[t.datum_b].surface.normal == (0.0, 0.0, 1.0)  # the top face, at the Ø20 end


@pytest.mark.parametrize(
    "name, outside, bores",
    [
        ("solid_shaft", [20.0], []),
        ("filleted_shaft", [24.0, 16.0], []),
        ("bored_shaft", [30.0, 18.0], [8.0]),
        ("bushing", [20.0], [12.0]),
        ("grooved_shaft", [16.0, 12.0, 16.0], []),
    ],
)
def test_every_synthetic_turned_part_is_turned(name, outside, bores):
    _m, t = _profile(name)
    assert t is not None and not t.mixed
    cyl = [s for s in t.segments if s.kind == "cylinder"]
    assert [round(s.diameter / MM, 6) for s in cyl if not s.internal] == outside
    assert [round(s.diameter / MM, 6) for s in cyl if s.internal] == bores
    if name == "filleted_shaft":
        assert [s.kind for s in t.segments] == ["cylinder", "torus", "cylinder"]


def test_a_part_with_only_a_bore_takes_its_datum_on_the_bore():
    """A funnel: a cone outside and a bore through, so the bore is the only cylinder."""
    profile = [(4 * MM, 0.0), (15 * MM, 0.0), (10 * MM, 20 * MM), (4 * MM, 20 * MM)]
    xt, _truth = T.revolve(profile, "funnel")
    m = facegraph.from_transmit(xt, name="funnel")
    t = recognise(m).turned
    assert t is not None and t.cylinder_of(t.datum_a).internal
    assert TU.datums_of(t)[0].reason == TU.DATUM_A_BORE_REASON
    assert [s.kind for s in t.segments] == ["cone", "cylinder"]


def test_a_flange_with_bolt_holes_off_the_axis_is_mixed():
    r = 30 * MM
    disc = P.prism([(-r, 0.0), P.Arc((0.0, 0.0), (r, 0.0)), P.Arc((0.0, 0.0), (-r, 0.0))], 10 * MM)
    for k in range(4):
        a = k * math.pi / 2
        at = (20 * MM * math.cos(a), 20 * MM * math.sin(a), 10 * MM)
        disc = P.cut_hole(disc, at, "-z", [("bore", 5 * MM, None)], f"h{k}")
    xt, _truth = P.build(disc)
    m = facegraph.from_transmit(xt, name="flange")
    t = recognise(m).turned
    assert t is not None and t.mixed and TU.MIXED_SHARE <= t.share < 1.0
    assert "% of its area turns about one axis" in t.reason
    outside = [s for s in t.segments if s.kind == "cylinder" and not s.internal]
    assert len(outside) == 1 and len(outside[0].faces) == 2  # the rim's two halves, one segment


@pytest.mark.parametrize("make", [P.four_holes_plate, P.boss_block, P.groove_plate])
def test_prismatic_parts_are_not_turned(make):
    assert recognise(facegraph.from_transmit(make()[0])).turned is None


@pytest.mark.parametrize("name", ["o02_boxA.SLDPRT", "o11_curved.SLDPRT"])
def test_the_fixtures_are_not_turned(name):
    from solidseas.drawing.source import open_source

    m = facegraph.from_bodies(open_source(fixture(name)).selected_bodies())
    assert recognise(m).turned is None


def test_the_turned_process_takes_the_turned_datums_and_splits_bosses_by_segment():
    m = _model("grooved_shaft")
    fs = recognise(m)
    bosses = [f for f in fs.features if isinstance(f, Boss)]
    assert sorted(len(b.faces) for b in bosses) == [1, 2]  # recognition takes both Ø16 pieces as one boss
    turned = TU.for_process(fs, "turned")
    bosses = [f for f in turned.features if isinstance(f, Boss)]
    assert [len(b.faces) for b in bosses] == [1, 1, 1]
    assert len(turned.features) == len(fs.features) + 1
    assert [d.letter for d in turned.frame.datums] == ["A", "B"]
    assert m.faces[turned.frame.datums[0].face].kind == "cylinder"
    assert TU.for_process(fs, "machined") is fs and TU.for_process("not a set", "turned") == "not a set"
    assert TU.for_process(replace(fs, turned=None), "turned").frame == fs.frame


def test_turned_parts_take_the_machined_entries_of_drawing_settings():
    assert settings_type("turned") == "machined"
    assert settings_type("printed") == "printed" and settings_type("machined") == "machined"


# --------------------------------------------------------------------------- drawings
def test_a_turned_drawing_shows_the_profile_with_the_larger_end_left():
    for name, right in (("stepped_shaft", (0.0, 0.0, 1.0)), ("small_end_first_shaft", (0.0, 0.0, -1.0))):
        run = _run(name)
        spec = next(s for s, _g in run.orchestrated.views if s.kind == "base")
        r, _up, d = spec.frame()
        assert r == pytest.approx(right) and abs(d[2]) < 1e-9, name
        assert run.drawing.options.front in ("+x", "-x", "+y", "-y")


def test_a_stepped_shaft_is_dimensioned_by_the_turned_rules():
    run = _run("stepped_shaft")
    texts = _texts(run)
    shown = {k: t for k, (t, _f) in texts.items()}
    assert shown == {
        "size/f-1": "Ø20.00",
        "size/f-2": "Ø12.00",
        "size/f-3": "Ø8.00",
        "size/f-4": "65.0",
        "chamfer/f-7": "1.0 X 45°",
        "loc/f-5/z": "20.00",
        "loc/f-6/z": "50.00",
        "datum/a": "A",
        "datum/b": "B",
    }
    # circular runout to A on every diameter but the datum's own
    frames = {k: f for k, (_t, f) in texts.items() if f is not None}
    assert set(frames) == {"size/f-1", "size/f-3"}
    assert all(f.characteristic == "circular_runout" and f.datums == ("A",) for f in frames.values())
    assert frames["size/f-1"].value == pytest.approx(0.1 * MM)
    dims = {d.key: d for d in run.drawing.dimensions}
    # the shoulders are placed from datum B by toleranced dimensions, not basic ones
    assert dims["loc/f-5/z"].tolerance == "block" and dims["loc/f-6/z"].tolerance == "block"
    assert all(d.view == "v-1" for d in dims.values())  # everything in the profile view
    assert [d.letter for d in run.drawing.datums] == ["A", "B"]
    assert not _errors(
        run.drawing, "R4.coincident", "R11.collisions", "R13.plusminus", "R18.datums", "R18.frames"
    )
    assert not [c for c in run.drawing.checks if c.level == "error"]


def test_set_datum_moves_a_to_another_diameter_and_the_runout_with_it():
    from solidseas.drawing import edit

    run = _run("stepped_shaft")
    big = next(f for f in run.features.features if isinstance(f, Boss) and abs(f.diameter - 20 * MM) < 1e-9)
    moved, _checks = edit.set_datum(run.drawing, "A", big.faces[0])
    assert [(d.letter, d.face) for d in moved.datums] == [
        ("A", big.faces[0]),
        ("B", run.drawing.datums[1].face),
    ]
    dims = {d.key: d for d in moved.dimensions}
    assert dims["size/f-1"].frame is None  # Ø20, now datum A
    assert dims["size/f-2"].frame.characteristic == "circular_runout"  # Ø12, no longer A
    assert dims["datum/a"].positions[0].value == pytest.approx(10 * MM)  # on Ø20's outline
    assert not [c for c in moved.checks if c.level == "error"]


def test_inch_diameters_and_shoulders_take_three_places():
    texts = {k: t for k, (t, _f) in _texts(_run("stepped_shaft", unit="in")).items()}
    assert texts["size/f-1"] == "Ø.787" and texts["loc/f-5/z"] == ".787" and texts["size/f-4"] == "2.56"


def test_equal_diameters_are_stated_once_with_their_count():
    run = _run("grooved_shaft")
    texts = _texts(run)
    assert texts["size/f-2"][0] == "2X Ø16.00" and texts["size/f-2"][1] is None  # datum A: the pair's axis
    assert texts["size/f-1"][0] == "Ø12.00" and texts["size/f-1"][1].characteristic == "circular_runout"
    assert not _errors(run.drawing, "R4.coincident", "R11.collisions", "R18.datums")


@pytest.mark.parametrize(
    "name", ["solid_shaft", "filleted_shaft", "bored_shaft", "bushing", "small_end_first_shaft"]
)
def test_every_synthetic_turned_part_draws_without_an_error(name):
    run = _run(name)
    assert not [c for c in run.drawing.checks if c.level == "error"], name
    assert any(d.key == "datum/a" for d in run.drawing.dimensions)


def test_a_bore_keeps_its_callout_in_the_end_view_until_half_sections_come():
    texts = _texts(_run("bored_shaft"))
    assert texts["callout/f-1"][0] == "Ø8.00 THRU"


def test_the_plus_minus_scheme_draws_no_datums_or_runout():
    run = _run("stepped_shaft", scheme="plusminus")
    texts = _texts(run)
    assert all(f is None for _t, f in texts.values())
    assert not any(k.startswith("datum/") for k in texts)
    assert any(c.code == "R13.plusminus" for c in run.drawing.checks)


def test_a_machined_drawing_of_a_turned_part_keeps_the_machined_rules():
    run = _run("stepped_shaft", process="machined")
    assert [d.letter for d in run.drawing.datums] == ["A"]
    assert run.features.frame.datums[0].reason == "the largest planar face"
    kinds = {d.key: d.kind for d in run.drawing.dimensions}
    assert kinds["size/f-1"] == "diameter"  # a leader in the circular view, as before


def test_a_turned_part_from_its_parasolid_file_is_drawn_and_updated(tmp_path):
    xt, _truth = T.stepped_shaft()
    path = _x_t(xt, str(tmp_path / "shaft.x_t"))
    d = make_drawing(
        path, options=DrawingOptions(units="mm", process="turned"), settings=G.settings(), fields=FIELDS
    )
    assert d.options.process == "turned" and d.model["format"] == "parasolid"
    saved = str(tmp_path / "shaft.ssdrw")
    save_drawing(d, saved)
    loaded = load_drawing(saved)
    assert loaded.options.process == "turned"
    # the Ø12 grows to Ø13: the update keeps the drawing's ids and changes that diameter
    grown, _truth = T.revolve(
        T._shaft([(20 * MM, 20 * MM), (13 * MM, 30 * MM), (8 * MM, 15 * MM)], chamfer=1 * MM), "stepped_shaft"
    )
    newer = _x_t(grown, str(tmp_path / "shaft_b.x_t"))
    merged, report = regenerate_drawing(loaded, source=newer)
    before = {r.key: r.value for r in loaded.dimensions}
    after = {r.key: r.value for r in merged.dimensions}
    assert after["size/f-2"] == pytest.approx(13 * MM) and before["size/f-2"] == pytest.approx(12 * MM)
    assert set(after) == set(before) and report.changed >= 1


def test_the_command_line_draws_a_turned_part(tmp_path, capsys):
    xt, _truth = T.bushing()
    (tmp_path / "parts").mkdir()
    part = _x_t(xt, str(tmp_path / "parts" / "bushing.x_t"))
    out = tmp_path / "out"
    out.mkdir()
    code = cli.main(
        ["drawing", "new", part, "--process", "turned", "--units", "mm", "--out", str(out), "--number", "B-1"]
    )
    assert code == 0, capsys.readouterr()
    written = list(out.iterdir())
    assert [p.suffix for p in written] == [".ssdrw"]
    assert load_drawing(str(written[0])).options.process == "turned"


def test_the_feature_set_keeps_no_profile_for_an_assembly():
    assert FeatureSet().turned is None
