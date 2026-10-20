"""Entities: view geometry, the painted layer, frames, datum symbols and the sheet's
furniture as DXF entities (``docs/DRAWINGS.md`` 6.7, 8.8, 11.4, 12.2).

Coordinates. The sheet is in millimetres; the DXF's model space is in the
drawing's unit at the size of the part. A point P on the sheet goes to
``P * unit / s``, where ``s`` is the sheet's scale (sheet millimetres per model
millimetre) and ``unit`` is 1 for millimetres and 1/25.4 for inches. For a view
placed at the sheet's scale that is exactly the view's own coordinates
(``ViewPlacement.to_view``, metres) times 1000, set at its origin's place in
model space, so the views come out at true size and the border, the title block
and the notes sit round them at ``1/s`` of their paper size. A view at another
scale (a detail) keeps the look it has on paper, magnified against the others,
and its dimensions carry ``DIMLFAC`` (:mod:`.dimensions`).

View geometry is written exactly: LINE, ARC, CIRCLE, ELLIPSE (with its parameters),
SPLINE (degree, knots, control points and weights as the display list holds
them) and LWPOLYLINE. Painted strokes become LINE, LWPOLYLINE or, where they hold
Béziers, a cubic SPLINE whose knots make each Bézier one span (exact); fills
become SOLID (three or four corners) or a solid HATCH; text becomes TEXT in the
``SOLIDSEAS`` style (Arial, Helvetica's widths) with its height the capital
height. The logo is not written: a DXF image is a link to an outside file.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ...errors import InvalidArgumentError
from .. import display as D
from .. import fonts
from ..limits import DrawingLimits
from ..numbers import plain_sum
from ..standards import CHARACTERISTICS, TEXT
from . import tables as T
from .tags import MAX_TEXT, clean, clean_tokens

Point = tuple[float, float]
BYBLOCK_COLOUR = 0
BYBLOCK_WEIGHT = -2
FRAME_PAD = 1.0  # millimetres of cell above and below the text
CELL_PAD = 1.2  # millimetres of cell either side of the text
BEZIER_STEPS = 8  # a Bézier's pieces in a HATCH boundary


def _bad(message: str) -> InvalidArgumentError:
    return InvalidArgumentError(message, detail={"parameter": "sheet"})


@dataclass
class Ent:
    """One entity before it has a handle: its type, layer, optional linetype, colour
    and lineweight, the tags after the common part, and its extended data."""

    kind: str
    layer: str
    body: list[tuple[int, Any]]
    linetype: str | None = None
    colour: int | None = None
    lineweight: int | None = None
    xdata: list[tuple[int, Any]] = field(default_factory=list)


def write_entity(w, ent: Ent, handle: str, owner: str) -> None:
    w.tags([(0, ent.kind), (5, handle), (330, owner), (100, "AcDbEntity"), (8, ent.layer)])
    if ent.linetype is not None:
        w.tag(6, ent.linetype)
    if ent.colour is not None:
        w.tag(62, ent.colour)
    if ent.lineweight is not None:
        w.tag(370, ent.lineweight)
    w.tags(ent.body)
    w.tags(ent.xdata)


def in_block(ent: Ent) -> Ent:
    """``ent`` drawn by its block reference: layer 0, colour, linetype and lineweight
    by block, unless it already carries its own."""
    ent.layer = "0"
    if ent.colour is None:
        ent.colour = BYBLOCK_COLOUR
    if ent.linetype is None:
        ent.linetype = "ByBlock"
    if ent.lineweight is None:
        ent.lineweight = BYBLOCK_WEIGHT
    return ent


# --------------------------------------------------------------------------- context


@dataclass(frozen=True)
class Context:
    """How one sheet maps to model space, and what its strings need. ``dx`` moves the
    sheet to the right by that many sheet millimetres: a drawing's later sheets stand
    beside its first."""

    unit: str  # "mm" or "in"
    sheet_scale: float  # sheet millimetres per model millimetre
    words: bool = False
    limits: DrawingLimits = DrawingLimits()
    dx: float = 0.0

    @property
    def k(self) -> float:
        """Model units per sheet millimetre."""
        return (1.0 / T.INCH_MM if self.unit == "in" else 1.0) / self.sheet_scale

    @property
    def heights(self):
        return TEXT[self.unit]

    def pt(self, p) -> Point:
        try:
            x, y = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            raise _bad("a sheet point must be two numbers") from None
        if not (math.isfinite(x) and math.isfinite(y)):
            raise _bad("a sheet point must be finite")
        k = self.k
        if self.dx:
            x += self.dx
        return (x * k, y * k)

    def size(self, d: float) -> float:
        d = float(d)
        if not math.isfinite(d):
            raise _bad("a sheet length must be finite")
        return d * self.k

    def text(self, s: str, *, mtext: bool = False, cut: int = MAX_TEXT) -> str:
        return clean(s, mtext=mtext, words=self.words, limit=self.limits.string_chars, cut=cut)

    def tokens(self, s: str) -> list[str]:
        return clean_tokens(s, mtext=True, words=self.words, limit=self.limits.string_chars)


def xyz(code: int, p: Point) -> list[tuple[int, Any]]:
    return [(code, float(p[0])), (code + 10, float(p[1])), (code + 20, 0.0)]


# --------------------------------------------------------------------------- entity builders (model space)


def line(p0: Point, p1: Point, layer: str) -> Ent:
    return Ent("LINE", layer, [(100, "AcDbLine"), *xyz(10, p0), *xyz(11, p1)])


def circle(c: Point, r: float, layer: str) -> Ent:
    return Ent("CIRCLE", layer, [(100, "AcDbCircle"), *xyz(10, c), (40, r)])


def arc(c: Point, r: float, start: float, end: float, layer: str) -> Ent:
    body = [(100, "AcDbCircle"), *xyz(10, c), (40, r), (100, "AcDbArc"), (50, start), (51, end)]
    return Ent("ARC", layer, body)


def ellipse(c: Point, major: Point, ratio: float, t0: float, t1: float, layer: str) -> Ent:
    body = [(100, "AcDbEllipse"), *xyz(10, c), *xyz(11, major), (210, 0.0), (220, 0.0), (230, 1.0)]
    body += [(40, ratio), (41, t0), (42, t1)]
    return Ent("ELLIPSE", layer, body)


def spline(degree: int, knots, points, weights, layer: str) -> Ent:
    flags = 8 | (4 if weights is not None else 0)
    body: list[tuple[int, Any]] = [(100, "AcDbSpline"), (210, 0.0), (220, 0.0), (230, 1.0), (70, flags)]
    body += [(71, degree), (72, len(knots)), (73, len(points)), (74, 0), (42, 1e-10), (43, 1e-10)]
    for u in knots:
        body.append((40, _fine(u)))
    if weights is not None:
        for wt in weights:
            body.append((41, _fine(wt)))
    for p in points:
        body += xyz(10, p)
    return Ent("SPLINE", layer, body)


def _fine(x) -> str:
    """A knot or weight with the decimals a parameter needs."""
    from .tags import num

    return num(float(x), 16)


def lwpolyline(points, closed: bool, layer: str) -> Ent:
    body: list[tuple[int, Any]] = [
        (100, "AcDbPolyline"),
        (90, len(points)),
        (70, 1 if closed else 0),
        (43, 0.0),
    ]
    for p in points:
        body += [(10, float(p[0])), (20, float(p[1]))]
    return Ent("LWPOLYLINE", layer, body)


ALIGN = {"left": 0, "centre": 1, "right": 2}


def text(
    at: Point,
    height: float,
    value: str,
    layer: str,
    *,
    angle: float = 0.0,
    anchor: str = "left",
    middle: bool = False,
    width: float = 0.0,
    bold: bool = False,
) -> Ent:
    """TEXT whose ``anchor`` (left, centre or right; on the baseline, or the middle
    when ``middle``) is at ``at``; ``width`` (model units) places the first
    alignment point readers that ignore the second one use."""
    h = ALIGN.get(anchor, 0)
    a = math.radians(angle)
    d = (math.cos(a), math.sin(a))
    shift = {0: 0.0, 1: width / 2.0, 2: width}[h]
    first = (at[0] - d[0] * shift, at[1] - d[1] * shift)
    if middle:
        first = (first[0] + math.sin(a) * height / 2.0, first[1] - math.cos(a) * height / 2.0)
    body: list[tuple[int, Any]] = [(100, "AcDbText"), *xyz(10, first), (40, height), (1, value)]
    if angle:
        body.append((50, angle % 360.0))
    body.append((7, T.STYLE_BOLD if bold else T.STYLE_REGULAR))
    if h or middle:
        body.append((72, h))
        body += xyz(11, at)
    body.append((100, "AcDbText"))
    if middle:
        body.append((73, 2))
    return Ent("TEXT", layer, body)


def mtext(
    at: Point, height: float, tokens: list[str], layer: str, *, attach: int = 1, angle: float = 0.0
) -> Ent:
    """MTEXT from cleaned pieces (``\\P`` between lines), its ``attach`` point (1 top
    left, 5 middle centre, 7 bottom left) at ``at``."""
    from .tags import chunks

    pieces = chunks(tokens)
    body: list[tuple[int, Any]] = [(100, "AcDbMText"), *xyz(10, at), (40, height), (41, 0.0)]
    body += [(71, attach), (72, 1)]
    body += [(3, piece) for piece in pieces[:-1]]
    body += [(1, pieces[-1]), (7, T.STYLE_REGULAR)]
    if angle:
        a = math.radians(angle)
        body += xyz(11, (math.cos(a), math.sin(a)))
    body += [(73, 1), (44, 1.0)]
    return Ent("MTEXT", layer, body)


def solid(points, layer: str) -> Ent:
    """A filled triangle or quadrilateral, corners in order round it."""
    p = list(points)
    if len(p) == 3:
        order = [p[0], p[1], p[2], p[2]]
    else:
        order = [p[0], p[1], p[3], p[2]]
    body: list[tuple[int, Any]] = [(100, "AcDbTrace")]
    for code, q in zip((10, 11, 12, 13), order, strict=True):
        body += xyz(code, q)
    return Ent("SOLID", layer, body)


def hatch(loops, layer: str) -> Ent:
    """A solid fill bounded by closed polygons (odd parity, so holes stay open)."""
    body: list[tuple[int, Any]] = [(100, "AcDbHatch"), *xyz(10, (0.0, 0.0)), (210, 0.0), (220, 0.0)]
    body += [(230, 1.0), (2, "SOLID"), (70, 1), (71, 0), (91, len(loops))]
    for i, loop in enumerate(loops):
        body += [(92, 3 if i == 0 else 2), (72, 0), (73, 1), (93, len(loop))]
        for p in loop:
            body += [(10, float(p[0])), (20, float(p[1]))]
        body.append((97, 0))
    body += [(75, 0), (76, 1), (98, 0)]
    return Ent("HATCH", layer, body)


def insert(name: str, at: Point, layer: str) -> Ent:
    return Ent("INSERT", layer, [(100, "AcDbBlockReference"), (2, name), *xyz(10, at)])


def point(at: Point, layer: str) -> Ent:
    return Ent("POINT", layer, [(100, "AcDbPoint"), *xyz(10, at)])


# --------------------------------------------------------------------------- view geometry


def _finite(*values) -> None:
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise _bad("a sheet number must be finite")


def from_geometry(item, ctx: Context) -> list[Ent]:
    """A display-list primitive (sheet millimetres) as exact model-space entities."""
    layer = T.STYLE_LAYER.get(getattr(item, "style", ""), "VISIBLE")
    out: list[Ent] = []
    if isinstance(item, D.Segment):
        out.append(line(ctx.pt(item.p0), ctx.pt(item.p1), layer))
    elif isinstance(item, D.Arc):
        _finite(item.radius, item.start_deg, item.end_deg)
        sweep = item.sweep()
        if item.radius > 0.0 and sweep > 0.0:
            c, r = ctx.pt(item.centre), ctx.size(item.radius)
            if sweep >= 360.0:
                out.append(circle(c, r, layer))
            else:
                start = item.start_deg % 360.0
                out.append(arc(c, r, start, (start + sweep) % 360.0, layer))
    elif isinstance(item, D.EllipseArc):
        out += _ellipse(item, ctx, layer)
    elif isinstance(item, D.Spline):
        _finite(*item.knots)
        if item.weights is not None:
            _finite(*item.weights)
            if any(wt <= 0.0 for wt in item.weights):
                raise _bad("a spline's weights must be more than nought")
        pts = [ctx.pt(p) for p in item.points]
        out.append(spline(item.degree, item.knots, pts, item.weights, layer))
    elif isinstance(item, D.Polyline):
        pts = [ctx.pt(p) for p in item.points]
        if len(pts) >= 2:
            out.append(lwpolyline(pts, bool(item.closed), layer))
    if getattr(item, "style", "") == "thin":
        for ent in out:
            ent.lineweight = 30
    return out


def _ellipse(item: D.EllipseArc, ctx: Context, layer: str) -> list[Ent]:
    _finite(item.ratio, item.t0, item.t1, *item.major)
    mx, my = ctx.size(item.major[0]), ctx.size(item.major[1])
    ratio, t0, t1 = float(item.ratio), float(item.t0), float(item.t1)
    if ratio <= 0.0 or (mx == 0.0 and my == 0.0):
        return []
    if ratio > 1.0:  # the minor axis is the longer: make it the major
        mx, my = -my * ratio, mx * ratio
        ratio = 1.0 / ratio
        t0, t1 = t0 - math.pi / 2.0, t1 - math.pi / 2.0
    tau = 2.0 * math.pi
    span = t1 - t0
    if abs(span) >= tau - 1e-12:
        start, end = 0.0, tau
    else:
        span %= tau
        if span == 0.0:
            return []
        start = t0 % tau
        end = start + span
        if end > tau:
            end -= tau
    return [ellipse(ctx.pt(item.centre), (mx, my), ratio, start, end, layer)]


# --------------------------------------------------------------------------- the painted layer

_OP_SIZE = {"M": 2, "L": 2, "C": 6, "Z": 0}


def subpaths(path) -> list[tuple[Point, list[tuple], bool]]:
    """A painted path as subpaths: (start, segments, closed), each segment ``("L", q)``
    or ``("C", c1, c2, q)``, in sheet millimetres."""
    out: list[tuple[Point, list[tuple], bool]] = []
    start: Point | None = None
    segs: list[tuple] = []
    closed = False
    for op in path:
        if not isinstance(op, (tuple, list)) or not op or op[0] not in _OP_SIZE:
            raise _bad("a painted path holds an operation it does not know")
        size = _OP_SIZE[op[0]]
        if len(op) != size + 1:
            raise _bad("a painted path operation has the wrong number of values")
        _finite(*op[1:])
        pts = [(float(op[i]), float(op[i + 1])) for i in range(1, size + 1, 2)]
        if op[0] == "M":
            if start is not None:
                out.append((start, segs, closed))
            start = pts[0]
            segs, closed = [], False
        elif op[0] == "Z":
            closed = True
        else:
            if start is None:
                raise _bad("a painted path must start with a move")
            if closed:  # drawing on after a close starts a new subpath at the start
                out.append((start, segs, closed))
                segs, closed = [], False
            segs.append((op[0], *pts))
    if start is not None:
        out.append((start, segs, closed))
    return out


def _cubic_points(start: Point, segs: list[tuple]) -> list[Point]:
    """Control points of a piecewise cubic Bézier through ``segs`` (lines as cubics)."""
    pts = [start]
    p = start
    for seg in segs:
        if seg[0] == "L":
            q = seg[1]
            pts += [
                (p[0] + (q[0] - p[0]) / 3.0, p[1] + (q[1] - p[1]) / 3.0),
                (p[0] + 2.0 * (q[0] - p[0]) / 3.0, p[1] + 2.0 * (q[1] - p[1]) / 3.0),
                q,
            ]
        else:
            q = seg[3]
            pts += [seg[1], seg[2], q]
        p = q
    return pts


def _bezier_knots(n: int) -> list[float]:
    return [0.0] * 4 + [float(i) for i in range(1, n) for _ in range(3)] + [float(n)] * 4


def _flatten(start: Point, segs: list[tuple]) -> list[Point]:
    pts = [start]
    p = start
    for seg in segs:
        if seg[0] == "L":
            pts.append(seg[1])
            p = seg[1]
            continue
        c1, c2, q = seg[1], seg[2], seg[3]
        for i in range(1, BEZIER_STEPS + 1):
            t = i / BEZIER_STEPS
            a, b, c, d = (1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t**3
            pts.append(
                (
                    a * p[0] + b * c1[0] + c * c2[0] + d * q[0],
                    a * p[1] + b * c1[1] + c * c2[1] + d * q[1],
                )
            )
        p = q
    return pts


def _linetype(dash) -> str:
    """The ``acad.lin`` line type a painted dash pattern stands for."""
    n = len(dash)
    if n == 0:
        return "CONTINUOUS"
    if n <= 3:
        return "HIDDEN" if dash[0] <= 3.0 * max(dash[1] if n > 1 else 1.0, 1e-9) else "DASHED"
    return "CENTER" if n < 6 else "PHANTOM"


def _grey(grey: float) -> int | None:
    if not grey or grey <= 0.0:
        return None
    return 8 if grey < 0.5 else 9


def _styled(
    ents: list[Ent], *, layer: str, dash=(), width: float | None = None, grey: float = 0.0, block: bool
):
    if block:
        lt = _linetype(dash)
        for ent in ents:
            ent.colour = _grey(grey)
            ent.linetype = None if lt == "CONTINUOUS" else lt
            if width is not None and T.lineweight(width) != 30:
                ent.lineweight = T.lineweight(width)
            in_block(ent)
        return ents
    target = T.LAYER_OF.get(layer, "NOTES")
    defaults = T.LAYER_BY_NAME[target]
    lt = _linetype(dash)
    for ent in ents:
        ent.layer = target
        if lt != defaults.linetype:
            ent.linetype = lt
        if width is not None and T.lineweight(width) != defaults.lineweight:
            ent.lineweight = T.lineweight(width)
        ent.colour = _grey(grey)
    return ents


def from_painted(item, ctx: Context, *, block: bool = False) -> list[Ent]:
    """A painted item (Stroke, Fill or TextRun) as model-space entities, on its layer or,
    for a block, on layer 0 by block. An image is not written."""
    if isinstance(item, D.Stroke):
        out: list[Ent] = []
        for start, segs, closed in subpaths(item.path):
            if not segs:
                continue
            if closed and segs[-1][-1] != start:
                segs = [*segs, ("L", start)]
            if all(s[0] == "L" for s in segs):
                pts = [ctx.pt(start)] + [ctx.pt(s[1]) for s in segs]
                if closed and len(pts) > 2:
                    out.append(lwpolyline(pts[:-1], True, "0"))
                elif len(pts) == 2:
                    out.append(line(pts[0], pts[1], "0"))
                else:
                    out.append(lwpolyline(pts, False, "0"))
            else:
                ctrl = [ctx.pt(p) for p in _cubic_points(start, segs)]
                out.append(spline(3, _bezier_knots(len(segs)), ctrl, None, "0"))
        return _styled(out, layer=item.layer, dash=item.dash, width=item.width, grey=item.grey, block=block)
    if isinstance(item, D.Fill):
        loops = []
        lines_only = True
        for start, segs, _closed in subpaths(item.path):
            if not segs:
                continue
            lines_only = lines_only and all(s[0] == "L" for s in segs)
            loop = [ctx.pt(p) for p in _flatten(start, segs)]
            if len(loop) > 1 and loop[-1] == loop[0]:
                loop.pop()
            if len(loop) >= 3:
                loops.append(loop)
        if not loops:
            return []
        if len(loops) == 1 and lines_only and len(loops[0]) <= 4:
            ent = solid(loops[0], "0")
        else:
            ent = hatch(loops, "0")
        return _styled([ent], layer=item.layer, grey=item.grey, block=block)
    if isinstance(item, D.TextRun):
        _finite(item.x, item.y, item.size, item.angle_deg, item.width)
        value = ctx.text(item.text)
        if not value or item.size <= 0.0:
            return []
        width = item.width or fonts.measure(item.text, item.size, item.bold)
        ent = text(
            ctx.pt((item.x, item.y)),
            ctx.size(item.size * fonts.CAP_HEIGHT),
            value,
            "0",
            angle=item.angle_deg,
            anchor=item.anchor,
            width=ctx.size(width),
            bold=item.bold,
        )
        return _styled([ent], layer=item.layer, block=block)
    return []


def painted_bounds(item) -> tuple[float, float, float, float] | None:
    """A painted item's box on the sheet (text by its measured width and capitals)."""
    if isinstance(item, (D.Stroke, D.Fill)):
        pts = []
        for op in item.path:
            if isinstance(op, (tuple, list)) and op and op[0] in _OP_SIZE:
                vals = op[1:]
                pts += [(vals[i], vals[i + 1]) for i in range(0, len(vals) - 1, 2)]
        if not pts:
            return None
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)
    if isinstance(item, D.TextRun):
        width = item.width or fonts.measure(item.text, item.size, item.bold)
        x0 = item.x - {"left": 0.0, "centre": width / 2.0, "right": width}.get(item.anchor, 0.0)
        return x0, item.y, x0 + width, item.y + item.size * fonts.CAP_HEIGHT
    return None


