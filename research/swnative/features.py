"""Read and edit the feature records of ``Contents/Config-<n>-ResolvedFeatures``.

The stream holds a part's feature tree as MFC ``CArchive`` output
(``docs/NATIVE_SLDPRT_WRITER.md`` section 4 has the layout and its evidence):
a u32 and a u16 header (the u16 is the number of top-level features), then one
object per feature, each starting with its class (a new-class record ``FF FF``
or a class reference) and a named node: a class reference (``04 80`` in most
files) and a ``CString`` name.

This module finds what the experiments edit, by structure rather than by fixed
offsets: class records, named nodes, driving parameters (``D1`` of a feature)
and sketch point records. It changes doubles in place and never moves bytes, so
the object map of the archive stays valid.
"""

import math
import re
import struct
from dataclasses import dataclass, field

_NAME = re.compile(rb"[A-Za-z_][A-Za-z0-9_]*\Z")
_CLASS = re.compile(rb"\xff\xff(..)(..)", re.S)
_PARAM_NAME = re.compile(r"D\d+\Z")
# Every driving parameter seen stores its value this many bytes after its name.
PARAM_VALUE_GAP = 22
_PARAM_GAP_BYTES = bytes.fromhex("00000000000000 40 ffffffff 00000000 fffeff 000000".replace(" ", ""))
# A sketch point: this run, then x and y as doubles in metres.
_POINT_PREFIX = bytes.fromhex("f03f" + "00" * 8 + "1e00")


class FeatureStreamError(ValueError):
    """The stream does not have the structure an edit relies on."""


@dataclass(frozen=True)
class ClassRecord:
    offset: int
    schema: int
    name: str


@dataclass(frozen=True)
class NamedNode:
    offset: int  # of the 04 80 tag
    name: str
    end: int  # first byte after the name
    record: str | None  # the class record the node is in


@dataclass(frozen=True)
class Parameter:
    """A driving dimension's stored value: ``name@feature`` as SOLIDWORKS names it."""

    name: str
    feature: str | None
    value_offset: int
    value: float

    @property
    def full_name(self) -> str:
        return f"{self.name}@{self.feature}" if self.feature else self.name


@dataclass(frozen=True)
class SketchPoint:
    offset: int  # of x; y follows
    x: float
    y: float
    record: str | None


def header(data: bytes) -> tuple[int, int]:
    """The stream's leading u32 and its top-level feature count."""
    if len(data) < 6:
        raise FeatureStreamError("stream too short for its header")
    return struct.unpack_from("<IH", data, 0)


def class_records(data: bytes) -> list[ClassRecord]:
    out = []
    for m in _CLASS.finditer(data):
        schema, n = struct.unpack("<HH", m.group(1) + m.group(2))
        name = data[m.end() : m.end() + n]
        if 3 <= n <= 64 and _NAME.match(name):
            out.append(ClassRecord(m.start(), schema, name.decode("ascii")))
    return out


def _record_at(records: list[ClassRecord], offset: int) -> str | None:
    best = None
    for r in records:
        if r.offset > offset:
            break
        best = r.name
    return best


def name_tag(data: bytes, records: list[ClassRecord] | None = None) -> bytes:
    """The class reference a named node starts with: the two bytes after the first class's name.

    It is ``04 80`` in most fixtures and ``05 80`` in the two with an imported body, so it
    names a class the stream does not define itself (section 4.6 of the design document).
    """
    records = class_records(data) if records is None else records
    if not records:
        raise FeatureStreamError("no class record")
    first = records[0]
    at = first.offset + 6 + len(first.name)
    tag = data[at : at + 2]
    if len(tag) != 2 or not tag[1] & 0x80 or data[at + 2 : at + 5] != b"\xff\xfe\xff":
        raise FeatureStreamError("the first feature is not a named node")
    return tag


@dataclass
class ObjectMap:
    """The ``CArchive`` load-map indices a feature stream's class references use.

    ``Contents/Config-0`` and ``Config-0-ResolvedFeatures`` are one archive:
    numbering starts in ``Config-0`` at the named-node tag's index minus 2,
    counts the MFC way (a new class takes the next index and its object the one
    after; a reference to a known class takes one for its new object), and
    reaches the feature stream's header u32 exactly at the end of ``Config-0``
    (section 4.6 of the design document). ``classes`` maps index to class name;
    ``count`` is the next index; ``references`` lists ``(offset, index)`` for the
    class references seen in the walked stream.
    """

    classes: dict[int, str]
    count: int
    references: list[tuple[int, int]] = field(default_factory=list)

    def walk(self, data: bytes, start: int = 0, end: int | None = None) -> "ObjectMap":
        """Continue the numbering over ``data[start:end]``; return the map after it."""
        end = len(data) if end is None else end
        classes, count, refs = dict(self.classes), self.count, []
        i = start
        while i < end - 1:
            if data[i] == 0xFF and data[i + 1] == 0xFF and i + 6 <= end:
                n = struct.unpack_from("<H", data, i + 4)[0]
                name = data[i + 6 : i + 6 + n]
                if 3 <= n <= 64 and _NAME.match(name):
                    classes[count] = name.decode("ascii")
                    count += 2
                    i += 6 + n
                    continue
            (v,) = struct.unpack_from("<H", data, i)
            if 0x8000 < v < 0xFFFF and (v & 0x7FFF) in classes:
                refs.append((i, v & 0x7FFF))
                count += 1
                i += 2
                continue
            i += 1
        return ObjectMap(classes, count, refs)

    def index_of(self, name: str) -> int | None:
        for k, v in self.classes.items():
            if v == name:
                return k
        return None


