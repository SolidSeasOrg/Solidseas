"""Exports for 3D printing: binary STL and 3MF of a part or an assembly (provisional).

``docs/API.md`` section 3.17 has the API. A part is exported from its Parasolid
bodies, tessellated (:mod:`solidseas.tessellate`) at a print-quality chord
tolerance, as closed solids over shared vertices with outward normals. Only
when it has no solid body to tessellate is the display mesh SOLIDWORKS saved
used, labelled as such and with the warning ``display_mesh_fallback``: that mesh
is what SOLIDWORKS last drew and is often not closed.

A model file that is not a SOLIDWORKS document (an STL, a 3MF, a STEP file...,
:func:`solidseas.formats.open_model`) is exported from its scene
(:meth:`~solidseas.formats.ModelDocument.scene`, asking for its B-rep bodies
first): each mesh object welded by exact coordinates and checked as a part's
mesh is, placed by the scene's items. ``source_format`` says which format the
model came from.

An assembly is exported from its display geometry
(:func:`solidseas.geometry.display_geometry`): every unsuppressed, visible part
instance of one configuration, placed as the assembly places it. The ``brep``
source comes first, so each component file's part is tessellated once from its
own bodies, and a stored mesh is used only where that fails, labelled in the
same way. Instances that cannot be placed or meshed are left out and counted.

A 3MF holds one object per component file (per mesh) and a build item, with its
transform, per instance, or with ``merge`` one object holding every placed
triangle. Its package has the three parts the 3MF core specification asks for:
``[Content_Types].xml``, ``_rels/.rels`` and ``3D/3dmodel.model``, the model in
millimetres, its numbers written so that they read back as the same float64. A
binary STL is every placed triangle in millimetres: an 80-byte header that does
not start with ``solid``, the count, and 50 bytes a triangle.

Slicers read a 3MF's coordinates, like an STL's, as float32. Two vertices of a
triangle that are a hair apart can be one point there, which leaves a triangle
with no area that the slicer counts as an error and repairs. So wherever a
triangle's corners would meet in float32, as written, its vertices are merged and
the triangles left with a repeated vertex dropped: an edge collapse, which keeps a
closed solid closed (:func:`_merged_coincident`). A sliver whose corners stay
apart but lie on one line has its longest edge flipped instead (:func:`_flipped`).

Pure Python, standard library only. Reads are bounded by the tessellation's and
the display geometry's limits, and every write by ``max_bytes``. A file is only
ever written by creating it new (never through a link, never over a file that is
there unless ``overwrite``, when a new file is written beside it and renamed over
it, and never to a device or an alternate data stream), and a write that fails
removes what it created.
"""

import math
import os
import struct
import time
import zipfile
from array import array
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, BinaryIO

from . import __version__
from .errors import (
    InvalidArgumentError,
    NothingToExportError,
    OutputRefusedError,
    ReaderWarning,
    SldLimitError,
)
from .formats.solidworks.components import IDENTITY, Placement

if TYPE_CHECKING:
    from .step import StepResult

FORMATS = ("3mf", "stl")  # for 3D printing: what print_model and write_export write
# Every format export_document and the CLI's export write: the print formats and STEP
# (solidseas.step), which holds the exact geometry rather than triangles.
EXPORT_FORMATS = ("3mf", "step", "stl")
EXTENSIONS = {"3mf": ".3mf", "stl": ".stl", "step": ".step"}
MIME_TYPES = {"3mf": "model/3mf", "stl": "model/stl", "step": "model/step"}
# The chord tolerance a print gets when none is given: a quarter of the viewer's (which
# is 1e-3 of the part's box diagonal), and never coarser than 0.01 mm, just under the
# 0.0125 mm to which the slicers simplify a layer's outline by default.
CHORD_FRACTION = 2.5e-4
MAX_CHORD_M = 1e-5
DEFAULT_ANGLE_DEG = 15.0
DEFAULT_MAX_TRIANGLES = 20_000_000
DEFAULT_MAX_SECONDS = 300.0
DEFAULT_MAX_BYTES = 2 << 30
# Where an assembly's meshes come from: each part's own bodies first, the stored meshes
# after them (solidseas.geometry.SOURCES, reordered).
SOURCES = ("brep", "assembly", "nested", "file", "subassembly")
MAX_COORDINATE_MM = 1e9  # a placed vertex farther out than 1,000 km is not a part
MAX_LISTED = 1_000  # skipped instances listed one by one; counts cover them all
# An assembly instance whose part holds no solid body, only surfaces or wires (geometry's
# reason bodies_not_asked, since the export asks for solids only).
SURFACES_ONLY = "surfaces_only"
SURFACES_ONLY_TEXT = (
    "its part holds only surface or wire bodies, which cannot be printed, "
    "and no display mesh was found for it"
)

STL_HEADER = b"Binary STL from SolidSeas, millimetres".ljust(80, b" ")  # never "solid" first: ASCII STL
MODEL_PART = "3D/3dmodel.model"
CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
MODEL_CONTENT_TYPE = "application/vnd.ms-package.3dmanufacturing-3dmodel+xml"
RELS_CONTENT_TYPE = "application/vnd.openxmlformats-package.relationships+xml"
START_PART_TYPE = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
CONTENT_TYPES_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    f'<Default Extension="rels" ContentType="{RELS_CONTENT_TYPE}"/>'
    f'<Default Extension="model" ContentType="{MODEL_CONTENT_TYPE}"/>'
    "</Types>\n"
)
RELS_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    f'<Relationship Target="/{MODEL_PART}" Id="rel0" Type="{START_PART_TYPE}"/>'
    "</Relationships>\n"
)
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)  # every entry the same time: the same model gives the same bytes
_FACET = struct.Struct("<12fH")
_CHUNK = 4096  # vertices or triangles formatted at a time


# --------------------------------------------------------------------------- the model
@dataclass(frozen=True)
class PrintObject:
    """One mesh to print: ``positions`` (float64 xyz, metres) and ``triangles`` (uint32
    index triples) over shared vertices, in the object's own frame. ``source`` is
    ``bodies`` (tessellated from its Parasolid bodies), ``display_mesh`` (the display
    mesh SOLIDWORKS saved, a fallback) or ``mesh`` (a mesh file's own triangles).
    ``closed``: every edge of its triangles is used twice, once each way
    (:func:`oriented_closed`). ``file`` is the component file key in an assembly
    (None for a part; a model file's tree node), ``chord_m`` the chord tolerance it
    was made at (None for a display mesh or a mesh file)."""

    name: str
    file: str | None
    configuration: str | None
    source: str
    positions: array = field(repr=False, compare=False)
    triangles: array = field(repr=False, compare=False)
    closed: bool
    chord_m: float | None
    warnings: tuple[ReaderWarning, ...] = ()

    @property
    def n_vertices(self) -> int:
        return len(self.positions) // 3

    @property
    def n_triangles(self) -> int:
        return len(self.triangles) // 3

    def measures(self) -> dict[str, Any]:
        """``volume_m3`` (meaningful when closed), ``area_m2`` and ``box`` ((low), (high),
        metres, None without triangles), from the float64 vertices."""
        return mesh_measures(self.positions, self.triangles)


@dataclass(frozen=True)
class PrintItem:
    """One placed copy of ``objects[object]``: ``instance`` is its component tree id
    (None for a part) and ``placement`` takes the object's frame to the model's."""

    object: int
    instance: str | None
    placement: Placement = IDENTITY


@dataclass(frozen=True)
class PrintModel:
    """A part or one assembly configuration, ready to write as STL or 3MF.

    ``counts`` has ``objects``, ``items``, ``vertices`` (over the objects),
    ``triangles`` (over the items, each counting its object's) and, for an assembly,
    ``parts``, ``placed``, ``skipped``, ``suppressed`` and ``hidden`` as
    :func:`~solidseas.geometry.display_geometry` counts them. ``skipped`` lists the
    instances left out (geometry's ``SkippedInstance``, at most 1,000), ``chord_m``
    the chord tolerance asked for (None: each part's automatic print chord) and
    ``source_format`` the registry id of the format the model was read from
    (``solidworks``, ``stl``, ``3mf``...)."""

    name: str
    doc_type: str
    configuration: str | None
    objects: tuple[PrintObject, ...]
    items: tuple[PrintItem, ...]
    chord_m: float | None
    counts: dict[str, int]
    skipped: tuple[Any, ...] = ()
    warnings: tuple[ReaderWarning, ...] = ()
    seconds: float = 0.0
    source_format: str = "solidworks"

    @property
    def closed(self) -> bool:
        """Every object used is closed."""
        used = {it.object for it in self.items}
        return bool(used) and all(self.objects[i].closed for i in used)

    def measures(self) -> dict[str, float]:
        """``volume_m3`` and ``area_m2`` of every item: each object measured once and
        counted for each item that places it (rigid placements keep both; a mirrored
        one keeps the volume positive)."""
        per = {}
        vol = area = 0.0
        for it in self.items:
            m = per.get(it.object)
            if m is None:
                m = per[it.object] = self.objects[it.object].measures()
            vol += m["volume_m3"] * abs(_det(it.placement.rotation))
            area += m["area_m2"]
        return {"volume_m3": vol, "area_m2": area}


