"""Product structure of a STEP file: products, their shapes and how assemblies place
their components (provisional).

ISO 10303-41, -43 and -44 as AP203, AP214 and AP242 use them:

* A ``PRODUCT_DEFINITION`` (of a ``PRODUCT_DEFINITION_FORMATION`` of a ``PRODUCT``) is
  one product version; its ``PRODUCT_DEFINITION_SHAPE`` is linked by a
  ``SHAPE_DEFINITION_REPRESENTATION`` to its shape representation. Representations
  related by a ``SHAPE_REPRESENTATION_RELATIONSHIP`` without a transformation share
  one coordinate space (a part's ``SHAPE_REPRESENTATION`` and its
  ``ADVANCED_BREP_SHAPE_REPRESENTATION``); one with a transformation, or a
  ``MAPPED_ITEM``, places one inside the other. A product's geometry is every solid,
  shell, faceted B-rep and tessellated item reachable that way, without entering
  another product's representation.
* An assembly is a ``NEXT_ASSEMBLY_USAGE_OCCURRENCE`` from the parent product
  definition to the child's. Its placement is a
  ``CONTEXT_DEPENDENT_SHAPE_REPRESENTATION`` whose relationship (a
  ``REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION`` over an
  ``ITEM_DEFINED_TRANSFORMATION``) maps ``transform_item_1`` of ``rep_1`` onto
  ``transform_item_2`` of ``rep_2``. Which of the two representations is the
  child's is found from the child product definition, never from the order,
  because writers store both orders. The child sits in the parent at
  ``T(parent item) * inverse(T(child item))``. An occurrence placed by a
  ``MAPPED_ITEM`` instead sits at ``T(mapping target) * inverse(T(mapping origin))``:
  either its context-dependent shape representation's relationship has no
  transformation and one of its two representations (not the parent's, not the
  child's) holds the mapped item, or it has no placement of its own and takes a
  mapped item of the parent's shape that maps the same child. A relationship with no
  transformation and no mapped item places the child at the parent's origin.

Every placement is in metres: each axis placement's location is scaled by its own
representation's context.
"""

import itertools
import math
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from ...errors import SldFormatError, SldLimitError
from ..solidworks.components import IDENTITY, Placement
from .builder import perpendicular
from .geometry import SOLIDS, Geometry, Unsupported
from .part21 import Part21, Record, Ref, Typed
from .units import ASSUMED, Context, Units

PD_TYPES = ("PRODUCT_DEFINITION", "PRODUCT_DEFINITION_WITH_ASSOCIATED_DOCUMENTS")
RR_TYPES = (
    "SHAPE_REPRESENTATION_RELATIONSHIP",
    "REPRESENTATION_RELATIONSHIP",
    "REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION",
)
FACETED = ("FACETED_BREP",)
TESSELLATED = (
    "TESSELLATED_SOLID",
    "TESSELLATED_SHELL",
    "TRIANGULATED_FACE",
    "COMPLEX_TRIANGULATED_FACE",
    "TRIANGULATED_SURFACE_SET",
    "COMPLEX_TRIANGULATED_SURFACE_SET",
)
SHELL_ITEMS = ("CLOSED_SHELL", "OPEN_SHELL", "ORIENTED_CLOSED_SHELL", "ORIENTED_OPEN_SHELL")
# Items a shape representation holds that are not geometry to draw: placements, and the
# like. Anything else that is not drawn is counted as left out.
IGNORED_ITEMS = (
    "AXIS2_PLACEMENT_3D",
    "AXIS2_PLACEMENT_2D",
    "AXIS1_PLACEMENT",
    "CARTESIAN_POINT",
    "DIRECTION",
)
MAX_REP_DEPTH = 16
MAX_VISITS = 100_000  # representations visited for one product (a guard against a dense graph)
CHILD_REPS = 10_000  # representations sharing one product's space, at most


# --------------------------------------------------------------------------- placements
def frame_placement(frame) -> Placement:
    """The placement that takes a frame's local coordinates to its representation's."""
    o, x, y, z = frame
    return Placement(((x[0], y[0], z[0]), (x[1], y[1], z[1]), (x[2], y[2], z[2])), o)


