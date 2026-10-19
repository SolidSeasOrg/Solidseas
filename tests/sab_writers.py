"""Synthetic ACIS SAB streams for the Alibre Design and ACIS tests, written by code.

Written from the layouts in ``docs/formats/alibre.md`` (SAB version 2100): every
value tagged, every topology and geometry record starting with an attribute
pointer, two integers and a pointer. A :class:`Solid` collects vertices, edges on
curves and faces on surfaces (loops of edges with a sense each); :meth:`Solid.sab`
writes body, lump, shell, faces, loops, coedges with partners, edges, vertices,
points, surfaces, curves and attributes, then ``End-of-ACIS-data``. Product,
version and date strings are the test's own. Every shape below is closed and its
volume and area are known.
"""

import math
import struct
from dataclasses import dataclass, field

INT, DBL, STR, TRUE, FALSE, PTR, IDENT, IDENT_X, SUB, SUB_END, END, POS, VEC, ENUM = (
    0x04,
    0x06,
    0x07,
    0x0A,
    0x0B,
    0x0C,
    0x0D,
    0x0E,
    0x0F,
    0x10,
    0x11,
    0x13,
    0x14,
    0x15,
)


def i(v: int):
    return (INT, v)


def d(v: float):
    return (DBL, v)


def e(v: int):
    return (ENUM, v)


def b(v: bool):
    return (TRUE if v else FALSE, None)


def kw(s: str):
    return (IDENT, s)


def s7(s: str):
    return (STR, s)


def pos(p):
    return (POS, tuple(float(x) for x in p))


def vec(p):
    return (VEC, tuple(float(x) for x in p))


class Ref:
    """A pointer to an object, resolved to a record index when the stream is written."""

    def __init__(self, obj) -> None:
        self.obj = obj


def ptr(obj):
    return (PTR, obj if isinstance(obj, int) else Ref(obj))


NULL = (PTR, -1)
OPEN = (SUB, None)
CLOSE = (SUB_END, None)


def encode(name: str, values) -> bytes:
    """One record: its type name (prefixes 0x0E, the last part 0x0D), values, 0x11."""
    out = bytearray()
    parts = name.split("-")
    for k, p in enumerate(parts):
        raw = p.encode("latin-1")
        out += bytes((IDENT if k == len(parts) - 1 else IDENT_X, len(raw))) + raw
    for tag, v in values:
        out.append(tag)
        if tag in (INT, PTR, ENUM):
            out += struct.pack("<i", v)
        elif tag == DBL:
            out += struct.pack("<d", v)
        elif tag in (POS, VEC):
            out += struct.pack("<3d", *v)
        elif tag in (STR, IDENT, IDENT_X):
            raw = v.encode("latin-1")
            out += bytes((len(raw),)) + raw
    out.append(END)
    return bytes(out)


def header(mm_per_unit: float = 10.0, version: int = 2100, signature: bytes = b"ACIS BinaryFile") -> bytes:
    out = bytearray(signature) + struct.pack("<4i", version, 0, 1, 0)
    for text in ("SolidSeas tests", "ACIS test writer", "Thu Jan 01 00:00:00 2026"):
        raw = text.encode()
        out += bytes((STR, len(raw))) + raw
    for x in (mm_per_unit, 1e-6, 1e-10):
        out += bytes((DBL,)) + struct.pack("<d", x)
    return bytes(out)


END_MARKER = bytes((IDENT, 16)) + b"End-of-ACIS-data"


def stream(records: list[tuple[str, list]], **header_args) -> bytes:
    """A whole SAB stream of ``records`` (pointers already indices)."""
    return header(**header_args) + b"".join(encode(n, v) for n, v in records) + END_MARKER


# --------------------------------------------------------------------------- geometry specs
def prefix(attrib=NULL):
    return [attrib, i(-1), i(-1), NULL]


def plane(root, normal, u_dir):
    return (
        "plane-surface",
        [pos(root), vec(normal), vec(u_dir), b(False), b(False), b(False), b(False), b(False)],
    )


def cone(centre, axis, major, ratio=1.0, sine=0.0, cosine=1.0, reverse_u=False):
    return (
        "cone-surface",
        [
            pos(centre),
            vec(axis),
            vec(major),
            d(ratio),
            b(False),
            b(False),
            d(sine),
            d(cosine),
            d(math.hypot(*major)),
        ]
        + [b(reverse_u), b(False), b(False), b(False), b(False)],
    )


