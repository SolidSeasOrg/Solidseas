"""A library folder's vault: its settings, its history and check-ins (``docs/PDM.md``).

A library is a folder that ``pdm init`` gave a ``.solidseas/vault`` folder. The vault
keeps every version of every tracked CAD file in one snapshot store
(:class:`~solidseas.versions.snapstore.SnapshotStore`, ``docs/VERSIONS.md`` 4) whose
records name files by their path below the library, so the library can move. Check-ins
are records of their own (:mod:`.checkins`).

**What it writes.** Only its own ``.solidseas`` folder in the library, the file a
restore puts back, and the copies the common-parts library and ``check --fix`` make
(:mod:`.library`), each through a temporary name and a rename, never through a link
(``docs/PDM.md`` 7). A restore stores the current file as a version before it writes.
Every source file is opened read-only below the library with no link on the way
followed; a file or folder that is a link is never tracked.

**Fast status.** A file whose size and modification time are those of its newest
version is unchanged without being read; only the others are hashed.
"""

from __future__ import annotations

import datetime
import fnmatch
import hashlib
import json
import os
import re
import secrets
import stat
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from .. import __version__
from ..errors import (
    BusyError,
    InvalidArgumentError,
    LinkRefusedError,
    OutputRefusedError,
    PathRefusedError,
    SolidSeasError,
)
from ..formats import registry
from ..formats.solidworks._io import check_folder_within, open_readonly, relative_parts
from ..resolve.names import component_problem, fold
from ..versions import snapstore
from ..versions.gitrepo import _is_link
from .checkins import (
    CHECKIN_NAME,
    MAX_CHECKIN_FILES,
    MAX_LABEL,
    MAX_WHO,
    YEAR_NAME,
    Checkin,
    CheckinFile,
    parse_checkin,
    valid_label,
    valid_relative,
)
from .settings import Settings

