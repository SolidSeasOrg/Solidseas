"""Bills of materials from an assembly's component tree (provisional, ``docs/API.md`` 3.16).

:func:`build_bom` turns one configuration of an assembly's component tree
(:meth:`Document.components`) into the rows of a bill of materials, grouped,
counted and numbered as SOLIDWORKS groups, counts and numbers the rows of a BOM
table, with each row's PART NUMBER and DESCRIPTION worked out as SOLIDWORKS'
default BOM template works them out. ``docs/FORMAT.md`` 12.7 holds the evidence;
fixture o19 carries SOLIDWORKS' own top-level and indented tables of o16, and
``tests/test_bom.py`` checks both cell by cell.

* **Which instances count.** An instance is in the BOM when it is neither
  suppressed nor excluded from the BOM, and no sub-assembly above it is either:
  a sub-assembly excluded from the BOM takes its components with it (the
  ``instances_in_bom`` rule of the component tree, ``docs/API.md`` 3.9).
* **Rows.** The instances under one parent that use the same file in the same
  configuration are one row, in the order the tree first lists them. VERIFIED on
  o19: o16's three instances of o07 (one stored before o09, two made by a
  component pattern and stored after the virtual part) are one row at the place
  of the first, and its excluded instance of o02 and suppressed one of o07 are in
  no row. That two configurations of one part are two rows is SOLIDWORKS' default
  ("display configurations of the same part as separate items"): a HYPOTHESIS, as
  no fixture uses one part in two configurations.
* **Types.** ``top`` (top-level only): the top assembly's own instances,
  sub-assemblies as single rows. ``indented``: each sub-assembly's row followed by
  its components' rows, one level deeper, numbered ``3.1``, ``3.2``... under item
  ``3``, gathered from every instance of the sub-assembly (which all list the same
  components, one ``swModel`` per file and configuration; a damaged tree where they
  differ gets ``bom_children_differ``). ``parts`` (parts only): every part at every
  level, sub-assemblies left out, one row per file and configuration across the
  whole assembly. VERIFIED on o19 for the first two; ``parts`` is built by the same
  rules, and every rule of it (order, grouping, quantities) is a HYPOTHESIS, as no
  SOLIDWORKS parts-only table has been compared.
* **QTY.** The number of instances in the row, per one instance of the parent
  assembly, as SOLIDWORKS shows it; ``total_quantity`` multiplies it through the
  parents, which is what the whole assembly needs. They are equal on o19, where
  the only sub-assembly is used once, so that the indented QTY. is per parent is a
  HYPOTHESIS (SOLIDWORKS' documented default).
* **PART NUMBER** is the document name: the file name without its extension, so
  ``Part12^o16_asm_features`` for o16's virtual part. VERIFIED on all 16 rows of
  o19's two tables (7 documents), two of which have properties that do not feed
  it: o06's ``PartNo`` and o09's ``Part Number`` (written by its STEP import). A
  configuration can tell SOLIDWORKS to show its configuration name or a name the
  user typed instead.
  The assembly's tree stores an alternate name for a configuration
  (``swConfigurationAlternateName`` of its model, :attr:`BomRow.alternate_name`),
  but no fixture has one and where the choice to show it is stored is UNKNOWN, so
  the document name stays the part number and a row whose configuration has an
  alternate name that differs gets the note ``bom_part_number_may_differ``.
  ``part_number_property`` (an option for integrations that keep their number in
  a property) takes the number from that property instead, configuration first,
  then the file, and the document name when neither has it.
* **DESCRIPTION** is the property ``Description`` of the row's file in the row's
  configuration: the configuration's own property, else the file's, names
  compared case-insensitively (:meth:`Document.effective_properties`). VERIFIED on
  o19: o06 used in its configuration OracleAlt, which has no ``Description`` of
  its own, shows the file's "Oracle test box"; the 6 rows whose files have none
  are empty. That a configuration's own ``Description`` wins is a HYPOTHESIS (no
  fixture has one).
* **Indentation.** In an indented table SOLIDWORKS indents the PART NUMBER cell
  by two spaces a level (``"  o02_boxA"`` at level 1, VERIFIED on o19);
  :func:`table` does the same. Deeper levels and whether other columns are
  indented are a HYPOTHESIS.

Each row's file is read for its properties: a virtual component, or an imported
one stored in the assembly, from the nested document inside the assembly; a
virtual component of a sub-assembly from inside that sub-assembly's document;
any other from the file reference resolution (:mod:`solidseas.resolve`) finds in
``roots``, opened read-only ``within`` its root (or its own folder outside the
roots), reading only the streams it needs, and closed once read; a sub-assembly
that stores a document a row needs stays open until the end. A file that cannot
be found or read still gets its row, with what the assembly knows (part number,
quantity, configuration, stored path) and a note saying why the rest is unknown.
The options that go to reference resolution are checked first, and a root that
cannot be walked raises as :func:`solidseas.resolve.resolve_references` raises.

Limits: ``max_instances`` and ``max_depth`` bound the component tree (a tree a
limit cut gives lower bounds, and ``truncated``), ``max_files`` the files opened
from disk (those reference resolution opens to read their identity included),
``max_seconds`` the time spent finding and reading them (resolution
included) and ``max_file_bytes`` the size of a file opened. A row a limit stopped
is noted like any other unread row. Nothing is written.
"""

import csv
import io
import os
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from .errors import ConfigurationNotFoundError, InvalidArgumentError, ReaderWarning
from .formats.solidworks.components import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_NODES,
    MAX_DEPTH_LIMIT,
    MAX_NODES_LIMIT,
    ComponentNode,
)
from .formats.solidworks.metadata import Property
from .resolve.core import Location, Resolution
from .roots import Root, Roots

