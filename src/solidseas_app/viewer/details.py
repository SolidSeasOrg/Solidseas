"""The details panel: one tab per view of the selected document.

Each tab is a :class:`Page`, which shows either a message (reading, an error,
nothing to show) or its content. The window feeds the panel one section at a
time as the worker reads them (:mod:`.reading`), and the panel only displays:
it never reads a file itself.

Document text is shown as plain text only. Item text in a tree is always
plain, but Qt decides by itself whether a tooltip is rich text, so every
tooltip goes through :func:`.wording.tip`.

The panel works on the UI thread, so it bounds what it builds: each tree shows
at most :data:`MAX_ROWS` rows and then a row saying how many more there are,
items are built detached and added in one call, and the Raw JSON tab shows the
first :data:`JSON_VIEW_CHARS` characters (Copy Summary JSON copies all of it).
A crafted part with 200,000 custom properties otherwise held the window for
29 seconds.

A row that stands for a referenced file (an instance, a file, a drawing view,
a model, a reference) goes to that file on a double-click or Enter, and its
context menu has Open and Show in File Explorer (the file in the program the
system opens it with, and in its folder: :mod:`.opening`), then Go to file and
Show in folder list (here, in the viewer): the panel says which file and what to
do through ``componentRequested`` and the window does it (:mod:`.navigate`). A
sub-assembly's row of the instances opens and closes on a double-click instead,
as a tree does everywhere in Windows (and SOLIDWORKS' FeatureManager); Enter
and the menu still go to its file. When the file is a part or an assembly, the
menu also has 3D Print for it, in the row's configuration (:meth:`DetailsPanel.add_print`,
which the window's :attr:`DetailsPanel.print_item` fills in; off, with the reason,
for a file that was not found); the 3D view's menu for a part has it for the part
and for each sub-assembly the part is in, nearest first (a part read from a
sub-assembly's own file, which no row stands for, through the document the view
drew it from, :attr:`DetailsPanel.print_document`, or off with the reason when the
view drew it from what its sub-assembly stores of it, its own file not found,
:attr:`DetailsPanel.print_missing`), and the legend's for a file.

The assembly's 3D view on the Preview tab and the Components tab pick the same
thing: an instance clicked in the view becomes the current row of the
instances, and the current row of the instances (or of the files) is picked in
the view. An instance double-clicked or right-clicked in the view goes to its
file, or opens its row's menu, exactly as its row would. An instance drawn as a
box, for want of a mesh, is one of these rows like any other. One the library
read from a sub-assembly's own file, which the components section does not
list, has no row: picking it leaves no row current, and a double-click or the
menu goes to the file of the sub-assembly it came from, whose row stands for it
(:meth:`DetailsPanel.row_of`).

A 3D file of another format than SOLIDWORKS (STEP, STL, 3MF, Alibre Design...) is
shown from the sections the window's worker pool reads (:func:`.reading.read_model`):
the Overview from its ``model_summary`` and the measures of its geometry
(:mod:`.modeldetails`), the Preview from the image it stores or one rendered from
its geometry, Properties as for a SOLIDWORKS document, Components for an assembly
from its tree (:func:`.modelview.components_data`, whose rows the 3D view picks as
it does a SOLIDWORKS assembly's), References for the files it names (an Alibre
assembly's components, found by their document GUID), and Raw JSON. BOM and Paths
are SOLIDWORKS documents' and are hidden for it; Where Used asks the index about it as
about a SOLIDWORKS document, and says when its format is one the index does not hold
(one SolidSeas cannot read). A row that stands for
something inside the file itself (:func:`.modelview.is_internal`) has no Go to file
or 3D Print entry: there is no file of its own to go to.

The Where Used tab (:mod:`.whereused`) is filled by the window from the opened
folder's index, not from the document's sections, so a message about reading
the document (a file that would not open, one the listing did not read) leaves
it alone.

The BOM tab shows an assembly configuration's bill of materials as SOLIDWORKS
draws its BOM tables (top-level only, parts only or indented, numbered 3.1 under
3), from the bom section the worker read with the references' resolution; its
configuration is the Components tab's, and a row goes to its file as an
instance's row does.

With the 3D view on, the menus of the instances and the files add how they look
there (Transparency, Hide, Isolate, Show all, Reset appearance) and, on a
sub-assembly's row, whether it explodes; a sub-assembly's file stands for every
part of every instance of it, as the panel tells the 3D view
(:func:`component_files`). The rows of instances (and of files) whose every
drawn instance is hidden are greyed with an eye struck through, and those all
transparent marked with a half filled square (:meth:`DetailsPanel._show_looks`).
"""

import html
import re
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from solidseas.bom import BOM_TYPES, table_cells
from solidseas.bom import COLUMNS as BOM_COLUMNS
from solidseas.bom import TYPE_NAMES as BOM_TYPE_NAMES

from . import modeldetails, navigate, opening
from .explode import subassemblies
from .menus import relay_status_tips
from .modelview import is_internal
from .preview import PreviewPane, files_text
from .reading import (
    DOC_TYPES,
    ROOT_ID,
    date_text,
    doc_type_of,
    is_model,
    mm,
    release_text,
    rotation_text,
    size_text,
    time_text,
)
from .whereused import WhereUsedPane
from .wording import (
    error_message,
    field_text,
    first_sentence,
    format_name,
    name_source,
    plural,
    reference_status,
    role_text,
    rule_text,
    stream_text,
    tip,
    unread_text,
    unusable,
)

TABS = (
    "Overview",
    "Preview",
    "Properties",
    "Components",
    "BOM",
    "References",
    "Where Used",
    "Paths",
    "Raw JSON",
)
TAB_SECTIONS = {
    "Overview": "summary",
    "Preview": "preview",
    "Properties": "summary",
    "Components": "components",
    "BOM": "bom",
    "References": "references",
    "Where Used": "where_used",
    "Paths": "paths",
    "Raw JSON": "summary",
}
# Hidden for a file of another format. Where Used stays: the index holds such files too.
SOLIDWORKS_TABS = ("BOM", "Paths")
MAX_ROWS = 2000  # rows one tree shows; the rest are counted in a last row
JSON_VIEW_CHARS = 1_000_000  # characters the Raw JSON tab shows

# Item data of a row that stands for a referenced file: the file key (C7), the row's
# own name in its tree (an instance id, a file key...) to find it again after Back,
# and for an instance the file key of the sub-assembly it is in and the configuration
# of the file it uses.
KEY_ROLE = Qt.ItemDataRole.UserRole
IDENT_ROLE = Qt.ItemDataRole.UserRole + 1
PARENT_ROLE = Qt.ItemDataRole.UserRole + 2
CONFIG_ROLE = Qt.ItemDataRole.UserRole + 3
# A row's look as built, which the 3D view's hidden and transparent states are shown over:
# greyed for a suppressed instance, and its first column's tooltip.
GREY_ROLE = Qt.ItemDataRole.UserRole + 4
TIP_ROLE = Qt.ItemDataRole.UserRole + 5
# A drawing view's row: the configuration the view shows its model in, which 3D Print
# uses (Go to file shows the model as it was saved).
VIEW_CONFIG_ROLE = Qt.ItemDataRole.UserRole + 6
# What componentRequested asks for: go to the file here, show it in the folder list, open it
# in its own program, or show it in its folder in the system's file manager.
OPEN, SHOW, PROGRAM, REVEAL = "open", "show", "program", "reveal"
OPEN_TEXT, SHOW_TEXT = navigate.GO_TEXT, "Show in folder list"

_LIGHT = {"green": "#2e7d32", "blue": "#1565c0", "purple": "#6a1b9a", "orange": "#c25100", "red": "#c62828"}
_DARK = {"green": "#81c784", "blue": "#64b5f6", "purple": "#ce93d8", "orange": "#ffb74d", "red": "#ef9a9a"}
_STATUS_TONE = {
    "resolved": "green",
    "moved": "blue",
    "embedded": "purple",
    "ambiguous": "orange",
    "missing": "red",
    "embedded_not_found": "red",
}
_SEVERITY_TONE = {"high": "red", "medium": "orange"}
_CATEGORIES = {
    "unc": "Network shares",
    "project": "Project folders",
    "profile": "User profile folders",
    "desktop": "Desktop",
    "temp": "Temp folders",
    "program": "Program folders",
    "windows": "Windows folders",
    "drive_root": "Drive roots",
}
_LINK_EXPRESSION = re.compile(r'"[^"]*@[^"]*"')  # "SW-Mass@part.SLDPRT", "D1@Sketch1"


def _tone(widget: QWidget, name: str | None) -> QColor | None:
    if name is None:
        return None
    dark = widget.palette().color(QPalette.ColorRole.Base).lightness() < 128
    return QColor((_DARK if dark else _LIGHT)[name])


def _state(node: dict[str, Any], *, parent_suppressed: bool = False) -> str:
    """An instance's flags in words: ``suppressed, excluded from BOM``, or empty. A
    child of a suppressed sub-assembly is ``suppressed (parent)``: SOLIDWORKS and
    the Files counts treat it as suppressed, whatever its own flag says."""
    flags = [
        word
        for word, on in (
            ("suppressed", node["suppressed"]),
            ("suppressed (parent)", parent_suppressed and not node["suppressed"]),
            ("hidden", node["hidden"]),
            ("excluded from BOM", node["excluded_from_bom"]),
            ("virtual", node["virtual"]),
        )
        if on
    ]
    return ", ".join(flags)


def _value_text(p: dict[str, Any]) -> str:
    v = p.get("value")
    if p["type"] == "boolean" and v is not None:
        return "Yes" if v else "No"
    if p["type"] == "date" and v is not None:
        return date_text(v)  # a date, never a time: SOLIDWORKS shows none
    if p["type"] == "number" and v is not None:
        return f"{v:g}" if isinstance(v, float) else str(v)
    if v is None:
        return p.get("text") or ""
    return str(v)


def is_computed(p: dict[str, Any]) -> bool:
    """The expression links to a model value or holds an equation (``"SW-Mass@..."``),
    so the value is SOLIDWORKS' result from the last save. The library's ``linked``
    decides the same from how the file stores the expression, and also covers
    ``$PRP:`` links, which hold no ``@``."""
    return bool(_LINK_EXPRESSION.search(p.get("expression") or ""))


def _tree(columns: tuple[str, ...], *, stretch: int | None = None) -> QTreeWidget:
    tree = QTreeWidget()
    tree.setColumnCount(len(columns))
    tree.setHeaderLabels(list(columns))
    tree.setAlternatingRowColors(True)
    tree.setUniformRowHeights(True)
    tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
    header = tree.header()
    header.setStretchLastSection(stretch is None)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    if stretch is not None:
        header.setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
    return tree


def _fit(tree: QTreeWidget, *, max_width: int = 360) -> None:
    for c in range(tree.columnCount()):
        if tree.header().sectionResizeMode(c) == QHeaderView.ResizeMode.Stretch:
            continue
        tree.resizeColumnToContents(c)
        if tree.columnWidth(c) > max_width:
            tree.setColumnWidth(c, max_width)


def _make(
    values: list[Any], *, bold: bool = False, color: QColor | None = None, tip_text: str | None = None
) -> QTreeWidgetItem:
    """An item not yet in any tree: adding it later, with its siblings, is one call."""
    item = QTreeWidgetItem(["" if v is None else str(v) for v in values])
    n = len(values)
    if bold:
        f = item.font(0)
        f.setBold(True)
        for c in range(n):
            item.setFont(c, f)
    if color is not None:
        for c in range(n):
            item.setForeground(c, color)
    if tip_text:
        safe = tip(tip_text)
        for c in range(n):
            item.setToolTip(c, safe)
    return item


