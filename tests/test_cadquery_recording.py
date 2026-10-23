"""CadQuery models as native parts, without CadQuery: a recording of how a model was built
(``solidseas.nativewrite.cqrecording``) read, checked and translated into
``ParametricDocumentIR``, and the recorder (``solidseas.nativewrite.cqrecorder``) driven with
a stand-in for CadQuery's ``Workplane``.

The recordings here are written by ``tests/cadquery_chains.py`` in CadQuery's own chained
style. The rules they pin were checked against CadQuery 2.8 itself, model by model, by
``tests/test_cadquery_models.py``, which runs where CadQuery is installed: each translated
model there removes exactly the material CadQuery's own does.
"""

import ast
import datetime
import fractions
import math
import sys
import types
from pathlib import Path

import pytest

from cadquery_chains import FORMAT, Chain
from solidseas.nativewrite import cqrecorder, ir
from solidseas.nativewrite import cqrecording as R

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def translate(chain: Chain, model, **options) -> ir.Document:
    return R.to_ir(R.from_data(chain.recording(model, **options)))


def plate() -> tuple[Chain, object]:
    """The plate the user guide shows: a 40 x 30 x 10 mm box from the origin with an 8 mm
    hole through the middle."""
    c = Chain()
    m = c.wp("XY").rect(40, 30, centered=False).extrude(10).faces(">Z").workplane(centerOption="CenterOfMass")
    return c, m.hole(8)


def mm(v: float) -> float:
    return round(v * 1000, 9)


def corners(sketch: ir.Sketch) -> list[tuple[float, float]]:
    return [(mm(p.x), mm(p.y)) for p in sketch.points]


def box_of(sketch: ir.Sketch, extrude: ir.Extrude) -> tuple[tuple, tuple]:
    """The box, in millimetres, a rectangle sketch extruded blind makes."""
    o, x, y = sketch.plane.origin, sketch.plane.x_dir, sketch.plane.y_dir
    n = (x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0])
    d = extrude.depth
    lo, hi = {"forward": (0, d), "reverse": (-d, 0), "midplane": (-d / 2, d / 2)}[extrude.direction]
    pts = [
        tuple(o[i] + p.x * x[i] + p.y * y[i] + t * n[i] for i in range(3))
        for p in sketch.points
        for t in (lo, hi)
    ]
    return tuple(min(mm(q[i]) for q in pts) for i in range(3)), tuple(
        max(mm(q[i]) for q in pts) for i in range(3)
    )


def unsupported(doc: ir.Document) -> list[str]:
    return [f"{f.name}: {f.reason}" for f in doc.features if isinstance(f, ir.Unsupported)]


# --------------------------------------------------------------------------- the done-when model
def test_a_plate_with_a_hole_is_a_box_and_a_cut_through_all():
    c, m = plate()
    doc = translate(c, m, name="plate")
    assert doc.name == "plate" and doc.source == {"system": "CadQuery", "format": R.FORMAT, "version": None}
    sketch1, boss, sketch2, cut = doc.features
    assert sketch1.plane == ir.Plane.named("xy") and sketch1.name == "rect(40, 30, centered=False)"
    assert corners(sketch1) == [(0, 0), (40, 0), (40, 30), (0, 30)]
    assert [cv.kind for cv in sketch1.curves] == ["line"] * 4 and not sketch1.dimensions
    assert (boss.name, boss.sketch, mm(boss.depth)) == ("extrude(10)", sketch1.id, 10)
    assert (boss.operation, boss.direction, boss.end) == ("new_body", "forward", "blind")
    assert sketch2.plane == ir.Plane.named("xy") and sketch2.name == "hole(8)"
    assert corners(sketch2) == [(20, 15)] and mm(sketch2.curves[0].radius) == 4
    assert (cut.name, cut.operation, cut.direction, cut.end) == ("hole(8)", "cut", "midplane", "through_all")


def test_the_native_writer_writes_the_plate_and_reads_it_back():
    gen = pytest.importorskip("solidseas.nativewrite.generate")
    from solidseas.formats.solidworks import open_document

    c, m = plate()
    doc = translate(c, m, name="plate", properties=[{"name": "PartNo", "value": "SS-1001", "type": "text"}])
    plan = gen.plan(doc)
    assert list(plan.left_out) == []
    assert [plan.names[f.id] for f in doc.features] == ["Sketch1", "Boss-Extrude1", "Sketch2", "Cut-Extrude1"]
    with open_document(gen.write_part(doc), name="plate.SLDPRT") as part:
        assert part.doc_type == "part"
        props = {p["name"]: p["value"] for p in part.summary(include=("properties",))["properties"]}
    assert props == {"PartNo": "SS-1001"}


def test_inches_and_other_units_are_scaled_to_the_ir_s_metres():
    c = Chain()
    m = c.wp("XY").rect(4, 3, centered=False).extrude(1)
    sketch, boss = translate(c, m, units="in").features
    assert max(p.x for p in sketch.points) == pytest.approx(0.1016) and boss.depth == pytest.approx(0.0254)
    sketch, boss = translate(c, m, units="cm").features
    assert boss.depth == pytest.approx(0.01)


