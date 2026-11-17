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

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QToolButton,
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
ARCHIVED_TEXT = "Show archived"
ARCHIVED_TIP = "List the projects in archive sections too. A search always looks in them"
PATH_ROLE = Qt.ItemDataRole.UserRole
DETAIL_ROLE = Qt.ItemDataRole.UserRole + 1  # the second line: section, when, changes
ARCHIVED_ROLE = Qt.ItemDataRole.UserRole + 2


CHILD_TIMEOUT = 600.0  # seconds; a library on a slow share can take minutes


def _in_child(library: str) -> tuple[list[dict[str, Any]] | None, str]:
    """The projects as ``solidseas pdm projects --json`` lists them, from a child
    process, and an empty reason; or None and why the child gave none (it could not be
    started, timed out, or answered with something that is not that list)."""
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
            capture_output=True,
            timeout=CHILD_TIMEOUT,
            check=False,
            **kwargs,
        )
    except subprocess.TimeoutExpired:
        return None, f"timed out after {CHILD_TIMEOUT:.0f} s"
    except Exception as exc:
        return None, f"could not start: {type(exc).__name__}: {exc}"
    try:
        env = json.loads(done.stdout.decode("utf-8"))
        rows = env["data"]["projects"]["projects"] if env.get("ok") else None
    except Exception as exc:
        err = done.stderr.decode("utf-8", "replace").strip().splitlines()
        tail = f"; {err[-1][:200]}" if err else ""
        return (
            None,
            f"exit code {done.returncode}, {len(done.stdout):,} bytes not read ({type(exc).__name__}){tail}",
        )
    if not isinstance(rows, list):
        return None, f"exit code {done.returncode}, no projects in the answer"
    for r in rows:
        r.pop("score", None)  # a search's; the view searches for itself
    return rows, ""


CHILD_TRIES = 2  # a second child is still far quicker than the work in the window's process


def activity_work(library: str, *, child: bool = True):
    """A Job's work: every project of the library with when it was last worked on, as
    data (``ProjectActivity.data``), from a child process when ``child`` and one of
    ``CHILD_TRIES`` answers, else in this thread. ``read`` says which did it, how long
    it took and, when the thread did, why each child gave nothing."""

    def work(_emit, cancelled) -> dict[str, Any]:
        import time

        from solidseas import model, pdm

        began = time.monotonic()
        reasons: list[str] = []
        for _ in range(CHILD_TRIES if child else 0):
            if cancelled():
                break
            rows, reason = _in_child(library)
            if rows is not None:
                read = {"how": "child", "seconds": time.monotonic() - began, "reasons": reasons}
                return {"ok": True, "kind": "projects", "library": library, "projects": rows, "read": read}
            reasons.append(reason)
        try:
            vault = pdm.open(library)
            rows = [a.data() for a in vault.project_activity(cancelled)]
        except Exception as exc:
            return {"ok": False, "kind": "projects", "library": library, "error": model.error_info(exc)}
        read = {"how": "thread", "seconds": time.monotonic() - began, "reasons": reasons}
        return {"ok": True, "kind": "projects", "library": library, "projects": rows, "read": read}

    return work


def read_text(read: dict[str, Any] | None) -> str:
    """How the projects were read, for the count's tooltip."""
    if not read:
        return ""
    how = "a separate process" if read.get("how") == "child" else "the window itself"
    text = f"Read by {how} in {read.get('seconds', 0):.1f} s."
    reasons = read.get("reasons") or []
    if reasons:
        text += " The separate process gave no answer: " + "; then ".join(reasons) + "."
    return text


def detail_text(row: dict[str, Any]) -> str:
    """A project's second line: its section, when it was last worked on and, when
    there are any, how many files have changes not checked in."""
    when = row.get("last_activity_utc")
    parts = [row["section"], ago(when) if when else "no CAD files"]
    pending = row.get("pending") or 0
    if pending:
        parts.append(f"{pending:,} not checked in")
    return " \u00b7 ".join(parts)


