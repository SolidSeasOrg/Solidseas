"""The History tab: a file's versions, each one's preview, and what changed.

**Versions.** For the document shown, :func:`version_rows` lists its versions newest
first as plain :class:`VersionRow` values: the commits that changed it when it sits in
a Git repository, else the snapshots SolidSeas keeps of it in the user's data folder
(``solidseas.versions``), with the working copy on top when it differs from the
newest one. That function is the tab's one source of versions, so another history (a
PDM vault's check-ins) can supply rows of the same shape later.

**A version.** Choosing a row shows that version's stored preview
(``versions.open_version(...).preview()``) and the differences between it and the
version before it (``versions.compare``): document fields, properties,
configurations and geometry, as the ``diff`` command reports them.

**Buttons.** Take Snapshot keeps a copy of the file as it is now in the user's data
folder (``versions.snapshot``), never beside the file, and lists it; for a file in
Git it is off, as its versions are its commits. Compare with Working Copy shows what
changed from the chosen version to the file on disk.

Every read, comparison and snapshot runs in a worker thread; the tab reads the
versions only while it is shown, so selecting documents with another tab open costs
nothing. Document text is shown as plain text, as everywhere in the viewer.
"""

import os
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Qt, QThreadPool, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .reading import size_text, time_text
from .wording import error_message, tip
from .workers import Job

TAB = "History"
PREVIEW_SIZE = (240, 180)  # the chosen version's preview fits this box
SNAPSHOT_TEXT = "Take Snapshot"
COMPARE_TEXT = "Compare with Working Copy"
NO_HISTORY_TEXT = (
    "This file has no earlier versions yet. Take Snapshot keeps a copy of it as it is now in your "
    "SolidSeas data folder, never beside the file, so you can see later what changed. A file in a "
    "Git repository lists the commits that changed it instead."
)


# --------------------------------------------------------------------------- the versions
@dataclass(frozen=True)
class VersionRow:
    """One version as the tab lists it. ``ref`` names it to ``solidseas.versions``
    (``working``, or a commit or snapshot id); ``kind`` is ``commit``, ``snapshot`` or
    ``working``; ``note`` is the commit's subject, the snapshot's note or, for the
    working copy, how it differs."""

    ref: str
    number: int
    kind: str
    time_utc: str | None
    note: str
    size: int | None
    author: str | None = None
    available: bool = True
    deleted: bool = False

    @property
    def label(self) -> str:
        return f"v{self.number}"

    @property
    def source(self) -> str:
        return {"commit": "Git commit", "snapshot": "Snapshot", "working": "Working copy"}.get(
            self.kind, self.kind
        )

    @property
    def readable(self) -> bool:
        """Its content can be read here: not a deletion, not an LFS object missing here."""
        return self.available and not self.deleted


def version_rows(path: str) -> list[VersionRow]:
    """The versions of the file at ``path``, newest first: the History tab's one source
    of rows. Reads the file and its history read-only and writes nothing."""
    from solidseas import versions

    data = versions.history(path)
    git = data["source"] == "git"
    state = data["working"]["state"]
    working_note = {
        ("changed", True): "Changed since the newest commit, not committed",
        ("new", True): "Not committed yet",
        ("changed", False): "Changed since the newest snapshot",
        ("new", False): "No snapshot yet",
    }.get((state, git), "")
    rows = []
    for v in data["versions"]:
        working = v["kind"] == "working"
        rows.append(
            VersionRow(
                ref="working" if working else v["id"],
                number=v["number"],
                kind=v["kind"],
                time_utc=v["time_utc"],
                note=working_note if working else (v["subject"] or ""),
                size=v["size"],
                author=v["author"],
                available=v["available"],
                deleted=v["status"] == "deleted",
            )
        )
    return rows


def has_history(rows: list[VersionRow]) -> bool:
    """Whether any version is stored: a commit or a snapshot, not only the working copy."""
    return any(r.kind != "working" for r in rows)


def from_git(rows: list[VersionRow]) -> bool:
    return any(r.kind == "commit" for r in rows)


