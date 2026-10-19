"""The 2015+ SOLIDWORKS container (file bytes 4 to 7 are ``00 00 00 04``).

The file is an 8-byte header followed by a PKZIP archive with four deviations
from APPNOTE ZIP (``docs/FORMAT.md`` has the full spec and evidence):

1. every stored offset is relative to file offset 8;
2. the ``PK`` record signatures are replaced by per-file 4-byte values derived
   from the 4-byte key in the header (MSVC ``rand()`` model, see
   :func:`lcg_signatures`);
3. every byte of a member name is nibble-swapped;
4. decoy records and random filler are interleaved with the real records, so
   a forward walk over declared sizes does not work.

Reading strategy, with no marker scanning: find the end-of-central-directory
record (EOCD) by a bounded backward search for its self-location invariant
``8 + cd_offset + cd_size == own offset``, parse ``entries`` central-directory
records sequentially, cross-check every local header against its directory
copy, then inflate each member as a capped stream with size and CRC checks.
"""

import re
import struct
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO

from ._io import pread
from .container import MODERN_MAGIC, Container, StreamInfo
from .errors import ReaderWarning, SldFormatError, SldIntegrityError, SldLimitError, UnknownFormatError
from .zlb import MAX_STREAM_BYTES

BASE = 8  # stored ZIP offsets are relative to this file offset
MAX_CD_BYTES = 64 << 20  # cap on the central directory
MAX_EOCD_CANDIDATES = 1_000  # cap on arithmetic EOCD candidates examined (real files need 1)
_IN_CHUNK = 1 << 20  # compressed bytes read per step
_OUT_CHUNK = 4 << 20  # decompressed bytes produced per step at most
# Tail windows searched for the EOCD, smallest first. Every corpus file has its EOCD
# within 820 bytes of the end, so the first window normally finds it, and a small
# central directory is served from it too (see _tail_read): a lazy open reads a few KiB.
_TAIL_WINDOWS = (1 << 11, 1 << 16, 1 << 20, 1 << 24)
_SCAN_CHUNK = 16 << 20

_LFH = struct.Struct("<4sHHHHHIIIHH")  # 30-byte local file header
_CDH = struct.Struct("<4sHHHHHHIIIHHHHHII")  # 46-byte central-directory header
_EOCD = struct.Struct("<4sHHHHIIH")  # 22-byte end of central directory
# EOCD candidates: 4 zero bytes (the disk fields), then two equal non-zero u16 entry counts
_EOCD_RE = re.compile(rb"(?=\x00\x00\x00\x00((?!\x00\x00)..)\1)", re.S)

# --------------------------------------------------------------------------- names
_NIBBLE_SWAP = bytes(((b << 4) | (b >> 4)) & 0xFF for b in range(256))


def _decode_name(stored: bytes) -> tuple[str, bool]:
    """``(name, used_cp437_fallback)`` for a stored member name."""
    b = bytes(stored).translate(_NIBBLE_SWAP)
    try:
        return b.decode("utf-8"), False
    except UnicodeDecodeError:
        return b.decode("cp437"), True


def decode_name(stored: bytes) -> str:
    """Decode a stored member name.

    Every stored byte is nibble-swapped (``((b << 4) | (b >> 4)) & 0xFF``, its
    own inverse). The swapped bytes are UTF-8 in every observed file although
    ZIP flag bit 11 is clear; anything that is not UTF-8 falls back to IBM437.
    """
    return _decode_name(stored)[0]


def encode_name(name: str) -> bytes:
    """Stored (nibble-swapped UTF-8) form of a member name."""
    return name.encode("utf-8").translate(_NIBBLE_SWAP)


# --------------------------------------------------------------------------- signatures
_LCG_MUL, _LCG_ADD, _M24 = 214013, 2531011, (1 << 24) - 1


