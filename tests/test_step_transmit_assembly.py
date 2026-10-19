"""STEP of a Parasolid transmit whose assemblies place bodies by instances: a part
product per body, an assembly product per ASSEMBLY and an occurrence per INSTANCE, as
the transmit holds them. Read back with SolidSeas' own STEP reader, every instance sits
where the transmit's own scene places it."""

import math
import re

import pytest

import xt_bodies as X
from solidseas.errors import NothingToExportError, NotRepresentableError
from solidseas.formats import Limits, open_model
from solidseas.formats.solidworks.parasolid import NULL_DOUBLE
from solidseas.step import step_bytes, step_model
from solidseas.step.assembly import _is_rigid
from solidseas_app.viewer import printing
from test_formats_xt import ABOUT_X, Asm, _assembly, _fan, _shape, x_b, x_t

STAMP = "2026-10-08T00:00:00"


def _count(text: str, entity: str) -> int:
    return len(re.findall(rf"={re.escape(entity)}\(", text))


def _box(placement, positions) -> tuple:
    pts = [placement.apply(positions[i : i + 3]) for i in range(0, len(positions), 3)]
    lo = [min(p[k] for p in pts) for k in range(3)]
    hi = [max(p[k] for p in pts) for k in range(3)]
    return tuple(round(v * 1000.0, 3) for v in (*lo, *hi))


def _boxes(scene, ids=None) -> list[tuple]:
    return sorted(
        _box(it.placement, scene.objects[it.object].positions)
        for it in scene.items
        if ids is None or it.instance in ids
    )


def _read_back(model):
    with open_model(step_bytes(model, time_stamp=STAMP), name="a.step") as doc:
        return doc.scene(), doc.tree()


@pytest.mark.parametrize("encoding", ["text", "binary"])
def test_each_assembly_is_a_product_and_each_instance_an_occurrence(encoding):
    a, _ids = _assembly()
    data = x_t(a.transmit()) if encoding == "text" else x_b(a.transmit())
    name = "a.x_t" if encoding == "text" else "a.x_b"
    with open_model(data, name=name) as doc:
        model = step_model(doc)
        drawn = doc.scene()
    text = step_bytes(model, time_stamp=STAMP).decode("ascii")
    assert model.doc_type == "assembly" and model.source_format == "parasolid"
    assert model.exact and not model.partial and model.warnings == ()
    assert [(p.name, p.kind) for p in model.products] == [
        ("a", "assembly"),
        ("a body 1", "part"),
        ("a body 2", "part"),
        ("a assembly 1", "assembly"),
    ]
    assert model.counts["products"] == 4 and model.counts["sub_assemblies"] == 1
    assert model.instances == (
        ("1.1", "a body 1"),
        ("1.2", "a body 1"),
        ("1.3.1", "a body 2"),
        ("1.3.2", "a body 2"),
    )
    assert _count(text, "NEXT_ASSEMBLY_USAGE_OCCURRENCE") == 5  # three in the top, two in the sub-assembly
    assert _count(text, "MANIFOLD_SOLID_BREP") == 2  # each body written once, however often placed
    scene, tree = _read_back(model)
    assert _boxes(scene) == _boxes(drawn)
    nodes = [n for n in tree.nodes if n.kind != "body"]
    sub = next(n for n in nodes if n.name == "a assembly 1")
    assert sub.parent == "1" and [n.name for n in nodes if n.parent == sub.id] == ["a body 2", "a body 2"]


def test_names_from_the_transmit_name_the_products_and_occurrences():
    a, ids = _assembly()
    a.attribute(ids["cyl"], "SDL/TYSA_NAME", "pin")
    a.attribute(ids["sub"], "SDL/TYSA_NAME", "boxes")
    with open_model(x_b(a.transmit()), name="a.x_b") as doc:
        model = step_model(doc, name="kit")
    assert [p.name for p in model.products] == ["kit", "pin", "kit body 2", "boxes"]
    _scene, tree = _read_back(model)
    top = [n.name for n in tree.nodes if n.parent == "1"]
    assert top == ["pin", "pin", "boxes"]


def test_an_assembly_placed_many_times_is_written_once():
    with open_model(_fan(3, 3), name="f.x_b") as doc:
        model = step_model(doc)
        drawn = doc.scene()
    text = step_bytes(model, time_stamp=STAMP).decode("ascii")
    assert model.counts["instances"] == 27 and model.counts["products"] == 4  # the top, two levels, a box
    assert _count(text, "NEXT_ASSEMBLY_USAGE_OCCURRENCE") == 9 and _count(text, "MANIFOLD_SOLID_BREP") == 1
    paths = [tuple(int(k) for k in i.split(".")) for i, _p in model.instances[:4]]
    assert paths == [(1, 1, 1, 1), (1, 1, 1, 2), (1, 1, 1, 3), (1, 1, 2, 1)]  # depth first, as the tree
    scene, _tree = _read_back(model)
    assert len(scene.items) == 27 and _boxes(scene) == _boxes(drawn)