def sphere(centre, radius, u_dir=(1, 0, 0), pole=(0, 0, 1)):
    return ("sphere-surface", [pos(centre), d(radius), vec(u_dir), vec(pole)] + [b(False)] * 5)


def torus(centre, axis, major, minor, u_dir=(1, 0, 0)):
    return ("torus-surface", [pos(centre), vec(axis), d(major), d(minor), vec(u_dir)] + [b(False)] * 5)


def bs3_surface(du, dv, knots_u, knots_v, points, weights=None, closure=(0, 0)):
    """The values of an ``exactsur`` block's B-spline (``points`` with u varying fastest)."""
    out = [kw("nurbs" if weights is not None else "nubs"), i(du), i(dv)]
    if weights is not None:
        out.append(kw("both"))
    out += [e(closure[0]), e(closure[1]), e(0), e(0), i(len(knots_u)), i(len(knots_v))]
    for k, m in knots_u:
        out += [d(k), i(m)]
    for k, m in knots_v:
        out += [d(k), i(m)]
    for n, p in enumerate(points):
        out += [d(p[0]), d(p[1]), d(p[2])]
        if weights is not None:
            out.append(d(weights[n]))
    out.append(d(1e-6))  # the fit tolerance
    return out


def spline(block, reversed_=False):
    """A ``spline-surface`` holding an ``exactsur`` definition (``block`` from :func:`bs3_surface`)."""
    return ("spline-surface", [b(reversed_), OPEN, kw("exactsur"), e(0), *block, CLOSE] + [b(False)] * 4)


def spline_ref(n: int, reversed_=False):
    """A ``spline-surface`` naming subtype definition ``n``."""
    return ("spline-surface", [b(reversed_), OPEN, kw("ref"), i(n), CLOSE] + [b(False)] * 4)


def straight(root, direction):
    return ("straight-curve", [pos(root), vec(direction), b(False), b(False)])


def ellipse(centre, normal, major, ratio=1.0):
    return ("ellipse-curve", [pos(centre), vec(normal), vec(major), d(ratio), b(False), b(False)])


def intcurve(degree, knots, points, weights=None, closure=0, reversed_=False):
    """An ``intcurve-curve`` with an ``exactcur`` B-spline."""
    blk = [kw("nurbs" if weights is not None else "nubs"), i(degree), e(closure), i(len(knots))]
    for k, m in knots:
        blk += [d(k), i(m)]
    for n, p in enumerate(points):
        blk += [d(p[0]), d(p[1]), d(p[2])]
        if weights is not None:
            blk.append(d(weights[n]))
    blk.append(d(1e-6))
    return ("intcurve-curve", [b(reversed_), OPEN, kw("exactcur"), e(0), *blk, CLOSE, b(False), b(False)])


# --------------------------------------------------------------------------- topology
@dataclass(eq=False)
class Vx:
    p: tuple


@dataclass(eq=False)
class Ed:
    curve: tuple
    start: Vx | None
    end: Vx | None
    sp: float = 0.0
    ep: float = 1.0
    reversed: bool = False
    coedges: list = field(default_factory=list)
    pid: int | None = None


@dataclass(eq=False)
class Fc:
    surface: tuple
    loops: list  # [[(Ed, coedge reversed)]]
    reversed: bool = False
    pid: int | None = None


