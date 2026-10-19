"""An Alibre Design part or assembly as a :class:`~solidseas.formats.ModelDocument`
(provisional, ``docs/formats/alibre.md``, ``docs/API.md`` 3.20.8).

The head comes from the small streams: ``VERSION`` (the document's GUID and
version), ``PROP_DATA`` (properties, fields and the thumbnail),
``LIGHT_CONFIGURATION_DATA`` (the active configuration and the part's colour),
the header of ``SAB_DATA`` (the unit of length) and the dictionaries of
``MESH_DATA``. A part's triangles come from one of two sources:

* ``MESH_DATA``, Alibre's own display tessellation: read in milliseconds, the
  first choice of rendered previews and thumbnails (``scene(prefer="display")``),
  but not closed (its faces meet with cracks), so the fallback for printing;
* ``SAB_DATA``, the exact ACIS B-rep, mapped to an in-memory Parasolid transmit
  and tessellated by :mod:`solidseas.tessellate`: closed, the first choice of
  exports (``scene(prefer="bodies")``) and of :meth:`bodies`.

An assembly holds no geometry: its design database lists inclusions, each a
document named by GUID with a placement; :mod:`.resolve` finds the files.
``IMPORT_DATA`` (an imported body before any feature) is never read.
"""

import math
import os

from ...errors import (
    FileTooLargeError,
    FormatNotSupportedError,
    SldFormatError,
    SldLimitError,
    SolidSeasError,
)
from ...formats.solidworks.preview import Preview
from .._source import Clock, ReadCancelledError, bmp_size, clip_text
from ..acis import sab as sabmod
from ..acis.geometry import tessellation_limits
from ..base import (
    BodyRef,
    ExternalReference,
    ModelDocument,
    ModelNode,
    SceneBuilder,
    _stem,
    make_property,
)
from ..solidworks.components import IDENTITY, Placement
from ..solidworks.document import SummaryFields
from . import design as designmod
from . import identity as idmod
from . import light as lightmod
from . import mesh as meshmod
from . import props as propsmod
from .container import AlibreContainer, open_container
from .resolve import Resolver

REVISION = 1
SAB_HEAD = 1024
MESH_HEAD = 64 << 10
# Millimetres per model unit as the length tokens of model_summary.
_UNIT_TOKENS = {25.4: "in", 10.0: "cm", 1.0: "mm", 1000.0: "m", 304.8: "ft", 0.001: "micron"}
# Placements in an assembly's design database: centimetres (a hypothesis, docs/formats/alibre.md).
PLACEMENT_SCALE_M = 0.01


def _unit_token(mm: float) -> str | None:
    for k, v in _UNIT_TOKENS.items():
        if abs(mm - k) <= 1e-9 * k:
            return v
    return None


