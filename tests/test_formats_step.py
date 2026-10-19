"""The STEP reader (``docs/formats/step.md``, ``docs/API.md`` 3.20.7): the Part 21 parser,
the B-rep builder, the box SOLIDWORKS wrote, synthetic files from
``tests/p21_writers.py`` for every surface, curve, topology form, assembly form,
unit, colour and property the reader takes, and the model on every surface."""

import io
import json
import math
import re
import zipfile
from pathlib import Path

import pytest

import p21_writers as W
import xt_bodies
from jsonschema_subset import validate
from solidseas import cli, export, model, scan
from solidseas.errors import FormatNotSupportedError, NothingToExportError, SldFormatError, SldLimitError
from solidseas.formats import Limits, open_model, readable
from solidseas.formats.solidworks.parasolid import read_file, text_header, write_text
from solidseas.formats.solidworks.parasolid import validate as xt_validate
from solidseas.formats.step import part21
from solidseas.formats.step.builder import BrepBuilder, GeometryRefused
from solidseas.tessellate import tessellate_transmit
from support import fixture_path

FIXTURE = fixture_path("o02_boxA.step")
GROUND_TRUTH = json.loads(fixture_path("ground_truth.json").read_text(encoding="utf-8"))
BS = "\\"
SURFACE_MODEL = "MANIFOLD_SURFACE_SHAPE_REPRESENTATION"


def _codes(warnings) -> set[str]:
    return {w.code for w in warnings}


def _volume(scene) -> float:
    return sum(scene.objects[it.object].measures()["volume_m3"] for it in scene.items)


