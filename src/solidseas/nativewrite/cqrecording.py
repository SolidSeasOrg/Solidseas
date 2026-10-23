"""CadQuery models as ``ParametricDocumentIR``, from a recording of how they were built.

A CadQuery model is Python code, and running it needs CadQuery. A *recording* is what that
code did, as plain data: every call made on CadQuery's ``Workplane`` while the model was
built, in order, with its arguments, the workplane it was called on and the one it returned.
:mod:`.cqrecorder` makes one in a CadQuery session; this module reads one with the standard
library only, and replays it by CadQuery's own rules (those of CadQuery 2.8) for the calls it
knows, so each sketch and feature lands in the IR where CadQuery put it:

* where a workplane is: ``Workplane`` on a named plane, or a plane given as data, with an
  origin; ``center``, ``moveTo`` and ``pushPoints``; ``faces`` with ``>X``, ``<X``, ``>Y``,
  ``<Y``, ``>Z`` or ``<Z``, then ``workplane`` with its offset, invert, origin and centre
  options; ``tag`` and ``end``;
* profiles: ``rect`` and ``circle`` at every point on the stack;
* features: ``extrude`` (blind, one way or both, joined, kept apart or cut), ``cutBlind``,
  ``cutThruAll``, ``box`` and ``hole``.

A workplane's axes must lie along the model's X, Y and Z. A sketch lies on the base plane
parallel to it (``xy``, ``xz`` or ``yz``), or on a plane offset from one. A cut through all
material (``cutThruAll``, or a ``hole`` without a depth that goes through every body in its
way) is sketched on the base plane and cut through all both ways, which removes the same
material wherever CadQuery's workplane was. A body that does not touch the bodies before it
is kept as a body of its own, as CadQuery leaves it.

Any other call, and every feature that follows one, becomes an :class:`~.ir.Unsupported`
entry that names the call and says why, as the SolidCraft adapter's untranslated features
do. Data that is not a recording, or a recording that contradicts itself, raises
:class:`RecordingError`.

Numbers are in the recording's ``units`` (CadQuery has none: millimetres unless the
recording says otherwise). No sketch dimension or relation is made: a rectangle or a circle
is its geometry, which is what the native part writer keeps today.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import ir

FORMAT = "solidseas-cadquery-recording/1"
UNITS = {"mm": 1e-3, "cm": 1e-2, "m": 1.0, "in": 0.0254}
MAX_FILE_BYTES = 16 << 20
MAX_STEPS = 10_000
MAX_VALUES = 10_000  # numbers, strings and lists in one step's arguments
MAX_DEPTH = 8  # lists in lists in an argument
MAX_TEXT = 200  # characters in a string argument
MAX_NAME = 120  # characters in the model's name
MAX_PROPERTIES = 1_000
MAX_INDEX = 4 * MAX_STEPS
TOLERANCE = 1e-4  # CadQuery's own (CQContext.tolerance), in model units: selecting faces
EPS = 1e-9  # what still counts as the same length, relative to the model's size
CALL_TEXT = 80  # characters of a call's text in a feature's name

# CadQuery 2.8's named planes (Plane.named): x direction and normal.
NAMED_PLANES = {
    "XY": ((1, 0, 0), (0, 0, 1)),
    "YZ": ((0, 1, 0), (1, 0, 0)),
    "ZX": ((0, 0, 1), (0, 1, 0)),
    "XZ": ((1, 0, 0), (0, -1, 0)),
    "YX": ((0, 1, 0), (0, 0, -1)),
    "ZY": ((0, 0, 1), (-1, 0, 0)),
    "front": ((1, 0, 0), (0, 0, 1)),
    "back": ((-1, 0, 0), (0, 0, -1)),
    "left": ((0, 0, 1), (-1, 0, 0)),
    "right": ((0, 0, -1), (1, 0, 0)),
    "top": ((1, 0, 0), (0, 1, 0)),
    "bottom": ((1, 0, 0), (0, -1, 0)),
}
BASE_FOR_AXIS = {0: "yz", 1: "xz", 2: "xy"}  # the IR's base plane across each axis
OPERATOR_SIGNS = {
    "__add__": "+", "__sub__": "-", "__and__": "&", "__or__": "|", "__mul__": "*", "__truediv__": "/",
    "__getitem__": "[]",
}  # fmt: skip
SELECTORS = {">X": (0, 1), "<X": (0, -1), ">Y": (1, 1), "<Y": (1, -1), ">Z": (2, 1), "<Z": (2, -1)}
CENTER_OPTIONS = ("ProjectedOrigin", "CenterOfMass", "CenterOfBoundBox")
UNSEEN = "works on a workplane the recording does not show being made, such as one a Sketch returns"

REQUIRED = object()
SIGNATURES: dict[str, tuple[tuple[str, Any], ...]] = {
    # CadQuery 2.8's parameters, in order, with their defaults.
    "Workplane": (("inPlane", "XY"), ("origin", (0, 0, 0)), ("obj", None)),
    "center": (("x", REQUIRED), ("y", REQUIRED)),
    "moveTo": (("x", 0), ("y", 0)),
    "pushPoints": (("pntList", REQUIRED),),
    "workplane": (("offset", 0.0), ("invert", False), ("centerOption", "ProjectedOrigin"), ("origin", None)),
    "faces": (("selector", None), ("tag", None)),
    "tag": (("name", REQUIRED),),
    "end": (("n", 1),),
    "rect": (("xLen", REQUIRED), ("yLen", REQUIRED), ("centered", True), ("forConstruction", False)),
    "circle": (("radius", REQUIRED), ("forConstruction", False)),
    "extrude": (("until", REQUIRED), ("combine", True), ("clean", True), ("both", False), ("taper", None)),
    "cutBlind": (("until", REQUIRED), ("clean", True), ("both", False), ("taper", None)),
    "cutThruAll": (("clean", True), ("taper", 0)),
    "box": (
        ("length", REQUIRED),
        ("width", REQUIRED),
        ("height", REQUIRED),
        ("centered", True),
        ("combine", True),
        ("clean", True),
    ),
    "hole": (("diameter", REQUIRED), ("depth", None), ("clean", True)),
}
FEATURE_CALLS = frozenset({"extrude", "cutBlind", "cutThruAll", "box", "hole"})
# Calls that draw into the wires a chain of workplanes shares (CadQuery's CQContext), or
# take from them: one SolidSeas does not replay leaves the next profile unknown.
PENDING_CALLS = frozenset(
    {
        "bezier", "circle", "close", "consolidateWires", "cutBlind", "cutThruAll", "each", "eachpoint",
        "ellipse", "ellipseArc", "extrude", "hLine", "hLineTo", "interpPlate", "line", "lineTo", "loft",
        "mirrorX", "mirrorY", "offset2D", "parametricCurve", "placeSketch", "polarLine", "polarLineTo",
        "polygon", "polyline", "radiusArc", "rect", "revolve", "sagittaArc", "sketch", "slot2D", "spline",
        "splineApprox", "sweep", "tangentArcPoint", "text", "threePointArc", "toPending", "twistExtrude",
        "vLine", "vLineTo", "wire",
    }
)  # fmt: skip
# Calls that use up every wire drawn, unless the stack holds faces to use instead.
CONSUMER_CALLS = frozenset({"extrude", "cutBlind", "cutThruAll", "twistExtrude", "revolve", "sweep", "loft"})


class RecordingError(ValueError):
    """The data is not a CadQuery recording this module reads, or it contradicts itself."""


class _NotTranslated(Exception):
    """A step this module does not translate; the text says why. ``draws`` is False when the
    step leaves the shared wires as they were."""

    def __init__(self, text: str, *, draws: bool = True) -> None:
        super().__init__(text)
        self.draws = draws


# ------------------------------------------------------------------ the recording
@dataclass(frozen=True)
class Ref:
    """An argument that is a workplane of the recording."""

    workplane: int


@dataclass(frozen=True)
class Vector:
    """An argument that is a CadQuery ``Vector``."""

    xyz: tuple[float, float, float]


@dataclass(frozen=True)
class PlaneValue:
    """An argument that is a CadQuery ``Plane``: its origin, x direction and normal."""

    origin: tuple[float, float, float]
    x_dir: tuple[float, float, float]
    normal: tuple[float, float, float]


@dataclass(frozen=True)
class Opaque:
    """An argument a recording does not hold as data, known by its type's name."""

    type: str


