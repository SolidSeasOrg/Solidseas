"""Every 3D format in the viewer: listing, details, previews, the 3D view, exports.

The files are the viewer's own synthetic samples (``solidseas_app.viewer.samples``:
one small file of each format SolidSeas reads, and an IGES file it cannot read),
written by code into each test's temporary folder; nothing here comes from a real
file. The parts that import no Qt (the samples, the naming of a model's rows and
instances, the mesh process's buffers and its JSON answers, the export's process,
the wording) are tested everywhere. The window runs offscreen; what needs OpenGL
(the 3D view, picking, explode, looks) runs on the real display through the
formats self-test (``--self-test-formats --3d``), as ``tests/gl_support.py`` runs
every display test.

A model file is never parsed in the window's process: a child process lists and
shows every sample and then reports which reader modules it imported, which must
be none.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from solidseas.formats import open_any
from solidseas_app.viewer import mesh3d, meshproc, modeljobs, modelview, printing, samples, wording

try:
    import PySide6.QtWidgets  # noqa: F401
except ImportError:
    HAVE_QT = False
else:
    HAVE_QT = True

needs_qt = pytest.mark.skipif(not HAVE_QT, reason="PySide6 is not installed: the viewer window is not tested")
SRC = str(Path(__file__).resolve().parent.parent / "src")
READERS = ("stl", "threemf", "obj", "ply", "off", "gltf", "amf", "xt", "step", "alibre", "acis")


@pytest.fixture(scope="module")
def sample_folder(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("formats") / "samples"
    samples.write_samples(str(folder))
    return folder


def _state(folder: Path) -> dict[str, tuple[int, int]]:
    return {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in sorted(folder.iterdir()) if p.is_file()}


# --------------------------------------------------------------------------- the samples
@pytest.mark.parametrize("name", list(samples.EXPECTED))
def test_every_sample_reads_as_written(sample_folder, name):
    fmt, doc_type, items, size = samples.EXPECTED[name]
    with open_any(str(sample_folder / name), within=str(sample_folder)) as doc:
        assert (doc.format, doc.doc_type) == (fmt, doc_type)
        g = modelview.scene_geometry(doc.scene(prefer="display"))
    assert g["items"] == items
    assert g["size_mm"] == pytest.approx(size, abs=1e-4)


def test_the_samples_cover_every_readable_format():
    from solidseas.formats import registry

    readable = {f for f in registry.FORMATS if registry.readable(f)} - {registry.SOLIDWORKS}
    assert {fmt for fmt, *_ in samples.EXPECTED.values()} == readable


def test_samples_never_replace_a_file(tmp_path):
    samples.write_samples(str(tmp_path))
    with pytest.raises(FileExistsError):
        samples.write_samples(str(tmp_path))


# --------------------------------------------------------------------------- rows and instance ids
def _node(i, parent, name, kind="component", obj=None, file=None, x=0.0):
    return {
        "id": i,
        "parent": parent,
        "name": name,
        "kind": kind,
        "object": obj,
        "file": file,
        "placement": {"rotation": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "translation_m": [x, 0.0, 0.0]},
        "color": None,
    }


def test_instance_ids_follow_the_tree_and_tell_siblings_apart():
    nodes = [
        {**_node("1", None, "top", "assembly"), "placement": None},
        _node("2", "1", "box"),
        _node("3", "2", "body", "body", 0),
        _node("4", "1", "box", x=0.05),
        _node("5", "4", "body", "body", 0),
        _node("6", "1", "a/b", "object", 1),
        _node("7", "1", None, "object", 2),
        _node("8", "1", "two bodies"),
        _node("9", "8", "left", "body", 3),
        _node("10", "8", "right", "body", 4),
    ]
    ids = modelview.path_ids(nodes)
    assert ids == {
        "1": "",
        "2": "box (1)",
        "3": "box (1)",  # one body under a part's occurrence: one instance, the occurrence's
        "4": "box (2)",
        "5": "box (2)",
        "6": "a%2Fb",
        "7": "object 7",
        "8": "two bodies",  # a part's several bodies: one part, one instance
        "9": "two bodies",
        "10": "two bodies",
    }
    assert modelview.unlabel("a%2Fb") == "a/b"


def test_the_root_id_is_the_details_panel_s():
    from solidseas_app.viewer import reading

    assert modelview.ROOT_ID == reading.ROOT_ID


def test_a_tree_becomes_the_components_rows_with_their_places():
    nodes = [
        {**_node("1", None, "top", "assembly"), "placement": None},
        _node("2", "1", "box", x=0.01),
        _node("3", "2", "body", "body", 0, x=0.005),
        _node("4", "1", "box", x=0.05),
        _node("5", "4", "body", "body", 0),
        _node("6", "1", "sub", x=0.1),
        _node("7", "6", "inner box", x=0.002),
        _node("8", "7", "body", "body", 0),
        _node("9", "6", "block", "object", 1),
    ]
    c = modelview.components_data({"tree": {"nodes": nodes, "truncated": False}, "references": []})
    first = c["children"][0]
    # a part's occurrence over its one body is one part row, not a sub-assembly of a body
    row = (first["id"], first["name"], first["file"], first["doc_type"])
    assert row == ("box (1)", "box (1)", "object:0", "part")
    assert first["children"] == []
    assert first["placement"]["translation_m"] == pytest.approx([0.015, 0.0, 0.0])  # in the model's frame
    assert first["transform"]["translation_m"] == pytest.approx([0.015, 0.0, 0.0])  # the two composed
    sub = c["children"][2]
    assert (sub["id"], sub["doc_type"], [r["id"] for r in sub["children"]]) == (
        "sub",
        "assembly",
        ["sub/inner box", "sub/block"],
    )
    assert sub["children"][0]["placement"]["translation_m"] == pytest.approx([0.102, 0.0, 0.0])
    # The Files table lists what the instances are of, under the object's own name.
    assert [(f["key"], f["file_name"], f["instances"], f["direct"]) for f in c["files"]] == [
        ("object:0", "body", 3, True),
        ("object:1", "block", 1, False),
    ]
    assert c["counts"] == {"nodes": 5, "depth": 2, "files": 2}
    assert (
        modelview.is_internal("object:0")
        and modelview.is_internal("node:2")
        and not modelview.is_internal("6")
    )


def _rows(path: Path) -> list[dict]:
    got = modeljobs.details({"path": str(path), "within": str(path.parent), "folder": str(path.parent)})
    return got["components"]


def test_a_step_or_3mf_part_placed_twice_is_two_part_rows(sample_folder, tmp_path):
    """A STEP part occurrence holds its body, and a 3MF component object its mesh: each is
    one part row (it used to be a sub-assembly holding a body row, with sub-assembly menus)."""
    import mesh_writers as mw
    import p21_writers as pw
    from model_writers import two_object_assembly

    comp = _rows(sample_folder / "pair.step")
    assert [(r["name"], r["doc_type"], r["children"]) for r in comp["children"]] == [
        ("box 1", "part", []),
        ("box 2", "part", []),
    ]
    assert [(f["file_name"], f["direct"], f["instances"]) for f in comp["files"]] == [("box", True, 2)]
    assert comp["counts"]["depth"] == 1
    (tmp_path / "nested.step").write_bytes(pw.assembly_file(nested=True))
    comp = _rows(tmp_path / "nested.step")
    assert [(r["id"], r["doc_type"]) for r in comp["children"]] == [("box 1", "part"), ("sub 1", "assembly")]
    assert [r["id"] for r in comp["children"][1]["children"]] == ["sub 1/box 2"]
    (tmp_path / "production.3mf").write_bytes(mw.threemf(two_object_assembly(), production=True))
    comp = _rows(tmp_path / "production.3mf")
    assert [(r["name"], r["doc_type"]) for r in comp["children"]] == [
        ("box (1)", "part"),
        ("box (2)", "part"),
        ("holed block", "part"),
    ]
    # the 3D view names its instances as the rows are named
    got = mesh3d.read_model_scene(str(tmp_path / "nested.step"), str(tmp_path), 1_000_000)
    assert [i for ids in got["data"].instance_ids for i in ids] == ["box 1", "sub 1/box 2"]


def test_a_multi_body_part_in_a_step_assembly_is_one_part_row(tmp_path):
    """A component whose product holds two bodies is one part, as SOLIDWORKS lists it: it
    used to be a sub-assembly row over a part row for each body. Both bodies are drawn
    as that row (a pick on either finds it, as row_of walks up the id) in one colour."""
    f = samples._P21()
    ctx = f.context()
    duo = f.product("duo")
    duo_rep = f.shape(duo, [f.box(samples.BOX), f.box((10.0, 10.0, 10.0))], ctx)
    one = f.product("box")
    one_rep = f.shape(one, [f.box(samples.BOX)], ctx)
    top = f.product("rig")
    top_rep = f.shape(top, [], ctx)
    f.place(top, duo, top_rep, duo_rep, (0.0, 0.0, 0.0), "duo 1")
    f.place(top, one, top_rep, one_rep, (80.0, 0.0, 0.0), "box 1")
    (tmp_path / "rig.step").write_bytes(f.bytes("rig.step"))
    comp = _rows(tmp_path / "rig.step")
    assert [(r["id"], r["doc_type"], r["children"]) for r in comp["children"]] == [
        ("duo 1", "part", []),
        ("box 1", "part", []),
    ]
    assert [(f["file_name"], f["doc_type"], f["instances"]) for f in comp["files"]] == [
        ("duo 1", "part", 1),
        ("box", "part", 1),
    ]
    got = mesh3d.read_model_scene(str(tmp_path / "rig.step"), str(tmp_path), 1_000_000)
    scene = got["data"]
    drawn = [i for ids in scene.instance_ids for i in ids]
    assert sorted(i.split("/")[0] for i in drawn) == ["box 1", "duo 1", "duo 1"]
    assert [(f["name"], f["instances"]) for f in scene.files] == [("duo 1", 1), ("box", 1)]
    assert {f["key"] for f in scene.files} == {f["key"] for f in comp["files"]}


def test_gltf_rotations_read_in_the_model_s_z_up_frame(tmp_path):
    """glTF's turn to Z up is part of its top nodes' placements; the Components tab shows
    each node's own rotation, as the same scene written as 3MF shows it."""
    import mesh_writers as mw
    from model_writers import two_object_assembly
    from solidseas_app.viewer.reading import rotation_text

    scene = two_object_assembly()
    data, _ = mw.gltf(scene)
    (tmp_path / "s.gltf").write_bytes(data)
    (tmp_path / "s.3mf").write_bytes(mw.threemf(scene))
    data, _ = mw.gltf(scene, hierarchy=True)
    (tmp_path / "h.gltf").write_bytes(data)
    flat = _rows(tmp_path / "s.gltf")["children"]
    as_3mf = _rows(tmp_path / "s.3mf")["children"]
    assert [rotation_text(r["placement"]["rotation"]) for r in flat] == ["none", "90° about Z", "none"]
    for g, t in zip(flat, as_3mf, strict=True):
        assert g["placement"]["translation_m"] == pytest.approx(t["placement"]["translation_m"], abs=1e-9)
        for a, b in zip(g["placement"]["rotation"], t["placement"]["rotation"], strict=True):
            assert a == pytest.approx(b, abs=1e-9)
    (group,) = _rows(tmp_path / "h.gltf")["children"]
    assert rotation_text(group["placement"]["rotation"]) == "none"
    inner = group["children"]
    assert [rotation_text(r["placement"]["rotation"]) for r in inner] == ["none", "90° about Z", "none"]
    assert [rotation_text(r["transform"]["rotation"]) for r in inner] == ["none", "90° about Z", "none"]
    assert inner[1]["transform"]["translation_m"] == pytest.approx([0.05, 0.0, 0.0], abs=1e-9)


