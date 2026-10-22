"""Synthetic parts for the drawing tests (``docs/DRAWINGS.md`` 19.1), built on
``xt_bodies.XtBuilder``: exact Parasolid bodies node by node, with their ground truth.

A part is described first and built last:

- :func:`prism` extrudes a profile in the XY plane along +Z. A profile is a list of
  points with :class:`Arc` items between them (a counter-clockwise arc is convex on
  an outer profile, a clockwise one a fillet); :func:`rounded` and :func:`chamfered`
  make corners.
- :func:`cut` takes a profile out of the top face, through or to a depth (a pocket,
  a slot, a window); its walls and floor are faces of their own.
- :func:`cut_hole` makes a hole from an entry point on any planar face whose normal
  is square to the hole's axis, as a stack of segments from the entry: a
  counterbore or spotface (``cbore``), a countersink (``csk``), bores (``bore``,
  through when the depth is None) and a flat or drill-point end. A hole whose entry
  face is not a frame plane is reported as needing an auxiliary view.
- :func:`add_boss` stands a cylinder on a planar face; :func:`cut_groove` cuts a
  face O-ring groove (an annular floor between a concave outer and a convex inner
  wall).

:func:`build` returns ``(transmit, truth)``. ``truth`` holds the envelope, every
feature with its values in metres, and the face count. The expected requirement
keys and dimension sets are written by the branches that plan them, from these
values (19.4).

Not built here yet, because they need intersection curves the builder does not
make: a cross hole entering a cylinder, a manifold passage ending in a cross bore,
and a slot on an inclined face. ``docs/drawings/REVIEW.md`` lists them for
``dwg-features``.
"""

from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass, field

from xt_bodies import XtBuilder

MM = 1e-3
X, Y, Z = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
AXES = {"+x": X, "-x": (-1.0, 0.0, 0.0), "+y": Y, "-y": (0.0, -1.0, 0.0), "+z": Z, "-z": (0.0, 0.0, -1.0)}


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b, strict=True))


def _add(a, b):
    return tuple(x + y for x, y in zip(a, b, strict=True))


def _mul(a, k):
    return tuple(x * k for x in a)


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a):
    n = math.sqrt(_dot(a, a))
    return tuple(x / n for x in a)


def _perp(a):
    """A unit vector square to ``a``."""
    helper = Z if abs(a[2]) < 0.9 else X
    return _unit(_cross(helper, a))


# --------------------------------------------------------------------------- profiles


@dataclass(frozen=True)
class Arc:
    """An arc from the previous point of a profile to ``end`` about ``centre``,
    counter-clockwise (seen from +Z) when ``ccw``."""

    centre: tuple[float, float]
    end: tuple[float, float]
    ccw: bool = True


def _segments(profile):
    """(start, end, None) for a line, (start, end, Arc) for an arc; the profile closes
    with a line back to its first point unless it ends there."""
    first = profile[0]
    out = []
    prev = first
    for item in profile[1:]:
        if isinstance(item, Arc):
            out.append((prev, item.end, item))
            prev = item.end
        else:
            out.append((prev, tuple(item), None))
            prev = tuple(item)
    if math.dist(prev, first) > 1e-12:
        out.append((prev, tuple(first), None))
    return out


def _sweep(start, end, arc: Arc) -> float:
    a0 = math.atan2(start[1] - arc.centre[1], start[0] - arc.centre[0])
    a1 = math.atan2(end[1] - arc.centre[1], end[0] - arc.centre[0])
    s = (a1 - a0) % (2 * math.pi) if arc.ccw else -((a0 - a1) % (2 * math.pi))
    return s


def polygon(profile, n_arc: int = 24) -> list[tuple[float, float]]:
    """The profile as points, arcs sampled, for inside tests and areas."""
    pts = []
    for start, end, arc in _segments(profile):
        pts.append(start)
        if arc is not None:
            r = math.dist(start, arc.centre)
            a0 = math.atan2(start[1] - arc.centre[1], start[0] - arc.centre[0])
            sweep = _sweep(start, end, arc)
            for k in range(1, n_arc):
                a = a0 + sweep * k / n_arc
                pts.append((arc.centre[0] + r * math.cos(a), arc.centre[1] + r * math.sin(a)))
    return pts


def signed_area(pts) -> float:
    """Positive for a counter-clockwise polygon."""
    return 0.5 * sum(pts[k - 1][0] * pts[k][1] - pts[k][0] * pts[k - 1][1] for k in range(len(pts)))


def inside(pts, x, y) -> bool:
    c = False
    for k, (ax, ay) in enumerate(pts):
        bx, by = pts[(k + 1) % len(pts)]
        if (ay > y) != (by > y) and x < ax + (bx - ax) * (y - ay) / (by - ay):
            c = not c
    return c


def _seg_distance(p, a, b) -> float:
    ab = _sub(b, a)
    t = max(0.0, min(1.0, _dot(_sub(p, a), ab) / _dot(ab, ab)))
    return math.dist(p, _add(a, _mul(ab, t)))


def clearance(pts, x, y) -> float:
    """How far (x, y) is from the polygon's boundary."""
    return min(_seg_distance((x, y), pts[k - 1], pts[k]) for k in range(len(pts)))


def rect(x0, y0, x1, y1):
    """A counter-clockwise rectangle."""
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def reverse(profile):
    """The same outline traversed the other way (an inner profile from an outer one)."""
    segs = _segments(profile)
    out = [segs[-1][1]]
    for start, _end, arc in reversed(segs):
        out.append(start if arc is None else Arc(arc.centre, start, not arc.ccw))
    if not isinstance(out[-1], Arc) and math.dist(out[-1], out[0]) < 1e-12:
        out.pop()
    return out


def stadium(cx, cy, length, width, angle=0.0):
    """A slot's outline, counter-clockwise: two half circles of diameter ``width`` whose
    centres are ``length`` apart, along ``angle`` (radians)."""
    r = width / 2
    d = (math.cos(angle), math.sin(angle))
    n = (-d[1], d[0])
    c1 = (cx - d[0] * length / 2, cy - d[1] * length / 2)
    c2 = (cx + d[0] * length / 2, cy + d[1] * length / 2)
    return [
        (c1[0] - n[0] * r, c1[1] - n[1] * r),
        (c2[0] - n[0] * r, c2[1] - n[1] * r),
        Arc(c2, (c2[0] + n[0] * r, c2[1] + n[1] * r), True),
        (c1[0] + n[0] * r, c1[1] + n[1] * r),
        Arc(c1, (c1[0] - n[0] * r, c1[1] - n[1] * r), True),
    ]


