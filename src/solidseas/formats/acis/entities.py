"""The ACIS entities SolidSeas decodes from a tokenized SAB stream (provisional,
``docs/formats/alibre.md``).

Every record is tokenized whatever its class (:mod:`.sab`); this module decodes
the classes a B-rep needs, at the record layouts verified for SAB version 2100:
topology (body, lump, shell, face, loop, coedge, edge, vertex, ``tvertex``; a
``tedge`` and ``tcoedge`` as an ordinary edge and coedge, a tedge's tolerance not
read), points, the body transform, surfaces (plane, cone, sphere, torus, spline)
and curves (straight, ellipse, intcurve), and two attributes
(``rgb_color-st-attrib`` and ``PersistentID-Alibre-attrib``). Each topology and
geometry record starts with an attribute pointer, two integers and a pointer; a
transform with an attribute pointer and one integer; an attribute with an
attribute pointer, an integer and its ``next``, ``previous`` and ``owner``
pointers.

Decoding checks the tag of every value it takes and every pointer against the
records' count and type, every time a decoder meets a record it has not decoded
before (one record may be asked for by several), so a damaged or crafted record
raises :class:`AcisError` with a reason; the caller decides whether that costs a
face or the body. A ``ref n`` subtype is followed to definition ``n``.
"""

import math
from dataclasses import dataclass

from .._source import Clock
from ..limits import Limits
from .bspline import (
    CURVE_SUBTYPES,
    SURFACE_SUBTYPES,
    BS3Curve,
    BS3Surface,
    SplineError,
    Values,
    read_curve,
    read_surface,
)
from .sab import (
    T_DOUBLE,
    T_DOUBLE2,
    T_ENUM,
    T_FALSE,
    T_IDENT,
    T_INT,
    T_POS,
    T_PTR,
    T_SUB_START,
    T_TRUE,
    T_VEC,
    SabFile,
)

Vec = tuple[float, float, float]