def test_an_alibre_assembly_names_its_component_files_and_where_they_are(sample_folder):
    path = str(sample_folder / "pair.AD_ASM")
    got = modeljobs.details({"path": path, "within": str(sample_folder), "folder": str(sample_folder)})
    rows = got["components"]["children"]
    assert [r["name"] for r in rows] == ["cube (1)", "cube (2)"]
    assert {r["file"] for r in rows} == {samples.CUBE_GUID}
    assert rows[1]["placement"]["translation_m"] == pytest.approx([0.02, 0.0, 0.0])
    (ref,) = got["references"]["files"]
    assert ref["key"] == samples.CUBE_GUID and ref["file_name"] == "cube.AD_PRT"
    assert ref["resolution"]["status"] == "resolved" and ref["resolution"]["rule"] == "document_guid"
    assert ref["resolution"]["match"] == {"root": "folder", "path": "cube.AD_PRT"}
    assert modelview.located("sub/x.AD_PRT", path, str(sample_folder.parent)) == {
        "root": "folder",
        "path": "samples/sub/x.AD_PRT",
    }
    assert (
        modelview.located(str(Path(path).anchor) + "elsewhere/x.AD_PRT", path, str(sample_folder))["root"]
        is None
    )


def test_the_view_job_measures_the_geometry_and_draws_a_preview(sample_folder):
    out, png = modeljobs.view({"path": str(sample_folder / "bracket.step"), "within": str(sample_folder)})
    assert out["geometry"]["items"] == 1 and out["geometry"]["bodies"] == 1 and out["geometry"]["faces"] == 6
    assert out["geometry"]["size_mm"] == pytest.approx(list(samples.BOX))
    assert out["preview"]["source"] == "rendered" and png[:8] == b"\x89PNG\r\n\x1a\n"
    out, png = modeljobs.view({"path": str(sample_folder / "cube.AD_PRT"), "within": str(sample_folder)})
    assert out["preview"]["source"] == "stored" and out["preview"]["stream"] == "PROP_DATA"
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # the stored bitmap, as a PNG SolidSeas wrote


