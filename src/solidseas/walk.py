"""The one folder walker: used by the folder listing (:func:`solidseas.listing.scan`),
the ``batch`` command and, later, the reference-resolution index.

It walks breadth first, one ``os.scandir`` per folder, with each folder's
entries sorted case-folded, and decides everything from
``DirEntry.stat(follow_symlinks=False)``. On Windows that answer comes with the
directory listing itself, with no extra call per entry, which matters on a file
share where every call is a network round trip. On Linux and macOS it costs one
``lstat`` per entry.

**Links are never followed.** Windows sets ``FILE_ATTRIBUTE_REPARSE_POINT`` on
anything that carries a reparse tag, and only some tags are links. An entry is
a link when it has the attribute and its tag is a junction (mount point), a
symbolic link, any other tag with the name-surrogate bit ``0x20000000`` (a WSL
symlink, for example), or 0 (a tag that was not reported fails closed). An
``is_symlink()`` or ``is_junction()`` entry is a link too. The link question is
decided before the folder question, because a junction also carries the
directory attribute. Other tags, such as a deduplicated file (``0x80000013``)
or a cloud folder (``0x9000701A``), are ordinary files and folders.

**Mount points are links too.** On Windows a volume mounted in a folder carries
the junction tag. On Linux and macOS an entry whose ``st_dev`` differs from the
root's is on another filesystem (a bind, network or FUSE mount), and is
reported as a link with reason ``mount_point`` and never entered, so the same
tree gives the same listing on every platform. (A Linux btrfs subvolume has a
device of its own and counts as a mount point.)

**Only regular files are files.** On Linux and macOS a FIFO, socket or device
named like a document is reported as skipped with reason ``not_regular_file``
and never opened: opening a FIFO waits for a writer, forever.

**Cloud placeholders are never read.** A file or folder with
``FILE_ATTRIBUTE_OFFLINE`` (``0x1000``), ``RECALL_ON_OPEN`` (``0x40000``) or
``RECALL_ON_DATA_ACCESS`` (``0x400000``) has data that is not on this machine;
opening it would start a download. Such an entry is reported as a placeholder
with its name and size, a placeholder folder is not entered, and the callers
never open a placeholder file.

**SOLIDWORKS lock files** (``~$<name>``, written while a document is open) are
reported as skipped and never read.

**Bounds.** ``max_depth`` folders deep, ``max_examined`` directory entries
examined and an optional deadline. When a bound stops the walk early,
:attr:`WalkStats.truncated` says which. Both are checked between entries: a
listing call that blocks (an unreachable share) runs past the deadline until
it returns. A folder that cannot be listed is reported as an error entry and
the walk goes on; only the root itself raises.

The root may itself be a junction or a symbolic link: a root is the caller's
configuration, not file content (``docs/API.md``, C6).
"""

import dataclasses
import os
import stat
import time
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000  # not in the stat module
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000  # not in the stat module
IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003  # a junction
IO_REPARSE_TAG_SYMLINK = 0xA000000C
NAME_SURROGATE = 0x20000000  # what IsReparseTagNameSurrogate tests

# Placeholder attributes, in the order their reason is reported.
_PLACEHOLDER = (
    (FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS, "recall_on_data_access"),
    (FILE_ATTRIBUTE_RECALL_ON_OPEN, "recall_on_open"),
    (FILE_ATTRIBUTE_OFFLINE, "offline"),
)

DEFAULT_MAX_DEPTH = 32
DEFAULT_MAX_EXAMINED = 1_000_000
LOCK_FILE_PREFIX = "~$"

# The listing call, behind a module attribute so tests can hand the walker fake entries.
_scandir: Callable[[str], Any] = os.scandir


@dataclass(frozen=True)
class WalkEntry:
    """One directory entry, classified from the directory listing alone.

    ``kind`` is one of:

    * ``"file"`` and ``"folder"``: ordinary entries;
    * ``"link"``: a symbolic link, junction, other name-surrogate reparse point or
      mount point, never followed (``reason`` is ``"junction"``, ``"symlink"``,
      ``"name_surrogate"``, ``"unreported_tag"`` or ``"mount_point"``);
    * ``"placeholder"``: a cloud file or folder whose data is not on this machine,
      never opened (``reason`` is ``"recall_on_data_access"``, ``"recall_on_open"``
      or ``"offline"``);
    * ``"skipped"``: a SOLIDWORKS lock file (``reason`` ``"lock_file"``), or a
      FIFO, socket or device (``"not_regular_file"``), never opened;
    * ``"error"``: an entry whose details, or a folder whose contents, could not
      be read (``error`` holds the exception).

    A ``"folder"`` that a depth limit kept the walk out of has ``reason``
    ``"max_depth"``.
    """

    path: str  # the root joined with the entry's relative path, in host form
    rel: str  # relative to the root, "/"-separated, in the on-disk spelling
    name: str
    depth: int  # 1 for an entry directly in the root
    kind: str
    is_dir: bool  # a folder, or a link or placeholder known to stand for one
    size: int | None  # files only
    mtime_ns: int | None
    reason: str | None = None
    error: BaseException | None = None
    # "<st_dev hex>:<st_ino hex>" when the listing gave both (Linux and macOS, where the
    # walker's lstat has them); None on Windows, whose directory listing carries neither.
    file_id: str | None = None


