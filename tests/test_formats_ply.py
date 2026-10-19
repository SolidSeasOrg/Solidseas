"""The PLY reader (``docs/formats/mesh.md``): ASCII and both binary encodings of the
neutral scene from ``tests/mesh_writers.py``, colours, normals, elements it skips,
strips and polygons, and the header's bounds."""

import struct

import pytest

import mesh_writers as mw
from model_writers import box, holed_block, two_object_assembly
from solidseas import export
from solidseas.errors import SldFormatError, SldLimitError
from solidseas.formats import Limits, open_model

ENCODINGS = ["ascii", "binary_le", "binary_be"]


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_the_neutral_scene_reads_alike_in_every_encoding(encoding):
    scene = two_object_assembly()
    with open_model(mw.ply(scene, encoding=encoding, extra_element=True), name="s.ply") as doc:
        assert (doc.format, doc.variant, doc.doc_type, doc.kind) == ("ply", encoding, "part", "mesh")
        assert doc.units["source"] == "assumed" and "units_assumed" in mw.codes(doc.warnings)
        assert [(p.name, p.value) for p in doc.properties] == [
            ("comment", "invented PLY for the SolidSeas tests"),
            ("obj_info", "invented"),
        ]
        assert doc.counts()["vertices"] == 32
        assert mw.scene_volume(doc) == pytest.approx(20000e-9, rel=1e-6)
        (obj,) = doc.scene().objects
        assert obj.color is None and obj.normals is None
        pm = export.print_model(doc)
    assert pm.closed


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_face_and_vertex_colours_split_the_model(encoding):
    scene = two_object_assembly()
    for kw in ({"face_colors": True}, {"vertex_colors": True}):
        with open_model(mw.ply(scene, encoding=encoding, **kw), name="c.ply") as doc:
            s = doc.scene()
            assert [o.color for o in s.objects] == [
                (204 / 255, 26 / 255, 26 / 255, 1.0),
                (26 / 255, 51 / 255, 204 / 255, 1.0),
            ]
            assert [o.n_triangles for o in s.objects] == [24, 32]
            assert [n.object for n in doc.tree().nodes] == [0]
            assert mw.scene_volume(doc) == pytest.approx(20000e-9, rel=1e-6)
    with open_model(
        mw.ply(scene, encoding=encoding, face_colors=True), name="c.ply", limits=Limits(colors_per_object=1)
    ) as doc:
        s = doc.scene()
        assert len(s.objects) == 1 and "colors_ignored" in mw.codes(s.warnings)


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_normals_are_kept(encoding):
    with open_model(mw.ply(box(1, 2, 3), encoding=encoding, normals=True), name="n.ply") as doc:
        (obj,) = doc.scene().objects
        assert obj.normals is not None and len(obj.normals) == len(obj.positions)
        assert list(obj.normals[:3]) == [0.0, 0.0, 1.0]


@pytest.mark.parametrize("index_type", ["int", "uint", "ushort"])
def test_index_types(index_type):
    with open_model(mw.ply(holed_block(), encoding="binary_le", index_type=index_type), name="i.ply") as doc:
        assert mw.scene_volume(doc) == pytest.approx(holed_block().volume_mm3() * 1e-9, rel=1e-6)


def test_polygons_and_triangle_strips():
    quads = (
        b"ply\nformat ascii 1.0\nelement vertex 8\nproperty float x\nproperty float y\nproperty float z\n"
        b"element face 6\nproperty list uchar int vertex_index\nend_header\n"
        b"0 0 0\n1 0 0\n1 1 0\n0 1 0\n0 0 1\n1 0 1\n1 1 1\n0 1 1\n"
        b"4 0 3 2 1\n4 4 5 6 7\n4 0 1 5 4\n4 1 2 6 5\n4 2 3 7 6\n4 3 0 4 7\n"
    )
    with open_model(quads, name="q.ply") as doc:
        assert doc.scene().counts["triangles"] == 12 and mw.scene_volume(doc) == pytest.approx(1e-9)
    strips = (
        b"ply\nformat ascii 1.0\nelement vertex 4\nproperty float x\nproperty float y\nproperty float z\n"
        b"element tristrips 1\nproperty list int int vertex_indices\nend_header\n"
        b"0 0 0\n1 0 0\n0 1 0\n1 1 0\n"
        b"5 0 1 2 3 -1\n"
    )
    with open_model(strips, name="t.ply") as doc:
        (obj,) = doc.scene().objects
        assert list(obj.triangles) == [0, 1, 2, 2, 1, 3]  # both face +z
        assert obj.measures()["area_m2"] == pytest.approx(1e-6)


