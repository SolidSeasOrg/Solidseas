"""Surface evaluators: points, first derivatives, normals, periods, poles and inversion.

Each surface has the parametrisation XT itself uses (``docs/FORMAT.md`` 10.8),
with X the ``x_axis``, A the axis or normal and Y = A x X:

* PLANE ``P + u X + v Y``; CYLINDER ``P + v A + r (cos u X + sin u Y)``;
* CONE ``P + v A + (r + v tan a)(cos u X + sin u Y)``, tan a the half angle's;
* SPHERE ``C + r (cos v (cos u X + sin u Y) + sin v A)``;
* TORUS ``C + (R + r cos v)(cos u X + sin u Y) + r sin v A``;
* B_SURFACE a B-spline in u and v; SWEPT_SURF ``section(u) + v sweep``;
* SPUN_SURF ``profile(u)`` turned by ``v`` (right hand) about the line (base, A);
* OFFSET_SURF ``base(u, v) + offset n(u, v)``, n the base's unit normal times
  the base's own sense;
* BLENDED_EDGE, a rolling blend, is not evaluated in Parasolid's own (u, v), which
  is not known: :mod:`.blend` approximates it by a rational B-spline, u along its
  spine and v across from its first support to its second.

The natural normal is ``Su x Sv``; a face's outward normal is that times the
surface's own sense times the face's sense, except on a blend, where it is taken
from a face the blend face meets tangentially.

Inside the tessellator every pole lies on a line ``v = const``: a surface whose
poles lie on lines ``u = const`` (a SPUN_SURF whose profile ends on its axis,
a B-spline with a collapsed first or last column) is presented with u and v
swapped, ``flip`` -1 (the swap turns the natural normal round), and
:meth:`Surface.from_file` maps the file's (u, v), from an SP-curve, into it.
A SPUN_SURF whose profile is closed (a whole circle, periodic in v too) has a
pole wherever the profile crosses its axis, as a nose revolved from an arc
whose centre is off the axis does at its tip.
"""

import math

from . import nurbs
from ._vec import (
    TWO_PI,
    add,
    combo,
    cross,
    dist,
    dot,
    mul,
    norm,
    orthonormal,
    step_angle,
    sub,
    unit,
    wrap_near,
)
from .curves import BCurve, Conic, Curve, Line, Polyline, SPCurve, Trimmed, make_curve
from .topology import (
    B_SURFACE,
    BLENDED_EDGE,
    BSPLINE_VERTICES,
    CONE,
    CURVE_TYPES,
    CYLINDER,
    KNOT_MULT,
    KNOT_SET,
    NURBS_SURF,
    OFFSET_SURF,
    PLANE,
    SPHERE,
    SPUN_SURF,
    SURFACE_TYPES,
    SWEPT_SURF,
    TORUS,
    FaceFailed,
    Topology,
)

MAX_DEPTH = 16  # surfaces and curves built inside one another (offset of a swept surface...)


