"""The DXF writer (docs/DRAWINGS.md 12.2, 19.2): read back with tests/dxf_reader.py."""

import io
import math

import pytest

import drawing_parts
import dxf_reader as R
from drawing_support import COMPANY, fixture, sample_sheet
from drawing_support import model as drawing_model
from solidseas import __version__, open_document
from solidseas.drawing import display as D
from solidseas.drawing import facegraph
from solidseas.drawing import write_dxf as public_write_dxf
from solidseas.drawing.dxf import dxf_bytes, write_dxf
from solidseas.drawing.limits import DrawingLimits
from solidseas.drawing.painter import stroke_geometry, text_run
from solidseas.drawing.types import Drawing, DrawingOptions
from solidseas.errors import InvalidArgumentError, SldLimitError

CBORE, DEPTH = "\u2334", "\u21a7"


def read(sheet, **kw) -> R.Document:
    return R.read(dxf_bytes(sheet, **kw))


def _line(owner, p0, p1, layer="dimensions"):
    return D.Stroke((("M", *p0), ("L", *p1)), 0.3, (), layer, owner)


def _arrow(owner, tip, back):
    dx, dy = tip[0] - back[0], tip[1] - back[1]
    n = math.hypot(dx, dy)
    ux, uy = dx / n, dy / n
    bx, by = tip[0] - 3.0 * ux, tip[1] - 3.0 * uy
    return D.Fill(
        (("M", *tip), ("L", bx - uy * 0.5, by + ux * 0.5), ("L", bx + uy * 0.5, by - ux * 0.5), ("Z",)),
        "dimensions",
        owner,
    )


def _text(owner, at, value, layer="dimensions", **kw):
    return text_run(
        at[0], at[1], 3.0, value, anchor=kw.pop("anchor", "centre"), layer=layer, owner=owner, **kw
    )


def dims_sheet() -> D.Sheet:
    """An A sheet at 1:2 with a view at the sheet's scale and a detail at 2:1, a
    dimension of every kind with its painted items owned by its id, a basic one and
    a chamfer note with nothing painted, a frame drawn from its cells and one painted
    under a dimension's owner, a datum symbol, the stamp, and furniture with nothing
    painted on its layers."""
    view = D.ViewPlacement("v-1", (60.0, 80.0), 0.5, "")
    detail = D.ViewPlacement("v-2", (200.0, 150.0), 2.0, "DETAIL B SCALE 2:1")
    src = D.Src(0, "plane:0,0,1:0", "v-1")
    geometry = tuple(
        D.place(g, view)
        for g in (
            D.Segment((0.0, 0.0), (0.1, 0.0), "visible", src),
            D.Arc((0.05, 0.01), 0.005, 0.0, 360.0, "visible", src),
        )
    ) + (D.place(D.Segment((0.0, 0.0), (0.005, 0.0), "visible", D.Src(0, "", "v-2")), detail),)

    hole = D.Dimension(
        "d-hole",
        "diameter",
        "v-1",
        ((82.5, 85.0), (87.5, 85.0)),
        (100.0, 100.0),
        0.01,
        D.DimText("10", prefix="4X \u00d8", suffix=("THRU", f"{CBORE} \u00d816 {DEPTH} 5")),
        precision=0,
    )
    a30 = math.radians(30.0)
    dims = (
        D.Dimension(
            "d-lin",
            "linear",
            "v-1",
            ((60.0, 80.0), (110.0, 80.0), (85.0, 70.0)),
            (85.0, 70.0),
            0.1,
            D.DimText("100"),
        ),
        D.Dimension(
            "d-ali",
            "aligned",
            "v-1",
            ((60.0, 80.0), (90.0, 120.0), (52.0, 86.0)),
            (68.0, 107.0),
            0.1,
            D.DimText("100"),
        ),
        D.Dimension(
            "d-rad",
            "radius",
            "v-1",
            ((100.0, 85.0), (104.0, 88.0)),
            (110.0, 95.0),
            0.01,
            D.DimText("10", prefix="R"),
        ),
        hole,
        D.Dimension(
            "d-ang",
            "angle",
            "v-1",
            (
                (150.0, 60.0),
                (170.0, 60.0),
                (150.0 + 20 * math.cos(a30), 60.0 + 20 * math.sin(a30)),
                (164.5, 63.9),
            ),
            (166.0, 66.0),
            30.0,
            D.DimText("30", after="\u00b0"),
            precision=0,
        ),
        D.Dimension(
            "d-ord",
            "ordinate",
            "v-1",
            ((60.0, 80.0), (110.0, 80.0), (110.0, 65.0)),
            (110.0, 62.0),
            0.1,
            D.DimText("100"),
        ),
        D.Dimension(
            "d-basic",
            "linear",
            "v-1",
            ((60.0, 80.0), (85.0, 80.0), (72.0, 55.0)),
            (72.0, 55.0),
            0.05,
            D.DimText("50", boxed=True),
            flags=("basic",),
            precision=0,
        ),
        D.Dimension(
            "d-det",
            "linear",
            "v-2",
            ((200.0, 150.0), (210.0, 150.0), (205.0, 140.0)),
            (205.0, 140.0),
            0.005,
            D.DimText("5"),
            precision=0,
        ),
        D.Dimension("d-chamfer", "chamfer", "v-1", (), (30.0, 120.0), 0.001, D.DimText("1 X 45\u00b0")),
    )
    frame = D.FeatureControlFrame(
        (120.0, 30.0), D.FrameItem("position", "0.2", True, "mmc", ("A", "B")), "d-hole"
    )
    painted_frame = D.FeatureControlFrame((120.0, 45.0), D.FrameItem("flatness", "0.1"), "d-lin")
    datum = D.DatumFeature("A", (30.0, 60.0), ((40.0, 80.0), (35.0, 66.0)), "v-1")
    stamp = D.Stamp("PRELIMINARY - NOT FOR MANUFACTURE", (10.0, 5.0), 90.0)
    annotations = (
        *dims,
        frame,
        painted_frame,
        datum,
        stamp,
        D.Border(279.4, 215.9, 9.652, 2, 2),
        D.TitleBlock((180.0, 10.0), 90.0, 40.0, (("company", COMPANY), ("title", "PLATE"))),
        D.CentreMark((85.0, 85.0), 2.5, "v-1"),
    )
    painted = stroke_geometry(geometry) + (
        # d-lin: extension lines, dimension line, arrows, value
        _line("d-lin", (60.0, 78.5), (60.0, 67.0)),
        _line("d-lin", (110.0, 78.5), (110.0, 67.0)),
        _line("d-lin", (60.0, 70.0), (110.0, 70.0)),
        _arrow("d-lin", (60.0, 70.0), (110.0, 70.0)),
        _arrow("d-lin", (110.0, 70.0), (60.0, 70.0)),
        _text("d-lin", (85.0, 68.5), "100"),
        # a flatness frame painted under d-lin's owner: outline, divider, zone
        D.Stroke(
            (("M", 120.0, 45.0), ("L", 140.0, 45.0), ("L", 140.0, 50.0), ("L", 120.0, 45.0 + 5.0), ("Z",)),
            0.3,
            (),
            "dimensions",
            "d-lin",
        ),
        _line("d-lin", (125.0, 45.0), (125.0, 50.0)),
        _text("d-lin", (126.2, 46.0), "0.1", anchor="left"),
        # d-ali
        _line("d-ali", (52.0, 86.0), (82.0, 126.0)),
        _arrow("d-ali", (52.0, 86.0), (82.0, 126.0)),
        _arrow("d-ali", (82.0, 126.0), (52.0, 86.0)),
        _text("d-ali", (68.0, 107.0), "100", angle_deg=53.13),
        # d-rad: a leader with a curved shoulder (a Bezier) to the arc
        D.Stroke(
            (("M", 110.0, 95.0), ("C", 108.0, 93.0, 106.0, 91.0, 104.0, 88.0)), 0.3, (), "dimensions", "d-rad"
        ),
        _arrow("d-rad", (104.0, 88.0), (106.0, 91.0)),
        _text("d-rad", (112.0, 95.0), "R10", anchor="left"),
        # the hole: leader, arrow, the value's line and the counterbore line
        _line("d-hole", (87.5, 85.0), (98.0, 99.0)),
        _arrow("d-hole", (87.5, 85.0), (98.0, 99.0)),
        _text("d-hole", (100.0, 99.0), "4X \u00d810 THRU", anchor="left"),
        _text("d-hole", (100.0, 94.0), f"{CBORE} \u00d816 {DEPTH} 5", anchor="left"),
        # d-ang: the arc as Beziers and the value
        D.Stroke(
            (("M", 165.0, 60.0), ("C", 165.0, 62.5, 164.3, 64.8, 163.0, 67.5)), 0.3, (), "dimensions", "d-ang"
        ),
        _text("d-ang", (166.0, 66.0), "30\u00b0"),
        # d-ord: leader and value
        _line("d-ord", (110.0, 78.5), (110.0, 65.0)),
        _text("d-ord", (110.0, 62.0), "100"),
        # d-det
        _line("d-det", (200.0, 140.0), (210.0, 140.0)),
        _text("d-det", (205.0, 141.0), "5"),
        # the stamp as layout paints it
        text_run(10.0, 5.0, 3.0, "PRELIMINARY - NOT FOR MANUFACTURE", angle_deg=90.0, layer="stamp"),
    )
    return D.Sheet("A", 279.4, 215.9, (1, 2), (view, detail), geometry, annotations, painted)


