"""The painter interface PDF, SVG and the viewer implement, and the curves they get
(``docs/DRAWINGS.md`` 6.7).

A painter draws only the painted layer (:mod:`.display` ``Stroke``, ``Fill``,
``TextRun``, ``ImageRun``), so every surface agrees to a hundredth of a
millimetre. Curves reach it as cubic Béziers: an arc in pieces of at most 90
degrees (four a circle, about 0.03 % of the radius off), an ellipse arc as the
same pieces mapped through the ellipse's affine frame (exact to the same
amount), a B-spline of degree 3 or less by knot insertion (exact), and a rational
or higher-degree spline as a polyline within :data:`SPLINE_TOLERANCE`.

:func:`stroke_geometry` turns display-list geometry into strokes with the
standard's line widths and dashes, which is how a sheet is painted before layout
exists (previews, tests) and how layout paints view geometry.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Protocol, runtime_checkable

from ..errors import InvalidArgumentError
from . import display as D
from . import fonts, standards

SPLINE_TOLERANCE = 0.01  # mm on the sheet
MAX_SPLINE_SAMPLES = 4096
ANCHORS = ("left", "centre", "right")


@runtime_checkable
class Painter(Protocol):
    """What a surface implements (6.7). Lengths are sheet millimetres, y up; ``grey``
    is 0 for black to 1 for white; ``font`` is ``Helvetica`` or ``Helvetica-Bold``;
    ``size`` is the font size."""

    def begin_page(self, width: float, height: float) -> None: ...

    def set_stroke(self, width: float, dash: Sequence[float], cap: int, join: int, grey: float) -> None: ...

    def path(self, ops: Sequence[tuple]) -> None: ...

    def stroke(self) -> None: ...

    def fill(self, grey: float) -> None: ...

    def text(
        self, x: float, y: float, size: float, angle_deg: float, string: str, font: str, anchor: str
    ) -> None: ...

    def image(self, x: float, y: float, width: float, height: float, data: bytes) -> None: ...

    def group(self, name: str) -> None: ...

    def end_group(self) -> None: ...

    def end_page(self) -> None: ...


# --------------------------------------------------------------------------- curves as Béziers


def arc_beziers(cx: float, cy: float, r: float, start_deg: float, sweep_deg: float) -> list[tuple]:
    """``("C", ...)`` operations for an arc counter-clockwise from ``start_deg`` through
    ``sweep_deg`` (negative: clockwise), in pieces of at most 90 degrees. The caller
    moves to the start point first."""
    if sweep_deg == 0.0 or r <= 0.0:
        return []
    n = max(1, math.ceil(abs(sweep_deg) / 90.0 - 1e-9))
    step = math.radians(sweep_deg) / n
    k = 4.0 / 3.0 * math.tan(step / 4.0)
    out = []
    a = math.radians(start_deg)
    for _ in range(n):
        b = a + step
        ca, sa, cb, sb = math.cos(a), math.sin(a), math.cos(b), math.sin(b)
        out.append(
            (
                "C",
                cx + r * (ca - k * sa),
                cy + r * (sa + k * ca),
                cx + r * (cb + k * sb),
                cy + r * (sb - k * cb),
                cx + r * cb,
                cy + r * sb,
            )
        )
        a = b
    return out


def _affine(ops: list[tuple], centre: D.Point, u: D.Point, v: D.Point) -> list[tuple]:
    """Map unit-circle operations through p -> centre + x u + y v."""
    out = []
    for op in ops:
        coords = op[1:]
        mapped = []
        for i in range(0, len(coords), 2):
            x, y = coords[i], coords[i + 1]
            mapped += [centre[0] + x * u[0] + y * v[0], centre[1] + x * u[1] + y * v[1]]
        out.append((op[0], *mapped))
    return out


def _insert(p: int, U: list[float], P: list[tuple], u: float) -> tuple[list[float], list[tuple]]:
    """Boehm's single knot insertion of ``u`` into a non-rational B-spline."""
    n = len(P) - 1
    k = p
    for i in range(p, n + 1):
        if U[i] <= u < U[i + 1]:
            k = i
            break
    else:
        k = max(i for i in range(p, n + 1) if U[i] < U[i + 1])
    Q = list(P[: k - p + 1])
    for i in range(k - p + 1, k + 1):
        den = U[i + p] - U[i]
        alpha = 0.0 if den == 0.0 else (u - U[i]) / den
        a, b = P[i - 1], P[i]
        Q.append((a[0] + alpha * (b[0] - a[0]), a[1] + alpha * (b[1] - a[1])))
    Q += P[k:]
    return U[: k + 1] + [u] + U[k + 1 :], Q