def painted_points(item) -> list[Point]:
    """The points a painted item touches: its path's points, or its text box's corners."""
    if isinstance(item, (D.Stroke, D.Fill)):
        out = []
        for op in item.path:
            if isinstance(op, (tuple, list)) and op and op[0] in _OP_SIZE:
                vals = op[1:]
                out += [(vals[i], vals[i + 1]) for i in range(0, len(vals) - 1, 2)]
        return out
    box = painted_bounds(item)
    if box is None:
        return []
    x0, y0, x1, y1 = box
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


# --------------------------------------------------------------------------- shapes in sheet millimetres


def arrowhead(tip: Point, toward: Point, length: float) -> list[Point]:
    """A filled arrowhead (3:1) whose tip is at ``tip``, pointing away from ``toward``."""
    dx, dy = tip[0] - toward[0], tip[1] - toward[1]
    n = math.hypot(dx, dy) or 1.0
    ux, uy = dx / n, dy / n
    half = length / 6.0
    bx, by = tip[0] - ux * length, tip[1] - uy * length
    return [tip, (bx - uy * half, by + ux * half), (bx + uy * half, by - ux * half)]


def _rect(x0: float, y0: float, x1: float, y1: float) -> list[Point]:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


class Sketch:
    """Collects shapes in sheet millimetres and makes model-space entities of them."""

    def __init__(self, ctx: Context, layer: str) -> None:
        self.ctx = ctx
        self.layer = layer
        self.ents: list[Ent] = []

    def line(self, p0: Point, p1: Point) -> None:
        self.ents.append(line(self.ctx.pt(p0), self.ctx.pt(p1), self.layer))

    def poly(self, pts, closed: bool = False) -> None:
        self.ents.append(lwpolyline([self.ctx.pt(p) for p in pts], closed, self.layer))

    def circle(self, c: Point, r: float) -> None:
        self.ents.append(circle(self.ctx.pt(c), self.ctx.size(r), self.layer))

    def arc(self, c: Point, r: float, a0: float, a1: float) -> None:
        self.ents.append(arc(self.ctx.pt(c), self.ctx.size(r), a0 % 360.0, a1 % 360.0, self.layer))

    def fill(self, pts) -> None:
        self.ents.append(solid([self.ctx.pt(p) for p in pts], self.layer))

    def text(self, at: Point, height: float, value: str, **kw) -> None:
        cleaned = self.ctx.text(value)
        if not cleaned:
            return
        width = fonts.measure_height(value, height, kw.get("bold", False))
        self.ents.append(
            text(
                self.ctx.pt(at), self.ctx.size(height), cleaned, self.layer, width=self.ctx.size(width), **kw
            )
        )

    def mtext(self, top_left: Point, height: float, lines, attach: int = 1) -> None:
        tokens: list[str] = []
        for i, words in enumerate(lines):
            if i:
                tokens.append("\\P")
            tokens += self.ctx.tokens(words)
        if tokens:
            self.ents.append(
                mtext(self.ctx.pt(top_left), self.ctx.size(height), tokens, self.layer, attach=attach)
            )


