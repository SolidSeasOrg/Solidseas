"""The 3MF reader (``docs/formats/mesh.md``): the fixture SOLIDWORKS wrote, packages
SolidSeas' own writer wrote of every fixture kind, and synthetic packages from
``tests/mesh_writers.py`` for the production and materials extensions, units,
metadata, thumbnails and refusals."""

import io
import json
import zipfile

import pytest

import mesh_writers as mw
from model_writers import IDENTITY, QUARTER_Z, Item, Scene, box, holed_block, two_object_assembly
from solidseas import export, jobs, model, open_document, scan
from solidseas.errors import FormatNotSupportedError, NothingToExportError, SldFormatError, SldLimitError
from solidseas.formats import Limits, open_model
from solidseas.formats.solidworks.components import IDENTITY as UNPLACED
from solidseas.formats.threemf import transform
from support import FIXTURES, fixture_path

FIXTURE = fixture_path("o02_boxA.3mf")
GT = json.loads(fixture_path("ground_truth.json").read_text(encoding="utf-8"))
O02 = GT["o02_boxA.SLDPRT"]["api"]["configurations"]["Default"]


# --------------------------------------------------------------------------- the fixture
def test_the_solidworks_3mf_fixture_reads_to_its_box():
    with open_model(FIXTURE) as doc:
        assert (doc.format, doc.variant, doc.doc_type, doc.kind) == ("3mf", "core", "part", "mesh")
        assert doc.units == {"length": "mm", "scale_m": 0.001, "source": "file"}
        assert doc.warnings == []
        assert doc.fields.created_utc.isoformat() == "2026-10-01T00:00:00"  # a date alone: naive
        assert {p.name for p in doc.properties} == {"CreationDate", "ModificationDate"}
        assert (
            doc.counts()["objects"] == 2 and doc.counts()["items"] == 1 and doc.counts()["model_parts"] == 1
        )
        s = doc.scene()
        (obj,) = s.objects
        m = obj.measures()
        assert m["volume_m3"] == pytest.approx(O02["volume_m3"], rel=1e-9)
        assert m["area_m2"] == pytest.approx(O02["surface_area_m2"], rel=1e-9)
        lo, hi = m["box"]
        assert [*lo, *hi] == pytest.approx(O02["bounding_box_m"], abs=1e-12)
        nodes = doc.tree().nodes
        assert [(n.id, n.parent, n.kind, n.object) for n in nodes] == [
            ("1", None, "component", None),
            ("1.1", "1", "object", 0),
        ]
        assert [it.instance for it in s.items] == ["1.1"]
        pv = doc.preview()
        assert (pv.mime, pv.width, pv.height, pv.stream) == ("image/png", 512, 512, "Metadata/thumbnail.png")


def test_the_fixture_exports_closed_and_its_preview_is_sanitised(tmp_path):
    with open_model(FIXTURE) as doc:
        pm = export.print_model(doc)
    assert pm.closed and pm.source_format == "3mf" and pm.measures()["volume_m3"] == pytest.approx(6e-6)
    folder = tmp_path / "f"
    folder.mkdir()
    (folder / "box.3mf").write_bytes(FIXTURE.read_bytes())
    jobs.configure({"roots": [str(folder)]})
    try:
        meta, png = jobs.model_preview(
            {"path": str(folder / "box.3mf"), "within": str(folder), "name": "box.3mf"}
        )
    finally:
        jobs.configure({})
    assert (
        meta["source"] == "stored"
        and meta["stream"] == "Metadata/thumbnail.png"
        and png.startswith(b"\x89PNG")
    )
    entry = next(e for e in scan(folder, formats="3mf", include=("preview",)) if e["type"] == "file")
    assert entry["status"] == "ok" and entry["preview"]["available"] and entry["model"]["format"] == "3mf"