def object_map(config: bytes, features: bytes) -> tuple[ObjectMap, ObjectMap]:
    """The map at the end of ``Config-<n>`` and at the end of its feature stream.

    The walk is a scan: it takes any ``0x80xx`` that names a known class as a
    reference, so it can see one inside other data. Its check is that the map
    after ``Config-<n>`` must equal the feature stream's header.
    """
    tag = name_tag(features)
    after_config = ObjectMap({}, tag[0] - 2).walk(config)
    first, _count = header(features)
    if after_config.count != first:
        raise FeatureStreamError(
            f"the map after the configuration stream is {after_config.count}, the feature stream says {first}"
        )
    return after_config, after_config.walk(features, 6)


def named_nodes(data: bytes, records: list[ClassRecord] | None = None) -> list[NamedNode]:
    records = class_records(data) if records is None else records
    pattern = re.compile(re.escape(name_tag(data, records) + b"\xff\xfe\xff") + b"([\x01-\xfe])", re.S)
    out = []
    for m in pattern.finditer(data):
        n = m.group(1)[0]
        raw = data[m.end() : m.end() + 2 * n]
        if len(raw) != 2 * n:
            continue
        try:
            name = raw.decode("utf-16-le")
        except UnicodeDecodeError:
            continue
        if not name.isprintable():
            continue
        out.append(NamedNode(m.start(), name, m.end() + 2 * n, _record_at(records, m.start())))
    return out


def parameters(data: bytes) -> list[Parameter]:
    """Every driving parameter (``D<n>``), with the feature it follows in the stream."""
    records = class_records(data)
    owner = None
    out = []
    for node in named_nodes(data, records):
        if not _PARAM_NAME.match(node.name):
            owner = node.name
            continue
        at = node.end + PARAM_VALUE_GAP
        if data[node.end : at] != _PARAM_GAP_BYTES or at + 8 > len(data):
            continue
        (value,) = struct.unpack_from("<d", data, at)
        if math.isfinite(value):
            out.append(Parameter(node.name, owner, at, value))
    return out


def parameter(data: bytes, full_name: str) -> Parameter:
    found = [p for p in parameters(data) if p.full_name == full_name]
    if len(found) != 1:
        raise FeatureStreamError(f"{full_name}: {len(found)} parameters of that name")
    return found[0]


def sketch_points(data: bytes, start: int = 0, end: int | None = None) -> list[SketchPoint]:
    records = class_records(data)
    end = len(data) if end is None else end
    out = []
    i = data.find(_POINT_PREFIX, start, end)
    while i >= 0:
        at = i + len(_POINT_PREFIX)
        if at + 16 <= len(data):
            x, y = struct.unpack_from("<dd", data, at)
            if math.isfinite(x) and math.isfinite(y):
                out.append(SketchPoint(at, x, y, _record_at(records, at)))
        i = data.find(_POINT_PREFIX, i + 1, end)
    return out


def feature_span(data: bytes, name: str) -> tuple[int, int]:
    """Offsets from a feature's named node to the next top-level feature's (or the end)."""
    nodes = [n for n in named_nodes(data) if not _PARAM_NAME.match(n.name)]
    for i, n in enumerate(nodes):
        if n.name == name:
            return n.offset, nodes[i + 1].offset if i + 1 < len(nodes) else len(data)
    raise FeatureStreamError(f"no feature named {name!r}")


def doubles_equal_to(data: bytes, value: float, start: int, end: int) -> list[int]:
    pat = struct.pack("<d", value)
    out, i = [], data.find(pat, start, end)
    while i >= 0:
        out.append(i)
        i = data.find(pat, i + 1, end)
    return out


def set_doubles(data: bytes, edits: dict[int, float]) -> bytes:
    """``data`` with the double at each offset replaced; the length never changes."""
    out = bytearray(data)
    for off, value in sorted(edits.items()):
        if off < 0 or off + 8 > len(out):
            raise FeatureStreamError(f"offset {off} outside the stream")
        out[off : off + 8] = struct.pack("<d", value)
    return bytes(out)
