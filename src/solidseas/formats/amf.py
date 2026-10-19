"""AMF, the Additive Manufacturing File format (ISO/ASTM 52915), plain or zipped
(provisional, ``docs/formats/mesh.md``).

An AMF file is XML: ``<amf unit="millimeter">`` holds ``<object>`` elements (a
``<mesh>`` of ``<vertices>``, each ``<vertex><coordinates><x>..``, and
``<volume>`` elements of ``<triangle><v1>..<v2>..<v3>..``), ``<material>``
elements with a ``<color>`` (``<r> <g> <b> <a>`` from 0 to 1), ``<metadata
type="...">`` and ``<constellation>`` elements that place objects and other
constellations (``<instance objectid>`` with ``<deltax>``.. ``<deltaz>`` and
``<rx>``.. ``<rz>`` in degrees, turned about x, then y, then z, then moved). A
zipped AMF is a zip package holding one ``.amf`` member.

SolidSeas reads each object as one object a colour. A ``<color>`` may stand in a
material, an object, a volume, a vertex or a triangle, and the later in that list
wins: a triangle takes its own colour, else its first corner's, else its volume's,
else its object's, else its volume's material's. Without constellations every
object is placed once where it stands, and the file is a part; with them it is an
assembly, each top-level constellation placing its instances (depth
``amf_constellation_depth``, cycles refused, every placement counted against
``limits.items``), and objects no constellation places are placed once where they
stand. Curved triangles (vertex normals and ``<edge>`` tangents) are drawn flat
(``curved_triangles_flattened``); colours given as formulas and textures are not
read. The unit is ``unit`` (millimetre when absent, as the standard says).

The head reads the first 64 KiB alone: the unit, the metadata before the first
object, and whether a constellation appears there. Constellations usually follow
the objects, so a longer file's document type stays unknown (None) until a full
read settles it.

A scene's ``max_triangles`` keeps the objects finished before it was passed: the
object being read is dropped, the rest of the file is read for its materials and
constellations only, and the finished objects are placed.

The XML is parsed by :func:`~solidseas.formats._source.xml_events` (no DOCTYPE or
entity, depth and text bounded); a zipped one is inflated by
:class:`~solidseas.formats._source.SafeZip` within the zip bounds.
"""

import math
import re
from array import array
from typing import Any

from ..errors import SldFormatError
from ..formats.solidworks.components import IDENTITY, Placement
from ._source import Clock, SafeZip, clip_text, xml_events
from .base import ModelDocument, ModelNode, ModelTree, SceneBuilder, _stem, make_property
from .obj import HeadChunks, MeshSink, Palette, unit_color, zip_chunks

REVISION = 1
HEAD_BYTES = 64 << 10
_UNITS = {
    "millimeter": "mm",
    "millimetre": "mm",
    "inch": "in",
    "feet": "ft",
    "foot": "ft",
    "meter": "m",
    "metre": "m",
    "micron": "micron",
    "micrometer": "micron",
}
_FIELDS = {"name": "title", "author": "author", "description": "comments"}
_CONSTELLATION = re.compile(rb"<(?:[A-Za-z_][\w.-]*:)?constellation[\s/>]")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _float(text: str) -> float | None:
    try:
        v = float(text)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _rotation(rx: float, ry: float, rz: float) -> tuple:
    """Turned about x, then y, then z (degrees): Rz Ry Rx, row by row."""
    cx, sx = math.cos(math.radians(rx)), math.sin(math.radians(rx))
    cy, sy = math.cos(math.radians(ry)), math.sin(math.radians(ry))
    cz, sz = math.cos(math.radians(rz)), math.sin(math.radians(rz))
    return (
        (cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx),
        (sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx),
        (-sy, cy * sx, cy * cx),
    )


class _Object:
    __slots__ = (
        "color",
        "dropped",
        "id",
        "n_vertices",
        "name",
        "palette",
        "positions",
        "tri_colors",
        "triangles",
        "vertex_colors",
        "volumes",
    )

    def __init__(self, oid: str, palette: Palette) -> None:
        self.id = oid
        self.name: str | None = None
        self.color: Any = None
        self.positions = array("d")
        self.triangles = array("I")
        self.n_vertices = 0
        self.palette = palette  # the colours of its vertices and triangles, numbered
        self.vertex_colors: array | None = None  # a palette id a vertex (0: none), when any has one
        self.tri_colors: array | None = None  # a palette id a triangle (0: none), when any has one
        self.volumes: list[dict] = []  # materialid, colour, triangles
        self.dropped = False  # cut by a scene's max_triangles

    def drop(self) -> None:
        self.dropped = True
        self.positions, self.triangles = array("d"), array("I")
        self.vertex_colors = self.tri_colors = None


