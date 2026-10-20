"""The PDF writer (``docs/DRAWINGS.md`` 12.1, 12.4, 17.2, 18).

PDF 1.7, written in pure Python, a page for each sheet: one for most drawings, and
for one whose parts list goes on to more sheets (:attr:`.display.Sheet.continuation`)
a page for each, in order. A page is its sheet: its
MediaBox is the sheet's size in points (72 to the inch, so a millimetre is
72/25.4 points) and the content is the sheet's painted layer, replayed through
:func:`.painter.paint` on a :class:`PdfPainter`, the same call the SVG
reference writer makes, so the two draw the same thing to a hundredth of a
millimetre. The content stream is compressed with FlateDecode.

- **Strokes and fills** carry the painted item's width, dash pattern, cap, join
  and grey; curves are the painter's cubic Béziers, written as they come.
- **Text** is set in the base-14 Helvetica and Helvetica-Bold with
  WinAnsiEncoding, so a reader draws it from its own copy of the font and the
  widths in :mod:`.fonts` are the widths it draws. ``size`` is the font size;
  the anchor (left, centre, right) is applied here with :func:`.fonts.measure`,
  and rotation goes through the text matrix. A character outside WinAnsi is
  refused with :class:`~solidseas.errors.InvalidArgumentError` naming it:
  symbols outside WinAnsi (every GD&T symbol, counterbore, countersink, depth)
  reach this writer only as paths drawn by layout.
- **Layers** are optional content groups: each painted layer of
  :data:`.display.LAYERS` is wrapped in ``BDC /OC ... EMC`` for its group in
  :data:`LAYER_GROUP`, the catalog lists the groups, and all are on.
- **The logo** is decoded by :func:`.images.read_png`, which takes only the
  narrow PNG of 7.1, and embedded as an image XObject with its alpha as a soft
  mask. A logo that is refused is left out and the page is still written; the
  reason is in the result's ``problems`` (:func:`to_pdf`) or the list passed to
  :func:`write_pdf`.
- **Metadata** is the producer (``SolidSeas`` and its version, which tells
  ``dwg-file`` that SolidSeas wrote the file) and the title: no path, user name
  or date. The file identifier is a hash of the file's content, so the same
  sheet writes the same bytes on one machine (12.4).
- **Nothing active**: no JavaScript, actions, forms, annotations, links,
  ``/OpenAction``, ``/AA``, ``/Launch`` or ``/URI`` is ever written. Strings are
  escaped, and a byte that is not printable ASCII is written as an octal escape
  (content) or the whole string as UTF-16 in hexadecimal (metadata).

``docs/drawings/pdf.md`` describes the writer for users of the library.
"""

from __future__ import annotations

import hashlib
import math
import unicodedata
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import IO, Any

from .. import __version__
from ..errors import InvalidArgumentError
from . import display as D
from . import fonts
from .images import PngImage, PngRefused, read_png
from .limits import DEFAULT_LIMITS, DrawingLimits
from .painter import ANCHORS, paint
from .types import Drawing

PT = 72.0 / 25.4  # points a millimetre
PRODUCER = f"SolidSeas {__version__}"
MAX_PAGE_MM = 14400.0 / PT  # ISO 32000-1's largest page without UserUnit, 200 inches
MAX_COORD_MM = 100_000.0  # anything farther from the sheet than 100 m is not a drawing
MAX_IMAGES = 8  # distinct images a page embeds; a drawing has one logo
MAX_PROBLEMS = 32

# The optional content groups of 12.1, in the order a reader's layer panel lists them.
GROUPS = ("Visible", "Hidden", "Centre lines", "Dimensions", "Notes", "Title block", "Stamp")
# Which group each painted layer is drawn in. Hidden holds every thin or broken line
# of the part that is not a centre line (hidden, tangent and phantom), so turning it
# off leaves the visible outline; hatching and the border draw with the outline.
LAYER_GROUP = {
    "visible": "Visible",
    "hidden": "Hidden",
    "tangent": "Hidden",
    "centre": "Centre lines",
    "phantom": "Hidden",
    "hatch": "Visible",
    "border": "Visible",
    "dimensions": "Dimensions",
    "notes": "Notes",
    "title": "Title block",
    "stamp": "Stamp",
}
FONT_RESOURCE = {"Helvetica": "F1", "Helvetica-Bold": "F2"}
_FONT = "<< /Type /Font /Subtype /Type1 /BaseFont /{} /Encoding /WinAnsiEncoding >>"
_PATH_ARITY = {"M": 2, "L": 2, "C": 6, "Z": 0}
_PATH_OP = {"M": "m", "L": "l", "C": "c", "Z": "h"}


