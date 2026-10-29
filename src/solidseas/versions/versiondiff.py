"""What changed between two versions of a file (provisional, ``docs/VERSIONS.md`` 5 and 6).

A version is compared on what it holds, never on its bytes alone (SOLIDWORKS writes
different bytes at every save of an unchanged model):

* **The document**: its type, saved version, units, summary fields, material, active
  configuration and preview, from the summary every surface builds
  (:func:`solidseas.model.build_document_summary`, ``build_model_summary`` for other
  formats).
* **Properties**: each file and configuration property, added, removed or changed in
  type, value, text, expression or link.
* **Configurations**: added and removed, and each one's comment and material.
* **Geometry**, per configuration of a part (once for a model file): how many bodies of
  each type, faces, edges and vertices, and a fingerprint of the B-rep. The fingerprint
  is the SHA-256 of the bodies' topology and geometry in a canonical form: nodes keyed
  by type and node id as :func:`~solidseas.formats.solidworks.parasolid.compare_brep`
  matches them, every field but attributes, links and numbering, nodes with no id of
  their own written in place, and bodies sorted, so the same model saved again keeps its
  fingerprint (fixtures o02 and o03 differ in their stored bytes, not in it). Where two
  fingerprints differ, both versions are measured: volume, area and box of the shown
  solid bodies, from their tessellation (:mod:`solidseas.tessellate`) at its default
  tolerance, within a shared time limit. A mesh file is fingerprinted from its triangles.

Assemblies and drawings are compared on the document, properties and configurations;
their geometry is not compared yet.
"""

from __future__ import annotations

import hashlib
import math
import time
from typing import Any

from .. import model
from ..errors import ReaderWarning
from ..formats import open_any
from ..formats.base import ModelDocument

DEFAULT_MAX_SECONDS = 60.0  # measuring both versions, together
BODY_KINDS = ("solid", "sheet", "wire", "general")
_DOC_FIELDS = ("title", "subject", "author", "keywords", "comments")
_UNIT_FIELDS = ("system", "length", "mass", "angle", "scale_m")
_PROPERTY_FIELDS = ("type", "value", "date", "text", "expression", "linked")
# Mirrors compare_brep: what never says anything about the shape (links between nodes of a
# list, numbering, attributes, index maps).
_SKIP_FIELDS = frozenset(
    {
        "attributes_features",
        "attribute_chains",
        "highest_node_id",
        "next",
        "previous",
        "owner",
        "index_map_offset",
        "index_map",
        "node_id_index_map",
        "schema_embedding_map",
        "lowest_node_id",
        "mesh_offset_data",
        "node_id",
    }
)
_INLINE_DEPTH = 8
_REL = 1e-9  # a measure that moved less than this, relative, did not change


# --------------------------------------------------------------------------- fingerprints
def _canon(value: Any) -> str:
    if isinstance(value, bool):
        return "T" if value else "F"
    if isinstance(value, float):
        return value.hex()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, (bytes, bytearray)):
        return "b" + bytes(value).hex()
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canon(v) for v in value) + "]"
    if value is None:
        return "N"
    return "?" + type(value).__name__


def body_fingerprint(xt) -> str:
    """The SHA-256 of one body transmit's topology and geometry in canonical form (see the
    module notes): the same for the same B-rep however its nodes are numbered and
    whatever attributes it carries."""
    from ..formats.solidworks.parasolid import _MODEL_TYPES

    names = {t: [f[0] for f in xt.layouts[t]] for t in xt.layouts}
    idx = xt.by_index()
    key: dict[int, tuple] = {}
    for n in xt.nodes:
        fields = names.get(n.type, ())
        if n.tname in _MODEL_TYPES and "node_id" in fields:
            key[n.index] = (n.tname, n.vals[fields.index("node_id")])
    for n in xt.nodes:
        if n.tname == "BODY":
            key[n.index] = ("BODY",)
    for n in xt.nodes:
        if n.tname == "HALFEDGE":
            fields = names.get(n.type, ())
            edge = n.vals[fields.index("edge")] if "edge" in fields else None
            loop = n.vals[fields.index("loop")] if "loop" in fields else None
            key[n.index] = ("HALFEDGE", key.get(edge), key.get(loop))

    def pointer(target: Any, depth: int, seen: frozenset) -> str:
        if not target:
            return "0"
        if not isinstance(target, int):
            return _canon(target)
        if target in key:
            return "@" + repr(key[target])
        node = idx.get(target)
        if node is None or node.tname not in _MODEL_TYPES or depth >= _INLINE_DEPTH or target in seen:
            return "<other>"
        return "{" + node_text(node, depth + 1, seen | {target}) + "}"

    def node_text(node, depth: int, seen: frozenset) -> str:
        parts = [node.tname]
        for f, v in zip(xt.layouts.get(node.type, ()), node.vals, strict=False):
            name, kind = f[0], f[1]
            if name in _SKIP_FIELDS:
                continue
            if kind == "p":
                text = (
                    "[" + ",".join(pointer(x, depth, seen) for x in v) + "]"
                    if isinstance(v, (list, tuple))
                    else pointer(v, depth, seen)
                )
            else:
                text = _canon(v)
            parts.append(f"{name}={text}")
        return ";".join(parts)

    rows = sorted((repr(k), node_text(idx[i], 0, frozenset({i}))) for i, k in key.items() if i in idx)
    h = hashlib.sha256()
    for k, text in rows:
        h.update(k.encode("utf-8", "surrogatepass"))
        h.update(b"\n")
        h.update(text.encode("utf-8", "surrogatepass"))
        h.update(b"\n\n")
    return h.hexdigest()