# --------------------------------------------------------------------------- frames and datum symbols

# The characteristics' symbols as strokes in a unit box centred on the cell: lines
# ("L", x0, y0, x1, y1), polygons ("P", closed, points), circles ("O", cx, cy, r),
# arcs ("A", cx, cy, r, a0, a1) and arrowheads ("V", tip, tail).
GLYPHS: dict[str, tuple[tuple, ...]] = {
    "straightness": (("L", -0.5, 0.0, 0.5, 0.0),),
    "flatness": (("P", True, ((-0.5, -0.25), (0.3, -0.25), (0.5, 0.25), (-0.3, 0.25))),),
    "circularity": (("O", 0.0, 0.0, 0.4),),
    "cylindricity": (("O", 0.0, 0.0, 0.3), ("L", -0.53, -0.32, -0.08, 0.46), ("L", 0.08, -0.46, 0.53, 0.32)),
    "profile_line": (("A", 0.0, -0.2, 0.45, 0.0, 180.0),),
    "profile_surface": (("A", 0.0, -0.2, 0.45, 0.0, 180.0), ("L", -0.45, -0.2, 0.45, -0.2)),
    "angularity": (("L", -0.5, -0.35, 0.5, -0.35), ("L", -0.5, -0.35, 0.4, 0.3)),
    "perpendicularity": (("L", -0.5, -0.4, 0.5, -0.4), ("L", 0.0, -0.4, 0.0, 0.5)),
    "parallelism": (("L", -0.45, -0.45, -0.05, 0.45), ("L", 0.05, -0.45, 0.45, 0.45)),
    "position": (("O", 0.0, 0.0, 0.3), ("L", -0.5, 0.0, 0.5, 0.0), ("L", 0.0, -0.5, 0.0, 0.5)),
    "circular_runout": (("L", -0.4, -0.4, 0.4, 0.4), ("V", (0.4, 0.4), (-0.4, -0.4))),
    "total_runout": (
        ("L", -0.5, -0.45, -0.05, 0.45),
        ("L", 0.0, -0.45, 0.45, 0.45),
        ("L", -0.5, -0.45, 0.0, -0.45),
        ("V", (-0.05, 0.45), (-0.5, -0.45)),
        ("V", (0.45, 0.45), (0.0, -0.45)),
    ),
}