def _item(parent, values: list[Any], **kw) -> QTreeWidgetItem:
    item = _make(values, **kw)
    if isinstance(parent, QTreeWidget):
        parent.addTopLevelItem(item)
    else:
        parent.addChild(item)
    return item


def _more(n: int, what: str, many: str, where: str = "") -> QTreeWidgetItem:
    item = _make([f"{plural(n, what, many)} more not shown{where}"])
    f = item.font(0)
    f.setItalic(True)
    item.setFont(0, f)
    return item


def _link(
    item: QTreeWidgetItem,
    key: str | None,
    ident: str,
    parent: str | None = None,
    configuration: str | None = None,
) -> None:
    """Mark ``item`` as standing for the referenced file ``key``; an instance also
    names the sub-assembly it is in and the configuration of the file it uses."""
    if key is None:
        return
    item.setData(0, KEY_ROLE, key)
    item.setData(0, IDENT_ROLE, ident)
    if parent is not None:
        item.setData(0, PARENT_ROLE, parent)
    if configuration:
        item.setData(0, CONFIG_ROLE, configuration)


_ICONS: dict[str, QIcon] = {}


def look_icon(kind: str) -> QIcon:
    """The Components tab's mark of a row hidden in the 3D view (an eye struck through),
    or transparent there (a square half filled, its outline showing through)."""
    if kind not in _ICONS:
        pix = QPixmap(14, 14)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        grey = QColor("#6b7480")
        p.setPen(QPen(grey, 1.2))
        if kind == "hidden":
            p.drawEllipse(2, 4, 10, 6)
            p.setBrush(grey)
            p.drawEllipse(5, 5, 4, 4)
            p.setPen(QPen(QColor("#c62828"), 1.6))
            p.drawLine(2, 12, 12, 2)
        else:
            p.drawRect(2, 2, 10, 10)
            p.fillRect(3, 3, 9, 4, QColor(107, 116, 128, 90))
            p.fillRect(3, 7, 9, 5, QColor(107, 116, 128, 200))
        p.end()
        _ICONS[kind] = QIcon(pix)
    return _ICONS[kind]


