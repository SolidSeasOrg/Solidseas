"""Drawings of parts read from STEP, Parasolid and Alibre Design files (docs/DRAWINGS.md
3.5, ``dwg-sources``): the source of 6.2 for each, refusals, and the same part drawn
from each of its files.

SOLIDWORKS wrote o02 as STEP, .x_t and .x_b and o11 and o12 as .x_b; the Alibre parts
and the STEP assembly, mesh and inch files are written here by code."""

import pytest

import alibre_writers as A
import p21_writers as P
import sab_writers as W
import xt_bodies as X
from drawing_support import fixture
from solidseas.drawing import document, make_drawing, pipeline
from solidseas.drawing import settings as S
from solidseas.drawing import source as src
from solidseas.drawing.types import DrawingOptions
from solidseas.errors import ConfigurationNotFoundError, InvalidArgumentError, UnsupportedOperationError
from solidseas.formats.base import open_model
from solidseas.formats.solidworks import parasolid as ps

SETTINGS = S.with_value(S.DrawingSettings(), "company", "name", "Example Engineering Co.")
MM = DrawingOptions(units="mm")


def _plan(part) -> list[tuple]:
    """What a drawing of ``part`` states: each dimension's key, kind and value (to a
    nanometre), and its text."""
    d = make_drawing(part, options=MM, settings=SETTINGS)
    return sorted((r.key, r.kind, round(r.value, 9), r.prefix) for r in d.dimensions)


# --------------------------------------------------------------------------- the source
@pytest.mark.parametrize(
    "name, fmt", [("o02_boxA.step", "step"), ("o02_boxA.x_t", "parasolid"), ("o02_boxA.x_b", "parasolid")]
)
def test_a_part_of_another_format_is_read_as_its_sldprt_is(name, fmt):
    s = src.open_source(fixture(name))
    part = src.open_source(fixture("o02_boxA.SLDPRT"))
    assert (s.name, s.format, s.kind, s.configuration) == (name, fmt, "brep", None)
    assert [(b.name, b.faces, b.type, b.selected, b.hidden) for b in s.bodies] == [
        ("Boss-Extrude1", 6, "solid", True, False)
    ]
    assert s.geometry_digest == part.geometry_digest  # the same faces, whatever file they came from
    assert len(s.sha256) == 64 and s.sha256 != part.sha256
    assert len(s.selected_bodies()) == 1 and s.selected_bodies()[0].transmit is not None


def test_a_step_file_states_its_unit_and_a_parasolid_file_never_does():
    step = src.open_source(fixture("o02_boxA.step"))
    assert (step.units.unit, step.units.origin, step.units.stated) == ("mm", "file", "mm")
    # a transmit is in metres whatever the part was designed in: the unit is guessed
    xt = src.open_source(fixture("o02_boxA.x_t"))
    assert (xt.units.unit, xt.units.origin, xt.units.stated) == ("mm", "guessed", None)
    assert xt.units.evidence is not None
    assert src.open_source(fixture("o02_boxA.x_b"), units="in").units.origin == "user"
    f, _ids = P.part_file(lambda f: [P.box_brep(f, size=(1.0, 2.0, 0.5))], length="in")
    with open_model(f.bytes(), name="inch.step") as doc:
        inch = src.open_source(doc)
    assert (inch.units.unit, inch.units.origin) == ("in", "file")


def test_a_step_file_that_states_no_unit_has_its_unit_guessed():
    f = P.P21()
    ctx = f.add("(GEOMETRIC_REPRESENTATION_CONTEXT(3)REPRESENTATION_CONTEXT('',''))")
    f.shape(f.product("p"), [P.box_brep(f)], ctx)
    with open_model(f.bytes(), name="bare.step") as doc:
        assert doc.units["source"] == "assumed"
        s = src.open_source(doc)
    assert s.units.origin == "guessed" and s.units.stated is None


