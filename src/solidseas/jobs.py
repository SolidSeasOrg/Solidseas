"""The jobs a worker process runs (:mod:`solidseas.workers`); provisional.

Each job takes its parameters as JSON data and returns JSON data, or a pair of
JSON data and raw bytes (a preview image). Every document job opens one file
read-only with :func:`~solidseas.formats.solidworks.open_document`, ``within``
the folder the caller names, and builds its answer with the same builder of
:mod:`solidseas.model` the Python API and the CLI use, so the data is identical
on every surface. A job holds the file open only while it runs and reads just
the parts of it the answer needs (``hold_open``), as the folder listing does;
the handle is closed when the job ends.

:func:`configure` runs once in each worker, before any job, with the pool's
settings:

* ``roots``: when not empty, the only folders a job may open documents below.
  A ``within`` outside them, or missing, is refused (``path_refused``, rule
  ``outside_roots``). The REST service passes its configured roots, so even a
  confused server process cannot make a worker open anything else.
* ``refuse_hard_links``: a file with more than one name (``st_nlink`` above 1 on
  the open handle) is refused before any byte is read (``link_refused``, rule
  ``hard_link``): another name for it may lie outside the root.
* ``max_file_bytes``: the largest document a job reads.
* ``formats`` (provisional): when set, the only formats a job reads a model file
  as. A file whose content is another format is refused whatever its name says
  (``format_not_supported``, rule ``format_not_enabled``): the REST service passes
  the formats it was started with.
* ``limits`` (provisional): the bounds of every model-file read, as a mapping of
  :class:`~solidseas.formats.Limits` fields to values (the defaults for the rest).
* ``flat_roots`` (provisional): roots served without their subfolders. A model file
  opened within one reads the files it names (a glTF buffer, an OBJ material
  library, an Alibre component) from its own folder only.

Two jobs serve the catalog (:mod:`solidseas.catalog`), whose writer process
never parses a CAD file itself: :func:`catalog_document` reads one document's
catalog record (what the catalog stores of it, checked again field by field
before it is stored), a SOLIDWORKS document's or a model file's, and
:func:`content_hash` the SHA-256 of one file's bytes.

:func:`batch_document` is the one job that writes: it reads a document for
``solidseas batch`` and writes its preview and Parasolid files to the run's
output folder, under the command line's write guards. It is not in the default
job table (:data:`solidseas.workers.JOB_NAMES`): only the command line's pool
adds it, so the service's workers can never run it.

Four jobs read model files, any 3D format SolidSeas reads other than SOLIDWORKS
(:func:`solidseas.formats.open_model`, provisional): :func:`model_summary`
(``model_summary`` data), :func:`model_entry` (a folder-listing entry),
:func:`model_properties` and :func:`model_preview` (the image the file stores,
as a PNG SolidSeas wrote, else one rendered from its geometry, as the binary
frame). Each opens its file ``within`` the folder the caller names, under the
same roots, hard-link and size settings as every other job.
"""

import hashlib
import os
from typing import Any

from . import model
from .errors import (
    FileTooLargeError,
    FormatNotSupportedError,
    InvalidArgumentError,
    LinkRefusedError,
    NoPreviewError,
    PathRefusedError,
    UnknownFormatError,
)
from .formats.solidworks import open_document

MAX_IDENTITY_ITEMS = 5_000
HASH_CHUNK = 1 << 20

_settings: dict[str, Any] = {
    "roots": (),
    "refuse_hard_links": False,
    "max_file_bytes": None,
    "formats": None,
    "limits": None,
    "flat_roots": (),
}


def _norm(folder: str) -> str:
    return os.path.normcase(os.path.abspath(folder)).rstrip("\\/")


def configure(settings: dict[str, Any]) -> None:
    """Set the worker's limits (see the module notes). Called once per worker."""
    from .formats.base import enabled_formats
    from .formats.limits import check_limits

    roots = settings.get("roots") or ()
    _settings["roots"] = tuple(_norm(r) for r in roots if isinstance(r, str))
    _settings["refuse_hard_links"] = bool(settings.get("refuse_hard_links"))
    limit = settings.get("max_file_bytes")
    _settings["max_file_bytes"] = limit if isinstance(limit, int) and not isinstance(limit, bool) else None
    _settings["formats"] = enabled_formats(settings.get("formats"))
    bounds = settings.get("limits")
    _settings["limits"] = check_limits(dict(bounds)) if bounds else None
    flat = settings.get("flat_roots") or ()
    _settings["flat_roots"] = tuple(_norm(r) for r in flat if isinstance(r, str))


