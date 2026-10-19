"""What a drawing is made from: ``DrawingSource`` (``docs/DRAWINGS.md`` 6.2).

:func:`open_source` reads a SOLIDWORKS part, read-only, and returns its name (the
file name only), format, configuration, bodies (name, type, face count, which are
drawn), units and where they came from, material, effective properties
(bounded), KeyWords hints, and three hashes: the file's SHA-256, the geometry
digest (every face's signature at 1e-7 m, so a save that changed no geometry
keeps it) and the digest of the properties the title block reads.

It takes SOLIDWORKS parts and assemblies: an assembly is read by
:func:`.assembly.open_assembly`, whose source has format ``sldasm`` and its
instances, placed bodies and parts list in ``assembly``. A SOLIDWORKS drawing is
refused with ``not_implemented`` (rule ``drawing``), another format with rule
``format_later``. When a part states no unit, the unit is guessed from its sizes
(whole thousandths of an inch against whole hundredths of a millimetre), with the
evidence, and the wizard asks the user to confirm it every time (Q3).
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any

from ..errors import InvalidArgumentError, UnsupportedOperationError
from ..tessellate.surfaces import Geometry
from ..tessellate.topology import CURVE_TYPES, EDGE, SURFACE_TYPES, FaceFailed, Topology
from . import keys, numbers
from .limits import DEFAULT_LIMITS, DrawingLimits

SOLIDWORKS_PARTS = (".sldprt",)
SOLIDWORKS_ASSEMBLIES = (".sldasm",)
SOLIDWORKS_OTHER = {".slddrw": "drawing"}
MAX_PROPERTIES = 1000
LENGTH_UNITS = {"mm": "mm", "cm": "mm", "m": "mm", "um": "mm", "in": "in", "ft": "in", "mil": "in"}


@dataclass(frozen=True)
class SourceBody:
    name: str
    type: str
    faces: int
    selected: bool
    hidden: bool = False


@dataclass(frozen=True)
class SourceUnits:
    """The drawing unit and where it came from: ``file`` (the part states it), ``guessed``
    (with the evidence) or ``user``."""

    unit: str
    origin: str
    evidence: numbers.UnitGuess | None = None
    stated: str | None = None  # the part's own length unit, when it states one


@dataclass(frozen=True)
class DrawingSource:
    """A part or an assembly as a drawing starts from it (6.2). An assembly's
    ``bodies`` are its instances' placed bodies, and ``assembly`` holds its instances
    and parts list (:class:`.assembly.AssemblyContents`); a part's is None."""

    name: str
    format: str
    kind: str
    configuration: str | None
    bodies: tuple[SourceBody, ...]
    units: SourceUnits
    material: str | None
    properties: tuple[tuple[str, str], ...]
    hints: tuple[float, ...]
    sha256: str | None
    geometry_digest: str
    properties_digest: str
    warnings: tuple[str, ...] = ()
    _bodies: tuple = field(default=(), repr=False, compare=False)
    assembly: Any = field(default=None, repr=False, compare=False)

    def selected_bodies(self) -> list:
        """The ``ParasolidBody`` objects of the bodies to draw, in order (an assembly's
        :class:`.assembly.PlacedBody` objects)."""
        chosen = {b.name for b in self.bodies if b.selected}
        return [b for b in self._bodies if b.name in chosen]

    def property(self, *names: str) -> str | None:
        """The first of ``names`` the part has a non-empty value for (compared without
        case): how the title block finds its fields."""
        folded = {k.casefold(): v for k, v in self.properties}
        for n in names:
            v = folded.get(n.casefold())
            if v is not None and v.strip():
                return v
        return None


def _refuse(rule: str, message: str, value: str) -> UnsupportedOperationError:
    return UnsupportedOperationError(message, detail={"rule": rule, "value": value})


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _clean(text: Any, limit: int) -> str:
    s = "" if text is None else str(text)
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s)
    return s[:limit]


