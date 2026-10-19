"""Text labels on a Gridfinity bin: a name raised from or sunk into the bin's top, along its
back edge (the lip), or into the floor of each tool's pocket.

Tracefinity draws the letters itself (``TextLabel`` in its bin, rendered in the STL and, with
the bin and the letters as two bodies, in a 3MF), so a label is what Tracefinity takes: its
text, its centre in the bin's mm, its turn, its font size (the em, in mm), raised or sunk and
how far. What SolidSeas decides is where it goes and how big it can be, and for that it needs
the text's size before Tracefinity draws it.

Tracefinity draws with the first of Arial, Liberation Sans, FreeSans and DejaVu Sans it
finds, else Pillow's own font (Aileron), whichever its container has. :data:`WIDTHS` is the
wider of DejaVu Sans and Aileron for each character, which is also wider than Arial's, so a
label measured with it is never wider on the bin than measured. The cap height asked for is
the smallest of those fonts' (0.69 em, Aileron's), so the letters are at least that tall, and
a line of text is taken as one em tall, ascenders to descenders.
"""

from __future__ import annotations

import math
import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

Point = tuple[float, float]

MIN_CAP = 4.0  # mm: the smallest capital letters that print legibly with a 0.4 mm nozzle
DEFAULT_CAP = 6.0
MAX_CAP = 20.0
DEFAULT_DEPTH = 0.6  # mm raised or sunk
MIN_DEPTH, MAX_DEPTH = 0.4, 1.5  # a pocket keeps 2 mm of floor, so a sunk label leaves 0.5 mm at least
MAX_CHARS = 40
CAP_RATIO = 0.69  # cap height over em, the smallest of Tracefinity's fonts
LINE = 1.0  # a line's height over em, ascenders to descenders
MARGIN = 1.0  # mm kept clear round a label: of a pocket, the lip, a scoop
STEP = 0.5  # mm a label's cap height shrinks by while looking for a size that fits
PLACEMENTS = ("lip", "floor")
STYLES = ("deboss", "emboss")

# Advance widths in em of the printable ASCII characters, from space to tilde.
_ADVANCES = """
    0.318 0.401 0.46 0.838 0.636 0.95 0.78 0.275 0.39 0.39 0.56 0.838
    0.318 0.361 0.318 0.337 0.636 0.636 0.636 0.636 0.636 0.636 0.636 0.636
    0.636 0.636 0.337 0.337 0.838 0.838 0.838 0.531 1.0 0.684 0.686 0.699
    0.77 0.632 0.575 0.775 0.752 0.295 0.544 0.656 0.575 0.866 0.748 0.787
    0.603 0.787 0.695 0.635 0.612 0.732 0.684 0.989 0.685 0.611 0.685 0.39
    0.337 0.39 0.838 0.5 0.5 0.613 0.635 0.55 0.635 0.615 0.352 0.635
    0.634 0.278 0.278 0.579 0.278 0.974 0.634 0.612 0.635 0.635 0.411 0.521
    0.392 0.634 0.592 0.818 0.592 0.592 0.525 0.636 0.337 0.636 0.838
"""
WIDTHS = dict(zip((chr(c) for c in range(32, 127)), map(float, _ADVANCES.split()), strict=True))


class LabelError(ValueError):
    """A label that cannot go on the bin as asked: said to the chat as it is."""


@dataclass(frozen=True)
class Label:
    """A label placed on the bin: ``centre`` in the bin's mm (x from its left, y from its
    back), ``rotation`` in degrees clockwise from reading left to right, ``cap`` the height
    of its capitals in mm, and ``box`` the corners of the room it takes, for the drawing."""

    text: str
    centre: Point
    rotation: float
    cap: float
    emboss: bool
    depth: float
    placement: str
    box: tuple[Point, ...]

    @property
    def em(self) -> float:
        return em_for(self.cap)

    def for_tracefinity(self) -> dict:
        """The label as Tracefinity keeps it in a bin (its ``TextLabel``)."""
        return {
            "id": f"solidseas-label-{uuid.uuid4()}",
            "text": self.text,
            "x": round(self.centre[0], 3),
            "y": round(self.centre[1], 3),
            "font_size": round(self.em, 3),
            "rotation": round(self.rotation, 3),
            "emboss": self.emboss,
            "depth": self.depth,
        }


def clean(text: str) -> str:
    """``text`` in the letters Tracefinity's fonts all draw: accents taken off, anything else
    outside printable ASCII left out, runs of spaces made one."""
    plain = unicodedata.normalize("NFKD", text)
    kept = "".join(c if c in WIDTHS else " " for c in plain if not unicodedata.combining(c))
    return " ".join(kept.split())[:MAX_CHARS]


def em_for(cap: float) -> float:
    """The font size (em, mm) whose capitals are at least ``cap`` mm tall."""
    return cap / CAP_RATIO


def width(text: str, cap: float) -> float:
    """How long ``text`` is at capitals ``cap`` mm tall, in mm, at most."""
    return sum(WIDTHS.get(c, 1.0) for c in text) * em_for(cap)


def line(cap: float) -> float:
    """How tall a line of text is at capitals ``cap`` mm tall, in mm."""
    return LINE * em_for(cap)


def sizes(cap: float) -> list[float]:
    """The cap heights to try, ``cap`` first, shrinking to :data:`MIN_CAP`."""
    out = [cap]
    while out[-1] - STEP >= MIN_CAP - 1e-9:
        out.append(round(out[-1] - STEP, 3))
    if out[-1] > MIN_CAP + 1e-9:
        out.append(MIN_CAP)
    return out


