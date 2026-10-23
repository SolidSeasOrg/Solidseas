"""The numbers a drawing's standard fixes, in one place (``docs/DRAWINGS.md`` 7.3, 22).

Sheet sizes, margins and zones; preferred scales; line widths and text heights;
the general tolerance blocks; the ISO 2768-1 tables for the millimetre option;
the additive process tolerances (service bureau figures); thread, tap drill and
clearance tables; the revision letter sequence; and the GD&T characteristics.
Every value is in our own words or a numeric fact; ``docs/drawings/standards.md``
says where each comes from and which are marked (verify).

Lengths on the sheet are millimetres; lengths on the part are metres unless a
name says otherwise. Nothing here reads a file or the clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from ..errors import InvalidArgumentError

INCH = 0.0254  # metres, exactly

# --------------------------------------------------------------------------- sheets


@dataclass(frozen=True)
class Sheet:
    """One sheet size in landscape: ``width`` and ``height`` in millimetres, the margin
    from the trimmed edge to the border, and the zone grid (columns by numbers,
    rows by letters, Y14.1)."""

    name: str
    width: float
    height: float
    margin: float
    columns: int
    rows: int

    def size(self, orientation: str = "landscape") -> tuple[float, float]:
        """(width, height) in millimetres for ``orientation`` (``landscape`` or ``portrait``)."""
        if orientation == "portrait":
            return self.height, self.width
        return self.width, self.height


# ASME sizes in inches (Y14.1): A 11 x 8.5, B 17 x 11, C 22 x 17, D 34 x 22, E 44 x 34.
# Margins 0.38 in on A and B, 0.50 in on C to E (NASA 1.1; verify Y14.1-2020's A size).
# Zones of 4.25 or 5.5 in a side: 2 x 2 on A, 4 x 2 on B, 4 x 4 on C, 8 x 4 on D and
# 8 x 8 on E (verify).
SHEETS: dict[str, Sheet] = {
    "A": Sheet("A", 279.4, 215.9, 0.38 * 25.4, 2, 2),
    "B": Sheet("B", 431.8, 279.4, 0.38 * 25.4, 4, 2),
    "C": Sheet("C", 558.8, 431.8, 0.50 * 25.4, 4, 4),
    "D": Sheet("D", 863.6, 558.8, 0.50 * 25.4, 8, 4),
    "E": Sheet("E", 1117.6, 863.6, 0.50 * 25.4, 8, 8),
}
SHEET_ORDER = ("A", "B", "C", "D", "E")

# Preferred scales as (sheet, model): 1:2 is (1, 2), 4:1 is (4, 1). Full size first, then
# reductions from the largest, then enlargements from the smallest (ASME preset, 7.3).
SCALES: tuple[tuple[int, int], ...] = (
    (1, 1),
    (1, 2),
    (1, 4),
    (1, 10),
    (1, 20),
    (2, 1),
    (4, 1),
    (10, 1),
    (20, 1),
)


def scale_text(scale: tuple[int, int]) -> str:
    """``scale`` as the title block says it: ``1:2``, ``4:1``, ``1:1``."""
    sheet, model = scale
    return f"{sheet}:{model}"


def scale_factor(scale: tuple[int, int]) -> float:
    """Sheet millimetres per model millimetre for ``scale`` (sheet, model)."""
    sheet, model = scale
    return sheet / model


def parse_scale(text: str) -> tuple[int, int] | None:
    """``N:M`` as (N, M), or None when it is not two whole numbers from 1 to 1000."""
    if not isinstance(text, str) or text.count(":") != 1:
        return None
    a, b = (part.strip() for part in text.split(":"))
    if not (a.isdigit() and b.isdigit()) or len(a) > 4 or len(b) > 4:
        return None
    n, m = int(a), int(b)
    if not (1 <= n <= 1000 and 1 <= m <= 1000):
        return None
    return n, m


# --------------------------------------------------------------------------- lines and text


@dataclass(frozen=True)
class LineStyle:
    """How one ``style`` of the display list is drawn: width in millimetres and dash
    pattern (dash, gap, ...) in millimetres, empty for a solid line."""

    width: float
    dash: tuple[float, ...] = ()


# Thick 0.6 mm and thin 0.3 mm (Y14.2 as publicly summarised; practice for the dashes).
LINES: dict[str, LineStyle] = {
    "visible": LineStyle(0.6),
    "border": LineStyle(0.6),
    "hidden": LineStyle(0.3, (3.0, 1.5)),
    "tangent": LineStyle(0.3, (6.0, 1.5)),
    "centre": LineStyle(0.3, (12.0, 1.5, 3.0, 1.5)),
    "phantom": LineStyle(0.3, (12.0, 1.5, 3.0, 1.5, 3.0, 1.5)),
    "thin": LineStyle(0.3),
    "dimension": LineStyle(0.3),
    "hatch": LineStyle(0.3),
}
LINE_STYLES = tuple(LINES)


@dataclass(frozen=True)
class TextPreset:
    """Text heights in millimetres for one unit (7.3)."""

    dimension: float
    note: float
    view_label: float
    view_letter: float
    title: float
    number: float
    block_label: float


TEXT: dict[str, TextPreset] = {
    "in": TextPreset(
        0.12 * 25.4, 0.12 * 25.4, 0.18 * 25.4, 0.24 * 25.4, 0.18 * 25.4, 0.24 * 25.4, 0.10 * 25.4
    ),
    "mm": TextPreset(3.0, 3.0, 4.5, 6.0, 4.5, 6.0, 2.5),
}


@dataclass(frozen=True)
class DimensionPreset:
    """Spacing of dimensions on the sheet, millimetres (7.3, 22 rule 11)."""

    first_row: float = 10.0
    row_spacing: float = 6.0
    extension_gap: float = 1.5
    extension_overrun: float = 3.0
    arrow_ratio: float = 3.0  # length to width; the length equals the text height


DIMENSIONS = DimensionPreset()

# --------------------------------------------------------------------------- tolerance blocks


@dataclass(frozen=True)
class BlockRow:
    """One row of a decimal tolerance block: ``places`` decimals carry ``plus_minus``
    (in the block's unit)."""

    places: int
    plus_minus: Fraction


# The ASME inch block: .X ±.030, .XX ±.010, .XXX ±.005; angles ±0.5 degree (7.3).
INCH_BLOCK: tuple[BlockRow, ...] = (
    BlockRow(1, Fraction(30, 1000)),
    BlockRow(2, Fraction(10, 1000)),
    BlockRow(3, Fraction(5, 1000)),
)
# The millimetre block: X ±0.5, X.X ±0.2, X.XX ±0.05; angles ±0.5 degree.
MM_BLOCK: tuple[BlockRow, ...] = (
    BlockRow(0, Fraction(5, 10)),
    BlockRow(1, Fraction(2, 10)),
    BlockRow(2, Fraction(5, 100)),
)
ANGLE_BLOCK = Fraction(1, 2)  # degrees, both units

# Basic dimensions gain decimals up to these, since their decimals select no tolerance (10.8).
BASIC_MAX_PLACES = {"in": 4, "mm": 3}

INTERPRETATION = "DIMENSIONING AND TOLERANCING PER ASME Y14.5-2018"

# --------------------------------------------------------------------------- the standard

PROFILES = ("asme", "iso")  # the drawing standards (docs/drawings/iso.md)
ANGLES = ("first", "third")  # projection angles (ASME Y14.3, ISO 5456-2)
STANDARD_ANGLE = {"asme": "third", "iso": "first"}
# The statement naming how the dimensions are read, once in the tolerance block, and the
# words R3.tolerance looks for in it (the ISO wording verify).
INTERPRETATIONS = {"asme": INTERPRETATION, "iso": "TOLERANCING ISO 8015"}
INTERPRETATION_KEYS = {"asme": "Y14.5", "iso": "ISO 8015"}
# What R13.plusminus names as discouraging plus/minus between features (ISO's verify).
PLUS_MINUS_SOURCE = {"asme": "Y14.5-2018", "iso": "the ISO GPS system (ISO 14405-2)"}


def profile_of(settings) -> str:
    """The drawing standard ``settings`` name: ``asme`` unless they name another known one."""
    profile = getattr(getattr(settings, "standard", None), "profile", "asme")
    return profile if profile in PROFILES else "asme"


def projection(settings) -> str:
    """The projection angle in force under ``settings``, ``first`` or ``third``: the
    standard's own unless the settings choose one."""
    chosen = getattr(getattr(settings, "standard", None), "projection", "standard")
    return chosen if chosen in ANGLES else STANDARD_ANGLE[profile_of(settings)]


def interpretation(settings) -> str:
    """The tolerance block's statement of the standard the dimensions are read by."""
    return INTERPRETATIONS[profile_of(settings)]

# --------------------------------------------------------------------------- ISO 2768-1

ISO2768_CLASSES = ("f", "m", "c", "v")

# Upper bound of each linear size range in millimetres (the first starts at 0.5), and the
# permissible deviation per class; None where the class gives none.
_ISO_LINEAR: tuple[tuple[float, tuple[str | None, ...]], ...] = (
    (3.0, ("0.05", "0.1", "0.2", None)),
    (6.0, ("0.05", "0.1", "0.3", "0.5")),
    (30.0, ("0.1", "0.2", "0.5", "1")),
    (120.0, ("0.15", "0.3", "0.8", "1.5")),
    (400.0, ("0.2", "0.5", "1.2", "2.5")),
    (1000.0, ("0.3", "0.8", "2", "4")),
    (2000.0, ("0.5", "1.2", "3", "6")),
    (4000.0, (None, "2", "4", "8")),
)
_ISO_RADIUS: tuple[tuple[float, tuple[str, ...]], ...] = (
    (3.0, ("0.2", "0.2", "0.4", "0.4")),
    (6.0, ("0.5", "0.5", "1", "1")),
    (float("inf"), ("1", "1", "2", "2")),
)
# Angle deviations in minutes of arc, by the shorter side's length in millimetres.
_ISO_ANGLE: tuple[tuple[float, tuple[int, ...]], ...] = (
    (10.0, (60, 60, 90, 180)),
    (50.0, (30, 30, 60, 120)),
    (120.0, (20, 20, 30, 60)),
    (400.0, (10, 10, 15, 30)),
    (float("inf"), (5, 5, 10, 20)),
)


def _iso_class(cls: str) -> int:
    if cls not in ISO2768_CLASSES:
        raise InvalidArgumentError(
            f"ISO 2768 class {cls!r} is not one of f, m, c, v", detail={"parameter": "cls"}
        )
    return ISO2768_CLASSES.index(cls)


def iso2768_linear(size_mm: float, cls: str = "m") -> Fraction | None:
    """The ISO 2768-1 permissible deviation (±, millimetres) for a linear size, or None
    where the standard gives none (under 0.5 mm, over 4000 mm, or the class has no
    value for that range)."""
    i = _iso_class(cls)
    if not 0.5 <= size_mm <= 4000.0:
        return None
    for upper, values in _ISO_LINEAR:
        if size_mm <= upper:
            v = values[i]
            return None if v is None else Fraction(v)
    return None


def iso2768_radius(size_mm: float, cls: str = "m") -> Fraction | None:
    """The ISO 2768-1 deviation (±, millimetres) for an external radius or chamfer height."""
    i = _iso_class(cls)
    if size_mm < 0.5:
        return None
    for upper, values in _ISO_RADIUS:
        if size_mm <= upper:
            return Fraction(values[i])
    return None


def iso2768_angle_minutes(shorter_side_mm: float, cls: str = "m") -> int:
    """The ISO 2768-1 angular deviation (±, minutes of arc) by the shorter side's length."""
    i = _iso_class(cls)
    for upper, values in _ISO_ANGLE:
        if shorter_side_mm <= upper:
            return values[i]
    return _ISO_ANGLE[-1][1][i]


# --------------------------------------------------------------------------- additive processes


@dataclass(frozen=True)
class ProcessTolerance:
    """A printing process's tolerance: a fixed amount plus a rate times the size, never
    under a floor, in X and Y and separately in Z (millimetres, and millimetres per
    millimetre). Service bureau figures (10.6); Settings label them so a business
    replaces them with its own."""

    name: str
    category: str  # ISO/ASTM 52900 process category
    xy_fixed: float
    z_fixed: float
    rate: float
    floor: float = 0.0

    def tolerance_mm(self, size_mm: float, along_z: bool = False) -> float:
        """± millimetres for a size of ``size_mm``."""
        fixed = self.z_fixed if along_z else self.xy_fixed
        return max(self.floor, fixed + self.rate * abs(size_mm))


PROCESSES: dict[str, ProcessTolerance] = {
    "sla": ProcessTolerance("SLA", "vat photopolymerization", 0.002 * 25.4, 0.005 * 25.4, 0.001),
    "polyjet": ProcessTolerance("PolyJet", "material jetting", 0.005 * 25.4, 0.005 * 25.4, 0.001),
    "sls": ProcessTolerance("SLS", "powder bed fusion", 0.010 * 25.4, 0.010 * 25.4, 0.001),
    "mjf": ProcessTolerance("MJF", "powder bed fusion", 0.012 * 25.4, 0.012 * 25.4, 0.001),
    "metal": ProcessTolerance("metal powder bed", "powder bed fusion", 0.003 * 25.4, 0.003 * 25.4, 0.001),
    "fdm": ProcessTolerance("FDM", "material extrusion", 0.0, 0.0, 0.005, 0.5),
}

# --------------------------------------------------------------------------- threads


@dataclass(frozen=True)
class Thread:
    """One thread: its designation, major diameter and pitch in millimetres, and the tap
    drill and clearance (normal fit) diameters in millimetres."""

    designation: str
    unit: str  # "mm" (ISO metric coarse, B1.13M) or "in" (Unified, B1.1)
    major: float
    pitch: float
    tap_drill: float
    clearance: float

    def internal(self) -> str:
        """The designation of a tapped hole with its usual class: ``1/4-20 UNC-2B``,
        ``M6 x 1-6H``."""
        return f"{self.designation}-{'2B' if self.unit == 'in' else '6H'}"


def _unified(name: str, major_in: float, tpi: int, drill_in: float, clear_in: float) -> Thread:
    return Thread(name, "in", major_in * 25.4, 25.4 / tpi, drill_in * 25.4, clear_in * 25.4)


# Metric coarse M3 to M16 (ISO 261 and 262), tap drills as major less pitch (practice) and
# ISO 273 medium clearance holes.
METRIC_COARSE: tuple[Thread, ...] = (
    Thread("M3 x 0.5", "mm", 3.0, 0.5, 2.5, 3.4),
    Thread("M4 x 0.7", "mm", 4.0, 0.7, 3.3, 4.5),
    Thread("M5 x 0.8", "mm", 5.0, 0.8, 4.2, 5.5),
    Thread("M6 x 1", "mm", 6.0, 1.0, 5.0, 6.6),
    Thread("M8 x 1.25", "mm", 8.0, 1.25, 6.8, 9.0),
    Thread("M10 x 1.5", "mm", 10.0, 1.5, 8.5, 11.0),
    Thread("M12 x 1.75", "mm", 12.0, 1.75, 10.2, 13.5),
    Thread("M14 x 2", "mm", 14.0, 2.0, 12.0, 15.5),
    Thread("M16 x 2", "mm", 16.0, 2.0, 14.0, 17.5),
)

# Unified coarse and fine, #4 to 1/2 (B1.1), tap drills for about 75 % thread and close-fit
# clearance drills (practice).
UNIFIED: tuple[Thread, ...] = (
    _unified("#4-40 UNC", 0.112, 40, 0.0890, 0.1160),
    _unified("#4-48 UNF", 0.112, 48, 0.0935, 0.1160),
    _unified("#6-32 UNC", 0.138, 32, 0.1065, 0.1440),
    _unified("#6-40 UNF", 0.138, 40, 0.1130, 0.1440),
    _unified("#8-32 UNC", 0.164, 32, 0.1360, 0.1695),
    _unified("#8-36 UNF", 0.164, 36, 0.1360, 0.1695),
    _unified("#10-24 UNC", 0.190, 24, 0.1495, 0.1960),
    _unified("#10-32 UNF", 0.190, 32, 0.1590, 0.1960),
    _unified("1/4-20 UNC", 0.250, 20, 0.2010, 0.2570),
    _unified("1/4-28 UNF", 0.250, 28, 0.2130, 0.2570),
    _unified("5/16-18 UNC", 0.3125, 18, 0.2570, 0.3230),
    _unified("5/16-24 UNF", 0.3125, 24, 0.2720, 0.3230),
    _unified("3/8-16 UNC", 0.375, 16, 0.3125, 0.3860),
    _unified("3/8-24 UNF", 0.375, 24, 0.3320, 0.3860),
    _unified("7/16-14 UNC", 0.4375, 14, 0.3680, 0.4531),
    _unified("7/16-20 UNF", 0.4375, 20, 0.3906, 0.4531),
    _unified("1/2-13 UNC", 0.500, 13, 0.4219, 0.5156),
    _unified("1/2-20 UNF", 0.500, 20, 0.4531, 0.5156),
)
THREADS = METRIC_COARSE + UNIFIED
TAP_DRILL_MATCH_MM = 0.01  # a hole matches a tap drill within this (23)


def threads_for_drill(diameter_m: float) -> tuple[Thread, ...]:
    """The threads whose tap drill is ``diameter_m`` within 0.01 mm: candidates only, a
    person confirms a thread (22 rule 7)."""
    d = diameter_m * 1000.0
    return tuple(t for t in THREADS if abs(t.tap_drill - d) <= TAP_DRILL_MATCH_MM + 1e-9)


def clearance_for(diameter_m: float) -> tuple[Thread, ...]:
    """The threads whose clearance hole is ``diameter_m`` within 0.01 mm."""
    d = diameter_m * 1000.0
    return tuple(t for t in THREADS if abs(t.clearance - d) <= TAP_DRILL_MATCH_MM + 1e-9)


def thread_depth_suggestion(drill_depth_m: float, thread: Thread) -> float:
    """The suggested thread depth in metres: the drill depth less three pitches, rounded
    down to the unit's step (0.5 mm, or 1/32 in), never below one pitch (10.9)."""
    depth_mm = drill_depth_m * 1000.0 - 3 * thread.pitch
    step = 0.5 if thread.unit == "mm" else 25.4 / 32
    depth_mm = int(depth_mm / step + 1e-9) * step
    return max(depth_mm, thread.pitch) / 1000.0


# --------------------------------------------------------------------------- revisions

REVISION_SKIP = frozenset("IOQSXZ")
_REVISION_LETTERS = tuple(c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if c not in REVISION_SKIP)


def revision_letters(count: int, first: str = "A") -> list[str]:
    """``count`` revision marks from ``first``: A, B, ... skipping I, O, Q, S, X and Z;
    after Y comes AA, then AB (Y14.35 as publicly summarised; verify)."""
    out, mark = [], first
    for _ in range(count):
        out.append(mark)
        mark = next_revision(mark)
    return out


def next_revision(mark: str) -> str:
    """The mark after ``mark``: B after A, AA after Y, AB after AA, BA after AY."""
    if not is_revision(mark):
        raise InvalidArgumentError(f"{mark!r} is not a revision mark", detail={"parameter": "mark"})
    digits = [_REVISION_LETTERS.index(c) for c in mark]
    i = len(digits) - 1
    while i >= 0:
        if digits[i] + 1 < len(_REVISION_LETTERS):
            digits[i] += 1
            return "".join(_REVISION_LETTERS[d] for d in digits)
        digits[i] = 0
        i -= 1
    return _REVISION_LETTERS[0] + "".join(_REVISION_LETTERS[d] for d in digits)


def is_revision(mark: str) -> bool:
    """Whether ``mark`` is one to four letters of the sequence."""
    return isinstance(mark, str) and 1 <= len(mark) <= 4 and all(c in _REVISION_LETTERS for c in mark)


VIEW_LETTER_SKIP = frozenset("IOQX")


def view_letters():
    """Section and detail letters: A, B, ... without I, O, Q or X (22 rule 12); after Z,
    AA, AB and on. Never reused within a drawing; the caller keeps the used ones."""
    single = [c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if c not in VIEW_LETTER_SKIP]
    yield from single
    for a in single:
        for b in single:
            yield a + b


# --------------------------------------------------------------------------- GD&T


@dataclass(frozen=True)
class Characteristic:
    """One geometric characteristic: its name, kind, whether it takes datums, and the
    Unicode code point used where a font has it (the PDF draws it as a path)."""

    name: str
    kind: str  # form, orientation, location, runout, profile
    datums: str  # "never", "optional" or "required"
    symbol: str


CHARACTERISTICS: dict[str, Characteristic] = {
    "straightness": Characteristic("straightness", "form", "never", "⏤"),
    "flatness": Characteristic("flatness", "form", "never", "⏥"),
    "circularity": Characteristic("circularity", "form", "never", "○"),
    "cylindricity": Characteristic("cylindricity", "form", "never", "⌭"),
    "profile_line": Characteristic("profile of a line", "profile", "optional", "⌒"),
    "profile_surface": Characteristic("profile of a surface", "profile", "optional", "⌓"),
    "angularity": Characteristic("angularity", "orientation", "required", "∠"),
    "perpendicularity": Characteristic("perpendicularity", "orientation", "required", "⟂"),
    "parallelism": Characteristic("parallelism", "orientation", "required", "∥"),
    "position": Characteristic("position", "location", "optional", "⌖"),
    "circular_runout": Characteristic("circular runout", "runout", "required", "↗"),
    "total_runout": Characteristic("total runout", "runout", "required", "⌰"),
}
MODIFIERS = {"mmc": "Ⓜ", "lmc": "Ⓛ", "diameter": "Ø"}

# Symbols in callouts and dimensions (Y14.5): WinAnsi has Ø, ±, ° and ×; the rest are paths.
SYMBOL_DIAMETER = "Ø"
SYMBOL_PLUS_MINUS = "±"
SYMBOL_DEGREE = "°"
SYMBOL_TIMES = "×"
SYMBOL_COUNTERBORE = "⌴"
SYMBOL_COUNTERSINK = "⌵"
SYMBOL_DEPTH = "↧"
# Words for readers whose fonts lack the symbols (a Settings choice, 10.9).
SYMBOL_WORDS = {SYMBOL_COUNTERBORE: "CBORE", SYMBOL_COUNTERSINK: "CSK", SYMBOL_DEPTH: "DEEP"}

__all__ = [
    "ANGLES",
    "ANGLE_BLOCK",
    "BASIC_MAX_PLACES",
    "CHARACTERISTICS",
    "DIMENSIONS",
    "INCH",
    "INCH_BLOCK",
    "INTERPRETATION",
    "INTERPRETATIONS",
    "INTERPRETATION_KEYS",
    "PLUS_MINUS_SOURCE",
    "PROFILES",
    "STANDARD_ANGLE",
    "ISO2768_CLASSES",
    "LINES",
    "LINE_STYLES",
    "METRIC_COARSE",
    "MM_BLOCK",
    "MODIFIERS",
    "PROCESSES",
    "REVISION_SKIP",
    "SCALES",
    "SHEETS",
    "SHEET_ORDER",
    "SYMBOL_COUNTERBORE",
    "SYMBOL_COUNTERSINK",
    "SYMBOL_DEGREE",
    "SYMBOL_DEPTH",
    "SYMBOL_DIAMETER",
    "SYMBOL_PLUS_MINUS",
    "SYMBOL_TIMES",
    "SYMBOL_WORDS",
    "TEXT",
    "THREADS",
    "UNIFIED",
    "VIEW_LETTER_SKIP",
    "BlockRow",
    "Characteristic",
    "DimensionPreset",
    "LineStyle",
    "ProcessTolerance",
    "Sheet",
    "TextPreset",
    "Thread",
    "clearance_for",
    "is_revision",
    "iso2768_angle_minutes",
    "iso2768_linear",
    "iso2768_radius",
    "interpretation",
    "next_revision",
    "parse_scale",
    "profile_of",
    "projection",
    "revision_letters",
    "scale_factor",
    "scale_text",
    "thread_depth_suggestion",
    "threads_for_drill",
    "view_letters",
]
