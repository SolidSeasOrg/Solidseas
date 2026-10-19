"""DIMENSION entities and their blocks (``docs/DRAWINGS.md`` 6.7, 12.2).

Each :class:`~solidseas.drawing.display.Dimension` becomes one DIMENSION entity
on layer DIM in the unit's dimension style, with its own anonymous block
(``*D1``, ``*D2``, ...) holding what the sheet shows of it: the painted items
whose owner is the dimension's id, replayed (lines, arrows as SOLID or a filled
HATCH, text as TEXT), plus the definition points on DEFPOINTS. A dimension with
nothing painted gets a block drawn from its definition points.

The text is measured: ``<>`` with the parts kept round it, so ``4X Ø`` and
``THRU`` give ``4X %%c<> THRU``. A first suffix line that is THRU or a depth goes
on the value's line; the other suffix lines (counterbore, countersink, thread)
are MTEXT beside the dimension, where the sheet painted them. Basic dimensions
carry a negative ``DIMGAP`` (the box a reader draws when it regenerates) and the
box itself in the block. A dimension in a view whose scale is not the sheet's
(a detail) carries its value as explicit text and its ``DIMLFAC``, and a
precision other than the style's its ``DIMDEC`` (``DIMADEC`` for angles), as
the ``ACAD`` ``DSTYLE`` overrides in its extended data.

Definition points, in the order ``Dimension.points`` holds them:

- ``linear`` (rotated by ``angle_deg``) and ``aligned``: the first extension
  line's origin, the second's, and a point on the dimension line;
- ``radius``: the centre, then the point on the arc;
- ``diameter`` and ``hole_callout``: the point on the circle the arrow touches,
  then the opposite point;
- ``angle``: the vertex, a point on the first side, a point on the second side,
  and a point on the arc (else ``text_at``);
- ``ordinate``: the origin, the feature, the leader's end; X-type when the leader
  runs more up than across.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ...errors import InvalidArgumentError
from .. import display as D
from .. import fonts
from ..standards import DIMENSIONS, SYMBOL_DEPTH
from . import entities as E
from . import tables as T
from .tags import MAX_TEXT

ROTATED, ALIGNED, ANGULAR, DIAMETER, RADIUS, ANGULAR3, ORDINATE = 0, 1, 2, 3, 4, 5, 6
KINDS = {
    "linear": ROTATED,
    "aligned": ALIGNED,
    "angle": ANGULAR3,
    "angular": ANGULAR3,
    "diameter": DIAMETER,
    "hole_callout": DIAMETER,
    "radius": RADIUS,
    "radial": RADIUS,
    "ordinate": ORDINATE,
}
MIN_POINTS = {ROTATED: 3, ALIGNED: 3, ANGULAR3: 3, DIAMETER: 2, RADIUS: 2, ORDINATE: 3}
SCALE_TOLERANCE = 1e-9


def _bad(message: str) -> InvalidArgumentError:
    return InvalidArgumentError(message, detail={"parameter": "sheet"})


def measures(dim: D.Dimension) -> bool:
    """Whether a dimension becomes a DIMENSION entity (other kinds, such as a chamfer
    note, are written as what the sheet painted)."""
    return dim.kind in KINDS


def lfac(placement: D.ViewPlacement | None, sheet_scale: float) -> float:
    """The DIMLFAC a dimension in ``placement``'s view needs: 1 at the sheet's scale."""
    if placement is None:
        return 1.0
    scale = float(placement.scale)
    if not math.isfinite(scale) or scale <= 0.0:
        raise _bad("a view's scale must be more than nought")
    if abs(scale - sheet_scale) <= SCALE_TOLERANCE * max(scale, sheet_scale):
        return 1.0
    return sheet_scale / scale


def on_line(suffix: str) -> bool:
    """Whether a suffix line belongs on the value's line: THRU or a depth."""
    s = suffix.strip().upper()
    return s == "THRU" or s.startswith(SYMBOL_DEPTH) or s.startswith("DEEP")


def split_suffix(text: D.DimText) -> tuple[list[str], list[str]]:
    """The suffix lines on the value's line, and those written beside it."""
    lines = [str(s) for s in text.suffix]
    if lines and on_line(lines[0]):
        return lines[:1], lines[1:]
    return [], lines


