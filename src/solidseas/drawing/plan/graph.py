"""The linear graph, one a frame axis: the planner's tool and the editor's checker
(``docs/DRAWINGS.md`` 10.2).

Nodes are the positions along the axis, contracted through the implied links a
size states (a width joins its two faces, a depth its floor to the open face, a
pitch a pattern's members). The origin is the datum plane square to the axis.

**Complete** means every node reaches the origin. **Not redundant** means the drawn
location dimensions form a tree over the contracted nodes: a dimension that joins
two nodes already joined closes a loop. :func:`check` says both, naming the
features a node stands for (C16), never only its coordinates.

:func:`witnesses` answers where a position can carry an extension line (C8): a face
where a view shows a visible line at it, a hole's or boss's axis where a view sees
the feature end on (open) or its centre line side on, an angled face's meet line
where it is end on.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

from ..types import GraphResult, ViewGeometry, ViewSpec, requirement_key
from .context import Context, dot
from .requirements import Link, Pos

SIDE_ON_COST = 0.15  # a centre line seen side on is a weaker witness than a centre mark
NOT_FRONT_COST = 0.1  # 10.2: a small amount for a view other than the front
STACK_COST = 0.5  # each dimension between a node and the origin beyond the first
DATUM_FACE_COST = 0.05  # another face of the origin's node, joined to it by a size


@dataclass(frozen=True)
class Witnessed:
    """A position seen in a view: where it is on the sheet axis the dimension runs
    along (view metres), and what a dimension pays to use it there."""

    view: str
    sheet_axis: str
    at: float
    cost: float


def witnesses(ctx: Context, p: Pos) -> list[Witnessed]:
    """Every orthographic view that shows ``p`` as a place an extension line can start."""
    out = []
    for spec, geom in ctx.orthographic():
        w = witness_in(ctx, spec, geom, p)
        if w is not None:
            out.append(w)
    return out


def witness_in(ctx: Context, spec: ViewSpec, geom: ViewGeometry, p: Pos) -> Witnessed | None:
    sa = ctx.sheet_axis(spec, p.axis)
    if sa is None:
        return None
    name, sign = sa
    at = sign * p.value
    base = 0.0 if spec.kind == "base" else NOT_FRONT_COST
    tol = max(ctx.tol, 1e-7)
    if p.kind == "face":
        if geom.witness_at(name, at, tol) is None:
            return None
        return Witnessed(spec.id, name, at, base)
    _r, _u, d = spec.frame()
    if p.along is None:
        return None
    if ctx.looks_along(spec, p.along):
        if p.seen and not any(dot(s, d) > 0.5 for s in p.seen):
            return None  # end on, but from the closed side: hidden
        return Witnessed(spec.id, name, at, base)
    if p.kind == "centre" and abs(dot(p.along, d)) <= 1e-6:
        return Witnessed(spec.id, name, at, base + SIDE_ON_COST)
    return None


class Graph:
    """One axis's positions, contracted into nodes by the implied links."""

    def __init__(self, axis: str, positions: list[Pos], links: list[Link], origin: int) -> None:
        self.axis = axis
        self.pos = {p.id: p for p in positions}
        parent = {pid: pid for pid in self.pos}

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        self.links = [lk for lk in links if lk.a in self.pos and lk.b in self.pos]
        for lk in self.links:
            ra, rb = find(lk.a), find(lk.b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
        self.node_of = {pid: find(pid) for pid in self.pos}
        self.members: dict[int, list[int]] = {}
        for pid in sorted(self.pos):
            self.members.setdefault(self.node_of[pid], []).append(pid)
        self.origin = self.node_of[origin] if origin in self.node_of else min(self.members, default=0)
        self.origin_pos = origin

    @property
    def nodes(self) -> list[int]:
        return sorted(self.members)

    def features(self, node: int) -> tuple[str, ...]:
        out: list[str] = []
        for pid in self.members[node]:
            out += self.pos[pid].features
        return tuple(dict.fromkeys(out))

    def keys(self, node: int) -> tuple[str, ...]:
        """The location requirement keys a node's dimension serves: one per feature it
        stands for, or one naming its first face when it stands for none."""
        feats = self.features(node)
        if feats:
            return tuple(requirement_key("loc", [f], self.axis) for f in feats)
        faces = [f for pid in self.members[node] for f in self.pos[pid].faces]
        name = f"face-{min(faces)}" if faces else f"node-{node}"
        return (requirement_key("loc", [name], self.axis),)

    def label(self, node: int, ctx: Context | None = None) -> str:
        """The node in words, by the features it stands for (C16)."""
        feats = self.features(node)
        if ctx is not None and feats:
            from .values import feature_words

            return feature_words(ctx, feats)
        if feats:
            return ", ".join(feats)
        v = self.pos[self.members[node][0]].value
        return f"the face at {self.axis.upper()} {v * 1000:.3f} mm"

    def check(self, edges: list[tuple[int, int, str]]) -> GraphResult:
        """Whether ``edges`` (position, position, dimension id), the drawn locations,
        reach every node from the origin once: missing keys and closed loops."""
        parent = {n: n for n in self.members}

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        loops: list[tuple[str, ...]] = []
        adjacent: dict[int, list[tuple[int, str]]] = {n: [] for n in self.members}
        for a, b, did in edges:
            if a not in self.node_of or b not in self.node_of:
                continue
            u, v = self.node_of[a], self.node_of[b]
            if find(u) == find(v):
                loops.append(tuple(sorted(_path(adjacent, u, v) + [did])))
                continue
            parent[max(find(u), find(v))] = min(find(u), find(v))
            adjacent[u].append((v, did))
            adjacent[v].append((u, did))
        origin = find(self.origin)
        missing: list[str] = []
        for n in self.nodes:
            if find(n) != origin:
                missing += self.keys(n)
        return GraphResult(f"linear/{self.axis}", not missing, bool(loops), tuple(missing), tuple(loops))


def _path(adjacent: dict[int, list[tuple[int, str]]], u: int, v: int) -> list[str]:
    """The dimensions on the tree path from node ``u`` to node ``v``: with the one that
    joins them again, the loop it closes."""
    back: dict[int, tuple[int, str] | None] = {u: None}
    queue = [u]
    for x in queue:
        if x == v:
            break
        for y, did in adjacent[x]:
            if y not in back:
                back[y] = (x, did)
                queue.append(y)
    out: list[str] = []
    x = v
    while back.get(x) is not None:
        x, did = back[x]
        out.append(did)
    return out


@dataclass(frozen=True)
class Located:
    """A drawn location: from position ``a`` to position ``b`` in ``view``."""

    a: int
    b: int
    view: str
    cost: float
    keys: tuple[str, ...]


def _drawable(ctx: Context, g: Graph, seen: dict[int, list[Witnessed]], na: int, nb: int):
    """The cheapest view and representatives joining nodes ``na`` and ``nb``: both seen
    in one view, along the same sheet axis."""
    best = None
    for pa in g.members[na]:
        for pb in g.members[nb]:
            for wa in seen[pa]:
                for wb in seen[pb]:
                    if wa.view != wb.view or wa.sheet_axis != wb.sheet_axis:
                        continue
                    cost = 1.0 + wa.cost + wb.cost
                    if na == g.origin and pa != g.origin_pos:
                        cost += DATUM_FACE_COST  # measure from the datum face itself
                    if g.pos[pb].kind == "face" and any(g.pos[q].kind == "centre" for q in g.members[nb]):
                        cost += DATUM_FACE_COST  # a slot by its centre line, not a wall
                    key = (cost, wa.view, pa, pb)
                    if best is None or key < best[0]:
                        best = (key, pa, pb, wa.view, cost)
    if best is None:
        return None
    return best[1], best[2], best[3], best[4]


def node_of_feature(g: Graph, fid: str) -> int | None:
    """The node standing for feature ``fid`` along the graph's axis: its centre where it
    has one, else its lowest position."""
    hits = [pid for pid in sorted(g.pos) if fid in g.pos[pid].features]
    centres = [pid for pid in hits if g.pos[pid].kind == "centre"]
    pick = centres or hits
    return g.node_of[pick[0]] if pick else None


def fixed_links(ctx: Context, g: Graph) -> dict[int, int]:
    """The links the user made (10.12 ``link``), node to the node it is dimensioned
    from: a feature's decision ``link_<axis>`` names the feature it is located from.
    A link to itself, to or from a node no feature stands for, or onto the origin is
    left out."""
    out: dict[int, int] = {}
    for fid in sorted(ctx.decisions):
        src = ctx.decisions[fid].get(f"link_{g.axis}")
        if not isinstance(src, str):
            continue
        a, b = node_of_feature(g, src), node_of_feature(g, fid)
        if a is None or b is None or a == b or b == g.origin:
            continue
        out[b] = a
    return out


def baseline(
    ctx: Context, g: Graph, previous: frozenset[tuple[str, ...]] = frozenset()
) -> tuple[list[Located], list[int]]:
    """The baseline tree (10.4): each node joined to the origin where one view sees
    both, else by the cheapest drawable path from a node already joined (Dijkstra,
    each step costing more the further it is from the origin, which keeps stacks
    short). ``previous`` holds the keys the last plan drew; their edges cost half
    (hysteresis). Returns the locations and the nodes no view can reach."""
    seen = {pid: witnesses(ctx, g.pos[pid]) for pid in g.pos}
    out: list[Located] = []
    depth = {g.origin: 0}
    best: dict[int, tuple] = {}
    heap: list[tuple] = []
    fixed = fixed_links(ctx, g)

    def offer(src: int, dst: int) -> None:
        if fixed.get(dst, src) != src:
            return  # the user dimensioned this node from another one
        if dst in best and best[dst][0] <= 0.5 + STACK_COST * depth[src]:
            return  # nothing from here can be cheaper
        hit = _drawable(ctx, g, seen, src, dst)
        if hit is None:
            return
        pa, pb, view, cost = hit
        keys = g.keys(dst)
        if keys in previous:
            cost *= 0.5
        total = cost + STACK_COST * depth[src]
        entry = (total, dst, src, pa, pb, view, cost)
        if dst not in best or entry < best[dst]:
            best[dst] = entry
            heapq.heappush(heap, entry)

    for n in g.nodes:
        if n != g.origin:
            offer(g.origin, n)
    while heap:
        total, dst, src, pa, pb, view, cost = heapq.heappop(heap)
        if dst in depth or best.get(dst) != (total, dst, src, pa, pb, view, cost):
            continue
        depth[dst] = depth[src] + 1
        out.append(Located(pa, pb, view, cost, g.keys(dst)))
        for n in g.nodes:
            if n not in depth:
                offer(dst, n)
    unreached = [n for n in g.nodes if n not in depth]
    return out, unreached


__all__ = [
    "Graph",
    "Located",
    "Witnessed",
    "baseline",
    "fixed_links",
    "node_of_feature",
    "witness_in",
    "witnesses",
]