def spline_beziers(
    degree: int, knots: Sequence[float], points: Sequence[D.Point]
) -> list[tuple[D.Point, ...]]:
    """A non-rational B-spline of degree 1 to 3 as cubic Béziers (four control points
    each), exactly, by raising every knot of its domain to multiplicity ``degree``."""
    p = degree
    if not 1 <= p <= 3:
        raise InvalidArgumentError("only degrees 1 to 3 convert exactly", detail={"parameter": "degree"})
    U, P = list(map(float, knots)), [tuple(map(float, q)) for q in points]
    lo, hi = U[p], U[len(P)]
    for u in sorted({x for x in U if lo <= x <= hi}):
        while sum(1 for x in U if x == u) < p:
            U, P = _insert(p, U, P, u)
    pieces = []
    for k in range(p, len(P)):
        if U[k] < U[k + 1] and lo <= U[k] and U[k + 1] <= hi:
            ctrl = P[k - p : k + 1]
            pieces.append(_cubic(ctrl))
    return pieces


def _cubic(ctrl: Sequence[tuple]) -> tuple[D.Point, ...]:
    if len(ctrl) == 4:
        return tuple(ctrl)
    if len(ctrl) == 3:
        a, b, c = ctrl
        return (
            a,
            (a[0] + 2.0 / 3.0 * (b[0] - a[0]), a[1] + 2.0 / 3.0 * (b[1] - a[1])),
            (c[0] + 2.0 / 3.0 * (b[0] - c[0]), c[1] + 2.0 / 3.0 * (b[1] - c[1])),
            c,
        )
    a, b = ctrl
    return (
        a,
        (a[0] + (b[0] - a[0]) / 3.0, a[1] + (b[1] - a[1]) / 3.0),
        (a[0] + 2 * (b[0] - a[0]) / 3.0, a[1] + 2 * (b[1] - a[1]) / 3.0),
        b,
    )


def _de_boor(p: int, U: Sequence[float], P: Sequence[tuple], W: Sequence[float] | None, t: float) -> D.Point:
    n = len(P) - 1
    k = p
    for i in range(p, n + 1):
        if U[i] <= t < U[i + 1]:
            k = i
            break
    else:
        k = max(i for i in range(p, n + 1) if U[i] < U[i + 1])
    w = [1.0] * len(P) if W is None else list(W)
    d = [(P[j][0] * w[j], P[j][1] * w[j], w[j]) for j in range(k - p, k + 1)]
    for r in range(1, p + 1):
        for j in range(p, r - 1, -1):
            i = j + k - p
            den = U[i + p - r + 1] - U[i]
            a = 0.0 if den == 0.0 else (t - U[i]) / den
            d[j] = tuple((1.0 - a) * d[j - 1][m] + a * d[j][m] for m in range(3))
    x, y, ww = d[p]
    return (x / ww, y / ww)


def spline_points(spline: D.Spline, tolerance: float = SPLINE_TOLERANCE) -> list[D.Point]:
    """Points along any spline, rational or not, close enough that the chords stay
    within about ``tolerance`` of the curve (bounded by :data:`MAX_SPLINE_SAMPLES`)."""
    p, U, P, W = spline.degree, spline.knots, spline.points, spline.weights
    lo, hi = U[p], U[len(P)]
    x0, y0, x1, y1 = spline.bounds()
    size = max(x1 - x0, y1 - y0, 1e-9)
    spans = max(1, len({u for u in U if lo <= u <= hi}) - 1)
    n = min(
        MAX_SPLINE_SAMPLES, max(8 * spans, int(math.ceil(math.sqrt(size / max(tolerance, 1e-6)) * 4 * spans)))
    )
    return [_de_boor(p, U, P, W, lo + (hi - lo) * i / n) for i in range(n + 1)]


