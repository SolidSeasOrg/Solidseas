"""The reference writer of the painted layer: SVG (``docs/DRAWINGS.md`` 12.3).

Internal: previews, documentation and goldens use it; it is not offered as an
export in stage 1. It is a :class:`~.painter.Painter`, so it draws exactly what
the PDF writer draws. The page is in millimetres with y flipped to SVG's
downward axis; numbers have three decimals, so the goldens compare within a
hundredth of a millimetre. Every string is escaped as XML text and nothing in
the file is active: no script, link or external reference, and the logo is an
inline PNG.

SVG has no pages, so a drawing of several sheets (an assembly's parts list going
on past the first, :attr:`.display.Sheet.continuation`) is a file for each sheet:
:func:`to_svg` and :func:`write_svg` draw the one sheet they are given (the first
alone for a drawing's sheet), and :func:`to_svgs` gives every sheet's, in order.
"""

from __future__ import annotations

import base64
import math
from collections.abc import Sequence
from typing import IO
from xml.sax.saxutils import escape, quoteattr

from . import display as D
from .painter import paint

_ANCHOR = {"left": "start", "centre": "middle", "right": "end"}


def _n(x: float) -> str:
    """A number with at most three decimals and no trailing zeros; never ``-0``."""
    text = f"{x:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


class SvgPainter:
    """Collects one page as SVG text; :meth:`text_out` returns it."""

    def __init__(self, title: str = "") -> None:
        self.title = title
        self.parts: list[str] = []
        self.height = 0.0
        self._ops: list[tuple] = []
        self._stroke = (0.3, (), 0, 0, 0.0)

    def _y(self, y: float) -> float:
        return self.height - y

    def begin_page(self, width: float, height: float) -> None:
        self.height = height
        self.parts = [
            '<?xml version="1.0" encoding="UTF-8"?>\n',
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{_n(width)}mm" height="{_n(height)}mm" '
            f'viewBox="0 0 {_n(width)} {_n(height)}">\n',
        ]
        if self.title:
            self.parts.append(f"<title>{escape(self.title)}</title>\n")
        self.parts.append(f'<rect x="0" y="0" width="{_n(width)}" height="{_n(height)}" fill="#fff"/>\n')

    def set_stroke(self, width: float, dash: Sequence[float], cap: int, join: int, grey: float) -> None:
        self._stroke = (width, tuple(dash), cap, join, grey)

    def path(self, ops: Sequence[tuple]) -> None:
        self._ops = list(ops)

    def _d(self) -> str:
        out = []
        for op in self._ops:
            if op[0] == "Z":
                out.append("Z")
                continue
            coords = op[1:]
            pairs = " ".join(
                f"{_n(coords[i])} {_n(self._y(coords[i + 1]))}" for i in range(0, len(coords), 2)
            )
            out.append(f"{op[0]}{pairs}")
        return " ".join(out)

    @staticmethod
    def _grey(g: float) -> str:
        v = max(0, min(255, int(round(g * 255))))
        return f"#{v:02x}{v:02x}{v:02x}"

    def stroke(self) -> None:
        width, dash, cap, join, grey = self._stroke
        caps = ("butt", "round", "square")
        joins = ("miter", "round", "bevel")
        attrs = [
            f'd="{self._d()}"',
            'fill="none"',
            f'stroke="{self._grey(grey)}"',
            f'stroke-width="{_n(width)}"',
            f'stroke-linecap="{caps[cap % 3]}"',
            f'stroke-linejoin="{joins[join % 3]}"',
        ]
        if dash:
            attrs.append(f'stroke-dasharray="{" ".join(_n(d) for d in dash)}"')
        self.parts.append(f"<path {' '.join(attrs)}/>\n")

    def fill(self, grey: float) -> None:
        self.parts.append(f'<path d="{self._d()}" fill="{self._grey(grey)}" stroke="none"/>\n')

    def text(
        self, x: float, y: float, size: float, angle_deg: float, string: str, font: str, anchor: str
    ) -> None:
        weight = ' font-weight="bold"' if font.endswith("Bold") else ""
        ty = self._y(y)
        rotate = f' transform="rotate({_n(-angle_deg)} {_n(x)} {_n(ty)})"' if angle_deg else ""
        # SVG viewers drop leading and trailing spaces and run spaces together unless told not to;
        # a callout's " THRU", written as its own piece after the size, needs its space kept.
        keep = ' xml:space="preserve"' if string != string.strip() or "  " in string else ""
        self.parts.append(
            f'<text x="{_n(x)}" y="{_n(ty)}" font-family="Helvetica, Arial, sans-serif" '
            f'font-size="{_n(size)}"{weight} text-anchor="{_ANCHOR.get(anchor, "start")}"{rotate}{keep}>'
            f"{escape(string)}</text>\n"
        )

    def image(self, x: float, y: float, width: float, height: float, data: bytes) -> None:
        href = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
        self.parts.append(
            f'<image x="{_n(x)}" y="{_n(self._y(y + height))}" width="{_n(width)}" height="{_n(height)}" '
            f"href={quoteattr(href)}/>\n"
        )

    def group(self, name: str) -> None:
        self.parts.append(f"<g id={quoteattr('layer-' + name)}>\n")

    def end_group(self) -> None:
        self.parts.append("</g>\n")

    def end_page(self) -> None:
        self.parts.append("</svg>\n")

    def text_out(self) -> str:
        return "".join(self.parts)


def to_svg(sheet: D.Sheet, title: str = "") -> str:
    """A sheet's painted layer as SVG text: that sheet alone, never those that
    continue it."""
    p = SvgPainter(title)
    paint(sheet, p)
    return p.text_out()


def to_svgs(sheet: D.Sheet, title: str = "") -> list[str]:
    """Every sheet of a drawing whose first sheet is ``sheet`` as SVG text, a file each,
    from the first."""
    return [to_svg(page, title) for page in D.sheets_of(sheet)]


def write_svg(sheet: D.Sheet, fh: IO[bytes], title: str = "") -> int:
    """Write a sheet as UTF-8 SVG to a binary file object; returns the bytes written."""
    data = to_svg(sheet, title).encode("utf-8")
    fh.write(data)
    return len(data)


def numbers(svg: str) -> list[float]:
    """Every number in an SVG's drawing attributes, in order: what the goldens compare
    within 0.01 mm across machines (12.4)."""
    import re

    out: list[float] = []
    for value in re.findall(
        r'(?:\bd|x|y|width|height|font-size|stroke-width|stroke-dasharray)="([^"]*)"', svg
    ):
        for tok in re.findall(r"-?\d+(?:\.\d+)?", value):
            out.append(float(tok))
    return out


def close_enough(a: str, b: str, tol: float = 0.01) -> bool:
    """Whether two SVGs carry the same numbers within ``tol`` and the same structure."""
    na, nb = numbers(a), numbers(b)
    return len(na) == len(nb) and all(math.isclose(x, y, abs_tol=tol) for x, y in zip(na, nb, strict=True))


__all__ = ["SvgPainter", "close_enough", "numbers", "to_svg", "to_svgs", "write_svg"]
