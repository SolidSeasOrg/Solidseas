"""Faceted and tessellated geometry of a STEP file, as meshes (provisional).

* A ``FACETED_BREP`` (ISO 10303-42) is a closed shell of planar faces bounded by
  ``POLY_LOOP``s. Each face's polygon, holes included, is projected onto the plane
  of its outer loop (its Newell normal) and triangulated with the tessellator's
  earcut (:func:`solidseas.tessellate.triangulate.earcut`, concave polygons
  included), keeping the loop's direction, so the triangles face the way the face
  does. Faces share a vertex wherever their loops name the same point.
* AP242's tessellated geometry (ISO 10303-42 edition 4): ``TRIANGULATED_FACE``,
  ``COMPLEX_TRIANGULATED_FACE`` (strips and fans), ``TRIANGULATED_SURFACE_SET``,
  ``COMPLEX_TRIANGULATED_SURFACE_SET``, grouped by ``TESSELLATED_SHELL`` and
  ``TESSELLATED_SOLID``, over a ``COORDINATES_LIST``. Indices count from 1; when a
  face has a ``pnindex``, its indices go through it to the coordinates. Strips
  alternate their winding as the standard says; fans turn about their first point.

Every coordinate is in the representation's length unit: the mesh builder scales
it to metres. Every index is checked by the mesh builder, which drops what names a
point the list does not hold.
"""

import math
from typing import Any

from ..base import MeshBuilder
from .builder import perpendicular
from .geometry import Geometry, Mapper, Unsupported, _list, _num
from .part21 import Part21, Ref, as_bool

TESSELLATED_FACES = (
    "TRIANGULATED_FACE",
    "COMPLEX_TRIANGULATED_FACE",
    "TRIANGULATED_SURFACE_SET",
    "COMPLEX_TRIANGULATED_SURFACE_SET",
)
MAX_GROUP_DEPTH = 8


class _Points:
    """Mesh vertices keyed by what they come from, so faces share them."""

    __slots__ = ("mb", "index", "g")

    def __init__(self, mb: MeshBuilder, g: Geometry) -> None:
        self.mb, self.g = mb, g
        self.index: dict[Any, int] = {}

    def point(self, ref: Any) -> tuple[int, tuple[float, float, float]]:
        if not isinstance(ref, Ref):
            raise Unsupported("bad_reference", "POLY_LOOP", "a polygon point is not a reference")
        got = self.index.get(int(ref))
        if got is None:
            q = self.g.point(ref, 1.0)
            got = self.index[int(ref)] = (self.mb.add_vertices(q), q)
        return got


def faceted(p21: Part21, mapper: Mapper, rid: int, mb: MeshBuilder, clock: Any) -> tuple[int, list]:
    """Triangles of a faceted B-rep into ``mb``: ``(faces, skipped)``, skipped as
    ``(face id, entity, reason, detail)``."""
    g = Geometry(p21)
    rec = g.rec(Ref(rid), "FACETED_BREP")
    prm = rec.params
    outer = prm[1] if len(prm) >= 2 else None
    pts = _Points(mb, g)
    faces = 0
    skipped: list = []
    try:
        faces_list = mapper.faces_of(outer, False)
    except Unsupported as exc:
        return 1, [(-1, exc.entity, exc.reason, exc.detail[:200])]
    for face, flip in faces_list:
        faces += 1
        try:
            _facet(g, pts, face, flip, clock, 0)
        except Unsupported as exc:
            skipped.append((face, exc.entity, exc.reason, exc.detail[:200]))
    return faces, skipped