class Solid:
    """A body under construction (see the module notes)."""

    def __init__(self) -> None:
        self.faces: list[Fc] = []
        self.color: tuple | None = None
        self.transform: tuple | None = None

    @staticmethod
    def vertex(p) -> Vx:
        return Vx(tuple(float(x) for x in p))

    @staticmethod
    def edge(curve, start, end, sp=0.0, ep=1.0, reversed_=False) -> Ed:
        return Ed(curve, start, end, sp, ep, reversed_)

    @staticmethod
    def line(a: Vx, z: Vx) -> Ed:
        dvec = tuple(z.p[k] - a.p[k] for k in range(3))
        n = math.sqrt(sum(x * x for x in dvec))
        return Ed(straight(a.p, tuple(x / n for x in dvec)), a, z, 0.0, n)

    def face(self, surface, loops, reversed_=False) -> Fc:
        f = Fc(surface, loops, reversed_)
        self.faces.append(f)
        return f

    def records(self, *, persistent_ids: bool = False) -> list[tuple[str, list]]:
        """The records, pointers resolved to indices."""
        recs: list[list] = []
        index: dict = {}

        def key(obj):
            return obj if isinstance(obj, tuple) else ("obj", id(obj))

        def add(obj, name, values) -> int:
            recs.append([name, values])
            if obj is not None:
                index[key(obj)] = len(recs) - 1
            return len(recs) - 1

        body, lump, shell = object(), object(), object()
        edges: list[Ed] = []
        vertices: list[Vx] = []
        for f in self.faces:
            for loop in f.loops:
                for ed, _rev in loop:
                    if ed not in edges:
                        edges.append(ed)
                        ed.coedges = []
                    for v in (ed.start, ed.end):
                        if v is not None and v not in vertices:
                            vertices.append(v)
        transform = object() if self.transform is not None else None
        add(body, "body", prefix() + [ptr(lump), NULL, ptr(transform) if transform else NULL, b(False)])
        add(lump, "lump", prefix() + [NULL, ptr(shell), ptr(body), b(False)])
        add(shell, "shell", prefix() + [NULL, NULL, ptr(self.faces[0]), NULL, ptr(lump), b(False)])
        loops: list[tuple[object, Fc, list]] = []
        coedges: list[tuple[object, Ed, bool, object]] = []
        for k, f in enumerate(self.faces):
            nxt = self.faces[k + 1] if k + 1 < len(self.faces) else None
            lps = [object() for _ in f.loops]
            add(
                f,
                "face",
                prefix()
                + [
                    ptr(nxt) if nxt else NULL,
                    ptr(lps[0]) if lps else NULL,
                    ptr(shell),
                    NULL,
                    ptr(("surf", id(f))),
                ]
                + [b(f.reversed), b(False), b(True), pos((0, 0, 0)), pos((0, 0, 0)), b(False)],
            )
            for j, (lp, loop) in enumerate(zip(lps, f.loops, strict=True)):
                ces = [object() for _ in loop]
                loops.append((lp, f, ces))
                for ce, (ed, rev) in zip(ces, loop, strict=True):
                    coedges.append((ce, ed, rev, lp))
                    ed.coedges.append(ce)
                lp_next = lps[j + 1] if j + 1 < len(lps) else None
                add(
                    lp,
                    "loop",
                    prefix()
                    + [
                        ptr(lp_next) if lp_next else NULL,
                        ptr(ces[0]),
                        ptr(f),
                        b(True),
                        pos((0, 0, 0)),
                        pos((0, 0, 0)),
                    ]
                    + [e(0)],
                )
        ring_of = {id(ce): ces for _lp, _f, ces in loops for ce in ces}
        for ce, ed, rev, lp in coedges:
            ring = ring_of[id(ce)]
            k = ring.index(ce)
            partners = [c for c in ed.coedges if c is not ce]
            partner = partners[0] if partners else None
            add(
                ce,
                "coedge",
                prefix()
                + [
                    ptr(ring[(k + 1) % len(ring)]),
                    ptr(ring[k - 1]),
                    ptr(partner) if partner else NULL,
                    ptr(ed),
                ]
                + [b(rev), ptr(lp), NULL],
            )
        for ed in edges:
            add(
                ed,
                "edge",
                prefix()
                + [ptr(ed.start) if ed.start else NULL, d(ed.sp), ptr(ed.end) if ed.end else NULL, d(ed.ep)]
                + [
                    ptr(ed.coedges[0]),
                    ptr(("curve", id(ed))) if ed.curve else NULL,
                    b(ed.reversed),
                    s7("unknown"),
                ]
                + [b(True), pos((0, 0, 0)), pos((0, 0, 0))],
            )
        for v in vertices:
            first = next(ed for ed in edges if ed.start is v or ed.end is v)
            add(v, "vertex", prefix() + [ptr(first), ptr(("point", id(v)))])
        for v in vertices:
            add(("point", id(v)), "point", prefix() + [pos(v.p)])
        for f in self.faces:
            name, vals = f.surface
            add(("surf", id(f)), name, prefix() + list(vals))
        for ed in edges:
            if ed.curve:
                name, vals = ed.curve
                add(("curve", id(ed)), name, prefix() + list(vals))
        if transform is not None:
            rows, t, scale = self.transform
            add(
                transform,
                "transform",
                [
                    NULL,
                    i(-1),
                    vec(rows[0]),
                    vec(rows[1]),
                    vec(rows[2]),
                    vec(t),
                    d(scale),
                    b(True),
                    b(False),
                    b(False),
                ],
            )
        if self.color is not None:
            r, g, bl = self.color
            add(None, "rgb_color-st-attrib", [NULL, i(-1), NULL, NULL, ptr(lump), i(0), d(r), d(g), d(bl)])
        if persistent_ids:
            for f in self.faces:
                if f.pid is not None:
                    add(None, "PersistentID-Alibre-attrib", [NULL, i(-1), NULL, NULL, ptr(f), i(0), i(f.pid)])
            for ed in edges:
                if ed.pid is not None:
                    add(
                        None,
                        "PersistentID-Alibre-attrib",
                        [NULL, i(-1), NULL, NULL, ptr(ed), i(0), i(ed.pid)],
                    )
        out = []
        for name, vals in recs:
            res = []
            for tag, v in vals:
                if tag == PTR and isinstance(v, Ref):
                    res.append((PTR, index[key(v.obj)]))
                else:
                    res.append((tag, v))
            out.append((name, res))
        return out

    def sab(self, *, persistent_ids: bool = False, **header_args) -> bytes:
        return stream(self.records(persistent_ids=persistent_ids), **header_args)


