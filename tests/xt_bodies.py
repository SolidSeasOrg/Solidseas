"""Synthetic Parasolid bodies for the tessellator's tests.

:class:`XtBuilder` writes nodes in the base-schema layouts (SCH_13006, as
``solidseas.formats.solidworks.xt_schema`` holds them) into an
:class:`~solidseas.formats.solidworks.parasolid.XtTransmit`, with the topology
XT uses: a BODY with one REGION and SHELL, FACEs chained by ``next``, each with
LOOPs of fins (HALFEDGEs) linked by ``forward`` and ``backward``, a fin's
``vertex`` its end vertex, and the two fins of an edge partners by ``other``.
The shapes below are closed solids whose volume and area are known exactly, and,
for the tessellator's and the STEP export's tests alike, bodies whose rounds are
rolling blends (BLENDED_EDGE).
"""

import math

from solidseas.formats.solidworks import xt_schema as S
from solidseas.formats.solidworks.parasolid import NULL_DOUBLE, Node, SchemaInfo, XtTransmit

BODY, SHELL, FACE, LOOP, EDGE, HALFEDGE, VERTEX, REGION, POINT = 12, 13, 14, 15, 16, 17, 18, 19, 29
LINE, CIRCLE, PLANE, CYLINDER, CONE, SPHERE, TORUS = 30, 31, 50, 51, 52, 53, 54
B_SURFACE, NURBS_SURF, BSPLINE_VERTICES, KNOT_MULT, KNOT_SET = 124, 126, 45, 127, 128
B_CURVE, NURBS_CURVE, TRIMMED_CURVE, SP_CURVE, INTERSECTION, CHART = 134, 136, 133, 137, 38, 40


def _default(kind: str, n: int):
    one = {"p": 0, "d": 0, "n": 0, "u": 0, "l": 0, "t": 0, "c": "+", "f": NULL_DOUBLE, "v": (0.0, 0.0, 0.0)}
    if n == S.VAR:
        return [] if kind != "c" else ""
    if n == 1:
        return one.get(kind, 0)
    return [one.get(kind, 0)] * n


class Edge:
    def __init__(self, idx: int, start, end) -> None:
        self.idx, self.start, self.end = idx, start, end
        self.fins: list[int] = []


