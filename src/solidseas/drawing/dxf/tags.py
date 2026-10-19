"""Group codes, numbers and strings of an ASCII DXF (``docs/DRAWINGS.md`` 12.2, 17.2).

A DXF is pairs of lines: a group code, then its value. :class:`TagWriter` writes
them with the code right-aligned in three columns, as AutoCAD does, and every
line ends in CRLF (the file is meant for Windows programs; every reader takes
either ending, and one file never mixes them). Numbers are written in fixed
point without an exponent, ``-0`` never appears, and a value that is not finite
is refused, so the same sheet always gives the same bytes. The writer counts
what it writes and stops at the drawing's ``output_bytes`` bound.

Strings reach a tag only through :func:`clean` (or a fixed ASCII name of ours):
control characters are removed, a caret is written ``^ `` (the DXF form of a
literal caret, so ``^J`` in a title cannot become a line break), MTEXT codes are
escaped (``\\``, ``{``, ``}``), Ø, ± and ° become ``%%c``, ``%%p`` and ``%%d``,
a typed ``%%`` is kept literal, and every other character outside ASCII is
written ``\\U+XXXX``. The symbols the CAD fonts lack (counterbore, countersink,
depth) become CBORE, CSK and DEEP when the caller asks for words.
"""

from __future__ import annotations

import math

from ...errors import InvalidArgumentError
from ..limits import DrawingLimits
from ..standards import SYMBOL_WORDS

NEWLINE = "\r\n"
MAX_TEXT = 250  # characters of one string value (R2000 takes 255)

# Characters a CAD font draws from a percent code.
PERCENT_CODES = {"Ø": "%%c", "⌀": "%%c", "±": "%%p", "°": "%%d"}


def num(x: float, places: int = 10) -> str:
    """A finite number in fixed point with at most ``places`` decimals, at least one
    decimal and never ``-0.0``."""
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise InvalidArgumentError("a DXF number must be finite", detail={"parameter": "sheet"})
    text = f"{float(x):.{places}f}".rstrip("0")
    if text.endswith("."):
        text += "0"
    return "0.0" if text == "-0.0" else text


def _control(cp: int) -> bool:
    return cp < 0x20 or 0x7F <= cp < 0xA0 or cp in (0x2028, 0x2029, 0xFEFF) or 0xD800 <= cp <= 0xDFFF


def clean_tokens(text: str, *, mtext: bool = False, words: bool = False, limit: int = 4096) -> list[str]:
    """``text`` as DXF string pieces, one a source character, so a long string can be
    cut or split into chunks without breaking an escape. ``limit`` bounds the source
    characters read."""
    if not isinstance(text, str):
        raise InvalidArgumentError("a drawing string must be text", detail={"parameter": "sheet"})
    text = text[:limit]
    literal_percent = "%%" in text
    out: list[str] = []
    for ch in text:
        cp = ord(ch)
        if _control(cp):
            continue
        if words and ch in SYMBOL_WORDS:
            out.append(SYMBOL_WORDS[ch])
        elif ch in PERCENT_CODES:
            out.append(PERCENT_CODES[ch])
        elif ch == "%":
            out.append("%%%" if literal_percent else "%")
        elif ch == "^":
            out.append("^ ")
        elif ch == "\\":
            out.append("\\\\" if mtext else "\\U+005C")
        elif mtext and ch in "{}":
            out.append("\\" + ch)
        elif cp > 0x7E:
            out.append(f"\\U+{cp:04X}" if cp <= 0xFFFF else "?")
        else:
            out.append(ch)
    return out


def clean(text: str, *, mtext: bool = False, words: bool = False, limit: int = 4096, cut: int = 0) -> str:
    """``text`` cleaned for a DXF string (see the module). ``cut`` keeps whole pieces
    up to that many characters (0: no cut)."""
    tokens = clean_tokens(text, mtext=mtext, words=words, limit=limit)
    if not cut:
        return "".join(tokens)
    out, size = [], 0
    for tok in tokens:
        if size + len(tok) > cut:
            break
        out.append(tok)
        size += len(tok)
    return "".join(out)


def chunks(tokens: list[str], size: int = MAX_TEXT) -> list[str]:
    """MTEXT pieces (from :func:`clean_tokens`) packed into strings of at most ``size``
    characters, never splitting an escape; the last string goes in group 1, the
    others in group 3."""
    out: list[str] = []
    current: list[str] = []
    length = 0
    for tok in tokens:
        if current and length + len(tok) > size:
            out.append("".join(current))
            current, length = [], 0
        current.append(tok)
        length += len(tok)
    out.append("".join(current))
    return out


def _plain(value: str) -> str:
    """A string that did not come through :func:`clean` (our own names), made safe."""
    if value.isascii() and not any(_control(ord(c)) for c in value):
        return value
    return clean(value)


class TagWriter:
    """Collects tags as text and counts the bytes against ``limits.output_bytes``; the
    count is shared with the other writers of one file through ``counter``."""

    def __init__(self, limits: DrawingLimits, counter: list[int] | None = None) -> None:
        self.limits = limits
        self.counter = counter if counter is not None else [0]
        self.parts: list[str] = []

    def tag(self, code: int, value) -> None:
        if isinstance(value, bool):
            text = str(int(value))
        elif isinstance(value, int):
            text = str(value)
        elif isinstance(value, float):
            text = num(value)
        else:
            text = _plain(str(value))
        line = f"{code:>3}{NEWLINE}{text}{NEWLINE}"
        self.counter[0] += len(line)
        if self.counter[0] > self.limits.output_bytes:
            raise self.limits.exceeded(
                "output_bytes", "the DXF would be larger than a drawing's output may be"
            )
        self.parts.append(line)

    def tags(self, pairs) -> None:
        for code, value in pairs:
            self.tag(code, value)

    def point(self, code: int, p, z: bool = True) -> None:
        """A point as codes ``code``, ``code + 10`` and (when ``z``) ``code + 20``."""
        self.tag(code, float(p[0]))
        self.tag(code + 10, float(p[1]))
        if z:
            self.tag(code + 20, 0.0)

    def text(self) -> str:
        return "".join(self.parts)


__all__ = ["MAX_TEXT", "NEWLINE", "PERCENT_CODES", "TagWriter", "chunks", "clean", "clean_tokens", "num"]
