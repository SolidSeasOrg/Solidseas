"""The PDF writer and the narrow PNG reader (docs/DRAWINGS.md 7.1, 12.1, 12.4, 17.2, 18,
19.2 dwg-pdf). Every PDF is read back through tests/pdf_reader.py."""

import functools
import getpass
import hashlib
import io
import math
import os
import random
import re
import socket
import struct
import tracemalloc
import xml.etree.ElementTree as ET
import zlib

import pytest

import solidseas
from drawing_support import COMPANY, sample_sheet, tiny_png
from pdf_reader import PT, Name, PdfDocument, PdfError, Ref, matrix_angle
from solidseas import drawing
from solidseas.drawing import display as D
from solidseas.drawing import fonts, images, painter, pdf, svg
from solidseas.drawing.limits import DrawingLimits
from solidseas.drawing.painter import arc_beziers, text_run
from solidseas.drawing.types import Drawing, DrawingOptions, TitleField
from solidseas.errors import InvalidArgumentError, SldLimitError

SVG = "{http://www.w3.org/2000/svg}"
# Keys and names that would make a PDF do something: none may appear (12.1).
FORBIDDEN = """JavaScript JS AA OpenAction Launch URI Annots AcroForm A Action Names EmbeddedFiles
EmbeddedFile XFA SubmitForm ImportData GoToR GoToE RichMedia Movie Sound Rendition Dests Outlines
Threads URL"""
MM = 0.01  # the agreement 6.7 asks of PDF and SVG


def write(item, **kw) -> tuple[bytes, PdfDocument, list[str]]:
    fh = io.BytesIO()
    problems: list[str] = []
    n = pdf.write_pdf(item, fh, problems=problems, **kw)
    data = fh.getvalue()
    assert n == len(data)
    return data, PdfDocument(data), problems


def sheet_of(*painted, annotations=()) -> D.Sheet:
    return D.Sheet("A", 279.4, 215.9, annotations=tuple(annotations), painted=tuple(painted))


def line(x0=10.0, y0=10.0, x1=50.0, y1=10.0, **kw) -> D.Stroke:
    return D.Stroke((("M", x0, y0), ("L", x1, y1)), kw.pop("width", 0.35), **kw)


# --------------------------------------------------------------------------- PNGs built for the tests


def chunk(tag: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))


def paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def filtered(kind: int, row: bytes, prev: bytes, bpp: int) -> bytes:
    """``row`` encoded with PNG filter ``kind``, written from the specification."""
    out = bytearray([kind])
    for i, x in enumerate(row):
        a = row[i - bpp] if i >= bpp else 0
        b = prev[i]
        c = prev[i - bpp] if i >= bpp else 0
        pred = (0, a, b, (a + b) // 2, paeth(a, b, c))[kind]
        out.append((x - pred) & 0xFF)
    return bytes(out)


def pixels(width: int, height: int, channels: int, seed: int = 1) -> bytes:
    return random.Random(seed).randbytes(width * height * channels)


def make_png(
    width=6,
    height=4,
    *,
    colour=6,
    depth=8,
    interlace=0,
    data=None,
    filters=lambda y: y % 5,
    before_idat=(),
    after_idat=(),
    idat=None,
    end=True,
) -> bytes:
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour] * (depth // 8 or 1)
    data = pixels(width, height, channels) if data is None else data
    stride = width * channels
    raw = bytearray()
    prev = bytes(stride)
    for y in range(height):
        row = data[y * stride : (y + 1) * stride]
        raw += filtered(filters(y), row, prev, channels)
        prev = row
    ihdr = struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, interlace)
    body = zlib.compress(bytes(raw)) if idat is None else idat
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + b"".join(before_idat) + chunk(b"IDAT", body)
    out += b"".join(after_idat)
    return out + (chunk(b"IEND", b"") if end else b"")


def logo_sheet(png: bytes) -> D.Sheet:
    return sheet_of(
        line(layer="border"),
        text_run(182.0, 20.0, 3.0, COMPANY, layer="title"),
        D.ImageRun(182.0, 30.0, 20.0, 10.0, png, "title", "logo"),
    )


# --------------------------------------------------------------------------- the file


