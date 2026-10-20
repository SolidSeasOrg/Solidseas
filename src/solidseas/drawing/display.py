"""The display list and the painted layer (``docs/DRAWINGS.md`` 6.7).

Plain dataclasses, no Qt and no I/O, in sheet millimetres with the origin at the
sheet's lower left and y up. Three layers:

- **Geometry** (:class:`Segment`, :class:`Arc`, :class:`EllipseArc`,
  :class:`Spline`, :class:`Polyline`), each with its ``style`` and ``src``. Model
  geometry reaches the sheet through its view's :class:`ViewPlacement`.
- **Annotations**, semantic, before layout: dimensions, centre marks and lines,
  notes, labels, datum symbols, frames, stamps, and the sheet's furniture.
- **The painted layer** layout makes of them: :class:`Stroke`, :class:`Fill`,
  :class:`TextRun` and :class:`ImageRun`, each with its owner and layer. PDF, SVG
  and the screen draw only this layer, so they agree; the DXF writer reads the
  semantic layer and replays a dimension's painted items into its block.

:func:`to_compact` and :func:`from_compact` turn a :class:`Sheet` into the
``.ssdrw``'s compact ``sheet`` member and back: lengths in integer micrometres,
every item a list led by its tag, so a released drawing reproduces exactly. A
drawing of several sheets is one compact member: the first sheet, holding the others
in its ``continuation`` (:func:`sheets_of` lists them all).
"""

from __future__ import annotations

import base64
import math
from dataclasses import dataclass, fields, is_dataclass
from typing import Any

from ..errors import InvalidArgumentError

Point = tuple[float, float]

LAYERS = (
    "visible",
    "hidden",
    "tangent",
    "centre",
    "phantom",
    "hatch",
    "border",
    "dimensions",
    "notes",
    "title",
    "stamp",
)
# What a geometry style is painted on (the PDF's optional content groups, the DXF's layers).
STYLE_LAYER = {
    "visible": "visible",
    "hidden": "hidden",
    "tangent": "tangent",
    "centre": "centre",
    "phantom": "phantom",
    "border": "border",
    "thin": "visible",
}


@dataclass(frozen=True)
class Src:
    """Where a piece of geometry comes from: body index, the edge's or face's signature
    and the view id, so the editor can pick the feature."""

    body: int = 0
    signature: str = ""
    view: str = ""


# --------------------------------------------------------------------------- geometry


@dataclass(frozen=True)
class Segment:
    p0: Point
    p1: Point
    style: str = "visible"
    src: Src = Src()

    def bounds(self) -> tuple[float, float, float, float]:
        return _box([self.p0, self.p1])


@dataclass(frozen=True)
class Arc:
    """A circle or circular arc counter-clockwise from ``start_deg`` to ``end_deg``; a
    full circle when they differ by 360."""

    centre: Point
    radius: float
    start_deg: float = 0.0
    end_deg: float = 360.0
    style: str = "visible"
    src: Src = Src()

    def sweep(self) -> float:
        s = (self.end_deg - self.start_deg) % 360.0
        return 360.0 if s == 0.0 and self.end_deg != self.start_deg else s

    def bounds(self) -> tuple[float, float, float, float]:
        pts = [self.point(self.start_deg), self.point(self.start_deg + self.sweep())]
        for q in range(0, 720, 90):
            if 0.0 < (q - self.start_deg) % 360.0 < self.sweep() or self.sweep() >= 360.0:
                pts.append(self.point(q))
        return _box(pts)

    def point(self, deg: float) -> Point:
        a = math.radians(deg)
        return (self.centre[0] + self.radius * math.cos(a), self.centre[1] + self.radius * math.sin(a))


@dataclass(frozen=True)
class EllipseArc:
    """An ellipse arc: ``centre``, the major semi-axis as a vector, the minor to major
    ``ratio``, and parameters ``t0`` to ``t1`` (radians, counter-clockwise), as DXF
    ELLIPSE has them."""

    centre: Point
    major: Point
    ratio: float
    t0: float = 0.0
    t1: float = 2.0 * math.pi
    style: str = "visible"
    src: Src = Src()

    def point(self, t: float) -> Point:
        mx, my = self.major
        nx, ny = -my * self.ratio, mx * self.ratio
        c, s = math.cos(t), math.sin(t)
        return (self.centre[0] + mx * c + nx * s, self.centre[1] + my * c + ny * s)

    def bounds(self) -> tuple[float, float, float, float]:
        n = 64
        span = self.t1 - self.t0
        return _box([self.point(self.t0 + span * k / n) for k in range(n + 1)])