@dataclass
class WalkStats:
    """What a walk saw, counted as it goes."""

    folders: int = 0  # folders listed, the root included
    entries: int = 0  # directory entries examined
    files: int = 0
    links: int = 0
    placeholders: int = 0
    skipped: int = 0
    errors: int = 0  # entries and folders that could not be read
    depth_limited: int = 0  # folders not entered because of max_depth
    truncated: str | None = None  # "max_examined" or "deadline" when the walk stopped early

    def to_dict(self) -> dict[str, Any]:
        return {
            "folders": self.folders,
            "entries": self.entries,
            "files": self.files,
            "links": self.links,
            "placeholders": self.placeholders,
            "skipped": self.skipped,
            "errors": self.errors,
            "depth_limited": self.depth_limited,
            "truncated": self.truncated,
        }


def reparse_link(attrs: int, tag: int) -> str | None:
    """Why a Windows entry with these attributes and reparse tag is a link the walker never
    follows (``junction``, ``symlink``, ``unreported_tag`` or ``name_surrogate``), or None
    when it is not one (no reparse point, or a tag such as a deduplicated file's)."""
    if not attrs & FILE_ATTRIBUTE_REPARSE_POINT:
        return None
    if tag == IO_REPARSE_TAG_MOUNT_POINT:
        return "junction"
    if tag == IO_REPARSE_TAG_SYMLINK:
        return "symlink"
    if tag == 0:
        return "unreported_tag"
    if tag & NAME_SURROGATE:
        return "name_surrogate"
    return None


def classify(
    entry: Any, folder: str, rel_prefix: str, depth: int, *, root_dev: int | None = None
) -> WalkEntry:
    """A :class:`WalkEntry` for one ``os.DirEntry`` (or anything with ``name``,
    ``stat(follow_symlinks=False)``, ``is_symlink()`` and optionally ``is_junction()``).

    ``root_dev`` is the root's ``st_dev``: on Linux and macOS an entry on another
    device is a mount point. Windows listings carry no device, so it is not used
    there (a Windows mount point is a junction)."""
    name = entry.name
    path = os.path.join(folder, name)
    rel = f"{rel_prefix}/{name}" if rel_prefix else name
    try:
        st = entry.stat(follow_symlinks=False)
    except OSError as exc:  # the entry vanished, or its details are denied
        return WalkEntry(path, rel, name, depth, "error", False, None, None, type(exc).__name__, exc)
    windows = hasattr(st, "st_file_attributes")
    attrs = int(getattr(st, "st_file_attributes", 0) or 0)
    tag = int(getattr(st, "st_reparse_tag", 0) or 0)
    is_dir = bool(attrs & FILE_ATTRIBUTE_DIRECTORY) if windows else stat.S_ISDIR(st.st_mode)
    mtime_ns = getattr(st, "st_mtime_ns", None)

    link = reparse_link(attrs, tag)
    if link is None:
        try:
            if entry.is_symlink():
                link = "symlink"
            elif getattr(entry, "is_junction", None) is not None and entry.is_junction():
                link = "junction"  # DirEntry.is_junction is Python 3.12 and later
        except OSError:
            link = "unreported_tag"
    if link is None and not windows and root_dev is not None and getattr(st, "st_dev", root_dev) != root_dev:
        link = "mount_point"  # another filesystem: lstat already gave st_dev, no extra call
    if link is not None:
        return WalkEntry(path, rel, name, depth, "link", is_dir, None, mtime_ns, link)

    for bit, reason in _PLACEHOLDER:
        if attrs & bit:
            size = None if is_dir else st.st_size
            return WalkEntry(path, rel, name, depth, "placeholder", is_dir, size, mtime_ns, reason)
    if is_dir:
        return WalkEntry(path, rel, name, depth, "folder", True, None, mtime_ns)
    if not stat.S_ISREG(st.st_mode):  # a FIFO, socket or device: opening a FIFO blocks
        return WalkEntry(path, rel, name, depth, "skipped", False, None, mtime_ns, "not_regular_file")
    if name.startswith(LOCK_FILE_PREFIX):
        return WalkEntry(path, rel, name, depth, "skipped", False, st.st_size, mtime_ns, "lock_file")
    ino = getattr(st, "st_ino", 0) or 0
    file_id = f"{getattr(st, 'st_dev', 0) or 0:x}:{ino:x}" if ino and not windows else None
    return WalkEntry(path, rel, name, depth, "file", False, st.st_size, mtime_ns, file_id=file_id)