def test_the_reader_reads_what_the_writer_writes_and_the_xref_is_right():
    data, doc, problems = write(sample_sheet())
    assert problems == []
    assert data.startswith(b"%PDF-1.7\n%") and doc.version == "1.7"
    assert data.endswith(b"%%EOF\n")
    assert data[doc.startxref :].startswith(b"xref\n0 ")
    assert doc.trailer["Size"] == len(doc.objects) + 1 == max(doc.xref) + 1
    for num, off in doc.xref.items():
        assert data[off:].startswith(f"{num} 0 obj\n".encode())
    for obj in doc.objects.values():  # each stream's /Length is its true length (the reader checks)
        if hasattr(obj, "raw"):
            assert obj.dict["Length"] == len(obj.raw) and obj.dict["Filter"] == "FlateDecode"
    assert doc.media_box() == pytest.approx([0.0, 0.0, 279.4 * PT, 215.9 * PT], abs=1e-3)
    assert doc.get(doc.catalog, "Type") == "Catalog" and doc.get(doc.page, "Type") == "Page"
    content = doc.content()
    assert content.isascii() and doc.page["Contents"] == Ref(4, 0)
    paths, runs, placed = doc.painted()
    assert len(paths) == len([p for p in sample_sheet().painted if isinstance(p, (D.Stroke, D.Fill))])
    assert [r.text for r in runs] == ["100", 'BRACKET <& "TEST">', "PRELIMINARY - NOT FOR MANUFACTURE"]
    assert [r.font for r in runs] == ["Helvetica", "Helvetica-Bold", "Helvetica"]
    assert len(placed) == 1


def test_the_reader_refuses_a_wrong_offset():
    data, _doc, _p = write(sample_sheet())
    broken = data.replace(b"0000000015 00000 n", b"0000000016 00000 n", 1)
    with pytest.raises(PdfError, match="points at"):
        PdfDocument(broken)


def test_write_pdf_takes_a_drawing_through_the_public_entry_point():
    d = Drawing(id="dwg-1", options=DrawingOptions(), settings=None, sheet=sample_sheet())
    fh = io.BytesIO()
    n = drawing.write_pdf(d, fh)
    assert n == len(fh.getvalue()) and fh.getvalue() == pdf.to_pdf(sample_sheet()).data


def test_the_pdf_painter_is_a_painter():
    assert isinstance(pdf.PdfPainter(), painter.Painter)


def test_anything_but_a_sheet_or_a_drawing_is_refused():
    fh = io.BytesIO()
    for item in ("sheet", None, 3, D.Stroke((("M", 0.0, 0.0),), 0.3), D.to_compact(sample_sheet())):
        with pytest.raises(InvalidArgumentError) as err:
            pdf.write_pdf(item, fh)
        assert err.value.detail == {"parameter": "drawing"}
    empty = Drawing(id="dwg-1", options=DrawingOptions(), settings=None)
    with pytest.raises(InvalidArgumentError, match="no laid-out sheet"):
        pdf.write_pdf(empty, fh)
    for kw, parameter in (
        ({"limits": "small"}, "limits"),
        ({"title": 7}, "title"),
        ({"problems": ()}, "problems"),
    ):
        with pytest.raises(InvalidArgumentError) as err:
            pdf.write_pdf(sample_sheet(), fh, **kw)
        assert err.value.detail == {"parameter": parameter}
    with pytest.raises(InvalidArgumentError) as err:
        pdf.write_pdf(sample_sheet(), "out.pdf")
    assert err.value.detail == {"parameter": "fh"}
    assert fh.getvalue() == b""


def test_values_a_pdf_cannot_hold_are_refused_and_nothing_is_written():
    bad = [
        sheet_of(D.Stroke((("M", 0.0, 0.0), ("L", math.nan, 1.0)), 0.3)),
        sheet_of(D.Stroke((("M", 0.0, 0.0), ("L", 1e9, 1.0)), 0.3)),
        sheet_of(D.Stroke((("L", 0.0, 0.0),), 0.3)),
        sheet_of(D.Stroke((("M", 0.0, 0.0), ("Q", 1.0, 1.0)), 0.3)),
        sheet_of(D.Stroke((("M", 0.0, 0.0), ("L", 1.0)), 0.3)),
        sheet_of(line(dash=(3.0, -1.0))),
        sheet_of(line(width=math.inf)),
        sheet_of(line(cap=3)),
        sheet_of(D.TextRun(10.0, 10.0, 0.0, "A")),
        sheet_of(D.TextRun(10.0, 10.0, 3.0, "A", anchor="middle")),
        D.Sheet("A", 0.0, 215.9),
        D.Sheet("A", 6000.0, 215.9),
    ]
    for sheet in bad:
        fh = io.BytesIO()
        with pytest.raises(InvalidArgumentError):
            pdf.write_pdf(sheet, fh)
        assert fh.getvalue() == b""


def test_the_output_bound_is_respected():
    fh = io.BytesIO()
    with pytest.raises(SldLimitError) as err:
        pdf.write_pdf(sample_sheet(), fh, limits=DrawingLimits(output_bytes=2000))
    assert err.value.detail["limit"] == "output_bytes" and fh.getvalue() == b""
    data, _doc, _p = write(sample_sheet(), limits=DrawingLimits(output_bytes=4000))
    assert len(data) <= 4000


