"""Replies are untrusted: the one JSON parser, the plan validator and the draft parser.

The plan validator refuses NaN, Infinity, 1e999, a bool where a number is expected, a
value out of range, an unknown operation, an unresolved handle, a plan over the step
limit and a protected or formula-like property (``docs/ASSISTANT.md``, "Tests the design
requires"), and every other rule of the vocabulary table.
"""

import json
import math
import time

import pytest

from ai_support import box_snapshot, handle_of, mm, parse, plan_json, square, step, summary_of
from solidseas.ai import prompts
from solidseas.ai.context import build_model_summary, prepare_request
from solidseas.ai.errors import InvalidSettingError, ReplyInvalidError
from solidseas.ai.prompts import MODEL, OPERATIONS, SAID, PlanLimits, parse_draft, parse_json_response

S = summary_of()
WIDTH = handle_of(S, "pr:dim:width")
ANGLE = handle_of(S, "pr:dim:angle")
FRONT = handle_of(S, "pr:plane:front")
TOP_FACE = handle_of(S, "pr:face:top")
HOLE_FACE = handle_of(S, "pr:face:hole")
SIDE_FACE = handle_of(S, "pr:face:front")
EDGE = handle_of(S, "pr:edge:top0")
EDGE2 = handle_of(S, "pr:edge:top1")
CIRCLE_EDGE = handle_of(S, "pr:edge:hole")
AXIS = handle_of(S, "pr:axis:hole")
BOSS = handle_of(S, "pr:feat:boss")
HOLE = handle_of(S, "pr:feat:hole")


def refused(text, *, goal="", limits=None, summary=None) -> str:
    with pytest.raises(ReplyInvalidError) as info:
        parse(text, goal=goal, limits=limits, summary=summary or S)
    return str(info.value)


# --------------------------------------------------------------------------- parse_json_response
@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        '```\n{"a": 1}\n```',
        'Here is the plan:\n```json\n{"a": 1}\n```\nLet me know.',
        'Sure! {"a": 1} Hope that helps.',
        '  \n{"a": 1}\n  ',
    ],
)
def test_json_is_found_bare_fenced_or_in_prose(text):
    assert parse_json_response(text) == {"a": 1}


@pytest.mark.parametrize(
    "text, words",
    [
        ('{"a": NaN}', "NaN"),
        ('{"a": Infinity}', "Infinity"),
        ('{"a": -Infinity}', "-Infinity"),
        ('{"a": 1e999}', "finite"),
        ('{"a": [1, {"b": -1e400}]}', "finite"),
        ('```json\n{"a": NaN}\n```', "NaN"),
        ('{"a": 1, "a": 2}', "twice"),
        ('{"steps": [{"op": "fillet", "op": "shell"}]}', "twice"),
    ],
)
def test_non_finite_numbers_and_repeated_keys_are_refused(text, words):
    with pytest.raises(ReplyInvalidError) as info:
        parse_json_response(text)
    assert words in str(info.value)


@pytest.mark.parametrize("text", ["", "no json here", "{not json}", "[1, 2", None, 42, b'{"a": 1}'])
def test_anything_else_is_refused(text):
    with pytest.raises(ReplyInvalidError):
        parse_json_response(text)


def test_an_overlong_reply_is_refused():
    with pytest.raises(ReplyInvalidError):
        parse_json_response('{"a": "' + "x" * prompts.MAX_REPLY_CHARS + '"}')


def test_deep_nesting_is_refused_not_a_crash():
    with pytest.raises(ReplyInvalidError):
        parse_json_response("[" * 100_000 + "]" * 100_000)


DRAFT_JSON = '{"language": "python", "code": "x = 1", "explanation": "ok"}'