def _part(ctx: E.Context, s: str) -> list[str]:
    """A user part of dimension text as MTEXT pieces, never holding a measured-value mark."""
    tokens = ctx.tokens(s)
    for i in range(len(tokens) - 1):
        if tokens[i] == "<" and tokens[i + 1] == ">":
            tokens[i] = "< "
    return tokens


def _stack(ctx: E.Context, s: str) -> list[str]:
    for ch in "^/#;":
        s = s.replace(ch, "")
    return _part(ctx, s)


def override(dim: D.Dimension, ctx: E.Context, explicit: bool) -> str:
    """The DIMENSION's text: the measured ``<>`` (or the value, when ``explicit``) with
    the prefix, what follows it, a stacked tolerance and an on-line suffix, cut whole
    pieces at a time to what a string holds."""
    t = dim.text
    tokens = _part(ctx, t.prefix) + (_part(ctx, t.value) if explicit else ["<>"]) + _part(ctx, t.after)
    if t.upper or t.lower:
        tokens += ["\\S", *_stack(ctx, t.upper), "^", *_stack(ctx, t.lower), ";"]
    same, _beside = split_suffix(t)
    for s in same:
        tokens += [" ", *_part(ctx, s)]
    out, size = [], 0
    for tok in tokens:
        if size + len(tok) > MAX_TEXT:
            break
        out.append(tok)
        size += len(tok)
    return "".join(out)


def shown(dim: D.Dimension) -> str:
    """The value's line as the sheet shows it."""
    t = dim.text
    same, _beside = split_suffix(t)
    parts = [t.prefix + t.value + t.after]
    if t.upper or t.lower:
        parts[0] += f" {t.upper}/{t.lower}"
    return " ".join(parts + same)


@dataclass
class Written:
    """A dimension as entities: the DIMENSION (model space), its block's content and
    what goes beside it in model space."""

    dimension: E.Ent
    block: list[E.Ent]
    beside: list[E.Ent] = field(default_factory=list)


def _points(dim: D.Dimension, kind: int) -> list[tuple[float, float]]:
    pts = list(dim.points)
    if len(pts) < MIN_POINTS[kind]:
        raise _bad(f"a {dim.kind} dimension needs {MIN_POINTS[kind]} definition points")
    out = []
    for p in pts[:4]:
        try:
            x, y = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            raise _bad("a definition point must be two numbers") from None
        if not (math.isfinite(x) and math.isfinite(y)):
            raise _bad("a definition point must be finite")
        out.append((x, y))
    if kind == ANGULAR3 and len(out) == 3:
        out.append((float(dim.text_at[0]), float(dim.text_at[1])))
    return out


def _unit(dx: float, dy: float) -> tuple[float, float]:
    n = math.hypot(dx, dy)
    return (dx / n, dy / n) if n > 0.0 else (1.0, 0.0)