def test_more_paths_than_the_items_bound_are_refused():
    from solidseas.errors import SldLimitError

    with open_model(_fan(10, 2), name="f.x_b", limits=Limits(items=99)) as doc:
        with pytest.raises(SldLimitError) as exc:
            step_model(doc)
    assert exc.value.detail["limit"] == "items"


@pytest.mark.parametrize(
    ("second", "reason"),
    [
        ({"rot": (1, 0, 0, 0, 1, 0, 0, 0, -1)}, "step_not_rigid"),  # mirrored
        ({"scale": 2.0}, "step_not_rigid"),
    ],
)
def test_an_instance_an_axis_placement_cannot_hold_refuses_the_export_unless_asked(second, reason):
    a = Asm()
    box = a.body(_shape(X.split_box, (0.01, 0.01, 0.01), 1))
    a.place(1, box, t=(0.05, 0, 0))
    a.place(1, box, **second)
    with open_model(x_b(a.transmit()), name="m.x_b") as doc:
        with pytest.raises(NotRepresentableError) as caught:
            step_model(doc)
        assert caught.value.detail["rule"] == "instances_left_out" and caught.value.detail["value"] == 1
        assert "1.2" in str(caught.value)
        model = step_model(doc, allow_partial=True)
        drawn = doc.scene()
        _m, why = printing.step_for_print(doc, None, "m")
    assert model.partial and model.incomplete == "1 instances left out"
    assert [s.reason for s in model.skipped] == [reason]
    assert any(w.code == "step_instances_left_out" for w in model.warnings)
    assert model.instances == (("1.1", "m body 1"),)
    scene, _tree = _read_back(model)
    assert _boxes(scene) == _boxes(drawn, {"1.1"})
    assert why.startswith("one of its instances cannot be written as STEP")


def test_an_instance_the_reader_leaves_out_is_left_out_of_the_step_too():
    a = Asm()
    box = a.body(_shape(X.split_box, (0.01, 0.01, 0.01), 1))
    a.place(1, box)
    bad = a.place(1, box)
    a.nodes[a.nodes[bad][1]["transform"]][1]["translation_vector"] = (math.nan, 0.0, 0.0)
    unset = a.place(1, box)
    a.nodes[a.nodes[unset][1]["transform"]][1]["rotation_matrix"][4] = NULL_DOUBLE
    with open_model(x_b(a.transmit()), name="b.x_b") as doc:
        with pytest.raises(NotRepresentableError) as caught:
            step_model(doc)
        assert caught.value.detail["value"] == 2
        model = step_model(doc, allow_partial=True)
    assert {(s.id, s.reason) for s in model.skipped} == {
        ("1.2", "non_finite_placement"),
        ("1.3", "non_finite_placement"),
    }
    assert model.counts["instances"] == 1


def test_an_assembly_of_sheets_is_written_when_sheets_are_asked_for():
    a = Asm()
    sheet = a.body(_shape(X.torus_band, 0.01, 0.003, -1.0, 1.0))
    a.place(1, sheet, t=(0.05, 0, 0))
    a.place(1, sheet, rot=ABOUT_X)
    with open_model(x_b(a.transmit()), name="s.x_b") as doc:
        with pytest.raises(NothingToExportError) as caught:
            step_model(doc)
        assert caught.value.detail["rule"] == "sheets_not_asked"
        model = step_model(doc, body_types=("solid", "sheet"))
    assert model.counts["sheets"] == 1 and model.counts["instances"] == 2


def test_a_body_not_asked_for_is_left_out_with_its_instances():
    a = Asm()
    box = a.body(_shape(X.split_box, (0.01, 0.01, 0.01), 1))
    sheet = a.body(_shape(X.torus_band, 0.01, 0.003, -1.0, 1.0))
    a.place(1, box)
    a.place(1, sheet, t=(0.05, 0, 0))
    with open_model(x_b(a.transmit()), name="s.x_b") as doc:
        model = step_model(doc)
    assert not model.partial and model.instances == (("1.1", "s body 1"),)
    assert model.counts["bodies_left_out"] == 1
    assert any(w.code == "bodies_left_out" and "1 sheet" in w.message for w in model.warnings)


def test_a_turn_is_rigid_and_a_mirror_scale_or_shear_is_not():
    turn = ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    assert _is_rigid(turn)
    assert not _is_rigid(((-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))
    assert not _is_rigid(((2.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 2.0)))
    assert not _is_rigid(((1.0, 0.5, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))  # determinant 1, sheared