def test_the_multibody_x_b_solidworks_writes_is_one_part_of_two_bodies():
    s = src.open_source(fixture("o12_multibody.x_b"))
    part = src.open_source(fixture("o12_multibody.SLDPRT"))
    assert sorted(b.name for b in s.bodies) == ["Boss-Extrude1", "Boss-Extrude2"]
    assert all(b.selected and b.faces == 6 for b in s.bodies)
    assert s.geometry_digest == part.geometry_digest
    one = src.open_source(fixture("o12_multibody.x_b"), bodies=("Boss-Extrude2",))
    assert [b.name for b in one.selected_bodies()] == ["Boss-Extrude2"]
    with pytest.raises(InvalidArgumentError):
        src.open_source(fixture("o12_multibody.x_b"), bodies=("nope",))


def test_an_alibre_part_is_read_with_its_unit_and_properties():
    data = A.part(solid=W.cylinder(1.0, 3.0))  # a cylinder in centimetres
    with open_model(data, name="pin.AD_PRT") as doc:
        s = src.open_source(doc, title_names=("Number", "Description"))
        assert doc.doc_type == "part"  # the document is left open
    assert (s.name, s.format, s.configuration) == ("pin.AD_PRT", "alibre", None)
    assert (s.units.unit, s.units.origin, s.units.stated) == ("mm", "file", "mm")
    assert [(b.name, b.faces) for b in s.bodies] == [("pin", 3)]
    assert s.property("Number") == "TC-1" and s.property("description") == "A cube for the tests"
    assert s.sha256 is None  # read from memory: no file to hash


def test_a_file_that_names_no_body_gets_a_name_for_each():
    xt = X.cylinder()
    xt.max_types = 231
    data = (ps.text_header(xt, fmt="text", key="k", file="k.x_t") + ps.write_text(xt) + "\n").encode(
        "latin-1"
    )
    with open_model(data, name="k.x_t") as doc:
        s = src.open_source(doc)
    assert [b.name for b in s.bodies] == ["Body1"]


# --------------------------------------------------------------------------- refusals
@pytest.mark.parametrize(
    "name, rule",
    [("o18_drw_boxA.SLDDRW", "drawing"), ("o02_boxA.STL", "format_later"), ("o02_boxA.3mf", "format_later")],
)
def test_drawings_and_meshes_are_refused_by_their_extension(name, rule):
    with pytest.raises(UnsupportedOperationError) as info:
        src.open_source(fixture(name))
    assert info.value.code == "not_implemented" and info.value.detail["rule"] == rule


def test_a_step_assembly_is_refused_for_now():
    with open_model(P.assembly_file(), name="pair.step") as doc:
        with pytest.raises(UnsupportedOperationError) as info:
            src.open_source(doc)
    assert info.value.detail == {"rule": "format_later", "value": "step"}
    assert "SOLIDWORKS assemblies" in str(info.value)


@pytest.mark.parametrize("moved", [False, True])
def test_a_parasolid_assembly_is_drawn_only_when_it_gathers_one_parts_bodies(moved):
    from test_formats_xt import Asm, x_t

    a = Asm()
    cyl, box = (a.body(_written(X.cylinder())), a.body(_written(X.split_box((0.03, 0.02, 0.01), 1))))
    a.place(1, cyl)
    a.place(1, box, t=(0.05, 0.0, 0.0) if moved else (0.0, 0.0, 0.0))
    with open_model(x_t(a.transmit()), name="pair.x_t") as doc:
        assert doc.doc_type == "assembly"
        if not moved:  # as SOLIDWORKS writes a multi-body part: drawn as that part
            assert len(src.open_source(doc).bodies) == 2
            return
        with pytest.raises(UnsupportedOperationError) as info:
            src.open_source(doc)
    assert info.value.detail == {"rule": "format_later", "value": "parasolid"}


def _written(xt):
    xt.max_types = 231  # XtBuilder leaves it unset; a written transmit carries it
    return xt


