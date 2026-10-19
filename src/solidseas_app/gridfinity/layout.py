"""Laying tools out in a Gridfinity bin, and where a tool's finger scoop goes.

A tool is its outline in mm, y down, as Tracefinity keeps it, with its finger holes. Each
tool is turned so its smallest bounding rectangle is square to the bin; the rectangles,
grown by the pocket clearance, are packed in shelves (tallest first, each into the first
shelf it fits), and the smallest bin they fit in is kept, fewest grid cells first, then the
squarest. A tool may lie along the bin's width or its depth.

A tool's place is given the way Tracefinity's bin editor rebuilds it
(``sync_placed_tools``): the library outline turned by ``rotation`` degrees about the mean
of its vertices, that mean landing on the placed position, and the finger holes moved with
it. So the bin is the same when the person opens it in Tracefinity.

The numbers follow Tracefinity 0.10's generator: 42 mm grid units, 7 mm height units, a
bin 0.5 mm smaller than its cells, pockets kept clear of the wall or stacking lip, and
4.75 mm of base and 2 mm of floor under the deepest pocket.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

Point = tuple[float, float]

GRID = 42.0  # mm in one grid unit
HEIGHT_UNIT = 7.0  # mm in one height unit
BIN_GAP = 0.5  # a bin is this much smaller than its cells
BASE = 4.75  # mm of base under the bin's floor
FLOOR = 2.0  # mm Tracefinity keeps under a pocket
LIP_REACH = 2.6  # how far the stacking lip reaches in from the outside
WALL = 1.6  # Tracefinity's wall
MAX_UNITS = 25.0
MAX_CELLS = 100
MAX_HEIGHT_UNITS = 20

SCOOP_REACH = 6.0  # mm a scoop across a tool reaches past each side of it
SCOOP_MIN, SCOOP_MAX = 10.0, 20.0  # a scoop's radius across a tool
NARROW = 14.0  # a tool at most twice this wide at its middle gets its scoop across it
EDGE_SCOOP = 12.0  # the radius of a scoop at the edge of a wider tool
_EPS = 1e-9


class LayoutError(ValueError):
    """The tools do not fit as asked: said to the chat as it is."""


@dataclass(frozen=True)
class Hole:
    """A finger hole as a circle: its centre and radius in the tool's mm."""

    x: float
    y: float
    radius: float


@dataclass(frozen=True)
class Shape:
    """A tool for the layout: its outline and its finger holes, in its own mm."""

    points: tuple[Point, ...]
    holes: tuple[Hole, ...] = ()


@dataclass(frozen=True)
class Placement:
    """Where one tool goes: ``rotation`` in degrees as Tracefinity turns it, ``centre``
    where its outline's vertex mean lands, and ``box`` the pocket's extent with its
    clearance (x0, y0, x1, y1), all in the bin's mm (x from its left, y from its back)."""

    index: int
    rotation: float
    centre: Point
    box: tuple[float, float, float, float]


@dataclass(frozen=True)
class Layout:
    grid: tuple[float, float]
    placements: tuple[Placement, ...]


# ----------------------------------------------------------------- geometry
def mean(points: Sequence[Point]) -> Point:
    n = len(points)
    return (sum(p[0] for p in points) / n, sum(p[1] for p in points) / n)


def turn(points: Iterable[Point], degrees: float, about: Point = (0.0, 0.0)) -> list[Point]:
    """Points turned about ``about``, exactly as Tracefinity turns a placed tool."""
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    ox, oy = about
    return [((x - ox) * c - (y - oy) * s, (x - ox) * s + (y - oy) * c) for x, y in points]


def extent(points: Iterable[Point]) -> tuple[float, float, float, float]:
    xs, ys = zip(*points, strict=True)
    return min(xs), min(ys), max(xs), max(ys)


def area(points: Sequence[Point]) -> float:
    n = len(points)
    return (
        abs(
            sum(
                points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1]
                for i in range(n)
            )
        )
        / 2
    )


