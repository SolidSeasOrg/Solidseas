"""How a bill of materials is shown: the BOM editor's table definition (provisional).

:mod:`solidseas.bom` works out an assembly's BOM as SOLIDWORKS would. A
:class:`BomTableSpec` says how a person wants it shown, and :func:`apply` gives
the table that results. One definition serves the viewer's BOM editor, a
``.ssbom`` file of its own and an assembly drawing's parts list.

* **Type.** One of :data:`solidseas.bom.BOM_TYPES`: top level only, parts only
  or indented. The BOM is built in that type; the spec only records it.
* **Columns.** Each is one of :data:`BUILT_IN` (``item``, ``part_number``,
  ``description``, ``quantity``, ``total_quantity``, ``configuration``,
  ``file_name``) or a property, ``property:<name>``, with its heading. The
  property columns are what :func:`solidseas.bom.build_bom` is asked for
  (:meth:`BomTableSpec.property_names`).
* **Rows** are known by a key that holds across Update from Model: the row's
  file name and configuration, or its part number when it has no file, and in an
  indented BOM the keys of the sub-assemblies above it too (:func:`own_key`,
  :func:`row_keys`).
  ``order`` lists keys in the order wanted: listed rows come first in that order,
  then the rest in the BOM's own order, each sub-assembly's components staying
  under it. ``hidden`` rows are left out, with the rows under them. The ITEM
  column is numbered again down the table as shown (``1``, ``2``; ``2.1`` under
  ``2`` when indented), as SOLIDWORKS numbers a table when its rows are moved.
* **Overrides** replace one cell's text: (row key, column id) to the text shown.
  The ITEM column cannot be overridden. An override whose row is no longer in
  the BOM, or whose column is no longer shown, is kept in the spec and listed in
  :attr:`ShownTable.unused`, so the editor can say which edits no longer apply.

Nothing here reads or writes a file; :mod:`solidseas.bomfile` does.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .bom import (
    BOM_TYPES,
    DEFAULT_TYPE,
    INDENT,
    MAX_COLUMN_NAME,
    MAX_COLUMNS,
    Bom,
    BomRow,
    check_property_name,
)
from .errors import InvalidArgumentError

SPEC_VERSION = 1
BUILT_IN: dict[str, str] = {  # column id: its default heading, as SOLIDWORKS' default BOM table heads it
    "item": "ITEM NO.",
    "part_number": "PART NUMBER",
    "description": "DESCRIPTION",
    "quantity": "QTY.",
    "total_quantity": "TOTAL QTY.",
    "configuration": "CONFIGURATION",
    "file_name": "FILE NAME",
    "drawing": "DWG NO.",  # the item's own drawing number: filled on a drawing's parts list, else empty
}
NUMERIC = ("quantity", "total_quantity")
PROPERTY = "property:"
DEFAULT_COLUMNS = ("item", "part_number", "description", "quantity")
MAX_ROWS = 10_000
MAX_CELL = 1_000
MAX_OVERRIDES = 10_000


@dataclass(frozen=True)
class Column:
    """One column: its ``id`` (a key of :data:`BUILT_IN`, or ``property:<name>``) and
    the ``heading`` shown over it."""

    id: str
    heading: str

    @property
    def property_name(self) -> str | None:
        """The property a property column shows, None for a built-in column."""
        return self.id[len(PROPERTY) :] if self.id.startswith(PROPERTY) else None

    @property
    def numeric(self) -> bool:
        return self.id in NUMERIC


def column(column_id: str, heading: str | None = None) -> Column:
    """A checked :class:`Column`, with its default heading when ``heading`` is None: the
    built-in one, or the property's name in capitals."""
    if not isinstance(column_id, str):
        raise InvalidArgumentError("a column id is text", detail={"parameter": "columns"})
    if column_id.startswith(PROPERTY):
        name = check_property_name(column_id[len(PROPERTY) :], "columns", label="a property column")
        default = name.upper()
        column_id = PROPERTY + name
    elif column_id in BUILT_IN:
        default = BUILT_IN[column_id]
    else:
        raise InvalidArgumentError(
            f"{column_id!r} is not a column: use one of {', '.join(BUILT_IN)} or property:<name>",
            detail={"parameter": "columns"},
        )
    if heading is None:
        heading = default
    if not isinstance(heading, str) or len(heading) > MAX_COLUMN_NAME or any(ord(c) < 32 for c in heading):
        raise InvalidArgumentError(
            f"a heading is text of at most {MAX_COLUMN_NAME} characters on one line",
            detail={"parameter": "columns"},
        )
    return Column(column_id, heading)


