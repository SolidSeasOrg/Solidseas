"""glTF 2.0, as JSON (``.gltf``) or binary (``.glb``) (provisional, ``docs/formats/mesh.md``).

A glTF asset is JSON: ``buffers`` of bytes, ``bufferViews`` (ranges of a buffer,
with a stride), ``accessors`` (typed arrays in a view: component type, element
type, count, normalisation, sparse substitutions), ``meshes`` of
``primitives`` (vertex attributes such as ``POSITION`` and ``NORMAL``,
``indices``, a drawing ``mode`` and a ``material``), ``nodes`` (a ``matrix``
or a translation, rotation and scale, children and a mesh) and ``scenes``
listing root nodes. A GLB is a 12-byte header (``glTF``, version 2, length), a
JSON chunk and an optional binary chunk, which is buffer 0.

SolidSeas reads:

* buffers from the GLB chunk, from ``data:`` URIs (base64, at most
  ``gltf_data_uri_bytes`` decoded) and from relative URIs naming a file inside
  the document's own folder (:func:`~solidseas.formats._source.read_sibling`:
  no scheme, drive, UNC, ``..`` or alternate stream, no link); images never;
* every accessor component type, ``normalized``, ``byteStride`` and sparse
  accessors, every range checked in Python integers against its view and
  buffer before anything is read, and every count against what the scene may
  still take. An accessor without a buffer view is zeros, its sparse values
  substituted: a primitive whose positions or indices are such an accessor
  without a sparse block has nothing to draw and is left out
  (``primitives_skipped``), and a zero-filled accessor may hold at most
  ``limits.zip_ratio`` times the bytes its sparse block was read from (past
  1 MiB), the bound a zip member's inflation keeps, so its size follows the
  file's: the block is read and checked before any zero is made. A strided view
  is copied a byte column at a time, never an object an element;
* triangles (mode 4), triangle strips (5) and fans (6); points and lines are
  left out (``primitives_skipped``);
* one scene object a primitive (its material's ``baseColorFactor`` as its
  colour, normals when given), placed once for each node that shows its mesh,
  with the node's ``matrix`` or translation, rotation and scale composed down
  the scene's hierarchy (the default scene, else the first; depth
  ``limits.depth``; a cycle or a node with two parents is refused);
* ``KHR_mesh_quantization``. A primitive held only in Draco
  (``KHR_draco_mesh_compression``) or meshopt (``EXT_meshopt_compression``)
  form is left out (``compression_not_supported``), and an asset that requires
  either is refused (``format_not_supported``, rule ``compression``); another
  required extension that changes geometry or that SolidSeas does not know
  refuses the asset too (rule ``required_extension``).

glTF is in metres with Y up: the reader turns the scene to Z up at its root
(+90 degrees about X), so its Home view matches a print mesh's. The asset's
generator is its ``application``; its copyright and simple ``extras`` values
are properties. An asset that places several meshes is an assembly, its tree the
node hierarchy; one placed mesh is a part. A scene's ``max_triangles`` keeps the
primitives finished before it was passed, placed by every node that shows them.
"""

import base64
import math
import struct
import sys
from array import array
from typing import Any
from urllib.parse import unquote_to_bytes

from ..errors import FormatNotSupportedError, SldFormatError
from ..formats.solidworks.components import IDENTITY, Placement
from ._source import Clock, SiblingBudget, clip_text, load_json, read_sibling, sibling_resolution
from .base import ExternalReference, ModelDocument, ModelNode, SceneBuilder, _stem, _Truncated, make_property
from .obj import split_application, unit_color