def test_a_text_run_longer_than_any_string_is_bounded():
    with pytest.raises(SldLimitError) as err:
        pdf.to_pdf(sheet_of(D.TextRun(10.0, 10.0, 3.0, "A" * 4097)))
    assert err.value.detail["limit"] == "string_chars"
    with pytest.raises(SldLimitError) as err:
        pdf.to_pdf(sample_sheet(), title="T" * 257)
    assert err.value.detail["limit"] == "title_chars"


# --------------------------------------------------------------------------- metadata, privacy, determinism


def test_the_producer_is_solidseas_and_the_title_comes_from_the_title_block():
    _data, doc, _p = write(sample_sheet())
    assert doc.info() == {"Producer": f"SolidSeas {solidseas.__version__}", "Title": 'BRACKET <& "TEST">'}


def test_the_title_argument_wins_and_is_escaped():
    _data, doc, _p = write(sample_sheet(), title="PLATE (2) \\ REV A")
    assert doc.info()["Title"] == "PLATE (2) \\ REV A"
    data, doc, _p = write(sample_sheet(), title="BRACKET Ø10 \u2013 1\u202e2\tX\n")
    assert doc.info()["Title"] == "BRACKET Ø10 \u2013 12 X"
    assert b"/Title <feff" in data  # not printable ASCII: UTF-16 in hexadecimal
    _data, doc, _p = write(sample_sheet(), title="")
    assert "Title" not in doc.info()


def test_the_drawing_title_is_used_when_the_sheet_has_no_title_block():
    sheet = sheet_of(line())
    title = (("number", TitleField("1234-001")), ("title", TitleField("PLATE, MOUNTING")))
    d = Drawing(id="dwg-1", options=DrawingOptions(), settings=None, sheet=sheet, title=title)
    _data, doc, _p = write(d)
    assert doc.info()["Title"] == "PLATE, MOUNTING"
    _data, doc, _p = write(sheet)
    assert "Title" not in doc.info()


def test_no_path_or_user_name_reaches_the_file(tmp_path):
    fake = "D:\\Projects\\Customer\\bracket.SLDPRT"
    sheet = sheet_of(
        text_run(182.0, 20.0, 3.0, "BRACKET", layer="title"),
        text_run(182.0, 14.0, 2.0, fake, layer="title"),
        annotations=(D.TitleBlock((180.0, 10.0), 90.0, 40.0, (("title", "BRACKET"), ("file", fake))),),
    )
    target = tmp_path / "1234-001 A PRELIMINARY.pdf"
    with open(target, "wb") as fh:
        pdf.write_pdf(sheet, fh)
    data = target.read_bytes()
    doc = PdfDocument(data)
    assert doc.info() == {"Producer": f"SolidSeas {solidseas.__version__}", "Title": "BRACKET"}
    texts = [r.text for r in doc.text_runs()]
    assert texts == ["BRACKET", fake]  # the path is where it was put, once
    content = doc.content().decode("latin-1")
    assert content.count("Projects") == 1 and content.count("Customer") == 1
    # the trailer's /ID is a digest: binary, so any byte (a backslash too) may be in it
    ids = {o for o in doc.trailer.get("ID", ()) if isinstance(o, bytes)}
    strings = b" ".join(o for o in doc.walk() if isinstance(o, bytes) and o not in ids).decode("latin-1")
    outside = re.sub(rb"stream\n.*?\nendstream", b"", data, flags=re.S).decode("latin-1")
    for text in (strings, outside):
        assert "Customer" not in text and "Projects" not in text and "\\" not in text
    needles = {str(tmp_path), os.getcwd(), os.path.expanduser("~"), target.name, "PRELIMINARY"}
    host = socket.gethostname()
    if len(host) >= 4:
        needles.add(host)
    for needle in needles:
        assert needle not in strings and needle not in outside and needle not in content
    user = getpass.getuser()  # where a name could be: a string, or text the writer added
    assert user not in strings and all(user not in text for text in texts if text != fake)
    for key in ("Author", "Creator", "CreationDate", "ModDate", "Subject", "Keywords"):
        assert key not in doc.info()
    assert "Metadata" not in doc.catalog


def test_writing_twice_gives_the_same_bytes_and_the_id_is_a_hash_of_the_content():
    a, doc, _p = write(sample_sheet())
    b, _doc, _p = write(sample_sheet())
    assert a == b
    first, second = doc.trailer["ID"]
    assert first == second and len(first) == 16
    assert first == hashlib.sha256(a[: doc.startxref]).digest()[:16]
    _c, other, _p = write(sample_sheet(), title="ANOTHER")
    assert other.trailer["ID"][0] != first