HOSTILE_REPLIES = {
    "fence then spaces": lambda: "```" + " " * 200_000 + "!",
    "fence then tabs": lambda: "```" + "\t" * 200_000 + "!",
    "fence, tag, blanks": lambda: "```json" + " \t" * 100_000 + "!",
    "a draft, then a fence and spaces": lambda: DRAFT_JSON + "\n```" + " " * 200_000 + ".",
    "many distinct fences": lambda: "".join(f"```\nx{i}```" for i in range(30_000)),
    "backticks": lambda: "`" * 300_000,
    "openers": lambda: "```\n" * 90_000,
}


@pytest.mark.parametrize("shape", list(HOSTILE_REPLIES))
def test_a_hostile_reply_is_read_in_linear_time(shape):
    """A fence opener followed by a long run of blanks took time quadratic in its length
    (16,000 blanks took 1.7 s, 200,000 would take minutes) while holding the interpreter
    lock, so the whole app froze; distinct fences were compared pairwise. Each of these
    must be read or refused at once."""
    text = HOSTILE_REPLIES[shape]()
    parses = shape.startswith("a draft")
    start = time.perf_counter()
    if parses:
        assert parse_draft(text).code == "x = 1"
    else:
        with pytest.raises(ReplyInvalidError):
            parse_json_response(text)
    assert time.perf_counter() - start < 1.0


# --------------------------------------------------------------------------- a valid plan of every operation
def every_operation_steps():
    return [
        step("set_dimension", dimension=WIDTH, value=mm(45)),
        step("set_dimension", dimension=ANGLE, value={"value": 30, "unit": "deg"}),
        step(
            "sketch_extrude_boss",
            plane=TOP_FACE,
            profile=square(5, 2, 2),
            depth=mm(3),
            direction="normal",
            end="blind",
        ),
        step("sketch_extrude_cut", plane=FRONT, profile=square(5), direction="reversed", end="through_all"),
        step(
            "sketch_extrude_cut", plane=FRONT, profile=square(5), depth=mm(2), direction="normal", end="blind"
        ),
        step("fillet", edges=[EDGE, EDGE2], radius=mm(1)),
        step("chamfer", edges=[EDGE], distance={"value": 0.02, "unit": "in"}),
        step("shell", faces=[TOP_FACE], thickness=mm(2)),
        step("shell", faces=[], thickness=mm(1), direction="inward"),
        step("linear_pattern", seeds=[HOLE], direction=EDGE, spacing=mm(8), count=3),
        step("circular_pattern", seeds=[BOSS], axis=HOLE_FACE, count=4),
        step("circular_pattern", seeds=[BOSS], axis=AXIS, count=2),
        step("suppress", features=[HOLE]),
        step("unsuppress", features=[HOLE, BOSS]),
        step("set_property", name="Description", value="Lid, 2 mm shell", scope="file"),
    ]


def test_a_plan_of_every_operation_is_accepted():
    steps = every_operation_steps()
    assert {s["op"] for s in steps} == set(OPERATIONS)
    plan = parse(plan_json(*steps, notes="ok"), goal="whatever")
    assert [s.op for s in plan.steps] == [s["op"] for s in steps]
    assert [s.index for s in plan.steps] == list(range(1, len(steps) + 1))
    assert plan.vocabulary == prompts.VOCABULARY_VERSION and plan.notes == "ok"
    assert plan.new_instances == 2 + 3 + 1
    first = plan.steps[0]
    assert (
        first.args["value"].metres == pytest.approx(0.045)
        and first.args["dimension"].targets[0].ref == "pr:dim:width"
    )
    chamfer = plan.steps[6].args["distance"]
    assert chamfer.unit == "in" and chamfer.mm == pytest.approx(0.508)
    assert set(plan.refs()) >= {"pr:dim:width", "pr:face:top", "pr:edge:top0", "pr:feat:hole"}