BOM_TYPES = ("top", "parts", "indented")
TYPE_NAMES = {"top": "top-level only", "parts": "parts only", "indented": "indented"}
COLUMNS = ("ITEM NO.", "PART NUMBER", "DESCRIPTION", "QTY.")
DESCRIPTION_PROPERTY = "Description"
INDENT = "  "  # a level of indentation in an indented table's PART NUMBER cell
DEFAULT_TYPE = "top"  # SOLIDWORKS' own default for a new BOM table
DEFAULT_MAX_FILES = 2_000
DEFAULT_MAX_SECONDS = 60.0
MAX_COLUMNS = 64
MAX_COLUMN_NAME = 256
DOCUMENT_ROOT_ID = "document"  # as solidseas.resolve names the document's own folder
_FOUND = ("resolved", "moved")
_NOT_STORED = "it is stored in the assembly, but the assembly does not hold it"
_CUT_STATES = ("truncated", "cycle", "unknown")

Opener = Callable[[str, str], Any]


# --------------------------------------------------------------------------- results
@dataclass(frozen=True)
class BomRow:
    """One row of a bill of materials.

    ``item`` is the item number as SOLIDWORKS writes it (``"3.1"``), ``level`` 0 for
    a row of the top assembly and one more for each sub-assembly above, ``parent``
    the item of the row above it in an indented BOM. ``alternate_name`` is the
    alternate name the assembly's tree stores for the row's configuration, which
    SOLIDWORKS may show as the part number (None when it stores none). ``quantity``
    counts the row's instances under one instance of its parent (the QTY. column)
    and ``total_quantity`` in the whole assembly. ``file`` is the file key (C7) and
    ``configuration`` the configuration the instances use. ``instances`` are the
    component tree ids of every instance the row stands for.

    ``properties`` are the file's effective properties in ``configuration``, None
    when they were not read (``notes`` say why); ``values`` holds one text per
    requested property column, None where the property is absent or unread.
    ``location`` is the file on disk that was read (for a document stored inside a
    sub-assembly, that sub-assembly's file), None for the assembly itself or when
    nothing was read, and ``nested`` the nested-document streams followed from
    there. ``resolution`` is the file's resolution status, or for a stored
    document ``embedded``, ``embedded_in_subassembly`` or ``embedded_not_found``.
    """

    item: str
    level: int
    parent: str | None
    part_number: str
    part_number_source: str
    alternate_name: str | None
    description: str | None
    quantity: int
    total_quantity: int
    file: str | None
    file_name: str | None
    stored_path: str | None
    doc_type: str | None
    configuration: str | None
    virtual: bool
    imported: bool
    instances: tuple[str, ...]
    resolution: str | None
    location: Location | None
    nested: tuple[str, ...]
    properties: tuple[Property, ...] | None
    values: tuple[str | None, ...]
    notes: tuple[ReaderWarning, ...]


@dataclass(frozen=True)
class Bom:
    """A bill of materials of one assembly configuration.

    ``type`` is one of :data:`BOM_TYPES`; ``configuration`` and
    ``configuration_source`` are the component tree's. ``columns`` are the
    property columns asked for, after the four of :data:`COLUMNS`. ``complete`` is
    true when nothing is missing or in doubt: the tree was not cut by a limit,
    every row's file was read (when ``read_properties``), no folder index was cut
    short, no sub-assembly's components are missing or differ between its
    instances, and no row's part number may differ from SOLIDWORKS'. ``counts``
    holds ``rows``, ``instances`` (in the rows), ``files`` (distinct), ``read`` and
    ``unread`` (rows), ``files_opened`` and ``seconds``."""

    type: str
    configuration: str | None
    configuration_source: str
    children_state: str
    columns: tuple[str, ...]
    part_number_property: str | None
    read_properties: bool
    rows: tuple[BomRow, ...]
    truncated: bool
    complete: bool
    counts: dict[str, Any]
    limits: dict[str, Any]
    resolution: Resolution | None
    warnings: tuple[ReaderWarning, ...]

    def table(self) -> list[list[str]]:
        """The cells of the table SOLIDWORKS would draw: :data:`COLUMNS` and the
        property columns as the first row, then one row of text per BOM row."""
        return table_cells(self.type, self.columns, [_row_cells(r) for r in self.rows])


def _row_cells(r: BomRow) -> dict[str, Any]:
    return {
        "item": r.item,
        "level": r.level,
        "part_number": r.part_number,
        "description": r.description,
        "quantity": r.quantity,
        "values": list(r.values),
    }


def table_cells(bom_type: str, columns: Iterable[str], rows: Iterable[Mapping[str, Any]]) -> list[list[str]]:
    """Table cells from rows given as ``bom`` JSON rows (or anything with their
    ``item``, ``level``, ``part_number``, ``description``, ``quantity`` and
    ``values``): the header, then a row each. In an indented table the part number
    is indented by :data:`INDENT` a level; an unknown description or value is empty."""
    out = [[*COLUMNS, *columns]]
    for r in rows:
        indent = INDENT * r["level"] if bom_type == "indented" else ""
        out.append(
            [
                r["item"],
                indent + r["part_number"],
                r["description"] or "",
                str(r["quantity"]),
                *(v or "" for v in r["values"]),
            ]
        )
    return out


