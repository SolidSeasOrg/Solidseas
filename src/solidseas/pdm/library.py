"""The common-parts library and the self-contained check's copies (``docs/PDM.md`` 5 and 6).

The library section of a library folder (``Library`` by default) holds parts that many
projects use. Each part there that the vault knows as an item has a record,
``.solidseas/vault/library/items/<item>.json``, with its item number and description.
Using an item copies its current version into a project and writes a link record,
``.solidseas/vault/library/links/<time>-<id>.json``, that says which version went where.
A later link record for the same project file supersedes an earlier one.

**Records.** Both kinds are written once, through a temporary name and a rename that
fails on an existing name, and never rewritten. They are data from a folder others may
write to, so :func:`parse_item` and :func:`parse_link` check every field and return
None for a record that does not hold up, which the reader skips.

**What it writes.** The copies ``add``, ``use``, ``update`` and ``check --fix`` make,
and the vault's own folder. A copy is written under a temporary name in the folder it
goes to and renamed, never through a link. ``use`` and ``check --fix`` write new files
only. ``update`` replaces only a file a link record says SolidSeas copied there, after
storing it as a version, and refuses one edited since unless forced. The source of a
copy is never changed.

**Candidates fast.** Files are grouped by size first, so a file whose size no other
file shares is never read, and a file whose size and modification time are those of
its newest version in the vault takes that version's hash without being read.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import __version__
from ..errors import BusyError, InvalidArgumentError, OutputRefusedError, PathRefusedError, SolidSeasError
from ..formats.solidworks._io import check_folder_within, open_readonly
from ..resolve.names import component_problem, fold
from ..versions import snapstore
from ..versions.gitrepo import _is_link
from .check import CheckResult, CopyPlan, check_project, is_toolbox_path, plan_copies
from .checkins import CheckinFile, valid_relative
from .vault import _folded

RECORD_VERSION = 1
MAX_RECORD_BYTES = 64 << 10
MAX_DESCRIPTION = 1000
MAX_ITEMS = 100_000
ITEM_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}\Z")
AUTO_ID = re.compile(r"SS-(\d{5,9})\Z", re.IGNORECASE)
LINK_NAME = re.compile(r"(\d{8}T\d{12}Z)-([0-9a-f]{12})\.json\Z")
HOW = ("use", "update", "fix")
_CANDIDATE_EXTENSIONS = (".sldprt", ".sldasm")  # parts and assemblies: what projects share
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SNAPSHOT_ID = re.compile(r"[0-9a-f]{12}\Z")
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_CHUNK = 1 << 20
_O_BINARY = getattr(os, "O_BINARY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_NEW_FILE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY | _O_NOFOLLOW | _O_CLOEXEC
_FORBIDDEN = set('/\\<>"|?*')


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _stamp(when: datetime.datetime) -> str:
    return when.strftime("%Y%m%dT%H%M%S%f") + "Z"


def _brief_time(when: datetime.datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(text: Any) -> datetime.datetime | None:
    if not isinstance(text, str) or len(text) > 40:
        return None
    try:
        return datetime.datetime.strptime(text, _TIME_FORMAT).replace(tzinfo=datetime.UTC)
    except ValueError:
        return None


def _key(rel: str) -> str:
    """A path below the library as the vault compares paths: ignoring case on Windows
    and macOS, exactly elsewhere."""
    return _folded(rel)


def valid_item_id(value: Any) -> bool:
    """Whether ``value`` can be an item number: 1 to 40 letters, digits, dots, hyphens
    and underscores, starting with a letter or digit, and usable as a file name."""
    return (
        isinstance(value, str)
        and ITEM_ID.match(value) is not None
        and not value.endswith(".")
        and component_problem(value + ".json") is None
    )


def _valid_description(value: Any) -> bool:
    return isinstance(value, str) and len(value) <= MAX_DESCRIPTION and not any(ord(c) < 32 for c in value)


def _sha(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.match(value) is not None


def _size(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and 0 <= value <= 2**53 - 1


# --------------------------------------------------------------------------- records
@dataclass(frozen=True)
class Item:
    """A library item: its number, the file in the library section (``path`` below the
    library), its description, the version it was added as, and where it was copied
    from (``source``, None when the file was already in the library section)."""

    id: str
    when: datetime.datetime
    path: str
    description: str
    sha256: str
    size: int
    snapshot: str
    source: str | None
    solidseas: str
    record: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "v": RECORD_VERSION,
            "item": self.id,
            "when_utc": self.when.strftime(_TIME_FORMAT),
            "path": self.path,
            "description": self.description,
            "sha256": self.sha256,
            "size": self.size,
            "snapshot": self.snapshot,
            "source": self.source,
            "solidseas": self.solidseas,
        }

    def data(self) -> dict[str, Any]:
        return {
            "item": self.id,
            "description": self.description,
            "path": self.path,
            "added_utc": _brief_time(self.when),
            "source": self.source,
            "first_version": self.snapshot,
        }


@dataclass(frozen=True)
class Link:
    """One copy of a library item in a project: which version of which item went to
    ``path`` (below the library) in ``project``, the copy's content and modification
    time right after it was made, and ``how`` it was made (``use``, ``update`` or
    ``fix``)."""

    id: str
    when: datetime.datetime
    item: str
    item_path: str
    item_sha256: str
    item_snapshot: str
    project: str
    path: str
    sha256: str
    size: int
    mtime_ns: int | None
    how: str
    solidseas: str
    record: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "v": RECORD_VERSION,
            "id": self.id,
            "when_utc": self.when.strftime(_TIME_FORMAT),
            "item": self.item,
            "item_path": self.item_path,
            "item_sha256": self.item_sha256,
            "item_snapshot": self.item_snapshot,
            "project": self.project,
            "path": self.path,
            "sha256": self.sha256,
            "size": self.size,
            "mtime_ns": None if self.mtime_ns is None else str(self.mtime_ns),
            "how": self.how,
            "solidseas": self.solidseas,
        }

    def data(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "when_utc": _brief_time(self.when),
            "item": self.item,
            "project": self.project,
            "path": self.path,
            "version": self.item_snapshot,
            "sha256": self.sha256,
            "how": self.how,
        }


def _load(data: bytes) -> dict[str, Any] | None:
    if len(data) > MAX_RECORD_BYTES:
        return None
    try:
        obj = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(obj, dict) or obj.get("v") != RECORD_VERSION:
        return None
    return obj


def parse_item(data: bytes, name: str) -> Item | None:
    """The item a record file holds, or None when its name or any field does not hold up."""
    obj = _load(data)
    if obj is None or not name.endswith(".json"):
        return None
    ident = obj.get("item")
    if not valid_item_id(ident) or name != f"{ident}.json":
        return None
    when = _parse_time(obj.get("when_utc"))
    path, desc, sha, size, snap = (obj.get(k) for k in ("path", "description", "sha256", "size", "snapshot"))
    source, made_by = obj.get("source"), obj.get("solidseas")
    if (
        when is None
        or not valid_relative(path)
        or "/" not in path
        or not _valid_description(desc)
        or not _sha(sha)
        or not _size(size)
        or not isinstance(snap, str)
        or not _SNAPSHOT_ID.match(snap)
        or (source is not None and not valid_relative(source))
        or not isinstance(made_by, str)
        or len(made_by) > 40
    ):
        return None
    return Item(ident, when, path, desc, sha, size, snap, source, made_by, name)


def parse_link(data: bytes, name: str) -> Link | None:
    """The link a record file holds, or None when its name or any field does not hold up."""
    m = LINK_NAME.match(name)
    obj = _load(data)
    if m is None or obj is None or obj.get("id") != m.group(2):
        return None
    when = _parse_time(obj.get("when_utc"))
    if when is None or _stamp(when) != m.group(1):
        return None
    f = {k: obj.get(k) for k in Link.__dataclass_fields__ if k not in ("id", "when", "record", "solidseas")}
    made_by, mtime = obj.get("solidseas"), f["mtime_ns"]
    if (
        not valid_item_id(f["item"])
        or not valid_relative(f["item_path"])
        or not _sha(f["item_sha256"])
        or not isinstance(f["item_snapshot"], str)
        or not _SNAPSHOT_ID.match(f["item_snapshot"])
        or not valid_relative(f["project"])
        or not valid_relative(f["path"])
        or not _key(f["path"]).startswith(_key(f["project"]) + "/")
        or not _sha(f["sha256"])
        or not _size(f["size"])
        or (mtime is not None and (not isinstance(mtime, str) or not re.fullmatch(r"-?\d{1,20}", mtime)))
        or f["how"] not in HOW
        or not isinstance(made_by, str)
        or len(made_by) > 40
    ):
        return None
    return Link(
        m.group(2),
        when,
        f["item"],
        f["item_path"],
        f["item_sha256"],
        f["item_snapshot"],
        f["project"],
        f["path"],
        f["sha256"],
        f["size"],
        None if mtime is None else int(mtime),
        f["how"],
        made_by,
        name,
    )


# --------------------------------------------------------------------------- writing files
def _regular(path: str) -> os.stat_result | None:
    """The file's lstat, None when it does not exist; a link or a folder is refused."""
    from .vault import _regular_or_none

    return _regular_or_none(path)