# --------------------------------------------------------------------------- planes and workplanes
@pytest.mark.parametrize(
    ("plane", "base", "direction", "box"),
    [
        ("XY", "xy", "forward", ((0, 0, 0), (40, 30, 10))),
        ("front", "xy", "forward", ((0, 0, 0), (40, 30, 10))),
        ("XZ", "xz", "reverse", ((0, -10, 0), (40, 0, 30))),
        ("YZ", "yz", "forward", ((0, 0, 0), (10, 40, 30))),
        ("back", "xy", "reverse", ((-40, 0, -10), (0, 30, 0))),
        ("right", "yz", "forward", ((0, 0, -40), (10, 30, 0))),
        ("top", "xz", "forward", ((0, 0, -30), (40, 10, 0))),
    ],
)
def test_each_named_plane_puts_the_sketch_on_its_base_plane(plane, base, direction, box):
    c = Chain()
    m = c.wp(plane).rect(40, 30, centered=False).extrude(10)
    sketch, boss = translate(c, m).features
    assert sketch.plane == ir.Plane.named(base) and boss.direction == direction
    assert box_of(sketch, boss) == box


def test_a_workplane_off_a_base_plane_sketches_on_an_offset_plane():
    c = Chain()
    m = c.wp("XY", origin=(5, 5, 3)).rect(10, 10).extrude(2)
    sketch, boss = translate(c, m).features
    assert (sketch.plane.base, sketch.plane.parent, mm(sketch.plane.offset)) == (None, "xy", 3)
    assert box_of(sketch, boss) == ((0, 0, 3), (10, 10, 5))
    c = Chain()
    m = (
        c.wp({"plane": {"origin": [1, 2, 0], "x_dir": [1, 0, 0], "normal": [0, 0, 1]}})
        .rect(10, 10)
        .extrude(5)
    )
    sketch, boss = translate(c, m).features
    assert sketch.plane == ir.Plane.named("xy") and box_of(sketch, boss) == ((-4, -3, 0), (6, 7, 5))


def test_a_workplane_whose_axes_are_not_the_model_s_is_not_translated():
    c = Chain()
    m = (
        c.wp({"plane": {"origin": [0, 0, 0], "x_dir": [1, 1, 0], "normal": [0, 0, 1]}})
        .rect(10, 10)
        .extrude(5)
    )
    assert unsupported(translate(c, m)) == [
        "Workplane(<Plane>): a workplane whose axes are not along X, Y and Z is not translated yet",
        "extrude(5): follows step 1, Workplane(<Plane>), which is not translated",
    ]


def test_faces_and_workplane_follow_cadquery_s_frames():
    # the bottom face's workplane looks up at the part, so its y runs along -Y
    c = Chain()
    m = c.wp("XY").rect(40, 30).extrude(10).faces("<Z").workplane().center(5, 5).hole(6)
    hole = translate(c, m).features[2]
    assert corners(hole) == [(5, -5)]
    # +X face: x along Y, y along Z, the origin projected onto it
    c = Chain()
    m = c.wp("XY").rect(40, 30).extrude(10).faces(">X").workplane().center(3, 4).hole(2)
    hole = translate(c, m).features[2]
    assert hole.plane == ir.Plane.named("yz") and corners(hole) == [(3, 4)]
    # centre options and a given origin
    for option, origin, where in (
        ("CenterOfBoundBox", None, (20, 15)),
        ("CenterOfMass", None, (20, 15)),
        ("ProjectedOrigin", (20, 15, 0), (20, 15)),
        ("ProjectedOrigin", None, (0, 0)),
    ):
        c = Chain()
        top = c.wp("XY").rect(40, 30, centered=False).extrude(10).faces(">Z")
        m = top.workplane(centerOption=option, origin=origin).hole(8)
        assert corners(translate(c, m).features[2]) == [where]


def test_an_offset_and_inverted_workplane_extrudes_back_into_the_part():
    c = Chain()
    m = (
        c.wp("XY")
        .rect(40, 30)
        .extrude(10)
        .faces(">Z")
        .workplane(offset=2, invert=True)
        .rect(10, 10)
        .extrude(2)
    )
    *_, sketch, boss = translate(c, m).features
    assert (sketch.plane.parent, mm(sketch.plane.offset)) == ("xy", 8)
    assert (boss.direction, boss.operation, box_of(sketch, boss)) == (
        "reverse",
        "join",
        ((-5, -5, 6), (5, 5, 8)),
    )
    c = Chain()
    m = c.wp("XY").workplane(offset=5).rect(20, 20).extrude(4)
    sketch, boss = translate(c, m).features
    assert mm(sketch.plane.offset) == 5 and box_of(sketch, boss) == ((-10, -10, 5), (10, 10, 9))


