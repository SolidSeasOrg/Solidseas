"""The document list: one row per listing entry, with thumbnails, sorting and filtering.

Rows keep the listing entry exactly as ``solidseas.scan`` returned it, minus the
inline image. Thumbnails are kept as small PNGs and turned into icons only for
rows on screen, through a bounded cache.

A 3D file of another format than SOLIDWORKS (its entry's ``model`` object) shows
its format in Type (``STEP``, ``STEP assembly``, ``Alibre part``), its variant or
the program that wrote it in Saved with (``AP214``, ``binary``), and until its
thumbnail is there a badge in its format's family colour: meshes teal, exchange
formats purple, other programs' own formats brown; a file of a format SolidSeas
lists but cannot read a grey one. :class:`DocumentFilter` hides those unreadable
files unless asked, and filters by type with the quick filter's types
(:mod:`.quickfilter`, :mod:`.filetypes`).
"""

import os
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    QRectF,
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QStyle

from solidseas.formats import registry

from . import filetypes
from .reading import doc_type_of, release_text, size_text, time_text
from .wording import status_short, tip
from .workers import THUMB_HEIGHT, THUMB_WIDTH

# Status sits next to Type: it is what says why a row is red or grey.
GEOMETRY_UNREADABLE = "Geometry not readable"
COLUMNS = ("Name", "Type", "Status", "Saved with", "Modified", "Size", "Folder")
NAME, TYPE, STATUS, VERSION, MODIFIED, SIZE, FOLDER = range(len(COLUMNS))
SortRole = Qt.ItemDataRole.UserRole + 2
_ICON_CACHE_ROWS = 800

_TYPE_TEXT = {"part": "Part", "assembly": "Assembly", "drawing": "Drawing"}
_BADGES = {"part": ("PRT", "#4a7fb5"), "assembly": ("ASM", "#4f9a5a"), "drawing": ("DRW", "#c07a2c")}
# A badge for each format SolidSeas reads, in its family's colour; any other format's is grey.
_FAMILY_COLORS = {"mesh": "#2a8f8f", "exchange": "#7a5cc0", "native": "#a0522d"}
_UNREADABLE_COLOR = "#8a8f96"
_FORMAT_BADGES = {
    "stl": "STL",
    "3mf": "3MF",
    "obj": "OBJ",
    "ply": "PLY",
    "off": "OFF",
    "gltf": "GLB",
    "amf": "AMF",
    "parasolid": "X_T",
    "step": "STP",
    "alibre": "AD",
    "acis": "SAB",
    "iges": "IGS",
}
# Saved with: the program that wrote a file of these formats says more than their variant.
_BY_PROGRAM = ("3mf", "amf", "obj", "gltf")
_VARIANTS = {
    "ascii": "ASCII",
    "binary_le": "binary",
    "binary_be": "binary, big-endian",
    "core": "3MF core",
    "plain": "XML",
    "zip": "zipped XML",
    "sab": "binary",
    "sat": "text",
}

# The widest text each column usually holds, to size it from the font in use.
COLUMN_SAMPLES = (
    "",
    "Alibre assembly",
    "2 warnings",
    "Alibre 99.0",
    "2024-12-31 23:59",
    "999.9 KB",
    "subfolder",
)


def is_lock_file(entry: dict[str, Any]) -> bool:
    return entry["status"] == "skipped" and entry.get("reason") == "lock_file"


def is_document(entry: dict[str, Any]) -> bool:
    """A document the listing read: what the folder counts and the status bar count."""
    return entry["type"] == "file" and entry["status"] == "ok"


def entry_format(entry: dict[str, Any]) -> str | None:
    """The registry id of a listing entry's format: what the listing read it as (its
    ``model`` object), else what its extension names; None for a folder or a name no
    format has."""
    if entry["type"] != "file":
        return None
    m = entry.get("model")
    if m and m.get("format"):
        return m["format"]
    if entry.get("format") in ("modern", "ole"):
        return registry.SOLIDWORKS
    spec = registry.by_extension(entry["path"])
    return spec.id if spec is not None else None


