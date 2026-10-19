"""The component meshes an assembly stores, in its components' own coordinates.

SOLIDWORKS 2023 and 2024 assemblies (113 of the 325 on the development corpus)
keep a display mesh of each component in streams named
``FaceTessellations/<nnn-nnn-nnn>`` and a ``FaceTessellations/Directory`` that
maps instances to them. ``docs/FORMAT.md`` section 12.3 has the layout and the
evidence; in short:

* **Directory**: u32 2, u32 the highest stream number, u32 the record count n,
  then n records. A record is u32 its number, a CString with the instance's
  path from the top (``sub-1@top/part-1@sub``: each instance name followed by
  ``@`` and the name of the document it sits in), u16 (meaning UNKNOWN), 10
  zero bytes, 8 bytes *shares* (zero, or the id of the record whose mesh this
  instance uses), 8 bytes its own id, a CString naming the stream that holds
  its own block (empty when it has none), i32 that block's number (-1 when
  none), u32 k and k triples of u32 (meaning UNKNOWN). All 113 directories
  parse to their last byte.
* **Blocks**: a stream holds the blocks of several records, back to back from
  offset 0 in block order. A block starts with u32 its number, the record's
  8-byte id and u32 a face count, then the face tables of ``Contents/DisplayLists``
  (:mod:`.mesh`). Every one of the 981 own blocks on the corpus is found this
  way.

Older assemblies keep the same meshes in their own ``Contents/DisplayLists``
instead, a section per component file that opens with a header holding the
file's stored path (:func:`path_sections`).

Everything here is a HYPOTHESIS read from the fixtures and checked on the
corpus (``docs/FORMAT.md`` 12.3); the meshes themselves use the verified table
grammar. Nothing here touches the disk: it reads streams of an open container,
each capped in size.
"""

import struct
from collections.abc import Mapping
from dataclasses import dataclass, field

from .container import Container
from .mesh import Mesh, mesh_from_bytes
from .metadata import read_cstring

PREFIX = "FaceTessellations/"
DIRECTORY = PREFIX + "Directory"
MAX_DIRECTORY_BYTES = 64 << 20
MAX_RECORDS = 1_000_000
MAX_TRIPLES = 100_000  # per record; the corpus has at most 216
SEARCH_FACTOR = 4  # block_ranges searches at most this many times a stream's size...
SEARCH_SLACK = 1 << 16  # ...plus this many bytes
_NO_ID = bytes(8)


@dataclass(frozen=True)
class TessRecord:
    """One instance in ``FaceTessellations/Directory``.

    ``path`` is the stored ``name`` split at ``/`` with each ``@<document>``
    removed: the instance names from the top assembly down. ``stream`` and
    ``block`` locate the record's own mesh, or are None; ``shares`` is the id of
    the record whose mesh it uses instead, or None. A record with neither has no
    mesh (a suppressed instance, a sub-assembly or a pattern feature)."""

    number: int
    name: str
    path: tuple[str, ...]
    tag: int
    shares: bytes | None
    id: bytes
    stream: str | None
    block: int | None
    triples: tuple[tuple[int, int, int], ...]


@dataclass(frozen=True)
class TessDirectory:
    """The parsed ``FaceTessellations/Directory``: u32 2 (on every corpus file), the
    highest stream number (it equals the largest ``<nnn-nnn-nnn>`` named on all 116:
    113 corpus assemblies and the 3 fixture assemblies) and the records."""

    version: int
    last_stream: int
    records: tuple[TessRecord, ...]
    by_id: dict[bytes, TessRecord] = field(default_factory=dict, compare=False, repr=False)

    def mesh_record(self, rec: TessRecord) -> TessRecord | None:
        """The record whose block holds ``rec``'s mesh: itself, the one it shares, or
        None."""
        if rec.stream is not None and rec.block is not None:
            return rec
        if rec.shares is None:
            return None
        target = self.by_id.get(rec.shares)
        if target is None or target.stream is None or target.block is None:
            return None
        return target


def instance_path(name: str) -> tuple[str, ...]:
    """``sub-1@top/part-1@sub`` as ``("sub-1", "part-1")``."""
    return tuple(seg.rpartition("@")[0] if "@" in seg else seg for seg in name.split("/"))


def parse_directory(d: bytes) -> TessDirectory | None:
    """The directory, or None when the bytes do not parse to their end as one."""
    if len(d) < 12:
        return None
    version, last_stream, n = struct.unpack_from("<III", d, 0)
    if n > MAX_RECORDS or n * 34 > len(d):  # a record takes at least 34 bytes
        return None
    p = 12
    records = []
    for _ in range(n):
        if p + 4 > len(d):
            return None
        (number,) = struct.unpack_from("<I", d, p)
        name, q = read_cstring(d, p + 4)
        if name is None or q + 28 > len(d):
            return None
        (tag,) = struct.unpack_from("<H", d, q)
        shares, own = d[q + 12 : q + 20], d[q + 20 : q + 28]
        stream, q = read_cstring(d, q + 28)
        if stream is None or q + 8 > len(d):
            return None
        block, k = struct.unpack_from("<iI", d, q)
        q += 8
        if k > MAX_TRIPLES or q + 12 * k > len(d):
            return None
        flat = struct.unpack_from(f"<{3 * k}I", d, q)
        q += 12 * k
        records.append(
            TessRecord(
                number=number,
                name=name,
                path=instance_path(name),
                tag=tag,
                shares=None if shares == _NO_ID else bytes(shares),
                id=bytes(own),
                stream=PREFIX + stream if stream and block >= 0 else None,
                block=block if stream and block >= 0 else None,
                triples=tuple(zip(flat[0::3], flat[1::3], flat[2::3], strict=True)),
            )
        )
        p = q
    if p != len(d):
        return None
    by_id: dict[bytes, TessRecord] = {}
    for r in records:
        by_id.setdefault(r.id, r)
    return TessDirectory(version, last_stream, tuple(records), by_id)