def test_points_on_the_stack_place_profiles_and_holes():
    c = Chain()
    m = c.wp("XY").rect(40, 30, centered=False).extrude(10).faces(">Z").workplane().moveTo(30, 20).hole(5)
    assert corners(translate(c, m).features[2]) == [(30, 20)]
    c = Chain()
    holes = (
        c.wp("XY").rect(40, 30).extrude(10).faces(">Z").workplane().pushPoints([(-10, 0), (10, 0)]).hole(5)
    )
    sketch = translate(c, holes).features[2]
    assert corners(sketch) == [(-10, 0), (10, 0)] and len(sketch.curves) == 2
    c = Chain()
    m = (
        c.wp("XY")
        .rect(40, 30)
        .extrude(10)
        .faces(">Z")
        .workplane()
        .pushPoints([{"vector": [5, 5, 0]}])
        .hole(3)
    )
    assert corners(translate(c, m).features[2]) == [(5, 5)]
    # a selected face is a point at its centre, as CadQuery's eachpoint takes it
    c = Chain()
    m = c.wp("XY").rect(40, 30, centered=False).extrude(10).faces(">Z").hole(8)
    assert corners(translate(c, m).features[2]) == [(20, 15)]


def test_rectangles_follow_centered_and_negative_sizes():
    for centered, size, box in (
        (True, (40, 30), ((-20, -15, 0), (20, 15, 10))),
        ((True, False), (40, 30), ((-20, 0, 0), (20, 30, 10))),
        (False, (-40, 30), ((-40, 0, 0), (0, 30, 10))),
    ):
        c = Chain()
        m = c.wp("XY").rect(*size, centered=centered).extrude(10)
        assert box_of(*translate(c, m).features) == box


def test_a_rectangle_with_a_circle_in_it_is_one_sketch_of_two_loops():
    c = Chain()
    m = c.wp("XY").rect(40, 30).circle(5).extrude(10)
    sketch, boss = translate(c, m).features
    assert sketch.name == "rect(40, 30) + circle(5)" and [cv.kind for cv in sketch.curves] == ["line"] * 4 + [
        "circle"
    ]
    assert boss.profile is None  # every closed region: the ring, as CadQuery makes it


# --------------------------------------------------------------------------- features
def test_boxes_are_extruded_from_the_plane_through_their_point():
    for centered, direction, box in (
        (True, "midplane", ((-20, -15, -5), (20, 15, 5))),
        ((True, True, False), "forward", ((-20, -15, 0), (20, 15, 10))),
        (False, "forward", ((0, 0, 0), (40, 30, 10))),
    ):
        c = Chain()
        m = c.wp("XY").box(40, 30, 10, centered=centered)
        sketch, boss = translate(c, m).features
        assert sketch.name == boss.name and boss.direction == direction and box_of(sketch, boss) == box


def test_extrusions_one_way_the_other_way_and_both():
    for until, both, direction, box in (
        (-10, False, "reverse", ((-20, -15, -10), (20, 15, 0))),
        (5, True, "midplane", ((-20, -15, -5), (20, 15, 5))),
    ):
        c = Chain()
        m = c.wp("XY").rect(40, 30).extrude(until, both=both)
        sketch, boss = translate(c, m).features
        assert boss.direction == direction and box_of(sketch, boss) == box


def test_a_box_apart_from_the_others_is_a_body_of_its_own_and_a_touching_one_joins():
    c = Chain()
    apart = (
        c.wp("XY")
        .rect(10, 10, centered=False)
        .extrude(5)
        .center(20, 0)
        .rect(10, 10, centered=False)
        .extrude(3)
    )
    assert [f.operation for f in translate(c, apart).features if isinstance(f, ir.Extrude)] == [
        "new_body"
    ] * 2
    c = Chain()
    touching = c.wp("XY").rect(10, 10, centered=False).extrude(5).center(10, 0).rect(10, 10, centered=False)
    doc = translate(c, touching.extrude(3))
    assert [f.operation for f in doc.features if isinstance(f, ir.Extrude)] == ["new_body", "join"]
    # SolidSeas stops following the shape where bodies join: a face of it is not selected
    c = Chain()
    joined = c.wp("XY").rect(10, 10, centered=False).extrude(5).center(10, 0).rect(10, 10, centered=False)
    doc = translate(c, joined.extrude(3).faces(">Z").workplane().hole(2))
    assert unsupported(doc) == [
        'faces(">Z"): SolidSeas does not follow the shape after step 6, extrude(3), where bodies join',
        'hole(2): follows step 7, faces(">Z"), which is not translated',
    ]


def test_combine_false_keeps_only_the_new_solid_as_cadquery_does():
    c = Chain()
    first = c.wp("XY").rect(10, 10, centered=False).extrude(5)
    m = first.center(20, 0).rect(10, 10, centered=False).extrude(3, combine=False)
    sketch, boss = translate(c, m).features
    assert boss.operation == "new_body" and box_of(sketch, boss) == ((20, 0, 0), (30, 10, 3))