def hull(points: Iterable[Point]) -> list[Point]:
    """The convex hull, counterclockwise in y-up terms (Andrew's monotone chain)."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o: Point, a: Point, b: Point) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[Point] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[Point] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def long_side_angle(points: Sequence[Point]) -> float:
    """Degrees, in (-90, 90], that turn the outline's smallest bounding rectangle square to
    the axes with its long side along x."""
    shell = hull(points)
    if len(shell) < 3:
        return 0.0
    best: tuple[float, float, float] | None = None  # area, |angle|, angle
    for i in range(len(shell)):
        (x1, y1), (x2, y2) = shell[i], shell[(i + 1) % len(shell)]
        if x1 == x2 and y1 == y2:
            continue
        angle = -math.degrees(math.atan2(y2 - y1, x2 - x1))
        x0, y0, xe, ye = extent(turn(shell, angle))
        if xe - x0 < ye - y0:
            angle += 90.0
            x0, y0, xe, ye = y0, x0, ye, xe
        angle = _half_turn(angle)
        candidate = ((xe - x0) * (ye - y0), abs(angle), angle)
        if (
            best is None
            or candidate[0] < best[0] - 1e-6
            or (abs(candidate[0] - best[0]) <= 1e-6 and candidate[1] < best[1])
        ):
            best = candidate
    return 0.0 if best is None else round(best[2], 4)


def _half_turn(angle: float) -> float:
    """The same rectangle's turn in (-90, 90]."""
    angle = math.fmod(angle, 180.0)
    if angle <= -90.0:
        angle += 180.0
    elif angle > 90.0:
        angle -= 180.0
    return angle


def size(points: Sequence[Point]) -> tuple[float, float]:
    """Length and width of the outline's smallest bounding rectangle, in its units."""
    x0, y0, x1, y1 = extent(turn(points, long_side_angle(points)))
    return x1 - x0, y1 - y0


def _crossings(points: Sequence[Point], x: float) -> list[float]:
    ys = []
    n = len(points)
    for i in range(n):
        (x1, y1), (x2, y2) = points[i], points[(i + 1) % n]
        if (x1 <= x < x2) or (x2 <= x < x1):
            ys.append(y1 + (x - x1) * (y2 - y1) / (x2 - x1))
    return ys


def finger_scoop(points: Sequence[Point]) -> Hole:
    """Where a round finger scoop goes on a tool, in its own mm: across the middle of its
    length, reaching :data:`SCOOP_REACH` past each side, when the tool is narrow there;
    otherwise half over one long edge, at the middle."""
    centre = mean(points)
    angle = long_side_angle(points)
    turned = turn(points, angle, centre)
    x0, y0, x1, y1 = extent(turned)
    mid = (x0 + x1) / 2
    ys = _crossings(turned, mid) or [y0, y1]
    low, high = min(ys), max(ys)
    half = (high - low) / 2
    if half <= NARROW:
        at, radius = (mid, (low + high) / 2), min(SCOOP_MAX, max(SCOOP_MIN, half + SCOOP_REACH))
    else:
        at, radius = (mid, high), EDGE_SCOOP
    bx, by = turn([at], -angle)[0]
    return Hole(round(bx + centre[0], 3), round(by + centre[1], 3), radius)


# ----------------------------------------------------------------- bins
def inset(stacking_lip: bool, wall: float = WALL) -> float:
    """How far the pockets stay in from the outside of the bin."""
    return max(wall, LIP_REACH if stacking_lip else 0.0)


def interior(units: float, inset_mm: float) -> float:
    """The room for pockets across ``units`` grid units."""
    return units * GRID - BIN_GAP - 2 * inset_mm


def units_for(length: float, inset_mm: float, half: bool) -> float:
    """The fewest grid units (whole, or halves with a half-grid base) with room for ``length``."""
    step = 0.5 if half else 1.0
    units = math.ceil((length + BIN_GAP + 2 * inset_mm) / (GRID * step) - _EPS) * step
    return max(1.0, units)


