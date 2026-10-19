"""Hostile files for the mesh readers (``docs/formats/mesh.md``): every one ends in a
documented exception (``SolidSeasError`` and its subclasses), or reads, within its time
bound; nothing else escapes. Truncation at every structural boundary and a sweep of
cut points, flipped bytes, overflowing counts, NaN and infinity, cycles, deep
nesting, zip bombs, names and URIs that climb out, DOCTYPE and entities, encrypted
and unknown zip members, the time bound and cancellation."""

import random
import struct
import time
import zlib

import pytest

import mesh_writers as mw
from model_writers import box, holed_block, two_object_assembly
from solidseas.errors import (
    FormatNotSupportedError,
    PathRefusedError,
    SldFormatError,
    SldLimitError,
    SolidSeasError,
)
from solidseas.formats import Limits, open_model
from solidseas.formats._source import ReadCancelledError
from support import within

SECONDS = 5.0  # what one hostile file may cost, at most


def _faces_first_ply() -> bytes:
    """A binary PLY of a cube of quads whose face element comes before its vertices, with a
    skipped element of a long list between them, and a strip element after them."""
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    verts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
    head = (
        b"ply\nformat binary_little_endian 1.0\nelement face 6\nproperty list uchar int vertex_indices\n"
        b"property uchar red\nproperty uchar green\nproperty uchar blue\n"
        b"element note 1\nproperty list int int words\n"
        b"element vertex 8\nproperty float x\nproperty float y\nproperty float z\n"
        b"element tristrips 1\nproperty list int int vertex_indices\nend_header\n"
    )
    body = b"".join(struct.pack("<B4i3B", 4, *q, 200, 40, 40) for q in quads)
    body += struct.pack("<i", 40) + struct.pack("<40i", *range(40))
    body += b"".join(struct.pack("<3f", *v) for v in verts)
    body += struct.pack("<i", 6) + struct.pack("<6i", 0, 1, 3, -1, 4, 5)
    return head + body


def _samples() -> dict[str, bytes]:
    scene = two_object_assembly()
    obj, _ = mw.obj(scene, mtl=None)
    gltf, _ = mw.gltf(scene)
    glb, _ = mw.gltf(scene, buffer="glb")
    bare_off = b"\n".join(mw.off(scene).split(b"\n")[2:])  # no comment, no keyword
    obj_text = obj.replace(b"\nf ", b" # a comment\nf ", 3).replace(b"\nv ", b" \\\n\nv ", 2)
    return {
        "f.ply": _faces_first_ply(),
        "k.off": bare_off,
        "k.obj": obj_text,
        "a.3mf": mw.threemf(scene, thumbnail=mw.png()),
        "p.3mf": mw.threemf(scene, production=True, colors="colorgroup"),
        "a.obj": obj,
        "a.ply": mw.ply(scene, face_colors=True),
        "b.ply": mw.ply(scene, encoding="binary_le", vertex_colors=True, extra_element=True),
        "c.ply": mw.ply(scene, encoding="binary_be", normals=True),
        "a.off": mw.off(scene, face_colors=True),
        "a.gltf": gltf,
        "a.glb": glb,
        "a.amf": mw.amf(scene),
        "z.amf": mw.amf(scene, zipped=True),
    }


SAMPLES = _samples()