def draw_glyph(sk: Sketch, name: str, centre: Point, size: float) -> bool:
    """Draw a characteristic's symbol; False when there is none for ``name``."""
    shapes = GLYPHS.get(name)
    if shapes is None:
        return False
    cx, cy = centre

    def at(x: float, y: float) -> Point:
        return (cx + x * size, cy + y * size)

    for shape in shapes:
        kind = shape[0]
        if kind == "L":
            sk.line(at(shape[1], shape[2]), at(shape[3], shape[4]))
        elif kind == "P":
            sk.poly([at(*p) for p in shape[2]], shape[1])
        elif kind == "O":
            sk.circle(at(shape[1], shape[2]), shape[3] * size)
        elif kind == "A":
            sk.arc(at(shape[1], shape[2]), shape[3] * size, shape[4], shape[5])
        elif kind == "V":
            sk.fill(arrowhead(at(*shape[1]), at(*shape[2]), 0.35 * size))
    return True


def _characteristic_key(name: str) -> str:
    key = str(name).strip().lower().replace(" ", "_")
    for k, c in CHARACTERISTICS.items():
        if key in (k, c.name.replace(" ", "_")) or name == c.symbol:
            return k
    return key


def frame_cells(frame: D.FrameItem, th: float) -> tuple[list[tuple[str, str, float]], float]:
    """The cells of a frame, (kind, text, width), and its height, for text ``th`` tall."""
    h = th + 2.0 * FRAME_PAD
    cells: list[tuple[str, str, float]] = [("symbol", _characteristic_key(frame.characteristic), h)]
    zone = ("Ø" if frame.diameter else "") + str(frame.zone)
    width = fonts.measure_height(zone, th) + 2.0 * CELL_PAD
    modifier = str(frame.modifier).strip().lower()
    if modifier in ("mmc", "lmc", "m", "l"):
        width += th * 1.3
    cells.append(("zone", zone, width))
    for letter in frame.datums:
        cells.append(("datum", str(letter), fonts.measure_height(str(letter), th) + 2.0 * CELL_PAD))
    return cells, h