REVISION = 1
_GLB_MAGIC = b"glTF"
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942
# component type: (struct code, bytes, the divisor of a normalised value)
_COMPONENTS = {
    5120: ("b", 1, 127.0),
    5121: ("B", 1, 255.0),
    5122: ("h", 2, 32767.0),
    5123: ("H", 2, 65535.0),
    5125: ("I", 4, None),
    5126: ("f", 4, None),
}
_TYPES = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
_DRACO = "KHR_draco_mesh_compression"
_MESHOPT = ("EXT_meshopt_compression", "KHR_meshopt_compression")
_GEOMETRY_EXTENSIONS = ("EXT_mesh_gpu_instancing",)
# Required extensions that leave geometry as the core reads it.
_HARMLESS = frozenset(
    {
        "KHR_mesh_quantization",
        "KHR_texture_transform",
        "KHR_texture_basisu",
        "EXT_texture_webp",
        "EXT_texture_avif",
        "KHR_lights_punctual",
        "KHR_xmp_json_ld",
        "KHR_animation_pointer",
    }
)
# +90 degrees about X: glTF's Y up becomes Z up
Z_UP = Placement(((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)), (0.0, 0.0, 0.0))
_ARRAYS = ("accessors", "bufferViews", "meshes", "nodes", "materials", "scenes", "images", "textures")
_ZERO_FLOOR = 1 << 20  # a zero-filled accessor may always hold this many bytes
_BATCH = 4096  # values converted, or strip and fan corners turned, between ticks of the clock


def _int(value: Any, what: str, low: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < low:
        raise SldFormatError(f"{what} is not a whole number of {low} or more")
    return value


def _numbers(value: Any, n: int, what: str) -> list[float]:
    if (
        not isinstance(value, list)
        or len(value) != n
        or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value)
    ):
        raise SldFormatError(f"{what} is not {n} finite numbers")
    return [float(v) for v in value]