class _ProjectDelegate(QStyledItemDelegate):
    """Draws a project as two lines: its name, then its section, when it was last
    worked on and its changes not checked in, smaller and greyed. An archived project
    is greyed all over."""

    PAD = 4

    def _fonts(self, option) -> tuple[QFont, QFont]:
        name = QFont(option.font)
        name.setBold(True)
        detail = QFont(option.font)
        detail.setPointSizeF(max(option.font.pointSizeF() * 0.9, 7.0))
        return name, detail

    def sizeHint(self, option, index) -> QSize:
        name, detail = self._fonts(option)
        from PySide6.QtGui import QFontMetrics

        h = QFontMetrics(name).height() + QFontMetrics(detail).height() + 3 * self.PAD
        return QSize(super().sizeHint(option, index).width(), h)

    def paint(self, painter, option, index) -> None:
        from PySide6.QtGui import QFontMetrics
        from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        archived = bool(index.data(ARCHIVED_ROLE))
        pal = opt.palette
        main = pal.color(QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text)
        dim = main if selected else pal.color(QPalette.ColorRole.PlaceholderText)
        name_font, detail_font = self._fonts(opt)
        r = opt.rect.adjusted(self.PAD + 2, self.PAD, -self.PAD, -self.PAD)
        nh = QFontMetrics(name_font).height()
        painter.save()
        painter.setFont(name_font)
        painter.setPen(dim if archived else main)
        name = QFontMetrics(name_font).elidedText(index.data(), Qt.TextElideMode.ElideRight, r.width())
        painter.drawText(QRect(r.left(), r.top(), r.width(), nh), Qt.AlignmentFlag.AlignLeft, name)
        painter.setFont(detail_font)
        painter.setPen(dim)
        detail = QFontMetrics(detail_font).elidedText(
            index.data(DETAIL_ROLE) or "", Qt.TextElideMode.ElideRight, r.width()
        )
        dh = QFontMetrics(detail_font).height()
        second = QRect(r.left(), r.top() + nh + self.PAD, r.width(), dh)
        painter.drawText(second, Qt.AlignmentFlag.AlignLeft, detail)
        painter.restore()


def _key(row: dict[str, Any]):
    from datetime import datetime

    when = row.get("last_activity_utc")
    dt = datetime.fromisoformat(when.replace("Z", "+00:00")) if when else None
    return row["name"], row["section"], row["path"], dt