class XtBuilder:
    def __init__(self) -> None:
        self.nodes: dict[int, list] = {}
        self.k = 1
        self.faces: list[int] = []

    # -- nodes
    def node(self, ntype: int, **fields) -> int:
        idx = self.k
        self.k += 1
        self.nodes[idx] = [ntype, dict(fields)]
        return idx

    def update(self, idx: int, **fields) -> None:
        self.nodes[idx][1].update(fields)

    def transmit(self) -> XtTransmit:
        xt = XtTransmit()
        xt.modeller = ": TRANSMIT FILE created by modeller version 3501251"
        xt.schema = "SCH_3501251_35102_13006"
        xt.base = 13006
        for idx, (ntype, fields) in self.nodes.items():
            lay = [tuple(f[:3]) for f in S.BASE[ntype]]
            xt.layouts.setdefault(ntype, lay)
            xt.schema_info.setdefault(ntype, SchemaInfo("base"))
            vals, count = [], None
            for name, kind, n in lay:
                v = fields[name] if name in fields else _default(kind, n)
                if n == S.VAR:
                    count = len(v)
                vals.append(v)
            xt.nodes.append(Node(ntype, idx, vals, count))
        xt.nodes.sort(key=lambda nd: nd.index)
        return xt

    # -- geometry
    def vertex(self, p) -> int:
        pt = self.node(POINT, pvec=tuple(map(float, p)))
        return self.node(VERTEX, point=pt)

    def plane(self, P, N, X, sense="+") -> int:
        return self.node(PLANE, pvec=_v(P), normal=_v(N), x_axis=_v(X), sense=sense)

    def cylinder(self, P, A, r, X, sense="+") -> int:
        return self.node(CYLINDER, pvec=_v(P), axis=_v(A), radius=float(r), x_axis=_v(X), sense=sense)

    def cone(self, P, A, r, half_angle, X, sense="+") -> int:
        return self.node(
            CONE,
            pvec=_v(P),
            axis=_v(A),
            radius=float(r),
            sin_half_angle=math.sin(half_angle),
            cos_half_angle=math.cos(half_angle),
            x_axis=_v(X),
            sense=sense,
        )

    def sphere(self, C, r, A, X, sense="+") -> int:
        return self.node(SPHERE, centre=_v(C), radius=float(r), axis=_v(A), x_axis=_v(X), sense=sense)

    def torus(self, C, A, R, r, X, sense="+") -> int:
        return self.node(
            TORUS,
            centre=_v(C),
            axis=_v(A),
            major_radius=float(R),
            minor_radius=float(r),
            x_axis=_v(X),
            sense=sense,
        )

    def line(self, P, D, sense="+") -> int:
        return self.node(LINE, pvec=_v(P), direction=_v(D), sense=sense)

    def circle(self, C, N, X, r, sense="+") -> int:
        return self.node(CIRCLE, centre=_v(C), normal=_v(N), x_axis=_v(X), radius=float(r), sense=sense)

    def nurbs_surface(
        self, rows, pu, pv, uknots, umult, vknots, vmult, *, rational=False, uclosed=False, sense="+"
    ):
        """A B_SURFACE: ``rows[i][j]`` control points (i along u), homogeneous when rational."""
        nu, nv = len(rows), len(rows[0])
        flat = [x for row in rows for c in row for x in c]
        verts = self.node(BSPLINE_VERTICES, vertices=[float(x) for x in flat])
        uk = self.node(KNOT_SET, knots=[float(k) for k in uknots])
        um = self.node(KNOT_MULT, mult=list(umult))
        vk = self.node(KNOT_SET, knots=[float(k) for k in vknots])
        vm = self.node(KNOT_MULT, mult=list(vmult))
        ns = self.node(
            NURBS_SURF,
            u_periodic=0,
            v_periodic=0,
            u_degree=pu,
            v_degree=pv,
            n_u_vertices=nu,
            n_v_vertices=nv,
            n_u_knots=len(uknots),
            n_v_knots=len(vknots),
            rational=1 if rational else 0,
            u_closed=1 if uclosed else 0,
            v_closed=0,
            vertex_dim=4 if rational else 3,
            bspline_vertices=verts,
            u_knot_mult=um,
            v_knot_mult=vm,
            u_knots=uk,
            v_knots=vk,
        )
        return self.node(B_SURFACE, nurbs=ns, sense=sense)

    # -- topology
    def edge(
        self, curve: int, start: int | None = None, end: int | None = None, tolerance=NULL_DOUBLE
    ) -> Edge:
        """An edge on ``curve`` from vertex ``start`` to ``end`` (both None: a ring)."""
        idx = self.node(EDGE, curve=curve, tolerance=tolerance)
        return Edge(idx, start, end)

    def face(self, surface: int, sense: str, loops) -> int:
        """A face; ``loops`` lists loops of ``(edge, fin sense)`` in order round the loop."""
        f = self.node(FACE, surface=surface, sense=sense)
        loop_ids = []
        for spec in loops:
            lp = self.node(LOOP, face=f)
            fins = []
            for e, s in spec:
                end = e.end if s == "+" else e.start
                fin = self.node(HALFEDGE, loop=lp, edge=e.idx, sense=s, vertex=end or 0)
                e.fins.append(fin)
                fins.append(fin)
            for a, b in zip(fins, fins[1:] + fins[:1], strict=True):
                self.update(a, forward=b)
                self.update(b, backward=a)
            self.update(lp, halfedge=fins[0])
            loop_ids.append(lp)
        for a, b in zip(loop_ids, loop_ids[1:], strict=False):
            self.update(a, next=b)
        if loop_ids:
            self.update(f, loop=loop_ids[0])
        self.faces.append(f)
        return f

    def body(self, edges, body_type: int = 1, shells=None) -> XtTransmit:
        """Close the body: partner fins, chain the faces into one shell (or into the
        ``shells`` given, lists of faces, all bounding the one region: the first the outer
        shell, the others cavities). The BODY gets index 1, as in a part transmit."""
        body = self.node(BODY, body_type=body_type)
        region = self.node(REGION, body=body, type="S")
        made = []
        for faces in shells or [self.faces]:
            shell = self.node(SHELL, body=body, region=region, face=faces[0])
            for a, b in zip(faces, faces[1:], strict=False):
                self.update(a, next=b)
            for f in faces:
                self.update(f, shell=shell)
            made.append(shell)
        for a, b in zip(made, made[1:], strict=False):
            self.update(a, next=b)
        self.update(body, region=region, shell=made[0])
        self.update(region, shell=made[0])
        for e in edges:
            self.update(e.idx, halfedge=e.fins[0])
            if len(e.fins) == 2:
                self.update(e.fins[0], other=e.fins[1])
                self.update(e.fins[1], other=e.fins[0])
        # renumber so that the BODY is node 1
        order = [body] + [i for i in self.nodes if i != body]
        remap = {old: new for new, old in enumerate(order, 1)}
        renamed = {}
        for old, (ntype, fields) in self.nodes.items():
            lay = S.BASE[ntype]
            out = {}
            for name, value in fields.items():
                kind = next(f[1] for f in lay if f[0] == name)
                out[name] = remap.get(value, value) if kind == "p" and isinstance(value, int) else value
            renamed[remap[old]] = [ntype, out]
        self.nodes = dict(sorted(renamed.items()))
        return self.transmit()


