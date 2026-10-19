"""The legacy SOLIDWORKS container: an MS-CFB (OLE) compound file.

Every legacy document in the development corpus is a standard version 3
compound file with 512-byte sectors, which ``olefile`` reads unaided. Stream
names are the CFB names joined with ``/``; the property sets keep their leading
``\\x05``. A stream whose name ends in ``__ZLB`` carries the ZLB wrapper
(:mod:`.zlb`), which :meth:`OleContainer.read` removes.

Aliases accepted by :meth:`~.container.Container.info`: the property-set names
without their ``\\x05``, ``<name>`` for ``<name>__ZLB``, and a unique
case-insensitive match (some files write ``config-0`` in lower case).

``olefile`` parses the header, the FAT and the directory. Stream bytes are read
here, from the sector chains olefile parsed, and only the bytes asked for: the
decoded size of a ``__ZLB`` stream comes from its chunk headers, and
:meth:`OleContainer.peek` reads only the head of a stream. Runs of contiguous
sectors are read in one call. With a document held open
(``open_document(..., hold_open=True)``), a folder listing therefore reads a
small part of each file instead of all of it.

Every size and count a chain walk depends on is checked against the file
before the walk: a stream, the mini stream (the root entry's size) and the mini
allocation table must each fit in the file, and a chain may not be longer than
its allocation table, because a longer chain has to visit a sector twice. A
crafted file that declares a huge mini stream and loops its chain therefore
fails at once instead of walking billions of sectors.
"""

import struct
from collections.abc import Iterator
from typing import Any, BinaryIO

from ._io import lock_error, pread
from .container import Container, StreamInfo
from .errors import (
    LockedFileError,
    ReaderWarning,
    SldError,
    SldFormatError,
    SldIntegrityError,
    SldLimitError,
)
from .zlb import MAX_STREAM_BYTES, ZLB_MAGIC, unwrap_zlb, zlb_size

MAX_STORAGE_DEPTH = 64  # nested storages; olefile's own tree build recurses as deep
_ZLB_HEADER_READS = 256  # chunk headers read one by one before reading the stream whole


