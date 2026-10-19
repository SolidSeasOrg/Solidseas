"""Hole callouts and the other leader statements (``docs/DRAWINGS.md`` 10.9).

A hole callout lists the hole in manufacturing order: the count and diameter with
THRU or its depth (to the full diameter, never the drill point); the counterbore
or spotface line; the countersink line (its diameter at the surface and included
angle); a confirmed thread with its depth; an entry round or chamfer larger than
the edge break. Repetition is ``nX``, never TYP. Symbols are the Y14.5 ones, or
CBORE, SPOTFACE, CSK and DEEP when Settings ask for words.

In a planned callout ``prefix`` holds the count and Ø, ``value`` the drilled
diameter, ``suffix[0]`` THRU or the depth on the value's line, and the rest of
``suffix`` the lines below.
"""

from __future__ import annotations

import math
import re

from .. import numbers, standards
from ..types import Hole
from .context import Context
from .values import DIAMETER, count_prefix, places, shown

CBORE = standards.SYMBOL_COUNTERBORE
CSK = standards.SYMBOL_COUNTERSINK
DEPTH = standards.SYMBOL_DEPTH
SPOTFACE = CBORE + "SF"  # the counterbore symbol with SF inside it (Y14.5-2009 on)
WORDS = {SPOTFACE: "SPOTFACE", CBORE: "CBORE", CSK: "CSK", DEPTH: "DEEP"}


def words(ctx: Context, text: str) -> str:
    """``text`` with the callout symbols spelt out when the Settings ask for words
    (10.9), for readers whose fonts lack them."""
    if not ctx.dimensioning.get("symbol_words"):
        return text
    for symbol in (SPOTFACE, CBORE, CSK, DEPTH):
        text = text.replace(symbol, WORDS[symbol])
    return text


def _len(ctx: Context, value_m: float, role: str) -> str:
    return shown(ctx, value_m, places(ctx, role)).text()


def edge_break_max(ctx: Context) -> float:
    """The largest edge break the general note allows, metres (the last number in the
    Settings' edge break text), or 0 when it states none."""
    text = ctx.settings.notes.edge_break_in if ctx.unit == "in" else ctx.settings.notes.edge_break_mm
    found = re.findall(r"\d*\.?\d+", text)
    if not found:
        return 0.0
    return numbers.from_unit(float(found[-1]), ctx.unit)


def hole(ctx: Context, h: Hole, count: int, fid: str) -> tuple[str, float, tuple[str, ...]]:
    """(prefix, the drilled diameter, suffix lines) of a hole's callout."""
    cylinders = [s for s in h.segments if s.kind == "cylinder"]
    drill = cylinders[-1] if cylinders else None
    value = drill.diameter if drill is not None else h.diameter
    prefix = count_prefix(count) + DIAMETER
    if h.through:
        first = "THRU"
    else:
        first = f"{DEPTH} {_len(ctx, h.depth, 'step')}"
    lines: list[str] = []
    entry = h.segments[0] if h.segments else None
    kinds = set(h.kind.split("+"))
    if entry is not None and entry.kind == "cylinder" and len(cylinders) > 1:
        line = (
            f"{SPOTFACE if 'spotface' in kinds else CBORE} {DIAMETER}{_len(ctx, entry.diameter, 'hole_size')}"
            f" {DEPTH} {_len(ctx, entry.depth, 'step')}"
        )
        if "counterbore" in kinds or "spotface" in kinds:
            lines.append(line)
        else:  # stepped: each larger step as its own diameter and depth
            for seg in cylinders[:-1]:
                lines.append(
                    f"{DIAMETER}{_len(ctx, seg.diameter, 'hole_size')} {DEPTH} {_len(ctx, seg.depth, 'step')}"
                )
    for seg in h.segments:
        if seg.kind == "cone" and "countersink" in kinds:
            top = max(seg.diameter, seg.diameter_end)
            angle = numbers.angle_text(round(math.degrees(seg.angle)), 0)
            lines.append(f"{CSK} {DIAMETER}{_len(ctx, top, 'hole_size')} X {angle}")
            break
    decided = ctx.decisions.get(fid, {})
    thread = decided.get("thread")
    if thread:
        depth = decided.get("thread_depth")
        if h.through or depth is None:
            lines.append(f"{thread} THRU" if h.through else str(thread))
        else:
            lines.append(f"{thread} {DEPTH} {_len(ctx, float(depth), 'step')}")
    if h.entry_break is not None:
        kind, size, _faces = h.entry_break
        if size > edge_break_max(ctx) + 1e-12:
            if kind == "round":
                lines.append(f"R{_len(ctx, size, 'width')} AT ENTRY")
            else:
                lines.append(f"{_len(ctx, size, 'width')} X 45{standards.SYMBOL_DEGREE} AT ENTRY")
    if h.ends[1] == "into_bore" and decided.get("into_bore_note"):
        lines.append("INTO BORE")
    return prefix, value, tuple(words(ctx, t) for t in (first, *lines))


def chamfer(
    ctx: Context, legs: tuple[float, float], angle: float, count: int
) -> tuple[str, float, tuple[str, ...]]:
    """(prefix, value, suffix) of a chamfer: ``2X .03 X 45°`` with the legs and angle
    style, ``.03 X .05`` with two legs (Settings)."""
    small, large = sorted(legs)
    style = ctx.dimensioning.get("chamfer_style", "leg_angle")
    prefix = count_prefix(count)
    if style == "two_legs" or abs(small - large) > max(ctx.tol, 1e-7):
        return prefix, small, (f"X {_len(ctx, large, 'width')}",)
    deg = numbers.angle_text(round(math.degrees(angle), 2), 0)
    return prefix, small, (f"X {deg}",)


__all__ = ["CBORE", "CSK", "DEPTH", "SPOTFACE", "WORDS", "chamfer", "edge_break_max", "hole", "words"]
