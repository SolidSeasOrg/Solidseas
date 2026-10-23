"""The 3D view's model: a part's saved display mesh, or an assembly's, made ready for the GPU.

``Document.mesh()`` gives the tessellation SOLIDWORKS cached the last time it
drew the part: positions and normals as float32 arrays in metres and the
triangles as a uint32 index array. Those arrays are already what an OpenGL
vertex and index buffer hold, so :func:`prepare` only turns them into bytes
and measures the bounding box; nothing is rebuilt vertex by vertex.
:func:`read_part_mesh` runs in the mesh process (:mod:`.meshproc`), never in
the window's own process.

The cost of a read follows the size of the ``Contents/DisplayLists`` stream
more than the triangles in it, and ``Document.mesh()`` cannot stop partway, so
the stream's size is checked first, from the container's directory, and a
stream over the byte budget for the triangle cap (:func:`byte_budget`) is
refused without reading it. The triangle cap is checked after the read.

An assembly is read through :func:`solidseas.geometry.display_geometry`
(:func:`read_assembly_scene`): one mesh per component file, each uploaded once,
and every instance that uses it with its placement in the assembly, which the
3D view draws with the mesh's buffers and the instance's matrix. The triangle
cap and the byte budget then bound the whole assembly, and the drawn budget
(:func:`drawn_budget`) the triangles of all its instances together: an
instance whose mesh would pass them is left out, and the view names it. Each
instance left out comes with its place and, where the assembly stores one, its
box (:func:`placeholders`), which the view draws in its place: the boxes are
made ready here too (:class:`BoxBuffers`), so the window only uploads them. A
stored box no model could have (beyond :data:`MAX_BOX_M` from the origin, or
far outside the box the assembly stores for itself, :data:`BOX_REACH`) is taken
as damaged and not drawn, so it can never take the camera away from the model.
The files of a sub-assembly read from its own file that are files the top
assembly names too are drawn as those (:func:`file_groups`): one legend row and
one colour a file. A virtual part opened on its own usually stores no mesh of
its own; it is drawn from the one its assembly keeps of it
(:func:`assembly_mesh_of`).

Nothing here imports Qt, so it is tested on its own.
"""

import colorsys
import math
import os
import time
from array import array
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from solidseas import model, open_document
from solidseas.formats.solidworks.components import parse_bounding_box
from solidseas.geometry import Box, DisplayGeometry, display_geometry

from .explode import instance_bounds

# The triangle cap: a part whose saved mesh has more triangles is read but not
# drawn, and the 3D view says so. Of 1,779 real parts with a display mesh the
# largest had 305,012 triangles, and reading cost 1.2 to 3.3 microseconds a
# triangle on large meshes, so the default draws every one of them and keeps a
# read near three seconds at most. Drawing is not what the cap protects: 20
# million triangles drew in under 9 ms a frame on a desktop graphics card.
#
# For an assembly the cap counts the triangles read over all its meshes, each
# component file's once, however many instances share it. Measured over the 325
# corpus assemblies in the mesh process: the most any read was 568,808 triangles
# (1,008,938 drawn), in 1.7 s at 113 MB of peak memory; the median read took
# 0.08 s and 24 MB, the slowest 3.1 s and the largest 240 MB. So the part's
# default covers every one of them, with the same bound on time. Instances are
# drawn from shared buffers, so what is drawn costs little: the ten largest drew
# in 0.4 to 2.1 ms a frame, and ten copies of the largest (10 million
# triangles) in 2.2 ms.
DEFAULT_TRIANGLE_CAP = 1_000_000
# A part that saved no display mesh is drawn from the triangles of its own bodies
# (solidseas.tessellate), within the same time display_geometry's brep source gives
# each part of an assembly.
BREP_SECONDS = 30.0
MIN_TRIANGLE_CAP = 10_000
MAX_TRIANGLE_CAP = 50_000_000

# The byte budget: the largest display-list stream read for each triangle the cap
# allows. Real parts store 160 to 830 bytes a triangle (the largest stream of the
# corpus, 124 MB, holds 150,000 triangles), so at the default cap the budget is
# 256 MB, twice that stream; at the smallest cap it is 64 MB. The library itself
# reads at most 1 GiB.
BUDGET_BYTES_PER_TRIANGLE = 256
MIN_BYTE_BUDGET = 64 << 20
MAX_BYTE_BUDGET = 1 << 30
DISPLAY_LISTS = ("contents/displaylists", "contents/displaylists__zlb")


def byte_budget(cap: int) -> int:
    """The largest display-list stream read under a triangle cap of ``cap``."""
    return min(max(cap * BUDGET_BYTES_PER_TRIANGLE, MIN_BYTE_BUDGET), MAX_BYTE_BUDGET)


# The drawn budget: the cap bounds the triangles read, each file's once, but every
# instance of a mesh is drawn, on the UI thread, every frame and in every pick's id
# pass. A crafted assembly of 100,000 instances of a part just under the cap would draw
# 1e11 triangles a frame; on a desktop card 88 million took 77 ms a frame, so about
# 3,000 such instances would pass the 2 s after which Windows resets the graphics
# driver. So an assembly draws at most DRAWN_PER_CAP times the cap, never above
# MAX_DRAWN, never below the cap itself (one instance of the largest mesh read): 20
# million at the default cap, about 17 ms a frame there. The most any corpus assembly
# draws is 1,008,938.
DRAWN_PER_CAP = 20
MAX_DRAWN = 100_000_000


def drawn_budget(cap: int) -> int:
    """The most triangles an assembly's instances draw together under a cap of ``cap``."""
    return max(cap, min(cap * DRAWN_PER_CAP, MAX_DRAWN))


def display_list_bytes(doc) -> int | None:
    """The decoded size of the part's display-list stream, from the container's
    directory without reading it, or None when it has none."""
    sizes = [s.size for s in doc.streams() if s.name.lower() in DISPLAY_LISTS]
    return max(sizes) if sizes else None


@dataclass
class MeshBuffers:
    """What the 3D view uploads: vertex positions and normals (float32 xyz) and
    triangle indices (uint32), with the model's bounding box in metres."""

    positions: bytes
    normals: bytes
    indices: bytes
    n_vertices: int
    n_triangles: int
    bbox: tuple[tuple[float, float, float], tuple[float, float, float]]

    @property
    def nbytes(self) -> int:
        return len(self.positions) + len(self.normals) + len(self.indices)


def prepare(mesh) -> MeshBuffers | None:
    """The buffers for a ``solidseas`` mesh, or None when it has no triangles."""
    if mesh is None or mesh.n_triangles == 0:
        return None
    p = mesh.positions
    normals = mesh.normals if len(mesh.normals) == len(p) else array("f", bytes(4 * len(p)))
    lo = (min(p[0::3]), min(p[1::3]), min(p[2::3]))
    hi = (max(p[0::3]), max(p[1::3]), max(p[2::3]))
    return MeshBuffers(
        positions=p.tobytes(),
        normals=normals.tobytes(),
        indices=mesh.triangles.tobytes(),
        n_vertices=mesh.n_vertices,
        n_triangles=mesh.n_triangles,
        bbox=(lo, hi),
    )