def hostile_sheet() -> D.Sheet:
    title = "TITLE \\P {BOLD} ^J \x07 M\u00fcller 100%% \u0000END"
    sheet = sample_sheet()
    note = D.Note("n-9", (20.0, 150.0), ((title, ()),), leader=((60.0, 120.0), (50.0, 140.0), (45.0, 148.0)))
    painted = sheet.painted + (text_run(20.0, 190.0, 3.0, title, layer="title", owner="title"),)
    return D.Sheet(
        sheet.name,
        sheet.width,
        sheet.height,
        sheet.scale,
        sheet.views,
        sheet.geometry,
        sheet.annotations + (note,),
        painted,
    )


def dimension(doc: R.Document, block_name: str) -> R.Record:
    return next(e for e in doc.find("DIMENSION") if e.get(2) == block_name)


def dimensions_by_text(doc: R.Document) -> dict[str, R.Record]:
    return {e.get(1): e for e in doc.find("DIMENSION")}


# --------------------------------------------------------------------------- the file


def test_the_reader_reads_what_the_writer_writes():
    buf = io.BytesIO()
    n = write_dxf(sample_sheet(), buf)
    data = buf.getvalue()
    assert n == len(data)
    doc = R.read(data)
    assert doc.sections == ["HEADER", "CLASSES", "TABLES", "BLOCKS", "ENTITIES", "OBJECTS"]
    assert doc.line_ending == "\r\n" and b"\n" not in data.replace(b"\r\n", b"")
    assert data.startswith(f"999\r\nSolidSeas {__version__}\r\n".encode())
    assert doc.comments == [f"SolidSeas {__version__}"]
    assert doc.var("$ACADVER") == "AC1015"
    assert doc.var("$INSUNITS") == "4" and doc.var("$MEASUREMENT") == "1"
    assert doc.var("$DIMSTYLE") == "SOLIDSEAS_MM"
    assert set(doc.tables) == {
        "VPORT",
        "LTYPE",
        "LAYER",
        "STYLE",
        "VIEW",
        "UCS",
        "APPID",
        "DIMSTYLE",
        "BLOCK_RECORD",
    }
    assert {"*Model_Space", "*Paper_Space"} <= set(doc.blocks)
    assert [c.get(1) for c in doc.classes] == ["ACDBDICTIONARYWDFLT", "ACDBPLACEHOLDER", "LAYOUT"]