class OleContainer(Container):
    """A legacy OLE container. Create it with :func:`~.container.open_container`."""

    format = "ole"

    def __init__(self, fh: BinaryIO, size: int, path: str | None, strict: bool, depth: int):
        super().__init__()
        try:
            import olefile
        except ImportError as exc:  # pragma: no cover - olefile is a declared dependency
            raise SldError("olefile is required to read legacy (OLE) SOLIDWORKS files") from exc
        self._fh, self.file_size, self.path, self._depth = fh, size, path, depth
        try:
            self._ole = olefile.OleFileIO(fh)
        except Exception as exc:  # olefile raises OSError, IndexError, struct.error on damage
            raise SldFormatError(f"not a readable OLE compound file: {exc}") from exc
        for _exc_type, msg in getattr(self._ole, "parsing_issues", None) or []:
            self.warnings.append(ReaderWarning("ole_parsing_issue", f"olefile: {msg}"))
        self._entries: list[list[str]] = []
        self._dir: list[Any] = []  # olefile directory entries, parallel to _infos
        self._codecs: list[str] = []
        self._raw_sizes: list[int] = []
        self._chains: dict[int, list[int]] = {}
        self._minifat: Any = None
        self._root_chain: list[int] | None = None
        try:
            self._list(strict)
        except SldError:
            raise
        except Exception as exc:
            raise SldFormatError(f"corrupt OLE directory: {exc}") from exc
        root = self._ole.root
        self.meta.update(
            root_clsid=(root.clsid or "").upper() or None,
            sector_size=self._ole.sectorsize,
            entries=len(self._infos),
        )

    def close(self) -> None:
        if not self._closed and getattr(self, "_ole", None) is not None:
            try:
                self._ole.close()
            except Exception:
                pass
        super().close()

    # stream bytes ----------------------------------------------------------------
    def _chain(
        self, start: int, count: int, fat: Any, what: str, out: list[int] | None = None
    ) -> list[int]:
        """The first ``count`` sector numbers of the chain starting at ``start``.

        A chain longer than its allocation table must visit some sector twice, so it
        is refused before the walk (olefile's "stream too large" rule). ``out`` is a
        prefix of the same chain already walked; the walk continues from its end.
        """
        n_fat = len(fat)
        if count > n_fat:
            raise SldFormatError(
                f"{what}: needs {count} sectors but the allocation table has {n_fat}; the chain must loop"
            )
        if out is None:
            out = []
        s = fat[out[-1]] if out else start
        while len(out) < count:
            if not 0 <= s < n_fat:
                raise SldFormatError(f"{what}: the sector chain ends early or leaves the allocation table")
            out.append(s)
            s = fat[s]
        return out

    def _check_ministream(self) -> None:
        """The mini stream and its allocation table must fit in the file before any
        chain through them is walked or the table is loaded."""
        ole = self._ole
        if ole.root.size > self.file_size:
            raise SldFormatError(
                f"the mini stream declares {ole.root.size} bytes, more than the file's {self.file_size}"
            )
        minifat_bytes = (ole.num_mini_fat_sectors or 0) * ole.sectorsize
        if minifat_bytes > self.file_size:
            raise SldFormatError(
                f"the mini allocation table declares {minifat_bytes} bytes, "
                f"more than the file's {self.file_size}"
            )

    def _stream_chain(self, index: int) -> list[int]:
        chain = self._chains.get(index)
        if chain is None:
            ole, raw_size = self._ole, self._raw_sizes[index]
            what = "/".join(self._entries[index])
            if raw_size < ole.minisectorcutoff:
                if self._minifat is None:
                    self._check_ministream()
                    try:
                        ole.loadminifat()
                    except Exception as exc:
                        raise SldFormatError(f"corrupt OLE mini allocation table: {exc}") from exc
                    self._minifat = ole.minifat
                unit, fat = ole.minisectorsize, self._minifat
            else:
                unit, fat = ole.sectorsize, ole.fat
            chain = self._chain(self._dir[index].isectStart, -(-raw_size // unit), fat, what)
            self._chains[index] = chain
        return chain

    def _ministream_segments(self, offset: int, n: int) -> list[tuple[int, int]]:
        """File ``(offset, length)`` runs holding bytes ``[offset, offset + n)`` of the mini stream.

        The mini stream's own chain is walked only as far as the last sector asked
        for, and extended on later calls."""
        ole = self._ole
        root_size, ss = ole.root.size, ole.sectorsize
        if offset + n > root_size:
            raise SldFormatError("a mini stream sector lies beyond the end of the mini stream")
        self._check_ministream()
        need = -(-(offset + n) // ss)
        if self._root_chain is None or len(self._root_chain) < need:
            prefix = self._root_chain
            self._root_chain = self._chain(ole.root.isectStart, need, ole.fat, "mini stream", prefix)
        out = []
        end = offset + n
        while offset < end:
            k, within = divmod(offset, ss)
            take = min(end - offset, ss - within)
            out.append(((self._root_chain[k] + 1) * ss + within, take))
            offset += take
        return out

    def _read_range(self, index: int, start: int, n: int) -> bytes:
        """Bytes ``[start, start + n)`` of stream ``index``, read from the sectors that hold
        them and nothing else. Contiguous sectors are read in one call."""
        raw_size = self._raw_sizes[index]
        what = "/".join(self._entries[index])
        if start < 0 or n < 0 or start + n > raw_size:
            raise SldFormatError(f"{what}: read of [{start}, {start + n}) outside the stream")
        if n == 0:
            return b""
        if raw_size > self.file_size:
            raise SldFormatError(f"{what}: stream size {raw_size} exceeds the file size")
        ole = self._ole
        mini = raw_size < ole.minisectorcutoff
        unit = ole.minisectorsize if mini else ole.sectorsize
        chain = self._stream_chain(index)
        segments: list[tuple[int, int]] = []
        pos, end = start, start + n
        while pos < end:
            k, within = divmod(pos, unit)
            take = min(end - pos, unit - within)
            if mini:
                segments.extend(self._ministream_segments(chain[k] * unit + within, take))
            else:
                segments.append(((chain[k] + 1) * unit + within, take))
            pos += take
        runs: list[list[int]] = []
        for off, length in segments:
            if runs and runs[-1][0] + runs[-1][1] == off:
                runs[-1][1] += length
            else:
                runs.append([off, length])
        try:
            parts = [pread(self._fh, off, length) for off, length in runs]
        except (SldError, LockedFileError):
            raise
        except PermissionError as exc:  # a byte-range lock on Windows; access denied elsewhere
            locked = lock_error(exc, f"{what}: byte range locked by another process")
            if locked is None:
                raise
            raise locked from exc
        except Exception as exc:
            raise SldFormatError(f"{what}: unreadable OLE stream: {exc}") from exc
        return parts[0] if len(parts) == 1 else b"".join(parts)

    def _zlb_extent(self, index: int) -> tuple[int, int] | None:
        """``(decoded size, end offset)`` of the ZLB block in stream ``index``, from its chunk
        headers alone; None when the stream does not start with the ZLB magic."""
        raw_size = self._raw_sizes[index]
        if raw_size < 16 or self._read_range(index, 0, 16) != ZLB_MAGIC:
            return None
        i, total = 16, 0
        for _ in range(_ZLB_HEADER_READS):
            if i + 8 > raw_size:
                raise SldFormatError(f"truncated ZLB chunk header at offset {i}")
            usize, csize = struct.unpack("<II", self._read_range(index, i, 8))
            i += 8
            if usize == 0 and csize == 0:
                return total, i
            if csize == 0 or i + csize > raw_size:
                raise SldFormatError(f"bad ZLB chunk at offset {i - 8} (usize {usize}, csize {csize})")
            total += usize
            i += csize
        return zlb_size(self._read_range(index, 0, raw_size))  # many small chunks: one read

    def _walk(self) -> list[tuple[list[str], Any]]:
        """``(path parts, directory entry)`` of every stream, in ``olefile.listdir`` order."""
        import olefile

        out: list[tuple[list[str], Any]] = []

        def visit(node: Any, prefix: list[str], depth: int) -> None:
            if depth > MAX_STORAGE_DEPTH:
                raise SldLimitError(f"storages nested deeper than {MAX_STORAGE_DEPTH}")
            for kid in node.kids:
                if kid.entry_type == olefile.STGTY_STORAGE:
                    visit(kid, [*prefix, kid.name], depth + 1)
                elif kid.entry_type == olefile.STGTY_STREAM:
                    out.append(([*prefix, kid.name], kid))

        visit(self._ole.root, [], 0)
        return out

    def _list(self, strict: bool) -> None:
        infos = []
        for i, (parts, entry) in enumerate(self._walk()):
            name = "/".join(parts)
            raw_size = entry.size
            self._entries.append(parts)
            self._dir.append(entry)
            self._raw_sizes.append(raw_size)
            codec, size, csize = "none", raw_size, None
            if name.endswith("__ZLB"):
                extent = self._zlb_extent(i)
                if extent is not None:
                    size, end = extent
                    if end != raw_size:
                        raise SldFormatError(f"{name}: {raw_size - end} bytes after the ZLB block")
                    codec, csize = "zlb", raw_size
                else:
                    msg = "name ends in __ZLB but the ZLB magic is missing; exposed raw"
                    if strict and raw_size:
                        raise SldFormatError(f"{name}: {msg}")
                    self.warnings.append(ReaderWarning("zlb_magic_missing", msg, name))
            self._codecs.append(codec)
            infos.append(
                StreamInfo(name=name, size=size, compressed_size=csize, offset=None, codec=codec, index=i)
            )
        self._infos = infos
        self._by_name = {}
        for i, s in enumerate(infos):
            self._by_name.setdefault(s.name, i)

    def _aliases(self, name: str) -> list[str]:
        out = []
        parts = name.split("/")
        if parts[-1] in ("SummaryInformation", "DocumentSummaryInformation"):
            out.append("/".join([*parts[:-1], "\x05" + parts[-1]]))
        if not name.endswith("__ZLB"):
            out.append(name + "__ZLB")
        return out

    def iter_read(
        self, name: str, *, max_bytes: int = MAX_STREAM_BYTES, verify: str = "auto"
    ) -> Iterator[bytes]:
        self._check_open()
        info = self.info(name)
        if info.size > max_bytes:
            raise SldLimitError(f"{info.name}: size {info.size} exceeds cap {max_bytes}")
        data = self._read_range(info.index, 0, self._raw_sizes[info.index])
        if self._codecs[info.index] == "zlb":
            data = unwrap_zlb(data, max_bytes=max_bytes)
        if len(data) != info.size:
            raise SldIntegrityError(f"{info.name}: decoded {len(data)} bytes, expected {info.size}")
        return iter((data,))

    def read_raw(self, name: str, *, max_bytes: int = MAX_STREAM_BYTES) -> bytes:
        self._check_open()
        info = self.info(name)
        raw_size = self._raw_sizes[info.index]
        if raw_size > max_bytes:
            raise SldLimitError(f"{info.name}: stored size {raw_size} exceeds cap {max_bytes}")
        return self._read_range(info.index, 0, raw_size)

    def peek(self, name: str, n: int = 16) -> bytes:
        """The first ``n`` decoded bytes of a stream. A stream without ZLB wrapping is read
        only as far as ``n``; a ``__ZLB`` stream is decoded whole."""
        self._check_open()
        info = self.info(name)
        if self._codecs[info.index] == "zlb":
            return super().peek(name, n)
        return self._read_range(info.index, 0, min(max(n, 0), self._raw_sizes[info.index]))
