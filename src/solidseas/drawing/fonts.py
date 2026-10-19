"""Text widths for the drawing's one typeface, Helvetica and Helvetica-Bold, in the
WinAnsi character set (``docs/DRAWINGS.md`` 5, 12.1).

The PDF writer uses the base-14 fonts, so a PDF reader draws them from its own
copy and every writer, the SVG one included, must measure text exactly as the
reader will draw it. The advance widths below are those of Adobe's Core 14 AFM
files, in thousandths of the font size, transcribed for WinAnsi only and without
kerning (the writers apply none). The AFM files' notice is in ``NOTICE``
(APAFML), as their terms ask; the transcription is ours, so ``docs/drawings/
REVIEW.md`` lists a check of every width against the files themselves.

Drafting gives a text height as the height of a capital letter, and the AFM's
cap height is 718 thousandths of the font size, so :func:`font_size` turns a
3 mm text height into a 4.18 mm font size. Typed text outside WinAnsi is refused
where it is typed (:func:`unsupported`); symbols outside it (the GD&T ones, the
counterbore, countersink and depth symbols) are drawn as paths and never reach
this module.
"""

from __future__ import annotations

from ..errors import InvalidArgumentError

FONTS = ("Helvetica", "Helvetica-Bold")
CAP_HEIGHT = 0.718  # of the font size, both weights
X_HEIGHT = {"Helvetica": 0.523, "Helvetica-Bold": 0.532}
ASCENT = 0.718
DESCENT = -0.207

# Code points of WinAnsi above 0x7F that are not Latin-1 (0x80 to 0x9F), as Unicode.
_WIN_HIGH = {
    0x20AC: 0x80, 0x201A: 0x82, 0x0192: 0x83, 0x201E: 0x84, 0x2026: 0x85, 0x2020: 0x86,
    0x2021: 0x87, 0x02C6: 0x88, 0x2030: 0x89, 0x0160: 0x8A, 0x2039: 0x8B, 0x0152: 0x8C,
    0x017D: 0x8E, 0x2018: 0x91, 0x2019: 0x92, 0x201C: 0x93, 0x201D: 0x94, 0x2022: 0x95,
    0x2013: 0x96, 0x2014: 0x97, 0x02DC: 0x98, 0x2122: 0x99, 0x0161: 0x9A, 0x203A: 0x9B,
    0x0153: 0x9C, 0x017E: 0x9E, 0x0178: 0x9F,
}  # fmt: skip


def winansi(ch: str) -> int | None:
    """The WinAnsi byte of a character, or None when WinAnsi has none."""
    cp = ord(ch)
    if 0x20 <= cp <= 0x7E or 0xA0 <= cp <= 0xFF:
        return cp
    return _WIN_HIGH.get(cp)


def encode(text: str) -> bytes:
    """``text`` as WinAnsi bytes; raises ValueError naming the first character it lacks."""
    out = bytearray()
    for ch in text:
        b = winansi(ch)
        if b is None:
            raise InvalidArgumentError(
                f"the character U+{ord(ch):04X} is not one a drawing's font has", detail={"parameter": "text"}
            )
        out.append(b)
    return bytes(out)


def unsupported(text: str) -> list[str]:
    """The characters of ``text`` the drawing's font cannot show, each once, in order."""
    seen: list[str] = []
    for ch in text:
        if winansi(ch) is None and ch not in seen:
            seen.append(ch)
    return seen


def _table(ascii_widths: str, high: dict[int, int]) -> dict[int, int]:
    widths = [int(w) for w in ascii_widths.split()]
    if len(widths) != 0x7F - 0x20:
        raise AssertionError("the ASCII width table must have 95 entries")
    table = {0x20 + i: w for i, w in enumerate(widths)}
    table.update(high)
    return table


# Advance widths of 0x20 to 0x7E, in code order (WinAnsi: 0x27 is quotesingle, 0x60 grave).
_HELVETICA_ASCII = """
278 278 355 556 556 889 667 191 333 333 389 584 278 333 278 278
556 556 556 556 556 556 556 556 556 556 278 278 584 584 584 556
1015 667 667 722 722 667 611 778 722 278 500 667 556 833 722 778
667 778 722 667 611 722 667 944 667 667 611 278 278 278 469 556
333 556 556 500 556 556 278 556 556 222 222 500 222 833 556 556
556 556 333 500 278 556 500 722 500 500 500 334 260 334 584
"""
_BOLD_ASCII = """
278 333 474 556 556 889 722 238 333 333 389 584 278 333 278 278
556 556 556 556 556 556 556 556 556 556 333 333 584 584 584 611
975 722 722 722 722 667 611 778 722 278 556 722 611 833 722 778
667 778 722 667 611 722 667 944 667 667 611 333 278 333 584 556
333 556 611 556 611 556 333 611 611 278 278 556 278 889 611 611
611 611 389 556 333 611 556 778 556 556 500 389 280 389 584
"""