def test_nothing_active_is_in_the_file():
    hostile = "/JavaScript (app.alert(1)) /OpenAction << /S /URI /URI (http://example.com) >>"
    sheet = sheet_of(
        text_run(10.0, 10.0, 3.0, hostile, layer="notes"),
        D.ImageRun(182.0, 30.0, 20.0, 10.0, tiny_png(), "title", "logo"),
    )
    data, doc, _p = write(sheet, title=hostile)
    assert doc.info()["Title"] == hostile
    forbidden = set(FORBIDDEN.split())
    for obj in doc.walk():
        if isinstance(obj, dict):
            assert not forbidden & set(obj), sorted(forbidden & set(obj))
            assert obj.get("Type") not in ("Annot", "Action", "Filespec", "EmbeddedFile", "XObjectForm")
            assert obj.get("Subtype") in (None, "Type1", "Image")
        if isinstance(obj, Name):
            assert obj not in forbidden
    strings = [o for o in doc.walk() if isinstance(o, bytes)]
    assert [s for s in strings if b"JavaScript" in s] == [hostile.encode("ascii")]  # the title, a string
    assert doc.text_runs()[0].text == hostile


# --------------------------------------------------------------------------- text


def svg_texts(sheet: D.Sheet) -> list[ET.Element]:
    return list(ET.fromstring(svg.to_svg(sheet)).iter(SVG + "text"))


def anchor_point(run, bold: bool, anchor: str) -> tuple[float, float, float]:
    """The point a PDF text run is anchored at, in sheet millimetres, and its angle."""
    size = run.size / PT
    width = fonts.measure(run.text, size, bold)
    k = {"start": 0.0, "middle": 0.5, "end": 1.0}[anchor]
    angle = matrix_angle(run.matrix)
    a = math.radians(angle)
    x = run.matrix[4] / PT + k * width * math.cos(a)
    y = run.matrix[5] / PT + k * width * math.sin(a)
    return x, y, angle


def test_text_positions_agree_with_the_svg_writer():
    sheet = sample_sheet()
    _data, doc, _p = write(sheet)
    runs = doc.text_runs()
    texts = svg_texts(sheet)
    assert len(runs) == len(texts) == 3
    for run, el in zip(runs, texts, strict=True):
        assert run.text == el.text
        assert run.size / PT == pytest.approx(float(el.get("font-size")), abs=MM)
        bold = el.get("font-weight") == "bold"
        assert run.font == ("Helvetica-Bold" if bold else "Helvetica")
        x, y, angle = anchor_point(run, bold, el.get("text-anchor"))
        assert x == pytest.approx(float(el.get("x")), abs=MM)
        assert y == pytest.approx(sheet.height - float(el.get("y")), abs=MM)
        rotate = re.match(r"rotate\((\S+) ", el.get("transform") or "rotate(0 ")
        turn = math.radians(angle + float(rotate.group(1)))  # SVG turns the other way
        assert (math.cos(turn), math.sin(turn)) == pytest.approx((1.0, 0.0), abs=1e-9)


def test_paths_agree_with_the_svg_writer():
    sheet = sample_sheet()
    _data, doc, _p = write(sheet)
    paths = doc.paths()
    elements = list(ET.fromstring(svg.to_svg(sheet)).iter(SVG + "path"))
    assert len(paths) == len(elements)
    for path, el in zip(paths, elements, strict=True):
        numbers = [float(t) for t in re.findall(r"-?\d+(?:\.\d+)?", el.get("d"))]
        flipped = [v if i % 2 == 0 else sheet.height - v for i, v in enumerate(numbers)]
        assert path.mm() == pytest.approx(flipped, abs=MM)
        assert [op[0] for op in path.ops] == [{"M": "m", "L": "l", "C": "c", "Z": "h"}[c]
                                              for c in re.findall(r"[MLCZ]", el.get("d"))]  # fmt: skip
        if el.get("fill") == "none":
            assert path.paint == "S"
            assert path.width / PT == pytest.approx(float(el.get("stroke-width")), abs=MM)
            dash = [float(v) for v in (el.get("stroke-dasharray") or "").split()]
            assert [d / PT for d in path.dash] == pytest.approx(dash, abs=MM)
        else:
            assert path.paint == "f"