# --------------------------------------------------------------------------- the 3D view's buffers
def test_a_z_up_part_is_turned_to_stand_up_in_the_view(sample_folder):
    result = mesh3d.read_model_scene(str(sample_folder / "box.stl"), str(sample_folder), 1_000_000)
    assert result["state"] == "ok" and result["model"] and result["stored_in"] == "mesh"
    lo, hi = result["data"].bbox
    # 10 x 20 x 30 mm with Z up: in the view's Y-up frame its 30 mm stand along Y.
    assert [round((hi[i] - lo[i]) * 1000, 3) for i in range(3)] == [10.0, 30.0, 20.0]
    step = mesh3d.read_model_scene(str(sample_folder / "bracket.step"), str(sample_folder), 1_000_000)
    lo, hi = step["data"].bbox  # a Y-up format is drawn as it is
    assert [round((hi[i] - lo[i]) * 1000, 3) for i in range(3)] == [10.0, 20.0, 30.0]
    assert step["stored_in"] == "bodies"


def test_an_assembly_s_instances_are_named_as_its_rows(sample_folder):
    for name in ("pair.3mf", "pair.step", "pair.AD_ASM"):
        path = str(sample_folder / name)
        result = mesh3d.read_model_scene(path, str(sample_folder), 1_000_000)
        assert result["state"] == "ok" and result["geometry"]["model"], name
        scene = result["data"]
        drawn = [i for ids in scene.instance_ids for i in ids]
        rows = modeljobs.details({"path": path, "within": str(sample_folder), "folder": str(sample_folder)})
        listed = set()
        stack = list(rows["components"]["children"])
        while stack:
            n = stack.pop()
            listed.add(n["id"])
            stack.extend(n["children"])
        assert drawn and set(drawn) <= listed, name
        keys = {f["key"] for f in rows["components"]["files"]}
        assert {f["key"] for f in scene.files} <= keys, name


def test_too_many_triangles_and_nothing_to_draw_are_said(sample_folder, tmp_path):
    over = mesh3d.read_model_scene(str(sample_folder / "pair.3mf"), str(sample_folder), 10)
    assert over["state"] == "too_large" and over["model"]
    empty = tmp_path / "empty.stl"
    empty.write_bytes(b"empty".ljust(80, b" ") + b"\0\0\0\0")
    got = mesh3d.read_model_scene(str(empty), str(tmp_path), 1000)
    assert got["state"] == "no_mesh" and got["model"]
    broken = tmp_path / "broken.step"
    broken.write_bytes(b"ISO-10303-21;\nHEADER;\n")
    got = mesh3d.read_model_scene(str(broken), str(tmp_path), 1000)
    assert got["state"] == "error" and got["error"]["code"]


def test_a_model_drawn_with_faces_left_out_says_so(tmp_path):
    """A face the tessellator cannot do leaves a hole in the 3D view. The view's answer was
    a plain ``ok`` all the same, so a model drawn with holes looked drawn whole; it is
    ``partial`` now, with a ``faces_left_out`` warning that says how many and why, for a
    part and for an assembly, and the window gets its buffers as for ``ok``."""
    import p21_writers as pw

    broken = b"HYPERBOLIC_THING('',"
    f, _ids = pw.part_file(lambda f: [pw.box_brep(f)])
    (tmp_path / "holed.step").write_bytes(f.bytes().replace(b"PLANE('',", broken, 1))
    (tmp_path / "pair.step").write_bytes(pw.assembly_file().replace(b"PLANE('',", broken, 1))
    (tmp_path / "whole.step").write_bytes(pw.box_file())
    got = mesh3d.read_model_scene(str(tmp_path / "holed.step"), str(tmp_path), 1_000_000)
    assert got["state"] == "partial" and got["data"].n_triangles == 10
    assert got["faces_left_out"]["count"] == 1
    assert got["faces_left_out"]["reasons"] == {"unsupported_surface": 1}
    (w,) = got["warnings"]
    assert w["code"] == "faces_left_out" and w["message"].startswith("1 face could not be tessellated")
    line, full = wording.faces_left_out_text(got["faces_left_out"])
    assert line == "1 face of this model could not be drawn, so the view has a hole there."
    assert full == "1 face: its surface type is not tessellated yet (an offset of a rolling blend, for one)"
    assert wording.faces_left_out_text(None) == ("", "")
    whole = mesh3d.read_model_scene(str(tmp_path / "whole.step"), str(tmp_path), 1_000_000)
    assert whole["state"] == "ok" and "faces_left_out" not in whole and "warnings" not in whole
    pair = mesh3d.read_model_scene(str(tmp_path / "pair.step"), str(tmp_path), 1_000_000)
    assert pair["state"] == "partial" and pair["geometry"]["faces_left_out"]["count"] == 1
    assert "faces_left_out" in {w["code"] for w in pair["geometry"]["mesh_warnings"]}
    text, _tip = wording.not_shown_text(pair["geometry"], 1_000_000)
    assert "1 face of this model could not be drawn" in text
    reader = meshproc.MeshReader()
    try:
        answer = reader.read(str(tmp_path / "holed.step"), str(tmp_path), 1_000_000, model_file=True)
        assert answer["state"] == "partial" and answer["data"].n_triangles == 10
        assert answer["faces_left_out"]["count"] == 1
        answer = reader.read(str(tmp_path / "pair.step"), str(tmp_path), 1_000_000, model_file=True)
        assert answer["state"] == "partial" and answer["data"].meshes
    finally:
        reader.close()


