"""The laid-out sheet on screen (``docs/DRAWINGS.md`` 6.7, 15.3, 15.4): a painter on
``QPainter``, a scene with one item per owner of the painted layer, and the view
the New Drawing wizard's preview and the drawing editor show it in.

:class:`QtPainter` implements :class:`solidseas.drawing.painter.Painter`, the
interface the PDF and SVG writers implement, so the screen draws what the PDF
draws: the same painted items, replayed by the same :func:`~solidseas.drawing.
painter.paint`, in the same order. Sheet millimetres become scene units one for
one, with y turned over (the display list has y up from the sheet's lower left;
the scene has y down from its upper left). Strokes keep their width, dash
pattern (lengths in millimetres, phase 0, all zeros drawn solid, as the PDF
writer does), cap and join; fills use the nonzero rule, as the PDF's ``f`` does;
grey is 0 for black to 1 for white. Text is set in Helvetica where the
platform has it, else in the first of :data:`FAMILIES` it has, all fonts with
Helvetica's widths: Arial on Windows, Liberation Sans on the VM (the name
Helvetica alone gives Tahoma on Windows, and whatever font comes first on Qt's
offscreen platform there), at the run's font size, placed by its anchor with
the Helvetica widths
of :mod:`solidseas.drawing.fonts` and stretched along its line to those widths,
so a run is exactly as long on screen as in the PDF whatever the platform's
font; text is black, as the PDF's is. The logo is decoded by
:func:`solidseas.drawing.images.read_png`, the PDF writer's narrow reader, so a
logo the PDF leaves out is left out here too, with the same reason in
:attr:`QtPainter.problems`. A path or text run with a coordinate that is not a
finite number within 100 m of the sheet is left out and said so, never drawn.
With a ``QPainter`` given, the painter draws at once; without one it records
what it would draw, and :func:`draw` replays that, optionally all in one colour.

:class:`SheetScene` is a ``QGraphicsScene`` built from a
:class:`~solidseas.drawing.display.Sheet`: one :class:`OwnerItem` per owner of
the painted layer (a dimension's id, ``<id>-frame``, ``datum-<letter>``, a view
id, ``title``, ``n-<k>``, ``border``, ``stamp`` and the rest), each replaying its
owner's items through a :class:`QtPainter`, stacked by the first layer it draws
on, in the order of ``display.LAYERS``, so dimensions draw over views as in the
PDF. The editor picks, hovers and selects by owner:

- ``hovered(owner)`` when the pointer comes over another owner (``""`` for
  none); ``picked(owner, modifiers)`` when the left button goes down, ``""``
  on empty paper; ``moved(owner, dx_mm, dy_mm)`` when a dimension or a balloon is dragged
  and dropped, in sheet millimetres with y up (the editor turns it into
  ``edit.move``). A dragged dimension stays where it was dropped until the next
  :meth:`SheetScene.set_sheet`, which puts every item back where its sheet draws
  it; Escape during a drag puts it back at once and emits nothing.
- :meth:`~SheetScene.set_sheet` rebuilds only the owners whose painted items
  changed, were added or went, and returns them.
- :meth:`~SheetScene.select` draws owners in the selection blue,
  :meth:`~SheetScene.highlight` in a colour of the caller's (the warning colour
  by default); a dimension the sheet flags ``needs_attention`` is drawn in the
  warning colour, and the owner under the pointer in the hover colour. The hover
  colour wins, then the selection, then a highlight, then the sheet's own. The
  PRELIMINARY stamp (owner ``stamp``) is red on screen and in the thumbnail, so
  nobody mistakes the preview for a released drawing; the PDF's stamp is black.
- :meth:`~SheetScene.owner_at` finds the owner drawn nearest a scene point
  (within a few pixels of the view, or a millimetre without one), preferring the
  one on top; :meth:`~SheetScene.owners_of_feature` the dimensions (and their
  frames) whose ``refs`` name a feature; :meth:`~SheetScene.render_png` the
  sheet as a PNG for a thumbnail, in the sheet's own colours.

:class:`SheetView` is the ``QGraphicsView``: fitted to the sheet (and fitted
again when resized, until the user zooms or pans; :meth:`SheetView.fit` fits
again), zooming about the pointer on the wheel in the direction the viewer's
mouse style gives (:func:`.viewmath.wheel_factor`), panning with the middle
button, the paper white with a shadow on a page in the window's background
colour, and drawing antialiased.

Nothing here is geometric work: a scene only replays a sheet laid out elsewhere
(15.4). Speed, measured offscreen on the VM on the 100-hole plate of
``tests/test_drawing_layout.py`` (203 dimensions, 1,252 painted items, 233
owners), from a cold start: the scene is built in 25 to 60 ms and a fitted
1,600 by 1,000 view painted in 40 to 85 ms; :meth:`SheetScene.set_sheet` after
one dimension moved, both sheets read from the compact form so that every item
is compared by value, takes about 1 ms. Most of the painting is Qt antialiasing
long thin lines.
"""

from __future__ import annotations

import hashlib
import math
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from typing import Any

from PySide6.QtCore import QBuffer, QEvent, QIODevice, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPolygonF,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QStyleOptionGraphicsItem,
)

from solidseas.drawing import display as D
from solidseas.drawing import fonts
from solidseas.drawing.images import PngRefused, read_png
from solidseas.drawing.painter import ANCHORS, paint
from solidseas.errors import InvalidArgumentError

from .viewmath import STANDARD, wheel_factor