def max_depth(height_units: int) -> float:
    """The deepest pocket a bin of ``height_units`` holds."""
    return height_units * HEIGHT_UNIT - BASE - FLOOR


def height_units_for(depth: float) -> int:
    """The fewest height units for pockets ``depth`` mm deep (two at least)."""
    return max(2, math.ceil((depth + BASE + FLOOR) / HEIGHT_UNIT - _EPS))


def _footprint(shape: Shape, rotation: float) -> tuple[float, float, float, float]:
    """The extent of the turned tool and its finger holes, about its vertex mean."""
    centre = mean(shape.points)
    turned = turn(shape.points, rotation, centre)
    x0, y0, x1, y1 = extent(turned)
    for hole, (hx, hy) in zip(
        shape.holes, turn([(h.x, h.y) for h in shape.holes], rotation, centre), strict=True
    ):
        x0, y0 = min(x0, hx - hole.radius), min(y0, hy - hole.radius)
        x1, y1 = max(x1, hx + hole.radius), max(y1, hy + hole.radius)
    return x0, y0, x1, y1


@dataclass(frozen=True)
class _Item:
    index: int
    rotation: float
    foot: tuple[float, float, float, float]
    width: float  # with the clearance
    depth: float


def _shelves(items: list[_Item], room: float, gap: float) -> list[list[_Item]] | None:
    """First fit, tallest first; None if an item is wider than the room."""
    shelves: list[list[_Item]] = []
    used: list[float] = []
    for item in sorted(items, key=lambda it: (-it.depth, -it.width, it.index)):
        if item.width > room + _EPS:
            return None
        for k, shelf in enumerate(shelves):
            if used[k] + gap + item.width <= room + _EPS:
                shelf.append(item)
                used[k] += gap + item.width
                break
        else:
            shelves.append([item])
            used.append(item.width)
    return shelves


def _block(shelves: list[list[_Item]], gap: float) -> tuple[float, float]:
    width = max(sum(it.width for it in s) + gap * (len(s) - 1) for s in shelves)
    depth = sum(max(it.depth for it in s) for s in shelves) + gap * (len(shelves) - 1)
    return width, depth


def lay_out(
    shapes: Sequence[Shape],
    *,
    clearance: float,
    gap: float,
    stacking_lip: bool,
    grid: tuple[float, float] | None = None,
    half: bool = False,
    reserve: float = 0.0,
    min_across: float = 1.0,
) -> Layout:
    """Place every shape in the smallest bin it fits, at least ``min_across`` units across,
    or in ``grid`` (units across, units deep), keeping a strip ``reserve`` mm deep free of
    pockets along the back edge (for a label); raises :class:`LayoutError` when they do not
    fit."""
    if not shapes:
        raise LayoutError("A bin needs at least one tool.")
    pad = inset(stacking_lip)
    options: list[tuple[_Item, _Item]] = []
    for i, shape in enumerate(shapes):
        along = long_side_angle(shape.points)
        pair = []
        for rotation in (along, _half_turn(along + 90.0)):
            foot = _footprint(shape, rotation)
            pair.append(
                _Item(i, rotation, foot, foot[2] - foot[0] + 2 * clearance, foot[3] - foot[1] + 2 * clearance)
            )
        options.append((pair[0], pair[1]))

    def arrangements(room: float) -> Iterable[list[list[_Item]]]:
        for pick in ("across", "deep", "fit"):
            if pick == "across":
                items = [a for a, _ in options]
            elif pick == "deep":
                items = [b for _, b in options]
            else:
                items = [a if a.width <= room + _EPS else b for a, b in options]
            shelves = _shelves(items, room, gap)
            if shelves is not None:
                yield shelves

    def best_for(
        across_units: float, deep_units: float | None
    ) -> tuple[tuple, list[list[_Item]], float] | None:
        room = interior(across_units, pad)
        found = None
        for shelves in arrangements(room):
            _, depth = _block(shelves, gap)
            deep = deep_units if deep_units is not None else units_for(depth + reserve, pad, half)
            if depth + reserve > interior(deep, pad) + _EPS or deep > MAX_UNITS:
                continue
            if math.ceil(across_units) * math.ceil(deep) > MAX_CELLS:
                continue
            cost = (across_units * deep, max(across_units, deep), deep, depth)
            if found is None or cost < found[0]:
                found = (cost, shelves, deep)
        return found

    step = 0.5 if half else 1.0
    if grid is not None:
        chosen = best_for(grid[0], grid[1])
        if chosen is None:
            smallest = _smallest(best_for, step)
            hint = (
                f" The smallest bin they fit is {_units(smallest[0])} x {_units(smallest[2])}."
                if smallest
                else ""
            )
            raise LayoutError(f"The tools do not fit in a {_units(grid[0])} x {_units(grid[1])} bin.{hint}")
        across, (_, shelves, deep) = grid[0], chosen
    else:
        smallest = _smallest(best_for, step, min_across)
        if smallest is None:
            raise LayoutError(
                f"The tools do not fit in any bin up to {_units(MAX_UNITS)} units a side "
                f"and {MAX_CELLS} cells."
            )
        across, _, deep, shelves = smallest
    return _place(shelves, across, deep, gap, clearance, reserve)


