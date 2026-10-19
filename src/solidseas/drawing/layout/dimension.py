"""Painting a dimension (``docs/DRAWINGS.md`` 11.2).

Extension lines with a gap from the part and an overrun past the dimension line,
starting where the witness is: the end of a visible line for a face, the end of a
hole's centre mark for a centre (C23); filled arrowheads; unidirectional text in a
break of the dimension line, outside with the arrows when cramped; basic values
boxed; ordinates from a 0 with their values on their extension lines; leaders
inclined 15 to 75 degrees with a horizontal shoulder; feature control frames as
cells; datum feature symbols as a framed letter on a leader to a filled triangle.

Every painted item is owned by its dimension's id, a frame by ``<id>-frame`` and a
datum symbol by ``datum-<letter>``, so a writer can tell them apart. The semantic
:class:`~solidseas.drawing.display.Dimension` carries the definition points in the
order the DXF writer reads them (``docs/drawings/dxf.md``).
"""

from __future__ import annotations

import math

from .. import display as D
from .. import standards
from ..display import DimText
from ..numbers import plain_sum
from .glyphs import THIN, Pen, text_width
from .index import DIMLINE, EXTLINE, HARD, Box, Index

OVERSHOOT = 3.0  # a centre mark beyond its circle, on paper (8.7)
LINE_PITCH = 1.7  # text lines a text height apart, times this


def flags(tolerance: str) -> tuple[str, ...]:
    if tolerance == "basic":
        return ("basic",)
    if tolerance == "reference":
        return ("reference",)
    if tolerance == "derived":
        return ("derived",)
    return ()


def value_line(t: DimText) -> str:
    out = t.prefix + t.value
    if t.after:
        out += (" " if out else "") + t.after
    return out


def paint_value(
    pen: Pen, index: Index, x: float, y: float, h: float, t: DimText, *, anchor: str, owner: str
) -> Box:
    """A dimension's value line with its baseline at ``y``: prefix and value, what
    follows them, a stacked tolerance, the basic box. Returns the box it covers."""
    main = t.prefix + t.value
    w_main = text_width(main, h)
    w_after = text_width(" " + t.after, h) if t.after else 0.0
    small = h * 0.8
    w_stack = (
        (max(text_width(t.upper, small), text_width(t.lower, small)) + h * 0.3)
        if (t.upper or t.lower)
        else 0.0
    )
    pad = h * 0.3 if t.boxed else 0.0
    total = w_main + w_after + w_stack + 2 * pad
    x0 = {"left": x, "centre": x - total / 2, "right": x - total}[anchor]
    box = pen.text(x0 + pad, y, h, main, owner=owner, keep=False)
    if t.boxed:
        frame = Box(x0, y - h * 0.45, x0 + w_main + 2 * pad, y + h * 1.25)
        pen.rect(frame, width=THIN, owner=owner)
        box = box.union(frame)
    cx = x0 + w_main + 2 * pad
    if t.after:
        box = box.union(pen.text(cx, y, h, " " + t.after, owner=owner, keep=False))
        cx += w_after
    if t.upper or t.lower:
        if t.upper:
            box = box.union(pen.text(cx + h * 0.3, y + h * 0.55, small, t.upper, owner=owner, keep=False))
        if t.lower:
            box = box.union(pen.text(cx + h * 0.3, y - h * 0.65, small, t.lower, owner=owner, keep=False))
    pen.texts.append((value_line(t), box, owner))
    index.add(HARD, box, owner)
    return box


def paint_suffix(
    pen: Pen, index: Index, x: float, y: float, h: float, lines, *, anchor: str, owner: str
) -> Box | None:
    """Lines below a value, each a pitch lower."""
    out = None
    for k, line in enumerate(lines):
        b = pen.text(x, y - (k + 1) * h * LINE_PITCH, h, line, anchor=anchor, owner=owner)
        index.add(HARD, b, owner)
        out = b if out is None else out.union(b)
    return out


def _broken_line(
    pen: Pen, did: str, lo: float, hi: float, g0: float, g1: float, at: float, horizontal: bool
) -> None:
    """A dimension line from ``lo`` to ``hi`` carried on to a text standing past an end,
    broken from ``g0`` to ``g1`` for the text."""
    start, end = min(lo, g0), max(hi, g1)
    for p, q in ((start, g0), (g1, end)):
        if q - p > 1e-6:
            pen.line((p, at) if horizontal else (at, p), (q, at) if horizontal else (at, q), owner=did)