def _closed(obj) -> bool:
    pos, tris = export.weld(obj)
    return export.oriented_closed(tris, len(pos) // 3)


def _read(data: bytes, name: str = "t.step", **kw):
    return open_model(data, name=name, **kw)


def _part(items_fn, **kw) -> bytes:
    f, _ids = W.part_file(items_fn, **kw)
    return f.bytes()


# --------------------------------------------------------------------------- registry
def test_the_reader_is_registered_and_readable():
    assert readable("step")
    with _read(W.box_file()) as doc:
        assert doc.format == "step" and doc.format_name == "STEP"


@pytest.mark.parametrize(
    ("schemas", "variant"),
    [
        (("CONFIG_CONTROL_DESIGN",), "AP203"),
        (
            (
                "AP203_CONFIGURATION_CONTROLLED_3D_DESIGN_OF_MECHANICAL_PARTS_AND_ASSEMBLIES_MIM_LF"
                " { 1 0 10303 403 }",
            ),
            "AP203",
        ),
        (("AUTOMOTIVE_DESIGN { 1 0 10303 214 3 1 1 }",), "AP214"),
        (("automotive_design",), "AP214"),
        (("AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF { 1 0 10303 442 1 1 4 }",), "AP242"),
        (("STRUCTURAL_FRAME_SCHEMA",), "other"),
    ],
)
def test_the_variant_comes_from_the_schema(schemas, variant):
    f, _ids = W.part_file(lambda f: [W.box_brep(f)])
    f.schema = schemas
    with _read(f.bytes()) as doc:
        assert doc.variant == variant
        assert _volume(doc.scene()) == pytest.approx(6e-6, rel=1e-9)


def test_alibre_design_history_is_refused():
    with pytest.raises(FormatNotSupportedError) as exc:
        _read(W.alibre_file())
    assert exc.value.detail == {"rule": "private_schema", "value": "ALIBRE_SCHEMA"}


# --------------------------------------------------------------------------- Part 21
def test_the_header_section():
    h = part21.read_header(W.box_file(), Limits())
    assert h.description == ("synthetic test file",) and h.implementation_level == "2;1"
    assert (h.name, h.time_stamp, h.author, h.organization) == (
        "synthetic.step",
        "2026-05-04T03:02:01",
        ("A. Tester",),
        ("Test Shop",),
    )
    assert h.originating_system == "Synthetic Writer 1.0" and h.preprocessor_version == "p21_writers"
    assert h.schemas == ("AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }",)


def test_values_complex_instances_and_comments():
    text = (
        b"ISO-10303-21;\nHEADER;FILE_DESCRIPTION(('x'),'2;1');FILE_NAME('n','t',(''),(''),'p','o','');"
        b"FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));ENDSEC;\n"
        b"/* a comment; with a 'quote */ DATA;\n"
        b"#10=SOME_ENTITY('a;b',(1,-2,+3),(1.5,-2.E-3,.5,1E2),.T.,.UNSPECIFIED.,$,*,#11,\n"
        b'  LENGTH_MEASURE(25.4),(( #12 ,#13),()),"0FF");\n'
        b"#11=(NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.)LENGTH_UNIT());\n"
        b"#12 = OTHER ( ) ; /* trailing */\n#13=OTHER();\n"
        b"ENDSEC;\nEND-ISO-10303-21;\n"
    )
    p = part21.open(text, limits=Limits())
    r = p.record(10)
    assert r.type == "SOME_ENTITY" and not r.complex
    a = r.params
    assert a[0] == "a;b" and a[1] == [1, -2, 3] and a[2] == [1.5, -2e-3, 0.5, 100.0]
    assert a[3] == "T" and isinstance(a[3], part21.Enum) and part21.as_bool(a[3]) is True
    assert a[4] == "UNSPECIFIED" and a[5] is None and a[6] is part21.DERIVED
    assert isinstance(a[7], part21.Ref) and a[7] == 11
    assert a[8] == part21.Typed("LENGTH_MEASURE", 25.4)
    assert a[9] == [[12, 13], []] and isinstance(a[10], part21.Binary)
    u = p.record(11)
    assert u.complex and u.types == ("NAMED_UNIT", "SI_UNIT", "LENGTH_UNIT")
    assert u.part("SI_UNIT") == ["MILLI", "METRE"] and u.part("NOPE") is None
    assert p.ids_of_type("OTHER") == [12, 13] and p.ids_of_type("SI_UNIT") == [11]
    assert p.type_of(11) == ("NAMED_UNIT", "SI_UNIT", "LENGTH_UNIT") and p.type_of(99) is None
    with pytest.raises(SldFormatError):
        p.record(99)


def test_every_string_escape():
    raw = (
        "a''b"
        + BS
        + "X2"
        + BS
        + "00E9"
        + BS
        + "X0"
        + BS
        + "c"
        + BS
        + "X"
        + BS
        + "E9"
        + BS
        + "S"
        + BS
        + "a "
        + BS
        + BS
        + " x\r\ny"
    ).encode()
    assert part21.decode_string(raw) == "a'b\u00e9c\u00e9\u00e1 \\ xy"
    assert part21.decode_string((BS + "X4" + BS + "0001F600" + BS + "X0" + BS).encode()) == "\U0001f600"
    assert part21.decode_string((BS + "PB" + BS + BS + "S" + BS + "1").encode()) == "\u0105"  # ISO 8859-2
    assert part21.decode_string((BS + "N" + BS + "x" + BS + "F" + BS).encode()) == "x"
    assert part21.decode_string((BS + "X2" + BS + "00E").encode()) == BS + "X2" + BS + "00E"  # not an escape
    assert part21.decode_string("caf\u00e9".encode()) == "caf\u00e9"  # UTF-8 as some writers store it
    assert part21.decode_string(b"caf\xe9") == "caf\u00e9"  # Latin-1 as others do
    with _read(W.escapes_file()) as doc:
        doc.tree()
        props = {p.name: p.value for p in doc.properties}
        assert props["product_name"] == "caf\u00e9 \u00e9\u00e8 \U0001f600 \u00e9 \u0105 it's \\ done"


def test_a_file_whose_instances_are_out_of_order_and_in_two_sections():
    f, _ids = W.part_file(lambda f: [W.box_brep(f)])
    data = f.bytes(order="reversed", newline="\r\n")
    with _read(data) as doc:
        assert _volume(doc.scene()) == pytest.approx(6e-6, rel=1e-9)
    text = f.bytes().decode()
    half = text.index("#40=")
    two = (
        text[:half]
        + "ENDSEC;\nANCHOR;\n<a>=#1;\nENDSEC;\nDATA('second',('AUTOMOTIVE_DESIGN'));\n"
        + text[half:]
    )
    p = part21.open(two.encode(), limits=Limits())
    assert p.sections == 2 and len(p) == len(f.lines)


def test_strings_wrapped_across_lines_read_whole():
    text = W.box_file().replace(b"'A. Tester'", b"'A. Te\r\nster'")
    assert part21.read_header(text, Limits()).author == ("A. Tester",)


# --------------------------------------------------------------------------- the builder
def test_the_builder_writes_a_valid_transmit_that_round_trips():
    f, ids = W.part_file(lambda f: [W.cylinder_brep(f)])
    with _read(f.bytes()) as doc:
        (body,) = doc.bodies()
    xt = body.transmit
    assert xt_validate(xt)["ok"] and body.body_type == "solid"
    direct = tessellate_transmit(xt).measures()["volume"]
    for fmt in ("text",):
        again = read_file((text_header(xt, fmt=fmt, key="k", file="f") + write_text(xt)).encode())
        assert tessellate_transmit(again).measures()["volume"] == pytest.approx(direct, rel=1e-12)


def test_the_builder_refuses_what_it_cannot_use():
    b = BrepBuilder()
    b.body("solid")
    with pytest.raises(GeometryRefused):
        b.plane((0, 0, 0), (0, 0, 0))
    with pytest.raises(GeometryRefused) as exc:
        b.vertex((math.nan, 0, 0))
    assert exc.value.reason == "non_finite"
    with pytest.raises(GeometryRefused):
        b.cylinder((0, 0, 0), (0, 0, 1), -1.0)
    with pytest.raises(GeometryRefused):
        b.bspline_curve(2, [(0, 0, 0), (1, 0, 0), (2, 0, 0)], [0.0, 1.0], [3, 2])
    with pytest.raises(ValueError):
        b.body("solid")
    small = BrepBuilder(limits=Limits(brep_nodes=3))
    small.body("solid")
    with pytest.raises(SldLimitError) as exc:
        for _ in range(5):
            small.vertex((0, 0, 0))
    assert exc.value.detail["limit"] == "brep_nodes"


@pytest.mark.parametrize("shape", ["cylinder", "sphere", "torus_band"])
def test_a_builder_solid_tessellates_as_the_same_shape_written_by_hand(shape):
    """The same B-rep, made by the tessellator's own test builder and read from STEP,
    gives the same volume (or, for a sheet, area)."""
    if shape == "cylinder":
        direct = tessellate_transmit(xt_bodies.cylinder(0.005, 0.02)).measures()["volume"]
        data = _part(lambda f: [W.cylinder_brep(f, split=False)])
        key = "volume_m3"
    elif shape == "sphere":
        direct = tessellate_transmit(xt_bodies.hemisphere(0.01)).measures()["volume"]
        data = _part(lambda f: [W.hemisphere_brep(f)])
        key = "volume_m3"
    else:
        direct = tessellate_transmit(xt_bodies.torus_band(0.01, 0.003, -math.pi / 2, math.pi / 2)).measures()[
            "area"
        ]
        data = _part(
            lambda f: [f.add(f"SHELL_BASED_SURFACE_MODEL('',(#{W.torus_band_shell(f)}))")],
            kind="MANIFOLD_SURFACE_SHAPE_REPRESENTATION",
        )
        key = "area_m2"
    with _read(data) as doc:
        s = doc.scene()
        got = sum(s.objects[it.object].measures()[key] for it in s.items)
    assert got == pytest.approx(direct, rel=2e-3)


# --------------------------------------------------------------------------- the fixture
def test_the_solidworks_step_fixture_reads_to_its_box():
    truth = GROUND_TRUTH["o02_boxA.SLDPRT"]["api"]["configurations"]["Default"]
    with open_model(FIXTURE) as doc:
        assert (doc.format, doc.variant, doc.doc_type, doc.kind) == ("step", "AP203", "part", "brep")
        assert doc.units == {"length": "mm", "scale_m": 0.001, "source": "file"}
        assert doc.application == {"name": "SolidWorks 2024", "version": None}
        assert doc.fields.last_saved_utc is not None and doc.fields.last_saved_utc.year == 2026
        head = doc.counts()
        assert (head["bodies"], head["faces"], head["components"]) == (1, 6, 0)
        tree = doc.tree()
        assert [(n.kind, n.object) for n in tree.nodes] == [("object", None), ("body", 0)]
        assert tree.nodes[0].name == "o02_boxA" and doc.fields.title == "o02_boxA"
        s = doc.scene()
        (obj,) = s.objects
        m = obj.measures()
        assert m["volume_m3"] == pytest.approx(truth["volume_m3"], rel=1e-9)
        assert m["area_m2"] == pytest.approx(truth["surface_area_m2"], rel=1e-9)
        lo, hi = m["box"]
        assert list(lo) + list(hi) == pytest.approx(truth["bounding_box_m"], abs=1e-12)
        assert obj.source == "bodies" and _closed(obj)
        assert s.counts["faces"] == s.counts["faces_done"] == 6 and s.counts["bodies"] == 1
        assert doc.warnings == []
        summary = doc.summary(include=model.MODEL_SUMMARY_PARTS)
    env = model.envelope("model_summary", summary, source={"file": str(FIXTURE)})
    assert validate(env, model.envelope_schema("model_summary"), strict=True) == []


def test_the_fixture_exports_and_round_trips_through_stl(tmp_path):
    with open_model(FIXTURE) as doc:
        pm = export.print_model(doc)
    assert pm.closed and pm.source_format == "step" and pm.objects[0].source == "bodies"
    assert pm.measures()["volume_m3"] == pytest.approx(6.0e-6, rel=1e-9)
    out = tmp_path / "box.stl"
    export.write_export(pm, out, "stl")
    with open_model(out) as again:
        assert _volume(again.scene()) == pytest.approx(6.0e-6, rel=1e-6)


# --------------------------------------------------------------------------- B-rep forms
def _offset_of_turned_trim(f):
    """A box's top: the offset by 10 mm of a plane at z = 40 whose rectangular trim turns
    its u round, so the offset's normal is -z and the face's same_sense false."""
    plane = f.plane((0, 0, 40), (0, 0, 1), (1, 0, 0))
    trim = f.add(f"RECTANGULAR_TRIMMED_SURFACE('',#{plane},0.,10.,0.,20.,.F.,.T.)")
    return f.add(f"OFFSET_SURFACE('',#{trim},10.,.F.)"), False


def _offset_of_revolution(f):
    """A cylinder's side: 2 mm out from a revolved degree-1 B-spline of radius 3 mm."""
    line = f.bspline_curve(1, [(3, 0, -5), (3, 0, 25)], [2, 2], [0.0, 1.0])
    spun = f.add(f"SURFACE_OF_REVOLUTION('',#{line},#{f.axis1((0, 0, 0), (0, 0, 1))})")
    return f.add(f"OFFSET_SURFACE('',#{spun},2.,.F.)"), True


def _revolved_line(f):
    """A cylinder's side revolved from an unbounded LINE."""
    return f.add(
        f"SURFACE_OF_REVOLUTION('',#{f.line((5, 0, 0), (0, 0, 1))},#{f.axis1((0, 0, 0), (0, 0, 1))})"
    ), True


SHAPES = {
    "box": (lambda f: [W.box_brep(f)], 6000.0, 1e-9),
    "box of B-spline edges": (lambda f: [W.box_brep(f, edges="bspline")], 6000.0, 1e-9),
    "box of polyline edges": (lambda f: [W.box_brep(f, edges="polyline")], 6000.0, 1e-9),
    "box of trimmed edges": (lambda f: [W.box_brep(f, edges="trimmed")], 6000.0, 1e-9),
    "box of surface curves": (lambda f: [W.box_brep(f, edges="surface_curve")], 6000.0, 1e-9),
    "box with pcurve edges": (lambda f: [W.box_brep(f, edges="pcurve")], 6000.0, 1e-9),
    "box with a B-spline face": (lambda f: [W.bspline_box_brep(f)], 6000.0, 1e-9),
    "box of composite edges": (lambda f: [W.box_brep(f, edges="composite")], 6000.0, 1e-9),
    "cylinder of composite rims": (lambda f: [W.composite_cylinder_brep(f)], math.pi * 25 * 20, 1e-2),
    "split cylinder": (lambda f: [W.cylinder_brep(f)], math.pi * 25 * 20, 1e-2),
    "cylinder with a seam": (lambda f: [W.cylinder_brep(f, split=False)], math.pi * 25 * 20, 1e-2),
    "rational B-spline cylinder": (lambda f: [W.nurbs_cylinder_brep(f)], math.pi * 25 * 20, 1e-2),
    "revolved cylinder": (lambda f: [W.revolved_brep(f)], math.pi * 25 * 20, 1e-2),
    "cone with an apex": (lambda f: [W.cone_brep(f)], math.pi * 25 * 10 / 3, 1e-2),
    "hemisphere": (lambda f: [W.hemisphere_brep(f)], 2 / 3 * math.pi * 1000, 1e-2),
    "elliptic prism": (lambda f: [W.elliptic_prism_brep(f)], math.pi * 8 * 4 * 10, 1e-2),
    "box with a void": (lambda f: [W.void_box_brep(f)], 27000.0 - 1000.0, 1e-9),
    "half cylinder extruded from a trimmed circle": (
        lambda f: [W.half_cylinder_brep(f)],
        math.pi * 25 * 10 / 2,
        1e-2,
    ),
    "half cylinder extruded from a circle trimmed against it": (
        lambda f: [W.half_cylinder_brep(f, sense=False)],
        math.pi * 25 * 10 / 2,
        1e-2,
    ),
    "cylinder revolved from a line trimmed against it": (
        lambda f: [W.revolved_brep(f, sense=False)],
        math.pi * 25 * 20,
        1e-2,
    ),
    "cylinder revolved from an unbounded line": (
        lambda f: [W.cylinder_brep(f, side=_revolved_line)],
        math.pi * 25 * 20,
        1e-2,
    ),
    "cylinder offset from a revolved B-spline": (
        lambda f: [W.cylinder_brep(f, side=_offset_of_revolution)],
        math.pi * 25 * 20,
        1e-2,
    ),
    "box topped by the offset of a turned trim": (
        lambda f: [W.box_brep(f, top=_offset_of_turned_trim)],
        6000.0,
        1e-9,
    ),
    "sphere bounded by its seam": (lambda f: [W.sphere_seam_brep(f)], 4 / 3 * math.pi * 1000, 1e-2),
    "ogive revolved from a circle that crosses its axis": (
        lambda f: [W.ogive_brep(f)],
        W.ogive_volume(),
        3e-2,
    ),
    "plate with a hole": (lambda f: [W.holed_plate_brep(f)], 4000.0 - math.pi * 250, 1e-2),
}


@pytest.mark.parametrize("label", list(SHAPES))
def test_every_brep_form_reads_closed_to_its_volume(label):
    items, volume_mm3, rel = SHAPES[label]
    with _read(_part(items)) as doc:
        s = doc.scene()
        assert s.skipped == () and doc.kind == "brep"
        assert all(_closed(o) for o in s.objects)
        assert _volume(s) == pytest.approx(volume_mm3 * 1e-9, rel=rel)
        assert s.counts["faces"] == s.counts["faces_done"]


def test_holes_stored_inside_out_are_turned_to_agree_with_the_plate():
    """A plate whose hole bounds run the same way as its outer bounds, lined by a
    cylinder whose same_sense agrees with them: the tessellator takes the holes where
    they lie, so the wall is turned round to agree with the plate and the solid closes
    (warning ``faces_reoriented``). The B-rep body keeps the file's orientation."""
    with _read(_part(lambda f: [W.holed_plate_brep(f, holes_reversed=True)])) as doc:
        s = doc.scene()
        assert s.skipped == () and all(_closed(o) for o in s.objects)
        assert _volume(s) == pytest.approx((4000.0 - math.pi * 250) * 1e-9, rel=1e-2)
        (w,) = [w for w in s.warnings if w.code == "faces_reoriented"]
        assert w.startswith("1 faces of 1 solids")
    with _read(_part(lambda f: [W.holed_plate_brep(f)])) as doc:
        assert "faces_reoriented" not in _codes(doc.scene().warnings)


def _pieces(obj) -> list[float]:
    """The signed volumes (mm^3) of an object's closed pieces, largest first by size."""
    from solidseas.tessellate import checks

    pos, tris = export.weld(obj)
    found = checks.shells(checks.Flat(pos), tris, checks.pieces(tris, len(pos) // 3))
    return sorted((s.volume * 1e9 for s in found if s.closed), key=abs, reverse=True)


@pytest.mark.parametrize(("convention", "turned"), [("iso", False), ("inward", True), ("inward_true", False)])
def test_void_shells_face_into_their_voids_whichever_way_the_writer_stored_them(convention, turned):
    """A void is an ORIENTED_CLOSED_SHELL marked ``.F.``. Read by the letter of ISO 10303-42
    that turns the shell's faces round, right for a writer whose shell faces out of the void
    as a solid's would, wrong for one whose shell already faces into it: that void came out
    inside out and its volume was added (28,000 mm^3, not 26,000). Each closed shell is now
    turned by its signed volume, the outside positive and each void negative (warning
    ``void_reoriented``), and a shell that faced the right way is left alone."""
    with _read(_part(lambda f: [W.void_box_brep(f, convention=convention)])) as doc:
        s = doc.scene()
        assert s.skipped == () and all(_closed(o) for o in s.objects)
        assert _volume(s) == pytest.approx(26000e-9, rel=1e-12)
        (obj,) = s.objects
        assert _pieces(obj) == pytest.approx([27000.0, -1000.0], rel=1e-12)
        codes = _codes(s.warnings)
        assert ("void_reoriented" in codes) is turned
        assert not codes & {"shells_inside_out", "solids_not_closed", "solid_reoriented"}
        if turned:
            (w,) = [w for w in s.warnings if w.code == "void_reoriented"]
            assert w.startswith("1 void shells of 1 solids")
        pm = export.print_model(doc)
    assert pm.closed and pm.measures()["volume_m3"] == pytest.approx(26000e-9, rel=1e-12)
    assert not _codes(pm.warnings) & {"shell_reoriented", "shells_inside_out", "not_closed"}


@pytest.mark.parametrize("planes_inward", [False, True])
def test_faces_whose_loops_all_run_against_them_keep_their_sense(planes_inward):
    """Every face of the box has same_sense false while its loop runs as if it were true:
    no loop ran the way of its face, and each was dropped (``seam_configuration``), so the
    file drew nothing. Each face now keeps the sense the file gives it and its loop is
    read the other way round (warning ``loops_reversed``), as other readers take it. With
    the planes facing out, same_sense false faces every face in, and the closed solid is
    turned round as a whole (``solid_reoriented``); with the planes facing in, the faces
    face out as they are."""
    with _read(_part(lambda f: [W.against_box_brep(f, planes_inward=planes_inward)])) as doc:
        s = doc.scene()
        assert s.skipped == () and s.counts["faces_done"] == 6
        assert all(_closed(o) for o in s.objects)
        assert _volume(s) == pytest.approx(6000e-9, rel=1e-12)
        (w,) = [w for w in s.warnings if w.code == "loops_reversed"]
        assert w.startswith("6 faces whose loops all ran against them")
        assert ("solid_reoriented" in _codes(s.warnings)) is not planes_inward
        assert "solids_not_closed" not in _codes(s.warnings)


@pytest.mark.parametrize(("size", "thin"), [((10.0, 20.0, 30.0), 0), ((10.0, 20.0, 0.005), 4)])
def test_faces_that_share_no_edge_and_whose_loops_run_against_them_face_out(size, thin):
    """A box whose six faces share no vertex and no edge (as some writers store a part),
    each face facing out by its sense and its loop running against it. Turned round to
    follow their loops, every face faced in, and with no edge between them no check could
    turn them back: the scene's volume came out -6,000 mm^3, every normal inward. Each
    face now keeps its sense, as other readers take it, and faces out; the print model,
    welded by position, is a closed box that needs no turning. A face thinner than the
    chord tolerance follows its loop, whichever way it runs (its sides may cross): on a
    box 5 um high its four sides did, facing in, and they are found facing against the
    rest by where their points lie and turned (``faces_reoriented``)."""
    want = size[0] * size[1] * size[2] * 1e-9
    with _read(_part(lambda f: [W.free_face_box_brep(f, size)])) as doc:
        s = doc.scene()
        assert s.skipped == () and s.counts["faces_done"] == 6
        assert _volume(s) == pytest.approx(want, rel=1e-9)
        codes = _codes(s.warnings)
        assert {"loops_reversed", "solids_not_closed"} <= codes
        assert "solid_reoriented" not in codes
        assert [w for w in s.warnings if w.code == "faces_reoriented"] == (
            [f"{thin} faces of 1 solids ran against their neighbours and were turned round"] if thin else []
        )
        pm = export.print_model(doc)
    assert pm.closed and pm.measures()["volume_m3"] == pytest.approx(want, rel=1e-9)
    codes = _codes(pm.warnings) | {w.code for o in pm.objects for w in o.warnings}
    assert not codes & {"shell_reoriented", "shells_inside_out", "not_closed"}


def test_a_seam_run_down_to_a_pole_and_back_folds_no_triangles():
    """A sphere's face bounded by its rim and by its seam run down to the pole and straight
    back up: in (u, v) the seam was a side of no width inside the cap, and the
    triangulation fanned its samples across it, triangles with no (u, v) area but area in
    space, each twice (the mesh not closed, 1,278 mm^2 against 1,178). The out-and-back
    pair is now taken out of the loop; the cap is cut to the pole as a rim alone is."""
    cap = math.pi * 15**2 * (30 - 15) / 3  # the sphere below z = 5, radius 10
    area = 2 * math.pi * 10 * 15 + math.pi * 75
    with _read(_part(lambda f: [W.sphere_seam_cap_brep(f)])) as doc:
        s = doc.scene(chord_m=2e-5)
        assert s.skipped == () and all(_closed(o) for o in s.objects)
        # within the chord tolerance's own shortfall (a mesh inside its sphere), never over
        assert _volume(s) == pytest.approx(cap * 1e-9, rel=5e-3)
        got = sum(s.objects[it.object].measures()["area_m2"] for it in s.items)
        assert area * 1e-6 * (1 - 5e-3) < got <= area * 1e-6
        assert not _codes(s.warnings) & {"faces_folded", "solids_not_closed"}


def test_a_plane_face_with_no_bound_is_left_out_without_naming_a_seam():
    """A face with no loop on a surface that does not close has nothing to bound it: it is
    left out as ``no_boundary``, not ``seam_configuration``, which says nothing of a plane."""
    f, _ids = W.part_file(lambda f: [W.box_brep(f)])
    text, n = re.subn(rb"ADVANCED_FACE\('',\(#\d+\)", b"ADVANCED_FACE('',()", f.bytes(), count=1)
    assert n == 1
    with _read(text) as doc:
        s = doc.scene()
        (skip,) = s.skipped
        assert (skip.reason, skip.surface) == ("no_boundary", "PLANE")
        assert s.counts["faces_done"] == 5


@pytest.mark.parametrize("surface", ["bspline", "plane"])
def test_an_edge_that_stops_dead_at_its_corners_is_sampled_once_there(surface):
    """A closed cubic B-spline edge whose curve stops and turns at four corners (each
    control point there three times over): its turn there stays whatever the length, and
    the sampler halved its segments to the depth bound, piling up samples a billionth of a
    millimetre apart, past ``max_edge_points`` (``edge_too_long``) or onto one (u, v) point
    that folded the face. A point a halving puts within a micrometre, or a hundredth of
    the chord tolerance, of its neighbours is now left out, and segments that short are
    not halved for their turn alone."""
    data = _part(lambda f: [W.cornered_square_sheet(f, surface=surface)], kind=SURFACE_MODEL)
    with _read(data) as doc:
        s = doc.scene()
        assert s.skipped == () and s.counts["faces_done"] == 1
        (obj,) = s.objects
        assert obj.measures()["area_m2"] == pytest.approx(100e-6, rel=1e-9)
        assert obj.n_vertices < 400
        assert "faces_folded" not in _codes(s.warnings)


def test_a_torus_through_its_own_axis_is_triangulated_to_its_area():
    """A torus whose major radius is under its minor one runs through its axis; on its part
    inside, ``R + r cos v`` is below nought. The triangulation scaled u by that sum's
    largest value, clamped to a thousandth of r there, so its triangles ran the whole way
    round in space and the patch came out 24 % too big. It is now scaled by the largest
    ``|R + r cos v|``."""
    R, r, u1, v0, v1 = 5.0, 10.0, 1.5, 2.5, 3.8
    n = 20000
    dv = (v1 - v0) / n
    want = u1 * r * sum(abs(R + r * math.cos(v0 + (k + 0.5) * dv)) for k in range(n)) * dv
    data = _part(lambda f: [W.crossed_torus_patch_sheet(f, R, r, u1, v0, v1)], kind=SURFACE_MODEL)
    with _read(data) as doc:
        s = doc.scene(chord_m=1e-5)
        assert s.skipped == ()
        (obj,) = s.objects
        assert obj.measures()["area_m2"] == pytest.approx(want * 1e-6, rel=5e-3)


@pytest.mark.parametrize("chord", [1e-4, 5e-5])
def test_a_face_whose_edges_run_past_its_surface_is_not_folded(chord):
    """A bent strip whose face runs 0.3 mm on past its B-spline surface's end: the
    boundary points out there all fell on the surface's own corner and edge in (u, v),
    some on one point, and the triangles touching them could never come within the chord
    tolerance, so each was split again until the face folded (21.2 mm^2, then 22.1 at a
    finer chord, against 20.73). Those points are now carried past the surface's edge by
    one unclamped step, and the triangles at them judged where they fall on the surface."""
    want = 10.3 * 2.0 + 0.3 * 1.3 / 3
    with _read(_part(lambda f: [W.overrun_strip_sheet(f)], kind=SURFACE_MODEL)) as doc:
        s = doc.scene(chord_m=chord)
        assert s.skipped == ()
        (obj,) = s.objects
        assert obj.measures()["area_m2"] == pytest.approx(want * 1e-6, rel=2e-3)
        assert not _codes(s.warnings) & {"faces_folded", "faces_coarse"}


def test_a_solid_with_a_face_left_out_is_said_to_be_open():
    """A solid whose mesh is not closed said nothing in the scene; it now warns
    ``solids_not_closed``."""
    f, _ids = W.part_file(lambda f: [W.box_brep(f)])
    text = f.bytes().replace(b"PLANE('',", b"HYPERBOLIC_THING('',", 1)
    with _read(text) as doc:
        (w,) = [w for w in doc.scene().warnings if w.code == "solids_not_closed"]
        assert w.startswith("1 solids are not closed")
    with _read(W.box_file()) as doc:
        assert doc.scene().warnings == ()


ROCKET = Path(__file__).parent / "generated" / "rocket.step"
# OCCT 7.9.3's measures of rocket.step (adaptive area at 1e-9, volume), mm^2 and mm^3
ROCKET_AREA, ROCKET_VOLUME = 8830.34, 30819.80


def test_a_rocket_made_with_cadquery_draws_every_face():
    """CadQuery's rocket (tests/generated/make_rocket.py) drew with holes: its
    nose, a SURFACE_OF_REVOLUTION of a whole circle crossing its axis at the tip, had no
    pole there and was left out (``seam_configuration``); its fins and skirt, trimmed by
    HYPERBOLA edges where the fins meet the cone, were left out as ``unsupported_curve``;
    and its filleted base, a torus band whose one loop OCCT writes running against the
    face, was taken for holes all round a whole torus. Every face is drawn now, closed, to
    OCCT's area and volume."""
    with _read(ROCKET.read_bytes(), name="rocket.step") as doc:
        s = doc.scene(chord_m=1e-5)
        assert s.skipped == () and s.counts["faces"] == s.counts["faces_done"] == 20
        (obj,) = s.objects
        assert _closed(obj)
        m = obj.measures()
        assert m["area_m2"] == pytest.approx(ROCKET_AREA * 1e-6, rel=1e-3)
        assert m["volume_m3"] == pytest.approx(ROCKET_VOLUME * 1e-9, rel=2e-3)
        assert not _codes(s.warnings) & {"solids_not_closed", "faces_left_out", "faces_folded"}
        (body,) = doc.bodies()
        t = tessellate_transmit(body.transmit, chord_m=1e-4)
        assert len(t.mesh.faces) == 20 and all(face.n_triangles for face in t.mesh.faces)


@pytest.mark.parametrize("chord", [1e-4, 1e-5])
def test_an_ogive_nose_is_drawn_to_its_volume_and_area(chord):
    """A nose of revolved arc: OCCT writes the arc's whole circle as the profile, so the
    spun surface is periodic in both directions, and the tip, where the circle crosses the
    axis, was no pole of it; the face's one loop wraps round the base and had nowhere to
    close. The crossings of a closed profile are its poles now."""
    rb, h = 10.0, 30.0
    R = (rb * rb + h * h) / (2.0 * rb)
    n = 20000
    dz = h / n
    side = 0.0
    for k in range(n):
        z = (k + 0.5) * dz
        q = math.sqrt(R * R - z * z)
        side += 2 * math.pi * (rb - R + q) * math.hypot(1.0, z / q) * dz
    with _read(_part(lambda f: [W.ogive_brep(f)])) as doc:
        s = doc.scene(chord_m=chord)
        assert s.skipped == ()
        (obj,) = s.objects
        assert _closed(obj)
        rel = 2e-2 if chord > 5e-5 else 2e-3
        assert obj.measures()["volume_m3"] == pytest.approx(W.ogive_volume(rb, h) * 1e-9, rel=rel)
        assert obj.measures()["area_m2"] == pytest.approx((side + math.pi * rb * rb) * 1e-6, rel=rel)


@pytest.mark.parametrize("composite", [False, True], ids=["edges", "composite"])
@pytest.mark.parametrize("kind", ["hyperbola", "parabola"])
def test_faces_bounded_by_hyperbolas_and_parabolas_are_drawn(kind, composite):
    """A HYPERBOLA or a PARABOLA, where a plane meets a cone, left its faces out as
    ``unsupported_curve``. An edge on one is now the exact rational quadratic B-spline of
    its arc between its vertices, and a trimmed one in a composite curve is sampled."""
    data = _part(lambda f: [W.open_conic_plate_sheet(f, kind, composite=composite)], kind=SURFACE_MODEL)
    with _read(data) as doc:
        s = doc.scene(chord_m=1e-5)
        assert s.skipped == ()
        (obj,) = s.objects
        assert obj.measures()["area_m2"] == pytest.approx(W.open_conic_plate_area(kind) * 1e-6, rel=2e-3)


@pytest.mark.parametrize("against", [False, True])
def test_a_torus_band_bounded_by_its_seam_is_drawn_whichever_way_its_loop_runs(against):
    """A torus band whose one loop runs round both rims and along its seam: stored running
    against the face (OCCT's fillets), it was read as holes in a whole torus and, the holes
    reaching all the way round, left out. It is read with its loop reversed now."""
    R, r = 10.0, 3.0
    data = _part(lambda f: [W.torus_seam_band_shell(f, R, r, against=against)], kind=SURFACE_MODEL)
    with _read(data) as doc:
        s = doc.scene(chord_m=1e-5)
        assert s.skipped == ()
        (obj,) = s.objects
        want = 2 * math.pi * r * (math.pi * R + 2 * r)
        assert obj.measures()["area_m2"] == pytest.approx(want * 1e-6, rel=1e-3)
        assert ("loops_reversed" in _codes(s.warnings)) == against


def test_a_periodic_bspline_surface_and_closed_bspline_edges():
    """A periodic B-spline (uniform knots, its rows not repeated) closes on itself, and a
    closed edge of one vertex on a closed B-spline curve goes all the way round."""
    from solidseas.tessellate import nurbs

    ring, knots = W.periodic_ring()
    U = nurbs.knot_vector(knots, [1] * len(knots), len(ring), 3)
    curve = nurbs.BSplineCurve(3, ring, U, False, True)
    pts = [curve.point(curve.lo + (curve.hi - curve.lo) * k / 4000) for k in range(4000)]
    area = 0.5 * abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1], strict=True)))
    with _read(_part(lambda f: [W.periodic_hoop_brep(f)])) as doc:
        s = doc.scene()
        assert s.skipped == () and all(_closed(o) for o in s.objects)
        assert _volume(s) == pytest.approx(area * 10 * 1e-9, rel=1e-2)


