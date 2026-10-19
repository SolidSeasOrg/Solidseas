"""Small drawings as PNG, with the standard library only (the packaged viewer has no
Pillow): filled polygons with holes, lines, circles and a few characters of a 5 x 7 font,
enough to number outlines and label a scale bar."""

from __future__ import annotations

import math
import struct
import zlib
from collections.abc import Sequence

Colour = tuple[int, int, int]
Point = tuple[float, float]

_FONT = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    "m": ("00000", "00000", "11010", "10101", "10101", "10101", "10101"),
    "x": ("00000", "00000", "10001", "01010", "00100", "01010", "10001"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    " ": ("00000",) * 7,
}
GLYPH_W, GLYPH_H = 5, 7


class Canvas:
    """An RGB picture ``width`` x ``height`` pixels, drawn on in pixel coordinates."""

    def __init__(self, width: int, height: int, background: Colour = (255, 255, 255)) -> None:
        self.width, self.height = width, height
        self.rows = [bytearray(bytes(background) * width) for _ in range(height)]

    def polygon(self, rings: Sequence[Sequence[Point]], colour: Colour) -> None:
        """Fill the rings together, even-odd, so an inner ring is a hole."""
        edges = []
        for ring in rings:
            n = len(ring)
            for i in range(n):
                (x1, y1), (x2, y2) = ring[i], ring[(i + 1) % n]
                if y1 == y2:
                    continue
                if y1 > y2:
                    x1, y1, x2, y2 = x2, y2, x1, y1
                edges.append((y1, y2, x1, (x2 - x1) / (y2 - y1)))
        if not edges:
            return
        top = max(0, math.floor(min(e[0] for e in edges)))
        bottom = min(self.height - 1, math.ceil(max(e[1] for e in edges)))
        pixel = bytes(colour)
        for y in range(top, bottom + 1):
            middle = y + 0.5
            xs = sorted(x1 + (middle - y1) * slope for y1, y2, x1, slope in edges if y1 <= middle < y2)
            row = self.rows[y]
            for a, b in zip(xs[0::2], xs[1::2], strict=False):
                start = max(0, math.ceil(a - 0.5))
                end = min(self.width, math.ceil(b - 0.5))
                if end > start:
                    row[start * 3 : end * 3] = pixel * (end - start)

    def rect(self, x0: float, y0: float, x1: float, y1: float, colour: Colour) -> None:
        self.polygon([[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]], colour)

    def line(self, a: Point, b: Point, colour: Colour, width: float = 1.0) -> None:
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length == 0:
            return
        nx, ny = -dy / length * width / 2, dx / length * width / 2
        self.polygon(
            [
                [
                    (a[0] + nx, a[1] + ny),
                    (b[0] + nx, b[1] + ny),
                    (b[0] - nx, b[1] - ny),
                    (a[0] - nx, a[1] - ny),
                ]
            ],
            colour,
        )

    def outline(self, ring: Sequence[Point], colour: Colour, width: float = 1.0) -> None:
        for i in range(len(ring)):
            self.line(ring[i], ring[(i + 1) % len(ring)], colour, width)

    def circle(self, centre: Point, radius: float, colour: Colour) -> None:
        self.polygon([_circle(centre, radius)], colour)

    def text(self, x: float, y: float, text: str, colour: Colour, scale: int = 2) -> None:
        """Draw ``text`` with its top left at (x, y); characters the font lacks are skipped."""
        left = round(x)
        for ch in text:
            glyph = _FONT.get(ch)
            if glyph is not None:
                for r, bits in enumerate(glyph):
                    for c, bit in enumerate(bits):
                        if bit == "1":
                            px, py = left + c * scale, round(y) + r * scale
                            self.rect(px, py, px + scale, py + scale, colour)
            left += (GLYPH_W + 1) * scale

    @staticmethod
    def text_size(text: str, scale: int = 2) -> tuple[int, int]:
        return len(text) * (GLYPH_W + 1) * scale - scale, GLYPH_H * scale

    def label(self, centre: Point, text: str, *, ink: Colour, paper: Colour, scale: int = 2) -> None:
        """``text`` in a small box of its own, centred on ``centre``."""
        w, h = self.text_size(text, scale)
        x, y = centre[0] - w / 2, centre[1] - h / 2
        self.rect(x - 2 * scale, y - 2 * scale, x + w + 2 * scale, y + h + 2 * scale, paper)
        self.text(x, y, text, ink, scale)

    def png(self) -> bytes:
        raw = b"".join(b"\x00" + bytes(row) for row in self.rows)
        header = struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(raw, 9))
            + _chunk(b"IEND", b"")
        )


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def _circle(centre: Point, radius: float, segments: int = 48) -> list[Point]:
    return [
        (
            centre[0] + radius * math.cos(2 * math.pi * k / segments),
            centre[1] + radius * math.sin(2 * math.pi * k / segments),
        )
        for k in range(segments)
    ]


class View:
    """Millimetres to pixels: the box (x0, y0, x1, y1) fitted in at most ``longest`` pixels a
    side with ``margin`` pixels round it and a ``band`` of pixels under it, y down as in the
    drawing's source."""

    def __init__(
        self, box: tuple[float, float, float, float], longest: int = 640, margin: int = 20, band: int = 32
    ) -> None:
        x0, y0, x1, y1 = box
        span = max(x1 - x0, y1 - y0, 1e-6)
        self.scale = (longest - 2 * margin) / span
        self.x0, self.y0, self.margin, self.band = x0, y0, margin, band
        self.width = max(1, math.ceil((x1 - x0) * self.scale) + 2 * margin)
        self.height = max(1, math.ceil((y1 - y0) * self.scale) + 2 * margin + band)

    def __call__(self, points: Sequence[Point]) -> list[Point]:
        m, s = self.margin, self.scale
        return [(m + (x - self.x0) * s, m + (y - self.y0) * s) for x, y in points]

    def at(self, point: Point) -> Point:
        return self([point])[0]


def scale_bar(canvas: Canvas, view: View, ink: Colour, caption: str = "") -> None:
    """A scale bar of a round length, labelled in mm, at the left of the band under the drawing, and
    ``caption`` at its right."""
    target = (canvas.width - 2 * view.margin) / 4 / view.scale  # about a quarter of the width
    length = max((v for v in (5, 10, 20, 50, 100, 200, 500) if v <= target), default=5)
    x, y = view.margin, canvas.height - view.band / 2 - 2
    end = x + length * view.scale
    canvas.line((x, y), (end, y), ink, 3)
    canvas.line((x, y - 6), (x, y + 6), ink, 2)
    canvas.line((end, y - 6), (end, y + 6), ink, 2)
    text = f"{length} mm"
    _, h = Canvas.text_size(text)
    canvas.text(end + 8, y - h / 2, text, ink)
    if caption:
        w, h = Canvas.text_size(caption)
        canvas.text(canvas.width - view.margin - w, y - h / 2, caption, ink)


__all__ = ["Canvas", "View", "scale_bar"]
