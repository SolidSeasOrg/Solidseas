"""3MF, the 3D Manufacturing Format: the core specification with the production and
materials extensions (provisional, ``docs/formats/mesh.md``).

A 3MF file is an Open Packaging Conventions package (a zip). Its relationships
(``_rels/.rels``) name the root model part (``3D/3dmodel.model`` by habit, never
assumed) and the thumbnail. A model part is XML in the core namespace:
``<model unit=...>`` with ``<metadata name=...>``, ``<resources>`` (property
groups such as ``<basematerials>``, and ``<object>`` elements that hold either a
``<mesh>`` of ``<vertices>`` and ``<triangles>`` or ``<components>`` that place
other objects) and a ``<build>`` of ``<item>`` elements that place objects. A
transform is twelve numbers, ``m00 m01 m02 m10 m11 m12 m20 m21 m22 m30 m31
m32``, applied to a row vector, the last three the translation.

SolidSeas reads:

* every object in the root model part and in the parts its components and
  build items name with the production extension's ``p:path`` (each part read
  once, from inside the package only; a non-root part's own ``p:path``
  references are refused, ``part_reference_refused``, as the extension says);
* each mesh object as one scene object a colour, its triangles' colours from
  ``<basematerials>`` display colours and the materials extension's
  ``<colorgroup>`` (a triangle's ``p1`` in its ``pid`` group, else in its
  object's; a triangle without ``p1`` takes its object's ``pid`` and ``pindex``,
  as the core specification says), up to ``colors_per_object`` (then
  ``colors_ignored``); textures, composite materials and multi-properties give no
  colour;
* the build: each item placed with its transform, components expanded down to
  their meshes with their transforms composed (depth
  ``threemf_component_depth``, cycles refused); objects of type ``other`` are
  never placed, support objects are, under their names;
* the unit (``micron``, ``millimeter``, ``centimeter``, ``inch``, ``foot``,
  ``meter``; millimetres when absent, as the specification says);
* the root model's metadata: ``Title``, ``Designer``, ``Description``,
  ``CreationDate``, ``ModificationDate`` and ``Application`` into the fields and
  the application, every unprefixed name as a property; names in a vendor's
  namespace (a slicer's) are not read;
* the stored preview: the package's thumbnail relationship, else
  ``Metadata/thumbnail.png``, else the first plate image, as a PNG.

A model that requires an extension the reader does not implement (slices, beam
lattices, volumetric data, secure content, displacement, or any namespace it
does not know) is refused (``format_not_supported``, rule
``required_extension``, the namespace as the value); one that only recommends it
is read without it (``extension_ignored``). Slicer settings and plates, kept in
vendor parts and namespaces, are not read (``slicer_data_ignored``).

The package is read through :class:`~solidseas.formats._source.SafeZip` (member
count, directory, inflated sizes and ratio bounded) and the XML through
:func:`~solidseas.formats._source.xml_events` (no DOCTYPE or entity, depth and
lengths bounded), streamed, never built as a tree.

A file is an assembly when its build places more than one item or one of its
component objects places more than one component. The head reads the first 64 KiB
of the root model alone (so a listing stays cheap): when the whole model is in it,
a scan of its tags settles the document type and the counts of objects and items;
otherwise more than one item or component seen there makes it an assembly, and
the rest stays unknown (None) until a full read (``tree()`` or ``scene()``)
settles it.

A scene's ``max_triangles`` keeps the objects finished before it was passed: the
object being read is dropped, the rest of the model is read for its components and
build only, and the finished objects are placed.
"""

import datetime
import re
from array import array
from dataclasses import replace
from typing import Any

from ..errors import FormatNotSupportedError, SldFormatError
from ..formats.solidworks.components import IDENTITY, Placement
from ..formats.solidworks.preview import Preview, png_size
from ._source import PNG_SIGNATURE, Clock, SafeZip, clip_text, opc_resolve, xml_events, xml_tree
from .base import UNIT_SCALE, ModelDocument, ModelNode, ModelTree, SceneBuilder, _stem, make_property
from .obj import HeadChunks, MeshSink, Palette, hex_color, split_application, zip_chunks