def test_coordinates_beyond_reach_are_refused_with_a_reason_not_a_stopped_process(tmp_path):
    """A corner at 1e300 is left out by the reader; a placement that scales its object far
    out is answered with a limit, which the window shows, rather than float32 infinities
    the window refuses as a bad answer (it used to say the mesh process stopped, and
    restart it)."""
    import mesh_writers as mw
    from model_writers import box

    (tmp_path / "huge.obj").write_text("v 1e300 0 0\nv 0 1 0\nv 0 0 1\nv 1 1 1\nf 1 2 3\nf 2 3 4\n")
    scaled = '<build><item objectid="1" transform="1e300 0 0 0 1e300 0 0 0 1e300 0 0 0"/></build>'
    (tmp_path / "scaled.3mf").write_bytes(mw.threemf(box(10, 20, 30), build_xml=scaled))
    got = mesh3d.read_model_scene(str(tmp_path / "huge.obj"), str(tmp_path), 1_000_000)
    assert got["state"] == "ok" and got["data"].n_triangles == 1
    got = mesh3d.read_model_scene(str(tmp_path / "scaled.3mf"), str(tmp_path), 1_000_000)
    assert got["state"] == "error" and got["error"]["code"] == "limit_exceeded"
    assert got["error"]["detail"] == {"limit": "coordinates"} and not got["error"]["retryable"]
    reader = meshproc.MeshReader()
    try:
        answer = reader.read(str(tmp_path / "scaled.3mf"), str(tmp_path), 1_000_000, model_file=True)
        assert answer["state"] == "error" and answer["error"]["code"] == "limit_exceeded"
        assert reader.started == 1  # the child answered; it was not stopped and started again
    finally:
        reader.close()


def test_the_mesh_process_answers_in_json_for_every_kind(sample_folder):
    reader = meshproc.MeshReader()
    try:
        part = reader.read(str(sample_folder / "block.ply"), str(sample_folder), 1_000_000, model_file=True)
        assert part["state"] == "ok" and part["data"].n_triangles == 12
        asm = reader.read(str(sample_folder / "pair.step"), str(sample_folder), 1_000_000, model_file=True)
        assert asm["state"] == "ok" and asm["data"].n_instances == 2
        assert asm["geometry"]["sources"] == ["bodies"]
        assert reader.started == 1  # one child, kept for the next read
    finally:
        reader.close()


def test_the_window_never_unpickles_what_a_child_sends():
    for module in (meshproc, printing):
        code = Path(module.__file__).read_text(encoding="utf-8")
        assert re.findall(r"conn\.recv\(", code) == [], module.__name__
        assert re.findall(r"\.send\(", code) == [], module.__name__
        assert re.findall(r"import pickle|\bpickle\.|\.recv\(\)", code) == [], module.__name__


def test_an_answer_that_does_not_hold_together_is_refused():
    good = {"n_vertices": 3, "n_triangles": 1, "bbox": [[0, 0, 0], [1, 1, 1]]}
    meshproc.check_mesh(good, bytes(36), bytes(36), bytes(12))
    for header, sizes in (
        (good, (36, 36, 24)),
        (good, (24, 36, 12)),
        ({**good, "n_vertices": -1}, (36, 36, 12)),
        ({**good, "bbox": [[0, 0], [1, 1]]}, (36, 36, 12)),
        ({**good, "bbox": [[0, 0, float("nan")], [1, 1, 1]]}, (36, 36, 12)),
        ("not an object", (36, 36, 12)),
    ):
        with pytest.raises(meshproc.BadAnswer):
            meshproc.check_mesh(header, *(bytes(n) for n in sizes))
    with pytest.raises(meshproc.BadAnswer):  # a triangle naming a vertex past the end
        meshproc.check_mesh(good, bytes(36), bytes(36), (7).to_bytes(4, "little") * 3)


# --------------------------------------------------------------------------- exports
def test_export_for_3d_printing_writes_stl_and_3mf_in_its_own_process(sample_folder, tmp_path):
    before = _state(sample_folder)
    out = tmp_path / "out"
    out.mkdir()
    for name, triangles in (("pair.3mf", 36), ("pair.AD_ASM", 24), ("bracket.x_b", 12)):
        for fmt in ("stl", "3mf"):
            own = out / f"{name}_{fmt}"
            own.mkdir()
            request = {
                "path": str(sample_folder / name),
                "folder": str(sample_folder),
                "fmt": fmt,
                "out_dir": str(own),
                "within": str(sample_folder),
                "name": name,
            }
            result = printing.export_in_process(request)
            assert result["ok"], result
            data = result["data"]
            assert data["closed"] and data["triangles"] == triangles, (name, fmt)
            assert Path(data["file"]).parent == own and os.path.getsize(data["file"]) == data["bytes"]
            assert not [p for p in os.listdir(own) if p.endswith(".part")]
    # Never into the opened folder: the write guards refuse it.
    refused = printing.export_in_process(
        {
            "path": str(sample_folder / "box.stl"),
            "folder": str(sample_folder),
            "fmt": "stl",
            "out_dir": str(sample_folder),
        }
    )
    assert not refused["ok"] and refused["error"]["code"] == "output_refused"
    assert _state(sample_folder) == before


def test_a_3mf_or_stl_opens_as_it_is_when_the_program_takes_its_format():
    assert printing.as_is("plate.3mf", "3mf", "3mf") and printing.as_is("BOX.STL", "stl", "stl")
    assert not printing.as_is("plate.3mf", "stl", "3mf") and not printing.as_is("part.step", "3mf", "step")


def test_an_export_child_out_of_memory_answers_in_json(monkeypatch):
    def big(**request):
        raise MemoryError

    class Conn:
        def __init__(self) -> None:
            self.sent: list[bytes] = []

        def recv_bytes(self, maxlength=None):
            return json.dumps({"path": "x", "out_dir": "y"}).encode()

        def send_bytes(self, value) -> None:
            self.sent.append(value)

    monkeypatch.setattr(printing, "export_to_folder", big)
    conn = Conn()
    printing._export_serve(conn)
    assert [json.loads(s) for s in conn.sent] == [{"ok": False, "error": printing.TOO_LARGE}]


