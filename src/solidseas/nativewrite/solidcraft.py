"""SolidCraft's native document into ``ParametricDocumentIR``.

SolidCraft (MIT or Apache-2.0, https://github.com/tangency-labs/solidcraft)
saves a ``.solidcraft`` file either as its JSON document or as a ZIP holding
``container.json`` and ``document.json``. This reads either with the standard
library only: no SolidCraft, no MCP server. Field names follow SolidCraft's
serialized format as documented in its repository; no SolidCraft code is used.

Supported now: parameters, sketches on the three base planes (points, lines,
circles, arcs, construction flags, the geometric constraints and driving
dimensions the IR lists) and extrusions (blind or through all; forward,
reverse or symmetric; new body, join or cut; all regions or chosen loops).
Every other feature becomes an :class:`~.ir.Unsupported` entry that says why,
and so does a supported feature that uses an option the IR lacks.

SolidCraft stores lengths in millimetres and angles in degrees in its
parameter expressions, radians in its angle dimensions' values. A bare number
in an expression is millimetres or degrees.
"""

import ast
import io
import json
import math
import operator
import re
import zipfile
from pathlib import Path

from . import ir

MAX_FILE_BYTES = 64 << 20
MAX_DOCUMENT_BYTES = 256 << 20
CONTAINER_FORMATS = ("solidcraft-container/1", "solvecraft-container/1")
FORMAT_RE = re.compile(r"(?:solidcraft|solvecraft)/(\d+)\Z")
OLDEST_FORMAT = 1
XZ_FRAME_FORMAT = 6  # from this format an XZ sketch's y is -Z; earlier ones are refused
NEWEST_FORMAT = 28
BASE_PLANES = {"XY": "xy", "XZ": "xz", "YZ": "yz"}
LENGTH_UNITS = {"mm": 1e-3, "cm": 1e-2, "m": 1.0, "um": 1e-6, "in": 0.0254, "ft": 0.3048, "mil": 2.54e-5}
ANGLE_UNITS = {"deg": math.pi / 180, "rad": 1.0}


class SolidCraftError(ValueError):
    """The file is not a SolidCraft document this adapter reads."""


# ------------------------------------------------------------------ reading
def load(source: str | Path | bytes) -> dict:
    """The document JSON of a ``.solidcraft`` file (plain JSON or the ZIP container)."""
    if isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
    else:
        p = Path(source)
        if p.stat().st_size > MAX_FILE_BYTES:
            raise SolidCraftError("file too large")
        raw = p.read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        raise SolidCraftError("file too large")
    if raw[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            info = z.getinfo("container.json")
            if info.file_size > 4096:
                raise SolidCraftError("container.json too large")
            fmt = json.loads(z.read(info)).get("format")
            if fmt not in CONTAINER_FORMATS:
                raise SolidCraftError(f"container format {fmt!r}")
            info = z.getinfo("document.json")
            if info.file_size > MAX_DOCUMENT_BYTES:
                raise SolidCraftError("document.json too large")
            raw = z.read(info)
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise SolidCraftError(f"not a SolidCraft document: {e}") from e
    if not isinstance(doc, dict) or not isinstance(doc.get("features"), list):
        raise SolidCraftError("not a SolidCraft document: no features list")
    m = FORMAT_RE.match(str(doc.get("format", "")))
    if not m:
        raise SolidCraftError(f"format {doc.get('format')!r}")
    n = int(m.group(1))
    if not OLDEST_FORMAT <= n <= NEWEST_FORMAT:
        raise SolidCraftError(
            f"format {n} is outside {OLDEST_FORMAT} to {NEWEST_FORMAT}; save it again in SolidCraft"
        )
    return doc


# ------------------------------------------------------------------ expressions
_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}
_FUNCS = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "abs": abs,
    "min": min,
    "max": max,
}
_UNIT_RE = re.compile(r"(\d(?:[\d.]*)(?:[eE][-+]?\d+)?)\s*(mm|cm|um|m|in|ft|mil|deg|rad)\b")


