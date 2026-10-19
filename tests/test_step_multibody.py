"""Multi-body parts in the STEP export: SOLIDWORKS writes a multi-body part's STEP as
one product whose one shape representation holds a MANIFOLD_SOLID_BREP per body, and
writes the part's .x_b as one assembly that places each body at the identity. Both
must give the same STEP; a transmit that places bodies anywhere else is still an
assembly, written as one (tests/test_step_transmit_assembly.py)."""

import re

import pytest

import xt_bodies as X
from solidseas import open_document
from solidseas.formats import open_model
from solidseas.formats.xt import bodies_in_place
from solidseas.step import step_bytes, step_model
from solidseas_app.viewer import printing
from support import fixture_path
from test_formats_xt import ABOUT_X, Asm, _shape, x_b

STRUCTURE = (
    "SHAPE_DEFINITION_REPRESENTATION(",
    "ADVANCED_BREP_SHAPE_REPRESENTATION(",
    "MANIFOLD_SOLID_BREP(",
    "NEXT_ASSEMBLY_USAGE_OCCURRENCE(",
    "PRODUCT(",
)


def _structure(model) -> dict[str, int]:
    text = step_bytes(model, time_stamp="2026-10-05T00:00:00").decode("ascii")
    return {k: len(re.findall(re.escape(k), text)) for k in STRUCTURE}


ONE_PART_TWO_SOLIDS = {
    "SHAPE_DEFINITION_REPRESENTATION(": 1,
    "ADVANCED_BREP_SHAPE_REPRESENTATION(": 1,
    "MANIFOLD_SOLID_BREP(": 2,
    "NEXT_ASSEMBLY_USAGE_OCCURRENCE(": 0,
    "PRODUCT(": 1,
}


def _two_boxes(**second) -> Asm:
    a = Asm()
    a.place(1, a.body(_shape(X.split_box, (0.01, 0.01, 0.01), 2)))
    a.place(1, a.body(_shape(X.split_box, (0.02, 0.01, 0.01), 2)), **second)
    return a


def _open(a: Asm):
    return open_model(x_b(a.transmit()), name="s.x_b")


def test_the_fixture_part_and_its_transmit_give_the_same_step():
    with open_document(fixture_path("o12_multibody.SLDPRT")) as doc:
        part = step_model(doc)
    with open_model(fixture_path("o12_multibody.x_b").read_bytes(), name="o12_multibody.x_b") as doc:
        assert doc.doc_type == "assembly"  # the head says so; only the whole transmit tells
        transmit = step_model(doc)
    assert _structure(part) == _structure(transmit) == ONE_PART_TWO_SOLIDS
    assert part.counts["faces"] == transmit.counts["faces"] == 12


def test_bodies_gathered_at_the_identity_are_one_part():
    a = _two_boxes()
    assert bodies_in_place(a.transmit())
    with _open(a) as doc:
        model = step_model(doc)
    assert _structure(model) == ONE_PART_TWO_SOLIDS
    assert model.counts["solids"] == 2 and model.counts["instances"] == 0


def test_an_instance_without_a_transform_is_at_the_identity():
    a = _two_boxes(transform=False)
    assert bodies_in_place(a.transmit())


TWO_PARTS_PLACED = {
    "SHAPE_DEFINITION_REPRESENTATION(": 3,
    "ADVANCED_BREP_SHAPE_REPRESENTATION(": 2,
    "MANIFOLD_SOLID_BREP(": 2,
    "NEXT_ASSEMBLY_USAGE_OCCURRENCE(": 2,
    "PRODUCT(": 3,
}


@pytest.mark.parametrize(
    "second",
    [
        {"t": (0.05, 0, 0)},  # moved
        {"rot": ABOUT_X},  # turned
    ],
)
def test_a_body_placed_anywhere_else_is_still_an_assembly(second):
    a = _two_boxes(**second)
    assert not bodies_in_place(a.transmit())
    with _open(a) as doc:
        model = step_model(doc)
        printed, why = printing.step_for_print(doc, None, "s")
    assert _structure(model) == _structure(printed) == TWO_PARTS_PLACED and why is None
    assert model.doc_type == "assembly" and model.counts["instances"] == 2


def test_a_scaled_body_cannot_be_placed_in_a_step():
    a = _two_boxes(scale=2.0)
    assert not bodies_in_place(a.transmit())
    with _open(a) as doc:
        model, why = printing.step_for_print(doc, None, "s")
    assert model is None and why.startswith("one of its instances cannot be written as STEP")


def test_a_body_placed_twice_or_a_sub_assembly_is_an_assembly():
    a = Asm()
    body = a.body(_shape(X.split_box, (0.01, 0.01, 0.01), 2))
    a.place(1, body)
    a.place(1, body)
    assert not bodies_in_place(a.transmit())
    b = Asm()
    sub = b.assembly()
    b.place(sub, b.body(_shape(X.split_box, (0.01, 0.01, 0.01), 2)))
    b.place(1, sub)
    assert not bodies_in_place(b.transmit())


def test_a_body_no_instance_places_makes_it_an_assembly():
    a = _two_boxes()
    a.body(_shape(X.split_box, (0.01, 0.01, 0.01), 2))  # copied in, never placed
    assert not bodies_in_place(a.transmit())


def test_3d_print_sends_a_multi_body_transmit_as_step():
    assert printing.step_unavailable("parasolid", "assembly") is None  # the export decides
    assert printing.step_unavailable("solidworks", "assembly") is None  # written as an assembly
    with open_model(fixture_path("o12_multibody.x_b").read_bytes(), name="o12_multibody.x_b") as doc:
        model, why = printing.step_for_print(doc, None, "o12")
    assert why is None and model.counts["solids"] == 2 and model.counts["products"] == 1
