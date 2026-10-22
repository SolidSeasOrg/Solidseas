"""The one way reference resolution touches the filesystem.

Every filesystem call made by :mod:`solidseas.resolve` goes through a
:class:`Gateway`; a test reads the package's source and fails if another module
makes one. The gateway applies the rules of ``docs/API.md`` C2:

* **Inside a root** every lookup is answered from the root's folder index,
  built here with the shared walker (:class:`solidseas.walk.Walk`), which never
  follows a link, junction or mount point. A root is configuration, so the
  root folder itself may be a junction or a share (C6).
* **Outside every root** only a point lookup of one known path is made, never
  a search, and only when the caller allows it (the library and the CLI do;
  the REST service does not). The anchor is classified from the text first,
  and only a local fixed or removable drive (Windows ``GetDriveTypeW`` 3 or 2)
  is touched, or the anchor of a path map's target, which is configuration.
  A UNC path or a mapped network drive is never ``stat``'d, opened or passed
  to ``realpath``: on Windows that connects over SMB and sends the user's
  credentials to whatever host the path names. On Linux and macOS an absolute
  host path is a local path; stored Windows paths never reach this module
  without a path map.
* A point lookup reads the entry with ``lstat`` and decides it with the
  walker's own rules (:func:`solidseas.walk.classify`): a link is not
  followed, and a cloud placeholder is found but never opened. The folders on
  the way are read the same way first, from the anchor down, each only after
  the ones above it passed (:meth:`Gateway._way`), so a link, junction or
  cloud placeholder folder earlier on the path refuses the lookup before
  anything goes through it: the operating system would otherwise follow a
  junction there, or a symbolic link to a share, as for any local path. A
  path map's target is configuration (C6), so only the folders below it are
  read this way.
* **Identity reads** open a document read-only, ``within`` its root (or, outside
  the roots, within its own folder), so no link below that folder is crossed
  and, on Windows, a placeholder is never recalled. Only paths this gateway
  found (in an index it built, or by a point lookup) are opened. Reads are
  capped in number and by the caller's deadline. The rules ask for a whole
  batch at once (:meth:`Gateway.read_identities`); with an ``identity_reader``
  the batch that passed these checks goes to it in one call, which is how the
  REST service reads identities in a worker process (``docs/API.md`` C10).

:attr:`Gateway.calls` records every request, including the ones refused, so
tests can prove that a planted path reached the gateway and was refused there.
"""

import os
import stat
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .. import walk as walk_mod
from ..formats.solidworks import open_document
from ..model import error_code
from ..roots import Root
from .identity import Identity, own_identity
from .index import FolderIndex
from .names import HOST_WINDOWS, HostPath, fold, host_split

DRIVE_REMOVABLE, DRIVE_FIXED, DRIVE_REMOTE, DRIVE_NO_ROOT_DIR = 2, 3, 4, 1
WALK_MAX_DEPTH = 64
_SEP = "\\" if HOST_WINDOWS else "/"

# The calls the gateway makes, behind module attributes so tests can watch or refuse them.
_lstat: Callable = os.lstat
_open_document: Callable = open_document
_Walk: Callable = walk_mod.Walk
_abspath: Callable[[str], str] = os.path.abspath


def _no_drive_type(root: str) -> int:
    return 0


if sys.platform == "win32":
    import ctypes

    _GetDriveTypeW = ctypes.WinDLL("kernel32", use_last_error=True).GetDriveTypeW
    _GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    _GetDriveTypeW.restype = ctypes.c_uint

    def _windows_drive_type(root: str) -> int:
        return int(_GetDriveTypeW(root))

    _drive_type: Callable[[str], int] = _windows_drive_type
else:  # pragma: no cover - Linux and macOS have no drive letters
    _drive_type = _no_drive_type


@dataclass(frozen=True)
class PointHit:
    """A document found by a point lookup outside every root."""

    host: HostPath
    path: str
    name: str
    size: int | None
    mtime_ns: int | None
    placeholder: bool


class _Probe:
    """An ``lstat`` result dressed as a directory entry, for :func:`walk.classify`."""

    def __init__(self, name: str, st) -> None:
        self.name = name
        self._st = st

    def stat(self, follow_symlinks: bool = True):
        return self._st

    def is_symlink(self) -> bool:
        return stat.S_ISLNK(self._st.st_mode)

    def is_junction(self) -> bool:
        return False