@pytest.mark.parametrize("name", ["o02_boxA.3mf", "o02_boxA.STL"])
def test_the_solidworks_exports_of_the_box_match_the_ground_truth(name):
    with open_model(fixture_path(name)) as doc:
        assert GT[name]["source_document"] == "o02_boxA.SLDPRT"
        s = doc.scene()
        m = export.print_model(doc).measures()
        assert m["volume_m3"] == pytest.approx(O02["volume_m3"], rel=1e-9)
        assert m["area_m2"] == pytest.approx(O02["surface_area_m2"], rel=1e-9)
        boxes = [s.objects[it.object].measures()["box"] for it in s.items]
        lo = [min(b[0][k] for b in boxes) for k in range(3)]
        hi = [max(b[1][k] for b in boxes) for k in range(3)]
        assert [*lo, *hi] == pytest.approx(O02["bounding_box_m"], abs=1e-9)


# --------------------------------------------------------------------------- SolidSeas' own writer
NATIVE = sorted(p.name for p in FIXTURES.iterdir() if p.suffix.upper() in (".SLDPRT", ".SLDASM"))
_PRINTED: dict = {}


def _printed(name: str):
    """The fixture's print model, once a test session (None when it has nothing to print)."""
    if name not in _PRINTED:
        with open_document(fixture_path(name)) as doc:
            try:
                _PRINTED[name] = export.print_model(doc)
            except NothingToExportError:
                _PRINTED[name] = None
    return _PRINTED[name]


@pytest.mark.parametrize("name", NATIVE)
def test_an_stl_solidseas_wrote_reads_back_to_its_print_model(name):
    pm = _printed(name)
    if pm is None:
        pytest.skip("the fixture has nothing to print")
    want = pm.measures()
    with open_model(export.export_bytes(pm, "stl"), name="again.stl") as doc:
        s = doc.scene()
        assert s.counts["triangles"] == pm.counts["triangles"]
        got = export.print_model(doc).measures()
    assert got["volume_m3"] == pytest.approx(want["volume_m3"], rel=1e-5)
    assert got["area_m2"] == pytest.approx(want["area_m2"], rel=1e-5)


@pytest.mark.parametrize("name", NATIVE)
def test_a_3mf_solidseas_wrote_reads_back_to_its_print_model(name):
    pm = _printed(name)
    if pm is None:
        pytest.skip("the fixture has nothing to print")
    with open_model(export.export_bytes(pm, "3mf"), name="again.3mf") as doc:
        s = doc.scene()
        assert doc.application["name"] == "SolidSeas"
        assert len(s.objects) == len(pm.objects) and len(s.items) == len(pm.items)
        for got, want in zip(s.items, pm.items, strict=True):
            assert got.object == want.object
            assert [*got.placement.translation_m] == pytest.approx([*want.placement.translation_m], abs=1e-12)
            for a, b in zip(got.placement.rotation, want.placement.rotation, strict=True):
                assert list(a) == pytest.approx(list(b), abs=1e-12)
        for got, want in zip(s.objects, pm.objects, strict=True):
            assert got.n_triangles == want.n_triangles and got.n_vertices == want.n_vertices
            assert got.measures()["volume_m3"] == pytest.approx(want.measures()["volume_m3"], rel=1e-9)
        assert doc.doc_type == ("assembly" if len(pm.items) > 1 else "part")
        again = export.print_model(doc)
    assert again.measures()["volume_m3"] == pytest.approx(pm.measures()["volume_m3"], rel=1e-9)
    assert again.closed == pm.closed