class Expressions:
    """Evaluate SolidCraft parameter expressions to SI values, with the parameters they name."""

    def __init__(self, params: list[dict]):
        self.text = {p["name"]: str(p.get("expr", "")) for p in params if isinstance(p, dict) and "name" in p}
        self.unit = {p["name"]: p.get("unit", "mm") for p in params if isinstance(p, dict) and "name" in p}
        self.cache: dict[str, float] = {}
        self.busy: set[str] = set()

    def param(self, name: str) -> float:
        if name in self.cache:
            return self.cache[name]
        if name not in self.text:
            raise SolidCraftError(f"no parameter {name!r}")
        if name in self.busy:
            raise SolidCraftError(f"parameter {name!r} refers to itself")
        self.busy.add(name)
        try:
            v = self.eval(self.text[name], self.unit.get(name, "mm"))
        finally:
            self.busy.discard(name)
        self.cache[name] = v
        return v

    def eval(self, text: str, unit: str = "mm") -> float:
        """SI value of ``text``; ``unit`` says what a bare number is (``mm``, ``deg`` or ``""``)."""
        if len(text) > 500:
            raise SolidCraftError("expression too long")
        scale = {"mm": 1e-3, "deg": math.pi / 180}.get(unit, 1.0)
        # "10 mm" becomes "(10*0.001/scale)" so that the whole expression is in the bare unit.
        src = _UNIT_RE.sub(
            lambda m: f"({m.group(1)}*{self._unit(m.group(2)) / scale!r})", text.replace(",", ".")
        )
        try:
            tree = ast.parse(src, mode="eval")
        except SyntaxError as e:
            raise SolidCraftError(f"expression {text!r}: {e.msg}") from e
        return self._node(tree.body, text) * scale

    @staticmethod
    def _unit(u: str) -> float:
        return LENGTH_UNITS.get(u) or ANGLE_UNITS[u]

    def _node(self, n: ast.AST, text: str) -> float:
        if (
            isinstance(n, ast.Constant)
            and isinstance(n.value, (int, float))
            and not isinstance(n.value, bool)
        ):
            return float(n.value)
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](self._node(n.left, text), self._node(n.right, text))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](self._node(n.operand, text))
        if isinstance(n, ast.Name):
            # A parameter's SI value back in this expression's bare unit.
            other = self.unit.get(n.id, "mm")
            return self.param(n.id) / {"mm": 1e-3, "deg": math.pi / 180}.get(other, 1.0)
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id in _FUNCS
            and not n.keywords
        ):
            return float(_FUNCS[n.func.id](*(self._node(a, text) for a in n.args)))
        raise SolidCraftError(f"expression {text!r}: not a supported form")


# ------------------------------------------------------------------ translation
_CONSTRAINT_FIELDS = {
    # SolidCraft type: (IR kind, point fields, curve fields)
    "coincident": ("coincident", ("p", "q"), ()),
    "horizontal": ("horizontal", (), ("l",)),
    "vertical": ("vertical", (), ("l",)),
    "horizontal_points": ("horizontal_points", ("p", "q"), ()),
    "vertical_points": ("vertical_points", ("p", "q"), ()),
    "parallel": ("parallel", (), ("a", "b")),
    "perpendicular": ("perpendicular", (), ("a", "b")),
    "collinear": ("collinear", (), ("a", "b")),
    "tangent": ("tangent", (), ("a", "b")),
    "equal": ("equal", (), ("a", "b")),
    "concentric": ("concentric", (), ("a", "b")),
    "midpoint": ("midpoint", ("p",), ("l",)),
    "point_on_curve": ("point_on_curve", ("p",), ("c",)),
    "symmetric": ("symmetric", ("p", "q"), ("l",)),
    "fix": ("fix", ("p",), ()),
}
_DIMENSION_FIELDS = {
    "length": ("length", (), ("l",)),
    "distance": ("distance", ("p", "q"), ()),
    "distance_x": ("distance_x", ("p", "q"), ()),
    "distance_y": ("distance_y", ("p", "q"), ()),
    "point_line_distance": ("point_line_distance", ("p",), ("l",)),
    "radius": ("radius", (), ("c",)),
    "diameter": ("diameter", (), ("c",)),
    "angle": ("angle", (), ("a", "b")),
}


