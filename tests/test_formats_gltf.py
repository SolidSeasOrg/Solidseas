"""The glTF 2.0 and GLB reader (``docs/formats/mesh.md``): the neutral scene in every
buffer form, the node hierarchy and the turn to Z up, accessors (strides, sparse,
quantised), drawing modes, compression and required extensions, and buffers beside
the file."""

import base64
import json
import os
import struct
import sys
import tracemalloc

import pytest

import mesh_writers as mw
from model_writers import QUARTER_Z, Item, Scene, box, holed_block, two_object_assembly
from solidseas import export
from solidseas.errors import (
    FileTooLargeError,
    FormatNotSupportedError,
    LinkRefusedError,
    PathRefusedError,
    SldFormatError,
    SldLimitError,
)
from solidseas.formats import Limits, open_model
from solidseas.formats.gltf import Z_UP
from solidseas.formats.solidworks.components import Placement

TRIANGLE = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)  # in the z = 0 plane of glTF: x, y up


def _asset(prims, blob: bytes, *, nodes=None, extra=None, accessors=None, views=None) -> bytes:
    """A small glTF with one mesh of ``prims`` over a data-URI buffer holding ``blob``."""
    doc = {
        "asset": {"version": "2.0"},
        "scenes": [{"nodes": [0]}],
        "nodes": nodes or [{"mesh": 0}],
        "meshes": [{"primitives": prims}],
        "accessors": accessors or [],
        "bufferViews": views or [{"buffer": 0, "byteOffset": 0, "byteLength": len(blob)}],
        "buffers": [
            {
                "byteLength": len(blob),
                "uri": "data:application/octet-stream;base64," + base64.b64encode(blob).decode(),
            }
        ],
    }
    doc.update(extra or {})
    return json.dumps(doc).encode()


def _position(count: int, view: int = 0, offset: int = 0, **kw) -> dict:
    return {
        "bufferView": view,
        "byteOffset": offset,
        "componentType": 5126,
        "count": count,
        "type": "VEC3",
        **kw,
    }


@pytest.mark.parametrize("buffer", ["data", "file", "glb"])
def test_the_neutral_scene_reads_in_every_buffer_form(tmp_path, buffer):
    scene = two_object_assembly()
    data, sib = mw.gltf(scene, buffer=buffer)
    for k, v in sib.items():
        (tmp_path / k).write_bytes(v)
    path = tmp_path / ("s.glb" if buffer == "glb" else "s.gltf")
    path.write_bytes(data)
    with open_model(path) as doc:
        assert (doc.format, doc.variant, doc.doc_type, doc.kind) == (
            "gltf",
            "glb" if buffer == "glb" else "gltf",
            "assembly",
            "mesh",
        )
        assert doc.units == {"length": "m", "scale_m": 1.0, "source": "format"}
        assert doc.application == {"name": "Invented Writer", "version": "1.2.3"}
        assert {p.name for p in doc.properties} >= {"generator", "copyright", "version"}
        assert doc.counts() | {} == {
            **doc.counts(),
            "objects": 2,
            "items": 3,
            "triangles": 56,
            "vertices": 24,
        }
        s = doc.scene()
        assert mw.scene_volume(doc) == pytest.approx(20000e-9, rel=1e-6)
        assert [o.color for o in s.objects] == [(0.8, 0.1, 0.1, 1.0), (0.1, 0.2, 0.8, 1.0)]
        # Z up again: the 30 mm box stands 30 mm tall in Z wherever the item puts it
        for it in s.items[:2]:
            pts = [it.placement.apply(s.objects[0].positions[i : i + 3]) for i in range(0, 24, 3)]
            assert max(p[2] for p in pts) - min(p[2] for p in pts) == pytest.approx(0.030, abs=1e-6)
        # an object stays in glTF's own frame: its placement is the turn to Z up after the node's
        moved = s.items[1].placement
        assert moved.translation_m == pytest.approx((0.05, 0.0, 0.0), abs=1e-9)
        want = Placement(QUARTER_Z, (0.0, 0.0, 0.0)).then(Z_UP).rotation
        assert [list(r) for r in moved.rotation] == [pytest.approx(list(r), abs=1e-9) for r in want]
        nodes = doc.tree().nodes
        assert nodes[0].kind == "assembly" and [n.object for n in nodes[1:]] == [0, 0, 1]
        assert {it.instance for it in s.items} == {n.id for n in nodes[1:]}
        refs = doc.references()
        if buffer == "file":
            assert [(r.kind, r.stored, r.resolution["status"], r.resolution["path"]) for r in refs] == [
                ("buffer", "scene.bin", "found", "scene.bin")  # relative to the file's folder
            ]
        else:
            assert refs == []
        pm = export.print_model(doc)
    assert pm.closed