def test_a_file_of_triangles_is_refused_until_mesh_drawings_come():
    f, _ids = P.part_file(lambda f: [P.tessellated_box(f)], kind="TESSELLATED_SHAPE_REPRESENTATION")
    with open_model(f.bytes(), name="mesh.step") as doc:
        with pytest.raises(UnsupportedOperationError) as info:
            src.open_source(doc)
    assert info.value.detail["rule"] == "format_later" and "meshes" in str(info.value)


def test_an_alibre_assembly_is_refused():
    data = A.assembly([A.Placed(A.CUBE_GUID)])
    with open_model(data, name="pair.AD_ASM") as doc:
        with pytest.raises(UnsupportedOperationError) as info:
            src.open_source(doc)
    assert info.value.detail["rule"] == "format_later"


def test_a_file_of_another_format_has_no_configuration():
    with pytest.raises(ConfigurationNotFoundError):
        src.open_source(fixture("o02_boxA.step"), configuration="Default")


# --------------------------------------------------------------------------- drawings
def test_the_same_part_as_sldprt_step_and_x_t_gives_the_same_plan():
    """Stage 2's acceptance check 3: one part, one plan, whichever file it is read from."""
    expected = _plan(fixture("o02_boxA.SLDPRT"))
    assert expected
    for name in ("o02_boxA.step", "o02_boxA.x_t", "o02_boxA.x_b"):
        assert _plan(fixture(name)) == expected, name


def test_a_curved_part_drawn_from_its_x_b_is_planned_as_from_its_sldprt():
    assert _plan(fixture("o11_curved.x_b")) == _plan(fixture("o11_curved.SLDPRT"))


def test_a_drawing_names_its_model_and_takes_its_number_from_the_file_name():
    d = make_drawing(fixture("o02_boxA.step"), options=MM, settings=SETTINGS)
    assert d.model["name"] == "o02_boxA.step" and d.model["format"] == "step"
    assert d.model["units"] == {"unit": "mm", "origin": "user"}
    assert document.title_text(d, "number") == "O02_BOXA"
    assert document._model_stem(d) == "o02_boxA"
    assert document.name_base(d).startswith("O02_BOXA")


def test_an_alibre_part_is_drawn():
    data = A.part(solid=W.cylinder(1.0, 3.0))
    with open_model(data, name="pin.AD_PRT") as doc:
        run = pipeline.run(doc, options=MM, settings=SETTINGS)
    assert run.source.format == "alibre"
    assert any(r.kind == "diameter" and abs(r.value - 0.02) < 1e-9 for r in run.drawing.dimensions)
    assert any(r.key.startswith("size/") and abs(r.value - 0.03) < 1e-9 for r in run.drawing.dimensions)


def test_the_drawing_process_probes_a_part_of_another_format():
    """What page 1 of the wizard reads (``drawingproc``'s probe): a STEP part has no
    configurations, and a mesh is refused by its extension, opening nothing."""
    from solidseas_app.viewer import drawingproc

    out, _files = drawingproc._do_probe({"op": "probe", "part": fixture("o02_boxA.step")})
    assert out["refused"] is None and out["configurations"] == [] and out["active_configuration"] is None
    assert (out["units"]["unit"], out["units"]["origin"]) == ("mm", "file")
    assert [(b["name"], b["faces"], b["selected"]) for b in out["bodies"]] == [("Boss-Extrude1", 6, True)]
    assert [round(v * 1000, 6) for v in out["size_m"]] == [10.0, 20.0, 30.0]
    out, _files = drawingproc._do_probe({"op": "probe", "part": fixture("o02_boxA.STL")})
    assert out["refused"] and out["refused_rule"] == "format_later"
    with pytest.raises(ConfigurationNotFoundError):
        drawingproc._do_probe({"op": "probe", "part": fixture("o02_boxA.x_t"), "configuration": "Default"})