def rounded(points, radii):
    """A polygon (counter-clockwise points) with corner ``k`` rounded by ``radii[k]`` (0
    leaves it sharp): convex corners get convex arcs, concave ones fillets."""
    n = len(points)
    out = []
    for k in range(n):
        prev, here, nxt = points[k - 1], points[k], points[(k + 1) % n]
        r = radii[k]
        if not r:
            out.append(here)
            continue
        d1 = _unit(_sub(here, prev))
        d2 = _unit(_sub(nxt, here))
        turn = d1[0] * d2[1] - d1[1] * d2[0]
        half = math.acos(max(-1.0, min(1.0, -(d1[0] * d2[0] + d1[1] * d2[1])))) / 2
        back = r / math.tan(half)
        t1 = (here[0] - d1[0] * back, here[1] - d1[1] * back)
        t2 = (here[0] + d2[0] * back, here[1] + d2[1] * back)
        left1 = (-d1[1], d1[0]) if turn > 0 else (d1[1], -d1[0])
        centre = (t1[0] + left1[0] * r, t1[1] + left1[1] * r)
        out.append(t1)
        out.append(Arc(centre, t2, turn > 0))
    return out


def chamfered(points, legs):
    """A polygon with corner ``k`` cut by a 45 degree chamfer of leg ``legs[k]`` (0: sharp)."""
    n = len(points)
    out = []
    for k in range(n):
        prev, here, nxt = points[k - 1], points[k], points[(k + 1) % n]
        c = legs[k]
        if not c:
            out.append(here)
            continue
        d1 = _unit(_sub(here, prev))
        d2 = _unit(_sub(nxt, here))
        out.append((here[0] - d1[0] * c, here[1] - d1[1] * c))
        out.append((here[0] + d2[0] * c, here[1] + d2[1] * c))
    return out


# --------------------------------------------------------------------------- the description


@dataclass
class Hole:
    at: tuple
    axis: tuple  # unit, into the material
    stack: list
    name: str = ""


@dataclass
class Boss:
    at: tuple
    normal: tuple
    diameter: float
    height: float
    name: str = ""


@dataclass
class Groove:
    centre: tuple
    normal: tuple
    inner: float
    outer: float
    depth: float
    name: str = ""


@dataclass
class Part:
    profile: list
    z0: float
    z1: float
    cuts: list = field(default_factory=list)  # (profile, depth or None)
    holes: list = field(default_factory=list)
    bosses: list = field(default_factory=list)
    grooves: list = field(default_factory=list)
    extra_truth: dict = field(default_factory=dict)


def prism(profile, height, *, z0=0.0) -> Part:
    """``profile`` (counter-clockwise seen from +Z) extruded from ``z0`` up by ``height``."""
    pts = polygon(profile)
    if signed_area(pts) <= 0:
        raise ValueError("an outer profile runs counter-clockwise")
    return Part(list(profile), z0, z0 + height)


def box(w, d, h, origin=(0.0, 0.0, 0.0)) -> Part:
    x0, y0, z0 = origin
    return prism(rect(x0, y0, x0 + w, y0 + d), h, z0=z0)


def cut(part: Part, profile, depth=None) -> Part:
    """Cut ``profile`` (counter-clockwise points) from the top face: through when
    ``depth`` is None, else a pocket of that depth."""
    p = copy.deepcopy(part)
    if depth is not None and not 0 < depth < p.z1 - p.z0:
        raise ValueError("a pocket must be shallower than the part")
    p.cuts.append((reverse(profile), depth))
    return p


def cut_hole(part: Part, at, axis, stack, name="") -> Part:
    """A hole entering at ``at`` along ``axis`` (a unit vector or ``+z`` and the like,
    pointing into the material). ``stack`` lists the segments from the entry:
    ``("cbore", D, depth)``, ``("csk", D, included_deg)``, ``("bore", d, depth)`` (depth
    None: through to the far face), ``("step", d, depth, included_deg)`` (a bore
    ending in a cone down to the next bore), and last ``("flat",)`` or ``("point",
    included_deg)`` for a blind end."""
    p = copy.deepcopy(part)
    a = AXES[axis] if isinstance(axis, str) else _unit(axis)
    p.holes.append(Hole(tuple(at), a, list(stack), name))
    return p


def add_boss(part: Part, at, normal, diameter, height, name="") -> Part:
    p = copy.deepcopy(part)
    n = AXES[normal] if isinstance(normal, str) else _unit(normal)
    p.bosses.append(Boss(tuple(at), n, diameter, height, name))
    return p


def cut_groove(part: Part, centre, normal, inner, outer, depth, name="") -> Part:
    p = copy.deepcopy(part)
    n = AXES[normal] if isinstance(normal, str) else _unit(normal)
    p.grooves.append(Groove(tuple(centre), n, inner, outer, depth, name))
    return p


def translate(part: Part, dx, dy, dz) -> Part:
    """The part moved: its origin no longer where it was (a regeneration pair)."""

    def move(profile):
        out = []
        for item in profile:
            if isinstance(item, Arc):
                out.append(
                    Arc(
                        (item.centre[0] + dx, item.centre[1] + dy),
                        (item.end[0] + dx, item.end[1] + dy),
                        item.ccw,
                    )
                )
            else:
                out.append((item[0] + dx, item[1] + dy))
        return out

    p = copy.deepcopy(part)
    p.profile = move(p.profile)
    p.cuts = [(move(pr), depth) for pr, depth in p.cuts]
    p.z0 += dz
    p.z1 += dz
    for h in p.holes:
        h.at = _add(h.at, (dx, dy, dz))
    for b in p.bosses:
        b.at = _add(b.at, (dx, dy, dz))
    for g in p.grooves:
        g.centre = _add(g.centre, (dx, dy, dz))
    return p


# --------------------------------------------------------------------------- building