def _v(p):
    return tuple(float(x) for x in p)


# --------------------------------------------------------------------------- shapes
Z, X = (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)


def sphere(r: float = 0.01) -> XtTransmit:
    """A whole sphere: one face with no loop."""
    b = XtBuilder()
    b.face(b.sphere((0, 0, 0), r, Z, X), "+", [])
    return b.body([])


def torus(R: float = 0.01, r: float = 0.003) -> XtTransmit:
    """A whole torus: one face with no loop."""
    b = XtBuilder()
    b.face(b.torus((0, 0, 0), Z, R, r, X), "+", [])
    return b.body([])


def cylinder(r: float = 0.005, h: float = 0.02) -> XtTransmit:
    """A cylinder closed by two planes: two ring edges on circles, the side a band."""
    b = XtBuilder()
    bottom = b.edge(b.circle((0, 0, 0), Z, X, r))
    top = b.edge(b.circle((0, 0, h), Z, X, r))
    b.face(b.cylinder((0, 0, 0), Z, r, X), "+", [[(bottom, "+")], [(top, "-")]])
    b.face(b.plane((0, 0, 0), Z, X), "-", [[(bottom, "-")]])
    b.face(b.plane((0, 0, h), Z, X), "+", [[(top, "+")]])
    return b.body([bottom, top])


def hemisphere(r: float = 0.01) -> XtTransmit:
    """The upper half of a sphere on a disc: a cap to the pole and a plane, sharing a ring."""
    b = XtBuilder()
    rim = b.edge(b.circle((0, 0, 0), Z, X, r))
    b.face(b.sphere((0, 0, 0), r, Z, X), "+", [[(rim, "+")]])
    b.face(b.plane((0, 0, 0), Z, X), "-", [[(rim, "-")]])
    return b.body([rim])


def cone(r: float = 0.005, h: float = 0.01) -> XtTransmit:
    """A cone on a disc: the cone's face reaches its apex, a pole."""
    b = XtBuilder()
    rim = b.edge(b.circle((0, 0, 0), Z, X, r))
    half = math.atan2(r, h)
    # The cone's radius shrinks along +z: axis -z from the apex side, or a negative half
    # angle along +z; here the axis is +z with the half angle negative.
    b.face(b.cone((0, 0, 0), Z, r, -half, X), "+", [[(rim, "+")]])
    b.face(b.plane((0, 0, 0), Z, X), "-", [[(rim, "-")]])
    return b.body([rim])