class _Skip(Exception):
    """This feature becomes an Unsupported entry with this reason."""


def _frame(origin, x_dir, y_dir) -> tuple:
    o = _mm3(origin, "the plane origin")
    x, y = _unit3(x_dir, "the plane's x"), _unit3(y_dir, "the plane's y")
    if abs(sum(a * b for a, b in zip(x, y, strict=True))) > 1e-9:
        raise _Skip("the plane's axes are not perpendicular")
    return o, x, y


def _base_of(o, x, y) -> str | None:
    for name, (bo, bx, by) in ir.PLANES.items():
        if all(abs(a - b) < 1e-12 for a, b in zip(o + x + y, bo + bx + by, strict=True)):
            return name
    return None


def _resolve_plane(plane: dict, ex: Expressions, fmt: int, depth: int = 0) -> ir.Plane:
    """A SolidCraft sketch plane as an IR frame, or _Skip with the reason."""
    if depth > 8:
        raise _Skip("a plane defined through too many others")
    t = plane.get("type")
    if t == "origin":
        if plane.get("name") not in BASE_PLANES:
            raise _Skip(f"an origin plane named {plane.get('name')!r}")
        if plane.get("name") == "XZ" and fmt < XZ_FRAME_FORMAT:
            raise _Skip(
                f"an XZ sketch from format {fmt}, before its frame was fixed in format {XZ_FRAME_FORMAT}"
            )
        return ir.Plane.named(BASE_PLANES[plane["name"]])
    if t == "custom":
        p = plane.get("plane") or {}
        o, x, y = _frame(p.get("origin"), p.get("x_dir"), p.get("y_dir"))
        return ir.Plane(o, x, y, _base_of(o, x, y))
    if t == "offset":
        base = _resolve_plane(plane.get("base") or {}, ex, fmt, depth + 1)
        dist = ex.eval(str(plane.get("distance", "0")), "mm")
        x, y = base.x_dir, base.y_dir
        n = (x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0])
        o = tuple(a + dist * b for a, b in zip(base.origin, n, strict=True))
        return ir.Plane(
            o, x, y, None, base.base if base.parent is None else None, dist if base.parent is None else None
        )
    if t == "face":
        p = plane.get("plane") or {}
        o, x, y = _frame(p.get("origin"), p.get("x_dir"), p.get("y_dir"))
        at = plane.get("at")
        return ir.Plane(
            o,
            x,
            y,
            None,
            None,
            None,
            _mm3(at, "the face point") if at is not None else None,
            str(plane["name"]) if plane.get("name") else None,
        )
    raise _Skip(f"a sketch on a {t!r} plane is not in the IR yet")