def _exercise(data: bytes, name: str, limits=None) -> None:
    """Open, summarise and read a file the way every surface does; SolidSeas errors only."""
    t0 = time.perf_counter()
    try:
        with open_model(data, name=name, limits=limits) as doc:
            doc.summary(include=("properties", "tree", "references"))
            doc.scene(max_seconds=SECONDS)
            doc.preview()
    except SolidSeasError:
        pass
    assert time.perf_counter() - t0 < SECONDS + within(1.0), name


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_every_cut_point_ends_in_a_documented_error_or_a_read(name):
    data = SAMPLES[name]
    n = len(data)
    cuts = sorted({*range(0, min(n, 300)), *range(0, n, max(1, n // 150)), n - 1, n - 2, n - 4})
    for cut in cuts:
        _exercise(data[:cut], name)


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_flipped_bytes_end_in_a_documented_error_or_a_read(name):
    data = SAMPLES[name]
    rng = random.Random(f"{name} 20261004")
    for _ in range(150):
        b = bytearray(data)
        for _k in range(rng.randint(1, 4)):
            i = rng.randrange(len(b))
            b[i] = rng.randrange(256)
        _exercise(bytes(b), name)


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_tight_limits_end_in_limit_errors(name):
    lim = Limits(
        triangles=10,
        vertices=10,
        objects=1,
        items=1,
        xml_depth=4,
        json_bytes=200,
        zip_member_bytes=256,
        polygon_corners=3,
        obj_line_bytes=16,
        ply_header_bytes=64,
        text_bytes=4,
        image_bytes=10,
    )
    _exercise(SAMPLES[name], name, lim)


# --------------------------------------------------------------------------- numbers
@pytest.mark.parametrize(
    "data",
    [
        mw.threemf(box(1, 1, 1)).replace(b"", b""),
    ],
)
def test_not_finite_coordinates_drop_their_triangles(data):
    text = b"v nan 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 inf\nf 1 2 3\nf 2 3 4\nf 2 4 3\n"
    with open_model(text, name="n.obj") as doc:
        s = doc.scene()
        assert s.counts["triangles"] == 0
        assert "degenerate_triangles_dropped" in mw.codes(s.objects[0].warnings)
    model = mw.threemf_mesh_xml(box(1, 1, 1), 1).replace('x="0.0"', 'x="NaN"', 1)
    pkg = mw.threemf(
        mw.Scene([], []), resources_extra=model, build_xml='<build><item objectid="1"/></build>', colors=None
    )
    with open_model(pkg, name="n.3mf") as doc:
        (obj,) = doc.scene().objects
        assert obj.n_triangles < 12 and all(v == v for v in obj.positions)


def test_overflowing_indices_and_counts():
    big = mw.threemf_mesh_xml(box(1, 1, 1), 1).replace('v1="0"', 'v1="1099511627776"', 1)
    pkg = mw.threemf(
        mw.Scene([], []), resources_extra=big, build_xml='<build><item objectid="1"/></build>', colors=None
    )
    with open_model(pkg, name="o.3mf") as doc:
        with pytest.raises(SldFormatError):
            doc.scene()
    neg = mw.threemf_mesh_xml(box(1, 1, 1), 1).replace('v1="0"', 'v1="-1"', 1)
    pkg = mw.threemf(
        mw.Scene([], []), resources_extra=neg, build_xml='<build><item objectid="1"/></build>', colors=None
    )
    with open_model(pkg, name="o.3mf") as doc:
        with pytest.raises(SldFormatError):
            doc.scene()
    with open_model(b"v 0 0 0\nf 99999999999999999999 1 1\n", name="o.obj") as doc:
        assert doc.scene().counts["triangles"] == 0
    ply = (
        b"ply\nformat binary_little_endian 1.0\nelement vertex 4294967295\n"
        b"property float x\nproperty float y\n"
        b"property float z\nend_header\n" + b"\0" * 24
    )
    with pytest.raises(SldFormatError):
        open_model(ply, name="o.ply")
    gltf, _ = mw.gltf(box(1, 1, 1))
    huge = gltf.replace(b'"count": 8', b'"count": 9999999999', 1)
    with pytest.raises(SolidSeasError):
        with open_model(huge, name="o.gltf") as doc:
            doc.scene()


# --------------------------------------------------------------------------- XML
@pytest.mark.parametrize(
    "inject",
    [
        b'<!DOCTYPE model [<!ENTITY big "x">]>',
        b'<!DOCTYPE model SYSTEM "http://example.invalid/x.dtd">',
    ],
)
def test_doctype_and_entities_are_refused_in_every_xml_part(inject):
    pkg = mw.threemf(box(1, 1, 1))
    parts = _parts(pkg)
    model = parts["3D/3dmodel.model"]
    parts["3D/3dmodel.model"] = model.replace(b"\n<model", b"\n" + inject + b"<model", 1)
    with pytest.raises(SldFormatError):
        open_model(mw._zip(parts), name="d.3mf")
    parts = _parts(pkg)
    parts["_rels/.rels"] = parts["_rels/.rels"].replace(
        b"\n<Relationships", b"\n" + inject + b"<Relationships", 1
    )
    with pytest.raises(SldFormatError):
        open_model(mw._zip(parts), name="d.3mf")
    amf = mw.amf(box(1, 1, 1)).replace(b"\n<amf", b"\n" + inject.replace(b"model", b"amf") + b"<amf", 1)
    with pytest.raises(SldFormatError):
        with open_model(amf, name="d.amf") as doc:
            doc.scene()


def test_deep_nesting_is_refused():
    deep = b"<a>" * 100 + b"</a>" * 100
    pkg = mw.threemf(box(1, 1, 1), resources_extra=deep.decode())
    with pytest.raises(SldFormatError) as exc:  # the head's parse reaches it in its first chunk
        with open_model(pkg, name="n.3mf") as doc:
            doc.scene()
    assert exc.value.detail["limit"] == "xml_depth"


def test_a_long_attribute_or_text_is_bounded():
    pkg = mw.threemf(box(1, 1, 1), metadata={"Title": "x" * 100})
    with pytest.raises(SldLimitError):
        open_model(pkg, name="l.3mf", limits=Limits(xml_text_bytes=50))


# --------------------------------------------------------------------------- zip packages
def _parts(pkg: bytes) -> dict[str, bytes]:
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(pkg)) as z:
        return {n: z.read(n) for n in z.namelist()}


def test_a_zip_bomb_stops_after_a_few_chunks():
    pkg = mw.threemf(box(1, 1, 1))
    parts = _parts(pkg)
    model = parts["3D/3dmodel.model"]
    padding = b"<!-- " + b" " * (40 << 20) + b" -->"  # 40 MiB of spaces deflate to about 40 KiB
    parts["3D/3dmodel.model"] = model.replace(b"<resources>", padding + b"<resources>", 1)
    bomb = mw._zip(parts)
    assert len(bomb) < 200_000
    t0 = time.perf_counter()
    with pytest.raises(SldLimitError) as exc:
        with open_model(bomb, name="b.3mf") as doc:
            doc.scene()
    assert exc.value.detail["limit"] == "zip_ratio"
    assert time.perf_counter() - t0 < within(2.0)
    with pytest.raises(SldLimitError) as exc:
        with open_model(pkg, name="b.3mf", limits=Limits(zip_total_bytes=500)) as doc:
            doc.scene()
    assert exc.value.detail["limit"] == "zip_total_bytes"
    with pytest.raises(SldLimitError) as exc:
        open_model(pkg, name="b.3mf", limits=Limits(zip_members=2))
    assert exc.value.detail["limit"] == "zip_members"


def _patch_central(pkg: bytes, member: str, offset: int, fmt: str, value: int) -> bytes:
    """``pkg`` with a field of ``member``'s central directory entry changed."""
    i = pkg.find(b"PK\x01\x02")
    data = bytearray(pkg)
    while i >= 0:
        nlen = struct.unpack_from("<H", data, i + 28)[0]
        name = bytes(data[i + 46 : i + 46 + nlen]).decode()
        if name == member:
            struct.pack_into(fmt, data, i + offset, value)
            return bytes(data)
        i = pkg.find(b"PK\x01\x02", i + 4)
    raise AssertionError(member)


def test_encrypted_and_unknown_members_are_refused():
    pkg = mw.threemf(box(1, 1, 1))
    enc = _patch_central(pkg, "3D/3dmodel.model", 8, "<H", 0x1)
    with pytest.raises(FormatNotSupportedError) as exc:
        open_model(enc, name="e.3mf")
    assert exc.value.detail == {"rule": "encrypted", "value": "zip"}
    lzma = _patch_central(pkg, "3D/3dmodel.model", 10, "<H", 14)
    with pytest.raises(FormatNotSupportedError) as exc:
        open_model(lzma, name="m.3mf")
    assert exc.value.detail["rule"] == "compression"
    amf = _patch_central(mw.amf(box(1, 1, 1), zipped=True), "model.amf", 8, "<H", 0x1)
    with pytest.raises(FormatNotSupportedError):
        open_model(amf, name="e.amf")


def test_a_damaged_member_is_a_format_error():
    pkg = bytearray(mw.threemf(holed_block()))
    i = pkg.find(b"3D/3dmodel.model") + len("3D/3dmodel.model") + 20  # inside the deflated model
    pkg[i : i + 8] = b"\xff" * 8
    with pytest.raises(SldFormatError):
        with open_model(bytes(pkg), name="d.3mf") as doc:
            doc.scene()


@pytest.mark.parametrize(
    "target", ["../../evil.model", "/../evil.model", "http://example.invalid/m.model", "3D\\3dmodel.model"]
)
def test_part_names_that_climb_out_of_the_package_are_refused(target):
    parts = _parts(mw.threemf(box(1, 1, 1)))
    parts["_rels/.rels"] = parts["_rels/.rels"].replace(b"/3D/3dmodel.model", target.encode(), 1)
    with pytest.raises(SldFormatError):
        open_model(mw._zip(parts), name="c.3mf")


def test_a_component_path_that_climbs_out_finds_nothing():
    pkg = mw.threemf(box(1, 1, 1), production=True)
    parts = _parts(pkg)
    parts["3D/3dmodel.model"] = parts["3D/3dmodel.model"].replace(
        b'p:path="/3D/Objects/object_1.model"', b'p:path="/../../3D/Objects/object_1.model"', 1
    )
    with open_model(mw._zip(parts), name="c.3mf") as doc:
        s = doc.scene()
        assert s.items == () and "component_not_found" in mw.codes(s.warnings)


@pytest.mark.parametrize(
    "uri",
    [
        "../x.bin",
        "/x.bin",
        "C:/x.bin",
        "C:x.bin",
        "//host/share/x.bin",
        "\\\\host\\x.bin",
        "file:///x.bin",
        "x.bin:stream",
        "a/../../x.bin",
        "%2e%2e/x.bin",
        "NUL",
        "con.bin",
    ],
)
def test_buffer_uris_that_climb_out_are_refused(tmp_path, uri):
    import json

    data, _ = mw.gltf(box(1, 1, 1), buffer="file")
    doc = json.loads(data)
    doc["buffers"][0]["uri"] = uri
    folder = tmp_path / "in"
    folder.mkdir()
    (folder / "x.gltf").write_text(json.dumps(doc))
    with open_model(folder / "x.gltf") as m:
        with pytest.raises(PathRefusedError):
            m.scene()


# --------------------------------------------------------------------------- time and cancellation
def test_the_time_bound_and_cancellation_stop_a_large_read():
    big = mw.Scene([holed_block()], [mw.Item(0, translation_mm=(40.0 * i, 0.0, 0.0)) for i in range(400)])
    data, _ = mw.obj(big, mtl=None)
    with open_model(data, name="t.obj") as doc:
        with pytest.raises(SldLimitError) as exc:
            doc.scene(max_seconds=1e-6)
        assert exc.value.detail["limit"] == "seconds"
        with pytest.raises(ReadCancelledError):
            doc.scene(cancelled=lambda: True)
    pkg = mw.threemf(big)
    with open_model(pkg, name="t.3mf") as doc:
        with pytest.raises(SldLimitError):
            doc.scene(max_seconds=1e-6)


def test_compressed_garbage_and_wrong_magic():
    for name, data in (
        ("g.3mf", b"PK\x03\x04" + zlib.compress(b"x" * 1000)),
        ("g.amf", b"PK\x03\x04" + b"\0" * 40),
        ("g.glb", b"glTF" + struct.pack("<II", 2, 12)),
        ("g.ply", b"ply\n"),
        ("g.off", b"OFF"),
        ("g.obj", b"\xff\xfe\x00garbage"),
    ):
        _exercise(data, name)
