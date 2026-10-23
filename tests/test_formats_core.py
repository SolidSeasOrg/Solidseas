"""The model-file contract (``docs/API.md`` 3.20): the registry and detection, opening,
the document interface, the mesh builder and scenes, the bounded building blocks of
``solidseas.formats._source``, the JSON of model files and their export."""

import io
import json
import os
import struct
import zipfile
import zlib

import pytest

import mesh_writers as mw
from jsonschema_subset import validate
from model_writers import (
    QUARTER_Z,
    Item,
    Scene,
    box,
    holed_block,
    scene_document,
    stl_ascii,
    stl_binary,
    two_object_assembly,
)
from solidseas import export, model
from solidseas.errors import (
    WARNING_CODES,
    FileTooLargeError,
    FormatNotSupportedError,
    InvalidArgumentError,
    LinkRefusedError,
    PathRefusedError,
    SldFormatError,
    SldLimitError,
    UnknownFormatError,
)
from solidseas.formats import (
    FORMATS,
    Limits,
    ModelDocument,
    by_extension,
    detect,
    extensions,
    open_any,
    open_model,
    readable,
    registry,
)
from solidseas.formats import _source as src
from solidseas.formats.base import MeshObject, ModelNode, SceneBuilder, SceneOptions, guarded
from solidseas.formats.registry import CAPABILITIES, FAMILIES, KINDS, detect_head
from solidseas.formats.solidworks import Document
from solidseas.formats.solidworks.components import IDENTITY, Placement
from support import fixture_path

OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
# The first line of an IGES file's start section: a format SolidSeas lists but cannot read.
IGES = b"a synthetic IGES file".ljust(72) + b"S      1\n"


# --------------------------------------------------------------------------- the registry
def test_every_registry_entry_is_well_formed():
    seen: dict[str, str] = {}
    for fid, spec in FORMATS.items():
        assert spec.id == fid and spec.name and spec.extensions
        assert spec.family in FAMILIES and spec.kind in KINDS and spec.up_axis in ("z", "y")
        assert spec.capabilities <= CAPABILITIES
        for ext in spec.extensions:
            assert ext.startswith(".") and ext == ext.lower(), ext
            assert ext not in seen, f"{ext} is both {seen[ext]} and {fid}"
            seen[ext] = fid
        assert set(spec.needs_signature) <= set(spec.extensions)
        if spec.reader is not None:
            module, func = spec.reader.split(":")
            assert module.startswith("solidseas.formats.") and func
    # the formats of the design, with the readers the branches add already named
    for fid in ("stl", "3mf", "obj", "ply", "off", "gltf", "amf", "parasolid", "step", "alibre", "acis"):
        assert FORMATS[fid].reader is not None, fid
    for fid in ("inventor", "solid_edge", "nx", "fusion", "3dxml", "edrawings", "vrml"):
        assert FORMATS[fid].reader is None, fid
    # IGES and BREP are read through the OCCT backend, only while it is available
    for fid in ("iges", "occt_brep"):
        assert FORMATS[fid].reader == "solidseas.formats.occt:open" and FORMATS[fid].backend == "occt", fid
    assert all(f.backend is None for f in FORMATS.values() if f.id not in ("iges", "occt_brep"))


def test_readable_finds_reader_modules_without_importing_them():
    import sys

    assert readable("stl") and readable("solidworks")
    assert not readable("iges") and not readable("nope")
    before = "solidseas.formats.threemf" in sys.modules
    readable("3mf")  # the module may or may not be there yet; it is never imported here
    assert ("solidseas.formats.threemf" in sys.modules) == before


def test_extensions_and_select():
    assert by_extension("Part.STL").id == "stl" and by_extension(".step").id == "step"
    assert by_extension("x.sldprt").id == "solidworks" and by_extension("x.txt") is None
    assert ".stl" in extensions("all") and extensions("solidworks") == (".sldasm", ".slddrw", ".sldprt")
    assert registry.select("stl, 3mf") == {"stl", "3mf"}
    assert registry.select(["all"]) == set(FORMATS)
    for bad in ("nope", "", ["stl", 3], 5):
        with pytest.raises(InvalidArgumentError):
            registry.select(bad)


def _zip(first: str, data: bytes = b"x") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(first, data)
    return buf.getvalue()


@pytest.mark.parametrize(
    ("head", "name", "expected"),
    [
        (OLE + b"\0" * 100, "a.sldprt", ("solidworks", "ole", "both", False)),
        (
            b"\x14\x00\x06\x00" + b"\x00\x00\x00\x04" + b"\0" * 100,
            "a.sldasm",
            ("solidworks", "modern", "both", False),
        ),
        (OLE + b"\0" * 100, "a.ad_prt", ("alibre", "part", "both", False)),
        (OLE + b"\0" * 100, "a.AD_ASM", ("alibre", "assembly", "both", False)),
        (OLE + b"\0" * 100, "a.bin", ("solidworks", "ole", "content", False)),
        (_zip("[Content_Types].xml"), "a.zip", ("3mf", None, "content", False)),
        (_zip("3D/3dmodel.model"), "a.3mf", ("3mf", None, "both", False)),
        (_zip("model.amf"), "m.zip", ("amf", "zip", "content", False)),
        (b"glTF" + struct.pack("<II", 2, 100) + b"\0" * 20, "m.bin", ("gltf", "glb", "content", False)),
        (b'{"asset": {"version": "2.0"}}', "m.gltf", ("gltf", "gltf", "both", False)),
        (b"\xef\xbb\xbf  ISO-10303-21;\nHEADER;", "p.stp", ("step", None, "both", False)),
        (b"ISO-10303-21;\nHEADER;", "p.stl", ("step", None, "content", True)),
        (
            b"**ABCDEFGHIJKLMNOP**\nFORMAT=text;\n**END_OF_HEADER**\nT51 : TRANSMIT",
            "p.x_t",
            ("parasolid", "text", "both", False),
        ),
        (b"PS\0\0\0\0\0", "p.x_b", ("parasolid", "binary", "both", False)),
        (b"ACIS BinaryFile" + b"\0" * 20, "p.sab", ("acis", "sab", "both", False)),
        (
            b"ply\nformat binary_little_endian 1.0\nelement vertex 3\n",
            "m.ply",
            ("ply", "binary_le", "both", False),
        ),
        (b"COFF\n3 1 0\n", "m.off", ("off", "COFF", "both", False)),
        (b"# comment\nv 0 0 0\nv 1 0 0\nf 1 2 3\n", "m.obj", ("obj", None, "both", False)),
        (b"solid x\n facet normal 0 0 1\n", "m.stl", ("stl", "ascii", "both", False)),
        (b"x" * 72 + b"S      1" + b"\n", "m.igs", ("iges", None, "both", False)),
        (b"random bytes", "m.igs", ("iges", None, "extension", False)),
        (b"random bytes", "m.txt", (None, None, None, False)),
    ],
)
def test_detection(head, name, expected):
    det = detect_head(head, len(head), name)
    assert (det.format, det.variant, det.by, det.mismatch) == expected


