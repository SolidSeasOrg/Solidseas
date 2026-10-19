"""Write the 2015+ SOLIDWORKS container.

``docs/FORMAT.md`` section 2 is the layout this writes, and
``docs/NATIVE_SLDPRT_WRITER.md`` section 3 says which parts of it SOLIDWORKS
has been seen to accept. Two ways to make a document:

- :func:`build_container` lays the members out again from byte 8, with no
  decoys, the source's key and signatures, and every member compressed the
  way SOLIDWORKS compresses (zlib level 1, raw deflate). A member whose
  decoded bytes did not change keeps its stored bytes.
- :func:`patch_in_place` keeps every byte of the source file and changes only
  what an edit needs: a member whose new stored form fits its old span is
  written over it, and one that does not is moved after the last member, with
  the central directory and end record written again behind it.

Both leave the source untouched. :func:`write_new_file` writes the result to a
path that must not exist yet, through a temporary name and a rename.
"""

import os
import struct
import zlib
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..formats.solidworks.container import MODERN_MAGIC, open_container
from ..formats.solidworks.modern import BASE, encode_name, lcg_signatures

_LFH = struct.Struct("<4sHHHHHIIIHH")
_CDH = struct.Struct("<4sHHHHHHIIIHHHHHII")
_EOCD = struct.Struct("<4sHHHHIIH")
VERSION_NEEDED = 20
FLAGS = 0x0006
METHOD = 8
EMPTY_DEFLATE = b"\x03\x00"
MAX_MEMBERS = 4096
MAX_MEMBER_BYTES = 1 << 30


class ContainerWriteError(ValueError):
    """The members or the edit cannot be written as a valid container."""


@dataclass
class Member:
    """One member: its name, decoded bytes and the directory fields kept from the source.

    ``stored`` is the member's raw deflate stream. It is reused only while it
    still belongs to ``data`` (``stored_for`` is the CRC and size it was read
    with); after an edit it is made again.
    """

    name: str
    data: bytes
    dos_time: int = 0
    dos_date: int = 0
    internal_attr: int = 0
    stored: bytes | None = None
    stored_for: tuple[int, int] | None = None

    @property
    def crc(self) -> int:
        return zlib.crc32(self.data) & 0xFFFFFFFF

    def stored_bytes(self) -> bytes:
        if self.stored is not None and self.stored_for == (self.crc, len(self.data)):
            return self.stored
        return deflate_member(self.data)


@dataclass
class SourceDocument:
    """A 2015+ document read for rewriting: its raw bytes, key, signatures and members."""

    raw: bytes
    key: bytes
    signatures: tuple[bytes, bytes, bytes]
    members: list[Member]
    offsets: dict[str, tuple[int, int, int]] = field(default_factory=dict)  # name: (lfh, data, stored size)
    cd_offset: int = 0
    cd_size: int = 0
    eocd_offset: int = 0

    def member(self, name: str) -> Member:
        for m in self.members:
            if m.name == name:
                return m
        raise KeyError(name)

    def data(self, name: str) -> bytes:
        return self.member(name).data


def deflate_member(data: bytes) -> bytes:
    """A member's stored form as SOLIDWORKS writes it: raw deflate, zlib level 1, memLevel 8."""
    if not data:
        return EMPTY_DEFLATE
    c = zlib.compressobj(1, zlib.DEFLATED, -15, 8, zlib.Z_DEFAULT_STRATEGY)
    return c.compress(data) + c.flush()


def read_document(source: str | os.PathLike | bytes) -> SourceDocument:
    """Read a 2015+ document's members and container fields, without changing the source."""
    raw = bytes(source) if isinstance(source, (bytes, bytearray, memoryview)) else Path(source).read_bytes()
    if raw[4:8] != MODERN_MAGIC:
        raise ContainerWriteError("not a 2015+ SOLIDWORKS container")
    with open_container(raw) as c:
        meta = dict(c.meta)
        infos = c.streams()
        if len(infos) > MAX_MEMBERS:
            raise ContainerWriteError(f"{len(infos)} members exceed the cap of {MAX_MEMBERS}")
        sigs = tuple(bytes.fromhex(meta[k]) for k in ("lfh_signature", "cd_signature", "eocd_signature"))
        cd_off, cd_size = int(meta["cd_offset"]), int(meta["cd_size"])
        attrs = _internal_attrs(raw, cd_off, len(infos))
        members, offsets = [], {}
        for info, attr in zip(infos, attrs, strict=True):
            data = c.read(info.name)
            stored = c.read_raw(info.name)
            members.append(
                Member(
                    name=info.name,
                    data=data,
                    dos_time=info.dos_time or 0,
                    dos_date=info.dos_date or 0,
                    internal_attr=attr,
                    stored=stored,
                    stored_for=(info.crc32, info.size),
                )
            )
            offsets[info.name] = (info.offset, info.data_offset, info.compressed_size)
    return SourceDocument(
        raw=raw,
        key=raw[:4],
        signatures=sigs,  # type: ignore[arg-type]
        members=members,
        offsets=offsets,
        cd_offset=cd_off,
        cd_size=cd_size,
        eocd_offset=int(meta["eocd_offset"]),
    )


def _internal_attrs(raw: bytes, cd_off: int, n: int) -> list[int]:
    out, pos = [], cd_off
    for _ in range(n):
        row = _CDH.unpack_from(raw, pos)
        out.append(row[14])
        pos += 46 + row[10] + row[11] + row[12]
    return out