def _facet(g: Geometry, pts: _Points, rid: int, flip: bool, clock: Any, depth: int) -> None:
    rec = g.rec(Ref(rid))
    if rec.has("ORIENTED_FACE"):
        p = rec.params
        if depth > 4 or len(p) < 4:
            raise Unsupported("bad_reference", "ORIENTED_FACE")
        _facet(g, pts, int(p[2]), flip ^ (as_bool(p[3]) is False), clock, depth + 1)
        return
    p = rec.params
    if rec.complex or len(p) < 2:
        raise Unsupported("bad_reference", rec.types[0], "a face without bounds")
    rings: list[list[tuple[int, tuple[float, float, float]]]] = []
    outer_at = 0
    for bound in _list(p[1], "a face's bounds"):
        brec = g.rec(bound, "FACE_BOUND", "FACE_OUTER_BOUND")
        bp = brec.params
        if len(bp) < 3:
            raise Unsupported("bad_reference", brec.types[0])
        loop = g.rec(bp[1])
        if not loop.has("POLY_LOOP"):
            raise Unsupported(
                "unsupported_curve", loop.types[0], "a faceted face bounded by other than a polygon"
            )
        ring = [pts.point(q) for q in _list(loop.params[1] if len(loop.params) >= 2 else None, "a polygon")]
        if len(ring) > 1 and ring[0][0] == ring[-1][0]:
            ring.pop()
        forward = (as_bool(bp[2]) is not False) ^ flip
        if not forward:
            ring.reverse()
        if brec.has("FACE_OUTER_BOUND"):
            outer_at = len(rings)
        rings.append(ring)
    if not rings:
        raise Unsupported("degenerate", rec.types[0], "a face with no polygon")
    if outer_at:
        rings.insert(0, rings.pop(outer_at))
    elif len(rings) > 1:  # no outer bound named: the largest polygon is the outer one
        rings.sort(key=lambda r: -_area(r))
    triangles(pts.mb, rings, clock)


def _newell(ring) -> tuple[float, float, float]:
    nx = ny = nz = 0.0
    n = len(ring)
    for k in range(n):
        (_i, a), (_j, b) = ring[k], ring[(k + 1) % n]
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    return nx, ny, nz


def _area(ring) -> float:
    nx, ny, nz = _newell(ring)
    return math.sqrt(nx * nx + ny * ny + nz * nz)


def triangles(mb: MeshBuilder, rings, clock: Any) -> None:
    """Triangulate a planar polygon (``rings``: the outer ring first, then holes, each a
    list of ``(vertex index, point)``) into ``mb``, keeping the outer ring's direction."""
    outer = rings[0]
    if len(outer) < 3:
        raise Unsupported("degenerate", "POLY_LOOP", "a polygon of fewer than three points")
    if len(rings) == 1 and len(outer) == 3:
        mb.add_triangles((outer[0][0], outer[1][0], outer[2][0]))
        return
    n = _newell(outer)
    length = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2)
    if not length > 0 or not math.isfinite(length):
        raise Unsupported("degenerate", "POLY_LOOP", "a polygon with no area")
    z = (n[0] / length, n[1] / length, n[2] / length)
    x = perpendicular(z, None)
    y = (z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0])
    from ...tessellate.triangulate import earcut

    xy: list[tuple[float, float]] = []
    pid: list[int] = []
    idx_rings = []
    for ring in rings:
        ids = []
        for vi, q in ring:
            ids.append(len(xy))
            xy.append((q[0] * x[0] + q[1] * x[1] + q[2] * x[2], q[0] * y[0] + q[1] * y[1] + q[2] * y[2]))
            pid.append(vi)
        idx_rings.append(ids)
    tris, _complete = earcut(xy, idx_rings[0], idx_rings[1:], pid, clock)
    if not tris:
        raise Unsupported("triangulation_failed", "POLY_LOOP", "the polygon could not be triangulated")
    mb.add_triangles(i for t in tris for i in (pid[t[0]], pid[t[1]], pid[t[2]]))


# --------------------------------------------------------------------------- AP242
def tessellated(p21: Part21, rid: int, mb: MeshBuilder, clock: Any) -> int:
    """Triangles of a tessellated item (a solid, a shell, a face or a surface set) into
    ``mb``; returns the faces read."""
    g = Geometry(p21)
    coords: dict[int, int] = {}  # COORDINATES_LIST id -> index of its first vertex in mb
    return _group(g, rid, mb, coords, clock, 0)


