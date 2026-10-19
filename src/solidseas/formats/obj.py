"""Wavefront OBJ with MTL colours (provisional, ``docs/formats/mesh.md``), and the pieces
the mesh readers share.

An OBJ file is text, one statement a line: ``v x y z`` a vertex, ``f a b c ...`` a
face over vertices numbered from 1 in the whole file (a negative number counts back
from the last vertex read; ``a/t/n`` also names a texture coordinate and a
normal, which are not kept), ``o name`` and ``g name`` start a named group,
``usemtl name`` picks a material and ``mtllib file`` names the material library
that defines it. SolidSeas reads:

* every group that has faces as one object, named by its ``o`` or ``g``
  statement (faces before any are the file's own object; a name used again adds
  to its group);
* faces of more than three corners projected onto their best-fit plane (Newell's
  normal) and cut into triangles by ear clipping
  (:func:`solidseas.tessellate.triangulate.earcut`), so concave ones come out
  right; a convex one is cut as a fan;
* the diffuse colour ``Kd`` (and ``d`` or ``Tr`` as its opacity) of each material
  from the libraries ``mtllib`` names, read only from inside the document's own
  folder (:func:`~solidseas.formats._source.read_sibling`); a group with several
  colours becomes one object a colour;
* comments anywhere on a line (``#`` to the end; on a line that names something,
  ``o``, ``g``, ``usemtl``, ``mtllib`` or ``newmtl``, a ``#`` after a space, so a
  name may hold one), and statements continued on the next line by a backslash at
  the end of a line, the joined statement within ``obj_line_bytes``.

Texture coordinates, texture maps, smoothing groups, points, lines and free-form
geometry are not read (``textures_ignored``, ``primitives_skipped``). OBJ states
no unit: millimetres are assumed (``units_assumed``).

A scene's ``max_triangles`` keeps the groups the read had left when it stopped, with
the faces read until then; the group being read is dropped, and the rest of the
file is not read (a material library it names later is not read either).

The rest of the module is shared by the mesh readers (3MF, PLY, OFF, AMF):
:class:`MeshSink` takes one object's vertices, triangles and colours and splits
it into one scene object a colour, :func:`polygon_triangles` triangulates a
polygon and :func:`text_lines` reads a text file a line at a time within a bound.
"""

import itertools
import math
import os
import re
from array import array
from collections import Counter
from collections.abc import Iterator, Sequence
from typing import Any

from ..errors import PathRefusedError, SldFormatError, SolidSeasError
from ._source import Clock, SiblingBudget, clip_text, read_sibling, sibling_resolution
from .base import (
    ExternalReference,
    ModelDocument,
    ModelNode,
    SceneBuilder,
    SceneOptions,
    _stem,
    _Truncated,
)
from .limits import Limits

REVISION = 1
Color = tuple[float, float, float, float]
NO_VERTEX = 0xFFFFFFFF  # an index no mesh has: MeshBuilder leaves its triangle out
_READ = 1 << 20  # text read at a time


