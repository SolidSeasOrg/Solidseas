"""The catalog: an index of the 3D files below a set of roots (provisional API,
``docs/API.md`` 3.18): SOLIDWORKS documents, and every other format SolidSeas reads
when its ``formats`` setting says so (:meth:`Catalog.configure`).

A catalog scans its roots, identifies every document by its path, its file id
and the SHA-256 of its bytes, and keeps in SQLite what each one says: its
type, saved version, configurations and properties (part numbers and
descriptions among them), its preview, the files it references with how each
resolves, and an assembly's model graph with quantities per configuration. The
desktop app and integrations query it instead of reading the files again:

* :meth:`Catalog.where_used`: which assemblies and drawings use a part or a
  sub-assembly, directly and through sub-assemblies, in which configuration
  and how many;
* :meth:`Catalog.search`: by name, part number, description or any property;
* :meth:`Catalog.duplicates`, :meth:`Catalog.missing_references` and
  :meth:`Catalog.changes`.

```python
from solidseas import catalog

if __name__ == "__main__":  # the workers are started with spawn, which imports this module again
    with catalog.open("D:/Jobs/Example") as cat:  # the catalog of that folder, in the user's cache
        cat.scan()                                # documents are read in worker processes
        used = cat.where_used("project", "parts/bracket.SLDPRT")
```

**Where it lives.** In the user's cache folder by default
(:func:`cache_dir`; ``SOLIDSEAS_CACHE_DIR`` overrides it), one catalog per
project folder. Beside the project (``<root>/.solidseas``) only when the caller
asks for ``location="project"``, and anywhere else only through ``db=``. A
catalog is never kept on a network location: a UNC path or a mapped drive on
Windows, a network file system's mount on Linux and macOS
(:mod:`solidseas.netfs`). A scan
never writes into a scanned folder otherwise. A
damaged catalog in the cache is made again when it is next opened for writing
or scanned; elsewhere it is ``catalog_incompatible`` (rule ``damaged``) until
it is cleared.

**Who writes.** One writer per catalog (an OS lock beside the database), which
never parses a CAD file: documents are read in a
:class:`~solidseas.workers.WorkerPool` and folders walked by the one walker
(:mod:`solidseas.walk`). Readers open the database read-only and never block
the writer. :mod:`.scan` has the phases, :mod:`.query` the queries,
:mod:`.record` the worker's record and its checks, :mod:`.resolution`
reference resolution from rows, :mod:`.store` the files and the lock, and
:mod:`.schema` the tables.

**What it holds.** Every document's name and path below its root, the roots'
own paths, every property (part numbers, descriptions, customers, prices if a
property holds them), the stored paths of references (absolute paths from other
machines), preview images, hashes and 90 days of change events.
:func:`clear` deletes a catalog; nothing in it ever leaves the machine.
"""

import contextlib
import os
import threading
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from ..errors import BusyError, CatalogIncompatibleError, InvalidArgumentError, PathRefusedError
from ..resolve.names import fold
from ..roots import Root, Roots
from . import query, record, schema, store
from .store import cache_dir

LOCATIONS = ("cache", "project", "file")
MODES = ("r", "w")
DEFAULT_EVENTS_DAYS = 90


def _as_roots(roots: Any) -> Roots | None:
    """``roots`` as :class:`Roots`: a Roots, Root objects, ``{id: folder}``, or folder paths
    (the first is root ``project``, the next ``project2``...)."""
    if roots is None:
        return None
    if isinstance(roots, Roots):
        out = roots
    elif isinstance(roots, Root):
        out = Roots([roots])
    elif isinstance(roots, Mapping):
        out = Roots.from_mapping(roots)
    elif isinstance(roots, (str, os.PathLike)):
        out = Roots([Root("project", os.path.abspath(os.fspath(roots)))])
    elif isinstance(roots, Iterable):
        items = []
        n = 0
        for r in roots:
            if isinstance(r, Root):
                items.append(r)
            else:
                n += 1
                items.append(Root("project" if n == 1 else f"project{n}", os.path.abspath(os.fspath(r))))
        out = Roots(items)
    else:
        raise InvalidArgumentError(
            "roots is a Roots, Root objects, {id: folder} or folders", detail={"parameter": "roots"}
        )
    folded = [(fold(r.path).rstrip("\\/"), r) for r in out]
    sep = "\\" if os.name == "nt" else "/"
    for a, ra in folded:
        for b, rb in folded:
            if ra is not rb and (b == a or b.startswith(a + sep)):
                raise InvalidArgumentError(
                    f"roots {ra.id} and {rb.id} overlap: every file below both would be indexed twice",
                    detail={"parameter": "roots", "rule": "overlapping_roots"},
                )
    return out