class _Planar:
    """A planar face before it is made: its plane, its loops, and how to tell whether a
    point lies inside it (a polygon in the plane's own (x, y), minus the holes)."""

    def __init__(self, origin, normal, xdir, outer2d, holes2d=(), kind="face"):
        self.origin, self.normal, self.x = origin, normal, xdir
        self.y = _cross(normal, xdir)
        self.outer2d = outer2d
        self.holes2d = list(holes2d)
        self.loops: list = []
        self.kind = kind

    def local(self, p):
        q = _sub(p, self.origin)
        return _dot(q, self.x), _dot(q, self.y), _dot(q, self.normal)

    def holds(self, p, r=0.0, tol=1e-9) -> bool:
        u, v, w = self.local(p)
        if abs(w) > tol:
            return False
        if not inside(self.outer2d, u, v) or clearance(self.outer2d, u, v) <= r:
            return False
        for h in self.holes2d:
            if inside(h, u, v) or clearance(h, u, v) <= r:
                return False
        return True


class _Builder:
    def __init__(self) -> None:
        self.b = XtBuilder()
        self.vertices: dict = {}
        self.lines: dict = {}
        self.edges: list = []
        self.faces: list = []  # (surface, sense, loops) or a _Planar
        self.planars: list[_Planar] = []

    def vertex(self, p):
        key = tuple(round(c * 1e9) for c in p)
        if key not in self.vertices:
            self.vertices[key] = self.b.vertex(p)
        return self.vertices[key]

    def line(self, a, c):
        """The edge from a to c (shared), and the sense that traverses it a to c."""
        ka, kc = tuple(round(x * 1e9) for x in a), tuple(round(x * 1e9) for x in c)
        key = (min(ka, kc), max(ka, kc))
        if key not in self.lines:
            lo, hi = (a, c) if ka <= kc else (c, a)
            e = self.b.edge(self.b.line(lo, _unit(_sub(hi, lo))), self.vertex(lo), self.vertex(hi))
            self.lines[key] = (e, None)
            self.edges.append(e)
        e, _ = self.lines[key]
        forward = tuple(round(x * 1e9) for x in a) == key[0]
        return e, "+" if forward else "-"

    def ring(self, centre, normal, r):
        e = self.b.edge(self.b.circle(centre, normal, _perp(normal), r))
        self.edges.append(e)
        return e

    def arc(self, centre, start, end, ccw):
        """An arc edge about +Z through start and end (z equal), and the sense that runs
        start to end."""
        r = math.dist(start[:2], centre[:2])
        circle = self.b.circle(centre, Z, X, r)
        if ccw:
            e = self.b.edge(circle, self.vertex(start), self.vertex(end))
            sense = "+"
        else:
            e = self.b.edge(circle, self.vertex(end), self.vertex(start))
            sense = "-"
        self.edges.append(e)
        return e, sense


def _flip(fins):
    return [(e, "-" if s == "+" else "+") for e, s in reversed(fins)]


def _level(bld: _Builder, profile, z):
    """A profile's edges at height z: one (edge, sense) a segment, running the profile's
    way, and each segment's 3D start and end."""
    fins, segs = [], []
    for start, end, arc in _segments(profile):
        a, c = (start[0], start[1], z), (end[0], end[1], z)
        if arc is None:
            fins.append(bld.line(a, c))
        else:
            fins.append(bld.arc((arc.centre[0], arc.centre[1], z), a, c, arc.ccw))
        segs.append((a, c, arc))
    return fins, segs


def _walls(bld: _Builder, profile, z_lo, z_hi, bottom, top):
    """The side faces of a profile between two levels, whose edges are ``bottom`` and
    ``top`` (from :func:`_level`): each outward to the right of the profile's way."""
    for k, (start, end, arc) in enumerate(_segments(profile)):
        p0, q0 = (start[0], start[1], z_lo), (end[0], end[1], z_lo)
        p1, q1 = (start[0], start[1], z_hi), (end[0], end[1], z_hi)
        up_q = bld.line(q0, q1)
        down_p = bld.line(p1, p0)
        e_bot, s_bot = bottom[k]
        e_top, s_top = top[k]
        loop = [(e_bot, s_bot), up_q, (e_top, "-" if s_top == "+" else "+"), down_p]
        if arc is None:
            d = _unit(_sub(q0, p0))
            normal = (d[1], -d[0], 0.0)
            length = math.dist(p0, q0)
            pl = _Planar(p0, normal, d, rect(0.0, 0.0, length, z_hi - z_lo), kind="side")
            pl.loops.append(loop)
            bld.planars.append(pl)
        else:
            r = math.dist(start, arc.centre)
            surface = bld.b.cylinder((arc.centre[0], arc.centre[1], z_lo), Z, r, X)
            bld.faces.append((surface, "+" if arc.ccw else "-", [loop]))


def _ring_poly(r, n=48):
    return [(r * math.cos(2 * math.pi * k / n), r * math.sin(2 * math.pi * k / n)) for k in range(n)]


def _find_face(bld: _Builder, point, normal, r, what):
    for pl in bld.planars:
        if _dot(pl.normal, normal) > 1 - 1e-9 and pl.holds(point, r):
            return pl
    raise ValueError(f"no planar face holds the {what} at {point}")


def _attach(pl: _Planar, ring, centre, ring_normal, r):
    """Put a circle into a planar face as an inner loop, and keep it out of the face's
    region for what comes after."""
    sense = "-" if _dot(ring_normal, pl.normal) > 0 else "+"
    pl.loops.append([(ring, sense)])
    u, v, _w = pl.local(centre)
    pl.holes2d.append([(u + x, v + y) for x, y in _ring_poly(r)])