# --------------------------------------------------------------------------- the neutral scene
@pytest.mark.parametrize("colors", ["base", "colorgroup", None])
@pytest.mark.parametrize("layout", ["plain", "production", "wrap"])
def test_the_neutral_scene_reads_alike_in_every_layout(colors, layout):
    scene = two_object_assembly()
    data = mw.threemf(scene, colors=colors, production=layout == "production", wrap=layout == "wrap")
    with open_model(data, name="s.3mf") as doc:
        assert doc.doc_type == "assembly"
        assert doc.variant == ("production" if layout == "production" else "core")
        assert mw.scene_volume(doc) == pytest.approx(scene.volume_mm3() * 1e-9, rel=1e-12)
        s = doc.scene()
        assert len(s.objects) == 2 and len(s.items) == 3
        if colors is None:
            assert [o.color for o in s.objects] == [None, None]
        else:
            assert [o.color for o in s.objects] == [
                pytest.approx((0.8, 0.102, 0.102, 1.0), abs=2e-3),
                pytest.approx((0.102, 0.2, 0.8, 1.0), abs=2e-3),
            ]
        lo, hi = s.objects[1].measures()["box"]
        assert hi[2] - lo[2] == pytest.approx(0.010)
        moved = s.items[1].placement
        assert moved.translation_m == pytest.approx((0.05, 0.0, 0.0))
        assert [list(r) for r in moved.rotation] == [list(r) for r in QUARTER_Z]
        tree = doc.tree().nodes
        objects = {n.id: n.object for n in tree if n.kind == "object"}
        assert sorted(objects.values()) == [0, 0, 1]
        assert {it.instance for it in s.items} == set(objects)
        pm = export.print_model(doc)
    assert pm.closed and pm.measures()["volume_m3"] == pytest.approx(20000e-9, rel=1e-12)


def test_one_item_is_a_part_and_several_are_an_assembly():
    one = Scene([box(1, 2, 3)], [Item(0)])
    with open_model(mw.threemf(one), name="p.3mf") as doc:
        assert doc.doc_type == "part" and [n.parent for n in doc.tree().nodes] == [None]
    with open_model(mw.threemf(one, wrap=True), name="p.3mf") as doc:
        assert doc.doc_type == "part"  # a components object with one component is still a part
    two = Scene([box(1, 2, 3)], [Item(0), Item(0, IDENTITY, (5.0, 0.0, 0.0))])
    with open_model(mw.threemf(two), name="a.3mf") as doc:
        assert doc.doc_type == "assembly" and doc.tree().nodes[0].kind == "assembly"


@pytest.mark.parametrize(
    ("unit", "length", "scale"),
    [
        ("micron", "micron", 1e-6),
        ("millimeter", "mm", 1e-3),
        ("centimeter", "cm", 1e-2),
        ("inch", "in", 0.0254),
        ("foot", "ft", 0.3048),
        ("meter", "m", 1.0),
        (None, "mm", 1e-3),
    ],
)
def test_units_scale_the_model(unit, length, scale):
    scene = Scene([box(1, 2, 3)], [Item(0, IDENTITY, (4.0, 0.0, 0.0))])
    with open_model(mw.threemf(scene, unit=unit), name="u.3mf") as doc:
        assert doc.units == {
            "length": length,
            "scale_m": scale,
            "source": "format" if unit is None else "file",
        }
        s = doc.scene()
        assert s.objects[0].measures()["volume_m3"] == pytest.approx(6 * scale**3, rel=1e-12)
        assert s.items[0].placement.translation_m == pytest.approx((4 * scale, 0.0, 0.0))
    with pytest.raises(SldFormatError):
        open_model(mw.threemf(scene, unit="furlong"), name="u.3mf")


def test_transforms_are_row_vector_matrices():
    p = transform("0 1 0 -1 0 0 0 0 1 10 20 30", 0.001)
    assert p.apply((0.001, 0.0, 0.0)) == pytest.approx((0.010, 0.021, 0.030))  # x turns to y
    assert transform(None, 1.0) == UNPLACED and transform(" ", 1.0) == UNPLACED
    for bad in ("1 2 3", "a b c d e f g h i j k l"):
        with pytest.raises(SldFormatError):
            transform(bad, 1.0)


