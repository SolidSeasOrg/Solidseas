"""Where a request's ``path`` is on disk, found without ever joining client text into a
path (``docs/API.md`` C3; critique 3.16; ```` and
``loopback-browser-dashboard``).

1. :func:`check_path_text` checks the text alone, with no filesystem access,
   and refuses with :class:`~solidseas.errors.PathRefusedError`, naming the
   rule and the component (``detail["rule"]``, ``detail["component_index"]``).
   The same rules apply on every operating system, so the API behaves the same
   everywhere: a leading ``/`` (``absolute``), an empty component
   (``empty_component``), a backslash, a control character or NUL, a lone
   surrogate, ``:`` (alternate data streams and drive letters, ``colon``), a
   component of dots and spaces such as ``..`` (``dot_component``), a trailing
   dot or space, ``< > " | ? *`` (``reserved_character``), a device name such
   as ``CON`` or ``NUL.txt`` (``device_name``), more than 1,024 characters
   (``too_long``), 64 components (``too_deep``) or 255 characters in one
   (``component_too_long``); and for a document route, a name without a
   SOLIDWORKS extension, or the extension of another format the service was
   started to read (``not_a_document``).
2. :func:`locate` then finds each component, compared as NTFS compares names,
   among the names the root's folder index holds (the index the service built
   when it started, with the shared walker, so nothing behind a link is in it).
   A name the index lacks (a file added since the service started) is looked
   for among the entries of a live listing of the deepest folder the index
   knows, and each entry found is classified by the walker's own rules: a link
   or mount point answers ``link_refused``, a cloud placeholder
   ``placeholder_file``, a lock file or a pipe ``path_refused``. The host path
   is built from the names the index or the listing returned, never from the
   request. Every component is then checked again with ``lstat``, from the root
   down, before the next is asked of the operating system: a folder of the
   index replaced by a link since the start is refused before any path through
   it is used (a symbolic link to a share would otherwise make the operating
   system connect there just to answer). An exact spelling wins; a name that matches several entries only
   case-insensitively is not found. 8.3 short names are never in a listing, so
   they are not found either.
3. The worker that reads the document opens it ``within`` the root (``O_NOFOLLOW``
   below the root on Linux and macOS, the final path of the open handle on
   Windows), which closes the race between this lookup and the read.
"""

import os
import stat
from dataclasses import dataclass

from .. import walk as walk_mod
from ..errors import InvalidArgumentError, LinkRefusedError, PathRefusedError, PlaceholderFileError
from ..formats.solidworks import SOLIDWORKS_EXTENSIONS
from ..resolve.index import FolderIndex
from ..resolve.names import component_problem, fold

MAX_PATH_CHARS = 1024
MAX_COMPONENTS = 64
_RESERVED = frozenset('<>"|?*')
_RULE = {"dots_and_spaces": "dot_component"}


def _refuse(rule: str, index: int | None = None) -> PathRefusedError:
    detail: dict = {"rule": rule}
    if index is not None:
        detail["component_index"] = index
    return PathRefusedError(f"the path was refused ({rule})", detail=detail)


def check_path_text(
    text: str, *, want: str, extensions: tuple[str, ...] = SOLIDWORKS_EXTENSIONS
) -> tuple[str, ...]:
    """The components of a request path, or :class:`PathRefusedError`. ``want`` is
    ``file`` (a document route) or ``folder`` (the listing, where ``""`` is the root);
    a document's name must end in one of ``extensions`` (lower case)."""
    if len(text) > MAX_PATH_CHARS:
        raise _refuse("too_long")
    if text.startswith("/"):
        raise _refuse("absolute", 0)
    if not text:
        if want == "folder":
            return ()
        raise _refuse("empty_component", 0)
    parts = text.split("/")
    if len(parts) > MAX_COMPONENTS:
        raise _refuse("too_deep")
    for i, c in enumerate(parts):
        if "\\" in c:
            raise _refuse("backslash", i)
        if any("\ud800" <= ch <= "\udfff" for ch in c):
            raise _refuse("lone_surrogate", i)
        problem = component_problem(c)
        if problem is not None:
            raise _refuse(_RULE.get(problem, problem), i)
        if c[-1] in ". ":
            raise _refuse("trailing_dot_or_space", i)
        if any(ch in _RESERVED for ch in c):
            raise _refuse("reserved_character", i)
    if want == "file" and not parts[-1].lower().endswith(tuple(extensions)):
        raise _refuse("not_a_document", len(parts) - 1)
    return tuple(parts)


@dataclass(frozen=True)
class Located:
    """A file or folder below a root. ``rel`` is ``/``-separated in the on-disk spelling
    (``""`` for the root itself); ``host`` the absolute path on this machine, built
    from names the index or a listing returned; ``size`` and ``mtime_ns`` from a
    fresh ``lstat`` (the service's ETag)."""

    rel: str
    host: str
    name: str
    is_dir: bool
    size: int | None
    mtime_ns: int | None


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


def _pick(candidates: list, name: str, key):
    exact = [c for c in candidates if key(c) == name]
    if exact:
        return exact[0]
    return candidates[0] if len(candidates) == 1 else None


def _not_found() -> FileNotFoundError:
    return FileNotFoundError(2, "no such file or folder in the root")