class ProjectsPane(QWidget):
    """The Projects view. ``projectChosen`` carries the chosen project's folder."""

    projectChosen = Signal(str)
    loaded_rows = Signal()  # the projects were read: the window marks the opened one

    def __init__(self, controller: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.library: str | None = None
        self.rows: list[dict[str, Any]] = []
        self.loaded = False
        self._generation = 0
        self.last_read: dict[str, Any] | None = None  # how the projects were read last (read_text)
        self._jobs: set[Any] = set()  # kept until they answer, as the Job objects must be

        self.search = QLineEdit()
        self.search.setPlaceholderText(SEARCH_HINT)
        self.search.setToolTip(tip(SEARCH_TIP))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._fill)
        self.search.returnPressed.connect(self._open_first)
        self.search.installEventFilter(self)
        self.refresh_button = QToolButton()
        self.refresh_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.refresh_button.setAccessibleName("Refresh")
        self.refresh_button.setToolTip(tip(REFRESH_TIP))
        self.refresh_button.clicked.connect(self.refresh)
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.refresh_button)
        self.show_archived = QCheckBox(ARCHIVED_TEXT)
        self.show_archived.setToolTip(tip(ARCHIVED_TIP))
        self.show_archived.toggled.connect(self._fill)
        self.current: str | None = None  # the opened project, as a path below the library

        self.list = QListWidget()
        self.list.setItemDelegate(_ProjectDelegate(self.list))
        self.list.setUniformItemSizes(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.itemClicked.connect(self._chosen)
        self.list.itemActivated.connect(self._chosen)

        self.note = QLabel(OUTSIDE_TEXT)
        self.note.setTextFormat(Qt.TextFormat.PlainText)
        self.note.setWordWrap(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(bar)
        lay.addWidget(self.show_archived)
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
            self.last_read = result.get("read")
            self._fill()
            self._show_state()
            self.loaded_rows.emit()

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
        return [self.list.item(i).data(PATH_ROLE) for i in range(self.list.count())]

    def _listed(self) -> list[dict[str, Any]]:
        """The rows the list may show: archived projects only when asked for or searched."""
        if self.show_archived.isChecked() or self.search.text().strip():
            return self.rows
        return [r for r in self.rows if not r.get("archived")]

    def set_current(self, folder: str | None) -> None:
        """Mark the project that holds the opened ``folder`` (none outside a project)."""
        self.current = None
        if folder and self.library:
            try:
                rel = os.path.relpath(folder, self.library).replace(os.sep, "/")
            except ValueError:  # another drive
                rel = ""
            if rel and not rel.startswith(".."):
                parts = rel.casefold().split("/")
                for r in self.rows:
                    p = r["path"].casefold().split("/")
                    if parts[: len(p)] == p:
                        self.current = r["path"]
                        break
        self._select_current()

    def _select_current(self) -> None:
        for i in range(self.list.count()):
            item = self.list.item(i)
            if self.current is not None and item.data(PATH_ROLE) == self.current:
                self.list.setCurrentItem(item)
                return
        self.list.clearSelection()

    def _fill(self, *_args: Any) -> None:
        from solidseas.pdm.search import search

        self.list.clear()
        if not self.rows:
            return
        for f in search(self._listed(), self.search.text(), key=_key):
            row = f.entry
            when = row.get("last_activity_utc")
            item = QListWidgetItem(row["name"])
            item.setData(PATH_ROLE, row["path"])
            item.setData(DETAIL_ROLE, detail_text(row))
            item.setData(ARCHIVED_ROLE, bool(row.get("archived")))
            lines = [row["path"]]
            if when:
                lines.append("Last worked on " + time_text(when))
            lines.append(plural(row.get("files") or 0, "CAD file"))
            item.setToolTip(tip("\n".join(lines)))
            self.list.addItem(item)
        self._select_current()
        if self.loaded:
            self._show_state()

    def _show_state(self) -> None:
        if self.library is None:
            self.note.setText(OUTSIDE_TEXT)
            self.note.show()
        elif not self.loaded:
            self.note.setText(LOOKING_TEXT)
            self.note.show()
        elif self.search.text().strip() and self.list.count() == 0:
            self.note.setText("No project matches. Try fewer letters.")
            self.note.show()
        else:
            shown, total = self.list.count(), len(self._listed())
            text = plural(total, "project") if shown == total else f"{shown:,} of {plural(total, 'project')}"
            self.note.setText(text)
            self.note.show()
        self.note.setToolTip(tip(read_text(self.last_read)) if self.loaded and self.last_read else "")
        self.search.setEnabled(self.library is not None)
        self.refresh_button.setEnabled(self.library is not None)

    def _chosen(self, item: QListWidgetItem) -> None:
        rel = item.data(PATH_ROLE)
        if self.library is None or not rel:
            return
        self.projectChosen.emit(os.path.join(self.library, *rel.split("/")))

    def _open_first(self) -> None:
        item = self.list.item(0)
        if item is not None:
            self.list.setCurrentItem(item)
            self._chosen(item)

    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtCore import QEvent

        if obj is self.search and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Down:
            if self.list.count():
                self.list.setFocus()
                if self.list.currentItem() is None:
                    self.list.setCurrentItem(self.list.item(0))
                return True
        return super().eventFilter(obj, event)
