"""The view cube over the 3D view's top-right corner, and the mark of the point the model
turns about.

:class:`ViewCube` is a small child widget of the 3D view, painted with QPainter from
the geometry :mod:`.viewcube` works out; it is not drawn with OpenGL. So it shares
no OpenGL state with the view's passes, Qt keeps its clicks away from picking and
from the model's menus, and the view's own frame (what ``grabFramebuffer`` reads,
which the self-test counts and compares pixel for pixel) is the model alone. It
fills no background, so the model shows around and through it, and it is drawn
translucent while the pointer is away from it.

A left click on a face, an edge or a corner emits ``regionClicked`` with the
region's direction, and on Home, a step arrow or a roll arrow ``homeClicked``,
``stepClicked`` or ``rollClicked``; a left-drag that starts on the cube turns the
model (``dragged``, then ``dragEnded``); a right-click on it opens its own menu
(Home, Set Current View as Home, Reset Home to Isometric, Fit). Every other press,
the middle button and the wheel everywhere, and a press on the widget's square
beside the cube, is ignored, so Qt passes it to the view, mapped to its
coordinates: a drag that starts just beside the cube turns the model, and a
right-click there opens the model's menu as before. A gesture the cube took stays
the cube's: the second click of a double-click whose first it took, wherever the
turn has moved the cube by then, and the release of a right press it took, which
opens no menu off the cube. Only :mod:`.view3d` imports this module, so with the
3D view off it is never loaded.
"""

import math

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPolygonF,
    QTransform,
)
from PySide6.QtWidgets import QMenu, QToolTip, QWidget

from . import viewcube
from .menus import relay_status_tips
from .viewmath import CLICK_SLOP, FREE, ISO_PITCH, ISO_YAW, Axes, turntable_axes
from .wording import tip

AWAY, OVER = 0.7, 1.0  # the cube's opacity while the pointer is away from it, and over it
FADE_MS = 150
# Its colours on a light background and on a dark one: faces, edges and controls, labels.
COLORS = {
    False: (QColor("#dfe5ec"), QColor("#7d8794"), QColor("#3b434d")),
    True: (QColor("#4a5260"), QColor("#9aa3ae"), QColor("#e6e9ed")),
}
HIGHLIGHT = QColor.fromRgbF(0.20, 0.55, 1.0)  # the model's selection blue
HIGHLIGHT_SHARE = 0.6
CONTROL_TIPS = {
    viewcube.HOME: "Home: the view this document opened with, or the one you set (Home key)",
    "step-up": "Turn the face above to the front",
    "step-down": "Turn the face below to the front",
    "step-left": "Turn the face on the left to the front",
    "step-right": "Turn the face on the right to the front",
    "roll-ccw": "Roll the view counter-clockwise to the next quarter turn",
    "roll-cw": "Roll the view clockwise to the next quarter turn",
}


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor.fromRgbF(
        a.redF() + (b.redF() - a.redF()) * t,
        a.greenF() + (b.greenF() - a.greenF()) * t,
        a.blueF() + (b.blueF() - a.blueF()) * t,
    )


def _scaled(c: QColor, f: float) -> QColor:
    return QColor.fromRgbF(min(c.redF() * f, 1.0), min(c.greenF() * f, 1.0), min(c.blueF() * f, 1.0))


