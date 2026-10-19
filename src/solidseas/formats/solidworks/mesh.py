"""The display tessellation SOLIDWORKS caches for drawing a model.

``Contents/DisplayLists`` (legacy: ``Contents/DisplayLists__ZLB``) holds one
tessellation table per displayed face. A table is six consecutive descriptors,
each ``u32 item_size, u32 kind, u32 flags (= 2), u32 count`` followed by
``item_size * count`` data bytes:

1. ``(4, 8)`` strip lengths L, each at least 3;
2. ``(12, 100)`` positions, ``C = sum(L)`` float32 xyz in metres;
3. ``(12, 100)`` normals, 0 or C float32 xyz;
4. ``(4, 8)`` ``E = sum(2L - 2)`` per-strip-edge tags, or 0 entries (meaning: hypothesis);
5. ``(4, 8)`` one value per strip, each ``2L - 2``;
6. ``(1, 8)`` E bytes, or 0 when descriptor 4 is empty (meaning: unknown).

Strip vertices are consecutive and expand with OpenGL triangle-strip winding.
On the synthetic box this reproduces SOLIDWORKS' own STL export exactly. The
mesh is what SOLIDWORKS last displayed: per-face, usually not watertight, and
for the configuration and display state at save time. It is not an exact B-rep.

The same table grammar appears in ``FaceTessellations/<nnn-nnn-nnn>`` streams of
2024-era assemblies (in component coordinates), ``Contents/VBLists`` and
``Contents/Config-<n>-ShrinkWrap``. The descriptor-table description in the
cadmpeg format notes (CC-BY-4.0) was the starting hypothesis; this is an
independent implementation checked against SOLIDWORKS' STL export.
"""

import re
import struct
import sys
from array import array
from collections.abc import Iterator
from dataclasses import dataclass

from .container import Container

MAX_DISPLAY_LIST_BYTES = 1 << 30
MAX_TABLE_VERTICES = 50_000_000

_D1 = re.compile(rb"\x04\x00\x00\x00\x08\x00\x00\x00\x02\x00\x00\x00")


@dataclass(frozen=True)
class FaceTess:
    """One displayed face: a range of vertices and triangles in the mesh."""

    offset: int  # byte offset of descriptor 1 in the source stream
    first_vertex: int
    n_vertices: int
    first_triangle: int
    n_triangles: int
    strips: tuple[int, ...]
    has_normals: bool


class Mesh:
    """Indexed triangle mesh in metres, stored compactly.

    ``positions`` and ``normals`` are interleaved float32 xyz arrays and
    ``triangles`` an interleaved uint32 index array. Faces without stored
    normals get (0, 0, 0) normals.
    """

    def __init__(self, stream: str = "") -> None:
        self.positions = array("f")
        self.normals = array("f")
        self.triangles = array("I")
        self.faces: list[FaceTess] = []
        self.stream = stream
        self.dropped_degenerate = 0

    @property
    def n_vertices(self) -> int:
        return len(self.positions) // 3

    @property
    def n_triangles(self) -> int:
        return len(self.triangles) // 3

    def vertex(self, i: int) -> tuple[float, float, float]:
        p = self.positions
        return p[3 * i], p[3 * i + 1], p[3 * i + 2]

    def iter_triangles(self) -> Iterator[tuple[tuple[float, float, float], ...]]:
        t = self.triangles
        for k in range(0, len(t), 3):
            yield self.vertex(t[k]), self.vertex(t[k + 1]), self.vertex(t[k + 2])

    def bbox(self) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
        p = self.positions
        if not p:
            return None
        return (min(p[0::3]), min(p[1::3]), min(p[2::3])), (max(p[0::3]), max(p[1::3]), max(p[2::3]))

    def volume(self) -> float:
        """Signed volume (m^3) by the divergence theorem. Meaningful only for a closed mesh."""
        total = 0.0
        for a, b, c in self.iter_triangles():
            total += (
                a[0] * (b[1] * c[2] - b[2] * c[1])
                - a[1] * (b[0] * c[2] - b[2] * c[0])
                + a[2] * (b[0] * c[1] - b[1] * c[0])
            ) / 6.0
        return total

    def area(self) -> float:
        """Total triangle area (m^2)."""
        total = 0.0
        for a, b, c in self.iter_triangles():
            u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
            v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
            n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            total += 0.5 * (n[0] * n[0] + n[1] * n[1] + n[2] * n[2]) ** 0.5
        return total

    def to_stl(self, scale: float = 1000.0) -> bytes:
        """Binary STL. The default scale converts metres to millimetres."""
        out = bytearray(b"SolidSeas display tessellation".ljust(80, b" "))
        out += struct.pack("<I", self.n_triangles)
        for a, b, c in self.iter_triangles():
            u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
            v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
            nx, ny, nz = u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]
            ln = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
            out += struct.pack(
                "<12fH",
                nx / ln,
                ny / ln,
                nz / ln,
                *(x * scale for x in a),
                *(x * scale for x in b),
                *(x * scale for x in c),
                0,
            )
        return bytes(out)