def linear(
    pen: Pen,
    index: Index,
    *,
    did: str,
    kind: str,
    horizontal: bool,
    a: float,
    b: float,
    start_a: float,
    start_b: float,
    gap_a: float,
    gap_b: float,
    at: float,
    outward: float,
    h: float,
    text: DimText,
    value: float,
    refs: tuple[str, ...],
    tolerance: str,
    places: int,
    view: str,
    shift: float = 0.0,
    clear=None,
) -> D.Dimension:
    """A linear dimension between sheet coordinates ``a`` and ``b`` along its axis,
    its line at ``at`` across it; each extension line starts at ``start`` (less its
    ``gap``) and runs ``outward`` (-1 below or left, +1 above or right). ``shift``
    moves the text along the line, millimetres, where the user moved it: the line
    then runs from end to end, on to the text when it stands past an end, with a
    break for the text. A text too wide for its span stands past the far end (right
    or above); ``clear``, given, says whether a box is free, and the text stands past
    the near end instead when only that is (two such texts at a view's corner)."""
    pre = standards.DIMENSIONS
    arrow = h
    lo, hi = min(a, b), max(a, b)
    over = pre.extension_overrun * 0.5 + 0.5
    pts = []
    for s, start, gap in ((a, start_a, gap_a), (b, start_b, gap_b)):
        p0 = start + outward * gap
        p1 = at + outward * over
        if horizontal:
            pen.line((s, p0), (s, p1), owner=did)
            index.add(EXTLINE, Box.around([(s, p0), (s, p1)], 0.2), did)
            pts.append((s, start))
        else:
            pen.line((p0, s), (p1, s), owner=did)
            index.add(EXTLINE, Box.around([(p0, s), (p1, s)], 0.2), did)
            pts.append((start, s))
    w = text_width(value_line(text), h) + (h * 0.6 if text.boxed else 0.0)
    span = hi - lo
    room = (w if horizontal else h) + 2 * arrow + 3.0
    inside = span >= room
    mid = (lo + hi) / 2
    if shift:
        along = mid + shift
        half = (w / 2 + 1.0) if horizontal else (h / 2 + 1.2)
        _broken_line(pen, did, lo, hi, along - half, along + half, at, horizontal)
        if horizontal:
            pen.arrow((lo, at), (-1.0, 0.0), arrow, owner=did)
            pen.arrow((hi, at), (1.0, 0.0), arrow, owner=did)
            tb = paint_value(pen, index, along, at - h / 2, h, text, anchor="centre", owner=did)
            line_box = Box(min(lo, tb.x0) - arrow, at - 0.25, max(hi, tb.x1) + arrow, at + 0.25)
            text_at, dim_pt = (along, at), (a, at)
        else:
            pen.arrow((at, lo), (0.0, -1.0), arrow, owner=did)
            pen.arrow((at, hi), (0.0, 1.0), arrow, owner=did)
            tb = paint_value(pen, index, at, along - h / 2, h, text, anchor="centre", owner=did)
            line_box = Box(at - 0.25, min(lo, tb.y0) - arrow, at + 0.25, max(hi, tb.y1) + arrow)
            text_at, dim_pt = (at, along), (at, a)
    elif horizontal:
        if inside:
            pen.line((lo, at), (mid - w / 2 - 1.0, at), owner=did)
            pen.line((mid + w / 2 + 1.0, at), (hi, at), owner=did)
            pen.arrow((lo, at), (-1.0, 0.0), arrow, owner=did)
            pen.arrow((hi, at), (1.0, 0.0), arrow, owner=did)
            tx = mid
        else:
            far, near = hi + arrow + 2.0 + w / 2, lo - arrow - 2.0 - w / 2
            boxes = [Box(x - w / 2, at - h * 0.7, x + w / 2, at + h * 0.7) for x in (far, near)]
            low = _near_end(clear, *boxes)
            tx = near if low else far
            if low:
                pen.line((lo - arrow - 1.0, at), (hi + arrow + 2.0, at), owner=did)
            else:
                pen.line((lo - arrow - 2.0, at), (hi + arrow + 1.0, at), owner=did)
            pen.arrow((lo, at), (1.0, 0.0), arrow, owner=did)
            pen.arrow((hi, at), (-1.0, 0.0), arrow, owner=did)
        tb = paint_value(pen, index, tx, at - h / 2, h, text, anchor="centre", owner=did)
        line_box = Box(min(lo, tb.x0) - arrow, at - 0.25, max(hi, tb.x1) + arrow, at + 0.25)
        text_at = (tx, at)
        dim_pt = (a, at)
    else:
        if inside:
            pen.line((at, lo), (at, mid - h / 2 - 1.2), owner=did)
            pen.line((at, mid + h / 2 + 1.2), (at, hi), owner=did)
            pen.arrow((at, lo), (0.0, -1.0), arrow, owner=did)
            pen.arrow((at, hi), (0.0, 1.0), arrow, owner=did)
            ty = mid
        else:
            far, near = hi + arrow + 2.0 + h / 2, lo - arrow - 2.0 - h / 2
            boxes = [Box(at - w / 2, y - h * 0.7, at + w / 2, y + h * 0.7) for y in (far, near)]
            low = _near_end(clear, *boxes)
            ty = near if low else far
            if low:
                pen.line((at, lo - arrow - 1.0), (at, hi + arrow + 2.0), owner=did)
            else:
                pen.line((at, lo - arrow - 2.0), (at, hi + arrow + 1.0), owner=did)
            pen.arrow((at, lo), (0.0, 1.0), arrow, owner=did)
            pen.arrow((at, hi), (0.0, -1.0), arrow, owner=did)
        tb = paint_value(pen, index, at, ty - h / 2, h, text, anchor="centre", owner=did)
        line_box = Box(at - 0.25, min(lo, tb.y0) - arrow, at + 0.25, max(hi, tb.y1) + arrow)
        text_at = (at, ty)
        dim_pt = (at, a)
    if text.suffix:
        paint_suffix(pen, index, text_at[0], text_at[1] - h / 2, h, text.suffix, anchor="centre", owner=did)
    index.add(DIMLINE, line_box, did)
    return D.Dimension(
        did,
        kind,
        view,
        (pts[0], pts[1], dim_pt),
        text_at,
        value,
        text,
        0.0 if horizontal else 90.0,
        refs,
        tolerance,
        places,
        flags(tolerance),
    )


