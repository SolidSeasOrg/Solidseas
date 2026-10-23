"""Display meshes as glTF 2.0 binary (GLB) for a 3D view in a web page: what the
service's ``/v1/mesh`` answers and its reference viewer draws (``docs/API.md`` 3.28,
provisional).

:func:`display_glb` writes what one document shows, from the display data the
document stores itself, and opens no other file and lists no folder:

* **a part**: its display mesh (``Document.mesh()``, what SOLIDWORKS last drew),
  else the triangles of its own Parasolid bodies (:mod:`solidseas.tessellate`), as
  the desktop viewer draws a part;
* **an assembly**: :func:`solidseas.geometry.display_geometry` with the meshes the
  assembly stores for its components and those of the documents stored inside it
  (the ``assembly`` and ``nested`` sources), no root to look in and no file opened.
  An instance whose mesh only its own part file holds is listed among the skipped
  ones, with the box the assembly stores for it, which a viewer can draw in its
  place. Which is why a GLB of an assembly may show fewer parts than the desktop
  viewer, which reads the component files too.

The file holds one glTF mesh per display mesh, shared by every node (instance) that
uses it, in metres with Y up, as SOLIDWORKS stores them and as glTF expects them.
Normals are written when every face of a mesh stores them, else left out, and a
viewer then shades each triangle flat, as glTF says. The scene's ``extras`` hold
``{"solidseas": ...}``: the summary :func:`display_glb` returns and the skipped
instances, each with its placed box. :func:`write_glb` is the writer, for meshes
from anywhere.
"""

import math
import struct
import sys
from array import array
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import __version__, model
from .errors import InvalidArgumentError, NothingToExportError, SldLimitError

GLB_MIME = "model/gltf-binary"
_MAGIC = b"glTF"
_JSON = b"JSON"
_BIN = b"BIN\x00"
_FLOAT = 5126
_UINT16 = 5123
_UINT32 = 5125
_ARRAY_BUFFER = 34962
_ELEMENT_ARRAY_BUFFER = 34963
# Limits of the service's answer: the triangles read, the display data decoded, the
# triangles the placed instances draw together, the instances, the skipped instances
# listed, and the time a part's bodies may take when it stores no display mesh. The
# triangle cap is the desktop viewer's (``solidseas_app.viewer.mesh3d``); at about 42
# bytes a triangle it keeps a GLB near 40 MB.
DEFAULT_MAX_TRIANGLES = 1_000_000
DEFAULT_MAX_BYTES = 256 << 20
DEFAULT_MAX_DRAWN = 20_000_000
DEFAULT_MAX_INSTANCES = 10_000
MAX_SKIPPED_LISTED = 1_000
DEFAULT_BODY_SECONDS = 30.0
# The display-list streams of a part, whose size is read from the container's directory.
_DISPLAY_LISTS = ("contents/displaylists", "contents/displaylists__zlb")
# A colour for each mesh, in turn: glTF's base colour is linear, so these are the
# linear values of a few muted sRGB colours.
PALETTE = (
    (0.42, 0.50, 0.60),
    (0.62, 0.38, 0.22),
    (0.30, 0.52, 0.32),
    (0.55, 0.33, 0.55),
    (0.62, 0.55, 0.25),
    (0.25, 0.48, 0.55),
    (0.58, 0.30, 0.33),
    (0.45, 0.45, 0.42),
)


@dataclass(frozen=True)
class GlbMesh:
    """One mesh: ``positions`` float32 xyz in metres, ``indices`` uint32 triangles,
    ``normals`` float32 xyz of unit length or None, ``color`` linear RGB."""

    name: str
    positions: array
    indices: array
    normals: array | None = None
    color: tuple[float, float, float] = PALETTE[0]
    extras: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class GlbNode:
    """One instance of a mesh: ``matrix`` column-major 4 x 4 (None: where the mesh is)."""

    name: str
    mesh: int
    matrix: Sequence[float] | None = None
    extras: Mapping[str, Any] | None = None


def _finite(values: array) -> bool:
    """Whether every float32 is finite: their sum in doubles is, since float32 values
    cannot add up to infinity in a double, and a NaN or an infinity carries through."""
    return math.isfinite(sum(values))


def _little_endian(a: array) -> bytes:
    if sys.byteorder == "little":
        return a.tobytes()
    b = array(a.typecode, a)
    b.byteswap()
    return b.tobytes()


