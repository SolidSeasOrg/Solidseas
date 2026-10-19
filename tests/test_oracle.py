"""Oracle tests: exact expected values from the synthetic fixtures and SOLIDWORKS' own exports.

The ground truth is documented in tests/fixtures/README.md and generation.log.
"""

import struct

import pytest

from solidseas import SolidSeasDeprecationWarning
from solidseas.formats.solidworks import open_document
from solidseas.formats.solidworks import parasolid as ps
from support import ASSEMBLY, NATIVE, PARTS, fixture_path

ORACLE_PROPS = {
    "PartNo": ("ORACLE-PN-123", "text"),
    "Description": ("Oracle test box", "text"),
    "Qty": (42, "number"),
}


def _props(doc):
    return {p.name: (p.value, p.type) for p in doc.properties}


def _xt(name: str) -> ps.XtTransmit:
    return ps.read_file(fixture_path(name).read_bytes())


# --------------------------------------------------------------------------- type and version
@pytest.mark.parametrize("name", NATIVE)
def test_type_and_saving_version(name):
    with open_document(fixture_path(name)) as doc:
        assert doc.format == "modern"
        assert doc.doc_type == ("assembly" if name == ASSEMBLY else "part")
        sv = doc.saved_version
        assert sv.format_version == 17000
        assert sv.release == "SOLIDWORKS 2024" and sv.release_verified
        assert sv.last_build == 2024016  # SOLIDWORKS 2024 SP1, revision 32.1.0
        assert sv.history[-1].version == 17000 and not sv.save_as_previous
        assert doc.metadata.checks["doc_type_guid_vs_extension"] is True
        assert doc.units["system"] == "MMGS" and doc.units["length"] == "mm"
        assert not doc.warnings


def test_assembly_template_history_is_inherited():
    with open_document(fixture_path(ASSEMBLY)) as doc:
        versions = [e.version for e in doc.saved_version.history]
    assert versions[0] < 17000 and versions[-1] == 17000
    assert 16000 in versions


# --------------------------------------------------------------------------- properties and configurations
@pytest.mark.parametrize(
    "name", ["o01_empty.SLDPRT", "o02_boxA.SLDPRT", "o03_boxA_again.SLDPRT", "o07_boxB_h31.SLDPRT", ASSEMBLY]
)
def test_no_custom_properties(name):
    with open_document(fixture_path(name)) as doc:
        assert doc.properties == []


@pytest.mark.parametrize(
    "name", ["o04_boxA_props.SLDPRT", "o05_boxA_props_mat.SLDPRT", "o06_boxA_props_mat_cfg.SLDPRT"]
)
def test_custom_properties_exact(name):
    with open_document(fixture_path(name)) as doc:
        assert _props(doc) == ORACLE_PROPS
        assert all(not p.linked for p in doc.properties)
        assert [p.expression for p in doc.properties] == ["ORACLE-PN-123", "Oracle test box", "42"]


@pytest.mark.parametrize("name", ["o02_boxA.SLDPRT", "o04_boxA_props.SLDPRT"])
def test_no_material(name):
    with open_document(fixture_path(name)) as doc:
        assert doc.material is None
        assert doc.configurations[0].material_assigned is False


@pytest.mark.parametrize("name", ["o05_boxA_props_mat.SLDPRT", "o06_boxA_props_mat_cfg.SLDPRT"])
def test_material(name):
    with open_document(fixture_path(name)) as doc:
        assert doc.material == "1060 Alloy"
        assert doc.metadata.material_database == "SOLIDWORKS Materials"
        assert doc.configurations[0].material_assigned is True


def test_configurations_of_o06():
    with open_document(fixture_path("o06_boxA_props_mat_cfg.SLDPRT")) as doc:
        assert [c.name for c in doc.configurations] == ["Default", "OracleAlt"]
        assert doc.active_configuration == "Default"
        default, alt = doc.configurations
        assert default.active and not alt.active
        assert (default.id, alt.id) == (0, 1)
        assert alt.comment == "oracle alt config"
        assert [(p.name, p.value, p.type) for p in alt.properties] == [("CfgOnly", "ALT-VALUE", "text")]
        assert default.properties == []
        assert doc.property_values("OracleAlt") == {
            **{k: v for k, (v, _) in ORACLE_PROPS.items()},
            "CfgOnly": "ALT-VALUE",
        }


