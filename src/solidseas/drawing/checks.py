"""The automated checklist (``docs/DRAWINGS.md`` 20.1).

:func:`run_checks` reads a drawing and gives every finding as a :class:`Check`: its
id from the 20.1 table (``R4.complete``, ``COV.unclaimed``...), its level
(``error``, ``warning`` or ``information``), a message a drafter reads, the item it
is about (a dimension, feature, view, title field or note, or the code itself when
it is about the drawing) and the fixes in words, in the style of 10.12 ("4X Ø.266
holes are not located along X", Restore, Add).

**Two modes.** With ``planned`` (the plan stage's :class:`~.plan.Planned`) and
``layout`` (its :class:`~.layout.LayoutResult`), a live run, every check runs: the
ones that read the model (the graphs, the witnesses, the views' directions) read
the plan's detail, and the layout's own checks are mapped onto the ids they belong
to (:data:`LAYOUT_CODES`). With the drawing alone, as read from a file, the checks
the file can answer run (the title, units, tolerance block, stamps and names,
signatures, overrides, the sheet's items, text heights from the painted layer,
callout grammar from the records, and the rest of :data:`CODES` marked ``file``)
and those that need the model (:data:`MODEL_ONLY`) are skipped: nothing is
reported for them, and nothing is guessed.

**Levels.** Each id has the severity of the table. The exceptions it gives are
kept: ``R2.rounding`` is an error above half the band; ``R3.roles`` is
information until CHECKED is signed; ``COV.unclaimed`` is a warning, an error
with ``release=True``; ``R6.material`` and ``R6.signatures`` are errors only with
``release=True``; ``R13.plusminus`` is information on printed parts. An
``R2.override`` or ``COV.unclaimed`` item the drawing records as accepted (Release
keeps the typed reason) is information. A typed material not in the list stays a
warning at release, because Release refuses it itself until it is accepted as
typed; the model-governs note is held under ``R15.process``, so the reason that
accepts unclaimed geometry never accepts a missing note (docs/drawings/checks.md).

**Assemblies.** An assembly's drawing (:mod:`.assembly`) has no dimensions, so the
checks of its dimensions' units and tolerances, material, notes, process, feature
coverage and schemes do not run on it, and a view need not carry a dimension; its
own, ``ASM.parts`` and ``ASM.balloons``, check that the sheet has the parts list
and that every item of it has a balloon (docs/drawings/assemblies.md).

The order is fixed: by code, then item, then message, numbers in ids compared as
numbers. Nothing here reads a file, the clock or the network.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from types import SimpleNamespace
from typing import Any

from ..errors import InvalidArgumentError
from . import display as D
from . import fonts, numbers, standards, types
from . import settings as settings_mod
from .assembly import is_assembly
from .layout import LayoutResult
from .layout.checks import FURNITURE, LEADER_MAX, LEADER_MIN
from .layout.index import Box
from .layout.patterns import closed, length_of
from .layout.stamps import PRELIMINARY
from .numbers import plain_sum
from .plan import Planned
from .plan.graph import witness_in
from .plan.notes import PROFILE_WORDS, upper
from .plan.schemes import MIN_DEEP
from .plan.values import dim_text, feature_words, length_text, text_line

LEVELS = ("error", "warning", "information")

# Every id of the 20.1 table: its severity there, and what it reads (``file``: the
# drawing alone answers it, in part where docs/drawings/checks.md says so; ``model``:
# only a live run with the plan's detail does).
CODES: dict[str, tuple[str, str]] = {
    "R1.aligned": ("error", "model"),
    "R1.scale": ("error", "file"),
    "R1.symbol": ("error", "file"),
    "R2.units": ("error", "file"),
    "R2.format": ("error", "file"),
    "R2.rounding": ("warning", "file"),
    "R2.override": ("error", "file"),
    "R3.tolerance": ("error", "file"),
    "R3.block": ("error", "file"),
    "R3.basic": ("error", "file"),
    "R3.roles": ("information", "file"),
    "R4.complete": ("error", "model"),
    "R4.redundant": ("error", "model"),
    "R4.members": ("error", "model"),
    "R4.coincident": ("error", "model"),
    "R5.visible": ("error", "model"),
    "R5.true_shape": ("error", "model"),
    "R6.title": ("error", "file"),
    "R6.material": ("error", "file"),
    "R6.signatures": ("error", "file"),
    "R7.callouts": ("error", "file"),
    "R8.sheet": ("error", "file"),
    "R9.lines": ("warning", "file"),
    "R10.text": ("error", "file"),
    "R11.collisions": ("error", "file"),
    "R11.spacing": ("warning", "file"),
    "R11.leaders": ("warning", "file"),
    "R12.views": ("warning", "file"),
    "R13.scheme": ("warning", "model"),
    "R13.plusminus": ("warning", "file"),
    "R14.notes": ("warning", "file"),
    "R15.process": ("error", "file"),
    "R18.datums": ("error", "file"),
    "R18.frames": ("error", "file"),
    "COV.unclaimed": ("warning", "file"),
    "REL.stamp": ("error", "file"),
    "ASM.parts": ("error", "file"),
    "ASM.balloons": ("warning", "file"),
}
MODEL_ONLY = tuple(code for code, (_level, reads) in CODES.items() if reads == "model")

# The layout's checks (layout/checks.py, 11.6) and the ids they belong to.
LAYOUT_CODES = {
    "L.overlap": "R11.collisions",
    "L.outside": "R8.sheet",
    "L.reserved": "R8.sheet",
    "L.leader": "R11.leaders",
    "L.placement": "R11.collisions",
    "L.cramped": "R12.views",
    "L.characters": "R10.text",
}
_LAYOUT_FIXES = {
    "L.overlap": ("Move",),
    "L.outside": ("Move",),
    "L.reserved": ("Move",),
    "L.leader": ("Move",),
    "L.placement": ("Move", "Lay Out Again"),
    "L.cramped": ("Add Detail View", "Sheet and Scale"),
    "L.characters": ("Edit the Text",),
}

# Decisions on a feature that confirm an ``into_bore`` end (10.9, 10.12 confirm_end).
END_DECISIONS = ("end", "into_bore", "into_bore_note")
# Letters drawn inside a symbol rather than lettering: the spotface's SF and the MMC and
# LMC modifiers' M and L (layout/glyphs.py).
GLYPH_LETTERS = frozenset({"SF", "M", "L"})
# Lower case a note may keep (plan/notes.py upper): the micro sign's units.
_UNIT_WORDS = ("µm", "µin")
_ROUNDING_ERROR = Fraction(1, 2)  # R2.rounding is an error above half the band
_SLACK = 0.01  # millimetres on the sheet: micrometre rounding of the compact form and float noise
_LEADER_SHOULDER = 3.0  # layout/dimension.py leader_block
_LETTERED = ("dimensions", "notes")
_TOLERANCE_KINDS = ("block", "basic", "reference", "derived", *numbers.TOLERANCE_KINDS)
_NOT_VALUES = ("datum_feature", "frame")
_COUNT = re.compile(r"^\s*([1-9][0-9]*)\s*[X×]\s*")
_NUMBER = re.compile(r"[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")
_DECIMAL = re.compile(r"(?<![0-9.])([0-9]*)\.([0-9]+)")
_INT = re.compile(r"([0-9]+)")
_TYP = re.compile(r"\bTYP\b\.?", re.I)
_THREAD = re.compile(
    r"^(?:M[0-9]+(?:\.[0-9]+)?(?:\s*[xX×]\s*[0-9]+(?:\.[0-9]+)?)?(?:-[0-9][A-Za-z])?"
    r"|(?:#[0-9]+|[0-9]+/[0-9]+|[0-9]+)-[0-9]+\s*UN[A-Z]{0,2}(?:-[0-9][AB])?)(?=\s|$)"
)
_LABEL = re.compile(r"^(SECTION|DETAIL) ([A-Z]{1,2})(?:-([A-Z]{1,2}))?(?: .*)?$")
_PROCESS_NOTE = "GENERAL TOLERANCES"
_SEE_NOTE = re.compile(r"SEE NOTE ([0-9]+)")
_MODEL_NOTE = "REDUCED-DIMENSION DRAWING"


@dataclass(frozen=True)
class Check:
    """One finding of the checklist: ``code`` an id of 20.1, ``level`` one of
    :data:`LEVELS`, ``message`` in words, ``item`` what it is about, ``fixes`` the
    remedies in words. ``other``, for two items that collide, is the item ``item``
    collides with: kept in memory only (counts of what collides with what), never
    written, and two checks that differ only in it are equal."""

    code: str
    level: str
    message: str
    item: str = ""
    fixes: tuple[str, ...] = ()
    other: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code:
            raise InvalidArgumentError("a check's code must be text", detail={"parameter": "code"})
        if self.level not in LEVELS:
            raise InvalidArgumentError(
                f"a check's level must be one of {', '.join(LEVELS)}", detail={"parameter": "level"}
            )
        if not isinstance(self.message, str) or not self.message:
            raise InvalidArgumentError("a check's message must be text", detail={"parameter": "message"})
        if not isinstance(self.item, str):
            raise InvalidArgumentError("a check's item must be text", detail={"parameter": "item"})
        if not isinstance(self.fixes, tuple) or not all(isinstance(f, str) for f in self.fixes):
            raise InvalidArgumentError("a check's fixes must be words", detail={"parameter": "fixes"})
        if not isinstance(self.other, str):
            raise InvalidArgumentError("a check's other item must be text", detail={"parameter": "other"})

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "level": self.level,
            "message": self.message,
            "item": self.item,
            "fixes": list(self.fixes),
        }


# --------------------------------------------------------------------------- helpers


def _natural(text: str) -> tuple:
    """A sort key that compares the numbers in ``text`` as numbers (d-2 before d-10)."""
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in _INT.split(text) if p)


def _order(check: Check) -> tuple:
    return (_natural(check.code), _natural(check.item), check.message, check.level, check.fixes)


def _plural(n: int, word: str, words: str | None = None) -> str:
    return f"{n} {word if n == 1 else (words or word + 's')}"


def _count_of(prefix: str) -> int | None:
    m = _COUNT.match(prefix or "")
    return int(m.group(1)) if m else None


def _box_of(item: Any) -> tuple[float, float, float, float] | None:
    b = getattr(item, "bounds", None)
    if b is None:
        return None
    try:
        return b()
    except (ValueError, ZeroDivisionError):
        return None


def _text_box(run: D.TextRun) -> Box:
    """The box a text run covers, as layout measures it (layout/glyphs.py Pen.text)."""
    h = run.size * fonts.CAP_HEIGHT
    w = run.width
    if abs(run.angle_deg) > 1e-9:
        off = {"centre": w / 2, "right": w}.get(run.anchor, 0.0)
        return Box(run.x - h * 1.05, run.y - off, run.x + h * 0.3, run.y - off + w)
    x0 = {"centre": run.x - w / 2, "right": run.x - w}.get(run.anchor, run.x)
    return Box(x0, run.y - 0.25 * h, x0 + w, run.y + h)


def _two_points(path) -> tuple[tuple[float, float], tuple[float, float]] | None:
    if len(path) == 2 and path[0][0] == "M" and path[1][0] == "L":
        return (path[0][1], path[0][2]), (path[1][1], path[1][2])
    return None


def _furniture(owner: str) -> bool:
    return owner.split("-")[0] in FURNITURE or owner.startswith("n-")


def _dec(x: float) -> Decimal:
    """``x`` as a Decimal of 12 significant digits, as numbers.py reads a value."""
    if not math.isfinite(x):
        raise InvalidArgumentError("a drawing value must be finite", detail={"parameter": "value"})
    return Decimal(f"{x:.12g}")


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


# --------------------------------------------------------------------------- what the checks read


class _In:
    """The drawing, and in a live run the plan and layout, as every check reads them."""

    def __init__(
        self, drawing: types.Drawing, planned: Planned | None, layout: LayoutResult | None, release: bool
    ):
        self.drawing = drawing
        self.planned = planned
        self.layout = layout
        self.release = release
        self.detail = planned.detail if planned is not None else None
        self.ctx = self.detail.ctx if self.detail is not None else None
        s = drawing.settings
        self.settings = s if isinstance(s, settings_mod.DrawingSettings) else settings_mod.DrawingSettings()
        sheet = drawing.sheet if isinstance(drawing.sheet, D.Sheet) else None
        if sheet is None and layout is not None:
            sheet = layout.sheet
        self.sheet: D.Sheet | None = sheet
        self.sheets = D.sheets_of(sheet)
        # every view drawn, on whichever of the drawing's sheets: the sheet it is on, from 1
        self.placed = {p.view: n for n, page in enumerate(self.sheets, 1) for p in page.views}
        self.process = drawing.options.process
        self.assembly = is_assembly(drawing)
        self.unit = self._unit()
        self.fmt = SimpleNamespace(unit=self.unit, process=self.process)
        self.shown = [d for d in drawing.dimensions if d.state == "shown"]
        self.records = {r.id: r for r in drawing.features}
        self.decisions = {r.id: dict(r.decisions) for r in drawing.features}
        self.accepted = dict(getattr(drawing, "accepted", ()) or ())
        self.annotations = tuple(sheet.annotations) if sheet is not None else ()
        self.sheet_dims = {a.id: a for a in self.annotations if isinstance(a, D.Dimension)}
        self.title_block = next((a for a in self.annotations if isinstance(a, D.TitleBlock)), None)
        self.fields = dict(self.title_block.fields) if self.title_block is not None else {}
        self.notes = [(nid, n) for nid, n in drawing.notes]
        self.plan_dims = self._plan_dims()
        self._view_boxes: dict[str, Box] | None = None

    # ------------------------------------------------------------------ the drawing's unit

    def _unit(self) -> str:
        if self.ctx is not None:
            return self.ctx.unit
        u = self.drawing.options.units
        if u in numbers.UNITS:
            return u
        if self.settings.standard.units in numbers.UNITS:
            return self.settings.standard.units
        units = (self.drawing.model or {}).get("units")
        if isinstance(units, Mapping) and units.get("unit") in numbers.UNITS:
            return units["unit"]
        return self.settings.standard.unit_for_unstated or "mm"

    # ------------------------------------------------------------------ the plan's dimensions

    def _plan_dims(self) -> dict[str, types.PlannedDimension]:
        """Each drawing dimension's planned one, by the drawing's id: the same id with
        the same key (new_drawing numbers them in planning order), else the same key."""
        if self.planned is None:
            return {}
        by_id = {p.id: p for p in self.planned.plan.dimensions}
        by_key: dict[tuple[str, str], list[types.PlannedDimension]] = {}
        for p in self.planned.plan.dimensions:
            by_key.setdefault((p.key, p.kind), []).append(p)
        out: dict[str, types.PlannedDimension] = {}
        used: set[str] = set()
        for d in self.drawing.dimensions:
            p = by_id.get(d.id)
            if p is not None and p.key == d.key and p.kind == d.kind:
                out[d.id] = p
                used.add(p.id)
        for d in self.drawing.dimensions:
            if d.id in out:
                continue
            for p in by_key.get((d.key, d.kind), ()):
                if p.id not in used:
                    out[d.id] = p
                    used.add(p.id)
                    break
        return out

    # ------------------------------------------------------------------ words

    def text_of(self, d: types.PlannedDimension) -> str:
        """A dimension as the sheet reads it."""
        override = getattr(d, "override", None)
        if override:
            return override
        ann = self.sheet_dims.get(d.id)
        if ann is not None:
            return text_line(ann.text)
        try:
            return text_line(dim_text(self.fmt, d))
        except (InvalidArgumentError, ValueError, ArithmeticError):
            return d.id

    def named(self, d: types.PlannedDimension) -> str:
        return f"{d.id} ({self.text_of(d)})"

    def feature_words(self, fids: Iterable[str]) -> str:
        fids = [f for f in fids if f]
        if not fids:
            return "a face"
        if self.ctx is not None:
            return feature_words(self.ctx, fids)
        out = [self._file_words(f) for f in fids[:2]]
        words = " and ".join(out)
        if len(fids) > 2:
            words += f" and {len(fids) - 2} more"
        return words

    def _file_words(self, fid: str) -> str:
        rec = self.records.get(fid)
        if rec is None:
            return fid
        size = dict(rec.descriptor.size)
        kind = rec.descriptor.type.lower()
        places = self.settings.precision(self.unit, "hole_size")

        def dia(v) -> str | None:
            if isinstance(v, (list, tuple)) and v:
                v = v[-1]
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                return standards.SYMBOL_DIAMETER + numbers.number(
                    numbers.in_unit(v, self.unit), places, self.unit
                )
            return None

        if kind == "pattern":
            d = dia(size.get("hole"))
            n = size.get("count")
            if isinstance(n, int) and d:
                return f"{n}X {d} holes"
        if kind == "hole":
            d = dia(size.get("diameters"))
            if d:
                return f"the {d} hole"
        return f"{fid} ({rec.descriptor.type})"

    def verb(self, words: str) -> str:
        """``are`` for features in the plural (``4X Ø6.60 holes``, two named), else ``is``."""
        return "are" if words.endswith(" holes") or " and " in words else "is"

    # ------------------------------------------------------------------ the sheet

    def view_boxes(self) -> dict[str, Box]:
        """Each view's box on the sheet it is on: its geometry and centre marks (a box no
        larger than the one layout measured bands from)."""
        if self._view_boxes is not None:
            return self._view_boxes
        boxes: dict[str, list[float]] = {}

        def grow(view: str, b) -> None:
            if not view or b is None:
                return
            cur = boxes.get(view)
            if cur is None:
                boxes[view] = [b[0], b[1], b[2], b[3]]
            else:
                cur[0], cur[1] = min(cur[0], b[0]), min(cur[1], b[1])
                cur[2], cur[3] = max(cur[2], b[2]), max(cur[3], b[3])

        for page in self.sheets:  # a view is on one sheet: its box is in that sheet's frame
            for g in page.geometry:
                grow(getattr(getattr(g, "src", None), "view", ""), _box_of(g))
            for a in page.annotations:
                if isinstance(a, D.CentreMark):
                    c, r = a.centre, a.radius
                    grow(a.view, (c[0] - r, c[1] - r, c[0] + r, c[1] + r))
        self._view_boxes = {v: Box(*b) for v, b in boxes.items()}
        return self._view_boxes

    def texts(self, layers: Iterable[str]) -> list[D.TextRun]:
        if self.sheet is None:
            return []
        layers = tuple(layers)
        return [p for p in self.sheet.painted if isinstance(p, D.TextRun) and p.layer in layers]

    def specs(self) -> dict[str, types.ViewSpec]:
        if self.planned is None:
            return {}
        return {v.id: v for v in self.planned.plan.views}

    def graph_view(self, view_id: str):
        try:
            return self.ctx.view(view_id)
        except (KeyError, AttributeError):
            return None


class _Out:
    """The checks found, with each code's level from the table unless one is given."""

    def __init__(self) -> None:
        self.items: list[Check] = []

    def add(
        self,
        code: str,
        message: str,
        item: str = "",
        fixes: tuple[str, ...] = (),
        level: str | None = None,
        other: str = "",
    ) -> None:
        self.items.append(Check(code, level or CODES[code][0], message, item or code, tuple(fixes), other))