def test_one_placed_mesh_is_a_part_and_a_hierarchy_composes():
    data, _ = mw.gltf(box(1, 2, 3))
    with open_model(data, name="p.gltf") as doc:
        assert doc.doc_type == "part" and [n.parent for n in doc.tree().nodes] == [None]
    scene = Scene([holed_block()], [Item(0, QUARTER_Z, (5.0, 6.0, 7.0)), Item(0)])
    data, _ = mw.gltf(scene, hierarchy=True, buffer="glb")
    with open_model(data, name="h.glb") as doc:
        nodes = doc.tree().nodes
        assert [(n.id, n.parent, n.kind) for n in nodes] == [
            ("0", None, "assembly"),
            ("3", "0", "component"),
            ("1", "3", "object"),
            ("2", "3", "object"),
        ]
        s = doc.scene()
        assert s.items[0].placement.translation_m == pytest.approx((0.005, 0.006, 0.007), abs=1e-9)
        assert mw.scene_volume(doc) == pytest.approx(2 * holed_block().volume_mm3() * 1e-9, rel=1e-6)


def test_extras_name_the_fields():
    data, _ = mw.gltf(
        box(1, 1, 1), extras={"title": "Invented", "author": "Someone", "count": 3, "skip": [1]}
    )
    with open_model(data, name="e.gltf") as doc:
        assert (doc.fields.title, doc.fields.author) == ("Invented", "Someone")
        assert {p.name: p.value for p in doc.properties}["count"] == "3"


def test_strides_short_indices_and_trs_nodes():
    data, _ = mw.gltf(holed_block(), strided=True, short_indices=True)
    with open_model(data, name="s.gltf") as doc:
        assert mw.scene_volume(doc) == pytest.approx(holed_block().volume_mm3() * 1e-9, rel=1e-6)
    blob = TRIANGLE
    trs = [
        {"mesh": 0, "translation": [1, 2, 3], "rotation": [0, 0, 0.7071068, 0.7071068], "scale": [2, 2, 2]}
    ]
    data = _asset([{"attributes": {"POSITION": 0}}], blob, nodes=trs, accessors=[_position(3)])
    with open_model(data, name="t.gltf") as doc:
        s = doc.scene()
        p = s.items[0].placement
        # scaled to (2, 0, 0), turned to (0, 2, 0), moved to (1, 4, 3) in glTF's frame; Z up: (1, -3, 4)
        assert p.apply((1.0, 0.0, 0.0)) == pytest.approx((1.0, -3.0, 4.0), abs=1e-6)
        assert "non_rigid_transform" in mw.codes(s.warnings)


def test_strips_fans_points_and_lines():
    quad = struct.pack("<12f", 0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0)
    prims = [
        {"attributes": {"POSITION": 0}, "mode": 5},
        {"attributes": {"POSITION": 0}, "mode": 6},
        {"attributes": {"POSITION": 0}, "mode": 0},
        {"attributes": {"POSITION": 0}, "mode": 1},
    ]
    data = _asset(prims, quad, accessors=[_position(4)])
    with open_model(data, name="m.gltf") as doc:
        assert "primitives_skipped" in mw.codes(doc.warnings)
        s = doc.scene()
        strip, fan = s.objects
        assert list(strip.triangles) == [0, 1, 2, 2, 1, 3]
        assert list(fan.triangles) == [1, 2, 0, 2, 3, 0]
        assert strip.measures()["area_m2"] == pytest.approx(1.0)


