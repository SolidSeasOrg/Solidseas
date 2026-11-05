"""The main window: a folder tree, the document list and the details panel.

Every file read runs in a worker (:mod:`.workers`). The listing has a pool of its
own; reading a document's details and exporting share a single-thread pool, so
the folder index used for reference resolution is touched by one thread at a
time. A details read that the selection has moved on from is cancelled between
sections and its results are dropped.

A third single-thread pool waits for a part's or an assembly's display meshes
for the optional 3D view, only when the Preview tab asks for it. The meshes
are read in a child process (:mod:`.meshproc`), which a cancelled read ends at
once; an assembly's component files are found there by reference resolution in
the opened folder, as the details panel finds them. A
fourth checks that the remembered folder is still there when the window
starts, so a server that has gone away holds up nothing else.

Settings (:mod:`.settings`) are read once when the window is made, from the
store it is given, and applied live: the Settings menu has the quick toggles
and Preferences. A window made without a store keeps its settings in memory.
With Remember Last Folder off, the folder dialogs' own record of the last
folder (Qt keeps one for every Qt program) is put back as it was after each
dialog.

Text that comes from a document or a path is shown as plain text: message
boxes and labels are set to plain text, and tooltips are escaped
(:func:`.wording.tip`).

A component's file can be opened from the contents of an assembly or a
drawing (:meth:`MainWindow.go_to_component`). The details panel already holds
the document's references resolved against the opened folder, so going there
reads nothing new: a file in the list is selected in it, one found outside the
opened folder and a virtual component (a nested document inside the assembly)
are shown on their own in the details panel, with a note saying so, and the
list then has no selection. Back (Alt+Left, the mouse's thumb Back button or a
keyboard's Back key) returns to the document before, with its tab,
configuration, selected rows, explode, 3D camera, what the 3D view hid or made
transparent, the sub-assemblies chosen to explode, and the 3D view's pick, put
back as it was where no row gives it (a part read from a sub-assembly's own
file, or every box).

The opened folder is indexed in the background once it is listed, and the
Where Used tab and the name filter read that index (:mod:`.whereused`).

Every 3D file SolidSeas knows is listed with SOLIDWORKS documents (View > Show > All
3D Files, on by default): STEP, Parasolid, STL, 3MF, OBJ, PLY, OFF, glTF, AMF, ACIS
and Alibre Design files are read, and a file of a format SolidSeas only recognises
(Inventor, VRML...) is listed only with View > Show > Files SolidSeas Cannot Read. IGES
and BREP files are read while the OCCT backend extension is on, and listed while it is
off, greyed, saying what they need. The Extensions page's changes reach the window at
once (:meth:`MainWindow.extensions_changed`): the worker processes are started again
when what they may start changes, and the folder is read again when what SolidSeas can
read changes. A file of another format is never read in the window's process (a
compound file wearing a SOLIDWORKS extension is a SOLIDWORKS document to the listing,
read in the window's threads as every SOLIDWORKS document is): the listing's entries,
the details panel's sections and the thumbnails drawn for files that store no image
(:mod:`.thumbnailer`) come from the window's own worker processes
(:mod:`.modelpool`), the 3D view from the mesh process and 3D Print and Export for
3D Printing from the export's process, all of which answer in JSON, PNG images
SolidSeas wrote and vertex buffers. File > Open File... opens one file, any format.

Open, on the toolbar, the File menu and the right-click menu of a file, hands the
file to the program the system opens it with, and Show in File Explorer shows it in
its folder (:mod:`.opening`); Go to file, on a component's menu, is what shows a file
here. The window starts no program for either: the system does, at the user's
request.

Tools > Modeling Assistant and the toolbar's Assistant button open the modeling
assistant's window (:mod:`solidseas_app.assistant.window`), one at a time: pressed
again, they bring the open one forward. Settings > AI Settings and Tools > AI Settings
open the AI settings page (:mod:`solidseas_app.assistant.settings_dialog`). Both use
the AI settings file ``AI.json`` beside the window's own settings file (in memory when
those are), and import the AI connector only when first opened.
"""

import os
import struct
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from PySide6.QtCore import (
    QByteArray,
    QEvent,
    QItemSelectionModel,
    QModelIndex,
    QPoint,
    QSettings,
    QSize,
    QStandardPaths,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    qVersion,
)
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTableView,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from solidseas import __version__
from solidseas.bom import TYPE_NAMES as BOM_TYPE_NAMES
from solidseas.resolve import IndexCache
from solidseas.trademarks import DISCLAIMER

from . import experimental, navigate, opening, printing, reading
from .convertaction import TEXT as CONVERT_TEXT
from .convertaction import TIP as CONVERT_TIP
from .convertaction import ConvertController
from .details import OPEN, PROGRAM, REVEAL, SHOW, TABS, DetailsPanel
from .documents import (
    COLUMN_SAMPLES,
    COLUMNS,
    FOLDER,
    MODIFIED,
    NAME,
    SIZE,
    STATUS,
    DocumentFilter,
    DocumentModel,
    display_folder,
    entry_format,
    folder_chain,
    is_document,
    is_lock_file,
)
from .lookstore import LookStore
from .menus import relay_status_tips
from .meshproc import MeshReader
from .modelpool import ModelPool
from .preferences import BOXES_NOTE, POINTER_TIP, VIEW_3D_STATUS, VIEW_CUBE_TIP
from .preview import MODEL
from .printaction import HERE_TEXT, HERE_TIP, PrintController, PrintTarget
from .quickfilter import QuickFilterBar
from .settings import Session, Settings, SettingsStore
from .stepaction import TEXT as STEP_TEXT
from .stepaction import TIP as STEP_TIP
from .stepaction import StepController
from .thumbnailer import Thumbnailer
from .viewmath import FREE, MOUSE_STYLES, ROTATION_MODES, SOLIDWORKS, STANDARD, TURNTABLE
from .whereused import WhereUsedController
from .wording import (
    error_message,
    needs_extension,
    plural,
    refusal_text,
    rule_text,
    sentence,
    tip,
    unread_text,
)
from .workers import Job, listing_work, preview_image

TITLE = f"SolidSeas Viewer (preview {__version__})"
READ_ONLY = "Read-only: SolidSeas never changes your files"
_FolderRole = Qt.ItemDataRole.UserRole + 1
_SPARE_COLUMNS = (SIZE, MODIFIED)  # what gives way, in this order, when the name gets too narrow
_STATUS_MAX = 200  # pixels: a longer status is elided, and its tooltip has it whole
_DOC_WORDS = {
    "part": ("part", "parts"),
    "assembly": ("assembly", "assemblies"),
    "drawing": ("drawing", "drawings"),
}
_HISTORY = 100  # places Back remembers
LOOKS_WRITE_MS = 1000  # the looks file is written this long after the last change, and at close
BACK_KEYS = "Alt+Left"
OPEN_TITLE = "Go to file"


@dataclass
class Place:
    """A document the details panel showed, and how, for Back to return to."""

    entry: dict[str, Any]  # its listing entry, or the one made for a document not in the list
    source: reading.Source
    apart: dict[str, str] | None  # "where" and "note" for a document not in the list, else None
    tab: int = 0
    selection: dict[str, str] = field(default_factory=dict)
    configuration: str | None = None
    folder_filter: str = ""
    name_filter: str = ""
    type_filter: frozenset[str] = frozenset()  # the quick filter's types on
    explode: int = 0  # how far the 3D view had an assembly exploded, in percent
    explode_level: str | None = None  # and grouped how
    camera: dict[str, Any] | None = None  # how the 3D view was turned and zoomed, if it showed the document
    # What the 3D view had picked (:attr:`.preview.PreviewPane.highlight`): put back as it
    # was where no row of the tab gives it, such as an instance read from a sub-assembly's
    # own file, or every box.
    pick: tuple[str, str] | None = None
    # What the 3D view hid or made transparent, and the sub-assemblies chosen to explode or
    # stay together (:meth:`.preview.PreviewPane.view_state`).
    view: dict[str, Any] | None = None

    @property
    def rel(self) -> str | None:
        """Its path in the list, or None."""
        return None if self.apart is not None else self.entry["path"]


class CandidateDialog(QDialog):
    """Pick one of the files an ambiguous reference could be."""

    def __init__(self, parent: QWidget | None, t: navigate.Target) -> None:
        super().__init__(parent)
        self.setWindowTitle(OPEN_TITLE)
        self.target = t
        label = QLabel(
            f"Several files could be {t.name}, and none fits better than the others. "
            "Choose the one to open." + (f"\n\nStored path: {t.stored_path}" if t.stored_path else "")
        )
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        self.list = QTreeWidget()
        self.list.setHeaderLabels(["Location", "Found by", "Identity"])
        self.list.setRootIsDecorated(False)
        self.list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        for i, c in enumerate(t.candidates):
            where = c.location if c.rel is not None else f"outside the opened folder: {c.location}"
            item = QTreeWidgetItem([where, rule_text(c.found_by), c.identity or ""])
            item.setToolTip(0, tip(c.location))
            item.setData(0, Qt.ItemDataRole.UserRole, i)
            usable = not c.placeholder and (c.rel is not None or c.path is not None)
            if not usable:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsSelectable)
                if c.placeholder:
                    item.setText(2, "cloud placeholder, not opened")
            self.list.addTopLevelItem(item)
        for col in range(3):
            self.list.resizeColumnToContents(col)
        self.list.setMinimumWidth(min(900, max(480, self.list.columnWidth(0) + 260)))
        self.list.itemDoubleClicked.connect(lambda *_: self.accept() if self.chosen() is not None else None)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.open_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.open_button.setText("Open")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.list.currentItemChanged.connect(
            lambda *_: self.open_button.setEnabled(self.chosen() is not None)
        )
        first = next(
            (
                self.list.topLevelItem(i)
                for i in range(self.list.topLevelItemCount())
                if self.list.topLevelItem(i).flags() & Qt.ItemFlag.ItemIsEnabled
            ),
            None,
        )
        if first is not None:
            self.list.setCurrentItem(first)
        self.open_button.setEnabled(self.chosen() is not None)
        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(self.list, 1)
        layout.addWidget(buttons)

    def chosen(self) -> int | None:
        """The candidate picked, by its index in the target's candidates."""
        item = self.list.currentItem()
        if item is None or not item.flags() & Qt.ItemFlag.ItemIsEnabled:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)


def show_message(parent: QWidget | None, icon: QMessageBox.Icon, title: str, text: str) -> None:
    """A message box whose text is plain text: it can quote a path or a document's text,
    which Qt would otherwise take for rich text when it looks like markup."""
    box = QMessageBox(icon, title, text, QMessageBox.StandardButton.Ok, parent)
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.exec()


def folder_exists(path: str) -> bool:
    """``os.path.isdir``; on a server that has gone away it takes the network's time-out."""
    return os.path.isdir(path)


def file_dialog_settings() -> QSettings:
    """Where Qt's file dialogs keep the last folder and their history: shared by every
    Qt program of the user (the registry on Windows)."""
    return QSettings(QSettings.Scope.UserScope, "QtProject")


_DIALOG_KEYS = ("lastVisited", "history")
_ABSENT = object()


def pick_folder(parent: QWidget | None, title: str, start: str, *, remember: bool) -> str:
    """``QFileDialog.getExistingDirectory``. Qt's dialog records the folder it showed
    when it closes; unless ``remember``, that record is put back as it was. (Windows'
    own folder dialog keeps a recent folder per program as well, out of Qt's reach.)"""
    return _dialog(lambda: QFileDialog.getExistingDirectory(parent, title, start), remember=remember)


def open_filters() -> list[str]:
    """File > Open File...'s filters: every 3D file SolidSeas reads, each format SolidSeas
    reads on its own, then all files."""
    from solidseas.formats import registry

    readable = [f for f in registry.FORMATS.values() if registry.readable(f.id)]

    def patterns(f) -> str:
        return " ".join(f"*{ext}" for ext in f.extensions)

    out = [f"3D files SolidSeas reads ({' '.join(patterns(f) for f in readable)})"]
    out += [f"{f.name} ({patterns(f)})" for f in readable]
    out.append("All files (*)")
    return out


def pick_file(parent: QWidget | None, title: str, start: str, *, remember: bool) -> str:
    """``QFileDialog.getOpenFileName`` with :func:`open_filters`, remembering the folder
    as :func:`pick_folder` does."""
    filters = ";;".join(open_filters())
    return _dialog(lambda: QFileDialog.getOpenFileName(parent, title, start, filters)[0], remember=remember)


def _dialog(show: Callable[[], str], *, remember: bool) -> str:
    saved: dict[str, Any] = {}
    if not remember:
        qs = file_dialog_settings()
        qs.beginGroup("FileDialog")
        saved = {k: qs.value(k) if qs.contains(k) else _ABSENT for k in _DIALOG_KEYS}
    try:
        return show()
    finally:
        if not remember:
            qs = file_dialog_settings()
            qs.beginGroup("FileDialog")
            for key, value in saved.items():
                if value is _ABSENT:
                    qs.remove(key)
                else:
                    qs.setValue(key, value)
            qs.endGroup()
            qs.sync()


def splitter_state_ok(state: bytes) -> bool:
    """Whether ``state`` looks like what ``QSplitter.saveState`` writes for the
    window's three panes: the marker, version 1 and a short list of sizes. Anything
    else (a hand-edited or damaged value) is never handed to Qt."""
    if len(state) < 12:
        return False
    marker, version, count = struct.unpack_from(">iiI", state)
    return marker == 0xFF and version == 1 and count <= 16 and len(state) >= 12 + 4 * count


def _folder_kind(entry: dict[str, Any]) -> int:
    """Which of a folder's counts a listed entry adds to: 0 a document read, 1 any other
    entry, 2 a SOLIDWORKS lock file, 3 a file of a format SolidSeas cannot read. The last
    two are counted only while their settings list them (:meth:`.DocumentFilter.listed`);
    a file of a format an extension opens is always listed, so it is 1."""
    if is_document(entry):
        return 0
    if is_lock_file(entry):
        return 2
    return 3 if entry["status"] == "unsupported" and not needs_extension(entry) else 1


# What Export BOM writes: the format's key for reading.export_bom, and its name in the dialog.
BOM_FORMATS = {"csv": "CSV (UTF-8, for Excel and ERP imports)", "json": "JSON (the bom envelope)"}
# What Export for 3D Printing writes.
PRINT_FORMATS = {
    "3mf": "3MF (each part once, placed by its items, in millimetres)",
    "stl": "STL (one binary mesh, in millimetres)",
}
AS_IS_TEXT = "&Open 3MF and STL Files As They Are"
AS_IS_TIP = (
    "3D Print opens a 3MF or STL file in the program as it is when it would be sent in its own format: a "
    "3MF when 3MF or STEP is chosen (a 3MF cannot go as STEP), an STL when STL is. Nothing is written, and "
    "a slicer project keeps its plates and settings, but the program then has your own file open, and "
    "saving there replaces it. Off (the default), it is exported to a new file next to the model like any "
    "other file."
)


