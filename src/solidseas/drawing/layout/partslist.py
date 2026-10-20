"""An assembly's parts list and item balloons on the sheet
(``docs/drawings/assemblies.md``).

**The parts list** stands on the title block, the width of it, as ASME Y14.34
places a parts list on the field of a drawing: the column headings at the bottom,
next to the title block, and the items above them from 1 upward. Its columns are
SOLIDWORKS' default BOM table's, their headings shortened to fit an A sheet's
title block, with DWG NO. after the part number, so the reader goes from an item
to its own drawing: ITEM, PART NO., DWG NO., DESCRIPTION and QTY., lettered at the
notes' height, in capitals when the Settings letter notes so. ITEM and QTY. are as
wide as their headings; the others share the rest by what they hold, and a text
too long for its cell is cut with an ellipsis.

**A long parts list** (:func:`shape`) grows leftward past the title block's width
when its texts need the room, to :data:`MAX_GROW` times that width, and, when it
would stand taller than :data:`PARTS_SHARE` of the field above the title block,
continues in columns to its left, each with its own headings at the bottom and
the items going on from where the column to its right ends, as many as
:data:`MOST_ACROSS` of the border's width holds. A list longer still goes on to
sheets of its own (:func:`continued`), the same size, each with the title block
and as many columns as the field above it holds, standing on it the same way and
each with its headings; a drawing held to one sheet (:func:`shape` without
``more``) stands taller instead.

**A balloon** is a circle round its item number, the number at the notes' height,
on a leader that ends in an arrowhead on the visible edge the plan chose. The
balloon goes outside its view, on the side the edge is on where it can, its
leader at 15 to 75 degrees as every leader is, clear of everything placed and
crossing no other leader; the leader points at the circle's centre.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .. import display as D
from ..numbers import plain_sum
from .glyphs import THICK, THIN, Pen, text_width
from .index import DIMLINE, HARD, Box, Index
from .titleblock import _cut

COLUMNS = ("ITEM", "PART NO.", "DWG NO.", "DESCRIPTION", "QTY.")
ROW = 2.0  # a row's height as a share of the text height
PAD = 1.0  # millimetres between a cell's rule and its text
SLACK = 0.2  # millimetres a column is wider than its widest text
TURN = 1.0  # millimetres of leader a degree away from straight out of the view is worth
OWNER = "parts"
REACH = (3.0, 6.0, 10.0, 15.0, 21.0, 28.0, 38.0)  # leader lengths tried beyond the view, millimetres
CLEAR = 1.5  # millimetres a leader runs clear of its view before the balloon


PARTS_SHARE = 0.6  # the most of the field's height above the title block one column takes
MAX_GROW = 1.6  # the widest a parts list grows, as a share of the title block's width
MOST_ACROSS = 0.75  # the most of the border's width the columns together take


def row_height(h: float) -> float:
    return h * ROW


@dataclass(frozen=True)
class Shape:
    """How a parts list stands on one sheet: its columns side by side, the lines in
    each (the last may hold fewer), each column's width, the tallest's height, and how
    many of the list's lines the sheet holds (the rest go on to the next)."""

    columns: int = 0
    per_column: int = 0
    width: float = 0.0
    height: float = 0.0
    lines: int = 0

    @property
    def total_width(self) -> float:
        return self.columns * self.width


def natural_width(rows, h: float, columns=COLUMNS, narrow=None) -> float:
    """The width at which no cell's text is cut."""

    def wide(text: str, bold: bool = False) -> float:
        return text_width(text, h, bold) + 2 * PAD + SLACK

    total = 0.0
    for k, head in enumerate(columns):
        total += max(wide(head, True), max([wide(r[k]) for r in rows if k < len(r)] or [0.0]))
    return total