def read_part_mesh(
    path: str,
    folder: str,
    cap: int,
    cancelled: Callable[[], bool] = lambda: False,
    *,
    nested: tuple[str, ...] = (),
    brep_cache=None,
) -> dict[str, Any]:
    """Read a part's display mesh for the 3D view.

    Returns ``{"state": ..., "seconds": {...}}`` with ``state`` one of ``ok``
    (``data`` is a :class:`MeshBuffers`), ``no_mesh``, ``not_part``,
    ``too_large`` (``triangles`` says how many the mesh has, or ``bytes`` how
    large its stream is when that is over ``budget``, the byte budget, and it
    was not read; ``cap`` is the triangle cap), ``cancelled`` or ``error``
    (``error`` is ``solidseas.model.error_info``). The document is opened
    read-only within ``folder``, like every other read of the viewer, and
    ``nested`` reads the nested document those streams lead to inside it (a
    virtual part, from its assembly). With ``brep_cache``
    (:class:`solidseas.tesscache.TessellationCache`) a part drawn from its bodies
    takes their tessellation from the cache when it holds it (``reused`` is then
    True), and leaves a whole one there for the next read.
    """
    seconds: dict[str, float] = {}
    if cancelled():  # the selection moved on while this waited its turn
        return {"state": "cancelled", "seconds": seconds}
    t = time.perf_counter()
    stored_in = None  # a virtual part's mesh comes from its assembly
    reused = False
    try:
        with open_document(path, within=folder) as top:
            parent, doc = None, top
            for stream in nested:
                parent, doc = doc, doc.nested(stream)
            seconds["open"] = time.perf_counter() - t
            if doc.doc_type != "part":
                return {"state": "not_part", "doc_type": doc.doc_type, "seconds": seconds}
            size, budget = display_list_bytes(doc), byte_budget(cap)
            if size is not None and size > budget:
                return {"state": "too_large", "bytes": size, "budget": budget, "cap": cap, "seconds": seconds}
            if cancelled():
                return {"state": "cancelled", "seconds": seconds}
            t = time.perf_counter()
            mesh = doc.mesh()
            if (mesh is None or mesh.n_triangles == 0) and parent is not None and nested:
                over: list[str] = []
                mesh = assembly_mesh_of(parent, nested[-1], cap, over)
                stored_in = "assembly" if mesh is not None else None
                if over:  # the assembly keeps a mesh of it, over the limit
                    seconds["read"] = time.perf_counter() - t
                    return {"state": "too_large", "in_assembly": True, "cap": cap, "seconds": seconds}
            seconds["read"] = time.perf_counter() - t
            if (mesh is None or mesh.n_triangles == 0) and not cancelled():
                # No display mesh saved anywhere: the triangles of the part's own bodies,
                # as display_geometry's brep source gives them for an assembly.
                t = time.perf_counter()
                cache_key = brep_cache.key(doc, None) if brep_cache is not None else None
                hit = brep_cache.get(cache_key) if cache_key is not None else None
                tess = None
                if hit is None:
                    tess = doc.tessellate(max_triangles=cap + 1, max_seconds=BREP_SECONDS)
                seconds["tessellate"] = time.perf_counter() - t
                if tess is not None and "max_triangles" in tess.truncated:
                    return {
                        "state": "too_large",
                        "triangles": cap + 1,  # more than the cap: how many more is not counted
                        "from_bodies": True,
                        "cap": cap,
                        "seconds": seconds,
                    }
                if hit is not None:
                    mesh, stored_in, reused = hit.mesh, "bodies", True
                elif tess is not None and tess.mesh.n_triangles:
                    mesh, stored_in = tess.mesh, "bodies"
                    _keep_tessellation(brep_cache, cache_key, tess)
    except MemoryError:  # the mesh process's memory limit (:mod:`.meshproc`)
        return {"state": "too_large", "memory": True, "cap": cap, "seconds": seconds}
    except Exception as exc:  # shown in the 3D view; never escapes the worker
        return {"state": "error", "error": model.error_info(exc), "seconds": seconds}
    if cancelled():
        return {"state": "cancelled", "seconds": seconds}
    if mesh is None or mesh.n_triangles == 0:
        return {"state": "no_mesh", "nested": bool(nested), "seconds": seconds}
    if mesh.n_triangles > cap:
        over = {"state": "too_large", "triangles": mesh.n_triangles, "cap": cap, "seconds": seconds}
        if stored_in == "bodies":
            over["from_bodies"] = True
        return over
    t = time.perf_counter()
    data = prepare(mesh)
    seconds["build"] = time.perf_counter() - t
    result = {"state": "ok", "data": data, "seconds": seconds}
    if stored_in:
        result["stored_in"] = stored_in
    if reused:
        result["reused"] = True
    return result


def _keep_tessellation(cache, key, tess) -> None:
    """Leave a part's whole tessellation in ``cache`` for the next read. It is made outside
    display geometry, so without the warnings that geometry's ``brep`` source gives with
    it: that source tessellates the part again when it needs it, and keeps that one."""
    if cache is None or key is None:
        return
    from solidseas.tesscache import CachedTessellation, keepable

    if keepable(tess):
        cache.put(key, CachedTessellation(tess.configuration, None, tess.mesh, None, tess.chord_m))
    else:
        cache.refuse()


def assembly_mesh_of(assembly, stream: str, cap: int, over: list[str] | None = None):
    """The display mesh ``assembly`` stores for its virtual component kept in the nested
    document ``stream``, or None. SOLIDWORKS keeps a virtual part's display mesh in its
    assembly (``FaceTessellations``, or an older assembly's own display lists), and often
    none in the part's own nested document, so a virtual part opened on its own is drawn
    from there: the mesh of the first instance of it the assembly's active
    configuration shows. Only the assembly's own streams are read. When the assembly
    holds a mesh of it that ``cap`` refuses, the limit's name is added to ``over``."""
    if assembly.doc_type != "assembly":
        return None
    g = display_geometry(assembly, sources=("assembly",), max_triangles=cap, max_bytes=byte_budget(cap))
    keys = {k for k, f in g.files.items() if f.nested == stream}
    for inst in g.instances:
        if inst.file in keys:
            return g.meshes[inst.mesh].mesh
    if over is not None:
        limits = ("max_triangles", "max_bytes")
        over.extend(s.reason for s in g.skipped if s.file in keys and s.reason in limits)
    return None


# --------------------------------------------------------------------------- assemblies
MAX_SKIPPED_LISTED = 500  # instances not shown that a result names one by one; the rest are counted
MAX_EXPANDED_ROWS = 2_000  # rows of sub-assemblies' own files sent: the Components tab shows no more
# Instances not shown whose place and stored box a result carries, for the view to draw a box in
# their place: as many as the library expands by default, 88 bytes each.
MAX_PLACEHOLDERS = 100_000
# Component colours: ten that stay apart from one another under the view's lighting, on
# the light and the dark background alike, then hues a golden angle apart.
_PALETTE = (
    "#4e79a7",
    "#f28e2b",
    "#59a14f",
    "#e15759",
    "#76b7b2",
    "#edc948",
    "#b07aa1",
    "#ff9da7",
    "#9c755f",
    "#8cd17d",
)


