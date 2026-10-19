"""Read-only access to the streams of a SOLIDWORKS document.

Two container generations exist (``docs/FORMAT.md`` has the byte-level spec):

* ``"modern"``: file bytes 4 to 7 are ``00 00 00 04``. An 8-byte header followed
  by a PKZIP archive whose stored offsets are relative to byte 8, with per-file
  record signatures, nibble-swapped member names, raw DEFLATE members and decoy
  records. Written by SOLIDWORKS 2015 and later. See :mod:`.modern`.
* ``"ole"``: an MS-CFB compound file. Streams named ``*__ZLB`` carry the ZLB
  wrapper. Written by SOLIDWORKS 2014 and earlier. See :mod:`.ole`.

:func:`open_container` detects the generation from the first 8 bytes and
returns a :class:`Container`. ``Container.read(name)`` returns a stream with
the container's own compression removed; content-level framing (for example
the ZLB chain inside ``Contents/Config-0-Partition``) is left to the decoders.

Safety: source files are opened read-only and share-tolerant, nothing is ever
written, every decompression is capped (1 GiB per stream by default) and every
structural length is bounds-checked, so malformed input raises a subclass of
:class:`~.errors.SldError` instead of hanging or exhausting memory.
"""

import io
import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO

from ...errors import InvalidArgumentError, LinkRefusedError
from ._io import open_readonly, pread
from .errors import (
    FileTooLargeError,
    ReaderWarning,
    SldError,
    SldLimitError,
    StreamNotFoundError,
    UnknownFormatError,
)
from .zlb import MAX_STREAM_BYTES

MODERN_MAGIC = b"\x00\x00\x00\x04"  # file bytes 4..7 of the 2015+ container
OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")
MAX_NEST_DEPTH = 16  # nesting limit for open_nested (deepest seen in the corpus: 5)

PathOrBytes = str | os.PathLike | bytes | bytearray | memoryview


@dataclass(frozen=True)
class StreamInfo:
    """One stream of a container.

    name             exact stored name, ``/``-separated. Modern: the decoded member
                     name. OLE: the storage path with the exact OLE names, for example
                     ``"\\x05SummaryInformation"`` or ``"Contents/DisplayLists__ZLB"``.
    size             length of the bytes ``read()`` returns
    compressed_size  stored length when the container compresses the stream, else None
    offset           modern: absolute file offset of the local header; OLE: None
    data_offset      modern: absolute file offset of the stored data; OLE: None
    codec            ``"deflate"`` or ``"stored"`` (modern), ``"zlb"`` or ``"none"`` (OLE)
    crc32            modern: declared CRC-32 of the decoded data; OLE: None
    index            position in the container's directory order
    dos_time         modern: the opaque ZIP "time" field (not a timestamp); OLE: None
    dos_date         modern: the opaque ZIP "date" field (not a timestamp); OLE: None
    """

    name: str
    size: int
    compressed_size: int | None
    offset: int | None
    data_offset: int | None = None
    codec: str = "none"
    crc32: int | None = None
    index: int = 0
    dos_time: int | None = None
    dos_date: int | None = None