def test_binary_stl_detection_trusts_the_size_rule_first():
    data = stl_binary(box(1, 1, 1), header=b"solid but binary")
    assert detect_head(data[:4096], len(data), "b.stl").variant == "binary"
    assert detect(data, "b.stl").variant == "binary"
    assert detect(fixture_path("o02_boxA.STL")).format == "stl"
    assert detect(fixture_path("o02_boxA.SLDPRT")).format == "solidworks"


def test_signature_rule_for_shared_extensions():
    spec = FORMATS["solid_edge"]
    assert registry.signature_ok(spec, "a.par", b"anything")
    assert registry.signature_ok(spec, "a.asm", OLE) and not registry.signature_ok(spec, "a.asm", b"mov ax,")
    assert not registry.signature_ok(FORMATS["nx"], "a.prt", OLE)  # no known test: never by name alone


# --------------------------------------------------------------------------- opening
def test_open_model_and_open_any(tmp_path):
    with open_model(fixture_path("o02_boxA.STL")) as doc:
        assert isinstance(doc, ModelDocument) and doc.file_info.size == os.path.getsize(
            fixture_path("o02_boxA.STL")
        )
        assert doc.name == "o02_boxA.STL" and doc.path.endswith("o02_boxA.STL")
    with open_any(fixture_path("o02_boxA.STL")) as doc:
        assert isinstance(doc, ModelDocument)
    with open_any(fixture_path("o02_boxA.SLDPRT")) as doc:
        assert isinstance(doc, Document)
    with pytest.raises(InvalidArgumentError) as exc:
        open_model(fixture_path("o02_boxA.SLDPRT"))
    assert exc.value.detail["rule"] == "solidworks_document"
    with open_model(stl_binary(box(1, 1, 1)), name="mem.stl") as doc:
        assert doc.path is None and doc.file_info is None and doc.name == "mem.stl"


def test_open_model_refusals(tmp_path):
    with pytest.raises(FileTooLargeError):
        open_model(fixture_path("o02_boxA.STL"), max_file_bytes=100)
    iges = tmp_path / "part.igs"
    iges.write_bytes(IGES)
    with pytest.raises(FormatNotSupportedError) as exc:
        open_model(iges)
    assert exc.value.detail == {"rule": "needs_extension", "value": "iges"}
    assert "OCCT backend extension" in str(exc.value) and "Tools > Extensions" in str(exc.value)
    assert (
        model.error_info(exc.value)["message"]
        == model.RULE_MESSAGES[("format_not_supported", "needs_extension")]
    )
    vrml = tmp_path / "scene.wrl"
    vrml.write_bytes(b"#VRML V2.0 utf8\n")
    with pytest.raises(FormatNotSupportedError) as exc:
        open_model(vrml)
    assert exc.value.detail == {"rule": "no_reader", "value": "vrml"}
    assert (
        model.error_info(exc.value)["message"] == model.RULE_MESSAGES[("format_not_supported", "no_reader")]
    )
    junk = tmp_path / "junk.dat"
    junk.write_bytes(b"nothing SolidSeas knows")
    with pytest.raises(UnknownFormatError) as exc:
        open_model(junk)
    assert exc.value.detail["rule"] == "unidentified"
    with pytest.raises(InvalidArgumentError):
        open_model(junk, format="nope")
    with pytest.raises(InvalidArgumentError):
        open_model(b"x", within=str(tmp_path))
    with pytest.raises(PathRefusedError):
        open_model(fixture_path("o02_boxA.STL"), within=str(tmp_path))


def test_formats_name_what_a_call_may_read_whatever_the_name_says(tmp_path):
    p = tmp_path / "really_3mf.stl"
    p.write_bytes(mw.threemf(box(1, 1, 1)))
    with open_model(p) as doc:  # every format: the content wins, as before
        assert doc.format == "3mf" and "extension_mismatch" in {w.code for w in doc.warnings}
    for formats in ("stl", ["stl"], "stl,obj"):
        with pytest.raises(FormatNotSupportedError) as exc:
            open_model(p, formats=formats)
        assert exc.value.detail == {"rule": "format_not_enabled", "value": "3mf"}
    assert (
        model.error_info(exc.value)["message"]
        == model.RULE_MESSAGES[("format_not_supported", "format_not_enabled")]
    )
    with open_model(p, formats=["stl", "3mf"]) as doc:
        assert doc.format == "3mf"
    with pytest.raises(FormatNotSupportedError):  # a forced format is held to them too
        open_model(p, format="3mf", formats="stl")
    with pytest.raises(InvalidArgumentError) as exc:
        open_model(p, formats=["nope"])
    assert exc.value.detail == {"parameter": "formats"}
    # open_any: a SOLIDWORKS document is read only when SOLIDWORKS is among them, by its
    # name or its content
    with pytest.raises(FormatNotSupportedError) as exc:
        open_any(fixture_path("o02_boxA.SLDPRT"), formats="stl")
    assert exc.value.detail == {"rule": "format_not_enabled", "value": "solidworks"}
    with open_any(fixture_path("o02_boxA.SLDPRT"), formats="solidworks,stl") as doc:
        assert isinstance(doc, Document)
    inside = tmp_path / "stl_inside.SLDPRT"
    inside.write_bytes(stl_binary(box(1, 1, 1)))
    with open_any(inside, formats="stl") as doc:  # a SOLIDWORKS name over STL content: the content
        assert doc.format == "stl" and "extension_mismatch" in {w.code for w in doc.warnings}
    disguised = tmp_path / "part.stl"
    disguised.write_bytes(fixture_path("o02_boxA.SLDPRT").read_bytes())
    with pytest.raises(FormatNotSupportedError) as exc:
        open_any(disguised, formats="stl")
    assert exc.value.detail == {"rule": "format_not_enabled", "value": "solidworks"}


def test_a_forced_format_and_a_mismatched_extension(tmp_path):
    p = tmp_path / "really_stl.obj"
    p.write_bytes(stl_binary(box(1, 1, 1)))
    with open_model(p) as doc:
        assert doc.format == "stl" and "extension_mismatch" in {w.code for w in doc.warnings}
    p2 = tmp_path / "noname.bin"
    p2.write_bytes(stl_binary(box(1, 1, 1)))
    with open_model(p2, format="stl") as doc:
        assert doc.detection.by == "forced" and doc.variant == "binary"


def test_a_solidworks_name_keeps_open_document_and_its_error(tmp_path):
    p = tmp_path / "stl_inside.SLDPRT"
    p.write_bytes(stl_binary(box(1, 1, 1)))
    with open_any(p) as doc:  # content SolidSeas reads: read as it is, and said
        assert doc.format == "stl" and "extension_mismatch" in {w.code for w in doc.warnings}
    s = tmp_path / "iges_inside.SLDPRT"
    s.write_bytes(IGES)
    with pytest.raises(UnknownFormatError):  # a format with no reader: open_document's error stands
        open_any(s)