@dataclass(frozen=True)
class BomTableSpec:
    """How a BOM is shown (module notes). Make one with :func:`spec` or
    :func:`spec_from_json`, which check it."""

    type: str = DEFAULT_TYPE
    columns: tuple[Column, ...] = tuple(Column(c, BUILT_IN[c]) for c in DEFAULT_COLUMNS)
    order: tuple[str, ...] = ()
    hidden: tuple[str, ...] = ()
    overrides: Mapping[tuple[str, str], str] = field(default_factory=dict)

    def property_names(self) -> tuple[str, ...]:
        """The properties the BOM must be built with, in column order."""
        return tuple(c.property_name for c in self.columns if c.property_name is not None)

    def to_json(self) -> dict[str, Any]:
        return {
            "version": SPEC_VERSION,
            "type": self.type,
            "columns": [{"id": c.id, "heading": c.heading} for c in self.columns],
            "order": list(self.order),
            "hidden": list(self.hidden),
            "overrides": [
                {"row": row, "column": col, "text": text}
                for (row, col), text in sorted(self.overrides.items())
            ],
        }


def spec(
    bom_type: str = DEFAULT_TYPE,
    columns: Iterable[Column | str | tuple[str, str]] = DEFAULT_COLUMNS,
    *,
    order: Iterable[str] = (),
    hidden: Iterable[str] = (),
    overrides: Mapping[tuple[str, str], str] | None = None,
) -> BomTableSpec:
    """A checked :class:`BomTableSpec`. A column is a :class:`Column`, a column id, or
    (id, heading). ``overrides`` maps (row key, column id) to text."""
    if bom_type not in BOM_TYPES:
        raise InvalidArgumentError(f"type is one of {', '.join(BOM_TYPES)}", detail={"parameter": "type"})
    cols: list[Column] = []
    for c in columns:
        if isinstance(c, Column):
            cols.append(column(c.id, c.heading))
        elif isinstance(c, tuple) and len(c) == 2:
            cols.append(column(c[0], c[1]))
        else:
            cols.append(column(c))
    if not cols or len(cols) > MAX_COLUMNS:
        raise InvalidArgumentError(f"a table has 1 to {MAX_COLUMNS} columns", detail={"parameter": "columns"})
    if len({c.id for c in cols}) != len(cols):
        raise InvalidArgumentError("a column is shown once", detail={"parameter": "columns"})
    keys = {"order": _keys(order, "order"), "hidden": _keys(hidden, "hidden")}
    out: dict[tuple[str, str], str] = {}
    for k, text in (overrides or {}).items():
        if not (isinstance(k, tuple) and len(k) == 2):
            raise InvalidArgumentError(
                "an override is for a (row, column)", detail={"parameter": "overrides"}
            )
        row, col = _key(k[0], "overrides"), k[1]
        if col == "item":
            raise InvalidArgumentError(
                "the item number cannot be overridden", detail={"parameter": "overrides"}
            )
        if not isinstance(col, str) or not (col in BUILT_IN or col.startswith(PROPERTY)):
            raise InvalidArgumentError(
                "an override names a column by its id", detail={"parameter": "overrides"}
            )
        out[(row, col)] = _cell(text)
    if len(out) > MAX_OVERRIDES:
        raise InvalidArgumentError(f"at most {MAX_OVERRIDES} overrides", detail={"parameter": "overrides"})
    return BomTableSpec(bom_type, tuple(cols), keys["order"], keys["hidden"], out)


def spec_from_json(data: Any) -> BomTableSpec:
    """The spec :meth:`BomTableSpec.to_json` wrote, checked as :func:`spec` checks it."""
    if not isinstance(data, dict) or data.get("version") != SPEC_VERSION:
        raise InvalidArgumentError(f"not a BOM table of version {SPEC_VERSION}", detail={"parameter": "spec"})
    try:
        columns = [(c["id"], c["heading"]) for c in data.get("columns", ())]
        overrides = {(o["row"], o["column"]): o["text"] for o in data.get("overrides", ())}
    except (TypeError, KeyError):
        raise InvalidArgumentError(
            "the BOM table's columns or overrides are malformed", detail={"parameter": "spec"}
        ) from None
    return spec(
        data.get("type"),
        columns,
        order=data.get("order", ()),
        hidden=data.get("hidden", ()),
        overrides=overrides,
    )