# --------------------------------------------------------------------------- R1: projection and scale


def _r1_symbol(s: _In, out: _Out) -> None:
    if s.sheet is None:
        return
    symbols = [a for a in s.annotations if isinstance(a, D.ProjectionSymbol)]
    if not symbols:
        out.add(
            "R1.symbol",
            "the title block has no projection symbol",
            "projection",
            ("Lay Out Again",),
        )
        return
    angle = standards.projection(s.settings)
    for p in symbols:
        if p.angle != angle:
            out.add(
                "R1.symbol",
                f"the projection symbol shows {p.angle}-angle projection; the drawing is {angle} angle",
                "projection",
                ("Lay Out Again",),
            )
    if len(symbols) > 1:
        out.add("R1.symbol", f"the projection symbol appears {len(symbols)} times", "projection")


def _r1_scale(s: _In, out: _Out) -> None:
    if s.sheet is None:
        return
    stated = s.fields.get("scale", "")
    drawn = standards.scale_text(tuple(s.sheet.scale))
    if s.title_block is not None and stated and stated != drawn:
        out.add(
            "R1.scale",
            f"the title block says SCALE {stated} but the views are drawn at {drawn}",
            "scale",
            ("Lay Out Again",),
        )
    specs = s.specs()
    if not specs:
        return  # which view is the isometric, or a detail, is the plan's to say
    factor = standards.scale_factor(tuple(s.sheet.scale))
    labels = {a.view: a.text for a in s.annotations if isinstance(a, D.ViewLabel)}
    for p in s.sheet.views:
        spec = specs.get(p.view)
        if spec is None or spec.kind == "isometric":
            continue
        if abs(p.scale - factor) <= 1e-9 * max(1.0, factor):
            continue
        if "SCALE" in labels.get(p.view, ""):
            continue
        out.add(
            "R1.scale",
            f"{p.view} is drawn at another scale than the sheet's {drawn} and its label does not say which",
            p.view,
            ("Label the Scale",),
        )


def _r1_aligned(s: _In, out: _Out) -> None:
    if s.sheet is None or s.planned is None:
        return
    specs = s.specs()
    placed = {p.view: p for p in s.sheet.views}
    boxes = s.view_boxes()
    for spec in s.planned.plan.views:
        if spec.kind != "projected" or spec.parent is None:
            continue
        parent = specs.get(spec.parent)
        pc, pp = placed.get(spec.id), placed.get(spec.parent)
        if parent is None or pc is None or pp is None:
            continue
        if abs(pc.scale - pp.scale) > 1e-9 * max(1.0, pp.scale):
            out.add(
                "R1.aligned",
                f"{spec.id} is drawn at another scale than {parent.id}, the view it is projected from",
                spec.id,
                ("Lay Out Again",),
            )
            continue
        rc, uc, dc = spec.frame()
        rp, up, _dp = parent.frame()
        shared = False
        for k, (a, b) in enumerate(((rc, rp), (uc, up))):
            if abs(_dot(a, b) - 1.0) <= 1e-9:
                shared = True
                off = abs(pc.origin[k] - pp.origin[k])
                if off > _SLACK:
                    out.add(
                        "R1.aligned",
                        f"{spec.id} is {off:.2f} mm out of line with {parent.id}; "
                        "projected views line up within 0.01 mm",
                        spec.id,
                        ("Lay Out Again",),
                    )
        if not shared:
            out.add(
                "R1.aligned",
                f"{spec.id} shares no sheet axis with {parent.id}, the view it is projected from",
                spec.id,
                ("Lay Out Again",),
            )
            continue
        bc, bp = boxes.get(spec.id), boxes.get(parent.id)
        if bc is None or bp is None:
            continue
        # third angle: on the side the view is seen from; first angle: on the far side
        angle = standards.projection(s.settings)
        sign = 1.0 if angle == "third" else -1.0
        side = (sign * _dot(dc, rp), sign * _dot(dc, up))
        (cx, cy), (px, py) = bc.centre(), bp.centre()
        if side[0] * (cx - px) < -_SLACK or side[1] * (cy - py) < -_SLACK:
            out.add(
                "R1.aligned",
                f"{spec.id} stands on the wrong side of {parent.id} for {angle}-angle projection",
                spec.id,
                ("Lay Out Again",),
            )


# --------------------------------------------------------------------------- R2: units and values


def _tolerance_lines(s: _In) -> list[str]:
    return [line for a in s.annotations if isinstance(a, D.ToleranceBlock) for line in a.lines]


def _r2_units(s: _In, out: _Out) -> None:
    if s.sheet is None:
        return
    said = [line for line in _tolerance_lines(s) if "DIMENSIONS ARE IN" in line.upper()]
    said += [n.text for _i, n in s.notes if "DIMENSIONS ARE IN" in n.text.upper()]
    if not said:
        out.add(
            "R2.units",
            "the drawing does not say what unit its dimensions are in",
            "units",
            ("Lay Out Again",),
        )
        return
    if len(said) > 1:
        out.add(
            "R2.units",
            f"the units are stated {len(said)} times; they are stated once, in the tolerance block",
            "units",
            ("Edit Notes",),
        )
    word = numbers.UNIT_WORDS[s.unit]
    for line in said:
        if word not in line.upper():
            out.add(
                "R2.units",
                f"the units statement '{line}' does not say {word}, the unit the dimensions are in",
                "units",
                ("Lay Out Again",),
            )


def _number_problem(token: str, unit: str) -> str | None:
    """Why a number as written breaks 10.8's rule for ``unit``, or None."""
    m = _DECIMAL.search(token)
    if m is None:
        return None
    whole = m.group(1)
    if unit == "in" and whole == "0":
        return f"{m.group(0)} has a leading zero, which inch values do not"
    if unit == "mm" and whole == "":
        return f"{m.group(0)} has no leading zero, which millimetre values need"
    return None


def _decimals(token: str) -> int | None:
    m = _DECIMAL.search(token)
    if m is not None:
        return len(m.group(2))
    return 0 if _INT.search(token) else None