# --------------------------------------------------------------------------- CSV
# After the table's own columns, what an ERP import needs to place each row.
CSV_COLUMNS = (
    "LEVEL",
    "TOTAL QTY.",
    "CONFIGURATION",
    "ALTERNATE NAME",
    "DOCUMENT TYPE",
    "FILE NAME",
    "STORED PATH",
    "FOUND AT",
    "NOTES",
)
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _csv_cell(value: Any) -> Any:
    """Text a spreadsheet would run as a formula gets a leading apostrophe, as in the
    command line's batch report."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


def _found_at(r: Mapping[str, Any]) -> str:
    loc = r["location"]
    text = "" if loc is None else (f"{loc['root']}:{loc['path']}" if loc["root"] is not None else loc["path"])
    for stream in r["nested"]:
        text += (" > " if text else "") + stream
    return text


def csv_text(data: Mapping[str, Any]) -> str:
    """``bom`` data (:func:`solidseas.model.build_bom`) as CSV text: a header row, then a
    row per BOM row, with ``\r\n`` line ends and fields quoted only where they
    need it. The columns are the table's (ITEM NO., PART NUMBER without indentation,
    DESCRIPTION, QTY., then the property columns), then :data:`CSV_COLUMNS`. A field
    a spreadsheet would run as a formula (starting with ``=``, ``+``, ``-``, ``@``, a
    tab or a carriage return) gets a leading apostrophe."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow([_csv_cell(c) for c in (*data["columns"], *CSV_COLUMNS)])
    for r in data["rows"]:
        cells = [
            r["item"],
            r["part_number"],
            r["description"] or "",
            r["quantity"],
            *(v or "" for v in r["values"]),
            r["level"],
            r["total_quantity"],
            r["configuration"] or "",
            r.get("alternate_name") or "",  # absent from bom data written before it existed
            r["doc_type"] or "",
            r["file_name"] or "",
            r["stored_path"] or "",
            _found_at(r),
            "; ".join(n["code"] for n in r["notes"]),
        ]
        w.writerow([_csv_cell(c) for c in cells])
    return buf.getvalue()


def csv_bytes(data: Mapping[str, Any]) -> bytes:
    """:func:`csv_text` as a file's bytes: UTF-8 after a byte order mark, which tells
    Excel and most ERP imports the encoding (a name such as ``o17_деталь`` survives)."""
    return ("\ufeff" + csv_text(data)).encode("utf-8")


# --------------------------------------------------------------------------- arguments
def _count(value: Any, name: str, low: int, high: int | None = None) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < low
        or (high is not None and value > high)
    ):
        span = f"from {low} to {high}" if high is not None else f"of at least {low}"
        raise InvalidArgumentError(f"{name} must be a whole number {span}", detail={"parameter": name})
    return value


def check_property_name(value: Any, parameter: str, *, label: str | None = None) -> str:
    """A property name for a column or for ``part_number_property``, checked; a bad one
    raises :class:`InvalidArgumentError` naming ``parameter`` (and ``label``, such as a
    command-line flag, in its message)."""
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > MAX_COLUMN_NAME
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
    ):
        raise InvalidArgumentError(
            f"{label or parameter}: a property name has 1 to {MAX_COLUMN_NAME} characters and no "
            "control characters",
            detail={"parameter": parameter},
        )
    return value


def check_type(bom_type: Any, parameter: str = "type") -> str:
    """A BOM type, checked; a bad one raises :class:`InvalidArgumentError` naming
    ``parameter`` (``type`` on the command line and the service, ``bom_type`` in
    Python)."""
    if not isinstance(bom_type, str) or bom_type not in BOM_TYPES:
        raise InvalidArgumentError(
            f"a BOM type is one of {', '.join(BOM_TYPES)}", detail={"parameter": parameter}
        )
    return bom_type


def check_columns(columns: Any, *, label: str = "columns") -> tuple[str, ...]:
    """The property columns, checked: at most :data:`MAX_COLUMNS` distinct names
    (compared case-insensitively, as SOLIDWORKS compares property names). An error
    names ``columns`` as its parameter and ``label`` in its message."""
    bad = {"parameter": "columns"}
    if isinstance(columns, (str, bytes)) or not isinstance(columns, Iterable):
        raise InvalidArgumentError(f"{label} is a list of property names", detail=bad)
    out = tuple(check_property_name(c, "columns", label=label) for c in columns)
    if len(out) > MAX_COLUMNS:
        raise InvalidArgumentError(f"{label}: at most {MAX_COLUMNS} property columns", detail=bad)
    if len({c.casefold() for c in out}) != len(out):
        raise InvalidArgumentError(f"{label}: a property column is named twice", detail=bad)
    return out


def _check_resolve_options(path_map: Any, allow_outside_roots: Any, cache: Any) -> None:
    """The options that go to reference resolution, checked before any work by the rules
    :func:`solidseas.resolve.resolve_references` applies, so that a bad one raises
    instead of turning into a note on every row."""
    from .resolve import IndexCache, parse_path_map

    parse_path_map(path_map)
    if not isinstance(allow_outside_roots, bool):
        raise InvalidArgumentError(
            "allow_outside_roots is true or false", detail={"parameter": "allow_outside_roots"}
        )
    if cache is not None and not isinstance(cache, IndexCache):
        raise InvalidArgumentError(
            "cache is a solidseas.resolve.IndexCache or None", detail={"parameter": "cache"}
        )


def _roots_of(doc, roots) -> Roots | None:
    if roots is None:
        if not doc.path:
            return None
        return Roots([Root(DOCUMENT_ROOT_ID, os.path.dirname(os.path.abspath(doc.path)))])
    if isinstance(roots, Roots):
        return roots
    if isinstance(roots, Mapping):
        return Roots.from_mapping(roots)
    if isinstance(roots, Root):
        return Roots([roots])
    if isinstance(roots, Iterable) and not isinstance(roots, (str, bytes)):
        return Roots(roots)
    raise InvalidArgumentError(
        "roots is a Roots, a Root, Roots entries or {id: folder}", detail={"parameter": "roots"}
    )


def _error_code(exc: BaseException) -> str:
    from .model import error_code

    return error_code(exc)


# --------------------------------------------------------------------------- reading the files
@dataclass(frozen=True)
class _Read:
    """What reading one file in one configuration gave."""

    properties: tuple[Property, ...] | None
    resolution: str | None
    location: Location | None
    nested: tuple[str, ...]
    notes: tuple[ReaderWarning, ...] = ()
    lists_components: bool | None = None  # an assembly's own file lists components (None: unknown)


class _Unread(Exception):
    def __init__(self, status: str | None, why: str) -> None:
        super().__init__(why)
        self.status, self.why = status, why


@dataclass
class _Open:
    doc: Any
    location: Location | None
    nested: tuple[str, ...]
    status: str | None


