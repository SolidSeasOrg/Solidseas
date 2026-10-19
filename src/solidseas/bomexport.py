"""A BOM table as shown (:class:`~solidseas.bomtable.ShownTable`) written as CSV, Excel
or PDF bytes (provisional). Pure Python, standard library only; nothing here writes a
file.

* **CSV**: the headings, then a row each, UTF-8 after a byte order mark with
  ``\\r\\n`` line ends, as :func:`solidseas.bom.csv_bytes` writes. Text a spreadsheet
  would run as a formula gets a leading apostrophe.
* **Excel** (``.xlsx``): one sheet, the headings bold and frozen, every cell an
  inline string except a quantity column's whole numbers, so no cell is ever a
  formula. The bytes are the same for the same table: every zip entry is dated
  1980-01-01 and marked as made on Unix, and no creation or change time is
  written (the ``reproducible-xlsx-bytes`` recipe).
* **PDF**: the table on Letter or A4 paper turned sideways, the title above it, the
  headings repeated on each page and ``Page 1 of 2`` below, lettered in
  Helvetica as the drawings are (:func:`solidseas.drawing.pdf.painted_pdf`). A
  cell too wide for its column is cut with an ellipsis. Those fonts show the
  Windows Latin characters only, so any other character is shown as ``?`` and
  :attr:`PdfExport.problems` says so; the CSV and Excel files keep every
  character.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from xml.sax.saxutils import escape

from .bomtable import ShownTable
from .drawing import fonts
from .drawing.pdf import PdfPainter, painted_pdf
from .errors import InvalidArgumentError

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
PAPERS = {"letter": (279.4, 215.9), "a4": (297.0, 210.0)}  # mm, landscape
MARGIN = 12.7
TEXT_HEIGHT = 2.5  # mm, the capitals of a cell
TITLE_HEIGHT = 4.0
ROW = 6.0  # mm a row
PAD = 1.5  # mm each side of a cell's text
ELLIPSIS = "…"
_ZIP_DATE = (1980, 1, 1, 0, 0, 0)


def _csv_cell(text: str) -> str:
    return "'" + text if text.startswith(_FORMULA_START) else text


def csv_bytes(table: ShownTable) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    for row in table.cells():
        w.writerow([_csv_cell(c) for c in row])
    return ("﻿" + buf.getvalue()).encode("utf-8")


# --------------------------------------------------------------------------- Excel
def _col(n: int) -> str:
    """The column letters of 0-based column ``n``: A, B, ..., Z, AA."""
    out = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def _xml_text(text: str) -> str:
    # XML 1.0 has no place for most control characters; a cell never holds one but a line end
    clean = "".join(c for c in text if c in "\t\n" or ord(c) >= 32)
    return escape(clean)


def _sheet_xml(table: ShownTable) -> str:
    cells = table.cells()
    numeric = [c.numeric for c in table.columns]
    widths = [
        min(60, max(8, max((len(row[i]) for row in cells), default=8) + 2)) for i in range(len(table.columns))
    ]
    rows_xml = []
    for r, row in enumerate(cells, 1):
        parts = []
        for i, text in enumerate(row):
            ref = f"{_col(i)}{r}"
            style = ' s="1"' if r == 1 else ""
            if r > 1 and numeric[i] and text.isdigit() and len(text) < 15:
                parts.append(f'<c r="{ref}"{style}><v>{int(text)}</v></c>')
            else:
                space = ' xml:space="preserve"' if text != text.strip() else ""
                parts.append(
                    f'<c r="{ref}" t="inlineStr"{style}><is><t{space}>{_xml_text(text)}</t></is></c>'
                )
        rows_xml.append(f'<row r="{r}">{"".join(parts)}</row>')
    cols = "".join(
        f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
        'state="frozen"/></sheetView></sheetViews>'
        f"<cols>{cols}</cols><sheetData>{''.join(rows_xml)}</sheetData></worksheet>"
    )


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    '<Override PartName="/xl/styles.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
    "</Types>"
)
_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="xl/workbook.xml"/></Relationships>'
)
_WORKBOOK_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
    'Target="worksheets/sheet1.xml"/>'
    '<Relationship Id="rId2" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    "</Relationships>"
)
_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    "</styleSheet>"
)


def _sheet_name(name: str) -> str:
    clean = "".join(c for c in name if c not in "[]:*?/\\" and ord(c) >= 32).strip("'").strip()
    return (clean or "BOM")[:31]


def xlsx_bytes(table: ShownTable, sheet_name: str = "BOM") -> bytes:
    """The table as a one-sheet ``.xlsx`` workbook (module notes)."""
    name = escape(_sheet_name(sheet_name), {'"': "&quot;"})
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{name}" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    parts = [
        ("[Content_Types].xml", _CONTENT_TYPES),
        ("_rels/.rels", _ROOT_RELS),
        ("xl/workbook.xml", workbook),
        ("xl/_rels/workbook.xml.rels", _WORKBOOK_RELS),
        ("xl/styles.xml", _STYLES),
        ("xl/worksheets/sheet1.xml", _sheet_xml(table)),
    ]
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in parts:
            info = zipfile.ZipInfo(name, date_time=_ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3  # as on Unix, on every platform, so the bytes match
            info.external_attr = 0o644 << 16
            z.writestr(info, text.encode("utf-8"))
    return out.getvalue()


# --------------------------------------------------------------------------- PDF
@dataclass(frozen=True)
class PdfExport:
    data: bytes
    pages: int
    problems: tuple[str, ...]


def _shown(text: str, replaced: list[str]) -> str:
    out = []
    for ch in text:
        if ch == "\n":
            out.append(" ")
        elif fonts.winansi(ch) is None:
            replaced.append(ch)
            out.append("?")
        else:
            out.append(ch)
    return "".join(out)


def _fit(text: str, width: float, size: float, bold: bool) -> str:
    if fonts.measure(text, size, bold) <= width:
        return text
    while text and fonts.measure(text + ELLIPSIS, size, bold) > width:
        text = text[:-1]
    return text + ELLIPSIS if text else ""


def pdf_bytes(table: ShownTable, title: str, *, paper: str = "letter") -> PdfExport:
    """The table as PDF pages (module notes) under ``title``."""
    if paper not in PAPERS:
        raise InvalidArgumentError(f"paper is one of {', '.join(PAPERS)}", detail={"parameter": "paper"})
    page_w, page_h = PAPERS[paper]
    usable = page_w - 2 * MARGIN
    size = fonts.font_size(TEXT_HEIGHT)
    replaced: list[str] = []
    title_text = _shown(title, replaced)
    heads = [_shown(h, replaced) for h in table.headings()]
    body = [[_shown(c, replaced) for c in r.cells] for r in table.rows]
    natural = [
        max([fonts.measure(heads[i], size, True)] + [fonts.measure(row[i], size, False) for row in body])
        + 2 * PAD
        for i in range(len(heads))
    ]
    widths = list(natural)
    while sum(widths) > usable:  # take from the widest column until the table fits the page
        widest = max(range(len(widths)), key=lambda i: widths[i])
        widths[widest] = max(widths[widest] - (sum(widths) - usable), max(widths[widest] * 0.8, 8.0))
        if all(w <= 8.0 for w in widths):
            break
    top = page_h - MARGIN - TITLE_HEIGHT * 2
    per_page = max(1, int((top - MARGIN - 8.0) // ROW) - 1)
    chunks = [body[i : i + per_page] for i in range(0, len(body), per_page)] or [[]]
    painters = []
    for n, chunk in enumerate(chunks, 1):
        p = PdfPainter()
        p.begin_page(page_w, page_h)
        p.text(
            MARGIN,
            page_h - MARGIN - TITLE_HEIGHT,
            fonts.font_size(TITLE_HEIGHT),
            0.0,
            title_text,
            "Helvetica-Bold",
            "left",
        )
        y = top
        lines = [y]
        for row, bold in [(heads, True), *((r, False) for r in chunk)]:
            x = MARGIN
            for i, text in enumerate(row):
                shown = _fit(text, widths[i] - 2 * PAD, size, bold)
                if table.columns[i].numeric and not bold:
                    p.text(
                        x + widths[i] - PAD,
                        y - ROW + (ROW - TEXT_HEIGHT) / 2,
                        size,
                        0.0,
                        shown,
                        fonts.font_name(bold),
                        "right",
                    )
                else:
                    p.text(
                        x + PAD,
                        y - ROW + (ROW - TEXT_HEIGHT) / 2,
                        size,
                        0.0,
                        shown,
                        fonts.font_name(bold),
                        "left",
                    )
                x += widths[i]
            y -= ROW
            lines.append(y)
        right = MARGIN + sum(widths)
        for k, ly in enumerate(lines):
            p.set_stroke(
                0.35 if k in (0, 1, len(lines) - 1) else 0.13,
                (),
                0,
                0,
                0.0 if k in (0, 1, len(lines) - 1) else 0.6,
            )
            p.path([("M", MARGIN, ly), ("L", right, ly)])
            p.stroke()
        p.set_stroke(0.13, (), 0, 0, 0.6)
        x = MARGIN
        for w in widths[:-1]:
            x += w
            p.path([("M", x, lines[0]), ("L", x, lines[-1])])
            p.stroke()
        p.set_stroke(0.35, (), 0, 0, 0.0)
        for xx in (MARGIN, right):
            p.path([("M", xx, lines[0]), ("L", xx, lines[-1])])
            p.stroke()
        p.text(page_w - MARGIN, MARGIN, size, 0.0, f"Page {n} of {len(chunks)}", "Helvetica", "right")
        p.end_page()
        painters.append(p)
    out = painted_pdf(painters, title_text)
    problems = list(out.problems)
    if replaced:
        shown_chars = "".join(sorted(set(replaced)))[:20]
        problems.append(
            f"the PDF's lettering cannot show {shown_chars}, so it shows ? there; "
            "the CSV and Excel files keep them"
        )
    return PdfExport(out.data, len(painters), tuple(problems))


__all__ = ["PAPERS", "PdfExport", "csv_bytes", "pdf_bytes", "xlsx_bytes"]
