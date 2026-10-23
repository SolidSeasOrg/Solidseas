"""Bounded, hostile-input-safe building blocks for the model-file readers (provisional).

Every reader of :mod:`solidseas.formats` reads its bytes through this module, so
the rules that keep a crafted file from costing unbounded memory or time live in
one place:

* :class:`Source` holds one document's bytes, in memory or behind a held,
  shared, read-only handle (:func:`open_source` opens it the way
  ``open_document`` opens a SOLIDWORKS file: ``within`` a folder, regular files
  only, ``max_file_bytes`` from ``fstat`` before any byte is read).
* :class:`Clock` is the time and cancellation check every reader loop ticks.
* :class:`SafeZip` reads a zip package (3MF, zipped AMF): the member count and
  the central directory's size are checked from the end records before Python's
  ``zipfile`` reads the directory, the directory ``zipfile`` then reads is
  refused past its bound and has its entries counted before ``zipfile`` builds
  them, encrypted members are refused, and a member is inflated chunk by chunk
  against its own bound, the read's total and a compression ratio, so a zip
  bomb stops after a few chunks.
  :func:`opc_resolve` turns a package relationship's target into a member name,
  refusing one that climbs out of the package.
* :func:`xml_events` parses XML with ``expat`` alone: a DOCTYPE, an entity
  declaration or an external entity is refused before it is used, and depth,
  attribute length and text length are bounded. Nothing builds a tree of a
  large document. :func:`xml_tree` builds a small one for small parts.
* :func:`load_json` parses JSON strictly: no NaN or Infinity, bounded size and
  depth.
* :func:`sibling_path` and :func:`read_sibling` read a file a document names
  (a glTF buffer, an OBJ material library) only from inside the document's own
  folder, never through a link, and only up to a count and a size, under the
  rules the document was opened with (a hard link refused, ``max_file_bytes``);
  :func:`sibling_resolution` says where such a file is without opening it.
* :func:`sanitize_png` and :func:`bmp_to_png` turn a stored image into a PNG
  that SolidSeas wrote itself: header, palette, transparency and pixel data,
  every length checked and the pixel data inflated to exactly the size the
  header implies. :func:`encode_png` writes PNGs (the renderer uses it too).

Pure Python, standard library only. Nothing here imports a reader.
"""

import io
import json
import math
import os
import re
import stat
import struct
import time
import zipfile
import zlib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote
from xml.parsers import expat

from ..errors import (
    FileTooLargeError,
    FormatNotSupportedError,
    InvalidArgumentError,
    LinkRefusedError,
    PathRefusedError,
    ReaderWarning,
    SldFormatError,
    SldLimitError,
    SolidSeasError,
)
from .limits import Limits
from .solidworks._io import open_readonly, pread
from .solidworks.document import FileInfo

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHUNK = 64 << 10  # bytes read or inflated at a time
_RATIO_FLOOR = 1 << 20  # the zip ratio is checked once a member has inflated past this


# --------------------------------------------------------------------------- cancellation and time
class ReadCancelledError(SolidSeasError):
    """A read was stopped because its ``cancelled`` callback said so (code ``interrupted``)."""

    code = "interrupted"


class Clock:
    """A deadline and a cancellation check that loops tick cheaply: the time and
    ``cancelled()`` are looked at every :data:`EVERY` ticks. Past the deadline it
    raises :class:`SldLimitError` with ``detail["limit"]`` ``limit`` (``seconds`` by
    default); when ``cancelled()`` is true, :class:`ReadCancelledError`."""

    EVERY = 4096
    __slots__ = ("cancelled", "deadline", "limit", "n", "seconds")

    def __init__(
        self,
        seconds: float | None,
        cancelled: Callable[[], bool] | None = None,
        *,
        limit: str = "seconds",
    ) -> None:
        self.seconds = seconds
        self.deadline = None if seconds is None else time.perf_counter() + seconds
        self.cancelled = cancelled
        self.limit = limit
        self.n = 0

    def tick(self, k: int = 1) -> None:
        self.n += k
        if self.n >= self.EVERY:
            self.n = 0
            self.check()

    def check(self) -> None:
        if self.cancelled is not None and self.cancelled():
            raise ReadCancelledError("the read was cancelled")
        if self.deadline is not None and time.perf_counter() > self.deadline:
            raise SldLimitError(f"the read took longer than {self.seconds:g} s", detail={"limit": self.limit})

    def left(self) -> float | None:
        return None if self.deadline is None else self.deadline - time.perf_counter()

    def child(self, seconds: float | None, *, limit: str = "seconds") -> "Clock":
        """A clock that ends ``seconds`` from now (its own ``limit``) or at this clock's
        deadline when that comes first (this clock's limit), with the same cancellation."""
        left = self.left()
        if left is not None and (seconds is None or left <= seconds):
            return Clock(max(left, 0.0), self.cancelled, limit=self.limit)
        return Clock(seconds, self.cancelled, limit=limit)


