"""The drawings the chat gets: the outlines a trace found, numbered, and a bin's layout from
above. Both are made from outlines alone, never from a photo."""

from __future__ import annotations

from collections.abc import Sequence

from .layout import BIN_GAP, GRID, Layout, inset
from .png import Canvas, View, scale_bar

Point = tuple[float, float]
Rings = Sequence[Sequence[Point]]  # an outline and the rings inside it

PAPER = (247, 246, 241)
INK = (40, 44, 52)
TOOL = (74, 96, 128)
BIN = (226, 226, 220)
CELL = (200, 200, 192)
POCKET_EDGE = (40, 52, 70)
SCOOP = (140, 160, 190)
LABEL = (255, 255, 255)
TEXT = (232, 196, 120)


def trace_drawing(outlines: Sequence[Rings]) -> bytes:
    """The outlines, in mm as traced, numbered from 1 in the order given."""
    points = [p for rings in outlines for p in rings[0]]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    pad = 8.0
    view = View((min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad))
    canvas = Canvas(view.width, view.height, PAPER)
    for rings in outlines:
        canvas.polygon([view(r) for r in rings], TOOL)
    for number, rings in enumerate(outlines, start=1):
        x0, y0 = min(p[0] for p in rings[0]), min(p[1] for p in rings[0])
        x1, y1 = max(p[0] for p in rings[0]), max(p[1] for p in rings[0])
        canvas.label(view.at(((x0 + x1) / 2, (y0 + y1) / 2)), str(number), ink=INK, paper=LABEL, scale=3)
    scale_bar(canvas, view, INK)
    return canvas.png()


def bin_drawing(
    layout: Layout,
    pockets: Sequence[Rings],
    scoops: Sequence[Sequence[tuple[float, float, float]]],
    *,
    stacking_lip: bool,
    height_units: int,
    labels: Sequence[Sequence[Point]] = (),
) -> bytes:
    """The bin from above: its cells, where the pockets may go, each tool's pocket and
    finger scoops where the layout put them, numbered as the tools were given, and the room
    each text label takes (``labels``, the corners of each)."""
    across, deep = layout.grid
    width, depth = across * GRID, deep * GRID
    view = View((0.0, 0.0, width, depth))
    canvas = Canvas(view.width, view.height, PAPER)
    edge = BIN_GAP / 2
    canvas.polygon(
        [view([(edge, edge), (width - edge, edge), (width - edge, depth - edge), (edge, depth - edge)])], BIN
    )
    k = 1
    while k * GRID < width - 1e-6:
        canvas.line(view.at((k * GRID, edge)), view.at((k * GRID, depth - edge)), CELL, 1)
        k += 1
    k = 1
    while k * GRID < depth - 1e-6:
        canvas.line(view.at((edge, k * GRID)), view.at((width - edge, k * GRID)), CELL, 1)
        k += 1
    room = edge + inset(stacking_lip)
    canvas.outline(
        view([(room, room), (width - room, room), (width - room, depth - room), (room, depth - room)]),
        CELL,
        1,
    )
    canvas.outline(
        view([(edge, edge), (width - edge, edge), (width - edge, depth - edge), (edge, depth - edge)]), INK, 2
    )
    for holes in scoops:
        for x, y, r in holes:
            canvas.circle(view.at((x, y)), r * view.scale, SCOOP)
    for rings in pockets:
        canvas.polygon([view(r) for r in rings], TOOL)
        canvas.outline(view(rings[0]), POCKET_EDGE, 1)
    for box in labels:
        canvas.polygon([view(box)], TEXT)
        canvas.outline(view(box), INK, 1)
    for placement in layout.placements:
        x0, y0, x1, y1 = placement.box
        canvas.label(
            view.at(((x0 + x1) / 2, (y0 + y1) / 2)), str(placement.index + 1), ink=INK, paper=LABEL, scale=2
        )
    scale_bar(canvas, view, INK, f"{across:g}x{deep:g}x{height_units}")
    return canvas.png()


__all__ = ["bin_drawing", "trace_drawing"]