@contextlib.contextmanager
def _sqlite_errors():
    """SQLite's errors on a catalog as the caller's: ``catalog_incompatible`` (rule
    ``damaged``) for a damaged database, ``permission_denied`` for one that cannot be
    written; any other error stands."""
    try:
        yield
    except Exception as exc:
        better = store.translate(exc)
        if better is None:
            raise
        raise better from exc


def _is_damaged(exc: BaseException) -> bool:
    return isinstance(exc, CatalogIncompatibleError) and (exc.detail or {}).get("rule") == "damaged"


def _first_project(roots: Roots) -> Root:
    for r in roots:
        if r.role == "project":
            return r
    return next(iter(roots))


def locate(
    roots: Any = None,
    *,
    location: str = "cache",
    name: str | None = None,
    db: str | os.PathLike | None = None,
    cache_dir: str | None = None,
) -> tuple[str, str, str]:
    """``(database path, location, name)`` for these arguments, without making anything."""
    if location not in LOCATIONS:
        raise InvalidArgumentError("location is cache, project or file", detail={"parameter": "location"})
    rs = _as_roots(roots)
    if db is not None:
        path = store.check_db_path(os.fspath(db))
        return path, "file", name or os.path.splitext(os.path.basename(path))[0]
    if location == "file":
        raise InvalidArgumentError("location file needs db", detail={"parameter": "db"})
    if location == "project":
        if not rs:
            raise InvalidArgumentError(
                "the in-project location needs a project root", detail={"parameter": "roots"}
            )
        project = _first_project(rs)
        if store.is_network(project.path):
            raise PathRefusedError(
                "a catalog is never kept on a network location: SQLite's locks are not reliable there",
                detail={"rule": "network_location"},
            )
        folder = os.path.join(project.path, store.PROJECT_FOLDER)
        return os.path.join(folder, store.CATALOG_FILE), "project", name or store.default_name(project.path)
    if name is None:
        if not rs:
            raise InvalidArgumentError("a catalog needs a name or roots", detail={"parameter": "catalog"})
        name = store.default_name(_first_project(rs).path)
    store.check_name(name)
    base = store.catalogs_dir(cache_dir)
    return os.path.join(base, name, store.CATALOG_FILE), "cache", name