class Container:
    """An open SOLIDWORKS container. Create one with :func:`open_container`."""

    format: str = ""

    def __init__(self) -> None:
        self.path: str | None = None
        self.file_size: int = 0
        self.meta: dict[str, object] = {}
        self.warnings: list[ReaderWarning] = []
        # (st_size, st_mtime_ns) from the open handle of the source file; None for bytes input
        self.file_stat: tuple[int, int] | None = None
        # (st_dev, st_ino, st_nlink) from the same fstat: which file this is on its volume,
        # whatever its name (the catalog follows a moved file by it); None for bytes input
        self.file_ident: tuple[int, int, int] | None = None
        self._fh: BinaryIO | None = None
        self._infos: list[StreamInfo] = []
        self._by_name: dict[str, int] = {}
        self._depth = 0
        self._closed = False

    # lifecycle -------------------------------------------------------------
    def close(self) -> None:
        if not self._closed:
            self._closed = True
            if self._fh is not None:
                try:
                    self._fh.close()
                finally:
                    self._fh = None

    def __enter__(self) -> "Container":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self):  # pragma: no cover - best effort
        try:
            self.close()
        except Exception:
            pass

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.format} {self.path or '<memory>'!r} streams={len(self._infos)}>"

    def _check_open(self) -> None:
        if self._closed:
            raise ValueError("I/O operation on a closed container")

    # directory ---------------------------------------------------------------
    def streams(self) -> list[StreamInfo]:
        """All streams in directory order."""
        return list(self._infos)

    def names(self) -> list[str]:
        return [s.name for s in self._infos]

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        try:
            self.info(name)
        except KeyError:
            return False
        return True

    def info(self, name: str) -> StreamInfo:
        """Look a stream up by exact name, then by the container's aliases, then
        by a unique case-insensitive match. Raises :class:`~.errors.StreamNotFoundError`,
        which is a ``KeyError``."""
        idx = self._by_name.get(name)
        if idx is None:
            for alt in self._aliases(name):
                idx = self._by_name.get(alt)
                if idx is not None:
                    break
        if idx is None:
            low = name.lower()
            hits = [i for i, s in enumerate(self._infos) if s.name.lower() == low]
            if len(hits) == 1:
                idx = hits[0]
        if idx is None:
            raise StreamNotFoundError(f"no stream named {name!r}", detail={"stream": name})
        return self._infos[idx]

    def _aliases(self, name: str) -> list[str]:
        return []

    # data -----------------------------------------------------------------------
    def read(self, name: str, *, max_bytes: int = MAX_STREAM_BYTES, verify: str = "auto") -> bytes:
        """Decoded stream bytes, with the container's compression removed.

        ``verify`` (modern containers): ``"auto"`` checks size and CRC-32 unless the
        file stores one constant CRC for every member (then the size only, with a
        warning), ``"strict"`` always checks both, ``"size"`` checks the size only and
        ``"none"`` only enforces the caps. Legacy ZLB chunks are always size-checked.
        """
        return b"".join(self.iter_read(name, max_bytes=max_bytes, verify=verify))

    def iter_read(
        self, name: str, *, max_bytes: int = MAX_STREAM_BYTES, verify: str = "auto"
    ) -> Iterator[bytes]:
        raise NotImplementedError

    def read_raw(self, name: str, *, max_bytes: int = MAX_STREAM_BYTES) -> bytes:
        """Stored bytes of the stream, without decompression."""
        raise NotImplementedError

    def peek(self, name: str, n: int = 16) -> bytes:
        """The first ``n`` decoded bytes of a stream (decodes only as much as needed)."""
        out = bytearray()
        for chunk in self.iter_read(name, verify="none"):
            out += chunk
            if len(out) >= n:
                break
        return bytes(out[:n])

    def is_nested_document(self, name: str) -> bool:
        """True when the decoded stream starts like a SOLIDWORKS container of either generation."""
        head = self.peek(name, 8)
        return head == OLE_MAGIC or (len(head) == 8 and head[4:8] == MODERN_MAGIC)

    def open_nested(self, name: str, *, strict: bool = True) -> "Container":
        """Open a stream that is itself a document (an assembly's ``VirtualComp/...``
        or ``ImportedComp/...`` member) as an in-memory container."""
        if self._depth + 1 > MAX_NEST_DEPTH:
            raise SldLimitError(f"nesting deeper than {MAX_NEST_DEPTH}")
        data = self.read(name)
        return _open_data(
            data, label=f"{self.path or '<memory>'}:{name}", strict=strict, depth=self._depth + 1
        )


def detect_format(head: bytes) -> str | None:
    """``"modern"``, ``"ole"`` or None, from the first 8 bytes of a file."""
    if head[:8] == OLE_MAGIC:
        return "ole"
    if len(head) >= 8 and head[4:8] == MODERN_MAGIC:
        return "modern"
    return None


def _open_handle(fh: BinaryIO, size: int, path: str | None, strict: bool, depth: int) -> Container:
    head = pread(fh, 0, min(8, size)) if size else b""
    fmt = detect_format(head)
    if fmt == "modern":
        from .modern import ModernContainer

        return ModernContainer(fh, size, path, strict, depth)
    if fmt == "ole":
        from .ole import OleContainer

        return OleContainer(fh, size, path, strict, depth)
    raise UnknownFormatError(
        f"{path or '<memory>'}: not a SOLIDWORKS document (first bytes {head.hex() or '<empty>'})"
    )


