"""B-spline curves and surfaces as XT stores them (``docs/FORMAT.md`` 10.8).

Knot vectors are the ``KNOT_SET`` values repeated by the ``KNOT_MULT`` counts
and have ``n + degree + 1`` entries; both arrays can carry trailing entries of
multiplicity 0, which hold no knot. Rational control points are homogeneous,
``(w x, w y, w z, w)``. A surface's control points are stored with v varying
fastest. Evaluation follows the textbook algorithms (Piegl and Tiller, *The
NURBS Book*, A2.1 and A2.3): the basis functions and their first derivatives
in one pass, then one sum over the control points of the span.

Every input is checked before use: degrees from 1 to :data:`MAX_DEGREE`, at
most :data:`MAX_CONTROL_POINTS` control points, finite non-decreasing knots of
the right length with a span of positive length, and finite positive weights.
A check that fails raises :class:`~.topology.FaceFailed` with ``bad_geometry``.
"""

import math
from bisect import bisect_right

from .topology import FaceFailed

MAX_DEGREE = 32
MAX_CONTROL_POINTS = 1_000_000
SEED_FULL = 65_536  # control points searched in full for a starting point


def knot_vector(knots, mults, n: int, degree: int) -> list[float]:
    """The full knot vector of ``n`` control points of ``degree``, checked."""
    if not 1 <= degree <= MAX_DEGREE:
        raise FaceFailed("bad_geometry", f"degree {degree} is out of range")
    if not 2 <= n <= MAX_CONTROL_POINTS or n < degree + 1:
        raise FaceFailed("bad_geometry", f"{n} control points for degree {degree}")
    if not isinstance(knots, list) or not isinstance(mults, list) or len(knots) != len(mults) or not knots:
        raise FaceFailed("bad_geometry", "knot values and multiplicities do not match")
    # The arrays can be longer than the knots they hold: entries of multiplicity 0 pad them.
    total = 0
    pairs = []
    for k, m in zip(knots, mults, strict=True):
        if not isinstance(m, int) or m < 0 or m > degree + 1:
            raise FaceFailed("bad_geometry", "a knot multiplicity is out of range")
        if m:
            pairs.append((k, m))
            total += m
    if total != n + degree + 1:
        raise FaceFailed("bad_geometry", f"{total} knots for {n} control points of degree {degree}")
    out: list[float] = []
    last = -math.inf
    for k, m in pairs:
        if not isinstance(k, float) or not math.isfinite(k) or k < last:
            raise FaceFailed("bad_geometry", "knot values are not finite and non-decreasing")
        last = k
        out.extend([k] * m)
    if not out[degree] < out[n]:
        raise FaceFailed("bad_geometry", "the knot vector has no span of positive length")
    return out


def control_points(values, count: int, dim: int, rational: bool) -> list[tuple[float, ...]]:
    """``count`` control points of ``dim`` values each, from a flat list, checked finite;
    rational ones keep their homogeneous form with a positive weight last."""
    if dim not in (2, 3, 4) or (rational and dim < 3):
        raise FaceFailed("bad_geometry", f"control points of {dim} values")
    if not isinstance(values, list) or len(values) != count * dim:
        raise FaceFailed("bad_geometry", "the control point count does not match the values stored")
    out = []
    for i in range(0, count * dim, dim):
        c = tuple(values[i : i + dim])
        for x in c:
            if not math.isfinite(x):
                raise FaceFailed("non_finite", "a control point is not finite")
        if rational and not c[-1] > 0.0:
            raise FaceFailed("bad_geometry", "a weight is not positive")
        out.append(c)
    return out


def find_span(U: list[float], n: int, p: int, u: float) -> int:
    """The knot span index of ``u`` (A2.1): ``U[span] <= u < U[span + 1]``, the last span
    at the end of the range."""
    if u >= U[n]:
        return n - 1
    if u <= U[p]:
        return p
    return bisect_right(U, u, p, n) - 1