def shape(
    rows,
    h: float,
    title_width: float,
    room: float,
    across: float,
    columns=COLUMNS,
    narrow=None,
    *,
    more: bool = False,
) -> Shape:
    """The parts list's shape on a sheet whose title block is ``title_width`` wide, with
    ``room`` millimetres of field above the title block and ``across`` millimetres of
    border width (see the module notes). With ``more`` a list longer than the columns
    hold fills them and leaves the rest to the sheets after (``lines`` says how many
    this one holds); without, its columns stand taller."""
    n = len(rows)
    if not n:
        return Shape()
    rh = row_height(h)
    width = min(max(title_width, natural_width(rows, h, columns, narrow)), title_width * MAX_GROW)
    fit = max(1, int(room * PARTS_SHARE // rh) - 1)
    most = int(across * MOST_ACROSS // width) or 1
    count = math.ceil(n / fit)
    if more and count > most:
        return Shape(most, fit, width, (fit + 1) * rh, most * fit)
    count = max(1, min(count, most))
    per = math.ceil(n / count)
    count = math.ceil(n / per)
    return Shape(count, per, width, (per + 1) * rh, n)


def continued(n: int, h: float, width: float, room: float, across: float, *, last: bool = False) -> Shape:
    """The shape of a parts list's ``n`` lines still to go on a sheet of their own, in
    columns ``width`` wide (the first sheet's), with ``room`` millimetres of field above
    the title block and ``across`` millimetres of border width: as many columns as the
    width holds, each as tall as the field. It holds what fits, the lines balanced
    across its columns when they all do; the ``last`` sheet a drawing may have holds
    every line left, its columns taller than the field when they must be."""
    if n <= 0:
        return Shape()
    rh = row_height(h)
    fit = max(1, int(room // rh) - 1)
    most = max(1, int(across // width))
    lines = n if last else min(n, most * fit)
    count = max(1, min(math.ceil(lines / fit), most))
    per = math.ceil(lines / count)
    count = math.ceil(lines / per)
    return Shape(count, per, width, (per + 1) * rh, lines)


def height(lines, h: float) -> float:
    """The parts list's height for ``lines`` (none: no list)."""
    return (len(lines) + 1) * row_height(h) if lines else 0.0


def cells(lines, *, capitals: bool) -> tuple[tuple[str, ...], ...]:
    """Each line's cells, one a column of :data:`COLUMNS` (or, for lines the BOM editor
    set, their own cells), in capitals when ``capitals``."""
    out = []
    for line in lines:
        row = line.cells or (line.item, line.part_number, line.drawing, line.description, str(line.quantity))
        out.append(tuple(c.upper() for c in row) if capitals else row)
    return tuple(out)


def widths(rows, width: float, h: float, columns=COLUMNS, narrow=None) -> tuple[float, ...]:
    """The columns' widths across ``width``: the ``narrow`` ones (by default ITEM and
    QTY.) as wide as their headings, the others their headings and a share of the
    rest by what they hold; when everything fits, the last wide column (DESCRIPTION
    by default) takes what is left."""

    def wide(text: str, bold: bool = False) -> float:
        return text_width(text, h, bold) + 2 * PAD + SLACK

    narrow = set((0, len(columns) - 1) if narrow is None else narrow)
    fixed = {k: wide(columns[k], True) for k in narrow}
    middle = [k for k in range(len(columns)) if k not in narrow]
    heads = [wide(columns[k], True) for k in middle]
    needs = [max(hd, max([wide(r[k]) for r in rows] or [0.0])) for hd, k in zip(heads, middle, strict=True)]
    extra = max(0.0, width - plain_sum(fixed.values())) - plain_sum(heads)
    want = plain_sum(n - hd for n, hd in zip(needs, heads, strict=True))
    if extra >= want:
        out = list(needs)
        if out:
            out[-1] += extra - want
    else:  # each its heading, and a share of what is left by what it lacks
        share = max(0.0, extra) / want
        out = [hd + (n - hd) * share for hd, n in zip(heads, needs, strict=True)]
    given = dict(zip(middle, out, strict=True))
    return tuple(fixed[k] if k in fixed else given[k] for k in range(len(columns)))


def parts_list(pen: Pen, box: Box, rows, h: float, columns=COLUMNS, narrow=None, per_column=None) -> list:
    """The parts list in ``box`` (see the module notes): its strokes and text on the
    painted layer, and its annotations, one a column. ``columns`` are the headings and
    ``narrow`` the columns as wide as their headings, centred (by default the first and
    last); with ``per_column`` the lines go that many a column, the first at the right
    of ``box``, the next to its left."""
    if not rows:
        return []
    per = per_column or len(rows)
    chunks = [rows[i : i + per] for i in range(0, len(rows), per)]
    if len(chunks) > 1:
        width = box.width / len(chunks)
        out = []
        for j, chunk in enumerate(chunks):
            x1 = box.x1 - j * width
            col = Box(x1 - width, box.y0, x1, box.y0 + (len(chunk) + 1) * row_height(h))
            out += parts_list(pen, col, chunk, h, columns, narrow)
        return out
    narrow = (0, len(columns) - 1) if narrow is None else tuple(narrow)
    rh = row_height(h)
    ws = widths(rows, box.width, h, columns, narrow)
    xs = [box.x0]
    for w in ws:
        xs.append(xs[-1] + w)
    xs[-1] = box.x1
    pen.rect(box, width=THICK, layer="title", owner=OWNER)
    for k in range(1, len(rows) + 1):
        y = box.y0 + k * rh
        pen.line((box.x0, y), (box.x1, y), width=THICK if k == 1 else THIN, layer="title", owner=OWNER)
    for x in xs[1:-1]:
        pen.line((x, box.y0), (x, box.y1), width=THIN, layer="title", owner=OWNER)

    def put(k: int, y0: float, text: str, bold: bool) -> None:
        room = xs[k + 1] - xs[k] - 2 * PAD
        shown = _cut(text, room, h, bold)
        y = y0 + (rh - h) / 2
        if k in narrow:
            pen.text(
                (xs[k] + xs[k + 1]) / 2, y, h, shown, bold=bold, anchor="centre", layer="title", owner=OWNER
            )
        else:
            pen.text(xs[k] + PAD, y, h, shown, bold=bold, layer="title", owner=OWNER)

    for k, head in enumerate(columns):
        put(k, box.y0, head, True)
    for n, row in enumerate(rows, 1):
        for k, text in enumerate(row):
            if text:
                put(k, box.y0 + n * rh, text, False)
    return [D.PartsList((box.x0, box.y0), box.width, box.height, tuple(columns), tuple(rows))]


def radius(item: str, h: float) -> float:
    """A balloon's radius round ``item`` at text height ``h``."""
    return max(1.25 * h, text_width(item, h) / 2 + 0.4 * h)


def _exit(a, u, box: Box) -> float:
    """How far from ``a`` (inside or on ``box``) along unit ``u`` the box ends."""
    t = math.inf
    for k, lo, hi in ((0, box.x0, box.x1), (1, box.y0, box.y1)):
        if u[k] > 1e-12:
            t = min(t, (hi - a[k]) / u[k])
        elif u[k] < -1e-12:
            t = min(t, (lo - a[k]) / u[k])
    return max(0.0, t)


def _turn(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def place_balloon(
    index: Index, area: Box, view: Box, anchor, r: float, angles, owner: str, blockers=(HARD, DIMLINE)
) -> tuple[tuple[float, float], tuple[float, float], bool]:
    """Where a balloon goes: its centre, the leader's end on its circle, and whether
    the place is clear (see the module notes): the circle clear of ``blockers`` in
    ``index``, the leader crossing no hard item or leader. When none is, the first
    place on the sheet, reported by the caller."""
    cx, cy = view.centre()
    out = (
        math.degrees(math.atan2(anchor[1] - cy, anchor[0] - cx))
        if (anchor[0], anchor[1]) != (cx, cy)
        else 45.0
    )
    grown = view.grow(CLEAR)
    best = None
    first = None
    for ang in sorted(angles, key=lambda a: (_turn(a, out), a)):
        u = (math.cos(math.radians(ang)), math.sin(math.radians(ang)))
        t0 = _exit(anchor, u, grown)
        for reach in REACH:
            d = t0 + reach + r
            c = (anchor[0] + u[0] * d, anchor[1] + u[1] * d)
            end = (c[0] - u[0] * r, c[1] - u[1] * r)
            circle = Box(c[0] - r, c[1] - r, c[0] + r, c[1] + r)
            if first is None and circle.inside(area):
                first = (c, end)
            if not circle.inside(area) or index.hits(circle, blockers, pad=1.0):
                continue
            if index.crosses(anchor, end, kinds=(HARD, DIMLINE), ignore=owner):
                continue
            cost = d + TURN * _turn(ang, out)
            if best is None or cost < best[0]:
                best = (cost, c, end)
            break  # a longer leader in this direction costs more
    if best is not None:
        return best[1], best[2], True
    if first is not None:
        return first[0], first[1], False
    u = (math.cos(math.radians(45.0)), math.sin(math.radians(45.0)))
    d = _exit(anchor, u, grown) + REACH[0] + r
    c = (anchor[0] + u[0] * d, anchor[1] + u[1] * d)
    return c, (c[0] - u[0] * r, c[1] - u[1] * r), False


def moved_balloon(
    index: Index, area: Box, anchor, offset, r: float, owner: str, blockers=(HARD, DIMLINE)
) -> tuple[tuple[float, float], tuple[float, float], bool]:
    """A balloon the user moved: its centre ``offset`` (paper millimetres) from the point
    its leader ends on, at least a little more than its radius away, and the leader's end
    on its circle; whether the place is clear as :func:`place_balloon` judges one."""
    dx, dy = offset
    d = math.hypot(dx, dy)
    least = r + REACH[0]
    if d < least:  # too close to show a leader: pushed out along the same direction
        u = (dx / d, dy / d) if d > 1e-9 else (math.cos(math.radians(45.0)), math.sin(math.radians(45.0)))
        dx, dy, d = u[0] * least, u[1] * least, least
    c = (anchor[0] + dx, anchor[1] + dy)
    u = (dx / d, dy / d)
    end = (c[0] - u[0] * r, c[1] - u[1] * r)
    circle = Box(c[0] - r, c[1] - r, c[0] + r, c[1] + r)
    clear = (
        circle.inside(area)
        and not index.hits(circle, blockers, pad=1.0)
        and not index.crosses(anchor, end, kinds=(HARD, DIMLINE), ignore=owner)
    )
    return c, end, clear


STACK_REACH = 20.0  # millimetres: a balloon stacks on another whose part's point is this near


def stacked_balloon(index: Index, area: Box, partner, anchor, r: float, owner: str, blockers=(HARD, DIMLINE)):
    """Where a balloon that found no clear place of its own stacks on ``partner`` (a placed
    :class:`~solidseas.drawing.display.Balloon` whose leader ends within
    :data:`STACK_REACH` of ``anchor``), as ASME Y14.34 allows for items that sit together:
    touching it, beyond it along its leader, then to either side; its centre, or None when
    none of those is clear. A stacked balloon has no leader of its own."""
    if (
        not partner.leader
        or math.hypot(partner.leader[0][0] - anchor[0], partner.leader[0][1] - anchor[1]) > STACK_REACH
    ):
        return None
    cx, cy = partner.centre
    ax, ay = partner.leader[0]
    d = math.hypot(cx - ax, cy - ay) or 1.0
    u = ((cx - ax) / d, (cy - ay) / d)
    gap = partner.radius + r
    for v in (u, (-u[1], u[0]), (u[1], -u[0])):
        c = (cx + v[0] * gap, cy + v[1] * gap)
        circle = Box(c[0] - r, c[1] - r, c[0] + r, c[1] + r)
        # its partner's square box overlaps the touching circle's: the partner is not in the way
        clear = not index.hits(circle, blockers, pad=0.5, ignore=f"balloon-{partner.item}")
        if circle.inside(area) and clear:
            return c
    return None


def paint_balloon(pen: Pen, item: str, centre, end, anchor, r: float, h: float, view: str, owner: str):
    """A balloon, its leader and arrowhead; its annotation. With ``end`` None it is
    stacked on another (:func:`stacked_balloon`): no leader, and its annotation's leader
    holds only the point on its part."""
    pen.circle(centre, r, width=THIN, layer="notes", owner=owner)
    pen.text(centre[0], centre[1] - h / 2, h, item, anchor="centre", layer="notes", owner=owner)
    if end is None:
        return D.Balloon(item, centre, r, (anchor,), view)
    d = (anchor[0] - end[0], anchor[1] - end[1])
    n = math.hypot(*d) or 1.0
    tail = (anchor[0] - d[0] / n * h, anchor[1] - d[1] / n * h)
    pen.line(end, tail, width=THIN, layer="notes", owner=owner)
    pen.arrow(anchor, d, h, layer="notes", owner=owner)
    return D.Balloon(item, centre, r, (anchor, end), view)


__all__ = [
    "COLUMNS",
    "Shape",
    "cells",
    "continued",
    "height",
    "paint_balloon",
    "parts_list",
    "place_balloon",
    "stacked_balloon",
    "radius",
    "row_height",
    "shape",
    "widths",
]
