"""The History tab: a file's versions, each one's preview, and what changed.

**Versions.** For the document shown, :func:`file_history` lists its versions newest
first as plain :class:`VersionRow` values, with the working copy on top when it differs
from the newest one. A file in a PDM library (``solidseas.pdm``) lists the library's
versions with their check-in notes, and the Git commits that changed it when it also
sits in a Git repository (``Vault.log``). Any other file lists the commits that
changed it when it sits in a Git repository, else the snapshots SolidSeas keeps of it
in the user's data folder (``solidseas.versions``) and, when a folder above it has a
store of its own (``.solidseas/history``, ``snapshot --project``), that store's
snapshots too. A controller can be given another source of rows; a row says which
history it came from, so its preview and differences are read from that history.

**A version.** Choosing a row shows that version's stored preview
(``versions.open_version(...).preview()``) and the differences between it and the
version before it (``versions.compare``): document fields, properties,
configurations and geometry, as the ``diff`` command reports them.

**Buttons.** Take Snapshot keeps a copy of the file as it is now in the user's data
folder (``versions.snapshot``), never beside the file, and lists it; for a file in
Git it is off, as its versions are its commits, and for a file in a library, whose
versions are its check-ins (PDM > Check In). Compare with Working Copy shows what
changed from the chosen version to the file on disk. A line under the buttons gives
the history's warnings (a Git history cut short, a version that could not be read).
View > History shows the tab (:attr:`HistoryController.act_history`).

Every read, comparison and snapshot runs in a worker thread; the tab reads the
versions only while it is shown, so selecting documents with another tab open costs
nothing. Document text is shown as plain text, as everywhere in the viewer.
"""

import os
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Qt, QThreadPool, Signal
from PySide6.QtGui import QAction, QKeySequence, QPixmap
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
NO_LIBRARY_HISTORY_TEXT = (
    "This file is in a library but has no version there yet. Check it in (PDM > Check In) to keep "
    "its first version with a note."
)


# --------------------------------------------------------------------------- the versions
@dataclass(frozen=True)
class VersionRow:
    """One version as the tab lists it. ``ref`` names it to ``solidseas.versions``
    (``working``, or a commit or snapshot id); ``kind`` is ``commit``, ``snapshot``,
    ``vault`` (a version in a PDM library) or ``working``; ``note`` is the commit's
    subject, the snapshot's note, the check-in's note or, for the working copy, how it
    differs. ``library`` is the library's folder for a ``vault`` row, ``project`` the
    folder whose own store holds a ``snapshot`` row (None for the user's store)."""

    ref: str
    number: int
    kind: str
    time_utc: str | None
    note: str
    size: int | None
    author: str | None = None
    available: bool = True
    deleted: bool = False
    library: str | None = None
    project: str | None = None
    revision: str | None = None
    state: str | None = None

    @property
    def label(self) -> str:
        return f"v{self.number}"

    @property
    def source(self) -> str:
        if self.kind == "snapshot" and self.project:
            return "Project snapshot"
        return {
            "commit": "Git commit",
            "snapshot": "Snapshot",
            "vault": "Library",
            "working": "Working copy",
        }.get(self.kind, self.kind)

    @property
    def readable(self) -> bool:
        """Its content can be read here: not a deletion, not an LFS object missing here."""
        return self.available and not self.deleted

    @property
    def family(self) -> tuple:
        """The history the row belongs to: rows of one family can be compared."""
        return (self.kind, self.library, self.project)

    def options(self) -> dict[str, Any]:
        """The ``solidseas.versions`` options that read this row's history."""
        if self.kind == "vault":
            from solidseas.pdm import VaultStore

            return {"source": "snapshots", "store": VaultStore(self.library)}
        if self.kind == "snapshot":
            return (
                {"source": "snapshots", "project": self.project} if self.project else {"source": "snapshots"}
            )
        if self.kind == "commit":
            return {"source": "git"}
        return {}


@dataclass(frozen=True)
class FileHistory:
    """What a source of rows gives the tab: the rows, newest first, the history's
    warnings in words, and the library's folder when the file is in one."""

    rows: list[VersionRow]
    warnings: tuple[str, ...] = ()
    library: str | None = None


def _warning_words(warnings) -> tuple[str, ...]:
    out = []
    for w in warnings or ():
        text = str((w or {}).get("message") or "").strip()
        if text:
            out.append(text[:1].upper() + text[1:])
    return tuple(out)


def _rows_of(data: dict[str, Any], *, project: str | None = None) -> list[VersionRow]:
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
                project=None if working else project,
            )
        )
    return rows