def frame_box(frame: D.FrameItem, at: Point, th: float) -> tuple[float, float, float, float]:
    cells, h = frame_cells(frame, th)
    return at[0], at[1], at[0] + plain_sum(c[2] for c in cells), at[1] + h


def frame_entities(frame: D.FrameItem, at: Point, ctx: Context) -> list[Ent]:
    """A feature control frame drawn from its cells, its lower left at ``at`` (sheet):
    the outline, the dividers, the symbol as strokes, the zone with its Ø and circled
    modifier, and the datum letters."""
    th = ctx.heights.dimension
    cells, h = frame_cells(frame, th)
    sk = Sketch(ctx, "0")
    x0, y0 = at
    total = plain_sum(c[2] for c in cells)
    sk.poly(_rect(x0, y0, x0 + total, y0 + h), True)
    x = x0
    for i, (kind, value, width) in enumerate(cells):
        if i:
            sk.line((x, y0), (x, y0 + h))
        if kind == "symbol":
            centre = (x + width / 2.0, y0 + h / 2.0)
            if not draw_glyph(sk, value, centre, th):
                sk.text(centre, th, value[:3].upper(), anchor="centre", middle=True)
        elif kind == "zone":
            sk.text((x + CELL_PAD, y0 + FRAME_PAD), th, value)
            modifier = str(frame.modifier).strip().lower()
            if modifier in ("mmc", "lmc", "m", "l"):
                c = (x + width - CELL_PAD - th * 0.55, y0 + h / 2.0)
                sk.circle(c, th * 0.55)
                sk.text(c, th * 0.7, "M" if modifier in ("mmc", "m") else "L", anchor="centre", middle=True)
        else:
            sk.text((x + CELL_PAD, y0 + FRAME_PAD), th, value)
        x += width
    return [in_block(e) for e in sk.ents]


