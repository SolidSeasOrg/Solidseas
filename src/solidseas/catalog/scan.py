"""One scan of a catalog's roots: walk and compare, read, resolve, hash.

The process that runs a scan holds the catalog's only write connection and
never parses a CAD file: every document is read by the ``catalog_document`` job
in a :class:`~solidseas.workers.WorkerPool` worker, every hash by
``content_hash``, and every folder is walked by :class:`solidseas.walk.Walk`.
The phases run in this order, each committed in batches (64 documents or a
quarter of a second) so a reader sees rows as they arrive:

1. **Walk and compare.** Each root is walked (links never followed, cloud
   placeholders never opened, ``~$`` lock files skipped, the catalog's own folder
   and, for a catalog in the cache, SolidSeas' cache folder left out, so indexing a
   home folder never walks the catalogs inside it). Only names ending in an
   extension of the formats the catalog indexes (its ``formats`` setting:
   ``.sldprt``, ``.sldasm`` and ``.slddrw`` by default) become rows, compared a
   folder at a time with that folder's rows. A file is unchanged when its size and
   modification time from the directory listing equal what was stored and,
   where the listing gives a file id (Linux and macOS), its file id too; a
   changed one is read again and its hash dropped. A file freed to a cloud
   placeholder, or brought back, with the same size and time keeps what was
   read of it. A path new to the catalog is matched to a row that vanished in
   this scan by file id, size and modification time, so a moved or renamed
   folder is not read again (a file id taken with ``lstat`` only after every
   folder from the root down was found to be no link); where the filesystem has
   no file ids, a match by folded name, size and time keeps the row but reads
   the file again. A renamed document's part numbers taken from its name, and
   its full-text row, follow the new name. A vanished row is
   deleted when the folder that held it was listed completely, and kept as
   ``stale`` when the walk could not tell (an unreadable, depth-limited or
   placeholder folder, a root that is unavailable, a walk a bound cut short): a
   share that is offline never empties the catalog.
2. **Read.** Every ``pending`` row is read in a worker, with a deadline per file
   and the pool's memory cap; the answer is checked as untrusted
   (:mod:`.record`) before anything of it is stored. A file larger than
   ``max_file_bytes`` is refused from the listing's size without a job. Locked,
   busy, timed-out and crashed reads are tried again at the next scan; a file
   that times out or crashes its worker twice at one size and time is
   ``quarantined`` until it changes. A read that never started because a shared
   pool had no worker free is ``busy`` and never counts toward that. Rows read
   by an older reader revision are read again after the new ones.
3. **Resolve.** Every document marked ``resolve``: assemblies and drawings read
   in this scan, those whose references name or found a file added, changed,
   moved or removed, one that was moved itself, and all of them when the roots
   changed. Each mark is written in the transaction of the change that asks for
   it, so a scan cancelled (or a process killed) before this phase leaves them
   for the next. Resolution runs from rows (:mod:`.resolution`). An Alibre Design
   assembly is resolved by the GUIDs its components hold
   (:func:`.resolution.resolve_alibre`), and every one is marked again when an
   Alibre file is added, changed, moved or removed.
4. **Hash.** The SHA-256 of each file whose hash is missing or stale, by the
   policy (``all``, ``duplicates``: only files whose size another file shares,
   which still finds every duplicate, or ``none``; by default ``all`` on a local
   drive and ``duplicates`` on a share), recorded per root so the queries count
   what is still to hash by the same rule (:data:`.query.HASH_WANTED`). A hash
   is kept only when the file did not change while it was read.

``max_seconds`` and ``cancel`` are checked between folders and files; what was
committed stays, and the next scan picks up the ``pending`` rows and the
``resolve`` marks.
"""

import concurrent.futures as cf
import datetime
import itertools
import json
import os
import stat
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .. import __version__, model
from ..errors import WorkerCrashedError, WorkerJobError, WorkerTimeoutError
from ..resolve.names import fold
from ..walk import Walk, classify
from . import query, record, schema
from .resolution import ALIBRE_EXTENSIONS, RowIndexes, host_path, resolve_alibre, resolve_documents

DEFAULT_WORKERS = 2
DEFAULT_FILE_TIMEOUT = 30.0
DEFAULT_MAX_FILE_BYTES = 2 << 30
DEFAULT_EVENTS_DAYS = 90
WALK_MAX_DEPTH = 32
WALK_MAX_EXAMINED = 1_000_000
BATCH_DOCUMENTS = 64
BATCH_SECONDS = 0.25
MAX_ERRORS = 100
HASH_BASE_SECONDS = 30.0
HASH_BYTES_PER_SECOND = 5_000_000
WORKER_MEMORY_MB = 2048
RETRY_CODES = ("locked", "busy", "timeout", "worker_crashed")
QUARANTINE_CODES = ("timeout", "worker_crashed")
HASH_POLICIES = ("all", "duplicates", "none")
PHASES = ("walk", "read", "resolve", "hash")
DESCRIPTION = "Description"
_CHUNK = 500


def utc_now() -> str:
    return model.iso8601(datetime.datetime.now(datetime.UTC).replace(microsecond=0))


def _chunks(items: list, n: int = _CHUNK):
    for i in range(0, len(items), n):
        yield items[i : i + n]


def _ancestors(rel: str) -> list[str]:
    """``""``, ``"a"``, ``"a/b"`` for the folder ``"a/b"``."""
    out = [""]
    if rel:
        parts = rel.split("/")
        out += ["/".join(parts[: i + 1]) for i in range(len(parts))]
    return out


def _error_object(code: str, rule: str | None = None, exception: str = "SolidSeasError") -> dict[str, Any]:
    """The error object for a code the scan decides itself (no exception behind it)."""
    spec = model.ERROR_CODES[code]
    return {
        "code": code,
        "message": model.RULE_MESSAGES.get((code, rule), spec.message) if rule else spec.message,
        "exception": exception,
        "retryable": spec.retryable,
        "detail": {"rule": rule} if rule else {},
        "reader_message": None,
    }


def _effective(cfg: dict[str, Any] | None, file_props: list[dict[str, Any]], name: str) -> str | None:
    """A property's text in a configuration: its own, else the file's, names compared
    case-insensitively; "" for one stored without text, None when neither has it."""
    want = name.casefold()
    for props in ((cfg or {}).get("properties") or [], file_props):
        for p in props:
            if p["name"].casefold() == want:
                return p["text"] if p["text"] is not None else ""
    return None


def _kind_state(state: str, retryable: bool, kind: str) -> str:
    """The state of a row whose bytes did not change when it becomes ``kind``: what was
    read of it stays true (a cloud placeholder keeps the data read before it was freed,
    since it is never read again while it is one); a row still to be read, or to be read
    again, waits for its data while it is a placeholder and is read once it is a file."""
    if kind == "placeholder":
        return "placeholder" if state == "pending" or (state == "error" and retryable) else state
    return "pending" if state == "placeholder" else state