def _subfolders(within: str | None) -> bool:
    """Whether a model file opened ``within`` a folder may read files below its own folder:
    not when that folder is a root served without its subfolders."""
    return within is None or _norm(within) not in _settings["flat_roots"]


def _model_formats(asked: list[str] | None = None) -> list[str] | None:
    """The formats a model-file job reads: those ``asked`` (None: every one) that the
    worker's ``formats`` setting allows; None when neither narrows them. Refused
    (``format_not_supported``, rule ``format_not_enabled``) when none is left."""
    allowed = _settings["formats"]
    if asked is None:
        return None if allowed is None else sorted(allowed)
    keep = set(asked) if allowed is None else set(asked) & allowed
    if not keep:
        raise FormatNotSupportedError(
            "none of the formats asked for is read here", detail={"rule": "format_not_enabled"}
        )
    return sorted(keep)


def _param(
    params: dict[str, Any], key: str, types: tuple, default: Any = None, *, required: bool = False
) -> Any:
    value = params.get(key, default)
    if value is None:
        if required:
            raise InvalidArgumentError(f"the job needs {key}", detail={"parameter": key})
        return None
    if isinstance(value, bool) and bool not in types:
        raise InvalidArgumentError(f"{key} has the wrong type", detail={"parameter": key})
    if not isinstance(value, types):
        raise InvalidArgumentError(f"{key} has the wrong type", detail={"parameter": key})
    return value


def _check_within(within: str | None) -> None:
    roots = _settings["roots"]
    if roots and (within is None or _norm(within) not in roots):
        raise PathRefusedError(
            "the folder is not one of this worker's roots", detail={"rule": "outside_roots"}
        )


def _open(params: dict[str, Any]):
    path = _param(params, "path", (str,), required=True)
    within = _param(params, "within", (str,))
    _check_within(within)
    return open_document(
        path,
        name=_param(params, "name", (str,)),
        within=within,
        max_file_bytes=_settings["max_file_bytes"],
        refuse_hard_links=_settings["refuse_hard_links"],
        hold_open=True,
    )


# --------------------------------------------------------------------------- document jobs
def document_summary(params: dict[str, Any]) -> dict[str, Any]:
    with _open(params) as doc:
        return model.build_document_summary(doc, nested=_param(params, "nested", (str,)))


def properties(params: dict[str, Any]) -> dict[str, Any]:
    with _open(params) as doc:
        return model.build_properties(
            doc,
            view=_param(params, "view", (str,), "effective"),
            configuration=_param(params, "configuration", (str,)),
            nested=_param(params, "nested", (str,)),
        )


def configurations(params: dict[str, Any]) -> dict[str, Any]:
    with _open(params) as doc:
        return model.build_configurations(doc)


def components(params: dict[str, Any]) -> dict[str, Any]:
    from .formats.solidworks.components import DEFAULT_MAX_DEPTH, DEFAULT_MAX_NODES

    with _open(params) as doc:
        return model.build_components(
            doc,
            configuration=_param(params, "configuration", (str,)),
            max_nodes=_param(params, "max_nodes", (int,), DEFAULT_MAX_NODES),
            max_depth=_param(params, "max_depth", (int,), DEFAULT_MAX_DEPTH),
            flat=_param(params, "flat", (bool,), False),
        )


def references(params: dict[str, Any]) -> dict[str, Any]:
    """``references`` data; with ``resolution_input`` true, ``{"references", "resolution_input"}``
    so the caller can resolve in its own process (``docs/API.md`` C10)."""
    from .resolve import ResolutionInput

    with _open(params) as doc:
        data = model.build_references(doc, configuration=_param(params, "configuration", (str,)))
        if not _param(params, "resolution_input", (bool,), False):
            return data
        return {"references": data, "resolution_input": ResolutionInput.from_document(doc).to_json()}


def resolution_input(params: dict[str, Any]) -> dict[str, Any]:
    """``{"doc_type", "resolution_input"}``: what the caller needs to resolve an
    assembly's references in its own process (``docs/API.md`` C10); the input is null
    for a part or a drawing."""
    from .resolve import ResolutionInput

    with _open(params) as doc:
        if doc.doc_type != "assembly":
            return {"doc_type": doc.doc_type, "resolution_input": None}
        return {"doc_type": doc.doc_type, "resolution_input": ResolutionInput.from_document(doc).to_json()}