class AmfDocument(ModelDocument):
    """One AMF file, plain or zipped (see the module notes)."""

    format = "amf"

    def __init__(self, source, *, name, path, file_info, limits, detection=None) -> None:
        super().__init__(
            source, name=name, path=path, file_info=file_info, limits=limits, detection=detection
        )
        self.kind = "mesh"
        head = source.head(4)
        self.variant = "zip" if head == b"PK\x03\x04" else "plain"
        self._zip: SafeZip | None = None
        self._member: str | None = None
        clock = Clock(limits.seconds)
        try:
            if self.variant == "zip":
                self._zip = SafeZip(source, limits, clock)
                members = [n for n in self._zip.names() if n.lower().endswith(".amf") and not n.endswith("/")]
                if not members:
                    raise SldFormatError("the zipped AMF holds no .amf member")
                self._member = members[0]
            self._head(clock)
        except BaseException:
            if self._zip is not None:
                self._zip.close()
            raise

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()
        super().close()

    def _chunks(self, clock: Clock):
        if self._zip is not None:
            return zip_chunks(self._zip, self._member, clock)
        return self.source.chunks()

    def _events(self, clock: Clock):
        for kind, tag, value in xml_events(self._chunks(clock), self.limits, clock):
            yield kind, _local(tag), value

    # -- the head --------------------------------------------------------------------------
    def _head(self, clock: Clock) -> None:
        lim = self.limits
        unit = None
        seen_root = False
        meta: list[tuple[str, str]] = []
        constellations = False
        head = HeadChunks(self._chunks(clock), HEAD_BYTES)
        mtype = None
        depth = 0
        for kind, tag, value in xml_events(head, lim, clock):
            if head.past:
                break
            tag = _local(tag)
            if kind == "start":
                depth += 1
                if not seen_root:
                    if tag != "amf":
                        raise SldFormatError("not an AMF file: its root element is not amf")
                    seen_root = True
                    unit = value.get("unit")
                elif depth == 2 and tag == "metadata":
                    mtype = value.get("type")
                elif depth == 2 and tag == "constellation":
                    constellations = True
                elif depth == 2 and tag == "object":
                    break
            else:
                if depth == 2 and tag == "metadata" and mtype:
                    meta.append((mtype, value))
                    mtype = None
                depth -= 1
        if not seen_root:
            raise SldFormatError("not an AMF file: no amf element")
        if unit is None:
            self.set_units("mm", "format")
        else:
            token = _UNITS.get(unit.strip().lower())
            if token is None:
                raise SldFormatError(f"the AMF unit {unit[:20]!r} is not one the standard names")
            self.set_units(token, "file")
        self._apply_metadata(meta)
        found = True if constellations else self._has_constellation(clock)
        self.doc_type = None if found is None else ("assembly" if found else "part")

    def _has_constellation(self, clock: Clock) -> bool | None:
        """Whether the first 64 KiB hold a ``<constellation>`` tag: True when they do, False
        when the whole file is in them and holds none, None when it is longer
        (constellations come after the objects, so the head's parse does not reach them)."""
        tail = b""
        fed = 0
        for chunk in self._chunks(clock):
            if fed >= HEAD_BYTES:
                return None
            chunk = chunk[: HEAD_BYTES - fed]
            fed += len(chunk)
            buf = tail + chunk
            if _CONSTELLATION.search(buf):
                return True
            tail = buf[-64:]
            clock.tick(len(chunk) // 64 or 1)
        return False

    def _apply_metadata(self, meta: list[tuple[str, str]]) -> None:
        lim = self.limits
        props = []
        fields: dict[str, Any] = {}
        for mtype, text in meta[: lim.properties]:
            key = clip_text(mtype.strip(), lim, self.warnings, "a metadata type")
            value = clip_text(text.strip(), lim, self.warnings, "a metadata value")
            props.append(make_property(key, value))
            f = _FIELDS.get(key.lower())
            if f and value and f not in fields:
                fields[f] = value
            if key.lower() == "cad" and value and self.application["name"] is None:
                self.application = {"name": value, "version": None}
        self.properties = props
        if fields:
            from dataclasses import replace

            self.fields = replace(self.fields, **fields)

    # -- the full read ---------------------------------------------------------------------
    def _parse(self, sink: MeshSink):
        """Every object, material and constellation, in one pass."""
        lim = self.limits
        clock = sink.clock
        objects: list[_Object] = []
        materials: dict[str, Any] = {}
        constellations: dict[str, list[tuple[str, Placement]]] = {}
        path: list[str] = []
        attrs: list[dict] = []
        obj: _Object | None = None
        volume: dict | None = None
        material_id: str | None = None
        constellation: list | None = None
        instance: dict | None = None
        coords: dict[str, float] = {}
        tri: dict[str, str] = {}
        color: dict[str, float | None] = {}
        vertex_color: Any = None
        tri_color: Any = None
        curved = False
        pending_v = pending_t = 0  # read and not counted yet, of the object being read
        placements = 0  # constellations and instances
        build = sink.building

        def cut() -> None:
            nonlocal pending_v, pending_t
            pending_v = pending_t = 0
            if obj is not None:
                obj.drop()

        for kind, tag, value in self._events(clock):
            if kind == "start":
                path.append(tag)
                attrs.append(value)
                if tag == "object" and len(path) == 2:
                    obj = _Object(value.get("id", str(len(objects))), Palette(lim))
                    if len(objects) >= lim.objects:
                        raise lim.exceeded("objects", f"the file has more than {lim.objects:,} objects")
                    objects.append(obj)
                    pending_v = pending_t = 0
                    if sink.cut:  # past max_triangles: read on for the constellations only
                        obj.drop()
                elif tag == "volume" and obj is not None:
                    volume = {"material": value.get("materialid"), "color": None, "start": len(obj.triangles)}
                    obj.volumes.append(volume)
                elif tag == "material" and len(path) == 2:
                    material_id = value.get("id")
                elif tag == "constellation" and len(path) == 2:
                    constellation = constellations.setdefault(value.get("id", ""), [])
                    placements += 1
                    if placements > lim.items:
                        raise lim.exceeded("items", f"the file places more than {lim.items:,} instances")
                elif tag == "instance" and constellation is not None:
                    instance = {"objectid": value.get("objectid", ""), "values": {}}
                elif tag == "color":
                    color = {}
                elif tag == "vertex":
                    vertex_color = None
                elif tag == "triangle":
                    tri_color = None
                elif tag in ("normal", "edge") and obj is not None:
                    curved = True
                continue
            # an end event: value is the element's text
            path.pop()
            mine = attrs.pop()
            parent = path[-1] if path else None
            if parent == "coordinates" and tag in ("x", "y", "z"):
                coords[tag] = float(value)
            elif tag == "coordinates" and obj is not None:
                xyz = (coords["x"], coords["y"], coords["z"])  # KeyError: damaged
                coords = {}
                if obj.dropped:
                    continue
                if build:
                    obj.positions.extend(xyz)
                obj.n_vertices += 1
                pending_v += 1
                if pending_v >= 4096:
                    if not sink.take(0, pending_v):
                        cut()
                    pending_v = 0
            elif tag == "vertex" and obj is not None and not obj.dropped:
                if vertex_color is not None or obj.vertex_colors is not None:
                    if obj.vertex_colors is None:
                        obj.vertex_colors = array("I", bytes(4 * max(0, obj.n_vertices - 1)))
                    obj.vertex_colors.append(obj.palette.id(vertex_color) if vertex_color is not None else 0)
            elif parent == "triangle" and tag in ("v1", "v2", "v3"):
                tri[tag] = value
            elif tag == "triangle" and obj is not None and volume is not None:
                a, b, c = int(tri["v1"]), int(tri["v2"]), int(tri["v3"])
                tri = {}
                if obj.dropped:
                    continue
                obj.triangles.extend((_index(a), _index(b), _index(c)))
                if tri_color is not None or obj.tri_colors is not None:
                    if obj.tri_colors is None:
                        obj.tri_colors = array("I", bytes(4 * (len(obj.triangles) // 3 - 1)))
                    obj.tri_colors.append(obj.palette.id(tri_color) if tri_color is not None else 0)
                pending_t += 1
                if pending_t >= 4096:
                    if not sink.take(pending_t, 0):
                        cut()
                    pending_t = 0
            elif parent == "color" and tag in ("r", "g", "b", "a"):
                color[tag] = _float(value)
            elif tag == "color":
                c = None
                if all(color.get(k) is not None for k in "rgb"):
                    a = color.get("a")
                    c = unit_color(color["r"], color["g"], color["b"], 1.0 if a is None else a)
                if parent == "triangle":
                    tri_color = c
                elif parent == "vertex":
                    vertex_color = c
                elif parent == "volume" and volume is not None:
                    volume["color"] = c
                elif parent == "object" and obj is not None:
                    obj.color = c
                elif parent == "material" and material_id is not None:
                    materials[material_id] = c
            elif parent == "metadata" or tag == "metadata":
                if (
                    tag == "metadata"
                    and parent == "object"
                    and obj is not None
                    and mine.get("type") == "name"
                ):
                    obj.name = clip_text(value.strip(), lim, None) or None
            elif parent == "instance" and instance is not None:
                instance["values"][tag] = value
            elif tag == "instance" and instance is not None and constellation is not None:
                v = {k: _float(t) for k, t in instance["values"].items()}
                d = [v.get(k) or 0.0 for k in ("deltax", "deltay", "deltaz", "rx", "ry", "rz")]
                constellation.append((instance["objectid"], (d[0], d[1], d[2]), _rotation(d[3], d[4], d[5])))
                placements += 1
                if placements > lim.items:
                    raise lim.exceeded("items", f"the file places more than {lim.items:,} instances")
                instance = None
            elif tag == "volume":
                if volume is not None and obj is not None:
                    volume["end"] = len(obj.triangles)
                volume = None
            elif tag == "object":
                # an object is finished: what it holds is counted before it is kept
                if obj is not None and not obj.dropped and not sink.take(pending_t, pending_v):
                    cut()
                pending_v = pending_t = 0
                obj = None
            elif tag == "material":
                material_id = None
            elif tag == "constellation":
                constellation = None
        if curved:
            sink.warn(
                "curved_triangles_flattened",
                "curved triangles (vertex normals and edge tangents) are drawn flat",
            )
        return objects, materials, constellations

    def _read(self, sink: MeshSink):
        """``(objects emitted: (node name, scene objects, colours) by AMF id, the ids of the
        objects a scene's max_triangles dropped, every object's id, constellations)``."""
        objects, materials, constellations = self._parse(sink)
        scale = self.units["scale_m"] or 0.001
        emitted: dict[str, tuple[str | None, list[int], list]] = {}
        dropped: set[str] = set()
        for obj in objects:
            if obj.dropped:
                dropped.add(obj.id)
                continue
            palette = obj.palette
            ntri = len(obj.triangles) // 3
            # each triangle's colour: its own, else its first corner's, else its volume's
            ids = array("I", bytes(4 * ntri))
            for vol in obj.volumes:
                c = vol["color"]
                if c is None:
                    c = obj.color
                if c is None and vol["material"] is not None:
                    c = materials.get(vol["material"])
                first = vol["start"] // 3
                n = (vol.get("end", len(obj.triangles)) - vol["start"]) // 3
                ids[first : first + n] = array("I", [palette.id(c)]) * n
            vc, tc = obj.vertex_colors, obj.tri_colors
            if vc is not None or tc is not None:
                tris = obj.triangles
                for t in range(ntri):
                    k = tc[t] if tc is not None and t < len(tc) else 0
                    if not k and vc is not None:
                        a = tris[3 * t]
                        k = vc[a] if a < len(vc) else 0
                    if k:
                        ids[t] = k
                    if not t & 4095:
                        sink.clock.tick(4096)
            if palette.overflow:
                sink.warn(
                    "colors_ignored", "an object has more colours than are kept; it is drawn without them"
                )
                ids = None
            objs, cols = sink.emit(
                name=obj.name or obj.id,
                node=None,
                scale_m=scale,
                positions=obj.positions,
                triangles=obj.triangles,
                default=obj.color,
                palette=palette.colors,
                color_ids=ids,
            )
            emitted.setdefault(obj.id, (obj.name or obj.id, objs, cols))
        return emitted, dropped, [o.id for o in objects], constellations

    def _layout(self, sink: MeshSink):
        """``(nodes, items, truncated)``: for a tree (``sink`` builds nothing) its nodes,
        stopped past ``limits.tree_nodes`` (then ``truncated``); for a scene ``(scene
        object, node id, placement)`` for each placed object. Every placement of an
        object or a constellation counts against ``limits.items``."""
        emitted, dropped, ids, constellations = self._read(sink)
        lim = self.limits
        if self.doc_type is None:
            self.doc_type = "assembly" if constellations else "part"
        scale = self.units["scale_m"] or 0.001
        tree = not sink.building
        nodes: list[ModelNode] = []
        items: list[tuple[int, str, Placement]] = []
        counter = [0]

        def new_id() -> str:
            counter[0] += 1
            if counter[0] > lim.items:
                raise lim.exceeded("items", f"the file places more than {lim.items:,} items")
            sink.clock.tick()
            return str(counter[0])

        def add(node: ModelNode) -> None:
            nodes.append(node)
            if len(nodes) > lim.tree_nodes:
                raise _Enough()

        def place_object(oid: str, parent: str | None, local: Placement, world: Placement) -> None:
            name, objs, cols = emitted[oid]
            node = new_id()
            if tree:
                add(
                    ModelNode(
                        node,
                        parent,
                        name,
                        "object",
                        objs[0] if objs else None,
                        None,
                        local if parent is not None and local is not IDENTITY else None,
                        cols[0] if cols else None,
                    )
                )
                return
            for i in objs:
                items.append((i, node, world))

        if not constellations:
            try:
                for oid in emitted:
                    place_object(oid, None, IDENTITY, IDENTITY)
            except _Enough:
                return nodes, items, True
            return nodes, items, False
        referenced = {oid for insts in constellations.values() for oid, _t, _r in insts}
        if all(cid in referenced for cid in constellations) and all(oid in referenced for oid in ids):
            raise SldFormatError("the AMF's constellations all place each other")
        root = "0"
        if tree:
            nodes.append(ModelNode(root, None, self.fields.title or _stem(self.name), "assembly"))
        depth_max = lim.amf_constellation_depth
        placed = {  # each instance's placement, made once however often its constellation is placed
            cid: [(oid, Placement(r, (t[0] * scale, t[1] * scale, t[2] * scale))) for oid, t, r in insts]
            for cid, insts in constellations.items()
        }

        def place_constellation(
            cid: str, parent: str, local: Placement, world: Placement, seen: tuple
        ) -> None:
            if cid in seen:
                raise SldFormatError("an AMF constellation places itself")
            if len(seen) >= depth_max:
                raise lim.exceeded("amf_constellation_depth", f"constellations nest deeper than {depth_max}")
            node = new_id()
            if tree:
                add(
                    ModelNode(
                        node,
                        parent,
                        f"constellation {cid}",
                        "component",
                        None,
                        None,
                        local if local is not IDENTITY else None,
                    )
                )
            for oid, inner in placed[cid]:
                if oid in constellations:
                    place_constellation(oid, node, inner, world.then(inner), (*seen, cid))
                elif oid in emitted:
                    place_object(oid, node, inner, world.then(inner))
                elif oid not in dropped:  # one cut by max_triangles is left out silently
                    sink.missing(node, f"an instance names object {oid[:40]!r}, which the file does not have")

        try:
            for cid in constellations:
                if cid not in referenced:
                    place_constellation(cid, root, IDENTITY, IDENTITY, ())
            for oid in emitted:
                if oid not in referenced:
                    place_object(oid, root, IDENTITY, IDENTITY)
        except _Enough:
            return nodes, items, True
        return nodes, items, False

    # -- hooks ---------------------------------------------------------------------------
    def _tree(self, clock: Clock):
        nodes, _items, truncated = self._layout(_AmfSink(None, self.limits, clock))
        return ModelTree(tuple(nodes), truncated)

    def _scene(self, sb: SceneBuilder) -> None:
        sink = _AmfSink(sb, self.limits, sb.clock)
        _nodes, items, _t = self._layout(sink)
        for i, node, placement in items:
            sb.add_item(i, node, placement)
        sink.finish_scene()


class _AmfSink(MeshSink):
    def missing(self, instance: str, message: str) -> None:
        if self.sb is not None:
            self.sb.missing_component(instance, message)


class _Enough(Exception):
    """A tree has more nodes than ``limits.tree_nodes``: the layout stops there."""


def _index(v: int) -> int:
    return v if 0 <= v < 0xFFFFFFFF else 0xFFFFFFFF


def open(source, *, name, path, file_info, limits, hold_open=False, detection=None) -> AmfDocument:
    """Open an AMF file's :class:`~solidseas.formats._source.Source` (the registry's reader
    for ``amf``)."""
    return AmfDocument(source, name=name, path=path, file_info=file_info, limits=limits, detection=detection)


__all__ = ["REVISION", "AmfDocument", "open"]
