"""A read-only view of the B-rep in a parsed transmit, for the tessellator.

Fields are read by name through the transmit's own schema, never by position,
since later schemas add fields to BODY, REGION, INTERSECTION and LIMIT
(``docs/FORMAT.md`` 10.8). Every pointer followed is checked to lead to a node
of the type expected, and every walk keeps a visited set and stops after as
many steps as the transmit has nodes, so a damaged or crafted file ends in a
:class:`FaceFailed` with a reason, never in a loop.
"""

import math
import time

from ..formats.solidworks.parasolid import NULL_DOUBLE, Node, XtTransmit

# Node type codes (the XT Format Reference's, as in xt_schema.NODE_NAMES).
BODY, SHELL, FACE, LOOP, EDGE, HALFEDGE, VERTEX, REGION, POINT = 12, 13, 14, 15, 16, 17, 18, 19, 29
LINE, CIRCLE, ELLIPSE, INTERSECTION, CHART, LIMIT = 30, 31, 32, 38, 40, 41
BSPLINE_VERTICES = 45
PLANE, CYLINDER, CONE, SPHERE, TORUS = 50, 51, 52, 53, 54
BLENDED_EDGE, BLEND_BOUND, OFFSET_SURF, SWEPT_SURF, SPUN_SURF = 56, 59, 60, 67, 68
B_SURFACE, NURBS_SURF, KNOT_MULT, KNOT_SET = 124, 126, 127, 128
TRIMMED_CURVE, B_CURVE, NURBS_CURVE, SP_CURVE = 133, 134, 136, 137

SURFACE_TYPES = frozenset(
    (PLANE, CYLINDER, CONE, SPHERE, TORUS, BLENDED_EDGE, OFFSET_SURF, SWEPT_SURF, SPUN_SURF, B_SURFACE, 120)
)
CURVE_TYPES = frozenset(
    (LINE, CIRCLE, ELLIPSE, INTERSECTION, BLEND_BOUND, TRIMMED_CURVE, B_CURVE, SP_CURVE, 130)
)