def test_open_any_within_a_folder(tmp_path):
    p = tmp_path / "a.stl"
    p.write_bytes(stl_binary(box(1, 1, 1)))
    with open_any(str(p), within=str(tmp_path), hold_open=True) as doc:
        assert not doc.source.in_memory and doc.scene().counts["triangles"] == 12
    assert doc.source.closed


# --------------------------------------------------------------------------- limits
def test_limits():
    lim = Limits()
    assert lim.triangles == 20_000_000 and lim.file_bytes is None and lim.seconds == 30.0
    assert lim.replace(triangles=5).triangles == 5
    for bad in ({"triangles": 0}, {"triangles": True}, {"seconds": float("inf")}, {"nope": 1}):
        with pytest.raises(InvalidArgumentError):
            Limits().replace(**bad)
    e = lim.exceeded("zip_ratio", "too much", 7)
    assert isinstance(e, SldLimitError) and e.detail == {"limit": "zip_ratio", "value": 7}


# --------------------------------------------------------------------------- the mesh builder and scenes
def _builder(**limits) -> SceneBuilder:
    return SceneBuilder(Limits(**limits), SceneOptions(), src.Clock(10.0))


def test_the_mesh_builder_drops_bad_triangles_and_scales():
    sb = _builder()
    mb = sb.mesh(name="m", scale_m=0.001)
    mb.add_vertices([0, 0, 0, 1, 0, 0, 0, 1, 0, float("inf"), 0, 0])
    mb.add_triangles([0, 1, 2, 0, 0, 1, 0, 1, 9, 0, 1, 3])
    obj = mb.build()
    assert list(obj.triangles) == [0, 1, 2] and obj.n_vertices == 3
    assert list(obj.positions) == [0, 0, 0, 0.001, 0, 0, 0, 0.001, 0]
    assert {w.code for w in obj.warnings} == {"indices_out_of_range", "degenerate_triangles_dropped"}
    with pytest.raises(SldFormatError):
        sb.mesh().add_triangles([-1, 0, 1])
    with pytest.raises(SldFormatError):
        sb.mesh().add_vertices([1, 2])


def test_the_mesh_builder_drops_corners_more_than_1000_km_out():
    """A coordinate a text format stores as 1e300 would overflow the export's sums and the
    3D view's float32 buffers: such a corner's triangles are left out, with a warning."""
    sb = _builder()
    mb = sb.mesh(name="m", scale_m=0.001)  # millimetres: the bound is 1e9 of them
    mb.add_vertices([0, 0, 0, 1, 0, 0, 0, 1, 0, 1e300, 0, 0, -2e9, 0, 0, 9.9e8, 0, 0])
    mb.add_triangles([0, 1, 2, 0, 1, 3, 0, 2, 4, 0, 1, 5])
    obj = mb.build()
    assert list(obj.triangles) == [0, 1, 2, 0, 1, 3] and obj.n_vertices == 4
    assert max(obj.positions) == pytest.approx(9.9e5)  # 990 km in metres is kept
    (w,) = obj.warnings
    assert w.code == "coordinates_out_of_range" and w.message.startswith("2 triangles")
    soup = sb.mesh(name="s", scale_m=1.0)  # an STL's soup in metres: one triangle out, one in
    soup.add_soup([0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 2e6, 0, 0, 0, 1, 0])
    obj = soup.build()
    assert obj.n_triangles == 1 and {w.code for w in obj.warnings} == {"coordinates_out_of_range"}


def test_a_tree_placement_that_is_not_finite_is_sent_as_null():
    nan = Placement(IDENTITY.rotation, (float("nan"), 0.0, 0.0))
    warn = model._Warnings()
    data = model.model_node_data(ModelNode("1", None, "n", "object", 0, placement=nan), warn)
    assert data["placement"] is None
    assert [w["code"] for w in warn.items] == ["value_not_representable"]
    model.model_node_data(ModelNode("2", None, "m", "object", 0, placement=nan), warn)
    assert len(warn.items) == 1  # said once a tree


def test_scene_bounds():
    sb = _builder(vertices=5)
    with pytest.raises(SldLimitError) as exc:
        sb.mesh().add_vertices([0.0] * 18)
    assert exc.value.detail["limit"] == "vertices"
    sb = _builder(objects=1)
    sb.mesh().finish()
    with pytest.raises(SldLimitError):
        sb.mesh().finish()
    sb = _builder(items=1)
    k = sb.mesh().finish()
    sb.add_item(k)
    with pytest.raises(SldLimitError):
        sb.add_item(k)


def test_scene_items_are_checked():
    sb = _builder()
    k = sb.mesh().finish()
    sb.add_item(k, "far", Placement(IDENTITY.rotation, (2e6, 0.0, 0.0)))
    sb.add_item(k, "nan", Placement(IDENTITY.rotation, (float("nan"), 0.0, 0.0)))
    mirror = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, -1.0))
    sb.add_item(k, "mirror", Placement(mirror, (0.0, 0.0, 0.0)))
    sb.add_item(k, "turned", Placement(QUARTER_Z, (0.0, 0.0, 0.0)))
    s = sb.build()
    assert [(x.instance, x.reason) for x in s.skipped] == [
        ("far", "out_of_range"),
        ("nan", "non_finite_placement"),
    ]
    assert [it.instance for it in s.items] == ["mirror", "turned"]
    assert [w.code for w in s.warnings] == ["non_rigid_transform"]
    with pytest.raises(SldFormatError):
        sb.add_item(5)
    sb.missing_component("c1", "not found")
    sb.missing_component("c2", "not found")
    s = sb.build()
    (w,) = [w for w in s.warnings if w.code == "component_not_found"]
    assert w.message.startswith("2 component")


def test_scene_options_are_checked_and_cached():
    doc = scene_document(two_object_assembly())
    for bad in (
        {"prefer": "x"},
        {"max_triangles": 0},
        {"chord_m": -1},
        {"angle_deg": 100},
        {"max_seconds": 0},
        {"body_types": ("nope",)},
        {"cancelled": 5},
    ):
        with pytest.raises(InvalidArgumentError):
            doc.scene(**bad)
    a = doc.scene()
    assert doc.scene() is a and doc.scene(prefer="display") is not a
    assert a.counts["objects"] == 2 and a.counts["items"] == 3 and a.counts["triangles"] == 12 * 2 + 32


def test_a_cancelled_scene_stops():
    doc = scene_document(Scene([box(1, 1, 1)], [Item(0)] * 5000))
    with pytest.raises(src.ReadCancelledError):
        doc.scene(cancelled=lambda: True)
    assert model.error_code(src.ReadCancelledError("x")) == "interrupted"