def test_the_public_entry_point_is_this_writer():
    buf = io.BytesIO()
    drawing = Drawing("dwg-1", DrawingOptions(), None, sheet=sample_sheet())
    assert public_write_dxf(drawing, buf) == len(buf.getvalue())
    assert buf.getvalue() == dxf_bytes(sample_sheet())


@pytest.mark.parametrize("make", [sample_sheet, dims_sheet, hostile_sheet])
def test_every_handle_is_unique_and_every_reference_resolves(make):
    doc = read(make())
    handles = doc.handles()
    assert len(handles) == len(set(handles))
    known = set(handles)
    for record, code, value in doc.references():
        assert value == "0" or value in known, (record.type, code, value)
    seed = int(doc.var("$HANDSEED"), 16)
    assert all(int(h, 16) < seed for h in handles)
    # owners: entities by their block's record, entries by their table, blocks by their record
    records = doc.tables["BLOCK_RECORD"]
    model = records.entry("*Model_Space").handle
    assert all(e.owner == model for e in doc.entities)
    for name, block in doc.blocks.items():
        record = records.entry(name).handle
        assert block.begin.owner == record and block.end.owner == record
        assert all(e.owner == record for e in block.entities)
    for table in doc.tables.values():
        assert table.header.owner == "0"
        assert all(e.owner == table.header.handle for e in table.entries)


@pytest.mark.parametrize("make", [sample_sheet, dims_sheet, hostile_sheet])
def test_the_tables_define_every_layer_line_type_style_and_block_used(make):
    doc = read(make())
    layers = {n.upper() for n in doc.tables["LAYER"].names()}
    assert {
        "0",
        "VISIBLE",
        "HIDDEN",
        "CENTER",
        "PHANTOM",
        "DIM",
        "HATCH",
        "BORDER",
        "TITLE",
        "NOTES",
        "STAMP",
    } <= layers
    assert {name.upper() for name in R.used_layers(doc)} <= layers
    linetypes = {n.upper() for n in doc.tables["LTYPE"].names()}
    assert {"BYBLOCK", "BYLAYER", "CONTINUOUS", "HIDDEN", "CENTER", "PHANTOM"} <= linetypes
    assert {name.upper() for name in R.used_linetypes(doc)} <= linetypes
    styles = set(doc.tables["STYLE"].names())
    assert R.used_styles(doc) <= styles and "Standard" in styles
    dimstyles = set(doc.tables["DIMSTYLE"].names())
    assert dimstyles == {"Standard", "SOLIDSEAS_MM", "SOLIDSEAS_IN"}
    assert {d.get(3) for d in doc.find("DIMENSION")} <= dimstyles
    records = set(doc.tables["BLOCK_RECORD"].names())
    assert records == set(doc.blocks)
    for e in R.drawn(doc):
        if e.type in ("INSERT", "DIMENSION"):
            assert e.get(2) in doc.blocks
    assert doc.tables["APPID"].names() == ["ACAD"]
    assert "ACAD_LAYOUT" in doc.objects[0].all(3)


def test_line_types_carry_acad_lin_patterns_and_ltscale_fits_the_sheet():
    doc = read(sample_sheet())
    hidden = doc.tables["LTYPE"].entry("HIDDEN")
    assert [float(v) for v in hidden.all(49)] == [6.35, -3.175]  # acadiso.lin, millimetres
    centre = doc.tables["LTYPE"].entry("CENTER")
    assert [float(v) for v in centre.all(49)] == pytest.approx([31.75, -6.35, 6.35, -6.35])
    # the hidden dash 3 mm on paper at 1:2: 6.35 * LTSCALE = 3 * 2
    assert float(doc.var("$LTSCALE")) * 6.35 == pytest.approx(6.0, abs=1e-6)
    inch = read(sample_sheet(), units="in")
    assert [float(v) for v in inch.tables["LTYPE"].entry("HIDDEN").all(49)] == [0.25, -0.125]
    assert float(inch.var("$LTSCALE")) * 0.25 == pytest.approx(6.0 / 25.4, abs=1e-6)
    layer = doc.tables["LAYER"].entry("HIDDEN")
    assert layer.get(6) == "HIDDEN" and layer.int(370) == 30
    assert doc.tables["LAYER"].entry("VISIBLE").int(370) == 60
    assert doc.tables["LAYER"].entry("DEFPOINTS").int(290) == 0


# --------------------------------------------------------------------------- views at true size


def test_views_are_at_true_size_in_model_space():
    sheet = sample_sheet()
    doc = read(sheet)
    view = sheet.views[0]
    visible = doc.find("LINE", "VISIBLE")
    assert len(visible) == 1
    assert R.length(visible[0]) == pytest.approx(100.0, abs=1e-9)  # 0.1 m at 1:2
    # every view point is its view coordinates in millimetres, set at its origin's place
    seg = sheet.geometry[0]
    for code, p in ((10, seg.p0), (11, seg.p1)):
        x, y = view.to_view(p)
        origin = (view.origin[0] / 0.5, view.origin[1] / 0.5)
        assert visible[0].point(code) == pytest.approx((origin[0] + x * 1000.0, origin[1] + y * 1000.0))
    circle = doc.find("CIRCLE", "VISIBLE")[0]
    assert circle.float(40) == pytest.approx(5.0)
    dim = doc.find("DIMENSION")[0]
    (x0, y0), (x1, y1) = dim.point(13), dim.point(14)
    assert math.hypot(x1 - x0, y1 - y0) == pytest.approx(100.0)
    # the sheet's furniture at 1/scale: the sheet's corner is (558.8, 431.8)
    assert (float(doc.var("$EXTMAX")), float(doc.header["$EXTMAX"][1].value)) == pytest.approx((558.8, 431.8))