def write_glb(
    meshes: Sequence[GlbMesh], nodes: Sequence[GlbNode], *, extras: Mapping[str, Any] | None = None
) -> bytes:
    """A GLB of ``meshes`` placed by ``nodes``, all in one scene. Raises
    :class:`~solidseas.errors.InvalidArgumentError` for a mesh whose arrays do not make
    triangles, whose indices pass its vertices or whose positions or normals are not
    finite, and for a node naming no mesh or with a matrix that is not 16 finite
    numbers."""
    blob = bytearray()
    views: list[dict[str, Any]] = []
    accessors: list[dict[str, Any]] = []
    gl_meshes: list[dict[str, Any]] = []
    materials: list[dict[str, Any]] = []

    def view(data: bytes, target: int) -> int:
        while len(blob) % 4:
            blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), "target": target})
        blob.extend(data)
        return len(views) - 1

    for m in meshes:
        bad = InvalidArgumentError(f"mesh {m.name!r} is not one GLB can hold", detail={"parameter": "meshes"})
        p, idx = m.positions, m.indices
        if p.typecode != "f" or idx.typecode != "I" or idx.itemsize != 4:
            raise bad
        if not p or len(p) % 3 or not idx or len(idx) % 3:
            raise bad
        n = len(p) // 3
        if max(idx) >= n or not _finite(p):
            raise bad
        lo = [min(p[k::3]) for k in range(3)]
        hi = [max(p[k::3]) for k in range(3)]
        attributes = {"POSITION": len(accessors)}
        accessors.append(
            {
                "bufferView": view(_little_endian(p), _ARRAY_BUFFER),
                "componentType": _FLOAT,
                "count": n,
                "type": "VEC3",
                "min": lo,
                "max": hi,
            }
        )
        if m.normals is not None:
            if m.normals.typecode != "f" or len(m.normals) != len(p) or not _finite(m.normals):
                raise bad
            attributes["NORMAL"] = len(accessors)
            accessors.append(
                {
                    "bufferView": view(_little_endian(m.normals), _ARRAY_BUFFER),
                    "componentType": _FLOAT,
                    "count": n,
                    "type": "VEC3",
                }
            )
        short = n <= 65536
        packed = array("H", idx) if short else idx
        index_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": view(_little_endian(packed), _ELEMENT_ARRAY_BUFFER),
                "componentType": _UINT16 if short else _UINT32,
                "count": len(idx),
                "type": "SCALAR",
            }
        )
        material = {
            "pbrMetallicRoughness": {
                "baseColorFactor": [*map(float, m.color), 1.0],
                "metallicFactor": 0.0,
                "roughnessFactor": 0.6,
            },
            "doubleSided": True,  # a display mesh is drawn face by face, and is not always closed
        }
        materials.append(material)
        primitive = {"attributes": attributes, "indices": index_accessor, "material": len(materials) - 1}
        entry: dict[str, Any] = {"name": m.name, "primitives": [primitive]}
        if m.extras:
            entry["extras"] = dict(m.extras)
        gl_meshes.append(entry)

    gl_nodes = []
    for node in nodes:
        if not 0 <= node.mesh < len(gl_meshes):
            raise InvalidArgumentError(f"node {node.name!r} names no mesh", detail={"parameter": "nodes"})
        entry = {"name": node.name, "mesh": node.mesh}
        if node.matrix is not None:
            matrix = [float(v) for v in node.matrix]
            if len(matrix) != 16 or not all(math.isfinite(v) for v in matrix):
                raise InvalidArgumentError(
                    f"node {node.name!r} has no usable matrix", detail={"parameter": "nodes"}
                )
            entry["matrix"] = matrix
        if node.extras:
            entry["extras"] = dict(node.extras)
        gl_nodes.append(entry)

    document: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": f"SolidSeas {__version__}"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(gl_nodes)))}],
    }
    if extras:
        document["scenes"][0]["extras"] = dict(extras)
    if gl_nodes:
        document["nodes"] = gl_nodes
    if gl_meshes:
        document.update(meshes=gl_meshes, materials=materials, accessors=accessors, bufferViews=views)
        while len(blob) % 4:
            blob.append(0)
        document["buffers"] = [{"byteLength": len(blob)}]
    text = model.dumps(document).encode("ascii")
    text += b" " * (-len(text) % 4)
    chunks = struct.pack("<I4s", len(text), _JSON) + text
    if blob:
        chunks += struct.pack("<I4s", len(blob), _BIN) + bytes(blob)
    total = 12 + len(chunks)
    if total > 0xFFFFFFFF:
        raise InvalidArgumentError("the meshes are too large for one GLB", detail={"parameter": "meshes"})
    return struct.pack("<4sII", _MAGIC, 2, total) + chunks