def _smallest(
    best_for, step: float, start: float = 1.0
) -> tuple[float, tuple, float, list[list[_Item]]] | None:
    found = None
    across = max(1.0, math.ceil(start / step - _EPS) * step)
    while across <= MAX_UNITS + _EPS:
        chosen = best_for(across, None)
        if chosen is not None and (found is None or chosen[0] < found[1]):
            found = (across, chosen[0], chosen[2], chosen[1])
        across += step
    return found


def _place(
    shelves: list[list[_Item]], across: float, deep: float, gap: float, clearance: float, reserve: float = 0.0
) -> Layout:
    width, depth = _block(shelves, gap)
    left0 = (across * GRID - width) / 2
    top = (deep * GRID - depth - reserve) / 2 + reserve
    placements = []
    for shelf in shelves:
        tall = max(it.depth for it in shelf)
        used = sum(it.width for it in shelf) + gap * (len(shelf) - 1)
        left = left0 + (width - used) / 2
        for item in shelf:
            y = top + (tall - item.depth) / 2
            fx0, fy0, _, _ = item.foot
            centre = (round(left + clearance - fx0, 4), round(y + clearance - fy0, 4))
            box = (left, y, left + item.width, y + item.depth)
            placements.append(Placement(item.index, item.rotation, centre, tuple(round(v, 4) for v in box)))
            left += item.width + gap
        top += tall + gap
    placements.sort(key=lambda p: p.index)
    return Layout((across, deep), tuple(placements))


def _units(value: float) -> str:
    return f"{value:g}"


def placed_points(points: Sequence[Point], placement: Placement) -> list[Point]:
    """A library outline (or ring, or hole centres) where ``placement`` puts it: turned
    about the outline's vertex mean, which lands on the placement's centre."""
    return placed_about(points, mean(points), placement)


def placed_about(points: Iterable[Point], about: Point, placement: Placement) -> list[Point]:
    cx, cy = placement.centre
    return [(round(cx + x, 4), round(cy + y, 4)) for x, y in turn(points, placement.rotation, about)]


__all__ = [
    "GRID",
    "HEIGHT_UNIT",
    "Hole",
    "Layout",
    "LayoutError",
    "Placement",
    "Shape",
    "area",
    "finger_scoop",
    "height_units_for",
    "inset",
    "interior",
    "lay_out",
    "long_side_angle",
    "max_depth",
    "mean",
    "placed_about",
    "placed_points",
    "size",
    "turn",
    "units_for",
]
