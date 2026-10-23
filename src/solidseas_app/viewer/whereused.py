"""The Where Used tab, the indexing of the opened folder, and the catalog search in
the name filter.

**Indexing.** When a folder's listing finishes, :class:`WhereUsedController`
starts the indexer process (:mod:`.indexer`), which brings that folder's
catalog (``solidseas.catalog``, in the user's cache folder) up to date in the
background; the status bar shows its progress. Settings > Index Opened Folders
turns it off (it is on unless switched off, kept in the settings file's
``[Index]`` section), and Settings > Clear Index deletes the opened folder's
catalog. Opening another folder stops the scan, which keeps what it committed.

**Where Used.** For the document shown, a read-only query of that catalog runs
in a worker thread and fills the tab: the assemblies that use the document
directly (with the quantity per configuration, unsuppressed and in the BOM),
those that use it inside a sub-assembly (with the chain), the drawings that show
it or an assembly that holds it, references that may name it (ambiguous) and
references to its name that found nothing. A line on top says how complete the
index is. A row goes to its file on a double-click or Enter, as a component's
row does elsewhere in the panel, and Back returns; its right-click menu has Open
and Show in File Explorer (:mod:`.opening`) and Go to file, for a document in the
opened folder. View > Where Used shows the
tab (:attr:`WhereUsedController.act_where_used`, which other menus may add).
The index holds what the list shows: every 3D format SolidSeas reads (STEP,
STL, an Alibre part...) while View > Show > All 3D Files is on, so the tab asks
it about such a file too. It follows an Alibre Design assembly's components, so
an Alibre part shows the assemblies that place it; it follows no reference of
the other formats yet, which the tab says when nothing uses such a file. For a
format SolidSeas cannot read
(IGES...) the tab says it is not indexed, and the index's search never finds
one, though the name filter still matches its name.

**Filter.** Once the folder is indexed, the name filter also keeps the documents
whose part number, description, configuration or property values match the
text (the catalog's search), 200 ms after the last keystroke.

Document text is shown as plain text, as everywhere in the viewer.
"""

import os
from typing import Any

from PySide6.QtCore import QObject, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QStyledItemDelegate,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from solidseas.catalog.record import REFERENCING_FORMATS
from solidseas.formats import registry

from . import indexer as indexer_mod
from . import opening
from .indexer import Indexer
from .menus import relay_status_tips
from .navigate import GO_TEXT
from .wording import ago, plural, tip
from .workers import Job

TAB = "Where Used"
MAX_ROWS = 2000
FILTER_DELAY_MS = 200
FILTER_PAGES = 10  # pages of 500 the name filter asks the catalog for
REL_ROLE = Qt.ItemDataRole.UserRole + 20
ALL = "All configurations"
GROUPS = (
    ("direct", "Used directly by"),
    ("inside", "Used inside"),
    ("drawings", "Drawings"),
    ("possible", "Possibly used by"),
    ("names", "Same name, not found"),
)


# --------------------------------------------------------------------------- work, off the UI thread
def folder_root(cat, folder: str) -> str | None:
    """The id of the catalog's root that is the opened folder (``project`` for the
    viewer's own catalogs; a catalog the command line made may name it otherwise)."""
    from solidseas.resolve.names import fold

    key = fold(os.path.normpath(folder))
    return next((r.id for r in cat.roots if fold(os.path.normpath(r.path)) == key), None)