def test_points_only_and_degenerate_faces():
    pts = (
        b"ply\nformat ascii 1.0\nelement vertex 2\nproperty float x\nproperty float y\nproperty float z\n"
        b"end_header\n0 0 0\n1 1 1\n"
    )
    with open_model(pts, name="p.ply") as doc:
        s = doc.scene()
        assert s.counts["triangles"] == 0 and "primitives_skipped" in mw.codes(s.warnings)
    two = (
        b"ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\n"
        b"element face 3\nproperty list uchar int vertex_indices\nend_header\n0 0 0\n1 0 0\n0 1 0\n"
        b"2 0 1\n3 0 1 2\n3 0 1 7\n"
    )
    with open_model(two, name="d.ply") as doc:
        s = doc.scene()
        assert s.counts["triangles"] == 1
        assert "degenerate_triangles_dropped" in mw.codes(s.warnings)
        assert "indices_out_of_range" in mw.codes(s.objects[0].warnings)


def _strip_ply(encoding: str, n: int) -> tuple[bytes, int]:
    """A 2 x ``n`` grid of vertices as one strip in one tristrips row (as strip files hold
    the whole mesh), the row longer than polygon_corners: ``(file, triangles)``."""
    verts = [(float(i), float(j), 0.0) for i in range(n) for j in (0, 1)]
    strip = list(range(2 * n))
    fmt = {"ascii": "ascii", "binary_le": "binary_little_endian", "binary_be": "binary_big_endian"}[encoding]
    head = (
        f"ply\nformat {fmt} 1.0\nelement vertex {len(verts)}\nproperty float x\nproperty float y\n"
        "property float z\nelement tristrips 1\nproperty list int int vertex_indices\nend_header\n"
    ).encode()
    if encoding == "ascii":
        body = "".join(f"{x} {y} {z}\n" for x, y, z in verts) + f"{len(strip)} " + " ".join(map(str, strip))
        return head + (body + "\n").encode(), 2 * n - 2
    e = "<" if encoding == "binary_le" else ">"
    body = b"".join(struct.pack(e + "3f", *v) for v in verts)
    body += struct.pack(e + "i", len(strip)) + struct.pack(f"{e}{len(strip)}i", *strip)
    return head + body, 2 * n - 2


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_a_strip_row_may_be_as_long_as_the_file(encoding):
    data, tris = _strip_ply(encoding, 1500)  # 3,000 indices in one row; polygon_corners is 1,024
    with open_model(data, name="s.ply") as doc:
        s = doc.scene()
    (obj,) = s.objects
    assert obj.n_triangles == tris and obj.warnings == ()
    assert obj.measures()["area_m2"] == pytest.approx(1499e-6)
    # every triangle keeps the strip's winding (its first triangle faces -z)
    p, t = obj.positions, obj.triangles
    for k in range(0, len(t), 3):
        a, b, c = (p[3 * t[k + i] : 3 * t[k + i] + 2] for i in range(3))
        assert (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) < 0
    with open_model(data, name="s.ply", limits=Limits(triangles=2000)) as doc:
        with pytest.raises(SldLimitError) as exc:
            doc.scene()
    assert exc.value.detail["limit"] == "triangles"


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_faces_before_vertices_read_alike(encoding):
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    verts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
    colors = [(255, 0, 0) if z == 0 else (0, 0, 255) for _x, _y, z in verts]
    fmt = {"ascii": "ascii", "binary_le": "binary_little_endian", "binary_be": "binary_big_endian"}[encoding]
    head = (
        f"ply\nformat {fmt} 1.0\nelement face 6\nproperty list uchar int vertex_indices\n"
        "element note 1\nproperty list int int words\n"
        "element vertex 8\nproperty float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n"
    ).encode()
    long_list = list(range(2000))  # an element the reader skips, its list longer than polygon_corners
    if encoding == "ascii":
        body = "".join(f"4 {' '.join(map(str, q))}\n" for q in quads)
        body += f"{len(long_list)} " + " ".join(map(str, long_list)) + "\n"
        body += "".join(
            f"{x} {y} {z} {r} {g} {b}\n" for (x, y, z), (r, g, b) in zip(verts, colors, strict=True)
        )
        data = head + body.encode()
    else:
        e = "<" if encoding == "binary_le" else ">"
        body = b"".join(struct.pack(e + "B4i", 4, *q) for q in quads)
        body += struct.pack(e + "i", len(long_list)) + struct.pack(f"{e}{len(long_list)}i", *long_list)
        body += b"".join(struct.pack(e + "3f3B", *v, *c) for v, c in zip(verts, colors, strict=True))
        data = head + body
    with open_model(data, name="f.ply") as doc:
        s = doc.scene()
        assert s.counts["triangles"] == 12 and mw.scene_volume(doc) == pytest.approx(1e-9)
        # each triangle takes its first corner's colour: the bottom face is red, the top blue
        by_color = {o.color: o.n_triangles for o in s.objects}
        assert by_color[(1.0, 0.0, 0.0, 1.0)] >= 2 and by_color[(0.0, 0.0, 1.0, 1.0)] >= 2
        assert sum(by_color.values()) == 12