def component_color(index: int) -> tuple[float, float, float]:
    """The colour of the ``index``-th component file, as red, green and blue from 0 to 1."""
    if index < len(_PALETTE):
        h = _PALETTE[index].lstrip("#")
        return int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    hue = (0.1 + (index - len(_PALETTE)) * 0.381966) % 1.0
    lightness = (0.55, 0.42, 0.66)[(index - len(_PALETTE)) % 3]
    return colorsys.hls_to_rgb(hue, lightness, 0.55)


def color_name(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(c * 255):02x}" for c in rgb)


@dataclass
class BoxBuffers:
    """The instances drawn as boxes, for want of a mesh: each one's matrix from a unit
    cube (0 to 1 along each axis) to its stored box placed in the assembly
    (``matrices``, float32, column-major, 16 per box) and that box in the assembly's
    frame (``bounds``, float32 low then high x, y, z per box, as
    :func:`.explode.instance_bounds` gives them), with their component tree ids, file
    keys, file names and the reasons they have no mesh (:data:`.wording.NOT_SHOWN`).
    ``count`` is how many have a box in all, :data:`MAX_PLACEHOLDERS` at most of which
    are here; ``bbox`` holds every box here."""

    matrices: bytes
    bounds: bytes
    ids: list[str]
    files: list[str | None]
    names: list[str | None]
    reasons: list[str]
    count: int
    bbox: tuple[tuple[float, float, float], tuple[float, float, float]]

    def __len__(self) -> int:
        return len(self.ids)

    @property
    def nbytes(self) -> int:
        return len(self.matrices) + len(self.bounds)


@dataclass
class SceneBuffers:
    """An assembly ready for the 3D view: each mesh once (``meshes``, in its
    component's own coordinates) and, for each mesh, its instances: their 4 x 4
    matrices (``matrices[i]``, float32, column-major, 16 per instance), the index
    of the component file each one is (``files_of[i]``, uint32, into ``files``)
    and their component tree ids (``instance_ids[i]``). ``files`` are the legend:
    ``{"key", "name", "instances", "color"}`` by first appearance. ``bbox`` holds
    every instance in the assembly's frame, and ``bounds[i]`` each instance's own box
    there (float32 low then high x, y, z; :func:`.explode.instance_bounds`), which the
    exploded view moves. ``boxes`` are the instances to draw as boxes, without a mesh
    (:class:`BoxBuffers`), or None; an assembly with nothing but those has no
    ``meshes``, and its ``bbox`` is theirs. ``documents`` gives, for an instance read
    from a sub-assembly's own file (its file key ``<sub-assembly key>/<key>``), whose
    row the components section does not have, the part's own document its mesh was
    read from (``path``, ``nested``), the configuration the instance uses and its file
    name, by instance id: what 3D Print exports for it (:func:`instance_documents`).
    ``missing`` gives, for such an instance drawn from what its sub-assembly stores of
    it because its own file was not found, could not be told from others or could not
    be read, its name, stored path and that reason, by instance id: what the 3D view's
    menu says in place of 3D Print (:func:`instance_missing`). ``expanded`` are the rows
    the Components tab lacks for the instances read from
    sub-assemblies' own files (:func:`expanded_rows`)."""

    meshes: list[MeshBuffers]
    matrices: list[bytes]
    files_of: list[bytes]
    instance_ids: list[list[str]]
    files: list[dict[str, Any]]
    bbox: tuple[tuple[float, float, float], tuple[float, float, float]]
    n_instances: int = 0
    n_triangles: int = 0  # drawn: every instance's triangles
    info: dict[str, Any] = field(default_factory=dict)
    bounds: list[bytes] = field(default_factory=list)
    boxes: BoxBuffers | None = None
    documents: dict[str, dict[str, Any]] = field(default_factory=dict)
    missing: dict[str, dict[str, Any]] = field(default_factory=dict)
    expanded: list[dict[str, Any]] = field(default_factory=list)

    @property
    def nbytes(self) -> int:
        return (
            sum(m.nbytes for m in self.meshes)
            + sum(len(b) for b in self.matrices)
            + sum(len(b) for b in self.files_of)
            + sum(len(b) for b in self.bounds)
            + (self.boxes.nbytes if self.boxes is not None else 0)
        )


def _folded_path(path: str | None) -> str | None:
    return path.replace("/", "\\").casefold() if path else None


def file_groups(g) -> dict[str, str]:
    """For each file key of ``g``, the key of the file the view draws it as. A file of a
    sub-assembly read from its own file (keyed ``<sub-assembly key>/<its key>``) that is a
    file already keyed is drawn as that one, the top assembly's keys first: the same file
    found on disk for its mesh, the same stored path (case-folded), or the same file name,
    since SOLIDWORKS holds one document of a name open at a time, so in one assembly a
    name is one file (a name two of the top assembly's keys bear is not used). Every
    other key stands for itself, and two of the top assembly's own keys are never merged."""
    disk: dict[str, set[str]] = {}
    for inst in g.instances:
        m = g.meshes.get(inst.mesh)
        if inst.file and m is not None and m.kind == "file" and m.path:
            disk.setdefault(inst.file, set()).add(os.path.normcase(os.path.abspath(m.path)))
    top_names = [(f.file_name or "").casefold() for k, f in g.files.items() if "/" not in k and f.file_name]
    seen: dict[tuple[str, str], str] = {}
    out: dict[str, str] = {}
    for key in sorted(g.files, key=lambda k: k.count("/")):
        f = g.files[key]
        idents = [("disk", p) for p in sorted(disk.get(key, ()))]
        stored = _folded_path(f.stored_path)
        if stored:
            idents.append(("path", stored))
        name = (f.file_name or "").casefold()
        if name and top_names.count(name) <= 1:
            idents.append(("name", name))
        found = None if "/" not in key else next((seen[i] for i in idents if i in seen), None)
        out[key] = found or key
        for i in idents:
            seen.setdefault(i, out[key])
    return out


# The kinds of mesh read from the part's own document: its file's display mesh, its
# bodies tessellated, or a virtual part's document kept inside an assembly.
OWN_DOCUMENT_KINDS = ("file", "brep", "nested")


def instance_documents(g) -> dict[str, dict[str, Any]]:
    """For each instance of ``g`` read from a sub-assembly's own file (its file key has a
    ``/``), the part's own document its mesh was read from, when it was: ``{"path",
    "nested", "configuration", "name"}`` by instance id. A part drawn from what its
    sub-assembly stores of it, its own file not found, has none."""
    out: dict[str, dict[str, Any]] = {}
    for inst in g.instances:
        if not inst.file or "/" not in inst.file:
            continue
        m = g.meshes.get(inst.mesh)
        if m is None or m.kind not in OWN_DOCUMENT_KINDS or not m.path:
            continue
        f = g.files.get(inst.file)
        name = (f.file_name or os.path.basename((f.stored_path or "").replace("\\", "/"))) if f else None
        out[inst.id] = {
            "path": m.path,
            "nested": list(m.nested),
            "configuration": inst.configuration,
            "name": name or inst.name,
        }
    return out


