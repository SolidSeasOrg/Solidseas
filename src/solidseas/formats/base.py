"""Model documents: the read-only view of one 3D file that is not a SOLIDWORKS document
(provisional, ``docs/API.md`` section 3.20).

:func:`open_model` opens one: it finds the file's format with the registry
(:mod:`solidseas.formats.registry`), opens the file read-only the way
:func:`~solidseas.formats.solidworks.open_document` does (``within`` a folder,
``max_file_bytes``, ``refuse_hard_links``, ``hold_open``) and hands it to that
format's reader. :func:`open_any` returns a SOLIDWORKS
:class:`~solidseas.formats.solidworks.Document` for a SOLIDWORKS file and a
:class:`ModelDocument` for anything else SolidSeas reads; both satisfy
:class:`AnyDocument`.

A :class:`ModelDocument` answers its head (format, variant, document type,
units, application, fields, properties, header counts and the stored preview)
cheaply; :meth:`~ModelDocument.tree`, :meth:`~ModelDocument.scene`,
:meth:`~ModelDocument.bodies` and :meth:`~ModelDocument.references` read what
they need. A :class:`Scene` is the one hand-off of geometry: mesh objects in
metres (:class:`MeshObject`) and the items that place them
(:class:`SceneItem`). The export, the viewer's 3D view and the thumbnail
renderer all start from one.

How a reader plugs in: a module whose function ``open(source, *, name, path,
file_info, limits, hold_open, detection)`` returns an instance of a
:class:`ModelDocument` subclass. The subclass sets ``format`` (the registry id)
as a class attribute, fills the head attributes in its constructor, and
implements the hooks ``_tree(clock)`` and ``_scene(scene_builder)`` (and, as they
apply, ``_bodies(clock)``, ``_preview()``, ``_references(clock)`` and
``_counts()``). The base class checks the arguments, keeps the clock and the
cancellation, caches, builds the summary and keeps every bound of
:class:`~solidseas.formats.limits.Limits`. A hook builds every mesh through a
:class:`MeshBuilder` from :meth:`SceneBuilder.mesh`, which checks indices,
drops degenerate triangles, counts triangles and vertices against the bounds
and converts to metres. A hook raises only ``SldFormatError``,
``SldLimitError``, ``FormatNotSupportedError`` or the I/O errors
``open_document`` documents; anything else a crafted file provokes
(``ValueError``, ``IndexError``, ``struct.error``...) is turned into
``SldFormatError`` at the boundary, and a ``MemoryError`` into ``SldLimitError``
with ``detail["limit"]`` ``memory``, the answer a worker's memory cap gives.
"""

import math
import os
import struct
import zlib
from array import array
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..errors import (
    FormatNotSupportedError,
    InvalidArgumentError,
    ReaderWarning,
    SldFormatError,
    SldLimitError,
    SolidSeasError,
    UnknownFormatError,
)
from . import registry
from ._source import Clock, Source, check_max_file_bytes, open_source
from .limits import Limits, check_limits
from .solidworks.components import IDENTITY, Placement
from .solidworks.document import FileInfo, SummaryFields
from .solidworks.metadata import PROPERTY_TYPES, Property

# Metres per unit of each length token (the tokens document_summary's units use).
UNIT_SCALE = {"mm": 0.001, "cm": 0.01, "m": 1.0, "in": 0.0254, "ft": 0.3048, "micron": 1e-6}
UNIT_SOURCES = ("file", "format", "assumed")
NODE_KINDS = ("assembly", "component", "object", "body")
MESH_SOURCES = ("mesh", "bodies", "display_mesh")
PREFER = ("bodies", "display")
BODY_TYPES = ("solid", "sheet", "wire", "general")
MAX_COORDINATE_M = 1e6  # a placement farther out than 1,000 km is not a part (export.MAX_COORDINATE_MM)
DEFAULT_MAX_NODES = 10_000
DEFAULT_MAX_DEPTH = 32

# What a crafted file can provoke in a reader that is not a SolidSeas error: turned into
# SldFormatError at the boundary (the reader's own errors and I/O errors pass unchanged).
_DAMAGE = (
    ValueError,
    LookupError,  # IndexError, KeyError, and an unknown codec a file names
    IndexError,
    KeyError,
    struct.error,
    UnicodeError,
    OverflowError,
    zlib.error,
    EOFError,
    ZeroDivisionError,
    RecursionError,
)