def write(
    dim: D.Dimension,
    ctx: E.Context,
    *,
    name: str,
    painted: list,
    placement: D.ViewPlacement | None,
) -> Written:
    """The DIMENSION named block ``name`` for ``dim``; ``painted`` are its painted items."""
    kind = KINDS[dim.kind]
    pts = _points(dim, kind)
    factor = lfac(placement, ctx.sheet_scale)
    explicit = factor != 1.0
    text_at = ctx.pt(dim.text_at)
    m = [ctx.pt(p) for p in pts]
    flags = kind | 32 | 128
    if kind == ORDINATE and abs(pts[2][1] - pts[1][1]) >= abs(pts[2][0] - pts[1][0]):
        flags |= 64
    body = [(100, "AcDbDimension"), (2, name), (3, T.DIMSTYLE_OF[ctx.unit])]
    if kind in (ROTATED, ALIGNED):
        body += E.xyz(10, m[2])
    elif kind == RADIUS:
        body += E.xyz(10, m[0])
    elif kind == DIAMETER:
        body += E.xyz(10, m[1])
    elif kind == ANGULAR3:
        body += E.xyz(10, m[3])
    else:
        body += E.xyz(10, m[0])
    body += [*E.xyz(11, text_at), (70, flags), (71, 5), (1, override(dim, ctx, explicit))]
    if kind in (ROTATED, ALIGNED):
        body += [(100, "AcDbAlignedDimension"), *E.xyz(13, m[0]), *E.xyz(14, m[1])]
        if kind == ROTATED:
            angle = float(dim.angle_deg)
            if not math.isfinite(angle):
                raise _bad("a dimension's angle must be finite")
            body += [(50, angle % 360.0), (100, "AcDbRotatedDimension")]
    elif kind == RADIUS:
        body += [(100, "AcDbRadialDimension"), *E.xyz(15, m[1]), (40, 0.0)]
    elif kind == DIAMETER:
        body += [(100, "AcDbDiametricDimension"), *E.xyz(15, m[0]), (40, 0.0)]
    elif kind == ANGULAR3:
        body += [(100, "AcDb3PointAngularDimension"), *E.xyz(13, m[1]), *E.xyz(14, m[2]), *E.xyz(15, m[0])]
    else:
        body += [(100, "AcDbOrdinateDimension"), *E.xyz(13, m[1]), *E.xyz(14, m[2])]

    boxed = dim.text.boxed or "basic" in dim.flags
    entity = E.Ent("DIMENSION", "DIM", body, xdata=_overrides(dim, ctx, kind, factor, boxed))

    _same, beside_lines = split_suffix(dim.text)
    main = shown(dim)
    beside_runs = [
        item for item in painted if isinstance(item, D.TextRun) and _beside(item.text, beside_lines, main)
    ]
    kept = [item for item in painted if not any(item is r for r in beside_runs)]
    block: list[E.Ent] = []
    for item in kept:
        block += E.from_painted(item, ctx, block=True)
    if not block:
        block = _synthesised(dim, ctx, kind, pts)
    if boxed and not _has_box(kept):
        block += _box(dim, ctx, kept)
    for p in m:
        block.append(E.point(p, "DEFPOINTS"))

    beside: list[E.Ent] = []
    if beside_lines:
        th = ctx.heights.dimension
        if beside_runs:
            x0, _y0, _x1, y1 = E.painted_bounds(beside_runs[0])
            top_left = (x0, y1)
        else:
            width = fonts.measure_height(shown(dim), th)
            top_left = (float(dim.text_at[0]) - width / 2.0, float(dim.text_at[1]) - th / 2.0 - 1.5)
        sk = E.Sketch(ctx, "DIM")
        sk.mtext(top_left, th, beside_lines)
        beside = sk.ents
    return Written(entity, block, beside)


def _beside(run: str, lines: list[str], main: str) -> bool:
    """Whether a painted text run is (part of) a line written beside the dimension: its
    text is one of those lines or a piece of one that the value's line lacks."""
    piece = run.strip()
    if not piece:
        return False
    return any(piece == line.strip() for line in lines) or (
        any(piece in line for line in lines) and piece not in main
    )


def _overrides(dim: D.Dimension, ctx: E.Context, kind: int, factor: float, boxed: bool):
    over: list[tuple[int, object]] = []
    if factor != 1.0:
        over += [(1070, 144), (1040, factor)]
    precision = dim.precision
    if isinstance(precision, bool) or not isinstance(precision, int):
        raise _bad("a dimension's precision must be a whole number")
    precision = max(0, min(8, precision))
    if kind == ANGULAR3:
        if precision != T.DIMADEC:
            over += [(1070, 179), (1070, precision)]
    elif precision != T.DIMDEC[ctx.unit]:
        over += [(1070, 271), (1070, precision)]
    if boxed:
        gap = T.DIMGAP_MM / (T.INCH_MM if ctx.unit == "in" else 1.0)
        over += [(1070, 147), (1040, -gap)]
    if not over:
        return []
    return [(1001, "ACAD"), (1000, "DSTYLE"), (1002, "{"), *over, (1002, "}")]


def _has_box(painted) -> bool:
    """Whether the painted items already hold a closed four-sided stroke (the box)."""
    for item in painted:
        if isinstance(item, D.Stroke):
            for _start, segs, closed in E.subpaths(item.path):
                if closed and len(segs) in (3, 4) and all(s[0] == "L" for s in segs):
                    return True
    return False