REFERENCE_PX = 100.0  # fonts are set at this pixel size and scaled to a run's size
# Helvetica, then fonts with its widths, in the order taken: Qt does not map the name
# Helvetica to Arial on Windows (it gave Tahoma on the PC) and maps it to anything on
# the offscreen platform, so the name alone is not enough there.
FAMILIES = ("Helvetica", "Arial", "Liberation Sans", "Nimbus Sans", "Nimbus Sans L", "FreeSans")
MAX_COORD = 100_000.0  # mm: what the PDF writer accepts, 100 m from the sheet
MAX_SHEET = 5080.0  # mm a side: the largest page the PDF writer makes (200 inches)
MAX_RENDER_PX = 8192  # render_png's largest side
MAX_PROBLEMS = 32
PICK_PIXELS = 5.0  # an owner is picked this near the pointer, in the view's pixels
PICK_MM = 1.0  # the same without a view, in sheet millimetres
MITER_LIMIT = 5.0  # Qt counts from the join point in pen widths: the PDF's default of 10
SELECTED_COLOUR = QColor("#1565c0")
HOVER_COLOUR = QColor("#1ea7e0")
WARNING_COLOUR = QColor("#e07b00")
STAMP_COLOUR = QColor("#c62828")
STAMP_OWNER = "stamp"  # the PRELIMINARY stamp's owner (layout.stamps)
FIT_MARGIN = 0.03  # of the sheet's larger side, round the paper when fitted
ZOOM_OUT = 0.25  # the view zooms out to this fraction of the fitted scale
ZOOM_IN = 400.0  # and in to this many pixels a millimetre
SHADOW = ((2.0, 0.0, 70), (3.0, 1.0, 40), (4.0, 2.0, 20))  # offset px, spread px, alpha

_STROKE, _FILL, _TEXT, _IMAGE = range(4)
_ARITY = {"M": 2, "L": 2, "C": 6, "Z": 0}
_CAPS = (Qt.PenCapStyle.FlatCap, Qt.PenCapStyle.RoundCap, Qt.PenCapStyle.SquareCap)
_JOINS = (Qt.PenJoinStyle.MiterJoin, Qt.PenJoinStyle.RoundJoin, Qt.PenJoinStyle.BevelJoin)
_LAYER_RANK = {name: i for i, name in enumerate(D.LAYERS)}
_BLACK = QColor(0, 0, 0)
_PENS: dict[tuple, QPen] = {}
_BRUSHES: dict[float, QBrush] = {}
_FONTS: dict[bool, tuple[QFont, QFontMetricsF]] = {}
_IMAGES: OrderedDict[bytes, QImage | str] = OrderedDict()
_MAX_CACHED = 512
_MAX_IMAGES = 8


# --------------------------------------------------------------------------- what a painter draws


def _grey(g: float) -> QColor:
    v = max(0, min(255, int(round(g * 255))))
    return QColor(v, v, v)


def _pen(width: float, dash: tuple[float, ...], cap: int, join: int, grey: float) -> QPen:
    """One pen per style, made once and shared."""
    key = (width, dash, cap, join, grey)
    pen = _PENS.get(key)
    if pen is None:
        if len(_PENS) >= _MAX_CACHED:
            _PENS.clear()
        pen = QPen(_grey(grey))
        pen.setWidthF(width)
        pen.setCapStyle(_CAPS[cap])
        pen.setJoinStyle(_JOINS[join])
        pen.setMiterLimit(MITER_LIMIT)
        if dash and width > 0.0:
            # Qt counts dashes in pen widths and needs pairs; an odd PDF pattern repeats
            pattern = list(dash) * (2 if len(dash) % 2 else 1)
            pen.setDashPattern([max(d / width, 1e-3) for d in pattern])
            pen.setDashOffset(0.0)
        _PENS[key] = pen
    return pen


def _brush(grey: float) -> QBrush:
    brush = _BRUSHES.get(grey)
    if brush is None:
        if len(_BRUSHES) >= _MAX_CACHED:
            _BRUSHES.clear()
        brush = _BRUSHES[grey] = QBrush(_grey(grey))
    return brush


def _font(bold: bool) -> tuple[QFont, QFontMetricsF]:
    """Helvetica, or the first of :data:`FAMILIES` the platform has, at the reference
    size, unhinted and unkerned (the writers apply no kerning)."""
    got = _FONTS.get(bold)
    if got is None:
        font = QFont()
        font.setFamilies(list(FAMILIES))
        font.setPixelSize(int(REFERENCE_PX))
        font.setBold(bold)
        font.setKerning(False)
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        got = _FONTS[bold] = (font, QFontMetricsF(font))
    return got


