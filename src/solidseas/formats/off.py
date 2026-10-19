"""OFF, the Object File Format of Geomview, as text (provisional, ``docs/formats/mesh.md``).

An OFF file starts with its keyword: ``OFF``, or with prefixes that add to each
vertex line, ``N`` a normal, ``C`` a colour and ``ST`` a texture coordinate
(``NOFF``, ``COFF``, ``CNOFF``, ``STOFF``...). Then the counts of vertices,
faces and edges (on the keyword's line or the next), the vertices one a line
(``x y z``, then the normal, the colour and the texture coordinate the keyword
promises) and the faces one a line: the number of corners, the vertex numbers
from 0, and an optional colour. ``#`` starts a comment. A colour is three or four
numbers, from 0 to 1 when written with a decimal point and from 0 to 255
otherwise; one number alone is a colour-map index, which is not read.

Faces of more than three corners are cut into triangles as an OBJ's are
(:func:`solidseas.formats.obj.polygon_triangles`). Each triangle takes its
face's colour, else the colour of its first corner; one object a colour.
Normals are kept, texture coordinates are not (``textures_ignored``). OFF
states no unit: millimetres are assumed (``units_assumed``).

The keyword is optional, as the manual says, since many files lack it: a file
that starts with its counts is read as ``OFF`` (it is opened as OFF only by its
``.off`` name, or when the format is forced). ``OFF`` followed by the vertex count
without a space (``OFF490 518 0``, as some collections write it) is read as
``OFF``. A binary OFF (``OFF BINARY``) is refused (``format_not_supported``, rule
``binary_off``), and so are the four-dimensional and n-dimensional variants
(``4OFF``, ``nOFF``: rule ``unsupported_variant``).
"""

import re
from array import array

from ..errors import FormatNotSupportedError, SldFormatError
from ._source import Clock
from .base import ModelDocument, ModelNode, SceneBuilder, _stem
from .obj import MeshSink, Palette, polygon_triangles, text_lines, unit_color

REVISION = 1
_KEYWORD = re.compile(rb"(ST)?(C)?(N)?(4)?(n)?OFF\Z")
_GLUED = re.compile(rb"((?:ST)?C?N?OFF)(\d+)\Z")  # a keyword and the vertex count without a space


def _tokens(raw: bytes) -> list[bytes]:
    """A line's words, a ``#`` comment left out."""
    i = raw.find(b"#")
    return (raw[:i] if i >= 0 else raw).split()


def _color(tokens: list[bytes]) -> tuple[float, float, float, float] | None:
    """Three or four numbers as a colour: 0 to 1 with a decimal point, else 0 to 255."""
    if len(tokens) not in (3, 4):
        return None
    try:
        values = [float(t) for t in tokens]
    except ValueError:
        return None
    if not any(b"." in t or b"e" in t.lower() for t in tokens):
        values = [v / 255.0 for v in values]
    if len(values) == 3:
        values.append(1.0)
    return unit_color(*values)


