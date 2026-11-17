"""The Projects view: the library's projects, most recently worked on first, with a
quick search, in place of the folder tree.

The window's left pane has two views, chosen with the **Projects** and **Folders**
buttons above it or View > Projects and View > Folders: this one, and the folder tree.
The window remembers which one was showing.

The list holds every project of the library the opened folder is in
(``Vault.project_activity``): its name, its section (Projects, Customers, Archive and so
on), when it was last worked on (the newest change to one of its CAD files; a
check-in does not count, since checking in the whole library would make every project
look recent) and how many of its files have changes not checked in. The newest are at the top.

Typing in the search box narrows the list as each letter is typed
(``solidseas.pdm.search``): the words may come in any order and may match the project's
name, its customer or its section, and letters may be left out ("brkt" finds
"Bracket"). Enter opens the best match. Down moves from the box into the list.

Clicking a project, or Enter on it, opens its folder in the window, so the file list
shows its files. The library stays the same, so the list stays. Outside a library the
view says so.

The projects are read by a ``solidseas pdm projects --json`` process of their own
(this program with ``--cli`` when frozen), which looks at every file with a stat only,
waited for in a thread of its own. A child process does not share the window's Python
lock with the listing and the index, nor wait behind the PDM menu's lookups, so the
list fills about as fast as the command line answers. If the process cannot be
started or its answer cannot be read, the same work runs in that thread instead.
Refresh reads them again; so does opening a folder in another library.
"""

import os
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .reading import time_text
from .wording import ago, error_message, plural, tip

SEARCH_HINT = "Search projects and customers"
SEARCH_TIP = (
    "Type part of a project's name, its customer or its section. Words can come in any order, "
    "and letters can be left out. Enter opens the best match"
)
REFRESH_TIP = "Look at the projects' files again"
OUTSIDE_TEXT = "Open a folder in a PDM library to list its projects here."
LOOKING_TEXT = "Looking at the projects..."
COLUMNS = ("Project", "Section", "Last worked on", "Not checked in")
NAME, SECTION, WHEN, PENDING = range(4)
PATH_ROLE = Qt.ItemDataRole.UserRole


CHILD_TIMEOUT = 600.0  # seconds; a library on a slow share can take minutes


