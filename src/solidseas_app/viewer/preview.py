"""The Preview tab: the stored preview image to pan and zoom, and the optional 3D view.

:class:`ImageView` draws the preview image, already decoded and scaled in a
worker, with pan and zoom (:class:`.viewmath.ImageZoom`): the wheel zooms
toward the cursor, in the direction the mouse style gives, dragging with any
button pans, a double-click fits. It never decodes the image again: zoomed out
it draws a copy scaled once per zoom level, zoomed in it draws only the visible
part of the image it holds.

:class:`PreviewPane` is the whole tab: a bar with Image and 3D (3D only when
the setting is on), the zoom controls, the view and a caption. The user's
choice of Image or 3D holds from one document to the next. Parts and
assemblies are drawn in 3D; a drawing shows its stored image, with the 3D
button off and a note saying why, and the next part or assembly is in 3D
again.

An assembly's 3D view colours each component file in its own colour, with a
legend over the view's corner that the Legend button shows and hides (an
assembly of more than :data:`LEGEND_SHOWN_UP_TO` files starts with it hidden
until the user chooses; it keeps to a third of the view's height and scrolls,
and a click on a file picks every instance of it), and its bar has a
configuration list that is the Components tab's: choosing one here reads the
Components tab in it too, and choosing one there redraws the view. An instance
with no mesh drawn that has a box stored in the assembly is drawn as that box
(:mod:`.view3d`), unless Settings > Boxes for Missing Meshes is off
(:meth:`PreviewPane.set_boxes`, which draws the assembly again without reading
it); the legend's last row stands for the boxes, and a click on it picks them
all. A status line under the view counts the boxes by reason and names the
instances that could not be shown at all and why (a missing file, no saved
mesh, the triangle limit). A second bar, for
assemblies, explodes the view (:mod:`.explode`): the Explode slider moves the
components apart, each top-level component as one or every part on its own,
following the slider closely while it is dragged or stepped and easing to an
amount set at once (a page step, Collapse, Back), and Collapse puts them back.
An assembly with one top-level component uses Every part unless a level was
chosen for it, and a note on the bar says so; with one part the slider is off.
It is for display only: the amount holds while the configuration changes, and
a new document starts collapsed. Back puts back the amount, the level and the
camera (:meth:`PreviewPane.restore_camera`) once the scene arrives.

Clicking an assembly's instance in the 3D view picks it: the view draws it in
the selection blue and fades the others, a note over the view's corner names
it, and ``instancePicked`` asks the Components tab to select its row; a row
selected there comes back as :meth:`PreviewPane.highlight_instance` (a
sub-assembly's row picks all its parts) or :meth:`PreviewPane.highlight_file`
(a file's row, every instance of it). A double-click on an instance
(``instanceActivated``) opens its file as a double-click on its row does, and
a right-click (``instanceMenu``) asks for that row's menu. The view numbers
instances; this pane turns the numbers into component tree ids, the boxes'
after the meshes'. An instance the library read from a sub-assembly's own file,
which the Components tab has no row for, is picked, named and opened all the
same; the note says which row of the tab stands for it (:attr:`PreviewPane.row_of`).

What the view shows of each component is the user's to choose: right-clicking a
component in the view, its row on the Components tab, or a file in the legend or
the Files table offers Transparency, Hide (Show once all of it is hidden),
Isolate, Show all and Reset appearance, and right-clicking empty space 3D Print
This Assembly, then Show all and Reset appearance once something is hidden or
changed (a part's view offers 3D Print This Part anywhere); in the view, Tab hides
the part under the pointer and Shift+Tab shows everything hidden, as in SOLIDWORKS.
The pane keeps those choices for the document while it is shown (:mod:`.appearance`,
by component tree id and file key, so they hold through another configuration for whatever is
there, and Back puts them back with :meth:`PreviewPane.view_state`), works out
each instance's look and has the view draw it; the legend greys a file all
hidden, and ``looksChanged`` lets the Components tab mark its rows. A file is
every instance of it, and a sub-assembly's file every part of every instance of
it (the Components tab gives the pane each component's file,
:meth:`PreviewPane.set_components`); where the view draws none of what a menu is
for, its look items are greyed with the reason. The right-click picks what the
menu is for, and a look chosen from it drops that pick (``pickDropped``), since a
pick fades everything else; a hidden instance is never drawn picked. A part's
menu in the view also has a submenu for each sub-assembly it is in, and for each
a check item that explodes it or keeps it together whatever the Explode bar's
level says (a sub-assembly's own row has it as "Explode this sub-assembly"),
greyed inside one chosen to stay together (:func:`.explode.group_of`); those
choices are each document's while the viewer runs, the bar counts the groups
they make and names those that hold in the scene drawn, and Reset appearance
drops them with the rest.

The 3D view is made the first time it is needed, from :mod:`.view3d`, which
is only imported then: with the setting off the viewer never loads OpenGL.
Starting OpenGL holds the window for about 0.6 s on a desktop graphics card
(the driver loads and the window turns to OpenGL drawing), so "Starting
OpenGL..." is drawn first. Turning to OpenGL drawing makes a shown window again,
which on Windows looks like the viewer closing and opening, so with the setting
on the view is made before the window is first shown (:meth:`PreviewPane.prepare_view`,
from the launcher), and when the setting is turned on.
The pane then asks the window for the mesh with ``meshRequested``; the window
reads it in the mesh process and hands back the result. Once OpenGL has
failed in the view, later parts say so without reading their mesh.

Every text shown here is plain text.
"""

import os
from array import array
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QActionGroup, QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSlider,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .appearance import BOXES, FILE, ID, TRANSPARENCY_STEPS, Look, Looks
from .explode import FULL_SECONDS as EXPLODE_SECONDS
from .explode import LEVELS, PARTS, TOP, explodes, group_of, held_by, subassemblies
from .menus import relay_status_tips
from .mesh3d import byte_budget
from .modelview import is_internal
from .viewmath import (
    FREE,
    SOLIDWORKS,
    STANDARD,
    TURNTABLE,
    VIEW_KEYS,
    ImageZoom,
    wheel_factor,
    wheel_text,
)
from .wording import (
    BOXES_SETTING,
    LIMITS,
    box_text,
    error_message,
    faces_left_out_text,
    not_shown_text,
    plural,
    seconds_text,
    sources_text,
    tip,
)

IMAGE, MODEL = "image", "3d"
_SMOOTH_UP_TO = 3.0  # zoomed in further than this, pixels are drawn sharp
_PAINT_FIRST_MS = 30  # time for "Starting OpenGL..." to reach the screen before the window is held
_MODEL_TIP = "Rotate, pan and zoom the saved display meshes of a part or an assembly"
# Where a 3D file of another format's triangles came from (.mesh3d.read_model_scene).
MODEL_SOURCES = {
    "mesh": "from the file's own triangles",
    "bodies": "made from the file's B-rep bodies",
    "display_mesh": "from the display mesh the file stores",
}
_NO_3D = {"drawing": "a drawing has no 3D model of its own"}
_IN_3D = ("part", "assembly")
LEGEND_ROWS = 400  # files the legend lists; the rest are counted in its last row
LEGEND_SHOWN_UP_TO = 12  # files: an assembly with more starts with its legend hidden
LEGEND_HEIGHT = 1 / 3  # of the view: a longer legend scrolls
LEGEND_WIDTH = 0.4  # of the view, at most
BOX_ROLE = Qt.ItemDataRole.UserRole + 1  # the legend's row of the boxes
# The legend's swatch of the boxes: the view's grey, with the dark edge it draws them with.
BOX_SWATCH, BOX_SWATCH_EDGE = "#b8bfc8", "#4b535d"
# Slider actions the view follows closely instead of easing: a drag, a key's or the wheel's step.
_FOLLOWED = (
    QAbstractSlider.SliderAction.SliderMove.value,
    QAbstractSlider.SliderAction.SliderSingleStepAdd.value,
    QAbstractSlider.SliderAction.SliderSingleStepSub.value,
)


ROTATION_TEXT = {
    FREE: "Rotation is free: a drag across turns the model about the screen's vertical axis, up or down "
    "about its horizontal axis, to any view.",
    TURNTABLE: "Rotation is a turntable: a drag across turns the model about its vertical axis, up or down "
    "tilts it, at most to straight above or below.",
}


CUBE_TEXT = (
    "The view cube turns with the model: click a face, an edge or a corner to look from there, its "
    "house (or the Home key) for the view the document opened with."
)
# What Page Up and Page Down do: a turntable never rolls, but looking straight down or up the
# same turn on the screen is its yaw.
ROLL_KEYS_TEXT = {
    FREE: "Page Up and Page Down roll it",
    TURNTABLE: "Page Up and Page Down roll it looking straight down or up",
}


def controls_text(
    style: str,
    invert: bool = False,
    *,
    assembly: bool = False,
    rotation: str = FREE,
    cube: bool = True,
    opens_files: bool = True,
) -> str:
    """How the 3D view is driven; for an assembly, how its components are picked, and, when
    any is a file of its own (``opens_files``), that a double-click opens it."""
    if style == SOLIDWORKS:
        drag = "Middle-drag rotates, Ctrl+middle-drag pans, Shift+middle-drag zooms"
    else:
        drag = "Left-drag rotates, right-drag pans"
    fit = "Double-click empty space or F fits" if assembly else "Double-click or F fits"
    home = CUBE_TEXT if cube else "The Home key goes back to the view the document opened with."
    text = (
        f"{drag}, {wheel_text(style, invert)} toward the cursor. {ROTATION_TEXT.get(rotation, '')} {fit}; "
        f"arrow keys turn the model, {ROLL_KEYS_TEXT.get(rotation, ROLL_KEYS_TEXT[FREE])}, Ctrl+1 to Ctrl+7 "
        f"give the standard views and R the isometric. {home}"
    )
    if assembly and opens_files:
        text += (
            " Click a component to pick it here and on the Components tab (Esc lets go), "
            "double-click it to open its file, right-click it for more."
        )
    elif assembly:  # objects inside the file shown: none has a file of its own to open
        text += (
            " Click a component to pick it here and on the Components tab (Esc lets go), "
            "right-click it for more."
        )
    return text


def files_text(files: int, internal: int = 0) -> str:
    """What an assembly's instances are of: files, or a model file's own objects."""
    if internal and internal >= files:
        return plural(files, "object")
    if internal:
        return f"{plural(files - internal, 'file')} and {plural(internal, 'object')}"
    return plural(files, "file")


def no_3d_text(doc_type: str | None) -> str:
    return (
        "The 3D view is for parts and assemblies: "
        + _NO_3D.get(doc_type or "", "this document is neither")
        + "."
    )


def choices_text(choices: dict[str, bool]) -> str:
    """The sub-assemblies chosen to explode or to stay together, in words: ``by your
    choice, sub-1 explodes and panel-1 stays together``; up to two named on each side."""

    def named(ids: list[str]) -> str:
        if len(ids) > 2:
            return plural(len(ids), "sub-assembly", "sub-assemblies")
        return " and ".join(i.rpartition("/")[2] for i in ids)

    on = sorted(k for k, v in choices.items() if v)
    off = sorted(k for k, v in choices.items() if not v)
    parts = []
    if on:
        parts.append(f"{named(on)} {'explodes' if len(on) == 1 else 'explode'}")
    if off:
        parts.append(f"{named(off)} {'stays' if len(off) == 1 else 'stay'} together")
    return "by your choice, " + " and ".join(parts) if parts else ""


