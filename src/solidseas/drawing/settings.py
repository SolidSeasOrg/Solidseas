"""Drawing Settings: the company's details, people, standard, sheets, tolerances,
notes, materials and the rest (``docs/DRAWINGS.md`` 7).

The file is ``Drawing.json`` beside the viewer's ``Viewer.ini``: under
``%APPDATA%\\SolidSeas`` on Windows, ``~/Library/Application Support/SolidSeas`` on
macOS, ``$XDG_CONFIG_HOME/solidseas`` elsewhere. Schema
``solidseas.drawing-settings/1``, at most 256 KiB, read under the library's strict
JSON rules (no repeated keys, no NaN or infinity, at most 32 levels deep).

Every value is checked on its own. One that fails its check falls back to its
default and the reason is listed in the problems :func:`load_settings` returns;
a list of records keeps its good entries and lists each one it dropped. Members
a newer SolidSeas wrote are kept, unread, and written back, so an older version
never loses them. The library writes the file only through :func:`save_settings`,
through a temporary file and a rename; the command line never writes it.

The values that need the user's answer before a first drawing are listed by
:meth:`DrawingSettings.first_use` (the unit for parts that state none, the
company's name, the people who sign).
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import sys
from collections.abc import Callable
from dataclasses import MISSING, dataclass, field, fields, replace
from typing import Any

from ..errors import InvalidArgumentError, SldLimitError
from . import standards
from .limits import DEFAULT_LIMITS

SCHEMA = "solidseas.drawing-settings/1"
FILE_NAME = "Drawing.json"
LOGO_NAME = "logo.png"
MAX_BYTES = DEFAULT_LIMITS.settings_bytes
MAX_DEPTH = DEFAULT_LIMITS.json_depth
MAX_ITEMS = 200  # records in any list: people, materials, finishes, notes
STRING = DEFAULT_LIMITS.string_chars
TITLE = DEFAULT_LIMITS.title_chars
NOTE = DEFAULT_LIMITS.note_chars

APPROVAL_ROWS = ("DRAWN", "CHECKED", "APPROVED", "ENGR", "MFG", "QA")
TYPES = ("machined", "printed")
NOTE_TOKENS = (
    "material",
    "finish",
    "process",
    "layer_height",
    "model",
    "model_rev",
    "model_hash",
    "fillet_radius",
    "profile",
    "edge_break",
    "surface_finish",
)
ROLES = ("envelope", "step", "width", "hole_size", "hole_location", "basic")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TOKEN = re.compile(r"\{([a-z_]+)\}")


class _Bad(ValueError):
    """A value failed its check; the message says why, in words a person reads."""


# --------------------------------------------------------------------------- checks


def _text(limit: int = STRING, *, empty: bool = True, multiline: bool = False) -> Callable[[Any], str]:
    def check(v: Any) -> str:
        if not isinstance(v, str):
            raise _Bad("it is not text")
        if len(v) > limit:
            raise _Bad(f"it is longer than {limit} characters")
        if _CONTROL.search(v) or (not multiline and ("\n" in v or "\r" in v)):
            raise _Bad("it holds control characters")
        if not empty and not v.strip():
            raise _Bad("it is empty")
        return v

    return check


def _flag(v: Any) -> bool:
    if not isinstance(v, bool):
        raise _Bad("it is not true or false")
    return v


def _one_of(*choices: Any) -> Callable[[Any], Any]:
    def check(v: Any) -> Any:
        if isinstance(v, bool) or v not in choices:
            raise _Bad(f"it is not one of {', '.join(str(c) for c in choices)}")
        return v

    return check


def _number(low: float, high: float, *, whole: bool = False) -> Callable[[Any], float]:
    def check(v: Any) -> float:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise _Bad("it is not a number")
        if whole and not (isinstance(v, int) or float(v).is_integer()):
            raise _Bad("it is not a whole number")
        if not low <= v <= high:
            raise _Bad(f"it is outside {low:g} to {high:g}")
        return int(v) if whole else float(v)

    return check


def _optional(inner: Callable[[Any], Any]) -> Callable[[Any], Any]:
    def check(v: Any) -> Any:
        return None if v is None else inner(v)

    return check


def _list(
    item: Callable[[Any], Any], limit: int = MAX_ITEMS, *, unique: bool = False
) -> Callable[[Any], tuple]:
    """A list whose items are each checked; the whole fails on the first bad item (for
    short lists of plain values)."""

    def check(v: Any) -> tuple:
        if not isinstance(v, list):
            raise _Bad("it is not a list")
        if len(v) > limit:
            raise _Bad(f"it has more than {limit} entries")
        out = tuple(item(x) for x in v)
        if unique and len(set(out)) != len(out):
            raise _Bad("it names one entry twice")
        return out

    return check


def _mapping(keys: tuple[str, ...], value: Callable[[Any], Any]) -> Callable[[Any], dict]:
    """An object with exactly ``keys``, each value checked."""

    def check(v: Any) -> dict:
        if not isinstance(v, dict) or set(v) != set(keys):
            raise _Bad(f"it must name {', '.join(keys)}")
        return {k: value(v[k]) for k in keys}

    return check


def _template(v: Any) -> str:
    text = _text(NOTE)(v)
    for token in _TOKEN.findall(text):
        if token not in NOTE_TOKENS:
            raise _Bad(f"{{{token}}} is not a token a note can hold")
    if text.count("{") != text.count("}"):
        raise _Bad("its braces do not pair")
    return text


def _scale(v: Any) -> str:
    if standards.parse_scale(v) is None:
        raise _Bad("it is not a scale such as 1:2")
    return v


def _revision(v: Any) -> str:
    if not standards.is_revision(v):
        raise _Bad("it is not a revision mark (A, B, ... without I, O, Q, S, X or Z)")
    return v


def _hex64(v: Any) -> str:
    if not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v):
        raise _Bad("it is not a SHA-256")
    return v


def _url_template(v: Any) -> str:
    text = _text(2000)(v)
    if not text.startswith("https://"):
        raise _Bad("it must start with https://")
    tokens = _TOKEN.findall(text)
    if any(t not in ("subject", "to") for t in tokens):
        raise _Bad("it may hold only {subject} and {to}")
    return text


# Records: each a dict checked field by field; a bad record is dropped on its own.


_REQUIRED = object()


def _record(spec: dict[str, tuple[Any, Callable[[Any], Any]]]) -> Callable[[Any], dict]:
    def check(v: Any) -> dict:
        if not isinstance(v, dict):
            raise _Bad("it is not an object")
        out = {}
        for k, (default, fn) in spec.items():
            if k not in v and default is _REQUIRED:
                raise _Bad(f"it has no {k}")
            out[k] = fn(v[k]) if k in v else default
        extra = set(v) - set(spec)
        if extra:
            raise _Bad(f"it holds {', '.join(sorted(extra))}, which a record of this kind does not")
        return out

    return check


_PERSON = _record({"name": (_REQUIRED, _text(TITLE, empty=False)), "initials": ("", _text(8))})
_MATERIAL = _record(
    {
        "names": ((), _list(_text(TITLE, empty=False), 20)),
        "callout": (_REQUIRED, _text(TITLE, empty=False)),
        "specification": ("", _text(TITLE)),
        "density": (None, _optional(_number(1.0, 25_000.0))),  # kg/m3
        "types": (TYPES, _list(_one_of(*TYPES), 2, unique=True)),
        "heat_treatable": (False, _flag),
    }
)
_FINISH = _record(
    {
        "name": (_REQUIRED, _text(TITLE, empty=False)),
        "callout": (_REQUIRED, _text(TITLE, empty=False)),
        "types": (TYPES, _list(_one_of(*TYPES), 2, unique=True)),
        "after": (True, _flag),
    }
)
_PROCESS = _record(
    {
        "name": (_REQUIRED, _text(64, empty=False)),
        "category": ("", _text(64)),
        "xy_fixed_mm": (_REQUIRED, _number(0.0, 10.0)),
        "z_fixed_mm": (_REQUIRED, _number(0.0, 10.0)),
        "rate": (_REQUIRED, _number(0.0, 0.1)),
        "floor_mm": (0.0, _number(0.0, 10.0)),
    }
)


def _records(check: Callable[[Any], dict]) -> Callable[[Any], tuple]:
    """Marker: a list of records, checked entry by entry (see :func:`_read_value`)."""
    check.records = True  # type: ignore[attr-defined]
    return check


# --------------------------------------------------------------------------- the groups


def _plain(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def _f(default: Any, check: Callable[[Any], Any], *, records: bool = False):
    """A setting's field: its default is put through its own check, so a default and the
    same value read back from the file are equal."""
    plain = _plain(default)
    normal = tuple(check(x) for x in plain) if records else check(plain)
    meta = {"check": check, "records": records}
    try:
        hash(normal)
    except TypeError:
        return field(default_factory=lambda: copy.deepcopy(normal), metadata=meta)
    return field(default=normal, metadata=meta)


_PROPRIETARY = (
    "THIS DRAWING AND THE DESIGN IT SHOWS BELONG TO {company}. DO NOT COPY OR DISCLOSE IT, "
    "OR USE IT FOR ANY PURPOSE OTHER THAN THE ONE FOR WHICH IT WAS SUPPLIED, WITHOUT ITS WRITTEN PERMISSION."
)


@dataclass(frozen=True)
class Company:
    name: str = _f("", _text(TITLE))
    address: tuple[str, ...] = _f((), _list(_text(TITLE), 4))
    phone: str = _f("", _text(64))
    web: str = _f("", _text(TITLE))
    logo: str | None = _f(None, _optional(_hex64))  # the SHA-256 of logo.png beside the settings
    cage: str = _f("", _text(5))
    proprietary: str = _f(_PROPRIETARY, _text(NOTE, multiline=True))
    do_not_scale: bool = _f(True, _flag)


@dataclass(frozen=True)
class People:
    people: tuple[dict, ...] = _f((), _records(_PERSON), records=True)
    rows: tuple[str, ...] = _f(
        ("DRAWN", "CHECKED", "APPROVED"), _list(_one_of(*APPROVAL_ROWS), 6, unique=True)
    )
    required: tuple[str, ...] = _f(("CHECKED", "APPROVED"), _list(_one_of(*APPROVAL_ROWS), 6, unique=True))
    same_person_twice: bool = _f(True, _flag)
    date_format: str = _f("iso", _one_of("iso", "us"))
    first_revision: str = _f("A", _revision)


@dataclass(frozen=True)
class Standard:
    profile: str = _f("asme", _one_of(*standards.PROFILES))
    units: str = _f("part", _one_of("part", "in", "mm"))
    unit_for_unstated: str | None = _f(None, _optional(_one_of("in", "mm")))
    upper_case_notes: bool = _f(True, _flag)
    # the projection angle: the standard's own (third angle for ASME, first for ISO), or
    # first or third whatever the standard (docs/drawings/iso.md)
    projection: str = _f("standard", _one_of("standard", *standards.ANGLES))


@dataclass(frozen=True)
class Sheets:
    size: str = _f("auto", _one_of("auto", *standards.SHEET_ORDER))
    orientation: str = _f("landscape", _one_of("landscape", "portrait"))
    zones: bool = _f(True, _flag)
    scales: tuple[str, ...] = _f(
        tuple(standards.scale_text(s) for s in standards.SCALES), _list(_scale, 20, unique=True)
    )


_NAMES = _list(_text(TITLE, empty=False), 10)


@dataclass(frozen=True)
class TitleSources:
    part_number: tuple[str, ...] = _f(("PartNo", "Part Number", "PartNumber"), _NAMES)
    number: tuple[str, ...] = _f(("DwgNo", "Drawing Number", "DrawingNo", "Number"), _NAMES)
    title: tuple[str, ...] = _f(("Description", "Title"), _NAMES)
    revision: tuple[str, ...] = _f(("Revision", "Rev"), _NAMES)
    model_revision: tuple[str, ...] = _f(("Revision", "Rev"), _NAMES)
    material: tuple[str, ...] = _f(("Material",), _NAMES)
    finish: tuple[str, ...] = _f(("Finish",), _NAMES)
    title_style: str = _f("noun_first", _one_of("noun_first", "as_typed"))
    show_weight: bool = _f(True, _flag)


def _block(rows: tuple[standards.BlockRow, ...]) -> list:
    return [[r.places, float(r.plus_minus)] for r in rows]


def _block_check(max_places: int, high: float) -> Callable[[Any], tuple]:
    places, plus_minus = _number(0, max_places, whole=True), _number(1e-6, high)

    def check(v: Any) -> tuple:
        if not isinstance(v, list) or not 1 <= len(v) <= 6:
            raise _Bad("it must be one to six rows")
        out = []
        for r in v:
            if not isinstance(r, list) or len(r) != 2:
                raise _Bad("each row must be [places, plus or minus]")
            out.append((places(r[0]), plus_minus(r[1])))
        if len({p for p, _ in out}) != len(out):
            raise _Bad("it names one row twice")
        return tuple(sorted(out))

    return check


_PRECISION_IN = {"envelope": 2, "step": 2, "width": 2, "hole_size": 3, "hole_location": 3, "basic": 3}
_PRECISION_MM = {"envelope": 1, "step": 1, "width": 1, "hole_size": 2, "hole_location": 2, "basic": 2}


@dataclass(frozen=True)
class Tolerances:
    inch_block: tuple = _f(
        tuple((r.places, float(r.plus_minus)) for r in standards.INCH_BLOCK), _block_check(4, 1.0)
    )
    mm_block: tuple = _f(
        tuple((r.places, float(r.plus_minus)) for r in standards.MM_BLOCK), _block_check(3, 25.0)
    )
    angle: float = _f(0.5, _number(0.001, 10.0))
    mm_general: str = _f("block", _one_of("block", *(f"iso2768-{c}" for c in standards.ISO2768_CLASSES)))
    precision_in: dict = _f(_PRECISION_IN, _mapping(ROLES, _number(0, 4, whole=True)))
    precision_mm: dict = _f(_PRECISION_MM, _mapping(ROLES, _number(0, 3, whole=True)))
    show_bands: bool = _f(True, _flag)


@dataclass(frozen=True)
class Gdt:
    scheme: dict = _f(
        {"machined": "datum", "printed": "plusminus"}, _mapping(TYPES, _one_of("datum", "plusminus"))
    )
    position_in: dict = _f(
        {"clearance": 0.010, "tapped": 0.010}, _mapping(("clearance", "tapped"), _number(1e-5, 1.0))
    )
    position_mm: dict = _f(
        {"clearance": 0.25, "tapped": 0.25}, _mapping(("clearance", "tapped"), _number(1e-4, 25.0))
    )
    position_modifier: str = _f("mmc", _one_of("mmc", "lmc", "none"))
    profile_in: float = _f(0.020, _number(1e-5, 1.0))
    profile_mm: float = _f(0.4, _number(1e-4, 25.0))
    undimensioned_in: float | None = _f(None, _optional(_number(1e-5, 1.0)))
    undimensioned_mm: float | None = _f(None, _optional(_number(1e-4, 25.0)))
    runout_in: float = _f(0.005, _number(1e-5, 1.0))
    runout_mm: float = _f(0.1, _number(1e-4, 25.0))


def _process_defaults() -> list:
    return [
        {
            "name": p.name,
            "category": p.category,
            "xy_fixed_mm": round(p.xy_fixed, 6),
            "z_fixed_mm": round(p.z_fixed, 6),
            "rate": p.rate,
            "floor_mm": p.floor,
        }
        for p in standards.PROCESSES.values()
    ]


@dataclass(frozen=True)
class Printing:
    processes: tuple[dict, ...] = _f(_process_defaults(), _records(_PROCESS), records=True)
    label: str = _f("Service bureau figures; replace them with your own.", _text(TITLE))


_MACHINED_NOTES = [
    "REMOVE ALL BURRS. {edge_break}",
    "FILLETS AND ROUNDS {fillet_radius}.",
    "SURFACE FINISH {surface_finish} MAX.",
    "FINISH: {finish}.",
    "DIMENSIONS APPLY AFTER FINISH.",
]
_PRINTED_NOTES = [
    "PROCESS: {process}. BUILD DIRECTION Z AS SHOWN.",
    "MATERIAL: {material}.",
    "LAYER HEIGHT {layer_height}.",
    "REMOVE ALL SUPPORT MATERIAL.",
    "DIMENSIONS APPLY AFTER POST-PROCESSING.",
]


@dataclass(frozen=True)
class Notes:
    machined: tuple[str, ...] = _f(tuple(_MACHINED_NOTES), _list(_template, 40))
    printed: tuple[str, ...] = _f(tuple(_PRINTED_NOTES), _list(_template, 40))
    edge_break_in: str = _f("BREAK SHARP EDGES .005-.015", _text(TITLE))
    edge_break_mm: str = _f("BREAK SHARP EDGES 0.1-0.4", _text(TITLE))
    surface_finish_in: str = _f("125 µin", _text(64))
    surface_finish_mm: str = _f("Ra 3.2 µm", _text(64))


def _mat(names, callout, spec, density, types, heat=False) -> dict:
    return {
        "names": list(names),
        "callout": callout,
        "specification": spec,
        "density": density,
        "types": list(types),
        "heat_treatable": heat,
    }


_MATERIALS = [
    _mat(("6061-t6 (ss)", "6061 alloy", "6061-t6"), "ALUMINUM 6061-T6", "ASTM B221", 2700.0, ("machined",)),
    _mat(("aisi 304", "304 stainless steel"), "STAINLESS STEEL 304", "ASTM A276", 8000.0, ("machined",)),
    _mat(("aisi 1018", "1018"), "STEEL 1018", "ASTM A108", 7870.0, ("machined",)),
    _mat(("aisi 4140", "4140"), "STEEL 4140", "ASTM A322", 7850.0, ("machined",), True),
    _mat(("pla",), "PLA", "", 1240.0, ("printed",)),
    _mat(("petg",), "PETG", "", 1270.0, ("printed",)),
    _mat(("abs", "abs pc"), "ABS", "", 1040.0, ("printed", "machined")),
    _mat(("nylon 12", "pa 12", "pa12"), "NYLON 12 (PA 12)", "", 1010.0, ("printed",)),
]


def _fin(name, callout, types, after) -> dict:
    return {"name": name, "callout": callout, "types": list(types), "after": after}


_FINISHES = [
    _fin("None", "NONE", TYPES, False),
    _fin("Clear anodize", "ANODIZE PER MIL-A-8625, TYPE II, CLASS 1, CLEAR", ("machined",), True),
    _fin("Black anodize", "ANODIZE PER MIL-A-8625, TYPE II, CLASS 2, BLACK", ("machined",), True),
    _fin("Passivate", "PASSIVATE PER ASTM A967", ("machined",), True),
    _fin("As printed", "AS PRINTED", ("printed",), False),
    _fin("Bead blast", "BEAD BLAST ALL OVER", TYPES, True),
]


@dataclass(frozen=True)
class Materials:
    entries: tuple[dict, ...] = _f(_MATERIALS, _records(_MATERIAL), records=True)
    finishes: tuple[dict, ...] = _f(_FINISHES, _records(_FINISH), records=True)


_VIEW_DEFAULT = {
    "views": ["front", "top", "right"],
    "isometric": True,
    "hidden": False,
    "tangent": "hidden",
    "front": "auto",
}
_VIEW = _record(
    {
        "views": (
            ("front", "top", "right"),
            _list(_one_of("front", "top", "right", "left", "bottom", "back"), 6, unique=True),
        ),
        "isometric": (True, _flag),
        "hidden": (False, _flag),
        "tangent": ("hidden", _one_of("hidden", "thin", "phantom")),
        "front": ("auto", _one_of("auto", "+x", "-x", "+y", "-y", "+z", "-z")),
    }
)
_DIM_DEFAULT = {
    "scheme": "baseline",
    "ordinate_tracks": 6,
    "ordinate_share": 0.25,
    "hole_callouts": True,
    "thread_suggestions": True,
    "chamfer_style": "leg_angle",
    "symbol_words": False,
}
_DIM = _record(
    {
        "scheme": ("baseline", _one_of("baseline", "ordinate")),
        "ordinate_tracks": (6, _number(1, 50, whole=True)),
        "ordinate_share": (0.25, _number(0.05, 1.0)),
        "hole_callouts": (True, _flag),
        "thread_suggestions": (True, _flag),
        "chamfer_style": ("leg_angle", _one_of("leg_angle", "two_legs")),
        "symbol_words": (False, _flag),
    }
)


@dataclass(frozen=True)
class Defaults:
    """Per manufacturing type: the default views and dimensioning; and the detail level
    a new drawing starts from (simplified, complex or fully defined)."""

    views: dict = _f({t: _VIEW_DEFAULT for t in TYPES}, _mapping(TYPES, _VIEW))
    dimensioning: dict = _f({t: _DIM_DEFAULT for t in TYPES}, _mapping(TYPES, _DIM))
    detail: str = _f("full", _one_of("simplified", "complex", "full"))


def _pattern(v: Any) -> str:
    text = _text(TITLE, empty=False)(v)
    tokens = _TOKEN.findall(text)
    if "number" not in tokens or any(t not in ("number", "revision", "title", "part_number") for t in tokens):
        raise _Bad("it must hold {number} and may hold {revision}, {title} and {part_number}")
    return text


@dataclass(frozen=True)
class Files:
    folder: str | None = _f(None, _optional(_text(STRING, empty=False)))  # None: next to the part
    name_pattern: str = _f("{number} {revision}", _pattern)
    keep_preliminary_current: bool = _f(True, _flag)
    replace_own_files: bool = _f(True, _flag)  # Q14, answered: on by default


@dataclass(frozen=True)
class Email:
    method: str = _f("automatic", _one_of("automatic", "webmail", "show"))
    webmail_url: str = _f("https://mail.google.com/mail/?view=cm&fs=1&su={subject}", _url_template)
    prefill_subject: bool = _f(True, _flag)


@dataclass(frozen=True)
class Limits:
    child_memory_mb: int = _f(3072, _number(256, 65_536, whole=True))  # the DrawingLimits ceiling
    draft_faces: int = _f(2000, _number(1, DEFAULT_LIMITS.faces, whole=True))


GROUPS: dict[str, type] = {
    "company": Company,
    "people": People,
    "standard": Standard,
    "sheets": Sheets,
    "title_sources": TitleSources,
    "tolerances": Tolerances,
    "gdt": Gdt,
    "printing": Printing,
    "notes": Notes,
    "materials": Materials,
    "defaults": Defaults,
    "files": Files,
    "email": Email,
    "limits": Limits,
}


@dataclass(frozen=True)
class DrawingSettings:
    """Every Drawing Setting (7.2), group by group. ``unknown`` keeps what a newer
    SolidSeas wrote, as (group, key, value) with key None for a whole group."""

    company: Company = field(default_factory=Company)
    people: People = field(default_factory=People)
    standard: Standard = field(default_factory=Standard)
    sheets: Sheets = field(default_factory=Sheets)
    title_sources: TitleSources = field(default_factory=TitleSources)
    tolerances: Tolerances = field(default_factory=Tolerances)
    gdt: Gdt = field(default_factory=Gdt)
    printing: Printing = field(default_factory=Printing)
    notes: Notes = field(default_factory=Notes)
    materials: Materials = field(default_factory=Materials)
    defaults: Defaults = field(default_factory=Defaults)
    files: Files = field(default_factory=Files)
    email: Email = field(default_factory=Email)
    limits: Limits = field(default_factory=Limits)
    unknown: tuple = ()

    def first_use(self) -> tuple[str, ...]:
        """The settings still waiting for the user's answer, as ``group.key``: the unit
        for parts that state none (Q3), the company's name and the people who sign."""
        out = []
        if self.standard.unit_for_unstated is None:
            out.append("standard.unit_for_unstated")
        if not self.company.name.strip():
            out.append("company.name")
        if not self.people.people:
            out.append("people.people")
        return tuple(out)

    def material(self, model_name: str | None) -> dict | None:
        """The material entry a model's material name maps to: case-folded with spaces
        collapsed, equal to one of an entry's names; the first match wins (7.2)."""
        if not model_name:
            return None
        key = _fold(model_name)
        for entry in self.materials.entries:
            if any(_fold(n) == key for n in entry["names"]):
                return entry
        return None

    def finish(self, text: str | None) -> dict | None:
        """The finish entry ``text`` names: its name or its callout, case-folded with
        spaces collapsed; the first match wins."""
        if not text:
            return None
        key = _fold(text)
        for entry in self.materials.finishes:
            if _fold(entry["name"]) == key or _fold(entry["callout"]) == key:
                return entry
        return None

    def block(self, unit: str) -> tuple[standards.BlockRow, ...]:
        """The general tolerance block for ``unit`` as rows."""
        from fractions import Fraction

        rows = self.tolerances.inch_block if unit == "in" else self.tolerances.mm_block
        return tuple(standards.BlockRow(p, Fraction(str(v))) for p, v in rows)

    def precision(self, unit: str, role: str) -> int:
        table = self.tolerances.precision_in if unit == "in" else self.tolerances.precision_mm
        return table[role]