class ExportDialog(QDialog):
    """Where to write an export, and whether an existing file may be replaced."""

    def __init__(
        self,
        parent: QWidget,
        title: str,
        folder: str,
        *,
        text_option: bool,
        pick: Callable[[QWidget, str, str], str] | None = None,
        formats: dict[str, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._pick = pick or (lambda p, t, start: QFileDialog.getExistingDirectory(p, t, start))
        self.folder = QLineEdit(folder)
        self.folder.setMinimumWidth(380)
        self.folder.setPlaceholderText("Choose an output folder")
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        self.text = QCheckBox("Also write Parasolid text (.x_t)")
        self.text.setVisible(text_option)
        self.format = QComboBox()  # what to write, for an export with a choice (a BOM)
        for key, label in (formats or {}).items():
            self.format.addItem(label, key)
        self.overwrite = QCheckBox("Overwrite existing files")
        note = QLabel(
            "SolidSeas writes only into the folder you choose here. It refuses the folder you "
            "opened and the document's own folder, never writes a SOLIDWORKS file and replaces "
            "an existing file only when you tick Overwrite."
        )
        note.setWordWrap(True)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.export_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.export_button.setText("Export")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.folder.textChanged.connect(self._folder_changed)
        self._folder_changed(self.folder.text())
        form = QFormLayout()
        form.addRow("Output folder:", row)
        if formats:
            form.addRow("Format:", self.format)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.text)
        layout.addWidget(self.overwrite)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def _folder_changed(self, text: str) -> None:
        self.export_button.setEnabled(bool(text.strip()))

    def _browse(self) -> None:
        chosen = self._pick(self, "Output folder", self.folder.text())
        if chosen:
            self.folder.setText(os.path.normpath(chosen))


class MainWindow(QMainWindow):
    listingFinished = Signal(object)  # the listing job's result
    detailsFinished = Signal(int)  # the generation whose sections have all arrived
    meshFinished = Signal(int)  # the generation whose 3D mesh read has ended, however it ended

    def __init__(
        self, store: SettingsStore | None = None, ai: Any = None, *, looks_path: str | None = None
    ) -> None:
        super().__init__()
        from .gcguard import install as collect_on_this_thread

        collect_on_this_thread()  # never on a worker: see gcguard
        self.setWindowTitle(TITLE)
        self.setAcceptDrops(True)
        self.resize(self._default_size())
        self.store = store if store is not None else SettingsStore(None)
        self.settings = self.store.load()  # read once, here
        # Each document's looks in the 3D view (.lookstore): in the file ``looks_path`` names,
        # from one run to the next (the launcher's, beside Viewer.ini), else in memory only.
        self.look_store = LookStore(looks_path)
        # The AI settings, keys and usage (assistant.aisettings.AIConfig), made when first needed.
        self._ai = ai
        self.assistant: Any = None  # the modeling assistant's window, while it is open
        self.ai_dialog: Any = None  # the AI settings page, while it is open
        self.settings_window: Any = None  # the Settings window, while it is open
        self._staged: list | None = None  # a re-index's rows, until it is read
        self._index_read_at: float | None = None  # when the shown index was read
        # The extension formats (savedindex.extension_formats) readable when the listing
        # running, and the one shown, were read: what a switch changed is read again.
        self._listing_extensions: tuple[str, ...] = ()
        self._shown_extensions: tuple[str, ...] = ()

        self.folder: str | None = None
        self.listing_pool = QThreadPool(self)
        self.listing_pool.setMaxThreadCount(1)
        self.work_pool = QThreadPool(self)
        self.work_pool.setMaxThreadCount(1)
        self.mesh_pool = QThreadPool(self)
        self.mesh_pool.setMaxThreadCount(1)
        self.check_pool = QThreadPool(self)  # the remembered folder's check, which can wait on a network
        self.check_pool.setMaxThreadCount(1)
        self.mesh_reader = MeshReader()  # its process starts when the 3D view first needs a mesh
        self.models = ModelPool()  # the worker processes that read files of other formats, when there are any
        self.export_pool = QThreadPool(self)  # Export for 3D Printing waits on its process here
        self.export_pool.setMaxThreadCount(1)
        self._export_job: Job | None = None
        self._listing_follows = False  # a setting changed by open_path, which lists the folder itself
        self._jobs: set[Job] = set()
        self._listing: Job | None = None
        self._details: Job | None = None
        self._mesh: Job | None = None
        self._mesh_token: object | None = None
        self.mesh_result: dict[str, Any] | None = None
        self._closing = False
        self._session_restored = False
        self._generation = 0
        self._entry: dict[str, Any] | None = None
        self._source: reading.Source | None = None  # where the shown document is read from
        self._bom_editors: list[Any] = []  # open BOM editors, kept alive while shown
        self._apart: dict[str, str] | None = None  # set while it is not a row of the list
        self._history: list[Place] = []
        self._pending_go: tuple[Any, ...] | None = None  # (generation, request...) waiting for references
        self._restore: list[Any] | None = None  # [generation, Place, configuration asked for]
        self._pending_select: str | None = None
        self._cache = IndexCache()
        self._folder_epoch = 0  # a new one each time a folder is opened: the mesh process indexes it again
        self._listed = 0
        self._last_export_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation
        )
        self._folders: dict[str, QTreeWidgetItem] = {}
        # Per folder: documents read, other entries, lock files and files of formats SolidSeas
        # cannot read (each counted below it too). The last two count only while shown.
        self._folder_counts: dict[str, list[int]] = {}
        self._split_done = False
        self._columns_chosen = False  # the user showed or hid a column: no automatic choice
        self._content_columns: dict[int, bool] = {FOLDER: False, STATUS: False}
        self._status_sample = ""  # the longest status listed, to size its column
        self._columns_sized = False  # the user resized a column: no automatic widths
        self._fitting = False
        self.listing_info: dict[str, Any] | None = None
        self.details_seconds: dict[str, float] = {}

        self.model = DocumentModel(self)
        self.proxy = DocumentFilter(self)
        self.proxy.setSourceModel(self.model)

        self._build_views()
        self.printer = PrintController(self)  # the 3D Print button and its program (.printaction)
        self.thumbnailer = Thumbnailer(self)  # pictures drawn for files of other formats that store none
        self.details.print_item = self.add_component_print  # 3D Print in the rows' and the legend's menus
        self.details.print_document = self.add_document_print  # and for a part no row stands for
        self.details.print_missing = self.add_missing_print  # off, for one whose file was not found
        self.details.preview.print_shown = self.add_shown_print  # and on the 3D view's empty space
        self.step = StepController(self)  # File > Export STEP (.stepaction)
        self.convert = ConvertController(self)  # File > Convert, the OCCT backend's (.convertaction)
        self._build_actions()
        # Drawings (.drawingaction): New Drawing and Open Drawing after 3D Print, Drawing
        # Settings, and Make Drawing beside every right-click menu's 3D Print entry.
        from .drawingaction import DrawingController

        self.drawings = DrawingController(self)
        self.drawings.install(self.menuBar().actions()[0].menu(), self.settings_menu, self.toolbar)
        self._build_status()
        self.where_used = WhereUsedController(self)  # indexing, the Where Used tab and the filter
        self.apply_settings(self.settings, save=False, initial=True)
        if self.store.reset_keys:
            self.statusBar().showMessage(
                "Some saved settings were not valid and are back to their defaults.", 10000
            )
        self._select_timer = QTimer(self)
        self._select_timer.setSingleShot(True)
        self._select_timer.setInterval(120)
        self._select_timer.timeout.connect(self._load_current)
        self._fit_timer = QTimer(self)  # columns refit once a resize settles
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(60)
        self._fit_timer.timeout.connect(self._fit_columns)
        self.split.splitterMoved.connect(lambda *_: self._fit_timer.start())
        self._looks_timer = QTimer(self)  # the looks file is written once the changes settle
        self._looks_timer.setSingleShot(True)
        self._looks_timer.setInterval(LOOKS_WRITE_MS)
        self._looks_timer.timeout.connect(self.look_store.flush)
        self.look_store.on_change = self._looks_timer.start
        self._update_actions()
        self._back_window = None  # the native window whose Back button and key go back
        # The list narrows when its scroll bar appears, often after the columns were fitted
        # (rows arrive after the listing is done): fit them again, or they overflow it.
        self.table.viewport().installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        """The mouse's thumb Back button (XButton1) and a keyboard's Back key go back,
        wherever the pointer or the focus is in this window, as in Explorer and browsers.
        Watched on the window itself, which has every mouse and key event before the
        widget under the pointer or with the focus (whatever that widget does with it).
        The list's viewport is watched too: a change of its width refits the columns."""
        if watched is self.table.viewport():
            if event.type() == QEvent.Type.Resize and event.size().width() != event.oldSize().width():
                self._fit_timer.start()
            return False
        if watched is not self._back_window:
            return False
        kind = event.type()
        if kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            back = event.button() == Qt.MouseButton.BackButton
        elif kind == QEvent.Type.KeyPress:
            back = event.key() == Qt.Key.Key_Back
        else:
            return False
        if back:
            self.go_back()
        return back

    @staticmethod
    def _default_size() -> QSize:
        """1440 x 900, or less on a smaller screen."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return QSize(1440, 900)
        avail = screen.availableGeometry()
        return QSize(
            max(900, min(1440, int(avail.width() * 0.92))), max(600, min(900, int(avail.height() * 0.9)))
        )

    # -- construction ----------------------------------------------------------------
    def _build_views(self) -> None:
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Folders"])
        self.tree.itemSelectionChanged.connect(self._folder_selected)

        self.table = QTableView()
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)  # keeps the extension in view
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setIconSize(QSize(40, 30))
        self.table.setModel(self.proxy)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._header_menu)
        header.sectionResized.connect(self._section_resized)
        self.table.sortByColumn(NAME, Qt.SortOrder.AscendingOrder)

        self.icons = QListView()
        self.icons.setViewMode(QListView.ViewMode.IconMode)
        self.icons.setResizeMode(QListView.ResizeMode.Adjust)
        self.icons.setMovement(QListView.Movement.Static)
        self.icons.setUniformItemSizes(True)
        self.icons.setWordWrap(True)
        self.icons.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self._size_icons()
        self.icons.setSpacing(4)
        self.icons.setModel(self.proxy)
        self.icons.setModelColumn(NAME)
        self.icons.setSelectionModel(self.table.selectionModel())
        self.table.selectionModel().currentRowChanged.connect(self._current_changed)
        for view in (self.table, self.icons):  # a part's or an assembly's row offers 3D Print
            view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            view.customContextMenuRequested.connect(lambda pos, v=view: self._list_menu(v, pos))

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by name")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self.proxy.set_text)
        self.sort_combo = QComboBox()
        self.sort_combo.addItems([f"Sort by {c.lower()}" for c in COLUMNS])
        self.sort_combo.activated.connect(
            lambda i: self.table.sortByColumn(i, self.table.horizontalHeader().sortIndicatorOrder())
        )
        self.table.horizontalHeader().sortIndicatorChanged.connect(self._sort_changed)
        # Filtering by type is the quick filter's row under this bar (.quickfilter): one button
        # per type the folder holds, of every format, several at once for a family.
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addWidget(self.filter, 1)
        bar.addWidget(self.sort_combo)

        empty = QWidget()
        el = QVBoxLayout(empty)
        el.addStretch(1)
        hint = QLabel(
            "Open a folder of 3D files to list them: SOLIDWORKS documents, STEP, Parasolid, STL, 3MF, "
            "OBJ, glTF, Alibre Design and more.\n" + READ_ONLY + "."
        )
        hint.setTextFormat(Qt.TextFormat.PlainText)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        el.addWidget(hint)
        open_button = QPushButton("Open Folder...")
        open_button.clicked.connect(self.choose_folder)
        el.addWidget(open_button, 0, Qt.AlignmentFlag.AlignHCenter)
        el.addStretch(2)

        self.list_stack = QStackedWidget()
        self.list_stack.addWidget(empty)
        self.list_stack.addWidget(self.table)
        self.list_stack.addWidget(self.icons)
        middle = QWidget()
        ml = QVBoxLayout(middle)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.addLayout(bar)
        self.quick = QuickFilterBar(self.model, self.proxy)  # the type buttons (.quickfilter)
        QWidget.setTabOrder(self.sort_combo, self.quick.all_button)
        ml.addWidget(self.quick)
        ml.addWidget(self._make_index_bar())
        ml.addWidget(self.list_stack, 1)

        self.details = DetailsPanel()
        self.details.configurationRequested.connect(self._configuration_requested)
        self.details.bomExportRequested.connect(self.export_bom)
        self.details.bomEditRequested.connect(self.edit_bom)
        self.details.geometryFailed.connect(self._geometry_failed)
        self.details.componentRequested.connect(
            lambda key, mode, parent, configuration: self.go_to_component(
                key, mode, parent or None, configuration or None
            )
        )
        self.details.preview.meshRequested.connect(self._mesh_requested)
        self.details.preview.warmUp.connect(self._warm_mesh_reader)
        self.details.preview.view_store = self.look_store

        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.addWidget(self.tree)
        self.split.addWidget(middle)
        self.split.addWidget(self.details)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 2)
        self.split.setStretchFactor(2, 3)
        self.setCentralWidget(self.split)

    def _size_icons(self) -> None:
        w, h = self.settings.thumbnail_pixels
        self.icons.setIconSize(QSize(w, h))
        self.icons.setGridSize(QSize(w + 28, h + 48))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        handle = self.windowHandle()
        if handle is not None and handle is not self._back_window:
            handle.installEventFilter(self)
            self._back_window = handle
        if not self._split_done:  # shares of the real width, once the window has one
            self._split_done = True
            if self._session_restored:
                QTimer.singleShot(0, self._fit_columns)
                return
            w = max(self.split.width(), self.width())
            tree, middle = int(w * 0.1), int(w * 0.44)
            self.split.setSizes([tree, middle, max(w - tree - middle, 300)])
            QTimer.singleShot(0, self._fit_columns)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        timer = getattr(self, "_fit_timer", None)  # None while __init__ runs
        if timer is not None:
            timer.start()

    # -- the document table's columns -----------------------------------------------
    def _auto_columns(self) -> None:
        """Which columns have something to show: Folder when a document lies in a
        subfolder, Status when a listed row has a status (an error, a warning, a
        link...). The others always have."""
        rows = [r for r in self.model.rows if self.proxy.listed(r)]
        self._content_columns = {
            FOLDER: any(r.folder for r in rows),
            STATUS: any(r.display[STATUS] for r in rows),
        }
        self._status_sample = max((r.display[STATUS] for r in rows), key=len, default="")
        self._fit_columns()

    def _fit_columns(self) -> None:
        """Size the columns from the font in use and give the name what is left.

        Until the user shows or hides a column, the empty Folder and Status columns
        are hidden, and when the name would still be too narrow, Size and then
        Modified give way (right-click the header to bring them back). Stops sizing once
        the user resizes a column."""
        if self._columns_sized:
            return
        fm = self.table.fontMetrics()
        pad = 22
        self._fitting = True
        try:
            widths = {}
            for c, sample in enumerate(COLUMN_SAMPLES):
                if c != NAME:
                    widths[c] = max(fm.horizontalAdvance(sample), fm.horizontalAdvance(COLUMNS[c])) + pad
            widths[STATUS] = max(
                widths[STATUS], min(fm.horizontalAdvance(self._status_sample) + pad, _STATUS_MAX)
            )
            for c, width in widths.items():
                self.table.setColumnWidth(c, width)
            avail = self.table.viewport().width() if self.table.isVisible() else self.list_stack.width() - 24
            # Room for about twenty characters: the name is elided in the middle, so its
            # start and its extension stay in view.
            minimum = fm.horizontalAdvance("o16_asm_fe...SLDASM") + self.table.iconSize().width() + pad

            def left() -> int:
                return avail - sum(w for c, w in widths.items() if not self.table.isColumnHidden(c))

            if not self._columns_chosen:
                for c, shown in self._content_columns.items():
                    self.table.setColumnHidden(c, not shown)
                for c in _SPARE_COLUMNS:
                    self.table.setColumnHidden(c, False)
                for c in _SPARE_COLUMNS:
                    if left() >= minimum:
                        break
                    self.table.setColumnHidden(c, True)
            self.table.setColumnWidth(NAME, max(minimum, left()))
        finally:
            self._fitting = False

    def _section_resized(self, column: int, old: int, new: int) -> None:
        # The last visible column follows the view's width by itself; only a resize of
        # another column, while the table is on screen, is the user's. Hiding or
        # showing a column resizes it to or from 0, and Qt can report that later,
        # after _fit_columns has finished: nobody drags a column to or from nothing.
        header = self.table.horizontalHeader()
        if old == 0 or new == 0 or header.isSectionHidden(column):
            return
        visible = [header.logicalIndex(v) for v in range(header.count())]
        visible = [c for c in visible if not header.isSectionHidden(c)]
        if not self._fitting and self.table.isVisible() and visible and column != visible[-1]:
            self._columns_sized = True

    def _header_menu(self, pos: QPoint) -> None:
        menu = relay_status_tips(QMenu(self))
        for c, name in enumerate(COLUMNS):
            if c == NAME:
                continue
            a = menu.addAction(name)
            a.setCheckable(True)
            a.setChecked(not self.table.isColumnHidden(c))
            a.toggled.connect(lambda on, col=c: self._show_column(col, on))
        menu.exec(self.table.horizontalHeader().mapToGlobal(pos))

    def _show_column(self, column: int, shown: bool) -> None:
        self._columns_chosen = True
        self.table.setColumnHidden(column, not shown)

    def _build_actions(self) -> None:
        st = self.style()

        def act(text: str, icon, slot, shortcut=None, tip_text: str | None = None) -> QAction:
            a = QAction(st.standardIcon(icon), text, self) if icon is not None else QAction(text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            if tip_text:
                a.setStatusTip(tip_text)
                a.setToolTip(tip_text)
            return a

        SP = QStyle.StandardPixmap
        self.act_open = act(
            "&Open Folder...", SP.SP_DirOpenIcon, self.choose_folder, QKeySequence.StandardKey.Open
        )
        self.act_open_file = act(
            "Open &File...",
            SP.SP_FileIcon,
            self.choose_file,
            "Ctrl+Shift+O",
            "Open one 3D file of any format SolidSeas reads: its folder is listed and the file selected",
        )
        self.act_open_shown = act("Ope&n", SP.SP_DialogOpenButton, self.open_shown, None, opening.OPEN_TIP)
        self.act_show_shown = act(
            opening.show_text(), SP.SP_DirLinkIcon, self.show_shown, None, opening.show_tip()
        )
        self.act_reload = act("&Reload", SP.SP_BrowserReload, self.reload, QKeySequence.StandardKey.Refresh)
        self.act_cancel = act("&Cancel Listing", SP.SP_BrowserStop, self.cancel_listing, "Esc")
        self.act_parasolid = act(
            "Export &Parasolid...",
            SP.SP_DialogSaveButton,
            self.export_parasolid,
            None,
            "Write the document's Parasolid bodies (.x_b, optionally .x_t) to a folder you choose",
        )
        self.act_step = act(STEP_TEXT, SP.SP_DialogSaveButton, self.export_step, None, STEP_TIP)
        self.act_convert = act(CONVERT_TEXT, SP.SP_DialogSaveButton, self.convert_file, None, CONVERT_TIP)
        self.act_convert.setVisible(self.convert_offered())  # the OCCT backend's front: there only with it
        self.act_preview = act(
            "Export Preview &Image...",
            SP.SP_FileDialogContentsView,
            self.export_preview,
            None,
            "Write the stored preview image to a folder you choose",
        )
        self.act_export_print = act(
            "Export for 3D Printin&g...",
            None,
            self.export_for_printing,
            None,
            "Write the part or assembly shown as STL or 3MF to a folder you choose, as 3D Print makes it",
        )
        self.act_bom = act(
            "Export &BOM...",
            None,
            self.export_bom,
            None,
            "Write the BOM the BOM tab shows to a CSV or JSON file in a folder you choose",
        )
        self.act_copy = act(
            "&Copy Summary JSON",
            SP.SP_FileDialogDetailedView,
            self.copy_json,
            "Ctrl+Shift+C",
            "Copy the document summary JSON, as the command line prints it",
        )
        self.act_back = act(
            "&Back",
            SP.SP_ArrowBack,
            self.go_back,
            BACK_KEYS,
            "Return to the document you opened a component's file from (Alt+Left)",
        )
        self.act_assistant = act(
            experimental.tagged("&Modeling Assistant..."),
            SP.SP_ComputerIcon,
            self.open_assistant,
            "Ctrl+Shift+A",
            "Open the modeling assistant: describe a change to a SOLIDWORKS part, and the AI model you set "
            "up drafts code you read before anything runs",
        )
        self.act_ai_settings = act(
            "&AI Settings...",
            None,
            lambda: self.open_settings("AI Assistant"),
            None,
            "Choose the AI provider and model the modeling assistant uses, store its API key and set its "
            "monthly budget",
        )
        self.act_about = act("&About SolidSeas Viewer", SP.SP_MessageBoxInformation, self.about)
        self.act_licences = act(
            "&Licences...",
            None,
            self.show_licences,
            None,
            "Show the licences of SolidSeas and of the third-party software it carries",
        )
        self.act_quit = act("E&xit", None, self.close, QKeySequence.StandardKey.Quit)
        self.act_details_view = QAction("&Details", self, checkable=True)
        self.act_icons_view = QAction("&Icons", self, checkable=True)
        group = QActionGroup(self)
        for a in (self.act_details_view, self.act_icons_view):
            group.addAction(a)
        self.act_details_view.setChecked(True)
        self.act_details_view.triggered.connect(lambda: self.set_view("details"))
        self.act_icons_view.triggered.connect(lambda: self.set_view("icons"))
        self.act_lock_files = QAction("Show SOLIDWORKS &Lock Files", self, checkable=True)
        self.act_lock_files.setStatusTip("List the ~$ files SOLIDWORKS keeps while a document is open")
        self.act_lock_files.toggled.connect(lambda on: self.change_settings(show_lock_files=on))
        self.act_all_formats = QAction("&All 3D Files", self, checkable=True)
        self.act_all_formats.setStatusTip(
            "List every 3D file SolidSeas knows with the SOLIDWORKS documents: STEP, Parasolid, STL, 3MF, "
            "OBJ, PLY, OFF, glTF, AMF, ACIS and Alibre Design files. Off, only SOLIDWORKS documents."
        )
        self.act_all_formats.toggled.connect(lambda on: self.change_settings(show_all_formats=on))
        self.act_unreadable = QAction("Files SolidSeas &Cannot Read", self, checkable=True)
        self.act_unreadable.setStatusTip(
            "Also list the files of 3D formats SolidSeas recognises but cannot read yet, such as Inventor "
            "and VRML files, so you can see they are there"
        )
        self.act_unreadable.toggled.connect(lambda on: self.change_settings(show_unreadable=on))
        self.act_print_as_is = QAction(AS_IS_TEXT, self, checkable=True)
        self.act_print_as_is.setStatusTip(AS_IS_TIP)
        self.act_print_as_is.setToolTip(AS_IS_TIP)
        self.act_print_as_is.toggled.connect(lambda on: self.change_settings(print_as_is=on))
        self.act_preferences = act(
            "&Settings...",
            None,
            lambda: self.open_settings(),
            "Ctrl+,",
            "Every setting of SolidSeas in one window: the viewer, the 3D view, 3D Print, drawings, the AI "
            "assistant and extensions",
        )
        self.act_preferences.setMenuRole(QAction.MenuRole.PreferencesRole)
        self.act_3d = QAction("Interactive &3D View", self, checkable=True)
        self.act_3d.setStatusTip(VIEW_3D_STATUS)
        self.act_3d.toggled.connect(lambda on: self.change_settings(view_3d=on))
        self.act_boxes = QAction("&Boxes for Missing Meshes", self, checkable=True)
        self.act_boxes.setStatusTip(BOXES_NOTE)
        self.act_boxes.toggled.connect(lambda on: self.change_settings(draw_boxes=on))
        self.act_mouse: dict[str, QAction] = {}
        mouse_group = QActionGroup(self)
        for style, text in (
            (STANDARD, "&Standard: Left-Drag Rotates"),
            (SOLIDWORKS, "&Middle-Drag Rotates, as in SOLIDWORKS"),
        ):
            a = QAction(text, self, checkable=True)
            a.setStatusTip(MOUSE_STYLES[style])
            a.setToolTip(MOUSE_STYLES[style])
            a.triggered.connect(lambda _on=False, st=style: self.change_settings(mouse_style=st))
            mouse_group.addAction(a)
            self.act_mouse[style] = a
        self.act_rotation: dict[str, QAction] = {}
        rotation_group = QActionGroup(self)
        for mode, text in (
            (FREE, "&Free: Any View, as in SOLIDWORKS"),
            (TURNTABLE, "&Turntable: Stays Upright"),
        ):
            a = QAction(text, self, checkable=True)
            a.setStatusTip(ROTATION_MODES[mode])
            a.setToolTip(ROTATION_MODES[mode])
            a.triggered.connect(lambda _on=False, m=mode: self.change_settings(rotation_mode=m))
            rotation_group.addAction(a)
            self.act_rotation[mode] = a
        self.act_view_cube = QAction("&View Cube in the 3D View", self, checkable=True)
        self.act_view_cube.setStatusTip(VIEW_CUBE_TIP)
        self.act_view_cube.toggled.connect(lambda on: self.change_settings(view_cube=on))
        self.act_pointer = QAction("Turn About the Point &Under the Pointer", self, checkable=True)
        self.act_pointer.setStatusTip(POINTER_TIP)
        self.act_pointer.toggled.connect(lambda on: self.change_settings(turn_about_pointer=on))
        self.act_invert_wheel = QAction("Reverse &Wheel Zoom", self, checkable=True)
        self.act_invert_wheel.setStatusTip(
            "Zoom the other way with the wheel, in either style, like the SOLIDWORKS option "
            "Reverse direction of mouse wheel zoom"
        )
        self.act_invert_wheel.toggled.connect(lambda on: self.change_settings(invert_wheel=on))
        self.act_remember = QAction("&Remember Last Folder and Layout", self, checkable=True)
        self.act_remember.setStatusTip(
            "Open the last folder, at the same window size, when the viewer starts"
        )
        self.act_remember.toggled.connect(lambda on: self.change_settings(remember_session=on))
        self.act_print_here = QAction(HERE_TEXT, self, checkable=True)
        self.act_print_here.setStatusTip(HERE_TIP)
        self.act_print_here.setToolTip(HERE_TIP)
        self.act_print_here.toggled.connect(lambda on: self.change_settings(print_next_to_model=on))

        self.act_details_view.setIcon(st.standardIcon(SP.SP_FileDialogListView))
        self.act_icons_view.setIcon(st.standardIcon(SP.SP_FileDialogContentsView))
        self.act_preview.setIcon(st.standardIcon(SP.SP_FileDialogInfoView))
        self.act_print = self.printer.action
        short = {
            self.act_back: "Back",
            self.act_open: "Open Folder",
            self.act_open_shown: "Open",
            self.act_reload: "Reload",
            self.act_cancel: "Cancel",
            self.act_details_view: "Details",
            self.act_icons_view: "Icons",
            self.act_parasolid: "Parasolid",
            self.act_preview: "Preview Image",
            self.act_copy: "Copy JSON",
            self.act_assistant: "Assistant",
        }
        for a, text in short.items():
            a.setIconText(text)

        m = self.menuBar()
        fm = m.addMenu("&File")
        fm.setToolTipsVisible(True)  # Export STEP's says why it is off for a document
        for a in (self.act_open, self.act_open_file):
            fm.addAction(a)
        self.recent_menu = fm.addMenu("Recent &Folders")
        self.recent_menu.setToolTipsVisible(True)
        for a in (self.act_reload, self.act_cancel):
            fm.addAction(a)
        self._fill_recent_menu()
        fm.addSeparator()
        fm.addAction(self.act_open_shown)
        fm.addAction(self.act_show_shown)
        fm.addSeparator()
        fm.addAction(self.act_parasolid)
        fm.addAction(self.act_step)
        fm.addAction(self.act_convert)
        fm.addAction(self.act_preview)
        fm.addAction(self.act_bom)
        fm.addAction(self.act_export_print)
        fm.addAction(self.act_print)
        fm.addSeparator()
        fm.addAction(self.act_quit)
        m.addMenu("&Edit").addAction(self.act_copy)
        vm = m.addMenu("&View")
        vm.addAction(self.act_back)
        vm.addSeparator()
        vm.addAction(self.act_details_view)
        vm.addAction(self.act_icons_view)
        vm.addSeparator()
        show = vm.addMenu("&Show")
        solidworks_files = show.addAction("SOLIDWORKS Files")
        solidworks_files.setCheckable(True)
        solidworks_files.setChecked(True)
        solidworks_files.setEnabled(False)  # always listed
        show.addAction(self.act_all_formats)
        show.addAction(self.act_unreadable)
        vm.addAction(self.act_lock_files)
        self.view_menu = vm
        tm = m.addMenu("&Tools")
        tm.addAction(self.act_assistant)
        tm.addAction(self.act_ai_settings)
        tm.addSeparator()
        self.act_extensions = tm.addAction("&Extensions...")
        self.act_extensions.setStatusTip("Choose which extensions are on, and add or remove their packages")
        self.act_extensions.triggered.connect(lambda _on=False: self.open_settings("Extensions"))
        self.tools_menu = tm
        sm = m.addMenu("&Settings")
        sm.addAction(self.act_preferences)
        sm.addAction(self.act_ai_settings)
        sm.addSeparator()
        sm.addAction(self.act_3d)
        sm.addAction(self.act_boxes)
        sm.addAction(self.act_view_cube)
        mouse = sm.addMenu("Mouse in the 3D View")
        for a in self.act_mouse.values():
            mouse.addAction(a)
        sm.addAction(self.act_invert_wheel)
        rotation = sm.addMenu("Rotation in the 3D View")
        for a in self.act_rotation.values():
            rotation.addAction(a)
        rotation.addSeparator()
        rotation.addAction(self.act_pointer)
        sm.addSeparator()
        sm.addMenu(self.printer.menu)
        sm.addAction(self.act_print_here)
        sm.addAction(self.act_print_as_is)
        sm.addSeparator()
        sm.addAction(self.act_lock_files)
        sm.addAction(self.act_remember)
        self.settings_menu = sm
        help_menu = m.addMenu("&Help")
        help_menu.addAction(self.act_licences)
        help_menu.addAction(self.act_about)

        tb = self.addToolBar("Main")
        tb.setObjectName("main-toolbar")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        tb.addAction(self.act_back)
        tb.addSeparator()
        for a in (self.act_open, self.act_reload, self.act_cancel):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.act_open_shown)
        tb.addAction(self.act_show_shown)
        tb.addSeparator()
        tb.addAction(self.act_details_view)
        tb.addAction(self.act_icons_view)
        tb.addSeparator()
        for a in (self.act_parasolid, self.act_preview, self.act_copy):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.act_print)
        tb.addSeparator()
        tb.addAction(self.act_assistant)
        self.toolbar = tb
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        badge = QToolButton()
        badge.setText("PREVIEW")
        badge.setToolTip(tip("An early preview of SolidSeas Desktop. " + READ_ONLY + "."))
        badge.setStyleSheet(
            "QToolButton { background: #c25100; color: white; font-weight: bold; border-radius: 3px;"
            " padding: 2px 8px; margin-right: 6px; }"
        )
        badge.clicked.connect(self.about)
        tb.addWidget(badge)

    def _build_status(self) -> None:
        sb = self.statusBar()
        self.status_label = QLabel("No folder open")
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)  # it quotes the folder's path
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setMaximumWidth(160)
        self.progress.setMaximumHeight(14)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_listing)
        sb.addWidget(self.status_label, 1)
        sb.addWidget(self.progress)
        sb.addWidget(self.cancel_button)
        read_only = QLabel("Read-only")
        read_only.setToolTip(tip(READ_ONLY))
        sb.addPermanentWidget(read_only)
        self.progress.hide()
        self.cancel_button.hide()

    # -- jobs ----------------------------------------------------------------------------
    def _start(self, pool: QThreadPool, job: Job, on_progress=None, on_finished=None) -> Job:
        self._jobs.add(job)
        if on_progress is not None:
            job.signals.progress.connect(on_progress)

        def finished(result: Any) -> None:
            try:
                if on_finished is not None:
                    on_finished(result)
            finally:
                QTimer.singleShot(0, lambda: self._jobs.discard(job))

        job.signals.finished.connect(finished)
        pool.start(job)
        return job

    # -- folders and listing ---------------------------------------------------------
    def pick_folder(self, parent: QWidget, title: str, start: str) -> str:
        return pick_folder(parent, title, start, remember=self.settings.remember_session)

    def choose_folder(self) -> None:
        start = self.folder or QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation
        )
        chosen = self.pick_folder(self, "Open a folder of 3D files", start)
        if chosen:
            self.open_folder(os.path.normpath(chosen))

    def choose_file(self) -> None:
        """File > Open File...: one 3D file of any format; its folder is listed and the file
        selected (:meth:`open_path`)."""
        start = self.folder or QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation
        )
        chosen = pick_file(self, "Open a 3D file", start, remember=self.settings.remember_session)
        if chosen:
            self.open_path(os.path.normpath(chosen))

    def _geometry_failed(self, rel: str, why: str) -> None:
        """The details panel could not read a listed file's geometry: its row says so."""
        i = self.model.find_path(rel)
        if i is not None:
            self.model.mark_unusable(i, why)

    def open_path(self, path: str) -> None:
        """A folder opens as it is; a file opens its folder and selects it. A file of another
        format than SOLIDWORKS turns View > Show > All 3D Files on first when it is off (and
        Files SolidSeas Cannot Read for one of a format SolidSeas cannot read, to say why;
        an IGES or BREP file is listed without it, saying what it needs), so it is listed to
        be selected."""
        path = os.path.abspath(path)
        if os.path.isfile(path):
            from solidseas.formats import registry

            spec = registry.by_extension(path)
            changes: dict[str, bool] = {}
            if spec is not None and spec.id != registry.SOLIDWORKS:
                changes["show_all_formats"] = True
                if not registry.readable(spec.id) and spec.backend is None:
                    changes["show_unreadable"] = True
            if changes:
                self._listing_follows = True  # the folder is listed below: once, with them
                try:
                    self.change_settings(**changes)
                finally:
                    self._listing_follows = False
            self.open_folder(os.path.dirname(path), select=os.path.basename(path))
        else:
            self.open_folder(path)

    def reload(self) -> None:
        """Reload: read the folder again (re-index it), the list staying until the new one
        is read."""
        if self.folder:
            self.reindex()

    def reindex(self) -> None:
        """Read the opened folder again, keeping the list shown until the new one is read,
        then swapping it in; the new index is saved."""
        if self.folder is None:
            return
        if self._listing is not None:
            return
        current = self._entry.get("path") if isinstance(self._entry, dict) else None
        self._pending_select = current or self._pending_select
        self._start_listing(self.folder, staged=True)

    # -- the saved index ----------------------------------------------------------------
    def _make_index_bar(self) -> QWidget:
        """The bar above the list that says how old the shown index is, with Re-index."""
        bar = QFrame()
        bar.setFrameShape(QFrame.Shape.StyledPanel)
        row = QHBoxLayout(bar)
        row.setContentsMargins(6, 2, 6, 2)
        self.index_label = QLabel("")
        self.index_label.setTextFormat(Qt.TextFormat.PlainText)
        self.index_button = QPushButton("Re-index")
        self.index_button.setToolTip(tip("Read every file of the folder again (Reload, F5)"))
        self.index_button.clicked.connect(self.reindex)
        row.addWidget(self.index_label, 1)
        row.addWidget(self.index_button)
        bar.hide()
        self.index_bar = bar
        return bar

    def _show_index_age(self, read_at: float | None, *, reindexing: bool = False) -> None:
        from .savedindex import age_text

        if read_at is None:
            self.index_bar.hide()
            return
        age = age_text(max(0.0, time.time() - read_at))
        if reindexing:
            self.index_label.setText(f"Showing this folder's index from {age} ago while it is read again...")
        else:
            self.index_label.setText(f"This folder's index is {age} old. Re-index to read every file again.")
        self.index_button.setEnabled(not reindexing)
        self.index_bar.show()

    def _formats(self) -> str:
        return "all" if self.settings.show_all_formats else "solidworks"

    def _save_index(self, result: dict[str, Any]) -> None:
        """Keep the listing just read as the folder's index, on a thread of its own."""
        if not (self.settings.keep_index and result.get("ok") and not result.get("cancelled")):
            return
        folder, formats, size = self.folder, self._formats(), self.settings.thumbnail_pixels
        extensions = self._shown_extensions  # what was readable when the folder was read
        rows = [(r.entry, r.thumb) for r in self.model.rows]
        counts, reason = result.get("counts") or {}, result.get("truncated_reason")
        read_at = self._index_read_at  # when the folder was read, not when the save ends
        from .savedindex import index_folder, save

        # The cache folder of now: a self-test's own one (selftest.own_cache_folder) is put
        # back to the person's when the run ends, and a save still waiting must not follow it.
        root = index_folder()

        def work() -> None:
            try:
                save(
                    folder,
                    formats,
                    size,
                    rows,
                    counts=counts,
                    truncated_reason=reason,
                    read_at=read_at,
                    root=root,
                    extensions=extensions,
                )
            except (OSError, ValueError, Exception):  # a cache that cannot be written: listed next time
                pass

        threading.Thread(target=work, name="solidseas-save-index", daemon=True).start()

    def _fill_recent_menu(self) -> None:
        """File > Recent Folders: the folders opened last, newest first, and Clear."""
        menu = getattr(self, "recent_menu", None)
        if menu is None:
            return
        menu.clear()
        recent = self.store.load_session().recent if self.settings.recent_count else ()
        for n, folder in enumerate(recent[: self.settings.recent_count], 1):
            name = display_folder(folder).replace("&", "&&")  # a folder's & is not a shortcut
            action = menu.addAction(f"&{n}  {name}" if n < 10 else name)
            action.setToolTip(tip(folder))
            action.triggered.connect(lambda _on=False, f=folder: self.open_folder(f))
        if not recent:
            empty = menu.addAction("No recent folders")
            empty.setEnabled(False)
            return
        menu.addSeparator()
        clear = menu.addAction("Clear Recent Folders")
        clear.triggered.connect(self.clear_recent)

    def clear_recent(self) -> None:
        """Forget the recent folders (the opened one is still reopened at start)."""
        session = self.store.load_session()
        session.recent = ()
        self.store.save_session(session)
        self._fill_recent_menu()

    def _remember_recent(self, folder: str) -> None:
        from .settings import remember_folder

        if not self.settings.recent_count:
            return
        session = self.store.load_session()
        session.recent = remember_folder(session.recent, folder, self.settings.recent_count)
        self.store.save_session(session)
        self._fill_recent_menu()

    def open_folder(self, folder: str, select: str | None = None) -> None:
        folder = os.path.abspath(folder)
        if not os.path.isdir(folder):
            show_message(self, QMessageBox.Icon.Warning, TITLE, f"Not a folder:\n{folder}")
            return
        self.cancel_listing()
        if self._details is not None:
            self._details.cancel()
        self._cancel_mesh()
        self.thumbnailer.stop()
        if folder != self.folder:  # Back stays within one folder; F5 keeps its places
            self._history.clear()
        self.folder = folder
        self.where_used.folder_opened(folder)
        self._pending_select = select
        self._cache = IndexCache()
        self._folder_epoch += 1
        self._generation += 1
        self._entry = None
        self._source = self._apart = None
        self._pending_go = self._restore = None
        self.model.clear()
        self._listed = 0
        self.listing_info = None
        self.tree.clear()
        self._folders = {}
        self._folder_counts = {}
        root = QTreeWidgetItem(self.tree, [display_folder(folder)])
        root.setData(0, _FolderRole, "")
        root.setToolTip(0, tip(folder))
        root.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self._folders[""] = root
        self.tree.setCurrentItem(root)
        self.details.clear("Select a document to see its details.")
        self.list_stack.setCurrentIndex(2 if self.act_icons_view.isChecked() else 1)
        self.model.set_thumb_size(self.settings.thumbnail_pixels)
        self._remember_recent(folder)
        self.index_bar.hide()
        saved = None
        if self.settings.keep_index:
            from .savedindex import extension_formats, load

            extensions = extension_formats()
            saved = load(folder, self._formats(), self.settings.thumbnail_pixels, extensions=extensions)
            if saved is not None:
                self._shown_extensions = extensions
        if saved is not None:
            self._show_saved(saved)
            hours = self.settings.reindex_after_hours
            if hours and saved.age_seconds() > hours * 3600:
                self._start_listing(folder, staged=True)
            return
        self._start_listing(folder)

    def _show_saved(self, saved: Any) -> None:
        """The folder's saved index, at once, as if it had just been listed."""
        try:
            for batch in saved.entries():
                self._add_rows(batch)
        except Exception:  # the file went away or is damaged: list the folder instead
            self.model.clear()
            self._listed = 0
            self._start_listing(self.folder)
            return
        result = {
            "ok": True,
            "counts": dict(saved.counts),
            "truncated_reason": saved.truncated_reason,
            "cancelled": False,
            "seconds": 0.0,
            "saved": True,
            "read_at": saved.read_at,
        }
        self._index_read_at = saved.read_at
        self._finish_listing(result)
        self._show_index_age(saved.read_at)

    def _start_listing(self, folder: str, *, staged: bool = False) -> None:
        """Read the folder (the listing); ``staged``: into a buffer, the list shown staying
        until the new one is read (a re-index)."""
        from .savedindex import extension_formats

        self._staged = [] if staged else None
        self._listing_extensions = extension_formats()
        if not staged:  # its rows are the list from the first batch on
            self._shown_extensions = self._listing_extensions
        if staged:
            if not self.index_bar.isHidden():  # its words change; the list never moves for it
                self._show_index_age(self._index_read_at, reindexing=True)
            self.status_label.setText(f"Re-indexing {folder}...")
        else:
            self.status_label.setText(f"Listing {folder}...")
        self.progress.show()
        self.cancel_button.show()
        work = listing_work(
            folder, self.settings.thumbnail_pixels, formats=self._formats(), foreign_pool=self.models
        )
        job = Job(work)
        self._listing = job
        self._start(
            self.listing_pool,
            job,
            on_progress=lambda batch, j=job: self._listing_batch(j, batch),
            on_finished=lambda result, j=job: self._listing_done(j, result),
        )
        self._update_actions()

    def cancel_listing(self) -> None:
        if self._listing is not None:
            self._listing.cancel()

    def _folder_label(self, f: str) -> None:
        docs, others, locks, unreadable = self._folder_counts.get(f, [0, 0, 0, 0])
        total = docs + others + (locks if self.proxy.lock_files else 0)
        total += unreadable if self.proxy.unreadable else 0
        name = display_folder(self.folder or "") if f == "" else f.rpartition("/")[2]
        item = self._folders[f]
        item.setText(0, f"{name} ({docs:,})" if total == docs else f"{name} ({docs:,} of {total:,})")
        text = f"{plural(docs, 'document')} read" + (
            f", {plural(total, 'entry', 'entries')} listed" if total != docs else ""
        )
        item.setToolTip(0, tip((self.folder or "") + "\n" + text if f == "" else text))

    def _listing_batch(self, job: Job, batch: list) -> None:
        if job is not self._listing:
            return
        if self._staged is not None:  # a re-index: kept until the new listing is read
            self._staged.extend(batch)
            self.status_label.setText(f"Re-indexing {self.folder}... {len(self._staged):,} entries")
            return
        self._add_rows(batch)
        self.status_label.setText(f"Listing {self.folder}... {self._listed:,} entries")

    def _add_rows(self, batch: list) -> None:
        rows = self.model.append(batch)
        self._listed += len(rows)
        touched: set[str] = set()
        for row in rows:
            if row.entry["type"] == "folder" and row.entry["status"] == "ok":
                continue
            kind = _folder_kind(row.entry)
            for f in ["", *folder_chain(row.folder)]:
                counts = self._folder_counts.setdefault(f, [0, 0, 0, 0])
                counts[kind] += 1
                touched.add(f)
                if f not in self._folders:
                    parent = self._folders[f.rpartition("/")[0]]
                    item = QTreeWidgetItem(parent, [f.rpartition("/")[2]])
                    item.setData(0, _FolderRole, f)
                    item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
                    self._folders[f] = item
        for f in touched:
            self._folder_label(f)
        self._folders[""].setExpanded(True)

    def _listing_done(self, job: Job, result: dict[str, Any]) -> None:
        if job is not self._listing:
            return
        self._listing = None
        self.progress.hide()
        self.cancel_button.hide()
        staged, self._staged = self._staged, None
        if staged is not None:
            if not result.get("ok") or result.get("cancelled"):  # the shown index stays
                if not self.index_bar.isHidden():
                    self._show_index_age(self._index_read_at)
                self.status_label.setText("Re-indexing was stopped; the saved index is still shown.")
                self._update_actions()
                return
            self._swap_rows(staged)
        self.index_bar.hide()
        self._index_read_at = time.time()
        self._shown_extensions = self._listing_extensions
        self._finish_listing(result)
        self._save_index(result)

    def _swap_rows(self, batch: list) -> None:
        """The list and the folder tree, made again from ``batch`` (a re-index's rows)."""
        self.model.clear()
        self._listed = 0
        self.tree.clear()
        self._folders = {}
        self._folder_counts = {}
        folder = self.folder or ""
        root = QTreeWidgetItem(self.tree, [display_folder(folder)])
        root.setData(0, _FolderRole, "")
        root.setToolTip(0, tip(folder))
        root.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self._folders[""] = root
        self.tree.setCurrentItem(root)
        for i in range(0, len(batch), 256):
            self._add_rows(batch[i : i + 256])

    def _finish_listing(self, result: dict[str, Any]) -> None:
        self.listing_info = result
        self.quick.listing_done(result)
        if not result.get("ok"):
            err = result.get("error") or {}
            self.status_label.setText("The folder could not be listed.")
            self.details.clear("The folder could not be listed.\n\n" + error_message(err))
        else:
            self.status_label.setText(self._counts_text(result))
            self.tree.sortItems(0, Qt.SortOrder.AscendingOrder)
            self._auto_columns()
        self._update_actions()
        if self._pending_select:
            self.select_document(self._pending_select)
            self._pending_select = None
        self.where_used.folder_listed(result)
        if result.get("ok"):
            self.thumbnailer.start()  # files of other formats that store no image: drawn now
        self.listingFinished.emit(result)

    def _counts_text(self, result: dict[str, Any]) -> str:
        from solidseas.formats import registry

        rows = self.model.rows
        types = Counter(r.doc_type for r in rows if is_document(r.entry) and r.doc_type and not r.is_model)
        docs = sum(types.values())
        parts = [plural(n, *_DOC_WORDS.get(t, (t, t + "s"))) for t, n in sorted(types.items())]
        text = f"{plural(docs, 'document')} read" + (f" ({', '.join(parts)})" if parts else "")
        models = Counter(r.format for r in rows if is_document(r.entry) and r.is_model)
        if models:
            named = [
                f"{n:,} {registry.FORMATS[f].name if f in registry.FORMATS else f}"
                for f, n in models.most_common(5)
            ]
            more = ", and more" if len(models) > 5 else ""
            word = "other 3D file" if docs else "3D file"
            them = f"{plural(sum(models.values()), word)} read ({', '.join(named)}{more})"
            text = f"{text}; {them}" if docs else them
        c = result["counts"]
        locks = sum(1 for r in self.model.rows if is_lock_file(r.entry))
        other = []
        if c.get("error"):
            other.append(f"{c['error']:,} could not be read")
        if (c.get("skipped") or 0) - locks > 0:
            other.append(f"{c['skipped'] - locks:,} skipped")
        if locks:
            other.append(
                plural(locks, "SOLIDWORKS lock file") + ("" if self.proxy.lock_files else " (hidden)")
            )
        if c.get("link"):
            other.append(plural(c["link"], "link") + " not followed")
        if c.get("placeholder"):
            other.append(plural(c["placeholder"], "cloud placeholder") + " not downloaded")
        if c.get("not_solidworks"):
            other.append(plural(c["not_solidworks"], "file") + " not from SOLIDWORKS")
        # IGES and BREP files while the OCCT backend is off: listed, and the status bar says
        # what opens them
        needs = Counter(r.format or "" for r in rows if needs_extension(r.entry))
        n_needs = sum(needs.values())
        if n_needs:
            names = " and ".join(
                registry.FORMATS[f].name if f in registry.FORMATS else "other" for f in sorted(needs)
            )
            files = "file needs" if n_needs == 1 else "files need"
            other.append(f"{n_needs:,} {names} {files} the OCCT backend extension (Tools > Extensions)")
        unreadable = (c.get("unsupported") or 0) - n_needs
        if unreadable > 0:
            other.append(
                plural(unreadable, "file")
                + " of formats SolidSeas cannot read"
                + ("" if self.proxy.unreadable else " (hidden)")
            )
        if other:
            text += "; " + ", ".join(other)
        text += f"; listed in {result['seconds']:.1f} s"
        if result.get("cancelled"):
            text += " (cancelled)"
        elif result.get("truncated_reason"):
            text += f" (stopped early: {result['truncated_reason'].replace('_', ' ')})"
        return text

    def _folder_selected(self) -> None:
        items = self.tree.selectedItems()
        self.proxy.set_folder((items[0].data(0, _FolderRole) or "") if items else "")

    # -- views -----------------------------------------------------------------------
    def set_view(self, view: str) -> None:
        (self.act_icons_view if view == "icons" else self.act_details_view).setChecked(True)
        if self.folder:
            self.list_stack.setCurrentIndex(2 if view == "icons" else 1)

    def set_lock_files(self, shown: bool) -> None:
        self.change_settings(show_lock_files=shown)

    def _show_unreadable(self, shown: bool) -> None:
        if shown == self.proxy.unreadable:
            return
        self.proxy.set_unreadable(shown)
        self.quick.update_types()  # a type only those files had gets, or loses, its button
        for f in self._folders:
            self._folder_label(f)
        self._auto_columns()
        if self.listing_info is not None and self.listing_info.get("ok"):
            self.status_label.setText(self._counts_text(self.listing_info))

    def _show_lock_files(self, shown: bool) -> None:
        if shown == self.proxy.lock_files:
            return
        self.proxy.set_lock_files(shown)
        self.quick.update_types()
        for f in self._folders:
            self._folder_label(f)
        self._auto_columns()
        if self.listing_info is not None and self.listing_info.get("ok"):
            self.status_label.setText(self._counts_text(self.listing_info))

    def _sort_changed(self, column: int, _order) -> None:
        if column < self.sort_combo.count():
            self.sort_combo.setCurrentIndex(column)

    def select_document(self, name: str) -> bool:
        """Select a document by its path below the opened folder or its file name."""
        row = self.model.find(name)
        if row is None:
            return False
        if self.tree.currentItem() is not self._folders.get(""):
            self.tree.setCurrentItem(self._folders[""])
        self.filter.clear()
        self.quick.reveal(self.model.rows[row].file_type)
        return self._select_row(row)

    def _select_row(self, row: int) -> bool:
        """Make ``row`` of the model the list's selection and show its details now."""
        index = self.proxy.mapFromSource(self.model.index(row, NAME))
        if not index.isValid():
            return False
        self.table.selectionModel().setCurrentIndex(
            index,
            QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows,
        )
        self.table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
        self.icons.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
        self._select_timer.stop()
        self._load_current()
        return True

    def _select_listed(self, rel: str) -> bool:
        """Select the entry at ``rel`` (exactly that path), widening the filters only as
        far as it takes: the name filter is cleared when it hides the entry, and the
        folder shown becomes the nearest folder that holds both it and the entry."""
        row = self.model.find_path(rel)
        if row is None:
            return False
        r = self.model.rows[row]
        if not self.proxy.accepts(r):
            if self.filter.text() and self.filter.text().strip().casefold() not in r.name.casefold():
                self.filter.clear()
            self.quick.reveal(r.file_type)
            shown = self.proxy.folder
            if shown and r.folder != shown and not r.folder.startswith(shown + "/"):
                common: list[str] = []
                for a, b in zip(shown.split("/"), r.folder.split("/") if r.folder else [], strict=False):
                    if a != b:
                        break
                    common.append(a)
                item = self._folders.get("/".join(common), self._folders.get(""))
                if item is not None:
                    self.tree.setCurrentItem(item)
        return self._select_row(row)

    # -- details ---------------------------------------------------------------------
    def _current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        self._select_timer.start()

    @staticmethod
    def _worth_reading(entry: dict[str, Any]) -> bool:
        """A document the listing read, or one it could not read for a reason that
        passes, such as a lock: that one is read again when it is selected."""
        if entry["type"] != "file":
            return False
        if entry["status"] == "ok":
            return True
        return entry["status"] == "error" and bool((entry.get("error") or {}).get("retryable"))

    def _load_current(self) -> None:
        index = self.table.selectionModel().currentIndex()
        entry = self.model.entry(self.proxy.mapToSource(index))
        if entry is None and self._apart is not None:
            return  # a document that is not a row of the list is shown: the list has no selection
        if entry is self._entry:
            if entry is not None and self._details is None:
                self.detailsFinished.emit(self._generation)  # already shown: nothing to wait for
            return
        folder = self.folder or ""
        source = reading.Source(reading.host_path(folder, entry["path"]), folder) if entry else None
        self._show(entry, source)

    def _show(
        self,
        entry: dict[str, Any] | None,
        source: reading.Source | None,
        *,
        apart: dict[str, str] | None = None,
    ) -> None:
        """Read ``entry`` from ``source`` into the details panel: a row of the list, or
        with ``apart`` (its ``where`` and ``note``) a document that is not one."""
        if self._details is not None:
            self._details.cancel()
        self._cancel_mesh()
        self._generation += 1
        self._entry, self._source, self._apart = entry, source, apart
        self._pending_go = None
        self.printer.document_changed()  # a print's result line was about the document before
        self.details_seconds = {}
        if entry is None or source is None:
            self.details.clear("Select a document to see its details.")
            self.where_used.document_shown(None, None, None)
            self._update_actions()
            return
        folder = self.folder or ""
        path = source.path
        if apart is None and not self._worth_reading(entry):
            self.details.show_unread(entry, path)
            self.where_used.document_shown(entry, source, apart, model_format=self._model_format(entry))
            self._update_actions()
            self.detailsFinished.emit(self._generation)
            return
        self.details.begin(entry, path, **(apart or {}))
        model_file = self.details.model_file  # a file of another format: read in the worker pool
        # The index holds every format the list shows; Where Used says when one is not indexed.
        self.where_used.document_shown(entry, source, apart, model_format=self._model_format(entry))
        self._update_actions()
        gen, cache = self._generation, self._cache
        within, nested = source.within, source.nested
        pool, cap = self.models, self.settings.triangle_cap
        outside = not self.settings.references_inside_only

        def sections(cancelled):
            if model_file:
                return reading.read_model(path, folder, pool, within=within, cap=cap, cancelled=cancelled)
            return reading.read_document(
                path, folder, cache=cache, cancelled=cancelled, within=within, nested=nested, outside=outside
            )

        def work(emit, cancelled):
            # After each section the worker waits until the window has shown it. Both
            # sides run Python, and while the worker reads, every call the UI thread
            # makes into Python (a table repaint asks the model hundreds of times)
            # waits for the interpreter lock: building a tab while the next section
            # was read held the window for up to two seconds on a 10,000-instance
            # assembly. Taking turns keeps each side's work off the other's clock.
            shown = threading.Event()
            for name, section in sections(cancelled):
                if name == "preview" and section.get("ok") and section["data"].get("image") is not None:
                    section["data"]["qimage"] = preview_image(section["data"]["image"])
                shown.clear()
                emit((name, section, shown))
                while not shown.wait(0.05):
                    if cancelled():
                        return {"ok": True}
            return {"ok": True}

        job = Job(work)
        self._details = job
        self._start(
            self.work_pool,
            job,
            on_progress=lambda item, g=gen: self._section(g, *item),
            on_finished=lambda _r, g=gen: self._details_done(g),
        )

    def _section(
        self, generation: int, name: str, section: dict[str, Any], shown: threading.Event | None = None
    ) -> None:
        try:
            if generation != self._generation:
                return
            self.details_seconds[name] = section.get("seconds", 0.0)
            if name == "open":
                self.details.open_failed(section)
            else:
                self.details.set_section(name, section)
            self._update_actions()
        finally:
            if shown is not None:
                shown.set()  # the worker may read the next section
        if generation == self._generation and name in ("components", "references", "bom"):
            self._after_section(name)

    def _details_done(self, generation: int) -> None:
        if generation == self._generation:
            self._details = None
            if self._pending_go is not None and self._pending_go[0] == generation:
                # The read ended without the references (cancelled, or the file failed).
                pending, self._pending_go = self._pending_go, None
                self.go_to_component(*pending[1:])
            if self._restore is not None and self._restore[0] == generation and not self._restore[2]:
                self._restore = None
            self.detailsFinished.emit(generation)

    def _configuration_requested(self, configuration: str) -> None:
        source = self._source
        if self._entry is None or source is None or self.folder is None:
            return
        gen, folder = self._generation, self.folder
        self.details.pages["Components"].message(f"Reading configuration {configuration}...")
        self._start(
            self.work_pool,
            Job(
                lambda _emit, _cancelled: reading.read_components(
                    source.path, folder, configuration, within=source.within, nested=source.nested
                )
            ),
            on_finished=lambda section, g=gen: self._section(g, "components", section),
        )
        if self.details.bom_reread(configuration):  # the BOM follows the assembly's configuration
            cache, outside = self._cache, not self.settings.references_inside_only
            self._start(
                self.work_pool,
                Job(
                    lambda _emit, _cancelled: reading.read_bom(
                        source.path,
                        folder,
                        configuration,
                        cache=cache,
                        within=source.within,
                        nested=source.nested,
                        outside=outside,
                    )
                ),
                on_finished=lambda section, g=gen: self._section(g, "bom", section),
            )
            self._update_actions()  # no Export BOM until the new configuration's BOM shows

    # -- going to a component's file -------------------------------------------------
    @property
    def history(self) -> list[Place]:
        """The places Back returns to, the next one last."""
        return list(self._history)

    @property
    def apart(self) -> dict[str, str] | None:
        """``where`` and ``note`` while the details show a document that is not a row
        of the list (one outside the opened folder, or a virtual component), else None."""
        return self._apart

    @property
    def source(self) -> reading.Source | None:
        """Where the document the details show is read from."""
        return self._source

    def go_to_component(
        self,
        key: str,
        mode: str = OPEN,
        parent: str | None = None,
        configuration: str | None = None,
    ) -> None:
        """Go to the file the shown document references as ``key``.

        :data:`.details.OPEN` shows it in the details panel: a file in the list is
        selected there, one outside the opened folder or stored inside the document
        is shown on its own. :data:`.details.SHOW` selects it in the list and gives
        the list the focus. :data:`.details.PROGRAM` opens it in the program the system
        opens it with and :data:`.details.REVEAL` shows it in its folder
        (:meth:`open_externally`), which leaves the panel as it is. An ambiguous file
        asks which one; a missing one says why.
        ``parent`` is the file key of the sub-assembly the instance is in, offered
        when the file is a virtual component stored inside that sub-assembly, and an
        assembly opens in ``configuration``, the one the instance uses, when it
        describes it. Back returns to the document shown now."""
        if self._entry is None or self._source is None or self.folder is None:
            return
        t = self.details.target(key)
        if t.kind == navigate.PENDING:
            if self._details is not None:  # the references are on their way
                self._pending_go = (self._generation, key, mode, parent, configuration)
                self.statusBar().showMessage(f"Finding {t.name} once its location is worked out...")
                return
            t = replace(
                t,
                kind=navigate.UNKNOWN,
                why="The references of this document were not read, so where the file is is not known.",
            )
        if t.kind == navigate.CHOOSE:
            index = self.choose_candidate(t)
            if index is None:
                return
            t = navigate.choose(t, index)
        if not t.openable:
            self._cannot_open(t, parent)
            return
        if mode in (PROGRAM, REVEAL):
            if t.kind == navigate.NESTED:
                self.statusBar().showMessage(f"{t.name} is stored inside the document, not as a file.", 8000)
            else:
                path = t.path if t.kind == navigate.OUTSIDE else reading.host_path(self.folder, t.rel or "")
                self.open_externally(path or "", reveal=mode == REVEAL)
            return
        listed = t.kind == navigate.LISTED and self.model.find_path(t.rel or "") is not None
        if mode == SHOW and not listed:
            why = t.not_listed_reason or "the listing had not reached it or stopped early"
            self.statusBar().showMessage(f"{t.name} is not in the list: {why}.", 8000)
            return
        origin = self._place()
        origin_name = self.details.title.text()
        if listed:
            self._push(origin)
            if not self._select_listed(t.rel or ""):
                self._history.pop()
                self.statusBar().showMessage(f"{t.name} could not be selected in the list.", 8000)
                self._update_actions()
                return
        else:
            back = f"Back (Alt+Left) returns to {origin_name}."
            entry = {"path": t.name, "type": "file", "status": "ok", "doc_type": t.doc_type}
            if t.kind == navigate.NESTED:
                stream = t.nested or ""
                what = {"VirtualComp": "A virtual component", "ImportedComp": "An imported component"}.get(
                    stream.partition("/")[0], "A component"
                )
                source = self._source.inside(stream)
                apart = {
                    "where": f"inside {origin_name}",
                    "note": f"{what}, stored inside {origin_name} ({stream}) rather than as a file of "
                    f"its own. {back}",
                }
            elif t.kind == navigate.OUTSIDE:
                path = t.path or ""
                source = reading.Source(path, os.path.dirname(path))
                entry["path"] = os.path.basename(path)
                apart = {
                    "where": f"outside the opened folder, in {os.path.dirname(path)}",
                    "note": f"Outside the folder you opened, so it is not in the list; shown here on its "
                    f"own, read-only like everything in this viewer. {back}",
                }
            else:  # in the opened folder, but not (yet) a row of the list
                rel = t.rel or ""
                source = reading.Source(reading.host_path(self.folder, rel), self.folder)
                entry["path"] = rel.rpartition("/")[2]
                folder = rel.rpartition("/")[0]
                apart = {
                    "where": f"in {folder}" if folder else "in the opened folder",
                    "note": "In the opened folder, but not in the list: the listing had not reached it "
                    f"or stopped early. {back}",
                }
            self._push(origin)
            self._open_apart(entry, source, apart)
        if mode == OPEN:
            tab = "Preview"
            pane = self.details.preview
            if t.doc_type in ("assembly", "drawing"):
                tab = "Components"
            elif t.kind == navigate.NESTED and not (pane.enabled_3d and pane.preferred == MODEL):
                # A virtual part stores no preview image of its own; the 3D view draws it from
                # the mesh its assembly keeps of it.
                tab = "Overview"
            self.details.tabs.setCurrentIndex(TABS.index(tab))
        else:
            self.list_stack.currentWidget().setFocus()
        used = ""
        if configuration and t.doc_type == "assembly" and self._entry is not None and self._source:
            # Shown in the configuration the instance uses, once its components arrive.
            place = Place(self._entry, self._source, self._apart, configuration=configuration)
            self._restore = [self._generation, place, False]
            if self._details is None:
                self._after_section("components")
        elif configuration and t.doc_type != "drawing":
            # A part shows the configuration it was saved in; say which one the instance uses.
            self.details.set_used_configuration(configuration, origin_name)
            used = f" The instance uses its configuration {configuration}."
        self.statusBar().showMessage(
            f"{navigate.found_text(t)}.{used} Back (Alt+Left) returns to {origin_name}.", 15000
        )
        self._update_actions()

    def go_to_listed(self, rel: str) -> None:
        """Show the document at ``rel`` below the opened folder (a Where Used row): selected
        in the list, or on its own when the list does not hold it. Back returns."""
        if self.folder is None or self._entry is None:
            return
        origin = self._place()
        origin_name = self.details.title.text()
        self._push(origin)
        name = rel.rpartition("/")[2]
        if self.model.find_path(rel) is None or not self._select_listed(rel):
            folder = rel.rpartition("/")[0]
            entry = {"path": name, "type": "file", "status": "ok", "doc_type": None}
            source = reading.Source(reading.host_path(self.folder, rel), self.folder)
            apart = {
                "where": f"in {folder}" if folder else "in the opened folder",
                "note": "In the opened folder, but not in the list: the listing had not reached it or "
                f"stopped early. Back (Alt+Left) returns to {origin_name}.",
            }
            self._open_apart(entry, source, apart)
        self.statusBar().showMessage(f"{name}. Back (Alt+Left) returns to {origin_name}.", 15000)
        self._update_actions()

    def _push(self, place: Place | None) -> None:
        if place is not None:
            self._history.append(place)
            del self._history[:-_HISTORY]

    def _place(self) -> Place | None:
        """The document shown now, as Back would return to it."""
        if self._entry is None or self._source is None:
            return None
        return Place(
            entry=self._entry,
            source=self._source,
            apart=self._apart,
            tab=self.details.tabs.currentIndex(),
            selection=self.details.selection(),
            configuration=self.details.configuration_shown(),
            folder_filter=self.proxy.folder,
            name_filter=self.filter.text(),
            type_filter=self.quick.selected(),
            explode=self.details.preview.explode_value,
            explode_level=self.details.preview.explode_level,
            camera=self.details.preview.camera_state(),
            pick=self.details.preview.highlight,
            view=self.details.preview.view_state(),
        )

    def _open_apart(self, entry: dict[str, Any], source: reading.Source, apart: dict[str, str]) -> None:
        """Show a document that is not a row of the list; the list loses its selection."""
        self._show(entry, source, apart=apart)
        sm = self.table.selectionModel()
        sm.clearSelection()
        sm.clearCurrentIndex()

    def go_back(self) -> bool:
        """Return to the document shown before the last :meth:`go_to_component`, with
        its tab, configuration, selected rows, list filters, explode and the 3D view's
        camera; False when there is none to return to, or its row has left the list."""
        if not self._history:
            return False
        place = self._history.pop()
        generation = self._generation
        if place.rel is not None:
            if self.filter.text() != place.name_filter:
                self.filter.setText(place.name_filter)
            self.quick.set_selected(place.type_filter)
            item = self._folders.get(place.folder_filter)
            if item is not None and self.tree.currentItem() is not item:
                self.tree.setCurrentItem(item)
            if not self._select_listed(place.rel):
                self.statusBar().showMessage(f"{place.rel} is no longer in the list.", 8000)
                self._update_actions()
                return False
        else:
            self._open_apart(place.entry, place.source, place.apart or {})
        pane = self.details.preview
        # Applied once the assembly is drawn again: the explode at once, then the camera as
        # the user left it, so the loop of zooming in, opening a part and coming back
        # does not start from the isometric fit each time.
        pane.set_explode(place.explode, place.explode_level, session=False)
        pane.set_view_state(place.view)
        if self._generation != generation:  # the document is read again: its scene follows
            pane.restore_camera(place.camera, place.configuration)
        self.details.tabs.setCurrentIndex(place.tab)
        self._restore = [self._generation, place, False]
        if self._details is None:  # already shown, nothing is read: restore it now
            for name in ("components", "references"):
                self._after_section(name)
        self.statusBar().clearMessage()
        self._update_actions()
        return True

    @property
    def restoring(self) -> bool:
        """Whether Back is still putting the tab's rows and configuration back."""
        return self._restore is not None and self._restore[0] == self._generation

    @property
    def busy(self) -> bool:
        """Whether the details are still being read, or Back is still restoring them."""
        return self._details is not None or self.restoring or self._pending_go is not None

    def _after_section(self, name: str) -> None:
        """The components or the references of the shown document have arrived: go on
        with a request that waited for the references, and put back what Back
        remembered."""
        pending = self._pending_go
        if name == "references" and pending is not None and pending[0] == self._generation:
            self._pending_go = None
            self.go_to_component(*pending[1:])
            return
        r = self._restore
        if r is None or r[0] != self._generation:
            return
        place: Place = r[1]
        if name == "components" and place.configuration:
            shown = self.details.configuration_shown()
            combo = self.details.config_combo
            known = [combo.itemText(i) for i in range(combo.count())]
            other = shown is not None and shown != place.configuration
            if not r[2] and other and place.configuration in known:
                r[2] = True  # read that configuration again; its section comes back here
                self._configuration_requested(place.configuration)
                return
            if r[2] and shown == place.configuration:
                r[2] = False
        self.details.restore_selection(place.selection)
        if place.pick is not None and self.details.preview.highlight != place.pick:
            self.details.preview.set_pick(place.pick)
        if not r[2] and self._details is None:
            self._restore = None

    def _cannot_open(self, t: navigate.Target, parent: str | None) -> None:
        text = f"{t.name} cannot be opened from here.\n\n{t.why}"
        if t.stored_path:
            text += f"\n\nStored path: {t.stored_path}"
        offer = None
        # A virtual component a sub-assembly stores, or a row read from a sub-assembly's own
        # file (:meth:`.details.DetailsPanel.from_subassembly_file`): that sub-assembly opens.
        if parent and (t.status == "embedded_in_subassembly" or self.details.from_subassembly_file(t.key)):
            offer = "Open the Sub-assembly"
        if self.explain(OPEN_TITLE, text, offer=offer) and parent:
            self.go_to_component(parent, OPEN)

    def explain(self, title: str, text: str, *, offer: str | None = None) -> bool:
        """Say why a file cannot be opened, as plain text; with ``offer``, a button that
        does something about it, and True when it was pressed."""
        box = QMessageBox(QMessageBox.Icon.Information, title, text, QMessageBox.StandardButton.Close, self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        button = box.addButton(offer, QMessageBox.ButtonRole.AcceptRole) if offer else None
        box.exec()
        return button is not None and box.clickedButton() is button

    def choose_candidate(self, t: navigate.Target) -> int | None:
        """Ask which of an ambiguous file's candidates to open; its index, or None."""
        dialog = CandidateDialog(self, t)
        try:
            return dialog.chosen() if dialog.exec() == QDialog.DialogCode.Accepted else None
        finally:
            dialog.deleteLater()

    # -- Open and Show in File Explorer ------------------------------------------------
    def shown_file(self) -> str | None:
        """The file the details show, for Open and Show in File Explorer on the toolbar and
        the File menu; None when nothing is shown, or a document stored inside another."""
        e, source = self._entry, self._source
        if e is None or source is None or e["type"] != "file" or source.nested:
            return None
        return source.path

    def open_shown(self) -> None:
        """Open: the file the details show, in the program the system opens it with."""
        path = self.shown_file()
        if path is not None:
            self.open_externally(path)

    def show_shown(self) -> None:
        """Show in File Explorer: the folder of the file the details show, with it selected."""
        path = self.shown_file()
        if path is not None:
            self.open_externally(path, reveal=True)

    def open_listed(self, rel: str, reveal: bool = False) -> None:
        """Open, or with ``reveal`` Show in File Explorer, for the file at ``rel`` below the
        opened folder (a Where Used row)."""
        if self.folder is not None:
            self.open_externally(reading.host_path(self.folder, rel), reveal=reveal)

    def open_externally(self, path: str, reveal: bool = False) -> bool:
        """Hand the file at ``path`` to the program the system opens it with, or with
        ``reveal`` show its folder with the file selected (:mod:`.opening`, looked up
        each time). The status bar says what was done, or why not; True when it was."""
        name = os.path.basename(path) or path
        why = opening.open_problem(path)
        if why is None:
            try:
                (opening.show_file if reveal else opening.open_file)(path)
            except OSError as exc:
                why = exc.strerror or str(exc)
        if why is not None:
            self.statusBar().showMessage(f"{name} was not {'shown' if reveal else 'opened'}: {why}.", 8000)
            return False
        if reveal:
            self.statusBar().showMessage(f"{name} shown in its folder.", 8000)
        else:
            self.statusBar().showMessage(f"{name} handed to the program that opens it.", 8000)
        return True

    # -- the 3D view's mesh ----------------------------------------------------------
    def _cancel_mesh(self) -> None:
        """Drop the mesh read in progress; if the child process is reading it, it is
        ended, so the next read does not wait behind it."""
        if self._mesh is not None:
            self._mesh.cancel()
            self.mesh_reader.cancel(self._mesh_token)
            self._mesh = self._mesh_token = None

    def _warm_mesh_reader(self) -> None:
        """The 3D view is starting: start the mesh process meanwhile."""
        if not self._closing:
            cap, reader = self.settings.triangle_cap, self.mesh_reader
            self._start(self.mesh_pool, Job(lambda _emit, _cancelled: reader.warm(cap)))

    def _mesh_requested(self) -> None:
        """The Preview tab shows the 3D view and has no mesh: read it in the mesh process,
        an assembly in the configuration the tab asks for, with its component files
        found in the opened folder as the details panel finds them."""
        source = self._source
        pane = self.details.preview
        if self._entry is None or source is None or self.folder is None or self._closing:
            pane.set_mesh_result({"state": "cancelled"})
            return
        self._cancel_mesh()
        gen, cap = self._generation, self.settings.triangle_cap
        token, reader = object(), self.mesh_reader
        assembly, configuration = pane.doc_type == "assembly", pane.configuration
        root, cache_key = self.folder, (self.folder, self._folder_epoch)
        model_file, outside = self.details.model_file, not self.settings.references_inside_only
        job = Job(
            lambda _emit, cancelled: reader.read(
                source.path,
                source.within,
                cap,
                cancelled,
                token=token,
                nested=source.nested,
                assembly=assembly,
                root=root,
                configuration=configuration,
                cache_key=cache_key,
                model_file=model_file,
                outside=outside,
            )
        )
        self._mesh, self._mesh_token = job, token
        self.mesh_result = None
        self._start(self.mesh_pool, job, on_finished=lambda r, g=gen, j=job: self._mesh_done(g, j, r))

    def _mesh_done(self, generation: int, job: Job, result: Any) -> None:
        if job is self._mesh:
            self._mesh = self._mesh_token = None
        if job.cancelled or generation != self._generation:
            return  # a read the window moved on from: its pane state was reset then
        if not isinstance(result, dict) or "state" not in result:  # the worker itself failed
            error = result.get("error") if isinstance(result, dict) else None
            result = {"state": "error", "error": error}
        self.mesh_result = result
        self.details.preview.set_mesh_result(result)
        self.meshFinished.emit(generation)

    @property
    def generation(self) -> int:
        return self._generation

    # -- settings --------------------------------------------------------------------
    def change_settings(self, **changes: Any) -> None:
        """One or more settings from a quick toggle or the code: applied and saved."""
        new = self.settings.but(**changes)
        if new != self.settings:
            self.apply_settings(new)

    def apply_settings(self, new: Settings, *, save: bool = True, initial: bool = False) -> None:
        """Make ``new`` the settings: applied to what is on screen now, where that can
        be done, and saved."""
        old = self.settings
        self.settings = new
        for action, on in (
            (self.act_3d, new.view_3d),
            (self.act_boxes, new.draw_boxes),
            (self.act_view_cube, new.view_cube),
            (self.act_pointer, new.turn_about_pointer),
            (self.act_invert_wheel, new.invert_wheel),
            (self.act_lock_files, new.show_lock_files),
            (self.act_remember, new.remember_session),
            (self.act_print_here, new.print_next_to_model),
            (self.act_all_formats, new.show_all_formats),
            (self.act_unreadable, new.show_unreadable),
            (self.act_print_as_is, new.print_as_is),
            (self.act_mouse[STANDARD], new.mouse_style == STANDARD),
            (self.act_mouse[SOLIDWORKS], new.mouse_style == SOLIDWORKS),
            (self.act_rotation[FREE], new.rotation_mode == FREE),
            (self.act_rotation[TURNTABLE], new.rotation_mode == TURNTABLE),
        ):
            if action.isChecked() != on:
                action.blockSignals(True)
                action.setChecked(on)
                action.blockSignals(False)
        pane = self.details.preview
        pane.set_mouse(new.mouse_style, new.invert_wheel)
        pane.set_boxes(new.draw_boxes)
        if initial or new.rotation_mode != old.rotation_mode:
            pane.set_rotation(new.rotation_mode)
        pane.set_navigation(new.view_cube, new.turn_about_pointer)
        if initial or new.view_3d != old.view_3d:
            if not new.view_3d:
                self._cancel_mesh()
            self.details.set_3d_enabled(new.view_3d)
            if new.view_3d and not initial:
                pane.prepare_view()  # the window turns to OpenGL drawing now, not at the first part
        if new.triangle_cap > old.triangle_cap:
            pane.retry_if_too_large(new.triangle_cap)
        drawings = getattr(self, "drawings", None)
        if drawings is not None and (initial or new.drawings != old.drawings):
            drawings.update_actions()  # New Drawing, Open Drawing and the button shown or not
        if initial or new.thumbnail_size != old.thumbnail_size:
            self._size_icons()
            self.model.set_thumb_size(new.thumbnail_pixels)
        if initial or new.list_view != old.list_view:
            self.set_view(new.list_view)
        self._show_lock_files(new.show_lock_files)
        self._show_unreadable(new.show_unreadable)
        if not initial and new.show_all_formats != old.show_all_formats and self.folder:
            if not self._listing_follows:
                # with or without the other formats: that choice's own saved index, else a listing
                self.open_folder(self.folder)
        if not initial and new.references_inside_only != old.references_inside_only:
            self._references_scope_changed(new.references_inside_only)
        if save:
            self.store.save(new)
            if old.remember_session and not new.remember_session:
                # forget the folder and layout now; the recent folders have a setting of their own
                self.store.save_session(Session(recent=self.store.load_session().recent))
            if new.recent_count != old.recent_count:
                self._fill_recent_menu()

    def _references_scope_changed(self, inside_only: bool) -> None:
        """Look for Referenced Files Only in the Opened Folder was turned on or off. On, Back
        forgets the documents outside the opened folder, which only a look outside it
        found, and one shown from there is closed; the document shown is read again, so its
        references, 3D view and BOM follow the setting."""
        folder = self.folder
        if inside_only and folder is not None:
            self._history = [p for p in self._history if printing.inside(p.source.path, folder)]
        entry, source = self._entry, self._source
        if entry is None or source is None:
            self._update_actions()
            return
        if inside_only and folder is not None and not printing.inside(source.path, folder):
            name = self.details.title.text()
            self._show(None, None)
            self.statusBar().showMessage(
                f"{name} was found outside the opened folder, where referenced files are no longer "
                "looked for.",
                15000,
            )
            return
        self._show(entry, source, apart=self._apart)

    def print_target(self) -> PrintTarget | None:
        """What 3D Print sends: where the part or assembly the details show is read from,
        the opened folder, and the configuration shown (an assembly's on the Components
        tab, a part's that the instance it was opened from uses; None: the active one).
        None when no part or assembly that can be read is shown."""
        e, source = self._entry, self._source
        if e is None or source is None or self.folder is None:
            return None
        summary = self.details.summary
        doc_type = summary.get("doc_type") if summary is not None else reading.doc_type_of(e)
        if doc_type not in ("part", "assembly") or not (e["status"] == "ok" or summary is not None):
            return None
        name = e["path"].rpartition("/")[2]
        if doc_type == "assembly":
            configuration = self.details.configuration_shown()
        else:
            configuration = self.details.used_configuration
        content = self._model_format(e) or "solidworks"  # what it holds, whatever its name says
        return PrintTarget(
            source, self.folder, configuration, name, doc_type=doc_type, content_format=content
        )

    def entry_print_target(self, entry: dict[str, Any]) -> PrintTarget | str | None:
        """What 3D Print from the list's row of ``entry`` sends: the document in its
        active configuration, or as the details show it when they show that row; why
        not, for a part or an assembly the listing could not read; None for any other
        row (a drawing, a lock file, a folder)."""
        if self.folder is None or entry["type"] != "file" or is_lock_file(entry):
            return None
        if reading.doc_type_of(entry) not in ("part", "assembly"):
            return None
        name = entry["path"].rpartition("/")[2]
        if entry is self._entry and self._apart is None:
            shown = self.print_target()
            if shown is not None:
                return shown
        if entry["status"] != "ok":
            path = reading.host_path(self.folder, entry["path"])
            return f"{name} cannot be 3D printed.\n\n{unread_text(entry, path)}"
        source = reading.Source(reading.host_path(self.folder, entry["path"]), self.folder)
        content = entry_format(entry)  # what the listing found it holds, whatever its name says
        return PrintTarget(
            source, self.folder, None, name, doc_type=reading.doc_type_of(entry), content_format=content
        )

    def component_print_target(
        self, key: str, parent: str = "", configuration: str = ""
    ) -> PrintTarget | str | None:
        """What 3D Print from the menu of a row for the referenced file ``key`` sends: the
        file reference resolution found for it, as Go to file finds it, in
        ``configuration`` (the row's; "" for the active one). A virtual component is
        read from inside the document that stores it: the assembly, or for one a
        sub-assembly stores, that sub-assembly (``parent``, the file key of the one its
        row is in, else the one the components section puts it in), where the export
        finds it by its stored name. Why not, when it cannot be found or is no part or
        assembly; None when the question of which file was cancelled."""
        if self._source is None or self.folder is None:
            return None
        got = self.print_source(key, parent)
        if got is None or isinstance(got, str):
            return got
        source, virtual, t = got
        if t.doc_type not in ("part", "assembly"):
            return f"{t.name} is not a part or an assembly, so it cannot be 3D printed."
        return PrintTarget(source, self.folder, configuration or None, t.name, virtual, t.doc_type)

    @staticmethod
    def _cannot_print_text(t: navigate.Target) -> str:
        text = f"{t.name} cannot be 3D printed from here.\n\n{t.why}"
        if t.stored_path:
            text += f"\n\nStored path: {t.stored_path}"
        return text

    def print_source(
        self, key: str, parent: str = "", depth: int = 0, *, ask: bool = True
    ) -> tuple[reading.Source, tuple[str, ...], navigate.Target] | str | None:
        """Where the referenced file ``key`` is read from for 3D Print: its source, the
        stored names of the virtual components to find inside it (:attr:`PrintTarget.virtual`)
        and its target; why not; None when the question of which file was cancelled, or
        without ``ask`` would be asked. A virtual component a sub-assembly stores is
        looked for inside that sub-assembly, found the same way, as deep as
        sub-assemblies stored inside each other go."""
        if self._source is None or self.folder is None:
            return None
        t = self.details.target(key)
        if t.kind == navigate.PENDING:
            if self._details is not None:
                return f"Where {t.name} is is still being worked out. Try again in a moment."
            t = replace(
                t,
                kind=navigate.UNKNOWN,
                why="The references of this document were not read, so where the file is is not known.",
            )
        if t.kind == navigate.CHOOSE:
            index = self.choose_candidate(t) if ask else None
            if index is None:
                return None
            t = navigate.choose(t, index)
        if t.status == "embedded_in_subassembly" and not t.openable and depth < 16:
            above = parent or self.details.parent_of(key)
            got = None
            if above:
                got = self.print_source(above, self.details.parent_of(above), depth + 1, ask=ask)
            if isinstance(got, tuple) and got[2].doc_type == "assembly":
                source, virtual, _sub = got
                return source, (*virtual, t.stored_path or t.name), t
            if isinstance(got, str):
                return (
                    f"{t.name} cannot be 3D printed from here.\n\nIt is a virtual component, stored inside "
                    f"the sub-assembly that uses it, and that sub-assembly cannot be read from here:\n\n{got}"
                )
            if above and got is None:
                return None
        if not t.openable:
            return self._cannot_print_text(t)
        if t.kind == navigate.NESTED:
            source = self._source.inside(t.nested or "")
        elif t.kind == navigate.OUTSIDE:
            path = t.path or ""
            source = reading.Source(path, os.path.dirname(path))
        else:
            source = reading.Source(reading.host_path(self.folder, t.rel or ""), self.folder)
        return source, (), t

    def add_component_print(self, menu: QMenu, text: str, key: str, parent: str, configuration: str) -> None:
        """The 3D Print entry of a row's menu (or the 3D view's, or the legend's) for the
        file ``key``, reading ``text`` (:meth:`.details.DetailsPanel.add_print`). For a
        file that was not found, or whose place is not known, the entry is off with the
        reason, in a few words after it and in full in its tooltip, as Show in folder
        list is; a virtual part of a sub-assembly is looked for inside it when chosen."""
        t = self.details.target(key)
        if t.kind in (navigate.MISSING, navigate.UNKNOWN) and t.status != "embedded_in_subassembly":
            self.printer.add_unavailable(
                menu, text, t.not_listed_reason or "not found", self._cannot_print_text(t)
            )
            return
        what = text.removeprefix("3D Print ")
        if configuration:
            what += f" in configuration {configuration}"
        self.printer.add_action(
            menu, text, lambda: self.component_print_target(key, parent, configuration), what=what
        )

    def add_document_print(self, menu: QMenu, text: str, document: dict[str, Any]) -> None:
        """The 3D view's 3D Print Part, reading ``text``, for a part no row of the
        Components tab stands for, one read from a sub-assembly's own file: the part's own
        document its mesh was read from, in the configuration its instance uses
        (:attr:`.preview.PreviewPane.instance_documents`)."""
        path = str(document.get("path") or "")
        nested = tuple(document.get("nested") or ())
        configuration = document.get("configuration") or None
        name = str(document.get("name") or os.path.basename(path))

        def resolve() -> PrintTarget | None:
            if self.folder is None or not path:
                return None
            within = self.folder if printing.inside(path, self.folder) else os.path.dirname(path)
            source = reading.Source(path, within, nested)
            return PrintTarget(source, self.folder, configuration, name, doc_type="part")  # a part's mesh

        what = name + (f" in configuration {configuration}" if configuration else "")
        self.printer.add_action(menu, text, resolve, what=what)

    def add_missing_print(self, menu: QMenu, text: str, missing: dict[str, Any]) -> None:
        """The 3D view's 3D Print Part, reading ``text``, for a part no row of the Components
        tab stands for that the view drew from what its sub-assembly stores of it, its own
        file not found (:attr:`.preview.PreviewPane.instance_missing`): off, with the reason
        in a few words after it and in full in its tooltip, as a row's entry is for a file
        that was not found."""
        from .mesh3d import UNPRINTABLE_FILE

        reason = str(missing.get("reason") or "missing")
        why = {
            "ambiguous": "Several files could be this one, and none of them can be printed from here.",
            "unreadable": "Its file was found, but it could not be read.",
        }.get(
            reason,
            "No file of that name was found. Searched the opened folder and its subfolders, and the "
            "stored path when it is on a drive of this computer.",
        )
        full = (
            f"{missing.get('name') or ''} cannot be 3D printed from here.\n\n{why} The 3D view draws it "
            "from what its sub-assembly stores of it."
        )
        if missing.get("stored_path"):
            full += f"\n\nStored path: {missing['stored_path']}"
        self.printer.add_unavailable(menu, text, UNPRINTABLE_FILE.get(reason, "not found"), full)

    def add_shown_print(self, menu: QMenu) -> bool:
        """3D Print This Assembly (or This Part) for the 3D view's menu on empty space:
        the document shown, in the configuration shown. False when it cannot be printed."""
        target = self.print_target()
        if target is None:
            return False
        word = "Assembly" if self.details.preview.doc_type == "assembly" else "Part"
        what = target.name + (f" in configuration {target.configuration}" if target.configuration else "")
        self.printer.add_action(menu, f"3D Print This {word}", self.print_target, what=what)
        return True

    def list_menu(self, index: QModelIndex) -> QMenu | None:
        """The context menu of the list's row at ``index`` (of the list's model): Open and
        Show in File Explorer for a file (:meth:`open_externally`), then 3D Print for a
        part or an assembly; None for a folder or a SOLIDWORKS lock file."""
        entry = self.model.entry(self.proxy.mapToSource(index)) if index.isValid() else None
        if entry is None or self.folder is None or entry["type"] != "file" or is_lock_file(entry):
            return None
        path = reading.host_path(self.folder, entry["path"])
        name = entry["path"].rpartition("/")[2]
        menu = relay_status_tips(QMenu(self))
        menu.setToolTipsVisible(True)
        why = opening.open_problem(path, look=False)
        for text, reveal, tip_text in (
            (opening.OPEN_TEXT, False, opening.OPEN_TIP),
            (opening.show_text(), True, opening.show_tip()),
        ):
            action = menu.addAction(text if why is None else f"{text} ({why})")
            action.setToolTip(tip(tip_text))
            action.setEnabled(why is None)
            action.triggered.connect(lambda _on=False, r=reveal: self.open_externally(path, reveal=r))
        if self.entry_print_target(entry) is not None:
            menu.addSeparator()
            self.printer.add_action(
                menu, f"3D Print {name}", lambda: self.entry_print_target(entry), what=name
            )
        return menu

    def _list_menu(self, view: QAbstractItemView, pos: QPoint) -> None:
        menu = self.list_menu(view.indexAt(pos))
        if menu is not None:
            menu.exec(view.viewport().mapToGlobal(pos))
            menu.deleteLater()

    # -- the modeling assistant -------------------------------------------------------
    def ai_config(self) -> Any:
        """Where the AI settings, the keys and the usage live: ``AI.json`` beside this
        window's settings file, or in memory when those are (tests)."""
        if self._ai is None:
            from ..assistant.aisettings import AIConfig, AISettingsStore, path_beside

            path = path_beside(self.store.path) if self.store.path else None
            self._ai = AIConfig(AISettingsStore(path))
        return self._ai

    def open_assistant(self) -> Any:
        """Tools > Modeling Assistant: open the assistant's window, or bring the open one
        forward. Returns it."""
        w = self.assistant
        if w is None:
            from ..assistant.live_sessions import default_sessions
            from ..assistant.window import AssistantWindow

            w = AssistantWindow(sessions=default_sessions(), ai=self.ai_config())
            w.setWindowIcon(self.windowIcon())
            w.closed.connect(lambda w=w: self._assistant_closed(w))
            self.assistant = w
        if w.isMinimized():
            w.showNormal()
        w.show()
        w.raise_()
        w.activateWindow()
        return w

    def _assistant_closed(self, w: Any) -> None:
        if self.assistant is w:
            self.assistant = None
        w.deleteLater()

    def open_ai_settings(self) -> Any:
        """Settings > AI Settings: open the AI settings page, or bring the open one forward.
        Returns it. A saved change rebuilds the open assistant's provider."""
        dialog = self.ai_dialog
        if dialog is None:
            from ..assistant.settings_dialog import AISettingsDialog

            dialog = AISettingsDialog(self, self.ai_config())
            dialog.changed.connect(self._ai_settings_changed)
            dialog.finished.connect(lambda _result, d=dialog: self._ai_settings_closed(d))
            self.ai_dialog = dialog
            dialog.open()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def _ai_settings_changed(self) -> None:
        if self.assistant is not None:
            self.assistant.reload_provider()

    def _ai_settings_closed(self, dialog: Any) -> None:
        if self.ai_dialog is dialog:
            self.ai_dialog = None
        dialog.deleteLater()

    def open_settings(self, page: str | None = None) -> Any:
        """Settings: every setting in one window (:mod:`.settingswindow`), on ``page``; one
        at a time, brought forward on that page when it is open already. Returns it."""
        from .settingswindow import open_settings

        return open_settings(self, page)

    def restore_session(self) -> str | None:
        """Bring back the window layout the last run left, when the settings say to
        remember it; the folder it had open, for :meth:`reopen`."""
        if not self.settings.remember_session:
            return None
        session = self.store.load_session()
        self.quick.set_selected(session.quick_filter)  # kept until the folder is listed
        if session.geometry:
            self.restoreGeometry(QByteArray(session.geometry))
        if (
            session.splitter
            and splitter_state_ok(session.splitter)
            and self.split.restoreState(QByteArray(session.splitter))
        ):
            self._session_restored = True
        return session.folder

    def reopen(self, folder: str) -> None:
        """Open the remembered ``folder`` once a worker has found it still there:
        asking a server that has gone away takes the network's time-out, which the
        window must not wait for. The check has a thread of its own, so a folder
        opened meanwhile lists at once, and then the answer is ignored. Nothing
        happens if the folder is gone."""

        def found(exists: Any) -> None:
            if exists is True and self.folder is None and not self._closing:
                self.open_folder(folder)

        self._start(self.check_pool, Job(lambda _emit, _cancelled: folder_exists(folder)), on_finished=found)

    def save_session(self) -> None:
        if self.settings.remember_session:
            self.store.save_session(
                Session(
                    folder=self.folder,
                    geometry=bytes(self.saveGeometry().data()),
                    splitter=bytes(self.split.saveState().data()),
                    quick_filter=tuple(sorted(self.quick.selected())),
                    recent=self.store.load_session().recent,
                )
            )

    # -- actions ---------------------------------------------------------------------
    def _update_actions(self) -> None:
        e = self._entry
        summary = self.details.summary
        readable = e is not None and e["type"] == "file" and (e["status"] == "ok" or summary is not None)
        if summary is not None:
            doc_type, preview = summary.get("doc_type"), (summary.get("preview") or {}).get("available")
        else:
            doc_type = e.get("doc_type") if e else None
            preview = (e.get("preview") or {}).get("available") if e else None
        if self.details.model_file:  # a model file's image: the one it stores, or one drawn from it
            preview = self.details.preview_png() is not None
        self.act_parasolid.setEnabled(readable and doc_type == "part" and not self.details.model_file)
        target = self.print_target()
        why = self.step_unavailable(target)
        self.act_step.setEnabled(
            doc_type in ("part", "assembly") and not self.step.busy and target is not None and not why
        )
        step_tip = STEP_TIP if not why else sentence(why) + "."
        self.act_step.setToolTip(step_tip)
        self.act_step.setStatusTip(step_tip)
        why = self.convert_unavailable(target)
        self.act_convert.setEnabled(
            doc_type in ("part", "assembly") and not self.convert.busy and target is not None and not why
        )
        convert_tip = CONVERT_TIP if not why else sentence(why) + "."
        self.act_convert.setToolTip(convert_tip)
        self.act_convert.setStatusTip(convert_tip)
        self.act_preview.setEnabled(readable and bool(preview))
        self.act_export_print.setEnabled(self._export_job is None and self.print_target() is not None)
        self.act_bom.setEnabled(readable and self.details.bom_shown() is not None)
        self.act_copy.setEnabled(readable and self.details.summary_json is not None)
        self.act_print.setEnabled(self.printer.busy or self.print_target() is not None)  # busy: Cancel
        shown = self.shown_file()
        openable = shown is not None and opening.open_problem(shown, look=False) is None
        self.act_open_shown.setEnabled(openable)
        self.act_show_shown.setEnabled(openable)
        self.act_reload.setEnabled(self.folder is not None)
        self.act_cancel.setEnabled(self._listing is not None)
        self.act_back.setEnabled(bool(self._history))

    def _model_format(self, entry: dict[str, Any] | None) -> str | None:
        """The registry id of the file of another format the details panel shows; None for a
        SOLIDWORKS document."""
        if entry is None or not self.details.model_file:
            return None
        fmt = entry_format(entry)
        return None if fmt == "solidworks" else fmt

    def step_unavailable(self, target: PrintTarget | None = None) -> str | None:
        """Why File > Export STEP is off for the document shown, said for its tooltip
        (:func:`.printing.step_unavailable`): a drawing, or a part or assembly it cannot
        write; None when it can be exported or nothing that could is shown."""
        target = target if target is not None else self.print_target()
        if target is None:
            e, summary = self._entry, self.details.summary
            shown = summary.get("doc_type") if summary is not None else reading.doc_type_of(e) if e else None
            return printing.step_unavailable(None, "drawing") if shown == "drawing" else None
        return printing.step_unavailable(self._model_format(self._entry), target.doc_type)

    def convert_unavailable(self, target: PrintTarget | None = None) -> str | None:
        """Why File > Convert is off for the document shown, said for its tooltip
        (:func:`.convertfile.unavailable`): a drawing, or a file of a format it does not
        convert; None when it converts or nothing that could is shown."""
        from . import convertfile

        target = target if target is not None else self.print_target()
        if target is None:
            e, summary = self._entry, self.details.summary
            shown = summary.get("doc_type") if summary is not None else reading.doc_type_of(e) if e else None
            return convertfile.unavailable(None, "drawing") if shown == "drawing" else None
        return convertfile.unavailable(self._model_format(self._entry), target.doc_type)

    @staticmethod
    def convert_offered() -> bool:
        """Whether File > Convert is in the File menu: while the OCCT backend can run here,
        the front of its extension (``docs/EXTENSIONS.md`` section 9)."""
        try:
            from solidseas.convert import backend

            return backend("occt").unavailable() is None
        except Exception:
            return False

    def copy_json(self) -> None:
        if self.details.summary_json:
            QApplication.clipboard().setText(self.details.summary_json)
            self.statusBar().showMessage("Summary JSON copied to the clipboard", 4000)

    def _export(self, title: str, *, parasolid: bool) -> None:
        source, folder = self._source, self.folder
        if self._entry is None or source is None or folder is None:
            return
        dialog = ExportDialog(
            self, title, self._last_export_dir, text_option=parasolid, pick=self.pick_folder
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        out_dir = dialog.folder.text().strip()
        if not out_dir:  # the Export button is off while the field is empty
            return
        self._last_export_dir = out_dir
        path, where = source.path, {"within": source.within, "nested": source.nested}
        overwrite, text = dialog.overwrite.isChecked(), dialog.text.isChecked()
        image = self.details.preview_png() if self.details.model_file and not parasolid else None
        pv = ((self.details.sections.get("preview") or {}).get("data")) or {}

        def work(_emit, _cancelled):
            if image is not None:  # a PNG SolidSeas wrote, which the panel already holds
                return {
                    "ok": True,
                    "data": reading.export_image(
                        image,
                        path,
                        folder,
                        out_dir,
                        overwrite=overwrite,
                        width=pv.get("width"),
                        height=pv.get("height"),
                        source=pv.get("source"),
                    ),
                }
            if parasolid:
                return {
                    "ok": True,
                    "data": reading.export_parasolid(
                        path, folder, out_dir, text=text, overwrite=overwrite, **where
                    ),
                }
            return {
                "ok": True,
                "data": reading.export_preview(path, folder, out_dir, overwrite=overwrite, **where),
            }

        self.statusBar().showMessage("Exporting...")
        self._start(
            self.work_pool,
            Job(work),
            on_finished=lambda r: self._export_done(title, r, parasolid, out_dir=out_dir, path=path),
        )

    def _export_done(
        self,
        title: str,
        result: dict[str, Any],
        parasolid: bool,
        *,
        out_dir: str = "",
        path: str | None = None,
    ) -> None:
        self.statusBar().clearMessage()
        warn, info = QMessageBox.Icon.Warning, QMessageBox.Icon.Information
        if not result.get("ok"):
            err = result.get("error") or {}
            if err.get("code") == "output_refused":
                text = f"Nothing was written.\n\n{refusal_text(err)}"
                if out_dir:
                    text += f"\n\nOutput folder: {out_dir}"
                show_message(self, warn, title, text)
            else:
                show_message(self, warn, title, "The export failed.\n\n" + error_message(err, path=path))
            return
        data = result["data"]
        if parasolid:
            written = data["written"]
            if not written:
                show_message(
                    self, info, title, "This document holds no Parasolid bodies, so nothing was written."
                )
                return
            lines = [f"{os.path.basename(w['output'])}  ({reading.size_text(w['bytes'])})" for w in written]
            problems = [f"problem: {p['error']}" for p in data.get("problems") or []]
            text = f"Wrote {plural(len(written), 'file')} to {os.path.dirname(written[0]['output'])}:\n\n"
            show_message(self, info, title, text + "\n".join(lines + problems))
        else:
            show_message(
                self,
                info,
                title,
                f"Wrote the {data['width']} x {data['height']} preview to\n{data['output']}",
            )

    def show_extensions(self) -> None:
        """Tools > Extensions: the Extensions page (:mod:`.extensionsdialog`)."""
        from .extensionsdialog import ExtensionsDialog

        dialog = ExtensionsDialog(self)
        dialog.changed.connect(self.extensions_changed)
        dialog.exec()
        dialog.deleteLater()

    def extensions_changed(self) -> None:
        """The Extensions page switched an extension on or off, or added or removed a
        package. What that changes for IGES and BREP files reaches this window now, not at
        its next start: what the OCCT backend answered is asked again, the worker processes
        that read other formats are started again when what they may start has changed
        (:meth:`.ModelPool.stale`; without the package they still start nothing), and the
        folder is read again when the formats SolidSeas can read have changed, so its rows
        and its saved index follow the switch."""
        from solidseas.convert import backends

        from .savedindex import extension_formats

        for backend in backends().values():
            forget = getattr(backend, "forget", None)
            if forget is not None:
                forget()
        if self._closing:
            return
        self.act_convert.setVisible(self.convert_offered())  # the backend's front follows its switch
        if not self.models.running or self.models.stale():
            # a read on the old workers runs again on the new ones; with none running, a
            # pool that would not start under the old switch is tried again at once
            self.models.restart()
        if self.folder is None or self._formats() == "solidworks":  # no IGES or BREP rows to change
            return
        now = extension_formats()
        if self._listing is not None:
            if now != self._listing_extensions:  # read under the old switch: read it again
                current = self._entry.get("path") if isinstance(self._entry, dict) else None
                self.open_folder(self.folder, select=self._pending_select or current)
            return
        if now != self._shown_extensions:
            self.reindex()

    def edit_bom(self) -> None:
        """Open the BOM editor (:mod:`.bomeditor`) on the BOMs the BOM tab has read, in the
        type the tab shows. It reads nothing again, so it opens at once."""
        from solidseas.bomtable import spec

        from .bomeditor import BomEditor

        section, source, data = self.details.bom_section, self._source, self.details.bom_shown()
        if section is None or source is None or data is None:
            return
        editor = BomEditor(
            section["boms"], source.path, section.get("configuration"), table_spec=spec(data["type"])
        )
        editor.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._bom_editors.append(editor)
        editor.destroyed.connect(
            lambda _o=None, e=editor: self._bom_editors.remove(e) if e in self._bom_editors else None
        )
        editor.show()

    def export_bom(self) -> None:
        """Write the BOM the BOM tab shows (its configuration and type) as CSV or JSON."""
        source, folder, data = self._source, self.folder, self.details.bom_shown()
        if self._entry is None or source is None or folder is None or data is None:
            return
        title = "Export BOM"
        dialog = ExportDialog(
            self, title, self._last_export_dir, text_option=False, pick=self.pick_folder, formats=BOM_FORMATS
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        out_dir = dialog.folder.text().strip()
        if not out_dir:  # the Export button is off while the field is empty
            return
        self._last_export_dir = out_dir
        path, nested = source.path, source.nested
        overwrite, fmt = dialog.overwrite.isChecked(), dialog.format.currentData()

        def work(_emit, _cancelled):
            written = reading.export_bom(
                path, folder, out_dir, data, fmt=fmt, overwrite=overwrite, nested=nested
            )
            return {"ok": True, "data": written}

        self.statusBar().showMessage("Exporting...")
        self._start(
            self.work_pool,
            Job(work),
            on_finished=lambda r: self._bom_export_done(title, r, data, out_dir=out_dir, path=path),
        )

    def _bom_export_done(
        self, title: str, result: dict[str, Any], data: dict[str, Any], *, out_dir: str, path: str
    ) -> None:
        if not result.get("ok"):  # refused or failed: said as every export says it
            self._export_done(title, result, False, out_dir=out_dir, path=path)
            return
        self.statusBar().clearMessage()
        rows = plural(len(data["rows"]), "row")
        show_message(
            self,
            QMessageBox.Icon.Information,
            title,
            f"Wrote the {BOM_TYPE_NAMES[data['type']]} BOM of configuration {data['configuration']} "
            f"({rows}) to\n{result['data']['output']}",
        )

    def export_step(self) -> None:
        """Write what the details panel shows as STEP, to a file the user picks (.stepaction)."""
        self.step.start()

    def convert_file(self) -> None:
        """Write what the details panel shows as IGES, BREP or STEP through the OCCT backend,
        to a file the user picks (.convertaction)."""
        if self.convert_offered():
            self.convert.start()

    def export_for_printing(self) -> None:
        """File > Export for 3D Printing...: the part or assembly shown, as 3D Print makes it,
        written as STL or 3MF into a folder the user chooses, through the write guards, in
        the export's own process (:func:`.printing.export_to_folder`)."""
        target = self.print_target()
        if target is None or self._export_job is not None:
            return
        title = "Export for 3D Printing"
        dialog = ExportDialog(
            self,
            title,
            self._last_export_dir,
            text_option=False,
            pick=self.pick_folder,
            formats=PRINT_FORMATS,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        out_dir = dialog.folder.text().strip()
        if not out_dir:
            return
        self._last_export_dir = out_dir
        source = target.source
        request = {
            "path": source.path,
            "folder": target.folder,
            "fmt": dialog.format.currentData(),
            "out_dir": out_dir,
            "within": source.within,
            "nested": list(source.nested),
            "virtual": list(target.virtual),
            "configuration": target.configuration,
            "name": target.name,
            "overwrite": dialog.overwrite.isChecked(),
        }
        if self.settings.references_inside_only:  # an assembly's files: the opened folder's
            request["outside"] = False

        def work(_emit, cancelled):
            return printing.export_in_process(request, cancelled)

        self.statusBar().showMessage(f"Exporting {target.name} for 3D printing...")
        job = Job(work)
        self._export_job = job
        self._start(
            self.export_pool,
            job,
            on_finished=lambda r, j=job: self._printing_export_done(j, title, r, out_dir, source.path),
        )
        self._update_actions()

    def _printing_export_done(
        self, job: Job, title: str, result: dict[str, Any], out_dir: str, path: str
    ) -> None:
        if job is self._export_job:
            self._export_job = None
        self._update_actions()
        if job.cancelled or self._closing:
            return
        self.statusBar().clearMessage()
        if not result.get("ok"):
            self._export_done(title, result, False, out_dir=out_dir, path=path)
            return
        data = result["data"]
        notes = []
        if not data.get("closed"):
            notes.append("it is not closed, so the slicer may have to repair it")
        if data.get("display_mesh_objects"):
            notes.append("made from the display mesh the file stores, as it has no solid body to use")
        if data.get("skipped"):
            notes.append(f"{plural(data['skipped'], 'instance')} left out")
        text = (
            f"Wrote {data['file']}\n({plural(data['triangles'], 'triangle')}, "
            f"{plural(data['objects'], 'object')}, {reading.size_text(data['bytes'])})"
        )
        if notes:
            text += "\n\nNote: " + "; ".join(notes) + "."
        show_message(self, QMessageBox.Icon.Information, title, text)

    def export_parasolid(self) -> None:
        self._export("Export Parasolid", parasolid=True)

    def export_preview(self) -> None:
        self._export("Export Preview Image", parasolid=False)

    def about(self) -> None:
        QMessageBox.about(
            self,
            "About SolidSeas Viewer",
            f"<h3>SolidSeas Viewer</h3><p>Preview {__version__}</p>"
            f"<p><b>{READ_ONLY}.</b></p>"
            "<p>This is an early preview of the SolidSeas desktop app. It lists a folder of "
            "SOLIDWORKS parts, assemblies and drawings, and of STEP, Parasolid, STL, 3MF, OBJ, PLY, OFF, "
            "glTF, AMF, ACIS and Alibre Design files, and shows what the SolidSeas library reads "
            "from them, without the programs that made them. It contacts the network only for the "
            "modeling assistant, and only the AI provider you set up in AI Settings.</p>"
            "<p>Apache License 2.0.</p>"
            f"<p>Uses Qt {qVersion()} and Qt for Python, copyright The Qt Company Ltd. and other "
            "contributors, under the GNU Lesser General Public License version 3. Help &gt; Licences "
            "shows that licence, the GNU GPL it builds on, and the licences of the other software "
            "SolidSeas carries.</p>"
            f"<p><small>{DISCLAIMER}</small></p>",
        )

    def show_licences(self) -> None:
        """Help > Licences: the licence texts the viewer carries (:mod:`.licences`)."""
        from .licences import LicencesDialog

        dialog = LicencesDialog(self)
        dialog.exec()
        dialog.deleteLater()

    # -- drag and drop, closing --------------------------------------------------
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.open_path(url.toLocalFile())
                break

    def shutdown(self, timeout_ms: int = 5000) -> bool:
        """Cancel what is running, end the mesh process and wait for the workers, at
        most ``timeout_ms`` in all; True when they all stopped."""
        self._closing = True
        self.cancel_listing()
        if self._details is not None:
            self._details.cancel()
        self._cancel_mesh()
        self.mesh_reader.close()
        self.printer.shutdown()  # ends a 3D Print export's process
        self.step.shutdown()  # and an Export STEP's
        self.convert.shutdown()  # and a Convert's
        if self._export_job is not None:
            self._export_job.cancel()  # ends Export for 3D Printing's process
        self.thumbnailer.stop()
        self.where_used.stop()  # the indexer process stops between files
        self.models.close()  # its workers end; a read waiting on one gets an error at once
        pools = (
            self.mesh_pool,
            self.listing_pool,
            self.work_pool,
            self.check_pool,
            self.printer.pool,
            self.step.pool,
            self.convert.pool,
            self.export_pool,
            self.thumbnailer.pool,
            *self.where_used.pools,
        )
        for pool in pools:
            pool.clear()
        deadline = time.monotonic() + timeout_ms / 1000
        done = True
        for pool in pools:
            left = max(0, int((deadline - time.monotonic()) * 1000))
            done = pool.waitForDone(left) and done
        self.thumbnailer.close_cache()
        self._looks_timer.stop()
        self.look_store.flush()  # the looks changed since the last write
        return done

    def closeEvent(self, event) -> None:
        self.save_session()
        if self.assistant is not None:
            self.assistant.close()  # it stops a script it is running
        self.shutdown()
        super().closeEvent(event)