def _group(g: Geometry, rid: int, mb: MeshBuilder, coords: dict, clock: Any, depth: int) -> int:
    if depth > MAX_GROUP_DEPTH:
        raise Unsupported("bad_reference", "TESSELLATED_SHELL", "groups nest too deep")
    rec = g.rec(Ref(rid))
    t = rec.types
    if "TESSELLATED_SOLID" in t or "TESSELLATED_SHELL" in t:
        n = 0
        prm = rec.params
        for it in prm[1] if len(prm) >= 2 and isinstance(prm[1], list) else []:
            if isinstance(it, Ref):
                n += _group(g, int(it), mb, coords, clock, depth + 1)
        return n
    if any(f in t for f in TESSELLATED_FACES):
        _face(g, rec, mb, coords, clock)
        return 1
    return 0


def _coordinates(g: Geometry, ref: Any, mb: MeshBuilder, coords: dict) -> tuple[int, int]:
    """``(first vertex index, count)`` of a COORDINATES_LIST, added to ``mb`` once."""
    rec = g.rec(ref, "COORDINATES_LIST")
    prm = rec.params
    rows = _list(prm[2] if len(prm) >= 3 else None, "a coordinates list")
    first = coords.get(rec.id)
    if first is None:
        flat: list[float] = []
        for row in rows:
            r = _list(row, "a coordinate")
            if len(r) != 3:
                raise Unsupported(
                    "bad_geometry", "COORDINATES_LIST", "a coordinate of other than three numbers"
                )
            flat.extend(_num(v, "a coordinate") for v in r)
        first = coords[rec.id] = mb.add_vertices(flat)
    return first, len(rows)


def _face(g: Geometry, rec, mb: MeshBuilder, coords: dict, clock: Any) -> None:
    t = rec.types
    prm = rec.params
    if len(prm) < 6:
        raise Unsupported("bad_reference", t[0], "a tessellated face without its attributes")
    first, count = _coordinates(g, prm[1], mb, coords)
    face = "TRIANGULATED_FACE" in t or "COMPLEX_TRIANGULATED_FACE" in t
    pnindex_at = 5 if face else 4
    pnindex = prm[pnindex_at] if len(prm) > pnindex_at and isinstance(prm[pnindex_at], list) else []
    lookup = [int(v) - 1 for v in pnindex if isinstance(v, int) and not isinstance(v, bool)]

    def vertex(k: Any) -> int:
        if isinstance(k, bool) or not isinstance(k, int) or k < 1:
            return 1 << 31  # out of range: the mesh builder leaves its triangle out
        i = k - 1
        if lookup:
            i = lookup[i] if i < len(lookup) else count
        return first + i if 0 <= i < count else 1 << 31

    out: list[int] = []
    if "COMPLEX_TRIANGULATED_FACE" in t or "COMPLEX_TRIANGULATED_SURFACE_SET" in t:
        strips = prm[pnindex_at + 1] if len(prm) > pnindex_at + 1 else []
        fans = prm[pnindex_at + 2] if len(prm) > pnindex_at + 2 else []
        for strip in strips if isinstance(strips, list) else []:
            s = [vertex(k) for k in _list(strip, "a strip")]
            for k in range(len(s) - 2):
                out.extend((s[k], s[k + 1], s[k + 2]) if k % 2 == 0 else (s[k + 1], s[k], s[k + 2]))
            if clock is not None:
                clock.tick(len(s) or 1)
        for fan in fans if isinstance(fans, list) else []:
            f = [vertex(k) for k in _list(fan, "a fan")]
            for k in range(1, len(f) - 1):
                out.extend((f[0], f[k], f[k + 1]))
            if clock is not None:
                clock.tick(len(f) or 1)
    else:
        tris = prm[pnindex_at + 1] if len(prm) > pnindex_at + 1 else []
        for tri in _list(tris, "triangles"):
            tr = _list(tri, "a triangle")
            if len(tr) != 3:
                raise Unsupported("bad_geometry", t[0], "a triangle of other than three corners")
            out.extend(vertex(k) for k in tr)
    mb.add_triangles(min(v, (1 << 32) - 1) for v in out)


__all__ = ["TESSELLATED_FACES", "faceted", "tessellated", "triangles"]