def lcg_signatures(key: bytes) -> list[tuple[bytes, bytes, bytes]]:
    """Predict the (local, central, end) record signatures from the 4-byte file key.

    Model: the key bytes are the low bytes of four consecutive MSVC-CRT
    ``rand()`` outputs (``state = state * 214013 + 2531011 mod 2**32``,
    ``output = (state >> 16) & 0x7FFF``). The low bytes r0..r11 of the next
    twelve outputs give LFH = r3 r2 r1 r0, CD = r7 r6 r5 r4 and
    EOCD = r11 r10 r9 r8 in file byte order. Only state bits 0 to 23 affect a
    low byte, so every 24-bit state consistent with the key is enumerated
    (normally exactly one). Diagnostic only: the reader never needs it.
    """
    key = bytes(key)
    if len(key) != 4:
        raise ValueError("key must be 4 bytes")
    k0, k1, k2, k3 = key
    out = []
    hi = k0 << 16
    for lo in range(1 << 16):
        s = ((hi | lo) * _LCG_MUL + _LCG_ADD) & _M24
        if (s >> 16) != k1:
            continue
        s = (s * _LCG_MUL + _LCG_ADD) & _M24
        if (s >> 16) != k2:
            continue
        s = (s * _LCG_MUL + _LCG_ADD) & _M24
        if (s >> 16) != k3:
            continue
        seq = bytearray()
        for _ in range(12):
            s = (s * _LCG_MUL + _LCG_ADD) & _M24
            seq.append(s >> 16)
        out.append((bytes(seq[3::-1]), bytes(seq[7:3:-1]), bytes(seq[11:7:-1])))
    return out


# --------------------------------------------------------------------------- reader
@dataclass
class _Member:
    info: StreamInfo
    method: int
    flags: int