def test_blind_cuts_are_sketched_where_cadquery_drew_them():
    for call in ("cutBlind", "extrude"):
        c = Chain()
        top = c.wp("XY").rect(40, 30).extrude(10).faces(">Z").workplane().rect(10, 10)
        m = top.cutBlind(-3) if call == "cutBlind" else top.extrude(-3, combine="cut")
        *_, sketch, cut = translate(c, m).features
        assert (sketch.plane.parent, mm(sketch.plane.offset)) == ("xy", 10)
        assert (cut.operation, cut.end, cut.direction, mm(cut.depth)) == ("cut", "blind", "reverse", 3)


def test_a_cut_through_all_is_sketched_on_the_base_plane():
    c = Chain()
    m = c.wp("XY").rect(40, 30).extrude(10).faces(">Z").workplane(offset=-5).rect(6, 6).cutThruAll()
    *_, sketch, cut = translate(c, m).features
    assert sketch.plane == ir.Plane.named("xy") and corners(sketch) == [(-3, -3), (3, -3), (3, 3), (-3, 3)]
    assert (cut.operation, cut.direction, cut.end) == ("cut", "midplane", "through_all")


def test_a_hole_that_does_not_go_through_is_not_translated():
    c = Chain()
    m = c.wp("XY").rect(40, 30).extrude(10).faces(">Z").workplane(offset=-5).hole(4)
    assert unsupported(translate(c, m)) == [
        "hole(4): a hole that does not go through every body in its way is not translated yet"
    ]
    for call, reason in (
        (
            lambda w: w.faces(">Z").workplane().hole(4, 3),
            "hole(4, 3): a hole with a depth is not translated yet",
        ),
        (lambda w: w.hole(4), "hole(4): hole() at the centre of a solid is not translated yet"),
    ):
        c = Chain()
        assert unsupported(translate(c, call(c.wp("XY").rect(40, 30).extrude(10)))) == [reason]


def test_a_hole_partly_off_the_part_is_written_as_cadquery_cut_it():
    c = Chain()
    m = c.wp("XY").rect(40, 30).extrude(10).faces(">Z").workplane().center(19, 0).hole(6)
    *_, sketch, cut = translate(c, m).features
    assert corners(sketch) == [(19, 0)] and cut.end == "through_all"


def test_the_same_call_twice_names_each_step():
    c = Chain()
    m = c.wp("XY").rect(40, 30).extrude(10).faces(">Z").workplane().hole(4)
    m = m.faces("<Z").workplane().center(10, 5).hole(4)
    names = [f.name for f in translate(c, m).features]
    assert names[2:] == ["hole(4) (step 6)", "hole(4) (step 6)", "hole(4) (step 10)", "hole(4) (step 10)"]


# --------------------------------------------------------------------------- selecting faces
def test_faces_at_one_height_are_selected_together():
    c = Chain()
    two = (
        c.wp("XY")
        .rect(10, 10, centered=False)
        .extrude(5)
        .center(20, 0)
        .rect(10, 10, centered=False)
        .extrude(5)
    )
    m = two.faces(">Z").workplane(centerOption="CenterOfMass").rect(2, 2).extrude(1)
    *_, sketch, boss = translate(c, m).features
    assert box_of(sketch, boss) == ((14, 4, 5), (16, 6, 6))  # between the two tops, as CadQuery puts it


def test_a_selection_that_takes_more_than_flat_ends_is_not_translated():
    c = Chain()
    thin = c.wp("XY").rect(40, 30).extrude(0.00005)  # its sides' centres are within CadQuery's tolerance
    assert unsupported(translate(c, thin.faces(">Z").workplane().hole(2))) == [
        'faces(">Z"): faces() selects faces other than flat ends of boxes, which is not translated yet',
        'hole(2): follows step 4, faces(">Z"), which is not translated',
    ]
    c = Chain()
    m = c.wp("XY").rect(40, 30).extrude(10).faces("|Z").workplane().hole(2)
    assert unsupported(translate(c, m))[0].startswith(
        'faces("|Z"): faces() with that selector is not translated'
    )


# --------------------------------------------------------------------------- what is not translated
def test_a_call_not_translated_and_each_feature_after_it_are_unsupported_entries():
    c = Chain()
    m = c.wp("XY").rect(40, 30).extrude(10).edges("|Z").fillet(2).faces(">Z").workplane().hole(3)
    doc = translate(c, m)
    assert [type(f).__name__ for f in doc.features] == ["Sketch", "Extrude"] + ["Unsupported"] * 3
    assert unsupported(doc) == [
        'edges("|Z"): CadQuery\'s edges() is not translated yet',
        "fillet(2): CadQuery's fillet() is not translated yet",
        "hole(3): follows step 5, fillet(2), which is not translated",
    ]
    gen = pytest.importorskip("solidseas.nativewrite.generate")
    with pytest.raises(gen.NativeWriteUnsupported) as exc:
        gen.plan(doc)
    assert any("fillet(2)" in str(item) for item in exc.value.items)
    assert [str(i) for i in gen.plan(doc, allow_partial=True).left_out] == unsupported(doc)