def _profile_of(hole: Hole):
    """A hole's profile as (w, r) from the entry (w = 0) going in (w negative), and how it
    ends: ``through``, ``flat`` or ``point``; marks where a planar shoulder is."""
    pts = []
    end = "through"
    w = 0.0
    stack = hole.stack
    bores = [s for s in stack if s[0] in ("bore", "step")]
    for i, seg in enumerate(stack):
        kind = seg[0]
        if kind == "cbore":
            d, depth = seg[1], seg[2]
            pts += [(w, d / 2), (w - depth, d / 2)]
            w -= depth
        elif kind == "csk":
            d, angle = seg[1], math.radians(seg[2])
            nxt = next(s for s in stack[i + 1 :] if s[0] in ("bore", "step"))
            r_next = nxt[1] / 2
            drop = (d / 2 - r_next) / math.tan(angle / 2)
            pts += [(w, d / 2)]
            w -= drop
        elif kind in ("bore", "step"):
            d, depth = seg[1], seg[2]
            pts.append((w, d / 2))
            if depth is None:
                pts.append((None, d / 2))
                end = "through"
                break
            w -= depth
            pts.append((w, d / 2))
            if kind == "step":
                k = bores.index(seg)
                r_next = bores[k + 1][1] / 2
                angle = math.radians(seg[3])
                w -= (d / 2 - r_next) / math.tan(angle / 2)
        elif kind == "flat":
            end = "flat"
        elif kind == "point":
            end = ("point", math.radians(seg[1]))
    return pts, end


def _make_hole(bld: _Builder, hole: Hole):
    A = _mul(hole.axis, -1.0)  # out of the material, toward the entry
    pts, end = _profile_of(hole)
    entry_r = pts[0][1]
    entry = _find_face(bld, hole.at, A, entry_r, "hole's entry")
    exit_face = None
    if pts[-1][0] is None:
        # through: the nearest face facing along the hole's travel that holds its axis
        best = None
        for pl in bld.planars:
            if _dot(pl.normal, hole.axis) > 1 - 1e-9:
                depth = _dot(_sub(pl.origin, hole.at), hole.axis)
                p = _add(hole.at, _mul(hole.axis, depth))
                if depth > 0 and pl.holds(p, pts[-1][1]) and (best is None or depth < best[0]):
                    best = (depth, pl)
        if best is None:
            raise ValueError(f"the hole at {hole.at} finds no face to leave by")
        exit_face = best[1]
        pts[-1] = (-best[0], pts[-1][1])
    # (w, r) corners, merged where a point repeats
    corners = []
    for w, r in pts:
        if corners and abs(corners[-1][0] - w) < 1e-12 and abs(corners[-1][1] - r) < 1e-12:
            continue
        corners.append((w, r))
    rings = [bld.ring(_add(hole.at, _mul(A, w)), A, r) for w, r in corners]
    _attach(entry, rings[0], hole.at, A, corners[0][1])
    for k in range(len(corners) - 1):
        (w1, r1), (w2, r2) = corners[k], corners[k + 1]
        hi, lo = rings[k], rings[k + 1]
        if abs(w1 - w2) < 1e-12:  # a planar shoulder facing the entry
            centre = _add(hole.at, _mul(A, w1))
            surface = bld.b.plane(centre, A, _perp(A))
            bld.faces.append((surface, "+", [[(hi, "+")], [(lo, "-")]]))
        elif abs(r1 - r2) < 1e-12:  # a bore
            base = _add(hole.at, _mul(A, w2))
            surface = bld.b.cylinder(base, A, r1, _perp(A))
            bld.faces.append((surface, "-", [[(lo, "-")], [(hi, "+")]]))
        else:  # a countersink or a step's cone, wider toward the entry
            base = _add(hole.at, _mul(A, w2))
            half = math.atan2(r1 - r2, w1 - w2)
            surface = bld.b.cone(base, A, r2, half, _perp(A))
            bld.faces.append((surface, "-", [[(lo, "-")], [(hi, "+")]]))
    w_end, r_end = corners[-1]
    last = rings[-1]
    if exit_face is not None:
        _attach(exit_face, last, _add(hole.at, _mul(A, w_end)), A, r_end)
    elif end == "flat":
        centre = _add(hole.at, _mul(A, w_end))
        bld.faces.append((bld.b.plane(centre, A, _perp(A)), "+", [[(last, "+")]]))
    else:
        angle = end[1]
        half = angle / 2
        base = _add(hole.at, _mul(A, w_end))
        bld.faces.append((bld.b.cone(base, A, r_end, half, _perp(A)), "-", [[(last, "+")]]))
    return corners, end, entry


def _make_boss(bld: _Builder, boss: Boss):
    r = boss.diameter / 2
    base_face = _find_face(bld, boss.at, boss.normal, r, "boss")
    base = bld.ring(boss.at, boss.normal, r)
    top_centre = _add(boss.at, _mul(boss.normal, boss.height))
    top = bld.ring(top_centre, boss.normal, r)
    _attach(base_face, base, boss.at, boss.normal, r)
    bld.faces.append(
        (bld.b.cylinder(boss.at, boss.normal, r, _perp(boss.normal)), "+", [[(base, "+")], [(top, "-")]])
    )
    cap = _Planar(top_centre, boss.normal, _perp(boss.normal), _ring_poly(r), kind="cap")
    cap.loops.append([(top, "+")])
    bld.planars.append(cap)


def _make_groove(bld: _Builder, g: Groove):
    face = _find_face(bld, g.centre, g.normal, g.outer / 2, "groove")
    n = g.normal
    floor_centre = _add(g.centre, _mul(n, -g.depth))
    ro, ri = g.outer / 2, g.inner / 2
    top_o, top_i = bld.ring(g.centre, n, ro), bld.ring(g.centre, n, ri)
    bot_o, bot_i = bld.ring(floor_centre, n, ro), bld.ring(floor_centre, n, ri)
    _attach(face, top_o, g.centre, n, ro)
    bld.faces.append((bld.b.cylinder(floor_centre, n, ro, _perp(n)), "-", [[(bot_o, "-")], [(top_o, "+")]]))
    bld.faces.append((bld.b.plane(floor_centre, n, _perp(n)), "+", [[(bot_o, "+")], [(bot_i, "-")]]))
    bld.faces.append((bld.b.cylinder(floor_centre, n, ri, _perp(n)), "+", [[(bot_i, "+")], [(top_i, "-")]]))
    island = _Planar(g.centre, n, _perp(n), _ring_poly(ri), kind="island")
    island.loops.append([(top_i, "+")])
    bld.planars.append(island)


