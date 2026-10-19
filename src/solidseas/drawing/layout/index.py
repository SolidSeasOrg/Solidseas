"""The spatial index layout places against (``docs/DRAWINGS.md`` 11.3, C21).

Three kinds of obstacle: **hard** ones (views, reserved areas, texts, callouts,
frames), which nothing may overlap; **dimension lines**, which no leader may cross;
and **extension lines**, which leaders may cross and datum symbols may not. Boxes
are binned in a grid of fixed cells, so a query looks at the few cells it touches.
Coordinates are sheet millimetres.
"""

from __future__ import annotations

from dataclasses import dataclass

HARD, DIMLINE, EXTLINE = "hard", "dimline", "extline"
CELL = 10.0
# A box or segment over more cells than this (or with a coordinate that is not finite) is
# kept apart and looked at by every query instead of binned, and a query that large looks
# at everything: binning cell by cell must never cost more than the sheet does.
MAX_CELLS = 4096


def _cells(box: Box) -> int | None:
    """How many cells ``box`` covers; None when more than :data:`MAX_CELLS` or not finite."""
    try:
        n = (int(box.x1 // CELL) - int(box.x0 // CELL) + 1) * (int(box.y1 // CELL) - int(box.y0 // CELL) + 1)
    except (OverflowError, ValueError):
        return None
    return n if n <= MAX_CELLS else None


@dataclass(frozen=True)
class Box:
    x0: float
    y0: float
    x1: float
    y1: float

    @staticmethod
    def around(points, pad: float = 0.0) -> Box:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return Box(min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)

    def grow(self, d: float) -> Box:
        return Box(self.x0 - d, self.y0 - d, self.x1 + d, self.y1 + d)

    def hits(self, o: Box, pad: float = 0.0) -> bool:
        return not (
            o.x0 >= self.x1 + pad or o.x1 <= self.x0 - pad or o.y0 >= self.y1 + pad or o.y1 <= self.y0 - pad
        )

    def inside(self, o: Box) -> bool:
        """Whether this box lies within ``o``."""
        return self.x0 >= o.x0 and self.y0 >= o.y0 and self.x1 <= o.x1 and self.y1 <= o.y1

    def union(self, o: Box) -> Box:
        return Box(min(self.x0, o.x0), min(self.y0, o.y0), max(self.x1, o.x1), max(self.y1, o.y1))

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    def centre(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)


def _segment_hits_box(a, b, box: Box) -> bool:
    """Whether the segment from ``a`` to ``b`` passes through ``box`` (Liang-Barsky)."""
    x0, y0 = a
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - box.x0), (dx, box.x1 - x0), (-dy, y0 - box.y0), (dy, box.y1 - y0)):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            if t > t1:
                return False
            t0 = max(t0, t)
        else:
            if t < t0:
                return False
            t1 = min(t1, t)
    return t0 < t1


def _cross(o, a, b) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def segments_cross(a, b, c, d) -> bool:
    """Whether segment ``a``-``b`` crosses segment ``c``-``d`` (touching ends excepted)."""
    d1, d2 = _cross(c, d, a), _cross(c, d, b)
    d3, d4 = _cross(a, b, c), _cross(a, b, d)
    return (d1 > 1e-9 and d2 < -1e-9 or d1 < -1e-9 and d2 > 1e-9) and (
        d3 > 1e-9 and d4 < -1e-9 or d3 < -1e-9 and d4 > 1e-9
    )