def _unread_note(why: str) -> ReaderWarning:
    return ReaderWarning(
        "bom_properties_unread",
        f"its file's properties are unknown: {why}; the row keeps what the assembly stores",
    )


class _Reader:
    """Reads the properties of the rows' files: each file once, in every configuration
    the rows need, within the limits. A sub-assembly that stores a document a row needs
    (a virtual component inside it, :meth:`keep_hosts_of`) stays open until the end;
    every other file is closed as soon as it has been read, so the files held open at
    once are those hosts only."""

    def __init__(self, doc, tree, *, roots, resolution, resolve_options, max_files, deadline, opener) -> None:
        self.doc, self.tree = doc, tree
        self.roots = roots
        self.resolution = resolution
        self.resolve_failed: str | None = None
        self.resolve_options = resolve_options
        self.max_files, self.deadline = max_files, deadline
        self.opener = opener
        self.files_opened = 0
        self.limits_hit: list[str] = []
        self.kept: dict[str, _Open | _Unread] = {}
        self.to_close: list[Any] = []
        self.streams: dict[str, dict[str, str]] = {}  # a sub-assembly's stored documents by file name
        parents: dict[str, str | None] = {}
        for n in tree.walk():
            for c in n.children:
                if c.file is not None:
                    parents.setdefault(c.file, n.file)
        self.parents = parents
        self.hosts: set[str] = set()  # sub-assemblies kept open for the documents stored in them

    def keep_hosts_of(self, keys: Iterable[str]) -> None:
        """Keep open, once read, each sub-assembly that stores one of ``keys`` (and the
        sub-assemblies those are stored in, for a virtual sub-assembly's own virtual
        parts)."""
        for key in keys:
            k, seen = key, set()
            while k not in seen:
                seen.add(k)
                f = self.tree.files.get(k)
                parent = self.parents.get(k) if f is not None and f.embedded_in_subassembly else None
                if parent is None:
                    break
                self.hosts.add(parent)
                k = parent

    # ---------------------------------------------------------------- resolution
    def _resolved(self, key: str) -> tuple[str, str, Location, str]:
        if self.resolution is None:
            if self.resolve_failed is not None:
                raise _Unread(None, self.resolve_failed)
            if self.roots is None:
                self.resolve_failed = (
                    "the assembly was read from bytes and no roots were given, so no file is searched"
                )
                raise _Unread(None, self.resolve_failed)
            from .resolve import Gateway, resolve_references

            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                self.limits_hit.append("max_seconds")
                raise _Unread(None, "the time limit was spent before the files were looked for")
            # The documents resolution opens to read their identity are files opened too,
            # and get only the room max_files leaves.
            room = max(0, self.max_files - self.files_opened)
            gateway = Gateway(
                allow_outside_roots=self.resolve_options["allow_outside_roots"],
                max_identity_reads=room,
                deadline=time.monotonic() + remaining,
            )
            try:
                self.resolution = resolve_references(
                    self.doc, self.roots, max_seconds=remaining, gateway=gateway, **self.resolve_options
                )
            except (MemoryError, InvalidArgumentError, OSError):
                # A bad argument, or a root folder that cannot be walked (it does not exist,
                # or access is denied): raised as resolve_references raises them.
                raise
            except Exception as exc:  # anything else: no file is searched, and every row says so
                self.resolve_failed = f"the files could not be looked for ({_error_code(exc)})"
                raise _Unread(None, self.resolve_failed) from None
            finally:
                self.files_opened += gateway.identity_reads
            if gateway.identity_reads >= room and any(
                c[0] == "identity" and c[2] == "skipped" for c in gateway.calls
            ):  # identities left unread for want of room: the results may be less sure
                self.limits_hit.append("max_files")
        r = self.resolution.results.get(key)
        if r is None:
            raise _Unread(None, "reference resolution has no result for its file")
        if r.status not in _FOUND or r.match is None:
            why = {
                "missing": "its file was not found",
                "ambiguous": "several files could be its file",
                "embedded_not_found": _NOT_STORED,
                "inside_parent": "it is an imported component kept inside the assembly",
            }.get(r.status, f"its file was not found ({r.status})")
            raise _Unread(r.status, why)
        if r.match.root is not None:
            try:
                within = self.roots[r.match.root].path  # type: ignore[index]
            except (KeyError, TypeError):
                raise _Unread(r.status, "its file was found under a root this call was not given") from None
        else:
            within = os.path.dirname(r.match.host_path)
        return r.match.host_path, within, r.match, r.status

    # ---------------------------------------------------------------- documents
    def _check_room(self) -> None:
        if time.monotonic() >= self.deadline:
            self.limits_hit.append("max_seconds")
            raise _Unread(None, "the time limit on reading the files was reached")
        if self.files_opened >= self.max_files:
            self.limits_hit.append("max_files")
            raise _Unread(None, "the limit on files opened was reached")

    def _on_disk(self, key: str) -> _Open:
        self._check_room()
        host, within, loc, status = self._resolved(key)
        self._check_room()  # resolution may have spent the time
        self.files_opened += 1
        try:
            d = self.opener(host, within)
        except MemoryError:
            raise
        except Exception as exc:
            raise _Unread(status, f"its file could not be read ({_error_code(exc)})") from None
        return _Open(d, loc, (), status)

    def _nested(self, outer: _Open, stream: str, status: str) -> _Open:
        try:
            d = outer.doc.nested(stream)
        except MemoryError:
            raise
        except Exception as exc:
            why = f"the document stored inside could not be read ({_error_code(exc)})"
            raise _Unread(status, why) from None
        return _Open(d, outer.location, (*outer.nested, stream), status)

    def document(self, key: str, *, keep: bool, seen: frozenset = frozenset()) -> _Open:
        """The document of file ``key``, open. With ``keep`` it stays open (and cached)
        until :meth:`close`; otherwise the caller closes a file it was given."""
        got = self.kept.get(key)
        if isinstance(got, _Unread):
            raise got
        if got is not None:
            return got
        f = self.tree.files.get(key)
        if f is None:
            raise _Unread(None, "the component tree does not name its file")
        top = _Open(self.doc, None, (), None)
        try:
            if f.nested:
                status = "embedded"
                opened = self._nested(top, f.nested, status)
            elif f.embedded_in_subassembly:
                status = "embedded_in_subassembly"
                parent = self.parents.get(key)
                if parent is None or parent in seen:
                    raise _Unread(status, "the sub-assembly that stores it is not known")
                outer = self.document(parent, keep=True, seen=seen | {key})
                opened = self._nested(outer, self._stream_in(parent, outer.doc, f), status)
            elif f.embedded == "embedded_not_found":
                raise _Unread("embedded_not_found", _NOT_STORED)
            else:
                opened = self._on_disk(key)
                if keep:
                    self.to_close.append(opened.doc)
        except _Unread as exc:
            if keep:
                self.kept[key] = exc
            raise
        if keep:
            self.kept[key] = opened
        return opened

    def _stream_in(self, parent: str, subdoc, f) -> str:
        """The nested-document stream that holds virtual file ``f`` in ``subdoc``, the
        sub-assembly (file ``parent``) that uses it directly, matched by the stored file
        name; the sub-assembly's map is made once."""
        names = self.streams.get(parent)
        if names is None:
            names = self.streams[parent] = {}
            for g in subdoc.reference_set().files.values():
                if g.nested:
                    names.setdefault(_base(g.stored_path), g.nested)
        got = names.get(_base(f.stored_path))
        if got is None:
            raise _Unread("embedded_not_found", "its sub-assembly does not store it")
        return got

    def close(self) -> None:
        for d in reversed(self.to_close):
            try:
                d.close()
            except Exception:  # closing never fails the result
                pass
        self.to_close.clear()

    # ---------------------------------------------------------------- properties
    def read(self, key: str, configurations: list[str | None], unlisted: bool) -> dict[str | None, _Read]:
        """The properties of file ``key`` in each of ``configurations``; with
        ``unlisted``, also whether its own file lists components in each."""
        f = self.tree.files.get(key)
        keep = key in self.hosts
        try:
            opened = self.document(key, keep=keep)
        except _Unread as exc:
            note = _unread_note(exc.why)
            status = exc.status if exc.status is not None else (f.embedded if f is not None else None)
            return {c: _Read(None, status, None, (), (note,)) for c in configurations}
        try:
            out = {}
            for c in configurations:
                notes: list[ReaderWarning] = []
                d = opened.doc
                try:
                    props = tuple(d.effective_properties(c))
                except ConfigurationNotFoundError:
                    props = tuple(d.properties)
                    if d.configurations:
                        notes.append(
                            ReaderWarning(
                                "bom_configuration_missing",
                                f"its file has no configuration {c!r}; the file's own properties are used",
                            )
                        )
                    else:
                        notes.append(
                            ReaderWarning(
                                "bom_configurations_unknown",
                                f"SolidSeas finds no configuration in its file, so {c!r} could not be "
                                "looked up; the file's own properties are used",
                            )
                        )
                lists = None
                if unlisted:
                    try:
                        sub = d.components(c, max_nodes=1)
                        if sub is not None and sub.children_state == "described":
                            lists = bool(sub.children)
                    except MemoryError:
                        raise
                    except Exception:  # the configuration is missing there: nothing is known
                        lists = None
                out[c] = _Read(props, opened.status, opened.location, opened.nested, tuple(notes), lists)
            return out
        finally:
            if not keep and opened.location is not None and not opened.nested:
                try:
                    opened.doc.close()
                except Exception:  # closing never fails the result
                    pass


