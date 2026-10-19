"""ACIS B-splines (``bs3_surface`` and ``bs3_curve``) as SAB stores them, and their XT
form (provisional, ``docs/formats/alibre.md``).

A surface block, after its subtype keyword (``exactsur``) and an enum, is: the form
``nurbs``, ``nubs`` or ``nullbs`` (no spline), the u and v degrees, for ``nurbs`` a
rational keyword (``both``, ``u`` or ``v``), the closure of u and of v (0 open, 1
closed, 2 periodic), the singularity of u and of v, the numbers of distinct u and
v knots, (value, multiplicity) pairs for u and then v, the control points (x, y,
z, then the weight when rational, not premultiplied, with u varying fastest) and
the fit tolerance. A curve block (``exactcur``, ``surfcur``, ``surfintcur``,
``parcur``) is the same in one direction, with no rational keyword: the form,
the degree, the closure, the number of distinct knots, the pairs, the control
points (four numbers each for ``nurbs``) and the fit tolerance.

The end knots carry multiplicity ``degree``, so the clamped knot vector XT wants
(``n + degree + 1`` knots) has one knot more at each end; XT stores a surface's
control points with v varying fastest and rational ones homogeneous. Every
count is checked against the values left in the record before anything is
built, and the number of distinct knots against ``bspline_knots``; a knot must be a
finite number, larger than the one before it. A clock, when given, is ticked once
a control point.
"""

import math
from dataclasses import dataclass

from .._source import Clock
from ..limits import Limits

FORMS = ("nurbs", "nubs", "nullbs")
CURVE_SUBTYPES = frozenset({"exactcur", "surfcur", "surfintcur", "parcur"})
SURFACE_SUBTYPES = frozenset({"exactsur"})


class SplineError(ValueError):
    """A B-spline block that does not decode: ``reason`` says why (an open set)."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason, self.detail = reason, detail


@dataclass(frozen=True)
class BS3Surface:
    """A decoded surface block. ``points[i_v * nu + i_u]`` are Cartesian, ``weights``
    parallel to them (None when not rational)."""

    form: str
    degree_u: int
    degree_v: int
    rational: bool
    closure_u: int
    closure_v: int
    singular_u: int
    singular_v: int
    knots_u: tuple[tuple[float, int], ...]
    knots_v: tuple[tuple[float, int], ...]
    nu: int
    nv: int
    points: tuple[tuple[float, float, float], ...]
    weights: tuple[float, ...] | None
    fit_tolerance: float | None


@dataclass(frozen=True)
class BS3Curve:
    """A decoded curve block: ``points`` Cartesian (``dim`` numbers each, 3 for a 3D
    curve), ``weights`` when rational."""

    form: str
    degree: int
    rational: bool
    closure: int
    knots: tuple[tuple[float, int], ...]
    points: tuple[tuple[float, ...], ...]
    weights: tuple[float, ...] | None
    fit_tolerance: float | None


class Values:
    """A cursor over one record's tagged values, from ``i``."""

    __slots__ = ("i", "tags", "vals")

    def __init__(self, tags: bytes, vals: list, i: int = 0) -> None:
        self.tags, self.vals, self.i = tags, vals, i

    def left(self) -> int:
        return len(self.vals) - self.i

    def peek(self) -> int | None:
        return self.tags[self.i] if self.i < len(self.vals) else None

    def take(self, *tags: int):
        if self.i >= len(self.vals):
            raise SplineError("cut_short", "the record ends early")
        t = self.tags[self.i]
        if tags and t not in tags:
            raise SplineError(
                "unexpected_value", f"tag {t:#04x} where {', '.join(f'{x:#04x}' for x in tags)} belongs"
            )
        v = self.vals[self.i]
        self.i += 1
        return v


_INT, _DOUBLE, _IDENT, _ENUM, _DOUBLE2 = 0x04, 0x06, 0x0D, 0x15, 0x17


def _int(c: Values) -> int:
    return c.take(_INT)


def _double(c: Values) -> float:
    return c.take(_DOUBLE, _DOUBLE2)


