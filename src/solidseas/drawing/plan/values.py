"""Values as the sheet shows them (``docs/DRAWINGS.md`` 10.6, 10.8).

Precision comes from a dimension's role and the Settings (inch: two places for the
envelope, steps and widths, three for hole sizes; millimetre: one and two). Basic
values show the places they need (C18). Printed parts show nominals as needed,
since their tolerance is the process note's. :func:`dim_text` turns a planned
dimension into the text parts layout measures; :func:`bands` counts the
dimensions in each tolerance band; :func:`rounding` is 10.8's guard.
"""

from __future__ import annotations

import math
from fractions import Fraction

from .. import numbers, standards
from ..display import DimText
from ..types import (
    AngledFace,
    Blend,
    Boss,
    Chamfer,
    Groove,
    Hole,
    Pattern,
    PlannedDimension,
    Pocket,
    Slot,
    Step,
    Width,
)
from .context import Context

DIAMETER = standards.SYMBOL_DIAMETER


def unit_for(source, options, settings) -> str:
    """The drawing's unit: the option, else the Settings', else the part's (as it
    states it or as guessed), else the Settings' unit for unstated parts, else mm."""
    if options.units in ("in", "mm"):
        return options.units
    if settings.standard.units in ("in", "mm"):
        return settings.standard.units
    units = getattr(source, "units", None)
    if units is not None and getattr(units, "unit", None) in ("in", "mm"):
        return units.unit
    return settings.standard.unit_for_unstated or "mm"


def places(ctx: Context, role: str) -> int:
    """Decimals for a role from the Settings."""
    return ctx.settings.precision(ctx.unit, role)


def tolerance_for(ctx: Context, tolerance_class: str) -> str:
    """How a requirement's dimension is toleranced: basic under the datum scheme for
    locations and pattern basics, else the general block."""
    if tolerance_class == "basic" and ctx.scheme == "datum":
        return "basic"
    return "block"


def _count(n: int) -> str:
    return f"{n}X " if n > 1 else ""


def length_text(ctx: Context, value_m: float, role: str, tolerance: str = "block", **kw) -> str:
    """One length as text, without its tolerance: for callout lines and notes."""
    return shown(ctx, value_m, places(ctx, role), tolerance, **kw).text()


def shown(
    ctx: Context, value_m: float, n_places: int, tolerance: str = "block", *, prefix: str = ""
) -> numbers.Shown:
    """A length as shown: basic to the places it needs, a printed part's nominal as
    needed, otherwise to ``n_places`` (which selects the block's row)."""
    if tolerance == "basic":
        return numbers.show(value_m, ctx.unit, n_places, numbers.Tolerance("basic"), prefix=prefix)
    if tolerance == "reference":
        return numbers.show(value_m, ctx.unit, n_places, numbers.Tolerance("reference"), prefix=prefix)
    if ctx.process == "printed":
        base = 3 if ctx.unit == "in" else 0
        return numbers.Shown(numbers.nominal(value_m, ctx.unit, base, exact=True), prefix=prefix)
    return numbers.show(value_m, ctx.unit, n_places, prefix=prefix)


def angle_shown(ctx: Context, value_rad: float, tolerance: str = "block") -> numbers.Shown:
    if tolerance == "basic":
        return numbers.show_angle(value_rad, 0, numbers.Tolerance("basic"))
    if tolerance == "reference":
        return numbers.show_angle(value_rad, 0, numbers.Tolerance("reference"))
    deg = math.degrees(value_rad)
    return numbers.show_angle(value_rad, numbers.places_needed(deg, 2))


def explicit(pd: PlannedDimension) -> numbers.Tolerance | None:
    """A planned dimension's explicit tolerance, or None for block, basic, reference
    and derived."""
    if pd.tolerance in ("block", "basic", "reference", "derived"):
        return None
    upper, lower = pd.tolerance_values
    return numbers.Tolerance(pd.tolerance, Fraction(str(upper)), Fraction(str(lower)))


def dim_text(ctx: Context, pd: PlannedDimension) -> DimText:
    """The text parts of a planned dimension, kept apart so layout measures each.

    For a hole callout ``suffix[0]`` is THRU or the depth, on the value's line, and
    the rest are lines below; for every other kind the suffix entries are lines
    below the value."""
    tol = explicit(pd)
    basic = pd.tolerance == "basic"
    if pd.kind in ("leader_note", "datum_feature"):
        lines = pd.suffix or ("",)
        return DimText(lines[0], prefix=pd.prefix, suffix=tuple(lines[1:]))
    if pd.kind == "angle":
        s = angle_shown(ctx, pd.value, pd.tolerance)
        return DimText(s.value, pd.prefix, s.after, s.upper, s.lower, s.boxed, pd.suffix)
    if pd.kind == "radius" and pd.tolerance == "derived":
        return DimText("", pd.prefix, suffix=pd.suffix)  # a full-round end: R alone (convention 5)
    if tol is not None:
        s = numbers.show(pd.value, ctx.unit, pd.places, tol, prefix=pd.prefix)
    else:
        s = shown(ctx, pd.value, pd.places, pd.tolerance, prefix=pd.prefix)
    override = getattr(pd, "override", None)
    if override:
        # the user's text stands for the value (R2.override); the symbol, count and
        # suffix stay, a stacked tolerance goes with the measured value
        first = pd.suffix[0] if pd.kind in ("hole_callout", "chamfer") and pd.suffix else ""
        rest = tuple(pd.suffix[1:]) if first else tuple(pd.suffix)
        return DimText(override, s.prefix, first, boxed=basic, suffix=rest)
    if pd.kind == "hole_callout":
        first = pd.suffix[0] if pd.suffix else ""
        after = (s.after + " " + first).strip() if first else s.after
        return DimText(s.value, s.prefix, after, s.upper, s.lower, basic, tuple(pd.suffix[1:]))
    if pd.kind == "chamfer":
        return DimText(s.value, s.prefix, pd.suffix[0] if pd.suffix else "", suffix=tuple(pd.suffix[1:]))
    return DimText(s.value, s.prefix, s.after, s.upper, s.lower, s.boxed or basic, pd.suffix)