@dataclass(frozen=True)
class Spline:
    """A B-spline: ``degree``, ``knots``, control ``points`` and ``weights`` (None when
    not rational). An orthographic projection is affine, so the projected control
    points give the exact projected curve."""

    degree: int
    knots: tuple[float, ...]
    points: tuple[Point, ...]
    weights: tuple[float, ...] | None = None
    style: str = "visible"
    src: Src = Src()

    def __post_init__(self) -> None:
        if not isinstance(self.degree, int) or self.degree < 1:
            raise InvalidArgumentError("a spline's degree must be 1 or more", detail={"parameter": "degree"})
        if len(self.knots) != len(self.points) + self.degree + 1:
            raise InvalidArgumentError(
                "a spline needs points + degree + 1 knots", detail={"parameter": "knots"}
            )
        if self.weights is not None and len(self.weights) != len(self.points):
            raise InvalidArgumentError("a spline needs one weight a point", detail={"parameter": "weights"})

    def bounds(self) -> tuple[float, float, float, float]:
        return _box(list(self.points))  # the control polygon holds the curve


@dataclass(frozen=True)
class Polyline:
    points: tuple[Point, ...]
    closed: bool = False
    style: str = "visible"
    src: Src = Src()

    def bounds(self) -> tuple[float, float, float, float]:
        return _box(list(self.points))


GEOMETRY = (Segment, Arc, EllipseArc, Spline, Polyline)


def _box(pts) -> tuple[float, float, float, float]:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


@dataclass(frozen=True)
class ViewPlacement:
    """Where a view sits on the sheet: model geometry in view coordinates (metres) maps
    to the sheet as ``origin + scale * 1000 * (x, y)``; ``scale`` is sheet mm per model
    mm (0.5 at 1:2)."""

    view: str
    origin: Point
    scale: float
    label: str = ""

    def to_sheet(self, p: Point) -> Point:
        k = self.scale * 1000.0
        return (self.origin[0] + k * p[0], self.origin[1] + k * p[1])

    def to_view(self, p: Point) -> Point:
        k = self.scale * 1000.0
        return ((p[0] - self.origin[0]) / k, (p[1] - self.origin[1]) / k)


def place(item, placement: ViewPlacement):
    """A geometry primitive in view metres moved onto the sheet by ``placement``."""
    k = placement.scale * 1000.0
    f = placement.to_sheet
    if isinstance(item, Segment):
        return Segment(f(item.p0), f(item.p1), item.style, item.src)
    if isinstance(item, Arc):
        return Arc(f(item.centre), item.radius * k, item.start_deg, item.end_deg, item.style, item.src)
    if isinstance(item, EllipseArc):
        return EllipseArc(
            f(item.centre),
            (item.major[0] * k, item.major[1] * k),
            item.ratio,
            item.t0,
            item.t1,
            item.style,
            item.src,
        )
    if isinstance(item, Spline):
        return Spline(
            item.degree, item.knots, tuple(f(p) for p in item.points), item.weights, item.style, item.src
        )
    if isinstance(item, Polyline):
        return Polyline(tuple(f(p) for p in item.points), item.closed, item.style, item.src)
    raise InvalidArgumentError("not a geometry primitive", detail={"parameter": "item"})


# --------------------------------------------------------------------------- annotations


@dataclass(frozen=True)
class DimText:
    """A dimension's text, its parts kept apart so layout measures each: the prefix
    (``4X Ø``), the value, what follows it on the line (``±.005``, ``MAX``), stacked
    upper and lower parts, whether it is boxed (basic), and suffix lines (``THRU``,
    a counterbore line)."""

    value: str
    prefix: str = ""
    after: str = ""
    upper: str = ""
    lower: str = ""
    boxed: bool = False
    suffix: tuple[str, ...] = ()