# --------------------------------------------------------------------------- shapes
# Corners of a unit box, counter-clockwise seen from outside each face, with the face's
# outward normal (the order tests/xt_bodies.split_box uses).
BOX_FACES = (
    (((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)), (0, 0, -1)),
    (((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)), (0, 0, 1)),
    (((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)), (0, -1, 0)),
    (((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)), (0, 1, 0)),
    (((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)), (-1, 0, 0)),
    (((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)), (1, 0, 0)),
)


def _polygon_faces(sol: Solid, polygons, corner) -> list[Ed]:
    """Faces on planes through ``polygons`` (corner keys counter-clockwise from outside,
    with the outward normal); edges shared between faces. ``corner(key)`` is a point."""
    vertices: dict = {}
    edges: dict = {}

    def vx(k):
        if k not in vertices:
            vertices[k] = sol.vertex(corner(k))
        return vertices[k]

    out = []
    for keys, normal, *rest in polygons:
        reversed_face = bool(rest and rest[0])
        loop = []
        for k in range(len(keys)):
            a, z = keys[k], keys[(k + 1) % len(keys)]
            lo, hi = (a, z) if a < z else (z, a)
            if (lo, hi) not in edges:
                edges[(lo, hi)] = sol.line(vx(lo), vx(hi))
                out.append(edges[(lo, hi)])
            loop.append((edges[(lo, hi)], a != lo))
        p0 = corner(keys[0])
        p1 = corner(keys[1])
        u_dir = tuple(p1[j] - p0[j] for j in range(3))
        n = tuple(-x for x in normal) if reversed_face else normal
        sol.face(plane(p0, n, u_dir), [loop], reversed_face)
    return out


def cube(size: float = 1.0, *, reversed_face: bool = True, color=None) -> Solid:
    """A cube of side ``size`` (model units) at the origin. With ``reversed_face`` the top
    face's plane normal points into the cube and the face is reversed, as ACIS allows."""
    sol = Solid()
    polys = [(keys, normal, reversed_face and normal == (0, 0, 1)) for keys, normal in BOX_FACES]
    edges = _polygon_faces(sol, polys, lambda k: tuple(size * c for c in k))
    for n, f in enumerate(sol.faces, 1):
        f.pid = n
    for n, ed in enumerate(edges, len(sol.faces) + 1):
        ed.pid = n
    sol.color = color
    return sol


def split_box(w: float = 2.0, dpt: float = 1.0, h: float = 1.0) -> Solid:
    """A box whose top is two faces on one bilinear spline surface: the first face holds
    the ``exactsur`` definition, the second names it with ``ref 0``."""
    sol = Solid()
    mid = 0.5

    def corner(k):
        return (w * k[0], dpt * k[1], h * k[2])

    polys = [
        (((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)), (0, 0, -1)),
        (((0, 0, 0), (1, 0, 0), (1, 0, 1), (mid, 0, 1), (0, 0, 1)), (0, -1, 0)),
        (((0, 1, 0), (0, 1, 1), (mid, 1, 1), (1, 1, 1), (1, 1, 0)), (0, 1, 0)),
        (((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)), (-1, 0, 0)),
        (((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)), (1, 0, 0)),
        (((0, 0, 1), (mid, 0, 1), (mid, 1, 1), (0, 1, 1)), (0, 0, 1)),
        (((mid, 0, 1), (1, 0, 1), (1, 1, 1), (mid, 1, 1)), (0, 0, 1)),
    ]
    _polygon_faces(sol, polys, corner)
    patch = bs3_surface(
        1, 1, [(0.0, 1), (1.0, 1)], [(0.0, 1), (1.0, 1)], [(0, 0, h), (w, 0, h), (0, dpt, h), (w, dpt, h)]
    )
    sol.faces[5].surface = spline(patch)
    sol.faces[6].surface = spline_ref(0)
    return sol