def search_row(con, file_id: int, rel: str, name: str, *, document: bool = True) -> None:
    """Make a file's full-text row again from its rows: its name and folder and, with
    ``document``, what its document says (each configuration's part number and
    description, every property's name and text, the configuration names). Whatever
    changed the file (a read, a failed read, a move, a rename, new part numbers), the row
    then agrees with the tables."""
    numbers = properties = names = ""
    if document:
        cfgs = con.execute(
            "SELECT name, part_number, description FROM configurations WHERE file = ? ORDER BY position",
            (file_id,),
        ).fetchall()
        numbers = " ".join(f"{pn} {desc or ''}" for _n, pn, desc in cfgs)
        names = " ".join(n for n, _pn, _desc in cfgs)
        properties = " ".join(
            f"{n} {t or ''}"
            for n, t in con.execute(
                "SELECT name, text FROM properties WHERE file = ? ORDER BY rowid", (file_id,)
            )
        )
    folder = rel.rpartition("/")[0].replace("/", " ")
    con.execute("DELETE FROM search WHERE rowid = ?", (file_id,))
    con.execute(
        "INSERT INTO search (rowid, name, numbers, properties, configurations, folder) VALUES "
        "(?, ?, ?, ?, ?, ?)",
        (file_id, name, numbers, properties, names, folder),
    )


class _Lstat:
    """An ``lstat`` result dressed as a directory entry, for :func:`solidseas.walk.classify`."""

    def __init__(self, name: str, st: os.stat_result) -> None:
        self.name = name
        self._st = st

    def stat(self, follow_symlinks: bool = True) -> os.stat_result:
        return self._st

    def is_symlink(self) -> bool:
        return stat.S_ISLNK(self._st.st_mode)

    def is_junction(self) -> bool:
        return False


@dataclass
class _RootWalk:
    """What the walk of one root saw."""

    db: int
    listed: set[str] = field(default_factory=lambda: {""})
    problems: dict[str, str] = field(default_factory=dict)
    truncated: str | None = None
    partial: str | None = None
    entries: int = 0
    documents: int = 0
    state: str = "ready"


@dataclass
class _Row:
    id: int
    root: int
    rel: str
    name: str
    size: int | None
    mtime_ns: int | None
    error_count: int


