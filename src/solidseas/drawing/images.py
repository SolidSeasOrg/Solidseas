"""The narrow PNG reader for the logo (``docs/DRAWINGS.md`` 7.1, 12.1, 17.2).

The viewer stores the logo as an 8-bit RGB or RGBA, non-interlaced PNG of at
most 1,200 pixels a side and 512 KiB, and the PDF writer embeds only that form.
:func:`read_png` takes exactly that and nothing else: the size of the file and
of the image are checked from the header before any pixel data is touched,
every chunk's CRC is checked, the IDAT chunks are joined, the zlib stream is
inflated with its output bounded by what the header implies (``width * height *
channels + height`` bytes, one filter byte a row), and the five PNG row filters
are undone. Anything outside the form is refused with :class:`PngRefused`, which
says why, and is never decoded further.

Ancillary chunks (``gAMA``, ``pHYs``, ``tEXt`` and the like, a lower-case first
letter) are skipped unread, as the PNG specification allows. A suggested palette
(``PLTE``) in a true-colour image is skipped too. A transparency chunk
(``tRNS``) is refused: in the narrow form only RGBA carries alpha.

Pure Python. The Up and Sub filters are undone a row at a time with whole-row
integer arithmetic; Average and Paeth depend on the byte just decoded and go a
byte at a time, so a 1,200 by 1,200 RGBA logo filtered entirely with Paeth is
the slowest case (``docs/drawings/pdf.md`` gives the time).
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from ..errors import InvalidArgumentError
from .limits import DEFAULT_LIMITS, DrawingLimits

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_CHUNKS = 4096  # a logo the viewer writes has a handful
_CHANNELS = {2: 3, 6: 4}  # colour type: channels (RGB, RGBA)
_CRITICAL = (b"IHDR", b"PLTE", b"IDAT", b"IEND")


class PngRefused(InvalidArgumentError):
    """A PNG outside the narrow form of 7.1. The message says why in words;
    ``detail["rule"]`` names the rule broken (``not_png``, ``file_size``,
    ``image_size``, ``format``, ``chunk``, ``crc``, ``truncated``, ``pixels``,
    ``filter``)."""


def _refuse(message: str, rule: str) -> PngRefused:
    return PngRefused(message, detail={"parameter": "png", "rule": rule})


@dataclass(frozen=True)
class PngImage:
    """A decoded logo: ``rgb`` holds ``width * height * 3`` bytes, rows from the top;
    ``alpha`` holds ``width * height`` bytes for an RGBA PNG, else None."""

    width: int
    height: int
    rgb: bytes
    alpha: bytes | None


def _chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    """The chunks up to and including IEND, each ``(tag, body)``, CRCs checked."""
    out: list[tuple[bytes, bytes]] = []
    pos = len(PNG_SIGNATURE)
    while True:
        if len(out) >= MAX_CHUNKS:
            raise _refuse(f"the PNG has more than {MAX_CHUNKS} chunks", "chunk")
        if pos + 12 > len(data):
            raise _refuse("the PNG ends before its IEND chunk", "truncated")
        (length,) = struct.unpack_from(">I", data, pos)
        tag = data[pos + 4 : pos + 8]
        if not (len(tag) == 4 and all(0x41 <= c <= 0x5A or 0x61 <= c <= 0x7A for c in tag)):
            raise _refuse("the PNG has a chunk whose name is not four letters", "chunk")
        end = pos + 8 + length
        if length > 0x7FFFFFFF or end + 4 > len(data):
            raise _refuse("a PNG chunk runs past the end of the file", "truncated")
        body = data[pos + 8 : end]
        (crc,) = struct.unpack_from(">I", data, end)
        if zlib.crc32(tag + body) & 0xFFFFFFFF != crc:
            raise _refuse(f"the PNG's {tag.decode('ascii')} chunk has a wrong CRC", "crc")
        out.append((tag, body))
        pos = end + 4
        if tag == b"IEND":
            return out


def _header(ihdr: bytes, limits: DrawingLimits) -> tuple[int, int, int]:
    """``(width, height, channels)`` from IHDR, refusing anything outside the form."""
    if len(ihdr) != 13:
        raise _refuse("the PNG's header chunk is not 13 bytes", "chunk")
    width, height, depth, colour, compression, filtering, interlace = struct.unpack(">IIBBBBB", ihdr)
    side = limits.logo_pixels
    if not (0 < width <= side and 0 < height <= side):
        raise _refuse(
            f"the PNG is {width} x {height} pixels; a logo is at most {side:,} a side", "image_size"
        )
    if depth != 8:
        raise _refuse(f"the PNG has {depth}-bit samples; a logo is 8-bit RGB or RGBA", "format")
    if colour not in _CHANNELS:
        kinds = {0: "greyscale", 3: "a palette", 4: "greyscale with alpha"}
        kind = kinds.get(colour, f"colour type {colour}")
        raise _refuse(f"the PNG uses {kind}; a logo is 8-bit RGB or RGBA", "format")
    if compression != 0 or filtering != 0:
        raise _refuse("the PNG names an unknown compression or filter method", "format")
    if interlace != 0:
        raise _refuse("the PNG is interlaced; a logo is not", "format")
    return width, height, _CHANNELS[colour]


def _inflate(data: bytes, expected: int) -> bytes:
    """The zlib stream ``data`` inflated to exactly ``expected`` bytes; never more than
    ``expected + 1`` are produced, so a stream that would inflate further (a zlib
    bomb) costs no more than a valid one."""
    d = zlib.decompressobj()
    try:
        raw = d.decompress(data, expected + 1)
    except zlib.error as exc:
        raise _refuse(f"the PNG's pixel data is damaged ({exc})", "pixels") from None
    if len(raw) > expected:
        raise _refuse("the PNG's pixel data is longer than its header says", "pixels")
    if len(raw) < expected:
        raise _refuse("the PNG's pixel data is shorter than its header says", "pixels")
    if not d.eof:
        raise _refuse("the PNG's pixel data does not end where its header says", "pixels")
    if d.unused_data:
        raise _refuse("the PNG has bytes after the end of its pixel data", "pixels")
    return raw


def _masks(n: int) -> tuple[int, int]:
    return int.from_bytes(b"\x7f" * n, "big"), int.from_bytes(b"\x80" * n, "big")


def _add(x: int, y: int, low: int, high: int) -> int:
    """Byte-wise addition modulo 256 of two rows held as big integers: the low seven
    bits of each byte add without carrying into the next byte, and the top bit is
    the exclusive or of the two top bits and the carry into it."""
    return ((x & low) + (y & low)) ^ ((x ^ y) & high)


def _sub(row: bytes, bpp: int, low: int, high: int) -> bytes:
    """Undo Sub: each byte plus the decoded byte ``bpp`` to its left, as a prefix sum
    over strides of ``bpp`` taken in doubling steps."""
    n = len(row)
    x = int.from_bytes(row, "big")
    shift = bpp
    while shift < n:
        x = _add(x, x >> (8 * shift), low, high)
        shift *= 2
    return x.to_bytes(n, "big")


def _up(row: bytes, prev: bytes, low: int, high: int) -> bytes:
    n = len(row)
    return _add(int.from_bytes(row, "big"), int.from_bytes(prev, "big"), low, high).to_bytes(n, "big")


def _average(row: bytes, prev: bytes, bpp: int) -> bytes:
    cur = bytearray(row)
    for i in range(min(bpp, len(cur))):
        cur[i] = (cur[i] + (prev[i] >> 1)) & 0xFF
    for i in range(bpp, len(cur)):
        cur[i] = (cur[i] + ((cur[i - bpp] + prev[i]) >> 1)) & 0xFF
    return bytes(cur)


def _paeth(row: bytes, prev: bytes, bpp: int) -> bytes:
    cur = bytearray(row)
    for i in range(min(bpp, len(cur))):  # no left neighbour: the predictor is the byte above
        cur[i] = (cur[i] + prev[i]) & 0xFF
    for i in range(bpp, len(cur)):
        a = cur[i - bpp]
        b = prev[i]
        c = prev[i - bpp]
        pa = b - c if b >= c else c - b
        pb = a - c if a >= c else c - a
        pc = a + b - c - c
        if pc < 0:
            pc = -pc
        if pa <= pb and pa <= pc:
            cur[i] = (cur[i] + a) & 0xFF
        elif pb <= pc:
            cur[i] = (cur[i] + b) & 0xFF
        else:
            cur[i] = (cur[i] + c) & 0xFF
    return bytes(cur)


def _unfilter(raw: bytes, height: int, stride: int, bpp: int) -> bytearray:
    """The pixel rows with each row's filter undone (PNG specification, section 9)."""
    out = bytearray(height * stride)
    low, high = _masks(stride)
    prev = bytes(stride)
    pos = 0
    for y in range(height):
        kind = raw[pos]
        row = raw[pos + 1 : pos + 1 + stride]
        pos += stride + 1
        if kind == 0:
            cur = row
        elif kind == 1:
            cur = _sub(row, bpp, low, high)
        elif kind == 2:
            cur = _up(row, prev, low, high)
        elif kind == 3:
            cur = _average(row, prev, bpp)
        elif kind == 4:
            cur = _paeth(row, prev, bpp)
        else:
            raise _refuse(f"row {y + 1} of the PNG has the unknown filter type {kind}", "filter")
        out[y * stride : (y + 1) * stride] = cur
        prev = cur
    return out