def _sort_key(entry: Any) -> tuple[str, str]:
    return entry.name.casefold(), entry.name


class Walk:
    """A breadth-first walk of ``root``. Iterate it for :class:`WalkEntry` objects;
    :attr:`stats` counts what it saw.

    ``recursive=False`` lists the root only. ``max_depth`` is the deepest entry
    listed (1 is the root's own entries). ``max_examined`` caps the directory
    entries examined, documents or not. ``deadline`` is a ``time.monotonic()`` value; ``max_seconds``
    sets one from now. Constructing a walk checks the root: it raises
    ``FileNotFoundError``, ``NotADirectoryError`` or ``PermissionError`` for it,
    and nothing for anything below it.
    """

    def __init__(
        self,
        root: str | os.PathLike,
        *,
        recursive: bool = True,
        max_depth: int = DEFAULT_MAX_DEPTH,
        max_examined: int | None = DEFAULT_MAX_EXAMINED,
        max_seconds: float | None = None,
        deadline: float | None = None,
    ) -> None:
        self.root = os.fspath(root)
        st = os.stat(self.root)  # follows a junction or link root on purpose (C6)
        if not stat.S_ISDIR(st.st_mode):
            raise NotADirectoryError(20, "not a folder", self.root)
        self.root_dev = st.st_dev  # entries on another device are mount points (Linux and macOS)
        self.recursive = recursive
        self.max_depth = max_depth
        self.max_examined = max_examined
        if max_seconds is not None:
            limit = time.monotonic() + max_seconds
            deadline = limit if deadline is None else min(deadline, limit)
        self.deadline = deadline
        self.stats = WalkStats()
        self._started = False

    def _over(self) -> bool:
        if self.max_examined is not None and self.stats.entries >= self.max_examined:
            self.stats.truncated = "max_examined"
            return True
        if self.deadline is not None and time.monotonic() >= self.deadline:
            self.stats.truncated = "deadline"
            return True
        return False

    def __iter__(self) -> Iterator[WalkEntry]:
        if self._started:
            raise RuntimeError("a Walk can be iterated once")
        self._started = True
        return self._walk()

    def _walk(self) -> Iterator[WalkEntry]:
        stats = self.stats
        queue: deque[tuple[str, str, int]] = deque([(self.root, "", 0)])
        while queue:
            folder, rel, depth = queue.popleft()
            if self._over():
                return
            items: list[Any] = []
            try:
                with _scandir(folder) as it:
                    for item in it:
                        if self._over():
                            break
                        stats.entries += 1
                        items.append(item)
            except OSError as exc:
                if depth == 0:
                    raise  # the root itself: the caller's argument is wrong
                stats.errors += 1
                name = rel.rsplit("/", 1)[-1]
                yield WalkEntry(folder, rel, name, depth, "error", True, None, None, type(exc).__name__, exc)
                continue
            stats.folders += 1
            items.sort(key=_sort_key)
            for item in items:
                e = classify(item, folder, rel, depth + 1, root_dev=self.root_dev)
                if e.kind == "file":
                    stats.files += 1
                elif e.kind == "link":
                    stats.links += 1
                elif e.kind == "placeholder":
                    stats.placeholders += 1
                elif e.kind == "skipped":
                    stats.skipped += 1
                elif e.kind == "error":
                    stats.errors += 1
                elif e.kind == "folder" and self.recursive:
                    if e.depth >= self.max_depth:
                        stats.depth_limited += 1
                        e = dataclasses.replace(e, reason="max_depth")
                    else:
                        queue.append((e.path, e.rel, e.depth))
                yield e
            if stats.truncated:
                return


__all__ = [
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_EXAMINED",
    "FILE_ATTRIBUTE_OFFLINE",
    "FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS",
    "FILE_ATTRIBUTE_RECALL_ON_OPEN",
    "IO_REPARSE_TAG_MOUNT_POINT",
    "IO_REPARSE_TAG_SYMLINK",
    "NAME_SURROGATE",
    "Walk",
    "WalkEntry",
    "WalkStats",
    "classify",
    "reparse_link",
]