# --------------------------------------------------------------------------- the document's bytes
class Source:
    """One document's bytes: ``data`` in memory, or a held read-only handle ``fh`` of
    ``size`` bytes. Reads are positioned (``read_at``) and bounded by the caller.

    ``refuse_hard_links``, ``max_file_bytes`` and ``subfolders`` say how the document was
    opened (:func:`open_source`), so the files it names (a glTF buffer, an OBJ material
    library, an Alibre component) are opened under the same rules. ``file_ident`` is
    ``(st_dev, st_ino, st_nlink)`` from ``fstat`` on the handle a path was opened
    with, as a SOLIDWORKS container keeps it (None for bytes)."""

    def __init__(self, data: bytes | None = None, *, fh: Any = None, size: int | None = None) -> None:
        if (data is None) == (fh is None):
            raise ValueError("a Source holds either data or a handle")
        self._data = data
        self._fh = fh
        self.size = len(data) if data is not None else int(size or 0)
        self.refuse_hard_links = False
        self.max_file_bytes: int | None = None
        self.subfolders = True  # whether the files it names may lie below its own folder
        self.file_ident: tuple[int, int, int] | None = None

    @property
    def in_memory(self) -> bool:
        return self._data is not None

    @property
    def closed(self) -> bool:
        return self._fh is not None and self._fh.closed

    def close(self) -> None:
        if self._fh is not None and not self._fh.closed:
            self._fh.close()

    def read_at(self, offset: int, n: int) -> bytes:
        """Exactly ``n`` bytes at ``offset``, or :class:`SldFormatError` when the file ends first."""
        if offset < 0 or n < 0 or offset + n > self.size:
            raise SldFormatError(
                f"unexpected end of data at offset {offset} (wanted {n} bytes of {self.size})"
            )
        if self._data is not None:
            return self._data[offset : offset + n]
        return pread(self._fh, offset, n)

    def read_upto(self, offset: int, n: int) -> bytes:
        """Up to ``n`` bytes at ``offset``: fewer at the end of the file."""
        if offset >= self.size or n <= 0:
            return b""
        return self.read_at(offset, min(n, self.size - offset))

    def head(self, n: int = 4096) -> bytes:
        return self.read_upto(0, n)

    def read_all(self, limit: int, name: str) -> bytes:
        """The whole file, refused with ``SldLimitError`` (``detail["limit"]`` ``name``) when it is
        larger than ``limit``."""
        if self.size > limit:
            raise SldLimitError(
                f"the file is {self.size:,} bytes, more than the {limit:,} allowed",
                detail={"limit": name, "value": self.size},
            )
        if self._data is not None:
            return self._data
        return self.read_at(0, self.size)

    def chunks(self, start: int = 0, end: int | None = None, size: int = CHUNK) -> Iterator[bytes]:
        """The bytes from ``start`` to ``end`` (the end of the file), ``size`` at a time."""
        end = self.size if end is None else min(end, self.size)
        pos = start
        while pos < end:
            n = min(size, end - pos)
            yield self.read_at(pos, n)
            pos += n

    def file(self) -> "_SourceFile":
        """A seekable, read-only file object over the source, for ``zipfile``."""
        return _SourceFile(self)


class _SourceFile(io.RawIOBase):
    """A file object over a :class:`Source`, with its own position."""

    def __init__(self, source: Source) -> None:
        self._s = source
        self._pos = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            pos = offset
        elif whence == 1:
            pos = self._pos + offset
        elif whence == 2:
            pos = self._s.size + offset
        else:
            raise ValueError("whence is 0, 1 or 2")
        if pos < 0:
            raise ValueError("negative seek position")
        self._pos = pos
        return pos

    def readinto(self, b) -> int:
        data = self._s.read_upto(self._pos, len(b))
        n = len(data)
        b[:n] = data
        self._pos += n
        return n

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = max(0, self._s.size - self._pos)
        data = self._s.read_upto(self._pos, size)
        self._pos += len(data)
        return data


def check_max_file_bytes(value: Any) -> int | None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
        raise InvalidArgumentError(
            "max_file_bytes must be a non-negative integer", detail={"parameter": "max_file_bytes"}
        )
    return value


def open_source(
    src: Any,
    *,
    within: Any = None,
    max_file_bytes: int | None = None,
    refuse_hard_links: bool = False,
    hold_open: bool = False,
    limits: Limits,
    subfolders: bool = True,
) -> tuple[Source, str | None, FileInfo | None]:
    """Open ``src`` (a path, or the bytes of a whole file) as
    ``open_document`` opens a SOLIDWORKS file: the :class:`Source`, the path (None for
    bytes) and the :class:`FileInfo` from ``fstat`` (None for bytes).

    A path is opened read-only and share-tolerant, ``within`` the folder when given
    (no link, junction or placeholder below it); a file larger than
    ``max_file_bytes`` (or ``limits.file_bytes``) raises ``FileTooLargeError``
    before any byte is read, and one with several names ``LinkRefusedError`` when
    ``refuse_hard_links``. Files up to ``limits.whole_read_bytes`` are read whole
    and the handle closed, unless ``hold_open``. ``subfolders`` false keeps the files
    the document names to its own folder (:func:`read_sibling`)."""
    max_file_bytes = check_max_file_bytes(max_file_bytes)
    caps = [c for c in (max_file_bytes, limits.file_bytes) if c is not None]
    cap = min(caps) if caps else None
    if isinstance(src, (bytes, bytearray, memoryview)):
        if within is not None:
            raise InvalidArgumentError(
                "within applies to a path, not to bytes", detail={"parameter": "within"}
            )
        data = bytes(src)
        if cap is not None and len(data) > cap:
            raise FileTooLargeError(
                f"<memory>: {len(data)} bytes exceeds the limit of {cap} bytes",
                detail={"limit": cap, "value": len(data)},
            )
        return _opened(Source(data), refuse_hard_links, max_file_bytes, subfolders), None, None
    try:
        path = os.fspath(src)
    except TypeError:
        raise InvalidArgumentError("src is a path or bytes", detail={"parameter": "src"}) from None
    if not isinstance(path, str):
        path = os.fsdecode(path)
    fh = open_readonly(path) if within is None else open_readonly(path, within=os.fspath(within))
    try:
        st = os.fstat(fh.fileno())
        size = st.st_size
        if refuse_hard_links and st.st_nlink > 1:
            raise LinkRefusedError(
                f"{path}: the file has more than one name, and another may lie outside the folder",
                detail={"rule": "hard_link"},
            )
        if cap is not None and size > cap:
            raise FileTooLargeError(
                f"{path}: {size} bytes exceeds the limit of {cap} bytes", detail={"limit": cap, "value": size}
            )
        info = FileInfo.from_stat(size, st.st_mtime_ns)
        if not hold_open and size <= limits.whole_read_bytes:
            data = pread(fh, 0, size) if size else b""
            fh.close()
            source = Source(data)
        else:
            source = Source(fh=fh, size=size)
        source.file_ident = (st.st_dev, st.st_ino, st.st_nlink)
        return _opened(source, refuse_hard_links, max_file_bytes, subfolders), path, info
    except BaseException:
        fh.close()
        raise