def inverse(p: Placement) -> Placement:
    """The inverse of a placement (any invertible matrix, not only a rotation)."""
    r, t = p.rotation, p.translation_m
    a, b, c = r[0]
    d, e, f = r[1]
    g, h, i = r[2]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if not math.isfinite(det) or abs(det) < 1e-300:
        raise Unsupported("bad_geometry", "", "a placement that cannot be inverted")
    inv = (
        ((e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det),
        ((f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det),
        ((d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det),
    )
    tt = tuple(-(inv[k][0] * t[0] + inv[k][1] * t[1] + inv[k][2] * t[2]) for k in range(3))
    return Placement(inv, tt)  # type: ignore[arg-type]


def _key(p: Placement) -> tuple:
    """A placement as a hashable key, to 1e-12 (as :func:`_same` compares them)."""
    return tuple(round(x, 12) for row in p.rotation for x in row) + tuple(
        round(x, 12) for x in p.translation_m
    )


def _same(a: Placement, b: Placement) -> bool:
    return all(
        abs(x - y) <= 1e-12
        for ra, rb in zip(a.rotation, b.rotation, strict=True)
        for x, y in zip(ra, rb, strict=True)
    ) and all(abs(x - y) <= 1e-12 for x, y in zip(a.translation_m, b.translation_m, strict=True))


PLACEMENT_CELL = 1e-6  # the grid :class:`_PlacementIndex` files placements on
PLACEMENT_MARGIN = 1e-9  # a value this close to a cell's edge is looked for on both sides


def _values(p: Placement) -> tuple[float, ...]:
    r = p.rotation
    return (*r[0], *r[1], *r[2], *p.translation_m)


def _cell(v: float) -> int:
    """The cell of the placement grid a value lies in. The cells are centred on the
    multiples of :data:`PLACEMENT_CELL`, so the values placements are full of (0, 1 and
    round lengths) lie in the middle of one, far from its edges."""
    return math.floor(v / PLACEMENT_CELL + 0.5)


class _PlacementIndex:
    """Placements in the order given, each of which can be taken once by the first that
    :func:`_same` matches to a placement asked for, in about constant time rather than a
    scan of them all. Each is filed by its twelve values on a grid of
    :data:`PLACEMENT_CELL`, far coarser than the 1e-12 :func:`_same` allows, so a match
    lies in the cell of the placement asked for or, where one of its values sits within
    :data:`PLACEMENT_MARGIN` of a cell's edge, in the cell beside it there. A placement
    that is not finite matches nothing, as with :func:`_same`."""

    def __init__(self, placements: list[Placement]) -> None:
        self.placements = placements
        self.cells: dict[tuple[int, ...], deque[int]] = defaultdict(deque)
        for k, p in enumerate(placements):
            vals = _values(p)
            if all(math.isfinite(v) for v in vals):
                self.cells[tuple(_cell(v) for v in vals)].append(k)

    @staticmethod
    def near(vals: tuple[float, ...]) -> list[tuple[int, ...]]:
        """The cells a placement within the tolerance of ``vals`` can lie in: one, unless a
        value sits within :data:`PLACEMENT_MARGIN` of a cell's edge."""
        sides = [range(_cell(v - PLACEMENT_MARGIN), _cell(v + PLACEMENT_MARGIN) + 1) for v in vals]
        return list(itertools.product(*sides))

    def take(self, p: Placement) -> bool:
        """Whether a placement not yet taken matches ``p``; the first in order that does is
        taken."""
        vals = _values(p)
        if not all(math.isfinite(v) for v in vals):
            return False
        best: tuple[int, deque[int], int] | None = None  # (placement, its cell, where in it)
        for key in self.near(vals):
            cell = self.cells.get(key)
            if not cell:
                continue
            for at, k in enumerate(cell):
                if best is not None and k > best[0]:
                    break
                if _same(self.placements[k], p):
                    best = (k, cell, at)
                    break
        if best is None:
            return False
        _k, cell, at = best
        if at == 0:
            cell.popleft()
        else:
            del cell[at]
        return True


# --------------------------------------------------------------------------- the structure
@dataclass
class Item:
    """One geometric item of a product: ``rid`` the STEP instance, ``kind`` ``solid``,
    ``sheet`` (a shell of a surface model, or an open shell), ``faceted`` or
    ``tessellated``, its representation's context and its placement in the
    product's frame. ``sbsm`` is the surface model a sheet's shell belongs to."""

    rid: int
    kind: str
    ctx: Context
    placement: Placement = IDENTITY
    sbsm: int | None = None


@dataclass
class ProductDef:
    pd: int
    product: int | None = None
    id_text: str | None = None
    name: str | None = None
    description: str | None = None
    reps: list[int] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    ctx: Context | None = None

    @property
    def label(self) -> str | None:
        for v in (self.name, self.id_text):
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None


@dataclass
class Occurrence:
    rid: int
    parent: int
    child: int
    name: str | None
    placement: Placement | None
    how: str  # "cdsr", "mapped_item" or "none"


@dataclass
class Structure:
    pds: dict[int, ProductDef]
    occurrences: list[Occurrence]
    roots: list[int]
    skipped_items: dict[str, int]
    orphans: bool = False  # the geometry came from representations no product names
    unresolved: int = 0  # occurrences with no usable placement
    rep_cycles: int = 0
    ambiguous: int = 0  # mapped items beside occurrences their relationships already place


@dataclass
class _Walk:
    """One product's walk over its representations: the items found (with their
    placements), the mapped items that place other products, the (representation,
    placement) pairs visited and how many."""

    seen: set = field(default_factory=set)
    mapped: list = field(default_factory=list)
    visited: set = field(default_factory=set)
    visits: int = 0


@dataclass
class _Beside:
    """The items of a representation that holds the mapped items placing occurrences
    beside their relationships (:meth:`Reader._mapped_beside`), read in order and only as
    far as needed: ``at`` is the next item to read, and ``found`` the mapped items read
    and not taken, by the representation each maps, as (position, item, placement)."""

    items: list
    ctx: Context
    at: int = 0
    found: dict[int, deque] = field(default_factory=dict)


def _text(v: Any) -> str | None:
    return v if isinstance(v, str) and v.strip() else None


class Reader:
    """Builds the :class:`Structure` of one file (see the module notes)."""

    def __init__(self, p21: Part21, units: Units, limits: Any, clock: Any = None) -> None:
        self.p = p21
        self.units = units
        self.g = Geometry(p21)
        self.limits = limits
        self.clock = clock
        self.skipped: dict[str, int] = defaultdict(int)
        self.rep_cycles = 0
        self._rel: dict[int, tuple[int, int, Any] | None] = {}
        self._child_cache: dict[int, set[int]] = {}
        self._links: dict[int, list[tuple[int, int, bool]]] = {}
        self._owner: dict[int, int] = {}
        self._beside: dict[int, _Beside | None] = {}

    def tick(self) -> None:
        if self.clock is not None:
            self.clock.tick()

    def rec(self, ref: Any) -> Record | None:
        return self.p.get(ref)

    def _readable(self, ref: Any) -> Record | None:
        """``rec``, with a record that cannot be parsed counted as skipped (``damaged``)
        rather than ending the read."""
        try:
            return self.p.get(ref)
        except SldLimitError:
            raise
        except SldFormatError:
            self.skipped["damaged"] += 1
            return None

    # -- product definitions and their representations ------------------------------------
    def read(self) -> Structure:
        p = self.p
        lim = self.limits
        pd_ids = sorted({i for t in PD_TYPES for i in p.ids_of_type(t)})
        if len(pd_ids) > lim.step_products:
            raise lim.exceeded("step_products", f"the file defines more than {lim.step_products:,} products")
        pds: dict[int, ProductDef] = {}
        for i in pd_ids:
            self.tick()
            pds[i] = self._pd(i)
        # product definition shapes: what each one describes
        pds_of: dict[int, list[int]] = defaultdict(list)  # PD or NAUO -> its PDS ids
        for i in p.ids_of_type("PRODUCT_DEFINITION_SHAPE"):
            r = p.record(i)
            prm = r.part("PRODUCT_DEFINITION_SHAPE") or r.params
            if len(prm) >= 3 and isinstance(prm[2], Ref):
                pds_of[int(prm[2])].append(i)
        rep_of_pds: dict[int, list[int]] = defaultdict(list)
        for i in p.ids_of_type("SHAPE_DEFINITION_REPRESENTATION"):
            r = p.record(i)
            prm = r.part("SHAPE_DEFINITION_REPRESENTATION") or r.params
            if len(prm) >= 2 and isinstance(prm[0], Ref) and isinstance(prm[1], Ref):
                rep_of_pds[int(prm[0])].append(int(prm[1]))
        owner: dict[int, int] = {}  # shape representation -> the PD it describes
        for pd, d in pds.items():
            listed: set[int] = set()
            for s in pds_of.get(pd, []):
                for rep in rep_of_pds.get(s, []):
                    if rep not in listed:
                        listed.add(rep)
                        d.reps.append(rep)
                    owner.setdefault(rep, pd)
        # relationships between representations, and those that place an occurrence
        cdsr_rr: dict[int, int] = {}  # NAUO's PDS -> the relationship
        for i in p.ids_of_type("CONTEXT_DEPENDENT_SHAPE_REPRESENTATION"):
            r = p.record(i)
            prm = r.params
            if len(prm) >= 2 and isinstance(prm[0], Ref) and isinstance(prm[1], Ref):
                cdsr_rr[int(prm[1])] = int(prm[0])
        assembly_links = set(cdsr_rr.values())
        links: dict[int, list[tuple[int, int, bool]]] = defaultdict(list)  # rep -> (rr, other, is_rep_1)
        rr_ids = sorted({i for t in RR_TYPES for i in p.ids_of_type(t)})
        for i in rr_ids:
            self.tick()
            if i in assembly_links:
                continue
            got = self._relationship(i)
            if got is None:
                continue
            rep_1, rep_2, _t = got
            links[rep_1].append((i, rep_2, True))
            links[rep_2].append((i, rep_1, False))
        self._links = links
        self._owner = owner
        # each product's geometry
        mapped: list[tuple[int, int, Placement, int, str | None]] = []  # parent, child, placement, item, name
        for pd, d in pds.items():
            self.tick()
            if d.reps:
                d.ctx = self._context(d.reps[0])
            walk = _Walk()
            for rep in d.reps:
                self._collect(pd, rep, IDENTITY, d, walk, set())
            mapped.extend(walk.mapped)
        # occurrences
        nauos = p.ids_of_type("NEXT_ASSEMBLY_USAGE_OCCURRENCE")
        if len(nauos) > lim.step_occurrences:
            raise lim.exceeded(
                "step_occurrences", f"the file holds more than {lim.step_occurrences:,} assembly occurrences"
            )
        occurrences: list[Occurrence] = []
        unresolved = 0
        pending_mapped: dict[tuple[int, int], list[tuple[Placement, int, str | None]]] = defaultdict(list)
        for parent, child, pl, item, name in mapped:
            pending_mapped[(parent, child)].append((pl, item, name))
        waiting: list[tuple[Occurrence, bool]] = []
        used_items: set[int] = set()  # mapped items that already place an occurrence
        for i in nauos:
            self.tick()
            r = p.record(i)
            prm = r.part("NEXT_ASSEMBLY_USAGE_OCCURRENCE") or r.params
            if r.complex:
                prm = r.part("PRODUCT_DEFINITION_RELATIONSHIP") or prm
            if len(prm) < 5 or not isinstance(prm[3], Ref) or not isinstance(prm[4], Ref):
                continue
            parent, child = int(prm[3]), int(prm[4])
            if parent not in pds or child not in pds:
                continue
            # the occurrence's name, else the child product's (writers often leave the name
            # blank and number the id), else its id
            name = _text(prm[1]) or pds[child].label or _text(prm[0])
            placement = None
            how = "none"
            shared = False  # a relationship with no transformation: the parent's origin
            for s in pds_of.get(i, []):
                rr = cdsr_rr.get(s)
                if rr is None:
                    continue
                got = self._relationship(rr)
                if got is None:
                    continue
                if got[2] is None:
                    shared = True
                    placement = self._mapped_beside(got, pds[child], pds[parent], used_items)
                    if placement is not None:
                        how = "mapped_item"
                        break
                    continue
                placement = self._occurrence_placement(rr, pds[child], pds[parent])
                if placement is not None:
                    how = "cdsr"
                    break
            occ = Occurrence(i, parent, child, name, placement, how)
            occurrences.append(occ)
            if placement is None:
                waiting.append((occ, shared))
        # an occurrence with no placement of its own takes a mapped item of the same pair, the
        # pair's mapped items in order (a cursor each, not a list shortened from its front)
        taken: dict[tuple[int, int], int] = defaultdict(int)
        for occ, shared in waiting:
            pair = (occ.parent, occ.child)
            got = pending_mapped.get(pair)
            if got and taken[pair] < len(got):
                pl, item, _name = got[taken[pair]]
                taken[pair] += 1
                occ.placement, occ.how = pl, "mapped_item"
                used_items.add(item)
            elif shared:
                occ.placement, occ.how = IDENTITY, "cdsr"
            else:
                unresolved += 1
        # mapped items left over: the same occurrence twice when one sits where an occurrence
        # of the pair already is, else further occurrences (counted as ambiguous when the
        # pair also has occurrences placed by their own relationships)
        own: dict[tuple[int, int], list[Placement]] = defaultdict(list)
        for o in occurrences:
            if o.how == "cdsr" and o.placement is not None:
                own[(o.parent, o.child)].append(o.placement)
        ambiguous = 0
        for (parent, child), rest in pending_mapped.items():
            placed = own.get((parent, child))
            index = _PlacementIndex(placed) if placed else None
            for pl, item, name in rest[taken.get((parent, child), 0) :]:
                self.tick()
                if item in used_items:
                    continue
                if index is not None and index.take(pl):
                    continue
                if placed is not None:
                    ambiguous += 1
                occurrences.append(Occurrence(item, parent, child, name, pl, "mapped_item"))
        children = {o.child for o in occurrences}
        roots = [pd for pd in pds if pd not in children]
        if not roots and pds:  # every product is inside another: a cycle, entered at the first
            roots = [min(pds)]
        orphans = False
        if not any(d.items for d in pds.values()) and not occurrences:
            orphan = self._orphans(set(owner))
            if orphan is not None:
                pds[orphan.pd] = orphan
                roots = [orphan.pd]
                orphans = True
        parents = {o.parent for o in occurrences}
        used = [r for r in roots if pds[r].items or r in parents]
        if used:
            roots = used
        return Structure(
            pds, occurrences, roots, dict(self.skipped), orphans, unresolved, self.rep_cycles, ambiguous
        )

    def _pd(self, i: int) -> ProductDef:
        r = self.p.record(i)
        prm = r.part("PRODUCT_DEFINITION") or r.params
        d = ProductDef(i)
        d.description = _text(prm[1]) if len(prm) >= 2 else None
        pdf = self.rec(prm[2]) if len(prm) >= 3 else None
        if pdf is not None:
            fp = pdf.params
            prod = self.rec(fp[2]) if len(fp) >= 3 else None
            if prod is not None and prod.has("PRODUCT"):
                pp = prod.part("PRODUCT") or prod.params
                d.product = prod.id
                d.id_text = _text(pp[0]) if pp else None
                d.name = _text(pp[1]) if len(pp) >= 2 else None
                if d.description is None and len(pp) >= 3:
                    d.description = _text(pp[2])
        return d

    def _context(self, rep: int) -> Context:
        r = self.rec(Ref(rep))
        if r is None:
            return ASSUMED
        return self.units.of(r)

    def _relationship(self, i: int) -> tuple[int, int, Any] | None:
        """``(rep_1, rep_2, transformation or None)`` of a representation relationship,
        read once."""
        if i in self._rel:
            return self._rel[i]
        got = self._read_relationship(i)
        self._rel[i] = got
        return got

    def _read_relationship(self, i: int) -> tuple[int, int, Any] | None:
        r = self.p.record(i)
        base = r.part("REPRESENTATION_RELATIONSHIP")
        if base is None:
            base = r.params if not r.complex else None
        if base is None or len(base) < 4 or not isinstance(base[2], Ref) or not isinstance(base[3], Ref):
            return None
        t = None
        rrwt = r.part("REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION")
        if rrwt:
            t = rrwt[0] if r.complex else (rrwt[4] if len(rrwt) >= 5 else None)
        return int(base[2]), int(base[3]), t

    # -- geometry of one product ------------------------------------------------------------
    def _collect(
        self, pd: int, rep: int, placement: Placement, d: ProductDef, walk: _Walk, path: set[int]
    ) -> None:
        """The items of ``rep`` and of the representations it leads to, placed in the
        product's frame. A representation is walked once for each placement it is reached
        at, so a dense graph of relationships costs its links, not its paths."""
        self.tick()
        if rep in path:  # only a mapped item can lead back to a representation on the path
            self.rep_cycles += 1
            return
        key = (rep, _key(placement))
        if key in walk.visited:
            return
        if len(path) >= MAX_REP_DEPTH or walk.visits >= MAX_VISITS:
            self.skipped["depth"] += 1
            return
        walk.visited.add(key)
        walk.visits += 1
        r = self._readable(Ref(rep))
        if r is None:
            return
        path = path | {rep}
        ctx = self.units.of(r)
        items = r.params[1] if len(r.params) >= 2 and isinstance(r.params[1], list) else []
        for it in items:
            self.tick()
            rec = self._readable(it)
            if rec is None:
                continue
            t = rec.types
            if rec.has("MAPPED_ITEM"):
                self._mapped(pd, rec, ctx, placement, d, walk, path)
                continue
            seen = walk.seen
            if any(s in t for s in SOLIDS):
                self._add(d, seen, Item(rec.id, "solid", ctx, placement))
            elif rec.has("SHELL_BASED_SURFACE_MODEL"):
                prm = rec.params
                for shell in prm[1] if len(prm) >= 2 and isinstance(prm[1], list) else []:
                    if isinstance(shell, Ref):
                        self._add(d, seen, Item(int(shell), "sheet", ctx, placement, rec.id))
            elif any(s in t for s in SHELL_ITEMS):
                kind = "solid" if ("CLOSED_SHELL" in t or "ORIENTED_CLOSED_SHELL" in t) else "sheet"
                self._add(d, seen, Item(rec.id, kind, ctx, placement))
            elif any(s in t for s in FACETED):
                self._add(d, seen, Item(rec.id, "faceted", ctx, placement))
            elif any(s in t for s in TESSELLATED):
                self._add(d, seen, Item(rec.id, "tessellated", ctx, placement))
            elif not any(s in t for s in IGNORED_ITEMS):
                self.skipped[t[0] if not rec.complex else "complex"] += 1
        for rr, other, is_rep_1 in self._links.get(rep, []):
            self.tick()
            if other in path:
                continue  # the way back along a relationship, not a cycle
            owner = self._owner.get(other)
            if owner is not None and owner != pd:
                continue  # another product's shape: an occurrence places it, not this
            got = self._relationship(rr)
            if got is None:
                continue
            rep_1, rep_2, t = got
            step = IDENTITY
            if t is not None:
                m = self._transformation(t, rep_1, rep_2)
                if m is None:
                    self.skipped["transformation"] += 1
                    continue
                # m takes rep_1's coordinates to rep_2's
                step = m if not is_rep_1 else inverse(m)
            self._collect(pd, other, placement.then(step), d, walk, path)

    def _add(self, d: ProductDef, seen: set, item: Item) -> None:
        key = (item.rid, _key(item.placement))  # a set, so a wide product is not quadratic
        if key in seen:
            return
        seen.add(key)
        d.items.append(item)

    def _mapped(self, pd, rec: Record, ctx: Context, placement, d, walk: _Walk, path) -> None:
        got = self._mapping(rec, ctx)
        if got is None:
            return
        target_rep, m = got
        owner = self._owner.get(target_rep)
        if owner is not None and owner != pd:
            walk.mapped.append((pd, owner, placement.then(m), rec.id, _text(rec.params[0])))
            return
        self._collect(pd, target_rep, placement.then(m), d, walk, path)

    def _mapping(self, rec: Record, ctx: Context) -> tuple[int, Placement] | None:
        """A MAPPED_ITEM's mapped representation, and the placement that takes it into the
        representation holding the item (whose context is ``ctx``)."""
        prm = rec.params
        if len(prm) < 3:
            return None
        source = self.rec(prm[1])
        if source is None or not source.has("REPRESENTATION_MAP"):
            return None
        sp = source.params
        if len(sp) < 2 or not isinstance(sp[1], Ref):
            return None
        target_rep = int(sp[1])
        try:
            origin = self._item_placement(sp[0], self._context(target_rep))
            target = self._item_placement(prm[2], ctx)
            return target_rep, target.then(inverse(origin))
        except Unsupported:
            self.skipped["transformation"] += 1
            return None

    def _mapped_beside(
        self, got: tuple[int, int, Any], child: ProductDef, parent: ProductDef, used: set[int]
    ) -> Placement | None:
        """The placement of an occurrence whose relationship has no transformation: the
        first mapped item not yet used, in the order stored, that maps the child and is held
        by one of the relationship's two representations that is neither the parent's nor
        the child's, or None. A representation that holds the mapped items of many
        occurrences is read once, not once for each of them (:class:`_Beside`)."""
        mine = self._child_reps(child)
        theirs = self._child_reps(parent)
        for rep in got[:2]:
            if rep in mine or rep in theirs:
                continue
            beside = self._beside_of(rep)
            if beside is None:
                continue
            placement = self._beside_take(beside, mine, used)
            if placement is not None:
                return placement
        return None

    def _beside_of(self, rep: int) -> _Beside | None:
        if rep not in self._beside:
            r = self.rec(Ref(rep))
            if r is not None and len(r.params) >= 2 and isinstance(r.params[1], list):
                self._beside[rep] = _Beside(r.params[1], self.units.of(r))
            else:
                self._beside[rep] = None
        return self._beside[rep]

    def _beside_take(self, b: _Beside, mine: set[int], used: set[int]) -> Placement | None:
        """The placement of the first mapped item of ``b`` not in ``used`` that maps one of
        ``mine``, which is then used. Those read already come first: any not yet read lies
        after them."""
        best: deque | None = None
        targets = mine if len(mine) < len(b.found) else list(b.found)
        for target in targets:
            queue = b.found.get(target)
            if not queue or target not in mine:
                continue
            while queue and queue[0][1] in used:
                queue.popleft()
            if queue and (best is None or queue[0][0] < best[0][0]):
                best = queue
        if best is not None:
            _at, item, placement = best.popleft()
            used.add(item)
            return placement
        while b.at < len(b.items):
            at = b.at
            b.at += 1
            self.tick()
            rec = self.rec(b.items[at])
            if rec is None or not rec.has("MAPPED_ITEM") or rec.id in used:
                continue
            m = self._mapping(rec, b.ctx)
            if m is None:
                continue
            if m[0] in mine:
                used.add(rec.id)
                return m[1]
            b.found.setdefault(m[0], deque()).append((at, rec.id, m[1]))
        return None

    def _item_placement(self, ref: Any, ctx: Context) -> Placement:
        """The placement of an axis placement or a Cartesian transformation operator."""
        r = self.rec(ref)
        if r is None:
            raise Unsupported("bad_reference", "", "a placement is missing")
        if r.has("CARTESIAN_TRANSFORMATION_OPERATOR_3D") or r.has("CARTESIAN_TRANSFORMATION_OPERATOR"):
            return self._operator(r, ctx)
        return frame_placement(self.g.frame(ref, ctx.length_m))

    def _operator(self, r: Record, ctx: Context) -> Placement:
        """A CARTESIAN_TRANSFORMATION_OPERATOR_3D: axis1, axis2, local_origin, scale and
        axis3, with ISO 10303-42's ``base_axis`` defaults."""
        # A simple instance lists the inherited names first (representation_item's, then
        # functionally_defined_transformation's name and description): its last five are
        # axis1, axis2, local_origin, scale and axis3. A complex one keeps them by record.
        if r.complex:
            base = r.part("CARTESIAN_TRANSFORMATION_OPERATOR") or []
            three = r.part("CARTESIAN_TRANSFORMATION_OPERATOR_3D") or []
            vals = list(base[-4:]) + [three[0] if three else None]
        elif r.has("CARTESIAN_TRANSFORMATION_OPERATOR_3D"):
            vals = list(r.params[-5:])
        else:
            vals = list(r.params[-4:]) + [None]
        # vals: axis1, axis2, local_origin, scale[, axis3]
        while len(vals) < 5:
            vals.append(None)
        a1 = self.g.direction(vals[0]) if isinstance(vals[0], Ref) else None
        a2 = self.g.direction(vals[1]) if isinstance(vals[1], Ref) else None
        a3 = self.g.direction(vals[4]) if isinstance(vals[4], Ref) else None
        origin = self.g.point(vals[2], ctx.length_m) if isinstance(vals[2], Ref) else (0.0, 0.0, 0.0)
        raw = vals[3].value if isinstance(vals[3], Typed) else vals[3]
        scale = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else 1.0
        z = a3 or (0.0, 0.0, 1.0)
        x = perpendicular(z, a1)
        y = (z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0])
        if a2 is not None:
            d = y[0] * a2[0] + y[1] * a2[1] + y[2] * a2[2]
            if d < 0:
                y = (-y[0], -y[1], -y[2])  # a left-handed operator: kept, and warned by the scene
        s = scale if math.isfinite(scale) and scale > 0 else 1.0
        rot = ((x[0] * s, y[0] * s, z[0] * s), (x[1] * s, y[1] * s, z[1] * s), (x[2] * s, y[2] * s, z[2] * s))
        return Placement(rot, origin)

    def _transformation(self, t: Any, rep_1: int, rep_2: int) -> Placement | None:
        """The placement that takes ``rep_1``'s coordinates to ``rep_2``'s."""
        r = self.rec(t)
        if r is None:
            return None
        try:
            if r.has("ITEM_DEFINED_TRANSFORMATION"):
                prm = r.part("ITEM_DEFINED_TRANSFORMATION") or r.params
                if len(prm) < 4:
                    return None
                f1 = self._item_placement(prm[2], self._context(rep_1))
                f2 = self._item_placement(prm[3], self._context(rep_2))
                return f2.then(inverse(f1))
            if r.has("CARTESIAN_TRANSFORMATION_OPERATOR_3D") or r.has("CARTESIAN_TRANSFORMATION_OPERATOR"):
                return self._operator(r, self._context(rep_2))
        except Unsupported:
            return None
        return None

    def _child_reps(self, d: ProductDef) -> set[int]:
        """A product's representations and those sharing their space (no transformation),
        found once for each product."""
        cached = self._child_cache.get(d.pd)
        if cached is not None:
            return cached
        out: set[int] = set()
        self._child_cache[d.pd] = out
        todo = list(d.reps)
        while todo and len(out) < CHILD_REPS:
            rep = todo.pop()
            if rep in out:
                continue
            out.add(rep)
            for rr, other, _is1 in self._links.get(rep, []):
                self.tick()
                got = self._relationship(rr)
                if got is not None and got[2] is None and other not in out:
                    owner = self._owner.get(other)
                    if owner is None or owner == d.pd:
                        todo.append(other)
        return out

    def _occurrence_placement(self, rr: int, child: ProductDef, parent: ProductDef) -> Placement | None:
        """The child's placement in the parent by a relationship with a transformation."""
        got = self._relationship(rr)
        if got is None or got[2] is None:
            return None
        rep_1, rep_2, t = got
        m = self._transformation(t, rep_1, rep_2)
        if m is None:
            return None
        mine = self._child_reps(child)
        if rep_1 in mine and rep_2 not in mine:
            return m
        if rep_2 in mine and rep_1 not in mine:
            return inverse(m)
        theirs = self._child_reps(parent)
        if rep_2 in theirs:
            return m
        if rep_1 in theirs:
            return inverse(m)
        return m  # the usual order: rep_1 the child's

    # -- representations no product names -------------------------------------------------
    def _orphans(self, owned: Iterable[int]) -> ProductDef | None:
        """One product holding the geometry of every shape representation, when no product
        definition leads to any (a file with no product structure)."""
        d = ProductDef(-1)
        walk = _Walk()
        for t in (
            "ADVANCED_BREP_SHAPE_REPRESENTATION",
            "MANIFOLD_SURFACE_SHAPE_REPRESENTATION",
            "FACETED_BREP_SHAPE_REPRESENTATION",
            "SHAPE_REPRESENTATION",
            "TESSELLATED_SHAPE_REPRESENTATION",
        ):
            for rep in self.p.ids_of_type(t):
                self._collect(-1, rep, IDENTITY, d, walk, set())
        if not d.items:
            return None
        d.ctx = d.items[0].ctx
        return d


__all__ = ["Item", "Occurrence", "ProductDef", "Reader", "Structure", "frame_placement", "inverse"]
