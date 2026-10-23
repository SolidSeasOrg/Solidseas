"""STEP written from parts that other readers build as Parasolid bodies in memory: STEP
files themselves, ACIS SAB files and Alibre Design parts (``solidseas.step``,
``BODY_FILE_FORMATS``). Each file is synthetic (``p21_writers``, ``sab_writers``,
``alibre_writers``), and each STEP written is checked by the export tests' own
independent re-reader and checkers (``step_support``) against the bodies it came from."""

import json

import pytest

import alibre_writers as A
import p21_writers as W
import sab_writers as S
import step_support as T
from solidseas import cli
from solidseas.errors import NothingToExportError, NotRepresentableError, UnsupportedOperationError
from solidseas.formats import open_model
from solidseas.step import step_bytes, step_model

STAMP = "2026-10-03T00:00:00Z"


def _written(data: bytes, name: str, **options):
    with open_model(data, name=name) as doc:
        m = step_model(doc, **options)
        transmits = [b.transmit for b in doc.bodies() or []]
    out = step_bytes(m, time_stamp=STAMP)
    return m, out, T.full_check(out, m, transmits)


def _sound(got: dict, faces: int) -> None:
    assert got["syntax"] == [] and got["topology"] == []
    assert got["geometry"]["beyond"] == []
    ori = got["orientation"]
    assert ori["disagree"] == [] and ori["agree"] == ori["faces"] == faces
    assert got["arcs"]["wrong"] == [] and got["pieces"]["wrong"] == []


def _brep_names(data: bytes) -> list[str]:
    f = T.read(data)
    return sorted(e.params[0] for kind in ("MANIFOLD_SOLID_BREP", "BREP_WITH_VOIDS") for e in f.of(kind))


@pytest.mark.parametrize(
    ("items", "faces", "split", "names"),
    [
        (lambda f: [W.box_brep(f)], 6, 0, ["box"]),
        (lambda f: [W.cylinder_brep(f, split=False)], 3, 0, ["cylinder"]),
        (lambda f: [W.hemisphere_brep(f)], 3, 1, ["dome"]),  # the cap is cut at its seams
        (lambda f: [W.void_box_brep(f)], 12, 0, ["void box"]),
        (lambda f: [W.box_brep(f, name="a"), W.box_brep(f, origin=(20, 0, 0), name="b")], 12, 0, ["a", "b"]),
    ],
    ids=["box", "cylinder", "hemisphere", "void", "two_bodies"],
)
def test_a_step_part_is_written_from_the_bodies_the_reader_built(items, faces, split, names):
    f, _ids = W.part_file(items)
    m, data, got = _written(f.bytes(), "part.step")
    assert m.source_format == "step" and m.doc_type == "part" and not m.partial
    assert m.counts["split_faces"] == split and m.counts["products"] == 1
    assert m.originating_system == "Synthetic Writer 1.0"
    _sound(got, faces)
    assert _brep_names(data) == names


def test_a_step_assembly_is_refused():
    with open_model(W.assembly_file(), name="asm.step") as doc:
        with pytest.raises(UnsupportedOperationError) as exc:
            step_model(doc)
    assert exc.value.detail == {"rule": "model_assembly", "value": "step"}


def test_a_step_body_placed_away_from_its_parts_origin_is_refused():
    """A box placed in its part by a mapped item 50 mm along x: what the reader holds is the
    box at its own origin, which written as the part's body would be in the wrong place."""
    f = W.P21()
    ctx = f.units()
    box = W.box_brep(f)
    held = f.add(f"ADVANCED_BREP_SHAPE_REPRESENTATION('',(#{f.axis2()},#{box}),#{ctx})")
    rmap = f.add(f"REPRESENTATION_MAP(#{f.axis2()},#{held})")
    item = f.add(f"MAPPED_ITEM('moved',#{rmap},#{f.axis2((50, 0, 0))})")
    pd = f.product("part")
    pds = f.add(f"PRODUCT_DEFINITION_SHAPE('','',#{pd})")
    rep = f.add(f"SHAPE_REPRESENTATION('',(#{f.axis2()},#{item}),#{ctx})")
    f.add(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{rep})")
    with open_model(f.bytes(), name="moved.step") as doc:
        assert doc.doc_type == "part"
        with pytest.raises(UnsupportedOperationError) as exc:
            step_model(doc)
    assert exc.value.detail == {"rule": "model_placed", "value": "step"}