def _knots(c: Values, count: int, limits: Limits) -> tuple[tuple[float, int], ...]:
    if count < 1:
        raise SplineError("bad_counts", "a knot list is empty")
    if count > limits.bspline_knots:
        raise limits.exceeded("bspline_knots", f"a B-spline has more than {limits.bspline_knots:,} knots")
    if 2 * count > c.left():
        raise SplineError("bad_counts", "more knots than the record holds")
    out = []
    last = None
    for _ in range(count):
        k = _double(c)
        m = _int(c)
        if not math.isfinite(k):
            raise SplineError("bad_knots", "a knot is not a finite number")
        if m < 1 or (last is not None and not k > last):
            raise SplineError("bad_knots", "knots are not increasing or a multiplicity is not positive")
        out.append((k, m))
        last = k
    return tuple(out)


def control_count(degree: int, knots: tuple[tuple[float, int], ...]) -> int:
    """Control points of a B-spline of ``degree`` over ``knots`` (end multiplicity ``degree``)."""
    return sum(m for _k, m in knots) - degree + 1


def _degree(c: Values) -> int:
    d = _int(c)
    if not 1 <= d <= 32:
        raise SplineError("bad_degree", f"degree {d}")
    return d


def read_surface(c: Values, limits: Limits, clock: Clock | None = None) -> BS3Surface | None:
    """A surface block from the form keyword on (the cursor after the subtype keyword
    and its enum); None for ``nullbs``."""
    form = c.take(_IDENT)
    if form not in FORMS:
        raise SplineError("unknown_form", repr(form)[:40])
    if form == "nullbs":
        return None
    du, dv = _degree(c), _degree(c)
    rational = False
    if form == "nurbs":
        kind = c.take(_IDENT)
        if kind not in ("both", "u", "v"):
            raise SplineError("unknown_form", f"rational {kind!r}"[:40])
        rational = True
    cu, cv, su, sv = (c.take(_ENUM) for _ in range(4))
    nku, nkv = _int(c), _int(c)
    ku = _knots(c, nku, limits)
    kv = _knots(c, nkv, limits)
    nu, nv = control_count(du, ku), control_count(dv, kv)
    if nu < 2 or nv < 2:
        raise SplineError("bad_counts", f"{nu} x {nv} control points")
    dim = 4 if rational else 3
    if nu * nv * dim > c.left():
        raise SplineError("bad_counts", "more control points than the record holds")
    pts, weights = [], [] if rational else None
    for _ in range(nu * nv):
        if clock is not None:
            clock.tick()
        p = (_double(c), _double(c), _double(c))
        pts.append(p)
        if rational:
            weights.append(_double(c))
    tol = _double(c) if c.peek() in (_DOUBLE, _DOUBLE2) else None
    return BS3Surface(
        form,
        du,
        dv,
        rational,
        cu,
        cv,
        su,
        sv,
        ku,
        kv,
        nu,
        nv,
        tuple(pts),
        None if weights is None else tuple(weights),
        tol,
    )


def read_curve(c: Values, limits: Limits, dim: int = 3, clock: Clock | None = None) -> BS3Curve | None:
    """A curve block from the form keyword on; ``dim`` 3 for a space curve, 2 for a
    parameter-space curve. None for ``nullbs``."""
    form = c.take(_IDENT)
    if form not in FORMS:
        raise SplineError("unknown_form", repr(form)[:40])
    if form == "nullbs":
        return None
    d = _degree(c)
    closure = c.take(_ENUM)
    nk = _int(c)
    knots = _knots(c, nk, limits)
    n = control_count(d, knots)
    if n < 2:
        raise SplineError("bad_counts", f"{n} control points")
    rational = form == "nurbs"
    per = dim + (1 if rational else 0)
    if n * per > c.left():
        raise SplineError("bad_counts", "more control points than the record holds")
    pts, weights = [], [] if rational else None
    for _ in range(n):
        if clock is not None:
            clock.tick()
        pts.append(tuple(_double(c) for _ in range(dim)))
        if rational:
            weights.append(_double(c))
    tol = _double(c) if c.peek() in (_DOUBLE, _DOUBLE2) else None
    return BS3Curve(
        form, d, rational, closure, knots, tuple(pts), None if weights is None else tuple(weights), tol
    )


