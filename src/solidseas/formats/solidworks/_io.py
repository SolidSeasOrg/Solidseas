"""Read-only, share-tolerant file access.

On Windows a document is opened with ``GENERIC_READ`` and
``FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE``, so another program
can still open it for writing, rename it or delete it while SolidSeas reads it.
Two things still fail while the handle is open: another program opening the
file with no sharing at all, and replacing the file by renaming another file
onto it. That is why :func:`~.container.open_container` reads the whole file
and closes the handle at once unless the caller asks to hold it open. Elsewhere
a read-only ``os.open`` is used. Nothing in this package ever opens a source
document for writing.

**Only regular files are read.** On Linux and macOS the file is opened with
``O_NONBLOCK``, so a FIFO named like a document cannot block the open waiting
for a writer, and ``fstat`` on the open descriptor must say it is a regular
file before ``O_NONBLOCK`` is cleared and anything is read. On Windows
``GetFileType`` must say it is a disk file, which refuses devices such as
``NUL`` and ``CON`` and named pipes. Anything else raises
:class:`~solidseas.errors.PathRefusedError` with ``detail["rule"]``
``"not_regular_file"``.

**Opening a file found inside a folder** (``within``, used by the folder
listing and batch) also refuses a link that appeared after the folder was
listed:

* On Linux and macOS the folder is opened (it may itself be a link: a root is
  configuration), then every component below it with ``O_NOFOLLOW`` through
  ``dir_fd``, so no symbolic link below the folder is ever followed.
* On Windows every folder between ``within`` and the file is first read with
  ``lstat``, one at a time from ``within`` down, and a link or junction among
  them is refused before the operating system could go through it (a symbolic
  link to a share would make it connect there). The file is then opened with
  ``FILE_FLAG_OPEN_NO_RECALL``, so opening never recalls a file whose data is
  elsewhere, and the open handle is checked: a cloud placeholder attribute raises
  :class:`~solidseas.errors.PlaceholderFileError` before any byte is read, and
  the handle's final path (``GetFinalPathNameByHandleW``) must equal the
  folder's final path joined with the rest, or a link or junction was crossed
  and :class:`~solidseas.errors.LinkRefusedError` is raised.

A path that is not below the folder at all raises ``PathRefusedError`` with the
rule ``"escapes_root"`` before anything is opened.

The handle is unbuffered (:class:`ReadOnlyFile`): a reader holding it open asks
the operating system for exactly the bytes it needs, so a folder listing that
reads a few streams of each file does not pull in the buffer-sized blocks
around every small read. ``read(n)`` still returns ``n`` bytes unless the file
ends first.

Errors, the same on every operating system:

* a missing file raises ``FileNotFoundError``;
* a folder raises ``IsADirectoryError``;
* access denied raises ``PermissionError`` (error code ``permission_denied``);
* only a Windows sharing or lock violation raises :class:`~.errors.LockedFileError`
  (error code ``locked``). POSIX has no mandatory share modes, so a
  ``PermissionError`` there is always a permissions problem, never a lock.
"""

import errno
import os
import stat
import sys
from typing import Any, BinaryIO

from ...errors import LinkRefusedError, PathRefusedError, PlaceholderFileError
from ...walk import reparse_link
from .errors import LockedFileError, SldFormatError

# A read() that fails with EACCES is a byte-range lock only on Windows (LockFileEx).
_EACCES_ON_READ_IS_A_LOCK = sys.platform == "win32"

# Attributes of a file whose data is not on this machine (see solidseas.walk).
_PLACEHOLDER_ATTRIBUTES = 0x1000 | 0x40000 | 0x400000  # OFFLINE, RECALL_ON_OPEN, RECALL_ON_DATA_ACCESS

# The POSIX open call, behind a module attribute so tests can refuse it on any OS.
_os_open = os.open


def lock_error(exc: OSError, what: str = "byte range locked by another process") -> LockedFileError | None:
    """The :class:`LockedFileError` an ``OSError`` from a read stands for, or None.

    A byte-range lock (LockFileEx) surfaces from ``read()`` on Windows as EACCES
    with no ``winerror``, or as a sharing or lock violation (32, 33).
    """
    if getattr(exc, "winerror", None) in (32, 33):
        return LockedFileError(exc.errno, what)
    if _EACCES_ON_READ_IS_A_LOCK and isinstance(exc, PermissionError):
        return LockedFileError(exc.errno, what)
    return None