def test_reader_damage_becomes_a_format_error():
    def bad():
        return [1][5]

    with pytest.raises(SldFormatError):
        guarded(bad)
    with pytest.raises(InvalidArgumentError):  # SolidSeas errors pass unchanged, ValueError or not
        guarded(lambda: (_ for _ in ()).throw(InvalidArgumentError("x")))


def test_running_out_of_memory_is_a_limit_error():
    def greedy():
        raise MemoryError

    with pytest.raises(SldLimitError) as exc:  # what a worker's memory cap answers too
        guarded(greedy)
    assert exc.value.code == "limit_exceeded" and exc.value.detail == {"limit": "memory"}


def test_tree_bounds():
    class Deep(ModelDocument):
        format = "stl"

        def _tree(self, clock):
            nodes = [ModelNode("0", None, "root", "assembly")]
            nodes += [ModelNode(str(i), str(i - 1), f"n{i}", "component") for i in range(1, 50)]
            return nodes

    doc = Deep(src.Source(b"x"), name="d.stl", path=None, file_info=None, limits=Limits())
    t = doc.tree(max_depth=5)
    assert len(t.nodes) == 5 and t.truncated
    t = doc.tree(max_nodes=3)
    assert len(t.nodes) == 3 and t.truncated
    t = doc.tree()  # limits.depth is 32
    assert t.truncated and len(t.nodes) == 32
    with pytest.raises(InvalidArgumentError):
        doc.tree(max_nodes=0)


# --------------------------------------------------------------------------- bounded building blocks
def test_source_reads_are_bounded():
    s = src.Source(b"0123456789")
    assert s.read_at(2, 3) == b"234" and s.read_upto(8, 10) == b"89" and s.head(4) == b"0123"
    with pytest.raises(SldFormatError):
        s.read_at(8, 3)
    with pytest.raises(SldLimitError):
        s.read_all(5, "json_bytes")
    f = s.file()
    f.seek(-3, 2)
    assert f.read() == b"789"


def _zip_bytes(members: dict[str, bytes], method=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=method) as z:
        for n, d in members.items():
            z.writestr(n, d)
    return buf.getvalue()


def test_safe_zip_reads_and_bounds():
    data = _zip_bytes({"3D/3dmodel.model": b"<model/>", "Metadata/x.png": b"p" * 100})
    z = src.SafeZip(src.Source(data), Limits())
    assert z.read("/3d/3DMODEL.model") == b"<model/>" and z.find("missing") is None
    with pytest.raises(SldLimitError):
        src.SafeZip(src.Source(data), Limits(zip_members=1))
    bomb = _zip_bytes({"bomb": b"\0" * (4 << 20)})
    with pytest.raises(SldLimitError) as exc:
        src.SafeZip(src.Source(bomb), Limits()).read("bomb")
    assert exc.value.detail["limit"] == "zip_ratio"
    with pytest.raises(SldLimitError) as exc:
        src.SafeZip(src.Source(data), Limits(zip_member_bytes=50)).read("Metadata/x.png")
    assert exc.value.detail["limit"] == "zip_member_bytes"
    z = src.SafeZip(src.Source(_zip_bytes({"a": b"a" * 600, "b": b"b" * 600})), Limits(zip_total_bytes=1000))
    z.read("a")
    with pytest.raises(SldLimitError):
        z.read("b")
    with pytest.raises(SldFormatError):
        src.SafeZip(src.Source(b"PK\x03\x04 not a zip"), Limits())


def test_safe_zip_refuses_encrypted_and_unknown_methods():
    data = bytearray(_zip_bytes({"a": b"hello"}, zipfile.ZIP_STORED))
    for off in (6, data.rfind(b"PK\x01\x02") + 8):  # local and central flags
        struct.pack_into("<H", data, off, 1)
    with pytest.raises(FormatNotSupportedError) as exc:
        src.SafeZip(src.Source(bytes(data)), Limits()).read("a")
    assert exc.value.detail["rule"] == "encrypted"
    bz = _zip_bytes({"a": b"hello"}, zipfile.ZIP_BZIP2)
    with pytest.raises(FormatNotSupportedError) as exc:
        src.SafeZip(src.Source(bz), Limits()).read("a")
    assert exc.value.detail == {"rule": "compression", "value": "zip_method_12"}



def _padded_bomb(inflated: int, junk: int) -> bytes:
    """A zip of one deflated member of ``inflated`` zero bytes whose entries state a
    compressed size ``junk`` bytes larger than its deflate stream, the junk lying between
    the stream and the central directory, so Python's zipfile sees no overlap."""
    deflate = zlib.compressobj(9, zlib.DEFLATED, -15)
    stream = deflate.compress(bytes(inflated)) + deflate.flush()
    crc = zlib.crc32(bytes(inflated))
    name = b"bomb"
    stated = len(stream) + junk
    local = struct.pack("<4s5H3L2H", b"PK\x03\x04", 20, 0, 8, 0, 0, crc, stated, inflated, len(name), 0)
    body = local + name + stream + bytes(junk)
    central = struct.pack(
        "<4s6H3L5H2L", b"PK\x01\x02", 20, 20, 0, 8, 0, 0, crc, stated, inflated, len(name), 0, 0, 0, 0, 0, 0
    )
    end = struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 1, 1, len(central) + len(name), len(body), 0)
    return body + central + name + end


def test_the_ratio_counts_the_bytes_read_not_the_size_a_directory_states():
    # 20 MiB of zeros deflate to about 20 KB; a stated size of 1 MiB more let the ratio
    # allow 200 MiB, while what is read for the member is the stream and one read ahead
    bomb = _padded_bomb(20 << 20, 1 << 20)
    with pytest.raises(SldLimitError) as exc:
        src.SafeZip(src.Source(bomb), Limits()).read("bomb")
    assert exc.value.detail["limit"] == "zip_ratio"
    small = _padded_bomb(1 << 20, 1 << 20)  # under the 1 MiB the ratio waits for: read
    assert src.SafeZip(src.Source(small), Limits()).read("bomb") == bytes(1 << 20)


def test_each_read_of_a_package_counts_against_its_total_alone():
    z = src.SafeZip(src.Source(_zip_bytes({"a": b"a" * 600, "b": b"b" * 600})), Limits(zip_total_bytes=1000))
    z.read("a")
    with pytest.raises(SldLimitError):
        z.read("b")  # one read: 1,200 bytes
    z.start_read()
    assert z.read("b") == b"b" * 600 and z.inflated == 600

def test_a_zip_feature_python_declines_is_refused_not_raised():
    """A directory entry asking for a zip version Python's reader lacks makes ``zipfile``
    raise NotImplementedError: SafeZip turns it into the reader's own error."""
    data = bytearray(_zip_bytes({"a": b"hello"}))
    central = data.find(b"PK\x01\x02")
    data[central + 6] = 0xFF  # version needed to extract: 25.5
    with pytest.raises(SldFormatError) as exc:
        src.SafeZip(src.Source(bytes(data)), Limits())
    assert "zip" in str(exc.value)
    assert not isinstance(exc.value, NotImplementedError)