def _combined(digests: list[str]) -> str:
    h = hashlib.sha256()
    for d in sorted(digests):
        h.update(d.encode("ascii"))
    return h.hexdigest()


def _brep_summary(bodies: list[tuple[str | None, Any]]) -> dict[str, Any]:
    """Counts and fingerprint of some bodies: ``(body type, transmit)`` pairs."""
    from ..formats.solidworks.parasolid import body_hidden

    kinds = dict.fromkeys(BODY_KINDS, 0)
    hidden = faces = edges = vertices = 0
    digests = []
    for body_type, xt in bodies:
        kind = body_type if body_type in kinds else "general"
        kinds[kind] += 1
        root = next((n for n in xt.nodes if n.tname == "BODY"), None)
        if root is not None and body_hidden(xt, root) is True:
            hidden += 1
        for n in xt.nodes:
            if n.tname == "FACE":
                faces += 1
            elif n.tname == "EDGE":
                edges += 1
            elif n.tname == "VERTEX":
                vertices += 1
        digests.append(body_fingerprint(xt))
    return {
        "stored": True,
        "bodies": kinds,
        "hidden_bodies": hidden,
        "faces": faces,
        "edges": edges,
        "vertices": vertices,
        "triangles": None,
        "fingerprint": _combined(digests),
        "measures": None,
    }


def _not_stored() -> dict[str, Any]:
    return {
        "stored": False,
        "bodies": None,
        "hidden_bodies": None,
        "faces": None,
        "edges": None,
        "vertices": None,
        "triangles": None,
        "fingerprint": None,
        "measures": None,
    }


def _mesh_summary(scene) -> dict[str, Any]:
    h = hashlib.sha256()
    triangles = 0
    for obj in scene.objects:
        h.update(b"object\n")
        h.update(obj.positions.typecode.encode("ascii") + obj.positions.tobytes())
        h.update(obj.triangles.typecode.encode("ascii") + obj.triangles.tobytes())
    for item in scene.items:
        p = item.placement
        h.update(f"item {item.object} {[list(r) for r in p.rotation]} {list(p.translation_m)}\n".encode())
        triangles += scene.objects[item.object].n_triangles if 0 <= item.object < len(scene.objects) else 0
    out = _not_stored()
    out.update({"stored": True, "triangles": triangles, "fingerprint": h.hexdigest()})
    return out


# --------------------------------------------------------------------------- measures
def _mm(value: float | None, power: int = 1) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return value * 1000.0**power


def _box_mm(box) -> dict[str, Any] | None:
    if box is None:
        return None
    lo, hi = box
    low = [_mm(v) for v in lo]
    high = [_mm(v) for v in hi]
    if any(v is None for v in (*low, *high)):
        return None
    return {"min": low, "max": high, "size": [h - lo_ for lo_, h in zip(low, high, strict=True)]}


def _no_measures(reason: str) -> dict[str, Any]:
    return {
        "measured": False,
        "reason": reason,
        "volume_mm3": None,
        "area_mm2": None,
        "box_mm": None,
        "closed": None,
        "complete": False,
        "chord_mm": None,
    }


def _ran_out(result) -> str | None:
    """``max_seconds`` when the time limit cut ``result`` (a tessellation or a scene)
    short, else None."""
    return "max_seconds" if result is not None and "max_seconds" in result.truncated else None