@dataclass(frozen=True)
class ExportResult:
    """A file written: its ``path``, ``format``, size in ``bytes``, whether every placed
    triangle went into one object (``merged``; always for STL) and the ``model``."""

    path: str
    format: str
    bytes: int
    merged: bool
    model: PrintModel


# --------------------------------------------------------------------------- mesh checks
def oriented_closed(triangles: array, n_vertices: int) -> bool:
    """Whether every edge of ``triangles`` (index triples) is used exactly twice, once
    each way: a closed, consistently oriented surface. No triangle may repeat a
    vertex. Memory is a few integers a corner (an adjacency table in arrays, each
    vertex's row sorted), and the time a pass over the corners and a bisection for
    each edge's reverse: n log(degree), so a vertex shared by many triangles (a fan)
    costs no more than many vertices would."""
    n = len(triangles)
    if n == 0 or n % 3:
        return False
    starts = array("Q", bytes(8 * (n_vertices + 1)))
    for v in triangles:
        if v >= n_vertices:
            return False
        starts[v + 1] += 1
    for i in range(n_vertices):
        starts[i + 1] += starts[i]
    cursor = array("Q", starts)
    out = array("I", bytes(4 * n))  # each corner's edge: the next vertex of its triangle
    for k in range(0, n, 3):
        a, b, c = triangles[k], triangles[k + 1], triangles[k + 2]
        if a == b or b == c or c == a:
            return False
        for v, w in ((a, b), (b, c), (c, a)):
            out[cursor[v]] = w
            cursor[v] += 1
    for v in range(n_vertices):
        s, e = starts[v], starts[v + 1]
        if e - s > 1:
            out[s:e] = array("I", sorted(out[s:e]))
    for v in range(n_vertices):
        prev = -1
        for i in range(starts[v], starts[v + 1]):
            w = out[i]
            if w == prev:  # an edge used twice the same way
                return False
            prev = w
            lo, hi = starts[w], starts[w + 1]
            j = bisect_left(out, v, lo, hi)
            if j == hi or out[j] != v:  # its reverse is missing
                return False
    return True


def _merged_coincident(f32: array, triangles: array) -> array | None:
    """``triangles`` with the vertices merged that are corners of one triangle and one
    point in ``f32`` (each vertex's coordinates as written, rounded to float32: what
    an STL holds and a slicer reads), and the triangles left with a repeated vertex
    dropped; None when no triangle has two corners at one point. That is an edge
    collapse: the two triangles beside a collapsed edge go, and their other edges
    meet, so a closed solid stays closed unless a vertex pair shares a third
    neighbour (:func:`oriented_closed` says)."""
    pairs = []
    t, f = triangles, f32
    for k in range(0, len(t), 3):
        a, b, c = t[k], t[k + 1], t[k + 2]
        ax, bx, cx = f[3 * a], f[3 * b], f[3 * c]
        if ax != bx and bx != cx and ax != cx:  # the usual case, decided by x alone
            continue
        pa, pb, pc = f[3 * a : 3 * a + 3], f[3 * b : 3 * b + 3], f[3 * c : 3 * c + 3]
        if pa == pb:
            pairs.append((a, b))
        if pb == pc:
            pairs.append((b, c))
        if pa == pc:
            pairs.append((a, c))
    if not pairs:
        return None
    parent: dict[int, int] = {}

    def root(v: int) -> int:
        while parent.get(v, v) != v:
            v = parent[v]
        return v

    for a, b in pairs:
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    to = {v: root(v) for v in parent}
    out = array("I")
    for k in range(0, len(t), 3):
        a, b, c = to.get(t[k], t[k]), to.get(t[k + 1], t[k + 1]), to.get(t[k + 2], t[k + 2])
        if a != b and b != c and a != c:
            out.extend((a, b, c))
    return out


def _compacted(values: list[array], triangles: array) -> tuple[list[array], array]:
    """Only the vertices ``triangles`` use, renumbered in their order: each of
    ``values`` (three numbers a vertex) kept for them, and the triangles over the new
    numbers."""
    used = sorted(set(triangles))
    new = {v: i for i, v in enumerate(used)}
    kept = []
    for vals in values:
        out = array(vals.typecode)
        for v in used:
            out.extend(vals[3 * v : 3 * v + 3])
        kept.append(out)
    return kept, array("I", (new[v] for v in triangles))


def _flat(mm: array, f32: array, t: array, offsets=None) -> list[int]:
    """The offsets of the triangles of ``t`` (all, or those at ``offsets``) with no
    area: their corners on one line in float32 millimetres, as a slicer reads them, or
    in float64 millimetres, as a 3MF holds them."""
    out = []
    for k in range(0, len(t), 3) if offsets is None else offsets:
        i, j, m = 3 * t[k], 3 * t[k + 1], 3 * t[k + 2]
        for p in (f32, mm):
            ax, ay, az = p[i], p[i + 1], p[i + 2]
            ux, uy, uz = p[j] - ax, p[j + 1] - ay, p[j + 2] - az
            wx, wy, wz = p[m] - ax, p[m + 1] - ay, p[m + 2] - az
            if uy * wz - uz * wy == 0.0 and uz * wx - ux * wz == 0.0 and ux * wy - uy * wx == 0.0:
                out.append(k)
                break
    return out


def _across(mm: array, t: array, k: int) -> tuple[int, int, int]:
    """A flat triangle at ``k`` as (a, b, m), in its own order: ``m`` the corner between
    the other two, across from the longest edge a-b."""
    c = (t[k], t[k + 1], t[k + 2])

    def length(u: int, v: int) -> float:
        return sum((mm[3 * u + i] - mm[3 * v + i]) ** 2 for i in range(3))

    sides = [length(c[0], c[1]), length(c[1], c[2]), length(c[2], c[0])]
    s = sides.index(max(sides))
    return c[s], c[(s + 1) % 3], c[(s + 2) % 3]


def _flipped(mm: array, f32: array, triangles: array, flat: list[int]) -> array | None:
    """``triangles`` with each flat triangle's longest edge flipped: a flat (a, b, m),
    ``m`` between a and b, and its neighbour (b, a, d) across that edge become
    (b, m, d) and (m, a, d), the neighbour's own surface cut at ``m``. Nothing moves
    and every edge stays used twice, once each way; no triangle is dropped, so a
    closed solid stays closed. A flip is left out where the edge m-d is there
    already, where the neighbour would come out flat too, or where two flat triangles
    want one neighbour (tried again in the next round). None when nothing flipped."""
    t = array("I", triangles)
    flipped = False
    for _round in range(4):
        want: dict[tuple[int, int], int] = {}
        corners: dict[int, tuple[int, int, int]] = {}
        for k in flat:
            a, b, m = corners[k] = _across(mm, t, k)
            want[(b, a)] = k
        found: dict[int, tuple[int, int]] = {}
        for q in range(0, len(t), 3):
            x, y, z = t[q], t[q + 1], t[q + 2]
            for e, d in (((x, y), z), ((y, z), x), ((z, x), y)):
                k = want.get(e)
                if k is not None and k != q:
                    found[k] = (q, d)
        new: dict[tuple[int, int], int] = {}
        for k, (_q, d) in found.items():
            m = corners[k][2]
            new[(m, d)] = new[(d, m)] = k
        taken = set()
        if new:
            for q in range(0, len(t), 3):
                x, y, z = t[q], t[q + 1], t[q + 2]
                for e in ((x, y), (y, z), (z, x)):
                    k = new.get(e)
                    if k is not None:
                        taken.add(k)
        used: set[int] = set()
        done: list[int] = []
        for k in flat:
            if k not in found or k in taken or k in used:
                continue
            q, d = found[k]
            a, b, m = corners[k]
            if q in used or d == m:
                continue
            before = t[k : k + 3], t[q : q + 3]
            t[k : k + 3] = array("I", (b, m, d))
            t[q : q + 3] = array("I", (m, a, d))
            if _flat(mm, f32, t, (k, q)):
                t[k : k + 3], t[q : q + 3] = before
                continue
            used.update((k, q))
            done.append(k)
        if not done:
            break
        flipped = True
        flat = [k for k in flat if k not in used]
        if not flat:
            break
    return t if flipped else None


