"""Where a catalog lives, its connections and its writer lock.

**Location.** :func:`cache_dir` is ``SOLIDSEAS_CACHE_DIR`` when that is set;
else ``%LOCALAPPDATA%\\SolidSeas`` on Windows (the base the service's token
file uses, which Windows does not roam) and ``$XDG_CACHE_HOME/solidseas``
(``~/.cache/solidseas``) elsewhere. A catalog named ``NAME`` is the folder
``<cache_dir>/catalogs/NAME``. The in-project location
(``<project root>/.solidseas``) is used only when a caller asks for it by
name, and never on a network location: SQLite's write-ahead log needs memory
shared on one machine, and its locks are unreliable over SMB and NFS. Folders
are made owner-only on Linux and macOS (0700, without following a link), as
the token file's folder is; on Windows the profile's own access list applies.

**Connections.** The writer holds the only read-write connection, set to
``journal_mode=WAL``, ``synchronous=NORMAL``, ``foreign_keys=ON``, a 5 s busy
timeout and a 64 MiB journal limit. Readers open the file with ``mode=ro`` and
``query_only=1``; in WAL mode they never block the writer, and each read
transaction sees one consistent snapshot.

**One writer.** ``catalog.lock`` beside the database is locked for the life of
the write connection (``msvcrt.locking`` on Windows, ``fcntl.flock`` elsewhere):
a second writer gets ``busy`` at once, and the operating system releases the
lock when a writer dies. Every write transaction is also ``BEGIN IMMEDIATE``.

**Files that are not what they seem.** A database that is not a catalog is
refused from its header before anything is written (:func:`file_application_id`).
The writer refuses a database, previews file, journal or lock that is a link or
not a plain file, wherever the catalog lives, so a link planted in a project's
``.solidseas`` folder is never written through. A catalog SQLite reports as
damaged (``SQLITE_CORRUPT`` or ``SQLITE_NOTADB``) is ``catalog_incompatible``
with rule ``damaged``, and one it cannot write is ``permission_denied``
(:func:`translate`).

``import solidseas.catalog`` works without the ``sqlite3`` module; opening a
catalog then raises ``not_implemented`` with a message that says why.
"""

import hashlib
import os
import pathlib
import stat
import sys

from ..errors import (
    BusyError,
    CatalogIncompatibleError,
    InvalidArgumentError,
    NotInCatalogError,
    PathRefusedError,
    SolidSeasError,
)
from ..resolve.names import fold
from . import schema

try:
    import sqlite3
except ImportError:  # pragma: no cover - a Python built without SQLite
    sqlite3 = None  # type: ignore[assignment]

CATALOG_FILE = "catalog.sqlite"
PREVIEWS_FILE = "previews.sqlite"
LOCK_FILE = "catalog.lock"
PROJECT_FOLDER = ".solidseas"
NAME_PATTERN = "[a-z0-9_-]{1,32}"
BUSY_TIMEOUT_MS = 5000
JOURNAL_LIMIT = 64 << 20
_SOLIDWORKS_EXTENSIONS = (
    ".sldprt",
    ".sldasm",
    ".slddrw",
    ".prtdot",
    ".asmdot",
    ".drwdot",
    ".sldlfp",
    ".sldblk",
)


class NotImplementedCatalogError(SolidSeasError, NotImplementedError):
    code = "not_implemented"


def need_sqlite() -> None:
    if sqlite3 is None:
        raise NotImplementedCatalogError(
            "the catalog needs Python's sqlite3 module, which this Python was built without"
        )


def cache_dir() -> str:
    """The folder SolidSeas keeps its caches in (see the module notes). Nothing is made."""
    env = os.environ.get("SOLIDSEAS_CACHE_DIR")
    if env:
        return os.path.abspath(env)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(base, "SolidSeas")
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "solidseas")


def catalogs_dir(base: str | None = None) -> str:
    return os.path.join(base or cache_dir(), "catalogs")