VAULT_PARTS = (".solidseas", "vault")
SETTINGS_NAME = "vault.json"
DRAWING_EXPORTS = (".pdf", ".dxf")
STATES = ("new", "changed", "gone", "unchanged")
_CHUNK = 1 << 20
_FOLD = sys.platform in ("win32", "darwin")
_O_BINARY = getattr(os, "O_BINARY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_NEW_FILE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY | _O_NOFOLLOW | _O_CLOEXEC
_KEY = re.compile(r"[0-9a-f]{32}\Z")


def _iso(when: datetime.datetime | None) -> str | None:
    return None if when is None else when.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_ns(mtime_ns: int | None) -> str | None:
    if mtime_ns is None:
        return None
    try:
        return _iso(datetime.datetime.fromtimestamp(mtime_ns / 1e9, datetime.UTC))
    except (OverflowError, OSError, ValueError):
        return None


def _folded(rel: str) -> str:
    return fold(rel) if _FOLD else rel


def _refuse_link(path: str, what: str) -> None:
    if _is_link(path):
        raise LinkRefusedError(f"{path}: {what} is a link, which is never followed", detail={"rule": "link"})


# --------------------------------------------------------------------------- the store
class VaultStore(snapstore.SnapshotStore):
    """The vault's snapshot store, ``<library>/.solidseas/vault/store``. Its records keep
    the path below the library, as a project's store does, so the library can move."""

    def __init__(self, library: str) -> None:
        super().__init__(os.path.join(library, *VAULT_PARTS, "store"), "vault", library)

    def recorded_path(self, path: str) -> str:
        full = os.path.abspath(os.fspath(path))
        try:
            parts = relative_parts(full, self.project)
        except PathRefusedError:
            raise PathRefusedError(
                "the file is not inside the library", detail={"rule": "outside_library"}
            ) from None
        return "/".join(parts)

    def _check_root(self) -> None:
        cur = self.project
        for name in (*VAULT_PARTS, "store"):
            cur = os.path.join(cur, name)
            _refuse_link(cur, "a folder of the vault")

    def _make_root(self) -> None:
        self._check_root()
        cur = self.project
        for name in (*VAULT_PARTS, "store"):
            cur = self._folder(cur, name, create=True)

    def key_of(self, rel: str) -> str:
        """The record folder of the file at ``rel`` below the library."""
        return hashlib.sha256(_folded(rel).encode("utf-8", "surrogatepass")).hexdigest()[:32]

    def newest(self, key: str) -> snapstore.Snapshot | None:
        """The newest record in the folder ``key`` that holds up and names a file of that
        key. Only the newest names are read, so this stays cheap however many versions a
        file has."""
        self._check_root()
        st = snapstore.lstat_within(self.root, ("files", key))  # refuses a link on the way
        if st is None or not stat.S_ISDIR(st.st_mode):
            return None
        return self._newest_in(os.path.join(self.root, "files", key), key)

    def _newest_in(self, folder: str, key: str) -> snapstore.Snapshot | None:
        """As :meth:`newest`, for a record folder already checked to be no link."""
        try:
            names = sorted((n for n in os.listdir(folder) if snapstore._RECORD_NAME.match(n)), reverse=True)
        except (FileNotFoundError, NotADirectoryError):
            return None
        for name in names:
            try:
                with open_readonly(os.path.join(folder, name), within=folder) as fh:
                    data = fh.read(snapstore.MAX_RECORD_BYTES + 1)
            except (OSError, SolidSeasError):
                continue
            snap = snapstore.parse_record(data, name)
            if snap is None or not valid_relative(snap.path) or self.key_of(snap.path) != key:
                continue
            return snap
        return None

    def newest_all(self) -> dict[str, snapstore.Snapshot]:
        """The newest snapshot of every file the store has, keyed by its folded path."""
        self._check_root()
        out: dict[str, snapstore.Snapshot] = {}
        st = snapstore.lstat_within(self.root, ("files",))
        if st is None or not stat.S_ISDIR(st.st_mode):
            return out
        files = os.path.join(self.root, "files")
        with os.scandir(files) as it:
            folders = [
                (e.path, e.name)
                for e in it
                if _KEY.match(e.name)
                and e.is_dir(follow_symlinks=False)
                and not (sys.platform == "win32" and _is_link(e.path))
            ]
        for folder, key in folders:
            snap = self._newest_in(folder, key)
            if snap is not None:
                out[_folded(snap.path)] = snap
        return out


# --------------------------------------------------------------------------- results
@dataclass(frozen=True)
class SectionInfo:
    """A section of the library: ``kind`` is ``projects``, ``library`` or ``archive``."""

    folder: str
    depth: int
    kind: str

    def data(self) -> dict[str, Any]:
        return {"folder": self.folder, "depth": self.depth, "kind": self.kind}


@dataclass(frozen=True)
class Project:
    """A project folder: ``path`` below the library (``/``-separated), its section and
    whether that section is an archive."""

    path: str
    section: str
    archived: bool = False

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    def data(self) -> dict[str, Any]:
        return {"path": self.path, "name": self.name, "section": self.section, "archived": self.archived}


@dataclass
class FileState:
    """One tracked file in a status: ``state`` is new, changed, gone or unchanged.
    ``sha256`` is given when the file was read (it is not read when its size and time
    match its newest version). ``snapshot`` is that newest version."""

    path: str
    state: str
    size: int | None = None
    mtime_ns: int | None = None
    sha256: str | None = None
    snapshot: snapstore.Snapshot | None = field(default=None, repr=False)

    def data(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "state": self.state,
            "size": self.size,
            "modified_utc": _iso_ns(self.mtime_ns),
            "sha256": self.sha256,
            "version": None if self.snapshot is None else self.snapshot.id,
        }


@dataclass
class Status:
    """What :meth:`Vault.status` found. ``files`` holds the new, changed and gone files
    (and the unchanged ones when asked); ``counts`` counts every state; ``skipped``
    lists files that could not be looked at, with the reason."""

    library: str
    scope: str
    files: list[FileState]
    counts: dict[str, int]
    skipped: list[dict[str, Any]] = field(default_factory=list)
    hashed: int = 0

    def data(self) -> dict[str, Any]:
        return {
            "library": self.library,
            "scope": self.scope,
            "counts": dict(self.counts),
            "hashed": self.hashed,
            "files": [f.data() for f in self.files],
            "skipped": list(self.skipped),
        }


@dataclass
class CheckinResult:
    """What a check-in or a scan did: the record it wrote (None when a scan found
    nothing to store), each file with its state before the check-in, and the files that
    could not be stored."""

    checkin: Checkin | None
    files: list[FileState]
    failed: list[dict[str, Any]]
    scope: list[str]
    skipped: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, int] | None = None  # a scan's, from its status (its files leave out unchanged ones)

    def data(self) -> dict[str, Any]:
        c = self.checkin
        stored = {f.path: f for f in c.files} if c is not None else {}
        rows = []
        for f in self.files:
            entry = stored.get(f.path)
            rows.append(
                {
                    "path": f.path,
                    "state": f.state,
                    "sha256": entry.sha256 if entry is not None else f.sha256,
                    "size": entry.size if entry is not None else f.size,
                    "version": entry.snapshot if entry is not None else None,
                    "stored": bool(entry is not None and entry.new),
                }
            )
        counts = dict(self.counts) if self.counts is not None else {s: 0 for s in STATES}
        if self.counts is None:
            for f in self.files:
                counts[f.state] += 1
        return {
            "checkin": None if c is None else c.brief(),
            "record": None if c is None else c.record,
            "scope": list(self.scope),
            "counts": counts,
            "stored": sum(1 for r in rows if r["stored"]),
            "files": rows,
            "failed": list(self.failed),
            "skipped": list(self.skipped),
        }