# Why a part's own file gave the 3D view no mesh, when that also means 3D Print cannot read
# it, in the few words its greyed menu entry gives (geometry's reasons).
UNPRINTABLE_FILE = {
    "missing": "not found",
    "ambiguous": "several files could be it",
    "unreadable": "its file could not be read",
}


def instance_missing(g) -> dict[str, dict[str, Any]]:
    """For each instance of ``g`` read from a sub-assembly's own file (its file key has a
    ``/``) that is drawn from what a sub-assembly stores of it because its own file
    gave no mesh for a reason of :data:`UNPRINTABLE_FILE` (``g.file_failures``):
    ``{"name", "stored_path", "reason"}`` by instance id, its file's name, the path its
    sub-assembly stores for it and that reason. One whose own file was found and read
    has its document instead (:func:`instance_documents`)."""
    failures = getattr(g, "file_failures", None) or {}
    out: dict[str, dict[str, Any]] = {}
    for inst in g.instances:
        if not inst.file or "/" not in inst.file:
            continue
        m = g.meshes.get(inst.mesh)
        reason = failures.get(inst.file)
        if m is None or m.kind in OWN_DOCUMENT_KINDS or reason not in UNPRINTABLE_FILE:
            continue
        f = g.files.get(inst.file)
        stored = (f.stored_path or None) if f else None
        name = (f.file_name or os.path.basename((stored or "").replace("\\", "/"))) if f else None
        out[inst.id] = {"name": name or inst.name, "stored_path": stored, "reason": reason}
    return out


def expanded_rows(g) -> list[dict[str, Any]]:
    """The instances ``g`` read from sub-assemblies' own documents, for the Components
    tab, which lists only what the assembly's own tree does. One entry for each
    sub-assembly instance expanded (:attr:`solidseas.geometry.DisplayGeometry.expanded`),
    parents first: ``{"id", "file", "configuration", "nodes", "children", "files"}``.
    ``children`` are its instances as the ``components`` kind gives them
    (:func:`solidseas.model.component_node_data`), their ids and file keys under the
    sub-assembly's (``<id>/...``, ``<file>/...``) and their placements in the top
    assembly's frame; ``files`` are its files as the ``references`` kind gives them, each
    with the resolution the read made of it (None where it made none). ``nodes`` counts
    the instances its tree holds; over all entries at most :data:`MAX_EXPANDED_ROWS` are
    given, as the tab shows no more."""
    out: list[dict[str, Any]] = []
    budget = MAX_EXPANDED_ROWS
    for e in g.expanded:
        if not e.file:
            continue
        results = e.resolution.results if e.resolution is not None else {}
        depth = e.id.count("/") + 1

        def row(n, parent: str, e=e, depth=depth) -> dict[str, Any]:
            nonlocal budget
            budget -= 1
            d = model.component_node_data(n, flat=True)
            place = None
            if e.placement is not None and n.placement is not None:
                composed = e.placement.then(n.placement)
                place = composed if composed.is_finite() else None
            d.update(
                id=f"{e.id}/{n.id}",
                parent=parent,
                depth=depth + n.depth,
                file=f"{e.file}/{n.file}" if n.file is not None else None,
                placement=model.placement_data(place),
            )
            kids = []
            for c in n.children:
                if budget <= 0:
                    break
                kids.append(row(c, d["id"]))
            d["children"] = kids
            return d

        children = []
        for n in e.tree.children:
            if budget <= 0:
                break
            children.append(row(n, e.id))
        files = []
        for f in e.tree.files.values():
            fd = model.component_file_data(f)
            fd["key"] = f"{e.file}/{f.key}"
            r = results.get(f.key)
            fd["resolution"] = None if r is None else {**model.resolution_result_data(r), "key": fd["key"]}
            files.append(fd)
        entry = {
            "id": e.id,
            "file": e.file,
            "configuration": e.configuration,
            "nodes": e.tree.node_count,
            "children": children,
            "files": files,
        }
        try:
            out.append(model.to_json_data(entry))
        except (TypeError, ValueError):  # a value JSON cannot carry: the tab goes without it
            continue
    return out


def scene_from_geometry(g, *, cancelled: Callable[[], bool] = lambda: False) -> "SceneBuffers | None":
    """The buffers for a :class:`solidseas.geometry.DisplayGeometry`, or None when it
    places no instance (or ``cancelled`` turned true). Each file gets the next
    colour of :func:`component_color` in the order its first instance comes, a file
    read from a sub-assembly's own file that the assembly names too counting as that
    file (:func:`file_groups`; the legend entry's ``keys`` are every key it stands
    for)."""
    groups = file_groups(g)
    order: dict[str, int] = {}
    files: list[dict[str, Any]] = []
    mesh_index: dict[str, int] = {}
    meshes: list[MeshBuffers] = []
    matrices: list[array] = []
    files_of: list[array] = []
    ids: list[list[str]] = []
    for inst in g.instances:
        if cancelled():
            return None
        mi = mesh_index.get(inst.mesh)
        if mi is None:
            buffers = prepare(g.meshes[inst.mesh].mesh)
            if buffers is None:
                continue
            mi = mesh_index[inst.mesh] = len(meshes)
            meshes.append(buffers)
            matrices.append(array("f"))
            files_of.append(array("I"))
            ids.append([])
        raw = inst.file or ""
        key = groups.get(raw, raw)
        fi = order.get(key)
        if fi is None:
            fi = order[key] = len(files)
            f = g.files.get(key)
            files.append(
                {
                    "key": key,
                    "keys": [key],
                    "name": (f.file_name or f.stored_path) if f is not None else None,
                    "instances": 0,
                    "color": color_name(component_color(fi)),
                }
            )
            files[fi]["name"] = files[fi]["name"] or inst.name
        if raw not in files[fi]["keys"]:
            files[fi]["keys"].append(raw)
        files[fi]["instances"] += 1
        matrices[mi].extend(inst.matrix())
        files_of[mi].append(fi)
        ids[mi].append(inst.id)
    if not meshes:
        return None
    placed = [m.tobytes() for m in matrices]
    # Each instance's box from its mesh's box, measured once per mesh by prepare(); the
    # assembly's box is their union, so nothing here passes over a mesh per instance.
    bounds = [instance_bounds(m.bbox, p) for m, p in zip(meshes, placed, strict=True)]
    return SceneBuffers(
        meshes=meshes,
        matrices=placed,
        files_of=[f.tobytes() for f in files_of],
        instance_ids=ids,
        files=files,
        bbox=bounds_box(bounds),
        n_instances=sum(len(i) for i in ids),
        n_triangles=sum(m.n_triangles * len(i) for m, i in zip(meshes, ids, strict=True)),
        bounds=bounds,
        documents=instance_documents(g),
        missing=instance_missing(g),
    )