def where_used_work(db: str, folder: str, path: str, configuration: str | None):
    """A Job's work: the ``where_used`` data of the document at ``path`` (on disk) and the
    catalog's state, read on a read-only connection. ``folder_root`` is the root that is
    the opened folder: rows in it can be opened."""

    def work(_emit, _cancelled) -> dict[str, Any]:
        from solidseas import catalog, model
        from solidseas.errors import NotInCatalogError

        try:
            with catalog.Catalog(db, location="cache", name="", roots=None, mode="r") as cat:
                state = _state(cat)
                own = folder_root(cat, folder)
                try:
                    root, rel = cat.locate(path)
                    data = cat.where_used(root, rel, configuration=configuration)
                except NotInCatalogError:
                    return {"ok": True, "data": None, "state": state, "folder_root": own}
                return {"ok": True, "data": data, "state": state, "folder_root": own}
        except NotInCatalogError:  # the indexer is making the catalog right now: nothing in it yet
            return {"ok": True, "data": None, "state": None, "folder_root": None}
        except Exception as exc:
            return {"ok": False, "error": model.error_info(exc)}

    return work


def _state(cat) -> dict[str, Any]:
    row = cat.con.execute("SELECT count(*) FROM documents").fetchone()
    last = cat.con.execute(
        "SELECT coalesce(finished_utc, started_utc), state FROM scans ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return {
        "documents": row[0],
        "last_scan_utc": last[0] if last else None,
        "last_state": last[1] if last else None,
    }


def filter_work(db: str, folder: str, text: str):
    """A Job's work: the paths below the opened folder whose catalog text matches ``text``
    (the name filter)."""

    def work(_emit, cancelled) -> dict[str, Any]:
        from solidseas import catalog

        paths: set[str] = set()
        try:
            with catalog.Catalog(db, location="cache", name="", roots=None, mode="r") as cat:
                own = folder_root(cat, folder)
                cursor = None
                for _ in range(FILTER_PAGES):
                    if cancelled():
                        break
                    data = cat.search(text, sort="name", limit=500, cursor=cursor)
                    paths.update(r["path"] for r in data["results"] if r["root"] == own)
                    cursor = data["next_cursor"]
                    if cursor is None:
                        break
        except Exception:  # an index not there yet, or text the search refuses: the name alone filters
            return {"ok": True, "text": text, "paths": []}
        return {"ok": True, "text": text, "paths": sorted(paths)}

    return work


# --------------------------------------------------------------------------- the tab
def not_indexed_text(fmt: str) -> str:
    """What Where Used says for a 3D file of the format ``fmt`` (a registry id) that
    SolidSeas cannot read, which the index therefore does not hold."""
    from solidseas.formats import registry

    spec = registry.FORMATS.get(fmt)
    if spec is not None and spec.backend is not None:
        return (
            f"SolidSeas reads {spec.name} files only with the OCCT backend extension, which is not on, so "
            "they are not indexed: Where Used cannot say what uses this one, and the name filter finds "
            "them by name alone."
        )
    return (
        f"SolidSeas cannot read {_format_name(fmt)} files yet, so they are not indexed: Where Used "
        "cannot say what uses this one, and the name filter finds them by name alone."
    )


def not_followed_text(fmt: str) -> str:
    """What Where Used adds when nothing uses a 3D file of the format ``fmt`` (a registry
    id), one of a format whose references the index does not follow yet (anything but
    SOLIDWORKS and Alibre Design, ``REFERENCING_FORMATS``)."""
    return f"The index does not follow references to {_format_name(fmt)} files yet."


def _format_name(fmt: str) -> str:
    from solidseas.formats import registry

    spec = registry.FORMATS.get(fmt)
    return spec.name if spec is not None else fmt