def _sketch(f: dict, ex: Expressions, fmt: int) -> ir.Sketch:
    plane = f.get("plane") or {}
    frame = _resolve_plane(plane, ex, fmt)
    s = f.get("sketch") or {}
    for extra in ("patterns", "links", "offsets", "freeform_offsets", "wires"):
        if s.get(extra):
            raise _Skip(f"sketch {extra} are not in the IR yet")
    pts = s.get("points") or []
    curves = s.get("curves") or []

    def pid(i) -> str:
        if not isinstance(i, int) or not 0 <= i < len(pts):
            raise _Skip(f"a point index {i!r} outside the sketch")
        return ir.ORIGIN if i == 0 else str(pts[i]["id"])

    def cid(i) -> str:
        if not isinstance(i, int) or not 0 <= i < len(curves):
            raise _Skip(f"a curve index {i!r} outside the sketch")
        return str(curves[i]["id"])

    if not pts or pts[0].get("id") != "origin":
        raise _Skip("the sketch does not start with its origin point")
    out = ir.Sketch(id=str(f["id"]), name=str(f.get("name", f["id"])), plane=frame)
    out.suppressed = bool(f.get("suppressed", False))
    index = {str(p["id"]): i for i, p in enumerate(pts)}
    for p in pts[1:]:
        x, y = p["pos"]
        out.points.append(ir.Point(str(p["id"]), x * 1e-3, y * 1e-3))
        if p.get("fixed"):
            out.constraints.append(ir.Constraint(f"fix-{p['id']}", "fix", [str(p["id"])]))
    for c in curves:
        t = c.get("type")
        cons = bool(c.get("construction", False))
        if t == "line":
            out.curves.append(ir.Curve(str(c["id"]), "line", [pid(c["a"]), pid(c["b"])], None, cons))
        elif t == "circle":
            out.curves.append(ir.Curve(str(c["id"]), "circle", [pid(c["c"])], float(c["r"]) * 1e-3, cons))
        elif t == "arc":
            out.curves.append(
                ir.Curve(str(c["id"]), "arc", [pid(c["c"]), pid(c["a"]), pid(c["b"])], None, cons)
            )
        else:
            raise _Skip(f"a {t!r} curve is not in the IR yet")
        if c.get("reversed") or c.get("infinite"):
            raise _Skip("reversed or infinite curves are not in the IR yet")
    del index
    for k in s.get("constraints") or []:
        t = k.get("type")
        if t in _CONSTRAINT_FIELDS:
            kind, pf, cf = _CONSTRAINT_FIELDS[t]
            out.constraints.append(
                ir.Constraint(str(k["id"]), kind, [pid(k[a]) for a in pf], [cid(k[a]) for a in cf])
            )
        elif t in _DIMENSION_FIELDS:
            kind, pf, cf = _DIMENSION_FIELDS[t]
            if kind == "angle" and k.get("flip"):
                raise _Skip("a flipped angle dimension is not in the IR yet")
            param = k.get("param")
            if param:
                value = ex.param(param)
            else:
                v = float(k["value"])
                value = v if kind == "angle" else v * 1e-3
            out.dimensions.append(
                ir.Dimension(
                    str(k["id"]),
                    kind,
                    value,
                    [pid(k[a]) for a in pf],
                    [cid(k[a]) for a in cf],
                    param,
                    bool(k.get("driven", False)),
                )
            )
        else:
            raise _Skip(f"a {t!r} constraint is not in the IR yet")
    return out


def _extrude(f: dict, ex: Expressions, sketches: dict[str, ir.Sketch]) -> ir.Extrude:
    sk = sketches.get(str(f.get("sketch")))
    if sk is None:
        raise _Skip("its sketch is not a translated sketch")
    if f.get("targets") or f.get("thin"):
        raise _Skip("target bodies and thin extrusions are not in the IR yet")
    e = f.get("extent") or {}
    for opt in ("distance2", "start_offset", "taper", "to", "to_offset", "from"):
        if e.get(opt) not in (None, "", "0", 0):
            raise _Skip(f"the extent option {opt!r} is not in the IR yet")
    op = f.get("operation", "new_body")
    if op not in ("new_body", "join", "cut"):
        raise _Skip(f"operation {op!r}")
    direction = {"positive": "forward", "negative": "reverse", "symmetric": "midplane"}.get(
        e.get("direction", "positive")
    )
    if direction is None:
        raise _Skip(f"direction {e.get('direction')!r}")
    end = "through_all" if e.get("through_all") else "blind"
    depth = 0.0
    if end == "blind":
        depth = ex.eval(str(e.get("distance", "0")), "mm")
        if depth < 0:
            depth = -depth
            direction = {"forward": "reverse", "reverse": "forward"}.get(direction, direction)
        if direction == "midplane" and e.get("convention", "legacy_per_side") == "legacy_per_side":
            depth *= 2  # the distance was each side's
    prof = f.get("profiles") or {"type": "all"}
    if prof.get("type") == "all":
        loops = None
    elif prof.get("type") == "curves":
        loops = [[str(c) for c in loop] for loop in prof.get("loops") or []]
    else:
        raise _Skip(f"a {prof.get('type')!r} profile selection is not in the IR yet")
    names = f.get("param_names") or []
    return ir.Extrude(
        id=str(f["id"]),
        name=str(f.get("name", f["id"])),
        sketch=sk.id,
        depth=depth,
        operation=op,
        direction=direction,
        end=end,
        profile=loops,
        depth_parameter=str(names[0]) if names and end == "blind" else None,
        suppressed=bool(f.get("suppressed", False)),
    )


