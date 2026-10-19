"""The details panel's Overview for a 3D file of another format than SOLIDWORKS.

The panel shows a model file from its ``model_summary`` (format, variant, document
type, units, the program that wrote it, summary fields, properties, warnings) and
the measures of its geometry (:func:`.modelview.scene_geometry`: objects, placed
items, bodies, faces, triangles, vertices and the box), which arrive in a second
section once the worker has read the geometry. :func:`overview` builds the tree
from both; until the geometry arrives its group says it is being read, and when it
could not be read, why, without hiding the rest. Every value is shown as plain
text.
"""

from typing import Any

from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from .reading import size_text, time_text
from .wording import error_message, plural, sources_text

DOC_TYPE_TEXT = {"part": "Part", "assembly": "Assembly"}
KIND_TEXT = {
    "mesh": "meshes (triangles)",
    "brep": "exact solids and surfaces (B-rep)",
    "mixed": "exact solids and surfaces, and meshes",
}
UNIT_NAMES = {
    "mm": "millimetres",
    "cm": "centimetres",
    "m": "metres",
    "in": "inches",
    "ft": "feet",
    "micron": "microns",
}
UNIT_SOURCES = {
    "file": "as the file states",
    "format": "the format's own unit",
    "assumed": "assumed: the file states none",
}
VARIANT_TEXT = {
    "ascii": "ASCII",
    "binary": "binary",
    "binary_le": "binary",
    "binary_be": "binary, big-endian",
    "text": "text",
    "glb": "binary glTF (GLB)",
    "gltf": "glTF JSON",
    "core": "core specification",
    "production": "with the production extension",
    "plain": "XML",
    "zip": "zipped",
    "sab": "binary (SAB)",
    "sat": "text (SAT)",
    "part": "part",
    "assembly": "assembly",
    "sheet_metal": "sheet metal part",
}
_FIELD_NAMES = {
    "title": "Title",
    "subject": "Subject",
    "author": "Author",
    "keywords": "Keywords",
    "comments": "Comments",
    "last_saved_by": "Last saved by",
    "created_utc": "Created",
    "last_saved_utc": "Last saved",
}
MAX_WARNINGS = 200