def _format_problems(s: _In, d: types.PlannedDimension, t: D.DimText) -> list[str]:
    out: list[str] = []
    unit = s.unit
    lines = [t.value, t.after, t.upper, t.lower, *t.suffix]
    for line in lines:
        for tok in _NUMBER.findall(line or ""):
            why = _number_problem(tok, unit)
            if why:
                out.append(why)
    if d.kind in ("leader_note",) + _NOT_VALUES:
        return out
    value = t.value
    if d.kind == "angle":
        if value and not value.rstrip(")").endswith(standards.SYMBOL_DEGREE):
            out.append(f"the angle {value} has no degree sign")
        for part in (t.after, t.upper, t.lower):
            if part and _NUMBER.search(part) and standards.SYMBOL_DEGREE not in part:
                out.append(f"the angle's tolerance {part} has no degree sign")
        return out
    tol = d.tolerance
    if tol == "derived":
        return out
    if tol == "basic":
        if not t.boxed:
            out.append("it is basic but not boxed")
        if t.after or t.upper or t.lower:
            out.append("it is basic and carries a tolerance; a basic value carries none")
        return out
    if tol == "reference":
        if not (value.startswith("(") and value.endswith(")")):
            out.append("it is a reference but not in parentheses")
        return out
    if tol == "limits":
        try:
            if Decimal(_NUMBER.findall(t.upper)[0]) < Decimal(_NUMBER.findall(t.lower)[0]):
                out.append("its upper limit stands below its lower one")
        except (IndexError, InvalidOperation):
            out.append("it is toleranced by limits but does not show both")
        return out
    places = _decimals(value)
    if s.process in types.MACHINING and places is not None and places != d.places:
        out.append(f"{value} shows {_plural(places, 'place')} where its precision is {d.places}")
    if tol in ("max", "min") and t.after != tol.upper():
        out.append(f"it is a {tol.upper()} value, and {tol.upper()} does not follow it")
    if tol == "symmetric":
        if not t.after.startswith(standards.SYMBOL_PLUS_MINUS):
            out.append("its symmetric tolerance is not written with ±")
        elif unit == "in" and _decimals(t.after) != places:
            out.append(f"the tolerance {t.after} does not carry the value's {places} places")
    if tol == "deviations":
        for dev in (t.upper, t.lower):
            if unit == "in":
                if dev[:1] not in ("+", "-"):
                    out.append(f"the deviation {dev} has no sign")
                elif _decimals(dev) != places:
                    out.append(f"the deviation {dev} does not carry the value's {places} places")
            else:
                if dev.lstrip("+-") and Decimal(dev.lstrip("+-") or "0") == 0 and dev != "0":
                    out.append(f"its zero deviation reads {dev}; in millimetres it is a lone 0")
                elif dev != "0" and dev[:1] not in ("+", "-"):
                    out.append(f"the deviation {dev} has no sign")
    return out


def _r2_format(s: _In, out: _Out) -> None:
    for d in s.shown:
        if getattr(d, "override", None) or d.kind in _NOT_VALUES:
            continue
        ann = s.sheet_dims.get(d.id)
        try:
            t = ann.text if ann is not None else dim_text(s.fmt, d)
            problems = _format_problems(s, d, t)
        except (InvalidArgumentError, ValueError, ArithmeticError):
            problems = ["its value cannot be shown"]
        for why in dict.fromkeys(problems):
            out.add("R2.format", f"{s.named(d)}: {why}", d.id, ("Reset the Text", "Lay Out Again"))


def _band(s: _In, d: types.PlannedDimension) -> tuple[Fraction, Fraction, Fraction] | None:
    """(band, upper deviation, lower deviation) in the drawing's unit for a toleranced
    value, or None when nothing shown tolerances it this way."""
    if d.kind in ("angle", "leader_note") + _NOT_VALUES:
        return None
    if d.tolerance == "block":
        if s.process == "printed":
            return None
        pm = numbers.block_plus_minus(s.unit, d.places, s.settings.block(s.unit))
        return None if pm is None else (2 * pm, pm, -pm)
    if d.tolerance in ("symmetric", "deviations", "limits"):
        upper, lower = (Fraction(str(v)) for v in d.tolerance_values)
        if d.tolerance == "symmetric":
            return (2 * upper, upper, -upper) if upper > 0 else None
        return (upper - lower, upper, lower) if upper > lower else None
    return None


def _r2_rounding(s: _In, out: _Out) -> None:
    for d in s.shown:
        if getattr(d, "override", None):
            continue
        band = _band(s, d)
        if band is None or not 0 <= d.places <= numbers.MAX_PLACES:
            continue
        width, up, low = band
        try:
            share = numbers.rounding_share(d.value, s.unit, d.places, width)
            v = _dec(numbers.in_unit(d.value, s.unit))
            shown = numbers.rounded(v, d.places)
        except (InvalidArgumentError, ArithmeticError):
            continue
        if share <= numbers.ROUNDING_SHARE:
            continue
        exact = numbers.number(v, numbers.places_needed(v, numbers.MAX_PLACES), s.unit)
        inside = Fraction(str(shown)) + low <= Fraction(str(v)) <= Fraction(str(shown)) + up
        pct = float(share) * 100.0
        band_words = numbers.band_text(width / 2, s.unit) if d.tolerance == "block" else "explicit"
        out.add(
            "R2.rounding",
            f"{s.named(d)} rounds the model's {exact} by {pct:.0f} % of its {band_words} band; "
            f"the model value lies {'inside' if inside else 'outside'} the band",
            d.id,
            ("Keep", "Increase the Precision", "Give a Tolerance"),
            level="error" if share > _ROUNDING_ERROR else None,
        )


def _measured(s: _In, d: types.PlannedDimension) -> Decimal:
    if d.kind == "angle":
        return _dec(math.degrees(d.value))
    return _dec(numbers.in_unit(d.value, s.unit))


def _r2_override(s: _In, out: _Out) -> None:
    for d in s.shown:
        text = getattr(d, "override", None)
        if text is None:
            continue
        try:
            measured = _measured(s, d)
        except (InvalidArgumentError, ArithmeticError):
            continue
        body = _COUNT.sub("", text, count=1)
        m = _NUMBER.search(body)
        places = max(d.places, 0)
        if m is not None:
            token = m.group(0)
            places = _decimals(token) or 0
            try:
                same = numbers.rounded(measured, min(places, numbers.MAX_PLACES)) == Decimal(token)
            except (InvalidOperation, InvalidArgumentError):
                same = False
            if same:
                continue
        model = numbers.number(
            measured, min(max(places, d.places, 0), numbers.MAX_PLACES), "mm" if d.kind == "angle" else s.unit
        )
        what = f"reads '{text}'" if m is not None else f"reads '{text}', which states no number,"
        reason = s.accepted.get(d.id) or s.accepted.get("R2.override")
        message = f"{d.id} {what} where the model measures {model}"
        if reason:
            message += f"; accepted: {reason}"
        out.add(
            "R2.override",
            message,
            d.id,
            ("Reset the Value", "Accept with a Reason"),
            level="information" if reason else None,
        )


# --------------------------------------------------------------------------- R3: tolerances


def _max_row(s: _In) -> int:
    rows = s.settings.block(s.unit)
    return max((r.places for r in rows), default=0)


def _r3_tolerance(s: _In, out: _Out) -> None:
    lines = _tolerance_lines(s)
    has_block = any(isinstance(a, D.ToleranceBlock) for a in s.annotations)
    if s.sheet is not None and has_block:
        text = " ".join(lines).upper()
        if s.process == "printed":
            if "SEE NOTE" not in text:
                out.add(
                    "R3.tolerance",
                    "the tolerance block of a printed part does not point at its process note",
                    "tolerance",
                    ("Lay Out Again",),
                )
        else:
            if "TOLERANCES:" not in text:
                out.add(
                    "R3.tolerance",
                    "the tolerance block gives no decimal tolerances",
                    "tolerance",
                    ("Lay Out Again",),
                )
            if "ANGLES" not in text:
                out.add(
                    "R3.tolerance",
                    "the tolerance block gives no angle tolerance",
                    "tolerance",
                    ("Lay Out Again",),
                )
        if standards.INTERPRETATION_KEYS[standards.profile_of(s.settings)] not in text:
            out.add(
                "R3.tolerance",
                "the tolerance block does not name the standard the dimensions are interpreted by",
                "tolerance",
                ("Lay Out Again",),
            )
    top = _max_row(s)
    rows = {r.places for r in s.settings.block(s.unit)}
    for d in s.shown:
        if d.kind in _NOT_VALUES:
            continue
        if d.tolerance not in _TOLERANCE_KINDS:
            out.add(
                "R3.tolerance",
                f"{s.named(d)} has no source of tolerance ({d.tolerance})",
                d.id,
                ("Set Tolerance",),
            )
            continue
        if d.tolerance == "block" and s.process in types.MACHINING and d.kind != "angle":
            if d.places not in rows and d.places <= top:
                out.add(
                    "R3.tolerance",
                    f"{s.named(d)} shows {_plural(d.places, 'place')}, "
                    "a precision the tolerance block has no row for",
                    d.id,
                    ("Set Precision", "Set Tolerance"),
                )


def _r3_block(s: _In, out: _Out) -> None:
    if s.process not in types.MACHINING:
        return
    top = _max_row(s)
    for d in s.shown:
        if d.tolerance != "block" or d.kind in ("angle",) + _NOT_VALUES:
            continue
        if d.places > top:
            out.add(
                "R3.block",
                f"{s.named(d)} shows {_plural(d.places, 'place')}, more than the tolerance block's last row "
                f"({top}), and has no tolerance of its own",
                d.id,
                ("Set Tolerance", "Set Precision"),
            )


def _profile_note(s: _In) -> bool:
    for _i, n in s.notes:
        if n.text.upper().startswith(PROFILE_WORDS) and any(
            f.characteristic == "profile_surface" for f in n.frames
        ):
            return True
    return False


def _r3_basic(s: _In, out: _Out) -> None:
    basics = [d for d in s.shown if d.tolerance == "basic"]
    if not basics or _profile_note(s):
        return
    framed: set[str] = set()
    for d in s.shown:
        if d.frame is not None:
            framed.update(d.features)
    for d in basics:
        if d.frame is not None or framed.intersection(d.features):
            continue
        out.add(
            "R3.basic",
            f"{s.named(d)} is basic, but no frame and no general profile note governs it",
            d.id,
            ("Add the Profile Note", "Set Frame"),
        )


def _checked_signed(s: _In) -> bool:
    return s.drawing.status in ("CHECKED", "RELEASED") or any(
        g.row == "CHECKED" for g in s.drawing.signatures
    )