def bom(params: dict[str, Any]) -> dict[str, Any]:
    """``bom`` data, from the resolution the caller made (``resolution``, as
    :func:`solidseas.bom.resolution_payload` writes it) against ``roots``: each
    component file it found is opened here, within its root, as every job opens a
    document. Nothing is looked up outside the roots."""
    from .bom import resolution_from_payload
    from .roots import Root, Roots

    items = _param(params, "roots", (list,), required=True)
    try:
        roots = Roots(
            Root(r["id"], r["path"], r.get("recursive", True), r.get("role", "project")) for r in items
        )
    except (KeyError, TypeError, AttributeError):
        raise InvalidArgumentError("roots is a list of root objects", detail={"parameter": "roots"}) from None
    payload = _param(params, "resolution", (dict,))
    res = resolution_from_payload(payload) if payload is not None else None
    with _open(params) as doc:
        if doc.doc_type == "assembly" and res is None:
            raise InvalidArgumentError(
                "an assembly's BOM job needs the resolution", detail={"parameter": "resolution"}
            )
        return model.build_bom(
            doc,
            configuration=_param(params, "configuration", (str,)),
            bom_type=_param(params, "type", (str,)),
            columns=_param(params, "columns", (list,), []),
            part_number_property=_param(params, "part_number_property", (str,)),
            roots=roots,
            resolution=res,
            allow_outside_roots=False,
            opener=lambda path, within: _open({"path": path, "within": within}),
        )