@pytest.mark.parametrize(
    ("build", "reason"),
    [
        (
            lambda c: c.wp("XY").polygon(6, 20).extrude(5),
            "extrude(5): follows step 2, polygon(6, 20), which is not translated",
        ),
        (
            lambda c: c.wp("XY").rect(10, 10).extrude(5, taper=5),
            "extrude(5, taper=5): a tapered extrusion or cut is not translated yet",
        ),
        (
            lambda c: c.wp("XY").box(20, 20, 2).faces(">Z").workplane(offset=5).rect(4, 4).extrude("next"),
            'extrude("next"): an extrusion up to a face is not translated yet',
        ),
        (
            lambda c: c.wp("XY").rect(10, 10).extrude(5, combine=False).box(2, 2, 2, combine="cut"),
            'box(2, 2, 2, combine="cut"): box() that cuts is not translated yet',
        ),
        (
            lambda c: c.wp("XY", obj={"object": "Solid"}).box(2, 2, 2),
            'Workplane("XY", obj=<Solid>): Workplane() with an object on its stack is not translated yet',
        ),
        (
            lambda c: c.wp("XY").box(10, 10, 10) - c.wp("XY").box(2, 2, 20),
            "- <workplane 3>: CadQuery's - operator is not translated yet",
        ),
    ],
)
def test_calls_and_options_not_translated_say_why(build, reason):
    c = Chain()
    assert reason in unsupported(translate(c, build(c)))


def test_a_workplane_the_recording_does_not_show_being_made():
    c = Chain()
    m = c.wp("XY").rect(10, 10).extrude(5)
    data = c.recording(m)
    data["steps"].append({"call": "hole", "on": 40, "args": [2], "kwargs": {}, "result": 41})
    data["model"] = 41
    assert unsupported(R.to_ir(R.from_data(data))) == [f"hole(2): {R.UNSEEN}"]


def test_wires_drawn_by_a_call_not_translated_make_the_next_profile_unknown():
    c = Chain()
    base = c.wp("XY").rect(40, 30).extrude(10)
    base.faces(">Z").workplane().polyline([(0, 0), (1, 0), (1, 1)])  # a branch; its wires stay pending
    m = base.faces("<Z").workplane().rect(4, 4).cutThruAll()
    assert unsupported(translate(c, m)) == [
        "cutThruAll(): its profile may hold wires drawn by step 6, polyline(((0, 0), (1, 0), (1, 1))), "
        "which is not translated"
    ]
    # that cut used every wire drawn, so the next profile is known again
    m = base.faces("<Z").workplane().rect(2, 2).cutThruAll()
    assert unsupported(translate(c, m)) == []
    # construction geometry draws nothing to use
    c = Chain()
    base = c.wp("XY").rect(40, 30).extrude(10)
    base.faces(">Z").workplane().rect(30, 20, forConstruction=True)
    m = base.faces("<Z").workplane().rect(4, 4).cutThruAll()
    assert unsupported(translate(c, m)) == []


# --------------------------------------------------------------------------- branches, tags and end
def test_only_the_model_s_own_chain_of_features_is_translated():
    c = Chain()
    base = c.wp("XY").rect(40, 30).extrude(10)
    base.faces(">Z").workplane().hole(5)  # a branch the model does not take
    m = base.faces("<Z").workplane().hole(3)
    assert [f.name for f in translate(c, m).features] == ["rect(40, 30)", "extrude(10)", "hole(3)", "hole(3)"]


def test_tag_and_end_go_back_as_cadquery_does():
    c = Chain()
    m = c.wp("XY").rect(40, 30).extrude(10).tag("base").faces(">Z").workplane().hole(5).end(3)
    m = m.faces("<Z").workplane().rect(4, 4).cutThruAll()
    assert [f.name for f in translate(c, m).features] == [
        "rect(40, 30)",
        "extrude(10)",
        "rect(4, 4)",
        "cutThruAll()",
    ]


# --------------------------------------------------------------------------- recordings that are refused
def _recording(**changes):
    c, m = plate()
    data = c.recording(m, name="plate")
    data.update(changes)
    return data