def default_name(root_path: str) -> str:
    """``folder-`` and the first 16 hex digits of the SHA-256 of the folder's folded path:
    one catalog per project folder."""
    digest = hashlib.sha256(fold(os.path.normpath(root_path)).encode("utf-8", "surrogatepass")).hexdigest()
    return "folder-" + digest[:16]


def check_name(name: str) -> str:
    import re

    if not isinstance(name, str) or not re.fullmatch(NAME_PATTERN, name):
        raise InvalidArgumentError(f"a catalog name matches {NAME_PATTERN}", detail={"parameter": "catalog"})
    return name


def is_network(path: str) -> bool:
    """Whether ``path`` is on a UNC share or a mapped network drive (Windows,
    ``GetDriveTypeW`` 4), from its text and the drive letter's mapping alone, or on a
    network file system's mount (Linux and macOS, :func:`solidseas.netfs.is_network`,
    from its text and the kernel's mount table)."""
    from ..resolve import gateway

    text = os.fspath(path).replace("/", "\\")
    if os.name != "nt":
        from .. import netfs

        return netfs.is_network(os.fspath(path))
    if text.startswith("\\\\"):
        return True
    drive = os.path.splitdrive(text)[0]
    if len(drive) == 2 and drive[1] == ":":
        return gateway._drive_type(drive.upper() + "\\") == gateway.DRIVE_REMOTE
    return False


def _is_link(path: str) -> bool:
    try:
        if os.path.islink(path):
            return True
        isjunction = getattr(os.path, "isjunction", None)
        return bool(isjunction and isjunction(path))
    except OSError:
        return False


def _open_to_others(path: str) -> str | None:
    """The first folder from ``path`` up that lets another account replace what is in
    it: writable by everyone without the sticky bit (``/tmp`` has it), or, for ``path``
    itself, owned by another account. None on Windows, whose folders are guarded by
    their access lists, and when every folder is safe."""
    if os.name == "nt":
        return None
    me = os.getuid()
    p = path
    while True:
        try:
            st = os.stat(p)
        except OSError:
            return None
        if p == path and st.st_uid != me:
            return p
        if st.st_mode & stat.S_IWOTH and not st.st_mode & stat.S_ISVTX:
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


def make_private_dir(path: str) -> None:
    """Make ``path`` and its parents; on Linux and macOS each new folder is 0700. A
    folder that is a link is refused, and so is one another account could swap for a
    link: a folder of another account's, or one inside a folder everyone may write to
    without the sticky bit (:func:`_open_to_others`)."""
    path = os.path.abspath(path)
    missing = []
    p = path
    while not os.path.isdir(p):
        missing.append(p)
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    for folder in reversed(missing):
        try:
            os.mkdir(folder, 0o700)
        except FileExistsError:
            pass
    if _is_link(path):
        raise PathRefusedError(
            "the catalog's folder is a link, which is never written through", detail={"rule": "link"}
        )
    if _open_to_others(path) is not None:
        raise PathRefusedError(
            "the catalog's folder is not private: another account owns it, or may replace it from a "
            "folder everyone can write to",
            detail={"rule": "not_private"},
        )


def check_db_path(path: str) -> str:
    """The database file a caller named (``db=``): its folder must exist, and neither the
    file nor its folder may be a link or carry a SOLIDWORKS extension."""
    full = os.path.abspath(os.fspath(path))
    if full.replace("/", "\\").startswith(("\\\\?\\", "\\\\.\\")):
        raise PathRefusedError(
            "device and long-path prefixes are not accepted", detail={"rule": "device_path"}
        )
    if is_network(full):  # decided from the text and the drive's type: a share is never touched
        raise PathRefusedError(
            "a catalog is never kept on a network location", detail={"rule": "network_location"}
        )
    if os.path.splitext(full)[1].lower() in _SOLIDWORKS_EXTENSIONS:
        raise PathRefusedError(
            "a catalog is never written to a SOLIDWORKS file", detail={"rule": "solidworks_file"}
        )
    folder = os.path.dirname(full)
    if not os.path.isdir(folder):
        raise FileNotFoundError(2, "the catalog's folder does not exist", folder)
    if _is_link(full) or _is_link(folder):
        raise PathRefusedError("the catalog's file or folder is a link", detail={"rule": "link"})
    if os.path.lexists(full) and not stat.S_ISREG(os.lstat(full).st_mode):
        raise PathRefusedError("the catalog's path is not a file", detail={"rule": "not_regular_file"})
    return full