def _temp_name(folder: str) -> str:
    return os.path.join(folder, f".solidseas-copy-{secrets.token_hex(8)}.tmp")


def _stream_to_temp(src, folder: str) -> tuple[str, str, int]:
    """Copy the open file ``src`` into a new temporary file in ``folder``: ``(tmp, sha256,
    size)``. The temporary file is removed when anything fails."""
    tmp = _temp_name(folder)
    fd = os.open(tmp, _NEW_FILE, 0o644)
    h = hashlib.sha256()
    n = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = src.read(_CHUNK)
                if not chunk:
                    break
                h.update(chunk)
                out.write(chunk)
                n += len(chunk)
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        if os.path.lexists(tmp):
            os.remove(tmp)
        raise
    return tmp, h.hexdigest(), n


def _copy_file_to_temp(source: str, folder: str) -> tuple[str, str, int]:
    """A temporary copy of the file at ``source`` in ``folder``; a file that changes while
    it is read is ``busy``."""
    with open_readonly(source, within=os.path.dirname(source)) as src:
        before = os.fstat(src.fileno())
        tmp, sha, n = _stream_to_temp(src, folder)
        after = os.fstat(src.fileno())
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or n != after.st_size:
        os.remove(tmp)
        raise BusyError(
            "the file changed while it was copied: try again once it is saved",
            detail={"rule": "file_changing"},
        )
    return tmp, sha, n


