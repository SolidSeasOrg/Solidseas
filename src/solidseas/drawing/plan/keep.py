"""Key dimensions only (``docs/DRAWINGS.md`` 10.10).

A part whose plan asks for more dimensions than a sheet shows clearly, or whose
layout still puts text on text, gets a drawing of its key dimensions, and the rest
is left to the model: a reduced-dimension drawing with the model-governs note.

Kept whatever the budget: the overall size (the envelope widths, and the faces at
each end of each frame axis), the datums, the holes and their patterns with their
locations, each datum's feature (the one its letter is recorded on), and every
feature the user has made a choice about or the drawing's own dimensions name (one
the user added, moved, overrode or removed). Then the other features and the planar
faces no feature claims, larger first, while the dimensions they bring keep within
the budget; past the first that does not fit, only those that bring none (a fillet
the general note states, a face at an offset already located). A feature's size is
the area of the faces that state or place it (a pocket's floor, a width's pair,
every face of the others), a face several share split between them; a pocket's
walls, which include whatever stands on its floor, are faces of their own, and a
pocket is kept or left whole with the widths across it. The faces of what is left
are unclaimed, with the reason ``model_defined``, and the planner neither states nor
locates them.

The dimensions are counted from the full plan, as it drew them: one for each need a
kept feature makes that the full plan stated, a location for each node of each
axis's graph (the kept positions, joined by the kept implied links) holding a
position the full plan located, but the origin's, and the datum symbols it drew.

Engraved lettering is left to the model whatever the budget (:func:`lettering`):
three or more pockets cut to one depth from one plane, at least half of them with
a free-form wall (a font's outline), and the features standing only on their
faces (the strokes' widths, steps and slopes). Their floors stay planes, so the
depth they share is stated once, with their count.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace

from ..facegraph import OtherSurface
from ..numbers import plain_sum
from ..types import Hole, Pattern, Pocket, Unclaimed, Width
from .context import AXES, Context, dot
from .requirements import Requirements

BUDGET = 60  # dimensions: about as many as the corpus sample's sheets show clear of each other
SHRINK = 0.6  # a crowded layout's next budget, as a share of the dimensions it drew
CROWDED = 0.05  # the share of a layout's dimensions whose text collides that makes it crowded
WALKS = 4  # walks over the features left, while one keeps something
PLACES = 9  # sizes rank to a thousandth of a square millimetre: a near tie falls to recognition order
ACROSS = 0.5  # a gap between two walls of a pocket spanning this share of its floor or more is across it
LETTERS = 3  # pockets at one depth from one plane, most with free-form walls, that read as lettering
MODEL_DEFINED = "model_defined"


def collisions(checks) -> int:
    """The layout checks of text on text: overlaps, and items that could not be placed
    clear."""
    return sum(1 for c in checks if c.code in ("L.overlap", "L.placement"))


def crowded(dimensions: int, checks) -> bool:
    """Whether a layout of ``dimensions`` dimensions collides too often to read; three
    collisions or fewer never do."""
    n = collisions(checks)
    return n > 3 and n >= CROWDED * dimensions


def _faces(f) -> set[int]:
    """The faces that state or place a feature: a pocket's floor, a width's pair, a
    step's or angled face's own face, every face of the others. A pocket's walls are
    faces of their own: they include whatever stands on its floor (ribs, bosses, the
    walls of embossed letters)."""
    if isinstance(f, Pocket):
        return {f.floor} - {-1}
    out = set(f.faces)
    out.update(getattr(f, "pair", ()))
    v = getattr(f, "face", -1)
    if isinstance(v, int):
        out.add(v)
    out.discard(-1)
    return out


def _span(model, face: int, direction) -> float:
    """How far a face reaches along ``direction``."""
    v0, v1 = model.faces[face].vertices
    along = [dot(p, direction) for p in model.points[v0:v1]]
    return max(along) - min(along) if along else 0.0


def _across(ctx: Context, key: set[int]) -> dict[int, list[int]]:
    """For each pocket, the gap widths across it, kept or left with it: between two of its
    walls and spanning at least :data:`ACROSS` of its floor (not the gap between two
    letters standing on it)."""
    fs = ctx.features
    gaps = [
        (j, w) for j, w in enumerate(fs.features) if isinstance(w, Width) and w.kind == "gap" and j not in key
    ]
    out: dict[int, list[int]] = {}
    taken: set[int] = set()
    for k, f in enumerate(fs.features):
        if not isinstance(f, Pocket) or k in key or not 0 <= f.floor < len(ctx.model.faces):
            continue
        walls = set(f.walls)
        for j, w in gaps:
            if j in taken or not set(w.pair) <= walls:
                continue
            if w.size >= ACROSS * _span(ctx.model, f.floor, ctx.direction(w.axis)):
                out.setdefault(k, []).append(j)
                taken.add(j)
    return out


class _Count:
    """The dimensions a choice of features and planar faces draws, counted from the full
    plan (a :class:`~.Planned`) as items are kept."""

    def __init__(self, ctx: Context, full) -> None:
        req: Requirements = full.detail.req
        self.ids = ctx.ids
        stated = {key for d in full.plan.dimensions for key in d.serves}
        self.needs_of: dict[int, list[int]] = defaultdict(list)
        for i, need in enumerate(req.needs):
            if need.req.key not in stated:
                continue  # no view drew it: it is not drawn with fewer either
            for k in need.features:
                self.needs_of[k].append(i)
        self.need_on: set[int] = set()
        # the positions in a node the full plan located (or its origin's); a location
        # runs between two positions
        self.reached: set[tuple[str, int]] = set()
        for ax, g in full.detail.graphs.items():
            nodes = {g.origin}
            for eax, a, b in full.detail.edges.values():
                if eax == ax:
                    nodes.update(g.node_of[p] for p in (a, b) if p in g.node_of)
            self.reached.update((ax, pid) for pid, node in g.node_of.items() if node in nodes)
        self.by_face: dict[int, list[tuple[str, int]]] = defaultdict(list)
        self.by_fid: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for ax in AXES:
            for p in req.positions.get(ax, ()):
                if p.kind == "face":
                    for f in p.faces:
                        self.by_face[f].append((ax, p.id))
                else:
                    for fid in p.features:
                        self.by_fid[fid].append((ax, p.id))
        self.links = {ax: list(req.links.get(ax, ())) for ax in AXES}
        self.link_fids: dict[tuple[str, int], tuple[str, ...]] = {}
        self.links_at: dict[tuple[str, int], list[tuple[str, int]]] = defaultdict(list)
        self.links_of: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for ax in AXES:
            for j, link in enumerate(self.links[ax]):
                fids = tuple(x for x in link.key.split("/")[1:] if x in ctx.index_of)
                self.link_fids[(ax, j)] = fids
                for fid in fids:
                    self.links_of[fid].append((ax, j))
                self.links_at[(ax, link.a)].append((ax, j))
                self.links_at[(ax, link.b)].append((ax, j))
        self.fids: set[str] = set()
        self.on: set[tuple[str, int]] = set()
        self.joined: set[tuple[str, int]] = set()
        self.parent: dict[tuple[str, int], tuple[str, int]] = {}
        self.located: dict[tuple[str, int], bool] = {}  # a root: whether its node needs a location
        self.nodes = dict.fromkeys(AXES, 0)  # the nodes that need a location, with the origin's
        self.needs = 0
        self.datums = sum(1 for d in full.plan.dimensions if d.kind == "datum_feature")

    def _root(self, x):
        root = x
        while self.parent.get(root, root) != root:
            root = self.parent[root]
        while self.parent.get(x, x) != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def _located(self, root) -> bool:
        return self.located.get(root, root in self.reached)

    def add(self, features, faces, keep: bool = False) -> int:
        """The count with ``features`` and ``faces`` kept as well; kept for good when
        ``keep``."""
        fids = {self.ids[k] for k in features} - self.fids
        needs = {i for k in features for i in self.needs_of.get(k, ()) if i not in self.need_on}
        new: set[tuple[str, int]] = set()
        for f in faces:
            new.update(x for x in self.by_face.get(f, ()) if x not in self.on)
        for fid in fids:
            new.update(x for x in self.by_fid.get(fid, ()) if x not in self.on)
        maybe: set[tuple[str, int]] = set()
        for fid in fids:
            maybe.update(self.links_of.get(fid, ()))
        for x in new:
            maybe.update(self.links_at.get(x, ()))
        kept = self.fids | fids
        links = []
        for ax, j in sorted(maybe):
            if (ax, j) in self.joined or not any(fid in kept for fid in self.link_fids[(ax, j)]):
                continue
            a, b = (ax, self.links[ax][j].a), (ax, self.links[ax][j].b)
            if (a in self.on or a in new) and (b in self.on or b in new):
                links.append((a, b, (ax, j)))
        # the links join the graphs' nodes: count the joins among the nodes as they stand
        tiny: dict = {}
        flags: dict = {}

        def top(x):
            while tiny.get(x, x) != x:
                x = tiny[x]
            return x

        def located(root) -> bool:
            return flags.get(root, self._located(root))

        nodes = dict(self.nodes)
        for x in new:
            nodes[x[0]] += x in self.reached
        for a, b, _key in links:
            ra, rb = top(self._root(a)), top(self._root(b))
            if ra != rb:
                fa, fb = located(ra), located(rb)
                tiny[ra] = rb
                flags[rb] = fa or fb
                nodes[a[0]] -= fa and fb
        total = self.needs + len(needs) + sum(max(0, n - 1) for n in nodes.values()) + self.datums
        if keep:
            self.fids |= fids
            self.need_on |= needs
            self.needs += len(needs)
            self.on |= new
            for a, b, key in links:
                self.joined.add(key)
                ra, rb = self._root(a), self._root(b)
                if ra != rb:
                    self.located[rb] = self._located(ra) or self._located(rb)
                    self.parent[ra] = rb
            self.nodes = nodes
        return total


def lettering(ctx: Context, named=frozenset()) -> Context:
    """``ctx`` with its engraved lettering left to the model but for its depth (see the
    module); ``ctx`` itself when it has none. A pocket the user has chosen something
    about or the drawing's own dimensions name (``named``), or that holds a datum's
    face, is not lettering."""
    fs = ctx.features
    model = ctx.model
    n = len(fs.features)
    tol = max(ctx.tol, 1e-12)
    datum_faces = {d.face for d in fs.frame.datums}
    groups: dict[tuple[str, int, int], list[int]] = {}
    for d in fs.depths:
        k = d.feature
        if not 0 <= k < n or k in fs.model_defined or not d.axis:
            continue
        f = fs.features[k]
        if not isinstance(f, Pocket) or ctx.ids[k] in ctx.decisions or ctx.ids[k] in named:
            continue
        if datum_faces & set(f.faces):
            continue
        at = ctx.plane_at(d.open_face, d.axis)
        groups.setdefault((d.axis, round(at / tol), round(d.value / tol)), []).append(k)
    letters: set[int] = set()
    for ks in groups.values():
        members = sorted(set(ks))
        free = sum(
            1
            for k in members
            if any(isinstance(model.faces[w].surface, OtherSurface) for w in fs.features[k].walls)
        )
        if len(members) >= LETTERS and 2 * free >= len(members):
            letters.update(members)
    if not letters:
        return ctx
    floors = {fs.features[k].floor for k in letters}
    faces = set().union(*(set(fs.features[k].faces) for k in letters))
    # the strokes' widths, steps and slopes: the features standing on the letters' faces alone
    on = {
        k
        for k, f in enumerate(fs.features)
        if k not in letters
        and k not in fs.model_defined
        and _faces(f)
        and _faces(f) <= faces
        and ctx.ids[k] not in ctx.decisions
        and ctx.ids[k] not in named
    }
    left = letters | on
    walls = {i for i in faces - floors if 0 <= i < len(model.faces)} - {u.face for u in fs.unclaimed}
    extra = tuple(Unclaimed(i, model.faces[i].area, MODEL_DEFINED) for i in sorted(walls))
    cov = fs.coverage
    coverage = replace(
        cov,
        features_unclaimed=cov.features_unclaimed + len(left),
        faces_claimed=max(0, cov.faces_claimed - len(extra)),
        area_claimed=max(0.0, cov.area_claimed - plain_sum(model.faces[i].area for i in sorted(walls))),
    )
    features = replace(
        fs,
        unclaimed=fs.unclaimed + extra,
        coverage=coverage,
        model_defined=fs.model_defined | frozenset(left),
        lettering=fs.lettering | frozenset(letters),
    )
    return replace(ctx, features=features, ids=ctx.ids)


def trim(ctx: Context, full, budget: int, named=frozenset()) -> Context | None:
    """``ctx`` with what does not fit ``budget`` left to the model (see the module), from
    ``full``, the plan of ``ctx`` with every requirement (a :class:`~.Planned`); None
    when nothing would be left. ``named`` holds the ids of features the drawing's own
    dimensions name, which are kept as the user's choices are."""
    req: Requirements = full.detail.req
    fs = ctx.features
    model = ctx.model
    n = len(fs.features)
    own = [_faces(f) for f in fs.features]
    # a feature's size: the area of its own faces, a face several share split between them
    sharing = Counter(i for faces in own for i in faces)
    size = [
        plain_sum(model.faces[i].area / sharing[i] for i in sorted(faces) if 0 <= i < len(model.faces))
        for faces in own
    ]
    faces_of = [set(faces) for faces in own]  # with the faces its depth runs between
    for d in fs.depths:
        if 0 <= d.feature < n:
            faces_of[d.feature].update(x for x in (d.open_face, d.floor) if x >= 0)
    claimed = set().union(*faces_of)

    def area(faces) -> float:
        return plain_sum(model.faces[i].area for i in sorted(faces) if 0 <= i < len(model.faces))

    key = {
        k
        for k, f in enumerate(fs.features)
        if isinstance(f, (Hole, Pattern))
        or (isinstance(f, Width) and f.role == "envelope")
        or ctx.ids[k] in ctx.decisions
        or ctx.ids[k] in named
    }
    # a datum's feature, the first that claims its face, as the drawing records its letter
    for d in fs.frame.datums:
        first = next((k for k, f in enumerate(fs.features) if d.face in f.faces), None)
        if first is not None:
            key.add(first)
    key_faces = {d.face for d in fs.frame.datums}
    for ax in AXES:
        at = [p for p in req.positions.get(ax, ()) if p.kind == "face"]
        if at:
            key_faces.update(min(at, key=lambda p: (p.value, p.id)).faces)
            key_faces.update(max(at, key=lambda p: (p.value, -p.id)).faces)
    for k in key:
        key_faces |= faces_of[k]
    count = _Count(ctx, full)
    total = count.add(key, key_faces, keep=True)
    kept, kept_faces = set(key), set(key_faces)

    across = _across(ctx, key)
    with_pocket = {j for js in across.values() for j in js}
    items = []
    for k in range(n):
        if k in key or k in with_pocket or k in fs.model_defined:
            continue
        feats = (k, *across.get(k, ()))
        faces = frozenset().union(*(faces_of[j] for j in feats))
        items.append(((-round(plain_sum(size[j] for j in feats), PLACES), 0, k), feats, faces))
    for ax in AXES:
        for p in req.positions.get(ax, ()):
            free = frozenset(i for i in p.faces if i not in claimed and i not in key_faces)
            if p.kind == "face" and free:
                items.append(((-round(area(free), PLACES), 1, min(free)), (), free))
    items.sort(key=lambda item: item[0])
    # Larger first, and past the first that does not fit only what brings nothing; a
    # width kept late may join two nodes and free a location, so walk what is left again
    # while a walk keeps something.
    rest = items
    for _walk in range(WALKS):
        past = False  # the first that does not fit
        left_over = []
        for item in rest:
            _rank, feats, faces = item
            trial = count.add(feats, faces)
            if trial > total and (past or trial > budget):
                past = True
                left_over.append(item)
                continue
            total = count.add(feats, faces, keep=True)
            kept.update(feats)
            kept_faces |= faces
        if len(left_over) == len(rest):
            break
        rest = left_over

    left_features = sorted(set(range(n)) - kept - fs.model_defined)  # lettering is left already
    left: set[int] = set()
    for k in left_features:
        left |= faces_of[k] | set(fs.features[k].faces)  # a pocket's walls, its rounded corners
    for _rank, feats, faces in items:
        if not feats:
            left |= faces
    left -= kept_faces
    for k in kept:
        left -= faces_of[k]
    left -= {u.face for u in fs.unclaimed}
    left = {i for i in left if 0 <= i < len(model.faces)}
    if not left_features and not left:
        return None
    extra = tuple(Unclaimed(i, model.faces[i].area, MODEL_DEFINED) for i in sorted(left))
    cov = fs.coverage
    coverage = replace(
        cov,
        features_unclaimed=cov.features_unclaimed + len(left_features),
        faces_claimed=max(0, cov.faces_claimed - len(extra)),
        area_claimed=max(0.0, cov.area_claimed - area(left)),
    )
    features = replace(
        fs,
        unclaimed=fs.unclaimed + extra,
        coverage=coverage,
        model_defined=fs.model_defined | frozenset(left_features),
    )
    return replace(ctx, features=features, ids=ctx.ids)


__all__ = ["BUDGET", "MODEL_DEFINED", "SHRINK", "collisions", "crowded", "lettering", "trim"]
