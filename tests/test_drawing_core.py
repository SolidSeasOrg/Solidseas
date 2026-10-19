"""The drawing core: bounds, contracts, the display list and its compact form, the
painter's curves, fonts, standards, signatures and the pipeline's capability gaps
(docs/DRAWINGS.md 5 to 7, 17, 22)."""

import json
import math
from fractions import Fraction

import pytest

from drawing_support import fixture, sample_sheet
from solidseas import drawing
from solidseas.drawing import display as D
from solidseas.drawing import fonts, keys, painter, pipeline, standards, types
from solidseas.drawing.limits import DEFAULT_LIMITS, DrawingLimits
from solidseas.errors import InvalidArgumentError, SldLimitError, UnsupportedOperationError

# --------------------------------------------------------------------------- limits


def test_the_default_limits_are_the_designs():
    assert (DEFAULT_LIMITS.faces, DEFAULT_LIMITS.edges, DEFAULT_LIMITS.triangles) == (
        50_000,
        150_000,
        400_000,
    )
    assert DEFAULT_LIMITS.seconds_total == 150.0 and DEFAULT_LIMITS.views == 12 and DEFAULT_LIMITS.sheets == 1
    assert DEFAULT_LIMITS.settings_bytes == 256 * 1024 and DEFAULT_LIMITS.json_depth == 32


@pytest.mark.parametrize(
    "kw",
    [{"faces": 0}, {"faces": 10**9}, {"faces": 2.5}, {"faces": True}, {"seconds_views": "90"}, {"sheets": 2}],
)
def test_limits_are_checked_when_made(kw):
    with pytest.raises(InvalidArgumentError):
        DrawingLimits(**kw)


def test_a_part_over_the_bounds_is_refused_with_its_counts():
    small = DrawingLimits(faces=100)
    assert small.refuse(faces=99) is None
    assert "101 faces" in small.refuse(faces=101)
    err = small.exceeded("faces", "too many")
    assert isinstance(err, SldLimitError) and err.detail == {"limit": "faces", "value": 100}


# --------------------------------------------------------------------------- contracts


def test_options_are_checked_and_the_scheme_follows_the_process():
    assert types.DrawingOptions().effective_scheme == "datum"
    assert types.DrawingOptions(process="printed").effective_scheme == "plusminus"
    assert types.DrawingOptions(process="printed", scheme="datum").effective_scheme == "datum"
    good = types.DrawingOptions(
        views=("front", "top"), scale=(1, 2), arrangement=(("v-1/x", "ordinate"),), turn=1
    )
    assert good.scale == (1, 2)
    for bad in (
        {"process": "turned"},
        {"scheme": "chain"},
        {"units": "cm"},
        {"views": ("front", "aux")},
        {"turn": 4},
        {"scale": (0, 1)},
        {"scale": "1:2"},
        {"arrangement": (("v-1", "baseline"),)},
        {"sheet": "F"},
        {"quality": "best"},
    ):
        with pytest.raises(InvalidArgumentError):
            types.DrawingOptions(**bad)


def test_view_frames_and_axis_maps():
    def spec(name):
        d, up = types.STANDARD_VIEWS[name]
        return types.ViewSpec(f"v-{name}", "base", d, up, name)

    assert spec("front").axis_map() == {"x": ("x", 1), "y": ("y", 1)}
    assert spec("top").axis_map() == {"x": ("x", 1), "y": ("z", -1)}
    assert spec("right").axis_map() == {"x": ("z", -1), "y": ("y", 1)}
    assert spec("isometric").axis_map() == {}
    right, up, d = spec("isometric").frame()
    assert abs(sum(a * b for a, b in zip(right, up, strict=True))) < 1e-12
    assert spec("front").project((0.01, 0.02, 0.03)) == (0.01, 0.02)
    with pytest.raises(InvalidArgumentError):
        types.ViewSpec("V 1", "base", (0, 0, 1), (0, 1, 0))


def test_requirement_keys_are_role_features_and_axis():
    assert types.requirement_key("loc", ["f-7"], "x") == "loc/f-7/x"
    assert types.requirement_key("size", ("f-3",)) == "size/f-3"
    with pytest.raises(InvalidArgumentError):
        types.requirement_key("loc", ["F 7"], "x")
    r = types.Requirement(
        "size/f-3", "size", ("f-3",), 0.008, "feature_size", satisfied_by=("linear", "leader_note")
    )
    assert "leader_note" in r.satisfied_by
    with pytest.raises(InvalidArgumentError):
        types.Requirement("size/f-3", "size", ("f-3",), 0.008, "feature_size", satisfied_by=("hole_table",))