@pytest.mark.parametrize("name", [p for p in PARTS if p != "o06_boxA_props_mat_cfg.SLDPRT"])
def test_single_configuration(name):
    with open_document(fixture_path(name)) as doc:
        assert [c.name for c in doc.configurations] == ["Default"]
        assert doc.active_configuration == "Default"


# --------------------------------------------------------------------------- Parasolid
@pytest.mark.parametrize(
    ("name", "reference"),
    [
        ("o02_boxA.SLDPRT", "o02_boxA.x_b"),
        ("o03_boxA_again.SLDPRT", "o02_boxA.x_b"),
        ("o04_boxA_props.SLDPRT", "o02_boxA.x_b"),
        ("o05_boxA_props_mat.SLDPRT", "o02_boxA.x_b"),
        ("o06_boxA_props_mat_cfg.SLDPRT", "o02_boxA.x_b"),
        ("o07_boxB_h31.SLDPRT", "o07_boxB_h31.x_b"),
    ],
)
def test_parasolid_matches_solidworks_export(name, reference):
    ref = _xt(reference)
    with open_document(fixture_path(name)) as doc:
        res = doc.parasolid()
    assert res.problems == []
    assert len(res.bodies) == 1
    body = res.bodies[0]
    assert (body.name, body.configuration_name, body.source, body.body_type) == (
        "Config-0/body1",
        "Default",
        "partition",
        "solid",
    )
    assert body.valid
    mine = ps.read_file(body.x_b("box"))
    assert (mine.modeller, mine.schema, mine.max_types, mine.usfld) == (
        ref.modeller,
        ref.schema,
        ref.max_types,
        ref.usfld,
    )
    assert mine.schema == "SCH_3501251_35102_13006"
    cmp = ps.compare_brep(mine, ref)
    assert cmp["identical"], cmp
    assert cmp["matched_nodes"] == 87
    assert ps.compare_brep(ps.read_file(body.x_t("box")), ref, tol=1e-14)["identical"]


def test_geometry_differs_between_box_a_and_box_b():
    with open_document(fixture_path("o07_boxB_h31.SLDPRT")) as doc:
        b = ps.read_file(doc.parasolid().bodies[0].x_b("b"))
    cmp = ps.compare_brep(b, _xt("o02_boxA.x_b"))
    assert not cmp["identical"] and cmp["n_diffs"] > 0
    points = [n.vals[-1] for n in b.nodes if n.tname == "POINT"]
    assert max(p[2] for p in points) == pytest.approx(0.031)