def read_directory(container: Container) -> TessDirectory | None:
    """The assembly's ``FaceTessellations/Directory``, or None when it has none or it
    does not parse."""
    if DIRECTORY not in container:
        return None
    return parse_directory(container.read(DIRECTORY, max_bytes=MAX_DIRECTORY_BYTES))


def block_ranges(data: bytes, records: list[TessRecord]) -> dict[int, tuple[int, int, int]]:
    """``{block: (start, end, faces)}`` for the blocks of ``records`` (all of one
    stream) found in ``data``. Blocks lie back to back in block order, so each is
    looked for after the one before it, and a block ends where the next one found
    starts: when every block is there, the stream is scanned once.

    A block that is not there sends its search to the end of the stream, and the
    next search starts again where it did. So the searches together stop after
    :data:`SEARCH_FACTOR` times the stream's size (each search counting at least a
    header's 16 bytes): a directory naming many blocks a large stream lacks then
    costs time in proportion to the stream, not to the stream times the blocks, and
    the blocks past that point are not found. Every block on the development
    corpus is found within the first pass."""
    wanted = sorted({r.block: r.id for r in records if r.block is not None}.items())
    starts = []
    pos = 0
    budget = SEARCH_FACTOR * len(data) + SEARCH_SLACK
    for block, rid in wanted:
        if budget <= 0:
            break
        stop = min(len(data), pos + budget)
        hit = data.find(struct.pack("<I", block) + rid, pos, stop)
        budget -= max((hit + 16 if hit >= 0 else stop) - pos, 16)
        if hit < 0 or hit + 16 > len(data):
            continue
        (faces,) = struct.unpack_from("<I", data, hit + 12)
        starts.append((hit, block, faces))
        pos = hit + 16
    out = {}
    for i, (start, block, faces) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(data)
        out[block] = (start, end, faces)
    return out


def block_mesh(data: bytes, start: int, end: int, stream: str) -> Mesh:
    """The mesh of one block: every face table between ``start`` and ``end``."""
    return mesh_from_bytes(data[start:end], stream)


_CSTRING_MARK = b"\xff\xfe\xff"
MAX_PATH_CHARS = 32_767  # the longest Windows path


def base_name(path: str) -> str:
    """The file name a stored path ends with, case-folded: what follows its last ``\\``
    or ``/``."""
    folded = path.casefold()
    return folded[max(folded.rfind("\\"), folded.rfind("/")) + 1 :]


def path_sections(
    data: bytes,
    paths: Mapping[str, str | None],
    names: Mapping[str, frozenset[str]] | None = None,
) -> dict[str, list[tuple[int, int]]]:
    """The component sections of an older assembly's ``Contents/DisplayLists``.

    Assemblies saved before SOLIDWORKS stored ``FaceTessellations`` keep their
    components' face tables in their own display-list stream instead, a section
    per component file, each opening with a header that holds the file's stored
    path as a CString, and the tables after it in the component's own
    coordinates (``docs/FORMAT.md`` 12.3, a HYPOTHESIS from the corpus alone).
    ``paths`` maps each stored path, case-folded, to a file key, or to None for a
    file whose sections are not wanted; a section starts at a CString equal to one
    of them and runs to the next one of another file. So every path the component
    tree stores should be given, the unwanted ones as None: a path left out does
    not end the section before it, which then runs on through that file's tables.
    Returns ``{file key: [(start, end), ...]}``, without the None ones: one span
    per run of that file's path, so a file found in several places has several
    spans. On the corpus at most one of a file's spans holds face tables; the
    others are its path written again with nothing after it, and
    :mod:`solidseas.geometry` takes the one with tables.

    Some streams also hold a header with another path of a file the tree names:
    the same file name in another folder, where the file was when that section
    was written, with that file's tables after it. ``names`` maps file names
    (:func:`base_name`) to the keys of the files that bear them (none for a file
    whose sections are not wanted): a path not in ``paths`` that holds a folder
    and ends in one of them ends the section before it, unless the name is the
    section's own file's, and the tables after it go to no file."""
    hits: list[tuple[int, str | None, frozenset[str] | None]] = []
    p = data.find(_CSTRING_MARK)
    while p >= 0:
        text, q = read_cstring(data, p, MAX_PATH_CHARS)
        if text is not None:
            folded = text.casefold()
            if folded in paths:
                hits.append((p, paths[folded], None))
            elif names and ("\\" in folded or "/" in folded):
                same = names.get(base_name(folded))
                if same is not None:
                    hits.append((p, None, same))
        p = data.find(_CSTRING_MARK, max(q, p + 1))
    starts: list[tuple[int, str | None]] = []
    for pos, key, same in hits:
        if same is not None and starts and starts[-1][1] in same:
            continue  # the section's own file, under another folder: the section goes on
        if not starts or starts[-1][1] != key:
            starts.append((pos, key))
    out: dict[str, list[tuple[int, int]]] = {}
    for i, (pos, key) in enumerate(starts):
        if key is None:
            continue
        end = starts[i + 1][0] if i + 1 < len(starts) else len(data)
        out.setdefault(key, []).append((pos, end))
    return out