def test_a_surface_model_is_a_sheet():
    data = _part(
        lambda f: [f.add(f"SHELL_BASED_SURFACE_MODEL('band',(#{W.torus_band_shell(f)}))")],
        kind="MANIFOLD_SURFACE_SHAPE_REPRESENTATION",
    )
    with _read(data) as doc:
        (body,) = doc.bodies()
        assert body.body_type == "sheet"
        s = doc.scene()
        area = s.objects[0].measures()["area_m2"]
        assert area == pytest.approx(2 * math.pi * 3 * (10 * math.pi + 6) * 1e-6, rel=1e-2)
        only_solids = doc.scene(body_types=("solid",))
        assert only_solids.items == () and "bodies_left_out" in _codes(only_solids.warnings)
        with pytest.raises(NothingToExportError) as exc:  # drawn in 3D, but nothing to print
            export.print_model(doc)
        assert exc.value.detail == {"rule": "no_solid"} and "only open surfaces" in str(exc.value)


def test_inch_and_degree_units():
    data = _part(lambda f: [W.cone_brep(f, angle_unit=math.pi / 180)], length="in", angle="deg")
    with _read(data) as doc:
        assert doc.units == {"length": "in", "scale_m": 0.0254, "source": "file"}
        v = _volume(doc.scene())
    assert v == pytest.approx(math.pi * 25 * 10 / 3 * 0.0254**3, rel=1e-2)


