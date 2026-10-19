"""The SOLIDWORKS "ZLB" wrapper and the length-prefixed ZLB chain.

A ZLB block is a 16-byte magic followed by chunks of ``u32 usize, u32 csize,
csize bytes of zlib data`` and a terminating ``(0, 0)`` chunk header. It is the
compression of every legacy OLE stream whose name ends in ``__ZLB`` and, in
both container generations, the framing of embedded Parasolid data.

A ZLB chain is ``(u32 length, length bytes holding one ZLB block)*`` up to the
end of the data. ``Contents/Config-<n>-Partition`` and
``Contents/Config-<n>-GhostPartition`` use it in both generations.

All integers are little-endian. See ``docs/FORMAT.md`` for the evidence.
"""

import struct
import zlib
from collections.abc import Iterator

from .errors import SldFormatError, SldIntegrityError, SldLimitError

ZLB_MAGIC = bytes.fromhex("231dd571da8148a2a85898b21b89ef99")
MAX_STREAM_BYTES = 1 << 30  # hard cap on any single decoded stream or block (1 GiB)


def _chunks(data: bytes, off: int) -> tuple[list[tuple[int, int, int]], int]:
    """Parse the chunk headers of one ZLB block at ``data[off:]``.

    Returns ``([(usize, data_start, csize), ...], end_offset)``.
    """
    if data[off : off + 16] != ZLB_MAGIC:
        raise SldFormatError(f"ZLB magic missing at offset {off}")
    i = off + 16
    n = len(data)
    chunks = []
    while True:
        if i + 8 > n:
            raise SldFormatError(f"truncated ZLB chunk header at offset {i}")
        usize, csize = struct.unpack_from("<II", data, i)
        i += 8
        if usize == 0 and csize == 0:
            return chunks, i
        if csize == 0 or i + csize > n:
            raise SldFormatError(f"bad ZLB chunk at offset {i - 8} (usize {usize}, csize {csize})")
        chunks.append((usize, i, csize))
        i += csize


def zlb_size(data: bytes, off: int = 0) -> tuple[int, int]:
    """``(decoded size, end offset)`` of the ZLB block at ``data[off:]``, without inflating it."""
    chunks, end = _chunks(data, off)
    return sum(u for u, _, _ in chunks), end


def unwrap_zlb(
    data: bytes, off: int = 0, *, max_bytes: int = MAX_STREAM_BYTES, require_end: bool = True
) -> bytes:
    """Decode one ZLB block starting at ``data[off:]``.

    Every chunk must inflate (zlib, RFC 1950, Adler-32 checked by zlib) to
    exactly its declared size. With ``require_end`` the block must end exactly
    at ``len(data)``. The declared total is checked against ``max_bytes``
    before anything is inflated.
    """
    chunks, end = _chunks(data, off)
    if require_end and end != len(data):
        raise SldFormatError(f"{len(data) - end} bytes after the end of the ZLB block")
    total = sum(u for u, _, _ in chunks)
    if total > max_bytes:
        raise SldLimitError(f"ZLB block decodes to {total} bytes, cap is {max_bytes}")
    parts = []
    mv = memoryview(data)
    for usize, start, csize in chunks:
        d = zlib.decompressobj()
        try:
            out = d.decompress(mv[start : start + csize], usize + 1)
        except zlib.error as exc:
            raise SldFormatError(f"corrupt ZLB chunk at offset {start}: {exc}") from exc
        if len(out) != usize or not d.eof or d.unused_data or d.unconsumed_tail:
            tail = "" if d.eof else ", stream not terminated"
            raise SldIntegrityError(
                f"ZLB chunk at offset {start}: inflated {len(out)} bytes, declared {usize}{tail}"
            )
        parts.append(out)
    return b"".join(parts)


def iter_zlb_chain(data: bytes, *, max_bytes: int = MAX_STREAM_BYTES) -> Iterator[bytes]:
    """Decode a chain of length-prefixed ZLB blocks, yielding each decoded block.

    A zero length yields ``b""``. ``max_bytes`` caps the total decoded size of
    the whole chain.
    """
    i, n, budget = 0, len(data), max_bytes
    while i < n:
        if i + 4 > n:
            raise SldFormatError(f"truncated chain length at offset {i}")
        (length,) = struct.unpack_from("<I", data, i)
        i += 4
        if i + length > n:
            raise SldFormatError(f"chain block at offset {i} overruns the data")
        if length == 0:
            yield b""
            continue
        block = unwrap_zlb(data[i : i + length], 0, max_bytes=budget)
        budget -= len(block)
        yield block
        i += length


def iter_chain_blocks(data: bytes) -> Iterator[tuple[int, bytes]]:
    """``(decoded size, ZLB block)`` for every block of a ZLB chain, without inflating anything.

    The block is still compressed, so a caller can check the declared size
    against its own budget before paying for :func:`unwrap_zlb`. An empty block
    gives ``(0, b"")``.
    """
    i, n = 0, len(data)
    while i < n:
        if i + 4 > n:
            raise SldFormatError(f"truncated chain length at offset {i}")
        (length,) = struct.unpack_from("<I", data, i)
        i += 4
        if i + length > n:
            raise SldFormatError(f"chain block at offset {i} overruns the data")
        block = data[i : i + length]
        yield (zlb_size(block)[0] if length else 0), block
        i += length


def chain_sizes(data: bytes) -> list[int]:
    """Decoded size of every block of a ZLB chain, without inflating anything."""
    return [size for size, _ in iter_chain_blocks(data)]


def peek_zlb(data: bytes, n: int, off: int = 0) -> bytes:
    """The first ``n`` decoded bytes of the ZLB block at ``data[off:]``, inflating no more than that."""
    chunks, _ = _chunks(data, off)
    out = bytearray()
    mv = memoryview(data)
    for _usize, start, csize in chunks:
        if len(out) >= n:
            break
        d = zlib.decompressobj()
        try:
            out += d.decompress(mv[start : start + csize], n - len(out))
        except zlib.error as exc:
            raise SldFormatError(f"corrupt ZLB chunk at offset {start}: {exc}") from exc
    return bytes(out[:n])