def test_profiles_hold_lines_arcs_and_circles_in_metres_and_close_exactly():
    profile = {
        "unit": "mm",
        "segments": [
            {"type": "line", "start": [0, 0], "end": [10, 0]},
            {"type": "arc", "center": [10, 5], "start": [10, 0], "end": [10.0000004, 10], "direction": "ccw"},
            {"type": "line", "start": [10, 10], "end": [0, 10]},
            {"type": "line", "start": [0, 10], "end": [0.0000003, 0.0000002]},
            {"type": "circle", "center": [5, 5], "radius": 1.5},
        ],
    }
    plan = parse(
        plan_json(
            step(
                "sketch_extrude_boss",
                plane=FRONT,
                profile=profile,
                depth=mm(1),
                direction="normal",
                end="blind",
            )
        )
    )
    segs = plan.steps[0].args["profile"].segments
    assert [s.type for s in segs] == ["line", "arc", "line", "line", "circle"]
    assert segs[0].end == (0.01, 0.0) and segs[1].center == (0.01, 0.005) and not segs[1].clockwise
    assert segs[4].radius == pytest.approx(0.0015)
    # the near-miss end points within a micrometre were snapped onto the point they meet
    assert segs[1].end == segs[2].start and segs[3].end == segs[0].start


# --------------------------------------------------------------------------- the refusals the design requires
@pytest.mark.parametrize(
    "raw",
    [
        '{"value": NaN, "unit": "mm"}',
        '{"value": Infinity, "unit": "mm"}',
        '{"value": -Infinity, "unit": "mm"}',
        '{"value": 1e999, "unit": "mm"}',
    ],
)
def test_non_finite_values_refuse_the_plan(raw):
    args = '{"edges": ["' + EDGE + '"], "radius": ' + raw + "}"
    text = '{"vocabulary": 1, "steps": [{"op": "fillet", "args": ' + args + "}]}"
    refused(text)


@pytest.mark.parametrize("value", [True, False, "2", None, [2], {"value": 2}])
def test_a_bool_or_other_non_number_where_a_number_is_expected_is_refused(value):
    assert "must be a number" in refused(
        plan_json(step("fillet", edges=[EDGE], radius={"value": value, "unit": "mm"}))
    )


@pytest.mark.parametrize("count", [True, 3.0, "3", 1, 51, -2])
def test_counts_are_whole_numbers_in_range(count):
    refused(plan_json(step("linear_pattern", seeds=[HOLE], direction=EDGE, spacing=mm(5), count=count)))


@pytest.mark.parametrize(
    "value, reason",
    [
        (mm(0.001), "more than 0.001 mm"),  # the bound is exclusive
        (mm(0.0005), "more than"),
        (mm(0), "more than"),
        (mm(-2), "more than"),
        (mm(10 * 51.0 + 1), "at most"),  # ten times the box diagonal (about 51 mm)
        ({"value": 30, "unit": "in"}, "at most"),
        ({"value": 2, "unit": "cm"}, "mm or in"),
        ({"value": 2}, "lacks unit"),
        ({"value": 2, "unit": "mm", "tolerance": 1}, "unknown fields"),
        (2, "must be an object"),
    ],
)
def test_lengths_out_of_range_or_without_a_unit_are_refused(value, reason):
    assert reason in refused(plan_json(step("fillet", edges=[EDGE], radius=value)))


def test_values_are_never_clamped_and_the_limit_follows_the_part():
    diagonal = math.dist((0, 0, 0), (40, 30, 10))
    assert parse(plan_json(step("fillet", edges=[EDGE], radius=mm(10 * diagonal - 0.01))))
    refused(plan_json(step("fillet", edges=[EDGE], radius=mm(10 * diagonal + 0.01))))
    empty = build_model_summary(box_snapshot(solid=False))
    assert not empty.has_solid_body
    plane = handle_of(empty, "pr:plane:front")
    big = plan_json(
        step(
            "sketch_extrude_boss",
            plane=plane,
            profile=square(900),
            depth=mm(999),
            direction="normal",
            end="blind",
        )
    )
    assert parse(big, summary=empty)
    refused(
        plan_json(
            step(
                "sketch_extrude_boss",
                plane=plane,
                profile=square(10),
                depth=mm(1001),
                direction="normal",
                end="blind",
            )
        ),
        summary=empty,
    )


