"""The quick filter: a row of small toggle buttons under the name filter, one per type of
document in the opened folder, as SOLIDWORKS' Open Recent dialog has for parts,
assemblies and drawings.

The types and their order come from :mod:`.filetypes`. Each button draws its type's
glyph here, with QPainter on the button itself, so it is sharp at any display
scaling and follows the palette: a block for a part, blocks for an assembly, a
sheet for a drawing, a lettered badge for an exchange or mesh format, a grey one
for a format SolidSeas lists but cannot read, and a grey badge of the extension for
a type the table does not know (on two lines when it has five or six letters). A
button that is on has a highlighted frame and background.

With no button on, every type shows. Turning buttons on shows only their types
(several at once show all of them), and the quick filter narrows what the folder
tree, the name filter and the index's search show, as they narrow each other. All
turns every button off. Each button is a Tab stop, Space toggles it, and its
tooltip names its type and counts the files of it the list would show with the
other filters as they are, and how many of those could not be read. The row wraps
onto more lines rather than widen the list's pane. It is the list's one filter by
type: a family of formats (the meshes, say) is several buttons on at once.

The row offers the types of the rows listed (lock files, and the files of formats
SolidSeas cannot read, only when View > Show lists them:
:meth:`.DocumentFilter.listed`), and a type that is on always has its button, so the
list says why it is filtered. While a folder is being listed, Reload included, the
row keeps the buttons it had, so it neither jumps nor loses the keyboard focus. When
the listing ends, the types the folder does not have are turned off and their
buttons go; when none that was on remains, the quick filter is off and every type
shows. Hiding the lock files, or the files SolidSeas cannot read, does the same for
a type only they had. A listing that was cancelled, failed or stopped early does not
say which types the folder lacks, so the types on stay on, with their buttons, until
one does.
"""

import sys
from collections.abc import Callable, Iterable
from functools import lru_cache
from typing import Any

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPalette, QPen, QPolygonF
from PySide6.QtWidgets import QAbstractButton, QLayout, QSizePolicy, QWidget

from . import filetypes
from .filetypes import FileType
from .wording import plural, tip

GLYPH = 20  # the glyph's side, in logical pixels
BUTTON = 26  # the button's side: the glyph, a frame and room for the focus ring between them
SPACING = 2
ALL_TEXT = "All"
ALL_TIP = "Show every type: turns the quick filter's buttons off"
HINT = "Turn on to show only this type, with any other types turned on. All shows every type."
# Where the row is with the folder: none opened yet, being listed, listed only in part
# (cancelled, failed or stopped early), listed in full.
IDLE, LISTING, PARTIAL, LISTED = "idle", "listing", "partial", "listed"


# ----------------------------------------------------------------------------- glyphs
def _badge_font(font: QFont) -> QFont:
    """``font``, bold, for a badge's letters. Away from Windows its outlines are not
    hinted: FreeType's hinting snaps capitals to whole pixels, 5 or 7 tall where the
    badge has room for 6, so the letters would come out a size smaller than designed."""
    font = QFont(font)
    font.setBold(True)
    if sys.platform != "win32":
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def _face(p: QPainter, points: list[tuple[float, float]], color: QColor) -> None:
    p.setBrush(color)
    p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in points]))


def _block(p: QPainter, x: float, y: float, s: float, base: QColor) -> None:
    """An isometric block in the square at (x, y) of side s (logical pixels)."""

    def at(u: float, v: float) -> tuple[float, float]:
        return x + u * s, y + v * s

    top, ur, lr, bottom, ll, ul, mid = (
        at(0.5, 0.03),
        at(0.95, 0.27),
        at(0.95, 0.73),
        at(0.5, 0.97),
        at(0.05, 0.73),
        at(0.05, 0.27),
        at(0.5, 0.51),
    )
    pen = QPen(base.darker(185), max(0.9, 0.06 * s))
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    _face(p, [top, ur, mid, ul], base.lighter(150))
    _face(p, [ul, mid, bottom, ll], base)
    _face(p, [mid, ur, lr, bottom], base.darker(130))


