"""STL, binary and ASCII: the reference model-file reader (provisional,
``docs/formats/stl.md``).

A binary STL is an 80-byte header, a little-endian 32-bit triangle count and 50
bytes a triangle: a normal and three corners as twelve float32, and a 16-bit
attribute. An ASCII STL is ``solid name``, then ``facet normal`` ...
``outer loop``, three ``vertex x y z`` lines, ``endloop``, ``endfacet`` for
each triangle, and ``endsolid``; a file may hold several solids.

Which one a file is comes from its size first: a file of exactly 84 + 50 n
bytes, n the count at bytes 80 to 83, is binary whatever its header says (most
binary STLs in the development corpus begin their header with the word
``solid``, as ASCII ones do). Otherwise a file that starts with ``solid`` is
ASCII, and anything else is read as binary only when it is at least as long as
its count says (extra bytes after the last triangle are ignored).

STL has no unit: millimetres are assumed (``units_assumed``). Normals are
ignored (they are computed again from the corners), and so are colours in the
attribute bits or a ``COLOR=`` header (``colors_ignored``). Every triangle is
three vertices of its own (a triangle soup): the export welds them. A binary
file's header becomes the property ``header``; an ASCII file's solids are its
objects, named by their ``solid`` lines.
"""

import struct

from ..errors import SldFormatError
from ._source import Clock
from .base import ModelDocument, ModelNode, SceneBuilder, make_property

REVISION = 1
HEADER_BYTES = 80
RECORD = 50
_RECORDS_A_CHUNK = 8192  # triangles unpacked at a time (400 KiB)
_CHUNK_STRUCT = struct.Struct("<" + "12x9f2x" * _RECORDS_A_CHUNK)
_ONE = struct.Struct("<12x9f2x")
_READ = 1 << 20  # ASCII bytes read at a time


def _printable(raw: bytes) -> str:
    text = raw.split(b"\0", 1)[0].decode("latin-1")
    return "".join(ch if 32 <= ord(ch) < 127 else " " for ch in text).strip()


