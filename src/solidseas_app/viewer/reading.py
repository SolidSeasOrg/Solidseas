"""What the viewer shows, read through the ``solidseas`` library, and the two exports.

Nothing here imports Qt, so it runs in worker threads and in tests as it is.

Every document is opened read-only ``within`` the folder the user opened, the way
the folder listing opens it: no link below that folder is crossed and a cloud
placeholder is never recalled. A component's file that reference resolution
found outside that folder is opened within its own folder instead, as the
resolution's identity reads open it, and a virtual component is read as the
nested document it is, from inside its assembly (:class:`Source`). Resolution
looks at a stored path outside the opened folder, on a drive of this computer,
unless ``outside`` is false (Settings, Look for Referenced Files Only in the
Opened Folder): then it looks in that folder alone.
``open_document`` reads the file whole and closes the handle before it
returns, so the viewer never holds a document open.

Each part of the details panel is a *section*: a plain dict with ``ok``, the
section's ``data`` or its ``error`` (``solidseas.model.error_info``) and the
``seconds`` it took. One section failing never stops the others. An assembly's
bill of materials (``bom``) is read with the resolution the references section
made, so its rows find the files the References tab shows; all three BOM types
are read at once, each component file once, and the panel switches between
them without reading again.

Exports go through the command line's write guards (``solidseas.cli``): the
output folder must not be the folder of the document or the opened folder, or
lie inside either; a SOLIDWORKS file, the source document and a hard link are
never written; and an existing file is replaced only when the user asks. A BOM
export writes the BOM the panel shows, as CSV or as the ``bom`` JSON envelope.
"""

import datetime
import math
import os
import re
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import Any

from solidseas import Root, Roots, model, open_document
from solidseas import bom as bom_lib
from solidseas import cli as _cli
from solidseas.errors import InvalidArgumentError, NoPreviewError
from solidseas.resolve import IndexCache, resolve_references

ROOT_ID = "folder"  # the root id the opened folder gets for reference resolution
SECTIONS = ("summary", "preview", "components", "references", "bom", "paths")
BOM_FORMATS = {"csv": ("text/csv", ".csv"), "json": ("application/json", ".json")}
DOC_TYPES = {"part": "Part", "assembly": "Assembly", "drawing": "Drawing"}
_EXTENSION_TYPES = {".sldprt": "part", ".sldasm": "assembly", ".slddrw": "drawing"}

Section = dict[str, Any]


def host_path(folder: str, rel: str) -> str:
    """The absolute path of a listing entry: ``rel`` is ``/``-separated below ``folder``."""
    return os.path.join(folder, *rel.split("/"))


@dataclass(frozen=True)
class Source:
    """Where a document the details panel shows is read from.

    ``path`` is the file on disk, opened read-only ``within`` a folder it must lie
    below: the opened folder for a listed document, the file's own folder for one
    outside it. ``nested`` is the chain of nested-document streams to follow from
    that file, empty for the file itself: ``("VirtualComp/Part12-sldprt",)`` is a
    virtual part stored inside the assembly at ``path``."""

    path: str
    within: str
    nested: tuple[str, ...] = ()

    def inside(self, stream: str) -> "Source":
        """The nested document in ``stream`` of this one."""
        return Source(self.path, self.within, (*self.nested, stream))


@contextmanager
def opened(path: str, within: str, nested: tuple[str, ...] = ()) -> Iterator[Any]:
    """The document at ``path``, opened read-only within ``within``, or the nested
    document ``nested`` leads to inside it. Closed on exit, with every nested one."""
    with open_document(path, within=within) as doc:
        for stream in nested:
            doc = doc.nested(stream)
        yield doc


def source_info(path: str, nested: tuple[str, ...] = ()) -> dict[str, Any]:
    """The JSON envelope's ``source``: ``{"file"}``, and ``nested`` for a nested
    document as the command line gives it (a list when one is nested in another)."""
    if not nested:
        return {"file": path}
    return {"file": path, "nested": nested[0] if len(nested) == 1 else list(nested)}


def export_stem(path: str, nested: tuple[str, ...] = ()) -> str:
    """The name an export of the document starts with: the file's name without its
    extension, and for a nested document ``_`` and the stream's last part, as
    ``solidseas preview --nested`` names it."""
    stem = os.path.splitext(os.path.basename(path))[0]
    if nested:
        stem += "_" + re.sub(r"[^\w.-]", "_", nested[-1].rsplit("/", 1)[-1])
    return stem