# A stored box is drawn only where a model could be: within this many metres of the
# origin, and within this many diagonals of the box the assembly stores for itself, past
# each of its sides. On the development corpus no component's box sticks out of its
# assembly's by 2% of the diagonal; past these, a box is taken as damaged and not drawn.
MAX_BOX_M = 1e4
BOX_REACH = 10


def assembly_box(doc, configuration: str | None) -> Box | None:
    """The box an assembly stores for itself in ``configuration`` (its own model's
    ``swBoundingBox``, ``docs/FORMAT.md`` 12.3: the active configuration's, or a copy of
    it), or None when there is none."""
    try:
        md = doc.metadata.tree or {}
        for c in md.get("configs", []):
            if c.get("name") == configuration:
                return parse_bounding_box((md.get("models", {}).get(c.get("model_ref")) or {}).get("bbox"))
    except Exception:  # no box to compare with, which is not a failure
        return None
    return None


def plausible(box: Box, reference: Box | None = None) -> bool:
    """Whether a placed box (in the assembly's frame) is one a model could have: finite,
    within :data:`MAX_BOX_M` of the origin, and with ``reference`` (:func:`assembly_box`)
    within :data:`BOX_REACH` of its diagonals past each of its sides."""
    values = (*box[0], *box[1])
    if not all(math.isfinite(v) and abs(v) <= MAX_BOX_M for v in values):
        return False
    if reference is None:
        return True
    (a0, a1) = reference
    reach = BOX_REACH * max(math.dist(a0, a1), 1e-3)
    return all(a0[i] - reach <= box[0][i] and box[1][i] <= a1[i] + reach for i in range(3))


def placeholders(g: DisplayGeometry, reference: Box | None = None) -> dict[str, Any]:
    """The instances ``g`` does not draw that have a placement and a stored box
    (:class:`solidseas.geometry.SkippedInstance`), packed for the view to draw a box in
    each one's place: ``ids``, ``files`` (file keys, as :func:`file_groups` draws them),
    ``names`` (their file names) and ``reasons`` in order, ``matrices`` (float32, 16 an
    instance, column-major, the component's frame to the assembly's) and ``boxes``
    (float32, six an instance: low then high x, y, z in the component's own coordinates,
    metres). At most :data:`MAX_PLACEHOLDERS`; ``count`` is how many there are in all.
    A box no model could have (:func:`plausible`, against ``reference``) is left out and
    counted in ``implausible``."""
    groups = file_groups(g)
    ids: list[str] = []
    files: list[str | None] = []
    names: list[str | None] = []
    reasons: list[str] = []
    matrices, boxes = array("f"), array("f")
    count = implausible = 0
    for s in g.skipped:
        matrix = s.matrix()
        placed = g.placeholder(s)
        if matrix is None or placed is None:
            continue
        if not plausible(placed, reference):
            implausible += 1
            continue
        count += 1
        if len(ids) >= MAX_PLACEHOLDERS:
            continue
        ids.append(s.id)
        key = groups.get(s.file or "", s.file) if s.file else None
        files.append(key)
        f = g.files.get(key or "")
        names.append((f.file_name or f.stored_path) if f is not None else None)
        reasons.append(s.reason)
        matrices.extend(matrix)
        boxes.extend((*s.box[0], *s.box[1]))  # type: ignore[index]
    return {
        "count": count,
        "implausible": implausible,
        "ids": ids,
        "files": files,
        "names": names,
        "reasons": reasons,
        "matrices": matrices.tobytes(),
        "boxes": boxes.tobytes(),
    }


def box_matrices(matrices: bytes, boxes: bytes) -> bytes:
    """For each placement of ``matrices`` (float32, 16 each, column-major) and stored box of
    ``boxes`` (float32 low then high x, y, z each, in the component's own coordinates), the
    matrix that takes a unit cube (0 to 1 along each axis) to that box placed: the
    placement times the box's scale and offset. Float32, 16 each."""
    m, b = array("f"), array("f")
    m.frombytes(matrices)
    b.frombytes(boxes)
    out = array("f")
    for k in range(min(len(m) // 16, len(b) // 6)):
        o, q = 16 * k, 6 * k
        lo = (b[q], b[q + 1], b[q + 2])
        size = (b[q + 3] - b[q], b[q + 4] - b[q + 1], b[q + 5] - b[q + 2])
        for c in range(3):  # the placement's axis columns, each scaled by the box's size
            out.extend((m[o + 4 * c] * size[c], m[o + 4 * c + 1] * size[c], m[o + 4 * c + 2] * size[c], 0.0))
        out.extend(
            (
                m[o] * lo[0] + m[o + 4] * lo[1] + m[o + 8] * lo[2] + m[o + 12],
                m[o + 1] * lo[0] + m[o + 5] * lo[1] + m[o + 9] * lo[2] + m[o + 13],
                m[o + 2] * lo[0] + m[o + 6] * lo[1] + m[o + 10] * lo[2] + m[o + 14],
                1.0,
            )
        )
    return out.tobytes()


UNIT_BOX = ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))


def box_buffers(ph: dict[str, Any]) -> BoxBuffers | None:
    """The boxes to draw for the placeholders ``ph`` (:func:`placeholders`), or None when
    there are none."""
    if not ph.get("ids"):
        return None
    matrices = box_matrices(ph["matrices"], ph["boxes"])
    bounds = instance_bounds(UNIT_BOX, matrices)
    return BoxBuffers(
        matrices=matrices,
        bounds=bounds,
        ids=list(ph["ids"]),
        files=list(ph["files"]),
        names=list(ph.get("names") or [None] * len(ph["ids"])),
        reasons=list(ph["reasons"]),
        count=ph["count"],
        bbox=bounds_box([bounds]),
    )


def bounds_box(bounds: list[bytes]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """The box holding every instance box of ``bounds`` (:func:`.explode.instance_bounds`)."""
    lo, hi = [float("inf")] * 3, [float("-inf")] * 3
    for raw in bounds:
        b = array("f")
        b.frombytes(raw)
        if not b:
            continue
        for i in range(3):
            lo[i] = min(lo[i], min(b[i::6]))
            hi[i] = max(hi[i], max(b[3 + i :: 6]))
    if lo[0] == float("inf"):
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])


