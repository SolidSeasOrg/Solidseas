"""PLY, the Stanford polygon file format, ASCII and binary (provisional,
``docs/formats/mesh.md``).

A PLY file is a text header, then the elements it declares in order. The header
is ``ply``, ``format ascii|binary_little_endian|binary_big_endian 1.0``,
``comment`` and ``obj_info`` lines, and for each element ``element name count``
followed by its properties: ``property type name`` or ``property list
count_type item_type name``; it ends at the first line that is ``end_header``
alone (the words in a comment end nothing). SolidSeas reads the ``vertex``
element (``x``, ``y``, ``z``; ``nx``, ``ny``, ``nz`` as normals; ``red``,
``green``, ``blue`` and ``alpha``, or ``diffuse_red``... as colours) and the
``face`` element
(``vertex_indices`` or ``vertex_index``, and a colour of its own), or
``tristrips`` (strips with -1 between them). Every other element is skipped by
its size; a list is skipped item by item. Faces of more than three corners are cut
into triangles as an OBJ's are (:func:`solidseas.formats.obj.polygon_triangles`).

Each triangle takes its face's colour, else the colour of its first corner;
one object a colour (``colors_ignored`` past ``colors_per_object``). A file
without faces holds points only, which are not read (``primitives_skipped``).
Comments and ``obj_info`` lines become the properties ``comment`` and
``obj_info``. PLY states no unit: millimetres are assumed (``units_assumed``).

Every count is checked against the bytes left before anything is allocated:
each row takes at least its fixed-size properties and list counts (binary), or
two bytes a property (ASCII).
"""

import re
import struct
import sys
from array import array

from ..errors import SldFormatError
from ._source import Clock
from .base import ModelDocument, ModelNode, SceneBuilder, _stem, make_property
from .obj import NO_VERTEX, MeshSink, Palette, decode_text, polygon_triangles, text_lines, unit_color

REVISION = 1
_TYPES = {
    b"char": "b",
    b"int8": "b",
    b"uchar": "B",
    b"uint8": "B",
    b"short": "h",
    b"int16": "h",
    b"ushort": "H",
    b"uint16": "H",
    b"int": "i",
    b"int32": "i",
    b"uint": "I",
    b"uint32": "I",
    b"float": "f",
    b"float32": "f",
    b"double": "d",
    b"float64": "d",
}
_INTEGER = frozenset("bBhHiI")
_END_HEADER = re.compile(rb"\nend_header(\r?\n|\Z)")  # the line that ends the header, and its line end
_COLOR_SCALE = {"b": 127.0, "B": 255.0, "h": 32767.0, "H": 65535.0, "i": 2147483647.0, "I": 4294967295.0}
_FORMATS = {b"ascii": "ascii", b"binary_little_endian": "binary_le", b"binary_big_endian": "binary_be"}
_COLOR_NAMES = (
    ("red", "green", "blue", "alpha"),
    ("diffuse_red", "diffuse_green", "diffuse_blue", "diffuse_alpha"),
)
_BATCH = 16_384  # fixed-size rows unpacked at a time


class _Prop:
    __slots__ = ("code", "count_code", "name")

    def __init__(self, name: str, code: str, count_code: str | None = None) -> None:
        self.name = name
        self.code = code
        self.count_code = count_code


class _Element:
    __slots__ = ("count", "name", "props")

    def __init__(self, name: str, count: int) -> None:
        self.name = name
        self.count = count
        self.props: list[_Prop] = []

    def index(self, name: str) -> int | None:
        for i, p in enumerate(self.props):
            if p.name == name:
                return i
        return None

    @property
    def fixed(self) -> bool:
        return all(p.count_code is None for p in self.props)

    def min_bytes(self, binary: bool) -> int:
        """The fewest bytes a row can take."""
        if not binary:
            return 2 * len(self.props)
        return sum(struct.calcsize(p.count_code or p.code) for p in self.props)