def _without_coincident(positions: array, triangles: array, closed: bool) -> tuple[array, array, bool]:
    """``positions`` (metres) and ``triangles`` with no triangle whose corners meet in
    float32 millimetres (:func:`_merged_coincident`), compacted, and no flat triangle
    where an edge flip can give it area (:func:`_flipped`); and whether that is
    closed. Unchanged when there is nothing to do, or when the change would open a
    closed solid (a vertex pair sharing a third neighbour): a slicer's repair then
    does better than a mesh that is not closed."""
    mm = array("d", (v * 1000.0 for v in positions))
    f32 = array("f", mm)
    pos, tris = positions, triangles
    merged = _merged_coincident(f32, triangles)
    if merged is not None:
        (pos, mm, f32), tris = _compacted([positions, mm, f32], merged)
    flat = _flat(mm, f32, tris)
    if flat:
        tris = _flipped(mm, f32, tris, flat) or tris
    if tris is triangles:
        return positions, triangles, closed
    now = oriented_closed(tris, len(pos) // 3)
    if closed and not now:
        return positions, triangles, closed
    return pos, tris, now


def mesh_measures(positions: array, triangles: array) -> dict[str, Any]:
    """Volume (m^3, by the divergence theorem), area (m^2) and box of a welded mesh."""
    vol = area = 0.0
    p, t = positions, triangles
    for k in range(0, len(t), 3):
        i, j, m = 3 * t[k], 3 * t[k + 1], 3 * t[k + 2]
        ax, ay, az = p[i], p[i + 1], p[i + 2]
        bx, by, bz = p[j], p[j + 1], p[j + 2]
        cx, cy, cz = p[m], p[m + 1], p[m + 2]
        vol += ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)
        ux, uy, uz = bx - ax, by - ay, bz - az
        wx, wy, wz = cx - ax, cy - ay, cz - az
        nx, ny, nz = uy * wz - uz * wy, uz * wx - ux * wz, ux * wy - uy * wx
        area += 0.5 * math.sqrt(nx * nx + ny * ny + nz * nz)
    box = None
    if t:
        used = sorted(set(t))
        xs = [p[3 * i] for i in used]
        ys = [p[3 * i + 1] for i in used]
        zs = [p[3 * i + 2] for i in used]
        box = ((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))
    return {"volume_m3": vol / 6.0, "area_m2": area, "box": box}


_WELD_CHUNK = 65_536  # vertices whose coordinates are copied out at a time, to key them


def weld(mesh) -> tuple[array, array]:
    """A display mesh (:class:`~solidseas.formats.solidworks.mesh.Mesh`, one set of
    vertices a face) over shared vertices: vertices at the same point become one, and
    triangles left with a repeated vertex are dropped. The points are numbered as the
    triangles first use them, each with the coordinates of the corner that first did.

    In two passes, so that the table of points is gone before the result is built:
    each vertex is mapped to the first vertex at its point, keyed by the bytes of its
    three coordinates (a negative zero read as zero, as the numbers compare), then the
    triangles are numbered through that map. That takes about 170 bytes a point at its
    peak, where a table keyed by tuples of floats that lived beside the result took about
    290, and on a display mesh, whose faces share only their edges, it is faster too: a
    point is looked up once a vertex, not once a corner. Coordinates that are not all
    finite are welded by their values, one corner at a time (:func:`_weld_by_value`):
    a NaN equals nothing, not even itself."""
    p, t = mesh.positions, mesh.triangles
    if not isinstance(p, array) or p.typecode not in "fd" or not _finite(p):
        return _weld_by_value(p, t)
    n = len(p) // 3
    step = 3 * p.itemsize
    negative_zero = array(p.typecode, [-0.0]).tobytes()
    first: dict[bytes, int] = {}
    same = array("I", bytes(4 * n))  # each vertex's first vertex at its point
    for start in range(0, n, _WELD_CHUNK):
        end = min(n, start + _WELD_CHUNK)
        raw = p[3 * start : 3 * end].tobytes()
        check = negative_zero in raw
        at = 0
        for v in range(start, end):
            key = raw[at : at + step]
            at += step
            if check and negative_zero in key:
                key = array(p.typecode, (x + 0.0 for x in p[3 * v : 3 * v + 3])).tobytes()
            same[v] = first.setdefault(key, v)
    del first
    number = [-1] * n  # a point's first vertex -> its number, once a triangle uses it
    pos = array("d")
    tris = array("I")
    count = 0
    for k in range(0, len(t), 3):
        i = t[k]
        s = same[i]
        a = number[s]
        if a < 0:
            a = number[s] = count
            count += 1
            pos.extend((p[3 * i], p[3 * i + 1], p[3 * i + 2]))
        i = t[k + 1]
        s = same[i]
        b = number[s]
        if b < 0:
            b = number[s] = count
            count += 1
            pos.extend((p[3 * i], p[3 * i + 1], p[3 * i + 2]))
        i = t[k + 2]
        s = same[i]
        c = number[s]
        if c < 0:
            c = number[s] = count
            count += 1
            pos.extend((p[3 * i], p[3 * i + 1], p[3 * i + 2]))
        if a != b and b != c and a != c:
            tris.extend((a, b, c))
    return pos, tris


def _finite(values: array) -> bool:
    """Whether every one of ``values`` is finite: their exact sum, in one pass, is."""
    try:
        return math.isfinite(math.fsum(values))
    except (OverflowError, ValueError):  # a sum past float's range, or inf and -inf
        return False


def _weld_by_value(p, t) -> tuple[array, array]:
    """:func:`weld`, one corner at a time, keyed by the coordinates' values."""
    index: dict[tuple[float, float, float], int] = {}
    pos = array("d")
    tris = array("I")
    for k in range(0, len(t), 3):
        ids = []
        for i in (t[k], t[k + 1], t[k + 2]):
            key = (p[3 * i], p[3 * i + 1], p[3 * i + 2])
            j = index.get(key)
            if j is None:
                j = index[key] = len(index)
                pos.extend(key)
            ids.append(j)
        if ids[0] != ids[1] and ids[1] != ids[2] and ids[0] != ids[2]:
            tris.extend(ids)
    return pos, tris


def _det(r) -> float:
    return (
        r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1])
        - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
        + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0])
    )


# --------------------------------------------------------------------------- building
def _format(fmt: Any) -> str:
    if not isinstance(fmt, str) or fmt.lower() not in FORMATS:
        raise InvalidArgumentError(
            f"format is one of {', '.join(FORMATS)}", detail={"parameter": "format", "value": str(fmt)[:16]}
        )
    return fmt.lower()