def basis_d1(U: list[float], span: int, u: float, p: int) -> tuple[list[float], list[float]]:
    """The ``p + 1`` non-zero basis functions at ``u`` and their first derivatives (A2.3)."""
    ndu = [[0.0] * (p + 1) for _ in range(p + 1)]
    ndu[0][0] = 1.0
    left = [0.0] * (p + 1)
    right = [0.0] * (p + 1)
    for j in range(1, p + 1):
        left[j] = u - U[span + 1 - j]
        right[j] = U[span + j] - u
        saved = 0.0
        for r in range(j):
            d = right[r + 1] + left[j - r]
            ndu[j][r] = d
            temp = ndu[r][j - 1] / d if d != 0.0 else 0.0
            ndu[r][j] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        ndu[j][j] = saved
    N = [ndu[r][p] for r in range(p + 1)]
    dN = [0.0] * (p + 1)
    last = ndu[p]
    for r in range(p + 1):
        d = 0.0
        if r >= 1 and last[r - 1] != 0.0:
            d += ndu[r - 1][p - 1] / last[r - 1]
        if r <= p - 1 and last[r] != 0.0:
            d -= ndu[r][p - 1] / last[r]
        dN[r] = d * p
    return N, dN


def basis_d2(U: list[float], span: int, u: float, p: int) -> tuple[list[float], list[float], list[float]]:
    """The basis functions at ``u`` with their first and second derivatives (A2.3, n = 2)."""
    ndu = [[0.0] * (p + 1) for _ in range(p + 1)]
    ndu[0][0] = 1.0
    left = [0.0] * (p + 1)
    right = [0.0] * (p + 1)
    for j in range(1, p + 1):
        left[j] = u - U[span + 1 - j]
        right[j] = U[span + j] - u
        saved = 0.0
        for r in range(j):
            d = right[r + 1] + left[j - r]
            ndu[j][r] = d
            temp = ndu[r][j - 1] / d if d != 0.0 else 0.0
            ndu[r][j] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        ndu[j][j] = saved
    n = min(2, p)
    ders = [[ndu[j][p] for j in range(p + 1)]] + [[0.0] * (p + 1) for _ in range(2)]
    a = [[0.0] * (p + 1) for _ in range(2)]

    def div(x, y):
        return x / y if y != 0.0 else 0.0

    for r in range(p + 1):
        s1, s2 = 0, 1
        a[0][0] = 1.0
        for k in range(1, n + 1):
            d = 0.0
            rk, pk = r - k, p - k
            if r >= k:
                a[s2][0] = div(a[s1][0], ndu[pk + 1][rk])
                d = a[s2][0] * ndu[rk][pk]
            j1 = 1 if rk >= -1 else -rk
            j2 = k - 1 if r - 1 <= pk else p - r
            for j in range(j1, j2 + 1):
                a[s2][j] = div(a[s1][j] - a[s1][j - 1], ndu[pk + 1][rk + j])
                d += a[s2][j] * ndu[rk + j][pk]
            if r <= pk:
                a[s2][k] = div(-a[s1][k - 1], ndu[pk + 1][r])
                d += a[s2][k] * ndu[r][pk]
            ders[k][r] = d
            s1, s2 = s2, s1
    f = p
    for k in range(1, n + 1):
        for j in range(p + 1):
            ders[k][j] *= f
        f *= p - k
    return ders[0], ders[1], ders[2]


def basis(U: list[float], span: int, u: float, p: int) -> list[float]:
    """The ``p + 1`` non-zero basis functions at ``u`` (A2.2)."""
    N = [1.0] + [0.0] * p
    left = [0.0] * (p + 1)
    right = [0.0] * (p + 1)
    for j in range(1, p + 1):
        left[j] = u - U[span + 1 - j]
        right[j] = U[span + j] - u
        saved = 0.0
        for r in range(j):
            d = right[r + 1] + left[j - r]
            temp = N[r] / d if d != 0.0 else 0.0
            N[r] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        N[j] = saved
    return N


