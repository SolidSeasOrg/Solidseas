"""The STL reader (``docs/formats/stl.md``): binary and ASCII, the fixture SOLIDWORKS
wrote, synthetic files from ``tests/model_writers.py`` and hostile ones."""

import struct

import pytest

from model_writers import Item, Scene, box, holed_block, stl_ascii, stl_binary, two_object_assembly
from solidseas import export
from solidseas.errors import NoPreviewError, NothingToExportError, SldFormatError, SldLimitError
from solidseas.formats import Limits, open_model
from support import fixture_path

FIXTURE = fixture_path("o02_boxA.STL")


def _codes(warnings) -> set[str]:
    return {w.code for w in warnings}


def _scene_volume(doc) -> float:
    s = doc.scene()
    return sum(s.objects[it.object].measures()["volume_m3"] for it in s.items)


# --------------------------------------------------------------------------- the fixture
def test_the_solidworks_stl_fixture_reads_to_its_box():
    with open_model(FIXTURE) as doc:
        assert (doc.format, doc.variant, doc.doc_type, doc.kind) == ("stl", "binary", "part", "mesh")
        assert doc.units == {"length": "mm", "scale_m": 0.001, "source": "assumed"}
        assert "units_assumed" in _codes(doc.warnings)
        assert doc.counts()["triangles"] == 12 and doc.counts()["objects"] == 1
        assert [p.name for p in doc.properties] == ["header"]
        s = doc.scene()
        (obj,) = s.objects
        m = obj.measures()
        assert m["volume_m3"] == pytest.approx(6.0e-6, rel=1e-6)
        assert m["area_m2"] == pytest.approx(0.0022, rel=1e-6)
        assert obj.source == "mesh" and s.counts["triangles"] == 12
        (node,) = doc.tree().nodes
        assert (node.kind, node.object, node.name) == ("object", 0, "o02_boxA")
        assert doc.preview() is None


def test_the_fixture_exports_closed_and_round_trips_through_stl(tmp_path):
    with open_model(FIXTURE) as doc:
        pm = export.print_model(doc)
    assert pm.closed and pm.source_format == "stl" and pm.objects[0].source == "mesh"
    assert pm.counts == {"objects": 1, "items": 1, "vertices": 8, "triangles": 12}
    assert pm.measures()["volume_m3"] == pytest.approx(6.0e-6, rel=1e-6)
    out = tmp_path / "again.stl"
    export.write_export(pm, out, "stl")
    with open_model(out) as again:
        assert _scene_volume(again) == pytest.approx(6.0e-6, rel=1e-6)


# --------------------------------------------------------------------------- binary
def test_a_binary_header_that_starts_with_solid_is_still_binary():
    data = stl_binary(box(1, 2, 3), header=b"solid looks like ASCII but is binary")
    with open_model(data, name="b.stl") as doc:
        assert doc.variant == "binary"
        assert _scene_volume(doc) == pytest.approx(6e-9, rel=1e-6)


def test_an_assembly_written_as_one_stl_keeps_its_volume():
    scene = two_object_assembly()
    with open_model(stl_binary(scene), name="a.stl") as doc:
        assert _scene_volume(doc) == pytest.approx(scene.volume_mm3() * 1e-9, rel=1e-6)
        pm = export.print_model(doc)
    assert pm.measures()["volume_m3"] == pytest.approx(20000e-9, rel=1e-6)
    assert pm.objects[0].closed  # three closed solids, welded


def test_extra_bytes_after_the_last_triangle_are_ignored():
    data = stl_binary(box(1, 1, 1)) + b"\0" * 7
    with open_model(data, name="x.stl") as doc:
        assert doc.variant == "binary" and doc.scene().counts["triangles"] == 12


def test_colours_in_attribute_bits_or_the_header_are_warned():
    with open_model(stl_binary(box(1, 1, 1), attribute=0x8000 | 0x1F), name="c.stl") as doc:
        assert "colors_ignored" in _codes(doc.scene().warnings)
    with open_model(stl_binary(box(1, 1, 1), header=b"COLOR=\xff\x00\x00\xff"), name="c.stl") as doc:
        assert "colors_ignored" in _codes(doc.warnings)


def test_a_binary_stl_too_short_for_its_count_is_refused():
    data = stl_binary(box(1, 1, 1))
    with pytest.raises(SldFormatError):
        open_model(data[:-10], name="t.stl")
    huge = b"\0" * 80 + struct.pack("<I", 0xFFFFFFFF) + b"\0" * 100
    with pytest.raises(SldFormatError):
        open_model(huge, name="h.stl")
    with pytest.raises(SldFormatError):
        open_model(b"\0" * 40, name="s.stl")