def test_planned_dimensions_and_the_drawing_are_checked():
    d = types.PlannedDimension("loc/f-7/x", "d-12", "linear", "v-1", 0.02, axis="x")
    assert d.state == "shown" and d.origin == "generated"
    with pytest.raises(InvalidArgumentError):
        types.PlannedDimension("loc/f-7/x", "d 12", "linear", "v-1", 0.02)
    with pytest.raises(InvalidArgumentError):
        types.Drawing("x", types.DrawingOptions(), None, status="DONE")


def test_witnesses_answer_where_a_visible_line_is():
    w = (
        types.Witness("x", 0.010, 0.0, 0.02),
        types.Witness("x", 0.010, 0.0, 0.05),
        types.Witness("y", 0.010, 0, 1),
    )
    g = types.ViewGeometry("v-1", witnesses=w)
    assert g.witness_at("x", 0.0100004, 1e-6).high == 0.05
    assert g.witness_at("x", 0.02, 1e-6) is None


def test_coverage_says_reduced_dimension_in_words():
    full = types.Coverage(features=3, faces=10, faces_claimed=10, area=1.0, area_claimed=1.0)
    assert full.complete and "every" in full.words()
    part = types.Coverage(
        features=3, features_unclaimed=2, faces=100, faces_claimed=93, area=1.0, area_claimed=0.97
    )
    assert (
        part.words()
        == "reduced-dimension drawing: 7 faces (3 % of the area, 2 features) are defined by the model"
    )


# --------------------------------------------------------------------------- display list


def test_the_compact_sheet_round_trips_in_micrometres():
    sheet = sample_sheet()
    data = json.loads(json.dumps(D.to_compact(sheet)))
    again = D.from_compact(data)
    assert again.views == sheet.views and again.annotations == sheet.annotations
    for a, b in zip(again.geometry, sheet.geometry, strict=True):
        assert type(a) is type(b) and a.style == b.style
    assert all(isinstance(v, int) for v in data["sheet"]["v"][1:3])  # width, height in micrometres
    assert data["sheet"]["v"][1] == 279400


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {"schema": "other", "sheet": {}},
        {"schema": D.SCHEMA, "sheet": {"k": "nope", "v": []}},
        {"schema": D.SCHEMA, "sheet": {"k": "sheet", "v": [1]}},
        {"schema": D.SCHEMA, "sheet": {"k": "sheet", "v": ["A", 1.5, 1, [1, 1], [], [], [], []]}},
        {
            "schema": D.SCHEMA,
            "sheet": {"k": "seg", "v": [[0, 0], [1, 1], "visible", {"k": "src", "v": [0, "", ""]}]},
        },
    ],
)
def test_a_bad_compact_sheet_is_refused(bad):
    with pytest.raises(InvalidArgumentError):
        D.from_compact(bad)


def test_a_deeply_nested_compact_sheet_is_refused():
    deep: list = []
    for _ in range(40):
        deep = [deep]
    bad = {"schema": D.SCHEMA, "sheet": {"k": "sheet", "v": ["A", 1, 1, [1, 1], deep, [], [], []]}}
    with pytest.raises(InvalidArgumentError):
        D.from_compact(bad)


def test_placing_geometry_scales_it_from_view_metres():
    v = D.ViewPlacement("v-1", (100.0, 50.0), 0.5)
    seg = D.place(D.Segment((0.01, 0.02), (0.03, 0.02)), v)
    assert seg.p0 == pytest.approx((105.0, 60.0)) and seg.p1 == pytest.approx((115.0, 60.0))
    arc = D.place(D.Arc((0.0, 0.0), 0.01), v)
    assert arc.radius == pytest.approx(5.0)
    assert v.to_view(v.to_sheet((0.01, 0.02))) == pytest.approx((0.01, 0.02))


def test_spline_and_arc_shapes_are_checked():
    with pytest.raises(InvalidArgumentError):
        D.Spline(3, (0, 1), ((0, 0), (1, 1)))
    assert D.Arc((0, 0), 1.0, 350.0, 10.0).sweep() == pytest.approx(20.0)
    assert D.Arc((0, 0), 1.0, 0.0, 360.0).sweep() == 360.0
    x0, y0, x1, y1 = D.Arc((0, 0), 1.0, 350.0, 10.0).bounds()
    assert x1 == pytest.approx(1.0) and x0 > 0.98