def _stride(n: int, step: int) -> list[int]:
    """Every ``step``-th index of ``n``, and the last."""
    out = list(range(0, n, step))
    if out[-1] != n - 1:
        out.append(n - 1)
    return out


def greville(U: list[float], i: int, p: int) -> float:
    """The Greville abscissa of control point ``i``: the mean of its ``p`` interior knots."""
    return sum(U[i + 1 : i + p + 1]) / p


class BSplineCurve:
    """A B-spline curve of any dimension (2 for the (u, v) curve of an SP-curve)."""

    def __init__(
        self, degree: int, cps: list[tuple[float, ...]], U: list[float], rational: bool, periodic: bool
    ):
        self.p, self.cps, self.U, self.rational = degree, cps, U, rational
        self.n = len(cps)
        self.dim = len(cps[0]) - (1 if rational else 0)
        self.lo, self.hi = U[degree], U[self.n]
        self.period = (self.hi - self.lo) if periodic else None

    def wrap(self, t: float) -> float:
        if self.period is not None and not self.lo <= t <= self.hi:
            t = self.lo + (t - self.lo) % self.period
        return min(max(t, self.lo), self.hi)

    def spans(self, t0: float, t1: float) -> int:
        """About how many knot spans lie between ``t0`` and ``t1`` (at least 1)."""
        a, b = (t0, t1) if t0 <= t1 else (t1, t0)
        total = max(1, self.n - self.p)
        if self.period is not None and b - a >= self.period:
            return total
        a, b = self.wrap(a), self.wrap(b)
        if b < a:  # across the end of a periodic range
            return total
        return min(total, max(1, bisect_right(self.U, b) - bisect_right(self.U, a) + 1))

    def d1(self, t: float) -> tuple[tuple[float, ...], tuple[float, ...]]:
        """The point and the first derivative at ``t``."""
        t = self.wrap(t)
        p = self.p
        span = find_span(self.U, self.n, p, t)
        N, dN = basis_d1(self.U, span, t, p)
        k = len(self.cps[0])
        a = [0.0] * k
        da = [0.0] * k
        base = span - p
        cps = self.cps
        for j in range(p + 1):
            c = cps[base + j]
            nj, dj = N[j], dN[j]
            for m in range(k):
                a[m] += nj * c[m]
                da[m] += dj * c[m]
        if not self.rational:
            return tuple(a), tuple(da)
        w, dw = a[-1], da[-1]
        pt = tuple(x / w for x in a[:-1])
        return pt, tuple((da[m] - dw * pt[m]) / w for m in range(k - 1))

    def point(self, t: float) -> tuple[float, ...]:
        """The point alone: the basis functions without their derivatives."""
        t = self.wrap(t)
        p = self.p
        span = find_span(self.U, self.n, p, t)
        N = basis(self.U, span, t, p)
        k = len(self.cps[0])
        a = [0.0] * k
        base = span - p
        cps = self.cps
        for j in range(p + 1):
            c = cps[base + j]
            nj = N[j]
            for m in range(k):
                a[m] += nj * c[m]
        if not self.rational:
            return tuple(a)
        w = a[-1]
        return tuple(x / w for x in a[:-1])

    def euclidean_points(self) -> list[tuple[float, ...]]:
        if not self.rational:
            return self.cps
        return [tuple(x / c[-1] for x in c[:-1]) for c in self.cps]