def _number(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise InvalidArgumentError(
            f"{name} must be a number from {low:g} to {high:g}", detail={"parameter": name}
        )
    return float(value)


def _whole(value: Any, name: str, low: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < low:
        raise InvalidArgumentError(
            f"{name} must be a whole number of at least {low}", detail={"parameter": name}
        )
    return value


def _stem(name: str | None, fallback: str) -> str:
    from .formats.registry import by_extension

    if not name:
        return fallback
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    stem, ext = os.path.splitext(base)
    if ext.lower() in (".sldprt", ".sldasm", ".slddrw") or (ext and by_extension(ext) is not None):
        base = stem
    for suffix in ("-sldprt", "-sldasm"):  # a nested document's stream name
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
    return base or fallback


def _tess_options(chord_m: float | None, angle_deg: float, max_triangles: int, max_seconds: float) -> dict:
    opts: dict[str, Any] = {
        "body_types": ("solid",),
        "angle_deg": angle_deg,
        "max_triangles": max_triangles,
        "max_seconds": max_seconds,
    }
    if chord_m is None:
        opts.update(chord_fraction=CHORD_FRACTION, max_chord_m=MAX_CHORD_M)
    else:
        opts["chord_m"] = chord_m
    return opts


def _brep_warnings(t) -> list[ReaderWarning]:
    out: list[ReaderWarning] = []
    reasons = ", ".join(f"{k} {v}" for k, v in sorted(t.reasons.items()))
    if t.counts["faces_skipped"]:
        out.append(
            ReaderWarning(
                "faces_left_out",
                f"{t.counts['faces_skipped']} of {t.counts['faces']} faces could not be tessellated "
                f"({reasons}): the solid has holes there, which a slicer may or may not repair",
            )
        )
    if t.counts["bodies_skipped"]:
        out.append(
            ReaderWarning(
                "faces_left_out",
                f"{t.counts['bodies_skipped']} of {t.counts['bodies']} bodies could not be walked face by "
                "face and are left out",
            )
        )
    if t.counts["bodies_left_out"]:
        out.append(
            ReaderWarning(
                "bodies_left_out",
                f"{t.counts['bodies_left_out']} bodies that are not solids (surfaces or wires) are left out: "
                "a printer prints solids",
            )
        )
    return out


def _fallback_warning(where: str) -> ReaderWarning:
    return ReaderWarning(
        "display_mesh_fallback",
        f"{where}, so the display mesh SOLIDWORKS saved is exported instead; it may not be closed, "
        "and a slicer may have to repair it",
    )


def _facing(
    positions: array, triangles: array, chord_m: float | None = None
) -> tuple[array, int, int, int, int]:
    """The guard on how a closed object's shells (its connected pieces) face:
    ``(triangles, turned, left, unsure)``. A closed shell that lies inside no other and
    has a negative signed volume can only be a solid inside out: it is turned round, and
    when every shell of the object faces the wrong way the whole object is inside out and
    every one is turned. Otherwise a shell whose sign disagrees with its nesting (one
    facing outward inside another) is either a body inside a body or a void turned inside
    out, which the mesh cannot tell apart: it is counted in ``left`` and left as it is. A
    shell that touches another so that which lies inside which cannot be told
    (:func:`~solidseas.tessellate.checks.nesting`) is counted in ``unsure`` and left as it
    is, whichever way it faces. ``chord_m`` is how far apart the triangles of two shells
    that touch may lie (the tessellation's chord tolerance; for a mesh of unknown origin,
    :data:`CHORD_FRACTION` of its box diagonal). Past :data:`~solidseas.tessellate.checks.MAX_SHELLS`
    closed shells none is judged, and the last of the five, the shells, says how many."""
    from .tessellate import checks

    groups = checks.pieces(triangles, len(positions) // 3)
    points = checks.Flat(positions)
    found = checks.shells(points, triangles, groups, closed=True)
    unsure = unjudged = 0
    if len(found) > checks.MAX_SHELLS:
        unjudged = sum(1 for s in found if s.closed)
    if len(found) > 1:
        if not chord_m:
            lo = (min(positions[0::3]), min(positions[1::3]), min(positions[2::3]))
            hi = (max(positions[0::3]), max(positions[1::3]), max(positions[2::3]))
            chord_m = CHORD_FRACTION * math.dist(lo, hi)
        depth = checks.nesting(points, triangles, found, chord_m)
        if len(found) <= checks.MAX_SHELLS:
            unsure = sum(1 for k, s in enumerate(found) if depth[k] is None and s.volume != 0.0)
    else:
        depth = [0] * len(found)
    wrong = checks.inside_out(found, depth)
    if wrong and len(wrong) == len(found):
        turn = wrong
    else:
        turn = [k for k in wrong if depth[k] == 0]
    if turn:
        triangles = checks.turn(triangles, [r for k in turn for r in found[k].ranges])
    return triangles, len(turn), len(wrong) - len(turn), unsure, unjudged


# Tessellation and scene checks the export judges again on the mesh it writes (_object).
REJUDGED = ("solids_not_closed", "shells_inside_out")


def _object(name, file_key, configuration, source, positions, triangles, chord_m, warnings) -> PrintObject:
    closed = oriented_closed(triangles, len(positions) // 3)
    positions, triangles, closed = _without_coincident(positions, triangles, closed)
    warnings = [w for w in warnings if w.code not in REJUDGED]
    if not closed:
        warnings.append(
            ReaderWarning(
                "not_closed",
                "the object is not closed: some edge of its triangles is not used twice, once each way",
            )
        )
    else:
        triangles, turned, left, unsure, unjudged = _facing(positions, triangles, chord_m)
        if unjudged:
            from .tessellate.checks import MAX_SHELLS

            warnings.append(
                ReaderWarning(
                    "shells_not_judged",
                    f"the object has {unjudged:,} closed shells, more than the {MAX_SHELLS} whose nesting is "
                    "worked out, so which way they face was not checked",
                )
            )
        if turned:
            warnings.append(
                ReaderWarning(
                    "shell_reoriented",
                    f"{turned} closed shells of the object faced inward, inside out, and were turned round",
                )
            )
        if left or unsure:
            found = []
            if left:
                found.append(
                    f"{left} closed shells face outward inside another shell: a body inside a body, or a "
                    "void turned inside out"
                )
            if unsure:
                found.append(
                    f"{unsure} closed shells touch another so that which lies inside which cannot be told, "
                    "so which way they should face was not checked"
                )
            found.append("they are left as they are")
            warnings.append(ReaderWarning("shells_inside_out", "; ".join(found)))
    if source == "display_mesh":
        name = f"{name} (display mesh)"
    return PrintObject(
        name, file_key, configuration, source, positions, triangles, closed, chord_m, tuple(warnings)
    )


def _part_model(doc, configuration, name, opts, t0) -> PrintModel:
    from .tessellate import tessellate_document

    t = tessellate_document(doc, configuration, include_hidden=False, **opts)
    warnings = [w for w in t.warnings if w.code not in REJUDGED]
    asked = t.configuration
    stored = not any(w.code == "no_stored_bodies" for w in t.warnings)
    if not stored and asked is not None and asked != doc.active_configuration:
        # As display_geometry's brep source does: the active configuration's bodies,
        # with a warning, rather than none.
        other = tessellate_document(doc, None, include_hidden=False, **opts)
        if not any(w.code == "no_stored_bodies" for w in other.warnings):
            warnings = [
                *(w for w in warnings if w.code != "no_stored_bodies"),
                ReaderWarning(
                    "mesh_configuration_differs",
                    f"the part stores no bodies of configuration {asked!r}; those of its active "
                    f"configuration {other.configuration!r} are exported, whose geometry may differ",
                ),
                *(w for w in other.warnings if w.code not in REJUDGED),
            ]
            t, stored = other, True
    for limit in ("max_triangles", "max_seconds", "max_faces"):
        if limit in t.truncated:
            raise SldLimitError(
                f"tessellating the part stopped at its {limit} limit; a coarser chord tolerance needs fewer "
                "triangles and less time",
                detail={"limit": limit},
            )
    if t.mesh.n_triangles:
        positions, triangles = t.welded()
        obj = _object(
            name, None, t.configuration, "bodies", positions, triangles, t.chord_m, _brep_warnings(t)
        )
        configuration = t.configuration
    else:
        hidden = [w for w in t.warnings if w.code == "bodies_left_out"]
        if stored and t.counts["bodies"] == 0 and t.counts["bodies_left_out"] == 0 and hidden:
            # As the STEP export: SOLIDWORKS prints nothing of a part whose bodies are all hidden.
            raise NothingToExportError(
                "nothing to export: every body of the part is hidden in SOLIDWORKS, which leaves hidden "
                "bodies out of what it exports",
                detail={"rule": "hidden"},
            )
        if stored and t.counts["bodies"] == 0:
            why = "the part's bodies are surfaces or wires, not solids"
        elif stored:
            why = "none of the part's solid faces could be tessellated"
        else:
            why = "the part stores no B-rep bodies"
        mesh = doc.mesh()
        if mesh is None or mesh.n_triangles == 0:
            raise NothingToExportError(f"nothing to export: {why}, and it stores no display mesh either")
        if mesh.n_triangles > opts["max_triangles"]:  # as the bodies are bounded, before welding
            raise SldLimitError(
                f"the part's display mesh has {mesh.n_triangles:,} triangles, more than the "
                f"{opts['max_triangles']:,} allowed",
                detail={"limit": "max_triangles"},
            )
        positions, triangles = weld(mesh)
        if not triangles:
            raise NothingToExportError(f"nothing to export: {why}, and its display mesh has no area")
        configuration = doc.active_configuration
        if asked is not None and asked != configuration:
            warnings.append(
                ReaderWarning(
                    "mesh_configuration_differs",
                    f"the display mesh shows configuration {configuration!r}, the one active when the part "
                    f"was saved, not {asked!r}",
                )
            )
        obj = _object(
            name, None, configuration, "display_mesh", positions, triangles, None, [_fallback_warning(why)]
        )
        if stored and t.counts["bodies"] == 0 and not obj.closed:
            # Its bodies are surfaces or wires and their mesh is open: nothing a slicer can print
            # as a solid, as a model file of open surfaces only is refused.
            raise NothingToExportError(
                "nothing to export: the part holds only open surfaces or wires, no solid body, and only a "
                "solid can be printed",
                detail={"rule": "no_solid"},
            )
    counts = {
        "objects": 1,
        "items": 1,
        "vertices": obj.n_vertices,
        "triangles": obj.n_triangles,
    }
    return PrintModel(
        name=name,
        doc_type="part",
        configuration=configuration,
        objects=(obj,),
        items=(PrintItem(0, None, IDENTITY),),
        chord_m=opts.get("chord_m"),
        counts=counts,
        warnings=tuple(warnings),
        seconds=time.perf_counter() - t0,
    )


def _box(obj: PrintObject) -> tuple[tuple[float, ...], tuple[float, ...]]:
    p = obj.positions
    return (min(p[0::3]), min(p[1::3]), min(p[2::3])), (max(p[0::3]), max(p[1::3]), max(p[2::3]))


def _in_range(box, placement: Placement) -> bool:
    """Whether an object of this box, placed, lies within :data:`MAX_COORDINATE_MM` of
    the origin (the box's corners, placed, are checked)."""
    lo, hi = box
    for x in (lo[0], hi[0]):
        for y in (lo[1], hi[1]):
            for z in (lo[2], hi[2]):
                if any(abs(v) * 1000.0 > MAX_COORDINATE_MM for v in placement.apply((x, y, z))):
                    return False
    return True


def _assembly_model(doc, configuration, name, opts, geometry_options, t0) -> PrintModel:
    from .geometry import SkippedInstance, display_geometry

    brep = {k: v for k, v in opts.items() if k in ("chord_m", "angle_deg", "chord_fraction", "max_chord_m")}
    brep.update(body_types=opts["body_types"], max_seconds=opts["max_seconds"], include_hidden=False)
    g = display_geometry(
        doc,
        configuration,
        sources=SOURCES,
        max_triangles=opts["max_triangles"],
        max_triangles_drawn=opts["max_triangles"],
        max_brep_seconds=opts["max_seconds"],
        brep_options=brep,
        keep_welded=True,
        **geometry_options,
    )
    files = g.files
    keys = list(dict.fromkeys(inst.mesh for inst in g.instances))
    # Names from the component files, told apart by configuration, then by number.
    base = {}
    for key in keys:
        src = g.meshes[key]
        f = files.get(src.file or "")
        base[key] = _stem(f.file_name if f is not None else None, "component")
    per_name = Counter(base.values())
    names: dict[str, str] = {}
    taken: Counter = Counter()
    for key in keys:
        n = base[key]
        cfg = g.meshes[key].configuration
        if per_name[n] > 1 and cfg:
            n = f"{n} ({cfg})"
        taken[n] += 1
        names[key] = n if taken[n] == 1 else f"{n} ({taken[n]})"
    objects: list[PrintObject] = []
    index: dict[str, int] = {}
    for key in keys:
        src = g.meshes[key]
        warnings = list(src.warnings)
        if src.kind == "brep" and src.welded is not None:
            positions, triangles = src.welded
            # The export's own codes: not_closed comes from the check below.
            warnings = [
                ReaderWarning("faces_left_out", w.message, w.stream)
                if w.code in ("brep_faces_skipped", "brep_bodies_skipped")
                else w
                for w in warnings
                if w.code != "brep_not_closed"
            ]
            obj = _object(
                names[key], src.file, src.configuration, "bodies", positions, triangles, src.chord_m, warnings
            )
        else:
            positions, triangles = weld(src.mesh)
            where = (
                "its part's bodies could not be exported (its file was not found, stores no solid body, "
                "or a limit was reached)"
            )
            obj = _object(
                names[key],
                src.file,
                src.configuration,
                "display_mesh",
                positions,
                triangles,
                None,
                [*warnings, _fallback_warning(where)],
            )
        index[key] = len(objects)
        objects.append(obj)
    items: list[PrintItem] = []
    # Only solids are asked for: a part whose bodies are all of other types holds surfaces or
    # wires, and says so rather than what the stored-mesh sources after it said.
    skipped = [
        replace(s, reason=SURFACES_ONLY, message=SURFACES_ONLY_TEXT) if s.reason == "bodies_not_asked" else s
        for s in g.skipped
    ]
    boxes = {i: _box(o) for i, o in enumerate(objects) if o.triangles}  # measured once an object
    for inst in g.instances:
        obj = objects[index[inst.mesh]]
        if not obj.triangles or not _in_range(boxes[index[inst.mesh]], inst.placement):
            skipped.append(
                SkippedInstance(
                    inst.id,
                    inst.name,
                    inst.file,
                    "out_of_range" if obj.triangles else "no_mesh",
                    "it would lie more than 1,000 km from the origin"
                    if obj.triangles
                    else "its saved display mesh has no triangle with any area",
                    None,
                    inst.placement,
                )
            )
            continue
        items.append(PrintItem(index[inst.mesh], inst.id, inst.placement))
    used = sorted({it.object for it in items})
    if not items:
        why = Counter(s.reason for s in skipped)
        detail = ", ".join(f"{r} {n}" for r, n in sorted(why.items())) or "it has no part instance shown"
        raise NothingToExportError(
            f"nothing to export: no instance of the assembly could be placed ({detail})"
        )
    if len(used) != len(objects):  # an object no item places is not written
        remap = {old: new for new, old in enumerate(used)}
        objects = [objects[i] for i in used]
        items = [PrintItem(remap[it.object], it.instance, it.placement) for it in items]
    warnings = list(g.warnings)
    if skipped:
        why = Counter(s.reason for s in skipped)
        warnings.append(
            ReaderWarning(
                "instances_left_out",
                f"{len(skipped)} instances shown in this configuration are left out: "
                + ", ".join(f"{r} {n}" for r, n in sorted(why.items())),
            )
        )
    gc = g.counts
    counts = {
        "objects": len(objects),
        "items": len(items),
        "vertices": sum(o.n_vertices for o in objects),
        "triangles": sum(objects[it.object].n_triangles for it in items),
        "parts": int(gc["parts"]),
        "placed": len(items),
        "skipped": len(skipped),
        "suppressed": int(gc["suppressed"]),
        "hidden": int(gc["hidden"]),
    }
    return PrintModel(
        name=name,
        doc_type="assembly",
        configuration=g.configuration,
        objects=tuple(objects),
        items=tuple(items),
        chord_m=opts.get("chord_m"),
        counts=counts,
        skipped=tuple(skipped[:MAX_LISTED]),
        warnings=tuple(warnings),
        seconds=time.perf_counter() - t0,
    )


@dataclass(frozen=True)
class _ModelSkip:
    """An item of a model file's scene that the export leaves out, shaped as geometry's
    ``SkippedInstance`` is for :func:`~solidseas.model.build_export_result`."""

    id: str
    name: str
    file: str | None
    reason: str
    message: str


def _model_file_model(doc, configuration, name, opts, t0) -> PrintModel:
    """A model file (:class:`~solidseas.formats.ModelDocument`) as a print model: its
    scene's objects welded and checked, placed by its items."""
    from .errors import ConfigurationNotFoundError, SolidSeasError
    from .formats.base import SkippedItem

    if configuration is not None and configuration != doc.active_configuration:
        raise ConfigurationNotFoundError(f"the file has no configuration named {configuration!r}")
    scene = doc.scene(
        prefer="bodies",
        max_triangles=opts["max_triangles"],
        chord_m=opts.get("chord_m"),
        chord_fraction=opts.get("chord_fraction"),
        max_chord_m=opts.get("max_chord_m"),
        angle_deg=opts["angle_deg"],
        max_seconds=opts["max_seconds"],
        body_types=opts["body_types"],
    )
    if "max_triangles" in scene.truncated:
        raise SldLimitError(
            f"the model has more than the {opts['max_triangles']:,} triangles allowed",
            detail={"limit": "max_triangles"},
        )
    names: dict[str, str] | None = None

    def named(instance: str | None, fallback: str) -> str:
        nonlocal names
        if names is None:  # only for an item left out: the tree can cost a pass over the file
            try:
                names = {n.id: n.name for n in doc.tree().nodes if n.name}
            except SolidSeasError:
                names = {}
        return names.get(instance or "", fallback)

    used = sorted({it.object for it in scene.items})
    objects: list[PrintObject] = []
    index: dict[int, int] = {}
    taken: Counter = Counter()
    for i in used:
        src = scene.objects[i]
        positions, triangles = weld(src)
        label = src.name or name
        taken[label] += 1
        if taken[label] > 1:
            label = f"{label} ({taken[label]})"
        warnings = list(src.warnings)
        if src.source == "display_mesh":
            warnings.append(
                ReaderWarning(
                    "display_mesh_fallback",
                    "the file's B-rep could not be exported, so the display mesh it stores is used instead; "
                    "it may not be closed, and a slicer may have to repair it",
                )
            )
        chord = opts.get("chord_m") if src.source == "bodies" else None
        index[i] = len(objects)
        objects.append(_object(label, src.node, None, src.source, positions, triangles, chord, warnings))
    skipped: list[Any] = []
    for s in scene.skipped:
        if isinstance(s, SkippedItem):
            skipped.append(
                _ModelSkip(s.instance or "", named(s.instance, s.instance or ""), None, s.reason, s.message)
            )
    items: list[PrintItem] = []
    boxes = {k: _box(o) for k, o in enumerate(objects) if o.triangles}
    for it in scene.items:
        k = index[it.object]
        obj = objects[k]
        if not obj.triangles:
            why = "its mesh has no triangle with any area"
            skipped.append(_ModelSkip(it.instance or "", named(it.instance, obj.name), None, "no_mesh", why))
            continue
        if not _in_range(boxes[k], it.placement):
            why = "it would lie more than 1,000 km from the origin"
            skipped.append(
                _ModelSkip(it.instance or "", named(it.instance, obj.name), None, "out_of_range", why)
            )
            continue
        items.append(PrintItem(k, it.instance, it.placement))
    placed = sum(objects[it.object].n_triangles for it in items)
    if placed > opts["max_triangles"]:  # one small mesh placed many times over
        raise SldLimitError(
            f"the model places {placed:,} triangles, more than the {opts['max_triangles']:,} allowed",
            detail={"limit": "max_triangles"},
        )
    if not items:
        if not skipped and any(w.code == "bodies_left_out" for w in scene.warnings):
            raise NothingToExportError(
                "nothing to export: the file holds only open surfaces or wires, no solid body, and only "
                "a solid can be printed",
                detail={"rule": "no_solid"},
            )
        why = Counter(s.reason for s in skipped)
        detail = ", ".join(f"{r} {n}" for r, n in sorted(why.items())) or "it holds no triangles"
        raise NothingToExportError(
            f"nothing to export: the file holds no geometry that can be placed ({detail})"
        )
    kept = sorted({it.object for it in items})
    if len(kept) != len(objects):
        remap = {old: new for new, old in enumerate(kept)}
        objects = [objects[k] for k in kept]
        items = [PrintItem(remap[it.object], it.instance, it.placement) for it in items]
    warnings = [*doc.warnings, *(w for w in scene.warnings if w.code not in REJUDGED)]
    faces = [s for s in scene.skipped if not isinstance(s, SkippedItem)]
    if faces:
        why = Counter(str(getattr(s, "reason", "")) for s in faces)
        reasons = ", ".join(f"{k} {v}" for k, v in sorted(why.items()) if k)
        said = f" ({reasons})" if reasons else ""
        warnings.append(
            ReaderWarning(
                "faces_left_out",
                f"{len(faces)} faces could not be tessellated{said}: the solid has holes there, which a "
                "slicer may or may not repair",
            )
        )
    if skipped:
        why = Counter(s.reason for s in skipped)
        warnings.append(
            ReaderWarning(
                "instances_left_out",
                f"{len(skipped)} items of the model are left out: "
                + ", ".join(f"{r} {n}" for r, n in sorted(why.items())),
            )
        )
    counts = {
        "objects": len(objects),
        "items": len(items),
        "vertices": sum(o.n_vertices for o in objects),
        "triangles": sum(objects[it.object].n_triangles for it in items),
    }
    if doc.doc_type == "assembly" or skipped:
        counts.update(placed=len(items), skipped=len(skipped))
    return PrintModel(
        name=name,
        doc_type=doc.doc_type or "part",
        configuration=doc.active_configuration,
        objects=tuple(objects),
        items=tuple(items),
        chord_m=opts.get("chord_m"),
        counts=counts,
        skipped=tuple(skipped[:MAX_LISTED]),
        warnings=tuple(warnings),
        seconds=time.perf_counter() - t0,
        source_format=doc.format,
    )


def print_model(
    doc,
    configuration: str | None = None,
    *,
    name: str | None = None,
    chord_m: float | None = None,
    angle_deg: float = DEFAULT_ANGLE_DEG,
    max_triangles: int = DEFAULT_MAX_TRIANGLES,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    roots=None,
    path_map=(),
    allow_outside_roots: bool = True,
    cache=None,
) -> PrintModel:
    """The part or the assembly configuration ``doc`` (None: the active one), ready to
    write as STL or 3MF. Provisional (``docs/API.md`` section 3.17).

    ``chord_m`` is the chord tolerance in metres (None: :data:`CHORD_FRACTION` of each
    part's box diagonal, at most :data:`MAX_CHORD_M`); ``angle_deg`` as for
    :mod:`solidseas.tessellate`. ``max_triangles`` bounds the triangles tessellated or
    read, and those placed (a model file placing one mesh many times over raises
    :class:`~solidseas.errors.SldLimitError` with ``detail["limit"]`` ``max_triangles``);
    ``max_seconds`` the time spent tessellating. ``name``
    names a part's object and the model (None: from the document's name). ``roots``,
    ``path_map``, ``allow_outside_roots`` and ``cache`` find an assembly's component
    files as :func:`~solidseas.geometry.display_geometry` does.

    ``doc`` may also be a model file (:class:`~solidseas.formats.ModelDocument`): its
    scene is read with its B-rep bodies preferred (for a mesh file, its own
    triangles), each object welded and checked, and placed by the scene's items;
    ``configuration`` must then be None or the file's active configuration.

    Raises :class:`~solidseas.errors.NothingToExportError` for a drawing, a part with
    neither solid bodies nor a display mesh, a model file holding only open surfaces
    or wires (``detail["rule"]`` ``no_solid``) and an assembly none of whose instances
    could be placed, :class:`~solidseas.errors.SldLimitError` when a limit stopped a
    part's tessellation, :class:`~solidseas.errors.ConfigurationNotFoundError` for an
    unknown configuration and :class:`~solidseas.errors.InvalidArgumentError` for a
    bad option."""
    t0 = time.perf_counter()
    if chord_m is not None:
        chord_m = _number(chord_m, "chord_m", 1e-7, 1e-2)
    angle_deg = _number(angle_deg, "angle_deg", 0.5, 90.0)
    max_triangles = _whole(max_triangles, "max_triangles", 1)
    max_seconds = _number(max_seconds, "max_seconds", 0.0, 1e6)
    if name is not None and not isinstance(name, str):
        raise InvalidArgumentError("name is a string", detail={"parameter": "name"})
    opts = _tess_options(chord_m, angle_deg, max_triangles, max_seconds)
    kind = doc.doc_type
    label = name or _stem(getattr(doc, "name", None), kind or "model")
    from .formats.base import ModelDocument

    if isinstance(doc, ModelDocument):
        return _model_file_model(doc, configuration, label, opts, t0)
    if kind == "part":
        return _part_model(doc, configuration, label, opts, t0)
    if kind == "assembly":
        geometry_options = {
            "roots": roots,
            "path_map": path_map,
            "allow_outside_roots": allow_outside_roots,
            "cache": cache,
        }
        return _assembly_model(doc, configuration, label, opts, geometry_options, t0)
    raise NothingToExportError(f"nothing to export: a {kind or 'document of unknown type'} has no 3D model")


# --------------------------------------------------------------------------- writing
class _Bounded:
    """A file object that refuses to grow past ``limit`` bytes."""

    def __init__(self, fh: BinaryIO, limit: int | None) -> None:
        self.fh, self.limit, self.end = fh, limit, 0

    def write(self, data) -> int:
        n = self.fh.write(data)
        try:
            self.end = max(self.end, self.fh.tell())
        except (OSError, AttributeError, ValueError):
            self.end += len(data)
        if self.limit is not None and self.end > self.limit:
            raise SldLimitError(
                f"the export would be larger than its {self.limit:,}-byte limit",
                detail={"limit": "max_bytes"},
            )
        return n

    def tell(self) -> int:
        return self.fh.tell()

    def seek(self, *args):
        return self.fh.seek(*args)

    def seekable(self) -> bool:
        return self.fh.seekable()

    def flush(self) -> None:
        self.fh.flush()


def _placed(obj: PrintObject, placement: Placement) -> tuple[array, bool]:
    """``obj``'s vertices placed, in millimetres (three float64 a vertex), and whether
    the placement mirrors."""
    p = obj.positions
    if placement is IDENTITY:
        return array("d", (v * 1000.0 for v in p)), False
    (r00, r01, r02), (r10, r11, r12), (r20, r21, r22) = placement.rotation
    tx, ty, tz = placement.translation_m
    out = array("d")
    for i in range(0, len(p), 3):
        x, y, z = p[i], p[i + 1], p[i + 2]
        out.extend(
            (
                (r00 * x + r01 * y + r02 * z + tx) * 1000.0,
                (r10 * x + r11 * y + r12 * z + ty) * 1000.0,
                (r20 * x + r21 * y + r22 * z + tz) * 1000.0,
            )
        )
    return out, _det(placement.rotation) < 0.0


def _written(obj: PrintObject, placement: Placement) -> tuple[array, array, array, bool]:
    """What a writer writes of ``obj`` placed: its vertices in millimetres (float64), the
    same rounded to float32, its triangles, and whether the placement mirrors (the
    writer turns each triangle). An object's own vertices never meet in float32 (see
    :func:`_object`); where placing it far from the origin, whose float32 steps are
    coarser, makes two corners of a triangle meet, they are merged in the same way."""
    mm, mirror = _placed(obj, placement)
    f32 = array("f", mm)
    tris = obj.triangles
    merged = _merged_coincident(f32, tris)
    if merged is not None:
        (mm2, f2), tris2 = _compacted([mm, f32], merged)
        if not obj.closed or oriented_closed(tris2, len(mm2) // 3):
            mm, f32, tris = mm2, f2, tris2
    return mm, f32, tris, mirror


def stl_size(model: PrintModel) -> int:
    """The size of the model's binary STL: 84 bytes and 50 a placed triangle. A file is
    smaller only where placing an item far from the origin made corners of a triangle
    meet in float32, and merging them left triangles out (:func:`write_stl` returns the
    size written)."""
    return 84 + 50 * model.counts["triangles"]


def _seekable(fh) -> bool:
    try:
        return bool(fh.seekable())
    except (AttributeError, OSError, ValueError):
        return False


def write_stl(model: PrintModel, fh: BinaryIO, *, max_bytes: int | None = DEFAULT_MAX_BYTES) -> int:
    """Write the model as binary STL to ``fh``: every item's triangles placed, in
    millimetres as float32, each with the unit normal of its float32 corners ((0, 0, 0)
    for a triangle with no area) and no triangle two of whose corners are one float32
    point. Returns the bytes written; raises ``SldLimitError`` before writing anything
    when the file could pass ``max_bytes``. Where triangles were left out the count in
    the header is put right at the end (``fh`` seekable), or found by a first pass."""
    count = model.counts["triangles"]
    size = stl_size(model)
    if count >= 1 << 32 or (max_bytes is not None and size > max_bytes):
        raise SldLimitError(
            f"the STL would be {size:,} bytes, over its limit", detail={"limit": "max_bytes", "value": size}
        )
    if not _seekable(fh):
        count = sum(len(_written(model.objects[it.object], it.placement)[2]) // 3 for it in model.items)
    fh.write(STL_HEADER)
    fh.write(struct.pack("<I", count))
    pack = _FACET.pack_into
    written = 0
    for it in model.items:
        _mm, f, t, mirror = _written(model.objects[it.object], it.placement)
        buf = bytearray(50 * min(_CHUNK, len(t) // 3 or 1))
        off = 0
        for k in range(0, len(t), 3):
            i, j, m = 3 * t[k], 3 * t[k + 1], 3 * t[k + 2]
            if mirror:
                j, m = m, j
            ax, ay, az = f[i], f[i + 1], f[i + 2]
            bx, by, bz = f[j], f[j + 1], f[j + 2]
            cx, cy, cz = f[m], f[m + 1], f[m + 2]
            ux, uy, uz = bx - ax, by - ay, bz - az
            wx, wy, wz = cx - ax, cy - ay, cz - az
            nx, ny, nz = uy * wz - uz * wy, uz * wx - ux * wz, ux * wy - uy * wx
            ln = math.sqrt(nx * nx + ny * ny + nz * nz)
            if ln > 0.0:
                nx, ny, nz = nx / ln, ny / ln, nz / ln
            else:
                nx = ny = nz = 0.0
            pack(buf, off, nx, ny, nz, ax, ay, az, bx, by, bz, cx, cy, cz, 0)
            off += 50
            if off == len(buf):
                fh.write(buf)
                off = 0
        if off:
            fh.write(memoryview(buf)[:off])
        written += len(t) // 3
    if written != count:  # seekable only: a first pass counts exactly
        fh.seek(80)
        fh.write(struct.pack("<I", written))
        fh.seek(0, os.SEEK_END)
    return 84 + 50 * written


def _num(v: float) -> str:
    """A coordinate as the 3MF's ST_Number: the shortest text that reads back as the
    same float64 (nine digits made corners a hair apart one point, and slivers flat)."""
    text = repr(v)
    if text.endswith(".0"):
        text = text[:-2]
    return "0" if text == "-0" else text


def _xml_text(text: str) -> str:
    """``text`` for an XML attribute: characters XML 1.0 does not allow are dropped,
    and the markup characters escaped."""
    kept = "".join(
        ch
        for ch in text
        if ch in "\t\n\r"
        or ("\u0020" <= ch <= "\ud7ff")
        or ("\ue000" <= ch <= "\ufffd")
        or ch >= "\U00010000"
    )
    return (
        kept.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("\t", "&#9;")
        .replace("\n", "&#10;")
        .replace("\r", "&#13;")
    )


def _transform(placement: Placement) -> str:
    """A placement as the 3MF transform attribute: the 3 x 4 matrix a row vector is
    multiplied by (``m00 m01 m02 m10 ... m32``), the translation in millimetres."""
    r, t = placement.rotation, placement.translation_m
    cells = [r[j][i] for i in range(3) for j in range(3)] + [t[0] * 1000.0, t[1] * 1000.0, t[2] * 1000.0]
    return " ".join(_num(c) for c in cells)


def _mesh_xml(pieces) -> Any:
    """The ``<mesh>`` element of one object, in chunks: ``pieces`` are (vertices in mm,
    three float64 a vertex; triangles; mirror) laid one after another."""
    yield "<mesh><vertices>"
    for mm, _t, _m in pieces:
        n = len(mm)
        for s in range(0, n, 3 * _CHUNK):
            yield "".join(
                f'<vertex x="{_num(mm[i])}" y="{_num(mm[i + 1])}" z="{_num(mm[i + 2])}"/>'
                for i in range(s, min(n, s + 3 * _CHUNK), 3)
            )
    yield "</vertices><triangles>"
    base = 0
    for mm, t, mirror in pieces:
        n = len(t)
        for s in range(0, n, 3 * _CHUNK):
            part = []
            for k in range(s, min(n, s + 3 * _CHUNK), 3):
                a, b, c = t[k] + base, t[k + 1] + base, t[k + 2] + base
                if mirror:
                    b, c = c, b
                part.append(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>')
            yield "".join(part)
        base += len(mm) // 3
    yield "</triangles></mesh>"


def _piece(obj: PrintObject, placement: Placement) -> tuple[array, array, bool]:
    mm, _f32, tris, mirror = _written(obj, placement)
    return mm, tris, mirror


def _model_xml(model: PrintModel, merge: bool):
    yield (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<model unit="millimeter" xml:lang="en-US" xmlns="{CORE_NS}">'
        f'<metadata name="Application">SolidSeas {__version__}</metadata>'
        f'<metadata name="Title">{_xml_text(model.name)}</metadata>'
        "<resources>"
    )
    build: list[tuple[int, str | None]] = []
    if merge:
        pieces = [_piece(model.objects[it.object], it.placement) for it in model.items]
        yield f'<object id="1" type="model" name="{_xml_text(model.name)}">'
        yield from _mesh_xml(pieces)
        yield "</object>"
        build.append((1, None))
    else:
        next_id = len(model.objects) + 1
        for i, obj in enumerate(model.objects):
            yield f'<object id="{i + 1}" type="model" name="{_xml_text(obj.name)}">'
            yield from _mesh_xml([_piece(obj, IDENTITY)])
            yield "</object>"
        for it in model.items:
            if _det(it.placement.rotation) < 0.0:
                # A mirroring placement is written out placed, with its triangles turned, rather
                # than left to each slicer's reading of a transform that turns the solid inside out.
                obj = model.objects[it.object]
                yield f'<object id="{next_id}" type="model" name="{_xml_text(obj.name)}">'
                yield from _mesh_xml([_piece(obj, it.placement)])
                yield "</object>"
                build.append((next_id, None))
                next_id += 1
            else:
                build.append((it.object + 1, _transform(it.placement)))
    yield "</resources><build>"
    for oid, transform in build:
        if transform is None:
            yield f'<item objectid="{oid}"/>'
        else:
            yield f'<item objectid="{oid}" transform="{transform}"/>'
    yield "</build></model>\n"


def write_3mf(
    model: PrintModel, fh: BinaryIO, *, merge: bool = False, max_bytes: int | None = DEFAULT_MAX_BYTES
) -> int:
    """Write the model as a 3MF package to ``fh`` (seekable or not): one object per
    :class:`PrintObject` and a build item per :class:`PrintItem`, with its transform,
    or with ``merge`` one object holding every placed triangle. Returns the bytes
    written; raises ``SldLimitError`` once the package passes ``max_bytes``."""
    out = _Bounded(fh, max_bytes)
    triangles = sum(o.n_triangles for o in model.objects) if not merge else model.counts["triangles"]
    big = 40 * model.counts["vertices"] + 45 * triangles > (1 << 31) - (1 << 26)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as z:  # type: ignore[arg-type]
        for part, text in (("[Content_Types].xml", CONTENT_TYPES_XML), ("_rels/.rels", RELS_XML)):
            info = zipfile.ZipInfo(part, _ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, text.encode("utf-8"))
        info = zipfile.ZipInfo(MODEL_PART, _ZIP_TIME)
        info.compress_type = zipfile.ZIP_DEFLATED
        with z.open(info, "w", force_zip64=big) as m:
            pending: list[str] = []
            size = 0
            for chunk in _model_xml(model, merge):
                pending.append(chunk)
                size += len(chunk)
                if size >= 1 << 20:
                    m.write("".join(pending).encode("utf-8"))
                    pending, size = [], 0
            if pending:
                m.write("".join(pending).encode("utf-8"))
    return out.end


def export_bytes(
    model: PrintModel, format: str = "3mf", *, merge: bool = False, max_bytes: int | None = DEFAULT_MAX_BYTES
) -> bytes:
    """The model as STL or 3MF bytes, in memory: for small models and tests."""
    import io

    fmt = _format(format)
    buf = io.BytesIO()
    if fmt == "stl":
        write_stl(model, buf, max_bytes=max_bytes)
    else:
        write_3mf(model, buf, merge=merge, max_bytes=max_bytes)
    return buf.getvalue()


def _link(path: str) -> bool:
    """A symbolic link, a junction or another name-surrogate reparse point: writing there
    would write somewhere else."""
    from .walk import reparse_link

    try:
        st = os.lstat(path)
    except OSError:
        return False
    attrs = int(getattr(st, "st_file_attributes", 0) or 0)
    tag = int(getattr(st, "st_reparse_tag", 0) or 0)
    return reparse_link(attrs, tag) is not None or os.path.islink(path)


def _refuse_special(target: str) -> None:
    """Refuse, on Windows, a path that is not a plain file name: a device (Windows reads
    ``nul .3mf`` in any folder as the NUL device, and ``abspath`` then gives
    ``\\\\.\\nul``), the device or extended-length namespace, or an alternate data stream
    of a file (``x.3mf:more``), which would write into a file that is there. The CLI's
    output paths follow the same rules."""
    if os.name != "nt":
        return
    if target.replace("/", "\\").startswith(("\\\\.\\", "\\\\?\\")):
        raise OutputRefusedError(
            f"refusing to write {target}: it names a device or the extended-length namespace",
            detail={"rule": "device_path"},
        )
    if ":" in os.path.splitdrive(target)[1]:
        raise OutputRefusedError(
            f"refusing to write {target}: it names an alternate data stream",
            detail={"rule": "alternate_stream"},
        )
    # Older Windows turns a reserved name in any folder into the device during abspath,
    # which the check above catches; newer Windows leaves the path alone but may still
    # open the device. Refuse the reserved names themselves, so both behave the same.
    stem = os.path.basename(target).split(".", 1)[0].rstrip(" ").upper()
    if stem in _DEVICE_NAMES:
        raise OutputRefusedError(
            f"refusing to write {target}: Windows reserves the name {stem} for a device",
            detail={"rule": "device_path"},
        )


_DEVICE_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"]
    + [f"{p}{n}" for p in ("COM", "LPT") for n in (*"123456789", "\u00b9", "\u00b2", "\u00b3")]
)


def _create(path: str):
    """``path`` created new and opened for writing; never a file that is there, never
    through a link at its end."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    for extra in ("O_BINARY", "O_NOFOLLOW", "O_CLOEXEC", "O_NOINHERIT"):
        flags |= getattr(os, extra, 0)
    fd = os.open(path, flags, 0o644)
    return os.fdopen(fd, "wb")


def write_export(
    model: PrintModel,
    path: str | os.PathLike,
    format: str = "3mf",
    *,
    merge: bool = False,
    overwrite: bool = False,
    max_bytes: int | None = DEFAULT_MAX_BYTES,
) -> ExportResult:
    """Write ``model`` to ``path`` as STL or 3MF. The file is created new: an existing
    one raises :class:`~solidseas.errors.OutputRefusedError` (rule ``exists``) unless
    ``overwrite``, and then the export is written to a new file beside it and renamed
    over it. A link at ``path`` is refused either way (rule ``link``), and a write that
    fails removes the file it created."""
    fmt = _format(format)
    if max_bytes is not None:
        max_bytes = _whole(max_bytes, "max_bytes", 1)

    def write(fh) -> int:
        if fmt == "stl":
            return write_stl(model, fh, max_bytes=max_bytes)
        return write_3mf(model, fh, merge=merge, max_bytes=max_bytes)

    target, size = write_new(path, write, overwrite=overwrite)
    return ExportResult(target, fmt, size, merge or fmt == "stl", model)


# Documents and templates of SOLIDWORKS: the same list the command line protects.
_SOLIDWORKS_FILES = (".sldprt", ".sldasm", ".slddrw", ".prtdot", ".asmdot", ".drwdot", ".sldlfp", ".sldblk")


def write_new(path: str | os.PathLike, write, *, overwrite: bool = False) -> tuple[str, int]:
    """Create the file ``path`` new and fill it with ``write(fh)``, which returns the
    size written: the rules of :func:`write_export` (and of the STEP export). Returns
    the absolute path and the size."""
    target = os.path.abspath(os.fspath(path))
    _refuse_special(target)
    if target.lower().endswith(_SOLIDWORKS_FILES):
        # The library never writes a SOLIDWORKS file, whatever the caller asks, so an
        # overwrite cannot replace a source document (AGENTS.md, the read-only rule).
        raise OutputRefusedError(
            f"refusing to write a SOLIDWORKS file: {target}", detail={"rule": "solidworks_file"}
        )
    if _link(target):
        raise OutputRefusedError(
            f"refusing to write {target}: it is a link, and writing would follow it", detail={"rule": "link"}
        )
    if os.path.isdir(target):
        raise OutputRefusedError(f"refusing to write {target}: it is a folder", detail={"rule": "exists"})
    if overwrite and os.path.lexists(target):
        folder, base = os.path.split(target)
        temp = os.path.join(folder, f".{base}.{os.urandom(4).hex()}.part")
        write_to = temp
    else:
        write_to = temp = target
    try:
        fh = _create(write_to)
    except FileExistsError:
        raise OutputRefusedError(
            f"{target} already exists; it is not replaced unless asked", detail={"rule": "exists"}
        ) from None
    try:
        with fh:
            size = write(fh)
        if temp != target:
            os.replace(temp, target)
    except BaseException:
        try:
            os.remove(write_to)
        except OSError:
            pass
        raise
    return target, size


def export_document(
    doc,
    path: str | os.PathLike,
    format: str = "3mf",
    *,
    merge: bool = False,
    overwrite: bool = False,
    max_bytes: int | None = DEFAULT_MAX_BYTES,
    **options: Any,
) -> "ExportResult | StepResult":
    """:func:`print_model` of ``doc`` with ``options``, written by :func:`write_export`;
    for ``format="step"``, :func:`solidseas.step.step_model` with ``options``, written by
    :func:`solidseas.step.write_step` (``merge`` does not apply), which returns a
    :class:`solidseas.step.StepResult`. ``format`` is one of :data:`EXPORT_FORMATS`."""
    if not isinstance(format, str) or format.lower() not in EXPORT_FORMATS:
        raise InvalidArgumentError(
            f"format is one of {', '.join(EXPORT_FORMATS)}",
            detail={"parameter": "format", "value": str(format)[:16]},
        )
    if format.lower() == "step":
        from .step import step_model, write_step

        if merge:
            raise InvalidArgumentError(
                "merge is for 3MF; a STEP file holds products", detail={"parameter": "merge"}
            )
        return write_step(step_model(doc, **options), path, overwrite=overwrite, max_bytes=max_bytes)
    fmt = _format(format)
    return write_export(
        print_model(doc, **options), path, fmt, merge=merge, overwrite=overwrite, max_bytes=max_bytes
    )


__all__ = [
    "CHORD_FRACTION",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_SECONDS",
    "DEFAULT_MAX_TRIANGLES",
    "EXPORT_FORMATS",
    "EXTENSIONS",
    "FORMATS",
    "MAX_CHORD_M",
    "MIME_TYPES",
    "SOURCES",
    "ExportResult",
    "PrintItem",
    "PrintModel",
    "PrintObject",
    "export_bytes",
    "export_document",
    "mesh_measures",
    "oriented_closed",
    "print_model",
    "stl_size",
    "weld",
    "write_3mf",
    "write_export",
    "write_new",
    "write_stl",
]