@dataclass(frozen=True)
class Step:
    """One call: ``call`` on the workplane ``on`` (None for ``Workplane(...)`` itself), its
    positional ``args`` and keyword ``kwargs``, and the workplane it returned (``result``;
    None when it returned something else). ``index`` counts from 1."""

    index: int
    call: str
    on: int | None
    args: tuple
    kwargs: tuple[tuple[str, Any], ...]
    result: int | None


@dataclass(frozen=True)
class Recording:
    """A recorded model: its ``name``, the ``units`` of its numbers, the ``steps``, and the
    workplane that holds the finished part (``model``), with the file ``properties`` the part
    gets and the version of the CadQuery that made it, when known."""

    name: str
    units: str
    steps: tuple[Step, ...]
    model: int
    properties: tuple[ir.Property, ...] = ()
    cadquery: str | None = None


def _finite(v: Any, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise RecordingError(f"{what}: {v!r} is not a finite number")
    return float(v)


def _triple(v: Any, what: str) -> tuple[float, float, float]:
    if not isinstance(v, list) or len(v) != 3:
        raise RecordingError(f"{what}: needs three numbers")
    return (_finite(v[0], what), _finite(v[1], what), _finite(v[2], what))


def _index(v: Any, what: str, *, null: bool = False) -> int | None:
    if v is None and null:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < MAX_INDEX:
        raise RecordingError(f"{what}: {v!r} is not a workplane's number")
    return v


def _value(v: Any, budget: list[int], depth: int = 0) -> Any:
    """An argument's value from its JSON form."""
    budget[0] -= 1
    if budget[0] < 0:
        raise RecordingError("a step has too many values in its arguments")
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, int):
        if abs(v) > 1 << 53:
            raise RecordingError(f"{v} is too large a number")
        return v
    if isinstance(v, float):
        return _finite(v, "an argument")
    if isinstance(v, str):
        if len(v) > MAX_TEXT:
            raise RecordingError(f"an argument's text is longer than {MAX_TEXT} characters")
        return v
    if isinstance(v, list):
        if depth >= MAX_DEPTH:
            raise RecordingError("an argument is nested too deeply")
        return tuple(_value(x, budget, depth + 1) for x in v)
    if isinstance(v, dict) and len(v) == 1:
        ((key, inner),) = v.items()
        if key == "workplane":
            return Ref(_index(inner, "a workplane argument"))
        if key == "vector":
            return Vector(_triple(inner, "a vector argument"))
        if key == "plane" and isinstance(inner, dict) and set(inner) == {"origin", "x_dir", "normal"}:
            return PlaneValue(
                _triple(inner["origin"], "a plane's origin"),
                _triple(inner["x_dir"], "a plane's x direction"),
                _triple(inner["normal"], "a plane's normal"),
            )
        if key == "object" and isinstance(inner, str) and 0 < len(inner) <= MAX_TEXT:
            return Opaque(inner)
    raise RecordingError(f"an argument is not one a recording holds: {str(v)[:60]}")


def _step(raw: Any, number: int) -> Step:
    if not isinstance(raw, dict) or not set(raw) <= {"call", "on", "args", "kwargs", "result"}:
        raise RecordingError(f"step {number} is not a recorded call")
    call = raw.get("call")
    if not isinstance(call, str) or not 0 < len(call) <= 64 or not call.isidentifier():
        raise RecordingError(f"step {number}: {str(call)[:64]!r} is not a call's name")
    args, kwargs = raw.get("args", []), raw.get("kwargs", {})
    if not isinstance(args, list) or not isinstance(kwargs, dict):
        raise RecordingError(f"step {number}: args is a list and kwargs an object")
    budget = [MAX_VALUES]
    values = tuple(_value(a, budget) for a in args)
    named = []
    for key, val in kwargs.items():
        if not key.isidentifier() or len(key) > 64:
            raise RecordingError(f"step {number}: {key[:64]!r} is not an argument's name")
        named.append((key, _value(val, budget)))
    on = _index(raw.get("on"), f"step {number}'s workplane", null=True)
    if (on is None) != (call == "Workplane"):
        raise RecordingError(f"step {number}: only Workplane(...) is called on no workplane")
    result = _index(raw.get("result"), f"step {number}'s result", null=True)
    return Step(number, call, on, values, tuple(named), result)


def _properties(raw: Any) -> tuple[ir.Property, ...]:
    if not isinstance(raw, list) or len(raw) > MAX_PROPERTIES:
        raise RecordingError(f"properties is a list of at most {MAX_PROPERTIES:,}")
    out = []
    for p in raw:
        if not isinstance(p, dict) or not {"name", "value"} <= set(p) <= {"name", "value", "type"}:
            raise RecordingError("a property has a name, a value and a type")
        out.append(ir.Property(p["name"], p["value"], p.get("type", "text")))
    return tuple(out)


def _no_constant(name: str) -> float:
    raise RecordingError(f"{name} is not a number a recording holds")