def model_type_text(entry: dict[str, Any], fmt: str | None, doc_type: str | None) -> str:
    """The Type column of a file of another format: ``STEP``, ``STEP assembly``, ``Alibre
    part``; the format's name alone for one that was not read."""
    spec = registry.FORMATS.get(fmt or "")
    name = spec.name if spec is not None else "Document"
    if fmt == "alibre":
        return f"Alibre {doc_type or 'file'}"
    if entry["status"] == "ok" and doc_type == "assembly":
        return f"{name} assembly"
    return name


def model_saved_text(entry: dict[str, Any]) -> str:
    """The Saved with column of a file of another format: the program that wrote it for
    an Alibre file and the formats whose variant says little (3MF, AMF, OBJ, glTF), else
    its variant (``AP214``, ``binary``), else the program."""
    m = entry.get("model") or {}
    app = m.get("application") or {}
    program = " ".join(v for v in (app.get("name"), app.get("version")) if v)
    if m.get("format") == "alibre" and app.get("version"):
        return f"Alibre {app['version']}"
    if m.get("format") in _BY_PROGRAM and program:
        return program
    variant = m.get("variant")
    if variant and variant.casefold() != (m.get("format_name") or "").casefold():
        return _VARIANTS.get(variant, variant)
    return program


@dataclass
class Row:
    entry: dict[str, Any]
    name: str
    folder: str  # "/"-separated, "" for the opened folder itself
    doc_type: str | None
    thumb: bytes | None
    display: tuple[str, ...] = field(default=())
    sort: tuple[Any, ...] = field(default=())
    tip: str = ""  # escaped: a name can hold markup on Linux and macOS
    format: str | None = None  # the registry id: "solidworks", "step", "stl"...
    family: str | None = None  # the registry's family of that format
    unusable: bool = False  # its geometry turned out unreadable after the listing (marked red)

    @property
    def is_model(self) -> bool:
        """A file of another format than SOLIDWORKS (read or not)."""
        return self.format is not None and self.format != registry.SOLIDWORKS

    @classmethod
    def make(cls, entry: dict[str, Any], thumb: bytes | None) -> "Row":
        rel = entry["path"]
        folder, _, name = rel.rpartition("/")
        fmt = entry_format(entry)
        doc_type = doc_type_of(entry) if entry["type"] == "file" else None
        file = entry.get("file") or {}
        sv = entry.get("saved_version")
        spec = registry.FORMATS.get(fmt or "")
        model = fmt is not None and fmt != registry.SOLIDWORKS
        if entry["type"] == "folder":
            type_text = "Folder"
        elif model:
            type_text = model_type_text(entry, fmt, doc_type)
        else:
            type_text = _TYPE_TEXT.get(doc_type or "", "Document")
            if entry.get("detected"):  # another format in a SOLIDWORKS name: as the quick filter files it
                known = filetypes.TYPES.get(filetypes.file_type(entry) or "")
                if known is not None and "solidworks" not in known.formats:
                    type_text = known.name
        row = cls(entry, name, folder, doc_type, thumb)
        row.format, row.family = fmt, spec.family if spec is not None else None
        row.display = (
            name,
            type_text,
            status_short(entry),
            model_saved_text(entry) if model else release_text(sv, short=True),
            time_text(file.get("modified_utc")),
            size_text(file.get("size")),
            folder,
        )
        mtime = int(file["mtime_ns"]) if file.get("mtime_ns") else -1
        row.sort = (
            name.casefold(),
            type_text.casefold(),
            row.display[STATUS].casefold(),
            (sv or {}).get("format_version") or -1,
            mtime,
            file.get("size") if file.get("size") is not None else -1,
            folder.casefold(),
        )
        row.tip = tip(f"{rel}\n{row.display[STATUS]}" if row.display[STATUS] else rel)
        return row

    @cached_property
    def file_type(self) -> str | None:
        """Its type for the quick filter (:func:`.filetypes.file_type`)."""
        return filetypes.file_type(self.entry)