def read_assembly_scene(
    path: str,
    within: str,
    root: str,
    cap: int,
    cancelled: Callable[[], bool] = lambda: False,
    *,
    nested: tuple[str, ...] = (),
    configuration: str | None = None,
    cache=None,
    outside: bool = True,
    brep_cache=None,
) -> dict[str, Any]:
    """Read an assembly for the 3D view, in the mesh process.

    The document is opened read-only within ``within`` (or the nested document
    ``nested`` leads to inside it), and its component files are found by
    reference resolution in ``root``, the opened folder, as the details panel
    finds them (``cache`` keeps that folder's index between reads), and without
    ``outside`` in that folder alone. ``cap`` is the
    triangle cap over every mesh read, and its byte budget the display data read.
    ``brep_cache`` (:class:`solidseas.tesscache.TessellationCache`) keeps the
    tessellations of parts drawn from their bodies between reads; the geometry's
    ``tessellations_reused`` then counts those this read took from it.

    Returns ``{"state", "seconds", ...}``. ``state`` is ``ok`` (``data`` is a
    :class:`SceneBuffers`: some instance is drawn from a mesh, or has a box to draw
    in its place, :attr:`SceneBuffers.boxes`), ``no_mesh`` (no instance could be
    drawn and none has a box), ``too_large`` (the same, because the cap or the
    budget was reached first), ``not_assembly`` (``doc_type`` says what it is),
    ``cancelled`` or ``error``. Every result but those last three has
    ``geometry``: the configuration shown, the counts, the limits reached, the
    instances not shown (``skipped``, at most :data:`MAX_SKIPPED_LISTED`, those
    without a box first, with ``skipped_count`` and ``skipped_reasons``, and
    ``placeholders``, where to draw a box for each that has a stored one:
    :func:`placeholders`) and the warnings of the meshes (``mesh_warnings``);
    ``placed`` counts the instances drawn from a mesh, and ``too_large`` says
    whether the cap or the budget left every one without a mesh, which the view
    says when it draws no boxes."""
    from solidseas import Root, Roots

    from .reading import ROOT_ID

    seconds: dict[str, float] = {}
    if cancelled():
        return {"state": "cancelled", "seconds": seconds}
    t = time.perf_counter()
    try:
        with open_document(path, within=within, hold_open=True) as top:
            doc = top
            for stream in nested:
                doc = doc.nested(stream)
            seconds["open"] = time.perf_counter() - t
            if doc.doc_type != "assembly":
                return {"state": "not_assembly", "doc_type": doc.doc_type, "seconds": seconds}
            t = time.perf_counter()
            hits = brep_cache.hits if brep_cache is not None else 0
            g = display_geometry(
                doc,
                configuration,
                roots=Roots([Root(ROOT_ID, os.path.abspath(root))]),
                # As the details panel resolves the references: a file found outside the
                # opened folder, on a local drive (never a network path), is drawn too,
                # read-only like every read. The Components tab shows it as found there,
                # and it opens from there too (docs/ARCHITECTURE.md, the viewer). Not with
                # Look for Referenced Files Only in the Opened Folder on (``outside``).
                allow_outside_roots=outside,
                cache=cache,
                max_triangles=cap,
                max_bytes=byte_budget(cap),
                max_triangles_drawn=drawn_budget(cap),
                brep_cache=brep_cache,
                # The Components tab lists the instances read from sub-assemblies' own files
                # and goes to their files, so where those are is worked out for each.
                resolve_expanded=True,
            )
            reference = assembly_box(doc, g.configuration)
            seconds["read"] = time.perf_counter() - t
    except MemoryError:  # the mesh process's memory limit (:mod:`.meshproc`)
        return {"state": "too_large", "memory": True, "cap": cap, "seconds": seconds}
    except Exception as exc:  # shown in the 3D view; never escapes the worker
        return {"state": "error", "error": model.error_info(exc), "seconds": seconds}
    if cancelled():
        return {"state": "cancelled", "seconds": seconds}
    t = time.perf_counter()
    scene = scene_from_geometry(g, cancelled=cancelled)
    seconds["build"] = time.perf_counter() - t
    if cancelled():
        return {"state": "cancelled", "seconds": seconds}
    reasons: dict[str, int] = {}
    for s in g.skipped:
        reasons[s.reason] = reasons.get(s.reason, 0) + 1
    names = {k: f.file_name for k, f in g.files.items()}
    t = time.perf_counter()
    ph = placeholders(g, reference)
    boxes = box_buffers(ph)
    seconds["build"] += time.perf_counter() - t  # the boxes are made ready with the meshes
    # Named one by one up to a limit: those drawn as nothing at all first, which the
    # status line names; the ones drawn as boxes it counts.
    boxed = set(ph["ids"])
    listed = sorted(g.skipped, key=lambda s: s.id in boxed)
    limited = {"max_triangles", "max_bytes"} & set(g.truncated)
    info = {
        "configuration": g.configuration,
        "configuration_source": g.configuration_source,
        "counts": dict(g.counts),
        "truncated": list(g.truncated),
        "skipped": [
            {
                "id": s.id,
                "name": s.name,
                "file": names.get(s.file or ""),
                "reason": s.reason,
                "message": s.message,
            }
            for s in listed[:MAX_SKIPPED_LISTED]
        ],
        "skipped_count": len(g.skipped),
        "skipped_reasons": reasons,
        "placeholders": ph,
        "placed": len(g.instances),
        "too_large": bool(limited) and not g.instances,
        "mesh_warnings": [
            {"file": names.get(m.file or ""), "code": w.code, "message": w.message}
            for m in g.meshes.values()
            for w in m.warnings
        ],
        "sources": sorted({m.kind for m in g.meshes.values()}),
        "cap": cap,
        "drawn_cap": drawn_budget(cap),
    }
    if brep_cache is not None:
        info["tessellations_reused"] = brep_cache.hits - hits
    if scene is None and boxes is None:
        state = "too_large" if info["too_large"] else "no_mesh"
        return {"state": state, "geometry": info, "cap": cap, "seconds": seconds}
    if scene is None:  # nothing but boxes
        assert boxes is not None
        scene = SceneBuffers(meshes=[], matrices=[], files_of=[], instance_ids=[], files=[], bbox=boxes.bbox)
    scene.boxes = boxes
    scene.info = info
    scene.expanded = expanded_rows(g)
    return {"state": "ok", "data": scene, "geometry": info, "cap": cap, "seconds": seconds}


# --------------------------------------------------------------------------- 3D files of other formats
# The view's frame is Y-up, as SOLIDWORKS draws: a format whose models stand on Z (STL, 3MF,
# glTF after its reader's turn: the registry's up_axis) is turned so its Z points up on screen,
# x' = x, y' = z, z' = -y, a quarter turn about X, before anything is drawn.
IDENTITY3 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def _turned(rotation, translation, up: str):
    """A placement (rows, metres) with the view's turn for ``up`` applied on the left."""
    r = tuple(tuple(float(v) for v in row) for row in rotation)
    t = tuple(float(v) for v in translation)
    if up != "z":
        return r, t
    return (r[0], r[2], tuple(-v for v in r[1])), (t[0], t[2], -t[1])


def _column_major(rotation, translation) -> tuple[float, ...]:
    r, t = rotation, translation
    return (
        r[0][0], r[1][0], r[2][0], 0.0,
        r[0][1], r[1][1], r[2][1], 0.0,
        r[0][2], r[1][2], r[2][2], 0.0,
        t[0], t[1], t[2], 1.0,
    )  # fmt: skip


def _float_box(p: array) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    return (min(p[0::3]), min(p[1::3]), min(p[2::3])), (max(p[0::3]), max(p[1::3]), max(p[2::3]))


# A model drawn farther out than this is refused before it is answered. The readers drop
# vertices beyond 1,000 km and skip items placed beyond it, so only a placement that scales its
# object enormously gets here; its float32 buffers would hold infinities the window refuses.
MAX_DRAWN_M = 1e9