@pytest.mark.parametrize("angle", [0, 360, -10, 400])
def test_angles_are_more_than_0_and_less_than_360(angle):
    refused(plan_json(step("set_dimension", dimension=ANGLE, value={"value": angle, "unit": "deg"})))


def test_a_dimension_takes_the_kind_of_value_it_is():
    assert "unit must be deg" in refused(plan_json(step("set_dimension", dimension=ANGLE, value=mm(5))))
    assert "mm or in" in refused(
        plan_json(step("set_dimension", dimension=WIDTH, value={"value": 5, "unit": "deg"}))
    )


@pytest.mark.parametrize("op", ["delete", "save", "open_file", "run_macro", "SET_DIMENSION", "", None, 3])
def test_an_unknown_operation_refuses_the_plan(op):
    assert "not an operation" in refused(plan_json({"op": op, "args": {}}))


@pytest.mark.parametrize("handle", ["E999", "F0", "D1@Sketch2", "pr:edge:top0", "", 5, None, "e1"])
def test_an_unresolved_handle_refuses_the_plan(handle):
    refused(plan_json(step("fillet", edges=[handle], radius=mm(1))))


def test_a_handle_of_the_wrong_kind_or_type_is_refused():
    assert "not allowed" in refused(plan_json(step("fillet", edges=[TOP_FACE], radius=mm(1))))
    assert "not allowed" in refused(
        plan_json(
            step(
                "sketch_extrude_boss",
                plane=HOLE_FACE,
                profile=square(),
                depth=mm(1),
                direction="normal",
                end="blind",
            )
        )
    )
    assert "not allowed" in refused(
        plan_json(step("linear_pattern", seeds=[HOLE], direction=CIRCLE_EDGE, spacing=mm(5), count=2))
    )
    assert "not allowed" in refused(
        plan_json(step("circular_pattern", seeds=[HOLE], axis=SIDE_FACE, count=2))
    )
    assert "not allowed" in refused(plan_json(step("set_dimension", dimension=BOSS, value=mm(5))))


def test_a_handle_whose_persist_reference_is_not_unique_resolves_to_nothing():
    summary = build_model_summary(box_snapshot(duplicate_ref=True))
    dup = [h for h in summary.handles.handles() if summary.handles.resolve(h) is None]
    assert len(dup) == 2  # both entities that report pr:edge:top0
    refused(plan_json(step("fillet", edges=[dup[0]], radius=mm(1))), summary=summary)


def test_the_same_entity_twice_is_refused():
    assert "twice" in refused(plan_json(step("fillet", edges=[EDGE, EDGE], radius=mm(1))))


def test_list_sizes_follow_the_table():
    edges = [h for h in S.handles.handles() if h.startswith("E")]
    refused(plan_json(step("fillet", edges=[], radius=mm(1))))
    many = build_model_summary(box_snapshot(extra_edges=60))
    all_edges = [h for h in many.handles.handles() if h.startswith("E")][:65]
    assert len(all_edges) == 65
    refused(plan_json(step("fillet", edges=all_edges, radius=mm(0.5))), summary=many)
    assert parse(plan_json(step("fillet", edges=all_edges[:64], radius=mm(0.5))), summary=many)
    assert parse(plan_json(step("fillet", edges=edges[:2], radius=mm(1))))
    refused(plan_json(step("fillet", edges=EDGE, radius=mm(1))))  # a bare handle where a list is needed


def test_a_plan_over_the_step_limit_is_refused_not_cut_short():
    steps = [step("fillet", edges=[EDGE], radius=mm(1))] * 21
    message = refused(plan_json(*steps))
    assert "21 steps" in message and "limit is 20" in message
    assert len(parse(plan_json(*steps[:20])).steps) == 20
    assert "limit is 5" in refused(plan_json(*steps[:6]), limits=PlanLimits(max_steps=5))