def doc_type_of(entry: dict[str, Any]) -> str | None:
    """``part``, ``assembly`` or ``drawing``: what the file says, else its extension."""
    if entry.get("doc_type"):
        return entry["doc_type"]
    ext = os.path.splitext(entry.get("path") or "")[1].lower()
    return _EXTENSION_TYPES.get(ext)


def _timed(fn: Callable[[], Any]) -> Section:
    t = time.perf_counter()
    try:
        data = fn()
    except Exception as exc:  # shown in the panel; one section never stops the others
        return {"ok": False, "error": model.error_info(exc), "seconds": time.perf_counter() - t}
    return {"ok": True, "data": data, "seconds": time.perf_counter() - t}


def _summary(doc, path: str, nested: tuple[str, ...] = ()) -> dict[str, Any]:
    data = model.build_document_summary(doc)
    envelope = model.envelope("document_summary", data, source=source_info(path, nested))
    return {"summary": data, "json": model.dumps(envelope, pretty=True)}


def _preview(doc) -> dict[str, Any]:
    pv = doc.preview()
    if pv is None:
        return {"image": None, "reason": "not_stored"}
    return {
        "image": pv.data,
        "reason": None,
        "mime": pv.mime,
        "width": pv.width,
        "height": pv.height,
        "stream": pv.stream,
    }


def _components(doc, configuration: str | None = None) -> dict[str, Any]:
    if doc.doc_type == "assembly":
        return {"kind": "assembly", "components": model.build_components(doc, configuration=configuration)}
    if doc.doc_type == "drawing":
        return {"kind": "drawing", "references": model.build_references(doc)}
    return {"kind": doc.doc_type or "unknown"}


def roots_for(folder: str) -> Roots:
    """The opened folder as the one root reference resolution searches."""
    return Roots([Root(ROOT_ID, os.path.abspath(folder))])


def _references(
    doc, folder: str, cache: IndexCache | None, keep: dict | None = None, *, outside: bool = True
) -> dict[str, Any]:
    if doc.doc_type not in ("assembly", "drawing"):
        return {"kind": doc.doc_type or "unknown"}
    res = resolve_references(doc, roots_for(folder), cache=cache, allow_outside_roots=outside)
    if keep is not None:
        keep["resolution"] = res
    return {"kind": doc.doc_type, "references": model.build_references(doc, resolution=res)}


def _bom(
    doc,
    folder: str,
    cache: IndexCache | None,
    configuration: str | None = None,
    resolution=None,
    *,
    outside: bool = True,
) -> dict[str, Any]:
    """The ``bom`` data of every BOM type of one configuration, each file read once, with
    the opened folder as the root (and ``resolution`` when the references section made
    one); ``outside`` as for :func:`read_document`."""
    if doc.doc_type != "assembly":
        return {"kind": doc.doc_type or "unknown"}
    boms = bom_lib.build_boms(
        doc,
        configuration,
        roots=roots_for(folder),
        resolution=resolution,
        cache=cache,
        allow_outside_roots=outside,
    )
    first = next(iter(boms.values()))
    return {
        "kind": "assembly",
        "configuration": first.configuration,
        "boms": {t: model.bom_data(b) for t, b in boms.items()},
    }


def read_document(
    path: str,
    folder: str,
    *,
    cache: IndexCache | None = None,
    cancelled: Callable[[], bool] = lambda: False,
    within: str | None = None,
    nested: tuple[str, ...] = (),
    outside: bool = True,
) -> Iterator[tuple[str, Section]]:
    """Read one document for the details panel, a section at a time.

    Yields ``(name, section)`` for each of :data:`SECTIONS` in order, or a single
    ``("open", section)`` with the error when the file does not open. Stops
    between sections when ``cancelled()`` turns true. ``cache`` keeps the folder
    index between documents; it is not thread-safe, so share it only between
    reads that run one after another.

    ``folder`` is the opened folder, the one root reference resolution searches,
    and with ``outside`` (the default) a stored path outside it on a drive of this
    computer is looked at too; without it, nothing outside it is.
    The file is opened within ``within`` (by default ``folder``), and ``nested``
    reads a nested document inside it instead (:class:`Source`).
    """
    t = time.perf_counter()
    stack = ExitStack()
    try:
        doc = stack.enter_context(opened(path, within or folder, nested))
    except Exception as exc:  # the error code and message are what the panel shows
        yield "open", {"ok": False, "error": model.error_info(exc), "seconds": time.perf_counter() - t}
        return
    with stack:
        made: dict[str, Any] = {}  # the references' resolution, which the BOM uses again
        steps: tuple[tuple[str, Callable[[], Any]], ...] = (
            ("summary", lambda: _summary(doc, path, nested)),
            ("preview", lambda: _preview(doc)),
            ("components", lambda: _components(doc)),
            ("references", lambda: _references(doc, folder, cache, made, outside=outside)),
            ("bom", lambda: _bom(doc, folder, cache, resolution=made.get("resolution"), outside=outside)),
            ("paths", lambda: model.build_path_report(doc)),
        )
        for name, step in steps:
            if cancelled():
                return
            yield name, _timed(step)