def path_of(item) -> list[tuple]:
    """A display-list geometry primitive as path operations."""
    if isinstance(item, D.Segment):
        return [("M", *item.p0), ("L", *item.p1)]
    if isinstance(item, D.Arc):
        sweep = item.sweep()
        start = item.point(item.start_deg)
        ops = [
            ("M", *start),
            *arc_beziers(item.centre[0], item.centre[1], item.radius, item.start_deg, sweep),
        ]
        if sweep >= 360.0:
            ops.append(("Z",))
        return ops
    if isinstance(item, D.EllipseArc):
        u = item.major
        v = (-u[1] * item.ratio, u[0] * item.ratio)
        sweep = math.degrees(item.t1 - item.t0)
        unit = [
            ("M", math.cos(item.t0), math.sin(item.t0)),
            *arc_beziers(0.0, 0.0, 1.0, math.degrees(item.t0), sweep),
        ]
        return _affine(unit, item.centre, u, v)
    if isinstance(item, D.Spline):
        if item.weights is None and item.degree <= 3:
            pieces = spline_beziers(item.degree, item.knots, item.points)
            if pieces:
                ops: list[tuple] = [("M", *pieces[0][0])]
                for _a, b, c, d in pieces:
                    ops.append(("C", *b, *c, *d))
                return ops
        pts = spline_points(item)
        return [("M", *pts[0]), *(("L", *q) for q in pts[1:])]
    if isinstance(item, D.Polyline):
        if not item.points:
            return []
        ops = [("M", *item.points[0]), *(("L", *q) for q in item.points[1:])]
        if item.closed:
            ops.append(("Z",))
        return ops
    raise TypeError(f"not a geometry primitive: {type(item).__name__}")


def stroke_geometry(
    items: Iterable, lines: dict[str, standards.LineStyle] | None = None
) -> tuple[D.Stroke, ...]:
    """Display-list geometry as strokes with the standard's widths and dashes, each on
    its style's layer and owned by its view."""
    styles = lines or standards.LINES
    out = []
    for item in items:
        line = styles.get(item.style, styles["thin"])
        layer = D.STYLE_LAYER.get(item.style, "visible")
        cap = 1 if item.style == "visible" else 0
        out.append(D.Stroke(tuple(path_of(item)), line.width, line.dash, layer, item.src.view, cap, 1))
    return tuple(out)


def text_run(x: float, y: float, height: float, text: str, **kw) -> D.TextRun:
    """A text run whose capitals are ``height`` millimetres tall, measured."""
    bold = kw.pop("bold", False)
    size = fonts.font_size(height)
    return D.TextRun(x, y, size, text, bold=bold, width=fonts.measure(text, size, bold), **kw)


def paint(sheet: D.Sheet, painter: Painter) -> None:
    """Replay a sheet's painted layer on ``painter``, one group a layer in the order of
    :data:`display.LAYERS` (so visible lines draw over hidden ones), items in their
    order within it."""
    painter.begin_page(sheet.width, sheet.height)
    by_layer: dict[str, list] = {}
    for item in sheet.painted:
        by_layer.setdefault(item.layer, []).append(item)
    order = [layer for layer in D.LAYERS if layer in by_layer] + sorted(set(by_layer) - set(D.LAYERS))
    for layer in order:
        painter.group(layer)
        for item in by_layer[layer]:
            if isinstance(item, D.Stroke):
                painter.set_stroke(item.width, item.dash, item.cap, item.join, item.grey)
                painter.path(item.path)
                painter.stroke()
            elif isinstance(item, D.Fill):
                painter.path(item.path)
                painter.fill(item.grey)
            elif isinstance(item, D.TextRun):
                painter.text(
                    item.x,
                    item.y,
                    item.size,
                    item.angle_deg,
                    item.text,
                    fonts.font_name(item.bold),
                    item.anchor,
                )
            elif isinstance(item, D.ImageRun):
                painter.image(item.x, item.y, item.width, item.height, item.png)
        painter.end_group()
    painter.end_page()


def _recorded(name: str):
    def record(self, *args, **kwargs):
        self.calls.append((name, *args, *kwargs.values()))

    record.__name__ = name
    return record


class RecordingPainter:
    """A painter that records its calls, for tests and for measuring what a sheet
    draws. Each method of :class:`Painter` is defined here, not looked up on the fly:
    since Python 3.12 ``isinstance`` against a runtime-checkable protocol finds a
    method only where it is defined."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    begin_page = _recorded("begin_page")
    set_stroke = _recorded("set_stroke")
    path = _recorded("path")
    stroke = _recorded("stroke")
    fill = _recorded("fill")
    text = _recorded("text")
    image = _recorded("image")
    group = _recorded("group")
    end_group = _recorded("end_group")
    end_page = _recorded("end_page")


__all__ = [
    "ANCHORS",
    "SPLINE_TOLERANCE",
    "Painter",
    "RecordingPainter",
    "arc_beziers",
    "paint",
    "path_of",
    "spline_beziers",
    "spline_points",
    "stroke_geometry",
    "text_run",
]