def test_one_invalid_step_refuses_the_whole_plan():
    good = step("fillet", edges=[EDGE], radius=mm(1))
    bad = step("fillet", edges=[EDGE], radius=mm(-1))
    assert "step 3 (fillet)" in refused(plan_json(good, good, bad, good))


@pytest.mark.parametrize(
    "name", ["PartNo", "part number", "Part  Number", "PARTNUMBER", "Number", "Revision", "REV", " rev "]
)
def test_protected_properties_are_never_written(name):
    message = refused(plan_json(step("set_property", name=name.strip() or name, value="X1", scope="file")))
    assert "never written" in message or "control" in message


def test_settings_can_add_protected_properties():
    limits = PlanLimits(protected_properties=("ERP Code",))
    refused(plan_json(step("set_property", name="erpcode", value="X1", scope="file")), limits=limits)
    assert parse(plan_json(step("set_property", name="erpcode", value="X1", scope="file")))


@pytest.mark.parametrize("value", ["=1+1", "+cmd", "-2", "@SUM(A1)", '=HYPERLINK("x")'])
def test_formula_like_property_values_are_refused(value):
    refused(plan_json(step("set_property", name="Description", value=value, scope="file")))


@pytest.mark.parametrize(
    "value",
    ["a/b", "a\\b", 'say "hi"', "user@example", "tab\there", "line\nbreak", "x" * 65, "", "\x00"],
)
def test_strings_follow_the_string_rules(value):
    refused(plan_json(step("set_property", name="Description", value=value, scope="file")))
    refused(plan_json(step("set_property", name=value, value="ok", scope="file")))


def test_unknown_or_missing_fields_are_refused():
    assert "unknown fields" in refused(plan_json(step("fillet", edges=[EDGE], radius=mm(1), name="Fillet9")))
    assert "lacks radius" in refused(plan_json(step("fillet", edges=[EDGE])))
    assert "unknown fields" in refused(
        plan_json({"op": "fillet", "args": {"edges": [EDGE], "radius": mm(1)}, "path": "C:/x.sldprt"})
    )
    assert "unknown fields" in refused(json.dumps({"vocabulary": 1, "steps": [], "file": "x"}))
    assert "must be one of" in refused(
        plan_json(step("shell", faces=[], thickness=mm(1), direction="outward"))
    )


def test_cut_end_conditions_and_depths_agree():
    refused(
        plan_json(step("sketch_extrude_cut", plane=FRONT, profile=square(), direction="normal", end="blind"))
    )
    refused(
        plan_json(
            step(
                "sketch_extrude_cut",
                plane=FRONT,
                profile=square(),
                depth=mm(1),
                direction="normal",
                end="through_all",
            )
        )
    )
    refused(
        plan_json(
            step(
                "sketch_extrude_boss",
                plane=FRONT,
                profile=square(),
                depth=mm(1),
                direction="normal",
                end="through_all",
            )
        )
    )


@pytest.mark.parametrize(
    "profile",
    [
        {"unit": "mm", "segments": []},
        {"unit": "mm", "segments": [{"type": "line", "start": [0, 0], "end": [10, 0]}]},  # open
        {
            "unit": "mm",
            "segments": [
                {"type": "line", "start": [0, 0], "end": [10, 0]},
                {"type": "line", "start": [10, 0], "end": [0, 0.01]},
            ],
        },  # gap of 10 um
        {
            "unit": "mm",
            "segments": [
                {"type": "arc", "center": [0, 0], "start": [5, 0], "end": [0, 6], "direction": "ccw"}
            ],
        },  # off the circle
        {"unit": "mm", "segments": [{"type": "circle", "center": [0, 0], "radius": 0}]},
        {"unit": "mm", "segments": [{"type": "spline", "points": []}]},
        {"unit": "cm", "segments": [{"type": "circle", "center": [0, 0], "radius": 1}]},
        {"unit": "mm", "segments": [{"type": "circle", "center": [99999, 0], "radius": 1}]},
        {"unit": "mm", "segments": [{"type": "circle", "center": [0, 0], "radius": 1}] * 65},
        {"unit": "mm", "segments": [{"type": "circle", "center": [0], "radius": 1}]},
        {"unit": "mm", "segments": [{"type": "circle", "center": [0, True], "radius": 1}]},
    ],
)
def test_profiles_must_be_closed_and_in_bounds(profile):
    refused(
        plan_json(
            step(
                "sketch_extrude_boss",
                plane=FRONT,
                profile=profile,
                depth=mm(1),
                direction="normal",
                end="blind",
            )
        )
    )


