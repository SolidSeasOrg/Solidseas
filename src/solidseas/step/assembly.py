"""STEP of an assembly (provisional): one product for the assembly and one for each part
it places, every instance a NEXT_ASSEMBLY_USAGE_OCCURRENCE at its placement. A
SOLIDWORKS assembly is :func:`assembly_model`, a Parasolid transmit's assemblies
:func:`transmit_assembly_model`.

The instances, their placements and the documents they are of come from
:func:`solidseas.geometry.display_geometry`, which finds an assembly's component files
as the 3D view and 3D Print do (``roots``, ``path_map``, ``allow_outside_roots``): a
part's own file, or a virtual part's document inside the assembly that stores it. Each
part and configuration is mapped once (:func:`solidseas.step._prepare`) and written once,
whatever number of instances place it; an instance places its part's origin by an
ITEM_DEFINED_TRANSFORMATION in the assembly's frame, as SOLIDWORKS writes it.

A sub-assembly the component tree lists is an assembly product of its own, its
occurrences placing its children in its frame (:class:`_Tree`); sub-assemblies of one
file and configuration placed alike share one product. A component that was not found, could not be
read, or is placed mirrored (an axis placement cannot mirror) refuses the export, unless
``allow_partial`` leaves those instances out and says so.
"""

import os
import time
from collections import Counter
from contextlib import ExitStack
from typing import Any

from ..errors import NothingToExportError, NotRepresentableError, ReaderWarning
from . import part21 as p21
from .product import AssemblyShape, Contexts, place, product

MIRROR_TOLERANCE = 1e-6  # a rotation's determinant may differ from 1 by this much
MAX_LISTED = 20  # instances named in a refusal's detail


def _is_rotation(r) -> bool:
    det = (
        r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1])
        - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
        + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0])
    )
    return abs(det - 1.0) <= MIRROR_TOLERANCE


def _inverse(p):
    from ..formats.solidworks.components import Placement

    r, t = p.rotation, p.translation_m
    rt = tuple(tuple(r[j][i] for j in range(3)) for i in range(3))
    return Placement(rt, tuple(-sum(rt[i][k] * t[k] for k in range(3)) for i in range(3)))  # type: ignore[arg-type]


def _relative(frame, placement):
    """``placement`` (in the top assembly's frame) in the frame ``frame`` places (None: the top's)."""
    return placement if frame is None else _inverse(frame).then(placement)


def _rounded(p) -> tuple:
    return (
        tuple(round(v, 9) for row in p.rotation for v in row),
        tuple(round(v, 9) for v in p.translation_m),
    )


class _Tree:
    """The sub-assemblies the instances are placed through, from the assembly's component
    tree (:func:`solidseas.model.build_components`): ``children`` maps a sub-assembly's id
    (None: the top) to its ``("part", instance)`` and ``("sub", id)`` children in order.
    A level the tree does not list (one read from a sub-assembly's own file) is not a
    product of its own: its parts are placed in the nearest sub-assembly it does list."""

    def __init__(self, doc, configuration, instances) -> None:
        from .. import model

        self.nodes: dict[str, dict] = {}
        self.files: dict[str, dict] = {}
        try:
            data = model.build_components(doc, configuration=configuration)
        except Exception:  # no tree to nest by: every part is placed in the top, as before
            data = {"children": [], "files": []}
        self.files = {f["key"]: f for f in data.get("files") or []}
        stack = list(data.get("children") or [])
        while stack:
            n = stack.pop()
            if n.get("doc_type") == "assembly" and n.get("placement") and n.get("file"):
                self.nodes[n["id"]] = n
            stack.extend(n.get("children") or [])
        self.children: dict[str | None, list[tuple[str, Any]]] = {}
        seen: set = set()
        for inst in instances:
            steps = inst.id.split("/")
            chain = [a for a in ("/".join(steps[:k]) for k in range(1, len(steps))) if a in self.nodes]
            parent = None
            for a in chain:
                if (parent, a) not in seen:
                    seen.add((parent, a))
                    self.children.setdefault(parent, []).append(("sub", a))
                parent = a
            self.children.setdefault(parent, []).append(("part", inst))

    def placement(self, ident: str):
        from ..formats.solidworks.components import Placement

        p = self.nodes[ident]["placement"]
        return Placement(tuple(tuple(r) for r in p["rotation"]), tuple(p["translation_m"]))  # type: ignore[arg-type]

    def stem(self, node: dict) -> str:
        f = self.files.get(node["file"]) or {}
        return os.path.splitext(f.get("file_name") or node.get("component") or node["name"])[0] or "assembly"


