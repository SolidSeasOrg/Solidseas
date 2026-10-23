"""The OBJ reader with MTL colours (``docs/formats/mesh.md``): synthetic files from
``tests/mesh_writers.py``, polygons, groups, material libraries beside the file and
the shared polygon and colour helpers."""

import os

import pytest

import mesh_writers as mw
from model_writers import Item, Scene, box, holed_block, two_object_assembly
from solidseas import export
from solidseas.errors import PathRefusedError, SldFormatError, SldLimitError
from solidseas.formats import Limits, open_model
from solidseas.formats._source import Clock
from solidseas.formats.obj import polygon_triangles, split_application, split_colors


def _write(folder, name: str, data: bytes, siblings: dict) -> object:
    for k, v in siblings.items():
        (folder / k).parent.mkdir(parents=True, exist_ok=True)
        (folder / k).write_bytes(v)
    (folder / name).write_bytes(data)
    return folder / name


@pytest.mark.parametrize("corners", ["plain", "slashes", "normals"])
@pytest.mark.parametrize("statement", ["o", "g"])
def test_the_neutral_scene_reads_with_its_groups_and_colours(tmp_path, corners, statement):
    scene = two_object_assembly()
    data, sib = mw.obj(scene, corners=corners, statement=statement)
    path = _write(tmp_path, "s.obj", data, sib)
    with open_model(path) as doc:
        assert (doc.format, doc.variant, doc.doc_type) == ("obj", None, "part")
        assert doc.units == {"length": "mm", "scale_m": 0.001, "source": "assumed"}
        assert "units_assumed" in mw.codes(doc.warnings)
        assert doc.properties[0].name == "comment"
        assert mw.scene_volume(doc) == pytest.approx(20000e-9, rel=1e-12)
        s = doc.scene()
        assert [o.name for o in s.objects] == ["box 1", "box 2", "block 1"]
        assert [o.color for o in s.objects] == [
            (0.8, 0.1, 0.1, 1.0),
            (0.8, 0.1, 0.1, 1.0),
            (0.1, 0.2, 0.8, 1.0),
        ]
        assert "textures_ignored" in mw.codes(s.warnings)
        nodes = doc.tree().nodes
        assert [(n.id, n.name, n.object) for n in nodes] == [
            ("1", "box 1", 0),
            ("2", "box 2", 1),
            ("3", "block 1", 2),
        ]
        (ref,) = doc.references()
        assert (ref.kind, ref.stored, ref.resolution["status"]) == (
            "material_library",
            "materials.mtl",
            "found",
        )
        pm = export.print_model(doc)
    assert pm.closed and pm.measures()["volume_m3"] == pytest.approx(20000e-9)


def test_negative_indices_count_back_from_the_last_vertex(tmp_path):
    data, sib = mw.obj(two_object_assembly(), negative=True)
    with open_model(_write(tmp_path, "n.obj", data, sib)) as doc:
        assert mw.scene_volume(doc) == pytest.approx(20000e-9, rel=1e-12)


def test_quads_and_a_concave_polygon_are_cut_right():
    with open_model(mw.obj_quads_box(), name="q.obj") as doc:
        s = doc.scene()
        assert [o.n_triangles for o in s.objects] == [12, 20]
        assert [o.measures()["volume_m3"] for o in s.objects] == pytest.approx([6000e-9, 1500e-9], rel=1e-12)
        pm = export.print_model(doc)
    assert pm.closed


def test_a_group_name_used_again_adds_to_its_group():
    text = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\ng a\nf 1 3 2\ng b\nf 1 2 4\ng a\nf 1 4 3\ng b\nf 2 3 4\n"
    with open_model(text, name="t.obj") as doc:
        s = doc.scene()
        assert [(o.name, o.n_triangles) for o in s.objects] == [("a", 2), ("b", 2)]
        assert doc.scene().counts["triangles"] == 4


def test_faces_before_any_group_are_the_files_own_object():
    text = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
    with open_model(text, name="plain.obj") as doc:
        (obj,) = doc.scene().objects
        assert obj.name == "plain" and obj.color is None