def datum_shape(datum: D.DatumFeature, th: float):
    """A datum symbol's box (x0, y0, x1, y1) with its lower left at ``datum.at``, and
    its leader from the feature (first point) to the box, all on the sheet."""
    side = th + 2.0 * FRAME_PAD
    x0, y0 = float(datum.at[0]), float(datum.at[1])
    box = (x0, y0, x0 + side, y0 + side)
    leader = [(float(p[0]), float(p[1])) for p in datum.leader]
    if not leader:
        bottom = (x0 + side / 2.0, y0)
        leader = [(bottom[0], y0 - side), bottom]
    return box, leader


def datum_entities(datum: D.DatumFeature, ctx: Context) -> list[Ent]:
    """A datum feature symbol: the letter in its box, the leader, and the filled
    triangle on the feature."""
    th = ctx.heights.dimension
    box, leader = datum_shape(datum, th)
    sk = Sketch(ctx, "0")
    x0, y0, x1, y1 = box
    sk.poly(_rect(x0, y0, x1, y1), True)
    sk.text(((x0 + x1) / 2.0, (y0 + y1) / 2.0), th, str(datum.letter), anchor="centre", middle=True)
    if len(leader) >= 2:
        sk.poly(leader)
        foot, toward = leader[0], leader[1]
        dx, dy = toward[0] - foot[0], toward[1] - foot[1]
        n = math.hypot(dx, dy) or 1.0
        ux, uy = dx / n, dy / n
        half = th / 2.0
        apex = (foot[0] + ux * th * 0.866, foot[1] + uy * th * 0.866)
        sk.fill(
            [(foot[0] - uy * half, foot[1] + ux * half), (foot[0] + uy * half, foot[1] - ux * half), apex]
        )
    return [in_block(e) for e in sk.ents]