def nurbs_cylinder(r: float = 0.005, h: float = 0.02) -> XtTransmit:
    """The cylinder of :func:`cylinder` with its side a rational B-spline surface: a
    nine-point circle of degree 2 in u (closed), straight in v."""
    w = math.sqrt(0.5)
    circle = [
        (1, 0, 1),
        (1, 1, w),
        (0, 1, 1),
        (-1, 1, w),
        (-1, 0, 1),
        (-1, -1, w),
        (0, -1, 1),
        (1, -1, w),
        (1, 0, 1),
    ]
    rows = []
    for x, y, wt in circle:
        rows.append([(x * r * wt, y * r * wt, 0.0, wt), (x * r * wt, y * r * wt, h * wt, wt)])
    b = XtBuilder()
    side = b.nurbs_surface(
        rows, 2, 1, [0, 1, 2, 3, 4], [3, 2, 2, 2, 3], [0, 1], [2, 2], rational=True, uclosed=True
    )
    bottom = b.edge(b.circle((0, 0, 0), Z, X, r))
    top = b.edge(b.circle((0, 0, h), Z, X, r))
    b.face(side, "+", [[(bottom, "+")], [(top, "-")]])
    b.face(b.plane((0, 0, 0), Z, X), "-", [[(bottom, "-")]])
    b.face(b.plane((0, 0, h), Z, X), "+", [[(top, "+")]])
    return b.body([bottom, top])


def nurbs_sphere(r: float = 0.01) -> XtTransmit:
    """A whole sphere as one rational B-spline face with no loop: u round the circle
    (closed), v the half meridian from the south pole to the north, so both boundary
    rows of control points collapse to a pole."""
    w = math.sqrt(0.5)
    circle = [(1, 0, 1), (1, 1, w), (0, 1, 1), (-1, 1, w), (-1, 0, 1)]
    circle += [(-1, -1, w), (0, -1, 1), (1, -1, w), (1, 0, 1)]
    meridian = [(0, -1, 1), (1, -1, w), (1, 0, 1), (1, 1, w), (0, 1, 1)]  # (radius, z, weight)
    rows = []
    for x, y, wu in circle:
        row = []
        for rho, z, wv in meridian:
            k = r * wu * wv
            row.append((x * rho * k, y * rho * k, z * k, wu * wv))
        rows.append(row)
    b = XtBuilder()
    side = b.nurbs_surface(
        rows, 2, 2, [0, 1, 2, 3, 4], [3, 2, 2, 2, 3], [0, 1, 2], [3, 2, 3], rational=True, uclosed=True
    )
    b.face(side, "+", [])
    return b.body([])


def torus_band(R: float, r: float, v0: float, v1: float) -> XtTransmit:
    """A sheet: the part of a torus between the minor angles ``v0 < v1``, bounded by two
    circles, its normal pointing away from the torus's centre circle."""
    b = XtBuilder()
    lo = b.edge(b.circle((0, 0, r * math.sin(v0)), Z, X, R + r * math.cos(v0)))
    hi = b.edge(b.circle((0, 0, r * math.sin(v1)), Z, X, R + r * math.cos(v1)))
    b.face(b.torus((0, 0, 0), Z, R, r, X), "+", [[(lo, "+")], [(hi, "-")]])
    return b.body([lo, hi], body_type=3)


def _turn(p, axis, angle: float):
    """``p`` turned by ``angle`` about the unit ``axis`` through the origin."""
    c, s = math.cos(angle), math.sin(angle)
    k = sum(a * q for a, q in zip(axis, p, strict=True))
    cr = (axis[1] * p[2] - axis[2] * p[1], axis[2] * p[0] - axis[0] * p[2], axis[0] * p[1] - axis[1] * p[0])
    return tuple(p[i] * c + cr[i] * s + axis[i] * k * (1 - c) for i in range(3))


def split_box(size=(0.03, 0.02, 0.01), splits: int = 5, axis=Z, angle: float = 0.0) -> XtTransmit:
    """A box turned by ``angle`` about ``axis``, every one of its twelve edges made of
    ``splits`` line edges end to end: each face's boundary has runs of points in a line,
    shared with the next face."""
    b = XtBuilder()
    W, D, H = size

    def corner(c):
        return _turn((W * c[0], D * c[1], H * c[2]), axis, angle)

    vertices: dict = {}
    chains: dict = {}
    edges: list = []

    def vertex(key, p):
        if key not in vertices:
            vertices[key] = b.vertex(p)
        return vertices[key]

    def chain(c0, c1):
        key = (c0, c1) if c0 < c1 else (c1, c0)
        if key not in chains:
            pa, pz = corner(key[0]), corner(key[1])
            pts = [tuple(pa[i] + (pz[i] - pa[i]) * t / splits for i in range(3)) for t in range(splits + 1)]
            vs = [vertex(key[0], pts[0])] + [vertex((key, t), pts[t]) for t in range(1, splits)]
            vs.append(vertex(key[1], pts[-1]))
            d = tuple(pz[i] - pa[i] for i in range(3))
            chains[key] = [b.edge(b.line(pts[t], d), vs[t], vs[t + 1]) for t in range(splits)]
            edges.extend(chains[key])
        es = chains[key]
        return [(e, "+") for e in es] if (c0, c1) == key else [(e, "-") for e in reversed(es)]

    for cs, normal, x_axis in _BOX_SIDES:
        loop = [fin for k in range(4) for fin in chain(cs[k], cs[(k + 1) % 4])]
        plane = b.plane(corner(cs[0]), _turn(normal, axis, angle), _turn(x_axis, axis, angle))
        b.face(plane, "+", [loop])
    return b.body(edges)