def _opened(
    source: Source, refuse_hard_links: bool, max_file_bytes: int | None, subfolders: bool = True
) -> Source:
    source.refuse_hard_links = bool(refuse_hard_links)
    source.max_file_bytes = max_file_bytes
    source.subfolders = bool(subfolders)
    return source


# --------------------------------------------------------------------------- text
def clip_text(text: str, limits: Limits, warnings: list | None = None, what: str = "a value") -> str:
    """``text`` cut to ``limits.text_bytes`` UTF-8 bytes; a warning ``text_truncated`` is
    appended to ``warnings`` when it was cut."""
    raw = text.encode("utf-8", "surrogatepass")
    if len(raw) <= limits.text_bytes:
        return text
    if warnings is not None:
        warnings.append(
            ReaderWarning("text_truncated", f"{what} is longer than {limits.text_bytes:,} bytes and was cut")
        )
    return raw[: limits.text_bytes].decode("utf-8", "ignore")


# --------------------------------------------------------------------------- zip packages
_EOCD = b"PK\x05\x06"
_EOCD64_LOCATOR = b"PK\x06\x07"
_EOCD64 = b"PK\x06\x06"
_CENTRAL = b"PK\x01\x02"
_END_SEARCH = 22 + 0xFFFF  # the most Python's zipfile reads at once while it looks for the end record
_ALLOWED_METHODS = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)


def zip_directory_size(source: Source) -> tuple[int, int]:
    """``(members, central directory bytes)`` from a zip's end records, without reading
    the directory. When a ZIP64 locator stands right before the end record, Python's
    ``zipfile`` takes both from the ZIP64 record whatever the end record holds, so they
    are taken from there here too: from the record where the locator points and from
    the one right before the locator (Python releases look in either), the larger of
    each. Raises :class:`SldFormatError` when there is no end record."""
    tail_len = min(source.size, _END_SEARCH)
    start = source.size - tail_len
    tail = source.read_upto(start, tail_len)
    i = tail.rfind(_EOCD)
    while i >= 0 and len(tail) - i < 22:
        i = tail.rfind(_EOCD, 0, i)
    if i < 0:
        raise SldFormatError("not a zip package: no end of central directory record")
    (_sig, _disk, _cd_disk, _n_disk, members, cd_size, _cd_off, _clen) = struct.unpack_from(
        "<IHHHHIIH", tail, i
    )
    locator = start + i - 20
    if locator < 0 or source.read_at(locator, 4) != _EOCD64_LOCATOR:
        return members, cd_size
    (where,) = struct.unpack_from("<Q", source.read_at(locator + 8, 8))
    found = []
    for at in sorted({where, locator - 56}):
        if 0 <= at <= locator - 56:
            rec = source.read_at(at, 56)
            if rec[:4] == _EOCD64:
                found.append(struct.unpack_from("<QQQ", rec, 24))  # this disk's members, all, bytes
    if found:
        members = max(max(here, every) for here, every, _n in found)
        cd_size = max(n for _here, _every, n in found)
    return members, cd_size


def central_entries(data: bytes, most: int) -> int:
    """How many central directory entries follow one another from the start of ``data``,
    walked as Python's ``zipfile`` walks a directory it has read, counted up to ``most``."""
    n = pos = 0
    end = len(data)
    while n < most and pos + 46 <= end and data[pos : pos + 4] == _CENTRAL:
        name, extra, comment = struct.unpack_from("<3H", data, pos + 28)
        pos += 46 + name + extra + comment
        n += 1
    return n


class _PackageFile(_SourceFile):
    """The file Python's ``zipfile`` reads a package through. While :class:`SafeZip`
    opens the package (``opening``), a read longer than the central directory may be
    is refused (``zip_directory_bytes``), and a read that holds a central directory has
    its entries counted (``zip_members``) before ``zipfile`` builds one object an entry:
    neither depends on how ``zipfile`` found the directory. Afterwards it reads as any
    file does, counting the bytes read (``consumed``), which is how much of the file
    a member's inflation has taken."""

    def __init__(self, source: Source, limits: Limits) -> None:
        super().__init__(source)
        self.limits = limits
        self.opening = True
        self.consumed = 0

    def read(self, size: int = -1) -> bytes:
        if not self.opening:
            data = super().read(size)
            self.consumed += len(data)
            return data
        lim = self.limits
        want = self._s.size - self._pos if size is None or size < 0 else size  # some releases read to the end
        if want > max(lim.zip_directory_bytes, _END_SEARCH):
            raise lim.exceeded("zip_directory_bytes", "the package's central directory is too large")
        data = super().read(size)
        if data[:4] == _CENTRAL and central_entries(data, lim.zip_members + 1) > lim.zip_members:
            raise lim.exceeded("zip_members", f"the package has more than {lim.zip_members:,} members")
        return data


def first_member_name(head: bytes) -> str | None:
    """The name of the first member of a zip from its first local header, or None."""
    if len(head) < 30 or head[:4] != b"PK\x03\x04":
        return None
    (nlen,) = struct.unpack_from("<H", head, 26)
    if 30 + nlen > len(head):
        return None
    return head[30 : 30 + nlen].decode("utf-8", "replace")