class Legend(QListWidget):
    """The component files of the assembly in the 3D view, each with its colour, over
    the view's top-right corner, under the view cube: at most :data:`LEGEND_WIDTH` of the
    view's width and :data:`LEGEND_HEIGHT` of its height, scrolling past that, so it never
    hides more than that corner of the model. A click on a file picks every instance of it
    (``filePicked``, its key), as its row of the Files table does. A last row says what
    the grey boxes are, when the view draws any, and a click on it picks them all
    (``boxesPicked``). It follows the view's size and the cube's; plain text only."""

    filePicked = Signal(str)
    boxesPicked = Signal()
    fileMenu = Signal(str, QPoint)  # a file right-clicked, and where: its menu
    boxesMenu = Signal(QPoint)  # the boxes' row right-clicked

    def __init__(self, view: QWidget) -> None:
        super().__init__(view)
        self.setObjectName("legend")
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setIconSize(QSize(12, 12))
        self.setUniformItemSizes(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setStyleSheet(
            "QListWidget#legend { background: rgba(127, 127, 127, 0.18); border-radius: 4px; padding: 2px; }"
        )
        self.setToolTip(
            tip(
                "Each component file in its colour, with its instances shown. Click a file to pick every "
                "instance of it. Legend hides this."
            )
        )
        self.itemClicked.connect(self._clicked)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.setProperty("reservesArea", True)  # the view fits the model beside it, not under it
        view.installEventFilter(self)
        if hasattr(view, "layoutChanged"):  # the view cube came, went or changed size
            view.layoutChanged.connect(self._place)
        self.hide()

    def set_files(self, files: list[dict], boxes: int = 0) -> None:
        """The files, and with ``boxes`` (how many the view draws) the row of the boxes."""
        self.clear()
        for f in files[:LEGEND_ROWS]:
            swatch = QPixmap(12, 12)
            swatch.fill(QColor(f["color"]))
            item = QListWidgetItem(QIcon(swatch), f"{f['name']} ({f['instances']:,})")
            shown = plural(f["instances"], "instance")
            item.setToolTip(tip(f"{f['name']}: {shown} shown. Click to pick them."))
            item.setData(Qt.ItemDataRole.UserRole, f.get("key") or "")
            self.addItem(item)
        if len(files) > LEGEND_ROWS:
            self.addItem(QListWidgetItem(f"and {plural(len(files) - LEGEND_ROWS, 'more file')}"))
        if boxes:
            swatch = QPixmap(12, 12)
            swatch.fill(QColor(BOX_SWATCH))
            painter = QPainter(swatch)
            painter.setPen(QColor(BOX_SWATCH_EDGE))
            painter.drawRect(0, 0, 11, 11)
            painter.end()
            item = QListWidgetItem(QIcon(swatch), f"Box: no mesh drawn ({boxes:,})")
            item.setToolTip(
                tip(
                    f"{plural(boxes, 'instance')} with no mesh drawn (a file not found, one that stores no "
                    "display data, or a limit of the 3D view reached) drawn as the box the assembly stores "
                    "for each. Click to pick them all."
                )
            )
            item.setData(BOX_ROLE, True)
            self.addItem(item)
        self._place()

    def _clicked(self, item: QListWidgetItem) -> None:
        if item.data(BOX_ROLE):
            self.boxesPicked.emit()
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if key:
            self.filePicked.emit(key)

    def _context_menu(self, pos: QPoint) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        where = self.viewport().mapToGlobal(pos)
        if item.data(BOX_ROLE):
            self.boxesMenu.emit(where)
        elif item.data(Qt.ItemDataRole.UserRole):
            self.fileMenu.emit(item.data(Qt.ItemDataRole.UserRole), where)

    def show_hidden(self, hidden: set[str], boxes_hidden: bool) -> None:
        """Grey the rows of the files whose every instance is hidden (by key), and the
        boxes' row with ``boxes_hidden``."""
        grey = self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
        for i in range(self.count()):
            item = self.item(i)
            off = boxes_hidden if item.data(BOX_ROLE) else item.data(Qt.ItemDataRole.UserRole) in hidden
            item.setData(Qt.ItemDataRole.ForegroundRole, grey if off else None)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.parent() and event.type() == QEvent.Type.Resize:
            self._place()
        return False

    def _place(self) -> None:
        view = self.parentWidget()
        if view is None:
            return
        margin = 8
        rows = max(self.count(), 1)
        row = self.sizeHintForRow(0) if self.count() else self.fontMetrics().height() + 4
        widest = max(
            (self.fontMetrics().horizontalAdvance(self.item(i).text()) for i in range(self.count())),
            default=60,
        )
        whole = rows * row + 8
        height = max(row + 8, min(whole, int(view.height() * LEGEND_HEIGHT)))
        if whole > height:
            widest += self.verticalScrollBar().sizeHint().width()
        width = min(widest + 44, max(120, int(view.width() * LEGEND_WIDTH)))
        top = view.legend_top() if hasattr(view, "legend_top") else margin  # under the view cube
        height = max(min(height, view.height() - top - margin), 1)
        self.setGeometry(view.width() - width - margin, top, width, height)
        self._reserve()

    def _reserve(self) -> None:
        """Tell the view the legend moved, came or went, so it fits the model beside it."""
        view = self.parentWidget()
        if view is not None and hasattr(view, "overlays_changed"):
            view.overlays_changed()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._reserve()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if self.isHidden():  # hidden itself: not with its view, nor as the view goes
            self._reserve()


class PickNote(QLabel):
    """What is picked in the 3D view, over its bottom-left corner; plain text, hidden
    when nothing is."""

    def __init__(self, view: QWidget) -> None:
        super().__init__(view)
        self.setObjectName("picknote")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet(
            "QLabel#picknote { background: rgba(127, 127, 127, 0.22); border-radius: 4px; padding: 3px 6px; }"
        )
        view.installEventFilter(self)
        self.hide()

    def show_text(self, text: str) -> None:
        self.setText(text)
        self.setVisible(bool(text))
        self._place()
        if text:
            self.raise_()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.parent() and event.type() == QEvent.Type.Resize:
            self._place()
        return False

    def _place(self) -> None:
        view = self.parentWidget()
        if view is None:
            return
        margin = 8
        widest = max(120, view.width() - 2 * margin)
        width = min(self.fontMetrics().horizontalAdvance(self.text()) + 20, widest)
        height = self.heightForWidth(width)
        self.setGeometry(margin, view.height() - height - margin, width, max(height, 1))


class ImageView(QWidget):
    """A picture to pan and zoom. ``zoomChanged`` follows every change of scale."""

    zoomChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setMinimumSize(1, 1)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(tip("Wheel: zoom toward the pointer. Drag: pan. Double-click: fit."))
        self.zoom = ImageZoom()
        self.mouse_style = STANDARD
        self.invert_wheel = False
        self.placeholder = ""
        self._pix: QPixmap | None = None
        self._source_width = 0
        self._scaled: tuple[float, QPixmap] | None = None
        self._drag: QPointF | None = None

    # -- content -------------------------------------------------------------------------
    @property
    def pixmap(self) -> QPixmap | None:
        return self._pix

    def set_image(self, pix: QPixmap | None, source_width: int | None = None) -> None:
        """Show ``pix``, fitted. ``source_width`` is the stored image's width, when the
        worker scaled it down, so the zoom percentage is of the stored image."""
        self._pix = pix if pix is not None and not pix.isNull() else None
        self._scaled = None
        self._source_width = source_width or (self._pix.width() if self._pix else 0)
        self.zoom.view_w, self.zoom.view_h = max(self.width(), 1), max(self.height(), 1)
        if self._pix is not None:
            self.zoom.set_image(self._pix.width(), self._pix.height())
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.zoom.set_image(0, 0)
            self.unsetCursor()
        self.update()
        self.zoomChanged.emit()

    def clear(self, placeholder: str = "") -> None:
        self.placeholder = placeholder
        self.set_image(None)

    @property
    def percent(self) -> float | None:
        """The zoom as a percentage of the stored image's size, or None with no image."""
        if self._pix is None or not self._source_width:
            return None
        return self.zoom.scale * self._pix.width() / self._source_width * 100

    def fit(self) -> None:
        self.zoom.fit()
        self._changed()

    def actual_size(self) -> None:
        """One pixel of the stored image to one pixel of the screen."""
        if self._pix is not None and self._source_width:
            self.zoom.zoom_to(self._source_width / self._pix.width())
            self._changed()

    def zoom_by(self, factor: float, at: tuple[float, float] | None = None) -> None:
        if self._pix is not None:
            self.zoom.zoom(factor, at)
            self._changed()

    def _changed(self) -> None:
        self.update()
        self.zoomChanged.emit()

    # -- drawing -------------------------------------------------------------------------
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.zoom.resize(self.width(), self.height())
        self.zoomChanged.emit()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), self.palette().color(QPalette.ColorRole.Base))
        if self._pix is None:
            if self.placeholder:
                p.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
                p.drawText(
                    self.rect().adjusted(24, 24, -24, -24),
                    Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                    self.placeholder,
                )
            p.end()
            return
        x, y, w, h = self.zoom.rect()
        s = self.zoom.scale
        if s < 1.0:
            # Smaller than the image held: scale it once for this zoom level, then
            # panning only moves that copy.
            if self._scaled is None or self._scaled[0] != s:
                self._scaled = (
                    s,
                    self._pix.scaled(
                        max(1, round(w)),
                        max(1, round(h)),
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    ),
                )
            p.drawPixmap(QPointF(round(x), round(y)), self._scaled[1])
        else:
            # Larger: Qt draws only the part of the image that is in view.
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, s <= _SMOOTH_UP_TO)
            p.drawPixmap(QRectF(x, y, w, h), self._pix, QRectF(self._pix.rect()))
        p.end()

    # -- the mouse and keys -------------------------------------------------------------
    def wheelEvent(self, event) -> None:
        steps = event.angleDelta().y() / 120.0
        if steps and self._pix is not None:
            pos = event.position()
            factor = wheel_factor(steps, style=self.mouse_style, invert=self.invert_wheel)
            self.zoom_by(factor, (pos.x(), pos.y()))
        event.accept()

    def mousePressEvent(self, event) -> None:
        if self._pix is not None and event.button() in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.RightButton,
            Qt.MouseButton.MiddleButton,
        ):
            self._drag = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag is None:
            return
        pos = event.position()
        self.zoom.pan(pos.x() - self._drag.x(), pos.y() - self._drag.y())
        self._drag = pos
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._drag = None
        if self._pix is not None:
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseDoubleClickEvent(self, event) -> None:
        self.fit()

    def contextMenuEvent(self, event) -> None:
        event.accept()  # the right button pans here

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_by(1.25)
        elif key == Qt.Key.Key_Minus:
            self.zoom_by(0.8)
        elif key in (Qt.Key.Key_0, Qt.Key.Key_F):
            self.fit()
        elif key == Qt.Key.Key_1:
            self.actual_size()
        else:
            super().keyPressEvent(event)


def _tool(text: str, tip_text: str, *, checkable: bool = False) -> QToolButton:
    b = QToolButton()
    b.setText(text)
    b.setToolTip(tip(tip_text))
    b.setCheckable(checkable)
    b.setAutoRaise(not checkable)
    b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    return b