def _near_end(clear, far: Box, near: Box) -> bool:
    """Whether a text too wide for its span stands past its near end: only when its
    far end is taken and the near one free."""
    return clear is not None and not clear(far) and clear(near)


def ordinate_band(
    pen: Pen,
    index: Index,
    *,
    horizontal: bool,
    origin: float,
    origin_start: float,
    items: list[tuple[str, float, float, float, DimText, float, tuple[str, ...], str, int]],
    row: float,
    outward: float,
    h: float,
    view: str,
    zero_id: str,
) -> list[D.Dimension]:
    """Ordinate dimensions along one side: a ``0`` at the origin and each feature's
    value on its extension line, turned to read from the right on a horizontal band;
    close values are jogged apart. ``items`` holds (id, position, start, gap, text,
    value, refs, tolerance, places)."""
    out = []
    boxed = any(e[4].boxed for e in items)
    pitch = h * (1.9 if boxed else 1.0) + 1.4
    entries = [(zero_id, origin, origin_start, 1.5, DimText("0"), 0.0, (), "basic", 0)] + list(items)
    entries.sort(key=lambda e: (e[1], e[0] != zero_id))
    last = None
    last_pos = None
    for did, pos, start, gap, text, value, refs, tolerance, places in entries:
        if last_pos is not None and abs(pos - last_pos) < 0.01:
            # the same value again (features in line): its extension line only
            p0 = start + outward * gap
            ext = [(pos, p0), (pos, row)] if horizontal else [(p0, pos), (row, pos)]
            pen.line(*ext, owner=did)
            index.add(EXTLINE, Box.around(ext, 0.2), did)
            continue
        last_pos = pos
        where = pos if last is None else max(pos, last + pitch)
        last = where
        p0 = start + outward * gap
        label = value_line(text)
        w = text_width(label, h) + (h * 0.6 if text.boxed else 0.0)
        if horizontal:
            pts = [(pos, p0), (pos, row - outward * 2.5), (where, row), (where, row + outward * 1.0)]
            pen.poly(pts, owner=did)
            index.add(EXTLINE, Box.around(pts, 0.2), did)
            ty = row + outward * (1.5 + (w if outward < 0 else 0.0))
            if text.boxed:
                bx = Box(where - h * 0.75, ty - 0.6, where + h * 0.45, ty + w + 0.4)
                pen.rect(bx, owner=did)
            box = pen.text(where + h / 2 - 0.1, ty, h, label, angle=90.0, owner=did)
            text_at = (where, ty + w / 2)
            end = (where, row)
        else:
            pts = [(p0, pos), (row - outward * 2.5, pos), (row, where), (row + outward * 1.0, where)]
            pen.poly(pts, owner=did)
            index.add(EXTLINE, Box.around(pts, 0.2), did)
            tx = row + outward * 1.5
            box = paint_value(
                pen, index, tx, where - h / 2, h, text, anchor="right" if outward < 0 else "left", owner=did
            )
            text_at = ((box.x0 + box.x1) / 2, where)
            end = (row, where)
        index.add(HARD, box, did)
        if did == zero_id:
            continue
        o_pt = (origin, origin_start) if horizontal else (origin_start, origin)
        f_pt = (pos, start) if horizontal else (start, pos)
        out.append(
            D.Dimension(
                did,
                "ordinate",
                view,
                (o_pt, f_pt, end),
                text_at,
                value,
                text,
                0.0,
                refs,
                tolerance,
                places,
                flags(tolerance),
            )
        )
    return out


