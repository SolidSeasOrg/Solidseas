"""STEP files (ISO 10303-21 exchange structures of AP203, AP214 and AP242) read as model
documents (provisional, ``docs/formats/step.md`` and ``docs/API.md`` 3.20.7).

:func:`open` is the registry's reader for ``step``. A :class:`StepDocument` reads
its head from the header section and one pass of entity names over the data
section (:func:`.schema.census`): the variant, the fields, the writing program,
whether it is an assembly, what it holds and its length unit. A full read
(``tree``, ``scene``, ``bodies``) indexes the file (:mod:`.part21`), builds its
product structure and placements (:mod:`.product`), its units (:mod:`.units`) and
colours (:mod:`.presentation`), and plans its objects: one mesh object for each
solid, each shell of a surface model, each faceted B-rep and each tessellated
item, placed once for every occurrence that reaches it.

B-rep objects are built as Parasolid bodies in memory (:mod:`.geometry`,
:mod:`.builder`) and drawn by SolidSeas' tessellator, so ``scene()`` holds
triangles with ``source`` ``bodies`` and ``bodies()`` the transmits; faceted and
tessellated items are meshes as stored (:mod:`.tessellated`, ``source`` ``mesh``).

Modules: :mod:`.part21` (the exchange structure), :mod:`.schema` (variant and
census), :mod:`.units`, :mod:`.product`, :mod:`.geometry`, :mod:`.builder`,
:mod:`.tessellated`, :mod:`.presentation` and :mod:`.properties`. Nothing here
writes a file or opens another one: a STEP file's external document references
are reported by ``references()``, never followed.
"""

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from ...errors import FormatNotSupportedError, SldFormatError, SldLimitError
from .._source import Clock, SafeZip, Source
from ..base import (
    BodyRef,
    ExternalReference,
    ModelDocument,
    ModelNode,
    ModelTree,
    SceneBuilder,
    _stem,
    make_property,
)
from ..solidworks.components import IDENTITY
from . import part21, properties, schema
from .geometry import MappedBody, Mapper, Unsupported
from .orient import orient_faces, orient_shells
from .part21 import Ref
from .presentation import Colours
from .product import Item, Occurrence, Reader, Structure
from .units import Units

REVISION = 1
ZIP_MAGIC = b"PK\x03\x04"
STEP_EXTENSIONS = (".step", ".stp", ".p21")


def _starts_as_step(z: SafeZip, name: str) -> bool:
    """Whether a zip member's first bytes are a Part 21 file's."""
    for chunk in z.iter_member(name, max_bytes=1 << 16):
        return chunk.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(part21.MAGIC)
    return False


CHORD_FRACTION = 1e-3  # of the model's box diagonal, as the tessellator's own default
CHORD_MIN, CHORD_MAX = 1e-6, 1e-3
BREP_KINDS = ("solid", "sheet")


@dataclass
class _Object:
    """One planned scene object: the item it draws, its product, name, colour and the tree
    node of its first appearance."""

    item: Item
    pd: int
    name: str | None
    color: tuple | None
    node: str
    mixed_colours: bool = False


@dataclass
class _Plan:
    """The tree (its first ``tree_nodes`` nodes), the objects, and how many items and
    components the occurrence paths place. The scene walks the paths again to place
    its items, so no path is kept."""

    nodes: list[ModelNode] = field(default_factory=list)
    objects: list[_Object] = field(default_factory=list)
    object_of: dict[tuple[int, str], int] = field(default_factory=dict)
    items: int = 0
    components: int = 0
    cycles: int = 0
    truncated: bool = False
    too_many: bool = False  # more items than limits.items, or more products reached than it allows
    cut: bool = False  # the walk stopped at its bound of products reached


@dataclass
class _Model:
    p21: part21.Part21
    units: Units
    structure: Structure
    colours: Colours
    plan: _Plan
    mapper: Mapper
    children: dict[int, list[Occurrence]]
    mapped: dict[int, MappedBody] = field(default_factory=dict)


def _readable(mapper: Mapper, rid: int):
    """The record ``rid``, or None when it is missing or cannot be parsed (the scene
    then says why)."""
    try:
        return mapper.p.get(Ref(rid))
    except SldLimitError:
        raise
    except SldFormatError:
        return None