def _base(stored_path: str | None) -> str:
    return os.path.basename((stored_path or "").replace("\\", "/")).casefold()


# --------------------------------------------------------------------------- grouping
def _in_bom(n: ComponentNode) -> bool:
    return not n.suppressed and not n.excluded_from_bom


def _group_key(n: ComponentNode) -> tuple[str, str | None]:
    return (n.file if n.file is not None else "\0" + (n.component or n.name), n.configuration)


def _groups(nodes: Iterable[ComponentNode]) -> list[list[ComponentNode]]:
    """The in-BOM instances of ``nodes``, one list per file and configuration, in the
    order each was first listed."""
    out: dict[tuple, list[ComponentNode]] = {}
    for n in nodes:
        if _in_bom(n):
            out.setdefault(_group_key(n), []).append(n)
    return list(out.values())


def _unlisted(n: ComponentNode) -> bool:
    """A sub-assembly whose components the top assembly's tree does not list."""
    return n.doc_type == "assembly" and n.children_state == "described" and not n.children


def _part_leaves(nodes: Iterable[ComponentNode]) -> Iterable[ComponentNode]:
    """Depth first, the in-BOM instances that have no listed components under them."""
    for n in nodes:
        if not _in_bom(n):
            continue
        if n.children:
            yield from _part_leaves(n.children)
        else:
            yield n


@dataclass(frozen=True)
class _Planned:
    """A row before its file has been read. ``children_differ``: the instances of this
    sub-assembly list different components (an indented BOM's row only)."""

    item: str
    level: int
    parent: str | None
    quantity: int
    total: int
    instances: tuple[ComponentNode, ...]
    children_differ: bool = False


def _plan_top(tree) -> list[_Planned]:
    groups = _groups(tree.children)
    return [_Planned(str(i), 0, None, len(g), len(g), tuple(g)) for i, g in enumerate(groups, start=1)]


