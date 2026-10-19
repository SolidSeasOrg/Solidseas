"""Dash patterns fitted to each line (``docs/DRAWINGS.md`` 11.5).

A hidden, centre or phantom line starts and ends with a dash: the standard pattern
is stretched or shrunk a little so a whole number of periods and one more dash fill
the line exactly (a closed curve takes whole periods). A line shorter than one
period is drawn as a single dash. Widths are the standard's two, in a 1:2 ratio.
"""

from __future__ import annotations

import math

from .. import display as D
from .. import standards
from ..numbers import plain_sum
from ..painter import path_of, spline_points

MIN_STRETCH, MAX_STRETCH = 0.6, 1.6


def length_of(item) -> float:
    """A geometry primitive's length on the sheet, millimetres."""
    if isinstance(item, D.Segment):
        return math.dist(item.p0, item.p1)
    if isinstance(item, D.Arc):
        return item.radius * math.radians(item.sweep())
    if isinstance(item, D.Polyline):
        pts = list(item.points) + ([item.points[0]] if item.closed and item.points else [])
        return plain_sum(math.dist(a, b) for a, b in zip(pts, pts[1:], strict=False))
    if isinstance(item, D.EllipseArc):
        n = 64
        pts = [item.point(item.t0 + (item.t1 - item.t0) * k / n) for k in range(n + 1)]
        return plain_sum(math.dist(a, b) for a, b in zip(pts, pts[1:], strict=False))
    if isinstance(item, D.Spline):
        pts = spline_points(item, 0.05)
        return plain_sum(math.dist(a, b) for a, b in zip(pts, pts[1:], strict=False))
    return 0.0


def closed(item) -> bool:
    if isinstance(item, D.Arc):
        return item.sweep() >= 360.0
    if isinstance(item, D.Polyline):
        return item.closed
    if isinstance(item, D.EllipseArc):
        return abs(item.t1 - item.t0) >= 2 * math.pi - 1e-9
    return False


def fit(dash: tuple[float, ...], length: float, is_closed: bool = False) -> tuple[float, ...]:
    """``dash`` scaled so the line starts and ends with a dash; () for a line too
    short to carry the pattern (drawn solid, one dash)."""
    if not dash or length <= 0:
        return tuple(dash)
    period = plain_sum(dash)
    if is_closed:
        n = max(1, round(length / period))
        s = length / (n * period)
    else:
        if length < period + dash[0]:
            return ()
        n = max(1, round((length - dash[0]) / period))
        s = length / (n * period + dash[0])
    s = min(MAX_STRETCH, max(MIN_STRETCH, s))
    return tuple(round(d * s, 4) for d in dash)


def strokes(items, layers=None, lines: dict | None = None) -> list[D.Stroke]:
    """Placed geometry as strokes, owned by its view, dashes fitted to each primitive;
    each on the layer given for it, else its style's."""
    styles = lines or standards.LINES
    out = []
    for k, item in enumerate(items):
        line = styles.get(item.style, styles["thin"])
        layer = layers[k] if layers is not None else D.STYLE_LAYER.get(item.style, "visible")
        dash = fit(line.dash, length_of(item), closed(item)) if line.dash else ()
        cap = 1 if item.style == "visible" else 0
        out.append(D.Stroke(tuple(path_of(item)), line.width, dash, layer, item.src.view, cap, 1))
    return out


__all__ = ["closed", "fit", "length_of", "strokes"]