def with_changes(members: list[Member], changes: dict[str, bytes | None]) -> list[Member]:
    """The members with ``changes`` applied: new data for a name, ``None`` to drop it.

    Names in ``changes`` that are not members are added at the end, in order.
    """
    names = {m.name for m in members}
    out = []
    for m in members:
        if m.name in changes:
            new = changes[m.name]
            if new is None:
                continue
            m = replace(m, data=bytes(new))
        out.append(m)
    for name, new in changes.items():
        if name not in names and new is not None:
            out.append(Member(name=name, data=bytes(new)))
    return out


def _check(members: list[Member]) -> None:
    if not members:
        raise ContainerWriteError("a container needs at least one member")
    if len(members) > MAX_MEMBERS:
        raise ContainerWriteError(f"{len(members)} members exceed the cap of {MAX_MEMBERS}")
    seen = set()
    for m in members:
        if not m.name or m.name in seen:
            raise ContainerWriteError(f"member name {m.name!r} is empty or repeated")
        seen.add(m.name)
        if len(m.data) > MAX_MEMBER_BYTES:
            raise ContainerWriteError(f"{m.name}: {len(m.data)} bytes exceed the cap")


def default_signatures(key: bytes) -> tuple[bytes, bytes, bytes]:
    preds = lcg_signatures(key)
    if not preds:
        raise ContainerWriteError(f"key {key.hex()} is not four consecutive rand() low bytes")
    return preds[0]


def build_container(
    members: list[Member],
    *,
    key: bytes,
    signatures: tuple[bytes, bytes, bytes] | None = None,
) -> bytes:
    """A complete 2015+ container holding ``members`` in order, with no decoys."""
    _check(members)
    lfh_sig, cd_sig, eocd_sig = signatures or default_signatures(key)
    out = bytearray(bytes(key) + MODERN_MAGIC)
    cd = bytearray()
    for m in members:
        stored = m.stored_bytes()
        name = encode_name(m.name)
        rel = len(out) - BASE
        head = (VERSION_NEEDED, FLAGS, METHOD, m.dos_time, m.dos_date, m.crc, len(stored), len(m.data))
        out += _LFH.pack(lfh_sig, *head, len(name), 0) + name + stored
        cd += _CDH.pack(cd_sig, 0, *head, len(name), 0, 0, 0, m.internal_attr, 0, rel) + name
    cd_rel = len(out) - BASE
    out += cd
    out += _EOCD.pack(eocd_sig, 0, 0, len(members), len(members), len(cd), cd_rel, 0)
    return bytes(out)


def patch_in_place(doc: SourceDocument, changes: dict[str, bytes]) -> bytes:
    """The source file with only the changed members rewritten.

    A member whose new stored bytes are no longer than its old span keeps its
    offset: the new header and data are written there and the rest of the old
    span keeps its bytes (a reader goes by the declared sizes). A member that
    grew is written after the last member's data, where the directory was, and
    the directory and end record follow it. Every other byte is the source's.
    Adding or dropping members is not done here; use :func:`build_container`.
    """
    for name in changes:
        if name not in doc.offsets:
            raise ContainerWriteError(f"{name}: not a member of the source")
    lfh_sig, cd_sig, eocd_sig = doc.signatures
    out = bytearray(doc.raw)
    order = [m.name for m in doc.members]
    entries: dict[str, tuple] = {}
    moved: list[tuple[str, bytes]] = []
    for m in doc.members:
        lfh_abs, _data_abs, old_size = doc.offsets[m.name]
        new = changes.get(m.name)
        mm = m if new is None else replace(m, data=bytes(new))
        stored = mm.stored_bytes()
        name = encode_name(mm.name)
        head = (VERSION_NEEDED, FLAGS, METHOD, mm.dos_time, mm.dos_date, mm.crc, len(stored), len(mm.data))
        entries[m.name] = (head, name, lfh_abs - BASE, mm)
        if new is None:
            continue
        if len(stored) <= old_size:
            rec = _LFH.pack(lfh_sig, *head, len(name), 0) + name + stored
            out[lfh_abs : lfh_abs + len(rec)] = rec
        else:
            moved.append((m.name, _LFH.pack(lfh_sig, *head, len(name), 0) + name + stored))
    # Everything from the old directory on is replaced: moved members, then the directory.
    tail_start = doc.cd_offset
    del out[tail_start:]
    for nm, rec in moved:
        head, name, _old_rel, mm = entries[nm]
        entries[nm] = (head, name, len(out) - BASE, mm)
        out += rec
    cd = bytearray()
    for nm in order:
        head, name, rel, mm = entries[nm]
        cd += _CDH.pack(cd_sig, 0, *head, len(name), 0, 0, 0, mm.internal_attr, 0, rel) + name
    cd_rel = len(out) - BASE
    out += cd
    out += _EOCD.pack(eocd_sig, 0, 0, len(order), len(order), len(cd), cd_rel, 0)
    return bytes(out)


def write_new_file(path: str | os.PathLike, data: bytes) -> Path:
    """Write ``data`` to ``path``, which must not exist, through a temporary name and a rename."""
    p = Path(path)
    if p.exists() or p.is_symlink():
        raise FileExistsError(f"{p} exists; the writer never replaces a file")
    tmp = p.with_name(p.name + ".partial")
    if tmp.exists() or tmp.is_symlink():
        raise FileExistsError(f"{tmp} exists")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if p.exists():
            raise FileExistsError(f"{p} appeared while writing")
        os.replace(tmp, p)
    finally:
        if tmp.exists():
            tmp.unlink()
    return p
