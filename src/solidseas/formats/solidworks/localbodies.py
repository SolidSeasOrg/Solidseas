"""``Config-<n>-FeatureBodies/LocalBodies``: per-feature Parasolid part transmits.

When a configuration's partition holds no bodies (mostly imported STEP, IGES
or STL geometry), the bodies are stored here as ready-made Parasolid part
transmits. Layout, inferred from the development corpus (integers
little-endian; the meaning of the zero fields is unknown)::

    u32 n_entries
    n_entries times:
        name       MFC CString: FF FE FF, u8 length (FF: u16 follows), UTF-16LE
        variant A  u32 0, u32 n_bodies, n_bodies x BODYREC
        variant B  exactly one BODYREC directly after the name
        variant C  (one stream in the corpus) a few bytes, then u32 L and a ZLB block of L bytes
    BODYREC = u32 flag (0 or 1, meaning unknown), u8 0, u32 L + 5, u8 0, u32 L,
              ZLB block of exactly L bytes

Each ZLB block decodes to a neutral-binary Parasolid part transmit (root BODY).
"""

import struct
from collections.abc import Iterator

from .errors import SldError, SldFormatError, SldLimitError
from .zlb import MAX_STREAM_BYTES, ZLB_MAGIC, unwrap_zlb, zlb_size


class LocalBodiesError(SldFormatError):
    """The LocalBodies framing did not match any known variant."""


def _cstring(d: bytes, i: int) -> tuple[str, int]:
    if d[i : i + 3] != b"\xff\xfe\xff":
        raise LocalBodiesError(f"no CString marker at {i}")
    if i + 4 > len(d):
        raise LocalBodiesError("truncated CString")
    n = d[i + 3]
    j = i + 4
    if n == 0xFF:
        if j + 2 > len(d):
            raise LocalBodiesError("truncated CString length")
        n = struct.unpack_from("<H", d, j)[0]
        j += 2
    if j + 2 * n > len(d):
        raise LocalBodiesError("CString overruns the stream")
    return d[j : j + 2 * n].decode("utf-16-le", "replace"), j + 2 * n


def _is_bodyrec(d: bytes, i: int) -> bool:
    if i + 30 > len(d):
        return False
    _b, _c, l5, _z, length = struct.unpack_from("<IBIBI", d, i)
    return l5 == length + 5 and d[i + 14 : i + 30] == ZLB_MAGIC


def _bare_block(d: bytes, i: int, window: int = 32) -> int | None:
    """Offset p in [i, i + window) where ``u32 L`` is followed by a ZLB block of exactly L bytes."""
    for p in range(i, min(i + window, len(d) - 20)):
        if d[p + 4 : p + 20] == ZLB_MAGIC:
            (length,) = struct.unpack_from("<I", d, p)
            try:
                _, end = zlb_size(d, p + 4)
            except SldError:
                return None
            return p if end - (p + 4) == length else None
    return None


def iter_local_body_blocks(d: bytes) -> Iterator[tuple[str, int, int, bytes]]:
    """Yield ``(feature_name, body_ordinal, decoded_size, zlb_block)`` without inflating any body.

    A caller checks ``decoded_size`` against its own budget before calling
    :func:`~solidseas.formats.solidworks.zlb.unwrap_zlb` on the block.
    """
    if len(d) < 4:
        raise LocalBodiesError("stream too short")
    (count,) = struct.unpack_from("<I", d, 0)
    i = 4
    for _ in range(count):
        name, i = _cstring(d, i)
        if _is_bodyrec(d, i):
            n_bodies = 1  # variant B
        elif not _is_bodyrec(d, i + 8) and (j := _bare_block(d, i)) is not None:
            size, end = zlb_size(d, j + 4)  # variant C: small gap, then u32 L + ZLB block
            yield name, 0, size, d[j + 4 : end]
            i = end
            continue
        else:
            if i + 8 > len(d):
                raise LocalBodiesError("truncated entry header")
            _a, n_bodies = struct.unpack_from("<II", d, i)  # variant A
            i += 8
        for k in range(n_bodies):
            if i + 14 > len(d):
                raise LocalBodiesError("truncated body header")
            _b, _c, l5, _z, length = struct.unpack_from("<IBIBI", d, i)
            if l5 != length + 5 or d[i + 14 : i + 30] != ZLB_MAGIC:
                raise LocalBodiesError(f"unexpected body header at {i}")
            start = i + 14
            size, end = zlb_size(d, start)
            if end - start != length:
                raise LocalBodiesError(f"ZLB length mismatch at {start}")
            yield name, k, size, d[start:end]
            i = end
    if i != len(d):
        raise LocalBodiesError(f"{len(d) - i} unparsed trailing bytes")


def iter_local_bodies(d: bytes, *, max_bytes: int = MAX_STREAM_BYTES) -> Iterator[tuple[str, int, bytes]]:
    """Yield ``(feature_name, body_ordinal, transmit_bytes)`` from a decoded LocalBodies stream.

    ``max_bytes`` caps each body and the total across the stream; the declared
    sizes are checked before anything is inflated.
    """
    budget = max_bytes
    for name, k, size, block in iter_local_body_blocks(d):
        if size > budget:
            raise SldLimitError(
                f"LocalBodies body {name!r}#{k} of {size} bytes exceeds the remaining cap {budget}"
            )
        budget -= size
        yield name, k, unwrap_zlb(block, max_bytes=size)