def test_each_primitive_is_written_exactly():
    doc = read(sample_sheet())
    arc = doc.find("ARC", "TANGENT")[0]
    assert (arc.float(40), arc.float(50), arc.float(51)) == pytest.approx((4.0, 90.0, 270.0))
    ellipse = doc.find("ELLIPSE")[0]
    assert ellipse.point(11) == pytest.approx((6.0, 0.0))
    assert (ellipse.float(40), ellipse.float(41), ellipse.float(42)) == pytest.approx((0.5, 0.0, math.pi))
    spline = doc.find("SPLINE", "PHANTOM")[0]
    assert spline.int(71) == 3 and spline.int(70) & 8
    assert [float(k) for k in spline.all(40)] == [0, 0, 0, 0, 0.5, 1, 1, 1, 1]
    assert spline.points(10)[1] == pytest.approx((140.0, 210.0))
    assert spline.all(41) == []  # not rational
    poly = doc.find("LWPOLYLINE", "CENTER")[0]
    assert poly.int(90) == 3 and [c for p in poly.points(10) for c in p] == pytest.approx(
        [120.0, 150.0, 170.0, 148.0, 220.0, 150.0]
    )
    hidden = doc.find("LINE", "HIDDEN")
    assert len(hidden) == 1 and hidden[0].get(6) is None  # by layer


def test_a_rational_spline_keeps_its_weights_and_a_tall_ellipse_turns():
    w = math.sqrt(0.5)
    spline = D.Spline(2, (0, 0, 0, 1, 1, 1), ((10.0, 0.0), (10.0, 10.0), (0.0, 10.0)), (1.0, w, 1.0))
    tall = D.EllipseArc((50.0, 50.0), (4.0, 0.0), 2.0)
    doc = read(D.Sheet("A", 279.4, 215.9, geometry=(spline, tall)))
    s = doc.find("SPLINE")[0]
    assert s.int(70) & 4 and [float(v) for v in s.all(41)] == pytest.approx([1.0, w, 1.0])
    e = doc.find("ELLIPSE")[0]
    assert e.point(11) == pytest.approx((0.0, 8.0)) and e.float(40) == pytest.approx(0.5)
    assert (e.float(41), e.float(42)) == pytest.approx((0.0, 2 * math.pi))


def test_painted_view_strokes_are_not_written_twice():
    sheet = sample_sheet()
    doc = read(sheet)
    view_layers = {"VISIBLE", "HIDDEN", "TANGENT", "CENTER", "PHANTOM"}
    assert len([e for e in doc.entities if e.layer in view_layers]) == len(sheet.geometry)


def test_a_painted_bezier_is_an_exact_cubic_spline_and_a_fill_a_solid_or_hatch():
    stroke = D.Stroke(
        (("M", 0.0, 0.0), ("C", 1.0, 2.0, 3.0, 2.0, 4.0, 0.0), ("L", 8.0, 0.0)), 0.3, (), "notes"
    )
    triangle = D.Fill((("M", 0.0, 0.0), ("L", 3.0, 1.0), ("L", 3.0, -1.0), ("Z",)), "notes")
    disc = D.Fill((("M", 10.0, 0.0), ("C", 10.0, 5.0, 20.0, 5.0, 20.0, 0.0), ("Z",)), "hatch")
    doc = read(D.Sheet("A", 279.4, 215.9, painted=(stroke, triangle, disc)))
    s = doc.find("SPLINE", "NOTES")[0]
    assert [float(k) for k in s.all(40)] == [0, 0, 0, 0, 1, 1, 1, 2, 2, 2, 2]
    assert [c for p in s.points(10)[:4] for c in p] == pytest.approx([0, 0, 1, 2, 3, 2, 4, 0])
    solid = doc.find("SOLID", "NOTES")[0]
    assert solid.point(12) == solid.point(13)  # a triangle repeats its last corner
    h = doc.find("HATCH", "HATCH")[0]
    assert h.get(2) == "SOLID" and h.int(70) == 1 and h.int(91) == 1


# --------------------------------------------------------------------------- dimensions


def test_every_dimension_has_its_block_and_measured_text():
    doc = read(dims_sheet())
    dims = doc.find("DIMENSION", "DIM")
    assert len(dims) == 8  # the chamfer note is not a measuring dimension
    names = [d.get(2) for d in dims]
    assert names == [f"*D{i}" for i in range(1, 9)]
    for d in dims:
        block = doc.block_of(d)
        assert block.begin.int(70) & 1  # anonymous
        assert [e for e in block.entities if e.layer != "DEFPOINTS"], d.get(2)
        assert d.int(70) & 32 and d.int(70) & 128
    measured = [d for d in dims if "<>" in d.get(1)]
    assert len(measured) == 7  # all but the detail view's
    assert dimensions_by_text(doc)["<>"].get(3) == "SOLIDSEAS_MM"


