"""An assembly's display geometry: every instance to draw, placed, and the meshes they share.

:func:`display_geometry` (provisional, ``docs/API.md`` section 3.14) expands one
configuration of an assembly's component tree and returns each unsuppressed,
visible part instance with its placement in the top assembly's frame, plus one
triangle mesh per component file (strictly, per source of a mesh), which every
instance of that file shares. What it cannot place or mesh is listed with the
reason, its placement and the box the assembly stores for it, so a viewer can
draw a box in its place. Nothing is written, and every read is bounded.

A sub-assembly whose components the top assembly's tree does not list is
expanded from the sub-assembly's own document, in the configuration the
instance uses, its placements composed as :meth:`Document.components` composes
them; the limits on instances and depth, and the protection against a document
that contains itself, hold across documents. When that document cannot be found
or read, or lists no components, the sub-assembly is skipped with the reason.

Where a mesh comes from, in the order ``sources`` gives (by default all five):

* ``"assembly"``: the mesh the assembly itself stores of that component, in the
  component's own coordinates (:mod:`.formats.solidworks.facetess`): one per
  instance in ``FaceTessellations/*`` (SOLIDWORKS 2023 and later), shared by
  the instances of one file, or one per file in an older assembly's own
  ``Contents/DisplayLists``. Both layouts are a HYPOTHESIS checked on the
  fixtures and the development corpus (``docs/FORMAT.md`` 12.3). The
  ``FaceTessellations`` meshes describe the configuration that was active when
  the assembly was saved, so an instance of another configuration uses one only
  when, at the same place in the active configuration, the same file is used in
  the same configuration. An older assembly's section is used only for a file
  that the tree uses in one configuration and whose stored path opens exactly
  one section, or several of which exactly one holds face tables (the others
  mention the path and hold none); a section ends at the next stored path of
  any file the component tree names, and at a header that names another of
  those files under another folder (where it was when that section was written).
* ``"nested"``: the display mesh of the document stored inside the assembly, for
  a virtual or an embedded imported component; a virtual component stored in a
  sub-assembly's own file is read from that sub-assembly.
* ``"file"``: the display mesh of the component's own file, found by reference
  resolution (:mod:`solidseas.resolve`) inside ``roots`` and opened read-only
  ``within`` its root, or its own folder outside the roots, as resolution's
  identity reads open it. A part stores the mesh of the configuration active
  when it was saved; when an instance uses another, the mesh source carries
  the warning ``mesh_configuration_differs``. A file found for several
  instances, of the top assembly or of sub-assemblies read from their own
  files, is opened and read once.
* ``"subassembly"``: for an instance inside a sub-assembly, the mesh a
  sub-assembly above it stores of it in its own document, by the same rules:
  the record of the instance's path below that sub-assembly, or the section of
  its file, where the sub-assembly's active configuration has the same files in
  the same configurations at every level down to the instance. The
  sub-assemblies above it are tried from the top down, and one whose stored mesh
  turns out empty or unreadable passes to the next, so a part several levels
  down comes from whichever sub-assembly above it has it. The sub-assembly's
  document is found as the files are (on disk, or stored inside the top
  assembly or another sub-assembly) and opened read-only. It comes after the
  part's own file: the files opened go to part files first, and a part file
  saved after the sub-assembly shows the part as it is now.
* ``"brep"``: the part's own Parasolid bodies, tessellated
  (:mod:`solidseas.tessellate`), in the configuration the instance uses or,
  when the part stores no partition for it, its active one. The document is
  the one the ``"nested"`` or ``"file"`` source reads (the same open document,
  when the file source has just found no display mesh in it). It comes last,
  so that a stored mesh always wins. A part gets 30 s, reading its bodies
  included, and tessellating them stops when that is spent; no part is started
  once ``max_brep_seconds`` is spent over the call. Reading a part's bodies,
  once started, runs to its end, so a part or the call can run past its limit
  by that one read.

When a source fails for an instance (no stored mesh, the file is missing), the
next one is tried. Placements are those of :meth:`Document.components`, the
stored transforms composed through every parent, VERIFIED against SOLIDWORKS on
the fixture assemblies.
"""

import os
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, NamedTuple

from .errors import InvalidArgumentError, ReaderWarning
from .formats.solidworks import facetess
from .formats.solidworks.components import (
    DEFAULT_MAX_DEPTH,
    MAX_DEPTH_LIMIT,
    MAX_NODES_LIMIT,
    Box,
    ComponentFile,
    ComponentNode,
    Placement,
    parse_bounding_box,
)
from .formats.solidworks.document import open_document
from .formats.solidworks.mesh import MAX_DISPLAY_LIST_BYTES, Mesh, mesh_from_bytes
from .roots import Root, Roots

SOURCES = ("assembly", "nested", "file", "subassembly", "brep")
MESH_STREAM = "Contents/DisplayLists"
DEFAULT_MAX_INSTANCES = 100_000
DEFAULT_MAX_FILES = 2_000
DEFAULT_MAX_TRIANGLES = 20_000_000
DEFAULT_MAX_TRIANGLES_DRAWN = 1_000_000_000
DEFAULT_MAX_BYTES = 2 << 30
DEFAULT_MAX_BREP_SECONDS = 60.0
BREP_SECONDS_PER_PART = 30.0  # solidseas.tessellate's own default
DOCUMENT_ROOT_ID = "document"  # as solidseas.resolve names the document's folder

# Why an instance is not drawn. An open set, like every enum of SolidSeas.
REASONS = {
    "no_placement": "a stored transform on the way to it is unreadable or not finite",
    "model_missing": "the component tree names a model it does not hold",
    "cycle": "the sub-assembly contains itself, so it was not expanded again",
    "truncated": "a limit of the component tree stopped the expansion here",
    "no_components": "it is a sub-assembly whose own file lists no components for the configuration used",
    "no_source": "none of the mesh sources asked for applies to it",
    "no_mesh": "its document stores no display mesh",
    "not_part": "its file is not a part",
    "missing": "its file was not found",
    "ambiguous": "several files could be its file",
    "embedded_not_found": "it is a virtual component the assembly does not store",
    "unreadable": "its document could not be read",
    "max_files": "the limit on files opened was reached",
    "max_triangles": "the limit on triangles read was reached",
    "max_bytes": "the limit on display data read was reached",
    "max_drawn": "the limit on triangles drawn, each instance counting its mesh again, was reached",
    "brep_failed": "its document stores no display mesh, and its bodies could not be tessellated",
    "bodies_not_asked": "its document stores no display mesh, and none of its bodies is of a type asked for",
    "max_brep_seconds": "the time limit on tessellating parts' bodies was reached",
}
NO_MESH_NOR_BODIES = "its document stores neither a display mesh nor B-rep bodies"


def _matrix(placement: Placement) -> tuple[float, ...]:
    r, t = placement.rotation, placement.translation_m
    return (
        r[0][0], r[1][0], r[2][0], 0.0,
        r[0][1], r[1][1], r[2][1], 0.0,
        r[0][2], r[1][2], r[2][2], 0.0,
        t[0], t[1], t[2], 1.0,
    )  # fmt: skip


