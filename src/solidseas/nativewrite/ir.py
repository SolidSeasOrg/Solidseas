"""``ParametricDocumentIR``: a CAD system's parametric part, independent of SOLIDWORKS and of the source.

A source adapter (:mod:`.solidcraft` is the first) fills it; a writer reads it.
It keeps design intent, not geometry: sketches with their points, curves,
geometric constraints and driving dimensions, and features with their
parameters, in timeline order. It is plain data: :func:`to_json` and
:func:`from_json` round-trip it, and :func:`validate` checks it with no CAD
system present.

Units are SI everywhere: lengths in metres, angles in radians. A sketch's
coordinates are in its plane's frame (``origin`` plus ``x_dir`` and ``y_dir``
in model coordinates, right-handed, the normal being ``x_dir`` x ``y_dir``).

A source feature the IR cannot hold faithfully becomes an
:class:`Unsupported` entry in the timeline, with the reason. Writers must
refuse a document that has one rather than leave the feature out, unless the
caller asked for a partial document and says so to the user.

``docs/NATIVE_SLDPRT_WRITER.md`` section 8 is the schema in prose.
"""

import datetime
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any

FORMAT = "solidseas-parametric-ir/1"

PLANES = {
    # The three base planes as model frames: (origin, x_dir, y_dir).
    "xy": ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
    "xz": ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, -1.0)),
    "yz": ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
}
CURVES = ("line", "circle", "arc")
CONSTRAINTS = {
    # kind: (number of point refs, number of curve refs)
    "coincident": (2, 0),
    "horizontal": (0, 1),
    "vertical": (0, 1),
    "horizontal_points": (2, 0),
    "vertical_points": (2, 0),
    "parallel": (0, 2),
    "perpendicular": (0, 2),
    "collinear": (0, 2),
    "tangent": (0, 2),
    "equal": (0, 2),
    "concentric": (0, 2),
    "midpoint": (1, 1),
    "point_on_curve": (1, 1),
    "symmetric": (2, 1),
    "fix": (1, 0),
}
DIMENSIONS = {
    "length": (0, 1),
    "distance": (2, 0),
    "distance_x": (2, 0),
    "distance_y": (2, 0),
    "point_line_distance": (1, 1),
    "radius": (0, 1),
    "diameter": (0, 1),
    "angle": (0, 2),
}
ANGLE_DIMENSIONS = ("angle",)
OPERATIONS = ("new_body", "join", "cut")
DIRECTIONS = ("forward", "reverse", "midplane")
ENDS = ("blind", "through_all")
PROPERTY_TYPES = ("text", "number", "date", "yesno")
ORIGIN = "origin"  # every sketch's origin point id, never listed in points
MAX_ITEMS = 100_000


class IRError(ValueError):
    """The document is not a valid ParametricDocumentIR."""


@dataclass
class Parameter:
    name: str
    value: float  # SI
    unit: str = "length"  # length, angle or number
    expression: str | None = None  # the source's own text, kept for a writer that can carry equations
    driving: bool = True


@dataclass
class Property:
    """A file custom property: what a part number or a description is kept in.

    ``value`` is a ``str`` for text, an ``int`` or ``float`` for a number, a
    ``YYYY-MM-DD`` ``str`` for a date and a ``bool`` for yes or no.
    """

    name: str
    value: str | float | bool
    type: str = "text"  # text, number, date or yesno


@dataclass
class Point:
    id: str
    x: float
    y: float
    construction: bool = False


@dataclass
class Curve:
    id: str
    kind: str  # line (points a, b), circle (center, radius), arc (center, a, b, counter-clockwise a to b)
    points: list[str]
    radius: float | None = None
    construction: bool = False


@dataclass
class Constraint:
    id: str
    kind: str
    points: list[str] = field(default_factory=list)
    curves: list[str] = field(default_factory=list)


@dataclass
class Dimension:
    id: str
    kind: str
    value: float  # SI
    points: list[str] = field(default_factory=list)
    curves: list[str] = field(default_factory=list)
    parameter: str | None = None  # the Parameter that drives it
    driven: bool = False  # a reference dimension