# --------------------------------------------------------------------------- notes and furniture


def note_entities(note: D.Note, ctx: Context) -> tuple[list[Ent], list[tuple[D.FrameItem, Point]]]:
    """A note as MTEXT on NOTES (its number first), its leader with an arrowhead on the
    feature (the leader's first point), and the inline frames to insert after each
    line's words, with their lower left on the sheet. ``note.at`` is the first
    line's left end on its baseline."""
    th = ctx.heights.note
    sk = Sketch(ctx, "NOTES")
    lines = []
    frames: list[tuple[D.FrameItem, Point]] = []
    pitch = th * 5.0 / 3.0  # MTEXT's single line spacing
    x0, y0 = float(note.at[0]), float(note.at[1])
    for i, entry in enumerate(note.lines):
        words, inline = entry[0], entry[1] if len(entry) > 1 else ()
        if i == 0 and note.number is not None:
            words = f"{note.number}. {words}"
        lines.append(words)
        x = x0 + fonts.measure_height(words, th) + 2.0
        for frame in inline:
            if isinstance(frame, D.FrameItem):
                frames.append((frame, (x, y0 - i * pitch - FRAME_PAD)))
                cells, _h = frame_cells(frame, ctx.heights.dimension)
                x += plain_sum(c[2] for c in cells) + 1.0
    sk.mtext((x0, y0 + th), th, lines)
    leader(sk, note.leader, ctx.heights.dimension)
    return sk.ents, frames


def leader(sk: Sketch, points, arrow: float) -> None:
    pts = [(float(p[0]), float(p[1])) for p in points]
    if len(pts) >= 2:
        sk.poly(pts)
        sk.fill(arrowhead(pts[0], pts[1], arrow))


def furniture_entities(item, ctx: Context) -> list[Ent]:
    """Sheet furniture drawn from the semantic layer, for a sheet whose painted layer
    has nothing on that item's layer."""
    h = ctx.heights
    if isinstance(item, D.CentreMark):
        sk = Sketch(ctx, "CENTER")
        cx, cy = float(item.centre[0]), float(item.centre[1])
        reach = float(item.radius) + float(item.overshoot)
        sk.line((cx - reach, cy), (cx + reach, cy))
        sk.line((cx, cy - reach), (cx, cy + reach))
        return sk.ents
    if isinstance(item, D.CentreLine):
        sk = Sketch(ctx, "CENTER")
        sk.line(item.p0, item.p1)
        return sk.ents
    if isinstance(item, D.ViewLabel):
        sk = Sketch(ctx, "NOTES")
        sk.text(item.at, h.view_label, item.text, anchor="centre")
        return sk.ents
    if isinstance(item, D.PlotStamp):
        sk = Sketch(ctx, "NOTES")
        sk.text(item.at, h.block_label, item.text)
        return sk.ents
    if isinstance(item, (D.ToleranceBlock, D.NotesBlock)):
        sk = Sketch(ctx, "TITLE" if isinstance(item, D.ToleranceBlock) else "NOTES")
        height = h.block_label if isinstance(item, D.ToleranceBlock) else h.note
        sk.mtext((float(item.at[0]), float(item.at[1]) + height), height, list(item.lines))
        return sk.ents
    if isinstance(item, D.VirtualSharp):
        return [point(ctx.pt(item.at), "DIM")]
    if isinstance(item, D.Border):
        return _border(item, ctx)
    if isinstance(item, D.TitleBlock):
        return _title_block(item, ctx)
    if isinstance(item, D.ProjectionSymbol):
        return _projection(item, ctx)
    return []