def _r3_roles(s: _In, out: _Out) -> None:
    if _checked_signed(s) or s.process not in types.MACHINING:
        return
    counts: dict[str, int] = {}
    for d in s.shown:
        if d.places_source != "role" or d.tolerance != "block" or d.kind in ("angle",) + _NOT_VALUES:
            continue
        pm = numbers.block_plus_minus(s.unit, d.places, s.settings.block(s.unit))
        if pm is None:
            continue
        b = numbers.band_text(pm, s.unit)
        counts[b] = counts.get(b, 0) + 1
    if not counts:
        return
    total = sum(counts.values())
    summary = ", ".join(f"{n} at {b}" for b, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    out.add(
        "R3.roles",
        f"{_plural(total, 'dimension')} {'takes its' if total == 1 else 'take their'} precision from "
        f"{'its' if total == 1 else 'their'} role ({summary}); "
        "review them before CHECKED is signed",
        "R3.roles",
        ("Set Precision",),
    )


# --------------------------------------------------------------------------- R4: complete and not redundant


def _edges(s: _In) -> dict[str, list[tuple[int, int, str]]]:
    """The drawn locations by frame axis, as (position, position, drawing id) in the
    drawing's order: the plan's edges for its dimensions, and a user's location
    matched to the graph's positions by value."""
    out: dict[str, list[tuple[int, int, str]]] = {ax: [] for ax in s.detail.graphs}
    tol = max(s.ctx.tol, 1e-9)
    for d in s.shown:
        if d.tolerance == "reference" or d.kind not in ("linear", "ordinate"):
            continue
        p = s.plan_dims.get(d.id)
        edge = s.detail.edges.get(p.id) if p is not None else None
        if edge is not None:
            ax, pa, pb = edge
            if ax in out:
                out[ax].append((pa, pb, d.id))
            continue
        if d.role != "feature_location" or d.axis not in out or len(d.positions) != 2:
            continue
        g = s.detail.graphs[d.axis]
        ends = []
        for want in d.positions:
            hit = None
            for pid in sorted(g.pos):
                q = g.pos[pid]
                if abs(q.value - want.value) <= tol and (q.kind != "face") == want.centre:
                    hit = pid
                    break
            ends.append(hit)
        if None not in ends:
            out[d.axis].append((ends[0], ends[1], d.id))
    return out


def _walk(g, edges: list[tuple[int, int, str]]):
    """Union-find over the drawn edges: the nodes not joined to the origin, and each
    loop as (the dimension that closes it, the dimensions it closes it with)."""
    parent = {n: n for n in g.members}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    adjacent: dict[int, list[tuple[int, str]]] = {n: [] for n in g.members}
    loops: list[tuple[str, tuple[str, ...], int]] = []
    for pa, pb, did in edges:
        if pa not in g.node_of or pb not in g.node_of:
            continue
        u, v = g.node_of[pa], g.node_of[pb]
        if find(u) == find(v):
            loops.append((did, tuple(_tree_path(adjacent, u, v)), u))
            continue
        parent[max(find(u), find(v))] = min(find(u), find(v))
        adjacent[u].append((v, did))
        adjacent[v].append((u, did))
    origin = find(g.origin)
    unreached = [n for n in g.nodes if find(n) != origin]
    return unreached, loops


def _tree_path(adjacent, u: int, v: int) -> list[str]:
    back: dict[int, tuple[int, str] | None] = {u: None}
    queue = [u]
    for x in queue:
        if x == v:
            break
        for y, did in adjacent[x]:
            if y not in back:
                back[y] = (x, did)
                queue.append(y)
    out: list[str] = []
    x = v
    while back.get(x) is not None:
        x, did = back[x]
        out.append(did)
    return out[::-1]


def _removed_serving(s: _In, keys: Iterable[str]) -> bool:
    keys = set(keys)
    return any(d.state == "removed" and keys.intersection(d.serves) for d in s.drawing.dimensions)


def _node_words(s: _In, g, node: int) -> tuple[str, str]:
    """(words, item) for a graph node: a pattern by itself, else its features."""
    feats = g.features(node)
    patterns = [f for f in feats if isinstance(_feature(s, f), types.Pattern)]
    if patterns:
        return s.feature_words(patterns[:1]), patterns[0]
    if feats:
        return s.feature_words(feats), feats[0]
    key = g.keys(node)[0]
    return g.label(node), key


def _feature(s: _In, fid: str):
    k = s.ctx.index_of.get(fid) if s.ctx is not None else None
    return s.ctx.features.features[k] if k is not None else None


def _r4_graphs(s: _In, out: _Out) -> None:
    edges = _edges(s)
    texts = {d.id: s.text_of(d) for d in s.shown}
    for ax, g in sorted(s.detail.graphs.items()):
        unreached, loops = _walk(g, edges.get(ax, []))
        for node in unreached:
            words, item = _node_words(s, g, node)
            keys = g.keys(node)
            out.add(
                "R4.complete",
                f"{words} {s.verb(words)} not located along {ax.upper()}",
                item,
                ("Restore", "Add") if _removed_serving(s, keys) else ("Add",),
            )
        for did, path, node in loops:
            if path:
                others = " and ".join(texts.get(x, x) for x in path)
                message = f"{did} ({texts.get(did, did)}) closes a loop with {others}"
            else:
                sizes = [
                    texts[d.id]
                    for d in s.shown
                    if any(lk.key in d.serves for lk in g.links if g.node_of.get(lk.a) == node)
                ]
                what = " and ".join(sizes) if sizes else "a size"
                message = f"{did} ({texts.get(did, did)}) joins two positions that {what} already joins"
            out.add("R4.redundant", message, did, ("Make Reference", "Remove the Other", "Link Instead"))


def _need_words(s: _In, key: str, words: str) -> str:
    role = key.split("/")[0]
    if role == "callout":
        return f"{words} {'have' if s.verb(words) == 'are' else 'has'} no callout"
    if role == "angle":
        if words.endswith(" holes"):
            return f"the angle of the first of {words} on their pitch circle is not stated"
        return f"the angle of {words} is not stated"
    if role == "pcd":
        return f"the pitch circle of {words} is not stated"
    if role == "step":
        return f"the angle between {words} on their pitch circle is not stated"
    if role == "pitch":
        ax = key.split("/")[-1].upper()
        return f"the pitch of {words} along {ax} is not stated"
    if role == "size" and " along " in words:  # a width names its own size
        return f"{words} {s.verb(words)} not stated"
    name = {
        "size": "the size",
        "depth": "the depth",
        "radius": "the radius",
        "chamfer": "the chamfer",
        "inner": "the inner diameter",
        "outer": "the outer diameter",
        "length": "the length",
    }.get(role, "a size")
    return f"{name} of {words} is not stated"


def _r4_sizes(s: _In, out: _Out) -> None:
    """Every size present, once (10.2: keyed on requirement keys, never on values)."""
    stating: dict[str, list[types.PlannedDimension]] = {}
    for d in s.shown:
        if d.tolerance == "reference":
            continue
        for key in d.serves:
            stating.setdefault(key, []).append(d)
    for need in s.detail.req.needs:
        key = need.req.key
        found = stating.get(key, [])
        if len(found) > 1:
            first, *rest = found
            for d in rest:
                out.add(
                    "R4.redundant",
                    f"{s.named(d)} states what {s.named(first)} already states",
                    d.id,
                    ("Remove the Other", "Make Reference"),
                )
        if found:
            continue
        role = key.split("/")[0]
        if role in ("pitch", "pcd", "step"):
            continue  # R4.members says it
        words = s.feature_words(need.req.features)
        out.add(
            "R4.complete",
            _need_words(s, key, words),
            need.req.features[0] if need.req.features else key,
            ("Restore", "Add") if _removed_serving(s, (key,)) else ("Add",),
        )


def _r4_members(s: _In, out: _Out) -> None:
    needs = {n.req.key: n for n in s.detail.req.needs}
    stating: dict[str, list[types.PlannedDimension]] = {}
    for d in s.shown:
        for key in d.serves:
            stating.setdefault(key, []).append(d)
    for k, p in s.ctx.features.of_type(types.Pattern):
        fid = s.ctx.ids[k]
        words = s.feature_words([fid])
        n = len(p.members)
        for d in stating.get(types.requirement_key("callout", [fid]), ()):
            said = _count_of(d.prefix)
            if (said or 1) != n:
                out.add(
                    "R4.members",
                    f"the callout {s.named(d)} says {said or 1}X but the pattern has {n} holes",
                    d.id,
                    ("Set Prefix",),
                )
        for key, need in needs.items():
            role = key.split("/")[0]
            if role not in ("pitch", "pcd", "step") or fid not in need.req.features:
                continue
            found = stating.get(key, [])
            if not found:
                what = {
                    "pitch": f"the pitch along {key.split('/')[-1].upper()}",
                    "pcd": "the pitch circle",
                    "step": "the angle between them",
                }[role]
                out.add(
                    "R4.members",
                    f"the members of {words} are not located: {what} is not stated",
                    fid,
                    ("Restore", "Add") if _removed_serving(s, (key,)) else ("Add",),
                )
            for d in found:
                said = _count_of(d.prefix)
                if role == "pitch" and need.count > 1 and said != need.count:
                    out.add(
                        "R4.members",
                        f"{s.named(d)} gives {said or 1}X where {words} have {need.count} spaces along "
                        f"{key.split('/')[-1].upper()}",
                        d.id,
                        ("Set Prefix",),
                    )
                if role == "step" and need.count > 1 and said != need.count:
                    out.add(
                        "R4.members",
                        f"{s.named(d)} gives {said or 1}X where {words} have {need.count} spaces "
                        "round their pitch circle",
                        d.id,
                        ("Set Prefix",),
                    )


def _merged_spans(geom, name: str, at: float, tol: float) -> int:
    spans = sorted((w.low, w.high) for w in geom.witnesses if w.axis == name and abs(w.position - at) <= tol)
    count = 0
    end = -math.inf
    for lo, hi in spans:
        if lo > end + tol:
            count += 1
            end = hi
        else:
            end = max(end, hi)
    return count


def _r4_coincident(s: _In, out: _Out) -> None:
    tol = max(s.ctx.tol, 1e-7)
    for d in s.shown:
        if d.kind not in ("linear", "ordinate"):
            continue
        p = s.plan_dims.get(d.id)
        found = s.graph_view(d.view)
        pos = s.detail.positions.get(p.id) if p is not None else None
        if pos is None or found is None or _count_of(d.prefix):
            continue
        spec, geom = found
        for q in pos:
            if q.kind != "face" or len(q.faces) < 2:
                continue
            sa = s.ctx.sheet_axis(spec, q.axis)
            if sa is None:
                continue
            n = _merged_spans(geom, sa[0], sa[1] * q.value, tol)
            if n > 1:
                where = numbers.number(
                    numbers.in_unit(q.value, s.unit), s.settings.precision(s.unit, "step"), s.unit
                )
                out.add(
                    "R4.coincident",
                    f"{s.named(d)} meets {n} separate surfaces at {q.axis.upper()} {where} in {d.view} "
                    f"with one extension line; give it a count ({n}X) or an extension line to each",
                    d.id,
                    ("Set Prefix", "Add"),
                )


# --------------------------------------------------------------------------- R5: visible, true shape


def _hole_of(s: _In, d: types.PlannedDimension) -> types.Hole | None:
    for fid in d.features:
        f = _feature(s, fid)
        if isinstance(f, types.Pattern) and f.members:
            first = s.ctx.features.features[f.members[0]]
            return first if isinstance(first, types.Hole) else None
        if isinstance(f, types.Hole):
            return f
    return None


def _seen_open(h: types.Hole, view_dir) -> bool:
    d = h.axis.direction
    seen = [(-d[0], -d[1], -d[2]), d] if h.through else [(-d[0], -d[1], -d[2])]
    return any(_dot(v, view_dir) > 0.5 for v in seen)


def _pos_words(s: _In, q) -> str:
    if q.features:
        return s.feature_words(q.features)
    v = numbers.number(numbers.in_unit(q.value, s.unit), s.settings.precision(s.unit, "step"), s.unit)
    return f"the face at {q.axis.upper()} {v}"


def _r5(s: _In, out: _Out) -> None:
    ctx = s.ctx
    for d in s.shown:
        p = s.plan_dims.get(d.id)
        found = s.graph_view(d.view)
        if p is None or found is None:
            continue
        spec, geom = found
        _r, _u, vd = spec.frame()
        if d.kind in ("linear", "ordinate", "datum_feature"):
            if d.axis is not None and ctx.sheet_axis(spec, d.axis) is None:
                out.add(
                    "R5.true_shape",
                    f"{s.named(d)} runs along {d.axis.upper()}, which {d.view} shows foreshortened",
                    d.id,
                    ("Move to Another View",),
                )
                continue
            for q in s.detail.positions.get(p.id, ()):
                if witness_in(ctx, spec, geom, q) is None:
                    out.add(
                        "R5.visible",
                        f"{s.named(d)} attaches to {_pos_words(s, q)}, "
                        f"which {d.view} shows no visible line for",
                        d.id,
                        ("Move to Another View",),
                    )
                    break
            continue
        need = s.detail.needs.get(p.id)
        hole = _hole_of(s, d) if d.kind in ("hole_callout", "diameter", "radius") else None
        if hole is not None and d.kind in ("hole_callout", "diameter"):
            if not ctx.looks_along(spec, hole.axis.direction):
                out.add(
                    "R5.true_shape",
                    f"{s.named(d)} sizes a hole in {d.view}, which does not show it as a circle",
                    d.id,
                    ("Move to Another View",),
                )
            elif not _seen_open(hole, vd):
                out.add(
                    "R5.visible",
                    f"{s.named(d)} is in {d.view}, which sees the hole's closed end",
                    d.id,
                    ("Move to Another View",),
                )
        elif need is not None and d.kind in ("radius", "angle") and need.facing is not None:
            if not ctx.looks_along(spec, need.facing):
                out.add(
                    "R5.true_shape",
                    f"{s.named(d)} is in {d.view}, which does not show its arc in true shape",
                    d.id,
                    ("Move to Another View",),
                )
        elif need is not None and d.kind == "chamfer" and need.edge_on is not None:
            if not ctx.looks_along(spec, need.edge_on):
                out.add(
                    "R5.true_shape",
                    f"{s.named(d)} is in {d.view}, which does not show the chamfer as a line at its angle",
                    d.id,
                    ("Move to Another View",),
                )
        # Ø above 180 degrees of cover, R at or below
        for fid in d.features[:1]:
            f = _feature(s, fid)
            cover = None
            if isinstance(f, types.Hole):
                cover = f.cover
            elif isinstance(f, types.Blend):
                cover = math.pi
            if cover is None:
                continue
            deg = math.degrees(cover)
            if d.kind in ("diameter", "hole_callout") and cover <= math.pi + 1e-6:
                out.add(
                    "R5.true_shape",
                    f"{s.named(d)} gives Ø to an arc of {deg:.0f} degrees; "
                    "arcs of 180 degrees or less take R",
                    d.id,
                    ("Set Prefix",),
                )
            elif d.kind == "radius" and cover > math.pi + 1e-6:
                out.add(
                    "R5.true_shape",
                    f"{s.named(d)} gives R to a hole of {deg:.0f} degrees; more than 180 degrees takes Ø",
                    d.id,
                    ("Set Prefix",),
                )


# --------------------------------------------------------------------------- R6: title, material, signatures


_TITLE_LABELS = {
    "title": "TITLE",
    "number": "DWG NO",
    "part_number": "PART NO",
    "revision": "REV",
    "size": "SIZE",
    "scale": "SCALE",
    "sheet": "SHEET",
    "status": "STATUS",
    "model": "MODEL",
    "material": "MATERIAL",
    "finish": "FINISH",
}


def _title_text(s: _In, key: str) -> str:
    if s.title_block is not None and key in s.fields:
        return str(s.fields.get(key) or "").strip()
    for k, f in s.drawing.title:
        if k == key:
            return f.text.strip()
    return ""


def _r6_title(s: _In, out: _Out) -> None:
    if not s.settings.company.name.strip():
        out.add(
            "R6.title",
            "the title block names no company; Drawing Settings hold none",
            "company",
            ("Drawing Settings",),
        )
    keys = ["title", "number", "part_number", "revision", "model"]
    if not s.assembly:  # an assembly's materials and finishes are its parts'
        keys += ["material", "finish"]
    if s.sheet is not None:
        if s.title_block is None:
            out.add("R6.title", "the sheet has no title block", "title", ("Lay Out Again",))
            return
        keys += ["size", "scale", "sheet", "status"]
        if not any(isinstance(a, D.ToleranceBlock) for a in s.annotations):
            out.add("R6.title", "the title block has no tolerance block", "tolerance", ("Lay Out Again",))
    for key in keys:
        if not _title_text(s, key):
            out.add(
                "R6.title",
                f"the title block's {_TITLE_LABELS[key]} is empty",
                key,
                ("Edit the Title Block",)
                if key not in ("size", "scale", "sheet", "status")
                else ("Lay Out Again",),
            )
    if s.sheet is not None:
        status = _title_text(s, "status")
        if status and status != s.drawing.status:
            out.add(
                "R6.title",
                f"the title block says {status} but the drawing is {s.drawing.status}",
                "status",
                ("Lay Out Again",),
            )
        size = _title_text(s, "size")
        if size and size != s.sheet.name:
            out.add(
                "R6.title",
                f"the title block says SIZE {size} on a {s.sheet.name} sheet",
                "size",
                ("Lay Out Again",),
            )
    rev = s.drawing.revisions[-1].rev if s.drawing.revisions else None
    shown_rev = _title_text(s, "revision")
    if rev and shown_rev and shown_rev != rev:
        out.add(
            "R6.title",
            f"the title block says REV {shown_rev} but the drawing's revision is {rev}",
            "revision",
            ("Edit the Title Block",),
        )
    sha = (s.drawing.model or {}).get("sha256")
    model = _title_text(s, "model")
    if isinstance(sha, str) and len(sha) >= 16 and model and sha[:16].upper() not in model.upper():
        out.add(
            "R6.title",
            "the MODEL field does not carry the first 16 hex digits of the model file's SHA-256",
            "model",
            ("Lay Out Again",),
        )
    elif (
        isinstance(sha, str)
        and len(sha) >= 16
        and model
        and s.title_block is not None
        and not any(sha[:16].upper() in run.text.upper() for run in s.texts(("title",)))
    ):
        out.add(
            "R6.title",
            "the title block's MODEL cell is cut before the model's short hash",
            "model",
            ("Lay Out Again",),
        )
    drawn = next((g for g in s.drawing.signatures if g.row == "DRAWN"), None)
    if drawn is None or not drawn.name.strip() or not drawn.date:
        out.add("R6.title", "nobody is named as DRAWN, with the date", "DRAWN", ("Sign...",))


def _material_entry(s: _In, text: str) -> dict | None:
    entry = s.settings.material(text)
    if entry is not None:
        return entry
    return next((e for e in s.settings.materials.entries if e["callout"].upper() == text.upper()), None)


def _r6_material(s: _In, out: _Out) -> None:
    level = "error" if s.release else "warning"
    text = _title_text(s, "material")
    if not text:
        return  # R6.title says the field is empty
    entry = _material_entry(s, text)
    if entry is None:
        if "material" not in s.accepted:
            # Release refuses an unmapped material itself until it is mapped or accepted as
            # typed (13.2); as an error here it could not be accepted at all.
            out.add(
                "R6.material",
                f"the material {text} is not in the materials list; map it, or accept it as typed at release",
                "material",
                ("Map the Material", "Accept as Typed"),
                level="warning",
            )
        return
    if not str(entry.get("specification") or "").strip():
        out.add(
            "R6.material",
            f"the materials list gives {entry['callout']} no specification",
            "material",
            ("Drawing Settings",),
            level="warning",
        )
    if entry.get("heat_treatable"):
        said = _title_text(s, "heat_treatment") or any("HEAT TREAT" in n.text.upper() for _i, n in s.notes)
        if not said:
            out.add(
                "R6.material",
                f"{entry['callout']} can be heat treated; the drawing does not say whether it is",
                "material",
                ("Edit Notes",),
                level=level,
            )


def _r6_signatures(s: _In, out: _Out) -> None:
    settings = s.settings
    by_row = {g.row: g for g in s.drawing.signatures}
    digest = None
    for row in settings.people.required:
        g = by_row.get(row)
        if g is None:
            out.add(
                "R6.signatures",
                f"{row} is not signed",
                row,
                ("Sign...",),
                level="error" if s.release else "information",
            )
            continue
        if digest is None:
            from .release import content_digest

            # the sheet is not covered by a signature, and leaving it out saves encoding it
            digest = content_digest(replace(s.drawing, sheet=None))
        if g.digest != digest:
            out.add(
                "R6.signatures",
                f"the {row} signature of {g.name} is older than the drawing's last change",
                row,
                ("Sign Again",),
                level="error" if s.release else "warning",
            )
    seen: dict[str, str] = {}
    for g in s.drawing.signatures:
        key = " ".join(g.name.split()).casefold()
        if key in seen:
            out.add(
                "R6.signatures",
                f"{g.name} signed both {seen[key]} and {g.row}",
                g.row,
                ("Sign...",),
                level="warning" if settings.people.same_person_twice else "error",
            )
        else:
            seen[key] = g.row


# --------------------------------------------------------------------------- R7: callouts


def _rank(line: str, threads: set[str]) -> int | None:
    t = line.strip().upper()
    if t.startswith(("⌴", "CBORE", "SPOTFACE", standards.SYMBOL_DIAMETER)):
        return 1
    if t.startswith(("⌵", "CSK")):
        return 2
    if _THREAD.match(line.strip()) or any(line.strip().startswith(x) for x in threads if x):
        return 3
    if t.endswith("AT ENTRY"):
        return 4
    if t == "INTO BORE":
        return 5
    return None


_RANK_WORDS = {1: "counterbore", 2: "countersink", 3: "thread", 4: "entry", 5: "into-bore"}


def _through(s: _In, d: types.PlannedDimension) -> bool | None:
    if s.ctx is not None:
        h = _hole_of(s, d)
        if h is not None:
            return h.through
    for fid in d.features:
        rec = s.records.get(fid)
        if rec is not None and rec.descriptor.type.lower() == "hole":
            v = dict(rec.descriptor.size).get("through")
            if isinstance(v, bool):
                return v
    return None


def _r7_callouts(s: _In, out: _Out) -> None:
    fixes = ("Reset the Text", "Lay Out Again")
    for d in s.shown:
        if d.kind != "hole_callout":
            continue
        name = s.named(d)
        if not re.fullmatch(r"(?:[1-9][0-9]*X )?" + standards.SYMBOL_DIAMETER, d.prefix or ""):
            out.add(
                "R7.callouts",
                f"{name} starts '{d.prefix}'; a hole callout starts with the count and Ø",
                d.id,
                fixes,
            )
        lines = [str(x) for x in d.suffix]
        first = lines[0].strip() if lines else ""
        depth = re.match(r"^(?:" + standards.SYMBOL_DEPTH + r"|DEEP)\s*\S", first)
        if first != "THRU" and not depth:
            out.add("R7.callouts", f"{name} says neither THRU nor a depth after its diameter", d.id, fixes)
        through = _through(s, d)
        if first == "THRU" and through is False:
            out.add("R7.callouts", f"{name} says THRU, but the hole does not go through", d.id, fixes)
        if depth and through is True:
            out.add("R7.callouts", f"{name} gives a depth, but the hole goes through", d.id, fixes)
        threads = {str(s.decisions.get(f, {}).get("thread") or "") for f in d.features}
        threads.discard("")
        last = 0
        for line in lines[1:]:
            r = _rank(line, threads)
            if r is None:
                continue
            if r < last:
                out.add(
                    "R7.callouts",
                    f"{name} puts its {_RANK_WORDS[r]} line after its {_RANK_WORDS[last]} line; a callout "
                    "lists the hole in the order it is made",
                    d.id,
                    fixes,
                )
            last = max(last, r)
        for line in lines:
            if _TYP.search(line):
                out.add(
                    "R7.callouts", f"{name} says TYP; repetition is stated with nX", d.id, ("Set Prefix",)
                )
        for line in lines[1:]:
            text = line.strip()
            if _THREAD.match(text) and not any(text.startswith(t) for t in threads):
                out.add(
                    "R7.callouts",
                    f"{name} names the thread '{text}', but no thread is confirmed for this hole",
                    d.id,
                    ("Confirm the Thread", "Reset the Text"),
                )
        for t in sorted(threads):
            if not any(line.strip().startswith(t) for line in lines):
                out.add(
                    "R7.callouts",
                    f"the thread {t} confirmed for this hole is missing from {name}",
                    d.id,
                    ("Lay Out Again",),
                )
        if s.ctx is not None:
            h = _hole_of(s, d)
            if h is not None and "into_bore" in h.ends:
                confirmed = any(k in s.decisions.get(f, {}) for f in d.features for k in END_DECISIONS)
                if not confirmed:
                    out.add(
                        "R7.callouts",
                        f"{name}: the hole runs into a bore, and its end is not confirmed",
                        d.id,
                        ("Confirm the End",),
                    )


# --------------------------------------------------------------------------- R8: the sheet


def _r8_sheet(s: _In, out: _Out) -> None:
    sheet = s.sheet
    if sheet is None:
        out.add("R8.sheet", "the drawing has no laid-out sheet", "sheet", ("Lay Out Again",))
        return
    std = standards.SHEETS.get(sheet.name)
    if std is None:
        out.add("R8.sheet", f"{sheet.name} is not one of the sheet sizes A to E", "sheet", ("Set Sheet",))
        return
    orientation = s.settings.sheets.orientation
    w, h = std.size(orientation)
    if abs(sheet.width - w) > _SLACK or abs(sheet.height - h) > _SLACK:
        out.add(
            "R8.sheet",
            f"the {sheet.name} sheet measures {sheet.width:.1f} x {sheet.height:.1f} mm; "
            f"{orientation} {sheet.name} is {w:.1f} x {h:.1f} mm",
            "sheet",
            ("Set Sheet",),
        )
    border = next((a for a in s.annotations if isinstance(a, D.Border)), None)
    if border is None:
        out.add("R8.sheet", "the sheet has no border", "border", ("Lay Out Again",))
        return
    if abs(border.margin - std.margin) > _SLACK:
        out.add(
            "R8.sheet",
            f"the border stands {border.margin:.1f} mm from the edge; a {sheet.name} sheet's margin is "
            f"{std.margin:.1f} mm",
            "border",
            ("Lay Out Again",),
        )
    zones = (std.columns, std.rows) if orientation == "landscape" else (std.rows, std.columns)
    if not s.settings.sheets.zones:
        zones = (0, 0)
    if (border.columns, border.rows) != zones:
        out.add(
            "R8.sheet",
            f"the border has {border.columns} by {border.rows} zones; a {sheet.name} sheet has "
            f"{zones[0]} by {zones[1]}",
            "border",
            ("Lay Out Again",),
        )
    right, top = sheet.width - std.margin, sheet.height - std.margin
    tb = s.title_block
    if tb is not None and (abs(tb.at[0] + tb.width - right) > _SLACK or abs(tb.at[1] - std.margin) > _SLACK):
        out.add("R8.sheet", "the title block is not in the lower right corner", "title", ("Lay Out Again",))
    rev = [_box_of_path(p.path) for p in sheet.painted if isinstance(p, D.Stroke) and p.owner == "revisions"]
    rev = [b for b in rev if b is not None]
    if not rev:
        out.add("R8.sheet", "the sheet has no revision block", "revisions", ("Lay Out Again",))
    else:
        x1, y1 = max(b[2] for b in rev), max(b[3] for b in rev)
        if abs(x1 - right) > _SLACK or abs(y1 - top) > _SLACK:
            out.add(
                "R8.sheet",
                "the revision block is not in the upper right corner",
                "revisions",
                ("Lay Out Again",),
            )
    _r8_numbered(s, out)
    if s.layout is not None:
        return  # the layout's own checks say what lies outside the border or in a block
    edge = Box(std.margin, std.margin, right, top).grow(0.01)
    blocks = []
    if tb is not None:
        blocks.append(Box(tb.at[0], tb.at[1], tb.at[0] + tb.width, tb.at[1] + tb.height))
    if rev:
        blocks.append(Box(min(b[0] for b in rev), min(b[1] for b in rev), x1, y1))
    told: set[tuple[str, str]] = set()
    for run in s.texts(_LETTERED):
        b = _text_box(run)
        owner = run.owner
        if not b.inside(edge) and owner not in ("stamp", "plot", "border"):
            if (owner, "outside") not in told:
                told.add((owner, "outside"))
                out.add("R8.sheet", f"'{run.text}' lies outside the border", owner or "sheet", ("Move",))
        elif not _furniture(owner) and any(b.hits(r) for r in blocks):
            if (owner, "block") not in told:
                told.add((owner, "block"))
                out.add(
                    "R8.sheet",
                    f"'{run.text}' lies in the title or revision block",
                    owner or "sheet",
                    ("Move",),
                )


def _r8_numbered(s: _In, out: _Out) -> None:
    """Every sheet of the drawing the first's size, with a title block saying which of
    how many it is (SHEET n OF m) and, after the first, naming the first's drawing
    number and revision."""
    sheets = D.sheets_of(s.sheet)
    m = len(sheets)
    first = dict(s.title_block.fields) if s.title_block is not None else {}
    for n, sheet in enumerate(sheets, 1):
        if n > 1 and (sheet.name, sheet.width, sheet.height) != (s.sheet.name, s.sheet.width, s.sheet.height):
            out.add("R8.sheet", f"sheet {n} is not the size of the first", "sheet", ("Lay Out Again",))
        tb = next((a for a in sheet.annotations if isinstance(a, D.TitleBlock)), None)
        if tb is None:
            if n > 1:
                out.add("R8.sheet", f"sheet {n} has no title block", "title", ("Lay Out Again",))
            continue
        fields = dict(tb.fields)
        for key, words in (("number", "drawing number"), ("revision", "revision")):
            if n > 1 and key in first and fields.get(key) != first[key]:
                out.add(
                    "R8.sheet",
                    f"sheet {n}'s title block gives the {words} {fields.get(key) or 'as empty'}; "
                    f"the first sheet's gives {first[key] or 'none'}",
                    "title",
                    ("Lay Out Again",),
                )
        said = " ".join(str(fields.get("sheet") or "").upper().split())
        if said and said != f"{n} OF {m}":
            out.add(
                "R8.sheet",
                f"sheet {n}'s title block says SHEET {said}; the drawing has {m} sheet{'s' if m > 1 else ''}",
                "title",
                ("Lay Out Again",),
            )


def _union(a, b) -> tuple[float, float, float, float]:
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def _box_of_path(path) -> tuple[float, float, float, float] | None:
    xs, ys = [], []
    for op in path:
        if op[0] in ("M", "L"):
            xs.append(op[1])
            ys.append(op[2])
        elif op[0] == "C":
            xs += [op[1], op[3], op[5]]
            ys += [op[2], op[4], op[6]]
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


# --------------------------------------------------------------------------- R9: lines


def _r9_lines(s: _In, out: _Out) -> None:
    if s.sheet is None:
        return
    lines = standards.LINES
    thick, thin = lines["visible"].width, lines["thin"].width
    if not 1.8 <= thick / thin <= 2.2 or thick < 0.6 - 1e-9 or thin < 0.3 - 1e-9:
        out.add("R9.lines", f"the line widths {thick} and {thin} mm are not thick and thin at 2:1", "lines")
    # The painter strokes the geometry first, one stroke an item in order (layout/patterns.py),
    # so each stroke is held to its item's style; the annotation strokes after it are thin.
    painted = s.sheet.painted
    wrong: dict[str, set[float]] = {}
    solid: dict[str, int] = {}
    dashed: dict[str, int] = {}
    paired = 0
    for k, g in enumerate(s.sheet.geometry):
        p = painted[k] if k < len(painted) else None
        if not isinstance(p, D.Stroke) or p.owner != g.src.view:
            break
        paired = k + 1
        style = lines.get(g.style, lines["thin"])
        if abs(p.width - style.width) > 0.005:
            wrong.setdefault(g.style, set()).add(round(p.width, 3))
        if not style.dash and p.dash:
            dashed[g.style] = dashed.get(g.style, 0) + 1
        elif (
            style.dash and not p.dash and (closed(g) or length_of(g) >= plain_sum(style.dash) + style.dash[0])
        ):
            solid[g.style] = solid.get(g.style, 0) + 1
    for p in painted[paired:]:
        if isinstance(p, D.Stroke) and p.layer in ("dimensions", "centre") and abs(p.width - thin) > 0.005:
            wrong.setdefault(p.layer, set()).add(round(p.width, 3))
    for style, found in sorted(wrong.items()):
        want = lines.get(style, lines["thin"]).width
        out.add(
            "R9.lines",
            f"{style} lines are drawn {', '.join(f'{w:.2f}' for w in sorted(found))} mm wide; "
            f"they are {'thick' if want == thick else 'thin'}, {want:.2f} mm",
            style,
            ("Lay Out Again",),
        )
    for style, n in sorted(dashed.items()):
        out.add("R9.lines", f"{_plural(n, f'{style} line')} drawn dashed; they are solid", style)
    for style, n in sorted(solid.items()):
        out.add("R9.lines", f"{_plural(n, f'{style} line')} drawn solid; they are dashed", style)
    marks: dict[str, list[tuple[float, float]]] = {}
    for a in s.annotations:
        if isinstance(a, D.CentreMark):
            marks.setdefault(a.view, []).append(a.centre)
    every = [c for cs in marks.values() for c in cs]
    missing: dict[str, int] = {}
    for g in s.sheet.geometry:
        if not isinstance(g, D.Arc) or g.style not in ("visible", "hidden") or g.sweep() < 360.0 - 1e-6:
            continue
        view = g.src.view
        near = marks.get(view, []) if view else every
        if not any(math.dist(c, g.centre) <= 0.05 for c in near):
            missing[view or "sheet"] = missing.get(view or "sheet", 0) + 1
    for view, n in sorted(missing.items()):
        out.add(
            "R9.lines",
            f"{_plural(n, 'circle')} in {view} {'has' if n == 1 else 'have'} no centre mark",
            view,
            ("Add Centre Marks",),
        )


# --------------------------------------------------------------------------- R10: text


def _text_group(owner: str) -> str:
    if owner == "notes" or owner.startswith("n-"):
        return "notes"
    if owner.endswith("-frame"):
        return owner[: -len("-frame")]
    return owner or "sheet"


def _r10_text(s: _In, out: _Out) -> None:
    if s.sheet is None:
        return
    least = standards.TEXT[s.unit].dimension
    low: dict[str, float] = {}
    lower: dict[str, str] = {}
    squeezed: dict[str, str] = {}
    labels: dict[str, float] = {}
    for run in s.texts(_LETTERED):
        h = run.size * fonts.CAP_HEIGHT
        group = _text_group(run.owner)
        if run.owner.endswith("-label"):
            labels[run.owner] = min(labels.get(run.owner, math.inf), h)
        elif run.text not in GLYPH_LETTERS and h < least - _SLACK:
            low[group] = min(low.get(group, math.inf), h)
        plain = run.text
        for w in _UNIT_WORDS:
            plain = plain.replace(w, "")
        if any(c.islower() for c in plain) and group not in lower:
            lower[group] = run.text
        if run.width > 0:
            want = fonts.measure(run.text, run.size, run.bold)
            if abs(run.width - want) > max(0.02, 0.01 * want) and group not in squeezed:
                squeezed[group] = run.text
    for group, h in sorted(low.items()):
        what = "the notes are" if group == "notes" else f"{group} is"
        out.add(
            "R10.text",
            f"{what} lettered {h:.1f} mm high, below the {least:.1f} mm minimum",
            group,
            ("Lay Out Again",),
        )
    for owner, h in sorted(labels.items()):
        if h <= least + _SLACK:
            out.add(
                "R10.text",
                f"the label of {owner[: -len('-label')]} is lettered {h:.1f} mm high; a view's label must be "
                f"larger than the {least:.1f} mm lettering",
                owner,
                ("Lay Out Again",),
            )
    for group, text in sorted(lower.items()):
        out.add("R10.text", f"'{text}' is not in capitals", group, ("Edit the Text",))
    for group, text in sorted(squeezed.items()):
        out.add("R10.text", f"'{text}' is squeezed or stretched to fit", group, ("Lay Out Again",))
    runs = s.texts(("title",))
    for key in ("title", "number"):
        value = s.fields.get(key, "")
        if not value:
            continue
        shown = _title_runs(runs, value, two_lines=key == "title")
        if not shown:
            continue
        h = min(run.size for run in shown) * fonts.CAP_HEIGHT
        if h < least - _SLACK:
            out.add(
                "R10.text",
                f"the title block's {_TITLE_LABELS[key]} is lettered {h:.1f} mm high to fit its block, below "
                f"the {least:.1f} mm minimum: shorten it, or use a larger sheet",
                key,
                ("Edit the Title Block", "Set Sheet"),
            )


def _shows(text: str, value: str) -> bool:
    """Whether a painted ``text`` is ``value``, or its start cut with an ellipsis."""
    cut = text.rstrip("…")
    return text == value or (text.endswith("…") and bool(cut) and value.startswith(cut))


def _title_runs(runs: list[D.TextRun], value: str, *, two_lines: bool) -> list[D.TextRun]:
    """The runs the title block shows ``value`` in: one run, or for the title two runs one
    above the other, the second going on where the first stops (layout/titleblock.py)."""
    for run in runs:
        if _shows(run.text, value):
            return [run]
    if not two_lines:
        return []
    for top in runs:
        if not top.text or not value.startswith(top.text + " "):
            continue
        rest = value[len(top.text) + 1 :]
        for low in runs:
            if low is not top and abs(low.x - top.x) < 0.5 and low.y < top.y and _shows(low.text, rest):
                return [top, low]
    return []


# --------------------------------------------------------------------------- R11: collisions, spacing


def _r11_collisions(s: _In, out: _Out) -> None:
    if s.sheet is None or s.layout is not None:
        return  # in a live run the layout's own checks say it (L.overlap, L.placement)
    boxes = []
    for run in s.texts(_LETTERED):
        boxes.append((_text_box(run), run.owner, run.text))
    # a feature control frame is a box of its own (its cells' strokes), as layout counts it
    frames: dict[str, tuple[float, float, float, float]] = {}
    for p in s.sheet.painted:
        if not isinstance(p, D.Stroke) or not p.owner.endswith("-frame"):
            continue
        b = _box_of_path(p.path)
        cur = frames.get(p.owner)
        if b is not None:
            frames[p.owner] = b if cur is None else _union(cur, b)
    boxes += [(Box(*b), owner, "frame") for owner, b in frames.items()]
    boxes.sort(key=lambda t: (t[0].x0, t[0].y0, t[1]))
    told: set[tuple[str, str]] = set()
    active: list[tuple[Box, str, str]] = []
    for b, owner, text in boxes:
        active = [a for a in active if a[0].x1 > b.x0 + 0.2]
        for b2, o2, t2 in active:
            if o2 == owner or not b2.hits(b, -0.2):
                continue
            pair = tuple(sorted((owner, o2)))
            if pair in told:
                continue
            told.add(pair)
            out.add(
                "R11.collisions", f"'{t2}' overlaps '{text}'", pair[0] or "sheet", ("Move",), other=pair[1]
            )
        active.append((b, owner, text))


def _r11_spacing(s: _In, out: _Out) -> None:
    if s.sheet is None:
        return
    pre = standards.DIMENSIONS
    boxes = s.view_boxes()
    rows: dict[tuple[str, str], list[tuple[float, float, float, str]]] = {}
    for a in s.annotations:
        if not isinstance(a, D.Dimension) or a.kind != "linear" or len(a.points) < 3:
            continue
        box = boxes.get(a.view)
        if box is None:
            continue
        (x0, y0), (x1, y1), (lx, ly) = a.points[:3]
        if abs(a.angle_deg) < 1e-6:
            line, lo, hi = ly, min(x0, x1), max(x0, x1)
            side = "below" if ly < box.y0 else "above" if ly > box.y1 else "inside"
            gap = box.y0 - ly if side == "below" else ly - box.y1
        elif abs(abs(a.angle_deg) - 90.0) < 1e-6:
            line, lo, hi = lx, min(y0, y1), max(y0, y1)
            side = "left" if lx < box.x0 else "right" if lx > box.x1 else "inside"
            gap = box.x0 - lx if side == "left" else lx - box.x1
        else:
            continue
        if side == "inside" or gap < pre.first_row - _SLACK:
            out.add(
                "R11.spacing",
                f"the dimension line of {a.id} stands {max(gap, 0.0):.1f} mm from {a.view}; the first row "
                f"stands at least {pre.first_row:.0f} mm off",
                a.id,
                ("Move", "Reset Position"),
            )
        rows.setdefault((a.view, side), []).append((line, lo, hi, a.id))
    for (_view, side), found in sorted(rows.items()):
        if side == "inside":
            continue
        found.sort(key=lambda t: (t[0], _natural(t[3])))
        for i, (la, lo_a, hi_a, ida) in enumerate(found):
            for lb, lo_b, hi_b, idb in found[i + 1 :]:
                apart = abs(lb - la)
                if apart > pre.row_spacing:
                    break
                if apart <= _SLACK or hi_a <= lo_b or hi_b <= lo_a:
                    continue
                if apart < pre.row_spacing - _SLACK:
                    out.add(
                        "R11.spacing",
                        f"{idb} stands {apart:.1f} mm from {ida}; "
                        f"rows stand at least {pre.row_spacing:.0f} mm apart",
                        idb,
                        ("Move", "Reset Position"),
                    )


def _painted_leaders(sheet: D.Sheet) -> list[tuple[str, tuple[float, float], tuple[float, float]]]:
    """Leaders as the painter drew them: a line, then its horizontal shoulder from the
    line's end, both owned by the item (layout/dimension.py leader_block)."""
    out = []
    strokes = [p for p in sheet.painted if isinstance(p, D.Stroke) and p.layer == "dimensions"]
    for a, b in zip(strokes, strokes[1:], strict=False):
        if a.owner != b.owner or not a.owner:
            continue
        first, second = _two_points(a.path), _two_points(b.path)
        if first is None or second is None:
            continue
        if math.dist(first[1], second[0]) > _SLACK or abs(second[1][1] - second[0][1]) > _SLACK:
            continue
        if abs(abs(second[1][0] - second[0][0]) - _LEADER_SHOULDER) > _SLACK:
            continue
        out.append((a.owner, first[0], first[1]))
    return out


def _r11_leaders(s: _In, out: _Out) -> None:
    if s.sheet is None or s.layout is not None:
        return  # in a live run the layout's own checks say it (L.leader)
    for owner, start, elbow in _painted_leaders(s.sheet):
        dx, dy = elbow[0] - start[0], elbow[1] - start[1]
        if math.hypot(dx, dy) < 1e-9:
            continue
        angle = math.degrees(math.atan2(abs(dy), abs(dx)))
        if not LEADER_MIN - 0.5 <= angle <= LEADER_MAX + 0.5:
            out.add(
                "R11.leaders",
                f"the leader of {owner} stands at {angle:.0f} degrees, outside 15 to 75",
                owner,
                ("Move",),
            )


# --------------------------------------------------------------------------- R12: views


def _r12_views(s: _In, out: _Out) -> None:
    if s.sheet is None:
        return
    labels = [a for page in s.sheets for a in page.annotations if isinstance(a, D.ViewLabel)]
    letters: dict[str, str] = {}
    for a in labels:
        m = _LABEL.match(a.text)
        if m is None:
            out.add("R12.views", f"the label '{a.text}' of {a.view} is not SECTION A-A or DETAIL B", a.view)
            continue
        letter = m.group(2)
        if m.group(1) == "SECTION" and m.group(3) != letter:
            out.add("R12.views", f"the label '{a.text}' of {a.view} names two letters", a.view)
        if any(c in standards.VIEW_LETTER_SKIP for c in letter):
            out.add(
                "R12.views",
                f"{a.view} is lettered {letter}; view letters skip I, O, Q and X",
                a.view,
                ("Reletter",),
            )
        if letter in letters:
            out.add(
                "R12.views",
                f"{a.view} reuses the letter {letter} of {letters[letter]}",
                a.view,
                ("Reletter",),
            )
        else:
            letters[letter] = a.view
    specs = s.specs()
    if not specs:
        return
    placed = set(s.placed)  # on any of the drawing's sheets
    labelled = {a.view for a in labels}
    used: dict[str, int] = {}
    for d in s.shown:
        used[d.view] = used.get(d.view, 0) + 1
    for vid, spec in sorted(specs.items(), key=lambda kv: _natural(kv[0])):
        if vid not in placed:
            if spec.kind == "isometric":
                _r12_left_out(s, out, vid)
            continue
        if spec.kind in ("base", "projected", "isometric") and vid in labelled:
            out.add("R12.views", f"{vid} is a principal view and is labelled; principal views are not", vid)
        if spec.kind in ("section", "detail") and vid not in labelled:
            out.add("R12.views", f"the {spec.kind} view {vid} has no label", vid, ("Lay Out Again",))
        if spec.kind != "isometric" and not used.get(vid) and not s.assembly:
            out.add("R12.views", f"{vid} carries no dimension", vid, ("Remove the View",))
        if spec.replaces and spec.replaces in placed:
            out.add(
                "R12.views",
                f"{vid} replaces {spec.replaces}, which is still on the sheet",
                vid,
                ("Remove the View",),
            )


def _r12_left_out(s: _In, out: _Out, vid: str) -> None:
    """The plan's isometric is on no sheet: it had no room. Said as information, the
    drawing being whole without it, with the way to give it room (11.7)."""
    if "isometric" in dict(s.drawing.options.view_sheets):
        out.add(
            "R12.views",
            "the isometric has no room even on a sheet of its own, so it is left out",
            vid,
            ("Sheet and Scale", "Remove the View"),
            level="information",
        )
        return
    out.add(
        "R12.views",
        "the isometric has no room on the sheet, so it is left out",
        vid,
        ("Move to Its Own Sheet", "Remove the View"),
        level="information",
    )


# --------------------------------------------------------------------------- R13: schemes


def _r13_scheme(s: _In, out: _Out) -> None:
    graphs = s.detail.graphs
    counts: dict[tuple[str, str], list[str]] = {}
    for d in s.shown:
        p = s.plan_dims.get(d.id)
        edge = s.detail.edges.get(p.id) if p is not None else None
        if edge is None:
            continue
        ax, pa, pb = edge
        g = graphs.get(ax)
        if g is None or pa not in g.node_of or pb not in g.node_of:
            continue
        if d.kind == "linear":
            counts.setdefault((d.view, ax), []).append(d.id)
        if g.origin not in (g.node_of[pa], g.node_of[pb]):
            a_words = _pos_words(s, g.pos[pa])
            b_words = _pos_words(s, g.pos[pb])
            out.add(
                "R13.scheme",
                f"{s.named(d)} locates {b_words} from {a_words} rather than from the datum",
                d.id,
                ("Link to the Datum",),
            )
    deep = s.layout.deep if s.layout is not None else frozenset()
    tracks = int(s.ctx.dimensioning.get("ordinate_tracks", 6))
    for (view, ax), ids in sorted(counts.items()):
        key = f"{view}/{ax}"
        if (key in deep and len(ids) >= MIN_DEEP) or len(ids) > tracks:
            out.add(
                "R13.scheme",
                f"the {len(ids)} locations along {ax.upper()} in {view} stack deeper than the "
                "Settings allow; ordinate dimensions would hold them",
                view,
                ("Use Ordinate",),
            )


def _r13_plusminus(s: _In, out: _Out) -> None:
    # Under the datum scheme a turned part's shoulders and ends are placed from the datum
    # end face by toleranced dimensions on purpose (docs/DRAWINGS.md 10.6), between faces
    turned = s.process == "turned" and s.drawing.options.effective_scheme == "datum"
    pm = [
        d
        for d in s.shown
        if d.role == "feature_location"
        and d.tolerance not in ("basic", "reference")
        and d.kind != "datum_feature"
        and not (turned and d.positions and not any(p.centre for p in d.positions))
    ]
    if not pm:
        return
    out.add(
        "R13.plusminus",
        f"{_plural(len(pm), 'location')} {'is' if len(pm) == 1 else 'are'} toleranced plus and minus; "
        f"{standards.PLUS_MINUS_SOURCE[standards.profile_of(s.settings)]} discourages plus/minus "
        "tolerances between features",
        "R13.plusminus",
        ("Use the Datum Scheme",),
        level="information" if s.process == "printed" else None,
    )


# --------------------------------------------------------------------------- R14, R15: notes and the process


def _note_texts(s: _In) -> list[str]:
    return [n.text.upper() for _i, n in s.notes]


def _r14_notes(s: _In, out: _Out) -> None:
    texts = _note_texts(s)
    if s.ctx is not None and s.detail is not None:
        r = s.detail.req.fillet_radius
        fillet = [t for t in texts if t.startswith("FILLETS AND ROUNDS")]
        if r:
            want = "R" + length_text(s.ctx, r, "width")
            if not any(want.upper() in t for t in fillet):
                out.add(
                    "R14.notes",
                    f"the fillet note does not give {want}, the most common fillet and round radius",
                    "fillet note",
                    ("Edit Notes",),
                )
        elif fillet:
            out.add("R14.notes", "the fillet note governs no fillet or round", "fillet note", ("Edit Notes",))
    for d in s.shown:
        if d.kind == "chamfer":
            line = d.suffix[0] if d.suffix else ""
            if not re.fullmatch(
                r"X (?:[0-9]*\.?[0-9]+" + standards.SYMBOL_DEGREE + r"|[0-9]*\.?[0-9]+)", line
            ):
                out.add(
                    "R14.notes",
                    f"{s.named(d)} is not written leg X angle or as two legs",
                    d.id,
                    ("Reset the Text",),
                )
        elif d.kind != "hole_callout" and any(_TYP.search(x) for x in (d.prefix, *d.suffix)):
            out.add(
                "R14.notes", f"{s.named(d)} says TYP; repetition is stated with nX", d.id, ("Set Prefix",)
            )
    for nid, n in s.notes:
        if _TYP.search(n.text):
            out.add("R14.notes", f"note {nid} says TYP; repetition is stated with nX", nid, ("Edit Notes",))
    if s.process in types.MACHINING:
        words = s.settings.notes.edge_break_in if s.unit == "in" else s.settings.notes.edge_break_mm
        if not any(words.upper() in t or ("BREAK" in t and "EDGE" in t) for t in texts):
            out.add("R14.notes", "no note breaks the sharp edges", "R14.notes", ("Edit Notes",))


def _fixed_templates(s: _In) -> list[str]:
    notes = s.settings.notes
    templates = notes.printed if s.process == "printed" else notes.machined
    out = []
    for t in templates:
        if "{" in t:
            continue
        out.append(upper(t) if s.settings.standard.upper_case_notes else t)
    return out


def _r15_process(s: _In, out: _Out) -> None:
    texts = _note_texts(s)
    for t in _fixed_templates(s):
        if t.upper() not in texts:
            out.add("R15.process", f"the {s.process} note '{t}' is missing", "R15.process", ("Edit Notes",))
    lines = " ".join(_tolerance_lines(s)).upper()
    if s.process == "printed":
        process = [k for k, t in enumerate(texts, 1) if t.startswith(_PROCESS_NOTE)]
        if not process:
            out.add(
                "R15.process",
                "a printed part's notes give no process tolerance note",
                "R15.process",
                ("Edit Notes",),
            )
        if s.sheet is not None:
            m = _SEE_NOTE.search(lines)
            if m is None or "TOLERANCES:" in lines.replace("GENERAL TOLERANCES:", ""):
                out.add(
                    "R15.process",
                    "the tolerance block of a printed part does not point at the process note",
                    "tolerance",
                    ("Lay Out Again",),
                )
            elif int(m.group(1)) not in process:
                out.add(
                    "R15.process",
                    f"the tolerance block points at note {m.group(1)}, which is not the process note",
                    "tolerance",
                    ("Lay Out Again",),
                )
            _build_arrows(s, out)
    elif s.sheet is not None and "SEE NOTE" in lines:
        out.add(
            "R15.process",
            "a machined part's tolerance block points at a note rather than giving the decimal table",
            "tolerance",
            ("Lay Out Again",),
        )


def _build_arrows(s: _In, out: _Out) -> None:
    """A printed part's build-direction arrow on each view carrying Z dimensions (and on
    the isometric, in a live run), looked for on the sheet the view is on."""
    arrows: dict[int, list[tuple[float, float]]] = {}
    for n, page in enumerate(s.sheets, 1):
        arrows[n] = [
            (r.x, r.y)
            for r in page.painted
            if isinstance(r, D.TextRun) and r.owner == "build" and "BUILD" in r.text
        ]
    boxes = s.view_boxes()
    views = {d.view for d in s.shown if d.axis == "z"}
    views |= {vid for vid, spec in s.specs().items() if spec.kind == "isometric"}
    for vid in sorted(views & set(s.placed), key=_natural):
        box = boxes.get(vid)
        if box is None:
            continue
        near = box.grow(32.0)  # an arrow set beside the view, with its label
        if not any(near.x0 <= x <= near.x1 and near.y0 <= y <= near.y1 for x, y in arrows[s.placed[vid]]):
            out.add(
                "R15.process",
                f"{vid} has no build-direction arrow",
                vid,
                ("Lay Out Again",),
            )


# --------------------------------------------------------------------------- R18: datums and frames


def _frames(s: _In) -> list[tuple[str, types.FrameCell]]:
    out = [(d.id, d.frame) for d in s.shown if d.frame is not None]
    for nid, n in s.notes:
        out += [(nid, f) for f in n.frames]
    return out


def _r18_datums(s: _In, out: _Out) -> None:
    defined: dict[str, int] = {}
    for d in s.drawing.datums:
        defined[d.letter] = defined.get(d.letter, 0) + 1
    for letter, n in sorted(defined.items()):
        if n > 1:
            out.add("R18.datums", f"datum {letter} is defined {n} times", f"datum-{letter}")
    referenced: dict[str, str] = {}
    for item, f in _frames(s):
        for letter in f.datums:
            referenced.setdefault(letter, item)
    symbols = {d.suffix[0]: d for d in s.shown if d.kind == "datum_feature" and d.suffix}
    on_sheet = {a.letter for a in s.annotations if isinstance(a, D.DatumFeature)}
    for letter, item in sorted(referenced.items()):
        if letter not in defined:
            out.add(
                "R18.datums",
                f"{item} refers to datum {letter}, which the drawing does not define",
                item,
                ("Set Datum",),
            )
            continue
        d = symbols.get(letter)
        if d is None:
            out.add(
                "R18.datums",
                f"datum {letter} is referred to but has no datum feature symbol",
                f"datum-{letter}",
                ("Restore", "Set Datum"),
            )
            continue
        if s.sheet is not None and letter not in on_sheet:
            out.add(
                "R18.datums",
                f"datum {letter}'s symbol is not on the sheet",
                f"datum-{letter}",
                ("Lay Out Again",),
            )
        p = s.plan_dims.get(d.id)
        found = s.graph_view(d.view) if p is not None else None
        if found is not None:
            spec, geom = found
            for q in s.detail.positions.get(p.id, ()):
                if witness_in(s.ctx, spec, geom, q) is None:
                    out.add(
                        "R18.datums",
                        f"datum {letter}'s symbol is in {d.view}, which shows its face as no visible line",
                        f"datum-{letter}",
                        ("Move to Another View",),
                    )


_FEATURE_OF_SIZE = ("position", "perpendicularity", "parallelism", "angularity", "straightness")


def _frame_problems(f: types.FrameCell) -> list[str]:
    c = standards.CHARACTERISTICS.get(f.characteristic)
    if c is None:
        return [f"'{f.characteristic}' is not a geometric characteristic"]
    out = []
    if not (isinstance(f.value, (int, float)) and math.isfinite(f.value) and f.value > 0):
        out.append(f"its {c.name} zone is not a positive value")
    if f.diameter and f.characteristic not in _FEATURE_OF_SIZE:
        out.append(f"a {c.name} zone takes no Ø")
    if f.modifier not in (None, "mmc", "lmc"):
        out.append(f"'{f.modifier}' is not a material condition")
    elif f.modifier is not None and f.characteristic not in _FEATURE_OF_SIZE:
        out.append(f"{c.name} takes no material condition")
    if c.datums == "never" and f.datums:
        out.append(f"{c.name} takes no datum")
    if c.datums == "required" and not f.datums:
        out.append(f"{c.name} needs a datum")
    if len(f.datums) > 3:
        out.append("a frame refers to at most three datums")
    if len(set(f.datums)) != len(f.datums):
        out.append("a frame refers to each datum once")
    if any(not re.fullmatch(r"[A-Z]{1,2}", x) for x in f.datums):
        out.append("datum references are capital letters")
    return out


def _r18_frames(s: _In, out: _Out) -> None:
    for item, f in _frames(s):
        for why in _frame_problems(f):
            out.add("R18.frames", f"the frame of {item}: {why}", item, ("Set Frame",))


# --------------------------------------------------------------------------- coverage and release


def _r_coverage(s: _In, out: _Out) -> None:
    if s.ctx is not None:
        cov = s.planned.plan.coverage
        unclaimed = tuple(s.ctx.features.unclaimed)
    else:
        cov = s.drawing.coverage
        unclaimed = ()
    note = next(((nid, n) for nid, n in s.notes if n.text.upper().startswith(_MODEL_NOTE)), None)
    reduced = bool(unclaimed) or not cov.complete or (s.ctx is None and note is not None)
    if not reduced:
        return
    reason = s.accepted.get("COV.unclaimed")
    if not cov.complete:
        words = cov.words()
    else:
        words = "a reduced-dimension drawing, as its model-governs note says (the file holds no counts)"
    if unclaimed:
        why: dict[str, int] = {}
        for u in unclaimed:
            why[u.reason] = why.get(u.reason, 0) + 1
        words += " (" + ", ".join(f"{n} {r.replace('_', ' ')}" for r, n in sorted(why.items())) + ")"
    if reason:
        out.add("COV.unclaimed", f"{words}; accepted: {reason}", "COV.unclaimed", level="information")
    else:
        out.add(
            "COV.unclaimed",
            words,
            "COV.unclaimed",
            ("Accept with a Reason",),
            level="error" if s.release else "warning",
        )
    # The note itself is one of the notes the drawing needs (10.10): a typed reason that
    # accepts the unclaimed geometry at release must not accept a missing or partial note.
    if note is None:
        out.add(
            "R15.process",
            "the drawing has unclaimed geometry and no model-governs note",
            "model note",
            ("Edit Notes",),
        )
        return
    nid, n = note
    missing = []
    text = n.text.upper()
    model = s.drawing.model or {}
    sha = model.get("sha256")
    if isinstance(sha, str) and len(sha) >= 16 and sha[:16].upper() not in text:
        missing.append("the model's short hash")
    part = model.get("part_number") or _title_text(s, "part_number")
    if part and str(part).upper() not in text:
        missing.append("the part number")
    rev = model.get("model_revision")
    if rev and str(rev).upper() not in text:
        missing.append("the model revision")
    if "PRECEDENCE" not in text:
        missing.append("that the dimensions shown take precedence")
    if not any(f.characteristic == "profile_surface" and f.datums for f in n.frames):
        missing.append("the profile tolerance of the undimensioned surfaces")
    if missing:
        out.add(
            "R15.process",
            f"the model-governs note {nid} does not give {', '.join(missing)}",
            nid,
            ("Edit Notes",),
        )


def _rel_stamp(s: _In, out: _Out) -> None:
    if s.drawing.status == "RELEASED":
        return
    if s.sheet is not None:
        stamped = any(isinstance(a, D.Stamp) and a.text == PRELIMINARY for a in s.annotations)
        painted = any(
            isinstance(p, D.TextRun) and p.layer == "stamp" and p.text == PRELIMINARY for p in s.sheet.painted
        )
        if not (stamped and painted):
            out.add(
                "REL.stamp",
                f"the unreleased sheet does not carry the stamp {PRELIMINARY}",
                "stamp",
                ("Lay Out Again",),
            )
    from .document import export_name

    for kind in ("pdf", "dxf"):
        try:
            name = export_name(s.drawing, kind)
        except InvalidArgumentError:
            continue
        if "PRELIMINARY" not in name:
            out.add("REL.stamp", f"the unreleased export would be named {name}, without PRELIMINARY", name)
    for o in s.drawing.outputs:
        if not o.released and "PRELIMINARY" not in o.name:
            out.add("REL.stamp", f"the unreleased export {o.name} is not named PRELIMINARY", o.name)


def _layout_checks(s: _In, out: _Out) -> None:
    for c in s.layout.checks:
        code = LAYOUT_CODES.get(c.code)
        if code is None:
            # a layout check this list does not know yet: kept under its own code
            level = c.severity if c.severity in LEVELS else "warning"
            out.items.append(Check(c.code, level, c.message, c.owner or c.code))
            continue
        out.add(code, c.message, c.owner or code, _LAYOUT_FIXES.get(c.code, ()), other=c.other)


# --------------------------------------------------------------------------- assemblies


def _asm_parts(s: _In, out: _Out) -> None:
    """An assembly's parts list on the sheet, and a balloon for each of its items that
    names an item of it (docs/drawings/assemblies.md)."""
    if not s.assembly or s.sheet is None:
        return
    lists = [a for a in s.annotations if isinstance(a, D.PartsList)]
    if not lists:
        out.add("ASM.parts", "the sheet has no parts list", "parts", ("Lay Out Again",))
        return
    # a long list's columns, in order, and those of the sheets it goes on to
    lists += [a for more in s.sheet.continuation for a in more.annotations if isinstance(a, D.PartsList)]
    rows = [r for pl in lists for r in pl.rows if r]
    items = {r[0] for r in rows}
    shown: set[str] = set()
    # the balloons of every sheet: a view put on a sheet of its own takes its balloons there
    for b in (a for page in s.sheets for a in page.annotations if isinstance(a, D.Balloon)):
        shown.add(b.item)
        if b.item not in items:
            out.add(
                "ASM.balloons",
                f"balloon {b.item} names no item of the parts list",
                f"balloon-{b.item}",
                ("Lay Out Again",),
                level="error",
            )
    from .plan.assembly import not_shown_items

    noted: set[str] = set()
    for _nid, note in s.notes:
        noted |= not_shown_items(getattr(note, "text", ""))
    for row in rows:
        if row[0] not in shown:
            name = f" ({row[1]})" if len(row) > 1 and row[1] else ""
            if row[0] in noted:  # not drawn in any view, and the sheet says so
                out.add(
                    "ASM.balloons",
                    f"item {row[0]}{name} is not drawn in any view; the note says it is not shown",
                    f"balloon-{row[0]}",
                    level="information",
                )
                continue
            out.add(
                "ASM.balloons",
                f"item {row[0]}{name} has no balloon: no view on the sheet shows an edge of it",
                f"balloon-{row[0]}",
            )


# --------------------------------------------------------------------------- the list

_FILE_CHECKS = (
    _r1_symbol,
    _r1_scale,
    _r2_units,
    _r2_format,
    _r2_rounding,
    _r2_override,
    _r3_tolerance,
    _r3_block,
    _r3_basic,
    _r3_roles,
    _r6_title,
    _r6_material,
    _r6_signatures,
    _r7_callouts,
    _r8_sheet,
    _r9_lines,
    _r10_text,
    _r11_collisions,
    _r11_spacing,
    _r11_leaders,
    _r12_views,
    _r13_plusminus,
    _r14_notes,
    _r15_process,
    _r18_datums,
    _r18_frames,
    _r_coverage,
    _rel_stamp,
    _asm_parts,
)
_MODEL_CHECKS = (_r1_aligned, _r4_graphs, _r4_sizes, _r4_members, _r4_coincident, _r5, _r13_scheme)
# What a part's drawing needs and an assembly's does not: its dimensions' units and
# tolerances, its material, its notes and process, its feature coverage and the
# dimension schemes (docs/drawings/assemblies.md).
# What only a fully defined drawing must answer; information on the other detail levels.
NOT_FULL_INFORMATION = frozenset({"R4.complete", "R4.members", "COV.unclaimed"})
# What an Express drawing leaves out on purpose, as (code, item): tolerances beyond the
# general ones, and the shop's general notes. Information on an Express drawing (until
# release, which asks for everything).
EXPRESS_INFORMATION = frozenset(
    {("R13.plusminus", "R13.plusminus"), ("R14.notes", "R14.notes"), ("R14.notes", "fillet note")}
)
# The title fields an Express drawing fills only from what it knows (the part, Drawing
# Settings), never by asking: a warning to fill in, not an error, until release.
EXPRESS_TITLE_WARNINGS = frozenset({"material", "finish", "DRAWN"})

_PART_ONLY = frozenset(
    {
        _r2_units,
        _r3_tolerance,
        _r3_block,
        _r3_basic,
        _r3_roles,
        _r6_material,
        _r13_plusminus,
        _r14_notes,
        _r15_process,
        _r_coverage,
        _r4_graphs,
        _r4_sizes,
        _r4_members,
        _r4_coincident,
        _r13_scheme,
    }
)


def run_checks(
    drawing: types.Drawing,
    *,
    planned: Planned | None = None,
    layout: LayoutResult | None = None,
    release: bool = False,
) -> tuple[Check, ...]:
    """The checklist of 20.1 for ``drawing``, in a fixed order (by code, then item).

    ``planned`` and ``layout`` are the plan stage's :class:`~.plan.Planned` and
    :class:`~.layout.LayoutResult` of a live run; with them every check runs, and
    the layout's own checks are kept under the ids they belong to. Without them the
    checks the file answers run and :data:`MODEL_ONLY` are skipped. ``release``
    asks for the release-time levels (R6.material, R6.signatures and COV.unclaimed
    as errors)."""
    if not isinstance(drawing, types.Drawing):
        raise InvalidArgumentError("drawing must be a Drawing", detail={"parameter": "drawing"})
    if planned is not None and not isinstance(planned, Planned):
        raise InvalidArgumentError(
            "planned must be the plan stage's Planned (orchestrate.run(...).planned)",
            detail={"parameter": "planned"},
        )
    if layout is not None and not isinstance(layout, LayoutResult):
        raise InvalidArgumentError(
            "layout must be a LayoutResult (orchestrate.run(...).result)", detail={"parameter": "layout"}
        )
    if not isinstance(release, bool):
        raise InvalidArgumentError("release must be true or false", detail={"parameter": "release"})
    s = _In(drawing, planned, layout, release)
    out = _Out()
    for check in _FILE_CHECKS:
        if not (s.assembly and check in _PART_ONLY):
            check(s, out)
    if planned is not None:
        for check in _MODEL_CHECKS:
            if not (s.assembly and check in _PART_ONLY):
                check(s, out)
    if layout is not None:
        _layout_checks(s, out)
    items = out.items
    detail = drawing.options.detail
    if detail != "full" and not s.assembly:
        # a simplified or complex drawing does not set out to define every feature
        level = "an Express" if drawing.options.express else f"a {detail}"
        why = f" ({level} drawing does not set out to define every feature)"
        items = [
            replace(c, level="information", message=c.message + why) if c.code in NOT_FULL_INFORMATION else c
            for c in items
        ]
    if drawing.options.express and not s.assembly and not release:
        items = [_express_level(c) for c in items]
    unique = {(c.code, c.item, c.message, c.level): c for c in items}
    return tuple(sorted(unique.values(), key=_order))


def _express_level(c: Check) -> Check:
    """``c`` at its level on an Express drawing: what Express leaves out on purpose is
    information, and a title field it found nothing for is a warning."""
    if (c.code, c.item) in EXPRESS_INFORMATION or (
        c.code == "R15.process" and c.item == "R15.process" and c.message.endswith("is missing")
    ):
        return replace(c, level="information", message=c.message + " (an Express drawing leaves it out)")
    if c.code == "R6.title" and c.item in EXPRESS_TITLE_WARNINGS and c.level == "error":
        why = " (an Express drawing asks nothing: fill it in before the drawing is released)"
        return replace(c, level="warning", message=c.message + why)
    return c


def skipped(*, planned: Planned | None = None) -> tuple[str, ...]:
    """The ids :func:`run_checks` cannot answer without the plan (the model): empty for
    a live run."""
    return () if planned is not None else MODEL_ONLY


__all__ = [
    "CODES",
    "END_DECISIONS",
    "EXPRESS_INFORMATION",
    "LAYOUT_CODES",
    "LEVELS",
    "MODEL_ONLY",
    "Check",
    "run_checks",
    "skipped",
]