def _hints(keywords: str | None) -> tuple[float, ...]:
    """Numbers in the KeyWords field, for ranking alternatives only (9): never a value."""
    if not keywords:
        return ()
    out = []
    for tok in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])", keywords[:4096]):
        try:
            v = float(tok)
        except ValueError:
            continue
        if math.isfinite(v):
            out.append(v)
        if len(out) >= 200:
            break
    return tuple(out)


def _walk(topo: Topology, body):
    """(face, surface node, [edge nodes]) of every face of a body, skipping damage."""
    for f in topo.faces(body):
        try:
            snode = topo.ref(f, "surface", SURFACE_TYPES, required=True)
            edges = []
            for lp in topo.loops(f):
                for fin in topo.fins(lp):
                    e = topo.ref(fin, "edge", (EDGE,))
                    if e is not None:
                        edges.append(e)
        except FaceFailed:
            continue
        yield f, snode, edges


def _face_signature(topo: Topology, geom: Geometry, face, snode, edges, tol: float) -> str:
    """A face's signature from its surface alone, as :mod:`.keys` defines it; a free-form
    face by its type and the box of its vertices."""
    try:
        S = geom.surface(snode)
    except FaceFailed:
        S = None
    name = snode.tname
    sense = topo.sense(face) * topo.sense(snode) * getattr(S, "flip", 1)
    if name == "PLANE" and S is not None:
        return keys.plane(tuple(c * sense for c in S.N), S.P, tol)
    if name == "CYLINDER" and S is not None:
        return keys.cylinder(S.P, S.A, S.r, tol)
    if name == "CONE" and S is not None:
        apex = None if S.t == 0.0 else tuple(S.P[i] - S.A[i] * S.r / S.t for i in range(3))
        return keys.cone(S.P, S.A, math.atan(S.t), tol, apex)
    if name == "SPHERE" and S is not None:
        return keys.sphere(S.C, S.r, tol)
    if name == "TORUS" and S is not None:
        return keys.torus(S.C, S.A, S.R, S.r, tol)
    pts = []
    for e in edges:
        for v in topo.edge_ends(e):
            p = topo.point_of(v) if v is not None else None
            if p is not None:
                pts.append(p)
    if pts:
        box = (
            tuple(min(p[i] for p in pts) for i in range(3)),
            tuple(max(p[i] for p in pts) for i in range(3)),
        )
    else:
        box = ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    return keys.other_face(name.lower(), box, 0.0, tol)


def _sizes(topo: Topology, geom: Geometry, edges) -> list[float]:
    """Lengths of straight edges and diameters of circles: the sizes a unit is guessed
    from."""
    out = []
    for e in edges:
        try:
            node = topo.ref(e, "curve", CURVE_TYPES)
            name = node.tname if node is not None else ""
            if name == "LINE":
                a, b = topo.edge_ends(e)
                pa = topo.point_of(a) if a is not None else None
                pb = topo.point_of(b) if b is not None else None
                if pa is not None and pb is not None:
                    out.append(math.dist(pa, pb))
            elif name == "CIRCLE":
                out.append(2.0 * topo.number(node, "radius"))
        except (FaceFailed, ArithmeticError, TypeError, ValueError):
            continue
    return out