class PlyDocument(ModelDocument):
    """One PLY file (see the module notes)."""

    format = "ply"

    def __init__(self, source, *, name, path, file_info, limits, detection=None) -> None:
        super().__init__(
            source, name=name, path=path, file_info=file_info, limits=limits, detection=detection
        )
        self.doc_type = "part"
        self.kind = "mesh"
        self.set_units("mm", "assumed")
        self.warn("units_assumed", "a PLY file states no unit of length; millimetres were assumed")
        self._header()

    # -- the header ------------------------------------------------------------------------
    def _header(self) -> None:
        lim = self.limits
        head = self.source.head(lim.ply_header_bytes + 2)
        # the header ends at a line that is end_header alone, never at those words in a comment
        m = _END_HEADER.search(head)
        if m is not None and not m.group(1) and len(head) < self.source.size:
            m = None  # cut off by the head, not by the file's end
        if m is None:
            if self.source.size > lim.ply_header_bytes:
                raise lim.exceeded(
                    "ply_header_bytes", f"the PLY header is longer than {lim.ply_header_bytes:,} bytes"
                )
            raise SldFormatError("the PLY header has no end_header line")
        self.data_start = m.end()
        lines = head[: m.start() + 1].replace(b"\r\n", b"\n").split(b"\n")
        if not lines or lines[0].strip() != b"ply":
            raise SldFormatError("not a PLY file: it does not start with ply")
        fmt = None
        elements: list[_Element] = []
        comments: list[str] = []
        info: list[str] = []
        for number_, raw in enumerate(lines[1:], start=2):
            parts = raw.split()
            if not parts:
                continue
            key = parts[0]
            if key == b"format":
                if len(parts) != 3 or parts[1] not in _FORMATS or fmt is not None:
                    raise SldFormatError(f"header line {number_}: the format line is not one PLY knows")
                if not parts[2].startswith(b"1."):
                    raise SldFormatError(f"header line {number_}: PLY version {parts[2][:8]!r} is not read")
                fmt = _FORMATS[parts[1]]
            elif key == b"comment":
                comments.append(decode_text(raw.strip()[7:], lim, self.warnings, "a comment"))
            elif key == b"obj_info":
                info.append(decode_text(raw.strip()[8:], lim, self.warnings, "an obj_info line"))
            elif key == b"element":
                if len(parts) != 3:
                    raise SldFormatError(f"header line {number_}: an element line is not element name count")
                try:
                    count = int(parts[2])
                except ValueError:
                    raise SldFormatError(f"header line {number_}: an element count is not a number") from None
                if count < 0:
                    raise SldFormatError(f"header line {number_}: an element count is negative")
                if len(elements) >= lim.ply_elements:
                    raise lim.exceeded(
                        "ply_elements", f"the PLY declares more than {lim.ply_elements} elements"
                    )
                elements.append(_Element(parts[1].decode("latin-1"), count))
            elif key == b"property":
                if not elements:
                    raise SldFormatError(f"header line {number_}: a property comes before any element")
                el = elements[-1]
                if len(el.props) >= lim.ply_properties:
                    raise lim.exceeded(
                        "ply_properties", f"a PLY element has more than {lim.ply_properties} properties"
                    )
                if len(parts) == 5 and parts[1] == b"list":
                    if parts[2] not in _TYPES or parts[3] not in _TYPES or _TYPES[parts[2]] not in _INTEGER:
                        raise SldFormatError(f"header line {number_}: a list property has an unknown type")
                    el.props.append(_Prop(parts[4].decode("latin-1"), _TYPES[parts[3]], _TYPES[parts[2]]))
                elif len(parts) == 3 and parts[1] in _TYPES:
                    el.props.append(_Prop(parts[2].decode("latin-1"), _TYPES[parts[1]]))
                else:
                    raise SldFormatError(f"header line {number_}: a property line is not one PLY knows")
            else:
                raise SldFormatError(f"header line {number_}: {key[:20]!r} is not a PLY header keyword")
        if fmt is None:
            raise SldFormatError("the PLY header has no format line")
        self.variant = fmt
        self.elements = elements
        binary = fmt != "ascii"
        need = sum(e.count * e.min_bytes(binary) for e in elements)
        left = self.source.size - self.data_start
        if need - (0 if binary else 1) > left:
            raise SldFormatError("the PLY declares more elements than the file holds")
        props = []
        if comments:
            props.append(make_property("comment", "\n".join(comments)))
        if info:
            props.append(make_property("obj_info", "\n".join(info)))
        self.properties = props
        vertex = self._element("vertex")
        if vertex is None:
            raise SldFormatError("the PLY has no vertex element")
        if any(vertex.index(c) is None for c in ("x", "y", "z")):
            raise SldFormatError("the PLY's vertices have no x, y and z")

    def _element(self, name: str) -> _Element | None:
        for e in self.elements:
            if e.name == name:
                return e
        return None

    def _faces(self) -> _Element | None:
        return self._element("face") or self._element("tristrips")

    def _counts(self):
        vertex = self._element("vertex")
        return {"objects": 1, "items": 1, "vertices": vertex.count if vertex else None}

    # -- reading -------------------------------------------------------------------------
    def _rows(self, clock: Clock):
        """A reader of the elements' rows from the start of the data."""
        if self.variant == "ascii":
            return _TextRows(self, clock)
        endian = "<" if self.variant == "binary_le" else ">"
        return _BinaryRows(self.source, self.data_start, endian, clock)

    def _read(self, sink: MeshSink) -> tuple[list[int], list]:
        lim = self.limits
        clock = sink.clock
        positions = array("d")
        normals: array | None = None
        vertex_colors: array | None = None
        palette = Palette(lim)
        triangles = array("I")
        color_ids: array | None = None
        degenerate = 0
        els = self.elements
        vi = next(i for i, e in enumerate(els) if e.name == "vertex")
        fi = next((i for i, e in enumerate(els) if e.name in ("face", "tristrips")), None)
        rows = self._rows(clock)
        if fi is not None and fi < vi:
            # The faces come first: read the vertices, then go back for the faces, whose
            # polygons need the vertices to be cut and the vertices' colours to be coloured.
            for el in els[:vi]:
                rows.skip(el)
            normals, vertex_colors = self._vertices(els[vi], rows, positions, palette, sink)
            for el in els[vi + 1 :]:
                rows.skip(el)
            rows = self._rows(clock)
            for el in els[:fi]:
                rows.skip(el)
            color_ids, degenerate = self._polygons(
                els[fi], rows, positions, vertex_colors, palette, triangles, sink
            )
        else:
            for i, el in enumerate(els):
                if i == vi:
                    normals, vertex_colors = self._vertices(el, rows, positions, palette, sink)
                elif i == fi:
                    color_ids, degenerate = self._polygons(
                        el, rows, positions, vertex_colors, palette, triangles, sink
                    )
                else:
                    rows.skip(el)
        if palette.overflow:
            sink.warn(
                "colors_ignored",
                f"the model has more than {lim.colors_per_object} colours; it is drawn without them",
            )
            color_ids = None
        if fi is None:
            sink.warn("primitives_skipped", "the file holds points only, which are not read")
        if degenerate:
            sink.warn(
                "degenerate_triangles_dropped",
                f"{degenerate} faces have fewer than three corners; they were left out",
                once=False,
            )
        return sink.emit(
            name=_stem(self.name),
            node="1",
            scale_m=0.001,
            positions=positions,
            triangles=triangles,
            normals=normals,
            palette=palette.colors,
            color_ids=color_ids,
        )

    def _vertices(self, el: _Element, rows, positions: array, palette: Palette, sink: MeshSink):
        ix, iy, iz = (el.index(c) for c in ("x", "y", "z"))
        inorm = [el.index(c) for c in ("nx", "ny", "nz")]
        has_normals = all(i is not None for i in inorm)
        normals = array("f") if has_normals else None
        icol = None
        for names in _COLOR_NAMES:
            got = [el.index(c) for c in names[:3]]
            if all(i is not None for i in got):
                icol = (*got, el.index(names[3]))
                break
        colors = array("I") if icol is not None else None
        scales = [_COLOR_SCALE.get(el.props[i].code, 1.0) if i is not None else 1.0 for i in (icol or ())]
        keep = {ix, iy, iz, *(inorm if has_normals else ()), *(i for i in icol or () if i is not None)}
        n = 0
        for row in rows.rows(el, keep=keep):
            positions.extend((row[ix], row[iy], row[iz]))
            if normals is not None:
                normals.extend((row[inorm[0]], row[inorm[1]], row[inorm[2]]))
            if colors is not None:
                r, g, b, a = icol
                c = unit_color(
                    row[r] / scales[0],
                    row[g] / scales[1],
                    row[b] / scales[2],
                    row[a] / scales[3] if a is not None else 1.0,
                )
                colors.append(palette.id(c))
            n += 1
            if not n & 4095:
                sink.count(0, 4096)
        sink.count(0, n & 4095)
        return normals, colors

    def _polygons(self, el, rows, positions, vertex_colors, palette, triangles, sink):
        lim = self.limits
        k = el.index("vertex_indices")
        if k is None:
            k = el.index("vertex_index")
        if k is None or el.props[k].count_code is None or el.props[k].code not in _INTEGER:
            raise SldFormatError(f"the PLY's {el.name} element has no list of vertex indices")
        icol = None
        for names in _COLOR_NAMES:
            got = [el.index(c) for c in names[:3]]
            if all(i is not None for i in got):
                icol = (*got, el.index(names[3]))
                break
        scales = [_COLOR_SCALE.get(el.props[i].code, 1.0) if i is not None else 1.0 for i in (icol or ())]
        colored = icol is not None or vertex_colors is not None
        ids = array("I") if colored else None
        strips = el.name == "tristrips"
        nv = len(positions) // 3
        degenerate = 0
        pending = 0
        clock = sink.clock
        keep = {k, *(i for i in icol or () if i is not None)}
        if strips:
            # a strip list is as long as the file allows (often the whole mesh in one row):
            # read compactly, its triangles counted as they are made
            got = rows.rows(el, keep=keep, compact=k)
        else:
            got = rows.rows(el, lim.polygon_corners, keep=keep)
        for row in got:
            first = len(triangles) // 3
            corners = row[k]
            if strips:
                pending = _strip_into(corners, triangles, pending, sink)
            else:
                if len(corners) == 3:
                    tris = (corners,)
                elif len(corners) < 3:
                    degenerate += 1
                    continue
                else:
                    tris = polygon_triangles(
                        positions, [c if 0 <= c < nv else NO_VERTEX for c in corners], clock
                    )
                for a0, b0, c0 in tris:
                    triangles.extend(
                        (
                            a0 if 0 <= a0 < NO_VERTEX else NO_VERTEX,
                            b0 if 0 <= b0 < NO_VERTEX else NO_VERTEX,
                            c0 if 0 <= c0 < NO_VERTEX else NO_VERTEX,
                        )
                    )
                pending += len(tris)
                if pending >= 4096:
                    sink.count(pending, 0)
                    pending = 0
            if ids is not None:
                if icol is not None:
                    r, g, b, a = icol
                    cid = palette.id(
                        unit_color(
                            row[r] / scales[0],
                            row[g] / scales[1],
                            row[b] / scales[2],
                            row[a] / scales[3] if a is not None else 1.0,
                        )
                    )
                    ids.extend(array("I", [cid]) * (len(triangles) // 3 - first))
                else:
                    nc = len(vertex_colors)
                    for t in range(first, len(triangles) // 3):
                        a0 = triangles[3 * t]
                        ids.append(vertex_colors[a0] if a0 < nc else 0)
        sink.count(pending, 0)
        return ids, degenerate

    # -- hooks ---------------------------------------------------------------------------
    def _tree(self, clock: Clock):
        objs, cols = self._read(MeshSink(None, self.limits, clock))
        return [ModelNode("1", None, _stem(self.name), "object", objs[0], color=cols[0])]

    def _scene(self, sb: SceneBuilder) -> None:
        objs, _cols = self._read(MeshSink(sb, self.limits, sb.clock))
        for i in objs:
            sb.add_item(i, "1")


def _strip_into(indices, triangles: array, pending: int, sink: MeshSink) -> int:
    """Append the triangles of triangle strips separated by negative numbers to
    ``triangles``, every other one turned so all keep the strip's winding, counting them
    on ``sink`` 4,096 at a time; returns the triangles made and not counted yet."""
    a = b = 0
    k = 0  # vertices of the current strip so far
    for v in indices:
        if v < 0:
            k = 0
            continue
        if v >= NO_VERTEX:
            v = NO_VERTEX
        if k >= 2:
            triangles.extend((a, b, v) if k % 2 == 0 else (b, a, v))
            pending += 1
            if pending >= 4096:
                sink.count(pending, 0)
                pending = 0
        a, b = b, v
        k += 1
    return pending


class _BinaryRows:
    """Rows of binary elements, read in order from ``start``."""

    def __init__(self, source, start: int, endian: str, clock: Clock) -> None:
        self.source = source
        self.pos = start
        self.endian = endian
        self.clock = clock
        self.buf = b""
        self.at = 0

    def _need(self, n: int) -> None:
        if len(self.buf) - self.at >= n:
            return
        want = max(n - (len(self.buf) - self.at), 1 << 20)
        more = self.source.read_upto(self.pos, want)
        self.pos += len(more)
        self.buf = self.buf[self.at :] + more
        self.at = 0
        if len(self.buf) < n:
            raise SldFormatError("the PLY ends before its last element")

    def _left(self) -> int:
        return self.source.size - self.pos + len(self.buf) - self.at

    def _skip(self, n: int) -> None:
        """Pass over ``n`` bytes without reading them."""
        have = len(self.buf) - self.at
        if n <= have:
            self.at += n
            return
        self.pos += n - have
        self.buf, self.at = b"", 0
        if self.pos > self.source.size:
            raise SldFormatError("the PLY ends before its last element")

    def rows(self, el: _Element, max_items: int | None = None, *, keep=None, compact: int | None = None):
        """The element's rows: a value a property, a tuple a list. ``max_items`` bounds the
        lists ``keep`` names (every list when it is None); the other lists are passed over
        (None), and list ``compact`` is read whole as an array, as long as the file allows."""
        if el.fixed:
            yield from self._fixed(el)
            return
        yield from self._lists(el, max_items, keep, compact)

    def _fixed(self, el: _Element):
        one = struct.Struct(self.endian + "".join(p.code for p in el.props))
        done = 0
        while done < el.count:
            k = min(_BATCH, el.count - done)
            self._need(k * one.size)
            block = memoryview(self.buf)[self.at : self.at + k * one.size]
            self.at += k * one.size
            yield from one.iter_unpack(block)
            done += k
            self.clock.tick(k)

    def _lists(self, el: _Element, max_items: int | None, keep=None, compact: int | None = None):
        endian = self.endian
        fmts = [
            (struct.Struct(endian + (p.count_code or p.code)), p.count_code is not None, p.code)
            for p in el.props
        ]
        sizes = {code: struct.calcsize(code) for code in {p.code for p in el.props}}
        swap = (endian == "<") != (sys.byteorder == "little")
        for _ in range(el.count):
            row = []
            for i, (st, is_list, code) in enumerate(fmts):
                self._need(st.size)
                (v,) = st.unpack_from(self.buf, self.at)
                self.at += st.size
                if not is_list:
                    row.append(v)
                    continue
                if v < 0:
                    raise SldFormatError(f"a list in the PLY's {el.name} element has a negative length")
                size = sizes[code] * v
                kept = keep is None or i in keep
                if kept and i != compact and max_items is not None and v > max_items:
                    raise _corners(max_items)
                if size > self._left():
                    raise SldFormatError("a PLY list runs past the end of the file")
                if not kept:
                    self._skip(size)
                    row.append(None)
                    continue
                self._need(size)
                if i == compact and array(code).itemsize == sizes[code]:
                    values = array(code)
                    values.frombytes(self.buf[self.at : self.at + size])
                    if swap and values.itemsize > 1:
                        values.byteswap()
                    row.append(values)
                else:
                    row.append(struct.unpack_from(f"{endian}{v}{code}", self.buf, self.at))
                self.at += size
            self.clock.tick()
            yield row

    def skip(self, el: _Element) -> None:
        if el.fixed:
            size = el.count * el.min_bytes(True)
            if size > self._left():
                raise SldFormatError("the PLY ends before its last element")
            self._skip(size)
            return
        for _row in self._lists(el, None, keep=()):
            pass


def _corners(limit: int):
    from ..errors import SldLimitError

    return SldLimitError(f"a PLY face has more than {limit:,} corners", detail={"limit": "polygon_corners"})


class _TextRows:
    """Rows of ASCII elements, read in order: tokens may run across lines."""

    def __init__(self, doc: PlyDocument, clock: Clock) -> None:
        lim = doc.limits
        self.lines = text_lines(doc.source, clock, lim.obj_line_bytes, "obj_line_bytes", doc.data_start)
        self.buf: list[bytes] = []
        self.at = 0
        self.clock = clock

    def _next(self) -> bytes:
        while self.at >= len(self.buf):
            try:
                _n, line = next(self.lines)
            except StopIteration:
                raise SldFormatError("the PLY ends before its last element") from None
            self.buf = line.split()
            self.at = 0
        t = self.buf[self.at]
        self.at += 1
        return t

    def _value(self, code: str):
        t = self._next()
        try:
            return int(t) if code in _INTEGER else float(t)
        except ValueError:
            raise SldFormatError(f"{t[:24]!r} in the PLY is not a number of its property's type") from None

    def rows(self, el: _Element, max_items: int | None = None, *, keep=None, compact: int | None = None):
        """As :meth:`_BinaryRows.rows`; a compact list's values are clamped to -1 (a strip's
        end) and to 2**31 - 1 (no vertex)."""
        props = [(p.code, p.count_code) for p in el.props]
        for _ in range(el.count):
            row = []
            for i, (code, count_code) in enumerate(props):
                kept = keep is None or i in keep
                if count_code is None:
                    if kept:
                        row.append(self._value(code))
                    else:
                        self._next()
                        row.append(None)
                    continue
                n = self._value(count_code)
                if n < 0:
                    raise SldFormatError(f"a list in the PLY's {el.name} element has a negative length")
                if not kept:
                    for _i in range(n):
                        self._next()
                    row.append(None)
                elif i == compact:
                    values = array("i")
                    for _i in range(n):
                        v = self._value(code)
                        values.append(-1 if v < 0 else min(v, 0x7FFFFFFF))
                    row.append(values)
                else:
                    if max_items is not None and n > max_items:
                        raise _corners(max_items)
                    row.append(tuple(self._value(code) for _ in range(n)))
            self.clock.tick()
            yield row

    def skip(self, el: _Element) -> None:
        props = [p.count_code for p in el.props]
        for _ in range(el.count):
            for count_code in props:
                if count_code is None:
                    self._next()
                    continue
                n = self._value(count_code)
                if n < 0:
                    raise SldFormatError(f"a list in the PLY's {el.name} element has a negative length")
                for _i in range(n):
                    self._next()
            self.clock.tick()


def open(source, *, name, path, file_info, limits, hold_open=False, detection=None) -> PlyDocument:
    """Open a PLY file's :class:`~solidseas.formats._source.Source` (the registry's reader
    for ``ply``)."""
    return PlyDocument(source, name=name, path=path, file_info=file_info, limits=limits, detection=detection)


__all__ = ["REVISION", "PlyDocument", "open"]