def _left_out(inst, reason: str, message: str):
    """A placed instance the STEP leaves out, as the record display_geometry gives an
    instance it could not draw."""
    from ..geometry import SkippedInstance

    return SkippedInstance(inst.id, inst.name, inst.file, reason, message, placement=inst.placement)


def _short(exc: BaseException) -> str:
    """A part's refusal in a few words, for the list of instances left out: its first
    clause, without "nothing to export: "."""
    text = str(exc).removeprefix("nothing to export: ")
    return text.split(" (", 1)[0].split("; ", 1)[0]


def _part_name(stem: str, configuration: str | None, shared: bool) -> str:
    return f"{stem} ({configuration})" if shared and configuration else stem


def assembly_model(
    doc,
    configuration: str | None,
    *,
    name: str,
    types,
    opts,
    allow_partial: bool,
    max_faces: int,
    max_entities: int,
    max_seconds: float,
    t0: float,
    originating: str,
    geometry_options: dict[str, Any],
):
    from ..formats.solidworks import open_document
    from ..geometry import display_geometry
    from . import (
        StepModel,
        StepProduct,
        _clock,
        _limit_from,
        _part_counts,
        _part_jobs,
        _prepare,
        _write_bodies,
    )

    clock = _clock(max_seconds, t0)
    g = display_geometry(
        doc,
        configuration,
        sources=("file", "brep"),
        max_brep_seconds=max_seconds,
        brep_options={"body_types": ("solid", "sheet"), "max_seconds": max_seconds},
        **geometry_options,
    )
    warnings: list[ReaderWarning] = list(g.warnings)
    skipped = list(g.skipped)
    instances = []
    for inst in g.instances:
        if not _is_rotation(inst.placement.rotation):
            skipped.append(
                _left_out(inst, "step_mirrored", "it is placed mirrored, which a STEP placement cannot hold")
            )
        else:
            instances.append(inst)

    # One product per document and configuration, in the order the instances first use them.
    def key_of(inst) -> tuple:
        src = g.meshes[inst.mesh]
        return (src.path, tuple(src.nested), inst.configuration)

    keys: dict[tuple, Any] = {}
    for inst in instances:
        keys.setdefault(key_of(inst), g.meshes[inst.mesh])
    stems: Counter = Counter()
    labels: dict[tuple, str] = {}
    for key, src in keys.items():
        f = g.files.get(src.file or "")
        stem = os.path.splitext(
            f.file_name if f is not None and f.file_name else os.path.basename(src.path or "")
        )[0]
        labels[key] = stem or "part"
        stems[labels[key]] += 1
    parts: dict[tuple, tuple[str, Any, str | None]] = {}
    refused: dict[tuple, str] = {}  # a part that cannot be written as asked: why
    for key in keys:
        path, nested, cfg = key
        label = _part_name(labels[key], cfg, stems[labels[key]] > 1)
        try:
            with ExitStack() as stack:
                # No path: a virtual part, stored in the assembly being written.
                part = doc if path is None else stack.enter_context(open_document(path))
                for stream in nested:
                    part = part.nested(stream)  # owned by its parent, which closes it
                cfg_name, jobs, part_warnings = _part_jobs(part, cfg)
                prep = _prepare(
                    jobs=jobs,
                    types=types,
                    opts=opts,
                    allow_partial=allow_partial,
                    max_faces=max_faces,
                    clock=clock,
                    warnings=part_warnings,
                    configuration=cfg_name,
                    doc=part,
                )
        except (NothingToExportError, NotRepresentableError) as exc:
            # As a part's own export: another configuration's geometry is never written in its
            # place, and a body STEP cannot hold refuses its part.
            refused[key] = _short(exc)
            continue
        warnings.extend(
            ReaderWarning(w.code, f"{label}: {w.message}", getattr(w, "stream", None)) for w in part_warnings
        )
        parts[key] = (label, prep, cfg_name)
    kept = []
    for inst in instances:
        if key_of(inst) in refused:
            skipped.append(_left_out(inst, "step_refused", refused[key_of(inst)]))
        else:
            kept.append(inst)
    reasons = [f"{s.id}: {s.message}" for s in skipped]
    instances = kept
    if not instances:
        raise NothingToExportError(
            "nothing to export: none of the assembly's instances can be written"
            + (f": {'; '.join(reasons[:3])}" if reasons else ""),
            detail={"rule": "no_instances"},
        )
    if skipped and not allow_partial:
        raise NotRepresentableError(
            f"{len(skipped)} of the assembly's instances cannot be written: {'; '.join(reasons[:3])}"
            f"{'; ...' if len(reasons) > 3 else ''}",
            detail={"rule": "instances_left_out", "value": len(skipped), "instances": reasons[:MAX_LISTED]},
        )
    unc = max(prep.uncertainty for _label, prep, _cfg in parts.values())
    w = p21.Writer(max_entities)
    try:
        ctx = Contexts(w)
        top = product(ctx, name, "assembly")
        shape = AssemblyShape(ctx, top, name, unc * p21.SCALE)
        written: dict[tuple, tuple[int, int, int]] = {}
        for key, (label, prep, _cfg) in parts.items():
            pd = product(ctx, label, "part")
            rep, origin = _write_bodies(ctx, pd, label, prep, clock)
            written[key] = (pd, rep, origin)
        placed = [(inst.id, parts[key_of(inst)][0]) for inst in instances]
        tree = _Tree(doc, g.configuration, instances)
        subs: dict[tuple, tuple[int, int, int]] = {}  # a sub-assembly's signature: its product
        sub_labels: Counter = Counter()

        def write(asm: str | None) -> tuple[tuple, tuple[int, int, int] | None]:
            """Write the sub-assembly ``asm``'s product (None: none for the top) once its
            children's exist; its signature, which an identical one shares, and its ids."""
            children = []
            for kind, child in tree.children.get(asm, []):
                clock.tick()
                if kind == "part":
                    children.append(
                        (key_of(child), child.id, child.name, child.placement, written[key_of(child)])
                    )
                else:
                    sig, ids = write(child)
                    node = tree.nodes[child]
                    children.append((sig, child, node["name"], tree.placement(child), ids))
            frame = tree.placement(asm) if asm is not None else None
            local = [(k, ident, nm, _relative(frame, pl), ids) for k, ident, nm, pl, ids in children]
            if asm is None:
                for _k, ident, nm, pl, (cpd, crep, corigin) in local:
                    shape.items.append(place(ctx, top, shape.rep, cpd, crep, corigin, pl, ident, nm))
                return (), None
            node = tree.nodes[asm]
            sig = (
                node["file"],
                node.get("configuration"),
                tuple((k, nm, _rounded(pl)) for k, _i, nm, pl, _ids in local),
            )
            if sig not in subs:
                stem = tree.stem(node)
                sub_labels[stem] += 1
                label = stem if sub_labels[stem] == 1 else f"{stem} ({sub_labels[stem]})"
                spd = product(ctx, label, "assembly")
                sub_shape = AssemblyShape(ctx, spd, label, unc * p21.SCALE)
                for _k, ident, nm, pl, (cpd, crep, corigin) in local:
                    sub_shape.items.append(place(ctx, spd, sub_shape.rep, cpd, crep, corigin, pl, ident, nm))
                sub_shape.close()
                subs[sig] = (spd, sub_shape.rep, sub_shape.items[0])
                sub_products.append(
                    StepProduct(label, "assembly", node["file"], node.get("configuration"), unc)
                )
            return sig, subs[sig]

        sub_products: list = []
        write(None)
        shape.close()
    except p21.EntityLimit as exc:
        raise _limit_from(exc) from None
    counts: Counter = Counter()
    for _label, prep, _cfg in parts.values():
        counts.update(_part_counts(prep))
    counts["products"] = 1 + len(parts) + len(sub_products)
    counts["instances"] = len(placed)
    counts["sub_assemblies"] = len(sub_products)
    left_out = counts.pop("bodies_left_out", 0)
    counts["entities"] = w.count
    counts["bodies_left_out"] = left_out
    devs = [p.deviation for _l, p, _c in parts.values() if p.deviation is not None]
    tols = [p.tolerance for _l, p, _c in parts.values() if p.tolerance is not None]
    gaps = [x for _l, p, _c in parts.values() for x in p.gaps]
    by: Counter = Counter()
    for _l, p, _c in parts.values():
        by.update(p.approximated)
    incomplete = [f"{label}: {p.incomplete}" for label, p, _c in parts.values() if p.incomplete]
    if skipped:
        incomplete.append(f"{len(skipped)} instances left out")
        warnings.append(
            ReaderWarning(
                "step_instances_left_out",
                f"{len(skipped)} of the assembly's instances are left out: {'; '.join(reasons[:3])}"
                f"{'; ...' if len(reasons) > 3 else ''}",
            )
        )
    products = (
        StepProduct(name, "assembly", None, g.configuration, unc),
        *(
            StepProduct(label, "part", key[0], cfg, prep.uncertainty)
            for key, (label, prep, cfg) in parts.items()
        ),
        *sub_products,
    )
    return StepModel(
        name=name,
        doc_type="assembly",
        configuration=g.configuration,
        products=products,
        bodies=tuple(r for _l, p, _c in parts.values() for r in p.records),
        counts=dict(counts),
        uncertainty_m=unc,
        max_deviation_m=max(devs) if devs else None,
        max_tolerance_m=max(tols) if tols else None,
        max_gap_m=max(gaps) if gaps else None,
        approximated=dict(by),
        exact=not by,
        partial=bool(incomplete),
        originating_system=originating,
        incomplete="; ".join(incomplete) or None,
        instances=tuple(placed),
        skipped=tuple(skipped),
        warnings=tuple(warnings),
        seconds=time.perf_counter() - t0,
        _data=w.lines,
    )