def load(source: str | Path | bytes) -> Recording:
    """Read a recording from a file, or from its bytes (at most :data:`MAX_FILE_BYTES`)."""
    if isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
    else:
        with open(source, "rb") as fh:
            raw = fh.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise RecordingError(f"the file is larger than {MAX_FILE_BYTES >> 20} MiB")
    try:
        data = json.loads(raw.decode("utf-8"), parse_constant=_no_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RecordingError(f"not a CadQuery recording: {exc}") from None
    return from_data(data)


def recording_in(raw: bytes) -> Recording | None:
    """The recording a ``.json`` file's bytes hold, checked; None when they are not JSON that
    says it is a recording (another design, say), so the caller reads them some other way."""
    try:
        data = json.loads(raw.decode("utf-8"), parse_constant=_no_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, RecordingError):
        return None
    return from_data(data) if is_recording(data) else None


def is_recording(data: Any) -> bool:
    """Whether JSON data says it is a CadQuery recording (its ``format``)."""
    return isinstance(data, dict) and data.get("format") == FORMAT


def from_data(data: Any) -> Recording:
    """A recording from its JSON form, checked (:func:`to_data` makes that form)."""
    if not is_recording(data):
        raise RecordingError(f"not a CadQuery recording: its format is not {FORMAT}")
    allowed = {"format", "name", "units", "cadquery", "model", "steps", "properties"}
    if not set(data) <= allowed:
        raise RecordingError(f"a recording has no field {sorted(set(data) - allowed)[0]!r}")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME:
        raise RecordingError(f"a recording's name is text of 1 to {MAX_NAME} characters")
    units = data.get("units", "mm")
    if units not in UNITS:
        raise RecordingError(f"units is one of {', '.join(UNITS)}")
    version = data.get("cadquery")
    if version is not None and (not isinstance(version, str) or len(version) > 40):
        raise RecordingError("cadquery is the version of the CadQuery that made the recording")
    steps = data.get("steps")
    if not isinstance(steps, list) or not 0 < len(steps) <= MAX_STEPS:
        raise RecordingError(f"steps is a list of 1 to {MAX_STEPS:,} calls")
    model = _index(data.get("model"), "model")
    rec = Recording(
        name=name.strip(),
        units=units,
        steps=tuple(_step(s, n) for n, s in enumerate(steps, 1)),
        model=model,
        properties=_properties(data.get("properties", [])),
        cadquery=version,
    )
    if not any(s.result == model for s in rec.steps):
        raise RecordingError(f"no step made the model's workplane {model}")
    return rec


def _value_data(v: Any) -> Any:
    if isinstance(v, tuple):
        return [_value_data(x) for x in v]
    if isinstance(v, Ref):
        return {"workplane": v.workplane}
    if isinstance(v, Vector):
        return {"vector": list(v.xyz)}
    if isinstance(v, PlaneValue):
        return {"plane": {"origin": list(v.origin), "x_dir": list(v.x_dir), "normal": list(v.normal)}}
    if isinstance(v, Opaque):
        return {"object": v.type}
    return v


def to_data(rec: Recording) -> dict:
    """The JSON form of a recording."""
    out: dict[str, Any] = {"format": FORMAT, "name": rec.name, "units": rec.units}
    if rec.cadquery is not None:
        out["cadquery"] = rec.cadquery
    out["model"] = rec.model
    out["steps"] = [
        {
            "call": s.call,
            "on": s.on,
            "args": [_value_data(a) for a in s.args],
            "kwargs": {k: _value_data(v) for k, v in s.kwargs},
            "result": s.result,
        }
        for s in rec.steps
    ]
    if rec.properties:
        out["properties"] = [{"name": p.name, "value": p.value, "type": p.type} for p in rec.properties]
    return out


def to_json(rec: Recording) -> str:
    """A recording as the text of a ``.json`` file."""
    return json.dumps(to_data(rec), indent=1, allow_nan=False) + "\n"


# ------------------------------------------------------------------ a call's text
def _text(v: Any) -> str:
    if isinstance(v, (bool, int, float)) or v is None:
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, tuple):
        return "(" + ", ".join(_text(x) for x in v) + ("," if len(v) == 1 else "") + ")"
    if isinstance(v, Vector):
        return "Vector" + _text(v.xyz)
    if isinstance(v, Ref):
        return f"<workplane {v.workplane}>"
    if isinstance(v, PlaneValue):
        return "<Plane>"
    return f"<{v.type}>"


def call_text(step: Step) -> str:
    """How the call reads in Python, such as ``rect(40, 30, centered=False)`` or, for an
    operator, ``- <workplane 3>``, cut short."""
    parts = [_text(a) for a in step.args] + [f"{k}={_text(v)}" for k, v in step.kwargs]
    sign = OPERATOR_SIGNS.get(step.call)
    if sign == "[]":
        text = f"[{', '.join(parts)}]"
    elif sign is not None:
        text = f"{sign} {', '.join(parts)}"
    else:
        text = f"{step.call}({', '.join(parts)})"
    return text if len(text) <= CALL_TEXT else text[: CALL_TEXT - 3] + "..."


def _not_translated(call: str) -> str:
    sign = OPERATOR_SIGNS.get(call)
    what = f"{sign} operator" if sign else f"{call}()"
    return f"CadQuery's {what} is not translated yet"


def _bind(step: Step) -> dict[str, Any]:
    """The step's arguments by name, with CadQuery's defaults for the rest."""
    params = SIGNATURES[step.call]
    if len(step.args) > len(params):
        raise _NotTranslated(f"{step.call}() takes at most {len(params)} arguments here")
    out = {name: value for (name, _), value in zip(params, step.args, strict=False)}
    known = {name for name, _ in params}
    for key, value in step.kwargs:
        if key not in known:
            raise _NotTranslated(f"{step.call}() has no argument {key!r} that SolidSeas knows")
        if key in out:
            raise RecordingError(f"step {step.index}: {key} is given twice")
        out[key] = value
    for name, default in params:
        if name not in out:
            if default is REQUIRED:
                raise RecordingError(f"step {step.index}: {step.call}() needs {name}")
            out[name] = default
    return out


# ------------------------------------------------------------------ vectors and frames
Vec = tuple[float, float, float]


def _add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a: Vec, s: float) -> Vec:
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _axis(v: Vec) -> tuple[int, int] | None:
    """``(axis, sign)`` when ``v`` points along X, Y or Z, else None."""
    n = math.sqrt(_dot(v, v))
    if not n > 0:
        return None
    u = _mul(v, 1 / n)
    for i in range(3):
        if abs(abs(u[i]) - 1) <= EPS and all(abs(u[j]) <= EPS for j in range(3) if j != i):
            return i, (1 if u[i] > 0 else -1)
    return None


def _unit(i: int, sign: int = 1) -> Vec:
    out = [0.0, 0.0, 0.0]
    out[i] = float(sign)
    return (out[0], out[1], out[2])


def _others(axis: int) -> tuple[int, int]:
    i, j = (k for k in range(3) if k != axis)
    return i, j


def _place(axis: int, level: float, a: float, b: float) -> Vec:
    """The model point at ``level`` along ``axis`` and ``a``, ``b`` along the other two."""
    i, j = _others(axis)
    p = [0.0, 0.0, 0.0]
    p[axis], p[i], p[j] = level, a, b
    return (p[0], p[1], p[2])


@dataclass(frozen=True)
class Frame:
    """A workplane: its origin, x direction and normal, both along model axes."""

    origin: Vec
    x: Vec
    z: Vec

    @property
    def y(self) -> Vec:
        return _cross(self.z, self.x)

    @property
    def normal(self) -> tuple[int, int]:
        """``(axis, sign)`` of the normal."""
        return _axis(self.z)  # type: ignore[return-value]

    def world(self, u: float, v: float, w: float = 0.0) -> Vec:
        return _add(self.origin, _add(_mul(self.x, u), _add(_mul(self.y, v), _mul(self.z, w))))


def _frame(origin: Vec, x_dir: Vec, normal: Vec) -> Frame:
    x_axis, z_axis = _axis(x_dir), _axis(normal)
    if x_axis is None or z_axis is None or x_axis[0] == z_axis[0]:
        raise _NotTranslated("a workplane whose axes are not along X, Y and Z is not translated yet")
    return Frame(origin, _unit(*x_axis), _unit(*z_axis))


# ------------------------------------------------------------------ profiles and bodies
@dataclass(frozen=True)
class Loop:
    """A closed profile on a plane across ``axis`` at ``level``: a rectangle from ``lo`` to
    ``hi``, or a circle about ``lo`` of ``radius``, in the other two model axes (in order),
    drawn by the step numbered ``step``."""

    kind: str
    axis: int
    level: float
    lo: tuple[float, float]
    hi: tuple[float, float]
    radius: float = 0.0
    step: int = field(default=0, compare=False)

    @property
    def center(self) -> tuple[float, float]:
        if self.kind == "circle":
            return self.lo
        return ((self.lo[0] + self.hi[0]) / 2, (self.lo[1] + self.hi[1]) / 2)

    @property
    def area(self) -> float:
        if self.kind == "circle":
            return math.pi * self.radius**2
        return (self.hi[0] - self.lo[0]) * (self.hi[1] - self.lo[1])

    def bounds(self) -> tuple[float, float, float, float]:
        if self.kind == "circle":
            (a, b), r = self.lo, self.radius
            return a - r, b - r, a + r, b + r
        return self.lo[0], self.lo[1], self.hi[0], self.hi[1]

    def point(self) -> Vec:
        """Its centre in model coordinates."""
        return _place(self.axis, self.level, *self.center)