class AlibreDocument(ModelDocument):
    """One Alibre Design file (see the module notes)."""

    format = "alibre"

    def __init__(self, source, *, name, path, file_info, limits, detection=None) -> None:
        super().__init__(
            source, name=name, path=path, file_info=file_info, limits=limits, detection=detection
        )
        self.kind = "brep"
        self._design: designmod.DesignDatabase | None = None
        self._display: meshmod.DisplayMesh | None = None
        self._sab = None
        self._resolver: Resolver | None = None
        self._resolutions: dict[str, object] = {}
        self.c: AlibreContainer = open_container(source, limits)
        try:
            self._head()
        except BaseException:
            self.c.close()
            raise

    def close(self) -> None:
        try:
            self.c.close()
        finally:
            super().close()

    # -- head -------------------------------------------------------------------------
    def _stream_warning(self, name: str, exc: Exception) -> None:
        self.warn("stream_unreadable", f"the stream could not be read: {type(exc).__name__}", name)

    def _head(self) -> None:
        c = self.c
        ext_variant = self.variant
        # which kind of document: the streams decide, the extension only names sheet metal
        geometry = c.has("SAB_DATA") or c.has("MESH_DATA")
        if geometry:
            self.doc_type = "part"
            self.variant = "sheet_metal" if ext_variant == "sheet_metal" else "part"
        elif c.has("CONSTITUENTS"):
            self.doc_type = "assembly"
            self.variant = "assembly"
        else:
            kind = self.design().kind
            if kind == "assembly":
                self.doc_type, self.variant = "assembly", "assembly"
            elif kind == "part":
                self.doc_type, self.variant = "part", "part"
            else:
                raise FormatNotSupportedError(
                    "this Alibre Design document is neither a part nor an assembly (a drawing?)",
                    detail={"rule": "unsupported_variant", "value": "alibre"},
                )
        if self.variant == "sheet_metal":
            self.warn(
                "variant_unverified", "an Alibre sheet metal part is read as a part; this is not yet verified"
            )
        # identity
        self.identity: idmod.DocumentIdentity | None = None
        try:
            self.identity = idmod.read_version(c.read("VERSION"), self.limits)
        except SldLimitError:
            raise
        except (SldFormatError, SolidSeasError) as exc:
            self._stream_warning("VERSION", exc)
        # properties, fields, application, thumbnail
        self._snapshot: bytes | None = None
        self._read_props()
        # configuration and colour
        self.color = None
        if c.has("LIGHT_CONFIGURATION_DATA"):
            try:
                lc = lightmod.read(c.read("LIGHT_CONFIGURATION_DATA"))
                self.active_configuration = (
                    clip_text(lc.configuration, self.limits, self.warnings) if lc.configuration else None
                )
                self.color = lc.color
            except SldLimitError:
                raise
            except SolidSeasError as exc:
                self._stream_warning("LIGHT_CONFIGURATION_DATA", exc)
        # units: the SAB header, else MESH_DATA's string
        self.sab_header: sabmod.SabHeader | None = None
        self.mesh_header: meshmod.MeshHeader | None = None
        if c.has("SAB_DATA"):
            try:
                self.sab_header = sabmod.read_header(c.peek("SAB_DATA", SAB_HEAD), self.limits)
            except SldLimitError:
                raise
            except SolidSeasError as exc:
                self._stream_warning("SAB_DATA", exc)
        if c.has("MESH_DATA"):
            try:
                head = c.peek("MESH_DATA", MESH_HEAD)
                try:
                    self.mesh_header = meshmod.read_header(head, self.limits)
                except SldFormatError:
                    if len(head) >= c.sizes["MESH_DATA"]:
                        raise
                    self.mesh_header = meshmod.read_header(c.read("MESH_DATA"), self.limits)
            except SldLimitError:
                raise
            except SolidSeasError as exc:
                self._stream_warning("MESH_DATA", exc)
        self.scale_m: float | None = None
        mesh_scale = self.mesh_header.scale_m if self.mesh_header is not None else None
        sab_scale = None
        if (
            self.sab_header is not None
            and math.isfinite(self.sab_header.mm_per_unit)
            and self.sab_header.mm_per_unit > 0
        ):
            sab_scale = self.sab_header.mm_per_unit / 1000.0
        if sab_scale is not None:
            self.scale_m = sab_scale
            token = _unit_token(self.sab_header.mm_per_unit)
            self.units = {"length": token, "scale_m": sab_scale, "source": "file"}
            if mesh_scale is not None and abs(mesh_scale - sab_scale) > 1e-9 * sab_scale:
                self.warn(
                    "units_disagree",
                    "the display mesh names another unit of length than the B-rep; the B-rep's is used",
                    "MESH_DATA",
                )
        elif mesh_scale is not None:
            self.scale_m = mesh_scale
            token = _unit_token(mesh_scale * 1000.0)
            self.units = {"length": token, "scale_m": mesh_scale, "source": "file"}
        elif self.doc_type == "assembly":
            self.units = {"length": "cm", "scale_m": PLACEMENT_SCALE_M, "source": "assumed"}
        else:
            self.scale_m = 0.001
            self.set_units("mm", "assumed")
            self.warn("units_assumed", "the file states no unit of length; millimetres were assumed")
        if self.color is None and self.mesh_header is not None:
            self.color = self.mesh_header.color

    def _read_props(self) -> None:
        try:
            data = self.c.read("PROP_DATA")
        except SldLimitError:
            raise
        except SolidSeasError as exc:
            self._stream_warning("PROP_DATA", exc)
            return
        entries, error = propsmod.read(data, self.limits)
        if error is not None:
            if isinstance(error, SldLimitError):
                raise error
            self._stream_warning("PROP_DATA", error)
        by_key: dict[str, propsmod.PropEntry] = {}
        props = []
        for e in entries:
            by_key.setdefault(e.key, e)
            if e.key == propsmod.SNAPSHOT and e.type == propsmod.T_BLOB and e.values:
                self._snapshot = e.values[0]
            if not propsmod.shown(e.key) or not e.values or e.type == propsmod.T_BLOB:
                continue
            if len(props) >= self.limits.properties:
                raise self.limits.exceeded(
                    "properties", f"the file has more than {self.limits.properties:,} properties"
                )
            name = clip_text(e.key, self.limits, self.warnings, "a property name")
            if e.type == propsmod.T_STRING:
                value = clip_text("\n".join(e.values), self.limits, self.warnings, "a property value")
                props.append(make_property(name, value, type="text"))
            else:
                v = e.values[0] if len(e.values) == 1 else None
                if isinstance(v, float) and not math.isfinite(v):
                    v = None
                if v is not None:
                    props.append(make_property(name, v, type="number"))
        self.properties = props

        def text(key: str) -> str | None:
            e = by_key.get(key)
            if e is None or e.type != propsmod.T_STRING or not e.values or not e.values[0]:
                return None
            return clip_text(e.values[0], self.limits, self.warnings)

        created, saved = text("Creation_Time"), text("Last_Modification_Time")
        self.fields = SummaryFields(
            title=text("name"),
            author=text("Creation_Author"),
            comments=text("description"),
            last_saved_by=text("Last_Modification_Author"),
            created_utc=propsmod.parse_time(created) if created else None,
            last_saved_utc=propsmod.parse_time(saved) if saved else None,
        )
        version = text("stepFileVersion")
        self.application = {
            "name": "Alibre Design",
            "version": propsmod.application_version(version) if version else None,
        }

    # -- full reads -------------------------------------------------------------------
    def design(self) -> designmod.DesignDatabase:
        """The design database (read once)."""
        if self._design is None:
            self._design = designmod.read(self.c.read("STEP_DATA"), self.limits, Clock(self.limits.seconds))
            if self._design.kind == "assembly" and any(any(inc.origin) for inc in self._design.inclusions):
                self.warn(
                    "placement_unit_assumed",
                    "the assembly's placements are read in centimetres, which the file does not confirm",
                    "STEP_DATA",
                )
        return self._design

    def _clock(self, clock: Clock | None) -> Clock:
        """A clock for reading one stream: ``limits.seconds``, or the caller's ``clock``
        when that ends first."""
        return Clock(self.limits.seconds) if clock is None else clock.child(self.limits.seconds)

    def display_mesh(self, clock: Clock | None = None) -> meshmod.DisplayMesh:
        """The whole ``MESH_DATA`` (read once)."""
        if self._display is None:
            self._display = meshmod.read(self.c.read("MESH_DATA"), self.limits, self._clock(clock))
        return self._display

    def sab(self, clock: Clock | None = None):
        """The ACIS model of ``SAB_DATA`` (read once); ``SldFormatError`` with rule
        ``acis_version`` when its layouts are not the verified ones."""
        if self._sab is None:
            from ..acis.entities import Model

            if self.sab_header is None:
                raise SldFormatError("the part has no readable ACIS body", detail={"stream": "SAB_DATA"})
            if not self.sab_header.verified:
                raise SldFormatError(
                    "the part's ACIS data is of a version whose layout is not verified",
                    detail={"stream": "SAB_DATA", "rule": "acis_version"},
                )
            data = self.c.read("SAB_DATA")
            self._sab = Model(sabmod.read(data, self.limits, self._clock(clock)), self.limits)
        return self._sab

    def _counts(self):
        if self.doc_type == "part":
            out = {"objects": 1, "items": 1, "bodies": 1 if self.c.has("SAB_DATA") else 0}
            if self.mesh_header is not None:
                out["faces"] = self.mesh_header.faces
            return out
        out = {"components": None, "references": None}
        try:
            out["components"] = len(self.design().inclusions)
        except SldLimitError:
            raise
        except SolidSeasError:
            pass
        try:
            out["references"] = len({x.guid for x in self.constituents()})
        except SldLimitError:
            raise
        except SolidSeasError:
            pass
        return out

    def constituents(self) -> list[idmod.DocumentIdentity]:
        if not self.c.has("CONSTITUENTS"):
            return []
        return idmod.read_constituents(self.c.read("CONSTITUENTS"), self.limits)

    def _preview(self):
        data = self._snapshot
        if not data:
            return None
        size = bmp_size(data)
        if size is None:
            raise SldFormatError(
                "the stored thumbnail is not a Windows bitmap", detail={"stream": "PROP_DATA"}
            )
        w, h = size
        if not (0 < w <= self.limits.image_side and 0 < h <= self.limits.image_side):
            raise SldFormatError(
                "the stored thumbnail's size is out of range", detail={"limit": "image_side"}
            )
        if len(data) > self.limits.image_bytes:
            raise SldFormatError("the stored thumbnail is too large", detail={"limit": "image_bytes"})
        return Preview(data, "image/bmp", w, h, "PROP_DATA")

    # -- tree ---------------------------------------------------------------------------
    def _tree(self, clock: Clock):
        stem = _stem(self.name)
        if self.doc_type == "part":
            return [ModelNode("1", None, stem, "object", 0, color=self.color)]
        nodes = [ModelNode("1", None, stem, "assembly")]
        for k, inc in enumerate(self.design().inclusions):
            clock.tick()
            res = self.resolution(inc.guid, inc.version, inc.stored_name)
            name = None
            if res.path:
                name = os.path.splitext(os.path.basename(res.path))[0]
            nodes.append(
                ModelNode(
                    str(k + 2),
                    "1",
                    clip_text(name or inc.stored_name or inc.guid, self.limits, None),
                    "component",
                    file=inc.guid,
                    placement=inc.placement(PLACEMENT_SCALE_M),
                )
            )
        return nodes

    # -- references -----------------------------------------------------------------------
    def resolver(self, roots: tuple[str, ...] = ()) -> Resolver:
        if self._resolver is None or self._resolver.roots != tuple(os.path.abspath(r) for r in roots if r):
            folder = os.path.dirname(os.path.abspath(self.path)) if self.path else None
            self._resolver = Resolver(
                folder, roots, self.limits, exclude=self.path, refuse_hard_links=self.refuse_hard_links
            )
            self._resolutions = {}
        return self._resolver

    def resolution(
        self, guid: str, version: int | None, stored_name: str | None, roots: tuple[str, ...] = ()
    ):
        r = self.resolver(roots)
        hit = self._resolutions.get(guid)
        if hit is None:
            hit = self._resolutions[guid] = r.resolve(guid, version, stored_name)
        return hit

    def _references(self, clock: Clock):
        if self.doc_type != "assembly":
            return []
        out: list[ExternalReference] = []
        seen: set[str] = set()
        incs = self.design().inclusions
        listed = set()
        try:
            listed = {x.guid for x in self.constituents()}
        except SldLimitError:
            raise
        except SolidSeasError as exc:
            self._stream_warning("CONSTITUENTS", exc)
        if listed and listed != {i.guid for i in incs}:
            if not any(w.code == "constituents_disagree" for w in self.warnings):
                self.warn(
                    "constituents_disagree", "CONSTITUENTS lists other documents than the assembly places"
                )
        for inc in incs:
            clock.tick()
            if inc.guid in seen:
                continue
            seen.add(inc.guid)
            res = self.resolution(inc.guid, inc.version, inc.stored_name)
            for w in res.warnings:
                if not any(x.code == w.code for x in self.warnings):
                    self.warnings.append(w)
            out.append(
                ExternalReference(
                    inc.guid,
                    "component",
                    clip_text(inc.stored_path, self.limits, None) if inc.stored_path else None,
                    clip_text(inc.stored_name, self.limits, None) if inc.stored_name else None,
                    {
                        "status": res.status,
                        "path": res.rel if res.within == self.resolver().folder else res.path,
                        "found_by": res.found_by,
                        "version": None if res.version is None else str(res.version),
                    },
                )
            )
        return out

    # -- geometry ---------------------------------------------------------------------------
    def _bodies(self, clock: Clock):
        if self.doc_type != "part":
            return None
        if not self.c.has("SAB_DATA"):
            return []
        build = self.body_build(clock)
        return [BodyRef(_stem(self.name), build.transmit, self._color(build), "1", build.body_type)]

    def _color(self, build=None):
        if self.color is not None:
            return self.color
        return build.color if build is not None else None

    def body_build(self, clock: Clock):
        """The ACIS body as a :class:`~..acis.geometry.BodyBuild` (raises when it cannot be
        mapped at all)."""
        from ..acis.entities import AcisError
        from ..acis.geometry import bodies, build_body

        m = self.sab(clock)
        found = bodies(m)
        if not found:
            raise SldFormatError("the ACIS data holds no body", detail={"stream": "SAB_DATA"})
        if len(found) > 1 and not any(w.code == "bodies_left_out" for w in self.warnings):
            self.warn("bodies_left_out", f"the ACIS data holds {len(found)} bodies; the first is read")
        try:
            return build_body(m, found[0], self.limits, clock, label=_stem(self.name) or "body")
        except AcisError as exc:
            raise SldFormatError(
                f"the ACIS body could not be mapped: {exc}", detail={"stream": "SAB_DATA"}
            ) from None

    def _scene(self, sb: SceneBuilder) -> None:
        if self.doc_type == "part":
            obj = self.part_object(sb, sb.options.prefer, node="1")
            if obj is not None:
                sb.add_item(obj, "1")
            return
        self._assembly(sb)

    def part_object(self, sb: SceneBuilder, prefer: str, node: str | None) -> int | None:
        """Add this part's mesh object to ``sb`` from the preferred source, falling back to
        the other; None when neither gives triangles."""
        order = ("display", "bodies") if prefer == "display" else ("bodies", "display")
        why = []
        for source in order:
            try:
                if source == "display":
                    if not self.c.has("MESH_DATA"):
                        why.append("the part stores no display mesh")
                        continue
                    got = self._display_object(sb, node)
                else:
                    if not self.c.has("SAB_DATA"):
                        why.append("the part stores no B-rep")
                        continue
                    got = self._bodies_object(sb, node)
            except (SldLimitError, ReadCancelledError):
                raise  # a bound or a cancel ends the scene; it is not a damaged stream
            except SolidSeasError as exc:
                if isinstance(exc, SldFormatError) and (exc.detail or {}).get("rule") == "acis_version":
                    if not any(w.code == "acis_version_unverified" for w in sb.warnings):
                        sb.warn(
                            "acis_version_unverified",
                            "the part's ACIS data is of a version whose layout is not verified; "
                            "its display mesh is used instead",
                            "SAB_DATA",
                        )
                else:
                    sb.warn("stream_unreadable", f"the part's {source} could not be read: {exc}"[:300])
                why.append(str(exc))
                continue
            if got is not None:
                return got
        return None

    def _display_object(self, sb: SceneBuilder, node: str | None) -> int | None:
        dm = self.display_mesh(sb.clock)
        if not dm.triangles:
            return None
        scale = self.scale_m or 0.001
        mb = sb.mesh(name=_stem(self.name), source="display_mesh", scale_m=scale, color=self.color, node=node)
        mb.add_vertices(dm.positions)
        mb.add_triangles(dm.triangles)
        mb.set_normals(dm.normals)
        return mb.finish()

    def _bodies_object(self, sb: SceneBuilder, node: str | None) -> int | None:
        from ...tessellate import tessellate_transmit

        build = self.body_build(sb.clock)
        left = sb.clock.left()
        opts = sb.options.tessellation()
        cap = sb.options.max_triangles
        max_tris = self.limits.triangles if cap is None else min(self.limits.triangles, cap + 1)
        tess = tessellate_transmit(
            build.transmit,
            max_seconds=max(0.0, left) if left is not None else sb.options.max_seconds,
            max_triangles=max_tris,
            **opts,
        )
        sb.skipped.extend(build.skipped)
        sb.skipped.extend(tess.skipped)
        for w in build.warnings:
            if w.code != "faces_left_out":
                sb.warnings.append(w)
        sb.counts["bodies"] = (sb.counts.get("bodies") or 0) + 1
        sb.counts["faces"] = (sb.counts.get("faces") or 0) + build.faces
        sb.counts["faces_done"] = (sb.counts.get("faces_done") or 0) + tess.counts.get("faces_done", 0)
        tessellation_limits(sb, tess, self.limits)
        positions, triangles = tess.welded()
        if not triangles:
            return None
        mb = sb.mesh(name=_stem(self.name), source="bodies", scale_m=1.0, color=self._color(build), node=node)
        mb.add_vertices(positions)
        mb.add_triangles(triangles)
        return mb.finish()

    # -- assemblies ----------------------------------------------------------------------------
    def _assembly(self, sb: SceneBuilder) -> None:
        state = _AssemblyState(self, sb)
        try:
            state.place(self, IDENTITY, None, 0, frozenset({self.identity.guid} if self.identity else ()))
        finally:
            state.close()
        sb.counts["components"] = state.opened
        if state.missing_by_limit:
            sb.warn(
                "instances_left_out", f"{state.missing_by_limit} components were left out: too many documents"
            )
        if state.resolver_truncated:
            sb.warn("component_not_found", "the search for component files stopped at a limit")