# --------------------------------------------------------------------------- built transmits
def field(xt: XtTransmit, node: Node, name: str):
    """A field of a node of a built transmit, by name."""
    return node.vals[xt.field_names(node.type).index(name)]


def set_field(xt: XtTransmit, node: Node, name: str, value) -> None:
    node.vals[xt.field_names(node.type).index(name)] = value


def add_node(xt: XtTransmit, ntype: int, **fields) -> Node:
    """A node added to a built transmit, after its last, in the base layout."""
    lay = [tuple(f[:3]) for f in S.BASE[ntype]]
    xt.layouts.setdefault(ntype, lay)
    xt.schema_info.setdefault(ntype, SchemaInfo("base"))
    idx = max(n.index for n in xt.nodes) + 1
    vals = [fields.get(name, _default(kind, n)) for name, kind, n in lay]
    node = Node(ntype, idx, vals, None)
    xt.nodes.append(node)
    xt._by_index = None
    return node


# --------------------------------------------------------------------------- rolling blends
def _sp_line(b: XtBuilder, surface: int, a, c, p1, p2) -> int:
    """A TRIMMED_CURVE over an SP_CURVE of ``surface``: the straight (u, v) segment from
    ``a`` to ``c``, trimmed from 0 to 1, its ends at the points ``p1`` and ``p2``."""
    verts = b.node(BSPLINE_VERTICES, vertices=[float(x) for x in (*a, *c)])
    knots = b.node(KNOT_SET, knots=[0.0, 1.0])
    mult = b.node(KNOT_MULT, mult=[2, 2])
    nc = b.node(
        NURBS_CURVE,
        degree=1,
        n_vertices=2,
        vertex_dim=2,
        n_knots=2,
        bspline_vertices=verts,
        knot_mult=mult,
        knots=knots,
    )
    sp = b.node(SP_CURVE, surface=surface, b_curve=b.node(B_CURVE, nurbs=nc, sense="+"), sense="+")
    return b.node(
        TRIMMED_CURVE, basis_curve=sp, sense="+", parm_1=0.0, parm_2=1.0, point_1=_v(p1), point_2=_v(p2)
    )