def _qimage(data: bytes) -> QImage | str:
    """The logo decoded by the PDF writer's reader, or why it was refused; the last few
    are kept."""
    key = hashlib.sha256(data).digest()
    got = _IMAGES.get(key)
    if got is not None:
        _IMAGES.move_to_end(key)
        return got
    try:
        png = read_png(data)
    except PngRefused as exc:
        got = str(exc)
    else:
        w, h = png.width, png.height
        if png.alpha is None:
            got = QImage(png.rgb, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        else:
            rgba = bytearray(w * h * 4)
            rgba[0::4] = png.rgb[0::3]
            rgba[1::4] = png.rgb[1::3]
            rgba[2::4] = png.rgb[2::3]
            rgba[3::4] = png.alpha
            got = QImage(bytes(rgba), w, h, 4 * w, QImage.Format.Format_RGBA8888).copy()
    _IMAGES[key] = got
    while len(_IMAGES) > _MAX_IMAGES:
        _IMAGES.popitem(last=False)
    return got


def _number(v: Any) -> bool:
    return isinstance(v, (int, float)) and -MAX_COORD <= v <= MAX_COORD  # NaN fails both


def _side(v: Any) -> bool:
    """Whether ``v`` is a sheet's width or height the PDF writer makes a page of."""
    return _number(v) and 0.0 < v <= MAX_SHEET


def _valid_ops(ops: Any) -> bool:
    if not isinstance(ops, (tuple, list)) or not ops:
        return False
    for i, op in enumerate(ops):
        if not isinstance(op, tuple) or not op:
            return False
        n = _ARITY.get(op[0])
        if n is None or len(op) != n + 1 or (i == 0 and op[0] != "M"):
            return False
        for v in op[1:]:
            if not _number(v):
                return False
    return True


def _append(path: QPainterPath, ops: Sequence[tuple], height: float) -> None:
    """Path operations in sheet millimetres added to ``path`` in scene units."""
    for op in ops:
        kind = op[0]
        if kind == "L":
            path.lineTo(op[1], height - op[2])
        elif kind == "M":
            path.moveTo(op[1], height - op[2])
        elif kind == "C":
            path.cubicTo(op[1], height - op[2], op[3], height - op[4], op[5], height - op[6])
        else:
            path.closeSubpath()


class _Prim:
    """One thing a :class:`QtPainter` drew: a stroked or filled path, a text run or an
    image, in scene units, with what picking needs."""

    __slots__ = (
        "kind",
        "path",
        "pen",
        "grey",
        "font",
        "text",
        "transform",
        "image",
        "rect",
        "outline",
        "_bounds",
        "_polys",
        "_tinted",
    )

    def __init__(self, kind: int) -> None:
        self.kind = kind
        self.path: QPainterPath | None = None
        self.pen: QPen | None = None
        self.grey = 0.0
        self.font: QFont | None = None
        self.text = ""
        self.transform: QTransform | None = None
        self.image: QImage | None = None
        self.rect: QRectF | None = None
        self.outline: QPolygonF | None = None  # a text run's or an image's box
        self._bounds: QRectF | None = None
        self._polys: list[list[tuple[float, float]]] | None = None
        self._tinted: tuple[int, QPen] | None = None

    @property
    def bounds(self) -> QRectF:
        if self._bounds is None:
            if self.kind == _STROKE:
                pad = self.pen.widthF() * (MITER_LIMIT if self.pen.joinStyle() == _JOINS[0] else 1.0) / 2
                self._bounds = self.path.controlPointRect().adjusted(-pad, -pad, pad, pad)
            elif self.kind == _FILL:
                self._bounds = self.path.controlPointRect()
            else:
                self._bounds = self.outline.boundingRect()
        return self._bounds

    def polylines(self) -> list[list[tuple[float, float]]]:
        """The path flattened, as lists of points (made once, when first picked)."""
        if self._polys is None:
            self._polys = [[(p.x(), p.y()) for p in poly] for poly in self.path.toSubpathPolygons()]
        return self._polys

    def tinted(self, colour: QColor) -> QPen:
        rgba = colour.rgba()
        if self._tinted is None or self._tinted[0] != rgba:
            pen = QPen(self.pen)
            pen.setColor(colour)
            self._tinted = (rgba, pen)
        return self._tinted[1]


class QtPainter:
    """A :class:`solidseas.drawing.painter.Painter` on a ``QPainter`` (``docs/DRAWINGS.md``
    6.7): sheet millimetres to scene units, y turned over.

    With ``target`` it draws on that ``QPainter`` as it is called (in ``colour`` when
    one is given); without, it records what each call draws in :attr:`prims`, for
    :func:`draw`. Strokes are kept apart: joining a style's strokes into one path was
    tried, and Qt strokes one long path far more slowly than its pieces (43 ms
    against 3 ms for the 100-hole plate's front view). :attr:`problems` lists what
    was left out and why, in words."""

    def __init__(self, target: QPainter | None = None, *, colour: Any = None) -> None:
        self.target = target
        self.colour = None if colour is None else QColor(colour)
        self.prims: list[_Prim] = []
        self.problems: list[str] = []
        self.width = 0.0
        self.height = 0.0
        self._ops: Sequence[tuple] | None = None
        self._style: tuple = (0.3, (), 0, 0, 0.0)

    def _problem(self, text: str) -> None:
        if text not in self.problems and len(self.problems) < MAX_PROBLEMS:
            self.problems.append(text)

    def _emit(self, prim: _Prim) -> None:
        if self.target is not None:
            draw(self.target, (prim,), self.colour)
        else:
            self.prims.append(prim)

    # ------------------------------------------------------------------ the protocol

    def begin_page(self, width: float, height: float) -> None:
        if not (_side(width) and _side(height)):
            raise InvalidArgumentError(
                f"a sheet must be more than 0 and at most {MAX_SHEET:.0f} mm a side",
                detail={"parameter": "sheet"},
            )
        self.width, self.height = float(width), float(height)
        self.prims = []
        self._ops = None

    def set_stroke(self, width: float, dash: Sequence[float], cap: int, join: int, grey: float) -> None:
        try:
            pattern = tuple(float(d) for d in dash)
        except (TypeError, ValueError):
            pattern = (-1.0,)
        if not (_number(width) and width >= 0.0 and all(0.0 <= d <= MAX_COORD for d in pattern)):
            self._problem("a stroke with a width or dash that is not a length was left out")
            self._style = None
            return
        if not any(d > 0.0 for d in pattern):
            pattern = ()  # all zero means solid, as the PDF writer has it
        cap = cap if cap in (0, 1, 2) and not isinstance(cap, bool) else 0
        join = join if join in (0, 1, 2) and not isinstance(join, bool) else 0
        g = min(1.0, max(0.0, float(grey))) if _number(grey) else 0.0
        self._style = (float(width), pattern, int(cap), int(join), g)

    def path(self, ops: Sequence[tuple]) -> None:
        if _valid_ops(ops):
            self._ops = ops
        else:
            self._ops = None
            self._problem("a path with an operation or coordinate a sheet cannot hold was left out")

    def _take(self) -> Sequence[tuple] | None:
        ops, self._ops = self._ops, None
        return ops

    def stroke(self) -> None:
        ops = self._take()
        if ops is None or self._style is None:
            return
        prim = _Prim(_STROKE)
        prim.path = QPainterPath()
        _append(prim.path, ops, self.height)
        prim.pen = _pen(*self._style)
        self._emit(prim)

    def fill(self, grey: float) -> None:
        ops = self._take()
        if ops is None:
            return
        prim = _Prim(_FILL)
        prim.path = QPainterPath()
        prim.path.setFillRule(Qt.FillRule.WindingFill)  # nonzero, as the PDF's f
        _append(prim.path, ops, self.height)
        prim.grey = min(1.0, max(0.0, float(grey))) if _number(grey) else 0.0
        self._emit(prim)

    def text(
        self, x: float, y: float, size: float, angle_deg: float, string: str, font: str, anchor: str
    ) -> None:
        if not isinstance(string, str) or not string:
            return
        if not (_number(x) and _number(y) and _number(size) and size > 0.0 and _number(angle_deg)):
            self._problem("a text run with a position or size a sheet cannot hold was left out")
            return
        if font not in fonts.FONTS:
            self._problem("text in a font other than Helvetica was set in Helvetica")
        if anchor not in ANCHORS:
            self._problem("text with an unknown anchor was set from its left end")
            anchor = "left"
        bold = font == fonts.FONTS[1]
        qfont, metrics = _font(bold)
        width = fonts.measure(string, size, bold)
        natural = metrics.horizontalAdvance(string)  # reference pixels
        k = size / REFERENCE_PX
        stretch = width / (natural * k) if natural > 0.0 and width > 0.0 else 1.0
        shift = {"left": 0.0, "centre": -width / 2.0, "right": -width}[anchor]
        a = math.radians(angle_deg % 360.0)
        x0, y0 = x + shift * math.cos(a), y + shift * math.sin(a)
        t = QTransform()
        t.translate(x0, self.height - y0)
        t.rotate(-angle_deg)
        t.scale(k * stretch, k)
        prim = _Prim(_TEXT)
        prim.font = qfont
        prim.text = string
        prim.transform = t
        top, bottom = metrics.ascent(), metrics.descent()
        prim.outline = t.map(QPolygonF(QRectF(0.0, -top, natural, top + bottom)))
        self._emit(prim)

    def image(self, x: float, y: float, width: float, height: float, data: bytes) -> None:
        if not all(_number(v) for v in (x, y, width, height)) or width <= 0.0 or height <= 0.0:
            self._problem("the logo was left out: its size on the sheet is not more than 0")
            return
        if not isinstance(data, (bytes, bytearray, memoryview)):
            self._problem("the logo was left out: it is not bytes")
            return
        image = _qimage(bytes(data))
        if isinstance(image, str):
            self._problem(f"the logo was left out: {image}")
            return
        prim = _Prim(_IMAGE)
        prim.image = image
        prim.rect = QRectF(x, self.height - y - height, width, height)
        prim.outline = QPolygonF(prim.rect)
        self._emit(prim)

    def group(self, name: str) -> None:
        pass  # the layers are the PDF's optional content groups; the screen shows them all

    def end_group(self) -> None:
        pass

    def end_page(self) -> None:
        self._ops = None


def draw(
    qp: QPainter, prims: Iterable[_Prim], colour: QColor | None = None, exposed: QRectF | None = None
) -> None:
    """Replay what a :class:`QtPainter` recorded on ``qp``, every item in ``colour`` when
    one is given (a light fill keeps its grey; the logo is tinted), only what meets
    ``exposed`` when given."""
    base = qp.worldTransform()
    moved = False
    for p in prims:
        if exposed is not None and not exposed.intersects(p.bounds):
            continue
        kind = p.kind
        if kind == _TEXT:
            qp.setWorldTransform(p.transform * base)
            moved = True
            qp.setFont(p.font)
            qp.setPen(_BLACK if colour is None else colour)
            qp.drawText(QPointF(0.0, 0.0), p.text)
            continue
        if moved:
            qp.setWorldTransform(base)
            moved = False
        if kind == _STROKE:
            qp.strokePath(p.path, p.pen if colour is None else p.tinted(colour))
        elif kind == _FILL:
            qp.fillPath(p.path, _brush(p.grey) if colour is None or p.grey >= 0.5 else QBrush(colour))
        else:
            qp.drawImage(p.rect, p.image)
            if colour is not None:
                tint = QColor(colour)
                tint.setAlpha(90)
                qp.fillRect(p.rect, tint)
    if moved:
        qp.setWorldTransform(base)


# --------------------------------------------------------------------------- picking arithmetic


def _segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    t = 0.0 if length <= 0.0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def _polyline_distance(polys: Iterable[Sequence[tuple[float, float]]], px: float, py: float) -> float:
    best = math.inf
    for poly in polys:
        if len(poly) == 1:
            best = min(best, math.hypot(px - poly[0][0], py - poly[0][1]))
        for (ax, ay), (bx, by) in zip(poly, poly[1:], strict=False):
            # a cheap bound first: most segments are far from the point
            if min(ax, bx) - best > px or px > max(ax, bx) + best:
                continue
            if min(ay, by) - best > py or py > max(ay, by) + best:
                continue
            best = min(best, _segment_distance(px, py, ax, ay, bx, by))
    return best


def _prim_distance(p: _Prim, x: float, y: float, tol: float) -> float | None:
    """How far (x, y) is from what ``p`` draws, or None when further than ``tol``."""
    b = p.bounds
    if x < b.left() - tol or x > b.right() + tol or y < b.top() - tol or y > b.bottom() + tol:
        return None
    if p.kind in (_TEXT, _IMAGE):
        if p.outline.containsPoint(QPointF(x, y), Qt.FillRule.OddEvenFill):
            return 0.0
        pts = [(q.x(), q.y()) for q in p.outline]
        d = _polyline_distance([pts + pts[:1]], x, y)
    elif p.kind == _FILL:
        if p.path.contains(QPointF(x, y)):
            return 0.0
        d = _polyline_distance(p.polylines(), x, y)
    else:
        d = max(0.0, _polyline_distance(p.polylines(), x, y) - p.pen.widthF() / 2.0)
    return d if d <= tol else None


# --------------------------------------------------------------------------- the scene


class OwnerItem(QGraphicsItem):
    """The group of one owner's painted items: drawn by replaying them through a
    :class:`QtPainter` (``painter.paint`` on just these items, so in layer order), in
    :attr:`colour` when the scene gives it one."""

    def __init__(self, owner: str, items: tuple, width: float, height: float) -> None:
        super().__init__()
        self.owner = owner
        self.items = items
        self.sheet_size = (width, height)
        recorder = QtPainter()
        paint(D.Sheet("", width, height, painted=items), recorder)
        self.prims = tuple(recorder.prims)
        self.problems = tuple(recorder.problems)
        rect = QRectF()
        for p in self.prims:
            rect = rect.united(p.bounds) if not rect.isNull() else QRectF(p.bounds)
        self._rect = rect
        self.colour: QColor | None = None  # what it is drawn in now; None for the sheet's own
        self.base: QColor | None = None  # its own colour on screen (the stamp's red, needs attention)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption, True)

    def boundingRect(self) -> QRectF:
        return self._rect

    def paint(self, qp: QPainter, option: QStyleOptionGraphicsItem, widget: Any = None) -> None:
        scene = self.scene()
        colour = self.base if isinstance(scene, SheetScene) and scene._plain else self.colour
        exposed = option.exposedRect if option is not None else None
        if exposed is not None and (exposed.isEmpty() or exposed.contains(self._rect)):
            exposed = None
        draw(qp, self.prims, colour, exposed)

    def distance(self, point: QPointF, tol: float) -> float | None:
        """How far a point in the item's coordinates is from what it draws, or None when
        further than ``tol``."""
        x, y = point.x(), point.y()
        best = None
        for p in self.prims:
            d = _prim_distance(p, x, y, tol)
            if d is not None and (best is None or d < best):
                best = d
                if d == 0.0:
                    break
        return best


def _owners(owners: Iterable[str] | str) -> Iterable[str]:
    return (owners,) if isinstance(owners, str) else owners


def _tolerance(widget: Any, pixels: float) -> float:
    """``pixels`` of the view a scene event came through, in scene millimetres."""
    view = widget.parent() if widget is not None else None
    if isinstance(view, QGraphicsView):
        scale = abs(view.transform().m11())
        if scale > 0.0:
            return pixels / scale
    return PICK_MM * pixels / PICK_PIXELS


class SheetScene(QGraphicsScene):
    """A laid-out sheet as a scene of :class:`OwnerItem` groups, one per owner; see the
    module's description. ``editable=False`` (the wizard's preview) never drags."""

    hovered = Signal(str)
    picked = Signal(str, object)
    moved = Signal(str, float, float)

    def __init__(self, sheet: D.Sheet | None = None, parent: Any = None, *, editable: bool = True) -> None:
        super().__init__(parent)
        self.editable = editable
        self._sheet: D.Sheet | None = None
        self._items: dict[str, OwnerItem] = {}
        self._order: tuple[str, ...] = ()
        self._selected: set[str] = set()
        self._highlight: dict[str, QColor] = {}
        self._attention: set[str] = set()
        self._dimensions: set[str] = set()
        self._features: dict[str, tuple[str, ...]] = {}
        self._hover = ""
        self._press: tuple[str, QPointF, float] | None = None
        self._drag: OwnerItem | None = None
        self._plain = False
        self._problems: tuple[str, ...] = ()
        if sheet is not None:
            self.set_sheet(sheet)

    # ------------------------------------------------------------------ the sheet

    @property
    def sheet(self) -> D.Sheet | None:
        return self._sheet

    @property
    def problems(self) -> tuple[str, ...]:
        """What the sheet holds that is not drawn, and why, in words."""
        return self._problems

    def owners(self) -> tuple[str, ...]:
        """Every owner of the painted layer, in the order the sheet first paints them."""
        return self._order

    def item(self, owner: str) -> OwnerItem | None:
        return self._items.get(owner)

    def set_sheet(self, sheet: D.Sheet) -> tuple[str, ...]:
        """Show ``sheet``, rebuilding only the owners whose painted items changed (and
        adding and removing owners); returns those owners, in sheet order with the
        removed ones last. Every item goes back where its sheet draws it, a drag in
        progress ends, and the selection and highlights keep the owners still there."""
        if not isinstance(sheet, D.Sheet):
            raise InvalidArgumentError("sheet must be a display.Sheet", detail={"parameter": "sheet"})
        size = (sheet.width, sheet.height)
        if not all(_side(v) for v in size):
            raise InvalidArgumentError(
                f"a sheet must be more than 0 and at most {MAX_SHEET:.0f} mm a side",
                detail={"parameter": "sheet"},
            )
        self.cancel_drag()
        self._press = None
        groups: dict[str, list] = {}
        problems: list[str] = []
        for it in sheet.painted:
            if not isinstance(it, D.PAINTED):
                if len(problems) < MAX_PROBLEMS:
                    problems.append(f"a {type(it).__name__} in the painted layer was left out")
                continue
            groups.setdefault(it.owner if isinstance(it.owner, str) else "", []).append(it)
        rebuilt: list[str] = []
        for owner, items in groups.items():
            items = tuple(items)
            old = self._items.get(owner)
            if old is not None and old.sheet_size == size and old.items == items:
                if not old.pos().isNull():
                    old.setPos(0.0, 0.0)
                continue
            if old is not None:
                self.removeItem(old)
            item = OwnerItem(owner, items, *size)
            self.addItem(item)
            self._items[owner] = item
            rebuilt.append(owner)
        for owner in [o for o in self._items if o not in groups]:
            self.removeItem(self._items.pop(owner))
            rebuilt.append(owner)
        # stacked by the first layer each draws on, then by where the sheet first paints it
        n = len(sheet.painted) + 1
        first: dict[str, tuple[int, int]] = {}
        for i, it in enumerate(sheet.painted):
            if isinstance(it, D.PAINTED):
                owner = it.owner if isinstance(it.owner, str) else ""
                rank = _LAYER_RANK.get(it.layer, len(D.LAYERS))
                got = first.get(owner)
                if got is None or rank < got[0]:
                    first[owner] = (rank, got[1] if got is not None else i)
        for owner, (rank, index) in first.items():
            z = rank + index / n
            item = self._items[owner]
            if item.zValue() != z:
                item.setZValue(z)
        self._order = tuple(groups)
        self._sheet = sheet
        self._read_annotations(sheet)
        self._selected &= set(self._items)
        self._highlight = {o: c for o, c in self._highlight.items() if o in self._items}
        seen = set(problems)
        for item in self._items.values():
            for text in item.problems:
                if text not in seen and len(problems) < MAX_PROBLEMS:
                    seen.add(text)
                    problems.append(text)
        self._problems = tuple(problems)
        self._restyle(self._items)
        if self.sceneRect() != QRectF(0.0, 0.0, *size):
            self.setSceneRect(QRectF(0.0, 0.0, *size))
        if self._hover and self._hover not in self._items:
            self._hover = ""
            self.hovered.emit("")
        return tuple(rebuilt)

    def _read_annotations(self, sheet: D.Sheet) -> None:
        dims: set[str] = set()
        attention: set[str] = set()
        features: dict[str, list[str]] = {}
        for a in sheet.annotations:
            if not isinstance(a, D.Dimension) or not isinstance(a.id, str):
                continue
            dims.add(a.id)
            if "needs_attention" in a.flags:
                attention.add(a.id)
            for ref in a.refs:
                if isinstance(ref, str):
                    features.setdefault(ref, []).append(a.id)
        self._dimensions = dims
        self._attention = attention
        self._features = {k: tuple(v) for k, v in features.items()}

    # ------------------------------------------------------------------ colours

    def _colour_of(self, owner: str) -> QColor | None:
        if owner and owner == self._hover:
            return HOVER_COLOUR
        if owner in self._selected:
            return SELECTED_COLOUR
        if owner in self._highlight:
            return self._highlight[owner]
        return self._base_of(owner)

    def _base_of(self, owner: str) -> QColor | None:
        if owner in self._attention:
            return WARNING_COLOUR
        if owner == STAMP_OWNER:
            return STAMP_COLOUR
        return None

    def _restyle(self, owners: Iterable[str]) -> None:
        for owner in owners:
            item = self._items.get(owner)
            if item is None:
                continue
            item.base = self._base_of(owner)
            colour = self._colour_of(owner)
            if colour != item.colour:
                item.colour = colour
                item.update()

    def select(self, owners: Iterable[str]) -> None:
        """Draw these owners in the selection blue, and no others (owners the sheet does
        not paint are ignored); one owner may be given as a string."""
        new = {o for o in _owners(owners) if o in self._items}
        old, self._selected = self._selected, new
        self._restyle(old ^ new)

    def selected(self) -> tuple[str, ...]:
        return tuple(o for o in self._order if o in self._selected)

    def highlight(self, owners: Iterable[str], colour: Any = WARNING_COLOUR) -> None:
        """Draw these owners in ``colour`` (anything ``QColor`` takes; the warning colour
        by default), replacing any earlier highlight; no owners clears it."""
        c = QColor(colour)
        if not c.isValid():
            raise InvalidArgumentError("the colour is not one Qt knows", detail={"parameter": "colour"})
        old = set(self._highlight)
        self._highlight = {o: c for o in _owners(owners) if o in self._items}
        self._restyle(old | set(self._highlight))

    def highlighted(self) -> dict[str, QColor]:
        return dict(self._highlight)

    @property
    def hover(self) -> str:
        """The owner under the pointer, ``""`` for none."""
        return self._hover

    def set_hover(self, owner: str) -> None:
        """Draw ``owner`` in the hover colour (``""`` for none), emitting ``hovered`` when
        it changes."""
        owner = owner if owner in self._items else ""
        if owner == self._hover:
            return
        old, self._hover = self._hover, owner
        self._restyle((old, owner))
        self.hovered.emit(owner)

    # ------------------------------------------------------------------ questions

    def to_scene(self, point: Sequence[float]) -> QPointF:
        """A sheet point (millimetres, y up) in scene coordinates."""
        height = self._sheet.height if self._sheet is not None else 0.0
        return QPointF(point[0], height - point[1])

    def to_sheet(self, point: QPointF) -> tuple[float, float]:
        """A scene point in sheet millimetres, y up."""
        height = self._sheet.height if self._sheet is not None else 0.0
        return (point.x(), height - point.y())

    def can_move(self, owner: str) -> bool:
        """Whether dragging ``owner`` moves it: a dimension of the sheet, or an assembly's
        item balloon, when editable."""
        movable = owner in self._dimensions or owner.startswith("balloon-")
        return self.editable and movable and owner in self._items

    def owner_at(self, point: QPointF, tolerance: float | None = None) -> str:
        """The owner drawn nearest ``point`` (scene coordinates) within ``tolerance``
        millimetres (:data:`PICK_MM` when not given), ``""`` for none. Of owners about as
        near, the one on top wins."""
        tol = PICK_MM if tolerance is None else max(0.0, float(tolerance))
        p = QPointF(point)
        box = QRectF(p.x() - tol, p.y() - tol, 2 * tol, 2 * tol)
        best, best_d = "", math.inf
        for item in self.items(
            box, Qt.ItemSelectionMode.IntersectsItemBoundingRect, Qt.SortOrder.DescendingOrder
        ):
            if not isinstance(item, OwnerItem) or not item.owner:
                continue
            d = item.distance(p - item.pos(), tol)
            if d is not None and d < best_d - 0.25 * tol:
                best, best_d = item.owner, d
        return best

    def owners_of_feature(self, feature_id: str) -> tuple[str, ...]:
        """The owners drawn for a feature: each dimension whose ``refs`` name it, with its
        frame, in sheet order."""
        dims = set(self._features.get(feature_id, ()))
        out = []
        for owner in self._order:
            if owner in dims or (owner.endswith("-frame") and owner[: -len("-frame")] in dims):
                out.append(owner)
        return tuple(out)

    def render_png(self, width_px: int) -> bytes:
        """The sheet as a PNG ``width_px`` wide, in its own colours (no hover, selection
        or highlight), for a thumbnail."""
        if isinstance(width_px, bool) or not isinstance(width_px, int) or not 1 <= width_px <= MAX_RENDER_PX:
            raise InvalidArgumentError(
                f"a thumbnail is 1 to {MAX_RENDER_PX} pixels wide", detail={"parameter": "width_px"}
            )
        if self._sheet is None:
            raise InvalidArgumentError("the scene has no sheet", detail={"parameter": "sheet"})
        paper = QRectF(0.0, 0.0, self._sheet.width, self._sheet.height)
        height_px = max(1, round(width_px * paper.height() / paper.width()))
        if height_px > MAX_RENDER_PX:
            raise InvalidArgumentError(
                f"a thumbnail is at most {MAX_RENDER_PX} pixels tall", detail={"parameter": "width_px"}
            )
        image = QImage(width_px, height_px, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor(255, 255, 255))
        qp = QPainter(image)
        qp.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self._plain = True
        try:
            self.render(qp, QRectF(0, 0, width_px, height_px), paper, Qt.AspectRatioMode.IgnoreAspectRatio)
        finally:
            self._plain = False
            qp.end()
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        return bytes(buffer.data())

    # ------------------------------------------------------------------ the mouse

    def cancel_drag(self) -> None:
        """Put a dragged item back where its sheet draws it, emitting nothing."""
        if self._drag is not None:
            self._drag.setPos(0.0, 0.0)
            self._drag = None
        self._press = None

    def mousePressEvent(self, event: Any) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        widget = event.widget()
        owner = self.owner_at(event.scenePos(), _tolerance(widget, PICK_PIXELS))
        drag = QApplication.startDragDistance() if QApplication.instance() is not None else 4
        self._press = (owner, QPointF(event.scenePos()), _tolerance(widget, float(drag)))
        event.accept()
        self.picked.emit(owner, event.modifiers())

    def mouseMoveEvent(self, event: Any) -> None:
        pos = event.scenePos()
        if self._drag is not None:
            self._drag.setPos(pos - self._press[1])
            event.accept()
            return
        if self._press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            owner, start, threshold = self._press
            if self.can_move(owner) and math.hypot(pos.x() - start.x(), pos.y() - start.y()) >= threshold:
                self._drag = self._items[owner]
                self._drag.setPos(pos - start)
            event.accept()
            return
        self.set_hover(self.owner_at(pos, _tolerance(event.widget(), PICK_PIXELS)))
        event.accept()

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        item, self._drag = self._drag, None
        self._press = None
        event.accept()
        if item is not None:
            d = item.pos()
            if d.x() or d.y():
                self.moved.emit(item.owner, d.x(), 0.0 - d.y())  # y up, never -0.0

    def mouseDoubleClickEvent(self, event: Any) -> None:
        self.mousePressEvent(event)

    def keyPressEvent(self, event: Any) -> None:
        if event.key() == Qt.Key.Key_Escape and self._drag is not None:
            self.cancel_drag()
            event.accept()
            return
        super().keyPressEvent(event)


# --------------------------------------------------------------------------- the view


class SheetView(QGraphicsView):
    """A :class:`SheetScene` on screen: fitted, wheel zoom about the pointer, middle
    button pan, the paper white with a shadow on the window's background, antialiased."""

    def __init__(self, scene: SheetScene | None = None, parent: Any = None) -> None:
        super().__init__(parent)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.wheel_style = STANDARD
        self.wheel_invert = False
        self.fitted = True  # until the user zooms or pans; a fitted view fits again when resized
        self._paper = QRectF()
        self._pan: QPointF | None = None
        if scene is not None:
            self.setScene(scene)

    def setScene(self, scene: QGraphicsScene | None) -> None:  # noqa: N802 (Qt's name)
        old = self.scene()
        if old is not None:
            try:
                old.sceneRectChanged.disconnect(self._paper_changed)
            except (RuntimeError, TypeError):
                pass
        super().setScene(scene)
        if scene is not None:
            scene.sceneRectChanged.connect(self._paper_changed)
            self._paper_changed(scene.sceneRect())

    def _paper_changed(self, rect: QRectF) -> None:
        self._paper = QRectF(rect)
        if rect.isEmpty():
            return
        room = max(rect.width(), rect.height()) * 4.0  # panning room round the paper
        self.setSceneRect(rect.adjusted(-room, -room, room, room))
        if self.fitted:
            self.fit()

    def _fit_rect(self) -> QRectF:
        m = max(self._paper.width(), self._paper.height()) * FIT_MARGIN
        return self._paper.adjusted(-m, -m, m, m)

    def fit(self) -> None:
        """Show the whole sheet, and keep it fitted while the view is resized."""
        self.fitted = True
        if not self._paper.isEmpty():
            self.fitInView(self._fit_rect(), Qt.AspectRatioMode.KeepAspectRatio)

    def scale_px_per_mm(self) -> float:
        return abs(self.transform().m11())

    def zoom(self, factor: float, at: QPointF | None = None) -> None:
        """Zoom by ``factor`` keeping the sheet point under ``at`` (viewport pixels; the
        middle when not given) where it is."""
        if self._paper.isEmpty() or not (factor > 0.0 and math.isfinite(factor)):
            return
        vp = self.viewport().rect()
        r = self._fit_rect()
        fitted = min(vp.width() / r.width(), vp.height() / r.height()) if vp.width() > 0 else 1.0
        current = self.scale_px_per_mm()
        target = min(max(current * factor, fitted * ZOOM_OUT), max(ZOOM_IN, fitted))
        if current <= 0.0 or abs(target / current - 1.0) < 1e-9:
            return
        middle = QPointF(vp.width() / 2.0, vp.height() / 2.0)
        at = middle if at is None else QPointF(at)
        inverse, _ok = self.viewportTransform().inverted()
        anchor, centre = inverse.map(at), inverse.map(middle)
        f = target / current
        self.scale(f, f)
        self.centerOn(anchor + (centre - anchor) / f)
        self.fitted = False

    def wheelEvent(self, event: Any) -> None:  # noqa: N802 (Qt's name)
        delta = event.angleDelta()
        steps = (delta.y() or delta.x()) / 120.0
        if steps:
            self.zoom(wheel_factor(steps, style=self.wheel_style, invert=self.wheel_invert), event.position())
        event.accept()

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802 (Qt's name)
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan = QPointF(event.position())
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802 (Qt's name)
        if self._pan is not None:
            now = QPointF(event.position())
            d = now - self._pan
            self._pan = now
            h, v = self.horizontalScrollBar(), self.verticalScrollBar()
            h.setValue(h.value() - round(d.x()))
            v.setValue(v.value() - round(d.y()))
            self.fitted = False
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802 (Qt's name)
        if event.button() == Qt.MouseButton.MiddleButton and self._pan is not None:
            self._pan = None
            self.viewport().unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def viewportEvent(self, event: Any) -> bool:  # noqa: N802 (Qt's name)
        if event.type() == QEvent.Type.Leave:
            scene = self.scene()
            if isinstance(scene, SheetScene):
                scene.set_hover("")
        return super().viewportEvent(event)

    def resizeEvent(self, event: Any) -> None:  # noqa: N802 (Qt's name)
        super().resizeEvent(event)
        if self.fitted:
            self.fit()

    def showEvent(self, event: Any) -> None:  # noqa: N802 (Qt's name)
        super().showEvent(event)
        if self.fitted:
            self.fit()

    def drawBackground(self, qp: QPainter, rect: QRectF) -> None:  # noqa: N802 (Qt's name)
        qp.fillRect(rect, self.palette().color(QPalette.ColorRole.Window))
        paper = self._paper
        if paper.isEmpty():
            return
        px = 1.0 / (self.scale_px_per_mm() or 1.0)
        for offset, spread, alpha in SHADOW:
            o, s = offset * px, spread * px
            qp.fillRect(paper.translated(o, o).adjusted(-s, -s, s, s), QColor(0, 0, 0, alpha))
        qp.fillRect(paper, QColor(255, 255, 255))


__all__ = [
    "HOVER_COLOUR",
    "SELECTED_COLOUR",
    "STAMP_COLOUR",
    "WARNING_COLOUR",
    "OwnerItem",
    "QtPainter",
    "SheetScene",
    "SheetView",
    "draw",
]