def test_anchor_centre_and_right_shift_by_the_measured_width():
    word = "Ø12.7 THRU"
    sheet = sheet_of(
        D.TextRun(100.0, 50.0, 5.0, word, anchor="left", layer="notes"),
        D.TextRun(100.0, 60.0, 5.0, word, anchor="centre", layer="notes"),
        D.TextRun(100.0, 70.0, 5.0, word, anchor="right", bold=True, layer="notes"),
    )
    runs = write(sheet)[1].text_runs()
    regular, bold = fonts.measure(word, 5.0), fonts.measure(word, 5.0, True)
    assert [r.matrix[4] / PT for r in runs] == pytest.approx(
        [100.0, 100.0 - regular / 2, 100.0 - bold], abs=1e-3
    )
    assert [r.matrix[5] / PT for r in runs] == pytest.approx([50.0, 60.0, 70.0], abs=1e-3)
    assert [r.font for r in runs] == ["Helvetica", "Helvetica", "Helvetica-Bold"]
    assert all(r.size == pytest.approx(5.0 * PT, abs=1e-3) for r in runs)
    assert runs[0].text == word and b"\\330" in write(sheet)[1].content()  # Ø as an octal escape


def test_rotated_text_turns_through_the_text_matrix():
    sheet = sheet_of(
        D.TextRun(40.0, 40.0, 4.0, "SECTION A-A", angle_deg=90.0, layer="notes"),
        D.TextRun(80.0, 40.0, 4.0, "R5", angle_deg=30.0, anchor="right", layer="notes"),
        D.TextRun(120.0, 40.0, 4.0, "R5", angle_deg=-120.0, anchor="centre", layer="notes"),
    )
    runs = write(sheet)[1].text_runs()
    assert runs[0].matrix[:4] == pytest.approx((0.0, 1.0, -1.0, 0.0), abs=1e-6)
    assert [matrix_angle(r.matrix) for r in runs] == pytest.approx([90.0, 30.0, -120.0], abs=1e-4)
    w = fonts.measure("R5", 4.0)
    assert (runs[1].matrix[4] / PT, runs[1].matrix[5] / PT) == pytest.approx(
        (80.0 - w * math.cos(math.radians(30)), 40.0 - w * math.sin(math.radians(30))), abs=1e-3
    )
    for run, el in zip(runs, svg_texts(sheet), strict=True):
        x, y, _angle = anchor_point(run, False, el.get("text-anchor"))
        assert (x, y) == pytest.approx((float(el.get("x")), sheet.height - float(el.get("y"))), abs=MM)


def test_text_outside_winansi_is_refused_naming_the_character():
    for text, code in (("\u2316 0.25 A", "U+2316"), ("\u2300 10", "U+2300"), ("LINE\nTWO", "U+000A")):
        with pytest.raises(InvalidArgumentError) as err:
            pdf.to_pdf(sheet_of(D.TextRun(10.0, 10.0, 3.0, text)))
        assert code in str(err.value) and err.value.detail["parameter"] == "text"
    with pytest.raises(InvalidArgumentError, match="the character \u2316 "):
        pdf.to_pdf(sheet_of(D.TextRun(1.0, 1.0, 3.0, "\u2316")))
    # Every WinAnsi character above ASCII goes through, the euro and the dashes among them.
    text = "".join(ch for ch in map(chr, range(0x20, 0x2200)) if fonts.winansi(ch) is not None)
    runs = write(sheet_of(D.TextRun(10.0, 10.0, 3.0, text)))[1].text_runs()
    assert runs[0].text == text


def test_gdt_symbols_reach_the_pdf_only_as_paths():
    # A position frame as layout draws it: the box, the symbol as a circle and a cross, and
    # the WinAnsi text beside it. The symbol itself is never text.
    cx, cy, r = 105.0, 52.5, 1.6
    circle = (("M", cx + r, cy), *arc_beziers(cx, cy, r, 0.0, 360.0), ("Z",))
    sheet = sheet_of(
        D.Stroke(
            (("M", 100.0, 50.0), ("L", 140.0, 50.0), ("L", 140.0, 55.0), ("L", 100.0, 55.0), ("Z",)),
            0.25,
            layer="dimensions",
            owner="f-1",
        ),  # fmt: skip
        D.Stroke(circle, 0.25, layer="dimensions", owner="f-1"),
        D.Stroke((("M", cx - 2.4, cy), ("L", cx + 2.4, cy)), 0.25, layer="dimensions", owner="f-1"),
        D.Stroke((("M", cx, cy - 2.4), ("L", cx, cy + 2.4)), 0.25, layer="dimensions", owner="f-1"),
        D.TextRun(112.0, 51.0, 3.5, "Ø0.25 M A B C", layer="dimensions", owner="f-1"),
    )
    _data, doc, _p = write(sheet)
    paths = doc.paths()
    assert len(paths) == 4 and all(p.group == "Dimensions" for p in paths)
    assert [op[0] for op in paths[1].ops] == ["m", "c", "c", "c", "c", "h"]
    assert paths[1].mm()[:2] == pytest.approx([cx + r, cy], abs=1e-3)
    assert [r.text for r in doc.text_runs()] == ["Ø0.25 M A B C"]