class _AssemblyState:
    """The documents one assembly scene opens, and their objects."""

    def __init__(self, top: AlibreDocument, sb: SceneBuilder) -> None:
        self.top = top
        self.sb = sb
        self.roots = sb.options.roots
        self.docs: dict[str, AlibreDocument | None] = {}
        self.objects: dict[str, int | None] = {}
        self.opened = 0
        self.missing_by_limit = 0
        self.resolver_truncated = False

    def close(self) -> None:
        for d in self.docs.values():
            if d is not None:
                d.close()

    def _open(self, path: str, within: str) -> tuple["AlibreDocument | None", str]:
        """The component document at ``path`` (opened once, under the rules the top
        assembly was opened with: ``refuse_hard_links`` and ``max_file_bytes``), or None
        and why: ``limit`` (``components`` reached) or ``unreadable``."""
        from ..base import open_model

        key = os.path.normcase(os.path.abspath(path))
        if key in self.docs:
            doc = self.docs[key]
            return doc, "" if doc is not None else "unreadable"
        if self.opened >= self.top.limits.components:
            self.missing_by_limit += 1
            return None, "limit"
        self.opened += 1
        try:
            doc = open_model(
                path,
                within=within,
                format="alibre",
                limits=self.top.limits,
                refuse_hard_links=self.top.refuse_hard_links,
                max_file_bytes=self.top.max_file_bytes,
            )
        except FileTooLargeError:  # this component's own file is over the caller's limit: left out
            doc = None
        except SldLimitError:
            raise
        except (SolidSeasError, OSError):
            doc = None
        if doc is not None and not isinstance(doc, AlibreDocument):
            doc.close()
            doc = None
        self.docs[key] = doc
        return doc, "" if doc is not None else "unreadable"

    def place(
        self, asm: AlibreDocument, placement: Placement, top_node: str | None, depth: int, path_guids
    ) -> None:
        sb = self.sb
        if depth >= asm.limits.depth:
            raise asm.limits.exceeded("depth", "the assembly's sub-assemblies nest too deeply")
        db = asm.design()
        if db.skipped and depth == 0:
            for _ in range(db.skipped):
                sb.missing_component(None, "an inclusion of the design database could not be read")
        for k, inc in enumerate(db.inclusions):
            sb.clock.tick()
            node = str(k + 2) if top_node is None else top_node
            if inc.guid in path_guids:
                sb.skip(node, "cycle", "an assembly includes itself")
                continue
            if depth == 0:
                res = self.top.resolution(inc.guid, inc.version, inc.stored_name, self.roots)
                resolver = self.top._resolver
            else:  # a sub-assembly's components: near it first, then the top's folder and the roots
                top_folder = os.path.dirname(os.path.abspath(self.top.path)) if self.top.path else None
                extra = self.roots + ((top_folder,) if top_folder else ())
                res = asm.resolution(inc.guid, inc.version, inc.stored_name, extra)
                resolver = asm._resolver
            if resolver is not None and resolver.truncated:
                self.resolver_truncated = True
            for w in res.warnings:
                if not any(x.code == w.code for x in sb.warnings):
                    sb.warnings.append(w)
            if res.status != "found":
                sb.missing_component(node, "a component document was not found")
                continue
            here = placement.then(inc.placement(PLACEMENT_SCALE_M))
            doc, why = self._open(res.path, res.within)
            if doc is None:
                if why == "limit":
                    sb.skip(node, "components_limit", "too many component documents")
                else:
                    sb.missing_component(node, "a component document could not be read")
                continue
            if doc.doc_type == "assembly":
                self.place(doc, here, node, depth + 1, path_guids | {inc.guid})
                continue
            key = os.path.normcase(os.path.abspath(res.path))
            if key not in self.objects:
                self.objects[key] = doc.part_object(sb, sb.options.prefer, node)
            obj = self.objects[key]
            if obj is None:
                sb.missing_component(node, "a component part holds no geometry SolidSeas can read")
                continue
            sb.add_item(obj, node, here)


def open(source, *, name, path, file_info, limits, hold_open=False, detection=None) -> AlibreDocument:
    """Open an Alibre Design file's :class:`~solidseas.formats._source.Source` (the
    registry's reader for ``alibre``)."""
    return AlibreDocument(
        source, name=name, path=path, file_info=file_info, limits=limits, detection=detection
    )


__all__ = ["PLACEMENT_SCALE_M", "REVISION", "AlibreDocument", "open"]
