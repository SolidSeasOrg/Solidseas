"""``solidseas.gltf`` (``docs/API.md`` 3.28): a document's display meshes as a GLB.

A strict reader here, sharing no code with the writer, checks every file the writer makes
against the parts of glTF 2.0 it uses: the frame and its alignment, accessors that point
inside their buffer views and those inside the buffer, POSITION bounds that are the
data's, indices inside their vertices. A part's GLB holds its display mesh byte for byte
(or, stored without one, its bodies' triangles); an assembly's places every instance
where ``display_geometry`` does, from the assembly's own display data, and opens no
other file even when the component files lie beside it.
"""

import json
import math
import os
import shutil
import struct
from array import array

import pytest

from builders import rebuild
from solidseas import Roots, open_document
from solidseas.errors import InvalidArgumentError, NothingToExportError, SldLimitError
from solidseas.formats.solidworks import container as container_mod
from solidseas.geometry import display_geometry
from solidseas.gltf import GLB_MIME, GlbMesh, GlbNode, display_glb, is_glb, write_glb
from support import fixture_path

O02 = fixture_path("o02_boxA.SLDPRT")
O08 = fixture_path("o08_asm_2x_boxA.SLDASM")
O16 = fixture_path("o16_asm_features.SLDASM")
STORED_MESHES = ("Contents/DisplayLists", "FaceTessellations/000-000-001", "FaceTessellations/Directory")
_SIZES = {5126: 4, 5125: 4, 5123: 2}
_COUNTS = {"VEC3": 3, "SCALAR": 1}


def read_glb(data: bytes) -> tuple[dict, bytes]:
    """The JSON and binary chunks of a GLB, after checking its frame byte by byte."""
    magic, version, length = struct.unpack_from("<4sII", data, 0)
    assert (magic, version, length) == (b"glTF", 2, len(data))
    size, kind = struct.unpack_from("<I4s", data, 12)
    assert kind == b"JSON" and size % 4 == 0
    text = data[20 : 20 + size]
    assert text.rstrip(b" ") == text.rstrip()  # padded with spaces only
    doc = json.loads(text, parse_constant=lambda c: pytest.fail(f"{c} in the JSON"))
    blob = b""
    rest = 20 + size
    if rest < len(data):
        size, kind = struct.unpack_from("<I4s", data, rest)
        assert kind == b"BIN\x00" and size % 4 == 0 and rest + 8 + size == len(data)
        blob = data[rest + 8 :]
    else:
        assert rest == len(data)
    return doc, blob


def accessor(doc: dict, blob: bytes, index: int) -> list:
    """The values of one accessor, checked to lie inside its view and the buffer."""
    a = doc["accessors"][index]
    v = doc["bufferViews"][a["bufferView"]]
    assert v["buffer"] == 0 and v["byteOffset"] % 4 == 0
    assert v["byteOffset"] + v["byteLength"] <= doc["buffers"][0]["byteLength"] == len(blob)
    width = _SIZES[a["componentType"]] * _COUNTS[a["type"]]
    assert a["count"] * width == v["byteLength"]
    code = {5126: "f", 5125: "I", 5123: "H"}[a["componentType"]]
    raw = blob[v["byteOffset"] : v["byteOffset"] + v["byteLength"]]
    return list(struct.unpack(f"<{a['count'] * _COUNTS[a['type']]}{code}", raw))


def check(data: bytes) -> dict:
    """Every rule of glTF 2.0 the writer relies on, for every mesh and node of a GLB."""
    doc, blob = read_glb(data)
    assert doc["asset"]["version"] == "2.0" and doc["scene"] == 0
    for mesh in doc.get("meshes", []):
        (prim,) = mesh["primitives"]
        positions = accessor(doc, blob, prim["attributes"]["POSITION"])
        a = doc["accessors"][prim["attributes"]["POSITION"]]
        assert a["min"] == [min(positions[k::3]) for k in range(3)]
        assert a["max"] == [max(positions[k::3]) for k in range(3)]
        assert all(math.isfinite(p) for p in positions)
        indices = accessor(doc, blob, prim["indices"])
        assert len(indices) % 3 == 0 and max(indices) < len(positions) // 3
        if "NORMAL" in prim["attributes"]:
            normals = accessor(doc, blob, prim["attributes"]["NORMAL"])
            assert len(normals) == len(positions)
        assert doc["materials"][prim["material"]]["doubleSided"] is True
    for node in doc.get("nodes", []):
        assert 0 <= node["mesh"] < len(doc["meshes"])
        assert len(node.get("matrix", [0] * 16)) == 16
    assert doc["scenes"][0]["nodes"] == list(range(len(doc.get("nodes", []))))
    return doc


