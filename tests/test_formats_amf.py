"""The AMF reader (``docs/formats/mesh.md``): plain and zipped, units, colours from
volumes, materials and objects, constellations and their bounds, curved triangles and
metadata."""

import pytest

import mesh_writers as mw
from model_writers import IDENTITY, QUARTER_Z, Item, Scene, box, holed_block, two_object_assembly
from solidseas import export
from solidseas.errors import SldFormatError, SldLimitError
from solidseas.formats import Limits, open_model


@pytest.mark.parametrize("zipped", [False, True])
@pytest.mark.parametrize("materials", [True, False])
def test_the_neutral_scene_reads_plain_and_zipped(zipped, materials):
    scene = two_object_assembly()
    with open_model(mw.amf(scene, zipped=zipped, materials=materials), name="s.amf") as doc:
        assert (doc.format, doc.variant, doc.doc_type, doc.kind) == (
            "amf",
            "zip" if zipped else "plain",
            "assembly",
            "mesh",
        )
        assert doc.units == {"length": "mm", "scale_m": 0.001, "source": "file"}
        assert doc.fields.title == "invented" and doc.application == {
            "name": "Invented Writer 4.5",
            "version": None,
        }
        assert mw.scene_volume(doc) == pytest.approx(20000e-9, rel=1e-12)
        s = doc.scene()
        assert [o.color for o in s.objects] == [(0.8, 0.1, 0.1, 1.0), (0.1, 0.2, 0.8, 1.0)]
        moved = s.items[1].placement
        assert moved.translation_m == pytest.approx((0.05, 0.0, 0.0))
        assert [list(r) for r in moved.rotation] == [pytest.approx(list(r), abs=1e-12) for r in QUARTER_Z]
        nodes = doc.tree().nodes
        assert [n.kind for n in nodes] == ["assembly", "component", "object", "object", "object"]
        assert {it.instance for it in s.items} == {n.id for n in nodes if n.kind == "object"}
        pm = export.print_model(doc)
    assert pm.closed and pm.measures()["volume_m3"] == pytest.approx(20000e-9)


def test_without_constellations_every_object_stands_once_and_it_is_a_part():
    scene = Scene([box(1, 2, 3), holed_block()], [Item(0), Item(1)])
    with open_model(mw.amf(scene, constellation=False, unit="inch"), name="p.amf") as doc:
        assert doc.doc_type == "part" and doc.units["length"] == "in"
        s = doc.scene()
        assert len(s.items) == 2
        assert s.objects[0].measures()["volume_m3"] == pytest.approx(6 * 0.0254**3, rel=1e-12)
        assert [n.parent for n in doc.tree().nodes] == [None, None]
    with open_model(mw.amf(scene, constellation=False, unit=None), name="d.amf") as doc:
        assert doc.units == {"length": "mm", "scale_m": 0.001, "source": "format"}
    with pytest.raises(SldFormatError):
        open_model(mw.amf(scene, unit="cubits"), name="u.amf")


def test_rotations_turn_about_x_then_y_then_z():
    text = (
        b'<amf unit="millimeter"><object id="1"><mesh><vertices>'
        b"<vertex><coordinates><x>0</x><y>0</y><z>0</z></coordinates></vertex>"
        b"<vertex><coordinates><x>1</x><y>0</y><z>0</z></coordinates></vertex>"
        b"<vertex><coordinates><x>0</x><y>1</y><z>0</z></coordinates></vertex>"
        b"</vertices><volume><triangle><v1>0</v1><v2>1</v2><v3>2</v3></triangle></volume></mesh></object>"
        b'<constellation id="2"><instance objectid="1"><deltax>10</deltax><rx>90</rx><rz>90</rz></instance>'
        b"</constellation></amf>"
    )
    with open_model(text, name="r.amf") as doc:
        p = doc.scene().items[0].placement
        # y turns to z about x, then stays; x turns to y about z
        assert p.apply((0.0, 0.001, 0.0)) == pytest.approx((0.010, 0.0, 0.001), abs=1e-12)
        assert p.apply((0.001, 0.0, 0.0)) == pytest.approx((0.010, 0.001, 0.0), abs=1e-12)