@dataclass(frozen=True)
class Dimension:
    """A dimension as a DXF DIMENSION needs it: ``points`` are its definition points
    (for a linear one the two extension line origins and a point on the dimension
    line), ``text_at`` the text's middle."""

    id: str
    kind: str
    view: str
    points: tuple[Point, ...]
    text_at: Point
    value: float
    text: DimText
    angle_deg: float = 0.0  # a linear dimension's direction on the sheet
    refs: tuple[str, ...] = ()
    tolerance: str = "block"
    precision: int = 2
    flags: tuple[str, ...] = ()  # basic, reference, moved, needs_attention


@dataclass(frozen=True)
class CentreMark:
    centre: Point
    radius: float
    view: str = ""
    overshoot: float = 3.0


@dataclass(frozen=True)
class CentreLine:
    p0: Point
    p1: Point
    view: str = ""


@dataclass(frozen=True)
class FrameItem:
    """A feature control frame's cells: the characteristic's name (``position``), the
    zone text with its Ø and modifier, and the datum letters."""

    characteristic: str
    zone: str
    diameter: bool = False
    modifier: str = ""
    datums: tuple[str, ...] = ()


@dataclass(frozen=True)
class Note:
    """A note: lines of words with inline frames (C27), optionally on a leader."""

    id: str
    at: Point
    lines: tuple[tuple[str, tuple[FrameItem, ...]], ...]
    leader: tuple[Point, ...] = ()
    number: int | None = None


@dataclass(frozen=True)
class ViewLabel:
    view: str
    at: Point
    text: str
    letter: str = ""


@dataclass(frozen=True)
class DatumFeature:
    letter: str
    at: Point
    leader: tuple[Point, ...]
    view: str = ""


@dataclass(frozen=True)
class FeatureControlFrame:
    at: Point
    frame: FrameItem
    owner: str = ""


@dataclass(frozen=True)
class Stamp:
    text: str
    at: Point
    angle_deg: float = 0.0


@dataclass(frozen=True)
class PlotStamp:
    text: str
    at: Point


@dataclass(frozen=True)
class VirtualSharp:
    at: Point
    view: str = ""


@dataclass(frozen=True)
class Border:
    width: float
    height: float
    margin: float
    columns: int
    rows: int


@dataclass(frozen=True)
class TitleBlock:
    at: Point
    width: float
    height: float
    fields: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Image:
    """The logo: a narrow-form PNG (7.1) and where it goes."""

    at: Point
    width: float
    height: float
    png: bytes
    sha256: str = ""


@dataclass(frozen=True)
class ProjectionSymbol:
    at: Point
    size: float
    angle: str = "third"


@dataclass(frozen=True)
class ToleranceBlock:
    at: Point
    lines: tuple[str, ...]


@dataclass(frozen=True)
class NotesBlock:
    at: Point
    lines: tuple[str, ...]


@dataclass(frozen=True)
class PartsList:
    """An assembly's parts list: its lower left, size, the column headings and each
    line's cells, in item order (``docs/drawings/assemblies.md``)."""

    at: Point
    width: float
    height: float
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class Balloon:
    """An item balloon: the item it names, its circle, and its leader from the point
    it ends on to the circle."""

    item: str
    centre: Point
    radius: float
    leader: tuple[Point, ...]
    view: str = ""


ANNOTATIONS = (
    Dimension,
    CentreMark,
    CentreLine,
    Note,
    ViewLabel,
    DatumFeature,
    FeatureControlFrame,
    Stamp,
    PlotStamp,
    VirtualSharp,
    Border,
    TitleBlock,
    Image,
    ProjectionSymbol,
    ToleranceBlock,
    NotesBlock,
    PartsList,
    Balloon,
)

# --------------------------------------------------------------------------- the painted layer

# A path is a tuple of operations: ("M", x, y), ("L", x, y), ("C", x1, y1, x2, y2, x3, y3), ("Z",).
PathOp = tuple


@dataclass(frozen=True)
class Stroke:
    """A stroked path: width and dash pattern in millimetres, cap and join as PDF has
    them (0 butt, 1 round, 2 square), a grey level (0 black), its layer and owner."""

    path: tuple[PathOp, ...]
    width: float
    dash: tuple[float, ...] = ()
    layer: str = "visible"
    owner: str = ""
    cap: int = 0
    join: int = 0
    grey: float = 0.0


@dataclass(frozen=True)
class Fill:
    path: tuple[PathOp, ...]
    layer: str = "visible"
    owner: str = ""
    grey: float = 0.0