def test_an_empty_binary_stl_has_nothing_to_export_or_draw():
    from solidseas.render import render_preview

    data = b"\0" * 80 + struct.pack("<I", 0)
    with open_model(data, name="e.stl") as doc:
        assert doc.counts()["triangles"] == 0
        with pytest.raises(NothingToExportError):
            export.print_model(doc)
        with pytest.raises(NoPreviewError):
            render_preview(doc)


def test_non_finite_corners_drop_their_triangles():
    data = bytearray(stl_binary(box(1, 1, 1)))
    struct.pack_into("<f", data, 84 + 12, float("nan"))  # the first triangle's first x
    with open_model(bytes(data), name="n.stl") as doc:
        (obj,) = doc.scene().objects
        assert obj.n_triangles == 11 and "degenerate_triangles_dropped" in _codes(obj.warnings)
        assert all(v == v for v in obj.positions)  # the NaN vertex is gone too


def test_the_triangle_bound_and_the_scene_cap():
    data = stl_binary(holed_block())
    with open_model(data, name="b.stl", limits=Limits(triangles=10)) as doc:
        with pytest.raises(SldLimitError) as exc:
            doc.scene()
    assert exc.value.detail["limit"] == "triangles"
    with open_model(data, name="b.stl") as doc:
        s = doc.scene(max_triangles=10)
        assert s.truncated == ("max_triangles",) and s.objects == ()


def test_the_time_bound_stops_a_large_read():
    one = stl_binary(holed_block())
    n = 200_000
    body = (one[84:] * (n // 32 + 1))[: 50 * n]
    data = one[:80] + struct.pack("<I", n) + body
    with open_model(data, name="big.stl") as doc:
        with pytest.raises(SldLimitError) as exc:
            doc.scene(max_seconds=1e-6)
    assert exc.value.detail["limit"] == "seconds"


# --------------------------------------------------------------------------- ASCII
def test_an_ascii_stl_with_several_solids_gives_one_object_each():
    scene = two_object_assembly()
    with open_model(stl_ascii(scene), name="a.stl") as doc:
        assert doc.variant == "ascii"
        assert [p.name for p in doc.properties] == ["solid"] and doc.properties[0].value == "box 1"
        names = [n.name for n in doc.tree().nodes]
        assert names == ["box 1", "box 2", "block 1"]
        s = doc.scene()
        assert [o.name for o in s.objects] == names and len(s.items) == 3
        assert _scene_volume(doc) == pytest.approx(20000e-9, rel=1e-9)
        assert doc.counts()["triangles"] is None  # an ASCII file's head does not say


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_ascii_line_ends_and_upper_case_keywords(newline):
    with open_model(stl_ascii(box(2, 3, 4), newline=newline, upper=True), name="u.stl") as doc:
        assert _scene_volume(doc) == pytest.approx(24e-9, rel=1e-9)


def test_an_ascii_facet_without_three_corners_is_left_out():
    text = stl_ascii(box(1, 1, 1)).decode()
    text = text.replace("    endloop", "      vertex 0 0 0\n    endloop", 1)
    with open_model(text.encode(), name="q.stl") as doc:
        s = doc.scene()
        assert s.counts["triangles"] == 11 and "degenerate_triangles_dropped" in _codes(s.warnings)


@pytest.mark.parametrize(
    "bad",
    [
        "solid x\nfacet normal 0 0 1\nouter loop\nvertex 0 0 zero\n",
        "solid x\nfacet normal 0 0 1\nouter loop\nvertex 0 0\n",
        "solid x\nwhatever 1 2 3\n",
    ],
)
def test_damaged_ascii_raises_a_format_error(bad):
    with open_model(bad.encode(), name="d.stl") as doc:
        with pytest.raises(SldFormatError):
            doc.scene()


def test_an_ascii_line_past_its_bound_is_refused():
    text = "solid x\n" + "facet normal " + "0" * 10_000 + " 0 0\n"
    with open_model(text.encode(), name="l.stl") as doc:
        with pytest.raises(SldLimitError) as exc:
            doc.scene()
    assert exc.value.detail["limit"] == "stl_line_bytes"


def test_an_empty_ascii_solid_reads_to_nothing():
    with open_model(b"solid empty\nendsolid empty\n", name="e.stl") as doc:
        s = doc.scene()
        assert s.counts["triangles"] == 0
        with pytest.raises(NothingToExportError):
            export.print_model(doc)


def test_ascii_and_binary_of_one_scene_read_alike():
    scene = Scene([holed_block()], [Item(0, translation_mm=(1.5, -2.25, 3.0))])
    with open_model(stl_binary(scene), name="b.stl") as b, open_model(stl_ascii(scene), name="a.stl") as a:
        mb = b.scene().objects[0].measures()
        ma = a.scene().objects[0].measures()
    assert mb["volume_m3"] == pytest.approx(ma["volume_m3"], rel=1e-6)
    assert [*mb["box"][0], *mb["box"][1]] == pytest.approx([*ma["box"][0], *ma["box"][1]], abs=1e-9)