def _inside(inner: Loop, outer: Loop, margin: float) -> bool:
    """Whether ``inner`` lies inside ``outer`` with at least ``margin`` to spare."""
    if outer.kind == "rect":
        a0, b0, a1, b1 = inner.bounds()
        return (
            a0 >= outer.lo[0] + margin
            and b0 >= outer.lo[1] + margin
            and a1 <= outer.hi[0] - margin
            and b1 <= outer.hi[1] - margin
        )
    c, r = outer.lo, outer.radius
    if inner.kind == "circle":
        return math.dist(inner.lo, c) + inner.radius <= r - margin
    a0, b0, a1, b1 = inner.bounds()
    return all(math.dist(p, c) <= r - margin for p in ((a0, b0), (a1, b0), (a1, b1), (a0, b1)))


def _apart(p: Loop, q: Loop, margin: float) -> bool:
    """Whether ``p`` and ``q`` are at least ``margin`` apart."""
    if p.kind == "rect" and q.kind == "rect":
        return (
            p.hi[0] + margin <= q.lo[0]
            or q.hi[0] + margin <= p.lo[0]
            or p.hi[1] + margin <= q.lo[1]
            or q.hi[1] + margin <= p.lo[1]
        )
    if p.kind == "circle" and q.kind == "circle":
        return math.dist(p.lo, q.lo) >= p.radius + q.radius + margin
    circle, rect = (p, q) if p.kind == "circle" else (q, p)
    (cx, cy), r = circle.lo, circle.radius
    dx = max(rect.lo[0] - cx, 0.0, cx - rect.hi[0])
    dy = max(rect.lo[1] - cy, 0.0, cy - rect.hi[1])
    return math.hypot(dx, dy) >= r + margin


@dataclass(frozen=True)
class Box:
    """A body SolidSeas follows: a box along the model's axes, from ``lo`` to ``hi``, with
    the ``cuts`` made right through it (loops across one axis, strictly inside its section)."""

    lo: Vec
    hi: Vec
    cuts: tuple[Loop, ...] = ()

    def section(self, axis: int) -> Loop:
        i, j = _others(axis)
        return Loop("rect", axis, 0.0, (self.lo[i], self.lo[j]), (self.hi[i], self.hi[j]))


@dataclass(frozen=True)
class Solid:
    """CadQuery's context solid: the IR features that made it (``history``), and its bodies,
    or None with ``why`` when SolidSeas does not follow its shape."""

    history: tuple
    bodies: tuple[Box, ...] | None
    why: str | None = None


@dataclass(frozen=True)
class Point:
    p: Vec


@dataclass(frozen=True)
class Wire:
    loop: Loop


@dataclass(frozen=True)
class Face:
    """A flat end of a box: across ``axis``, on its ``sign`` side."""

    box: Box
    axis: int
    sign: int

    @property
    def level(self) -> float:
        return self.box.hi[self.axis] if self.sign > 0 else self.box.lo[self.axis]

    @property
    def openings(self) -> tuple[Loop, ...]:
        return tuple(c for c in self.box.cuts if c.axis == self.axis)

    @property
    def area(self) -> float:
        return self.box.section(self.axis).area - sum(c.area for c in self.openings)

    def center(self) -> Vec:
        """Its centre of mass, as CadQuery's ``Face.Center()``."""
        rect = self.box.section(self.axis)
        total = rect.area
        a, b = rect.center[0] * total, rect.center[1] * total
        for c in self.openings:
            total -= c.area
            a -= c.center[0] * c.area
            b -= c.center[1] * c.area
        return _place(self.axis, self.level, a / total, b / total)

    def bound_center(self) -> Vec:
        return _place(self.axis, self.level, *self.box.section(self.axis).center)


@dataclass
class State:
    """A workplane as SolidSeas follows it: its frame and stack, the workplane it came from
    and the first of its chain (``root``). When ``why`` is set it is not followed, and
    ``hint`` is the solid it worked on, with what was not translated."""

    frame: Frame | None
    stack: tuple | None
    parent: int | None
    root: int
    why: str | None = None
    hint: Solid | None = None


@dataclass
class Chain:
    """What a chain of workplanes shares (CadQuery's ``CQContext``): the wires drawn and not
    yet used, or ``uncertain`` naming the step after which they are not known."""

    pending: list[Loop] = field(default_factory=list)
    uncertain: str | None = None