def _in_child(library: str) -> list[dict[str, Any]] | None:
    """The projects as ``solidseas pdm projects --json`` lists them, from a child
    process; None when it could not be started or answered with something else."""
    import json
    import subprocess
    import sys

    from .connectorsvc import program

    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        done = subprocess.run(
            [*program(), "pdm", "projects", library, "--json"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=CHILD_TIMEOUT,
            check=False,
            **kwargs,
        )
        env = json.loads(done.stdout.decode("utf-8"))
        rows = env["data"]["projects"]["projects"] if env.get("ok") else None
    except Exception:
        return None
    if not isinstance(rows, list):
        return None
    for r in rows:
        r.pop("score", None)  # a search's; the view searches for itself
    return rows


def activity_work(library: str, *, child: bool = True):
    """A Job's work: every project of the library with when it was last worked on, as
    data (``ProjectActivity.data``), from a child process when ``child`` and it
    answers, else in this thread."""

    def work(_emit, cancelled) -> dict[str, Any]:
        from solidseas import model, pdm

        rows = _in_child(library) if child else None
        if rows is not None:
            return {"ok": True, "kind": "projects", "library": library, "projects": rows}
        try:
            vault = pdm.open(library)
            rows = [a.data() for a in vault.project_activity(cancelled)]
        except Exception as exc:
            return {"ok": False, "kind": "projects", "library": library, "error": model.error_info(exc)}
        return {"ok": True, "kind": "projects", "library": library, "projects": rows}

    return work


def _key(row: dict[str, Any]):
    from datetime import datetime

    when = row.get("last_activity_utc")
    dt = datetime.fromisoformat(when.replace("Z", "+00:00")) if when else None
    return row["name"], row["section"], row["path"], dt


class ProjectsPane(QWidget):
    """The Projects view. ``projectChosen`` carries the chosen project's folder."""

    projectChosen = Signal(str)

    def __init__(self, controller: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.library: str | None = None
        self.rows: list[dict[str, Any]] = []
        self.loaded = False
        self._generation = 0
        self._jobs: set[Any] = set()  # kept until they answer, as the Job objects must be

        self.search = QLineEdit()
        self.search.setPlaceholderText(SEARCH_HINT)
        self.search.setToolTip(tip(SEARCH_TIP))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._fill)
        self.search.returnPressed.connect(self._open_first)
        self.search.installEventFilter(self)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setToolTip(tip(REFRESH_TIP))
        self.refresh_button.clicked.connect(self.refresh)
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.refresh_button)

        self.list = QTreeWidget()
        self.list.setHeaderLabels(list(COLUMNS))
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setAlternatingRowColors(True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.itemClicked.connect(self._chosen)
        self.list.itemActivated.connect(self._chosen)
        header = self.list.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(NAME, QHeaderView.ResizeMode.Stretch)
        for c in (SECTION, WHEN, PENDING):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)

        self.note = QLabel(OUTSIDE_TEXT)
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        self.note.setWordWrap(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(bar)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.note)
        self._show_state()

    # -- which library -------------------------------------------------------------------
    def set_library(self, library: str | None) -> None:
        """Follow the library the opened folder is in: read its projects when it is a
        new one (only while the view shows, else when it is next shown)."""
        if library is not None and self.library is not None:
            if os.path.normcase(os.path.abspath(library)) == os.path.normcase(os.path.abspath(self.library)):
                return
        self.library = library
        self.rows = []
        self.loaded = False
        self._generation += 1
        self._fill()
        self._show_state()
        if library is not None and self.isVisible():
            self.refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.library is not None and not self.loaded:
            self.refresh()

    def refresh(self) -> None:
        """Read the library's projects again, in a lookup thread."""
        if self.library is None:
            return
        self._generation += 1
        g = self._generation
        library = self.library
        self.note.setText(LOOKING_TEXT)
        self.note.show()
        self.refresh_button.setEnabled(False)

        def done(result: dict[str, Any]) -> None:
            if g != self._generation:
                return
            self.refresh_button.setEnabled(True)
            self.loaded = True
            if not result.get("ok"):
                self.rows = []
                self._fill()
                self.note.setText("The projects could not be read. " + error_message(result.get("error")))
                self.note.show()
                return
            self.rows = result["projects"]
            self._fill()
            self._show_state()

        self._start(activity_work(library), done)

    def _start(self, work, on_finished) -> None:
        """Run ``work`` in a daemon thread of its own: it only reads, so a closing window
        does not wait for it, and an answer that comes after is ignored."""
        import threading

        from .workers import Job

        job = Job(work)
        self._jobs.add(job)

        def finished(result: Any) -> None:
            self._jobs.discard(job)
            if not getattr(self.controller, "stopped", False):
                on_finished(result)

        job.signals.finished.connect(finished)

        def run() -> None:
            try:
                job.run()
            except RuntimeError:  # the window, and the job's signals, are gone
                pass

        threading.Thread(target=run, name="SolidSeas projects", daemon=True).start()

    # -- the list --------------------------------------------------------------------------
    def shown_paths(self) -> list[str]:
        """The projects listed, top to bottom, as paths below the library."""
        return [self.list.topLevelItem(i).data(NAME, PATH_ROLE) for i in range(self.list.topLevelItemCount())]

    def _fill(self, *_args: Any) -> None:
        from solidseas.pdm.search import search

        self.list.clear()
        if not self.rows:
            return
        found = search(self.rows, self.search.text(), key=_key)
        for f in found:
            row = f.entry
            when = row.get("last_activity_utc")
            pending = row.get("pending") or 0
            item = QTreeWidgetItem(
                [
                    row["name"],
                    row["section"],
                    ago(when) if when else "never",
                    f"{pending:,}" if pending else "",
                ]
            )
            item.setData(NAME, PATH_ROLE, row["path"])
            item.setToolTip(NAME, tip(row["path"]))
            if when:
                item.setToolTip(WHEN, tip(time_text(when)))
            item.setToolTip(PENDING, tip(plural(pending, "file") + " changed since the last check-in"))
            item.setTextAlignment(PENDING, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if row.get("archived"):
                for c in range(len(COLUMNS)):
                    item.setForeground(c, self.palette().placeholderText())
            self.list.addTopLevelItem(item)
        if self.loaded:
            self._show_state()

    def _show_state(self) -> None:
        if self.library is None:
            self.note.setText(OUTSIDE_TEXT)
            self.note.show()
        elif not self.loaded:
            self.note.setText(LOOKING_TEXT)
            self.note.show()
        elif self.search.text().strip() and self.list.topLevelItemCount() == 0:
            self.note.setText("No project matches. Try fewer letters.")
            self.note.show()
        else:
            shown, total = self.list.topLevelItemCount(), len(self.rows)
            text = plural(total, "project") if shown == total else f"{shown:,} of {plural(total, 'project')}"
            self.note.setText(text)
            self.note.show()
        self.search.setEnabled(self.library is not None)
        self.refresh_button.setEnabled(self.library is not None)

    def _chosen(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        rel = item.data(NAME, PATH_ROLE)
        if self.library is None or not rel:
            return
        self.projectChosen.emit(os.path.join(self.library, *rel.split("/")))

    def _open_first(self) -> None:
        item = self.list.topLevelItem(0)
        if item is not None:
            self.list.setCurrentItem(item)
            self._chosen(item)

    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtCore import QEvent

        if obj is self.search and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Down:
            if self.list.topLevelItemCount():
                self.list.setFocus()
                if self.list.currentItem() is None:
                    self.list.setCurrentItem(self.list.topLevelItem(0))
                return True
        return super().eventFilter(obj, event)