def text_line(text: DimText) -> str:
    """A dimension's text on one line, for reports, checks and tests."""
    main = text.prefix + text.value
    if text.boxed:
        main = f"[{main}]"
    parts = [main]
    if text.after:
        parts.append(text.after)
    if text.upper or text.lower:
        parts.append(f"{text.upper}/{text.lower}")
    out = " ".join(p for p in parts if p)
    return " / ".join([out, *text.suffix]) if text.suffix else out


# ---------------------------------------------------------------------- bands


def band_of(ctx: Context, pd: PlannedDimension) -> str | None:
    """The tolerance band a dimension falls in under the general block (``±.010``),
    or None when the block does not tolerance it."""
    if pd.state != "shown" or pd.tolerance != "block" or ctx.process == "printed":
        return None
    if pd.kind in ("datum_feature", "frame", "leader_note"):
        return None
    if pd.kind == "angle":
        return standards.SYMBOL_PLUS_MINUS + numbers.angle_text(ctx.settings.tolerances.angle, 1)
    pm = numbers.block_plus_minus(ctx.unit, pd.places, ctx.settings.block(ctx.unit))
    if pm is None:
        return None
    return numbers.band_text(pm, ctx.unit)


def bands(ctx: Context, dims) -> tuple[tuple[str, int], ...]:
    """How many shown dimensions fall in each band, the most common first (10.8)."""
    counts: dict[str, int] = {}
    for pd in dims:
        b = band_of(ctx, pd)
        if b is not None:
            counts[b] = counts.get(b, 0) + 1
    return tuple(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def rounding(ctx: Context, pd: PlannedDimension) -> bool:
    """Whether the value as shown is off the model's by more than a tenth of its band
    (10.8): the check offers to keep it, add places or give a tolerance; the
    precision is never changed behind the user's back."""
    if pd.tolerance != "block" or pd.kind in ("angle", "datum_feature", "leader_note", "frame"):
        return False
    pm = numbers.block_plus_minus(ctx.unit, pd.places, ctx.settings.block(ctx.unit))
    if pm is None:
        return False
    return numbers.rounding_flagged(pd.value, ctx.unit, pd.places, 2 * pm)


# ---------------------------------------------------------------------- words


def feature_words(ctx: Context, fids) -> str:
    """Features in words for the checker (C16): ``4X Ø6.6 holes``, ``the 100.0 width``."""
    out = []
    for fid in list(fids)[:2]:
        k = ctx.index_of.get(fid)
        if k is None:
            out.append(fid)
            continue
        out.append(_one(ctx, ctx.features.features[k]))
    words = " and ".join(out)
    if len(list(fids)) > 2:
        words += f" and {len(list(fids)) - 2} more"
    return words


def _len(ctx: Context, v: float, role: str = "width") -> str:
    return numbers.number(numbers.in_unit(v, ctx.unit), places(ctx, role), ctx.unit)


def _one(ctx: Context, f) -> str:
    if isinstance(f, Pattern):
        first = ctx.features.features[f.members[0]] if f.members else None
        d = first.diameter if isinstance(first, Hole) else 0.0
        return f"{len(f.members)}X {DIAMETER}{_len(ctx, d, 'hole_size')} holes"
    if isinstance(f, Hole):
        return f"the {DIAMETER}{_len(ctx, f.diameter, 'hole_size')} hole"
    if isinstance(f, Boss):
        return f"the {DIAMETER}{_len(ctx, f.diameter, 'hole_size')} boss"
    if isinstance(f, Width):
        word = {"envelope": "overall size", "gap": "gap"}.get(f.role, f.role)
        if f.kind == "gap" and f.role not in ("pocket", "slot", "keyseat", "groove"):
            word = "gap"
        return f"the {_len(ctx, f.size)} {word} along {f.axis.upper()}"
    if isinstance(f, Slot):
        return f"the {_len(ctx, f.width)} slot"
    if isinstance(f, Step):
        return f"the step at {f.axis.upper()} {_len(ctx, f.offset)}"
    if isinstance(f, Pocket):
        return "the pocket"
    if isinstance(f, Groove):
        return "the face groove"
    if isinstance(f, Blend):
        return f"the R{_len(ctx, f.radius)} {f.kind}"
    if isinstance(f, Chamfer):
        return "the chamfer"
    if isinstance(f, AngledFace):
        return "the angled face"
    return "the feature"


def count_prefix(n: int) -> str:
    return _count(n)


__all__ = [
    "angle_shown",
    "band_of",
    "bands",
    "count_prefix",
    "dim_text",
    "explicit",
    "feature_words",
    "length_text",
    "places",
    "rounding",
    "shown",
    "text_line",
    "tolerance_for",
    "unit_for",
]
