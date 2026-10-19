"""A test-only reader of the ASCII DXF the drawing writer makes (docs/DRAWINGS.md 19.2).

It reads tags (pairs of group code and value), splits them into sections, tables
and their entries, blocks with their entities, the ENTITIES and the OBJECTS,
and knows each record's handle (group 5, or 105 for a dimension style) and owner
(the first 330 outside a ``{...}`` group). It is strict where the writer must be:
the file is ASCII, uses one line ending throughout, has an even number of lines,
every group code is a number, and the sections come in order and end with EOF.
Helpers find entities by type and layer and collect every handle reference, so
the tests check that handles are unique and every reference resolves.

It is not a general DXF reader: no binary DXF, no R12, no interpretation beyond
what the tests ask.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

SECTIONS = ("HEADER", "CLASSES", "TABLES", "BLOCKS", "ENTITIES", "OBJECTS")
# Group codes whose value is a handle another record must have.
POINTER_CODES = (330, 331, 340, 350, 360, 390)


class DxfError(ValueError):
    """The file is not one this reader takes."""


@dataclass(frozen=True)
class Tag:
    code: int
    value: str

    def number(self) -> float:
        return float(self.value)


@dataclass
class Record:
    """One record: its type (the value of its 0 tag) and the tags after it."""

    type: str
    tags: list[Tag]

    def get(self, code: int, default: str | None = None) -> str | None:
        for t in self.tags:
            if t.code == code:
                return t.value
        return default

    def all(self, code: int) -> list[str]:
        return [t.value for t in self.tags if t.code == code]

    def float(self, code: int, default: float | None = None) -> float | None:
        v = self.get(code)
        return default if v is None else float(v)

    def int(self, code: int, default: int | None = None) -> int | None:
        v = self.get(code)
        return default if v is None else int(v)

    def point(self, code: int) -> tuple[float, float]:
        return (float(self.get(code)), float(self.get(code + 10)))

    def points(self, code: int = 10) -> list[tuple[float, float]]:
        """Every (x, y) given as repeated ``code`` and ``code + 10`` pairs."""
        xs = [float(t.value) for t in self.tags if t.code == code]
        ys = [float(t.value) for t in self.tags if t.code == code + 10]
        return list(zip(xs, ys, strict=False))

    @property
    def handle(self) -> str | None:
        return self.get(105 if self.type == "DIMSTYLE" else 5)

    @property
    def owner(self) -> str | None:
        depth = 0
        for t in self.tags:
            if t.code == 102:
                depth += 1 if t.value.startswith("{") else -1
            elif t.code == 330 and depth == 0:
                return t.value
        return None

    @property
    def layer(self) -> str | None:
        return self.get(8)

    def xdata(self, app: str = "ACAD") -> list[Tag]:
        """The extended data of ``app`` (the tags after ``1001 app``)."""
        out: list[Tag] = []
        inside = False
        for t in self.tags:
            if t.code == 1001:
                inside = t.value == app
                continue
            if inside and t.code >= 1000:
                out.append(t)
        return out

    def dimstyle_overrides(self) -> dict[int, str]:
        """A DIMENSION's ``ACAD`` ``DSTYLE`` overrides: dimension variable code to value."""
        tags = self.xdata()
        out: dict[int, str] = {}
        values = [t for t in tags if t.code not in (1000, 1002)]
        for i in range(0, len(values) - 1, 2):
            out[int(values[i].value)] = values[i + 1].value
        return out

    @property
    def text(self) -> str:
        """An MTEXT's whole string (its 3 groups, then its 1), or a TEXT's value."""
        return "".join(self.all(3)) + (self.get(1) or "") if self.type == "MTEXT" else (self.get(1) or "")


@dataclass
class Table:
    name: str
    header: Record
    entries: list[Record] = field(default_factory=list)

    def names(self) -> list[str]:
        return [e.get(2) for e in self.entries]

    def entry(self, name: str) -> Record | None:
        for e in self.entries:
            if (e.get(2) or "").upper() == name.upper():
                return e
        return None


@dataclass
class Block:
    name: str
    begin: Record
    entities: list[Record]
    end: Record


@dataclass
class Document:
    comments: list[str]
    header: dict[str, list[Tag]]
    classes: list[Record]
    tables: dict[str, Table]
    blocks: dict[str, Block]
    entities: list[Record]
    objects: list[Record]
    sections: list[str]
    line_ending: str
    tag_count: int

    def var(self, name: str) -> str | None:
        """A header variable's first value."""
        tags = self.header.get(name)
        return tags[0].value if tags else None

    def records(self) -> list[Record]:
        """Every record that can carry a handle: tables, entries, blocks and their
        entities, the entities and the objects."""
        out: list[Record] = []
        for table in self.tables.values():
            out.append(table.header)
            out += table.entries
        for block in self.blocks.values():
            out += [block.begin, *block.entities, block.end]
        out += self.entities
        out += self.objects
        return out

    def handles(self) -> list[str]:
        return [r.handle for r in self.records() if r.handle is not None]

    def by_handle(self) -> dict[str, Record]:
        return {r.handle: r for r in self.records() if r.handle is not None}

    def references(self) -> list[tuple[Record, int, str]]:
        """Every handle a record points to: (record, code, handle)."""
        out = []
        for r in self.records():
            for t in r.tags:
                if t.code in POINTER_CODES:
                    out.append((r, t.code, t.value))
        return out

    def find(self, type: str | None = None, layer: str | None = None, where=None) -> list[Record]:
        """Model-space entities (or ``where``'s) of a type and layer."""
        pool = self.entities if where is None else where
        return [e for e in pool if (type is None or e.type == type) and (layer is None or e.layer == layer)]

    def block_of(self, entity: Record) -> Block:
        """The block a DIMENSION or INSERT names."""
        return self.blocks[entity.get(2)]