class PreviewPane(QWidget):
    """The Preview tab's content. ``meshRequested`` asks the window to read the
    selected part's or assembly's display meshes (an assembly in
    :attr:`configuration`); it answers with :meth:`set_mesh_result`. ``warmUp`` says
    the 3D view is starting, so the window can start the mesh process meanwhile.
    ``configurationChosen`` says the user chose another configuration of the
    assembly in the bar, for the Components tab to follow.

    ``preferred`` is the user's choice of the Image and 3D buttons; ``mode`` is
    what is shown, which is the image for a drawing, and for a document whose image
    was asked for from the Overview tab (:meth:`show_image_once`)."""

    meshRequested = Signal()
    warmUp = Signal()
    configurationChosen = Signal(str)
    instancePicked = Signal(str)  # an instance clicked in the 3D view, by component tree id; "" for none
    instanceActivated = Signal(str)  # an instance double-clicked: open its file
    instanceMenu = Signal(str, QPoint)  # an instance right-clicked, and where
    filePicked = Signal(str)  # a file clicked in the legend: every instance of it, by file key
    boxesPicked = Signal()  # the boxes' row clicked in the legend: every instance drawn as a box
    looksChanged = Signal()  # what is hidden or transparent changed, for the Components tab
    pickDropped = Signal()  # a look chosen from a menu dropped the pick: no row stays current

    def __init__(self) -> None:
        super().__init__()
        self.preferred = IMAGE
        self.mode = IMAGE
        self.image_once = False  # the image shown for this document only, preferred left alone
        self.enabled_3d = False
        self.mouse_style = STANDARD
        self.invert_wheel = False
        self.rotation_mode = FREE
        self.show_cube = True  # Settings > View Cube in the 3D View
        self.about_pointer = True  # Settings > Turn About the Point Under the Pointer
        # Home in the 3D view, a camera state, for each document whose user set one there,
        # under :attr:`document_key`, while the viewer runs: its scenes open at it.
        self._homes_by_document: dict[Any, dict[str, Any]] = {}
        self._drawn_key: Any = None  # the document whose scene the 3D view shows, while it does
        self.doc_type: str | None = None
        self.model_file = False  # a 3D file of another format (set by the details panel)
        self.mesh_state = "idle"
        self.mesh_info: dict[str, Any] = {}
        self.view: QWidget | None = None  # the 3D view, made when first needed
        self.view_factory: Callable[[], QWidget] | None = None  # tests replace the 3D view
        self.gl_check: Callable[[], tuple[bool, str]] | None = None
        self.gl_result: tuple[bool, str] | None = None  # what the OpenGL check said, once made
        self.image_caption = ""
        self.configuration: str | None = None  # the assembly configuration to show; None: as the file says
        self.requested_configuration: str | None = None  # the one the mesh in the view, or on its way, is of
        self.legend: Legend | None = None
        # The exploded view: the level the user chose holds from one document to the next
        # (``session_level``); ``explode_level`` is the one this document uses, which is
        # Every part when it has a single top-level component and the user has not chosen
        # here. The amount (percent) holds only while the document stays.
        self.session_level = TOP
        self.explode_level = TOP
        self.level_chosen = False  # the user, or Back, chose this document's level: no automatic one
        self.explode_value = 0
        self._slider_action: tuple[int, int] | None = None  # the slider's last action, and where to
        # The camera Back puts back once the scene of that configuration arrives.
        self._pending_camera: tuple[dict[str, Any], str | None] | None = None
        self.instance_ids: list[str] = []  # the assembly's instances, in the view's order
        self.instance_files: list[int] = []  # the index in ``files`` of each one's file
        # For an instance read from a sub-assembly's own file, which no row of the
        # Components tab stands for, the document its mesh was read from when that is the
        # part's own: {"path", "nested", "configuration", "name"} by instance id, for its
        # 3D Print entry (:attr:`.mesh3d.SceneBuffers.documents`); for one drawn from what its
        # sub-assembly stores of it, its own file not found: {"name", "stored_path",
        # "reason"}, for the entry off with the reason (:attr:`.mesh3d.SceneBuffers.missing`).
        self.instance_documents: dict[str, dict[str, Any]] = {}
        self.instance_missing: dict[str, dict[str, Any]] = {}
        self.files: list[dict[str, Any]] = []  # the legend's files
        self.explode_groups: dict[str, int] = {}
        # The instances drawn as boxes come last, from ``box_from`` in ``instance_ids``: their
        # file keys, file names and the reasons they have no mesh.
        self.draw_boxes = True  # Settings > Boxes for Missing Meshes
        self.box_from = 0
        self.box_keys: list[str | None] = []
        self.box_names: list[str | None] = []
        self.box_reasons: list[str] = []
        # The assembly read last, to draw again when the boxes are turned on or off: its
        # buffers, its geometry, the triangle cap it was read under and the read's seconds.
        self.assembly: tuple[Any, dict[str, Any], int | None, float] | None = None
        # What is picked: ("instance", id), every instance under that id, ("file", key),
        # every instance of that file, or ("boxes", ""), every instance drawn as a box;
        # kept for the next scene of the same document.
        self.highlight: tuple[str, str] | None = None
        self.pick_note: PickNote | None = None
        # The id of the Components tab's row that stands for an instance: its own, or for
        # one read from a sub-assembly's own file that sub-assembly's; None when the tab
        # has none (the details panel sets it).
        self.row_of: Callable[[str], str | None] | None = None
        # The details panel's menu for a file (Open, Show in File Explorer, Go to file and
        # Show in folder list), which the legend's menu starts with; None when there is none.
        self.file_menu: Callable[[str], QMenu | None] | None = None
        # The window's 3D Print entry for the document shown, which the menu of the view's
        # empty space starts with (:meth:`space_menu`): it adds it to a menu and says whether
        # it did; None: no such entry.
        self.print_shown: Callable[[QMenu], bool] | None = None
        # What the user chose to see: hidden and transparent components (:mod:`.appearance`),
        # for this document while it is shown, and the sub-assemblies chosen to explode or
        # stay together, by id, which each document keeps while the viewer runs
        # (``_choices_by_document``, under :attr:`document_key`). ``instance_looks`` is each
        # instance's look as the view draws it.
        self.looks = Looks()
        self.explode_choices: dict[str, bool] = {}
        self.document_key: Any = None
        self._choices_by_document: dict[Any, dict[str, bool]] = {}
        self.instance_looks: list[Look] = []
        # The sub-assemblies' files, as the Components tab read them: each one's file key by
        # its component tree id, and each file's name by its key (:meth:`set_components`).
        self.component_files: dict[str, str] = {}
        self.component_names: dict[str, str] = {}
        self._pieces: tuple | None = None  # the last count of :meth:`explode_pieces`, and what it was of

        self.image_button = _tool("Image", "The preview image SOLIDWORKS stored", checkable=True)
        self.model_button = _tool("3D", _MODEL_TIP, checkable=True)
        self.image_button.setChecked(True)
        group = QButtonGroup(self)
        group.setExclusive(True)
        group.addButton(self.image_button)
        group.addButton(self.model_button)
        self.image_button.clicked.connect(lambda: self.set_mode(IMAGE))
        self.model_button.clicked.connect(lambda: self.set_mode(MODEL))
        self.model_button.setVisible(False)
        self.image_button.setVisible(False)

        self.zoom_out = _tool("−", "Zoom out (minus key)")
        self.zoom_label = QLabel()
        self.zoom_label.setTextFormat(Qt.TextFormat.PlainText)
        self.zoom_label.setMinimumWidth(self.zoom_label.fontMetrics().horizontalAdvance("00000%") + 8)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setToolTip(tip("Zoom, as a share of the stored image's size"))
        self.zoom_in = _tool("+", "Zoom in (plus key)")
        self.fit_button = _tool("Fit", "Fit the view (double-click, or F)")
        self.actual_button = _tool("1:1", "One image pixel to one screen pixel (1 key)")
        self.iso_button = _tool("Isometric", "Back to the isometric view, fitted (R, or Ctrl+7)")
        self.config_label = QLabel("Configuration:")
        self.config_combo = QComboBox()
        self.config_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.config_combo.setToolTip(
            tip("The assembly configuration drawn; the Components tab shows the same one")
        )
        self.config_combo.activated.connect(
            lambda i: self.choose_configuration(self.config_combo.itemText(i))
        )
        self.legend_button = _tool(
            "Legend",
            "Show or hide the colour of each component file. An assembly of more than "
            f"{LEGEND_SHOWN_UP_TO} files starts with it hidden, until you choose here.",
            checkable=True,
        )
        self.legend_button.setChecked(True)
        self.legend_button.toggled.connect(lambda _on: self._show_legend())
        self.legend_chosen = False  # the user showed or hid the legend: their choice holds
        self.legend_button.clicked.connect(self._legend_button_clicked)

        bar = QHBoxLayout()
        bar.setContentsMargins(6, 2, 6, 2)
        bar.setSpacing(2)
        bar.addWidget(self.image_button)
        bar.addWidget(self.model_button)
        bar.addSpacing(10)
        bar.addWidget(self.config_label)
        bar.addWidget(self.config_combo)
        bar.addStretch(1)
        bar.addWidget(self.legend_button)
        for w in (self.zoom_out, self.zoom_label, self.zoom_in, self.actual_button, self.iso_button):
            bar.addWidget(w)
        bar.addWidget(self.fit_button)

        self.explode_label = QLabel("Explode:")
        self.explode_slider = QSlider(Qt.Orientation.Horizontal)
        self.explode_slider.setRange(0, 100)
        self.explode_slider.setSingleStep(5)
        self.explode_slider.setPageStep(25)
        self.explode_slider.setMinimumWidth(100)
        self.explode_slider.setMaximumWidth(260)
        self.explode_slider.setToolTip(
            tip(
                "Move the components apart, away from the assembly's centre, for display only: "
                "nothing is changed in the file"
            )
        )
        self.explode_slider.actionTriggered.connect(self._slider_acted)
        self.explode_slider.valueChanged.connect(self._explode_changed)
        self.explode_percent = QLabel()
        self.explode_percent.setTextFormat(Qt.TextFormat.PlainText)
        self.explode_percent.setMinimumWidth(self.explode_percent.fontMetrics().horizontalAdvance("100%") + 6)
        self.explode_combo = QComboBox()
        for key, text in LEVELS.items():
            self.explode_combo.addItem(text, key)
        self.explode_combo.setToolTip(
            tip(
                "Move each top-level component as one (a sub-assembly with its parts), or every part "
                "on its own"
            )
        )
        self.explode_combo.activated.connect(lambda i: self.set_explode_level(self.explode_combo.itemData(i)))
        self.collapse_button = _tool("Collapse", "Put every component back where it is placed")
        self.collapse_button.clicked.connect(self.collapse)
        # Play: the explode and the collapse as one animation, from where the bar is
        self.play_button = _tool("Play", "Explode the assembly all the way, then collapse it again")
        self.play_button.clicked.connect(self.toggle_play)
        self._play_timer = QTimer(self)
        self._play_timer.setSingleShot(True)
        self._play_timer.timeout.connect(self._play_next)
        self._play_step = 0  # 0 not playing, 1 exploding, 2 holding then collapsing
        # Why the bar does what it does when that is not obvious: one top-level component, so
        # every part moves; or one part, so nothing can.
        self.explode_hint = QLabel()
        self.explode_hint.setTextFormat(Qt.TextFormat.PlainText)
        hint_font = self.explode_hint.font()
        hint_font.setItalic(True)
        self.explode_hint.setFont(hint_font)
        # Cut short in a narrow panel rather than widening it, which would move the window's
        # splitter each time a note comes and goes; the tooltip has it whole.
        self.explode_hint.setMinimumWidth(1)
        explode_bar = QHBoxLayout()
        explode_bar.setContentsMargins(6, 0, 6, 2)
        explode_bar.setSpacing(4)
        explode_bar.addWidget(self.explode_label)
        explode_bar.addWidget(self.explode_slider, 1)
        explode_bar.addWidget(self.explode_percent)
        explode_bar.addWidget(self.explode_combo)
        explode_bar.addWidget(self.collapse_button)
        explode_bar.addWidget(self.play_button)
        explode_bar.addWidget(self.explode_hint)
        explode_bar.addStretch(1)
        self.explode_row = QWidget()
        self.explode_row.setLayout(explode_bar)
        self.explode_row.hide()
        self._explode_text()

        self.image = ImageView()
        self.image.zoomChanged.connect(self._zoom_changed)
        self.zoom_out.clicked.connect(lambda: self.image.zoom_by(0.8))
        self.zoom_in.clicked.connect(lambda: self.image.zoom_by(1.25))
        self.actual_button.clicked.connect(self.image.actual_size)
        self.fit_button.clicked.connect(self.fit)
        self.iso_button.clicked.connect(self._isometric)

        self.model_message = QLabel()
        self.model_message.setTextFormat(Qt.TextFormat.PlainText)
        self.model_message.setWordWrap(True)
        self.model_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.model_message.setContentsMargins(24, 24, 24, 24)
        self.model_message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.model_stack = QStackedWidget()
        self.model_stack.addWidget(self.model_message)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.image)
        self.stack.addWidget(self.model_stack)

        self.caption = QLabel()
        self.caption.setWordWrap(True)
        self.caption.setTextFormat(Qt.TextFormat.PlainText)
        self.caption.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.caption.setContentsMargins(6, 4, 6, 4)
        # What an assembly's 3D view could not show, and why.
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status.setStyleSheet(
            "QLabel { background: rgba(194, 81, 0, 0.14); border: 1px solid rgba(194, 81, 0, 0.5);"
            " border-radius: 3px; padding: 4px 6px; margin: 4px 6px 0 6px; }"
        )
        self.status.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(bar)
        layout.addWidget(self.explode_row)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.status)
        layout.addWidget(self.caption)
        self._show_controls()

    # -- the document -------------------------------------------------------------------
    @property
    def document_path(self) -> str | None:
        """The shown document's path (the first part of its :attr:`document_key`), for
        messages that name its format; None when none is shown."""
        key = self.document_key
        return key[0] if isinstance(key, tuple) and key and isinstance(key[0], str) else None

    def reset(self, doc_type: str | None, key: Any = None) -> None:
        """A new document (or none): forget the image, the mesh, the configurations and
        what was hidden or made transparent. ``key`` names the document, ``(path, path
        below the opened folder)``, whose choices of sub-assemblies to explode come back
        while the viewer runs."""
        self.doc_type = doc_type
        self.document_key = key
        self.looks = Looks()
        self.explode_choices = dict(self._choices_by_document.get(key, {})) if key is not None else {}
        self.instance_looks = []
        self.component_files, self.component_names = {}, {}
        self.mesh_state = "idle"
        self.mesh_info = {}
        self.image_caption = ""
        self.configuration = self.requested_configuration = None
        self.config_combo.clear()
        self.instance_ids = []
        self.instance_files = []
        self.instance_documents = {}
        self.instance_missing = {}
        self.files = []
        self._no_boxes()
        self.assembly = None
        self.explode_groups = {}
        self.highlight = None
        if self.pick_note is not None:
            self.pick_note.show_text("")
        self.explode_slider.blockSignals(True)
        self.explode_slider.setValue(0)  # a new document starts collapsed
        self.explode_slider.blockSignals(False)
        self.explode_value = 0
        self._slider_action = None
        self._pending_camera = None
        self._drawn_key = None
        self.level_chosen = False
        self._use_level(self.session_level)
        self._explode_text()
        self.image_once = False
        self.image.clear()
        if self.view is not None:
            self.view.set_mesh(None)  # type: ignore[attr-defined]
        self._set_status("", "")
        self._model_message("")
        self._apply_mode()

    def set_configurations(self, names: list[str], current: str | None) -> None:
        """The assembly's configurations and the one the Components tab shows, which the
        3D view shows too: the view is read again when it shows another one."""
        self.config_combo.blockSignals(True)
        self.config_combo.clear()
        self.config_combo.addItems(names)
        if current:
            self.config_combo.setCurrentText(current)
        self.config_combo.blockSignals(False)
        if current and current != self.configuration:
            self._switch_configuration(current)
        self._show_controls()

    def choose_configuration(self, name: str) -> None:
        """The user chose ``name`` in the bar: draw it, and have the Components tab show it."""
        if name and name != self.configuration:
            self._switch_configuration(name)
            self.configurationChosen.emit(name)

    def _switch_configuration(self, name: str) -> None:
        self.configuration = name
        if self.doc_type != "assembly":
            return
        if self.mesh_state in ("loading", "ready", "no_mesh", "too_large", "error"):
            if self.requested_configuration is None and self.mesh_state == "loading":
                self.requested_configuration = name  # asked for the file's own choice, which this is
                return
            if self.requested_configuration != name:
                self.mesh_state = "idle"
                self._maybe_request()

    def set_doc_type(self, doc_type: str | None) -> None:
        if doc_type != self.doc_type:
            self.doc_type = doc_type
            self.mesh_state = "idle"
        self._apply_mode()

    def set_image(self, pix: QPixmap | None, *, source_width: int | None, caption: str) -> None:
        self.image_caption = caption
        self.image.placeholder = ""
        self.image.set_image(pix, source_width)
        self._update_caption()
        self._maybe_request()

    def set_no_image(self, text: str) -> None:
        self.image_caption = ""
        self.image.clear(text)
        self._update_caption()
        self._maybe_request()

    @property
    def has_3d(self) -> bool:
        """Whether this document can be drawn in 3D here: the setting is on and it is a
        part or an assembly."""
        return self.enabled_3d and self.doc_type in _IN_3D

    @property
    def no_3d(self) -> bool:
        """A document known to have no 3D view: a drawing."""
        return self.doc_type is not None and self.doc_type not in _IN_3D

    # -- settings ------------------------------------------------------------------------
    def set_3d_enabled(self, on: bool) -> None:
        if on == self.enabled_3d:
            return
        self.enabled_3d = on
        self.image_once = False
        if on:
            self.preferred = MODEL  # turning the 3D view on shows it
        else:
            if self.view is not None:  # let OpenGL go
                self.model_stack.removeWidget(self.view)
                self.view.deleteLater()
                self.view = None
                self.legend = self.pick_note = None  # went with the view
            self.mesh_state = "idle"
        self._apply_mode()

    def set_mouse(self, style: str, invert_wheel: bool) -> None:
        self.mouse_style, self.invert_wheel = style, invert_wheel
        self.image.mouse_style, self.image.invert_wheel = style, invert_wheel
        if self.view is not None:
            self.view.mouse_style = style  # type: ignore[attr-defined]
            self.view.invert_wheel = invert_wheel  # type: ignore[attr-defined]
        self._update_caption()

    def set_rotation(self, mode: str) -> None:
        """Turn the 3D view freely or as a turntable (:data:`.viewmath.ROTATION_MODES`)."""
        self.rotation_mode = mode
        if self.view is not None and hasattr(self.view, "set_rotation_mode"):
            self.view.set_rotation_mode(mode)  # type: ignore[attr-defined]
        self._update_caption()

    def set_navigation(self, view_cube: bool, about_pointer: bool = True) -> None:
        """Settings: whether the 3D view shows its view cube, and whether a drag turns the
        model about the point under the pointer."""
        self.show_cube, self.about_pointer = view_cube, about_pointer
        if self.view is not None and hasattr(self.view, "set_cube_shown"):
            self.view.set_cube_shown(view_cube)  # type: ignore[attr-defined]
            self.view.set_about_pointer(about_pointer)  # type: ignore[attr-defined]
        self._update_caption()

    def _same_document(self) -> bool:
        """Whether the scene about to be drawn replaces one of the same document (another
        configuration, Boxes for Missing Meshes turned on or off, a read again under a
        higher triangle limit): the view then keeps its camera."""
        return self._drawn_key is not None and self._drawn_key == self.document_key

    def _use_home(self, view: QWidget) -> None:
        """Before a scene of the document is shown: the view opens it at the document's
        Home, and its Home key goes there."""
        if hasattr(view, "use_home"):
            view.use_home(self._homes_by_document.get(self.document_key))  # type: ignore[attr-defined]

    def _home_changed(self, state: dict[str, Any] | None) -> None:
        """The user set Home in the 3D view, or put it back to the isometric: kept for this
        document while the viewer runs."""
        if self.document_key is None:
            return
        if state:
            self._homes_by_document[self.document_key] = dict(state)
        else:
            self._homes_by_document.pop(self.document_key, None)

    def set_boxes(self, on: bool) -> None:
        """Settings > Boxes for Missing Meshes: the assembly shown is drawn again with or
        without its boxes, from the read it has, keeping its camera, explode and pick."""
        if on == self.draw_boxes:
            return
        self.draw_boxes = on
        if (
            self.assembly is None
            or self.doc_type != "assembly"
            or self.mesh_state not in ("ready", "no_mesh", "too_large")
            or self.view is None
            or getattr(self.view, "error", None)
        ):
            return
        self._show_assembly()  # the same document: its camera stays

    def _no_boxes(self) -> None:
        self.box_from = len(self.instance_ids)
        self.box_keys, self.box_names, self.box_reasons = [], [], []

    def retry_if_too_large(self, cap: int) -> None:
        """A higher triangle cap: read a mesh refused under the old one again, and an
        assembly that the old one cut short."""
        if self.mesh_state == "ready" and self.mesh_info.get("limited"):
            self.mesh_state = "idle"
            self._maybe_request()
            return
        if self.mesh_state != "too_large":
            return
        info = self.mesh_info
        if "triangles" in info:
            fits = info["triangles"] <= cap
        elif "bytes" in info:
            fits = info["bytes"] <= byte_budget(cap)
        else:  # it ran out of memory: a higher cap allows more
            fits = True
        if fits:
            self.mesh_state = "idle"
            self._maybe_request()

    # -- the exploded view ----------------------------------------------------------------
    @property
    def can_explode(self) -> bool:
        """Whether an assembly is drawn in 3D now, which the Explode bar moves apart."""
        return self.mode == MODEL and self.doc_type == "assembly" and self.mesh_state == "ready"

    def set_explode(self, percent: int, level: str | None = None, *, session: bool = True) -> None:
        """Explode the assembly to ``percent``, at ``level`` when given, as the Explode bar
        does; with ``session`` off the level is this document's only (Back puts back the
        level the document had, not the user's choice for the next one)."""
        if level is not None:
            self.set_explode_level(level, session=session)
        self.explode_slider.setValue(int(percent))

    def collapse(self) -> None:
        """Put every component back, easing there."""
        self.explode_slider.setValue(0)

    PLAY_HOLD_S = 0.8  # how long Play keeps the assembly exploded before it collapses it

    def toggle_play(self) -> None:
        """Play the explode and then the collapse (the bar's Play), or stop playing."""
        if self._play_step:
            self.stop_play()
            return
        self._play_step = 1
        self.play_button.setText("Stop")
        self.explode_slider.setValue(100)
        self._play_timer.start(int((EXPLODE_SECONDS + self.PLAY_HOLD_S) * 1000))

    def _play_next(self) -> None:
        if self._play_step == 1:
            self._play_step = 2
            self.explode_slider.setValue(0)
            self._play_timer.start(int(EXPLODE_SECONDS * 1000) + 50)
        else:
            self.stop_play()

    def stop_play(self) -> None:
        """Stop playing, leaving the assembly where the animation is heading."""
        self._play_timer.stop()
        self._play_step = 0
        self.play_button.setText("Play")

    def set_explode_level(self, level: str, *, session: bool = True) -> None:
        """The level chosen for this document and, with ``session``, the next ones."""
        if level not in LEVELS:
            return
        if session:
            self.session_level = level
        self.level_chosen = True
        self._use_level(level)
        self._explode_text()

    def _use_level(self, level: str) -> None:
        self.explode_level = level
        index = self.explode_combo.findData(level)
        if index != self.explode_combo.currentIndex():
            self.explode_combo.setCurrentIndex(index)
        if self.view is not None and self.can_explode:
            self.view.set_explode_level(level)  # type: ignore[attr-defined]

    def _slider_acted(self, action: int) -> None:
        # Emitted before the value follows the action, with the position it goes to.
        self._slider_action = (int(action), self.explode_slider.sliderPosition())

    def _explode_changed(self, value: int) -> None:
        """The slider moved: dragged, or stepped by a key or the wheel, the view follows it
        closely; a page step, Home or End, Collapse and Back ease there."""
        self.explode_value = value
        acted, self._slider_action = self._slider_action, None
        action = acted[0] if acted is not None and acted[1] == value else None
        follow = self.explode_slider.isSliderDown() or action in _FOLLOWED
        if self.view is not None and self.can_explode:
            self.view.explode_to(value / 100, animate=True, follow=follow)  # type: ignore[attr-defined]
        self._explode_text()

    def _explode_text(self) -> None:
        value = self.explode_value
        groups = self.explode_groups.get(self.explode_level)
        parts = self.explode_groups.get(PARTS)
        self.explode_percent.setText(f"{value}%")
        one_part = parts is not None and parts < 2
        self.explode_slider.setEnabled(not one_part)
        self.explode_combo.setEnabled(not one_part)
        self.collapse_button.setEnabled(value > 0 and not one_part)
        self.play_button.setEnabled(not one_part)
        note = ""
        chosen = choices_text(self.active_choices()) if groups is not None else ""
        hidden = groups is not None and self._any_hidden()
        if one_part:
            hint = note = "There is only one part, so nothing moves."
        elif groups is not None and (chosen or hidden):
            # The groups as they are made now: with the choices for sub-assemblies, of what
            # is shown.
            pieces = self.explode_pieces() or 0
            if not pieces:
                hint = note = "Nothing moves: every component is hidden."
            elif pieces < 2:
                hint = note = "Nothing moves: what is shown moves as one piece" + (
                    f" ({chosen})." if chosen else "."
                )
            else:
                hint = f"{plural(pieces, 'group')} move apart" + (f"; {chosen}." if chosen else ".")
                if chosen:
                    note = chosen[0].upper() + chosen[1:] + "."
            if hidden and pieces:
                hint += " What is hidden is left out: it stays where it is and is not counted."
        elif groups is not None and groups < 2:
            hint = note = "There is only one top-level component, so nothing moves: choose Every part."
        elif groups is not None:
            what = "top-level component" if self.explode_level == TOP else "part"
            hint = f"{plural(groups, what)} move apart."
            if self.explode_level == PARTS and not self.level_chosen and self.explode_groups.get(TOP, 2) < 2:
                note = "One top-level component, so every part moves on its own."
        else:
            hint = ""
        self.explode_percent.setToolTip(tip(hint) if hint else "")
        self.explode_hint.setText(note)
        self.explode_hint.setToolTip(tip(note) if note else "")
        self.explode_hint.setVisible(bool(note))

    def _new_scene(self, data, *, boxes: bool = False) -> None:
        """A new scene of the assembly, with its boxes after its meshes' instances when
        ``boxes``: group it at the level chosen, explode it as far as the bar says, at
        once, put back the camera Back remembered, and pick again what was picked. An
        assembly with one top-level component and several parts uses Every part, unless
        a level was chosen for it: grouped by top-level component nothing would move."""
        self.instance_ids = [i for ids in data.instance_ids for i in ids]
        self.instance_files = []
        self.instance_documents = dict(data.documents)
        self.instance_missing = dict(data.missing)
        for raw in data.files_of:
            index = array("I")
            index.frombytes(raw)
            self.instance_files.extend(index)
        self.files = list(data.files)
        self._no_boxes()
        b = data.boxes if boxes else None
        if b is not None:
            self.box_keys, self.box_names, self.box_reasons = list(b.files), list(b.names), list(b.reasons)
            self.instance_ids += b.ids
        self.explode_groups = {
            level: len({group_of(i, level) for i in self.instance_ids}) for level in LEVELS
        }
        if not self.level_chosen:
            single = self.explode_groups[TOP] < 2 and self.explode_groups[PARTS] >= 2
            self._use_level(PARTS if single else self.session_level)
        view = self.view
        self._apply_looks(highlight=False)  # what is hidden, before the explode spreads the rest
        if view is not None and hasattr(view, "set_explode_choices"):
            view.set_explode_choices(self.explode_choices)
        if view is not None:
            view.set_explode_level(self.explode_level)  # type: ignore[attr-defined]
            if self.explode_value:
                view.explode_to(self.explode_value / 100, animate=False)  # type: ignore[attr-defined]
        self._apply_camera((data.info or {}).get("configuration"))
        self._explode_text()
        self._apply_highlight()

    # -- the camera, for Back -------------------------------------------------------------
    def camera_state(self) -> dict[str, Any] | None:
        """How the 3D view is turned and zoomed now, for Back; None when it shows nothing."""
        view = self.view
        if view is None or self.mesh_state != "ready" or not hasattr(view, "camera_state"):
            return None
        return view.camera_state()

    def restore_camera(self, state: dict[str, Any] | None, configuration: str | None = None) -> None:
        """Turn and zoom the 3D view as ``state`` says once the document's scene arrives (an
        assembly's in ``configuration``), after its explode: what Back does."""
        self._pending_camera = (state, configuration) if state else None

    def _apply_camera(self, configuration: str | None) -> None:
        pending = self._pending_camera
        if pending is None or self.view is None or not hasattr(self.view, "set_camera_state"):
            return
        state, wanted = pending
        if wanted is not None and configuration is not None and wanted != configuration:
            return  # a scene of another configuration: the one Back asked for follows
        self._pending_camera = None
        self.view.set_camera_state(state)

    # -- picking -------------------------------------------------------------------------
    def highlight_instance(self, ident: str | None) -> None:
        """Pick the instance ``ident`` in the 3D view, or with a sub-assembly's id every
        part under it; None picks nothing."""
        self.highlight = ("instance", ident) if ident else None
        self._apply_highlight()

    def highlight_file(self, key: str | None) -> None:
        """Pick every instance of the component file ``key``; None picks nothing."""
        self.highlight = ("file", key) if key else None
        self._apply_highlight()

    def picked_indices(self) -> list[int]:
        """The view's instances that :attr:`highlight` names."""
        return self.indices_of(self.highlight) if self.highlight is not None else []

    def indices_of(self, what: tuple[str, str]) -> list[int]:
        """The view's instances that ``what`` names, as :attr:`highlight` does: ``("instance",
        id)`` every instance under that id, ``("file", key)`` every instance of that file,
        ``("boxes", "")`` every instance drawn as a box. A sub-assembly's file names every
        part drawn under each instance of that sub-assembly (:attr:`component_files`)."""
        kind, value = what
        if kind == "file":
            # A file read from a sub-assembly's own file may be drawn as one the assembly names.
            value = next((f["key"] for f in self.files if value in f.get("keys", ())), value)
            files = {i for i, f in enumerate(self.files) if f.get("key") == value}
            drawn = [g for g, fi in enumerate(self.instance_files) if fi in files]
            drawn += [self.box_from + k for k, key in enumerate(self.box_keys) if key == value]
            subs = {i for i, key in self.component_files.items() if key == value}
            if subs:
                ids = self.instance_ids
                under = (g for g, iid in enumerate(ids) if any(s in subs for s in subassemblies(iid)))
                drawn = sorted({*drawn, *under})
            return drawn
        if kind == "boxes":
            return list(range(self.box_from, len(self.instance_ids)))
        inside = value + "/"
        return [g for g, iid in enumerate(self.instance_ids) if iid == value or iid.startswith(inside)]

    def _apply_highlight(self) -> None:
        indices = self.picked_indices() if self.instance_ids else []
        view = self.view
        if view is not None and hasattr(view, "set_highlight") and self.instance_ids:
            # A hidden instance is drawn nowhere, picked or not: with every one picked hidden,
            # nothing is drawn picked and nothing faded for it.
            view.set_highlight([g for g in indices if not self._hidden(g)])
        if view is not None:
            self._ensure_pick_note(view).show_text(self._pick_text(indices))

    def drop_pick(self) -> None:
        """Pick nothing, here and on the Components tab (``pickDropped``)."""
        if self.highlight is None:
            return
        self.highlight = None
        self._apply_highlight()
        self.pickDropped.emit()

    def is_box(self, index: int) -> bool:
        """Whether the view's instance ``index`` is drawn as a box, for want of a mesh."""
        return self.box_from <= index < len(self.instance_ids)

    def _file_key(self, index: int) -> str | None:
        """The key of the file the instance at ``index`` is of (an object of the file shown
        for a model file's own objects, :func:`.modelview.is_internal`); None for a box."""
        if self.is_box(index):
            return None
        fi = self.instance_files[index] if index < len(self.instance_files) else None
        f = self.files[fi] if fi is not None and fi < len(self.files) else {}
        return f.get("key")

    def _file_name(self, index: int) -> str:
        if self.is_box(index):
            return self.box_names[index - self.box_from] or ""
        fi = self.instance_files[index] if index < len(self.instance_files) else None
        f = self.files[fi] if fi is not None and fi < len(self.files) else {}
        return f.get("name") or ""

    def describe_instance(self, index: int) -> str:
        """An instance's id and its file, for the hover text; a box says it has no mesh."""
        if not 0 <= index < len(self.instance_ids):
            return ""
        name = self._file_name(index)
        if self.is_box(index):
            return box_text(self.instance_ids[index], name, self.box_reasons[index - self.box_from])
        return f"{self.instance_ids[index]} ({name})" if name else self.instance_ids[index]

    def _pick_text(self, indices: list[int]) -> str:
        if not self.instance_ids or self.mode != MODEL:
            return ""
        if self.instance_looks and all(look.hidden for look in self.instance_looks):
            return "Every component is hidden. Right-click the view for Show all."
        text = self._picked_text(indices)
        if text and indices and all(self._hidden(g) for g in indices):
            text += " It is hidden: Show all brings it back."
        return text

    def _picked_text(self, indices: list[int]) -> str:
        if self.highlight is None:
            return ""
        kind, value = self.highlight
        if kind == "file":
            name = next((f.get("name") for f in self.files if f.get("key") == value), None)
            if name is None and value in self.component_files.values():  # a sub-assembly's file
                name = self.component_names.get(value) or value
                return f"Picked: every instance of {name} ({plural(len(indices), 'part')} shown)."
            if name is None:
                pairs = zip(self.box_keys, self.box_names, strict=True)
                name = next((n for k, n in pairs if k == value and n), value)
            return f"Picked: every instance of {name} ({plural(len(indices), 'instance')} shown)."
        if kind == "boxes" and not indices:
            return f"Picked: the boxes, which are not drawn now ({BOXES_SETTING} is off, or there are none)."
        if kind == "boxes":
            return f"Picked: every instance drawn as a box, for want of a mesh ({len(indices):,})."
        if not indices and not self.draw_boxes and self._boxed(value):
            return (
                f"Picked: {value}, which has no mesh drawn; it is drawn as a box while {BOXES_SETTING} "
                "is on, and that is off."
            )
        if not indices:
            return f"Picked: {value}, which is not drawn here (suppressed, hidden or not read)."
        if len(indices) == 1 and self.instance_ids[indices[0]] == value:
            text = f"Picked: {self.describe_instance(indices[0])}."
            if is_internal(self._file_key(indices[0])):  # an object inside the file shown
                return text
            row = self.row_of(value) if self.row_of is not None else None
            if row is not None and row != value:
                return (
                    f"{text} It was read from the sub-assembly's own file, so the Components tab has no "
                    f"row for it; {row} stands for it there, and a double-click opens that file."
                )
            return f"{text} Double-click it to open its file."
        return f"Picked: {value}, {plural(len(indices), 'part')} shown."

    def _boxed(self, ident: str) -> bool:
        """Whether the read gives a box for the instance ``ident``, or for one under it."""
        b = self.assembly[0].boxes if self.assembly is not None else None
        inside = ident + "/"
        return b is not None and any(i == ident or i.startswith(inside) for i in b.ids)

    def _picked(self, index: int) -> None:
        """A click in the 3D view: pick that instance (none for -1) here and on the
        Components tab."""
        ident = self.instance_ids[index] if 0 <= index < len(self.instance_ids) else ""
        self.highlight_instance(ident or None)
        self.instancePicked.emit(ident)

    def _activated(self, index: int) -> None:
        if 0 <= index < len(self.instance_ids):
            self._picked(index)
            self.instanceActivated.emit(self.instance_ids[index])

    def _hide_key(self, index: int) -> None:
        """Tab in the 3D view: hide the instance under the pointer, as its menu's Hide does."""
        if 0 <= index < len(self.instance_ids):
            self._from_menu(lambda: self.set_hidden(("instance", self.instance_ids[index])))

    def _menu(self, index: int, where: QPoint) -> None:
        if 0 <= index < len(self.instance_ids):
            self._picked(index)
            self.instanceMenu.emit(self.instance_ids[index], where)
            return
        menu = self.space_menu()
        if menu is not None:
            menu.exec(where)
            menu.deleteLater()

    def space_menu(self) -> QMenu | None:
        """The menu of the 3D view's empty space (or of anywhere on a part): 3D Print This
        Assembly (or This Part), in the configuration shown (:attr:`print_shown`), then,
        once something is hidden or changed, what puts the view back, then how the camera
        looks (:meth:`add_camera_actions`). None when it would be empty."""
        menu = relay_status_tips(QMenu(self))
        menu.setToolTipsVisible(True)
        printed = self.print_shown is not None and self.print_shown(menu)
        if self.doc_type == "assembly" and (self.looks.changed or self.explode_choices):
            if printed:
                menu.addSeparator()
            self.add_view_actions(menu)
        self.add_camera_actions(menu)
        if menu.isEmpty():
            menu.deleteLater()
            return None
        return menu

    def _ensure_pick_note(self, view: QWidget) -> PickNote:
        if self.pick_note is None or self.pick_note.parentWidget() is not view:
            self.pick_note = PickNote(view)
        return self.pick_note

    # -- image or 3D ---------------------------------------------------------------------
    def set_mode(self, mode: str) -> None:
        """The user's choice of Image or 3D. It holds for the next document: a
        drawing shows its image, and the next part or assembly is in 3D again."""
        self.preferred = mode
        self.image_once = False
        self._apply_mode()

    def show_image_once(self) -> None:
        """Show the image for this document, as the Overview's image asks, leaving the
        user's choice of the buttons for the next document."""
        self.image_once = True
        self._apply_mode()

    def _apply_mode(self) -> None:
        """Show what the user chose where it can be shown."""
        no_3d = self.no_3d
        mode = (
            MODEL
            if self.enabled_3d and self.preferred == MODEL and not no_3d and not self.image_once
            else IMAGE
        )
        self.mode = mode
        if no_3d and self.mesh_state == "idle":
            self.mesh_state = "no_3d"
        self.image_button.setChecked(mode == IMAGE)
        self.model_button.setChecked(mode == MODEL)
        self.model_button.setEnabled(not no_3d)
        self.model_button.setToolTip(tip(no_3d_text(self.doc_type) if no_3d else _MODEL_TIP))
        self.stack.setCurrentIndex(1 if mode == MODEL else 0)
        self._show_controls()
        self._update_caption()
        self._maybe_request()

    def fit(self) -> None:
        if self.mode == MODEL:
            if self.view is not None and self.mesh_state == "ready":
                self.view.fit()  # type: ignore[attr-defined]
        else:
            self.image.fit()

    def _isometric(self) -> None:
        if self.view is not None and self.mesh_state == "ready":
            if hasattr(self.view, "moving"):  # the real view eases there, as R does
                self.view.reset_view(animate=True)  # type: ignore[attr-defined]
            else:
                self.view.reset_view()  # type: ignore[attr-defined]

    def _show_controls(self) -> None:
        model = self.mode == MODEL
        assembly = model and self.doc_type == "assembly"
        self.image_button.setVisible(self.enabled_3d)
        self.model_button.setVisible(self.enabled_3d)
        for w in (self.zoom_out, self.zoom_label, self.zoom_in, self.actual_button):
            w.setVisible(not model)
        self.iso_button.setVisible(model)
        self.config_label.setVisible(assembly and self.config_combo.count() > 0)
        self.config_combo.setVisible(assembly and self.config_combo.count() > 0)
        self.legend_button.setVisible(assembly)
        self.explode_row.setVisible(assembly)
        if self.pick_note is not None:
            self.pick_note.show_text(self._pick_text(self.picked_indices()) if assembly else "")
        self.status.setVisible(model and bool(self.status.text()))
        self._show_legend()
        self._zoom_changed()

    def _show_legend(self) -> None:
        if self.legend is not None:
            on = (
                self.mode == MODEL
                and self.doc_type == "assembly"
                and self.mesh_state == "ready"
                and self.legend_button.isChecked()
            )
            self.legend.setVisible(on)
            if on:
                self.legend.raise_()
            self.legend._reserve()  # shown or hidden while the view itself is hidden, too

    def _set_status(self, text: str, full: str) -> None:
        self.status.setText(text)
        self.status.setToolTip(tip(full))
        self.status.setVisible(self.mode == MODEL and bool(text))

    def _zoom_changed(self) -> None:
        pct = self.image.percent
        self.zoom_label.setText("" if pct is None else f"{pct:.0f}%" if pct >= 10 else f"{pct:.1f}%")
        has = self.image.pixmap is not None
        for w in (self.zoom_out, self.zoom_in, self.actual_button):
            w.setEnabled(has)
        if self.mode == IMAGE:
            self.fit_button.setEnabled(has)
        else:
            ready = self.mesh_state == "ready"
            self.fit_button.setEnabled(ready)
            self.iso_button.setEnabled(ready)
            self.explode_row.setEnabled(ready and self.doc_type == "assembly")

    def _update_caption(self) -> None:
        if self.mode == IMAGE:
            lines = [self.image_caption]
            if self.enabled_3d and self.preferred == MODEL and self.no_3d:
                lines.append(no_3d_text(self.doc_type) + " This is the preview SOLIDWORKS stored.")
            text = "\n".join(line for line in lines if line)
        else:
            text = ""
            i = self.mesh_info
            if self.mesh_state == "ready" and "instances" in i:
                boxes = i.get("boxes") or 0
                of = files_text(i["files"], i.get("internal") or 0)
                drawn = (
                    f"{plural(i['instances'], 'instance')} of {of}, "
                    f"{plural(i['triangles'], 'triangle')} drawn from {i['read_triangles']:,} read, "
                    f"from {sources_text(i['sources'])}"
                )
                if boxes and not i["instances"]:
                    drawn = f"No mesh to draw: {plural(boxes, 'box', 'boxes')} stand in for the instances"
                elif boxes:
                    drawn += f", and {plural(boxes, 'box', 'boxes')} for instances with no mesh"
                text = f"{drawn}, read in {seconds_text(i['seconds'])}. " + controls_text(
                    self.mouse_style,
                    self.invert_wheel,
                    assembly=True,
                    rotation=self.rotation_mode,
                    cube=self.show_cube,
                    opens_files=(i.get("internal") or 0) < i["files"],
                )
            elif self.mesh_state == "ready":
                where = {
                    "assembly": (
                        "from the display mesh SOLIDWORKS keeps for this virtual part in its assembly"
                    ),
                    "bodies": "made from the part's own bodies, as it saved no display mesh",
                }.get(i.get("stored_in"), "from the display mesh SOLIDWORKS saved with the part")
                if self.model_file:
                    where = MODEL_SOURCES.get(i.get("stored_in") or "", "from the file")
                text = (
                    f"{plural(i['triangles'], 'triangle')} and {plural(i['vertices'], 'vertex', 'vertices')} "
                    f"{where}, read in "
                    f"{seconds_text(i['seconds'])}. "
                    + controls_text(
                        self.mouse_style, self.invert_wheel, rotation=self.rotation_mode, cube=self.show_cube
                    )
                )
        self.caption.setText(text)
        self.caption.setVisible(bool(text))
        self._zoom_changed()

    # -- the 3D view ---------------------------------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._maybe_request()

    def _model_message(self, text: str, *, error: bool = False) -> None:
        self.model_message.setText(text)
        self.model_message.setStyleSheet("color: #c62828;" if error else "")
        self.model_stack.setCurrentWidget(self.model_message)

    def prepare_view(self) -> None:
        """Make the 3D view now, hidden, when OpenGL can draw here. A window turns to
        OpenGL drawing when its first OpenGL widget is added; on Windows the window is
        made again for that, which looks like the viewer closing and opening. Made
        before the window is first shown (or when 3D is turned on), the view is there
        from the start, and the first part shown in 3D only shows it. The mesh process
        starts meanwhile (``warmUp``), as it does when the view is made at the first part."""
        if self.view is not None:
            return
        if self.gl_result is None:
            self.gl_result = self._gl()
        if self.gl_result[0]:
            self._ensure_view()
            self.warmUp.emit()

    def _gl(self) -> tuple[bool, str]:
        if self.gl_check is not None:
            return self.gl_check()
        from .view3d import gl_status

        return gl_status()

    def _maybe_request(self) -> None:
        """Ask for the mesh when the 3D view is on screen and has nothing yet."""
        if not (self.enabled_3d and self.mode == MODEL and self.isVisible()):
            return
        if self.mesh_state != "idle":
            return
        if self.doc_type is None:
            self._model_message("Select a part or an assembly to see it in 3D.")
            return
        if self.view is not None and getattr(self.view, "error", None):
            self._gl_failed(self.view.error)  # type: ignore[attr-defined]
            return
        if self.view is None:
            if self.gl_result is not None and not self.gl_result[0]:
                self._no_gl(self.gl_result[1])
            else:
                self._start_gl()
            return
        self.mesh_state = "loading"
        self.requested_configuration = self.configuration
        self._set_status("", "")
        self._model_message(
            "Reading the model..."
            if self.model_file
            else "Reading the assembly's display meshes..."
            if self.doc_type == "assembly"
            else "Reading the saved display mesh..."
        )
        self._update_caption()
        self.meshRequested.emit()

    def _start_gl(self) -> None:
        """The first 3D view: say so, let that reach the screen, then check OpenGL and
        make the view, which hold the window for a moment."""
        self.mesh_state = "starting"
        self._model_message("Starting OpenGL for the 3D view...")
        self._update_caption()
        self.warmUp.emit()
        self.model_message.repaint()
        QTimer.singleShot(_PAINT_FIRST_MS, self._finish_gl_start)

    def _finish_gl_start(self) -> None:
        if self.mesh_state != "starting":
            return  # the document or the setting changed meanwhile, and asks again itself
        if not (self.enabled_3d and self.mode == MODEL and self.isVisible()):
            self.mesh_state = "idle"  # asked again when the 3D view is next on screen
            return
        if self.gl_result is None:
            self.gl_result = self._gl()
        if not self.gl_result[0]:
            self._no_gl(self.gl_result[1])
            return
        self._ensure_view()
        self.mesh_state = "idle"
        self._maybe_request()

    def _no_gl(self, why: str) -> None:
        self.mesh_state = "no_gl"
        self._model_message(
            f"The 3D view needs OpenGL, which is not available here: {why}. The preview image still works "
            "under Image."
        )
        self._update_caption()

    def set_mesh_result(self, result: dict[str, Any]) -> None:
        """The window's answer to ``meshRequested`` (:meth:`.meshproc.MeshReader.read`)."""
        if self.mesh_state != "loading":
            return  # the document, the setting or the view changed since it was asked for
        state = result.get("state")
        seconds = result.get("wall")
        if seconds is None:
            seconds = sum((result.get("seconds") or {}).values())
        if state == "cancelled":
            self.mesh_state = "idle"
            return
        geometry = result.get("geometry")
        self.assembly = None
        if geometry is not None:
            if self.configuration is None:
                self.configuration = geometry.get("configuration")
            self.requested_configuration = geometry.get("configuration")
            text, full = not_shown_text(geometry, result.get("cap"), boxes=self.draw_boxes)
            self._set_status(text, full)
        if state in ("ok", "partial"):  # partial: drawn, with faces left out (a model file)
            view = self.view
            if view is None or getattr(view, "error", None):
                self.mesh_state = "idle"
                self._maybe_request()
                return
            data = result["data"]
            if geometry is not None:  # an assembly
                self.assembly = (data, geometry, result.get("cap"), seconds)
                self._show_assembly()
                return
            self.mesh_info = {
                "triangles": data.n_triangles,
                "vertices": data.n_vertices,
                "seconds": seconds,
                "stored_in": result.get("stored_in"),
            }
            self.mesh_state = "ready"
            self._use_home(view)
            view.set_mesh(data, keep_camera=self._same_document())  # type: ignore[attr-defined]
            self._drawn_key = self.document_key
            self._apply_camera(None)
            self.model_stack.setCurrentWidget(view)
            self._set_status(*faces_left_out_text(result.get("faces_left_out")))
            self._show_controls()
        elif state == "no_mesh" and geometry is not None:
            self.mesh_state = "no_mesh"
            self._model_message(_nothing_text(geometry))
        elif state == "no_mesh" and result.get("nested"):
            self.mesh_state = "no_mesh"
            self._model_message(
                "No saved display mesh here: SOLIDWORKS keeps a virtual part's display mesh in the "
                "assembly that stores it rather than in the part, and that assembly holds none for this "
                "part in its active configuration. The assembly's 3D view shows every instance it has a "
                "mesh for; Back returns there."
            )
        elif state == "no_mesh" and result.get("model"):
            self.mesh_state = "no_mesh"
            self._model_message(
                "Nothing to draw: the file holds no triangles, and no body that could be tessellated. "
                "The Overview's warnings say what was left out."
            )
        elif state == "no_mesh":
            self.mesh_state = "no_mesh"
            self._model_message(
                "No saved display mesh: this part stores no triangles to draw, because it has no "
                "bodies or because SOLIDWORKS saved it without its display data. The preview image "
                "is under Image."
            )
        elif state == "too_large":
            self.mesh_state = "too_large"
            self._model_message(_too_large_text(result))
            self.mesh_info = {k: result[k] for k in ("triangles", "bytes") if k in result}
        elif state in ("not_part", "not_assembly"):
            self.mesh_state = "idle"
            self.set_doc_type(result.get("doc_type"))
            return
        else:
            self.mesh_state = "error"
            what = "The model" if result.get("model") else "The saved display mesh"
            why = error_message(result.get("error"), path=self.document_path)
            self._model_message(f"{what} could not be read.\n\n{why}", error=True)
        self._update_caption()
        self._show_controls()

    def _show_assembly(self) -> None:
        """Draw the assembly read last (:attr:`assembly`), with a box for each instance
        without a mesh when :attr:`draw_boxes` says so; with nothing to draw, say why."""
        assert self.assembly is not None
        data, geometry, cap, seconds = self.assembly
        view = self.view
        if view is None or getattr(view, "error", None):
            self.mesh_state = "idle"
            self._maybe_request()
            return
        boxes = len(data.boxes) if self.draw_boxes and data.boxes is not None else 0
        text, full = not_shown_text(geometry, cap, boxes=self.draw_boxes)
        self._set_status(text, full)
        if not data.meshes and not boxes:  # nothing but boxes, and they are off
            self.instance_ids, self.instance_files, self.files = [], [], []
            self.instance_documents = {}
            self.instance_missing = {}
            self.instance_looks = []
            self._no_boxes()
            view.set_mesh(None)  # type: ignore[attr-defined]
            self._drawn_key = None
            too_large = bool(geometry.get("too_large"))
            self.mesh_state = "too_large" if too_large else "no_mesh"
            self.mesh_info = {}
            self._model_message(
                _too_large_text({"geometry": geometry, "cap": cap}) if too_large else _nothing_text(geometry)
            )
            self._update_caption()
            self._show_controls()
            return
        counts = geometry["counts"]
        self.mesh_info = {
            "instances": data.n_instances,
            "boxes": boxes,
            "files": len(data.files),
            "internal": sum(1 for f in data.files if is_internal(f.get("key"))),
            "meshes": len(data.meshes),
            "triangles": data.n_triangles,
            "read_triangles": counts["triangles_read"],
            "vertices": sum(m.n_vertices for m in data.meshes),
            "skipped": geometry["skipped_count"],
            "configuration": geometry["configuration"],
            "sources": geometry["sources"],
            "limited": bool(set(geometry["truncated"]) & set(LIMITS)),
            "seconds": seconds,
        }
        self.mesh_state = "ready"
        self._use_home(view)
        keep = self._same_document()
        view.set_assembly(data, boxes=bool(boxes), keep_camera=keep)  # type: ignore[attr-defined]
        self._drawn_key = self.document_key
        self._ensure_legend(view).set_files(data.files, boxes=boxes)
        if not self.legend_chosen:  # a long legend would hide the model's corner
            self.legend_button.setChecked(len(data.files) <= LEGEND_SHOWN_UP_TO)
        self._new_scene(data, boxes=bool(boxes))
        self.model_stack.setCurrentWidget(view)
        self._update_caption()
        self._show_controls()

    def _ensure_legend(self, view: QWidget) -> Legend:
        if self.legend is None or self.legend.parentWidget() is not view:
            self.legend = Legend(view)
            self.legend.filePicked.connect(self._legend_file)
            self.legend.boxesPicked.connect(self._legend_boxes)
            self.legend.fileMenu.connect(self._legend_file_menu)
            self.legend.boxesMenu.connect(self._legend_boxes_menu)
        return self.legend

    def _legend_button_clicked(self) -> None:
        self.legend_chosen = True

    def _legend_file(self, key: str) -> None:
        """A file clicked in the legend: pick every instance of it, here and on the Files table."""
        self.highlight_file(key)
        self.filePicked.emit(key)

    def highlight_boxes(self) -> None:
        """Pick every instance drawn as a box."""
        self.set_pick(("boxes", ""))

    def set_pick(self, pick: tuple[str, str] | None) -> None:
        """Pick what :attr:`highlight` held, as Back puts it back."""
        self.highlight = pick
        self._apply_highlight()

    def _legend_boxes(self) -> None:
        """The boxes' row clicked in the legend: pick them all; the Components tab has no row
        that stands for them, so none of its rows stays current."""
        self.highlight_boxes()
        self.boxesPicked.emit()

    def _legend_file_menu(self, key: str, where: QPoint) -> None:
        """A file right-clicked in the legend: pick every instance of it, as a click does,
        and show its menu: the details panel's for its file (:attr:`file_menu`), then how
        its instances look."""
        self._legend_file(key)
        menu = self.file_menu(key) if self.file_menu is not None else None
        menu = menu or relay_status_tips(QMenu(self))
        self.add_file_actions(menu, key)
        menu.exec(where)
        menu.deleteLater()

    def _legend_boxes_menu(self, where: QPoint) -> None:
        self._legend_boxes()
        menu = relay_status_tips(QMenu(self))
        menu.setToolTipsVisible(True)
        self.add_look_actions(menu, ("boxes", ""))
        menu.addSeparator()
        self.add_view_actions(menu)
        menu.exec(where)
        menu.deleteLater()

    # -- what each component looks like ----------------------------------------------------
    @property
    def styles_3d(self) -> bool:
        """Whether components can be hidden, made transparent or kept from exploding here:
        the 3D view is on and the document is an assembly."""
        return self.enabled_3d and self.doc_type == "assembly"

    def _canonical_file(self, key: str) -> str:
        """The key the legend draws the file ``key`` as (:func:`.mesh3d.file_groups`)."""
        return next((f["key"] for f in self.files if key in f.get("keys", ())), key)

    def _file_keys(self, index: int) -> list[str]:
        """Every key the file of the view's instance ``index`` goes by, then the files of the
        sub-assemblies it is in (:attr:`component_files`): a choice made for a file covers
        every instance of it, and for a sub-assembly's file every part in each instance of
        that sub-assembly."""
        if self.is_box(index):
            key = self.box_keys[index - self.box_from]
            keys = [key, self._canonical_file(key)] if key else []
        else:
            fi = self.instance_files[index] if index < len(self.instance_files) else None
            f = self.files[fi] if fi is not None and fi < len(self.files) else None
            keys = [f["key"], *f.get("keys", ())] if f is not None and f.get("key") else []
        if self.component_files and index < len(self.instance_ids):
            subs = subassemblies(self.instance_ids[index])
            keys += [self.component_files[s] for s in subs if s in self.component_files]
        return keys

    def set_components(self, files: dict[str, str], names: dict[str, str]) -> None:
        """The sub-assemblies as the Components tab read them: each one's file key by its
        component tree id (``files``), and each file's name by its key (``names``), so a
        sub-assembly's file in the Files table covers the parts of every instance of it
        (:func:`.details.component_files`)."""
        if (files, names) == (self.component_files, self.component_names):
            return
        self.component_files, self.component_names = dict(files), dict(names)
        if self.instance_ids:
            self._apply_looks()

    def _hidden(self, index: int) -> bool:
        return index < len(self.instance_looks) and self.instance_looks[index].hidden

    def _any_hidden(self) -> bool:
        return any(look.hidden for look in self.instance_looks)

    def _scope(self, what: tuple[str, str]) -> tuple[str, str]:
        kind, value = what
        if kind == "file":
            return (FILE, self._canonical_file(value))
        if kind == "boxes":
            return (BOXES, "")
        return (ID, value)

    def _apply_looks(self, *, highlight: bool = True) -> None:
        """Work out each instance's look from :attr:`looks` and have the view draw it, the
        legend grey the files all hidden, the pick note and the Explode bar say what
        follows, and the Components tab show it (``looksChanged``)."""
        ids = self.instance_ids
        looks = [self.looks.look(iid, self._file_keys(g), box=self.is_box(g)) for g, iid in enumerate(ids)]
        self.instance_looks = looks
        view = self.view
        if view is not None and hasattr(view, "set_looks") and ids:
            view.set_looks([look.opacity for look in looks], [look.hidden for look in looks])
        if self.legend is not None:
            shown: set[int] = set()
            for g, fi in enumerate(self.instance_files):
                if not self._hidden(g):
                    shown.add(fi)
            drawn = set(self.instance_files)
            hidden = {self.files[fi].get("key") for fi in drawn - shown if fi < len(self.files)}
            boxes = range(self.box_from, len(ids))
            self.legend.show_hidden(hidden, bool(boxes) and all(self._hidden(g) for g in boxes))
        if highlight:
            self._apply_highlight()
        self._explode_text()
        self.looksChanged.emit()

    def target_look(self, what: tuple[str, str]) -> tuple[bool, int | None]:
        """Whether every instance ``what`` names (:meth:`indices_of`) is hidden, and the
        transparency they share (None when they differ); with none drawn, the look the
        choices give ``what`` itself."""
        looks = [self.instance_looks[g] for g in self.indices_of(what) if g < len(self.instance_looks)]
        if not looks:
            kind, value = what
            if kind == "file":
                looks = [self.looks.look("", [value, self._canonical_file(value)])]
            else:
                looks = [self.looks.look(value if kind == "instance" else "", box=kind == "boxes")]
        shared = {look.transparency for look in looks}
        return all(look.hidden for look in looks), (shared.pop() if len(shared) == 1 else None)

    def look_summary(self) -> tuple[dict[str, tuple[bool, int]], dict[str, tuple[bool, int]]]:
        """For the Components tab, by instance or sub-assembly id and by file key: whether
        every instance drawn under it is hidden, and the transparency every one of them
        shown has (0 when they differ or are opaque); only what has an instance drawn,
        and only what is not as the file draws it."""
        by_id: dict[str, list[Look]] = {}
        by_file: dict[str, list[Look]] = {}
        for g, look in enumerate(self.instance_looks):
            names = self.instance_ids[g].split("/")
            for k in range(len(names)):
                by_id.setdefault("/".join(names[: k + 1]), []).append(look)
            for key in dict.fromkeys(self._file_keys(g)):
                by_file.setdefault(key, []).append(look)

        def summary(groups: dict[str, list[Look]]) -> dict[str, tuple[bool, int]]:
            out = {}
            for name, looks in groups.items():
                hidden = all(look.hidden for look in looks)
                shared = {look.transparency for look in looks if not look.hidden}
                transparency = shared.pop() if len(shared) == 1 else 0
                if hidden or transparency:
                    out[name] = (hidden, transparency)
            return out

        return summary(by_id), summary(by_file)

    def is_subassembly(self, ident: str) -> bool:
        """Whether the view draws parts under ``ident``: a sub-assembly whose explode can be
        chosen."""
        inside = ident + "/"
        return any(iid.startswith(inside) for iid in self.instance_ids)

    def set_transparency(self, what: tuple[str, str], percent: int) -> None:
        """Make what ``what`` names this transparent (percent), as its menu does."""
        self.looks.transparent(self._scope(what), percent)
        self._apply_looks()

    def set_hidden(self, what: tuple[str, str], hidden: bool = True) -> None:
        self.looks.hide(self._scope(what), hidden)
        self._apply_looks()

    def isolate(self, what: tuple[str, str]) -> None:
        """Hide everything but what ``what`` names; nothing, when the view draws none of it
        (everything would be hidden)."""
        if not self.indices_of(what):
            return
        self.looks.isolate(self._scope(what))
        self._apply_looks()

    def show_all(self) -> None:
        self.looks.show_all()
        self._apply_looks()

    def reset_appearance(self) -> None:
        """Every component shown and opaque, and every sub-assembly exploding as the
        Explode bar's level says."""
        self.looks.reset()
        self._set_choices({})
        self._apply_looks()

    def set_subassembly_explodes(self, ident: str, on: bool) -> None:
        """Explode the sub-assembly ``ident`` (its components move apart) or keep it
        together, whatever the Explode bar's level says, until Reset appearance."""
        self._set_choices({**self.explode_choices, ident: bool(on)})

    def _set_choices(self, choices: dict[str, bool]) -> None:
        self.explode_choices = dict(choices)
        if self.document_key is not None:
            if choices:
                self._choices_by_document[self.document_key] = dict(choices)
            else:
                self._choices_by_document.pop(self.document_key, None)
        view = self.view
        if view is not None and hasattr(view, "set_explode_choices") and self.instance_ids:
            view.set_explode_choices(self.explode_choices)
        self._explode_text()

    def active_choices(self) -> dict[str, bool]:
        """The choices of sub-assemblies to explode or stay together that hold now: of those
        the view draws parts of, and not held together by one around them chosen to stay
        together (:func:`.explode.held_by`)."""
        choices = self.explode_choices
        return {s: on for s, on in choices.items() if held_by(s, choices) is None and self.is_subassembly(s)}

    def explode_pieces(self) -> int | None:
        """How many groups move apart now: at the bar's level, with the choices made for
        sub-assemblies, of what is shown; None with no assembly drawn."""
        if not self.instance_ids:
            return None
        level, choices = self.explode_level, self.explode_choices
        # Kept while the scene, the looks, the level and the choices hold: the bar asks again
        # at each step of its slider, and a large assembly takes a while to count.
        key = (level, tuple(sorted(choices.items())))
        kept = self._pieces
        if kept is not None and kept[2] == key:
            ids, looks, _key, pieces = kept
            if ids is self.instance_ids and looks is self.instance_looks:
                return pieces
        shown = (iid for g, iid in enumerate(self.instance_ids) if not self._hidden(g))
        pieces = len({group_of(iid, level, choices) for iid in shown})
        self._pieces = (self.instance_ids, self.instance_looks, key, pieces)
        return pieces

    def view_state(self) -> dict[str, Any]:
        """What the user chose to see here, for Back (:meth:`set_view_state`)."""
        return {"looks": self.looks.state(), "explode": dict(self.explode_choices)}

    def set_view_state(self, state: dict[str, Any] | None) -> None:
        """Put back what :meth:`view_state` gave, as Back does."""
        if state is None:
            return
        self.looks = Looks.from_state(state.get("looks"))
        self._set_choices(dict(state.get("explode") or {}))
        self._apply_looks()

    # -- the menus ---------------------------------------------------------------------------
    def _from_menu(self, change: Callable[[], None]) -> None:
        """A look chosen from a menu: made, then the pick dropped. The right-click that opened
        the menu picked the component, and a pick fades everything else, which would hide
        what a see-through housing is made see-through for: the view shows the result as
        it is."""
        change()
        self.drop_pick()

    def add_look_actions(self, menu: QMenu, what: tuple[str, str]) -> None:
        """Transparency, Hide (Show when it is all hidden) and Isolate for what ``what``
        names (:meth:`indices_of`), at the end of ``menu``; greyed, with the reason, when
        the view draws none of it."""
        hidden, transparency = self.target_look(what)
        drawn = bool(self.indices_of(what))
        steps = menu.addMenu("Transparency")
        steps.setToolTipsVisible(True)
        group = QActionGroup(steps)
        group.setExclusive(True)
        for step in TRANSPARENCY_STEPS:
            action = steps.addAction("Opaque" if not step else f"{step}%")
            action.setCheckable(True)
            action.setChecked(drawn and step == transparency)
            group.addAction(action)
            action.triggered.connect(
                lambda _on=False, s=step: self._from_menu(lambda: self.set_transparency(what, s))
            )
        hide = menu.addAction("Show" if drawn and hidden else "Hide")
        hide.setToolTip(
            tip(
                "Show it again"
                if hidden
                else "Leave it out of the view until you show it. Tab hides the part under the pointer."
            )
        )
        hide.triggered.connect(lambda: self._from_menu(lambda: self.set_hidden(what, not hidden)))
        isolate = menu.addAction("Isolate")
        isolate.setToolTip(tip("Hide everything else"))
        isolate.triggered.connect(lambda: self._from_menu(lambda: self.isolate(what)))
        if not drawn:
            why = tip("The 3D view draws none of it here: suppressed, not read, or not in this configuration")
            for action in (steps.menuAction(), hide, isolate):
                action.setEnabled(False)
                action.setToolTip(why)

    def add_camera_actions(self, menu: QMenu) -> None:
        """Zoom to Fit, the standard views, Home and Copy Image, as the view's keys and its
        view cube give them; nothing while no model is drawn."""
        view = self.view
        if view is None or self.mesh_state != "ready" or not hasattr(view, "set_view"):
            return
        if not menu.isEmpty():
            menu.addSeparator()
        fit = menu.addAction("Zoom to Fit")
        fit.setShortcut("F")
        fit.setToolTip(tip("Fit what is shown to the view"))
        fit.triggered.connect(lambda: view.fit())
        views = menu.addMenu("Standard Views")
        for n, name in VIEW_KEYS.items():
            action = views.addAction(name.capitalize())
            action.setShortcut(f"Ctrl+{n}")
            action.triggered.connect(lambda _on=False, v=name: view.set_view(v, animate=True))
        home = menu.addAction("Go Home")
        home.setShortcut("Home")
        home.setToolTip(tip("Turn to the Home view: the isometric one, or the one you set"))
        home.triggered.connect(lambda: view.go_home())
        set_home = menu.addAction("Set Current View as Home")
        set_home.setToolTip(tip("Make the view as it is now the one Home turns to"))
        set_home.triggered.connect(lambda: view.set_home(True))
        menu.addSeparator()
        copy = menu.addAction("Copy Image")
        copy.setToolTip(tip("Copy the 3D view as it is now to the clipboard, to paste into another program"))
        copy.triggered.connect(self.copy_image)
        from .animationaction import MENU_TEXT, MENU_TIP, available

        if available(view):
            save = menu.addAction(MENU_TEXT)
            save.setToolTip(tip(MENU_TIP))
            save.triggered.connect(self.save_animation)

    def save_animation(self, *, dialog=None, runner=None) -> bool:
        """Save Animation... (:mod:`.animationaction`): ask for the clip's options, then
        where to save it, then draw and encode it. ``dialog`` and ``runner`` stand in for
        the options dialog and the run in tests."""
        from .animationaction import AnimationDialog, OptionsError, SaveAnimation

        view = self.view
        if view is None or not hasattr(view, "render_frames"):
            return False
        dialog = dialog or AnimationDialog(self, assembly=bool(getattr(view, "can_explode", False)))
        if dialog.result() != QDialog.DialogCode.Accepted and dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        try:
            options = dialog.options()
        except OptionsError as exc:
            QMessageBox.warning(self, "Save Animation", f"That clip cannot be made: {exc}.")
            return False
        path = self.document_path
        name = os.path.splitext(os.path.basename(path))[0] if path else "animation"
        runner = runner or SaveAnimation(self, view, name)
        return runner.run(options)

    def copy_image(self) -> None:
        """The 3D view as drawn now, on the clipboard (nothing is written to a file)."""
        if self.view is not None and hasattr(self.view, "grabFramebuffer"):
            from PySide6.QtWidgets import QApplication

            QApplication.clipboard().setImage(self.view.grabFramebuffer())

    def add_view_actions(self, menu: QMenu) -> None:
        """Show all and Reset appearance, each on only when it has something to do."""
        show = menu.addAction("Show all")
        show.setToolTip(tip("Show every component hidden here again (Shift+Tab)"))
        show.setEnabled(self.looks.any_hidden)
        show.triggered.connect(lambda: self._from_menu(self.show_all))
        reset = menu.addAction("Reset appearance")
        reset.setToolTip(
            tip(
                "Every component shown and opaque again, and every sub-assembly exploding as the Explode "
                "bar's level says"
            )
        )
        reset.setEnabled(self.looks.changed or bool(self.explode_choices))
        reset.triggered.connect(lambda: self._from_menu(self.reset_appearance))

    def add_explode_actions(self, menu: QMenu, subs: list[str], *, this: bool = False) -> None:
        """A check item for each sub-assembly of ``subs``: whether it explodes, from its
        choice or the bar's level; ``this`` labels a single one's own row. One inside a
        sub-assembly chosen to stay together moves with that one whatever its own choice:
        its item is greyed and unchecked, and its tooltip names that one."""
        choices = self.explode_choices
        for sub in subs:
            name = sub.rpartition("/")[2]
            action = menu.addAction("Explode this sub-assembly" if this else f"Explode sub-assembly {name}")
            action.setCheckable(True)
            action.setChecked(explodes(sub, self.explode_level, choices))
            holder = held_by(sub, choices)
            if holder is not None:
                action.setEnabled(False)
                text = f"{sub} moves as one with {holder}, which you chose to keep together."
                if sub in choices:
                    wish = "to explode" if choices[sub] else "to stay together"
                    text += f" Your choice for it, {wish}, holds once {holder.rpartition('/')[2]} explodes."
                action.setToolTip(tip(text))
            else:
                why = "Your choice, until Reset appearance." if sub in choices else "As the bar's level says."
                what = f"{sub}: its components move apart when the assembly explodes, or it moves as one."
                action.setToolTip(tip(f"{what} {why}"))
            action.triggered.connect(lambda on, s=sub: self.set_subassembly_explodes(s, on))

    def add_instance_actions(
        self, menu: QMenu, ident: str, *, path: bool, subassembly: bool | None = None
    ) -> None:
        """For the instance or sub-assembly ``ident``: how it looks; with ``path`` (a part
        right-clicked in the view) each sub-assembly it is in, from the part up, how that
        looks in a submenu of its own and whether it explodes, else, for a sub-assembly's
        own row (``subassembly``, by default whether the view draws parts under it),
        whether it explodes; then Show all and Reset appearance."""
        menu.setToolTipsVisible(True)
        menu.addSeparator()
        self.add_look_actions(menu, ("instance", ident))
        subs = subassemblies(ident)[::-1] if path else []
        if subassembly is None:
            subassembly = self.is_subassembly(ident)
        if subs:
            menu.addSeparator()
            for sub in subs:
                inner = menu.addMenu(f"Sub-assembly {sub.rpartition('/')[2]}")
                inner.setToolTipsVisible(True)
                self.add_look_actions(inner, ("instance", sub))
            menu.addSeparator()
            self.add_explode_actions(menu, subs)
        elif not path and subassembly:
            menu.addSeparator()
            self.add_explode_actions(menu, [ident], this=True)
        menu.addSeparator()
        self.add_view_actions(menu)

    def add_file_actions(self, menu: QMenu, key: str) -> None:
        """For every instance of the file ``key``: how they look, then Show all and Reset
        appearance."""
        menu.setToolTipsVisible(True)
        menu.addSeparator()
        self.add_look_actions(menu, ("file", key))
        menu.addSeparator()
        self.add_view_actions(menu)

    def _ensure_view(self) -> QWidget:
        if self.view is None:
            if self.view_factory is not None:
                view = self.view_factory()
            else:
                from .view3d import ModelView

                view = ModelView(
                    mouse_style=self.mouse_style,
                    invert_wheel=self.invert_wheel,
                    rotation_mode=self.rotation_mode,
                    show_cube=self.show_cube,
                    about_pointer=self.about_pointer,
                )
            view.failed.connect(self._gl_failed)  # type: ignore[attr-defined]
            if hasattr(view, "homeChanged"):
                view.homeChanged.connect(self._home_changed)  # type: ignore[attr-defined]
            if hasattr(view, "picked"):
                view.picked.connect(self._picked)  # type: ignore[attr-defined]
                view.activated.connect(self._activated)  # type: ignore[attr-defined]
                view.menuRequested.connect(self._menu)  # type: ignore[attr-defined]
                view.describe = self.describe_instance  # type: ignore[attr-defined]
            if hasattr(view, "hideRequested"):
                view.hideRequested.connect(self._hide_key)  # type: ignore[attr-defined]
                view.showAllRequested.connect(lambda: self._from_menu(self.show_all))  # type: ignore[attr-defined]
                view.any_hidden = lambda: self.looks.any_hidden  # type: ignore[attr-defined]
            self.model_stack.addWidget(view)
            self.view = view
        return self.view

    def _gl_failed(self, why: str) -> None:
        self.mesh_state = "gl_failed"
        self._model_message(
            f"The 3D view could not draw here: {why}. The preview image still works under Image.", error=True
        )
        self._update_caption()


