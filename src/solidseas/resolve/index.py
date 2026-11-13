"""The folder index of one root: every SOLIDWORKS document below it, and every file a part
can be imported from (:data:`.names.IMPORT_EXTENSIONS`), by folder and by
name, as the shared folder walker (:mod:`solidseas.walk`) found it.

The gateway (:mod:`.gateway`) walks the root and feeds the entries in; this
module only keeps them. Because the walker never follows a link, junction or
mount point, nothing behind one is in the index, so a lookup inside a root
cannot leave it, on every operating system. Cloud placeholders are indexed
with ``placeholder=True`` and are never opened.

Names and folders are keyed by :func:`.names.fold`, so lookups are
case-insensitive the way NTFS is, on every operating system. A
case-sensitive filesystem can hold two names that fold alike; both are kept,
and a lookup returns both. A second key, :func:`.names.nfc_fold`, finds a
name that matches only after NFC normalisation; such a lookup says so.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from ..roots import Root
from .names import HostPath, fold, is_reference_name, nfc_fold


@dataclass(frozen=True)
class IndexedFile:
    """One document found by the walk. ``rel`` is relative to the root, ``/``-separated,
    in the on-disk spelling."""

    rel: str
    name: str
    folder: tuple[str, ...]
    size: int | None
    mtime_ns: int | None
    placeholder: bool


@dataclass
class _Folder:
    dirs: dict[str, list[str]] = field(default_factory=dict)  # fold(name) -> child rel
    nfc_dirs: dict[str, list[str]] = field(default_factory=dict)
    files: dict[str, list[IndexedFile]] = field(default_factory=dict)
    nfc_files: dict[str, list[IndexedFile]] = field(default_factory=dict)


class FolderIndex:
    """The documents below one root. Built by :meth:`.gateway.Gateway.build_index`.

    ``partial`` names the bound that cut the walk short (``max_examined``,
    ``deadline`` or ``max_depth``), or is None for a complete index.
    ``unreadable`` counts folders the walk could not list.
    """

    def __init__(self, root: Root, host: HostPath) -> None:
        self.root = root
        self.host = host
        self.partial: str | None = None
        self.unreadable = 0
        self.examined = 0
        self.documents = 0
        self._folders: dict[str, _Folder] = {"": _Folder()}
        self._by_name: dict[str, list[IndexedFile]] = {}
        self._by_nfc: dict[str, list[IndexedFile]] = {}

    # ------------------------------------------------------------------ building
    def _folder(self, rel: str) -> _Folder:
        node = self._folders.get(rel)
        if node is None:
            node = self._folders[rel] = _Folder()
        return node

    def add_folder(self, rel: str, name: str) -> None:
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        node = self._folder(parent)
        node.dirs.setdefault(fold(name), []).append(rel)
        node.nfc_dirs.setdefault(nfc_fold(name), []).append(rel)
        self._folder(rel)

    def add_file(
        self, rel: str, name: str, size: int | None, mtime_ns: int | None, placeholder: bool
    ) -> None:
        if not is_reference_name(name):
            return
        folder = tuple(rel.split("/")[:-1])
        f = IndexedFile(rel, name, folder, size, mtime_ns, placeholder)
        node = self._folder("/".join(folder))
        key, nkey = fold(name), nfc_fold(name)
        node.files.setdefault(key, []).append(f)
        node.nfc_files.setdefault(nkey, []).append(f)
        self._by_name.setdefault(key, []).append(f)
        self._by_nfc.setdefault(nkey, []).append(f)
        self.documents += 1

    def with_root(self, root: Root) -> "FolderIndex":
        """The same index under another root id or role (the folder is the same)."""
        other = FolderIndex.__new__(FolderIndex)
        other.__dict__.update(self.__dict__)
        other.root = root
        return other

    def with_files(self, files: Sequence[tuple[str, int | None, int | None]]) -> "FolderIndex":
        """A copy of this index with ``files`` (``rel``, ``size``, ``mtime_ns``) added as if
        the walk had found them, in folders it already holds. A copy plan uses it to ask
        what the search would find once its planned copies exist. This index is left as
        it is."""
        other = FolderIndex.__new__(FolderIndex)
        other.__dict__.update(self.__dict__)
        other._folders = dict(self._folders)
        other._by_name = dict(self._by_name)
        other._by_nfc = dict(self._by_nfc)
        copied: set[str] = set()
        for rel, size, mtime_ns in files:
            name = rel.rsplit("/", 1)[-1]
            if not is_reference_name(name):
                continue
            folder = rel.rsplit("/", 1)[0] if "/" in rel else ""
            if folder not in copied:
                old = other._folders.get(folder)
                if old is not None:
                    other._folders[folder] = _Folder(
                        old.dirs,
                        old.nfc_dirs,
                        {k: list(v) for k, v in old.files.items()},
                        {k: list(v) for k, v in old.nfc_files.items()},
                    )
                copied.add(folder)
            key, nkey = fold(name), nfc_fold(name)
            other._by_name[key] = list(other._by_name.get(key, ()))
            other._by_nfc[nkey] = list(other._by_nfc.get(nkey, ()))
            other.add_file(rel, name, size, mtime_ns, False)
        return other

    # ------------------------------------------------------------------ lookups
    def covers(self, host: HostPath) -> tuple[str, ...] | None:
        """The components of the folder ``host`` below this root, or None when the
        index does not cover that folder (another root, or below a root that is not
        recursive). Compared folded."""
        anchor, parts = self.host.key
        h_anchor, h_parts = host.key
        if h_anchor != anchor or h_parts[: len(parts)] != parts:
            return None
        rest = host.parts[len(parts) :]
        if rest and not self.root.recursive:
            return None
        return tuple(rest)

    def lookup(self, folder: Sequence[str], name: str) -> tuple[list[IndexedFile], bool]:
        """Documents named ``name`` in the folder ``folder`` (components below the root),
        each component matched folded. Returns ``(files, nfc_only)``: ``nfc_only`` is True
        when a component or the name matched only after NFC normalisation."""
        nodes = [("", False)]
        for comp in folder:
            nxt: list[tuple[str, bool]] = []
            key, nkey = fold(comp), nfc_fold(comp)
            for rel, weak in nodes:
                node = self._folders.get(rel)
                if node is None:
                    continue
                exact = node.dirs.get(key)
                if exact:
                    nxt += [(r, weak) for r in exact]
                else:
                    nxt += [(r, True) for r in node.nfc_dirs.get(nkey, ())]
            nodes = nxt
            if not nodes:
                return [], False
        out: list[IndexedFile] = []
        weak_any = False
        key, nkey = fold(name), nfc_fold(name)
        for rel, weak in nodes:
            node = self._folders.get(rel)
            if node is None:
                continue
            exact = node.files.get(key)
            if exact:
                out += exact
                weak_any = weak_any or weak
            elif node.nfc_files.get(nkey):
                out += node.nfc_files[nkey]
                weak_any = True
        return out, weak_any and bool(out)

    def by_name(self, name: str) -> tuple[list[IndexedFile], bool]:
        """Every document named ``name`` anywhere below the root, and whether the name
        matched only after NFC normalisation."""
        exact = self._by_name.get(fold(name))
        if exact:
            return list(exact), False
        weak = self._by_nfc.get(nfc_fold(name))
        return (list(weak), True) if weak else ([], False)

    def child_folders(self, rel: str, name: str) -> list[str]:
        """The folders named ``name`` (compared folded) directly in the folder ``rel``,
        as relative paths in the on-disk spelling."""
        node = self._folders.get(rel)
        return list(node.dirs.get(fold(name), ())) if node is not None else []

    def folder_files(self, rel: str, name: str) -> list[IndexedFile]:
        """The documents named ``name`` (compared folded) directly in the folder ``rel``."""
        node = self._folders.get(rel)
        return list(node.files.get(fold(name), ())) if node is not None else []

    def host_of(self, f: IndexedFile) -> HostPath:
        return self.host.child(*f.rel.split("/"))

    def folder_parts(self, f: IndexedFile) -> tuple[str, ...]:
        """The file's folder as host components, for suffix scores."""
        return (*self.host.parts, *f.folder)


__all__ = ["FolderIndex", "IndexedFile"]