def _box(dim: D.Dimension, ctx: E.Context, painted) -> list[E.Ent]:
    """The basic box round the value: round the painted text, else round the text the
    sheet would show at ``text_at``."""
    boxes = [E.painted_bounds(item) for item in painted if isinstance(item, D.TextRun)]
    boxes = [b for b in boxes if b is not None]
    th = ctx.heights.dimension
    if boxes:
        x0 = min(b[0] for b in boxes)
        y0 = min(b[1] for b in boxes)
        x1 = max(b[2] for b in boxes)
        y1 = max(b[3] for b in boxes)
    else:
        width = fonts.measure_height(shown(dim), th)
        cx, cy = float(dim.text_at[0]), float(dim.text_at[1])
        x0, x1, y0, y1 = cx - width / 2.0, cx + width / 2.0, cy - th / 2.0, cy + th / 2.0
    gap = T.DIMGAP_MM
    sk = E.Sketch(ctx, "0")
    sk.poly([(x0 - gap, y0 - gap), (x1 + gap, y0 - gap), (x1 + gap, y1 + gap), (x0 - gap, y1 + gap)], True)
    return [E.in_block(e) for e in sk.ents]


def _synthesised(dim: D.Dimension, ctx: E.Context, kind: int, pts) -> list[E.Ent]:
    """A block drawn from the definition points, for a dimension the sheet did not paint:
    extension and dimension lines, arrowheads and the text at ``text_at``."""
    th = ctx.heights.dimension
    arrow = th
    gap, over = DIMENSIONS.extension_gap, DIMENSIONS.extension_overrun
    sk = E.Sketch(ctx, "0")
    if kind in (ROTATED, ALIGNED):
        p1, p2, on = pts[0], pts[1], pts[2]
        if kind == ROTATED:
            a = math.radians(float(dim.angle_deg))
            d = (math.cos(a), math.sin(a))
        else:
            d = _unit(p2[0] - p1[0], p2[1] - p1[1])
        ends = []
        for p in (p1, p2):
            t = (p[0] - on[0]) * d[0] + (p[1] - on[1]) * d[1]
            e = (on[0] + d[0] * t, on[1] + d[1] * t)
            ends.append(e)
            v = _unit(e[0] - p[0], e[1] - p[1])
            if math.hypot(e[0] - p[0], e[1] - p[1]) > gap:
                sk.line((p[0] + v[0] * gap, p[1] + v[1] * gap), (e[0] + v[0] * over, e[1] + v[1] * over))
        sk.line(ends[0], ends[1])
        sk.fill(E.arrowhead(ends[0], ends[1], arrow))
        sk.fill(E.arrowhead(ends[1], ends[0], arrow))
    elif kind == DIAMETER:
        sk.line(pts[0], pts[1])
        sk.fill(E.arrowhead(pts[0], pts[1], arrow))
        sk.fill(E.arrowhead(pts[1], pts[0], arrow))
    elif kind == RADIUS:
        tail = (float(dim.text_at[0]), float(dim.text_at[1]))
        if math.hypot(tail[0] - pts[1][0], tail[1] - pts[1][1]) < 1e-9:
            tail = pts[0]
        sk.line(tail, pts[1])
        sk.fill(E.arrowhead(pts[1], tail, arrow))
    elif kind == ANGULAR3:
        v, a, b, at = pts
        r = math.hypot(at[0] - v[0], at[1] - v[1])
        if r > 0.0:
            a1 = math.degrees(math.atan2(a[1] - v[1], a[0] - v[0]))
            a2 = math.degrees(math.atan2(b[1] - v[1], b[0] - v[0]))
            loc = math.degrees(math.atan2(at[1] - v[1], at[0] - v[0]))
            if (loc - a1) % 360.0 > (a2 - a1) % 360.0:  # the arc is the other way round
                a1, a2 = a2, a1
            sk.arc(v, r, a1, a2)
            for ang, step in ((a1, 1.0), (a2, -1.0)):
                rad = math.radians(ang)
                tip = (v[0] + r * math.cos(rad), v[1] + r * math.sin(rad))
                back = math.radians(ang + step * math.degrees(arrow / r))
                sk.fill(E.arrowhead(tip, (v[0] + r * math.cos(back), v[1] + r * math.sin(back)), arrow))
    else:  # ordinate: a leader from the feature to its end
        feature, end = pts[1], pts[2]
        v = _unit(end[0] - feature[0], end[1] - feature[1])
        sk.line((feature[0] + v[0] * gap, feature[1] + v[1] * gap), end)
    sk.text((float(dim.text_at[0]), float(dim.text_at[1])), th, shown(dim), anchor="centre", middle=True)
    return [E.in_block(e) for e in sk.ents]


__all__ = ["KINDS", "Written", "lfac", "measures", "on_line", "override", "shown", "split_suffix", "write"]
