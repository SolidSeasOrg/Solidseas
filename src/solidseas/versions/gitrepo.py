"""A Git repository's history of one file, read in pure Python (provisional).

``docs/VERSIONS.md`` section 3 has the design. SolidSeas reads the repository's own
files, read-only, and runs no program: not git, not a hook, not a filter, not a
signature or credential helper, whatever the repository's configuration names, and it
never reaches the network. It reads:

* the repository found from a file's folder upwards, on the same file system: a
  ``.git`` folder, or a ``.git`` file naming the folder of a linked worktree or a
  submodule (``commondir`` then names the shared one);
* ``HEAD``, loose references and ``packed-refs``;
* objects, loose or in packs (index version 2, deltas by offset and by id), in the
  SHA-1 or the SHA-256 object format, and in the object folders ``alternates`` names;
* ``shallow``, where a shallow clone's history stops;
* Git LFS pointer files, and the LFS objects already on this machine.

Every file is opened through :func:`~solidseas.formats.solidworks._io.open_readonly`
``within`` the folder that holds it, so no link below that folder is followed and a
cloud placeholder is never recalled. A ``.git`` file, ``commondir``, ``alternates`` or
``lfs.storage`` that sends the reading to a network location on another drive or share
than the work tree's is refused before anything there is touched (on Windows the open
alone would hand the share this account's credentials).

Refused, with ``format_not_supported``: references kept in the reftable format (rule
``reftable``), an extension of repository format 1 SolidSeas does not know
(``repository_extension``) and a pack index of version 1 (``pack_index_version``). An
object that is not on this machine (a shallow or partial clone, an LFS object that was
not fetched) is reported as missing and never fetched. A repository whose objects do
not decode is ``damaged_file`` (rule ``git_object``).
"""

from __future__ import annotations

import bisect
import heapq
import os
import re
import stat
import sys
import unicodedata
import zlib
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from ..errors import (
    FileTooLargeError,
    FormatNotSupportedError,
    LinkRefusedError,
    PathRefusedError,
    SolidSeasError,
    VersionUnavailableError,
)
from ..formats.solidworks._io import open_readonly
from ..resolve.names import fold

GIT_FOLDER = ".git"
DEFAULT_MAX_COMMITS = 20_000  # commits walked for one file's history
MAX_DELTA_CHAIN = 10_000  # deltas between an object and its base (git writes at most 50 by default)
MAX_SMALL_FILE = 1 << 20  # HEAD, a loose reference, a .git file, commondir, config, alternates
MAX_PACKED_REFS = 256 << 20
MAX_SHALLOW = 64 << 20
MAX_INDEX_BYTES = 1 << 30  # a pack index: 28 bytes an object (40 with SHA-256)
MAX_TREE_BYTES = 64 << 20  # a tree or a commit
MAX_ALTERNATES = 16
MAX_ALTERNATE_DEPTH = 5
MAX_DISCOVERY_DEPTH = 256
MAX_LFS_POINTER = 1024  # a pointer file is about 130 bytes; Git LFS writes none over 1024
CACHE_BYTES = 32 << 20  # objects kept decoded, trees and commits above all
CACHE_OBJECT_BYTES = 4 << 20  # larger objects are not kept

_OBJECT_TYPES = {1: "commit", 2: "tree", 3: "blob", 4: "tag"}
_OFS_DELTA, _REF_DELTA = 6, 7
_FILE_MODES = (b"100644", b"100755", b"100664")
_KNOWN_EXTENSIONS = frozenset(
    {
        "noop",
        "noop-v1",
        "preciousobjects",
        "partialclone",
        "worktreeconfig",
        "objectformat",
        "compatobjectformat",
        "refstorage",
    }
)
_HEX = re.compile(r"[0-9a-f]+\Z")
_REFNAME_BAD = re.compile(r"[\x00-\x20\x7f~^:?*\[\\]|\.\.|@\{|//")
_PERSON = re.compile(rb"^(.*?) ?<[^<>]*> (-?\d{1,19}) ([+-]\d{4})$")
_LFS_VERSIONS = (b"version https://git-lfs.github.com/spec/v1", b"version https://hawser.github.com/spec/v1")
_LFS_OID = re.compile(rb"^oid sha256:([0-9a-f]{64})$", re.M)
_LFS_SIZE = re.compile(rb"^size (\d{1,19})$", re.M)
_CASE_INSENSITIVE = sys.platform in ("win32", "darwin")
_REFTABLE = "the repository keeps its references in the reftable format, which SolidSeas does not read yet"


class GitObjectError(SolidSeasError):
    """The repository's objects or references do not decode: ``damaged_file``, rule
    ``git_object``."""

    code = "damaged_file"

    def __init__(self, message: str) -> None:
        super().__init__(message, detail={"rule": "git_object"})


class MissingObjectError(VersionUnavailableError):
    """An object the history needs is not on this machine (a shallow or partial clone):
    ``version_unavailable``, rule ``object_missing``."""

    def __init__(self, oid: str) -> None:
        super().__init__(f"object {oid} is not in this repository", detail={"rule": "object_missing"})
        self.oid = oid


def _unsupported(message: str, rule: str) -> FormatNotSupportedError:
    return FormatNotSupportedError(message, detail={"rule": rule})


# --------------------------------------------------------------------------- results
@dataclass(frozen=True)
class Commit:
    """One commit: its tree, its parents, who wrote it and when (Unix seconds and the
    zone's offset in minutes) and the first line of its message. The author's e-mail
    address is not kept."""

    oid: str
    tree: str
    parents: tuple[str, ...]
    author: str | None
    authored: int | None
    authored_offset: int | None
    committed: int | None
    committed_offset: int | None
    subject: str


@dataclass(frozen=True)
class LfsPointer:
    """A Git LFS pointer: the SHA-256 and size of the content it stands for."""

    oid: str
    size: int