@dataclass
class Plane:
    origin: tuple[float, float, float]
    x_dir: tuple[float, float, float]
    y_dir: tuple[float, float, float]
    base: str | None = None  # "xy", "xz" or "yz" when it is one of the base planes
    parent: str | None = None  # a base plane this one is offset from, along its normal
    offset: float | None = None  # that distance, metres
    face_point: tuple[float, float, float] | None = None  # on a face of an earlier feature: a point on it
    face_name: str | None = None  # the source's persistent name for that face

    @classmethod
    def named(cls, base: str) -> "Plane":
        o, x, y = PLANES[base]
        return cls(o, x, y, base)


@dataclass
class Sketch:
    id: str
    name: str
    plane: Plane
    points: list[Point] = field(default_factory=list)
    curves: list[Curve] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)
    dimensions: list[Dimension] = field(default_factory=list)
    suppressed: bool = False
    type: str = "sketch"


@dataclass
class Extrude:
    id: str
    name: str
    sketch: str
    depth: float  # SI, along the direction; for midplane, the total
    operation: str = "new_body"
    direction: str = "forward"
    end: str = "blind"
    profile: list[list[str]] | None = None  # closed loops of curve ids; None: every closed region
    depth_parameter: str | None = None
    suppressed: bool = False
    type: str = "extrude"


@dataclass
class Axis:
    """A revolve axis: a line of the sketch, the sketch's x or y axis, or a line in model space."""

    kind: str  # sketch_line, sketch_x, sketch_y, model
    curve: str | None = None  # sketch_line
    origin: tuple[float, float, float] | None = None  # model
    direction: tuple[float, float, float] | None = None  # model


@dataclass
class Revolve:
    id: str
    name: str
    sketch: str
    axis: Axis
    angle: float  # radians; for midplane, the total
    operation: str = "new_body"
    direction: str = "forward"  # forward, reverse, midplane
    profile: list[list[str]] | None = None
    angle_parameter: str | None = None
    suppressed: bool = False
    type: str = "revolve"


@dataclass
class EdgeRef:
    """An edge of an earlier feature's result, found again by a point on it (model metres).

    ``name`` is the source's persistent name for it when it has one, kept so a
    writer with the source's topology can match it exactly; the point is what
    any writer can use.
    """

    point: tuple[float, float, float]
    name: str | None = None


@dataclass
class Fillet:
    id: str
    name: str
    edges: list[EdgeRef]
    radius: float
    radius_parameter: str | None = None
    suppressed: bool = False
    type: str = "fillet"


@dataclass
class Chamfer:
    id: str
    name: str
    edges: list[EdgeRef]
    distance: float
    distance2: float | None = None  # two distances
    angle: float | None = None  # distance and angle (radians)
    distance_parameter: str | None = None
    suppressed: bool = False
    type: str = "chamfer"


@dataclass
class Hole:
    id: str
    name: str
    positions: list[tuple[float, float, float]]  # on the face, model metres
    direction: tuple[float, float, float]  # into the material
    diameter: float
    depth: float | None = None  # None: through all
    kind: str = "simple"  # simple, counterbore, countersink
    cb_diameter: float | None = None
    cb_depth: float | None = None
    cs_diameter: float | None = None
    cs_angle: float | None = None
    suppressed: bool = False
    type: str = "hole"


@dataclass
class Pattern:
    id: str
    name: str
    features: list[str]  # ids of the features copied
    kind: str  # linear, circular
    direction1: tuple[float, float, float] | None = None
    count1: int = 1
    spacing1: float = 0.0
    direction2: tuple[float, float, float] | None = None
    count2: int = 1
    spacing2: float = 0.0
    origin: tuple[float, float, float] | None = None  # circular
    axis: tuple[float, float, float] | None = None  # circular
    angle: float = 2 * math.pi  # circular, the total
    suppressed: bool = False
    type: str = "pattern"


@dataclass
class Mirror:
    id: str
    name: str
    features: list[str]
    plane: Plane
    suppressed: bool = False
    type: str = "mirror"


@dataclass
class Unsupported:
    id: str
    name: str
    source_type: str
    reason: str
    type: str = "unsupported"