# --------------------------------------------------------------------------- the vault
class Vault:
    """An opened library (:func:`init`, :func:`open_vault`)."""

    created = False  # True on the vault init has just made

    def __init__(self, root: str, settings: Settings) -> None:
        self.root = root
        self.folder = os.path.join(root, *VAULT_PARTS)
        self.settings = settings
        self.store = VaultStore(root)
        self._extensions = frozenset(registry.extensions("all")) | frozenset(DRAWING_EXPORTS)
        self._extensions |= frozenset(settings.tracked)
        self._ignore = [re.compile(fnmatch.translate(p.lower())) for p in settings.ignore]

    def __repr__(self) -> str:
        return f"<Vault {self.root!r}>"

    @property
    def library(self):
        """The common-parts library (:class:`~solidseas.pdm.library.Library`)."""
        from .library import Library

        return Library(self)

    def check(
        self,
        path: str | os.PathLike | None = None,
        *,
        plan: bool = False,
        fix: bool = False,
        copy_toolbox: bool = False,
        who: str | None = None,
    ) -> dict[str, Any]:
        """``pdm check``: whether each project holds every file its documents reference
        (:func:`solidseas.pdm.library.check`, ``docs/PDM.md`` 5)."""
        from .library import check

        return check(self, path, plan=plan, fix=fix, copy_toolbox=copy_toolbox, who=who)

    # ------------------------------------------------------------------ paths
    def relative(self, path: str | os.PathLike) -> str:
        """The path of ``path`` below the library, ``/``-separated (``""`` for the library
        itself). A path outside the library is ``path_refused`` (rule ``outside_library``)."""
        full = os.path.abspath(os.fspath(path))
        if os.path.normcase(full) == os.path.normcase(self.root):
            return ""
        try:
            return "/".join(relative_parts(full, self.root))
        except PathRefusedError:
            raise PathRefusedError(
                f"{full}: not inside the library at {self.root}", detail={"rule": "outside_library"}
            ) from None

    def absolute(self, rel: str) -> str:
        return os.path.join(self.root, *rel.split("/")) if rel else self.root

    def tracked(self, path: str | os.PathLike) -> bool:
        """Whether the file at ``path`` is one the vault keeps versions of: inside the
        library, in no hidden folder (such as ``.solidseas`` or ``.git``), with an extension
        of a CAD format SolidSeas lists, a drawing export (PDF, DXF) or ``tracked``, not a
        SOLIDWORKS lock file (``~$``) and matching no ``ignore`` pattern. The name alone
        decides; nothing on disk is looked at."""
        try:
            rel = self.relative(path)
        except PathRefusedError:
            return False
        return self._tracked_rel(rel)

    def _tracked_rel(self, rel: str) -> bool:
        if not rel:
            return False
        parts = rel.split("/")
        if any(p.startswith(".") for p in parts):
            return False
        name = parts[-1]
        if name.startswith("~$") or registry.extension_of(name) not in self._extensions:
            return False
        if self._ignore:
            low, low_name = rel.lower(), name.lower()
            if any(p.match(low) or p.match(low_name) for p in self._ignore):
                return False
        return True

    # ------------------------------------------------------------------ sections and projects
    def _top_folders(self) -> list[str]:
        out = []
        with os.scandir(self.root) as it:
            for e in it:
                if e.name.startswith(".") or not e.is_dir(follow_symlinks=False) or _is_link(e.path):
                    continue
                out.append(e.name)
        return sorted(out, key=str.casefold)

    def sections(self) -> list[SectionInfo]:
        """The library's sections as the settings name them (every top-level folder when
        they name none), each with its kind. A section folder that does not exist yet is
        listed all the same."""
        s = self.settings
        archive = {a.casefold() for a in s.archive}

        def kind(folder: str) -> str:
            if folder.casefold() == s.library.casefold():
                return "library"
            return "archive" if folder.casefold() in archive else "projects"

        if s.sections:
            return [SectionInfo(x.folder, x.depth, kind(x.folder)) for x in s.sections]
        return [SectionInfo(f, 1, kind(f)) for f in self._top_folders()]

    def _section(self, name: str) -> SectionInfo | None:
        for sec in self.sections() if self.settings.sections else ():
            if sec.folder.casefold() == name.casefold():
                return sec
        if self.settings.sections:
            return None
        s = self.settings
        kind = "library" if name.casefold() == s.library.casefold() else "projects"
        if kind == "projects" and name.casefold() in {a.casefold() for a in s.archive}:
            kind = "archive"
        return SectionInfo(name, 1, kind)

    def projects(self) -> list[Project]:
        """Every project folder: the folders ``depth`` levels below each section, the
        library section's excluded (it holds common parts, not projects). Hidden folders
        and links are passed over."""
        out: list[Project] = []
        for sec in self.sections():
            if sec.kind == "library":
                continue
            base = os.path.join(self.root, sec.folder)
            if _is_link(base) or not os.path.isdir(base):
                continue
            level = [(base, sec.folder)]
            for _ in range(sec.depth):
                nxt = []
                for folder, rel in level:
                    try:
                        with os.scandir(folder) as it:
                            entries = sorted(it, key=lambda e: e.name.casefold())
                    except OSError:
                        continue
                    for e in entries:
                        if e.name.startswith(".") or not e.is_dir(follow_symlinks=False) or _is_link(e.path):
                            continue
                        nxt.append((e.path, f"{rel}/{e.name}"))
                level = nxt
            out.extend(Project(rel, sec.folder, sec.kind == "archive") for _f, rel in level)
        return out

    def project_of(self, path: str | os.PathLike) -> Project | None:
        """The project the path lies in (or is, for a folder that exists); None for a
        path in the library section, outside every section or above a project's level."""
        try:
            rel = self.relative(path)
        except PathRefusedError:
            return None
        parts = rel.split("/") if rel else []
        if not parts:
            return None
        sec = self._section(parts[0])
        least = 1 + sec.depth if sec is not None else 0
        if not os.path.isdir(self.absolute(rel)):
            least += 1  # a file sits in its project, never is one
        if sec is None or sec.kind == "library" or len(parts) < least:
            return None
        if any(p.startswith(".") for p in parts[: 1 + sec.depth]):
            return None
        return Project("/".join(parts[: 1 + sec.depth]), sec.folder, sec.kind == "archive")

    # ------------------------------------------------------------------ walking
    def _walk(self, rel: str, skipped: list[dict[str, Any]]) -> Iterator[tuple[str, str, os.stat_result]]:
        """``(rel, full, lstat)`` of every tracked regular file below the folder ``rel``.
        Hidden folders are passed over; a link is never followed and is listed in
        ``skipped`` when it would have been tracked."""
        stack = [(self.absolute(rel), rel)]
        while stack:
            folder, frel = stack.pop()
            try:
                it = os.scandir(folder)
            except OSError as exc:
                skipped.append({"path": frel, "reason": _reason(exc)})
                continue
            with it:
                entries = list(it)
            for e in entries:
                name = e.name
                if name.startswith("."):
                    continue
                erel = f"{frel}/{name}" if frel else name
                try:
                    if e.is_symlink():  # a link to a folder, or to a file
                        if self._tracked_rel(erel) or e.is_dir():  # stat only: nothing is read
                            skipped.append({"path": erel, "reason": "link"})
                        continue
                    if e.is_dir(follow_symlinks=False):
                        if _is_link(e.path):  # a junction
                            skipped.append({"path": erel, "reason": "link"})
                        else:
                            stack.append((e.path, erel))
                        continue
                    if not self._tracked_rel(erel):
                        continue
                    st = e.stat(follow_symlinks=False)
                except OSError as exc:
                    skipped.append({"path": erel, "reason": _reason(exc)})
                    continue
                if stat.S_ISLNK(st.st_mode) or (sys.platform == "win32" and _is_link(e.path)):
                    skipped.append({"path": erel, "reason": "link"})
                    continue
                if not stat.S_ISREG(st.st_mode):
                    continue
                yield erel, e.path, st

    def _hash(self, full: str) -> tuple[str, int, int]:
        """``(sha256, size, mtime_ns)`` of the file, read once read-only below the library."""
        for _attempt in range(3):
            with open_readonly(full, within=self.root) as fh:
                before = os.fstat(fh.fileno())
                h = hashlib.sha256()
                n = 0
                while True:
                    chunk = fh.read(_CHUNK)
                    if not chunk:
                        break
                    h.update(chunk)
                    n += len(chunk)
                after = os.fstat(fh.fileno())
            if (before.st_size, before.st_mtime_ns) == (
                after.st_size,
                after.st_mtime_ns,
            ) and n == after.st_size:
                return h.hexdigest(), n, after.st_mtime_ns
        raise BusyError(
            "the file kept changing while it was read: try again once it is saved",
            detail={"rule": "file_changing"},
        )

    # ------------------------------------------------------------------ status
    def _scope(self, path: str | os.PathLike | None) -> tuple[str, bool]:
        """``(rel, is_file)`` of the path a command names (the library when None)."""
        if path is None:
            return "", False
        full = os.path.abspath(os.fspath(path))
        rel = self.relative(full)
        if rel and any(p.startswith(".") for p in rel.split("/")):
            raise PathRefusedError(
                f"{full}: a hidden folder of the library is never tracked", detail={"rule": "hidden"}
            )
        _refuse_link(full, "the path")
        if os.path.isdir(full):
            check_folder_within(full, self.root)
            return rel, False
        check_folder_within(os.path.dirname(full), self.root)
        if not self._tracked_rel(rel):
            raise InvalidArgumentError(
                f"{full}: not a file the vault tracks (a CAD file, or a drawing's PDF or DXF)",
                detail={"rule": "not_tracked", "parameter": "path"},
            )
        return rel, True

    def _removed(self) -> dict[str, datetime.datetime]:
        """When each file was last checked in as gone, keyed by its folded path."""
        out: dict[str, datetime.datetime] = {}
        for c in self.checkins():
            for f in c.files:
                if f.removed:
                    out[_folded(f.path)] = c.when
        return out

    def status(self, path: str | os.PathLike | None = None, *, unchanged: bool = False) -> Status:
        """Tracked files below ``path`` (a folder or one file; the library when None)
        that are new, changed since their newest version, or gone. A file whose size and
        modification time are those of its newest version is unchanged and not read.
        ``unchanged`` lists the unchanged files too (they are always counted)."""
        rel, is_file = self._scope(path)
        index = self.store.newest_all()
        counts = {s: 0 for s in STATES}
        files: list[FileState] = []
        skipped: list[dict[str, Any]] = []
        hashed = 0
        seen: set[str] = set()

        def look(frel: str, full: str, st: os.stat_result) -> None:
            nonlocal hashed
            key = _folded(frel)
            seen.add(key)
            snap = index.get(key)
            fs = FileState(frel, "new", st.st_size, st.st_mtime_ns, None, snap)
            if snap is not None:
                if snap.size == st.st_size and snap.mtime_ns == st.st_mtime_ns:
                    fs.state = "unchanged"
                else:
                    try:
                        fs.sha256, fs.size, fs.mtime_ns = self._hash(full)
                    except (OSError, SolidSeasError) as exc:
                        skipped.append({"path": frel, "reason": _reason(exc)})
                        return
                    hashed += 1
                    fs.state = "unchanged" if fs.sha256 == snap.sha256 else "changed"
            counts[fs.state] += 1
            if fs.state != "unchanged" or unchanged:
                files.append(fs)

        if is_file:
            full = self.absolute(rel)
            try:
                st = os.lstat(full)
            except FileNotFoundError:
                st = None
            if st is not None and stat.S_ISREG(st.st_mode):
                look(rel, full, st)
        else:
            for frel, full, st in self._walk(rel, skipped):
                look(frel, full, st)
        removed = None
        prefix = _folded(rel + "/") if rel else ""
        for key, snap in index.items():
            if key in seen:
                continue
            if is_file and key != _folded(rel):
                continue
            if not is_file and prefix and not key.startswith(prefix):
                continue
            if not self._tracked_rel(snap.path) or os.path.lexists(self.absolute(snap.path)):
                continue
            if removed is None:
                removed = self._removed()
            gone_at = removed.get(key)
            if gone_at is not None and gone_at >= snap.taken:
                continue  # checked in as gone
            counts["gone"] += 1
            files.append(FileState(snap.path, "gone", None, None, None, snap))
        files.sort(key=lambda f: (f.path.casefold(), f.path))
        skipped.sort(key=lambda s: s["path"])
        return Status(self.root, rel, files, counts, skipped, hashed)

    # ------------------------------------------------------------------ check-ins
    def checkins(self) -> list[Checkin]:
        """Every check-in record that holds up, oldest first. One that does not is skipped."""
        self.store._check_root()
        base = os.path.join(self.folder, "checkins")
        _refuse_link(base, "the vault's check-in folder")
        try:
            years = sorted(n for n in os.listdir(base) if YEAR_NAME.match(n))
        except (FileNotFoundError, NotADirectoryError):
            return []
        out = []
        for year in years:
            folder = os.path.join(base, year)
            if _is_link(folder) or not os.path.isdir(folder):
                continue
            for name in sorted(os.listdir(folder)):
                if not CHECKIN_NAME.match(name):
                    continue
                try:
                    with open_readonly(os.path.join(folder, name), within=self.folder) as fh:
                        data = fh.read(_MAX_READ)
                except (OSError, SolidSeasError):
                    continue
                c = parse_checkin(data, name, year)
                if c is not None:
                    out.append(c)
        out.sort(key=lambda c: (c.when, c.id))
        return out

    def _write_checkin(self, c: Checkin) -> Checkin:
        self.store._make_root()
        folder = self.store._folder(self.folder, "checkins", create=True)
        folder = self.store._folder(folder, f"{c.when.year:04d}", create=True)
        name = c.name()
        data = json.dumps(c.to_json(), ensure_ascii=True, sort_keys=True).encode("ascii")
        fd = os.open(os.path.join(folder, name), _NEW_FILE, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        return Checkin(
            c.id,
            c.when,
            c.note,
            c.who,
            c.revision,
            c.state,
            c.auto,
            c.solidseas,
            c.files,
            f"{c.when.year:04d}/{name}",
        )

    def _store_files(
        self, states: list[FileState], note: str | None, *, removals: bool
    ) -> tuple[list[CheckinFile], list[dict[str, Any]]]:
        entries: list[CheckinFile] = []
        failed: list[dict[str, Any]] = []
        snap_note = None if note is None else note[: snapstore.MAX_NOTE]
        for f in states:
            if f.state == "gone":
                if removals:
                    entries.append(CheckinFile(f.path, None, None, None, False, True))
                continue
            if f.state == "unchanged":
                if f.snapshot is not None:
                    entries.append(CheckinFile(f.path, f.snapshot.sha256, f.snapshot.size, f.snapshot.id))
                continue
            try:
                snap, new = self.store.add(self.absolute(f.path), note=snap_note)
            except (OSError, SolidSeasError) as exc:
                from ..model import error_code

                failed.append({"path": f.path, "code": error_code(exc), "message": str(exc)})
                continue
            entries.append(CheckinFile(f.path, snap.sha256, snap.size, snap.id, new))
        return entries, failed

    def _new_checkin(
        self,
        entries: list[CheckinFile],
        note: str | None,
        *,
        who: str,
        revision: str | None = None,
        state: str | None = None,
        auto: bool = False,
    ) -> Checkin:
        return self._write_checkin(
            Checkin(
                secrets.token_hex(6),
                datetime.datetime.now(datetime.UTC),
                note,
                who,
                revision,
                state,
                auto,
                __version__,
                tuple(entries),
            )
        )

    def checkin(
        self,
        paths: str | os.PathLike | list[str | os.PathLike],
        note: str,
        revision: str | None = None,
        state: str | None = None,
        who: str | None = None,
    ) -> CheckinResult:
        """Store a version of each new or changed tracked file under ``paths`` (files or
        folders) and write one check-in record with ``note``. Unchanged files are listed
        in the record with the version they already have and are not stored again; gone
        files are recorded as removed, so status stops listing them. ``revision`` and
        ``state`` are labels of at most 64 characters; ``who`` defaults to the settings'."""
        if not isinstance(note, str) or not note.strip() or len(note) > snapstore.MAX_NOTE or "\0" in note:
            raise InvalidArgumentError(
                f"a check-in needs a note of at most {snapstore.MAX_NOTE} characters",
                detail={"parameter": "note"},
            )
        for value, name in ((revision, "revision"), (state, "state")):
            if value is not None and not valid_label(value):
                raise InvalidArgumentError(
                    f"{name} is text of at most {MAX_LABEL} characters", detail={"parameter": name}
                )
        who = self.settings.who if who is None else who
        if not isinstance(who, str) or len(who) > MAX_WHO or any(ord(c) < 32 for c in who):
            raise InvalidArgumentError(
                f"who is a name of at most {MAX_WHO} characters", detail={"parameter": "who"}
            )
        if isinstance(paths, (str, os.PathLike)):
            paths = [paths]
        if not paths:
            raise InvalidArgumentError(
                "name at least one file or folder to check in", detail={"parameter": "paths"}
            )
        states: dict[str, FileState] = {}
        scope: list[str] = []
        skipped: list[dict[str, Any]] = []
        for p in paths:
            st = self.status(p, unchanged=True)
            scope.append(st.scope)
            skipped.extend(st.skipped)
            for f in st.files:
                states.setdefault(_folded(f.path), f)
        ordered = sorted(states.values(), key=lambda f: (f.path.casefold(), f.path))
        if not ordered:
            raise InvalidArgumentError(
                "there is no tracked file there to check in",
                detail={"rule": "nothing_tracked", "parameter": "paths"},
            )
        if len(ordered) > MAX_CHECKIN_FILES:
            raise InvalidArgumentError(
                f"a check-in holds at most {MAX_CHECKIN_FILES:,} files: check in a smaller folder",
                detail={"parameter": "paths"},
            )
        entries, failed = self._store_files(ordered, note, removals=True)
        record = (
            self._new_checkin(entries, note, who=who, revision=revision, state=state) if entries else None
        )
        return CheckinResult(record, ordered, failed, scope, skipped)

    def scan(self, path: str | os.PathLike | None = None) -> CheckinResult:
        """Store a version of every new or changed tracked file below ``path`` (the
        library when None), as an automatic check-in with no note. Nothing is written when
        nothing changed, so it is safe to run on a schedule. Gone files are only reported."""
        st = self.status(path)
        changed = [f for f in st.files if f.state in ("new", "changed")]
        entries, failed = self._store_files(changed, None, removals=False)
        record = self._new_checkin(entries, None, who=self.settings.who, auto=True) if entries else None
        return CheckinResult(record, st.files, failed, [st.scope], st.skipped, dict(st.counts))

    # ------------------------------------------------------------------ history
    def _file(self, path: str | os.PathLike) -> tuple[str, str]:
        full = os.path.abspath(os.fspath(path))
        rel = self.relative(full)
        if not self._tracked_rel(rel):
            raise InvalidArgumentError(
                f"{full}: not a file the vault tracks (a CAD file, or a drawing's PDF or DXF)",
                detail={"rule": "not_tracked", "parameter": "path"},
            )
        check_folder_within(os.path.dirname(full), self.root)
        _refuse_link(full, "the file")
        return full, rel

    def _timeline(self, full: str, source: str):
        from .. import versions

        if source not in ("vault", "git"):
            raise InvalidArgumentError("source is vault or git", detail={"parameter": "source"})
        if source == "git":
            return versions.timeline(full, source="git")
        return versions.timeline(full, source="snapshots", store=self.store)

    def log(self, path: str | os.PathLike) -> dict[str, Any]:
        """The file's versions, newest first: the vault's, each with the check-ins that
        name it (note, revision, state, who), and the Git commits that changed it when the
        file sits in a Git repository. The working copy is on top when it differs from the
        newest version in the vault."""
        from .. import versions
        from ..versions import gitrepo

        full, rel = self._file(path)
        by_snapshot: dict[str, list[dict[str, Any]]] = {}
        key = _folded(rel)
        for c in self.checkins():
            for f in c.files:
                if f.snapshot is not None and _folded(f.path) == key:
                    by_snapshot.setdefault(f.snapshot, []).insert(0, c.brief())  # newest first
        entries: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        with self._timeline(full, "vault") as t:
            working = t.working.data()
            for v in t.versions:
                row = _log_row(v.data(), "working" if v.kind == "working" else "vault")
                if v.kind == "snapshot":
                    row["checkins"] = by_snapshot.get(v.id, [])
                entries.append(row)
        git = None
        repo = gitrepo.find_repository(full)
        if repo is not None:
            repo.close()
            try:
                with versions.timeline(full, source="git") as g:
                    git = {k: g.git[k] for k in ("work_tree", "path", "branch", "head")}
                    warnings.extend(g.warnings)
                    for v in g.stored:
                        entries.append(_log_row(v.data(), "git"))
            except (OSError, SolidSeasError) as exc:
                from ..model import error_code

                warnings.append(
                    {
                        "code": "git_unreadable",
                        "stream": None,
                        "message": f"the Git history could not be read ({error_code(exc)}): {exc}",
                    }
                )
        top = [e for e in entries if e["source"] == "working"]
        rest = sorted(
            (e for e in entries if e["source"] != "working"),
            key=lambda e: (e["time_utc"] or "", e["number"] or 0),
            reverse=True,
        )
        return {
            "file": {"name": os.path.basename(full), "path": full},
            "path": rel,
            "working": working,
            "git": git,
            "versions": top + rest,
            "warnings": warnings,
        }

    def show(self, path: str | os.PathLike, version: str, *, source: str = "vault") -> dict[str, Any]:
        """One version's facts: the version, its document (format, type, release that
        saved it), its properties and configurations, and its geometry's counts and
        fingerprint per configuration (``docs/VERSIONS.md`` 5)."""
        from ..versions import DEFAULT_MAX_VERSION_BYTES
        from ..versions.versiondiff import Side, _document_brief

        full, _rel = self._file(path)
        with self._timeline(full, source) as t:
            v = t.find(version)
            data = t.read(v, limit=DEFAULT_MAX_VERSION_BYTES)
            v.sha256 = v.sha256 or hashlib.sha256(data).hexdigest()
            with Side(data, os.path.basename(full)) as side:
                summary = side.summary
                return {
                    "file": {"name": os.path.basename(full), "path": full},
                    "source": t.source,
                    "version": v.data(),
                    "document": _document_brief(summary),
                    "properties": list(summary.get("properties") or []),
                    "configurations": [c.get("name") for c in summary.get("configurations") or []],
                    "geometry": {
                        "reason": side.geometry_reason,
                        "configurations": [
                            {"configuration": name, "summary": g} for name, g in side.geometry.items()
                        ],
                    },
                    "warnings": list(t.warnings) + list(side.warnings),
                }

    def diff(
        self,
        path: str | os.PathLike,
        older: str | None = None,
        newer: str | None = None,
        *,
        source: str = "vault",
        measure: bool = True,
        max_seconds: float = 60.0,
    ) -> dict[str, Any]:
        """``version_diff`` data between two versions of the file (``docs/VERSIONS.md`` 6),
        from the vault (or Git with ``source="git"``), named as ``pdm log`` lists them."""
        from .. import versions

        full, _rel = self._file(path)
        if source not in ("vault", "git"):
            raise InvalidArgumentError("source is vault or git", detail={"parameter": "source"})
        if source == "git":
            return versions.compare(
                full, older, newer, source="git", measure=measure, max_seconds=max_seconds
            )
        return versions.compare(
            full, older, newer, source="snapshots", store=self.store, measure=measure, max_seconds=max_seconds
        )

    # ------------------------------------------------------------------ restore
    def restore(
        self, path: str | os.PathLike, version: str, as_name: str | None = None, *, who: str | None = None
    ) -> dict[str, Any]:
        """Put a version of the file back from the vault. The current file, when there is
        one, is stored as a version first. Without ``as_name`` the file is replaced; with
        it, the version is written as a new file of that name in the same folder, which
        must not exist. Either way it is written through a temporary name and a rename,
        never through a link, and the restored file is checked in with a note."""
        from ..versions import DEFAULT_MAX_VERSION_BYTES

        full, rel = self._file(path)
        folder = os.path.dirname(full)
        target = full
        if as_name is not None:
            if (
                not isinstance(as_name, str)
                or component_problem(as_name) is not None
                or any(c in '/\\<>"|?*' for c in as_name)
                or as_name.startswith(".")
            ):
                raise InvalidArgumentError(
                    "--as takes a file name for the same folder, without a folder", detail={"parameter": "as"}
                )
            target = os.path.join(folder, as_name)
            if not self._tracked_rel(self.relative(target)):
                raise InvalidArgumentError(
                    f"{as_name}: not a name the vault tracks: keep the file's extension",
                    detail={"rule": "not_tracked", "parameter": "as"},
                )
            if os.path.lexists(target):
                raise OutputRefusedError(
                    f"{target} already exists: a restore never writes over another file",
                    detail={"rule": "exists"},
                )
        with self._timeline(full, "vault") as t:  # named before the current file is stored
            v = t.find(version)
            if v.kind != "snapshot":
                raise InvalidArgumentError(
                    "name a version stored in the vault: vN, latest or its id",
                    detail={"parameter": "version"},
                )
            data = t.read(v, limit=DEFAULT_MAX_VERSION_BYTES)
            vdata = v.data()
        name = f"v{vdata['number']}"
        current = _regular_or_none(full)
        stored_first = None
        if current is not None:
            snap, new = self.store.add(full, note=f"stored before restoring {name}")
            stored_first = {"version": snap.id, "new": new, "sha256": snap.sha256}
            current = _regular_or_none(full)
        written = not (target == full and stored_first is not None and stored_first["sha256"] == v.sha256)
        record = None
        if written:  # else the file already holds that version
            tmp = _write_temp(folder, data)
            try:
                if target == full and current is not None:
                    now = _regular_or_none(full)
                    if now is None or (now.st_size, now.st_mtime_ns) != (
                        current.st_size,
                        current.st_mtime_ns,
                    ):
                        raise BusyError(
                            "the file changed while the version was put back: try again once it is saved",
                            detail={"rule": "file_changing"},
                        )
                    os.replace(tmp, full)
                else:
                    _rename_new(tmp, target)
            finally:
                if os.path.lexists(tmp):
                    os.remove(tmp)
            note = f"Restored {name} ({v.id})" + (f" from {rel}" if target != full else "")
            snap, new = self.store.add(target, note=note)
            record = self._new_checkin(
                [CheckinFile(self.relative(target), snap.sha256, snap.size, snap.id, new)],
                note,
                who=self.settings.who if who is None else who,
            )
        return {
            "file": {"name": os.path.basename(target), "path": target},
            "path": self.relative(target),
            "from": rel,
            "version": vdata,
            "replaced": target == full and current is not None and written,
            "written": written,
            "stored_first": stored_first,
            "checkin": None if record is None else record.brief(),
        }


_MAX_READ = 32 << 20


def _log_row(v: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "source": source,
        "number": v["number"] if source != "git" else None,
        "id": v["id"],
        "time_utc": v["time_utc"],
        "author": v["author"],
        "subject": v["subject"],
        "status": v["status"],
        "size": v["size"],
        "sha256": v["sha256"],
        "available": v["available"],
        "checkins": [],
    }


def _reason(exc: BaseException) -> str:
    from ..model import error_code

    return error_code(exc)


def _regular_or_none(path: str) -> os.stat_result | None:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    if _is_link(path):
        raise LinkRefusedError(
            f"{path}: the file is a link, which is never written through", detail={"rule": "link"}
        )
    if not stat.S_ISREG(st.st_mode):
        raise PathRefusedError(f"{path}: not a regular file", detail={"rule": "not_a_file"})
    return st


def _write_temp(folder: str, data: bytes) -> str:
    tmp = os.path.join(folder, f".solidseas-restore-{secrets.token_hex(8)}.tmp")
    fd = os.open(tmp, _NEW_FILE, 0o644)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        if os.path.lexists(tmp):
            os.remove(tmp)
        raise
    return tmp


def _rename_new(tmp: str, final: str) -> None:
    """Move ``tmp`` to ``final``, which must not exist: never over another file."""
    if sys.platform == "win32":
        try:
            os.rename(tmp, final)  # Windows refuses an existing name
        except FileExistsError:
            raise OutputRefusedError(f"{final} already exists", detail={"rule": "exists"}) from None
        return
    try:
        os.link(tmp, final)  # fails on an existing name, link or not
    except FileExistsError:
        raise OutputRefusedError(f"{final} already exists", detail={"rule": "exists"}) from None
    except OSError:
        if os.path.lexists(final):
            raise OutputRefusedError(f"{final} already exists", detail={"rule": "exists"}) from None
        os.rename(tmp, final)  # a file system without hard links
        return
    os.remove(tmp)


# --------------------------------------------------------------------------- opening
def _settings_path(root: str) -> str:
    return os.path.join(root, *VAULT_PARTS, SETTINGS_NAME)


def _read_settings(root: str) -> Settings:
    path = _settings_path(root)
    cur = root
    for name in VAULT_PARTS:
        cur = os.path.join(cur, name)
        _refuse_link(cur, "a folder of the vault")
    with open_readonly(path, within=root) as fh:
        data = fh.read(2 << 20)
    return Settings.loads(data)


def _has_vault(folder: str) -> bool:
    st = snapstore.lstat_within(folder, (*VAULT_PARTS, SETTINGS_NAME))
    return st is not None and stat.S_ISREG(st.st_mode)


def find_library(path: str | os.PathLike) -> str | None:
    """The library that holds ``path``: the nearest folder at or above it with a
    ``.solidseas/vault/vault.json``; None when there is none."""
    cur = os.path.abspath(os.fspath(path))
    if not os.path.isdir(cur):
        cur = os.path.dirname(cur)
    while True:
        if _has_vault(cur):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def open_vault(path: str | os.PathLike = ".") -> Vault:
    """The library that holds ``path`` (a file or folder in it), found by walking up to
    the nearest ``.solidseas/vault/vault.json``. ``invalid_argument`` (rule
    ``not_a_library``) when there is none."""
    root = find_library(path)
    if root is None:
        raise InvalidArgumentError(
            f"{os.path.abspath(os.fspath(path))} is not in a library: make one with "
            "solidseas pdm init FOLDER",
            detail={"rule": "not_a_library"},
        )
    return Vault(root, _read_settings(root))


def init(folder: str | os.PathLike, *, settings: Settings | None = None) -> Vault:
    """Make ``folder`` a library: its ``.solidseas/vault`` with ``vault.json``, an empty
    store and check-in folder. Nothing else in the folder is changed. A folder that
    already is a library is opened as it is (the vault's ``created`` is False then). A
    folder inside another library is refused."""
    root = os.path.abspath(os.fspath(folder))
    if not os.path.isdir(root):
        raise FileNotFoundError(2, "the folder does not exist", root)
    if _has_vault(root):
        return Vault(root, _read_settings(root))
    parent = find_library(os.path.dirname(root))
    if parent is not None and parent != root:
        raise InvalidArgumentError(
            f"{root} is inside the library at {parent}: a library cannot hold another",
            detail={"rule": "inside_library"},
        )
    settings = settings or Settings()
    vault = Vault(root, settings)
    vault.store._make_root()
    vault.store._folder(vault.folder, "checkins", create=True)
    tmp = os.path.join(vault.folder, f".tmp-{secrets.token_hex(8)}")
    fd = os.open(tmp, _NEW_FILE, 0o644)
    with os.fdopen(fd, "wb") as out:
        out.write(settings.dumps())
        out.flush()
        os.fsync(out.fileno())
    try:
        _rename_new(tmp, _settings_path(root))
    except OutputRefusedError:
        return Vault(root, _read_settings(root))  # made meanwhile
    finally:
        if os.path.lexists(tmp):
            os.remove(tmp)
    vault.created = True
    return vault


__all__ = [
    "CheckinResult",
    "FileState",
    "Project",
    "SectionInfo",
    "Status",
    "Vault",
    "VaultStore",
    "find_library",
    "init",
    "open_vault",
]