def _mm3(v, what: str) -> tuple[float, float, float]:
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise _Skip(f"{what} is not a point")
    return tuple(float(c) * 1e-3 for c in v)


def _unit3(v, what: str) -> tuple[float, float, float]:
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise _Skip(f"{what} is not a direction")
    n = math.sqrt(sum(float(c) ** 2 for c in v))
    if not n:
        raise _Skip(f"{what} has no length")
    return tuple(float(c) / n for c in v)


def _count(ex: Expressions, text) -> int:
    v = ex.eval(str(text), "")
    if abs(v - round(v)) > 1e-9 or v < 1:
        raise _Skip(f"a count of {text!r} is not a whole number")
    return int(round(v))


def _edges(f: dict) -> list[ir.EdgeRef]:
    pts = f.get("edges") or []
    names = f.get("edge_names") or []
    if not pts:
        raise _Skip("no edges")
    return [
        ir.EdgeRef(_mm3(p, "an edge point"), names[i] if i < len(names) else None) for i, p in enumerate(pts)
    ]


def _first_param(f: dict) -> str | None:
    names = f.get("param_names") or []
    return str(names[0]) if names else None


def _revolve(f: dict, ex: Expressions, sketches: dict[str, ir.Sketch]) -> ir.Revolve:
    sk = sketches.get(str(f.get("sketch")))
    if sk is None:
        raise _Skip("its sketch is not a translated sketch")
    if f.get("targets") or f.get("to"):
        raise _Skip("target bodies and Up To are not in the IR yet")
    angle = ex.eval(str(f.get("angle", "360")), "deg")
    full = abs(angle - 2 * math.pi) < 1e-9
    if not full and not f.get("symmetric") and f.get("convention", "legacy_axis_start") != "sketch_normal":
        raise _Skip("a partial revolve's side follows SolidCraft's legacy convention, not mapped yet")
    if f.get("angle2") not in (None, ""):
        raise _Skip("two-sided revolves are not in the IR yet")
    a = f.get("axis") or {}
    t = a.get("type")
    if t == "sketch_line":
        axis = ir.Axis("sketch_line", curve=str(a["curve"]))
    elif t == "sketch_axis" and a.get("axis") in ("x", "y"):
        axis = ir.Axis(f"sketch_{a['axis']}")
    elif t == "world" and a.get("axis") in ("X", "Y", "Z", "x", "y", "z"):
        d = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}[a["axis"].lower()]
        axis = ir.Axis("model", origin=(0.0, 0.0, 0.0), direction=d)
    elif t == "line":
        axis = ir.Axis(
            "model",
            origin=_mm3(a.get("origin"), "the axis origin"),
            direction=_unit3(a.get("dir"), "the axis"),
        )
    else:
        raise _Skip(f"a {t!r} revolve axis")
    op = f.get("operation", "new_body")
    if op not in ("new_body", "join", "cut"):
        raise _Skip(f"operation {op!r}")
    prof = f.get("profiles") or {"type": "all"}
    if prof.get("type") not in ("all", "curves"):
        raise _Skip(f"a {prof.get('type')!r} profile selection is not in the IR yet")
    loops = (
        None if prof.get("type") == "all" else [[str(c) for c in loop] for loop in prof.get("loops") or []]
    )
    return ir.Revolve(
        id=str(f["id"]),
        name=str(f.get("name", f["id"])),
        sketch=sk.id,
        axis=axis,
        angle=angle,
        operation=op,
        direction="midplane" if f.get("symmetric") else "forward",
        profile=loops,
        angle_parameter=_first_param(f),
        suppressed=bool(f.get("suppressed", False)),
    )