@dataclass(frozen=True)
class FileVersion:
    """One commit that changed the file: ``status`` is ``added``, ``modified`` or
    ``deleted`` (then ``blob`` is None). ``size`` is the blob's (None when the object
    is not on this machine) and ``lfs`` the pointer when the blob is one."""

    commit: Commit
    status: str
    blob: str | None
    size: int | None = None
    lfs: LfsPointer | None = None
    path: str = ""


@dataclass
class History:
    """A file's versions, newest first, and how the walk went."""

    versions: list[FileVersion] = field(default_factory=list)
    walked: int = 0
    truncated: bool = False
    incomplete: bool = False  # a parent was not on this machine (a shallow or partial clone)


# --------------------------------------------------------------------------- small helpers
def _is_link(path: str) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    if sys.platform == "win32":
        from ..walk import reparse_link

        attrs = getattr(st, "st_file_attributes", 0)
        return reparse_link(attrs, getattr(st, "st_reparse_tag", 0)) is not None
    return False


def _read(path: str, within: str, limit: int, *, prefix: bool = False) -> bytes:
    """The whole file at ``path`` below ``within`` (no link below it followed), at most
    ``limit`` bytes; more raises :class:`GitObjectError`. With ``prefix`` only its first
    ``limit`` bytes are read."""
    with open_readonly(path, within=within) as fh:
        data = fh.read(limit if prefix else limit + 1)
    if len(data) > limit:
        raise GitObjectError(f"{os.path.basename(path)} is larger than SolidSeas reads ({limit:,} bytes)")
    return data


def lstat_within(base: str, parts: tuple[str, ...]) -> os.stat_result | None:
    """``lstat`` of ``base`` joined with ``parts``, each folder on the way checked first,
    so no link below ``base`` is followed (one raises :class:`LinkRefusedError`); None
    when something on the way is missing."""
    cur = base
    st = None
    for i, name in enumerate(parts):
        cur = os.path.join(cur, name)
        try:
            st = os.lstat(cur)
        except OSError:
            return None
        if _is_link(cur):
            raise LinkRefusedError(
                f"{cur}: reached through a link, which is never followed", detail={"rule": "link_in_path"}
            )
        if i < len(parts) - 1 and not stat.S_ISDIR(st.st_mode):
            return None
    return st


def _anchor(path: str) -> str:
    import ntpath

    return os.path.normcase(ntpath.splitdrive(path)[0]) if os.name == "nt" else ""


def _check_target(target: str, base: str, what: str) -> str:
    """``target`` (absolute) when the repository may read there: never a device or
    long-path prefix, and on Windows never a network location on another drive or share
    than ``base``, decided from the text and the drive's type before anything there is
    opened."""
    full = os.path.abspath(target)
    # judged on the text as written too: Windows reads \??\UNC\host\share as a share
    if any(t.replace("/", "\\").startswith(("\\\\?\\", "\\\\.\\", "\\??\\")) for t in (target, full)):
        raise PathRefusedError(
            f"{what} names a device path, which is never read", detail={"rule": "device_path"}
        )
    if os.name == "nt" and _anchor(full) != _anchor(base):
        from ..catalog.store import is_network

        if is_network(full):
            raise PathRefusedError(
                f"{what} names a network location outside the repository's own drive, which is never read",
                detail={"rule": "network_location"},
            )
    return full


def _text_line(data: bytes) -> str:
    return data.decode("utf-8", "replace").strip()


def _check_refname(name: str) -> str:
    """``name`` when it is a reference name SolidSeas may look up as a file below the
    repository: ``HEAD`` or ``refs/...`` with no component that leaves its folder."""
    if name == "HEAD":
        return name
    if (
        not name.startswith("refs/")
        or name.endswith(("/", ".", ".lock"))
        or _REFNAME_BAD.search(name)
        or any(not part or part.startswith(".") for part in name.split("/"))
        or len(name) > 1024
    ):
        raise GitObjectError("a reference names something that is not a reference")
    return name


def parse_config(text: str) -> dict[str, str]:
    """The keys of a Git configuration file as ``section.key`` (and
    ``section.subsection.key``), lower case but for subsections, last value wins.
    Includes are not followed: only the repository's own file says what format it has."""
    out: dict[str, str] = {}
    section: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        if line.startswith("["):
            end = line.find("]")
            if end < 0:
                section = None
                continue
            head = line[1:end].strip()
            if '"' in head:
                name, _, sub = head.partition(" ")
                section = name.strip().lower() + "." + sub.strip().strip('"')
            else:
                section = head.lower()
            line = line[end + 1 :].strip()
            if not line or line[0] in "#;":
                continue
        if section is None:
            continue
        key, eq, value = line.partition("=")
        key = key.strip().lower()
        if not key:
            continue
        out[f"{section}.{key}"] = _config_value(value) if eq else "true"
    return out


def _config_value(value: str) -> str:
    out = []
    quoted = False
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == '"':
            quoted = not quoted
        elif ch == "\\" and i + 1 < len(value):
            i += 1
            out.append({"n": "\n", "t": "\t", "b": "\b"}.get(value[i], value[i]))
        elif ch in "#;" and not quoted:
            break
        else:
            out.append(ch)
        i += 1
    return "".join(out).strip()


def parse_lfs_pointer(data: bytes) -> LfsPointer | None:
    """The pointer ``data`` holds when it is a Git LFS pointer file, else None."""
    if len(data) > MAX_LFS_POINTER or not data.startswith(_LFS_VERSIONS):
        return None
    oid = _LFS_OID.search(data)
    size = _LFS_SIZE.search(data)
    if oid is None or size is None:
        return None
    return LfsPointer(oid.group(1).decode("ascii"), int(size.group(1)))