def _badge(text: str, color: str, size: tuple[int, int]) -> QIcon:
    width, height = size
    k = height / THUMB_HEIGHT
    pix = QPixmap(width, height)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(QRectF(20 * k, 8 * k, width - 40 * k, height - 16 * k), 10 * k, 10 * k)
    font = QFont()
    font.setBold(True)
    font.setPixelSize(max(8, round(22 * k)))
    p.setFont(font)
    p.setPen(QColor("white"))
    p.drawText(QRectF(0, 0, width, height), Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return QIcon(pix)


def _padded(pix: QPixmap, size: tuple[int, int]) -> QPixmap:
    """``pix`` centred on a transparent picture of the thumbnail cell's shape (``size``,
    4:3), as large as ``pix`` allows: a square 3MF or Alibre image is drawn as large as
    before, and every row's icon is as wide, so the names line up. A view draws an
    icon of another shape narrower, which moved those rows' names to the left."""
    width, height = size
    w, h = pix.width(), pix.height()
    if w <= 0 or h <= 0 or width <= 0 or height <= 0 or w * height == h * width:
        return pix
    if w * height < h * width:  # narrower than the cell: wider canvas
        cw, ch = (h * width + height - 1) // height, h
    else:  # flatter than the cell: taller canvas
        cw, ch = w, (w * height + width - 1) // width
    out = QPixmap(cw, ch)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.drawPixmap((cw - w) // 2, (ch - h) // 2, pix)
    p.end()
    return out


class DocumentModel(QAbstractTableModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rows: list[Row] = []
        self._by_path: dict[str, int] = {}
        self._by_name: dict[str, int] = {}
        self._icons: OrderedDict[int, QIcon] = OrderedDict()
        self._badges: dict[str, QIcon] = {}
        self.thumb_size = (THUMB_WIDTH, THUMB_HEIGHT)

    def set_thumb_size(self, size: tuple[int, int]) -> None:
        """The size badges are drawn at; thumbnails already listed keep theirs."""
        if size != self.thumb_size:
            self.thumb_size = size
            self._badges.clear()
            if self.rows:
                self.dataChanged.emit(self.index(0, NAME), self.index(len(self.rows) - 1, NAME))

    # -- content ---------------------------------------------------------------------
    def clear(self) -> None:
        self.beginResetModel()
        self.rows = []
        self._by_path.clear()
        self._by_name.clear()
        self._icons.clear()
        self.endResetModel()

    def append(self, batch: list[tuple[dict[str, Any], bytes | None]]) -> list[Row]:
        if not batch:
            return []
        new = [Row.make(entry, thumb) for entry, thumb in batch]
        first = len(self.rows)
        self.beginInsertRows(QModelIndex(), first, first + len(new) - 1)
        for i, row in enumerate(new, first):
            self._by_path.setdefault(row.entry["path"].casefold(), i)
            self._by_name.setdefault(row.name.casefold(), i)
        self.rows.extend(new)
        self.endInsertRows()
        return new

    def find(self, name: str) -> int | None:
        """The row of a document by its path below the opened folder, else by its file
        name (case-insensitive), else None."""
        want = name.replace("\\", "/").casefold()
        found = self._by_path.get(want)
        return found if found is not None else self._by_name.get(want)

    def set_thumb(self, i: int, thumb: bytes | None) -> None:
        """Give row ``i`` a thumbnail made after the listing (a rendered one)."""
        if not 0 <= i < len(self.rows):
            return
        self.rows[i].thumb = thumb
        self._icons.pop(i, None)
        index = self.index(i, NAME)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DecorationRole])

    def mark_unusable(self, i: int, why: str) -> None:
        """Row ``i`` was listed as read, but its geometry could not be read afterwards (by the
        thumbnail drawn for it, or the details panel): its Status says so, in red, and its
        tooltip gives ``why``. Marking a row twice changes nothing."""
        if not 0 <= i < len(self.rows) or self.rows[i].unusable:
            return
        row = self.rows[i]
        row.unusable = True
        text = GEOMETRY_UNREADABLE
        row.display = (*row.display[:STATUS], text, *row.display[STATUS + 1 :])
        row.sort = (*row.sort[:STATUS], text.casefold(), *row.sort[STATUS + 1 :])
        row.tip = tip(f"{row.entry['path']}\n{text}: {why}" if why else f"{row.entry['path']}\n{text}")
        self.dataChanged.emit(self.index(i, 0), self.index(i, len(COLUMNS) - 1))

    def find_path(self, rel: str) -> int | None:
        """The row of the entry at ``rel`` below the opened folder, compared as Windows
        compares names (case-insensitively); never another file of the same name."""
        return self._by_path.get(rel.replace("\\", "/").casefold())

    def entry(self, index: QModelIndex) -> dict[str, Any] | None:
        """The listing entry of a row of this model (not of a proxy). Entries stay in
        Python: handing a dict through a Qt role would convert it on every call."""
        return self.rows[index.row()].entry if index.isValid() else None

    # -- icons -------------------------------------------------------------------------
    def _placeholder(self, row: Row) -> QIcon:
        status = row.entry["status"]
        if row.entry["type"] == "folder":
            key = "folder-link" if status == "link" else "folder"
        elif status in ("error", "not_solidworks"):
            key = "warning"
        elif status in ("link", "placeholder", "skipped"):
            key = "file-link" if status == "link" else "file"
        elif row.is_model:
            key = f"format:{row.format}:{status}"
        else:
            key = row.doc_type or "file"
        icon = self._badges.get(key)
        if icon is None:
            style = QApplication.style()
            pixmaps = {
                "folder": QStyle.StandardPixmap.SP_DirIcon,
                "folder-link": QStyle.StandardPixmap.SP_DirLinkIcon,
                "warning": QStyle.StandardPixmap.SP_MessageBoxWarning,
                "file-link": QStyle.StandardPixmap.SP_FileLinkIcon,
                "file": QStyle.StandardPixmap.SP_FileIcon,
            }
            if key in _BADGES:
                icon = _badge(*_BADGES[key], self.thumb_size)
            elif key.startswith("format:"):
                spec = registry.FORMATS.get(row.format or "")
                label = _FORMAT_BADGES.get(row.format or "") or (spec.name[:3].upper() if spec else "3D")
                color = _UNREADABLE_COLOR if status == "unsupported" else _FAMILY_COLORS.get(row.family or "")
                icon = _badge(label, color or _UNREADABLE_COLOR, self.thumb_size)
            else:
                icon = style.standardIcon(pixmaps.get(key, QStyle.StandardPixmap.SP_FileIcon))
            self._badges[key] = icon
        return icon

    def icon(self, i: int) -> QIcon:
        row = self.rows[i]
        if row.thumb is None:
            return self._placeholder(row)
        icon = self._icons.get(i)
        if icon is not None:
            self._icons.move_to_end(i)
            return icon
        pix = QPixmap()
        if not pix.loadFromData(row.thumb, "PNG"):
            return self._placeholder(row)
        icon = QIcon(_padded(pix, self.thumb_size))
        self._icons[i] = icon
        if len(self._icons) > _ICON_CACHE_ROWS:
            self._icons.popitem(last=False)
        return icon

    # -- QAbstractTableModel --------------------------------------------------------
    def rowCount(self, parent=None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def columnCount(self, parent=None) -> int:
        return 0 if parent is not None and parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.ToolTipRole:
            return tip("Right-click to show or hide columns")
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return row.display[col]
        if role == SortRole:
            return row.sort[col]
        if role == Qt.ItemDataRole.DecorationRole and col == NAME:
            return self.icon(index.row())
        if role == Qt.ItemDataRole.ToolTipRole:
            return row.tip
        if role == Qt.ItemDataRole.TextAlignmentRole and col == SIZE:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole and (row.unusable or row.entry["status"] != "ok"):
            return QColor("#c62828") if row.unusable or row.entry["status"] == "error" else QColor("#808080")
        return None


class DocumentFilter(QSortFilterProxyModel):
    """Shows the documents in one folder and below it, whose names contain a text (or
    whose paths the index found for it, :meth:`set_also`), of the quick filter's types
    when it has any on (:meth:`set_types`): each filter narrows what the others show.
    SOLIDWORKS lock files, and files of formats SolidSeas cannot read, are hidden unless
    asked for (:meth:`listed`)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._folder = ""
        self._text = ""
        self._lock_files = False
        self._also: frozenset[str] = frozenset()
        self._types: frozenset[str] = frozenset()
        self._unreadable = False
        self.setSortRole(SortRole)
        self.setDynamicSortFilter(True)

    def _refilter(self, folder: str, text: str, lock_files: bool) -> None:
        if hasattr(self, "beginFilterChange"):  # Qt 6.9 and later; invalidateFilter is deprecated
            self.beginFilterChange()
            self._folder, self._text, self._lock_files = folder, text, lock_files
            self.endFilterChange()
        else:
            self._folder, self._text, self._lock_files = folder, text, lock_files
            self.invalidateFilter()

    def set_folder(self, folder: str) -> None:
        self._refilter(folder, self._text, self._lock_files)

    def set_text(self, text: str) -> None:
        self._also = frozenset()  # the index's matches were for the old text
        self._refilter(self._folder, text.strip().casefold(), self._lock_files)

    def set_also(self, paths) -> None:
        """Also keep the entries at these paths while a text is set: what the index's
        search found for it (part numbers, descriptions, properties)."""
        self._also = frozenset(paths)
        self._refilter(self._folder, self._text, self._lock_files)

    def set_lock_files(self, shown: bool) -> None:
        self._refilter(self._folder, self._text, shown)

    def set_types(self, types: Iterable[str]) -> None:
        """Keep only the rows of these quick filter types (:mod:`.filetypes`); with none,
        rows of every type and folders."""
        types = frozenset(types)
        if types != self._types:
            self._types = types
            self._refilter(self._folder, self._text, self._lock_files)

    @property
    def types(self) -> frozenset[str]:
        return self._types

    def _set(self, name: str, value: Any) -> None:
        if hasattr(self, "beginFilterChange"):  # Qt 6.9 and later; invalidateFilter is deprecated
            self.beginFilterChange()
            setattr(self, name, value)
            self.endFilterChange()
        else:
            setattr(self, name, value)
            self.invalidateFilter()

    def set_unreadable(self, shown: bool) -> None:
        """Show the files of formats SolidSeas lists but cannot read (status ``unsupported``)."""
        self._set("_unreadable", bool(shown))

    @property
    def unreadable(self) -> bool:
        return self._unreadable

    @property
    def lock_files(self) -> bool:
        return self._lock_files

    @property
    def text(self) -> str:
        """The name filter's text, case-folded; "" when there is none."""
        return self._text

    @property
    def folder(self) -> str:
        """The folder shown, ``/``-separated below the opened one; "" for all of it."""
        return self._folder

    def listed(self, row: "Row") -> bool:
        """Whether ``row`` is listed at all, whatever the folder, the text and the type
        filters: what a setting hides (lock files, and files of formats SolidSeas cannot
        read) is not. The quick filter offers the types of these rows, so it never offers
        a type whose files are all hidden."""
        if not self._lock_files and is_lock_file(row.entry):
            return False
        return self._unreadable or row.entry["status"] != "unsupported"

    def accepts(self, row: "Row", *, types: bool = True) -> bool:
        """Whether ``row`` passes the filters; with ``types`` false, every filter but the
        quick filter (what it would show of each type)."""
        if not self.listed(row):
            return False
        if types and self._types and row.file_type not in self._types:
            return False
        f = self._folder
        if f and row.folder != f and not row.folder.startswith(f + "/"):
            return False
        return not self._text or self._text in row.name.casefold() or row.entry["path"] in self._also

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex) -> bool:
        return self.accepts(self.sourceModel().rows[source_row])


def folder_chain(folder: str) -> list[str]:
    """``a/b/c`` gives ``["a", "a/b", "a/b/c"]``; the opened folder itself is ``""``."""
    if not folder:
        return []
    parts = folder.split("/")
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


def display_folder(path: str) -> str:
    return os.path.basename(os.path.normpath(path)) or path
