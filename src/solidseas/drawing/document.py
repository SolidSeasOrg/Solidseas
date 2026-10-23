"""The drawing file (``.ssdrw``), a new drawing's records, and where Save may write
(``docs/DRAWINGS.md`` 13.1, 13.4, 12.5, 12.6 and 17.2).

**The file.** UTF-8 JSON without a byte order mark, one object, its members in the
fixed order of 13.1, numbers in shortest round-trip form, model quantities in
metres, sheet quantities in millimetres and the laid-out sheet in the compact form
of :func:`.display.to_compact`. Schema ``solidseas.drawing/1``. :func:`dumps` and
:func:`loads` turn a :class:`~.types.Drawing` into bytes and back; :func:`load`,
:func:`read` and :func:`save` do the same with a path.

**Reading is hostile-input reading (17.2).** Before anything else a file is checked
for its size (``drawing_bytes``), strict JSON (no repeated keys, no NaN or
infinity, no number too large to be finite), nesting (``json_depth``), the schema
(major 1; a higher major is refused with a message saying a newer SolidSeas wrote
it), ids (``[a-z0-9-]{1,64}``, none given twice), finite numbers in range, and the
bounds of strings and arrays. A file outside those bounds is refused whole with the
reason. After that every value is checked on its own: one that fails falls back to
its default, or its record is left out, and the reason is listed. Members a newer
SolidSeas wrote, at the top or inside a record, are kept (at most ``unknown_bytes``
of them), never interpreted, and written back where they were.

**Records the core types do not hold.** :class:`DimensionRecord` adds a placement,
a text override and flags to :class:`~.types.PlannedDimension`; :class:`NoteRecord`
adds the note's origin to :class:`~.types.NoteLine`; :class:`DrawingDocument` adds
the file's ``created`` and ``modified`` times and the items accepted at release to
:class:`~.types.Drawing`. Each is a subclass, so code that reads the core types
reads these too.

**Saving (12.6).** :func:`save` writes exactly the path it is given and never picks
a name. A path that exists is refused unless ``replaces`` is given and equals the
file's current SHA-256; a link, a device, a stream or anything but a plain file is
refused; the file is written through a temporary name and a rename. The decisions
around it are helpers: :func:`save_target` and :func:`export_target` apply the
``replace_own_files`` rule of the drawing's settings and return the path to write
and what it may replace, :func:`export_name` and :func:`drawing_file_name` name
files by the settings' pattern through the rules of the viewer's ``safe_stem``,
:func:`next_free_name` gives `` (2)``, `` (3)`` and on, :func:`write_output` writes
an export under the same rules, :func:`record_output` records it, and
:func:`folder_problem` checks a folder as the 3D Print file's folder is checked.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
import re
import stat
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, fields, replace
from typing import Any

from .. import __version__
from ..bomtable import spec_from_json
from ..errors import DrawingInvalidError, InvalidArgumentError, OutputRefusedError, SldLimitError
from . import display, numbers, standards, types
from . import settings as settings_mod
from .limits import DEFAULT_LIMITS, DrawingLimits
from .types import (
    Datum,
    Descriptor,
    DrawingOptions,
    FeatureRecord,
    FrameCell,
    NoteLine,
    Output,
    PlannedDimension,
    Position,
    Revision,
    Signature,
    TitleField,
)

SCHEMA = "solidseas.drawing/1"
SCHEMA_PREFIX = "solidseas.drawing/"
EXTENSION = ".ssdrw"
GENERATOR = "SolidSeas"
EXPORT_EXTENSIONS = {"pdf": ".pdf", "dxf": ".dxf"}
PRELIMINARY_SUFFIX = " PRELIMINARY"
FIRST_DESCRIPTION = "INITIAL RELEASE"
BOM = b"\xef\xbb\xbf"

# Members in the order of DRAWINGS.md 13.1. ``datums`` (C28) follows the features and
# ``accepted`` (what Release accepted, with the typed reasons) follows the signatures.
MEMBERS = (
    "schema",
    "id",
    "generator",
    "created",
    "modified",
    "model",
    "options",
    "settings",
    "title",
    "features",
    "datums",
    "dimensions",
    "notes",
    "status",
    "signatures",
    "accepted",
    "revisions",
    "outputs",
    "next_id",
    "sheet",
)
MODEL_KEYS = (
    "name",
    "relative",
    "stored",
    "format",
    "configuration",
    "sha256",
    "geometry",
    "properties",
    "part_number",
    "model_revision",
    "units",
    "extents",
)
OPTION_KEYS = (
    "process",
    "profile",
    "units",
    "scheme",
    "arrangement",
    "front",
    "views",
    "sheet",
    "scale",
    "hidden",
    "tangent",
    "bodies",
    "quality",
    "configuration",
    "parts_list",
    "detail",
    "balloons",
    "mode",
    "view_sheets",
)
DIMENSION_KEYS = (
    "key",
    "id",
    "origin",
    "state",
    "view",
    "placement",
    "text",
    "precision",
    "tolerance",
    "frame",
    "kind",
    "role",
    "axis",
    "features",
    "serves",
    "value",
    "positions",
    "anchor",
    "radius",
    "side",
    "flags",
)
# The title fields the settings' title sources name, in the order a title block reads them.
TITLE_KEYS = ("title", "number", "part_number", "revision", "model_revision", "material", "finish")
# Flags a dimension record carries: set by regeneration (new, changed, needs_attention,
# placement_reset) and by the editor (user_tolerance, user_frame: overrides to keep).
DIMENSION_FLAGS = ("new", "changed", "needs_attention", "placement_reset", "user_tolerance", "user_frame")
NOTE_ORIGINS = ("template", "user")
# A dimension's tolerance: the kinds of numbers.Tolerance, and ``derived`` (a full-round
# end's R, stated by the size and the width, convention 5).
TOLERANCES = (*numbers.TOLERANCE_KINDS, "derived")

# Bounds of the records in a file, beyond DrawingLimits (17.1).
MAX_ARRAY = 10_000  # any array outside the sheet
MAX_MEMBERS = 2_000  # members of any object outside the sheet
MAX_NUMBER = 1e15  # any number in the file, by magnitude
MAX_INT_DIGITS = 20
MAX_TITLE_FIELDS = 64
MAX_NOTES = 400
MAX_REVISIONS = 1_000
MAX_OUTPUTS = 1_000
MAX_DATUMS = 26
MAX_ACCEPTED = 1_000
MAX_ZONES = 200
MAX_NAME = 255  # a file name
MAX_PATH = 1_024  # a path's text
MAX_ID_NUMBER = 1_000_000_000
MAX_STEM = 80  # the viewer's printing.MAX_STEM
MAX_TRIES = 1_000  # names tried past the first, as printing.MAX_TRIES
HASH_CHUNK = 1 << 20

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_KEY = re.compile(r"[a-z0-9_]+(?:[/][a-z0-9_-]+)*")
_FIELD_KEY = re.compile(r"[a-z][a-z0-9_]{0,31}")
_NAME_KEY = re.compile(r"[a-z][a-z0-9_]{0,63}")
_TYPE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}")  # a descriptor's type: Hole, Width, Blend...
_HEX64 = re.compile(r"[0-9a-f]{64}")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_ZONE = re.compile(r"[A-Z]{1,2}[0-9]{1,3}")
_LETTER = re.compile(r"[A-Z]{1,2}")
_FLAG = re.compile(r"[a-z][a-z_]{0,31}")
_SIDE = re.compile(r"[a-z_]{1,16}")
# The viewer's printing.safe_stem rules, mirrored here so the library never imports the viewer.
_RESERVED = re.compile(r"(CON|PRN|AUX|NUL|COM[0-9¹²³]|LPT[0-9¹²³]) *(\..*)?", re.I)
_UNSAFE = re.compile(r"[^\w .,()+\-]")
_PATTERN_TOKEN = re.compile(r"\{([a-z_]+)\}")
_PDF_PRODUCER = re.compile(rb"/Producer\s*\(SolidSeas[ )]")
_LINE_BREAKS = {"\u2028": "\\u2028", "\u2029": "\\u2029", "\u0085": "\\u0085"}


# --------------------------------------------------------------------------- records


@dataclass(frozen=True)
class Placement:
    """Where the user put a dimension, relative to its attach points (13.4): offsets
    along and across the dimension in paper millimetres, the track index, and whether
    the user moved it (a placement layout chose is not kept across a regeneration)."""

    along_mm: float = 0.0
    across_mm: float = 0.0
    track: int = 0
    moved: bool = False

    def __post_init__(self) -> None:
        for name in ("along_mm", "across_mm"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > 1e4:
                raise InvalidArgumentError(
                    f"{name} must be a length on the sheet", detail={"parameter": name}
                )
        if not isinstance(self.track, int) or isinstance(self.track, bool) or not 0 <= self.track <= 1000:
            raise InvalidArgumentError("track must be 0 to 1000", detail={"parameter": "track"})
        if not isinstance(self.moved, bool):
            raise InvalidArgumentError("moved must be true or false", detail={"parameter": "moved"})


@dataclass(frozen=True)
class DimensionRecord(PlannedDimension):
    """A dimension as the drawing keeps it (6.8, 13.1): the planned dimension and the
    user's placement, text override and the flags regeneration and the editor set."""

    placement: Placement | None = None
    override: str | None = None
    flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.placement is not None and not isinstance(self.placement, Placement):
            raise InvalidArgumentError("placement must be a Placement", detail={"parameter": "placement"})
        if self.override is not None and (not isinstance(self.override, str) or len(self.override) > 256):
            raise InvalidArgumentError("override must be text", detail={"parameter": "override"})
        if not isinstance(self.flags, tuple) or not all(
            isinstance(f, str) and _FLAG.fullmatch(f) for f in self.flags
        ):
            raise InvalidArgumentError("flags must be words", detail={"parameter": "flags"})


@dataclass(frozen=True)
class NoteRecord(NoteLine):
    """A note as the drawing keeps it: ``template`` (from the settings' templates) or
    ``user`` (typed in the editor). Notes are never regenerated (13.5)."""

    origin: str = "template"

    def __post_init__(self) -> None:
        if self.origin not in NOTE_ORIGINS:
            raise InvalidArgumentError("a note's origin is template or user", detail={"parameter": "origin"})


@dataclass(frozen=True)
class DrawingDocument(types.Drawing):
    """A :class:`~.types.Drawing` with the file's own members: when it was made and last
    saved (ISO 8601 with the local offset), and the items Release accepted with the
    user's typed reasons, as (item, reason)."""

    created: str | None = None
    modified: str | None = None
    accepted: tuple[tuple[str, str], ...] = ()


def as_record(dimension: PlannedDimension) -> DimensionRecord:
    """``dimension`` as a :class:`DimensionRecord` (itself when it is one)."""
    if isinstance(dimension, DimensionRecord):
        return dimension
    if not isinstance(dimension, PlannedDimension):
        raise InvalidArgumentError(
            "a dimension must be a PlannedDimension", detail={"parameter": "dimension"}
        )
    return DimensionRecord(**{f.name: getattr(dimension, f.name) for f in fields(PlannedDimension)})


def as_document(drawing: types.Drawing) -> DrawingDocument:
    """``drawing`` as a :class:`DrawingDocument` (itself when it is one)."""
    if isinstance(drawing, DrawingDocument):
        return drawing
    if not isinstance(drawing, types.Drawing):
        raise InvalidArgumentError("drawing must be a Drawing", detail={"parameter": "drawing"})
    return DrawingDocument(**{f.name: getattr(drawing, f.name) for f in fields(types.Drawing)})


def next_number(drawing: types.Drawing, prefix: str) -> int:
    """The next free number of ids ``prefix-N`` (``f``, ``d``, ``n``, ``v``) in ``drawing``."""
    return dict(drawing.next_id).get(prefix, 1)


def id_number(ident: str, prefix: str) -> int | None:
    """N of an id ``prefix-N``, or None."""
    m = re.fullmatch(re.escape(prefix) + r"-([0-9]{1,9})", ident or "")
    return int(m.group(1)) if m else None


# --------------------------------------------------------------------------- errors


class DrawingFileError(DrawingInvalidError):
    """A ``.ssdrw`` refused whole: not a SolidSeas drawing, not strict JSON, written by a
    newer SolidSeas, or outside the bounds of 17.2. ``detail["rule"]`` is
    ``drawing_invalid`` and ``detail["value"]`` names the check; the error code is
    ``drawing_invalid`` (an ``InvalidArgumentError`` still)."""


def _refuse(message: str, reason: str) -> DrawingFileError:
    return DrawingFileError(
        message, detail={"parameter": "drawing", "rule": "drawing_invalid", "value": reason}
    )