def is_glb(data: bytes) -> bool:
    """Whether ``data`` has a GLB's frame: the header with version 2 and the true length,
    a JSON chunk, and at most one binary chunk after it, every chunk 4-byte aligned.
    Nothing inside the chunks is read."""
    if len(data) < 20 or data[:4] != _MAGIC:
        return False
    version, length = struct.unpack_from("<II", data, 4)
    if version != 2 or length != len(data):
        return False
    kinds = []
    offset = 12
    while offset < len(data):
        if offset + 8 > len(data):
            return False
        size, kind = struct.unpack_from("<I4s", data, offset)
        if size % 4 or offset + 8 + size > len(data):
            return False
        kinds.append(kind)
        offset += 8 + size
    return kinds in ([_JSON], [_JSON, _BIN])


# --------------------------------------------------------------------------- a document's display data
def _too_large(what: str, limit: int, value: int | None = None) -> SldLimitError:
    detail: dict[str, Any] = {"limit": limit}
    if value is not None:
        detail["value"] = value
    return SldLimitError(f"the {what} is past the limit of {limit}", detail=detail)


def _normals(mesh) -> array | None:
    """The mesh's normals when every face stores them and every one is finite, else None."""
    if len(mesh.normals) != len(mesh.positions) or not all(f.has_normals for f in mesh.faces):
        return None
    return mesh.normals if _finite(mesh.normals) else None


def _part(doc, configuration: str | None, max_triangles: int, max_bytes: int, body_seconds: float):
    active = doc.active_configuration
    mesh, source = None, None
    if configuration is None or configuration == active:
        sizes = [s.size for s in doc.streams() if s.name.lower() in _DISPLAY_LISTS]
        if sizes and max(sizes) > max_bytes:
            raise _too_large("display data", max_bytes, max(sizes))
        mesh, source = doc.mesh(), "display_mesh"
    if mesh is None or mesh.n_triangles == 0:
        # No display mesh of that configuration: the triangles of the part's own bodies.
        tess = doc.tessellate(configuration, max_triangles=max_triangles + 1, max_seconds=body_seconds)
        if tess is not None and "max_triangles" in tess.truncated:
            raise _too_large("number of triangles", max_triangles)
        if tess is not None and tess.mesh.n_triangles:
            mesh, source = tess.mesh, "bodies"
            configuration = tess.configuration or configuration
    if mesh is None or mesh.n_triangles == 0:
        raise NothingToExportError(
            "the part stores no display mesh and no bodies to draw", detail={"rule": "no_mesh"}
        )
    if mesh.n_triangles > max_triangles:
        raise _too_large("number of triangles", max_triangles, mesh.n_triangles)
    name = (doc.name or "part").rsplit(".", 1)[0]
    meshes = [GlbMesh(name, mesh.positions, mesh.triangles, _normals(mesh), PALETTE[0])]
    nodes = [GlbNode(name, 0)]
    summary = {
        "doc_type": "part",
        "configuration": configuration if configuration is not None else active,
        "source": source,
        "meshes": 1,
        "instances": 1,
        "skipped": 0,
        "triangles": mesh.n_triangles,
        "triangles_drawn": mesh.n_triangles,
        "truncated": [],
    }
    return meshes, nodes, summary, []