class SafeZip:
    """A zip package read within :class:`Limits` (see the module notes). What its members
    inflate to is counted against ``zip_total_bytes`` one read at a time: a reader calls
    :meth:`start_read` as each of its calls (``tree()``, ``scene()``, ``preview()``)
    begins, the package's opening being the first read."""

    def __init__(self, source: Source, limits: Limits, clock: Clock | None = None) -> None:
        self.limits = limits
        self.clock = clock
        members, cd_size = zip_directory_size(source)
        if members > limits.zip_members:
            raise limits.exceeded("zip_members", f"the package has {members:,} members", members)
        if cd_size > limits.zip_directory_bytes:
            raise limits.exceeded("zip_directory_bytes", f"the package's directory is {cd_size:,} bytes")
        fobj = self._file = _PackageFile(source, limits)
        try:
            self._zf = zipfile.ZipFile(fobj)
        except (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, struct.error, EOFError) as exc:
            raise SldFormatError(f"the zip package is damaged: {exc}") from None
        except NotImplementedError as exc:  # a directory entry naming a zip version Python lacks
            raise SldFormatError(
                f"the zip package is damaged or needs a zip feature SolidSeas does not read: {exc}"[:200]
            ) from None
        fobj.opening = False
        infos = self._zf.infolist()
        if len(infos) > limits.zip_members:
            raise limits.exceeded("zip_members", f"the package has {len(infos):,} members", len(infos))
        self._by_name = {i.filename: i for i in infos}
        self._folded: dict[str, list[str]] = {}
        for name in self._by_name:
            self._folded.setdefault(name.casefold(), []).append(name)
        self.inflated = 0  # every member inflated in this read so far

    def start_read(self) -> None:
        """Count what is inflated from now on as a new read against ``zip_total_bytes``."""
        self.inflated = 0

    def close(self) -> None:
        self._zf.close()

    def names(self) -> list[str]:
        return list(self._by_name)

    def find(self, name: str) -> str | None:
        """The member called ``name`` (a leading ``/`` dropped), exactly, else the one
        member whose name matches it case-insensitively (OPC part names are), else None."""
        name = name.lstrip("/")
        if name in self._by_name:
            return name
        same = self._folded.get(name.casefold(), [])
        return same[0] if len(same) == 1 else None

    def size(self, name: str) -> int:
        return self._by_name[name].file_size

    def _info(self, name: str) -> zipfile.ZipInfo:
        found = self.find(name)
        if found is None:
            raise SldFormatError(f"the package has no part {name!r}")
        info = self._by_name[found]
        if info.flag_bits & 0x1:
            raise FormatNotSupportedError(
                "the package holds an encrypted part", detail={"rule": "encrypted", "value": "zip"}
            )
        if info.compress_type not in _ALLOWED_METHODS:
            raise FormatNotSupportedError(
                f"a part is compressed with zip method {info.compress_type}, which is not read",
                detail={"rule": "compression", "value": f"zip_method_{info.compress_type}"},
            )
        return info

    def iter_member(self, name: str, *, max_bytes: int | None = None) -> Iterator[bytes]:
        """The member's bytes, inflated :data:`CHUNK` at a time, each chunk counted
        against ``max_bytes`` (default ``zip_member_bytes``), the read's
        ``zip_total_bytes`` and the ``zip_ratio``. The ratio is taken against the bytes
        read from the file for the member so far (its header and what ``zipfile`` read
        ahead included), never against the size its directory entry states."""
        info = self._info(name)
        lim = self.limits
        cap = lim.zip_member_bytes if max_bytes is None else min(max_bytes, lim.zip_member_bytes)
        start = self._file.consumed
        got = 0
        try:
            with self._zf.open(info) as fh:
                while True:
                    if self.clock is not None:
                        self.clock.tick(CHUNK // 64)
                    chunk = fh.read(CHUNK)
                    if not chunk:
                        break
                    got += len(chunk)
                    self.inflated += len(chunk)
                    if got > cap:
                        raise lim.exceeded("zip_member_bytes", f"a part inflates past {cap:,} bytes")
                    if self.inflated > lim.zip_total_bytes:
                        raise lim.exceeded("zip_total_bytes", "the package inflates past its total limit")
                    stored = max(1, self._file.consumed - start)
                    if got > _RATIO_FLOOR and got > lim.zip_ratio * stored:
                        raise lim.exceeded("zip_ratio", "a part inflates far more than a model part can")
                    yield chunk
        except (zipfile.BadZipFile, zlib.error, EOFError, ValueError, struct.error) as exc:
            raise SldFormatError(f"a part of the package is damaged: {exc}") from None
        except NotImplementedError as exc:  # strong encryption, patched data: what Python declines
            raise FormatNotSupportedError(
                f"a part of the package uses a zip feature SolidSeas does not read ({str(exc)[:80]})",
                detail={"rule": "encrypted", "value": "zip"},
            ) from None

    def read(self, name: str, *, max_bytes: int | None = None) -> bytes:
        """The whole member, inflated within the bounds of :meth:`iter_member`."""
        return b"".join(self.iter_member(name, max_bytes=max_bytes))


def opc_resolve(source_part: str, target: str) -> str | None:
    """The package member a relationship of ``source_part`` (a member name; ``""`` for
    the package's own relationships) names with ``target``: relative targets join the
    source part's folder, ``/``-led targets the package root. None for an external
    target (a URI scheme), a backslash, or a path that climbs out of the package."""
    if not target or "\\" in target or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", target):
        return None
    target = unquote(target.split("#", 1)[0])
    if target.startswith("/"):
        parts: list[str] = []
        rest = target[1:]
    else:
        parts = source_part.strip("/").split("/")[:-1] if source_part else []
        rest = target
    for comp in rest.split("/"):
        if comp in ("", "."):
            continue
        if comp == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(comp)
    return "/".join(parts) or None


# --------------------------------------------------------------------------- XML
class _XmlRefused(Exception):
    pass


@dataclass
class XmlNode:
    """One element of a small XML document read by :func:`xml_tree`."""

    tag: str
    attrs: dict[str, str]
    text: str = ""
    children: list["XmlNode"] = field(default_factory=list)

    def find(self, tag: str) -> "XmlNode | None":
        for c in self.children:
            if c.tag == tag:
                return c
        return None

    def findall(self, tag: str) -> list["XmlNode"]:
        return [c for c in self.children if c.tag == tag]


def _qname(name: str) -> str:
    """expat's ``uri}local`` as ElementTree's ``{uri}local``."""
    if "}" in name:
        uri, local = name.rsplit("}", 1)
        return "{" + uri + "}" + local
    return name


def xml_events(
    chunks: Iterable[bytes],
    limits: Limits,
    clock: Clock | None = None,
    *,
    namespaces: bool = True,
) -> Iterator[tuple[str, str, Any]]:
    """Parse XML fed as ``chunks`` and yield ``("start", tag, attrs)`` and
    ``("end", tag, text)`` events, tags as ``{namespace}local`` when ``namespaces``.
    ``text`` is the element's text before its first child (whitespace included),
    which is what a model format keeps in an element; text after a child is
    ignored. A DOCTYPE, an entity declaration or an external entity raises
    :class:`SldFormatError` before it is used; depth past ``xml_depth``
    ``SldFormatError``, an attribute or a text past its bound ``SldLimitError``."""
    parser = expat.ParserCreate(namespace_separator="}" if namespaces else None)
    parser.buffer_text = True
    parser.ordered_attributes = False
    try:
        parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    except AttributeError:  # pragma: no cover - every CPython has it
        pass
    events: list[tuple[str, str, Any]] = []
    stack: list[list] = []  # [tag, text parts, text length, has child]
    max_depth, max_attr, max_text = limits.xml_depth, limits.xml_attribute_bytes, limits.xml_text_bytes

    def refuse_doctype(*_args):
        raise _XmlRefused("the XML declares a DOCTYPE, which is never read")

    def refuse_entity(*_args):
        raise _XmlRefused("the XML declares or uses an entity, which is never read")

    def start(name, attrs):
        if len(stack) >= max_depth:
            raise SldFormatError(
                f"the XML nests deeper than {max_depth} elements", detail={"limit": "xml_depth"}
            )
        if stack:
            stack[-1][3] = True
        out = {}
        for k, v in attrs.items():
            if len(v) > max_attr:
                raise limits.exceeded("xml_attribute_bytes", "an XML attribute value is too long")
            out[_qname(k) if namespaces else k] = v
        tag = _qname(name) if namespaces else name
        stack.append([tag, [], 0, False])
        events.append(("start", tag, out))

    def end(_name):
        tag, parts, _n, _child = stack.pop()
        events.append(("end", tag, "".join(parts)))

    def chars(data):
        if not stack:
            return
        top = stack[-1]
        if top[3]:  # after a child: a tail, not kept
            return
        top[2] += len(data)
        if top[2] > max_text:
            raise limits.exceeded("xml_text_bytes", "an XML element's text is too long")
        top[1].append(data)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars
    parser.StartDoctypeDeclHandler = refuse_doctype
    parser.EntityDeclHandler = refuse_entity
    parser.UnparsedEntityDeclHandler = refuse_entity
    parser.ExternalEntityRefHandler = refuse_entity
    parser.SkippedEntityHandler = refuse_entity
    parser.DefaultHandler = None
    try:
        for chunk in chunks:
            if clock is not None:
                clock.tick(max(1, len(chunk) // 256))
            parser.Parse(chunk, False)
            if events:
                yield from events
                events.clear()
        parser.Parse(b"", True)
        yield from events
        events.clear()
    except _XmlRefused as exc:
        raise SldFormatError(str(exc), detail={"rule": "xml_doctype"}) from None
    except expat.ExpatError as exc:
        raise SldFormatError(f"the XML is not well formed: {exc}") from None
    except RecursionError:
        raise SldFormatError("the XML nests too deeply", detail={"limit": "xml_depth"}) from None
    except SolidSeasError:
        raise
    except (LookupError, ValueError) as exc:  # an encoding the declaration names that Python lacks
        raise SldFormatError(f"the XML names an encoding SolidSeas cannot read: {exc}"[:200]) from None


def xml_tree(
    data: bytes | Iterable[bytes],
    limits: Limits,
    clock: Clock | None = None,
    *,
    max_nodes: int | None = None,
    namespaces: bool = True,
) -> XmlNode:
    """A small XML document (a relationships part, content types, metadata) as an
    :class:`XmlNode` tree, parsed by :func:`xml_events` with at most ``max_nodes``
    elements (default ``limits.xml_nodes``)."""
    chunks = [data] if isinstance(data, (bytes, bytearray)) else data
    most = limits.xml_nodes if max_nodes is None else max_nodes
    root: XmlNode | None = None
    stack: list[XmlNode] = []
    n = 0
    for kind, tag, value in xml_events(chunks, limits, clock, namespaces=namespaces):
        if kind == "start":
            n += 1
            if n > most:
                raise limits.exceeded("xml_nodes", f"the XML part has more than {most:,} elements")
            node = XmlNode(tag, value)
            if stack:
                stack[-1].children.append(node)
            else:
                root = node
            stack.append(node)
        else:
            stack.pop().text = value
    if root is None:
        raise SldFormatError("the XML has no element")
    return root


# --------------------------------------------------------------------------- JSON
def _refuse_constant(name: str) -> None:
    raise ValueError(f"{name} is not JSON")


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):  # 1e999 is valid JSON, and Python reads it as infinity
        raise ValueError(f"the number {text[:24]} is too large to hold")
    return value


def load_json(data: bytes, limits: Limits) -> Any:
    """``data`` parsed as strict JSON (UTF-8, no NaN or Infinity, and no number too
    large for a double, such as 1e999), at most ``json_bytes`` long and
    ``json_depth`` deep; damaged JSON raises :class:`SldFormatError`."""
    if len(data) > limits.json_bytes:
        raise limits.exceeded("json_bytes", f"the JSON is {len(data):,} bytes", len(data))
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError:
        raise SldFormatError("the JSON is not UTF-8") from None
    text = text.removeprefix("﻿")
    try:
        value = json.loads(text, parse_constant=_refuse_constant, parse_float=_finite_float)
    except RecursionError:
        raise SldFormatError("the JSON nests too deeply", detail={"limit": "json_depth"}) from None
    except ValueError as exc:
        raise SldFormatError(f"the JSON is damaged: {exc}") from None
    stack = [(value, 1)]
    while stack:
        v, d = stack.pop()
        if isinstance(v, (dict, list)):
            if d > limits.json_depth:
                raise SldFormatError(
                    f"the JSON nests deeper than {limits.json_depth}", detail={"limit": "json_depth"}
                )
            items = v.values() if isinstance(v, dict) else v
            stack.extend((x, d + 1) for x in items if isinstance(x, (dict, list)))
    return value


# --------------------------------------------------------------------------- files beside a document
_WINDOWS_DEVICE = re.compile(r"(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?\Z", re.IGNORECASE)


def sibling_path(folder: str, uri: str) -> str:
    """The path of the file a document in ``folder`` names with the relative reference
    ``uri`` (percent escapes decoded). Refused with ``PathRefusedError`` (rule
    ``outside_document_folder``): a scheme, a drive, a UNC or absolute path, a
    backslash, a ``:`` (an alternate data stream), a ``..`` or empty component, a
    control character, or a Windows device name."""
    def refuse(why: str) -> PathRefusedError:
        return PathRefusedError(
            f"a file the document names is refused ({why})", detail={"rule": "outside_document_folder"}
        )

    if not isinstance(uri, str) or not uri or len(uri) > 4096:
        raise refuse("empty or too long")
    text = unquote(uri)
    if any(ch in text for ch in ("\\", ":", "\0")) or any(ord(ch) < 32 for ch in text):
        raise refuse("a scheme, drive, backslash or control character")
    if text.startswith("/"):
        raise refuse("an absolute path")
    parts = []
    for comp in text.split("/"):
        if comp == ".":
            continue
        if comp in ("", "..") or comp.rstrip(" .") != comp or _WINDOWS_DEVICE.match(comp):
            raise refuse("a component that climbs out or names a device")
        parts.append(comp)
    if not parts:
        raise refuse("no file name")
    return os.path.join(folder, *parts)


class SiblingBudget:
    """How many files beside one document have been read, against ``limits.siblings``,
    and how many bytes, against ``limits.sibling_total_bytes`` (every read counts, so
    two buffers that name one file count it twice), and the rules the document was
    opened under (``refuse_hard_links``, ``max_file_bytes``, ``subfolders``), which every
    file it names is opened under too."""

    def __init__(
        self,
        limits: Limits,
        *,
        refuse_hard_links: bool = False,
        max_file_bytes: int | None = None,
        subfolders: bool = True,
    ) -> None:
        self.limits = limits
        self.count = 0
        self.bytes = 0
        self.refuse_hard_links = bool(refuse_hard_links)
        self.max_file_bytes = max_file_bytes
        self.subfolders = bool(subfolders)

    @classmethod
    def of(cls, source: "Source", limits: Limits) -> "SiblingBudget":
        """A budget under the rules ``source`` was opened with."""
        return cls(
            limits,
            refuse_hard_links=source.refuse_hard_links,
            max_file_bytes=source.max_file_bytes,
            subfolders=source.subfolders,
        )


def read_sibling(doc_path: str | None, uri: str, budget: SiblingBudget) -> bytes:
    """The bytes of the file ``uri`` names beside the document at ``doc_path``, opened
    ``within`` the document's folder (no link, junction or placeholder), at most
    ``sibling_bytes`` (and the budget's ``max_file_bytes``) long, refused when it has
    several names and the budget's ``refuse_hard_links`` says so, and counted against
    ``siblings`` and ``sibling_total_bytes`` before it is read. When the budget's
    ``subfolders`` is false, a file in a subfolder of the document's folder is refused
    (``PathRefusedError``, rule ``subfolder``). A document opened from bytes has no
    folder: :class:`SldFormatError`."""
    if doc_path is None:
        raise SldFormatError("the document was opened from bytes, so the files it names cannot be read")
    lim = budget.limits
    budget.count += 1
    if budget.count > lim.siblings:
        raise lim.exceeded("siblings", f"the document names more than {lim.siblings:,} files")
    folder = os.path.dirname(os.path.abspath(doc_path))
    path = sibling_path(folder, uri)
    if not budget.subfolders and os.path.dirname(path) != folder:
        raise PathRefusedError(
            "a file the document names lies in a subfolder, and only the document's own folder is read",
            detail={"rule": "subfolder"},
        )
    with open_readonly(path, within=folder) as fh:
        st = os.fstat(fh.fileno())
        size = st.st_size
        if budget.refuse_hard_links and st.st_nlink > 1:
            raise LinkRefusedError(
                "a file the document names has more than one name, and another may lie outside the folder",
                detail={"rule": "hard_link"},
            )
        if budget.max_file_bytes is not None and size > budget.max_file_bytes:
            raise FileTooLargeError(
                f"a file the document names is {size:,} bytes, over the {budget.max_file_bytes:,} allowed",
                detail={"limit": budget.max_file_bytes, "value": size},
            )
        if size > lim.sibling_bytes:
            raise lim.exceeded("sibling_bytes", f"a file the document names is {size:,} bytes", size)
        if budget.bytes + size > lim.sibling_total_bytes:
            raise lim.exceeded(
                "sibling_total_bytes",
                f"the files the document names add up to more than {lim.sibling_total_bytes:,} bytes",
                budget.bytes + size,
            )
        budget.bytes += size
        return pread(fh, 0, size) if size else b""


def sibling_resolution(
    doc_path: str | None, uri: str, *, refuse_hard_links: bool = False, subfolders: bool = True
) -> dict[str, Any]:
    """Where a file the document names would be read from, as :func:`read_sibling` would
    open it, without opening anything: ``status`` ``found`` (a regular file inside the
    document's folder; ``path`` relative to that folder, ``/``-separated, and
    ``found_by`` ``relative_path``), ``not_found``, or ``refused`` (a reference that
    climbs out, a link, junction or cloud placeholder on the way, a file with several
    names when ``refuse_hard_links``, one in a subfolder when not ``subfolders``, or a
    document opened from bytes). Each component below the folder is read with
    ``lstat`` only after the ones above it passed, so no stat goes through a link."""
    from ..walk import reparse_link
    from .solidworks._io import _PLACEHOLDER_ATTRIBUTES

    def answer(status: str, path: str | None = None) -> dict[str, Any]:
        return {
            "status": status,
            "path": path,
            "found_by": "relative_path" if path else None,
            "version": None,
        }

    if doc_path is None:
        return answer("not_found")
    folder = os.path.dirname(os.path.abspath(doc_path))
    try:
        path = sibling_path(folder, uri)
    except PathRefusedError:
        return answer("refused")
    parts = os.path.relpath(path, folder).split(os.sep)
    if not subfolders and len(parts) > 1:
        return answer("refused")
    cur = folder
    st = None
    for i, name in enumerate(parts):
        cur = os.path.join(cur, name)
        try:
            st = os.lstat(cur)
        except (OSError, ValueError):
            return answer("not_found")
        attrs = getattr(st, "st_file_attributes", 0)
        if stat.S_ISLNK(st.st_mode) or reparse_link(attrs, getattr(st, "st_reparse_tag", 0)) is not None:
            return answer("refused")
        if i < len(parts) - 1 and not stat.S_ISDIR(st.st_mode):
            return answer("not_found")
    assert st is not None
    if not stat.S_ISREG(st.st_mode) or getattr(st, "st_file_attributes", 0) & _PLACEHOLDER_ATTRIBUTES:
        return answer("refused")
    if refuse_hard_links and st.st_nlink > 1:
        return answer("refused")
    return answer("found", "/".join(parts))


# --------------------------------------------------------------------------- images
def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def encode_png(width: int, height: int, pixels: bytes, channels: int) -> bytes:
    """A PNG of ``pixels`` (rows top to bottom, 8 bits a sample, ``channels`` 1, 2, 3 or 4:
    grey, grey and alpha, RGB, RGBA), every row after the first with the Up filter,
    which suits rendered and photographed images alike."""
    color_type = {1: 0, 2: 4, 3: 2, 4: 6}[channels]
    stride = width * channels
    if len(pixels) != stride * height:
        raise ValueError("pixels do not match the size")
    raw = bytearray()
    prev = bytes(stride)
    for y in range(height):
        row = pixels[y * stride : (y + 1) * stride]
        up = bytes((a - b) & 0xFF for a, b in zip(row, prev, strict=True)) if y else row
        raw.append(2 if y else 0)
        raw += up
        prev = row
    return (
        PNG_SIGNATURE
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _png_chunk(b"IEND", b"")
    )


_BIT_DEPTHS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
_ADAM7 = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))