class Index:
    """Boxes and segments by kind, binned by cell."""

    def __init__(self) -> None:
        self.items: list[tuple[str, Box, str]] = []
        self.cells: dict[tuple[int, int], list[int]] = {}
        self.big: list[int] = []  # items over MAX_CELLS cells, which every query looks at
        self.segments: list[tuple[str, tuple, tuple, str]] = []
        self.seg_cells: dict[tuple[int, int], list[int]] = {}
        self.big_segments: list[int] = []

    def add_segment(self, kind: str, a, b, owner: str = "") -> None:
        """A leader or line that others may not cross (``kind`` as for boxes)."""
        k = len(self.segments)
        self.segments.append((kind, tuple(a), tuple(b), owner))
        box = Box.around((a, b))
        if _cells(box) is None:
            self.big_segments.append(k)
            return
        for key in self._keys(box):
            self.seg_cells.setdefault(key, []).append(k)

    def mark(self) -> tuple[int, int]:
        """How much the index holds now, for :meth:`rewind` to go back to."""
        return len(self.items), len(self.segments)

    def rewind(self, mark: tuple[int, int]) -> tuple[list, list]:
        """Take out every box and segment added since ``mark``; returns them, in the
        order they were added, so that adding them again gives back the same index."""
        n_items, n_segments = mark
        items, segments = self.items[n_items:], self.segments[n_segments:]
        for _kind, box, _owner in items:
            if _cells(box) is not None:
                for key in self._keys(box):
                    cell = self.cells.get(key)
                    while cell and cell[-1] >= n_items:
                        cell.pop()
        for _kind, a, b, _owner in segments:
            box = Box.around((a, b))
            if _cells(box) is not None:
                for key in self._keys(box):
                    cell = self.seg_cells.get(key)
                    while cell and cell[-1] >= n_segments:
                        cell.pop()
        while self.big and self.big[-1] >= n_items:
            self.big.pop()
        while self.big_segments and self.big_segments[-1] >= n_segments:
            self.big_segments.pop()
        del self.items[n_items:]
        del self.segments[n_segments:]
        return items, segments

    def _keys(self, box: Box):
        for i in range(int(box.x0 // CELL), int(box.x1 // CELL) + 1):
            for j in range(int(box.y0 // CELL), int(box.y1 // CELL) + 1):
                yield (i, j)

    def add(self, kind: str, box: Box, owner: str = "") -> None:
        k = len(self.items)
        self.items.append((kind, box, owner))
        if _cells(box) is None:
            self.big.append(k)
            return
        for key in self._keys(box):
            self.cells.setdefault(key, []).append(k)

    def near(self, box: Box):
        if _cells(box) is None:  # a query this large looks at everything
            yield from self.items
            return
        seen = set(self.big)
        for k in self.big:
            yield self.items[k]
        for key in self._keys(box):
            for k in self.cells.get(key, ()):
                if k not in seen:
                    seen.add(k)
                    yield self.items[k]

    def _near_segments(self, box: Box):
        """The indices of the stored segments ``box`` may meet."""
        if _cells(box) is None:
            yield from range(len(self.segments))
            return
        seen = set(self.big_segments)
        yield from self.big_segments
        for key in self._keys(box):
            for k in self.seg_cells.get(key, ()):
                if k not in seen:
                    seen.add(k)
                    yield k

    def _ids(self, box: Box, cells: dict, big: list, count: int):
        """The stored items (or segments) in the cells ``box`` touches, an item over
        several cells as often as it is there: for a yes or no, where a repeat costs less
        than keeping them apart."""
        if _cells(box) is None:
            return range(count)
        ids = list(big)
        get = cells.get
        j0, j1 = int(box.y0 // CELL), int(box.y1 // CELL) + 1
        for i in range(int(box.x0 // CELL), int(box.x1 // CELL) + 1):
            for j in range(j0, j1):
                got = get((i, j))
                if got:
                    ids += got
        return ids

    def hits(self, box: Box, kinds=(HARD,), pad: float = 0.0, ignore: str | None = None) -> bool:
        """Whether ``box`` overlaps a stored box of one of ``kinds``."""
        probe = box.grow(pad)
        x0, y0, x1, y1 = box.x0, box.y0, box.x1, box.y1
        items = self.items
        for k in self._ids(probe, self.cells, self.big, len(items)):
            kind, b, owner = items[k]
            if (
                kind in kinds
                and (ignore is None or owner != ignore)
                and not (x0 >= b.x1 + pad or x1 <= b.x0 - pad or y0 >= b.y1 + pad or y1 <= b.y0 - pad)
            ):
                return True
        return False

    def crosses(self, a, b, kinds=(DIMLINE, HARD), ignore: str | None = None) -> bool:
        """Whether the segment ``a`` to ``b`` passes through a stored box or crosses a
        stored segment of ``kinds``."""
        probe = Box.around((a, b))
        items = self.items
        for k in self._ids(probe, self.cells, self.big, len(items)):
            kind, box, owner = items[k]
            if kind in kinds and (ignore is None or owner != ignore) and _segment_hits_box(a, b, box):
                return True
        segments = self.segments
        for k in self._ids(probe, self.seg_cells, self.big_segments, len(segments)):
            kind, c, d, owner = segments[k]
            if kind in kinds and (ignore is None or owner != ignore) and segments_cross(a, b, c, d):
                return True
        return False

    def segment_hits(self, box: Box, kinds=(DIMLINE,)) -> bool:
        """Whether a stored segment of ``kinds`` passes through ``box``."""
        segments = self.segments
        for k in self._ids(box, self.seg_cells, self.big_segments, len(segments)):
            kind, c, d, _owner = segments[k]
            if kind in kinds and _segment_hits_box(c, d, box):
                return True
        return False


__all__ = ["DIMLINE", "EXTLINE", "HARD", "Box", "Index", "segments_cross"]