def _fillet(f: dict, ex: Expressions) -> ir.Fillet:
    for opt in ("style", "fit", "corner"):
        if f.get(opt) not in (None, "constant", "exact", "rolling", {"type": "constant"}):
            raise _Skip(f"fillet option {opt!r} is not in the IR yet")
    return ir.Fillet(
        str(f["id"]),
        str(f.get("name", f["id"])),
        _edges(f),
        ex.eval(str(f["radius"]), "mm"),
        _first_param(f),
        bool(f.get("suppressed", False)),
    )


def _chamfer(f: dict, ex: Expressions) -> ir.Chamfer:
    if f.get("flip"):
        raise _Skip("a flipped chamfer's side is not in the IR yet")
    d2 = f.get("distance2")
    ang = f.get("angle")
    return ir.Chamfer(
        str(f["id"]),
        str(f.get("name", f["id"])),
        _edges(f),
        ex.eval(str(f["distance"]), "mm"),
        ex.eval(str(d2), "mm") if d2 not in (None, "") else None,
        ex.eval(str(ang), "deg") if ang not in (None, "") else None,
        _first_param(f),
        bool(f.get("suppressed", False)),
    )


def _hole(f: dict, ex: Expressions) -> ir.Hole:
    if f.get("points") or f.get("to") or f.get("thread"):
        raise _Skip("holes at sketch points, Up To and threads are not in the IR yet")
    kind = (f.get("hole") or {"type": "simple"}).get("type", "simple")
    h = f.get("hole") or {}
    out = ir.Hole(
        str(f["id"]),
        str(f.get("name", f["id"])),
        [_mm3(f.get("position"), "the hole position")],
        _unit3(f.get("direction"), "the drilling direction"),
        ex.eval(str(f["diameter"]), "mm"),
        ex.eval(str(f["depth"]), "mm") if f.get("depth") not in (None, "") else None,
        suppressed=bool(f.get("suppressed", False)),
    )
    if kind == "simple":
        return out
    if kind == "counterbore":
        out.kind, out.cb_diameter, out.cb_depth = (
            kind,
            ex.eval(str(h["cb_diameter"]), "mm"),
            ex.eval(str(h["cb_depth"]), "mm"),
        )
        return out
    if kind == "countersink":
        out.kind, out.cs_diameter, out.cs_angle = (
            kind,
            ex.eval(str(h["cs_diameter"]), "mm"),
            ex.eval(str(h["cs_angle"]), "deg"),
        )
        return out
    raise _Skip(f"a {kind!r} hole is not in the IR yet")


def _pattern(f: dict, ex: Expressions, by_name: dict[str, str]) -> ir.Pattern:
    if f.get("bodies"):
        raise _Skip("body patterns are not in the IR yet")
    feats = [by_name.get(str(n)) for n in f.get("features") or []]
    if not feats or None in feats:
        raise _Skip("it copies a feature that is not translated")
    p = f.get("pattern") or {}
    for opt in ("alignment", "reversed"):
        if p.get(opt) not in (None, False, "same", "Same"):
            raise _Skip(f"pattern option {opt!r} is not in the IR yet")
    base = dict(
        id=str(f["id"]),
        name=str(f.get("name", f["id"])),
        features=feats,
        suppressed=bool(f.get("suppressed", False)),
    )
    if p.get("type") == "rectangular":
        out = ir.Pattern(
            **base,
            kind="linear",
            direction1=_unit3(p.get("dir1"), "direction 1"),
            count1=_count(ex, p.get("count1", 1)),
            spacing1=ex.eval(str(p.get("spacing1", "0")), "mm"),
        )
        if p.get("dir2") is not None:
            out.direction2 = _unit3(p["dir2"], "direction 2")
            out.count2 = _count(ex, p.get("count2", 1))
            out.spacing2 = ex.eval(str(p.get("spacing2", "0")), "mm")
        return out
    if p.get("type") == "circular":
        return ir.Pattern(
            **base,
            kind="circular",
            origin=_mm3(p.get("origin"), "the pattern centre"),
            axis=_unit3(p.get("axis"), "the pattern axis"),
            count1=_count(ex, p.get("count", 1)),
            angle=ex.eval(str(p.get("angle", "360")), "deg"),
        )
    raise _Skip(f"a {p.get('type')!r} pattern is not in the IR yet")