def filleted_box(W=0.03, D=0.02, H=0.01, r=0.002, *, tolerant=False):
    """A box with the edge at x = W, z = H rounded by a rolling blend of radius r
    between the top and the side: the blend's spine is the line at (W - r, y, H - r), its
    contact lines straight, its ends quarter circles.

    ``tolerant``: the edge where the blend meets the top is a tolerant edge with no curve
    of its own, each fin carrying a trimmed SP-curve in its own face, and the blend's fin
    is the edge's first (its (u, v), Parasolid's own of the blend, made up here)."""
    b = XtBuilder()
    P = {
        "A": (0, 0, 0),
        "B": (W, 0, 0),
        "C": (W, D, 0),
        "Dd": (0, D, 0),
        "E": (0, 0, H),
        "F": (0, D, H),
        "G": (W - r, 0, H),
        "Hh": (W - r, D, H),
        "I": (W, 0, H - r),
        "J": (W, D, H - r),
    }
    V = {k: b.vertex(p) for k, p in P.items()}
    edges = {}

    def line(a, c):
        key = frozenset((a, c))
        if key not in edges:
            d = tuple(P[c][i] - P[a][i] for i in range(3))
            edges[key] = (b.edge(b.line(P[a], d), V[a], V[c]), a)
        e, start = edges[key]
        return e, "+" if start == a else "-"

    def arc(a, c, centre):
        key = frozenset((a, c))
        if key not in edges:
            start, end = ("I", "G") if "I" in (a, c) else ("J", "Hh")
            edges[key] = (b.edge(b.circle(centre, (0, -1, 0), (1, 0, 0), r), V[start], V[end]), start)
        e, start = edges[key]
        return e, "+" if start == a else "-"

    front, back = (W - r, 0, H - r), (W - r, D, H - r)
    planes = {}

    def plane(name, p, n, x):
        planes[name] = b.plane(p, n, x)
        return planes[name]

    b.face(
        plane("bottom", (0, 0, 0), (0, 0, -1), (1, 0, 0)),
        "+",
        [[line("A", "Dd"), line("Dd", "C"), line("C", "B"), line("B", "A")]],
    )
    b.face(
        plane("top", (0, 0, H), (0, 0, 1), (1, 0, 0)),
        "+",
        [[line("E", "G"), line("G", "Hh"), line("Hh", "F"), line("F", "E")]],
    )
    b.face(
        plane("side", (W, 0, 0), (1, 0, 0), (0, 1, 0)),
        "+",
        [[line("B", "C"), line("C", "J"), line("J", "I"), line("I", "B")]],
    )
    b.face(
        plane("left", (0, 0, 0), (-1, 0, 0), (0, 1, 0)),
        "+",
        [[line("A", "E"), line("E", "F"), line("F", "Dd"), line("Dd", "A")]],
    )
    b.face(
        plane("front", (0, 0, 0), (0, -1, 0), (1, 0, 0)),
        "+",
        [[line("A", "B"), line("B", "I"), arc("I", "G", front), line("G", "E"), line("E", "A")]],
    )
    b.face(
        plane("back", (0, D, 0), (0, 1, 0), (1, 0, 0)),
        "+",
        [[line("Dd", "F"), line("F", "Hh"), arc("Hh", "J", back), line("J", "C"), line("C", "Dd")]],
    )
    spine = b.line(front, (0, 1, 0))
    blend = b.node(56, blend_type="R", spine=spine, range=[-r, -r], sense="+")
    b.face(blend, "+", [[line("Hh", "G"), arc("G", "I", front), line("I", "J"), arc("J", "Hh", back)]])
    if tolerant:
        e, _start = edges[frozenset(("G", "Hh"))]  # from G to Hh, the top's fin first
        b.update(e.idx, curve=0, tolerance=1e-8)
        top_fin, blend_fin = e.fins
        # the top plane is P + u X + v Y with X = (1, 0, 0) and Y = N x X = (0, 1, 0)
        b.update(top_fin, curve=_sp_line(b, planes["top"], (W - r, 0.0), (W - r, D), P["G"], P["Hh"]))
        b.update(blend_fin, curve=_sp_line(b, blend, (0.0, 0.0), (1.0, 0.0), P["Hh"], P["G"]))
        e.fins.reverse()
    xt = b.body([e for e, _s in edges.values()])
    # The blend's two supports, pointed at once the body has its final numbering.
    by_normal = {}
    for n in xt.nodes:
        if n.tname == "PLANE":
            by_normal[tuple(field(xt, n, "normal"))] = n.index
    blend_node = next(n for n in xt.nodes if n.type == 56)
    set_field(xt, blend_node, "surface", [by_normal[(0.0, 0.0, 1.0)], by_normal[(1.0, 0.0, 0.0)]])
    return xt


def blend_on(xt, spine: int, r: float, supports: tuple[str, str]):
    """Point the body's one BLENDED_EDGE at its two supports, found by type once the body
    has its final numbering: ``supports`` names "top" (the plane above z = 0) and
    "side" (the cylinder)."""
    nodes = {
        "top": next(n.index for n in xt.nodes if n.tname == "PLANE" and field(xt, n, "pvec")[2] > 0),
        "side": next(n.index for n in xt.nodes if n.tname == "CYLINDER"),
    }
    blend_node = next(n for n in xt.nodes if n.type == 56)
    set_field(xt, blend_node, "surface", [nodes[k] for k in supports])
    return xt