def _open_data(data: bytes, label: str, strict: bool, depth: int) -> Container:
    fh = io.BytesIO(bytes(data))
    try:
        container = _open_handle(fh, len(data), None, strict, depth)
    except BaseException:
        fh.close()
        raise
    container.meta["source"] = label
    return container


MAX_IN_MEMORY_BYTES = 512 << 20  # files up to this size are read whole and the handle closed


def _check_size(size: int, max_file_bytes: int | None, label: str) -> None:
    if max_file_bytes is not None and size > max_file_bytes:
        raise FileTooLargeError(
            f"{label}: {size} bytes exceeds the limit of {max_file_bytes} bytes",
            detail={"limit": max_file_bytes, "value": size},
        )


def open_container(
    src: PathOrBytes,
    *,
    strict: bool = True,
    hold_open: bool = False,
    max_in_memory: int = MAX_IN_MEMORY_BYTES,
    max_file_bytes: int | None = None,
    within: str | os.PathLike | None = None,
    refuse_hard_links: bool = False,
) -> Container:
    """Open a SOLIDWORKS document read-only and parse its directory.

    ``src`` is a path or a bytes-like object holding a whole document. Raises
    :class:`~.errors.LockedFileError` when another process holds the file
    exclusively, :class:`~.errors.UnknownFormatError` for anything that is
    neither container generation, and :class:`~.errors.SldFormatError` for
    malformed structure. With ``strict=False`` disagreements between a modern
    local header and its central-directory copy become warnings.

    By default a file of up to ``max_in_memory`` bytes is read whole and its
    handle closed before this returns, so a long-lived container never stops
    SOLIDWORKS from saving over the file. ``hold_open=True``, or a larger file,
    keeps a shared read-only handle until :meth:`Container.close`.

    ``max_file_bytes`` refuses a larger file with
    :class:`~.errors.FileTooLargeError` before any byte is read: the size comes
    from ``fstat`` on the open handle, which also gives
    :attr:`Container.file_stat`.

    ``within`` names a folder the file must lie below. The file is then opened
    without following any link, junction or mount point below that folder and
    without recalling a cloud placeholder (see :mod:`._io`); the folder listing
    and ``batch`` open what the walker found this way, so a name replaced by a
    link after the folder was listed is refused with
    :class:`~solidseas.errors.LinkRefusedError` instead of being followed.

    ``refuse_hard_links`` refuses a file that has more than one name
    (``st_nlink`` above 1 on the open handle) with
    :class:`~solidseas.errors.LinkRefusedError` (rule ``hard_link``) before any
    byte is read: another name for the same data may lie outside the folder a
    caller confines reads to. The REST service sets it.
    """
    if isinstance(src, (bytes, bytearray, memoryview)):
        if within is not None:
            raise InvalidArgumentError(
                "within applies to a path, not to bytes", detail={"parameter": "within"}
            )
        data = bytes(src)
        _check_size(len(data), max_file_bytes, "<memory>")
        return _open_data(data, "<memory>", strict, 0)
    path = os.fspath(src)
    fh = open_readonly(path) if within is None else open_readonly(path, within=os.fspath(within))
    try:
        st = os.fstat(fh.fileno())
        size = st.st_size
        if refuse_hard_links and st.st_nlink > 1:
            raise LinkRefusedError(
                f"{path}: the file has more than one name, and another may lie outside the folder",
                detail={"rule": "hard_link"},
            )
        _check_size(size, max_file_bytes, path)
        if not hold_open and size <= max_in_memory:
            data = pread(fh, 0, size) if size else b""
            fh.close()
            mem = io.BytesIO(data)
            try:
                container = _open_handle(mem, size, path, strict, 0)
            except BaseException:
                mem.close()
                raise
        else:
            container = _open_handle(fh, size, path, strict, 0)
    except BaseException:
        fh.close()
        raise
    container.file_stat = (size, st.st_mtime_ns)
    container.file_ident = (st.st_dev, st.st_ino, st.st_nlink)
    return container


__all__ = [
    "Container",
    "MAX_NEST_DEPTH",
    "MAX_STREAM_BYTES",
    "MODERN_MAGIC",
    "OLE_MAGIC",
    "SldError",
    "StreamInfo",
    "detect_format",
    "open_container",
]
