"""Values as a drawing shows them (``docs/DRAWINGS.md`` 10.8), and the unit a part that
states none was probably drawn in (6.2, Q3).

Every value arrives exact from the B-rep in metres (radians for angles) and is
converted with 1 in = 25.4 mm exactly. Rounding is half away from zero on the
decimal form of the value, so 0.0125 shown to two places is 0.013 on every
machine. The rules, in our words:

- Inch: no leading zero; the decimals are the precision, which selects the
  tolerance under the block. An explicit tolerance carries the value's
  decimals, a zero deviation included (``.500 +.005 -.000``).
- Millimetre: a leading zero. Under the decimal block, trailing zeros are kept
  where they select the tolerance; under ISO 2768 or a process note a nominal
  is shown to the places needed to state it. In an explicit tolerance a zero
  deviation is a lone 0 and the other keeps its sign and decimals.
- Limits are stacked upper over lower; symmetric tolerances use ±; MAX and MIN
  follow the value; angles carry the degree sign on value and tolerance; basic
  values are boxed with no tolerance; references are in parentheses.

Nothing here knows about views, layout or fonts: a :class:`Shown` holds the
strings, and layout measures and places them.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from fractions import Fraction

from ..errors import InvalidArgumentError
from . import standards

UNITS = ("in", "mm")
UNIT_WORDS = {"in": "INCHES", "mm": "MILLIMETERS"}
MAX_PLACES = 6
ROUNDING_SHARE = Fraction(1, 10)  # a shown value off by more than this share of its band is flagged

TOLERANCE_KINDS = ("block", "symmetric", "deviations", "limits", "max", "min", "basic", "reference")


def plain_sum(values: Iterable[float], start: float = 0) -> float:
    """``values`` added one at a time from the left, as ``sum()`` adds floats up to
    Python 3.11. From 3.12 ``sum()`` compensates for rounding, so its last bits can
    differ, and with them a number rounded at its last place on the sheet: the drawing
    library adds floats here, so a part draws the same on every Python version."""
    out = start
    for v in values:
        out = out + v
    return out


def _unit(unit: str) -> str:
    if unit not in UNITS:
        raise InvalidArgumentError(f"unit {unit!r} is not 'in' or 'mm'", detail={"parameter": "unit"})
    return unit


def in_unit(value_m: float, unit: str) -> float:
    """``value_m`` metres in ``unit``."""
    return value_m * 1000.0 if _unit(unit) == "mm" else value_m / standards.INCH


def from_unit(value: float, unit: str) -> float:
    """``value`` in ``unit`` as metres."""
    return value / 1000.0 if _unit(unit) == "mm" else value * standards.INCH


def _decimal(x: float | Fraction | Decimal) -> Decimal:
    """``x`` as a Decimal of 12 significant digits, which drops the binary noise of a
    conversion (0.0127 / 0.0254 is 0.5) and keeps every place a drawing shows."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, Fraction):
        return Decimal(x.numerator) / Decimal(x.denominator)
    if not math.isfinite(x):
        raise InvalidArgumentError("a drawing value must be finite", detail={"parameter": "value"})
    return Decimal(f"{x:.12g}")


def rounded(x: float | Fraction | Decimal, places: int) -> Decimal:
    """``x`` rounded half away from zero to ``places`` decimals."""
    if not isinstance(places, int) or not 0 <= places <= MAX_PLACES:
        raise InvalidArgumentError(
            f"places must be a whole number from 0 to {MAX_PLACES}", detail={"parameter": "places"}
        )
    try:
        return _decimal(x).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise InvalidArgumentError("the value is too large to show", detail={"parameter": "value"}) from None


def places_needed(x: float | Fraction | Decimal, max_places: int) -> int:
    """The fewest decimals, at most ``max_places``, that state ``x`` exactly (to the 12
    significant digits a value keeps)."""
    d = _decimal(x)
    for places in range(max_places + 1):
        if rounded(d, places) == d:
            return places
    return max_places


def number(x: float | Fraction | Decimal, places: int, unit: str, *, sign: bool = False) -> str:
    """``x`` (already in ``unit``) to ``places`` decimals: no leading zero in inches, a
    leading zero in millimetres; ``sign`` puts + before a positive value. A value that
    rounds to zero has no minus sign."""
    _unit(unit)
    d = rounded(x, places)
    if d == 0:
        d = abs(d)
    text = f"{abs(d):.{places}f}"
    if unit == "in" and text.startswith("0.") and places > 0:
        text = text[1:]
    if d < 0:
        return "-" + text
    return "+" + text if sign else text