@dataclass(frozen=True)
class TextRun:
    """Text at (``x``, ``y``): ``size`` is the font size in millimetres (the cap height
    over 0.718), ``anchor`` where (x, y) is on the text (``left``, ``centre``,
    ``right`` on the baseline), ``width`` the measured advance."""

    x: float
    y: float
    size: float
    text: str
    angle_deg: float = 0.0
    bold: bool = False
    anchor: str = "left"
    width: float = 0.0
    layer: str = "dimensions"
    owner: str = ""


@dataclass(frozen=True)
class ImageRun:
    x: float
    y: float
    width: float
    height: float
    png: bytes
    layer: str = "title"
    owner: str = ""


PAINTED = (Stroke, Fill, TextRun, ImageRun)


@dataclass(frozen=True)
class Sheet:
    """One laid-out sheet: its size name and millimetres, the drawing's scale, the
    views' placements, the geometry already on the sheet, the annotations and the
    painted layer. The first sheet of a drawing holds the sheets that continue it in
    ``continuation`` (sheet 2 onward, each with no ``continuation`` of its own): an
    assembly's parts list too long for the first goes on there. A drawing of one
    sheet has none, and its compact form is the same as before there could be any."""

    name: str
    width: float
    height: float
    scale: tuple[int, int] = (1, 1)
    views: tuple[ViewPlacement, ...] = ()
    geometry: tuple[Any, ...] = ()
    annotations: tuple[Any, ...] = ()
    painted: tuple[Any, ...] = ()
    continuation: tuple[Sheet, ...] = ()


def sheets_of(sheet: Any) -> tuple[Sheet, ...]:
    """Every sheet of a drawing from its first: ``sheet`` and the sheets that continue
    it, in order (none for anything but a :class:`Sheet`)."""
    if not isinstance(sheet, Sheet):
        return ()
    return (sheet, *(s for s in sheet.continuation if isinstance(s, Sheet)))


# --------------------------------------------------------------------------- the compact form

_TAGS: dict[type, str] = {
    Src: "src",
    Segment: "seg",
    Arc: "arc",
    EllipseArc: "ell",
    Spline: "spl",
    Polyline: "pl",
    ViewPlacement: "view",
    DimText: "dt",
    Dimension: "dim",
    CentreMark: "cm",
    CentreLine: "cl",
    FrameItem: "fcf",
    Note: "note",
    ViewLabel: "vl",
    DatumFeature: "datum",
    FeatureControlFrame: "frame",
    Stamp: "stamp",
    PlotStamp: "plot",
    VirtualSharp: "vs",
    Border: "border",
    TitleBlock: "tb",
    Image: "img",
    ProjectionSymbol: "proj",
    ToleranceBlock: "tol",
    NotesBlock: "notes",
    PartsList: "parts",
    Balloon: "balloon",
    Stroke: "stroke",
    Fill: "fill",
    TextRun: "text",
    ImageRun: "imgrun",
    Sheet: "sheet",
}
_CLASSES = {tag: cls for cls, tag in _TAGS.items()}
# Number fields that are not sheet lengths: kept as numbers rather than micrometres.
_NOT_LENGTH = frozenset(
    {"start_deg", "end_deg", "ratio", "t0", "t1", "knots", "weights", "angle_deg", "grey", "value", "scale"}
)
_COUNTS = frozenset({"degree", "columns", "rows", "precision", "cap", "join", "number", "body"})
# Fields at the end of an item that its compact form leaves out while they hold their
# default, so that an item written before the field existed reads the same and is
# written the same: a one-sheet drawing's sheet has no ``continuation``.
_OPTIONAL_TAIL: dict[type, tuple[str, ...]] = {Sheet: ("continuation",)}
SCHEMA = "solidseas.drawing-sheet/1"
MAX_DEPTH = 32
MAX_SHEETS = 64  # the sheets one compact form holds, the first included


def _bad(message: str) -> InvalidArgumentError:
    return InvalidArgumentError(message, detail={"parameter": "sheet"})