def test_empty_part_has_an_empty_partition():
    with open_document(fixture_path("o01_empty.SLDPRT")) as doc:
        res = doc.parasolid(include_raw=True)
    assert res.bodies == [] and res.problems == []
    assert sorted(t.kind for t in res.raw) == ["deltas", "partition"]
    raw = next(t for t in res.raw if t.kind == "partition")
    assert ps.parse_binary(raw.data).kind == "partition"
    assert raw.p_b("empty").startswith(b"**ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def test_solidworks_x_b_round_trips_byte_for_byte():
    _header, body = ps.split_header(fixture_path("o02_boxA.x_b").read_bytes())
    xt = ps.parse_binary(body)
    assert ps.write_binary(xt) == body
    assert ps.validate(xt)["ok"]


def test_text_writer_reproduces_solidworks_x_t():
    _header, body = ps.split_header(fixture_path("o02_boxA.x_t").read_bytes())
    text = body.decode("latin-1")
    records = text.replace("\r", "").rstrip("\n").split("\n")
    rewritten = ps.write_text(ps.parse_text(text))
    assert rewritten == "\n".join(records)


def test_text_and_binary_exports_describe_the_same_model():
    cmp = ps.compare_brep(_xt("o02_boxA.x_t"), _xt("o02_boxA.x_b"), tol=1e-14)
    assert cmp["identical"]


# --------------------------------------------------------------------------- assembly references
def test_assembly_references():
    with open_document(fixture_path(ASSEMBLY)) as doc:
        refs = doc.references()
        assert doc.parasolid().bodies == []
    assert len(refs) == 1
    ref = refs[0]
    assert ref.file_name == "o02_boxA.SLDPRT"
    assert ref.path.endswith("o02_boxA.SLDPRT")
    assert ref.direct is True and ref.virtual is False
    assert ref.configurations == ["Default"]
    assert "Header2" in ref.sources
    assert sorted(i.name for i in ref.instances) == ["o02_boxA-1", "o02_boxA-2"]
    assert ref.key is not None and len(ref.instances) == 2
    with pytest.warns(SolidSeasDeprecationWarning):
        assert ref.quantity == 2  # deprecated, still answering for 0.1 callers
    t1, t2 = (i.translation for i in sorted(ref.instances, key=lambda i: i.name))
    assert (t2[0] - t1[0], t2[1] - t1[1], t2[2] - t1[2]) == pytest.approx((0.05, 0.0, 0.0))


def test_parts_have_no_references():
    with open_document(fixture_path("o02_boxA.SLDPRT")) as doc:
        assert doc.references() == []


# --------------------------------------------------------------------------- previews and display mesh
@pytest.mark.parametrize("name", NATIVE)
def test_previews(name):
    with open_document(fixture_path(name)) as doc:
        png = doc.preview()
        assert (png.mime, png.width, png.height, png.stream) == ("image/png", 640, 480, "PreviewPNG")
        assert png.data.startswith(b"\x89PNG\r\n\x1a\n")
        bmp = doc.preview(prefer="dib")
    assert bmp.mime == "image/bmp" and bmp.stream == "Preview"
    assert bmp.data[:2] == b"BM"
    size, width, height, planes, bpp, compression = struct.unpack_from("<IiiHHI", bmp.data, 14)
    assert (size, planes, bpp, compression) == (40, 1, 8, 1)  # BITMAPINFOHEADER, 8 bpp, BI_RLE8
    assert (width, height) == (bmp.width, bmp.height)
    assert struct.unpack_from("<I", bmp.data, 2)[0] == len(bmp.data)


def _stl_triangles(data: bytes):
    count = struct.unpack_from("<I", data, 80)[0]
    for i in range(count):
        v = struct.unpack_from("<12f", data, 84 + 50 * i)
        yield v[3:6], v[6:9], v[9:12]


def _canonical(tri, scale):
    pts = [tuple(round(x * scale, 4) + 0.0 for x in p) for p in tri]
    return min(pts[k:] + pts[:k] for k in range(3))


def test_display_mesh_equals_solidworks_stl():
    with open_document(fixture_path("o02_boxA.SLDPRT")) as doc:
        mesh = doc.mesh()
    assert (len(mesh.faces), mesh.n_triangles) == (6, 12)
    assert mesh.volume() == pytest.approx(6.0e-6, rel=1e-6)
    assert mesh.area() == pytest.approx(0.0022, rel=1e-6)
    mine = sorted(_canonical(t, 1000.0) for t in mesh.iter_triangles())
    stl = sorted(_canonical(t, 1.0) for t in _stl_triangles(fixture_path("o02_boxA.STL").read_bytes()))
    assert mine == stl
    again = sorted(_canonical(t, 1.0) for t in _stl_triangles(mesh.to_stl()))
    assert again == stl


def test_display_mesh_of_box_b_and_empty_part():
    with open_document(fixture_path("o07_boxB_h31.SLDPRT")) as doc:
        assert doc.mesh().volume() == pytest.approx(6.2e-6, rel=1e-6)
    with open_document(fixture_path("o01_empty.SLDPRT")) as doc:
        assert doc.mesh().n_triangles == 0


# --------------------------------------------------------------------------- embedded paths
def test_saved_files_embed_account_folders():
    with open_document(fixture_path("o02_boxA.SLDPRT")) as doc:
        found, skipped = doc.embedded_paths()
    assert skipped == []
    biography = {p.kind for p in found if p.stream == "_MO_VERSION_17000/Biography"}
    assert {"temp", "desktop", "program-data"} <= biography


def test_assembly_paths_include_the_component_path():
    with open_document(fixture_path(ASSEMBLY)) as doc:
        found, _ = doc.embedded_paths()
    streams = {p.stream for p in found if p.path.lower().endswith("o02_boxa.sldprt")}
    assert {"Header2", "swXmlContents/COMPINSTANCETREE", "SwDocContentMgr/SwDocContentMgrInfo"} <= streams