class Surface:
    """Base class. ``kind`` is ``plane``, ``analytic`` or ``parametric``; ``pu`` and
    ``pv`` the periods (None when not periodic); ``poles`` the pole lines as
    ``(v, point)``; ``urange`` and ``vrange`` the parameter ranges Newton keeps to
    (None: unbounded or periodic)."""

    kind = "parametric"
    name = "SURFACE"
    flip = 1
    pu: float | None = None
    pv: float | None = None
    poles: tuple = ()
    pole_radius: tuple = ()  # how far from its point a pole reaches (a row collapsed within the chord)
    urange: tuple[float, float] | None = None
    vrange: tuple[float, float] | None = None

    def point(self, u, v):
        return self.d1(u, v)[0]

    def d1(self, u, v):
        raise NotImplementedError

    def normal(self, u, v):
        """The unit natural normal, or None where ``Su x Sv`` vanishes (a pole)."""
        _p, su, sv = self.d1(u, v)
        n = cross(su, sv)
        ln = norm(n)
        scale = norm(su) * norm(sv)
        if not ln > 1e-12 * scale or ln == 0.0:
            return None
        return (n[0] / ln, n[1] / ln, n[2] / ln)

    def from_file(self, u, v):
        return u, v

    def clamp(self, u, v):
        if self.urange is not None:
            u = min(max(u, self.urange[0]), self.urange[1])
        if self.vrange is not None:
            v = min(max(v, self.vrange[0]), self.vrange[1])
        return u, v

    def pole_at(self, p, tol: float):
        for v, q in self.poles:
            if dist(p, q) <= tol:
                return v
        return None

    def at_pole(self, u, v, p, tol: float):
        """The pole line a point lies on, or None: within ``tol`` of a pole's point, or, for
        a boundary row collapsed to within the chord tolerance, at that row's v and near it."""
        vp = self.pole_at(p, tol)
        if vp is not None:
            return vp
        for k, (pv, q) in enumerate(self.poles):
            radius = self.pole_radius[k] if k < len(self.pole_radius) else 0.0
            span = (self.vrange[1] - self.vrange[0]) if self.vrange else 1.0
            if radius > 0.0 and abs(v - pv) <= 1e-6 * span and dist(p, q) <= 2.0 * radius + tol:
                return pv
        return None

    def closest(self, p, hint, tol: float, ptol: float, clock=None, near: float | None = None):
        """``(u, v, distance)`` of the point of the surface nearest ``p``; ``u`` is None at
        a pole. ``hint`` is the (u, v) of a nearby point, or None.

        A point of the surface found within ``near`` of ``p`` is taken at once. One
        farther is compared with what every starting point gives, and the nearest is
        kept: Newton from a starting point on the wrong part of the surface (the other
        wall of a thin fold, say) stops at a point a few chords away that is nearest only
        locally. ``near`` None is ``tol``, the first point found within it taken."""
        vp = self.pole_at(p, ptol)
        if vp is not None:
            return None, vp, 0.0
        take = tol if near is None else near
        best = None
        if hint is not None and hint[0] is not None:
            best = newton(self, p, hint[0], hint[1])
        if best is None or best[2] > take:
            for su, sv in self.seeds(p, clock):
                got = newton(self, p, su, sv)
                if best is None or got[2] < best[2]:
                    best = got
                if best[2] <= take:
                    break
        if best is None:
            raise FaceFailed("inversion_failed", "no starting point")
        vp = self.at_pole(best[0], best[1], p, ptol)
        if vp is not None:
            return None, vp, best[2]
        return best

    def seeds(self, p, clock=None):
        return []

    def bend_across(self, p, t, hint, tol: float, clock=None):
        """``(curvature, (u, v))``: how fast the surface turns away, at its point nearest
        ``p``, in the direction square to ``t`` (the unit tangent of a curve on it there):
        the absolute normal curvature across the curve, from first derivatives by
        differences. The (u, v) is a hint for the next point along the curve. None at a
        pole, where the derivatives say nothing, or where no point of the surface is
        within ``tol`` of ``p``."""
        u, v, d = self.closest(p, hint, tol, 1e-9, clock, near=tol)
        if u is None or not d <= tol:
            return None
        hu, hv = 1e-6 * (1.0 + abs(u)), 1e-6 * (1.0 + abs(v))
        # Differences inside the parameter range, so that a curve on the surface's own edge
        # (a fillet's rim) is not measured over a step clamped to nothing on one side.
        cu, cv = _inside(u, self.urange, hu), _inside(v, self.vrange, hv)
        _p, su, sv = self.d1(cu, cv)
        n = unit(cross(su, sv))
        b = unit(cross(n, t)) if n is not None else None
        if b is None:
            return None
        _a, su1, sv1 = self.d1(cu + hu, cv)
        _a, su0, sv0 = self.d1(cu - hu, cv)
        _a, su3, sv3 = self.d1(cu, cv + hv)
        _a, su2, sv2 = self.d1(cu, cv - hv)
        e, f, g = dot(su, su), dot(su, sv), dot(sv, sv)
        det = e * g - f * f
        if not det > 1e-24 * (e * g):
            return None
        x, y = dot(b, su), dot(b, sv)
        a, c = (g * x - f * y) / det, (e * y - f * x) / det  # b in the basis (Su, Sv)
        ll = dot(sub(su1, su0), n) / (2.0 * hu)
        mm = dot(sub(su3, su2), n) / (2.0 * hv)
        nn = dot(sub(sv3, sv2), n) / (2.0 * hv)
        den = e * a * a + 2.0 * f * a * c + g * c * c
        if not den > 0.0:
            return None
        k = abs((ll * a * a + 2.0 * mm * a * c + nn * c * c) / den)
        if not math.isfinite(k):
            return None
        return k, (u, v)

    def speeds(self, box):
        """Rough lengths of a unit step in u and in v over the (u, v) box
        ``(u0, u1, v0, v1)``, for scaling the domain so that its triangles are well
        shaped in space."""
        u0, u1, v0, v1 = box
        su = sv = 0.0
        k = 0
        for i in range(3):
            for j in range(3):
                u = u0 + (u1 - u0) * (i + 0.5) / 3
                v = v0 + (v1 - v0) * (j + 0.5) / 3
                _p, du, dv = self.d1(u, v)
                su += norm(du)
                sv += norm(dv)
                k += 1
        su, sv = su / k, sv / k
        if not su > 0.0 or not math.isfinite(su):
            su = sv if sv > 0.0 else 1.0
        if not sv > 0.0 or not math.isfinite(sv):
            sv = su
        return su, sv

    def d2(self, u, v):
        """``(P, Su, Sv, Suu, Svv)``, the second derivatives by differences of the first."""
        hu = 1e-5 * (1.0 + abs(u))
        hv = 1e-5 * (1.0 + abs(v))
        p, su, sv = self.d1(u, v)
        _a, su1, _b = self.d1(u + hu, v)
        _a, su0, _b = self.d1(u - hu, v)
        _a, _b, sv1 = self.d1(u, v + hv)
        _a, _b, sv0 = self.d1(u, v - hv)
        return p, su, sv, mul(sub(su1, su0), 0.5 / hu), mul(sub(sv1, sv0), 0.5 / hv)

    def steps(self, box, chord: float, angle: float):
        """Grid steps in u and v for the first points inside a face (None: none needed),
        from the normal curvature on a 3 x 3 sample of the box: the step each sample
        point needs, the median of them. The grid only seeds the refinement,
        which adds points where the curvature is higher, so a few sharp places do not
        set the step for the whole face."""
        u0, u1, v0, v1 = box
        need_u: list[float] = []
        need_v: list[float] = []
        flat_u = flat_v = 0
        for i in range(3):
            for j in range(3):
                u = u0 + (u1 - u0) * (i + 0.5) / 3
                v = v0 + (v1 - v0) * (j + 0.5) / 3
                _p, su, sv, suu, svv = self.d2(u, v)
                n = unit(cross(su, sv))
                if n is None:
                    continue
                ku = abs(dot(suu, n))
                kv = abs(dot(svv, n))
                a = _step(ku, norm(su), chord, angle)
                b = _step(kv, norm(sv), chord, angle)
                if a is None:
                    flat_u += 1
                else:
                    need_u.append(a)
                if b is None:
                    flat_v += 1
                else:
                    need_v.append(b)
        return _quartile(need_u, flat_u), _quartile(need_v, flat_v)