def guarded(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """``fn(*args, **kwargs)`` with what a crafted file provokes turned into
    :class:`SldFormatError`, and running out of memory into :class:`SldLimitError`
    (see the module notes)."""
    try:
        return fn(*args, **kwargs)
    except (SolidSeasError, OSError):
        raise
    except MemoryError:
        raise SldLimitError("reading the file ran out of memory", detail={"limit": "memory"}) from None
    except _DAMAGE as exc:
        raise SldFormatError(f"the file could not be read ({type(exc).__name__}: {exc})"[:300]) from exc


# --------------------------------------------------------------------------- the neutral types
Color = tuple[float, float, float, float]


@dataclass(frozen=True)
class ModelNode:
    """One node of a model's tree: ``kind`` is ``assembly``, ``component``, ``object`` or
    ``body``; ``object`` the index of its mesh object in the scene (None when it has
    none or the scene was not read); ``file`` a reference key (an Alibre component's
    document); ``placement`` relative to its parent; ``color`` RGBA from 0 to 1."""

    id: str
    parent: str | None
    name: str | None
    kind: str
    object: int | None = None
    file: str | None = None
    placement: Placement | None = None
    color: Color | None = None


@dataclass(frozen=True)
class ModelTree:
    """The nodes of a model in order, parents before children; ``truncated`` when
    ``max_nodes`` or ``max_depth`` cut it short."""

    nodes: tuple[ModelNode, ...]
    truncated: bool = False


@dataclass(frozen=True)
class MeshObject:
    """One mesh in its own frame: ``positions`` (float64 xyz, metres), ``triangles``
    (uint32 index triples), ``normals`` (float32 per vertex, when the file gives
    them), ``color`` (RGBA 0 to 1), ``source`` (``mesh`` for a mesh file's own
    triangles, ``bodies`` for a tessellated B-rep, ``display_mesh`` for a display
    tessellation the file stores), ``node`` the tree node it belongs to."""

    name: str | None
    positions: array = field(repr=False, compare=False)
    triangles: array = field(repr=False, compare=False)
    normals: array | None = field(default=None, repr=False, compare=False)
    color: Color | None = None
    source: str = "mesh"
    node: str | None = None
    warnings: tuple[ReaderWarning, ...] = ()

    @property
    def n_vertices(self) -> int:
        return len(self.positions) // 3

    @property
    def n_triangles(self) -> int:
        return len(self.triangles) // 3

    def measures(self) -> dict[str, Any]:
        """``volume_m3`` (meaningful when closed), ``area_m2`` and ``box``."""
        from ..export import mesh_measures

        return mesh_measures(self.positions, self.triangles)


@dataclass(frozen=True)
class SceneItem:
    """One placed copy of ``objects[object]``: ``instance`` its tree node id and
    ``placement`` from the object's frame to the model's."""

    object: int
    instance: str | None
    placement: Placement = IDENTITY


@dataclass(frozen=True)
class SkippedItem:
    """An instance a scene leaves out, with a ``reason`` token and a message."""

    instance: str | None
    reason: str
    message: str = ""


@dataclass(frozen=True)
class Scene:
    """Meshes in metres and the items that place them. ``counts`` has every key of
    :data:`SCENE_COUNTS` (``objects``, ``items``, ``vertices``, ``triangles``: placed,
    ``bodies``, ``faces``, ``faces_done`` and ``components``, None where they do not
    apply); ``truncated`` names the bounds that cut it short (``max_triangles``);
    ``skipped`` holds :class:`SkippedItem` and tessellation ``SkippedFace`` objects."""

    objects: tuple[MeshObject, ...]
    items: tuple[SceneItem, ...]
    counts: dict[str, int | None]
    truncated: tuple[str, ...] = ()
    skipped: tuple[Any, ...] = ()
    warnings: tuple[ReaderWarning, ...] = ()


SCENE_COUNTS = ("objects", "items", "vertices", "triangles", "bodies", "faces", "faces_done", "components")


@dataclass(frozen=True)
class BodyRef:
    """One B-rep body as an in-memory Parasolid transmit (``XtTransmit``)."""

    name: str | None
    transmit: Any = field(repr=False, compare=False)
    color: Color | None = None
    node: str | None = None
    body_type: str | None = None


@dataclass(frozen=True)
class ExternalReference:
    """A file the document names: ``key`` (stable within the document), ``kind``
    (``component``, ``buffer``, ``material_library``), ``stored`` (the text the file
    stores, which can be a path from another machine), ``name`` and ``resolution``
    (``status``, ``path``, ``found_by``, ``version``) when it was looked for."""

    key: str
    kind: str
    stored: str | None
    name: str | None
    resolution: dict[str, Any] | None = None


@dataclass(frozen=True)
class SceneOptions:
    """The options of one :meth:`ModelDocument.scene` call, checked."""

    prefer: str = "bodies"
    max_triangles: int | None = None
    chord_m: float | None = None
    chord_fraction: float | None = None
    max_chord_m: float | None = None
    angle_deg: float = 15.0
    max_seconds: float = 30.0
    body_types: tuple[str, ...] = ("solid", "sheet")
    roots: tuple[str, ...] = ()

    def tessellation(self) -> dict[str, Any]:
        """These options as keyword arguments of :func:`solidseas.tessellate.tessellate_transmit`."""
        out: dict[str, Any] = {"angle_deg": self.angle_deg, "body_types": self.body_types}
        if self.chord_m is not None:
            out["chord_m"] = self.chord_m
        else:
            if self.chord_fraction is not None:
                out["chord_fraction"] = self.chord_fraction
            if self.max_chord_m is not None:
                out["max_chord_m"] = self.max_chord_m
        return out


class _Truncated(Exception):
    """The scene reached its ``max_triangles``: the objects finished so far are kept."""


# --------------------------------------------------------------------------- building scenes
class SceneBuilder:
    """What a reader's ``_scene`` hook fills: objects (from :meth:`mesh`), items,
    skipped instances, warnings and counts. Triangles and vertices are counted
    against the document's :class:`Limits` and the call's ``max_triangles``."""

    def __init__(self, limits: Limits, options: SceneOptions, clock: Clock) -> None:
        self.limits = limits
        self.options = options
        self.clock = clock
        self.objects: list[MeshObject] = []
        self.items: list[SceneItem] = []
        self.skipped: list[Any] = []
        self.warnings: list[ReaderWarning] = []
        self.counts: dict[str, int | None] = dict.fromkeys(("bodies", "faces", "faces_done", "components"))
        self.triangles = 0
        self.vertices = 0

    def mesh(
        self,
        *,
        name: str | None = None,
        source: str = "mesh",
        scale_m: float = 1.0,
        color: Color | None = None,
        node: str | None = None,
    ) -> "MeshBuilder":
        """A :class:`MeshBuilder` for one object, whose coordinates are in units of
        ``scale_m`` metres."""
        return MeshBuilder(self, name=name, source=source, scale_m=scale_m, color=color, node=node)

    def take(self, triangles: int, vertices: int) -> None:
        """Count triangles and vertices about to be stored (see the class notes)."""
        lim = self.limits
        self.triangles += triangles
        self.vertices += vertices
        if self.triangles > lim.triangles:
            raise lim.exceeded("triangles", f"the model has more than {lim.triangles:,} triangles")
        if self.vertices > lim.vertices:
            raise lim.exceeded("vertices", f"the model has more than {lim.vertices:,} vertices")
        cap = self.options.max_triangles
        if cap is not None and self.triangles > cap:
            raise _Truncated()

    def add_object(self, obj: MeshObject) -> int:
        """Add a finished object; returns its index."""
        if len(self.objects) >= self.limits.objects:
            raise self.limits.exceeded("objects", f"the model has more than {self.limits.objects:,} objects")
        self.objects.append(obj)
        return len(self.objects) - 1

    def add_item(self, obj: int, instance: str | None = None, placement: Placement = IDENTITY) -> None:
        """Place ``objects[obj]``. A placement that is not finite, or lies farther than
        1,000 km out, is skipped; one that scales, shears or mirrors is kept and warned
        (``non_rigid_transform``)."""
        if not 0 <= obj < len(self.objects):
            raise SldFormatError("an item places an object the model does not have")
        if len(self.items) >= self.limits.items:
            raise self.limits.exceeded("items", f"the model places more than {self.limits.items:,} items")
        if not placement.is_finite():
            self.skip(instance, "non_finite_placement", "its placement is not finite")
            return
        if any(abs(v) > MAX_COORDINATE_M for v in placement.translation_m):
            self.skip(instance, "out_of_range", "it would lie more than 1,000 km from the origin")
            return
        if not _rigid(placement.rotation) and not any(w.code == "non_rigid_transform" for w in self.warnings):
            self.warnings.append(
                ReaderWarning(
                    "non_rigid_transform",
                    "a placement scales, shears or mirrors its object; it is kept as stored",
                )
            )
        self.items.append(SceneItem(obj, instance, placement))
        self.clock.tick()

    def skip(self, instance: str | None, reason: str, message: str = "") -> None:
        self.skipped.append(SkippedItem(instance, reason, message))

    def missing_component(self, instance: str | None, message: str) -> None:
        """A component that could not be found or read: skipped, with the warning
        ``component_not_found`` (once a document, with the count)."""
        self.skip(instance, "component_not_found", message)
        n = sum(1 for s in self.skipped if isinstance(s, SkippedItem) and s.reason == "component_not_found")
        self.warnings = [w for w in self.warnings if w.code != "component_not_found"]
        self.warnings.append(
            ReaderWarning(
                "component_not_found", f"{n} component(s) could not be found or read and are left out"
            )
        )

    def warn(self, code: str, message: str, stream: str | None = None) -> None:
        self.warnings.append(ReaderWarning(code, message, stream))

    def build(self, truncated: Iterable[str] = ()) -> Scene:
        placed = sum(self.objects[it.object].n_triangles for it in self.items)
        counts: dict[str, int | None] = {
            "objects": len(self.objects),
            "items": len(self.items),
            "vertices": sum(o.n_vertices for o in self.objects),
            "triangles": placed,
            **self.counts,
        }
        return Scene(
            tuple(self.objects),
            tuple(self.items),
            counts,
            tuple(truncated),
            tuple(self.skipped),
            tuple(self.warnings),
        )


def _rigid(r: Sequence[Sequence[float]], tol: float = 1e-6) -> bool:
    """Whether a rotation matrix is orthonormal with determinant +1."""
    for i in range(3):
        for j in range(3):
            dot = sum(r[k][i] * r[k][j] for k in range(3))
            if abs(dot - (1.0 if i == j else 0.0)) > tol:
                return False
    det = (
        r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1])
        - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
        + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0])
    )
    return det > 0.0