def test_sparse_and_quantised_accessors():
    base = TRIANGLE
    idx = struct.pack("<H", 2) + b"\0\0"
    val = struct.pack("<3f", 0, 2, 0)
    blob = base + idx + val
    views = [
        {"buffer": 0, "byteOffset": 0, "byteLength": 36},
        {"buffer": 0, "byteOffset": 36, "byteLength": 4},
        {"buffer": 0, "byteOffset": 40, "byteLength": 12},
    ]
    sparse = {"count": 1, "indices": {"bufferView": 1, "componentType": 5123}, "values": {"bufferView": 2}}
    data = _asset(
        [{"attributes": {"POSITION": 0}}], blob, accessors=[_position(3, sparse=sparse)], views=views
    )
    with open_model(data, name="s.gltf") as doc:
        (obj,) = doc.scene().objects
        assert list(obj.positions[6:9]) == [0.0, 2.0, 0.0]
    q = struct.pack("<9h", 0, 0, 0, 32767, 0, 0, 0, 32767, 0) + b"\0\0"
    acc = {"bufferView": 0, "componentType": 5122, "normalized": True, "count": 3, "type": "VEC3"}
    data = _asset(
        [{"attributes": {"POSITION": 0}}],
        q,
        accessors=[acc],
        extra={"extensionsRequired": ["KHR_mesh_quantization"], "extensionsUsed": ["KHR_mesh_quantization"]},
    )
    with open_model(data, name="q.gltf") as doc:
        (obj,) = doc.scene().objects
        assert list(obj.positions[3:6]) == pytest.approx([1.0, 0.0, 0.0])


def test_accessors_without_a_buffer_view_cost_what_the_file_holds():
    # positions that are zeros only (no buffer view, no sparse block): nothing to draw,
    # however many the accessor claims, and nothing allocated for them
    zeros = {"componentType": 5126, "count": 60_000_000, "type": "VEC3"}
    data = _asset([{"attributes": {"POSITION": 0}}], TRIANGLE, accessors=[zeros])
    assert len(data) < 500
    with open_model(data, name="z.gltf") as doc:
        assert doc.counts()["objects"] == 0 and "primitives_skipped" in mw.codes(doc.warnings)
        s = doc.scene()
        assert s.counts["objects"] == 0 and s.counts["items"] == 0
        assert doc.tree().nodes[0].object is None
    # indices that are zeros only: no triangle
    data = _asset(
        [{"attributes": {"POSITION": 0}, "indices": 1}],
        TRIANGLE,
        accessors=[_position(3), {"componentType": 5125, "count": 3_000_000, "type": "SCALAR"}],
    )
    with open_model(data, name="i.gltf") as doc:
        assert doc.scene().counts["objects"] == 0 and "primitives_skipped" in mw.codes(doc.warnings)
    # zeros with one sparse value: bounded by the sparse block's size, as a zip member's inflation
    idx = struct.pack("<I", 2)
    val = struct.pack("<3f", 0, 2, 0)
    views = [
        {"buffer": 0, "byteOffset": 0, "byteLength": 4},
        {"buffer": 0, "byteOffset": 4, "byteLength": 12},
    ]
    sparse = {"count": 1, "indices": {"bufferView": 0, "componentType": 5125}, "values": {"bufferView": 1}}
    for count, ok in ((3, True), (60_000_000, False)):
        acc = {"componentType": 5126, "count": count, "type": "VEC3", "sparse": sparse}
        data = _asset([{"attributes": {"POSITION": 0}}], idx + val, accessors=[acc], views=views)
        with open_model(data, name="s.gltf") as doc:
            if ok:
                (obj,) = doc.scene().objects
                assert list(obj.positions) == [0.0] * 6 + [0.0, 2.0, 0.0]
                continue
            with pytest.raises(SldLimitError) as exc:
                doc.scene()
            assert exc.value.detail["limit"] == "zip_ratio"
    # a count past what the scene may still take is refused before anything is read
    with open_model(
        _asset([{"attributes": {"POSITION": 0}}], TRIANGLE, accessors=[_position(3)]),
        name="v.gltf",
        limits=Limits(vertices=2),
    ) as doc:
        with pytest.raises(SldLimitError) as exc:
            doc.scene()
    assert exc.value.detail["limit"] == "vertices"