class _Bad(ValueError):
    """A value failed its own check; the message says why."""


# --------------------------------------------------------------------------- writing


def _jsonable(value: Any, where: str) -> Any:
    """``value`` as plain JSON values: tuples become lists; floats must be finite."""
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidArgumentError(
                f"{where} holds a number that is not finite", detail={"parameter": where}
            )
        return value
    if isinstance(value, (tuple, list)):
        return [_jsonable(v, where) for v in value]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise InvalidArgumentError(
                    f"{where} holds a key that is not text", detail={"parameter": where}
                )
            out[k] = _jsonable(v, where)
        return out
    raise InvalidArgumentError(f"{where} cannot hold a {type(value).__name__}", detail={"parameter": where})


def _pointer(*parts: str) -> str:
    """A JSON pointer to a record, its parts escaped: where an unknown member is put back."""
    return "".join("/" + p.replace("~", "~0").replace("/", "~1") for p in parts)


def _profile(settings: Any) -> str:
    return settings.standard.profile if isinstance(settings, settings_mod.DrawingSettings) else "asme"


def _options_out(o: DrawingOptions, settings: Any) -> dict:
    out = _options_core(o, settings)
    if o.parts_list is not None:  # written only when set, so other drawings' files stay as they were
        out["parts_list"] = json.loads(o.parts_list)
    if o.detail != "full":  # likewise: a fully defined drawing's file is as it always was
        out["detail"] = o.detail
    if o.balloons:  # likewise: balloons the user moved, {item: [dx, dy]}
        out["balloons"] = {item: [dx, dy] for item, dx, dy in o.balloons}
    if o.mode != "expert":  # likewise: how an Express drawing was started
        out["mode"] = o.mode
    if o.view_sheets:  # likewise: the views put on a sheet after the first, {view: sheet}
        out["view_sheets"] = {view: number for view, number in o.view_sheets}
    return out


def _options_core(o: DrawingOptions, settings: Any) -> dict:
    return {
        "process": o.process,
        "profile": _profile(settings),
        "units": o.units,
        "scheme": o.scheme,
        "arrangement": {k: v for k, v in o.arrangement},
        "front": {"direction": o.front, "turn": o.turn},
        "views": o.views if o.views == "auto" else list(o.views),
        "sheet": o.sheet,
        "scale": o.scale if o.scale == "auto" else list(o.scale),
        "hidden": o.hidden,
        "tangent": o.tangent,
        "bodies": None if o.bodies is None else list(o.bodies),
        "quality": o.quality,
        "configuration": o.configuration,
    }


def _frame_out(f: FrameCell | None) -> dict | None:
    if f is None:
        return None
    return {
        "characteristic": f.characteristic,
        "value": f.value,
        "diameter": f.diameter,
        "modifier": f.modifier,
        "datums": list(f.datums),
    }


def _dimension_out(d: PlannedDimension) -> dict:
    placement = getattr(d, "placement", None)
    tolerance: dict[str, Any] = {"type": d.tolerance}
    if tuple(d.tolerance_values) != (0.0, 0.0):
        tolerance["values"] = list(d.tolerance_values)
    return {
        "key": d.key,
        "id": d.id,
        "origin": d.origin,
        "state": d.state,
        "view": d.view,
        "placement": None
        if placement is None
        else {
            "along_mm": placement.along_mm,
            "across_mm": placement.across_mm,
            "track": placement.track,
            "moved": placement.moved,
        },
        "text": {"prefix": d.prefix, "suffix": list(d.suffix), "override": getattr(d, "override", None)},
        "precision": {"places": d.places, "source": d.places_source},
        "tolerance": tolerance,
        "frame": _frame_out(d.frame),
        "kind": d.kind,
        "role": d.role,
        "axis": d.axis,
        "features": list(d.features),
        "serves": list(d.serves),
        "value": d.value,
        "positions": [
            {"value": p.value, "centre": p.centre, "radius": p.radius, "features": list(p.features)}
            for p in d.positions
        ],
        "anchor": None if d.anchor is None else list(d.anchor),
        "radius": d.radius,
        "side": d.side,
        "flags": list(getattr(d, "flags", ())),
    }


def _note_out(ident: str, note: NoteLine) -> dict:
    out: dict[str, Any] = {"id": ident, "origin": getattr(note, "origin", "template"), "text": note.text}
    if note.frames:
        out["frames"] = [_frame_out(f) for f in note.frames]
    return out


def _model_out(model: Mapping[str, Any]) -> dict:
    out = {k: model.get(k) for k in MODEL_KEYS}
    for k, v in model.items():
        if k not in out:
            out[k] = v
    return out


def member_values(drawing: types.Drawing) -> dict[str, Any]:
    """Every member of the file as plain JSON values, without the unknown members a
    newer SolidSeas wrote: what :func:`dumps` writes and what a content digest reads."""
    s = drawing.settings
    if s is not None and not isinstance(s, settings_mod.DrawingSettings):
        raise InvalidArgumentError(
            "a drawing's settings must be DrawingSettings", detail={"parameter": "settings"}
        )
    if not isinstance(drawing.options, DrawingOptions):
        raise InvalidArgumentError(
            "a drawing's options must be DrawingOptions", detail={"parameter": "options"}
        )
    sheet = drawing.sheet
    if sheet is not None and not isinstance(sheet, display.Sheet):
        raise InvalidArgumentError("a drawing's sheet must be a display Sheet", detail={"parameter": "sheet"})
    out = {
        "schema": SCHEMA,
        "id": types.check_id(drawing.id, "drawing id"),
        "generator": {"name": GENERATOR, "version": __version__},
        "created": getattr(drawing, "created", None),
        "modified": getattr(drawing, "modified", None),
        "model": _model_out(drawing.model or {}),
        "options": _options_out(drawing.options, s),
        "settings": None if s is None else settings_mod.to_dict(s),
        "title": {k: {"text": f.text, "from": f.source} for k, f in drawing.title},
        "features": [
            {"id": r.id, "descriptor": r.descriptor.to_dict(), "decisions": {k: v for k, v in r.decisions}}
            for r in drawing.features
        ],
        "datums": [{"letter": d.letter, "face": d.face, "reason": d.reason} for d in drawing.datums],
        "dimensions": [_dimension_out(d) for d in drawing.dimensions],
        "notes": [_note_out(i, n) for i, n in drawing.notes],
        "status": drawing.status,
        "signatures": [
            {"row": g.row, "name": g.name, "date": g.date, "digest": g.digest} for g in drawing.signatures
        ],
        "accepted": [{"item": i, "reason": r} for i, r in getattr(drawing, "accepted", ())],
        "revisions": [
            {
                "rev": r.rev,
                "zones": list(r.zones),
                "description": r.description,
                "date": r.date,
                "approved": r.approved,
            }
            for r in drawing.revisions
        ],
        "outputs": [
            {
                "kind": o.kind,
                "name": o.name,
                "sha256": o.sha256,
                "revision": o.revision,
                "released": o.released,
            }
            for o in drawing.outputs
        ],
        "next_id": {k: n for k, n in drawing.next_id},
        "sheet": None if sheet is None else display.to_compact(sheet),
    }
    return {k: _jsonable(v, k) for k, v in out.items()}


def _split_unknown(unknown: Iterable[tuple[str, Any]]) -> tuple[dict[str, dict], list[tuple[str, Any]]]:
    nested: dict[str, dict] = {}
    top: list[tuple[str, Any]] = []
    for name, value in unknown:
        if isinstance(name, str) and name.startswith("/"):
            if isinstance(value, dict):
                nested.setdefault(name, {}).update(value)
        elif isinstance(name, str):
            top.append((name, value))
    return nested, top


def _put_back(members: dict[str, Any], nested: Mapping[str, dict]) -> None:
    """Put the unknown members of records back after their known ones."""
    if not nested:
        return

    def extra(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            for k, v in nested.get(path, {}).items():
                obj.setdefault(k, v)

    extra(members["options"], "/options")
    for k, field_value in members["title"].items():
        extra(field_value, _pointer("title", k))
    for rec in members["features"]:
        base = _pointer("features", rec["id"])
        extra(rec, base)
        extra(rec["descriptor"], base + "/descriptor")
    for rec in members["dimensions"]:
        base = _pointer("dimensions", rec["id"])
        extra(rec, base)
        for sub in ("placement", "text", "precision", "tolerance", "frame"):
            extra(rec.get(sub), f"{base}/{sub}")
    for rec in members["notes"]:
        extra(rec, _pointer("notes", rec["id"]))
    for rec in members["datums"]:
        extra(rec, _pointer("datums", rec["letter"]))
    for rec in members["signatures"]:
        extra(rec, _pointer("signatures", rec["row"]))
    for rec in members["revisions"]:
        extra(rec, _pointer("revisions", rec["rev"]))
    for rec in members["outputs"]:
        extra(rec, _pointer("outputs", rec["name"]))
    extra(members["model"].get("units"), "/model/units")
    extra(members["options"].get("front"), "/options/front")


def _encode(value: Any, compact: bool = False) -> str:
    sep = (",", ":") if compact else (", ", ": ")
    text = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=sep)
    for c, esc in _LINE_BREAKS.items():
        text = text.replace(c, esc)
    return text


RECORD_MEMBERS = (
    "features",
    "datums",
    "dimensions",
    "notes",
    "signatures",
    "accepted",
    "revisions",
    "outputs",
)


def dumps(drawing: types.Drawing, *, limits: DrawingLimits = DEFAULT_LIMITS) -> bytes:
    """The ``.ssdrw`` bytes of ``drawing``: UTF-8 JSON without a byte order mark, its
    members in the order of 13.1, one record a line, the sheet compact on its own
    line, a newline at the end. The same drawing always gives the same bytes."""
    if not isinstance(drawing, types.Drawing):
        raise InvalidArgumentError("drawing must be a Drawing", detail={"parameter": "drawing"})
    members = member_values(drawing)
    nested, top = _split_unknown(drawing.unknown)
    _put_back(members, nested)
    raw_sheet = dict(top).get("sheet")
    if members["sheet"] is None and raw_sheet is not None:
        members["sheet"] = raw_sheet  # a sheet this SolidSeas could not read, written back as it came
    items = list(members.items()) + [(k, v) for k, v in top if k not in members]
    lines = []
    for k, v in items:
        key = _encode(k)
        if k in RECORD_MEMBERS and isinstance(v, list) and v:
            body = "[\n" + ",\n".join("    " + _encode(r) for r in v) + "\n  ]"
        elif k == "sheet":
            body = _encode(v, compact=True)
            if v is not None and len(body.encode("utf-8")) > limits.sheet_bytes:
                raise limits.exceeded("sheet_bytes", "the laid-out sheet is larger than a drawing file holds")
        else:
            body = _encode(v)
        lines.append(f"  {key}: {body}")
    text = "{\n" + ",\n".join(lines) + "\n}\n"
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError:
        raise InvalidArgumentError(
            "the drawing holds text that is not valid Unicode", detail={"parameter": "drawing"}
        ) from None
    if len(data) > limits.drawing_bytes:
        raise limits.exceeded("drawing_bytes", "the drawing is larger than a drawing file holds")
    return data


# --------------------------------------------------------------------------- reading: whole-file checks


def _strict(text: str) -> Any:
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ValueError(f"the member {k[:40]!r} appears twice in one object")
            out[k] = v
        return out

    def constant(name):
        raise ValueError(f"{name} is not a number a drawing file may hold")

    def number(text):
        v = float(text)
        if not math.isfinite(v):
            raise ValueError("a number is too large to be finite")
        return v

    def whole(text):
        if len(text.lstrip("-")) > MAX_INT_DIGITS:
            raise ValueError("a whole number has too many digits")
        return int(text)

    return json.loads(
        text, object_pairs_hook=pairs, parse_constant=constant, parse_float=number, parse_int=whole
    )


def _prewalk(value: Any, depth: int, in_sheet: bool, limits: DrawingLimits) -> None:
    if depth > limits.json_depth:
        raise limits.exceeded(
            "json_depth", f"the drawing file is nested more than {limits.json_depth} levels deep"
        )
    if isinstance(value, dict):
        if not in_sheet and len(value) > MAX_MEMBERS:
            raise _refuse(f"an object in the drawing file has more than {MAX_MEMBERS:,} members", "members")
        for k, v in value.items():
            _prewalk(k, depth + 1, in_sheet, limits)
            _prewalk(v, depth + 1, in_sheet or (depth == 0 and k == "sheet"), limits)
    elif isinstance(value, list):
        if not in_sheet and len(value) > MAX_ARRAY:
            raise _refuse(f"an array in the drawing file has more than {MAX_ARRAY:,} entries", "array_bounds")
        for v in value:
            _prewalk(v, depth + 1, in_sheet, limits)
    elif isinstance(value, str):
        if not in_sheet and len(value) > limits.string_chars:
            raise limits.exceeded(
                "string_chars",
                f"a text in the drawing file is longer than {limits.string_chars:,} characters",
            )
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise _refuse("a text in the drawing file is not valid Unicode", "unicode") from None
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, (int, float)):
        if abs(value) > MAX_NUMBER:
            raise _refuse("a number in the drawing file is out of range", "number_range")