def test_material_libraries_are_read_only_from_the_documents_folder(tmp_path):
    scene = Scene([box(1, 1, 1, color=(1.0, 0.0, 0.0, 1.0))], [Item(0)])
    data, sib = mw.obj(scene, mtl="../outside.mtl")
    (tmp_path / "outside.mtl").write_bytes(b"newmtl mat0\nKd 1 0 0\n")
    inner = tmp_path / "inner"
    inner.mkdir()
    path = inner / "x.obj"
    path.write_bytes(data)
    with open_model(path) as doc:
        s = doc.scene()
        assert [o.color for o in s.objects] == [None] and "material_library_unread" in mw.codes(s.warnings)
        (ref,) = doc.references()
        assert ref.resolution["status"] == "refused"
    data, sib = mw.obj(scene, mtl="missing.mtl")
    path.write_bytes(data)
    with open_model(path) as doc:
        assert "material_library_unread" in mw.codes(doc.scene().warnings)
        assert doc.references()[0].resolution["status"] == "not_found"
    data, sib = mw.obj(scene, mtl="sub/colours.mtl")
    with open_model(_write(inner, "y.obj", data, sib)) as doc:
        assert doc.scene().objects[0].color == (1.0, 0.0, 0.0, 1.0)
        assert doc.references()[0].resolution["path"] == "sub/colours.mtl"  # never a path on this machine
    # a library with a second name outside the folder: read unless the document refuses hard links
    os.link(tmp_path / "outside.mtl", inner / "linked.mtl")
    data, sib = mw.obj(scene, mtl="linked.mtl")
    path.write_bytes(data)
    with open_model(path) as doc:
        assert doc.scene().objects[0].color == (1.0, 0.0, 0.0, 1.0)
    with open_model(path, refuse_hard_links=True) as doc:
        s = doc.scene()
        assert [o.color for o in s.objects] == [None] and "material_library_unread" in mw.codes(s.warnings)
        assert doc.references()[0].resolution["status"] == "refused"
    with open_model(data, name="bytes.obj") as doc:  # bytes have no folder: no library is read
        assert "material_library_unread" in mw.codes(doc.scene().warnings)
        assert doc.references()[0].resolution["status"] == "not_found"


def test_mtl_colours_opacity_and_texture_maps(tmp_path):
    (tmp_path / "m.mtl").write_bytes(
        b"newmtl a\nKd 0.2 0.4 0.6\nd 0.5\nmap_Kd t.png\n"
        b"newmtl b\nKd spectral f.rfl\nTr 0.25\nnewmtl c\nKd 2 -1 0.5\n"
    )
    text = (
        b"mtllib m.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\n"
        b"usemtl a\nf 1 3 2\nusemtl b\nf 1 2 4\nusemtl c\nf 1 4 3\nusemtl none\nf 2 3 4\n"
    )
    (tmp_path / "c.obj").write_bytes(text)
    with open_model(tmp_path / "c.obj") as doc:
        s = doc.scene()
        assert [o.color for o in s.objects] == [(0.2, 0.4, 0.6, 0.5), None, (1.0, 0.0, 0.5, 1.0)]
        assert [o.n_triangles for o in s.objects] == [1, 2, 1]  # b and the unknown material: no colour
        assert "textures_ignored" in mw.codes(s.warnings)


def test_comments_anywhere_and_continued_lines(tmp_path):
    bs = b"\\"
    (tmp_path / "m#1.mtl").write_bytes(
        b"# a library\nnewmtl red#2 # a name may hold a hash\nKd 1 0 0 # red\nd 0.5 # half\n"
        b"newmtl blue\nKd 0 0 1#glued\n"
    )
    text = (
        b"mtllib m#1.mtl # the library\n"
        b"v 0 0 0 # a vertex\nv 1 0 0#glued\nv 0 1 " + bs + b"\n 0\nv 0 0 1\n"
        b"# a comment that ends in a backslash does not continue " + bs + b"\n"
        b"o first # the first group\nusemtl red#2 # its material\n"
        b"f 1 3 2 # a face\nf 1 2 " + bs + b"\r\n 4\n"
        b"g second#2\nusemtl blue\nf 1 4 3#x\nf 2 3 " + bs + b"\n4 " + bs + b"\n"  # the last line continues
    )
    (tmp_path / "c.obj").write_bytes(text)
    with open_model(tmp_path / "c.obj") as doc:
        assert [r.stored for r in doc.references()] == ["m#1.mtl"]
        s = doc.scene()
        assert [(o.name, o.n_triangles, o.color) for o in s.objects] == [
            ("first", 2, (1.0, 0.0, 0.0, 0.5)),
            ("second#2", 2, (0.0, 0.0, 1.0, 1.0)),
        ]
        assert "material_library_unread" not in mw.codes(s.warnings)
        assert mw.scene_volume(doc) == pytest.approx(1e-9 / 6)
    long = b"f 1 " + bs + b"\n" + (b"2 2 2 2 " + bs + b"\n") * 15 + b"3\n"  # short lines, a long statement
    with open_model(
        b"v 0 0 0\nv 1 0 0\nv 0 1 0\n" + long, name="l.obj", limits=Limits(obj_line_bytes=100)
    ) as doc:
        with pytest.raises(SldLimitError) as exc:
            doc.scene()
    assert exc.value.detail["limit"] == "obj_line_bytes"


