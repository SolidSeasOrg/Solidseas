"""The notes block (``docs/DRAWINGS.md`` 11.4): NOTES: and the numbered notes,
wrapped to the block's width, above the title block. A note's frames follow its
words on its last line (C27), the general profile note's included, and the next
note starts far enough down that its capitals stand a millimetre clear of them.
"""

from __future__ import annotations

from .. import display as D
from ..numbers import plain_sum
from ..plan.gdt import frame_item
from ..types import NoteLine
from . import dimension
from .glyphs import Pen, text_width
from .index import HARD, Box, Index

PITCH = 1.6


def wrap(text: str, width: float, h: float, indent: float = 0.0) -> list[str]:
    """``text`` in lines of at most ``width``, those after the first ``indent`` in."""
    lines: list[str] = []
    cur = ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        room = width - (indent if lines else 0.0)
        if not cur or text_width(trial, h) <= room:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def height(notes: tuple[NoteLine, ...], width: float, h: float, frame_w) -> float:
    """How tall the block is for these notes at text height ``h``."""
    if not notes:
        return 0.0
    rows = 1
    extra = 0.0
    for k, n in enumerate(notes, 1):
        lines = wrap(f"{k}. {n.text}", width, h, h * INDENT)
        rows += len(lines)
        if n.frames:
            last = _end(lines, h) + 2.0 + plain_sum(frame_w(f) for f in n.frames)
            if last > width:
                extra += own_row(h)
            extra += below_frame(h)
    return rows * h * PITCH + h + extra


INDENT = 1.2  # continuation lines start this many text heights in


def own_row(h: float) -> float:
    """How far below the last line a frame on a row of its own sets the next baseline:
    the frame (a text height and 2 mm) clear of the descenders above it."""
    return 1.25 * h + 1.2


FRAME_DROP = 1.4  # a note's frame stands this far below its line's baseline
CLEAR = 1.0  # the next note's capitals stand at least this far below a frame


def below_frame(h: float) -> float:
    """How much further down the next note starts after a note with frames, so its
    capitals stand :data:`CLEAR` below the frames (which reach :data:`FRAME_DROP`
    below the baseline, further than the line pitch leaves room for)."""
    return max(0.0, FRAME_DROP + CLEAR - (PITCH - 1.0) * h)


def _end(lines: list[str], h: float) -> float:
    """Where the last line ends, from the block's left edge."""
    return (h * INDENT if len(lines) > 1 else 0.0) + text_width(lines[-1], h)


def notes_block(
    pen: Pen, index: Index, ctx, area: Box, notes: tuple[NoteLine, ...], h: float, frame_w
) -> list:
    """Paint the notes in ``area`` from its top and return their annotations."""
    if not notes:
        return []
    out: list = []
    x = area.x0 + 1.0
    y = area.y1 - h * 1.4
    pen.text(x, y, h, "NOTES:", bold=True, layer="notes", owner="notes")
    width = area.width - 2.0
    for k, n in enumerate(notes, 1):
        y -= h * PITCH
        lines = wrap(f"{k}. {n.text}", width, h, h * INDENT)
        first_y = y
        for j, line in enumerate(lines):
            if j:
                y -= h * PITCH
            pen.text(x + (h * INDENT if j else 0.0), y, h, line, layer="notes", owner=f"n-{k}")
        if n.frames:
            fx = x + _end(lines, h) + 2.0
            total = plain_sum(frame_w(f) for f in n.frames)
            fy = y - FRAME_DROP  # the frame's cells centred on the line
            if fx + total > area.x1:
                y -= own_row(h)
                fx = x + h * INDENT
                fy = y - FRAME_DROP
            for f in n.frames:
                box, ann = dimension.frame(
                    pen, index, x=fx, y=fy, h=h, item=frame_item(ctx, f), anchor="left", owner=f"n-{k}-frame"
                )
                out.append(ann)
                fx = box.x1 + 1.0
            y -= below_frame(h)
        out.append(
            D.Note(
                f"n-{k}",
                (x, first_y),
                ((n.text, tuple(frame_item(ctx, f) for f in n.frames)),),
                (),
                k,
            )
        )
    index.add(HARD, area, "notes")
    return out


__all__ = ["CLEAR", "INDENT", "below_frame", "height", "notes_block", "own_row", "wrap"]