# --------------------------------------------------------------------------- wording and rows
def test_what_cannot_be_read_is_said_plainly():
    def err(rule, value):
        return {"code": "format_not_supported", "detail": {"rule": rule, "value": value}}

    assert "a VRML file" in wording.not_supported_text(err("no_reader", "vrml"))
    needs = wording.not_supported_text(err("needs_extension", "iges"))
    assert "IGES files with the OCCT backend extension" in needs and "Tools > Extensions" in needs
    assert "not a STEP model" in wording.not_supported_text(err("private_schema", "ALIBRE_SCHEMA"))
    assert "schema file" in wording.not_supported_text(err("schema_not_embedded", "parasolid"))
    text = wording.error_message({"code": "damaged_file"}, path=r"C:\x\bracket.stp")
    assert "whole STEP file" in text and "SOLIDWORKS" not in text
    assert "SOLIDWORKS" in wording.error_message({"code": "damaged_file"}, path=r"C:\x\a.SLDPRT")
    entry = {"path": "scene.wrl", "type": "file", "status": "unsupported", "model": {"format_name": "VRML"}}
    assert wording.status_short(entry) == "Format not read yet"
    assert "cannot read that format yet" in wording.unread_text(entry)
    iges = {
        "path": "sheet.igs",
        "type": "file",
        "status": "unsupported",
        "model": {"format": "iges", "format_name": "IGES"},
    }
    assert wording.status_short(iges) == "Needs the OCCT backend"
    text = wording.unread_text(iges)
    assert "IGES files with the OCCT backend extension" in text and "Tools > Extensions" in text
    ok = {"path": "a.stl", "type": "file", "status": "ok", "warnings": [{"code": "units_assumed"}]}
    assert wording.status_short(ok) == ""  # the unit an STL cannot state is not news on every row


def test_messages_name_the_right_menu_and_what_was_searched():
    from solidseas_app.viewer import navigate

    entry = {"path": "a.wrl", "type": "file", "status": "unsupported", "detected": "vrml"}
    assert "View > Show > Files SolidSeas Cannot Read" in wording.unread_text(entry)
    # an IGES file is listed whatever that setting says, so its text names only what it needs
    iges = {"path": "a.igs", "type": "file", "status": "unsupported", "detected": "iges"}
    assert "Files SolidSeas Cannot Read" not in wording.unread_text(iges)
    renamed = {"path": "b.SLDPRT", "type": "file", "status": "not_solidworks", "detected": "step"}
    step = wording.unread_text(renamed)
    assert "View > Show > All 3D Files" in step and "SOLIDWORKS documents only" not in step
    no_solid = {"code": "nothing_to_export", "detail": {"rule": "no_solid"}}
    assert "only open surfaces" in wording.error_message(no_solid, path=r"C:\x\band.step")
    assert wording.unusable({"code": "damaged_file", "retryable": False})
    assert not wording.unusable({"code": "timeout", "retryable": True})
    assert not wording.unusable({"code": "interrupted"}) and not wording.unusable(None)
    assert "whole STL file" in wording.first_sentence({"code": "damaged_file"}, r"C:\x\g.stl")
    # what was searched for a file a model file names
    missing = {"status": "missing", "warnings": []}
    component = {"key": "{g}", "file_name": "cube", "kind": "component", "resolution": missing}
    t = navigate.target(component, key="{g}", model=True)
    assert t.kind == navigate.MISSING and "document GUID" in t.why
    assert "opened folder was not searched" in t.why and "No file of that name" not in t.why
    sw = navigate.target({**component, "kind": None}, key="{g}")
    assert "No file of that name was found" in sw.why  # a SOLIDWORKS reference keeps its wording
    buffer = {"key": "buffer:0", "file_name": "b.bin", "kind": "buffer", "resolution": missing}
    assert "document's own folder" in navigate.target(buffer, key="buffer:0", model=True).why
    refused = {**buffer, "resolution": {"status": "refused", "warnings": []}}
    assert "link" in navigate.target(refused, key="buffer:0", model=True).why


def _entry(name, fmt, doc_type="part", status="ok", **model):
    return {
        "path": name,
        "type": "file",
        "status": status,
        "doc_type": doc_type,
        "file": {"size": 1, "mtime_ns": "1", "modified_utc": None},
        "warnings": [],
        "model": {"format": fmt, "format_name": fmt.upper(), "readable": status == "ok", **model},
    }


@needs_qt
def test_rows_name_their_format_and_family():
    from solidseas_app.viewer.documents import Row

    step = Row.make(_entry("a.step", "step", "assembly", variant="AP214"), None)
    assert step.display[1] == "STEP assembly" and step.display[3] == "AP214" and step.family == "exchange"
    alibre = Row.make(
        _entry("c.AD_PRT", "alibre", application={"name": "Alibre Design", "version": "9"}), None
    )
    assert alibre.display[1] == "Alibre part" and alibre.display[3] == "Alibre 9"
    stl = Row.make(_entry("b.stl", "stl", variant="binary"), None)
    assert (stl.display[1], stl.display[3]) == ("STL", "binary")
    sw = Row.make({**_entry("p.SLDPRT", "x"), "model": None, "format": "modern"}, None)
    assert sw.format == "solidworks" and not sw.is_model
    # the quick filter files each by what the listing read it as (.filetypes)
    types = (step.file_type, stl.file_type, alibre.file_type, sw.file_type)
    assert types == ("step", "stl", "ad_prt", "sldprt")


@needs_qt
def test_a_row_whose_geometry_is_unreadable_says_so_and_icons_line_up(app):
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QColor

    from solidseas.formats._source import encode_png
    from solidseas_app.viewer.documents import GEOMETRY_UNREADABLE, NAME, STATUS, DocumentModel

    def png(w, h):
        return encode_png(w, h, bytes(w * h * 3), 3)

    m = DocumentModel()
    m.append(
        [
            (_entry("g.stl", "stl"), None),
            (_entry("sq.3mf", "3mf"), png(48, 48)),
            (_entry("w.3mf", "3mf"), png(64, 48)),
        ]
    )
    assert m.data(m.index(0, STATUS)) == ""  # listed as read: the listing only opened it
    m.mark_unusable(0, "The file is damaged or incomplete.")
    assert m.data(m.index(0, STATUS)) == GEOMETRY_UNREADABLE
    assert m.data(m.index(0, NAME), Qt.ItemDataRole.ForegroundRole) == QColor("#c62828")
    assert "damaged" in m.data(m.index(0, NAME), Qt.ItemDataRole.ToolTipRole)
    # a square stored image is drawn in a 4:3 icon, as wide as a 4:3 one at any icon size
    for want in (QSize(128, 96), QSize(48, 36)):
        square, wide = (m.icon(i).actualSize(want) for i in (1, 2))
        assert square == wide and square.width() * 3 == square.height() * 4