def preview(params: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    with _open(params) as doc:
        pv = doc.preview(
            prefer=_param(params, "prefer", (str,), "png"), nested=_param(params, "nested", (str,))
        )
    if pv is None:
        raise NoPreviewError("the document stores no preview image")
    return {"mime": pv.mime, "width": pv.width, "height": pv.height, "stream": pv.stream}, pv.data


def path_report(params: dict[str, Any]) -> dict[str, Any]:
    with _open(params) as doc:
        return model.build_path_report(doc)


def display_glb(params: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    """What the document shows, as a GLB (:func:`solidseas.gltf.display_glb`), with its
    summary: from the display data the document stores itself, so no other file is
    opened and no folder listed, whatever the document names."""
    from .gltf import GLB_MIME
    from .gltf import display_glb as build

    with _open(params) as doc:
        summary, data = build(doc, _param(params, "configuration", (str,)))
    return {"mime": GLB_MIME, **summary}, data


def _formats(params: dict[str, Any]) -> list[str] | None:
    from .formats import registry

    value = _param(params, "formats", (list,))
    if value is None:
        return None
    return sorted(registry.select(value))


def listing_entry(params: dict[str, Any]) -> tuple[dict[str, Any], bytes | None]:
    """One folder-listing entry (:func:`solidseas.listing.read_entry`), with the preview
    image as the payload when the listing inlines images. ``formats`` (format ids)
    lets a file wearing a SOLIDWORKS extension be read as another format it holds,
    one the worker's own ``formats`` allow."""
    from .listing import read_entry

    within = _param(params, "within", (str,), required=True)
    _check_within(within)
    path = _param(params, "path", (str,), required=True)
    include = tuple(_param(params, "include", (list,), []))
    asked = _formats(params)
    if asked is not None and _settings["formats"] is not None:
        asked = sorted(set(asked) & _settings["formats"]) or None
    entry, image = read_entry(
        path,
        _param(params, "rel", (str,), required=True),
        _param(params, "name", (str,), required=True),
        _param(params, "file", (dict,)),
        within=within,
        include=include,
        reader_message=_param(params, "reader_message", (bool,), True),
        max_file_bytes=_settings["max_file_bytes"],
        refuse_hard_links=_settings["refuse_hard_links"],
        formats=asked,
        limits=_settings["limits"],
        subfolders=_subfolders(within),
    )
    return entry, image if "preview_data" in include else None


# --------------------------------------------------------------------------- model-file jobs
RENDER_MODES = ("auto", "never", "always")


def _open_model(params: dict[str, Any]):
    """The model file ``params`` names, opened as every model-file job opens one (also
    :mod:`solidseas_app.viewer.modeljobs`, which shares this and :func:`_param`): only
    as a format the worker reads, within the worker's limits."""
    from .formats import open_model

    path = _param(params, "path", (str,), required=True)
    within = _param(params, "within", (str,))
    _check_within(within)
    return open_model(
        path,
        name=_param(params, "name", (str,)),
        within=within,
        max_file_bytes=_settings["max_file_bytes"],
        refuse_hard_links=_settings["refuse_hard_links"],
        hold_open=True,
        formats=_model_formats(),
        limits=_settings["limits"],
        subfolders=_subfolders(within),
    )


def model_summary(params: dict[str, Any]) -> dict[str, Any]:
    """``model_summary`` data of one model file (``include``: the optional parts,
    default all three). A reference's ``resolution.path`` is relative to the
    document's folder; one that is not (an Alibre component found under a further
    root, which the service never passes) is sent as null, so no answer holds a
    path on this machine."""
    include = _param(params, "include", (list,), list(model.MODEL_SUMMARY_PARTS))
    with _open_model(params) as doc:
        data = model.build_model_summary(doc, include=tuple(include))
    for ref in data.get("references") or []:
        res = ref.get("resolution")
        where = res.get("path") if isinstance(res, dict) else None
        if isinstance(where, str) and (os.path.isabs(where) or where.startswith(("/", "\\")) or ":" in where):
            res["path"] = None
    return data


def model_properties(params: dict[str, Any]) -> dict[str, Any]:
    """``properties`` data of one model file."""
    with _open_model(params) as doc:
        return model.build_model_properties(
            doc,
            view=_param(params, "view", (str,), "effective"),
            configuration=_param(params, "configuration", (str,)),
        )


def model_entry(params: dict[str, Any]) -> tuple[dict[str, Any], bytes | None]:
    """One folder-listing entry for a model file (:func:`solidseas.listing.read_model_entry`),
    with the stored preview as a PNG SolidSeas wrote as the payload when the listing
    inlines images. ``formats`` (format ids) are the formats the listing reads; the
    file is read only as one of those that the worker reads too."""
    from .listing import read_model_entry

    within = _param(params, "within", (str,), required=True)
    _check_within(within)
    include = tuple(_param(params, "include", (list,), []))
    entry, image = read_model_entry(
        _param(params, "path", (str,), required=True),
        _param(params, "rel", (str,), required=True),
        _param(params, "name", (str,), required=True),
        _param(params, "file", (dict,)),
        within=within,
        include=include,
        reader_message=_param(params, "reader_message", (bool,), True),
        max_file_bytes=_settings["max_file_bytes"],
        refuse_hard_links=_settings["refuse_hard_links"],
        formats=_model_formats(_formats(params)),
        limits=_settings["limits"],
        subfolders=_subfolders(within),
    )
    return entry, image if "preview_data" in include else None


def model_preview(params: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    """A model file's preview as a PNG SolidSeas wrote: the image it stores (sanitised,
    a bitmap converted), else one rendered from its geometry
    (:func:`solidseas.render.render_preview`). ``render``: ``auto`` (the default),
    ``never`` (the stored image or ``no_preview``) or ``always``; ``width`` and
    ``height`` size a rendered one."""
    from .formats._source import preview_png
    from .render import DEFAULT_HEIGHT, DEFAULT_WIDTH, render_preview

    mode = _param(params, "render", (str,), "auto")
    if mode not in RENDER_MODES:
        raise InvalidArgumentError(
            f"render is one of {', '.join(RENDER_MODES)}", detail={"parameter": "render"}
        )
    width = _param(params, "width", (int,), DEFAULT_WIDTH)
    height = _param(params, "height", (int,), DEFAULT_HEIGHT)
    with _open_model(params) as doc:
        if mode != "always":
            got = preview_png(doc.preview(), doc.limits)
            if got is not None:
                png, w, h, stream = got
                return {
                    "mime": "image/png",
                    "width": w,
                    "height": h,
                    "stream": stream,
                    "source": "stored",
                }, png
            if mode == "never":
                raise NoPreviewError("the file stores no preview image")
        r = render_preview(doc, width=width, height=height, limits=doc.limits)
    meta = {"mime": r.mime, "width": r.width, "height": r.height, "stream": None, "source": "rendered"}
    meta["partial"] = r.partial
    return meta, r.data


def batch_document(params: dict[str, Any]) -> dict[str, Any]:
    """One document of ``solidseas batch`` (:func:`solidseas.cli.batch_row`): its report
    row and its ``report.jsonl`` detail, with its preview and Parasolid files written
    below ``out_dir``. Not in the default job table: see the module notes."""
    from .cli import batch_row

    folder = _param(params, "folder", (str,), required=True)
    _check_within(folder)
    opts = _param(params, "opts", (dict,), required=True)
    row, detail = batch_row(
        _param(params, "path", (str,), required=True),
        folder,
        _param(params, "out_dir", (str,), required=True),
        opts,
    )
    return {"row": row, "detail": detail}


def identities(params: dict[str, Any]) -> list[dict[str, Any]]:
    """The creation time each listed document stores about itself
    (:func:`solidseas.resolve.identity.own_identity`), one batch per resolution."""
    from .resolve.identity import own_identity

    items = _param(params, "items", (list,), required=True)
    if len(items) > MAX_IDENTITY_ITEMS:
        raise InvalidArgumentError("too many identity reads in one job", detail={"parameter": "items"})
    out = []
    for item in items:
        try:
            if not isinstance(item, dict):
                raise InvalidArgumentError("an identity read is an object", detail={"parameter": "items"})
            with _open({"path": item.get("path"), "within": item.get("within")}) as doc:
                ident = own_identity(doc)
            out.append({"creation_time": ident.creation_time, "source": ident.source, "error": None})
        except Exception as exc:  # one unreadable candidate never stops the batch
            out.append({"creation_time": None, "source": None, "error": model.error_code(exc)})
    return out


def catalog_document(params: dict[str, Any]) -> tuple[dict[str, Any], bytes | None]:
    """The catalog record of one document (:func:`solidseas.catalog.record.build_record`),
    with its preview image as the payload when ``previews`` is true. ``graph`` false leaves
    out the model graph (a record too large with it is read again without). A STEP file
    wearing a SOLIDWORKS extension answers ``{"not_solidworks": "step"}``. A file of
    another format SolidSeas reads, by its name's extension, is opened as the folder
    listing opens one (:func:`solidseas.formats.open_any`): a model file's record is
    :func:`~solidseas.catalog.record.build_model_record`'s, and a SOLIDWORKS document
    wearing another extension gets a SOLIDWORKS record."""
    from .catalog.record import RECORD_VERSION, build_model_record, build_record
    from .listing import sniff_format
    from .resolve.names import is_document_name

    previews = _param(params, "previews", (bool,), True)
    graph = _param(params, "graph", (bool,), True)
    path = _param(params, "path", (str,), required=True)
    if not is_document_name(_param(params, "name", (str,)) or path):
        from .formats import open_any
        from .formats.base import ModelDocument

        within = _param(params, "within", (str,))
        _check_within(within)
        with open_any(
            path,
            name=_param(params, "name", (str,)),
            within=within,
            max_file_bytes=_settings["max_file_bytes"],
            refuse_hard_links=_settings["refuse_hard_links"],
            hold_open=True,
            formats=_model_formats(),
            limits=_settings["limits"],
            subfolders=_subfolders(within),
        ) as doc:
            if isinstance(doc, ModelDocument):
                return build_model_record(doc, previews=previews)
            return build_record(doc, previews=previews, graph=graph)
    try:
        with _open(params) as doc:
            return build_record(doc, previews=previews, graph=graph)
    except UnknownFormatError:
        within = _param(params, "within", (str,))
        if sniff_format(_param(params, "path", (str,), required=True), within=within) == "step":
            return {"v": RECORD_VERSION, "not_solidworks": "step"}, None
        raise


def content_hash(params: dict[str, Any]) -> dict[str, Any]:
    """The SHA-256 of one file's bytes, read ``within`` its root in 1 MiB chunks without
    recalling a placeholder or crossing a link. ``stable`` is false when the file's size or
    modification time changed while it was read (the hash is then not to be kept)."""
    from .formats.solidworks._io import open_readonly

    path = _param(params, "path", (str,), required=True)
    within = _param(params, "within", (str,), required=True)
    _check_within(within)
    h = hashlib.sha256()
    n = 0
    with open_readonly(path, within=within) as fh:
        before = os.fstat(fh.fileno())
        if _settings["refuse_hard_links"] and before.st_nlink > 1:
            raise LinkRefusedError("the file has more than one name", detail={"rule": "hard_link"})
        limit = _settings["max_file_bytes"]
        if limit is not None and before.st_size > limit:
            raise FileTooLargeError(
                "the file is larger than the configured maximum",
                detail={"limit": limit, "value": before.st_size},
            )
        while True:
            chunk = fh.read(HASH_CHUNK)
            if not chunk:
                break
            h.update(chunk)
            n += len(chunk)
        after = os.fstat(fh.fileno())
    stable = (before.st_size, before.st_mtime_ns) == (
        after.st_size,
        after.st_mtime_ns,
    ) and n == before.st_size
    return {
        "sha256": h.hexdigest(),
        "bytes": n,
        "size": before.st_size,
        "mtime_ns": str(before.st_mtime_ns),
        "stable": stable,
    }


__all__ = [
    "batch_document",
    "catalog_document",
    "content_hash",
    "bom",
    "components",
    "configurations",
    "configure",
    "display_glb",
    "document_summary",
    "identities",
    "listing_entry",
    "model_entry",
    "model_preview",
    "model_properties",
    "model_summary",
    "path_report",
    "preview",
    "properties",
    "references",
    "resolution_input",
]