# --------------------------------------------------------------------------- a part
def test_a_parts_glb_holds_its_display_mesh_byte_for_byte():
    with open_document(O02) as doc:
        summary, data = display_glb(doc)
        mesh = doc.mesh()
    assert is_glb(data) and summary["bytes"] == len(data) and GLB_MIME == "model/gltf-binary"
    assert summary == {
        "doc_type": "part",
        "configuration": "Default",
        "source": "display_mesh",
        "meshes": 1,
        "instances": 1,
        "skipped": 0,
        "triangles": mesh.n_triangles,
        "triangles_drawn": mesh.n_triangles,
        "truncated": [],
        "bytes": len(data),
    }
    doc_json = check(data)
    _doc, blob = read_glb(data)
    prim = doc_json["meshes"][0]["primitives"][0]
    assert accessor(doc_json, blob, prim["attributes"]["POSITION"]) == list(mesh.positions)
    assert accessor(doc_json, blob, prim["indices"]) == list(mesh.triangles)
    assert accessor(doc_json, blob, prim["attributes"]["NORMAL"]) == list(mesh.normals)
    assert doc_json["accessors"][prim["indices"]]["componentType"] == 5123  # few vertices: uint16
    assert doc_json["nodes"] == [{"name": "o02_boxA", "mesh": 0}]  # where the mesh is: no matrix
    extras = doc_json["scenes"][0]["extras"]["solidseas"]
    assert extras["units"] == "m" and extras["skipped_listed"] == [] and extras["source"] == "display_mesh"


def test_a_part_stored_without_a_display_mesh_is_drawn_from_its_bodies(tmp_path):
    path = tmp_path / "bodies_only.SLDPRT"
    path.write_bytes(rebuild(O02, drop=("Contents/DisplayLists",)))
    with open_document(path) as doc:
        assert doc.mesh() is None  # the premise
        summary, data = display_glb(doc)
    assert summary["source"] == "bodies" and summary["triangles"] >= 12
    doc_json = check(data)
    lo, hi = doc_json["accessors"][0]["min"], doc_json["accessors"][0]["max"]
    with open_document(O02) as doc:  # the same box as the display mesh shows
        stored = doc.mesh().bbox()
    assert all(abs(a - b) < 1e-6 for a, b in zip([*lo, *hi], [*stored[0], *stored[1]], strict=True))


def test_another_configuration_of_a_part_is_drawn_from_its_bodies():
    with open_document(fixture_path("o13_two_geometry_configs.SLDPRT")) as doc:
        names = [c.name for c in doc.configurations]
        other = next(n for n in names if n != doc.active_configuration)
        active_summary, active = display_glb(doc)
        summary, data = display_glb(doc, other)
    assert active_summary["source"] == "display_mesh" and summary["source"] == "bodies"
    assert summary["configuration"] == other and check(data) and data != active


@pytest.mark.parametrize(
    ("name", "rule"), [("o01_empty.SLDPRT", "no_mesh"), ("o18_drw_boxA.SLDDRW", "drawing")]
)
def test_a_document_with_nothing_to_draw_says_so(name, rule):
    with open_document(fixture_path(name)) as doc, pytest.raises(NothingToExportError) as caught:
        display_glb(doc)
    assert caught.value.code == "nothing_to_export" and caught.value.detail == {"rule": rule}