@pytest.mark.parametrize(
    ("data", "words"),
    [
        ({"format": "solidseas-parametric-ir/1"}, "not a CadQuery recording"),
        ({"extra": 1}, "has no field 'extra'"),
        ({"name": ""}, "name is text"),
        ({"units": "furlong"}, "units is one of"),
        ({"cadquery": 2.8}, "version"),
        ({"steps": []}, "steps is a list"),
        ({"model": 99}, "no step made the model's workplane 99"),
        ({"model": True}, "not a workplane's number"),
        ({"steps": [{"call": "1rect", "on": 0, "args": [], "kwargs": {}, "result": 1}]}, "not a call's name"),
        ({"steps": [{"call": "rect", "on": 0, "args": {}, "kwargs": {}, "result": 1}]}, "args is a list"),
        (
            {"steps": [{"call": "Workplane", "on": 0, "args": [], "kwargs": {}, "result": 1}]},
            "only Workplane",
        ),
        ({"steps": [{"call": "rect", "on": None, "args": [], "kwargs": {}, "result": 1}]}, "only Workplane"),
        (
            {"steps": [{"call": "rect", "on": 0, "args": [{"thing": 1}], "kwargs": {}, "result": 1}]},
            "not one a",
        ),
        (
            {"steps": [{"call": "rect", "on": 0, "args": ["x" * 201], "kwargs": {}, "result": 1}]},
            "longer than",
        ),
        (
            {"steps": [{"call": "rect", "on": 0, "args": [[[[[[[[[[1]]]]]]]]]], "kwargs": {}, "result": 1}]},
            "deeply",
        ),
        (
            {"steps": [{"call": "pushPoints", "on": 0, "args": [[1] * 10_001], "kwargs": {}, "result": 1}]},
            "too many",
        ),
        ({"steps": [{"call": "rect", "on": 0, "args": [2**60], "kwargs": {}, "result": 1}]}, "too large"),
        ({"properties": [{"name": "Qty"}]}, "a property has"),
        ({"properties": [{"name": "Made", "value": "20 Oct", "type": "date"}]}, "a date needs YYYY-MM-DD"),
    ],
)
def test_data_that_is_not_a_recording_is_refused(data, words):
    with pytest.raises(R.RecordingError, match=words):
        R.to_ir(R.from_data(_recording(**data)))


def test_a_recording_that_contradicts_itself_is_refused():
    def refused(build, words):
        c = Chain()
        with pytest.raises(R.RecordingError, match=words):
            translate(c, build(c))

    refused(lambda c: c.wp("XY").extrude(10), "extrude.. has no wires to use")
    refused(lambda c: c.wp("XY").rect(4, 4).cutThruAll(), "has no solid to cut")
    refused(lambda c: c.wp("XY").rect(40), r"rect\(\) needs yLen")
    refused(lambda c: c.wp("XY").rect(40, 30, centered=True, xLen=4), "xLen is given twice")
    refused(lambda c: c.wp("XY").rect(40, 30).extrude(10).faces(">Z"), "holds no solid")
    refused(lambda c: c.wp("XY").box(4, 3, 1).faces(">Z").workplane(centerOption="Middle"), "centerOption")
    c = Chain()
    m = c.wp("XY").rect(40, 30).extrude(10)
    data = c.recording(m)
    data["steps"].append(dict(data["steps"][1]))  # rect makes workplane 1 again
    with pytest.raises(R.RecordingError, match="made twice"):
        R.to_ir(R.from_data(data))
    data = c.recording(m)
    data["steps"].append({"call": "end", "on": 2, "args": [1], "kwargs": {}, "result": 0})
    data["model"] = 0
    with pytest.raises(R.RecordingError, match="end.1. returns workplane 1, not 0"):
        R.to_ir(R.from_data(data))


def test_an_argument_cadquery_has_but_solidseas_does_not_know_is_not_translated():
    c = Chain()
    m = c.wp("XY").rect(40, 30, centred=False).extrude(10)
    assert unsupported(translate(c, m))[0] == (
        "rect(40, 30, centred=False): rect() has no argument 'centred' that SolidSeas knows"
    )


# --------------------------------------------------------------------------- the file
def test_a_recording_round_trips_through_its_json(tmp_path):
    c = Chain()
    m = c.wp({"plane": {"origin": [0, 0, 0], "x_dir": [1, 0, 0], "normal": [0, 0, 1]}}).rect(10, 10)
    m = m.extrude(5).tag({"object": "Thing"}).pushPoints([{"vector": [1, 2, 3]}, (1, 2)]).hole(1)
    rec = R.from_data(
        c.recording(m, cadquery="2.8.0", properties=[{"name": "Qty", "value": 2, "type": "number"}])
    )
    assert R.from_data(R.to_data(rec)) == rec
    path = tmp_path / "plate.json"
    path.write_text(R.to_json(rec), encoding="utf-8")
    assert R.load(path) == rec == R.load(path.read_bytes())
    assert R.read_ir(path) == R.to_ir(rec)
    assert R.to_ir(rec).source["version"] == "2.8.0"


@pytest.mark.parametrize(
    ("raw", "words"),
    [
        (b"\xff\xfe not text", "not a CadQuery recording"),
        (b"{not json", "not a CadQuery recording"),
        (b'{"format": "' + FORMAT.encode() + b'", "x": NaN}', "NaN is not a number"),
    ],
)
def test_bytes_that_are_not_a_recording(raw, words):
    with pytest.raises(R.RecordingError, match=words):
        R.load(raw)


def test_a_file_larger_than_the_cap_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "MAX_FILE_BYTES", 64)
    path = tmp_path / "big.json"
    path.write_bytes(b" " * 65)
    with pytest.raises(R.RecordingError, match="larger than"):
        R.load(path)