def read_tags(data: bytes) -> tuple[list[Tag], str]:
    """The tags of an ASCII DXF and its line ending."""
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise DxfError(f"the file is not ASCII: {exc}") from None
    ending = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(ending)
    if lines and lines[-1] == "":
        lines.pop()
    for line in lines:
        if "\r" in line or "\n" in line:
            raise DxfError("the file mixes line endings or has a line break inside a value")
    if len(lines) % 2:
        raise DxfError("the file has an odd number of lines")
    tags = []
    for i in range(0, len(lines), 2):
        try:
            code = int(lines[i].strip())
        except ValueError:
            raise DxfError(f"line {i + 1} is not a group code: {lines[i]!r}") from None
        tags.append(Tag(code, lines[i + 1]))
    return tags, ending


def _records(tags: list[Tag]) -> tuple[list[str], list[Record]]:
    comments = []
    records: list[Record] = []
    for t in tags:
        if t.code == 999:
            comments.append(t.value)
        elif t.code == 0:
            records.append(Record(t.value, []))
        elif not records:
            raise DxfError("a tag comes before the first record")
        else:
            records[-1].tags.append(t)
    return comments, records


def read(data: bytes) -> Document:
    tags, ending = read_tags(data)
    comments, records = _records(tags)
    if not records or records[-1].type != "EOF":
        raise DxfError("the file does not end with EOF")
    doc = Document(comments, {}, [], {}, {}, [], [], [], ending, len(tags))
    i = 0
    n = len(records) - 1
    while i < n:
        rec = records[i]
        if rec.type != "SECTION":
            raise DxfError(f"expected a SECTION, found {rec.type}")
        name = rec.get(2)
        doc.sections.append(name)
        i += 1
        body = []
        while i < n and records[i].type != "ENDSEC":
            body.append(records[i])
            i += 1
        if i >= n:
            raise DxfError(f"section {name} has no ENDSEC")
        i += 1
        if name == "HEADER":
            current = None
            for t in rec.tags[1:]:
                if t.code == 9:
                    current = t.value
                    doc.header[current] = []
                elif current is None:
                    raise DxfError("a header value comes before its variable")
                else:
                    doc.header[current].append(t)
        elif name == "CLASSES":
            doc.classes = body
        elif name == "TABLES":
            table = None
            for r in body:
                if r.type == "TABLE":
                    table = Table(r.get(2), r)
                elif r.type == "ENDTAB":
                    if table is None:
                        raise DxfError("ENDTAB without TABLE")
                    doc.tables[table.name] = table
                    table = None
                elif table is None:
                    raise DxfError(f"a {r.type} outside a table")
                else:
                    table.entries.append(r)
        elif name == "BLOCKS":
            begin = None
            inner: list[Record] = []
            for r in body:
                if r.type == "BLOCK":
                    if begin is not None:
                        raise DxfError("a BLOCK inside a block")
                    begin, inner = r, []
                elif r.type == "ENDBLK":
                    if begin is None:
                        raise DxfError("ENDBLK without BLOCK")
                    block = Block(begin.get(2), begin, inner, r)
                    if block.name in doc.blocks:
                        raise DxfError(f"block {block.name} is defined twice")
                    doc.blocks[block.name] = block
                    begin = None
                elif begin is None:
                    raise DxfError(f"a {r.type} outside a block")
                else:
                    inner.append(r)
        elif name == "ENTITIES":
            doc.entities = body
        elif name == "OBJECTS":
            doc.objects = body
        else:
            raise DxfError(f"unknown section {name}")
    return doc


# --------------------------------------------------------------------------- helpers for the tests


def length(entity: Record) -> float:
    """A LINE's length."""
    (x0, y0), (x1, y1) = entity.point(10), entity.point(11)
    return math.hypot(x1 - x0, y1 - y0)


def drawn(doc: Document) -> list[Record]:
    """Every entity: model space and every block's."""
    out = list(doc.entities)
    for block in doc.blocks.values():
        out += block.entities
    return out


def used_layers(doc: Document) -> set[str]:
    out = {e.layer for e in drawn(doc)}
    for block in doc.blocks.values():
        out |= {block.begin.layer, block.end.layer}
    return out


def used_linetypes(doc: Document) -> set[str]:
    out = {e.get(6) for e in drawn(doc) if e.get(6) is not None}
    return out | {layer.get(6) for layer in doc.tables["LAYER"].entries}


def used_styles(doc: Document) -> set[str]:
    return {e.get(7) for e in drawn(doc) if e.type in ("TEXT", "MTEXT")}


__all__ = [
    "Block",
    "Document",
    "DxfError",
    "Record",
    "Table",
    "Tag",
    "drawn",
    "length",
    "read",
    "read_tags",
    "used_layers",
    "used_linetypes",
    "used_styles",
]