def build(part: Part):
    """The part as ``(XtTransmit, truth)``."""
    bld = _Builder()
    z0, z1 = part.z0, part.z1
    outer_bot, _ = _level(bld, part.profile, z0)
    outer_top, _ = _level(bld, part.profile, z1)
    top = _Planar((0.0, 0.0, z1), Z, X, [(p[0], p[1]) for p in polygon(part.profile)], kind="top")
    bottom = _Planar(
        (0.0, 0.0, z0), (0.0, 0.0, -1.0), X, [(p[0], -p[1]) for p in polygon(part.profile)], kind="bottom"
    )
    top.loops.append(outer_top)
    bottom.loops.append(_flip(outer_bot))
    bld.planars += [top, bottom]
    _walls(bld, part.profile, z0, z1, outer_bot, outer_top)
    for profile, depth in part.cuts:
        z_f = z0 if depth is None else z1 - depth
        at_top, _ = _level(bld, profile, z1)
        at_floor, _ = _level(bld, profile, z_f)
        top.loops.append(at_top)
        top.holes2d.append([(p[0], p[1]) for p in polygon(profile)])
        if depth is None:
            bottom.loops.append(_flip(at_floor))
            bottom.holes2d.append([(p[0], -p[1]) for p in polygon(profile)])
        else:
            floor = _Planar(
                (0.0, 0.0, z_f), Z, X, [(p[0], p[1]) for p in polygon(reverse(profile))], kind="floor"
            )
            floor.loops.append(_flip(at_floor))
            bld.planars.append(floor)
        _walls(bld, profile, z_f, z1, at_floor, at_top)
    for g in part.grooves:
        _make_groove(bld, g)
    for boss in part.bosses:
        _make_boss(bld, boss)
    made = [(_make_hole(bld, h), h) for h in part.holes]
    for pl in bld.planars:
        surface = bld.b.plane(pl.origin, pl.normal, pl.x)
        bld.faces.append((surface, "+", pl.loops))
    for surface, sense, loops in bld.faces:
        bld.b.face(surface, sense, loops)
    xt = bld.b.body(bld.edges)
    return xt, _truth(part, made, len(bld.faces))


# --------------------------------------------------------------------------- truth


def _hole_kind(hole: Hole) -> str:
    kinds = [s[0] for s in hole.stack]
    parts = []
    if "cbore" in kinds:
        depth = next(s[2] for s in hole.stack if s[0] == "cbore")
        parts.append("spotface" if depth <= 1.0 * MM else "counterbore")
    if "csk" in kinds:
        parts.append("countersink")
    if "step" in kinds:
        parts.append("stepped")
    return "+".join(parts) or "simple"


def _truth(part: Part, made, n_faces) -> dict:
    pts = polygon(part.profile)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    lo, hi = [min(xs), min(ys), part.z0], [max(xs), max(ys), part.z1]
    for b in part.bosses:  # a boss along a frame axis stands out of the profile's box
        top = _add(b.at, _mul(b.normal, b.height))
        for i in range(3):
            reach = 0.0 if abs(b.normal[i]) > 0.5 else b.diameter / 2
            lo[i] = min(lo[i], b.at[i] - reach, top[i] - reach)
            hi[i] = max(hi[i], b.at[i] + reach, top[i] + reach)
    holes = []
    for (corners, end, entry), h in made:
        bores = [s for s in h.stack if s[0] in ("bore", "step")]
        ends = "thru" if end == "through" else (end if isinstance(end, str) else "point")
        full_depth = None
        if ends != "thru":
            last = [c for c in corners if abs(c[1] - bores[-1][1] / 2) < 1e-12]
            full_depth = -last[-1][0]
        holes.append(
            {
                "name": h.name,
                "at": h.at,
                "axis": h.axis,
                "kind": _hole_kind(h),
                "diameter": bores[-1][1],
                "diameters": [s[1] for s in h.stack if s[0] in ("cbore", "bore", "step", "csk")],
                "end": ends,
                "depth": full_depth,
                "stack": [tuple(s) for s in h.stack],
                "entry": entry.kind,
                "needs_auxiliary": max(abs(c) for c in h.axis) < 1 - 1e-9,
            }
        )
    return {
        "envelope": tuple(hi[i] - lo[i] for i in range(3)),
        "box": (tuple(lo), tuple(hi)),
        "faces": n_faces,
        "holes": holes,
        "bosses": [
            {"name": b.name, "at": b.at, "diameter": b.diameter, "height": b.height} for b in part.bosses
        ],
        "grooves": [
            {"name": g.name, "centre": g.centre, "inner": g.inner, "outer": g.outer, "depth": g.depth}
            for g in part.grooves
        ],
        "cuts": [{"depth": d, "through": d is None} for _p, d in part.cuts],
        **part.extra_truth,
    }


# --------------------------------------------------------------------------- the stage 1 parts


def hole_kinds_plate():
    """A 160 x 80 x 20 mm plate with one hole of each kind along -Z from the top: simple,
    counterbore, spotface, countersinks at 82 and 90 degrees, blind flat, drill point
    and stepped."""
    t = 20 * MM
    p = box(160 * MM, 80 * MM, t)
    top = lambda x, y: (x * MM, y * MM, t)  # noqa: E731
    p = cut_hole(p, top(15, 20), "-z", [("bore", 6.6 * MM, None)], "simple")
    p = cut_hole(
        p, top(40, 20), "-z", [("cbore", 11 * MM, 6.5 * MM), ("bore", 6.6 * MM, None)], "counterbore"
    )
    p = cut_hole(p, top(65, 20), "-z", [("cbore", 13 * MM, 0.5 * MM), ("bore", 6.6 * MM, None)], "spotface")
    p = cut_hole(p, top(90, 20), "-z", [("csk", 12 * MM, 82), ("bore", 6.6 * MM, None)], "countersink82")
    p = cut_hole(p, top(115, 20), "-z", [("csk", 12 * MM, 90), ("bore", 6.6 * MM, None)], "countersink90")
    p = cut_hole(p, top(30, 55), "-z", [("bore", 8 * MM, 12 * MM), ("flat",)], "blind_flat")
    p = cut_hole(p, top(70, 55), "-z", [("bore", 6.8 * MM, 14 * MM), ("point", 118)], "drill_point")
    p = cut_hole(p, top(110, 55), "-z", [("step", 10 * MM, 8 * MM, 118), ("bore", 5 * MM, None)], "stepped")
    return build(p)