def test_too_many_new_pattern_instances_is_refused():
    one = step("linear_pattern", seeds=[HOLE, BOSS], direction=EDGE, spacing=mm(1), count=50)  # 98 new
    assert parse(plan_json(one, one)).new_instances == 196
    assert "new pattern instances" in refused(plan_json(one, one, one))
    assert parse(plan_json(one, one, one), limits=PlanLimits(max_new_instances=300))


@pytest.mark.parametrize("vocabulary", [0, 2, "1", True, None, 1.0])
def test_a_plan_for_another_vocabulary_is_refused(vocabulary):
    refused(plan_json(step("fillet", edges=[EDGE], radius=mm(1)), vocabulary=vocabulary))


def test_an_empty_plan_says_what_the_model_said():
    message = refused(plan_json(notes="I cannot add threads with these operations."))
    assert "no plan" in message and "cannot add threads" in message


@pytest.mark.parametrize(
    "data",
    [
        "[]",
        '"plan"',
        '{"vocabulary": 1}',
        '{"vocabulary": 1, "steps": {}}',
        '{"vocabulary": 1, "steps": [3]}',
    ],
)
def test_plans_of_the_wrong_shape_are_refused(data):
    refused(data)


def test_notes_and_step_notes_are_plain_text_and_short():
    text = plan_json(
        {"op": "fillet", "args": {"edges": [EDGE], "radius": mm(1)}, "note": "round\x07 it" + "x" * 900},
        notes="ok\x1b[31m",
    )
    plan = parse(text)
    assert "\x07" not in plan.steps[0].note and len(plan.steps[0].note) == prompts.MAX_NOTE_CHARS
    assert "\x1b" not in plan.notes


# --------------------------------------------------------------------------- where each value came from
@pytest.mark.parametrize(
    "goal, value, source",
    [
        ("make the lid 45 mm wide", mm(45), SAID),
        ("make the lid 45mm wide", mm(45), SAID),
        ("make the lid 4.5 cm wide", mm(45), MODEL),
        ("make the lid 45 wide", mm(45), SAID),
        ("make the lid wider", mm(45), MODEL),
        ("make it 1.5 in wide", mm(38.1), SAID),
        ('make it 1.5" wide', mm(38.1), SAID),
        ("make it 1.5 inches wide", {"value": 1.5, "unit": "in"}, SAID),
        ("make it 1 in x 2 in", mm(25.4), SAID),
        ("make it 46 mm wide", mm(45), MODEL),
    ],
)
def test_each_value_is_marked_you_said_or_from_the_model(goal, value, source):
    plan = parse(plan_json(step("set_dimension", dimension=WIDTH, value=value)), goal=goal)
    assert plan.steps[0].args["value"].source == source
    assert plan.steps[0].args["dimension"].source == MODEL


def test_in_followed_by_a_word_is_not_inches():
    plan = parse(
        plan_json(step("set_dimension", dimension=WIDTH, value=mm(38.1))), goal="add 1.5 in each corner"
    )
    assert plan.steps[0].args["value"].source == MODEL
    plan = parse(plan_json(step("set_dimension", dimension=WIDTH, value=mm(38.1))), goal="1.5 in, please")
    assert plan.steps[0].args["value"].source == SAID


