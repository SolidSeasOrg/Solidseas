"""The SVG reference writer of the painted layer (docs/DRAWINGS.md 12.3, 12.4)."""

import io
import re
import xml.etree.ElementTree as ET

from drawing_support import sample_sheet
from solidseas.drawing import display as D
from solidseas.drawing import svg

SVG = "{http://www.w3.org/2000/svg}"


def test_the_sheet_is_a_well_formed_svg_in_millimetres():
    text = svg.to_svg(sample_sheet(), "o11 drawing")
    root = ET.fromstring(text)
    assert root.tag == SVG + "svg"
    assert root.get("width") == "279.4mm" and root.get("height") == "215.9mm"
    assert root.get("viewBox") == "0 0 279.4 215.9"
    assert root.find(SVG + "title").text == "o11 drawing"


def test_layers_are_groups_in_the_standard_order():
    root = ET.fromstring(svg.to_svg(sample_sheet()))
    ids = [g.get("id") for g in root.findall(SVG + "g")]
    assert ids == ["layer-visible", "layer-hidden", "layer-tangent", "layer-centre", "layer-phantom",
                   "layer-dimensions", "layer-title", "layer-stamp"]  # fmt: skip


def test_y_is_flipped_and_strokes_keep_their_widths_and_dashes():
    sheet = D.Sheet(
        "A", 100.0, 50.0, painted=(D.Stroke((("M", 10.0, 5.0), ("L", 20.0, 5.0)), 0.3, (3.0, 1.5), "hidden"),)
    )
    path = ET.fromstring(svg.to_svg(sheet)).find(f"{SVG}g/{SVG}path")
    assert path.get("d") == "M10 45 L20 45"
    assert path.get("stroke-width") == "0.3" and path.get("stroke-dasharray") == "3 1.5"
    assert path.get("fill") == "none"


def test_text_is_escaped_anchored_and_rotated():
    text = svg.to_svg(sample_sheet())
    assert 'BRACKET &lt;&amp; "TEST"&gt;' in text
    root = ET.fromstring(text)
    runs = {t.text: t for t in root.iter(SVG + "text")}
    assert runs["100"].get("text-anchor") == "middle"
    assert runs['BRACKET <& "TEST">'].get("font-weight") == "bold"
    assert runs["PRELIMINARY - NOT FOR MANUFACTURE"].get("transform").startswith("rotate(-90 ")


def test_the_logo_is_an_inline_png_and_nothing_is_active():
    text = svg.to_svg(sample_sheet())
    image = ET.fromstring(text).find(f".//{SVG}image")
    assert image.get("href").startswith("data:image/png;base64,")
    lowered = text.lower()
    for active in ("<script", "javascript:", "onload", 'xlink:href="http', "<a ", "<foreignobject"):
        assert active not in lowered


def test_writing_twice_gives_the_same_bytes():
    a, b = io.BytesIO(), io.BytesIO()
    n = svg.write_svg(sample_sheet(), a)
    svg.write_svg(sample_sheet(), b)
    assert a.getvalue() == b.getvalue() and n == len(a.getvalue())


def test_numbers_have_three_decimals_and_no_negative_zero():
    assert svg._n(1.23456) == "1.235" and svg._n(-0.0001) == "0" and svg._n(2.0) == "2"
    text = svg.to_svg(sample_sheet())
    assert not re.search(r"\d\.\d{4,}", text.split("base64,")[0])


def test_goldens_compare_within_a_hundredth():
    sheet = sample_sheet()
    a = svg.to_svg(sheet)
    moved = D.Sheet(
        sheet.name,
        sheet.width,
        sheet.height,
        sheet.scale,
        sheet.views,
        sheet.geometry,
        sheet.annotations,
        tuple(
            D.Stroke(
                tuple((op[0], *(c + 0.004 for c in op[1:])) for op in p.path),
                p.width,
                p.dash,
                p.layer,
                p.owner,
            )
            if isinstance(p, D.Stroke)
            else p
            for p in sheet.painted
        ),
    )
    b = svg.to_svg(moved)
    assert a != b and svg.close_enough(a, b)
    far = D.Sheet("A", 279.4, 215.9, painted=(D.Stroke((("M", 0.0, 0.0), ("L", 1.0, 1.0)), 0.3),))
    assert not svg.close_enough(a, svg.to_svg(far))


def test_the_compact_sheet_draws_the_same():
    sheet = sample_sheet()
    again = D.from_compact(D.to_compact(sheet))
    assert svg.close_enough(svg.to_svg(sheet), svg.to_svg(again), 0.001)