class BSplineSurface:
    """A B-spline surface; ``rows[i][j]`` is control point (i along u, j along v)."""

    def __init__(
        self, pu: int, pv: int, rows, U: list[float], V: list[float], rational: bool, uper: bool, vper: bool
    ):
        self.pu, self.pv, self.rows, self.U, self.V, self.rational = pu, pv, rows, U, V, rational
        self.nu, self.nv = len(rows), len(rows[0])
        self.ulo, self.uhi = U[pu], U[self.nu]
        self.vlo, self.vhi = V[pv], V[self.nv]
        self.uperiod = (self.uhi - self.ulo) if uper else None
        self.vperiod = (self.vhi - self.vlo) if vper else None
        self.k = len(rows[0][0])

    def transposed(self) -> "BSplineSurface":
        rows = [list(col) for col in zip(*self.rows, strict=True)]
        return BSplineSurface(
            self.pv,
            self.pu,
            rows,
            self.V,
            self.U,
            self.rational,
            self.vperiod is not None,
            self.uperiod is not None,
        )

    def _wrap(self, u: float, v: float) -> tuple[float, float]:
        if self.uperiod is not None and not self.ulo <= u <= self.uhi:
            u = self.ulo + (u - self.ulo) % self.uperiod
        if self.vperiod is not None and not self.vlo <= v <= self.vhi:
            v = self.vlo + (v - self.vlo) % self.vperiod
        return min(max(u, self.ulo), self.uhi), min(max(v, self.vlo), self.vhi)

    def d1(self, u: float, v: float):
        """The point and the first derivatives along u and v."""
        u, v = self._wrap(u, v)
        pu, pv = self.pu, self.pv
        su = find_span(self.U, self.nu, pu, u)
        sv = find_span(self.V, self.nv, pv, v)
        Nu, dNu = basis_d1(self.U, su, u, pu)
        Nv, dNv = basis_d1(self.V, sv, v, pv)
        k = self.k
        a = [0.0] * k
        au = [0.0] * k
        av = [0.0] * k
        rows = self.rows
        b0 = sv - pv
        for i in range(pu + 1):
            row = rows[su - pu + i]
            r = [0.0] * k
            dr = [0.0] * k
            for j in range(pv + 1):
                c = row[b0 + j]
                nj, dj = Nv[j], dNv[j]
                for m in range(k):
                    r[m] += nj * c[m]
                    dr[m] += dj * c[m]
            ni, di = Nu[i], dNu[i]
            for m in range(k):
                a[m] += ni * r[m]
                au[m] += di * r[m]
                av[m] += ni * dr[m]
        if not self.rational:
            return (a[0], a[1], a[2]), (au[0], au[1], au[2]), (av[0], av[1], av[2])
        w, wu, wv = a[3], au[3], av[3]
        pt = (a[0] / w, a[1] / w, a[2] / w)
        return (
            pt,
            tuple((au[m] - wu * pt[m]) / w for m in range(3)),
            tuple((av[m] - wv * pt[m]) / w for m in range(3)),
        )

    def d2(self, u: float, v: float):
        """The point, the first derivatives and the second derivatives along u and along v
        (``Suu``, ``Svv``; the mixed one is not needed)."""
        u, v = self._wrap(u, v)
        pu, pv = self.pu, self.pv
        su = find_span(self.U, self.nu, pu, u)
        sv = find_span(self.V, self.nv, pv, v)
        Nu, dNu, ddNu = basis_d2(self.U, su, u, pu)
        Nv, dNv, ddNv = basis_d2(self.V, sv, v, pv)
        k = self.k
        A = [0.0] * k
        Au = [0.0] * k
        Av = [0.0] * k
        Auu = [0.0] * k
        Avv = [0.0] * k
        rows = self.rows
        b0 = sv - pv
        for i in range(pu + 1):
            row = rows[su - pu + i]
            r = [0.0] * k
            dr = [0.0] * k
            ddr = [0.0] * k
            for j in range(pv + 1):
                c = row[b0 + j]
                nj, dj, ddj = Nv[j], dNv[j], ddNv[j]
                for m in range(k):
                    r[m] += nj * c[m]
                    dr[m] += dj * c[m]
                    ddr[m] += ddj * c[m]
            ni, di, ddi = Nu[i], dNu[i], ddNu[i]
            for m in range(k):
                A[m] += ni * r[m]
                Au[m] += di * r[m]
                Av[m] += ni * dr[m]
                Auu[m] += ddi * r[m]
                Avv[m] += ni * ddr[m]
        if not self.rational:
            return tuple(A[:3]), tuple(Au[:3]), tuple(Av[:3]), tuple(Auu[:3]), tuple(Avv[:3])
        w, wu, wv, wuu, wvv = A[3], Au[3], Av[3], Auu[3], Avv[3]
        S = [A[m] / w for m in range(3)]
        Su = [(Au[m] - wu * S[m]) / w for m in range(3)]
        Sv = [(Av[m] - wv * S[m]) / w for m in range(3)]
        Suu = [(Auu[m] - 2.0 * wu * Su[m] - wuu * S[m]) / w for m in range(3)]
        Svv = [(Avv[m] - 2.0 * wv * Sv[m] - wvv * S[m]) / w for m in range(3)]
        return tuple(S), tuple(Su), tuple(Sv), tuple(Suu), tuple(Svv)

    def point(self, u: float, v: float) -> tuple[float, float, float]:
        """The point alone: the basis functions without their derivatives."""
        u, v = self._wrap(u, v)
        pu, pv = self.pu, self.pv
        su = find_span(self.U, self.nu, pu, u)
        sv = find_span(self.V, self.nv, pv, v)
        Nu = basis(self.U, su, u, pu)
        Nv = basis(self.V, sv, v, pv)
        rows = self.rows
        b0 = sv - pv
        a0 = a1 = a2 = a3 = 0.0
        rational = self.rational
        for i in range(pu + 1):
            ni = Nu[i]
            if ni == 0.0:
                continue
            row = rows[su - pu + i]
            for j in range(pv + 1):
                w = ni * Nv[j]
                c = row[b0 + j]
                a0 += w * c[0]
                a1 += w * c[1]
                a2 += w * c[2]
                if rational:
                    a3 += w * c[3]
        if rational:
            return (a0 / a3, a1 / a3, a2 / a3)
        return (a0, a1, a2)

    def _nearest(self, p, cells, count: int, clock) -> list[tuple[float, int, int]]:
        best: list[tuple[float, int, int]] = []
        rows = self.rows
        if clock is not None:
            clock.tick(len(cells))
        for i, j in cells:
            q = self.euclidean(rows[i][j])
            d = (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 + (q[2] - p[2]) ** 2
            if len(best) < count:
                best.append((d, i, j))
                best.sort()
            elif d < best[-1][0]:
                best[-1] = (d, i, j)
                best.sort()
        return best

    def euclidean(self, c) -> tuple[float, float, float]:
        if self.rational:
            return (c[0] / c[3], c[1] / c[3], c[2] / c[3])
        return (c[0], c[1], c[2])

    def seeds(self, p, count: int = 4, clock=None) -> list[tuple[float, float]]:
        """The Greville abscissae of the ``count`` control points nearest ``p``. A net of
        more than :data:`SEED_FULL` points is searched every few rows and columns first,
        then around the nearest few of those, so a lookup costs about that many points
        however large the net."""
        nu, nv = self.nu, self.nv
        su = sv = 1
        if nu * nv > SEED_FULL:
            side = math.isqrt(SEED_FULL)
            su = max(1, math.ceil(nu / side))
            sv = max(1, math.ceil(nv / side))
        coarse = [(i, j) for i in _stride(nu, su) for j in _stride(nv, sv)]
        best = self._nearest(p, coarse, 2 * count if su > 1 or sv > 1 else count, clock)
        if su > 1 or sv > 1:
            near = set()
            for _d, i0, j0 in best:
                for i in range(max(0, i0 - su), min(nu, i0 + su + 1)):
                    for j in range(max(0, j0 - sv), min(nv, j0 + sv + 1)):
                        near.add((i, j))
            best = self._nearest(p, sorted(near), count, clock)
        out = []
        for _d, i, j in best:
            u = min(max(greville(self.U, i, self.pu), self.ulo), self.uhi)
            v = min(max(greville(self.V, j, self.pv), self.vlo), self.vhi)
            out.append((u, v))
        return out
