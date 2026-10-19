"""The OFF reader (``docs/formats/mesh.md``): the keyword's variants, colours, normals,
comments, polygons and the refusals."""

import pytest

import mesh_writers as mw
from model_writers import box, holed_block, two_object_assembly
from solidseas import export
from solidseas.errors import FormatNotSupportedError, SldFormatError, SldLimitError
from solidseas.formats import Limits, open_model


@pytest.mark.parametrize("keyword", ["OFF", "COFF", "NOFF", "CNOFF", "STOFF"])
def test_the_neutral_scene_reads_in_every_variant(keyword):
    scene = two_object_assembly()
    with open_model(mw.off(scene, keyword=keyword), name="s.off") as doc:
        assert (doc.format, doc.variant, doc.doc_type) == ("off", keyword, "part")
        assert "units_assumed" in mw.codes(doc.warnings) and doc.counts()["vertices"] == 32
        assert mw.scene_volume(doc) == pytest.approx(20000e-9, rel=1e-12)
        s = doc.scene()
        (obj,) = s.objects
        assert (obj.normals is not None) == ("N" in keyword)
        assert obj.color == ((0.5, 0.5, 0.5, 1.0) if "C" in keyword else None)
        pm = export.print_model(doc)
    assert pm.closed


def test_face_colours_split_the_model_and_counts_may_share_the_keyword_line():
    scene = two_object_assembly()
    with open_model(mw.off(scene, face_colors=True, counts_on_keyword_line=True), name="c.off") as doc:
        s = doc.scene()
        assert [o.color for o in s.objects] == [
            (204 / 255, 26 / 255, 26 / 255, 1.0),
            (26 / 255, 51 / 255, 204 / 255, 1.0),
        ]
        assert mw.scene_volume(doc) == pytest.approx(20000e-9, rel=1e-12)


def test_colour_forms_polygons_and_comments():
    text = (
        b"OFF # a comment after the keyword\n"
        b"# a comment line\n\n"
        b"8 6 12\n"
        b"0 0 0\n1 0 0\n1 1 0\n0 1 0\n0 0 1\n1 0 1\n1 1 1\n0 1 1\n"
        b"4 0 3 2 1 1.0 0.0 0.0\n"  # floats: 0 to 1
        b"4 4 5 6 7 255 0 0\n"  # integers: 0 to 255, the same red
        b"4 0 1 5 4 0 0 255 128\n"
        b"4 1 2 6 5 7\n"  # a colour-map index: no colour
        b"4 2 3 7 6\n"
        b"4 3 0 4 7 # a comment\n"
    )
    with open_model(text, name="p.off") as doc:
        s = doc.scene()
        assert [o.color for o in s.objects] == [(1.0, 0.0, 0.0, 1.0), (0.0, 0.0, 1.0, 128 / 255), None]
        assert [o.n_triangles for o in s.objects] == [4, 2, 6]
        assert mw.scene_volume(doc) == pytest.approx(1e-9)


@pytest.mark.parametrize(
    ("data", "rule", "value"),
    [
        (b"OFF BINARY\n8 6 0\n", "binary_off", "off"),
        (b"4OFF\n1 0 0\n0 0 0 1\n", "unsupported_variant", "4OFF"),
        (b"nOFF\n4\n1 0 0\n0 0 0 0\n", "unsupported_variant", "nOFF"),
    ],
)
def test_binary_and_more_dimensional_variants_are_refused(data, rule, value):
    with pytest.raises(FormatNotSupportedError) as exc:
        open_model(data, name="x.off")
    assert exc.value.detail == {"rule": rule, "value": value}


