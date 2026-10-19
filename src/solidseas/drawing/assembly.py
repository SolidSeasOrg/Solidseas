"""What an assembly drawing is made from (``docs/drawings/assemblies.md``).

:func:`open_assembly` reads one configuration of a SOLIDWORKS assembly, read-only:

- the part instances to draw, each placed in the assembly's frame as the viewer and
  the STEP export place them (:func:`solidseas.geometry.display_geometry`), with the
  document each part is read from: its own file, found by reference resolution, or
  the document a virtual part is stored in;
- each part's bodies, read once for each configuration used however many instances
  use it: the solid bodies SOLIDWORKS shows, each placed for every instance
  (:class:`PlacedBody`), so the model stage tessellates a part once
  (:func:`~solidseas.drawing.facegraph.from_bodies`);
- the bill of materials, top-level only as SOLIDWORKS' default BOM table is
  (:func:`solidseas.bom.build_bom`), as the parts list's lines, each with the
  instances it stands for.

It returns a :class:`~solidseas.drawing.source.DrawingSource` of format ``sldasm``
whose ``assembly`` holds them. The name, units, properties and hashes are the
assembly's own, as a part's are; the geometry digest covers every drawn instance's
part geometry and placement, so moving a component or changing a part changes it.

An instance that cannot be drawn (its file not found, its part storing no bodies
for its configuration, a placement that scales or shears) is left out and said in
the warnings; when none can be drawn the assembly is refused with
``not_implemented``, rule ``no_instances``. An instance excluded from the bill of
materials is drawn and gets no balloon.
"""

from __future__ import annotations

import contextlib
import contextvars
import math
import os
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any

from ..errors import InvalidArgumentError, SolidSeasError, UnsupportedOperationError
from . import keys, numbers
from .limits import DEFAULT_LIMITS, DrawingLimits
from .types import BomLine, DrawingOptions

FORMAT = "sldasm"
BOM_TYPE = "top"  # SOLIDWORKS' own default for a new BOM table
RIGID = 1e-6  # how far a placement's rotation may be from a rotation
MAX_LEFT_OUT = 20  # instances left out that the warnings name one by one
MAX_LINE_PROPERTIES = 200  # a parts list line's properties kept for its drawing number
VIEWS = ("front", "top", "right", "isometric")
FRONT = "+z"


@dataclass(frozen=True)
class PlacedBody:
    """A part's body where one instance puts it: the ``ParasolidBody``, the name the
    drawing gives it (the instance's id and the body's name), the placement from the
    part's frame to the assembly's and the instance's id."""

    body: Any
    name: str
    placement: Any
    instance: str

    @property
    def transmit(self) -> Any:
        return self.body.transmit

    @property
    def body_type(self) -> str:
        return self.body.body_type


@dataclass(frozen=True)
class AssemblyInstance:
    """A part instance drawn: its component tree id and name, the part's document
    name, the configuration used, the parts list item it is counted in (None when it
    is in none) and the model's bodies that are its own."""

    id: str
    name: str
    part: str
    configuration: str | None
    item: str | None
    bodies: tuple[int, ...]


@dataclass(frozen=True)
class AssemblyContents:
    """An assembly as its drawing reads it: the instances drawn, their placed bodies in
    the model's body order, the parts list, the instances left out with the reason,
    and whether the bill of materials is complete (:attr:`solidseas.bom.Bom.complete`)."""

    instances: tuple[AssemblyInstance, ...]
    bodies: tuple[PlacedBody, ...]
    bom: tuple[BomLine, ...]
    left_out: tuple[tuple[str, str], ...] = ()
    bom_complete: bool = True
    # every type's BOM (solidseas.bom.Bom by type), for a parts list the BOM editor set
    boms: tuple[tuple[str, Any], ...] = ()

    def bom_of(self, bom_type: str) -> Any:
        """The :class:`~solidseas.bom.Bom` of ``bom_type``, None when it was not built."""
        return dict(self.boms).get(bom_type)

    def instance_of_body(self, k: int) -> str | None:
        """The id of the instance that model body ``k`` belongs to."""
        return self.bodies[k].instance if 0 <= k < len(self.bodies) else None

    def instances_of(self, line: BomLine) -> list[AssemblyInstance]:
        """The drawn instances a parts list line stands for, in drawing order: its own
        instances and, for a sub-assembly's line, the parts inside it."""
        own = set(line.instances)
        out = []
        for inst in self.instances:
            if inst.id in own or any(inst.id.startswith(i + "/") for i in own):
                out.append(inst)
        return out