# --------------------------------------------------------------------------- painter


def _bezier(t, p):
    u = 1 - t
    return tuple(
        u**3 * a + 3 * u * u * t * b + 3 * u * t * t * c + t**3 * d for a, b, c, d in zip(*p, strict=True)
    )


def test_arcs_become_beziers_within_three_hundredths_of_a_percent():
    ops = painter.arc_beziers(0.0, 0.0, 10.0, 0.0, 360.0)
    assert len(ops) == 4
    start = (10.0, 0.0)
    worst = 0.0
    for op in ops:
        p = (start, op[1:3], op[3:5], op[5:7])
        for k in range(21):
            worst = max(worst, abs(math.hypot(*_bezier(k / 20, p)) - 10.0))
        start = op[5:7]
    assert worst / 10.0 < 3e-4
    assert painter.arc_beziers(0, 0, 1, 0, 0) == []


def test_b_splines_of_degree_three_or_less_become_beziers_exactly():
    U = (0, 0, 0, 0, 0.3, 0.7, 1, 1, 1, 1)
    P = ((0, 0), (1, 3), (3, 4), (5, 1), (7, 2), (9, 0))
    pieces = painter.spline_beziers(3, U, P)
    assert len(pieces) == 3
    spans = [(0, 0.3), (0.3, 0.7), (0.7, 1.0)]
    for (a, b), piece in zip(spans, pieces, strict=True):
        for k in range(11):
            t = k / 10
            exact = painter._de_boor(3, U, P, None, a + (b - a) * t)
            assert math.dist(_bezier(t, piece), exact) < 1e-12
    quad = painter.spline_beziers(2, (0, 0, 0, 0.5, 1, 1, 1), ((0, 0), (1, 2), (2, 0), (3, 1)))
    assert len(quad) == 2 and quad[0][0] == (0.0, 0.0) and quad[-1][-1] == (3.0, 1.0)
    with pytest.raises(ValueError):
        painter.spline_beziers(4, (0,) * 5 + (1,) * 5, ((0, 0),) * 5)


def test_a_rational_spline_is_drawn_through_its_points():
    s = D.Spline(2, (0, 0, 0, 1, 1, 1), ((1.0, 0.0), (1.0, 1.0), (0.0, 1.0)), (1.0, math.sqrt(0.5), 1.0))
    ops = painter.path_of(s)
    assert ops[0][0] == "M" and all(op[0] == "L" for op in ops[1:])
    assert all(abs(math.hypot(op[1], op[2]) - 1.0) < 1e-9 for op in ops)  # a true quarter circle


def test_ellipse_arcs_map_the_circle_through_their_frame():
    e = D.EllipseArc((5.0, 5.0), (2.0, 0.0), 0.5, 0.0, math.pi)
    ops = painter.path_of(e)
    assert ops[0] == ("M", 7.0, 5.0)
    assert ops[-1][-2:] == pytest.approx((3.0, 5.0))
    assert len(ops) == 3  # two quarter pieces


def test_paint_replays_the_painted_layer_by_layer():
    rec = painter.RecordingPainter()
    painter.paint(sample_sheet(), rec)
    names = [c[0] for c in rec.calls]
    assert names[0] == "begin_page" and names[-1] == "end_page"
    groups = [c[1] for c in rec.calls if c[0] == "group"]
    assert groups.index("visible") < groups.index("hidden") < groups.index("dimensions")
    assert names.count("group") == names.count("end_group")
    assert ("text", 85.0, 73.0, fonts.font_size(3.0), 0.0, "100", "Helvetica", "centre") in rec.calls
    assert isinstance(rec, painter.Painter)


def test_strokes_take_the_standards_widths_and_dashes():
    strokes = painter.stroke_geometry(
        [D.Segment((0, 0), (1, 0), "visible"), D.Segment((0, 0), (1, 0), "hidden")]
    )
    assert strokes[0].width == 0.6 and strokes[0].dash == ()
    assert strokes[1].width == 0.3 and strokes[1].dash == standards.LINES["hidden"].dash
    assert strokes[1].layer == "hidden"


# --------------------------------------------------------------------------- fonts