def _key(value: Any, parameter: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4 * MAX_COLUMN_NAME:
        raise InvalidArgumentError("a row key is the text row_keys gives", detail={"parameter": parameter})
    return value


def _keys(values: Iterable[str], parameter: str) -> tuple[str, ...]:
    out = tuple(_key(v, parameter) for v in values)
    if len(out) > MAX_ROWS or len(set(out)) != len(out):
        raise InvalidArgumentError(
            f"{parameter} lists each row once, at most {MAX_ROWS}", detail={"parameter": parameter}
        )
    return out


def _cell(text: Any) -> str:
    if not isinstance(text, str) or len(text) > MAX_CELL or any(ord(c) < 32 and c != "\n" for c in text):
        raise InvalidArgumentError(
            f"a cell holds text of at most {MAX_CELL} characters", detail={"parameter": "overrides"}
        )
    return text


# --------------------------------------------------------------------------- the table
@dataclass(frozen=True)
class SourceRow:
    """What the table reads of a BOM row, from a :class:`~solidseas.bom.BomRow` or a row
    of ``bom`` JSON (:func:`solidseas.model.bom_data`) alike; ``source`` is the row
    itself."""

    item: str
    level: int
    parent: str | None
    part_number: str
    file_name: str | None
    configuration: str | None
    quantity: int
    total_quantity: int
    description: str | None
    values: tuple[str | None, ...]
    properties: tuple[tuple[str, str, str], ...]  # (name, scope, text) of the file's effective properties
    source: Any


def _source(bom: Bom | Mapping[str, Any]) -> tuple[str, tuple[str, ...], list[SourceRow]]:
    """The BOM's type, property columns and rows, from a :class:`Bom` or ``bom`` JSON."""
    if isinstance(bom, Bom):
        return bom.type, bom.columns, [_from(r, getattr) for r in bom.rows]
    if isinstance(bom, Mapping) and isinstance(bom.get("rows"), list):
        props = tuple(bom.get("property_columns") or ())
        return bom["type"], props, [_from(r, lambda m, k: m.get(k)) for r in bom["rows"]]
    raise InvalidArgumentError("a BOM is a Bom or bom JSON", detail={"parameter": "bom"})


def _from(r: Any, get) -> SourceRow:
    return SourceRow(
        get(r, "item"),
        get(r, "level") or 0,
        get(r, "parent"),
        get(r, "part_number") or "",
        get(r, "file_name"),
        get(r, "configuration"),
        get(r, "quantity") or 0,
        get(r, "total_quantity") or 0,
        get(r, "description"),
        tuple(get(r, "values") or ()),
        tuple(_props(get(r, "properties"))),
        r,
    )


def _props(found: Any) -> list[tuple[str, str, str]]:
    out = []
    for p in found or ():
        if isinstance(p, Mapping):
            name, scope, text = p.get("name"), p.get("scope"), p.get("text")
        else:
            name, scope, text = getattr(p, "name", None), getattr(p, "scope", None), getattr(p, "text", None)
        if isinstance(name, str) and isinstance(text, str):
            out.append((name, scope or "file", text))
    return out


def property_names(bom: Bom | Mapping[str, Any]) -> list[str]:
    """Every property name the BOM's rows have, in the order first met, compared as
    SOLIDWORKS compares them (without regard to case): what a property column can show."""
    _type, props, rows = _source(bom)
    seen: dict[str, str] = {}
    for name in props:
        seen.setdefault(name.casefold(), name)
    for r in rows:
        for name, _scope, _text in r.properties:
            seen.setdefault(name.casefold(), name)
    return list(seen.values())


def own_key(row: SourceRow | BomRow) -> str:
    """A row's own part of its key: its file's name (compared as Windows compares names)
    and configuration, or its part number when it has no file name. Not the file key,
    which numbers the assembly's references and can change when a component is added."""
    name = row.file_name.casefold() if row.file_name else "#" + row.part_number
    return f"{name}|{row.configuration or ''}"


def _keys_of(bom_type: str, rows: list[SourceRow]) -> dict[str, str]:
    keys: dict[str, str] = {}
    for r in rows:
        own = own_key(r)
        above = keys.get(r.parent) if bom_type == "indented" and r.parent is not None else None
        keys[r.item] = f"{above}/{own}" if above else own
    return keys


def row_keys(bom: Bom | Mapping[str, Any]) -> dict[str, str]:
    """Each row's key (module notes) by its item number: in an indented BOM, the keys
    of the rows above it and its own, joined by ``/``. ``bom`` is a :class:`Bom` or
    ``bom`` JSON."""
    bom_type, _props, rows = _source(bom)
    return _keys_of(bom_type, rows)


@dataclass(frozen=True)
class ShownRow:
    """A row as shown: its ``key``, the BOM row it shows (``row.source`` is the
    :class:`~solidseas.bom.BomRow` or JSON row given), the ``item`` number it is shown
    with, its ``level``, the text of each cell and whether each cell's text is an
    override."""

    key: str
    row: SourceRow
    item: str
    level: int
    cells: tuple[str, ...]
    overridden: tuple[bool, ...]


@dataclass(frozen=True)
class ShownTable:
    """The table a spec gives for a BOM: the ``columns`` and their headings, the rows
    shown, the keys of rows hidden, and ``unused``: the overrides (row key, column id)
    whose row or column is not in the table."""

    type: str
    columns: tuple[Column, ...]
    rows: tuple[ShownRow, ...]
    hidden: tuple[str, ...]
    unused: tuple[tuple[str, str], ...]

    def headings(self) -> list[str]:
        return [c.heading for c in self.columns]

    def cells(self) -> list[list[str]]:
        """The headings, then each row's cells: what every export writes."""
        return [self.headings(), *(list(r.cells) for r in self.rows)]


def _value(bom_type: str, props: tuple[str, ...], row: SourceRow, c: Column, item: str) -> str:
    if c.id == "item":
        return item
    if c.id == "part_number":
        indent = INDENT * row.level if bom_type == "indented" else ""
        return indent + row.part_number
    if c.id == "description":
        return row.description or ""
    if c.id == "quantity":
        return str(row.quantity)
    if c.id == "total_quantity":
        return str(row.total_quantity)
    if c.id == "configuration":
        return row.configuration or ""
    if c.id == "file_name":
        return row.file_name or ""
    if c.id == "drawing":
        return ""  # an assembly drawing's plan fills it (solidseas.drawing.plan.assembly)
    want = (c.property_name or "").casefold()
    names = [n.casefold() for n in props]
    if want in names and names.index(want) < len(row.values):
        return row.values[names.index(want)] or ""
    # not built as a column: the row's own properties, the configuration's before the file's
    found = sorted(
        (scope != "configuration", text) for name, scope, text in row.properties if name.casefold() == want
    )
    return found[0][1] if found else ""


def apply(table_spec: BomTableSpec, bom: Bom | Mapping[str, Any]) -> ShownTable:
    """The table ``table_spec`` gives for ``bom`` (a :class:`Bom` or ``bom`` JSON; module
    notes). ``bom`` should be built in the spec's type with its property columns; a
    property column the BOM lacks is shown empty."""
    bom_type, props, rows = _source(bom)
    keys = _keys_of(bom_type, rows)
    by_key = {keys[r.item]: r for r in rows}
    position = {r.item: i for i, r in enumerate(rows)}
    children: dict[str | None, list[SourceRow]] = {}
    for r in rows:
        parent = r.parent if bom_type == "indented" else None
        children.setdefault(parent, []).append(r)
    rank = {k: i for i, k in enumerate(table_spec.order)}
    hidden_set = set(table_spec.hidden)
    shown: list[ShownRow] = []
    hidden: list[str] = []

    def walk(parent: str | None, prefix: str) -> None:
        group = sorted(
            children.get(parent, []), key=lambda r: (rank.get(keys[r.item], len(rank)), position[r.item])
        )
        n = 0
        for r in group:
            k = keys[r.item]
            if k in hidden_set:
                hidden.append(k)
                continue
            n += 1
            item = f"{prefix}{n}"
            cells, overridden = [], []
            for c in table_spec.columns:
                text = table_spec.overrides.get((k, c.id))
                overridden.append(text is not None)
                cells.append(text if text is not None else _value(bom_type, props, r, c, item))
            shown.append(ShownRow(k, r, item, r.level, tuple(cells), tuple(overridden)))
            if bom_type == "indented":
                walk(r.item, item + ".")

    walk(None, "")
    column_ids = {c.id for c in table_spec.columns}
    unused = tuple(
        sorted((row, col) for row, col in table_spec.overrides if row not in by_key or col not in column_ids)
    )
    return ShownTable(bom_type, table_spec.columns, tuple(shown), tuple(hidden), unused)


__all__ = [
    "BUILT_IN",
    "DEFAULT_COLUMNS",
    "NUMERIC",
    "PROPERTY",
    "SPEC_VERSION",
    "BomTableSpec",
    "Column",
    "ShownRow",
    "ShownTable",
    "SourceRow",
    "apply",
    "column",
    "own_key",
    "property_names",
    "row_keys",
    "spec",
    "spec_from_json",
]