def _plan_indented(tree) -> list[_Planned]:
    out: list[_Planned] = []

    def rows(members: list, level: int, prefix: str, parent: str | None) -> bool:
        """The rows under a parent whose instances have the component lists ``members``:
        one row per file and configuration over all of them, in first-seen order, with
        every instance under every instance of the parent. QTY. is the count under one
        instance of the parent (the first that has the row), the total quantity the
        count of instances. True when the instances list different components, which
        SOLIDWORKS never writes (one model per file and configuration) but a damaged or
        crafted tree can."""
        pool: dict[tuple, list[ComponentNode]] = {}
        first: dict[tuple, int] = {}  # each row's QTY.: its count under the first instance that has it
        per_member: list[dict[tuple, int]] = []
        for children in members:
            mine: dict[tuple, int] = {}
            for c in children:
                if _in_bom(c):
                    key = _group_key(c)
                    pool.setdefault(key, []).append(c)
                    mine[key] = mine.get(key, 0) + 1
            for key, n in mine.items():
                first.setdefault(key, n)
            per_member.append(mine)
        # Every node is counted once on its own level, so planning is linear in the tree
        # (max_instances bounds it), however many instances list however many components.
        for i, (key, every) in enumerate(pool.items(), start=1):
            item = f"{prefix}{i}"
            quantity = first[key]
            at = len(out)
            out.append(_Planned(item, level, parent, quantity, len(every), tuple(every)))
            below = [n.children for n in every]
            if any(below) and rows(below, level + 1, item + ".", item):
                out[at] = replace(out[at], children_differ=True)
        return len({frozenset(m.items()) for m in per_member}) > 1

    if tree.children:
        rows([list(tree.children)], 0, "", None)
    return out


def _plan_parts(tree) -> list[_Planned]:
    groups: dict[tuple, list[ComponentNode]] = {}
    for n in _part_leaves(tree.children):
        groups.setdefault(_group_key(n), []).append(n)
    return [_Planned("", 0, None, len(g), len(g), tuple(g)) for g in groups.values()]


_PLANS = {"top": _plan_top, "indented": _plan_indented, "parts": _plan_parts}
# Row notes that make a BOM incomplete (with an unread file): something is missing, or a
# cell may not be SOLIDWORKS'.
_INCOMPLETE_NOTES = ("bom_children_missing", "bom_children_differ", "bom_part_number_may_differ")


# --------------------------------------------------------------------------- rows
def _text_of(props: tuple[Property, ...] | None, name: str) -> str | None:
    if props is None:
        return None
    folded = name.casefold()
    for p in props:
        if p.name.casefold() == folded:
            return p.text if p.text is not None else ""
    return None


def _document_name(n: ComponentNode, f) -> str:
    name = f.file_name if f is not None and f.file_name else None
    if name:
        stem, ext = os.path.splitext(name)
        return stem if ext else name
    return n.component or n.name


def _children_note(n: ComponentNode, read: _Read | None) -> ReaderWarning | None:
    """Why a sub-assembly's components are missing from the BOM, or None."""
    if n.children_state in _CUT_STATES and n.doc_type != "part":
        why = {
            "truncated": "a limit of the component tree stopped the expansion here",
            "cycle": "the sub-assembly contains itself",
            "unknown": "the component tree names a model it does not hold",
        }[n.children_state]
        return ReaderWarning("bom_children_missing", f"its components are missing: {why}")
    if _unlisted(n) and (read is None or read.lists_components is not False):
        why = (
            "the assembly's tree does not list them, and its own file does"
            if read is not None and read.lists_components
            else "the assembly's tree does not list them, and its own file was not read to check"
        )
        return ReaderWarning("bom_children_missing", f"its components are missing: {why}")
    return None


def _make_row(
    p: _Planned,
    tree,
    reads: dict[tuple, _Read],
    *,
    bom_type: str,
    columns: tuple[str, ...],
    part_number_property: str | None,
    read_properties: bool,
) -> BomRow:
    n = p.instances[0]
    f = tree.files.get(n.file) if n.file is not None else None
    read = reads.get(_group_key(n))
    props = read.properties if read is not None else None
    notes = list(read.notes) if read is not None else []
    if n.file is None and read_properties:
        notes.append(_unread_note("the component tree does not say which file it uses"))
    if bom_type != "top":
        cut = _children_note(n, read)
        if cut is not None:
            notes.append(cut)
    if p.children_differ:
        notes.append(
            ReaderWarning(
                "bom_children_differ",
                "its instances list different components (the tree holds more than one model of "
                "its file in this configuration): the rows under it list those of every instance, "
                "each QTY. as under the first instance that has it, and the total quantities count "
                "every instance",
            )
        )
    part_number, source = _document_name(n, f), "document_name"
    if part_number_property is not None:
        value = _text_of(props, part_number_property)
        if value:
            part_number, source = value, "property"
    alternate = next((i.alternate_name for i in p.instances if i.alternate_name), None)
    if alternate is not None and source == "document_name" and alternate != part_number:
        notes.append(
            ReaderWarning(
                "bom_part_number_may_differ",
                f"its configuration stores the alternate name {alternate!r}, which SOLIDWORKS shows "
                "as the part number when the configuration is set to; where that setting is stored "
                "is not known, so the document name is given",
            )
        )
    description = _text_of(props, DESCRIPTION_PROPERTY)
    if description is None and props is not None:
        description = ""
    return BomRow(
        item=p.item,
        level=p.level,
        parent=p.parent,
        part_number=part_number,
        part_number_source=source,
        alternate_name=alternate,
        description=description,
        quantity=p.quantity,
        total_quantity=p.total,
        file=n.file,
        file_name=f.file_name if f is not None else None,
        stored_path=f.stored_path if f is not None else None,
        doc_type=n.doc_type,
        configuration=n.configuration,
        virtual=bool(f.virtual) if f is not None else n.virtual,
        imported=bool(f.imported) if f is not None else False,
        instances=tuple(i.id for i in p.instances),
        resolution=read.resolution if read is not None else (f.embedded if f is not None else None),
        location=read.location if read is not None else None,
        nested=read.nested if read is not None else (),
        properties=props,
        values=tuple(_text_of(props, c) for c in columns),
        notes=tuple(notes),
    )