def test_each_kind_is_its_dimension_type_with_its_points():
    doc = read(dims_sheet())
    by_block = {d.get(2): d for d in doc.find("DIMENSION")}
    types = [by_block[f"*D{i}"].int(70) & 0x47 for i in range(1, 9)]
    assert types == [0, 1, 4, 3, 5, 6 | 64, 0, 0]
    lin = by_block["*D1"]
    assert lin.all(100) == ["AcDbEntity", "AcDbDimension", "AcDbAlignedDimension", "AcDbRotatedDimension"]
    assert lin.float(50) == 0.0
    ali = by_block["*D2"]
    assert "AcDbRotatedDimension" not in ali.all(100)
    (x0, y0), (x1, y1) = ali.point(13), ali.point(14)
    assert math.hypot(x1 - x0, y1 - y0) == pytest.approx(100.0)
    rad = by_block["*D3"]
    assert math.dist(rad.point(10), rad.point(15)) == pytest.approx(10.0)  # R10 at 1:2
    dia = by_block["*D4"]
    assert math.dist(dia.point(10), dia.point(15)) == pytest.approx(10.0)
    ang = by_block["*D5"]
    v, a, b = ang.point(15), ang.point(13), ang.point(14)
    angle = math.degrees(math.atan2(b[1] - v[1], b[0] - v[0]) - math.atan2(a[1] - v[1], a[0] - v[0]))
    assert angle == pytest.approx(30.0)
    ordinate = by_block["*D6"]
    assert ordinate.point(13)[0] - ordinate.point(10)[0] == pytest.approx(100.0)
    assert "AcDbOrdinateDimension" in ordinate.all(100)


def test_a_dimensions_painted_items_are_its_block():
    doc = read(dims_sheet())
    block = doc.block_of(dimension(doc, "*D1"))
    kinds = sorted(e.type for e in block.entities if e.layer == "0")
    assert kinds == ["LINE", "LINE", "LINE", "SOLID", "SOLID", "TEXT"]
    for e in block.entities:
        if e.layer == "0":
            assert e.int(62) == 0 and e.int(370) == -2 and e.get(6) == "ByBlock"
    assert [e.get(1) for e in block.entities if e.type == "TEXT"] == ["100"]
    assert len([e for e in block.entities if e.type == "POINT" and e.layer == "DEFPOINTS"]) == 3
    # none of it is in model space as well
    assert not [e for e in doc.entities if e.type == "TEXT" and e.get(1) == "100"]
    # a Bezier leader in a block is an exact spline
    rad = doc.block_of(dimension(doc, "*D3"))
    assert [e.type for e in rad.entities if e.layer == "0"] == ["SPLINE", "SOLID", "TEXT"]


def test_the_hole_diameter_is_a_dimension_with_its_count_and_suffix():
    doc = read(dims_sheet())
    hole = dimensions_by_text(doc)["4X %%c<> THRU"]
    assert hole.int(70) & 7 == 3
    assert "AcDbDiametricDimension" in hole.all(100)
    beside = [e for e in doc.find("MTEXT", "DIM") if "\\U+2334" in e.text]
    assert len(beside) == 1
    assert beside[0].text == "\\U+2334 %%c16 \\U+21A7 5"
    assert beside[0].point(10) == pytest.approx(
        (200.0, 188.0 + 2 * 3.0), abs=0.01
    )  # where the sheet painted it
    block = doc.block_of(hole)
    texts = [e.get(1) for e in block.entities if e.type == "TEXT"]
    assert texts == ["4X %%c10 THRU"]  # the counterbore line is beside, not in the block


def test_symbol_words_replace_the_symbols_cad_fonts_lack():
    doc = read(dims_sheet(), symbol_words=True)
    beside = [e.text for e in doc.find("MTEXT", "DIM") if "CBORE" in e.text]
    assert beside == ["CBORE %%c16 DEEP 5"]
    assert b"\\U+2334" not in dxf_bytes(dims_sheet(), symbol_words=True)


def test_a_basic_dimension_gets_its_box_and_a_negative_gap():
    doc = read(dims_sheet())
    by_block = {d.get(2): d for d in doc.find("DIMENSION")}
    basic = by_block["*D7"]
    assert float(basic.dimstyle_overrides()[147]) == pytest.approx(-1.0)
    block = doc.block_of(basic)
    boxes = [e for e in block.entities if e.type == "LWPOLYLINE" and e.int(70) == 1]
    assert len(boxes) == 1 and boxes[0].int(90) == 4
    # nothing was painted for it: its block is drawn from the definition points
    assert [e.get(1) for e in block.entities if e.type == "TEXT"] == ["50"]
    assert len([e for e in block.entities if e.type == "SOLID"]) == 2


def test_a_detail_view_dimension_has_explicit_text_and_its_own_dimlfac():
    doc = read(dims_sheet())
    detail = dimension(doc, "*D8")
    assert detail.get(1) == "5" and "<>" not in detail.get(1)
    overrides = detail.dimstyle_overrides()
    assert float(overrides[144]) == pytest.approx(0.25)  # 1:2 sheet, 2:1 detail
    (x0, y0), (x1, y1) = detail.point(13), detail.point(14)
    assert math.hypot(x1 - x0, y1 - y0) * float(overrides[144]) == pytest.approx(5.0)
    assert detail.xdata()[0] == R.Tag(1000, "DSTYLE")
    # dimensions at the sheet's scale need no DIMLFAC
    assert 144 not in dimension(doc, "*D1").dimstyle_overrides()


def test_precision_other_than_the_styles_is_an_override():
    doc = read(dims_sheet())
    assert 271 not in dimension(doc, "*D1").dimstyle_overrides()  # 2 places, the style's
    assert int(dimension(doc, "*D4").dimstyle_overrides()[271]) == 0
    assert int(dimension(doc, "*D5").dimstyle_overrides()[179]) == 0
    style = doc.tables["DIMSTYLE"].entry("SOLIDSEAS_MM")
    assert style.int(271) == 2 and style.float(140) == 3.0 and style.float(40) == 2.0


def test_a_non_measuring_kind_is_text_where_the_sheet_put_it():
    doc = read(dims_sheet())
    chamfer = [e for e in doc.find("MTEXT", "DIM") if e.text.startswith("1 X 45")]
    assert len(chamfer) == 1 and chamfer[0].text == "1 X 45%%d"


# --------------------------------------------------------------------------- frames, datums, stamp, notes