def test_a_sparse_block_is_read_and_checked_before_any_zero_is_made():
    # four million sparse values claimed over views that hold one: the claim is refused from
    # the views, before the accessor's 240 MB of zeros are made (a 552-byte file made the
    # read peak at 495 MB when the zeros came first)
    idx = struct.pack("<I", 2)
    val = struct.pack("<3f", 0, 2, 0)
    views = [
        {"buffer": 0, "byteOffset": 0, "byteLength": 4},
        {"buffer": 0, "byteOffset": 4, "byteLength": 12},
    ]
    sparse = {
        "count": 4_000_000,
        "indices": {"bufferView": 0, "componentType": 5125},
        "values": {"bufferView": 1},
    }
    acc = {"componentType": 5126, "count": 20_000_000, "type": "VEC3", "sparse": sparse}
    data = _asset([{"attributes": {"POSITION": 0}}], idx + val, accessors=[acc], views=views)
    tracemalloc.start()
    try:
        with open_model(data, name="s.gltf") as doc:
            with pytest.raises(SldFormatError, match="sparse data runs past"):
                doc.scene()
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 32 << 20
    # an index past the accessor's end is refused from the block as well
    sparse = {"count": 1, "indices": {"bufferView": 0, "componentType": 5125}, "values": {"bufferView": 1}}
    acc = {"componentType": 5126, "count": 2, "type": "VEC3", "sparse": sparse}
    data = _asset([{"attributes": {"POSITION": 0}}], idx + val, accessors=[acc], views=views)
    with open_model(data, name="s.gltf") as doc:
        with pytest.raises(SldFormatError, match="past the accessor's end"):
            doc.scene()


@pytest.mark.parametrize("stride", [16, 20, 36])
def test_a_strided_view_reads_as_a_packed_one(stride):
    pts = [((i % 97) * 0.01, (i % 89) * 0.02 + i * 1e-4, -(i % 83) * 0.03) for i in range(3000)]

    def positions(step: int) -> list[float]:
        blob = b"".join(struct.pack("<3f", *p) + bytes(step - 12) for p in pts)
        view = {"buffer": 0, "byteOffset": 0, "byteLength": len(blob)}
        if step != 12:
            view["byteStride"] = step
        data = _asset([{"attributes": {"POSITION": 0}}], blob, accessors=[_position(len(pts))], views=[view])
        with open_model(data, name="p.gltf") as doc:
            (obj,) = doc.scene().objects
            return list(obj.positions)

    assert positions(stride) == positions(12)


def test_buffers_beside_the_file_are_bounded_in_total(tmp_path):
    # ten buffers name one 1 MiB file: every read counts against sibling_total_bytes
    blob = TRIANGLE + bytes((1 << 20) - len(TRIANGLE))
    (tmp_path / "big.bin").write_bytes(blob)
    n = 10
    doc = {
        "asset": {"version": "2.0"},
        "scenes": [{"nodes": list(range(n))}],
        "nodes": [{"mesh": i} for i in range(n)],
        "meshes": [{"primitives": [{"attributes": {"POSITION": i}}]} for i in range(n)],
        "accessors": [_position(3, view=i) for i in range(n)],
        "bufferViews": [{"buffer": i, "byteOffset": 0, "byteLength": 36} for i in range(n)],
        "buffers": [{"byteLength": len(blob), "uri": "big.bin"} for _ in range(n)],
    }
    path = tmp_path / "many.gltf"
    path.write_text(json.dumps(doc))
    with open_model(path, limits=Limits(sibling_total_bytes=3 << 20)) as m:
        with pytest.raises(SldLimitError) as exc:
            m.scene()
    assert exc.value.detail["limit"] == "sibling_total_bytes"
    with open_model(path) as m:  # within the default total every buffer is read
        assert m.scene().counts["objects"] == n