def test_helvetica_widths_for_the_drawing_characters():
    assert fonts.advance("0") == 556 and fonts.advance("W") == 944 and fonts.advance("i") == 222
    assert fonts.advance("Ø") == 778 and fonts.advance("±") == 584 and fonts.advance("°") == 400
    assert fonts.advance("×") == 584
    assert fonts.advance("b", bold=True) == 611 and fonts.advance("b") == 556  # bold has its own widths
    assert fonts.measure("1000", 10.0) == pytest.approx(22.24)
    assert fonts.font_size(3.0) == pytest.approx(3.0 / 0.718)
    assert fonts.measure_height("A", 3.0) == pytest.approx(667 * 3.0 / 0.718 / 1000)


def test_every_winansi_character_has_a_width():
    for code in list(range(0x20, 0x7F)) + list(range(0xA0, 0x100)):
        assert fonts.advance(chr(code)) > 0 and fonts.advance(chr(code), True) > 0


def test_text_outside_winansi_is_named_and_refused():
    assert fonts.unsupported("4X Ø.266 ⌴ 漢⌴") == ["⌴", "漢"]
    assert fonts.encode("Ø.500 ±.005") == b"\xd8.500 \xb1.005"
    assert fonts.encode("\u2013") == b"\x96"
    with pytest.raises(ValueError):
        fonts.encode("⌖")


# --------------------------------------------------------------------------- standards


def test_sheets_margins_and_scales():
    assert standards.SHEETS["A"].size() == (279.4, 215.9)
    assert standards.SHEETS["A"].size("portrait") == (215.9, 279.4)
    assert standards.SHEETS["B"].margin == pytest.approx(9.652) and standards.SHEETS[
        "D"
    ].margin == pytest.approx(12.7)
    assert standards.scale_text((1, 2)) == "1:2" and standards.scale_factor((4, 1)) == 4.0
    assert standards.parse_scale("1:2") == (1, 2) and standards.parse_scale(" 10 : 1 ") == (10, 1)
    for bad in ("1:0", "a:b", "1:2:3", "", "99999:1", None):
        assert standards.parse_scale(bad) is None


def test_revision_letters_skip_and_roll_over():
    letters = standards.revision_letters(21)
    assert letters[:8] == ["A", "B", "C", "D", "E", "F", "G", "H"]
    assert not set("IOQSXZ") & set("".join(letters))
    assert letters[-1] == "AA" and letters[-2] == "Y"
    assert standards.next_revision("AY") == "BA" and standards.next_revision("YY") == "AAA"
    with pytest.raises(ValueError):
        standards.next_revision("I")
    views = standards.view_letters()
    first = [next(views) for _ in range(23)]
    assert (
        "I" not in first and "O" not in first and "Q" not in first and "X" not in first and first[-1] == "AA"
    )


def test_iso_2768_tables():
    assert standards.iso2768_linear(10.0, "m") == Fraction(2, 10)
    assert standards.iso2768_linear(3.0, "f") == Fraction(5, 100)
    assert standards.iso2768_linear(2500.0, "f") is None
    assert standards.iso2768_linear(0.3, "m") is None
    assert standards.iso2768_radius(4.0, "c") == 1
    assert standards.iso2768_angle_minutes(30.0, "m") == 30
    assert standards.iso2768_angle_minutes(1000.0, "v") == 20
    with pytest.raises(ValueError):
        standards.iso2768_linear(10.0, "x")


def test_threads_are_candidates_from_the_tap_drill_tables():
    assert [t.designation for t in standards.threads_for_drill(0.0050)] == ["M6 x 1"]
    assert "1/4-20 UNC" in [t.designation for t in standards.threads_for_drill(0.201 * 0.0254)]
    assert [t.internal() for t in standards.threads_for_drill(0.0068)] == ["M8 x 1.25-6H"]
    assert standards.threads_for_drill(0.0061) == ()
    m6 = standards.threads_for_drill(0.005)[0]
    assert standards.thread_depth_suggestion(0.015, m6) == pytest.approx(0.012)


def test_process_tolerances_are_the_service_bureau_figures():
    sla = standards.PROCESSES["sla"]
    assert sla.tolerance_mm(100.0) == pytest.approx(0.0508 + 0.1)
    assert sla.tolerance_mm(100.0, along_z=True) == pytest.approx(0.127 + 0.1)
    assert standards.PROCESSES["fdm"].tolerance_mm(20.0) == 0.5  # the floor
    assert standards.PROCESSES["fdm"].tolerance_mm(200.0) == pytest.approx(1.0)


