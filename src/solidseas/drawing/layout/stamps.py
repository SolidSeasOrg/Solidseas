"""The border, its zones and the stamps (``docs/DRAWINGS.md`` 11.4).

The border is the thick frame inside the margins, with zone marks and their labels
when Settings ask for zones: numbers along the top and bottom from the right,
letters up the sides from the bottom (Y14.1). The PRELIMINARY stamp goes in the
top margin of every unreleased sheet, and a zone mark under it stops short of it;
the plot stamp names SolidSeas, its version,
the part's file name (never a folder) and its configuration, inside the border
at the lower left.
"""

from __future__ import annotations

from ... import __version__
from .. import display as D
from .glyphs import THICK, THIN, Pen, text_width
from .sheet import SheetFrame

PRELIMINARY = "PRELIMINARY - NOT FOR MANUFACTURE"
ZONE_LETTERS = "ABCDEFGHJKLMNPRTUVWY"  # I, O, Q, S, X and Z are not used


def _stamp_place(f: SheetFrame) -> tuple[float, float, float]:
    """The PRELIMINARY stamp's middle, baseline and height in the top margin: as large
    as the margin allows, kept clear of the zone labels either side."""
    h = min(4.0, f.margin * 0.45)
    if f.columns > 1:
        room = f.border.width / f.columns * (1.0 if f.columns % 2 == 0 else 0.6) - 6.0
        while h > 2.0 and text_width(PRELIMINARY, h, True) > room:
            h -= 0.1
    return (f.border.x0 + f.border.x1) / 2, f.border.y1 + (f.margin - h) / 2, h


def border(pen: Pen, f: SheetFrame, zones: bool, *, stamped: bool = False) -> list:
    """The border and its zones; ``stamped`` when the sheet carries the PRELIMINARY
    stamp, which a zone mark in the top margin stops short of."""
    b = f.border
    pen.rect(b, width=THICK, layer="border", owner="border")
    out: list = [D.Border(f.width, f.height, f.margin, f.columns if zones else 0, f.rows if zones else 0)]
    if not zones:
        return out
    h = min(3.0, f.margin * 0.4)
    tick = f.margin * 0.5
    sx, sy, sh = _stamp_place(f)
    half = text_width(PRELIMINARY, sh, True) / 2 + 1.0
    for i in range(f.columns):
        x0 = b.x1 - (i + 1) * b.width / f.columns
        if i < f.columns - 1:
            pen.line((x0, b.y0), (x0, b.y0 - tick), width=THIN, layer="border", owner="border")
            # an even number of columns puts a mark under the stamp's middle
            top = min(tick, sy - b.y1 - 1.0) if stamped and abs(x0 - sx) <= half else tick
            if top > 0.0:
                pen.line((x0, b.y1), (x0, b.y1 + top), width=THIN, layer="border", owner="border")
        xm = x0 + b.width / f.columns / 2
        label = str(i + 1)
        pen.text(
            xm,
            b.y0 - f.margin * 0.5 - h / 2,
            h,
            label,
            anchor="centre",
            layer="border",
            owner="border",
            keep=False,
        )
        pen.text(
            xm,
            b.y1 + f.margin * 0.5 - h / 2,
            h,
            label,
            anchor="centre",
            layer="border",
            owner="border",
            keep=False,
        )
    for j in range(f.rows):
        y0 = b.y0 + j * b.height / f.rows
        if j:
            pen.line((b.x0, y0), (b.x0 - tick, y0), width=THIN, layer="border", owner="border")
            pen.line((b.x1, y0), (b.x1 + tick, y0), width=THIN, layer="border", owner="border")
        ym = y0 + b.height / f.rows / 2 - h / 2
        letter = ZONE_LETTERS[j % len(ZONE_LETTERS)]
        pen.text(
            b.x0 - f.margin * 0.5, ym, h, letter, anchor="centre", layer="border", owner="border", keep=False
        )
        pen.text(
            b.x1 + f.margin * 0.5, ym, h, letter, anchor="centre", layer="border", owner="border", keep=False
        )
    return out


def stamps(pen: Pen, f: SheetFrame, *, released: bool, file_name: str, configuration: str | None) -> list:
    out: list = []
    if not released:
        x, y, h = _stamp_place(f)
        pen.text(x, y, h, PRELIMINARY, bold=True, anchor="centre", layer="stamp", owner="stamp", keep=False)
        out.append(D.Stamp(PRELIMINARY, (x, y)))
    words = f"SolidSeas {__version__}"
    if file_name:
        words += f", {file_name}" + (f" ({configuration})" if configuration else "")
    h = 1.8
    at = (f.plot.x0 + 1.0, f.plot.y0 + 1.0)
    pen.text(at[0], at[1], h, words, layer="stamp", owner="plot", keep=False)
    out.append(D.PlotStamp(words, at))
    return out


__all__ = ["PRELIMINARY", "border", "stamps"]