class ModernContainer(Container):
    """A 2015+ container. Create it with :func:`~.container.open_container`."""

    format = "modern"

    def __init__(self, fh: BinaryIO, size: int, path: str | None, strict: bool, depth: int):
        super().__init__()
        self._fh, self.file_size, self.path, self._depth = fh, size, path, depth
        self._members: list[_Member] = []
        self._crc_constant = False
        self._tail: tuple[int, bytes] = (size, b"")  # the last tail window read: (offset, bytes)
        self._parse(strict)
        self._tail = (size, b"")

    # structure ----------------------------------------------------------------
    def _parse(self, strict: bool) -> None:
        f, size = self._fh, self.file_size
        if size < BASE + 22:
            raise SldFormatError(f"file too small for a modern container ({size} bytes)")
        head = pread(f, 0, BASE)
        if head[4:8] != MODERN_MAGIC:
            raise UnknownFormatError(f"bytes 4..7 are {head[4:8].hex()}, not 00000004")
        self.meta.update(key=head[:4].hex(), header=head.hex())
        last_err: Exception | None = None
        examined = 0
        # Directory bytes read across every candidate. A crafted file can plant many
        # self-consistent candidates whose directories each cover most of the file.
        self._cd_read_budget = 2 * size + (1 << 20)
        for p in self._eocd_candidates():
            examined += 1
            if examined > MAX_EOCD_CANDIDATES:
                break
            try:
                self._parse_from_eocd(p, strict)
                self.meta["eocd_candidates_examined"] = examined
                return
            except SldFormatError as exc:  # includes SldLimitError: try the next candidate
                last_err = exc
        if isinstance(last_err, SldLimitError):
            raise SldLimitError(f"no usable end-of-central-directory record (last candidate: {last_err})")
        if last_err is not None:
            raise SldFormatError(f"no valid end-of-central-directory record (last candidate: {last_err})")
        raise SldFormatError("no self-consistent end-of-central-directory record found")

    def _eocd_candidates(self) -> Iterator[int]:
        """Absolute offsets satisfying the EOCD self-location invariant, nearest to
        EOF first. Scans growing tail windows, then the rest of the file in chunks."""
        f, size = self._fh, self.file_size
        done_lo = size  # candidates at or above done_lo were already yielded
        for win in (*_TAIL_WINDOWS, None):
            if win is None:
                end = done_lo
                while end > BASE:
                    start = max(BASE, end - _SCAN_CHUNK)
                    buf = pread(f, start, min(size, end + 21) - start)
                    yield from self._candidates_in(buf, start, end)
                    end = start
                return
            start = max(BASE, size - win)
            if start >= done_lo:
                continue
            buf = pread(f, start, size - start)
            self._tail = (start, buf)
            yield from self._candidates_in(buf, start, done_lo)
            done_lo = start
            if start == BASE:
                return

    def _candidates_in(self, buf: bytes, buf_start: int, below: int) -> Iterator[int]:
        size = self.file_size
        found = []
        for m in _EOCD_RE.finditer(buf):
            q = m.start() - 4
            p = buf_start + q
            if q < 0 or p < BASE or p >= below or q + 22 > len(buf):
                continue
            n_this, n_total, cd_size, cd_off, clen = struct.unpack_from("<HHIIH", buf, q + 8)
            if n_this != n_total or BASE + cd_off + cd_size != p:
                continue
            if cd_size < 46 * n_total or p + 22 + clen > size:
                continue
            found.append(p)
        return reversed(found)

    def _tail_read(self, offset: int, n: int) -> bytes:
        """``n`` bytes at ``offset``, from the tail window already read when it covers them."""
        start, buf = self._tail
        if start <= offset and offset + n <= start + len(buf):
            return buf[offset - start : offset - start + n]
        return pread(self._fh, offset, n)

    def _parse_from_eocd(self, p: int, strict: bool) -> None:
        f, size = self._fh, self.file_size
        (eocd_sig, _disk, _cd_disk, n_this, n_total, cd_size, cd_off, clen) = _EOCD.unpack(
            self._tail_read(p, 22)
        )
        if cd_size > MAX_CD_BYTES:
            raise SldLimitError(f"central directory of {cd_size} bytes exceeds cap {MAX_CD_BYTES}")
        if 0xFFFF in (n_this, n_total) or 0xFFFFFFFF in (cd_size, cd_off):
            raise SldFormatError("ZIP64 end records are not supported (never observed)")
        cd_start = BASE + cd_off
        # Check the first record from a small read before reading the whole directory.
        first = _CDH.unpack(self._tail_read(cd_start, 46))
        f_vneed, f_nlen, f_xlen, f_cmlen, f_lho = first[2], first[10], first[11], first[12], first[16]
        if f_nlen == 0 or f_vneed > 63 or 46 + f_nlen + f_xlen + f_cmlen > cd_size:
            raise SldFormatError("first central directory record is implausible")
        if BASE + f_lho + 30 + f_nlen > cd_start:
            raise SldFormatError("first central directory record points outside the data area")
        if cd_size > self._cd_read_budget:
            raise SldLimitError("candidate end records together claim more directory than the file holds")
        self._cd_read_budget -= cd_size
        cd = self._tail_read(cd_start, cd_size)
        warnings: list[ReaderWarning] = []
        # 1. central directory: n_total records, sequential, length-delimited
        rows = []
        pos = 0
        cd_sig = None
        for i in range(n_total):
            if pos + 46 > cd_size:
                raise SldFormatError(f"central directory entry {i} overruns the directory")
            row = _CDH.unpack_from(cd, pos)
            sig, vneed, nlen, xlen, cmlen, disk_start = row[0], row[2], row[10], row[11], row[12], row[13]
            csize, usize, lho = row[8], row[9], row[16]
            if cd_sig is None:
                cd_sig = sig
            elif sig != cd_sig:
                raise SldFormatError(
                    f"central directory entry {i}: signature {sig.hex()} differs from {cd_sig.hex()}"
                )
            end = pos + 46 + nlen + xlen + cmlen
            if end > cd_size:
                raise SldFormatError(f"central directory entry {i}: name, extra or comment overrun")
            if nlen == 0:
                raise SldFormatError(f"central directory entry {i}: empty name")
            if 0xFFFFFFFF in (csize, usize, lho):
                raise SldFormatError(f"entry {i} uses ZIP64 fields (not supported, never observed)")
            if disk_start != 0:
                raise SldFormatError(f"entry {i}: multi-disk archives are not supported")
            if vneed > 63:
                raise SldFormatError(f"entry {i}: implausible version-needed {vneed}")
            if BASE + lho + 30 + nlen > cd_start:
                raise SldFormatError(f"entry {i}: local header offset {BASE + lho} outside the data area")
            rows.append((row, cd[pos + 46 : pos + 46 + nlen]))
            pos = end
        # 2. local headers: one signature per file, every field equal to its directory copy
        members: list[_Member] = []
        lfh_sig = None
        spans = []
        for i, (row, raw_name) in enumerate(rows):
            vneed, flags, method, mtime, mdate, crc, csize, usize = row[2:10]
            lho = row[16]
            name, fallback = _decode_name(raw_name)
            if fallback:
                warnings.append(
                    ReaderWarning(
                        "container_name_not_utf8", f"entry {i}: name is not UTF-8, decoded as cp437"
                    )
                )
            lfh_abs = BASE + lho
            # One read for the header and the name it should carry (the directory's copy);
            # the name is read again only when the lengths disagree.
            head = pread(f, lfh_abs, 30 + len(raw_name))
            lfh = _LFH.unpack_from(head, 0)
            sig, l_head, l_crc, l_csize, l_usize, l_nlen, l_xlen = (
                lfh[0],
                lfh[1:6],
                lfh[6],
                lfh[7],
                lfh[8],
                lfh[9],
                lfh[10],
            )
            if lfh_sig is None:
                lfh_sig = sig
            elif sig != lfh_sig:
                raise SldFormatError(
                    f"{name}: local header signature {sig.hex()} differs from {lfh_sig.hex()}"
                )
            if l_nlen == len(raw_name):
                l_name = head[30:]
            else:
                l_name = pread(f, lfh_abs + 30, l_nlen) if l_nlen else b""
            mismatch = []
            if l_head != (vneed, flags, method, mtime, mdate):
                mismatch.append("header fields")
            if l_name != raw_name:
                mismatch.append("name")
            if not (flags & 0x8) and (l_crc, l_csize, l_usize) != (crc, csize, usize):
                mismatch.append("crc/sizes")
            if mismatch:
                msg = f"local header differs from central directory ({', '.join(mismatch)})"
                if strict:
                    raise SldFormatError(f"{name}: {msg}")
                warnings.append(ReaderWarning("container_header_mismatch", msg, name))
            data_off = lfh_abs + 30 + l_nlen + l_xlen
            if data_off + csize > cd_start:
                raise SldFormatError(
                    f"{name}: data [{data_off}, {data_off + csize}) runs into the central directory "
                    f"at {cd_start}"
                )
            spans.append((lfh_abs, data_off + csize, name))
            codec = {8: "deflate", 0: "stored"}.get(method, f"method-{method}")
            info = StreamInfo(
                name=name,
                size=usize,
                compressed_size=csize,
                offset=lfh_abs,
                data_offset=data_off,
                codec=codec,
                crc32=crc,
                index=i,
                dos_time=mtime,
                dos_date=mdate,
            )
            members.append(_Member(info, method=method, flags=flags))
        spans.sort()
        for (a0, a1, an), (b0, _b1, bn) in zip(spans, spans[1:], strict=False):
            if a1 > b0:
                raise SldFormatError(f"members overlap: {an} [{a0}, {a1}) and {bn} at {b0}")
        crcs = {m.info.crc32 for m in members}
        crc_constant = len(members) >= 3 and len(crcs) == 1 and any(m.info.size for m in members)
        if crc_constant:
            warnings.append(
                ReaderWarning(
                    "container_crc_constant",
                    f"every member declares the same CRC-32 {next(iter(crcs)):08x}; CRC checks are skipped "
                    "(sizes are still verified)",
                )
            )
        # commit
        self._crc_constant = crc_constant
        self._members = members
        self._infos = [m.info for m in members]
        self._by_name = {}
        for i, s in enumerate(self._infos):
            self._by_name.setdefault(s.name, i)
        self.warnings.extend(warnings)
        self.meta.update(
            eocd_offset=p,
            eocd_signature=eocd_sig.hex(),
            cd_offset=cd_start,
            cd_size=cd_size,
            cd_signature=cd_sig.hex() if cd_sig else None,
            lfh_signature=lfh_sig.hex() if lfh_sig else None,
            entries=n_total,
            cd_slack=cd_size - pos,
            tail_bytes=size - (p + 22 + clen),
            first_local_header=min((m.info.offset for m in members), default=None),
            crc_constant=crc_constant,
        )

    def signatures_match_lcg(self) -> bool | None:
        """Whether the observed record signatures equal the ``rand()`` model's prediction."""
        sigs = (
            self.meta.get("lfh_signature"),
            self.meta.get("cd_signature"),
            self.meta.get("eocd_signature"),
        )
        if None in sigs:
            return None
        preds = [tuple(x.hex() for x in t) for t in lcg_signatures(bytes.fromhex(str(self.meta["key"])))]
        return sigs in preds

    # data -----------------------------------------------------------------------
    def _member(self, name: str) -> _Member:
        self._check_open()
        return self._members[self.info(name).index]

    def iter_read(
        self, name: str, *, max_bytes: int = MAX_STREAM_BYTES, verify: str = "auto"
    ) -> Iterator[bytes]:
        if verify not in ("auto", "strict", "size", "none"):
            raise ValueError("verify must be 'auto', 'strict', 'size' or 'none'")
        return self._iter_member(self._member(name), max_bytes, verify)

    def _iter_member(self, m: _Member, max_bytes: int, verify: str) -> Iterator[bytes]:
        info = m.info
        if m.flags & 0x1:
            raise SldFormatError(f"{info.name}: encrypted members are not supported")
        if m.method not in (0, 8):
            raise SldFormatError(f"{info.name}: unsupported compression method {m.method}")
        check_size = verify != "none"
        check_crc = verify == "strict" or (verify == "auto" and not self._crc_constant)
        if check_size and info.size > max_bytes:
            raise SldLimitError(f"{info.name}: declared size {info.size} exceeds cap {max_bytes}")
        limit = min(max_bytes, info.size) if check_size else max_bytes
        size_bound = check_size and limit == info.size
        f = self._fh
        pos = info.data_offset
        remaining = info.compressed_size
        produced = 0
        crc = 0
        d = zlib.decompressobj(-15) if m.method == 8 else None
        pending = b""
        while True:
            if not pending and remaining:
                pending = pread(f, pos, min(_IN_CHUNK, remaining))
                pos += len(pending)
                remaining -= len(pending)
            if d is None:
                out, pending = pending, b""
            else:
                try:
                    out = d.decompress(pending, _OUT_CHUNK)
                except zlib.error as exc:
                    raise SldFormatError(f"{info.name}: corrupt deflate data ({exc})") from exc
                pending = d.unconsumed_tail
            if out:
                produced += len(out)
                if produced > limit:
                    if size_bound:
                        raise SldIntegrityError(
                            f"{info.name}: decoded data exceeds the declared size ({limit} bytes)"
                        )
                    raise SldLimitError(f"{info.name}: decoded data exceeds the cap ({limit} bytes)")
                if check_crc:
                    crc = zlib.crc32(out, crc)
                yield out
            if d is None:
                if not remaining:
                    break
            elif d.eof:
                if check_size and (d.unused_data or pending or remaining):
                    extra = len(d.unused_data) + len(pending) + remaining
                    raise SldFormatError(f"{info.name}: {extra} bytes follow the end of the deflate stream")
                break
            elif not out and not pending and not remaining:
                raise SldFormatError(f"{info.name}: deflate stream ends before its end-of-block")
        if check_size and produced != info.size:
            raise SldIntegrityError(f"{info.name}: decoded {produced} bytes, declared {info.size}")
        if check_crc and crc != info.crc32:
            raise SldIntegrityError(f"{info.name}: CRC-32 {crc:08x} != declared {info.crc32:08x}")

    def read_raw(self, name: str, *, max_bytes: int = MAX_STREAM_BYTES) -> bytes:
        m = self._member(name)
        if m.info.compressed_size > max_bytes:
            raise SldLimitError(f"{name}: stored size {m.info.compressed_size} exceeds cap {max_bytes}")
        return pread(self._fh, m.info.data_offset, m.info.compressed_size)