class OffDocument(ModelDocument):
    """One OFF file (see the module notes)."""

    format = "off"

    def __init__(self, source, *, name, path, file_info, limits, detection=None) -> None:
        super().__init__(
            source, name=name, path=path, file_info=file_info, limits=limits, detection=detection
        )
        self.doc_type = "part"
        self.kind = "mesh"
        self.set_units("mm", "assumed")
        self.warn("units_assumed", "an OFF file states no unit of length; millimetres were assumed")
        self._header(Clock(limits.seconds))

    def _header(self, clock: Clock) -> None:
        lines = text_lines(self.source, clock, self.limits.obj_line_bytes, "obj_line_bytes")
        keyword = None
        counts: list[bytes] = []
        for _n, raw in lines:
            words = _tokens(raw)
            if not words:
                continue
            if keyword is None:
                m = _KEYWORD.match(words[0])
                glued = _GLUED.match(words[0]) if m is None else None
                if glued is not None:
                    keyword, m = glued.group(1), _KEYWORD.match(glued.group(1))
                    words = [keyword, glued.group(2), *words[1:]]
                elif m is None:
                    if not (len(words) >= 2 and all(w.isdigit() for w in words[:3])):
                        raise SldFormatError(
                            "not an OFF file: it starts with neither an OFF keyword nor its counts"
                        )
                    keyword, m = b"OFF", _KEYWORD.match(b"OFF")  # the keyword is optional
                    words = [keyword, *words]
                else:
                    keyword = words[0]
                if len(words) > 1 and words[1].upper() == b"BINARY":
                    raise FormatNotSupportedError(
                        "binary OFF files are not read", detail={"rule": "binary_off", "value": "off"}
                    )
                if m.group(4) or m.group(5):
                    raise FormatNotSupportedError(
                        f"{keyword.decode('ascii')} files (more than three dimensions) are not read",
                        detail={"rule": "unsupported_variant", "value": keyword.decode("ascii")},
                    )
                counts = words[1:]
            else:
                counts += words
            if len(counts) >= 2:
                self.data_line = _n
                break
        if keyword is None or len(counts) < 2:
            raise SldFormatError("the OFF file has no vertex and face counts")
        try:
            nv, nf = int(counts[0]), int(counts[1])
        except ValueError:
            raise SldFormatError("the OFF file's counts are not whole numbers") from None
        if nv < 0 or nf < 0:
            raise SldFormatError("the OFF file's counts are negative")
        if 6 * nv + 8 * nf - 1 > self.source.size:
            raise SldFormatError("the OFF file declares more vertices and faces than it holds")
        m = _KEYWORD.match(keyword)
        self.variant = keyword.decode("ascii")
        self.has_texture = bool(m.group(1))
        self.has_color = bool(m.group(2))
        self.has_normal = bool(m.group(3))
        self.n_vertices, self.n_faces = nv, nf

    def _counts(self):
        return {"objects": 1, "items": 1, "vertices": self.n_vertices}

    # -- reading -------------------------------------------------------------------------
    def _read(self, sink: MeshSink):
        lim = self.limits
        clock = sink.clock
        positions = array("d")
        normals = array("f") if self.has_normal else None
        vcolors = array("I") if self.has_color else None
        palette = Palette(lim)
        triangles = array("I")
        ids: array | None = None
        degenerate = 0
        pending = 0
        corners_max = lim.polygon_corners
        nv, nf = self.n_vertices, self.n_faces
        lines = text_lines(self.source, clock, self.limits.obj_line_bytes, "obj_line_bytes")
        for number_, _raw in lines:
            if number_ >= self.data_line:
                break
        read_v = read_f = 0
        textures = False
        for number_, raw in lines:
            if read_v >= nv and read_f >= nf:
                break
            words = _tokens(raw)
            if not words:
                continue
            if read_v < nv:
                if len(words) < 3:
                    raise SldFormatError(f"line {number_}: a vertex is not three numbers")
                try:
                    values = [float(w) for w in words[: 6 if self.has_normal else 3]]
                except ValueError:
                    raise SldFormatError(f"line {number_}: a vertex coordinate is not a number") from None
                positions.extend(values[:3])
                rest = words[3:]
                if normals is not None:
                    if len(values) < 6:
                        raise SldFormatError(f"line {number_}: a vertex has no normal")
                    normals.extend(values[3:6])
                    rest = words[6:]
                if self.has_texture and len(rest) >= 2:
                    textures = True
                    rest = rest[:-2]
                if vcolors is not None:
                    vcolors.append(palette.id(_color(rest[:4])))
                read_v += 1
                if not read_v & 4095:
                    sink.count(0, 4096)
                continue
            n_text = words[0]
            try:
                n = int(n_text)
                corners = [int(w) for w in words[1 : n + 1]]
            except ValueError:
                raise SldFormatError(f"line {number_}: a face is not whole numbers") from None
            if n > corners_max:
                raise lim.exceeded(
                    "polygon_corners", f"line {number_}: a face has more than {corners_max:,} corners"
                )
            if len(corners) != n:
                raise SldFormatError(f"line {number_}: a face has fewer vertex numbers than it says")
            read_f += 1
            if n < 3:
                degenerate += 1
                continue
            corners = [c if 0 <= c < nv else 0xFFFFFFFF for c in corners]
            tris = [tuple(corners)] if n == 3 else polygon_triangles(positions, corners, clock)
            face_color = _color(words[n + 1 :])
            fid = -1
            if face_color is not None or vcolors is not None:
                if ids is None:
                    ids = array("I", bytes(4 * (len(triangles) // 3)))
                if face_color is not None:
                    fid = palette.id(face_color)
            for t in tris:
                triangles.extend(t)
                if ids is not None:
                    if fid >= 0:
                        ids.append(fid)
                    else:
                        a = t[0]
                        ids.append(vcolors[a] if vcolors is not None and a < len(vcolors) else 0)
            pending += len(tris)
            if pending >= 4096:
                sink.count(pending, 0)
                pending = 0
        if read_v < nv or read_f < nf:
            raise SldFormatError("the OFF file ends before its last vertex or face")
        sink.count(pending, read_v & 4095)
        if palette.overflow:
            sink.warn(
                "colors_ignored",
                f"the model has more than {lim.colors_per_object} colours; it is drawn without them",
            )
            ids = None
        if textures:
            sink.warn("textures_ignored", "texture coordinates are not read")
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
            color_ids=ids,
        )

    def _tree(self, clock: Clock):
        objs, cols = self._read(MeshSink(None, self.limits, clock))
        return [ModelNode("1", None, _stem(self.name), "object", objs[0], color=cols[0])]

    def _scene(self, sb: SceneBuilder) -> None:
        objs, _cols = self._read(MeshSink(sb, self.limits, sb.clock))
        for i in objs:
            sb.add_item(i, "1")


def open(source, *, name, path, file_info, limits, hold_open=False, detection=None) -> OffDocument:
    """Open an OFF file's :class:`~solidseas.formats._source.Source` (the registry's reader
    for ``off``)."""
    return OffDocument(source, name=name, path=path, file_info=file_info, limits=limits, detection=detection)


__all__ = ["REVISION", "OffDocument", "open"]