def _out_of_reach(box) -> dict[str, Any] | None:
    """The error answer for a model whose drawn ``box`` is not finite or lies beyond
    :data:`MAX_DRAWN_M`, else None."""
    if all(math.isfinite(v) and abs(v) <= MAX_DRAWN_M for corner in box for v in corner):
        return None
    from solidseas.errors import SldLimitError

    exc = SldLimitError(
        "the model's placements put it farther out than a million kilometres (a placement that scales "
        "its object enormously), so it is not drawn",
        detail={"limit": "coordinates"},
    )
    return {"state": "error", "error": model.error_info(exc)}


def _object_buffers(obj) -> MeshBuffers | None:
    """One mesh object of a scene, in its own frame, as the view uploads it."""
    if obj.n_triangles == 0:
        return None
    p = array("f", obj.positions)
    normals = obj.normals if obj.normals is not None and len(obj.normals) == len(p) else None
    n = array("f", normals) if normals is not None else array("f", bytes(4 * len(p)))
    return MeshBuffers(
        positions=p.tobytes(),
        normals=n.tobytes(),
        indices=array("I", obj.triangles).tobytes(),
        n_vertices=obj.n_vertices,
        n_triangles=obj.n_triangles,
        bbox=_float_box(p),
    )


def _rotate_into(out: array, values, rot, t=None) -> None:
    (a, b, c), (d, e, f), (g, h, k) = rot
    tx, ty, tz = t if t is not None else (0.0, 0.0, 0.0)
    for i in range(0, len(values), 3):
        x, y, z = values[i], values[i + 1], values[i + 2]
        out.extend((a * x + b * y + c * z + tx, d * x + e * y + f * z + ty, g * x + h * y + k * z + tz))


def merged_part(scene, up: str, cancelled: Callable[[], bool] = lambda: False) -> MeshBuffers | None:
    """Every placed item of ``scene`` as one mesh in the model's frame, turned for ``up``:
    a part, in one colour, as a SOLIDWORKS part is drawn. None when nothing is drawn."""
    pos, nrm, idx = array("f"), array("f"), array("I")
    for it in scene.items:
        if cancelled():
            return None
        obj = scene.objects[it.object]
        if obj.n_triangles == 0:
            continue
        rot, t = _turned(it.placement.rotation, it.placement.translation_m, up)
        base = len(pos) // 3
        p = obj.positions
        if rot == IDENTITY3 and t == (0.0, 0.0, 0.0):
            pos.extend(array("f", p))
        else:
            _rotate_into(pos, p, rot, t)
        ns = obj.normals if obj.normals is not None and len(obj.normals) == len(p) else None
        if ns is None:
            nrm.frombytes(bytes(4 * len(p)))  # none stored: the view lights each face from its plane
        elif rot == IDENTITY3:
            nrm.extend(array("f", ns))
        else:
            _rotate_into(nrm, ns, rot)
        if base:
            idx.extend(v + base for v in obj.triangles)
        else:
            idx.extend(obj.triangles)
    if not idx:
        return None
    return MeshBuffers(
        positions=pos.tobytes(),
        normals=nrm.tobytes(),
        indices=idx.tobytes(),
        n_vertices=len(pos) // 3,
        n_triangles=len(idx) // 3,
        bbox=_float_box(pos),
    )


def model_scene_buffers(
    scene, nodes: list[dict[str, Any]], up: str, cap: int, cancelled: Callable[[], bool] = lambda: False
) -> tuple["SceneBuffers | None", list[dict[str, Any]]]:
    """An assembly of a model file ready for the view: each mesh object once, each placed
    item an instance named by its tree node's instance id (:func:`.modelview.path_ids`,
    the Components tab's rows), coloured by the file it stands for (an Alibre
    component's document, else the object), turned for ``up``; and the items left out
    because the drawn budget (:func:`drawn_budget`) was reached."""
    from .modelview import file_key, fold, path_ids

    ids = path_ids(nodes)
    by_id = {n["id"]: n for n in nodes}
    shown, alias = fold(nodes)  # the bodies of a part folded into one row share its file
    folded_into = {n["id"]: n for n in shown}
    budget = drawn_budget(cap)
    mesh_of: dict[int, int] = {}
    meshes: list[MeshBuffers] = []
    matrices: list[array] = []
    files_of: list[array] = []
    instance_ids: list[list[str]] = []
    files: list[dict[str, Any]] = []
    file_index: dict[str, int] = {}
    used: dict[str, int] = {}
    counted: set[str] = set()  # the multi-body parts placed so far: their other bodies add no instance
    skipped: list[dict[str, Any]] = []
    drawn = 0
    for k, it in enumerate(scene.items):
        if cancelled():
            return None, skipped
        obj = scene.objects[it.object]
        node = by_id.get(it.instance or "")
        base = ids.get(it.instance or "") if node is not None else None
        if not base:
            base = f"item {k + 1}"
        used[base] = used.get(base, 0) + 1
        if used[base] == 1:
            ident = base
        else:  # one node placed several times (an Alibre sub-assembly's parts): one row stands for all
            ident = f"{base}/{(obj.name or 'object').replace('%', '%25').replace('/', '%2F')} ({used[base]})"
        if drawn + obj.n_triangles > budget:
            skipped.append(
                {"id": ident, "name": obj.name, "file": None, "reason": "max_drawn", "message": ""}
            )
            continue
        mi = mesh_of.get(it.object)
        if mi is None:
            buffers = _object_buffers(obj)
            if buffers is None:
                continue
            mi = mesh_of[it.object] = len(meshes)
            meshes.append(buffers)
            matrices.append(array("f"))
            files_of.append(array("I"))
            instance_ids.append([])
        drawn += obj.n_triangles
        row = folded_into.get(alias.get(node["id"], "")) if node is not None else None
        key = file_key(row or node) if node is not None else f"object:{it.object}"
        fi = file_index.get(key)
        if fi is None:
            fi = file_index[key] = len(files)
            named = row if row is not None and row.get("objects") else node  # a multi-body part: its row
            name = (named or {}).get("name") or obj.name or key
            color = color_name(component_color(fi))
            files.append({"key": key, "keys": [key], "name": name, "instances": 0, "color": color})
        if row is None or not row.get("objects") or base not in counted:
            files[fi]["instances"] += 1
            if row is not None and row.get("objects"):
                counted.add(base)
        rot, t = _turned(it.placement.rotation, it.placement.translation_m, up)
        matrices[mi].extend(_column_major(rot, t))
        files_of[mi].append(fi)
        instance_ids[mi].append(ident)
    if not meshes:
        return None, skipped
    placed = [m.tobytes() for m in matrices]
    bounds = [instance_bounds(m.bbox, p) for m, p in zip(meshes, placed, strict=True)]
    return (
        SceneBuffers(
            meshes=meshes,
            matrices=placed,
            files_of=[f.tobytes() for f in files_of],
            instance_ids=instance_ids,
            files=files,
            bbox=bounds_box(bounds),
            n_instances=sum(len(i) for i in instance_ids),
            n_triangles=sum(m.n_triangles * len(i) for m, i in zip(meshes, instance_ids, strict=True)),
            bounds=bounds,
        ),
        skipped,
    )