def _tag(p: QPainter, rect: QRectF, letters: str, color: QColor) -> None:
    """A small badge of ``letters`` in the lower right of ``rect`` (logical pixels), its
    letters about 6 pixels tall at 100 percent."""
    s = rect.width()
    box = QRectF(rect.right() - 0.68 * s, rect.bottom() - 0.5 * s, 0.68 * s, 0.5 * s)
    _badge(p, box, letters, color.darker(115), radius=0.18)


def badge_lines(letters: str) -> list[str]:
    """The lines a badge shows ``letters`` on: one for up to four, else two, split at an
    underscore (``AD_DRW`` gives ``AD`` and ``DRW``) or in the middle (``3D``, ``XML``)."""
    if len(letters) <= 4:
        return [letters]
    head, sep, tail = letters.partition("_")
    if sep and head and tail:
        return [head, tail]
    return [letters[: len(letters) // 2], letters[len(letters) // 2 :]]


def _badge(p: QPainter, box: QRectF, letters: str, color: QColor, *, radius: float = 0.16) -> None:
    """A rounded badge filling ``box``, with ``letters`` in white, as large as fits, on
    the lines :func:`badge_lines` gives. An underscore is centred with the capitals, so
    it stays clear of the badge's edge, and baselines fall on whole device pixels."""
    p.setPen(QPen(color.darker(140), 1.0))
    p.setBrush(color)
    r = radius * min(box.width(), box.height()) * 2
    p.drawRoundedRect(box, r, r)
    if not letters:
        return
    lines = badge_lines(letters)
    gap = 0.1 * box.height() if len(lines) > 1 else 0.0
    cap = (box.height() * (0.74 if len(lines) > 1 else 0.6) - gap) / len(lines)
    font = _badge_font(p.font())
    size, stretch = min(
        _fit(font.toString(), line, round(box.width() * 0.84 * 4), round(cap * 4)) for line in lines
    )
    font.setPixelSize(size)
    font.setStretch(stretch)
    fm = QFontMetricsF(font)
    p.setFont(font)
    p.setPen(QColor("white"))
    cap_h = fm.capHeight()
    drop = max(0.0, fm.tightBoundingRect("_").bottom()) if "_" in lines[-1] else 0.0
    block = len(lines) * cap_h + (len(lines) - 1) * gap + drop
    dpr = p.device().devicePixelRatioF() if p.device() is not None else 1.0
    baseline = box.center().y() - block / 2 + cap_h
    for line in lines:
        width = fm.horizontalAdvance(line)
        p.drawText(QPointF(box.center().x() - width / 2, round(baseline * dpr) / dpr), line)
        baseline += cap_h + gap


@lru_cache(maxsize=256)
def _fit(font_spec: str, letters: str, width4: int, cap4: int) -> tuple[int, int]:
    """The largest bold pixel size, and the least narrowing (a stretch down to 70 percent),
    at which ``letters`` fit ``width4`` wide with capitals ``cap4`` tall (both in
    quarters of a logical pixel): four letters stay as tall as three, only narrower."""
    font = QFont()
    font.fromString(font_spec)
    font = _badge_font(font)
    size = max(5, int(cap4 / 4 / 0.7) + 1)
    while size > 5:
        font.setPixelSize(size)
        for stretch in (100, 90, 80, 70):
            font.setStretch(stretch)
            fm = QFontMetricsF(font)
            if fm.capHeight() * 4 <= cap4 and fm.horizontalAdvance(letters) * 4 <= width4:
                return size, stretch
        size -= 1
    return 5, 70


def paint_glyph(p: QPainter, rect: QRectF, ft: FileType) -> None:
    """Draw the glyph of ``ft`` in the square ``rect`` (logical pixels)."""
    color = QColor(filetypes.shown_color(ft))
    s = rect.width()
    x, y = rect.left(), rect.top()
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    if ft.glyph == "part":
        _block(p, x + 0.08 * s, y + 0.06 * s, 0.84 * s, color)
    elif ft.glyph == "assembly":
        _block(p, x + 0.38 * s, y + 0.0 * s, 0.6 * s, color.lighter(115))
        _block(p, x + 0.02 * s, y + 0.18 * s, 0.6 * s, color)
        _block(p, x + 0.3 * s, y + 0.4 * s, 0.6 * s, color.darker(105))
    elif ft.glyph == "drawing":
        _sheet(p, x, y, s, color)
    elif len(badge_lines(ft.letters)) > 1:  # a long extension: two lines on a square badge
        _badge(p, QRectF(x, y, s, s), ft.letters, color, radius=0.12)
    else:
        _badge(p, QRectF(x, y + 0.18 * s, s, 0.64 * s), ft.letters, color)
    if ft.glyph != "badge" and ft.letters:
        _tag(p, rect, ft.letters, color)
    p.restore()


def _sheet(p: QPainter, x: float, y: float, s: float, color: QColor) -> None:
    """A drawing sheet: a page with a folded corner, a view and a title block."""

    def at(u: float, v: float) -> QPointF:
        return QPointF(x + u * s, y + v * s)

    line = max(1.0, 0.06 * s)
    page = QPainterPath(at(0.14, 0.04))
    for u, v in ((0.62, 0.04), (0.86, 0.28), (0.86, 0.96), (0.14, 0.96)):
        page.lineTo(at(u, v))
    page.closeSubpath()
    p.setPen(
        QPen(
            color.darker(150), line, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.RoundJoin
        )
    )
    p.setBrush(QColor("#ffffff"))
    p.drawPath(page)
    fold = QPolygonF([at(0.62, 0.04), at(0.62, 0.28), at(0.86, 0.28)])
    p.setBrush(color.lighter(160))
    p.drawPolygon(fold)
    p.setPen(QPen(color.darker(115), line))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(at(0.25, 0.36), at(0.56, 0.62)))
    p.drawEllipse(QRectF(at(0.33, 0.43), at(0.48, 0.56)))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawRect(QRectF(at(0.46, 0.74), at(0.86, 0.96)))


# ----------------------------------------------------------------------------- the buttons
class TypeButton(QAbstractButton):
    """A small flat toggle button that draws a type's glyph, or the word All."""

    def __init__(self, ft: FileType | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.file_type = ft
        self.describe: Callable[[], str] | None = None  # the tooltip, worked out when it shows
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        if ft is None:
            self.setText(ALL_TEXT)
            self.setAccessibleName("All types")
            self.setAccessibleDescription(ALL_TIP)
            self.setToolTip(tip(ALL_TIP))
        else:
            self.setAccessibleName(ft.title)
            self.setAccessibleDescription("Quick filter: " + HINT)
            self.setToolTip(tip(ft.title))

    def sizeHint(self) -> QSize:
        if self.file_type is None:
            return QSize(max(BUTTON, self.fontMetrics().horizontalAdvance(ALL_TEXT) + 14), BUTTON)
        return QSize(BUTTON, BUTTON)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def event(self, e) -> bool:
        if e.type() == QEvent.Type.ToolTip and self.describe is not None:
            self.setToolTip(tip(self.describe()))
        return super().event(e)

    def _ring(self, inset: int) -> QRectF:
        """The rectangle ``inset`` device pixels in from the edge, through the middle of
        its pixels, so a one-pixel line on it is sharp at any scaling."""
        dpr = self.devicePixelRatioF()
        w, h = round(self.width() * dpr), round(self.height() * dpr)
        a = inset + 0.5
        return QRectF(a / dpr, a / dpr, (w - 2 * a) / dpr, (h - 2 * a) / dpr)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        hl = pal.color(QPalette.ColorRole.Highlight)
        on, down = self.isChecked(), self.isDown()
        hover = self.isEnabled() and self.underMouse()
        if on or down or hover:  # a frame and a tint in the highlight colour
            fill = QColor(hl)
            fill.setAlphaF(0.34 if down else 0.24 if on else 0.12)
            edge = QColor(hl)
            edge.setAlphaF(1.0 if on else 0.6)
            pen = QPen(edge, 1.0)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(fill)
            p.drawRoundedRect(self._ring(0), 3, 3)
        if self.hasFocus():  # inside the frame, clear of the glyph
            pen = QPen(pal.color(QPalette.ColorRole.Text), 1.0, Qt.PenStyle.DotLine)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(self._ring(round(self.devicePixelRatioF())), 2, 2)
        if not self.isEnabled():
            p.setOpacity(0.4)
        if self.file_type is None:
            p.setPen(pal.color(QPalette.ColorRole.ButtonText))
            font = QFont(self.font())
            font.setBold(on)
            p.setFont(font)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())
        else:
            side = float(GLYPH)
            glyph = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
            paint_glyph(p, glyph, self.file_type)
        p.end()


class FlowLayout(QLayout):
    """Lays its widgets out left to right, starting a new line when the next one would not
    fit; as narrow as its widest widget, and as tall as its lines at the width it has."""

    def __init__(self, parent: QWidget | None = None, spacing: int = SPACING) -> None:
        super().__init__(parent)
        self._items: list = []
        self._gap = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._lay(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._lay(rect, move=True)

    def sizeHint(self) -> QSize:
        width = sum(i.sizeHint().width() for i in self._items) + self._gap * max(0, len(self._items) - 1)
        height = max((i.sizeHint().height() for i in self._items), default=0)
        m = self.contentsMargins()
        return QSize(width + m.left() + m.right(), height + m.top() + m.bottom())

    def minimumSize(self) -> QSize:
        size = QSize()
        for i in self._items:
            size = size.expandedTo(i.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _lay(self, rect: QRect, *, move: bool) -> int:
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line = area.x(), area.y(), 0
        for item in self._items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            if x > area.x() and x + hint.width() > area.right() + 1:
                x, y, line = area.x(), y + line + self._gap, 0
            if move:
                item.setGeometry(QRect(x, y, hint.width(), hint.height()))
            x += hint.width() + self._gap
            line = max(line, hint.height())
        return y + line - rect.y() + m.bottom()


# ----------------------------------------------------------------------------- the row
class QuickFilterBar(QWidget):
    """The row of type buttons over a :class:`.documents.DocumentModel` and the
    :class:`.documents.DocumentFilter` it filters (see the module docstring)."""

    def __init__(self, model, proxy, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model, self.proxy = model, proxy
        self.buttons: dict[str, TypeButton] = {}
        self._present: set[str] = set()  # the types of the rows listed
        self._state = IDLE  # no folder yet; LISTING; PARTIAL or LISTED once its listing ended
        self._previous: set[str] = set()  # while listing: the buttons the row had before
        self._flow = FlowLayout(self)
        self.all_button = TypeButton(None, self)
        self.all_button.setChecked(True)
        self.all_button.clicked.connect(lambda: self.set_selected(()))
        self._flow.addWidget(self.all_button)
        self.setAccessibleName("Quick filter by type")
        self.setVisible(False)
        model.modelReset.connect(self._reset)
        model.rowsInserted.connect(self._inserted)

    # -- state ---------------------------------------------------------------------------
    def selected(self) -> frozenset[str]:
        """The types on; empty when every type shows."""
        return self.proxy.types

    def keys(self) -> list[str]:
        """The types that have a button, in the row's order."""
        return list(self.buttons)

    def set_selected(self, keys: Iterable[str]) -> frozenset[str]:
        """Turn on exactly ``keys`` (the others off) and filter the list by them. Once the
        folder is listed in full, a type it does not have is not turned on. Returns the
        types on."""
        keys = frozenset(k for k in keys if k)
        if self._state == LISTED:
            keys &= self._present
        self.proxy.set_types(keys)  # refilters only when they changed
        self._sync()
        return keys

    def reveal(self, key: str | None) -> None:
        """Make sure a row of type ``key`` is not hidden by the quick filter: its type is
        turned on too (a row with no type turns the quick filter off)."""
        types = self.proxy.types
        if types and key not in types:
            self.set_selected(types | {key} if key else ())

    def _rows_of(self, key: str) -> list:
        return [r for r in self.model.rows if r.file_type == key and self.proxy.accepts(r, types=False)]

    def count(self, key: str) -> int:
        """The rows of type ``key`` the list would show, the other filters as they are."""
        return len(self._rows_of(key))

    def tooltip_text(self, key: str) -> str:
        """The button's tooltip: its type, how many of the list's rows are of it (files,
        whatever the listing made of them) and how many of those could not be read: by
        the listing, or their geometry afterwards; or that SolidSeas cannot read the
        format at all (the files View > Show > Files SolidSeas Cannot Read lists)."""
        rows = self._rows_of(key)
        n = len(rows)
        line = f"{plural(n, 'file')} in the folder shown"
        if self.proxy.text:
            line += " that matches the filter" if n == 1 else " that match the filter"
        unsupported = sum(1 for r in rows if r.entry["status"] == "unsupported")
        unread = sum(1 for r in rows if r.entry["status"] == "error" or getattr(r, "unusable", False))
        if unsupported and unsupported == n:
            line += "; SolidSeas cannot read this format yet"
        elif unsupported:
            line += f"; {unsupported:,} of a format SolidSeas cannot read yet"
        if unread:
            line += f"; {unread:,} could not be read"
        return f"{filetypes.info(key).title}\n{line}\n{HINT}"

    # -- the listing -----------------------------------------------------------------------
    def update_types(self) -> None:
        """Work out the types offered from every row listed again (after the lock files, or
        the files SolidSeas cannot read, were shown or hidden). Once the folder is listed in
        full, a type that is on and no row has any more is turned off, as opening a folder
        without it does."""
        self._present = {r.file_type for r in self.model.rows if r.file_type and self.proxy.listed(r)}
        if self._state == LISTED and not self.proxy.types <= self._present:
            self.proxy.set_types(self.proxy.types & self._present)
        self._sync()

    def listing_done(self, result: dict[str, Any]) -> None:
        """The folder's listing ended with ``result`` (``ok``, ``cancelled``,
        ``truncated_reason``). Listed in full, the types it does not have are turned off
        and lose their buttons, and when none of the types on remains every type shows.
        Cancelled, failed or stopped early, the types on stay on with their buttons: the
        listing does not say the folder lacks them."""
        whole = bool(result.get("ok")) and not result.get("cancelled") and not result.get("truncated_reason")
        self._state = LISTED if whole else PARTIAL
        self._previous = set()
        self.update_types()

    def _reset(self) -> None:
        """The model was cleared for a folder to be listed: the buttons stay until it is."""
        self._previous = set(self.buttons)
        self._state = LISTING
        self._present = set()
        self._sync()

    def _inserted(self, _parent, first: int, last: int) -> None:
        new = {r.file_type for r in self.model.rows[first : last + 1] if r.file_type and self.proxy.listed(r)}
        if not new <= self._present:
            self._present |= new
            self._sync()

    # -- the buttons -----------------------------------------------------------------------
    def _sync(self) -> None:
        """Buttons for the types offered and the types on (and, while listing, the
        buttons the row had), in order, checked as the filter is."""
        types = self.proxy.types
        placeholders = self._previous if self._state == LISTING else set()
        wanted = filetypes.ordered(self._present | types | placeholders)
        if wanted != list(self.buttons):
            for key in [k for k in self.buttons if k not in wanted]:
                button = self.buttons.pop(key)
                self._flow.removeWidget(button)
                button.hide()  # the keyboard focus, if it had it, moves along the row now
                button.deleteLater()
            for key in wanted:
                if key not in self.buttons:
                    button = TypeButton(filetypes.info(key), self)
                    button.describe = lambda k=key: self.tooltip_text(k)
                    button.toggled.connect(lambda on, k=key: self._toggled(k, on))
                    self.buttons[key] = button
            order = [self.all_button, *(self.buttons[k] for k in wanted)]
            for w in order:
                self._flow.removeWidget(w)
            for w in order:
                self._flow.addWidget(w)
                w.show()
            self.buttons = {k: self.buttons[k] for k in wanted}
            for a, b in zip(order, order[1:], strict=False):
                QWidget.setTabOrder(a, b)
            self._flow.invalidate()
        for key, button in self.buttons.items():
            if button.isChecked() != (key in types):
                button.blockSignals(True)
                button.setChecked(key in types)
                button.blockSignals(False)
                button.update()
        self.all_button.setChecked(not types)
        self.setVisible(self._state != IDLE and bool(self.buttons))
        self.updateGeometry()

    def _toggled(self, key: str, on: bool) -> None:
        types = self.proxy.types
        self.set_selected(types | {key} if on else types - {key})