def patterns_plate():
    """A 200 x 120 x 10 mm plate: a linear row of five 5.5 mm holes at 20 mm pitch, a
    3 x 2 grid of 4.5 mm holes at 15 by 12 mm, and six 5.5 mm holes on a 40 mm pitch
    circle clocked 15 degrees round a 16 mm bore."""
    t = 10 * MM
    p = box(200 * MM, 120 * MM, t)
    for k in range(5):
        p = cut_hole(p, ((20 + 20 * k) * MM, 20 * MM, t), "-z", [("bore", 5.5 * MM, None)], f"linear{k}")
    for i in range(3):
        for j in range(2):
            p = cut_hole(
                p,
                ((20 + 15 * i) * MM, (70 + 12 * j) * MM, t),
                "-z",
                [("bore", 4.5 * MM, None)],
                f"grid{i}{j}",
            )
    c = (150 * MM, 60 * MM)
    p = cut_hole(p, (c[0], c[1], t), "-z", [("bore", 16 * MM, None)], "bore")
    for k in range(6):
        a = math.radians(15 + 60 * k)
        at = (c[0] + 20 * MM * math.cos(a), c[1] + 20 * MM * math.sin(a), t)
        p = cut_hole(p, at, "-z", [("bore", 5.5 * MM, None)], f"circular{k}")
    p.extra_truth = {
        "patterns": [
            {"kind": "linear", "count": 5, "pitch": 20 * MM, "diameter": 5.5 * MM},
            {"kind": "grid", "counts": (3, 2), "pitches": (15 * MM, 12 * MM), "diameter": 4.5 * MM},
            {"kind": "circular", "count": 6, "pcd": 40 * MM, "first_deg": 15.0, "diameter": 5.5 * MM},
        ]
    }
    return build(p)


def arc_plate(angles_deg, bore: bool = True):
    """A 100 x 100 x 10 mm plate with 5 mm holes on a 60 mm pitch circle at the angles
    given (degrees from X), round a 16 mm bore in the middle unless ``bore`` is False."""
    t = 10 * MM
    p = box(100 * MM, 100 * MM, t)
    if bore:
        p = cut_hole(p, (50 * MM, 50 * MM, t), "-z", [("bore", 16 * MM, None)], "bore")
    for k, deg in enumerate(angles_deg):
        a = math.radians(deg)
        at = (50 * MM + 30 * MM * math.cos(a), 50 * MM + 30 * MM * math.sin(a), t)
        p = cut_hole(p, at, "-z", [("bore", 5 * MM, None)], f"arc{k}")
    return build(p)


def arc_pattern_plate():
    """``arc_plate`` with five holes 30 degrees apart from 20 degrees: an arc pattern whose
    first end needs its angle (the arc-pattern golden)."""
    return arc_plate([20, 50, 80, 110, 140])


def four_holes_plate():
    """A 100 x 60 x 10 mm plate with four 6.6 mm holes at irregular positions: eight
    locations."""
    t = 10 * MM
    p = box(100 * MM, 60 * MM, t)
    for k, (x, y) in enumerate([(12, 10), (37, 48), (71, 15), (88, 44)]):
        p = cut_hole(p, (x * MM, y * MM, t), "-z", [("bore", 6.6 * MM, None)], f"h{k}")
    p.extra_truth = {"patterns": [{"kind": "scattered", "count": 4, "diameter": 6.6 * MM}]}
    return build(p)


def link_plate():
    """A 120 x 30 x 8 mm link with full-round ends (R15, "2X R" without a value) and a
    12 mm hole at each end's centre."""
    t, L, w = 8 * MM, 120 * MM, 30 * MM
    r = w / 2
    profile = [(r, 0.0), (L - r, 0.0), Arc((L - r, r), (L - r, w), True), (r, w), Arc((r, r), (r, 0.0), True)]
    p = prism(profile, t)
    for k, x in enumerate((r, L - r)):
        p = cut_hole(p, (x, r, t), "-z", [("bore", 12 * MM, None)], f"end{k}")
    p.extra_truth = {"full_round": {"radius": r, "derived": True, "count": 2}}
    return build(p)


def boss_block():
    """A 60 x 60 x 20 mm block topped by a 30 mm boss 15 mm high, with a 10 mm hole down
    through both."""
    h = 20 * MM
    p = box(60 * MM, 60 * MM, h)
    p = add_boss(p, (30 * MM, 30 * MM, h), "+z", 30 * MM, 15 * MM, "boss")
    p = cut_hole(p, (30 * MM, 30 * MM, h + 15 * MM), "-z", [("bore", 10 * MM, None)], "through_boss")
    return build(p)


def pocket_tab_block():
    """A block 80 wide and 20 high (front view, XY) with a 6 mm tab standing 15 mm on its
    top near the right, 50 deep along Z, and a 40 x 12 x 8 mm pocket in its +Z face:
    the tab's thickness and the pocket's width, length and depth are each stated
    directly."""
    L, H, D = 80 * MM, 20 * MM, 50 * MM
    tx0, tx1, th = 66 * MM, 72 * MM, 35 * MM
    profile = [(0.0, 0.0), (L, 0.0), (L, H), (tx1, H), (tx1, th), (tx0, th), (tx0, H), (0.0, H)]
    p = prism(profile, D)
    p = cut(p, rect(15 * MM, 4 * MM, 55 * MM, 16 * MM), 8 * MM)
    p.extra_truth = {
        "tab": {"thickness": tx1 - tx0, "height": th - H, "x": (tx0, tx1)},
        "pocket": {"x": (15 * MM, 55 * MM), "y": (4 * MM, 16 * MM), "depth": 8 * MM},
    }
    return build(p)