def _schema_major(schema: Any) -> int:
    if not isinstance(schema, str) or not schema.startswith(SCHEMA_PREFIX):
        raise _refuse("the file is not a SolidSeas drawing (it names no solidseas.drawing schema)", "schema")
    m = re.fullmatch(r"([0-9]{1,4})(?:\.[0-9]{1,4})?", schema[len(SCHEMA_PREFIX) :])
    if not m:
        raise _refuse("the file names a drawing schema SolidSeas does not know", "schema")
    major = int(m.group(1))
    if major > 1:
        raise _refuse(
            f"the drawing was written by a newer SolidSeas ({schema[:40]}); update SolidSeas to open it",
            "schema_newer",
        )
    if major < 1:
        raise _refuse("the file names a drawing schema SolidSeas does not know", "schema")
    return major


def _ids(raw: dict, limits: DrawingLimits) -> None:
    """Every id in the file matches ``[a-z0-9-]{1,64}`` and none is given twice, or the
    file is refused whole (17.2); and the record arrays are within their bounds."""

    def check(value: Any, what: str) -> None:
        if not isinstance(value, str) or not types.ID_PATTERN.fullmatch(value):
            raise _refuse(f"the drawing file holds a {what} that is not an id", "id")

    check(raw.get("id"), "drawing id")
    bounds = {
        "features": limits.requirements,
        "dimensions": limits.requirements,
        "notes": MAX_NOTES,
        "datums": MAX_DATUMS,
        "signatures": len(settings_mod.APPROVAL_ROWS),
        "accepted": MAX_ACCEPTED,
        "revisions": MAX_REVISIONS,
        "outputs": MAX_OUTPUTS,
    }
    for name, bound in bounds.items():
        value = raw.get(name)
        if isinstance(value, list) and len(value) > bound:
            if name in ("features", "dimensions"):
                raise limits.exceeded("requirements", f"the drawing file holds more than {bound:,} {name}")
            raise _refuse(f"the drawing file holds more than {bound:,} {name}", "array_bounds")
    if isinstance(raw.get("title"), dict) and len(raw["title"]) > MAX_TITLE_FIELDS:
        raise _refuse(f"the drawing file holds more than {MAX_TITLE_FIELDS} title fields", "array_bounds")
    for name, what in (("features", "feature id"), ("dimensions", "dimension id"), ("notes", "note id")):
        records = raw.get(name)
        if not isinstance(records, list):
            continue
        seen: set[str] = set()
        for rec in records:
            if not isinstance(rec, dict):
                continue
            ident = rec.get("id")
            check(ident, what)
            if ident in seen:
                raise _refuse(f"the drawing file names {what} {ident} twice", "id_twice")
            seen.add(ident)
            if name == "dimensions":
                if "view" in rec:
                    check(rec["view"], "view id")
                refs = rec.get("features")
                if isinstance(refs, list):
                    for ref in refs:
                        check(ref, "feature id")
                positions = rec.get("positions")
                if isinstance(positions, list):
                    for p in positions:
                        if isinstance(p, dict) and isinstance(p.get("features"), list):
                            for ref in p["features"]:
                                check(ref, "feature id")


# --------------------------------------------------------------------------- reading: values


def _text(v: Any, limit: int, *, empty: bool = True) -> str:
    if not isinstance(v, str):
        raise _Bad("it is not text")
    if len(v) > limit:
        raise _Bad(f"it is longer than {limit:,} characters")
    if _CONTROL.search(v):
        raise _Bad("it holds control characters")
    if not empty and not v.strip():
        raise _Bad("it is empty")
    return v


def _opt(check: Callable[..., Any], v: Any, *args: Any, **kw: Any) -> Any:
    return None if v is None else check(v, *args, **kw)


def _hex64(v: Any) -> str:
    if not isinstance(v, str) or not _HEX64.fullmatch(v):
        raise _Bad("it is not a SHA-256")
    return v


def _number(v: Any, low: float, high: float) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not low <= v <= high:
        raise _Bad(f"it is not a number from {low:g} to {high:g}")
    return float(v)


def _whole(v: Any, low: int, high: int) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not low <= v <= high:
        raise _Bad(f"it is not a whole number from {low:,} to {high:,}")
    return v


def _flag(v: Any) -> bool:
    if not isinstance(v, bool):
        raise _Bad("it is not true or false")
    return v


def _one_of(v: Any, choices: Iterable[Any]) -> Any:
    choices = tuple(choices)
    if isinstance(v, bool) or v not in choices:
        raise _Bad("it is not one of " + ", ".join(str(c) for c in choices))
    return v


def _date(v: Any) -> str:
    if not isinstance(v, str) or not _DATE.fullmatch(v):
        raise _Bad("it is not a date written YYYY-MM-DD")
    try:
        datetime.date.fromisoformat(v)
    except ValueError:
        raise _Bad("it is not a date") from None
    return v


def _timestamp(v: Any) -> str:
    if not isinstance(v, str) or len(v) > 40:
        raise _Bad("it is not a time")
    try:
        datetime.datetime.fromisoformat(v)
    except ValueError:
        raise _Bad("it is not a time written in ISO 8601") from None
    return v


def _value(v: Any, depth: int = 0) -> Any:
    """A JSON value kept in a descriptor or a decision: scalars and arrays (as tuples)."""
    if v is None or isinstance(v, (bool, str, int, float)):
        if isinstance(v, str) and len(v) > 256:
            raise _Bad("it holds text longer than 256 characters")
        return v
    if isinstance(v, list) and depth < 4:
        return tuple(_value(x, depth + 1) for x in v)
    raise _Bad("it holds a value of a kind a descriptor does not")


def _pairs(v: Any, limit: int = 64) -> tuple[tuple[str, Any], ...]:
    if not isinstance(v, dict):
        raise _Bad("it is not an object")
    if len(v) > limit:
        raise _Bad(f"it has more than {limit} members")
    out = []
    for k, x in v.items():
        if not _NAME_KEY.fullmatch(k):
            raise _Bad(f"{k[:40]!r} is not a name it may hold")
        out.append((k, _value(x)))
    return tuple(out)


def _descriptor(v: Any) -> Descriptor:
    if not isinstance(v, dict):
        raise _Bad("it is not an object")
    kind = v.get("type")
    if not isinstance(kind, str) or not _TYPE_NAME.fullmatch(kind):
        raise _Bad("its type is not a name")
    position = v.get("position", [])
    if not isinstance(position, list) or len(position) > 16:
        raise _Bad("its position is not a list of numbers")
    return Descriptor(
        kind,
        _pairs(v.get("size", {})),
        _pairs(v.get("adjacency", {})),
        tuple(_number(p, -1e6, 1e6) for p in position),
    )


def _decision_value(v: Any, depth: int = 0) -> Any:
    if v is None or isinstance(v, (bool, str, int, float)):
        if isinstance(v, str) and len(v) > 256:
            raise _Bad("it holds text longer than 256 characters")
        return v
    if depth >= 4:
        raise _Bad("it is nested too deeply")
    if isinstance(v, list):
        return tuple(_decision_value(x, depth + 1) for x in v)
    if isinstance(v, dict):
        return {k: _decision_value(x, depth + 1) for k, x in _checked_keys(v).items()}
    raise _Bad("it holds a value of a kind a decision does not")


def _decisions(v: Any) -> tuple[tuple[str, Any], ...]:
    if not isinstance(v, dict):
        raise _Bad("it is not an object")
    return tuple((k, _decision_value(x)) for k, x in _checked_keys(v).items())


def _checked_keys(v: dict) -> dict:
    if len(v) > 64:
        raise _Bad("it has more than 64 members")
    for k in v:
        if not _NAME_KEY.fullmatch(k):
            raise _Bad(f"{k[:40]!r} is not a name it may hold")
    return v


def _frame(v: Any) -> FrameCell:
    if not isinstance(v, dict):
        raise _Bad("it is not a feature control frame")
    datums = v.get("datums", [])
    if not isinstance(datums, list) or len(datums) > 3:
        raise _Bad("its datums are not up to three letters")
    return FrameCell(
        _one_of(v.get("characteristic"), standards.CHARACTERISTICS),
        _number(v.get("value"), 0.0, 1e3),
        _flag(v.get("diameter", False)),
        _opt(_one_of, v.get("modifier"), ("mmc", "lmc")),
        tuple(_letter(d) for d in datums),
    )


def _letter(v: Any) -> str:
    if not isinstance(v, str) or not _LETTER.fullmatch(v):
        raise _Bad("it is not a datum letter")
    return v


def _file_name(v: Any) -> str:
    text = _text(v, MAX_NAME, empty=False)
    if any(c in text for c in '/\\:*?"<>|') or text.strip(" .") != text or text in (".", ".."):
        raise _Bad("it is not a plain file name")
    return text