def _enc(value: Any, length: bool) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _encode(value)
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise _bad("a sheet value must be finite")
        if length:
            return int(round(value * 1000.0))
        return value if isinstance(value, int) else float(repr(round(value, 9)))
    if isinstance(value, bytes):
        return {"b64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, tuple):
        return [_enc(v, length) for v in value]
    raise _bad(f"a sheet cannot hold a {type(value).__name__}")


def _encode(obj: Any) -> dict:
    tag = _TAGS.get(type(obj))
    if tag is None:
        raise _bad(f"a sheet cannot hold a {type(obj).__name__}")
    names = list(fields(obj))
    for name in reversed(_OPTIONAL_TAIL.get(type(obj), ())):
        if names and names[-1].name == name and getattr(obj, name) == names[-1].default:
            names.pop()
    values = [_enc(getattr(obj, f.name), f.name not in _NOT_LENGTH and f.name not in _COUNTS) for f in names]
    return {"k": tag, "v": values}


def to_compact(sheet: Sheet) -> dict[str, Any]:
    """The sheet as the ``.ssdrw``'s compact member: plain JSON values only, lengths in
    integer micrometres."""
    if not isinstance(sheet, Sheet):
        raise InvalidArgumentError("sheet must be a Sheet", detail={"parameter": "sheet"})
    return {"schema": SCHEMA, "sheet": _encode(sheet)}


def _dec(value: Any, length: bool, depth: int) -> Any:
    if depth > MAX_DEPTH:
        raise _bad("the sheet is nested too deeply")
    if isinstance(value, dict):
        if set(value) == {"k", "v"}:
            return _decode(value, depth + 1)
        if set(value) == {"b64"} and isinstance(value["b64"], str):
            try:
                return base64.b64decode(value["b64"], validate=True)
            except ValueError:
                raise _bad("the sheet holds an image that is not base64") from None
        raise _bad("the sheet holds an object it does not know")
    if isinstance(value, list):
        return tuple(_dec(v, length, depth + 1) for v in value)
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value / 1000.0 if length else value
    if isinstance(value, float):
        if not math.isfinite(value) or length:
            raise _bad("a sheet length must be a whole number of micrometres")
        return value
    raise _bad("the sheet holds a value it cannot")


def _decode(item: dict, depth: int) -> Any:
    cls = _CLASSES.get(item["k"]) if isinstance(item["k"], str) else None
    values = item["v"]
    if cls is None or not isinstance(values, list):
        raise _bad("the sheet holds an item it does not know")
    names = fields(cls)
    if not len(names) - len(_OPTIONAL_TAIL.get(cls, ())) <= len(values) <= len(names):
        raise _bad(f"a {item['k']} item has the wrong number of values")
    names = names[: len(values)]  # the optional fields left out keep their defaults
    kwargs = {
        f.name: _dec(v, f.name not in _NOT_LENGTH and f.name not in _COUNTS, depth)
        for f, v in zip(names, values, strict=True)
    }
    try:
        return cls(**kwargs)
    except (TypeError, ValueError) as exc:
        raise _bad(f"a {item['k']} item is not valid: {exc}") from None


def from_compact(data: Any) -> Sheet:
    """A sheet from its compact member; InvalidArgumentError for anything else."""
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("sheet"), dict):
        raise _bad("not a compact sheet")
    sheet = _dec(data["sheet"], True, 0)
    if not isinstance(sheet, Sheet):
        raise _bad("not a compact sheet")
    more = sheet.continuation
    if not isinstance(more, tuple) or not all(isinstance(s, Sheet) and s.continuation == () for s in more):
        raise _bad("the sheets that continue the first must be sheets of their own")
    if len(more) + 1 > MAX_SHEETS:
        raise _bad(f"a drawing has at most {MAX_SHEETS} sheets")
    return sheet


__all__ = [
    "ANNOTATIONS",
    "GEOMETRY",
    "LAYERS",
    "PAINTED",
    "SCHEMA",
    "STYLE_LAYER",
    "Arc",
    "Balloon",
    "Border",
    "CentreLine",
    "CentreMark",
    "DatumFeature",
    "DimText",
    "Dimension",
    "EllipseArc",
    "FeatureControlFrame",
    "Fill",
    "FrameItem",
    "Image",
    "ImageRun",
    "Note",
    "NotesBlock",
    "PartsList",
    "PlotStamp",
    "Polyline",
    "ProjectionSymbol",
    "Segment",
    "Sheet",
    "Spline",
    "Src",
    "Stamp",
    "Stroke",
    "TextRun",
    "TitleBlock",
    "ToleranceBlock",
    "ViewLabel",
    "ViewPlacement",
    "VirtualSharp",
    "from_compact",
    "place",
    "sheets_of",
    "to_compact",
]