def step_slot_block():
    """A block 100 x 60 x 30 mm with a 20 x 20 step out of its back right corner, its
    convex vertical corners chamfered 3 mm, a through slot 8 wide with 30 between end
    centres, and a blind slot 6 wide, 20 between centres and 5 deep."""
    W, D, H = 100 * MM, 60 * MM, 30 * MM
    corners = [(0.0, 0.0), (W, 0.0), (W, 40 * MM), (80 * MM, 40 * MM), (80 * MM, D), (0.0, D)]
    outline = chamfered(corners, [3 * MM, 3 * MM, 3 * MM, 0.0, 3 * MM, 3 * MM])
    p = prism(outline, H)
    p = cut(p, stadium(30 * MM, 20 * MM, 30 * MM, 8 * MM))
    p = cut(p, stadium(60 * MM, 25 * MM, 20 * MM, 6 * MM, math.pi / 2), 5 * MM)
    p.extra_truth = {
        "step": {"face_y": 40 * MM, "x": (80 * MM, W)},
        "slots": [
            {"width": 8 * MM, "centres": 30 * MM, "depth": None},
            {"width": 6 * MM, "centres": 20 * MM, "depth": 5 * MM},
        ],
        "chamfers": {"leg": 3 * MM, "count": 5},
    }
    return build(p)


def angled_round_block():
    """An 80 x 40 x 30 mm block (front view) whose top right is cut at 30 degrees, the
    angled face meeting the top at an R5 round: the meet line is a virtual sharp."""
    L, H, D = 80 * MM, 30 * MM, 40 * MM
    corner = (55 * MM, H)
    drop = (L - corner[0]) * math.tan(math.radians(30))
    pts = [(0.0, 0.0), (L, 0.0), (L, H - drop), corner, (0.0, H)]
    profile = rounded(pts, [0, 0, 0, 5 * MM, 0])
    p = prism(profile, D)
    p.extra_truth = {"angled": {"angle_deg": 30.0, "round": 5 * MM, "sharp": corner}}
    return build(p)


def inclined_hole_block():
    """A 60 x 40 x 30 mm block (front view) with its top right cut at 45 degrees and a
    blind 6 mm hole square to that face: it needs an auxiliary view."""
    L, H, D = 60 * MM, 30 * MM, 40 * MM
    pts = [(0.0, 0.0), (L, 0.0), (L, 15 * MM), (45 * MM, H), (0.0, H)]
    p = prism(pts, D)
    mid = (52.5 * MM, 22.5 * MM)
    n = _unit((1.0, 1.0, 0.0))
    p = cut_hole(
        p, (mid[0], mid[1], 20 * MM), _mul(n, -1.0), [("bore", 6 * MM, 8 * MM), ("flat",)], "inclined"
    )
    return build(p)


def groove_plate():
    """A 80 x 80 x 15 mm plate with a face O-ring groove (inner 40, outer 50, 3 deep) round
    a 20 mm through hole."""
    t = 15 * MM
    p = box(80 * MM, 80 * MM, t)
    p = cut_groove(p, (40 * MM, 40 * MM, t), "+z", 40 * MM, 50 * MM, 3 * MM, "oring")
    p = cut_hole(p, (40 * MM, 40 * MM, t), "-z", [("bore", 20 * MM, None)], "bore")
    return build(p)


def sixteen_holes_plate():
    """A 300 x 200 x 10 mm plate with sixteen 5 mm holes at scattered positions: more
    than the ordinate switch's tracks."""
    t = 10 * MM
    p = box(300 * MM, 200 * MM, t)
    rng = random.Random(16)
    xs = rng.sample(range(2, 58), 16)
    ys = rng.sample(range(2, 38), 16)
    for k, (x, y) in enumerate(zip(xs, ys, strict=True)):
        p = cut_hole(p, (x * 5 * MM, y * 5 * MM, t), "-z", [("bore", 5 * MM, None)], f"h{k}")
    return build(p)


def printed_bracket():
    """A printed L-bracket (front view an L, 50 deep): a 60 x 6 mm base and a 40 x 6 mm
    upright, two 5 mm holes down through the base and two through the upright."""
    D = 50 * MM
    profile = [
        (0.0, 0.0),
        (60 * MM, 0.0),
        (60 * MM, 6 * MM),
        (6 * MM, 6 * MM),
        (6 * MM, 40 * MM),
        (0.0, 40 * MM),
    ]
    p = prism(profile, D)
    for k, z in enumerate((15 * MM, 35 * MM)):
        p = cut_hole(p, (40 * MM, 6 * MM, z), "-y", [("bore", 5 * MM, None)], f"base{k}")
        p = cut_hole(p, (6 * MM, 25 * MM, z), "-x", [("bore", 5 * MM, None)], f"upright{k}")
    return build(p)


def random_plate(seed: int, n: int = 8):
    """A seeded plate with ``n`` holes kept apart from each other and the edges."""
    rng = random.Random(seed)
    w, d, t = rng.randint(60, 200) * MM, rng.randint(40, 120) * MM, rng.choice((6, 8, 10, 12)) * MM
    p = box(w, d, t)
    placed: list[tuple[float, float, float]] = []
    tries = 0
    while len(placed) < n and tries < 2000:
        tries += 1
        dia = rng.choice((3.4, 4.5, 5.5, 6.6, 9.0)) * MM
        x = rng.uniform(dia + 2 * MM, w - dia - 2 * MM)
        y = rng.uniform(dia + 2 * MM, d - dia - 2 * MM)
        if all(math.dist((x, y), (px, py)) > (dia + pd) / 2 + 3 * MM for px, py, pd in placed):
            placed.append((x, y, dia))
    for k, (x, y, dia) in enumerate(placed):
        p = cut_hole(p, (x, y, t), "-z", [("bore", dia, None)], f"h{k}")
    return build(p)