def is_assembly(obj: Any) -> bool:
    """Whether ``obj`` (a ``DrawingSource``, a drawing, or a drawing's ``model``
    member) is of an assembly."""
    if isinstance(obj, dict):
        return obj.get("format") == FORMAT
    model = getattr(obj, "model", None)
    if isinstance(model, dict):
        return model.get("format") == FORMAT
    return getattr(obj, "format", None) == FORMAT


def assembly_options(options: DrawingOptions) -> DrawingOptions:
    """An assembly drawing's options: what the user chose, and where they left a choice
    to SolidSeas, the assembly's defaults: the front, top and right views and the
    isometric (:data:`VIEWS`), hidden lines off, and the front seen from the
    assembly's own front (+Z, SOLIDWORKS' Front view)."""
    kw: dict[str, Any] = {}
    if options.views == "auto":
        kw["views"] = VIEWS
    if options.hidden is None:
        kw["hidden"] = False
    if options.front is None:
        kw["front"] = FRONT
    return replace(options, **kw) if kw else options


def _identity(obj: Any) -> tuple[Any, Any, bool]:
    if isinstance(obj, dict):
        return obj.get("sha256"), obj.get("geometry"), obj.get("format") == FORMAT
    return getattr(obj, "sha256", None), getattr(obj, "geometry_digest", None), is_assembly(obj)


def same_file(model: Any, source: Any) -> bool:
    """Whether ``source`` (a ``DrawingSource``, or another drawing's ``model`` member) is
    the very model a drawing's ``model`` member names: the same file by its SHA-256
    and, for an assembly, whose parts are files of their own, the same geometry digest
    too, so a part changed under an unchanged assembly file is a changed model."""
    sha, shape, asm = _identity(model)
    their_sha, their_shape, their_asm = _identity(source)
    if not sha or their_sha != sha:
        return False
    if asm or their_asm:
        return bool(shape) and their_shape == shape
    return True


def _rigid(placement: Any) -> bool:
    """Whether a placement only turns (or mirrors) and moves: its rotation's rows are
    unit length and square to each other within :data:`RIGID`."""
    r = placement.rotation
    for i in range(3):
        for j in range(3):
            dot = r[i][0] * r[j][0] + r[i][1] * r[j][1] + r[i][2] * r[j][2]
            if not math.isfinite(dot) or abs(dot - (1.0 if i == j else 0.0)) > RIGID:
                return False
    return all(math.isfinite(v) for v in placement.translation_m)


def _placement_text(placement: Any) -> str:
    q = keys.DIGEST_TOLERANCE
    values = [*(v for row in placement.rotation for v in row), *placement.translation_m]
    return ",".join(str(keys.q(float(v), q)) for v in values)


def _line_of(row: Any) -> BomLine:
    props = tuple(
        (str(p.name), str(p.text if p.text is not None else p.value))
        for p in (row.properties or ())
        if p.text is not None or p.value is not None
    )
    return BomLine(
        item=str(row.item),
        part_number=str(row.part_number or ""),
        description=str(row.description or ""),
        quantity=int(row.quantity),
        level=int(row.level),
        instances=tuple(str(i) for i in row.instances),
        file=str(row.file_name or ""),
        own_file=not (row.virtual or row.imported),
        properties=props[:MAX_LINE_PROPERTIES],
    )