def read_components(
    path: str,
    folder: str,
    configuration: str | None,
    *,
    within: str | None = None,
    nested: tuple[str, ...] = (),
) -> Section:
    """The components section for another assembly configuration."""

    def run() -> dict[str, Any]:
        with opened(path, within or folder, nested) as doc:
            return _components(doc, configuration)

    return _timed(run)


def read_bom(
    path: str,
    folder: str,
    configuration: str | None,
    *,
    cache: IndexCache | None = None,
    within: str | None = None,
    nested: tuple[str, ...] = (),
    outside: bool = True,
) -> Section:
    """The bom section for another assembly configuration (``outside`` as for
    :func:`read_document`)."""

    def run() -> dict[str, Any]:
        with opened(path, within or folder, nested) as doc:
            return _bom(doc, folder, cache, configuration, outside=outside)

    return _timed(run)


# --------------------------------------------------------------------------- exports
def output_dir(out_dir: str, path: str, folder: str) -> str:
    """The output folder, refused inside the document's folder or the opened folder."""
    if not out_dir.strip():
        raise InvalidArgumentError("no output folder was given", detail={"parameter": "out_dir"})
    sources = [os.path.dirname(os.path.abspath(path)), os.path.abspath(folder)]
    return _cli.check_output_dir(out_dir, sources, allow_source_dir=False)