def test_metadata_fills_fields_application_and_properties():
    meta = {
        "Title": "Invented bracket",
        "Designer": "A. Designer",
        "Description": "made up",
        "CreationDate": "2026-09-30T14:02:11Z",
        "ModificationDate": "2026-10-01",
        "Application": "Example Slicer-2.6.1",
        "Custom": "kept",
    }
    with open_model(mw.threemf(box(1, 1, 1), metadata=meta, vendor=True), name="m.3mf") as doc:
        f = doc.fields
        assert (f.title, f.author, f.comments) == ("Invented bracket", "A. Designer", "made up")
        assert f.created_utc.isoformat() == "2026-09-30T14:02:11+00:00"  # a zone: aware UTC
        # a date alone or a time without a zone stays as stored, so no viewer moves its day
        assert f.last_saved_utc.isoformat() == "2026-10-01T00:00:00" and f.last_saved_utc.tzinfo is None
        assert doc.application == {"name": "Example Slicer", "version": "2.6.1"}
        assert [p.name for p in doc.properties] == list(meta)  # the vendor's own metadata is not read
        assert "slicer_data_ignored" in mw.codes(doc.warnings)
        data = doc.summary()
    assert data["application"]["version"] == "2.6.1" and data["fields"]["title"] == "Invented bracket"


# --------------------------------------------------------------------------- thumbnails
def test_thumbnails_by_relationship_then_by_name_then_the_first_plate():
    with open_model(mw.threemf(box(1, 1, 1), thumbnail=mw.png(8, 6)), name="t.3mf") as doc:
        pv = doc.preview()
        assert (pv.width, pv.height, pv.stream) == (8, 6, "Metadata/thumbnail.png")
    plates = {"Metadata/plate_2.png": mw.png(4, 4), "Metadata/plate_1.png": mw.png(5, 5)}
    with open_model(mw.threemf(box(1, 1, 1), extra_parts=plates), name="t.3mf") as doc:
        assert doc.preview().stream == "Metadata/plate_1.png"
    jpeg = {"Metadata/thumbnail.png": b"\xff\xd8\xff\xe0 not a png"}
    with open_model(mw.threemf(box(1, 1, 1), extra_parts=jpeg), name="t.3mf") as doc:
        assert doc.preview() is None
        assert doc.summary()["preview"] == {
            **doc.summary()["preview"],
            "available": False,
            "renderable": True,
        }


def test_a_thumbnail_larger_than_its_bound_is_left_out():
    data = mw.threemf(box(1, 1, 1), thumbnail=mw.png(64, 64))
    with open_model(data, name="t.3mf", limits=Limits(image_bytes=100)) as doc:
        assert doc.preview() is None


# --------------------------------------------------------------------------- extensions
def test_a_required_extension_the_reader_lacks_refuses_the_file():
    with pytest.raises(FormatNotSupportedError) as exc:
        open_model(mw.threemf(box(1, 1, 1), required=(("s", mw.SLICE),)), name="r.3mf")
    assert exc.value.detail == {"rule": "required_extension", "value": mw.SLICE}
    with pytest.raises(FormatNotSupportedError) as exc:
        open_model(mw.threemf(box(1, 1, 1), required=(("x", "http://example.invalid/x"),)), name="r.3mf")
    assert exc.value.detail["value"] == "http://example.invalid/x"
    with pytest.raises(SldFormatError):  # a prefix it never declares
        open_model(mw.threemf(box(1, 1, 1), root_extra=' requiredextensions="q"'), name="r.3mf")


def test_required_production_and_materials_are_read_and_recommended_unknowns_warned():
    data = mw.threemf(box(1, 1, 1), colors="colorgroup", production=True, required=(("p", mw.PRODUCTION),))
    with open_model(data, name="p.3mf") as doc:
        assert doc.variant == "production" and mw.scene_volume(doc) == pytest.approx(1e-9)
    data = mw.threemf(box(1, 1, 1), recommended=(("s", mw.SLICE),))
    with open_model(data, name="r.3mf") as doc:
        assert "extension_ignored" in mw.codes(doc.warnings)