def _bad(message: str, parameter: str = "sheet") -> InvalidArgumentError:
    return InvalidArgumentError(message, detail={"parameter": parameter})


def _real(value: Any, parameter: str = "sheet") -> float:
    """``value`` as a finite float, or InvalidArgumentError."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _bad(f"a {parameter} value must be a number", parameter)
    x = float(value)
    if not math.isfinite(x):
        raise _bad(f"a {parameter} value must be finite", parameter)
    return x


def _n(x: float, places: int = 3) -> str:
    """A number for the file: at most ``places`` decimals, no trailing zeros, never
    ``-0``. Points to three decimals are a third of a micrometre."""
    text = f"{x:.{places}f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "", "-") else text


def _pt(mm: float) -> str:
    return _n(mm * PT)


def _coord(value: Any) -> float:
    x = _real(value, "sheet")
    if abs(x) > MAX_COORD_MM:
        raise _bad("a sheet coordinate is more than 100 m from the sheet")
    return x


def _literal(raw: bytes) -> str:
    """A PDF literal string: parentheses and backslashes escaped, every byte that is
    not printable ASCII as a three-digit octal escape, so the content is plain ASCII."""
    out = []
    for b in raw:
        if b in (0x28, 0x29, 0x5C):
            out.append("\\" + chr(b))
        elif 0x20 <= b <= 0x7E:
            out.append(chr(b))
        else:
            out.append(f"\\{b:03o}")
    return "(" + "".join(out) + ")"


def _text_string(text: str) -> str:
    """A PDF text string for the document information: printable ASCII as an escaped
    literal, anything else as UTF-16BE with its byte order mark, in hexadecimal."""
    if all(0x20 <= ord(ch) <= 0x7E for ch in text):
        return _literal(text.encode("ascii"))
    return "<feff" + text.encode("utf-16-be").hex() + ">"


def _winansi(text: str) -> bytes:
    """``text`` in WinAnsi, or InvalidArgumentError naming the first character the
    PDF's fonts cannot show."""
    out = bytearray()
    for ch in text:
        b = fonts.winansi(ch)
        if b is None:
            shown = ch if ch.isprintable() else ascii(ch)[1:-1]
            raise InvalidArgumentError(
                f"the character {shown} (U+{ord(ch):04X}) is not in WinAnsi, the encoding of the PDF's "
                "fonts; symbols outside it are drawn as paths",
                detail={"parameter": "text", "value": f"U+{ord(ch):04X}"},
            )
        out.append(b)
    return bytes(out)


def _clean_title(text: str, limit: int) -> str:
    """A title fit for the document information: white space as single spaces, and
    control, format (bidirectional overrides among them), surrogate, private and
    unassigned characters removed; at most ``limit`` characters."""
    kept = "".join(
        " " if ch.isspace() else ch for ch in text if ch.isspace() or unicodedata.category(ch)[0] != "C"
    )
    return " ".join(kept.split())[:limit]


