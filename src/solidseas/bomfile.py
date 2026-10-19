"""The ``.ssbom`` file: a BOM as a person edited it, kept on its own (provisional).

A ``.ssbom`` is UTF-8 JSON holding the assembly it is the BOM of (its file name, its
path relative to the ``.ssbom``'s folder, and the configuration), the table
definition (:class:`~solidseas.bomtable.BomTableSpec`) and the table as it was last
shown, so the file can be read and exported without the assembly. Opening it again
with the assembly at hand builds the BOM afresh and applies the definition, which
keeps every edit whose row is still there and lists the others
(:attr:`~solidseas.bomtable.ShownTable.unused`).

Saving follows the drawing file's rules (:func:`solidseas.drawing.document.save`):
the file is written through a temporary name and a rename, created new when nothing
is there and written over an existing file only when ``replaces`` equals the
SHA-256 of what is there now, never through a link and never over anything but a
plain file. Reading refuses a file over :data:`MAX_BYTES`, JSON with ``NaN`` or a
repeated key, and a schema it does not know.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any

from .bomtable import BomTableSpec, ShownTable, spec_from_json
from .drawing.document import Saved, _write
from .drawing.limits import DEFAULT_LIMITS
from .errors import InvalidArgumentError

EXTENSION = ".ssbom"
FORMAT = "solidseas-bom"
SCHEMA = 1
MAX_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class BomFile:
    """What a ``.ssbom`` holds. ``model`` has ``name`` (the assembly's file name),
    ``relative`` (its path from the ``.ssbom``'s folder, ``/`` separated, None when
    on another drive) and ``configuration``; ``table`` the headings and rows of text as
    last shown."""

    model: dict[str, Any]
    spec: BomTableSpec
    table: tuple[tuple[str, ...], ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "schema": SCHEMA,
            "model": dict(self.model),
            "spec": self.spec.to_json(),
            "table": [list(r) for r in self.table],
        }


def make(
    bom_path: str | os.PathLike,
    assembly: str | os.PathLike,
    configuration: str | None,
    table: ShownTable,
    table_spec: BomTableSpec,
) -> BomFile:
    """A :class:`BomFile` for the assembly at ``assembly`` to be saved at ``bom_path``."""
    folder = os.path.dirname(os.path.abspath(os.fspath(bom_path)))
    target = os.path.abspath(os.fspath(assembly))
    try:
        relative: str | None = os.path.relpath(target, folder).replace(os.sep, "/")
    except ValueError:  # another drive
        relative = None
    model = {"name": os.path.basename(target), "relative": relative, "configuration": configuration}
    return BomFile(model, table_spec, tuple(tuple(r) for r in table.cells()))


def dumps(bom_file: BomFile) -> bytes:
    return (
        json.dumps(bom_file.to_json(), ensure_ascii=False, indent=1, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _strict(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in pairs:
        if k in out:
            raise InvalidArgumentError(f"the BOM file repeats the key {k!r}", detail={"parameter": "path"})
        out[k] = v
    return out


def _no_constant(name: str) -> Any:
    raise InvalidArgumentError(
        f"the BOM file holds {name}, which is not a number", detail={"parameter": "path"}
    )


def loads(data: bytes) -> BomFile:
    """The :class:`BomFile` in ``data``, checked (module notes)."""
    if len(data) > MAX_BYTES:
        raise InvalidArgumentError(
            "the BOM file is larger than SolidSeas reads", detail={"parameter": "path"}
        )
    try:
        raw = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_strict, parse_constant=_no_constant)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise InvalidArgumentError("not a BOM file: it is not JSON", detail={"parameter": "path"}) from None
    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        raise InvalidArgumentError("not a SolidSeas BOM file", detail={"parameter": "path"})
    if raw.get("schema") != SCHEMA:
        raise InvalidArgumentError(
            f"a BOM file of schema {raw.get('schema')!r}, which this SolidSeas cannot read",
            detail={"parameter": "path"},
        )
    model = raw.get("model")
    if not isinstance(model, dict) or not isinstance(model.get("name"), str):
        raise InvalidArgumentError("the BOM file names no assembly", detail={"parameter": "path"})
    for key in ("relative", "configuration"):
        if model.get(key) is not None and not isinstance(model.get(key), str):
            raise InvalidArgumentError(f"the BOM file's {key} is not text", detail={"parameter": "path"})
    table = raw.get("table")
    if not isinstance(table, list) or not all(
        isinstance(r, list) and all(isinstance(c, str) for c in r) for r in table
    ):
        raise InvalidArgumentError("the BOM file's table is not rows of text", detail={"parameter": "path"})
    keep = {k: model.get(k) for k in ("name", "relative", "configuration")}
    return BomFile(keep, spec_from_json(raw.get("spec")), tuple(tuple(r) for r in table))


@dataclass(frozen=True)
class Loaded:
    bom_file: BomFile
    sha256: str


def read(path: str | os.PathLike) -> Loaded:
    """Read a ``.ssbom``: what it holds and the SHA-256 of its bytes (the next save's
    ``replaces``)."""
    with open(os.fspath(path), "rb") as fh:
        data = fh.read(MAX_BYTES + 1)
    return Loaded(loads(data), hashlib.sha256(data).hexdigest())


def save(bom_file: BomFile, path: str | os.PathLike, *, replaces: str | None = None) -> Saved:
    """Write ``bom_file`` to exactly ``path`` (a ``.ssbom``), by the rules in the module
    notes. Returns the path, SHA-256 and size written."""
    target = os.path.abspath(os.fspath(path))
    if not target.lower().endswith(EXTENSION):
        raise InvalidArgumentError(f"a BOM is saved to a {EXTENSION} file", detail={"parameter": "path"})
    data = dumps(bom_file)
    return _write(
        target,
        lambda fh: fh.write(data),
        replaces=replaces,
        limit=MAX_BYTES,
        limits=DEFAULT_LIMITS,
        bound="drawing_bytes",
    )


def assembly_path(bom_path: str | os.PathLike, bom_file: BomFile) -> str | None:
    """Where the assembly is, from the ``.ssbom``'s folder and the path it records; None
    when it records none."""
    rel = bom_file.model.get("relative")
    if not rel:
        return None
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(os.fspath(bom_path))), rel))


__all__ = [
    "EXTENSION",
    "FORMAT",
    "MAX_BYTES",
    "SCHEMA",
    "BomFile",
    "Loaded",
    "assembly_path",
    "dumps",
    "loads",
    "make",
    "read",
    "save",
]