def test_a_part_past_a_limit_is_refused():
    with open_document(O02) as doc:
        with pytest.raises(SldLimitError) as caught:
            display_glb(doc, max_triangles=5)
        assert caught.value.code == "limit_exceeded" and caught.value.detail == {"limit": 5, "value": 12}
        with pytest.raises(SldLimitError) as caught:
            display_glb(doc, max_bytes=100)
        assert caught.value.detail["limit"] == 100
        for bad in ({"max_triangles": 0}, {"max_bytes": True}, {"body_seconds": 0}):
            with pytest.raises(InvalidArgumentError):
                display_glb(doc, **bad)


# --------------------------------------------------------------------------- an assembly
def test_an_assemblys_glb_places_every_instance_where_display_geometry_does():
    with open_document(O16) as doc:
        summary, data = display_glb(doc)
        g = display_geometry(doc, roots=Roots([]), allow_outside_roots=False, sources=("assembly", "nested"))
    doc_json = check(data)
    nodes = doc_json["nodes"]
    assert len(nodes) == len(g.instances) == summary["instances"] == 12 and summary["skipped"] == 0
    assert len(doc_json["meshes"]) == len(g.meshes) == summary["meshes"]
    for node, inst in zip(nodes, g.instances, strict=True):
        assert node["name"] == inst.name and node["extras"]["id"] == inst.id
        assert node["matrix"] == list(inst.matrix())
        indices = doc_json["meshes"][node["mesh"]]["primitives"][0]["indices"]
        assert doc_json["accessors"][indices]["count"] == len(g.meshes[inst.mesh].mesh.triangles)
    shared = {}  # one glTF mesh per display mesh, shared by its instances
    for node, inst in zip(nodes, g.instances, strict=True):
        assert shared.setdefault(inst.mesh, node["mesh"]) == node["mesh"]
    assert summary["triangles_drawn"] == sum(g.meshes[i.mesh].triangles for i in g.instances)


def _recorded_opens(monkeypatch) -> tuple[list[str], list[str]]:
    opened: list[str] = []
    real = container_mod.open_readonly

    def record(path, **kwargs):
        opened.append(os.path.basename(os.fspath(path)))
        return real(path, **kwargs)

    monkeypatch.setattr(container_mod, "open_readonly", record)
    listed: list[str] = []
    real_scandir = os.scandir

    def scandir(path="."):
        listed.append(os.fspath(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)
    return opened, listed


def test_an_assembly_whose_meshes_are_in_its_part_files_opens_none_of_them(tmp_path, monkeypatch):
    """The part files sit beside the assembly, findable by name, and the assembly stores
    no mesh of them: its instances are listed as skipped, each with the box the assembly
    stores for it, and nothing but the assembly is opened or listed."""
    folder = tmp_path / "project"
    folder.mkdir()
    shutil.copy2(O02, folder / "o02_boxA.SLDPRT")
    path = folder / "bare.SLDASM"
    path.write_bytes(rebuild(O08, drop=STORED_MESHES))
    opened, listed = _recorded_opens(monkeypatch)
    with open_document(path) as doc:
        summary, data = display_glb(doc)
    assert opened == ["bare.SLDASM"] and listed == []
    assert summary["instances"] == 0 and summary["skipped"] == 2 and summary["meshes"] == 0
    doc_json = check(data)
    assert "nodes" not in doc_json and "buffers" not in doc_json  # nothing drawn: no binary chunk
    skipped = doc_json["scenes"][0]["extras"]["solidseas"]["skipped_listed"]
    assert [s["name"] for s in skipped] == ["o02_boxA-1", "o02_boxA-2"]
    boxes = [s["box"] for s in skipped]
    assert all(b is not None and all(lo < hi for lo, hi in zip(b[0], b[1], strict=True)) for b in boxes)
    assert boxes[0] != boxes[1]  # each in its own place
    opened.clear()
    with open_document(O08) as doc:  # control: the same assembly with its stored meshes
        assert display_glb(doc)[0]["instances"] == 2


# --------------------------------------------------------------------------- the writer
def _square() -> GlbMesh:
    positions = array("f", [0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0])
    return GlbMesh("square", positions, array("I", [0, 1, 2, 0, 2, 3]))


def test_the_writer_shares_a_mesh_between_nodes_and_keeps_their_matrices():
    move = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 5.0, 0, 0, 1.0]
    data = write_glb([_square()], [GlbNode("a", 0), GlbNode("b", 0, move, {"id": "b-1"})], extras={"k": 1})
    doc = check(data)
    assert [n.get("matrix") for n in doc["nodes"]] == [None, move]
    assert doc["nodes"][1]["extras"] == {"id": "b-1"} and doc["scenes"][0]["extras"] == {"k": 1}
    assert "NORMAL" not in doc["meshes"][0]["primitives"][0]["attributes"]  # none given: flat shading