@needs_qt
def test_the_3d_view_and_the_components_tab_speak_of_the_file_shown(app):
    """The 3D view's error names the format, not SOLIDWORKS; a model file's rows say what a
    double-click does only where there is a file to go to; counts say objects."""
    from solidseas_app.viewer.details import DetailsPanel
    from solidseas_app.viewer.preview import controls_text, files_text

    d = DetailsPanel()
    p = d.preview
    p.reset("part", key=(r"C:\models\garbage.stl", "garbage.stl"))
    assert p.document_path == r"C:\models\garbage.stl"
    p.mesh_state = "loading"
    p.set_mesh_result({"state": "error", "model": True, "error": {"code": "damaged_file"}})
    text = p.model_message.text()
    assert "whole STL file" in text and "SOLIDWORKS" not in text
    sw_tip = d.instances.headerItem().toolTip(0)
    assert "Double-click a part" in sw_tip
    d.set_model_file(True)
    tip = d.instances.headerItem().toolTip(0)
    assert "object inside this file has no file to go to" in tip and "Double-click a part" not in tip
    d.set_model_file(False)
    assert d.instances.headerItem().toolTip(0) == sw_tip
    assert "double-click it to open its file" in controls_text("standard", assembly=True)
    assert "double-click" not in controls_text("standard", assembly=True, opens_files=False).split("fits;")[1]
    assert (files_text(3, 3), files_text(3, 1), files_text(2)) == (
        "3 objects",
        "2 files and 1 object",
        "2 files",
    )
    d.deleteLater()


# --------------------------------------------------------------------------- the window, offscreen
@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from solidseas_app.viewer.app import use_system_fonts

    use_system_fonts()
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _wait(app, condition, timeout: float = 120.0) -> None:
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            raise AssertionError("timed out waiting for the viewer")
        app.processEvents()
        time.sleep(0.005)


@pytest.fixture
def window(app):
    from solidseas_app.viewer.window import MainWindow

    w = MainWindow()
    w.show()
    w.finished_generations = []
    w.detailsFinished.connect(w.finished_generations.append)
    yield w
    assert w.shutdown()
    w.close()
    w.deleteLater()
    app.processEvents()


def _open(app, w, folder: Path) -> dict:
    w.open_folder(str(folder))
    _wait(app, lambda: w.listing_info is not None)
    return w.listing_info


def _select(app, w, name: str) -> None:
    before = w.generation
    assert w.select_document(name), name
    _wait(app, lambda: any(g > before for g in w.finished_generations) and w._details is None)


@needs_qt
def test_every_format_is_listed_with_its_type_and_filtered(app, window, sample_folder):
    before = _state(sample_folder)
    w = window
    info = _open(app, w, sample_folder)
    assert info["ok"] and info["counts"]["ok"] == len(samples.EXPECTED) and info["counts"]["unsupported"] == 1
    rows = {r.name: r for r in w.model.rows}
    assert (
        rows["pair.step"].display[1] == "STEP assembly"
        and rows["pair.AD_ASM"].display[1] == "Alibre assembly"
    )
    assert rows["sheet.igs"].entry["status"] == "unsupported"
    # The IGES file is listed, greyed, while the OCCT backend extension is off, with Files
    # SolidSeas Cannot Read off too: its row, the quick filter and the status bar say what
    # opens it.
    shown = {w.proxy.mapToSource(w.proxy.index(i, 0)).row() for i in range(w.proxy.rowCount())}
    assert w.model.find("sheet.igs") in shown and not w.settings.show_unreadable
    assert rows["sheet.igs"].display[2] == "Needs the OCCT backend"
    assert "1 IGES file needs the OCCT backend extension (Tools > Extensions)" in w.status_label.text()
    assert "cannot read" not in w.status_label.text()
    # The quick filter offers a button for every format listed, in its order.
    bar = w.quick
    readable = ["step", "stl", "3mf", "x_t", "x_b", "sab", "obj", "ply", "off", "gltf", "glb", "amf"]
    assert bar.keys() == [*readable, "ad_prt", "ad_asm", "iges"]
    assert w.proxy.rowCount() == len(samples.EXPECTED) + 1
    assert "with the OCCT backend extension (Tools > Extensions)" in bar.tooltip_text("iges")
    w.change_settings(show_unreadable=True)  # nothing more to show here
    assert w.proxy.rowCount() == len(samples.EXPECTED) + 1 and bar.keys()[-1] == "iges"
    assert bar.tooltip_text("x_t").startswith("Parasolid text (X_T, XMT_TXT)\n1 file in the folder shown")
    # It is the one filter by type: a family is several buttons on at once.
    bar.set_selected({"ad_prt", "ad_asm"})
    assert w.proxy.rowCount() == 2
    bar.set_selected({"stl", "obj", "ply", "off", "gltf", "glb", "amf", "3mf"})
    assert w.proxy.rowCount() == 8  # STL, OBJ, PLY, OFF, glTF, GLB, AMF, 3MF
    bar.set_selected({"iges"})
    assert w.proxy.rowCount() == 1
    w.change_settings(show_unreadable=False)  # an IGES file stays listed, and its type on
    assert bar.selected() == {"iges"} and w.proxy.rowCount() == 1
    bar.set_selected(())
    assert w.proxy.rowCount() == len(samples.EXPECTED) + 1
    assert not hasattr(w, "type_combo")
    assert "3D files read" in w.status_label.text()
    # The thumbnails: stored ones with the listing, the others drawn in the worker pool and cached.
    _wait(app, lambda: not w.thumbnailer.active and not w.thumbnailer._busy)
    assert all(r.thumb is not None for r in w.model.rows if r.entry["status"] == "ok")
    assert w.thumbnailer.report()["drawn"] == 12
    _open(app, w, sample_folder)
    _wait(app, lambda: not w.thumbnailer.active and not w.thumbnailer._busy)
    assert w.thumbnailer.report()["cached"] == 12 and w.thumbnailer.report()["drawn"] == 0
    # Turned off, the listing is SOLIDWORKS documents only again, and no model file is read.
    w.change_settings(show_all_formats=False)
    _wait(app, lambda: w.listing_info is not None and w._listing is None)
    assert w.model.rows == []
    assert _state(sample_folder) == before


VRML = b"#VRML V2.0 utf8\nShape {}\n"  # a format SolidSeas lists but cannot read