def test_a_body_the_reader_built_without_a_face_is_not_written_without_loss():
    f, _ids = W.part_file(
        lambda f: [W.box_brep(f, name="whole"), W.box_brep(f, (5, 5, 5), (30, 0, 0), name="cut")]
    )
    text = f.bytes()
    at = text.index(b"PLANE('',", text.index(b"MANIFOLD_SOLID_BREP('whole'"))  # a plane of the second box
    text = text[:at] + b"HYPERBOLIC_THING(''," + text[at + len(b"PLANE('',") :]
    with open_model(text, name="damaged.step") as doc:
        with pytest.raises(NotRepresentableError) as exc:
            step_model(doc)
    assert exc.value.detail == {"rule": "faces_left_out", "value": 1}
    assert "cut (1 face not read)" in str(exc.value)
    m, data, got = _written(text, "damaged.step", allow_partial=True)
    assert m.partial and _brep_names(data) == ["whole"]
    assert "step_bodies_left_out" in {w.code for w in m.warnings}
    assert got["syntax"] == [] and got["topology"] == []


def test_faceted_items_beside_the_bodies_are_not_dropped_unsaid():
    data = W.part_file(lambda f: [W.box_brep(f), W.faceted_box(f, (5, 5, 5))], kind="SHAPE_REPRESENTATION")[0]
    with open_model(data.bytes(), name="mixed.step") as doc:
        with pytest.raises(NotRepresentableError) as exc:
            step_model(doc)
        assert "1 faceted or tessellated items" in str(exc.value)
        m = step_model(doc, allow_partial=True)
    assert m.partial and m.counts["bodies"] == 1
    data = W.part_file(lambda f: [W.faceted_box(f)], kind="FACETED_BREP_SHAPE_REPRESENTATION")[0]
    with open_model(data.bytes(), name="mesh.step") as doc:
        with pytest.raises(NothingToExportError):
            step_model(doc, allow_partial=True)


@pytest.mark.parametrize(
    ("make", "faces", "split"),
    [(lambda: S.cube(1.0), 6, 0), (S.cylinder, 4, 1), (S.ring_torus, 1, 0), (S.half_sphere, 3, 1)],
    ids=["cube", "cylinder", "torus", "half_sphere"],
)
def test_an_acis_sab_file_is_written_from_its_bodies(make, faces, split):
    m, _data, got = _written(make().sab(), "shape.sab", body_types=("solid", "sheet"))
    assert m.source_format == "acis" and m.counts["split_faces"] == split
    _sound(got, faces)


def test_an_acis_face_the_reader_cannot_map_refuses_the_export():
    with open_model(S.elliptic_cone().sab(), name="e.sab") as doc:
        with pytest.raises(NotRepresentableError) as exc:
            step_model(doc)
    assert exc.value.detail["rule"] == "faces_left_out"


def test_an_alibre_part_is_written_from_its_acis_body_and_an_assembly_is_refused():
    m, data, got = _written(A.part(), "cube.AD_PRT")
    assert m.source_format == "alibre" and m.originating_system.startswith("Alibre Design")
    _sound(got, 6)
    assert _brep_names(data) == ["cube"]
    with open_model(A.assembly([A.Placed(A.CUBE_GUID)]), name="pair.AD_ASM") as doc:
        with pytest.raises(UnsupportedOperationError) as exc:
            step_model(doc)
    assert exc.value.detail == {"rule": "model_assembly", "value": "alibre"}


def test_the_command_line_exports_a_step_part_as_step(tmp_path, capsys):
    src = tmp_path / "in" / "box.step"
    src.parent.mkdir()
    src.write_bytes(W.box_file())
    code = cli.main(["export", str(src), "--format", "step", "-o", str(tmp_path / "out.step"), "--json"])
    env = json.loads(capsys.readouterr().out)
    assert code == 0 and env["data"]["format"] == "step", env
    assert T.syntax_problems(T.read((tmp_path / "out.step").read_bytes())) == []