def test_frames_and_datum_symbols_are_inserted_blocks():
    doc = read(dims_sheet())
    inserts = {e.get(2): e for e in doc.find("INSERT", "DIM")}
    assert set(inserts) == {"SS_FCF_1", "SS_FCF_2", "SS_DATUM_1"}
    assert inserts["SS_FCF_1"].point(10) == pytest.approx((240.0, 60.0))
    drawn = doc.blocks["SS_FCF_1"]
    assert drawn.begin.point(10) == pytest.approx((240.0, 60.0))
    kinds = {e.type for e in drawn.entities}
    assert {"LWPOLYLINE", "LINE", "CIRCLE", "TEXT"} <= kinds
    assert "%%c0.2" in [e.get(1) for e in drawn.entities if e.type == "TEXT"]
    assert "M" in [e.get(1) for e in drawn.entities if e.type == "TEXT"]  # the MMC modifier, circled
    # the frame painted under d-lin's owner is its own block, not part of d-lin's
    painted = doc.blocks["SS_FCF_2"]
    assert [e.get(1) for e in painted.entities if e.type == "TEXT"] == ["0.1"]
    assert "0.1" not in [e.get(1) for e in doc.block_of(dimension(doc, "*D1")).entities]
    datum = doc.blocks["SS_DATUM_1"]
    assert [e.get(1) for e in datum.entities if e.type == "TEXT"] == ["A"]
    assert {"LWPOLYLINE", "SOLID"} <= {e.type for e in datum.entities}
    assert all(e.layer == "0" for e in datum.entities)


def test_the_note_frame_is_a_block_after_its_words():
    doc = read(sample_sheet())
    note = doc.find("MTEXT", "NOTES")[0]
    assert note.text == "UNLESS OTHERWISE SPECIFIED, ALL SURFACES"
    insert = doc.find("INSERT")[0]
    block = doc.block_of(insert)
    assert insert.point(10)[0] > note.point(10)[0] + 150.0
    assert ["0.4", "A", "B", "C"] == [e.get(1) for e in block.entities if e.type == "TEXT"]


def test_the_stamp_is_text_on_its_own_layer():
    doc = read(dims_sheet())
    stamps = doc.find("TEXT", "STAMP")
    assert len(stamps) == 1
    assert stamps[0].get(1) == "PRELIMINARY - NOT FOR MANUFACTURE"
    assert stamps[0].float(50) == 90.0 and stamps[0].float(40) == pytest.approx(6.0)
    everything = [e.get(1) for e in R.drawn(doc)]
    assert everything.count("PRELIMINARY - NOT FOR MANUFACTURE") == 1


def test_furniture_with_nothing_painted_is_drawn_from_the_sheet():
    doc = read(dims_sheet())
    border = doc.find("LWPOLYLINE", "BORDER")
    assert len(border) == 1 and border[0].points(10)[0] == pytest.approx((19.304, 19.304))
    zones = [e.get(1) for e in doc.find("TEXT", "BORDER")]
    assert sorted(set(zones)) == ["1", "2", "A", "B"]
    title = [e.get(1) for e in doc.find("TEXT", "TITLE")]
    assert title == [f"COMPANY: {COMPANY}", "TITLE: PLATE"]
    assert len(doc.find("LINE", "CENTER")) == 2


def test_strings_are_cleaned_and_escaped_without_breaking_the_file():
    data = dxf_bytes(hostile_sheet())
    doc = R.read(data)  # parses: no stray line break, all ASCII
    assert b"\x07" not in data and b"\x00" not in data
    title = [e.get(1) for e in doc.find("TEXT", "TITLE") if "TITLE" in e.get(1)]
    assert title == ["TITLE \\U+005CP {BOLD} ^ J  M\\U+00FCller 100%%%%%% END"]
    note = [e for e in doc.find("MTEXT", "NOTES") if "TITLE" in e.text]
    assert note[0].text == "TITLE \\\\P \\{BOLD\\} ^ J  M\\U+00FCller 100%%%%%% END"
    # the leader ends in an arrowhead on its first point
    assert doc.find("SOLID", "NOTES")[0].point(10) == pytest.approx((120.0, 240.0))


def test_a_long_string_is_cut_or_split_whole():
    words = "\u00d8" * 200 + "A" * 300
    sheet = D.Sheet(
        "A",
        279.4,
        215.9,
        annotations=(D.Note("n-1", (10.0, 100.0), ((words, ()),)),),
        painted=(text_run(10.0, 10.0, 3.0, words, layer="notes"),),
    )
    doc = read(sheet)
    text = doc.find("TEXT", "NOTES")[0].get(1)
    assert len(text) <= 250 and text.endswith("%%c")
    mtext = doc.find("MTEXT", "NOTES")[0]
    assert all(len(v) <= 250 for v in mtext.all(3) + [mtext.get(1)])
    assert mtext.text == "%%c" * 200 + "A" * 300


# --------------------------------------------------------------------------- units, determinism and refusals


def test_an_inch_drawing_is_written_in_inches():
    drawing = Drawing("dwg-1", DrawingOptions(units="in"), None, sheet=sample_sheet())
    doc = R.read(dxf_bytes(drawing))
    assert doc.var("$INSUNITS") == "1" and doc.var("$MEASUREMENT") == "0"
    assert doc.var("$DIMSTYLE") == "SOLIDSEAS_IN"
    assert R.length(doc.find("LINE", "VISIBLE")[0]) == pytest.approx(100.0 / 25.4)
    assert dimension(doc, "*D1").get(3) == "SOLIDSEAS_IN"
    style = doc.tables["DIMSTYLE"].entry("SOLIDSEAS_IN")
    assert style.float(140) == pytest.approx(0.12) and style.int(78) == 4
    stated = Drawing("dwg-1", DrawingOptions(), None, model={"units": {"unit": "in"}}, sheet=sample_sheet())
    assert R.read(dxf_bytes(stated)).var("$INSUNITS") == "1"
    assert R.read(dxf_bytes(stated, units="mm")).var("$INSUNITS") == "4"