def _measure_part(doc, configuration: str | None, deadline: float) -> dict[str, Any]:
    """Volume, area and box of a part configuration's shown solid bodies."""
    from ..tessellate import tessellate_document

    left = deadline - time.monotonic()
    if left <= 0:
        return _no_measures("max_seconds")
    t = tessellate_document(doc, configuration, body_types=("solid",), include_hidden=False, max_seconds=left)
    if t is None or not t.counts.get("bodies"):
        # a read the time ran out in has no bodies yet: that is the time, not the part
        return _no_measures(_ran_out(t) or "no_solid_bodies")
    m = t.measures()
    complete = not t.truncated and not t.counts.get("faces_skipped") and not t.counts.get("bodies_skipped")
    return {
        "measured": True,
        "reason": None if complete else "incomplete",
        "volume_mm3": _mm(m.get("volume"), 3),
        "area_mm2": _mm(m.get("area"), 2),
        "box_mm": _box_mm(m.get("box")),
        "closed": t.closed,
        "complete": complete,
        "chord_mm": _mm(t.chord_m),
    }


def _measure_model(doc, deadline: float, *, bodies: bool) -> dict[str, Any]:
    """Volume, area and box of a model file's scene: each object's measures, placed."""
    from ..export import mesh_measures

    left = deadline - time.monotonic()
    if left <= 0:
        return _no_measures("max_seconds")
    scene = doc.scene(prefer="bodies" if bodies else "display", body_types=("solid",), max_seconds=left)
    if not scene.items:
        return _no_measures(_ran_out(scene) or "no_solid_bodies")
    volume = area = 0.0
    low = [math.inf] * 3
    high = [-math.inf] * 3
    per_object: dict[int, dict] = {}
    for item in scene.items:
        if not 0 <= item.object < len(scene.objects):
            continue
        obj = scene.objects[item.object]
        m = per_object.get(item.object)
        if m is None:
            m = per_object[item.object] = mesh_measures(obj.positions, obj.triangles)
        volume += m["volume_m3"]
        area += m["area_m2"]
        if m["box"] is not None:
            (x0, y0, z0), (x1, y1, z1) = m["box"]
            for x in (x0, x1):
                for y in (y0, y1):
                    for z in (z0, z1):
                        q = item.placement.apply((x, y, z))
                        for k in range(3):
                            low[k] = min(low[k], q[k])
                            high[k] = max(high[k], q[k])
    box = (tuple(low), tuple(high)) if all(math.isfinite(v) for v in (*low, *high)) else None
    complete = not scene.truncated and not scene.skipped
    return {
        "measured": True,
        "reason": None if complete else "incomplete",
        "volume_mm3": _mm(volume, 3),
        "area_mm2": _mm(area, 2),
        "box_mm": _box_mm(box),
        "closed": None,
        "complete": complete,
        "chord_mm": None,
    }


# --------------------------------------------------------------------------- one version
class Side:
    """One version opened from its bytes: its summary and geometry, measured on demand."""

    def __init__(self, data: bytes, name: str) -> None:
        self.doc = open_any(data, name=name)
        self._bodies = False  # a model file's geometry came from B-rep bodies
        try:
            self.model = isinstance(self.doc, ModelDocument)
            if self.model:
                self.summary = model.build_model_summary(self.doc, include=("properties",))
            else:
                self.summary = model.build_document_summary(self.doc)
            self.geometry_reason, self.geometry, self.warnings = self._geometry()
        except BaseException:
            self.doc.close()
            raise

    def close(self) -> None:
        self.doc.close()

    def __enter__(self) -> Side:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @property
    def doc_type(self) -> str | None:
        return self.summary.get("doc_type")

    def _geometry(self) -> tuple[str | None, dict[str | None, dict[str, Any]], list[dict[str, Any]]]:
        """``(why there is none, {configuration: summary}, warnings)``."""
        from ..tessellate import bodies_of

        warnings: list[dict[str, Any]] = []
        doc = self.doc
        if self.model:
            refs = doc.bodies()
            if refs:
                self._bodies = True
                return None, {None: _brep_summary([(r.body_type, r.transmit) for r in refs])}, warnings
            self._bodies = False
            if doc.kind not in ("mesh", "mixed"):
                return "no_geometry", {}, warnings
            return None, {None: _mesh_summary(doc.scene(prefer="display"))}, warnings
        if doc.doc_type != "part":
            return doc.doc_type or "no_geometry", {}, warnings
        out: dict[str | None, dict[str, Any]] = {}
        for cfg in doc.configurations:
            _name, bodies, reader, _n = bodies_of(doc, cfg.name)
            for w in reader:
                if isinstance(w, ReaderWarning) and w.code != "no_stored_bodies":
                    warnings.append(w.to_dict())
            out[cfg.name] = (
                _brep_summary([(b.body_type, b.transmit) for b in bodies]) if bodies else _not_stored()
            )
        return None, out, warnings

    def measure(self, configuration: str | None, deadline: float) -> dict[str, Any]:
        if self.model:
            return _measure_model(self.doc, deadline, bodies=self._bodies)
        return _measure_part(self.doc, configuration, deadline)