def test_a_file_without_units_assumes_millimetres():
    f = W.P21()
    ctx = f.add("(GEOMETRIC_REPRESENTATION_CONTEXT(3)REPRESENTATION_CONTEXT('',''))")
    box = W.box_brep(f)
    pd = f.product("p")
    f.shape(pd, [box], ctx)
    with _read(f.bytes()) as doc:
        assert doc.units["source"] == "assumed" and "units_assumed" in _codes(doc.warnings)
        assert _volume(doc.scene()) == pytest.approx(6e-6, rel=1e-9)


def test_a_file_without_product_structure_still_reads():
    f = W.P21()
    ctx = f.units()
    box = W.box_brep(f)
    f.add(f"ADVANCED_BREP_SHAPE_REPRESENTATION('',(#{box}),#{ctx})")
    with _read(f.bytes()) as doc:
        assert _volume(doc.scene()) == pytest.approx(6e-6, rel=1e-9)
        assert doc.doc_type == "part"


def test_a_file_with_no_geometry_reads_with_no_bodies():
    f = W.P21()
    f.units()
    f.product("empty")
    with _read(f.bytes()) as doc:
        assert doc.scene().objects == () and doc.bodies() == []
        assert [n.kind for n in doc.tree().nodes] == ["object"]


def test_a_face_that_cannot_be_read_is_left_out_with_a_reason():
    f, _ids = W.part_file(lambda f: [W.box_brep(f)])
    text = f.bytes().replace(b"PLANE('',", b"HYPERBOLIC_THING('',", 1)
    with _read(text) as doc:
        s = doc.scene()
        assert s.counts["faces"] == 6 and s.counts["faces_done"] == 5
        (skip,) = s.skipped
        assert (skip.reason, skip.surface) == ("unsupported_surface", "HYPERBOLIC_THING")
        pm = export.print_model(doc)
    assert not pm.closed and "faces_left_out" in _codes(pm.warnings)