@pytest.mark.parametrize(
    ("first", "variant"),
    [
        ("{counts}\n", "OFF"),  # the keyword is optional (the Geomview manual)
        ("# made without a keyword\n\n{counts}\n", "OFF"),
        ("OFF{counts}\n", "OFF"),  # the keyword and the vertex count without a space
        ("COFF{counts}\n", "COFF"),
    ],
)
def test_the_keyword_may_be_left_out_or_run_into_the_counts(first, variant):
    lines = mw.off(holed_block(), keyword="COFF" if variant == "COFF" else "OFF").decode().splitlines()
    counts = lines[2]  # the writer puts a comment, the keyword and the counts first
    data = (first.format(counts=counts) + "\n".join(lines[3:]) + "\n").encode()
    with open_model(data, name="k.off") as doc:
        assert doc.variant == variant and doc.counts()["vertices"] == 16
        assert mw.scene_volume(doc) == pytest.approx(holed_block().volume_mm3() * 1e-9, rel=1e-12)
        if variant == "COFF":
            assert doc.scene().objects[0].color == (0.5, 0.5, 0.5, 1.0)


@pytest.mark.parametrize(
    "bad",
    [
        b"OFF\n",
        b"OFF\n3\n",
        b"OFF\nthree two 0\n",
        b"OFF\n-1 0 0\n",
        b"OFF\n100000 100000 0\n0 0 0\n",
        b"NOT AN OFF\n1 1 1\n",
        b"8\n0 0 0\n",  # counts alone need at least two numbers
        b"8 x 0\n0 0 0\n",
    ],
)
def test_a_damaged_header_is_refused(bad):
    with pytest.raises(SldFormatError):
        open_model(bad, name="b.off")


@pytest.mark.parametrize(
    "bad",
    [
        b"OFF\n3 1 0\n0 0 0\n1 0 0\n",  # ends early
        b"OFF\n3 1 0\n0 0 0\n1 0 0\n0 1\n3 0 1 2\n",
        b"OFF\n3 1 0\n0 0 0\n1 0 0\n0 1 x\n3 0 1 2\n",
        b"OFF\n3 1 0\n0 0 0\n1 0 0\n0 1 0\n3 0 1\n",
        b"OFF\n3 1 0\n0 0 0\n1 0 0\n0 1 0\n3 0 1 x\n",
        b"NOFF\n3 1 0\n0 0 0\n1 0 0\n0 1 0\n3 0 1 2\n",  # no normals
    ],
)
def test_damaged_data_is_refused(bad):
    with pytest.raises(SldFormatError):  # by the head when the counts cannot fit, else by the read
        with open_model(bad, name="d.off") as doc:
            doc.scene()


def test_bad_indices_degenerate_faces_and_bounds():
    text = b"OFF\n3 3 0\n0 0 0\n1 0 0\n0 1 0\n3 0 1 2\n3 0 1 5\n2 0 1\n"
    with open_model(text, name="i.off") as doc:
        s = doc.scene()
        assert s.counts["triangles"] == 1
        assert "indices_out_of_range" in mw.codes(s.objects[0].warnings)
        assert "degenerate_triangles_dropped" in mw.codes(s.warnings)
    many = b"OFF\n1 1 0\n0 0 0\n9 " + b"0 " * 9 + b"\n"
    with open_model(many, name="m.off", limits=Limits(polygon_corners=8)) as doc:
        with pytest.raises(SldLimitError) as exc:
            doc.scene()
    assert exc.value.detail["limit"] == "polygon_corners"
    with open_model(mw.off(holed_block()), name="c.off") as doc:
        assert doc.scene(max_triangles=5).truncated == ("max_triangles",)
    with open_model(mw.off(box(1, 1, 1)), name="t.off", limits=Limits(triangles=5)) as doc:
        with pytest.raises(SldLimitError):
            doc.scene()


@pytest.mark.usefixtures("outbound_guard")
def test_python_cli_and_rest_give_the_same_model_summary(tmp_path, capsys):
    (tmp_path / "a.off").write_bytes(mw.off(two_object_assembly(), face_colors=True))
    (tmp_path / "b.off").write_bytes(mw.off(holed_block(), keyword="CNOFF"))
    mw.same_on_three_surfaces(tmp_path, ["a.off", "b.off"], "off", capsys)