def _zip64_end(pkg: bytes, copies: int, *, stated: int | None = None) -> bytes:
    """``pkg`` with its central directory written ``copies`` times and a ZIP64 end record
    and locator that state that directory (``stated`` members, default every entry),
    while the end record itself still states the original directory, with no
    sentinels. Python's ``zipfile`` reads the ZIP64 record whatever the end record says."""
    (_sig, _d, _cd, _nd, members, cd_size, cd_off, _c) = struct.unpack_from("<IHHHHIIH", pkg, len(pkg) - 22)
    directory = pkg[cd_off : cd_off + cd_size] * copies
    body = pkg[:cd_off] + directory
    total = members * copies if stated is None else stated
    record = struct.pack("<4sQ2H2L4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, total, total, len(directory), cd_off)
    locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, len(body), 1)
    end = struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, members, members, cd_size, cd_off, 0)
    return body + record + locator + end


class _Built(zipfile.ZipInfo):
    """A ZipInfo that counts how many ``zipfile`` builds while it reads a directory."""

    made = 0

    def __init__(self, *args, **kwargs):
        type(self).made += 1
        super().__init__(*args, **kwargs)


def test_a_zip64_end_record_is_read_as_python_reads_it(monkeypatch):
    pkg = _zip_bytes({"3D/3dmodel.model": b"<model/>", "a": b"a", "b": b"b"})
    assert src.zip_directory_size(src.Source(pkg))[0] == 3
    # one copy: a well-formed ZIP64 end, read as before
    one = _zip64_end(pkg, 1)
    assert src.zip_directory_size(src.Source(one)) == src.zip_directory_size(src.Source(pkg))
    assert src.SafeZip(src.Source(one), Limits()).read("3D/3dmodel.model") == b"<model/>"
    # five copies behind an end record that names one: the count and the size come from the
    # ZIP64 record, which zipfile reads even though the end record holds no sentinel, and the
    # package is refused before zipfile reads its directory
    five = _zip64_end(pkg, 5)
    members, size = src.zip_directory_size(src.Source(five))
    assert members == 15 and size == 5 * src.zip_directory_size(src.Source(pkg))[1]

    def never(*_a, **_k):
        raise AssertionError("zipfile read the directory")

    monkeypatch.setattr(src.zipfile, "ZipFile", never)
    with pytest.raises(SldLimitError) as exc:
        src.SafeZip(src.Source(five), Limits(zip_members=10))
    assert exc.value.detail["limit"] == "zip_members"
    with pytest.raises(SldLimitError) as exc:
        src.SafeZip(src.Source(five), Limits(zip_directory_bytes=size - 1))
    assert exc.value.detail["limit"] == "zip_directory_bytes"


def test_the_directory_zipfile_reads_is_bounded_and_counted_before_it_is_built(monkeypatch):
    pkg = _zip_bytes({"3D/3dmodel.model": b"<model/>", "a": b"a", "b": b"b"})
    monkeypatch.setattr(zipfile, "ZipInfo", _Built)
    # the ZIP64 record states one member over a directory of 15 entries: the entries are
    # counted from the bytes zipfile reads, before it builds one of them
    _Built.made = 0
    with pytest.raises(SldLimitError) as exc:
        src.SafeZip(src.Source(_zip64_end(pkg, 5, stated=1)), Limits(zip_members=10))
    assert exc.value.detail["limit"] == "zip_members" and _Built.made == 0
    # a directory longer than its bound is refused at zipfile's read, whatever the end
    # records were taken to say
    big = _zip_bytes({f"m{i}": b"x" for i in range(3000)})  # a directory of about 150 KB
    monkeypatch.setattr(src, "zip_directory_size", lambda _source: (1, 1))
    _Built.made = 0
    with pytest.raises(SldLimitError) as exc:
        src.SafeZip(src.Source(big), Limits(zip_directory_bytes=100_000))
    assert exc.value.detail["limit"] == "zip_directory_bytes" and _Built.made == 0
    # within the bounds, the same package opens, and its members read
    _Built.made = 0
    z = src.SafeZip(src.Source(big), Limits())
    assert _Built.made == 3000 and z.read("m2999") == b"x"
    assert src.central_entries(b"", 5) == 0 and src.central_entries(b"PK\x01\x02" + bytes(42), 5) == 1
    # some Python releases read the end record with read() and no size: that is the rest of
    # the file, held to the same bound
    f = src._PackageFile(src.Source(bytes(70_000)), Limits(zip_directory_bytes=1))
    f.seek(-22, 2)
    assert f.read() == bytes(22)
    f.seek(0)
    with pytest.raises(SldLimitError):
        f.read()
    f.opening = False
    assert len(f.read()) == 70_000


@pytest.mark.parametrize(
    ("source", "target", "expected"),
    [
        ("", "/3D/3dmodel.model", "3D/3dmodel.model"),
        ("3D/3dmodel.model", "parts/p.model", "3D/parts/p.model"),
        ("3D/3dmodel.model", "../Metadata/t.png", "Metadata/t.png"),
        ("3D/3dmodel.model", "../../../etc", None),
        ("", "http://example.invalid/x", None),
        ("", "a\\b", None),
        ("", "/a%20b.png#frag", "a b.png"),
    ],
)
def test_opc_resolve(source, target, expected):
    assert src.opc_resolve(source, target) == expected


def test_xml_is_parsed_without_doctypes_or_entities():
    lim = Limits()
    tree = src.xml_tree(b'<a xmlns="urn:x" k="v"><b>text</b><b/></a>', lim)
    assert tree.tag == "{urn:x}a" and tree.attrs == {"k": "v"}
    assert [c.text for c in tree.findall("{urn:x}b")] == ["text", ""]
    for bad in (
        b'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY e "x">]><a>&e;</a>',
        b'<!DOCTYPE a SYSTEM "http://example.invalid/a.dtd"><a/>',
        b"<a><b></a>",
    ):
        with pytest.raises(SldFormatError):
            src.xml_tree(bad, lim)
    with pytest.raises(SldFormatError):
        src.xml_tree(b"<a>" * 100 + b"</a>" * 100, lim)
    with pytest.raises(SldLimitError):
        src.xml_tree(b'<a k="' + b"x" * 70000 + b'"/>', lim)
    with pytest.raises(SldLimitError):
        src.xml_tree(b"<a>" + b"x" * 70000 + b"</a>", lim)
    many = b"<v>" + b"<x/>" * 100_000 + b"</v>"  # whitespace and tails never pile up
    assert sum(1 for e in src.xml_events([many], lim) if e[0] == "start") == 100_001