def test_compression_and_required_extensions():
    blob = TRIANGLE
    draco = {"attributes": {"POSITION": 1}, "extensions": {"KHR_draco_mesh_compression": {"bufferView": 0}}}
    accs = [_position(3), {"componentType": 5126, "count": 3, "type": "VEC3"}]
    data = _asset(
        [{"attributes": {"POSITION": 0}}, draco],
        blob,
        accessors=accs,
        extra={"extensionsUsed": ["KHR_draco_mesh_compression"]},
    )
    with open_model(data, name="d.gltf") as doc:
        assert "compression_not_supported" in mw.codes(doc.warnings)
        assert len(doc.scene().objects) == 1
    for ext, rule in (
        ("KHR_draco_mesh_compression", "compression"),
        ("EXT_meshopt_compression", "compression"),
        ("EXT_mesh_gpu_instancing", "required_extension"),
        ("VENDOR_magic", "required_extension"),
    ):
        data = _asset(
            [{"attributes": {"POSITION": 0}}],
            blob,
            accessors=[_position(3)],
            extra={"extensionsRequired": [ext], "extensionsUsed": [ext]},
        )
        with pytest.raises(FormatNotSupportedError) as exc:
            open_model(data, name="r.gltf")
        assert exc.value.detail == {"rule": rule, "value": ext}
    data = _asset(
        [{"attributes": {"POSITION": 0}}],
        blob,
        accessors=[_position(3)],
        extra={"extensionsRequired": ["KHR_materials_unlit", "KHR_texture_transform"]},
    )
    with open_model(data, name="ok.gltf") as doc:
        assert len(doc.scene().objects) == 1
    data = _asset(
        [{"attributes": {"POSITION": 0}}],
        blob,
        accessors=[_position(3)],
        extra={"extensionsUsed": ["EXT_mesh_gpu_instancing"]},
    )
    with open_model(data, name="i.gltf") as doc:
        assert "extension_ignored" in mw.codes(doc.warnings)


