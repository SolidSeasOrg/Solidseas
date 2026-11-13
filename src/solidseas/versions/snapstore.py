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

**Flushed in batches.** :meth:`SnapshotStore.add_many` copies many files at once and
flushes them to disk a batch at a time, in an order that keeps a crash harmless: the
copies before they get their object names, the objects and their folders before any
record that names them, the records before the caller writes anything that names them
(``docs/VERSIONS.md`` 4.3).

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
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
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
BATCH_FILES = 1000  # files copied before a batch is flushed to disk at once
COPY_WORKERS = 4  # files copied at once: the work waits on the disk, not the processor
SYNC_WORKERS = 32  # flushes at once: the disk commits flushes that wait together in one go
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
        (result,) = self.add_many([path], note=note, max_file_bytes=max_file_bytes, workers=1)
        if isinstance(result, BaseException):
            raise result
        return result

    def add_many(
        self,
        paths: list[str],
        *,
        note: str | None = None,
        max_file_bytes: int | None = None,
        workers: int | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> list[tuple[Snapshot, bool] | OSError | SolidSeasError]:
        """Take a snapshot of each file in ``paths``, as :meth:`add` does, and return one
        result per path in the same order: ``(snapshot, new)``, or the error that file met
        (any other error is raised). Files are copied ``workers`` at a time and flushed
        to disk in batches of :data:`BATCH_FILES`, :data:`SYNC_WORKERS` flushes at once:
        every copy of a batch is flushed before it gets its object name, and every object
        and its folder before the first record that names it is written; the records are
        created in the order of ``paths`` and flushed with their folders before this
        returns. ``progress(done, bytes)`` is called as copies finish."""
        if note is not None and (not isinstance(note, str) or len(note) > MAX_NOTE or "\0" in note):
            raise InvalidArgumentError(
                f"a note is text of at most {MAX_NOTE} characters", detail={"parameter": "note"}
            )
        if workers is None:
            workers = COPY_WORKERS
        fulls = [os.path.abspath(os.fspath(p)) for p in paths]
        results: list[Any] = [None] * len(fulls)
        if not fulls:
            return results
        self._make_root()
        objects = self._folders("objects", create=True)
        done = [0, 0]
        many = len(fulls) > 1
        pool = ThreadPoolExecutor(workers) if workers > 1 and many else None
        flusher = ThreadPoolExecutor(SYNC_WORKERS) if many else None
        try:
            for start in range(0, len(fulls), BATCH_FILES):
                self._add_batch(
                    fulls,
                    range(start, min(start + BATCH_FILES, len(fulls))),
                    results,
                    objects,
                    note,
                    max_file_bytes,
                    pool,
                    flusher,
                    progress,
                    done,
                )
        finally:
            for executor in (pool, flusher):
                if executor is not None:
                    executor.shutdown(wait=True, cancel_futures=True)
        return results

    def _add_batch(
        self,
        fulls: list[str],
        indices: range,
        results: list[Any],
        objects: str,
        note: str | None,
        max_file_bytes: int | None,
        pool: ThreadPoolExecutor | None,
        flusher: ThreadPoolExecutor | None,
        progress: Callable[[int, int], None] | None,
        done: list[int],
    ) -> None:
        copies: dict[int, _Copy] = {}
        try:
            # 1. copy each file to a temporary name, hashing as it goes; nothing synced yet
            def finished(i: int, outcome: _Copy | BaseException) -> None:
                if isinstance(outcome, _Copy):
                    copies[i] = outcome
                    done[1] += outcome.size
                else:
                    results[i] = outcome
                done[0] += 1
                if progress is not None:
                    progress(done[0], done[1])

            if pool is None:
                for i in indices:
                    finished(i, self._copy_or_error(fulls[i], objects, max_file_bytes))
            else:
                futures = {
                    pool.submit(self._copy_or_error, fulls[i], objects, max_file_bytes): i for i in indices
                }
                try:
                    for fut in as_completed(futures):
                        finished(futures[fut], fut.result())
                except BaseException:
                    # stop the copies not started, and let the ones running finish, so
                    # that their temporary copies are removed below too
                    for fut in futures:
                        fut.cancel()
                    for fut, i in futures.items():
                        if (
                            not fut.cancelled()
                            and fut.exception() is None
                            and isinstance(fut.result(), _Copy)
                        ):
                            copies.setdefault(i, fut.result())
                    raise

            # 2. in order: which copies become objects, and which files get a record
            place: dict[str, _Copy] = {}  # sha -> the copy that becomes its object
            records: list[int] = []
            planned: dict[str, tuple[str, int]] = {}  # key -> (sha, index) of a record planned here
            alias: dict[int, int] = {}  # the same file named twice with the same content
            for i in indices:
                c = copies.get(i)
                if c is None:
                    continue
                try:
                    key = self.key(c.full)
                    if key in planned and planned[key][0] == c.sha:
                        alias[i] = planned[key][1]
                        continue
                    if key not in planned:
                        existing = self.snapshots(c.full)
                        if existing and existing[-1].sha256 == c.sha:
                            results[i] = (existing[-1], False)
                    if c.sha not in place and not (
                        self.has_object(c.sha, c.size) and self._intact(c.sha, c.size)
                    ):
                        place[c.sha] = c  # also puts back a newest snapshot's copy that is damaged or gone
                except (OSError, SolidSeasError) as exc:
                    results[i] = exc
                    continue
                if results[i] is None:
                    planned[key] = (c.sha, i)
                    records.append(i)

            # 3. flush the copies, give them their object names, flush their folders
            failed_objects: dict[str, BaseException] = {}
            if place:
                try:
                    _sync_files([c.tmp for c in place.values()], flusher)
                except OSError as exc:
                    failed_objects = dict.fromkeys(place, exc)
                folders = set()
                for sha, c in place.items():
                    if sha in failed_objects:
                        continue
                    try:
                        self._place(c.tmp, sha, c.size)
                        folders.add(os.path.join(objects, sha[:2]))
                    except (OSError, SolidSeasError) as exc:
                        failed_objects[sha] = exc
                try:
                    _sync_folders([*sorted(folders), objects], flusher)
                except OSError as exc:
                    failed_objects.update(dict.fromkeys(place, exc))
            for i in indices:
                c = copies.get(i)
                if c is not None and c.sha in failed_objects:
                    results[i] = failed_objects[c.sha]

            # 4. the records, created in order, then flushed with their folders
            written: list[int] = []
            for i in records:
                c = copies[i]
                if c.sha in failed_objects:
                    continue
                snap = Snapshot(
                    secrets.token_hex(6),
                    datetime.datetime.now(datetime.UTC),
                    c.sha,
                    c.size,
                    c.recorded,
                    c.mtime_ns,
                    note,
                    __version__,
                    "",
                )
                try:
                    snap = self._write_record(c.full, snap)
                except (OSError, SolidSeasError) as exc:
                    results[i] = exc
                    continue
                results[i] = (snap, True)
                written.append(i)
            if written:
                folders = sorted({self._record_folder(copies[i].full) for i in written})
                try:
                    _sync_files(
                        [
                            os.path.join(self._record_folder(copies[i].full), results[i][0].record)
                            for i in written
                        ],
                        flusher,
                    )
                    _sync_folders([*folders, os.path.join(self.root, "files"), self.root], flusher)
                except OSError as exc:
                    for i in written:
                        results[i] = exc
            for i, j in alias.items():
                results[i] = (results[j][0], False) if isinstance(results[j], tuple) else results[j]
        finally:
            for c in copies.values():
                if os.path.lexists(c.tmp):
                    os.remove(c.tmp)

    def _copy_or_error(self, full: str, objects: str, max_file_bytes: int | None) -> _Copy | BaseException:
        try:
            return self._copy(full, objects, max_file_bytes)
        except (OSError, SolidSeasError) as exc:
            return exc

    def _copy(self, full: str, objects: str, max_file_bytes: int | None) -> _Copy:
        """Copy the file to a new temporary name in ``objects``, hashing as it goes. The
        copy is not flushed to disk here: :meth:`_add_batch` flushes a batch at once."""
        recorded = self.recorded_path(full)
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
            if (before.st_size, before.st_mtime_ns) != (
                after.st_size,
                after.st_mtime_ns,
            ) or count != before.st_size:
                raise BusyError(
                    "the file changed while it was copied: take the snapshot again once it is saved",
                    detail={"rule": "file_changing"},
                )
        except BaseException:
            if os.path.lexists(tmp):
                os.remove(tmp)
            raise
        return _Copy(full, recorded, tmp, h.hexdigest(), count, after.st_mtime_ns)

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
        """Move the copy at ``tmp``, already flushed to disk, to its object name, keeping an
        object already there only when its content is intact; any other is replaced by the
        copy."""
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

    def _record_folder(self, full: str) -> str:
        return os.path.join(self.root, "files", self.key(full))

    def _write_record(self, full: str, snap: Snapshot) -> Snapshot:
        """Create the record of ``snap`` under its new name. It is not flushed here: the
        caller flushes it with its folder once the batch's records are written."""
        folder = self._folders("files", self.key(full), create=True)
        stamp = snap.taken.strftime("%Y%m%dT%H%M%S%f") + "Z"
        name = f"{stamp}-{snap.id}.json"
        path = os.path.join(folder, name)
        data = json.dumps(snap.to_json(), ensure_ascii=True, sort_keys=True).encode("ascii")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY | _O_NOFOLLOW | _O_CLOEXEC, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(data)
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


@dataclass(frozen=True)
class _Copy:
    """A file copied to a temporary name in ``objects``, not yet flushed to disk."""

    full: str
    recorded: str
    tmp: str
    sha: str
    size: int
    mtime_ns: int


def sync_file(path: str) -> None:
    """Flush the file at ``path`` to disk (``FlushFileBuffers`` on Windows, which needs it
    opened for writing). It is never created, truncated or followed as a link."""
    mode = os.O_WRONLY if os.name == "nt" else os.O_RDONLY
    fd = os.open(path, mode | _O_BINARY | _O_NOFOLLOW | _O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def sync_folder(path: str) -> None:
    """Flush a folder's entries to disk, so a name just made or renamed in it survives a
    crash. Windows keeps no such handle open to a folder and needs none: it does nothing
    there."""
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _O_NOFOLLOW | _O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _sync_all(fn: Callable[[str], None], paths: list[str], pool: ThreadPoolExecutor | None) -> None:
    """Call ``fn`` on every path, on the pool's threads when there is one: a disk that
    takes many flushes at once commits them together. The first error is raised once all
    have run."""
    if pool is None or len(paths) < 2:
        for p in paths:
            fn(p)
        return
    futures = [pool.submit(fn, p) for p in paths]
    errors = [fut.exception() for fut in futures]
    first = next((e for e in errors if e is not None), None)
    if first is not None:
        raise first


def _sync_files(paths: list[str], pool: ThreadPoolExecutor | None = None) -> None:
    _sync_all(sync_file, paths, pool)


def _sync_folders(paths: list[str], pool: ThreadPoolExecutor | None = None) -> None:
    _sync_all(sync_folder, paths, pool)


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
    "sync_file",
    "sync_folder",
]
