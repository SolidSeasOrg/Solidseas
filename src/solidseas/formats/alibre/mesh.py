"""``MESH_DATA``: the display tessellation an Alibre Design part stores (provisional,
``docs/formats/alibre.md``).

Little-endian throughout. Three typed dictionaries (integers, doubles, strings),
each a 32-bit entry count and per entry a 32-bit key length, the key, a 32-bit
element count and the elements (four bytes an integer, eight a double, a 32-bit
length and the bytes a string). Keys seen: ``SCHEMA_VERSION_KEY``, ``color`` and
``edgeColor`` (RGBA bytes), ``configId``, ``reflectivity``, ``stateID``;
``density``, ``extent`` (the B-rep's box, six doubles, model units); ``name`` and
``units``. Then the face, edge and vertex counts of the B-rep, and one block per
face followed by one per edge: a 32-bit id, the index list's length L, the
record count V, a 32-bit 0, a byte 0 and a float32 -1.0, then V records of eight
float32 and L 32-bit indices. A face's records are x, y, z, a unit normal and the
surface's (u, v); its indices are ``3, a, b, c`` per triangle, counter-clockwise
seen from outside, then a 0. An edge's first records are its polyline's points.
Face ids run from 1 to the face count and edge ids after them; each equals the
``PersistentID`` of its face or edge in the ACIS body.

Every count and length is checked against the bytes left before anything is
read (``mesh_dictionary_entries``, ``mesh_key_bytes``, ``mesh_blocks``), every
index against its block's records, and the declared counts against the blocks.
The clock is ticked once a block and once a record and a triangle inside one, so
one block of millions of records cannot outrun the time bound.
"""

import struct
from array import array
from dataclasses import dataclass, field

from ...errors import SldFormatError
from .._source import Clock
from ..limits import Limits

UNITS = {
    "mm": 0.001,
    "millimeters": 0.001,
    "millimetres": 0.001,
    "cm": 0.01,
    "centimeters": 0.01,
    "centimetres": 0.01,
    "m": 1.0,
    "meters": 1.0,
    "metres": 1.0,
    "in": 0.0254,
    "inch": 0.0254,
    "inches": 0.0254,
    "ft": 0.3048,
    "feet": 0.3048,
    "foot": 0.3048,
}
_BLOCK = struct.Struct("<4iBf")
_CHUNK = 4096  # records or triangles between ticks of the clock


def _bad(msg: str) -> SldFormatError:
    return SldFormatError(msg, detail={"stream": "MESH_DATA"})


@dataclass
class MeshHeader:
    """The dictionaries and counts of ``MESH_DATA``; ``end`` where the blocks start."""

    ints: dict[str, tuple[int, ...]] = field(default_factory=dict)
    doubles: dict[str, tuple[float, ...]] = field(default_factory=dict)
    strings: dict[str, tuple[str, ...]] = field(default_factory=dict)
    faces: int = 0
    edges: int = 0
    vertices: int = 0
    end: int = 0

    @property
    def units(self) -> str | None:
        got = self.strings.get("units")
        return got[0] if got else None

    @property
    def scale_m(self) -> float | None:
        u = self.units
        return UNITS.get(u.strip().lower()) if u else None

    @property
    def color(self) -> tuple[float, float, float, float] | None:
        got = self.ints.get("color")
        if not got:
            return None
        r, g, b, a = struct.pack("<i", got[0])
        return (r / 255.0, g / 255.0, b / 255.0, a / 255.0) if a else None

    @property
    def extent(self) -> tuple[float, ...] | None:
        got = self.doubles.get("extent")
        return got if got is not None and len(got) == 6 else None


def read_header(data: bytes, limits: Limits) -> MeshHeader:
    """The dictionaries and counts at the start of ``data`` (the stream, or enough of
    its head); ``SldFormatError`` when they run past it."""
    h = MeshHeader()
    i, n = 0, len(data)

    def i32() -> int:
        nonlocal i
        if i + 4 > n:
            raise _bad("MESH_DATA is cut short")
        (v,) = struct.unpack_from("<i", data, i)
        i += 4
        return v

    for kind in ("ints", "doubles", "strings"):
        count = i32()
        if not 0 <= count <= limits.mesh_dictionary_entries:
            raise limits.exceeded(
                "mesh_dictionary_entries", f"a MESH_DATA dictionary has {count:,} entries", count
            )
        target = getattr(h, kind)
        for _ in range(count):
            kl = i32()
            if not 0 <= kl <= limits.mesh_key_bytes or i + kl > n:
                raise _bad("a MESH_DATA key is too long or runs past the stream")
            key = data[i : i + kl].decode("latin-1")
            i += kl
            k = i32()
            if k < 0:
                raise _bad("a MESH_DATA entry has a negative count")
            if kind == "ints":
                if i + 4 * k > n:
                    raise _bad("a MESH_DATA entry runs past the stream")
                target[key] = struct.unpack_from(f"<{k}i", data, i)
                i += 4 * k
            elif kind == "doubles":
                if i + 8 * k > n:
                    raise _bad("a MESH_DATA entry runs past the stream")
                target[key] = struct.unpack_from(f"<{k}d", data, i)
                i += 8 * k
            else:
                if 4 * k > n - i:
                    raise _bad("a MESH_DATA entry runs past the stream")
                vals = []
                for _ in range(k):
                    sl = i32()
                    if not 0 <= sl <= limits.text_bytes or i + sl > n:
                        raise _bad("a MESH_DATA string is too long or runs past the stream")
                    vals.append(data[i : i + sl].decode("utf-8", "replace"))
                    i += sl
                target[key] = tuple(vals)
    h.faces, h.edges, h.vertices = i32(), i32(), i32()
    if min(h.faces, h.edges, h.vertices) < 0 or h.faces + h.edges > limits.mesh_blocks:
        raise limits.exceeded(
            "mesh_blocks", "MESH_DATA declares more blocks than are allowed", h.faces + h.edges
        )
    h.end = i
    return h