def test_nested_constellations_cycles_depth_and_missing_objects():
    head = (
        b'<amf><object id="1"><mesh><vertices>'
        b"<vertex><coordinates><x>0</x><y>0</y><z>0</z></coordinates></vertex>"
        b"<vertex><coordinates><x>1</x><y>0</y><z>0</z></coordinates></vertex>"
        b"<vertex><coordinates><x>0</x><y>1</y><z>0</z></coordinates></vertex>"
        b"</vertices><volume><triangle><v1>0</v1><v2>1</v2><v3>2</v3></triangle></volume></mesh></object>"
    )
    nested = head + (
        b'<constellation id="10"><instance objectid="1"><deltax>1</deltax></instance>'
        b'<instance objectid="9"/></constellation>'
        b'<constellation id="11"><instance objectid="10"><deltax>5</deltax></instance>'
        b'<instance objectid="10"><deltay>5</deltay></instance></constellation></amf>'
    )
    with open_model(nested, name="n.amf") as doc:
        s = doc.scene()
        assert sorted(it.placement.translation_m for it in s.items) == [
            pytest.approx((0.001, 0.005, 0.0)),
            pytest.approx((0.006, 0.0, 0.0)),
        ]
        assert "component_not_found" in mw.codes(s.warnings)
        nodes = doc.tree().nodes
        assert [n.kind for n in nodes].count("object") == 2
    cyc = head + (
        b'<constellation id="10"><instance objectid="11"/></constellation>'
        b'<constellation id="11"><instance objectid="10"/></constellation>'
        b'<constellation id="12"><instance objectid="10"/></constellation></amf>'
    )
    with open_model(cyc, name="c.amf") as doc:
        with pytest.raises(SldFormatError):
            doc.scene()
    deep = (
        head
        + b"".join(
            b'<constellation id="%d"><instance objectid="%d"/></constellation>' % (20 + i, 21 + i)
            for i in range(20)
        )
        + b'<constellation id="40"><instance objectid="1"/></constellation></amf>'
    )
    with open_model(deep, name="d.amf") as doc:
        with pytest.raises(SldLimitError) as exc:
            doc.scene()
    assert exc.value.detail["limit"] == "amf_constellation_depth"


def test_volume_colours_win_over_objects_and_objects_over_materials_and_curves_are_flattened():
    text = (
        b'<amf><material id="5"><color><r>0</r><g>1</g><b>0</b></color></material>'
        b'<object id="1"><color><r>0</r><g>0</g><b>1</b></color><mesh><vertices>'
        + b"".join(
            b"<vertex><coordinates><x>%d</x><y>%d</y><z>%d</z></coordinates><normal><nx>0</nx></normal></vertex>"
            % p
            for p in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))
        )
        + b"</vertices><edge><v1>0</v1><dx1>1</dx1></edge>"
        b"<volume><color><r>1</r><g>0</g><b>0</b><a>0.5</a></color><triangle><v1>0</v1><v2>2</v2><v3>1</v3></triangle></volume>"
        b'<volume materialid="5"><triangle><v1>0</v1><v2>1</v2><v3>3</v3></triangle></volume>'
        b"<volume><triangle><v1>0</v1><v2>3</v2><v3>2</v3></triangle></volume>"
        b"<volume><color><r>x+y</r><g>0</g><b>0</b></color><triangle><v1>1</v1><v2>2</v2><v3>3</v3></triangle></volume>"
        b"</mesh></object></amf>"
    )
    with open_model(text, name="c.amf") as doc:
        s = doc.scene()
        # the second volume's material is green, but the object's blue comes before it
        assert [o.color for o in s.objects] == [(1.0, 0.0, 0.0, 0.5), (0.0, 0.0, 1.0, 1.0)]
        assert [o.n_triangles for o in s.objects] == [1, 3]  # a formula colour falls back to the object's
        assert "curved_triangles_flattened" in mw.codes(s.warnings)
        assert mw.scene_volume(doc) == pytest.approx(1e-9 / 6)