class AcisError(ValueError):
    """A record that does not decode as the class it claims: ``reason`` is an open set
    (``bad_reference``, ``unexpected_value``, ``cut_short``, ``unsupported_surface``,
    ``unsupported_curve``, ``bad_geometry``...)."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason, self.detail = reason, detail


# --------------------------------------------------------------------------- decoded classes
@dataclass(frozen=True)
class Body:
    lump: int | None
    transform: int | None


@dataclass(frozen=True)
class Lump:
    next: int | None
    shell: int | None
    body: int | None


@dataclass(frozen=True)
class Shell:
    next: int | None
    subshell: int | None
    face: int | None
    lump: int | None


@dataclass(frozen=True)
class Face:
    next: int | None
    loop: int | None
    shell: int | None
    surface: int | None
    reversed: bool
    double_sided: bool


@dataclass(frozen=True)
class Loop:
    next: int | None
    coedge: int | None
    face: int | None


@dataclass(frozen=True)
class Coedge:
    next: int | None
    previous: int | None
    partner: int | None
    edge: int | None
    reversed: bool
    loop: int | None


@dataclass(frozen=True)
class Edge:
    start: int | None
    start_param: float
    end: int | None
    end_param: float
    coedge: int | None
    curve: int | None
    reversed: bool


@dataclass(frozen=True)
class Vertex:
    edge: int | None
    point: int | None
    tolerance: float | None


@dataclass(frozen=True)
class Transform:
    rows: tuple[Vec, Vec, Vec]
    translation: Vec
    scale: float
    rotate: bool
    reflect: bool
    shear: bool

    @property
    def identity(self) -> bool:
        eye = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        return (
            all(abs(self.rows[i][j] - eye[i][j]) < 1e-12 for i in range(3) for j in range(3))
            and all(abs(x) < 1e-12 for x in self.translation)
            and abs(self.scale - 1.0) < 1e-12
            and not self.reflect
            and not self.shear
        )


@dataclass(frozen=True)
class Plane:
    root: Vec
    normal: Vec
    u_dir: Vec
    reverse_v: bool


@dataclass(frozen=True)
class Cone:
    """Its base ellipse (``centre``, ``axis`` the ellipse's normal, ``major`` the major
    axis vector, ``ratio`` minor to major), the sine and cosine of the half angle, the
    u scale and the reversed-u flag."""

    centre: Vec
    axis: Vec
    major: Vec
    ratio: float
    sine: float
    cosine: float
    u_scale: float
    reverse_u: bool


@dataclass(frozen=True)
class Sphere:
    centre: Vec
    radius: float
    u_dir: Vec
    pole: Vec
    reverse_v: bool


@dataclass(frozen=True)
class Torus:
    centre: Vec
    axis: Vec
    major: float
    minor: float
    u_dir: Vec
    reverse_v: bool


@dataclass(frozen=True)
class Spline:
    """A ``spline-surface``: ``reversed`` its sense, ``subtype`` the keyword of the
    definition it holds or names, ``bs3`` the B-spline (None when the definition
    holds none SolidSeas reads)."""

    reversed: bool
    subtype: str
    bs3: BS3Surface | None


@dataclass(frozen=True)
class Straight:
    root: Vec
    direction: Vec


@dataclass(frozen=True)
class Ellipse:
    centre: Vec
    normal: Vec
    major: Vec
    ratio: float


@dataclass(frozen=True)
class IntCurve:
    reversed: bool
    subtype: str
    bs3: BS3Curve | None


SURFACE_CLASSES = {
    "plane-surface": "plane",
    "cone-surface": "cone",
    "sphere-surface": "sphere",
    "torus-surface": "torus",
    "spline-surface": "spline",
}
CURVE_CLASSES = {"straight-curve": "straight", "ellipse-curve": "ellipse", "intcurve-curve": "intcurve"}


# --------------------------------------------------------------------------- the model
class Model:
    """A tokenized SAB stream with decoders for the classes above. A record is decoded
    once for each decoder that asks for it: the cache is keyed by the decoder as well as
    the record, so a pointer that leads to a record already decoded as another class
    still meets the type check and fails with ``bad_reference``. ``limits`` bounds
    the B-splines."""

    def __init__(self, sab: SabFile, limits: Limits) -> None:
        self.sab = sab
        self.header = sab.header
        self.records = sab.records
        self.limits = limits
        self._cache: dict[tuple[str, int], object] = {}
        self._owned: dict[int, list[int]] | None = None
        self._faces_by_shell: dict[int, list[int]] | None = None

    # -- records ----------------------------------------------------------------------
    def type_of(self, index: int) -> str:
        return self.records[index].name

    def indices(self, name: str) -> list[int]:
        return [i for i, r in enumerate(self.records) if r.name == name]

    def _cursor(self, index: int, expect: str | tuple[str, ...]) -> Values:
        if not isinstance(index, int) or not 0 <= index < len(self.records):
            raise AcisError("bad_reference", "a pointer leads to no record")
        rec = self.records[index]
        names = (expect,) if isinstance(expect, str) else expect
        if rec.name not in names:
            raise AcisError("bad_reference", f"a pointer to a {names[0]} leads to a {rec.name[:40]}")
        return Values(rec.tags, rec.vals)

    def _ptr(self, c: Values) -> int | None:
        """A pointer: None for -1, else the record index, checked when it is followed (a
        pointer past the last record then fails with ``bad_reference``)."""
        v = _take(c, T_PTR)
        return None if v == -1 else v

    def _prefix(self, c: Values) -> None:
        """The attribute pointer, two integers and a pointer every topology and geometry
        record starts with (version 2100)."""
        _take(c, T_PTR)
        _take(c, T_INT)
        _take(c, T_INT)
        _take(c, T_PTR)

    def _cached(self, kind: str, index: int, build):
        """The record ``index`` as decoder ``kind`` decodes it, built once."""
        key = (kind, index)
        hit = self._cache.get(key)
        if hit is None:
            try:
                hit = build()
            except SplineError as exc:
                raise AcisError(exc.reason, exc.detail) from None
            self._cache[key] = hit
        return hit

    # -- topology ---------------------------------------------------------------------
    def body(self, i: int) -> Body:
        def build():
            c = self._cursor(i, "body")
            self._prefix(c)
            lump = self._ptr(c)
            self._ptr(c)  # wire
            transform = self._ptr(c)
            return Body(lump, transform)

        return self._cached("body", i, build)

    def lump(self, i: int) -> Lump:
        def build():
            c = self._cursor(i, "lump")
            self._prefix(c)
            return Lump(self._ptr(c), self._ptr(c), self._ptr(c))

        return self._cached("lump", i, build)

    def shell(self, i: int) -> Shell:
        def build():
            c = self._cursor(i, "shell")
            self._prefix(c)
            nxt, sub, face = self._ptr(c), self._ptr(c), self._ptr(c)
            self._ptr(c)  # wire
            return Shell(nxt, sub, face, self._ptr(c))

        return self._cached("shell", i, build)

    def face(self, i: int) -> Face:
        def build():
            c = self._cursor(i, "face")
            self._prefix(c)
            nxt, loop, shell = self._ptr(c), self._ptr(c), self._ptr(c)
            self._ptr(c)  # subshell
            surface = self._ptr(c)
            rev = _bool(c)
            double = _bool(c)
            return Face(nxt, loop, shell, surface, rev, double)

        return self._cached("face", i, build)

    def loop(self, i: int) -> Loop:
        def build():
            c = self._cursor(i, "loop")
            self._prefix(c)
            return Loop(self._ptr(c), self._ptr(c), self._ptr(c))

        return self._cached("loop", i, build)

    def coedge(self, i: int) -> Coedge:
        def build():
            c = self._cursor(i, ("coedge", "tcoedge-coedge"))
            self._prefix(c)
            nxt, prev, partner, edge = self._ptr(c), self._ptr(c), self._ptr(c), self._ptr(c)
            rev = _bool(c)
            return Coedge(nxt, prev, partner, edge, rev, self._ptr(c))

        return self._cached("coedge", i, build)

    def edge(self, i: int) -> Edge:
        def build():
            c = self._cursor(i, ("edge", "tedge-edge"))
            self._prefix(c)
            start = self._ptr(c)
            sp = _number(c)
            end = self._ptr(c)
            ep = _number(c)
            coedge = self._ptr(c)
            curve = self._ptr(c)
            rev = _bool(c)
            return Edge(start, sp, end, ep, coedge, curve, rev)

        return self._cached("edge", i, build)

    def vertex(self, i: int) -> Vertex:
        def build():
            c = self._cursor(i, ("vertex", "tvertex-vertex"))
            self._prefix(c)
            edge, point = self._ptr(c), self._ptr(c)
            tol = None
            if self.records[i].name == "tvertex-vertex" and c.peek() in (T_DOUBLE, T_DOUBLE2):
                tol = _number(c)
            return Vertex(edge, point, tol)

        return self._cached("vertex", i, build)

    def point(self, i: int) -> Vec:
        def build():
            c = self._cursor(i, "point")
            self._prefix(c)
            return _vec(c, T_POS)

        return self._cached("point", i, build)

    def transform(self, i: int) -> Transform:
        def build():
            c = self._cursor(i, "transform")
            _take(c, T_PTR)
            _take(c, T_INT)
            rows = (_vec(c), _vec(c), _vec(c))
            t = _vec(c)
            scale = _number(c)
            flags = [_bool(c) for _ in range(3)]
            return Transform(rows, t, scale, *flags)

        return self._cached("transform", i, build)

    # -- geometry ---------------------------------------------------------------------
    def surface(self, i: int, clock: Clock | None = None):
        """The decoded surface of record ``i``; :class:`AcisError` with reason
        ``unsupported_surface`` for a class or subtype SolidSeas does not decode.
        ``clock`` is ticked once a B-spline control point."""

        def build():
            if not isinstance(i, int) or not 0 <= i < len(self.records):
                raise AcisError("bad_reference", "a face's surface pointer leads to no record")
            name = self.records[i].name
            kind = SURFACE_CLASSES.get(name)
            if kind is None:
                raise AcisError("unsupported_surface", name[:60])
            c = self._cursor(i, name)
            self._prefix(c)
            if kind == "plane":
                return Plane(_vec(c, T_POS), _vec(c), _vec(c), _bool(c))
            if kind == "cone":
                centre, axis, major = _vec(c, T_POS), _vec(c), _vec(c)
                ratio = _number(c)
                _interval(c)
                sine, cosine, u_scale = _number(c), _number(c), _number(c)
                return Cone(centre, axis, major, ratio, sine, cosine, u_scale, _bool(c))
            if kind == "sphere":
                centre = _vec(c, T_POS)
                radius = _number(c)
                return Sphere(centre, radius, _vec(c), _vec(c), _bool(c))
            if kind == "torus":
                centre, axis = _vec(c, T_POS), _vec(c)
                major, minor = _number(c), _number(c)
                return Torus(centre, axis, major, minor, _vec(c), _bool(c))
            rev = _bool(c)
            subtype, bs3 = self._subtype_surface(i, c, clock)
            return Spline(rev, subtype, bs3)

        return self._cached("surface", i, build)

    def curve(self, i: int, clock: Clock | None = None):
        """The decoded curve of record ``i``; :class:`AcisError` with reason
        ``unsupported_curve`` for a class or subtype SolidSeas does not decode.
        ``clock`` is ticked once a B-spline control point."""

        def build():
            if not isinstance(i, int) or not 0 <= i < len(self.records):
                raise AcisError("bad_reference", "an edge's curve pointer leads to no record")
            name = self.records[i].name
            kind = CURVE_CLASSES.get(name)
            if kind is None:
                raise AcisError("unsupported_curve", name[:60])
            c = self._cursor(i, name)
            self._prefix(c)
            if kind == "straight":
                return Straight(_vec(c, T_POS), _vec(c))
            if kind == "ellipse":
                centre, normal, major = _vec(c, T_POS), _vec(c), _vec(c)
                return Ellipse(centre, normal, major, _number(c))
            rev = _bool(c)
            subtype, bs3 = self._subtype_curve(i, c, clock)
            return IntCurve(rev, subtype, bs3)

        return self._cached("curve", i, build)

    def _definition(self, record: int, c: Values) -> tuple[str, Values]:
        """The subtype at the cursor (``{ keyword ...``), a ``ref n`` followed: its keyword
        and a cursor just after the keyword."""
        _take(c, T_SUB_START)
        kw = _take(c, T_IDENT)
        hops = 0
        while kw == "ref":
            n = _take(c, T_INT)
            if not 0 <= n < len(self.sab.subtypes):
                raise AcisError("bad_reference", "a subtype reference names no definition")
            rec, at = self.sab.subtypes[n]
            r = self.records[rec]
            c = Values(r.tags, r.vals, at)
            _take(c, T_SUB_START)
            kw = _take(c, T_IDENT)
            hops += 1
            if hops > 1:  # a definition is never itself a reference
                raise AcisError("bad_reference", "a subtype reference leads to another reference")
        return kw, c

    def _subtype_surface(self, record: int, c: Values, clock: Clock | None) -> tuple[str, BS3Surface | None]:
        kw, c = self._definition(record, c)
        if kw not in SURFACE_SUBTYPES:
            return kw, None
        _take(c, T_ENUM)
        return kw, read_surface(c, self.limits, clock)

    def _subtype_curve(self, record: int, c: Values, clock: Clock | None) -> tuple[str, BS3Curve | None]:
        kw, c = self._definition(record, c)
        if kw not in CURVE_SUBTYPES:
            return kw, None
        _take(c, T_ENUM)
        return kw, read_curve(c, self.limits, clock=clock)

    # -- faces by shell ------------------------------------------------------------------
    def faces_by_shell(self, clock: Clock | None = None) -> dict[int, list[int]]:
        """Face records by the shell their ``shell`` pointer names, in record order,
        built once (a face that does not decode is left out). It lets every body find
        its faces outside its shells' chains without a pass over every record each."""
        if self._faces_by_shell is None:
            out: dict[int, list[int]] = {}
            for f, r in enumerate(self.records):
                if r.name != "face":
                    continue
                if clock is not None:
                    clock.tick()
                try:
                    shell = self.face(f).shell
                except AcisError:
                    continue
                if shell is not None:
                    out.setdefault(shell, []).append(f)
            self._faces_by_shell = out
        return self._faces_by_shell

    # -- attributes -------------------------------------------------------------------
    def owned(self) -> dict[int, list[int]]:
        """Attribute records by the entity that owns them."""
        if self._owned is None:
            out: dict[int, list[int]] = {}
            for i, r in enumerate(self.records):
                if not r.name.endswith("attrib"):
                    continue
                t = r.tags
                if (
                    len(t) >= 5
                    and t[0] == T_PTR
                    and t[1] == T_INT
                    and t[2] == T_PTR
                    and t[3] == T_PTR
                    and t[4] == T_PTR
                ):
                    owner = r.vals[4]
                    if isinstance(owner, int) and 0 <= owner < len(self.records):
                        out.setdefault(owner, []).append(i)
            self._owned = out
        return self._owned

    def rgb_color(self, owner: int) -> tuple[float, float, float] | None:
        """The ``rgb_color-st-attrib`` colour an entity carries, each from 0 to 1."""
        for a in self.owned().get(owner, ()):
            r = self.records[a]
            if r.name != "rgb_color-st-attrib":
                continue
            ds = [v for t, v in zip(r.tags, r.vals, strict=True) if t in (T_DOUBLE, T_DOUBLE2)]
            if len(ds) >= 3 and all(math.isfinite(x) and 0.0 <= x <= 1.0 for x in ds[:3]):
                return (ds[0], ds[1], ds[2])
        return None

    def persistent_ids(self, name: str = "PersistentID-Alibre-attrib") -> dict[int, int]:
        """Entity to the last integer of the named attribute (Alibre's face and edge ids)."""
        out: dict[int, int] = {}
        for owner, attrs in self.owned().items():
            for a in attrs:
                r = self.records[a]
                if r.name == name:
                    ints = [v for t, v in zip(r.tags, r.vals, strict=True) if t == T_INT]
                    if len(ints) >= 2:
                        out[owner] = ints[-1]
        return out


# --------------------------------------------------------------------------- values
def _take(c: Values, tag: int):
    try:
        return c.take(tag)
    except SplineError as exc:
        raise AcisError(exc.reason, exc.detail) from None


def _bool(c: Values) -> bool:
    try:
        return bool(c.take(T_TRUE, T_FALSE))
    except SplineError as exc:
        raise AcisError(exc.reason, exc.detail) from None


def _number(c: Values) -> float:
    try:
        return float(c.take(T_DOUBLE, T_DOUBLE2))
    except SplineError as exc:
        raise AcisError(exc.reason, exc.detail) from None


def _vec(c: Values, *tags: int) -> Vec:
    try:
        v = c.take(*(tags or (T_VEC, T_POS)))
    except SplineError as exc:
        raise AcisError(exc.reason, exc.detail) from None
    return v


def _interval(c: Values) -> None:
    """A curve's range: two bounds, each false (unbounded) or true and a double."""
    for _ in range(2):
        if _bool(c):
            _number(c)


__all__ = [
    "CURVE_CLASSES",
    "SURFACE_CLASSES",
    "AcisError",
    "Body",
    "Coedge",
    "Cone",
    "Edge",
    "Ellipse",
    "Face",
    "IntCurve",
    "Loop",
    "Lump",
    "Model",
    "Plane",
    "Shell",
    "Sphere",
    "Spline",
    "Straight",
    "Torus",
    "Transform",
    "Vertex",
]