def test_a_non_root_part_that_requires_an_unknown_extension_is_refused():
    data = mw.threemf(box(1, 1, 1), production=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    name = "3D/Objects/object_1.model"
    parts[name] = parts[name].replace(
        b"<model ", b'<model xmlns:s="%s" requiredextensions="s" ' % mw.SLICE.encode(), 1
    )
    with open_model(mw._zip(parts), name="n.3mf") as doc:
        with pytest.raises(FormatNotSupportedError):
            doc.scene()


def test_a_non_root_part_may_not_name_another_part():
    data = mw.threemf(
        Scene([box(1, 1, 1), box(2, 2, 2)], [Item(0), Item(1, IDENTITY, (9.0, 0, 0))]), production=True
    )
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    name = "3D/Objects/object_1.model"
    sneaky = (
        '<object id="7" type="model"><components>'
        '<component objectid="2" p:path="/3D/Objects/object_2.model"/>'
        "</components></object></resources>"
    )
    parts[name] = parts[name].replace(b"</resources>", sneaky.encode(), 1)
    with open_model(mw._zip(parts), name="n.3mf") as doc:
        s = doc.scene()
        assert "part_reference_refused" in mw.codes(s.warnings) and len(s.items) == 2


# --------------------------------------------------------------------------- objects and the build
def test_other_objects_are_never_placed_and_support_objects_are():
    scene = Scene([box(1, 1, 1), box(2, 2, 2)], [Item(0), Item(1, IDENTITY, (5.0, 0.0, 0.0))])
    data = mw.threemf(scene, colors=None).replace(b"", b"")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    m = parts["3D/3dmodel.model"]
    m = m.replace(b'<object id="1" type="model"', b'<object id="1" type="other"', 1)
    m = m.replace(b'<object id="2" type="model"', b'<object id="2" type="support"', 1)
    parts["3D/3dmodel.model"] = m
    with open_model(mw._zip(parts), name="o.3mf") as doc:
        s = doc.scene()
        assert len(s.objects) == 1 and len(s.items) == 1
        assert [k.reason for k in s.skipped] == ["other_object"]
        assert s.objects[0].measures()["volume_m3"] == pytest.approx(8e-9)


def test_a_missing_object_or_part_is_left_out_with_a_warning():
    build = (
        '<build><item objectid="1"/><item objectid="99"/><item objectid="1" p:path="/3D/none.model"/></build>'
    )
    data = mw.threemf(box(1, 1, 1), build_xml=build, production=True)
    # production=True wraps object 1 as 1001; object 1 itself lives in its own part, so the
    # first item names an object the root lacks too
    with open_model(data, name="m.3mf") as doc:
        s = doc.scene()
        assert s.items == () and "component_not_found" in mw.codes(s.warnings)
        assert len([k for k in s.skipped if k.reason == "component_not_found"]) == 3


def test_component_cycles_and_depth_are_refused():
    cyc = (
        '<object id="10" type="model"><components><component objectid="11"/></components></object>'
        '<object id="11" type="model"><components><component objectid="10"/></components></object>'
    )
    data = mw.threemf(box(1, 1, 1), resources_extra=cyc, build_xml='<build><item objectid="10"/></build>')
    with open_model(data, name="c.3mf") as doc:
        with pytest.raises(SldFormatError):
            doc.scene()
    chain = (
        "".join(
            f'<object id="{20 + i}" type="model"><components>'
            f'<component objectid="{21 + i}"/></components></object>'
            for i in range(20)
        )
        + '<object id="40" type="model"><components><component objectid="1"/></components></object>'
    )
    data = mw.threemf(box(1, 1, 1), resources_extra=chain, build_xml='<build><item objectid="20"/></build>')
    with open_model(data, name="d.3mf") as doc:
        with pytest.raises(SldLimitError) as exc:
            doc.scene()
    assert exc.value.detail["limit"] == "threemf_component_depth"


def test_triangle_colours_split_an_object_and_too_many_are_merged():
    m = box(1, 1, 1)
    groups = (
        '<basematerials id="5"><base name="r" displaycolor="#FF0000"/>'
        '<base name="g" displaycolor="#00FF00"/></basematerials>'
    )
    obj = mw.threemf_mesh_xml(m, 1, tri_props=lambda k: f' pid="5" p1="{k % 2}"')
    data = mw.threemf(
        Scene([], []),
        resources_extra=groups + obj,
        build_xml='<build><item objectid="1"/></build>',
        colors=None,
    )
    with open_model(data, name="c.3mf") as doc:
        s = doc.scene()
        assert [o.color for o in s.objects] == [(1.0, 0.0, 0.0, 1.0), (0.0, 1.0, 0.0, 1.0)]
        assert [o.n_triangles for o in s.objects] == [6, 6] and len(s.items) == 2
        assert {it.instance for it in s.items} == {"1"}
        (node,) = doc.tree().nodes
        assert node.object == 0 and node.color == (1.0, 0.0, 0.0, 1.0)
        assert export.print_model(doc).measures()["volume_m3"] == pytest.approx(1e-9)
    with open_model(data, name="c.3mf", limits=Limits(colors_per_object=1)) as doc:
        s = doc.scene()
        assert len(s.objects) == 1 and "colors_ignored" in mw.codes(s.warnings)


def test_a_triangle_without_p1_takes_its_objects_default_whatever_its_pid():
    # the 3MF Core Specification (the triangle element) gives a triangle without p1 its
    # object's default property
    groups = (
        '<basematerials id="5"><base name="r" displaycolor="#FF0000"/>'
        '<base name="g" displaycolor="#00FF00"/></basematerials>'
        '<basematerials id="6"><base name="b" displaycolor="#0000FF"/>'
        '<base name="w" displaycolor="#FFFFFF"/></basematerials>'
    )

    def props(k):
        return (' pid="6"', ' pid="6" p1="1"', "", ' p1="0"')[k % 4]

    obj = mw.threemf_mesh_xml(box(1, 1, 1), 1, extra=' pid="5" pindex="1"', tri_props=props)
    data = mw.threemf(
        Scene([], []),
        resources_extra=groups + obj,
        build_xml='<build><item objectid="1"/></build>',
        colors=None,
    )
    with open_model(data, name="p.3mf") as doc:
        s = doc.scene()
    # pid 6 without p1, and no property at all: the object's green; pid 6 p1 1: white; p1 0
    # in the object's group: red
    assert {o.color: o.n_triangles for o in s.objects} == {
        (0.0, 1.0, 0.0, 1.0): 6,
        (1.0, 1.0, 1.0, 1.0): 3,
        (1.0, 0.0, 0.0, 1.0): 3,
    }


def test_textures_give_no_colour_and_are_warned():
    tex = '<m:texture2dgroup id="7" texid="1"><m:tex2coord u="0" v="0"/></m:texture2dgroup>'
    obj = mw.threemf_mesh_xml(box(1, 1, 1), 1, tri_props=lambda k: ' pid="7" p1="0"')
    data = mw.threemf(
        Scene([], []),
        resources_extra=tex + obj,
        build_xml='<build><item objectid="1"/></build>',
        colors="colorgroup",
    )
    with open_model(data, name="t.3mf") as doc:
        s = doc.scene()
        assert [o.color for o in s.objects] == [None] and "textures_ignored" in mw.codes(s.warnings)


def test_a_mirroring_item_is_kept_and_warned():
    mirror = ((-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    scene = Scene([holed_block()], [Item(0, mirror, (0.0, 0.0, 0.0))])
    with open_model(mw.threemf(scene), name="m.3mf") as doc:
        s = doc.scene()
        assert "non_rigid_transform" in mw.codes(s.warnings)
        pm = export.print_model(doc)
    assert pm.measures()["volume_m3"] == pytest.approx(scene.volume_mm3() * 1e-9)


@pytest.mark.parametrize("value", ["nan", "inf", "1e999", "-1e999"])
@pytest.mark.parametrize("where", ["item", "component"])
def test_a_transform_that_is_not_finite_never_breaks_the_summary(where, value):
    """The scene leaves such an item out; the tree keeps its node with a null placement
    and a warning, so every summary surface still answers (it used to raise ValueError,
    an internal error and a REST 500)."""
    cells = f"1 0 0 0 1 0 0 0 1 {value} 0 0"
    if where == "item":
        build = f'<build><item objectid="1" transform="{cells}"/></build>'
        data = mw.threemf(box(10, 20, 30), build_xml=build)
    else:
        wrapper = (
            f'<object id="9" type="model"><components><component objectid="1" transform="{cells}"/>'
            "</components></object>"
        )
        data = mw.threemf(
            box(10, 20, 30), resources_extra=wrapper, build_xml='<build><item objectid="9"/></build>'
        )
    with open_model(data, name="nan.3mf") as doc:
        summary = doc.summary(include=("properties", "tree", "references"))
        json.dumps(summary, allow_nan=False)  # strict JSON
        (w,) = [w for w in summary["warnings"] if w["code"] == "value_not_representable"]
        assert w["stream"] == "tree"  # the node is kept, its placement null
        s = doc.scene()
        assert s.items == () and [x.reason for x in s.skipped] == ["non_finite_placement"]
        with pytest.raises(NothingToExportError):
            export.print_model(doc)


def test_the_scene_cap_and_the_triangle_bound():
    data = mw.threemf(two_object_assembly())
    with open_model(data, name="b.3mf") as doc:
        s = doc.scene(max_triangles=13)
        assert s.truncated == ("max_triangles",)
    with open_model(data, name="b.3mf", limits=Limits(triangles=20)) as doc:
        with pytest.raises(SldLimitError) as exc:
            doc.scene()
    assert exc.value.detail["limit"] == "triangles"
    with pytest.raises(SldLimitError) as exc:
        open_model(data, name="b.3mf", limits=Limits(objects=1))  # the head counts the objects
    assert exc.value.detail["limit"] == "objects"


def test_head_counts_and_the_listing_entry(tmp_path):
    (tmp_path / "s.3mf").write_bytes(mw.threemf(two_object_assembly(), thumbnail=mw.png()))
    data = scan(tmp_path, formats="all", include=("properties", "preview")).listing()
    (entry,) = data["entries"]
    assert entry["status"] == "ok" and entry["doc_type"] == "assembly" and entry["preview"]["available"]
    assert entry["model"]["counts"]["objects"] == 2 and entry["model"]["counts"]["items"] == 3
    assert entry["model"]["variant"] == "core"
    from jsonschema_subset import validate

    assert validate(model.envelope("listing", data), model.envelope_schema("listing"), strict=True) == []


def test_render_and_export_through_the_cli(tmp_path, capsys):
    from solidseas import cli

    (tmp_path / "in").mkdir()
    out = tmp_path / "out"
    out.mkdir()
    path = tmp_path / "in" / "s.3mf"
    path.write_bytes(mw.threemf(two_object_assembly()))
    assert cli.main(["preview", str(path), "-o", str(out / "p.png"), "--json"]) == 0
    env = json.loads(capsys.readouterr().out)
    assert env["data"]["source"] == "rendered" and (out / "p.png").read_bytes().startswith(b"\x89PNG")
    assert cli.main(["export", str(path), "--format", "stl", "-o", str(out / "s.stl"), "--json"]) == 0
    env = json.loads(capsys.readouterr().out)
    assert env["data"]["source_format"] == "3mf" and env["data"]["closed"]
    with open_model(out / "s.stl") as again:
        assert mw.scene_volume(again) == pytest.approx(20000e-9, rel=1e-6)


@pytest.mark.usefixtures("outbound_guard")
def test_python_cli_and_rest_give_the_same_model_summary(tmp_path, capsys):
    (tmp_path / "a.3mf").write_bytes(mw.threemf(two_object_assembly(), thumbnail=mw.png(), production=True))
    (tmp_path / "b.3mf").write_bytes(FIXTURE.read_bytes())
    mw.same_on_three_surfaces(tmp_path, ["a.3mf", "b.3mf"], "3mf", capsys)