def _time_up(exc: SldLimitError, clock: Clock) -> bool:
    """Whether ``exc`` is ``clock`` running out, rather than another bound."""
    left = clock.left()
    return (exc.detail or {}).get("limit") == clock.limit and left is not None and left <= 0


class StepDocument(ModelDocument):
    """One STEP file (see the module notes)."""

    format = "step"

    def __init__(self, source, *, name, path, file_info, limits, detection=None) -> None:
        super().__init__(
            source, name=name, path=path, file_info=file_info, limits=limits, detection=detection
        )
        if source.head(4) == ZIP_MAGIC:
            source = self._unzip(source)
        head = source.read_upto(0, limits.p21_header_bytes + 4096)
        self.header = part21.read_header(head, limits, complete=len(head) >= source.size)
        schema.refuse_private(self.header.schemas)
        self.variant = schema.variant(self.header.schemas)
        container = self.properties
        self.fields, self.properties, self.application = properties.head(self.header, limits, self.warnings)
        self.properties = container + self.properties
        self.census = schema.census(source, self.header.data_offset, limits, Clock(limits.seconds))
        c = self.census
        self.doc_type = "assembly" if c.assembly else "part"
        self.kind = "mixed" if c.brep and c.mesh else ("mesh" if c.mesh else "brep")
        if c.length_m is not None:
            self._set_scale(c.length_m, "file")
        else:
            self.set_units("mm", "assumed")
            self._assumed()
        self._model: _Model | None = None

    # -- head ----------------------------------------------------------------------------
    def _unzip(self, outer: Source) -> Source:
        """The exchange structure inside a zip archive (ISO 10303-21's compressed form, a
        ``.stpZ`` or a zipped ``.step``): its one member named as a STEP file, or its one
        member that starts as one, inflated within the zip bounds and
        ``whole_read_bytes``. The archive's handle is closed once it is read."""
        lim = self.limits
        z = SafeZip(outer, lim, Clock(lim.seconds))
        try:
            names = [n for n in z.names() if not n.endswith("/")]
            named = [n for n in names if n.lower().endswith(STEP_EXTENSIONS)]
            if len(named) != 1:
                named = [n for n in names if _starts_as_step(z, n)]
            if len(named) != 1:
                raise FormatNotSupportedError(
                    "the zip archive does not hold exactly one STEP file",
                    detail={"rule": "archive", "value": "zip"},
                )
            data = z.read(named[0], max_bytes=lim.whole_read_bytes)
        finally:
            z.close()
        outer.close()
        inner = Source(data)
        self._source = inner
        self.properties = [make_property("container", "zip")]
        return inner

    def _set_scale(self, scale_m: float, source: str) -> None:
        from .units import length_token

        token = length_token(scale_m)
        if token is not None:
            self.set_units(token, source)
        else:  # a unit with no token (a yard, a nanometre): its scale is still known
            self.units = {"length": None, "scale_m": scale_m, "source": source}

    def _assumed(self) -> None:
        if not any(w.code == "units_assumed" for w in self.warnings):
            self.warn("units_assumed", "the file states no unit of length; millimetres were assumed")

    def _counts(self) -> dict[str, int | None]:
        if self._model is not None:
            plan = self._model.plan
            bodies = sum(1 for o in plan.objects if o.item.kind in BREP_KINDS)
            return {
                "objects": len(plan.objects),
                "items": plan.items,
                "bodies": bodies,
                "faces": self.census.names["ADVANCED_FACE"] + self.census.names["FACE_SURFACE"],
                "components": plan.components,
                "references": self.census.names["DOCUMENT_FILE"],
            }
        n = self.census.names
        return {
            "bodies": self.census.brep + n["FACETED_BREP"],
            "faces": n["ADVANCED_FACE"] + n["FACE_SURFACE"],
            "components": n["NEXT_ASSEMBLY_USAGE_OCCURRENCE"],
            "references": n["DOCUMENT_FILE"],
        }

    # -- the full read ---------------------------------------------------------------------
    def _load(self, clock: Clock) -> _Model:
        if self._model is not None:
            return self._model
        lim = self.limits
        p21 = part21.open(self.source, limits=lim, clock=clock)
        units = Units(p21)
        structure = Reader(p21, units, lim, clock).read()
        colours = Colours(p21, lim, clock)
        mapper = Mapper(p21, lim, clock)
        children: dict[int, list[Occurrence]] = defaultdict(list)
        for occ in structure.occurrences:
            children[occ.parent].append(occ)
        plan = self._plan(structure, children, colours, mapper, clock)
        model = _Model(p21, units, structure, colours, plan, mapper, dict(children))
        self._model = model
        self._after_load(model)
        return model

    def _after_load(self, m: _Model) -> None:
        s, plan = m.structure, m.plan
        roots = [s.pds[r] for r in s.roots if r in s.pds]
        ctx = next((d.ctx for d in roots if d.ctx is not None), None)
        if ctx is not None:
            if ctx.assumed:
                self.set_units("mm", "assumed")
                self._assumed()
            else:
                self._set_scale(ctx.length_m, "file")
                self.warnings = [w for w in self.warnings if w.code != "units_assumed"]
        self.doc_type = "assembly" if plan.components else "part"
        kinds = {o.item.kind for o in plan.objects}
        has_brep = bool(kinds & set(BREP_KINDS))
        has_mesh = bool(kinds - set(BREP_KINDS))
        if plan.objects:
            self.kind = "mixed" if has_brep and has_mesh else ("mesh" if has_mesh else "brep")
        if len(roots) == 1:
            root = roots[0]
            if root.label and self.fields.title is None:
                from dataclasses import replace

                self.fields = replace(self.fields, title=root.label)
            self.properties = self.properties + properties.product(root, self.limits, self.warnings)
            owners = {root.pd}
            for i in m.p21.ids_of_type("PRODUCT_DEFINITION_SHAPE"):
                r = m.p21.record(i)
                prm = r.params
                if len(prm) >= 3 and prm[2] == root.pd:
                    owners.add(i)
            self.properties = self.properties + properties.user_defined(
                m.p21, owners, self.limits, self.warnings
            )
        skipped = sum(s.skipped_items.values())
        if skipped:
            what = ", ".join(f"{k} {n}" for k, n in sorted(s.skipped_items.items())[:8])
            self.warn("representation_skipped", f"{skipped} representation items are not drawn ({what})")
        if s.unresolved:
            self.warn(
                "placement_unresolved",
                f"{s.unresolved} assembly occurrences have no usable placement and are placed at the origin",
            )
        if s.ambiguous:
            self.warn(
                "placement_ambiguous",
                f"{s.ambiguous} mapped items place a component whose occurrences already have placements "
                "of their own; each is kept as a further occurrence",
            )
        if plan.cycles or s.rep_cycles:
            self.warn(
                "assembly_cycle",
                f"{plan.cycles + s.rep_cycles} product or representation references lead back to themselves "
                "and were not followed again",
            )
        mixed = sum(1 for o in plan.objects if o.mixed_colours)
        if mixed:
            self.warn(
                "colors_ignored",
                f"{mixed} bodies have faces of several colours; each is drawn in its most common one",
            )

    def _walk(self, s: Structure, children: dict[int, list[Occurrence]], clock: Clock | None, place: bool):
        """The occurrence paths in tree order, parents before children: ``("node", id,
        parent id, name, kind, own placement)`` for each product reached, ``("item", id,
        node id, product, item, placement)`` for each of its items, ``("cycle",)`` and
        ``("deep",)`` where an occurrence is not followed, and ``("cut",)`` when
        ``items`` plus ``tree_nodes`` products have been reached. Item placements are in
        the root's frame when ``place``, else None. The same structure always gives the
        same ids, so the scene's items name the tree's nodes."""
        lim = self.limits
        cap = lim.items + lim.tree_nodes
        stem = _stem(self.name)
        n = 0  # ids given
        reached = 0  # products reached
        # (product, placement, parent node, name, kind, own placement, path, depth)
        stack: list[tuple] = []
        for r in reversed(s.roots):
            d = s.pds[r]
            stack.append(
                (r, IDENTITY if place else None, None, d.label or stem, None, None, frozenset((r,)), 1)
            )
        while stack:
            if clock is not None:
                clock.tick()
            if reached >= cap:
                yield ("cut",)
                return
            pd, placement, parent, name, kind, own, path, depth = stack.pop()
            d = s.pds[pd]
            reached += 1
            n += 1
            nid = str(n)
            if kind is None:
                kind = "assembly" if children.get(pd) else "object"
            yield ("node", nid, parent, name, kind, own)
            for item in d.items:
                if clock is not None:
                    clock.tick()
                n += 1
                yield ("item", str(n), nid, pd, item, placement.then(item.placement) if place else None)
            for occ in reversed(children.get(pd, [])):
                if occ.child in path:
                    yield ("cycle",)
                    continue
                if depth >= lim.depth:
                    yield ("deep",)
                    continue
                pl = occ.placement or IDENTITY
                stack.append(
                    (
                        occ.child,
                        placement.then(pl) if place else None,
                        nid,
                        occ.name or s.pds[occ.child].label,
                        "component",
                        pl,
                        path | {occ.child},
                        depth + 1,
                    )
                )

    def _plan(
        self,
        s: Structure,
        children: dict[int, list[Occurrence]],
        colours: Colours,
        mapper: Mapper,
        clock: Clock | None = None,
    ) -> _Plan:
        """The tree's first ``tree_nodes`` nodes, every object (on its first appearance)
        and the counts, from one walk of the occurrence paths that keeps no path."""
        plan = _Plan()
        lim = self.limits
        stem = _stem(self.name)
        for ev in self._walk(s, children, clock, False):
            tag = ev[0]
            if tag == "node":
                _tag, nid, parent, name, kind, own = ev
                if kind == "component":
                    plan.components += 1
                if len(plan.nodes) < lim.tree_nodes:
                    plan.nodes.append(ModelNode(nid, parent, name, kind, None, None, own, None))
                else:
                    plan.truncated = True
            elif tag == "item":
                _tag, bid, nid, pd, item, _placement = ev
                key = (item.rid, item.kind)
                k = plan.object_of.get(key)
                if k is None:
                    colour, mixed = self._colour(item, colours, mapper)
                    k = plan.object_of[key] = len(plan.objects)
                    name = self._item_name(item, mapper) or s.pds[pd].label or stem
                    plan.objects.append(_Object(item, pd, name, colour, bid, mixed))
                plan.items += 1
                if plan.items > lim.items:
                    plan.too_many = plan.truncated = True
                    break
                if len(plan.nodes) < lim.tree_nodes:
                    obj = plan.objects[k]
                    plan.nodes.append(
                        ModelNode(bid, nid, obj.name, "body", k, None, item.placement, obj.color)
                    )
                else:
                    plan.truncated = True
            elif tag == "cycle":
                plan.cycles += 1
            elif tag == "cut":
                plan.too_many = plan.cut = plan.truncated = True
            else:
                plan.truncated = True
        return plan

    def _item_name(self, item: Item, mapper: Mapper) -> str | None:
        rec = _readable(mapper, item.rid)
        if rec is None or rec.complex or not rec.params:
            return None
        v = rec.params[0]
        if isinstance(v, str) and v.strip() and v.strip().upper() not in ("NONE", "UNKNOWN"):
            return v.strip()
        return None

    def _colour(self, item: Item, colours: Colours, mapper: Mapper) -> tuple[tuple | None, bool]:
        """A body's colour: its own style, its shell's or its surface model's, else the most
        common colour of its faces (and whether its faces had several)."""
        for rid in (item.rid, item.sbsm):
            if rid is not None and colours.get(rid) is not None:
                return colours.get(rid), False
        if not colours.by_item:
            return None, False
        shells: list[Any] = []
        rec = _readable(mapper, item.rid)
        if rec is None:
            return None, False
        if item.kind == "solid" and (rec.has("MANIFOLD_SOLID_BREP") or rec.has("BREP_WITH_VOIDS")):
            prm = rec.params
            if len(prm) >= 2:
                shells.append(prm[1])
        elif item.kind == "faceted":
            prm = rec.params
            if len(prm) >= 2:
                shells.append(prm[1])
        else:
            shells.append(Ref(item.rid))
        votes: Counter = Counter()
        for sh in shells:
            if isinstance(sh, Ref) and colours.get(int(sh)) is not None:
                return colours.get(int(sh)), False
            try:
                faces = mapper.faces_of(sh, False)
            except SldLimitError:
                raise
            except (Unsupported, SldFormatError):  # a damaged shell: the scene will say why
                continue
            for f, _flip in faces:
                c = colours.get(f)
                if c is not None:
                    votes[c] += 1
        if not votes:
            return None, False
        return votes.most_common(1)[0][0], len(votes) > 1

    # -- hooks -------------------------------------------------------------------------------
    def _tree(self, clock: Clock) -> ModelTree:
        m = self._load(clock)
        return ModelTree(tuple(m.plan.nodes), m.plan.truncated)

    def _mapped(self, m: _Model, k: int) -> MappedBody:
        got = m.mapped.get(k)
        if got is None:
            obj = m.plan.objects[k]
            got = m.mapped[k] = m.mapper.body(obj.item.rid, obj.item.ctx, kind=obj.item.kind, name=obj.name)
        return got

    def _bodies(self, clock: Clock) -> list[BodyRef]:
        m = self._load(clock)
        m.mapper.clock = clock
        out = []
        for k, obj in enumerate(m.plan.objects):
            if obj.item.kind not in BREP_KINDS:
                continue
            mb = self._mapped(m, k)
            if mb.transmit is not None:
                out.append(BodyRef(obj.name, mb.transmit, obj.color, obj.node, mb.kind))
        return out

    def part_bodies(
        self, max_seconds: float = 30.0
    ) -> tuple[list[tuple[str | None, BodyRef | None, int]], bool, int]:
        """What the STEP export needs to write the file as one part: each B-rep body as
        ``(name, body, faces left out)`` (body None when none of its faces could be built),
        whether every B-rep item lies once, at the identity, in the frame of the products
        holding them (so that its bodies are one part's), and how many faceted and
        tessellated items the file holds (triangles, which no B-rep body carries)."""
        from ..solidworks.components import IDENTITY as ORIGIN
        from .product import _same

        clock = Clock(max_seconds)
        m = self._load(clock)
        m.mapper.clock = clock
        if m.plan.too_many:
            raise self.limits.exceeded("items", f"the model places more than {self.limits.items:,} items")
        in_place = m.plan.components == 0
        placed: Counter = Counter()
        for ev in self._walk(m.structure, m.children, clock, True):
            if ev[0] != "item" or ev[4].kind not in BREP_KINDS:
                continue
            placed[(ev[4].rid, ev[4].kind)] += 1
            if not _same(ev[5], ORIGIN):
                in_place = False
        if any(n > 1 for n in placed.values()):
            in_place = False
        out = []
        for k, obj in enumerate(m.plan.objects):
            if obj.item.kind not in BREP_KINDS:
                continue
            mb = self._mapped(m, k)
            ref = (
                None if mb.transmit is None else BodyRef(obj.name, mb.transmit, obj.color, obj.node, mb.kind)
            )
            out.append((obj.name, ref, max(len(mb.skipped), 1) if ref is None else len(mb.skipped)))
        meshes = sum(1 for o in m.plan.objects if o.item.kind not in BREP_KINDS)
        return out, in_place, meshes

    def _references(self, clock: Clock) -> list[ExternalReference]:
        m = self._load(clock)
        out = []
        for i in m.p21.ids_of_type("DOCUMENT_FILE"):
            r = m.p21.record(i)
            prm = r.part("DOCUMENT_FILE") or r.params
            stored = next((v for v in prm[:2] if isinstance(v, str) and v.strip()), None) if prm else None
            name = stored.replace("\\", "/").rsplit("/", 1)[-1] if stored else None
            out.append(ExternalReference(f"#{i}", "component", stored, name))
        return out

    def _scene(self, sb: SceneBuilder) -> None:
        m = self._load(sb.clock)
        m.mapper.clock = sb.clock
        opts = sb.options
        plan = m.plan
        if plan.too_many:
            lim = self.limits
            if plan.cut:
                raise lim.exceeded(
                    "items", f"the assembly reaches more than {lim.items + lim.tree_nodes:,} products"
                )
            raise lim.exceeded("items", f"the model places more than {lim.items:,} items")
        from ...tessellate import SkippedFace, check_warnings

        # map every body first: the chord tolerance comes from the whole model's box. The
        # time limit, reached here or later, leaves the bodies not done out (max_seconds)
        time_up = False
        boxes = []
        for k, obj in enumerate(plan.objects):
            if obj.item.kind in BREP_KINDS and obj.item.kind in opts.body_types:
                try:
                    mb = self._mapped(m, k)
                except SldLimitError as exc:
                    if not _time_up(exc, sb.clock):
                        raise
                    time_up = True
                    break
                if mb.box is not None:
                    boxes.append(mb.box)
        chord = opts.chord_m
        if chord is None:
            fraction = opts.chord_fraction or CHORD_FRACTION
            high = opts.max_chord_m or CHORD_MAX
            if boxes:
                lo = [min(b[0][i] for b in boxes) for i in range(3)]
                hi = [max(b[1][i] for b in boxes) for i in range(3)]
                chord = min(max(math.dist(lo, hi) * fraction, CHORD_MIN), high)
            else:
                chord = min(1e-4, high)
        counts: Counter = Counter()
        left_out: set[int] = set()  # bodies of a type not asked for: not placed
        timed_out: set[int] = set()  # objects the time limit stopped before
        incomplete = 0  # bodies the time limit left unfinished
        # what was turned round: faces to agree with their neighbours and their solids, void
        # shells and their solids, solids whose outer shell faced in
        turned: Counter = Counter()
        found: Counter = Counter()  # the self-checks' findings over every body (CHECKS)
        cap = (
            self.limits.triangles
            if opts.max_triangles is None
            else min(self.limits.triangles, opts.max_triangles + 1)
        )
        for k, obj in enumerate(plan.objects):
            item = obj.item
            if item.kind in BREP_KINDS:
                source = "bodies"
                scale = 1.0
            else:
                source, scale = "mesh", item.ctx.length_m
            builder = sb.mesh(name=obj.name, source=source, scale_m=scale, color=obj.color, node=obj.node)
            if item.kind in BREP_KINDS and item.kind not in opts.body_types:
                left_out.add(k)
                builder.finish()
                continue
            if time_up:
                incomplete += 1
                timed_out.add(k)
                builder.finish()
                continue
            try:
                if item.kind in BREP_KINDS:
                    time_up = self._draw_body(m, k, obj, builder, sb, chord, cap, counts, turned, found)
                    if time_up is None:  # no time was left to start it
                        time_up = True
                        timed_out.add(k)
                    if time_up:
                        incomplete += 1
                elif item.kind == "faceted":
                    from .tessellated import faceted

                    faces, skipped = faceted(m.p21, m.mapper, item.rid, builder, sb.clock)
                    counts["faces"] += faces
                    counts["faces_done"] += faces - len(skipped)
                    for face, entity, reason, detail in skipped:
                        sb.skipped.append(SkippedFace(obj.name or "body", face, entity, reason, detail))
                else:
                    from .tessellated import tessellated

                    n = tessellated(m.p21, item.rid, builder, sb.clock)
                    counts["faces"] += n
                    counts["faces_done"] += n
            except SldLimitError as exc:
                if not _time_up(exc, sb.clock):
                    raise
                time_up = True
                incomplete += 1
                timed_out.add(k)
                builder = sb.mesh(name=obj.name, source=source, scale_m=scale, color=obj.color, node=obj.node)
            builder.finish()
        if time_up:
            # the bodies done are placed whatever the time: their items cost no more than
            # the walk the plan already made within its own bound
            sb.clock = Clock(None, sb.clock.cancelled)
        for ev in self._walk(m.structure, m.children, sb.clock, True):
            if ev[0] != "item":
                continue
            _tag, bid, _nid, _pd, item, placement = ev
            k = plan.object_of.get((item.rid, item.kind))
            if k is None or k in left_out:
                continue
            if k in timed_out:
                sb.skip(bid, "max_seconds", "the time limit stopped the tessellation before it")
                continue
            sb.add_item(k, bid, placement)
        sb.counts.update(
            bodies=counts["bodies"],
            faces=counts["faces"],
            faces_done=counts["faces_done"],
            components=plan.components,
        )
        if left_out:
            sb.warn(
                "bodies_left_out",
                f"{len(left_out)} bodies of a type not asked for (sheets or wires) are left out",
            )
        if turned["faces"]:
            sb.warn(
                "faces_reoriented",
                f"{turned['faces']} faces of {turned['face_solids']} solids ran against their neighbours "
                "and were turned round",
            )
        if turned["voids"]:
            sb.warn(
                "void_reoriented",
                f"{turned['voids']} void shells of {turned['void_solids']} solids faced out of their voids "
                "and were turned round",
            )
        if turned["outer"]:
            sb.warn(
                "solid_reoriented",
                f"{turned['outer']} solids were inside out (their outer shell faced in) and were turned "
                "round",
            )
        for w in check_warnings(found):
            sb.warn(w.code, w.message)
        if incomplete:
            sb.warn(
                "faces_left_out",
                f"the time limit stopped the tessellation: {incomplete} bodies are not complete",
            )

    def _draw_body(
        self, m: _Model, k: int, obj: _Object, builder, sb: SceneBuilder, chord, cap, counts, turned, found
    ):
        """Map and tessellate one B-rep body into ``builder``: False when it was done, True
        when the time limit stopped its tessellation, None when no time was left to
        start it. A solid's faces are turned to agree with their neighbours and its shells
        to face the way the file's solid says (:mod:`.orient`); ``turned`` counts what was
        turned and ``found`` the self-checks' findings on what is drawn."""
        from ...tessellate import SkippedFace, checks, tessellate_transmit

        mb = self._mapped(m, k)
        counts["bodies"] += 1
        counts["faces"] += mb.faces
        for face, entity, reason, detail in mb.skipped:
            sb.skipped.append(SkippedFace(obj.name or "body", face, entity, reason, detail))
        if mb.transmit is None:
            return False
        left = sb.clock.left()
        seconds = sb.options.max_seconds if left is None else left
        # keep a margin for turning the triangles into the object: the time bound then
        # leaves the bodies done so far, rather than nothing
        seconds -= min(1.0, 0.1 * seconds)
        if seconds <= 0:
            return None
        t = tessellate_transmit(
            mb.transmit,
            chord_m=chord,
            angle_deg=sb.options.angle_deg,
            max_seconds=min(seconds, 1e6),
            max_triangles=cap,
            body_types=BREP_KINDS,
        )
        counts["faces_done"] += t.counts.get("faces_done", 0)
        for f in t.skipped:
            sb.skipped.append(SkippedFace(obj.name or "body", f.face, f.surface, f.reason, f.detail))
        positions, triangles = t.welded()
        body = dict(t.checks)
        if obj.item.kind == "solid" and triangles:
            ranges = [(f.first_triangle, f.n_triangles) for f in t.mesh.faces]
            changed = False
            if t.closed is False:
                triangles, n = orient_faces(positions, triangles, ranges, sb.clock)
                if body.get("loops_reversed"):
                    # A face whose loops ran against it kept its sense, and one too thin to
                    # tell which way its loop runs follows the loop: where faces share no
                    # edge, only points at the same place, those that disagree are found so.
                    triangles, more = orient_faces(positions, triangles, ranges, sb.clock, by_position=True)
                    n += more
                if n:
                    turned["faces"] += n
                    turned["face_solids"] += 1
                    changed = True
            # The tessellator judged the shells only of a solid that came out closed, by
            # how they nest, and not a shell that touches another so that its nesting cannot
            # be told; the file says which shell is the outside and which are voids, so a
            # solid with voids is always judged by it.
            judged = body.get("shells_inside_out") or body.get("solids_not_closed")
            if changed or judged or len(mb.shells) > 1:
                triangles, voids, outer = orient_shells(
                    positions, triangles, ranges, t.face_shells, mb.shells
                )
                if voids:
                    turned["voids"] += voids
                    turned["void_solids"] += 1
                if outer:
                    turned["outer"] += outer
                if changed or voids or outer:
                    body["solids_not_closed"] = 0 if checks.edge_use(triangles) == (0, 0) else 1
                    body["shells_inside_out"] = 0
        found.update(body)
        builder.add_vertices(positions)
        builder.add_triangles(triangles)
        return "max_seconds" in t.truncated


def open(source, *, name, path, file_info, limits, hold_open=False, detection=None) -> StepDocument:
    """Open a STEP file's :class:`~solidseas.formats._source.Source` (the registry's reader
    for ``step``)."""
    return StepDocument(source, name=name, path=path, file_info=file_info, limits=limits, detection=detection)


__all__ = ["REVISION", "StepDocument", "open"]