REVISION = 1
HEAD_BYTES = 64 << 10
CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
MATERIAL = "http://schemas.microsoft.com/3dmanufacturing/material/2015/02"
PRODUCTION = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
TRIANGLE_SETS = "http://schemas.microsoft.com/3dmanufacturing/trianglesets/2021/07"
XML_NS = "http://www.w3.org/XML/1998/namespace"
START_PART = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
THUMBNAIL = "http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"
RELATIONSHIPS = "http://schemas.openxmlformats.org/package/2006/relationships"
# What each extension namespace the reader knows is (the ones it reads, and the ones it refuses).
UNDERSTOOD = frozenset({CORE, MATERIAL, PRODUCTION, TRIANGLE_SETS})
KNOWN_EXTENSIONS = {
    "http://schemas.microsoft.com/3dmanufacturing/slice/2015/07": "slices",
    "http://schemas.microsoft.com/3dmanufacturing/beamlattice/2017/02": "beam lattices",
    "http://schemas.microsoft.com/3dmanufacturing/beamlattice/balls/2020/07": "beam lattice balls",
    "http://schemas.microsoft.com/3dmanufacturing/securecontent/2019/04": "secure content",
    "http://schemas.microsoft.com/3dmanufacturing/securecontent/2019/07": "secure content",
    "http://schemas.microsoft.com/3dmanufacturing/volumetric/2022/01": "volumetric data",
    "http://schemas.3mf.io/3dmanufacturing/implicit/2023/12": "implicit geometry",
    "http://schemas.microsoft.com/3dmanufacturing/displacement/2022/07": "displacement",
    "http://schemas.3mf.io/3dmanufacturing/displacement/2023/10": "displacement",
    "http://schemas.microsoft.com/3dmanufacturing/production/alternatives/2021/04": "production alternatives",
}
_STANDARD = UNDERSTOOD | set(KNOWN_EXTENSIONS) | {XML_NS}
UNITS = {"micron": "micron", "millimeter": "mm", "centimeter": "cm", "inch": "in", "foot": "ft", "meter": "m"}
_FIELDS = {"Title": "title", "Designer": "author", "Description": "comments"}
_DATES = {"CreationDate": "created_utc", "ModificationDate": "last_saved_utc"}
_TYPES = ("model", "solidsupport", "support", "surface", "other")
_PLATE = re.compile(r"Metadata/plate_(\d+)\.png\Z", re.IGNORECASE)
_TAG = re.compile(rb"<(?:[A-Za-z_][\w.-]*:)?(item|component|object|/object)[\s/>]")

_V = f"{{{CORE}}}vertex"
_T = f"{{{CORE}}}triangle"
_OBJECT = f"{{{CORE}}}object"
_MESH = f"{{{CORE}}}mesh"
_COMPONENT = f"{{{CORE}}}component"
_COMPONENTS = f"{{{CORE}}}components"
_ITEM = f"{{{CORE}}}item"
_MODEL = f"{{{CORE}}}model"
_BASEMATERIALS = f"{{{CORE}}}basematerials"
_BASE = f"{{{CORE}}}base"
_COLORGROUP = f"{{{MATERIAL}}}colorgroup"
_COLOR = f"{{{MATERIAL}}}color"
_NO_COLOR_GROUPS = {
    f"{{{MATERIAL}}}texture2dgroup": (f"{{{MATERIAL}}}tex2coord", True),
    f"{{{MATERIAL}}}compositematerials": (f"{{{MATERIAL}}}composite", False),
    f"{{{MATERIAL}}}multiproperties": (f"{{{MATERIAL}}}multi", False),
}
_PATH = f"{{{PRODUCTION}}}path"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def transform(text: str | None, scale_m: float) -> Placement:
    """A 3MF transform attribute as a :class:`Placement` (translation in metres, the
    numbers in units of ``scale_m`` metres). None or empty is the identity."""
    if text is None or not text.strip():
        return IDENTITY
    cells = text.split()
    if len(cells) != 12:
        raise SldFormatError("a transform is not twelve numbers")
    try:
        m = [float(c) for c in cells]
    except ValueError:
        raise SldFormatError("a transform holds something that is not a number") from None
    rot = ((m[0], m[3], m[6]), (m[1], m[4], m[7]), (m[2], m[5], m[8]))
    return Placement(rot, (m[9] * scale_m, m[10] * scale_m, m[11] * scale_m))