@pytest.mark.parametrize("encoding", [b"x-unknown", b"shift_jis"])
def test_an_xml_encoding_python_cannot_read_is_a_format_error(encoding):
    data = b'<?xml version="1.0" encoding="' + encoding + b'"?><a/>'
    with pytest.raises(SldFormatError):
        src.xml_tree(data, Limits())


def test_json_is_strict_and_bounded():
    lim = Limits()
    assert src.load_json(b'{"a": [1, 2.5, "x"]}', lim) == {"a": [1, 2.5, "x"]}
    for bad in (b'{"a": NaN}', b"[Infinity]", b"{", b"\xff"):
        with pytest.raises(SldFormatError):
            src.load_json(bad, lim)
    with pytest.raises(SldFormatError):
        src.load_json(b"[" * 100 + b"]" * 100, lim)
    with pytest.raises(SldFormatError):
        src.load_json(b"[" * 100_000 + b"]" * 100_000, lim)
    with pytest.raises(SldLimitError):
        src.load_json(b"[1]", Limits(json_bytes=2))



def test_json_numbers_too_large_for_a_double_are_refused():
    for bad in (b"[1e999]", b'{"a": -1e999}', b"[1.5e400]"):
        with pytest.raises(SldFormatError) as exc:
            src.load_json(bad, Limits())
        assert "too large" in str(exc.value)
    assert src.load_json(b"[1.7e308, -1e-400, 1e2]", Limits()) == [1.7e308, -0.0, 100.0]


def test_a_small_xml_tree_has_a_limit_of_its_own():
    lim = Limits(xml_nodes=3)
    assert len(src.xml_tree(b"<a><b/><b/></a>", lim).children) == 2
    with pytest.raises(SldLimitError) as exc:
        src.xml_tree(b"<a><b/><b/><b/></a>", lim)
    assert exc.value.detail == {"limit": "xml_nodes"}
    with pytest.raises(SldLimitError):  # a caller's own bound wins
        src.xml_tree(b"<a><b/></a>", Limits(), max_nodes=1)
    assert Limits().xml_nodes == 100_000

@pytest.mark.parametrize(
    "uri",
    [
        "../x.bin",
        "/x.bin",
        "C:/x.bin",
        "\\\\host\\share\\x",
        "a/../../x",
        "file:x.bin",
        "x.bin:ads",
        "NUL.bin",
        "a//b",
        "",
        "x\x01",
    ],
)
def test_sibling_references_that_leave_the_folder_are_refused(tmp_path, uri):
    with pytest.raises(PathRefusedError) as exc:
        src.sibling_path(str(tmp_path), uri)
    assert exc.value.detail["rule"] == "outside_document_folder"


def test_siblings_are_read_inside_the_folder_and_counted(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b 1.bin").write_bytes(b"abc")
    doc = str(tmp_path / "m.gltf")
    budget = src.SiblingBudget(Limits(siblings=1, sibling_bytes=10))
    assert src.read_sibling(doc, "sub/b%201.bin", budget) == b"abc"
    with pytest.raises(SldLimitError):
        src.read_sibling(doc, "sub/b%201.bin", budget)
    (tmp_path / "big.bin").write_bytes(b"x" * 11)
    with pytest.raises(SldLimitError):
        src.read_sibling(doc, "big.bin", src.SiblingBudget(Limits(sibling_bytes=10)))
    with pytest.raises(SldFormatError):
        src.read_sibling(None, "big.bin", src.SiblingBudget(Limits()))


def test_siblings_are_bounded_in_total_with_every_read_counted(tmp_path):
    (tmp_path / "b.bin").write_bytes(b"x" * 400)
    doc = str(tmp_path / "m.gltf")
    budget = src.SiblingBudget(Limits(sibling_total_bytes=1000))
    assert src.read_sibling(doc, "b.bin", budget) == b"x" * 400
    assert src.read_sibling(doc, "b.bin", budget) == b"x" * 400  # one file named twice counts twice
    with pytest.raises(SldLimitError) as exc:
        src.read_sibling(doc, "b.bin", budget)
    assert exc.value.detail == {"limit": "sibling_total_bytes", "value": 1200} and budget.bytes == 800
    assert Limits().sibling_total_bytes == 2 << 30



def test_a_document_opened_without_subfolders_reads_files_beside_it_only(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.bin").write_bytes(b"below")
    (tmp_path / "b.bin").write_bytes(b"beside")
    doc = str(tmp_path / "m.gltf")
    flat = src.SiblingBudget(Limits(), subfolders=False)
    assert src.read_sibling(doc, "b.bin", flat) == b"beside"
    with pytest.raises(PathRefusedError) as exc:
        src.read_sibling(doc, "sub/b.bin", flat)
    assert exc.value.detail == {"rule": "subfolder"}
    assert src.read_sibling(doc, "sub/b.bin", src.SiblingBudget(Limits())) == b"below"
    assert src.sibling_resolution(doc, "sub/b.bin")["status"] == "found"
    assert src.sibling_resolution(doc, "sub/b.bin", subfolders=False)["status"] == "refused"
    assert src.sibling_resolution(doc, "b.bin", subfolders=False)["status"] == "found"
    # how a document was opened travels with its Source to the budget
    source, _path, _info = src.open_source(tmp_path / "b.bin", limits=Limits(), subfolders=False)
    assert source.subfolders is False and src.SiblingBudget.of(source, Limits()).subfolders is False

def _folder_link(target, link) -> None:
    """A junction on Windows (no extra rights needed), a symbolic link elsewhere."""
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def test_siblings_keep_the_rules_the_document_was_opened_with(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "b.bin").write_bytes(b"outside")
    os.link(outside / "b.bin", root / "b.bin")  # a second name inside the folder
    doc = str(root / "m.gltf")
    assert src.read_sibling(doc, "b.bin", src.SiblingBudget(Limits())) == b"outside"  # not asked to refuse
    with pytest.raises(LinkRefusedError) as exc:
        src.read_sibling(doc, "b.bin", src.SiblingBudget(Limits(), refuse_hard_links=True))
    assert exc.value.detail == {"rule": "hard_link"}
    (root / "big.bin").write_bytes(b"x" * 20)
    with pytest.raises(FileTooLargeError):
        src.read_sibling(doc, "big.bin", src.SiblingBudget(Limits(), max_file_bytes=10))
    # a document's Source says how it was opened, and the budget takes that over
    source, _path, _info = src.open_source(
        root / "big.bin", refuse_hard_links=True, max_file_bytes=100, limits=Limits()
    )
    budget = src.SiblingBudget.of(source, Limits())
    assert (budget.refuse_hard_links, budget.max_file_bytes) == (True, 100)


def test_sibling_resolution_is_relative_and_never_goes_through_a_link(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    (root / "sub").mkdir(parents=True)
    outside.mkdir()
    (root / "sub" / "b.bin").write_bytes(b"in")
    (outside / "o.bin").write_bytes(b"out")
    doc = str(root / "m.obj")
    found = src.sibling_resolution(doc, "sub/b.bin")
    assert found == {"status": "found", "path": "sub/b.bin", "found_by": "relative_path", "version": None}
    assert src.sibling_resolution(doc, "sub/none.bin")["status"] == "not_found"
    assert src.sibling_resolution(doc, "../outside/o.bin")["status"] == "refused"
    assert src.sibling_resolution(doc, "sub")["status"] == "refused"  # a folder is no file
    assert src.sibling_resolution(None, "sub/b.bin")["status"] == "not_found"
    _folder_link(outside, root / "jn")
    try:
        assert (root / "jn" / "o.bin").is_file()  # control: the link leads to a file outside
        assert src.sibling_resolution(doc, "jn/o.bin") == {
            "status": "refused",
            "path": None,
            "found_by": None,
            "version": None,
        }
    finally:
        os.rmdir(root / "jn") if os.name == "nt" else os.unlink(root / "jn")
    os.link(outside / "o.bin", root / "hard.bin")
    assert src.sibling_resolution(doc, "hard.bin")["status"] == "found"
    assert src.sibling_resolution(doc, "hard.bin", refuse_hard_links=True)["status"] == "refused"


def _png(width=4, height=3, channels=4) -> bytes:
    return src.encode_png(width, height, bytes(range(width * height * channels)), channels)


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def test_png_sanitising():
    lim = Limits()
    png = _png()
    out, w, h = src.sanitize_png(png + b"trailing bytes", lim)
    assert (w, h) == (4, 3) and out.startswith(src.PNG_SIGNATURE)
    assert zlib.decompress(out[out.index(b"IDAT") + 4 : -16]) == zlib.decompress(
        png[png.index(b"IDAT") + 4 : -16]
    )
    text = png[:33] + _chunk(b"tEXt", b"Author\0someone") + png[33:]
    assert b"tEXt" not in src.sanitize_png(text, lim)[0]  # only header, palette, transparency and pixels
    bad_crc = bytearray(png)
    bad_crc[30] ^= 1
    big = src.PNG_SIGNATURE + _chunk(b"IHDR", struct.pack(">IIBBBBB", 5000, 1, 8, 2, 0, 0, 0))
    short = src.PNG_SIGNATURE + _chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 3, 8, 6, 0, 0, 0))
    short += _chunk(b"IDAT", zlib.compress(b"\0" * 10)) + _chunk(b"IEND", b"")
    bomb = src.PNG_SIGNATURE + _chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 3, 8, 6, 0, 0, 0))
    bomb += _chunk(b"IDAT", zlib.compress(b"\0" * 10_000_000)) + _chunk(b"IEND", b"")
    bad_filter = src.PNG_SIGNATURE + _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
    bad_filter += _chunk(b"IDAT", zlib.compress(b"\x07\x00")) + _chunk(b"IEND", b"")
    for bad in (b"not a png", bytes(bad_crc), big + _chunk(b"IEND", b""), short, bomb, bad_filter, png[:-12]):
        with pytest.raises(SldFormatError):
            src.sanitize_png(bad, lim)