class PdfPainter:
    """A :class:`~.painter.Painter` that collects one page as a PDF content stream.

    Lengths come in sheet millimetres and are written in points. The graphics state
    (line width, dash, cap, join, stroke and fill grey) is written only when it
    changes, in the order the painter sets it, so the stream is the same for the
    same calls. ``problems`` lists, in words, what was left out (a refused logo, an
    unknown layer); the page is written regardless."""

    def __init__(self, *, limits: DrawingLimits = DEFAULT_LIMITS) -> None:
        if not isinstance(limits, DrawingLimits):
            raise _bad("limits must be DrawingLimits", "limits")
        self.limits = limits
        self.width = 0.0
        self.height = 0.0
        self.problems: list[str] = []
        self.groups_used: list[str] = []
        self.fonts_used: list[str] = []
        self.images: list[tuple[str, PngImage]] = []  # (resource name, image), in first use order
        self._image_names: dict[bytes, str] = {}
        self._refused: dict[bytes, str] = {}
        self._out: list[str] = []
        self._path = ""
        self._want: tuple = (0.0, (), 0, 0, 0.0)
        self._state: dict[str, Any] = {}
        self._depth = 0

    # ------------------------------------------------------------------ bookkeeping

    def _problem(self, text: str) -> None:
        if text not in self.problems and len(self.problems) < MAX_PROBLEMS:
            self.problems.append(text)

    def _set(self, key: str, value: Any, op: str) -> None:
        if self._state.get(key) != value:
            self._state[key] = value
            self._out.append(op)

    def _fill_grey(self, grey: float) -> None:
        g = _n(grey)
        self._set("g", g, f"{g} g")

    # ------------------------------------------------------------------ the protocol

    def begin_page(self, width: float, height: float) -> None:
        w, h = _real(width, "sheet"), _real(height, "sheet")
        if not (0.0 < w <= MAX_PAGE_MM and 0.0 < h <= MAX_PAGE_MM):
            raise _bad(f"a sheet must be more than 0 and at most {MAX_PAGE_MM:.0f} mm a side")
        self.width, self.height = w, h
        self._out = []
        self._state = {}
        self._depth = 0

    def set_stroke(self, width: float, dash: Sequence[float], cap: int, join: int, grey: float) -> None:
        w = _real(width, "width")
        if w < 0.0:
            raise _bad("a line width cannot be negative", "width")
        if not isinstance(dash, (tuple, list)):
            raise _bad("a dash pattern must be a sequence of lengths", "dash")
        pattern = tuple(_real(d, "dash") for d in dash)
        if any(d < 0.0 for d in pattern):
            raise _bad("a dash length cannot be negative", "dash")
        if not any(d > 0.0 for d in pattern):
            pattern = ()  # all zero is not a pattern a reader accepts; it means solid
        for value, name in ((cap, "cap"), (join, "join")):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2:
                raise _bad(f"a line {name} must be 0, 1 or 2", name)
        g = min(1.0, max(0.0, _real(grey, "grey")))
        self._want = (w, pattern, cap, join, g)

    def path(self, ops: Sequence[tuple]) -> None:
        parts = []
        for i, op in enumerate(ops):
            if not isinstance(op, tuple) or not op or op[0] not in _PATH_ARITY:
                raise _bad("a path operation must be M, L, C or Z with its coordinates")
            if len(op) != 1 + _PATH_ARITY[op[0]]:
                raise _bad(f"a path's {op[0]} operation has the wrong number of coordinates")
            if i == 0 and op[0] != "M":
                raise _bad("a path must start with a move")
            parts.append(" ".join([*(_pt(_coord(c)) for c in op[1:]), _PATH_OP[op[0]]]))
        self._path = " ".join(parts)

    def stroke(self) -> None:
        if not self._path:
            return
        w, pattern, cap, join, g = self._want
        self._set("w", _pt(w), f"{_pt(w)} w")
        dash = "[" + " ".join(_pt(d) for d in pattern) + "] 0 d"
        self._set("d", dash, dash)
        self._set("J", cap, f"{cap} J")
        self._set("j", join, f"{join} j")
        grey = _n(g)
        self._set("G", grey, f"{grey} G")
        self._out.append(self._path + " S")
        self._path = ""

    def fill(self, grey: float) -> None:
        if not self._path:
            return
        self._fill_grey(min(1.0, max(0.0, _real(grey, "grey"))))
        self._out.append(self._path + " f")
        self._path = ""

    def text(
        self, x: float, y: float, size: float, angle_deg: float, string: str, font: str, anchor: str
    ) -> None:
        if not isinstance(string, str):
            raise _bad("text must be a string", "text")
        if len(string) > self.limits.string_chars:
            raise self.limits.exceeded("string_chars", "a text run is longer than a drawing allows")
        if font not in FONT_RESOURCE:
            raise _bad("the font must be Helvetica or Helvetica-Bold", "font")
        if anchor not in ANCHORS:
            raise _bad("the anchor must be left, centre or right", "anchor")
        x, y = _coord(x), _coord(y)
        size = _real(size, "size")
        if not 0.0 < size <= MAX_PAGE_MM:
            raise _bad("a font size must be more than 0 and no larger than a sheet", "size")
        angle = _real(angle_deg, "angle_deg")
        encoded = _winansi(string)
        if not string:
            return
        width = fonts.measure(string, size, font.endswith("Bold"))
        shift = {"left": 0.0, "centre": -width / 2.0, "right": -width}[anchor]
        a = math.radians(angle % 360.0)
        ca, sa = math.cos(a), math.sin(a)
        x0, y0 = x + shift * ca, y + shift * sa
        if font not in self.fonts_used:
            self.fonts_used.append(font)
        self._fill_grey(0.0)
        self._out.append(
            f"BT /{FONT_RESOURCE[font]} {_pt(size)} Tf {_n(ca, 6)} {_n(sa, 6)} {_n(-sa, 6)} {_n(ca, 6)} "
            f"{_pt(x0)} {_pt(y0)} Tm {_literal(encoded)} Tj ET"
        )

    def image(self, x: float, y: float, width: float, height: float, data: bytes) -> None:
        x, y = _coord(x), _coord(y)
        w, h = _coord(width), _coord(height)
        if w <= 0.0 or h <= 0.0:
            self._problem("the logo was left out: its size on the sheet is not more than 0")
            return
        if not isinstance(data, (bytes, bytearray, memoryview)):
            self._problem("the logo was left out: it is not bytes")
            return
        key = hashlib.sha256(bytes(data)).digest()
        if key in self._refused:
            return
        name = self._image_names.get(key)
        if name is None:
            if len(self.images) >= MAX_IMAGES:
                self._problem(f"an image was left out: a page embeds at most {MAX_IMAGES}")
                return
            try:
                decoded = read_png(data, limits=self.limits)
            except PngRefused as exc:
                self._refused[key] = str(exc)
                self._problem(f"the logo was left out: {exc}")
                return
            name = f"Im{len(self.images) + 1}"
            self._image_names[key] = name
            self.images.append((name, decoded))
        self._out.append(f"q {_pt(w)} 0 0 {_pt(h)} {_pt(x)} {_pt(y)} cm /{name} Do Q")

    def group(self, name: str) -> None:
        group = LAYER_GROUP.get(name) if isinstance(name, str) else None
        if group is None:
            shown = ascii(name if isinstance(name, str) else type(name).__name__)[:48]
            self._problem(f"items on the unknown layer {shown} were drawn in the Visible group")
            group = "Visible"
        if group not in self.groups_used:
            self.groups_used.append(group)
        self._out.append(f"/OC /L{GROUPS.index(group)} BDC")
        self._depth += 1

    def end_group(self) -> None:
        if self._depth > 0:
            self._out.append("EMC")
            self._depth -= 1

    def end_page(self) -> None:
        while self._depth > 0:
            self.end_group()

    # ------------------------------------------------------------------ results

    def content(self) -> bytes:
        """The page's content stream, uncompressed."""
        return ("\n".join(self._out) + "\n").encode("ascii")


