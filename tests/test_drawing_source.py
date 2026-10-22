"""The drawing's source: a SOLIDWORKS part read for a drawing (docs/DRAWINGS.md 6.2),
on the o01 to o19 fixtures."""

import pytest

from drawing_support import fixture
from solidseas import open_document
from solidseas.drawing import source as S
from solidseas.errors import InvalidArgumentError, UnsupportedOperationError

BOX = ("o02_boxA.SLDPRT", "o03_boxA_again.SLDPRT", "o04_boxA_props.SLDPRT", "o09_import_step.SLDPRT")


def test_a_part_is_read_with_its_identity_and_units():
    s = S.open_source(fixture("o02_boxA.SLDPRT"))
    assert s.name == "o02_boxA.SLDPRT" and s.format == "sldprt" and s.kind == "brep"
    assert s.configuration == "Default"
    assert [(b.faces, b.type, b.selected) for b in s.bodies] == [(6, "solid", True)]
    assert (s.units.unit, s.units.origin, s.units.stated) == ("mm", "file", "mm")
    assert len(s.sha256) == 64 and len(s.geometry_digest) == 64
    assert len(s.selected_bodies()) == 1


def test_the_name_is_the_file_name_only():
    s = S.open_source(fixture("o17_деталь.SLDPRT"))
    assert s.name == "o17_деталь.SLDPRT" and "/" not in s.name and "\\" not in s.name


@pytest.mark.parametrize("name", BOX[1:])
def test_the_geometry_digest_survives_saves_that_changed_no_geometry(name):
    first = S.open_source(fixture(BOX[0]))
    other = S.open_source(fixture(name))
    assert other.geometry_digest == first.geometry_digest
    assert other.sha256 != first.sha256  # a different file all the same


def test_a_geometry_change_changes_the_digest():
    a = S.open_source(fixture("o02_boxA.SLDPRT"))
    for name in ("o07_boxB_h31.SLDPRT", "o10_import_step_cut.SLDPRT", "o11_curved.SLDPRT"):
        assert S.open_source(fixture(name)).geometry_digest != a.geometry_digest


def test_properties_material_and_their_digest():
    names = ("PartNo", "Description")
    plain = S.open_source(fixture("o02_boxA.SLDPRT"), title_names=names)
    props = S.open_source(fixture("o05_boxA_props_mat.SLDPRT"), title_names=names)
    assert props.material == "1060 Alloy"
    assert props.property("partno") == "ORACLE-PN-123"
    assert props.property("Missing", "Description") == "Oracle test box"
    assert props.properties_digest != plain.properties_digest
    # a property the title block does not read leaves the digest alone
    assert (
        S.open_source(fixture("o05_boxA_props_mat.SLDPRT"), title_names=("Nope",)).properties_digest
        == S.open_source(fixture("o02_boxA.SLDPRT"), title_names=("Nope",)).properties_digest
    )


def test_a_configuration_is_chosen_by_name():
    s = S.open_source(fixture("o06_boxA_props_mat_cfg.SLDPRT"), configuration="OracleAlt")
    assert s.configuration == "OracleAlt"


def test_bodies_are_chosen_by_name_and_unknown_names_refused():
    s = S.open_source(fixture("o12_multibody.SLDPRT"))
    assert [b.selected for b in s.bodies] == [True, True]
    one = S.open_source(fixture("o12_multibody.SLDPRT"), bodies=(s.bodies[1].name,))
    assert [b.selected for b in one.bodies] == [False, True]
    assert [b.name for b in one.selected_bodies()] == [s.bodies[1].name]
    with pytest.raises(InvalidArgumentError):
        S.open_source(fixture("o12_multibody.SLDPRT"), bodies=("nope",))


def test_the_users_unit_wins_over_the_parts():
    s = S.open_source(fixture("o02_boxA.SLDPRT"), units="in")
    assert (s.units.unit, s.units.origin, s.units.stated) == ("in", "user", "mm")
    with pytest.raises(InvalidArgumentError):
        S.open_source(fixture("o02_boxA.SLDPRT"), units="cm")


def test_an_open_document_is_read_and_left_open():
    with open_document(fixture("o11_curved.SLDPRT")) as doc:
        s = S.open_source(doc)
        assert s.name == "o11_curved.SLDPRT" and s.bodies[0].faces == 12
        assert doc.doc_type == "part"  # still usable


@pytest.mark.parametrize(
    "name, rule",
    [
        ("o18_drw_boxA.SLDDRW", "drawing"),
        ("o02_boxA.STL", "format_later"),
    ],
)
def test_drawings_take_parts_and_assemblies_only(name, rule):
    # STEP, Parasolid and Alibre parts are drawn too: tests/test_drawing_sources.py
    with pytest.raises(UnsupportedOperationError) as info:
        S.open_source(fixture(name))
    assert info.value.code == "not_implemented" and info.value.detail["rule"] == rule


def test_a_part_with_no_bodies_has_none_to_draw():
    s = S.open_source(fixture("o01_empty.SLDPRT"))
    assert s.bodies == () and s.selected_bodies() == []
    assert any("no bodies" in w for w in s.warnings)


def test_keyword_hints_are_numbers_only():
    assert S._hints("bore 12.5 depth 30, M6 thread, -2") == (12.5, 30.0, -2.0)
    assert S._hints(None) == ()