def read_model_scene(
    path: str,
    within: str,
    cap: int,
    cancelled: Callable[[], bool] = lambda: False,
) -> dict[str, Any]:
    """Read a 3D file of another format than SOLIDWORKS for the view, in the mesh process.

    The file is opened read-only within ``within`` (:func:`solidseas.formats.open_model`)
    and its scene read with the display mesh it stores first (an Alibre part's), else
    its own triangles or its B-rep bodies tessellated within :data:`BREP_SECONDS`,
    under the triangle ``cap``. A part is drawn as one mesh (``data`` a
    :class:`MeshBuffers`, ``stored_in`` what its triangles came from: ``mesh``,
    ``bodies`` or ``display_mesh``); an assembly as a :class:`SceneBuffers` whose
    instances are named as the Components tab names its rows, with ``geometry`` as
    :func:`read_assembly_scene` gives it. The states are those of
    :func:`read_part_mesh` and :func:`read_assembly_scene`, and ``partial``: drawn as
    ``ok`` is, with faces of its bodies that could not be tessellated left out. A
    ``partial`` result says so in ``faces_left_out`` (:func:`faces_left_out`) and in a
    warning of that code, in ``warnings`` for a part and in the geometry's
    ``mesh_warnings`` for an assembly. Every result has ``model`` True, and ``format``
    and ``format_name`` once the file opened."""
    from solidseas.formats import open_model
    from solidseas.model import model_node_data

    seconds: dict[str, float] = {}
    out: dict[str, Any] = {"model": True, "seconds": seconds}
    if cancelled():
        return {**out, "state": "cancelled"}
    t = time.perf_counter()
    try:
        with open_model(path, within=within, hold_open=True) as doc:
            seconds["open"] = time.perf_counter() - t
            doc_type, up = doc.doc_type, doc.spec.up_axis
            out["format"], out["format_name"] = doc.format, doc.format_name
            t = time.perf_counter()
            scene = doc.scene(prefer="display", max_triangles=cap + 1, max_seconds=BREP_SECONDS)
            nodes = [model_node_data(n) for n in doc.tree().nodes] if doc_type == "assembly" else []
            seconds["read"] = time.perf_counter() - t
    except MemoryError:  # the mesh process's memory limit (:mod:`.meshproc`)
        return {**out, "state": "too_large", "memory": True, "cap": cap}
    except Exception as exc:  # shown in the 3D view; never escapes the process
        return {**out, "state": "error", "error": model.error_info(exc)}
    if cancelled():
        return {**out, "state": "cancelled"}
    placed = sum(scene.objects[it.object].n_triangles for it in scene.items)
    sources = sorted({o.source for o in scene.objects})
    if "max_triangles" in scene.truncated:
        return {
            **out,
            "state": "too_large",
            "triangles": cap + 1,
            "cap": cap,
            "from_bodies": "bodies" in sources,
        }
    if placed == 0:
        reasons = sorted({str(getattr(s, "reason", "")) for s in scene.skipped[:50]} - {""})
        return {**out, "state": "no_mesh", "reasons": reasons}
    left_out = faces_left_out(scene)
    drawn = "partial" if left_out else "ok"
    t = time.perf_counter()
    if doc_type != "assembly":
        if placed > drawn_budget(cap):  # a part placing its objects many times over
            return {**out, "state": "too_large", "triangles": placed, "cap": cap}
        data = merged_part(scene, up, cancelled)
        seconds["build"] = time.perf_counter() - t
        if data is None:
            return {**out, "state": "cancelled" if cancelled() else "no_mesh"}
        if data.n_triangles > cap:
            return {**out, "state": "too_large", "triangles": data.n_triangles, "cap": cap}
        far = _out_of_reach(data.bbox)
        if far is not None:
            return {**out, **far}
        got = {**out, "state": drawn, "data": data, "stored_in": sources[0] if len(sources) == 1 else "mesh"}
        if left_out:
            got["faces_left_out"] = left_out
            got["warnings"] = [{"code": "faces_left_out", "message": left_out["message"]}]
        return got
    buffers, over = model_scene_buffers(scene, nodes, up, cap, cancelled)
    seconds["build"] = time.perf_counter() - t
    if cancelled():
        return {**out, "state": "cancelled"}
    if buffers is not None:
        far = _out_of_reach(buffers.bbox)
        if far is not None:
            return {**out, **far}
    skipped = [
        {"id": None, "name": s.instance, "file": None, "reason": s.reason, "message": s.message}
        for s in scene.skipped
        if hasattr(s, "instance")
    ] + over
    reasons_count: dict[str, int] = {}
    for s in skipped:
        reasons_count[s["reason"]] = reasons_count.get(s["reason"], 0) + 1
    info = {
        "configuration": None,
        "configuration_source": "none",
        "counts": {
            "instances": len(scene.items),
            "triangles_read": sum(o.n_triangles for o in scene.objects),
            "meshes": len(scene.objects),
        },
        "truncated": ["max_drawn"] if over else [],
        "skipped": skipped[:MAX_SKIPPED_LISTED],
        "skipped_count": len(skipped),
        "skipped_reasons": reasons_count,
        "placeholders": {"count": 0, "implausible": 0, "ids": [], "files": [], "names": [], "reasons": []},
        "placed": len(scene.items) - len(over),
        "too_large": False,
        "mesh_warnings": [{"file": None, "code": w.code, "message": w.message} for w in scene.warnings]
        + ([{"file": None, "code": "faces_left_out", "message": left_out["message"]}] if left_out else []),
        "sources": sources,
        "cap": cap,
        "drawn_cap": drawn_budget(cap),
        "model": True,
    }
    if buffers is None:
        return {**out, "state": "no_mesh", "geometry": info, "cap": cap}
    if left_out:
        info["faces_left_out"] = left_out
    buffers.info = info
    return {**out, "state": drawn, "data": buffers, "geometry": info, "cap": cap}


def faces_left_out(scene) -> dict[str, Any] | None:
    """The faces of a scene's bodies that could not be tessellated, or None when there are
    none: ``count``, ``reasons`` (each reason's count, from ``solidseas.tessellate``'s
    ``REASONS``) and ``message``, a sentence for the warning ``faces_left_out``. A face
    left out leaves a hole in what the 3D view draws, so it is never passed over."""
    faces = [s for s in scene.skipped if not hasattr(s, "instance")]
    if not faces:
        return None
    reasons: dict[str, int] = {}
    for s in faces:
        why = str(getattr(s, "reason", "") or "unknown")
        reasons[why] = reasons.get(why, 0) + 1
    said = ", ".join(f"{k} {n}" for k, n in sorted(reasons.items()))
    n = len(faces)
    return {
        "count": n,
        "reasons": reasons,
        "message": f"{n} {'face' if n == 1 else 'faces'} could not be tessellated ({said}): the 3D view "
        "has holes there",
    }