@needs_qt
def test_the_folder_tree_counts_files_it_cannot_read_only_while_they_are_listed(app, window, tmp_path):
    """The folder tree's counts, and the columns fitted to the rows, leave out the files of
    formats SolidSeas cannot read while Files SolidSeas Cannot Read hides them, as they do
    hidden lock files. An IGES file, which the OCCT backend extension opens, is always
    listed and counted."""
    from solidseas_app.viewer.documents import STATUS

    every = tmp_path / "every"
    samples.write_samples(str(every))
    folder = tmp_path / "samples"
    (folder / "sub").mkdir(parents=True)
    for name in ("box.stl", "bracket.step"):  # neither read with a warning
        (folder / name).write_bytes((every / name).read_bytes())
    (folder / "scene.wrl").write_bytes(VRML)
    (folder / "sub" / "scene.wrl").write_bytes(VRML)
    w = window
    read = 2
    info = _open(app, w, folder)
    assert info["ok"] and info["counts"]["unsupported"] == 2
    root, sub = w._folders[""], w._folders["sub"]
    assert root.text(0) == f"samples ({read})" and sub.text(0) == "sub (0)"
    assert "listed" not in root.toolTip(0)
    header = w.table.horizontalHeader()
    assert header.isSectionHidden(STATUS)  # only the hidden files have a status to show
    w.change_settings(show_unreadable=True)
    assert root.text(0) == f"samples ({read} of {read + 2})" and sub.text(0) == "sub (0 of 1)"
    assert f"{read} documents read, {read + 2} entries listed" in root.toolTip(0)
    assert not header.isSectionHidden(STATUS)
    w.change_settings(show_unreadable=False)
    assert root.text(0) == f"samples ({read})" and sub.text(0) == "sub (0)"
    assert header.isSectionHidden(STATUS)
    # an IGES file is listed and counted with the setting off, and its Status shown
    (folder / "sub" / "sheet.igs").write_bytes((every / "sheet.igs").read_bytes())
    w.reindex()
    _wait(app, lambda: w._listing is None)
    root, sub = w._folders[""], w._folders["sub"]
    assert root.text(0) == f"samples ({read} of {read + 1})" and sub.text(0) == "sub (0 of 1)"
    assert not header.isSectionHidden(STATUS)
    assert "2 files of formats SolidSeas cannot read (hidden)" in w.status_label.text()


@needs_qt
def test_each_format_shows_the_details_that_fit_it(app, window, sample_folder):
    from solidseas_app.viewer import whereused as wording_where_used
    from solidseas_app.viewer.details import TABS

    w = window
    d = w.details
    _open(app, w, sample_folder)
    _select(app, w, "box.stl")
    assert d.model_file and d.pages["Overview"].showing_content
    assert not any(d.tabs.isTabVisible(TABS.index(t)) for t in ("BOM", "Paths"))
    assert d.tabs.isTabVisible(TABS.index("Where Used"))  # the index holds STL files too
    assert d.pages["Where Used"].message_text.startswith("Indexing of opened folders is off")
    assert d.geometry["size_mm"] == pytest.approx(list(samples.BOX))
    assert "no components" in d.pages["Components"].message_text
    assert d.sections["preview"]["data"]["source"] == "rendered" and w.act_preview.isEnabled()
    assert w.act_export_print.isEnabled() and w.act_print.isEnabled() and not w.act_parasolid.isEnabled()
    assert not w.act_step.isEnabled() and w.act_step.toolTip().startswith("STL files hold triangles")
    assert json.loads(d.summary_json)["kind"] == "model_summary"
    _select(app, w, "pair.3mf")
    assert d.pages["Components"].showing_content and d.instances.topLevelItemCount() == 3
    assert [d.files.topLevelItem(i).text(0) for i in range(d.files.topLevelItemCount())] == ["box", "block"]
    assert d.sections["preview"]["data"]["source"] == "stored"
    # An object of the file has no Open or Go to file: there is no file of its own to go to.
    item = d.instances.topLevelItem(0)
    texts = [a.text() for a in d.component_menu(item).actions()]
    assert not d.request(item) and "Go to file" not in texts and not any(t.startswith("Open") for t in texts)
    _select(app, w, "pair.AD_ASM")
    assert d.pages["References"].showing_content
    assert d.references.topLevelItem(0).text(1) == "found"
    # A component found by its document GUID opens as a SOLIDWORKS component's file does.
    d.request(d.instances.topLevelItem(0))
    _wait(app, lambda: d.title.text() == "cube.AD_PRT" and w._details is None)
    assert w.history and w.go_back()
    _wait(app, lambda: d.title.text() == "pair.AD_ASM" and w._details is None)
    w.change_settings(show_unreadable=True)
    _select(app, w, "sheet.igs")
    assert "IGES files with the OCCT backend extension" in d.pages["Overview"].message_text
    assert d.pages["Where Used"].message_text == wording_where_used.not_indexed_text("iges")
    assert "only with the OCCT backend extension" in d.pages["Where Used"].message_text
    assert "cannot read VRML files yet" in wording_where_used.not_indexed_text("vrml")


@needs_qt
def test_opening_a_model_file_lists_its_format_first(app, window, sample_folder, tmp_path):
    """A file of another format opened by name (File > Open File..., a file dropped on the
    window, the command line) is listed and selected even with All 3D Files off; one of a
    format SolidSeas cannot read is listed, with Files SolidSeas Cannot Read, to say why. An
    IGES file is listed without that setting, and says what opens it."""
    w = window
    w.change_settings(show_all_formats=False)
    w.open_path(str(sample_folder / "pair.step"))
    _wait(app, lambda: w.listing_info is not None and w._details is None and w.details.summary is not None)
    assert w.settings.show_all_formats and not w.settings.show_unreadable
    assert w.details.title.text() == "pair.step"
    w.open_path(str(sample_folder / "sheet.igs"))
    _wait(app, lambda: w.listing_info is not None and w.details.title.text() == "sheet.igs")
    assert not w.settings.show_unreadable
    assert "OCCT backend extension" in w.details.pages["Overview"].message_text
    (tmp_path / "scene.wrl").write_bytes(VRML)
    w.open_path(str(tmp_path / "scene.wrl"))
    _wait(app, lambda: w.listing_info is not None and w.details.title.text() == "scene.wrl")
    assert w.settings.show_unreadable
    assert "cannot read that format yet" in w.details.pages["Overview"].message_text


@needs_qt
def test_a_damaged_model_file_says_why_in_its_format_s_words(app, window, tmp_path):
    folder = tmp_path / "damaged"
    folder.mkdir()
    (folder / "broken.step").write_bytes(
        b"ISO-10303-21;\nHEADER;\nFILE_SCHEMA(('ALIBRE_SCHEMA'));\nENDSEC;\n"
    )
    (folder / "nothing.stl").write_bytes(b"solid x\nendsolid x\n")
    w = window
    _open(app, w, folder)
    for name in ("broken.step", "nothing.stl"):
        _select(app, w, name)
        text = w.details.pages["Overview"].message_text or w.details.pages["Preview"].message_text
        assert "SOLIDWORKS" not in text, (name, text)