def random_block(seed: int):
    """A seeded machined block, nearer the parts a shop draws than :func:`random_plate`: an
    outline with corners rounded to mixed radii (some sharp), up to three pockets with
    corner radii, a through slot half the time and two to ten holes of mixed sizes, all
    kept apart from each other, the edges and the rounded corners. Its layouts give the
    callouts, radii, frames and datum symbols a sheet has to find room for."""
    rng = random.Random(seed)
    w, d = rng.randint(60, 180), rng.randint(40, 120)  # mm, as everything below until built
    t = rng.choice((8, 10, 12, 16, 20))
    corners = [rng.choice((0, 0, 3, 5, 8, 10)) * MM for _ in range(4)]
    p = prism(rounded([(0.0, 0.0), (w * MM, 0.0), (w * MM, d * MM), (0.0, d * MM)], corners), t * MM)
    taken: list[tuple[float, float, float, float]] = []

    def free(x0, y0, x1, y1, gap=3.0):
        if x0 < 4 or y0 < 4 or x1 > w - 4 or y1 > d - 4:
            return False
        apart = (x1 + gap < u0 or x0 - gap > u1 or y1 + gap < v0 or y0 - gap > v1 for u0, v0, u1, v1 in taken)
        return all(apart)

    for _ in range(rng.randint(0, 3)):
        for _try in range(50):
            pw, ph = rng.uniform(12, w / 2.5), rng.uniform(10, d / 2.5)
            x0, y0 = rng.uniform(6, w - pw - 6), rng.uniform(6, d - ph - 6)
            if free(x0, y0, x0 + pw, y0 + ph):
                r = min(rng.choice((0, 2, 3, 4, 6)), pw / 2 - 0.5, ph / 2 - 0.5)
                pocket = rounded(rect(x0 * MM, y0 * MM, (x0 + pw) * MM, (y0 + ph) * MM), [r * MM] * 4)
                depth = rng.choice((2, 3, 4, 5, 6))
                if depth < t - 1:
                    p = cut(p, pocket, depth * MM)
                    taken.append((x0, y0, x0 + pw, y0 + ph))
                break
    if rng.random() < 0.5:
        for _try in range(50):
            length, width = rng.uniform(10, 30), rng.choice((6.0, 8.0, 10.0))
            cx = rng.uniform(6 + length / 2 + width, w - 6 - length / 2 - width)
            cy = rng.uniform(6 + width, d - 6 - width)
            reach = length / 2 + width / 2
            outline = (cx - reach, cy - width / 2, cx + reach, cy + width / 2)
            if free(*outline):
                p = cut(p, stadium(cx * MM, cy * MM, length * MM, width * MM))
                taken.append(outline)
                break
    for k in range(rng.randint(2, 10)):
        for _try in range(80):
            dia = rng.choice((3.4, 4.5, 5.5, 6.6, 9.0, 11.0))
            x, y = rng.uniform(5 + dia, w - 5 - dia), rng.uniform(5 + dia, d - 5 - dia)
            hole = (x - dia / 2, y - dia / 2, x + dia / 2, y + dia / 2)
            if free(*hole) and all(math.dist((x, y), c) > 14 for c in ((0, 0), (w, 0), (w, d), (0, d))):
                p = cut_hole(p, (x * MM, y * MM, t * MM), "-z", [("bore", dia * MM, None)], f"h{k}")
                taken.append(hole)
                break
    return build(p)


POCKETS = [  # (x0, y0, length along X, width along Y, depth), mm: largest first
    (10.0, 10.0, 40.0, 35.0, 3.0),
    (61.0, 11.0, 36.0, 31.0, 4.0),
    (112.0, 12.0, 32.0, 27.0, 5.0),
    (13.0, 58.0, 28.0, 23.0, 6.0),
    (64.0, 59.0, 24.0, 19.0, 7.0),
    (115.0, 60.0, 21.0, 16.0, 8.0),
]


def pockets_plate():
    """A 160 x 100 x 18 mm plate with six rectangular pockets of falling size, each at its
    own offsets and depth (:data:`POCKETS`), and a 5 mm hole through each corner: more
    dimensions than a small budget keeps, so a key-dimensions drawing keeps the holes,
    the overall size and the larger pockets and leaves the smaller to the model."""
    W, D, T = 160 * MM, 100 * MM, 18 * MM
    p = box(W, D, T)
    for x0, y0, length, width, depth in POCKETS:
        p = cut(p, rect(x0 * MM, y0 * MM, (x0 + length) * MM, (y0 + width) * MM), depth * MM)
    for k, (x, y) in enumerate(((5.0, 5.0), (155.0, 5.0), (5.0, 95.0), (155.0, 95.0))):
        p = cut_hole(p, (x * MM, y * MM, T), "-z", [("bore", 5 * MM, None)], f"h{k}")
    return build(p)


def letters_plate():
    """A 60 x 40 x 10 mm plate with four small pockets cut 0.5 mm into its top in a row,
    as engraved letters are (a test gives their walls a font's free-form surfaces)."""
    p = box(60 * MM, 40 * MM, 10 * MM)
    for k in range(4):
        x0 = (15 + 8 * k) * MM
        p = cut(p, rect(x0, 15 * MM, x0 + 4 * MM, 25 * MM), 0.5 * MM)
    return build(p)


# Regeneration pairs (19.1): the same part before and after a change.


def pair_midplane(length_before=60 * MM, length_after=70 * MM):
    """A block extruded both ways from its mid-plane, lengthened."""
    a = box(length_before, 40 * MM, 20 * MM, (-length_before / 2, 0.0, 0.0))
    b = box(length_after, 40 * MM, 20 * MM, (-length_after / 2, 0.0, 0.0))
    return build(a), build(b)


def pair_origin_moved():
    p = cut_hole(
        box(80 * MM, 50 * MM, 10 * MM), (20 * MM, 25 * MM, 10 * MM), "-z", [("bore", 6 * MM, None)], "h"
    )
    return build(p), build(translate(p, 10 * MM, -5 * MM, 0.0))


def pair_pattern_grew():
    base = box(120 * MM, 40 * MM, 10 * MM)
    a, b = base, base
    for k in range(4):
        a = cut_hole(a, ((20 + 25 * k) * MM, 20 * MM, 10 * MM), "-z", [("bore", 5 * MM, None)], f"h{k}")
    for k in range(5):
        b = cut_hole(b, ((10 + 25 * k) * MM, 20 * MM, 10 * MM), "-z", [("bore", 5 * MM, None)], f"h{k}")
    return build(a), build(b)


def pair_datum_changes():
    """A plate whose largest face is the top (100 x 60), then a block whose largest face
    is a side (100 x 80 tall)."""
    return build(box(100 * MM, 60 * MM, 10 * MM)), build(box(100 * MM, 20 * MM, 80 * MM))


PARTS = {
    "hole_kinds": hole_kinds_plate,
    "patterns": patterns_plate,
    "four_holes": four_holes_plate,
    "link": link_plate,
    "boss": boss_block,
    "step_slot": step_slot_block,
    "angled_round": angled_round_block,
    "inclined_hole": inclined_hole_block,
    "groove": groove_plate,
    "sixteen_holes": sixteen_holes_plate,
    "printed_bracket": printed_bracket,
}