# --------------------------------------------------------------------------- building
def build_boms(
    doc,
    configuration: str | None = None,
    *,
    bom_types: Iterable[str] = BOM_TYPES,
    roots=None,
    resolution: Resolution | None = None,
    path_map=(),
    allow_outside_roots: bool = True,
    cache=None,
    columns: Iterable[str] = (),
    part_number_property: str | None = None,
    read_properties: bool = True,
    max_instances: int = DEFAULT_MAX_NODES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_files: int = DEFAULT_MAX_FILES,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    max_file_bytes: int | None = None,
    opener: Opener | None = None,
) -> dict[str, Bom] | None:
    """Several BOM types of one assembly configuration, ``{type: Bom}``, each file read
    once for all of them; None for a part or a drawing. The options are those of
    :func:`build_bom`."""
    asked = [bom_types] if isinstance(bom_types, str) else bom_types
    if not isinstance(asked, Iterable):
        raise InvalidArgumentError("bom_types is a list of BOM types", detail={"parameter": "bom_types"})
    types = tuple(dict.fromkeys(check_type(t, "bom_types") for t in asked))
    if not types:
        raise InvalidArgumentError("at least one BOM type", detail={"parameter": "bom_types"})
    cols = check_columns(columns)
    pn_property = None
    if part_number_property is not None:
        pn_property = check_property_name(part_number_property, "part_number_property")
    if not isinstance(read_properties, bool):
        raise InvalidArgumentError(
            "read_properties is true or false", detail={"parameter": "read_properties"}
        )
    limits = {
        "max_instances": _count(max_instances, "max_instances", 1, MAX_NODES_LIMIT),
        "max_depth": _count(max_depth, "max_depth", 1, MAX_DEPTH_LIMIT),
        "max_files": _count(max_files, "max_files", 0),
        "max_seconds": _seconds(max_seconds),
    }
    if max_file_bytes is not None:
        _count(max_file_bytes, "max_file_bytes", 1)
    if resolution is not None and not hasattr(resolution, "results"):
        raise InvalidArgumentError(
            "resolution is a solidseas.resolve.Resolution", detail={"parameter": "resolution"}
        )
    if opener is not None and not callable(opener):
        raise InvalidArgumentError("opener is a function (path, within)", detail={"parameter": "opener"})
    search = _roots_of(doc, roots)
    _check_resolve_options(path_map, allow_outside_roots, cache)
    if doc.doc_type != "assembly":
        if configuration is not None:
            doc.configuration(configuration)  # an unknown name is refused on every document type
        return None
    started = time.monotonic()
    tree = doc.components(configuration, max_nodes=limits["max_instances"], max_depth=limits["max_depth"])
    plans = {t: _PLANS[t](tree) for t in types}

    # Which file is read in which configurations, in the order the rows first need them.
    needs: dict[str, list[str | None]] = {}
    unlisted: set[str] = set()
    for planned in plans.values():
        for p in planned:
            n = p.instances[0]
            if n.file is None:
                continue
            cfgs = needs.setdefault(n.file, [])
            if n.configuration not in cfgs:
                cfgs.append(n.configuration)
            if _unlisted(n):
                unlisted.add(n.file)
    reads: dict[tuple, _Read] = {}
    reader = None
    if read_properties and needs:
        if opener is None:

            def opener(path: str, within: str):
                from .formats.solidworks.document import open_document

                return open_document(path, within=within, hold_open=True, max_file_bytes=max_file_bytes)

        reader = _Reader(
            doc,
            tree,
            roots=search,
            resolution=resolution,
            resolve_options={
                "path_map": path_map,
                "allow_outside_roots": allow_outside_roots,
                "cache": cache,
            },
            max_files=limits["max_files"],
            deadline=started + limits["max_seconds"],
            opener=opener,
        )
        reader.keep_hosts_of(needs)
        try:
            for key, cfgs in needs.items():
                for cfg, got in reader.read(key, cfgs, key in unlisted).items():
                    reads[(key, cfg)] = got
        finally:
            reader.close()
    seconds = time.monotonic() - started
    res = reader.resolution if reader is not None else resolution
    out = {}
    for t in types:
        planned = plans[t]
        if t == "parts":  # an empty sub-assembly (its own file lists nothing) is no part
            planned = [
                p
                for p in planned
                if not (
                    _unlisted(p.instances[0])
                    and getattr(reads.get(_group_key(p.instances[0])), "lists_components", None) is False
                )
            ]
            planned = [
                _Planned(str(i), p.level, p.parent, p.quantity, p.total, p.instances)
                for i, p in enumerate(planned, start=1)
            ]
        rows = tuple(
            _make_row(
                p,
                tree,
                reads,
                bom_type=t,
                columns=cols,
                part_number_property=pn_property,
                read_properties=read_properties,
            )
            for p in planned
        )
        unread = sum(1 for r in rows if r.properties is None) if read_properties else 0
        in_doubt = any(w.code in _INCOMPLETE_NOTES for r in rows for w in r.notes)
        complete = (
            tree.children_state == "described"
            and not tree.truncated
            and unread == 0
            and not in_doubt
            and not (res is not None and res.index_partial)
        )
        out[t] = Bom(
            type=t,
            configuration=tree.configuration,
            configuration_source=tree.configuration_source,
            children_state=tree.children_state,
            columns=cols,
            part_number_property=pn_property,
            read_properties=read_properties,
            rows=rows,
            truncated=tree.truncated,
            complete=complete,
            counts={
                "rows": len(rows),
                "instances": sum(len(r.instances) for r in rows),
                "files": len({r.file for r in rows if r.file is not None}),
                "read": len(rows) - unread if read_properties else 0,
                "unread": unread,
                "files_opened": reader.files_opened if reader is not None else 0,
                "seconds": seconds,
            },
            limits={**limits, "max_file_bytes": max_file_bytes},
            resolution=res,
            warnings=tuple(tree.warnings)
            + tuple(
                ReaderWarning("bom_limit_reached", f"the limit {name} stopped the reading of some files")
                for name in dict.fromkeys(reader.limits_hit if reader is not None else ())
            ),
        )
    return out