def _placed_box(placement: Placement, box: Box) -> Box:
    """``box`` (component coordinates) with its eight corners placed: the box holding them."""
    lo, hi = box
    pts = [placement.apply((x, y, z)) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    return (
        (min(q[0] for q in pts), min(q[1] for q in pts), min(q[2] for q in pts)),
        (max(q[0] for q in pts), max(q[1] for q in pts), max(q[2] for q in pts)),
    )


@dataclass(frozen=True)
class MeshSource:
    """One mesh, shared by every instance whose ``mesh`` is ``key``.

    ``kind`` is ``assembly``, ``subassembly``, ``nested``, ``file`` or ``brep`` (an
    open set); ``stream`` the stream it was read from, in the assembly (``assembly``,
    ``nested``), in the sub-assembly's document (``subassembly``) or in ``path``,
    the file on disk (``file``, and ``subassembly`` and ``nested`` for a document
    read from a sub-assembly's file). A ``brep`` mesh was tessellated from the
    Parasolid bodies of the part (:mod:`solidseas.tessellate`): ``stream`` is the
    partition or LocalBodies stream that held them, and ``path`` and ``nested`` say
    where the part's document is, as for ``file`` and ``nested``. ``nested`` lists
    the nested-document streams followed to that document. ``configuration`` is the
    configuration the mesh shows where that is known. ``mesh`` is in the
    component's own coordinates, metres. For a ``brep`` mesh ``chord_m`` is the chord
    tolerance it was tessellated at, and with ``keep_welded`` ``welded`` holds its
    triangles over shared float64 vertices, as
    :meth:`solidseas.tessellate.Tessellation.welded` gives them, closed where the
    bodies are; both are None for the other kinds."""

    key: str
    kind: str
    file: str | None
    stream: str
    path: str | None
    nested: tuple[str, ...]
    configuration: str | None
    mesh: Mesh
    warnings: tuple[ReaderWarning, ...] = ()
    welded: tuple[Any, Any] | None = field(default=None, repr=False, compare=False)
    chord_m: float | None = None

    @property
    def triangles(self) -> int:
        return self.mesh.n_triangles


@dataclass(frozen=True)
class PlacedInstance:
    """A part instance to draw: its component tree id and name, its file key and the
    configuration it uses, the key of its mesh in :attr:`DisplayGeometry.meshes`,
    and its placement from the component's frame to the top assembly's frame."""

    id: str
    name: str
    file: str | None
    configuration: str | None
    mesh: str
    placement: Placement

    def matrix(self) -> tuple[float, ...]:
        """The placement as a 4 x 4 matrix in column-major order (OpenGL's), metres."""
        return _matrix(self.placement)


@dataclass(frozen=True)
class SkippedInstance:
    """An unsuppressed, visible instance that is not drawn: ``reason`` is a key of
    :data:`REASONS` (an open set) and ``code`` the error code where a read failed.

    ``placement`` is where it would be drawn, from the component's frame to the top
    assembly's (None when a stored transform on the way is unreadable), and ``box``
    the box its assembly stores for that component in that configuration
    (``swBoundingBox`` of its model, ``docs/FORMAT.md`` 12.1), in the component's
    own coordinates, metres; None when not stored, not six finite numbers with each
    low end at most its high end, or when two models of that file and configuration
    disagree. Placed with the placement (:meth:`DisplayGeometry.placeholder`) it is a
    box to draw in the instance's place."""

    id: str
    name: str
    file: str | None
    reason: str
    message: str
    code: str | None = None
    placement: Placement | None = None
    box: Box | None = None

    def matrix(self) -> tuple[float, ...] | None:
        """The placement as a column-major 4 x 4 matrix, or None when unknown."""
        return _matrix(self.placement) if self.placement is not None else None


@dataclass(frozen=True)
class DisplayGeometry:
    """One assembly configuration, ready to draw. ``counts`` has ``instances`` (the
    component tree's, with the instances of the sub-assemblies expanded from their
    own files), ``parts`` (part instances, drawn or not, and each sub-assembly that
    could not be expanded counted once), ``placed``, ``suppressed``, ``hidden``,
    ``skipped``, ``meshes``, ``triangles_read`` (over the meshes),
    ``triangles_drawn`` (over the instances), ``files_opened``, ``bytes_read``
    (display data decoded), ``meshes_tessellated`` (meshes the ``brep`` source made)
    and ``brep_seconds`` (the time it took, a float, the one count that is not a
    whole number); ``placed + skipped + suppressed + hidden == parts``.
    ``truncated`` names each limit that stopped something. ``files`` are the
    component tree's files, by the file keys the instances name (the files of a
    sub-assembly expanded from its own file are keyed ``<its key>/<the key in its
    file>``), and ``resolution`` the reference resolution made for the top
    assembly's files read from disk (None when none was needed). ``file_failures``
    says, by file key, why the ``"file"`` source gave no mesh where it was tried (a
    key of :data:`REASONS`: ``missing``, ``ambiguous``, ``unreadable``, ``no_mesh``...),
    so an instance drawn from another source, what a sub-assembly stores of it say,
    can tell why its own file was not used."""

    configuration: str | None
    configuration_source: str
    instances: tuple[PlacedInstance, ...]
    meshes: dict[str, MeshSource]
    skipped: tuple[SkippedInstance, ...]
    counts: dict[str, int | float]
    truncated: tuple[str, ...]
    warnings: tuple[ReaderWarning, ...]
    files: dict[str, ComponentFile] = field(default_factory=dict)
    resolution: Any = None
    file_failures: dict[str, str] = field(default_factory=dict)
    # Each mesh's own box, measured once however many instances share the mesh.
    _mesh_boxes: dict[str, Box] = field(default_factory=dict, init=False, repr=False, compare=False)

    def mesh_box(self, key: str) -> Box:
        """The box of mesh ``key`` in its component's own coordinates, measured once."""
        box = self._mesh_boxes.get(key)
        if box is None:
            box = self.meshes[key].mesh.bbox() or ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
            self._mesh_boxes[key] = box
        return box

    def bounds(self, instance: PlacedInstance, *, exact: bool = False) -> Box:
        """The instance's box in the top assembly's frame: of its mesh's box corners
        (:meth:`mesh_box`, so each instance costs eight points), or with ``exact`` of
        every vertex."""
        if not exact:
            return _placed_box(instance.placement, self.mesh_box(instance.mesh))
        place = instance.placement.apply
        p = self.meshes[instance.mesh].mesh.positions
        pts = [place((p[i], p[i + 1], p[i + 2])) for i in range(0, len(p), 3)]
        return (
            (min(q[0] for q in pts), min(q[1] for q in pts), min(q[2] for q in pts)),
            (max(q[0] for q in pts), max(q[1] for q in pts), max(q[2] for q in pts)),
        )

    def placeholder(self, skipped: SkippedInstance) -> Box | None:
        """Where a skipped instance would be: its stored box with the eight corners
        placed, in the top assembly's frame, or None when its placement or its box is
        unknown."""
        if skipped.placement is None or skipped.box is None:
            return None
        return _placed_box(skipped.placement, skipped.box)

    def bbox(self, *, exact: bool = False) -> Box | None:
        """The box of every placed instance (:meth:`bounds`), or None when none is: in
        time the meshes' vertices once plus eight points an instance, or with ``exact``
        every instance's vertices."""
        out: Box | None = None
        for inst in self.instances:
            lo, hi = self.bounds(inst, exact=exact)
            if out is None:
                out = (lo, hi)
            else:
                out = (
                    (min(out[0][0], lo[0]), min(out[0][1], lo[1]), min(out[0][2], lo[2])),
                    (max(out[1][0], hi[0]), max(out[1][1], hi[1]), max(out[1][2], hi[2])),
                )
        return out


class _Failed(Exception):
    def __init__(self, reason: str, message: str | None = None, code: str | None = None) -> None:
        super().__init__(reason)
        self.reason, self.message, self.code = reason, message or REASONS.get(reason, reason), code


_SOURCE_LIMITS = ("max_files", "max_triangles", "max_bytes", "max_brep_seconds")
# A source stopped by a limit: one of those, or ``truncated`` when the instance limit
# stopped the reading of a sub-assembly's own tree before the instance was looked up.
_LIMITED = (*_SOURCE_LIMITS, "truncated")
_STORED_KINDS = ("assembly", "subassembly")
_BREP_FAILURES = ("brep_failed", "bodies_not_asked")


def _reported(before: _Failed, now: _Failed, kind: str) -> _Failed:
    """Which of two sources' failures an instance reports. A limit wins: with a higher
    one the instance would be drawn, whatever the next source then said. A part's
    bodies that failed say more than a later source finding no display mesh in the
    same document. Otherwise a file's or a nested document's reason says more than an
    assembly's stored meshes."""
    if (before.reason in _LIMITED) != (now.reason in _LIMITED):
        return before if before.reason in _LIMITED else now
    if now.reason == "no_mesh" and (before.reason in _BREP_FAILURES or before.message == NO_MESH_NOR_BODIES):
        return before
    return now if kind not in _STORED_KINDS else before


def _count(value: Any, name: str, low: int, high: int | None = None) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < low
        or (high is not None and value > high)
    ):
        span = f"from {low} to {high}" if high is not None else f"of at least {low}"
        raise InvalidArgumentError(f"{name} must be a whole number {span}", detail={"parameter": name})
    return value