def read_png(data: bytes, *, limits: DrawingLimits = DEFAULT_LIMITS) -> PngImage:
    """Decode a logo in the narrow form of 7.1, or raise :class:`PngRefused` saying
    why. ``limits.logo_bytes`` bounds the file and ``limits.logo_pixels`` each side."""
    if not isinstance(limits, DrawingLimits):
        raise InvalidArgumentError("limits must be DrawingLimits", detail={"parameter": "limits"})
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise _refuse("the logo is not bytes", "not_png")
    data = bytes(data)
    if len(data) > limits.logo_bytes:
        raise _refuse(f"the PNG is {len(data):,} bytes; a logo is at most {limits.logo_bytes:,}", "file_size")
    if data[: len(PNG_SIGNATURE)] != PNG_SIGNATURE:
        raise _refuse("the logo is not a PNG", "not_png")
    # The header is read and judged before any other chunk, so an image of the wrong
    # size or form is refused before its pixel data is so much as checked.
    if len(data) < 33 or data[12:16] != b"IHDR":
        raise _refuse("the PNG does not start with its header chunk", "chunk")
    _header(data[16:29], limits)
    chunks = _chunks(data)
    width, height, channels = _header(chunks[0][1], limits)
    idat: list[bytes] = []
    idat_done = False
    for tag, body in chunks[1:]:
        name = tag.decode("ascii")
        if tag == b"IHDR":
            raise _refuse("the PNG has a second header chunk", "chunk")
        if tag == b"IDAT":
            if idat_done:
                raise _refuse("the PNG's IDAT chunks are not consecutive", "chunk")
            idat.append(body)
            continue
        if idat:
            idat_done = True
        if tag == b"IEND":
            break  # _chunks stops at IEND; anything after it is never read
        if tag == b"PLTE":
            if idat:
                raise _refuse("the PNG's palette follows its pixel data", "chunk")
        elif tag == b"tRNS":
            raise _refuse(
                "the PNG has a transparency chunk (tRNS); a logo carries alpha only as RGBA", "format"
            )
        elif tag[0] < 0x61 and tag not in _CRITICAL:
            raise _refuse(f"the PNG has the unknown critical chunk {name}", "chunk")
    if not idat:
        raise _refuse("the PNG has no pixel data", "truncated")
    stride = width * channels
    raw = _inflate(b"".join(idat), height * (stride + 1))
    pixels = _unfilter(raw, height, stride, channels)
    if channels == 3:
        return PngImage(width, height, bytes(pixels), None)
    rgb = bytearray(width * height * 3)
    rgb[0::3] = pixels[0::4]
    rgb[1::3] = pixels[1::4]
    rgb[2::3] = pixels[2::4]
    return PngImage(width, height, bytes(rgb), bytes(pixels[3::4]))


def png_size(data: bytes, *, limits: DrawingLimits = DEFAULT_LIMITS) -> tuple[int, int]:
    """``(width, height)`` of a logo in pixels, from its header alone (the title block
    keeps the logo's proportions); :class:`PngRefused` for a header outside the narrow
    form of 7.1. Nothing past the header is read."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise _refuse("the logo is not bytes", "not_png")
    head = bytes(data[:33])
    if head[: len(PNG_SIGNATURE)] != PNG_SIGNATURE:
        raise _refuse("the logo is not a PNG", "not_png")
    if len(head) < 33 or head[12:16] != b"IHDR":
        raise _refuse("the PNG does not start with its header chunk", "chunk")
    width, height, _channels = _header(head[16:29], limits)
    return width, height


def png_problem(data: bytes, *, limits: DrawingLimits = DEFAULT_LIMITS) -> str | None:
    """Why ``data`` is not a logo the PDF writer embeds, or None when it is."""
    try:
        read_png(data, limits=limits)
    except PngRefused as exc:
        return str(exc)
    return None


__all__ = ["MAX_CHUNKS", "PNG_SIGNATURE", "PngImage", "PngRefused", "png_problem", "png_size", "read_png"]