def _inside(x: float, rng, h: float) -> float:
    """``x`` kept at least ``h`` inside the range ``rng`` (None: no range), where the
    range is wider than twice that."""
    if rng is None or not rng[1] - rng[0] > 2.0 * h:
        return x
    return min(max(x, rng[0] + h), rng[1] - h)


def _quartile(steps: list[float], flat: int):
    """The median of the steps the sample points need, None when most need none."""
    if len(steps) <= flat:
        return None
    steps.sort()
    return steps[len(steps) // 2]


def _step(k2: float, speed: float, chord: float, angle: float):
    """A parameter step for second derivative (normal part) ``k2`` and speed ``speed``:
    within ``chord`` of the surface and turning at most ``angle``; None for no curvature."""
    if not k2 > 0.0 or not math.isfinite(k2):
        return None
    h = math.sqrt(8.0 * chord / k2)
    if math.isfinite(speed) and speed > 0.0:
        h = min(h, angle * speed / k2)
    return h


def newton(S: Surface, p, u: float, v: float, iters: int = 24):
    """Gauss-Newton on ``|S(u, v) - p|``: ``(u, v, distance)``, the best seen."""
    best = (u, v, math.inf)
    for _ in range(iters):
        q, su, sv = S.d1(u, v)
        r = sub(p, q)
        d = norm(r)
        if not math.isfinite(d):
            break
        if d < best[2]:
            best = (u, v, d)
        if d <= 1e-13:
            break
        a, b, c = dot(su, su), dot(su, sv), dot(sv, sv)
        g1, g2 = dot(r, su), dot(r, sv)
        det = a * c - b * b
        if not det > 1e-24 * (a * c) or det == 0.0:
            break
        du = (c * g1 - b * g2) / det
        dv = (a * g2 - b * g1) / det
        nu, nv = S.clamp(u + du, v + dv)
        if abs(nu - u) * math.sqrt(a) + abs(nv - v) * math.sqrt(c) <= 1e-14 * (1.0 + d):
            u, v = nu, nv
            break
        u, v = nu, nv
    q = S.point(u, v)
    d = dist(q, p)
    if math.isfinite(d) and d < best[2]:
        best = (u, v, d)
    return best


# --------------------------------------------------------------------------- analytic
class Plane(Surface):
    kind = "plane"
    name = "PLANE"

    def __init__(self, P, N, X) -> None:
        frame = orthonormal(N, X)
        if frame is None:
            raise FaceFailed("bad_geometry", "a plane's axes are parallel")
        self.P, (self.N, self.X, self.Y) = P, frame

    def d1(self, u, v):
        return combo(self.P, self.X, u, self.Y, v), self.X, self.Y

    def normal(self, u, v):
        return self.N

    def closest(self, p, hint, tol, ptol, clock=None, near=None):
        q = sub(p, self.P)
        return dot(q, self.X), dot(q, self.Y), abs(dot(q, self.N))

    def speeds(self, box):
        return 1.0, 1.0

    def steps(self, box, chord, angle):
        return None, None


class Revolved(Surface):
    """Shared by the surfaces of revolution with closed forms: a frame and the radial
    direction ``e(u) = cos u X + sin u Y``."""

    kind = "analytic"
    pu = TWO_PI

    def _frame(self, A, X):
        frame = orthonormal(A, X)
        if frame is None:
            raise FaceFailed("bad_geometry", f"a {self.name.lower()}'s axes are parallel")
        self.A, self.X, self.Y = frame

    def _local(self, p, origin):
        q = sub(p, origin)
        return dot(q, self.X), dot(q, self.Y), dot(q, self.A)


class Cylinder(Revolved):
    name = "CYLINDER"

    def __init__(self, P, A, r, X) -> None:
        if not r > 0.0:
            raise FaceFailed("bad_geometry", "a cylinder's radius is not positive")
        self._frame(A, X)
        self.P, self.r = P, r

    def d1(self, u, v):
        c, s = math.cos(u), math.sin(u)
        e = combo((0.0, 0.0, 0.0), self.X, c, self.Y, s)
        p = add(add(self.P, mul(self.A, v)), mul(e, self.r))
        return p, combo((0.0, 0.0, 0.0), self.X, -self.r * s, self.Y, self.r * c), self.A

    def closest(self, p, hint, tol, ptol, clock=None, near=None):
        x, y, h = self._local(p, self.P)
        rho = math.hypot(x, y)
        return math.atan2(y, x), h, abs(rho - self.r)

    def speeds(self, box):
        return self.r, 1.0

    def steps(self, box, chord, angle):
        return step_angle(self.r, chord, angle), None


class Cone(Revolved):
    name = "CONE"

    def __init__(self, P, A, r, sin_a, cos_a, X) -> None:
        if not (cos_a > 1e-12 and math.isfinite(sin_a / cos_a)) or not r >= 0.0:
            raise FaceFailed("bad_geometry", "a cone's half angle or radius is out of range")
        self._frame(A, X)
        self.P, self.r, self.t = P, r, sin_a / cos_a
        if self.t != 0.0:
            va = -r / self.t
            self.apex_v = va
            self.poles = ((va, add(P, mul(self.A, va))),)
        else:
            self.apex_v = None

    def d1(self, u, v):
        c, s = math.cos(u), math.sin(u)
        e = combo((0.0, 0.0, 0.0), self.X, c, self.Y, s)
        rho = self.r + v * self.t
        p = add(add(self.P, mul(self.A, v)), mul(e, rho))
        su = combo((0.0, 0.0, 0.0), self.X, -rho * s, self.Y, rho * c)
        sv = add(self.A, mul(e, self.t))
        return p, su, sv

    def closest(self, p, hint, tol, ptol, clock=None, near=None):
        x, y, h = self._local(p, self.P)
        rho_p = math.hypot(x, y)
        # In the plane through the axis and p, the cone is the line rho = r + v tan(a),
        # rho signed: the nearest point of it to (rho_p, h) or, past the apex, to
        # (-rho_p, h) on the other side of the axis.
        ca = 1.0 / math.sqrt(1.0 + self.t * self.t)
        sa = self.t * ca
        best = None
        for side in (1.0, -1.0):
            q = side * rho_p
            v = ((q - self.r) * sa + h * ca) * ca
            d = abs((q - self.r) * ca - h * sa)
            if best is None or d < best[0]:
                best = (d, v, side)
        d, v, side = best
        if self.pole_at(p, ptol) is not None:
            return None, self.apex_v, d
        u = math.atan2(y, x) if side > 0 else math.atan2(-y, -x)
        return u, v, d

    def speeds(self, box):
        rho = max(abs(self.r + box[2] * self.t), abs(self.r + box[3] * self.t))
        return max(rho, 1e-9), math.sqrt(1.0 + self.t * self.t)

    def steps(self, box, chord, angle):
        rho = max(abs(self.r + box[2] * self.t), abs(self.r + box[3] * self.t))
        return step_angle(rho, chord, angle), None


class Sphere(Revolved):
    name = "SPHERE"

    def __init__(self, C, r, A, X) -> None:
        if not r > 0.0:
            raise FaceFailed("bad_geometry", "a sphere's radius is not positive")
        self._frame(A, X)
        self.C, self.r = C, r
        h = math.pi / 2
        self.poles = ((-h, sub(C, mul(self.A, r))), (h, add(C, mul(self.A, r))))
        self.vrange = (-h, h)

    def d1(self, u, v):
        cu, su_, cv, sv_ = math.cos(u), math.sin(u), math.cos(v), math.sin(v)
        e = combo((0.0, 0.0, 0.0), self.X, cu, self.Y, su_)
        r = self.r
        p = add(self.C, add(mul(e, r * cv), mul(self.A, r * sv_)))
        du = combo((0.0, 0.0, 0.0), self.X, -r * cv * su_, self.Y, r * cv * cu)
        dv = add(mul(e, -r * sv_), mul(self.A, r * cv))
        return p, du, dv

    def normal(self, u, v):
        cv = math.cos(v)
        if abs(cv) < 1e-12:
            return None
        e = combo((0.0, 0.0, 0.0), self.X, math.cos(u), self.Y, math.sin(u))
        return add(mul(e, cv), mul(self.A, math.sin(v)))

    def closest(self, p, hint, tol, ptol, clock=None, near=None):
        x, y, h = self._local(p, self.C)
        rho = math.hypot(x, y)
        d = abs(math.sqrt(rho * rho + h * h) - self.r)
        v = math.atan2(h, rho)
        if rho <= ptol:
            return None, (math.pi / 2 if h > 0 else -math.pi / 2), d
        return math.atan2(y, x), v, d

    def speeds(self, box):
        v0, v1 = box[2], box[3]
        c = 1.0 if v0 <= 0.0 <= v1 else max(math.cos(v0), math.cos(v1))
        return max(self.r * c, self.r * 1e-3), self.r

    def steps(self, box, chord, angle):
        s = step_angle(self.r, chord, angle)
        return s, s

    def extent(self):
        r = self.r
        return [add(self.C, (r, r, r)), sub(self.C, (r, r, r))]


class Torus(Revolved):
    name = "TORUS"
    pv = TWO_PI

    def __init__(self, C, A, R, r, X) -> None:
        if not r > 0.0 or not R > -r:
            raise FaceFailed("bad_geometry", "a torus's radii are out of range")
        self._frame(A, X)
        self.C, self.R, self.r = C, R, r

    def d1(self, u, v):
        cu, su_, cv, sv_ = math.cos(u), math.sin(u), math.cos(v), math.sin(v)
        e = combo((0.0, 0.0, 0.0), self.X, cu, self.Y, su_)
        rho = self.R + self.r * cv
        p = add(self.C, add(mul(e, rho), mul(self.A, self.r * sv_)))
        du = combo((0.0, 0.0, 0.0), self.X, -rho * su_, self.Y, rho * cu)
        dv = add(mul(e, -self.r * sv_), mul(self.A, self.r * cv))
        return p, du, dv

    def closest(self, p, hint, tol, ptol, clock=None, near=None):
        x, y, h = self._local(p, self.C)
        rho = math.hypot(x, y)
        if rho <= ptol:
            raise FaceFailed("degenerate", "a point on a torus's axis")
        u = math.atan2(y, x)
        v = math.atan2(h, rho - self.R)
        d = abs(math.hypot(rho - self.R, h) - self.r)
        if self.R < self.r:
            # A torus that meets its axis covers some points twice: take the nearer reading.
            u2, v2 = u + math.pi, math.atan2(h, -rho - self.R)
            d2 = abs(math.hypot(-rho - self.R, h) - self.r)
            if d2 < d or (
                hint is not None and hint[0] is not None and d2 <= tol and _closer(hint, (u2, v2), (u, v))
            ):
                return u2, v2, d2
        return u, v, d

    def speeds(self, box):
        """The largest speed round the axis over the box, ``|R + r cos v|``: a torus whose
        major radius is under its minor one runs through its axis, and the
        part of it inside, where ``R + r cos v`` is below nought, is as fast as its
        distance from the axis, not as slow as that sum."""
        v0, v1 = box[2], box[3]
        whole = (v1 - v0) >= TWO_PI
        cmax = 1.0 if whole or _contains_angle(v0, v1, 0.0) else max(math.cos(v0), math.cos(v1))
        cmin = -1.0 if whole or _contains_angle(v0, v1, math.pi) else min(math.cos(v0), math.cos(v1))
        rho = max(abs(self.R + self.r * cmax), abs(self.R + self.r * cmin))
        return max(rho, self.r * 1e-3), self.r

    def steps(self, box, chord, angle):
        return step_angle(self.R + self.r, chord, angle), step_angle(self.r, chord, angle)

    def extent(self):
        """The two corners of the torus's box."""
        e = tuple(self.R * math.sqrt(max(0.0, 1.0 - self.A[i] ** 2)) + self.r for i in range(3))
        return [add(self.C, e), sub(self.C, e)]


def _contains_angle(a0: float, a1: float, x: float) -> bool:
    lo, hi = min(a0, a1), max(a0, a1)
    k = math.ceil((lo - x) / TWO_PI)
    return x + k * TWO_PI <= hi


def _closer(hint, a, b) -> bool:
    def d(q):
        return abs(wrap_near(q[0], hint[0], TWO_PI) - hint[0]) + abs(
            wrap_near(q[1], hint[1], TWO_PI) - hint[1]
        )

    return d(a) < d(b)


# --------------------------------------------------------------------------- parametric
class BSurface(Surface):
    name = "B_SURFACE"

    def __init__(self, spline: nurbs.BSplineSurface, chord: float) -> None:
        # Closed without the flag: the first and last rows of control points coincide.
        if spline.uperiod is None and _coincide(spline, "u", chord / 10.0):
            spline.uperiod = spline.uhi - spline.ulo
        if spline.vperiod is None and _coincide(spline, "v", chord / 10.0):
            spline.vperiod = spline.vhi - spline.vlo
        # A boundary row collapsed to within the chord tolerance is a pole: a point there
        # has no u worth having.
        u_poles = _collapsed(spline, "u", chord)
        v_poles = _collapsed(spline, "v", chord)
        if u_poles and not v_poles:
            spline = spline.transposed()
            self.flip = -1
            self.swapped = True
            v_poles = u_poles
        else:
            self.swapped = False
        self.s = spline
        self.pu, self.pv = spline.uperiod, spline.vperiod
        self.urange = None if self.pu is not None else (spline.ulo, spline.uhi)
        self.vrange = None if self.pv is not None else (spline.vlo, spline.vhi)
        self.poles = tuple((spline.vlo if side == 0 else spline.vhi, pt) for side, pt, _r in v_poles)
        self.pole_radius = tuple(r for _s, _p, r in v_poles)

    def d1(self, u, v):
        return self.s.d1(u, v)

    def point(self, u, v):
        return self.s.point(u, v)

    def d2(self, u, v):
        return self.s.d2(u, v)

    def from_file(self, u, v):
        return (v, u) if self.swapped else (u, v)

    def seeds(self, p, clock=None):
        out = self.s.seeds(p, clock=clock)
        s = self.s
        # a coarse grid as a last resort
        for i in range(5):
            for j in range(5):
                out.append((s.ulo + (s.uhi - s.ulo) * (i + 0.5) / 5, s.vlo + (s.vhi - s.vlo) * (j + 0.5) / 5))
        return out

    def box(self):
        s = self.s
        return s.ulo, s.uhi, s.vlo, s.vhi


def _coincide(s: nurbs.BSplineSurface, direction: str, tol: float) -> bool:
    """Whether the first and last rows of control points along ``direction`` are the
    same points: the surface closes on itself there."""
    if direction == "u":
        a, b = s.rows[0], s.rows[-1]
    else:
        a, b = [r[0] for r in s.rows], [r[-1] for r in s.rows]
    return all(dist(s.euclidean(x), s.euclidean(y)) <= tol for x, y in zip(a, b, strict=True))


def _collapsed(s: nurbs.BSplineSurface, direction: str, tol: float):
    """The boundary rows of control points that collapse to within ``tol`` of one point:
    ``[(0 or 1, point, spread)]`` for the low and high ends of v (``direction == "v"``)
    or of u."""
    out = []
    if direction == "v":
        rows = [[r[0] for r in s.rows], [r[-1] for r in s.rows]]
        periodic = s.vperiod is not None
    else:
        rows = [s.rows[0], s.rows[-1]]
        periodic = s.uperiod is not None
    if periodic:
        return out
    for side, row in enumerate(rows):
        pts = [s.euclidean(c) for c in row]
        first = pts[0]
        spread = max(dist(q, first) for q in pts)
        if spread <= tol:
            out.append((side, first, spread))
    return out


def _bsurface(topo: Topology, node, chord: float) -> BSurface:
    ns = topo.ref(node, "nurbs", (NURBS_SURF,), required=True)
    get = topo.get
    pu, pv = get(ns, "u_degree"), get(ns, "v_degree")
    nu, nv = get(ns, "n_u_vertices"), get(ns, "n_v_vertices")
    dim = get(ns, "vertex_dim")
    rational = bool(get(ns, "rational", 0))
    for x in (pu, pv, nu, nv, dim):
        if not isinstance(x, int):
            raise FaceFailed("bad_geometry", "a B-surface's sizes are not integers")
    if dim != (4 if rational else 3):
        raise FaceFailed("bad_geometry", f"B-surface control points of {dim} values")
    if not (1 <= nu <= nurbs.MAX_CONTROL_POINTS and 1 <= nv <= nurbs.MAX_CONTROL_POINTS) or (
        nu * nv > nurbs.MAX_CONTROL_POINTS
    ):
        raise FaceFailed("bad_geometry", f"{nu} x {nv} control points")
    U = nurbs.knot_vector(
        get(topo.ref(ns, "u_knots", (KNOT_SET,), required=True), "knots"),
        get(topo.ref(ns, "u_knot_mult", (KNOT_MULT,), required=True), "mult"),
        nu,
        pu,
    )
    V = nurbs.knot_vector(
        get(topo.ref(ns, "v_knots", (KNOT_SET,), required=True), "knots"),
        get(topo.ref(ns, "v_knot_mult", (KNOT_MULT,), required=True), "mult"),
        nv,
        pv,
    )
    cps = nurbs.control_points(
        get(topo.ref(ns, "bspline_vertices", (BSPLINE_VERTICES,), required=True), "vertices"),
        nu * nv,
        dim,
        rational,
    )
    rows = [cps[i * nv : (i + 1) * nv] for i in range(nu)]  # v varies fastest
    uper = bool(get(ns, "u_periodic", 0)) or bool(get(ns, "u_closed", 0))
    vper = bool(get(ns, "v_periodic", 0)) or bool(get(ns, "v_closed", 0))
    return BSurface(nurbs.BSplineSurface(pu, pv, rows, U, V, rational, uper, vper), chord)


def _range(curve: Curve):
    """A curve's parameter range ``(lo, hi)`` and period, for a section or a profile."""
    if isinstance(curve, Trimmed):
        a, b = curve.t1, curve.t2
        return (min(a, b), max(a, b)), None
    if isinstance(curve, (BCurve, SPCurve)):
        return (curve.lo, curve.hi), curve.period
    if isinstance(curve, Conic):
        return (0.0, TWO_PI), TWO_PI
    if isinstance(curve, Polyline):
        return (curve.lo, curve.hi), None
    if isinstance(curve, Line):
        return None, None
    return None, None


class Swept(Surface):
    name = "SWEPT_SURF"

    def __init__(self, section: Curve, sweep) -> None:
        if not dot(sweep, sweep) > 1e-24:
            raise FaceFailed("bad_geometry", "a swept surface has no sweep")
        self.c, self.w = section, sweep
        rng, period = _range(section)
        self.pu = period
        self.urange = rng if period is None else None
        self.crange = rng

    def d1(self, u, v):
        q, dq = self.c.d1(u)
        return add(q, mul(self.w, v)), dq, self.w

    def seeds(self, p, clock=None):
        if self.crange is None:
            return [(0.0, 0.0)]
        lo, hi = self.crange
        ww = dot(self.w, self.w)
        best, out = math.inf, (lo, 0.0)
        for i in range(65):
            t = lo + (hi - lo) * i / 64
            q = sub(p, self.c.point(t))
            v = dot(q, self.w) / ww
            d = norm(sub(q, mul(self.w, v)))
            if d < best:
                best, out = d, (t, v)
        return [out]


def _rotate(q, axis, c, s):
    """``q`` turned about the unit ``axis`` by the angle of cosine ``c`` and sine ``s``."""
    return add(add(mul(q, c), mul(cross(axis, q), s)), mul(axis, dot(axis, q) * (1.0 - c)))


class Spun(Surface):
    """Presented swapped: u is the turn about the axis (period 2 pi), v the profile's
    parameter, so the poles where the profile meets the axis lie on lines v = const."""

    name = "SPUN_SURF"
    flip = -1

    def __init__(self, profile: Curve, base, axis, prange, tol: float) -> None:
        self.c, self.B, self.A = profile, base, axis
        self.pu = TWO_PI
        rng, period = _range(profile)
        if prange is not None:
            rng = prange
        if period is not None and prange is None:
            self.pv = period
            rng = None
        self.vrange = rng
        poles = []
        if rng is not None:
            for t in rng:
                q = profile.point(t)
                if self._radial(q)[1] <= tol:
                    poles.append((t, q))
        elif self.pv is not None and profile.lo is not None:
            # A closed profile (a circle) that crosses the axis, as a nose of revolved arc
            # does: each crossing is a pole, on the line v = its parameter (mod the period).
            poles = self._crossings(profile.lo, self.pv, tol)
        self.poles = tuple(poles)

    def _crossings(self, lo: float, period: float, tol: float):
        """The poles of a closed profile: ``(t, point)`` where it comes within ``tol`` of the
        axis, from a sampling of its period refined about each closest sample."""
        n = 96
        ts = [lo + period * k / n for k in range(n)]
        rho = [self._radial(self.c.point(t))[1] for t in ts]
        out = []
        for k in range(n):
            if not (rho[k] <= rho[k - 1] and rho[k] <= rho[(k + 1) % n]):
                continue
            a, b = ts[k] - period / n, ts[k] + period / n
            for _ in range(60):  # golden section on the distance to the axis
                m1, m2 = b - 0.618 * (b - a), a + 0.618 * (b - a)
                if self._radial(self.c.point(m1))[1] <= self._radial(self.c.point(m2))[1]:
                    b = m2
                else:
                    a = m1
            t = 0.5 * (a + b)
            q = self.c.point(t)
            if self._radial(q)[1] <= tol and all(
                abs((t - s + 0.5 * period) % period - 0.5 * period) > 1e-9 for s, _q in out
            ):
                out.append(((t - lo) % period + lo, q))
        return out

    def _radial(self, q):
        r = sub(q, self.B)
        h = dot(r, self.A)
        rad = sub(r, mul(self.A, h))
        return rad, norm(rad), h

    def d1(self, u, v):
        q, dq = self.c.d1(v)
        c, s = math.cos(u), math.sin(u)
        p = add(self.B, _rotate(sub(q, self.B), self.A, c, s))
        return p, cross(self.A, sub(p, self.B)), _rotate(dq, self.A, c, s)

    def from_file(self, u, v):
        return v, u

    def seeds(self, p, clock=None):
        _rad_p, rho_p, h_p = self._radial(p)
        rad_p = _rad_p
        rng = self.vrange
        if rng is None:
            if self.c.lo is None or self.c.hi is None:
                return []
            rng = (self.c.lo, self.c.hi)
        lo, hi = rng
        best, bt = math.inf, lo
        for i in range(97):
            t = lo + (hi - lo) * i / 96
            _rad, rho, h = self._radial(self.c.point(t))
            d = (rho - rho_p) ** 2 + (h - h_p) ** 2
            if d < best:
                best, bt = d, t
        rad_t, rho_t, _h = self._radial(self.c.point(bt))
        if rho_t <= 0.0 or rho_p <= 0.0:
            return [(0.0, bt)]
        ang = math.atan2(dot(self.A, cross(rad_t, rad_p)), dot(rad_t, rad_p))
        return [(ang, bt)]


class Offset(Surface):
    """``base(u, v) + offset n``, with n the base's unit normal pointing the way of the
    base node's own sense (its natural normal times that sense)."""

    name = "OFFSET_SURF"

    def __init__(self, base: Surface, offset: float, base_sense: int = 1) -> None:
        self.b = base
        # The base's normal here is in its own (perhaps swapped) parametrisation.
        self.d = offset * base_sense * base.flip
        self.kind = "parametric"
        self.flip, self.pu, self.pv = base.flip, base.pu, base.pv
        self.urange, self.vrange = base.urange, base.vrange

    def point(self, u, v):
        n = self.b.normal(u, v)
        q = self.b.point(u, v)
        if n is None:
            return q
        return add(q, mul(n, self.d))

    def d1(self, u, v):
        h = 1e-7
        p = self.point(u, v)
        su = mul(sub(self.point(u + h, v), self.point(u - h, v)), 0.5 / h)
        sv = mul(sub(self.point(u, v + h), self.point(u, v - h)), 0.5 / h)
        return p, su, sv

    def normal(self, u, v):
        return self.b.normal(u, v)

    def from_file(self, u, v):
        return self.b.from_file(u, v)

    def closest(self, p, hint, tol, ptol, clock=None, near=None):
        base_near = None if near is None else abs(self.d) + near
        u, v, _d = self.b.closest(p, hint, abs(self.d) + tol, ptol, clock, near=base_near)
        if u is None:
            return u, v, _d
        got = newton(self, p, u, v, iters=8)
        return got

    def speeds(self, box):
        return self.b.speeds(box)


class Geometry:
    """Surface and curve evaluators of one transmit, built once a node, with failures
    remembered and a guard against geometry that refers to itself. A rolling blend's
    surface is its approximation by ``blends`` (:class:`.blend.Blends`, which samples
    the edges of its faces); without them it is ``unsupported_surface``."""

    def __init__(self, topo: Topology, chord: float, blends=None) -> None:
        self.topo, self.chord = topo, chord
        self.blends = blends
        self._cache: dict[int, object] = {}
        self._building: set[int] = set()

    def _get(self, node, build):
        got = self._cache.get(node.index)
        if got is None:
            if node.index in self._building or len(self._building) >= MAX_DEPTH:
                raise FaceFailed("bad_reference", "geometry that refers to itself")
            self._building.add(node.index)
            try:
                got = build(node)
            except FaceFailed as exc:
                got = exc
            finally:
                self._building.discard(node.index)
            self._cache[node.index] = got
        if isinstance(got, FaceFailed):
            raise got
        return got

    def surface(self, node) -> Surface:
        return self._get(node, self._make_surface)  # type: ignore[return-value]

    def curve(self, node) -> Curve:
        return self._get(node, self._make_curve)  # type: ignore[return-value]

    def _make_curve(self, node):
        return make_curve(self.topo, node, self.surface, self.curve)

    def _make_surface(self, node) -> Surface:
        topo = self.topo
        t = node.type
        if t == PLANE:
            return Plane(topo.vector(node, "pvec"), topo.unit(node, "normal"), topo.vector(node, "x_axis"))
        if t == CYLINDER:
            return Cylinder(
                topo.vector(node, "pvec"),
                topo.unit(node, "axis"),
                topo.number(node, "radius"),
                topo.vector(node, "x_axis"),
            )
        if t == CONE:
            return Cone(
                topo.vector(node, "pvec"),
                topo.unit(node, "axis"),
                topo.number(node, "radius"),
                topo.number(node, "sin_half_angle"),
                topo.number(node, "cos_half_angle"),
                topo.vector(node, "x_axis"),
            )
        if t == SPHERE:
            return Sphere(
                topo.vector(node, "centre"),
                topo.number(node, "radius"),
                topo.unit(node, "axis"),
                topo.vector(node, "x_axis"),
            )
        if t == TORUS:
            return Torus(
                topo.vector(node, "centre"),
                topo.unit(node, "axis"),
                topo.number(node, "major_radius"),
                topo.number(node, "minor_radius"),
                topo.vector(node, "x_axis"),
            )
        if t == B_SURFACE:
            return _bsurface(topo, node, self.chord)
        if t == SWEPT_SURF:
            section = self.curve(topo.ref(node, "section", CURVE_TYPES, required=True))
            return Swept(section, topo.vector(node, "sweep"))
        if t == SPUN_SURF:
            profile = self.curve(topo.ref(node, "profile", CURVE_TYPES, required=True))
            return Spun(profile, topo.vector(node, "base"), topo.unit(node, "axis"), None, self.chord / 10.0)
        if t == OFFSET_SURF:
            bnode = topo.ref(node, "surface", SURFACE_TYPES, required=True)
            if bnode.type == BLENDED_EDGE:
                # An offset goes along its base's natural normal, and a blend's (Parasolid's
                # own parametrisation of it) is not known.
                raise FaceFailed("unsupported_surface", "an offset of a rolling blend")
            return Offset(self.surface(bnode), topo.number(node, "offset"), topo.sense(bnode))
        if t == BLENDED_EDGE:
            if self.blends is None:
                raise FaceFailed("unsupported_surface", "BLENDED_EDGE")
            return self.blends.evaluator(node)
        raise FaceFailed("unsupported_surface", node.tname)