def test_triangle_and_vertex_colours_come_first():
    def rgb(r, g, b):
        return b"<color><r>%d</r><g>%d</g><b>%d</b></color>" % (r, g, b)

    corners = ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))
    text = (
        b'<amf><material id="5">' + rgb(0, 1, 1) + b"</material>"
        b'<object id="1">'
        + rgb(1, 1, 0)
        + b"<mesh><vertices>"
        + b"".join(
            b"<vertex><coordinates><x>%d</x><y>%d</y><z>%d</z></coordinates>%s</vertex>"
            % (*p, rgb(1, 0, 1) if p == (0, 0, 1) else b"")
            for p in corners
        )
        + b'</vertices><volume materialid="5">'
        + rgb(0, 0, 1)
        + b"<triangle>"
        + rgb(1, 0, 0)
        + b"<v1>0</v1><v2>2</v2><v3>1</v3></triangle>"  # its own: red
        b"<triangle><v1>3</v1><v2>1</v2><v3>2</v3></triangle>"  # its first corner's: magenta
        b"<triangle><v1>0</v1><v2>1</v2><v3>3</v3></triangle>"  # the volume's: blue
        b"<triangle>"
        + rgb(0, 1, 0)
        + b"<v1>3</v1><v2>2</v2><v3>0</v3></triangle>"  # its own over its corner's
        b"</volume></mesh></object></amf>"
    )
    with open_model(text, name="t.amf") as doc:
        s = doc.scene()
        assert {o.color: o.n_triangles for o in s.objects} == {
            (1.0, 0.0, 0.0, 1.0): 1,
            (1.0, 0.0, 1.0, 1.0): 1,
            (0.0, 0.0, 1.0, 1.0): 1,
            (0.0, 1.0, 0.0, 1.0): 1,
        }
        assert mw.scene_volume(doc) == pytest.approx(1e-9 / 6)
        assert [n.color for n in doc.tree().nodes] == [(1.0, 0.0, 0.0, 1.0)]


@pytest.mark.parametrize(
    "bad",
    [
        b"<notamf/>",
        b"<amf><object><mesh><vertices><vertex><coordinates><x>0</x><y>0</y></coordinates></vertex>"
        b"</vertices></mesh></object></amf>",
        b"<amf><object><mesh><vertices><vertex><coordinates><x>a</x><y>0</y><z>0</z></coordinates></vertex>"
        b"</vertices></mesh></object></amf>",
        b"<amf><object><mesh><volume><triangle><v1>0</v1><v2>1</v2></triangle></volume></mesh></object></amf>",
        b"<amf><object><mesh><volume><triangle><v1>0</v1><v2>1</v2><v3>-1</v3></triangle></volume>",
        b'<!DOCTYPE amf [<!ENTITY e "x">]><amf>&e;</amf>',
    ],
)
def test_damaged_files_are_refused(bad):
    with pytest.raises(SldFormatError):
        with open_model(bad, name="b.amf") as doc:
            doc.scene()


def test_a_zip_without_an_amf_member_is_refused_and_bounds_hold():
    with pytest.raises(SldFormatError):
        open_model(mw._zip({"readme.txt": b"none"}), name="z.amf")
    data = mw.amf(two_object_assembly(), zipped=True)
    with pytest.raises(SldLimitError) as exc:
        open_model(data, name="z.amf", limits=Limits(zip_members=0 + 1).replace(zip_member_bytes=100))
    assert exc.value.detail["limit"] == "zip_member_bytes"
    with open_model(mw.amf(holed_block()), name="t.amf") as doc:
        assert doc.scene(max_triangles=5).truncated == ("max_triangles",)


def test_identity_items_place_nothing_but_the_object():
    scene = Scene([box(1, 1, 1)], [Item(0, IDENTITY, (0.0, 0.0, 0.0))])
    with open_model(mw.amf(scene), name="i.amf") as doc:
        (it,) = doc.scene().items
        assert it.placement.translation_m == (0.0, 0.0, 0.0)


@pytest.mark.usefixtures("outbound_guard")
def test_python_cli_and_rest_give_the_same_model_summary(tmp_path, capsys):
    (tmp_path / "a.amf").write_bytes(mw.amf(two_object_assembly()))
    (tmp_path / "b.amf").write_bytes(mw.amf(two_object_assembly(), zipped=True, constellation=False))
    mw.same_on_three_surfaces(tmp_path, ["a.amf", "b.amf"], "amf", capsys)