def _link_refused() -> PathRefusedError:
    return PathRefusedError("the catalog's file or folder is a link", detail={"rule": "link"})


def check_catalog_files(db_path: str) -> None:
    """Refuse a catalog whose database, previews, their journals or lock is a link or not
    a plain file: the writer would write through it (a link planted in a project's
    ``.solidseas`` folder could point anywhere)."""
    previews = sidecar(db_path, PREVIEWS_FILE)
    names = [base + s for base in (db_path, previews) for s in ("", "-wal", "-shm", "-journal")]
    names.append(sidecar(db_path, LOCK_FILE))
    for p in names:
        if _is_link(p):
            raise _link_refused()
        try:
            st = os.lstat(p)
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(st.st_mode):
            raise PathRefusedError("the catalog's path is not a file", detail={"rule": "not_regular_file"})


def sidecar(db_path: str, name: str) -> str:
    """A file beside the database: previews and the lock. For a database named by the
    caller, ``<db>.previews.sqlite`` and ``<db>.lock``."""
    folder, base = os.path.split(db_path)
    if base == CATALOG_FILE:
        return os.path.join(folder, name)
    return db_path + {PREVIEWS_FILE: ".previews.sqlite", LOCK_FILE: ".lock"}[name]


# --------------------------------------------------------------------------- the lock
class WriterLock:
    """An exclusive, non-blocking lock on ``path`` held until :meth:`release`."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._fd: int | None = None

    def acquire(self) -> "WriterLock":
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        if _is_link(self.path):
            raise _link_refused()
        fd = os.open(self.path, flags, 0o600)
        try:
            # Windows has no O_NOFOLLOW: the file opened must be the path's own, not a link's target
            st, here = os.fstat(fd), os.lstat(self.path)
            if (st.st_dev, st.st_ino) != (here.st_dev, here.st_ino) or not stat.S_ISREG(here.st_mode):
                raise _link_refused()
        except BaseException:
            os.close(fd)
            raise
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise BusyError(
                "another process is updating this catalog", detail={"rule": "catalog_locked"}
            ) from None
        self._fd = fd
        return self

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)

    @property
    def held(self) -> bool:
        return self._fd is not None


def lock_is_held(path: str) -> bool:
    """Whether some process holds ``path`` locked now (tried and released at once)."""
    if not os.path.exists(path):
        return False
    try:
        WriterLock(path).acquire().release()
    except BusyError:
        return True
    except OSError:
        return False
    return False


def writer_alive(path: str) -> bool | None:
    """Whether a writer holds the lock file ``path`` now: tried on a read-only handle and
    released at once, so a reader never makes or changes the file. None when that cannot
    be told (the file cannot be opened)."""
    if not os.path.lexists(path):
        return False
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return None
    try:
        if sys.platform == "win32":
            import msvcrt

            try:
                msvcrt.locking(fd, msvcrt.LK_NBRLCK, 1)
            except OSError:
                return True
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        return None
    finally:
        os.close(fd)


# --------------------------------------------------------------------------- connections
def fts5_available() -> bool:
    need_sqlite()
    try:
        con = sqlite3.connect(":memory:")
        try:
            con.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        finally:
            con.close()
        return True
    except sqlite3.Error:
        return False


def _uri(path: str, mode: str) -> str:
    """A SQLite URI for a local file (percent-encoded, so no name can add a parameter)."""
    return pathlib.Path(os.path.abspath(path)).as_uri() + f"?mode={mode}"


def not_a_catalog() -> CatalogIncompatibleError:
    return CatalogIncompatibleError(
        "the database is not a SolidSeas catalog", detail={"rule": "not_a_catalog"}
    )


def damaged() -> CatalogIncompatibleError:
    return CatalogIncompatibleError(
        "the catalog is damaged: clear it and index the folder again", detail={"rule": "damaged"}
    )


_SQLITE_READONLY = 8
_SQLITE_CORRUPT = 11
_SQLITE_NOTADB = 26


def translate(exc: BaseException) -> BaseException | None:
    """What a SQLite error on a catalog means to its caller: ``damaged`` (a corrupt
    database, or a file that is no longer a database), ``permission_denied`` (a file that
    cannot be written), else None (the error stands)."""
    if sqlite3 is None or not isinstance(exc, sqlite3.DatabaseError):
        return None
    code = getattr(exc, "sqlite_errorcode", None)
    if code is not None:
        primary = code & 0xFF
        if primary in (_SQLITE_CORRUPT, _SQLITE_NOTADB):
            return damaged()
        if primary == _SQLITE_READONLY:
            return PermissionError(13, "the catalog's files cannot be written")
        return None
    text = str(exc).lower()
    if "malformed" in text or "not a database" in text:
        return damaged()
    if "readonly database" in text:
        return PermissionError(13, "the catalog's files cannot be written")
    return None


def file_application_id(path: str) -> int | None:
    """The application id in the header of the SQLite file at ``path``, read from the file
    itself, with no connection (so nothing is ever written to a database that is not
    ours): None for an empty or missing file. A file that is not SQLite is refused."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(100)
    except FileNotFoundError:
        return None
    if not head:
        return None
    if len(head) < 100 or head[:16] != b"SQLite format 3\x00":
        raise not_a_catalog()
    return int.from_bytes(head[68:72], "big")