def test_points_lines_and_free_form_are_skipped_and_warned():
    text = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nl 1 2\np 3\ncstype bspline\ncurv 0 1 1 2\nend\ns 1\nf 1 2 3\nvp 0.5\n"
    with open_model(text, name="p.obj") as doc:
        s = doc.scene()
        assert s.counts["triangles"] == 1 and "primitives_skipped" in mw.codes(s.warnings)


def test_bad_faces_and_indices():
    text = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2\nf 1 2 3\nf 1 2 9\nf 1 1 2\nf -9 1 2\n"
    with open_model(text, name="b.obj") as doc:
        s = doc.scene()
        assert s.counts["triangles"] == 1
        obj = s.objects[0]
        assert {"indices_out_of_range", "degenerate_triangles_dropped"} <= mw.codes(obj.warnings)
        assert "degenerate_triangles_dropped" in mw.codes(s.warnings)  # the face of two corners
    for bad in (b"v 0 0\n", b"v 0 0 zero\n", b"v 0 0 0\nf 1 x 1\n"):
        with open_model(bad, name="d.obj") as doc:
            with pytest.raises(SldFormatError):
                doc.scene()


def test_the_bounds_of_an_obj():
    many = b"v 0 0 0\n" * 5 + b"f " + b" ".join(b"1" for _ in range(6)) + b"\n"
    with open_model(many, name="c.obj", limits=Limits(polygon_corners=5)) as doc:
        with pytest.raises(SldLimitError) as exc:
            doc.scene()
    assert exc.value.detail["limit"] == "polygon_corners"
    long = b"v 0 0 0 " + b"0" * 200 + b"\n"
    with open_model(long, name="l.obj", limits=Limits(obj_line_bytes=100)) as doc:
        with pytest.raises(SldLimitError) as exc:
            doc.scene()
    assert exc.value.detail["limit"] == "obj_line_bytes"
    mats = b"".join(b"usemtl m%d\n" % i for i in range(5))
    with open_model(mats, name="m.obj", limits=Limits(obj_materials=3)) as doc:
        with pytest.raises(SldLimitError) as exc:
            doc.scene()
    assert exc.value.detail["limit"] == "obj_materials"
    libs = b"".join(b"mtllib l%d.mtl\n" % i for i in range(5))
    with open_model(libs, name="m.obj", limits=Limits(obj_material_libraries=3)) as doc:
        with pytest.raises(SldLimitError) as exc:
            doc.scene()
    assert exc.value.detail["limit"] == "obj_material_libraries"
    data, _sib = mw.obj(holed_block(), mtl=None)
    with open_model(data, name="t.obj", limits=Limits(triangles=10)) as doc:
        with pytest.raises(SldLimitError):
            doc.scene()
    with open_model(data, name="t.obj") as doc:
        assert doc.scene(max_triangles=10).truncated == ("max_triangles",)


# --------------------------------------------------------------------------- the shared helpers
def test_polygon_triangles_keep_the_winding_and_fall_back_to_a_fan():
    clock = Clock(5.0)
    square = [0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0]
    assert polygon_triangles(square, [0, 1, 2, 3], clock) == [(0, 1, 2), (0, 2, 3)]
    # a concave arrow, counter-clockwise seen from +z: every triangle faces +z
    pts = [0, 0, 0, 4, 0, 0, 4, 4, 0, 2, 1, 0, 0, 4, 0]
    tris = polygon_triangles(pts, [0, 1, 2, 3, 4], clock)
    assert len(tris) == 3
    for a, b, c in tris:
        ux, uy = pts[3 * b] - pts[3 * a], pts[3 * b + 1] - pts[3 * a + 1]
        vx, vy = pts[3 * c] - pts[3 * a], pts[3 * c + 1] - pts[3 * a + 1]
        assert ux * vy - uy * vx > 0
    assert polygon_triangles(pts, [0, 1], clock) == []
    assert polygon_triangles(pts, [0, 1, 99, 2], clock) == [(0, 1, 99), (0, 99, 2)]  # a vertex not read yet
    line = [0, 0, 0, 1, 0, 0, 2, 0, 0, 3, 0, 0]
    assert polygon_triangles(line, [0, 1, 2, 3], clock) == [(0, 1, 2), (0, 2, 3)]