def rounded_cylinder(R=0.01, H=0.02, r=0.002, *, torus=False):
    """A cylinder whose top edge is rounded by a rolling blend of radius r round a circular
    spine: the blend face is a ring, bounded by two ring edges, and goes all the way round
    its spine (its true surface is the torus of radii R - r and r). ``torus``: that face
    lies on the TORUS itself instead."""
    b = XtBuilder()
    bottom = b.edge(b.circle((0, 0, 0), Z, X, R))
    side_top = b.edge(b.circle((0, 0, H - r), Z, X, R))
    top = b.edge(b.circle((0, 0, H), Z, X, R - r))
    b.face(b.cylinder((0, 0, 0), Z, R, X), "+", [[(bottom, "+")], [(side_top, "-")]])
    spine = b.circle((0, 0, H - r), Z, X, R - r)
    if torus:
        round_ = b.torus((0, 0, H - r), Z, R - r, r, X)
    else:
        round_ = b.node(56, blend_type="R", spine=spine, range=[-r, -r], sense="+")
    b.face(round_, "+", [[(side_top, "+")], [(top, "-")]])
    b.face(b.plane((0, 0, H), Z, X), "+", [[(top, "+")]])
    b.face(b.plane((0, 0, 0), Z, X), "-", [[(bottom, "-")]])
    xt = b.body([bottom, side_top, top])
    return xt if torus else blend_on(xt, spine, r, ("top", "side"))


def tilted_cylinder(R=0.01, H=0.02, r=0.002, degrees=50.0):
    """A cylinder cut at the top by a plane tilted by ``degrees``, the cut edge rounded by a
    rolling blend: its spine is an ellipse, and the angle of its section changes round
    it, so the loft's error peaks away from the middle of its spans. Returns the body and
    the spine (centre, major axis, minor axis, radii) in metres."""
    theta = math.radians(degrees)
    st, ct = math.sin(theta), math.cos(theta)
    n = (0.0, st, ct)  # the top plane's outward normal
    zc = H - r / ct  # the spine: the top plane moved r into the body, on the cylinder of radius R - r
    major = (0.0, ct, -st)
    b = XtBuilder()
    bottom = b.edge(b.circle((0, 0, 0), Z, X, R))
    spine = b.node(
        32, centre=(0.0, 0.0, zc), normal=n, x_axis=major, major_radius=(R - r) / ct, minor_radius=R - r
    )
    # where the sphere touches the cylinder: the spine moved out to radius R
    k = st / ct * (R - r) / R
    q = math.sqrt(1.0 + k * k)
    on_side = b.edge(
        b.node(
            32,
            centre=(0.0, 0.0, zc),
            normal=(0.0, k / q, 1.0 / q),
            x_axis=(0.0, 1.0 / q, -k / q),
            major_radius=R * q,
            minor_radius=R,
        )
    )
    # where it touches the top plane: the spine moved r along the plane's normal
    on_top = b.edge(
        b.node(
            32,
            centre=(0.0, r * st, zc + r * ct),
            normal=n,
            x_axis=major,
            major_radius=(R - r) / ct,
            minor_radius=R - r,
        )
    )
    b.face(b.cylinder((0, 0, 0), Z, R, X), "+", [[(bottom, "+")], [(on_side, "-")]])
    blend = b.node(56, blend_type="R", spine=spine, range=[-r, -r], sense="+")
    b.face(blend, "+", [[(on_side, "+")], [(on_top, "-")]])
    b.face(b.plane((0, 0, H), n, X), "+", [[(on_top, "+")]])
    b.face(b.plane((0, 0, 0), Z, X), "-", [[(bottom, "-")]])
    xt = blend_on(b.body([bottom, on_side, on_top]), spine, r, ("top", "side"))
    return xt, ((0.0, 0.0, zc), major, (1.0, 0.0, 0.0), (R - r) / ct, R - r)


# --------------------------------------------------------------------------- a box with a cavity
# A unit box's faces: corners counter-clockwise about the outward normal, the normal and
# the plane's x axis.
_BOX_SIDES = (
    (((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)), (0, 0, -1), (1, 0, 0)),
    (((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)), (0, 0, 1), (1, 0, 0)),
    (((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)), (0, -1, 0), (1, 0, 0)),
    (((0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)), (0, 1, 0), (1, 0, 0)),
    (((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)), (-1, 0, 0), (0, 1, 0)),
    (((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)), (1, 0, 0), (0, 1, 0)),
)