def _check_entry(we: walk_mod.WalkEntry, index: int, *, last: bool, want: str) -> None:
    if we.kind == "link":
        raise LinkRefusedError(
            "the path goes through a link, junction or mount point",
            detail={"rule": "link_in_path", "component_index": index},
        )
    if we.kind == "placeholder":
        raise PlaceholderFileError("the file is a cloud placeholder whose data is not on this machine")
    if we.kind == "error":
        raise we.error if isinstance(we.error, OSError) else _not_found()
    if we.kind == "skipped":
        raise _refuse(we.reason or "skipped", index)
    if last and want == "folder" and we.kind == "file":
        raise InvalidArgumentError(
            "the path names a file, not a folder", detail={"parameter": "path", "rule": "not_a_folder"}
        )
    if (not last or want == "folder") and we.kind != "folder":
        raise _not_found()
    if last and want == "file" and we.kind != "file":
        raise _not_found()


def _check_folders(index: FolderIndex, parts: tuple[str, ...], root_dev: int | None) -> str:
    """The host path of the folder ``parts`` below the root, after an ``lstat`` of each
    component from the root down has found a folder and no link. The folders come from
    the index built at start, and one may have been replaced by a link since: each
    ``lstat`` names a path whose folders were all checked already, so the operating
    system never goes through a link (a symbolic link to a share would make it connect
    there) before it is refused."""
    host = index.host.join()
    for i, comp in enumerate(parts):
        host = os.path.join(host, comp)
        st = os.lstat(host)
        we = walk_mod.classify(_Probe(comp, st), os.path.dirname(host), "", i + 1, root_dev=root_dev)
        _check_entry(we, i, last=False, want="folder")
    return host


def _fresh(index: FolderIndex, rel: str, name: str, *, is_dir: bool, root_dev: int | None) -> Located:
    """``rel`` re-read with ``lstat``, component by component from the root, and classified
    again: what changed since the index was built is caught here (the worker's own open
    catches what changes later)."""
    parts = tuple(rel.split("/")) if rel else ()
    if not parts:  # the root itself; it may be a link (C6)
        host = index.host.join()
        st = os.stat(host)
        if not stat.S_ISDIR(st.st_mode):
            raise NotADirectoryError(20, "the root is not a folder")
        return Located("", host, name, True, None, st.st_mtime_ns)
    folder = _check_folders(index, parts[:-1], root_dev)
    host = os.path.join(folder, parts[-1])
    st = os.lstat(host)
    we = walk_mod.classify(_Probe(parts[-1], st), folder, "", len(parts), root_dev=root_dev)
    _check_entry(we, len(parts) - 1, last=True, want="folder" if is_dir else "file")
    return Located(rel, host, parts[-1], is_dir, None if is_dir else st.st_size, st.st_mtime_ns)


def locate(index: FolderIndex, parts: tuple[str, ...], *, want: str, root_dev: int | None = None) -> Located:
    """The file (``want="file"``) or folder (``"folder"``) the checked components name
    below the root of ``index`` (see the module notes). Raises ``FileNotFoundError``,
    :class:`LinkRefusedError`, :class:`PlaceholderFileError` or :class:`PathRefusedError`."""
    folders = parts if want == "folder" else parts[:-1]
    if folders and not index.root.recursive:
        raise _not_found()  # a root that is not recursive serves its own folder only
    rel = ""
    i = 0
    while i < len(folders):
        found = _pick(index.child_folders(rel, folders[i]), folders[i], lambda r: r.rsplit("/", 1)[-1])
        if found is None:
            break
        rel = found
        i += 1
    if i == len(folders):
        if want == "folder":
            return _fresh(index, rel, rel.rsplit("/", 1)[-1], is_dir=True, root_dev=root_dev)
        f = _pick(index.folder_files(rel, parts[-1]), parts[-1], lambda x: x.name)
        if f is not None:
            if f.placeholder:
                raise PlaceholderFileError(
                    "the file is a cloud placeholder whose data is not on this machine"
                )
            return _fresh(index, f.rel, f.name, is_dir=False, root_dev=root_dev)
    return _live(index, rel, parts, i, want=want, root_dev=root_dev)


def _live(
    index: FolderIndex, rel: str, parts: tuple[str, ...], start: int, *, want: str, root_dev: int | None
) -> Located:
    try:  # the deepest folder the index knows, checked from the root before it is listed
        folder = _check_folders(index, tuple(rel.split("/")) if rel else (), root_dev)
    except (FileNotFoundError, NotADirectoryError):
        raise _not_found() from None
    for i in range(start, len(parts)):
        comp = parts[i]
        key = fold(comp)
        try:
            with walk_mod._scandir(folder) as it:
                matches = [e for e in it if fold(e.name) == key]
        except (FileNotFoundError, NotADirectoryError):
            raise _not_found() from None
        entry = _pick(matches, comp, lambda e: e.name)
        if entry is None:
            raise _not_found()
        last = i == len(parts) - 1
        we = walk_mod.classify(entry, folder, rel, i + 1, root_dev=root_dev)
        _check_entry(we, i, last=last, want=want)
        rel, folder = we.rel, we.path
    name = rel.rsplit("/", 1)[-1]
    return _fresh(index, rel, name, is_dir=want == "folder", root_dev=root_dev)


__all__ = ["MAX_COMPONENTS", "MAX_PATH_CHARS", "Located", "check_path_text", "locate"]
