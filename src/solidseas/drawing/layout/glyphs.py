"""The pen layout paints with, and the symbols it draws as paths (``docs/DRAWINGS.md``
11.2, 11.4).

:class:`Pen` collects the painted layer's strokes, fills and text runs, each with
its layer and owner. Text goes through :meth:`Pen.text`, which measures it with the
fonts the writers use and draws the symbols WinAnsi lacks as paths in line with
the words: counterbore, spotface, countersink and depth. GD&T characteristic
symbols, the material modifiers, the projection symbol, the datum triangle and
the build-direction arrow are paths too. Proportions of the projection symbol and
the GD&T symbols are verify items (standards.md).
"""

from __future__ import annotations

import math

from .. import display as D
from .. import fonts, standards
from ..painter import arc_beziers
from .index import Box

THIN = standards.LINES["thin"].width
THICK = standards.LINES["visible"].width
CBORE = standards.SYMBOL_COUNTERBORE
CSK = standards.SYMBOL_COUNTERSINK
DEPTH = standards.SYMBOL_DEPTH
SPOTFACE = CBORE + "SF"
# A symbol's width as a share of the text height, and the space after it.
GLYPH_WIDTH = {SPOTFACE: 1.9, CBORE: 1.0, CSK: 1.0, DEPTH: 0.7}
GLYPH_GAP = 0.25


def _split(text: str) -> list[tuple[str, bool]]:
    """``text`` as runs of plain text and symbols (True for a symbol)."""
    out: list[tuple[str, bool]] = []
    k = 0
    plain = ""
    while k < len(text):
        if text.startswith(SPOTFACE, k):
            sym = SPOTFACE
        elif text[k] in (CBORE, CSK, DEPTH):
            sym = text[k]
        else:
            plain += text[k]
            k += 1
            continue
        if plain:
            out.append((plain, False))
            plain = ""
        out.append((sym, True))
        k += len(sym)
    if plain:
        out.append((plain, False))
    return out


def clean(text: str) -> tuple[str, list[str]]:
    """``text`` with every character the font lacks (other than the drawn symbols)
    replaced by ``?``, and the characters replaced."""
    bad = [c for c in fonts.unsupported(text) if c not in (CBORE, CSK, DEPTH)]
    for c in bad:
        text = text.replace(c, "?")
    return text, bad


def text_width(text: str, height: float, bold: bool = False) -> float:
    """The width of ``text`` whose capitals are ``height`` tall, symbols included."""
    size = fonts.font_size(height)
    total = 0.0
    for part, sym in _split(text):
        if sym:
            total += (GLYPH_WIDTH[part] + GLYPH_GAP) * height
        else:
            total += fonts.measure(part, size, bold)
    return total