Feature = Sketch | Extrude | Revolve | Fillet | Chamfer | Hole | Pattern | Mirror | Unsupported
AXES = ("sketch_line", "sketch_x", "sketch_y", "model")
HOLES = ("simple", "counterbore", "countersink")
PATTERNS = ("linear", "circular")


@dataclass
class Document:
    name: str
    features: list[Feature] = field(default_factory=list)
    parameters: list[Parameter] = field(default_factory=list)
    properties: list[Property] = field(default_factory=list)  # file custom properties, in order
    source: dict[str, Any] = field(default_factory=dict)  # system, format, file: provenance only
    format: str = FORMAT

    def feature(self, fid: str) -> Feature:
        for f in self.features:
            if f.id == fid:
                return f
        raise KeyError(fid)

    @property
    def unsupported(self) -> list[Unsupported]:
        return [f for f in self.features if isinstance(f, Unsupported)]


# ------------------------------------------------------------------ validation
def _finite(v: Any, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise IRError(f"{what}: {v!r} is not a finite number")
    return float(v)


def _unit_vector(v, what: str) -> None:
    if len(v) != 3:
        raise IRError(f"{what}: needs three components")
    n = math.sqrt(sum(_finite(c, what) ** 2 for c in v))
    if abs(n - 1) > 1e-9:
        raise IRError(f"{what}: not a unit vector")


def _validate_sketch(s: Sketch) -> None:
    p = s.plane
    for v, w in ((p.x_dir, "x_dir"), (p.y_dir, "y_dir")):
        _unit_vector(v, f"{s.id}.plane.{w}")
    if abs(sum(a * b for a, b in zip(p.x_dir, p.y_dir, strict=True))) > 1e-9:
        raise IRError(f"{s.id}.plane: x_dir and y_dir are not perpendicular")
    if p.base is not None and p.base not in PLANES:
        raise IRError(f"{s.id}.plane.base: {p.base!r}")
    points = {ORIGIN}
    for pt in s.points:
        if pt.id in points:
            raise IRError(f"{s.id}: point id {pt.id!r} repeated")
        _finite(pt.x, pt.id)
        _finite(pt.y, pt.id)
        points.add(pt.id)
    curves = set()
    for c in s.curves:
        if c.id in curves or c.id in points:
            raise IRError(f"{s.id}: curve id {c.id!r} repeated")
        if c.kind not in CURVES:
            raise IRError(f"{s.id}.{c.id}: curve kind {c.kind!r}")
        want = {"line": 2, "circle": 1, "arc": 3}[c.kind]
        if len(c.points) != want or any(q not in points for q in c.points):
            raise IRError(f"{s.id}.{c.id}: a {c.kind} takes {want} points of this sketch")
        if c.kind == "line" and c.points[0] == c.points[1]:
            raise IRError(f"{s.id}.{c.id}: a line from a point to itself")
        if c.kind == "circle" and not (c.radius is not None and _finite(c.radius, c.id) > 0):
            raise IRError(f"{s.id}.{c.id}: a circle needs a positive radius")
        curves.add(c.id)
    for group, vocab in ((s.constraints, CONSTRAINTS), (s.dimensions, DIMENSIONS)):
        for k in group:
            if k.kind not in vocab:
                raise IRError(f"{s.id}.{k.id}: unknown kind {k.kind!r}")
            np_, nc = vocab[k.kind]
            if len(k.points) != np_ or len(k.curves) != nc:
                raise IRError(f"{s.id}.{k.id}: {k.kind} takes {np_} points and {nc} curves")
            if any(q not in points for q in k.points) or any(q not in curves for q in k.curves):
                raise IRError(f"{s.id}.{k.id}: refers to something not in the sketch")
    for d in s.dimensions:
        v = _finite(d.value, d.id)
        if d.kind not in ANGLE_DIMENSIONS and v < 0:
            raise IRError(f"{s.id}.{d.id}: a length dimension is not negative")


def _validate_properties(props: list[Property]) -> None:
    seen = set()
    for p in props:
        if not isinstance(p.name, str) or not p.name.strip():
            raise IRError(f"property {p.name!r}: needs a name")
        if p.name.casefold() in seen:
            raise IRError(f"property {p.name!r} repeated")
        seen.add(p.name.casefold())
        if p.type not in PROPERTY_TYPES:
            raise IRError(f"property {p.name!r}: type {p.type!r}")
        v = p.value
        if p.type == "text" and not isinstance(v, str):
            raise IRError(f"property {p.name!r}: a text property needs a string")
        if p.type == "number":
            _finite(v, f"property {p.name!r}")
        if p.type == "yesno" and not isinstance(v, bool):
            raise IRError(f"property {p.name!r}: a yes or no property needs true or false")
        if p.type == "date":
            try:
                datetime.date.fromisoformat(v if isinstance(v, str) and len(v) == 10 else "")
            except ValueError:
                raise IRError(f"property {p.name!r}: a date needs YYYY-MM-DD") from None


def validate(doc: Document) -> Document:
    """Raise :class:`IRError` unless ``doc`` is well formed; return it."""
    if doc.format != FORMAT:
        raise IRError(f"format {doc.format!r}, this reader takes {FORMAT}")
    if max(len(doc.features), len(doc.parameters), len(doc.properties)) > MAX_ITEMS:
        raise IRError("too many items")
    names = set()
    for prm in doc.parameters:
        if prm.name in names:
            raise IRError(f"parameter {prm.name!r} repeated")
        if prm.unit not in ("length", "angle", "number"):
            raise IRError(f"parameter {prm.name!r}: unit {prm.unit!r}")
        _finite(prm.value, prm.name)
        names.add(prm.name)
    _validate_properties(doc.properties)
    ids: dict[str, Feature] = {}
    for f in doc.features:
        if not f.id or f.id in ids:
            raise IRError(f"feature id {f.id!r} empty or repeated")
        if isinstance(f, Sketch):
            _validate_sketch(f)
            for d in f.dimensions:
                if d.parameter is not None and d.parameter not in names:
                    raise IRError(f"{f.id}.{d.id}: no parameter {d.parameter!r}")
        elif isinstance(f, Extrude):
            sk = ids.get(f.sketch)
            if not isinstance(sk, Sketch):
                raise IRError(f"{f.id}: sketch {f.sketch!r} is not an earlier sketch")
            if f.operation not in OPERATIONS or f.direction not in DIRECTIONS or f.end not in ENDS:
                raise IRError(f"{f.id}: operation, direction or end not in the vocabulary")
            if f.end == "blind" and not _finite(f.depth, f.id) > 0:
                raise IRError(f"{f.id}: a blind extrusion needs a positive depth")
            if f.depth_parameter is not None and f.depth_parameter not in names:
                raise IRError(f"{f.id}: no parameter {f.depth_parameter!r}")
            if f.profile is not None:
                known = {c.id for c in sk.curves}
                for loop in f.profile:
                    if not loop or any(c not in known for c in loop):
                        raise IRError(f"{f.id}: a profile loop names curves not in {sk.id}")
        elif isinstance(f, Revolve):
            sk = ids.get(f.sketch)
            if not isinstance(sk, Sketch):
                raise IRError(f"{f.id}: sketch {f.sketch!r} is not an earlier sketch")
            if f.axis.kind not in AXES or f.operation not in OPERATIONS or f.direction not in DIRECTIONS:
                raise IRError(f"{f.id}: axis, operation or direction not in the vocabulary")
            if f.axis.kind == "sketch_line" and f.axis.curve not in {c.id for c in sk.curves}:
                raise IRError(f"{f.id}: axis line {f.axis.curve!r} is not in {sk.id}")
            if f.axis.kind == "model":
                _unit_vector(f.axis.direction or (), f"{f.id}.axis")
            if not 0 < _finite(f.angle, f.id) <= 2 * math.pi + 1e-12:
                raise IRError(f"{f.id}: angle outside (0, 360] degrees")
        elif isinstance(f, (Fillet, Chamfer)):
            size = f.radius if isinstance(f, Fillet) else f.distance
            if not f.edges or not _finite(size, f.id) > 0:
                raise IRError(f"{f.id}: needs edges and a positive size")
            for e in f.edges:
                for c in e.point:
                    _finite(c, f.id)
        elif isinstance(f, Hole):
            if f.kind not in HOLES or not f.positions or not _finite(f.diameter, f.id) > 0:
                raise IRError(f"{f.id}: kind, positions or diameter")
            _unit_vector(f.direction, f"{f.id}.direction")
            if f.depth is not None and not _finite(f.depth, f.id) > 0:
                raise IRError(f"{f.id}: a blind hole needs a positive depth")
        elif isinstance(f, (Pattern, Mirror)):
            if not f.features or any(x not in ids for x in f.features):
                raise IRError(f"{f.id}: copies features that are not earlier ones")
            if isinstance(f, Pattern):
                if f.kind not in PATTERNS or f.count1 < 1 or f.count2 < 1:
                    raise IRError(f"{f.id}: kind or counts")
                if f.kind == "linear":
                    _unit_vector(f.direction1 or (), f"{f.id}.direction1")
                else:
                    _unit_vector(f.axis or (), f"{f.id}.axis")
        elif not isinstance(f, Unsupported):
            raise IRError(f"{f.id}: not a feature type of this IR")
        ids[f.id] = f
    return doc


# ------------------------------------------------------------------ JSON
def to_json(doc: Document) -> str:
    return json.dumps(asdict(validate(doc)), indent=2, sort_keys=False)


def _plane(d: dict) -> Plane:
    fp = d.get("face_point")
    return Plane(
        tuple(d["origin"]),
        tuple(d["x_dir"]),
        tuple(d["y_dir"]),
        d.get("base"),
        d.get("parent"),
        d.get("offset"),
        tuple(fp) if fp is not None else None,
        d.get("face_name"),
    )


def _feature(d: dict) -> Feature:
    t = d.get("type")
    if t == "sketch":
        return Sketch(
            id=d["id"],
            name=d["name"],
            plane=_plane(d["plane"]),
            points=[Point(**p) for p in d.get("points", [])],
            curves=[Curve(**c) for c in d.get("curves", [])],
            constraints=[Constraint(**c) for c in d.get("constraints", [])],
            dimensions=[Dimension(**x) for x in d.get("dimensions", [])],
            suppressed=d.get("suppressed", False),
        )
    if t == "extrude":
        return Extrude(**{k: v for k, v in d.items() if k != "type"})
    if t == "unsupported":
        return Unsupported(**{k: v for k, v in d.items() if k != "type"})
    rest = {k: v for k, v in d.items() if k != "type"}
    if t == "revolve":
        ax = dict(rest["axis"])
        for k in ("origin", "direction"):
            if ax.get(k) is not None:
                ax[k] = tuple(ax[k])
        return Revolve(**{**rest, "axis": Axis(**ax)})
    if t in ("fillet", "chamfer"):
        cls = Fillet if t == "fillet" else Chamfer
        return cls(**{**rest, "edges": [EdgeRef(tuple(e["point"]), e.get("name")) for e in rest["edges"]]})
    if t == "hole":
        return Hole(
            **{
                **rest,
                "positions": [tuple(p) for p in rest["positions"]],
                "direction": tuple(rest["direction"]),
            }
        )
    if t == "pattern":
        for k in ("direction1", "direction2", "origin", "axis"):
            if rest.get(k) is not None:
                rest[k] = tuple(rest[k])
        return Pattern(**rest)
    if t == "mirror":
        return Mirror(**{**rest, "plane": _plane(rest["plane"])})
    raise IRError(f"feature type {t!r}")


def from_json(text: str | bytes) -> Document:
    try:
        d = json.loads(text)
        doc = Document(
            name=d["name"],
            features=[_feature(f) for f in d.get("features", [])],
            parameters=[Parameter(**p) for p in d.get("parameters", [])],
            properties=[Property(**p) for p in d.get("properties", [])],
            source=d.get("source", {}),
            format=d.get("format", ""),
        )
    except (KeyError, TypeError, ValueError) as e:
        if isinstance(e, IRError):
            raise
        raise IRError(f"not an IR document: {e}") from e
    return validate(doc)