@dataclass(frozen=True)
class PdfOutput:
    """A written PDF: its bytes, and in words what was left out of it (a refused logo,
    an unknown layer). An empty ``problems`` means the page is everything the sheet
    painted."""

    data: bytes
    problems: tuple[str, ...] = ()


class _Objects:
    """Numbered indirect objects, written in number order."""

    def __init__(self) -> None:
        self.bodies: list[bytes | None] = []

    def reserve(self) -> int:
        self.bodies.append(None)
        return len(self.bodies)

    def put(self, num: int, body: bytes) -> int:
        self.bodies[num - 1] = body
        return num

    def add(self, body: bytes) -> int:
        return self.put(self.reserve(), body)


def _stream(entries: str, data: bytes) -> bytes:
    packed = zlib.compress(data, 9)
    head = f"<< {entries}{' ' if entries else ''}/Filter /FlateDecode /Length {len(packed)} >>\nstream\n"
    return head.encode("ascii") + packed + b"\nendstream"


def _sheet_of(item: Any) -> tuple[D.Sheet, Drawing | None]:
    if isinstance(item, D.Sheet):
        return item, None
    if isinstance(item, Drawing):
        if not isinstance(item.sheet, D.Sheet):
            raise _bad("the drawing has no laid-out sheet to write", "drawing")
        return item.sheet, item
    raise _bad("write_pdf takes a Drawing or a display.Sheet", "drawing")