def nominal(
    value_m: float, unit: str, places: int, *, exact: bool = False, max_places: int | None = None
) -> str:
    """A length's nominal. Under the decimal block (``exact`` false) it has ``places``
    decimals, trailing zeros kept. With ``exact`` (ISO 2768, a process note, a basic
    value) it has the places needed to state it, at least ``places`` and at most
    ``max_places`` (the unit's basic limit by default)."""
    v = in_unit(value_m, unit)
    if exact:
        cap = standards.BASIC_MAX_PLACES[unit] if max_places is None else max_places
        places = min(cap, max(places, places_needed(v, cap)))
    return number(v, places, unit)


@dataclass(frozen=True)
class Tolerance:
    """How a value is toleranced. ``upper`` and ``lower`` are deviations from the nominal
    in the drawing's unit (degrees for an angle): ``symmetric`` uses ``upper`` as ±,
    ``deviations`` and ``limits`` both, ``block`` takes the general block's value.
    ``places`` is the tolerance's decimals in millimetres (None: as needed); in
    inches the tolerance always has the value's."""

    kind: str = "block"
    upper: Fraction = Fraction(0)
    lower: Fraction = Fraction(0)
    places: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in TOLERANCE_KINDS:
            raise InvalidArgumentError(
                f"tolerance kind {self.kind!r} is not one of {', '.join(TOLERANCE_KINDS)}",
                detail={"parameter": "kind"},
            )
        for name in ("upper", "lower"):
            v = getattr(self, name)
            if not isinstance(v, Fraction):
                object.__setattr__(self, name, Fraction(str(v)) if isinstance(v, float) else Fraction(v))
        if self.kind == "symmetric" and self.upper <= 0:
            raise InvalidArgumentError(
                "a symmetric tolerance must be more than 0", detail={"parameter": "upper"}
            )
        if self.kind in ("deviations", "limits") and self.upper < self.lower:
            raise InvalidArgumentError(
                "the upper deviation must not be below the lower one", detail={"parameter": "upper"}
            )
        if self.places is not None and not (isinstance(self.places, int) and 0 <= self.places <= MAX_PLACES):
            raise InvalidArgumentError(
                f"tolerance places must be a whole number from 0 to {MAX_PLACES}",
                detail={"parameter": "places"},
            )

    def band(self) -> Fraction | None:
        """The width of the tolerance zone, or None when this kind states none."""
        if self.kind == "symmetric":
            return 2 * self.upper
        if self.kind in ("deviations", "limits"):
            return self.upper - self.lower
        return None


@dataclass(frozen=True)
class Shown:
    """A value as the sheet shows it. ``value`` is the main text (empty for limits),
    ``after`` follows it on the same line (``±.005``, ``MAX``), ``upper`` and
    ``lower`` are stacked to its right (deviations or limits), ``boxed`` draws the
    basic box. ``prefix`` and ``suffix`` (``Ø``, ``R``, ``°`` is part of the value)
    are kept apart so layout can measure each."""

    value: str
    after: str = ""
    upper: str = ""
    lower: str = ""
    boxed: bool = False
    prefix: str = ""

    def text(self) -> str:
        """One line for reports and tests: ``Ø.500 +.005 -.000``, ``[1.250]`` for basic."""
        main = self.prefix + self.value
        if self.boxed:
            main = f"[{main}]"
        parts = [main] if main else []
        if self.after:
            parts.append(self.after)
        if self.upper or self.lower:
            parts.append(f"{self.upper} {self.lower}".strip() if main else f"{self.upper}/{self.lower}")
        return " ".join(parts)


def block_plus_minus(
    unit: str, places: int, block: tuple[standards.BlockRow, ...] | None = None
) -> Fraction | None:
    """The general block's ± for a value shown to ``places`` decimals, or None when the
    block has no row for it (more places than its last row needs an explicit
    tolerance, ``R3.block``)."""
    rows = (
        block if block is not None else (standards.INCH_BLOCK if _unit(unit) == "in" else standards.MM_BLOCK)
    )
    for row in rows:
        if row.places == places:
            return row.plus_minus
    return None