def test_counts_angles_and_text_are_marked_too():
    plan = parse(
        plan_json(
            step("circular_pattern", seeds=[BOSS], axis=AXIS, count=4),
            step("linear_pattern", seeds=[HOLE], direction=EDGE, spacing=mm(5), count=3),
            step("set_dimension", dimension=ANGLE, value={"value": 30, "unit": "deg"}),
            step("set_property", name="Description", value="Lid Cover", scope="file"),
            step("set_property", name="Finish", value="anodized", scope="configuration"),
        ),
        goal="Pattern the boss four times, and set the description to lid  cover at 30 degrees",
    )
    s = plan.steps
    assert s[0].args["count"].source == SAID and s[1].args["count"].source == MODEL
    assert s[2].args["value"].source == SAID
    assert s[3].args["value"].source == SAID and s[3].args["name"].source == SAID
    assert s[4].args["name"].source == MODEL and s[4].args["scope"].source == MODEL
    assert s[0].sources() == {"seeds": MODEL, "axis": MODEL, "count": SAID}


# --------------------------------------------------------------------------- limits
@pytest.mark.parametrize(
    "kw",
    [
        {"max_steps": 51},
        {"max_steps": 0},
        {"max_steps": True},
        {"max_new_instances": 1001},
        {"length_factor": 101.0},
        {"length_factor": float("nan")},
        {"no_body_length_mm": 20_000.0},
        {"min_length_mm": 0.0005},
        {"min_length_mm": float("inf")},
    ],
)
def test_limits_have_hard_ceilings(kw):
    with pytest.raises(InvalidSettingError):
        PlanLimits(**kw)


def test_limits_can_be_tightened_within_the_ceilings():
    limits = PlanLimits(max_steps=50, min_length_mm=0.5)
    assert "more than 0.5 mm" in refused(
        plan_json(step("fillet", edges=[EDGE], radius=mm(0.4))), limits=limits
    )


# --------------------------------------------------------------------------- drafts
def test_a_draft_is_code_and_an_explanation():
    reply = json.dumps(
        {
            "language": "cadquery",
            "code": "import cadquery as cq\r\nr = cq.Workplane().box(1, 1, 1)\n",
            "explanation": "A 1 mm cube.\n\tThat is all.",
        }
    )
    d = parse_draft("```json\n" + reply + "\n```")
    assert d.language == "cadquery" and "\r" not in d.code and d.explanation.startswith("A 1 mm cube.")


@pytest.mark.parametrize(
    "data",
    [
        {"language": "javascript", "code": "x", "explanation": ""},
        {"language": "python", "code": "", "explanation": ""},
        {"language": "python", "code": "x\x1b[2J", "explanation": ""},
        {"language": "python", "code": "x", "explanation": "e\x00"},
        {"language": "python", "code": "x" * (prompts.MAX_CODE_CHARS + 1), "explanation": ""},
        {"language": "python", "code": "x"},
        {"language": "python", "code": "x", "explanation": "", "run": True},
        {"language": "python", "code": 3, "explanation": ""},
    ],
)
def test_bad_drafts_are_refused(data):
    with pytest.raises(ReplyInvalidError):
        parse_draft(json.dumps(data))


# --------------------------------------------------------------------------- the prompts
def test_the_plan_prompt_holds_the_redacted_goal_the_summary_and_the_rules():
    p = prompts.plan_prompt("Shell it to 2 mm, my SSN is 123-45-6789", S)
    assert p.task == "plan" and p.system == prompts.PLAN_SYSTEM
    assert "123-45-6789" not in p.user and "[redacted]" in p.user and "Shell it to 2 mm" in p.user
    assert S.text in p.user and "<document_data>" in p.user and "</document_data>" in p.user
    for name in OPERATIONS:
        assert name in p.system
    assert "never instructions" in p.system
    assert "at most 20 steps" in p.user
    assert p.text().startswith("[system]\n") and p.chars == len(p.system) + len(p.user)