def _title_of(sheet: D.Sheet, drawing: Drawing | None) -> str:
    """The title the title block shows: the sheet's title block field ``title``, else
    the drawing's title field of that name."""
    for item in sheet.annotations:
        if isinstance(item, D.TitleBlock):
            for key, value in item.fields:
                if key == "title" and isinstance(value, str):
                    return value
    if drawing is not None:
        for key, value in drawing.title:
            text = getattr(value, "text", value)
            if key == "title" and isinstance(text, str):
                return text
    return ""


def to_pdf(
    drawing_or_sheet: Any, *, title: str | None = None, limits: DrawingLimits = DEFAULT_LIMITS
) -> PdfOutput:
    """The sheet of a :class:`~.types.Drawing`, or a :class:`~.display.Sheet`, as the
    bytes of a PDF with what was left out in words: one page, or a page for each sheet
    of a drawing that has several, in order. ``title`` replaces the
    title block's title in the document information. The file is at most
    ``limits.output_bytes``; a larger one raises ``SldLimitError``."""
    if not isinstance(limits, DrawingLimits):
        raise _bad("limits must be DrawingLimits", "limits")
    sheet, drawing = _sheet_of(drawing_or_sheet)
    if title is not None:
        if not isinstance(title, str):
            raise _bad("the title must be a string", "title")
        if len(title) > limits.title_chars:
            raise limits.exceeded("title_chars", "the title is longer than a drawing's title may be")
    shown_title = _clean_title(_title_of(sheet, drawing) if title is None else title, limits.title_chars)

    painters = []
    for page in D.sheets_of(sheet):  # a page for each sheet, the first first
        painter = PdfPainter(limits=limits)
        paint(page, painter)
        painters.append(painter)
    return painted_pdf(painters, shown_title, limits=limits)