class _Reader:
    """One file's reading: the problems found and the unknown members kept."""

    def __init__(self, limits: DrawingLimits) -> None:
        self.limits = limits
        self.problems: list[str] = []
        self.unknown: list[tuple[str, Any]] = []
        self.unknown_bytes = 0

    def problem(self, where: str, why: Any, then: str = "the default is used") -> None:
        self.problems.append(f"{where}: {why}; {then}")

    def count(self, value: Any) -> None:
        size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8", "replace"))
        self.unknown_bytes += size
        if self.unknown_bytes > self.limits.unknown_bytes:
            raise self.limits.exceeded(
                "unknown_bytes",
                "the drawing file holds more members this SolidSeas does not know than it keeps",
            )

    def keep(self, name: str, value: Any) -> None:
        self.count(value)
        self.unknown.append((name, value))

    def extras(self, obj: Any, known: Iterable[str], path: str) -> None:
        if not isinstance(obj, dict):
            return
        known = set(known)
        extra = {k: v for k, v in obj.items() if k not in known}
        if extra:
            self.keep(path, extra)

    def field(self, where: str, obj: dict, key: str, check: Callable[[Any], Any], default: Any) -> Any:
        if key not in obj:
            return default
        try:
            return check(obj[key])
        except (ValueError, TypeError) as exc:
            self.problem(f"{where}.{key}", exc)
            return default

    # The members, in file order.

    def model(self, raw: Any) -> dict:
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            self.problem("model", "it is not an object", "the model is not known")
            return {}
        L = self.limits

        def units(v: Any) -> dict:
            if not isinstance(v, dict):
                raise _Bad("it is not an object")
            self.extras(v, ("unit", "origin"), "/model/units")
            return {
                "unit": _one_of(v.get("unit"), ("in", "mm")),
                "origin": _one_of(v.get("origin"), ("file", "guessed", "user")),
            }

        def extents(v: Any) -> list:
            if not isinstance(v, list) or len(v) != 3:
                raise _Bad("it is not three ranges")
            out = []
            for r in v:
                if not isinstance(r, list) or len(r) != 2:
                    raise _Bad("it is not three ranges")
                lo, hi = _number(r[0], -1e3, 1e3), _number(r[1], -1e3, 1e3)
                if hi < lo:
                    raise _Bad("a range ends before it starts")
                out.append([lo, hi])
            return out

        checks: dict[str, Callable[[Any], Any]] = {
            "name": lambda v: _opt(_text, v, MAX_NAME),
            "relative": lambda v: _opt(_text, v, MAX_PATH),
            "stored": lambda v: _opt(_text, v, MAX_PATH),
            "format": lambda v: _opt(_text, v, 32),
            "configuration": lambda v: _opt(_text, v, L.title_chars),
            "sha256": lambda v: _opt(_hex64, v),
            "geometry": lambda v: _opt(_hex64, v),
            "properties": lambda v: _opt(_hex64, v),
            "part_number": lambda v: _opt(_text, v, L.title_chars),
            "model_revision": lambda v: _opt(_text, v, L.title_chars),
            "units": lambda v: _opt(units, v),
            "extents": lambda v: _opt(extents, v),
        }
        out: dict[str, Any] = {}
        for k in MODEL_KEYS:
            out[k] = self.field("model", raw, k, checks[k], None)
        extra = {k: v for k, v in raw.items() if k not in out}
        if extra:
            self.count(extra)  # unknown model members live in the model itself, written back after the rest
            out.update(extra)
        return out

    def options(self, raw: Any) -> DrawingOptions:
        if not isinstance(raw, dict):
            self.problem("options", "it is not an object", "the defaults are used")
            return DrawingOptions()
        self.extras(raw, OPTION_KEYS, "/options")
        front = raw.get("front", {})
        if not isinstance(front, dict):
            self.problem("options.front", "it is not an object")
            front = {}
        self.extras(front, ("direction", "turn"), "/options/front")
        found: dict[str, Any] = {}

        def seq(v: Any) -> Any:
            return tuple(v) if isinstance(v, list) else v

        if "process" in raw:
            found["process"] = raw["process"]
        if "units" in raw:
            found["units"] = raw["units"]
        if "scheme" in raw:
            found["scheme"] = raw["scheme"]
        if "arrangement" in raw:
            a = raw["arrangement"]
            found["arrangement"] = tuple(a.items()) if isinstance(a, dict) else a
        if "direction" in front:
            found["front"] = front["direction"]
        if "turn" in front:
            found["turn"] = front["turn"]
        if "views" in raw:
            found["views"] = seq(raw["views"])
        for k in ("sheet", "hidden", "tangent", "quality"):
            if k in raw:
                found[k] = raw[k]
        if "scale" in raw:
            found["scale"] = seq(raw["scale"])
        if "bodies" in raw:
            b = raw["bodies"]
            found["bodies"] = None if b is None else seq(b)
        if "configuration" in raw:
            found["configuration"] = raw["configuration"]
        if "detail" in raw:
            found["detail"] = raw["detail"]
        if "mode" in raw:
            found["mode"] = raw["mode"]
        if "view_sheets" in raw:
            v = raw["view_sheets"]
            found["view_sheets"] = tuple(v.items()) if isinstance(v, dict) else v
        if "balloons" in raw:
            b = raw["balloons"]
            if isinstance(b, dict) and all(isinstance(v, list) and len(v) == 2 for v in b.values()):
                found["balloons"] = tuple((k, v[0], v[1]) for k, v in b.items())
            else:
                self.problem(
                    "options.balloons", "it is not an object of item: [dx, dy]", "they are placed again"
                )
        if raw.get("parts_list") is not None:
            try:
                found["parts_list"] = types.parts_list_text(spec_from_json(raw["parts_list"]))
            except InvalidArgumentError as exc:
                self.problem("options.parts_list", exc, "the default parts list is used")
        if raw.get("profile", "asme") not in standards.PROFILES:
            self.problem("options.profile", "it is not a profile this SolidSeas draws", "ASME is used")
        kw: dict[str, Any] = {}
        for k, v in found.items():
            try:
                if k == "configuration":
                    _opt(_text, v, self.limits.title_chars)
                elif k == "bodies" and v is not None:
                    if not isinstance(v, tuple) or len(v) > self.limits.bodies:
                        raise _Bad("it is not a list of body names")
                    for name in v:
                        _text(name, self.limits.title_chars)
                DrawingOptions(**{k: v})
                kw[k] = v
            except (ValueError, TypeError) as exc:
                self.problem(f"options.{k}", exc)
        return DrawingOptions(**kw)

    def settings(self, raw: Any) -> settings_mod.DrawingSettings:
        if not isinstance(raw, dict):
            self.problem(
                "settings", "the snapshot is missing or not an object", "the default settings are used"
            )
            return settings_mod.DrawingSettings()
        try:
            loaded, problems = settings_mod.from_dict(raw)
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            self.problem(
                "settings",
                f"the snapshot could not be read ({type(exc).__name__})",
                "the default settings are used",
            )
            return settings_mod.DrawingSettings()
        self.problems.extend(f"settings: {p}" for p in problems)
        return loaded

    def title(self, raw: Any) -> tuple[tuple[str, TitleField], ...]:
        if raw is None:
            return ()
        if not isinstance(raw, dict):
            self.problem("title", "it is not an object", "no title field is read")
            return ()
        out = []
        for k, v in raw.items():
            try:
                if not _FIELD_KEY.fullmatch(k):
                    raise _Bad("it is not the name of a title field")
                if not isinstance(v, dict):
                    raise _Bad("it is not an object")
                self.extras(v, ("text", "from"), _pointer("title", k))
                out.append(
                    (
                        k,
                        TitleField(
                            _text(v.get("text"), self.limits.title_chars),
                            _one_of(v.get("from", "typed"), ("part", "list", "typed")),
                        ),
                    )
                )
            except (_Bad, InvalidArgumentError) as exc:
                self.problem(f"title.{k[:40]}", exc, "the field is left out")
        return tuple(out)

    def records(self, raw: Any, name: str) -> list:
        if raw is None:
            return []
        if not isinstance(raw, list):
            self.problem(name, "it is not a list", "it is left empty")
            return []
        out = []
        for k, rec in enumerate(raw):
            if not isinstance(rec, dict):
                self.problem(f"{name}[{k}]", "it is not an object", "it is left out")
                continue
            out.append(rec)
        return out

    def features(self, raw: Any) -> tuple[FeatureRecord, ...]:
        out = []
        for rec in self.records(raw, "features"):
            ident = rec["id"]
            where = f"features[{ident}]"
            self.extras(rec, ("id", "descriptor", "decisions"), _pointer("features", ident))
            desc = rec.get("descriptor")
            if isinstance(desc, dict):
                self.extras(
                    desc,
                    ("type", "size", "adjacency", "position"),
                    _pointer("features", ident) + "/descriptor",
                )
            descriptor = self.field(where, rec, "descriptor", _descriptor, Descriptor("unknown"))
            if "descriptor" not in rec:
                self.problem(f"{where}.descriptor", "it is missing", "the feature is matched as unknown")
            decisions = self.field(where, rec, "decisions", _decisions, ())
            out.append(FeatureRecord(ident, descriptor, decisions))
        return tuple(out)

    def datums(self, raw: Any) -> tuple[Datum, ...]:
        out, letters = [], set()
        for k, rec in enumerate(self.records(raw, "datums")):
            try:
                letter = _letter(rec.get("letter"))
                if letter in letters:
                    raise _Bad(f"datum {letter} is named twice")
                self.extras(rec, ("letter", "face", "reason"), _pointer("datums", letter))
                out.append(
                    Datum(
                        letter,
                        _whole(rec.get("face"), -1, 10_000_000),
                        _text(rec.get("reason", ""), self.limits.title_chars),
                    )
                )
                letters.add(letter)
            except _Bad as exc:
                self.problem(f"datums[{k}]", exc, "the datum is left out")
        return tuple(out)

    def dimension(self, rec: dict) -> DimensionRecord | None:
        ident = rec["id"]
        where = f"dimensions[{ident}]"
        base = _pointer("dimensions", ident)
        L = self.limits
        self.extras(rec, DIMENSION_KEYS, base)
        try:
            key = rec.get("key")
            if not isinstance(key, str) or len(key) > 256 or not _KEY.fullmatch(key):
                raise _Bad("its key is not a requirement key")
            kind = _one_of(rec.get("kind"), types.DIMENSION_KINDS)
            value = _number(rec.get("value"), -1e6, 1e6)
            view = rec.get("view")
            if not isinstance(view, str):
                raise _Bad("it names no view")
        except _Bad as exc:
            self.problem(where, exc, "the dimension is left out")
            return None

        def placement(v: Any) -> Placement | None:
            if v is None:
                return None
            if not isinstance(v, dict):
                raise _Bad("it is not an object")
            self.extras(v, ("along_mm", "across_mm", "track", "moved"), base + "/placement")
            return Placement(
                _number(v.get("along_mm", 0.0), -1e4, 1e4),
                _number(v.get("across_mm", 0.0), -1e4, 1e4),
                _whole(v.get("track", 0), 0, 1000),
                _flag(v.get("moved", False)),
            )

        text = rec.get("text", {})
        if not isinstance(text, dict):
            self.problem(f"{where}.text", "it is not an object")
            text = {}
        self.extras(text, ("prefix", "suffix", "override"), base + "/text")
        precision = rec.get("precision", {})
        if not isinstance(precision, dict):
            self.problem(f"{where}.precision", "it is not an object")
            precision = {}
        self.extras(precision, ("places", "source"), base + "/precision")
        tolerance = rec.get("tolerance", {})
        if not isinstance(tolerance, dict):
            self.problem(f"{where}.tolerance", "it is not an object")
            tolerance = {}
        self.extras(tolerance, ("type", "values"), base + "/tolerance")
        if isinstance(rec.get("frame"), dict):
            self.extras(
                rec["frame"], ("characteristic", "value", "diameter", "modifier", "datums"), base + "/frame"
            )

        def suffix(v: Any) -> tuple[str, ...]:
            if not isinstance(v, list) or len(v) > 16:
                raise _Bad("it is not up to sixteen lines")
            return tuple(_text(x, L.title_chars) for x in v)

        def values(v: Any) -> tuple[float, float]:
            if not isinstance(v, list) or len(v) != 2:
                raise _Bad("it is not two numbers")
            return (_number(v[0], -1e6, 1e6), _number(v[1], -1e6, 1e6))

        def positions(v: Any) -> tuple[Position, ...]:
            if not isinstance(v, list) or len(v) > 64:
                raise _Bad("it is not a list of positions")
            out = []
            for p in v:
                if not isinstance(p, dict) or not isinstance(p.get("features", []), list):
                    raise _Bad("a position is not an object naming its features")
                out.append(
                    Position(
                        _number(p.get("value"), -1e6, 1e6),
                        _flag(p.get("centre", False)),
                        _number(p.get("radius", 0.0), 0.0, 1e6),
                        tuple(p.get("features", [])),
                    )
                )
            return tuple(out)

        def anchor(v: Any) -> tuple[float, float, float] | None:
            if v is None:
                return None
            if not isinstance(v, list) or len(v) != 3:
                raise _Bad("it is not a point")
            return (_number(v[0], -1e6, 1e6), _number(v[1], -1e6, 1e6), _number(v[2], -1e6, 1e6))

        def keys(v: Any) -> tuple[str, ...]:
            if not isinstance(v, list) or len(v) > 256:
                raise _Bad("it is not a list of requirement keys")
            for x in v:
                if not isinstance(x, str) or len(x) > 256 or not _KEY.fullmatch(x):
                    raise _Bad("it holds something that is not a requirement key")
            return tuple(v)

        def flags(v: Any) -> tuple[str, ...]:
            if not isinstance(v, list) or len(v) > 16:
                raise _Bad("it is not a list of flags")
            for x in v:
                if not isinstance(x, str) or not _FLAG.fullmatch(x):
                    raise _Bad("it holds something that is not a flag")
            return tuple(v)

        def axis(v: Any) -> str | None:
            if v is None:
                return None
            if not isinstance(v, str) or not re.fullmatch(r"[a-z0-9_-]{1,64}", v):
                raise _Bad("it is not an axis or graph name")
            return v

        kw = {
            "key": key,
            "id": ident,
            "kind": kind,
            "view": view,
            "value": value,
            "origin": self.field(
                where, rec, "origin", lambda v: _one_of(v, ("generated", "user")), "generated"
            ),
            "state": self.field(where, rec, "state", lambda v: _one_of(v, ("shown", "removed")), "shown"),
            "placement": self.field(where, rec, "placement", placement, None),
            "prefix": self.field(where + ".text", text, "prefix", lambda v: _text(v, 64), ""),
            "suffix": self.field(where + ".text", text, "suffix", suffix, ()),
            "override": self.field(where + ".text", text, "override", lambda v: _opt(_text, v, 256), None),
            "places": self.field(
                where + ".precision", precision, "places", lambda v: _whole(v, 0, numbers.MAX_PLACES), 2
            ),
            "places_source": self.field(
                where + ".precision", precision, "source", lambda v: _one_of(v, ("role", "user")), "role"
            ),
            "tolerance": self.field(
                where + ".tolerance",
                tolerance,
                "type",
                lambda v: _one_of(v, TOLERANCES),
                "block",
            ),
            "tolerance_values": self.field(where + ".tolerance", tolerance, "values", values, (0.0, 0.0)),
            "frame": self.field(where, rec, "frame", lambda v: _opt(_frame, v), None),
            "role": self.field(where, rec, "role", lambda v: _one_of(v, types.ROLES), "feature_size"),
            "axis": self.field(where, rec, "axis", axis, None),
            "features": tuple(rec.get("features", [])) if isinstance(rec.get("features", []), list) else (),
            "serves": self.field(where, rec, "serves", keys, ()),
            "positions": self.field(where, rec, "positions", positions, ()),
            "anchor": self.field(where, rec, "anchor", anchor, None),
            "radius": self.field(where, rec, "radius", lambda v: _number(v, 0.0, 1e6), 0.0),
            "side": self.field(where, rec, "side", lambda v: None if v is None else _side(v), None),
            "flags": self.field(where, rec, "flags", flags, ()),
        }
        try:
            return DimensionRecord(**kw)
        except (InvalidArgumentError, TypeError) as exc:
            self.problem(where, exc, "the dimension is left out")
            return None

    def dimensions(self, raw: Any) -> tuple[DimensionRecord, ...]:
        out = []
        for rec in self.records(raw, "dimensions"):
            d = self.dimension(rec)
            if d is not None:
                out.append(d)
        return tuple(out)

    def notes(self, raw: Any) -> tuple[tuple[str, NoteLine], ...]:
        out = []
        for rec in self.records(raw, "notes"):
            ident = rec["id"]
            self.extras(rec, ("id", "origin", "text", "frames"), _pointer("notes", ident))
            try:
                frames = rec.get("frames", [])
                if not isinstance(frames, list) or len(frames) > 8:
                    raise _Bad("its frames are not a list of up to eight")
                out.append(
                    (
                        ident,
                        NoteRecord(
                            _text(rec.get("text"), self.limits.note_chars),
                            tuple(_frame(f) for f in frames),
                            _one_of(rec.get("origin", "template"), NOTE_ORIGINS),
                        ),
                    )
                )
            except (_Bad, InvalidArgumentError) as exc:
                self.problem(f"notes[{ident}]", exc, "the note is left out")
        return tuple(out)

    def status(self, raw: Any) -> str:
        if raw in types.STATUSES:
            return raw
        self.problem("status", "it is not PRELIMINARY, CHECKED or RELEASED", "PRELIMINARY is used")
        return "PRELIMINARY"

    def signatures(self, raw: Any) -> tuple[Signature, ...]:
        out, rows = [], set()
        for k, rec in enumerate(self.records(raw, "signatures")):
            try:
                row = _one_of(rec.get("row"), settings_mod.APPROVAL_ROWS)
                if row in rows:
                    raise _Bad(f"{row} is signed twice")
                self.extras(rec, ("row", "name", "date", "digest"), _pointer("signatures", row))
                out.append(
                    Signature(
                        row,
                        _text(rec.get("name"), self.limits.title_chars, empty=False),
                        _date(rec.get("date")),
                        _hex64(rec.get("digest")),
                    )
                )
                rows.add(row)
            except _Bad as exc:
                self.problem(f"signatures[{k}]", exc, "the signature is left out")
        return tuple(out)

    def accepted(self, raw: Any) -> tuple[tuple[str, str], ...]:
        out = []
        for k, rec in enumerate(self.records(raw, "accepted")):
            try:
                out.append(
                    (
                        _text(rec.get("item"), 256, empty=False),
                        _text(rec.get("reason"), self.limits.title_chars, empty=False),
                    )
                )
            except _Bad as exc:
                self.problem(f"accepted[{k}]", exc, "the entry is left out")
        return tuple(out)

    def revisions(self, raw: Any) -> tuple[Revision, ...]:
        out, marks = [], set()
        for k, rec in enumerate(self.records(raw, "revisions")):
            try:
                rev = rec.get("rev")
                if not standards.is_revision(rev):
                    raise _Bad("it is not a revision mark")
                if rev in marks:
                    raise _Bad(f"revision {rev} is named twice")
                self.extras(
                    rec, ("rev", "zones", "description", "date", "approved"), _pointer("revisions", rev)
                )
                zones = rec.get("zones", [])
                if not isinstance(zones, list) or len(zones) > MAX_ZONES:
                    raise _Bad("its zones are not a list")
                for z in zones:
                    if not isinstance(z, str) or not _ZONE.fullmatch(z):
                        raise _Bad("it names a zone that is not a letter and a number")
                out.append(
                    Revision(
                        rev,
                        _text(rec.get("description", ""), self.limits.note_chars),
                        tuple(zones),
                        _opt(_date, rec.get("date")),
                        _opt(_text, rec.get("approved"), self.limits.title_chars),
                    )
                )
                marks.add(rev)
            except _Bad as exc:
                self.problem(f"revisions[{k}]", exc, "the revision row is left out")
        return tuple(out)

    def outputs(self, raw: Any) -> tuple[Output, ...]:
        out = []
        for k, rec in enumerate(self.records(raw, "outputs")):
            try:
                name = _file_name(rec.get("name"))
                self.extras(
                    rec, ("kind", "name", "sha256", "revision", "released"), _pointer("outputs", name)
                )
                rev = rec.get("revision")
                if not standards.is_revision(rev):
                    raise _Bad("its revision is not a revision mark")
                out.append(
                    Output(
                        _one_of(rec.get("kind"), EXPORT_EXTENSIONS),
                        name,
                        _hex64(rec.get("sha256")),
                        rev,
                        _flag(rec.get("released", False)),
                    )
                )
            except _Bad as exc:
                self.problem(f"outputs[{k}]", exc, "the record is left out")
        return tuple(out)

    def next_id(self, raw: Any, used: Mapping[str, int]) -> tuple[tuple[str, int], ...]:
        given: dict[str, int] = {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                if (
                    not re.fullmatch(r"[a-z]{1,8}", k)
                    or isinstance(v, bool)
                    or not isinstance(v, int)
                    or not 1 <= v <= MAX_ID_NUMBER
                ):
                    self.problem(
                        f"next_id.{k[:16]}",
                        "it is not a number for new ids",
                        "it is worked out from the ids used",
                    )
                    continue
                given[k] = v
        elif raw is not None:
            self.problem("next_id", "it is not an object", "it is worked out from the ids used")
        out = dict(given)
        for prefix in ("f", "d", "n", "v"):
            need = used.get(prefix, 0) + 1
            if out.get(prefix, 1) < need:
                if prefix in given:
                    self.problem(f"next_id.{prefix}", "it is below an id the drawing uses", f"{need} is used")
                out[prefix] = need
            out.setdefault(prefix, 1)
        order = [p for p in ("f", "d", "n", "v")] + [p for p in out if p not in ("f", "d", "n", "v")]
        return tuple((p, out[p]) for p in order)

    def sheet(self, raw: Any) -> Any:
        if raw is None:
            return None
        size = len(json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if size > self.limits.sheet_bytes:
            raise self.limits.exceeded(
                "sheet_bytes", "the laid-out sheet is larger than a drawing file holds"
            )
        try:
            sheet = display.from_compact(raw)
            if len(display.sheets_of(sheet)) > self.limits.sheets:
                raise InvalidArgumentError(f"the drawing has more than {self.limits.sheets} sheets")
            return sheet
        except (InvalidArgumentError, TypeError, ValueError) as exc:
            self.problem("sheet", exc, "the drawing opens without its laid-out sheet, which is kept as it is")
            self.unknown.append(("sheet", raw))  # bounded by sheet_bytes, not unknown_bytes
            return None


def _side(v: Any) -> str:
    if not isinstance(v, str) or not _SIDE.fullmatch(v):
        raise _Bad("it is not a side")
    return v


def _used(features, dimensions, notes, sheet) -> dict[str, int]:
    used = {"f": 0, "d": 0, "n": 0, "v": 0}

    def see(prefix: str, ident: str) -> None:
        n = id_number(ident, prefix)
        if n is not None:
            used[prefix] = max(used[prefix], n)

    for r in features:
        see("f", r.id)
    for d in dimensions:
        see("d", d.id)
        see("v", d.view)
        for f in d.features:
            see("f", f)
    for ident, _n in notes:
        see("n", ident)
    if isinstance(sheet, display.Sheet):
        for v in sheet.views:
            see("v", v.view)
    return used


def loads(
    data: bytes | bytearray | memoryview | str, *, limits: DrawingLimits = DEFAULT_LIMITS
) -> tuple[DrawingDocument, list[str]]:
    """A drawing from ``.ssdrw`` bytes, and the problems found (17.2). A file outside the
    bounds is refused whole: :class:`DrawingFileError` with the reason, or
    ``SldLimitError`` naming the bound passed. A value that fails its own check falls
    back to its default, or its record is left out, and the problem says which."""
    if not isinstance(limits, DrawingLimits):
        raise InvalidArgumentError("limits must be DrawingLimits", detail={"parameter": "limits"})
    if isinstance(data, str):
        try:
            data = data.encode("utf-8")
        except UnicodeEncodeError:
            raise _refuse("the drawing file is not valid UTF-8", "not_utf8") from None
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise InvalidArgumentError("data must be bytes", detail={"parameter": "data"})
    data = bytes(data)
    if len(data) > limits.drawing_bytes:
        raise limits.exceeded(
            "drawing_bytes", f"the drawing file is larger than {limits.drawing_bytes // (1 << 20)} MiB"
        )
    if data.startswith(BOM):
        raise _refuse("the drawing file starts with a byte order mark, which a drawing file never has", "bom")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise _refuse("the drawing file is not valid UTF-8", "not_utf8") from None
    try:
        raw = _strict(text)
    except RecursionError:
        raise limits.exceeded(
            "json_depth", f"the drawing file is nested more than {limits.json_depth} levels deep"
        ) from None
    except ValueError as exc:
        raise _refuse(f"the drawing file is not strict JSON ({str(exc)[:120]})", "json") from None
    _prewalk(raw, 0, False, limits)
    if not isinstance(raw, dict):
        raise _refuse("the file is not a SolidSeas drawing (it is not one JSON object)", "not_object")
    _schema_major(raw.get("schema"))
    _ids(raw, limits)

    r = _Reader(limits)
    for name, value in raw.items():
        if name in MEMBERS:
            continue
        if name.startswith("/"):
            r.problem(name[:40], "it is not a member name a drawing file uses", "it is left out")
            continue
        r.keep(name, value)
    created = r.field("file", raw, "created", lambda v: _opt(_timestamp, v), None)
    modified = r.field("file", raw, "modified", lambda v: _opt(_timestamp, v), None)
    model = r.model(raw.get("model"))
    options = r.options(raw.get("options", {}))
    snapshot = r.settings(raw.get("settings"))
    title = r.title(raw.get("title"))
    features = r.features(raw.get("features"))
    datums = r.datums(raw.get("datums"))
    dimensions = r.dimensions(raw.get("dimensions"))
    notes = r.notes(raw.get("notes"))
    status = r.status(raw.get("status", "PRELIMINARY"))
    signatures = r.signatures(raw.get("signatures"))
    accepted = r.accepted(raw.get("accepted"))
    revisions = r.revisions(raw.get("revisions"))
    outputs = r.outputs(raw.get("outputs"))
    sheet = r.sheet(raw.get("sheet"))
    next_id = r.next_id(raw.get("next_id"), _used(features, dimensions, notes, sheet))
    drawing = DrawingDocument(
        id=raw["id"],
        options=options,
        settings=snapshot,
        model=model,
        title=title,
        features=features,
        datums=datums,
        dimensions=dimensions,
        notes=notes,
        status=status,
        signatures=signatures,
        revisions=revisions,
        outputs=outputs,
        next_id=next_id,
        sheet=sheet,
        unknown=tuple(r.unknown),
        created=created,
        modified=modified,
        accepted=accepted,
    )
    return drawing, r.problems


# --------------------------------------------------------------------------- files


@dataclass(frozen=True)
class Loaded:
    """A drawing read from a file: the drawing, the problems found, the SHA-256 of the
    bytes read (what Save's ``replaces`` needs, kept by the editor for the file it has
    open) and the path."""

    drawing: DrawingDocument
    problems: tuple[str, ...]
    sha256: str
    path: str


@dataclass(frozen=True)
class Saved:
    """What :func:`save` or :func:`write_output` wrote: the path, the SHA-256 of the bytes
    written (the next Save's ``replaces``), their size, and for a save the drawing as
    saved (its ``modified`` time set)."""

    path: str
    sha256: str
    size: int
    drawing: Any = None


def read(path: str | os.PathLike, *, limits: DrawingLimits = DEFAULT_LIMITS) -> Loaded:
    """Read a ``.ssdrw``: the drawing, its problems and the hash of the bytes read. Only a
    plain file is read, and no more than ``drawing_bytes`` of it."""
    target = os.path.abspath(os.fspath(path))
    st = os.stat(target)
    if not stat.S_ISREG(st.st_mode):
        raise InvalidArgumentError(
            "a drawing is read only from a plain file", detail={"parameter": "path", "rule": "not_a_file"}
        )
    if st.st_size > limits.drawing_bytes:
        raise limits.exceeded(
            "drawing_bytes", f"the drawing file is larger than {limits.drawing_bytes // (1 << 20)} MiB"
        )
    with open(target, "rb") as fh:
        data = fh.read(limits.drawing_bytes + 1)
    drawing, problems = loads(data, limits=limits)
    return Loaded(drawing, tuple(problems), hashlib.sha256(data).hexdigest(), target)


def load(path: str | os.PathLike, *, limits: DrawingLimits = DEFAULT_LIMITS, **_kw: Any) -> DrawingDocument:
    """Read a ``.ssdrw`` (the library's ``drawing.load``); the problems found are the
    drawing's ``warnings``. :func:`read` also gives the file's hash."""
    loaded = read(path, limits=limits)
    return replace(loaded.drawing, warnings=loaded.problems)


def _check_now(stamp: Any) -> None:
    try:
        _timestamp(stamp)
    except _Bad as exc:
        raise InvalidArgumentError(f"now: {exc}", detail={"parameter": "now"}) from None


def _now() -> str:
    return datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()


def file_sha256(path: str, limit: int | None = None) -> str | None:
    """The SHA-256 of the plain file at ``path`` (never through a link at its name), or
    None when it is missing, not a plain file, unreadable or larger than ``limit``."""
    try:
        st = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode) or (limit is not None and st.st_size > limit):
        return None
    h = hashlib.sha256()
    size = 0
    try:
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(HASH_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if limit is not None and size > limit:
                    return None
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


class _Hashing:
    """A file handle that hashes and counts what is written, and stops past ``limit``."""

    def __init__(self, fh, limit: int, limits: DrawingLimits, bound: str) -> None:
        self.fh, self.limit, self.limits, self.bound = fh, limit, limits, bound
        self.h = hashlib.sha256()
        self.size = 0

    def write(self, data) -> int:
        b = bytes(data)
        self.size += len(b)
        if self.size > self.limit:
            raise self.limits.exceeded(self.bound, "the file is larger than SolidSeas writes")
        self.h.update(b)
        return self.fh.write(b)

    def flush(self) -> None:
        self.fh.flush()


def _write(
    target: str,
    produce: Callable[[Any], Any],
    *,
    replaces: str | None,
    limit: int,
    limits: DrawingLimits,
    bound: str,
) -> Saved:
    """Write ``target`` through a temporary name and a rename: created new when nothing is
    there; over a file only when ``replaces`` equals its SHA-256. Never through a link,
    never over a device or anything but a plain file."""
    from ..export import write_new

    if replaces is not None and (not isinstance(replaces, str) or not _HEX64.fullmatch(replaces)):
        raise InvalidArgumentError("replaces must be a SHA-256", detail={"parameter": "replaces"})
    try:
        st = os.lstat(target)
    except FileNotFoundError:
        st = None
    overwrite = False
    if st is not None:
        attrs = int(getattr(st, "st_file_attributes", 0) or 0)
        if stat.S_ISLNK(st.st_mode) or attrs & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
            raise OutputRefusedError(
                f"refusing to write {target}: it is a link, and writing would follow it",
                detail={"rule": "link"},
            )
        if not stat.S_ISREG(st.st_mode):
            raise OutputRefusedError(
                f"refusing to write {target}: it is not a plain file", detail={"rule": "not_a_file"}
            )
        if replaces is None:
            raise OutputRefusedError(
                f"{os.path.basename(target)} is already there; SolidSeas replaces only a file it may replace",
                detail={"rule": "exists"},
            )
        current = file_sha256(target, limit)
        if current != replaces:
            raise OutputRefusedError(
                f"{os.path.basename(target)} changed since SolidSeas last read or wrote it, so it stays",
                detail={"rule": "changed"},
            )
        overwrite = True
    box: dict[str, _Hashing] = {}

    def write(fh) -> int:
        w = _Hashing(fh, limit, limits, bound)
        box["w"] = w
        produce(w)
        return w.size

    path, size = write_new(target, write, overwrite=overwrite)
    return Saved(path, box["w"].h.hexdigest(), size)


def save(
    drawing: types.Drawing,
    path: str | os.PathLike,
    *,
    replaces: str | None = None,
    limits: DrawingLimits = DEFAULT_LIMITS,
    now: str | None = None,
) -> Saved:
    """Write ``drawing`` to exactly ``path`` (a ``.ssdrw``), never picking a name (12.6). A
    path that exists is refused (``OutputRefusedError``, rule ``exists``) unless
    ``replaces`` is given and equals the SHA-256 of the file there now (else rule
    ``changed``); a link (``link``), a device, a stream or anything but a plain file
    (``not_a_file``) is refused either way. The file is written through a temporary
    name and a rename. Returns what was written, with the drawing as saved."""
    if not isinstance(drawing, types.Drawing):
        raise InvalidArgumentError("drawing must be a Drawing", detail={"parameter": "drawing"})
    target = os.path.abspath(os.fspath(path))
    if not target.lower().endswith(EXTENSION):
        raise InvalidArgumentError(f"a drawing is saved to a {EXTENSION} file", detail={"parameter": "path"})
    stamp = now if now is not None else _now()
    _check_now(stamp)
    doc = as_document(drawing)
    doc = replace(doc, modified=stamp, created=doc.created or stamp)
    data = dumps(doc, limits=limits)
    saved = _write(
        target,
        lambda fh: fh.write(data),
        replaces=replaces,
        limit=limits.drawing_bytes,
        limits=limits,
        bound="drawing_bytes",
    )
    return replace(saved, drawing=doc)


# --------------------------------------------------------------------------- names (12.5)


def safe_stem(name: str, limit: int = MAX_STEM) -> str:
    """A file name stem by the rules of the viewer's ``printing.safe_stem``: characters a
    file name cannot hold, or a shell could misread, become ``_``; at most ``limit``
    characters; never a Windows device name; never empty (``drawing``)."""
    stem = _UNSAFE.sub("_", str(name)).strip(" .")
    stem = re.sub(r"_{2,}", "_", stem)[: max(1, limit)].strip(" .")
    if not stem:
        return "drawing"
    if _RESERVED.fullmatch(stem):
        stem = "_" + stem[: max(1, limit) - 1]
    return stem


def title_text(drawing: types.Drawing, key: str) -> str:
    for k, f in drawing.title:
        if k == key:
            return f.text
    return ""


def current_revision(drawing: types.Drawing) -> str | None:
    """The drawing's revision: the mark of its last revision row."""
    return drawing.revisions[-1].rev if drawing.revisions else None


def _model_stem(drawing: types.Drawing) -> str:
    """The model's file name without the extension of a format drawings are made from."""
    from ..formats import registry
    from .source import MODEL_FORMATS

    name = str((drawing.model or {}).get("name") or "")
    base = re.split(r"[\\/]", name)[-1]
    stem, ext = os.path.splitext(base)
    spec = registry.by_extension(ext)
    drawn = ext.lower() in (".sldprt", ".sldasm", ".slddrw") or (
        spec is not None and spec.id in MODEL_FORMATS
    )
    return stem if stem and drawn else base


def _number_text(drawing: types.Drawing) -> str:
    return title_text(drawing, "number") or title_text(drawing, "part_number") or _model_stem(drawing)


def name_base(drawing: types.Drawing) -> str:
    """The settings' name pattern (``{number} {revision}``) filled from the drawing: the
    number (else the part number, else the model's name), the revision, the title and
    the part number, spaces collapsed."""
    pattern = "{number} {revision}"
    s = drawing.settings
    if isinstance(s, settings_mod.DrawingSettings):
        pattern = s.files.name_pattern
    values = {
        "number": _number_text(drawing),
        "revision": current_revision(drawing) or title_text(drawing, "revision"),
        "title": title_text(drawing, "title"),
        "part_number": title_text(drawing, "part_number"),
    }
    text = _PATTERN_TOKEN.sub(lambda m: values.get(m.group(1), ""), pattern)
    return " ".join(text.split())


def export_stem(drawing: types.Drawing, *, released: bool | None = None) -> str:
    """An export's stem (12.5): the pattern through ``safe_stem``; unreleased exports end
    in `` PRELIMINARY`` (``1234-001 A PRELIMINARY``)."""
    released = drawing.status == "RELEASED" if released is None else released
    base = name_base(drawing)
    if released:
        return safe_stem(base)
    return safe_stem(base, MAX_STEM - len(PRELIMINARY_SUFFIX)) + PRELIMINARY_SUFFIX


def export_name(drawing: types.Drawing, kind: str, *, released: bool | None = None) -> str:
    """``1234-001 A PRELIMINARY.pdf``, or ``1234-001 A.pdf`` for a released drawing."""
    if kind not in EXPORT_EXTENSIONS:
        raise InvalidArgumentError("kind is pdf or dxf", detail={"parameter": "kind"})
    return export_stem(drawing, released=released) + EXPORT_EXTENSIONS[kind]


def drawing_file_name(drawing: types.Drawing) -> str:
    """The ``.ssdrw``'s name: the drawing number made safe (``1234-001.ssdrw``), without
    the revision, since one file carries every revision."""
    return safe_stem(_number_text(drawing)) + EXTENSION


def _unnumbered(stem: str) -> str:
    """``stem`` without a `` (N)`` a numbered name ends in, so the next is ``(N+1)``."""
    return re.sub(r" \([0-9]{1,7}\)$", "", stem) or stem


def candidate_names(stem: str, ext: str):
    """``stem + ext``, then ``stem (2) + ext`` and on: at most :data:`MAX_TRIES` names."""
    for n in range(1, MAX_TRIES + 1):
        yield stem + ext if n == 1 else f"{stem} ({n}){ext}"


def next_free_name(
    folder: str | os.PathLike, stem: str, ext: str, *, exists: Callable[[str], bool] | None = None
) -> str:
    """The first of :func:`candidate_names` not taken in ``folder``, as a path. Refused
    (``OutputRefusedError``, rule ``exists``) when every name tried is taken."""
    exists = exists or os.path.lexists
    folder = os.fspath(folder)
    for name in candidate_names(stem, ext):
        path = os.path.join(folder, name)
        if not exists(path):
            return path
    raise OutputRefusedError(
        f"every name tried for {stem}{ext} is taken", detail={"rule": "exists", "highest": MAX_TRIES}
    )


# --------------------------------------------------------------------------- what Save may replace (12.6)


@dataclass(frozen=True)
class Target:
    """Where a write goes: the path, the SHA-256 the file there must still have to be
    replaced (None: the file is created new), whether a numbered name was taken because
    the plain one was not free, and the words the status line shows."""

    path: str
    replaces: str | None = None
    renamed: bool = False
    words: str = ""


def _files_settings(drawing: types.Drawing) -> settings_mod.Files:
    s = drawing.settings
    return s.files if isinstance(s, settings_mod.DrawingSettings) else settings_mod.Files()


def _drawing_id_of(path: str, limits: DrawingLimits) -> str | None:
    try:
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limits.drawing_bytes:
            return None
        with open(path, "rb") as fh:
            data = fh.read(limits.drawing_bytes + 1)
        drawing, _problems = loads(data, limits=limits)
    except (OSError, InvalidArgumentError, SldLimitError, ValueError):
        return None  # not a drawing this SolidSeas reads: not a file Save may replace
    return drawing.id


def save_target(
    drawing: types.Drawing,
    path: str | os.PathLike,
    *,
    loaded_sha256: str | None = None,
    exists: Callable[[str], bool] | None = None,
    limits: DrawingLimits = DEFAULT_LIMITS,
) -> Target:
    """Where Save writes ``drawing`` when the user's file is ``path`` (12.6). A free path
    is written new. With ``replace_own_files`` on (the default), a file there is
    replaced only when it is a SolidSeas drawing with the same id that still has
    ``loaded_sha256``, the hash recorded when it was last loaded or saved; anything else
    gets the next free name. With it off every write is a new file."""
    exists = exists or os.path.lexists
    target = os.path.abspath(os.fspath(path))
    if not exists(target):
        return Target(target)
    files = _files_settings(drawing)
    if files.replace_own_files and loaded_sha256 is not None:
        current = file_sha256(target, limits.drawing_bytes)
        if current == loaded_sha256 and _drawing_id_of(target, limits) == drawing.id:
            return Target(
                target, current, False, f"{os.path.basename(target)} is replaced by its newer version"
            )
    folder, base = os.path.split(target)
    stem = base[: -len(EXTENSION)] if base.lower().endswith(EXTENSION) else os.path.splitext(base)[0]
    other = next_free_name(folder, _unnumbered(stem), EXTENSION, exists=exists)
    why = (
        "every save is a new file"
        if not files.replace_own_files
        else "it is not this drawing's own unchanged file"
    )
    return Target(
        other, None, True, f"{base} is taken ({why}), so the drawing is saved as {os.path.basename(other)}"
    )


def says_solidseas(path: str, kind: str, limit: int = DEFAULT_LIMITS.output_bytes) -> bool:
    """Whether the export at ``path`` says SolidSeas wrote it: a PDF whose ``/Producer``
    starts with ``SolidSeas``, a DXF whose first line is ``999`` and second starts with
    ``SolidSeas``. Read only, at most ``limit`` bytes."""
    try:
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            return False
        with open(path, "rb") as fh:
            if kind == "dxf":
                head = fh.read(256).splitlines()
                return (
                    len(head) >= 2 and head[0].strip() == b"999" and head[1].strip().startswith(b"SolidSeas")
                )
            if kind != "pdf":
                return False
            tail = b""
            while True:
                chunk = fh.read(HASH_CHUNK)
                if not chunk:
                    return False
                if _PDF_PRODUCER.search(tail + chunk):
                    return True
                tail = chunk[-64:]
    except OSError:
        return False


def export_target(
    drawing: types.Drawing,
    folder: str | os.PathLike,
    kind: str,
    *,
    exists: Callable[[str], bool] | None = None,
    limits: DrawingLimits = DEFAULT_LIMITS,
) -> Target:
    """Where an export of ``drawing`` goes in ``folder`` (12.5, 12.6). A released export is
    created new and never replaces anything: a taken name gets the next free one. A
    PRELIMINARY export may replace its own earlier file only with ``replace_own_files``
    and "keep preliminary exports up to date" on, and only when ``outputs`` lists that
    name, unreleased, with the hash the file still has, and the file says SolidSeas
    wrote it. Anything else gets the next free name."""
    exists = exists or os.path.lexists
    name = export_name(drawing, kind)
    path = os.path.abspath(os.path.join(os.fspath(folder), name))
    if not exists(path):
        return Target(path)
    released = drawing.status == "RELEASED"
    files = _files_settings(drawing)
    if not released and files.replace_own_files and files.keep_preliminary_current:
        own = [o for o in drawing.outputs if o.kind == kind and o.name == name and not o.released]
        if own:
            current = file_sha256(path, limits.output_bytes)
            if current == own[-1].sha256 and says_solidseas(path, kind, limits.output_bytes):
                return Target(path, current, False, f"{name} is rewritten to keep it current")
    stem = name[: -len(EXPORT_EXTENSIONS[kind])]
    other = next_free_name(os.path.dirname(path), stem, EXPORT_EXTENSIONS[kind], exists=exists)
    if released:
        why = "released files are never replaced"
    elif not files.replace_own_files:
        why = "every write is a new file"
    else:
        why = "it is not this drawing's own unchanged export"
    return Target(
        other, None, True, f"{name} is taken ({why}), so it is written as {os.path.basename(other)}"
    )


def write_output(
    path: str | os.PathLike,
    write: Callable[[Any], Any],
    *,
    replaces: str | None = None,
    limits: DrawingLimits = DEFAULT_LIMITS,
) -> Saved:
    """Write an export with ``write(fh)`` under Save's rules: created new, or over the file
    there only when ``replaces`` equals its hash; through a temporary name and a rename;
    at most ``output_bytes``. Returns the path, hash and size, for :func:`record_output`."""
    target = os.path.abspath(os.fspath(path))
    if os.path.splitext(target)[1].lower() not in EXPORT_EXTENSIONS.values():
        raise InvalidArgumentError("an export is a .pdf or .dxf file", detail={"parameter": "path"})
    return _write(
        target, write, replaces=replaces, limit=limits.output_bytes, limits=limits, bound="output_bytes"
    )


def record_output(
    drawing: types.Drawing, kind: str, name: str, sha256: str, *, released: bool | None = None
) -> types.Drawing:
    """``drawing`` with an export recorded in ``outputs`` (kind, name, hash, the current
    revision, released or not), replacing the record of an earlier write of the same
    unreleased file. A released record is never replaced: a released file is written
    once."""
    if kind not in EXPORT_EXTENSIONS:
        raise InvalidArgumentError("kind is pdf or dxf", detail={"parameter": "kind"})
    try:
        name = _file_name(name)
        _hex64(sha256)
    except _Bad as exc:
        raise InvalidArgumentError(f"an output record: {exc}", detail={"parameter": "name"}) from None
    rev = current_revision(drawing)
    if rev is None:
        raise InvalidArgumentError("the drawing has no revision row", detail={"parameter": "drawing"})
    released = drawing.status == "RELEASED" if released is None else bool(released)
    kept = []
    for o in drawing.outputs:
        if o.name == name and o.kind == kind:
            if o.released:
                raise OutputRefusedError(
                    f"{name} was released; it is never written again", detail={"rule": "released"}
                )
            continue
        kept.append(o)
    kept.append(Output(kind, name, sha256, rev, released))
    return replace(drawing, outputs=tuple(kept))


# --------------------------------------------------------------------------- the folder (12.6)

DRIVE_REMOVABLE, DRIVE_FIXED, DRIVE_REMOTE, DRIVE_RAMDISK = 2, 3, 4, 6
FOLDER_ODD = "the folder has a path SolidSeas does not write to (a device or a stream of a file)"
FOLDER_NETWORK = (
    "the folder is on a network share or drive outside the folder you opened, which SolidSeas never touches"
)
FOLDER_LINKED = "the folder, or one it is in, is a link or a junction, which SolidSeas never writes through"
FOLDER_PLACEHOLDER = "the folder is a cloud placeholder, whose files are not on this computer"
FOLDER_NOT_A_FOLDER = "the folder is not a folder"
FOLDER_READ_ONLY = "the folder is read-only"


def _windows_drive_type(root: str) -> int:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    kernel32.GetDriveTypeW.restype = ctypes.c_uint
    return int(kernel32.GetDriveTypeW(root))


def _key(path: str, windows: bool) -> str:
    import ntpath
    import posixpath

    mod = ntpath if windows else posixpath
    return mod.normcase(mod.normpath(path))


def _inside(path: str, folder: str, windows: bool) -> bool:
    import ntpath
    import posixpath

    mod = ntpath if windows else posixpath
    p, f = _key(path, windows), _key(folder, windows)
    try:
        return mod.commonpath([p, f]) == f
    except ValueError:
        return False


def is_local(
    path: str, *, windows: bool | None = None, drive_type: Callable[[str], int] | None = None
) -> bool:
    """Whether ``path`` is on a drive of this computer, from its text and its drive
    letter's kind only: a UNC path or a mapped network drive is not."""
    windows = os.name == "nt" if windows is None else windows
    if not windows:
        return True
    p = path.replace("/", "\\")
    if p.startswith("\\\\"):
        return False
    if len(p) < 2 or p[1] != ":" or not p[0].isascii() or not p[0].isalpha():
        return False
    kind = (drive_type or _windows_drive_type)(p[:2] + "\\")
    return kind in (DRIVE_FIXED, DRIVE_REMOVABLE, DRIVE_RAMDISK)


def folder_problem(
    folder: str | os.PathLike,
    opened: str | os.PathLike | None = None,
    *,
    windows: bool | None = None,
    drive_type: Callable[[str], int] | None = None,
) -> str | None:
    """Why drawing files must not be written in ``folder``, said for the user, or None:
    the rules of the 3D Print file's folder (the viewer's ``printing.folder_problem``,
    12.6). Refused: a device or extended-length path or a stream (on Windows); a folder
    outside ``opened`` that is not on a drive of this computer (a UNC path or a mapped
    network drive, never contacted); a link, a junction or a cloud placeholder at the
    folder or any folder above it; something that is not a folder; outside Windows, a
    folder this account may not write in. Only the path's text and ``lstat`` are used."""
    from .. import walk

    windows = os.name == "nt" if windows is None else windows
    folder = os.fspath(folder)
    if not folder or "\x00" in folder or len(folder) > MAX_PATH:
        return FOLDER_ODD
    if windows:
        p = folder.replace("/", "\\")
        drive_end = 2 if len(p) >= 2 and p[1] == ":" else 0
        if p.startswith(("\\\\?\\", "\\\\.\\")) or ":" in p[drive_end:]:
            return FOLDER_ODD
    if windows != (os.name == "nt"):
        within = opened is not None and _inside(folder, os.fspath(opened), windows)
        if not within and not is_local(folder, windows=windows, drive_type=drive_type):
            return FOLDER_NETWORK
        return None  # another system's path, judged from its text alone
    folder = os.path.abspath(folder)
    within = opened is not None and _inside(folder, os.path.abspath(os.fspath(opened)), windows)
    if not within and not is_local(folder, windows=windows, drive_type=drive_type):
        return FOLDER_NETWORK
    chain = [folder]
    while len(chain) < MAX_PATH:
        up = os.path.dirname(chain[-1])
        if not up or up == chain[-1]:
            break
        chain.append(up)
    for f in reversed(chain):
        try:
            st = os.lstat(f)
        except OSError as exc:
            return f"the folder could not be looked at ({exc.strerror or exc})"
        attrs = int(getattr(st, "st_file_attributes", 0) or 0)
        tag = int(getattr(st, "st_reparse_tag", 0) or 0)
        if stat.S_ISLNK(st.st_mode) or walk.reparse_link(attrs, tag) is not None:
            return FOLDER_LINKED
        placeholder = walk.FILE_ATTRIBUTE_OFFLINE | walk.FILE_ATTRIBUTE_RECALL_ON_OPEN
        if attrs & (placeholder | walk.FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS):
            return FOLDER_PLACEHOLDER
        if not stat.S_ISDIR(st.st_mode):
            return FOLDER_NOT_A_FOLDER
    if not windows and not os.access(folder, os.W_OK | os.X_OK):
        return FOLDER_READ_ONLY
    return None


# --------------------------------------------------------------------------- a new drawing (13.1, 13.4)


def remap_sheet(sheet: Any, ids: Mapping[str, str], drop: Iterable[str] = ()) -> Any:
    """``sheet`` with dimension ids renamed by ``ids`` (on the dimensions, their frames and
    every painted item they own), and the items of the dimensions in ``drop`` taken off."""
    if not isinstance(sheet, display.Sheet):
        return sheet
    drop = set(drop)
    if not ids and not drop:
        return sheet
    annotations = []
    for a in sheet.annotations:
        if isinstance(a, display.Dimension):
            if a.id in drop:
                continue
            if a.id in ids:
                a = replace(a, id=ids[a.id])
        elif isinstance(a, display.FeatureControlFrame):
            if a.owner in drop:
                continue
            if a.owner in ids:
                a = replace(a, owner=ids[a.owner])
        annotations.append(a)
    painted = []
    for p in sheet.painted:
        owner = getattr(p, "owner", "")
        if owner in drop:
            continue
        painted.append(replace(p, owner=ids[owner]) if owner in ids else p)
    return replace(sheet, annotations=tuple(annotations), painted=tuple(painted))


def _drawing_id(seed: str | None) -> str:
    if seed is None:
        return str(uuid.uuid4())
    if not isinstance(seed, str):
        raise InvalidArgumentError("seed must be text", detail={"parameter": "seed"})
    digest = hashlib.sha256(("solidseas.drawing:" + seed).encode("utf-8")).digest()[:16]
    return str(uuid.UUID(bytes=digest, version=4))


def _check_fields(fields_in: Mapping[str, str] | None, limits: DrawingLimits) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in (fields_in or {}).items():
        if not isinstance(k, str) or not _FIELD_KEY.fullmatch(k):
            raise InvalidArgumentError(
                f"{str(k)[:40]!r} is not the name of a title field", detail={"parameter": "fields"}
            )
        try:
            out[k] = _text(v, limits.title_chars)
        except _Bad as exc:
            raise InvalidArgumentError(f"title field {k}: {exc}", detail={"parameter": "fields"}) from None
    if len(out) > MAX_TITLE_FIELDS:
        raise InvalidArgumentError("too many title fields", detail={"parameter": "fields"})
    return out


def _source_property(source: Any, names: Iterable[str]) -> str | None:
    getter = getattr(source, "property", None)
    if getter is None:
        return None
    value = getter(*names)
    return value.strip() if isinstance(value, str) and value.strip() else None


def part_title_fields(
    source: Any, settings: settings_mod.DrawingSettings, limits: DrawingLimits = DEFAULT_LIMITS
) -> dict[str, TitleField]:
    """The title fields the part gives through the settings' property names, origin
    ``part``: they follow the part when it changes (13.5). The part's material is
    shown as its callout when the settings' list maps it."""
    out: dict[str, TitleField] = {}
    ts = settings.title_sources
    for key in TITLE_KEYS:
        value = _source_property(source, getattr(ts, key))
        if key == "material" and value is None:
            m = getattr(source, "material", None)
            value = m.strip() if isinstance(m, str) and m.strip() else None
        if value is None:
            continue
        value = _CONTROL.sub("", value)[: limits.title_chars]
        if key == "material":
            entry = settings.material(value)
            if entry is not None:
                out[key] = TitleField(entry["callout"][: limits.title_chars], "part")
                continue
        out[key] = TitleField(value, "part")
    return out


def _listed(settings: settings_mod.DrawingSettings, key: str, text: str) -> dict | None:
    """The settings' list entry a typed material or finish names, whose callout the
    title block shows; None for any other field or a text the list does not hold."""
    if key == "material":
        return settings.material(text)
    if key == "finish":
        return settings.finish(text)
    return None


def _title(
    source: Any, settings: settings_mod.DrawingSettings, typed: Mapping[str, str], plan: types.Plan, limits
) -> tuple:
    part = part_title_fields(source, settings, limits)
    out: dict[str, TitleField] = {}
    for key in TITLE_KEYS:
        if key in typed:
            text = typed[key]
            entry = _listed(settings, key, text)
            out[key] = (
                TitleField(entry["callout"], "list") if entry is not None else TitleField(text, "typed")
            )
        elif key in part:
            out[key] = part[key]
    for key, text in typed.items():
        if key not in out and key not in ("drawn_by",):
            out[key] = TitleField(text, "typed")
    for key, text in plan.title:
        if key not in out and isinstance(text, str) and _FIELD_KEY.fullmatch(key or ""):
            out[key] = TitleField(_CONTROL.sub("", text)[: limits.title_chars], "part")
    return tuple(out.items())


def model_identity(source: Any, settings: settings_mod.DrawingSettings, extents: Any) -> dict[str, Any]:
    """The ``model`` member of 13.1 from a ``DrawingSource``: name, the relative path
    (the name: next to the part), format, configuration, the three hashes, part number,
    model revision, units, and the part's extents in the datum frame when known."""
    ts = settings.title_sources
    units = getattr(source, "units", None)
    name = getattr(source, "name", None)
    return {
        "name": name,
        "relative": name,  # next to the part, the default; locate.with_model_path sets it for another folder
        "stored": None,
        "format": getattr(source, "format", None),
        "configuration": getattr(source, "configuration", None),
        "sha256": getattr(source, "sha256", None),
        "geometry": getattr(source, "geometry_digest", None),
        "properties": getattr(source, "properties_digest", None),
        "part_number": _source_property(source, ts.part_number),
        "model_revision": _source_property(source, ts.model_revision),
        "units": None if units is None else {"unit": units.unit, "origin": units.origin},
        "extents": extents,
    }


def _direction_name(v: Any) -> str | None:
    try:
        x, y, z = (float(c) for c in v)
    except (TypeError, ValueError):
        return None
    for name, axis in (("x", (1, 0, 0)), ("y", (0, 1, 0)), ("z", (0, 0, 1))):
        dot = x * axis[0] + y * axis[1] + z * axis[2]
        if abs(abs(dot) - 1.0) < 1e-9:
            return ("+" if dot > 0 else "-") + name
    return None


def _freeze(
    options: DrawingOptions,
    source: Any,
    settings,
    plan: types.Plan,
    sheet: Any,
    drawn: Any = None,
    chosen: DrawingOptions | None = None,
) -> DrawingOptions:
    """The options as frozen at the first save (6.8): units, scheme, view set, sheet,
    scale, front direction and its quarter turns as this run chose them (``chosen``,
    the options the plan stage settled on). The view set is every view the
    views stage drew (``drawn``, when the plan stage hands them over), not only those
    the plan kept, so drawing them again gives every view the id it had."""
    kw: dict[str, Any] = {}
    units = getattr(getattr(source, "units", None), "unit", None)
    if options.units == "part" and units in ("in", "mm"):
        kw["units"] = units
    if options.scheme is None:
        # a simplified or complex drawing is plus/minus unless the person chose a scheme
        kw["scheme"] = (
            options.effective_scheme
            if options.detail != "full"
            else settings.gdt.scheme.get(types.settings_type(options.process), options.effective_scheme)
        )
    if options.views == "auto":
        specs = [s for s, _g in drawn] if drawn else list(plan.views)
        names = tuple(dict.fromkeys(v.name for v in specs if v.name in types.VIEW_NAMES))
        if names:
            kw["views"] = names
    if options.sheet == "auto" and isinstance(sheet, display.Sheet) and sheet.name in types.SHEET_CHOICES[1:]:
        kw["sheet"] = sheet.name
    if options.scale == "auto" and isinstance(sheet, display.Sheet):
        sc = tuple(sheet.scale)
        if len(sc) == 2 and all(
            isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= 1000 for n in sc
        ):
            kw["scale"] = sc
    if options.front is None and chosen is not None and chosen.front is not None:
        # the front and its quarter turns as the plan stage chose them (8.2)
        kw["front"], kw["turn"] = chosen.front, chosen.turn
    elif options.front is None:
        for v in plan.views:
            if v.name == "front":
                name = _direction_name(v.direction)
                if name is not None:
                    kw["front"] = name
                break
    return replace(options, **kw) if kw else options


def _planned(planned: Any, features: Any) -> tuple[types.Plan, Any, Any]:
    if isinstance(planned, types.Plan):
        plan, sheet, fs = planned, None, None
    elif isinstance(planned, tuple) and len(planned) in (2, 3) and isinstance(planned[0], types.Plan):
        plan, sheet = planned[0], planned[1]
        fs = planned[2] if len(planned) == 3 else None
    else:
        raise InvalidArgumentError(
            "planned must be the plan stage's (Plan, Sheet)", detail={"parameter": "planned"}
        )
    if features is not None:
        fs = features
    if sheet is not None and not isinstance(sheet, display.Sheet):
        raise InvalidArgumentError(
            "the planned sheet must be a display Sheet", detail={"parameter": "planned"}
        )
    if fs is not None and not isinstance(fs, types.FeatureSet):
        raise InvalidArgumentError("features must be a FeatureSet", detail={"parameter": "features"})
    return plan, sheet, fs


def new_drawing(
    source: Any,
    planned: Any,
    options: DrawingOptions | None = None,
    settings: settings_mod.DrawingSettings | None = None,
    fields: Mapping[str, str] | None = None,
    *,
    features: types.FeatureSet | None = None,
    seed: str | None = None,
    today: str | datetime.date | None = None,
    now: str | None = None,
    limits: DrawingLimits = DEFAULT_LIMITS,
) -> DrawingDocument:
    """A PRELIMINARY drawing from a run (the pipeline's ``assemble`` stage, 13.1, 13.4).

    ``planned`` is what the plan stage returns, ``(Plan, Sheet)``; ``features`` (or a
    third member of ``planned``) is the run's ``FeatureSet``, from which the feature
    table takes its descriptors: ids ``f-1``, ``f-2``... in recognition order, and each
    datum's letter as a decision on the feature that claims its face. Without it the
    table is empty and the drawing says so. Dimensions get ids ``d-1``... in planning
    order (the sheet follows), notes ``n-1``... with origin ``template``. Title fields
    come from ``fields`` (origin ``typed``; a material in the settings' list as its
    callout, origin ``list``), else from the part's properties under the settings'
    names (origin ``part``). ``fields["drawn_by"]`` signs DRAWN with ``today``. The id
    is random, or derived from ``seed`` when one is given; ``options`` are frozen as
    the run chose them."""
    from . import release

    plan, sheet, fs = _planned(planned, features)
    options = options if options is not None else DrawingOptions()
    if not isinstance(options, DrawingOptions):
        raise InvalidArgumentError("options must be DrawingOptions", detail={"parameter": "options"})
    settings = settings if settings is not None else settings_mod.DrawingSettings()
    if not isinstance(settings, settings_mod.DrawingSettings):
        raise InvalidArgumentError("settings must be DrawingSettings", detail={"parameter": "settings"})
    if not isinstance(limits, DrawingLimits):
        raise InvalidArgumentError("limits must be DrawingLimits", detail={"parameter": "limits"})
    typed = _check_fields(fields, limits)
    warnings = [str(w) for w in getattr(source, "warnings", ())]

    # The feature table, in recognition order, with each datum's letter on its feature.
    letters: dict[int, str] = {}
    records: list[FeatureRecord] = []
    extents = None
    datums = tuple(plan.datums)
    if fs is not None:
        if len(fs.features) > limits.requirements:
            raise limits.exceeded("requirements", "the part has more features than a drawing holds")
        datums = datums or tuple(fs.frame.datums)
        for datum in datums:
            for i, f in enumerate(fs.features):
                if datum.face in f.faces and i not in letters:
                    letters[i] = datum.letter
                    break
        for i, f in enumerate(fs.features):
            decisions = (("datum", letters[i]),) if i in letters else ()
            records.append(FeatureRecord(f"f-{i + 1}", f.descriptor, decisions))
        if len(fs.frame.extents) == 3:
            extents = [[float(lo), float(hi)] for lo, hi in fs.frame.extents]
    else:
        warnings.append("the plan stage handed over no feature set, so the feature table is empty")

    # Dimensions in planning order; the sheet follows any renumbering.
    if len(plan.dimensions) > limits.requirements:
        raise limits.exceeded("requirements", "the plan has more dimensions than a drawing holds")
    renumber: dict[str, str] = {}
    dims = []
    for k, d in enumerate(plan.dimensions, 1):
        ident = f"d-{k}"
        if d.id != ident:
            renumber[d.id] = ident
        dims.append(replace(as_record(d), id=ident))
    if renumber:
        if len({d.id for d in plan.dimensions}) != len(plan.dimensions):
            raise InvalidArgumentError(
                "the plan names one dimension id twice", detail={"parameter": "planned"}
            )
        sheet = remap_sheet(sheet, renumber)
    notes = tuple((f"n-{k}", NoteRecord(n.text, n.frames, "template")) for k, n in enumerate(plan.notes, 1))

    used_f = len(records)
    for d in dims:
        for ref in (*d.features, *(f for p in d.positions for f in p.features)):
            n = id_number(ref, "f")
            if n is not None:
                used_f = max(used_f, n)
    used_v = 0
    for v in plan.views:
        n = id_number(v.id, "v")
        if n is not None:
            used_v = max(used_v, n)
    first = settings.people.first_revision
    for candidate in (typed.get("revision"), _source_property(source, settings.title_sources.revision)):
        if candidate is not None and standards.is_revision(candidate):
            first = candidate
            break
    stamp = now if now is not None else _now()
    _check_now(stamp)
    drawing = DrawingDocument(
        id=_drawing_id(seed),
        options=_freeze(
            options,
            source,
            settings,
            plan,
            sheet,
            getattr(getattr(planned, "done", None), "views", None),
            getattr(getattr(planned, "done", None), "options", None),
        ),
        settings=settings,
        model=model_identity(source, settings, extents),
        title=_title(source, settings, typed, plan, limits),
        features=tuple(records),
        datums=datums,
        dimensions=tuple(dims),
        notes=notes,
        status="PRELIMINARY",
        revisions=(Revision(first, FIRST_DESCRIPTION),),
        next_id=(("f", used_f + 1), ("d", len(dims) + 1), ("n", len(notes) + 1), ("v", used_v + 1)),
        sheet=sheet,
        coverage=plan.coverage,
        warnings=tuple(warnings),
        created=stamp,
        modified=stamp,
    )
    drawn_by = typed.get("drawn_by")
    if drawn_by and drawn_by.strip():
        day = release.iso_day(today)
        drawing = replace(
            drawing, signatures=(Signature("DRAWN", drawn_by.strip(), day, release.content_digest(drawing)),)
        )
    return drawing


__all__ = [
    "EXPORT_EXTENSIONS",
    "EXTENSION",
    "MEMBERS",
    "SCHEMA",
    "DimensionRecord",
    "DrawingDocument",
    "DrawingFileError",
    "Loaded",
    "NoteRecord",
    "Placement",
    "Saved",
    "Target",
    "as_document",
    "as_record",
    "candidate_names",
    "current_revision",
    "drawing_file_name",
    "dumps",
    "export_name",
    "export_stem",
    "export_target",
    "file_sha256",
    "folder_problem",
    "is_local",
    "load",
    "loads",
    "member_values",
    "model_identity",
    "new_drawing",
    "next_free_name",
    "part_title_fields",
    "read",
    "record_output",
    "remap_sheet",
    "safe_stem",
    "save",
    "save_target",
    "says_solidseas",
    "write_output",
]