def working_comparable(rows: list[VersionRow], index: int, exists: bool) -> bool:
    """Whether Compare with Working Copy means something for row ``index``: the file is
    on disk, the row is a readable stored version, and it is not the working copy itself
    (the newest stored version is, when no working row is listed)."""
    if not exists or not 0 <= index < len(rows):
        return False
    row = rows[index]
    if row.kind == "working" or not row.readable:
        return False
    return rows[0].kind == "working" or index > 0


# --------------------------------------------------------------------------- work, off the UI thread
def load_work(path: str, source=None):
    """A Job's work: the rows of the file at ``path`` from ``source`` (default
    :func:`version_rows`) and whether the file is on disk now."""

    def work(_emit, _cancelled) -> dict[str, Any]:
        rows = (source or version_rows)(path)
        return {"ok": True, "rows": rows, "exists": os.path.isfile(path)}

    return work


def preview_of(path: str, row: VersionRow) -> dict[str, Any]:
    """The stored preview of one version, scaled to :data:`PREVIEW_SIZE` as PNG bytes,
    or None with the reason in words."""
    from solidseas import versions

    from .workers import thumbnail

    if row.deleted:
        return {"image": None, "why": "The file was deleted in this commit."}
    if not row.available:
        return {"image": None, "why": "This version is not on this computer."}
    try:
        with versions.open_version(path, row.ref) as doc:
            p = doc.preview()
            image = thumbnail(p.data, PREVIEW_SIZE) if p is not None else None
    except Exception as exc:
        from solidseas import model

        return {
            "image": None,
            "why": "Its preview could not be read. " + error_message(model.error_info(exc)),
        }
    return {"image": image, "why": "" if image else "This version stores no preview image."}


def detail_work(path: str, row: VersionRow, previous: VersionRow | None):
    """A Job's work: ``row``'s preview first (as progress), then the differences from
    ``previous`` to it."""

    def work(emit, cancelled) -> dict[str, Any]:
        emit(preview_of(path, row))
        if cancelled():
            return {"ok": True, "diff": None, "why": ""}
        if previous is None:
            return {"ok": True, "diff": None, "why": "This is the first version: there is none before it."}
        if row.deleted:
            return {"ok": True, "diff": None, "why": "The file was deleted in this commit."}
        if not row.readable or not previous.readable:
            why = (
                "The version before is the file's deletion, so there is nothing to compare with."
                if previous.deleted
                else "One of the two versions is not on this computer, so they cannot be compared."
            )
            return {"ok": True, "diff": None, "why": why}
        return compare_work(path, previous.ref, row.ref)(emit, cancelled)

    return work


def compare_work(path: str, older: str, newer: str):
    """A Job's work: ``version_diff`` data from ``older`` to ``newer``."""

    def work(_emit, _cancelled) -> dict[str, Any]:
        from solidseas import versions

        return {"ok": True, "diff": versions.compare(path, older, newer), "why": ""}

    return work


def snapshot_work(path: str):
    """A Job's work: a snapshot of the file at ``path`` into the user's own store."""

    def work(_emit, _cancelled) -> dict[str, Any]:
        from solidseas import versions

        return {"ok": True, "data": versions.snapshot(path)}

    return work


# --------------------------------------------------------------------------- the differences in words
_FIELDS = {
    "type": "Document type",
    "format": "Format",
    "saved_version": "Saved in",
    "title": "Title",
    "subject": "Subject",
    "author": "Author",
    "keywords": "Keywords",
    "comments": "Comments",
    "material": "Material",
    "active_configuration": "Active configuration",
    "comment": "Configuration comment",
    "units.system": "Unit system",
    "units.length": "Length unit",
    "units.mass": "Mass unit",
    "units.angle": "Angle unit",
    "units.scale_m": "Scale",
}
_MEASURES = {
    "volume_mm3": ("Volume", " mm3"),
    "area_mm2": ("Area", " mm2"),
    "size_x_mm": ("Size in x", " mm"),
    "size_y_mm": ("Size in y", " mm"),
    "size_z_mm": ("Size in z", " mm"),
    "min_x_mm": ("Lowest x", " mm"),
    "min_y_mm": ("Lowest y", " mm"),
    "min_z_mm": ("Lowest z", " mm"),
}
_GEOMETRY = {
    "unchanged": "Unchanged",
    "changed": "Changed",
    "added": "Added",
    "removed": "Removed",
    "not_stored": "Not stored in either version",
    "not_compared": "Not compared: one version does not store its bodies",
}
_NOT_COMPARED = {
    "different_types": "the two versions are different kinds of document",
    "no_geometry": "neither version holds geometry",
    "assembly": "assemblies are not compared on geometry yet",
    "drawing": "drawings are not compared on geometry yet",
}