# --------------------------------------------------------------------------- shared: text
def text_lines(
    source: Any, clock: Clock, limit: int, limit_name: str, start: int = 0, end: int | None = None
) -> Iterator[tuple[int, bytes]]:
    """``(line number, line)`` of the text from ``start`` to ``end``, each line without its
    line feed and at most ``limit`` bytes (else ``SldLimitError`` naming ``limit_name``)."""
    rest = b""
    number = 0
    for chunk in source.chunks(start, end, _READ):
        clock.tick(len(chunk) // 64 or 1)
        rest += chunk
        lines = rest.split(b"\n")
        rest = lines.pop()
        if len(rest) > limit:
            raise _too_long(limit, limit_name, number + len(lines) + 1)
        for line in lines:
            number += 1
            if len(line) > limit:
                raise _too_long(limit, limit_name, number)
            yield number, line
    if rest:
        yield number + 1, rest


def _too_long(limit: int, name: str, number: int) -> SolidSeasError:
    from ..errors import SldLimitError

    return SldLimitError(f"line {number} is longer than {limit:,} bytes", detail={"limit": name})


def decode_text(raw: bytes, limits: Limits, warnings: list | None = None, what: str = "a name") -> str:
    """Bytes of a name or a comment as text: UTF-8 (else Latin-1), control characters
    turned into spaces, cut to ``limits.text_bytes``."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    text = "".join(ch if ch >= " " or ch == "\t" else " " for ch in text).strip()
    return clip_text(text, limits, warnings, what)


_NAMING = frozenset({b"o", b"g", b"usemtl", b"mtllib", b"newmtl"})
_NAME_COMMENT = re.compile(rb"\s#")


def uncomment(line: bytes) -> bytes:
    """An OBJ or MTL line without its comment: everything from ``#`` on, except that on
    a line naming something (``o``, ``g``, ``usemtl``, ``mtllib``, ``newmtl``) a ``#``
    starts a comment only after a space, so a name may hold one."""
    s = line.lstrip()
    if s[:1] == b"#":
        return b""
    words = s.split(None, 1)
    if words and words[0] in _NAMING:
        m = _NAME_COMMENT.search(line)
        return line[: m.start()] if m else line
    i = line.find(b"#")
    return line if i < 0 else line[:i]


def number(token: Any) -> float:
    """A token as a float; ``SldFormatError`` when it is not a number."""
    try:
        return float(token)
    except (TypeError, ValueError):
        shown = token[:24] if isinstance(token, (bytes, str)) else type(token).__name__
        raise SldFormatError(f"{shown!r} is not a number") from None


def unit_color(r: float, g: float, b: float, a: float = 1.0) -> Color | None:
    """An RGBA colour of four numbers from 0 to 1 (clamped), or None when one is not finite."""
    if not all(math.isfinite(v) for v in (r, g, b, a)):
        return None
    return tuple(min(1.0, max(0.0, float(v))) for v in (r, g, b, a))  # type: ignore[return-value]


def hex_color(text: str) -> Color | None:
    """``#RRGGBB`` or ``#RRGGBBAA`` as an RGBA colour, else None."""
    if not isinstance(text, str):
        return None
    t = text.strip()
    if not t.startswith("#") or len(t) not in (7, 9):
        return None
    try:
        values = [int(t[i : i + 2], 16) / 255.0 for i in range(1, len(t), 2)]
    except ValueError:
        return None
    if len(values) == 3:
        values.append(1.0)
    return unit_color(*values)


_APPLICATION = re.compile(r"(.*?\S)[\s_-]+[vV]?(\d+(?:\.\d+)+[\w.+-]*)\s*\Z")


def split_application(text: str | None) -> dict[str, str | None]:
    """``application`` from a writer's name: ``{"name", "version"}``, the version split off
    when the text ends in one (``Example CAD 5.1.2``, ``Slicer-2.6.0``)."""
    if not text or not text.strip():
        return {"name": None, "version": None}
    text = text.strip()
    m = _APPLICATION.match(text)
    if m is None:
        return {"name": text, "version": None}
    return {"name": m.group(1), "version": m.group(2)}


# --------------------------------------------------------------------------- shared: packages and heads
def zip_chunks(package: Any, member: str, clock: Clock, max_bytes: int | None = None) -> Iterator[bytes]:
    """A zip member's bytes, inflated by :class:`~solidseas.formats._source.SafeZip` a chunk at
    a time while ticking ``clock``. A zip feature Python's reader declines (strong
    encryption, patched data) is refused as SolidSeas refuses an encrypted member
    (``format_not_supported``, rule ``encrypted``)."""
    from ..errors import FormatNotSupportedError

    package.clock = clock
    try:
        yield from package.iter_member(member, max_bytes=max_bytes)
    except NotImplementedError as exc:
        raise FormatNotSupportedError(
            f"a part of the package uses a zip feature SolidSeas does not read ({str(exc)[:80]})",
            detail={"rule": "encrypted", "value": "zip"},
        ) from None


class HeadChunks:
    """Chunks fed to an XML parser, counting what was fed, so a head read stops once the
    events of its first ``limit`` bytes are seen (never by cutting the document short,
    which the parser would take for damage). :attr:`past` is true once every event of
    the first ``limit`` bytes has been consumed."""

    def __init__(self, chunks: Any, limit: int) -> None:
        self._chunks = chunks
        self.limit = limit
        self.fed = 0
        self.consumed = 0  # bytes of the chunks whose events were all consumed

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self._chunks:
            self.consumed = self.fed
            self.fed += len(chunk)
            yield chunk

    @property
    def past(self) -> bool:
        return self.consumed >= self.limit


# --------------------------------------------------------------------------- shared: polygons
def polygon_triangles(
    positions: Sequence[float], corners: Sequence[int], clock: Clock
) -> list[tuple[int, ...]]:
    """Triangles over ``corners`` (vertex indices into ``positions``, x, y, z a vertex) of
    one planar, or nearly planar, polygon, wound as the polygon is. A convex polygon is
    cut as a fan; any other is projected onto its best-fit plane (Newell's normal) and
    cut by ear clipping, falling back to the fan when that fails (a polygon that
    crosses itself). A corner naming a vertex not read yet gives the fan."""
    n = len(corners)
    if n < 3:
        return []
    if n == 3:
        return [(corners[0], corners[1], corners[2])]
    fan = [(corners[0], corners[i], corners[i + 1]) for i in range(1, n - 1)]
    nv = len(positions) // 3
    if any(c >= nv for c in corners):
        return fan
    pts = [(positions[3 * c], positions[3 * c + 1], positions[3 * c + 2]) for c in corners]
    nx = ny = nz = 0.0
    for i in range(n):
        x0, y0, z0 = pts[i]
        x1, y1, z1 = pts[(i + 1) % n]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if not (length > 0.0 and math.isfinite(length)):
        return fan
    nx, ny, nz = nx / length, ny / length, nz / length
    convex = True
    for i in range(n):
        ax, ay, az = pts[i - 1]
        bx, by, bz = pts[i]
        cx, cy, cz = pts[(i + 1) % n]
        ux, uy, uz = bx - ax, by - ay, bz - az
        vx, vy, vz = cx - bx, cy - by, cz - bz
        turn = (uy * vz - uz * vy) * nx + (uz * vx - ux * vz) * ny + (ux * vy - uy * vx) * nz
        if turn < 0.0:
            convex = False
            break
    if convex:
        return fan
    from ..tessellate.triangulate import earcut

    # u, v in the plane with u x v along the normal, so the polygon is counter-clockwise
    ax = min(range(3), key=lambda k: abs((nx, ny, nz)[k]))
    e = [0.0, 0.0, 0.0]
    e[ax] = 1.0
    ux, uy, uz = ny * e[2] - nz * e[1], nz * e[0] - nx * e[2], nx * e[1] - ny * e[0]
    ul = math.sqrt(ux * ux + uy * uy + uz * uz)
    ux, uy, uz = ux / ul, uy / ul, uz / ul
    vx, vy, vz = ny * uz - nz * uy, nz * ux - nx * uz, nx * uy - ny * ux
    xy = [(x * ux + y * uy + z * uz, x * vx + y * vy + z * vz) for x, y, z in pts]
    tris, ok = earcut(xy, list(range(n)), [], list(corners), clock, max_steps=50 * n * n + 10_000)
    if not ok or len(tris) != n - 2:
        return fan
    return [(corners[a], corners[b], corners[c]) for a, b, c in tris]


# --------------------------------------------------------------------------- shared: objects
def split_colors(
    default: Color | None,
    palette: Sequence[Color | None] | None,
    color_ids: Sequence[int] | None,
    limits: Limits,
) -> tuple[list[Color | None], dict[int, int] | None, bool]:
    """The colours one object is split into, in the order they first appear: ``(colours,
    assignment, merged)``. ``color_ids`` gives each triangle an index into ``palette``
    (None: every triangle has ``default``; an index outside the palette is
    ``default`` too); ``assignment`` maps each id to its piece (None for one piece).
    More colours than ``limits.colors_per_object`` give one piece in the colour most
    triangles have, and ``merged``."""
    if color_ids is None or not len(color_ids):
        return [default], None, False
    pal = palette or ()
    counts = Counter(color_ids)  # ids in the order they first appear
    by_color: dict[Any, int] = {}
    weight: Counter = Counter()
    for cid, n in counts.items():
        c = pal[cid] if 0 <= cid < len(pal) else default
        by_color.setdefault(c, len(by_color))
        weight[c] += n
    colors = list(by_color)
    if len(colors) == 1:
        return colors, None, False
    if len(colors) > limits.colors_per_object:
        top = max(colors, key=lambda c: (weight[c], -by_color[c]))
        return [top], None, True
    assign = {cid: by_color[pal[cid] if 0 <= cid < len(pal) else default] for cid in counts}
    return colors, assign, False


class Palette:
    """Distinct colours numbered as they first appear (0 is None, no colour), at most
    ``limits.colors_per_object`` of them: past that :attr:`overflow` is set and every
    further colour is numbered 0, and the reader draws the object without its colours
    (``colors_ignored``)."""

    def __init__(self, limits: Limits) -> None:
        self.colors: list[Color | None] = [None]
        self._ids: dict[Color | None, int] = {None: 0}
        self.limit = limits.colors_per_object
        self.overflow = False

    def id(self, color: Color | None) -> int:
        i = self._ids.get(color)
        if i is None:
            if len(self.colors) > self.limit:
                self.overflow = True
                return 0
            i = self._ids[color] = len(self.colors)
            self.colors.append(color)
        return i


class MeshSink:
    """Where a mesh reader puts each object it reads (see the module notes).

    With a :class:`~solidseas.formats.base.SceneBuilder` (a scene), :meth:`count`
    counts what is about to be held against the scene's bounds and its
    ``max_triangles``, and :meth:`emit` adds one scene object a colour, each built by
    a :class:`~solidseas.formats.base.MeshBuilder` (indices checked, degenerate
    triangles dropped, metres). Without one (a tree), nothing is stored: the counts
    are kept against the bounds, and :meth:`emit` says which scene objects the
    object would become, so the tree and the scene number them alike.

    ``max_triangles`` keeps what was finished, as the STL reader does: a reader
    counts each object's last triangles before it emits it, with :meth:`take`, which
    returns False (and sets :attr:`cut`) once the cap is passed. The object being
    read then is dropped, the reader reads on only for what places the objects
    already emitted (a 3MF's build, an AMF's constellations) and places those, and
    :meth:`finish_scene` ends the scene as truncated."""

    def __init__(self, sb: SceneBuilder | None, limits: Limits, clock: Clock) -> None:
        self.sb = sb
        self.limits = limits
        self.clock = clock
        # the pieces are built through a builder of their own: their triangles and vertices
        # were counted on the scene already, as they were read
        self._pieces = SceneBuilder(limits, SceneOptions(), clock) if sb is not None else None
        self.n_objects = 0
        self.triangles = 0
        self.vertices = 0
        self.cut = False  # max_triangles was passed: nothing more is stored
        self._warned: set[str] = set()

    @property
    def building(self) -> bool:
        return self.sb is not None

    def count(self, triangles: int = 0, vertices: int = 0) -> None:
        if self.sb is not None:
            self.sb.take(triangles, vertices)
            return
        lim = self.limits
        self.triangles += triangles
        self.vertices += vertices
        if self.triangles > lim.triangles:
            raise lim.exceeded("triangles", f"the model has more than {lim.triangles:,} triangles")
        if self.vertices > lim.vertices:
            raise lim.exceeded("vertices", f"the model has more than {lim.vertices:,} vertices")

    def take(self, triangles: int = 0, vertices: int = 0) -> bool:
        """:meth:`count`, except that passing the scene's ``max_triangles`` returns False
        and sets :attr:`cut` instead of raising; once cut, nothing more is counted."""
        if self.cut:
            return False
        try:
            self.count(triangles, vertices)
        except _Truncated:
            self.cut = True
            return False
        return True

    def finish_scene(self) -> None:
        """End a scene whose read was cut (see the class notes): the base class marks it
        truncated, keeping what the reader placed."""
        if self.cut:
            raise _Truncated()

    def warn(self, code: str, message: str, *, once: bool = True) -> None:
        """A scene warning (dropped for a tree), once a code unless ``once`` is false."""
        if self.sb is None or (once and code in self._warned):
            return
        self._warned.add(code)
        self.sb.warn(code, message)

    def emit(
        self,
        *,
        name: str | None,
        node: str | None,
        scale_m: float,
        positions: Sequence[float],
        triangles: Sequence[int],
        normals: Sequence[float] | None = None,
        default: Color | None = None,
        palette: Sequence[Color | None] | None = None,
        color_ids: Sequence[int] | None = None,
        shared: bool = False,
    ) -> tuple[list[int], list[Color | None]]:
        """One object: its scene object indices (one a colour) and their colours.
        ``positions`` are x, y, z a vertex in units of ``scale_m`` metres,
        ``triangles`` index triples into them, ``normals`` one a vertex or None, and
        ``color_ids`` one index into ``palette`` a triangle (None: ``default``).
        ``shared`` says the vertices are the whole file's (an OBJ's), so each object
        keeps only those its triangles use."""
        colors, assign, merged = split_colors(default, palette, color_ids, self.limits)
        if merged:
            self.warn(
                "colors_ignored",
                f"an object has more than {self.limits.colors_per_object} colours; it is drawn in the "
                "colour most of its triangles have",
            )
        if self.sb is None:
            first = self.n_objects
            self.n_objects += len(colors)
            return list(range(first, first + len(colors))), colors
        pieces = self._pieces
        assert pieces is not None
        if normals is not None and len(normals) != len(positions):
            normals = None
        out: list[int] = []
        if assign is None and not shared:
            mb = pieces.mesh(name=name, scale_m=scale_m, color=colors[0], node=node)
            mb.add_vertices(positions)
            if normals is not None:
                mb.set_normals(normals)
            mb.add_triangles(triangles)
            out.append(self.sb.add_object(mb.build()))
            return out, colors
        if assign is None:
            per = [triangles]
        else:
            assert color_ids is not None
            per = [array("I") for _ in colors]
            for t in range(len(triangles) // 3):
                per[assign[color_ids[t]]].extend(triangles[3 * t : 3 * t + 3])
                if not t & 4095:
                    self.clock.tick(4096)
        nv = len(positions) // 3
        for k, color in enumerate(colors):
            tris = per[k]
            used = sorted(v for v in set(tris) if v < nv)
            local = {v: i for i, v in enumerate(used)}
            mb = pieces.mesh(name=name, scale_m=scale_m, color=color, node=node)
            mb.add_vertices(positions[3 * v + j] for v in used for j in range(3))
            if normals is not None:
                mb.set_normals(normals[3 * v + j] for v in used for j in range(3))
            mb.add_triangles(local.get(v, NO_VERTEX) for v in tris)
            out.append(self.sb.add_object(mb.build()))
        return out, colors


# --------------------------------------------------------------------------- OBJ
_PRIMITIVES = frozenset({b"l", b"p", b"curv", b"curv2", b"surf"})
_FREE_FORM = frozenset(
    {
        b"cstype",
        b"deg",
        b"bmat",
        b"step",
        b"parm",
        b"trim",
        b"hole",
        b"scrv",
        b"sp",
        b"end",
        b"con",
    }
)
_KNOWN = frozenset(
    {
        b"vp",
        b"s",
        b"mg",
        b"lod",
        b"usemap",
        b"maplib",
        b"bevel",
        b"c_interp",
        b"d_interp",
        b"shadow_obj",
        b"trace_obj",
        b"ctech",
        b"stech",
        b"call",
        b"csh",
    }
)


class _Group:
    __slots__ = ("color_ids", "name", "triangles")

    def __init__(self, name: str | None) -> None:
        self.name = name
        self.triangles = array("I")
        self.color_ids = array("I")


class ObjDocument(ModelDocument):
    """One OBJ file (see the module notes)."""

    format = "obj"

    def __init__(self, source, *, name, path, file_info, limits, detection=None) -> None:
        super().__init__(
            source, name=name, path=path, file_info=file_info, limits=limits, detection=detection
        )
        self.doc_type = "part"
        self.kind = "mesh"
        self.variant = None
        self.set_units("mm", "assumed")
        self.warn("units_assumed", "an OBJ file states no unit of length; millimetres were assumed")
        # The comments the file starts with, from its first 4 KiB (a line cut there is cut).
        comments = []
        for raw in source.head(4096).split(b"\n"):
            line = raw.strip()
            if not line:
                continue
            if line[:1] != b"#" or len(comments) >= 16:
                break
            text = decode_text(line[1:], limits, self.warnings, "a comment")
            if text:
                comments.append(text)
        if comments:
            from .base import make_property

            text = clip_text("\n".join(comments), limits, self.warnings, "the comments")
            self.properties = [make_property("comment", text)]

    def _stem(self) -> str | None:
        return _stem(self.name)

    # -- reading -------------------------------------------------------------------------
    def _read(self, sink: MeshSink) -> list[tuple[str, str | None, list[int], list[Color | None]]]:
        """Read the file into ``sink``: ``(node id, name, scene objects, colours)`` a group."""
        lim = self.limits
        clock = sink.clock
        positions = array("d")
        groups: dict[str | None, _Group] = {}
        group = None
        materials: dict[str, int] = {}
        material = 0  # no material
        libraries: list[str] = []
        skipped_primitives = textures = False
        degenerate = 0
        corners_max = lim.polygon_corners
        nv = 0
        pending = 0  # triangles read and not counted yet, all of the current group
        held = b""  # a statement continued by a backslash, from line ``start``
        start = 0
        lines = text_lines(self.source, clock, lim.obj_line_bytes, "obj_line_bytes")
        for number_, line in itertools.chain(lines, ((0, b""),)):  # a last empty line ends a held one
            if b"#" in line:
                line = uncomment(line)
            if b"\\" in line:
                end = line.rstrip()
                if end.endswith(b"\\"):
                    if not held:
                        start = number_
                    held += end[:-1] + b" "
                    if len(held) > lim.obj_line_bytes:
                        raise _too_long(lim.obj_line_bytes, "obj_line_bytes", start)
                    continue
            if held:
                raw, number_, held = held + line, start, b""
            else:
                raw = line
            parts = raw.split()
            if not parts:
                continue
            key = parts[0]
            if key == b"v":
                if len(parts) < 4:
                    raise SldFormatError(f"line {number_}: a vertex is not three numbers")
                try:
                    positions.extend((float(parts[1]), float(parts[2]), float(parts[3])))
                except ValueError:
                    raise SldFormatError(f"line {number_}: a vertex coordinate is not a number") from None
                nv += 1
                if not nv & 4095:
                    sink.count(0, 4096)
            elif key == b"f":
                n = len(parts) - 1
                if n > corners_max:
                    raise lim.exceeded(
                        "polygon_corners", f"line {number_}: a face has more than {corners_max:,} corners"
                    )
                if n < 3:
                    degenerate += 1
                    continue
                corners = []
                for tok in parts[1:]:
                    try:
                        i = int(tok.split(b"/", 1)[0])
                    except ValueError:
                        raise SldFormatError(
                            f"line {number_}: a face corner is not a vertex number"
                        ) from None
                    if 0 < i <= NO_VERTEX:
                        corners.append(i - 1)
                    elif i < 0 and nv + i >= 0:
                        corners.append(nv + i)
                    else:
                        corners.append(NO_VERTEX)
                if group is None:
                    group = groups.setdefault(None, _Group(None))
                if n == 3:
                    group.triangles.extend(corners)
                    group.color_ids.append(material)
                    pending += 1
                else:
                    tris = polygon_triangles(positions, corners, clock)
                    for t in tris:
                        group.triangles.extend(t)
                    group.color_ids.extend([material] * len(tris))
                    pending += len(tris)
                if pending >= 4096:
                    if not sink.take(pending, 0):
                        break  # max_triangles: this group is dropped below
                    pending = 0
            elif key == b"vn" or key == b"#":
                continue
            elif key == b"vt":
                textures = True
            elif key in (b"o", b"g"):
                if pending:  # the group being left is counted whole
                    if not sink.take(pending, 0):
                        break
                    pending = 0
                label = decode_text(raw.strip()[len(key) :], lim, None) or None
                group = groups.get(label)
                if group is None:
                    if len(groups) >= lim.objects:
                        raise lim.exceeded("objects", f"the file has more than {lim.objects:,} groups")
                    group = groups[label] = _Group(label)
            elif key == b"usemtl":
                label = decode_text(raw.strip()[6:], lim, None)
                material = materials.get(label, 0)
                if not material:
                    if len(materials) >= lim.obj_materials:
                        raise lim.exceeded(
                            "obj_materials", f"the file uses more than {lim.obj_materials:,} materials"
                        )
                    material = materials[label] = len(materials) + 1
            elif key == b"mtllib":
                for lib in _library_names(raw.strip()[6:], lim):
                    if lib not in libraries:
                        libraries.append(lib)
            elif key in _PRIMITIVES:
                skipped_primitives = True
            elif key in _FREE_FORM or key in _KNOWN or key.startswith(b"#"):
                continue
            else:
                continue  # a statement OBJ readers do not share: ignored, as they ignore it
        if not sink.cut:
            sink.take(pending, nv & 4095)
        if sink.cut and group is not None:  # the group being read when max_triangles was passed
            groups.pop(group.name, None)
        colors, map_textures, unread = self._materials(libraries, materials, clock)
        if unread:
            sink.warn(
                "material_library_unread",
                f"{unread} material libraries the file names could not be read; their colours are not shown",
            )
        if textures or map_textures:
            sink.warn("textures_ignored", "texture coordinates and texture maps are not read")
        if skipped_primitives:
            sink.warn("primitives_skipped", "points, lines and free-form curves and surfaces are not read")
        if degenerate:
            sink.warn(
                "degenerate_triangles_dropped",
                f"{degenerate} faces have fewer than three corners; they were left out",
                once=False,
            )
        palette: list[Color | None] = [None] + [colors.get(m) for m in materials]
        out = []
        stem = self._stem()
        k = 0
        for g in groups.values():
            if not g.triangles:
                continue
            k += 1
            node = str(k)
            ids = g.color_ids if any(g.color_ids) else None
            objs, cols = sink.emit(
                name=g.name or stem,
                node=node,
                scale_m=0.001,
                positions=positions,
                triangles=g.triangles,
                palette=palette,
                color_ids=ids,
                shared=True,
            )
            out.append((node, g.name or stem, objs, cols))
        return out

    def _materials(
        self, libraries: list[str], used: dict[str, int], clock: Clock
    ) -> tuple[dict[str, Color | None], bool, int]:
        """The colours of the materials ``used``, from ``libraries``: ``(colours by name,
        texture maps seen, libraries that could not be read)``."""
        colors: dict[str, Color | None] = {}
        textures = False
        unread = 0
        if not libraries:
            return colors, textures, unread
        lim = self.limits
        if len(libraries) > lim.obj_material_libraries:
            raise lim.exceeded(
                "obj_material_libraries", f"the file names more than {lim.obj_material_libraries} libraries"
            )
        budget = SiblingBudget.of(self.source, lim)
        for lib in libraries:
            try:
                data = read_sibling(self.path, lib, budget)
            except (OSError, PathRefusedError, SldFormatError):
                unread += 1
                continue
            got, tex = _parse_mtl(data, lim, clock)
            textures = textures or tex
            for k, v in got.items():
                colors.setdefault(k, v)
        return {name: colors.get(name) for name in used}, textures, unread

    # -- hooks ---------------------------------------------------------------------------
    def _tree(self, clock: Clock):
        groups = self._read(MeshSink(None, self.limits, clock))
        return [
            ModelNode(node, None, name, "object", objs[0] if objs else None, color=cols[0] if cols else None)
            for node, name, objs, cols in groups
        ]

    def _scene(self, sb: SceneBuilder) -> None:
        sink = MeshSink(sb, self.limits, sb.clock)
        for node, _name, objs, _cols in self._read(sink):
            for i in objs:
                sb.add_item(i, node)
        sink.finish_scene()

    def _references(self, clock: Clock) -> list[ExternalReference]:
        lim = self.limits
        names: list[str] = []
        for _n, raw in text_lines(self.source, clock, lim.obj_line_bytes, "obj_line_bytes"):
            line = uncomment(raw).lstrip() if b"#" in raw else raw.lstrip()
            if line[:6] == b"mtllib" and line[6:7].isspace():
                for lib in _library_names(line.strip()[6:], lim):
                    if lib not in names:
                        names.append(lib)
                        if len(names) > lim.references:
                            break
        return [
            ExternalReference(
                f"mtllib:{i + 1}",
                "material_library",
                lib,
                os.path.basename(lib.replace("\\", "/")) or lib,
                sibling_resolution(self.path, lib, refuse_hard_links=self.refuse_hard_links),
            )
            for i, lib in enumerate(names)
        ]


def _library_names(raw: bytes, limits: Limits) -> list[str]:
    """The library names of one ``mtllib`` statement: the whole rest of the line when it
    ends in ``.mtl`` and holds no other ``.mtl`` (a name with spaces), else its words."""
    text = decode_text(raw, limits, None)
    if not text:
        return []
    if text.lower().endswith(".mtl") and text.lower().count(".mtl") == 1:
        return [text]
    return text.split()


def _parse_mtl(data: bytes, limits: Limits, clock: Clock) -> tuple[dict[str, Color | None], bool]:
    """The diffuse colours of an MTL library's materials, and whether it names texture maps."""
    from ._source import Source

    colors: dict[str, Color | None] = {}
    current: str | None = None
    kd: list[float] | None = None
    alpha = 1.0
    textures = False

    def close() -> None:
        if current is not None and current not in colors:
            colors[current] = unit_color(*kd, alpha) if kd is not None else None

    for _n, line in text_lines(Source(data), clock, limits.obj_line_bytes, "obj_line_bytes"):
        raw = uncomment(line) if b"#" in line else line
        parts = raw.split()
        if not parts:
            continue
        key = parts[0].lower()
        if key == b"newmtl":
            close()
            if len(colors) >= limits.obj_materials:
                raise limits.exceeded(
                    "obj_materials", f"a library defines more than {limits.obj_materials:,} materials"
                )
            current = decode_text(raw.strip()[6:], limits, None)
            kd, alpha = None, 1.0
        elif key == b"kd" and len(parts) >= 4:
            try:
                kd = [float(parts[1]), float(parts[2]), float(parts[3])]
            except ValueError:
                kd = None  # a spectral or CIE XYZ colour: not read
        elif key == b"d" and len(parts) >= 2:
            try:
                alpha = float(parts[-1])
            except ValueError:
                pass
        elif key == b"tr" and len(parts) >= 2:
            try:
                alpha = 1.0 - float(parts[-1])
            except ValueError:
                pass
        elif key.startswith(b"map_") or key in (b"bump", b"disp", b"decal", b"refl"):
            textures = True
    close()
    return colors, textures


def open(source, *, name, path, file_info, limits, hold_open=False, detection=None) -> ObjDocument:
    """Open an OBJ file's :class:`~solidseas.formats._source.Source` (the registry's reader
    for ``obj``)."""
    return ObjDocument(source, name=name, path=path, file_info=file_info, limits=limits, detection=detection)


__all__ = [
    "NO_VERTEX",
    "REVISION",
    "MeshSink",
    "Palette",
    "ObjDocument",
    "decode_text",
    "hex_color",
    "number",
    "open",
    "polygon_triangles",
    "split_application",
    "split_colors",
    "text_lines",
    "uncomment",
    "unit_color",
]