def _number(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def format_text(s: dict[str, Any]) -> str:
    """``STEP, AP214``; ``STL, binary``; the format's name alone without a variant."""
    name = s.get("format_name") or s.get("format") or "unknown"
    variant = s.get("variant")
    if not variant or s.get("format") == "alibre" or variant.casefold() == name.casefold():
        return name
    return f"{name}, {VARIANT_TEXT.get(variant, variant)}"


def type_text(s: dict[str, Any]) -> str:
    """The subtitle's document type: ``STEP assembly``, ``Alibre Design part``."""
    doc = (s.get("doc_type") or "file").lower()
    return f"{s.get('format_name') or 'Model'} {doc}"


def units_text(units: dict[str, Any] | None) -> str:
    u = units or {}
    length = u.get("length")
    if not length:
        return "not known"
    return (
        f"{UNIT_NAMES.get(length, length)} ({UNIT_SOURCES.get(u.get('source') or '', u.get('source') or '')})"
    )


def size_lines(geometry: dict[str, Any], units: dict[str, Any] | None) -> list[tuple[str, str]]:
    """The box of the model: its size in millimetres (and in the file's own unit when that
    is not millimetres), and its corners."""
    box = geometry.get("box_m")
    if not box:
        return [("Size", "no triangles to measure")]
    lo, hi = box
    mm = [(hi[i] - lo[i]) * 1000.0 for i in range(3)]
    size = " x ".join(_number(v) for v in mm) + " mm"
    u = units or {}
    scale = u.get("scale_m")
    if u.get("length") and u["length"] != "mm" and isinstance(scale, (int, float)) and scale > 0:
        own = " x ".join(_number((hi[i] - lo[i]) / scale) for i in range(3))
        size += f" ({own} {u['length']})"
    corners = (
        "from ("
        + ", ".join(_number(v * 1000.0) for v in lo)
        + ") to ("
        + ", ".join(_number(v * 1000.0) for v in hi)
    ) + ") mm"
    return [("Size (X x Y x Z)", size), ("Box", corners)]


def _add(parent: QTreeWidgetItem, field: str, value: Any) -> QTreeWidgetItem:
    item = QTreeWidgetItem([field, "" if value is None else str(value)])
    parent.addChild(item)
    return item


def _group(tree: QTreeWidget, text: str) -> QTreeWidgetItem:
    item = QTreeWidgetItem([text])
    f = item.font(0)
    f.setBold(True)
    item.setFont(0, f)
    tree.addTopLevelItem(item)
    return item


def geometry_rows(
    geometry: dict[str, Any] | None, error: dict[str, Any] | None, units: dict[str, Any] | None, *, path=None
) -> list[tuple[str, str]]:
    """The Geometry group's rows: what was measured, being read, or why it could not be."""
    if geometry is None:
        if error is not None:
            first = error_message(error, path=path).split("\n", 1)[0]
            return [("Geometry", f"could not be read: {first}")]
        return [("Geometry", "being read...")]
    g = geometry
    rows: list[tuple[str, str]] = []
    rows.append(("Objects", f"{g['objects']:,}"))
    rows.append(("Placed", plural(g["items"], "item")))
    if g.get("bodies") is not None:
        rows.append(("Bodies", f"{g['bodies']:,}"))
    if g.get("faces") is not None:
        faces = f"{g['faces']:,}"
        if g.get("faces_done") is not None and g["faces_done"] != g["faces"]:
            faces += f" ({g['faces_done']:,} drawn, {g['faces'] - g['faces_done']:,} left out)"
        rows.append(("Faces", faces))
    rows.append(("Triangles", f"{g['triangles']:,} placed, from {sources_text(g.get('sources') or [])}"))
    rows.append(("Vertices", f"{g['vertices']:,}"))
    rows += size_lines(g, units)
    if g.get("truncated"):
        rows.append(
            ("Cut short", "by the 3D view's triangle limit: the counts and the box are of what was read")
        )
    if g.get("skipped_count"):
        rows.append(("Left out", plural(g["skipped_count"], "item") + " (see Warnings)"))
    return rows


def _drawn_text(geometry: dict[str, Any] | None, error: dict[str, Any] | None) -> str:
    """Whether the Preview tab can draw a picture from the geometry, as its read went."""
    if error is not None:
        return "none can be drawn either, as the geometry could not be read (see Geometry)"
    if geometry is not None and not geometry.get("triangles"):
        return "none can be drawn either, as the geometry holds no triangles"
    return "the Preview tab draws one from the geometry"


def overview(
    tree: QTreeWidget,
    s: dict[str, Any],
    geometry: dict[str, Any] | None = None,
    geometry_error: dict[str, Any] | None = None,
    *,
    used_configuration: str | None = None,
    path: str | None = None,
) -> None:
    """Fill the Overview ``tree`` for the ``model_summary`` ``s`` and its geometry."""
    tree.setUpdatesEnabled(False)
    try:
        tree.clear()
        doc = _group(tree, "Document")
        _add(doc, "Format", format_text(s))
        doc_type = DOC_TYPE_TEXT.get(s.get("doc_type") or "", "unknown")
        how = (
            "from the file's own structure"
            if s.get("doc_type") == "assembly"
            else "one model, however many objects it holds"
        )
        _add(doc, "Type", f"{doc_type} ({how})")
        _add(doc, "Holds", KIND_TEXT.get(s.get("kind") or "", s.get("kind") or "unknown"))
        _add(doc, "Units", units_text(s.get("units")))
        app = s.get("application") or {}
        if app.get("name") or app.get("version"):
            _add(doc, "Written by", " ".join(v for v in (app.get("name"), app.get("version")) if v))
        if s.get("active_configuration"):
            _add(doc, "Configuration", s["active_configuration"])
        if used_configuration:
            _add(doc, "Used by the instance", used_configuration)

        f = s.get("file") or {}
        file = _group(tree, "File")
        _add(file, "Name", f.get("name"))
        if f.get("size") is not None:
            _add(file, "Size", f"{size_text(f['size'])} ({f['size']:,} bytes)")
        _add(file, "Modified", time_text(f.get("modified_utc")))

        geo = _group(tree, "Geometry")
        for k, v in geometry_rows(geometry, geometry_error, s.get("units"), path=path):
            _add(geo, k, v)

        fields = {k: v for k, v in (s.get("fields") or {}).items() if v not in (None, "")}
        fl = _group(tree, f"Summary fields ({len(fields)})")
        for k, v in fields.items():
            _add(fl, _FIELD_NAMES.get(k, k.capitalize()), time_text(v) if k.endswith("_utc") else v)

        c = s.get("counts") or {}
        pv = s.get("preview") or {}
        cnt = _group(tree, "Contents")
        _add(cnt, "Properties", len(s.get("properties") or []))
        for key, label in (
            ("components", "Components"),
            ("references", "Referenced files"),
            ("model_parts", "Model parts"),
        ):
            if c.get(key) is not None:
                _add(cnt, label, f"{c[key]:,}")
        if pv.get("available"):
            _add(
                cnt,
                "Stored preview",
                f"{pv.get('width')} x {pv.get('height')} ({pv.get('stream') or 'stored'})",
            )
        else:
            reason = "none stored" if pv.get("reason") == "not_stored" else f"none ({pv.get('reason')})"
            if pv.get("renderable"):
                reason += "; " + _drawn_text(geometry, geometry_error)
            _add(cnt, "Stored preview", reason)

        warnings = list(s.get("warnings") or [])
        for w in (geometry or {}).get("warnings") or []:
            if not any(x.get("code") == w.get("code") for x in warnings):
                warnings.append(w)
        for sk in ((geometry or {}).get("skipped") or [])[:MAX_WARNINGS]:
            what = sk.get("instance") or "a face"
            warnings.append(
                {"code": f"left out: {sk.get('reason')}", "message": f"{what}: {sk.get('message') or ''}"}
            )
        wl = _group(tree, f"Warnings ({len(warnings):,})")
        for w in warnings[:MAX_WARNINGS]:
            _add(wl, w.get("code") or "", w.get("message") or "")
        if len(warnings) > MAX_WARNINGS:
            _add(wl, f"{len(warnings) - MAX_WARNINGS:,} more", "see Raw JSON")
        if not warnings:
            _add(wl, "none", "")
        tree.expandAll()
        tree.resizeColumnToContents(0)
        tree.setColumnWidth(0, max(tree.columnWidth(0) + 12, 200))
    finally:
        tree.setUpdatesEnabled(True)


__all__ = ["format_text", "geometry_rows", "overview", "size_lines", "type_text", "units_text"]