class WhereUsedPane(QWidget):
    """The tab's content: the index's state on top, a configuration box and the tree.
    ``fileRequested`` carries a row's path below the opened folder; ``openRequested`` that
    path and whether to show it in its folder (Show in File Explorer) rather than open it
    (Open); ``configurationChosen`` the configuration asked for ("" for all of them)."""

    fileRequested = Signal(str)
    openRequested = Signal(str, bool)
    configurationChosen = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setContentsMargins(6, 4, 6, 4)
        self.config = QComboBox()
        self.config.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.config.activated.connect(self._config_chosen)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.status, 1)
        top.addWidget(self.config)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(6)
        self.tree.setHeaderLabels(["File", "Configuration", "Qty", "Unsuppressed", "In BOM", "Notes"])
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)  # paths keep both ends
        self._notes_delegate = NotesDelegate(self.tree)  # the notes read as text: cut at the end
        self.tree.setItemDelegateForColumn(NOTES_COLUMN, self._notes_delegate)
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.tree.header().setStretchLastSection(True)
        self.tree.headerItem().setToolTip(
            0,
            tip(
                "Double-click a document or press Enter to go to it. Back (Alt+Left) returns. Right-click "
                f"for {opening.OPEN_TEXT} (in its own program), {opening.show_text()} and {GO_TEXT}."
            ),
        )
        self.tree.itemActivated.connect(self._activated)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addWidget(self.tree, 1)
        self.data: dict[str, Any] | None = None
        self.rows: dict[str, list[QTreeWidgetItem]] = {}

    def _config_chosen(self, index: int) -> None:
        text = self.config.itemText(index)
        self.configurationChosen.emit("" if index == 0 else text)

    def _activated(self, item: QTreeWidgetItem, _column: int) -> None:
        rel = item.data(0, REL_ROLE)
        if rel:
            self.fileRequested.emit(rel)

    def row_menu(self, item: QTreeWidgetItem | None) -> QMenu | None:
        """The right-click menu of a document's row: Open and Show in File Explorer, then
        Go to file (what a double-click does, in bold); off, with why, for a document in
        another indexed folder. None for a group's title row."""
        if item is None or item.parent() is None:
            return None
        rel = item.data(0, REL_ROLE) or ""
        why = None if rel else "not in the opened folder"
        menu = relay_status_tips(QMenu(self))
        menu.setToolTipsVisible(True)
        for text, reveal, tip_text in (
            (opening.OPEN_TEXT, False, opening.OPEN_TIP),
            (opening.show_text(), True, opening.show_tip()),
        ):
            action = menu.addAction(text if why is None else f"{text} ({why})")
            action.setToolTip(tip(tip_text))
            action.setEnabled(why is None)
            action.triggered.connect(lambda _on=False, r=reveal: self.openRequested.emit(rel, r))
        menu.addSeparator()
        go = menu.addAction(GO_TEXT if why is None else f"{GO_TEXT} ({why})")
        f = go.font()
        f.setBold(True)
        go.setFont(f)
        go.setEnabled(why is None)
        go.triggered.connect(lambda: self.fileRequested.emit(rel))
        return menu

    def _context_menu(self, pos) -> None:
        menu = self.row_menu(self.tree.itemAt(pos))
        if menu is not None:
            menu.exec(self.tree.viewport().mapToGlobal(pos))
            menu.deleteLater()

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def set_configurations(self, names: list[str], current: str | None) -> None:
        self.config.blockSignals(True)
        self.config.clear()
        self.config.addItem(ALL)
        self.config.addItems(names)
        if current and current in names:
            self.config.setCurrentIndex(names.index(current) + 1)
        self.config.setVisible(bool(names))
        self.config.blockSignals(False)

    def clear(self) -> None:
        self.data = None
        self.rows = {}
        self.tree.clear()

    def show_data(self, data: dict[str, Any], own: str | None) -> None:
        """Fill the tree from ``where_used`` data; rows in root ``own`` (the opened folder)
        go to their document."""
        self.clear()
        self.data = data
        groups: dict[str, list[QTreeWidgetItem]] = {key: [] for key, _ in GROUPS}
        shown = 0
        for u in data["users"]:
            if shown >= MAX_ROWS:
                break
            if u["relation"] in ("drawing_view", "drawing_of_assembly"):
                key = "drawings"
            elif u["depth"] == 1 and u["relation"] == "component":
                key = "direct"
            else:
                key = "inside"
            via = " > ".join(v["name"] if v["stored"] else v["path"] or v["name"] for v in u["via"])
            notes = [w["message"] for w in u["warnings"]]
            if via:
                notes.insert(0, f"through {via}")
            rows = u["uses"] or [None]
            for use in rows:
                if use is None:
                    views = ", ".join(
                        f"{v['sheet']} / {v['view']}"
                        + (f" ({v['configuration']})" if v["configuration"] else "")
                        for v in u["views"]
                    )
                    values = [u["path"], "", "", "", "", "; ".join([views, *notes] if views else notes)]
                else:
                    cfg = use["user_configuration"] or ""
                    if use["configuration"]:
                        cfg = f"{cfg} (uses {use['configuration']})" if cfg else use["configuration"]
                    values = [
                        u["path"],
                        cfg,
                        str(use["instances"]),
                        str(use["unsuppressed"]),
                        str(use["in_bom"]),
                        "; ".join(notes),
                    ]
                item = QTreeWidgetItem(values)
                _notes_tip(item)
                if u["root"] == own:
                    item.setData(0, REL_ROLE, u["path"])
                    item.setToolTip(0, tip(u["path"]))
                else:
                    item.setToolTip(0, tip(f"{u['path']}, in the indexed folder {u['root']}"))
                groups[key].append(item)
                shown += 1
        for p in data["possible"]:
            item = QTreeWidgetItem(
                [p["path"], "", "", "", "", f"an ambiguous reference to {p['file_name'] or p['key']}"]
            )
            _notes_tip(item)
            if p["root"] == own:
                item.setData(0, REL_ROLE, p["path"])
            groups["possible"].append(item)
        for m in data["name_matches"]:
            stored = m["stored_path"] or m["file_name"] or m["key"]
            item = QTreeWidgetItem([m["path"], "", "", "", "", f"{m['status']}: {stored}"])
            if m["root"] == own:
                item.setData(0, REL_ROLE, m["path"])
            _notes_tip(item)
            groups["names"].append(item)
        tops = []
        for key, title in GROUPS:
            items = groups[key]
            if not items:
                continue
            top = QTreeWidgetItem([f"{title} ({len(items):,})"])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            top.setFirstColumnSpanned(False)
            top.addChildren(items)
            tops.append(top)
            self.rows[key] = items
        self.tree.addTopLevelItems(tops)
        for top in tops:
            top.setExpanded(True)
        for c in range(1, 5):
            self.tree.resizeColumnToContents(c)
        self.tree.setColumnWidth(0, max(self.tree.columnWidth(0), 260))