def _check_version(con, *, writing: bool, min_reader: int | None) -> int:
    user_version = con.execute("PRAGMA user_version").fetchone()[0]
    if user_version > schema.SCHEMA_VERSION:
        if writing or (min_reader is not None and min_reader > schema.SCHEMA_VERSION):
            raise CatalogIncompatibleError(
                "a newer SolidSeas wrote this catalog", detail={"rule": "too_new", "value": user_version}
            )
    return user_version


def check_schema(con, database: str = "main") -> None:
    """Refuse a database holding a view or a trigger. SolidSeas never makes one in a
    catalog or its previews, and one in a catalog someone else made (in a shared
    project's ``.solidseas`` folder, say) could make a query hang or answer wrongly.
    Run before any query reads a table; the connection also has ``trusted_schema``
    off, so nothing in a database's schema runs a function that is not harmless."""
    rows = con.execute(
        f"SELECT type FROM {database}.sqlite_master WHERE type IN ('view', 'trigger')"
    ).fetchall()
    if rows:
        kinds = " and ".join(f"{k}s" for k in sorted({r[0] for r in rows}))
        raise CatalogIncompatibleError(
            f"the catalog holds {kinds}, which SolidSeas never makes: it is not opened",
            detail={"rule": "unexpected_schema", "value": len(rows)},
        )


def connect_writer(path: str):
    """The read-write connection of the writer (autocommit; transactions are explicit).
    The file is checked to be a catalog, or new, before SQLite opens it."""
    need_sqlite()
    app = file_application_id(path)
    if app not in (None, schema.APPLICATION_ID):
        raise not_a_catalog()
    con = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    try:
        con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        con.execute("PRAGMA trusted_schema=OFF")
        check_schema(con)
        if app is None:  # new: marked as a catalog before anything else is written
            con.execute(f"PRAGMA application_id={schema.APPLICATION_ID}")
        _check_version(con, writing=True, min_reader=None)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA foreign_keys=ON")
        con.execute(f"PRAGMA journal_size_limit={JOURNAL_LIMIT}")
    except BaseException:
        con.close()
        raise
    return con


def _being_made() -> NotInCatalogError:
    return NotInCatalogError("the catalog is being made: its first scan has not written its tables yet")