@dataclass
class DisplayMesh:
    """The faces of ``MESH_DATA`` as one indexed mesh in model units: ``positions``
    (float64 xyz), ``normals`` (float32), ``triangles`` (uint32) and ``faces``
    (``(id, first vertex, vertices, first triangle, triangles)`` per face block)."""

    header: MeshHeader
    positions: array
    normals: array
    triangles: array
    faces: list[tuple[int, int, int, int, int]]
    edges: int


def read(data: bytes, limits: Limits, clock: Clock | None = None) -> DisplayMesh:
    """Every face block of a whole ``MESH_DATA`` stream (edge blocks are checked and
    skipped); ``SldFormatError`` for anything malformed, to the stream's last byte."""
    h = read_header(data, limits)
    i, n = h.end, len(data)
    pos = array("d")
    nrm = array("f")
    tris = array("I")
    faces: list[tuple[int, int, int, int, int]] = []
    edges = 0
    for b in range(h.faces + h.edges):
        if clock is not None:
            clock.tick()
        if i + _BLOCK.size > n:
            raise _bad("a MESH_DATA block is cut short")
        bid, L, V, _zero, _flag, _minus = _BLOCK.unpack_from(data, i)
        i += _BLOCK.size
        if V < 0 or L < 0 or 32 * V + 4 * L > n - i:
            raise _bad("a MESH_DATA block declares more records or indices than the stream holds")
        recs = array("f")
        recs.frombytes(data[i : i + 32 * V])
        i += 32 * V
        idx = array("i")
        idx.frombytes(data[i : i + 4 * L])
        i += 4 * L
        if struct.pack("<i", 1) != b"\x01\x00\x00\x00":  # pragma: no cover - big-endian hosts
            recs.byteswap()
            idx.byteswap()
        if b >= h.faces:
            edges += 1
            if L and not 0 <= idx[0] <= V:
                raise _bad("a MESH_DATA edge block's point count is out of range")
            continue
        # a face: "3, a, b, c" per triangle, then 0
        if L % 4 != 1 or idx[L - 1] != 0:
            raise _bad("a MESH_DATA face's index list does not end with its terminator")
        t = (L - 1) // 4
        if t and set(idx[0 : L - 1 : 4]) != {3}:
            raise _bad("a MESH_DATA face holds a polygon that is not a triangle")
        a, bb, c = idx[1 : L - 1 : 4], idx[2 : L - 1 : 4], idx[3 : L - 1 : 4]
        if t and (min(min(a), min(bb), min(c)) < 0 or max(max(a), max(bb), max(c)) >= V):
            raise _bad("a MESH_DATA triangle names a record its face does not have")
        first_v = len(pos) // 3
        first_t = len(tris) // 3
        xs, ys, zs = recs[0::8], recs[1::8], recs[2::8]
        nx, ny, nz = recs[3::8], recs[4::8], recs[5::8]
        for k0 in range(0, V, _CHUNK):
            k1 = min(V, k0 + _CHUNK)
            if clock is not None:
                clock.tick(k1 - k0)
            for k in range(k0, k1):
                pos.extend((xs[k], ys[k], zs[k]))
                nrm.extend((nx[k], ny[k], nz[k]))
        for k0 in range(0, t, _CHUNK):
            k1 = min(t, k0 + _CHUNK)
            if clock is not None:
                clock.tick(k1 - k0)
            for k in range(k0, k1):
                tris.extend((first_v + a[k], first_v + bb[k], first_v + c[k]))
        faces.append((bid, first_v, V, first_t, t))
    if i != n:
        raise _bad(f"{n - i} bytes follow the last MESH_DATA block")
    return DisplayMesh(h, pos, nrm, tris, faces, edges)


__all__ = ["UNITS", "DisplayMesh", "MeshHeader", "read", "read_header"]
