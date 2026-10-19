"""The catalog record of one document: built in a worker, checked in the writer.

:func:`build_record` runs inside a worker process (the ``catalog_document`` job
of :mod:`solidseas.jobs`) on a SOLIDWORKS document opened read-only ``within``
its root, and :func:`build_model_record` on a file of any other format SolidSeas
reads (a model file, :func:`solidseas.formats.open_any`). Which formats a catalog
indexes is its ``formats`` setting (:func:`indexed_formats`). A record is plain
JSON data, built from the same builders as the ``document_summary``,
``references`` and ``model_summary`` kinds, plus the preview image as the job's
raw payload.

A SOLIDWORKS document's record holds:

* ``stat``: size, modification time, file id (``st_dev:st_ino`` in hex, None
  where the filesystem reports no inode number) and link count, from ``fstat``
  on the handle the worker read;
* the summary fields the catalog keeps: format, type, saved version, active
  configuration, material, summary fields, units, preview, counts and warning
  codes;
* the file's custom properties and each configuration with its own;
* ``identity``: the creation time the document stores about itself
  (:func:`solidseas.resolve.identity.own_identity`), which the catalog's
  resolution compares with what assemblies stored;
* ``folder_at_save`` and every referenced file with what resolution needs of it
  (the fields of :class:`solidseas.resolve.ResolutionInput`), so references are
  resolved later from rows without opening the file again;
* the model graph of an assembly, grouped: one ``edges`` row per parent (the
  document itself, or a sub-assembly by its file key in this document's tree),
  parent configuration, child file key and child configuration, with the
  instance, unsuppressed and in-BOM counts at that level and the child model's
  alternate name;
* a drawing's views: sheet, view, configuration and the model's file key.

A model file's record holds what its head says, read as the folder listing
reads it: ``stat``, the registry id as ``format``, its type (``part``,
``assembly`` or null), active configuration, summary fields, units (``length``,
``scale_m`` and ``source``), the header counts (:data:`MODEL_COUNT_NAMES`), the
image it stores as a PNG SolidSeas wrote, warning codes and properties. It has
no configurations, identity, folder at save or views, and the worker never
reads its tree, scene, bodies or the files it names to make it.

An Alibre Design file (:data:`REFERENCING_FORMATS`) adds ``document``: the GUID
and version its ``VERSION`` stream gives, by which the assemblies that place it
name it. An Alibre assembly adds its components, from its design database
alone (never found on disk here): one reference per document it places, keyed
by that document's GUID, with the repository path and name stored and the
version it asks for (``version``), and one model-graph row per document, from
the assembly in its active configuration, counting its inclusions (Alibre stores
no suppression or BOM flag the reader knows, so all three counts are the
inclusions). The catalog resolves them later from rows, by GUID
(:func:`solidseas.catalog.resolution.resolve_alibre`).

:func:`check_record` runs in the writer process, which treats the worker's
answer as untrusted: every field is checked for its type, its enumeration, its
range and its length, and a document may carry at most
:data:`MAX_CONFIGURATIONS` configurations, :data:`MAX_PROPERTIES` properties,
:data:`MAX_REFERENCES` references, :data:`MAX_EDGES` edges and
:data:`MAX_VIEWS` views. A record that fails raises :class:`InvalidRecord` and
nothing of it is stored. :func:`build_record` keeps a legitimate document inside
those limits itself: over-long text is cut, properties and configurations past
the limits are left out, and a model graph or view list too large is left out
with ``references_state`` ``truncated``, so such a document is indexed, not
refused. The preview payload is kept only when it is what the record says: a
PNG or a BMP by its signature, of the size and SHA-256 given, at most
:data:`MAX_PREVIEW_BYTES`.
"""

import hashlib
import json
import math
import re
from typing import Any

from ..errors import SolidSeasError
from ..formats.solidworks.preview import PNG_SIGNATURE

RECORD_VERSION = 1
MAX_TEXT = 4096
MAX_KEY = 64
MAX_NAME = 1024
MAX_PROPERTY_TEXT = 65536
MAX_CONFIGURATIONS = 10_000
MAX_PROPERTIES = 10_000
MAX_REFERENCES = 100_000
MAX_EDGES = 200_000
MAX_VIEWS = 10_000
MAX_WARNINGS = 1_000
MAX_PREVIEW_BYTES = 16 << 20
MAX_COUNT = 1 << 31
REPLY_LIMIT = 32 << 20  # the longest answer the catalog accepts from the job