# --------------------------------------------------------------------------- meshes
def test_faceted_and_tessellated_geometry_are_meshes():
    for items, kind, volume in (
        (lambda f: [W.faceted_box(f)], "FACETED_BREP_SHAPE_REPRESENTATION", 6000.0),
        (lambda f: [W.faceted_box(f, concave=True)], "FACETED_BREP_SHAPE_REPRESENTATION", 3000.0),
        (lambda f: [W.tessellated_box(f)], "TESSELLATED_SHAPE_REPRESENTATION", 6000.0),
        (lambda f: [W.tessellated_box(f, complex_form=True)], "TESSELLATED_SHAPE_REPRESENTATION", 6000.0),
    ):
        with _read(_part(items, kind=kind)) as doc:
            assert doc.kind == "mesh"
            s = doc.scene()
            (obj,) = s.objects
            assert obj.source == "mesh" and _closed(obj)
            assert _volume(s) == pytest.approx(volume * 1e-9, rel=1e-9)
            assert doc.bodies() == []


def test_a_file_of_both_is_mixed():
    data = _part(lambda f: [W.box_brep(f), W.faceted_box(f, (5, 5, 5))], kind="SHAPE_REPRESENTATION")
    with _read(data) as doc:
        assert doc.kind == "mixed"
        s = doc.scene()
        assert sorted(o.source for o in s.objects) == ["bodies", "mesh"]
        assert _volume(s) == pytest.approx((6000 + 125) * 1e-9, rel=1e-9)