def test_gdt_characteristics():
    assert standards.CHARACTERISTICS["position"].datums == "optional"
    assert standards.CHARACTERISTICS["flatness"].datums == "never"
    assert standards.CHARACTERISTICS["perpendicularity"].kind == "orientation"


# --------------------------------------------------------------------------- signatures


def test_signatures_are_canonical_and_rounded():
    assert keys.plane((0, 0, -1), (5, 5, 0.01), 1e-7) == keys.plane((0, 0, 1), (0, 0, 0.01), 1e-7)
    a = keys.cylinder((0.01, 0.0, 5.0), (0, 0, 1), 0.003, 1e-7)
    b = keys.cylinder((0.01, 0.0, -2.0), (0, 0, -1), 0.003, 1e-7)
    assert a == b
    assert keys.line_edge((0, 0, 0), (1, 0, 0), 1e-7) == keys.line_edge((1, 0, 0), (0, 0, 0), 1e-7)
    assert keys.q(-0.0, 1e-7) == 0 and keys.q(2.5e-7, 1e-7) == 3
    assert keys.digest(["b", "a"]) == keys.digest(["a", "b"])


def test_descriptors_are_rounded_sorted_and_compared_by_size():
    a = keys.descriptor("Hole", {"diameter": 0.0066000001, "through": True}, {"entry": "+z"}, (0.012, 0.01))
    b = keys.descriptor("Hole", {"through": True, "diameter": 0.0066}, {"entry": "+z"}, (0.0120000004, 0.01))
    assert a == b
    assert a.to_dict()["size"] == {"diameter": 0.0066, "through": True}
    c = keys.descriptor("Hole", {"diameter": 0.0067, "through": True})
    assert not keys.same_size(a, c, 1e-5) and keys.same_size(a, c, 2e-4)


# --------------------------------------------------------------------------- pipeline


def test_a_missing_stage_is_a_capability_gap():
    have = pipeline.available()
    missing = [name for name, _path in pipeline.STAGES if not have[name]]
    if not missing:
        pytest.skip("every stage is built")
    with pytest.raises(UnsupportedOperationError) as info:
        drawing.make_drawing(fixture("o11_curved.SLDPRT"))
    assert info.value.code == "not_implemented"
    assert info.value.detail == {"rule": "stage_missing", "value": missing[0]}
    calls = {
        "load": lambda: drawing.load("x.ssdrw"),
        "write_pdf": lambda: drawing.write_pdf(None, None),
        "regenerate": lambda: drawing.regenerate(None),
    }
    for name, call in calls.items():
        if have[name]:
            continue
        with pytest.raises(UnsupportedOperationError) as info:
            call()
        assert info.value.detail == {"rule": "stage_missing", "value": name}


def test_a_stage_that_does_not_exist_is_named():
    with pytest.raises(UnsupportedOperationError) as info:
        pipeline.resolve("later", "solidseas.drawing.not_yet_built:make")
    assert info.value.detail == {"rule": "stage_missing", "value": "later"}
    with pytest.raises(UnsupportedOperationError):
        pipeline.resolve("later", "solidseas.drawing.limits:not_there")


def test_built_stages_run_and_a_branch_can_drive_its_own():
    have = pipeline.available()
    assert have["source"] and have["model"]
    run = pipeline.run(fixture("o11_curved.SLDPRT"), until="model")
    assert run.source.name == "o11_curved.SLDPRT" and len(run.model.faces) == 12
    assert [name for name, _s in run.seconds] == ["source", "model"]
    seen = []
    run = pipeline.run(
        fixture("o02_boxA.SLDPRT"), until="features", stages={"features": lambda m: seen.append(m) or "fs"}
    )
    assert run.features == "fs" and len(seen[0].faces) == 6


def test_the_pipeline_checks_its_arguments():
    for kw in (
        {"options": "x"},
        {"settings": {}},
        {"limits": 3},
        {"until": "nope"},
        {"stages": {"nope": print}},
        {"fields": {"title": "x" * 300}},
    ):
        with pytest.raises(InvalidArgumentError):
            pipeline.run(fixture("o02_boxA.SLDPRT"), **kw)


def test_a_stage_over_its_time_is_stopped():
    slow = DrawingLimits(seconds_features=0.01)

    def features(_m):
        import time

        time.sleep(0.05)
        return "fs"

    with pytest.raises(SldLimitError) as info:
        pipeline.run(fixture("o02_boxA.SLDPRT"), until="features", stages={"features": features}, limits=slow)
    assert info.value.detail["limit"] == "seconds_features"