def export_parasolid(
    path: str,
    folder: str,
    out_dir: str,
    *,
    text: bool,
    overwrite: bool,
    within: str | None = None,
    nested: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Write the document's Parasolid bodies (``.x_b``, and ``.x_t`` with ``text``) into
    ``out_dir``: the ``parasolid_result`` data. Every output path is checked before
    the first file is written; a refusal raises ``OutputRefusedError``. ``within``
    and ``nested`` are as for :func:`read_document`."""
    out = output_dir(out_dir, path, folder)
    with opened(path, within or folder, nested) as doc:
        res = doc.parasolid()
        stem = export_stem(path, nested)
        written = _cli._write_parasolid(
            res,
            stem,
            out,
            [path],
            text=text,
            raw=False,
            allow_source_dir=False,
            force=overwrite,
            source_dirs=[os.path.abspath(folder)],
        )
    return model.build_parasolid_result(len(res.bodies), written, res.problems)


def export_preview(
    path: str,
    folder: str,
    out_dir: str,
    *,
    overwrite: bool,
    within: str | None = None,
    nested: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Write the stored preview image (PNG, or BMP for the older DIB) into ``out_dir``:
    the ``file_written`` data. Raises ``NoPreviewError`` when the file stores none.
    ``within`` and ``nested`` are as for :func:`read_document`."""
    out = output_dir(out_dir, path, folder)
    with opened(path, within or folder, nested) as doc:
        pv = doc.preview()
    if pv is None:
        raise NoPreviewError("the document stores no preview image")
    stem = export_stem(path, nested)
    target = _cli.check_output_file(
        os.path.join(out, stem + pv.extension),
        [path],
        allow_source_dir=False,
        force=overwrite,
        source_dirs=[os.path.abspath(folder)],
    )
    _cli._write(target, pv.data)
    return model.build_file_written(
        target, len(pv.data), stream=pv.stream, mime=pv.mime, width=pv.width, height=pv.height
    )


def export_bom(
    path: str,
    folder: str,
    out_dir: str,
    data: dict[str, Any],
    *,
    fmt: str,
    overwrite: bool,
    nested: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Write ``data`` (one BOM of the bom section) into ``out_dir`` as ``fmt``, ``csv``
    (UTF-8 with a byte order mark, :func:`solidseas.bom.csv_bytes`) or ``json`` (the
    ``bom`` envelope, as ``solidseas bom --json`` prints it): the ``file_written`` data.
    The file is named after the document and the BOM type, ``frame_bom_indented.csv``."""
    if fmt not in BOM_FORMATS:
        raise InvalidArgumentError("a BOM is exported as csv or json", detail={"parameter": "format"})
    mime, ext = BOM_FORMATS[fmt]
    out = output_dir(out_dir, path, folder)
    if fmt == "csv":
        payload = bom_lib.csv_bytes(data)
    else:
        envelope = model.envelope("bom", data, source=source_info(path, nested))
        payload = (model.dumps(envelope, pretty=True) + "\n").encode("utf-8")
    target = _cli.check_output_file(
        os.path.join(out, f"{export_stem(path, nested)}_bom_{data['type']}{ext}"),
        [path],
        allow_source_dir=False,
        force=overwrite,
        source_dirs=[os.path.abspath(folder)],
    )
    _cli._write(target, payload)
    return model.build_file_written(target, len(payload), mime=mime)


# --------------------------------------------------------------------------- 3D files of other formats
MODEL_SECTIONS = ("summary", "components", "references", "preview", "geometry")


def is_model(entry: dict[str, Any] | None, path: str | None = None) -> bool:
    """Whether the document of a listing ``entry`` (or at ``path``, for one opened apart
    from the list) is a file of another format than SOLIDWORKS that SolidSeas reads:
    the listing read it as one (its ``model`` object), or its extension names such a
    format."""
    if entry is not None and entry.get("model") is not None:
        return bool(entry["model"].get("readable", True))
    from solidseas.formats import registry

    spec = registry.by_extension(path or (entry or {}).get("path"))
    return spec is not None and spec.id != registry.SOLIDWORKS and registry.readable(spec.id)


def _pool_section(call: Callable[[], Any]) -> Section:
    """A section from a worker job: its data (and payload), or its error object (the
    worker's own error, a time-out or a crash), with the seconds it took."""
    t = time.perf_counter()
    try:
        result = call()
    except Exception as exc:  # the job's own error (its code survives), a time-out, a crash
        return {"ok": False, "error": model.error_info(exc), "seconds": time.perf_counter() - t}
    return {"ok": True, "data": result, "seconds": time.perf_counter() - t}


def read_model(
    path: str,
    folder: str,
    pool,
    *,
    within: str | None = None,
    cap: int = 1_000_000,
    cancelled: Callable[[], bool] = lambda: False,
) -> Iterator[tuple[str, Section]]:
    """Read a file of another format for the details panel, a section at a time, every
    byte of it in a worker of ``pool`` (:mod:`.modelpool`, :mod:`.modeljobs`), never in
    this process.

    Yields ``("summary", ...)`` (``summary``, the ``model_summary`` data, and ``json``,
    its envelope as the command line prints it), ``("components", ...)`` (an
    assembly's rows, :func:`.modelview.components_data`, else what it is),
    ``("references", ...)``, ``("preview", ...)`` (the stored image as a PNG
    SolidSeas wrote, else one rendered from the geometry) and ``("geometry", ...)``
    (the Overview's measures), or a single ``("open", ...)`` with the error when the
    file does not open. ``cap`` bounds the triangles read, as the 3D view's limit
    does."""
    from .modeljobs import DETAILS_JOB, VIEW_JOB

    params = {"path": path, "within": within or folder, "folder": folder}
    first = _pool_section(lambda: pool.call(DETAILS_JOB, params).data)
    if not first["ok"]:
        yield "open", first
        return
    data = first["data"]
    summary = data["summary"]
    envelope = model.envelope("model_summary", summary, source=source_info(path))
    yield (
        "summary",
        {**first, "data": {"summary": summary, "json": model.dumps(envelope, pretty=True), "model": True}},
    )
    if cancelled():
        return
    doc_type = summary.get("doc_type") or "part"
    what = f"{summary.get('format_name') or 'model'} {doc_type}"
    if data.get("components") is not None:
        components = {"kind": "assembly", "components": data["components"], "model": True}
    else:
        components = {"kind": doc_type, "model": True, "message": f"This {what} has no components."}
    yield "components", {"ok": True, "data": components, "seconds": 0.0}
    if data.get("references") is not None:
        references = {"kind": "assembly", "references": data["references"], "model": True}
    else:
        references = {"kind": doc_type, "model": True, "message": f"This {what} names no other files."}
    yield "references", {"ok": True, "data": references, "seconds": 0.0}
    if cancelled():
        return
    viewed = _pool_section(lambda: pool.call(VIEW_JOB, {**params, "cap": cap}))
    if not viewed["ok"]:
        yield "preview", viewed
        yield "geometry", viewed
        return
    result = viewed["data"]
    meta, png = result.data or {}, result.payload
    pv = meta.get("preview")
    if pv is not None and png is not None:
        preview = {
            "image": png,
            "reason": None,
            "mime": "image/png",
            "width": pv.get("width"),
            "height": pv.get("height"),
            "stream": pv.get("stream"),
            "source": pv.get("source"),
            "partial": bool(pv.get("partial")),
        }
    else:
        preview = {"image": None, "reason": "not_stored", "detail": meta.get("preview_reason")}
    yield "preview", {"ok": True, "data": preview, "seconds": viewed["seconds"]}
    if meta.get("geometry") is not None:
        yield "geometry", {"ok": True, "data": meta["geometry"], "seconds": viewed["seconds"]}
    else:
        yield "geometry", {"ok": False, "error": meta.get("geometry_error"), "seconds": viewed["seconds"]}


def export_image(
    png: bytes,
    path: str,
    folder: str,
    out_dir: str,
    *,
    overwrite: bool,
    width: int | None = None,
    height: int | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Write a preview image the details panel holds (a PNG SolidSeas wrote: a model
    file's stored image, sanitised, or one rendered from its geometry) into
    ``out_dir`` through the write guards, named after the document: the
    ``file_written`` data."""
    out = output_dir(out_dir, path, folder)
    target = _cli.check_output_file(
        os.path.join(out, export_stem(path) + ".png"),
        [path],
        allow_source_dir=False,
        force=overwrite,
        source_dirs=[os.path.abspath(folder)],
    )
    _cli._write(target, png)
    return model.build_file_written(
        target, len(png), mime="image/png", width=width, height=height, source=source
    )


# --------------------------------------------------------------------------- display text
def mm(metres: float | None) -> str:
    """Metres as millimetres with at most three decimals: ``0.05`` gives ``50``."""
    if metres is None or not math.isfinite(metres):
        return ""
    text = f"{metres * 1000:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


_AXES = ("X", "Y", "Z")


def rotation_text(rotation: list[list[float]] | None) -> str:
    """A rotation matrix (row by row) as an angle about an axis: ``90° about Z``,
    ``40° about (0.577, 0.577, 0.577)``, or ``none``."""
    if not rotation:
        return ""
    r = rotation
    cos = max(-1.0, min(1.0, (r[0][0] + r[1][1] + r[2][2] - 1) / 2))
    angle = math.degrees(math.acos(cos))
    if angle < 1e-6:
        return "none"
    axis = [r[2][1] - r[1][2], r[0][2] - r[2][0], r[1][0] - r[0][1]]
    norm = math.sqrt(sum(a * a for a in axis))
    if norm < 1e-9:  # a half turn: the axis comes from the diagonal
        axis = [math.sqrt(max(0.0, (r[i][i] + 1) / 2)) for i in range(3)]
        k = max(range(3), key=lambda i: axis[i])
        axis = [axis[i] if i == k or r[k][i] >= 0 else -axis[i] for i in range(3)]
        norm = math.sqrt(sum(a * a for a in axis)) or 1.0
    axis = [a / norm for a in axis]
    deg = f"{angle:.3f}".rstrip("0").rstrip(".")
    for i, a in enumerate(axis):
        if abs(a) > 1 - 1e-9:
            return f"{deg}° about {'-' if a < 0 else ''}{_AXES[i]}"
    return f"{deg}° about ({', '.join(f'{a:.3f}' for a in axis)})"


def size_text(size: int | None) -> str:
    if size is None:
        return ""
    if size < 1024:
        return f"{size} bytes"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def time_text(iso: str | None) -> str:
    """An ISO 8601 time as local time to the minute; a time without a zone stays as stored."""
    if not iso:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    if dt.tzinfo is not None:
        dt = dt.astimezone()
    return dt.strftime("%Y-%m-%d %H:%M")


def date_text(iso: str | None) -> str:
    """A date-only value, such as a custom property of type date, as ``2024-03-15``.

    On fixture o14 SOLIDWORKS stored 3/15/2024 as 16:00 UTC, which is noon
    on that day where the file was saved (UTC-4). Noon keeps the day in UTC the
    typed day for any saving time zone from UTC-11 to UTC+11, while the viewer's
    own time zone would move it to the next day from UTC+8 eastwards. A time
    without a zone keeps its own day."""
    if not iso:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.UTC)
    return dt.strftime("%Y-%m-%d")


def release_text(saved_version: dict[str, Any] | None, *, short: bool = False) -> str:
    """``SOLIDWORKS 2024`` (``SW 2024`` with ``short``), or the format version when the
    release is not known."""
    if not saved_version:
        return ""
    release = saved_version.get("release")
    if release:
        if short and release.startswith("SOLIDWORKS "):
            return "SW " + release[len("SOLIDWORKS ") :]
        return release
    fv = saved_version.get("format_version")
    return f"format {fv}" if fv is not None else "unknown"