def test_indices_are_uint32_once_a_mesh_has_too_many_vertices_for_uint16():
    n = 65537
    positions = array("f", [float(i % 7) for i in range(3 * n)])
    mesh = GlbMesh("big", positions, array("I", [0, 1, n - 1]))
    doc, blob = read_glb(write_glb([mesh], [GlbNode("big", 0)]))
    assert doc["accessors"][1]["componentType"] == 5125 and accessor(doc, blob, 1) == [0, 1, n - 1]


@pytest.mark.parametrize(
    "mesh",
    [
        GlbMesh("nan", array("f", [0, 0, 0, 1, 0, float("nan"), 1, 1, 0]), array("I", [0, 1, 2])),
        GlbMesh("inf", array("f", [0, 0, 0, 1, 0, float("inf"), 1, 1, 0]), array("I", [0, 1, 2])),
        GlbMesh("past", array("f", [0, 0, 0, 1, 0, 0, 1, 1, 0]), array("I", [0, 1, 3])),
        GlbMesh("ragged", array("f", [0, 0, 0, 1, 0, 0, 1, 1]), array("I", [0, 1, 2])),
        GlbMesh("pairs", array("f", [0, 0, 0, 1, 0, 0, 1, 1, 0]), array("I", [0, 1])),
        GlbMesh("empty", array("f"), array("I")),
        GlbMesh("doubles", array("d", [0, 0, 0, 1, 0, 0, 1, 1, 0]), array("I", [0, 1, 2])),
        GlbMesh("shorts", array("f", [0, 0, 0, 1, 0, 0, 1, 1, 0]), array("H", [0, 1, 2])),
        GlbMesh(
            "normals",
            array("f", [0, 0, 0, 1, 0, 0, 1, 1, 0]),
            array("I", [0, 1, 2]),
            array("f", [0, 0, 1, 0, 0, float("nan"), 0, 0, 1]),
        ),
    ],
    ids=lambda m: m.name,
)
def test_the_writer_refuses_a_mesh_glb_cannot_hold(mesh):
    with pytest.raises(InvalidArgumentError):
        write_glb([mesh], [GlbNode("x", 0)])


@pytest.mark.parametrize(
    "node",
    [GlbNode("none", 1), GlbNode("short", 0, [1.0] * 15), GlbNode("nan", 0, [float("nan")] * 16)],
    ids=lambda n: n.name,
)
def test_the_writer_refuses_a_node_glb_cannot_hold(node):
    with pytest.raises(InvalidArgumentError):
        write_glb([_square()], [node])


def test_is_glb_reads_the_frame_alone():
    data = write_glb([_square()], [GlbNode("a", 0)])
    assert is_glb(data)
    json_only = write_glb([], [])
    assert is_glb(json_only) and read_glb(json_only)[1] == b""
    broken = {
        "short": data[:16],
        "magic": b"gltf" + data[4:],
        "version": data[:4] + struct.pack("<I", 1) + data[8:],
        "length": data[:8] + struct.pack("<I", len(data) + 4) + data[12:],
        "trailing": data[:8] + struct.pack("<I", len(data) + 4) + data[12:] + b"\0\0\0\0",
        "unaligned": data[:12] + struct.pack("<I", struct.unpack_from("<I", data, 12)[0] + 1) + data[16:],
        "bin_first": data[:16] + b"BIN\x00" + data[20:],
        "html": b"<html><script>x</script></html>",
    }
    for label, bad in broken.items():
        assert not is_glb(bad), label