# --------------------------------------------------------------------------- strokes, fills, layers


def test_strokes_keep_width_dash_cap_join_and_grey():
    sheet = sheet_of(
        line(width=0.35, dash=(3.0, 1.5), cap=1, join=2, grey=0.5, layer="hidden"),
        line(width=0.7, layer="hidden"),
        line(width=0.25, dash=(0.0, 0.0), layer="hidden"),
        line(width=0.25, dash=(12.0, 1.5, 3.0, 1.5), grey=2.0, layer="centre"),
    )
    paths = write(sheet)[1].paths()
    assert [p.width / PT for p in paths] == pytest.approx([0.35, 0.7, 0.25, 0.25], abs=1e-3)
    assert [[d / PT for d in p.dash] for p in paths] == [
        pytest.approx([3.0, 1.5], abs=1e-3), [], [], pytest.approx([12.0, 1.5, 3.0, 1.5], abs=1e-3)
    ]  # fmt: skip
    assert [(p.cap, p.join) for p in paths] == [(1, 2), (0, 0), (0, 0), (0, 0)]
    assert [p.stroke_grey for p in paths] == [0.5, 0.0, 0.0, 1.0]
    assert all(p.paint == "S" for p in paths)


def test_fills_and_beziers_are_written_as_the_painter_gives_them():
    curve = (("M", 10.0, 10.0), ("C", 12.0, 15.0, 18.0, 15.0, 20.0, 10.0), ("Z",))
    sheet = sheet_of(D.Fill(curve, "dimensions", "d-1", 0.25), D.TextRun(30.0, 30.0, 3.0, "A"))
    paths, runs, _placed = write(sheet)[1].painted()
    assert paths[0].paint == "f" and paths[0].fill_grey == 0.25
    assert paths[0].ops[1][0] == "c" and paths[0].mm() == pytest.approx(
        [10.0, 10.0, 12.0, 15.0, 18.0, 15.0, 20.0, 10.0], abs=1e-3
    )
    assert runs[0].fill_grey == 0.0  # text is black whatever was filled before


def test_layers_are_optional_content_groups_with_their_names():
    sheet = sheet_of(*(line(y0=10.0 + i, y1=10.0 + i, layer=layer) for i, layer in enumerate(D.LAYERS)))
    data, doc, problems = write(sheet)
    assert problems == []
    assert doc.ocg_names() == list(pdf.GROUPS)
    assert pdf.GROUPS == ("Visible", "Hidden", "Centre lines", "Dimensions", "Notes", "Title block", "Stamp")
    by_y = {round(p.mm()[1] - 10.0): p.group for p in doc.paths()}
    assert [by_y[i] for i in range(len(D.LAYERS))] == [pdf.LAYER_GROUP[layer] for layer in D.LAYERS]
    assert pdf.LAYER_GROUP == {
        "visible": "Visible", "hidden": "Hidden", "tangent": "Hidden", "centre": "Centre lines",
        "phantom": "Hidden", "hatch": "Visible", "border": "Visible", "dimensions": "Dimensions",
        "notes": "Notes", "title": "Title block", "stamp": "Stamp",
    }  # fmt: skip
    props = doc.get(doc.catalog, "OCProperties")
    default = doc.get(props, "D")
    assert default["BaseState"] == "ON" and "OFF" not in default
    assert (
        [r.num for r in default["ON"]] == [r.num for r in props["OCGs"]] == [r.num for r in default["Order"]]
    )
    assert doc.get(doc.catalog, "ViewerPreferences") == {"PrintScaling": "None"}


def test_the_sample_sheet_draws_each_layer_in_its_group():
    paths, runs, placed = write(sample_sheet())[1].painted()
    assert write(sample_sheet())[1].ocg_names() == ["Visible", "Hidden", "Centre lines", "Dimensions",
                                                    "Title block", "Stamp"]  # fmt: skip
    assert {p.group for p in paths if p.dash} >= {"Hidden", "Centre lines"}
    assert [r.group for r in runs] == ["Dimensions", "Title block", "Stamp"]
    assert placed[0].group == "Title block"


def test_an_unknown_layer_is_drawn_with_visible_and_said():
    data, doc, problems = write(sheet_of(line(layer="mystery"), line(layer="mystery")))
    assert [p.group for p in doc.paths()] == ["Visible", "Visible"]
    assert problems == ["items on the unknown layer 'mystery' were drawn in the Visible group"]