class ReadOnlyFile:
    """An unbuffered, read-only file whose ``read(n)`` returns ``n`` bytes unless the
    file ends first (a raw read may legally return fewer). It offers what the
    readers and ``olefile`` use: ``read``, ``seek``, ``tell``, ``fileno``, ``close``
    and ``closed``."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            return self._raw.read()  # read to the end; FileIO loops until EOF itself
        first = self._raw.read(size)
        if not first or len(first) >= size:
            return first or b""
        parts, got = [first], len(first)
        while got < size:
            more = self._raw.read(size - got)
            if not more:
                break
            parts.append(more)
            got += len(more)
        return b"".join(parts)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._raw.seek(offset, whence)

    def tell(self) -> int:
        return self._raw.tell()

    def fileno(self) -> int:
        return self._raw.fileno()

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def close(self) -> None:
        self._raw.close()

    @property
    def closed(self) -> bool:
        return self._raw.closed

    def __enter__(self) -> "ReadOnlyFile":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


# --------------------------------------------------------------------------- shared checks
def not_regular_file(path: str) -> PathRefusedError:
    return PathRefusedError(
        f"{path}: not a regular file (a pipe, socket or device); not opened",
        detail={"rule": "not_regular_file"},
    )


def relative_parts(path: str, within: str) -> list[str]:
    """The components of ``path`` below the folder ``within``, from the text alone.

    Raises :class:`PathRefusedError` (rule ``escapes_root``) for a path that is not
    strictly below the folder; nothing on disk is touched."""
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(within))
    except ValueError:  # another drive on Windows
        rel = os.pardir
    parts = rel.split(os.sep)
    if os.path.isabs(rel) or any(p in ("", os.curdir, os.pardir) for p in parts):
        raise PathRefusedError(f"{path}: not inside {within}", detail={"rule": "escapes_root"})
    return parts


# --------------------------------------------------------------------------- Linux and macOS
_O_BINARY = getattr(os, "O_BINARY", 0)  # Windows only: lets the POSIX path run in tests there
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_LINK_ERRNOS = {errno.ELOOP, errno.ENOTDIR, errno.EMLINK}  # what O_NOFOLLOW on a link answers


def _regular_descriptor(fd: int, path: str) -> BinaryIO:
    """Wrap ``fd`` once ``fstat`` says it is a regular file; close it and raise otherwise."""
    try:
        st = os.fstat(fd)
        if stat.S_ISDIR(st.st_mode):
            raise IsADirectoryError(errno.EISDIR, "is a folder, not a file", path)
        if not stat.S_ISREG(st.st_mode):
            raise not_regular_file(path)
        if _O_NONBLOCK:
            os.set_blocking(fd, True)  # a regular file: reads behave as before
        raw = open(fd, "rb", buffering=0, closefd=True)
    except BaseException:
        os.close(fd)
        raise
    return ReadOnlyFile(raw)  # type: ignore[return-value]


def _open_readonly_posix(path: str) -> BinaryIO:
    """Open ``path`` for reading only (Linux, macOS), never blocking on a FIFO."""
    # FileNotFoundError and PermissionError propagate unchanged.
    fd = _os_open(path, os.O_RDONLY | _O_NONBLOCK | _O_CLOEXEC | _O_BINARY)
    return _regular_descriptor(fd, path)


def _refuse_if_link(exc: OSError, name: str, dir_fd: int, path: str) -> None:
    """Raise :class:`LinkRefusedError` when ``name`` in ``dir_fd`` is a symbolic link."""
    if exc.errno not in _LINK_ERRNOS:
        return
    try:
        st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except OSError:
        return
    if stat.S_ISLNK(st.st_mode):
        raise LinkRefusedError(
            f"{path}: reached through a symbolic link below the folder, which is never followed",
            detail={"rule": "link_in_path"},
        ) from exc


def _open_within_posix(path: str, within: str) -> BinaryIO:
    """Open ``path`` below ``within`` without following any link below ``within``."""
    parts = relative_parts(path, within)
    dir_flags = os.O_RDONLY | _O_DIRECTORY | _O_CLOEXEC
    fd = _os_open(within, dir_flags)  # the folder itself may be a link (a root is configuration)
    try:
        for name in parts[:-1]:
            try:
                sub = _os_open(name, dir_flags | _O_NOFOLLOW, dir_fd=fd)
            except OSError as exc:
                _refuse_if_link(exc, name, fd, path)
                raise type(exc)(exc.errno, exc.strerror, path) from None
            os.close(fd)
            fd = sub
        try:
            ffd = _os_open(parts[-1], os.O_RDONLY | _O_NOFOLLOW | _O_NONBLOCK | _O_CLOEXEC, dir_fd=fd)
        except OSError as exc:
            _refuse_if_link(exc, parts[-1], fd, path)
            raise type(exc)(exc.errno, exc.strerror, path) from None
    finally:
        os.close(fd)
    return _regular_descriptor(ffd, path)


# --------------------------------------------------------------------------- Windows
if sys.platform == "win32":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CreateFileW = _k32.CreateFileW
    _CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _CreateFileW.restype = wintypes.HANDLE
    _CloseHandle = _k32.CloseHandle
    _CloseHandle.argtypes = [wintypes.HANDLE]
    _GetFileType = _k32.GetFileType
    _GetFileType.argtypes = [wintypes.HANDLE]
    _GetFileType.restype = wintypes.DWORD
    _GetFinalPathNameByHandleW = _k32.GetFinalPathNameByHandleW
    _GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    _GetFinalPathNameByHandleW.restype = wintypes.DWORD
    _INVALID_HANDLE = wintypes.HANDLE(-1).value
    _GENERIC_READ = 0x80000000
    _FILE_READ_ATTRIBUTES = 0x80
    _SHARE_ALL = 0x1 | 0x2 | 0x4  # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
    _OPEN_EXISTING = 3
    _FILE_ATTRIBUTE_NORMAL = 0x80
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000  # needed to open a folder
    _FILE_FLAG_OPEN_NO_RECALL = 0x00100000  # leave data that is elsewhere where it is
    _FILE_TYPE_DISK = 1
    _VOLUME_NAME_NT = 0x2  # \Device\...: defined for every volume and share, letter or not

    def _long(path: str) -> str:
        p = os.path.abspath(path)
        if len(p) >= 248 and not p.startswith("\\\\?\\"):
            p = "\\\\?\\UNC\\" + p[2:] if p.startswith("\\\\") else "\\\\?\\" + p
        return p

    def _create(path: str, access: int, flags: int) -> int:
        handle = _CreateFileW(_long(path), access, _SHARE_ALL, None, _OPEN_EXISTING, flags, None)
        if handle is None or handle == _INVALID_HANDLE:
            err = ctypes.get_last_error()
            if err in (32, 33):  # sharing violation, lock violation
                raise LockedFileError(err, "file is locked by another process", path)
            if err in (2, 3):
                raise FileNotFoundError(errno.ENOENT, "file not found", path)
            if err == 5:
                # CreateFileW without backup semantics answers "access denied" for a folder.
                if not flags & _FILE_FLAG_BACKUP_SEMANTICS and os.path.isdir(_long(path)):
                    raise IsADirectoryError(errno.EISDIR, "is a folder, not a file", path)
                raise PermissionError(errno.EACCES, "access denied", path)
            raise OSError(err, ctypes.FormatError(err).strip(), path)
        return handle

    def _final_path(handle: int, path: str) -> str:
        size = 512
        while True:
            buf = ctypes.create_unicode_buffer(size)
            n = _GetFinalPathNameByHandleW(handle, buf, size, _VOLUME_NAME_NT)
            if n == 0:
                err = ctypes.get_last_error()
                raise OSError(err, ctypes.FormatError(err).strip(), path)
            if n < size:
                return buf.value
            size = n + 1

    def _folder_final_path(folder: str) -> str:
        handle = _create(folder, _FILE_READ_ATTRIBUTES, _FILE_FLAG_BACKUP_SEMANTICS)
        try:
            return _final_path(handle, folder)
        finally:
            _CloseHandle(handle)

    def _check_folders(path: str, within: str, folders: list[str]) -> None:
        """Refuse a link or junction among ``folders`` below ``within``, each read with
        ``lstat`` (which does not follow the last component) only after the ones above it
        passed, so no path handed to the operating system goes through a link."""
        cur = within
        for name in folders:
            cur = os.path.join(cur, name)
            st = os.lstat(cur)
            attrs = getattr(st, "st_file_attributes", 0)
            if reparse_link(attrs, getattr(st, "st_reparse_tag", 0)) is not None:
                raise LinkRefusedError(
                    f"{path}: reached through a link or junction below the folder, which is never followed",
                    detail={"rule": "link_in_path"},
                )
            if not stat.S_ISDIR(st.st_mode):
                raise FileNotFoundError(errno.ENOENT, "file not found", path)

    def _check_within(handle: int, fd: int, path: str, within: str, parts: list[str]) -> None:
        if os.fstat(fd).st_file_attributes & _PLACEHOLDER_ATTRIBUTES:
            raise PlaceholderFileError(f"{path}: a cloud placeholder whose data is not on this machine")
        expected = _folder_final_path(within).rstrip("\\") + "\\" + "\\".join(parts)
        if os.path.normcase(_final_path(handle, path)) != os.path.normcase(expected):
            raise LinkRefusedError(
                f"{path}: reached through a link or junction below the folder, which is never followed",
                detail={"rule": "link_in_path"},
            )

    def open_readonly(path: str, *, within: str | None = None) -> BinaryIO:
        """Open ``path`` for reading only, sharing read, write and delete access.

        With ``within``, ``path`` must lie below that folder and is opened without
        recalling a placeholder or crossing a link (see the module notes)."""
        parts = relative_parts(path, within) if within is not None else None
        if parts is not None:
            _check_folders(path, within, parts[:-1])
        flags = _FILE_ATTRIBUTE_NORMAL | (_FILE_FLAG_OPEN_NO_RECALL if within is not None else 0)
        handle = _create(path, _GENERIC_READ, flags)
        try:
            if _GetFileType(handle) != _FILE_TYPE_DISK:
                raise not_regular_file(path)
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | _O_BINARY)
        except BaseException:
            _CloseHandle(handle)
            raise
        try:
            if within is not None:
                _check_within(handle, fd, path, within, parts)
            raw = open(fd, "rb", buffering=0, closefd=True)
        except BaseException:
            os.close(fd)
            raise
        return ReadOnlyFile(raw)  # type: ignore[return-value]

else:  # pragma: no cover - exercised on Linux and macOS only

    def open_readonly(path: str, *, within: str | None = None) -> BinaryIO:
        """Open ``path`` for reading only, never blocking on a FIFO.

        With ``within``, ``path`` must lie below that folder and no symbolic link
        below the folder is followed (see the module notes)."""
        if within is None:
            return _open_readonly_posix(path)
        return _open_within_posix(path, within)


def check_folder_within(folder: str, within: str) -> None:
    """Refuse ``folder`` unless it is ``within`` itself or lies below it with no link,
    junction or symbolic link on the way, as :func:`open_readonly` checks a file.

    The REST service calls it before walking a folder it located from a request:
    :class:`~solidseas.errors.LinkRefusedError` (rule ``link_in_path``) when a link
    was crossed, :class:`~solidseas.errors.PathRefusedError` (``escapes_root``) for a
    folder outside ``within``. ``within`` itself may be a link (a root is
    configuration)."""
    if os.path.normcase(os.path.abspath(folder)) == os.path.normcase(os.path.abspath(within)):
        return
    parts = relative_parts(folder, within)
    if sys.platform == "win32":
        _check_folders(folder, within, parts)
        expected = _folder_final_path(within).rstrip("\\") + "\\" + "\\".join(parts)
        if os.path.normcase(_folder_final_path(folder)) != os.path.normcase(expected):
            raise LinkRefusedError(
                f"{folder}: reached through a link or junction below the folder, which is never followed",
                detail={"rule": "link_in_path"},
            )
        return
    dir_flags = os.O_RDONLY | _O_DIRECTORY | _O_CLOEXEC
    fd = _os_open(within, dir_flags)
    try:
        for name in parts:
            try:
                sub = _os_open(name, dir_flags | _O_NOFOLLOW, dir_fd=fd)
            except OSError as exc:
                _refuse_if_link(exc, name, fd, folder)
                raise type(exc)(exc.errno, exc.strerror, folder) from None
            os.close(fd)
            fd = sub
    finally:
        os.close(fd)


def pread(f: BinaryIO, offset: int, n: int) -> bytes:
    """Read exactly ``n`` bytes at ``offset`` or raise :class:`SldFormatError`."""
    try:
        f.seek(offset)
        data = f.read(n)
    except OSError as exc:
        locked = lock_error(exc)
        if locked is not None:
            raise locked from exc
        raise
    if len(data) != n:
        raise SldFormatError(f"unexpected end of data at offset {offset} (wanted {n} bytes, got {len(data)})")
    return data