def _high(regular: bool) -> dict[int, int]:
    """Widths of 0x80 to 0xFF; the two weights differ only where the second value is given."""
    pairs: dict[int, tuple[int, int]] = {
        0x82: (222, 278), 0x83: (556, 556), 0x84: (333, 500), 0x85: (1000, 1000),
        0x86: (556, 556), 0x87: (556, 556), 0x88: (333, 333), 0x89: (1000, 1000),
        0x8A: (667, 667), 0x8B: (333, 333), 0x8C: (1000, 1000), 0x8E: (611, 611),
        0x91: (222, 278), 0x92: (222, 278), 0x93: (333, 500), 0x94: (333, 500),
        0x95: (350, 350), 0x96: (556, 556), 0x97: (1000, 1000), 0x98: (333, 333),
        0x99: (1000, 1000), 0x9A: (500, 556), 0x9B: (333, 333), 0x9C: (944, 944),
        0x9E: (500, 500), 0x9F: (667, 667),
        0xA0: (278, 278), 0xA1: (333, 333), 0xA2: (556, 556), 0xA3: (556, 556),
        0xA4: (556, 556), 0xA5: (556, 556), 0xA6: (260, 280), 0xA7: (556, 556),
        0xA8: (333, 333), 0xA9: (737, 737), 0xAA: (370, 370), 0xAB: (556, 556),
        0xAC: (584, 584), 0xAD: (333, 333), 0xAE: (737, 737), 0xAF: (333, 333),
        0xB0: (400, 400), 0xB1: (584, 584), 0xB2: (333, 333), 0xB3: (333, 333),
        0xB4: (333, 333), 0xB5: (556, 611), 0xB6: (537, 556), 0xB7: (278, 278),
        0xB8: (333, 333), 0xB9: (333, 333), 0xBA: (365, 365), 0xBB: (556, 556),
        0xBC: (834, 834), 0xBD: (834, 834), 0xBE: (834, 834), 0xBF: (611, 611),
        0xC6: (1000, 1000), 0xC7: (722, 722), 0xD0: (722, 722), 0xD1: (722, 722),
        0xD7: (584, 584), 0xD8: (778, 778), 0xDD: (667, 667), 0xDE: (667, 667),
        0xDF: (611, 611), 0xE6: (889, 889), 0xE7: (500, 556), 0xF0: (556, 611),
        0xF1: (556, 611), 0xF7: (584, 584), 0xF8: (611, 611), 0xFD: (500, 556),
        0xFE: (556, 611), 0xFF: (500, 556),
    }  # fmt: skip
    for code in range(0xC0, 0xC6):  # A with accents
        pairs[code] = (667, 722)
    for code in range(0xC8, 0xCC):  # E with accents
        pairs[code] = (667, 667)
    for code in range(0xCC, 0xD0):  # I with accents
        pairs[code] = (278, 278)
    for code in range(0xD2, 0xD7):  # O with accents
        pairs[code] = (778, 778)
    for code in range(0xD9, 0xDD):  # U with accents
        pairs[code] = (722, 722)
    for code in range(0xE0, 0xE6):  # a with accents
        pairs[code] = (556, 556)
    for code in range(0xE8, 0xEC):  # e with accents
        pairs[code] = (556, 556)
    for code in range(0xEC, 0xF0):  # i with accents
        pairs[code] = (278, 278)
    for code in range(0xF2, 0xF7):  # o with accents
        pairs[code] = (556, 611)
    for code in range(0xF9, 0xFD):  # u with accents
        pairs[code] = (556, 611)
    return {code: (w[0] if regular else w[1]) for code, w in pairs.items()}


WIDTHS: dict[str, dict[int, int]] = {
    "Helvetica": _table(_HELVETICA_ASCII, _high(True)),
    "Helvetica-Bold": _table(_BOLD_ASCII, _high(False)),
}
# The Core 14 AFM files predate the euro, so WinAnsi 0x80 has no width there; it is
# measured as a digit (practice) and the PDF reader's font decides how it looks.
for _table_widths in WIDTHS.values():
    _table_widths.setdefault(0x80, 556)
del _table_widths


def font_name(bold: bool = False) -> str:
    return FONTS[1] if bold else FONTS[0]


def font_size(text_height: float) -> float:
    """The font size whose capital letters are ``text_height`` tall (same unit)."""
    return text_height / CAP_HEIGHT


def advance(ch: str, bold: bool = False) -> int:
    """One character's advance in thousandths of the font size; 0 for one the font lacks
    (it is refused before it gets here)."""
    b = winansi(ch)
    if b is None:
        return 0
    return WIDTHS[font_name(bold)].get(b, 0)


def measure(text: str, size: float, bold: bool = False) -> float:
    """The width of ``text`` set at font size ``size``, in the unit of ``size``."""
    table = WIDTHS[font_name(bold)]
    total = 0
    for ch in text:
        b = winansi(ch)
        if b is not None:
            total += table.get(b, 0)
    return total * size / 1000.0


def measure_height(text: str, text_height: float, bold: bool = False) -> float:
    """The width of ``text`` whose capitals are ``text_height`` tall."""
    return measure(text, font_size(text_height), bold)


__all__ = [
    "ASCENT",
    "CAP_HEIGHT",
    "DESCENT",
    "FONTS",
    "WIDTHS",
    "X_HEIGHT",
    "advance",
    "encode",
    "font_name",
    "font_size",
    "measure",
    "measure_height",
    "unsupported",
    "winansi",
]