def xt_knots(degree: int, knots: tuple[tuple[float, int], ...]) -> tuple[list[float], list[int]]:
    """``(values, multiplicities)`` of the clamped knot vector XT wants: the end
    multiplicities raised by one (see the module notes)."""
    values = [float(k) for k, _m in knots]
    mults = [m for _k, m in knots]
    if len(mults) < 2 or mults[0] != degree or mults[-1] != degree:
        # A periodic or unclamped spline: its knot convention is not verified.
        raise SplineError("unclamped", "the end knots do not have the multiplicity of the degree")
    mults[0] += 1
    mults[-1] += 1
    if any(m > degree + 1 for m in mults):
        raise SplineError("bad_knots", "a knot's multiplicity is more than the degree allows")
    return values, mults


def _basis(knots: list[float], degree: int, n: int, t: float) -> list[float]:
    """The ``n`` basis functions at ``t`` (Cox and de Boor), for checks and tests."""
    m = len(knots)
    t = min(max(t, knots[0]), knots[-1])
    if t >= knots[-1]:
        span = max(j for j in range(m - 1) if knots[j] < knots[j + 1])
        N = [1.0 if j == span else 0.0 for j in range(m - 1)]
    else:
        N = [1.0 if knots[j] <= t < knots[j + 1] else 0.0 for j in range(m - 1)]
    for p in range(1, degree + 1):
        for j in range(m - 1 - p):
            a = b = 0.0
            d1 = knots[j + p] - knots[j]
            d2 = knots[j + p + 1] - knots[j + 1]
            if d1 > 0:
                a = (t - knots[j]) / d1 * N[j]
            if d2 > 0:
                b = (knots[j + p + 1] - t) / d2 * N[j + 1]
            N[j] = a + b
    return N[:n]


def full_knots(degree: int, knots: tuple[tuple[float, int], ...]) -> list[float]:
    values, mults = xt_knots(degree, knots)
    out: list[float] = []
    for k, m in zip(values, mults, strict=True):
        out.extend([k] * m)
    return out


def surface_point(s: BS3Surface, u: float, v: float) -> tuple[float, float, float]:
    """The point of a decoded surface at (u, v): a direct evaluation, for checks."""
    Nu = _basis(full_knots(s.degree_u, s.knots_u), s.degree_u, s.nu, u)
    Nv = _basis(full_knots(s.degree_v, s.knots_v), s.degree_v, s.nv, v)
    x = y = z = w = 0.0
    for b in range(s.nv):
        if not Nv[b]:
            continue
        for a in range(s.nu):
            if not Nu[a]:
                continue
            k = b * s.nu + a
            f = Nu[a] * Nv[b] * (s.weights[k] if s.weights is not None else 1.0)
            p = s.points[k]
            x += f * p[0]
            y += f * p[1]
            z += f * p[2]
            w += f
    return (x / w, y / w, z / w)


def curve_point(cv: BS3Curve, t: float) -> tuple[float, ...]:
    """The point of a decoded curve at ``t``, for checks."""
    n = len(cv.points)
    N = _basis(full_knots(cv.degree, cv.knots), cv.degree, n, t)
    acc = [0.0] * len(cv.points[0])
    w = 0.0
    for a in range(n):
        if not N[a]:
            continue
        f = N[a] * (cv.weights[a] if cv.weights is not None else 1.0)
        for k, x in enumerate(cv.points[a]):
            acc[k] += f * x
        w += f
    return tuple(x / w for x in acc)


__all__ = [
    "CURVE_SUBTYPES",
    "SURFACE_SUBTYPES",
    "BS3Curve",
    "BS3Surface",
    "SplineError",
    "Values",
    "control_count",
    "curve_point",
    "full_knots",
    "read_curve",
    "read_surface",
    "surface_point",
    "xt_knots",
]