class FaceFailed(Exception):
    """A face (or, raised from a body walk, a body) that cannot be tessellated, with a
    reason from an open set (``docs/API.md`` 3.15) and a detail for people."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason, self.detail = reason, detail


class TimeUp(Exception):
    """The time limit of a tessellation was reached."""


class Clock:
    """A deadline checked every :data:`EVERY` ticks, so loops can tick cheaply."""

    EVERY = 512
    __slots__ = ("deadline", "n")

    def __init__(self, seconds: float) -> None:
        self.deadline = time.perf_counter() + seconds
        self.n = 0

    def tick(self, k: int = 1) -> None:
        self.n += k
        if self.n >= self.EVERY:
            self.n = 0
            if time.perf_counter() > self.deadline:
                raise TimeUp

    def check(self) -> None:
        if time.perf_counter() > self.deadline:
            raise TimeUp

    def left(self) -> float:
        return self.deadline - time.perf_counter()


def finite3(v) -> tuple[float, float, float]:
    if not isinstance(v, tuple) or len(v) != 3:
        raise FaceFailed("bad_reference", "a vector field is not three numbers")
    x, y, z = v
    if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
        raise FaceFailed("non_finite", "a vector is not finite")
    return v


_MISSING = object()


class Topology:
    """Field access by name, checked pointers and bounded walks over one transmit."""

    def __init__(self, xt: XtTransmit) -> None:
        self.xt = xt
        self.nodes: dict[int, Node] = xt.by_index()
        self.limit = len(xt.nodes) + 16
        # A schema that names a field twice: the first one, as XtTransmit.get reads it.
        self._fields: dict[tuple[int, str], int] = {}
        self.shell_of: dict[int, int] = {}  # a face's shell, as the last walk by faces() found it
        for t, lay in xt.layouts.items():
            for i, f in enumerate(lay):
                self._fields.setdefault((t, f[0]), i)

    # -- fields
    def get(self, node: Node, name: str, default=_MISSING):
        i = self._fields.get((node.type, name))
        if i is None or i >= len(node.vals):
            if default is _MISSING:
                raise FaceFailed("bad_reference", f"{node.tname} has no field {name}")
            return default
        return node.vals[i]

    def ref(self, node: Node, name: str, types=None, *, required: bool = False) -> Node | None:
        """The node a pointer field leads to, of one of ``types``; None for a null pointer
        (or raises when ``required``)."""
        v = self.get(node, name, 0)
        if not v:
            if required:
                raise FaceFailed("bad_reference", f"{node.tname}.{name} is null")
            return None
        if not isinstance(v, int):
            raise FaceFailed("bad_reference", f"{node.tname}.{name} is not a pointer")
        target = self.nodes.get(v)
        if target is None:
            raise FaceFailed("bad_reference", f"{node.tname}.{name} points to no node")
        if types is not None and target.type not in types:
            raise FaceFailed("bad_reference", f"{node.tname}.{name} points to a {target.tname}")
        return target

    def number(self, node: Node, name: str) -> float:
        v = self.get(node, name)
        if not isinstance(v, (int, float)) or not math.isfinite(v):
            raise FaceFailed("non_finite", f"{node.tname}.{name} is not a finite number")
        return float(v)

    def vector(self, node: Node, name: str) -> tuple[float, float, float]:
        return finite3(self.get(node, name))

    def unit(self, node: Node, name: str) -> tuple[float, float, float]:
        x, y, z = self.vector(node, name)
        n = math.sqrt(x * x + y * y + z * z)
        if not n > 1e-12:
            raise FaceFailed("bad_geometry", f"{node.tname}.{name} is not a direction")
        return (x / n, y / n, z / n)

    def sense(self, node: Node) -> int:
        """+1 or -1 from a ``sense`` field ('+' or '-'); +1 when the type has none."""
        s = self.get(node, "sense", "+")
        return -1 if s == "-" else 1

    def tolerance(self, node: Node) -> float:
        """A tolerance field: 0 for exact (NULL_DOUBLE) or anything unusable."""
        v = self.get(node, "tolerance", NULL_DOUBLE)
        if not isinstance(v, float) or not math.isfinite(v) or v <= 0.0 or v == NULL_DOUBLE:
            return 0.0
        return v

    # -- walks
    def bodies(self) -> list[Node]:
        return [n for n in self.xt.nodes if n.type == BODY]

    def faces(self, body: Node) -> list[Node]:
        """Every face of ``body``: its regions, their shells, and each shell's faces by
        ``face`` and ``next`` and by ``front_face`` and ``next_front``, each face once.
        :attr:`shell_of` then gives each face's shell (its node index)."""
        out: list[Node] = []
        seen: set[int] = set()
        steps = 0
        regions: set[int] = set()
        region = self.ref(body, "region", (REGION,))
        while region is not None:
            if region.index in regions:
                raise FaceFailed("bad_reference", "the region chain loops")
            regions.add(region.index)
            shells: set[int] = set()
            shell = self.ref(region, "shell", (SHELL,))
            while shell is not None:
                if shell.index in shells:
                    raise FaceFailed("bad_reference", "the shell chain loops")
                shells.add(shell.index)
                for first, nxt in (("face", "next"), ("front_face", "next_front")):
                    chain: set[int] = set()
                    f = self.ref(shell, first, (FACE,))
                    while f is not None and f.index not in chain:
                        steps += 1
                        if steps > 4 * self.limit:
                            raise FaceFailed("bad_reference", "the face chains are too long")
                        chain.add(f.index)
                        if f.index not in seen:
                            seen.add(f.index)
                            out.append(f)
                            self.shell_of[f.index] = shell.index
                        f = self.ref(f, nxt, (FACE,))
                shell = self.ref(shell, "next", (SHELL,))
            region = self.ref(region, "next", (REGION,))
        return out

    def loops(self, face: Node) -> list[Node]:
        out: list[Node] = []
        seen: set[int] = set()
        lp = self.ref(face, "loop", (LOOP,))
        while lp is not None:
            if lp.index in seen:
                raise FaceFailed("bad_reference", "the loop chain loops")
            seen.add(lp.index)
            out.append(lp)
            lp = self.ref(lp, "next", (LOOP,))
        return out

    def fins(self, loop: Node) -> list[Node]:
        """The fins of a loop in order, by ``forward``; the ring must close."""
        first = self.ref(loop, "halfedge", (HALFEDGE,), required=True)
        out = [first]
        seen = {first.index}
        f = self.ref(first, "forward", (HALFEDGE,), required=True)
        while f is not first:
            if f.index in seen:
                raise FaceFailed("bad_reference", "a fin ring does not close")
            seen.add(f.index)
            out.append(f)
            if len(out) > self.limit:
                raise FaceFailed("bad_reference", "a fin ring is too long")
            f = self.ref(f, "forward", (HALFEDGE,), required=True)
        return out

    def point_of(self, vertex: Node | None) -> tuple[float, float, float] | None:
        if vertex is None:
            return None
        pt = self.ref(vertex, "point", (POINT,), required=True)
        return self.vector(pt, "pvec")

    def fin_ends(self, fin: Node) -> tuple[Node | None, Node | None]:
        """A fin's start and end vertices. ``vertex`` is its end; its start is the end of
        the fin before it in its loop, or for a fin outside any loop its partner's end."""
        end = self.ref(fin, "vertex", (VERTEX,))
        start = None
        if self.ref(fin, "loop", (LOOP,)) is not None:
            back = self.ref(fin, "backward", (HALFEDGE,))
            if back is not None:
                start = self.ref(back, "vertex", (VERTEX,))
        else:
            other = self.ref(fin, "other", (HALFEDGE,))
            if other is not None and other is not fin:
                start = self.ref(other, "vertex", (VERTEX,))
        return start, end

    def edge_fins(self, edge: Node) -> list[Node]:
        """The fins of an edge: ``halfedge`` and its partners by ``other``."""
        first = self.ref(edge, "halfedge", (HALFEDGE,), required=True)
        out = [first]
        f = self.ref(first, "other", (HALFEDGE,))
        while f is not None and f is not first and len(out) < 64:
            if any(f is g for g in out):
                break
            out.append(f)
            f = self.ref(f, "other", (HALFEDGE,))
        return out

    def edge_ends(self, edge: Node) -> tuple[Node | None, Node | None]:
        """An edge's start and end vertices, from a fin in a loop: the fin's own ends when
        it runs along the edge (sense '+'), swapped when it runs against it."""
        fins = self.edge_fins(edge)
        fin = next((f for f in fins if self.ref(f, "loop", (LOOP,)) is not None), fins[0])
        start, end = self.fin_ends(fin)
        if self.sense(fin) < 0:
            start, end = end, start
        return start, end