def _copy_snapshot_to_temp(store: snapstore.SnapshotStore, snap: snapstore.Snapshot, folder: str) -> str:
    """A temporary copy of a stored version in ``folder``, checked against its hash."""
    store._check_root()
    with open_readonly(store.object_path(snap.sha256), within=store.root) as src:
        tmp, sha, n = _stream_to_temp(src, folder)
    if sha != snap.sha256 or n != snap.size:
        os.remove(tmp)
        raise snapstore.SnapshotDamagedError("the version's stored copy does not match its hash")
    return tmp


def _write_record(folder: str, name: str, obj: dict[str, Any]) -> None:
    """Write a record once: a temporary name, then a rename that fails on an existing name."""
    from .vault import _rename_new

    data = json.dumps(obj, ensure_ascii=True, sort_keys=True).encode("ascii")
    tmp = os.path.join(folder, f".tmp-{secrets.token_hex(8)}")
    fd = os.open(tmp, _NEW_FILE, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        _rename_new(tmp, os.path.join(folder, name))
    finally:
        if os.path.lexists(tmp):
            os.remove(tmp)


def _make_folders(base: str, parts: list[str]) -> str:
    """``base`` joined with ``parts``, each folder made when missing; a link or a file on
    the way is refused."""
    from .vault import _refuse_link

    cur = base
    for name in parts:
        cur = os.path.join(cur, name)
        _refuse_link(cur, "a folder on the way")
        try:
            os.mkdir(cur)
        except FileExistsError:
            pass
        if _is_link(cur) or not os.path.isdir(cur):
            raise PathRefusedError(f"{cur}: not a folder", detail={"rule": "not_a_folder"})
    return cur


def _subfolder(value: str | None) -> list[str]:
    """The components of a ``--to`` folder below a project."""
    if value is None or value in ("", "."):
        return []
    parts = [p for p in value.replace("\\", "/").split("/") if p not in ("", ".")]
    if (
        value.startswith(("/", "\\"))
        or (len(value) > 1 and value[1] == ":")
        or not parts
        or any(
            p == ".."
            or p.startswith(".")
            or component_problem(p) is not None
            or any(c in _FORBIDDEN for c in p)
            for p in parts
        )
    ):
        raise InvalidArgumentError(
            f"{value!r}: --to names a folder inside the project, such as parts/hardware",
            detail={"parameter": "to"},
        )
    return parts


# --------------------------------------------------------------------------- the library
@dataclass
class _ItemState:
    """An item's file as it is now: ``sha256`` None when it is missing. ``snapshot`` is
    its newest version in the vault, ``stored`` whether the file still holds it."""

    full: str
    sha256: str | None
    snapshot: snapstore.Snapshot | None

    @property
    def stored(self) -> bool:
        return self.snapshot is not None and self.sha256 == self.snapshot.sha256


class Library:
    """The common parts of a vault's library section (``vault.library``)."""

    def __init__(self, vault) -> None:
        self.vault = vault
        self.folder = os.path.join(vault.folder, "library")

    @property
    def section(self) -> str:
        return self.vault.settings.library

    @property
    def section_path(self) -> str:
        return self.vault.absolute(self.section)

    def in_section(self, rel: str) -> bool:
        parts = rel.split("/")
        return len(parts) > 1 and fold(parts[0]) == fold(self.section)

    # ------------------------------------------------------------------ reading records
    def _records(self, kind: str) -> tuple[str, list[str]]:
        from .vault import _refuse_link

        self.vault.store._check_root()
        _refuse_link(self.folder, "the vault's library folder")
        folder = os.path.join(self.folder, kind)
        _refuse_link(folder, "the vault's library folder")
        try:
            names = sorted(os.listdir(folder))
        except (FileNotFoundError, NotADirectoryError):
            return folder, []
        return folder, names[:MAX_ITEMS] if kind == "items" else names

    def _read(self, folder: str, name: str) -> bytes | None:
        try:
            with open_readonly(os.path.join(folder, name), within=self.vault.folder) as fh:
                return fh.read(MAX_RECORD_BYTES + 1)
        except (OSError, SolidSeasError):
            return None

    def items(self) -> list[Item]:
        """Every item whose record holds up and names a file in the library section, by number."""
        folder, names = self._records("items")
        out: dict[str, Item] = {}
        for name in names:
            if not name.endswith(".json") or name.startswith("."):
                continue
            data = self._read(folder, name)
            item = None if data is None else parse_item(data, name)
            if item is None or not self.in_section(item.path):
                continue
            out.setdefault(fold(item.id), item)  # two names that fold alike: the first, by name
        return sorted(out.values(), key=lambda i: (i.id.casefold(), i.id))

    def item(self, ident: str) -> Item:
        """The item of that number (case does not matter); ``invalid_argument`` (rule
        ``unknown_item``) when there is none."""
        for it in self.items():
            if fold(it.id) == fold(str(ident)):
                return it
        raise InvalidArgumentError(
            f"{ident}: no library item has that number (pdm library list shows them)",
            detail={"rule": "unknown_item", "parameter": "item"},
        )

    def links(self) -> list[Link]:
        """Every link record that holds up, oldest first."""
        folder, names = self._records("links")
        out = []
        for name in names:
            if not LINK_NAME.match(name):
                continue
            data = self._read(folder, name)
            link = None if data is None else parse_link(data, name)
            if link is not None:
                out.append(link)
        out.sort(key=lambda link: (link.when, link.id))
        return out

    def current_links(self) -> dict[str, Link]:
        """The newest link of every project file, keyed by its folded path."""
        out: dict[str, Link] = {}
        for link in self.links():
            out[_key(link.path)] = link
        return out

    # ------------------------------------------------------------------ states
    def _hash_of(self, rel: str, st: os.stat_result, index: dict[str, snapstore.Snapshot] | None = None):
        """``(sha256, newest snapshot)`` of the file at ``rel``, read only when its size or
        time differ from its newest version's."""
        store = self.vault.store
        snap = index.get(_folded(rel)) if index is not None else store.newest(store.key_of(rel))
        if snap is not None and (snap.size, snap.mtime_ns) == (st.st_size, st.st_mtime_ns):
            return snap.sha256, snap
        sha, _size, _mtime = self.vault._hash(self.vault.absolute(rel))
        return sha, snap

    def _item_state(self, item: Item) -> _ItemState:
        full = self.vault.absolute(item.path)
        st = _regular(full)
        if st is None:
            store = self.vault.store
            return _ItemState(full, None, store.newest(store.key_of(item.path)))
        sha, snap = self._hash_of(item.path, st)
        return _ItemState(full, sha, snap)

    def _version_number(self, rel: str, snap_id: str) -> int | None:
        for n, s in enumerate(self.vault.store.snapshots(self.vault.absolute(rel)), start=1):
            if s.id == snap_id:
                return n
        return None

    def _project(self, path: str | os.PathLike):
        """The project that ``path`` is or lies in; ``invalid_argument`` (rule
        ``not_a_project``) otherwise."""
        from .vault import Project

        full = os.path.abspath(os.fspath(path))
        proj = self.vault.project_of(full)
        if proj is None:
            raise InvalidArgumentError(
                f"{full}: not a project folder of the library, or a folder in one",
                detail={"rule": "not_a_project", "parameter": "project"},
            )
        assert isinstance(proj, Project)
        check_folder_within(self.vault.absolute(proj.path), self.vault.root)
        return proj

    def _checkin(self, entries: list[CheckinFile], note: str, who: str | None):
        if not entries:
            return None
        return self.vault._new_checkin(
            entries, note[: snapstore.MAX_NOTE], who=self.vault.settings.who if who is None else who
        )

    def _write_link(
        self, item: Item, version: snapstore.Snapshot, project: str, dest_rel: str, how: str
    ) -> Link:
        store = self.vault.store
        store._make_root()
        folder = store._folder(store._folder(self.vault.folder, "library", create=True), "links", create=True)
        st = os.lstat(self.vault.absolute(dest_rel))
        when = _now()
        link = Link(
            secrets.token_hex(6),
            when,
            item.id,
            item.path,
            version.sha256,
            version.id,
            project,
            dest_rel,
            version.sha256,
            st.st_size,
            st.st_mtime_ns,
            how,
            __version__,
        )
        name = f"{_stamp(when)}-{link.id}.json"
        _write_record(folder, name, link.to_json())
        return Link(*(getattr(link, f) for f in Link.__dataclass_fields__ if f != "record"), name)

    def _store(self, rel: str, note: str | None, entries: list[CheckinFile]) -> snapstore.Snapshot:
        snap, new = self.vault.store.add(self.vault.absolute(rel), note=note)
        if new:
            entries.append(CheckinFile(rel, snap.sha256, snap.size, snap.id, True))
        return snap

    def _version(self, rel: str, snap: snapstore.Snapshot) -> dict[str, Any]:
        return {
            "id": snap.id,
            "number": self._version_number(rel, snap.id),
            "sha256": snap.sha256,
            "size": snap.size,
        }

    # ------------------------------------------------------------------ candidates
    def candidates(self, limit: int | None = None) -> dict[str, Any]:
        """SOLIDWORKS parts and assemblies whose identical content sits in two or more
        projects, most widely shared first. Toolbox parts, and content that a file in the
        library section already has, are left out. Only files that share a size with another
        are hashed, and those whose size and time match their newest version are not read."""
        v = self.vault
        skipped: list[dict[str, Any]] = []
        by_size: dict[int, list[tuple[str, str, os.stat_result]]] = {}
        looked = 0
        for proj in v.projects():
            for rel, _full, st in v._walk(proj.path, skipped):
                if not rel.lower().endswith(_CANDIDATE_EXTENSIONS) or is_toolbox_path(rel.replace("/", "\\")):
                    continue
                looked += 1
                by_size.setdefault(st.st_size, []).append((rel, proj.path, st))
        groups = {size: files for size, files in by_size.items() if len({_key(p) for _r, p, _s in files}) > 1}
        index = v.store.newest_all() if groups else {}
        hashed = 0

        def sha_of(rel: str, st: os.stat_result) -> str | None:
            nonlocal hashed
            snap = index.get(_folded(rel))
            if snap is not None and (snap.size, snap.mtime_ns) == (st.st_size, st.st_mtime_ns):
                return snap.sha256
            try:
                sha = v._hash(v.absolute(rel))[0]
            except (OSError, SolidSeasError) as exc:
                from .vault import _reason

                skipped.append({"path": rel, "reason": _reason(exc)})
                return None
            hashed += 1
            return sha

        in_library: set[str] = set()
        section = self.section_path
        if groups and os.path.isdir(section) and not _is_link(section):
            for rel, _full, st in v._walk(self.section, skipped):
                if st.st_size in groups:
                    sha = sha_of(rel, st)
                    if sha is not None:
                        in_library.add(sha)
        by_sha: dict[str, list[tuple[str, str]]] = {}
        size_of: dict[str, int] = {}
        for size, files in groups.items():
            for rel, proj, st in files:
                sha = sha_of(rel, st)
                if sha is None or sha in in_library:
                    continue
                by_sha.setdefault(sha, []).append((rel, proj))
                size_of[sha] = size
        rows = []
        for sha, files in by_sha.items():
            projects = sorted({p for _r, p in files}, key=str.casefold)
            if len({_key(p) for p in projects}) < 2:
                continue
            files.sort(key=lambda f: (f[0].casefold(), f[0]))
            all_names = [r.rsplit("/", 1)[-1] for r, _p in files]
            names = sorted(set(all_names), key=str.casefold)
            rows.append(
                {
                    "name": min(names, key=lambda n: -all_names.count(n)),  # the commonest, then A to Z
                    "names": names,
                    "sha256": sha,
                    "size": size_of[sha],
                    "projects": len(projects),
                    "copies": [{"path": r, "project": p} for r, p in files],
                }
            )
        rows.sort(key=lambda r: (-r["projects"], -len(r["copies"]), r["name"].casefold(), r["sha256"]))
        total = len(rows)
        if limit is not None:
            rows = rows[:limit]
        skipped.sort(key=lambda s: s["path"])
        return {
            "documents": looked,
            "hashed": hashed,
            "total": total,
            "candidates": rows,
            "skipped": skipped,
        }

    # ------------------------------------------------------------------ add and list
    def _next_id(self, taken: set[str]) -> str:
        n = 0
        for ident in taken:
            m = AUTO_ID.match(ident)
            if m is not None:
                n = max(n, int(m.group(1)))
        while True:
            n += 1
            ident = f"SS-{n:05d}"
            if fold(ident) not in taken:
                return ident

    def add(
        self,
        path: str | os.PathLike,
        item: str | None = None,
        description: str | None = None,
        *,
        who: str | None = None,
    ) -> dict[str, Any]:
        """Make the file at ``path`` a library item. A file outside the library section is
        copied into the section's top folder (the source is not changed, and a file of
        that name there is never replaced); a file already in the section is recorded where
        it is. Its first version is stored, and the item record written, with ``item`` as
        its number (given, or the next ``SS-00001`` style number)."""
        from .vault import _refuse_link, _rename_new

        v = self.vault
        full = os.path.abspath(os.fspath(path))
        if item is not None and not valid_item_id(item):
            raise InvalidArgumentError(
                f"{item!r}: an item number is 1 to 40 letters, digits, dots, hyphens and underscores",
                detail={"parameter": "item"},
            )
        description = "" if description is None else description
        if not _valid_description(description):
            raise InvalidArgumentError(
                f"a description is one line of at most {MAX_DESCRIPTION} characters",
                detail={"parameter": "description"},
            )
        _refuse_link(full, "the file")
        if _regular(full) is None:
            raise FileNotFoundError(2, "the file does not exist", full)
        name = os.path.basename(full)
        try:
            rel = v.relative(full)
        except PathRefusedError:
            rel = None
        if rel is not None and any(p.startswith(".") for p in rel.split("/")):
            raise PathRefusedError(f"{full}: a hidden folder of the library", detail={"rule": "hidden"})
        if not v._tracked_rel(f"{self.section}/{name}"):
            raise InvalidArgumentError(
                f"{full}: not a file the vault tracks (a CAD file, or a drawing's PDF or DXF)",
                detail={"rule": "not_tracked", "parameter": "path"},
            )
        existing = self.items()
        taken = {fold(i.id) for i in existing}
        if item is not None and fold(item) in taken:
            raise OutputRefusedError(
                f"{item}: a library item already has that number", detail={"rule": "item_exists"}
            )
        entries: list[CheckinFile] = []
        if rel is not None and self.in_section(rel):
            check_folder_within(os.path.dirname(full), v.root)
            if any(_key(i.path) == _key(rel) for i in existing):
                raise OutputRefusedError(
                    f"{full}: already a library item", detail={"rule": "already_an_item"}
                )
            dest_rel, source, copied = rel, None, False
        else:
            if rel is not None:
                check_folder_within(os.path.dirname(full), v.root)
            folder = _make_folders(v.root, [self.section])
            dest = os.path.join(folder, name)
            dest_rel = f"{self.section}/{name}"
            if os.path.lexists(dest):
                raise OutputRefusedError(
                    f"{dest} already exists: the library section has a file of that name, which is "
                    "never replaced",
                    detail={"rule": "exists"},
                )
            if rel is not None:  # stored first, so its history says what was copied
                self._store(rel, None, entries)
            tmp, _sha, _n = _copy_file_to_temp(full, folder)
            try:
                _rename_new(tmp, dest)
            finally:
                if os.path.lexists(tmp):
                    os.remove(tmp)
            source, copied = rel, True
        ident = item
        note = None
        snap = None
        store = v.store
        store._make_root()
        folder = store._folder(store._folder(v.folder, "library", create=True), "items", create=True)
        for _attempt in range(100):
            ident = item if item is not None else self._next_id(taken)
            note = f"Added to the library as {ident}" + (f": {description}" if description else "")
            if snap is None:
                snap = self._store(dest_rel, note[: snapstore.MAX_NOTE], entries)
            record = Item(
                ident, _now(), dest_rel, description, snap.sha256, snap.size, snap.id, source, __version__
            )
            try:
                _write_record(folder, f"{ident}.json", record.to_json())
                break
            except OutputRefusedError:
                if item is not None:
                    raise OutputRefusedError(
                        f"{item}: a library item already has that number", detail={"rule": "item_exists"}
                    ) from None
                taken.add(fold(ident))
        else:  # pragma: no cover (a hundred numbers taken meanwhile)
            raise BusyError("no free item number was found: try again", detail={"rule": "item_numbers"})
        assert note is not None and snap is not None
        record = Item(
            *(getattr(record, f) for f in Item.__dataclass_fields__ if f != "record"), f"{ident}.json"
        )
        checkin = self._checkin(entries, note, who)
        return {
            "item": record.data(),
            "copied": copied,
            "version": self._version(dest_rel, snap),
            "checkin": None if checkin is None else checkin.brief(),
        }

    def list(self) -> dict[str, Any]:
        """Every item with its current version and the number of projects using it."""
        current = self.current_links()
        rows = []
        for item in self.items():
            state = self._item_state(item)
            links = [link for link in current.values() if fold(link.item) == fold(item.id)]
            snap = state.snapshot
            rows.append(
                {
                    **item.data(),
                    "exists": state.sha256 is not None,
                    "sha256": state.sha256,
                    "version": None if snap is None else self._version(item.path, snap),
                    "stored": state.stored,
                    "copies": len(links),
                    "projects": len({_key(link.project) for link in links}),
                }
            )
        return {"section": self.section, "items": rows}

    # ------------------------------------------------------------------ use
    def use(
        self,
        ident: str,
        project: str | os.PathLike,
        to: str | None = None,
        *,
        who: str | None = None,
    ) -> dict[str, Any]:
        """Copy the item's current version into the project (its top folder, or the
        folder ``to`` inside it, made when missing) and write a link record. A file of
        that name already there is never replaced: ``output_refused``, rule ``exists``."""
        from .vault import _rename_new

        v = self.vault
        item = self.item(ident)
        proj = self._project(project)
        parts = _subfolder(to)
        src = v.absolute(item.path)
        if _regular(src) is None:
            raise FileNotFoundError(2, f"library item {item.id}'s file is not in the library any more", src)
        name = item.path.rsplit("/", 1)[-1]
        folder_path = os.path.join(v.absolute(proj.path), *parts)
        dest = os.path.join(folder_path, name)
        if os.path.lexists(dest):
            raise OutputRefusedError(
                f"{dest} already exists: a copy never replaces a file (pdm library update brings a copy "
                "made from the library up to date)",
                detail={"rule": "exists"},
            )
        entries: list[CheckinFile] = []
        version = self._store(item.path, None, entries)
        folder_path = _make_folders(v.absolute(proj.path), parts)
        check_folder_within(folder_path, v.root)
        tmp = _copy_snapshot_to_temp(v.store, version, folder_path)
        try:
            _rename_new(tmp, dest)
        finally:
            if os.path.lexists(tmp):
                os.remove(tmp)
        dest_rel = v.relative(dest)
        number = self._version_number(item.path, version.id)
        note = f"Copied library item {item.id} v{number} into {proj.path}"
        self._store(dest_rel, note, entries)
        link = self._write_link(item, version, proj.path, dest_rel, "use")
        checkin = self._checkin(entries, note, who)
        return {
            "item": item.data(),
            "project": proj.data(),
            "path": dest_rel,
            "file": {"name": name, "path": dest},
            "version": self._version(item.path, version),
            "link": link.data(),
            "checkin": None if checkin is None else checkin.brief(),
        }

    # ------------------------------------------------------------------ updates
    def _copy_state(self, link: Link) -> tuple[str, str | None]:
        """``(state, sha256)`` of a link's copy now: ``gone``, ``unchanged`` or ``edited``."""
        full = self.vault.absolute(link.path)
        try:
            st = _regular(full)
        except (OSError, SolidSeasError):
            return "gone", None
        if st is None:
            return "gone", None
        if (st.st_size, st.st_mtime_ns) == (link.size, link.mtime_ns):
            return "unchanged", link.sha256
        sha = self.vault._hash(full)[0]
        return ("unchanged" if sha == link.sha256 else "edited"), sha

    def updates(self, project: str | os.PathLike | None = None, *, all_links: bool = False) -> dict[str, Any]:
        """Copies whose item has a newer version than the copy was made from (``behind``),
        and copies edited in their project since they were made (``edited``) or gone
        (``gone``). ``project`` limits it to one project; ``all_links`` lists the current
        copies too."""
        proj = None if project is None else self._project(project)
        items = {fold(i.id): i for i in self.items()}
        states: dict[str, _ItemState] = {}
        rows = []
        counts = {"current": 0, "behind": 0, "edited": 0, "gone": 0, "unknown_item": 0}
        for link in sorted(self.current_links().values(), key=lambda link: (link.path.casefold(), link.path)):
            if proj is not None and _key(link.project) != _key(proj.path):
                continue
            item = items.get(fold(link.item))
            if item is None:
                counts["unknown_item"] += 1
                continue
            state = states.get(fold(item.id))
            if state is None:
                try:
                    state = states[fold(item.id)] = self._item_state(item)
                except (OSError, SolidSeasError):
                    state = states[fold(item.id)] = _ItemState(self.vault.absolute(item.path), None, None)
            try:
                copy, sha = self._copy_state(link)
            except (OSError, SolidSeasError):
                copy, sha = "gone", None
            behind = state.sha256 is not None and state.sha256 != link.item_sha256
            for k, on in (("behind", behind), ("edited", copy == "edited"), ("gone", copy == "gone")):
                counts[k] += on
            if not behind and copy == "unchanged":
                counts["current"] += 1
                if not all_links:
                    continue
            newest = state.snapshot
            rows.append(
                {
                    "item": item.id,
                    "description": item.description,
                    "project": link.project,
                    "path": link.path,
                    "copied_utc": _brief_time(link.when),
                    "version": link.item_snapshot,
                    "number": self._version_number(item.path, link.item_snapshot),
                    "newest": None if newest is None or not state.stored else newest.id,
                    "newest_number": None
                    if newest is None or not state.stored
                    else self._version_number(item.path, newest.id),
                    "item_changed": state.sha256 is not None and not state.stored,
                    "behind": behind,
                    "copy": copy,
                    "sha256": sha,
                }
            )
        return {"scope": None if proj is None else proj.path, "counts": counts, "links": rows}

    def update(
        self,
        project: str | os.PathLike,
        ident: str,
        *,
        force: bool = False,
        who: str | None = None,
    ) -> dict[str, Any]:
        """Replace the project's copies of the item with its current version. Each copy is
        stored as a version first. A copy edited in the project since it was made is
        refused (``output_refused``, rule ``edited``) unless ``force``; a copy that is gone
        is left gone. Only files a link record says were copied from the item are written."""
        v = self.vault
        item = self.item(ident)
        proj = self._project(project)
        links = [
            link
            for link in self.current_links().values()
            if _key(link.project) == _key(proj.path) and fold(link.item) == fold(item.id)
        ]
        if not links:
            raise InvalidArgumentError(
                f"{proj.path} has no copy of library item {item.id} (pdm library use makes one)",
                detail={"rule": "not_linked", "parameter": "item"},
            )
        links.sort(key=lambda link: (link.path.casefold(), link.path))
        src = v.absolute(item.path)
        if _regular(src) is None:
            raise FileNotFoundError(2, f"library item {item.id}'s file is not in the library any more", src)
        looked = [(link, *self._copy_state(link)) for link in links]
        edited = [link.path for link, copy, _sha in looked if copy == "edited"]
        if edited and not force:
            raise OutputRefusedError(
                f"{', '.join(edited)}: edited in the project since it was copied from the library; "
                "pdm library update --force replaces it (it is stored as a version first)",
                detail={"rule": "edited"},
            )
        entries: list[CheckinFile] = []
        version = self._store(item.path, None, entries)
        number = self._version_number(item.path, version.id)
        note = f"Updated from library item {item.id} v{number}"
        rows = []
        for link, copy, sha in looked:
            row = {"path": link.path, "copy": copy, "written": False, "stored_first": None, "link": None}
            rows.append(row)
            if copy == "gone":
                continue
            full = v.absolute(link.path)
            folder = os.path.dirname(full)
            check_folder_within(folder, v.root)
            if sha == version.sha256:
                if link.item_sha256 != version.sha256:
                    row["link"] = self._write_link(item, version, proj.path, link.path, "update").data()
                continue
            first, new = v.store.add(full, note=f"stored before updating from library item {item.id}")
            row["stored_first"] = {"version": first.id, "new": new, "sha256": first.sha256}
            if new:
                entries.append(CheckinFile(link.path, first.sha256, first.size, first.id, True))
            before = _regular(full)
            tmp = _copy_snapshot_to_temp(v.store, version, folder)
            try:
                now = _regular(full)
                same = now is not None and before is not None and first.sha256 == sha
                if not same or (now.st_size, now.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
                    raise BusyError(
                        f"{full} changed while it was updated: try again once it is saved",
                        detail={"rule": "file_changing"},
                    )
                os.replace(tmp, full)
            finally:
                if os.path.lexists(tmp):
                    os.remove(tmp)
            self._store(link.path, note, entries)
            row["written"] = True
            row["link"] = self._write_link(item, version, proj.path, link.path, "update").data()
        checkin = self._checkin(entries, note, who)
        return {
            "item": item.data(),
            "project": proj.data(),
            "version": self._version(item.path, version),
            "copies": rows,
            "checkin": None if checkin is None else checkin.brief(),
        }

    # ------------------------------------------------------------------ check --fix
    def fix(self, project, plan: CopyPlan, *, who: str | None = None) -> dict[str, Any]:
        """Make the copies of a :func:`~solidseas.pdm.check.plan_copies` plan for one
        project: each a new file, never over an existing one. A copy whose source is a
        library item's file is recorded as a link. A copy that fails is listed, not raised."""
        from ..model import error_code
        from .vault import _rename_new

        v = self.vault
        items = {_key(i.path): i for i in self.items()}
        entries: list[CheckinFile] = []
        copied: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for c in plan.copies:
            src, dest = os.fspath(c.source), os.fspath(c.destination)
            try:
                folder = os.path.dirname(dest)
                check_folder_within(folder, v.absolute(project.path))
                if os.path.lexists(dest):
                    raise OutputRefusedError(f"{dest} already exists", detail={"rule": "exists"})
                try:
                    src_rel = v.relative(src)
                except PathRefusedError:
                    src_rel = None
                item = items.get(_key(src_rel)) if src_rel is not None else None
                version = None
                if src_rel is not None and v._tracked_rel(src_rel):
                    check_folder_within(os.path.dirname(src), v.root)
                    version = self._store(src_rel, None, entries)
                    tmp = _copy_snapshot_to_temp(v.store, version, folder)
                else:
                    tmp = _copy_file_to_temp(src, folder)[0]
                try:
                    _rename_new(tmp, dest)
                finally:
                    if os.path.lexists(tmp):
                        os.remove(tmp)
                dest_rel = v.relative(dest)
                note = f"Copied into {project.path} to make it self-contained"
                if v._tracked_rel(dest_rel):
                    self._store(dest_rel, note, entries)
                link = None
                if item is not None and version is not None:
                    link = self._write_link(item, version, project.path, dest_rel, "fix").data()
                copied.append(
                    {
                        "source": src,
                        "destination": dest,
                        "item": None if item is None else item.id,
                        "link": link,
                    }
                )
            except (OSError, SolidSeasError) as exc:
                failed.append(
                    {"source": src, "destination": dest, "code": error_code(exc), "message": str(exc)}
                )
        checkin = self._checkin(
            entries, f"Copied {len(copied)} files into {project.path} to make it self-contained", who
        )
        return {
            "copied": copied,
            "failed": failed,
            "checkin": None if checkin is None else checkin.brief(),
        }


# --------------------------------------------------------------------------- pdm check
def _finding_data(f) -> dict[str, Any]:
    return {
        "document": str(f.document),
        "key": f.key,
        "stored_path": f.stored_path,
        "file_name": f.file_name,
        "relation": f.relation,
        "result": f.result,
        "found": None if f.found is None else str(f.found),
        "place": f.place,
        "found_in": None if f.found_in is None else str(f.found_in),
        "status": f.status,
        "rule": f.rule,
        "identity": f.identity,
        "searched": f.searched,
        "toolbox": f.toolbox,
        "warnings": list(f.warnings),
    }


def _plan_data(plan: CopyPlan, items: dict[str, Item], vault) -> dict[str, Any]:
    def item_of(source: Path) -> str | None:
        try:
            rel = vault.relative(source)
        except PathRefusedError:
            return None
        it = items.get(_key(rel))
        return None if it is None else it.id

    def row(c) -> dict[str, Any]:
        return {
            "source": str(c.source),
            "destination": str(c.destination),
            "referenced_by": [str(p) for p in c.referenced_by],
            "place": c.place,
            "item": item_of(c.source),
        }

    return {
        "copies": [row(c) for c in plan.copies],
        "present": [row(c) for c in plan.present],
        "conflicts": [
            {
                "source": str(c.source),
                "destination": str(c.destination),
                "referenced_by": [str(p) for p in c.referenced_by],
                "reason": c.reason,
            }
            for c in plan.conflicts
        ],
    }


def _result_data(proj, res: CheckResult) -> dict[str, Any]:
    return {
        "project": proj.data(),
        "documents": res.documents,
        "counts": res.counts(),
        "self_contained": res.self_contained,
        "findings": [_finding_data(f) for f in res.problems()],
        "unreadable": [{"path": str(p), "error": e} for p, e in res.unreadable],
        "plan": None,
        "fix": None,
    }


def check(
    vault,
    path: str | os.PathLike | None = None,
    *,
    plan: bool = False,
    fix: bool = False,
    copy_toolbox: bool = False,
    who: str | None = None,
) -> dict[str, Any]:
    """``pdm check``: the self-contained check of one project (the one ``path`` is or
    lies in) or, when ``path`` is None or the library folder, of every project that is
    not archived. ``plan`` lists the copies that would make each self-contained; ``fix``
    makes them (new files only) and checks the project again."""
    lib = vault.library
    if path is None or os.path.normcase(os.path.abspath(os.fspath(path))) == os.path.normcase(vault.root):
        projects = [p for p in vault.projects() if not p.archived]
        scope = ""
    else:
        projects = [lib._project(path)]
        scope = projects[0].path
    library_folder = Path(lib.section_path)
    items = {_key(i.path): i for i in lib.items()} if (plan or fix) else {}
    rows = []
    for proj in projects:
        folder = Path(vault.absolute(proj.path))
        res = check_project(
            folder, library=library_folder if library_folder.is_dir() else None, copy_toolbox=copy_toolbox
        )
        row = _result_data(proj, res)
        if fix:
            p = plan_copies(res)
            done = lib.fix(proj, p, who=who)
            res = check_project(
                folder, library=library_folder if library_folder.is_dir() else None, copy_toolbox=copy_toolbox
            )
            row = _result_data(proj, res)
            row["fix"] = done
            row["plan"] = _plan_data(plan_copies(res), items, vault)
        elif plan:
            row["plan"] = _plan_data(plan_copies(res), items, vault)
        rows.append(row)
    return {
        "scope": scope,
        "copy_toolbox": copy_toolbox,
        "plan": plan or fix,
        "fix": fix,
        "projects": rows,
        "self_contained": sum(1 for r in rows if r["self_contained"]),
    }


__all__ = [
    "HOW",
    "Item",
    "Library",
    "Link",
    "check",
    "parse_item",
    "parse_link",
    "valid_item_id",
]