def _item_of(instance_id: str, lines: tuple[BomLine, ...]) -> str | None:
    """The item an instance is counted in: the line naming it, or the line of the
    sub-assembly it is inside, the nearest first."""
    best: tuple[int, str] | None = None
    for line in lines:
        for i in line.instances:
            if instance_id == i or instance_id.startswith(i + "/"):
                if best is None or len(i) > best[0]:
                    best = (len(i), line.item)
    return best[1] if best is not None else None


class _Part:
    """One part document in one configuration, read once: its bodies to draw, the
    signatures and sizes of its faces, and why it cannot be drawn when it cannot."""

    def __init__(self) -> None:
        self.name = ""
        self.configuration: str | None = None
        self.bodies: list = []
        self.faces: dict[int, int] = {}
        self.digest = ""
        self.sizes: list[float] = []
        self.why: str | None = None
        self.warnings: list[str] = []


def _read_part(doc: Any, path: str | None, nested: tuple[str, ...], configuration: str | None) -> _Part:
    from ..formats.solidworks import open_document
    from ..tessellate import bodies_of, shown_bodies
    from ..tessellate.surfaces import Geometry
    from ..tessellate.topology import Topology
    from .source import _face_signature, _sizes, _walk

    out = _Part()
    try:
        holder = None
        if path is None:
            part = doc
        else:
            holder = open_document(path)
            part = holder
        try:
            for stream in nested:
                part = part.nested(stream)  # owned by its parent, which closes it
            if part.doc_type != "part":
                out.why = "its document is not a part"
                return out
            out.name = (
                os.path.basename(path) if path and not nested else (getattr(part, "name", "") or "part")
            )
            cfg_name, bodies, warnings, _n = bodies_of(part, configuration)
            out.configuration = cfg_name
            out.warnings = [str(w) for w in warnings if getattr(w, "code", "") != "no_stored_bodies"]
            shown, _hidden = shown_bodies(bodies)
            out.bodies = [b for b in shown if b.body_type == "solid"]
            if not out.bodies:
                out.why = f"its part stores no solid body for configuration {cfg_name!r}"
                return out
            signatures: list[str] = []
            for b in out.bodies:
                topo = Topology(b.transmit)
                geom = Geometry(topo, 1e-4)
                count = 0
                for tb in topo.bodies():
                    for face, snode, edges in _walk(topo, tb):
                        count += 1
                        signatures.append(
                            _face_signature(topo, geom, face, snode, edges, keys.DIGEST_TOLERANCE)
                        )
                        out.sizes.extend(_sizes(topo, geom, edges))
                out.faces[id(b)] = count
            out.digest = keys.digest(signatures)
        finally:
            if holder is not None:
                holder.close()
    except SolidSeasError as exc:
        out.why = f"its part could not be read: {exc}"
    except OSError as exc:
        out.why = f"its part could not be read: {exc.strerror or exc}"
    return out


# The folders an assembly's component files are looked for in while a drawing is made from
# it (:func:`searching`); none set, the assembly's own folder, as SOLIDWORKS looks.
_SEARCH: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar("drawing_search", default=())


@contextlib.contextmanager
def searching(folders) -> Iterator[None]:
    """Look for assembly components in ``folders`` (and each assembly's own folder) while
    drawings are made, updated or merged inside this block: the viewer gives the folder it
    has open, as 3D Print and the 3D view do, so an assembly opened from a project folder
    finds parts kept elsewhere in it."""
    token = _SEARCH.set(tuple(os.path.abspath(os.fspath(f)) for f in folders if f))
    try:
        yield
    finally:
        _SEARCH.reset(token)