def _fold(name: str) -> str:
    return " ".join(name.casefold().split())


def default_settings(profile: str = "asme") -> DrawingSettings:
    """The defaults of ``profile``: ASME's, or ISO's (millimetres, for parts that state
    no unit too, and the standard's first-angle projection; docs/drawings/iso.md)."""
    if profile not in standards.PROFILES:
        raise InvalidArgumentError(
            f"profile must be one of {', '.join(standards.PROFILES)}", detail={"parameter": "profile"}
        )
    if profile == "iso":
        return DrawingSettings(standard=Standard(profile="iso", units="mm", unit_for_unstated="mm"))
    return DrawingSettings()


# --------------------------------------------------------------------------- reading and writing


def settings_folder(env: dict[str, str] | None = None, platform: str | None = None) -> str:
    """The folder ``Drawing.json`` lives in on this system."""
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    home = os.path.expanduser("~")
    if platform == "win32":
        base = env.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        return os.path.join(base, "SolidSeas")
    if platform == "darwin":
        return os.path.join(home, "Library", "Application Support", "SolidSeas")
    base = env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return os.path.join(base, "solidseas")


def settings_path() -> str:
    return os.path.join(settings_folder(), FILE_NAME)


def _strict(raw: bytes) -> Any:
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ValueError(f"the key {k!r} appears twice")
            out[k] = v
        return out

    def constant(name):
        raise ValueError(f"{name} is not a number Drawing Settings accept")

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    _depth(value, 0)
    return value