def _ring(sol: Solid, z: float, r: float) -> Ed:
    v = sol.vertex((r, 0.0, z))
    return sol.edge(ellipse((0, 0, z), (0, 0, 1), (r, 0, 0)), v, v, 0.0, 2 * math.pi)


def cylinder(r: float = 1.0, h: float = 2.0, *, inward: bool = False) -> Solid:
    """A cylinder about z from 0 to ``h``: a cone surface of sine 0 with two ring edges
    on circles, and two planar caps. With ``inward`` the surface's cosine is -1 (its
    normal points to the axis) and the face is reversed: the same solid."""
    sol = Solid()
    bottom, top = _ring(sol, 0.0, r), _ring(sol, h, r)
    side = cone((0, 0, 0), (0, 0, 1), (r, 0, 0), sine=0.0, cosine=-1.0 if inward else 1.0)
    sol.face(side, [[(bottom, False)], [(top, True)]], reversed_=inward)
    sol.face(plane((0, 0, 0), (0, 0, -1), (1, 0, 0)), [[(bottom, True)]])
    sol.face(plane((0, 0, h), (0, 0, 1), (1, 0, 0)), [[(top, False)]])
    return sol


def frustum(r0: float = 2.0, r1: float = 1.0, h: float = 2.0) -> Solid:
    """A cone frustum about z: radius ``r0`` at 0, ``r1`` at ``h``."""
    sol = Solid()
    bottom, top = _ring(sol, 0.0, r0), _ring(sol, h, r1)
    a = math.atan2(r1 - r0, h)
    sol.face(
        cone((0, 0, 0), (0, 0, 1), (r0, 0, 0), sine=math.sin(a), cosine=math.cos(a)),
        [[(bottom, False)], [(top, True)]],
    )
    sol.face(plane((0, 0, 0), (0, 0, -1), (1, 0, 0)), [[(bottom, True)]])
    sol.face(plane((0, 0, h), (0, 0, 1), (1, 0, 0)), [[(top, False)]])
    return sol


def whole_sphere(r: float = 1.0, *, inside_out: bool = False) -> Solid:
    """A whole sphere: one face with no loop. With ``inside_out`` the radius is negative
    and the face reversed: the same solid."""
    sol = Solid()
    sol.face(sphere((0, 0, 0), -r if inside_out else r), [], reversed_=inside_out)
    return sol


def half_sphere(r: float = 1.0, pole=(0, 0, 1)) -> Solid:
    """Half a solid sphere, on the side y >= 0: a sphere face bounded by one ring edge
    on the great circle in the plane y = 0 (its vertex at (0, 0, r)), and the flat
    face. With the default pole the ring runs through both of the sphere's poles, as a
    solid sphere cut by a plane through its axis does."""
    sol = Solid()
    top = sol.vertex((0, 0, r))
    ring = sol.edge(ellipse((0, 0, 0), (0, 1, 0), (0, 0, r)), top, top, 0.0, 2 * math.pi)
    sol.face(sphere((0, 0, 0), r, (1, 0, 0), pole), [[(ring, False)]])
    sol.face(plane((0, 0, 0), (0, -1, 0), (1, 0, 0)), [[(ring, True)]])
    return sol


def ring_torus(major: float = 2.0, minor: float = 0.5) -> Solid:
    """A whole torus: one face with no loop."""
    sol = Solid()
    sol.face(torus((0, 0, 0), (0, 0, 1), major, minor), [])
    return sol