def _seconds(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1e6:
        raise InvalidArgumentError(
            f"{name} must be a number of seconds from 0 to 1e6", detail={"parameter": name}
        )
    return float(value)


def _roots_of(doc, roots) -> Roots | None:
    if roots is None:
        if not doc.path:
            return None
        return Roots([Root(DOCUMENT_ROOT_ID, os.path.dirname(os.path.abspath(doc.path)))])
    if isinstance(roots, Roots):
        return roots
    if isinstance(roots, Mapping):
        return Roots.from_mapping(roots)
    if isinstance(roots, Root):
        return Roots([roots])
    if isinstance(roots, Iterable) and not isinstance(roots, (str, bytes)):
        return Roots(roots)
    raise InvalidArgumentError(
        "roots is a Roots, a Root, Roots entries or {id: folder}", detail={"parameter": "roots"}
    )


def _error_code(exc: BaseException) -> str:
    from .model import error_code

    return error_code(exc)


def _file_ident(path: str) -> tuple[str, str]:
    return ("file", os.path.normcase(os.path.abspath(path)))


def _named(tree, node: ComponentNode) -> tuple[str | None, str | None]:
    """How an instance is compared with another document's: its file's name and the
    configuration it uses. File keys are each document's own, so names are compared."""
    f = tree.files.get(node.file) if node.file is not None else None
    name = f.file_name.casefold() if f is not None and f.file_name else None
    return name, node.configuration


@dataclass(frozen=True)
class _Ref:
    """A document of the hierarchy, open: ``path`` is the file on disk that holds it
    (None for the top assembly and the documents stored inside it), ``nested`` the
    nested-document streams from there to it, and ``ident`` what it is, to notice a
    document met again inside itself."""

    doc: Any
    path: str | None
    nested: tuple[str, ...]
    ident: tuple


class _Shared:
    """What every expansion of one document shares, however many instances of it there
    are and wherever they sit: its files' reference resolution, the documents opened
    for them, and the boxes its models store."""

    def __init__(self, resolution=None) -> None:
        self.resolution = resolution
        self.resolve_failed: _Failed | None = None
        self.subdocs: dict[str, _Ref | _Failed] = {}
        self.boxes: dict[tuple, Box | None] | None = None


class _Ctx:
    """A document whose component tree the instances come from: the top assembly, or
    a sub-assembly expanded from its own document. File keys are ``prefix`` and its
    own keys, instance ids ``id_prefix`` and its own ids, depths ``depth`` more than
    its own, and ``lineage`` holds every document it lies inside, itself included."""

    def __init__(self, ref: _Ref, tree, prefix: str, id_prefix: str, depth: int, lineage, shared) -> None:
        self.ref, self.tree, self.prefix, self.id_prefix = ref, tree, prefix, id_prefix
        self.depth, self.lineage, self.shared = depth, lineage, shared
        self.parents: dict[str, str | None] | None = None

    def key(self, local: str | None) -> str | None:
        return None if local is None else self.prefix + local


class _Item(NamedTuple):
    """An instance on the way down: ``path`` the instance names from the top, ``chain``
    the file keys and configurations from the top, ``names`` each level's file name
    and configuration, ``ancestors`` the sub-assemblies above it (node, context, index
    in ``path``), ``parent`` its parent's node and context."""

    node: ComponentNode
    ctx: _Ctx
    place: Placement | None
    path: tuple[str, ...]
    chain: tuple
    names: tuple
    ancestors: tuple
    parent: tuple | None
    sup: bool
    hid: bool


_AMBIGUOUS = object()


class _Stored:
    """The component meshes one assembly document stores (``docs/FORMAT.md`` 12.3),
    read on first use within the builder's limits: ``FaceTessellations`` records by
    instance path, or an older document's sections of ``Contents/DisplayLists`` by
    file. ``tree`` is the component tree whose files may take a section: the
    configuration shown for the top assembly, the active one for a sub-assembly
    (set by :meth:`active_chain`).

    The directory and the display-list stream count against the byte limit when
    read. When the limit refuses one, :attr:`refused` holds that failure, and an
    instance that could have taken a mesh from it reports the limit."""

    def __init__(self, builder: "_Builder", ref: _Ref, tree, sid: str) -> None:
        self.b, self.ref, self.tree, self.sid = builder, ref, tree, sid
        self._dir: facetess.TessDirectory | None | bool = False  # False: not read yet
        self.records: dict[tuple[str, ...], list[facetess.TessRecord]] | None = None
        self.streams: dict[str, tuple[bytes, dict[int, tuple[int, int, int]]] | None] = {}
        self.spans: dict[str, list[tuple[int, int]]] | None = None
        self.data = b""
        self.choices: dict[str, tuple | None] = {}
        self.refused: _Failed | None = None  # the byte limit refused the directory or the stream
        self.dir_refused = False  # it was the directory
        self.wanted: set[str] = set()  # the files whose sections the refused stream could hold
        self.active: dict[tuple[str, ...], Any] | None = None
        self.active_cut = False  # the instance limit cut the active tree read

    # -- FaceTessellations
    def directory(self) -> facetess.TessDirectory | None:
        if self._dir is False:
            self._dir = None
            c = self.ref.doc.container
            try:
                if facetess.DIRECTORY in c:
                    self.b.budget_bytes(c.info(facetess.DIRECTORY).size)
                    self._dir = facetess.read_directory(c)
            except _Failed as exc:  # the byte limit
                self.refused, self.dir_refused = exc, True
            except MemoryError:
                raise
            except Exception:  # a damaged directory: the other sources still work
                self._dir = None
        return self._dir or None

    def record(self, path: tuple[str, ...]) -> facetess.TessRecord | None:
        """The record whose block holds the mesh of the one instance at ``path``; raises
        the byte limit's failure when that limit refused the directory."""
        directory = self.directory()
        if directory is None:
            if self.dir_refused:
                raise self.refused  # type: ignore[misc]
            return None
        if self.records is None:
            self.records = {}
            for r in directory.records:
                self.records.setdefault(r.path, []).append(r)
        found = self.records.get(path)
        if not found or len(found) != 1:
            return None
        return directory.mesh_record(found[0])

    def block(self, stream: str, block: int) -> Mesh:
        b = self.b
        b.room_for_triangles()
        if stream not in self.streams:
            self.streams[stream] = None
            c = self.ref.doc.container
            if stream not in c:
                raise _Failed("no_mesh", "the assembly names a mesh stream it does not hold")
            b.budget_bytes(c.info(stream).size)
            try:
                data = c.read(stream, max_bytes=MAX_DISPLAY_LIST_BYTES)
            except MemoryError:
                raise
            except Exception as exc:
                raise _Failed("unreadable", code=_error_code(exc)) from None
            recs = [r for r in self.directory().records if r.stream == stream]  # type: ignore[union-attr]
            self.streams[stream] = (data, facetess.block_ranges(data, recs))
        entry = self.streams[stream]
        if entry is None:
            raise _Failed("no_mesh", "the assembly's mesh stream could not be read")
        data, ranges = entry
        span = ranges.get(block)
        if span is None:
            raise _Failed("no_mesh", "the assembly's mesh stream does not hold that block")
        mesh = facetess.block_mesh(data, span[0], span[1], stream)
        b.keep(mesh)
        return mesh

    # -- older documents: sections of Contents/DisplayLists
    def _sections(self) -> dict[str, list[tuple[int, int]]]:
        if self.spans is not None:
            return self.spans
        self.spans = {}
        doc = self.ref.doc
        c = doc.container
        if self.tree is None or self.directory() is not None or self.dir_refused or MESH_STREAM not in c:
            return self.spans
        md = doc.metadata.tree or {}
        models = Counter(m.get("file_ref") for m in md.get("models", {}).values())
        own = doc.metadata.own_file_ids
        # Every stored path of the component tree ends the section before it, whatever its
        # file (a sub-assembly, a part used in several configurations or only in another
        # one, a path two files share): left out, it would let that section run on through
        # its tables. Only a part used in one configuration, under a path of its own, has
        # its section used. A path that names one of those files in another folder (written
        # while it was elsewhere) ends a section too, unless it names the section's own file.
        paths: dict[str, str | None] = {}
        names: dict[str, set[str]] = {}
        shared: Counter = Counter()
        for fid, f in md.get("files", {}).items():
            p = f.get("path")
            if p and fid not in own:
                paths[p.casefold()] = None
                shared[p.casefold()] += 1
                names.setdefault(facetess.base_name(p), set())
        seen: set[str] = set()
        for key, f in self.tree.files.items():
            if f.stored_path:
                folded = f.stored_path.casefold()
                usable = (
                    f.doc_type == "part"
                    and models.get(key) == 1
                    and shared.get(folded, 0) <= 1
                    and folded not in seen
                )
                paths[folded] = key if usable else None
                names.setdefault(facetess.base_name(folded), set()).add(key)
                seen.add(folded)
        if not any(paths.values()):
            return self.spans
        try:
            self.b.budget_bytes(c.info(MESH_STREAM).size)
            data = c.read(MESH_STREAM, max_bytes=MAX_DISPLAY_LIST_BYTES)
        except _Failed as exc:  # the byte limit: the files it could have given report it
            self.refused = exc
            self.wanted = {k for k in paths.values() if k is not None}
            return self.spans
        except MemoryError:
            raise
        except Exception:  # an unreadable stream: the other sources still work
            return self.spans
        self.data = data
        self.spans = facetess.path_sections(data, paths, {n: frozenset(k) for n, k in names.items()})
        return self.spans

    def section(self, key: str) -> tuple | None:
        """How file ``key``'s section is read: ``("span", start, end)``, ``("mesh",
        mesh)`` when it had to be decoded to be chosen, ``("limit",)`` when the
        triangle limit came first, or None when the file has none to use: no section,
        or several that hold face tables (which configuration each shows is not
        stored). Raises the byte limit's failure when that limit refused the stream
        that could hold the file's section."""
        if key not in self.choices:
            spans = self._sections().get(key)
            if not spans and self.refused is not None and key in self.wanted:
                raise self.refused
            if not spans:
                self.choices[key] = None
            elif len(spans) == 1:
                self.choices[key] = ("span", *spans[0])
            else:
                self.choices[key] = self._choose(spans)
        return self.choices[key]

    def _choose(self, spans: list[tuple[int, int]]) -> tuple | None:
        """A path that opens several sections: each is decoded once (they lie in the
        stream already counted against the byte limit, apart from one another), and the
        one that holds face tables is the file's when only one does; the others mention
        the path with no tables after it. Two with tables are refused. Decoding stops at
        the triangle limit."""
        b = self.b
        room = b.max_triangles - b.counts["triangles_read"]
        if room <= 0:
            return ("limit",)
        found: Mesh | None = None
        decoded = 0
        for start, end in spans:
            mesh = mesh_from_bytes(self.data[start:end], MESH_STREAM)
            if mesh.n_triangles == 0:
                continue
            if found is not None:
                return None
            decoded += mesh.n_triangles
            if decoded > room:
                return ("limit",)
            found = mesh
        if found is None:
            return ("span", *spans[0])  # no tables in any: it reads as no mesh
        return ("mesh", found)

    def section_mesh(self, key: str) -> Mesh:
        b = self.b
        b.room_for_triangles()
        choice = self.choices.get(key)
        if choice is None or choice[0] == "limit":
            b.truncated.append("max_triangles")
            raise _Failed("max_triangles")
        mesh = (
            choice[1]
            if choice[0] == "mesh"
            else mesh_from_bytes(self.data[choice[1] : choice[2]], MESH_STREAM)
        )
        b.keep(mesh)
        return mesh

    # -- a sub-assembly's active configuration
    def active_chain(self, path: tuple[str, ...]):
        """The instance at ``path`` in the document's active configuration: ``(file key,
        names)``, ``names`` each level's file name and configuration (:func:`_named`), or
        None when there is none, or more than one, by that path. The trees read so count
        against an allowance of their own, :attr:`_Builder.lookup_nodes`; when it runs
        out before the instance is found, raises ``truncated`` (a limit) and names
        ``max_instances`` in ``truncated``."""
        b = self.b
        if self.active is None:
            self.active = {}
            room = min(b.lookup_nodes, b.max_instances)
            tree = None
            if room < 1:
                self.active_cut = True
            else:
                try:
                    tree = self.ref.doc.components(None, max_nodes=room, max_depth=b.max_depth)
                except MemoryError:
                    raise
                except Exception:  # no usable tree: nothing of it can be matched
                    tree = None
            if tree is not None:
                b.lookup_nodes -= tree.node_count
                self.active_cut = tree.truncated and tree.node_count >= room
                self.tree = tree
                stack = [(n, (n.name,), (_named(tree, n),)) for n in tree.children]
                while stack:
                    n, p, names = stack.pop()
                    self.active[p] = _AMBIGUOUS if p in self.active else (n.file, names)
                    stack.extend((k, (*p, k.name), (*names, _named(tree, k))) for k in n.children)
        hit = self.active.get(path)
        if hit is None and self.active_cut:
            b.truncated.append("max_instances")
            raise _Failed(
                "truncated",
                "the instance limit stopped the reading of the sub-assemblies' own trees before it",
            )
        return None if hit is _AMBIGUOUS else hit


class _Builder:
    def __init__(
        self, doc, tree, *, roots, resolution, resolve_options, sources, limits, brep=None
    ) -> None:
        self.doc = doc
        self.tree = tree
        self.roots = roots
        self.resolve_options = resolve_options
        self.sources = sources
        # The brep source's tessellation: options for solidseas.tessellate, the body types,
        # the seconds a part may take and whether to keep the shared-vertex triangles.
        self.brep = brep or _brep_settings(None, False)
        (
            self.max_instances,
            self.max_depth,
            self.max_files,
            self.max_triangles,
            self.max_bytes,
            self.max_drawn,
            self.max_brep_seconds,
        ) = limits
        self.counts = dict.fromkeys(
            (
                "instances",
                "parts",
                "placed",
                "suppressed",
                "hidden",
                "skipped",
                "meshes",
                "triangles_read",
                "triangles_drawn",
                "files_opened",
                "bytes_read",
                "meshes_tessellated",
            ),
            0,
        )
        self.counts["brep_seconds"] = 0.0
        self.truncated: list[str] = []
        self.meshes: dict[str, MeshSource] = {}
        self.failed: dict[str, _Failed] = {}
        self.file_failures: dict[str, str] = {}  # file key -> why its own file gave no mesh
        self.users: dict[str, set[str | None]] = {}  # mesh key -> configurations its instances use
        self.opened: list[Any] = []  # documents to close at the end
        self.held: tuple[str, Any] | None = None  # a part file with no display mesh, for the brep source
        ident = _file_ident(doc.path) if doc.path else ("memory", id(doc))
        ref = _Ref(doc, None, (), ident)
        top_shared = _Shared(resolution)
        self.shared: dict[tuple, _Shared] = {ident: top_shared}  # by document identity
        self.top = _Ctx(ref, tree, "", "", 0, frozenset((ident,)), top_shared)
        self.stored = _Stored(self, ref, tree, "")
        self.substored: dict[tuple, _Stored] = {}  # sub-assembly documents' stored meshes, by identity
        self.docs: dict[tuple, _Ref | _Failed] = {}  # sub-assembly files opened, by identity
        self.file_meshes: dict[str, str] = {}  # a file read for its mesh: its path -> the mesh key
        self.expanded: dict[tuple, Any] = {}  # (document, configuration, depth left) -> tree or failure
        self.parent_maps: dict[int, tuple[Any, dict[str, str | None]]] = {}  # by tree
        self.files: dict[str, ComponentFile] = dict(tree.files)
        self.active_paths: dict[tuple[str, ...], tuple] | None = None
        self.lookup_nodes = self.max_instances  # instances the sub-assemblies' own trees may expand
        self.brep_keys: dict[tuple[str, str], str] = {}  # (file, configuration) -> brep mesh key

    # ---------------------------------------------------------------- the tree
    def run(self) -> DisplayGeometry:
        tree = self.tree
        self.counts["instances"] = tree.node_count
        if tree.truncated:
            self.truncated.append("max_instances" if tree.node_count >= self.max_instances else "max_depth")
        placed: list[PlacedInstance] = []
        skipped: list[SkippedInstance] = []
        top = self.top
        stack = [
            _Item(
                n,
                top,
                n.placement,
                (n.name,),
                (n.file, n.configuration),
                (_named(tree, n),),
                (),
                None,
                False,
                False,
            )
            for n in reversed(tree.children)
        ]
        try:
            while stack:
                it = stack.pop()
                node, ctx = it.node, it.ctx
                sup = it.sup or node.suppressed
                hid = it.hid or node.hidden
                if node.children:
                    self._push(stack, it, ctx, node.children, sup, hid)
                    continue
                self.counts["parts"] += 1
                if sup:
                    self.counts["suppressed"] += 1
                    continue
                if hid:
                    self.counts["hidden"] += 1
                    continue
                try:
                    if node.doc_type == "assembly" and node.children_state == "described":
                        # A sub-assembly whose components this tree does not list: its own file does.
                        inner, children = self._expand(it)
                        self.counts["parts"] -= 1
                        self._push(stack, it, inner, children, sup, hid)
                        continue
                    key = self._place(it)
                    if self.counts["triangles_drawn"] + self.meshes[key].triangles > self.max_drawn:
                        self.truncated.append("max_drawn")
                        raise _Failed("max_drawn")
                except _Failed as f:
                    skipped.append(
                        SkippedInstance(
                            ctx.id_prefix + node.id,
                            node.name,
                            ctx.key(node.file),
                            f.reason,
                            f.message,
                            f.code,
                            it.place,
                            self._box(ctx, node),
                        )
                    )
                    continue
                placed.append(
                    PlacedInstance(
                        ctx.id_prefix + node.id,
                        node.name,
                        ctx.key(node.file),
                        node.configuration,
                        key,
                        it.place,  # type: ignore[arg-type]
                    )
                )
                self.users.setdefault(key, set()).add(node.configuration)
                self.counts["triangles_drawn"] += self.meshes[key].triangles
        finally:
            self._hold(None, None)
            for d in reversed(self.opened):
                try:
                    d.close()
                except Exception:  # closing never fails the result
                    pass
        meshes = {k: self._with_warnings(m) for k, m in self.meshes.items() if k in self.users}
        self.counts.update(placed=len(placed), skipped=len(skipped), meshes=len(meshes))
        return DisplayGeometry(
            configuration=tree.configuration,
            configuration_source=tree.configuration_source,
            instances=tuple(placed),
            meshes=meshes,
            skipped=tuple(skipped),
            counts=self.counts,
            truncated=tuple(dict.fromkeys(self.truncated)),
            warnings=tuple(tree.warnings),
            files=self.files,
            resolution=self.top.shared.resolution,
            file_failures=dict(self.file_failures),
        )

    def _push(self, stack: list, it: _Item, ctx: _Ctx, children, sup: bool, hid: bool) -> None:
        """Put ``children`` (of ``it``'s node, from ``ctx``'s tree) on the stack. The top
        tree's nodes carry their placement; an expanded document's are composed here
        from the stored transforms, parent by parent, as ``Document.components`` does."""
        ancestors = (*it.ancestors, (it.node, it.ctx, len(it.path) - 1))
        for c in reversed(children):
            if ctx is self.top:
                place = c.placement
            elif it.place is None or c.transform is None:
                place = None
            else:
                place = it.place.then(c.transform)
                place = place if place.is_finite() else None
            stack.append(
                _Item(
                    c,
                    ctx,
                    place,
                    (*it.path, c.name),
                    (*it.chain, ctx.key(c.file), c.configuration),
                    (*it.names, _named(ctx.tree, c)),
                    ancestors,
                    (it.node, it.ctx),
                    sup,
                    hid,
                )
            )

    def _expand(self, it: _Item):
        """``(context, children)`` for a sub-assembly whose components its tree does not
        list, from its own document in the configuration the instance uses."""
        node, ctx = it.node, it.ctx
        depth = ctx.depth + node.depth
        if depth >= self.max_depth:
            self.truncated.append("max_depth")
            raise _Failed("truncated", "the depth limit stopped the expansion at this sub-assembly")
        room = self.max_instances - self.counts["instances"]
        if room < 1:
            self.truncated.append("max_instances")
            raise _Failed("truncated", "the instance limit stopped the expansion at this sub-assembly")
        ref = self._subdoc(ctx, node.file)
        if ref.ident in ctx.lineage:
            raise _Failed("cycle")
        if ref.doc.doc_type != "assembly":
            raise _Failed("no_components", "the tree names an assembly, and its file is not one")
        sub = self._components(ref, node.configuration, room, self.max_depth - depth)
        if not sub.children:
            raise _Failed("no_components")
        self.counts["instances"] += sub.node_count
        if sub.truncated:
            self.truncated.append("max_instances" if sub.node_count >= sub.max_nodes else "max_depth")
        full = ctx.key(node.file)
        shared = self.shared.setdefault(ref.ident, _Shared())
        inner = _Ctx(
            ref, sub, f"{full}/", f"{ctx.id_prefix}{node.id}/", depth, ctx.lineage | {ref.ident}, shared
        )
        for k, f in sub.files.items():
            key = inner.key(k)
            if key not in self.files:
                self.files[key] = replace(  # type: ignore[index]
                    f,
                    key=key,
                    direct=False,
                    instances=None,
                    instances_unsuppressed=None,
                    instances_in_bom=None,
                )
        return inner, sub.children

    def _components(self, ref: _Ref, configuration: str | None, room: int, depth_left: int):
        """The component tree of the sub-assembly document ``ref`` in ``configuration``,
        within ``room`` nodes and ``depth_left`` levels. Read once for every instance of
        that document in that configuration (reading it walks the document's whole
        metadata), and again only when a tree the instance limit cut is asked for with
        more room, or a whole one with less."""
        ck = (ref.ident, configuration, depth_left)
        got = self.expanded.get(ck)
        if isinstance(got, _Failed):
            raise got
        if got is not None:
            cut = got.truncated and got.node_count >= got.max_nodes
            if got.node_count <= room and not cut:
                return got
            if cut and got.max_nodes == room:
                return got
        try:
            got = ref.doc.components(configuration, max_nodes=room, max_depth=depth_left)
        except MemoryError:
            raise
        except Exception as exc:  # a configuration its own file does not have
            fail = self.expanded[ck] = _Failed(
                "no_components",
                f"its own file has no configuration {configuration!r}",
                _error_code(exc),
            )
            raise fail from None
        self.expanded[ck] = got
        return got

    def _with_warnings(self, m: MeshSource) -> MeshSource:
        if m.kind in _STORED_KINDS or m.configuration is None:
            return m
        other = sorted(c for c in self.users.get(m.key, ()) if c is not None and c != m.configuration)
        if not other:
            return m
        if m.kind == "brep":  # a part with no bodies of the instances' configuration: the active one's
            text = (
                f"its part stores no bodies of configuration {', '.join(repr(c) for c in other)}; those of "
                f"{m.configuration!r} are used, whose geometry may differ"
            )
        else:
            text = (
                f"the document stores the display mesh of configuration {m.configuration!r}; instances "
                f"use {', '.join(repr(c) for c in other)}, whose geometry may differ"
            )
        w = ReaderWarning("mesh_configuration_differs", text, m.stream)
        return replace(m, warnings=(*m.warnings, w))

    def _place(self, it: _Item) -> str:
        """The key of the mesh for ``it``, reading it if need be; raises _Failed."""
        node, ctx = it.node, it.ctx
        if node.children_state in ("cycle", "truncated"):
            raise _Failed(node.children_state)
        if node.children_state == "unknown" or node.file is None:
            raise _Failed("model_missing")
        if it.place is None:
            raise _Failed("no_placement")
        if node.doc_type not in ("part", None):
            raise _Failed("not_part", "its file is an assembly whose components are not described")
        f = ctx.tree.files.get(node.file)
        failure: _Failed | None = None
        tried = False
        for kind in self.sources:
            this: _Failed | None = None  # why this source gave no mesh
            try:
                # A source can give several candidates (the sub-assemblies above, in turn):
                # one that fails passes to the next.
                for key, read in self._candidates(kind, it, f):
                    tried = True
                    if key in self.meshes:
                        return key
                    fail = self.failed.get(key)
                    if fail is None:
                        try:
                            self.meshes[key] = read()
                            return key
                        except _Failed as exc:
                            fail = self.failed[key] = exc
                    this = fail
                    failure = fail if failure is None else _reported(failure, fail, kind)
            except _Failed as exc:  # finding the source already failed (a limit, say)
                tried = True
                this = exc
                failure = exc if failure is None else _reported(failure, exc, kind)
            if kind == "file" and this is not None:
                self.file_failures.setdefault(ctx.key(node.file) or "", this.reason)
        if not tried or failure is None:
            raise _Failed("no_source")
        raise failure

    # ---------------------------------------------------------------- choosing a source
    def _candidates(self, kind: str, it: _Item, f: ComponentFile | None) -> Iterable[tuple[str, Callable]]:
        if kind == "subassembly":
            return self._in_subassembly(it)
        got = self._candidate(kind, it, f)
        return () if got is None else (got,)

    def _candidate(
        self, kind: str, it: _Item, f: ComponentFile | None
    ) -> tuple[str, Callable[[], MeshSource]] | None:
        node, ctx = it.node, it.ctx
        full = ctx.key(node.file)
        if kind == "assembly":
            st = self.stored
            rec = st.record(it.path)
            if rec is not None and self._same_as_active(it.path, it.chain):
                key = f"assembly:{rec.stream}#{rec.block}"
                return key, lambda: self._block_source(key, "assembly", st, rec, it)
            if ctx is self.top and f is not None and st.section(f.key) is not None:
                key = f"assembly:{MESH_STREAM}#{f.key}"
                return key, lambda: self._section_source(key, "assembly", st, f.key, it)
            return None
        if kind == "subassembly":
            return self._in_subassembly(it)
        if f is None:
            return None
        if kind == "nested":
            if f.nested:
                key = f"nested:{full}"
                ref = ctx.ref
                return key, lambda: self._from_document(
                    key, "nested", full, ref.doc, (f.nested,), ref.path, ref.nested
                )
            if f.embedded_in_subassembly and it.parent is not None and it.parent[0].file:
                pnode, pctx = it.parent
                key = f"nested:{pctx.key(pnode.file)}|{full}"
                return key, lambda: self._read_subassembly(key, f, full, pnode, pctx)
            if f.embedded == "embedded_not_found":
                return f"nested:{full}", _raising(_Failed("embedded_not_found"))
            return None
        if kind == "file":
            if f.virtual or f.embedded:
                return None
            # One mesh for a file found on disk, however many contexts name it.
            path, within = self._resolved(ctx, f.key)
            key = self.file_meshes.setdefault(_file_ident(path)[1], f"file:{full}")
            return key, _bind(self._read_file, key, path, within, full)
        if kind == "brep":
            return self._brep_candidate(it, f, full)
        return None

    def _brep_candidate(
        self, it: _Item, f: ComponentFile, full
    ) -> tuple[str, Callable[[], MeshSource]] | None:
        """The part's own bodies, tessellated in the configuration the instance uses: one
        mesh for each document and configuration, however many instances share them."""
        ctx = it.ctx
        cfg = it.node.configuration
        tag = "" if cfg is None else cfg
        if f.nested:
            key = f"brep:nested:{full}#{tag}"
            ref = ctx.ref
            return key, _bind(self._brep_document, key, full, ref.doc, (f.nested,), ref.path, ref.nested, cfg)
        if f.embedded_in_subassembly and it.parent is not None and it.parent[0].file:
            pnode, pctx = it.parent
            key = f"brep:nested:{pctx.key(pnode.file)}|{full}#{tag}"
            return key, _bind(self._brep_subassembly, key, f, full, pnode, pctx, cfg)
        if f.virtual or f.embedded:
            return None
        path, within = self._resolved(ctx, f.key)
        ident = _file_ident(path)[1]
        key = self.brep_keys.setdefault((ident, tag), f"brep:{full}#{tag}")
        return key, _bind(self._brep_file, key, path, within, full, cfg)

    def _in_subassembly(self, it: _Item):
        """The meshes the sub-assemblies above the instance store of it, as candidates
        from the one nearest the top down: when one fails to give a mesh (a section of
        its file with no face tables, a block that cannot be read), the next is tried.
        A limit met on the way is raised after the last, so that the instance reports it
        when none gave a mesh."""
        limit: _Failed | None = None
        for anc, actx, i in it.ancestors:
            try:
                ref = self._subdoc(actx, anc.file)
                st = self.substored.get(ref.ident)
                if st is None:
                    st = self.substored[ref.ident] = _Stored(self, ref, None, actx.key(anc.file) or "")
                rel = it.path[i + 1 :]
                hit = st.active_chain(rel)
                if hit is None or hit[1] != it.names[i + 1 :]:
                    continue
                rec = st.record(rel)
                local = hit[0]
                if rec is not None:
                    key = f"subassembly:{st.sid}|{rec.stream}#{rec.block}"
                    found = key, _bind(self._block_source, key, "subassembly", st, rec, it)
                elif st.directory() is None and local is not None and st.section(local) is not None:
                    key = f"subassembly:{st.sid}|{MESH_STREAM}#{local}"
                    found = key, _bind(self._section_source, key, "subassembly", st, local, it)
                else:
                    continue
            except _Failed as exc:
                if limit is None and exc.reason in _LIMITED:
                    limit = exc
                continue
            yield found
        if limit is not None:
            raise limit

    def _same_as_active(self, path, chain) -> bool:
        """The assembly's meshes describe the configuration active at save: an instance
        of another configuration may use one only where that configuration has the same
        file in the same configuration at every level down to it."""
        tree = self.tree
        if tree.configuration_source == "active" or tree.configuration == self.doc.active_configuration:
            return True
        if self.active_paths is None:
            self.active_paths = {}
            try:
                active = self.doc.components(None, max_nodes=self.max_instances, max_depth=self.max_depth)
            except Exception:
                active = None
            if active is not None:
                stack = [(n, (n.name,), (n.file, n.configuration)) for n in active.children]
                while stack:
                    n, p, c = stack.pop()
                    self.active_paths[p] = c
                    stack.extend((k, (*p, k.name), (*c, k.file, k.configuration)) for k in n.children)
        return self.active_paths.get(path) == chain

    # ---------------------------------------------------------------- reading
    def budget_bytes(self, size: int) -> None:
        if self.counts["bytes_read"] + size > self.max_bytes:
            self.truncated.append("max_bytes")
            raise _Failed("max_bytes")
        self.counts["bytes_read"] += size

    def room_for_triangles(self) -> None:
        if self.counts["triangles_read"] >= self.max_triangles:
            self.truncated.append("max_triangles")
            raise _Failed("max_triangles")

    def keep(self, mesh: Mesh) -> None:
        if mesh.n_triangles == 0:
            raise _Failed("no_mesh")
        if self.counts["triangles_read"] + mesh.n_triangles > self.max_triangles:
            self.truncated.append("max_triangles")
            raise _Failed("max_triangles")
        self.counts["triangles_read"] += mesh.n_triangles

    def _block_source(self, key: str, kind: str, st: _Stored, rec, it: _Item) -> MeshSource:
        mesh = st.block(rec.stream, rec.block)
        return self._stored_source(key, kind, st, rec.stream, mesh, it)

    def _section_source(self, key: str, kind: str, st: _Stored, local: str, it: _Item) -> MeshSource:
        mesh = st.section_mesh(local)
        return self._stored_source(key, kind, st, MESH_STREAM, mesh, it)

    def _stored_source(self, key, kind, st: _Stored, stream: str, mesh: Mesh, it: _Item) -> MeshSource:
        node = it.node
        path, nested = (st.ref.path, st.ref.nested) if kind == "subassembly" else (None, ())
        return MeshSource(key, kind, it.ctx.key(node.file), stream, path, nested, node.configuration, mesh)

    def _from_document(self, key, kind, file_key, doc, nested, path, outer=()) -> MeshSource:
        """The display mesh of ``doc`` (a document already open), or of the nested
        document ``nested`` leads to inside it. ``outer`` are the nested-document
        streams that led to ``doc`` itself."""
        self.room_for_triangles()
        try:
            for stream in nested:
                self.budget_bytes(doc.container.info(stream).size)
                doc = doc.nested(stream)
            if doc.doc_type != "part":
                raise _Failed("not_part")
            c = doc.container
            if MESH_STREAM not in c:
                raise _Failed("no_mesh")
            info = c.info(MESH_STREAM)
            self.budget_bytes(info.size)
            mesh = mesh_from_bytes(c.read(MESH_STREAM, max_bytes=MAX_DISPLAY_LIST_BYTES), info.name)
            configuration = doc.active_configuration
        except _Failed:
            raise
        except MemoryError:
            raise
        except Exception as exc:
            raise _Failed("unreadable", code=_error_code(exc)) from None
        self.keep(mesh)
        return MeshSource(key, kind, file_key, info.name, path, (*outer, *nested), configuration, mesh)

    def _resolved(self, ctx: _Ctx, file_key: str):
        """``(host path, within)`` of a file of ``ctx``'s document that reference
        resolution found. Resolution runs once a document, and every document resolved
        in one call shares one index of the roots (the ``cache`` given, or one of its
        own), so the roots are walked once."""
        sh = ctx.shared
        if sh.resolution is None:
            if self.roots is None:
                raise _Failed(
                    "missing",
                    "the assembly was opened from bytes and no roots were given, so no file is searched",
                )
            if sh.resolve_failed is not None:
                raise sh.resolve_failed
            from .resolve import IndexCache, resolve_references

            if self.resolve_options.get("cache") is None:
                self.resolve_options["cache"] = IndexCache()
            try:
                sh.resolution = resolve_references(ctx.ref.doc, self.roots, **self.resolve_options)
            except MemoryError:
                raise
            except Exception as exc:  # a root that cannot be walked: the files are not searched
                sh.resolve_failed = _Failed(
                    "missing", "the files could not be looked for in the folders given", _error_code(exc)
                )
                raise sh.resolve_failed from None
        r = sh.resolution.results.get(file_key)
        if r is None:
            raise _Failed("missing")
        if r.match is None or r.status not in ("resolved", "moved"):
            reason = r.status if r.status in REASONS else "missing"
            raise _Failed(reason)
        if r.match.root is not None:
            try:
                within = self.roots[r.match.root].path  # type: ignore[index]
            except (KeyError, TypeError):
                raise _Failed("missing", "the file was found under a root this call was not given") from None
        else:
            within = os.path.dirname(r.match.host_path)
        return r.match.host_path, within

    def _open(self, path: str, within: str):
        if self.counts["files_opened"] >= self.max_files:
            self.truncated.append("max_files")
            raise _Failed("max_files")
        self.counts["files_opened"] += 1
        try:
            return open_document(path, within=within, hold_open=True)
        except MemoryError:
            raise
        except Exception as exc:
            raise _Failed("unreadable", code=_error_code(exc)) from None

    def _read_file(self, key: str, path: str, within: str, file_key) -> MeshSource:
        self.room_for_triangles()
        doc = self._open(path, within)
        try:
            return self._from_document(key, "file", file_key, doc, (), path)
        except _Failed as exc:
            # The brep source, later in the order, reads the same document's bodies:
            # keep it open for that rather than open it again.
            if exc.reason == "no_mesh" and "brep" in self.sources:
                self._hold(path, doc)
                doc = None
            raise
        finally:
            if doc is not None:
                doc.close()

    def _hold(self, path: str | None, doc) -> None:
        """Keep ``doc`` (the file at ``path``) open for the brep source, closing the one
        held before; ``_hold(None, None)`` closes it."""
        if self.held is not None and self.held[1] is not doc:
            try:
                self.held[1].close()
            except Exception:  # closing never fails the result
                pass
        self.held = None if doc is None else (path, doc)  # type: ignore[assignment]

    # ---------------------------------------------------------------- the brep source
    def _brep_file(self, key: str, path: str, within: str, file_key, cfg) -> MeshSource:
        self.room_for_triangles()
        file_fail = self.failed.get(self.file_meshes.get(_file_ident(path)[1], ""))
        if file_fail is not None and file_fail.reason != "no_mesh":
            raise file_fail  # the file source could not read it either: not opened again
        if self.held is not None and self.held[0] == path:
            doc = self.held[1]
        else:
            doc = self._open(path, within)
            self._hold(path, doc)
        return self._brep_document(key, file_key, doc, (), path, (), cfg)

    def _brep_subassembly(self, key, f, file_key, pnode, pctx, cfg) -> MeshSource:
        ref = self._subdoc(pctx, pnode.file)
        stream = self._stream_in(ref.doc, f)
        return self._brep_document(key, file_key, ref.doc, (stream,), ref.path, ref.nested, cfg)

    def _brep_document(self, key, file_key, doc, nested, path, outer, cfg) -> MeshSource:
        """The part ``doc`` (or the nested document ``nested`` leads to inside it)
        tessellated from its Parasolid bodies in configuration ``cfg``, or, when the part
        stores no bodies of that one, in its active configuration (the warning
        ``mesh_configuration_differs`` then says so)."""
        from .errors import ConfigurationNotFoundError
        from .tessellate import _options, _run, bodies_of, hidden_message, shown_bodies

        self.room_for_triangles()
        left = self.max_brep_seconds - self.counts["brep_seconds"]
        if left <= 0.0:
            self.truncated.append("max_brep_seconds")
            raise _Failed("max_brep_seconds")
        t0 = time.perf_counter()
        # The part's time runs from here, reading its bodies included: tessellating gets
        # what the read leaves. A read once started runs to its end.
        per_part = self.brep["seconds"]
        seconds = min(per_part, left)
        deadline = t0 + seconds
        try:
            for stream in nested:
                self.budget_bytes(doc.container.info(stream).size)
                doc = doc.nested(stream)
            if doc.doc_type != "part":
                raise _Failed("not_part")
            room = self.max_bytes - self.counts["bytes_read"]
            if room <= 0:
                self.truncated.append("max_bytes")
                raise _Failed("max_bytes")
            try:
                name, bodies, warns, used = bodies_of(doc, cfg, max_total_bytes=room)
            except ConfigurationNotFoundError:
                name, bodies, warns, used = cfg, [], [], 0
            self.counts["bytes_read"] += used
            if not bodies and cfg is not None and name != doc.active_configuration:
                room = self.max_bytes - self.counts["bytes_read"]
                name, bodies, warns, more = bodies_of(doc, None, max_total_bytes=max(room, 1))
                self.counts["bytes_read"] += more
            hidden = 0
            if bodies and not self.brep["hidden"]:
                bodies, hidden = shown_bodies(bodies)
                if not bodies:
                    raise _Failed("bodies_not_asked", f"{REASONS['bodies_not_asked']} (every body is hidden)")
            if not bodies:
                # the byte limit refused a stream (the message names the room it had left)
                if any(
                    w.code == "bodies_unreadable" and ("budget" in w.message or f"cap {room}" in w.message)
                    for w in warns
                ):
                    self.truncated.append("max_bytes")
                    raise _Failed("max_bytes")
                raise _Failed("no_mesh", NO_MESH_NOR_BODIES)
            rest = deadline - time.perf_counter()
            if rest <= 0.0:
                if seconds < per_part:
                    self.truncated.append("max_brep_seconds")
                    raise _Failed("max_brep_seconds")
                raise _Failed("brep_failed", f"reading its bodies took longer than {seconds:g} s")
            room_tris = self.max_triangles - self.counts["triangles_read"]
            items = [(b.name, b.transmit, None, self.brep["types"]) for b in bodies]
            t = _run(
                items,
                _options(**self.brep["options"], max_seconds=rest, max_triangles=max(room_tris, 0)),
                configuration=name,
                warnings=warns,
            )
        except _Failed:
            raise
        except MemoryError:
            raise
        except Exception as exc:
            raise _Failed("unreadable", code=_error_code(exc)) from None
        finally:
            self.counts["brep_seconds"] += time.perf_counter() - t0
        if "max_triangles" in t.truncated:
            self.truncated.append("max_triangles")
            raise _Failed("max_triangles")
        if "max_seconds" in t.truncated:
            if seconds < per_part:
                self.truncated.append("max_brep_seconds")
                raise _Failed("max_brep_seconds")
            raise _Failed("brep_failed", f"tessellating its bodies took longer than {seconds:g} s")
        if t.mesh.n_triangles == 0:
            left_out = t.counts["bodies_left_out"]
            if left_out and not t.reasons and t.counts["bodies"] == 0:
                raise _Failed(
                    "bodies_not_asked", f"{REASONS['bodies_not_asked']} ({left_out} bodies of other types)"
                )
            why = ", ".join(sorted(t.reasons)) or "no faces"
            raise _Failed("brep_failed", f"{REASONS['brep_failed']} ({why})")
        self.keep(t.mesh)
        self.counts["meshes_tessellated"] += 1
        stream = bodies[0].report.get("stream") or ""
        warnings = []
        reasons = ", ".join(f"{k} {v}" for k, v in sorted(t.reasons.items()))
        if t.counts["faces_skipped"]:
            warnings.append(
                ReaderWarning(
                    "brep_faces_skipped",
                    f"{t.counts['faces_skipped']} of {t.counts['faces']} faces of its bodies could not be "
                    f"tessellated ({reasons})",
                    stream,
                )
            )
        if t.counts["bodies_skipped"]:
            warnings.append(
                ReaderWarning(
                    "brep_bodies_skipped",
                    f"{t.counts['bodies_skipped']} of {t.counts['bodies']} of its bodies could not be walked "
                    f"face by face and are left out ({reasons})",
                    stream,
                )
            )
        if t.closed is False:
            warnings.append(ReaderWarning("brep_not_closed", "a solid body's mesh is not closed", stream))
        if hidden:
            warnings.append(ReaderWarning("brep_bodies_hidden", hidden_message(hidden), stream))
        return MeshSource(
            key,
            "brep",
            file_key,
            stream,
            path,
            (*outer, *nested),
            name,
            t.mesh,
            tuple(warnings),
            t.welded() if self.brep["welded"] else None,
            t.chord_m,
        )

    def _parents(self, ctx: _Ctx) -> dict[str, str | None]:
        """Each file of ``ctx``'s tree and the file of the instance it sits in, worked out
        once a tree however many contexts share it."""
        if ctx.parents is None:
            got = self.parent_maps.get(id(ctx.tree))
            if got is None:
                parents: dict[str, str | None] = {}
                for n in ctx.tree.walk():
                    for c in n.children:
                        if c.file is not None:
                            parents.setdefault(c.file, n.file)
                # The tree is held with its map, so no other tree takes its id.
                got = self.parent_maps[id(ctx.tree)] = (ctx.tree, parents)
            ctx.parents = got[1]
        return ctx.parents

    def _subdoc(self, ctx: _Ctx, file_key: str) -> _Ref:
        """A sub-assembly of ``ctx``'s document, open: a file on disk, or a document
        stored inside that document or inside another of its sub-assemblies."""
        sh = ctx.shared
        got = sh.subdocs.get(file_key)
        if isinstance(got, _Failed):
            raise got
        if isinstance(got, _Ref):
            return got
        sh.subdocs[file_key] = _Failed("missing")  # a loop of parents ends here
        f = ctx.tree.files.get(file_key)
        here = ctx.ref
        try:
            if f is not None and f.nested:
                self.budget_bytes(here.doc.container.info(f.nested).size)
                got = _Ref(
                    here.doc.nested(f.nested), here.path, (*here.nested, f.nested), (here.ident, f.nested)
                )
            elif f is not None and f.embedded_in_subassembly:
                parent = self._parents(ctx).get(file_key)
                if parent is None:
                    raise _Failed("embedded_not_found")
                pref = self._subdoc(ctx, parent)
                stream = self._stream_in(pref.doc, f)
                self.budget_bytes(pref.doc.container.info(stream).size)
                got = _Ref(pref.doc.nested(stream), pref.path, (*pref.nested, stream), (pref.ident, stream))
            else:
                got = self._on_disk(ctx, file_key)
        except _Failed as exc:
            sh.subdocs[file_key] = exc
            raise
        except MemoryError:
            raise
        except Exception as exc:
            fail = sh.subdocs[file_key] = _Failed("unreadable", code=_error_code(exc))
            raise fail from None
        sh.subdocs[file_key] = got
        return got

    def _on_disk(self, ctx: _Ctx, file_key: str) -> _Ref:
        """A sub-assembly's file on disk, open: opened once however many contexts name it."""
        path, within = self._resolved(ctx, file_key)
        ident = _file_ident(path)
        got = self.docs.get(ident)
        if isinstance(got, _Failed):
            raise got
        if got is None:
            try:
                doc = self._open(path, within)
            except _Failed as exc:  # unreadable, or max_files, which no later call gets past
                self.docs[ident] = exc
                raise
            self.opened.append(doc)
            got = self.docs[ident] = _Ref(doc, path, (), ident)
        return got

    @staticmethod
    def _stream_in(subdoc, f) -> str:
        """The nested-document stream that holds virtual file ``f`` in ``subdoc``, the
        sub-assembly that uses it directly."""
        name = os.path.basename((f.stored_path or "").replace("\\", "/")).casefold()
        for g in subdoc.reference_set().files.values():
            if g.nested and os.path.basename((g.stored_path or "").replace("\\", "/")).casefold() == name:
                return g.nested
        raise _Failed("embedded_not_found", "its sub-assembly does not store it")

    def _read_subassembly(self, key, f, file_key, pnode, pctx) -> MeshSource:
        ref = self._subdoc(pctx, pnode.file)
        stream = self._stream_in(ref.doc, f)
        return self._from_document(key, "nested", file_key, ref.doc, (stream,), ref.path, ref.nested)

    def _box(self, ctx: _Ctx, node: ComponentNode) -> Box | None:
        """The box ``ctx``'s document stores for the node's model (its file in its
        configuration), or None: not stored, unreadable, or two models of that file and
        configuration disagree."""
        sh = ctx.shared
        if sh.boxes is None:
            sh.boxes = {}
            try:
                models = (ctx.ref.doc.metadata.tree or {}).get("models", {})
            except MemoryError:
                raise
            except Exception:
                models = {}
            for m in models.values():
                k = (m.get("file_ref"), m.get("config"))
                box = parse_bounding_box(m.get("bbox"))
                sh.boxes[k] = box if k not in sh.boxes or sh.boxes[k] == box else None
        if node.file is None:
            return None
        return sh.boxes.get((node.file, node.configuration))


_BREP_OPTIONS = ("chord_m", "angle_deg", "chord_fraction", "max_chord_m")


def _brep_settings(brep_options: Mapping[str, Any] | None, keep_welded: bool) -> dict[str, Any]:
    """The brep source's settings from ``display_geometry``'s ``brep_options``: the
    tessellation options it passes on (checked here, so a bad one raises before any
    work), the body types, the seconds one part may take, and ``keep_welded``."""
    from .tessellate import _body_types, _options

    given = dict(brep_options or {})
    known = (*_BREP_OPTIONS, "body_types", "max_seconds", "include_hidden")
    unknown = sorted(set(given) - set(known))
    if unknown:
        raise InvalidArgumentError(
            f"brep_options takes {', '.join(known)}, not {', '.join(unknown)}",
            detail={"parameter": "brep_options"},
        )
    options = {k: given[k] for k in _BREP_OPTIONS if k in given}
    seconds = given.get("max_seconds", BREP_SECONDS_PER_PART)
    _options(**options, max_seconds=seconds)  # raises InvalidArgumentError for a bad value
    return {
        "options": options,
        "types": _body_types(given.get("body_types", ("solid", "sheet"))),
        "seconds": float(seconds),
        "welded": bool(keep_welded),
        "hidden": bool(given.get("include_hidden", True)),
    }


def _raising(failure: _Failed) -> Callable[[], MeshSource]:
    def read() -> MeshSource:
        raise failure

    return read


def _bind(fn, *args) -> Callable[[], MeshSource]:
    return lambda: fn(*args)


def display_geometry(
    doc,
    configuration: str | None = None,
    *,
    roots=None,
    resolution=None,
    sources: Iterable[str] = SOURCES,
    path_map=(),
    allow_outside_roots: bool = True,
    cache=None,
    max_instances: int = DEFAULT_MAX_INSTANCES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_files: int = DEFAULT_MAX_FILES,
    max_triangles: int = DEFAULT_MAX_TRIANGLES,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_triangles_drawn: int = DEFAULT_MAX_TRIANGLES_DRAWN,
    max_brep_seconds: float = DEFAULT_MAX_BREP_SECONDS,
    brep_options: Mapping[str, Any] | None = None,
    keep_welded: bool = False,
) -> DisplayGeometry | None:
    """The display geometry of one configuration of the assembly ``doc``, or None for a
    part or a drawing. Provisional (``docs/API.md`` section 3.14).

    ``configuration`` is chosen as :meth:`Document.components` chooses it. ``sources``
    orders where meshes come from (:data:`SOURCES`). ``roots`` are the folders
    reference resolution searches for component files (None: the document's own
    folder), and ``path_map``, ``allow_outside_roots`` and ``cache`` go to
    :func:`solidseas.resolve.resolve_references`; a ``resolution`` already made
    against the same ``roots`` is used as it is. Resolution runs only when a file
    is needed, for the top assembly and for each sub-assembly read from its own
    file, all against one index of the roots (``cache``, or one made for the call).

    Limits: ``max_instances`` and ``max_depth`` bound the component tree, with the
    sub-assemblies expanded from their own files counted in (and, as an allowance
    of its own, the sub-assemblies' own trees the ``subassembly`` source reads),
    ``max_files`` the documents opened from disk, ``max_triangles`` the triangles
    read over every mesh, ``max_bytes`` the display data decoded (every stream of it,
    directories included), and ``max_triangles_drawn`` the triangles
    of the placed instances, each counting its mesh again (what a viewer draws a
    frame). An instance a limit stops is skipped with that limit as its reason
    (``max_drawn`` for the last), and the limit is named in ``truncated``; where a
    source failed on a limit and the next one for another reason, the limit is the
    reason given. ``max_brep_seconds`` bounds the time the ``brep`` source spends on
    parts' bodies over the whole call (``max_brep_seconds`` as a reason and in
    ``truncated`` when spent): no part is started after it, and a part whose bodies
    take the rest of it to read is not tessellated, so the call runs past it by at
    most one part's read. Raises only for bad arguments and for errors
    opening the assembly's own tree; a component that cannot be read is skipped
    with a reason.

    ``brep_options`` (provisional) sets how the ``brep`` source tessellates: any of
    ``chord_m``, ``angle_deg``, ``chord_fraction`` and ``max_chord_m`` for
    :mod:`solidseas.tessellate`, ``body_types`` (by default solids and sheets) and
    ``max_seconds``, the time one part may take (30 s by default). With
    ``keep_welded`` each ``brep`` mesh also carries its triangles over shared
    vertices (:attr:`MeshSource.welded`), as exports want them.
    """
    if doc.doc_type != "assembly":
        return None
    order = tuple(sources) if not isinstance(sources, str) else (sources,)
    if not order or any(s not in SOURCES for s in order) or len(set(order)) != len(order):
        raise InvalidArgumentError(
            f"sources is a sequence of distinct names from {', '.join(SOURCES)}",
            detail={"parameter": "sources"},
        )
    limits = (
        _count(max_instances, "max_instances", 1, MAX_NODES_LIMIT),
        _count(max_depth, "max_depth", 1, MAX_DEPTH_LIMIT),
        _count(max_files, "max_files", 0),
        _count(max_triangles, "max_triangles", 0),
        _count(max_bytes, "max_bytes", 0),
        _count(max_triangles_drawn, "max_triangles_drawn", 0),
        _seconds(max_brep_seconds, "max_brep_seconds"),
    )
    brep = _brep_settings(brep_options, keep_welded)
    if resolution is not None and not hasattr(resolution, "results"):
        raise InvalidArgumentError(
            "resolution is a solidseas.resolve.Resolution", detail={"parameter": "resolution"}
        )
    tree = doc.components(configuration, max_nodes=limits[0], max_depth=limits[1])
    builder = _Builder(
        doc,
        tree,
        roots=_roots_of(doc, roots),
        resolution=resolution,
        resolve_options={"path_map": path_map, "allow_outside_roots": allow_outside_roots, "cache": cache},
        sources=order,
        limits=limits,
        brep=brep,
    )
    return builder.run()


__all__ = [
    "DEFAULT_MAX_BREP_SECONDS",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_FILES",
    "DEFAULT_MAX_INSTANCES",
    "DEFAULT_MAX_TRIANGLES",
    "DEFAULT_MAX_TRIANGLES_DRAWN",
    "REASONS",
    "SOURCES",
    "Box",
    "DisplayGeometry",
    "MeshSource",
    "PlacedInstance",
    "SkippedInstance",
    "display_geometry",
]