@needs_qt
def test_a_listed_file_whose_geometry_cannot_be_read_is_marked(app, window, tmp_path):
    """The listing only opens a file; when its thumbnail or its details find the geometry
    unreadable, the row says so, and the Overview does not promise a drawn preview."""
    from solidseas_app.viewer.documents import GEOMETRY_UNREADABLE, STATUS

    folder = tmp_path / "unusable"
    folder.mkdir()
    (folder / "garbage.stl").write_bytes(b"solid x\nthis is not an STL statement\nendsolid x\n")
    (folder / "box.stl").write_bytes(samples.stl_binary())
    w = window
    _open(app, w, folder)
    garbage = w.model.find("garbage.stl")
    assert w.model.rows[garbage].display[STATUS] == ""  # listed: the listing only opened it
    _wait(app, lambda: not w.thumbnailer.active and not w.thumbnailer._busy)
    assert w.model.rows[garbage].display[STATUS] == GEOMETRY_UNREADABLE
    assert w.model.rows[w.model.find("box.stl")].display[STATUS] == ""
    _select(app, w, "garbage.stl")
    _wait(app, lambda: w.details.geometry_error is not None)
    o = w.details.overview
    lines = {}
    for i in range(o.topLevelItemCount()):
        group = o.topLevelItem(i)
        for k in range(group.childCount()):
            lines[group.child(k).text(0)] = group.child(k).text(1)
    assert "none can be drawn either" in lines["Stored preview"]
    assert "draws one from the geometry" not in lines["Stored preview"]


@needs_qt
def test_the_window_parses_no_model_file_itself(sample_folder, tmp_path):
    """A child process lists the samples and shows each one's details offscreen, then says
    which reader modules it imported: none, every byte having been read by its workers."""
    script = f"""
import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["SOLIDSEAS_CACHE_DIR"] = {str(tmp_path / "cache")!r}
from PySide6.QtWidgets import QApplication
from solidseas_app.viewer.window import MainWindow

def main():
    app = QApplication([])
    w = MainWindow()
    done = []
    w.detailsFinished.connect(done.append)
    w.open_folder({str(sample_folder)!r})
    end = time.monotonic() + 120
    def wait(cond):
        while not cond():
            if time.monotonic() > end:
                raise SystemExit("timed out")
            app.processEvents()
            time.sleep(0.01)
    wait(lambda: w.listing_info is not None)
    for r in [r for r in w.model.rows if r.entry["status"] == "ok"]:
        g = w.generation
        w.select_document(r.entry["path"])
        wait(lambda: any(x > g for x in done) and w._details is None)
    wait(lambda: not w.thumbnailer.active and not w.thumbnailer._busy)
    readers = sorted(m for m in sys.modules if m.split(".")[:2] == ["solidseas", "formats"]
                     and len(m.split(".")) > 2 and m.split(".")[2] in {READERS!r})
    print("READERS", readers, w.models.started)
    w.shutdown()

if __name__ == "__main__":
    main()
"""
    path = tmp_path / "child.py"
    path.write_text(script, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": SRC, "QT_QPA_PLATFORM": "offscreen"}
    proc = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, timeout=300, env=env)
    line = next((x for x in proc.stdout.splitlines() if x.startswith("READERS")), None)
    assert proc.returncode == 0 and line is not None, proc.stderr[-2000:]
    assert line == "READERS [] 1", line


@needs_qt
def test_the_formats_self_test_offscreen(tmp_path):
    """Without OpenGL: every format lists, previews and exports (the 3D view is the
    display test below)."""
    report = tmp_path / "report.json"
    env = {**os.environ, "PYTHONPATH": SRC, "QT_QPA_PLATFORM": "offscreen", "APPDATA": str(tmp_path)}
    proc = subprocess.run(
        [sys.executable, "-m", "solidseas_app", "--self-test-formats", "--report", str(report)],
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
    )
    assert "Traceback" not in proc.stderr, proc.stderr[-3000:]
    r = json.loads(report.read_text(encoding="utf-8"))
    assert proc.returncode == 0 and r["ok"], r
    assert set(r["files"]) == set(samples.EXPECTED)
    assert all(f["exports"]["stl"]["ok"] and f["exports"]["3mf"]["ok"] for f in r["files"].values())
    for name, f in r["files"].items():
        prints = {k: f["exports"][k] for k in ("print", "print_stl", "print_step")}
        assert all(p["ok"] for p in prints.values()), (name, prints)
        assert (prints["print"]["format"], prints["print_stl"]["format"]) == ("3mf", "stl")
        fmt, doc_type = samples.EXPECTED[name][:2]
        if fmt == "parasolid" and doc_type == "part":
            assert prints["print_step"]["format"] == "step" and prints["print_step"]["read_back"] == "step"
        else:
            assert prints["print_step"]["format"] == "3mf" and prints["print_step"]["fallback"], name
        assert "not indexed" not in f["where_used"], name  # the index holds every format SolidSeas reads
        assert f["export_step"]["enabled"] == (fmt == "parasolid" and doc_type == "part"), name


@needs_qt
def test_the_formats_self_test_on_the_display(tmp_path):
    """On the real display, with OpenGL: each sample drawn and read back, an assembly's
    instance picked by a click, exploded and hidden (``gl_support.run_self_test``)."""
    from gl_support import run_self_test

    shots = tmp_path / "shots"
    r = run_self_test(
        ["--self-test-formats", "--3d", "--screenshot-dir", str(shots)], shots, appdata=tmp_path
    )
    assert r["opengl"]["available"]
    for name, f in r["files"].items():
        view = f["view_3d"]
        assert view["state"] == "ready" and view["covered"] > 0.01, name
        # the view cube's clicks and Home, and a turn about the point under the pointer
        nav = view["navigation"]
        assert [c["viewcube"] for c in nav["viewcube"]] == ["top", "front-top-right", "home"], name
        assert not any("failed" in c for c in nav["viewcube"]), (name, nav["viewcube"])
        assert "failed" not in nav["pivot"] and max(abs(v) for v in nav["pivot"]["kept"]) <= 0.5, name
        if samples.EXPECTED[name][1] == "assembly":
            assert view["pick"]["picked"] == [view["pick"]["instance"]] and view["explode"]["moving"], name
            assert view["hide"] == {"hidden": True, "shown_again": True}, name
    assert len(r["screenshots"]) >= 3 * len(samples.EXPECTED)