class ViewCube(QWidget):
    """The view cube. :meth:`follow` turns it with the camera; ``hover`` is what the
    pointer is over (a region, a button's name, or None) and ``target_opacity`` the
    opacity it is fading to."""

    regionClicked = Signal(tuple)  # a face, an edge or a corner: its direction
    homeClicked = Signal()
    stepClicked = Signal(str)  # step-up, step-down, step-left or step-right
    rollClicked = Signal(int)  # 1 counter-clockwise, -1 clockwise
    dragged = Signal(float, float)  # pixels across and down since the last move
    dragEnded = Signal()
    homeSet = Signal(bool)  # True: the current view becomes Home; False: Home is the isometric again
    fitClicked = Signal()

    def __init__(self, view: QWidget) -> None:
        super().__init__(view)
        self.setObjectName("viewcube")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.axes: Axes = turntable_axes(ISO_YAW, ISO_PITCH)
        self.mode = FREE
        self.hover: tuple | str | None = None
        self.has_home = False  # a Home of the user's own is set: the menu offers to drop it
        self.opacity = self.target_opacity = AWAY
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(FADE_MS)
        self._fade.valueChanged.connect(self._faded)
        # The press this widget took: what it was on and where, and whether it became a drag.
        self._press: tuple | None = None
        self._last = QPointF()
        self._dragging = False
        self._swallow_release = False
        # When (ms) the last left press this widget saw was one it took, for the double-click
        # that may follow; the right press it took and where; whether its release, on the
        # cube and not dragged, asks for the cube's menu (Windows asks after the release).
        self._clicked_at: int | None = None
        self._right_at: QPointF | None = None
        self._menu_ok = False
        self.menu: QMenu | None = None  # the menu last opened, while it is open

    # -- what it shows -----------------------------------------------------------------------
    @property
    def side(self) -> int:
        return self.width()

    def follow(self, axes: Axes, mode: str = FREE) -> None:
        """Turn with the camera: repaint only when its axes (or its rotation mode, which
        decides the roll arrows) changed."""
        if axes == self.axes and mode == self.mode:
            return
        self.axes, self.mode = axes, mode
        if self.hover is not None and not isinstance(self.hover, str):
            self.hover = None  # the region under the pointer moved; the next move finds it again
        self.update()

    @property
    def pressed(self) -> bool:
        """Whether a left press this widget took is under way (a click or a drag of the cube)."""
        return self._press is not None

    @property
    def shown(self) -> frozenset[str]:
        return viewcube.shown_controls(self.axes, self.mode)

    def at(self, x: float, y: float) -> tuple | str | None:
        """What the widget point ``(x, y)`` is on: a button's name, a region's direction, or
        None. Buttons first: they lie off the cube."""
        control = viewcube.control_at(x, y, self.side, self.shown)
        if control is not None:
            return control
        return viewcube.region_at(self.axes, x, y, self.side)

    def _dark(self) -> bool:
        source = self.parentWidget() or self
        return source.palette().color(QPalette.ColorRole.Base).lightness() < 128

    def colors(self) -> tuple[QColor, QColor, QColor]:
        """Faces, edges and controls, labels: for the background drawn now."""
        return COLORS[self._dark()]

    def cell_color(self, cell: viewcube.Cell, highlighted: bool = False) -> QColor:
        """A cell's fill: its face's colour lit as the model's faces are, in the selection
        blue where the pointer is."""
        face = _scaled(self.colors()[0], 0.7 + 0.3 * cell.shade)
        return _mix(face, HIGHLIGHT, HIGHLIGHT_SHARE) if highlighted else face

    # -- painting ----------------------------------------------------------------------------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self.opacity)
        self.paint(p)
        p.end()

    def picture(self) -> QImage:
        """The cube as it is painted, fully opaque, in device pixels: what the self-test
        reads, since the view's own frame never holds it."""
        dpr = self.devicePixelRatioF()
        img = QImage(
            max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr)), QImage.Format.Format_ARGB32
        )
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint(p)
        p.end()
        return img

    def paint(self, p: QPainter) -> None:
        size = self.side
        if size <= 0:
            return
        _face, edge, label = self.colors()
        cells = viewcube.cells(self.axes, size)
        faces: dict[tuple, list[viewcube.Cell]] = {}
        for c in cells:
            faces.setdefault(c.face, []).append(c)
        hover = self.hover if isinstance(self.hover, tuple) else None
        pen = QPen(edge, 1.2)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        for face, mine in sorted(faces.items(), key=lambda kv: kv[1][0].facing):
            outline = self._face_polygon(face, size)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.cell_color(mine[0]))
            p.drawPolygon(outline)
            if hover is not None:
                p.setBrush(self.cell_color(mine[0], True))
                for c in mine:
                    if c.region == hover:
                        p.drawPolygon(QPolygonF([QPointF(*pt) for pt in c.polygon]))
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolygon(outline)
            if mine[0].facing > viewcube.LABEL_FACING:
                self._label(p, face, size, label)
        self._controls(p, size, edge)

    def _face_polygon(self, face: tuple, size: int) -> QPolygonF:
        ox, oy, ax, ay, bx, by = viewcube.label_frame(self.axes, face, size)
        pts = [(ox + ax * u + bx * v, oy + ay * u + by * v) for u, v in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        return QPolygonF([QPointF(x, y) for x, y in pts])

    def label_pixels(self, size: int) -> float:
        """The labels' pixel size: the largest at which BOTTOM fits
        :data:`.viewcube.LABEL_WIDTH` of a face's edge, and never above
        :data:`.viewcube.LABEL_HEIGHT` of it."""
        edge = 2 * viewcube.HALF * size
        font = QFont(self.font())
        font.setBold(True)
        font.setPixelSize(100)
        wide = QFontMetricsF(font).horizontalAdvance(viewcube.LONGEST_LABEL)
        return max(1.0, min(viewcube.LABEL_WIDTH * edge * 100 / max(wide, 1.0), viewcube.LABEL_HEIGHT * edge))

    def _label(self, p: QPainter, face: tuple, size: int, color: QColor) -> None:
        """The face's name, drawn through the map from the face's own square to where it
        lands (:func:`.viewcube.label_frame`), so it lies on the face, upright as the face
        is in its own view."""
        h = viewcube.HALF * size
        ox, oy, ax, ay, bx, by = viewcube.label_frame(self.axes, face, size)
        # Text runs right and down in pixels of a face seen square on: u to the right, -v down.
        p.save()
        p.setTransform(QTransform(ax / h, ay / h, -bx / h, -by / h, ox, oy), True)
        font = QFont(self.font())
        font.setBold(True)
        font.setPixelSize(max(1, round(self.label_pixels(size))))
        p.setFont(font)
        p.setPen(color)
        p.drawText(QRectF(-h, -h, 2 * h, 2 * h), Qt.AlignmentFlag.AlignCenter, viewcube.LABELS[face])
        p.restore()

    def _controls(self, p: QPainter, size: int, color: QColor) -> None:
        shown = self.shown
        rects = viewcube.control_rects(size)
        for name in sorted(shown):
            x, y, w, h = rects[name]
            c = HIGHLIGHT if self.hover == name else color
            p.setPen(QPen(c, max(1.2, size / 90), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            if name == viewcube.HOME:
                self._house(p, QRectF(x, y, w, h), c)
            elif name in viewcube.ROLLS:
                self._roll(p, QRectF(x, y, w, h), c, name == "roll-cw")
            else:
                self._arrow(p, QRectF(x, y, w, h), c, viewcube.STEP_SIDES[name])

    @staticmethod
    def _house(p: QPainter, r: QRectF, c: QColor) -> None:
        m = r.width() * 0.15
        x0, x1, y0, y1 = r.left() + m, r.right() - m, r.top() + m, r.bottom() - m
        mid, eave = (x0 + x1) / 2, y0 + (y1 - y0) * 0.45
        roof = QPolygonF([QPointF(x0, eave), QPointF(mid, y0), QPointF(x1, eave)])
        p.drawPolyline(roof)
        inset = (x1 - x0) * 0.17
        p.drawPolyline(
            QPolygonF(
                [
                    QPointF(x0 + inset, eave - 1),
                    QPointF(x0 + inset, y1),
                    QPointF(x1 - inset, y1),
                    QPointF(x1 - inset, eave - 1),
                ]
            )
        )

    @staticmethod
    def _arrow(p: QPainter, r: QRectF, c: QColor, side: tuple[int, int]) -> None:
        cx, cy, s = r.center().x(), r.center().y(), r.width() * 0.42
        dx, dy = side
        tip_ = QPointF(cx + dx * s, cy + dy * s)
        a = QPointF(cx - dx * s * 0.6 + dy * s, cy - dy * s * 0.6 + dx * s)
        b = QPointF(cx - dx * s * 0.6 - dy * s, cy - dy * s * 0.6 - dx * s)
        p.setBrush(c)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF([tip_, a, b]))

    @staticmethod
    def _roll(p: QPainter, r: QRectF, c: QColor, clockwise: bool) -> None:
        """A curved arrow, round three quarters of a circle, its head at the end it turns to."""
        m = r.width() * 0.2
        box = r.adjusted(m, m, -m, -m)
        start, span = (120.0, -250.0) if clockwise else (60.0, 250.0)
        path = QPainterPath()
        path.arcMoveTo(box, start)
        path.arcTo(box, start, span)
        p.drawPath(path)
        end = math.radians(start + span)
        rad = box.width() / 2
        tip_ = QPointF(box.center().x() + rad * math.cos(end), box.center().y() - rad * math.sin(end))
        turn = -1.0 if clockwise else 1.0  # the arc's direction at its end, on the screen
        along = QPointF(-math.sin(end) * turn, -math.cos(end) * turn)
        out = QPointF(math.cos(end), -math.sin(end))
        k = r.width() * 0.16
        p.setBrush(c)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(
            QPolygonF(
                [tip_ + along * k, tip_ - along * (k * 0.4) + out * k, tip_ - along * (k * 0.4) - out * k]
            )
        )

    # -- the pointer -------------------------------------------------------------------------
    def _faded(self, value) -> None:
        self.opacity = float(value)
        self.update()

    def _fade_to(self, opacity: float) -> None:
        if opacity == self.target_opacity:
            return
        self.target_opacity = opacity
        self._fade.stop()
        self._fade.setStartValue(self.opacity)
        self._fade.setEndValue(opacity)
        self._fade.start()

    def enterEvent(self, event) -> None:
        self._fade_to(OVER)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._fade_to(AWAY)
        self._set_hover(None)
        super().leaveEvent(event)

    def _set_hover(self, what) -> None:
        if what != self.hover:
            self.hover = what
            self.update()
        if what is None:
            self.unsetCursor()
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:
        pos = event.position()
        what = self.at(pos.x(), pos.y())
        left = event.button() == Qt.MouseButton.LeftButton
        if left:
            self._clicked_at = None
        elif event.button() == Qt.MouseButton.RightButton:
            self._right_at = None
        if what is None or event.button() not in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            event.ignore()  # beside the cube, or the middle button: the view's
            return
        view = self.parentWidget()
        if view is not None:
            view.setFocus(Qt.FocusReason.MouseFocusReason)
        self._set_hover(what)
        if left:
            self._press = (what, QPointF(pos))
            self._last = QPointF(pos)
            self._dragging = False
            self._clicked_at = event.timestamp()
        else:
            self._right_at = QPointF(pos)  # the cube's menu follows with the context menu event
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if self._press is None:
            if event.buttons() != Qt.MouseButton.NoButton:
                event.ignore()  # a drag the view took: its moves are the view's
                return
            self._set_hover(self.at(pos.x(), pos.y()))
            event.accept()
            return
        what, start = self._press
        if not self._dragging:
            if abs(pos.x() - start.x()) + abs(pos.y() - start.y()) <= CLICK_SLOP:
                return
            if isinstance(what, str):  # a drag that starts on a button does nothing
                self._dragging = True
                self._press = (None, start)
                return
            self._dragging = True
            self._set_hover(None)
            from .view3d import rotate_cursor

            self.setCursor(rotate_cursor())
        if self._press[0] is not None:
            dx, dy = pos.x() - self._last.x(), pos.y() - self._last.y()
            if dx or dy:
                self.dragged.emit(dx, dy)
        self._last = QPointF(pos)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._swallow_release:
            self._swallow_release = False
            event.accept()
            return
        pos = event.position()
        if event.button() == Qt.MouseButton.RightButton:
            start, self._right_at = self._right_at, None
            if start is None:
                event.ignore()  # a right press the view took
                return
            moved = abs(pos.x() - start.x()) + abs(pos.y() - start.y())
            self._menu_ok = moved <= CLICK_SLOP and self.at(pos.x(), pos.y()) is not None
            event.accept()  # the cube's press: its release is the cube's, wherever it lands
            return
        if self._press is None or event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        (what, _start), self._press = self._press, None
        dragging, self._dragging = self._dragging, False
        if dragging:
            if what is not None:
                self.dragEnded.emit()
            self._set_hover(self.at(pos.x(), pos.y()))
        else:
            self._click(what)
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        """The first click already turned the view: the second does nothing more, on the cube
        and wherever the turn has moved the cube from under the pointer meanwhile (a step
        arrow hides once the view leaves the face, a corner moves away), if the cube took the
        first click. Otherwise the view's (a fit, or opening the component there)."""
        pos = event.position()
        if event.button() == Qt.MouseButton.LeftButton and (
            self._took_first(event) or self.at(pos.x(), pos.y()) is not None
        ):
            self._swallow_release = True
            event.accept()
            return
        event.ignore()

    def _took_first(self, event) -> bool:
        """Whether this widget took the first click of the double-click ``event``."""
        if self._clicked_at is None:
            return False
        interval = QGuiApplication.styleHints().mouseDoubleClickInterval()
        return 0 <= event.timestamp() - self._clicked_at <= interval

    def _click(self, what) -> None:
        if what == viewcube.HOME:
            self.homeClicked.emit()
        elif what in viewcube.STEPS:
            self.stepClicked.emit(what)
        elif what in viewcube.ROLLS:
            self.rollClicked.emit(1 if what == "roll-ccw" else -1)
        elif isinstance(what, tuple):
            self.regionClicked.emit(what)

    def make_menu(self) -> QMenu:
        """The cube's own menu: Home, Set Current View as Home, Reset Home to Isometric
        (when a Home of your own is set) and Fit."""
        menu = relay_status_tips(QMenu(self))
        menu.setToolTipsVisible(True)
        home = menu.addAction("Home")
        home.setToolTip(tip(CONTROL_TIPS[viewcube.HOME]))
        home.triggered.connect(self.homeClicked.emit)
        set_home = menu.addAction("Set Current View as Home")
        set_home.setToolTip(tip("Home and this document's next opening while the viewer runs show this view"))
        set_home.triggered.connect(lambda: self.homeSet.emit(True))
        reset = menu.addAction("Reset Home to Isometric")
        reset.setToolTip(tip("Home is the isometric view, fitted, again"))
        reset.setEnabled(self.has_home)
        reset.triggered.connect(lambda: self.homeSet.emit(False))
        menu.addSeparator()
        fit = menu.addAction("Fit")
        fit.setToolTip(tip("Show the whole model from this direction (F)"))
        fit.triggered.connect(self.fitClicked.emit)
        return menu

    def contextMenuEvent(self, event) -> None:
        """On the cube, its own menu, for a right-click the cube took (or the menu key);
        beside it the model's, which the view opens. A right press dragged here from the
        view, or from the cube's regions to beside them, is no click on the cube."""
        mine = True
        if event.reason() == QContextMenuEvent.Reason.Mouse:
            if QGuiApplication.mouseButtons() & Qt.MouseButton.RightButton:
                mine = self._right_at is not None  # asked on the press, which the cube took
            else:
                mine = self._menu_ok  # asked on the release
        self._menu_ok = False
        if not mine or self.at(event.pos().x(), event.pos().y()) is None:
            event.ignore()
            return
        event.accept()
        self.menu = self.make_menu()
        self.run_menu(self.menu, event.globalPos())
        self.menu.deleteLater()
        self.menu = None

    def run_menu(self, menu: QMenu, where) -> None:
        """Show ``menu`` at ``where`` until it closes (tests stand in for it)."""
        menu.exec(where)

    def event(self, e) -> bool:
        """Over the cube, what a click there does; beside it, the view's tooltip."""
        if e.type() == QEvent.Type.ToolTip:
            what = self.at(e.pos().x(), e.pos().y())
            if what is None:
                e.ignore()
                return False
            text = CONTROL_TIPS[what] if isinstance(what, str) else viewcube.tooltip(what)
            QToolTip.showText(e.globalPos(), tip(text), self)
            return True
        return super().event(e)


class PivotMark(QWidget):
    """A small dot where the model turns about the point under the pointer, in the
    selection blue with a white ring; mouse events pass through it."""

    SIZE = 11  # pixels: a 7 pixel dot and its ring

    def __init__(self, view: QWidget) -> None:
        super().__init__(view)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.resize(self.SIZE, self.SIZE)
        self.hide()

    def show_at(self, x: float, y: float) -> None:
        self.move(round(x - self.SIZE / 2), round(y - self.SIZE / 2))
        self.show()
        self.raise_()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("white"), 2.0))
        p.setBrush(HIGHLIGHT)
        p.drawEllipse(QRectF(2, 2, self.SIZE - 4, self.SIZE - 4))
        p.end()