@pytest.mark.parametrize(
    "bad",
    [
        b"ply\nformat ascii 1.0\nend_header\n",  # no vertex element
        b"ply\nformat ascii 2.0\nelement vertex 0\nend_header\n",
        b"ply\nformat sideways 1.0\nelement vertex 0\nend_header\n",
        b"ply\nelement vertex 0\nproperty float x\nend_header\n",  # no format
        b"ply\nformat ascii 1.0\nproperty float x\nelement vertex 0\nend_header\n",
        b"ply\nformat ascii 1.0\nelement vertex 1\nproperty quad x\nend_header\n0\n",
        b"ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nproperty float y\nend_header\n0 0\n",
        b"ply\nformat ascii 1.0\nelement vertex 1000000\nproperty float x\nproperty float y\n"
        b"property float z\n"
        b"end_header\n0 0 0\n",
        b"ply\nformat ascii 1.0\nelement vertex -1\nproperty float x\nend_header\n",
        b"ply\nformat ascii 1.0\nnonsense here\nend_header\n",
        b"ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nproperty float y\nproperty float z\n",
    ],
)
def test_a_damaged_header_is_refused(bad):
    with pytest.raises(SldFormatError):
        open_model(bad, name="b.ply")


def test_damaged_data_and_the_bounds():
    base = mw.ply(holed_block(), encoding="binary_le")
    with open_model(base[:-7], name="t.ply") as doc:
        with pytest.raises(SldFormatError):
            doc.scene()
    float_lists = mw.ply(box(1, 1, 1)).replace(
        b"property list uchar int vertex_indices", b"property list uchar float vertex_indices"
    )
    with open_model(float_lists, name="f.ply") as doc:
        with pytest.raises(SldFormatError):
            doc.scene()
    with pytest.raises(SldLimitError) as exc:
        open_model(
            b"ply\nformat ascii 1.0\ncomment " + b"x" * 200 + b"\n",
            name="h.ply",
            limits=Limits(ply_header_bytes=100),
        )
    assert exc.value.detail["limit"] == "ply_header_bytes"
    many = b"ply\nformat ascii 1.0\n" + b"".join(b"element e%d 0\n" % i for i in range(5)) + b"end_header\n"
    with pytest.raises(SldLimitError) as exc:
        open_model(many, name="e.ply", limits=Limits(ply_elements=4))
    assert exc.value.detail["limit"] == "ply_elements"
    props = (
        b"ply\nformat ascii 1.0\nelement vertex 0\n"
        + b"".join(b"property float p%d\n" % i for i in range(5))
        + b"end_header\n"
    )
    with pytest.raises(SldLimitError) as exc:
        open_model(props, name="p.ply", limits=Limits(ply_properties=4))
    assert exc.value.detail["limit"] == "ply_properties"
    big_face = (
        b"ply\nformat binary_little_endian 1.0\nelement vertex 0\nproperty float x\nproperty float y\n"
        b"property float z\nelement face 1\nproperty list uchar int vertex_indices\nend_header\n"
        + struct.pack("<B", 200)
        + b"\0" * 800
    )
    with open_model(big_face, name="b.ply", limits=Limits(polygon_corners=100)) as doc:
        with pytest.raises(SldLimitError) as exc:
            doc.scene()
    assert exc.value.detail["limit"] == "polygon_corners"
    skipped_list = (
        b"ply\nformat binary_little_endian 1.0\nelement vertex 0\nproperty float x\nproperty float y\n"
        b"property float z\nelement thing 1\nproperty list uint int stuff\nend_header\n"
        + struct.pack("<I", 0xFFFFFFF0)
        + b"\0" * 8
    )
    with open_model(skipped_list, name="s.ply") as doc:
        with pytest.raises(SldFormatError):
            doc.scene()  # a list longer than the file is refused before it is read
    with open_model(mw.ply(holed_block()), name="c.ply") as doc:
        assert doc.scene(max_triangles=5).truncated == ("max_triangles",)


@pytest.mark.usefixtures("outbound_guard")
def test_python_cli_and_rest_give_the_same_model_summary(tmp_path, capsys):
    (tmp_path / "a.ply").write_bytes(mw.ply(two_object_assembly(), face_colors=True))
    (tmp_path / "b.ply").write_bytes(mw.ply(two_object_assembly(), encoding="binary_be", normals=True))
    mw.same_on_three_surfaces(tmp_path, ["a.ply", "b.ply"], "ply", capsys)