def _search_roots(path: str | None):
    """The roots reference resolution searches for ``path``'s components: the folders
    :func:`searching` gave, then the assembly's own folder when none of them holds it;
    None (its own folder) when none were given."""
    from ..roots import Root, Roots

    folders = _SEARCH.get()
    if not folders:
        return None
    roots = [Root(f"folder{i}" if i else "folder", f) for i, f in enumerate(folders)]
    if path:
        own = os.path.dirname(os.path.abspath(path))
        if not any(_within(own, f) for f in folders):
            roots.append(Root("document", own))
    return Roots(roots)


def _within(path: str, folder: str) -> bool:
    try:
        base = os.path.normcase(folder)
        return os.path.commonpath([os.path.normcase(path), base]) == base
    except ValueError:  # another drive
        return False


def open_assembly(
    path_or_document: Any,
    *,
    configuration: str | None = None,
    bodies: tuple[str, ...] | None = None,
    units: str | None = None,
    title_names: tuple[str, ...] = (),
    limits: DrawingLimits = DEFAULT_LIMITS,
):
    """Read a SOLIDWORKS assembly for a drawing. ``bodies`` names what to draw, by
    instance id or by a body's name in the drawing (None: every instance);
    ``units``, ``title_names`` and ``limits`` as for a part
    (:func:`~solidseas.drawing.source.open_source`)."""
    from ..bom import BOM_TYPES, build_boms
    from ..formats.solidworks import open_document
    from ..geometry import display_geometry
    from .source import LENGTH_UNITS, MAX_PROPERTIES, DrawingSource, SourceBody, SourceUnits, _clean, _hints
    from .source import _sha256 as sha256_of

    if units not in (None, "in", "mm"):
        raise InvalidArgumentError("units must be 'in', 'mm' or None", detail={"parameter": "units"})
    own = False
    if isinstance(path_or_document, (str, os.PathLike)):
        path = os.fspath(path_or_document)
        doc = open_document(path)
        own = True
    else:
        doc = path_or_document
        path = getattr(doc, "path", None)
    try:
        if doc.doc_type != "assembly":
            raise UnsupportedOperationError(
                "this document is not an assembly",
                detail={"rule": "format_later", "value": str(doc.doc_type)},
            )
        warnings = [str(w) for w in doc.warnings]
        roots = _search_roots(path)
        g = display_geometry(
            doc,
            configuration,
            roots=roots,
            sources=("nested", "file", "brep"),
            max_instances=limits.instances,
            max_brep_seconds=limits.seconds_source,
            brep_options={"body_types": ("solid",)},
        )
        warnings += [str(w) for w in g.warnings]
        left_out: list[tuple[str, str]] = [(s.id, s.message) for s in g.skipped]
        # every type at once (one pass reads the files): a parts list the BOM editor set
        # may be parts only or indented
        boms = build_boms(
            doc,
            g.configuration,
            bom_types=BOM_TYPES,
            roots=roots,
            resolution=g.resolution,
            max_seconds=limits.seconds_source,
        )
        bom = boms.get(BOM_TYPE) if boms else None
        lines = tuple(_line_of(r) for r in bom.rows) if bom is not None else ()
        bom_complete = bool(bom is not None and bom.complete)
        if bom is not None:
            warnings += [str(w) for w in bom.warnings]

        parts: dict[tuple, _Part] = {}
        placed: list[PlacedBody] = []
        instances: list[AssemblyInstance] = []
        records: list[SourceBody] = []
        signatures: list[str] = []
        sizes: list[float] = []
        wanted = set(bodies) if bodies is not None else None
        seen_names: set[str] = set()
        for inst in g.instances:
            src = g.meshes[inst.mesh]
            key = (src.path, tuple(src.nested), inst.configuration)
            part = parts.get(key)
            if part is None:
                part = parts[key] = _read_part(doc, src.path, tuple(src.nested), inst.configuration)
                warnings += [f"{inst.name}: {w}" for w in part.warnings]
                sizes.extend(part.sizes)
            if part.why is not None:
                left_out.append((inst.id, part.why))
                continue
            if not _rigid(inst.placement):
                left_out.append((inst.id, "it is placed scaled or sheared, which a drawing cannot draw"))
                continue
            own_bodies = []
            for b in part.bodies:
                name = f"{inst.id}/{b.name}"
                seen_names.update((name, inst.id))
                chosen = wanted is None or name in wanted or inst.id in wanted
                records.append(SourceBody(name, b.body_type or "unknown", part.faces.get(id(b), 0), chosen))
                if chosen:
                    own_bodies.append(len(placed))
                    placed.append(PlacedBody(b, name, inst.placement, inst.id))
            if not own_bodies:
                continue
            instances.append(
                AssemblyInstance(
                    inst.id,
                    inst.name,
                    part.name,
                    part.configuration,
                    _item_of(inst.id, lines),
                    tuple(own_bodies),
                )
            )
            signatures.append(f"{inst.id}|{part.digest}|{_placement_text(inst.placement)}")
        if wanted is not None:
            missing = sorted(wanted - seen_names)
            if missing:
                raise InvalidArgumentError(
                    f"the assembly has no instance or body named {missing[0]!r}",
                    detail={"parameter": "bodies"},
                )
        for ident, why in left_out[:MAX_LEFT_OUT]:
            warnings.append(f"{ident} is not drawn: {why}")
        if len(left_out) > MAX_LEFT_OUT:
            warnings.append(f"{len(left_out) - MAX_LEFT_OUT} more instances are not drawn")
        if not placed:
            reasons = "; ".join(f"{i}: {w}" for i, w in left_out[:3])
            raise UnsupportedOperationError(
                "nothing to draw: none of the assembly's instances can be drawn"
                + (f" ({reasons})" if reasons else ""),
                detail={"rule": "no_instances", "value": len(left_out)},
            )
        if g.truncated:
            warnings.append("a limit stopped reading the assembly: " + ", ".join(g.truncated))

        stated_raw = (doc.units or {}).get("length") if isinstance(doc.units, dict) else None
        stated = LENGTH_UNITS.get(stated_raw) if isinstance(stated_raw, str) else None
        if units is not None:
            unit_info = SourceUnits(units, "user", None, stated)
        elif stated is not None:
            unit_info = SourceUnits(stated, "file", None, stated)
        else:
            guess = numbers.guess_units(sizes)
            unit_info = SourceUnits(guess.unit, "guessed", guess, None)
        cfg_name = g.configuration
        props_raw = doc.property_values(cfg_name) if cfg_name is not None else doc.property_values()
        props = [
            (_clean(k, limits.title_chars), _clean(v, limits.string_chars))
            for k, v in list(props_raw.items())[:MAX_PROPERTIES]
        ]
        if len(props_raw) > MAX_PROPERTIES:
            warnings.append(f"only the first {MAX_PROPERTIES} properties are read")
        name = os.path.basename(path) if path else (getattr(doc, "name", "") or "assembly")
        return DrawingSource(
            name=name,
            format=FORMAT,
            kind="brep",
            configuration=cfg_name,
            bodies=tuple(records),
            units=unit_info,
            material=None,
            properties=tuple(props),
            hints=_hints(doc.fields.keywords),
            sha256=sha256_of(path) if path else None,
            geometry_digest=keys.digest(signatures),
            properties_digest=keys.properties_digest(dict(props), title_names),
            warnings=tuple(warnings),
            _bodies=tuple(placed),
            assembly=AssemblyContents(
                tuple(instances),
                tuple(placed),
                lines,
                tuple(left_out),
                bom_complete,
                tuple((boms or {}).items()),
            ),
        )
    finally:
        if own:
            doc.close()


__all__ = [
    "BOM_TYPE",
    "FORMAT",
    "FRONT",
    "VIEWS",
    "AssemblyContents",
    "AssemblyInstance",
    "PlacedBody",
    "assembly_options",
    "is_assembly",
    "open_assembly",
    "same_file",
]
