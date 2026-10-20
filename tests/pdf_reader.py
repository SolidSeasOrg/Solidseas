"""A small PDF reader for the tests of the PDF writer (docs/DRAWINGS.md 19.2, dwg-pdf).

Test code only, written from ISO 32000-1 rather than from the writer, so the tests
read what the writer wrote the way a PDF reader would: the header, the xref table
(each offset checked against the object it points at), the trailer, the indirect
objects (dictionaries, arrays, names, strings, numbers, references, streams), the
FlateDecode filter, and a content stream as operators with their operands.
:class:`PdfDocument` then lists the page's text runs, paths, optional content
groups and images, and the document information.

It reads classic cross-reference tables only (no xref streams, object streams or
incremental updates) and refuses anything else, which is what a one-page file from
the writer must be.
"""

from __future__ import annotations

import math
import re
import zlib
from dataclasses import dataclass, field
from typing import Any, NamedTuple

WHITESPACE = b"\x00\t\n\x0c\r "
DELIMITERS = b"()<>[]{}/%"
_NUMBER = re.compile(rb"[+-]?(?:\d+\.?\d*|\.\d+)")
PT = 72.0 / 25.4


class PdfError(Exception):
    """The file is not one this reader takes."""


class Name(str):
    """A PDF name, without its slash."""

    def __repr__(self) -> str:
        return "/" + str(self)


class Op(str):
    """A bare keyword: a content stream operator, or ``obj``, ``R``, ``stream`` and the like."""


class Ref(NamedTuple):
    num: int
    gen: int


@dataclass
class Stream:
    dict: dict
    raw: bytes

    def data(self) -> bytes:
        """The stream's bytes with its filters undone (FlateDecode only)."""
        filters = self.dict.get("Filter")
        if filters is None:
            return self.raw
        names = filters if isinstance(filters, list) else [filters]
        out = self.raw
        for f in names:
            if f != "FlateDecode":
                raise PdfError(f"the reader does not undo the {f} filter")
            out = zlib.decompress(out)
        return out


class Lexer:
    """Tokens of PDF syntax from ``data`` starting at ``pos``."""

    def __init__(self, data: bytes, pos: int = 0) -> None:
        self.data = data
        self.pos = pos

    def skip(self) -> None:
        d = self.data
        while self.pos < len(d):
            c = d[self.pos]
            if c in WHITESPACE:
                self.pos += 1
            elif c == 0x25:  # % comment to the end of the line
                while self.pos < len(d) and d[self.pos] not in b"\r\n":
                    self.pos += 1
            else:
                return

    def token(self) -> Any:
        """The next token: a number, Name, bytes (a string), an Op, or one of the
        delimiters ``[``, ``]``, ``<<``, ``>>`` as an Op; None at the end."""
        self.skip()
        d = self.data
        if self.pos >= len(d):
            return None
        c = d[self.pos : self.pos + 1]
        if c == b"(":
            return self._literal()
        if c == b"<":
            if d[self.pos : self.pos + 2] == b"<<":
                self.pos += 2
                return Op("<<")
            return self._hex()
        if c == b">":
            if d[self.pos : self.pos + 2] != b">>":
                raise PdfError(f"a lone > at {self.pos}")
            self.pos += 2
            return Op(">>")
        if c in (b"[", b"]", b"{", b"}"):
            self.pos += 1
            return Op(c.decode())
        if c == b"/":
            self.pos += 1
            start = self.pos
            while self.pos < len(d) and d[self.pos] not in WHITESPACE and d[self.pos] not in DELIMITERS:
                self.pos += 1
            raw = re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), d[start : self.pos])
            return Name(raw.decode("latin-1"))
        start = self.pos
        while self.pos < len(d) and d[self.pos] not in WHITESPACE and d[self.pos] not in DELIMITERS:
            self.pos += 1
        word = d[start : self.pos]
        if not word:
            raise PdfError(f"an unexpected {c!r} at {start}")
        if _NUMBER.fullmatch(word):
            return float(word) if b"." in word else int(word)
        return Op(word.decode("latin-1"))

    def _literal(self) -> bytes:
        d = self.data
        self.pos += 1
        depth = 1
        out = bytearray()
        escapes = {ord("n"): b"\n", ord("r"): b"\r", ord("t"): b"\t", ord("b"): b"\b", ord("f"): b"\f"}
        while True:
            if self.pos >= len(d):
                raise PdfError("a string runs past the end")
            c = d[self.pos]
            self.pos += 1
            if c == 0x5C:  # backslash
                e = d[self.pos]
                self.pos += 1
                if e in escapes:
                    out += escapes[e]
                elif e in b"()\\":
                    out.append(e)
                elif 0x30 <= e <= 0x37:
                    digits = bytes([e])
                    while len(digits) < 3 and 0x30 <= d[self.pos] <= 0x37:
                        digits += d[self.pos : self.pos + 1]
                        self.pos += 1
                    out.append(int(digits, 8) & 0xFF)
                elif e == 0x0D:  # a line continuation
                    if d[self.pos] == 0x0A:
                        self.pos += 1
                elif e == 0x0A:
                    pass
                else:
                    out.append(e)
            elif c == 0x28:
                depth += 1
                out.append(c)
            elif c == 0x29:
                depth -= 1
                if depth == 0:
                    return bytes(out)
                out.append(c)
            elif c == 0x0D:  # an end of line in a string reads as a line feed
                if d[self.pos] == 0x0A:
                    self.pos += 1
                out.append(0x0A)
            else:
                out.append(c)

    def _hex(self) -> bytes:
        end = self.data.index(b">", self.pos)
        digits = re.sub(rb"[\x00\t\n\x0c\r ]", b"", self.data[self.pos + 1 : end])
        if not re.fullmatch(rb"[0-9A-Fa-f]*", digits):
            raise PdfError("a hexadecimal string holds something else")
        if len(digits) % 2:
            digits += b"0"
        self.pos = end + 1
        return bytes.fromhex(digits.decode("ascii"))