# --------------------------------------------------------------------------- assemblies
def _placed(doc):
    s = doc.scene()
    out = []
    for it in s.items:
        lo, _hi = s.objects[it.object].measures()["box"]
        out.append((tuple(round(c * 1000, 6) for c in it.placement.translation_m), it.placement.rotation))
    return s, sorted(out)


@pytest.mark.parametrize("order", ["child_first", "parent_first"])
def test_an_assembly_places_its_parts_whichever_order_its_relationships_take(order):
    with _read(W.assembly_file(order=order)) as doc:
        assert doc.doc_type == "assembly"
        s, placed = _placed(doc)
        assert len(s.objects) == 1 and len(s.items) == 2
        assert placed[0][0] == (0.0, 0.0, 0.0)
        assert placed[1][0] == (50.0, 0.0, 0.0)
        rot = placed[1][1]
        assert [list(r) for r in rot] == [
            pytest.approx([0, -1, 0]),
            pytest.approx([1, 0, 0]),
            pytest.approx([0, 0, 1]),
        ]
        assert _volume(s) == pytest.approx(12000e-9, rel=1e-9)
        tree = doc.tree()
        kinds = [n.kind for n in tree.nodes]
        assert kinds == ["assembly", "component", "body", "component", "body"]
        names = [n.name for n in tree.nodes if n.kind == "component"]
        assert names == ["box 1", "box 2"]
        assert s.counts["components"] == 2 and doc.counts()["components"] == 2


def test_a_nested_assembly_composes_its_placements():
    with _read(W.assembly_file(nested=True)) as doc:
        s, placed = _placed(doc)
        assert [p[0] for p in placed] == [(0.0, 0.0, 0.0), (50.0, 100.0, 0.0)]
        kinds = [n.kind for n in doc.tree().nodes]
        assert kinds == ["assembly", "component", "body", "component", "component", "body"]


def test_an_assembly_of_mapped_items():
    with _read(W.assembly_file(mapped=True)) as doc:
        assert doc.doc_type == "assembly"
        _s, placed = _placed(doc)
        assert [p[0] for p in placed] == [(0.0, 0.0, 0.0), (50.0, 0.0, 0.0)]