def _assembly(
    doc, configuration: str | None, max_triangles: int, max_bytes: int, max_drawn: int, max_instances: int
):
    from .geometry import display_geometry
    from .roots import Roots

    g = display_geometry(
        doc,
        configuration,
        roots=Roots([]),  # no root: no folder is listed and no component file looked for
        allow_outside_roots=False,
        sources=("assembly", "nested"),
        max_instances=max_instances,
        max_files=0,  # and none opened, whatever a resolution said
        max_triangles=max_triangles,
        max_bytes=max_bytes,
        max_triangles_drawn=max_drawn,
    )
    first: dict[str, int] = {}
    for i, inst in enumerate(g.instances):  # meshes in the order their first instance comes
        first.setdefault(inst.mesh, i)
    keys = sorted(g.meshes, key=lambda k: first.get(k, len(g.instances)))
    index = {k: i for i, k in enumerate(keys)}
    meshes = []
    for i, key in enumerate(keys):
        source = g.meshes[key]
        m = source.mesh
        meshes.append(
            GlbMesh(
                f"mesh-{i + 1}",
                m.positions,
                m.triangles,
                _normals(m),
                PALETTE[i % len(PALETTE)],
                {"file": source.file, "source": source.kind, "configuration": source.configuration},
            )
        )
    nodes = []
    skipped = []
    for inst in g.instances:
        matrix = inst.matrix()
        if not all(math.isfinite(v) for v in matrix):
            skipped.append((inst.id, inst.name, inst.file, "no_placement", None))
            continue
        extras = {"id": inst.id, "file": inst.file, "configuration": inst.configuration}
        nodes.append(GlbNode(inst.name, index[inst.mesh], matrix, extras))
    listed = []
    for s in g.skipped:
        box = g.placeholder(s)
        if box is not None and not all(math.isfinite(v) for corner in box for v in corner):
            box = None
        listed.append(
            {
                "id": s.id,
                "name": s.name,
                "file": s.file,
                "reason": s.reason,
                "message": s.message,
                "box": [list(box[0]), list(box[1])] if box is not None else None,
            }
        )
    for ident, name, file_key, reason, box in skipped:
        listed.append(
            {"id": ident, "name": name, "file": file_key, "reason": reason, "message": None, "box": box}
        )
    if not nodes and not listed:
        raise NothingToExportError(
            "the assembly shows no part in that configuration", detail={"rule": "no_instances"}
        )
    summary = {
        "doc_type": "assembly",
        "configuration": g.configuration,
        "source": "display_data",
        "meshes": len(meshes),
        "instances": len(nodes),
        "skipped": len(listed),
        "triangles": int(g.counts.get("triangles_read", 0)),
        "triangles_drawn": sum(len(meshes[n.mesh].indices) // 3 for n in nodes),
        "truncated": list(g.truncated),
    }
    return meshes, nodes, summary, listed


def display_glb(
    doc,
    configuration: str | None = None,
    *,
    max_triangles: int = DEFAULT_MAX_TRIANGLES,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_triangles_drawn: int = DEFAULT_MAX_DRAWN,
    max_instances: int = DEFAULT_MAX_INSTANCES,
    body_seconds: float = DEFAULT_BODY_SECONDS,
) -> tuple[dict[str, Any], bytes]:
    """The GLB of what an open document shows, and its summary (provisional, see the
    module notes): ``doc_type``, ``configuration``, ``source`` (``display_mesh`` or
    ``bodies`` for a part, ``display_data`` for an assembly), ``meshes``,
    ``instances``, ``skipped``, ``triangles`` (read, each mesh once),
    ``triangles_drawn`` (by the instances) and ``truncated`` (the limits that left
    instances out). ``configuration`` is chosen as ``components()`` chooses it for an
    assembly; for a part, one other than the active configuration is drawn from its
    bodies, since the display mesh shows the active one.

    Raises :class:`~solidseas.errors.NothingToExportError` for a drawing, a part with
    neither a display mesh nor bodies, and an assembly that shows no part;
    :class:`~solidseas.errors.SldLimitError` (``limit_exceeded``) for a part past
    ``max_triangles`` or ``max_bytes``. An assembly's instances past a limit are
    skipped, with the limit as their reason."""
    for value, name in (
        (max_triangles, "max_triangles"),
        (max_bytes, "max_bytes"),
        (max_triangles_drawn, "max_triangles_drawn"),
        (max_instances, "max_instances"),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise InvalidArgumentError(f"{name} must be a positive integer", detail={"parameter": name})
    if isinstance(body_seconds, bool) or not isinstance(body_seconds, (int, float)) or not body_seconds > 0:
        raise InvalidArgumentError("body_seconds must be positive", detail={"parameter": "body_seconds"})
    if doc.doc_type == "part":
        meshes, nodes, summary, skipped = _part(doc, configuration, max_triangles, max_bytes, body_seconds)
    elif doc.doc_type == "assembly":
        meshes, nodes, summary, skipped = _assembly(
            doc, configuration, max_triangles, max_bytes, max_triangles_drawn, max_instances
        )
    else:
        raise NothingToExportError("a drawing holds no 3D model to draw", detail={"rule": "drawing"})
    extras = {
        "solidseas": {
            **summary,
            "units": "m",
            "skipped_listed": skipped[:MAX_SKIPPED_LISTED],
        }
    }
    data = write_glb(meshes, nodes, extras=extras)
    return {**summary, "bytes": len(data)}, data


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_DRAWN",
    "DEFAULT_MAX_INSTANCES",
    "DEFAULT_MAX_TRIANGLES",
    "GLB_MIME",
    "PALETTE",
    "GlbMesh",
    "GlbNode",
    "display_glb",
    "is_glb",
    "write_glb",
]