def open_source(
    path_or_document,
    *,
    configuration: str | None = None,
    bodies: tuple[str, ...] | None = None,
    units: str | None = None,
    title_names: tuple[str, ...] = (),
    limits: DrawingLimits = DEFAULT_LIMITS,
) -> DrawingSource:
    """Read a SOLIDWORKS part or assembly for a drawing (6.2). ``bodies`` names the
    bodies to draw (None: every solid body SOLIDWORKS shows; an assembly's instances
    by id); ``units`` (``in`` or ``mm``) is the user's choice and overrides what the
    part states; ``title_names`` are the property names the title block reads, which
    the properties digest covers."""
    from ..formats.solidworks import open_document
    from ..tessellate import bodies_of, shown_bodies
    from .assembly import open_assembly

    if units not in (None, "in", "mm"):
        raise InvalidArgumentError("units must be 'in', 'mm' or None", detail={"parameter": "units"})
    kw = {"configuration": configuration, "bodies": bodies, "units": units, "title_names": title_names}
    own = False
    if isinstance(path_or_document, (str, os.PathLike)):
        path = os.fspath(path_or_document)
        ext = os.path.splitext(path)[1].lower()
        if ext in SOLIDWORKS_OTHER:
            raise _refuse(
                "drawing", "a drawing is made from a part or an assembly; this is a drawing", ext[1:]
            )
        if ext in SOLIDWORKS_ASSEMBLIES:
            return open_assembly(path, limits=limits, **kw)
        if ext not in SOLIDWORKS_PARTS:
            raise _refuse(
                "format_later", "drawings from this format come in a later release", ext[1:] or "unknown"
            )
        doc = open_document(path)
        own = True
    else:
        doc = path_or_document
        path = getattr(doc, "path", None)
    try:
        doc_type = doc.doc_type
        if doc_type == "assembly":
            return open_assembly(doc, limits=limits, **kw)
        if doc_type == "drawing":
            raise _refuse(
                "drawing", "a drawing is made from a part or an assembly; this is a drawing", doc_type
            )
        if doc_type != "part":
            raise _refuse("format_later", "this document is not a part", str(doc_type))
        warnings = [str(w) for w in doc.warnings]
        cfg_name, all_bodies, body_warnings, _n = bodies_of(doc, configuration)
        warnings += [str(w) for w in body_warnings]
        shown, _hidden = shown_bodies(all_bodies)
        shown_ids = {id(b) for b in shown}
        if bodies is not None:
            names = {b.name for b in all_bodies}
            missing = [n for n in bodies if n not in names]
            if missing:
                raise InvalidArgumentError(
                    f"the part has no body named {missing[0]!r}", detail={"parameter": "bodies"}
                )
        records = []
        signatures: list[str] = []
        sizes: list[float] = []
        for b in all_bodies:
            topo = Topology(b.transmit)
            geom = Geometry(topo, 1e-4)
            count = 0
            for tb in topo.bodies():
                for face, snode, edges in _walk(topo, tb):
                    count += 1
                    signatures.append(_face_signature(topo, geom, face, snode, edges, keys.DIGEST_TOLERANCE))
                    sizes.extend(_sizes(topo, geom, edges))
            hidden = id(b) not in shown_ids
            selected = (b.name in bodies) if bodies is not None else (b.body_type == "solid" and not hidden)
            records.append(SourceBody(b.name, b.body_type or "unknown", count, selected, hidden))
        stated_raw = (doc.units or {}).get("length") if isinstance(doc.units, dict) else None
        stated = LENGTH_UNITS.get(stated_raw) if isinstance(stated_raw, str) else None
        if units is not None:
            unit_info = SourceUnits(units, "user", None, stated)
        elif stated is not None:
            unit_info = SourceUnits(stated, "file", None, stated)
        else:
            guess = numbers.guess_units(sizes)
            unit_info = SourceUnits(guess.unit, "guessed", guess, None)
        props_raw = doc.property_values(cfg_name) if cfg_name is not None else doc.property_values()
        props = []
        for k, v in list(props_raw.items())[:MAX_PROPERTIES]:
            props.append((_clean(k, limits.title_chars), _clean(v, limits.string_chars)))
        if len(props_raw) > MAX_PROPERTIES:
            warnings.append(f"only the first {MAX_PROPERTIES} properties are read")
        material = _clean(doc.material, limits.title_chars) or None
        hints = _hints(doc.fields.keywords)
        sha = _sha256(path) if path else None
        name = os.path.basename(path) if path else (getattr(doc, "name", "") or "part")
        return DrawingSource(
            name=name,
            format="sldprt",
            kind="brep",
            configuration=cfg_name,
            bodies=tuple(records),
            units=unit_info,
            material=material,
            properties=tuple(props),
            hints=hints,
            sha256=sha,
            geometry_digest=keys.digest(signatures),
            properties_digest=keys.properties_digest(dict(props), title_names),
            warnings=tuple(warnings),
            _bodies=tuple(all_bodies),
        )
    finally:
        if own:
            doc.close()


__all__ = ["DrawingSource", "SourceBody", "SourceUnits", "open_source"]