def _bmp(
    width: int, height: int, bpp: int = 24, *, claimed: int | None = None, compression: int = 0
) -> bytes:
    stride = ((width * bpp + 31) // 32) * 4
    pixels = bytearray(stride * abs(height))
    for y in range(abs(height)):
        for x in range(width):
            o = y * stride + x * (bpp // 8)
            pixels[o : o + 3] = bytes((x * 10 % 256, y * 20 % 256, 200))  # B, G, R
    size = 54 + len(pixels)
    header = b"BM" + struct.pack("<IHHI", claimed if claimed is not None else size, 0, 0, 54)
    info = struct.pack("<IiiHHIIiiII", 40, width, height, 1, bpp, compression, len(pixels), 0, 0, 0, 0)
    return header + info + bytes(pixels)


@pytest.mark.parametrize(("bpp", "height"), [(24, 3), (32, 3), (24, -3)])
def test_bitmaps_become_pngs(bpp, height):
    png, w, h = src.bmp_to_png(_bmp(5, height, bpp), Limits())
    assert (w, h) == (5, 3)
    again, _w, _h = src.sanitize_png(png, Limits())  # what SolidSeas writes passes its own checks
    raw = zlib.decompress(png[png.index(b"IDAT") + 4 : -16])
    # the first pixel of the top row: bottom-up storage puts it on the last stored row
    stored_row = 0 if height < 0 else 2
    assert raw[1:4] == bytes((200, stored_row * 20, 0))


def test_hostile_bitmaps_are_refused():
    for bad in (
        _bmp(5, 3, 24, claimed=10**9),
        _bmp(5, 3, 16),
        _bmp(5, 3, 24, compression=1),
        _bmp(5000, 3),
        _bmp(5, 3)[:70],
        b"BM" + b"\0" * 10,
    ):
        with pytest.raises(SldFormatError):
            src.bmp_to_png(bad, Limits())


def test_preview_png_passes_only_images_solidseas_wrote():
    from solidseas.formats.solidworks import Preview

    assert src.preview_png(None, Limits()) is None
    assert src.preview_png(Preview(b"\xff\xd8jpeg", "image/jpeg", 1, 1, "x"), Limits()) is None
    png, w, h, stream = src.preview_png(Preview(_bmp(5, 3), "image/bmp", 5, 3, "PROP_DATA"), Limits())
    assert (w, h, stream) == (5, 3, "PROP_DATA") and png.startswith(src.PNG_SIGNATURE)


# --------------------------------------------------------------------------- JSON of model files
def test_model_summary_matches_its_schema_and_the_python_call():
    with open_model(fixture_path("o02_boxA.STL")) as doc:
        data = model.build_model_summary(doc, include=model.MODEL_SUMMARY_PARTS)
        assert doc.summary() == model.build_model_summary(doc)
    env = model.envelope("model_summary", data)
    assert validate(env, model.envelope_schema("model_summary"), strict=True) == []
    assert data["counts"]["triangles"] == 12 and data["references"] == [] and data["tree"]["nodes"]
    assert data["preview"]["renderable"] and not data["preview"]["available"]
    with pytest.raises(InvalidArgumentError):
        model.build_model_summary(doc, include=("nope",))


def test_model_summary_of_a_placed_coloured_scene():
    doc = scene_document(two_object_assembly())
    data = model.build_model_summary(doc, include=model.MODEL_SUMMARY_PARTS)
    assert (
        validate(model.envelope("model_summary", data), model.envelope_schema("model_summary"), strict=True)
        == []
    )
    assert [n["kind"] for n in data["tree"]["nodes"]] == ["assembly", "component", "component", "component"]
    assert data["doc_type"] == "assembly" and data["units"]["source"] == "file"


def test_model_properties_and_configurations():
    with open_model(fixture_path("o02_boxA.STL")) as doc:
        props = model.build_properties(doc)
        assert props["view"] == "effective" and [p["name"] for p in props["properties"]] == ["header"]
        assert model.build_properties(doc, view="configuration")["properties"] == []
        assert model.build_configurations(doc) == {
            "active_configuration": None,
            "configurations": [],
            "warnings": [],
        }
        with pytest.raises(InvalidArgumentError):
            model.build_properties(doc, nested="x")
        from solidseas.errors import ConfigurationNotFoundError

        with pytest.raises(ConfigurationNotFoundError):
            model.build_properties(doc, configuration="Default")


def test_listing_entries_of_model_files(tmp_path):
    from solidseas.formats.solidworks import Preview

    with open_model(fixture_path("o02_boxA.STL")) as doc:
        entry, image = model.model_listing_entry("o02_boxA.STL", doc, ("properties", "preview"))
    assert entry["status"] == "ok" and entry["format"] is None and entry["saved_version"] is None
    assert entry["model"]["format"] == "stl" and entry["model"]["readable"] and image is None
    assert entry["preview"]["reason"] == "not_stored"
    doc = scene_document(two_object_assembly())
    doc._preview = lambda: Preview(_bmp(6, 4), "image/bmp", 6, 4, "PROP_DATA")
    entry, image = model.model_listing_entry("s.stl", doc, ("preview_data",))
    assert entry["preview"]["mime"] == "image/png" and (
        entry["preview"]["width"],
        entry["preview"]["height"],
    ) == (6, 4)
    assert image.startswith(src.PNG_SIGNATURE) and entry["preview"]["bytes"] == len(image)
    doc._preview = lambda: Preview(b"BM broken", "image/bmp", 6, 4, "PROP_DATA")
    entry, image = model.model_listing_entry("s.stl", doc, ("preview",))
    assert image is None and entry["preview"]["reason"] == "undecodable"
    assert "preview_undecodable" in {w["code"] for w in entry["warnings"]}
    unsupported = model.unsupported_entry("p.step", None, FORMATS["step"])
    assert unsupported["status"] == "unsupported" and unsupported["detected"] == "step"
    assert unsupported["model"]["readable"] is False


def test_the_new_error_and_warning_codes_are_registered():
    spec = model.ERROR_CODES["format_not_supported"]
    assert (spec.http_status, spec.cli_exit, spec.retryable) == (422, 1, False)
    for code in (
        "units_assumed",
        "extension_mismatch",
        "non_rigid_transform",
        "degenerate_triangles_dropped",
        "indices_out_of_range",
        "colors_ignored",
        "text_truncated",
        "component_not_found",
    ):
        assert code in WARNING_CODES


# --------------------------------------------------------------------------- export of model files
def test_a_placed_coloured_scene_exports_as_objects_and_items(tmp_path):
    doc = scene_document(two_object_assembly())
    pm = export.print_model(doc)
    assert pm.source_format == "stl" and pm.doc_type == "assembly" and pm.closed
    assert pm.counts == {"objects": 2, "items": 3, "vertices": 24, "triangles": 56, "placed": 3, "skipped": 0}
    assert pm.measures()["volume_m3"] == pytest.approx(20000e-9, rel=1e-9)
    assert [o.source for o in pm.objects] == ["mesh", "mesh"]
    result = export.write_export(pm, tmp_path / "s.3mf", "3mf")
    data = model.build_export_result(result)
    assert data["source_format"] == "stl"
    assert (
        validate(model.envelope("export_result", data), model.envelope_schema("export_result"), strict=True)
        == []
    )
    with zipfile.ZipFile(tmp_path / "s.3mf") as z:
        xml = z.read("3D/3dmodel.model").decode()
    assert xml.count("<item ") == 3 and xml.count("<object ") == 2 and "transform=" in xml


def test_export_leaves_out_what_cannot_be_placed():
    scene = Scene([box(1, 1, 1), holed_block()], [Item(0), Item(1, translation_mm=(5e9, 0.0, 0.0))])
    doc = scene_document(scene)
    pm = export.print_model(doc)
    assert pm.counts["items"] == 1 and pm.counts["skipped"] == 1
    assert pm.skipped[0].reason == "out_of_range"
    assert "instances_left_out" in {w.code for w in pm.warnings}
    with pytest.raises(Exception) as exc:
        export.print_model(doc, "Default")
    assert model.error_code(exc.value) == "configuration_not_found"


@pytest.mark.parametrize("value", ["1e300", "-1e300", "1.E300", "1e12"])
def test_a_corner_far_out_never_overflows_the_export(tmp_path, value):
    """An OFF block with one corner moved out (the welding's squares overflowed at 1e300,
    an internal error on every export surface): its triangles are left out, the rest of
    the block exports."""
    lines = mw.off(box(10, 20, 30)).decode().splitlines()
    first = next(i for i, line in enumerate(lines) if len(line.split()) == 3 and line[0] in "-0123456789")
    lines[first + 1] = f"{value} 0.0 0.0"  # the first vertex (after the counts line)
    (tmp_path / "far.off").write_text("\n".join(lines) + "\n")
    with open_model(tmp_path / "far.off") as doc:
        pm = export.print_model(doc)
        assert "coordinates_out_of_range" in {w.code for o in pm.objects for w in o.warnings}
        assert 0 < pm.counts["triangles"] < 12
    result = export.write_export(pm, tmp_path / "far.stl", "stl")
    assert result.bytes == 84 + 50 * pm.counts["triangles"]


def test_placed_triangles_are_bounded_for_model_files():
    """One small mesh placed many times passes the triangles read, not those placed."""
    items = [Item(0, translation_mm=(2.0 * k, 0.0, 0.0)) for k in range(50)]
    doc = scene_document(Scene([box(1, 1, 1)], items))
    assert export.print_model(doc, max_triangles=600).counts["triangles"] == 600
    with pytest.raises(SldLimitError) as exc:
        export.print_model(doc, max_triangles=599)
    assert exc.value.detail == {"limit": "max_triangles"}


def test_export_of_an_ascii_stl_keeps_one_object_per_solid():
    with open_model(stl_ascii(two_object_assembly()), name="a.stl") as doc:
        pm = export.print_model(doc)
    assert [o.name for o in pm.objects] == ["box 1", "box 2", "block 1"] and pm.closed
    assert json.loads(model.dumps(model.build_export_result(export.ExportResult("x", "stl", 0, True, pm))))


def test_mesh_objects_measure_themselves():
    sb = _builder()
    mb = sb.mesh(scale_m=0.001)
    m = box(10, 20, 30)
    mb.add_vertices(c for p in m.vertices for c in p)
    mb.add_triangles(i for t in m.triangles for i in t)
    obj = mb.build()
    assert isinstance(obj, MeshObject) and obj.measures()["volume_m3"] == pytest.approx(6e-6)