def test_an_empty_sheet_is_a_blank_page():
    _data, doc, problems = write(D.Sheet("B", 431.8, 279.4))
    assert doc.media_box() == pytest.approx([0.0, 0.0, 431.8 * PT, 279.4 * PT], abs=1e-3)
    assert doc.painted() == ([], [], []) and doc.ocg_names() == [] and problems == []


# --------------------------------------------------------------------------- the logo


def test_the_logo_is_an_image_with_a_soft_mask_where_its_run_puts_it():
    data = pixels(6, 4, 4)
    png = make_png(6, 4, data=data)
    _bytes, doc, problems = write(logo_sheet(png))
    assert problems == []
    (placed,) = doc.images()
    assert placed.matrix == pytest.approx((20.0 * PT, 0.0, 0.0, 10.0 * PT, 182.0 * PT, 30.0 * PT), abs=1e-3)
    image = placed.xobject.dict
    assert (image["Subtype"], image["Width"], image["Height"], image["BitsPerComponent"]) == (
        "Image",
        6,
        4,
        8,
    )
    assert image["ColorSpace"] == "DeviceRGB"
    rgb = bytes(b for i, b in enumerate(data) if i % 4 != 3)
    assert placed.xobject.data() == rgb
    mask = doc.resolve(image["SMask"])
    assert mask.dict["ColorSpace"] == "DeviceGray" and (mask.dict["Width"], mask.dict["Height"]) == (6, 4)
    assert mask.data() == data[3::4]
    assert placed.group == "Title block"


def test_an_rgb_logo_has_no_soft_mask():
    data = pixels(5, 3, 3)
    _bytes, doc, problems = write(logo_sheet(make_png(5, 3, colour=2, data=data)))
    (placed,) = doc.images()
    assert problems == [] and "SMask" not in placed.xobject.dict and placed.xobject.data() == data


def test_the_same_logo_twice_is_stored_once():
    png = tiny_png()
    sheet = sheet_of(D.ImageRun(10.0, 10.0, 20.0, 10.0, png), D.ImageRun(40.0, 10.0, 20.0, 10.0, png))
    doc = write(sheet)[1]
    placed = doc.images()
    assert len(placed) == 2 and placed[0].name == placed[1].name
    assert (
        sum(1 for o in doc.objects.values() if getattr(o, "dict", {}).get("Subtype") == "Image") == 2
    )  # + mask


@functools.cache
def bomb(megabytes: int) -> bytes:
    c = zlib.compressobj(9)
    block = bytes(1 << 20)
    body = b"".join(c.compress(block) for _ in range(megabytes)) + c.flush()
    return body


def palette_png() -> bytes:
    return make_png(colour=3, before_idat=(chunk(b"PLTE", bytes(range(12))),))


def raw_png(raw: bytes) -> bytes:
    """A 6 by 4 RGBA header over the pixel data ``raw``, compressed as it is."""
    return make_png(idat=zlib.compress(raw))


REFUSED = {
    "16-bit": (lambda: make_png(colour=6, depth=16), "format", "16-bit"),
    "palette": (palette_png, "format", "palette"),
    "greyscale": (lambda: make_png(colour=0), "format", "greyscale"),
    "interlaced": (lambda: make_png(interlace=1), "format", "interlaced"),
    "too wide": (lambda: make_png(1201, 1, filters=lambda y: 0), "image_size", "1,200"),
    "too many bytes": (lambda: make_png(400, 400, filters=lambda y: 0), "file_size", "524,288"),
    "bad CRC": (lambda: make_png()[:-16] + bytes(4) + make_png()[-12:], "crc", "IDAT chunk has a wrong CRC"),
    "truncated": (lambda: make_png()[:60], "truncated", "past the end"),
    "no IEND": (lambda: make_png(end=False), "truncated", "IEND"),
    "zlib bomb": (lambda: make_png(idat=bomb(200)), "pixels", "longer"),
    "short pixels": (lambda: raw_png(bytes(10)), "pixels", "shorter"),
    "damaged zlib": (lambda: make_png(idat=b"\x78\x9c\xff\xff\xff"), "pixels", "damaged"),
    "bytes after the pixels": (lambda: make_png(idat=zlib.compress(bytes(100)) + b"xx"), "pixels", "after"),
    "unknown filter": (lambda: raw_png(b"\x05" + bytes(99)), "filter", "filter type 5"),
    "transparency": (lambda: make_png(colour=2, before_idat=(chunk(b"tRNS", bytes(6)),)), "format", "tRNS"),
    "unknown critical chunk": (lambda: make_png(before_idat=(chunk(b"ABCD", b""),)), "chunk", "ABCD"),
    "split pixel data": (
        lambda: make_png(after_idat=(chunk(b"tEXt", b"a\x00b"), chunk(b"IDAT", b""))),
        "chunk",
        "consecutive",
    ),
    "second header": (lambda: make_png(before_idat=(chunk(b"IHDR", bytes(13)),)), "chunk", "second header"),
    "not a PNG": (lambda: b"GIF89a" + bytes(40), "not_png", "not a PNG"),
    "empty": (lambda: b"", "not_png", "not a PNG"),
}