def painted_pdf(
    painters: PdfPainter | Sequence[PdfPainter], title: str, *, limits: DrawingLimits = DEFAULT_LIMITS
) -> PdfOutput:
    """The pages ``painters`` hold (each after ``end_page``), in order, as the bytes of a
    PDF whose document information has ``title``: what :func:`to_pdf` writes for a
    sheet, and what a table painted outside a drawing (a BOM) is written with. One
    painter gives exactly the file :func:`to_pdf` always wrote."""
    pages_painted = [painters] if isinstance(painters, PdfPainter) else list(painters)
    if not pages_painted or not all(isinstance(p, PdfPainter) for p in pages_painted):
        raise _bad("painted_pdf takes one PdfPainter or a sequence of them", "painters")
    shown_title = _clean_title(title, limits.title_chars)

    objs = _Objects()
    catalog, pages = objs.reserve(), objs.reserve()
    page_refs = [objs.reserve() for _ in pages_painted]
    contents = [objs.add(_stream("", p.content())) for p in pages_painted]
    used_fonts = [font for font in FONT_RESOURCE if any(font in p.fonts_used for p in pages_painted)]
    font_refs = {font: objs.add(_FONT.format(font).encode("ascii")) for font in used_fonts}
    used = [g for g in GROUPS if any(g in p.groups_used for p in pages_painted)]
    ocg_refs = {g: objs.add(f"<< /Type /OCG /Name {_literal(g.encode('ascii'))} >>".encode()) for g in used}
    image_refs: list[dict[str, int]] = []
    for painter in pages_painted:
        refs_here = {}
        for name, img in painter.images:
            common = (
                f"/Type /XObject /Subtype /Image /Width {img.width} /Height {img.height} /BitsPerComponent 8"
            )
            smask = ""
            if img.alpha is not None:
                mask = objs.add(_stream(f"{common} /ColorSpace /DeviceGray", img.alpha))
                smask = f" /SMask {mask} 0 R"
            refs_here[name] = objs.add(_stream(f"{common} /ColorSpace /DeviceRGB{smask}", img.rgb))
        image_refs.append(refs_here)
    info_entries = f"/Producer {_text_string(PRODUCER)}"
    if shown_title:
        info_entries += f" /Title {_text_string(shown_title)}"
    info = objs.add(f"<< {info_entries} >>".encode("ascii"))

    for painter, page, content, images in zip(pages_painted, page_refs, contents, image_refs, strict=True):
        resources = []
        if font_refs:
            resources.append(
                "/Font << " + " ".join(f"/{FONT_RESOURCE[f]} {n} 0 R" for f, n in font_refs.items()) + " >>"
            )
        if images:
            resources.append("/XObject << " + " ".join(f"/{k} {n} 0 R" for k, n in images.items()) + " >>")
        if ocg_refs:
            resources.append(
                "/Properties << "
                + " ".join(f"/L{GROUPS.index(g)} {n} 0 R" for g, n in ocg_refs.items())
                + " >>"
            )
        media = f"[0 0 {_pt(painter.width)} {_pt(painter.height)}]"
        objs.put(
            page,
            (
                f"<< /Type /Page /Parent {pages} 0 R /MediaBox {media} "
                f"/Resources << {' '.join(resources)} >> /Contents {content} 0 R >>"
            ).encode("ascii"),
        )
    kids = " ".join(f"{n} 0 R" for n in page_refs)
    objs.put(pages, f"<< /Type /Pages /Kids [{kids}] /Count {len(page_refs)} >>".encode("ascii"))
    refs = " ".join(f"{n} 0 R" for n in ocg_refs.values())
    oc = f" /OCProperties << /OCGs [{refs}] /D << /Order [{refs}] /ON [{refs}] /BaseState /ON >> >>"
    # Print at the sheet's own size: a drawing scaled to fit the paper measures wrong.
    prefs = " /ViewerPreferences << /PrintScaling /None >>"
    objs.put(
        catalog,
        f"<< /Type /Catalog /Pages {pages} 0 R{oc if ocg_refs else ''}{prefs} >>".encode("ascii"),
    )

    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for num, body in enumerate(objs.bodies, 1):
        offsets.append(len(out))
        out += f"{num} 0 obj\n".encode("ascii") + (body or b"null") + b"\nendobj\n"
    # The identifier is a hash of everything above, so the same sheet gets the same one.
    file_id = hashlib.sha256(bytes(out)).hexdigest()[:32]
    xref = len(out)
    out += f"xref\n0 {len(objs.bodies) + 1}\n0000000000 65535 f \n".encode("ascii")
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(objs.bodies) + 1} /Root {catalog} 0 R /Info {info} 0 R "
        f"/ID [<{file_id}> <{file_id}>] >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode("ascii")
    if len(out) > limits.output_bytes:
        raise limits.exceeded("output_bytes", "the PDF would be larger than a drawing's output may be")
    return PdfOutput(bytes(out), tuple(p for painter in pages_painted for p in painter.problems))


def write_pdf(
    drawing_or_sheet: Any,
    fh: IO[bytes],
    *,
    title: str | None = None,
    limits: DrawingLimits = DEFAULT_LIMITS,
    problems: list[str] | None = None,
) -> int:
    """Write the sheet of a :class:`~.types.Drawing`, or a :class:`~.display.Sheet`,
    as a PDF of a page for each of its sheets (one for a drawing of one sheet) to the
    binary file object ``fh``; returns the bytes written.

    Nothing is written unless the whole file is made: a sheet the writer refuses
    (text outside WinAnsi, a value that is not finite) raises
    ``InvalidArgumentError``, and a file over ``limits.output_bytes`` raises
    ``SldLimitError``. A logo outside the narrow PNG form is left out and the page
    written; when ``problems`` is a list, the reasons are appended to it."""
    if not callable(getattr(fh, "write", None)):
        raise _bad("fh must be a binary file object", "fh")
    if problems is not None and not isinstance(problems, list):
        raise _bad("problems must be a list", "problems")
    result = to_pdf(drawing_or_sheet, title=title, limits=limits)
    view = memoryview(result.data)
    done = 0
    while done < len(view):
        n = fh.write(view[done:])
        done = len(view) if n is None else done + n
        if n == 0:
            raise OSError("the file object accepted no more bytes")
    if problems is not None:
        problems.extend(result.problems)
    return len(result.data)


__all__ = [
    "FONT_RESOURCE",
    "GROUPS",
    "LAYER_GROUP",
    "PRODUCER",
    "PT",
    "PdfOutput",
    "PdfPainter",
    "painted_pdf",
    "to_pdf",
    "write_pdf",
]