def _seconds(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1e6:
        raise InvalidArgumentError(
            "max_seconds must be a number of seconds from 0 to 1e6", detail={"parameter": "max_seconds"}
        )
    return float(value)


# --------------------------------------------------------------------------- the service's hand-over
def resolution_payload(res: Resolution) -> dict[str, Any]:
    """``res`` as JSON data for a worker process of the REST service, which reads the
    files it found (``docs/API.md`` C10). Unlike the ``references`` kind it carries
    each match's host path: it goes from the server process to its own worker and
    never into an answer."""
    return {
        "results": [
            {
                "key": r.key,
                "status": r.status,
                "stored_path": r.stored_path,
                "match": None
                if r.match is None
                else {"root": r.match.root, "path": r.match.path, "host_path": r.match.host_path},
                "rule": r.rule,
                "confidence": r.confidence,
                "identity": r.identity,
                "nested": r.nested,
            }
            for r in res.results.values()
        ],
        "roots": [
            {
                "id": s.id,
                "role": s.role,
                "recursive": s.recursive,
                "index_partial": s.index_partial,
                "truncated_reason": s.truncated_reason,
            }
            for s in res.roots
        ],
        "index_partial": res.index_partial,
        "allow_outside_roots": res.allow_outside_roots,
        "truncated": res.truncated,
    }


def resolution_from_payload(data: Any) -> Resolution:
    """The :class:`~solidseas.resolve.Resolution` :func:`resolution_payload` made,
    checked field by field (it crossed a process boundary). Candidates and warnings
    are not carried: a BOM uses neither."""
    from .resolve.core import ResolvedReference, RootState

    def bad(what: str) -> InvalidArgumentError:
        return InvalidArgumentError(f"resolution payload: {what}", detail={"parameter": "resolution"})

    def text(v: Any, what: str, *, null: bool = True) -> Any:
        if (v is None and null) or (isinstance(v, str) and len(v) <= 32_768):
            return v
        raise bad(what)

    def flag(v: Any, what: str) -> bool:
        if not isinstance(v, bool):
            raise bad(what)
        return v

    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise bad("not an object with results")
    if not isinstance(data.get("roots"), list):
        raise bad("roots")
    results = {}
    for item in data["results"]:
        if not isinstance(item, dict):
            raise bad("a result is not an object")
        m = item.get("match")
        match = None
        if m is not None:
            if not isinstance(m, dict):
                raise bad("match")
            match = Location(
                text(m.get("root"), "match root"),
                text(m.get("path"), "match path", null=False),
                text(m.get("host_path"), "match host path", null=False),
            )
        key = text(item.get("key"), "key", null=False)
        results[key] = ResolvedReference(
            key=key,
            status=text(item.get("status"), "status", null=False),
            stored_path=text(item.get("stored_path"), "stored_path"),
            match=match,
            rule=text(item.get("rule"), "rule"),
            confidence=text(item.get("confidence"), "confidence", null=False),
            identity=text(item.get("identity"), "identity", null=False),
            nested=text(item.get("nested"), "nested"),
            candidates=(),
            warnings=(),
        )
    roots = []
    for s in data["roots"]:
        if not isinstance(s, dict):
            raise bad("a root is not an object")
        roots.append(
            RootState(
                text(s.get("id"), "root id", null=False),
                text(s.get("role"), "root role", null=False),
                flag(s.get("recursive"), "recursive"),
                flag(s.get("index_partial"), "index_partial"),
                text(s.get("truncated_reason"), "truncated_reason"),
            )
        )
    return Resolution(
        results=results,
        roots=tuple(roots),
        index_partial=flag(data.get("index_partial"), "index_partial"),
        allow_outside_roots=flag(data.get("allow_outside_roots"), "allow_outside_roots"),
        truncated=flag(data.get("truncated"), "truncated"),
    )


def build_bom(
    doc,
    configuration: str | None = None,
    *,
    bom_type: str = DEFAULT_TYPE,
    **options: Any,
) -> Bom | None:
    """The bill of materials of one configuration of the assembly ``doc``, or None for
    a part or a drawing. Provisional (``docs/API.md`` 3.16).

    ``configuration`` is chosen as :meth:`Document.components` chooses it, and
    ``bom_type`` is ``top`` (the default, as in SOLIDWORKS), ``parts`` or
    ``indented``. ``columns`` adds a column per property name, read like
    DESCRIPTION; ``part_number_property`` takes PART NUMBER from that property
    instead of the document name; ``read_properties=False`` reads no file at all
    (no description, no property columns).

    ``roots`` are the folders reference resolution searches for the component files
    (None: the document's own folder), and ``path_map``, ``allow_outside_roots`` and
    ``cache`` go to :func:`solidseas.resolve.resolve_references`; a ``resolution``
    already made against the same ``roots`` is used as it is. ``opener(path,
    within)`` opens a file (by default read-only, ``within`` its root, reading only
    what is needed, refusing a file larger than ``max_file_bytes``).

    Limits as in the module notes: ``max_instances``, ``max_depth``, ``max_files``,
    ``max_seconds`` and ``max_file_bytes``. Raises only for bad arguments, an
    unknown configuration and errors reading the assembly's own tree.
    """
    got = build_boms(doc, configuration, bom_types=(check_type(bom_type, "bom_type"),), **options)
    return None if got is None else got[bom_type]


__all__ = [
    "BOM_TYPES",
    "COLUMNS",
    "CSV_COLUMNS",
    "DEFAULT_MAX_FILES",
    "DEFAULT_MAX_SECONDS",
    "DEFAULT_TYPE",
    "DESCRIPTION_PROPERTY",
    "INDENT",
    "MAX_COLUMNS",
    "TYPE_NAMES",
    "Bom",
    "BomRow",
    "build_bom",
    "build_boms",
    "check_columns",
    "check_property_name",
    "check_type",
    "csv_bytes",
    "csv_text",
    "table_cells",
]