ZONE_LETTERS = "ABCDEFGHJKLMNPRTUVWY"


def _border(b: D.Border, ctx: Context) -> list[Ent]:
    _finite(b.width, b.height, b.margin)
    sk = Sketch(ctx, "BORDER")
    m, w, h = float(b.margin), float(b.width), float(b.height)
    sk.poly(_rect(m, m, w - m, h - m), True)
    th = ctx.heights.block_label
    cols = max(1, min(int(b.columns), 64))
    rows = max(1, min(int(b.rows), len(ZONE_LETTERS)))
    zw, zh = (w - 2 * m) / cols, (h - 2 * m) / rows
    for j in range(cols):
        x = m + j * zw
        if j:
            sk.line((x, m), (x, m / 2.0))
            sk.line((x, h - m), (x, h - m / 2.0))
        label = str(cols - j)  # numbers leftward from the right
        for y in (m / 2.0 - th / 2.0, h - m / 2.0 - th / 2.0):
            sk.text((x + zw / 2.0, y), th, label, anchor="centre")
    for i in range(rows):
        y = m + i * zh
        if i:
            sk.line((m, y), (m / 2.0, y))
            sk.line((w - m, y), (w - m / 2.0, y))
        label = ZONE_LETTERS[i]  # letters up from the bottom
        for x in (m / 2.0, w - m / 2.0):
            sk.text((x, y + zh / 2.0 - th / 2.0), th, label, anchor="centre")
    return sk.ents


def _title_block(tb: D.TitleBlock, ctx: Context) -> list[Ent]:
    _finite(tb.width, tb.height)
    sk = Sketch(ctx, "TITLE")
    x0, y0 = float(tb.at[0]), float(tb.at[1])
    w, h = float(tb.width), float(tb.height)
    sk.poly(_rect(x0, y0, x0 + w, y0 + h), True)
    rows = list(tb.fields)[:64]
    if not rows:
        return sk.ents
    pitch = h / len(rows)
    th = min(ctx.heights.block_label, pitch * 0.6)
    for i, (key, value) in enumerate(rows):
        top = y0 + h - i * pitch
        if i:
            sk.line((x0, top), (x0 + w, top))
        label = str(key).replace("_", " ").upper()
        sk.text((x0 + 1.5, top - pitch / 2.0 - th / 2.0), th, f"{label}: {value}")
    return sk.ents


def _projection(ps: D.ProjectionSymbol, ctx: Context) -> list[Ent]:
    """The projection symbol round ``at`` (its middle): a frustum and its end view,
    the circles on the right for third angle and on the left for first."""
    _finite(ps.size)
    sk = Sketch(ctx, "TITLE")
    s = float(ps.size)
    cx, cy = float(ps.at[0]), float(ps.at[1])
    third = ps.angle != "first"
    side = 1.0 if third else -1.0
    circles = (cx + side * 0.75 * s, cy)
    sk.circle(circles, s / 2.0)
    sk.circle(circles, s / 4.0)
    near, far = cx - side * 0.25 * s, cx - side * 1.25 * s  # the small end faces the circles
    sk.poly([(far, cy - s / 2.0), (near, cy - s / 4.0), (near, cy + s / 4.0), (far, cy + s / 2.0)], True)
    return sk.ents


def stamp_entities(stamp: D.Stamp, ctx: Context, run: D.TextRun | None = None) -> list[Ent]:
    """The PRELIMINARY stamp: TEXT on its own layer, where the sheet painted it (``run``,
    its painted text) or else at the stamp's own place in note height."""
    sk = Sketch(ctx, "STAMP")
    if run is not None:
        _finite(run.x, run.y, run.size, run.angle_deg)
        height = run.size * fonts.CAP_HEIGHT
        sk.text(
            (run.x, run.y), height, stamp.text, angle=float(run.angle_deg), anchor=run.anchor, bold=run.bold
        )
    else:
        _finite(stamp.angle_deg)
        sk.text(stamp.at, ctx.heights.note, stamp.text, angle=float(stamp.angle_deg))
    return sk.ents


__all__ = [
    "Context",
    "Ent",
    "GLYPHS",
    "Sketch",
    "arrowhead",
    "datum_entities",
    "datum_shape",
    "frame_box",
    "frame_cells",
    "frame_entities",
    "from_geometry",
    "from_painted",
    "furniture_entities",
    "in_block",
    "note_entities",
    "painted_bounds",
    "painted_points",
    "stamp_entities",
    "subpaths",
    "write_entity",
]