def _nothing_text(geometry: dict[str, Any]) -> str:
    """Why an assembly configuration shows nothing in 3D."""
    if not geometry.get("skipped_count"):
        return (
            "Nothing to draw: this assembly configuration has no part that is shown. The preview image is "
            "under Image."
        )
    text = (
        "Nothing to draw: no instance of this assembly configuration has a display mesh that could be read. "
        "The status line below says why for each."
    )
    boxes = (geometry.get("placeholders") or {}).get("count")
    if boxes:
        text += f" {BOXES_SETTING} draws {plural(boxes, 'of them', 'of them')} as boxes."
    return text + " The preview image is under Image."


def _too_large_text(result: dict[str, Any]) -> str:
    cap = result.get("cap") or 0
    raise_it = "Raise the limit under Settings > 3D View to draw it."
    if result.get("model") and result.get("memory"):
        return (
            f"Reading this model needed more memory than the 3D view allows under its limit of {cap:,} "
            f"triangles, so it was stopped. {raise_it}"
        )
    if result.get("model"):
        return (
            f"This model comes to more than the 3D view's limit of {cap:,} triangles. {raise_it} A model "
            "this size takes a while to read."
        )
    if result.get("geometry") is not None:
        return (
            f"The display meshes of this assembly take more than the 3D view's limit of {cap:,} triangles "
            f"before any instance could be drawn. {raise_it}"
        )
    if result.get("in_assembly"):
        return (
            f"The display mesh this virtual part's assembly keeps of it is more than the 3D view's limit "
            f"of {cap:,} triangles. {raise_it}"
        )
    if result.get("from_bodies"):
        return (
            f"This part saved no display mesh, and its bodies come to more than the 3D view's limit of "
            f"{cap:,} triangles. {raise_it}"
        )
    if "triangles" in result:
        return (
            f"This part's saved display mesh has {result['triangles']:,} triangles, more than the 3D view's "
            f"limit of {cap:,}. {raise_it} A mesh this size takes a while to read."
        )
    if "bytes" in result:
        return (
            f"This part's saved display data is {result['bytes'] / 1e6:,.0f} MB, more than the 3D view reads "
            f"under its limit of {cap:,} triangles ({result['budget'] / 1e6:,.0f} MB), so it was not read. "
            f"{raise_it} Data this size takes a while to read."
        )
    return (
        "Reading this part's saved display mesh needed more memory than the 3D view allows under its "
        f"limit of {cap:,} triangles, so it was stopped. {raise_it}"
    )