class StlDocument(ModelDocument):
    """One STL file (see the module notes)."""

    format = "stl"

    def __init__(self, source, *, name, path, file_info, limits, detection=None) -> None:
        super().__init__(
            source, name=name, path=path, file_info=file_info, limits=limits, detection=detection
        )
        head = source.head(512)
        size = source.size
        count = struct.unpack_from("<I", head, HEADER_BYTES)[0] if len(head) >= 84 else None
        text = head.lstrip(b" \t\r\n")
        if count is not None and size == 84 + RECORD * count:
            self.variant = "binary"
        elif text[:5].lower() == b"solid":
            self.variant = "ascii"
        elif count is not None and size >= 84 + RECORD * count:
            self.variant = "binary"
        elif count is not None:
            raise SldFormatError(
                f"the STL declares {count:,} triangles but holds room for {(size - 84) // RECORD:,}"
            )
        else:
            raise SldFormatError("the file is too short to be an STL")
        self.count = count if self.variant == "binary" else None
        self.doc_type = "part"
        self.kind = "mesh"
        self.set_units("mm", "assumed")
        self.warn("units_assumed", "an STL file states no unit of length; millimetres were assumed")
        if self.variant == "binary":
            header = _printable(head[:HEADER_BYTES])
            if header:
                self.properties = [make_property("header", header)]
            if b"COLOR=" in head[:HEADER_BYTES]:
                self.warn("colors_ignored", "the header names a colour (COLOR=), which is not read")
        else:
            first = text.split(b"\n", 1)[0][5:].strip()[: limits.stl_name_bytes]
            title = _printable(first)
            if title:
                self.properties = [make_property("solid", title)]

    def _counts(self):
        if self.variant == "binary":
            return {"objects": 1, "items": 1, "triangles": self.count, "vertices": 3 * self.count}
        return {}

    def _tree(self, clock: Clock):
        if self.variant == "binary":
            return [ModelNode("1", None, self._stem(), "object", 0)]
        names = [name for name, _start in self._solids(clock)]
        return [ModelNode(str(i + 1), None, n or self._stem(), "object", i) for i, n in enumerate(names)]

    def _stem(self) -> str | None:
        from .base import _stem

        return _stem(self.name)

    # -- binary ------------------------------------------------------------------------
    def _scene(self, sb: SceneBuilder) -> None:
        if self.variant == "binary":
            self._binary(sb)
        else:
            self._ascii(sb)

    def _binary(self, sb: SceneBuilder) -> None:
        src, n = self.source, self.count
        mb = sb.mesh(name=self._stem(), scale_m=0.001, node="1")
        colored = False
        done = 0
        while done < n:
            k = min(_RECORDS_A_CHUNK, n - done)
            data = src.read_at(84 + RECORD * done, RECORD * k)
            if k == _RECORDS_A_CHUNK:
                mb.add_soup(_CHUNK_STRUCT.unpack(data))
            else:
                mb.add_soup(v for rec in _ONE.iter_unpack(data) for v in rec)
            if not colored and max(data[49::RECORD]) >= 0x80:
                colored = True
            done += k
        if colored:
            sb.warn("colors_ignored", "triangles carry colours in their attribute bits, which are not read")
        sb.add_item(mb.finish(), "1")

    # -- ASCII -----------------------------------------------------------------------------
    def _lines(self, clock: Clock):
        """``(line number, stripped line)`` of the file, each at most ``stl_line_bytes``."""
        limit = self.limits.stl_line_bytes
        rest = b""
        number = 0
        for chunk in self.source.chunks(0, None, _READ):
            clock.tick(len(chunk) // 64 or 1)
            rest += chunk
            lines = rest.split(b"\n")
            rest = lines.pop()
            if len(rest) > limit:
                raise self.limits.exceeded("stl_line_bytes", f"an STL line is longer than {limit:,} bytes")
            for line in lines:
                number += 1
                if len(line) > limit:
                    raise self.limits.exceeded(
                        "stl_line_bytes", f"line {number} is longer than {limit:,} bytes"
                    )
                yield number, line.strip()
        if rest.strip():
            yield number + 1, rest.strip()

    def _solids(self, clock: Clock):
        """The solids' names and the line each starts on, from a pass over the file."""
        out = []
        for number, line in self._lines(clock):
            if line[:5].lower() == b"solid" and (len(line) == 5 or line[5:6].isspace()):
                name = _printable(line[5:].strip()[: self.limits.stl_name_bytes])
                out.append((name or None, number))
                if len(out) > self.limits.objects:
                    raise self.limits.exceeded("objects", "the STL holds too many solids")
        return out or [(None, 1)]

    def _ascii(self, sb: SceneBuilder) -> None:
        mb = None
        corners: list[float] = []
        in_facet = False
        dropped = 0
        n_solids = 0

        def close(mb):
            if mb is not None:
                sb.add_item(mb.finish(), mb.node)

        for number, line in self._lines(sb.clock):
            if not line:
                continue
            word = line.split(None, 1)[0].lower()
            if word == b"vertex":
                parts = line.split()
                if len(parts) != 4:
                    raise SldFormatError(f"line {number}: a vertex is not three numbers")
                try:
                    corners.extend((float(parts[1]), float(parts[2]), float(parts[3])))
                except ValueError:
                    raise SldFormatError(f"line {number}: a vertex coordinate is not a number") from None
                if len(corners) > 3 * self.limits.polygon_corners:
                    raise self.limits.exceeded(
                        "polygon_corners", f"line {number}: a facet has too many corners"
                    )
            elif word == b"facet":
                corners.clear()
                in_facet = True
            elif word == b"endfacet":
                if mb is None:
                    n_solids += 1
                    mb = sb.mesh(name=self._stem(), scale_m=0.001, node=str(n_solids))
                if len(corners) == 9:
                    mb.add_soup(corners)
                else:
                    dropped += 1
                corners.clear()
                in_facet = False
            elif word == b"solid" and not in_facet:
                close(mb)
                n_solids += 1
                name = _printable(line[5:].strip()[: self.limits.stl_name_bytes]) or self._stem()
                mb = sb.mesh(name=name, scale_m=0.001, node=str(n_solids))
            elif word == b"endsolid":
                close(mb)
                mb = None
            elif word in (b"outer", b"endloop"):
                continue
            else:
                raise SldFormatError(
                    f"line {number}: {word[:20].decode('latin-1')!r} is not an STL statement"
                )
        close(mb)
        if dropped:
            sb.warn(
                "degenerate_triangles_dropped",
                f"{dropped} facets do not have three corners; they were left out",
            )


def open(source, *, name, path, file_info, limits, hold_open=False, detection=None) -> StlDocument:
    """Open an STL file's :class:`~solidseas.formats._source.Source` (the registry's
    reader for ``stl``)."""
    return StlDocument(source, name=name, path=path, file_info=file_info, limits=limits, detection=detection)


__all__ = ["REVISION", "StlDocument", "open"]