def project_store_of(path: str) -> str | None:
    """The nearest folder above the file at ``path`` that holds a snapshot store of its
    own (``.solidseas/history``, a real folder, not a link); None when there is none."""
    from solidseas.versions.snapstore import PROJECT_FOLDER, STORE_FOLDER

    cur = os.path.dirname(os.path.abspath(path))
    while True:
        own = os.path.join(cur, PROJECT_FOLDER)
        store = os.path.join(own, STORE_FOLDER)
        if not os.path.islink(own) and not os.path.islink(store) and os.path.isdir(store):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def _by_time(rows: list[VersionRow]) -> list[VersionRow]:
    return sorted(rows, key=lambda r: (r.time_utc or "", r.number), reverse=True)


def snapshot_history(path: str) -> FileHistory:
    """The versions of a file outside any library: its Git commits when it has some,
    else the user's snapshots of it and those of the nearest project store above it.
    Reads the file and its history read-only and writes nothing."""
    from solidseas import versions

    data = versions.history(path)
    rows = _rows_of(data)
    warnings = list(data.get("warnings") or ())
    if data["source"] == "git":
        return FileHistory(rows, _warning_words(warnings))
    project = project_store_of(path)
    if project is None:
        return FileHistory(rows, _warning_words(warnings))
    pdata = versions.history(path, source="snapshots", project=project)
    prows = _rows_of(pdata, project=project)
    pstored = [r for r in prows if r.kind != "working"]
    if not pstored:
        return FileHistory(rows, _warning_words(warnings))
    warnings += list(pdata.get("warnings") or ())
    stored = _by_time([r for r in rows if r.kind != "working"] + pstored)
    # the working copy is listed when it differs from the newest version of the two stores
    owner = rows if stored[0].project is None else prows
    top = [r for r in owner if r.kind == "working"]
    return FileHistory(top + stored, _warning_words(warnings))


def version_rows(path: str) -> list[VersionRow]:
    """The rows of :func:`snapshot_history`."""
    return snapshot_history(path).rows


def _checkin_note(checkins: list[dict[str, Any]]) -> tuple[str, str | None, str | None]:
    """The note, revision and state a library version shows: its newest check-in's
    note, and the newest revision and state any of its check-ins gave it."""
    note = next((c["note"] for c in checkins if c.get("note")), "")
    if not note and checkins and all(c.get("auto") for c in checkins):
        note = "Stored by a scan"
    revision = next((c["revision"] for c in checkins if c.get("revision")), None)
    state = next((c["state"] for c in checkins if c.get("state")), None)
    return note, revision, state


def library_history(path: str, library: str | None = None) -> FileHistory:
    """The versions of a file in a PDM library (``Vault.log``): the library's versions
    with their check-in notes, the Git commits that changed it when it sits in a Git
    repository, and the working copy on top when it differs from the newest library
    version. Reads only."""
    from solidseas import pdm

    vault = pdm.open(library or path)
    data = vault.log(path)
    working_note = {
        "changed": "Changed since the newest library version, not checked in",
        "new": "Not checked in yet",
    }.get(data["working"]["state"], "")
    git_rows = [v for v in data["versions"] if v["source"] == "git"]
    git_number = {v["id"]: len(git_rows) - i for i, v in enumerate(git_rows)}  # the oldest is v1
    rows = []
    for v in data["versions"]:
        if v["source"] == "working":
            rows.append(VersionRow("working", v["number"], "working", v["time_utc"], working_note, v["size"]))
        elif v["source"] == "git":
            rows.append(
                VersionRow(
                    v["id"],
                    git_number[v["id"]],
                    "commit",
                    v["time_utc"],
                    v["subject"] or "",
                    v["size"],
                    author=v["author"],
                    available=v["available"],
                    deleted=v["status"] == "deleted",
                )
            )
        else:
            checkins = v.get("checkins") or []
            note, revision, state = _checkin_note(checkins)
            who = next((c["who"] for c in checkins if c.get("who")), None)
            rows.append(
                VersionRow(
                    v["id"],
                    v["number"],
                    "vault",
                    v["time_utc"],
                    note or (v["subject"] or ""),
                    v["size"],
                    author=who,
                    available=v["available"],
                    library=vault.root,
                    revision=revision,
                    state=state,
                )
            )
    return FileHistory(rows, _warning_words(data.get("warnings")), vault.root)


def file_history(path: str) -> FileHistory:
    """The tab's default source: :func:`library_history` for a file in a PDM library,
    :func:`snapshot_history` for any other."""
    from solidseas import pdm

    library = pdm.find_library(path)
    if library is not None:
        return library_history(path, library)
    return snapshot_history(path)


def has_history(rows: list[VersionRow]) -> bool:
    """Whether any version is stored: a commit, a snapshot or a library version, not
    only the working copy."""
    return any(r.kind != "working" for r in rows)