class Pen:
    """The painted layer as layout builds it."""

    def __init__(self) -> None:
        self.items: list = []
        self.texts: list[tuple[str, Box, str]] = []  # what each text run covers, for the checks
        self.replaced: list[str] = []

    # ------------------------------------------------------------------ strokes

    def path(self, ops, *, width: float = THIN, dash=(), layer: str = "dimensions", owner: str = "", cap=0):
        self.items.append(D.Stroke(tuple(ops), width, tuple(dash), layer, owner, cap, 1))

    def line(self, a, b, **kw) -> None:
        self.path((("M", *a), ("L", *b)), **kw)

    def poly(self, pts, closed: bool = False, **kw) -> None:
        if len(pts) < 2:
            return
        ops = [("M", *pts[0]), *(("L", *p) for p in pts[1:])]
        if closed:
            ops.append(("Z",))
        self.path(ops, **kw)

    def fill(self, pts, *, layer: str = "dimensions", owner: str = "") -> None:
        ops = [("M", *pts[0]), *(("L", *p) for p in pts[1:]), ("Z",)]
        self.items.append(D.Fill(tuple(ops), layer, owner))

    def arc(self, c, r: float, start_deg: float, sweep_deg: float, **kw) -> None:
        a = math.radians(start_deg)
        ops = [
            ("M", c[0] + r * math.cos(a), c[1] + r * math.sin(a)),
            *arc_beziers(c[0], c[1], r, start_deg, sweep_deg),
        ]
        self.path(ops, **kw)

    def circle(self, c, r: float, **kw) -> None:
        self.arc(c, r, 0.0, 360.0, **kw)

    def rect(self, box: Box, **kw) -> None:
        self.poly([(box.x0, box.y0), (box.x1, box.y0), (box.x1, box.y1), (box.x0, box.y1)], closed=True, **kw)

    def arrow(self, tip, direction, length: float, *, layer: str = "dimensions", owner: str = "") -> None:
        """A filled arrowhead with its point at ``tip``, pointing along ``direction``;
        three times as long as it is wide (7.3)."""
        dx, dy = direction
        n = math.hypot(dx, dy) or 1.0
        ux, uy = dx / n, dy / n
        w = length / standards.DIMENSIONS.arrow_ratio
        base = (tip[0] - ux * length, tip[1] - uy * length)
        self.fill(
            [tip, (base[0] - uy * w / 2, base[1] + ux * w / 2), (base[0] + uy * w / 2, base[1] - ux * w / 2)],
            layer=layer,
            owner=owner,
        )

    # ------------------------------------------------------------------ text

    def text(
        self,
        x: float,
        y: float,
        height: float,
        text: str,
        *,
        anchor: str = "left",
        bold: bool = False,
        angle: float = 0.0,
        layer: str = "dimensions",
        owner: str = "",
        keep: bool = True,
    ) -> Box:
        """Text whose capitals are ``height`` tall with its baseline at ``y``; returns
        the box it covers. Turned text (``angle`` 90) holds no symbols."""
        text, bad = clean(text)
        self.replaced += bad
        size = fonts.font_size(height)
        width = text_width(text, height, bold)
        if angle:
            run = D.TextRun(
                x, y, size, text, angle, bold, anchor, fonts.measure(text, size, bold), layer, owner
            )
            self.items.append(run)
            off = {"left": 0.0, "centre": width / 2, "right": width}[anchor]
            box = Box(x - height * 1.05, y - off, x + height * 0.3, y - off + width)
            if keep:
                self.texts.append((text, box, owner))
            return box
        x0 = {"left": x, "centre": x - width / 2, "right": x - width}[anchor]
        cx = x0
        for part, sym in _split(text):
            if sym:
                self.glyph(part, cx, y, height, layer=layer, owner=owner)
                cx += (GLYPH_WIDTH[part] + GLYPH_GAP) * height
            else:
                w = fonts.measure(part, size, bold)
                self.items.append(D.TextRun(cx, y, size, part, 0.0, bold, "left", w, layer, owner))
                cx += w
        box = Box(x0, y - 0.25 * height, x0 + width, y + height)
        if keep:
            self.texts.append((text, box, owner))
        return box

    def glyph(self, sym: str, x: float, y: float, h: float, *, layer: str, owner: str) -> None:
        """One callout symbol with its left at ``x`` on baseline ``y``, ``h`` tall."""
        w = GLYPH_WIDTH[sym] * h
        kw = {"width": THIN, "layer": layer, "owner": owner}
        if sym in (CBORE, SPOTFACE):
            self.poly([(x, y + h), (x, y), (x + w, y), (x + w, y + h)], **kw)
            if sym == SPOTFACE:
                small = 0.6 * h
                size = fonts.font_size(small)
                tw = fonts.measure("SF", size)
                self.items.append(
                    D.TextRun(x + (w - tw) / 2, y + 0.2 * h, size, "SF", 0.0, False, "left", tw, layer, owner)
                )
        elif sym == CSK:
            self.poly([(x, y + h), (x + w / 2, y), (x + w, y + h)], **kw)
        elif sym == DEPTH:
            mid = x + w / 2
            self.line((x, y + h), (x + w, y + h), **kw)
            self.line((mid, y + h), (mid, y), **kw)
            self.poly([(x + 0.1 * w, y + 0.35 * h), (mid, y), (x + 0.9 * w, y + 0.35 * h)], **kw)

    # ------------------------------------------------------------------ GD&T

    def characteristic(self, name: str, c, size: float, *, layer: str, owner: str) -> None:
        """A characteristic's symbol centred on ``c`` in a cell ``size`` high."""
        kw = {"width": THIN, "layer": layer, "owner": owner}
        r = size * 0.28
        x, y = c
        if name == "position":
            self.circle(c, r, **kw)
            self.line((x - r * 1.45, y), (x + r * 1.45, y), **kw)
            self.line((x, y - r * 1.45), (x, y + r * 1.45), **kw)
        elif name == "profile_surface":
            self.arc((x, y - r * 0.5), r * 1.2, 0.0, 180.0, **kw)
            self.line((x - r * 1.2, y - r * 0.5), (x + r * 1.2, y - r * 0.5), **kw)
        elif name == "profile_line":
            self.arc((x, y - r * 0.5), r * 1.2, 0.0, 180.0, **kw)
        elif name == "flatness":
            self.poly(
                [
                    (x - r * 1.3, y - r * 0.6),
                    (x + r * 0.7, y - r * 0.6),
                    (x + r * 1.3, y + r * 0.6),
                    (x - r * 0.7, y + r * 0.6),
                ],
                closed=True,
                **kw,
            )
        elif name == "straightness":
            self.line((x - r * 1.4, y), (x + r * 1.4, y), **kw)
        elif name == "circularity":
            self.circle(c, r, **kw)
        elif name == "cylindricity":
            self.circle(c, r * 0.8, **kw)
            self.line((x - r * 1.3, y - r * 1.2), (x - r * 0.4, y + r * 1.2), **kw)
            self.line((x + r * 0.4, y - r * 1.2), (x + r * 1.3, y + r * 1.2), **kw)
        elif name == "perpendicularity":
            self.line((x - r * 1.3, y - r), (x + r * 1.3, y - r), **kw)
            self.line((x, y - r), (x, y + r * 1.3), **kw)
        elif name == "parallelism":
            self.line((x - r * 1.2, y - r), (x - r * 0.2, y + r * 1.2), **kw)
            self.line((x + r * 0.2, y - r), (x + r * 1.2, y + r * 1.2), **kw)
        elif name == "angularity":
            self.line((x - r * 1.3, y - r), (x + r * 1.3, y - r), **kw)
            self.line((x - r * 1.3, y - r), (x + r * 1.0, y + r * 1.0), **kw)
        elif name in ("circular_runout", "total_runout"):
            self.line((x - r, y - r), (x + r, y + r), **kw)
            self.arrow((x + r, y + r), (1.0, 1.0), r * 0.8, layer=layer, owner=owner)
            if name == "total_runout":
                self.line((x - r * 0.3, y - r), (x + r * 1.7, y + r), **kw)
        else:
            self.circle(c, r, **kw)

    def modifier(self, kind: str, c, size: float, *, layer: str, owner: str) -> None:
        """MMC or LMC: the letter in a circle."""
        self.circle(c, size * 0.36, width=THIN, layer=layer, owner=owner)
        h = size * 0.42
        letter = "M" if kind == "mmc" else "L"
        self.text(c[0], c[1] - h / 2, h, letter, anchor="centre", layer=layer, owner=owner, keep=False)

    def datum_triangle(
        self, tip_line_point, outward, size: float, *, layer: str, owner: str
    ) -> tuple[float, float]:
        """A filled datum triangle standing on a face's line at ``tip_line_point``,
        pointing out along ``outward``; returns where its leader starts."""
        ox, oy = outward
        n = math.hypot(ox, oy) or 1.0
        ux, uy = ox / n, oy / n
        px, py = -uy, ux
        h = size * 0.75
        a = (tip_line_point[0] + px * size / 2, tip_line_point[1] + py * size / 2)
        b = (tip_line_point[0] - px * size / 2, tip_line_point[1] - py * size / 2)
        top = (tip_line_point[0] + ux * h, tip_line_point[1] + uy * h)
        self.fill([a, b, top], layer=layer, owner=owner)
        return top

    def projection_symbol(
        self,
        x: float,
        y: float,
        h: float,
        *,
        angle: str = "third",
        layer: str = "title",
        owner: str = "projection",
    ) -> Box:
        """The projection symbol of ``angle`` (``third`` or ``first``) with its lower left
        at (``x``, ``y``), ``h`` tall: a truncated cone seen from the side, and on its
        right the same cone seen from its small end (two whole circles). A third-angle
        view stands on the side it is seen from, so the cone's narrow end faces the
        circles; a first-angle view stands on the far side, so its wide end does
        (ASME Y14.3 and ISO 5456-2 as publicly summarised; the proportions verify)."""
        kw = {"width": THIN, "layer": layer, "owner": owner}
        w = h * 1.1
        if angle == "first":
            cone = [(x, y + h * 0.25), (x, y + h * 0.75), (x + w, y + h), (x + w, y)]
        else:
            cone = [(x, y), (x, y + h), (x + w, y + h * 0.75), (x + w, y + h * 0.25)]
        self.poly(cone, closed=True, **kw)
        c = (x + w + h * 0.35 + h / 2, y + h / 2)
        self.circle(c, h / 2, **kw)
        self.circle(c, h / 4, **kw)
        self.line(
            (x - h * 0.15, y + h / 2),
            (c[0] + h * 0.65, y + h / 2),
            width=THIN,
            dash=standards.LINES["centre"].dash,
            layer=layer,
            owner=owner,
        )
        return Box(x - h * 0.15, y, c[0] + h * 0.65, y + h)

    def build_arrow(self, base, length: float, *, layer: str = "notes", owner: str = "build") -> Box:
        """The build-direction arrow: up the sheet from ``base``, labelled Z."""
        tip = (base[0], base[1] + length)
        self.line(base, tip, width=THIN, layer=layer, owner=owner)
        self.arrow(tip, (0.0, 1.0), length * 0.25, layer=layer, owner=owner)
        h = length * 0.3
        self.text(
            base[0] + h * 0.4, base[1] + length * 0.4, h, "BUILD Z", layer=layer, owner=owner, keep=False
        )
        return Box(base[0] - h, base[1], base[0] + h * 0.4 + text_width("BUILD Z", h), tip[1])


__all__ = ["CBORE", "CSK", "DEPTH", "SPOTFACE", "THICK", "THIN", "Pen", "clean", "text_width"]