# ------------------------------------------------------------------ the replay
class _Replay:
    def __init__(self, rec: Recording) -> None:
        self.rec = rec
        self.k = UNITS[rec.units]
        self.states: dict[int, State] = {}
        self.chains: dict[int, Chain] = {}
        names = {s.index: call_text(s) for s in rec.steps}
        counts: dict[str, int] = {}
        for text in names.values():
            counts[text] = counts.get(text, 0) + 1
        # the same call twice: say which step each feature came from
        self.names = {n: t + (f" (step {n})" if counts[t] > 1 else "") for n, t in names.items()}
        size = 0.0
        for s in rec.steps:
            for v in s.args + tuple(v for _, v in s.kwargs):
                if not isinstance(v, bool) and isinstance(v, (int, float)):
                    size = max(size, abs(v))
        self.eps = EPS * max(1.0, size)

    def label(self, step: Step) -> str:
        return f"step {step.index}, {call_text(step)}"

    def untranslated(self, step: Step) -> str:
        """Why what comes after ``step`` is not translated either."""
        return f"follows {self.label(step)}, which is not translated"

    def unfollowed(self, step: Step, where: str) -> str:
        """Why a step that needs the shape is not translated, when SolidSeas stopped following
        it at ``step``."""
        return f"SolidSeas does not follow the shape after {self.label(step)}, where {where}"

    # ---------------------------------------------------------------- the stack and the solid
    def find_solid(self, index: int | None) -> Solid | None:
        """CadQuery's ``findSolid``: the solid on this workplane's stack, else its parent's."""
        while index is not None:
            st = self.states[index]
            if st.why is not None:
                return st.hint or Solid((), None, st.why)
            solids = [x for x in st.stack if isinstance(x, Solid)]
            if solids:
                return solids[0]
            index = st.parent
        return None

    def base_solid(self, step: Step) -> Solid:
        """The solid a cut works on, which CadQuery requires."""
        base = self.find_solid(step.on)
        if base is None:
            raise RecordingError(f"step {step.index}: {step.call}() has no solid to cut")
        if base.bodies is None and not base.history:
            raise _NotTranslated(base.why)
        return base

    def points(self, st: State, step: Step) -> list[Vec]:
        """Where each item on the stack puts a profile, a box or a hole (``eachpoint``)."""
        if not st.stack:
            return [st.frame.origin]
        out = []
        for item in st.stack:
            if isinstance(item, Point):
                out.append(item.p)
            elif isinstance(item, Wire):
                out.append(item.loop.point())
            elif isinstance(item, Face):
                out.append(item.center())
            else:
                raise _NotTranslated(f"{step.call}() at the centre of a solid is not translated yet")
        return out

    # ---------------------------------------------------------------- the IR
    def ir_plane(self, axis: int, level: float) -> ir.Plane:
        base = BASE_FOR_AXIS[axis]
        if abs(level) <= self.eps:
            return ir.Plane.named(base)
        _, x_dir, y_dir = ir.PLANES[base]
        return ir.Plane(_mul(_unit(axis), level * self.k), x_dir, y_dir, None, base, level * self.k)

    def sketch(self, step: Step, loops: list[Loop], level: float) -> ir.Sketch:
        """An IR sketch of ``loops``, on the base plane across their axis at ``level``."""
        axis = loops[0].axis
        _, bx, by = ir.PLANES[BASE_FOR_AXIS[axis]]

        def uv(a: float, b: float) -> tuple[float, float]:
            p = _place(axis, 0.0, a, b)
            return _dot(p, bx) * self.k, _dot(p, by) * self.k

        points: list[ir.Point] = []
        curves: list[ir.Curve] = []
        for n, loop in enumerate(loops, 1):
            if loop.kind == "circle":
                cx, cy = uv(*loop.lo)
                points.append(ir.Point(f"c{n}", cx, cy))
                curves.append(ir.Curve(f"k{n}", "circle", [f"c{n}"], radius=loop.radius * self.k))
                continue
            us = sorted({uv(loop.lo[0], loop.lo[1])[0], uv(loop.hi[0], loop.hi[1])[0]})
            vs = sorted({uv(loop.lo[0], loop.lo[1])[1], uv(loop.hi[0], loop.hi[1])[1]})
            ids = [f"p{n}.{m}" for m in range(1, 5)]
            corners = [(us[0], vs[0]), (us[1], vs[0]), (us[1], vs[1]), (us[0], vs[1])]  # counter-clockwise
            points += [ir.Point(pid, u, v) for pid, (u, v) in zip(ids, corners, strict=True)]
            curves += [ir.Curve(f"l{n}.{m + 1}", "line", [ids[m], ids[(m + 1) % 4]]) for m in range(4)]
        drawn = list(dict.fromkeys(loop.step or step.index for loop in loops))  # the calls that drew them
        name = " + ".join(self.names[n] for n in drawn)
        if len(name) > 2 * CALL_TEXT:
            name = name[: 2 * CALL_TEXT - 3] + "..."
        return ir.Sketch(f"s{step.index}", name, self.ir_plane(axis, level), points=points, curves=curves)

    def check_profiles(self, loops: list[Loop]) -> None:
        """Profiles CadQuery and the IR read alike: on one plane, each pair apart or one
        inside the other, and nothing inside a loop that is itself inside one."""
        first = loops[0]
        if any(lp.axis != first.axis or abs(lp.level - first.level) > self.eps for lp in loops):
            raise _NotTranslated("profiles on more than one plane are not translated yet")
        depth = [0] * len(loops)
        for a, p in enumerate(loops):
            for b, q in enumerate(loops):
                if a == b:
                    continue
                if _inside(p, q, self.eps):
                    depth[a] += 1
                elif not _inside(q, p, self.eps) and not _apart(p, q, self.eps):
                    raise _NotTranslated("profiles that overlap or touch in one sketch are not translated")
        if max(depth) > 1:
            raise _NotTranslated("profiles nested more than one deep are not translated yet")

    @staticmethod
    def boxes_of(loops: list[Loop], span: tuple[float, float]) -> list[Box] | None:
        """The boxes rectangles make when extruded over ``span`` along their axis; None when
        a profile is a circle or holds another, which SolidSeas then stops following."""
        out = []
        for loop in loops:
            if loop.kind != "rect" or any(_inside(q, loop, 0.0) for q in loops if q is not loop):
                return None
            i, j = _others(loop.axis)
            lo, hi = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
            lo[loop.axis], hi[loop.axis] = span
            lo[i], lo[j], hi[i], hi[j] = loop.lo[0], loop.lo[1], loop.hi[0], loop.hi[1]
            out.append(Box((lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])))
        return out

    def touches(self, a: Box, b: Box) -> bool:
        return all(a.lo[i] <= b.hi[i] + self.eps and b.lo[i] <= a.hi[i] + self.eps for i in range(3))

    def covers(self, span: tuple[float, float], body: Box, axis: int) -> bool:
        return span[0] <= body.lo[axis] + self.eps and body.hi[axis] <= span[1] + self.eps

    # ---------------------------------------------------------------- features
    def boss(
        self,
        step: Step,
        on: State,
        loops: list[Loop],
        span: tuple[float, float],
        combine: Any,
        level: float,
        depth: float,
        direction: str,
    ) -> Solid:
        """A solid from ``loops`` extruded over ``span``, joined to the context solid or not
        as ``combine`` says."""
        sketch = self.sketch(step, loops, level)
        new = self.boxes_of(loops, span)
        base = self.find_solid(step.on) if combine else None
        if base is not None and base.bodies is None and not base.history:
            raise _NotTranslated(base.why)
        operation = "new_body"
        bodies: tuple[Box, ...] | None = tuple(new) if new is not None else None
        why = None if new is not None else self.unfollowed(step, "a profile is not a plain rectangle")
        history: tuple = ()
        if base is not None:
            history = base.history
            if base.bodies is None or new is None:
                operation, bodies, why = "join", None, base.why or why
            elif any(self.touches(a, b) for a in new for b in base.bodies):
                operation, bodies, why = "join", None, self.unfollowed(step, "bodies join")
            else:
                bodies = base.bodies + tuple(new)
        extrude = ir.Extrude(
            f"f{step.index}", self.names[step.index], sketch.id, depth * self.k, operation, direction
        )
        return Solid(history + (sketch, extrude), bodies, why)

    def cut(
        self,
        step: Step,
        base: Solid,
        loops: list[Loop],
        sketch: ir.Sketch,
        extrude: ir.Extrude,
        through: bool,
    ) -> Solid:
        """``base`` with ``loops`` cut: followed when each loop goes right through a box and
        lies strictly inside its section, or misses it."""
        history = base.history + (sketch, extrude)
        if base.bodies is None:
            return Solid(history, None, base.why)
        lost = Solid(history, None, self.unfollowed(step, "a cut does not go cleanly through a box"))
        if not through:
            return lost
        bodies = list(base.bodies)
        for loop in loops:
            for n, body in enumerate(bodies):
                section = body.section(loop.axis)
                if _apart(loop, section, self.eps):
                    continue
                if not _inside(loop, section, self.eps) or any(
                    c.axis != loop.axis or not _apart(c, loop, self.eps) for c in body.cuts
                ):
                    return lost
                bodies[n] = Box(body.lo, body.hi, body.cuts + (loop,))
        return Solid(history, tuple(bodies), None)

    # ---------------------------------------------------------------- one step
    def step(self, step: Step) -> None:
        on = None
        if step.on is not None:
            on = self.states.get(step.on)
            if on is None:  # made before the recording started, or by something not recorded
                on = State(None, None, None, step.on, why=UNSEEN)
                self.states[step.on] = on
        if step.result is None:  # it returned something else than a workplane
            if step.call in PENDING_CALLS and on is not None:
                self.leaves_wires(step, on, self.chains.setdefault(on.root, Chain()))
            return
        known = step.call in SIGNATURES
        if step.call in ("tag", "end") or (step.result in self.states and not known):
            self.returns_existing(step, on, known)
            return
        if step.result in self.states:
            raise RecordingError(f"step {step.index}: workplane {step.result} is made twice")
        root = step.result if on is None else on.root
        chain = self.chains.setdefault(root, Chain())
        if on is not None and on.why is not None and known and step.call not in FEATURE_CALLS:
            # nothing to replay it on, so the workplane it makes is not followed either
            self.leaves_wires(step, on, chain)
            self.states[step.result] = State(None, None, step.on, root, why=on.why, hint=on.hint)
            return
        try:
            if not known:
                raise _NotTranslated(_not_translated(step.call))
            if on is not None and on.why is not None:
                raise _NotTranslated(on.why)
            state = getattr(self, "do_" + step.call)(step, on, _bind(step), chain)
            state.root = root
        except _NotTranslated as why:
            if why.draws:
                self.leaves_wires(step, on, chain)
            base = on.hint if on is not None and on.why is not None else self.find_solid(step.on)
            entry = ir.Unsupported(f"u{step.index}", self.names[step.index], "cadquery", str(why))
            hint = Solid((base.history if base is not None else ()) + (entry,), None, self.untranslated(step))
            state = State(None, None, step.on, root, why=self.untranslated(step), hint=hint)
        self.states[step.result] = state

    def leaves_wires(self, step: Step, on: State | None, chain: Chain) -> None:
        """What a step SolidSeas does not replay leaves of the shared wires: a call that uses
        them all leaves none; one that draws leaves them unknown."""
        if (
            step.call in CONSUMER_CALLS
            and on is not None
            and on.why is None
            and not any(isinstance(x, Face) for x in on.stack)
        ):
            chain.pending, chain.uncertain = [], None
        elif step.call in PENDING_CALLS and chain.uncertain is None:
            chain.uncertain = self.label(step)

    def returns_existing(self, step: Step, on: State | None, known: bool) -> None:
        """``tag`` returns its own workplane and ``end`` an earlier one. Another call that
        returns a workplane already made may have changed it (CadQuery's ``add`` does)."""
        if step.call == "tag":
            if step.result != step.on:
                raise RecordingError(f"step {step.index}: tag() returns its own workplane")
            return
        if step.call == "end":
            n = _bind(step)["n"]
            if isinstance(n, bool) or not isinstance(n, int) or n < 1:
                raise RecordingError(f"step {step.index}: end() takes a count of 1 or more")
            index = step.on
            for _ in range(n):
                st = self.states.get(index)
                if st is None or st.why is not None:
                    index = None
                    break
                index = st.parent
            if index is not None and index != step.result:
                raise RecordingError(
                    f"step {step.index}: end({n}) returns workplane {index}, not {step.result}"
                )
            if step.result not in self.states:
                self.states[step.result] = State(
                    None,
                    None,
                    None,
                    on.root,
                    why=f"follows {self.label(step)}, back to a workplane SolidSeas does not follow",
                )
            return
        st = self.states[step.result]
        chain = self.chains.setdefault(st.root, Chain())
        self.leaves_wires(step, None, chain)
        if st.why is None:
            base = self.find_solid(step.result)
            entry = ir.Unsupported(
                f"u{step.index}", self.names[step.index], "cadquery", _not_translated(step.call)
            )
            hint = Solid((base.history if base is not None else ()) + (entry,), None, self.untranslated(step))
            self.states[step.result] = State(
                None, None, st.parent, st.root, why=self.untranslated(step), hint=hint
            )

    # ---------------------------------------------------------------- the calls replayed
    def vec3(self, v: Any, what: str) -> Vec:
        if isinstance(v, Vector):
            return v.xyz
        if (
            isinstance(v, tuple)
            and len(v) in (2, 3)
            and all(not isinstance(c, bool) and isinstance(c, (int, float)) for c in v)
        ):
            return (float(v[0]), float(v[1]), float(v[2]) if len(v) == 3 else 0.0)
        raise _NotTranslated(f"{what} is not a point SolidSeas reads", draws=False)

    @staticmethod
    def number(v: Any, what: str) -> float:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise _NotTranslated(f"{what} that is not a number is not translated yet")
        return float(v)

    @staticmethod
    def centered(value: Any, n: int) -> tuple[bool, ...]:
        if isinstance(value, bool):
            return (value,) * n
        if isinstance(value, tuple) and len(value) == n and all(isinstance(v, bool) for v in value):
            return value
        raise _NotTranslated(f"centered is True, False or {n} of those")

    def do_Workplane(self, step: Step, on: None, a: dict, chain: Chain) -> State:  # noqa: N802
        plane, obj = a["inPlane"], a["obj"]
        if obj is not None:
            raise _NotTranslated("Workplane() with an object on its stack is not translated yet")
        if isinstance(plane, str):
            if plane not in NAMED_PLANES:
                raise RecordingError(f"step {step.index}: {plane!r} is not a plane CadQuery names")
            x_dir, normal = NAMED_PLANES[plane]
            origin = self.vec3(a["origin"], "the origin")
        elif isinstance(plane, PlaneValue):  # CadQuery takes a Plane's own origin
            origin, x_dir, normal = plane.origin, plane.x_dir, plane.normal
        else:
            raise _NotTranslated("Workplane() on that kind of plane is not translated yet")
        return State(_frame(origin, x_dir, normal), (), None, step.result)

    def do_center(self, step: Step, on: State, a: dict, chain: Chain) -> State:
        p = on.frame.world(self.number(a["x"], "x"), self.number(a["y"], "y"))
        return State(Frame(p, on.frame.x, on.frame.z), (Point(p),), step.on, on.root)

    def do_moveTo(self, step: Step, on: State, a: dict, chain: Chain) -> State:  # noqa: N802
        p = on.frame.world(self.number(a["x"], "x"), self.number(a["y"], "y"))
        return State(on.frame, (Point(p),), step.on, on.root)

    def do_pushPoints(self, step: Step, on: State, a: dict, chain: Chain) -> State:  # noqa: N802
        given = a["pntList"]
        if not isinstance(given, tuple) or not given:
            raise _NotTranslated("pushPoints() with that list is not translated yet")
        pts = tuple(Point(on.frame.world(*self.vec3(p, "a point"))) for p in given)
        return State(on.frame, pts, step.on, on.root)

    def do_faces(self, step: Step, on: State, a: dict, chain: Chain) -> State:
        if a["tag"] is not None:
            raise _NotTranslated("faces() of a tagged workplane is not translated yet")
        sel = a["selector"].strip() if isinstance(a["selector"], str) else None
        if sel not in SELECTORS:
            raise _NotTranslated(
                "faces() with that selector is not translated yet; >X, <X, >Y, <Y, >Z and <Z are"
            )
        if len(on.stack) != 1 or not isinstance(on.stack[0], Solid):
            raise _NotTranslated("faces() of anything but the solid is not translated yet")
        solid = on.stack[0]
        if solid.bodies is None:
            raise _NotTranslated(solid.why)
        axis, sign = SELECTORS[sel]
        return State(on.frame, tuple(self.select(solid.bodies, axis, sign)), step.on, on.root)

    def select(self, bodies: tuple[Box, ...], axis: int, sign: int) -> list[Face]:
        """CadQuery's ``>Z`` and the like: every face keyed by its centre along the axis,
        clustered within :data:`TOLERANCE` of each cluster's first, and the last (or first)
        cluster taken. Only the flat ends of boxes are followed."""
        keyed: list[tuple[float, Face | None]] = []
        for body in bodies:
            for ax in range(3):
                for sg in (-1, 1):
                    face = Face(body, ax, sg)
                    keyed.append((face.center()[axis], face))
            for c in body.cuts:  # the walls of the cuts through it
                mid = (body.lo[axis] + body.hi[axis]) / 2
                if c.axis == axis:
                    keyed.append((mid, None))
                elif c.kind == "circle":
                    keyed.append((c.point()[axis], None))
                else:
                    k = _others(c.axis).index(axis)
                    keyed += [(c.lo[k], None), (c.hi[k], None), (c.center[k], None), (c.center[k], None)]
        keyed.sort(key=lambda kv: kv[0])
        clusters: list[list[Face | None]] = [[]]
        start = keyed[0][0]
        for key, face in keyed:
            if abs(key - start) <= TOLERANCE:
                clusters[-1].append(face)
            else:
                clusters.append([face])
                start = key
        chosen = clusters[-1] if sign > 0 else clusters[0]
        if any(f is None or f.axis != axis or f.sign != sign for f in chosen):
            raise _NotTranslated(
                "faces() selects faces other than flat ends of boxes, which is not translated yet"
            )
        return chosen  # type: ignore[return-value]

    def do_workplane(self, step: Step, on: State, a: dict, chain: Chain) -> State:
        option = a["centerOption"]
        if option not in CENTER_OPTIONS:
            raise RecordingError(f"step {step.index}: centerOption {option!r} is not CadQuery's")
        stack = on.stack
        if stack and all(isinstance(x, Face) for x in stack):
            faces: list[Face] = list(stack)
            if any(abs(f.level - faces[0].level) >= TOLERANCE for f in faces):
                raise RecordingError(f"step {step.index}: the faces are not co-planar")
            if option == "CenterOfBoundBox":
                pts = [f.bound_center() for f in faces]
                center = (
                    sum(p[0] for p in pts) / len(pts),
                    sum(p[1] for p in pts) / len(pts),
                    sum(p[2] for p in pts) / len(pts),
                )
            else:
                total = sum(f.area for f in faces)
                pts = [_mul(f.center(), f.area / total) for f in faces]
                center = (sum(p[0] for p in pts), sum(p[1] for p in pts), sum(p[2] for p in pts))
            normal = _unit(faces[0].axis, faces[0].sign)
            x_dir = _cross((0.0, 0.0, 1.0), normal)
            if math.sqrt(_dot(x_dir, x_dir)) < TOLERANCE:  # a face across Z: x is the model's
                x_dir = (1.0, 0.0, 0.0)
        elif not stack or (len(stack) == 1 and isinstance(stack[0], Point)):
            center = stack[0].p if stack else on.frame.origin
            parent = self.states.get(on.parent) if on.parent is not None else None
            if parent is not None and parent.stack and isinstance(parent.stack[0], Face):
                raise _NotTranslated("workplane() at a point of a face is not translated yet")
            normal, x_dir = on.frame.z, on.frame.x
        else:
            raise _NotTranslated("workplane() on that selection is not translated yet")
        if option == "ProjectedOrigin":
            origin = on.frame.origin if a["origin"] is None else self.vec3(a["origin"], "origin")
            center = _sub(origin, _mul(normal, _dot(_sub(origin, center), normal)))
        if a["invert"] is True:
            normal = _mul(normal, -1.0)
        elif a["invert"] is not False:
            raise _NotTranslated("invert that is not True or False is not translated")
        center = _add(center, _mul(normal, self.number(a["offset"], "offset")))
        return State(_frame(center, x_dir, normal), (), step.on, on.root)

    def do_rect(self, step: Step, on: State, a: dict, chain: Chain) -> State:
        if a["forConstruction"] is not False:
            raise _NotTranslated("construction geometry is not translated yet", draws=False)
        w, h = self.number(a["xLen"], "xLen"), self.number(a["yLen"], "yLen")
        cx, cy = self.centered(a["centered"], 2)
        f = on.frame
        axis, _ = f.normal
        i, j = _others(axis)
        loops = []
        for p in self.points(on, step):
            # CadQuery's corners, about the point, then moved by half a side when not centered
            us = [(0.0 if cx else w / 2) + s * w / 2 for s in (-1, 1)]
            vs = [(0.0 if cy else h / 2) + s * h / 2 for s in (-1, 1)]
            corners = [_add(p, _add(_mul(f.x, u), _mul(f.y, v))) for u in us for v in vs]
            lo = (min(c[i] for c in corners), min(c[j] for c in corners))
            hi = (max(c[i] for c in corners), max(c[j] for c in corners))
            if not (hi[0] - lo[0] > self.eps and hi[1] - lo[1] > self.eps):
                raise _NotTranslated("a rectangle with no area is not translated")
            loops.append(Loop("rect", axis, p[axis], lo, hi, step=step.index))
        chain.pending.extend(loops)
        return State(on.frame, tuple(Wire(lp) for lp in loops), step.on, on.root)

    def do_circle(self, step: Step, on: State, a: dict, chain: Chain) -> State:
        if a["forConstruction"] is not False:
            raise _NotTranslated("construction geometry is not translated yet", draws=False)
        r = self.number(a["radius"], "radius")
        if not r > self.eps:
            raise _NotTranslated("a circle with no area is not translated")
        axis, _ = on.frame.normal
        i, j = _others(axis)
        loops = [
            Loop("circle", axis, p[axis], (p[i], p[j]), (p[i], p[j]), r, step.index)
            for p in self.points(on, step)
        ]
        chain.pending.extend(loops)
        return State(on.frame, tuple(Wire(lp) for lp in loops), step.on, on.root)

    def take_wires(self, step: Step, on: State, chain: Chain) -> list[Loop]:
        """The wires an extrusion or a cut uses (CadQuery's ``_getFaces``): all of them."""
        if any(isinstance(x, Face) for x in on.stack):
            raise _NotTranslated(f"{step.call}() of selected faces is not translated yet", draws=False)
        if chain.uncertain is not None:
            raise _NotTranslated(
                f"its profile may hold wires drawn by {chain.uncertain}, which is not translated"
            )
        if not chain.pending:
            raise RecordingError(f"step {step.index}: {step.call}() has no wires to use")
        loops, chain.pending = list(chain.pending), []
        self.check_profiles(loops)
        if loops[0].axis != on.frame.normal[0]:
            raise _NotTranslated(
                f"{step.call}() across a plane its profiles are not on is not translated yet"
            )
        return loops

    def distance(self, value: Any, what: str) -> float:
        if isinstance(value, (str, Opaque)) or value is None:
            raise _NotTranslated(f"{what} up to a face is not translated yet")
        d = self.number(value, what)
        if not abs(d) > self.eps:
            raise _NotTranslated(f"{what} of no length is not translated")
        return d

    @staticmethod
    def no_taper(value: Any) -> None:
        if isinstance(value, bool) or value not in (None, 0, 0.0):
            raise _NotTranslated("a tapered extrusion or cut is not translated yet")

    @staticmethod
    def direction(frame: Frame, d: float, both: bool) -> str:
        """The IR's direction for going ``d`` along the frame's normal; the base planes'
        normals are the model's +X, +Y and +Z."""
        if both:
            return "midplane"
        return "forward" if frame.normal[1] * d > 0 else "reverse"

    def span(self, frame: Frame, level: float, d: float, both: bool) -> tuple[float, float]:
        """Where a prism from ``level``, ``d`` along the frame's normal, reaches."""
        if both:
            return level - abs(d), level + abs(d)
        far = level + frame.normal[1] * d
        return min(level, far), max(level, far)

    def do_extrude(self, step: Step, on: State, a: dict, chain: Chain) -> State:
        combine = a["combine"]
        if combine in ("cut", "s"):  # CadQuery calls cutBlind
            cut = {"until": a["until"], "both": a["both"], "taper": a["taper"]}
            return self.do_cutBlind(step, on, cut, chain)
        if combine not in (True, False, "a"):
            raise RecordingError(f"step {step.index}: combine {combine!r} is not CadQuery's")
        self.no_taper(a["taper"])
        d = self.distance(a["until"], "an extrusion")
        both = a["both"] is True
        loops = self.take_wires(step, on, chain)
        level = loops[0].level
        solid = self.boss(
            step,
            on,
            loops,
            self.span(on.frame, level, d, both),
            combine,
            level,
            2 * abs(d) if both else abs(d),
            self.direction(on.frame, d, both),
        )
        return State(on.frame, (solid,), step.on, on.root)

    def do_box(self, step: Step, on: State, a: dict, chain: Chain) -> State:
        if a["combine"] not in (True, False, "a"):
            raise _NotTranslated("box() that cuts is not translated yet", draws=False)
        length, width, height = (self.number(a[k], k) for k in ("length", "width", "height"))
        if not all(s > self.eps for s in (length, width, height)):
            raise _NotTranslated("a box with no volume is not translated", draws=False)
        cx, cy, cz = self.centered(a["centered"], 3)
        f = on.frame
        axis, _ = f.normal
        i, j = _others(axis)
        loops = []
        for p in self.points(on, step):
            us = [(-length / 2 if cx else 0.0) + s * length for s in (0, 1)]
            vs = [(-width / 2 if cy else 0.0) + s * width for s in (0, 1)]
            corners = [_add(p, _add(_mul(f.x, u), _mul(f.y, v))) for u in us for v in vs]
            lo = (min(c[i] for c in corners), min(c[j] for c in corners))
            hi = (max(c[i] for c in corners), max(c[j] for c in corners))
            loops.append(Loop("rect", axis, p[axis], lo, hi))
        self.check_profiles(loops)
        level = loops[0].level
        if cz:  # about the point, half each way
            span, direction = (level - height / 2, level + height / 2), "midplane"
        else:
            span, direction = self.span(f, level, height, False), self.direction(f, height, False)
        solid = self.boss(step, on, loops, span, a["combine"], level, height, direction)
        return State(on.frame, (solid,), step.on, on.root)

    def do_cutBlind(self, step: Step, on: State, a: dict, chain: Chain) -> State:  # noqa: N802
        both, taper = a["both"], a["taper"]
        if isinstance(both, float) and taper is None:  # CadQuery reads a float there as the taper
            both, taper = False, both
        self.no_taper(taper)
        d = self.distance(a["until"], "a cut")
        both = both is True
        base = self.base_solid(step)
        loops = self.take_wires(step, on, chain)
        level = loops[0].level
        sketch = self.sketch(step, loops, level)
        extrude = ir.Extrude(
            f"f{step.index}",
            self.names[step.index],
            sketch.id,
            (2 * abs(d) if both else abs(d)) * self.k,
            "cut",
            self.direction(on.frame, d, both),
        )
        span = self.span(on.frame, level, d, both)
        axis = loops[0].axis
        through = base.bodies is not None and all(self.covers(span, b, axis) for b in base.bodies)
        return State(on.frame, (self.cut(step, base, loops, sketch, extrude, through),), step.on, on.root)

    def do_cutThruAll(self, step: Step, on: State, a: dict, chain: Chain) -> State:  # noqa: N802
        self.no_taper(a["taper"])
        base = self.base_solid(step)
        loops = self.take_wires(step, on, chain)
        sketch = self.sketch(step, loops, 0.0)
        extrude = ir.Extrude(
            f"f{step.index}", self.names[step.index], sketch.id, 0.0, "cut", "midplane", "through_all"
        )
        return State(on.frame, (self.cut(step, base, loops, sketch, extrude, True),), step.on, on.root)

    def do_hole(self, step: Step, on: State, a: dict, chain: Chain) -> State:
        d = self.number(a["diameter"], "diameter")
        if not d > self.eps:
            raise _NotTranslated("a hole with no diameter is not translated", draws=False)
        if a["depth"] is not None:
            raise _NotTranslated("a hole with a depth is not translated yet", draws=False)
        base = self.base_solid(step)
        if base.bodies is None:
            raise _NotTranslated(base.why, draws=False)
        axis, sign = on.frame.normal
        i, j = _others(axis)
        lo = [min(b.lo[n] for b in base.bodies) for n in range(3)]
        hi = [max(b.hi[n] for b in base.bodies) for n in range(3)]
        length = math.dist(lo, hi)  # CadQuery drills as deep as the part's box is long
        loops = []
        for p in self.points(on, step):
            loop = Loop("circle", axis, 0.0, (p[i], p[j]), (p[i], p[j]), d / 2)
            end = p[axis] - sign * length  # away from the workplane's normal
            span = (min(p[axis], end), max(p[axis], end))
            for body in base.bodies:
                if not _apart(loop, body.section(axis), self.eps) and not self.covers(span, body, axis):
                    raise _NotTranslated(
                        "a hole that does not go through every body in its way is not translated yet",
                        draws=False,
                    )
            loops.append(loop)
        try:
            self.check_profiles(loops)
        except _NotTranslated as why:
            raise _NotTranslated(str(why), draws=False) from None
        sketch = self.sketch(step, loops, 0.0)
        extrude = ir.Extrude(
            f"f{step.index}", self.names[step.index], sketch.id, 0.0, "cut", "midplane", "through_all"
        )
        return State(on.frame, (self.cut(step, base, loops, sketch, extrude, True),), step.on, on.root)

    # ---------------------------------------------------------------- the model
    def run(self) -> ir.Document:
        for s in self.rec.steps:
            self.step(s)
        st = self.states.get(self.rec.model)
        if st is None:
            raise RecordingError(f"no step made the model's workplane {self.rec.model}")
        if st.why is not None:
            history = st.hint.history if st.hint is not None else ()
            if not any(isinstance(f, ir.Unsupported) for f in history):
                history += (ir.Unsupported("model", self.rec.name, "cadquery", st.why),)
        else:
            if not st.stack or not all(isinstance(x, Solid) for x in st.stack):
                raise RecordingError(
                    "the model's workplane holds no solid: record the one with the finished part"
                )
            history = st.stack[0].history
        doc = ir.Document(
            name=self.rec.name,
            features=list(history),
            properties=list(self.rec.properties),
            source={"system": "CadQuery", "format": FORMAT, "version": self.rec.cadquery},
        )
        try:
            return ir.validate(doc)
        except ir.IRError as exc:
            raise RecordingError(f"the recording does not make a design SolidSeas reads: {exc}") from None


def to_ir(rec: Recording) -> ir.Document:
    """Translate a recording (module notes). A step this does not translate stays in the
    timeline as an :class:`~.ir.Unsupported` entry, and so does each feature after it."""
    return _Replay(rec).run()


def read_ir(source: str | Path | bytes) -> ir.Document:
    """A recording file, or its bytes, as ``ParametricDocumentIR``."""
    return to_ir(load(source))


__all__ = [
    "FORMAT",
    "UNITS",
    "Opaque",
    "PlaneValue",
    "Recording",
    "RecordingError",
    "Ref",
    "Step",
    "Vector",
    "call_text",
    "from_data",
    "is_recording",
    "load",
    "read_ir",
    "to_data",
    "to_ir",
    "to_json",
]