def leader_block(
    pen: Pen,
    index: Index,
    *,
    did: str,
    start,
    elbow,
    right: bool,
    h: float,
    lines: list[str],
    first: DimText | None,
    frame_cells=None,
    frame_draw=None,
    arrow: bool = True,
) -> tuple[Box, tuple]:
    """A leader from ``start`` to ``elbow`` and a shoulder, then the text lines (the
    first the value line when ``first`` is given) and a frame under them. Returns the
    block's box and the shoulder's end."""
    shoulder = (elbow[0] + (3.0 if right else -3.0), elbow[1])
    pen.line(start, elbow, owner=did)
    pen.line(elbow, shoulder, owner=did)
    if arrow:
        pen.arrow(start, (start[0] - elbow[0], start[1] - elbow[1]), h, owner=did)
    else:
        pen.circle(start, 0.4, owner=did)
    tx = shoulder[0] + (1.0 if right else -1.0)
    anchor = "left" if right else "right"
    y = elbow[1] - h / 2
    box = None
    if first is not None:
        box = paint_value(pen, index, tx, y, h, first, anchor=anchor, owner=did)
        rest = lines
    else:
        b = pen.text(tx, y, h, lines[0], anchor=anchor, owner=did)
        index.add(HARD, b, did)
        box = b
        rest = lines[1:]
    for k, line in enumerate(rest):
        b = pen.text(tx, y - (k + 1) * h * LINE_PITCH, h, line, anchor=anchor, owner=did)
        index.add(HARD, b, did)
        box = box.union(b)
    if frame_draw is not None:
        fy = y - (len(rest) + 1) * h * LINE_PITCH + h * 0.2
        fb = frame_draw(tx, fy, anchor)
        box = box.union(fb)
    index.add_segment(DIMLINE, start, elbow, did)
    index.add_segment(DIMLINE, elbow, shoulder, did)
    return box, shoulder


def frame(
    pen: Pen, index: Index, *, x: float, y: float, h: float, item: D.FrameItem, anchor: str, owner: str
) -> tuple[Box, D.FeatureControlFrame]:
    """A feature control frame with its lower left at (``x``, ``y``) (or its lower
    right, with ``anchor`` right): the characteristic's symbol, the zone with Ø and a
    circled modifier, then a cell for each datum letter."""
    cell = h + 2.0
    zone = ("Ø" if item.diameter else "") + item.zone
    zw = text_width(zone, h) + 2.4 + (cell * 0.8 if item.modifier else 0.0)
    widths = [cell, zw] + [cell] * len(item.datums)
    total = plain_sum(widths)
    x0 = x if anchor == "left" else x - total
    box = Box(x0, y, x0 + total, y + cell)
    pen.rect(box, owner=owner)
    cx = x0
    for k, w in enumerate(widths):
        if k:
            pen.line((cx, y), (cx, y + cell), owner=owner)
        if k == 0:
            pen.characteristic(
                item.characteristic, (cx + w / 2, y + cell / 2), cell, layer="dimensions", owner=owner
            )
        elif k == 1:
            pen.text(cx + 1.2, y + (cell - h) / 2, h, zone, owner=owner, keep=False)
            if item.modifier:
                pen.modifier(
                    item.modifier, (cx + w - cell * 0.45, y + cell / 2), cell, layer="dimensions", owner=owner
                )
        else:
            letter = item.datums[k - 2]
            pen.text(cx + w / 2, y + (cell - h) / 2, h, letter, anchor="centre", owner=owner, keep=False)
        cx += w
    pen.texts.append(("frame", box, owner))
    index.add(HARD, box, owner)
    return box, D.FeatureControlFrame((x0, y), item, owner)