def from_git(rows: list[VersionRow]) -> bool:
    return any(r.kind == "commit" for r in rows)


def previous_of(rows: list[VersionRow], index: int) -> VersionRow | None:
    """The version before row ``index`` to compare it with: the next older row of the
    same history (the next older row of any, for the working copy)."""
    if not 0 <= index < len(rows):
        return None
    row = rows[index]
    for older in rows[index + 1 :]:
        if row.kind == "working" or older.family == row.family:
            return older
    return None


def pair_options(a: VersionRow, b: VersionRow | None) -> dict[str, Any]:
    """The options that read both rows: those of the one that is not the working copy."""
    for r in (a, b):
        if r is not None and r.kind != "working":
            return r.options()
    return {}


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
    :func:`file_history`; a source gives a :class:`FileHistory` or a list of rows), its
    warnings, its library and whether the file is on disk now."""

    def work(_emit, _cancelled) -> dict[str, Any]:
        got = (source or file_history)(path)
        if not isinstance(got, FileHistory):
            got = FileHistory(list(got))
        return {
            "ok": True,
            "rows": got.rows,
            "warnings": list(got.warnings),
            "library": got.library,
            "exists": os.path.isfile(path),
        }

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
        with versions.open_version(path, row.ref, **row.options()) as doc:
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
        return compare_work(path, previous.ref, row.ref, **pair_options(row, previous))(emit, cancelled)

    return work


def compare_work(path: str, older: str, newer: str, **options: Any):
    """A Job's work: ``version_diff`` data from ``older`` to ``newer`` (``options``:
    those of ``solidseas.versions.compare`` that name the history)."""

    def work(_emit, _cancelled) -> dict[str, Any]:
        from solidseas import versions

        return {"ok": True, "diff": versions.compare(path, older, newer, **options), "why": ""}

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


def _side(v: dict[str, Any], library: bool = False) -> str:
    if v["kind"] == "working":
        return f"v{v['number']}, the working copy"
    what = "Git commit" if v["kind"] == "commit" else "library version" if library else "snapshot"
    when = time_text(v["time_utc"])
    return f"v{v['number']} ({what}{', ' + when if when else ''})"


def diff_caption(diff: dict[str, Any], *, library: bool = False) -> str:
    """The sentence above the differences: which two versions (``library``: of a PDM
    library's), and when there are none."""
    text = f"Changes from {_side(diff['from'], library)} to {_side(diff['to'], library)}."
    if diff["same_content"]:
        return text + " The two versions are the same file."
    if not any(name != "Notes" for name, _rows in diff_groups(diff)):
        text += " No change found in the document, its properties, configurations or geometry."
    return text


# --------------------------------------------------------------------------- the tab
def note_text(row: VersionRow) -> str:
    """The Note column: the note, then the revision and state a check-in gave it."""
    labels = [f"rev {row.revision}"] if row.revision else []
    labels += [row.state] if row.state else []
    if not labels:
        return row.note
    return f"{row.note} ({', '.join(labels)})" if row.note else ", ".join(labels).capitalize()


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
        self.warnings = QLabel()
        self.warnings.setTextFormat(Qt.TextFormat.PlainText)
        self.warnings.setWordWrap(True)
        self.warnings.setContentsMargins(6, 0, 6, 4)
        self.warnings.hide()

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
        layout.addWidget(self.warnings)
        layout.addWidget(split, 1)
        self.rows: list[VersionRow] = []

    def _current(self, current: QTreeWidgetItem | None, _previous) -> None:
        if current is not None:
            self.versionChosen.emit(self.tree.indexOfTopLevelItem(current))

    def clear(self) -> None:
        self.rows = []
        self.tree.clear()
        self.status.setText("")
        self.show_warnings([])
        self.clear_version("")

    def show_warnings(self, warnings: list[str]) -> None:
        """The history's warnings in one plain line under the buttons; hidden when none."""
        words = [w[:1].upper() + w[1:].rstrip(".") + "." for w in warnings if w]
        self.warnings.setText("Note: " + " ".join(words) if words else "")
        self.warnings.setVisible(bool(words))

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
                [
                    r.label,
                    time_text(r.time_utc),
                    r.source,
                    note_text(r),
                    size_text(r.size) if r.readable else "",
                ]
            )
            item.setTextAlignment(4, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lines = [f"{r.source} {r.ref}" if r.kind != "working" else "The file as it is now"]
            if r.author:
                lines.append(f"By {r.author}")
            if r.note:
                lines.append(r.note)
            labels = [f"revision {r.revision}"] if r.revision else []
            labels += [f"state {r.state}"] if r.state else []
            if labels:
                lines.append(", ".join(labels).capitalize())
            if r.deleted:
                lines.append("The file was deleted in this commit.")
            elif not r.available:
                lines.append("Its content is not on this computer (a Git LFS object that was not fetched).")
            item.setToolTip(0, tip("\n".join(lines)))
            if note_text(r):
                item.setToolTip(3, tip(note_text(r)))
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
        self.act_history = QAction("&History", window)
        self.act_history.setShortcut(QKeySequence("Ctrl+Shift+H"))
        self.act_history.setStatusTip("Show the versions of the selected file and what changed in each")
        self.act_history.triggered.connect(self.show_tab)
        view_menu = getattr(window, "view_menu", None)
        if view_menu is not None:
            view_menu.addAction(self.act_history)
        self.path: str | None = None
        self.rows: list[VersionRow] = []
        self.library: str | None = None
        self.exists = False
        self._loaded = False
        self._generation = 0  # of the document shown and its list
        self._detail = 0  # of the chosen version's details
        self._snapshotting = False

    @property
    def showing(self) -> bool:
        return self.w.details.tabs.currentWidget() is self.page

    def show_tab(self) -> None:
        tabs = self.w.details.tabs
        tabs.setCurrentIndex(tabs.indexOf(self.page))

    def chosen_row(self) -> VersionRow | None:
        """The version chosen in the list, when one is."""
        index = self.pane.chosen
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def refresh(self, paths: list[str] | None = None) -> None:
        """Read the versions again (now when the tab is shown, else when it is next
        shown), when the file shown is one of ``paths`` or lies below one (any, when None)."""
        if self.path is None:
            return
        if paths is not None:
            key = os.path.normcase(os.path.abspath(self.path))
            folders = [os.path.normcase(os.path.abspath(p)) for p in paths]
            if not any(key == f or key.startswith(f.rstrip(os.sep) + os.sep) for f in folders):
                return
        self._loaded = False
        self._load_if_shown()

    def document_shown(self, entry: dict[str, Any] | None, source) -> None:
        """The details panel shows another document: its versions are read when the tab is shown."""
        self._generation += 1
        self._detail += 1
        self.path = None
        self.rows = []
        self.library = None
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
        self.library = result.get("library")
        git = from_git(self.rows)
        library = self.library is not None
        if library and not any(r.kind == "vault" for r in self.rows):
            status = NO_LIBRARY_HISTORY_TEXT
            if git:
                status += " The commits that changed it in its Git repository are listed."
        elif library:
            status = "The versions of this file in the library, newest first, with their check-in notes."
            if git:
                status += " The commits that changed it in its Git repository are listed with them."
        elif not has_history(self.rows):
            status = NO_HISTORY_TEXT
        elif git:
            status = "The commits that changed this file in its Git repository, newest first."
        elif any(r.project for r in self.rows):
            status = (
                "The snapshots of this file in your SolidSeas data folder and in its project's own "
                "store, newest first."
            )
        else:
            status = "The snapshots of this file in your SolidSeas data folder, newest first."
        if not self.exists:
            status += " The file is not on disk now."
        self.pane.status.setText(status)
        self.pane.show_warnings(result.get("warnings") or [])
        self.pane.snapshot_button.setEnabled(
            self.exists and not git and not library and not self._snapshotting
        )
        if library:
            snapshot_tip = (
                "This file is in a library: check it in (PDM > Check In) to keep a version with a note."
            )
        elif git:
            snapshot_tip = "This file's versions are its Git commits: commit it to add one."
        else:
            snapshot_tip = (
                "Keep a copy of the file as it is now in your SolidSeas data folder, never beside the "
                "file, and add it to this list. Nothing is stored when the file has not changed since its "
                "newest snapshot."
            )
        self.pane.snapshot_button.setToolTip(tip(snapshot_tip))
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
        previous = previous_of(self.rows, index)
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
            self.pane.show_diff(
                diff_caption(result["diff"], library=self.library is not None), result["diff"]
            )
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
        row = self.rows[index]
        job = Job(compare_work(self.path, row.ref, "working", **row.options()))
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
                self.pane.snapshot_button.setEnabled(self.exists and self.library is None)
        self.shown.emit(result)

    def stop(self) -> None:
        """The window is closing: queued work is dropped; the window waits for :attr:`pool`."""
        self.pool.clear()


__all__ = [
    "TAB",
    "FileHistory",
    "HistoryController",
    "HistoryPane",
    "VersionRow",
    "diff_caption",
    "diff_groups",
    "file_history",
    "has_history",
    "library_history",
    "previous_of",
    "snapshot_history",
    "version_rows",
    "working_comparable",
]