def parse_object(lex: Lexer, tok: Any = None) -> Any:
    """One object, references (``n g R``) folded in."""
    tok = lex.token() if tok is None else tok
    if tok is None:
        raise PdfError("an object was expected")
    if isinstance(tok, Op):
        if tok == "<<":
            out: dict = {}
            while True:
                key = lex.token()
                if key == ">>":
                    return out
                if not isinstance(key, Name):
                    raise PdfError(f"a dictionary key is not a name: {key!r}")
                if key in out:
                    raise PdfError(f"the dictionary repeats the key /{key}")
                out[key] = parse_object(lex)
        if tok == "[":
            items = []
            while True:
                t = lex.token()
                if t == "]":
                    return items
                items.append(parse_object(lex, t))
        if tok == "true":
            return True
        if tok == "false":
            return False
        if tok == "null":
            return None
        raise PdfError(f"an unexpected keyword {tok!r}")
    if isinstance(tok, int):
        save = lex.pos
        gen = lex.token()
        if isinstance(gen, int) and not isinstance(gen, bool):
            r = lex.token()
            if r == "R":
                return Ref(tok, gen)
        lex.pos = save
    return tok


@dataclass
class Path:
    """A painted path: its operations in points (``m``, ``l``, ``c``, ``h``), how it
    was painted (``S``, ``f``, ...), the graphics state then, and the optional content
    group it was in."""

    ops: list[tuple]
    paint: str
    width: float
    dash: list[float]
    cap: int
    join: int
    stroke_grey: float
    fill_grey: float
    group: str | None

    def mm(self) -> list[float]:
        """Every coordinate in millimetres, in order."""
        return [v / PT for op in self.ops for v in op[1:]]


@dataclass
class TextRun:
    font: str
    size: float  # points
    matrix: tuple[float, ...]  # the text matrix: a b c d e f
    text: str
    group: str | None
    fill_grey: float


@dataclass
class Placed:
    """An image drawn on the page: its resource name, the matrix it was drawn with,
    and the image XObject."""

    name: str
    matrix: tuple[float, ...]
    xobject: Stream
    group: str | None


