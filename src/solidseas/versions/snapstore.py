"""SolidSeas' own snapshots of a file: content-addressed copies kept outside Git
(provisional, ``docs/VERSIONS.md`` section 4).

A store is a folder:

* ``objects/<2 hex>/<64 hex>``: each distinct content once, named by its SHA-256;
* ``files/<32 hex>/<time>-<id>.json``: one small record per snapshot of one file, in
  the folder of that file's key (the SHA-256 of its path, folded on Windows and macOS).

**Where.** In the user's data folder by default (:func:`data_dir`, ``history`` in it),
in ``<project>/.solidseas/history`` only when the caller names the project, or in a
folder the caller names. Never beside a source document otherwise.

**Never through a link.** Every folder from the store down is checked with ``lstat``
before it is used, and made owner-only on Linux and macOS. Records and objects are
created with ``O_EXCL``, so never over an existing name and never through a link
planted under that name; an object is copied to a temporary name, its hash checked,
then renamed into place. The source is read with
:func:`~solidseas.formats.solidworks._io.open_readonly` within its own folder: a file
that is a link, a cloud placeholder or not a regular file is refused, and a file that
changes while it is copied is not kept (``busy``, rule ``file_changing``).

**No shared file is rewritten**, so two processes, or two people sharing a project's
store, never lose each other's snapshots, and no lock is needed: unlike the catalog's
SQLite, the store may live on a network share when the project does.

**Reading.** Every record is checked field by field and skipped when it does not hold
up or names another file; every object is hashed again before it is used, and one
that does not match is ``damaged_file`` (rule ``snapshot_object``).
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import secrets
import stat
import sys
from dataclasses import dataclass
from typing import Any

from .. import __version__
from ..errors import (
    BusyError,
    FileTooLargeError,
    InvalidArgumentError,
    LinkRefusedError,
    PathRefusedError,
    SolidSeasError,
    VersionUnavailableError,
)
from ..formats.solidworks._io import open_readonly, relative_parts
from ..resolve.names import fold
from .gitrepo import _is_link, lstat_within

STORE_FOLDER = "history"
PROJECT_FOLDER = ".solidseas"
LOCATIONS = ("data", "project", "folder")
RECORD_VERSION = 1
MAX_RECORDS = 10_000  # the newest records of one file read
MAX_RECORD_BYTES = 64 << 10
MAX_NOTE = 1000
COPY_CHUNK = 1 << 20
_RECORD_NAME = re.compile(r"(\d{8}T\d{12}Z)-([0-9a-f]{12})\.json\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_FOLD_PATHS = sys.platform in ("win32", "darwin")
_O_BINARY = getattr(os, "O_BINARY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


class SnapshotDamagedError(SolidSeasError):
    """A stored snapshot's content does not match its hash: ``damaged_file``, rule
    ``snapshot_object``."""

    code = "damaged_file"

    def __init__(self, message: str) -> None:
        super().__init__(message, detail={"rule": "snapshot_object"})


def data_dir() -> str:
    """The folder SolidSeas keeps the user's own data in: ``SOLIDSEAS_DATA_DIR`` when that
    is set; else ``%LOCALAPPDATA%\\SolidSeas`` on Windows (the catalogs' base, which
    Windows does not roam) and ``$XDG_DATA_HOME/solidseas`` (``~/.local/share/solidseas``)
    elsewhere. Snapshots are not a cache: nothing can make them again, so they are not
    kept in the cache folder. Nothing is made."""
    env = os.environ.get("SOLIDSEAS_DATA_DIR")
    if env:
        return os.path.abspath(env)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(base, "SolidSeas")
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "solidseas")


def utc_stamp(when: datetime.datetime) -> str:
    return when.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class Snapshot:
    """One snapshot of a file: its ``id`` (12 hex digits), when it was taken (UTC), the
    SHA-256 and size of the content, the path it was taken from (absolute, or below the
    project for a project's store), the file's modification time then, the note given
    with it and the SolidSeas version that took it."""

    id: str
    taken: datetime.datetime
    sha256: str
    size: int
    path: str
    mtime_ns: int | None
    note: str | None
    solidseas: str
    record: str

    def to_json(self) -> dict[str, Any]:
        return {
            "v": RECORD_VERSION,
            "id": self.id,
            "taken_utc": utc_stamp(self.taken),
            "sha256": self.sha256,
            "size": self.size,
            "path": self.path,
            "mtime_ns": None if self.mtime_ns is None else str(self.mtime_ns),
            "note": self.note,
            "solidseas": self.solidseas,
        }


def _parse_time(text: Any) -> datetime.datetime | None:
    if not isinstance(text, str) or len(text) > 40 or not text.endswith("Z"):
        return None
    try:
        when = datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        return None
    return when.replace(tzinfo=datetime.UTC)


def parse_record(data: bytes, name: str) -> Snapshot | None:
    """The snapshot a record file holds, or None when any field does not hold up. A
    record is data from a folder others may write to (a project's store): nothing in it
    is trusted until checked."""
    m = _RECORD_NAME.match(name)
    if m is None or len(data) > MAX_RECORD_BYTES:
        return None
    try:
        obj = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(obj, dict) or obj.get("v") != RECORD_VERSION:
        return None
    sid, sha, size, path = obj.get("id"), obj.get("sha256"), obj.get("size"), obj.get("path")
    mtime, note, made_by = obj.get("mtime_ns"), obj.get("note"), obj.get("solidseas")
    taken = _parse_time(obj.get("taken_utc"))
    if (
        sid != m.group(2)
        or not isinstance(sha, str)
        or not _SHA256.match(sha)
        or isinstance(size, bool)
        or not isinstance(size, int)
        or not 0 <= size <= 2**53 - 1
        or not isinstance(path, str)
        or not 0 < len(path) <= 4096
        or "\0" in path
        or taken is None
        or (mtime is not None and (not isinstance(mtime, str) or not re.fullmatch(r"-?\d{1,20}", mtime)))
        or (note is not None and (not isinstance(note, str) or len(note) > MAX_NOTE))
        or not isinstance(made_by, str)
        or len(made_by) > 40
    ):
        return None
    return Snapshot(sid, taken, sha, size, path, None if mtime is None else int(mtime), note, made_by, name)


class SnapshotStore:
    """One store (:func:`open_store`). ``location`` is ``data``, ``project`` or
    ``folder``; ``project`` the project folder for a project's store."""

    def __init__(self, root: str, location: str, project: str | None = None) -> None:
        self.root = root
        self.location = location
        self.project = project

    def __repr__(self) -> str:
        return f"<SnapshotStore {self.location} {self.root!r}>"

    # ------------------------------------------------------------------ keys
    def recorded_path(self, path: str) -> str:
        """The path a record keeps for the file at ``path``: absolute, or ``/``-separated
        below the project for a project's store (so the store keeps working when the
        project folder moves)."""
        full = os.path.abspath(os.fspath(path))
        if self.location != "project":
            return full
        try:
            parts = relative_parts(full, self.project)
        except PathRefusedError:
            raise PathRefusedError(
                "the file is not inside the project whose store was named", detail={"rule": "outside_project"}
            ) from None
        return "/".join(parts)

    @staticmethod
    def _same_path(a: str, b: str) -> bool:
        return fold(a) == fold(b) if _FOLD_PATHS else a == b

    def key(self, path: str) -> str:
        text = self.recorded_path(path)
        if _FOLD_PATHS:
            text = fold(text)
        return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()[:32]

    # ------------------------------------------------------------------ folders
    def _check_root(self) -> None:
        """Refuse a store whose own folder, or a project's ``.solidseas`` folder, is a link."""
        folders = [self.root]
        if self.location == "project":
            folders.insert(0, os.path.join(self.project, PROJECT_FOLDER))
        for folder in folders:
            if _is_link(folder):
                raise LinkRefusedError(
                    f"{folder}: a folder of the snapshot store is a link, which is never followed",
                    detail={"rule": "link"},
                )

    def _make_root(self) -> None:
        from ..catalog.store import make_private_dir

        self._check_root()
        if self.location == "project":
            folder = os.path.join(self.project, PROJECT_FOLDER)
            make_private_dir(folder)
            self._folder(folder, STORE_FOLDER, create=True)
        else:
            make_private_dir(self.root)

    @staticmethod
    def _folder(base: str, name: str, *, create: bool) -> str:
        """``base/name``, a real folder: made owner-only when ``create`` and missing; a link
        or a file there is refused."""
        path = os.path.join(base, name)
        if create:
            try:
                os.mkdir(path, 0o700)
            except FileExistsError:
                pass
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            if create:
                raise
            return path
        if _is_link(path):
            raise LinkRefusedError(
                f"{path}: a folder of the snapshot store is a link, which is never written through",
                detail={"rule": "link"},
            )
        if not stat.S_ISDIR(st.st_mode):
            raise PathRefusedError(
                f"{path}: the snapshot store holds a file where a folder belongs",
                detail={"rule": "not_a_folder"},
            )
        return path

    def _folders(self, *names: str, create: bool) -> str:
        cur = self.root
        for name in names:
            cur = self._folder(cur, name, create=create)
        return cur

    # ------------------------------------------------------------------ reading
    def snapshots(self, path: str) -> list[Snapshot]:
        """The snapshots of the file at ``path``, oldest first."""
        recorded = self.recorded_path(path)
        self._check_root()
        st = lstat_within(self.root, ("files", self.key(path)))
        if st is None or not stat.S_ISDIR(st.st_mode):
            return []
        folder = os.path.join(self.root, "files", self.key(path))
        names = sorted(n for n in os.listdir(folder) if _RECORD_NAME.match(n))[-MAX_RECORDS:]
        out = []
        for name in names:
            try:
                with open_readonly(os.path.join(folder, name), within=self.root) as fh:
                    data = fh.read(MAX_RECORD_BYTES + 1)
            except (OSError, SolidSeasError):
                continue  # one unreadable record never hides the others
            snap = parse_record(data, name)
            if snap is not None and self._same_path(snap.path, recorded):
                out.append(snap)
        out.sort(key=lambda s: (s.taken, s.record))
        return out

    def object_path(self, sha256: str) -> str:
        if not _SHA256.match(sha256):
            raise InvalidArgumentError("not a SHA-256", detail={"parameter": "sha256"})
        return os.path.join(self.root, "objects", sha256[:2], sha256)

    def has_object(self, sha256: str, size: int) -> bool:
        st = lstat_within(self.root, ("objects", sha256[:2], sha256))
        return st is not None and stat.S_ISREG(st.st_mode) and st.st_size == size

    def read(self, snap: Snapshot, *, limit: int) -> bytes:
        """The content of a snapshot, hashed again before it is returned."""
        if snap.size > limit:
            raise FileTooLargeError(
                "the snapshot is larger than the configured maximum",
                detail={"limit": limit, "value": snap.size},
            )
        self._check_root()
        try:
            with open_readonly(self.object_path(snap.sha256), within=self.root) as fh:
                data = fh.read(snap.size + 1)
        except FileNotFoundError:
            raise VersionUnavailableError(
                "the snapshot's stored copy is not in the store any more", detail={"rule": "snapshot_missing"}
            ) from None
        if len(data) != snap.size or hashlib.sha256(data).hexdigest() != snap.sha256:
            raise SnapshotDamagedError("the snapshot's stored copy does not match its hash")
        return data

    # ------------------------------------------------------------------ writing
    def add(
        self, path: str, *, note: str | None = None, max_file_bytes: int | None = None
    ) -> tuple[Snapshot, bool]:
        """Take a snapshot of the file at ``path``: ``(snapshot, new)``. When the file's
        content is that of its newest snapshot, nothing is written and that snapshot is
        returned with ``new`` False."""
        if note is not None and (not isinstance(note, str) or len(note) > MAX_NOTE or "\0" in note):
            raise InvalidArgumentError(
                f"a note is text of at most {MAX_NOTE} characters", detail={"parameter": "note"}
            )
        full = os.path.abspath(os.fspath(path))
        recorded = self.recorded_path(full)
        self._make_root()
        objects = self._folders("objects", create=True)
        tmp = os.path.join(objects, f".tmp-{secrets.token_hex(8)}")
        h = hashlib.sha256()
        count = 0
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY | _O_NOFOLLOW | _O_CLOEXEC, 0o600)
        try:
            with os.fdopen(fd, "wb") as out:
                with open_readonly(full, within=os.path.dirname(full)) as src:
                    before = os.fstat(src.fileno())
                    if max_file_bytes is not None and before.st_size > max_file_bytes:
                        raise FileTooLargeError(
                            "the file is larger than the configured maximum",
                            detail={"limit": max_file_bytes, "value": before.st_size},
                        )
                    while True:
                        chunk = src.read(COPY_CHUNK)
                        if not chunk:
                            break
                        h.update(chunk)
                        out.write(chunk)
                        count += len(chunk)
                    after = os.fstat(src.fileno())
                out.flush()
                os.fsync(out.fileno())
            if (before.st_size, before.st_mtime_ns) != (
                after.st_size,
                after.st_mtime_ns,
            ) or count != before.st_size:
                raise BusyError(
                    "the file changed while it was copied: take the snapshot again once it is saved",
                    detail={"rule": "file_changing"},
                )
            sha = h.hexdigest()
            existing = self.snapshots(full)
            same = bool(existing) and existing[-1].sha256 == sha
            if not (same and self._intact(sha, count)):
                self._place(tmp, sha, count)  # a newest snapshot whose copy is damaged or gone gets it back
            if same:
                return existing[-1], False
        finally:
            if os.path.lexists(tmp):
                os.remove(tmp)
        snap = Snapshot(
            secrets.token_hex(6),
            datetime.datetime.now(datetime.UTC),
            sha,
            count,
            recorded,
            after.st_mtime_ns,
            note,
            __version__,
            "",
        )
        return self._write_record(full, snap), True

    def _intact(self, sha: str, size: int) -> bool:
        """Whether the object named ``sha`` holds content of that hash and size."""
        h = hashlib.sha256()
        n = 0
        try:
            with open_readonly(self.object_path(sha), within=self.root) as fh:
                while True:
                    chunk = fh.read(COPY_CHUNK)
                    if not chunk:
                        break
                    h.update(chunk)
                    n += len(chunk)
        except FileNotFoundError:
            return False
        return n == size and h.hexdigest() == sha

    def _place(self, tmp: str, sha: str, size: int) -> None:
        """Move the copy at ``tmp`` to its object name, keeping an object already there
        only when its content is intact; any other is replaced by the copy."""
        folder = self._folders("objects", sha[:2], create=True)
        final = os.path.join(folder, sha)
        for _ in range(2):
            try:
                st = os.lstat(final)
            except FileNotFoundError:
                try:
                    os.rename(tmp, final)  # Windows refuses an existing name: then the loop looks again
                    return
                except FileExistsError:
                    continue
            if _is_link(final) or not stat.S_ISREG(st.st_mode):
                raise LinkRefusedError(
                    f"{final}: the snapshot store holds a link or another kind of file there, which is never "
                    "written through",
                    detail={"rule": "link"},
                )
            if st.st_size == size and self._intact(sha, size):
                return  # the same content, stored before
            os.replace(tmp, final)  # a damaged copy: replaced by this one
            return

    def _write_record(self, full: str, snap: Snapshot) -> Snapshot:
        folder = self._folders("files", self.key(full), create=True)
        stamp = snap.taken.strftime("%Y%m%dT%H%M%S%f") + "Z"
        name = f"{stamp}-{snap.id}.json"
        path = os.path.join(folder, name)
        data = json.dumps(snap.to_json(), ensure_ascii=True, sort_keys=True).encode("ascii")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY | _O_NOFOLLOW | _O_CLOEXEC, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        return Snapshot(
            snap.id,
            snap.taken,
            snap.sha256,
            snap.size,
            snap.path,
            snap.mtime_ns,
            snap.note,
            snap.solidseas,
            name,
        )


def open_store(
    *, project: str | os.PathLike | None = None, store: str | os.PathLike | SnapshotStore | None = None
) -> SnapshotStore:
    """The store to read or write: ``store`` (a folder, or a :class:`SnapshotStore` such as
    a PDM vault's, returned as it is), else the project's (``<project>/.solidseas/history``),
    else the user's own (``data_dir()/history``). Nothing is made until a snapshot is taken."""
    if project is not None and store is not None:
        raise InvalidArgumentError("name a project or a store, not both", detail={"parameter": "store"})
    if isinstance(store, SnapshotStore):
        return store
    if store is not None:
        root = os.path.abspath(os.fspath(store))
        if root.replace("/", "\\").startswith(("\\\\?\\", "\\\\.\\")):
            raise PathRefusedError(
                "device and long-path prefixes are not accepted", detail={"rule": "device_path"}
            )
        return SnapshotStore(root, "folder")
    if project is not None:
        folder = os.path.abspath(os.fspath(project))
        if not os.path.isdir(folder):
            raise FileNotFoundError(2, "the project folder does not exist", folder)
        return SnapshotStore(os.path.join(folder, PROJECT_FOLDER, STORE_FOLDER), "project", folder)
    return SnapshotStore(os.path.join(data_dir(), STORE_FOLDER), "data")


__all__ = [
    "LOCATIONS",
    "Snapshot",
    "SnapshotDamagedError",
    "SnapshotStore",
    "data_dir",
    "open_store",
    "parse_record",
]