class Gateway:
    """Filesystem access for one resolution call (see the module notes).

    ``allow_outside_roots`` permits point lookups outside every root.
    ``max_identity_reads`` caps the documents opened and ``deadline`` (a
    ``time.monotonic()`` value) stops opening more after it passes.
    ``identity_reader``, when given, reads a batch of ``(path, within)`` pairs that
    passed the gateway's checks and returns one :class:`Identity` each, in order;
    without it the gateway opens them itself.
    """

    def __init__(
        self,
        *,
        allow_outside_roots: bool = True,
        max_identity_reads: int = 5_000,
        deadline: float | None = None,
        identity_reader: Callable[[list[tuple[str, str]]], Sequence[Identity]] | None = None,
    ) -> None:
        self.allow_outside_roots = allow_outside_roots
        self.max_identity_reads = max_identity_reads
        self.deadline = deadline
        self.identity_reader = identity_reader
        self.calls: list[tuple[str, str, str]] = []
        self.identity_reads = 0
        self._within: set[str] = set()  # index roots: folders identity reads may open below
        self._found: set[str] = set()  # fold(path) of files point lookups found
        self._drive_types: dict[str, int] = {}
        self._folders: dict[str, str | None] = {}  # fold(folder) -> why a lookup stops there, or None

    # ------------------------------------------------------------------ text only
    def document_folder(self, path: str) -> HostPath:
        """The folder of a document's path on this machine (text only)."""
        return host_split(os.path.dirname(_abspath(path)))

    def anchor_class(self, host: HostPath) -> str:
        """``local``, ``unc``, ``network_drive``, ``absent_drive``, ``device_path``,
        ``other_drive`` or ``relative``, decided before any filesystem call.
        ``GetDriveTypeW`` reads the drive letter's mapping and connects nowhere. On
        Linux and macOS a path on a network file system's mount is ``network_drive``, from the
        kernel's mount table (:mod:`solidseas.netfs`), which asks nothing of the share."""
        if not HOST_WINDOWS:
            if host.anchor != "/":
                return "relative"
            from .. import netfs

            return "network_drive" if netfs.is_network(host.join()) else "local"
        a = host.anchor
        if a.startswith(("\\\\?", "\\\\.")):
            return "device_path"
        if a.startswith("\\\\"):
            return "unc"
        if len(a) == 2 and a[1] == ":":
            letter = a.upper()
            kind = self._drive_types.get(letter)
            if kind is None:
                kind = self._drive_types[letter] = _drive_type(letter + "\\")
            if kind in (DRIVE_FIXED, DRIVE_REMOVABLE):
                return "local"
            if kind == DRIVE_REMOTE:
                return "network_drive"
            if kind == DRIVE_NO_ROOT_DIR:
                return "absent_drive"
            return "other_drive"
        return "relative"

    # ------------------------------------------------------------------ roots
    def build_index(self, root: Root, *, max_examined: int, deadline: float | None) -> FolderIndex:
        """Walk ``root`` and index its documents. Raises ``FileNotFoundError``,
        ``NotADirectoryError`` or ``PermissionError`` for the root itself only."""
        self.calls.append(("walk", root.path, "started"))
        walk = _Walk(
            root.path,
            recursive=root.recursive,
            max_depth=WALK_MAX_DEPTH,
            max_examined=max(1, max_examined),
            deadline=deadline,
        )
        index = FolderIndex(root, host_split(root.path))
        for e in walk:
            if e.kind == "folder" and e.reason is None:
                index.add_folder(e.rel, e.name)
            elif e.kind == "file":
                index.add_file(e.rel, e.name, e.size, e.mtime_ns, False)
            elif e.kind == "placeholder" and not e.is_dir:
                index.add_file(e.rel, e.name, e.size, e.mtime_ns, True)
            elif e.kind == "error" and e.is_dir:
                index.unreadable += 1
        stats = walk.stats
        index.examined = stats.entries
        index.partial = stats.truncated or ("max_depth" if stats.depth_limited else None)
        self.adopt(index)
        return index

    def adopt(self, index: FolderIndex) -> None:
        """Allow identity reads below ``index``'s root (an index built earlier and cached)."""
        self._within.add(fold(index.host.join()))

    # ------------------------------------------------------------------ outside the roots
    def point_lookup(
        self, host: HostPath, *, configured: HostPath | None = None, trusted: int = 0
    ) -> PointHit | str:
        """Look up one known file outside every root. Returns a :class:`PointHit`, or why
        there is none: ``absent``, ``not_a_document`` (a folder, link, lock file or
        device), ``link_on_path`` or ``placeholder_on_path`` (a folder on the way is a
        link, junction or other name surrogate, or a cloud placeholder: :meth:`_way`),
        ``outside_roots`` (lookups outside the roots are not allowed), or the refused
        anchor class (``unc``, ``network_drive``, ``device_path``, ``other_drive``,
        ``relative``). ``configured`` is a path map's target: its anchor is configuration
        and may be any class but a device path, and its own folders are not read on the
        way. ``trusted`` is how many folders below the anchor the caller vouches for (the
        document's own folder, which the caller opened), not read on the way either."""
        path = host.join()
        cls = self.anchor_class(host)
        mapped = configured is not None and fold(configured.anchor) == fold(host.anchor)
        if cls == "absent_drive":
            self.calls.append(("point", path, "absent_drive"))
            return "absent"
        if cls != "local" and not (mapped and cls != "device_path"):
            self.calls.append(("point", path, f"refused:{cls}"))
            return cls
        if not self.allow_outside_roots:
            self.calls.append(("point", path, "refused:outside_roots"))
            return "outside_roots"
        own = trusted
        if mapped and configured is not None:
            n = len(configured.parts)
            if [fold(p) for p in host.parts[:n]] == [fold(p) for p in configured.parts]:
                own = max(own, n)
        stop = self._way(host, own)
        if stop is not None:
            self.calls.append(("point", path, stop))
            return stop.removeprefix("refused:")
        try:
            st = _lstat(path)
        except (OSError, ValueError):
            self.calls.append(("point", path, "absent"))
            return "absent"
        e = walk_mod.classify(_Probe(host.parts[-1], st), os.path.dirname(path), "", 1)
        if e.kind not in ("file", "placeholder") or e.is_dir:
            self.calls.append(("point", path, f"not_a_document:{e.kind}"))
            return "not_a_document"
        self.calls.append(("point", path, e.kind))
        self._found.add(fold(path))
        return PointHit(host, path, host.parts[-1], e.size, e.mtime_ns, e.kind == "placeholder")

    def _way(self, host: HostPath, own: int) -> str | None:
        """Why a lookup of ``host`` stops on its way, or None when the way is clear. The
        folders from the anchor down, past the first ``own`` (the caller's), are read with
        ``lstat`` and decided by :func:`solidseas.walk.classify`, each only after the ones
        above it passed, so nothing goes through a link on the way: ``absent`` when one is
        not there or is not a folder, ``refused:link_on_path`` when one is a link, junction
        or other name surrogate, and ``refused:placeholder_on_path`` when one is a cloud
        placeholder folder, which the walker never enters either. A folder's answer is
        kept for the gateway's later lookups."""
        for k in range(own, len(host.parts) - 1):
            folder = HostPath(host.anchor, host.parts[: k + 1]).join()
            key = fold(folder) if HOST_WINDOWS else folder
            if key not in self._folders:
                stop: str | None = None
                try:
                    st = _lstat(folder)
                except (OSError, ValueError):
                    stop = "absent"
                else:
                    e = walk_mod.classify(_Probe(host.parts[k], st), os.path.dirname(folder), "", 1)
                    if e.kind == "link":
                        stop = "refused:link_on_path"
                    elif e.kind == "placeholder":
                        stop = "refused:placeholder_on_path"
                    elif e.kind != "folder":
                        stop = "absent"
                self._folders[key] = stop
            if self._folders[key] is not None:
                return self._folders[key]
        return None

    # ------------------------------------------------------------------ identity
    def read_identity(self, path: str, *, within: str, placeholder: bool) -> Identity:
        """The creation time the document at ``path`` stores about itself. ``within`` is
        the root it was indexed under, or its own folder for a point lookup."""
        return self.read_identities([(path, within, placeholder)])[0]

    def _refusal(self, path: str, within: str, placeholder: bool) -> Identity | None:
        """Why ``path`` is not read (as the identity to report), or None when it may be."""
        key = fold(path)
        if placeholder:
            self.calls.append(("identity", path, "placeholder_not_read"))
            return Identity(None, placeholder=True)
        folder = fold(within)
        inside = folder in self._within and key.startswith(folder.rstrip("\\/") + _SEP)
        if not inside and key not in self._found:
            self.calls.append(("identity", path, "refused:not_found_by_gateway"))
            return Identity(None, error="path_refused")
        if self.identity_reads >= self.max_identity_reads or (
            self.deadline is not None and time.monotonic() >= self.deadline
        ):
            self.calls.append(("identity", path, "skipped"))
            return Identity(None, skipped=True)
        self.identity_reads += 1
        self.calls.append(("identity", path, "read"))
        return None

    def read_identities(self, requests: Sequence[tuple[str, str, bool]]) -> list[Identity]:
        """The identity of each ``(path, within, placeholder)`` request, in order. Each one
        is checked as :meth:`read_identity` describes; the ones that pass are read
        here, one at a time, or by ``identity_reader`` in one batch."""
        out: list[Identity | None] = []
        todo: list[int] = []
        for path, within, placeholder in requests:
            refused = self._refusal(path, within, placeholder)
            if refused is None:
                todo.append(len(out))
            out.append(refused)
        if todo and self.identity_reader is not None:
            got = list(self.identity_reader([(requests[i][0], requests[i][1]) for i in todo]))
            if len(got) != len(todo):
                got = [Identity(None, error="internal")] * len(todo)
            for i, ident in zip(todo, got, strict=True):
                out[i] = ident
        else:
            for i in todo:
                path, within, _placeholder = requests[i]
                try:
                    with _open_document(path, hold_open=True, within=within) as doc:
                        out[i] = own_identity(doc)
                except Exception as exc:  # one unreadable candidate never stops the resolution
                    out[i] = Identity(None, error=error_code(exc))
        return out  # type: ignore[return-value]


def within_of(host: HostPath) -> str:
    """The folder a point-lookup hit is opened within: its own."""
    return HostPath(host.anchor, host.parts[:-1]).join()


__all__ = ["Gateway", "PointHit", "within_of"]