class Catalog:
    """One open catalog: ``mode="w"`` holds the writer lock and may :meth:`scan`;
    ``mode="r"`` only queries. Use :func:`open`. Not thread-safe: open one per thread
    (:meth:`reader` opens a read-only one on the same database)."""

    def __init__(self, path: str, *, location: str, name: str | None, roots: Roots | None, mode: str) -> None:
        if mode not in MODES:
            raise InvalidArgumentError("mode is r or w", detail={"parameter": "mode"})
        self.path = path
        self.location = location
        self.name = name or ""
        self.mode = mode
        self.previews_path = store.sidecar(path, store.PREVIEWS_FILE)
        self._lock: store.WriterLock | None = None
        self._vacuum = False
        self._previews_attached = False
        self._scan_lock = threading.Lock()
        self.con = None
        if store.is_network(path):  # SQLite's shared memory and locks need a local disk
            raise PathRefusedError(
                "a catalog is never kept on a network location: SQLite's locks are not reliable there",
                detail={"rule": "network_location"},
            )
        try:
            if mode == "w":
                store.check_catalog_files(path)  # nothing is ever written through a link
                # a database that is not a catalog is refused before anything is made beside it
                for p, app in (
                    (path, schema.APPLICATION_ID),
                    (self.previews_path, schema.PREVIEWS_APPLICATION_ID),
                ):
                    if store.file_application_id(p) not in (None, app):
                        raise store.not_a_catalog()
                folder = os.path.dirname(path)
                if location in ("cache", "project"):
                    store.make_private_dir(folder)
                self._lock = store.WriterLock(store.sidecar(path, store.LOCK_FILE)).acquire()
                with _sqlite_errors():
                    self._connect_writer()
            else:
                self.con = store.connect_reader(path)
            with _sqlite_errors():
                if not name:  # the name it was made with (an in-project catalog found by its folder)
                    self.name = self.meta("catalog_name") or os.path.splitext(os.path.basename(path))[0]
                engine = self.meta("search_engine")
                self.fts5 = engine == "fts5" and store.fts5_available()
                # the roots a writer was given become the catalog's at its next scan; a reader has
                # the stored ones, whatever it was located by
                self.roots = roots if roots is not None and mode == "w" else self._stored_roots()
        except BaseException:
            self.close()
            raise

    # ------------------------------------------------------------------ set-up
    def _connect_writer(self) -> None:
        self.con = store.connect_writer(self.path)
        self._prepare()
        store.attach_previews(self.con, self.previews_path, writing=True)
        self._previews_attached = True

    def _start_over(self) -> None:
        """Delete a damaged catalog's database and previews (the writer lock stays held) and
        make it again: a catalog is a cache of what the files say, and the next scan reads
        them all again."""
        con, self.con = self.con, None
        if con is not None:
            try:
                con.close()
            except Exception:
                pass
        self._previews_attached = False
        for base in (self.path, self.previews_path):
            for suffix in ("", "-wal", "-shm", "-journal"):
                if os.path.lexists(base + suffix):
                    os.remove(base + suffix)
        with _sqlite_errors():
            self._connect_writer()
        self.fts5 = self.meta("search_engine") == "fts5" and store.fts5_available()

    def _prepare(self) -> None:
        con = self.con
        version = con.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            fts5 = store.fts5_available()
            con.execute("BEGIN IMMEDIATE")
            schema.create(con, fts5=fts5)
            from .. import __version__
            from .scan import utc_now

            for key, value in (
                ("schema_version", str(schema.SCHEMA_VERSION)),
                ("min_reader_schema", str(schema.MIN_READER_SCHEMA)),
                ("created_utc", utc_now()),
                ("created_by", __version__),
                ("catalog_name", self.name),
                ("location", self.location),
                ("reader_revision", str(schema.READER_REVISION)),
                ("search_engine", "fts5" if fts5 else "like"),
                ("events_days", str(DEFAULT_EVENTS_DAYS)),
            ):
                con.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (key, value))
            con.execute(f"PRAGMA user_version={schema.SCHEMA_VERSION}")
            con.execute("COMMIT")
            return
        while version < schema.SCHEMA_VERSION:
            step = schema.MIGRATIONS.get(version)
            con.execute("BEGIN IMMEDIATE")
            try:
                if step is None:
                    fts5 = store.fts5_available()
                    schema.rebuild(con, fts5=fts5)
                    version = schema.SCHEMA_VERSION
                    for key, value in (
                        ("search_engine", "fts5" if fts5 else "like"),
                        ("reader_revision", str(schema.READER_REVISION)),
                        ("min_reader_schema", str(schema.MIN_READER_SCHEMA)),
                    ):
                        con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
                else:
                    step(con)
                    version += 1
                con.execute(f"PRAGMA user_version={version}")
                con.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)", (str(version),)
                )
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
        # a writer that died left its scan running: say so
        con.execute("UPDATE scans SET state = 'failed' WHERE state = 'running'")

    def _stored_roots(self) -> Roots:
        rows = self.con.execute(
            "SELECT root_id, path, recursive, role FROM roots ORDER BY position"
        ).fetchall()
        return Roots(Root(r[0], r[1], bool(r[2]), r[3]) for r in rows)

    def keep_stored_ids(self, made_up: Iterable[str]) -> None:
        """Let each of the roots given to this writer whose id is in ``made_up`` (an id the
        caller made up, such as the command line's ``project`` for a folder given without
        one) take the id the catalog already stores for its folder, unless another given
        root has that id. ``solidseas index FOLDER`` and ``serve --catalog`` share the
        catalog of a folder; without this, each scan by one renamed the roots the other
        named, and every assembly and drawing was resolved again."""
        self._writable()
        made_up = set(made_up)
        stored = {fold(r.path).rstrip("\\/"): r.id for r in self._stored_roots()}
        given = list(self.roots or ())
        taken = {r.id for r in given if r.id not in made_up}
        out = []
        for r in given:
            new = stored.get(fold(r.path).rstrip("\\/")) if r.id in made_up else None
            if new is not None and new != r.id and new not in taken:
                r = Root(new, r.path, r.recursive, r.role)
            taken.add(r.id)
            out.append(r)
        if len({r.id for r in out}) == len(out):  # else a made-up id was taken: keep them all
            self.roots = Roots(out)

    def _root_rows(self) -> list[tuple[int, Root]]:
        by_id = {r.id: r for r in self.roots}
        out = []
        for db, root_id in self.con.execute("SELECT id, root_id FROM roots ORDER BY position").fetchall():
            if root_id in by_id:
                out.append((db, by_id[root_id]))
        return out

    def meta(self, key: str) -> str | None:
        row = self.con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def _checkpoint(self) -> None:
        for db in ("main", "pv") if self._previews_attached else ("main",):
            try:
                self.con.execute(f"PRAGMA {db}.wal_checkpoint(TRUNCATE)")
            except Exception:  # a reader holds the log: the next checkpoint takes it
                pass
        if self._vacuum:
            self._vacuum = False
            try:
                self.con.execute("VACUUM")
            except Exception:
                pass

    def _writable(self) -> None:
        if self.mode != "w" or self.con is None:
            raise InvalidArgumentError("the catalog was opened read-only", detail={"parameter": "mode"})

    # ------------------------------------------------------------------ writing
    @property
    def formats(self) -> frozenset[str]:
        """The formats (registry ids) the catalog indexes: its ``formats`` setting
        (:meth:`configure`), SOLIDWORKS documents until it is changed."""
        return record.stored_formats(self.meta("formats"))

    def configure(
        self,
        *,
        part_number_property: str | None = ...,  # type: ignore[assignment]
        hash: str | None = ...,  # type: ignore[assignment]  # noqa: A002
        events_days: int | None = None,
        formats: Any = None,
    ) -> None:
        """Change the catalog's options. ``part_number_property`` takes each configuration's
        part number from that property (configuration first, then file), recomputed from
        the stored properties at once; None goes back to the document name. ``hash`` is the
        default hash policy of scans (None: by root). ``events_days`` is how long change
        events are kept. ``formats`` is what the scans index: ``"solidworks"`` (the
        default), ``"all"`` (every format SolidSeas reads) or format ids; the files of a
        format left out are removed from the catalog at once, with no change events, and
        those of a format added are indexed by the next scan."""
        self._writable()
        with _sqlite_errors():
            self._configure(part_number_property, hash, events_days, formats)

    def _configure(
        self,
        part_number_property: Any,
        hash: Any,  # noqa: A002
        events_days: int | None,
        formats: Any = None,
    ) -> None:
        from .scan import HASH_POLICIES

        con = self.con
        if formats is not None:
            wanted = record.indexed_formats(formats)  # an unknown id is refused here
            if not wanted:
                raise InvalidArgumentError(
                    "formats names no format SolidSeas reads", detail={"parameter": "formats"}
                )
            setting = "all" if wanted == record.indexed_formats("all") else ",".join(sorted(wanted))
        con.execute("BEGIN IMMEDIATE")
        try:
            if formats is not None and (self.meta("formats") or record.DEFAULT_FORMATS) != setting:
                self._drop_formats(record.indexed_extensions(wanted))
                con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('formats', ?)", (setting,))
            if part_number_property is not ...:
                if part_number_property is not None and (
                    not isinstance(part_number_property, str) or not 0 < len(part_number_property) <= 255
                ):
                    raise InvalidArgumentError(
                        "part_number_property is a property name",
                        detail={"parameter": "part_number_property"},
                    )
                con.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES ('part_number_property', ?)",
                    (part_number_property or "",),
                )
                self._recompute_part_numbers(part_number_property)
            if hash is not ...:
                if hash is not None and hash not in HASH_POLICIES:
                    raise InvalidArgumentError(
                        "hash is all, duplicates or none", detail={"parameter": "hash"}
                    )
                con.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES ('hash_policy', ?)", (hash or "",)
                )
            if events_days is not None:
                if (
                    isinstance(events_days, bool)
                    or not isinstance(events_days, int)
                    or not 1 <= events_days <= 3650
                ):
                    raise InvalidArgumentError(
                        "events_days is 1 to 3650", detail={"parameter": "events_days"}
                    )
                con.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES ('events_days', ?)", (str(events_days),)
                )
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise

    def _drop_formats(self, extensions: tuple[str, ...]) -> None:
        """Remove the files whose extension is not one of ``extensions`` (a format the
        catalog no longer indexes), with what was read of them, and mark the documents
        whose references found one to be resolved again. No change event is recorded: the
        files did not change. Folders left empty go at the next scan."""
        con = self.con
        ids = [
            fid
            for fid, name in con.execute("SELECT id, name FROM files").fetchall()
            if not name.lower().endswith(extensions)
        ]
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            marks = ",".join("?" * len(chunk))
            con.execute(
                "UPDATE files SET resolve = 1 WHERE state = 'ok' AND id IN (SELECT file FROM refs WHERE "
                f"target IN ({marks}))",
                chunk,
            )
            if self.fts5:
                con.execute(f"DELETE FROM search WHERE rowid IN ({marks})", chunk)
            con.execute(f"DELETE FROM files WHERE id IN ({marks})", chunk)
        if ids:
            self._vacuum = True

    def _recompute_part_numbers(self, prop: str | None) -> None:
        from .scan import search_row

        con = self.con
        want = fold(prop) if prop else None
        rows = con.execute(
            "SELECT c.file, c.position, c.name, f.name, f.rel FROM configurations c JOIN files f ON "
            "f.id = c.file"
        ).fetchall()
        for fid, pos, cfg, fname, _rel in rows:
            pn, source = os.path.splitext(fname)[0], "document_name"
            if want is not None:
                value = con.execute(
                    "SELECT text FROM properties WHERE file = ? AND name_fold = ? AND "
                    "(configuration = ? OR configuration IS NULL) ORDER BY configuration IS NULL LIMIT 1",
                    (fid, want, cfg),
                ).fetchone()
                if value is not None and value[0]:
                    pn, source = value[0], "property"
            con.execute(
                "UPDATE configurations SET part_number = ?, part_number_source = ? WHERE file = ? AND "
                "position = ?",
                (pn, source, fid, pos),
            )
        if self.fts5:  # the words a search finds follow the part numbers
            for fid, fname, rel in {(r[0], r[3], r[4]) for r in rows}:
                search_row(con, fid, rel, fname)

    def scan(
        self,
        *,
        pool=None,
        workers: int = 2,
        hash: str | None = None,  # noqa: A002
        previews: bool = True,
        file_timeout: float = 30.0,
        max_seconds: float | None = None,
        max_file_bytes: int | None = None,
        progress: Callable[[str, int, int], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Scan the roots and bring the catalog up to date (:mod:`.scan`); returns the
        ``catalog_scan`` data. ``pool`` is a :class:`~solidseas.workers.WorkerPool` to read
        with (its roots must include the catalog's); without one a pool of ``workers`` runs
        below normal priority for the scan. ``hash`` is ``all``, ``duplicates`` or ``none``
        (None: the catalog's setting, else ``all`` on a local drive and ``duplicates`` on a
        share). ``progress(phase, done, total)`` is called as it goes; ``cancel`` (an
        event) and ``max_seconds`` stop it between files, keeping what was committed."""
        from .scan import DEFAULT_MAX_FILE_BYTES, HASH_POLICIES, Scanner

        self._writable()
        if not self.roots:
            raise InvalidArgumentError("the catalog has no roots to scan", detail={"parameter": "roots"})
        if hash is not None and hash not in HASH_POLICIES:
            raise InvalidArgumentError("hash is all, duplicates or none", detail={"parameter": "hash"})
        if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 64:
            raise InvalidArgumentError("workers is 1 to 64", detail={"parameter": "workers"})
        for value, pname in ((file_timeout, "file_timeout"), (max_seconds, "max_seconds")):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0
            ):
                raise InvalidArgumentError(f"{pname} must be positive", detail={"parameter": pname})
        limit = DEFAULT_MAX_FILE_BYTES if max_file_bytes is None else max_file_bytes
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise InvalidArgumentError(
                "max_file_bytes must be positive", detail={"parameter": "max_file_bytes"}
            )
        if not self._scan_lock.acquire(blocking=False):
            raise BusyError("a scan of this catalog is already running", detail={"rule": "catalog_locked"})

        def run() -> dict[str, Any]:
            with _sqlite_errors():
                return Scanner(
                    self,
                    pool=pool,
                    workers=workers,
                    hash_policy=hash or (self.meta("hash_policy") or None),
                    previews=previews,
                    file_timeout=float(file_timeout),
                    max_seconds=max_seconds,
                    max_file_bytes=limit,
                    progress=progress,
                    cancel=cancel,
                ).run()

        try:
            try:
                return run()
            except CatalogIncompatibleError as exc:
                if not (_is_damaged(exc) and self.location == "cache"):
                    raise
            self._start_over()  # a damaged catalog in the cache: made again, and scanned from nothing
            return run()
        finally:
            self._scan_lock.release()

    # ------------------------------------------------------------------ reading
    def sizes(self) -> dict[str, int | None]:
        def size(p: str) -> int | None:
            total = None
            for suffix in ("", "-wal"):
                try:
                    total = (total or 0) + os.path.getsize(p + suffix)
                except OSError:
                    pass
            return total

        return {"catalog_bytes": size(self.path), "previews_bytes": size(self.previews_path)}

    def status(self, *, paths: bool = True) -> dict[str, Any]:
        """``catalog`` data: the roots, the counts, the state of the last scan."""
        writer = None
        if self.mode == "r":  # a scan marked running whose writer is gone was cut short
            writer = store.writer_alive(store.sidecar(self.path, store.LOCK_FILE))
        with _sqlite_errors():
            return query.status(
                self.con,
                name=self.name,
                location=self.location,
                sizes=self.sizes(),
                paths=paths,
                writer=writer,
            )

    def where_used(
        self,
        root: str,
        path: str,
        *,
        configuration: str | None = None,
        indirect: bool = True,
        max_depth: int = query.DEFAULT_MAX_DEPTH,
        max_seconds: float | None = None,
    ) -> dict[str, Any]:
        """``where_used`` data for the file at ``path`` below root ``root`` (:mod:`.query`).
        ``max_seconds`` stops a walk up that takes longer with ``timeout``."""
        import time

        deadline = None
        if max_seconds is not None:
            if (
                isinstance(max_seconds, bool)
                or not isinstance(max_seconds, (int, float))
                or not max_seconds > 0
            ):
                raise InvalidArgumentError(
                    "max_seconds must be positive", detail={"parameter": "max_seconds"}
                )
            deadline = time.monotonic() + max_seconds
        with _sqlite_errors():
            return query.where_used(
                self.con,
                root,
                path,
                configuration=configuration,
                indirect=indirect,
                max_depth=max_depth,
                deadline=deadline,
            )

    def search(
        self, text: str, *, sort: str = "relevance", limit: int = 100, cursor: str | None = None
    ) -> dict[str, Any]:
        """``catalog_search`` data (``docs/API.md`` 3.18 has the query text)."""
        with _sqlite_errors():
            return query.search(self.con, text, fts5=self.fts5, sort=sort, limit=limit, cursor=cursor)

    def duplicates(
        self, *, names: bool = False, limit: int = query.MAX_LIMIT, cursor: str | None = None
    ) -> dict:
        """``duplicates`` data: groups of files with identical contents, the largest waste
        first, and with ``names`` the groups of files that share a name but differ."""
        with _sqlite_errors():
            return query.duplicates(self.con, names=names, limit=limit, cursor=cursor)

    def missing_references(self, *, limit: int = query.MAX_LIMIT, cursor: str | None = None) -> dict:
        """``missing_references`` data: per document, the references that resolve nowhere
        within the roots, are ambiguous or were resolved with low confidence."""
        with _sqlite_errors():
            return query.missing_references(self.con, limit=limit, cursor=cursor)

    def changes(
        self, *, since: str | None = None, limit: int = query.MAX_LIMIT, cursor: str | None = None
    ) -> dict:
        """``catalog_changes`` data: the scans' events, newest first, since ``since``
        (``7d``, ``12h``, ``2w`` or a date) when given."""
        with _sqlite_errors():
            return query.changes(self.con, since=since, limit=limit, cursor=cursor)

    def preview(self, root: str, path: str) -> tuple[str, bytes] | None:
        """The stored preview image of a file: ``(mime, bytes)``, or None."""
        with _sqlite_errors():
            if not self._previews_attached:
                self._previews_attached = store.attach_previews(self.con, self.previews_path, writing=False)
                if not self._previews_attached:
                    return None
            return query.preview(self.con, root, path)

    def locate(self, path: str | os.PathLike) -> tuple[str, str]:
        """``(root id, path below it)`` for a host path inside one of the catalog's roots,
        from the text alone. Raises ``not_in_catalog`` for a path outside them."""
        from ..errors import NotInCatalogError

        full = os.path.abspath(os.fspath(path))
        key = fold(full)
        sep = "\\" if os.name == "nt" else "/"
        for r in self.roots:
            base = fold(r.path).rstrip("\\/")
            if key.startswith(base + sep):
                rel = full[len(r.path.rstrip("\\/")) + 1 :].replace("\\", "/")
                return r.id, rel
        raise NotInCatalogError("the file is not below any of the catalog's roots")

    def reader(self) -> "Catalog":
        """A read-only catalog on the same database, for another thread."""
        return Catalog(self.path, location=self.location, name=self.name, roots=self.roots, mode="r")

    # ------------------------------------------------------------------ closing
    def close(self) -> None:
        con, self.con = self.con, None
        if con is not None:
            try:
                con.close()
            except Exception:
                pass
        if self._lock is not None:
            self._lock.release()
            self._lock = None

    def __enter__(self) -> "Catalog":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<Catalog {self.name!r} {self.location} {self.mode}>"


def open(  # noqa: A001 - the module's verb, as catalog.open
    roots: Any = None,
    *,
    location: str = "cache",
    name: str | None = None,
    db: str | os.PathLike | None = None,
    cache_dir: str | None = None,
    mode: str = "w",
) -> Catalog:
    """Open (and, for writing, make) a catalog.

    ``roots`` is anything :class:`~solidseas.Roots` accepts, ``{id: folder}`` or folder
    paths; a scan makes them the catalog's roots (a root left out is removed with its
    rows). Without them the stored roots are used. The catalog is the one named
    ``name`` in the cache folder (default: one per first project root), the
    in-project one with ``location="project"``, or the file ``db``. ``mode="r"`` opens
    it read-only; ``"w"`` takes the writer lock (``busy`` when another process holds
    it)."""
    store.need_sqlite()
    rs = _as_roots(roots)
    path, loc, nm = locate(rs, location=location, name=name, db=db, cache_dir=cache_dir)
    if mode == "r" and not os.path.isfile(path):
        from ..errors import NotInCatalogError

        raise NotInCatalogError("no catalog exists for that folder: index it first")
    try:
        return Catalog(path, location=loc, name=nm, roots=rs, mode=mode)
    except CatalogIncompatibleError as exc:
        if not (_is_damaged(exc) and mode == "w" and loc == "cache"):
            raise
    # a damaged catalog in the cache is a cache: its files go, and it is made again
    store.remove_files(path)
    return Catalog(path, location=loc, name=nm, roots=rs, mode=mode)


def catalog_name(path: str | os.PathLike) -> str | None:
    """The name the catalog database at ``path`` was made with, read without changing
    anything; None when it cannot be read."""
    try:
        with Catalog(os.fspath(path), location="file", name="-", roots=None, mode="r") as cat:
            return cat.meta("catalog_name")
    except Exception:
        return None


def list_catalogs(cache_dir: str | None = None) -> list[dict[str, Any]]:
    """Every catalog in the cache folder: name, folder, roots (id and path), size and last
    scan. Each is opened read-only; one that cannot be read is listed with ``error``."""
    from .. import model

    base = store.catalogs_dir(cache_dir)
    out: list[dict[str, Any]] = []
    if store.is_network(base):  # catalogs are never kept on a share: nothing to list there
        return out
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return out
    for nm in names:
        path = os.path.join(base, nm, store.CATALOG_FILE)
        if not os.path.isfile(path):
            continue
        item: dict[str, Any] = {"name": nm, "folder": os.path.dirname(path), "roots": [], "error": None}
        try:
            with Catalog(path, location="cache", name=nm, roots=None, mode="r") as cat:
                item["roots"] = [{"id": r.id, "path": r.path, "role": r.role} for r in cat.roots]
                last = cat.con.execute(
                    "SELECT id, coalesce(finished_utc, started_utc), state FROM scans ORDER BY id DESC "
                    "LIMIT 1"
                ).fetchone()
                item["last_scan_utc"] = last[1] if last else None
                item["last_scan_state"] = last[2] if last else None
                item.update(cat.sizes())
        except Exception as exc:
            item["error"] = model.error_code(exc)
        out.append(item)
    return out


def find_catalog(path: str | os.PathLike, cache_dir: str | None = None) -> str | None:
    """The name of the catalog in the cache whose root holds ``path`` (the most recently
    scanned when several do), or None. A catalog that cannot be read is found only by
    its default name, that of ``path`` or a folder above it, so opening it says why."""
    here = os.path.abspath(os.fspath(path))
    full = fold(here)
    sep = "\\" if os.name == "nt" else "/"
    defaults = set()
    while True:
        defaults.add(store.default_name(here))
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    best: tuple[str, str] | None = None
    unreadable: str | None = None
    for item in list_catalogs(cache_dir):
        if item.get("error"):
            if unreadable is None and item["name"] in defaults:
                unreadable = item["name"]
            continue
        for r in item["roots"]:
            base = fold(r["path"]).rstrip("\\/")
            if full == base or full.startswith(base + sep):
                stamp = item.get("last_scan_utc") or ""
                if best is None or stamp > best[0]:
                    best = (stamp, item["name"])
    return best[1] if best else unreadable


def clear(
    name: str | None = None,
    *,
    db: str | os.PathLike | None = None,
    roots: Any = None,
    location: str = "cache",
    cache_dir: str | None = None,
    all: bool = False,  # noqa: A002
) -> list[str]:
    """Delete a catalog: its database, previews, their journals and its lock (and its folder
    in the cache when that is then empty). ``all=True`` deletes every catalog in the cache.
    Refuses with ``busy`` while a writer holds the lock. Returns the files removed."""
    removed: list[str] = []
    if all:
        targets = [
            os.path.join(store.catalogs_dir(cache_dir), i["name"], store.CATALOG_FILE)
            for i in list_catalogs(cache_dir)
        ]
    else:
        path, _loc, _nm = locate(roots, location=location, name=name, db=db, cache_dir=cache_dir)
        targets = [path]
    for path in targets:
        # only a catalog is ever deleted: a file that is not one (another program's database
        # named by mistake) is refused before anything of it or beside it goes
        foreign = [
            p
            for p, app in (
                (path, schema.APPLICATION_ID),
                (store.sidecar(path, store.PREVIEWS_FILE), schema.PREVIEWS_APPLICATION_ID),
            )
            if store.file_application_id(p) not in (None, app)
        ]
        if foreign:
            if all:
                continue
            raise store.not_a_catalog()
        lock = store.sidecar(path, store.LOCK_FILE)
        if os.path.exists(lock):
            store.WriterLock(lock).acquire().release()  # busy while a writer holds it
        removed += store.remove_files(path)
        folder = os.path.dirname(path)
        if os.path.basename(path) == store.CATALOG_FILE:
            try:
                os.rmdir(folder)
            except OSError:
                pass
    return removed


__all__ = [
    "LOCATIONS",
    "Catalog",
    "cache_dir",
    "catalog_name",
    "clear",
    "find_catalog",
    "list_catalogs",
    "locate",
    "open",
]