def holed_plate(n: int = 2, pitch: float = 0.004, r: float = 0.001, h: float = 0.002) -> XtTransmit:
    """A square plate with ``n`` x ``n`` round holes through it, ``pitch`` apart, each hole's
    wall a band between two ring edges, as Parasolid holds a hole: every wall goes round its
    cylinder, so the STEP export cuts each in two at its seams, and each cut splits rings of
    the plate's top and bottom faces, which hold every hole."""
    b = XtBuilder()
    W = n * pitch
    size = (W, W, h)
    corners: dict = {}
    sides: dict = {}
    edges: list = []

    def point(c):
        return tuple(size[i] * c[i] for i in range(3))

    def side(c0, c1):
        key = (c0, c1) if c0 < c1 else (c1, c0)
        if key not in sides:
            for c in key:
                if c not in corners:
                    corners[c] = b.vertex(point(c))
            pa, pb = point(key[0]), point(key[1])
            d = tuple(pb[i] - pa[i] for i in range(3))
            sides[key] = b.edge(b.line(pa, d), corners[key[0]], corners[key[1]])
            edges.append(sides[key])
        return sides[key], "+" if (c0, c1) == key else "-"

    holes = []
    for i in range(n):
        for j in range(n):
            x, y = (i + 0.5) * pitch, (j + 0.5) * pitch
            low = b.edge(b.circle((x, y, 0.0), Z, X, r))
            high = b.edge(b.circle((x, y, h), Z, X, r))
            holes.append((x, y, low, high))
            edges += [low, high]
    for k, (cs, normal, x_axis) in enumerate(_BOX_SIDES):
        loops = [[side(cs[m], cs[(m + 1) % 4]) for m in range(4)]]
        if k == 0:  # the bottom, facing -z: its holes run counter-clockwise about +z
            loops += [[(low, "+")] for _x, _y, low, _high in holes]
        elif k == 1:  # the top, facing +z: clockwise about it
            loops += [[(high, "-")] for _x, _y, _low, high in holes]
        b.face(b.plane(point(cs[0]), normal, x_axis), "+", loops)
    for x, y, low, high in holes:  # each wall facing into its hole
        b.face(b.cylinder((x, y, 0.0), Z, r, X), "-", [[(low, "-")], [(high, "+")]])
    return b.body(edges)


def void_box(size: float = 0.03, void=(0.01, 0.02)) -> XtTransmit:
    """A cube of side ``size`` with a cubic cavity from ``void[0]`` to ``void[1]`` on every
    axis, as Parasolid holds one: a solid region bounded by two shells, the outer one's
    faces looking out of the cube and the cavity's looking into the cavity (out of the
    material, so each face's sense is ``-`` on the plane whose normal leaves the cavity, and
    its loop runs the other way round). 27,000 less 1,000 cubic millimetres by default."""
    b = XtBuilder()
    edges: list = []

    def box(lo: float, hi: float, cavity: bool) -> list[int]:
        vertices: dict = {}
        made: dict = {}

        def point(c):
            return tuple(lo + (hi - lo) * x for x in c)

        def vertex(c):
            if c not in vertices:
                vertices[c] = b.vertex(point(c))
            return vertices[c]

        def fin(c0, c1):
            key = (c0, c1) if c0 < c1 else (c1, c0)
            if key not in made:
                pa, pz = point(key[0]), point(key[1])
                d = tuple(pz[i] - pa[i] for i in range(3))
                n = sum(x * x for x in d) ** 0.5
                made[key] = b.edge(b.line(pa, tuple(x / n for x in d)), vertex(key[0]), vertex(key[1]))
                edges.append(made[key])
            return made[key], "+" if (c0, c1) == key else "-"

        faces = []
        for cs, normal, x_axis in _BOX_SIDES:
            order = list(reversed(cs)) if cavity else list(cs)
            loop = [fin(order[k], order[(k + 1) % 4]) for k in range(4)]
            faces.append(b.face(b.plane(point(cs[0]), normal, x_axis), "-" if cavity else "+", [loop]))
        return faces

    outer = box(0.0, size, False)
    inner = box(void[0], void[1], True)
    return b.body(edges, shells=[outer, inner])