def _deviation(d: Fraction, places: int, unit: str, *, upper: bool) -> str:
    if d == 0:  # millimetres: a lone 0; inches: the value's places, signed by its side
        return "0" if unit == "mm" else ("+" if upper else "-") + number(0, places, unit)
    return number(d, places, unit, sign=True)


def _tol_places(tol: Tolerance, unit: str, value_places: int, *values: Fraction) -> int:
    if unit == "in":
        return value_places
    if tol.places is not None:
        return tol.places
    return max([places_needed(v, MAX_PLACES) for v in values] + [1])


def show(
    value_m: float,
    unit: str,
    places: int,
    tolerance: Tolerance | None = None,
    *,
    prefix: str = "",
) -> Shown:
    """A length as the sheet shows it (10.8). ``places`` is the precision; under a
    ``block`` tolerance (the default) it selects the block's row."""
    tol = tolerance or Tolerance()
    v = in_unit(value_m, unit)
    if tol.kind == "basic":
        return Shown(nominal(value_m, unit, 0, exact=True), boxed=True, prefix=prefix)
    if tol.kind == "reference":
        return Shown(f"({number(v, places, unit)})", prefix=prefix)
    main = number(v, places, unit)
    if tol.kind == "block":
        return Shown(main, prefix=prefix)
    if tol.kind in ("max", "min"):
        return Shown(main, after=tol.kind.upper(), prefix=prefix)
    if tol.kind == "symmetric":
        tp = _tol_places(tol, unit, places, tol.upper)
        return Shown(main, after=standards.SYMBOL_PLUS_MINUS + number(tol.upper, tp, unit), prefix=prefix)
    if tol.kind == "deviations":
        tp = _tol_places(tol, unit, places, tol.upper, tol.lower)
        return Shown(
            main,
            upper=_deviation(tol.upper, tp, unit, upper=True),
            lower=_deviation(tol.lower, tp, unit, upper=False),
            prefix=prefix,
        )
    # limits: the upper limit above the lower, both to the same places
    base = _decimal(v)
    hi, lo = base + _decimal(tol.upper), base + _decimal(tol.lower)
    lp = places if unit == "in" else max(places, _tol_places(tol, unit, places, tol.upper, tol.lower))
    return Shown("", upper=number(hi, lp, unit), lower=number(lo, lp, unit), prefix=prefix)


def angle_text(degrees: float | Fraction | Decimal, places: int = 0, *, sign: bool = False) -> str:
    """An angle in decimal degrees with its sign: ``15°``, ``82°``, ``0.5°``. Angles keep
    a leading zero in both units."""
    return number(degrees, places, "mm", sign=sign) + standards.SYMBOL_DEGREE


def minutes_text(minutes: int) -> str:
    """An angle given in minutes of arc as degrees and minutes: ``1°30'``, ``0°5'``."""
    return (
        f"{minutes // 60}{standards.SYMBOL_DEGREE}{minutes % 60}'"
        if minutes % 60
        else f"{minutes // 60}{standards.SYMBOL_DEGREE}"
    )


def show_angle(value_rad: float, places: int = 0, tolerance: Tolerance | None = None) -> Shown:
    """An angle as the sheet shows it, the degree sign on value and tolerance."""
    tol = tolerance or Tolerance()
    deg = math.degrees(value_rad)
    if tol.kind == "basic":
        return Shown(angle_text(deg, places_needed(deg, 3)), boxed=True)
    if tol.kind == "reference":
        return Shown(f"({angle_text(deg, places)})")
    main = angle_text(deg, places)
    if tol.kind == "symmetric":
        tp = tol.places if tol.places is not None else max(1, places_needed(tol.upper, 3))
        return Shown(main, after=standards.SYMBOL_PLUS_MINUS + angle_text(tol.upper, tp))
    if tol.kind == "deviations":
        tp = (
            tol.places
            if tol.places is not None
            else max(places_needed(tol.upper, 3), places_needed(tol.lower, 3))
        )
        return Shown(
            main,
            upper=angle_text(tol.upper, tp, sign=True),
            lower=angle_text(tol.lower, tp, sign=tol.lower > 0),
        )
    if tol.kind == "limits":
        base = _decimal(deg)
        hi, lo = base + _decimal(tol.upper), base + _decimal(tol.lower)
        return Shown("", upper=angle_text(hi, places), lower=angle_text(lo, places))
    if tol.kind in ("max", "min"):
        return Shown(main, after=tol.kind.upper())
    return Shown(main)