@pytest.mark.parametrize("case", sorted(REFUSED))
def test_a_png_outside_the_narrow_form_is_refused_and_the_page_still_written(case):
    make, rule, words = REFUSED[case]
    png = make()
    with pytest.raises(images.PngRefused) as err:
        images.read_png(png)
    assert err.value.detail == {"parameter": "png", "rule": rule}
    assert words in str(err.value)
    assert isinstance(err.value, InvalidArgumentError) and images.png_problem(png) == str(err.value)
    _bytes, doc, problems = write(logo_sheet(png))
    assert problems == [f"the logo was left out: {err.value}"]
    assert doc.images() == [] and "XObject" not in doc.get(doc.page, "Resources")
    assert [r.text for r in doc.text_runs()] == [COMPANY] and len(doc.paths()) == 1


def test_a_zlib_bomb_is_inflated_no_further_than_the_header_allows():
    png = make_png(idat=bomb(200))
    assert len(png) < 512 * 1024
    tracemalloc.start()
    try:
        with pytest.raises(images.PngRefused, match="longer"):
            images.read_png(png)
        _now, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 1 << 22  # 4 MiB, far from the 200 MB it would inflate to


def test_a_logo_over_the_callers_bounds_is_refused():
    png = make_png(30, 20)
    assert images.read_png(png).width == 30
    with pytest.raises(images.PngRefused, match="at most 16 a side"):
        images.read_png(png, limits=DrawingLimits(logo_pixels=16))
    with pytest.raises(images.PngRefused, match="at most 100$"):
        images.read_png(png, limits=DrawingLimits(logo_bytes=100))
    with pytest.raises(InvalidArgumentError):
        images.read_png(png, limits="small")


@pytest.mark.parametrize("colour, channels", [(2, 3), (6, 4)])
@pytest.mark.parametrize("width", [1, 2, 7, 37])
def test_all_five_filters_are_undone(colour, channels, width):
    height = 15
    data = pixels(width, height, channels, seed=width)
    for scheme in (lambda y: y % 5, lambda y: 4 - y % 5, lambda y: 1, lambda y: 3, lambda y: 4):
        image = images.read_png(make_png(width, height, colour=colour, data=data, filters=scheme))
        assert (image.width, image.height) == (width, height)
        if channels == 3:
            assert image.rgb == data and image.alpha is None
        else:
            assert image.rgb == bytes(b for i, b in enumerate(data) if i % 4 != 3)
            assert image.alpha == data[3::4]


def test_ancillary_chunks_and_a_suggested_palette_are_skipped():
    data = pixels(6, 4, 3)
    extra = (chunk(b"gAMA", struct.pack(">I", 45455)), chunk(b"PLTE", bytes(6)), chunk(b"pHYs", bytes(9)))
    png = make_png(6, 4, colour=2, data=data, before_idat=extra, after_idat=(chunk(b"tEXt", b"k\x00v"),))
    assert images.read_png(png).rgb == data
    assert images.read_png(png + b"anything after IEND is never read").rgb == data
    head = make_png(6, 4, colour=2, data=data)[:33]  # the signature and IHDR
    body = zlib.compress(b"".join(filtered(0, data[y * 18 : (y + 1) * 18], bytes(18), 3) for y in range(4)))
    two = head + chunk(b"IDAT", body[:5]) + chunk(b"IDAT", body[5:]) + chunk(b"IEND", b"")
    assert images.read_png(two).rgb == data


def test_the_logo_drawing_support_makes_is_accepted():
    image = images.read_png(tiny_png())
    assert (image.width, image.height) == (4, 2)
    assert image.rgb == b"\x10\x20\x30" * 8 and image.alpha == b"\xff" * 8


def test_an_image_with_no_size_on_the_sheet_is_left_out():
    _bytes, doc, problems = write(sheet_of(D.ImageRun(10.0, 10.0, 0.0, 10.0, tiny_png())))
    assert doc.images() == [] and problems == [
        "the logo was left out: its size on the sheet is not more than 0"
    ]