def _number(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "" if value is None else str(value)
    return f"{value:,.6g}" if abs(value) < 1e6 else f"{value:,.0f}"


def _property(p: dict[str, Any] | None) -> str:
    if p is None:
        return ""
    if p.get("type") == "text":
        return str(p["value"] if p.get("value") is not None else p.get("text") or "")
    return str(p["text"] if p.get("text") is not None else p.get("value"))


def _where(name: str, configuration: str | None) -> str:
    return f"{name} ({configuration})" if configuration else name


def diff_groups(diff: dict[str, Any]) -> list[tuple[str, list[tuple[str, str, str]]]]:
    """``version_diff`` data as groups of rows (what, before, after), in the order the
    tab shows them; a group with nothing in it is left out."""
    groups: list[tuple[str, list[tuple[str, str, str]]]] = []
    props = diff["properties"]
    rows = [(_where(p["name"], p["configuration"]), "", _property(p["to"])) for p in props["added"]]
    rows += [
        (_where(p["name"], p["configuration"]), _property(p["from"]), "(removed)") for p in props["removed"]
    ]
    rows += [
        (_where(p["name"], p["configuration"]), _property(p["from"]), _property(p["to"]))
        for p in props["changed"]
    ]
    if rows:
        groups.append(("Properties", rows))
    cfgs = diff["configurations"]
    rows = [(name, "", "(added)") for name in cfgs["added"]]
    rows += [(name, "", "(removed)") for name in cfgs["removed"]]
    if rows:
        groups.append(("Configurations", rows))
    rows = []
    for c in diff["document"]["changes"]:
        if c["field"] == "preview":
            rows.append(("Preview image", "", "changed"))
            continue
        name = _FIELDS.get(c["field"], c["field"].replace("_", " ").capitalize())
        rows.append((_where(name, c["configuration"]), c["from"] or "(none)", c["to"] or "(none)"))
    if rows:
        groups.append(("Document", rows))
    g = diff["geometry"]
    rows = []
    if g["compared"]:
        for row in g["configurations"]:
            if row["status"] == "unchanged":
                continue
            name = row["configuration"] or "The model"
            rows.append((name, "", _GEOMETRY.get(row["status"], row["status"])))
            for c in row["changes"]:
                label, unit = _MEASURES.get(c["measure"], (c["measure"].replace("_", " ").capitalize(), ""))
                rows.append((f"  {label}", _number(c["from"]) + unit, _number(c["to"]) + unit))
    elif g["reason"]:
        rows.append(("Not compared", "", _NOT_COMPARED.get(g["reason"], g["reason"].replace("_", " "))))
    if rows:
        groups.append(("Geometry", rows))
    notes = [(w["message"][:1].upper() + w["message"][1:], "", "") for w in diff.get("warnings") or ()]
    if notes:
        groups.append(("Notes", notes))
    return groups


def _side(v: dict[str, Any]) -> str:
    if v["kind"] == "working":
        return f"v{v['number']}, the working copy"
    what = "Git commit" if v["kind"] == "commit" else "snapshot"
    when = time_text(v["time_utc"])
    return f"v{v['number']} ({what}{', ' + when if when else ''})"


def diff_caption(diff: dict[str, Any]) -> str:
    """The sentence above the differences: which two versions, and when there are none."""
    text = f"Changes from {_side(diff['from'])} to {_side(diff['to'])}."
    if diff["same_content"]:
        return text + " The two versions are the same file."
    if not any(name != "Notes" for name, _rows in diff_groups(diff)):
        text += " No change found in the document, its properties, configurations or geometry."
    return text


# --------------------------------------------------------------------------- the tab
class HistoryPane(QWidget):
    """The tab's content: a line on top with the two buttons, the versions, and under them
    the chosen version's preview beside its differences. ``versionChosen`` carries the
    chosen row's index; ``snapshotRequested`` and ``compareRequested`` the buttons."""

    versionChosen = Signal(int)
    snapshotRequested = Signal()
    compareRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setContentsMargins(6, 4, 6, 4)
        self.snapshot_button = QPushButton(SNAPSHOT_TEXT)
        self.snapshot_button.clicked.connect(self.snapshotRequested)
        self.compare_button = QPushButton(COMPARE_TEXT)
        self.compare_button.clicked.connect(self.compareRequested)
        self.compare_button.setToolTip(
            tip("Show what changed from the chosen version to the file as it is now.")
        )
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.status, 1)
        top.addWidget(self.snapshot_button)
        top.addWidget(self.compare_button)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Version", "When", "Source", "Note", "Size"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tree.currentItemChanged.connect(self._current)

        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setWordWrap(True)
        self.image.setTextFormat(Qt.TextFormat.PlainText)
        self.image.setFixedWidth(PREVIEW_SIZE[0] + 8)
        self.image.setMinimumHeight(PREVIEW_SIZE[1] // 2)
        self.diff_caption = QLabel()
        self.diff_caption.setTextFormat(Qt.TextFormat.PlainText)
        self.diff_caption.setWordWrap(True)
        self.diff_caption.setContentsMargins(6, 4, 6, 4)
        self.diff = QTreeWidget()
        self.diff.setColumnCount(3)
        self.diff.setHeaderLabels(["Change", "Before", "After"])
        self.diff.setUniformRowHeights(True)
        self.diff.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.diff_caption)
        rl.addWidget(self.diff, 1)
        bottom = QWidget()
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.image, 0, Qt.AlignmentFlag.AlignTop)
        bl.addWidget(right, 1)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.tree)
        split.addWidget(bottom)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        split.setChildrenCollapsible(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addWidget(split, 1)
        self.rows: list[VersionRow] = []

    def _current(self, current: QTreeWidgetItem | None, _previous) -> None:
        if current is not None:
            self.versionChosen.emit(self.tree.indexOfTopLevelItem(current))

    def clear(self) -> None:
        self.rows = []
        self.tree.clear()
        self.status.setText("")
        self.clear_version("")

    def clear_version(self, text: str) -> None:
        """The preview and the differences say ``text`` until the chosen version is read."""
        self.image.clear()
        self.image.setText(text)
        self.diff.clear()
        self.diff_caption.setText(text)

    def show_rows(self, rows: list[VersionRow]) -> None:
        """List ``rows`` without choosing one (the controller chooses)."""
        self.rows = list(rows)
        self.tree.blockSignals(True)
        self.tree.clear()
        for r in rows:
            item = QTreeWidgetItem(
                [r.label, time_text(r.time_utc), r.source, r.note, size_text(r.size) if r.readable else ""]
            )
            item.setTextAlignment(4, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lines = [f"{r.source} {r.ref}" if r.kind != "working" else "The file as it is now"]
            if r.author:
                lines.append(f"By {r.author}")
            if r.note:
                lines.append(r.note)
            if r.deleted:
                lines.append("The file was deleted in this commit.")
            elif not r.available:
                lines.append("Its content is not on this computer (a Git LFS object that was not fetched).")
            item.setToolTip(0, tip("\n".join(lines)))
            if r.note:
                item.setToolTip(3, tip(r.note))
            if not r.readable:
                for c in range(5):
                    item.setForeground(c, self.palette().placeholderText())
            self.tree.addTopLevelItem(item)
        self.tree.blockSignals(False)
        for c in (0, 1, 2, 4):
            self.tree.resizeColumnToContents(c)

    def choose(self, index: int) -> None:
        item = self.tree.topLevelItem(index)
        if item is not None:
            if self.tree.currentItem() is item:
                self.versionChosen.emit(index)
            else:
                self.tree.setCurrentItem(item)

    @property
    def chosen(self) -> int:
        item = self.tree.currentItem()
        return -1 if item is None else self.tree.indexOfTopLevelItem(item)

    def show_preview(self, result: dict[str, Any]) -> None:
        pix = QPixmap()
        if result.get("image") and pix.loadFromData(result["image"]):
            self.image.setPixmap(pix)
        else:
            self.image.clear()
            self.image.setText(result.get("why") or "")

    def show_diff(self, caption: str, diff: dict[str, Any] | None) -> None:
        self.diff_caption.setText(caption)
        self.diff.clear()
        if diff is None:
            return
        for name, rows in diff_groups(diff):
            top = QTreeWidgetItem([name, "", ""])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            self.diff.addTopLevelItem(top)
            for what, before, after in rows:
                item = QTreeWidgetItem(top, [what, before, after])
                for c, text in enumerate((what, before, after)):
                    if text:
                        item.setToolTip(c, tip(text))
            top.setExpanded(True)
        self.diff.resizeColumnToContents(0)


# --------------------------------------------------------------------------- the controller
class HistoryController(QObject):
    """The History tab of one window (see the module notes). ``shown`` carries each
    result the tab showed: the versions, a version's differences, a snapshot taken
    (for tests)."""

    shown = Signal(object)

    def __init__(self, window, source=None) -> None:
        super().__init__(window)
        self.w = window
        self.source = source  # None: version_rows, looked up at each load
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(
            2
        )  # the list and a version's details; a slow compare never holds the list
        self.pane: HistoryPane = window.details.history
        self.page = window.details.pages[TAB]
        self.pane.versionChosen.connect(self._chosen)
        self.pane.snapshotRequested.connect(self.take_snapshot)
        self.pane.compareRequested.connect(self.compare_with_working)
        window.details.tabs.currentChanged.connect(lambda _i: self._load_if_shown())
        self.path: str | None = None
        self.rows: list[VersionRow] = []
        self.exists = False
        self._loaded = False
        self._generation = 0  # of the document shown and its list
        self._detail = 0  # of the chosen version's details
        self._snapshotting = False

    @property
    def showing(self) -> bool:
        return self.w.details.tabs.currentWidget() is self.page

    def document_shown(self, entry: dict[str, Any] | None, source) -> None:
        """The details panel shows another document: its versions are read when the tab is shown."""
        self._generation += 1
        self._detail += 1
        self.path = None
        self.rows = []
        self._loaded = False
        self.pane.clear()
        if entry is None or source is None:
            return
        if source.nested:
            self.page.message(
                "This component is stored inside its assembly, not as a file of its own: History "
                "covers files."
            )
            return
        self.path = source.path
        self.page.message("Reading the versions of this file...")
        self._load_if_shown()

    def _load_if_shown(self) -> None:
        if self.path is not None and not self._loaded and self.showing:
            self.load()

    def load(self) -> None:
        """Read the versions of the document shown (again), in a worker thread."""
        if self.path is None:
            return
        self._loaded = True
        self._generation += 1
        generation, path = self._generation, self.path
        job = Job(load_work(path, self.source))
        self.w._start(self.pool, job, on_finished=lambda result, g=generation: self._listed(g, result))

    def _listed(self, generation: int, result: dict[str, Any]) -> None:
        if generation != self._generation:
            return
        if not result.get("ok"):
            self.page.message(
                "The versions of this file could not be read.\n\n"
                + error_message(result.get("error"), path=self.path),
                error=True,
            )
            self.shown.emit(result)
            return
        self.rows, self.exists = result["rows"], result["exists"]
        git = from_git(self.rows)
        if not has_history(self.rows):
            status = NO_HISTORY_TEXT
        elif git:
            status = "The commits that changed this file in its Git repository, newest first."
        else:
            status = "The snapshots of this file in your SolidSeas data folder, newest first."
        if not self.exists:
            status += " The file is not on disk now."
        self.pane.status.setText(status)
        self.pane.snapshot_button.setEnabled(self.exists and not git and not self._snapshotting)
        self.pane.snapshot_button.setToolTip(
            tip(
                "This file's versions are its Git commits: commit it to add one."
                if git
                else "Keep a copy of the file as it is now in your SolidSeas data folder, never beside the "
                "file, and add it to this list. Nothing is stored when the file has not changed since its "
                "newest snapshot."
            )
        )
        self.pane.compare_button.setEnabled(False)
        self.pane.show_rows(self.rows)
        self.page.show_content()
        self.shown.emit(result)
        if self.rows:
            self.pane.choose(0)
        else:
            self.pane.clear_version("")

    def _chosen(self, index: int) -> None:
        if not 0 <= index < len(self.rows) or self.path is None:
            return
        self.pane.compare_button.setEnabled(working_comparable(self.rows, index, self.exists))
        row = self.rows[index]
        previous = self.rows[index + 1] if index + 1 < len(self.rows) else None
        self._detail += 1
        detail = self._detail
        self.pane.clear_version("Reading this version...")
        job = Job(detail_work(self.path, row, previous))
        self.w._start(
            self.pool,
            job,
            on_progress=lambda result, d=detail: self._previewed(d, result),
            on_finished=lambda result, d=detail: self._compared(d, result),
        )

    def _previewed(self, detail: int, result: dict[str, Any]) -> None:
        if detail == self._detail:
            self.pane.show_preview(result)

    def _compared(self, detail: int, result: dict[str, Any]) -> None:
        if detail != self._detail:
            return
        if not result.get("ok"):
            self.pane.show_diff(
                "The two versions could not be compared. "
                + error_message(result.get("error"), path=self.path),
                None,
            )
        elif result.get("diff") is None:
            self.pane.show_diff(result.get("why") or "", None)
        else:
            self.pane.show_diff(diff_caption(result["diff"]), result["diff"])
        self.shown.emit(result)

    def compare_with_working(self) -> None:
        """What changed from the chosen version to the file as it is now."""
        index = self.pane.chosen
        if self.path is None or not working_comparable(self.rows, index, self.exists):
            return
        self._detail += 1
        detail = self._detail
        self.pane.diff.clear()
        self.pane.diff_caption.setText("Comparing with the working copy...")
        job = Job(compare_work(self.path, self.rows[index].ref, "working"))
        self.w._start(self.pool, job, on_finished=lambda result, d=detail: self._compared(d, result))

    def take_snapshot(self) -> None:
        """Keep a copy of the file shown in the user's data folder, then list it."""
        if self.path is None or self._snapshotting:
            return
        self._snapshotting = True
        self.pane.snapshot_button.setEnabled(False)
        generation, path = self._generation, self.path
        job = Job(snapshot_work(path))
        self.w._start(
            self.pool, job, on_finished=lambda result, g=generation: self._snapshot_taken(g, path, result)
        )

    def _snapshot_taken(self, generation: int, path: str, result: dict[str, Any]) -> None:
        self._snapshotting = False
        name = os.path.basename(path)
        if not result.get("ok"):
            text = "The snapshot could not be taken. " + error_message(result.get("error"), path=path)
        elif result["data"]["new"]:
            text = f"Took snapshot v{result['data']['snapshot']['number']} of {name}."
        else:
            text = f"{name} has not changed since its newest snapshot: nothing new was stored."
        self.w.statusBar().showMessage(text, 10000)
        if generation == self._generation and path == self.path:
            if result.get("ok"):
                self.load()
            else:
                self.pane.status.setText(text)
                self.pane.snapshot_button.setEnabled(self.exists)
        self.shown.emit(result)

    def stop(self) -> None:
        """The window is closing: queued work is dropped; the window waits for :attr:`pool`."""
        self.pool.clear()


__all__ = [
    "TAB",
    "HistoryController",
    "HistoryPane",
    "VersionRow",
    "diff_caption",
    "diff_groups",
    "has_history",
    "version_rows",
    "working_comparable",
]