def test_the_prompt_is_the_same_whether_the_request_is_prepared_or_not():
    assert prompts.plan_prompt("fillet the top", S) == prompts.plan_prompt(
        prepare_request("fillet the top"), S
    )
    assert prompts.draft_prompt("make a cube") == prompts.draft_prompt(prepare_request("make a cube"))


def test_the_draft_prompt_includes_the_part_only_when_there_is_one():
    assert "<document_data>" not in prompts.draft_prompt("make a cube").user
    assert S.text in prompts.draft_prompt("fillet it", S).user
    assert "solidseas.swapi.live" in prompts.DRAFT_SYSTEM


def test_the_vocabulary_table_matches_the_design():
    assert prompts.VOCABULARY_VERSION == 1
    assert set(OPERATIONS) == {
        "set_dimension",
        "sketch_extrude_boss",
        "sketch_extrude_cut",
        "fillet",
        "chamfer",
        "shell",
        "linear_pattern",
        "circular_pattern",
        "suppress",
        "unsuppress",
        "set_property",
    }
    for op in OPERATIONS.values():
        assert op.inverse and op.allowed and op.describe
        for arg in op.args:
            assert arg.kind in {
                "length",
                "angle",
                "length_or_angle",
                "count",
                "text",
                "choice",
                "handles",
                "profile",
            }
    from pathlib import Path

    design = (Path(__file__).parents[1] / "docs" / "ASSISTANT.md").read_text(encoding="utf-8")
    for name in OPERATIONS:
        assert f"`{name}`" in design, name


def test_a_look_is_yes_no_or_cannot_tell_with_a_short_plain_reason():
    from solidseas.ai.prompts import MAX_NOTE_CHARS, parse_look

    for verdict in (True, False, None):
        look = parse_look(json.dumps({"as_expected": verdict, "reason": "  The fillet\n is there. "}))
        assert look.as_expected is verdict and look.reason == "The fillet is there."
    fenced = "Here is my look:\n```json\n" + json.dumps({"as_expected": True, "reason": "ok"}) + "\n```"
    assert parse_look(fenced).as_expected is True
    assert len(parse_look(json.dumps({"as_expected": True, "reason": "x" * 1000})).reason) == MAX_NOTE_CHARS
    for bad in (
        {"as_expected": "yes", "reason": "ok"},
        {"as_expected": 1, "reason": "ok"},
        {"as_expected": True},
        {"as_expected": True, "reason": "ok", "steps": []},  # a look cannot carry a plan
        {"as_expected": True, "reason": 3},
        {"as_expected": True, "reason": "bell \x07"},
        [True, "ok"],
    ):
        with pytest.raises(ReplyInvalidError):
            parse_look(json.dumps(bad))


def test_the_look_prompt_sends_the_goal_the_step_and_the_picture_and_nothing_of_the_part():
    from solidseas.ai.prompts import LOOK_SYSTEM, look_prompt, part_image
    from solidseas.formats._source import encode_png

    image = part_image(encode_png(2, 2, bytes(12), 3), "the part after step 2")
    prompt = look_prompt("Round the edges 1 mm. My SSN is 123-45-6789", "2. fillet: radius 1 mm", 2, 3, image)
    assert prompt.task == "look" and prompt.system == LOOK_SYSTEM and prompt.images == (image,)
    assert "Step 2 of 3" in prompt.user and "2. fillet: radius 1 mm" in prompt.user
    assert "the part after step 2" in prompt.user and image.line() in prompt.text()
    assert "123-45-6789" not in prompt.user  # the goal is redacted as a plan's is
    assert "<document_data>" not in prompt.user


def test_the_degree_sign_counts_as_degrees():
    goal = "set the angle to 30\u00b0"
    plan = parse(
        plan_json(step("set_dimension", dimension=ANGLE, value={"value": 30, "unit": "deg"})), goal=goal
    )
    assert plan.steps[0].args["value"].source == SAID