NOTES_COLUMN = 5


class NotesDelegate(QStyledItemDelegate):
    """The Notes column: notes are sentences, so one too long for the column is cut at its
    end, where the tree cuts a path in the middle to keep both of its ends."""

    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        option.textElideMode = Qt.TextElideMode.ElideRight


def _notes_tip(item: QTreeWidgetItem) -> None:
    """The whole note of a row as its Notes cell's tooltip, for one the column cuts."""
    text = item.text(NOTES_COLUMN)
    if text:
        item.setToolTip(NOTES_COLUMN, tip(text))


# --------------------------------------------------------------------------- the controller
class WhereUsedController(QObject):
    """Indexing of the opened folder, the Where Used tab's queries and the catalog part of
    the name filter, for one window (see the module notes)."""

    indexFinished = Signal(object)  # the indexer's result
    shown = Signal(object)  # the where-used result shown (for tests)

    def __init__(self, window) -> None:
        super().__init__(window)
        from solidseas import catalog

        self.w = window
        self._catalog = catalog
        self.indexer = Indexer()
        self.pool = QThreadPool(self)  # the indexing job, which waits on the indexer process
        self.pool.setMaxThreadCount(1)
        self.query_pool = QThreadPool(self)  # where-used and filter queries, quick and read-only
        self.query_pool.setMaxThreadCount(1)
        self.enabled = indexer_mod.load_enabled(window.store)
        self.folder: str | None = None
        self.db: str | None = None
        self.job: Job | None = None
        self.progress: dict[str, Any] | None = None
        self.result: dict[str, Any] | None = None
        self._rel: str | None = None
        self._path: str | None = None
        self._configuration: str | None = None
        self._generation = 0
        self._filter_text = ""
        self.pane: WhereUsedPane = window.details.where_used
        self.pane.fileRequested.connect(window.go_to_listed)
        self.pane.openRequested.connect(window.open_listed)
        self.pane.configurationChosen.connect(self._configuration_chosen)

        self.act_where_used = QAction("&Where Used", window)
        self.act_where_used.setShortcut(QKeySequence("Ctrl+Shift+U"))
        self.act_where_used.setStatusTip("Show the assemblies and drawings that use the selected document")
        self.act_where_used.triggered.connect(self.show_tab)
        self.act_index = QAction("&Index Opened Folders", window, checkable=True)
        self.act_index.setChecked(self.enabled)
        self.act_index.setStatusTip(
            "Keep an index of each folder you open in your cache folder, for Where Used and the filter"
        )
        self.act_index.toggled.connect(self.set_enabled)
        self.act_clear = QAction("&Clear Index...", window)
        self.act_clear.setStatusTip("Delete the index of the opened folder from your cache folder")
        self.act_clear.triggered.connect(self.clear_index)
        window.view_menu.addSeparator()
        window.view_menu.addAction(self.act_where_used)
        window.settings_menu.addSeparator()
        window.settings_menu.addAction(self.act_index)
        window.settings_menu.addAction(self.act_clear)

        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        window.statusBar().addPermanentWidget(self.label)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(FILTER_DELAY_MS)
        self.timer.timeout.connect(self._filter_now)
        window.filter.textChanged.connect(lambda _t: self.timer.start())
        self._show_state()

    # -- state ----------------------------------------------------------------------
    def status_text(self) -> str:
        if not self.enabled:
            return "Index off"
        if self.folder is None:
            return ""
        if self.job is not None:
            p = self.progress or {}
            phase, done, total = p.get("phase"), p.get("done", 0), p.get("total", 0)
            if phase == "read" and total:
                return f"Indexing: reading {done:,} of {total:,} documents..."
            if phase == "resolve" and total:
                return f"Indexing: resolving references, {done:,} of {total:,}..."
            if phase == "hash" and total:
                return f"Indexing: hashing {done:,} of {total:,} files..."
            if phase == "walk":
                return f"Indexing: {plural(done, 'document')} found..."
            return "Indexing..."
        if self.result is not None:
            if self.result.get("ok"):
                data = self.result.get("data") or {}
                c = data.get("counts") or {}
                return f"Indexed {plural(c.get('seen', 0), 'document')}"
            if self.result.get("stopped"):
                return "Indexing stopped"
            return "Indexing failed"
        return ""

    def _show_state(self) -> None:
        text = self.status_text()
        self.label.setText(text)
        self.label.setVisible(bool(text))
        self.act_clear.setEnabled(self.folder is not None and self.db is not None and os.path.exists(self.db))
        self.w.filter.setPlaceholderText(
            "Filter by name, part number or property"
            if self.db and os.path.exists(self.db)
            else "Filter by name"
        )

    # -- the window's events --------------------------------------------------------
    def folder_opened(self, folder: str) -> None:
        """A folder is being listed: stop indexing another one."""
        if self.job is not None:
            self.job.cancel()
            self.indexer.stop()
        self.job = None
        self.progress = self.result = None
        self.folder = folder
        try:
            self.db = self._catalog.locate(folder)[0]
        except Exception:
            self.db = None
        self.w.proxy.set_also(())
        self._show_state()

    def folder_listed(self, result: dict[str, Any]) -> None:
        # a saved index shown again is not a new listing: the catalog was brought up to
        # date when it was read, and is again at the next re-index
        if result.get("saved"):
            return
        if self.enabled and result.get("ok") and self.folder is not None and not self.w._closing:
            self.start()

    def start(self) -> None:
        """Index the opened folder now (in the background)."""
        folder = self.folder
        if folder is None or self.job is not None:
            return
        indexer = self.indexer
        formats = "all" if self.w.settings.show_all_formats else "solidworks"  # what the list shows

        def work(emit, cancelled):
            return indexer.run(folder, emit, cancelled, formats=formats)

        job = Job(work)
        self.job = job
        self.progress = None
        self.w._start(
            self.pool,
            job,
            on_progress=lambda message, j=job: self._progress(j, message),
            on_finished=lambda result, j=job: self._finished(j, result),
        )
        self._show_state()

    def _progress(self, job: Job, message: dict[str, Any]) -> None:
        if job is not self.job:
            return
        if "progress" in message:
            first = self.progress is None
            self.progress = message["progress"]
            if first and self._rel is not None:
                self.query()  # the first rows are there: show what the index knows so far
        self._show_state()
        if self._rel is not None:
            self.pane.set_status(self.tab_status())

    def _finished(self, job: Job, result: dict[str, Any]) -> None:
        if job is not self.job:
            return
        self.job = None
        self.result = result
        if result.get("ok") and result.get("db"):
            self.db = result["db"]
        self._show_state()
        self.query()
        if self.w.filter.text().strip():
            self._filter_now()
        self.indexFinished.emit(result)

    def document_shown(
        self, entry: dict[str, Any] | None, source, apart, *, model_format: str | None = None
    ) -> None:
        """The details panel shows another document: ask the index who uses it, of a 3D
        file of another format (``model_format``, its registry id) too. One of a format
        SolidSeas cannot read is not indexed, which the tab says."""
        self._rel = None
        self._configuration = None
        page = self.w.details.pages[TAB]
        self.pane.clear()
        if entry is None or source is None:
            return
        if model_format is not None and not registry.readable(model_format):
            page.message(not_indexed_text(model_format))
            return
        if source.nested:
            page.message(
                "This component is stored inside its assembly, not as a file of its own: Where Used "
                "covers files."
            )
            return
        self._rel = source.path  # a document outside the indexed folders is "not in the index"
        self._path = source.path
        self.pane.set_configurations([], None)
        self.query()

    def _configuration_chosen(self, configuration: str) -> None:
        self._configuration = configuration or None
        self.query()

    def tab_status(self, state: dict[str, Any] | None = None, data: dict[str, Any] | None = None) -> str:
        if not self.enabled:
            return "Indexing of opened folders is off: turn on Settings > Index Opened Folders."
        if self.job is not None:
            return self.status_text() + " What the index holds so far is shown."
        if state is not None and state.get("documents"):
            text = f"Indexed {plural(state['documents'], 'document')}, {ago(state.get('last_scan_utc'))}."
            if data is not None and not data.get("complete"):
                text += " Some files still wait to be read or resolved."
            for warning in (data or {}).get("warnings") or []:  # an open set: each says what it means
                message = warning["message"]
                text += f" {message[:1].upper()}{message[1:]}."
            if data is not None and data.get("truncated"):
                text += " Only the nearest uses are listed."
            return text + " Uses within the indexed folders."
        return ""

    def query(self) -> None:
        """Run the where-used query of the document shown, if the index is there."""
        rel = self._rel
        page = self.w.details.pages[TAB]
        if rel is None:
            return
        if not self.enabled and not (self.db and os.path.exists(self.db)):
            page.message("Indexing of opened folders is off: turn on Settings > Index Opened Folders.")
            return
        if not self.db or not os.path.exists(self.db):
            page.message(
                "The opened folder is being indexed..."
                if self.job is not None
                else "The opened folder is not indexed."
            )
            return
        self._generation += 1
        generation = self._generation
        job = Job(where_used_work(self.db, self.folder or "", self._path or "", self._configuration))
        self.w._start(
            self.query_pool, job, on_finished=lambda result, g=generation: self._answer(g, rel, result)
        )

    def _answer(self, generation: int, rel: str, result: dict[str, Any]) -> None:
        if generation != self._generation or rel != self._rel:
            return
        page = self.w.details.pages[TAB]
        if not result.get("ok"):
            from .wording import error_message

            page.message("The index could not be read.\n\n" + error_message(result.get("error")), error=True)
            self.shown.emit(result)
            return
        data, state = result.get("data"), result.get("state")
        if data is None:
            page.message(
                "This file is not in the index yet."
                if self.job is not None
                else "This file is not in the index."
            )
            self.shown.emit(result)
            return
        self.pane.set_configurations(data["target"]["configurations"], data["configuration"])
        self.pane.show_data(data, result.get("folder_root"))
        status = self.tab_status(state, data)
        if not data["users"] and not data["possible"] and not data["name_matches"]:
            status = (status + " No document in the indexed folders uses this file.").strip()
            fmt = data["target"].get("format")
            if fmt is not None and fmt not in REFERENCING_FORMATS:
                status += " " + not_followed_text(fmt)
        self.pane.set_status(status)
        page.show_content()
        self.shown.emit(result)

    # -- the name filter ------------------------------------------------------------
    def _filter_now(self) -> None:
        text = self.w.filter.text().strip()
        self._filter_text = text
        if not text or not self.db or not os.path.exists(self.db):
            self.w.proxy.set_also(())
            return
        job = Job(filter_work(self.db, self.folder or "", text))
        self.w._start(self.query_pool, job, on_finished=self._filtered)

    def _filtered(self, result: dict[str, Any]) -> None:
        if result.get("text") != self._filter_text or self.w.filter.text().strip() != self._filter_text:
            return
        self.w.proxy.set_also(result.get("paths") or ())

    # -- actions --------------------------------------------------------------------
    def show_tab(self) -> None:
        self.w.details.tabs.setCurrentIndex(self.w.details.tabs.indexOf(self.w.details.pages[TAB]))

    def set_enabled(self, on: bool) -> None:
        if on == self.enabled:
            return
        self.enabled = on
        indexer_mod.save_enabled(self.w.store, on)
        if on and self.w.listing_info is not None:
            self.start()
        elif not on and self.job is not None:
            self.job.cancel()
            self.indexer.stop()
        self._show_state()
        self.query()

    def clear_index(self) -> None:
        """Delete the opened folder's index (asked first)."""
        if self.folder is None:
            return
        answer = QMessageBox.question(
            self.w,
            "Clear Index",
            "Delete the index of the opened folder from your cache folder? The files themselves are "
            "not touched; the next indexing reads them again.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.clear_now()

    def clear_now(self) -> bool:
        if self.job is not None:
            self.job.cancel()
            self.indexer.stop()
            self.pool.waitForDone(int((3 + 1) * 1000))
        try:
            self._catalog.clear(roots=self.folder)
        except Exception as exc:
            from solidseas import model

            from .wording import error_message

            self.w.statusBar().showMessage(
                "The index could not be cleared: " + error_message(model.error_info(exc)), 10000
            )
            return False
        self.result = None
        self.w.proxy.set_also(())
        self._show_state()
        self.query()
        self.w.statusBar().showMessage("The index of the opened folder was deleted.", 8000)
        return True

    def stop(self) -> None:
        """Stop indexing (the window is closing); the window waits for :attr:`pools`."""
        if self.job is not None:
            self.job.cancel()
        self.indexer.stop()

    @property
    def pools(self) -> tuple[QThreadPool, QThreadPool]:
        return self.pool, self.query_pool


__all__ = ["TAB", "WhereUsedController", "WhereUsedPane", "ago", "filter_work", "where_used_work"]