def _desc(d: bytes, p: int) -> tuple[int, int, int, int, int] | None:
    if p + 16 > len(d):
        return None
    isz, kind, fl, cnt = struct.unpack_from("<IIII", d, p)
    if fl != 2 or isz == 0 or isz > 64 or cnt > MAX_TABLE_VERTICES or p + 16 + isz * cnt > len(d):
        return None
    return isz, kind, cnt, p + 16, p + 16 + isz * cnt


def _arr(code: str, b) -> array:
    a = array(code)
    a.frombytes(b)
    if sys.byteorder != "little":
        a.byteswap()
    return a


def parse_tess_tables(d: bytes) -> Iterator[dict]:
    """Yield ``{"off", "end", "strips", "positions", "normals"}`` for every complete,
    self-consistent six-descriptor table in ``d``."""
    mv = memoryview(d)
    pos = 0
    for m in _D1.finditer(d):
        p = m.start()
        if p < pos:
            continue
        a = _desc(d, p)
        if not a or a[2] == 0:
            continue
        n = a[2]
        strips = _arr("I", mv[a[3] : a[4]])
        if min(strips) < 3:
            continue
        count = sum(strips)
        b = _desc(d, a[4])
        if not b or b[:3] != (12, 100, count):
            continue
        c = _desc(d, b[4])
        if not c or c[:2] != (12, 100) or c[2] not in (0, count):
            continue
        edges = 2 * count - 2 * n
        e = _desc(d, c[4])
        if not e or e[:2] != (4, 8) or e[2] not in (0, edges):
            continue
        g5 = _desc(d, e[4])
        if not g5 or g5[:3] != (4, 8, n):
            continue
        per_strip = _arr("I", mv[g5[3] : g5[4]])
        if any(v != 2 * s - 2 for v, s in zip(per_strip, strips, strict=True)):
            continue
        g6 = _desc(d, g5[4])
        if not g6 or g6[:2] != (1, 8) or g6[2] != e[2]:
            continue
        positions = _arr("f", mv[b[3] : b[4]])
        s = sum(positions)
        if s != s or abs(s) == float("inf"):  # NaN or infinity: not a table
            continue
        yield {
            "off": p,
            "end": g6[4],
            "strips": strips,
            "positions": positions,
            "normals": _arr("f", mv[c[3] : c[4]]),
        }
        pos = g6[4]


def mesh_from_bytes(d: bytes, stream: str = "", *, keep_degenerate: bool = False) -> Mesh:
    """Triangle mesh from every tessellation table in a stream."""
    mesh = Mesh(stream)
    pm, nm, tm = mesh.positions, mesh.normals, mesh.triangles
    for t in parse_tess_tables(d):
        pos, nor, strips = t["positions"], t["normals"], t["strips"]
        v0 = len(pm) // 3
        t0 = len(tm) // 3
        pm.extend(pos)
        if len(nor) == len(pos):
            nm.extend(nor)
        else:
            nm.extend(array("f", bytes(4 * len(pos))))
        s = 0
        for ln in strips:
            for j in range(ln - 2):
                a, b, c = s + j, s + j + 1, s + j + 2
                if j & 1:
                    b, c = c, b
                if not keep_degenerate:
                    pa, pb, pc = pos[3 * a : 3 * a + 3], pos[3 * b : 3 * b + 3], pos[3 * c : 3 * c + 3]
                    if pa == pb or pb == pc or pa == pc:
                        mesh.dropped_degenerate += 1
                        continue
                tm.extend((v0 + a, v0 + b, v0 + c))
            s += ln
        n_vertices = len(pos) // 3
        mesh.faces.append(
            FaceTess(t["off"], v0, n_vertices, t0, len(tm) // 3 - t0, tuple(strips), len(nor) == len(pos))
        )
    return mesh


def read_display_mesh(container: Container, *, stream: str = "Contents/DisplayLists") -> Mesh | None:
    """The cached display tessellation of a part, or None when the stream is absent.

    For an assembly this is not an assembled model: 2024-era assemblies keep
    component meshes in ``FaceTessellations/*`` in component coordinates.
    """
    if stream not in container:
        return None
    data = container.read(stream, max_bytes=MAX_DISPLAY_LIST_BYTES)
    return mesh_from_bytes(data, container.info(stream).name)