def _date(text: str) -> datetime.datetime | None:
    """A metadata date: aware UTC when it carries a zone, else naive, as stored (a date
    alone is its midnight): ISO 8601 text without a zone is local time where it was
    written, zone unknown, so it is never moved to another day."""
    t = text.strip()
    if not t:
        return None
    try:
        if len(t) == 10:
            d = datetime.date.fromisoformat(t)
            return datetime.datetime(d.year, d.month, d.day)
        dt = datetime.datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(datetime.UTC)


class _Obj:
    __slots__ = ("colors", "components", "id", "name", "part", "scene", "type")

    def __init__(self, part: str, oid: str, name: str | None, otype: str) -> None:
        self.part = part
        self.id = oid
        self.name = name
        self.type = otype
        self.scene: list[int] = []
        self.colors: list = []
        self.components: list[tuple[str, str, Placement]] | None = None  # part, object id, placement


class _Model:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], _Obj] = {}
        self.items: list[tuple[str, str, Placement, str | None]] = []  # part, id, placement, part number
        self.parts: list[str] = []
        self.components = 0


class ThreeMfDocument(ModelDocument):
    """One 3MF package (see the module notes)."""

    format = "3mf"

    def __init__(self, source, *, name, path, file_info, limits, detection=None) -> None:
        super().__init__(
            source, name=name, path=path, file_info=file_info, limits=limits, detection=detection
        )
        self.kind = "mesh"
        clock = Clock(limits.seconds)
        self._zip = SafeZip(source, limits, clock)
        try:
            self._package(clock)
        except BaseException:
            self._zip.close()
            raise

    def close(self) -> None:
        self._zip.close()
        super().close()

    def _member(self, member: str, clock: Clock, max_bytes: int | None = None):
        """A member's bytes, inflated a chunk at a time, ticking ``clock``."""
        return zip_chunks(self._zip, member, clock, max_bytes)

    # -- the package -----------------------------------------------------------------------
    def _relationships(self, part: str, clock: Clock) -> list[tuple[str, str]]:
        """``(type, member)`` of the internal relationships of ``part`` (``""``: the package)."""
        if part:
            folder, _, base = part.rpartition("/")
            rels = f"{folder}/_rels/{base}.rels" if folder else f"_rels/{base}.rels"
        else:
            rels = "_rels/.rels"
        member = self._zip.find(rels)
        if member is None:
            return []
        data = b"".join(self._member(member, clock, self.limits.xml_text_bytes * 16))
        root = xml_tree(data, self.limits, clock)
        out = []
        for rel in root.children:
            if _local(rel.tag) != "Relationship" or rel.attrs.get("TargetMode", "").lower() == "external":
                continue
            target = opc_resolve(part, rel.attrs.get("Target", ""))
            if target is not None:
                out.append((rel.attrs.get("Type", ""), target))
        return out

    def _package(self, clock: Clock) -> None:
        lim = self.limits
        rels = self._relationships("", clock)
        root = None
        thumbs: list[str] = []
        for rtype, target in rels:
            if rtype.lower() == START_PART.lower() and root is None:
                root = self._zip.find(target)
            elif rtype.lower() == THUMBNAIL.lower():
                found = self._zip.find(target)
                if found is not None:
                    thumbs.append(found)
        if root is None:
            raise SldFormatError("the 3MF package names no 3D model part")
        self.root = root
        names = self._zip.names()
        for fixed in ("Metadata/thumbnail.png",):
            found = self._zip.find(fixed)
            if found is not None and found not in thumbs:
                thumbs.append(found)
        plates = sorted((int(m.group(1)), n) for n in names if (m := _PLATE.match(n)))
        if plates and plates[0][1] not in thumbs:
            thumbs.append(plates[0][1])
        self._thumbnails = thumbs
        self._model_parts = sum(1 for n in names if n.lower().endswith(".model"))
        vendor_parts = any(
            n.lower().startswith("metadata/") and n.lower().endswith((".config", ".xml", ".json"))
            for n in names
        )
        self._head(clock, vendor_parts)
        self._scan(clock)
        if self._n_objects is not None and lim.objects < self._n_objects:
            raise lim.exceeded("objects", f"the model has more than {lim.objects:,} objects")

    def _head(self, clock: Clock, vendor_parts: bool) -> None:
        """The root model's start tag and its metadata, from its first 64 KiB."""
        lim = self.limits
        head = HeadChunks(self._member(self.root, clock), HEAD_BYTES)
        ns: dict[str, str] = {}
        default = None
        root_attrs: dict[str, str] | None = None
        meta: list[tuple[str, str]] = []
        name = None
        depth = 0
        for kind, tag, value in xml_events(head, lim, clock, namespaces=False):
            if head.past:
                break
            if kind == "start":
                depth += 1
                if root_attrs is None:
                    root_attrs = value
                    ns = {k[6:]: v for k, v in value.items() if k.startswith("xmlns:")}
                    default = value.get("xmlns")
                    prefix, _, local = tag.rpartition(":")
                    uri = ns.get(prefix) if prefix else default
                    if local != "model" or uri != CORE:
                        raise SldFormatError("the 3MF's model part is not a 3MF model")
                elif depth == 2 and _local(tag) == "metadata":
                    name = value.get("name")
                elif depth == 2 and _local(tag) == "resources":
                    break
            else:
                if depth == 2 and _local(tag) == "metadata" and name is not None:
                    meta.append((name, value))
                    if len(meta) > lim.threemf_metadata:
                        raise lim.exceeded("threemf_metadata", "the model has too many metadata elements")
                    name = None
                depth -= 1
        if root_attrs is None:
            raise SldFormatError("the 3MF's model part is empty")
        self._ns = ns
        required = self._extensions(root_attrs.get("requiredextensions", ""), ns, default)
        for uri in required:
            if uri not in UNDERSTOOD:
                what = KNOWN_EXTENSIONS.get(uri, "an extension SolidSeas does not know")
                raise FormatNotSupportedError(
                    f"the 3MF requires {what}, which SolidSeas does not read",
                    detail={"rule": "required_extension", "value": uri[:200]},
                )
        recommended = [
            u
            for u in self._extensions(root_attrs.get("recommendedextensions", ""), ns, default)
            if u not in UNDERSTOOD
        ]
        if recommended:
            names = ", ".join(sorted({KNOWN_EXTENSIONS.get(u, u) for u in recommended}))
            self.warn("extension_ignored", f"the 3MF recommends {names}, which SolidSeas does not read")
        declared = set(ns.values()) | ({default} if default else set())
        self.variant = "production" if PRODUCTION in declared or PRODUCTION in required else "core"
        if vendor_parts or any(u not in _STANDARD for u in declared):
            self.warn(
                "slicer_data_ignored",
                "the package carries a slicer's own settings (plates, parameters), which are not read",
            )
        unit = root_attrs.get("unit")
        if unit is None:
            self.set_units("mm", "format")
        else:
            token = UNITS.get(unit.strip())
            if token is None:
                raise SldFormatError(f"the 3MF unit {unit[:20]!r} is not one the specification names")
            self.set_units(token, "file")
        self._metadata(meta)

    @staticmethod
    def _extensions(text: str, ns: dict[str, str], default: str | None) -> list[str]:
        out = []
        for prefix in text.split():
            uri = ns.get(prefix)
            if uri is None:
                raise SldFormatError(
                    f"the 3MF names the extension prefix {prefix[:20]!r} without declaring it"
                )
            out.append(uri)
        return out

    def _metadata(self, meta: list[tuple[str, str]]) -> None:
        lim = self.limits
        props = []
        fields: dict[str, Any] = {}
        for name, text in meta:
            if ":" in name:
                continue  # a vendor's (a slicer's) metadata
            key = clip_text(name, lim, self.warnings, "a metadata name")
            value = clip_text(text.strip(), lim, self.warnings, "a metadata value")
            props.append(make_property(key, value))
            if name in _FIELDS and value and _FIELDS[name] not in fields:
                fields[_FIELDS[name]] = value
            elif name in _DATES and _DATES[name] not in fields:
                when = _date(value)
                if when is not None:
                    fields[_DATES[name]] = when
            elif name == "Application" and value:
                self.application = split_application(value)
        self.properties = props[: lim.properties]
        if fields:
            self.fields = replace(self.fields, **fields)

    def _scan(self, clock: Clock) -> None:
        """Count the root model's objects, items and the most components one object
        places, from the tags of its first 64 KiB (not a parse: its meshes are not
        read). When the model is longer, only an assembly is settled (see the module
        notes)."""
        items = objects = most = 0
        current = 0
        tail = b""
        fed = 0
        complete = True
        for chunk in self._member(self.root, clock):
            if fed >= HEAD_BYTES:
                complete = False
                break
            chunk = chunk[: HEAD_BYTES - fed]
            fed += len(chunk)
            buf = tail + chunk
            cut = max(0, len(buf) - 256)
            last = 0
            for m in _TAG.finditer(buf):
                if m.start() >= cut:
                    break
                last = m.end()
                word = m.group(1)
                if word == b"item":
                    items += 1
                elif word == b"object":
                    objects += 1
                    current = 0
                elif word == b"component":
                    current += 1
                    most = max(most, current)
            tail = buf[max(cut, last) :]
            clock.tick(len(chunk) // 64 or 1)
        for m in _TAG.finditer(tail):
            word = m.group(1)
            if word == b"item":
                items += 1
            elif word == b"object":
                objects += 1
                current = 0
            elif word == b"component":
                current += 1
                most = max(most, current)
        if complete:
            self._n_objects, self._n_items = objects, items
            self.doc_type = "assembly" if items > 1 or most > 1 else "part"
        else:
            self._n_objects = self._n_items = None
            self.doc_type = "assembly" if items > 1 or most > 1 else None

    def _counts(self):
        return {"objects": self._n_objects, "items": self._n_items, "model_parts": self._model_parts}

    def _preview(self):
        lim = self.limits
        for member in self._thumbnails:
            if self._zip.size(member) > lim.image_bytes:
                continue
            data = b"".join(self._member(member, Clock(lim.seconds), lim.image_bytes))
            if not data.startswith(PNG_SIGNATURE):
                continue
            size = png_size(data)
            if size is None:
                continue
            return Preview(data, "image/png", size[0], size[1], member)
        return None

    # -- the model -------------------------------------------------------------------------
    def _read(self, sink: MeshSink) -> _Model:
        model = _Model()
        self._part(self.root, True, sink, model)
        wanted: list[str] = []
        for obj in list(model.objects.values()):
            for part, _oid, _p in obj.components or ():
                if part != self.root and part not in wanted:
                    wanted.append(part)
        for part, _oid, _p, _n in model.items:
            if part != self.root and part not in wanted:
                wanted.append(part)
        if len(wanted) + 1 > self.limits.threemf_model_parts:
            raise self.limits.exceeded(
                "threemf_model_parts", f"the model names more than {self.limits.threemf_model_parts:,} parts"
            )
        for part in wanted:
            if self._zip.find(part) is not None:
                self._part(part, False, sink, model)
        return model

    def _part(self, member: str, root: bool, sink: MeshSink, model: _Model) -> None:
        """Read one model part's objects into ``model`` (and its build, for the root)."""
        lim = self.limits
        clock = sink.clock
        build = sink.building
        model.parts.append(member)
        scale = 0.001
        groups: dict[str, list] = {}
        group: list | None = None
        group_entry: str | None = None
        group_entries = 0
        groups_dropped = textures = False
        obj: _Obj | None = None
        obj_pid = obj_pindex = None
        positions = array("d")
        triangles = array("I")
        ids: array | None = None
        palette: Palette | None = None
        keymap: dict = {}
        default_cid = 0
        ntri = 0
        skip_mesh = False
        nv = 0
        pending_v = pending_t = 0
        refused = 0
        if not root:
            self._check_part(member, clock)
        for kind, tag, a in xml_events(self._member(member, clock), lim, clock):
            if kind == "start":
                if tag == _V:
                    if skip_mesh:
                        continue
                    x, y, z = float(a["x"]), float(a["y"]), float(a["z"])
                    if build:
                        positions.extend((x, y, z))
                    nv += 1
                    pending_v += 1
                    if pending_v >= 4096:
                        if not sink.take(0, pending_v):  # max_triangles: this object is dropped
                            skip_mesh = True
                            positions, triangles, ids = array("d"), array("I"), None
                        pending_v = 0
                    continue
                if tag == _T:
                    if skip_mesh:
                        continue
                    v1, v2, v3 = int(a["v1"]), int(a["v2"]), int(a["v3"])
                    if build:
                        if v1 < 0 or v2 < 0 or v3 < 0:
                            raise SldFormatError("a triangle names a negative vertex index")
                        triangles.extend((v1, v2, v3))
                    p1 = a.get("p1")
                    # without p1 a triangle takes its object's default property, whatever its pid
                    if p1 is not None and palette is not None and not palette.overflow:
                        pid = a.get("pid")
                        key = (pid, p1)
                        cid = keymap.get(key)
                        if cid is None:
                            cid = palette.id(_property_color(groups, pid if pid is not None else obj_pid, p1))
                            if len(keymap) < 65_536:
                                keymap[key] = cid
                        if ids is None:
                            ids = array("I", [default_cid]) * ntri
                        ids.append(cid)
                    elif ids is not None:
                        ids.append(default_cid)
                    ntri += 1
                    pending_t += 1
                    if pending_t >= 4096:
                        if not sink.take(pending_t, 0):
                            skip_mesh = True
                            positions, triangles, ids = array("d"), array("I"), None
                        pending_t = 0
                    continue
                if tag == _OBJECT:
                    oid = a.get("id")
                    if oid is None:
                        raise SldFormatError("an object has no id")
                    otype = a.get("type", "model")
                    if otype not in _TYPES:
                        otype = "model"
                    oname = a.get("name") or a.get("partnumber")
                    obj = _Obj(member, oid, clip_text(oname, lim, None) if oname else None, otype)
                    if (member, oid) in model.objects:
                        raise SldFormatError(f"two objects share the id {oid[:20]!r}")
                    if len(model.objects) >= lim.objects:
                        raise lim.exceeded("objects", f"the model has more than {lim.objects:,} objects")
                    model.objects[(member, oid)] = obj
                    obj_pid, obj_pindex = a.get("pid"), a.get("pindex")
                elif tag == _MESH and obj is not None:
                    # past max_triangles, meshes are skipped: the read goes on for the build
                    skip_mesh = obj.type == "other" or sink.cut
                    pending_t = pending_v = 0
                    positions = array("d")
                    triangles = array("I")
                    ids = None
                    palette = Palette(lim)
                    keymap = {}
                    default_cid = palette.id(_property_color(groups, obj_pid, obj_pindex))
                    ntri = nv = 0
                elif tag == _COMPONENTS and obj is not None:
                    obj.components = []
                elif tag == _COMPONENT and obj is not None and obj.components is not None:
                    path = a.get(_PATH)
                    part = member
                    if path:
                        target = opc_resolve("", path)
                        found = self._zip.find(target) if target else None
                        if not root and found != member:
                            refused += 1
                            continue
                        part = found or (target or "")
                    model.components += 1
                    if model.components > lim.threemf_components:
                        raise lim.exceeded(
                            "threemf_components",
                            f"the model has more than {lim.threemf_components:,} components",
                        )
                    obj.components.append((part, a.get("objectid", ""), transform(a.get("transform"), scale)))
                elif tag == _ITEM and root:
                    path = a.get(_PATH)
                    part = member
                    if path:
                        target = opc_resolve("", path)
                        part = (self._zip.find(target) if target else None) or (target or "")
                    if len(model.items) >= lim.items:
                        raise lim.exceeded("items", f"the build has more than {lim.items:,} items")
                    model.items.append(
                        (
                            part,
                            a.get("objectid", ""),
                            transform(a.get("transform"), scale),
                            a.get("partnumber"),
                        )
                    )
                elif tag == _BASEMATERIALS or tag == _COLORGROUP:
                    group = self._new_group(groups, a)
                elif tag in _NO_COLOR_GROUPS:
                    group = self._new_group(groups, a)
                    group_entry, is_texture = _NO_COLOR_GROUPS[tag]
                    textures = textures or is_texture
                elif tag == _BASE and group is not None:
                    group_entries += 1
                    if group_entries <= lim.threemf_color_groups:
                        group.append(hex_color(a.get("displaycolor", "")))
                    else:
                        groups_dropped = True
                        group.append(None)
                elif tag == _COLOR and group is not None:
                    group_entries += 1
                    if group_entries <= lim.threemf_color_groups:
                        group.append(hex_color(a.get("color", "")))
                    else:
                        groups_dropped = True
                        group.append(None)
                elif group_entry is not None and tag == group_entry and group is not None:
                    group.append(None)
                elif tag == _MODEL:
                    unit = a.get("unit")
                    if unit is not None:
                        token = UNITS.get(unit.strip())
                        if token is None:
                            raise SldFormatError(
                                f"the 3MF unit {unit[:20]!r} is not one the specification names"
                            )
                        scale = UNIT_SCALE[token]
                continue
            # end events
            if tag == _MESH and obj is not None:
                if not skip_mesh and not sink.take(pending_t, pending_v):
                    skip_mesh = True  # this object passed max_triangles: dropped
                pending_t = pending_v = 0
                if not skip_mesh:
                    if palette is not None and palette.overflow:
                        sink.warn(
                            "colors_ignored",
                            f"an object has over {lim.colors_per_object} colours; it is drawn without them",
                        )
                        ids = None
                    obj.scene, obj.colors = sink.emit(
                        name=obj.name or f"object {obj.id}",
                        node=None,
                        scale_m=scale,
                        positions=positions,
                        triangles=triangles,
                        default=palette.colors[default_cid] if palette is not None else None,
                        palette=palette.colors if palette is not None else None,
                        color_ids=ids,
                    )
                positions, triangles, ids, palette, keymap = array("d"), array("I"), None, None, {}
                skip_mesh = False
            elif tag == _OBJECT:
                obj = None
            elif tag in (_BASEMATERIALS, _COLORGROUP) or tag in _NO_COLOR_GROUPS:
                group = None
                group_entry = None
        if refused:
            sink.warn(
                "part_reference_refused",
                f"{refused} components of a model part name another part, which only the root model may do; "
                "they are left out",
            )
        if groups_dropped:
            sink.warn(
                "colors_ignored", "the model defines more colours than are kept; the rest are not shown"
            )
        if textures:
            sink.warn(
                "textures_ignored", "textures are not read; textured triangles are drawn without colour"
            )

    def _new_group(self, groups: dict, a: dict) -> list:
        gid = a.get("id")
        if gid is None:
            raise SldFormatError("a property group has no id")
        if len(groups) >= self.limits.threemf_color_groups:
            raise self.limits.exceeded(
                "threemf_color_groups", f"the model has more than {self.limits.threemf_color_groups:,} groups"
            )
        group: list = []
        groups[gid] = group
        return group

    def _start_tag(self, member: str, clock: Clock) -> tuple[str, dict[str, str]]:
        """A part's root element: its qualified name and attributes, its namespace
        declarations included (parsed without namespaces, from its first chunks)."""
        head = HeadChunks(self._member(member, clock), HEAD_BYTES)
        for kind, tag, value in xml_events(head, self.limits, clock, namespaces=False):
            if head.past:
                break
            if kind == "start":
                return tag, value
        raise SldFormatError("a 3MF model part is empty")

    def _check_part(self, member: str, clock: Clock) -> None:
        """A non-root part is a 3MF model whose required extensions the reader implements."""
        tag, attrs = self._start_tag(member, clock)
        ns = {k[6:]: v for k, v in attrs.items() if k.startswith("xmlns:")}
        prefix, _, local = tag.rpartition(":")
        if local != "model" or (ns.get(prefix) if prefix else attrs.get("xmlns")) != CORE:
            raise SldFormatError("a part the model names is not a 3MF model")
        for uri in self._extensions(attrs.get("requiredextensions", ""), ns, attrs.get("xmlns")):
            if uri not in UNDERSTOOD:
                what = KNOWN_EXTENSIONS.get(uri, "an extension SolidSeas does not know")
                raise FormatNotSupportedError(
                    f"a model part requires {what}, which SolidSeas does not read",
                    detail={"rule": "required_extension", "value": uri[:200]},
                )

    # -- the build, expanded --------------------------------------------------------------
    def _settle(self, model: _Model) -> bool:
        """Whether the model is an assembly: the head's document type, settled from the full
        read ``model`` when the head left it unknown (and the head's counts with it)."""
        root = self.root
        most = max(
            (len(o.components) for (part, _i), o in model.objects.items() if part == root and o.components),
            default=0,
        )
        if self.doc_type is None:
            self.doc_type = "assembly" if len(model.items) > 1 or most > 1 else "part"
        if self._n_objects is None:
            self._n_objects = sum(1 for part, _i in model.objects if part == root)
            self._n_items = len(model.items)
        return self.doc_type == "assembly"

    def _layout(self, sink: MeshSink):
        """``(nodes, items, truncated)``: for a tree (``sink`` builds nothing) its nodes,
        stopped past ``limits.tree_nodes`` (then ``truncated``); for a scene ``(scene
        object, instance, placement)`` for each placed mesh. The build's items are
        expanded down their components, each placement counted against ``limits.items``."""
        model = self._read(sink)
        lim = self.limits
        tree = not sink.building
        nodes: list[ModelNode] = []
        items: list[tuple[int, str, Placement]] = []
        assembly = self._settle(model)
        if assembly and tree:
            title = self.fields.title or _stem(self.name)
            nodes.append(ModelNode("0", None, title, "assembly"))
        depth_max = lim.threemf_component_depth
        expanded = [0]

        def add(node: ModelNode) -> None:
            nodes.append(node)
            if len(nodes) > lim.tree_nodes:
                raise _Enough()

        def place(key, node, parent, local, world, depth, path, label):
            expanded[0] += 1
            if expanded[0] > lim.items:
                raise lim.exceeded("items", f"the build places more than {lim.items:,} objects")
            sink.clock.tick()
            obj = model.objects.get(key)
            if obj is None:
                if sink.sb is not None:
                    sink.sb.missing_component(
                        node, f"it names object {key[1][:20]!r}, which the model does not have"
                    )
                return
            if obj.type == "other":
                if sink.sb is not None:
                    sink.sb.skip(
                        node, "other_object", "it places an object of type other, which is never built"
                    )
                return
            if key in path:
                raise SldFormatError("the model's components place each other in a cycle")
            if depth > depth_max:
                raise lim.exceeded("threemf_component_depth", f"components nest deeper than {depth_max}")
            name = obj.name or label or f"object {obj.id}"
            if obj.components is None:
                if tree:
                    add(
                        ModelNode(
                            node,
                            parent,
                            name,
                            "object",
                            obj.scene[0] if obj.scene else None,
                            None,
                            local,
                            obj.colors[0] if obj.colors else None,
                        )
                    )
                else:
                    for i in obj.scene:
                        items.append((i, node, world))
                return
            if tree:
                add(ModelNode(node, parent, name, "component", None, None, local))
            for j, (part, oid, placement) in enumerate(obj.components, start=1):
                place(
                    (part, oid),
                    f"{node}.{j}",
                    node,
                    placement,
                    world.then(placement),
                    depth + 1,
                    (*path, key),
                    None,
                )

        try:
            for i, (part, oid, placement, number) in enumerate(model.items, start=1):
                label = clip_text(number, lim, None) if number else None
                place((part, oid), str(i), "0" if assembly else None, placement, placement, 1, (), label)
        except _Enough:
            return nodes, items, True
        return nodes, items, False

    def _tree(self, clock: Clock):
        nodes, _items, truncated = self._layout(MeshSink(None, self.limits, clock))
        return ModelTree(tuple(nodes), truncated)

    def _scene(self, sb: SceneBuilder) -> None:
        sink = MeshSink(sb, self.limits, sb.clock)
        _nodes, items, _t = self._layout(sink)
        for i, node, placement in items:
            sb.add_item(i, node, placement)
        sink.finish_scene()


class _Enough(Exception):
    """A tree has more nodes than ``limits.tree_nodes``: the layout stops there."""


def _property_color(groups: dict, pid: str | None, index: str | None):
    """The colour of entry ``index`` of property group ``pid``, or None."""
    if pid is None:
        return None
    group = groups.get(pid)
    if not group:
        return None
    try:
        i = int(index) if index is not None else 0
    except ValueError:
        return None
    return group[i] if 0 <= i < len(group) else None


def open(source, *, name, path, file_info, limits, hold_open=False, detection=None) -> ThreeMfDocument:
    """Open a 3MF package's :class:`~solidseas.formats._source.Source` (the registry's
    reader for ``3mf``)."""
    return ThreeMfDocument(
        source, name=name, path=path, file_info=file_info, limits=limits, detection=detection
    )


__all__ = ["CORE", "MATERIAL", "PRODUCTION", "REVISION", "ThreeMfDocument", "open", "transform"]