def _mirror(f: dict, by_name: dict[str, str]) -> ir.Mirror:
    if f.get("bodies") or f.get("combine"):
        raise _Skip("body mirrors are not in the IR yet")
    feats = [by_name.get(str(n)) for n in f.get("features") or []]
    if not feats or None in feats:
        raise _Skip("it mirrors a feature that is not translated")
    plane = f.get("plane") or {}
    if plane.get("type") != "origin" or plane.get("name") not in BASE_PLANES:
        raise _Skip(f"a mirror about a {plane.get('type')!r} plane (only the base planes for now)")
    return ir.Mirror(
        str(f["id"]),
        str(f.get("name", f["id"])),
        feats,
        ir.Plane.named(BASE_PLANES[plane["name"]]),
        bool(f.get("suppressed", False)),
    )


def to_ir(doc: dict, *, file_name: str | None = None) -> ir.Document:
    """Translate a loaded SolidCraft document. Unsupported features stay in the timeline as such."""
    params = doc.get("params") or []
    ex = Expressions(params)
    fmt = int(FORMAT_RE.match(str(doc.get("format", ""))).group(1))
    out = ir.Document(
        name=str(doc.get("name") or "part"),
        source={"system": "SolidCraft", "format": doc.get("format"), "file": file_name},
    )
    for p in params:
        unit = {"mm": "length", "deg": "angle"}.get(p.get("unit", "mm"), "number")
        out.parameters.append(
            ir.Parameter(str(p["name"]), ex.param(p["name"]), unit, str(p.get("expr", "")), True)
        )
    if doc.get("components") or doc.get("occurrences") or (doc.get("configs") or {}).get("rows"):
        raise SolidCraftError("assemblies and configurations are not in the IR yet")
    marker = doc.get("marker")
    sketches: dict[str, ir.Sketch] = {}
    by_name: dict[str, str] = {}  # translated features by their SolidCraft name, for patterns and mirrors
    features = doc["features"] if marker is None else doc["features"][: int(marker)]
    for f in features:
        t = f.get("type")
        try:
            if t == "sketch":
                s = _sketch(f, ex, fmt)
                sketches[s.id] = s
                out.features.append(s)
            elif t == "extrude":
                out.features.append(_extrude(f, ex, sketches))
                # A depth parameter SolidCraft names only on the feature is a parameter here too.
                last = out.features[-1]
                known = {p.name for p in out.parameters}
                if (
                    isinstance(last, ir.Extrude)
                    and last.depth_parameter
                    and last.depth_parameter not in known
                ):
                    out.parameters.append(
                        ir.Parameter(
                            last.depth_parameter, last.depth, "length", str(f["extent"].get("distance"))
                        )
                    )
            elif t == "revolve":
                out.features.append(_revolve(f, ex, sketches))
            elif t == "fillet":
                out.features.append(_fillet(f, ex))
            elif t == "chamfer":
                out.features.append(_chamfer(f, ex))
            elif t == "hole":
                out.features.append(_hole(f, ex))
            elif t == "pattern":
                out.features.append(_pattern(f, ex, by_name))
            elif t == "mirror":
                out.features.append(_mirror(f, by_name))
            else:
                raise _Skip(f"SolidCraft {t!r} features are not in the IR yet")
            if not isinstance(out.features[-1], ir.Unsupported):
                by_name[str(f.get("name", f.get("id")))] = out.features[-1].id
        except _Skip as why:
            out.features.append(
                ir.Unsupported(str(f.get("id")), str(f.get("name", f.get("id"))), str(t), str(why))
            )
    return ir.validate(out)


def read_ir(source: str | Path | bytes) -> ir.Document:
    name = None if isinstance(source, (bytes, bytearray)) else Path(source).name
    return to_ir(load(source), file_name=name)