DOC_TYPES = ("part", "assembly", "drawing")
EMBEDDED = ("embedded", "embedded_not_found", "embedded_in_subassembly")
PROPERTY_TYPES = ("text", "number", "boolean", "date", "other")
REFERENCES_STATES = ("none", "described", "unknown", "truncated")
FIELD_NAMES = ("title", "author", "last_saved_by", "keywords", "comments", "last_saved_utc")
COUNT_NAMES = (
    "streams",
    "configurations",
    "custom_properties",
    "references",
    "nested_documents",
    "parasolid_partitions",
)
UNIT_NAMES = ("system", "length", "mass", "angle", "length_decimal_places")
PREVIEW_MIMES = ("image/png", "image/bmp")
SOLIDWORKS_FORMATS = ("modern", "ole")  # a SOLIDWORKS document's format: its container
# A model file's units and header counts (solidseas.formats.base.HEAD_COUNTS).
MODEL_UNIT_NAMES = ("length", "scale_m", "source")
MODEL_COUNT_NAMES = (
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
DEFAULT_FORMATS = "solidworks"  # what a catalog indexes until told otherwise
# The formats whose references the catalog follows, so where-used finds their users.
REFERENCING_FORMATS = ("solidworks", "alibre")
_GUID = re.compile(r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")


# --------------------------------------------------------------------------- formats
def indexed_formats(setting: Any = DEFAULT_FORMATS) -> frozenset[str]:
    """The formats (registry ids) a catalog whose ``formats`` setting is ``setting``
    indexes: ``"all"`` for every format SolidSeas reads, ``"solidworks"`` (the default),
    or format ids, as a list or as text joined by commas. A format SolidSeas lists but
    cannot read is left out; an unknown id is ``invalid_argument``."""
    from ..formats import registry

    return frozenset(f for f in registry.select(setting) if registry.readable(f))


def stored_formats(text: str | None) -> frozenset[str]:
    """The formats a catalog indexes, from its stored setting (``meta`` ``formats``; None
    or empty: the default). Ids this version does not know, which a newer one may have
    stored, are left out rather than refused."""
    from ..formats import registry

    if not text:
        return indexed_formats(DEFAULT_FORMATS)
    if text == "all":
        return indexed_formats("all")
    known = [f for f in text.split(",") if f in registry.FORMATS]
    return indexed_formats(known) if known else frozenset()


def indexed_extensions(formats: frozenset[str]) -> tuple[str, ...]:
    """The lower-case extensions, with their dots, of the files ``formats`` index."""
    from ..formats import registry

    return registry.extensions(sorted(formats)) if formats else ()


def file_format(stored: str | None, name: str) -> str | None:
    """The registry id of a catalog file: the format its document was read as
    (``solidworks`` for a SOLIDWORKS document), else the one its extension names; None
    for a name no format has."""
    if stored in SOLIDWORKS_FORMATS:
        return "solidworks"
    if stored:
        return stored
    from ..formats import registry

    spec = registry.by_extension(name)
    return spec.id if spec is not None else None


def _model_formats() -> frozenset[str]:
    """The formats a model record may name: every format SolidSeas reads but SOLIDWORKS."""
    return indexed_formats("all") - {"solidworks"}


# --------------------------------------------------------------------------- the worker side
def _cut(text: Any, limit: int) -> Any:
    return text[:limit] if isinstance(text, str) and len(text) > limit else text


def _property(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": _cut(p["name"], MAX_NAME),
        "type": p["type"],
        "text": _cut(p["text"], MAX_PROPERTY_TEXT),
        "value": _cut(p["value"], MAX_PROPERTY_TEXT),
        "expression": _cut(p["expression"], MAX_PROPERTY_TEXT),
        "linked": p["linked"],
    }


def _fit(rec: dict[str, Any]) -> None:
    """Keep a legitimate record inside the writer's limits (see the module notes)."""
    budget = MAX_PROPERTIES
    rec["configurations"] = rec["configurations"][:MAX_CONFIGURATIONS]
    rec["properties"] = rec["properties"][:budget]
    budget -= len(rec["properties"])
    for c in rec["configurations"]:
        c["name"] = _cut(c["name"], MAX_NAME)
        c["comment"] = _cut(c["comment"], MAX_PROPERTY_TEXT)
        c["material"] = _cut(c["material"], MAX_NAME)
        c["properties"] = c["properties"][: max(0, budget)]
        budget -= len(c["properties"])
    for key, limit in (
        ("active_configuration", MAX_NAME),
        ("material", MAX_NAME),
        ("folder_at_save", MAX_TEXT),
    ):
        rec[key] = _cut(rec[key], limit)
    rec["fields"] = {k: _cut(v, MAX_PROPERTY_TEXT) for k, v in rec["fields"].items()}
    if (
        len(rec["references"]) > MAX_REFERENCES
        or len(rec["edges"]) > MAX_EDGES
        or len(rec["views"]) > MAX_VIEWS
    ):
        rec["references"], rec["edges"], rec["views"] = [], [], []
        rec["references_state"] = "truncated"


def model_graph(doc) -> list[list[Any]]:
    """An assembly's stored model graph, grouped (see the module notes). Where the tree
    holds more than one model of one file in one configuration, the first one counts, as
    in a bill of materials."""
    md = doc.metadata
    tree = md.tree or {}
    models = tree.get("models", {})
    files = tree.get("files", {})
    own = md.own_file_ids
    top_names = {
        c.get("model_ref"): c.get("name") for c in tree.get("configs", []) if c.get("name") is not None
    }
    owner: dict[tuple, str] = {}
    groups: dict[tuple, list[Any]] = {}
    for r in tree.get("refs", []):
        parent = models.get(r["parent_model"])
        child = models.get(r["model_ref"])
        if parent is None or child is None:
            continue
        child_key = child.get("file_ref")
        if child_key is None or child_key not in files or child_key in own:
            continue
        parent_file = parent.get("file_ref")
        if parent_file in own:
            parent_key, parent_cfg = None, top_names.get(r["parent_model"], parent.get("config"))
        elif parent_file is None or parent_file not in files:
            continue
        else:
            parent_key, parent_cfg = parent_file, parent.get("config")
        if owner.setdefault((parent_key, parent_cfg), r["parent_model"]) != r["parent_model"]:
            continue
        key = (parent_key, parent_cfg, child_key, r.get("config") or child.get("config"))
        g = groups.get(key)
        if g is None:
            g = groups[key] = [0, 0, 0, child.get("alternate_name") or None]
        g[0] += 1
        if not r["suppressed"]:
            g[1] += 1
            if not r["exclude_from_bom"]:
                g[2] += 1
    return [[*k, *v] for k, v in groups.items()]


def build_record(doc, *, previews: bool = True, graph: bool = True) -> tuple[dict[str, Any], bytes | None]:
    """The catalog record of an open document and its preview image (None when it has
    none or ``previews`` is false). See the module notes."""
    from .. import model
    from ..resolve import ResolutionInput
    from ..resolve.identity import own_identity

    c = doc.container
    size, mtime_ns = c.file_stat if c.file_stat is not None else (None, None)
    dev, ino, nlink = c.file_ident if c.file_ident is not None else (0, 0, 1)
    summary = model.build_document_summary(doc)
    sv = summary["saved_version"]
    pv = summary["preview"]
    fields = summary["fields"]
    ident = own_identity(doc)
    folder = doc.metadata.summary.get("folder_at_save")
    rec: dict[str, Any] = {
        "v": RECORD_VERSION,
        "stat": {
            "size": size,
            "mtime_ns": None if mtime_ns is None else str(mtime_ns),
            "file_id": f"{dev:x}:{ino:x}" if ino else None,
            "nlink": nlink,
        },
        "format": summary["format"],
        "doc_type": summary["doc_type"],
        "doc_type_source": summary["doc_type_source"],
        "release": sv["release"],
        "release_verified": sv["release_verified"],
        "format_version": sv["format_version"],
        "last_build": sv["last_build"],
        "active_configuration": summary["active_configuration"],
        "material": (summary["material"] or {}).get("name"),
        "fields": {k: fields.get(k) for k in FIELD_NAMES},
        "units": summary["units"],
        "preview": (
            {k: pv[k] for k in ("mime", "width", "height", "bytes", "sha256", "stream")}
            if pv["available"]
            else None
        ),
        "counts": summary["counts"],
        "warnings": [w["code"] for w in summary["warnings"]][:MAX_WARNINGS],
        "properties": [_property(p) for p in summary["properties"] or []],
        "configurations": [
            {
                "name": cfg["name"],
                "id": cfg["id"],
                "active": cfg["active"],
                "most_recent": cfg["most_recent"],
                "comment": cfg["comment"],
                "material": (cfg["material"] or {}).get("name"),
                "properties": [_property(p) for p in cfg["properties"]],
            }
            for cfg in summary["configurations"] or []
        ],
        "identity": {"creation_time": ident.creation_time, "source": ident.source},
        "folder_at_save": folder if isinstance(folder, str) else None,
        "references_state": "none",
        "references": [],
        "edges": [],
        "views": [],
    }
    if doc.doc_type in ("assembly", "drawing"):
        if not graph:
            rec["references_state"] = "truncated"
        else:
            rs = doc.reference_set()
            inp = {f.key: f for f in ResolutionInput.from_document(doc).files}
            refs = []
            for f in rs.files.values():
                i = inp.get(f.key)
                ni = i.nested_identity if i is not None else None
                refs.append(
                    {
                        "key": f.key,
                        "stored_path": f.stored_path,
                        "file_name": f.file_name,
                        "doc_type": f.doc_type,
                        "direct": f.direct,
                        "virtual": f.virtual,
                        "imported": f.imported,
                        "embedded": f.embedded,
                        "nested": f.nested,
                        "stored_creation_time": i.stored_creation_time if i is not None else None,
                        "parent_documents": i.parent_documents if i is not None else 0,
                        "nested_identity": None
                        if ni is None
                        else {"creation_time": ni.creation_time, "source": ni.source, "error": ni.error},
                    }
                )
            rec["references"] = refs
            if rs.truncated:
                rec["references_state"] = "truncated"
            elif doc.doc_type == "drawing":
                rec["references_state"] = "described"
            else:
                rec["references_state"] = (
                    rs.children_state if rs.children_state in REFERENCES_STATES else "unknown"
                )
            if doc.doc_type == "assembly":
                rec["edges"] = model_graph(doc)
            elif rs.sheets is not None:
                rec["views"] = [[s.name, v.name, v.configuration, v.file] for s in rs.sheets for v in s.views]
    _fit(rec)
    image = None
    if previews and pv["available"]:
        try:
            p = doc.preview()
        except Exception:  # undecodable: the summary already said so
            p = None
        if p is not None and len(p.data) <= MAX_PREVIEW_BYTES:
            image = p.data
    return model.to_json_data(rec), image


def build_model_record(doc, *, previews: bool = True) -> tuple[dict[str, Any], bytes | None]:
    """The catalog record of an open model file (a :class:`~solidseas.formats.base.ModelDocument`)
    and the image it stores as a PNG SolidSeas wrote (None when it stores none, it cannot
    be decoded or ``previews`` is false). Only the head is read: never the tree, the
    scene, the bodies or the files the model names. See the module notes."""
    from .. import model
    from ..errors import SldFormatError
    from ..formats._source import preview_png

    summary = model.build_model_summary(doc, include=("properties",))
    fi = doc.file_info
    ident = getattr(doc.source, "file_ident", None)
    dev, ino, nlink = ident if ident is not None else (0, 0, None)
    fields = summary["fields"]
    warnings = [w["code"] for w in summary["warnings"]]
    pv = None
    image = None
    try:
        got = preview_png(doc.preview(), doc.limits)
    except SldFormatError:  # undecodable: the summary's warnings say so
        got = None
    if got is not None and len(got[0]) <= MAX_PREVIEW_BYTES:
        png, width, height, stream = got
        pv = {
            "mime": "image/png",
            "width": width,
            "height": height,
            "bytes": len(png),
            "sha256": hashlib.sha256(png).hexdigest(),
            "stream": stream,
        }
        image = png if previews else None
    rec: dict[str, Any] = {
        "v": RECORD_VERSION,
        "stat": {
            "size": fi.size if fi is not None else None,
            "mtime_ns": None if fi is None else str(fi.mtime_ns),
            "file_id": f"{dev:x}:{ino:x}" if ino else None,
            "nlink": nlink,
        },
        "format": summary["format"],
        "doc_type": summary["doc_type"],
        "doc_type_source": "content",
        "release": None,
        "release_verified": False,
        "format_version": None,
        "last_build": None,
        "active_configuration": summary["active_configuration"],
        "material": None,
        "fields": {k: fields.get(k) for k in FIELD_NAMES},
        "units": {k: summary["units"].get(k) for k in MODEL_UNIT_NAMES},
        "preview": pv,
        "counts": {k: summary["counts"].get(k) for k in MODEL_COUNT_NAMES},
        "warnings": warnings[:MAX_WARNINGS],
        "properties": [_property(p) for p in summary["properties"] or []],
        "configurations": [],
        "identity": {"creation_time": None, "source": None},
        "folder_at_save": None,
        "references_state": "none",
        "references": [],
        "edges": [],
        "views": [],
    }
    if summary["format"] == "alibre":
        _alibre(doc, rec)
    _fit(rec)
    return model.to_json_data(rec), image


def _alibre(doc, rec: dict[str, Any]) -> None:
    """An Alibre document's GUID and version, and an assembly's components and model
    graph from its design database (see the module notes). A database that cannot be
    read leaves the components out, with ``references_state`` saying why."""
    from ..errors import SldLimitError, SolidSeasError

    ident = getattr(doc, "identity", None)
    if ident is not None:
        rec["document"] = {"guid": ident.guid, "version": ident.version}
    if doc.doc_type != "assembly":
        return
    try:
        inclusions = doc.design().inclusions
    except SldLimitError:
        rec["references_state"] = "truncated"
        return
    except SolidSeasError:
        rec["references_state"] = "unknown"
        return
    refs: dict[str, dict[str, Any]] = {}
    count: dict[str, int] = {}
    for inc in inclusions:
        count[inc.guid] = count.get(inc.guid, 0) + 1
        if inc.guid not in refs:
            refs[inc.guid] = {
                "key": inc.guid,
                "stored_path": _cut(inc.stored_path, MAX_TEXT),
                "file_name": _cut(inc.stored_name, MAX_NAME),
                "doc_type": None,
                "direct": True,
                "virtual": False,
                "imported": False,
                "embedded": None,
                "nested": None,
                "stored_creation_time": None,
                "parent_documents": 0,
                "nested_identity": None,
                "version": inc.version,
            }
    active = _cut(doc.active_configuration, MAX_NAME)
    rec["references"] = list(refs.values())
    rec["edges"] = [[None, active, guid, None, n, n, n, None] for guid, n in count.items()]
    rec["references_state"] = "described"


# --------------------------------------------------------------------------- the writer side
class InvalidRecord(SolidSeasError, ValueError):
    """A worker's answer that is not a catalog record (``what`` names the field). Its
    error code is ``internal`` with ``detail["rule"]`` ``invalid_record``."""

    code = "internal"

    def __init__(self, what: str) -> None:
        super().__init__(f"invalid catalog record: {what}", detail={"rule": "invalid_record"})
        self.what = what


def _text(v: Any, what: str, limit: int = MAX_TEXT, *, null: bool = True) -> str | None:
    if v is None and null:
        return None
    if not isinstance(v, str) or len(v) > limit:
        raise InvalidRecord(what)
    return v


def _int(v: Any, what: str, lo: int = 0, hi: int = MAX_COUNT, *, null: bool = True) -> int | None:
    if v is None and null:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise InvalidRecord(what)
    return v


def _bool(v: Any, what: str, *, null: bool = False) -> bool | None:
    if v is None and null:
        return None
    if not isinstance(v, bool):
        raise InvalidRecord(what)
    return v


def _enum(v: Any, choices: tuple[str, ...], what: str, *, null: bool = True) -> str | None:
    if v is None and null:
        return None
    if v not in choices:
        raise InvalidRecord(what)
    return v


def _obj(v: Any, what: str, *, null: bool = False) -> dict[str, Any] | None:
    if v is None and null:
        return None
    if not isinstance(v, dict):
        raise InvalidRecord(what)
    return v


def _list(v: Any, what: str, limit: int) -> list[Any]:
    if not isinstance(v, list) or len(v) > limit:
        raise InvalidRecord(what)
    return v


def _scale(v: Any, what: str) -> float | None:
    """A model's metres per unit: a positive, finite number, or None."""
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not v > 0:
        raise InvalidRecord(what)
    return float(v)


def _digits(v: Any, what: str) -> int | None:
    if v is None:
        return None
    if not isinstance(v, str) or not 1 <= len(v) <= 24:
        raise InvalidRecord(what)
    body = v[1:] if v.startswith("-") else v
    if not body.isascii() or not body.isdigit():
        raise InvalidRecord(what)
    n = int(v)
    if abs(n) >= 1 << 63:
        raise InvalidRecord(what)
    return n


def _value(v: Any, what: str) -> Any:
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, int):
        return _int(v, what, -(2**53 - 1), 2**53 - 1)
    if isinstance(v, float):
        if not math.isfinite(v):
            raise InvalidRecord(what)
        return v
    return _text(v, what, MAX_PROPERTY_TEXT)


def _properties(items: Any, what: str, budget: list[int]) -> list[dict[str, Any]]:
    out = []
    for p in _list(items, what, MAX_PROPERTIES):
        budget[0] += 1
        if budget[0] > MAX_PROPERTIES:
            raise InvalidRecord(f"{what}: too many properties")
        p = _obj(p, what)
        out.append(
            {
                "name": _text(p.get("name"), f"{what}.name", MAX_NAME, null=False),
                "type": _enum(p.get("type"), PROPERTY_TYPES, f"{what}.type", null=False),
                "text": _text(p.get("text"), f"{what}.text", MAX_PROPERTY_TEXT),
                "value": _value(p.get("value"), f"{what}.value"),
                "expression": _text(p.get("expression"), f"{what}.expression", MAX_PROPERTY_TEXT),
                "linked": _bool(p.get("linked"), f"{what}.linked"),
            }
        )
    return out


def _nested_identity(v: Any, what: str) -> dict[str, Any] | None:
    o = _obj(v, what, null=True)
    if o is None:
        return None
    return {
        "creation_time": _int(o.get("creation_time"), f"{what}.creation_time", 0, 2**53 - 1),
        "source": _text(o.get("source"), f"{what}.source", 32),
        "error": _text(o.get("error"), f"{what}.error", 100),
    }


def check_preview(meta: dict[str, Any] | None, payload: bytes | None) -> bytes | None:
    """The payload when it is the image ``meta`` describes, else None."""
    if meta is None or payload is None or len(payload) > MAX_PREVIEW_BYTES:
        return None
    if len(payload) != meta.get("bytes") or hashlib.sha256(payload).hexdigest() != meta.get("sha256"):
        return None
    if meta["mime"] == "image/png" and payload[:8] == PNG_SIGNATURE:
        return payload
    if meta["mime"] == "image/bmp" and payload[:2] == b"BM":
        return payload
    return None


def check_record(data: Any) -> dict[str, Any]:
    """The record ``data`` checked field by field (see the module notes), or
    :class:`InvalidRecord`."""
    o = _obj(data, "record")
    if o.get("v") != RECORD_VERSION:
        raise InvalidRecord("v")
    if "not_solidworks" in o:
        return {"not_solidworks": _enum(o.get("not_solidworks"), ("step",), "not_solidworks", null=False)}
    fmt = o.get("format")
    model_file = fmt not in SOLIDWORKS_FORMATS
    if model_file and (not isinstance(fmt, str) or fmt not in _model_formats()):
        raise InvalidRecord("format")
    stat = _obj(o.get("stat"), "stat")
    out: dict[str, Any] = {
        "stat": {
            "size": _int(stat.get("size"), "stat.size", 0, 2**53 - 1),
            "mtime_ns": _digits(stat.get("mtime_ns"), "stat.mtime_ns"),
            "file_id": _text(stat.get("file_id"), "stat.file_id", 80),
            "nlink": _int(stat.get("nlink"), "stat.nlink", 0, MAX_COUNT),
        },
        "format": fmt,
        "doc_type": _enum(o.get("doc_type"), DOC_TYPES[:2] if model_file else DOC_TYPES, "doc_type"),
        "doc_type_source": _text(o.get("doc_type_source"), "doc_type_source", 32),
        "release": _text(o.get("release"), "release", 256),
        "release_verified": _bool(o.get("release_verified"), "release_verified"),
        "format_version": _int(o.get("format_version"), "format_version", -(2**53 - 1), 2**53 - 1),
        "last_build": _int(o.get("last_build"), "last_build", -(2**53 - 1), 2**53 - 1),
        "active_configuration": _text(o.get("active_configuration"), "active_configuration", MAX_NAME),
        "material": _text(o.get("material"), "material", MAX_NAME),
        "folder_at_save": _text(o.get("folder_at_save"), "folder_at_save"),
        "references_state": _enum(
            o.get("references_state"), REFERENCES_STATES, "references_state", null=False
        ),
    }
    fields = _obj(o.get("fields"), "fields")
    out["fields"] = {k: _text(fields.get(k), f"fields.{k}", MAX_PROPERTY_TEXT) for k in FIELD_NAMES}
    units = _obj(o.get("units"), "units", null=True)
    if units is not None and model_file:
        units = {
            "length": _text(units.get("length"), "units.length", 64),
            "scale_m": _scale(units.get("scale_m"), "units.scale_m"),
            "source": _text(units.get("source"), "units.source", 64),
        }
    elif units is not None:
        u = {}
        for k in UNIT_NAMES:
            v = units.get(k)
            u[k] = (
                _text(v, f"units.{k}", 64)
                if isinstance(v, str)
                else _int(v, f"units.{k}", -(2**53 - 1), 2**53 - 1)
            )
        units = u
    out["units"] = units
    counts = _obj(o.get("counts"), "counts")
    names = MODEL_COUNT_NAMES if model_file else COUNT_NAMES
    out["counts"] = {k: _int(counts.get(k), f"counts.{k}", 0, 2**53 - 1) for k in names}
    pv = _obj(o.get("preview"), "preview", null=True)
    if pv is not None:
        sha = _text(pv.get("sha256"), "preview.sha256", 64, null=False)
        if len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
            raise InvalidRecord("preview.sha256")
        pv = {
            "mime": _enum(pv.get("mime"), PREVIEW_MIMES, "preview.mime", null=False),
            "width": _int(pv.get("width"), "preview.width", 0, 2**53 - 1),
            "height": _int(pv.get("height"), "preview.height", 0, 2**53 - 1),
            "bytes": _int(pv.get("bytes"), "preview.bytes", 0, 2**53 - 1, null=False),
            "sha256": sha,
            "stream": _text(pv.get("stream"), "preview.stream", MAX_NAME),
        }
    out["preview"] = pv
    out["warnings"] = [
        _text(w, "warnings", MAX_KEY, null=False) for w in _list(o.get("warnings"), "warnings", MAX_WARNINGS)
    ]
    budget = [0]
    out["properties"] = _properties(o.get("properties"), "properties", budget)
    configs = []
    for c in _list(o.get("configurations"), "configurations", MAX_CONFIGURATIONS):
        c = _obj(c, "configurations")
        configs.append(
            {
                "name": _text(c.get("name"), "configurations.name", MAX_NAME, null=False),
                "id": _int(c.get("id"), "configurations.id", -(2**53 - 1), 2**53 - 1),
                "active": _bool(c.get("active"), "configurations.active"),
                "most_recent": _bool(c.get("most_recent"), "configurations.most_recent", null=True),
                "comment": _text(c.get("comment"), "configurations.comment", MAX_PROPERTY_TEXT),
                "material": _text(c.get("material"), "configurations.material", MAX_NAME),
                "properties": _properties(c.get("properties"), "configurations.properties", budget),
            }
        )
    out["configurations"] = configs
    ident = _obj(o.get("identity"), "identity")
    out["identity"] = {
        "creation_time": _int(ident.get("creation_time"), "identity.creation_time", 0, 2**53 - 1),
        "source": _text(ident.get("source"), "identity.source", 32),
    }
    refs = []
    keys: set[str] = set()
    for r in _list(o.get("references"), "references", MAX_REFERENCES):
        r = _obj(r, "references")
        key = _text(r.get("key"), "references.key", MAX_KEY, null=False)
        if key in keys:
            raise InvalidRecord("references.key repeated")
        keys.add(key)
        refs.append(
            {
                "key": key,
                "stored_path": _text(r.get("stored_path"), "references.stored_path"),
                "file_name": _text(r.get("file_name"), "references.file_name", MAX_NAME),
                "doc_type": _enum(r.get("doc_type"), DOC_TYPES, "references.doc_type"),
                "direct": _bool(r.get("direct"), "references.direct", null=True),
                "virtual": _bool(r.get("virtual"), "references.virtual"),
                "imported": _bool(r.get("imported"), "references.imported"),
                "embedded": _enum(r.get("embedded"), EMBEDDED, "references.embedded"),
                "nested": _text(r.get("nested"), "references.nested", MAX_NAME),
                "stored_creation_time": _int(
                    r.get("stored_creation_time"), "references.stored_creation_time", 0, 2**53 - 1
                ),
                "parent_documents": _int(
                    r.get("parent_documents"), "references.parent_documents", 0, MAX_REFERENCES, null=False
                ),
                "nested_identity": _nested_identity(r.get("nested_identity"), "references.nested_identity"),
                "version": _int(r.get("version"), "references.version", -(2**53 - 1), 2**53 - 1),
            }
        )
    out["references"] = refs
    edges = []
    for e in _list(o.get("edges"), "edges", MAX_EDGES):
        e = _list(e, "edges", 8)
        if len(e) != 8:
            raise InvalidRecord("edges")
        edges.append(
            (
                _text(e[0], "edges.parent_key", MAX_KEY),
                _text(e[1], "edges.parent_configuration", MAX_NAME),
                _text(e[2], "edges.child_key", MAX_KEY, null=False),
                _text(e[3], "edges.child_configuration", MAX_NAME),
                _int(e[4], "edges.instances", null=False),
                _int(e[5], "edges.unsuppressed", null=False),
                _int(e[6], "edges.in_bom", null=False),
                _text(e[7], "edges.alternate_name", MAX_NAME),
            )
        )
    out["edges"] = edges
    views = []
    for v in _list(o.get("views"), "views", MAX_VIEWS):
        v = _list(v, "views", 4)
        if len(v) != 4:
            raise InvalidRecord("views")
        views.append(
            (
                _text(v[0], "views.sheet", MAX_NAME),
                _text(v[1], "views.view", MAX_NAME),
                _text(v[2], "views.configuration", MAX_NAME),
                _text(v[3], "views.key", MAX_KEY),
            )
        )
    out["views"] = views
    document = _obj(o.get("document"), "document", null=True)
    if document is not None:
        guid = _text(document.get("guid"), "document.guid", 36, null=False)
        if not _GUID.match(guid):
            raise InvalidRecord("document.guid")
        document = {
            "guid": guid,
            "version": _int(document.get("version"), "document.version", -(2**53 - 1), 2**53 - 1),
        }
    out["document"] = document
    if model_file:
        if configs or views:
            raise InvalidRecord("model record with configurations or views")
        if fmt != "alibre" and (refs or edges or document is not None):
            raise InvalidRecord("model record with references of a format whose references are not followed")
        if any(not _GUID.match(r["key"]) for r in refs):
            raise InvalidRecord("references.key")
        if any(e[0] is not None or e[2] not in keys for e in edges):
            raise InvalidRecord("edges")
    elif document is not None:
        raise InvalidRecord("document")
    return out


def value_json(v: Any) -> str:
    """A checked property value as the JSON text the catalog stores."""
    return json.dumps(v, ensure_ascii=False, allow_nan=False)


__all__ = [
    "MAX_CONFIGURATIONS",
    "MAX_EDGES",
    "MAX_PREVIEW_BYTES",
    "MAX_PROPERTIES",
    "MAX_REFERENCES",
    "MAX_VIEWS",
    "RECORD_VERSION",
    "REFERENCING_FORMATS",
    "REPLY_LIMIT",
    "InvalidRecord",
    "DEFAULT_FORMATS",
    "build_model_record",
    "build_record",
    "check_preview",
    "check_record",
    "file_format",
    "indexed_extensions",
    "indexed_formats",
    "model_graph",
    "stored_formats",
    "value_json",
]