def test_the_same_sheet_writes_the_same_bytes():
    assert dxf_bytes(dims_sheet()) == dxf_bytes(dims_sheet())
    assert dxf_bytes(sample_sheet()) == dxf_bytes(sample_sheet())


@pytest.mark.parametrize("bad", ["sheet", None, {}, 3, Drawing("dwg-1", DrawingOptions(), None)])
def test_anything_but_a_sheet_is_refused(bad):
    with pytest.raises(InvalidArgumentError) as info:
        write_dxf(bad, io.BytesIO())
    assert info.value.detail["parameter"] == "drawing"


def test_bad_arguments_and_hostile_sheets_are_refused():
    buf = io.BytesIO()
    for kw, parameter in (
        ({"units": "ft"}, "units"),
        ({"limits": 5}, "limits"),
        ({"symbol_words": 1}, "symbol_words"),
    ):
        with pytest.raises(InvalidArgumentError) as info:
            write_dxf(sample_sheet(), buf, **kw)
        assert info.value.detail["parameter"] == parameter
    with pytest.raises(InvalidArgumentError):
        write_dxf(sample_sheet(), object())
    nan = D.Sheet("A", 279.4, 215.9, geometry=(D.Segment((0.0, 0.0), (float("nan"), 1.0)),))
    bad_path = D.Sheet("A", 279.4, 215.9, painted=(D.Stroke((("Q", 1.0),), 0.3),))
    bad_scale = D.Sheet("A", 279.4, 215.9, (0, 2))
    short = D.Sheet(
        "A",
        279.4,
        215.9,
        annotations=(D.Dimension("d-1", "linear", "", ((0.0, 0.0),), (0, 0), 1.0, D.DimText("1")),),
    )
    for sheet in (nan, bad_path, bad_scale, short):
        with pytest.raises(InvalidArgumentError) as info:
            write_dxf(sheet, buf)
        assert info.value.detail["parameter"] == "sheet"
    assert buf.getvalue() == b""


def test_hostile_item_fields_are_refused_as_a_bad_sheet():
    words = D.Note("n-1", (10.0, 10.0), ((5, ()),))
    border = D.Border(279.4, 215.9, 9.652, "two", 2)
    for item in (words, border):
        with pytest.raises(InvalidArgumentError) as info:
            dxf_bytes(D.Sheet("A", 279.4, 215.9, annotations=(item,)))
        assert info.value.detail["parameter"] == "sheet"


def test_a_sheet_through_its_compact_form_writes_the_same_entities():
    sheet = dims_sheet()
    again = D.from_compact(D.to_compact(sheet))
    a, b = read(sheet), read(again)
    assert [e.type for e in R.drawn(a)] == [e.type for e in R.drawn(b)]
    assert [d.get(1) for d in a.find("DIMENSION")] == [d.get(1) for d in b.find("DIMENSION")]


def test_two_dimensions_with_one_id_are_both_written():
    dim = D.Dimension(
        "d-1", "linear", "", ((0.0, 0.0), (10.0, 0.0), (5.0, -5.0)), (5.0, -5.0), 0.01, D.DimText("10")
    )
    painted = (_line("d-1", (0.0, -5.0), (10.0, -5.0)),)
    doc = read(D.Sheet("A", 279.4, 215.9, annotations=(dim, dim), painted=painted))
    dims = doc.find("DIMENSION")
    assert [d.get(2) for d in dims] == ["*D1", "*D2"]
    second = [e.type for e in doc.block_of(dims[1]).entities if e.layer == "0"]
    assert "TEXT" in second and second.count("SOLID") == 2  # drawn from its points


def test_suffix_lines_painted_in_pieces_round_symbols_are_found_beside():
    dim = D.Dimension(
        "d-1",
        "diameter",
        "",
        ((0.0, 0.0), (10.0, 0.0)),
        (20.0, 20.0),
        0.01,
        D.DimText("10", prefix="\u00d8", suffix=(f"{CBORE} \u00d816 {DEPTH} 5",)),
    )
    glyph = D.Stroke((("M", 20.0, 14.0), ("L", 20.0, 16.0), ("L", 22.0, 16.0)), 0.3, (), "dimensions", "d-1")
    painted = (
        _text("d-1", (20.0, 19.0), "\u00d810", anchor="left"),
        _text("d-1", (23.0, 14.0), "\u00d816", anchor="left"),
        glyph,
        _text("d-1", (34.0, 14.0), "5", anchor="left"),
    )
    doc = read(D.Sheet("A", 279.4, 215.9, annotations=(dim,), painted=painted))
    assert doc.find("DIMENSION")[0].get(1) == "%%c<>"
    beside = doc.find("MTEXT", "DIM")
    assert [e.text for e in beside] == ["\\U+2334 %%c16 \\U+21A7 5"]
    assert beside[0].point(10)[0] == pytest.approx(23.0)
    block = doc.block_of(doc.find("DIMENSION")[0])
    assert [e.get(1) for e in block.entities if e.type == "TEXT"] == ["%%c10"]


def test_the_output_bound_is_respected():
    buf = io.BytesIO()
    with pytest.raises(SldLimitError) as info:
        write_dxf(dims_sheet(), buf, limits=DrawingLimits(output_bytes=20_000))
    assert info.value.detail["limit"] == "output_bytes"
    assert buf.getvalue() == b""
    size = len(dxf_bytes(dims_sheet()))
    assert write_dxf(dims_sheet(), buf, limits=DrawingLimits(output_bytes=size)) == size


def test_no_path_or_user_name_and_no_logo_reach_the_file():
    data = dxf_bytes(sample_sheet())
    assert b"IMAGE" not in data and b"IMAGEDEF" not in data
    assert b"/home" not in data and b"C:\\" not in data and b"Users" not in data


# --------------------------------------------------------------------------- every synthetic part and fixture