def test_a_component_with_no_name_of_its_own_takes_its_product_name():
    """Writers often leave an occurrence's name blank and number its id ('NAUO1'): the
    component is then named by the child product."""
    f = W.P21()
    ctx = f.units()
    box = W.box_brep(f)
    part = f.product("box part")
    top = f.product("top")
    rp, _ = f.shape(part, [box], ctx)
    rt, _ = f.shape(top, [], ctx)
    for k, at in enumerate(((0, 0, 0), (50, 0, 0)), 1):
        nauo = f.occurrence(top, part, rt, rp, at=at)
        f.lines = [(i, t.replace("('NAUO','',", f"('NAUO{k}',' ',") if i == nauo else t) for i, t in f.lines]
    with _read(f.bytes()) as doc:
        names = [n.name for n in doc.tree().nodes if n.kind == "component"]
        assert names == ["box part", "box part"]


def _mapped_assembly(form: str) -> bytes:
    """A box placed at the origin and 50 mm along x by MAPPED_ITEMs, each occurrence's
    context-dependent shape representation over a relationship with no transformation:
    the mapped items in the parent's shape (``parent``) or each in a representation of
    its own that is the relationship's rep_1 (``own``); or (``none``) no mapped items,
    the relationship alone placing the box at the parent's origin."""
    f = W.P21()
    ctx = f.units()
    box = W.box_brep(f)
    part = f.product("box part")
    rp, _ = f.shape(part, [box], ctx)
    top = f.product("top")
    pds = f.add(f"PRODUCT_DEFINITION_SHAPE('','',#{top})")
    places = [(0, 0, 0), (50, 0, 0)] if form != "none" else [(0, 0, 0)]
    rmap = f.add(f"REPRESENTATION_MAP(#{f.axis2()},#{rp})")
    items = [f.add(f"MAPPED_ITEM('m{k}',#{rmap},#{f.axis2(at)})") for k, at in enumerate(places)]
    held = [f"#{i}" for i in items] if form == "parent" else []
    rt = f.add(f"SHAPE_REPRESENTATION('',(#{f.axis2()}{''.join(',' + h for h in held)}),#{ctx})")
    f.add(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{rt})")
    for k, item in enumerate(items):
        nauo = f.add(f"NEXT_ASSEMBLY_USAGE_OCCURRENCE('{k}','box {k}','',#{top},#{part},$)")
        npds = f.add(f"PRODUCT_DEFINITION_SHAPE('','',#{nauo})")
        rep_1 = f.add(f"SHAPE_REPRESENTATION('',(#{item}),#{ctx})") if form == "own" else rp
        rr = f.add(f"SHAPE_REPRESENTATION_RELATIONSHIP('','',#{rep_1},#{rt})")
        f.add(f"CONTEXT_DEPENDENT_SHAPE_REPRESENTATION(#{rr},#{npds})")
    if form == "none":
        f.lines = [(i, t) for i, t in f.lines if not t.startswith(("MAPPED_ITEM", "REPRESENTATION_MAP"))]
    return f.bytes()


@pytest.mark.parametrize("form", ["parent", "own"])
def test_mapped_items_beside_a_relationship_without_a_transformation(form):
    with _read(_mapped_assembly(form)) as doc:
        s, placed = _placed(doc)
        assert [p[0] for p in placed] == [(0.0, 0.0, 0.0), (50.0, 0.0, 0.0)]
        assert _volume(s) == pytest.approx(12000e-9, rel=1e-9)
        assert not _codes(doc.warnings) & {"placement_unresolved", "placement_ambiguous"}


def test_a_relationship_without_a_transformation_places_at_the_parent_origin():
    with _read(_mapped_assembly("none")) as doc:
        _s, placed = _placed(doc)
        assert [p[0] for p in placed] == [(0.0, 0.0, 0.0)]
        assert "placement_unresolved" not in _codes(doc.warnings)


@pytest.mark.parametrize(("at", "items", "warned"), [((0, 0, 0), 1, False), ((80, 0, 0), 2, True)])
def test_a_mapped_item_beside_an_occurrence_placed_by_its_relationship(at, items, warned):
    """A mapped item that places the child where its occurrence's own relationship
    already does is the same occurrence; one elsewhere is kept as a further
    occurrence and warned."""
    f = W.P21()
    ctx = f.units()
    box = W.box_brep(f)
    part = f.product("box part")
    rp, _ = f.shape(part, [box], ctx)
    top = f.product("top")
    pds = f.add(f"PRODUCT_DEFINITION_SHAPE('','',#{top})")
    rmap = f.add(f"REPRESENTATION_MAP(#{f.axis2()},#{rp})")
    item = f.add(f"MAPPED_ITEM('m',#{rmap},#{f.axis2(at)})")
    rt = f.add(f"SHAPE_REPRESENTATION('',(#{f.axis2()},#{item}),#{ctx})")
    f.add(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{rt})")
    f.occurrence(top, part, rt, rp, at=(0, 0, 0), name="box")
    with _read(f.bytes()) as doc:
        s = doc.scene()
        assert len(s.items) == items
        assert ("placement_ambiguous" in _codes(doc.warnings)) is warned


def test_an_assembly_that_contains_itself_is_not_followed_twice():
    f = W.P21()
    ctx = f.units()
    box = W.box_brep(f)
    a = f.product("a")
    b = f.product("b")
    ra, _ = f.shape(a, [box], ctx)
    rb, _ = f.shape(b, [], ctx)
    f.occurrence(a, b, ra, rb, at=(10, 0, 0), name="b in a")
    f.occurrence(b, a, rb, ra, at=(20, 0, 0), name="a in b")
    with _read(f.bytes()) as doc:
        s = doc.scene()
        assert "assembly_cycle" in _codes(doc.warnings)
        assert len(s.items) >= 1


def test_an_occurrence_without_a_placement_is_placed_at_the_origin():
    f = W.P21()
    ctx = f.units()
    box = W.box_brep(f)
    part = f.product("part")
    top = f.product("top")
    f.shape(part, [box], ctx)
    f.shape(top, [], ctx)
    f.add(f"NEXT_ASSEMBLY_USAGE_OCCURRENCE('1','loose','',#{top},#{part},$)")
    with _read(f.bytes()) as doc:
        _s, placed = _placed(doc)
        assert placed == [((0.0, 0.0, 0.0), ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))]
        assert "placement_unresolved" in _codes(doc.warnings)


# --------------------------------------------------------------------------- colours and properties
def test_colours_of_bodies_faces_and_named_colours():
    f, ids = W.part_file(lambda f: [W.box_brep(f), W.box_brep(f, origin=(20, 0, 0))])
    first, second = ids["items"]
    f.colour(first, (1.0, 0.5, 0.0), transparency=0.25)
    f.named_colour(second, "blue")
    with _read(f.bytes()) as doc:
        objs = doc.scene().objects
        assert objs[0].color == pytest.approx((1.0, 0.5, 0.0, 0.75))
        assert objs[1].color == (0.0, 0.0, 1.0, 1.0)
        assert [n.color for n in doc.tree().nodes if n.kind == "body"][1] == (0.0, 0.0, 1.0, 1.0)