def band(cap: float) -> float:
    """The strip a lip label needs along the back edge: its line and a margin each side."""
    return line(cap) + 2 * MARGIN


def _box(centre: Point, w: float, h: float, rotation: float) -> tuple[Point, ...]:
    a = math.radians(rotation)
    c, s = math.cos(a), math.sin(a)
    cx, cy = centre
    corners = ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))
    return tuple((round(cx + x * c - y * s, 4), round(cy + x * s + y * c, 4)) for x, y in corners)


def on_lip(
    text: str, cap: float, *, across_mm: float, room: float, between: tuple[float, float], **style
) -> Label | None:
    """A label along the back edge, centred across the bin (``across_mm`` wide) and between
    the lip and the pockets (``between``, y from the back), or None when ``text`` at capitals
    ``cap`` mm tall is longer than ``room``, the width inside the lip, less the margins."""
    w = width(text, cap)
    if w > room - 2 * MARGIN + 1e-9 or line(cap) + 2 * MARGIN > between[1] - between[0] + 1e-9:
        return None
    centre = (across_mm / 2, (between[0] + between[1]) / 2)
    return Label(text, centre, 0.0, cap, placement="lip", box=_box(centre, w, line(cap), 0.0), **style)


def _turn(points, degrees: float) -> list[Point]:
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    return [(x * c - y * s, x * s + y * c) for x, y in points]


def _clips(a: Point, b: Point, box: tuple[float, float, float, float]) -> bool:
    """Whether the segment ``a``-``b`` passes through the open box (Liang-Barsky)."""
    x0, y0, x1, y1 = box
    if max(a[0], b[0]) <= x0 or min(a[0], b[0]) >= x1 or max(a[1], b[1]) <= y0 or min(a[1], b[1]) >= y1:
        return False
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]), (-dy, a[1] - y0), (dy, y1 - a[1])):
        if abs(p) < 1e-12:
            if q <= 0:
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


def _inside(x: float, y: float, rings: Sequence[Sequence[Point]]) -> bool:
    """Even-odd: inside the outline and outside the rings within it."""
    inside = False
    for ring in rings:
        n = len(ring)
        for i in range(n):
            (xi, yi), (xj, yj) = ring[i], ring[i - 1]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
    return inside


def _crossings(rings: Sequence[Sequence[Point]], x: float) -> list[float]:
    ys = []
    for ring in rings:
        n = len(ring)
        for i in range(n):
            (x1, y1), (x2, y2) = ring[i - 1], ring[i]
            if (x1 <= x < x2) or (x2 <= x < x1):
                ys.append(y1 + (x - x1) * (y2 - y1) / (x2 - x1))
    return sorted(ys)


def in_pocket(
    text: str,
    cap: float,
    rings: Sequence[Sequence[Point]],
    holes: Sequence[tuple[float, float, float]],
    rotation: float,
    **style,
) -> Label | None:
    """A label on a pocket's floor, reading along ``rotation`` (degrees clockwise), clear of
    the pocket's edge, the rings of material inside it and its finger ``holes`` (x, y,
    radius) by :data:`MARGIN`, as near the middle of the pocket's length as it fits; None when
    ``text`` at capitals ``cap`` mm tall fits nowhere in it. ``rings`` are the pocket's
    outline and inner rings in the bin's mm."""
    w, h = width(text, cap) + 2 * MARGIN, line(cap) + 2 * MARGIN
    turned = [_turn(r, -rotation) for r in rings]
    spots = [(*_turn([(x, y)], -rotation)[0], r) for x, y, r in holes]
    xs = [p[0] for p in turned[0]]
    x0, x1 = min(xs), max(xs)
    if x1 - x0 < w:
        return None
    middle = (x0 + x1) / 2
    reach = (x1 - x0 - w) / 2
    steps = max(1, min(60, math.ceil(reach)))
    offsets = sorted(
        {0.0, *(reach * k / steps * sign for k in range(1, steps + 1) for sign in (1, -1))}, key=abs
    )
    edges = [(r[i - 1], r[i]) for r in turned for i in range(len(r))]
    for dx in offsets:
        cx = middle + dx
        ys = _crossings(turned, cx)
        for a, b in zip(ys[::2], ys[1::2], strict=False):
            if b - a < h:
                continue
            cy = (a + b) / 2
            box = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
            if not _inside(cx, cy, turned):
                continue
            if any(_clips(a_, b_, box) for a_, b_ in edges):
                continue
            if any(
                math.hypot(max(box[0] - sx, 0, sx - box[2]), max(box[1] - sy, 0, sy - box[3])) < r
                for sx, sy, r in spots
            ):
                continue
            centre = _turn([(cx, cy)], rotation)[0]
            centre = (round(centre[0], 4), round(centre[1], 4))
            return Label(
                text,
                centre,
                rotation,
                cap,
                placement="floor",
                box=_box(centre, w - 2 * MARGIN, h - 2 * MARGIN, rotation),
                **style,
            )
    return None


__all__ = [
    "DEFAULT_CAP",
    "DEFAULT_DEPTH",
    "MARGIN",
    "MAX_CAP",
    "MAX_DEPTH",
    "MIN_CAP",
    "MIN_DEPTH",
    "PLACEMENTS",
    "STYLES",
    "WIDTHS",
    "Label",
    "LabelError",
    "band",
    "clean",
    "em_for",
    "in_pocket",
    "line",
    "on_lip",
    "sizes",
    "width",
]