def component_files(c: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Of an assembly's components section ``c``: each sub-assembly's file key by its
    component tree id, at every level of the tree (not only the rows shown), and each
    file's name by its key, for the 3D view (:meth:`.preview.PreviewPane.set_components`).
    A sub-assembly is a component with components of its own or an assembly's file: the
    view may draw parts read from its own file under one the tree has no children for."""
    kinds = {f["key"]: f.get("doc_type") for f in c.get("files") or []}
    files: dict[str, str] = {}
    stack = list(c.get("children") or [])
    while stack:
        n = stack.pop()
        ident, key, inside = n.get("id") or n.get("name"), n.get("file"), n.get("children") or []
        if ident and key and (inside or kinds.get(key) == "assembly"):
            files[ident] = key
        stack.extend(inside)
    names = {f["key"]: f.get("file_name") or f.get("stored_path") or f["key"] for f in c.get("files") or []}
    return files, names


def _walk(tree: QTreeWidget):
    stack = [tree.topLevelItem(i) for i in reversed(range(tree.topLevelItemCount()))]
    while stack:
        item = stack.pop()
        yield item
        stack.extend(item.child(i) for i in reversed(range(item.childCount())))


def _reset(tree: QTreeWidget) -> None:
    tree.setUpdatesEnabled(False)
    tree.clear()


def _done(tree: QTreeWidget) -> None:
    tree.setUpdatesEnabled(True)


class Page(QStackedWidget):
    """A tab's content, or a message in its place."""

    def __init__(self, content: QWidget) -> None:
        super().__init__()
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.label.setContentsMargins(24, 24, 24, 24)
        self.addWidget(self.label)
        self.addWidget(content)
        self.message_text = ""

    def message(self, text: str, *, error: bool = False) -> None:
        self.message_text = text
        self.label.setText(text)
        color = _tone(self, "red") if error else None
        self.label.setStyleSheet(f"color: {color.name()};" if color else "")
        self.setCurrentIndex(0)

    def show_content(self) -> None:
        self.message_text = ""
        self.setCurrentIndex(1)

    @property
    def showing_content(self) -> bool:
        return self.currentIndex() == 1


class OverviewImage(QWidget):
    """The document's preview image at the top of the Overview tab, at most
    :attr:`LONGEST` pixels on its longer side and narrower when the panel is. A
    click, Enter or Space emits ``activated``: the panel shows the Preview tab."""

    activated = Signal()
    LONGEST = 280
    MARGIN = 4  # room for the focus and hover frame

    def __init__(self) -> None:
        super().__init__()
        self._source: QPixmap | None = None
        self._scaled: QPixmap | None = None
        self._scaled_for: tuple[int, int, float] | None = None
        self._pressed = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Show in the Preview tab")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        policy = QSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.hide()

    def set_image(self, pix: QPixmap | None, name: str = "") -> None:
        """Show ``pix`` (the Preview tab's image) for the document ``name``, or hide for None."""
        if pix is None or pix.isNull():
            self._source = self._scaled = self._scaled_for = None
            self.setAccessibleName("")
            self.hide()
            return
        self._source, self._scaled, self._scaled_for = pix, None, None
        self.setAccessibleName(f"Preview of {name}" if name else "Preview")
        self.setAccessibleDescription("Shows the image on the Preview tab")
        self.updateGeometry()
        self.show()
        self.update()

    @property
    def has_image(self) -> bool:
        return self._source is not None

    def _fitted(self, width: int) -> QSize:
        """The image's size on screen within ``width`` (frame included), aspect kept."""
        if self._source is None:
            return QSize(0, 0)
        dpr = self._source.devicePixelRatio() or 1.0
        sw, sh = self._source.width() / dpr, self._source.height() / dpr
        room = max(1, min(self.LONGEST, width - 2 * self.MARGIN))
        scale = min(1.0, self.LONGEST / max(sw, sh), room / sw)
        return QSize(max(1, round(sw * scale)), max(1, round(sh * scale)))

    def sizeHint(self) -> QSize:
        size = self._fitted(self.LONGEST + 2 * self.MARGIN)
        return size + QSize(2 * self.MARGIN, 2 * self.MARGIN)

    def minimumSizeHint(self) -> QSize:
        return QSize(min(64, self.sizeHint().width()), self.heightForWidth(64))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._fitted(width).height() + 2 * self.MARGIN

    def _pixmap(self, size: QSize) -> QPixmap | None:
        """The source scaled smoothly to ``size`` at the screen's pixel ratio, kept until either changes."""
        if self._source is None:
            return None
        dpr = self.devicePixelRatioF()
        key = (size.width(), size.height(), dpr)
        if self._scaled is None or self._scaled_for != key:
            pix = self._source.scaled(
                QSize(round(size.width() * dpr), round(size.height() * dpr)),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            pix.setDevicePixelRatio(dpr)
            self._scaled, self._scaled_for = pix, key
        return self._scaled

    def paintEvent(self, event) -> None:
        size = self._fitted(self.width())
        pix = self._pixmap(size)
        if pix is None:
            return
        frame = QRect(0, 0, size.width() + 2 * self.MARGIN, size.height() + 2 * self.MARGIN)
        painter = QPainter(self)
        painter.drawPixmap(self.MARGIN, self.MARGIN, pix)
        pal = self.palette()
        if self.hasFocus():
            painter.setPen(QPen(pal.color(QPalette.ColorRole.Highlight), 2))
            painter.drawRoundedRect(frame.adjusted(1, 1, -1, -1), 3, 3)
        else:
            color = pal.color(QPalette.ColorRole.Highlight if self.underMouse() else QPalette.ColorRole.Mid)
            painter.setPen(QPen(color, 1))
            painter.drawRoundedRect(frame.adjusted(0, 0, -1, -1), 3, 3)
        painter.end()

    def event(self, event) -> bool:
        if event.type() in (QEvent.Type.HoverEnter, QEvent.Type.HoverLeave):
            self.update()
        return super().event(event)

    def mousePressEvent(self, event) -> None:
        self._pressed = event.button() == Qt.MouseButton.LeftButton
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if (
            self._pressed
            and event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.activated.emit()
        self._pressed = False
        event.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit()
            event.accept()
            return
        super().keyPressEvent(event)


def _caption() -> QLabel:
    label = QLabel()
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setContentsMargins(6, 4, 6, 4)
    return label


class DetailsPanel(QWidget):
    """The tabs for one document. ``configurationRequested`` asks the window to read an
    assembly's components in another configuration; ``componentRequested`` asks it to
    go to a referenced file: (file key, :data:`OPEN` or :data:`SHOW`, the file key of
    the sub-assembly the row is in, the configuration of the file the instance uses;
    "" where there is none). ``geometryFailed`` says a model file's geometry could not
    be read: (its path below the opened folder, the first sentence of why), so the
    window marks its row."""

    configurationRequested = Signal(str)
    componentRequested = Signal(str, str, str, str)
    bomExportRequested = Signal()
    bomEditRequested = Signal()
    geometryFailed = Signal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.title = QLabel()
        f = self.title.font()
        f.setPointSizeF(f.pointSizeF() * 1.35)
        f.setBold(True)
        self.title.setFont(f)
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.subtitle = QLabel()
        self.subtitle.setTextFormat(Qt.TextFormat.PlainText)
        self.subtitle.setWordWrap(True)
        self.subtitle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # Says where a document opened from another one's contents comes from, when it
        # is not a row of the list: outside the opened folder, or inside its assembly.
        self.note = QLabel()
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        self.note.setWordWrap(True)
        self.note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.note.setStyleSheet(
            "QLabel { background: rgba(194, 81, 0, 0.14); border: 1px solid rgba(194, 81, 0, 0.5);"
            " border-radius: 3px; padding: 4px 6px; }"
        )
        self.note.hide()

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.pages: dict[str, Page] = {}

        self.overview = _tree(("Field", "Value"))
        # The Preview tab's image above the Overview's facts, when the document has one.
        self.overview_image = OverviewImage()
        self.overview_image.activated.connect(self.show_preview_image)
        overview = QWidget()
        ol = QVBoxLayout(overview)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(4)
        ol.addWidget(self.overview_image, 0, Qt.AlignmentFlag.AlignLeft)
        ol.addWidget(self.overview, 1)
        self.preview = PreviewPane()
        # The 3D view's configuration list is this tab's: a choice there reads this tab again.
        self.preview.configurationChosen.connect(self.configurationRequested)
        self.properties = _tree(("Name", "Value", "Type", "Expression", "Computed"))
        self.properties.headerItem().setToolTip(
            4,
            tip(
                "Yes when the expression links to a model value or holds an equation. Value is then "
                "the result SOLIDWORKS stored at the last save, which can be out of date."
            ),
        )
        self._build_components()
        self._build_bom()
        self.ref_summary = _caption()
        self.references = _tree(
            ("File", "Status", "Found at", "Found by", "Confidence", "Identity", "Stored path", "Notes")
        )
        self.paths_summary = _caption()
        self.paths = _tree(("Path or name", "Severity", "Why it is stored", "Account", "Found in"))
        for tree in (self.references, self.paths):  # a path's end names the file: keep it in view
            tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.paths_note = _caption()
        self.where_used = WhereUsedPane()
        self.json = QPlainTextEdit()
        self.json.setReadOnly(True)
        self.json.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.json.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))

        refs = QWidget()
        rl = QVBoxLayout(refs)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.ref_summary)
        rl.addWidget(self.references, 1)
        paths = QWidget()
        pal = QVBoxLayout(paths)
        pal.setContentsMargins(0, 0, 0, 0)
        pal.addWidget(self.paths_summary)
        pal.addWidget(self.paths, 1)
        pal.addWidget(self.paths_note)
        contents = {
            "Overview": overview,
            "Preview": self.preview,
            "Properties": self.properties,
            "Components": self.components_widget,
            "BOM": self.bom_widget,
            "References": refs,
            "Where Used": self.where_used,
            "Paths": paths,
            "Raw JSON": self.json,
        }
        for name in TABS:
            page = Page(contents[name])
            self.pages[name] = page
            self.tabs.addTab(page, name)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 0)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addWidget(self.note)
        layout.addWidget(self.tabs, 1)

        # The rows that stand for a referenced file, by a name kept with Back's place.
        self.linked_trees = {
            "instances": self.instances,
            "files": self.files,
            "sheets": self.sheets,
            "models": self.models,
            "bom": self.bom_tree,
            "references": self.references,
        }
        for tree in self.linked_trees.values():
            # In the instances (and a drawing's sheets), a double-click opens and closes a row
            # with rows under it, a sub-assembly, as everywhere in Windows, and goes to the
            # file of any other row; Enter, and Go to file on the context menu, go to the file
            # of any row. Elsewhere the rows under a file are details of it (the References
            # tab's candidates), so a double-click on the file goes to it.
            tree.setExpandsOnDoubleClick(tree in (self.instances, self.sheets))
            tree.itemDoubleClicked.connect(self._double_clicked)
            tree.installEventFilter(self)
            tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            tree.customContextMenuRequested.connect(lambda pos, t=tree: self._context_menu(t, pos))
        # The 3D view's pick and the Components tab's current row follow each other.
        self.preview.instancePicked.connect(self.select_instance)
        self.preview.instanceActivated.connect(self.open_instance)
        self.preview.instanceMenu.connect(self.instance_menu_at)
        self.preview.filePicked.connect(self.select_file)
        self.preview.boxesPicked.connect(self._no_current_rows)
        self.preview.row_of = self.row_of
        self.preview.file_menu = self._file_link_menu
        self.preview.looksChanged.connect(self._show_looks)
        self.preview.pickDropped.connect(self._no_current_rows)
        # The window's 3D Print entry for a menu: (menu, its text, the file key, the file key
        # of the sub-assembly the row is in, the configuration); None: the menus have none.
        self.print_item: Callable[[QMenu, str, str, str, str], Any] | None = None
        # And for a document the 3D view drew a part from that no row stands for: (menu,
        # its text, the document, :attr:`.preview.PreviewPane.instance_documents`).
        self.print_document: Callable[[QMenu, str, dict[str, Any]], Any] | None = None
        # And, off with the reason, for such a part drawn from what its sub-assembly stores
        # of it, its own file not found: (menu, its text, what the view keeps of it,
        # :attr:`.preview.PreviewPane.instance_missing`).
        self.print_missing: Callable[[QMenu, str, dict[str, Any]], Any] | None = None
        self._quiet = False  # rows made current or not here, for the view's pick: the view keeps it
        self.instances.currentItemChanged.connect(self._instance_current)
        self.files.currentItemChanged.connect(self._file_current)
        self._header_tips(False)

        self.summary: dict[str, Any] | None = None
        self.summary_json: str | None = None
        self.model_file = False  # a 3D file of another format than SOLIDWORKS is shown
        self.geometry: dict[str, Any] | None = None  # its measures, once read
        self.geometry_error: dict[str, Any] | None = None
        self.where = ""
        self.path: str | None = None  # the document's full path, to shorten reader messages
        self.size: int | None = None
        self.sections: dict[str, dict[str, Any]] = {}
        self.clear("Open a folder, then select a document to see its details.")

    def _build_components(self) -> None:
        self.config_combo = QComboBox()
        self.config_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.config_combo.activated.connect(
            lambda i: self.configurationRequested.emit(self.config_combo.itemText(i))
        )
        self.components_counts = QLabel()
        self.components_counts.setTextFormat(Qt.TextFormat.PlainText)
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 4)
        self.config_label = QLabel("Configuration:")
        bar.addWidget(self.config_label)
        bar.addWidget(self.config_combo)
        bar.addSpacing(12)
        bar.addWidget(self.components_counts, 1)

        self.instances = _tree(
            (
                "Instance",
                "Configuration",
                "State",
                "X (mm)",
                "Y (mm)",
                "Z (mm)",
                "Rotation",
            )
        )
        self.instances.headerItem().setToolTip(
            2,
            tip(
                "Suppressed, hidden, excluded from the bill of materials, virtual. "
                '"suppressed (parent)": inside a suppressed sub-assembly.'
            ),
        )
        for c in (3, 4, 5):
            self.instances.headerItem().setToolTip(c, tip("Position in the top assembly's frame"))
        self.files = _tree(
            ("File", "Type", "Instances", "Unsuppressed", "In BOM", "Configurations used", "Notes")
        )
        self.sheets = _tree(("Sheet or view", "Model", "Configuration"))
        self.models = _tree(("Model", "Stored path"))
        self.models.setTextElideMode(Qt.TextElideMode.ElideMiddle)

        asm = QSplitter(Qt.Orientation.Vertical)
        asm.addWidget(self.instances)
        asm.addWidget(self.files)
        asm.setStretchFactor(0, 3)
        asm.setStretchFactor(1, 2)
        drw = QSplitter(Qt.Orientation.Vertical)
        drw.addWidget(self.sheets)
        drw.addWidget(self.models)
        self.components_stack = QStackedWidget()
        self.components_stack.addWidget(asm)
        self.components_stack.addWidget(drw)

        self.components_widget = QWidget()
        cl = QVBoxLayout(self.components_widget)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addLayout(bar)
        cl.addWidget(self.components_stack, 1)

    def _build_bom(self) -> None:
        """The BOM tab: an assembly configuration's bill of materials, as SOLIDWORKS draws
        its BOM tables, in one of three types, with a button to export the one shown."""
        self.bom_section: dict[str, Any] | None = None
        self.bom_config = QComboBox()
        self.bom_config.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        # The configuration is the assembly's, as on the Components tab: a choice reads both again.
        self.bom_config.activated.connect(
            lambda i: self.configurationRequested.emit(self.bom_config.itemText(i))
        )
        self.bom_type = QComboBox()
        for t in BOM_TYPES:
            self.bom_type.addItem(BOM_TYPE_NAMES[t].capitalize(), t)
        self.bom_type.setCurrentIndex(BOM_TYPES.index("indented"))
        self.bom_type.activated.connect(lambda _i: self._show_bom())
        self.bom_counts = QLabel()
        self.bom_counts.setTextFormat(Qt.TextFormat.PlainText)
        self.bom_export = QPushButton("Export BOM...")
        self.bom_export.setToolTip(tip("Write this BOM, as shown, to a CSV or JSON file in a folder"))
        self.bom_export.clicked.connect(self.bomExportRequested)
        self.bom_edit = QPushButton("Edit BOM...")
        self.bom_edit.setToolTip(
            tip("Choose the columns, order and text of this BOM; save it, or export it to CSV, Excel or PDF")
        )
        self.bom_edit.clicked.connect(self.bomEditRequested)
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 4)
        bar.addWidget(QLabel("Configuration:"))
        bar.addWidget(self.bom_config)
        bar.addSpacing(12)
        bar.addWidget(QLabel("Type:"))
        bar.addWidget(self.bom_type)
        bar.addSpacing(12)
        bar.addWidget(self.bom_counts, 1)
        # the buttons on a row of their own, so the bar never widens the details panel
        buttons = QHBoxLayout()
        buttons.setContentsMargins(6, 0, 6, 4)
        buttons.addStretch(1)
        buttons.addWidget(self.bom_edit)
        buttons.addWidget(self.bom_export)
        self.bom_tree = _tree((*BOM_COLUMNS, "Total qty.", "Configuration", "Found", "Notes"))
        self.bom_tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        h = self.bom_tree.headerItem()
        h.setToolTip(1, tip("The document name, as SOLIDWORKS shows it by default"))
        h.setToolTip(2, tip("The component's Description property in the configuration the assembly uses"))
        h.setToolTip(3, tip("Instances in one of its parent assembly"))
        h.setToolTip(4, tip("Instances in the whole assembly"))
        self.bom_widget = QWidget()
        bl = QVBoxLayout(self.bom_widget)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addLayout(bar)
        bl.addLayout(buttons)
        bl.addWidget(self.bom_tree, 1)

    def _bom(self, data: dict[str, Any]) -> None:
        page = self.pages["BOM"]
        self.bom_section = None
        if data["kind"] != "assembly":
            what = {"part": "A part", "drawing": "A drawing"}.get(data["kind"], f"A {data['kind']}")
            page.message(
                f"{what} has no bill of materials of its own. Select an assembly to see its BOM, "
                "as SOLIDWORKS numbers it."
            )
            return
        self.bom_section = data
        comp = ((self.sections.get("components") or {}).get("data") or {}).get("components") or {}
        names = list(comp.get("configurations_described") or []) or [data["configuration"] or ""]
        self.bom_config.blockSignals(True)
        self.bom_config.clear()
        self.bom_config.addItems([n for n in names if n])
        if data["configuration"]:
            self.bom_config.setCurrentText(data["configuration"])
        self.bom_config.blockSignals(False)
        self._show_bom()
        page.show_content()

    def bom_shown(self) -> dict[str, Any] | None:
        """The ``bom`` data of the BOM the tab shows (its configuration and type), or None
        while there is none to export: no assembly, its BOM failed, or another
        configuration's is being read."""
        if self.bom_section is None:
            return None
        return self.bom_section["boms"].get(self.bom_type.currentData())

    def bom_reread(self, configuration: str) -> bool:
        """Before the BOM is read again for ``configuration``: forget the one shown, so
        that it cannot be exported as if it were the new one, and say so on the tab.
        False when the document has no BOM to read again (it is no assembly)."""
        section = self.sections.get("bom")
        if section is None or (section.get("ok") and (section.get("data") or {}).get("kind") != "assembly"):
            return False
        self.bom_section = None
        self.pages["BOM"].message(f"Reading configuration {configuration}...")
        return True

    def _show_bom(self) -> None:
        data = self.bom_shown()
        if data is None:
            return
        rows = data["rows"]
        cells = table_cells(data["type"], data["property_columns"], rows)[1:]
        c = data["counts"]
        text = f"{plural(c['rows'], 'row')}, {plural(c['instances'], 'instance')}"
        if c["unread"]:
            text += f"; {plural(c['unread'], 'file')} not read, see Notes"
        if data["truncated"]:
            text += "; stopped at a limit, quantities are lower bounds"
        if data["children_state"] == "unknown":
            text += "; the file stores no component tree for this configuration"
        self.bom_counts.setText(text)
        parents = self._instance_files(data["configuration"])
        t = self.bom_tree
        _reset(t)
        try:
            items = []
            for r, cell in zip(rows[:MAX_ROWS], cells, strict=False):
                notes = r["notes"]
                lines = [r["file_name"] or "file unknown"]
                if r["stored_path"]:
                    lines.append(r["stored_path"])
                lines += [n["message"] for n in notes]
                item = _make(
                    [
                        *cell[:4],
                        r["total_quantity"],
                        r["configuration"] or "",
                        self._bom_found(r),
                        ", ".join(n["code"].removeprefix("bom_").replace("_", " ") for n in notes),
                    ],
                    tip_text="\n".join(lines),
                )
                first = r["instances"][0] if r["instances"] else ""
                parent = parents.get(first.rpartition("/")[0]) if "/" in first else None
                _link(item, r["file"], f"bom:{r['item']}", parent, r["configuration"])
                for col in (3, 4):
                    item.setTextAlignment(col, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if notes:
                    tone = _tone(self, "orange")
                    if tone is not None:
                        item.setForeground(7, tone)
                items.append(item)
            if len(rows) > MAX_ROWS:
                items.append(_more(len(rows) - MAX_ROWS, "row", "rows"))
            t.addTopLevelItems(items)
            _fit(t, max_width=300)
        finally:
            _done(t)

    def _instance_files(self, configuration: str | None) -> dict[str, str]:
        """Each instance's file key by its component tree id, from the components section
        when it shows ``configuration``: a BOM row inside a sub-assembly names that
        sub-assembly's file for going to its own (a virtual part stored there)."""
        comp = ((self.sections.get("components") or {}).get("data") or {}).get("components") or {}
        if comp.get("configuration") != configuration:
            return {}
        out: dict[str, str] = {}
        stack = list(comp.get("children") or [])
        while stack:
            n = stack.pop()
            if n.get("id") and n.get("file"):
                out[n["id"]] = n["file"]
            stack.extend(n.get("children") or [])
        return out

    @staticmethod
    def _bom_found(r: dict[str, Any]) -> str:
        """Where a BOM row's properties were read: the file found, or the document stored
        inside an assembly; else why not."""
        loc = r.get("location")
        where = ""
        if loc:
            if loc["root"] is None:
                where = f"outside the folder: {loc['path']}"
            else:
                where = loc["path"] if loc["root"] == ROOT_ID else f"{loc['root']}: {loc['path']}"
        if r.get("nested"):
            return f"inside {where or 'this document'} ({' > '.join(r['nested'])})"
        if where or not r.get("resolution"):
            return where
        return reference_status(r["resolution"])

    # -- state -------------------------------------------------------------------------
    def clear(self, message: str) -> None:
        self.title.setText("No document selected")
        self.subtitle.setText("")
        self.note.setText("")
        self.note.hide()
        self._base_note = ""
        # The configuration the instance this part was opened from uses, and that assembly.
        self.used_configuration: str | None = None
        self.used_by = ""
        self.summary = None
        self.summary_json = None
        self.path = None
        self.size = None
        self.sections = {}
        self.bom_section = None
        self._rows_of: str | None = None  # the document whose instances and files the rows are
        self._picked_in = "instances"  # the tree whose current row the 3D view picked last
        self.geometry = self.geometry_error = None
        self.preview.reset(None)
        self.overview_image.set_image(None)
        for page in self.pages.values():
            page.message(message)
        self.set_model_file(False)

    def _header_tips(self, model_file: bool) -> None:
        """The tooltips of the trees' headers: what a double-click, Enter and the right-click
        menu do. For a model file, only a component that is a file of its own (an Alibre
        part) has a file to go to; an object inside the file shown has none."""
        for tree, what in (
            (self.instances, "a part's row"),
            (self.files, "a file"),
            (self.sheets, "a view"),
            (self.models, "a model"),
            (self.bom_tree, "a row"),
            (self.references, "a file"),
        ):
            if model_file and tree in (self.instances, self.files):
                text = (
                    "Click a row to pick it in the 3D view. A component that is a file of its own (an Alibre "
                    "part) goes to that file on a double-click or Enter, and its right-click menu has "
                    f"{opening.OPEN_TEXT}, {opening.show_text()}, {OPEN_TEXT} and {SHOW_TEXT}; an object "
                    "inside this file has no file to go to."
                )
            else:
                more = (
                    " A sub-assembly's row opens and closes on a double-click; select it and press Enter to "
                    "go to its file."
                    if tree is self.instances
                    else ""
                )
                text = (
                    f"Double-click {what} or press Enter to go to its file.{more} Right-click for "
                    f"{opening.OPEN_TEXT} (in its own program), {opening.show_text()}, {OPEN_TEXT} and "
                    f"{SHOW_TEXT}."
                )
            tree.headerItem().setToolTip(0, tip(text))

    def set_model_file(self, on: bool) -> None:
        """A 3D file of another format is shown (or not): the tabs that are a SOLIDWORKS
        document's own are hidden for it, and its 3D view reads it as one."""
        if on != self.model_file:
            self._header_tips(on)
        self.model_file = on
        self.preview.model_file = on
        for name in SOLIDWORKS_TABS:
            i = TABS.index(name)
            if self.tabs.isTabVisible(i) == on:
                self.tabs.setTabVisible(i, not on)
        if on and TABS[self.tabs.currentIndex()] in SOLIDWORKS_TABS:
            self.tabs.setCurrentIndex(TABS.index("Overview"))

    def _heading(
        self, entry: dict[str, Any], path: str | None, where: str | None = None, note: str | None = None
    ) -> None:
        folder, _, name = entry["path"].rpartition("/")
        self.title.setText(name)
        if where is None:
            where = f"in {folder}" if folder else "in the opened folder"
        self.where = where
        self.subtitle.setText(self.where)
        self._base_note = note or ""
        self._show_note()
        self.path = path
        self.size = (entry.get("file") or {}).get("size")

    def _show_note(self) -> None:
        """The note under the subtitle: where a document not in the list comes from, and
        which configuration the instance it was opened from uses."""
        lines = [self._base_note] if self._base_note else []
        used = self.used_configuration
        active = (self.summary or {}).get("active_configuration")
        if used and active and active != used:
            lines.append(
                f"Opened from an instance in {self.used_by or 'an assembly'} that uses this part's "
                f"configuration {used}. The file's active configuration is {active}: the preview and "
                f"the 3D view show {active}, as the file was saved, and the Overview and Properties "
                f"tabs mark {used}."
            )
        text = "\n".join(lines)
        self.note.setText(text)
        self.note.setVisible(bool(text))

    def set_used_configuration(self, configuration: str | None, used_by: str = "") -> None:
        """The part shown was opened from an instance (in ``used_by``) that uses its
        ``configuration``: the note says so, and the Overview and Properties tabs mark it."""
        self.used_configuration, self.used_by = configuration or None, used_by
        self._show_note()
        if self.summary is not None:
            self._overview(self.summary)
            self._properties(self.summary)

    def begin(
        self,
        entry: dict[str, Any],
        path: str | None = None,
        *,
        where: str | None = None,
        note: str | None = None,
    ) -> None:
        """A document is being read: its name, and "Reading..." on every tab. ``where``
        replaces the folder the subtitle names, and ``note`` is shown under it, for a
        document that is not a row of the list."""
        self.clear("Reading...")
        self._heading(entry, path, where, note)
        self.preview.reset(doc_type_of(entry), key=(path, entry["path"]))
        self.set_model_file(is_model(entry, path))

    def show_unread(self, entry: dict[str, Any], path: str | None = None) -> None:
        """An entry the listing did not read (a link, a placeholder, an error...): what the
        listing says about it, and nothing is opened."""
        self.clear("")
        self._heading(entry, path)
        self.set_model_file(entry.get("model") is not None or format_name(path or entry["path"]) is not None)
        text = unread_text(entry, path)
        for name, page in self.pages.items():
            if name != "Where Used":
                page.message(text, error=entry["status"] == "error")

    def open_failed(self, section: dict[str, Any]) -> None:
        text = "This document could not be read.\n\n" + error_message(
            section.get("error"), size=self.size, path=self.path
        )
        for name, page in self.pages.items():
            if name != "Where Used":
                page.message(text, error=True)

    def set_section(self, name: str, section: dict[str, Any]) -> None:
        self.sections[name] = section
        if name == "geometry":  # a model file's measures: part of the Overview, never in its place
            self._geometry(section)
            return
        tabs = [t for t, s in TAB_SECTIONS.items() if s == name]
        if name == "bom":
            self.bom_section = None  # until this section shows, there is no BOM to export
        if not section.get("ok"):
            text = "This part of the document could not be read.\n\n" + error_message(
                section.get("error"), path=self.path
            )
            for t in tabs:
                self.pages[t].message(text, error=True)
            return
        show = {
            "summary": self._summary,
            "preview": self._preview,
            "components": self._components,
            "bom": self._bom,
            "references": self._references,
            "paths": self._paths,
        }.get(name)
        if show is None:
            return
        try:
            show(section["data"])
        except Exception as exc:  # a value the panel did not expect: say so on its tabs, never crash
            text = (
                "This part of the document could not be shown.\n\n"
                f"Technical details: {type(exc).__name__}: {exc}"
            )
            for t in tabs:
                self.pages[t].message(text, error=True)

    # -- Overview, Properties, Raw JSON -------------------------------------------
    def _geometry(self, section: dict[str, Any]) -> None:
        """A model file's measures arrived (or could not be read): the Overview shows them."""
        if section.get("ok"):
            self.geometry, self.geometry_error = section["data"], None
        else:
            self.geometry, self.geometry_error = None, section.get("error") or {"code": "internal"}
            key = self.preview.document_key
            if unusable(self.geometry_error) and isinstance(key, tuple) and len(key) == 2:
                self.geometryFailed.emit(key[1], first_sentence(self.geometry_error, self.path))
        if self.summary is not None and self.model_file:
            self._overview(self.summary)

    def _summary(self, data: dict[str, Any]) -> None:
        if data.get("model"):
            self._model_summary(data)
            return
        s = self.summary = data["summary"]
        self.summary_json = data["json"]
        self.preview.set_doc_type(s["doc_type"])
        sv = s["saved_version"]
        type_text = DOC_TYPES.get(s["doc_type"] or "", "Unknown type")
        self.subtitle.setText(f"{type_text}, saved with {release_text(sv)}, {self.where}")
        self._show_note()
        self._overview(s)
        self._properties(s)
        text = data["json"]
        if len(text) > JSON_VIEW_CHARS:
            cut = text.rfind("\n", 0, JSON_VIEW_CHARS)
            cut = cut if cut > 0 else JSON_VIEW_CHARS
            text = (
                text[:cut] + f"\n\n... {len(data['json']) - cut:,} more characters not shown here. "
                "Edit > Copy Summary JSON copies all of it."
            )
        self.json.setPlainText(text)
        self.pages["Overview"].show_content()
        self.pages["Raw JSON"].show_content()

    def preview_png(self) -> bytes | None:
        """A model file's preview image as the Preview tab shows it (a PNG SolidSeas wrote:
        the one the file stores, or one drawn from its geometry), or None."""
        section = self.sections.get("preview") or {}
        data = section.get("data") if section.get("ok") else None
        image = (data or {}).get("image")
        return image if self.model_file and isinstance(image, bytes) else None

    def _model_summary(self, data: dict[str, Any]) -> None:
        """A model file's summary: the subtitle, Overview, Properties and Raw JSON."""
        s = self.summary = data["summary"]
        self.summary_json = data["json"]
        self.preview.set_doc_type(s.get("doc_type") or "part")
        detail = modeldetails.format_text(s)
        detail = "" if detail == s.get("format_name") else f" ({detail})"
        self.subtitle.setText(f"{modeldetails.type_text(s)}{detail}, {self.where}")
        self._show_note()
        self._overview(s)
        self._properties(s)
        self._json(data["json"])
        self.pages["Overview"].show_content()
        self.pages["Raw JSON"].show_content()

    def _json(self, text: str) -> None:
        if len(text) > JSON_VIEW_CHARS:
            cut = text.rfind("\n", 0, JSON_VIEW_CHARS)
            cut = cut if cut > 0 else JSON_VIEW_CHARS
            text = (
                text[:cut] + f"\n\n... {len(text) - cut:,} more characters not shown here. "
                "Edit > Copy Summary JSON copies all of it."
            )
        self.json.setPlainText(text)

    def _overview(self, s: dict[str, Any]) -> None:
        if self.model_file and s.get("format_name") is not None:
            modeldetails.overview(
                self.overview,
                s,
                self.geometry,
                self.geometry_error,
                used_configuration=self.used_configuration,
                path=self.path,
            )
            return
        t = self.overview
        _reset(t)
        sv, f = s["saved_version"], s["file"]
        doc = _item(t, ["Document"], bold=True)
        source = {"definition": "from the stored type", "extension": "from the file extension"}.get(
            s["doc_type_source"], "not stored"
        )
        _item(doc, ["Type", f"{DOC_TYPES.get(s['doc_type'] or '', 'unknown')} ({source})"])
        _item(
            doc, ["Container", "2015 and later" if s["format"] == "modern" else "legacy (OLE compound file)"]
        )
        release = release_text(sv)
        if sv.get("release") and not sv.get("release_verified"):
            release += " (release estimated from the format version)"
        _item(doc, ["Saved with", release])
        _item(doc, ["Format version", sv.get("format_version")])
        if sv.get("last_build") is not None:
            _item(doc, ["Last build", f"{sv['last_build']} ({sv.get('last_build_date') or 'date unknown'})"])
        _item(doc, ["Saved as previous version", "yes" if sv.get("save_as_previous") else "no"])

        file = _item(t, ["File"], bold=True)
        _item(file, ["Name", f["name"]])
        if f.get("size") is not None:
            _item(file, ["Size", f"{size_text(f['size'])} ({f['size']:,} bytes)"])
        _item(file, ["Modified", time_text(f.get("modified_utc"))])

        configs = s.get("configurations") or []
        cfg = _item(t, [f"Configurations ({len(configs):,})"], bold=True)
        active = s["active_configuration"]
        if not active and s["doc_type"] == "drawing":
            active = "none stored (drawings have no configurations)"
        elif not active:
            active = "none stored"
        _item(cfg, ["Active", active])
        used = self.used_configuration
        if used:
            _item(cfg, ["Used by the instance", f"{used} (in {self.used_by})" if self.used_by else used])
        rows = []
        for c in configs[:MAX_ROWS]:
            flags = [
                w
                for w, on in (
                    ("active", c["active"]),
                    ("most recent", c["most_recent"]),
                    ("used by the instance you opened it from", bool(used) and c["name"] == used),
                )
                if on
            ]
            extra = []
            if c.get("material"):
                extra.append(f"material {c['material']['name']}")
            if c.get("properties"):
                extra.append(plural(len(c["properties"]), "property", "properties") + " of its own")
            if c.get("comment"):
                extra.append(f"comment: {c['comment']}")
            label = c["name"] + (f" ({', '.join(flags)})" if flags else "")
            rows.append(_make([label, "; ".join(extra)]))
        if len(configs) > MAX_ROWS:
            rows.append(_more(len(configs) - MAX_ROWS, "configuration", "configurations"))
        cfg.addChildren(rows)

        other = _item(t, ["Material and units"], bold=True)
        m = s.get("material")
        _item(
            other,
            ["Material", f"{m['name']} ({m['database'] or 'database not stored'})" if m else "none assigned"],
        )
        u = s.get("units")
        if u:
            dp = u.get("length_decimal_places")
            units = f"{u['system']}: length {u['length']}, mass {u['mass']}, angle {u['angle']}"
            if dp is not None:
                units += f", {dp} decimal places"
            _item(other, ["Units", units])
        else:
            _item(other, ["Units", "not stored"])

        fields = {k: v for k, v in s["fields"].items() if v not in (None, "")}
        fl = _item(t, [f"Summary fields ({len(fields)})"], bold=True)
        names = {"last_saved_by": "Last saved by", "created_utc": "Created", "last_saved_utc": "Last saved"}
        for k, v in fields.items():
            _item(fl, [names.get(k, k.capitalize()), time_text(v) if k.endswith("_utc") else v])

        c = s["counts"]
        pv = s["preview"]
        cnt = _item(t, ["Contents"], bold=True)
        _item(cnt, ["Streams", c["streams"]])
        _item(cnt, ["Custom properties", c["custom_properties"]])
        if c["references"] is not None:
            _item(cnt, ["Referenced files", c["references"]])
        _item(cnt, ["Nested documents", c["nested_documents"]])
        _item(cnt, ["Parasolid partitions", c["parasolid_partitions"]])
        if pv["available"]:
            _item(cnt, ["Preview", f"{pv['width']} x {pv['height']} {pv['mime']} ({pv['stream']})"])
        else:
            _item(
                cnt, ["Preview", "none stored" if pv["reason"] == "not_stored" else f"none ({pv['reason']})"]
            )

        warnings = s.get("warnings") or []
        wl = _item(
            t, [f"Warnings ({len(warnings):,})"], bold=True, color=_tone(t, "orange") if warnings else None
        )
        rows = [
            _make([w["code"], w["message"]], tip_text=w.get("stream") or None) for w in warnings[:MAX_ROWS]
        ]
        if len(warnings) > MAX_ROWS:
            rows.append(_more(len(warnings) - MAX_ROWS, "warning", "warnings", "; see Raw JSON"))
        if not warnings:
            rows.append(_make(["none", ""]))
        wl.addChildren(rows)
        t.expandAll()
        t.resizeColumnToContents(0)
        t.setColumnWidth(0, max(t.columnWidth(0) + 12, 200))
        _done(t)

    def _properties(self, s: dict[str, Any]) -> None:
        t = self.properties
        _reset(t)
        try:
            groups = [("File properties", s.get("properties") or [])]
            used = self.used_configuration
            for c in s.get("configurations") or []:
                flags = ["active"] if c["active"] else []
                if used and c["name"] == used:
                    flags.append("used by the instance")
                label = f"Configuration {c['name']}" + (f" ({', '.join(flags)})" if flags else "")
                groups.append((label, c.get("properties") or []))
            if not any(props for _, props in groups):
                what = "file" if self.model_file else "document"
                self.pages["Properties"].message(f"No custom properties are stored in this {what}.")
                return
            everything = "; Raw JSON and Copy Summary JSON have all"
            left = MAX_ROWS
            tops = []
            for i, (label, props) in enumerate(groups):
                if not props:
                    continue
                if left <= 0:
                    hidden = sum(len(p) for _, p in groups[i:])
                    tops.append(_more(hidden, "property", "properties", everything))
                    break
                g = _make([f"{label} ({len(props):,})"], bold=True)
                rows = []
                for p in props[:left]:
                    rows.append(
                        _make(
                            [
                                p["name"],
                                _value_text(p),
                                p["type"],
                                p.get("expression") or "",
                                "yes" if is_computed(p) else "",
                            ],
                            tip_text=f"stored text: {p['text']}" if p.get("text") is not None else None,
                        )
                    )
                if len(props) > left:
                    rows.append(_more(len(props) - left, "property", "properties", everything))
                left -= min(left, len(props))
                g.addChildren(rows)
                tops.append(g)
            t.addTopLevelItems(tops)
            t.expandAll()
            _fit(t)
        finally:
            _done(t)
        self.pages["Properties"].show_content()

    # -- Preview -------------------------------------------------------------------
    def _preview(self, data: dict[str, Any]) -> None:
        page = self.pages["Preview"]
        self.overview_image.set_image(None)
        if data.get("image") is None:
            text = "No preview stored: this document was saved without a preview image."
            if self.model_file:
                text = "No preview: the file stores no image, and none could be drawn from its geometry."
                if data.get("detail"):
                    text += f" ({data['detail']})"
            if self.preview.has_3d:  # the 3D view may still have something to show
                self.preview.set_no_image(text)
                page.show_content()
            else:
                page.message(text)
            return
        if "qimage" in data:  # decoded and scaled in the worker by the window
            pix = QPixmap.fromImage(data["qimage"])
        else:
            pix = QPixmap()
            pix.loadFromData(data["image"])
        if pix.isNull():
            page.message("The stored preview image could not be shown.", error=True)
            return
        caption = (
            f"{data['width']} x {data['height']} {data['mime']}, {size_text(len(data['image']))}, "
            f"from the stream {data['stream']}"
        )
        if data.get("source") == "rendered":
            caption = (
                f"{data['width']} x {data['height']}, drawn by SolidSeas from the model's geometry, as the "
                "file stores no image"
            )
            if data.get("partial"):
                caption += " (partly: a limit stopped it before every triangle was drawn)"
        elif data.get("source") == "stored":
            caption = (
                f"{data['width']} x {data['height']}, the image the file stores"
                + (f" ({data['stream']})" if data.get("stream") else "")
                + ", as a PNG SolidSeas wrote"
            )
        self.preview.set_image(pix, source_width=data.get("width") or pix.width(), caption=caption)
        self.overview_image.set_image(pix, self.title.text())
        page.show_content()

    def show_preview_image(self) -> None:
        """The Overview's image was clicked: the Preview tab, showing the image, not the 3D view."""
        self.preview.show_image_once()
        self.tabs.setCurrentIndex(TABS.index("Preview"))
        self.preview.image.setFocus(Qt.FocusReason.OtherFocusReason)

    def set_3d_enabled(self, on: bool) -> None:
        """Settings > Interactive 3D View, applied to the document on show."""
        self.preview.set_3d_enabled(on)
        section = self.sections.get("preview")
        if section is not None and section.get("ok"):
            self._preview(section["data"])

    # -- Components ------------------------------------------------------------------
    def _components(self, data: dict[str, Any]) -> None:
        page = self.pages["Components"]
        kind = data["kind"]
        if data.get("message"):  # a model file that is not an assembly
            page.message(data["message"])
            return
        if kind == "assembly":
            # The same document in another configuration keeps its picked rows where it has them.
            kept = {}
            if self._rows_of is not None and self._rows_of == self.path:
                # Read from the trees: the tab shows "Reading configuration..." meanwhile.
                for name in sorted(("instances", "files"), key=lambda n: n == self._picked_in):
                    item = self.linked_trees[name].currentItem()
                    if item is not None and item.data(0, IDENT_ROLE):
                        kept[name] = item.data(0, IDENT_ROLE)
            self._assembly(data["components"])
            self._rows_of = self.path
            page.show_content()
            self._show_looks()  # what the 3D view hides or shows through, on the new rows
            if kept:
                self.restore_selection(kept)
            return
        if kind == "drawing":
            self._drawing(data["references"])
        else:
            page.message(
                f"A {kind} has no components. Assemblies list their instances here, drawings their sheets."
            )
            return
        page.show_content()

    def _assembly(self, c: dict[str, Any]) -> None:
        for tree in (self.sheets, self.models):  # an earlier drawing's rows
            tree.clear()
        self.components_stack.setCurrentIndex(0)
        configured = bool(c["configurations_described"] or c["configuration"])  # a model file has none
        self.config_label.setVisible(configured)
        self.config_combo.setVisible(configured)
        self.config_combo.blockSignals(True)
        self.config_combo.clear()
        self.config_combo.addItems(
            c["configurations_described"] or ([c["configuration"]] if c["configuration"] else [])
        )
        if c["configuration"]:
            self.config_combo.setCurrentText(c["configuration"])
        self.config_combo.blockSignals(False)
        self.preview.set_configurations(
            [self.config_combo.itemText(i) for i in range(self.config_combo.count())], c["configuration"]
        )
        counts = c["counts"]
        internal = sum(1 for f in c["files"] if is_internal(f.get("key")))
        text = f"{plural(counts['nodes'], 'instance')} of {files_text(counts['files'], internal)}"
        text += f", {plural(counts['depth'], 'level')}"
        if c["configuration_source"] not in ("active", "requested", "none"):
            text += f" (configuration chosen: {c['configuration_source'].replace('_', ' ')})"
        if c["truncated"]:
            text += "; stopped at a limit, counts are lower bounds"
        if c["children_state"] == "unknown":
            text += "; the file stores no component tree for this configuration"
        if c["warnings"]:
            text += f"; {plural(len(c['warnings']), 'warning')}"
        self.components_counts.setText(text)

        files = {f["key"]: f for f in c["files"]}
        disabled = self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        t = self.instances
        _reset(t)
        try:
            tops: list[QTreeWidgetItem] = []
            shown = 0
            stack = [(None, n, False, None) for n in reversed(c["children"] or [])]
            while stack and shown < MAX_ROWS:
                parent, n, parent_suppressed, parent_file = stack.pop()
                f = files.get(n["file"]) or {}
                pl = n.get("placement") or {}
                pos = pl.get("translation_m") or [None, None, None]
                local = (n.get("transform") or {}).get("translation_m")
                if is_internal(n["file"]):
                    lines = [f"inside this file: {f.get('file_name') or n['name']}"]
                else:
                    lines = [f.get("file_name") or "file unknown"]
                if f.get("stored_path"):
                    lines.append(f["stored_path"])
                if local:
                    relative = ", ".join(mm(v) for v in local)
                    lines.append(f"position relative to its parent: {relative} mm")
                if n["children_state"] in ("truncated", "cycle", "unknown"):
                    lines.append(f"children: {n['children_state']}")
                if parent_suppressed and not n["suppressed"]:
                    lines.append("inside a suppressed sub-assembly, so suppressed too")
                suppressed = n["suppressed"] or parent_suppressed
                item = _make(
                    [
                        n["name"],
                        n["configuration"] or "",
                        _state(n, parent_suppressed=parent_suppressed),
                        mm(pos[0]),
                        mm(pos[1]),
                        mm(pos[2]),
                        rotation_text(pl.get("rotation")),
                    ],
                    color=disabled if suppressed else None,
                    tip_text="\n".join(lines),
                )
                _link(item, n["file"], n.get("id") or n["name"], parent_file, n["configuration"])
                item.setData(0, GREY_ROLE, bool(suppressed))
                shown += 1
                for col in (3, 4, 5):
                    item.setTextAlignment(col, right)
                if n["hidden"]:
                    font = QFont(item.font(0))
                    font.setItalic(True)
                    item.setFont(0, font)
                if parent is None:
                    tops.append(item)
                else:
                    parent.addChild(item)
                stack.extend((item, ch, suppressed, n["file"]) for ch in reversed(n["children"] or []))
            if stack:
                more = max(counts["nodes"] - shown, len(stack))
                tops.append(_more(more, "instance", "instances", "; the Files table counts them all"))
            t.addTopLevelItems(tops)
            if shown <= 500:
                t.expandAll()
            else:
                t.expandToDepth(0)
            _fit(t, max_width=240)
            t.setColumnWidth(2, max(t.columnWidth(2), 120))  # State: room for "suppressed, hidden"
        finally:
            _done(t)

        ft = self.files
        _reset(ft)
        try:
            rows = []
            for f in c["files"][:MAX_ROWS]:
                notes = []
                if f["virtual"]:
                    notes.append("virtual")
                if f["imported"]:
                    notes.append("imported")
                if f["embedded"]:
                    notes.append(f["embedded"].replace("_", " "))
                if f["direct"] is False:
                    notes.append("only inside sub-assemblies")
                item = _make(
                    [
                        f["file_name"] or f["stored_path"],
                        DOC_TYPES.get(f["doc_type"] or "", ""),
                        f["instances"],
                        f["instances_unsuppressed"],
                        f["instances_in_bom"],
                        ", ".join(f["configurations_used"]),
                        ", ".join(notes),
                    ],
                    tip_text=f["stored_path"],
                )
                _link(item, f["key"], f["key"])
                for col in (2, 3, 4):
                    item.setTextAlignment(col, right)
                rows.append(item)
            if len(c["files"]) > MAX_ROWS:
                rows.append(_more(len(c["files"]) - MAX_ROWS, "file", "files"))
            ft.addTopLevelItems(rows)
            _fit(ft, max_width=260)
        finally:
            _done(ft)
        self.preview.set_components(*component_files(c))

    def _drawing(self, r: dict[str, Any]) -> None:
        for tree in (self.instances, self.files):  # an earlier assembly's rows
            tree.clear()
        self.components_stack.setCurrentIndex(1)
        self.config_label.setVisible(False)
        self.config_combo.setVisible(False)
        sheets = r.get("sheets") or []
        views = sum(len(s["views"]) for s in sheets)
        self.components_counts.setText(
            f"{plural(len(sheets), 'sheet')}, {plural(views, 'view')}, "
            f"{plural(len(r['files']), 'referenced model')}"
        )
        files = {f["key"]: f for f in r["files"]}
        t = self.sheets
        _reset(t)
        try:
            tops = []
            shown = 0
            for si, s in enumerate(sheets):
                if shown >= MAX_ROWS:
                    tops.append(_more(len(sheets) - len(tops), "sheet", "sheets"))
                    break
                sheet = _make([f"{s['name']} ({plural(len(s['views']), 'view')})", "", ""], bold=True)
                rows = []
                for vi, v in enumerate(s["views"][: MAX_ROWS - shown]):
                    # The view stores the model's name in lower case; its file entry has the real name.
                    model = (files.get(v.get("file")) or {}).get("file_name") or v["file_name"] or ""
                    row = _make([v["name"], model, v["configuration"] or ""])
                    _link(row, v.get("file"), f"{si}/{vi}")
                    row.setData(0, VIEW_CONFIG_ROLE, v["configuration"] or "")
                    rows.append(row)
                shown += 1 + len(rows)
                if len(s["views"]) > len(rows):
                    rows.append(_more(len(s["views"]) - len(rows), "view", "views"))
                sheet.addChildren(rows)
                tops.append(sheet)
            t.addTopLevelItems(tops)
            t.expandAll()
            _fit(t)
        finally:
            _done(t)
        m = self.models
        _reset(m)
        try:
            rows = []
            for f in r["files"][:MAX_ROWS]:
                row = _make([f["file_name"] or "", f["stored_path"] or ""], tip_text=f["stored_path"])
                _link(row, f["key"], f["key"])
                rows.append(row)
            if len(r["files"]) > MAX_ROWS:
                rows.append(_more(len(r["files"]) - MAX_ROWS, "model", "models"))
            m.addTopLevelItems(rows)
            _fit(m, max_width=300)
        finally:
            _done(m)

    # -- References ------------------------------------------------------------------
    def _references(self, data: dict[str, Any]) -> None:
        page = self.pages["References"]
        if data.get("message"):  # a model file that names no other file
            page.message(data["message"])
            return
        if data["kind"] not in ("assembly", "drawing"):
            page.message(f"A {data['kind']} references no other files.")
            return
        r = data["references"]
        res = r.get("resolution") or {}
        counts = ", ".join(f"{v:,} {reference_status(k)}" for k, v in (res.get("counts") or {}).items() if v)
        where = "the opened folder and its subfolders"
        if data.get("model"):
            where = "the assembly's folder and its subfolders, by each file's document GUID"
        if res.get("outside_roots"):
            where += ", and stored paths on local drives outside it"
        files = plural(len(r["files"]), "referenced file")
        text = f"{files}" + (f": {counts}." if counts else ".") + f" Searched {where}."
        if res.get("index_partial"):
            text += " A limit cut the folder index short, so a missing file may still exist."
        self.ref_summary.setText(text)
        disabled = self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
        t = self.references
        _reset(t)
        try:
            rows = []
            for f in r["files"][:MAX_ROWS]:
                rr = f.get("resolution") or {}
                status = rr.get("status")
                notes = [w["code"].replace("_", " ") for w in rr.get("warnings") or []]
                if f["direct"] is False:
                    notes.insert(0, "inside a sub-assembly")
                item = _make(
                    [
                        f["file_name"] or f["key"],
                        reference_status(status),
                        self._found_at(rr),
                        rule_text(rr.get("rule")),
                        rr.get("confidence") or "",
                        rr.get("identity") or "",
                        f["stored_path"] or "",
                        ", ".join(notes),
                    ]
                )
                _link(item, f["key"], f["key"])
                item.setToolTip(6, tip(f["stored_path"]))
                if rr.get("warnings"):
                    item.setToolTip(7, tip("\n".join(w["message"] for w in rr["warnings"])))
                if rr.get("rule"):
                    item.setToolTip(3, tip(f"rule: {rr['rule']}"))
                tone = _tone(self, _STATUS_TONE.get(status or ""))
                if tone is not None:
                    item.setForeground(1, tone)
                cands = []
                for cand in rr.get("candidates") or []:
                    loc = (
                        cand["path"]
                        if cand["root"] is None
                        else (cand["path"] if cand["root"] == ROOT_ID else f"{cand['root']}: {cand['path']}")
                    )
                    cands.append(
                        _make(
                            [
                                "candidate",
                                "",
                                loc,
                                rule_text(cand["found_by"]),
                                "",
                                cand["identity"] or "",
                                "",
                                "cloud placeholder, not read" if cand["placeholder"] else "",
                            ],
                            color=disabled,
                            tip_text=loc,
                        )
                    )
                item.addChildren(cands)
                rows.append(item)
            if len(r["files"]) > MAX_ROWS:
                rows.append(_more(len(r["files"]) - MAX_ROWS, "referenced file", "referenced files"))
            t.addTopLevelItems(rows)
            t.expandAll()
            _fit(t, max_width=300)
        finally:
            _done(t)
        page.show_content()

    @staticmethod
    def _found_at(rr: dict[str, Any]) -> str:
        if rr.get("nested"):
            return f"inside this document ({rr['nested']})"
        m = rr.get("match")
        if not m:
            return ""
        if m["root"] is None:
            return f"outside the folder: {m['path']}"
        return m["path"] if m["root"] == ROOT_ID else f"{m['root']}: {m['path']}"

    # -- Paths -------------------------------------------------------------------------
    def _paths(self, d: dict[str, Any]) -> None:
        page = self.pages["Paths"]
        c = d["counts"]
        docs = c["documents"]
        if d["complete"]:
            head = f"Complete: {plural(docs, 'document')} read, nested documents included."
        else:
            reasons = ", ".join(sorted({i["reason"].replace("_", " ") for i in d["incomplete"]}))
            head = f"Incomplete ({reasons}): what follows is a lower bound."
        cats = ", ".join(f"{_CATEGORIES.get(k, k).lower()} {v:,}" for k, v in c["by_category"].items() if v)
        accounts = len(d["accounts"])
        self.paths_summary.setText(
            f"{head} {plural(c['paths'], 'path')}{': ' + cats if cats else ''}. "
            f"{plural(accounts, 'user name')}"
            + (f", {plural(len(d['hosts']), 'network server')}." if d["hosts"] else ".")
        )
        self.paths_note.setText(d["rewrite"]["note"])
        t = self.paths
        _reset(t)
        try:
            tops: list[QTreeWidgetItem] = []
            left = MAX_ROWS

            def group(label: str, items: list[Any], build, what: str, many: str) -> QTreeWidgetItem:
                nonlocal left
                g = _make([label], bold=True)
                rows = [build(x) for x in items[: max(left, 0)]]
                left -= len(rows)
                if len(items) > len(rows):
                    rows.append(
                        _more(len(items) - len(rows), what, many, "; see Raw JSON or solidseas paths")
                    )
                g.addChildren(rows)
                tops.append(g)
                return g

            def account(a: dict[str, Any]) -> QTreeWidgetItem:
                note = (
                    "only in the save history, probably a template's author" if a["inherited_likely"] else ""
                )
                item = _make(
                    [
                        a["name"],
                        a["severity"],
                        "named in: " + ", ".join(name_source(s) for s in a["sources"]),
                        "",
                        note or plural(a["paths"], "path"),
                    ]
                )
                tone = _tone(self, _SEVERITY_TONE.get(a["severity"]))
                if tone is not None:
                    item.setForeground(1, tone)
                return item

            def host(h: dict[str, Any]) -> QTreeWidgetItem:
                return _make(
                    [
                        h["host"],
                        h["severity"],
                        "shares: " + (", ".join(h["shares"]) or "-"),
                        "",
                        plural(h["paths"], "path"),
                    ]
                )

            def identity(f: dict[str, Any]) -> QTreeWidgetItem:
                where = stream_text(f["stream"])
                if f["nested"]:
                    where += " in " + " > ".join(f["nested"])
                raw = (f["stream"] or "") + (" in " + " > ".join(f["nested"]) if f["nested"] else "")
                item = _make(
                    [
                        f["value"],
                        "",
                        field_text(f["field"]) + ("" if f["current"] else ", an earlier save"),
                        "",
                        where,
                    ]
                )
                item.setToolTip(4, tip(f"stream: {raw}" if raw else ""))
                return item

            def found(p: dict[str, Any]) -> QTreeWidgetItem:
                streams = sorted({stream_text(loc["stream"]) for loc in p["locations"]})
                raw = sorted({loc["stream"] or "-" for loc in p["locations"]})
                nested = sorted({" > ".join(loc["nested"]) for loc in p["locations"] if loc["nested"]})
                where = ", ".join(streams) + (f"; nested: {'; '.join(nested)}" if nested else "")
                why = ", ".join(role_text(r) for r in p["roles"])
                if p["inherited_likely"]:
                    why += " (probably from a template)"
                item = _make([p["path"], p["severity"], why, p["account"] or p["host"] or "", where])
                item.setToolTip(0, tip(p["path"]))
                item.setToolTip(4, tip("streams: " + ", ".join(raw)))
                tone = _tone(self, _SEVERITY_TONE.get(p["severity"]))
                if tone is not None:
                    item.setForeground(1, tone)
                return item

            if d["accounts"]:
                group(f"User names ({accounts:,})", d["accounts"], account, "user name", "user names")
            if d["hosts"]:
                group(f"Servers ({len(d['hosts']):,})", d["hosts"], host, "server", "servers")
            if d["identity_fields"]:
                group(
                    f"Names stored in the file ({len(d['identity_fields']):,})",
                    d["identity_fields"],
                    identity,
                    "name",
                    "names",
                )
            by_category: dict[str, list[dict[str, Any]]] = {}
            for p in d["paths"]:
                by_category.setdefault(p["category"], []).append(p)
            for category, paths in by_category.items():
                label = _CATEGORIES.get(category, category)
                group(
                    f"{label} ({c['by_category'].get(category, len(paths)):,})", paths, found, "path", "paths"
                )
            t.addTopLevelItems(tops)
            t.expandAll()
            _fit(t, max_width=380)
            t.setColumnWidth(2, min(t.columnWidth(2), 220))
        finally:
            _done(t)
        if not d["paths"] and not d["accounts"] and not d["identity_fields"]:
            page.message("This document stores no paths or user names.")
            return
        page.show_content()

    # -- going to a referenced file ----------------------------------------------------
    def target(self, key: str) -> navigate.Target:
        """Where the referenced file ``key`` is, from the references section; ``pending``
        while that section has not arrived. Something inside a model file itself (an
        object, a grouping) is no file to go to."""
        if is_internal(key):
            return navigate.Target(
                navigate.UNKNOWN,
                key,
                self._internal_name(key),
                why="It is a part of this file, not a file of its own.",
            )
        section = self.sections.get("references")
        if section is None:
            comp = (self.sections.get("components") or {}).get("data") or {}
            files = (comp.get("components") or comp.get("references") or {}).get("files") or []
            file = next((f for f in files if f.get("key") == key), None)
            return navigate.target(file and {**file, "resolution": None}, key=key, pending=True)
        if not section.get("ok"):
            return navigate.Target(
                navigate.UNKNOWN,
                key,
                key,
                why="The references of this document could not be read.\n\n"
                + error_message(section.get("error"), path=self.path),
            )
        refs = section["data"].get("references") or {}
        files = {f["key"]: f for f in refs.get("files") or []}
        outside = (refs.get("resolution") or {}).get("outside_roots", True)
        model = bool(section["data"].get("model"))
        return navigate.target(files.get(key), key=key, outside_roots=bool(outside), model=model)

    def _internal_name(self, key: str) -> str:
        comp = ((self.sections.get("components") or {}).get("data") or {}).get("components") or {}
        for f in comp.get("files") or []:
            if f.get("key") == key:
                return f.get("file_name") or key
        return key

    def request(self, item: QTreeWidgetItem, mode: str = OPEN) -> bool:
        """Ask the window to go to the file ``item`` stands for, as a double-click
        (:data:`OPEN`) or Show in folder list (:data:`SHOW`) does; False for a row that
        stands for none, or for something inside the file shown."""
        key = item.data(0, KEY_ROLE)
        if not key or is_internal(key):
            return False
        parent, configuration = item.data(0, PARENT_ROLE) or "", item.data(0, CONFIG_ROLE) or ""
        self.componentRequested.emit(key, mode, parent, configuration)
        return True

    def _double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        tree = item.treeWidget()
        if item.childCount() and tree is not None and tree.expandsOnDoubleClick():
            return  # the tree opens or closes the row: a sub-assembly is explored, not left
        self.request(item, OPEN)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Enter on a row of a linked tree goes to its file, a sub-assembly's too."""
        if (
            event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and watched in self.linked_trees.values()
        ):
            item = watched.currentItem()  # type: ignore[attr-defined]
            if item is not None and self.request(item, OPEN):
                return True
        return super().eventFilter(watched, event)

    def component_menu(self, item: QTreeWidgetItem) -> QMenu | None:
        """The context menu of a row that stands for a referenced file: Open and Show in File
        Explorer, Go to file and Show in folder list (:meth:`_link_menu`), each off with the
        reason when it cannot be done, then
        3D Print for a part or an assembly, in the row's configuration: an instance's or
        a BOM row's, the one a drawing view shows, and for a row of a file (the Files
        table, a drawing's models, the References tab) the one configuration it is used
        in, else the active one. With an assembly's 3D view on, a row of the instances
        adds how that instance (or every part of a sub-assembly) looks there and, for a
        sub-assembly, whether it explodes, and a row of the files how every instance of
        that file looks (:meth:`.preview.PreviewPane.add_instance_actions`)."""
        key = item.data(0, KEY_ROLE)
        if not key:
            return None
        parent, configuration = item.data(0, PARENT_ROLE) or "", item.data(0, CONFIG_ROLE) or ""
        menu = self._link_menu(key, parent, configuration)
        tree, pane = item.treeWidget(), self.preview
        if tree in (self.files, self.models, self.references):
            configuration = self.only_configuration(key)
        elif tree is self.sheets:
            configuration = item.data(0, VIEW_CONFIG_ROLE) or ""
        self.add_print(menu, key, parent, configuration)
        if pane.styles_3d and tree is self.instances:
            ident = item.data(0, IDENT_ROLE)
            sub = item.childCount() > 0 or pane.is_subassembly(ident)
            pane.add_instance_actions(menu, ident, path=False, subassembly=sub)
        elif pane.styles_3d and tree is self.files:
            pane.add_file_actions(menu, key)
        return menu

    def _file_link_menu(self, key: str) -> QMenu | None:
        """Open, Show in File Explorer, Go to file, Show in folder list and 3D Print for
        the file ``key`` of the assembly's Files table, for the 3D view's legend; None for
        a file the table does not list."""
        section = self.sections.get("components") or {}
        files = ((section.get("data") or {}).get("components") or {}).get("files") or []
        if not section.get("ok") or not any(f.get("key") == key for f in files):
            return None
        menu = self._link_menu(key, "", "")
        self.add_print(menu, key, "", self.only_configuration(key))
        return menu

    def only_configuration(self, key: str) -> str:
        """The configuration the file ``key`` is used in, when it is used in one: every
        instance of it in an assembly, or every view of it in a drawing (the files of the
        components section, or of the references section); else "" (its active one)."""
        lists = []
        for name, kind in (
            ("components", "components"),  # an assembly, in the configuration shown
            ("components", "references"),  # a drawing
            ("references", "references"),
        ):
            section = self.sections.get(name) or {}
            data = section.get("data") if section.get("ok") else None
            lists.append(((data or {}).get(kind) or {}).get("files") or [])
        for files in lists:
            for f in files:
                if f.get("key") == key and "configurations_used" in f:
                    used = f.get("configurations_used") or []
                    return used[0] if len(used) == 1 and used[0] else ""
        return ""

    def parent_of(self, key: str) -> str:
        """The file key of the sub-assembly an instance of the file ``key`` is in, from the
        components section; "" for a file used at the top, or not found."""
        section = self.sections.get("components") or {}
        data = (section.get("data") or {}).get("components") if section.get("ok") else None
        stack = [(n, "") for n in (data or {}).get("children") or []]
        seen = 0
        while stack and seen < 1_000_000:
            n, parent_file = stack.pop()
            seen += 1
            if n.get("file") == key:
                return parent_file
            stack.extend((c, n.get("file") or "") for c in n.get("children") or [])
        return ""

    def add_print(
        self,
        menu: QMenu,
        key: str,
        parent: str,
        configuration: str,
        *,
        kind: bool = False,
        first: bool = True,
    ) -> bool:
        """Add the window's 3D Print entry (:attr:`print_item`) for the file ``key`` to
        ``menu`` (after a separator when it is the ``first``), when that file is a part or
        an assembly: "3D Print" and its name, or with ``kind`` "3D Print Part" or "3D
        Print Sub-assembly" and its name, as the 3D view's menu says it. Whether one was
        added."""
        if self.print_item is None:
            return False
        t = self.target(key)
        if t.doc_type not in ("part", "assembly"):
            return False
        word = ("Part " if t.doc_type == "part" else "Sub-assembly ") if kind else ""
        if first:
            menu.addSeparator()
        self.print_item(menu, f"3D Print {word}{t.name}", key, parent, configuration)
        return True

    def add_path_prints(self, menu: QMenu, ident: str) -> int:
        """The 3D view's 3D Print entries for the instance ``ident``: its part, in the
        configuration the instance uses, then each sub-assembly it is in, nearest first,
        each in the configuration it is used in. The part is found from its row on the
        Components tab, or for one the 3D view read from a sub-assembly's own file, which
        has no row, from the document the view drew it from
        (:attr:`.preview.PreviewPane.instance_documents`); one it drew from what its
        sub-assembly stores of it, its own file not found, has the entry off with the
        reason (:attr:`.preview.PreviewPane.instance_missing`). How many were added."""
        added = 0
        for probe in (ident, *subassemblies(ident)[::-1]):
            link = self.instance_link(probe)
            if link is None:
                document = self.preview.instance_documents.get(probe) if probe == ident else None
                missing = self.preview.instance_missing.get(probe) if probe == ident else None
                if document is not None and self.print_document is not None:
                    if not added:
                        menu.addSeparator()
                    self.print_document(menu, f"3D Print Part {document['name']}", document)
                    added += 1
                elif missing is not None and self.print_missing is not None:
                    if not added:
                        menu.addSeparator()
                    self.print_missing(menu, f"3D Print Part {missing['name']}", missing)
                    added += 1
                continue
            key, parent, configuration = link
            if self.add_print(menu, key, parent, configuration, kind=True, first=not added):
                added += 1
        return added

    def _link_menu(self, key: str, parent: str, configuration: str) -> QMenu:
        """Open and Show in File Explorer (:mod:`.opening`), then Go to file (what a
        double-click does, in bold) and Show in folder list, for the file ``key``; each is
        off, with the reason, when it cannot be done. None of them for something inside
        the file shown, which has no file of its own."""
        menu = relay_status_tips(QMenu(self))
        menu.setToolTipsVisible(True)  # the 3D Print entry's says the configuration and where it goes
        if is_internal(key):  # inside the file shown: nothing to open, only how it looks
            return menu
        t = self.target(key)
        why = {
            navigate.NESTED: "stored inside the document",
            navigate.MISSING: "not found",
            navigate.UNKNOWN: "not resolved",
        }.get(t.kind)
        for text, mode, tip_text in (
            (opening.OPEN_TEXT, PROGRAM, opening.OPEN_TIP),
            (opening.show_text(), REVEAL, opening.show_tip()),
        ):
            action = menu.addAction(text if why is None else f"{text} ({why})")
            action.setToolTip(tip(tip_text))
            action.setEnabled(why is None)
            action.triggered.connect(
                lambda _on=False, m=mode: self.componentRequested.emit(key, m, parent, configuration)
            )
        menu.addSeparator()
        open_action = menu.addAction(OPEN_TEXT)
        f = open_action.font()
        f.setBold(True)  # what a double-click does
        open_action.setFont(f)
        open_action.triggered.connect(lambda: self.componentRequested.emit(key, OPEN, parent, configuration))
        show_action = menu.addAction(SHOW_TEXT)
        if t.in_folder_list is False:
            show_action.setEnabled(False)
            show_action.setText(f"{SHOW_TEXT} ({t.not_listed_reason})")
        show_action.triggered.connect(lambda: self.componentRequested.emit(key, SHOW, parent, configuration))
        return menu

    # -- the 3D view's instances -------------------------------------------------------
    def instance_item(self, ident: str) -> QTreeWidgetItem | None:
        """The row of the instance ``ident`` (a component tree id) on the Components tab."""
        if not ident or "instances" not in self.shown_trees():
            return None
        for item in _walk(self.instances):
            if item.data(0, IDENT_ROLE) == ident and item.data(0, KEY_ROLE):
                return item
        return None

    def select_instance(self, ident: str) -> bool:
        """Make the instance ``ident`` the current row of the instances, as a click on it
        in the 3D view does; "" leaves none current, and so does an instance without a row
        (one read from a sub-assembly's own file), for which it gives False, leaving the
        view's pick as it is. A body of a model file's multi-body part, drawn under its
        part's id (:func:`.modelview.fold`), makes the part's row current: a row inside the
        file stands for everything drawn under it."""
        tree = self.instances
        item = self.instance_item(ident) if ident else None
        if item is None and ident:
            row = self.row_of(ident)
            link = self.instance_link(row) if row else None
            if link is not None and is_internal(link[0]):
                item = self.instance_item(row)
        if item is None:
            self._quiet = True
            try:
                tree.clearSelection()
                tree.setCurrentItem(None)
            finally:
                self._quiet = False
            return not ident
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        tree.setCurrentItem(item)
        tree.scrollToItem(item)
        return True

    def select_file(self, key: str) -> bool:
        """Make the file ``key`` the current row of the Files table, as a click on it in the
        3D view's legend does; False when it has no row there (the pick stays the legend's)."""
        if "files" not in self.shown_trees():
            return False
        for item in _walk(self.files):
            if item.data(0, KEY_ROLE) == key:
                self.files.setCurrentItem(item)
                self.files.scrollToItem(item)
                return True
        return False

    def instance_link(self, ident: str) -> tuple[str, str, str] | None:
        """``(file key, the sub-assembly's file key, configuration)`` of the instance
        ``ident``, as its row holds them, from its row or, for an instance past the rows
        shown, from the components section; None when the section has no such instance."""
        item = self.instance_item(ident)
        if item is not None:
            return (
                item.data(0, KEY_ROLE),
                item.data(0, PARENT_ROLE) or "",
                item.data(0, CONFIG_ROLE) or "",
            )
        section = self.sections.get("components") or {}
        data = (section.get("data") or {}).get("components") if section.get("ok") else None
        stack = [(n, None) for n in (data or {}).get("children") or []]
        while stack:
            n, parent_file = stack.pop()
            if n.get("id") == ident:
                return (n["file"], parent_file or "", n.get("configuration") or "") if n.get("file") else None
            stack.extend((c, n.get("file")) for c in n.get("children") or [])
        return None

    def row_of(self, ident: str) -> str | None:
        """The id of the instance of the components section that stands for ``ident``:
        ``ident`` itself, or for an instance the library read from a sub-assembly's own
        file (which the section does not list) the nearest sub-assembly above it that the
        section lists; None when there is none, or no section yet."""
        probe = ident
        while probe:
            if self.instance_link(probe) is not None:
                return probe
            probe = probe.rpartition("/")[0]
        return None

    def open_instance(self, ident: str) -> bool:
        """Go to the file of the instance ``ident``, as a double-click on its row does; for
        one without a row, of the sub-assembly whose row stands for it (:meth:`row_of`)."""
        row = self.row_of(ident)
        link = self.instance_link(row) if row else None
        if link is None or is_internal(link[0]):
            return False
        key, parent, configuration = link
        self.componentRequested.emit(key, OPEN, parent, configuration)
        return True

    def instance_menu(self, ident: str) -> QMenu | None:
        """The menu of the instance ``ident`` in the 3D view: its row's, and Show on
        Components tab; for one without a row, its sub-assembly's (:meth:`row_of`). Then
        3D Print for its part and for each sub-assembly it is in (:meth:`add_path_prints`),
        how it looks, and how each sub-assembly it is in looks and whether it explodes
        (:meth:`.preview.PreviewPane.add_instance_actions`). None for an instance the
        view does not draw and the tab has no row for."""
        row = self.row_of(ident)
        link = self.instance_link(row) if row else None
        styled = self.preview.styles_3d and ident in self.preview.instance_ids
        if row is not None and link is not None:
            menu = self._link_menu(*link)
            item = self.instance_item(row)
            label = "Show on Components tab" if row == ident else f"Show {row} on Components tab"
            tab = menu.addAction(label)
            tab.setEnabled(item is not None)
            tab.triggered.connect(lambda: self._show_instance(row))
        elif styled:
            menu = relay_status_tips(QMenu(self))
            menu.setToolTipsVisible(True)
        else:
            return None
        self.add_path_prints(menu, ident)
        if styled:
            self.preview.add_instance_actions(menu, ident, path=True)
        return menu

    def _show_looks(self) -> None:
        """Mark the rows of the instances and of the files whose every instance drawn is
        hidden in the 3D view (greyed, with an eye struck through) or transparent (a half
        filled square), with a line in the tooltip saying so; a row with nothing drawn, or
        drawn as the file draws it, keeps its own look."""
        if not self.pages["Components"].showing_content or self.components_stack.currentIndex() != 0:
            return
        by_id, by_file = self.preview.look_summary()
        grey = self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
        for tree, summary in ((self.instances, by_id), (self.files, by_file)):
            for item in _walk(tree):
                name = item.data(0, IDENT_ROLE)
                if not name:
                    continue
                hidden, transparency = summary.get(name, (False, 0))
                base_tip = item.data(0, TIP_ROLE)
                if base_tip is None:
                    base_tip = item.toolTip(0)
                    item.setData(0, TIP_ROLE, base_tip)
                if hidden:
                    item.setIcon(0, look_icon("hidden"))
                    line = "Hidden in the 3D view."
                elif transparency:
                    item.setIcon(0, look_icon("transparent"))
                    line = f"{transparency}% transparent in the 3D view."
                else:
                    item.setIcon(0, QIcon())
                    line = ""
                if line and base_tip.endswith("</qt>"):  # one tooltip, escaped as tip() makes it
                    item.setToolTip(0, base_tip[: -len("</qt>")] + "<br>" + html.escape(line) + "</qt>")
                else:
                    item.setToolTip(0, base_tip or tip(line))
                color = grey if hidden or item.data(0, GREY_ROLE) else None
                for c in range(tree.columnCount()):
                    item.setData(c, Qt.ItemDataRole.ForegroundRole, color)

    def instance_menu_at(self, ident: str, where: QPoint) -> None:
        """The menu of a component right-clicked in the 3D view: its row's menu, then how the
        camera looks (:meth:`.preview.PreviewPane.add_camera_actions`), which a row of the
        Components tab does not offer."""
        menu = self.instance_menu(ident)
        if menu is not None:
            self.preview.add_camera_actions(menu)
            menu.exec(where)
            menu.deleteLater()

    def _show_instance(self, ident: str) -> None:
        if self.select_instance(ident):
            self.tabs.setCurrentIndex(TABS.index("Components"))

    def _no_current_rows(self) -> None:
        """No row of the instances or the files is current, and the view's pick stays: what
        the legend's row of the boxes does, which no row of the tab stands for."""
        self._quiet = True
        try:
            for tree in (self.instances, self.files):
                tree.clearSelection()
                tree.setCurrentItem(None)
        finally:
            self._quiet = False

    def _instance_current(self, current: QTreeWidgetItem | None, _previous) -> None:
        if self._quiet:
            return
        ident = current.data(0, IDENT_ROLE) if current is not None else None
        if ident:
            self._picked_in = "instances"
            self.preview.highlight_instance(ident)
        elif (self.preview.highlight or ("",))[0] == "instance":
            self.preview.highlight_instance(None)

    def _file_current(self, current: QTreeWidgetItem | None, _previous) -> None:
        if self._quiet:
            return
        key = current.data(0, KEY_ROLE) if current is not None else None
        if key:
            self._picked_in = "files"
            self.preview.highlight_file(key)
        elif (self.preview.highlight or ("",))[0] == "file":
            self.preview.highlight_file(None)

    def _context_menu(self, tree: QTreeWidget, pos: QPoint) -> None:
        item = tree.itemAt(pos)
        menu = self.component_menu(item) if item is not None else None
        if menu is not None:
            tree.setCurrentItem(item)
            menu.exec(tree.viewport().mapToGlobal(pos))
            menu.deleteLater()

    def shown_trees(self) -> list[str]:
        """The names of the :attr:`linked_trees` that show this document's rows: an
        assembly's instances and files or a drawing's sheets and models, and the
        references, once each has arrived."""
        names = []
        if self.pages["Components"].showing_content:
            assembly = self.components_stack.currentIndex() == 0
            names += ["instances", "files"] if assembly else ["sheets", "models"]
        if self.pages["BOM"].showing_content:
            names.append("bom")
        if self.pages["References"].showing_content:
            names.append("references")
        return names

    def find_item(self, tree: str, text: str) -> QTreeWidgetItem | None:
        """The first row of ``tree`` (a name of :attr:`linked_trees`), if it is shown,
        whose first column reads ``text`` and that stands for a file; for the self-test
        and tests."""
        if tree not in self.shown_trees():
            return None
        for item in _walk(self.linked_trees[tree]):
            if item.text(0) == text and item.data(0, KEY_ROLE):
                return item
        return None

    def selection(self) -> dict[str, str]:
        """The current row of each shown tree that has one, by its name in that tree; the
        tree the 3D view picked from last comes last, so restoring them in order picks
        the same thing there again."""
        out = {}
        for name in self.shown_trees():
            item = self.linked_trees[name].currentItem()
            if item is not None and item.data(0, IDENT_ROLE):
                out[name] = item.data(0, IDENT_ROLE)
        if self._picked_in in out:
            out[self._picked_in] = out.pop(self._picked_in)
        return out

    def restore_selection(self, selection: dict[str, str]) -> set[str]:
        """Make the rows :meth:`selection` named current again, where they are shown;
        the names of the trees done."""
        done = set()
        shown = self.shown_trees()
        for name, ident in selection.items():
            if name not in shown:
                continue
            tree = self.linked_trees[name]
            for item in _walk(tree):
                if item.data(0, IDENT_ROLE) == ident:
                    parent = item.parent()
                    while parent is not None:
                        parent.setExpanded(True)
                        parent = parent.parent()
                    tree.setCurrentItem(item)
                    tree.scrollToItem(item)
                    done.add(name)
                    break
        return done

    def configuration_shown(self) -> str | None:
        """The configuration the Components tab shows for an assembly, else None."""
        section = self.sections.get("components") or {}
        if not section.get("ok") or (section.get("data") or {}).get("kind") != "assembly":
            return None
        return self.config_combo.currentText() or None