def _depth(value: Any, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise ValueError(f"it is nested more than {MAX_DEPTH} levels deep")
    if isinstance(value, dict):
        for v in value.values():
            _depth(v, depth + 1)
    elif isinstance(value, list):
        for v in value:
            _depth(v, depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("it holds a number too large to be finite")


def _read_value(group: str, f, raw: Any, problems: list[str]) -> Any:
    check = f.metadata["check"]
    if f.metadata.get("records"):
        if not isinstance(raw, list):
            problems.append(f"{group}.{f.name}: it is not a list; the default is used")
            return _default(f)
        kept = []
        for k, item in enumerate(raw[:MAX_ITEMS]):
            try:
                kept.append(check(item))
            except _Bad as exc:
                problems.append(f"{group}.{f.name}[{k}]: {exc}; the entry is left out")
        if len(raw) > MAX_ITEMS:
            problems.append(f"{group}.{f.name}: only the first {MAX_ITEMS} entries are kept")
        return tuple(kept)
    try:
        return check(raw)
    except _Bad as exc:
        problems.append(f"{group}.{f.name}: {exc}; the default is used")
        return _default(f)


def _default(f) -> Any:
    return f.default if f.default is not MISSING else f.default_factory()


def from_dict(data: Any) -> tuple[DrawingSettings, list[str]]:
    """Settings from their JSON object, and the problems found: every value checked on
    its own, a bad one replaced by its default."""
    problems: list[str] = []
    if not isinstance(data, dict):
        return DrawingSettings(), ["the settings are not an object; the defaults are used"]
    schema = data.get("schema")
    if schema != SCHEMA:
        prefix = SCHEMA.rsplit("/", 1)[0] + "/"
        major = schema[len(prefix) :] if isinstance(schema, str) and schema.startswith(prefix) else ""
        if not (major.isdigit() and int(major) > 1):
            return DrawingSettings(), [
                f"the file is not Drawing Settings ({schema!r}); the defaults are used"
            ]
        problems.append(
            f"the settings were written by a newer SolidSeas ({schema}); what this one knows is read"
        )
    groups: dict[str, Any] = {}
    unknown: list = []
    for name, value in data.items():
        if name == "schema":
            continue
        cls = GROUPS.get(name)
        if cls is None:
            unknown.append((name, None, value))
            continue
        if not isinstance(value, dict):
            problems.append(f"{name}: it is not an object; its defaults are used")
            continue
        known = {f.name: f for f in fields(cls)}
        kwargs = {}
        for key, raw in value.items():
            f = known.get(key)
            if f is None:
                unknown.append((name, key, raw))
                continue
            kwargs[key] = _read_value(name, f, raw, problems)
        groups[name] = cls(**kwargs)
    return DrawingSettings(**groups, unknown=tuple(unknown)), problems


def to_dict(settings: DrawingSettings) -> dict[str, Any]:
    """The settings as their JSON object, unknown members included, in a fixed order."""
    out: dict[str, Any] = {"schema": SCHEMA}
    for name in GROUPS:
        group = getattr(settings, name)
        out[name] = {f.name: _plain(getattr(group, f.name)) for f in fields(group)}
    for group, key, value in settings.unknown:
        if key is None:
            out.setdefault(group, value)
        elif isinstance(out.get(group), dict):
            out[group].setdefault(key, value)
    return out


def dumps(settings: DrawingSettings) -> bytes:
    """The file's bytes: UTF-8 JSON, two-space indented, a newline at the end."""
    return (json.dumps(to_dict(settings), ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode(
        "utf-8"
    )


def load_settings(path: str | os.PathLike | None = None) -> tuple[DrawingSettings, list[str]]:
    """The effective settings and the problems found. A missing file gives the defaults
    with no problem; a file over 256 KiB, not UTF-8 or not strict JSON gives the
    defaults with that problem. The file is never written here."""
    target = os.fspath(path) if path is not None else settings_path()
    try:
        with open(target, "rb") as fh:
            raw = fh.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return DrawingSettings(), []
    except OSError as exc:
        return DrawingSettings(), [
            f"the settings file could not be read ({exc.strerror or exc}); the defaults are used"
        ]
    if len(raw) > MAX_BYTES:
        return DrawingSettings(), [
            f"the settings file is larger than {MAX_BYTES // 1024} KiB; the defaults are used"
        ]
    try:
        data = _strict(raw)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        return DrawingSettings(), [f"the settings file is not valid ({exc}); the defaults are used"]
    return from_dict(data)


def save_settings(settings: DrawingSettings, path: str | os.PathLike | None = None) -> str:
    """Write the settings through a temporary file and a rename, never through a link;
    returns the path. Refuses settings over 256 KiB."""
    from ..export import write_new

    if not isinstance(settings, DrawingSettings):
        raise InvalidArgumentError("settings must be DrawingSettings", detail={"parameter": "settings"})
    data = dumps(settings)
    if len(data) > MAX_BYTES:
        raise SldLimitError("the settings are larger than 256 KiB", detail={"limit": "settings_bytes"})
    target = os.fspath(path) if path is not None else settings_path()
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)

    def write(fh) -> int:
        fh.write(data)
        return len(data)

    written, _size = write_new(target, write, overwrite=True)
    return written


def logo_problem(png: bytes, sha256: str | None) -> str | None:
    """Why a stored logo is not used, or None: it must be the narrow PNG of 7.1 (8-bit
    RGB or RGBA, not interlaced, at most 1,200 pixels a side and 512 KiB) whose hash
    the settings record. Only the header is read; nothing is decoded further."""
    if sha256 is None:
        return "no logo is set"
    if not isinstance(png, (bytes, bytearray)) or len(png) > DEFAULT_LIMITS.logo_bytes:
        return "the logo is larger than 512 KiB"
    if hashlib.sha256(png).hexdigest() != sha256:
        return "the logo file does not match the one the settings recorded"
    if png[:8] != b"\x89PNG\r\n\x1a\n" or png[12:16] != b"IHDR" or len(png) < 33:
        return "the logo is not a PNG"
    width, height = int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")
    depth, colour, _comp, _filter, interlace = png[24], png[25], png[26], png[27], png[28]
    if not (0 < width <= DEFAULT_LIMITS.logo_pixels and 0 < height <= DEFAULT_LIMITS.logo_pixels):
        return "the logo is more than 1,200 pixels a side"
    if depth != 8 or colour not in (2, 6) or interlace != 0:
        return "the logo is not an 8-bit RGB or RGBA PNG without interlacing"
    return None


def with_value(settings: DrawingSettings, group: str, key: str, value: Any) -> DrawingSettings:
    """A copy of ``settings`` with one value changed, checked as loading checks it;
    InvalidArgumentError names the setting when the value fails."""
    cls = GROUPS.get(group)
    if cls is None:
        raise InvalidArgumentError(f"there is no settings group {group!r}", detail={"parameter": "group"})
    known = {f.name: f for f in fields(cls)}
    f = known.get(key)
    if f is None:
        raise InvalidArgumentError(f"there is no setting {group}.{key}", detail={"parameter": "key"})
    problems: list[str] = []
    checked = _read_value(group, f, json.loads(json.dumps(_plain(value))), problems)
    if problems:
        raise InvalidArgumentError(problems[0], detail={"parameter": f"{group}.{key}"})
    return replace(settings, **{group: replace(getattr(settings, group), **{key: checked})})


__all__ = [
    "APPROVAL_ROWS",
    "FILE_NAME",
    "GROUPS",
    "LOGO_NAME",
    "NOTE_TOKENS",
    "SCHEMA",
    "DrawingSettings",
    "default_settings",
    "dumps",
    "from_dict",
    "load_settings",
    "logo_problem",
    "save_settings",
    "settings_folder",
    "settings_path",
    "to_dict",
    "with_value",
]