def test_split_colors_orders_merges_and_maps():
    lim = Limits()
    red, blue = (1.0, 0.0, 0.0, 1.0), (0.0, 0.0, 1.0, 1.0)
    assert split_colors(None, None, None, lim) == ([None], None, False)
    colors, assign, merged = split_colors(None, [None, blue, red, red], [2, 1, 3, 2], lim)
    assert colors == [red, blue] and assign == {2: 0, 1: 1, 3: 0} and not merged
    colors, assign, merged = split_colors(None, [red, blue], [0, 1, 1], Limits(colors_per_object=1))
    assert colors == [blue] and assign is None and merged
    assert split_colors(red, [blue], [0, 5], lim)[0] == [blue, red]  # an id past the palette has the default


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("SolidSeas 0.2.36", ("SolidSeas", "0.2.36")),
        ("Example Slicer-2.6.0", ("Example Slicer", "2.6.0")),
        ("Writer v3.6.27", ("Writer", "3.6.27")),
        ("Example CAD", ("Example CAD", None)),
        ("", (None, None)),
    ],
)
def test_split_application(text, want):
    got = split_application(text)
    assert (got["name"], got["version"]) == want


def test_a_sibling_uri_that_climbs_out_is_refused(tmp_path):
    from solidseas.formats._source import SiblingBudget, read_sibling

    for uri in (
        "../x.mtl",
        "/x.mtl",
        "C:/x.mtl",
        "//server/share/x.mtl",
        "file:x.mtl",
        "a/../../x.mtl",
        "x.mtl:alt",
    ):
        with pytest.raises(PathRefusedError):
            read_sibling(str(tmp_path / "d.obj"), uri, SiblingBudget(Limits()))


@pytest.mark.usefixtures("outbound_guard")
def test_python_cli_and_rest_give_the_same_model_summary(tmp_path, capsys):
    data, sib = mw.obj(two_object_assembly())
    _write(tmp_path, "s.obj", data, sib)
    (tmp_path / "q.obj").write_bytes(mw.obj_quads_box())
    mw.same_on_three_surfaces(tmp_path, ["s.obj", "q.obj"], "obj", capsys)


def test_material_libraries_are_counted_as_they_are_named():
    # the seventeenth library is refused where it is named, before the damaged line after it
    text = "".join(f"mtllib lib{i}.mtl\n" for i in range(17)) + "v x y z\n"
    with open_model(text.encode(), name="l.obj") as doc:
        with pytest.raises(SldLimitError) as exc:
            doc.scene()
    assert exc.value.detail["limit"] == "obj_material_libraries"
    # references() stops at its bound, before the over-long line after it
    text = "".join(f"mtllib r{i}.mtl\n" for i in range(4)) + "#" + "x" * 2000 + "\n"
    with open_model(text.encode(), name="r.obj", limits=Limits(references=3, obj_line_bytes=1000)) as doc:
        with pytest.raises(SldLimitError) as exc:
            doc.references()
    assert exc.value.detail["limit"] == "references"


def test_a_library_in_a_subfolder_is_read_only_when_subfolders_are(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "m.mtl").write_text("newmtl red\nKd 1 0 0\n")
    (tmp_path / "x.obj").write_text("mtllib sub/m.mtl\nusemtl red\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    with open_model(tmp_path / "x.obj") as doc:
        assert doc.scene().objects[0].color == (1.0, 0.0, 0.0, 1.0)
        assert doc.references()[0].resolution["status"] == "found"
    with open_model(tmp_path / "x.obj", subfolders=False) as doc:
        s = doc.scene()
        assert s.objects[0].color is None and "material_library_unread" in mw.codes(s.warnings)
        assert doc.references()[0].resolution["status"] == "refused"
