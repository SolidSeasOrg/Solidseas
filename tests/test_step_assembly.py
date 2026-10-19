"""STEP of SOLIDWORKS assemblies: one product for the assembly and one for each part and
configuration it places, each instance a NEXT_ASSEMBLY_USAGE_OCCURRENCE at its placement.
Read back with SolidSeas' own STEP reader, every instance sits where the 3D view draws
it; a component that cannot be written refuses the export unless allow_partial."""

import re
import shutil

import pytest

import step_support as T
from solidseas import geometry as geo
from solidseas import open_document
from solidseas.errors import NothingToExportError, NotRepresentableError
from solidseas.formats import open_model
from solidseas.roots import Root, Roots
from solidseas.step import step_bytes, step_model
from solidseas.step.assembly import _is_rotation
from support import FIXTURES, fixture_path

O08, O15, O16 = "o08_asm_2x_boxA.SLDASM", "o15_sub_asm.SLDASM", "o16_asm_features.SLDASM"


def _count(text: str, entity: str) -> int:
    return len(re.findall(rf"={re.escape(entity)}\(", text))


def _box(placement, positions) -> tuple:
    pts = [placement.apply(positions[i : i + 3]) for i in range(0, len(positions), 3)]
    lo = [min(p[k] for p in pts) for k in range(3)]
    hi = [max(p[k] for p in pts) for k in range(3)]
    return tuple(round(v * 1000.0, 3) for v in (*lo, *hi))


def _export(name: str, **kw):
    with open_document(fixture_path(name)) as doc:
        model = step_model(doc, **kw)
        drawn = geo.display_geometry(doc, sources=("file", "brep"), max_brep_seconds=30.0)  # as the export
    return model, drawn


def _read_back(model) -> list[tuple]:
    with open_model(step_bytes(model, time_stamp="2026-10-07T00:00:00"), name="a.step") as doc:
        scene = doc.scene()
    return sorted(_box(it.placement, scene.objects[it.object].positions) for it in scene.items)


@pytest.mark.parametrize(("name", "parts", "instances"), [(O08, 1, 2), (O15, 2, 2)])
def test_an_assembly_is_a_product_per_part_and_an_occurrence_per_instance(name, parts, instances):
    model, drawn = _export(name)
    text = step_bytes(model, time_stamp="2026-10-07T00:00:00").decode("ascii")
    assert model.doc_type == "assembly" and not model.partial and model.exact
    assert model.counts["products"] == 1 + parts and model.counts["instances"] == instances
    assert _count(text, "PRODUCT") == 1 + parts
    assert _count(text, "NEXT_ASSEMBLY_USAGE_OCCURRENCE") == instances
    assert _count(text, "CONTEXT_DEPENDENT_SHAPE_REPRESENTATION") == instances
    assert _count(text, "MANIFOLD_SOLID_BREP") == parts  # each part written once, however often placed
    want = sorted(_box(i.placement, drawn.meshes[i.mesh].mesh.positions) for i in drawn.instances)
    assert _read_back(model) == want  # every instance where the 3D view draws it, sub-assemblies' too
    checked = T.file_check(text.encode("ascii"))
    assert checked["problems"] == [] and checked["solids"] == parts


def test_a_component_that_cannot_be_written_refuses_the_assembly_unless_asked():
    """o16 places o06 in a configuration whose bodies o06 does not store: as for a part,
    another configuration's geometry is never written in its place."""
    with open_document(fixture_path(O16)) as doc:
        with pytest.raises(NotRepresentableError) as caught:
            step_model(doc)
    assert caught.value.detail["rule"] == "instances_left_out" and caught.value.detail["value"] == 1
    assert "o06_boxA_props_mat_cfg-1" in str(caught.value) and "'OracleAlt'" in str(caught.value)
    model, drawn = _export(O16, allow_partial=True)
    assert model.partial and model.incomplete == "1 instances left out"
    assert any(w.code == "step_instances_left_out" for w in model.warnings)
    placed = dict(model.instances)
    assert set(placed) == {i.id for i in drawn.instances} - {"o06_boxA_props_mat_cfg-1"}
    assert placed["Part12^o16_asm_features-1"] == "Part12^o16_asm_features"  # a virtual part, from inside o16
    assert placed["o15_sub_asm-1/o07_boxB_h31-1"] == "o07_boxB_h31"  # flattened out of its sub-assembly
    want = sorted(
        _box(i.placement, drawn.meshes[i.mesh].mesh.positions) for i in drawn.instances if i.id in placed
    )
    assert _read_back(model) == want


def test_an_assembly_whose_parts_are_all_missing_has_nothing_to_write(tmp_path):
    shutil.copy(FIXTURES / O08, tmp_path / O08)  # without o02_boxA beside it
    with open_document(tmp_path / O08) as doc:
        with pytest.raises((NothingToExportError, NotRepresentableError)):
            step_model(doc, roots=Roots([Root("here", str(tmp_path))]), allow_outside_roots=False)


def test_a_mirrored_placement_is_not_a_rotation():
    assert _is_rotation(((1, 0, 0), (0, 1, 0), (0, 0, 1)))
    assert _is_rotation(((0, -1, 0), (1, 0, 0), (0, 0, 1)))
    assert not _is_rotation(((-1, 0, 0), (0, 1, 0), (0, 0, 1)))  # a mirror STEP's axis placement cannot hold


def test_a_sub_assembly_is_a_product_of_its_own_placing_its_parts():
    """o16 places o15, which places two parts (one turned 40 degrees): o15 is an assembly
    product of its own, and its occurrences place its parts in its frame."""
    model, _drawn = _export(O16, allow_partial=True)
    text = step_bytes(model, time_stamp="2026-10-07T00:00:00").decode("utf-8")
    assert [p.name for p in model.products if p.kind == "assembly"] == ["o16_asm_features", "o15_sub_asm"]
    assert model.counts["sub_assemblies"] == 1 and model.counts["products"] == 7
    assert _count(text, "NEXT_ASSEMBLY_USAGE_OCCURRENCE") == 12  # 10 in o16 and 2 in o15
    with open_model(text.encode("utf-8"), name="a.step") as doc:
        nodes = [n for n in doc.tree().nodes if n.kind != "body"]
    sub = next(n for n in nodes if n.name == "o15_sub_asm-1")
    assert sub.parent == "1" and sorted(n.name for n in nodes if n.parent == sub.id) == [
        "o02_boxA-1",
        "o07_boxB_h31-1",
    ]


def test_a_placement_seen_from_its_parent_and_back():
    from solidseas.formats.solidworks.components import Placement
    from solidseas.step.assembly import _inverse, _relative

    turned = Placement(((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)), (0.1, 0.2, 0.3))
    inner = Placement(((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)), (0.01, 0.0, 0.0))
    world = turned.then(inner)
    back = _relative(turned, world)
    assert all(abs(a - b) < 1e-12 for a, b in zip(back.translation_m, inner.translation_m, strict=True))
    assert _inverse(turned).then(turned).apply((1.0, 2.0, 3.0)) == pytest.approx((1.0, 2.0, 3.0))