def test_textures_are_warned_and_a_textured_material_has_no_colour():
    mats = {"materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}]}
    data = _asset(
        [{"attributes": {"POSITION": 0}, "material": 0}], TRIANGLE, accessors=[_position(3)], extra=mats
    )
    with open_model(data, name="t.gltf") as doc:
        assert "textures_ignored" in mw.codes(doc.warnings)
        assert doc.scene().objects[0].color is None


@pytest.mark.parametrize(
    ("nodes", "scenes"),
    [
        ([{"mesh": 0, "children": [0]}], [{"nodes": [0]}]),  # its own child
        ([{"children": [1]}, {"children": [0], "mesh": 0}], [{"nodes": [0]}]),  # a cycle
        ([{"children": [2]}, {"children": [2]}, {"mesh": 0}], [{"nodes": [0, 1]}]),  # two parents
        ([{"mesh": 0}], [{"nodes": [0, 0]}]),  # one root twice
        ([{"mesh": 0, "children": [5]}], [{"nodes": [0]}]),
        ([{"mesh": 3}], [{"nodes": [0]}]),
        ([{"mesh": 0, "matrix": [1, 0, 0]}], [{"nodes": [0]}]),
        ([{"mesh": 0}], [{"nodes": [0]}, {"nodes": "x"}]),
    ],
)
def test_a_damaged_hierarchy_is_refused(nodes, scenes):
    data = _asset(
        [{"attributes": {"POSITION": 0}}],
        TRIANGLE,
        nodes=nodes,
        accessors=[_position(3)],
        extra={"scenes": scenes, "scene": len(scenes) - 1},
    )
    with pytest.raises(SldFormatError):
        open_model(data, name="h.gltf")


def test_a_deep_hierarchy_is_bounded():
    nodes = [{"children": [i + 1]} for i in range(40)] + [{"mesh": 0}]
    data = _asset([{"attributes": {"POSITION": 0}}], TRIANGLE, nodes=nodes, accessors=[_position(3)])
    with pytest.raises(SldLimitError) as exc:
        open_model(data, name="d.gltf")
    assert exc.value.detail["limit"] == "depth"


@pytest.mark.parametrize(
    "accessor",
    [
        _position(4),  # runs past its view
        _position(3, offset=4),
        {"bufferView": 0, "componentType": 9999, "count": 3, "type": "VEC3"},
        {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC2"},
        {"bufferView": 0, "componentType": 5126, "count": -1, "type": "VEC3"},
        {"bufferView": 7, "componentType": 5126, "count": 3, "type": "VEC3"},
    ],
)
def test_a_damaged_accessor_is_refused(accessor):
    data = _asset([{"attributes": {"POSITION": 0}}], TRIANGLE, accessors=[accessor])
    with pytest.raises(SldFormatError):
        with open_model(data, name="a.gltf") as doc:
            doc.scene()


def test_buffers_beside_the_file_stay_inside_its_folder(tmp_path):
    inner = tmp_path / "inner"
    inner.mkdir()
    (tmp_path / "outside.bin").write_bytes(TRIANGLE)
    for uri in ("../outside.bin", "file:///outside.bin", "C:/outside.bin", "//host/share/outside.bin"):
        doc = json.loads(_asset([{"attributes": {"POSITION": 0}}], TRIANGLE, accessors=[_position(3)]))
        doc["buffers"][0]["uri"] = uri
        (inner / "x.gltf").write_text(json.dumps(doc))
        with open_model(inner / "x.gltf") as m:
            with pytest.raises(PathRefusedError):
                m.scene()
            assert m.references()[0].resolution["status"] == "refused"
    doc["buffers"][0]["uri"] = "missing.bin"
    (inner / "x.gltf").write_text(json.dumps(doc))
    with open_model(inner / "x.gltf") as m:
        with pytest.raises(SldFormatError):
            m.scene()
    with open_model(json.dumps(doc).encode(), name="b.gltf") as m:  # bytes: no folder to read from
        with pytest.raises(SldFormatError):
            m.scene()


def test_a_buffer_keeps_the_rules_the_asset_was_opened_with(tmp_path):
    """A buffer with a second name outside the folder is refused like the asset itself would
    be (``refuse_hard_links``, as the REST service opens), and so is one too large."""
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    data, siblings = mw.gltf(box(10, 20, 30), buffer="file")
    (outside / "scene.bin").write_bytes(siblings["scene.bin"])
    os.link(outside / "scene.bin", root / "scene.bin")
    (root / "hard.gltf").write_bytes(data)
    with open_model(root / "hard.gltf", within=root) as doc:  # not asked: read as before
        assert doc.scene().counts["items"] == 1
        assert doc.references()[0].resolution["status"] == "found"
    with open_model(root / "hard.gltf", within=root, refuse_hard_links=True) as doc:
        assert doc.refuse_hard_links
        with pytest.raises(LinkRefusedError) as exc:
            doc.scene()
        assert exc.value.detail == {"rule": "hard_link"}
        assert doc.references()[0].resolution == {
            "status": "refused",
            "path": None,
            "found_by": None,
            "version": None,
        }
    (root / "scene.bin").unlink()
    (root / "scene.bin").write_bytes(siblings["scene.bin"] + bytes(len(data)))  # longer than the asset
    with open_model(root / "hard.gltf", max_file_bytes=len(data)) as doc:
        with pytest.raises(FileTooLargeError):  # the buffer is larger than the file limit
            doc.scene()


def test_the_container_and_json_are_checked():
    good, _ = mw.gltf(box(1, 1, 1), buffer="glb")
    with pytest.raises(SldFormatError):
        open_model(good[:4] + struct.pack("<I", 1) + good[8:], name="v.glb")  # version 1
    with pytest.raises(SldFormatError):
        open_model(good[:8] + struct.pack("<I", len(good) + 10) + good[12:], name="l.glb")
    with pytest.raises(SldFormatError):
        open_model(good[:30], name="t.glb")
    for bad in (
        b'{"asset": {"version": "1.0"}}',
        b'{"asset": {"version": "2.0"}, "nodes": [NaN]}',
        b'{"asset": {"version": "2.0"}, "meshes": 3}',
        b'{"asset": 2}',
        b"[1]",
    ):
        with pytest.raises(SldFormatError):
            open_model(bad, name="j.gltf")
    with pytest.raises(SldLimitError) as exc:
        open_model(good, name="b.glb", limits=Limits(json_bytes=64))
    assert exc.value.detail["limit"] == "json_bytes"
    data, _ = mw.gltf(holed_block())
    with open_model(data, name="d.gltf", limits=Limits(gltf_data_uri_bytes=100)) as doc:
        with pytest.raises(SldLimitError) as exc:
            doc.scene()
    assert exc.value.detail["limit"] == "gltf_data_uri_bytes"


def test_array_and_buffer_counts_are_bounded():
    data, _ = mw.gltf(two_object_assembly())
    with pytest.raises(SldLimitError) as exc:
        open_model(data, name="c.gltf", limits=Limits(gltf_array_items=2))
    assert exc.value.detail["limit"] == "gltf_array_items"
    doc = json.loads(data)
    doc["buffers"] = doc["buffers"] * 3
    with pytest.raises(SldLimitError) as exc:
        open_model(json.dumps(doc).encode(), name="c.gltf", limits=Limits(gltf_buffers=2))
    assert exc.value.detail["limit"] == "gltf_buffers"


@pytest.mark.usefixtures("outbound_guard")
def test_python_cli_and_rest_give_the_same_model_summary(tmp_path, capsys):
    data, sib = mw.gltf(two_object_assembly(), buffer="file")
    (tmp_path / "a.gltf").write_bytes(data)
    for k, v in sib.items():
        (tmp_path / k).write_bytes(v)
    (tmp_path / "b.glb").write_bytes(mw.gltf(two_object_assembly(), buffer="glb", hierarchy=True)[0])
    mw.same_on_three_surfaces(tmp_path, ["a.gltf", "b.glb"], "gltf", capsys)


def test_the_glb_chunk_walk_keeps_the_time_bound():
    js = json.dumps({"asset": {"version": "2.0"}}).encode()
    js += b" " * (-len(js) % 4)
    chunks = struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", 0, 0x5A5A5A5A) * 10_000
    glb = b"glTF" + struct.pack("<II", 2, 12 + len(chunks)) + chunks
    with open_model(glb, name="c.glb") as doc:  # ten thousand empty chunks read in time
        assert doc.counts()["objects"] == 0
    with pytest.raises(SldLimitError) as exc:
        open_model(glb, name="c.glb", limits=Limits(seconds=1e-9))
    assert exc.value.detail["limit"] == "seconds"


def test_strips_fans_and_normalised_values_tick_the_clock():
    """The loops that turn strips and fans into triangles and convert normalised values
    tick the scene's clock as they go, so its time bound and cancellation reach them."""
    pts = [((i % 100) * 300, (i // 100) * 300, (i % 7) * 100) for i in range(9000)]
    blob = b"".join(struct.pack("<3h", *p) for p in pts)
    acc = {"bufferView": 0, "componentType": 5122, "normalized": True, "count": len(pts), "type": "VEC3"}
    quantized = {"extensionsRequired": ["KHR_mesh_quantization"], "extensionsUsed": ["KHR_mesh_quantization"]}
    prims = [{"attributes": {"POSITION": 0}, "mode": 5}, {"attributes": {"POSITION": 0}, "mode": 6}]
    data = _asset(prims, blob, accessors=[acc], extra=quantized)
    callers = []

    def cancelled():
        frame = sys._getframe(1)
        while frame is not None and frame.f_code.co_name in ("check", "tick"):
            frame = frame.f_back
        callers.append(frame.f_code.co_name if frame is not None else None)
        return False

    with open_model(data, name="q.gltf") as doc:
        s = doc.scene(cancelled=cancelled)
    assert len(s.objects) == 2
    assert callers.count("_primitive") >= 4 and callers.count("_accessor") >= 6


def test_a_buffer_in_a_subfolder_is_read_only_when_subfolders_are(tmp_path):
    data, sib = mw.gltf(box(1, 1, 1), buffer="file")
    doc = json.loads(data)
    doc["buffers"][0]["uri"] = "sub/scene.bin"
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "scene.bin").write_bytes(sib["scene.bin"])
    path = tmp_path / "s.gltf"
    path.write_text(json.dumps(doc))
    with open_model(path) as m:
        assert m.scene().counts["triangles"] == 12
        assert m.references()[0].resolution["status"] == "found"
    with open_model(path, subfolders=False) as m:
        assert m.subfolders is False
        with pytest.raises(PathRefusedError) as exc:
            m.scene()
        assert exc.value.detail == {"rule": "subfolder"}
        assert m.references()[0].resolution["status"] == "refused"