W2 = math.sqrt(0.5)
CIRCLE9 = [
    (1, 0, 1),
    (1, 1, W2),
    (0, 1, 1),
    (-1, 1, W2),
    (-1, 0, 1),
    (-1, -1, W2),
    (0, -1, 1),
    (1, -1, W2),
    (1, 0, 1),
]
CIRCLE_KNOTS = [
    (0.0, 2),
    (1.0, 2),
    (2.0, 2),
    (3.0, 2),
    (4.0, 2),
]  # end multiplicity = degree, as ACIS stores them


def rational_cylinder(r: float = 1.0, h: float = 2.0) -> Solid:
    """The cylinder with its side a rational quadratic B-spline (``nurbs``, u round the
    circle, v up) and its bottom edge an intcurve on the same circle."""
    sol = Solid()
    vb = sol.vertex((r, 0.0, 0.0))
    pts = [(x * r, y * r, 0.0) for x, y, _w in CIRCLE9]
    weights = [w for _x, _y, w in CIRCLE9]
    bottom = sol.edge(intcurve(2, CIRCLE_KNOTS, pts, weights, closure=1), vb, vb, 0.0, 4.0)
    top = _ring(sol, h, r)
    side_pts = [(x * r, y * r, z) for z in (0.0, h) for x, y, _w in CIRCLE9]
    side_w = weights + weights
    side = spline(bs3_surface(2, 1, CIRCLE_KNOTS, [(0.0, 1), (1.0, 1)], side_pts, side_w, closure=(1, 0)))
    sol.face(side, [[(bottom, False)], [(top, True)]])
    sol.face(plane((0, 0, 0), (0, 0, -1), (1, 0, 0)), [[(bottom, True)]])
    sol.face(plane((0, 0, h), (0, 0, 1), (1, 0, 0)), [[(top, False)]])
    return sol


def elliptic_cylinder(a: float = 2.0, b_: float = 1.0, h: float = 1.0) -> Solid:
    """A cylinder of elliptic section (a cone surface of sine 0 and ratio b/a)."""
    sol = Solid()
    v0, v1 = sol.vertex((a, 0, 0)), sol.vertex((a, 0, h))
    bottom = sol.edge(ellipse((0, 0, 0), (0, 0, 1), (a, 0, 0), b_ / a), v0, v0, 0.0, 2 * math.pi)
    top = sol.edge(ellipse((0, 0, h), (0, 0, 1), (a, 0, 0), b_ / a), v1, v1, 0.0, 2 * math.pi)
    sol.face(cone((0, 0, 0), (0, 0, 1), (a, 0, 0), ratio=b_ / a), [[(bottom, False)], [(top, True)]])
    sol.face(plane((0, 0, 0), (0, 0, -1), (1, 0, 0)), [[(bottom, True)]])
    sol.face(plane((0, 0, h), (0, 0, 1), (1, 0, 0)), [[(top, False)]])
    return sol


def cone_point(r: float = 1.0, h: float = 2.0) -> Solid:
    """A cone on a disc reaching its apex: the cone face's second loop is one degenerate
    edge at the apex (no curve, one vertex), as ACIS writes one."""
    sol = Solid()
    bottom = _ring(sol, 0.0, r)
    apex = sol.vertex((0.0, 0.0, h))
    degenerate = sol.edge(None, apex, apex, 0.0, 0.0)
    a = math.atan2(-r, h)
    side = cone((0, 0, 0), (0, 0, 1), (r, 0, 0), sine=math.sin(a), cosine=math.cos(a))
    sol.face(side, [[(bottom, False)], [(degenerate, False)]])
    sol.face(plane((0, 0, 0), (0, 0, -1), (1, 0, 0)), [[(bottom, True)]])
    return sol


def elliptic_cone(a: float = 2.0, b_: float = 1.0, h: float = 1.0) -> Solid:
    """An elliptic frustum's side, which SolidSeas does not map: its face is left out."""
    sol = elliptic_cylinder(a, b_, h)
    t = math.atan2(-0.5, h)
    side = cone((0, 0, 0), (0, 0, 1), (a, 0, 0), ratio=b_ / a, sine=math.sin(t), cosine=math.cos(t))
    sol.faces[0].surface = side
    return sol


def records_of(sol: Solid, **kw) -> list[list]:
    """The records of ``sol`` as mutable ``[name, values]`` pairs, for damaging them."""
    return [[n, list(v)] for n, v in sol.records(**kw)]


def find(recs: list[list], name: str, k: int = 0) -> int:
    """The index of the ``k``-th record named ``name``."""
    return [j for j, r in enumerate(recs) if r[0] == name][k]