class MeshBuilder:
    """Collects one object's vertices and triangles (see the module notes).

    ``add_vertices`` and ``add_triangles`` (or ``add_vertex`` and ``add_triangle``)
    build an indexed mesh; ``add_soup`` adds triangles of three new vertices each
    (an STL's), which need no index check. :meth:`build` drops triangles naming a
    vertex the mesh lacks (``indices_out_of_range``), those with a repeated or
    non-finite corner (``degenerate_triangles_dropped``) and those with a corner
    more than 1,000 km (:data:`MAX_COORDINATE_M`) from the object's origin
    (``coordinates_out_of_range``: no part lies there, and no later sum or square
    of such numbers can overflow), scales to metres and returns the
    :class:`MeshObject`; :meth:`finish` also adds it to the scene."""

    def __init__(
        self,
        scene: SceneBuilder,
        *,
        name: str | None,
        source: str,
        scale_m: float,
        color: Color | None,
        node: str | None,
    ) -> None:
        if source not in MESH_SOURCES:
            raise ValueError(f"unknown mesh source {source!r}")
        if not (isinstance(scale_m, (int, float)) and math.isfinite(scale_m) and scale_m > 0):
            raise SldFormatError("the unit of length is not a positive number")
        self.scene = scene
        self.name = name
        self.source = source
        self.scale_m = float(scale_m)
        self.color = color
        self.node = node
        self.positions = array("d")
        self.triangles = array("I")
        self.normals: array | None = None
        self._indexed = False

    @property
    def n_vertices(self) -> int:
        return len(self.positions) // 3

    def add_vertices(self, xyz: Iterable[float]) -> int:
        """Append vertices (x, y, z, x, y, z...); returns the index of the first."""
        first = self.n_vertices
        before = len(self.positions)
        self.positions.extend(xyz)
        added = len(self.positions) - before
        if added % 3:
            raise SldFormatError("vertex coordinates do not come in threes")
        self.scene.take(0, added // 3)
        self.scene.clock.tick(added // 3 or 1)
        return first

    def add_vertex(self, x: float, y: float, z: float) -> int:
        return self.add_vertices((x, y, z))

    def add_triangles(self, indices: Iterable[int]) -> None:
        """Append triangles as index triples into this object's vertices."""
        before = len(self.triangles)
        try:
            self.triangles.extend(indices)
        except OverflowError:
            raise SldFormatError("a vertex index is negative or too large") from None
        added = len(self.triangles) - before
        if added % 3:
            raise SldFormatError("triangle indices do not come in threes")
        self._indexed = True
        self.scene.take(added // 3, 0)
        self.scene.clock.tick(added // 3 or 1)

    def add_triangle(self, a: int, b: int, c: int) -> None:
        self.add_triangles((a, b, c))

    def add_soup(self, xyz: Iterable[float]) -> None:
        """Append triangles of three new vertices each: nine numbers a triangle."""
        before = len(self.positions)
        self.positions.extend(xyz)
        added = len(self.positions) - before
        if added % 9:
            raise SldFormatError("triangle corners do not come in nines")
        n = added // 9
        first = before // 3
        self.triangles.extend(range(first, first + 3 * n))
        self.scene.take(n, 3 * n)
        self.scene.clock.tick(n or 1)

    def set_normals(self, normals: Iterable[float]) -> None:
        """Per-vertex normals (three numbers a vertex), kept when there is one a vertex."""
        self.normals = array("f", normals)

    def build(self) -> MeshObject:
        p, t = self.positions, self.triangles
        n = len(p) // 3
        warnings: list[ReaderWarning] = []
        bad: set[int] = set()  # vertices not finite, or farther out than MAX_COORDINATE_M
        far: set[int] = set()
        reach = MAX_COORDINATE_M / self.scale_m  # in the file's own unit
        if p and (not math.isfinite(sum(p)) or max(p) > reach or min(p) < -reach):
            bad = {i // 3 for i, v in enumerate(p) if not -reach <= v <= reach}  # NaN fails too
            far = {i // 3 for i, v in enumerate(p) if math.isfinite(v) and abs(v) > reach}
        oob = degenerate = out_of_range = 0
        if self._indexed or bad:
            kept = array("I")
            for k in range(0, len(t), 3):
                a, b, c = t[k], t[k + 1], t[k + 2]
                if a >= n or b >= n or c >= n:
                    oob += 1
                elif bad and (a in bad or b in bad or c in bad):
                    if far and (a in far or b in far or c in far):
                        out_of_range += 1
                    else:
                        degenerate += 1
                elif a == b or b == c or a == c:
                    degenerate += 1
                else:
                    kept.extend((a, b, c))
                if not k % 12288:
                    self.scene.clock.tick(4096)
            t = kept
        normals = self.normals if self.normals is not None and len(self.normals) == len(p) else None
        if bad:  # the vertices not finite or out of range go, so no measure ever sees them
            used = sorted(set(t))
            new = {v: i for i, v in enumerate(used)}
            p = array("d", (p[3 * v + j] for v in used for j in range(3)))
            if normals is not None:
                normals = array("f", (normals[3 * v + j] for v in used for j in range(3)))
            t = array("I", (new[v] for v in t))
        if oob:
            warnings.append(
                ReaderWarning(
                    "indices_out_of_range", f"{oob} triangles name a vertex the mesh lacks; left out"
                )
            )
        if degenerate:
            warnings.append(
                ReaderWarning(
                    "degenerate_triangles_dropped",
                    f"{degenerate} triangles with a repeated or non-finite corner were left out",
                )
            )
        if out_of_range:
            warnings.append(
                ReaderWarning(
                    "coordinates_out_of_range",
                    f"{out_of_range} triangles with a corner more than 1,000 km from the object's origin "
                    "were left out",
                )
            )
        if self.scale_m != 1.0:
            p = array("d", map(self.scale_m.__mul__, p))
        return MeshObject(self.name, p, t, normals, self.color, self.source, self.node, tuple(warnings))

    def finish(self) -> int:
        """:meth:`build`, added to the scene; returns the object's index."""
        return self.scene.add_object(self.build())


# --------------------------------------------------------------------------- the documents
def make_property(name: str, value: Any, *, type: str | None = None, text: str | None = None) -> Property:
    """A file-scope :class:`Property` for a model file. ``type`` defaults from the value:
    ``text`` for a string, ``number`` for an int or a float, ``boolean`` for a bool and
    ``date`` for a datetime."""
    import datetime

    if type is None:
        if isinstance(value, bool):
            type = "boolean"
        elif isinstance(value, (int, float)):
            type = "number"
        elif isinstance(value, datetime.datetime):
            type = "date"
        elif isinstance(value, str):
            type = "text"
        else:
            type = "other"
    if type not in PROPERTY_TYPES:
        type = "other"
    if text is None:
        text = (
            value.isoformat()
            if isinstance(value, datetime.datetime)
            else (None if value is None else str(value))
        )
    return Property(
        name=name,
        value=value,
        text=text,
        type=type,
        expression=None,
        linked=False,
        expression_source=None,
        pid=0,
        vt=None,
    )


class ModelDocument:
    """One 3D file read-only (see the module notes). Create it with :func:`open_model`;
    close it, or use ``with``. Not thread-safe.

    Head attributes, set by the reader when it opens: ``format`` (registry id),
    ``variant``, ``doc_type`` (``part``, ``assembly`` or None: an assembly when the
    file has product structure, a part otherwise, however many objects it holds),
    ``kind`` (``mesh``, ``brep`` or ``mixed``), ``units`` (``length``, ``scale_m``,
    ``source``), ``application`` (``name``, ``version``), ``fields``
    (:class:`SummaryFields`), ``properties`` (file-scope :class:`Property` objects),
    ``configurations`` (always empty), ``active_configuration`` and ``warnings``.
    ``refuse_hard_links``, ``max_file_bytes`` and ``subfolders`` are those it was opened
    with; a file it names (a buffer, a material library, a component) is opened under
    them too."""

    format: str = ""

    def __init__(
        self,
        source: Source,
        *,
        name: str | None,
        path: str | None,
        file_info: FileInfo | None,
        limits: Limits,
        detection: registry.Detection | None = None,
    ) -> None:
        self._source = source
        self.path = path
        self.name: str | None = name if name is not None else (os.path.basename(path) if path else None)
        self.file_info = file_info
        self.limits = limits
        self.detection = detection
        # how the document was opened: the files it names are opened under the same rules
        self.refuse_hard_links: bool = bool(getattr(source, "refuse_hard_links", False))
        self.max_file_bytes: int | None = getattr(source, "max_file_bytes", None)
        self.subfolders: bool = bool(getattr(source, "subfolders", True))
        spec = registry.FORMATS.get(self.format)
        self.variant: str | None = detection.variant if detection is not None else None
        self.doc_type: str | None = "part"
        self.kind: str = spec.kind if spec is not None else "mesh"
        self.units: dict[str, Any] = {"length": None, "scale_m": None, "source": None}
        self.application: dict[str, Any] = {"name": None, "version": None}
        self.fields = SummaryFields()
        self.properties: list[Property] = []
        self.configurations: list[Any] = []
        self.active_configuration: str | None = None
        self.warnings: list[ReaderWarning] = []
        self._scene_cache: tuple[SceneOptions, Scene] | None = None
        self._trees: dict[tuple[int, int], ModelTree] = {}
        self._refs_cache: list[ExternalReference] | None = None

    # lifecycle ---------------------------------------------------------------------
    def close(self) -> None:
        self._source.close()

    def __enter__(self) -> "ModelDocument":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<ModelDocument {self.format} {self.doc_type} {self.name or '<memory>'!r}>"

    # head ------------------------------------------------------------------------------
    @property
    def spec(self) -> registry.FormatSpec:
        return registry.FORMATS[self.format]

    @property
    def format_name(self) -> str:
        spec = registry.FORMATS.get(self.format)
        return spec.name if spec is not None else self.format

    @property
    def source(self) -> Source:
        """The document's bytes, for its reader."""
        return self._source

    def set_units(self, length: str | None, source: str) -> None:
        """Set ``units`` from a length token of :data:`UNIT_SCALE` (None: unknown)."""
        if source not in UNIT_SOURCES:
            raise ValueError(f"unknown unit source {source!r}")
        scale = UNIT_SCALE.get(length) if length is not None else None
        self.units = {"length": length if scale is not None else None, "scale_m": scale, "source": source}

    def warn(self, code: str, message: str, stream: str | None = None) -> None:
        self.warnings.append(ReaderWarning(code, message, stream))

    def counts(self) -> dict[str, int | None]:
        """What the head knows of the model's size: every key of :data:`HEAD_COUNTS`,
        None where it would need a full read."""
        out: dict[str, int | None] = dict.fromkeys(HEAD_COUNTS)
        got = guarded(self._counts) or {}
        out.update({k: v for k, v in got.items() if k in out})
        return out

    # full reads ---------------------------------------------------------------------------
    def tree(self, *, max_nodes: int = DEFAULT_MAX_NODES, max_depth: int = DEFAULT_MAX_DEPTH) -> ModelTree:
        """The model's tree: components and objects with their placements, parents before
        children, at most ``max_nodes`` nodes (and ``limits.tree_nodes``) and
        ``max_depth`` levels, then ``truncated``."""
        for value, what in ((max_nodes, "max_nodes"), (max_depth, "max_depth")):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise InvalidArgumentError(
                    f"{what} must be a positive whole number", detail={"parameter": what}
                )
        key = (max_nodes, max_depth)
        hit = self._trees.get(key)
        if hit is not None:
            return hit
        clock = Clock(self.limits.seconds)
        got = guarded(self._tree, clock)
        nodes = list(got.nodes if isinstance(got, ModelTree) else got)
        truncated = bool(got.truncated) if isinstance(got, ModelTree) else False
        cap = min(max_nodes, self.limits.tree_nodes)
        depth_cap = min(max_depth, self.limits.depth)
        depth: dict[str, int] = {}
        kept: list[ModelNode] = []
        for nd in nodes:
            d = depth.get(nd.parent, 0) + 1 if nd.parent is not None else 1
            if nd.parent is not None and nd.parent not in depth:
                truncated = True  # its parent was cut
                continue
            if d > depth_cap or len(kept) >= cap:
                truncated = True
                continue
            depth[nd.id] = d
            kept.append(nd)
        tree = ModelTree(tuple(kept), truncated)
        self._trees[key] = tree
        return tree

    def scene(
        self,
        *,
        prefer: str = "bodies",
        max_triangles: int | None = None,
        chord_m: float | None = None,
        chord_fraction: float | None = None,
        max_chord_m: float | None = None,
        angle_deg: float = 15.0,
        max_seconds: float = 30.0,
        body_types: Collection[str] = ("solid", "sheet"),
        roots: Iterable[str] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> Scene:
        """The model as meshes in metres and the items that place them (:class:`Scene`).

        ``prefer`` is ``bodies`` (export and 3D printing: tessellate the B-rep, the
        stored display mesh only as a fallback) or ``display`` (the 3D view and
        thumbnails: a stored display mesh first). ``max_triangles`` stops the read
        once the objects hold more triangles (``truncated`` says ``max_triangles``;
        what was finished is kept); ``limits.triangles`` raises instead. ``chord_m``,
        ``chord_fraction``, ``max_chord_m``, ``angle_deg`` and ``body_types`` are the
        tessellation's options for B-rep formats; ``max_seconds`` bounds the call and
        ``cancelled`` stops it (``ReadCancelledError``); ``roots`` are further folders
        where an assembly's component files may be found."""
        if prefer not in PREFER:
            raise InvalidArgumentError("prefer is bodies or display", detail={"parameter": "prefer"})
        if max_triangles is not None and (
            isinstance(max_triangles, bool) or not isinstance(max_triangles, int) or max_triangles < 1
        ):
            raise InvalidArgumentError(
                "max_triangles must be a positive whole number", detail={"parameter": "max_triangles"}
            )
        for value, what in (
            (chord_m, "chord_m"),
            (chord_fraction, "chord_fraction"),
            (max_chord_m, "max_chord_m"),
        ):
            if value is not None and not _positive(value):
                raise InvalidArgumentError(f"{what} must be a positive number", detail={"parameter": what})
        if not _positive(angle_deg) or not 0.5 <= angle_deg <= 90.0:
            raise InvalidArgumentError("angle_deg must be from 0.5 to 90", detail={"parameter": "angle_deg"})
        if not _positive(max_seconds):
            raise InvalidArgumentError(
                "max_seconds must be a positive number", detail={"parameter": "max_seconds"}
            )
        types = tuple(body_types)
        if not types or any(t not in BODY_TYPES for t in types):
            raise InvalidArgumentError(
                f"body_types takes {', '.join(BODY_TYPES)}", detail={"parameter": "body_types"}
            )
        if cancelled is not None and not callable(cancelled):
            raise InvalidArgumentError("cancelled is a callable", detail={"parameter": "cancelled"})
        folders = tuple(os.fspath(r) for r in (roots or ()))
        options = SceneOptions(
            prefer,
            max_triangles,
            chord_m,
            chord_fraction,
            max_chord_m,
            float(angle_deg),
            float(max_seconds),
            types,
            folders,
        )
        if self._scene_cache is not None and self._scene_cache[0] == options:
            return self._scene_cache[1]
        sb = SceneBuilder(self.limits, options, Clock(max_seconds, cancelled))
        truncated: tuple[str, ...] = ()
        try:
            guarded(self._scene, sb)
        except _Truncated:
            truncated = ("max_triangles",)
        scene = sb.build(truncated)
        self._scene_cache = (options, scene)
        return scene

    def bodies(self, *, max_seconds: float = 30.0) -> list[BodyRef] | None:
        """The B-rep bodies as in-memory Parasolid transmits, or None for a format that
        holds no B-rep."""
        if not _positive(max_seconds):
            raise InvalidArgumentError(
                "max_seconds must be a positive number", detail={"parameter": "max_seconds"}
            )
        got = guarded(self._bodies, Clock(max_seconds))
        return None if got is None else list(got)

    def preview(self, prefer: str = "png") -> Any:
        """The preview image the file stores, as stored (a
        :class:`~solidseas.formats.solidworks.Preview`), or None. ``prefer`` is
        accepted for symmetry with SOLIDWORKS documents (``png`` or ``dib``)."""
        if prefer not in ("png", "dib"):
            raise InvalidArgumentError("prefer is png or dib", detail={"parameter": "prefer"})
        return guarded(self._preview)

    def references(self) -> list[ExternalReference]:
        """The files the document names, at most ``limits.references``."""
        if self._refs_cache is None:
            got = list(guarded(self._references, Clock(self.limits.seconds)) or [])
            if len(got) > self.limits.references:
                raise self.limits.exceeded(
                    "references", f"the document names more than {self.limits.references:,} files"
                )
            self._refs_cache = got
        return list(self._refs_cache)

    def summary(self, include: Collection[str] = ("properties", "tree")) -> dict[str, Any]:
        """``model_summary`` data (``docs/API.md`` 5.16), exactly what the CLI and REST
        send. ``include`` names the optional parts: ``properties``, ``tree`` and
        ``references``; a part left out is null."""
        from .. import model

        return model.build_model_summary(self, include=include)

    # hooks a reader implements -------------------------------------------------------------
    def _counts(self) -> dict[str, int | None]:
        """Header counts the head knows (keys of :data:`HEAD_COUNTS`)."""
        return {}

    def _tree(self, clock: Clock) -> ModelTree | list[ModelNode]:
        """The tree; by default one ``object`` node per scene object is not known
        without the scene, so the document itself is one node."""
        return [ModelNode("1", None, _stem(self.name), "object", 0)]

    def _scene(self, sb: SceneBuilder) -> None:
        """Fill ``sb`` (its ``options`` and ``clock`` are the call's) with objects and items."""
        raise NotImplementedError

    def _bodies(self, clock: Clock) -> list[BodyRef] | None:
        return None

    def _preview(self) -> Any:
        return None

    def _references(self, clock: Clock) -> list[ExternalReference]:
        return []


HEAD_COUNTS = (
    "objects",
    "items",
    "bodies",
    "faces",
    "triangles",
    "vertices",
    "components",
    "references",
    "model_parts",
)


def _positive(value: Any) -> bool:
    return (
        not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value > 0
    )


def _stem(name: str | None) -> str | None:
    if not name:
        return None
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    stem, ext = os.path.splitext(base)
    return stem if ext and registry.by_extension(ext) is not None else base


@runtime_checkable
class AnyDocument(Protocol):
    """What a SOLIDWORKS :class:`~solidseas.formats.solidworks.Document` and a
    :class:`ModelDocument` both offer."""

    path: str | None
    name: str | None

    @property
    def file_info(self) -> FileInfo | None: ...

    @property
    def doc_type(self) -> str | None: ...

    @property
    def fields(self) -> SummaryFields: ...

    @property
    def properties(self) -> list[Property]: ...

    @property
    def warnings(self) -> list[ReaderWarning]: ...

    def preview(self, *args: Any, **kwargs: Any) -> Any: ...

    def summary(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...

    def close(self) -> None: ...

    def __enter__(self) -> Any: ...

    def __exit__(self, *exc: Any) -> None: ...


# --------------------------------------------------------------------------- opening
def _check_args(name: Any, format: Any) -> None:
    if name is not None and not isinstance(name, str):
        raise InvalidArgumentError("name must be a string", detail={"parameter": "name"})
    if format is not None and (not isinstance(format, str) or format not in registry.FORMATS):
        raise InvalidArgumentError(
            f"format is one of {', '.join(sorted(registry.FORMATS))}", detail={"parameter": "format"}
        )


def enabled_formats(formats: Any) -> frozenset[str] | None:
    """The format ids a call may read: None (every format) for None, else ``formats``
    (``"all"``, an id, comma-separated ids or ids) as :func:`registry.select` reads it."""
    return None if formats is None else registry.select(formats)


def _display_name(src: Any, name: str | None) -> str | None:
    if name is not None:
        return name
    if isinstance(src, (bytes, bytearray, memoryview)):
        return None
    return os.path.basename(os.fspath(src))


def _open(
    src: Any,
    *,
    name: str | None,
    format: str | None,
    within: Any,
    max_file_bytes: int | None,
    refuse_hard_links: bool,
    hold_open: bool,
    limits: Any,
    allow_solidworks: bool,
    unknown: UnknownFormatError | None = None,
    formats: Any = None,
    subfolders: bool = True,
) -> Any:
    lim = check_limits(limits)
    max_file_bytes = check_max_file_bytes(max_file_bytes)
    allowed = enabled_formats(formats)
    source, path, info = open_source(
        src,
        within=within,
        max_file_bytes=max_file_bytes,
        refuse_hard_links=bool(refuse_hard_links),
        hold_open=hold_open,
        limits=lim,
        subfolders=bool(subfolders),
    )
    try:
        shown = name if name is not None else (os.path.basename(path) if path else None)
        head = source.head(registry.HEAD_BYTES)
        if format is not None:
            detection = registry.detect_as(format, head, source.size, shown)
        else:
            detection = registry.detect_head(head, source.size, shown)
        fid = detection.format
        if unknown is not None and (fid is None or fid == registry.SOLIDWORKS or not registry.readable(fid)):
            raise unknown  # a SOLIDWORKS name whose content SolidSeas cannot read otherwise either
        if fid is None:
            raise UnknownFormatError(
                f"{path or '<memory>'}: SolidSeas does not know this file's format",
                detail={"rule": "unidentified"},
            )
        if allowed is not None and fid not in allowed:
            raise FormatNotSupportedError(
                f"the file holds {registry.FORMATS[fid].name} data, a format not read here",
                detail={"rule": "format_not_enabled", "value": fid},
            )
        if fid == registry.SOLIDWORKS:
            if not allow_solidworks:
                raise InvalidArgumentError(
                    "a SOLIDWORKS document: open it with open_document or open_any",
                    detail={"parameter": "src", "rule": "solidworks_document"},
                )
            from .solidworks import open_document

            if path is None:  # bytes: hand them on
                data = source.read_all(lim.whole_read_bytes, "whole_read_bytes")
                return open_document(data, name=name, max_file_bytes=max_file_bytes)
            source.close()  # a path: open_document opens it again, as it always does
            return open_document(
                path,
                name=name,
                within=within,
                max_file_bytes=max_file_bytes,
                refuse_hard_links=refuse_hard_links,
                hold_open=hold_open,
            )
        opener = registry.reader(fid)
        if opener is None:
            spec = registry.FORMATS[fid]
            if spec.backend is not None:
                from ..convert import unavailable

                reason = unavailable(fid)
                if reason is not None:
                    raise FormatNotSupportedError(reason, detail={"rule": "needs_extension", "value": fid})
            raise FormatNotSupportedError(
                f"SolidSeas cannot read {spec.name} files yet", detail={"rule": "no_reader", "value": fid}
            )
        doc = guarded(
            opener,
            source,
            name=shown,
            path=path,
            file_info=info,
            limits=lim,
            hold_open=hold_open,
            detection=detection,
        )
        if detection.mismatch:
            spec = registry.by_extension(shown)
            said = spec.name if spec else "what its extension says"
            doc.warn(
                "extension_mismatch",
                f"the file holds {doc.format_name} data, not {said}; it is read as what it holds",
            )
        return doc
    except BaseException:
        source.close()
        raise


def open_model(
    src: Any,
    *,
    name: str | None = None,
    format: str | None = None,
    within: Any = None,
    max_file_bytes: int | None = None,
    refuse_hard_links: bool = False,
    hold_open: bool = False,
    limits: Any = None,
    formats: Any = None,
    subfolders: bool = True,
) -> ModelDocument:
    """Open a 3D file that is not a SOLIDWORKS document, read-only (provisional).

    ``src`` is a path or the bytes of a whole file; ``name`` the display name and the
    extension hint (default: the path's file name). The format comes from the
    content and the name (:func:`solidseas.formats.registry.detect`); ``format``
    forces a reader. ``within``, ``max_file_bytes``, ``refuse_hard_links`` and
    ``hold_open`` behave as for ``open_document``; ``limits`` (a :class:`Limits`)
    overrides any bound. ``formats`` names the formats this call may read (``"all"``,
    an id, comma-separated ids or ids; None: every one): a file whose content is
    another is refused, whatever its name says. ``subfolders`` false keeps the files the
    document names (a glTF buffer, an OBJ material library, an Alibre component) to
    its own folder, as a service root served without its subfolders needs.

    Raises what ``open_document`` raises, plus
    :class:`~solidseas.errors.FormatNotSupportedError` for a format SolidSeas
    knows but cannot read (``detail["rule"]`` ``no_reader``), content of a format
    ``formats`` leaves out (``format_not_enabled``, ``detail["value"]`` the format it
    holds) or a feature that stops this document; an unidentified file raises
    ``UnknownFormatError`` (``detail["rule"]`` ``unidentified``), and a SOLIDWORKS
    document ``InvalidArgumentError`` (use :func:`open_any`)."""
    _check_args(name, format)
    return _open(
        src,
        name=name,
        format=format,
        within=within,
        max_file_bytes=max_file_bytes,
        refuse_hard_links=refuse_hard_links,
        hold_open=hold_open,
        limits=limits,
        allow_solidworks=False,
        formats=formats,
        subfolders=subfolders,
    )


def open_any(
    src: Any,
    *,
    name: str | None = None,
    format: str | None = None,
    within: Any = None,
    max_file_bytes: int | None = None,
    refuse_hard_links: bool = False,
    hold_open: bool = False,
    limits: Any = None,
    formats: Any = None,
    subfolders: bool = True,
) -> Any:
    """A SOLIDWORKS :class:`~solidseas.formats.solidworks.Document` for a SOLIDWORKS
    file, else a :class:`ModelDocument` (provisional). A file with a SOLIDWORKS
    extension is opened by ``open_document`` exactly as before; only when that
    finds no SOLIDWORKS container and the content is a format SolidSeas reads is
    it read as that format (with the warning ``extension_mismatch``), else the
    ``UnknownFormatError`` stands. With ``formats`` leaving SOLIDWORKS out, such a
    file goes by its content alone. The arguments are those of :func:`open_model`."""
    _check_args(name, format)
    shown = _display_name(src, name)
    spec = registry.by_extension(shown)
    allowed = enabled_formats(formats)
    named = format == registry.SOLIDWORKS or (
        format is None and spec is not None and spec.id == registry.SOLIDWORKS
    )
    if named and (allowed is None or registry.SOLIDWORKS in allowed):
        from .solidworks import open_document

        try:
            return open_document(
                src,
                name=name,
                within=within,
                max_file_bytes=max_file_bytes,
                refuse_hard_links=refuse_hard_links,
                hold_open=hold_open,
            )
        except UnknownFormatError as exc:
            if format == registry.SOLIDWORKS:
                raise
            unknown = exc
        return _open(
            src,
            name=name,
            format=None,
            within=within,
            max_file_bytes=max_file_bytes,
            refuse_hard_links=refuse_hard_links,
            hold_open=hold_open,
            limits=limits,
            allow_solidworks=False,
            unknown=unknown,
            formats=allowed,
            subfolders=subfolders,
        )
    return _open(
        src,
        name=name,
        format=format,
        within=within,
        max_file_bytes=max_file_bytes,
        refuse_hard_links=refuse_hard_links,
        hold_open=hold_open,
        limits=limits,
        allow_solidworks=True,
        formats=allowed,
        subfolders=subfolders,
    )


def is_model(doc: Any) -> bool:
    """Whether ``doc`` is a :class:`ModelDocument` (not a SOLIDWORKS document)."""
    return isinstance(doc, ModelDocument)


__all__ = [
    "BODY_TYPES",
    "HEAD_COUNTS",
    "MESH_SOURCES",
    "NODE_KINDS",
    "SCENE_COUNTS",
    "UNIT_SCALE",
    "AnyDocument",
    "BodyRef",
    "ExternalReference",
    "MeshBuilder",
    "MeshObject",
    "ModelDocument",
    "ModelNode",
    "ModelTree",
    "Scene",
    "SceneBuilder",
    "SceneItem",
    "SceneOptions",
    "SkippedItem",
    "enabled_formats",
    "guarded",
    "is_model",
    "make_property",
    "open_any",
    "open_model",
]