def test_call_text_reads_like_the_code():
    def text(call, *args, **kwargs):
        return R.call_text(R.Step(1, call, 0, args, tuple(kwargs.items()), 1))

    assert text("rect", 40, 30.5, centered=(True, False)) == "rect(40, 30.5, centered=(True, False))"
    assert text("faces", ">Z") == 'faces(">Z")' and text("pushPoints", ((1, 2),)) == "pushPoints(((1, 2),))"
    assert text("union", R.Ref(3)) == "union(<workplane 3>)" and text("__getitem__", 0) == "[0]"
    assert text("moveTo", R.Vector((1.0, 2.0, 0.0))) == "moveTo(Vector(1.0, 2.0, 0.0))"
    long = text("polyline", tuple((n, n) for n in range(40)))
    assert len(long) == R.CALL_TEXT and long.endswith("...")


# --------------------------------------------------------------------------- the recorder, with a stand-in
class Shape:
    def __init__(self, kind: str) -> None:
        self.kind = kind

    def ShapeType(self) -> str:  # noqa: N802 - CadQuery's name
        return self.kind


class Stand:
    """A stand-in for CadQuery's Workplane: its methods call each other and make new
    workplanes the way CadQuery's do."""

    def __init__(self, inPlane="XY", origin=(0, 0, 0), obj=None):  # noqa: N803 - CadQuery's names
        self.objects = [] if obj is None else [obj]
        self.parent = None

    def newObject(self, objects):  # noqa: N802
        made = self.__class__()
        made.parent, made.objects = self, list(objects)
        return made

    def eachpoint(self, shape):
        return self.newObject([shape])

    def rect(self, xLen, yLen, centered=True, forConstruction=False):  # noqa: N803
        return self.eachpoint(Shape("Wire"))

    def extrude(self, until, combine=True):
        return self.newObject([Shape("Solid")])

    def tag(self, name):
        return self

    def val(self):
        return self.objects[0] if self.objects else None

    def cut(self, other):
        return self.newObject([Shape("Solid")])

    def __sub__(self, other):
        return self.cut(other)

    @property
    def size(self):
        return len(self.objects)

    @classmethod
    def made(cls):
        return cls()


def _vector(x, y, z):
    kind = type("Vector", (), {"__module__": "cadquery.occ_impl.geom"})
    v = kind()
    v.x, v.y, v.z = x, y, z
    return v


def _plane():
    kind = type("Plane", (), {"__module__": "cadquery.occ_impl.geom"})
    p = kind()
    p.origin, p.xDir, p.zDir = (
        types.SimpleNamespace(toTuple=lambda t=t: t) for t in ((0, 0, 1), (1, 0, 0), (0, 0, 1))
    )
    return p


def test_the_recorder_writes_down_the_calls_made_from_outside_only():
    before = dict(Stand.__dict__)
    with cqrecorder.Recorder(Stand) as rec:
        part = Stand("XY").rect(4, 3).extrude(2)
        part.val()
        assert part.size == 1 and Stand.made() is not None  # a property and a class method run as they are
    data = R.to_data(rec.recording(part, name="block"))
    assert [(s["call"], s["on"], s["result"]) for s in data["steps"]] == [
        ("Workplane", None, 0),
        ("rect", 0, 1),
        ("extrude", 1, 2),
        ("val", 2, None),
    ]
    assert data["steps"][0]["args"] == ["XY"] and data["model"] == 2 and data["name"] == "block"
    assert dict(Stand.__dict__) == before  # everything put back
    after = Stand().rect(1, 1).extrude(1)
    with pytest.raises(ValueError, match="saw being made"):
        rec.recording(after)


def test_the_recorder_keeps_values_as_data():
    other_kind = type("Location", (), {})
    with cqrecorder.Recorder(Stand) as rec:
        a = Stand(_plane()).rect(
            fractions.Fraction(1, 4), 3.0, centered=(True, False), forConstruction=_vector(1, 2, 3)
        )
        b = Stand().rect(1, 1).extrude(1)
        model = a.extrude(math.nan, combine=other_kind()) - b
        model = model.tag("x" * 300)
    steps = R.to_data(rec.recording(model))["steps"]
    by_call = {s["call"]: s for s in steps}
    assert by_call["Workplane"]["args"] == [
        {"plane": {"origin": [0, 0, 1], "x_dir": [1, 0, 0], "normal": [0, 0, 1]}}
    ]
    assert by_call["rect"]["args"] == [0.25, 3.0] and by_call["rect"]["kwargs"] == {
        "centered": [True, False],
        "forConstruction": {"vector": [1.0, 2.0, 3.0]},
    }
    assert by_call["extrude"]["args"] == [{"object": "float"}]
    assert by_call["extrude"]["kwargs"] == {"combine": {"object": "Location"}}
    assert by_call["__sub__"]["args"] == [{"workplane": 4}] and "cut" not in by_call  # b, the fifth made
    assert by_call["tag"]["args"] == [{"object": "str"}] and by_call["tag"]["result"] == by_call["tag"]["on"]