@dataclass
class PdfDocument:
    data: bytes
    version: str = ""
    xref: dict[int, int] = field(default_factory=dict)
    trailer: dict = field(default_factory=dict)
    objects: dict[int, Any] = field(default_factory=dict)
    startxref: int = 0
    page_index: int | None = None  # the page read, from 0; None: the file must have one

    def __post_init__(self) -> None:
        d = self.data
        m = re.match(rb"%PDF-(\d\.\d)\r?\n", d)
        if not m:
            raise PdfError("no PDF header")
        self.version = m.group(1).decode()
        tail = d[-64:]
        m = re.search(rb"startxref\s+(\d+)\s+%%EOF\s*$", tail)
        if not m:
            raise PdfError("no startxref at the end")
        self.startxref = int(m.group(1))
        lex = Lexer(d, self.startxref)
        if lex.token() != "xref":
            raise PdfError("startxref does not point at an xref table")
        while True:
            first = lex.token()
            if first == "trailer":
                break
            count = lex.token()
            if not isinstance(first, int) or not isinstance(count, int):
                raise PdfError("a bad xref subsection")
            lex.skip()
            for k in range(count):
                entry = d[lex.pos : lex.pos + 20]
                if not re.fullmatch(rb"\d{10} \d{5} [nf](?: \r| \n|\r\n)", entry):
                    raise PdfError(f"a bad xref entry {entry!r}")
                if entry[17:18] == b"n":
                    self.xref[first + k] = int(entry[:10])
                lex.pos += 20
        self.trailer = parse_object(lex)
        if not isinstance(self.trailer, dict):
            raise PdfError("the trailer is not a dictionary")
        for num, off in sorted(self.xref.items()):
            self.objects[num] = self._read_object(num, off)

    def _read_object(self, num: int, off: int) -> Any:
        lex = Lexer(self.data, off)
        head = (lex.token(), lex.token(), lex.token())
        if head != (num, 0, "obj"):
            raise PdfError(f"the xref offset {off} of object {num} points at {head!r}")
        obj = parse_object(lex)
        save = lex.pos
        tok = lex.token()
        if tok == "stream":
            d = self.data
            if d[lex.pos : lex.pos + 2] == b"\r\n":
                lex.pos += 2
            elif d[lex.pos : lex.pos + 1] == b"\n":
                lex.pos += 1
            else:
                raise PdfError("stream is not followed by an end of line")
            length = obj["Length"]
            if isinstance(length, Ref):  # an indirect length, read where the xref says
                length = self._read_object(length.num, self.xref[length.num])
            if not isinstance(length, int) or length < 0:
                raise PdfError(f"the stream of object {num} has no usable /Length")
            raw = d[lex.pos : lex.pos + length]
            lex.pos += length
            if lex.token() != "endstream":
                raise PdfError(f"the stream of object {num} is not its /Length long")
            obj = Stream(obj, raw)
        else:
            lex.pos = save
        if lex.token() != "endobj":
            raise PdfError(f"object {num} has no endobj")
        return obj

    # ------------------------------------------------------------------ navigation

    def resolve(self, obj: Any) -> Any:
        for _ in range(32):
            if not isinstance(obj, Ref):
                return obj
            obj = self.objects.get(obj.num)
        raise PdfError("a reference loop")

    def get(self, d: Any, key: str, default: Any = None) -> Any:
        d = self.resolve(d)
        if isinstance(d, Stream):
            d = d.dict
        return self.resolve(d.get(key, default)) if isinstance(d, dict) else default

    @property
    def catalog(self) -> dict:
        return self.resolve(self.trailer["Root"])

    @property
    def page_count(self) -> int:
        return len(self.get(self.get(self.catalog, "Pages"), "Kids"))

    @property
    def page(self) -> dict:
        kids = self.get(self.get(self.catalog, "Pages"), "Kids")
        if self.page_index is not None:
            return self.resolve(kids[self.page_index])
        if len(kids) != 1:
            raise PdfError("the reader takes one page unless it is given page_index")
        return self.resolve(kids[0])

    def resources(self, kind: str) -> dict:
        return self.get(self.get(self.page, "Resources", {}), kind, {}) or {}

    def media_box(self) -> list[float]:
        return [float(v) for v in self.get(self.page, "MediaBox")]

    def content(self) -> bytes:
        contents = self.get(self.page, "Contents")
        parts = contents if isinstance(contents, list) else [contents]
        return b"\n".join(self.resolve(p).data() for p in parts)

    def info(self) -> dict[str, Any]:
        """The document information, strings decoded (UTF-16 with its mark, else
        PDFDocEncoding, read here as Latin-1)."""
        raw = self.resolve(self.trailer.get("Info")) or {}
        return {k: decode_text(v) if isinstance(v, bytes) else v for k, v in raw.items()}

    def ocg_names(self) -> list[str]:
        props = self.get(self.catalog, "OCProperties")
        if not props:
            return []
        return [decode_text(self.get(ref, "Name")) for ref in self.get(props, "OCGs")]

    def walk(self):
        """Every object in the file, depth first, with dictionaries' keys: what the
        tests search for anything active."""
        stack = list(self.objects.values()) + [self.trailer]
        seen = 0
        while stack:
            seen += 1
            if seen > 100_000:
                raise PdfError("too many objects to walk")
            obj = stack.pop()
            yield obj
            if isinstance(obj, Stream):
                stack.append(obj.dict)
            elif isinstance(obj, dict):
                stack.extend(obj.keys())
                stack.extend(obj.values())
            elif isinstance(obj, list):
                stack.extend(obj)

    # ------------------------------------------------------------------ the content

    def operations(self) -> list[tuple[str, list]]:
        return operations(self.content())

    def painted(self) -> tuple[list[Path], list[TextRun], list[Placed]]:
        """The page replayed: its paths, text runs and images in drawing order."""
        props = self.resources("Properties")
        fonts = self.resources("Font")
        xobjects = self.resources("XObject")
        paths: list[Path] = []
        runs: list[TextRun] = []
        placed: list[Placed] = []
        gs = {"w": 1.0, "d": [], "J": 0, "j": 0, "G": 0.0, "g": 0.0, "cm": (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)}
        saved: list[dict] = []
        groups: list[str | None] = []
        current: list[tuple] = []
        font = size = None
        tm: tuple[float, ...] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        in_text = False
        for op, args in self.operations():
            group = next((g for g in reversed(groups) if g is not None), None)
            if op == "q":
                saved.append(dict(gs))
            elif op == "Q":
                gs = saved.pop()
            elif op == "cm":
                gs["cm"] = _concat(tuple(float(a) for a in args), gs["cm"])
            elif op == "w":
                gs["w"] = float(args[0])
            elif op == "d":
                gs["d"] = [float(a) for a in args[0]]
                if args[1] != 0:
                    raise PdfError("the reader expects a dash phase of 0")
            elif op in ("J", "j"):
                gs[op] = int(args[0])
            elif op in ("G", "g"):
                gs[op] = float(args[0])
            elif op in ("m", "l", "c"):
                current.append((op, *(float(a) for a in args)))
            elif op == "h":
                current.append(("h",))
            elif op == "re":
                x, y, w, h = (float(a) for a in args)
                current += [("m", x, y), ("l", x + w, y), ("l", x + w, y + h), ("l", x, y + h), ("h",)]
            elif op in ("S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "n"):
                if op != "n":
                    paths.append(
                        Path(current, op, gs["w"], gs["d"], gs["J"], gs["j"], gs["G"], gs["g"], group)
                    )
                current = []
            elif op == "BDC":
                tag, prop = args
                if tag == "OC":
                    ocg = props.get(prop) if isinstance(prop, Name) else prop
                    groups.append(decode_text(self.get(ocg, "Name")))
                else:
                    groups.append(None)
            elif op == "BMC":
                groups.append(None)
            elif op == "EMC":
                if not groups:
                    raise PdfError("an EMC without its BDC")
                groups.pop()
            elif op == "BT":
                if in_text:
                    raise PdfError("BT inside BT")
                in_text, tm = True, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
            elif op == "ET":
                in_text = False
            elif op == "Tf":
                font = decode_text(self.get(fonts.get(args[0]), "BaseFont"))
                size = float(args[1])
            elif op == "Tm":
                tm = tuple(float(a) for a in args)
            elif op == "Td":
                tm = (*tm[:4], tm[4] + float(args[0]), tm[5] + float(args[1]))
            elif op == "Tj":
                if not in_text:
                    raise PdfError("Tj outside BT")
                runs.append(TextRun(font, size, tm, bytes(args[0]).decode("cp1252"), group, gs["g"]))
            elif op == "Do":
                placed.append(Placed(args[0], gs["cm"], self.resolve(xobjects.get(args[0])), group))
            elif op in ("BI", "ID", "EI"):
                raise PdfError("the reader does not take inline images")
        if groups or saved or in_text:
            raise PdfError("the content leaves a group, a saved state or a text object open")
        return paths, runs, placed

    def paths(self) -> list[Path]:
        return self.painted()[0]

    def text_runs(self) -> list[TextRun]:
        return self.painted()[1]

    def images(self) -> list[Placed]:
        return self.painted()[2]


def _concat(m: tuple[float, ...], n: tuple[float, ...]) -> tuple[float, ...]:
    """The matrix m then n (PDF's ``cm`` order)."""
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (a * A + b * C, a * B + b * D, c * A + d * C, c * B + d * D, e * A + f * C + E, e * B + f * D + F)


def operations(content: bytes) -> list[tuple[str, list]]:
    """A content stream as ``(operator, operands)`` in order."""
    lex = Lexer(content)
    out: list[tuple[str, list]] = []
    operands: list = []
    while True:
        tok = lex.token()
        if tok is None:
            break
        if isinstance(tok, Op) and tok not in ("[", "<<", "true", "false", "null"):
            if tok in ("]", ">>"):
                raise PdfError(f"an unbalanced {tok}")
            out.append((str(tok), operands))
            operands = []
        else:
            operands.append(parse_object(lex, tok))
    if operands:
        raise PdfError("operands without an operator at the end")
    return out


def decode_text(value: Any) -> str:
    """A PDF text string as str."""
    if isinstance(value, Name):
        return str(value)
    if not isinstance(value, bytes):
        raise PdfError(f"not a string: {value!r}")
    if value[:2] == b"\xfe\xff":
        return value[2:].decode("utf-16-be")
    return value.decode("latin-1")


def matrix_angle(m: tuple[float, ...]) -> float:
    """The rotation of a text matrix in degrees, counter-clockwise."""
    return math.degrees(math.atan2(m[1], m[0]))


__all__ = [
    "PT",
    "Lexer",
    "Name",
    "Op",
    "Path",
    "PdfDocument",
    "PdfError",
    "Placed",
    "Ref",
    "Stream",
    "TextRun",
    "decode_text",
    "matrix_angle",
    "operations",
    "parse_object",
]