def _row_bytes(width: int, bits_per_pixel: int) -> int:
    return (width * bits_per_pixel + 7) // 8


def _passes(width: int, height: int, interlace: int) -> list[tuple[int, int]]:
    if not interlace:
        return [(width, height)]
    out = []
    for x0, y0, dx, dy in _ADAM7:
        w = (width - x0 + dx - 1) // dx if width > x0 else 0
        h = (height - y0 + dy - 1) // dy if height > y0 else 0
        if w and h:
            out.append((w, h))
    return out


def sanitize_png(data: bytes, limits: Limits) -> tuple[bytes, int, int]:
    """A stored PNG rewritten by SolidSeas: ``(png, width, height)``.

    Every chunk's length and CRC is checked (at most ``png_chunks`` chunks), the
    header's size against ``image_side``, its bit depth and colour type against
    the specification, the palette and transparency against the colour type, and
    the pixel data must inflate to exactly the size the header implies (at most
    ``image_bytes``), with a valid filter on every row. The PNG written holds only
    the header, the palette, the transparency and the pixel data, compressed
    again. Anything else raises :class:`SldFormatError`."""
    if len(data) < 8 or data[:8] != PNG_SIGNATURE:
        raise SldFormatError("not a PNG")
    pos, n_chunks = 8, 0
    ihdr = plte = trns = None
    idat: list[bytes] = []
    idat_len = 0
    ended = False
    while pos + 12 <= len(data):
        (length,) = struct.unpack_from(">I", data, pos)
        tag = data[pos + 4 : pos + 8]
        if length > 0x7FFFFFFF or pos + 12 + length > len(data) or not tag.isalpha():
            raise SldFormatError("a PNG chunk runs past the end of the image")
        body = data[pos + 8 : pos + 8 + length]
        (crc,) = struct.unpack_from(">I", data, pos + 8 + length)
        if zlib.crc32(tag + body) & 0xFFFFFFFF != crc:
            raise SldFormatError("a PNG chunk's checksum is wrong")
        n_chunks += 1
        if n_chunks > limits.png_chunks:
            raise SldFormatError("the PNG has too many chunks", detail={"limit": "png_chunks"})
        pos += 12 + length
        if ihdr is None and tag != b"IHDR":
            raise SldFormatError("the PNG does not start with its header")
        if tag == b"IHDR":
            if ihdr is not None or length != 13:
                raise SldFormatError("the PNG header is malformed")
            ihdr = body
        elif tag == b"PLTE":
            if plte is not None or idat or length % 3 or not 3 <= length <= 768:
                raise SldFormatError("the PNG palette is malformed")
            plte = body
        elif tag == b"tRNS":
            if trns is not None or idat:
                raise SldFormatError("the PNG transparency is malformed")
            trns = body
        elif tag == b"IDAT":
            idat.append(body)
            idat_len += length
            if idat_len > limits.image_bytes:
                raise SldFormatError("the PNG's pixel data is too large", detail={"limit": "image_bytes"})
        elif tag == b"IEND":
            ended = True
            break
    if ihdr is None or not ended or not idat:
        raise SldFormatError("the PNG is incomplete")
    width, height, depth, ctype, comp, filt, interlace = struct.unpack(">IIBBBBB", ihdr)
    if not (0 < width <= limits.image_side and 0 < height <= limits.image_side):
        raise SldFormatError(
            f"the PNG is {width} x {height}, outside 1 to {limits.image_side}", detail={"limit": "image_side"}
        )
    if ctype not in _BIT_DEPTHS or depth not in _BIT_DEPTHS[ctype] or comp or filt or interlace > 1:
        raise SldFormatError("the PNG header names an unknown format")
    if ctype == 3 and (plte is None or len(plte) // 3 > (1 << depth)):
        raise SldFormatError("a palette PNG has no usable palette")
    if plte is not None and ctype in (0, 4):
        raise SldFormatError("a grey PNG has a palette")
    if trns is not None:
        if ctype in (4, 6):
            raise SldFormatError("a PNG with alpha has a transparency chunk")
        if (ctype == 0 and len(trns) != 2) or (ctype == 2 and len(trns) != 6):
            raise SldFormatError("the PNG transparency is malformed")
        if ctype == 3 and len(trns) > len(plte or b"") // 3:
            raise SldFormatError("the PNG transparency is longer than its palette")
    bpp = depth * _CHANNELS[ctype]
    sizes = [(_row_bytes(w, bpp), h) for w, h in _passes(width, height, interlace)]
    expected = sum((rb + 1) * h for rb, h in sizes)
    if expected > limits.image_bytes:
        raise SldFormatError("the PNG's pixels are too large", detail={"limit": "image_bytes"})
    d = zlib.decompressobj()
    try:
        raw = d.decompress(b"".join(idat), expected + 1)
    except zlib.error as exc:
        raise SldFormatError(f"the PNG's pixel data is damaged: {exc}") from None
    if len(raw) != expected or not d.eof:
        raise SldFormatError("the PNG's pixel data is not the size its header says")
    off = 0
    for rb, h in sizes:
        for _ in range(h):
            if raw[off] > 4:
                raise SldFormatError("a PNG row has an unknown filter")
            off += rb + 1
    out = PNG_SIGNATURE + _png_chunk(b"IHDR", ihdr)
    if plte is not None:
        out += _png_chunk(b"PLTE", plte)
    if trns is not None:
        out += _png_chunk(b"tRNS", trns)
    out += _png_chunk(b"IDAT", zlib.compress(raw, 6)) + _png_chunk(b"IEND", b"")
    return out, width, height


def bmp_size(data: bytes) -> tuple[int, int] | None:
    """``(width, height)`` of a Windows bitmap file, or None."""
    if len(data) < 26 or data[:2] != b"BM":
        return None
    w, h = struct.unpack_from("<ii", data, 18)
    return (w, abs(h)) if w > 0 and h else None


def bmp_to_png(data: bytes, limits: Limits) -> tuple[bytes, int, int]:
    """A stored Windows bitmap (``BM``, a ``BITMAPINFOHEADER`` or larger, one plane, 24 or
    32 bits a pixel, uncompressed) as an RGB PNG SolidSeas writes: ``(png, width,
    height)``. Every size and offset is checked against the data first; anything
    else raises :class:`SldFormatError`."""
    if len(data) < 54 or data[:2] != b"BM":
        raise SldFormatError("not a Windows bitmap")
    (file_size,) = struct.unpack_from("<I", data, 2)
    (pixel_offset,) = struct.unpack_from("<I", data, 10)
    header_size, width, height, planes, bpp, compression = struct.unpack_from("<IiiHHI", data, 14)
    if header_size < 40 or planes != 1 or bpp not in (24, 32) or compression != 0:
        raise SldFormatError("the bitmap is not an uncompressed 24- or 32-bit image")
    if file_size > len(data):
        raise SldFormatError("the bitmap's header claims more bytes than it has")
    rows = abs(height)
    if not (0 < width <= limits.image_side and 0 < rows <= limits.image_side):
        raise SldFormatError(
            f"the bitmap is {width} x {rows}, outside 1 to {limits.image_side}",
            detail={"limit": "image_side"},
        )
    step = bpp // 8
    stride = ((width * bpp + 31) // 32) * 4
    if pixel_offset < 14 + header_size or pixel_offset + stride * rows > len(data):
        raise SldFormatError("the bitmap's pixels lie outside its data")
    out = bytearray(width * 3 * rows)
    line = width * 3
    for y in range(rows):
        src_row = (rows - 1 - y) if height > 0 else y  # bottom-up unless the height is negative
        start = pixel_offset + src_row * stride
        row = data[start : start + width * step]
        dst = y * line
        out[dst : dst + line : 3] = row[2::step]
        out[dst + 1 : dst + line : 3] = row[1::step]
        out[dst + 2 : dst + line : 3] = row[0::step]
    return encode_png(width, rows, bytes(out), 3), width, rows


def preview_png(pv: Any, limits: Limits) -> tuple[bytes, int, int, str | None] | None:
    """A stored preview (a :class:`~solidseas.formats.solidworks.Preview`, or None) as a PNG
    SolidSeas wrote: ``(png, width, height, stream)``. A PNG is sanitised
    (:func:`sanitize_png`), a bitmap converted (:func:`bmp_to_png`); any other image
    type is not passed on (None). A damaged image raises :class:`SldFormatError`."""
    if pv is None:
        return None
    if pv.mime == "image/png":
        png, w, h = sanitize_png(pv.data, limits)
    elif pv.mime == "image/bmp":
        png, w, h = bmp_to_png(pv.data, limits)
    else:
        return None
    return png, w, h, pv.stream


def finite(*values: float) -> bool:
    return all(math.isfinite(v) for v in values)


__all__ = [
    "CHUNK",
    "PNG_SIGNATURE",
    "Clock",
    "ReadCancelledError",
    "SafeZip",
    "SiblingBudget",
    "Source",
    "XmlNode",
    "bmp_size",
    "bmp_to_png",
    "central_entries",
    "check_max_file_bytes",
    "clip_text",
    "encode_png",
    "finite",
    "first_member_name",
    "load_json",
    "opc_resolve",
    "open_source",
    "preview_png",
    "read_sibling",
    "sanitize_png",
    "sibling_path",
    "sibling_resolution",
    "xml_events",
    "xml_tree",
    "zip_directory_size",
]