SYNTHETIC = sorted(drawing_parts.PARTS)
FIXTURES = [
    "o02_boxA.SLDPRT",
    "o03_boxA_again.SLDPRT",
    "o04_boxA_props.SLDPRT",
    "o05_boxA_props_mat.SLDPRT",
    "o06_boxA_props_mat_cfg.SLDPRT",
    "o07_boxB_h31.SLDPRT",
    "o09_import_step.SLDPRT",
    "o10_import_step_cut.SLDPRT",
    "o11_curved.SLDPRT",
    "o12_multibody.SLDPRT",
]


def _flat(p):
    return (p[0], p[1])


def plan_view_sheet(m: facegraph.BrepModel):
    """A test stand-in for the views stage: the model seen from +z (x right, y up) at
    the largest preferred scale that fits an A sheet, every edge as a line, an arc in
    the view's plane, a B-spline or a polyline of its samples, a diameter dimension
    on every circle facing the viewer, and an overall linear dimension."""
    (x0, y0, _z0), (x1, y1, _z1) = m.box
    size = max(x1 - x0, y1 - y0) * 1000.0
    scale = next(
        (s for s in ((2, 1), (1, 1), (1, 2), (1, 4), (1, 10)) if size * s[0] / s[1] <= 150.0), (1, 20)
    )
    k = scale[0] / scale[1]
    view = D.ViewPlacement("v-1", (40.0 - x0 * 1000.0 * k, 40.0 - y0 * 1000.0 * k), k, "")
    in_view, dims = [], []
    for key in sorted(m.edges):
        edge = m.edges[key]
        src = D.Src(edge.body, edge.signature, "v-1")
        c = edge.curve
        if c.kind == "line" and edge.ends is not None:
            in_view.append(D.Segment(_flat(edge.ends[0]), _flat(edge.ends[1]), "visible", src))
        elif c.kind == "circle" and abs(abs(c.direction[2]) - 1.0) < 1e-9:
            centre = _flat(c.point)
            if edge.ends is None:
                in_view.append(D.Arc(centre, c.radius, 0.0, 360.0, "visible", src))
                at = view.to_sheet((centre[0] + c.radius, centre[1]))
                back = view.to_sheet((centre[0] - c.radius, centre[1]))
                dims.append(
                    D.Dimension(
                        f"d-{len(dims) + 1}", "diameter", "v-1", (at, back), (at[0] + 10.0, at[1] + 10.0),
                        2 * c.radius, D.DimText(f"{2000 * c.radius:.2f}", prefix="Ø"),
                    )
                )  # fmt: skip
            else:
                ang = [math.degrees(math.atan2(p[1] - centre[1], p[0] - centre[0])) for p in edge.points]
                a0, a1, mid = ang[0], ang[-1], ang[len(ang) // 2]
                if (mid - a0) % 360.0 > (a1 - a0) % 360.0:
                    a0, a1 = a1, a0
                in_view.append(D.Arc(centre, c.radius, a0, a1, "visible", src))
        elif c.kind == "bspline" and c.points:
            pts = tuple(_flat(p) for p in c.points)
            in_view.append(D.Spline(c.degree, c.knots, pts, c.weights, "visible", src))
        elif len(edge.points) >= 2:
            in_view.append(D.Polyline(tuple(_flat(p) for p in edge.points), False, "visible", src))
    geometry = tuple(D.place(g, view) for g in in_view)
    left, right = view.to_sheet((x0, y0)), view.to_sheet((x1, y0))
    below = ((left[0] + right[0]) / 2, left[1] - 12.0)
    overall = D.DimText(f"{(x1 - x0) * 1000:.2f}")
    dims.append(D.Dimension("d-0", "linear", "v-1", (left, right, below), below, x1 - x0, overall))
    sheet = D.Sheet("A", 279.4, 215.9, scale, (view,), geometry, tuple(dims), stroke_geometry(geometry))
    return sheet, in_view


def check_document(doc: R.Document) -> None:
    handles = doc.handles()
    assert len(handles) == len(set(handles))
    known = set(handles)
    assert all(v == "0" or v in known for _r, _c, v in doc.references())
    assert {n.upper() for n in R.used_layers(doc)} <= {n.upper() for n in doc.tables["LAYER"].names()}
    assert {n.upper() for n in R.used_linetypes(doc)} <= {n.upper() for n in doc.tables["LTYPE"].names()}
    assert R.used_styles(doc) <= set(doc.tables["STYLE"].names())
    for d in doc.find("DIMENSION"):
        assert "<>" in d.get(1)
        assert [e for e in doc.block_of(d).entities if e.layer != "DEFPOINTS"]


def check_true_size(doc: R.Document, in_view) -> None:
    lines = doc.find("LINE", "VISIBLE")
    segments = [g for g in in_view if isinstance(g, D.Segment)]
    assert len(lines) == len(segments)
    for line, seg in zip(lines, segments, strict=True):
        assert R.length(line) == pytest.approx(math.dist(seg.p0, seg.p1) * 1000.0, abs=1e-6)
    assert len(R.drawn(doc)) >= len(in_view)


@pytest.mark.parametrize("name", SYNTHETIC)
def test_every_synthetic_part_writes_a_dxf_the_reader_accepts(name):
    sheet, in_view = plan_view_sheet(drawing_model(name))
    doc = read(sheet)
    check_document(doc)
    check_true_size(doc, in_view)
    assert len(doc.find("DIMENSION")) == len(sheet.annotations)


@pytest.mark.parametrize("name", FIXTURES)
def test_every_fixture_part_writes_a_dxf_the_reader_accepts(name):
    with open_document(fixture(name)) as document:
        m = facegraph.from_document(document)
    sheet, in_view = plan_view_sheet(m)
    doc = read(sheet)
    check_document(doc)
    check_true_size(doc, in_view)
