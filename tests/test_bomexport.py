"""BOM exports (``solidseas.bomexport``): CSV, Excel and PDF of a table as shown."""

import dataclasses
import io
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib

import pytest

from solidseas import InvalidArgumentError, open_document
from solidseas import bom as bom_mod
from solidseas.bomexport import csv_bytes, pdf_bytes, xlsx_bytes
from solidseas.bomtable import apply, row_keys, spec
from support import fixture_path

MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


@pytest.fixture(scope="module")
def o16():
    with open_document(fixture_path("o16_asm_features.SLDASM")) as doc:
        return bom_mod.build_bom(doc, bom_type="indented", columns=["Description"])


def _edited(b):
    keys = row_keys(b)
    return apply(
        spec(
            "indented",
            ["item", "part_number", "description", "quantity", "property:Description"],
            overrides={(keys["1"], "description"): "=HYPERLINK(1)", (keys["4"], "quantity"): "3 + 1 spare"},
        ),
        b,
    )


def _cells(data: bytes) -> list[list[tuple[str | None, str]]]:
    """Every row of the workbook's sheet as (cell type, text)."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in root.iter(MAIN + "row"):
        cells = []
        for c in row:
            if c.get("t") == "inlineStr":
                cells.append(("text", "".join(t.text or "" for t in c.iter(MAIN + "t"))))
            else:
                cells.append((c.get("t"), c.find(MAIN + "v").text))
        rows.append(cells)
    return rows


def _pages_text(data: bytes) -> bytes:
    """Every content stream of a PDF, inflated."""
    return b"".join(
        zlib.decompress(m) for m in re.findall(rb"/FlateDecode[^>]*>>\nstream\n(.*?)\nendstream", data, re.S)
    )


def test_csv_keeps_every_character_and_guards_against_formulas(o16):
    text = csv_bytes(_edited(o16)).decode("utf-8")
    assert text.startswith("﻿ITEM NO.,PART NUMBER,DESCRIPTION,QTY.,DESCRIPTION\r\n")
    assert "1,o02_boxA,'=HYPERLINK(1),2," in text and "o17_деталь" in text


def test_excel_holds_text_as_text_quantities_as_numbers_and_never_a_formula(o16):
    data = xlsx_bytes(_edited(o16), "o16 [BOM]")
    rows = _cells(data)
    assert [t for _, t in rows[0]] == ["ITEM NO.", "PART NUMBER", "DESCRIPTION", "QTY.", "DESCRIPTION"]
    assert rows[1][2] == ("text", "=HYPERLINK(1)"), "a cell that looks like a formula stays text"
    assert rows[1][3] == (None, "2") and rows[6][3] == ("text", "3 + 1 spare")
    assert ("text", "o17_деталь") in rows[8]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert {i.date_time for i in z.infolist()} == {(1980, 1, 1, 0, 0, 0)}
        assert {i.create_system for i in z.infolist()} == {3}
        assert b'name="o16 BOM"' in z.read("xl/workbook.xml"), (
            "characters Excel refuses in a sheet name are left out"
        )
        assert b"<f>" not in z.read("xl/worksheets/sheet1.xml")
    assert data == xlsx_bytes(_edited(o16), "o16 [BOM]"), "the same table writes the same bytes"


def test_pdf_is_lettered_as_the_drawings_and_says_what_it_cannot_show(o16):
    out = pdf_bytes(_edited(o16), "BILL OF MATERIALS - o16_asm_features")
    assert out.data.startswith(b"%PDF-1.7") and out.pages == 1
    assert len(out.problems) == 1 and "?" in out.problems[0] and "Excel files keep them" in out.problems[0]
    assert b"/Count 1" in out.data and b"(BILL OF MATERIALS - o16_asm_features)" in out.data
    assert out.data == pdf_bytes(_edited(o16), "BILL OF MATERIALS - o16_asm_features").data


def test_a_long_bom_takes_several_pages_with_the_headings_on_each(o16):
    table = _edited(o16)
    many = dataclasses.replace(table, rows=table.rows * 12)  # 108 rows
    out = pdf_bytes(many, "LONG", paper="a4")
    assert out.pages > 1 and f"/Count {out.pages}".encode() in out.data
    text = _pages_text(out.data)
    assert text.count(b"(ITEM NO.)") == out.pages
    assert f"(Page {out.pages} of {out.pages})".encode() in text
    with pytest.raises(InvalidArgumentError):
        pdf_bytes(table, "x", paper="legal")