def band_text(plus_minus: Fraction, unit: str) -> str:
    """A symmetric band as the wizard says it: ``±.010``, ``±0.05``."""
    places = places_needed(plus_minus, MAX_PLACES)
    if unit == "in":
        places = max(places, 3)
    return standards.SYMBOL_PLUS_MINUS + number(plus_minus, places, unit)


def band_summary(bands: Iterable[str]) -> str:
    """How many dimensions fall in each band, widest band count first: ``23 at ±.010,
    14 at ±.005``."""
    counts = Counter(bands)
    return ", ".join(f"{n} at {b}" for b, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def rounding_share(value_m: float, unit: str, places: int, band: Fraction | None) -> Fraction:
    """How far the value as shown is from the model's, as a share of the tolerance
    band (10.8's rounding guard); 0 when there is no band."""
    if not band:
        return Fraction(0)
    v = _decimal(in_unit(value_m, unit))
    off = abs(rounded(v, places) - v)
    return Fraction(str(off)) / Fraction(band)


def rounding_flagged(value_m: float, unit: str, places: int, band: Fraction | None) -> bool:
    """Whether the rounding guard flags this value: shown off by more than 10 % of its band."""
    return rounding_share(value_m, unit, places, band) > ROUNDING_SHARE


# --------------------------------------------------------------------------- unit guessing


@dataclass(frozen=True)
class UnitGuess:
    """The unit a part's sizes suggest (6.2, Q3), with the evidence: how many sizes are
    whole thousandths of an inch, how many whole hundredths of a millimetre, how
    many only one of those, and how many sizes there were. ``decided`` is false
    when the evidence does not lean either way, and then ``unit`` is inch."""

    unit: str
    inch: int
    mm: int
    inch_only: int
    mm_only: int
    sizes: int
    decided: bool

    def to_dict(self) -> dict:
        return {
            "unit": self.unit,
            "inch": self.inch,
            "mm": self.mm,
            "inch_only": self.inch_only,
            "mm_only": self.mm_only,
            "sizes": self.sizes,
            "decided": self.decided,
        }


def _whole(x: float, step: int) -> bool:
    """Whether ``x`` is a whole number of 1/``step``, within a thousandth of a step
    (2.5e-8 m for an inch thousandth, above the B-rep's resolution)."""
    scaled = x * step
    return abs(scaled - round(scaled)) <= 1e-3


def guess_units(sizes_m: Iterable[float], *, lean: float = 1.5, minimum: int = 3) -> UnitGuess:
    """Guess the unit from a part's sizes in metres. A size counts for inch when it is a
    whole thousandth of an inch, for millimetre when a whole hundredth of a
    millimetre; sizes that are both prove nothing. The guess is decided when one
    side has at least ``minimum`` sizes of its own and ``lean`` times the other's."""
    inch = mm = inch_only = mm_only = n = 0
    for s in sizes_m:
        if not isinstance(s, (int, float)) or not math.isfinite(s) or s <= 0:
            continue
        n += 1
        is_in = _whole(s / standards.INCH, 1000)
        is_mm = _whole(s * 1000.0, 100)
        inch += is_in
        mm += is_mm
        inch_only += is_in and not is_mm
        mm_only += is_mm and not is_in
    if mm_only >= minimum and mm_only >= lean * inch_only:
        return UnitGuess("mm", inch, mm, inch_only, mm_only, n, True)
    if inch_only >= minimum and inch_only >= lean * mm_only:
        return UnitGuess("in", inch, mm, inch_only, mm_only, n, True)
    return UnitGuess("in", inch, mm, inch_only, mm_only, n, False)


__all__ = [
    "ROUNDING_SHARE",
    "TOLERANCE_KINDS",
    "UNITS",
    "UNIT_WORDS",
    "Shown",
    "Tolerance",
    "UnitGuess",
    "angle_text",
    "band_summary",
    "band_text",
    "block_plus_minus",
    "from_unit",
    "guess_units",
    "in_unit",
    "minutes_text",
    "nominal",
    "number",
    "places_needed",
    "plain_sum",
    "rounded",
    "rounding_flagged",
    "rounding_share",
    "show",
    "show_angle",
]