def connect_reader(path: str):
    """A read-only connection (``mode=ro``, ``query_only``). The file must exist. A
    catalog a writer is making right now, an empty file or one marked as a catalog
    whose tables are not there yet, is ``not_in_catalog``: nothing is indexed yet."""
    need_sqlite()
    if not os.path.isfile(path):
        raise FileNotFoundError(2, "no catalog there", path)
    app = file_application_id(path)
    if app is None:
        raise _being_made()
    if app != schema.APPLICATION_ID:
        raise not_a_catalog()
    con = sqlite3.connect(_uri(path, "ro"), uri=True, isolation_level=None, check_same_thread=False)
    try:
        con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        con.execute("PRAGMA trusted_schema=OFF")
        con.execute("PRAGMA query_only=1")
        check_schema(con)
        con.execute("PRAGMA foreign_keys=ON")
        min_reader = None
        try:
            row = con.execute("SELECT value FROM meta WHERE key = 'min_reader_schema'").fetchone()
            min_reader = int(row[0]) if row else None
        except (sqlite3.Error, ValueError):
            min_reader = None
        if _check_version(con, writing=False, min_reader=min_reader) == 0:
            raise _being_made()
    except sqlite3.DatabaseError as exc:  # its header says it is a catalog: it is a damaged one
        con.close()
        raise translate(exc) or damaged() from None
    except BaseException:
        con.close()
        raise
    return con


def attach_previews(con, path: str, *, writing: bool) -> bool:
    """Attach the previews database as ``pv``; False when a reader finds none."""
    if writing:
        app = file_application_id(path)
        if app not in (None, schema.PREVIEWS_APPLICATION_ID):
            raise not_a_catalog()
        con.execute("ATTACH DATABASE ? AS pv", (path,))
        _checked_previews(con)
        if app is None:
            con.execute(f"PRAGMA pv.application_id={schema.PREVIEWS_APPLICATION_ID}")
        con.execute("PRAGMA pv.journal_mode=WAL")
        con.execute("PRAGMA pv.synchronous=NORMAL")
        if con.execute("SELECT count(*) FROM pv.sqlite_master").fetchone()[0] == 0:
            con.execute("BEGIN IMMEDIATE")
            con.execute(f"PRAGMA pv.user_version={schema.PREVIEWS_VERSION}")
            con.execute(
                schema.PREVIEW_TABLES.strip().rstrip(";").replace("TABLE previews", "TABLE pv.previews")
            )
            con.execute("COMMIT")
        return True
    try:
        if file_application_id(path) != schema.PREVIEWS_APPLICATION_ID:
            return False
    except CatalogIncompatibleError:
        return False
    con.execute("ATTACH DATABASE ? AS pv", (_uri(path, "ro"),))
    _checked_previews(con)
    return True


def _checked_previews(con) -> None:
    """:func:`check_schema` of the previews just attached; refused, they are detached."""
    try:
        check_schema(con, "pv")
    except BaseException:
        con.execute("DETACH DATABASE pv")
        raise


def remove_files(db_path: str) -> list[str]:
    """Delete a catalog's files (the database, its previews, their journals and the lock);
    returns the paths removed."""
    removed = []
    for base in (db_path, sidecar(db_path, PREVIEWS_FILE)):
        for suffix in ("", "-wal", "-shm", "-journal"):
            p = base + suffix
            if os.path.lexists(p):
                os.remove(p)
                removed.append(p)
    lock = sidecar(db_path, LOCK_FILE)
    if os.path.lexists(lock):
        os.remove(lock)
        removed.append(lock)
    return removed


__all__ = [
    "CATALOG_FILE",
    "LOCK_FILE",
    "PREVIEWS_FILE",
    "PROJECT_FOLDER",
    "WriterLock",
    "attach_previews",
    "check_schema",
    "cache_dir",
    "catalogs_dir",
    "check_catalog_files",
    "check_db_path",
    "check_name",
    "connect_reader",
    "connect_writer",
    "damaged",
    "default_name",
    "fts5_available",
    "is_network",
    "lock_is_held",
    "make_private_dir",
    "need_sqlite",
    "remove_files",
    "sidecar",
    "translate",
    "writer_alive",
]