# --------------------------------------------------------------------------- Parasolid assemblies
def _is_rigid(r) -> bool:
    """A turn: orthonormal columns and no mirror. A scale or a shear, which an axis
    placement cannot hold either, is not one."""
    for i in range(3):
        for j in range(3):
            dot = r[0][i] * r[0][j] + r[1][i] * r[1][j] + r[2][i] * r[2][j]
            if abs(dot - (1.0 if i == j else 0.0)) > MIRROR_TOLERANCE:
                return False
    return _is_rotation(r)


def _unique(label: str, used: Counter) -> str:
    used[label] += 1
    return label if used[label] == 1 else f"{label} ({used[label]})"


def transmit_assembly_model(
    doc,
    xt,
    *,
    name: str,
    types,
    opts,
    allow_partial: bool,
    max_faces: int,
    max_entities: int,
    max_seconds: float,
    t0: float,
    originating: str,
):
    """STEP of a Parasolid transmit whose assemblies place bodies by instances: as the
    transmit holds it, a part product for each body (written once however many instances
    place it), an assembly product for each ASSEMBLY, and a NEXT_ASSEMBLY_USAGE_OCCURRENCE
    for each INSTANCE, at its TRANSFORM in its assembly's frame. The file's one
    assembly is the top product, named ``name``; a partition with several top-level
    parts gets a top product of that name placing each at the identity.

    An instance the reader leaves out (``Scene.skipped``'s reasons), one placed mirrored,
    scaled or sheared (an axis placement holds a turn and a move only) and one whose body
    the export refuses refuse the export, unless ``allow_partial`` leaves them out. A
    body of a type not asked for is not written, nor are its instances, as a part's
    export leaves such a body out."""
    from ..formats._source import Clock as ReadClock
    from ..formats.solidworks.components import IDENTITY
    from ..formats.xt import ASSEMBLY, BODY
    from ..geometry import SkippedInstance
    from . import (
        BODY_TYPES,
        StepModel,
        StepProduct,
        TimeUp,
        Topology,
        _clock,
        _Job,
        _limit_from,
        _part_counts,
        _prepare,
        _write_bodies,
    )

    clock = _clock(max_seconds, t0)
    lim = doc.limits
    st = doc._analysed(ReadClock(lim.seconds))
    if st.too_deep:
        raise lim.exceeded("depth", f"the transmit's assemblies nest deeper than {lim.depth}")
    topo = Topology(xt)
    kinds = {}
    for b in topo.bodies():
        code = topo.get(b, "body_type", 0)
        kinds[b.index] = BODY_TYPES.get(code, "unknown") if isinstance(code, int) else "unknown"

    # One part product per body asked for, in the order the tree first reaches them.
    warnings: list[ReaderWarning] = []
    parts: dict[int, tuple[str, Any]] = {}
    refused: dict[int, str] = {}
    not_asked: Counter = Counter()
    part_labels: Counter = Counter()
    for k, body in enumerate(st.bodies, 1):
        kind = kinds.get(body.index, "unknown")
        if kind not in types:
            not_asked[kind] += 1
            continue
        label = _unique(st.name(body) or f"{name} body {k}", part_labels)
        part_warnings: list[ReaderWarning] = []
        try:
            prep = _prepare(
                jobs=[_Job(label, xt, body, kind, "transmit", None, topo)],
                types=types,
                opts=opts,
                allow_partial=allow_partial,
                max_faces=max_faces,
                clock=clock,
                warnings=part_warnings,
                configuration=None,
            )
        except (NothingToExportError, NotRepresentableError) as exc:
            refused[body.index] = _short(exc)
            continue
        warnings.extend(ReaderWarning(w.code, f"{label}: {w.message}") for w in part_warnings)
        parts[body.index] = (label, prep)

    # Each assembly's instances by the id of the first path that reaches them, as the tree has it.
    single = len(st.tops) == 1 and st.tops[0].type == ASSEMBLY
    first: dict[int, str] = {}
    queue = [(pid, top) for pid, top in st.top_ids if top.type == ASSEMBLY]
    for pid, top in queue:
        first.setdefault(top.index, pid)
    while queue:
        clock.tick()
        pid, asm = queue.pop(0)
        for n, _it, child, _pl in st.children[asm.index]:
            if child.type == ASSEMBLY and child.index not in first:
                first[child.index] = f"{pid}.{n}"
                queue.append((first[child.index], child))

    skipped: list = []
    occurrences: dict[int, list[tuple[int, str, str, Any, Any]]] = {}
    asm_labels: dict[int, str] = {}  # each sub-assembly written: its product's name
    used_labels: Counter = Counter()
    for a in st.post:  # children first: a sub-assembly is decided before the assemblies placing it
        clock.tick()
        if a not in first:
            continue
        here = occurrences[a] = []
        for n, reason, message in st.skips[a]:
            skipped.append(SkippedInstance(f"{first[a]}.{n}", "", None, reason, message))
        for n, it, child, pl in st.children[a]:
            ident = f"{first[a]}.{n}"
            if child.type == BODY:
                if child.index in refused:
                    skipped.append(SkippedInstance(ident, "", None, "step_refused", refused[child.index]))
                    continue
                if child.index not in parts:
                    continue  # a body of a type not asked for
                fallback = parts[child.index][0]
            elif occurrences.get(child.index):
                fallback = asm_labels[child.index]
            else:
                continue  # an assembly with nothing in it to write
            nm = st.name(it) or st.name(child) or fallback
            if not _is_rigid(pl.rotation):
                skipped.append(
                    SkippedInstance(
                        ident,
                        nm,
                        None,
                        "step_not_rigid",
                        "it is placed mirrored or scaled, which a STEP placement cannot hold",
                    )
                )
                continue
            here.append((n, ident, nm, child, pl))
        if here and not (single and a == st.tops[0].index):
            fallback = f"{name} assembly {len(asm_labels) + 1}"
            asm_labels[a] = _unique(st.name(st.f.idx[a]) or fallback, used_labels)
    if single:
        top_children = occurrences[st.tops[0].index]
    else:
        top_children = []
        for pid, top in st.top_ids:
            body = top.type == BODY and top.index in parts
            if body or (top.type == ASSEMBLY and occurrences.get(top.index)):
                label = parts[top.index][0] if body else asm_labels[top.index]
                top_children.append((int(pid), pid, st.name(top) or label, top, IDENTITY))
    reasons = [f"{s.id}: {s.message}" for s in skipped]
    if not top_children:
        if not_asked.get("sheet") and not parts and not refused:
            raise NothingToExportError(
                "nothing to export: the assembly's bodies are sheets (surfaces); ask for sheets to write "
                "them",
                detail={"rule": "sheets_not_asked"},
            )
        raise NothingToExportError(
            "nothing to export: none of the assembly's instances can be written"
            + (f": {'; '.join(reasons[:3])}" if reasons else ""),
            detail={"rule": "no_instances"},
        )
    if skipped and not allow_partial:
        raise NotRepresentableError(
            f"{len(skipped)} of the assembly's instances cannot be written: {'; '.join(reasons[:3])}"
            f"{'; ...' if len(reasons) > 3 else ''}",
            detail={"rule": "instances_left_out", "value": len(skipped), "instances": reasons[:MAX_LISTED]},
        )

    # The part instances written, path by path; a few instances can place a part billions of times.
    n_items, _n_left, _per = st.count(set(parts))
    if n_items > lim.items:
        raise lim.exceeded("items", f"the transmit places more than {lim.items:,} parts")
    placed: list[tuple[str, str]] = []
    stack = [(ident, child) for _n, ident, _nm, child, _pl in reversed(top_children)]
    while stack:
        clock.tick()
        pid, child = stack.pop()
        if child.type == BODY:
            placed.append((pid, parts[child.index][0]))
        else:
            stack.extend((f"{pid}.{n}", c) for n, _i, _nm, c, _pl in reversed(occurrences[child.index]))

    every = [top_children, *occurrences.values()]
    used_parts = {c.index for kids in every for *_x, c, _p in kids if c.type == BODY}
    unc = max(parts[i][1].uncertainty for i in used_parts)
    w = p21.Writer(max_entities)
    sub_products: list = []
    try:
        ctx = Contexts(w)
        top = product(ctx, name, "assembly")
        shape = AssemblyShape(ctx, top, name, unc * p21.SCALE)
        written: dict[int, tuple[int, int, int]] = {}
        for index, (label, prep) in parts.items():
            if index in used_parts:
                pd = product(ctx, label, "part")
                rep, origin = _write_bodies(ctx, pd, label, prep, clock)
                written[index] = (pd, rep, origin)
        for a in st.post:
            if a not in asm_labels:
                continue
            label = asm_labels[a]
            spd = product(ctx, label, "assembly")
            sub_shape = AssemblyShape(ctx, spd, label, unc * p21.SCALE)
            for _n, ident, nm, child, pl in occurrences[a]:
                clock.tick()
                cpd, crep, corigin = written[child.index]
                sub_shape.items.append(place(ctx, spd, sub_shape.rep, cpd, crep, corigin, pl, ident, nm))
            sub_shape.close()
            written[a] = (spd, sub_shape.rep, sub_shape.items[0])
            sub_products.append(StepProduct(label, "assembly", None, None, unc))
        for _n, ident, nm, child, pl in top_children:
            clock.tick()
            cpd, crep, corigin = written[child.index]
            shape.items.append(place(ctx, top, shape.rep, cpd, crep, corigin, pl, ident, nm))
        shape.close()
    except (p21.EntityLimit, TimeUp) as exc:
        raise _limit_from(exc) from None

    preps = [parts[i] for i in parts if i in used_parts]
    counts: Counter = Counter()
    for _label, prep in preps:
        counts.update(_part_counts(prep))
    counts["products"] = 1 + len(preps) + len(sub_products)
    counts["instances"] = len(placed)
    counts["sub_assemblies"] = len(sub_products)
    left_out = counts.pop("bodies_left_out", 0) + sum(not_asked.values())
    counts["entities"] = w.count
    counts["bodies_left_out"] = left_out
    if not_asked:
        listed = ", ".join(f"{v} {k}" for k, v in sorted(not_asked.items()))
        warnings.append(
            ReaderWarning("bodies_left_out", f"bodies of a type not asked for are not written ({listed})")
        )
    devs = [p.deviation for _l, p in preps if p.deviation is not None]
    tols = [p.tolerance for _l, p in preps if p.tolerance is not None]
    gaps = [x for _l, p in preps for x in p.gaps]
    by: Counter = Counter()
    for _l, p in preps:
        by.update(p.approximated)
    incomplete = [f"{label}: {p.incomplete}" for label, p in preps if p.incomplete]
    if skipped:
        incomplete.append(f"{len(skipped)} instances left out")
        warnings.append(
            ReaderWarning(
                "step_instances_left_out",
                f"{len(skipped)} of the assembly's instances are left out: {'; '.join(reasons[:3])}"
                f"{'; ...' if len(reasons) > 3 else ''}",
            )
        )
    products = (
        StepProduct(name, "assembly", None, None, unc),
        *(StepProduct(label, "part", None, None, p.uncertainty) for label, p in preps),
        *sub_products,
    )
    return StepModel(
        name=name,
        doc_type="assembly",
        configuration=None,
        products=products,
        bodies=tuple(r for _l, p in preps for r in p.records),
        counts=dict(counts),
        uncertainty_m=unc,
        max_deviation_m=max(devs) if devs else None,
        max_tolerance_m=max(tols) if tols else None,
        max_gap_m=max(gaps) if gaps else None,
        approximated=dict(by),
        exact=not by,
        partial=bool(incomplete),
        originating_system=originating,
        incomplete="; ".join(incomplete) or None,
        instances=tuple(placed),
        skipped=tuple(skipped),
        warnings=tuple(warnings),
        seconds=time.perf_counter() - t0,
        _data=w.lines,
    )