# --------------------------------------------------------------------------- the differences
def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _change(name: str, configuration: str | None, a: Any, b: Any) -> dict[str, Any]:
    return {"field": name, "configuration": configuration, "from": _text(a), "to": _text(b)}


def _material_name(m: Any) -> str | None:
    return m.get("name") if isinstance(m, dict) else None


def _document_changes(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for key in ("format", "doc_type"):
        if a.get(key) != b.get(key):
            out.append(_change("type" if key == "doc_type" else key, None, a.get(key), b.get(key)))
    sa, sb = a.get("saved_version") or {}, b.get("saved_version") or {}
    if (sa.get("release"), sa.get("format_version")) != (sb.get("release"), sb.get("format_version")):
        out.append(_change("saved_version", None, sa.get("release"), sb.get("release")))
    ua, ub = a.get("units") or {}, b.get("units") or {}
    for key in _UNIT_FIELDS:  # a SOLIDWORKS document's, or a model file's length and scale
        if ua.get(key) != ub.get(key):
            out.append(_change(f"units.{key}", None, ua.get(key), ub.get(key)))
    fa, fb = a.get("fields") or {}, b.get("fields") or {}
    for key in _DOC_FIELDS:
        if fa.get(key) != fb.get(key):
            out.append(_change(key, None, fa.get(key), fb.get(key)))
    # a document with configurations says its material in each of them (below)
    configured = bool(a.get("configurations") or b.get("configurations"))
    if not configured and _material_name(a.get("material")) != _material_name(b.get("material")):
        out.append(
            _change("material", None, _material_name(a.get("material")), _material_name(b.get("material")))
        )
    if a.get("active_configuration") != b.get("active_configuration"):
        out.append(
            _change(
                "active_configuration", None, a.get("active_configuration"), b.get("active_configuration")
            )
        )
    ca = {c["name"]: c for c in a.get("configurations") or ()}
    cb = {c["name"]: c for c in b.get("configurations") or ()}
    for name in ca:
        if name not in cb:
            continue
        if ca[name].get("comment") != cb[name].get("comment"):
            out.append(_change("comment", name, ca[name].get("comment"), cb[name].get("comment")))
        ma, mb = _material_name(ca[name].get("material")), _material_name(cb[name].get("material"))
        if ma != mb:
            out.append(_change("material", name, ma, mb))
    pa, pb = a.get("preview") or {}, b.get("preview") or {}
    if pa.get("sha256") != pb.get("sha256"):
        out.append(_change("preview", None, pa.get("sha256"), pb.get("sha256")))
    return out


def _properties(summary: dict[str, Any]) -> dict[tuple[str | None, str], dict[str, Any]]:
    out: dict[tuple[str | None, str], dict[str, Any]] = {}
    for p in summary.get("properties") or ():
        out[(None, p["name"])] = p
    for c in summary.get("configurations") or ():
        for p in c.get("properties") or ():
            out[(c["name"], p["name"])] = p
    return out


def _property_changes(a: dict[str, Any], b: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    pa, pb = _properties(a), _properties(b)
    added, removed, changed = [], [], []
    for key in sorted(set(pa) | set(pb), key=lambda k: (k[0] is not None, k[0] or "", k[1])):
        cfg, name = key
        x, y = pa.get(key), pb.get(key)
        row = {"configuration": cfg, "name": name, "from": x, "to": y}
        if x is None:
            added.append(row)
        elif y is None:
            removed.append(row)
        elif any(x.get(f) != y.get(f) for f in _PROPERTY_FIELDS):
            changed.append(row)
    return {"added": added, "removed": removed, "changed": changed}


def _configuration_changes(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    na = [c["name"] for c in a.get("configurations") or ()]
    nb = [c["name"] for c in b.get("configurations") or ()]
    return {
        "added": [n for n in nb if n not in na],
        "removed": [n for n in na if n not in nb],
        "active": {"from": a.get("active_configuration"), "to": b.get("active_configuration")},
    }


def _close(x: float, y: float) -> bool:
    return x == y or abs(x - y) <= _REL * max(abs(x), abs(y), 1e-12)


def _measure_changes(fa: dict[str, Any], fb: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for kind in BODY_KINDS:
        x = (fa.get("bodies") or {}).get(kind)
        y = (fb.get("bodies") or {}).get(kind)
        if x != y and x is not None and y is not None:
            out.append({"measure": f"{kind}_bodies", "from": x, "to": y})
    for key in ("hidden_bodies", "faces", "edges", "vertices", "triangles"):
        x, y = fa.get(key), fb.get(key)
        if x != y and x is not None and y is not None:
            out.append({"measure": key, "from": x, "to": y})
    ma, mb = fa.get("measures") or {}, fb.get("measures") or {}
    if ma.get("measured") and mb.get("measured") and ma.get("complete") and mb.get("complete"):
        for key in ("volume_mm3", "area_mm2"):
            x, y = ma.get(key), mb.get(key)
            if x is not None and y is not None and not _close(x, y):
                out.append({"measure": key, "from": x, "to": y})
        ba, bb = ma.get("box_mm"), mb.get("box_mm")
        if ba and bb:
            for part, label in (("size", "size"), ("min", "min")):
                for axis, k in (("x", 0), ("y", 1), ("z", 2)):
                    x, y = ba[part][k], bb[part][k]
                    if not _close(x, y) and abs(x - y) > 1e-9:
                        out.append({"measure": f"{label}_{axis}_mm", "from": x, "to": y})
    return out


def compare_sides(
    a: Side, b: Side, *, measure: bool = True, max_seconds: float = DEFAULT_MAX_SECONDS
) -> dict:
    """The differences between two opened versions: ``document``, ``properties``,
    ``configurations``, ``geometry`` and ``warnings`` of the ``version_diff`` kind."""
    deadline = time.monotonic() + max_seconds
    warnings = list(a.warnings) + [w for w in b.warnings if w not in a.warnings]
    if a.model != b.model or a.doc_type != b.doc_type:
        geometry = {"compared": False, "reason": "different_types", "configurations": []}
    elif a.geometry_reason is not None or b.geometry_reason is not None:
        geometry = {"compared": False, "reason": a.geometry_reason or b.geometry_reason, "configurations": []}
    else:
        rows = []
        names = list(a.geometry) + [n for n in b.geometry if n not in a.geometry]
        incomplete = False
        for name in names:
            fa, fb = a.geometry.get(name), b.geometry.get(name)
            if fa is None:
                status = "added"
            elif fb is None:
                status = "removed"
            elif not fa["stored"] and not fb["stored"]:
                status = "not_stored"
            elif not fa["stored"] or not fb["stored"]:
                status = "not_compared"
            elif fa["fingerprint"] == fb["fingerprint"]:
                status = "unchanged"
            else:
                status = "changed"
                if measure:
                    fa = dict(fa, measures=a.measure(name, deadline))
                    fb = dict(fb, measures=b.measure(name, deadline))
                    if not (fa["measures"]["complete"] and fb["measures"]["complete"]):
                        incomplete = True
            rows.append(
                {
                    "configuration": name,
                    "status": status,
                    "from": fa,
                    "to": fb,
                    "changes": _measure_changes(fa, fb) if status == "changed" else [],
                }
            )
        if incomplete:
            warnings.append(
                {
                    "code": "measures_incomplete",
                    "stream": None,
                    "message": "some volumes, areas or boxes were not compared: a version could not be "
                    "measured whole within the time limit",
                }
            )
        geometry = {"compared": True, "reason": None, "configurations": rows}
    return {
        "document": {
            "from": _document_brief(a.summary),
            "to": _document_brief(b.summary),
            "changes": _document_changes(a.summary, b.summary),
        },
        "properties": _property_changes(a.summary, b.summary),
        "configurations": _configuration_changes(a.summary, b.summary),
        "geometry": geometry,
        "warnings": warnings,
    }


def _document_brief(s: dict[str, Any]) -> dict[str, Any]:
    sv = s.get("saved_version") or {}
    return {
        "format": s.get("format"),
        "type": s.get("doc_type"),
        "saved_version": sv.get("release"),
        "configurations": len(s.get("configurations") or ()),
        "properties": len(s.get("properties") or ()),
    }


__all__ = ["DEFAULT_MAX_SECONDS", "Side", "body_fingerprint", "compare_sides"]