def test_a_recording_holds_only_the_model_s_chain_and_its_properties():
    with cqrecorder.Recorder(Stand) as rec:
        Stand().rect(9, 9)  # another model
        part = Stand().rect(4, 3).extrude(2)
    rec_ = rec.recording(
        part,
        name="block",
        units="in",
        properties={"PartNo": "SS-1", "Qty": 4, "Bought": True, "Made": datetime.date(2026, 10, 22)},
    )
    assert [s.call for s in rec_.steps] == ["Workplane", "rect", "extrude"] and rec_.units == "in"
    assert [(p.name, p.type, p.value) for p in rec_.properties] == [
        ("PartNo", "text", "SS-1"),
        ("Qty", "number", 4),
        ("Bought", "yesno", True),
        ("Made", "date", "2026-10-22"),
    ]


def test_the_model_must_hold_the_solid():
    with cqrecorder.Recorder(Stand) as rec:
        sketch = Stand().rect(4, 3)
    with pytest.raises(ValueError, match="holds no solid"):
        rec.recording(sketch)


def test_one_recorder_at_a_time_and_workplane_is_put_back_after_an_error():
    before = dict(Stand.__dict__)
    with cqrecorder.Recorder(Stand):
        with pytest.raises(RuntimeError, match="one model at a time"):
            with cqrecorder.Recorder(Stand):
                pass
    with pytest.raises(ZeroDivisionError):
        with cqrecorder.Recorder(Stand):
            Stand().rect(1, 1).extrude(1 / 0)
    assert dict(Stand.__dict__) == before
    with cqrecorder.Recorder(Stand):  # and a new one opens
        pass


def test_a_workplane_seen_first_as_a_target_joins_its_parent_s_chain():
    with cqrecorder.Recorder(Stand) as rec:
        start = Stand().rect(4, 3)
        unseen = Stand.__new__(Stand)  # made without a call the recorder sees, as a Sketch hands one back
        unseen.objects, unseen.parent = [], start
        part = unseen.extrude(2)
    data = R.to_data(rec.recording(part))
    assert [s["call"] for s in data["steps"]] == ["Workplane", "rect", "extrude"]
    assert unsupported(R.to_ir(R.from_data(data))) == [f"extrude(2): {R.UNSEEN}"]


def test_save_writes_a_new_json_file_only(tmp_path):
    with cqrecorder.Recorder(Stand) as rec:
        part = Stand().rect(4, 3).extrude(2)
    path = rec.save(tmp_path / "block.json", part, name="block")
    assert R.load(path).name == "block"
    with pytest.raises(FileExistsError):
        rec.save(path, part)
    with pytest.raises(ValueError, match=r"\.json"):
        rec.save(tmp_path / "block.txt", part)


def test_without_a_class_the_recorder_uses_cadquery_s_workplane(monkeypatch):
    fake = types.ModuleType("cadquery")
    fake.Workplane, fake.__version__ = Stand, "2.8.0"
    monkeypatch.setitem(sys.modules, "cadquery", fake)
    with cqrecorder.Recorder() as rec:
        part = Stand().rect(4, 3).extrude(2)
    assert rec.recording(part).cadquery == "2.8.0"


# --------------------------------------------------------------------------- CadQuery stays optional
def _imports(path: Path) -> list[tuple[str, int]]:
    """Each top-level module a file imports, with the depth of the function it is in (0 at
    module level)."""
    found = []

    def walk(node, depth):
        for child in ast.iter_child_nodes(node):
            inner = depth + isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            if isinstance(child, ast.Import):
                found.extend((a.name.split(".")[0], depth) for a in child.names)
            elif isinstance(child, ast.ImportFrom) and child.module and child.level == 0:
                found.append((child.module.split(".")[0], depth))
            walk(child, inner)

    walk(ast.parse(path.read_text(encoding="utf-8")), 0)
    return found


def _imports_recorder(path: Path) -> bool:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import) and any("cqrecorder" in a.name for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and (
            "cqrecorder" in (node.module or "") or any(a.name == "cqrecorder" for a in node.names)
        ):
            return True
    return False


def test_only_the_recorder_imports_cadquery_and_only_when_it_opens():
    users = {
        p.relative_to(SRC).as_posix(): [d for name, d in _imports(p) if name == "cadquery"]
        for p in SRC.rglob("*.py")
    }
    users = {k: v for k, v in users.items() if v}
    assert users == {"solidseas/nativewrite/cqrecorder.py": [1]}  # inside a function, never at import
    # a CadQuery session imports the recorder; nothing in SolidSeas does
    assert [p for p in SRC.rglob("*.py") if _imports_recorder(p)] == []
    spec = (ROOT / "packaging" / "SolidSeasViewer.spec").read_text(encoding="utf-8")
    assert '"cadquery"' in spec  # the viewer's build leaves CadQuery out