class Scanner:
    """One scan of ``cat`` (a writable :class:`solidseas.catalog.Catalog`); :meth:`run`
    returns the ``catalog_scan`` data."""

    def __init__(
        self,
        cat,
        *,
        pool=None,
        workers: int = DEFAULT_WORKERS,
        hash_policy: str | None = None,
        previews: bool = True,
        file_timeout: float = DEFAULT_FILE_TIMEOUT,
        max_seconds: float | None = None,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        progress: Callable[[str, int, int], None] | None = None,
        cancel: threading.Event | None = None,
        verify: bool = False,
    ) -> None:
        self.cat = cat
        self.verify = verify
        self.con = cat.con
        self.pool = pool
        self.workers = workers
        self.hash_policy = hash_policy
        self.previews = previews
        self.file_timeout = file_timeout
        self.max_file_bytes = max_file_bytes
        self.progress = progress
        self.cancel = cancel
        self.deadline = None if max_seconds is None else time.monotonic() + max_seconds
        self.pn_property = cat.meta("part_number_property") or None
        self.extensions = record.indexed_extensions(cat.formats)
        self._in_tx = False
        self._tx_n = 0
        self._tx_t = 0.0
        self.scan_id = 0
        self.root_ids: dict[int, str] = {}  # db id -> root id
        self.root_paths: dict[int, str] = {}
        self.walks: dict[int, _RootWalk] = {}
        self.available: set[int] = set()
        self.new_rows: list[tuple[int, int, str, str, int | None, int | None, str | None]] = []
        self.roots_changed = False
        self.removed_roots: list[str] = []
        self.errors: list[dict[str, Any]] = []
        self.counts = dict.fromkeys(
            (
                "seen",
                "added",
                "changed",
                "unchanged",
                "moved",
                "removed",
                "stale",
                "read_ok",
                "read_errors",
                "not_solidworks",
                "pending",
                "hashed",
                "hash_pending",
                "resolved_documents",
                "verified",
            ),
            0,
        )
        self.seconds = dict.fromkeys((*PHASES, "total"), 0.0)
        self.stopped: str | None = None  # "cancelled" or "deadline"
        self._folders: dict[tuple[int, str], int] = {}
        self._own_pool = None

    # ------------------------------------------------------------------ transactions
    def _begin(self) -> None:
        if not self._in_tx:
            self.con.execute("BEGIN IMMEDIATE")
            self._in_tx = True
            self._tx_n = 0
            self._tx_t = time.monotonic()

    def _commit(self, force: bool = False) -> None:
        if not self._in_tx:
            return
        if force or self._tx_n >= BATCH_DOCUMENTS or time.monotonic() - self._tx_t >= BATCH_SECONDS:
            self.con.execute("COMMIT")
            self._in_tx = False

    def _over(self) -> bool:
        if self.stopped is not None:
            return True
        if self.cancel is not None and self.cancel.is_set():
            self.stopped = "cancelled"
        elif self.deadline is not None and time.monotonic() >= self.deadline:
            self.stopped = "deadline"
        return self.stopped is not None

    def _report(self, phase: str, done: int, total: int) -> None:
        if self.progress is not None:
            try:
                self.progress(phase, done, total)
            except Exception:  # a progress callback never stops a scan
                pass

    def _event(self, kind: str, file: int | None, root: int | None, rel: str | None, **kw: Any) -> None:
        self.con.execute(
            "INSERT INTO events (scan, time_utc, kind, file, root, rel, previous_root, previous_rel, size, "
            "sha256, previous_sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self.scan_id,
                self.now,
                kind,
                file,
                self.root_ids.get(root) if root is not None else None,
                rel,
                kw.get("previous_root"),
                kw.get("previous_rel"),
                kw.get("size"),
                kw.get("sha256"),
                kw.get("previous_sha256"),
            ),
        )

    # ------------------------------------------------------------------ the run
    def run(self) -> dict[str, Any]:
        t0 = time.monotonic()
        self.now = utc_now()
        con = self.con
        try:
            self._begin()
            cur = con.execute(
                "INSERT INTO scans (started_utc, library_version, state, counts) VALUES (?, ?, 'running', "
                "'{}')",
                (self.now, __version__),
            )
            self.scan_id = cur.lastrowid
            self._sync_roots()
            self._commit(force=True)
            t = time.monotonic()
            for db, root in self.cat._root_rows():
                if self._over():
                    break
                self._walk_root(db, root)
            self._move_pass()
            self._vanished_pass()
            self._commit(force=True)
            self.seconds["walk"] = time.monotonic() - t
            try:
                t = time.monotonic()
                if self.verify and not self._over():
                    self._verify_phase()
                self.seconds["hash"] = time.monotonic() - t
                t = time.monotonic()
                if not self._over():
                    self._read_phase()
                self.seconds["read"] = time.monotonic() - t
                t = time.monotonic()
                if self.stopped != "cancelled":
                    self._resolve_phase()
                self.seconds["resolve"] = time.monotonic() - t
                t = time.monotonic()
                if not self._over():
                    self._hash_phase()
                self.seconds["hash"] += time.monotonic() - t
            finally:
                if self._own_pool is not None:
                    self._own_pool.close()
                    self._own_pool = None
            self.seconds["total"] = time.monotonic() - t0
            return self._finish("done")
        except BaseException:
            if self._in_tx:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                self._in_tx = False
            self.seconds["total"] = time.monotonic() - t0
            try:
                self._finish("failed")
            except Exception:
                pass
            raise

    def _pool(self):
        """The pool to read with: the caller's, or one started now, the first time a file
        must be read (an unchanged rescan starts none)."""
        if self.pool is not None:
            return self.pool
        if self._own_pool is None:
            self._own_pool = self._make_pool()
        return self._own_pool

    def _make_pool(self):
        from ..workers import WorkerPool

        paths = [self.root_paths[db] for db in sorted(self.available)]
        return WorkerPool(
            self.workers,
            timeout_s=max(self.file_timeout, HASH_BASE_SECONDS),
            memory_mb=WORKER_MEMORY_MB,
            roots=paths,
            max_file_bytes=self.max_file_bytes,
            max_result_bytes=record.REPLY_LIMIT,
            reader_message=False,
            priority="below_normal",
        )

    # ------------------------------------------------------------------ roots
    def _sync_roots(self) -> None:
        """Make the stored roots the catalog's roots. A stored root keeps its rows as long
        as its folder is still given, whatever id it is given under (ids that trade folders
        are renamed through temporary names, so a swap never collides); a folder no longer
        given is removed with its rows; the order is the given one. When anything changed,
        every assembly and drawing is marked to be resolved again, in this transaction."""
        con = self.con
        given = list(self.cat.roots)
        stored = con.execute(
            "SELECT id, root_id, path_fold, role, recursive, position, path FROM roots"
        ).fetchall()
        by_fold = {row[2]: row for row in stored}
        given_ids = {r.id for r in given}
        kept: dict[int, Any] = {}
        for r in given:
            row = by_fold.get(fold(r.path))
            if row is not None:
                kept[row[0]] = r
        for db, root_id, *_rest in stored:
            if db not in kept:
                self._drop_root(db)
                if root_id not in given_ids:
                    self.removed_roots.append(root_id)
                self.roots_changed = True
        stored_ids = {row[0]: row[1] for row in stored}
        renamed = [(db, r.id) for db, r in kept.items() if stored_ids[db] != r.id]
        for db, _new in renamed:
            con.execute("UPDATE roots SET root_id = ? WHERE id = ?", (f"~renaming~{db}", db))
        for db, new in renamed:
            con.execute("UPDATE roots SET root_id = ? WHERE id = ?", (new, db))
            self.roots_changed = True
        from .store import is_network

        for position, r in enumerate(given):
            row = by_fold.get(fold(r.path))
            if row is None:
                con.execute(
                    "INSERT INTO roots (root_id, path, path_fold, role, recursive, position, network, state) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'new')",
                    (r.id, r.path, fold(r.path), r.role, int(r.recursive), position, int(is_network(r.path))),
                )
                self.roots_changed = True
            elif (row[3], bool(row[4]), row[5], row[6]) != (r.role, r.recursive, position, r.path):
                con.execute(
                    "UPDATE roots SET role = ?, recursive = ?, position = ?, path = ? WHERE id = ?",
                    (r.role, int(r.recursive), position, r.path, row[0]),
                )
                self.roots_changed = True
        rows = con.execute("SELECT id, root_id, path, network FROM roots").fetchall()
        for db, root_id, path, network in rows:
            self.root_ids[db] = root_id
            self.root_paths[db] = path
            policy = self.hash_policy or ("duplicates" if network else "all")
            con.execute("UPDATE roots SET hash_policy = ? WHERE id = ?", (policy, db))
        if self.roots_changed:
            con.execute(
                "UPDATE files SET resolve = 1 WHERE state = 'ok' AND id IN (SELECT DISTINCT file FROM refs)"
            )

    def _drop_root(self, db: int) -> None:
        if self.cat.fts5:
            self.con.execute("DELETE FROM search WHERE rowid IN (SELECT id FROM files WHERE root = ?)", (db,))
        self.con.execute("DELETE FROM roots WHERE id = ?", (db,))
        self.cat._vacuum = True

    # ------------------------------------------------------------------ phase 0: walk
    def _folder_id(self, db: int, rel: str) -> int:
        key = (db, rel)
        fid = self._folders.get(key)
        if fid is not None:
            return fid
        for a in _ancestors(rel):
            if (db, a) in self._folders:
                continue
            row = self.con.execute("SELECT id FROM folders WHERE root = ? AND rel = ?", (db, a)).fetchone()
            if row is None:
                row = (
                    self.con.execute(
                        "INSERT INTO folders (root, rel, name) VALUES (?, ?, ?)",
                        (db, a, a.rpartition("/")[2]),
                    ).lastrowid,
                )
            self._folders[(db, a)] = row[0]
        return self._folders[key]

    def _search_row(self, file_id: int, rel: str, name: str, *, document: bool = True) -> None:
        if self.cat.fts5:
            search_row(self.con, file_id, rel, name, document=document)

    # ------------------------------------------------------------------ re-resolution marks
    # Which documents are resolved again is marked (files.resolve = 1) in the transaction of the
    # change that asks for it, never kept in memory: a scan cancelled or killed before its
    # resolve phase leaves the marks, and the next scan's resolve phase takes them.
    def _resolve_naming(self, names) -> None:
        """Mark the documents whose references name one of ``names`` (folded)."""
        names = sorted({n for n in names if n})
        for chunk in _chunks(names):
            marks = ",".join("?" * len(chunk))
            self.con.execute(
                "UPDATE files SET resolve = 1 WHERE resolve = 0 AND state = 'ok' AND id IN (SELECT file "
                f"FROM refs WHERE name_fold IN ({marks}))",
                chunk,
            )

    def _resolve_targeting(self, ids) -> None:
        """Mark the documents whose references resolved to one of the rows ``ids``."""
        ids = sorted(set(ids))
        for chunk in _chunks(ids):
            marks = ",".join("?" * len(chunk))
            self.con.execute(
                "UPDATE files SET resolve = 1 WHERE resolve = 0 AND state = 'ok' AND id IN (SELECT file "
                f"FROM refs WHERE target IN ({marks}))",
                chunk,
            )

    def _resolve_alibre(self, names) -> None:
        """When one of ``names`` is an Alibre Design file's, mark every Alibre assembly:
        its components are found by the GUID each Alibre file holds, wherever the file is
        below the roots, so any Alibre file added, changed, moved or removed may change
        what they find."""
        if not any(n.lower().endswith(ALIBRE_EXTENSIONS) for n in names):
            return
        self.con.execute(
            "UPDATE files SET resolve = 1 WHERE resolve = 0 AND state = 'ok' AND id IN (SELECT file FROM "
            "documents WHERE format = 'alibre' AND doc_type = 'assembly') AND id IN (SELECT DISTINCT file "
            "FROM refs)"
        )

    def _unavailable(self, db: int, info: _RootWalk) -> None:
        """The root's folder cannot be listed (gone, offline, denied): every row it has is
        kept, stale, and nothing of it is read."""
        con = self.con
        info.state = "unavailable"
        self.available.discard(db)
        self._begin()
        con.execute("UPDATE files SET stale = 1 WHERE root = ?", (db,))
        self.counts["stale"] += con.execute("SELECT count(*) FROM files WHERE root = ?", (db,)).fetchone()[0]
        con.execute("UPDATE roots SET state = 'unavailable' WHERE id = ?", (db,))
        self._commit(force=True)

    def _indexed(self, name: str) -> bool:
        """Whether a file of this name is one of the formats the catalog indexes."""
        return name.lower().endswith(self.extensions)

    def _own_folders(self) -> list[str]:
        """The folders a walk leaves out: the catalog's own (its database, previews and
        lock), and for a catalog in the cache SolidSeas' cache folder with every catalog
        in it, which a root such as the user's home folder would otherwise hold."""
        from .store import cache_dir

        own = os.path.dirname(os.path.abspath(self.cat.path))
        out = [own]
        if self.cat.location == "cache":
            out += [os.path.dirname(own), cache_dir()]
        return out

    def _walk_root(self, db: int, root) -> None:
        info = _RootWalk(db)
        self.walks[db] = info
        try:
            walk = Walk(
                root.path,
                recursive=root.recursive,
                max_depth=WALK_MAX_DEPTH,
                max_examined=WALK_MAX_EXAMINED,
                deadline=self.deadline,
                exclude=self._own_folders(),
            )
            entries = iter(walk)
            first = next(entries, None)  # the root's own listing: only it raises
        except OSError:
            self._unavailable(db, info)
            return
        self.available.add(db)
        current: str | None = None
        buffer: list = []
        stopped = None
        for e in itertools.chain((first,) if first is not None else (), entries):
            if self._over():
                stopped = self.stopped
                break
            parent = e.rel.rpartition("/")[0]
            if parent != current:
                self._flush(db, current, buffer)
                current, buffer = parent, []
            if e.kind == "folder":
                if e.reason == "max_depth":
                    info.problems[e.rel] = "max_depth"
                elif root.recursive:
                    info.listed.add(e.rel)
            elif e.kind == "link":
                if e.is_dir:
                    info.problems[e.rel] = "link"
            elif e.kind == "placeholder":
                if e.is_dir:
                    info.problems[e.rel] = "placeholder"
                elif self._indexed(e.name):
                    buffer.append(e)
            elif e.kind == "error":
                if e.is_dir:
                    info.problems[e.rel] = "unreadable"
                    info.listed.discard(e.rel)
                elif self._indexed(e.name):
                    buffer.append(e)
            elif e.kind == "file" and self._indexed(e.name):
                buffer.append(e)
        self._flush(db, current, buffer)
        stats = walk.stats
        info.entries = stats.entries
        info.truncated = stopped or stats.truncated
        info.partial = info.truncated or ("max_depth" if stats.depth_limited else None)
        info.state = "partial" if info.partial else "ready"
        self._commit(force=True)

    def _flush(self, db: int, folder: str | None, entries: list) -> None:
        if folder is None or not entries:
            return
        con = self.con
        self._begin()
        fid = self._folder_id(db, folder)
        existing = {
            r[1]: r
            for r in con.execute(
                "SELECT id, name, size, mtime_ns, kind, state, error_retryable, sha256, file_id FROM files "
                "WHERE folder = ?",
                (fid,),
            )
        }
        seen: list[tuple[int]] = []
        touched: list[str] = []  # names whose referencing documents are resolved again
        info = self.walks[db]
        for e in entries:
            info.documents += 1
            self.counts["seen"] += 1
            kind = "placeholder" if e.kind == "placeholder" else "file"
            row = existing.get(e.name)
            if row is None:
                if e.kind == "error":
                    state = "error"
                elif kind == "placeholder":
                    state = "placeholder"
                else:
                    state = "pending"
                cur = con.execute(
                    "INSERT INTO files (root, folder, rel, name, name_fold, ext, kind, size, mtime_ns, "
                    "file_id, first_scan, seen_scan, changed_scan, state, error_code, error_retryable) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        db,
                        fid,
                        e.rel,
                        e.name,
                        fold(e.name),
                        os.path.splitext(e.name)[1].lower(),
                        kind,
                        e.size,
                        e.mtime_ns,
                        e.file_id,
                        self.scan_id,
                        self.scan_id,
                        self.scan_id,
                        state,
                        model.error_code(e.error) if e.kind == "error" and e.error is not None else None,
                        1 if e.kind == "error" else None,
                    ),
                )
                self.new_rows.append((cur.lastrowid, db, e.rel, e.name, e.size, e.mtime_ns, e.file_id))
                self._search_row(cur.lastrowid, e.rel, e.name, document=False)
                touched.append(fold(e.name))
                continue
            rid, _name, size, mtime, old_kind, state, retryable, sha, old_id = row
            if e.kind == "error":  # there, but its details could not be read: keep what is known
                seen.append((rid,))
                self.counts["unchanged"] += 1
                continue
            # The listing's size and time say whether the bytes changed; where the listing
            # gives a file id (Linux and macOS), a file deleted and made again under the same
            # name, size and time is another file too.
            other_file = bool(e.file_id and old_id and e.file_id != old_id)
            same = (size, mtime) == (e.size, e.mtime_ns) and not other_file
            if same:
                seen.append((rid,))
                self.counts["unchanged"] += 1
                if old_kind != kind:
                    # freed to a cloud placeholder, or brought back, with the same bytes: what was
                    # read of it stays true (a placeholder is never read, so it would not come back)
                    # a placeholder's identity is never read, so the references to it are
                    # resolved again either way
                    new_state = _kind_state(state, bool(retryable), kind)
                    if new_state == state:
                        con.execute("UPDATE files SET kind = ? WHERE id = ?", (kind, rid))
                    else:
                        con.execute(
                            "UPDATE files SET kind = ?, state = ?, error_code = NULL, "
                            "error_retryable = NULL, error_count = 0 WHERE id = ?",
                            (kind, new_state, rid),
                        )
                    touched.append(fold(e.name))
                elif state == "error" and retryable and kind == "file":
                    con.execute("UPDATE files SET state = 'pending' WHERE id = ?", (rid,))
                continue
            con.execute(
                "UPDATE files SET size = ?, mtime_ns = ?, kind = ?, state = ?, changed_scan = ?, seen_scan = "
                "?, stale = 0, sha256 = NULL, hash_size = NULL, hash_mtime_ns = NULL, error_code = NULL, "
                "error_retryable = NULL, error_count = 0, file_id = ? WHERE id = ?",
                (
                    e.size,
                    e.mtime_ns,
                    kind,
                    "placeholder" if kind == "placeholder" else "pending",
                    self.scan_id,
                    self.scan_id,
                    e.file_id,
                    rid,
                ),
            )
            if kind == "placeholder":  # changed while away: what was read of it no longer holds
                self._clear_document(rid)
                self._search_row(rid, e.rel, e.name, document=False)
            self._event("changed", rid, db, e.rel, size=e.size, previous_sha256=sha)
            self.counts["changed"] += 1
            touched.append(fold(e.name))
        if seen:
            con.executemany(f"UPDATE files SET seen_scan = {int(self.scan_id)}, stale = 0 WHERE id = ?", seen)
        self._resolve_naming(touched)
        self._resolve_alibre(touched)
        self._tx_n += len(entries)
        self._commit()
        self._report("walk", self.counts["seen"], 0)

    def _clear_document(self, file_id: int) -> None:
        for table in ("documents", "configurations", "properties", "refs", "edges", "views"):
            self.con.execute(f"DELETE FROM {table} WHERE file = ?", (file_id,))

    def _lstat_id(self, db: int, rel: str) -> str | None:
        """The file id of ``rel`` below root ``db``, from ``lstat``, after each folder from
        the root down was ``lstat``-ed and found a folder, not a link: the operating system
        never goes through a link (one to a share would make it connect there). None for a
        path that leads through a link, is not a plain file, or has no file id."""
        host = self.root_paths[db]
        root_dev = None
        if os.name != "nt":
            try:
                root_dev = os.stat(host).st_dev
            except OSError:
                return None
        parts = rel.split("/")
        try:
            for i, comp in enumerate(parts):
                folder, host = host, os.path.join(host, comp)
                st = os.lstat(host)
                we = classify(_Lstat(comp, st), folder, "", i + 1, root_dev=root_dev)
                if we.kind != ("file" if i == len(parts) - 1 else "folder"):
                    return None
        except OSError:
            return None
        return f"{st.st_dev:x}:{st.st_ino:x}" if st.st_ino else None

    def _move_pass(self) -> None:
        """A path new to the catalog that is a row which vanished in this scan, by file id,
        size and modification time, takes that row: nothing is read again. Without file ids
        to prove it (a match by folded name, size and time), the row keeps its history but
        the file is read again. The documents that name either name or resolved to the row
        are resolved again, and so is a moved document itself, since what its references
        find depends on where it is."""
        con = self.con
        vanished: dict[tuple, list[list[Any]]] = {}
        for db in self.available:
            for row in con.execute(
                "SELECT id, root, rel, name_fold, size, mtime_ns, file_id, sha256, name, kind, state, "
                "error_retryable FROM files WHERE root = ? AND seen_scan < ?",
                (db, self.scan_id),
            ):
                vanished.setdefault((row[4], row[5]), []).append(list(row))
        added: list[tuple] = []
        if not vanished:
            added = self.new_rows
        else:
            for new in self.new_rows:
                self._begin()
                nid, db, rel, name, size, mtime, file_id = new
                cands = vanished.get((size, mtime))
                if not cands or size is None:
                    added.append(new)
                    continue
                fid = file_id or self._lstat_id(db, rel)
                match = [c for c in cands if fid is not None and c[6] == fid]
                probable = False
                if not match:
                    same = [c for c in cands if (fid is None or c[6] is None) and c[3] == fold(name)]
                    if len(same) == 1:
                        match, probable = same, True
                if not match:
                    added.append(new)
                    continue
                old = match[0]
                rid, old_name, old_kind, state, retryable = old[0], old[8], old[9], old[10], old[11]
                cands.remove(old)
                folder, kind = con.execute("SELECT folder, kind FROM files WHERE id = ?", (nid,)).fetchone()
                con.execute("DELETE FROM files WHERE id = ?", (nid,))
                if self.cat.fts5:
                    con.execute("DELETE FROM search WHERE rowid = ?", (nid,))
                con.execute(
                    "UPDATE files SET root = ?, folder = ?, rel = ?, name = ?, name_fold = ?, ext = ?, "
                    "kind = ?, seen_scan = ?, stale = 0, file_id = coalesce(?, file_id) WHERE id = ?",
                    (
                        db,
                        folder,
                        rel,
                        name,
                        fold(name),
                        os.path.splitext(name)[1].lower(),
                        kind,
                        self.scan_id,
                        fid,
                        rid,
                    ),
                )
                if probable and kind == "file":
                    # no file id proves it is the same file: what was read of the old one is not
                    # trusted, and the file is read (and hashed) again
                    con.execute(
                        "UPDATE files SET state = 'pending', changed_scan = ?, sha256 = NULL, "
                        "hash_size = NULL, hash_mtime_ns = NULL, error_code = NULL, error_retryable = NULL, "
                        "error_count = 0, resolve = 0 WHERE id = ?",
                        (self.scan_id, rid),
                    )
                elif kind != old_kind:
                    new_state = _kind_state(state, bool(retryable), kind)
                    if new_state != state:
                        con.execute(
                            "UPDATE files SET state = ?, error_code = NULL, error_retryable = NULL, "
                            "error_count = 0 WHERE id = ?",
                            (new_state, rid),
                        )
                if os.path.splitext(name)[0] != os.path.splitext(old_name)[0]:
                    # renamed: a part number taken from the document name follows the new name
                    con.execute(
                        "UPDATE configurations SET part_number = ? WHERE file = ? AND part_number_source = "
                        "'document_name'",
                        (os.path.splitext(name)[0], rid),
                    )
                self._search_row(rid, rel, name)
                self._resolve_naming((old[3], fold(name)))
                self._resolve_alibre((name,))
                self._resolve_targeting((rid,))
                con.execute(
                    "UPDATE files SET resolve = 1 WHERE id = ? AND state = 'ok' AND EXISTS (SELECT 1 "
                    "FROM refs WHERE file = ?)",
                    (rid, rid),
                )
                self._event(
                    "moved",
                    rid,
                    db,
                    rel,
                    previous_root=self.root_ids.get(old[1]),
                    previous_rel=old[2],
                    size=size,
                    sha256=old[7],
                )
                self.counts["moved"] += 1
                self._tx_n += 1
                self._commit()
        self._begin()
        for nid, db, rel, _name, size, _mtime, _fid in added:
            self._event("added", nid, db, rel, size=size)
            self.counts["added"] += 1
        self._commit(force=True)

    def _gone(self, info: _RootWalk, rel: str) -> bool | None:
        """True when a vanished row at ``rel`` is gone, False when it is to be kept
        (stale), from what the walk of its root listed."""
        if info.truncated:
            return False
        folder = rel.rpartition("/")[0]
        for a in reversed(_ancestors(folder)):
            problem = info.problems.get(a)
            if problem is not None:
                return problem == "link"  # behind a link it is no longer inside the root
            if a in info.listed:
                return True
        return False

    def _vanished_pass(self) -> None:
        con = self.con
        for db, info in self.walks.items():
            if info.state == "unavailable":
                continue
            rows = con.execute(
                "SELECT id, rel, name_fold, size, sha256 FROM files WHERE root = ? AND seen_scan < ?",
                (db, self.scan_id),
            ).fetchall()
            if not rows:
                continue
            gone = [r for r in rows if self._gone(info, r[1])]
            kept = [(r[0],) for r in rows if not self._gone(info, r[1])]
            self._begin()
            if kept:
                con.executemany("UPDATE files SET stale = 1 WHERE id = ?", kept)
                self.counts["stale"] += len(kept)
            ids = [r[0] for r in gone]
            self._resolve_targeting(ids)
            self._resolve_naming(r[2] for r in gone)
            self._resolve_alibre([r[2] for r in gone])
            for r in gone:
                self._event("removed", r[0], db, r[1], size=r[3], sha256=r[4])
            for chunk in _chunks(ids):
                marks = ",".join("?" * len(chunk))
                if self.cat.fts5:
                    con.execute(f"DELETE FROM search WHERE rowid IN ({marks})", chunk)
                con.execute(f"DELETE FROM files WHERE id IN ({marks})", chunk)
            self.counts["removed"] += len(ids)
            self._commit(force=True)
        self._collect_folders()

    def _collect_folders(self) -> None:
        """Forget the folders no document is in or below any more."""
        con = self.con
        self._begin()
        for db in self.available:
            needed: set[str] = set()
            for (rel,) in con.execute("SELECT rel FROM files WHERE root = ?", (db,)):
                needed.update(_ancestors(rel.rpartition("/")[0]))
            drop = [
                (fid,)
                for fid, rel in con.execute("SELECT id, rel FROM folders WHERE root = ?", (db,)).fetchall()
                if rel not in needed
            ]
            if drop:
                con.executemany("DELETE FROM folders WHERE id = ?", drop)
        self._folders.clear()
        self._commit(force=True)

    # ------------------------------------------------------------------ phase 1: read
    def _read_rows(self) -> list[_Row]:
        if not self.available:
            return []
        marks = ",".join("?" * len(self.available))
        query = (
            "SELECT f.id, f.root, f.rel, f.name, f.size, f.mtime_ns, f.error_count FROM files f "
            "JOIN roots r ON r.id = f.root "
            f"WHERE f.kind = 'file' AND f.stale = 0 AND f.root IN ({marks}) AND {{}} ORDER BY r.position, "
            "f.rel"
        )
        roots = sorted(self.available)
        rows = self.con.execute(query.format("f.state = 'pending'"), roots).fetchall()
        old = self.con.execute(
            query.format("f.state = 'ok' AND (f.reader_revision IS NULL OR f.reader_revision < ?)"),
            (*roots, schema.READER_REVISION),
        ).fetchall()
        return [_Row(*r) for r in rows + old]

    def _read_one(self, pool, row: _Row) -> tuple:
        params = {
            "path": host_path(self.root_paths[row.root], row.rel),
            "within": self.root_paths[row.root],
            "name": row.name,
            "previews": bool(self.previews),
            "graph": True,
        }
        try:
            r = pool.call(
                "catalog_document", params, timeout=self.file_timeout, max_result_bytes=record.REPLY_LIMIT
            )
            return "ok", r.data, r.payload
        except WorkerJobError as exc:
            if exc.code != "response_too_large":
                return "error", exc, None
        except (WorkerTimeoutError, WorkerCrashedError) as exc:
            return "error", exc, None
        except Exception as exc:  # the pool closed under the read, or a bad argument
            return "error", exc, None
        params["graph"] = False  # too large with its model graph: its properties are still indexed
        try:
            r = pool.call(
                "catalog_document", params, timeout=self.file_timeout, max_result_bytes=record.REPLY_LIMIT
            )
            return "ok", r.data, r.payload
        except Exception as exc:
            return "error", exc, None

    def _read_phase(self) -> None:
        rows = self._read_rows()
        total = len(rows)
        self.counts["pending"] = total
        if not total:
            return
        pool = self._pool()
        done = 0
        it = iter(rows)
        window = max(2, 2 * getattr(pool, "workers", self.workers))
        with cf.ThreadPoolExecutor(max_workers=getattr(pool, "workers", self.workers)) as ex:
            running: dict[cf.Future, _Row] = {}
            exhausted = False
            while True:
                while not exhausted and len(running) < window and not self._over():
                    row = next(it, None)
                    if row is None:
                        exhausted = True
                        break
                    if row.size is not None and row.size > self.max_file_bytes:
                        self._begin()
                        self._failed(
                            row, "file_too_large", _error_object("file_too_large", None, "FileTooLargeError")
                        )
                        done += 1
                        continue
                    running[ex.submit(self._read_one, pool, row)] = row
                if not running:
                    break
                finished, _ = cf.wait(list(running), timeout=BATCH_SECONDS, return_when=cf.FIRST_COMPLETED)
                for fut in finished:
                    row = running.pop(fut)
                    self._begin()
                    self._take(row, fut.result())
                    done += 1
                    self._tx_n += 1
                self._commit()
                self._report("read", done, total)
        self._commit(force=True)
        self.counts["pending"] = total - done

    def _take(self, row: _Row, result: tuple) -> None:
        status, data, payload = result
        if status != "ok":
            exc = data
            code = model.error_code(exc)
            if code in QUARANTINE_CODES and self.cancel is not None and self.cancel.is_set():
                return  # stopped under the read (the workers are going): read again next time
            info = model.error_info(exc, reader_message=False)
            if code == "timeout" and info["detail"].get("rule") == "no_free_worker":
                # the read never started: a pool shared with other work had no worker free in
                # time, which says nothing about the file (it is tried again, never quarantined)
                code = "busy"
                info = _error_object(code, "no_free_worker", info["exception"])
            self._failed(row, code, info)
            return
        try:
            rec = record.check_record(data)
        except record.InvalidRecord as exc:
            self._failed(row, "internal", model.error_info(exc, reader_message=False))
            return
        if "not_solidworks" in rec:
            self._clear_document(row.id)
            self.con.execute(
                "UPDATE files SET state = 'not_solidworks', error_code = NULL, error_count = 0, resolve = 0 "
                "WHERE id = ?",
                (row.id,),
            )
            self._search_row(row.id, row.rel, row.name, document=False)
            self._resolve_naming((fold(row.name),))
            self.counts["not_solidworks"] += 1
            return
        self._store(row, rec, payload)
        self.counts["read_ok"] += 1

    def _failed(self, row: _Row, code: str, info: dict[str, Any]) -> None:
        count = row.error_count + 1
        if code in QUARANTINE_CODES and count >= 2:
            state, code = "quarantined", "quarantined"
        else:
            state = "error"
        retryable = 1 if code in RETRY_CODES else 0
        self._clear_document(row.id)
        self.con.execute(
            "UPDATE files SET state = ?, error_code = ?, error_retryable = ?, error_count = ?, resolve = 0 "
            "WHERE id = ?",
            (state, code, retryable, row.error_count if code == "busy" else count, row.id),
        )
        self._search_row(row.id, row.rel, row.name, document=False)
        self._resolve_naming((fold(row.name),))
        self._resolve_alibre((row.name,))
        self._event("read_error", row.id, row.root, row.rel, size=row.size)
        self.counts["read_errors"] += 1
        if len(self.errors) < MAX_ERRORS:
            error = (
                info
                if info.get("code") == code
                else _error_object(code, None, info.get("exception") or "SolidSeasError")
            )
            self.errors.append({"root": self.root_ids.get(row.root), "path": row.rel, "error": error})

    def _store(self, row: _Row, rec: dict[str, Any], payload: bytes | None) -> None:
        con = self.con
        fid = row.id
        self._clear_document(fid)
        pv = rec["preview"]
        image = record.check_preview(pv, payload) if self.previews else None
        fields = rec["fields"]
        ident = rec["identity"]
        con.execute(
            "INSERT INTO documents (file, format, doc_type, doc_type_source, release, release_verified, "
            "format_version, last_build, active_configuration, creation_time, creation_source, "
            "folder_at_save, material, title, author, last_saved_by, keywords, comments, last_saved_utc, "
            "units, preview_mime, preview_width, preview_height, preview_bytes, preview_sha256, "
            "preview_stream, counts, warnings, references_state, doc_guid, doc_version) VALUES (?, ?, ?, ?, "
            "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fid,
                rec["format"],
                rec["doc_type"],
                rec["doc_type_source"],
                rec["release"],
                int(rec["release_verified"]),
                rec["format_version"],
                rec["last_build"],
                rec["active_configuration"],
                ident["creation_time"],
                ident["source"],
                rec["folder_at_save"],
                rec["material"],
                fields["title"],
                fields["author"],
                fields["last_saved_by"],
                fields["keywords"],
                fields["comments"],
                fields["last_saved_utc"],
                json.dumps(rec["units"]) if rec["units"] is not None else None,
                pv["mime"] if pv else None,
                pv["width"] if pv else None,
                pv["height"] if pv else None,
                pv["bytes"] if pv else None,
                pv["sha256"] if pv else None,
                pv["stream"] if pv else None,
                json.dumps(rec["counts"]),
                json.dumps(rec["warnings"]) if rec["warnings"] else None,
                rec["references_state"],
                (rec["document"] or {}).get("guid"),
                (rec["document"] or {}).get("version"),
            ),
        )
        file_props = rec["properties"]
        prop_rows = [
            (
                fid,
                None,
                p["name"],
                fold(p["name"]),
                p["type"],
                p["text"],
                record.value_json(p["value"]),
                p["expression"],
                int(p["linked"]),
            )
            for p in file_props
        ]
        cfg_rows = []
        stem = os.path.splitext(row.name)[0]
        for pos, c in enumerate(rec["configurations"]):
            prop_rows += [
                (
                    fid,
                    c["name"],
                    p["name"],
                    fold(p["name"]),
                    p["type"],
                    p["text"],
                    record.value_json(p["value"]),
                    p["expression"],
                    int(p["linked"]),
                )
                for p in c["properties"]
            ]
            pn, source = stem, "document_name"
            if self.pn_property:
                value = _effective(c, file_props, self.pn_property)
                if value:
                    pn, source = value, "property"
            cfg_rows.append(
                (
                    fid,
                    pos,
                    c["name"],
                    c["id"],
                    int(c["active"]),
                    None if c["most_recent"] is None else int(c["most_recent"]),
                    c["comment"],
                    c["material"],
                    pn,
                    source,
                    _effective(c, file_props, DESCRIPTION),
                )
            )
        if prop_rows:
            con.executemany(
                "INSERT INTO properties (file, configuration, name, name_fold, type, text, value, "
                "expression, linked) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                prop_rows,
            )
        if cfg_rows:
            con.executemany(
                "INSERT INTO configurations (file, position, name, sw_id, active, most_recent, comment, "
                "material, "
                "part_number, part_number_source, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                cfg_rows,
            )
        refs = rec["references"]
        if refs:
            con.executemany(
                "INSERT INTO refs (file, key, position, stored_path, file_name, name_fold, doc_type, direct, "
                "virtual, imported, embedded, nested, stored_creation_time, parent_documents, "
                "nested_creation_time, nested_identity_source, nested_identity_error, doc_version) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        fid,
                        r["key"],
                        pos,
                        r["stored_path"],
                        r["file_name"],
                        fold(r["file_name"]) if r["file_name"] else None,
                        r["doc_type"],
                        None if r["direct"] is None else int(r["direct"]),
                        int(r["virtual"]),
                        int(r["imported"]),
                        r["embedded"],
                        r["nested"],
                        r["stored_creation_time"],
                        r["parent_documents"],
                        (r["nested_identity"] or {}).get("creation_time"),
                        (r["nested_identity"] or {}).get("source"),
                        (r["nested_identity"] or {}).get("error"),
                        r["version"],
                    )
                    for pos, r in enumerate(refs)
                ],
            )
        if rec["edges"]:
            con.executemany(
                "INSERT INTO edges (file, parent_key, parent_configuration, child_key, child_configuration, "
                "instances, unsuppressed, in_bom, alternate_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(fid, *e) for e in rec["edges"]],
            )
        if rec["views"]:
            con.executemany(
                "INSERT INTO views (file, position, sheet, view, configuration, key) VALUES (?, ?, ?, ?, ?, "
                "?)",
                [(fid, pos, *v) for pos, v in enumerate(rec["views"])],
            )
        if image is not None:
            con.execute(
                "INSERT OR IGNORE INTO pv.previews (sha256, mime, width, height, data) VALUES (?, ?, ?, ?, "
                "?)",
                (pv["sha256"], pv["mime"], pv["width"], pv["height"], image),
            )
        stat = rec["stat"]
        size = stat["size"] if stat["size"] is not None else row.size
        mtime = stat["mtime_ns"] if stat["mtime_ns"] is not None else row.mtime_ns
        # the listing's own file id stays where it gave one (Linux and macOS), so a rescan compares
        # like with like; elsewhere the id is the one the worker read the file through
        con.execute(
            "UPDATE files SET state = 'ok', read_size = ?, read_mtime_ns = ?, size = ?, mtime_ns = ?, "
            "reader_revision = ?, file_id = coalesce(file_id, ?), error_code = NULL, error_retryable = NULL, "
            "error_count = 0, resolve = ? WHERE id = ?",
            (size, mtime, size, mtime, schema.READER_REVISION, stat["file_id"], 1 if refs else 0, fid),
        )
        self._search_row(fid, row.rel, row.name)
        self._resolve_naming((fold(row.name),))
        self._resolve_alibre((row.name,))

    # ------------------------------------------------------------------ phase 2: resolve
    def _resolve_phase(self) -> None:
        """Resolve every document marked to be (``files.resolve``): marked as the changes
        that ask for it were committed, in this scan or one that stopped before this phase."""
        con = self.con
        self._begin()
        con.execute("UPDATE files SET resolve = 0 WHERE resolve = 1 AND state <> 'ok'")
        self._commit(force=True)
        docs = con.execute(
            "SELECT f.id, f.root, f.rel, d.format FROM files f LEFT JOIN documents d ON d.file = f.id WHERE "
            "f.resolve = 1 ORDER BY f.root, f.rel"
        ).fetchall()
        if not docs:
            return
        alibre = [fid for fid, _db, _rel, fmt in docs if fmt == "alibre"]
        docs = [(fid, db, rel) for fid, db, rel, fmt in docs if fmt != "alibre"]
        done = 0
        for fid in alibre:  # found by GUID among the rows: no folder index, no identity read
            if self._over():
                break
            self._begin()
            resolve_alibre(con, fid, scan_id=self.scan_id)
            done += 1
            self._tx_n += 1
            self._commit()
            self._report("resolve", done, len(alibre) + len(docs))
        self._commit(force=True)
        self.counts["resolved_documents"] = done
        if not docs:
            return
        roots = []
        for db, root in self.cat._root_rows():
            info = self.walks.get(db)
            partial = None
            if info is not None:
                partial = "unavailable" if info.state == "unavailable" else info.partial
            else:
                partial = con.execute("SELECT partial FROM roots WHERE id = ?", (db,)).fetchone()[0]
            roots.append((db, root, partial))
        indexes = RowIndexes(con, roots)
        errors: list = []

        def done_one() -> None:
            self._tx_n += 1
            self._commit()

        where = {fid: (db, rel) for fid, db, rel in docs}
        n = resolve_documents(
            con,
            indexes,
            self.cat.roots,
            ((fid, host_path(self.root_paths[db], rel)) for fid, db, rel in docs),
            scan_id=self.scan_id,
            over=self._over,
            begin=self._begin,
            commit=done_one,
            errors=errors,
            progress=lambda n: self._report("resolve", done + n, len(alibre) + len(docs)),
        )
        self._commit(force=True)
        self.counts["resolved_documents"] = done + n
        for fid, _exc in errors:
            db, rel = where[fid]
            if len(self.errors) < MAX_ERRORS:
                self.errors.append(
                    {
                        "root": self.root_ids.get(db),
                        "path": rel,
                        "error": model.error_info(_exc, reader_message=False),
                    }
                )

    # ------------------------------------------------------------------ phase 3: hash
    def _hash_rows(self) -> list[tuple]:
        """The files to hash now: those the policy of their root (``roots.hash_policy``, set
        at the start of the scan) wants and that have no current hash, read already, in the
        roots that could be listed."""
        if not self.available:
            return []
        roots = sorted(self.available)
        marks = ",".join("?" * len(roots))
        return self.con.execute(
            "SELECT f.id, f.root, f.rel, f.size, f.mtime_ns FROM files f JOIN roots ro ON ro.id = f.root "
            f"WHERE {query.HASH_WANTED} AND f.state <> 'pending' AND f.root IN ({marks}) "
            "ORDER BY f.root, f.rel",
            roots,
        ).fetchall()

    def _hash_one(self, pool, row: tuple) -> tuple:
        fid, db, rel, size, mtime = row
        timeout = HASH_BASE_SECONDS + (size or 0) / HASH_BYTES_PER_SECOND
        try:
            r = pool.call(
                "content_hash",
                {"path": host_path(self.root_paths[db], rel), "within": self.root_paths[db]},
                timeout=timeout,
            )
            return "ok", r.data
        except Exception as exc:
            return "error", exc

    def _hash_each(self, rows: list[tuple], take: Callable[[tuple, str], None]) -> int:
        """Hash ``rows`` (``(id, root, rel, size, mtime_ns, ...)``) in the pool, calling
        ``take(row, sha256)`` in this thread for each hash that holds: the file did not
        change while it was read and still has the size and time of its row. How many."""
        total = len(rows)
        if not total:
            return 0
        pool = self._pool()
        done = taken = 0
        it = iter(rows)
        workers = getattr(pool, "workers", self.workers)
        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            running: dict[cf.Future, tuple] = {}
            exhausted = False
            while True:
                while not exhausted and len(running) < 2 * workers and not self._over():
                    row = next(it, None)
                    if row is None:
                        exhausted = True
                        break
                    running[ex.submit(self._hash_one, pool, row[:5])] = row
                if not running:
                    break
                finished, _ = cf.wait(list(running), timeout=BATCH_SECONDS, return_when=cf.FIRST_COMPLETED)
                for fut in finished:
                    row = running.pop(fut)
                    status, data = fut.result()
                    done += 1
                    if status != "ok" or not isinstance(data, dict):
                        continue
                    sha = data.get("sha256")
                    try:
                        mtime = int(data.get("mtime_ns"))
                    except (TypeError, ValueError):
                        continue
                    if (
                        data.get("stable") is True
                        and isinstance(sha, str)
                        and len(sha) == 64
                        and all(ch in "0123456789abcdef" for ch in sha)
                        and data.get("size") == row[3]
                        and mtime == row[4]
                    ):
                        self._begin()
                        take(row, sha)
                        self._tx_n += 1
                        taken += 1
                self._commit()
                self._report("hash", done, total)
        self._commit(force=True)
        return taken

    def _hash_phase(self) -> None:
        def take(row: tuple, sha: str) -> None:
            self.con.execute(
                "UPDATE files SET sha256 = ?, hash_size = ?, hash_mtime_ns = ? WHERE id = ? "
                "AND size = ? AND mtime_ns = ?",
                (sha, row[3], row[4], row[0], row[3], row[4]),
            )

        self.counts["hashed"] += self._hash_each(self._hash_rows(), take)

    def _verify_phase(self) -> None:
        """With ``verify``: hash again each file the walk found unchanged that holds a
        hash of its present size and time. A file rewritten in place with its time put
        back (which the listing cannot tell, on Windows, where it gives no file id, nor
        anywhere when the file id stays) has other bytes: it is a changed file, read
        again in this scan, its references and the documents naming it resolved again,
        with a ``changed`` event. Counted in ``verified`` and, when they differ,
        ``changed``."""
        if not self.available:
            return
        roots = sorted(self.available)
        marks = ",".join("?" * len(roots))
        rows = self.con.execute(
            "SELECT id, root, rel, size, mtime_ns, sha256, name FROM files WHERE kind = 'file' AND stale = 0 "
            "AND sha256 IS NOT NULL AND hash_size IS size AND hash_mtime_ns IS mtime_ns "
            f"AND state <> 'pending' AND seen_scan = ? AND changed_scan <> ? AND root IN ({marks}) "
            "ORDER BY root, rel",
            (self.scan_id, self.scan_id, *roots),
        ).fetchall()

        def take(row: tuple, sha: str) -> None:
            fid, db, rel, size, mtime, old, name = row
            if sha == old:
                return
            self.con.execute(
                "UPDATE files SET state = 'pending', changed_scan = ?, sha256 = ?, hash_size = ?, "
                "hash_mtime_ns = ?, error_code = NULL, error_retryable = NULL, error_count = 0 "
                "WHERE id = ? AND size = ? AND mtime_ns = ?",
                (self.scan_id, sha, size, mtime, fid, size, mtime),
            )
            self._event("changed", fid, db, rel, size=size, sha256=sha, previous_sha256=old)
            self.counts["changed"] += 1
            self.counts["unchanged"] -= 1
            self._resolve_naming([fold(name)])

        self.counts["verified"] = self._hash_each(rows, take)

    # ------------------------------------------------------------------ the end
    def _finish(self, state: str) -> dict[str, Any]:
        con = self.con
        if self._in_tx:
            con.execute("COMMIT")
            self._in_tx = False
        if state == "done" and self.stopped == "cancelled":
            state = "cancelled"
        elif state == "done" and self.stopped == "deadline":
            state = "truncated"
        self.counts["hash_pending"] = query.hash_pending(con)
        con.execute("BEGIN IMMEDIATE")
        roots_out = []
        for db, root in self.cat._root_rows():
            info = self.walks.get(db)
            if info is None:
                roots_out.append(
                    {
                        "id": root.id,
                        "state": "not_scanned",
                        "entries": 0,
                        "documents": 0,
                        "truncated_reason": self.stopped,
                    }
                )
                continue
            pending = con.execute(
                "SELECT count(*) FROM files WHERE root = ? AND (state = 'pending' OR resolve = 1)", (db,)
            ).fetchone()[0]
            complete = info.state == "ready" and pending == 0
            if info.state == "unavailable":
                root_state = "unavailable"
            else:
                root_state = "ready" if complete else "partial"
            con.execute(
                "UPDATE roots SET state = ?, partial = ?, last_scan = ?, "
                "last_complete_scan = CASE WHEN ? THEN ? ELSE last_complete_scan END WHERE id = ?",
                (
                    root_state,
                    "unavailable" if info.state == "unavailable" else info.partial,
                    self.scan_id,
                    int(complete),
                    self.scan_id,
                    db,
                ),
            )
            roots_out.append(
                {
                    "id": root.id,
                    "state": info.state,
                    "entries": info.entries,
                    "documents": info.documents,
                    "truncated_reason": info.truncated,
                }
            )
        data = {
            "catalog": self.cat.name,
            "scan": self.scan_id,
            "state": state,
            "roots": roots_out,
            "removed_roots": list(self.removed_roots),
            "counts": dict(self.counts),
            "seconds": {k: round(v, 3) for k, v in self.seconds.items()},
            "errors": list(self.errors),
            "truncated": self.stopped == "deadline"
            or any(r.get("truncated_reason") in ("max_examined", "deadline") for r in roots_out),
            "truncated_reason": "deadline"
            if self.stopped == "deadline"
            else next(
                (
                    r["truncated_reason"]
                    for r in roots_out
                    if r.get("truncated_reason") in ("max_examined", "deadline")
                ),
                None,
            ),
            "cancelled": self.stopped == "cancelled",
        }
        con.execute(
            "UPDATE scans SET finished_utc = ?, state = ?, counts = ? WHERE id = ?",
            (utc_now(), state, json.dumps(self.counts), self.scan_id),
        )
        days = int(self.cat.meta("events_days") or DEFAULT_EVENTS_DAYS)
        limit = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)
        con.execute("DELETE FROM events WHERE time_utc < ?", (model.iso8601(limit.replace(microsecond=0)),))
        con.execute(
            "DELETE FROM pv.previews WHERE sha256 NOT IN "
            "(SELECT preview_sha256 FROM documents WHERE preview_sha256 IS NOT NULL)"
        )
        con.execute("COMMIT")
        self.cat._checkpoint()
        return model.to_json_data(data)


__all__ = [
    "DEFAULT_FILE_TIMEOUT",
    "DEFAULT_MAX_FILE_BYTES",
    "DEFAULT_WORKERS",
    "HASH_POLICIES",
    "PHASES",
    "Scanner",
]
