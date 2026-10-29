"""Small 3D vector helpers on tuples (pure Python, no numpy)."""

import math

TWO_PI = 2.0 * math.pi


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a):
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def dist(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def unit(a):
    n = norm(a)
    return (a[0] / n, a[1] / n, a[2] / n) if n > 0.0 else None


def combo(p, a, s, b, t):
    """``p + s a + t b``."""
    return (p[0] + s * a[0] + t * b[0], p[1] + s * a[1] + t * b[1], p[2] + s * a[2] + t * b[2])


def orthonormal(axis, x_axis):
    """``(A, X, Y)``: the axis, the x axis made perpendicular to it, and ``A x X``; None
    when the x axis is parallel to the axis."""
    x = sub(x_axis, mul(axis, dot(x_axis, axis)))
    x = unit(x)
    if x is None or norm(x) < 0.5:
        return None
    return axis, x, cross(axis, x)


def finite(p) -> bool:
    return math.isfinite(p[0]) and math.isfinite(p[1]) and math.isfinite(p[2])


def wrap_near(x: float, ref: float, period: float) -> float:
    """``x`` shifted by whole periods to within half a period of ``ref``."""
    return ref + ((x - ref + 0.5 * period) % period) - 0.5 * period


def step_angle(radius: float, chord: float, angle: float) -> float:
    """The largest turn along an arc of ``radius`` that keeps within ``chord`` of it."""
    r = abs(radius)
    if r <= chord:
        return angle
    return min(angle, 2.0 * acos(1.0 - chord / r))


# The trigonometry the mesher uses, the same on every platform. The C libraries Python
# runs on (glibc on Linux, the Microsoft runtime on Windows) round a sine, a cosine or an
# arctangent the opposite way now and then, a difference in the last bit. The mesher's
# choices (where to add a point, which diagonal to flip) turn on ties that symmetry makes,
# so one last bit was enough to give the same part a different mesh, and a drawing's
# silhouettes from it, on Windows. Each result is rounded to 40 bits of mantissa (a
# relative 1e-12, far below any tolerance the mesher works to), so two libraries' answers
# one last bit apart round to the same number unless the exact value sits within that
# bit of a rounding boundary, which is about one call in four thousand of those that
# differ at all. Square roots and hypot are exact or Python's own, and need none of this.
# An angle every library gives exactly (none, a right angle, a straight one) is kept as
# it is, so tests such as "this is a half turn" still hold.
_MANTISSA = float(2**40)
_EXACT_ANGLES = (0.0, 0.5 * math.pi, math.pi)


def stable(x: float) -> float:
    """``x`` with its mantissa rounded to 40 bits; zero, infinities and NaN unchanged."""
    if x == 0.0 or not math.isfinite(x):
        return x
    m, e = math.frexp(x)
    return math.ldexp(round(m * _MANTISSA) / _MANTISSA, e)


def sin(x: float) -> float:
    return stable(math.sin(x))


def cos(x: float) -> float:
    return stable(math.cos(x))


def tan(x: float) -> float:
    return stable(math.tan(x))


def _angle(r: float) -> float:
    return r if abs(r) in _EXACT_ANGLES else stable(r)


def acos(x: float) -> float:
    return _angle(math.acos(x))


def atan2(y: float, x: float) -> float:
    return _angle(math.atan2(y, x))