def test_face_colours_give_the_body_its_most_common_one():
    f = W.P21()
    ctx = f.units()
    box = W.box_brep(f)
    faces = [i for i, t in f.lines if t.startswith("ADVANCED_FACE")]
    for k, face in enumerate(faces):
        f.colour(face, (0.0, 1.0, 0.0) if k < 4 else (1.0, 0.0, 0.0))
    over = f.colour(box, (0.2, 0.2, 0.2))
    f.colour(box, (0.9, 0.9, 0.9), overriding=over)
    pd = f.product("p")
    f.shape(pd, [box], ctx)
    with _read(f.bytes()) as doc:
        assert doc.scene().objects[0].color == pytest.approx((0.9, 0.9, 0.9, 1.0))
    f2 = W.P21()
    ctx = f2.units()
    box = W.box_brep(f2)
    faces = [i for i, t in f2.lines if t.startswith("ADVANCED_FACE")]
    for k, face in enumerate(faces):
        f2.colour(face, (0.0, 1.0, 0.0) if k < 4 else (1.0, 0.0, 0.0))
    f2.shape(f2.product("p"), [box], ctx)
    with _read(f2.bytes()) as doc:
        assert doc.scene().objects[0].color == (0.0, 1.0, 0.0, 1.0)
        assert "colors_ignored" in _codes(doc.warnings)


def test_time_stamps_keep_their_zone_or_stay_as_stored():
    from solidseas.formats.step.properties import time_stamp

    assert time_stamp("2026-05-04T03:02:01").isoformat() == "2026-05-04T03:02:01"
    assert time_stamp("2026-01-01").isoformat() == "2026-01-01T00:00:00"
    assert time_stamp("2026-05-04T03:02:01Z").isoformat() == "2026-05-04T03:02:01+00:00"
    assert time_stamp("2026-05-04T03:02:01+02:00").isoformat() == "2026-05-04T01:02:01+00:00"
    assert time_stamp("not a time") is None


def test_header_fields_products_and_user_defined_properties():
    f, ids = W.part_file(lambda f: [W.box_brep(f)], name="bracket")
    f.user_property(ids["pd"], "Part Number", "BR-100")
    f.user_property(ids["pd"], "Revision", 3)
    with _read(f.bytes()) as doc:
        assert doc.fields.author == "A. Tester"
        # no zone in the time stamp: kept as stored, naive (local time where it was written)
        assert doc.fields.last_saved_utc.isoformat() == "2026-05-04T03:02:01"
        assert doc.application["name"] == "Synthetic Writer 1.0"
        doc.tree()
        props = {p.name: p.value for p in doc.properties}
        assert props["organization"] == "Test Shop" and props["schema"].startswith("AUTOMOTIVE_DESIGN")
        assert props["product_name"] == "bracket" and props["Part Number"] == "BR-100"
        assert props["Revision"] == 3.0
        assert doc.fields.title == "bracket"


def test_external_document_references_are_reported_not_opened():
    f, _ids = W.part_file(lambda f: [W.box_brep(f)])
    f.add("DOCUMENT_FILE('C:/elsewhere/part1.stp','','',#1,'','')")
    with _read(f.bytes()) as doc:
        (ref,) = doc.references()
        assert (ref.kind, ref.stored, ref.name, ref.resolution) == (
            "component",
            "C:/elsewhere/part1.stp",
            "part1.stp",
            None,
        )


# --------------------------------------------------------------------------- compressed
def test_a_zipped_step_file_reads_as_its_member():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("inner.stp", W.box_file())
    with _read(buf.getvalue(), name="packed.stp") as doc:
        assert doc.variant == "AP214" and {p.name: p.value for p in doc.properties}["container"] == "zip"
        assert _volume(doc.scene()) == pytest.approx(6e-6, rel=1e-9)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.stp", W.box_file())
        z.writestr("b.stp", W.box_file())
    with pytest.raises(FormatNotSupportedError) as exc:
        _read(buf.getvalue(), name="two.stp")
    assert exc.value.detail == {"rule": "archive", "value": "zip"}


# --------------------------------------------------------------------------- the surfaces
@pytest.fixture(scope="module")
def folder(tmp_path_factory):
    base = tmp_path_factory.mktemp("step") / "models"
    base.mkdir()
    (base / "box.step").write_bytes(W.box_file())
    (base / "assembly.stp").write_bytes(W.assembly_file())
    return base


def _run(capsys, *argv):
    code = cli.main([*argv, "--json"])
    out, err = capsys.readouterr()
    assert err == ""
    return code, json.loads(out)


def test_a_listing_reads_step_files(folder):
    data = scan(folder, formats="all").listing()
    got = {e["path"]: e for e in data["entries"]}
    box, asm = got["box.step"], got["assembly.stp"]
    assert box["status"] == "ok" and box["model"]["format"] == "step" and box["model"]["readable"]
    assert box["model"]["variant"] == "AP214" and box["model"]["kind"] == "brep"
    assert asm["model"]["counts"]["components"] == 2


def test_the_command_line_reads_and_exports_step_files(folder, capsys, tmp_path):
    code, env = _run(capsys, "info", str(folder / "assembly.stp"))
    assert code == 0 and env["kind"] == "model_summary"
    assert env["data"]["doc_type"] == "assembly" and env["data"]["format"] == "step"
    assert validate(env, model.envelope_schema("model_summary"), strict=True) == []
    code, env = _run(
        capsys, "export", str(folder / "assembly.stp"), "--format", "3mf", "-o", str(tmp_path / "a.3mf")
    )
    assert code == 0 and env["data"]["source_format"] == "step" and env["data"]["closed"]
    assert env["data"]["counts"]["items"] == 2
    code, env = _run(capsys, "preview", str(folder / "box.step"), "-o", str(tmp_path))
    assert code == 0 and env["data"]["source"] == "rendered"


def test_python_and_the_command_line_give_the_same_model_summary(folder, capsys):
    for name in ("box.step", "assembly.stp"):
        with open_model(folder / name) as doc:
            python = doc.summary(include=model.MODEL_SUMMARY_PARTS)
        _code, env = _run(capsys, "info", str(folder / name))
        assert env["data"] == python, name


def test_the_rest_service_reads_step_files(folder):
    from serve_support import Running

    running = Running({"models": folder}, workers=1, formats=("solidworks", "step"))
    try:
        r = running.get("document", root="models", path="assembly.stp")
        assert r.status == 200 and r.json()["kind"] == "model_summary"
        with open_model(folder / "assembly.stp") as doc:
            assert r.json()["data"] == doc.summary(include=model.MODEL_SUMMARY_PARTS)
        r = running.get("preview", root="models", path="box.step")
        assert r.status == 200 and r.body.startswith(b"\x89PNG")
    finally:
        running.close()


# --------------------------------------------------------------------------- the STEP writer as an oracle
@pytest.mark.parametrize(
    "name", ["o02_boxA", "o10_import_step_cut", "o11_curved", "o12_multibody", "o13_two_geometry_configs"]
)
def test_step_written_by_solidseas_reads_back_to_its_source_bodies(name):
    """The STEP the STEP export writes of each fixture reads back, at the same chord
    tolerance, to the volume and area of SolidSeas' tessellation of the part's own bodies
    (equal within 1e-6 when measured)."""
    step = pytest.importorskip("solidseas.step")
    from solidseas.formats.solidworks import open_document
    from solidseas.tessellate import tessellate_document

    with open_document(fixture_path(name + ".SLDPRT")) as doc:
        t = tessellate_document(doc)
        source = t.measures()
        data = step.step_bytes(step.step_model(doc))
    with _read(data) as again:
        s = again.scene(chord_m=t.chord_m)
        assert all(_closed(o) for o in s.objects)
        assert s.counts["faces_done"] == s.counts["faces"]
        got_v = _volume(s)
        got_a = sum(s.objects[it.object].measures()["area_m2"] for it in s.items)
    assert got_v == pytest.approx(source["volume"], rel=1e-5)
    assert got_a == pytest.approx(source["area"], rel=1e-5)
