"""2D cleanup of a view's runs (``docs/DRAWINGS.md`` 8.4 step 5).

Pieces shorter than 0.02 % of the diagonal are dropped, and so is any piece
lying within that distance of, and parallel within 3 degrees to, a kept piece of
higher rank (visible before hidden, edges before silhouettes, longer before
shorter). That removes back
edges that project onto front edges, the edges of faces seen edge-on, hidden
lines under visible ones, and the far rim of a through hole seen along its axis.
A piece is dropped only when every one of its segments is covered, so a circle
is kept or dropped whole. Pieces given as ``under`` stand for the runs an earlier
cleanup kept: they are in place before any other, so a piece added to a view
later is dropped where it lies along one of them.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from ..numbers import plain_sum

SHORT_FRACTION = 2e-4
PARALLEL_DEG = 3.0
CELL_FACTOR = 8.0  # grid cells this many tolerances wide
LENGTH_PLACES = 9  # a piece's length in metres, compared to this many places when ordering


@dataclass
class Piece:
    """A run before it becomes a display primitive: its 2D points, whether visible,
    whether it comes from an edge or a silhouette, and what made it."""

    points: list
    visible: bool
    kind: str  # edge or silhouette
    payload: object = None
    curved: bool = False
    rank_extra: int = 0
    segs: list = field(default_factory=list)


def _dist_seg(p, a, b) -> float:
    ab = (b[0] - a[0], b[1] - a[1])
    l2 = ab[0] * ab[0] + ab[1] * ab[1]
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / l2))
    return math.dist(p, (a[0] + ab[0] * t, a[1] + ab[1] * t))


def length(points) -> float:
    return plain_sum(math.dist(a, b) for a, b in zip(points, points[1:], strict=False))


def rank(piece: Piece) -> tuple:
    """Where a piece stands in the cleanup order: visible before hidden, edges before
    silhouettes, then longer before shorter, so a whole circle is kept and the short
    pieces of another lying under it go. The length is compared to the nanometre
    (:data:`LENGTH_PLACES`): pieces equal by symmetry, such as a cone's two silhouette
    lines, differ only in their last bits, which differ between platforms' sine and
    cosine, so they keep the order they came in on every machine."""
    return (
        not piece.visible,
        piece.kind != "edge",
        piece.rank_extra,
        -round(length(piece.points), LENGTH_PLACES),
    )


def cleanup(pieces: list[Piece], diagonal: float, *, under: Sequence[Piece] = ()) -> list[Piece]:
    eps = SHORT_FRACTION * diagonal
    cos_p = math.cos(math.radians(PARALLEL_DEG))
    cell = max(eps * CELL_FACTOR, 1e-12)
    grid: dict[tuple[int, int], list] = {}

    def cells(a, b):
        i0, i1 = sorted((int(math.floor(a[0] / cell)), int(math.floor(b[0] / cell))))
        j0, j1 = sorted((int(math.floor(a[1] / cell)), int(math.floor(b[1] / cell))))
        for i in range(i0 - 1, i1 + 2):
            for j in range(j0 - 1, j1 + 2):
                yield (i, j)

    def near(p, ab, lab) -> bool:
        """Whether a kept segment parallel to ``ab`` passes within the tolerance of ``p``."""
        for key in cells(p, p):
            for c, e in grid.get(key, ()):
                ce = (e[0] - c[0], e[1] - c[1])
                lce = math.hypot(*ce)
                # a piece shorter than the tolerance has no direction worth comparing
                if lce == 0 or (lab > eps and abs(ab[0] * ce[0] + ab[1] * ce[1]) / (lab * lce) < cos_p):
                    continue
                if _dist_seg(p, c, e) <= eps:
                    return True
        return False

    def covered(a, b) -> bool:
        """Whether the segment ab lies along kept pieces: its ends and middle each near
        one, so a segment straddling two kept samples counts."""
        ab = (b[0] - a[0], b[1] - a[1])
        lab = math.hypot(*ab)
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        return near(a, ab, lab) and near(b, ab, lab) and near(mid, ab, lab)

    def add(a, b) -> None:
        for key in cells(a, b):
            grid.setdefault(key, []).append((a, b))

    for piece in under:
        for a, b in zip(piece.points, piece.points[1:], strict=False):
            # a long straight run in short steps, so each step fills only the cells near it
            n = max(1, math.ceil(math.dist(a, b) / cell))
            steps = [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n + 1)]
            for p, q in zip(steps, steps[1:], strict=False):
                add(p, q)
    kept = []
    order = sorted(pieces, key=rank)
    for piece in order:
        pts = piece.points
        if len(pts) < 2 or length(pts) < eps:
            continue
        pairs = list(zip(pts, pts[1:], strict=False))
        if all(covered(a, b) for a, b in pairs):
            continue
        kept.append(piece)
        for a, b in pairs:
            add(a, b)
    return kept


__all__ = ["Piece", "cleanup", "length", "rank"]