def datum_reach(h: float) -> float:
    """How far a datum feature symbol stands out from its face: the triangle, the
    leader and the letter's box (:func:`datum_symbol`), and a millimetre clear."""
    return h * 0.9 * 0.75 + 3.0 + (h + 2.5) + 1.0


def datum_symbol(pen: Pen, *, letter: str, foot, outward, h: float, view: str) -> tuple[Box, D.DatumFeature]:
    """A datum feature symbol: a filled triangle on the face's line at ``foot``, a
    short leader out along ``outward``, and the letter in a square box."""
    owner = f"datum-{letter}"
    size = h + 2.5
    top = pen.datum_triangle(foot, outward, h * 0.9, layer="dimensions", owner=owner)
    ox, oy = outward
    n = math.hypot(ox, oy) or 1.0
    ux, uy = ox / n, oy / n
    end = (top[0] + ux * 3.0, top[1] + uy * 3.0)
    pen.line(top, end, owner=owner)
    if abs(ux) > abs(uy):
        x0 = end[0] if ux > 0 else end[0] - size
        y0 = end[1] - size / 2
    else:
        x0 = end[0] - size / 2
        y0 = end[1] if uy > 0 else end[1] - size
    box = Box(x0, y0, x0 + size, y0 + size)
    pen.rect(box, owner=owner)
    pen.text(x0 + size / 2, y0 + (size - h) / 2, h, letter, anchor="centre", owner=owner, keep=False)
    pen.texts.append((letter, box, owner))
    return box.union(Box.around([foot, end], 0.5)), D.DatumFeature(letter, (x0, y0), (foot, top, end), view)


def angle(
    pen: Pen,
    index: Index,
    *,
    did: str,
    vertex,
    a0: float,
    a1: float,
    radius: float,
    h: float,
    text: DimText,
    value: float,
    refs,
    tolerance: str,
    places: int,
    view: str,
) -> D.Dimension:
    """An angle from direction ``a0`` to ``a1`` (degrees, counter-clockwise) about
    ``vertex``: the sides drawn out past the arc, the arc with arrows, the value
    outside it at the middle."""
    cx, cy = vertex
    for ang in (a0, a1):
        r = math.radians(ang)
        pen.line(vertex, (cx + (radius + 3.0) * math.cos(r), cy + (radius + 3.0) * math.sin(r)), owner=did)
    sweep = (a1 - a0) % 360.0
    pen.arc(vertex, radius, a0, sweep, owner=did)
    for ang, sense in ((a0, -1.0), (a1, 1.0)):
        r = math.radians(ang)
        tip = (cx + radius * math.cos(r), cy + radius * math.sin(r))
        pen.arrow(tip, (-sense * math.sin(r), sense * math.cos(r)), h, owner=did)
    m = math.radians(a0 + sweep / 2)
    tx, ty = cx + (radius + h * 1.2) * math.cos(m), cy + (radius + h * 1.2) * math.sin(m)
    anchor = "left" if math.cos(m) >= -0.2 else "right"
    box = paint_value(pen, index, tx, ty - h / 2, h, text, anchor=anchor, owner=did)
    index.add(DIMLINE, Box.around([vertex, (tx, ty)], 0.3), did)
    p0 = (cx + radius * math.cos(math.radians(a0)), cy + radius * math.sin(math.radians(a0)))
    p1 = (cx + radius * math.cos(math.radians(a1)), cy + radius * math.sin(math.radians(a1)))
    pm = (cx + radius * math.cos(m), cy + radius * math.sin(m))
    return D.Dimension(
        did,
        "angle",
        view,
        (vertex, p0, p1, pm),
        ((box.x0 + box.x1) / 2, ty),
        value,
        text,
        0.0,
        refs,
        tolerance,
        places,
        flags(tolerance),
    )


__all__ = [
    "LINE_PITCH",
    "OVERSHOOT",
    "angle",
    "datum_reach",
    "datum_symbol",
    "flags",
    "frame",
    "leader_block",
    "linear",
    "ordinate_band",
    "paint_suffix",
    "paint_value",
    "value_line",
]
