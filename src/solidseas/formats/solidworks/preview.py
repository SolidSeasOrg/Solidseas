"""Saved preview images.

A document stores at most two preview streams, under the same names in both
container generations:

* ``PreviewPNG``: a PNG, 640 x 480, 8-bit RGBA, fully opaque.
* ``Preview``: ``u32 length`` followed by a packed DIB (BITMAPINFOHEADER, 8 bpp,
  BI_RLE8, bottom-up) sized like the SOLIDWORKS graphics area at save time.

Rarer image streams are per-configuration previews (``Config-<n>-PreviewPNG``,
``Config-<n>-Preview``) and drawing sheets (``Images/Sheet_<n>``, PNG). About a
third of the documents in the development corpus store no preview at all. See
``docs/FORMAT.md`` for the evidence behind each statement.
"""

import io
import re
import struct
from dataclasses import dataclass

from .container import Container
from .errors import SldFormatError

MAX_PREVIEW_BYTES = 256 << 20  # any preview stream larger than this is refused
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class Preview:
    """A preview image: complete file bytes (PNG or BMP) plus its dimensions."""

    data: bytes
    mime: str  # "image/png" or "image/bmp"
    width: int
    height: int
    stream: str  # the stream it came from

    @property
    def extension(self) -> str:
        return ".png" if self.mime == "image/png" else ".bmp"


def png_size(data: bytes) -> tuple[int, int] | None:
    """``(width, height)`` from a PNG IHDR chunk, or None."""
    if len(data) >= 24 and data[:8] == PNG_SIGNATURE and data[12:16] == b"IHDR":
        w, h = struct.unpack(">II", data[16:24])
        return w, h
    return None


def _dib_header(dib: bytes) -> tuple[int, int, int, int, int, int]:
    if len(dib) < 40:
        raise SldFormatError("DIB too short")
    bs, w, h, planes, bpp, comp, _isz, _xp, _yp, clr_used, _ci = struct.unpack_from("<IiiHHIIiiII", dib, 0)
    if bs not in (40, 108, 124) or planes != 1 or bpp not in (1, 4, 8, 16, 24, 32) or w <= 0 or h == 0:
        raise SldFormatError(f"not a DIB (header size {bs}, planes {planes}, bpp {bpp}, {w} x {h})")
    if bpp <= 8:
        ncol = clr_used or (1 << bpp)
    else:
        ncol = clr_used + (3 if comp == 3 and bs == 40 else 0)
    return bs, w, h, bpp, comp, ncol


def dib_to_bmp(stream: bytes) -> tuple[bytes, int, int]:
    """``Preview`` stream (u32 length + packed DIB) to complete .bmp file bytes, width and height."""
    if len(stream) < 44:
        raise SldFormatError("Preview stream too short")
    if stream[:2] == b"BM":  # tolerate a stream that is already a .bmp file
        _bs, w, h, *_ = _dib_header(stream[14:])
        return stream, w, abs(h)
    (n,) = struct.unpack_from("<I", stream, 0)
    dib = stream[4 : 4 + n] if 0 < n <= len(stream) - 4 else stream[4:]
    bs, w, h, _bpp, _comp, ncol = _dib_header(dib)
    off = 14 + bs + 4 * ncol
    bmp = b"BM" + struct.pack("<IHHI", 14 + len(dib), 0, 0, off) + dib
    return bmp, w, abs(h)


_CONFIG_PREVIEW = re.compile(r"Config-(\d{1,9})-Preview(PNG)?")  # bounded: int() of a crafted name
_SHEET = re.compile(r"Images/Sheet_(\d{1,9})")


def preview_streams(container: Container) -> list[str]:
    """Names of every preview-image stream in a document, best first."""
    names = container.names()
    out = [want for want in ("PreviewPNG", "Preview") if want in names]
    cfg = [n for n in names if _CONFIG_PREVIEW.fullmatch(n)]
    cfg.sort(key=lambda s: (int(_CONFIG_PREVIEW.fullmatch(s).group(1)), not s.endswith("PNG")))
    out += cfg
    out += sorted((n for n in names if _SHEET.fullmatch(n)), key=lambda s: int(_SHEET.fullmatch(s).group(1)))
    return out


def decode_preview_stream(container: Container, name: str) -> Preview:
    """Decode one preview stream to a PNG or a complete BMP file."""
    data = container.read(name, max_bytes=MAX_PREVIEW_BYTES)
    if data[:8] == PNG_SIGNATURE:
        size = png_size(data)
        if not size:
            raise SldFormatError(f"{name}: PNG without IHDR")
        return Preview(data, "image/png", size[0], size[1], name)
    bmp, w, h = dib_to_bmp(data)
    return Preview(bmp, "image/bmp", w, h, name)


def read_preview(container: Container, *, prefer: str = "png") -> Preview | None:
    """The document's saved preview image, or None when it stores none.

    ``prefer="png"`` returns ``PreviewPNG`` first, then the ``Preview`` DIB, then
    per-configuration previews and drawing sheets. ``prefer="dib"`` returns the
    larger, 256-colour ``Preview`` DIB first, as a BMP file.
    """
    if prefer not in ("png", "dib"):
        raise ValueError("prefer must be 'png' or 'dib'")
    candidates = preview_streams(container)
    if prefer == "dib":
        candidates.sort(key=lambda n: 0 if n == "Preview" else 1)
    last_err: Exception | None = None
    for name in candidates:
        try:
            return decode_preview_stream(container, name)
        except (SldFormatError, struct.error) as exc:
            last_err = exc
    if last_err is not None:
        raise SldFormatError(f"no preview stream could be decoded: {last_err}") from last_err
    return None


def convert_image(data: bytes, fmt: str) -> bytes:
    """Re-encode image bytes as ``"PNG"`` or ``"BMP"``. Needs Pillow (``pip install solidseas[image]``)."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "converting between PNG and BMP needs Pillow: pip install solidseas[image]"
        ) from exc
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            out = io.BytesIO()
            im.save(out, fmt)
    except Exception as exc:  # Pillow raises many types, including DecompressionBombError
        raise SldFormatError(f"preview image could not be converted: {type(exc).__name__}: {exc}") from None
    return out.getvalue()