def _varint_le(data: bytes, pos: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        if pos >= len(data) or shift > 63:
            raise GitObjectError("a delta's size does not decode")
        c = data[pos]
        pos += 1
        value |= (c & 0x7F) << shift
        shift += 7
        if not c & 0x80:
            return value, pos


def apply_delta(base: bytes, delta: bytes, limit: int) -> bytes:
    """``delta`` applied to ``base`` (git's copy and insert instructions); the result may
    not exceed ``limit`` bytes."""
    src_size, pos = _varint_le(delta, 0)
    dst_size, pos = _varint_le(delta, pos)
    if src_size != len(base):
        raise GitObjectError("a delta does not fit its base")
    if dst_size > limit:
        raise FileTooLargeError(
            "a version of the file is larger than the configured maximum",
            detail={"limit": limit, "value": dst_size},
        )
    out = bytearray()
    n = len(delta)
    while pos < n:
        c = delta[pos]
        pos += 1
        if c & 0x80:
            off = size = 0
            for i in range(4):
                if c & (1 << i):
                    if pos >= n:
                        raise GitObjectError("a delta ends inside a copy")
                    off |= delta[pos] << (8 * i)
                    pos += 1
            for i in range(3):
                if c & (0x10 << i):
                    if pos >= n:
                        raise GitObjectError("a delta ends inside a copy")
                    size |= delta[pos] << (8 * i)
                    pos += 1
            if size == 0:
                size = 0x10000
            if off + size > len(base):
                raise GitObjectError("a delta copies from beyond its base")
            out += base[off : off + size]
        elif c:
            if pos + c > n:
                raise GitObjectError("a delta ends inside an insert")
            out += delta[pos : pos + c]
            pos += c
        else:
            raise GitObjectError("a delta holds a reserved instruction")
        if len(out) > dst_size:
            raise GitObjectError("a delta makes more than it says")
    if len(out) != dst_size:
        raise GitObjectError("a delta makes less than it says")
    return bytes(out)


def _inflate(data: bytes | memoryview, size: int, what: str) -> bytes:
    """Exactly ``size`` bytes inflated from the zlib stream at the start of ``data``."""
    d = zlib.decompressobj()
    try:
        out = d.decompress(data, size + 1)
    except zlib.error:
        raise GitObjectError(f"{what} does not inflate") from None
    if len(out) != size:
        raise GitObjectError(f"{what} inflates to another size than it says")
    return out


# --------------------------------------------------------------------------- packs
class _Pack:
    """One pack and its index (version 2)."""

    def __init__(self, idx_path: str, pack_path: str, within: str, hash_len: int) -> None:
        self.pack_path = pack_path
        self.within = within
        self.hash_len = hash_len
        idx = _read(idx_path, within, MAX_INDEX_BYTES)
        if idx[:4] != b"\xfftOc":
            raise _unsupported(
                "a pack index of version 1, which SolidSeas does not read", "pack_index_version"
            )
        version = int.from_bytes(idx[4:8], "big")
        if version != 2:
            raise _unsupported(f"a pack index of version {version}", "pack_index_version")
        fan = idx[8 : 8 + 1024]
        if len(fan) != 1024:
            raise GitObjectError("a pack index is cut short")
        self.fanout = [int.from_bytes(fan[4 * i : 4 * i + 4], "big") for i in range(256)]
        n = self.fanout[255]
        if any(self.fanout[i] > self.fanout[i + 1] for i in range(255)):
            raise GitObjectError("a pack index's fan-out goes down")
        names_at = 8 + 1024
        offsets_at = names_at + n * hash_len + n * 4
        large_at = offsets_at + n * 4
        if len(idx) < large_at + 2 * hash_len:
            raise GitObjectError("a pack index is cut short")
        self.count = n
        self.names = idx[names_at : names_at + n * hash_len]
        small = idx[offsets_at:large_at]
        large = idx[large_at : len(idx) - 2 * hash_len]
        offsets = []
        for i in range(n):
            v = int.from_bytes(small[4 * i : 4 * i + 4], "big")
            if v & 0x80000000:
                k = v & 0x7FFFFFFF
                if 8 * k + 8 > len(large):
                    raise GitObjectError("a pack index's large offset is missing")
                v = int.from_bytes(large[8 * k : 8 * k + 8], "big")
            offsets.append(v)
        self.offsets = offsets
        self._fh = open_readonly(pack_path, within=within)
        head = self._fh.read(12)
        if head[:4] != b"PACK" or int.from_bytes(head[4:8], "big") not in (2, 3):
            self._fh.close()
            raise GitObjectError("a pack does not start as a pack")
        self._fh.seek(0, os.SEEK_END)
        self.size = self._fh.tell()
        self._ends = sorted(set(offsets) | {self.size - hash_len})
        if self._ends[0] < 12 or self._ends[-1] > self.size:
            self._fh.close()
            raise GitObjectError("a pack index points outside its pack")

    def close(self) -> None:
        self._fh.close()

    def find(self, oid: bytes) -> int | None:
        """The offset of ``oid`` in this pack, or None."""
        first = oid[0]
        lo = self.fanout[first - 1] if first else 0
        hi = self.fanout[first]
        hl = self.hash_len
        names = self.names
        while lo < hi:
            mid = (lo + hi) // 2
            here = names[mid * hl : mid * hl + hl]
            if here == oid:
                return self.offsets[mid]
            if here < oid:
                lo = mid + 1
            else:
                hi = mid
        return None

    def entry(self, offset: int) -> bytes:
        """The bytes of the entry at ``offset``, up to where the next one starts."""
        k = bisect.bisect_right(self._ends, offset)
        if k >= len(self._ends) or offset < 12:
            raise GitObjectError("a pack entry lies outside its pack")
        end = self._ends[k]
        self._fh.seek(offset)
        data = self._fh.read(end - offset)
        if len(data) != end - offset:
            raise GitObjectError("a pack is cut short")
        return data


def _entry_header(data: bytes) -> tuple[int, int, int]:
    """``(type, size, position after the header)`` of a pack entry."""
    if not data:
        raise GitObjectError("a pack entry is empty")
    c = data[0]
    typ = (c >> 4) & 7
    size = c & 15
    shift = 4
    pos = 1
    while c & 0x80:
        if pos >= len(data) or shift > 63:
            raise GitObjectError("a pack entry's header does not decode")
        c = data[pos]
        pos += 1
        size |= (c & 0x7F) << shift
        shift += 7
    return typ, size, pos


def _ofs_delta_base(data: bytes, pos: int) -> tuple[int, int]:
    if pos >= len(data):
        raise GitObjectError("a delta's base does not decode")
    c = data[pos]
    pos += 1
    ofs = c & 0x7F
    while c & 0x80:
        if pos >= len(data) or ofs > 1 << 56:
            raise GitObjectError("a delta's base does not decode")
        c = data[pos]
        pos += 1
        ofs = ((ofs + 1) << 7) | (c & 0x7F)
    return ofs, pos


# --------------------------------------------------------------------------- the object store
class _ObjectStore:
    """The objects of one ``objects`` folder and those of its alternates."""

    def __init__(self, folder: str, hash_len: int, depth: int = 0) -> None:
        self.folder = folder
        self.hash_len = hash_len
        self._packs: list[_Pack] | None = None
        self.alternates: list[_ObjectStore] = []
        if depth < MAX_ALTERNATE_DEPTH:
            for alt in self._alternate_folders():
                try:
                    self.alternates.append(_ObjectStore(alt, hash_len, depth + 1))
                except OSError:
                    continue  # an alternate that is gone: its objects are missing, which is reported

    def _alternate_folders(self) -> list[str]:
        path = os.path.join(self.folder, "info", "alternates")
        try:
            text = _read(path, self.folder, MAX_SMALL_FILE).decode("utf-8", "replace")
        except FileNotFoundError:
            return []
        out = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith('"') and line.endswith('"') and len(line) > 1:
                line = line[1:-1]
            target = line if os.path.isabs(line) else os.path.join(self.folder, line)
            target = _check_target(target, self.folder, "the repository's alternates")
            if not os.path.isdir(target) or _is_link(target):
                continue
            out.append(target)
            if len(out) >= MAX_ALTERNATES:
                break
        return out

    def packs(self, *, refresh: bool = False) -> list[_Pack]:
        if self._packs is not None and not refresh:
            return self._packs
        old = {p.pack_path: p for p in self._packs or ()}
        packs: list[_Pack] = []
        folder = os.path.join(self.folder, "pack")
        if _is_link(folder):  # checked before listing: listing a link would go where it leads
            raise LinkRefusedError(
                "the repository's pack folder is a link, which is never followed",
                detail={"rule": "link_in_path"},
            )
        try:
            names = sorted(os.listdir(folder))
        except (FileNotFoundError, NotADirectoryError):
            names = []
        for name in names:
            if not (name.startswith("pack-") and name.endswith(".idx")):
                continue
            pack_path = os.path.join(folder, name[:-4] + ".pack")
            if pack_path in old:
                packs.append(old.pop(pack_path))
                continue
            try:
                packs.append(_Pack(os.path.join(folder, name), pack_path, self.folder, self.hash_len))
            except FileNotFoundError:
                continue  # a pack being written or removed by git right now
        for p in old.values():
            p.close()
        self._packs = packs
        return packs

    def close(self) -> None:
        for p in self._packs or ():
            p.close()
        self._packs = []
        for a in self.alternates:
            a.close()

    def loose_path(self, hexid: str) -> str:
        return os.path.join(self.folder, hexid[:2], hexid[2:])


# --------------------------------------------------------------------------- the repository
class Repository:
    """A repository found from a file (:func:`find_repository`), read-only. Close it
    (or use it as a context manager) to release the pack files it holds open."""

    def __init__(self, work_tree: str, git_dir: str, common_dir: str) -> None:
        self.work_tree = work_tree
        self.git_dir = git_dir
        self.common_dir = common_dir
        try:
            config = parse_config(
                _read(os.path.join(common_dir, "config"), common_dir, MAX_SMALL_FILE).decode(
                    "utf-8", "replace"
                )
            )
        except FileNotFoundError:
            config = {}
        self.config = config
        version = config.get("core.repositoryformatversion", "0").strip() or "0"
        if version not in ("0", "1"):
            raise _unsupported(f"repository format version {version}", "repository_extension")
        extensions = {k.split(".", 1)[1]: v for k, v in config.items() if k.startswith("extensions.")}
        if version == "1":
            unknown = sorted(set(extensions) - _KNOWN_EXTENSIONS)
            if unknown:
                raise _unsupported(
                    f"the repository uses the extension {unknown[0]}, which SolidSeas does not read",
                    "repository_extension",
                )
        if extensions.get("refstorage", "files").lower() != "files":
            raise _unsupported(_REFTABLE, "reftable")
        fmt = extensions.get("objectformat", "sha1").lower() if version == "1" else "sha1"
        if fmt not in ("sha1", "sha256"):
            raise _unsupported(f"the object format {fmt}", "repository_extension")
        self.object_format = fmt
        self.hash_len = 20 if fmt == "sha1" else 32
        objects = os.path.join(common_dir, "objects")
        if _is_link(objects):
            raise LinkRefusedError(
                "the repository's objects folder is a link, which is never followed",
                detail={"rule": "link_in_path"},
            )
        self.store = _ObjectStore(objects, self.hash_len)
        self.shallow = self._read_shallow()
        # a partial clone: older git names its remote in extensions.partialClone, newer marks
        # the remote itself as a promisor
        self.partial = "partialclone" in extensions or any(
            k.startswith("remote.") and k.endswith(".promisor") and v.lower() in ("true", "yes", "on", "1")
            for k, v in config.items()
        )
        self._cache: OrderedDict[str, tuple[str, bytes]] = OrderedDict()
        self._cache_bytes = 0
        self._commits: dict[str, Commit] = {}
        self._entries: OrderedDict[tuple[str, tuple[str, ...]], tuple[bytes, str] | None] = OrderedDict()

    # ------------------------------------------------------------------ plumbing
    def __enter__(self) -> Repository:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        self.store.close()

    def _read_shallow(self) -> frozenset[str]:
        try:
            text = _read(os.path.join(self.common_dir, "shallow"), self.common_dir, MAX_SHALLOW)
        except FileNotFoundError:
            return frozenset()
        return frozenset(line for line in text.decode("ascii", "replace").split() if self._is_oid(line))

    def _is_oid(self, text: str) -> bool:
        return len(text) == 2 * self.hash_len and bool(_HEX.match(text))

    def lfs_folder(self) -> str:
        """Where this repository's Git LFS objects are (``lfs.storage``, else ``lfs`` in
        the shared folder)."""
        custom = self.config.get("lfs.storage")
        if custom:
            target = custom if os.path.isabs(custom) else os.path.join(self.common_dir, custom)
            return _check_target(target, self.common_dir, "lfs.storage")
        return os.path.join(self.common_dir, "lfs")

    # ------------------------------------------------------------------ references
    def head(self) -> tuple[str | None, str | None]:
        """``(branch reference, commit id)``: the reference HEAD names (None when HEAD
        holds a commit id itself) and the commit it resolves to (None before the first
        commit)."""
        text = _text_line(_read(os.path.join(self.git_dir, "HEAD"), self.git_dir, MAX_SMALL_FILE))
        if text.startswith("ref:"):
            name = text[4:].strip()
            if name == "refs/heads/.invalid":  # what a reftable repository's HEAD holds
                raise _unsupported(_REFTABLE, "reftable")
            return name, self.resolve_ref(name)
        if self._is_oid(text):
            return None, text
        raise GitObjectError("HEAD holds neither a reference nor a commit id")

    def resolve_ref(self, name: str, depth: int = 0) -> str | None:
        """The commit a reference names, following symbolic references; None when it
        does not exist (a branch with no commit yet)."""
        if depth > 10:
            raise GitObjectError("references point at each other in a loop")
        name = _check_refname(name)
        per_worktree = name == "HEAD" or name.startswith(
            ("refs/bisect/", "refs/worktree/", "refs/rewritten/")
        )
        base = self.git_dir if per_worktree else self.common_dir
        path = os.path.join(base, *name.split("/"))
        try:
            text = _text_line(_read(path, base, MAX_SMALL_FILE))
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
            text = None
        if text is not None:
            if text.startswith("ref:"):
                return self.resolve_ref(text[4:].strip(), depth + 1)
            if self._is_oid(text):
                return text
            raise GitObjectError("a reference holds neither a reference nor a commit id")
        return self._packed_ref(name)

    def _packed_ref(self, name: str) -> str | None:
        path = os.path.join(self.common_dir, "packed-refs")
        try:
            data = _read(path, self.common_dir, MAX_PACKED_REFS)
        except FileNotFoundError:
            return None
        want = (" " + name).encode("utf-8")
        for line in data.split(b"\n"):
            line = line.rstrip(b"\r")
            if line.endswith(want) and not line.startswith((b"#", b"^")):
                oid = line[: -len(want)].decode("ascii", "replace")
                if self._is_oid(oid):
                    return oid
        return None

    # ------------------------------------------------------------------ objects
    def _remember(self, key: str, value: tuple[str, bytes]) -> None:
        size = len(value[1])
        if size > CACHE_OBJECT_BYTES:
            return
        old = self._cache.pop(key, None)
        if old is not None:
            self._cache_bytes -= len(old[1])
        self._cache[key] = value
        self._cache_bytes += size
        while self._cache_bytes > CACHE_BYTES and self._cache:
            _k, old = self._cache.popitem(last=False)
            self._cache_bytes -= len(old[1])

    def _locate(self, raw: bytes, store: _ObjectStore, *, refresh: bool) -> tuple[_ObjectStore, Any] | None:
        for p in store.packs(refresh=refresh):
            off = p.find(raw)
            if off is not None:
                return store, (p, off)
        hexid = raw.hex()
        path = store.loose_path(hexid)
        if os.path.isfile(path):
            return store, path
        for alt in store.alternates:
            got = self._locate(raw, alt, refresh=refresh)
            if got is not None:
                return got
        return None

    def _find(self, oid: str) -> tuple[_ObjectStore, Any]:
        if not self._is_oid(oid):
            raise GitObjectError("an object id is not one")
        raw = bytes.fromhex(oid)
        got = self._locate(raw, self.store, refresh=False)
        if got is None:  # git may have packed it since the packs were listed
            got = self._locate(raw, self.store, refresh=True)
        if got is None:
            raise MissingObjectError(oid)
        return got

    def has_object(self, oid: str) -> bool:
        try:
            self._find(oid)
        except MissingObjectError:
            return False
        return True

    def _read_loose(self, store: _ObjectStore, path: str, limit: int, *, header_only: bool = False):
        if header_only:  # the header is in the first few bytes, whatever the object's size
            compressed = _read(path, store.folder, 4096, prefix=True)
        else:  # zlib adds a little to data it cannot shrink
            compressed = _read(path, store.folder, limit + (1 << 20) + limit // 2)
        d = zlib.decompressobj()
        try:
            head = d.decompress(compressed, 64)
        except zlib.error:
            raise GitObjectError("a loose object does not inflate") from None
        nul = head.find(b"\0")
        if nul < 0:
            raise GitObjectError("a loose object has no header")
        typ, _, size_text = head[:nul].partition(b" ")
        if typ not in (b"commit", b"tree", b"blob", b"tag") or not size_text.isdigit():
            raise GitObjectError("a loose object's header does not decode")
        size = int(size_text)
        kind = typ.decode("ascii")
        if header_only:
            return kind, size
        if size > limit:
            raise FileTooLargeError(
                "a version of the file is larger than the configured maximum",
                detail={"limit": limit, "value": size},
            )
        try:
            rest = d.decompress(d.unconsumed_tail, size + 1 - (len(head) - nul - 1))
        except zlib.error:
            raise GitObjectError("a loose object does not inflate") from None
        body = head[nul + 1 :] + rest
        if len(body) != size:
            raise GitObjectError("a loose object inflates to another size than it says")
        return kind, body

    def object_info(self, oid: str) -> tuple[str, int]:
        """``(type, size)`` of an object, reading as little of it as it can."""
        store, where = self._find(oid)
        if isinstance(where, str):
            return self._read_loose(store, where, 0, header_only=True)
        pack, offset = where
        data = pack.entry(offset)
        typ, size, pos = _entry_header(data)
        if typ in _OBJECT_TYPES:
            return _OBJECT_TYPES[typ], size
        base_type = self._base_type(pack, offset)
        if typ == _OFS_DELTA:
            _ofs, pos = _ofs_delta_base(data, pos)
        elif typ == _REF_DELTA:
            pos += self.hash_len
        else:
            raise GitObjectError("a pack entry has an unknown type")
        d = zlib.decompressobj()
        try:
            head = d.decompress(data[pos:], 32)
        except zlib.error:
            raise GitObjectError("a delta does not inflate") from None
        _src, at = _varint_le(head, 0)
        dst, _at = _varint_le(head, at)
        return base_type, dst

    def _base_type(self, pack: _Pack, offset: int) -> str:
        for _ in range(MAX_DELTA_CHAIN):
            data = pack.entry(offset)
            typ, _size, pos = _entry_header(data)
            if typ in _OBJECT_TYPES:
                return _OBJECT_TYPES[typ]
            if typ == _OFS_DELTA:
                ofs, _pos = _ofs_delta_base(data, pos)
                if not 0 < ofs < offset:
                    raise GitObjectError("a delta's base lies outside its pack")
                offset -= ofs
            elif typ == _REF_DELTA:
                base = data[pos : pos + self.hash_len].hex()
                store, where = self._find(base)
                if isinstance(where, str):
                    return self._read_loose(store, where, 0, header_only=True)[0]
                pack, offset = where
            else:
                raise GitObjectError("a pack entry has an unknown type")
        raise GitObjectError("a chain of deltas is too long")

    def read_object(self, oid: str, *, limit: int) -> tuple[str, bytes]:
        """``(type, content)`` of an object of at most ``limit`` bytes."""
        hit = self._cache.get(oid)
        if hit is not None:
            self._cache.move_to_end(oid)
            return hit
        store, where = self._find(oid)
        if isinstance(where, str):
            got = self._read_loose(store, where, limit)
        else:
            got = self._read_packed(where[0], where[1], limit)
        self._remember(oid, got)
        return got

    def _read_packed(self, pack: _Pack, offset: int, limit: int) -> tuple[str, bytes]:
        # (cache key, entry bytes, where its delta starts, delta size), from the object down
        chain: list[tuple[str, bytes, int, int]] = []
        base: tuple[str, bytes] | None = None
        while base is None:
            if len(chain) > MAX_DELTA_CHAIN:
                raise GitObjectError("a chain of deltas is too long")
            key = f"{pack.pack_path}\0{offset}"
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                base = cached
                break
            data = pack.entry(offset)
            typ, size, pos = _entry_header(data)
            if typ in _OBJECT_TYPES:
                if size > limit:
                    raise FileTooLargeError(
                        "a version of the file is larger than the configured maximum",
                        detail={"limit": limit, "value": size},
                    )
                base = (_OBJECT_TYPES[typ], _inflate(memoryview(data)[pos:], size, "a pack entry"))
                self._remember(key, base)
            elif typ == _OFS_DELTA:
                ofs, pos = _ofs_delta_base(data, pos)
                if not 0 < ofs < offset:
                    raise GitObjectError("a delta's base lies outside its pack")
                chain.append((key, data, pos, size))
                offset -= ofs
            elif typ == _REF_DELTA:
                base_id = data[pos : pos + self.hash_len].hex()
                chain.append((key, data, pos + self.hash_len, size))
                store, where = self._find(base_id)
                if isinstance(where, str):
                    base = self._read_loose(store, where, max(limit, MAX_TREE_BYTES))
                else:
                    pack, offset = where
            else:
                raise GitObjectError("a pack entry has an unknown type")
        kind, content = base
        for key, data, pos, size in reversed(chain):
            if size > (1 << 31):
                raise GitObjectError("a delta is larger than SolidSeas reads")
            delta = _inflate(memoryview(data)[pos:], size, "a delta")
            content = apply_delta(content, delta, limit if kind == "blob" else MAX_TREE_BYTES)
            # every object on the way is kept (small ones): the next object of a chain that
            # shares this part of it starts from here instead of from the chain's base
            self._remember(key, (kind, content))
        return kind, content

    def read_blob(self, oid: str, *, limit: int) -> bytes:
        kind, data = self.read_object(oid, limit=limit)
        if kind != "blob":
            raise GitObjectError("an object the tree calls a file is not one")
        return data

    # ------------------------------------------------------------------ commits and trees
    def commit(self, oid: str) -> Commit:
        got = self._commits.get(oid)
        if got is not None:
            return got
        kind, data = self.read_object(oid, limit=MAX_TREE_BYTES)
        if kind != "commit":
            raise GitObjectError("a commit id names something that is not a commit")
        got = parse_commit(oid, data, self.hash_len)
        if len(self._commits) > 200_000:
            self._commits.clear()
        self._commits[oid] = got
        return got

    def _tree(self, oid: str) -> bytes:
        kind, data = self.read_object(oid, limit=MAX_TREE_BYTES)
        if kind != "tree":
            raise GitObjectError("a tree id names something that is not a tree")
        return data

    def tree_entries(self, oid: str) -> Iterator[tuple[bytes, str, str]]:
        """``(mode, name, object id)`` of each entry of a tree."""
        data = self._tree(oid)
        hl = self.hash_len
        i = 0
        n = len(data)
        while i < n:
            sp = data.find(b" ", i)
            nul = data.find(b"\0", sp + 1) if sp >= 0 else -1
            if sp < 0 or nul < 0 or nul + 1 + hl > n:
                raise GitObjectError("a tree does not decode")
            yield (
                data[i:sp],
                data[sp + 1 : nul].decode("utf-8", "surrogateescape"),
                data[nul + 1 : nul + 1 + hl].hex(),
            )
            i = nul + 1 + hl

    def _child(self, tree: str, name: str) -> tuple[bytes, str] | None:
        """The entry ``name`` of a tree: exactly, or on Windows and macOS by case and
        Unicode normalisation when exactly one entry matches that way."""
        data = self._tree(tree)
        hl = self.hash_len
        want = name.encode("utf-8", "surrogateescape")
        i = 0
        n = len(data)
        while i < n:  # the names compared as bytes: a history looks up one name in many trees
            sp = data.find(b" ", i)
            nul = data.find(b"\0", sp + 1) if sp >= 0 else -1
            if sp < 0 or nul < 0 or nul + 1 + hl > n:
                raise GitObjectError("a tree does not decode")
            if data[sp + 1 : nul] == want:
                return data[i:sp], data[nul + 1 : nul + 1 + hl].hex()
            i = nul + 1 + hl
        if not _CASE_INSENSITIVE:
            return None
        folded = fold(unicodedata.normalize("NFC", name))
        loose = [
            (mode, oid)
            for mode, entry, oid in self.tree_entries(tree)
            if fold(unicodedata.normalize("NFC", entry)) == folded
        ]
        return loose[0] if len(loose) == 1 else None

    def entry(self, tree: str, parts: tuple[str, ...]) -> tuple[bytes, str] | None:
        """``(mode, object id)`` at the path ``parts`` below ``tree``, or None."""
        key = (tree, parts)
        if key in self._entries:
            self._entries.move_to_end(key)
            return self._entries[key]
        got = self._child(tree, parts[0])
        if got is not None and len(parts) > 1:
            got = self.entry(got[1], parts[1:]) if got[0] == b"40000" else None
        self._entries[key] = got
        if len(self._entries) > 200_000:
            self._entries.popitem(last=False)
        return got

    def file_at(self, commit: str, parts: tuple[str, ...]) -> str | None:
        """The blob id of the file at ``parts`` in ``commit``, or None when that commit
        has no regular file there."""
        got = self.entry(self.commit(commit).tree, parts)
        if got is None or got[0] not in _FILE_MODES:
            return None
        return got[1]

    # ------------------------------------------------------------------ history
    def file_history(
        self, parts: tuple[str, ...], *, start: str | None = None, max_commits: int = DEFAULT_MAX_COMMITS
    ) -> History:
        """The commits reachable from ``start`` (HEAD's commit by default) that changed the
        file at ``parts``, newest first by commit time, as ``git log -- <path>`` lists
        them with its default history simplification: a commit whose file is the same as
        one of its parents' is passed over and only that parent is followed. A change of
        mode alone is no new version."""
        out = History()
        if start is None:
            start = self.head()[1]
        if start is None:
            return out
        seq = 0
        first = self.commit(start)
        heap = [(-(first.committed or 0), seq, start)]
        queued = {start}
        while heap:
            _t, _s, oid = heapq.heappop(heap)
            if out.walked >= max_commits:
                out.truncated = True
                break
            out.walked += 1
            c = self.commit(oid)
            mine = self.file_at(oid, parts)
            parents = []
            if oid not in self.shallow:
                for p in c.parents:
                    if self.has_object(p):
                        parents.append(p)
                    else:
                        out.incomplete = True
            elif c.parents:
                out.incomplete = True
            if not parents:
                if mine is not None:
                    out.versions.append(self._version(c, "added", mine, parts))
                continue
            theirs = [self.file_at(p, parts) for p in parents]
            same = [p for p, b in zip(parents, theirs, strict=True) if b == mine]
            if same:
                follow = same[:1]
            else:
                follow = parents
                if mine is None:
                    out.versions.append(self._version(c, "deleted", None, parts))
                elif all(b is None for b in theirs):
                    out.versions.append(self._version(c, "added", mine, parts))
                else:
                    out.versions.append(self._version(c, "modified", mine, parts))
            for p in follow:
                if p not in queued:
                    queued.add(p)
                    seq += 1
                    heapq.heappush(heap, (-(self.commit(p).committed or 0), seq, p))
        return out

    def _version(self, c: Commit, status: str, blob: str | None, parts: tuple[str, ...]) -> FileVersion:
        path = "/".join(parts)
        if blob is None:
            return FileVersion(c, status, None, path=path)
        try:
            _kind, size = self.object_info(blob)
        except MissingObjectError:
            return FileVersion(c, status, blob, path=path)
        lfs = None
        if size <= MAX_LFS_POINTER:
            lfs = parse_lfs_pointer(self.read_blob(blob, limit=MAX_LFS_POINTER))
        return FileVersion(c, status, blob, size, lfs, path=path)

    # ------------------------------------------------------------------ Git LFS
    def lfs_object(self, pointer: LfsPointer) -> str | None:
        """The path of the LFS object a pointer stands for when it is on this machine (a
        plain file of the pointer's size), else None."""
        folder = self.lfs_folder()
        parts = ("objects", pointer.oid[:2], pointer.oid[2:4], pointer.oid)
        if _is_link(folder):
            raise LinkRefusedError(
                f"{folder}: the Git LFS folder is a link, which is never followed",
                detail={"rule": "link_in_path"},
            )
        st = lstat_within(folder, parts)
        if st is None or not stat.S_ISREG(st.st_mode) or st.st_size != pointer.size:
            return None
        return os.path.join(folder, *parts)


def parse_commit(oid: str, data: bytes, hash_len: int) -> Commit:
    """A commit object's headers and the first line of its message."""
    head, sep, message = data.partition(b"\n\n")
    if not sep:
        head, message = data, b""
    tree = None
    parents: list[str] = []
    author = committer = None
    encoding = "utf-8"
    for line in head.split(b"\n"):
        if line.startswith(b" "):
            continue  # the continuation of a signature or a merged tag
        key, _, value = line.partition(b" ")
        if key == b"tree":
            tree = value.decode("ascii", "replace")
        elif key == b"parent":
            parents.append(value.decode("ascii", "replace"))
        elif key == b"author":
            author = value
        elif key == b"committer":
            committer = value
        elif key == b"encoding":
            encoding = value.decode("ascii", "replace").strip() or "utf-8"
    want = 2 * hash_len
    if tree is None or len(tree) != want or not _HEX.match(tree):
        raise GitObjectError("a commit names no tree")
    if any(len(p) != want or not _HEX.match(p) for p in parents):
        raise GitObjectError("a commit names a parent that is not an object id")
    try:
        text = message.decode(encoding, "replace")
    except LookupError:
        text = message.decode("utf-8", "replace")
    subject = ""
    for line in text.splitlines():
        if line.strip():
            subject = line.strip()[:300]
            break
    a_name, a_time, a_off = _person(author, encoding)
    _c_name, c_time, c_off = _person(committer, encoding)
    return Commit(oid, tree, tuple(parents), a_name, a_time, a_off, c_time, c_off, subject)


def _person(value: bytes | None, encoding: str) -> tuple[str | None, int | None, int | None]:
    if value is None:
        return None, None, None
    m = _PERSON.match(value.strip())
    if m is None:
        return None, None, None
    try:
        name = m.group(1).decode(encoding, "replace").strip()
    except LookupError:
        name = m.group(1).decode("utf-8", "replace").strip()
    when = int(m.group(2))
    zone = m.group(3)
    offset = (1 if zone[:1] == b"+" else -1) * (int(zone[1:3]) * 60 + int(zone[3:5]))
    if not -(1 << 40) < when < 1 << 40:
        when = None
    return (name[:200] or None), when, offset


# --------------------------------------------------------------------------- discovery
def _git_dir_from_file(path: str, folder: str) -> str:
    text = _text_line(_read(path, folder, MAX_SMALL_FILE))
    if not text.startswith("gitdir:"):
        raise GitObjectError("a .git file does not name a repository folder")
    target = text[7:].strip()
    full = target if os.path.isabs(target) else os.path.join(folder, target)
    return _check_target(os.path.normpath(full), folder, "the .git file")


def _common_dir(git_dir: str) -> str:
    try:
        text = _text_line(_read(os.path.join(git_dir, "commondir"), git_dir, MAX_SMALL_FILE))
    except FileNotFoundError:
        return git_dir
    full = text if os.path.isabs(text) else os.path.join(git_dir, text)
    return _check_target(os.path.normpath(full), git_dir, "the repository's commondir")


def _looks_like_git_dir(git_dir: str, common_dir: str) -> bool:
    return os.path.isfile(os.path.join(git_dir, "HEAD")) and os.path.isdir(
        os.path.join(common_dir, "objects")
    )


def find_work_tree(path: str) -> tuple[str, str, str] | None:
    """``(work tree, git folder, shared git folder)`` of the repository holding
    ``path``, looked for from its folder upwards on the same file system, or None. A
    ``.git`` that is a link raises :class:`LinkRefusedError`: it is never followed."""
    folder = os.path.dirname(os.path.abspath(path))
    try:
        dev = os.stat(folder).st_dev if os.name != "nt" else None
    except OSError:
        return None
    for _ in range(MAX_DISCOVERY_DEPTH):
        dotgit = os.path.join(folder, GIT_FOLDER)
        try:
            st = os.lstat(dotgit)
        except OSError:
            st = None
        if st is not None:
            if _is_link(dotgit):
                raise LinkRefusedError(
                    f"{dotgit}: the repository's .git is a link, which is never followed",
                    detail={"rule": "link_in_path"},
                )
            if stat.S_ISDIR(st.st_mode):
                git_dir = dotgit
            elif stat.S_ISREG(st.st_mode):
                git_dir = _git_dir_from_file(dotgit, folder)
            else:
                git_dir = None
            if git_dir is not None:
                common = _common_dir(git_dir)
                if _looks_like_git_dir(git_dir, common):
                    return folder, git_dir, common
        parent = os.path.dirname(folder)
        if parent == folder:
            return None
        if dev is not None:
            try:
                if os.stat(parent).st_dev != dev:
                    return None  # git does not look across file systems either
            except OSError:
                return None
        folder = parent
    return None


def find_repository(path: str) -> Repository | None:
    """The repository whose work tree holds ``path``, opened read-only, or None."""
    found = find_work_tree(path)
    if found is None:
        return None
    return Repository(*found)


def blob_hasher(size: int, object_format: str) -> Any:
    """A hash primed with git's header for a blob of ``size`` bytes in ``object_format``
    (``sha1`` or ``sha256``): fed the content, its ``hexdigest()`` is the blob's id."""
    import hashlib

    h = hashlib.new(object_format)
    h.update(b"blob %d\0" % size)
    return h


__all__ = [
    "DEFAULT_MAX_COMMITS",
    "Commit",
    "FileVersion",
    "GitObjectError",
    "History",
    "LfsPointer",
    "MissingObjectError",
    "Repository",
    "apply_delta",
    "blob_hasher",
    "find_repository",
    "find_work_tree",
    "lstat_within",
    "parse_commit",
    "parse_config",
    "parse_lfs_pointer",
]