def _local_placement(node: dict) -> Placement:
    """A node's placement in its parent's frame: its matrix, else T R S."""
    if "matrix" in node:
        m = _numbers(node["matrix"], 16, "a node's matrix")
        rot = tuple(tuple(m[j * 4 + i] for j in range(3)) for i in range(3))
        return Placement(rot, (m[12], m[13], m[14]))  # type: ignore[arg-type]
    t = _numbers(node.get("translation", [0.0, 0.0, 0.0]), 3, "a node's translation")
    q = _numbers(node.get("rotation", [0.0, 0.0, 0.0, 1.0]), 4, "a node's rotation")
    s = _numbers(node.get("scale", [1.0, 1.0, 1.0]), 3, "a node's scale")
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w)
    if n > 0.0:
        x, y, z, w = x / n, y / n, z / n, w / n
    else:
        x, y, z, w = 0.0, 0.0, 0.0, 1.0
    r = (
        (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
        (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
        (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
    )
    rot = tuple(tuple(r[i][j] * s[j] for j in range(3)) for i in range(3))
    return Placement(rot, (t[0], t[1], t[2]))  # type: ignore[arg-type]


class GltfDocument(ModelDocument):
    """One glTF asset (see the module notes)."""

    format = "gltf"

    def __init__(self, source, *, name, path, file_info, limits, detection=None) -> None:
        super().__init__(
            source, name=name, path=path, file_info=file_info, limits=limits, detection=detection
        )
        self.kind = "mesh"
        self._bin: tuple[int, int] | None = None  # the GLB binary chunk: offset, length
        self._buffers: dict[int, bytes] = {}
        self._budget = SiblingBudget.of(source, limits)
        if source.head(4) == _GLB_MAGIC:
            self.variant = "glb"
            data = self._glb(Clock(limits.seconds))
        else:
            self.variant = "gltf"
            data = source.read_all(limits.json_bytes, "json_bytes")
        self.json = load_json(data, limits)
        self._check()
        self.set_units("m", "format")
        self._head()

    # -- the container ----------------------------------------------------------------------
    def _glb(self, clock: Clock) -> bytes:
        src = self.source
        lim = self.limits
        if src.size < 20:
            raise SldFormatError("the GLB is shorter than its header")
        _magic, version, length = struct.unpack("<4sII", src.read_at(0, 12))
        if version != 2:
            raise SldFormatError(f"GLB version {version} is not read (glTF 2.0 only)")
        if length > src.size or length < 20:
            raise SldFormatError("the GLB's length is not the file's")
        pos = 12
        json_data = None
        while pos + 8 <= length:
            clock.tick()  # a file of empty chunks keeps the time bound
            clen, ctype = struct.unpack("<II", src.read_at(pos, 8))
            if pos + 8 + clen > length:
                raise SldFormatError("a GLB chunk runs past the end of the file")
            if json_data is None:
                if ctype != _JSON_CHUNK:
                    raise SldFormatError("the GLB's first chunk is not JSON")
                if clen > lim.json_bytes:
                    raise lim.exceeded("json_bytes", f"the GLB's JSON is {clen:,} bytes", clen)
                json_data = src.read_at(pos + 8, clen)
            elif ctype == _BIN_CHUNK and self._bin is None:
                self._bin = (pos + 8, clen)
            pos += 8 + clen + (-clen % 4 if pos + 8 + clen + (-clen % 4) <= length else 0)
        if json_data is None:
            raise SldFormatError("the GLB has no JSON chunk")
        return json_data.rstrip(b" \0")

    def _check(self) -> None:
        j = self.json
        lim = self.limits
        if not isinstance(j, dict) or not isinstance(j.get("asset"), dict):
            raise SldFormatError("not a glTF asset: no asset object")
        version = j["asset"].get("version")
        if not isinstance(version, str) or not version.startswith("2."):
            raise SldFormatError(f"glTF version {str(version)[:12]!r} is not read (glTF 2.0 only)")
        for key in _ARRAYS:
            v = j.get(key, [])
            if not isinstance(v, list) or not all(isinstance(x, dict) for x in v):
                raise SldFormatError(f"the asset's {key} is not a list of objects")
            if len(v) > lim.gltf_array_items:
                raise lim.exceeded(
                    "gltf_array_items", f"the asset has more than {lim.gltf_array_items:,} {key}"
                )
        buffers = j.get("buffers", [])
        if not isinstance(buffers, list) or not all(isinstance(x, dict) for x in buffers):
            raise SldFormatError("the asset's buffers is not a list of objects")
        if len(buffers) > lim.gltf_buffers:
            raise lim.exceeded("gltf_buffers", f"the asset has more than {lim.gltf_buffers:,} buffers")
        required = j.get("extensionsRequired", [])
        if not isinstance(required, list):
            raise SldFormatError("extensionsRequired is not a list")
        for ext in required:
            if not isinstance(ext, str):
                raise SldFormatError("extensionsRequired names something that is not a string")
            if ext == _DRACO or ext in _MESHOPT:
                raise FormatNotSupportedError(
                    f"the asset requires {ext}, a mesh compression SolidSeas does not read",
                    detail={"rule": "compression", "value": ext},
                )
            if ext not in _HARMLESS and not ext.startswith("KHR_materials_"):
                raise FormatNotSupportedError(
                    f"the asset requires the extension {ext}, which SolidSeas does not read",
                    detail={"rule": "required_extension", "value": ext[:100]},
                )
        primitives = sum(len(m.get("primitives", []) or []) for m in j.get("meshes", []))
        if primitives > lim.gltf_array_items:
            raise lim.exceeded(
                "gltf_array_items", f"the asset has more than {lim.gltf_array_items:,} primitives"
            )

    def _get(self, key: str, index: Any) -> dict:
        items = self.json.get(key, [])
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(items):
            raise SldFormatError(f"a reference to {key} {str(index)[:12]} names none the asset has")
        return items[index]

    # -- the head: structure from the JSON alone ---------------------------------------------
    def _head(self) -> None:
        j = self.json
        lim = self.limits
        asset = j["asset"]
        props = []
        for key in ("generator", "copyright", "version", "minVersion"):
            v = asset.get(key)
            if isinstance(v, str) and v:
                props.append(make_property(key, clip_text(v, lim, self.warnings, f"the asset's {key}")))
        extras = asset.get("extras")
        fields: dict[str, Any] = {}
        if isinstance(extras, dict):
            for k, v in list(extras.items())[: lim.properties]:
                if isinstance(v, (str, int, float)) and not isinstance(v, bool) and isinstance(k, str):
                    text = clip_text(str(v), lim, self.warnings, "an extras value")
                    props.append(make_property(clip_text(k, lim, self.warnings, "an extras name"), text))
                    if k.lower() in ("title", "author") and isinstance(v, str) and v:
                        fields[k.lower()] = text
        self.properties = props
        if fields:
            from dataclasses import replace

            self.fields = replace(self.fields, **fields)
        self.application = split_application(
            asset.get("generator") if isinstance(asset.get("generator"), str) else None
        )
        self._objects, self._mesh_objects = self._primitives()
        self._nodes, self._instances = self._hierarchy()
        self.doc_type = "assembly" if len(self._instances) > 1 else "part"
        used = j.get("extensionsUsed", [])
        if isinstance(used, list):
            ignored = [e for e in used if e in _GEOMETRY_EXTENSIONS]
            if ignored:
                self.warn("extension_ignored", f"the asset uses {', '.join(ignored)}, which is not read")
        if any(
            isinstance(m.get("pbrMetallicRoughness"), dict)
            and "baseColorTexture" in m["pbrMetallicRoughness"]
            for m in j.get("materials", [])
        ):
            self.warn("textures_ignored", "textures are not read; materials are drawn in their base colour")

    def _primitives(self) -> tuple[list[tuple[int, int]], list[list[int]]]:
        """The scene objects: one a drawable primitive, in mesh order."""
        objects: list[tuple[int, int]] = []
        per_mesh: list[list[int]] = []
        skipped = compressed = empty = 0
        for mi, mesh in enumerate(self.json.get("meshes", [])):
            prims = mesh.get("primitives", [])
            if not isinstance(prims, list):
                raise SldFormatError("a mesh's primitives is not a list")
            mine = []
            for pi, prim in enumerate(prims):
                if not isinstance(prim, dict) or not isinstance(prim.get("attributes"), dict):
                    raise SldFormatError("a primitive has no attributes")
                mode = prim.get("mode", 4)
                if mode not in (4, 5, 6) or "POSITION" not in prim["attributes"]:
                    skipped += 1
                    continue
                if self._compressed_only(prim):
                    compressed += 1
                    continue
                if self._all_zeros(prim["attributes"]["POSITION"]) or (
                    "indices" in prim and self._all_zeros(prim["indices"])
                ):
                    empty += 1
                    continue
                mine.append(len(objects))
                objects.append((mi, pi))
            per_mesh.append(mine)
        if skipped:
            self.warn(
                "primitives_skipped",
                f"{skipped} primitives are points or lines, or have no positions; left out",
            )
        if compressed:
            self.warn(
                "compression_not_supported",
                f"{compressed} primitives are held only in a compression SolidSeas does not read; left out",
            )
        if empty:
            self.warn(
                "primitives_skipped",
                f"{empty} primitives have positions or indices without data (all zeros), so nothing to "
                "draw; left out",
            )
        return objects, per_mesh

    def _all_zeros(self, index: Any) -> bool:
        """Whether an accessor has neither a buffer view nor a sparse block: zeros only."""
        acc = self._get("accessors", index)
        return "bufferView" not in acc and not isinstance(acc.get("sparse"), dict)

    def _compressed_only(self, prim: dict) -> bool:
        ext = prim.get("extensions")
        acc = self._get("accessors", prim["attributes"]["POSITION"])
        if isinstance(ext, dict) and _DRACO in ext and "bufferView" not in acc:
            return True
        views = [acc.get("bufferView")]
        if "indices" in prim:
            views.append(self._get("accessors", prim["indices"]).get("bufferView"))
        for v in views:
            if v is None:
                continue
            view = self._get("bufferViews", v)
            vext = view.get("extensions")
            if isinstance(vext, dict) and any(k in vext for k in _MESHOPT):
                buf = self._get("buffers", view.get("buffer"))
                bext = buf.get("extensions")
                if "uri" not in buf and (self.variant != "glb" or view.get("buffer") != 0):
                    return True
                if isinstance(bext, dict) and any(
                    isinstance(bext.get(k), dict) and bext[k].get("fallback") for k in _MESHOPT
                ):
                    return True
        return False

    def _hierarchy(self):
        """The nodes shown, parents first: ``(nodes, instances)``; nodes are ``(index,
        parent index or None, local placement)`` and instances ``(node index, world
        placement)`` for each node with a mesh."""
        j = self.json
        nodes = j.get("nodes", [])
        lim = self.limits
        parent: dict[int, int] = {}
        for i, nd in enumerate(nodes):
            kids = nd.get("children", [])
            if not isinstance(kids, list):
                raise SldFormatError("a node's children is not a list")
            for c in kids:
                c = _int(c, "a node's child")
                if c >= len(nodes):
                    raise SldFormatError("a node's child names a node the asset does not have")
                if c in parent or c == i:
                    raise SldFormatError("a node is the child of two nodes, or of itself")
                parent[c] = i
        scenes = j.get("scenes", [])
        if scenes:
            index = j.get("scene", 0)
            roots = self._get("scenes", index).get("nodes", [])
            if not isinstance(roots, list):
                raise SldFormatError("a scene's nodes is not a list")
            roots = [_int(r, "a scene's node") for r in roots]
        else:
            roots = [i for i in range(len(nodes)) if i not in parent]
        for r in roots:
            if r >= len(nodes) or r in parent:
                raise SldFormatError("a scene's root node is missing, or is another node's child")
        if len(set(roots)) != len(roots):
            raise SldFormatError("a scene names one root node twice")
        shown: list[tuple[int, int | None, Placement]] = []
        instances: list[tuple[int, Placement]] = []
        stack = [(r, None, Z_UP, 1) for r in reversed(roots)]
        seen: set[int] = set()
        while stack:
            i, up, world_up, depth = stack.pop()
            if i in seen:
                raise SldFormatError("the node hierarchy has a cycle")
            seen.add(i)
            if depth > lim.depth:
                raise lim.exceeded("depth", f"the node hierarchy is deeper than {lim.depth}")
            nd = nodes[i]
            local = _local_placement(nd)
            world = world_up.then(local)
            shown.append((i, up, local if up is not None else Z_UP.then(local)))
            if "mesh" in nd:
                mesh = _int(nd["mesh"], "a node's mesh")
                if mesh >= len(self._mesh_objects):
                    raise SldFormatError("a node names a mesh the asset does not have")
                instances.append((i, world))
                if len(instances) > lim.items:
                    raise lim.exceeded("items", f"the asset places more than {lim.items:,} meshes")
            for c in reversed(nd.get("children", [])):
                stack.append((c, i, world, depth + 1))
        if not nodes and not scenes:  # meshes and nothing to place them: each once, where it stands
            for m in range(len(self._mesh_objects)):
                instances.append((-1 - m, Z_UP))
        return shown, instances

    def _mesh_of(self, node_index: int) -> int:
        if node_index < 0:
            return -1 - node_index
        return self.json["nodes"][node_index]["mesh"]

    def _counts(self):
        tris = verts = 0
        per_object = []
        for mi, pi in self._objects:
            prim = self.json["meshes"][mi]["primitives"][pi]
            n_pos = _int(self._get("accessors", prim["attributes"]["POSITION"]).get("count"), "a count")
            n = n_pos
            if "indices" in prim:
                n = _int(self._get("accessors", prim["indices"]).get("count"), "a count")
            mode = prim.get("mode", 4)
            per_object.append(n // 3 if mode == 4 else max(0, n - 2))
            verts += n_pos
        placed = 0
        items = 0
        for node, _w in self._instances:
            for o in self._mesh_objects[self._mesh_of(node)]:
                tris += per_object[o]
                placed += 1
        items = placed
        return {"objects": len(self._objects), "items": items, "triangles": tris, "vertices": verts}

    # -- buffers and accessors ----------------------------------------------------------------
    def _buffer(self, index: Any) -> bytes:
        index = _int(index, "a buffer view's buffer")
        hit = self._buffers.get(index)
        if hit is not None:
            return hit
        buf = self._get("buffers", index)
        lim = self.limits
        length = _int(buf.get("byteLength"), "a buffer's byteLength", 1)
        uri = buf.get("uri")
        if uri is None:
            if self.variant != "glb" or index != 0 or self._bin is None:
                raise SldFormatError(f"buffer {index} has no data")
            offset, size = self._bin
            if length > size:
                raise SldFormatError("buffer 0 is longer than the GLB's binary chunk")
            data = self.source.read_at(offset, length)
        elif not isinstance(uri, str):
            raise SldFormatError("a buffer's uri is not text")
        elif uri.startswith("data:"):
            data = _data_uri(uri, lim)
        else:
            try:
                data = read_sibling(self.path, uri, self._budget)
            except FileNotFoundError:
                raise SldFormatError(f"buffer {index}'s file is missing") from None
        if len(data) < length:
            raise SldFormatError(f"buffer {index} holds fewer bytes than its byteLength says")
        data = data[:length]
        self._buffers[index] = data
        return data

    def _accessor(
        self,
        index: Any,
        types: tuple[str, ...],
        what: str,
        budget: tuple[int, str] | None = None,
        clock: Clock | None = None,
    ) -> tuple[array, int]:
        """An accessor's values as a flat array (floats for normalised integers), and the
        components an element. ``budget`` is ``(elements, limit name)``: the most it may
        hold, checked before anything is allocated; ``clock`` is ticked as normalised
        values are converted."""
        acc = self._get("accessors", index)
        ctype = acc.get("componentType")
        if ctype not in _COMPONENTS:
            raise SldFormatError(f"{what}: component type {str(ctype)[:12]} is not a glTF one")
        etype = acc.get("type")
        if etype not in types:
            raise SldFormatError(f"{what}: element type {str(etype)[:12]} is not {' or '.join(types)}")
        code, size, scale = _COMPONENTS[ctype]
        ncomp = _TYPES[etype]
        count = _int(acc.get("count"), f"{what}'s count")
        elem = size * ncomp
        if count * ncomp > 3 * self.limits.vertices:
            raise self.limits.exceeded("vertices", f"{what} holds more values than a model may")
        if budget is not None and count > budget[0]:
            raise self.limits.exceeded(budget[1], f"{what} holds more elements than the model may still take")
        sparse = acc.get("sparse")
        block = self._sparse(sparse, code, size, ncomp, count, what) if isinstance(sparse, dict) else None
        if "bufferView" in acc:
            view = self._get("bufferViews", acc["bufferView"])
            data = self._buffer(view.get("buffer"))
            v_off = _int(view.get("byteOffset", 0), "a view's byteOffset")
            v_len = _int(view.get("byteLength"), "a view's byteLength", 1)
            if v_off + v_len > len(data):
                raise SldFormatError(f"{what}: a buffer view runs past the end of its buffer")
            stride = view.get("byteStride")
            stride = elem if stride is None else _int(stride, "a view's byteStride", 1)
            a_off = _int(acc.get("byteOffset", 0), f"{what}'s byteOffset")
            if count and a_off + stride * (count - 1) + elem > v_len:
                raise SldFormatError(f"{what}: the accessor runs past the end of its buffer view")
            start = v_off + a_off
            if stride == elem or not count:
                raw = data[start : start + count * elem]
            else:  # one column of bytes at a time, never an object an element
                raw = bytearray(count * elem)
                span = stride * (count - 1) + 1
                for k in range(elem):
                    raw[k::elem] = data[start + k : start + k + span : stride]
            values = array(code)
            values.frombytes(raw)
            if sys.byteorder == "big" and size > 1:
                values.byteswap()
        else:
            # zeros, which only the sparse block sets: at most zip_ratio times the bytes that
            # block was read from (past 1 MiB), checked before the zeros are made
            lim = self.limits
            held = 0 if block is None else len(block[0]) * block[0].itemsize + len(block[1]) * size
            if count * elem > max(_ZERO_FLOOR, lim.zip_ratio * held):
                raise lim.exceeded(
                    "zip_ratio", f"{what} has no buffer view and is far larger than its sparse values"
                )
            values = array(code, bytes(elem)) * count
        if block is not None:
            positions, rep = block
            for k, p in enumerate(positions):
                values[p * ncomp : (p + 1) * ncomp] = rep[k * ncomp : (k + 1) * ncomp]
        if scale is not None and acc.get("normalized"):
            fl = array("f")
            for i in range(0, len(values), _BATCH):
                fl.extend(max(v / scale, -1.0) for v in values[i : i + _BATCH])
                if clock is not None:
                    clock.tick(_BATCH)
            return fl, ncomp
        return values, ncomp

    def _sparse(
        self, sparse: dict, code: str, size: int, ncomp: int, count: int, what: str
    ) -> tuple[array, array]:
        """A sparse block's element indices and values, read from their views and checked
        (every index inside the accessor) before anything the accessor holds is made."""
        n = _int(sparse.get("count"), f"{what}'s sparse count", 1)
        if n > count:
            raise SldFormatError(f"{what}: more sparse values than elements")
        idx = sparse.get("indices")
        val = sparse.get("values")
        if not isinstance(idx, dict) or not isinstance(val, dict):
            raise SldFormatError(f"{what}: a sparse accessor lacks its indices or values")
        icode = {5121: ("B", 1), 5123: ("H", 2), 5125: ("I", 4)}.get(idx.get("componentType"))
        if icode is None:
            raise SldFormatError(f"{what}: sparse indices of an unknown type")
        ind = self._view_bytes(idx, n * icode[1], what)
        positions = array(icode[0])
        positions.frombytes(ind)
        rep = array(code)
        rep.frombytes(self._view_bytes(val, n * size * ncomp, what))
        if sys.byteorder == "big":
            positions.byteswap()
            if size > 1:
                rep.byteswap()
        if n and max(positions) >= count:
            raise SldFormatError(f"{what}: a sparse index is past the accessor's end")
        return positions, rep

    def _view_bytes(self, ref: dict, n: int, what: str) -> bytes:
        view = self._get("bufferViews", ref.get("bufferView"))
        data = self._buffer(view.get("buffer"))
        v_off = _int(view.get("byteOffset", 0), "a view's byteOffset")
        v_len = _int(view.get("byteLength"), "a view's byteLength", 1)
        off = _int(ref.get("byteOffset", 0), "a sparse byteOffset")
        if v_off + v_len > len(data) or off + n > v_len:
            raise SldFormatError(f"{what}: sparse data runs past the end of its buffer view")
        return data[v_off + off : v_off + off + n]

    # -- hooks ---------------------------------------------------------------------------
    def _object_name(self, mi: int, pi: int) -> str | None:
        mesh = self.json["meshes"][mi]
        name = mesh.get("name") if isinstance(mesh.get("name"), str) else None
        n = len(mesh.get("primitives", []))
        label = clip_text(name, self.limits, None) if name else f"mesh {mi}"
        return label if n == 1 else f"{label} ({pi + 1})"

    def _color(self, prim: dict):
        if "material" not in prim:
            return None
        mat = self._get("materials", prim["material"])
        pbr = mat.get("pbrMetallicRoughness")
        factor = pbr.get("baseColorFactor") if isinstance(pbr, dict) else None
        if factor is None:
            ext = mat.get("extensions")
            sg = ext.get("KHR_materials_pbrSpecularGlossiness") if isinstance(ext, dict) else None
            factor = sg.get("diffuseFactor") if isinstance(sg, dict) else None
        if factor is None:
            return None
        try:
            return unit_color(*_numbers(factor, 4, "a material's colour"))
        except SldFormatError:
            return None

    def _tree(self, clock: Clock):
        assembly = self.doc_type == "assembly"
        out: list[ModelNode] = []
        if assembly:
            out.append(ModelNode("0", None, self.fields.title or _stem(self.name), "assembly"))
        nodes = self.json.get("nodes", [])
        for i, up, local in self._nodes:
            nd = nodes[i]
            mesh = nd.get("mesh")
            objs = self._mesh_objects[mesh] if mesh is not None else []
            name = nd.get("name") if isinstance(nd.get("name"), str) else None
            if not name and mesh is not None:
                mname = self.json["meshes"][mesh].get("name")
                name = mname if isinstance(mname, str) else None
            kind = "object" if objs and not nd.get("children") else "component"
            parent = str(up + 1) if up is not None else ("0" if assembly else None)
            color = None
            if objs:
                mi, pi = self._objects[objs[0]]
                color = self._color(self.json["meshes"][mi]["primitives"][pi])
            out.append(
                ModelNode(
                    str(i + 1),
                    parent,
                    clip_text(name, self.limits, None) if name else f"node {i}",
                    kind,
                    objs[0] if objs else None,
                    None,
                    local if parent is not None or local is not IDENTITY else None,
                    color,
                )
            )
            clock.tick()
        for node, _w in self._instances:
            if node < 0:
                m = -1 - node
                objs = self._mesh_objects[m]
                out.append(
                    ModelNode(
                        f"m{m + 1}",
                        "0" if assembly else None,
                        f"mesh {m}",
                        "object",
                        objs[0] if objs else None,
                    )
                )
        return out

    def _scene(self, sb: SceneBuilder) -> None:
        cut = False
        try:
            for mi, pi in self._objects:
                prim = self.json["meshes"][mi]["primitives"][pi]
                self._primitive(sb, mi, pi, prim)
        except _Truncated:  # max_triangles: the primitives finished are placed
            cut = True
        finished = len(sb.objects)
        for node, world in self._instances:
            instance = str(node + 1) if node >= 0 else f"m{-node}"
            for o in self._mesh_objects[self._mesh_of(node)]:
                if o < finished:
                    sb.add_item(o, instance, world)
        if cut:
            raise _Truncated()

    def _primitive(self, sb: SceneBuilder, mi: int, pi: int, prim: dict) -> None:
        what = f"mesh {mi} primitive {pi}"
        attrs = prim["attributes"]
        lim = self.limits
        clock = sb.clock
        pos, _n = self._accessor(
            attrs["POSITION"], ("VEC3",), f"{what} POSITION", (lim.vertices - sb.vertices, "vertices"), clock
        )
        nv = len(pos) // 3
        normals = None
        if (
            "NORMAL" in attrs
            and not self._all_zeros(attrs["NORMAL"])
            and self._get("accessors", attrs["NORMAL"]).get("count") == nv
        ):
            nrm, _n = self._accessor(attrs["NORMAL"], ("VEC3",), f"{what} NORMAL", (nv, "vertices"), clock)
            if len(nrm) == len(pos):
                normals = nrm
        if "indices" in prim:
            idx, _n = self._accessor(
                prim["indices"],
                ("SCALAR",),
                f"{what} indices",
                (3 * (lim.triangles - sb.triangles) + 2, "triangles"),
                clock,
            )
            if idx.typecode not in "BHI":
                raise SldFormatError(f"{what}: indices are not unsigned whole numbers")
        else:
            idx = range(nv)
        mode = prim.get("mode", 4)
        n = len(idx)
        if mode == 4:
            tris = idx if n % 3 == 0 else idx[: n - n % 3]
        elif mode == 5:
            tris = array("I")
            for i in range(n - 2):
                if i % 2 == 0:
                    tris.extend((idx[i], idx[i + 1], idx[i + 2]))
                else:
                    tris.extend((idx[i + 1], idx[i], idx[i + 2]))
                if not i % _BATCH:
                    clock.tick(_BATCH)
        else:
            tris = array("I")
            for i in range(1, n - 1):
                tris.extend((idx[i], idx[i + 1], idx[0]))
                if not i % _BATCH:
                    clock.tick(_BATCH)
        mb = sb.mesh(name=self._object_name(mi, pi), scale_m=1.0, color=self._color(prim), node=None)
        mb.add_vertices(pos if pos.typecode == "d" else iter(pos))
        if normals is not None:
            mb.set_normals(normals)
        mb.add_triangles(tris if isinstance(tris, array) and tris.typecode == "I" else iter(tris))
        mb.finish()

    def _references(self, clock: Clock) -> list[ExternalReference]:
        out = []
        for i, buf in enumerate(self.json.get("buffers", [])):
            uri = buf.get("uri")
            if isinstance(uri, str) and not uri.startswith("data:"):
                name = uri.replace("\\", "/").rsplit("/", 1)[-1] or uri
                res = sibling_resolution(
                    self.path, uri, refuse_hard_links=self.refuse_hard_links, subfolders=self.subfolders
                )
                out.append(ExternalReference(f"buffer:{i}", "buffer", uri, name, res))
        return out


def _data_uri(uri: str, limits) -> bytes:
    head, sep, payload = uri.partition(",")
    if not sep:
        raise SldFormatError("a data URI has no data")
    if head.endswith(";base64"):
        if len(payload) * 3 // 4 > limits.gltf_data_uri_bytes:
            raise limits.exceeded("gltf_data_uri_bytes", "a data URI decodes to more bytes than allowed")
        try:
            return base64.b64decode(payload, validate=True)
        except ValueError:
            raise SldFormatError("a data URI is not valid base64") from None
    if len(payload) > limits.gltf_data_uri_bytes:
        raise limits.exceeded("gltf_data_uri_bytes", "a data URI decodes to more bytes than allowed")
    return unquote_to_bytes(payload)


def open(source, *, name, path, file_info, limits, hold_open=False, detection=None) -> GltfDocument:
    """Open a glTF or GLB file's :class:`~solidseas.formats._source.Source` (the registry's
    reader for ``gltf``)."""
    return GltfDocument(source, name=name, path=path, file_info=file_info, limits=limits, detection=detection)


__all__ = ["REVISION", "Z_UP", "GltfDocument", "open"]
