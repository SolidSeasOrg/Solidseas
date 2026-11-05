"""Command line interface: ``solidseas <command> ...`` or ``python -m solidseas <command> ...``.

Every command opens source documents read-only and accepts ``--json``. With
``--json`` a command prints exactly one JSON document on standard output (an
envelope from :mod:`solidseas.model`; ``schema`` prints a JSON Schema) and
nothing on standard error, usage errors included: ``--version`` prints the
``version`` envelope, and ``--help`` an ``invalid_argument`` error whose
``detail.usage`` holds the help text. Without it, results are human-readable
and messages go to standard error.

Exit codes (``docs/API.md`` section 7): 0 success, 1 failed, 2 usage error,
3 refused by a safety rule, 4 partial (``list`` or ``batch`` finished with at
least one item error, a resolution index or a path report cut short), 130
interrupted. The code for a failure comes from the error code of the
exception, through ``solidseas.model.ERROR_CODES``.

``index`` builds or updates a catalog (``solidseas.catalog``) of one or more
folders, in the user's cache folder unless ``--in-project`` or ``--db`` says
otherwise; ``where-used``, ``search``, ``duplicates``, ``missing``, ``changes``
and ``catalog`` query it, read-only, and never open a CAD file. Without
``--catalog``, ``--db`` or ``--in-project`` they use the catalog in the cache
whose root holds the file named (``where-used``) or the current folder.

The single-file commands also read 3D files of other formats (provisional,
``docs/API.md`` 3.20): ``info`` prints a ``model_summary``, ``props`` and
``configurations`` their usual kinds, ``preview`` the image the file stores or
one rendered from its geometry (``--render``, ``--stored``) and ``export`` an
STL or 3MF of it, or the STEP of a Parasolid transmit file's part (another
format answers ``not_implemented`` for ``--format step``). The commands that
only make sense for SOLIDWORKS documents (``components``, ``references``,
``bom``, ``paths``, ``streams``, ``dump``, ``parasolid``) answer
``not_implemented`` for them, and a format SolidSeas knows but cannot read
answers ``format_not_supported``. ``list --formats`` lists them too.

``drawing ACTION`` (provisional, ``docs/drawings/cli.md``) makes, exports, updates,
checks and shows drawings of parts (``solidseas.drawing``) and prints Drawing
Settings; under ``--json`` every action prints one ``drawing_result``. It never signs
or releases a drawing, never writes a file it did not write, and never replaces a
released export (``docs/DRAWINGS.md`` 12.6).

``serve`` runs the REST service (``solidseas.serve``) until it is stopped: it
prints one ``serve_started`` line on standard output when it is ready (one
compact JSON line under ``--json``) and logs to standard error. ``mcp`` offers the same
reads to an MCP app on standard input and output (``solidseas.serve.mcp``) until the app
closes standard input.

``list`` and ``batch`` read each document in a worker process
(:class:`solidseas.workers.WorkerPool`), as the service does: a file that hangs,
crashes its reader or needs more memory than the cap becomes one failed entry
(``timeout``, ``worker_crashed``, ``limit_exceeded``) and the run goes on.
``--in-process`` reads in this process instead. The workers start with spawn,
which runs the main module again in each of them: ``python -m solidseas`` and the
installed ``solidseas`` command are fine, and a script that calls :func:`main`
needs ``if __name__ == "__main__":``, as :mod:`solidseas.workers` explains.

Commands that write files refuse to write into the folder that holds a source
file, or any folder below it, unless ``--allow-source-dir`` is given; never
write a file with a SOLIDWORKS extension or over a source file; and never
overwrite an existing file unless ``--force`` is given.

``sldprt`` (provisional) is the one exception to the SOLIDWORKS extension rule: it
writes a new ``.sldprt`` made from a SolidCraft design, a SolidSeas IR file or a CadQuery
recording by the clean-room generator (``solidseas.nativewrite.generate``), reads it back
first, and never replaces a file, so it has no ``--force``.
"""

import argparse
import contextlib
import csv
import os
import re
import stat
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, replace
from typing import Any

from . import __version__, model
from . import bom as bom_mod
from .errors import (
    DrawingInvalidError,
    FormatNotSupportedError,
    InvalidArgumentError,
    ModelNotFoundError,
    NoPreviewError,
    OutputRefusedError,
    StreamNotFoundError,
    UnsupportedOperationError,
    VersionNotFoundError,
    VersionUnavailableError,
    WorkerCrashedError,
)
from .export import EXPORT_FORMATS
from .export import EXTENSIONS as EXPORT_EXTENSIONS
from .formats import open_any, registry
from .formats.base import ModelDocument
from .formats.limits import Limits
from .formats.solidworks import (
    SOLIDWORKS_EXTENSIONS,
    Document,
    LockedFileError,
    SldError,
    open_document,
)
from .formats.solidworks.components import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_NODES,
    MAX_DEPTH_LIMIT,
    MAX_NODES_LIMIT,
)
from .formats.solidworks.parasolid import DEFAULT_MAX_TRANSMIT_BYTES, ParasolidResult
from .formats.solidworks.preview import Preview, convert_image
from .listing import Scan
from .resolve import Resolution, resolve_references
from .roots import Root, Roots
from .trademarks import DISCLAIMER
from .walk import DEFAULT_MAX_EXAMINED, Walk

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_REFUSED, EXIT_PARTIAL, EXIT_INTERRUPTED = 0, 1, 2, 3, 4, 130
PROTECTED_EXTENSIONS = (*SOLIDWORKS_EXTENSIONS, ".prtdot", ".asmdot", ".drwdot", ".sldlfp", ".sldblk")
# Per-document deadlines in seconds, against the development corpus: its slowest summary took
# 0.3 s, and the slowest of its 400 largest documents about 25 s in batch (39 s with --text).
LIST_FILE_TIMEOUT_S = 30.0
BATCH_FILE_TIMEOUT_S = 300.0
WORKER_MEMORY_MB = 2048
MAX_JOBS = 64  # the most workers a WorkerPool runs
LIST_WORKERS = 2  # documents are read one at a time; the second worker stands in while one is replaced
# Jobs the CLI adds to its worker pool's table (WorkerPool(jobs=...)). A batch row writes the
# document's preview and Parasolid files, so its job is not in the default table and the
# service's workers can never run it. Tests point entries at stand-ins that hang or crash.
WORKER_JOBS: dict[str, str] = {"batch_document": "solidseas.jobs:batch_document"}


# An output location the CLI will not write to. The 0.1 name, kept as an alias of
# solidseas.errors.OutputRefusedError (error code output_refused).
Refused = OutputRefusedError


def exit_code(code: str) -> int:
    """The process exit code for an error code (``docs/API.md`` sections 5.6 and 7)."""
    spec = model.ERROR_CODES.get(code)
    return spec.cli_exit if spec is not None and spec.cli_exit is not None else EXIT_FAILED


# --------------------------------------------------------------------------- output safety
# Every refusal carries detail["rule"], so a caller such as the desktop viewer can say
# in its own words what was refused: device_path, alternate_stream, no_file_name,
# solidworks_file, source_document, source_folder, exists, hard_link, link and
# output_extension.
def _refused(message: str, rule: str) -> OutputRefusedError:
    return Refused(message, detail={"rule": rule})


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _parents(path: str) -> Iterable[str]:
    """``path``, then each folder above it up to its drive, share or root."""
    while True:
        yield path
        parent = os.path.dirname(path)
        if parent == path:
            return
        path = parent


def _existing(path: str) -> str | None:
    """``path`` if it exists, else its deepest folder that does, else None."""
    for p in _parents(os.path.abspath(path)):
        if os.path.exists(p):
            return p
    return None


def _is_within(path: str, folder: str) -> bool:
    """True when ``path`` is ``folder`` or lies below it.

    First by text, after resolving links. Then by file identity, because text
    misses another name for the same folder: an administrative share or other
    UNC alias of a local folder (``\\\\localhost\\C$\\...``), a second share of
    one folder, a mount point. The deepest part of ``path`` that exists, and
    each folder above it, both as written and with links resolved, is compared
    with ``folder`` by device and file number. A filesystem that reports no
    file number leaves the decision to the text."""
    p, f = _norm(path), _norm(folder)
    try:
        if os.path.commonpath([p, f]) == f:
            return True
    except ValueError:  # different drives on Windows
        pass
    try:
        target = os.stat(folder)
    except OSError:
        return False
    if not target.st_ino:
        return False
    existing = _existing(path)
    if existing is None:
        return False
    seen: set[str] = set()
    for start in (existing, os.path.realpath(existing)):
        for parent in _parents(start):
            key = os.path.normcase(parent)
            if key in seen:
                continue
            seen.add(key)
            try:
                if os.path.samestat(os.stat(parent), target):
                    return True
            except OSError:
                continue
    return False


def _is_link(path: str) -> bool:
    """A symbolic link or a junction: writing through either writes somewhere else."""
    try:
        if os.path.islink(path):
            return True
        isjunction = getattr(os.path, "isjunction", None)  # Python 3.12 and later
        return bool(isjunction and isjunction(path))
    except OSError:
        return False


def final_path(path: str) -> str:
    """The absolute path the operating system will actually create for ``path``.

    On Windows, trailing dots and spaces are dropped from the last component, as
    Windows itself does, and paths that name an alternate data stream, a device
    or the extended-length namespace are refused. Every check runs on this form,
    and the file is written at this form, so an alias cannot slip past a check.
    """
    raw = os.fspath(path)
    if raw.replace("/", "\\").startswith(("\\\\?\\", "\\\\.\\")):
        raise _refused(f"refusing a device or extended-length path: {path}", "device_path")
    full = os.path.abspath(raw)
    if os.name == "nt":
        _drive, rest = os.path.splitdrive(full)
        if ":" in rest:
            raise _refused(f"refusing a path that names an alternate data stream: {path}", "alternate_stream")
        head, tail = os.path.split(full)
        if tail:
            tail = tail.rstrip(" .")
            if not tail:
                raise _refused(f"refusing an output path with no usable file name: {path}", "no_file_name")
            full = os.path.join(head, tail)
    return full


def check_output_file(
    out: str,
    sources: Iterable[str],
    *,
    allow_source_dir: bool,
    force: bool,
    source_dirs: Iterable[str] = (),
) -> str:
    """Return the path to write, or raise :class:`Refused` unless writing it is safe.

    ``sources`` are the documents read: none is overwritten, and unless
    ``allow_source_dir`` the file is not written in or below a source's folder.
    ``source_dirs`` are further folders that were read, such as a folder a
    listing opened, kept out of in the same way. An existing file is replaced
    only with ``force``, and never when it is a hard link, a symbolic link or a
    junction."""
    final = final_path(out)
    exists = os.path.lexists(final)
    names = [final]
    if exists:
        names.append(os.path.realpath(final))  # long name of an 8.3 alias, target of a link
    if any(os.path.splitext(n)[1].lower() in PROTECTED_EXTENSIONS for n in names):
        raise _refused(f"refusing to write a SOLIDWORKS file: {out}", "solidworks_file")
    # The folder the data would land in: the file's own, and its link target's.
    folders = list(dict.fromkeys(os.path.dirname(n) for n in names))
    folder_refusal = _refused(
        f"refusing to write next to the source file ({out}); "
        "choose another folder or pass --allow-source-dir",
        "source_folder",
    )
    for src in sources:
        same = _norm(final) == _norm(src)
        if not same and exists:
            try:
                same = os.path.samefile(final, src)
            except OSError:
                same = False
        if same:
            raise _refused(f"refusing to overwrite the source document: {out}", "source_document")
        if not allow_source_dir and any(_is_within(f, os.path.dirname(src)) for f in folders):
            raise folder_refusal
    for d in source_dirs:
        if not allow_source_dir and any(_is_within(f, d) for f in folders):
            raise folder_refusal
    if exists:
        if not force:
            raise _refused(f"{out} already exists; pass --force to overwrite it", "exists")
        if _is_link(final):
            raise _refused(f"refusing to overwrite {out}: it is a link, and writing would follow it", "link")
        try:
            st = os.stat(final)
            # Only a file can be a hard link. A folder's link count on Linux and macOS
            # counts its subfolders' ".." entries, so it is above 1 for every folder.
            links = st.st_nlink if stat.S_ISREG(st.st_mode) else 1
        except OSError:
            links = 1
        if links > 1:
            raise _refused(
                f"refusing to overwrite {out}: it is a hard link, and another name shares its data",
                "hard_link",
            )
    return final


def check_output_dir(out_dir: str, source_dirs: Iterable[str], *, allow_source_dir: bool) -> str:
    final = final_path(out_dir)
    for d in source_dirs:
        if not allow_source_dir and _is_within(final, d):
            raise _refused(
                f"refusing to write inside the source folder ({out_dir}); "
                "choose another folder or pass --allow-source-dir",
                "source_folder",
            )
    return final


def _write(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


# --------------------------------------------------------------------------- printing
def _say(text: str = "") -> None:
    sys.stdout.write(text + "\n")


def _print_json(value: Any) -> None:
    sys.stdout.write(model.dumps(value, pretty=True) + "\n")


def _emit(args: argparse.Namespace, kind: str, data: Any, code: int = EXIT_OK) -> int:
    """Print the envelope of ``kind`` under ``--json``; return ``code``."""
    if args.json:
        _print_json(model.envelope(kind, data, source=args.source))
    return code


def _human(exc: BaseException) -> str:
    if isinstance(exc, FileNotFoundError):
        return f"not found: {exc.filename or exc}"
    if isinstance(exc, LockedFileError):
        return f"the file is locked by another program: {exc}"
    if isinstance(
        exc,
        (
            OutputRefusedError,
            InvalidArgumentError,
            NoPreviewError,
            UnsupportedOperationError,
            VersionNotFoundError,
            VersionUnavailableError,
        ),
    ):
        return str(exc)
    if isinstance(exc, KeyboardInterrupt):
        return "interrupted"
    return f"{type(exc).__name__}: {exc}"


def _failure(json_mode: bool, exc: BaseException, source: dict[str, Any] | None) -> int:
    code = model.error_code(exc)
    if json_mode:
        _print_json(model.error_envelope(exc, source=source))
    else:
        sys.stderr.write(f"solidseas: {_human(exc)}\n")
    return exit_code(code)


# --------------------------------------------------------------------------- document commands
def _model_info(args: argparse.Namespace, doc: ModelDocument) -> int:
    if args.nested is not None:
        raise InvalidArgumentError(
            "--nested applies to SOLIDWORKS assemblies", detail={"parameter": "nested"}
        )
    data = model.build_model_summary(doc, include=model.MODEL_SUMMARY_PARTS)
    if args.json:
        return _emit(args, "model_summary", data)
    variant = f" ({data['variant']})" if data["variant"] else ""
    units = data["units"]
    unit_text = units["length"] or "unknown"
    if units["source"] == "assumed":
        unit_text += " (assumed)"
    app = data["application"]
    _say(f"file:            {data['file']['name'] or '<memory>'}")
    _say(f"format:          {data['format_name']}{variant}")
    _say(f"document type:   {data['doc_type'] or 'unknown'}")
    _say(f"units:           {unit_text}")
    if app["name"]:
        _say(f"application:     {app['name']}{' ' + app['version'] if app['version'] else ''}")
    counts = {k: v for k, v in data["counts"].items() if v is not None}
    if counts:
        _say("counts:          " + ", ".join(f"{k} {v:,}" for k, v in counts.items()))
    _say(f"properties:      {len(data['properties'])}")
    pv = data["preview"]
    if pv["available"]:
        _say(f"preview:         {pv['width']} x {pv['height']} {pv['mime']} ({pv['stream']})")
    else:
        can = ", can be rendered" if pv["renderable"] else ""
        _say(f"preview:         none stored{can}")
    for w in data["warnings"]:
        _say(f"warning: {w['code']}: {w['message']}")
    return EXIT_OK


def cmd_info(args: argparse.Namespace, doc: Document) -> int:
    if isinstance(doc, ModelDocument):
        return _model_info(args, doc)
    data = model.build_document_summary(doc, nested=args.nested)
    if args.json:
        return _emit(args, "document_summary", data)
    sv = data["saved_version"]
    release = sv["release"] or "unknown release"
    if sv["release"] and not sv["release_verified"]:
        release += " (mapping is a hypothesis)"
    _say(f"file:            {data['file']['name'] or '<memory>'}")
    _say(f"format:          {data['format']} container")
    _say(f"document type:   {data['doc_type'] or 'unknown'}")
    _say(f"saved by:        format version {sv['format_version']}, {release}, build {sv['last_build']}")
    _say(f"configurations:  {len(data['configurations'])}")
    for c in data["configurations"]:
        flag = " (active)" if c["active"] else ""
        mat = f", material {c['material']['name']}" if c["material"] else ""
        _say(f"  - {c['name']}{flag}{mat}")
    if data["units"]:
        u = data["units"]
        _say(f"units:           {u['system']} ({u['length']}, {u['mass']})")
    counts, pv = data["counts"], data["preview"]
    _say(f"custom props:    {counts['custom_properties']}")
    _say(f"streams:         {counts['streams']}")
    if pv["available"]:
        _say(f"preview:         {pv['width']} x {pv['height']} {pv['mime']} ({pv['stream']})")
    else:
        _say(f"preview:         none ({pv['reason']})")
    _say(f"parasolid:       {counts['parasolid_partitions']} partition stream(s)")
    if counts["references"] is not None:
        _say(f"references:      {counts['references']}")
    if counts["nested_documents"]:
        _say(f"nested docs:     {counts['nested_documents']}")
    for w in data["warnings"]:
        _say(f"warning: {w['code']}: {w['message']}")
    return EXIT_OK


def cmd_props(args: argparse.Namespace, doc: Document) -> int:
    data = model.build_properties(
        doc, view=args.view, configuration=args.configuration, nested=args.nested
    )
    if args.json:
        return _emit(args, "properties", data)
    _print_json(data)  # the data alone, as JSON, as in 0.1
    return EXIT_OK


def cmd_configurations(args: argparse.Namespace, doc: Document) -> int:
    data = model.build_configurations(doc)
    if args.json:
        return _emit(args, "configurations", data)
    if not data["configurations"]:
        _say("no configurations stored")
    for c in data["configurations"]:
        flag = " (active)" if c["active"] else ""
        mat = f", material {c['material']['name']}" if c["material"] else ""
        _say(f"{c['name']}{flag}{mat}, {len(c['properties'])} properties")
    return EXIT_OK


def cmd_streams(args: argparse.Namespace, doc: Document) -> int:
    data = model.build_streams(doc)
    if args.json:
        return _emit(args, "streams", data)
    _say(f"{'size':>12} {'stored':>12} {'codec':<8} name")
    for r in data["streams"]:
        stored = "" if r["compressed_size"] is None else str(r["compressed_size"])
        name = r["name"].encode("unicode_escape").decode("ascii")
        _say(f"{r['size']:>12} {stored:>12} {r['codec']:<8} {name}")
    _say(f"{len(data['streams'])} streams")
    return EXIT_OK


def cmd_dump(args: argparse.Namespace, doc: Document) -> int:
    if args.stream not in doc.container:
        raise StreamNotFoundError(
            f"no stream named {args.stream!r}; list them with: solidseas streams FILE",
            detail={"stream": args.stream},
        )
    out = check_output_file(
        args.output, [args.file], allow_source_dir=args.allow_source_dir, force=args.force
    )
    data = doc.read_stream(args.stream, raw=args.raw)
    _write(out, data)
    stream = doc.container.info(args.stream).name
    if not args.json:
        _say(f"wrote {len(data)} bytes to {out}")
    return _emit(args, "file_written", model.build_file_written(out, len(data), stream=stream, raw=args.raw))


def _preview_output(pv: Preview, out: str, default_stem: str) -> tuple[str, bytes]:
    """Resolve the preview output path and bytes (converting with Pillow if the suffix asks for it)."""
    if os.path.isdir(out) or out.endswith(("/", "\\")):
        return os.path.join(out, default_stem + pv.extension), pv.data
    ext = os.path.splitext(out)[1].lower()
    if ext == pv.extension or ext == "":
        return (out if ext else out + pv.extension), pv.data
    if ext in (".png", ".bmp"):
        return out, convert_image(pv.data, ext[1:].upper())
    raise _refused(f"preview output must end in .png or .bmp, not {ext}", "output_extension")


def _model_preview(args: argparse.Namespace, doc: ModelDocument) -> tuple[Preview, str]:
    """The preview of a model file to write, and where it came from: the image it stores
    unless ``--render``, else (and without ``--stored``) one rendered from its geometry."""
    if args.nested is not None:
        raise InvalidArgumentError(
            "--nested applies to SOLIDWORKS assemblies", detail={"parameter": "nested"}
        )
    if not args.render:
        pv = doc.preview(prefer=args.prefer)
        if pv is not None and pv.mime == "image/bmp" and args.output.lower().endswith(".png"):
            from .formats._source import bmp_to_png

            try:  # a bitmap SolidSeas converts itself, with no Pillow
                png, w, h = bmp_to_png(pv.data, doc.limits)
                pv = Preview(png, "image/png", w, h, pv.stream)
            except SldError:
                pass  # one it does not: Pillow may
        if pv is not None:
            return pv, "stored"
        if args.stored:
            raise NoPreviewError("the file stores no preview image")
    from .render import render_preview

    r = render_preview(doc, limits=doc.limits)
    return Preview(r.data, r.mime, r.width, r.height, "rendered"), "rendered"


def cmd_preview(args: argparse.Namespace, doc: Document) -> int:
    if args.render and args.stored:
        raise InvalidArgumentError("--render and --stored exclude each other", detail={"parameter": "render"})
    if isinstance(doc, ModelDocument):
        pv, source = _model_preview(args, doc)
    else:
        if args.render:
            raise UnsupportedOperationError(
                "a SOLIDWORKS document's preview is the one it stores; --render is for other 3D files",
                detail={"rule": "solidworks_render", "value": "solidworks"},
            )
        pv, source = doc.preview(prefer=args.prefer, nested=args.nested), "stored"
    if pv is None:
        raise NoPreviewError("the document stores no preview image")
    stem = os.path.splitext(os.path.basename(args.file))[0]
    if args.nested:
        stem += "_" + re.sub(r"[^\w.-]", "_", args.nested.rsplit("/", 1)[-1])
    out, data = _preview_output(pv, args.output, stem)
    out = check_output_file(out, [args.file], allow_source_dir=args.allow_source_dir, force=args.force)
    _write(out, data)
    mime = "image/png" if out.lower().endswith(".png") else "image/bmp"
    if not args.json:
        where = "rendered from the model" if source == "rendered" else f"from {pv.stream}"
        _say(f"wrote {pv.width} x {pv.height} preview {where} to {out}")
    written = model.build_file_written(
        out,
        len(data),
        stream=pv.stream if source == "stored" else None,
        mime=mime,
        width=pv.width,
        height=pv.height,
        source=source,
    )
    return _emit(args, "file_written", written)


def _write_parasolid(
    res: ParasolidResult,
    base: str,
    out_dir: str,
    sources: list[str],
    *,
    text: bool,
    raw: bool,
    allow_source_dir: bool,
    force: bool,
    source_dirs: Iterable[str] = (),
) -> list[dict[str, Any]]:
    written = []
    jobs: list[tuple[str, Any, str, str]] = []
    used: set[str] = set()

    def unique(stem: str) -> str:
        # Configuration names that sanitise or truncate to the same text would
        # otherwise write to one file, and the second body would replace the first.
        cand, n = stem, 1
        while os.path.normcase(cand) in used:
            n += 1
            cand = f"{stem}_{n}"
        used.add(os.path.normcase(cand))
        return cand

    for body in res.bodies:
        stem = unique(body.file_stem(base))
        jobs.append((os.path.join(out_dir, stem + ".x_b"), body, "x_b", stem))
        if text:
            jobs.append((os.path.join(out_dir, stem + ".x_t"), body, "x_t", stem))
    if raw:
        for t in res.raw:
            ext = "p_b" if t.kind == "partition" else "d_b"
            stem = unique(f"{base}_Config-{t.configuration_id}_{t.kind}")
            jobs.append((os.path.join(out_dir, f"{stem}.{ext}"), t, ext, stem))
    source_dirs = list(source_dirs)
    jobs = [
        (
            check_output_file(
                path, sources, allow_source_dir=allow_source_dir, force=force, source_dirs=source_dirs
            ),
            obj,
            kind,
            stem,
        )
        for path, obj, kind, stem in jobs
    ]
    for path, obj, kind, stem in jobs:
        if kind == "x_b":
            data = obj.x_b(stem)
        elif kind == "x_t":
            data = obj.x_t(stem)
        else:
            data = obj.p_b(stem)
        _write(path, data)
        entry: dict[str, Any] = {"output": path, "kind": kind, "bytes": len(data)}
        if kind in ("x_b", "x_t"):
            entry.update(
                body=obj.name,
                configuration=obj.configuration_name,
                configuration_id=obj.configuration_id,
                source=obj.source,
                body_type=obj.body_type,
                schema=obj.schema,
                valid=obj.valid,
            )
        else:
            entry.update(configuration_id=obj.configuration_id, transmit=obj.kind)
        written.append(entry)
    return written


_ASSEMBLY_PARASOLID_FLAGS = (
    ("--configuration", "configuration"),
    ("--allow-partial", "allow_partial"),
    ("--other-configurations", "other_configurations"),
    ("--include-hidden", "include_hidden"),
)


def _write_assembly_parasolid(
    doc: Document,
    prefix: str,
    name: str,
    out_dir: str,
    sources: list[str],
    *,
    configuration: str | None,
    allow_partial: bool,
    other_configurations: bool,
    include_hidden: bool,
    text: bool,
    max_bytes: int,
    allow_source_dir: bool,
    force: bool,
) -> tuple[Any, list[dict[str, Any]]]:
    """An assembly's one transmit (``solidseas.parasolid``), written to ``out_dir`` as
    ``<prefix>_<configuration>.x_b`` and, with ``text``, .x_t, under the write guards:
    every path is checked before anything is written. ``name`` names the top assembly
    inside the file. ``parasolid`` and ``batch`` both write an assembly through this.
    Returns the :class:`~solidseas.parasolid.AssemblyParasolid` and the files written."""
    from .formats.solidworks.parasolid import _safe
    from .parasolid import assembly_parasolid

    m = assembly_parasolid(
        doc,
        configuration,
        name=name,
        allow_partial=allow_partial,
        other_configurations=other_configurations,
        include_hidden=include_hidden,
        max_bytes=max_bytes,
    )
    base = f"{prefix}_{_safe(m.configuration)}" if m.configuration else prefix
    jobs = [(os.path.join(out_dir, base + ".x_b"), "x_b")]
    if text:
        jobs.append((os.path.join(out_dir, base + ".x_t"), "x_t"))
    jobs = [
        (check_output_file(path, sources, allow_source_dir=allow_source_dir, force=force), kind)
        for path, kind in jobs
    ]
    written = []
    for path, kind in jobs:
        data = m.data(kind, base)
        _write(path, data)
        written.append(
            {
                "output": path,
                "kind": kind,
                "bytes": len(data),
                "configuration": m.configuration,
                "source": "assembly",
                "schema": m.schema,
                "valid": m.valid,
            }
        )
    return m, written


def _parasolid_assembly(args: argparse.Namespace, doc: Document) -> int:
    """``parasolid`` for an assembly: one transmit of every part instance of one
    configuration (``solidseas.parasolid``), as .x_b and, with ``--text``, .x_t."""
    for flag, given in (("--raw", args.raw), ("--local-bodies", args.local_bodies != "fallback")):
        if given:
            raise InvalidArgumentError(f"{flag} is for a part", detail={"parameter": flag})
    stem = os.path.splitext(os.path.basename(args.file))[0]
    m, written = _write_assembly_parasolid(
        doc,
        stem,
        stem,
        args.output,
        [args.file],
        configuration=args.configuration,
        allow_partial=args.allow_partial,
        other_configurations=args.other_configurations,
        include_hidden=args.include_hidden,
        text=args.text,
        max_bytes=int(args.max_mb * (1 << 20)),
        allow_source_dir=args.allow_source_dir,
        force=args.force,
    )
    if not args.json:
        for w in written:
            _say(f"wrote {w['output']} ({w['bytes']} bytes)")
        c = m.counts
        _say(
            f"{c['instances']} instance(s) of {c['parts']} part(s) placed, "
            f"{c['bodies_placed']} bodies in all, configuration {m.configuration}"
        )
        for s in m.skipped:
            _say(f"left out: {s.id}: {s.message}")
        for w in m.warnings:
            _say(f"warning: {w}")
    code = EXIT_PARTIAL if m.skipped else EXIT_OK
    data = model.build_parasolid_result(m.counts["bodies_placed"], written, [], assembly=m)
    return _emit(args, "parasolid_result", data, code)


def cmd_parasolid(args: argparse.Namespace, doc: Document) -> int:
    args.output = check_output_dir(
        args.output, [os.path.dirname(os.path.abspath(args.file))], allow_source_dir=args.allow_source_dir
    )
    if doc.doc_type == "assembly":
        return _parasolid_assembly(args, doc)
    for flag, attr in _ASSEMBLY_PARASOLID_FLAGS:
        if getattr(args, attr):
            raise InvalidArgumentError(f"{flag} is for an assembly", detail={"parameter": flag})
    res = doc.parasolid(
        local_bodies=args.local_bodies, include_raw=args.raw, max_bytes=int(args.max_mb * (1 << 20))
    )
    stem = os.path.splitext(os.path.basename(args.file))[0]
    written = _write_parasolid(
        res,
        stem,
        args.output,
        [args.file],
        text=args.text,
        raw=args.raw,
        allow_source_dir=args.allow_source_dir,
        force=args.force,
    )
    if not args.json:
        for w in written:
            _say(f"wrote {w['output']} ({w['bytes']} bytes)")
        for p in res.problems:
            _say(f"problem: {p}")
        if not res.bodies:
            _say("no Parasolid bodies found")
    return _emit(
        args, "parasolid_result", model.build_parasolid_result(len(res.bodies), written, res.problems)
    )


def _export_output(out: str | None, stem: str, fmt: str) -> str:
    """The export's output path: ``out`` as given (its extension must be the format's),
    the document's name with the format's extension inside ``out`` when it is a
    folder that exists, or in the current folder when ``out`` is None. A name with no
    extension that is not a folder is refused rather than guessed at: ``-o Prints``
    meant for a folder that is not there would otherwise write ``Prints.stl``."""
    ext = EXPORT_EXTENSIONS[fmt]
    accepted = (".step", ".stp") if fmt == "step" else (ext,)
    if out is None:
        return os.path.join(os.getcwd(), stem + ext)
    if os.path.isdir(out):
        return os.path.join(out, stem + ext)
    if out.endswith(("/", "\\")):
        raise _refused(f"the folder {out} does not exist", "output_folder")
    given = os.path.splitext(out)[1].lower()
    if not given:
        raise _refused(
            f"-o names neither a folder that exists nor a file ending in {' or '.join(accepted)}: {out}",
            "output_extension",
        )
    if given not in accepted and given not in PROTECTED_EXTENSIONS:  # a SOLIDWORKS name: its own rule
        raise _refused(
            f"a {fmt.upper()} export must end in {' or '.join(accepted)}, not {given}", "output_extension"
        )
    return out


def _step_options(args: argparse.Namespace) -> None:
    """Refuse the options of the other format: ``--chord`` and ``--merge`` for STEP, the
    STEP options for 3MF and STL (``invalid_argument``, exit 2)."""
    if args.format == "step":
        for flag, given in (("--chord", args.chord is not None), ("--merge", args.merge)):
            if given:
                raise InvalidArgumentError(
                    f"{flag} is for 3MF and STL: a STEP export holds the exact geometry, not triangles",
                    detail={"parameter": flag},
                )
        return
    for flag, given in (
        ("--sheets", args.sheets),
        ("--allow-partial", args.allow_partial),
        ("--exact-only", args.exact_only),
        ("--include-hidden", args.include_hidden),
        ("--check", args.check),
    ):
        if given:
            raise InvalidArgumentError(f"{flag} is for --format step", detail={"parameter": flag})


def _step_check(sm: Any, path: str) -> dict[str, Any]:
    """``export --check``: what Open CASCADE made of the STEP file at ``path`` that ``sm``
    was written as, with ``findings`` (what is wrong, in words) and ``sound``. A part's
    solids, surface bodies and faces must be those written; an assembly's model counts
    each part once, not each instance, so only the rest is checked there."""
    from .convert.occt import BACKEND, step_findings

    with open(path, "rb") as fh:
        check = BACKEND.check_bytes(fh.read())
    c = sm.counts
    part = not c.get("instances")
    findings = step_findings(
        check,
        solids=c.get("solids") if part else None,
        sheets=c.get("sheets") if part else None,
        faces=c.get("faces") if part else None,
    )
    return {"sound": not findings, "findings": findings, **check}


def _check_lines(check: dict[str, Any]) -> list[str]:
    """``export --check``'s lines for a person."""
    by = f"Open CASCADE {check['occt']}" if check.get("occt") else "Open CASCADE"
    if check["sound"]:
        what = (
            f"{check.get('solids') or 0} solid(s), {check.get('sheets') or 0} sheet(s), "
            f"{check.get('faces') or 0:,} faces"
        )
        lines = [f"checked with {by}: it reads the file as written, {what}, closed and valid"]
    else:
        lines = [f"checked with {by}: the file does not read as written"]
        lines += [f"check: {f}" for f in check["findings"]]
    measures = []
    if check.get("volume_mm3") is not None:
        measures.append(f"volume {check['volume_mm3']:,.6g} cubic mm")
    if check.get("area_mm2") is not None:
        measures.append(f"area {check['area_mm2']:,.6g} square mm")
    if measures:
        lines.append(f"{by} measures {', '.join(measures)}")
    return lines


def _export_step(args: argparse.Namespace, doc: Document, stem: str, out: str) -> int:
    from .step import step_model, write_step

    if args.check:  # said before anything is written, as convert says it
        from .convert.occt import BACKEND

        reason = BACKEND.unavailable()
        if reason is not None:
            raise FormatNotSupportedError(reason, detail={"rule": "needs_extension", "value": "step"})
    sm = step_model(
        doc,
        args.configuration,
        name=stem,
        body_types=("solid", "sheet") if args.sheets else ("solid",),
        allow_partial=args.allow_partial,
        exact_only=args.exact_only,
        include_hidden=args.include_hidden,
    )
    result = write_step(sm, out, overwrite=args.force)
    code = EXIT_PARTIAL if sm.partial or sm.counts.get("skipped") else EXIT_OK
    check = _step_check(sm, result.path) if args.check else None
    if check is not None and not check["sound"]:
        code = EXIT_FAILED  # the file is kept: the check says what is wrong in it
    if not args.json:
        c = sm.counts
        if sm.exact:
            how = "exact"
        else:
            dev = sm.max_deviation_m * 1000.0
            how = f"approximated where it had to be, at most {dev:.3g} mm from the geometry"
        _say(
            f"wrote {out} ({result.bytes:,} bytes): {c['products']} product(s), {c['solids']} solid(s), "
            f"{c['sheets']} sheet(s), {c['faces']:,} faces, {how}"
        )
        for w in sm.warnings:
            _say(f"warning: {w}")
        for line in _check_lines(check) if check is not None else ():
            _say(line)
    return _emit(args, "export_result", model.build_export_result(result, check=check), code)


def cmd_export(args: argparse.Namespace, doc: Document) -> int:
    from .export import print_model, write_export

    _step_options(args)
    stem = os.path.splitext(os.path.basename(args.file))[0]
    out = check_output_file(
        _export_output(args.output, stem, args.format),
        [args.file],
        allow_source_dir=args.allow_source_dir,
        force=args.force,
    )
    if args.format == "step":  # a SOLIDWORKS part or a Parasolid file; solidseas.step refuses the rest
        return _export_step(args, doc, stem, out)
    chord = None if args.chord is None else args.chord / 1000.0
    pm = print_model(doc, args.configuration, name=stem, chord_m=chord)
    result = write_export(pm, out, args.format, merge=args.merge, overwrite=args.force)
    code = EXIT_PARTIAL if pm.counts.get("skipped") else EXIT_OK
    if not args.json:
        c = pm.counts
        state = "closed" if pm.closed else "NOT closed: a slicer may have to repair it"
        _say(
            f"wrote {out} ({result.bytes:,} bytes): {c['objects']} object(s), {c['items']} placed, "
            f"{c['triangles']:,} triangles, {state}"
        )
        for w in (*pm.warnings, *(w for o in pm.objects for w in o.warnings)):
            _say(f"warning: {w}")
    return _emit(args, "export_result", model.build_export_result(result), code)


def _convert_output(out: str | None, stem: str, fmt: str) -> str:
    """``convert``'s output path, chosen as :func:`_export_output` chooses an export's."""
    from .convert import EXTENSIONS

    accepted = EXTENSIONS[fmt]
    if out is None:
        return os.path.join(os.getcwd(), stem + accepted[0])
    if os.path.isdir(out):
        return os.path.join(out, stem + accepted[0])
    if out.endswith(("/", "\\")):
        raise _refused(f"the folder {out} does not exist", "output_folder")
    given = os.path.splitext(out)[1].lower()
    if not given:
        raise _refused(
            f"-o names neither a folder that exists nor a file ending in {' or '.join(accepted)}: {out}",
            "output_extension",
        )
    if given not in accepted and given not in PROTECTED_EXTENSIONS:  # a SOLIDWORKS name: its own rule
        raise _refused(f"the file must end in {' or '.join(accepted)}, not {given}", "output_extension")
    return out


def cmd_convert(args: argparse.Namespace, doc: Document) -> int:
    from .convert import MIME_TYPES, convert_document, target_format, target_name

    fmt = target_format(args.format)
    stem = os.path.splitext(os.path.basename(args.file))[0]
    out = check_output_file(
        _convert_output(args.output, stem, fmt),
        [args.file],
        allow_source_dir=args.allow_source_dir,
        force=args.force,
    )
    result = convert_document(doc, out, args.format, overwrite=args.force)
    if not args.json:
        r = result.report
        what = ", ".join(
            f"{r[k]} {label}"
            for k, label in (("solids", "solid(s)"), ("faces", "face(s)"))
            if isinstance(r.get(k), int)
        )
        _say(f"wrote {result.path} ({result.bytes:,} bytes), {target_name(fmt)} through Open CASCADE: {what}")
        left = int(r.get("open_shells") or 0) + int(r.get("free_faces") or 0)
        if left:
            _say(f"warning: {left} group(s) of surfaces did not close into a solid when sewn at 0.01 mm")
        if r.get("valid") is False:
            _say("warning: Open CASCADE's check found faults in the shape")
    written = model.build_file_written(
        result.path, result.bytes, mime=MIME_TYPES.get(fmt), source=result.backend
    )
    return _emit(args, "file_written", written)


# --------------------------------------------------------------------------- native parts
DESIGN_FORMATS = {".solidcraft": "solidcraft", ".json": "ir"}
NATIVE_PART_NOTE = (
    "SolidSeas made this part without SOLIDWORKS and checked it. Parts like it open in "
    "SOLIDWORKS 2024 and rebuild when you change a depth; open an important one there before "
    "you rely on it."
)
NATIVE_HOLE_NOTE = (
    "SolidSeas made this part without SOLIDWORKS and checked it. Parts like it open in "
    "SOLIDWORKS 2024 with the hole in place; open an important one there before you rely on it."
)
NATIVE_FILLET_NOTE = (
    "SolidSeas made this part without SOLIDWORKS and checked it. Parts with a fillet have not "
    "been opened in SOLIDWORKS yet; open this one there before you rely on it."
)


def _sldprt_output(out: str | None, stem: str) -> str:
    """``sldprt``'s output path, chosen as :func:`_export_output` chooses an export's: a
    name ending in ``.sldprt``, or the design's name in a folder that exists."""
    if out is None:
        return os.path.join(os.getcwd(), stem + ".SLDPRT")
    if os.path.isdir(out):
        return os.path.join(out, stem + ".SLDPRT")
    if out.endswith(("/", "\\")):
        raise _refused(f"the folder {out} does not exist", "output_folder")
    given = os.path.splitext(out)[1].lower()
    if not given:
        raise _refused(
            f"-o names neither a folder that exists nor a file ending in .sldprt: {out}", "output_extension"
        )
    if given != ".sldprt":
        raise _refused(f"a part must end in .sldprt, not {given}", "output_extension")
    return out


def check_new_part(out: str, design: str, *, allow_source_dir: bool) -> str:
    """Return the path to write a native part at, or raise :class:`Refused`. The one
    SOLIDWORKS file the command line writes is always a new one: nothing already there is
    replaced, whatever it is, and the folder rules of :func:`check_output_file` apply."""
    final = final_path(out)
    if os.path.lexists(final):
        raise _refused(f"{out} already exists; a part SolidSeas writes never replaces a file", "exists")
    folder = os.path.dirname(final)
    if not allow_source_dir and _is_within(folder, os.path.dirname(os.path.abspath(design))):
        raise _refused(
            f"refusing to write next to the source file ({out}); "
            "choose another folder or pass --allow-source-dir",
            "source_folder",
        )
    if not os.path.isdir(folder):
        raise _refused(f"the folder {folder} does not exist", "output_folder")
    return final


def _read_design(path: str):
    """A design as ``ParametricDocumentIR``: a ``.solidcraft`` file through its adapter, a
    ``.json`` file as a CadQuery recording when its format says it is one
    (``solidseas.nativewrite.cqrecording``), else as a SolidSeas IR file. Returns the
    document and its format."""
    import zipfile

    from .nativewrite import cqrecording, ir, solidcraft

    fmt = DESIGN_FORMATS.get(os.path.splitext(path)[1].lower())
    if fmt is None:
        raise InvalidArgumentError(
            f"a design is a .solidcraft file, or a .json file holding a SolidSeas IR document or a "
            f"CadQuery recording: {path}",
            detail={"parameter": "design"},
        )
    try:
        if fmt == "solidcraft":
            return solidcraft.read_ir(path), fmt
        with open(path, "rb") as fh:
            raw = fh.read(solidcraft.MAX_FILE_BYTES + 1)
        if len(raw) > solidcraft.MAX_FILE_BYTES:
            raise ir.IRError(f"the file is larger than {solidcraft.MAX_FILE_BYTES >> 20} MiB")
        fmt = "cadquery"  # what the message below calls it when the recording is refused
        recording = cqrecording.recording_in(raw)
        if recording is not None:
            return cqrecording.to_ir(recording), fmt
        fmt = "ir"
        return ir.from_json(raw), fmt
    except (ValueError, KeyError, zipfile.BadZipFile, RecursionError) as exc:
        what = {"solidcraft": "SolidCraft design", "cadquery": "CadQuery recording"}.get(
            fmt, "SolidSeas IR document"
        )
        raise InvalidArgumentError(
            f"{path} is not a {what} SolidSeas reads: {exc}", detail={"parameter": "design"}
        ) from None


def _with_properties(doc: Any, given: Iterable[str]) -> Any:
    """``doc`` with each ``--property NAME=VALUE`` set as a text file property, replacing a
    property of the same name (in any case) the design already has."""
    from .nativewrite import ir

    for text in given:
        name, sep, value = text.partition("=")
        name = name.strip()
        if not sep or not name:
            raise InvalidArgumentError(
                f"--property takes NAME=VALUE, such as PartNo=SS-1001: {text}",
                detail={"parameter": "property"},
            )
        doc.properties = [p for p in doc.properties if p.name.casefold() != name.casefold()]
        doc.properties.append(ir.Property(name, value))
    try:
        return ir.validate(doc)
    except ir.IRError as exc:
        raise InvalidArgumentError(f"--property: {exc}", detail={"parameter": "property"}) from None


def _part_identity(generate: Any, stem: str) -> Any:
    """A new file's identity (section 15.6.6 of ``docs/sldprt-spec``), with the file name the
    part is saved under."""
    return generate.Identity.new(file_stem=stem)


def _part_names(names: Any, features: Iterable[Any]) -> list[dict[str, str]]:
    """The design's features the part holds, in timeline order, each with its name in the
    part. ``plan.names`` maps a feature's id or name to that name, as a dict whose values
    are the name (or end with it) or as entries that end with it."""
    lookup: dict[str, str] = {}
    entries = names.items() if isinstance(names, dict) else (names or ())
    for entry in entries:
        if not isinstance(entry, (tuple, list)) or len(entry) < 2:
            continue
        keys, value = list(entry[:-1]), entry[-1]
        if isinstance(value, (tuple, list)) and value:
            keys += list(value[:-1])
            value = value[-1]
        if isinstance(value, str):
            for key in keys:
                lookup.setdefault(str(key), value)
    out = []
    for f in features:
        part_name = lookup.get(f.id) or lookup.get(f.name)
        if part_name is not None:
            out.append({"id": f.id, "name": f.name, "part_name": part_name})
    return out


def _check_part(data: bytes, name: str) -> None:
    """Read the part back as any SOLIDWORKS part is read, before it is written."""
    try:
        with open_document(data, name=name) as part:
            doc_type = part.doc_type
    except Exception as exc:
        raise RuntimeError(
            f"the part made from the design could not be read back, so nothing was written: {exc}"
        ) from exc
    if doc_type != "part":
        raise RuntimeError("the file made from the design does not read as a part, so nothing was written")


def cmd_sldprt(args: argparse.Namespace) -> int:
    """``solidseas sldprt DESIGN`` (provisional): a native ``.sldprt`` made from a design
    by the clean-room generator (``solidseas.nativewrite.generate``), written as a new
    file. A design that needs what the generator cannot write is refused with every
    item listed, unless ``--allow-partial``: then they are left out, listed, and it exits 4."""
    from .nativewrite.container import write_new_file

    stem = os.path.splitext(os.path.basename(args.path))[0]
    out = check_new_part(
        _sldprt_output(args.output, stem), args.path, allow_source_dir=args.allow_source_dir
    )
    doc, fmt = _read_design(args.path)
    doc = _with_properties(doc, args.property or ())
    try:
        from .nativewrite import generate
    except ModuleNotFoundError as exc:
        if exc.name != "solidseas.nativewrite.generate":
            raise
        raise UnsupportedOperationError(
            "this SolidSeas cannot write parts yet", detail={"rule": "native_write"}
        ) from None
    identity = _part_identity(generate, os.path.splitext(os.path.basename(out))[0])
    unsupported: list[str] = []
    try:
        plan = generate.plan(doc, identity=identity)
    except generate.NativeWriteUnsupported as exc:
        unsupported = [str(item) for item in exc.items]
        if not args.allow_partial:
            listed = "".join(f"\n  {item}" for item in unsupported)
            raise UnsupportedOperationError(
                f"the design needs what SolidSeas cannot write in a part yet, so nothing was written:{listed}"
                "\nadd --allow-partial to write the part without them",
                detail={"rule": "native_write", "value": len(unsupported)},
            ) from None
        plan = generate.plan(doc, identity=identity, allow_partial=True)
    data = generate.write_part(doc, identity=identity, allow_partial=bool(unsupported))
    _check_part(data, os.path.basename(out))
    try:
        written = os.fspath(write_new_file(out, data))
    except FileExistsError:
        raise _refused(
            f"{out} already exists; a part SolidSeas writes never replaces a file", "exists"
        ) from None
    features = _part_names(plan.names, doc.features)
    left_out = [str(item) for item in plan.left_out]
    written_props = {item["name"] for item in plan.slots.get("props", ())}  # docs/sldprt-spec 15.6.9
    properties = [
        {"name": p.name, "type": p.type, "value": p.value} for p in doc.properties if p.name in written_props
    ]
    if not args.json:
        count = f"{len(features)} feature(s)" if features else "no features"
        _say(f"wrote {written} ({len(data):,} bytes), a part with {count} from the design {doc.name}")
        for f in features:
            _say(f"  {f['part_name']}, from {f['name']}")
        if properties:
            _say(f"file properties: {', '.join(p['name'] for p in properties)}")
        if left_out:
            _say("left out of the part:")
            for item in left_out:
                _say(f"  {item}")
        items = plan.slots.get("features", ())  # docs/sldprt-spec 15.6.2
        if any(f.get("fillet") for f in items):
            _say(NATIVE_FILLET_NOTE)
        else:
            _say(NATIVE_HOLE_NOTE if any(f.get("cut") for f in items) else NATIVE_PART_NOTE)
    result = model.build_sldprt_written(
        written,
        len(data),
        design_name=doc.name,
        design_format=fmt,
        features=features,
        properties=properties,
        left_out=left_out,
        unsupported=unsupported,
    )
    return _emit(args, "sldprt_written", result, EXIT_PARTIAL if unsupported else EXIT_OK)


def _flags(node: dict[str, Any]) -> str:
    flags = [f for f in ("suppressed", "hidden", "virtual") if node[f]]
    if node["excluded_from_bom"]:
        flags.append("excluded from BOM")
    if node["children_state"] in ("truncated", "cycle", "unknown"):
        flags.append(f"children {node['children_state']}")
    return f" [{', '.join(flags)}]" if flags else ""


def cmd_components(args: argparse.Namespace, doc: Document) -> int:
    data = model.build_components(
        doc,
        configuration=args.configuration,
        max_nodes=args.max_nodes,
        max_depth=args.max_depth,
        flat=args.flat,
    )
    if args.json:
        return _emit(args, "components", data)
    if data["children_state"] == "none":
        _say(f"no components: the document is a {doc.doc_type or 'document of unknown type'}")
        return EXIT_OK
    files = {f["key"]: f for f in data["files"]}
    _say(f"configuration: {data['configuration']} ({data['configuration_source']})")
    if data["children_state"] == "unknown":
        _say("the file stores no component tree; referenced files from Header2:")
        for f in data["files"]:
            _say(f"  {f['file_name'] or f['stored_path']}")
    nodes = data["instances"] if data["instances"] is not None else []
    if data["children"] is not None:
        stack = list(reversed(data["children"]))
        while stack:
            node = stack.pop()
            nodes.append(node)
            stack.extend(reversed(node["children"]))
    for node in nodes:
        f = files.get(node["file"]) or {}
        detail = f", {node['configuration']}" if node["configuration"] else ""
        _say(f"{'  ' * node['depth']}{node['name']}  ({f.get('file_name') or '?'}{detail}){_flags(node)}")
    c = data["counts"]
    _say(f"{c['nodes']} instances of {c['files']} files, {c['depth']} levels" + (
        " (stopped at a limit)" if data["truncated"] else ""
    ))
    for w in data["warnings"]:
        _say(f"warning: {w['code']}: {w['message']}")
    return EXIT_OK


def _root_args(values: list[str] | None, role: str, flag: str) -> list[Root]:
    out = []
    for text in values or ():
        root_id, sep, folder = text.partition("=")
        if not sep or not folder:
            raise InvalidArgumentError(f"{flag} takes ID=DIR, not {text!r}", detail={"parameter": flag})
        out.append(Root(root_id, os.path.abspath(folder), True, role))
    return out


def _resolution(args: argparse.Namespace, doc: Document) -> Resolution | None:
    given = args.root or args.library or args.path_map or args.no_outside_roots
    if not args.resolve:
        if given:
            raise InvalidArgumentError(
                "--root, --library, --path-map and --no-outside-roots need --resolve",
                detail={"parameter": "resolve"},
            )
        return None
    roots = _root_args(args.root, "project", "--root") + _root_args(args.library, "library", "--library")
    return resolve_references(
        doc,
        Roots(roots) if roots else None,
        path_map=args.path_map or (),
        allow_outside_roots=not args.no_outside_roots,
    )


def _where(loc: dict[str, Any] | None) -> str:
    if loc is None:
        return "-"
    return f"{loc['root']}:{loc['path']}" if loc["root"] is not None else loc["path"]


def cmd_references(args: argparse.Namespace, doc: Document) -> int:
    resolution = _resolution(args, doc)
    data = model.build_references(doc, configuration=args.configuration, resolution=resolution)
    code = EXIT_PARTIAL if resolution is not None and resolution.index_partial else EXIT_OK
    if args.json:
        return _emit(args, "references", data, code)
    if data["children_state"] == "none" and data["sheets"] is None:
        _say(f"no references: the document is a {doc.doc_type or 'document of unknown type'}")
        return EXIT_OK
    if data["configuration"] is not None:
        _say(f"configuration: {data['configuration']} ({data['configuration_source']})")
    for f in data["files"]:
        counts = "" if f["instances"] is None else f"  {f['instances_in_bom']} in BOM of {f['instances']}"
        where = "" if f["direct"] is not False else "  (inside a sub-assembly)"
        embedded = f"  [{f['embedded']}]" if f["embedded"] else ""
        _say(f"{f['key']:<12}{f['file_name'] or '?'}{counts}{where}{embedded}")
        r = f["resolution"]
        if r is not None:
            how = f"{r['rule']}, {r['confidence']} confidence, identity {r['identity']}" if r["rule"] else "-"
            found = _where(r["match"]) if r["nested"] is None else r["nested"]
            _say(f"{'':<12}  {r['status']}: {found}  ({how})")
            for w in r["warnings"]:
                _say(f"{'':<12}    {w['code']}")
            if r["status"] == "ambiguous":
                for c in r["candidates"]:
                    _say(f"{'':<12}    candidate {_where(c)} (identity {c['identity']})")
    for sheet in data["sheets"] or []:
        _say(f"sheet {sheet['name']}: " + (", ".join(
            f"{v['name']} ({v['file_name']}, {v['configuration']})" for v in sheet["views"]
        ) or "no views"))
    _say(f"{len(data['files'])} referenced files")
    summary = data["resolution"]
    if summary is not None:
        _say(
            "resolution: "
            + ", ".join(f"{k} {v}" for k, v in summary["counts"].items() if v)
            + "; roots "
            + ", ".join(f"{r['id']} ({r['role']})" for r in summary["roots"])
            + ("; a limit cut a folder index short" if summary["index_partial"] else "")
        )
    for w in data["warnings"]:
        _say(f"warning: {w['code']}: {w['message']}")
    return code


BOM_FORMATS = ("table", "csv", "json")


def _visible(text: str) -> str:
    """``text`` with each character a terminal would act on or not show (a line break, a
    carriage return, a tab, an escape...) written as its Python escape, so that a value
    read from a file keeps to its line and cannot move the cursor."""
    if text.isprintable():
        return text
    return "".join(ch if ch.isprintable() else ch.encode("unicode_escape").decode("ascii") for ch in text)


def _bom_table_text(data: dict[str, Any]) -> str:
    """The BOM as SOLIDWORKS draws it, in columns of plain text; characters a terminal
    would act on are escaped (:func:`_visible`), which the CSV and JSON exports never need."""
    cells = [
        [_visible(c) for c in row]
        for row in bom_mod.table_cells(data["type"], data["property_columns"], data["rows"])
    ]
    widths = [max(len(row[i]) for row in cells) for i in range(len(cells[0]))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)).rstrip() for row in cells]
    return "\n".join(lines) + "\n"


def _write_stdout_utf8(text: str) -> None:
    """Text that may hold any character (a CSV export), as UTF-8 on standard output
    whatever the console's code page."""
    sys.stdout.flush()
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(text)
        return
    buffer.write(text.encode("utf-8"))
    buffer.flush()


def cmd_bom(args: argparse.Namespace, doc: Document) -> int:
    fmt = args.format or ("json" if args.json else "table")
    if args.json and fmt != "json" and args.output is None:
        raise InvalidArgumentError(
            f"--format {fmt} prints to standard output, which --json uses; add -o FILE to write it",
            detail={"parameter": "format"},
        )
    columns = bom_mod.check_columns(args.column or (), label="--column")
    if args.part_number_property is not None:
        bom_mod.check_property_name(
            args.part_number_property, "part_number_property", label="--part-number-property"
        )
    roots = _root_args(args.root, "project", "--root") + _root_args(args.library, "library", "--library")
    read_dirs = [r.path for r in roots]  # the folders the component files are read from
    out = None
    if args.output is not None:  # checked before anything is read
        out = check_output_file(
            args.output,
            [args.file],
            allow_source_dir=args.allow_source_dir,
            force=args.force,
            source_dirs=read_dirs,
        )
    data = model.build_bom(
        doc,
        configuration=args.configuration,
        bom_type=args.type,
        columns=columns,
        part_number_property=args.part_number_property,
        roots=Roots(roots) if roots else None,
        path_map=args.path_map or (),
        allow_outside_roots=not args.no_outside_roots,
    )
    if out is not None:  # nor beside a component file that was found outside the roots
        outside = [
            os.path.dirname(r["location"]["path"])
            for r in data["rows"]
            if r["location"] is not None and r["location"]["root"] is None
        ]
        if outside:
            out = check_output_file(
                args.output,
                [args.file],
                allow_source_dir=args.allow_source_dir,
                force=args.force,
                source_dirs=[*read_dirs, *outside],
            )
    code = EXIT_OK if data["complete"] else EXIT_PARTIAL
    envelope = model.envelope("bom", data, source=args.source)
    if fmt == "csv":
        content = bom_mod.csv_text(data)
    elif fmt == "json":
        content = model.dumps(envelope, pretty=True) + "\n"
    else:
        content = _bom_table_text(data)
    if out is not None:
        _write(out, bom_mod.csv_bytes(data) if fmt == "csv" else content.encode("utf-8"))
    if args.json:
        _print_json(envelope)
        return code
    if out is not None:
        _say(f"wrote the {bom_mod.TYPE_NAMES[data['type']]} BOM ({len(data['rows'])} rows) as {fmt} to {out}")
    elif fmt == "csv":
        _write_stdout_utf8(content)
        return code
    elif fmt == "json":
        sys.stdout.write(content)
        return code
    if data["children_state"] == "none":
        _say(f"no BOM: the document is a {doc.doc_type or 'document of unknown type'}")
        return code
    _say(_visible(f"configuration: {data['configuration']} ({data['configuration_source']}), "
                  f"{bom_mod.TYPE_NAMES[data['type']]}"))
    if out is None:
        sys.stdout.write(content)
    c = data["counts"]
    state = "complete" if data["complete"] else "incomplete: see the notes"
    _say(f"{c['rows']} rows, {c['instances']} instances, {c['files']} files, {c['read']} read; {state}")
    for r in data["rows"]:
        for n in r["notes"]:
            _say(_visible(f"note: {r['item']} {r['part_number']}: {n['code']}: {n['message']}"))
    for w in data["warnings"]:
        _say(_visible(f"warning: {w['code']}: {w['message']}"))
    return code


def _in(nested: list[str]) -> str:
    return f" (in {' > '.join(nested)})" if nested else ""


def cmd_paths(args: argparse.Namespace, doc: Document) -> int:
    data = model.build_path_report(doc)
    code = EXIT_OK if data["complete"] else EXIT_PARTIAL
    if args.json:
        return _emit(args, "path_report", data, code)
    counts = data["counts"]
    docs = counts["documents"]
    if data["complete"]:
        _say(f"complete: {docs} document{'s' if docs != 1 else ''} read, nested documents included")
    else:
        _say("incomplete: the report is a lower bound")
        for gap in data["incomplete"]:
            _say(f"  {gap['reason']}: {gap['stream'] or '-'}{_in(gap['nested'])}")
    by_cat = ", ".join(f"{k} {v}" for k, v in counts["by_category"].items() if v)
    _say(f"{counts['paths']} paths" + (f": {by_cat}" if by_cat else ""))
    if data["accounts"]:
        _say("accounts:")
        for a in data["accounts"]:
            note = "; only in history, probably from a template" if a["inherited_likely"] else ""
            _say(f"  {a['name']:<24}{a['severity']:<8}{', '.join(a['sources'])}; {a['paths']} paths{note}")
    if data["hosts"]:
        _say("hosts:")
        for h in data["hosts"]:
            shares = ", ".join(h["shares"]) or "-"
            _say(f"  {h['host']:<24}{h['severity']:<8}shares {shares}; {h['paths']} paths")
    if data["identity_fields"]:
        _say("names stored in the file:")
        for f in data["identity_fields"]:
            _say(f"  {f['field']:<24}{f['value']}{_in(f['nested'])}")
    if data["paths"]:
        _say("paths:")
        for p in data["paths"]:
            where = ", ".join(sorted({loc["stream"] or "-" for loc in p["locations"]}))
            nested = sorted({" > ".join(loc["nested"]) for loc in p["locations"] if loc["nested"]})
            more = f"; nested: {'; '.join(nested)}" if nested else ""
            _say(f"  {p['severity']:<8}{p['category']:<12}{p['path']}")
            _say(f"  {'':<20}{', '.join(p['roles'])}: {where}{more}")
    _say(data["rewrite"]["note"])
    return code


# --------------------------------------------------------------------------- folder commands
_PREVIEW_INCLUDE = {"none": (), "meta": ("preview",), "inline": ("preview_data",)}


def _listing_include(args: argparse.Namespace) -> tuple[str, ...]:
    parts: list[str] = []
    for item in (args.include or "").split(","):
        item = item.strip()
        if not item:
            continue
        if item not in ("properties", "configurations"):
            raise InvalidArgumentError(
                f"--include accepts properties and configurations, not {item!r}",
                detail={"parameter": "include"},
            )
        parts.append(item)
    return (*parts, *_PREVIEW_INCLUDE[args.preview])


def _worker_options(args: argparse.Namespace, file_timeout: float) -> None:
    """Fill in ``--file-timeout`` and ``--memory-mb``, which only worker processes have."""
    if args.in_process:
        given = [f for f, v in (("--file-timeout", args.file_timeout), ("--memory-mb", args.memory_mb)) if v]
        if getattr(args, "jobs", 1) > 1:
            given.append("--jobs")
        if given:
            raise InvalidArgumentError(
                f"{' and '.join(given)} {'needs' if len(given) == 1 else 'need'} worker processes; "
                "leave out --in-process",
                detail={"parameter": "in_process"},
            )
        return
    if getattr(args, "jobs", 1) > MAX_JOBS:
        raise InvalidArgumentError(f"--jobs is at most {MAX_JOBS}", detail={"parameter": "jobs"})
    args.file_timeout = args.file_timeout or file_timeout
    args.memory_mb = args.memory_mb or WORKER_MEMORY_MB


@contextlib.contextmanager
def _worker_pool(args: argparse.Namespace, folder: str, workers: int) -> Iterator[Any]:
    """The worker processes that read the documents below ``folder``, or None with
    ``--in-process``. Each document gets ``--file-timeout`` seconds and each worker
    ``--memory-mb``; a worker may open documents below ``folder`` alone."""
    if args.in_process:
        yield None
        return
    from .workers import WorkerPool

    with WorkerPool(
        workers,
        timeout_s=args.file_timeout,
        memory_mb=args.memory_mb,
        roots=[os.path.abspath(folder)],
        jobs=WORKER_JOBS,
    ) as pool:
        yield pool


def cmd_list(args: argparse.Namespace) -> int:
    _worker_options(args, LIST_FILE_TIMEOUT_S)
    scan = Scan(
        args.folder,
        formats=args.formats,
        recursive=args.recursive,
        include=_listing_include(args),
        max_depth=args.max_depth,
        max_entries=args.limit,
        max_examined=args.max_examined,
        max_seconds=args.timeout,
        file_timeout=args.file_timeout,
    )
    # Workers start only once the folder is known to be there.
    with _worker_pool(args, args.folder, LIST_WORKERS) as pool:
        scan.pool = pool
        return _print_listing(args, scan)


def _print_listing(args: argparse.Namespace, scan: Scan) -> int:
    if args.json:
        data = scan.listing()
        return _emit(args, "listing", data, EXIT_PARTIAL if data["counts"]["error"] else EXIT_OK)
    for e in scan:
        detail = ""
        if e["status"] == "ok" and e["type"] == "file" and e.get("model"):
            m = e["model"]
            pv = e["preview"]
            shown = ""
            if pv is not None and pv["available"]:
                shown = f", preview {pv['width']} x {pv['height']}"
            variant = f" {m['variant']}" if m["variant"] else ""
            detail = f"  {m['format_name']}{variant} {e['doc_type'] or 'model'}{shown}"
        elif e["status"] == "unsupported":
            spec = registry.FORMATS.get(e["model"]["format"])
            if spec is not None and spec.backend is not None:
                from .convert import unavailable

                detail = f"  {e['model']['format_name']}: {unavailable(spec.id) or 'not read'}"
            else:
                detail = f"  {e['model']['format_name']}: SolidSeas cannot read this format yet"
        elif e["status"] == "ok" and e["type"] == "file":
            sv = e["saved_version"] or {}
            pv = e["preview"]
            shown = (
                ""
                if pv is None
                else (f", preview {pv['width']} x {pv['height']}" if pv["available"] else ", no preview")
            )
            detail = f"  {e['doc_type'] or 'unknown'}, {sv.get('release') or 'unknown release'}{shown}"
        elif e["error"]:
            detail = f"  {e['error']['code']}"
        elif e["reason"] or e["detected"]:
            detail = f"  {e['reason'] or e['detected']}"
        _say(f"{e['status']:<15}{e['path']}{'/' if e['type'] == 'folder' else ''}{detail}")
    c = scan.counts
    _say(
        f"{c['entries']} entries: "
        + ", ".join(
            f"{k} {c[k]}"
            for k in ("ok", "error", "skipped", "link", "placeholder", "not_solidworks", "unsupported")
            if c.get(k)
        )
        + (f"; stopped early ({scan.truncated_reason})" if scan.truncated_reason else "")
    )
    return EXIT_PARTIAL if c["error"] else EXIT_OK


REPORT_FIELDS = [
    "file",
    "status",
    "error",
    "format",
    "doc_type",
    "format_version",
    "release",
    "last_build",
    "configurations",
    "active_configuration",
    "custom_properties",
    "streams",
    "preview",
    "preview_size",
    "parasolid_bodies",
    "parasolid_files",
    "parasolid_problems",
    "warnings",
    # Added last, so a reader that goes by column position still finds the others.
    "parasolid_left_out",
]
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_ITEM_ERRORS = ("error", "locked", "refused")


def _csv_cell(value: Any) -> Any:
    """Text a spreadsheet would run as a formula gets a leading apostrophe."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


def batch_row(
    path: str, folder: str, out_dir: str, opts: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read one document for ``batch``, write its preview and Parasolid files below
    ``out_dir`` (``opts`` holds the run's switches) and return its report row and its
    ``report.jsonl`` detail. Every failure becomes the row's error. A worker process
    runs this through the ``batch_document`` job (:mod:`solidseas.jobs`), or this
    process does with ``--in-process``."""
    rel = os.path.relpath(path, folder)
    row: dict[str, Any] = dict.fromkeys(REPORT_FIELDS, "")
    row.update(file=rel, status="ok")
    detail: dict[str, Any] = {"file": rel, "summary": None, "parasolid": None}
    name = os.path.basename(path)
    target_dir = os.path.join(out_dir, os.path.dirname(rel))
    try:
        with open_document(path, within=folder) as doc:  # a link swapped in after the walk is refused
            summary = model.build_document_summary(doc)
            sv = summary["saved_version"]
            row.update(
                format=summary["format"],
                doc_type=summary["doc_type"] or "",
                format_version=sv["format_version"] if sv["format_version"] is not None else "",
                release=sv["release"] or "",
                last_build=sv["last_build"] if sv["last_build"] is not None else "",
                configurations=len(summary["configurations"]),
                active_configuration=summary["active_configuration"] or "",
                custom_properties=summary["counts"]["custom_properties"],
                streams=summary["counts"]["streams"],
                warnings=len(summary["warnings"]),
            )
            detail["summary"] = summary
            if opts["preview"]:
                pv = doc.preview()
                if pv is not None:
                    out = check_output_file(
                        os.path.join(target_dir, name + pv.extension),
                        [path],
                        allow_source_dir=opts["allow_source_dir"],
                        force=opts["force"],
                    )
                    _write(out, pv.data)
                    row.update(preview=os.path.relpath(out, out_dir), preview_size=f"{pv.width}x{pv.height}")
            if opts["parasolid"] and summary["doc_type"] == "part":
                res = doc.parasolid(max_bytes=opts["max_bytes"])
                written = _write_parasolid(
                    res,
                    name,
                    target_dir,
                    [path],
                    text=opts["text"],
                    raw=False,
                    allow_source_dir=opts["allow_source_dir"],
                    force=opts["force"],
                )
                row.update(
                    parasolid_bodies=len(res.bodies),
                    parasolid_files=len(written),
                    parasolid_problems=len(res.problems),
                )
                result = model.build_parasolid_result(len(res.bodies), written, res.problems)
                for w in result["written"]:
                    w["output"] = os.path.relpath(w["output"], out_dir)
                detail["parasolid"] = result
            elif opts["parasolid"] and summary["doc_type"] == "assembly":
                # As `solidseas parasolid` writes it; a refusal is this document's error.
                m, written = _write_assembly_parasolid(
                    doc,
                    name,
                    os.path.splitext(name)[0],
                    target_dir,
                    [path],
                    configuration=opts.get("configuration"),
                    allow_partial=bool(opts.get("allow_partial")),
                    other_configurations=bool(opts.get("other_configurations")),
                    include_hidden=bool(opts.get("include_hidden")),
                    text=opts["text"],
                    max_bytes=opts["max_bytes"],
                    allow_source_dir=opts["allow_source_dir"],
                    force=opts["force"],
                )
                row.update(
                    parasolid_bodies=m.counts["bodies_placed"],
                    parasolid_files=len(written),
                    parasolid_problems=0,
                    parasolid_left_out=len(m.skipped),
                )
                result = model.build_parasolid_result(m.counts["bodies_placed"], written, [], assembly=m)
                for w in result["written"]:
                    w["output"] = os.path.relpath(w["output"], out_dir)
                detail["parasolid"] = result
    except LockedFileError as exc:
        row.update(status="locked", error=str(exc))
    except Refused as exc:
        row.update(status="refused", error=str(exc))
    except SldError as exc:
        row.update(status="error", error=f"{type(exc).__name__}: {exc}")
    except MemoryError:  # over a worker's --memory-mb (the code limit_exceeded), or the machine's
        row.update(status="error", error="SldLimitError: reading the document ran out of memory")
    except Exception as exc:  # one malformed file must never end the whole batch
        row.update(status="error", error=f"{type(exc).__name__}: {exc}")
    return row, detail


def _worker_batch_row(
    pool: Any, path: str, folder: str, out_dir: str, opts: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """:func:`batch_row` in a worker process. A worker that missed its deadline, crashed
    or ran out of memory gives the document an error row, and the run goes on. The row
    is rebuilt here from the report's fields, so a worker cannot add a column or name
    another file. ``path`` and ``folder`` go to the worker as given: it shares this
    process's working folder, and a row's error then names the document as the
    in-process run does."""
    rel = os.path.relpath(path, folder)
    params = {"path": path, "folder": folder, "out_dir": out_dir, "opts": opts}
    try:
        data = pool.call("batch_document", params).data
        row, detail = data["row"], data["detail"]
        if not isinstance(row, dict) or not isinstance(detail, dict):
            raise TypeError
        out = {k: row.get(k, "") for k in REPORT_FIELDS}
        if not all(isinstance(v, (str, int)) and not isinstance(v, bool) for v in out.values()):
            raise TypeError
        summary, parasolid = detail.get("summary"), detail.get("parasolid")
        if not all(v is None or isinstance(v, dict) for v in (summary, parasolid)):
            raise TypeError
    except (KeyError, TypeError):
        exc = WorkerCrashedError("the worker's answer was not what the batch job returns")
        return _walk_row(path, folder, "error", f"{type(exc).__name__}: {exc}")
    except Exception as exc:  # a timeout, a crash, the memory cap: this document's error
        info = model.error_info(exc)
        return _walk_row(path, folder, "error", f"{info['exception']}: {info['reader_message']}")
    out["file"] = rel
    return out, {"file": rel, "summary": summary, "parasolid": parasolid}


# Rows for what the walk itself decided: the row status per walk kind, and the
# text per walk reason (solidseas.walk.WalkEntry).
_WALK_ROWS = {"skipped": "skipped", "placeholder": "placeholder", "link": "link"}
_WALK_TEXT = {
    "lock_file": "SOLIDWORKS lock file",
    "not_regular_file": "not a regular file (a pipe, socket or device), not opened",
    "mount_point": "mount point, not followed",
}


def _walk_row(path: str, folder: str, status: str, error: str) -> tuple[dict[str, Any], dict[str, Any]]:
    rel = os.path.relpath(path, folder)
    row: dict[str, Any] = dict.fromkeys(REPORT_FIELDS, "")
    row.update(file=rel, status=status, error=error)
    return row, {"file": rel, "summary": None, "parasolid": None}


def _walk_text(kind: str, reason: str | None) -> str:
    if reason in _WALK_TEXT:
        return _WALK_TEXT[reason]
    if kind == "placeholder":
        return f"cloud placeholder, not opened ({reason})"
    return f"link, not followed ({reason})"


def cmd_batch(args: argparse.Namespace) -> int:
    _worker_options(args, BATCH_FILE_TIMEOUT_S)
    folder = args.folder
    # raises for a missing folder or a file
    walk = Walk(folder, recursive=not args.no_recurse, max_examined=args.max_examined)
    args.output = check_output_dir(args.output, [folder], allow_source_dir=args.allow_source_dir)
    report_csv = os.path.join(args.output, "report.csv")
    report_jsonl = os.path.join(args.output, "report.jsonl")
    for p in (report_csv, report_jsonl):
        if os.path.exists(p) and not args.force:
            raise _refused(f"{p} already exists; pass --force to overwrite it", "exists")
    if args.no_parasolid:
        for flag, attr in _ASSEMBLY_PARASOLID_FLAGS:
            if getattr(args, attr):
                raise InvalidArgumentError(
                    f"{flag} is for the Parasolid files, which --no-parasolid leaves out",
                    detail={"parameter": flag},
                )
    opts = {
        "preview": not args.no_preview,
        "parasolid": not args.no_parasolid,
        "text": args.text,
        "max_bytes": int(args.max_mb * (1 << 20)),
        "allow_source_dir": args.allow_source_dir,
        "force": args.force,
        "configuration": args.configuration,
        "allow_partial": args.allow_partial,
        "other_configurations": args.other_configurations,
        "include_hidden": args.include_hidden,
    }
    # One walk, in order: documents to read, and rows for what the walk itself decided.
    plan: list[tuple[str, Any]] = []
    folder_errors = 0
    for we in walk:
        if we.kind == "error" and we.is_dir:
            folder_errors += 1
            continue
        if we.is_dir or not we.name.lower().endswith(SOLIDWORKS_EXTENSIONS):
            continue
        if we.kind == "file":
            plan.append(("file", we.path))
        elif we.kind in _WALK_ROWS:
            text = _walk_text(we.kind, we.reason)
            plan.append(("row", _walk_row(we.path, folder, _WALK_ROWS[we.kind], text)))
        elif we.kind == "error":
            plan.append(
                ("row", _walk_row(we.path, folder, "error", f"{type(we.error).__name__}: {we.error}"))
            )
    files = [p for k, p in plan if k == "file"]
    os.makedirs(args.output, exist_ok=True)
    results: list[dict[str, Any]] = []
    # Rows are written as each file finishes, so an interrupted run still leaves
    # a report of everything done so far.
    with (
        _worker_pool(args, folder, args.jobs) if files else contextlib.nullcontext() as pool,
        open(report_csv, "w", newline="", encoding="utf-8") as csv_fh,
        open(report_jsonl, "w", encoding="utf-8", newline="\n") as jsonl_fh,
    ):
        w = csv.DictWriter(csv_fh, fieldnames=REPORT_FIELDS)
        w.writeheader()
        csv_fh.flush()

        def record(row: dict[str, Any], detail: dict[str, Any]) -> None:
            w.writerow({k: _csv_cell(v) for k, v in row.items()})
            line = {"file": detail["file"], "status": row["status"], "error": row["error"] or None}
            jsonl_fh.write(
                model.dumps({**line, "summary": detail["summary"], "parasolid": detail["parasolid"]})
            )
            jsonl_fh.write("\n")
            csv_fh.flush()
            jsonl_fh.flush()
            results.append(row)

        if pool is None:  # --in-process, or nothing to read
            for kind, item in plan:
                record(*(batch_row(item, folder, args.output, opts) if kind == "file" else item))
        else:
            from concurrent.futures import ThreadPoolExecutor

            # One thread per worker hands documents to the pool; rows are recorded in
            # walk order. On an interruption the pool is closed before anything waits
            # for these threads, which ends their calls at once.
            threads = ThreadPoolExecutor(max_workers=args.jobs, thread_name_prefix="solidseas-batch")
            try:
                done = threads.map(lambda p: _worker_batch_row(pool, p, folder, args.output, opts), files)
                for kind, item in plan:
                    record(*(next(done) if kind == "file" else item))
            finally:
                threads.shutdown(wait=False, cancel_futures=True)
    counts: dict[str, int] = {}
    for row in results:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    data = model.build_batch_summary(
        files=len(results),
        status_counts=counts,
        report_csv=report_csv,
        report_jsonl=report_jsonl,
        previews=sum(1 for r in results if r["preview"]),
        parasolid_files=sum(int(r["parasolid_files"] or 0) for r in results),
        parasolid_left_out=sum(int(r["parasolid_left_out"] or 0) for r in results),
        walk=walk.stats.to_dict(),
    )
    # Partial: some document failed, a folder could not be read, a walk limit cut the run
    # short, or an assembly's Parasolid left components out (--allow-partial).
    partial = (
        folder_errors
        or walk.stats.truncated
        or any(counts.get(s) for s in _ITEM_ERRORS)
        or data["parasolid_left_out"]
    )
    if not args.json:
        _say(f"{len(results)} documents: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
        _say(f"previews written: {data['previews']}, Parasolid files written: {data['parasolid_files']}")
        if data["parasolid_left_out"]:
            assemblies = sum(1 for r in results if r["parasolid_left_out"])
            _say(
                f"components left out of assembly Parasolid files: {data['parasolid_left_out']} "
                f"in {assemblies} assembl{'y' if assemblies == 1 else 'ies'} (see the report)"
            )
        if folder_errors:
            _say(f"folders that could not be read: {folder_errors}")
        if walk.stats.truncated:
            _say(f"stopped early: {walk.stats.truncated}")
        _say(f"report: {report_csv}")
    return _emit(args, "batch_summary", data, EXIT_PARTIAL if partial else EXIT_OK)


# --------------------------------------------------------------------------- the service
def _serve_settings(args: argparse.Namespace) -> dict[str, Any]:
    """The service's settings: each option given on the command line, else the
    configuration file's value (``--config``), else the default. ``roots`` holds the
    project roots, then the libraries."""
    from .serve import load_serve_config

    file = load_serve_config(args.config) if args.config else {}
    given = {
        "port": args.port,
        "bind": args.bind,
        "token_file": args.token_file,
        "identity_key_file": args.identity_key_file,
        "workers": args.workers,
        "allow_remote": args.allow_remote,
        "allowed_hosts": args.allowed_host,
        "identity_addresses": args.identity_address,
        "allow_origins": args.allow_origin,
        "catalog": args.catalog,
        "catalog_rescan": args.catalog_rescan,
        "formats": args.formats,
        "viewer": args.viewer,
    }
    defaults = {
        "port": 8765,
        "bind": "127.0.0.1",
        "allow_remote": False,
        "allowed_hosts": [],
        "identity_addresses": [],
        "allow_origins": [],
        "catalog": False,
        "catalog_rescan": 300.0,
        "formats": registry.SOLIDWORKS,
        "viewer": False,
    }
    settings = {k: v if v is not None else file.get(k, defaults.get(k)) for k, v in given.items()}
    projects = _root_args(args.root, "project", "--root") if args.root else file.get("roots", [])
    libraries = file.get("libraries", [])
    if args.library:
        libraries = _root_args(args.library, "library", "--library")
    settings["roots"] = [*projects, *libraries]
    return settings


def _service_roots(roots: list[Root], command: str) -> list[Root]:
    """The roots of ``serve`` or ``mcp``: at least one, each a folder that exists."""
    if not roots:
        raise InvalidArgumentError(
            f"{command} needs at least one --root ID=DIR", detail={"parameter": "root"}
        )
    for r in roots:
        if not os.path.isdir(r.path):
            raise FileNotFoundError(2, f"root {r.id}: no such folder", r.path)
    return roots


def cmd_mcp(args: argparse.Namespace) -> int:
    """Serve an MCP client on standard input and output (``solidseas.serve.mcp``) until it
    closes standard input: the service's reads over the same roots, with no port.
    Standard output carries the protocol alone, so a failure before it serves is one
    line on standard error, ``--json`` or not."""
    from .serve.mcp import DEFAULT_WORKERS, serve_stdio

    args.json = False
    projects = _root_args(args.root, "project", "--root")
    roots = _service_roots(projects + _root_args(args.library, "library", "--library"), "mcp")
    return serve_stdio(Roots(roots), workers=args.workers or DEFAULT_WORKERS, catalog=bool(args.catalog))


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the REST service. Refusals (a remote bind without its settings, a token file
    others can read) exit 3 before anything listens; once it serves, it runs until
    SIGINT, SIGTERM or Ctrl+Break and ends the process itself."""
    from .serve import (
        ServeConfig,
        Server,
        check_bind,
        configure_logging,
        default_identity_key_file,
        default_workers,
        ensure_identity_key,
        ensure_token_file,
        parse_identity_address,
        parse_origin,
        run_until_signalled,
    )

    s = _serve_settings(args)
    check_bind(s["bind"], allow_remote=s["allow_remote"], allowed_hosts=tuple(s["allowed_hosts"]))
    for text in s["identity_addresses"]:
        parse_identity_address(text)  # refused before the token file is touched
    for text in s["allow_origins"]:
        parse_origin(text)
    roots = _service_roots(s["roots"], "serve")
    token_path, tokens, created = ensure_token_file(s["token_file"])
    key_file = s["identity_key_file"] or default_identity_key_file(token_path)
    _key_path, identity_key, key_created = ensure_identity_key(key_file)
    config = ServeConfig(
        roots=Roots(roots),
        tokens=tokens,
        host=s["bind"],
        port=s["port"],
        allow_remote=s["allow_remote"],
        allowed_hosts=tuple(s["allowed_hosts"]),
        workers=s["workers"] or default_workers(),
        catalog=s["catalog"],
        catalog_rescan_s=s["catalog_rescan"],
        formats=s["formats"],
        identity_key=identity_key,
        identity_addresses=tuple(s["identity_addresses"]),
        allow_origins=tuple(s["allow_origins"]),
        viewer=s["viewer"],
    )
    server = Server(config)  # binds: a port in use stops here (address_unavailable)
    configure_logging()
    server.start()
    data = model.build_serve_started(
        host=server.host,
        port=server.port,
        roots=[r.id for r in roots],
        workers=config.workers,
        token_file_created=created,
    )
    if args.json:
        sys.stdout.write(model.dumps(model.envelope("serve_started", data, source=None)) + "\n")
    else:
        _say(f"solidseas serve: listening on {data['url']} (roots: {', '.join(data['roots'])})")
        if created:
            _say("created the token file, holding one token named default (it is never printed)")
        if key_created:
            _say("created the identity key file, the service's own secret for /v1/identity (never printed)")
        _say("clients send Authorization: Bearer <token>, with a token from the token file")
        if config.viewer:
            _say(f"the reference viewer: {data['url'].removesuffix('v1/')}viewer/ (it asks for a token)")
    sys.stdout.flush()
    run_until_signalled(server)  # ends the process
    return EXIT_OK  # pragma: no cover


# --------------------------------------------------------------------------- the catalog
def _index_roots(args: argparse.Namespace) -> list[Root]:
    """The roots ``index`` was given: each FOLDER (``project``, ``project2``...),
    each ``--root ID=FOLDER`` and each ``--library FOLDER`` or ``--library ID=FOLDER``."""
    from .roots import ROOT_ID

    roots: list[Root] = []
    for i, folder in enumerate(args.folders or ()):
        root_id = "project" if i == 0 else f"project{i + 1}"
        roots.append(Root(root_id, os.path.abspath(folder), True, "project"))
    roots += _root_args(args.root, "project", "--root")
    for i, text in enumerate(args.library or ()):
        root_id, sep, folder = text.partition("=")
        if sep and folder and ROOT_ID.match(root_id):
            roots.append(Root(root_id, os.path.abspath(folder), True, "library"))
        else:
            roots.append(Root(f"library{i + 1}", os.path.abspath(text), True, "library"))
    if not roots:
        raise InvalidArgumentError("index needs a folder", detail={"parameter": "folder"})
    for r in roots:
        if not os.path.isdir(r.path):
            raise FileNotFoundError(2, f"root {r.id}: no such folder", r.path)
    return roots


def _named_root(root_id: str, args: argparse.Namespace) -> bool:
    """Whether ``index`` was given ``root_id`` by name (``--root ID=FOLDER`` or ``--library
    ID=FOLDER``) rather than making it up for a folder given alone."""
    texts = [*(getattr(args, "root", None) or ()), *(getattr(args, "library", None) or ())]
    return any(t.partition("=")[0] == root_id and "=" in t for t in texts)


def _check_in_project(args: argparse.Namespace) -> None:
    from . import netfs

    if getattr(args, "in_project", False) and os.name != "nt" and not netfs.readable():
        raise InvalidArgumentError(
            "--in-project cannot tell a network filesystem here; name the database with --db instead",
            detail={"parameter": "in_project"},
        )


def _project_db(near: str) -> str | None:
    """The in-project catalog in ``near`` or the nearest folder above it that has one."""
    from .catalog import store

    p = os.path.abspath(near)
    if store.is_network(p):  # an in-project catalog is never on a share: none is looked for there
        return None
    while True:
        db = os.path.join(p, store.PROJECT_FOLDER, store.CATALOG_FILE)
        if os.path.isfile(db):
            return db
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


def _open_catalog(args: argparse.Namespace, near: str, mode: str = "r"):
    """The catalog a query command names: ``--db``, ``--catalog``, ``--in-project`` (the
    nearest ``.solidseas`` folder at or above ``near``), else the catalog in the cache whose
    root holds ``near``."""
    from . import catalog
    from .errors import NotInCatalogError

    _check_in_project(args)
    if args.db:
        return catalog.open(db=args.db, mode=mode)
    if args.catalog:
        return catalog.open(name=args.catalog, mode=mode)
    if args.in_project:
        db = _project_db(near)
        if db is None:
            raise NotInCatalogError(
                "no in-project catalog here: run solidseas index FOLDER --in-project first"
            )
        # the catalog's own name, as index gave it (read from the catalog)
        return catalog.Catalog(db, location="project", name=None, roots=None, mode=mode)
    name = catalog.find_catalog(near)
    if name is None:
        raise NotInCatalogError(
            "no catalog holds that folder: run solidseas index FOLDER first, or name one with --catalog"
        )
    return catalog.open(name=name, mode=mode)


def _counts_line(c: dict[str, Any]) -> str:
    parts = [f"{c['seen']:,} documents"]
    for key, word in (
        ("added", "added"),
        ("changed", "changed"),
        ("moved", "moved"),
        ("removed", "removed"),
        ("stale", "kept stale"),
        ("read_ok", "read"),
        ("read_errors", "could not be read"),
        ("hashed", "hashed"),
    ):
        if c.get(key):
            parts.append(f"{c[key]:,} {word}")
    return ", ".join(parts)


def cmd_index(args: argparse.Namespace) -> int:
    from . import catalog

    _check_in_project(args)
    roots = Roots(_index_roots(args))
    if args.in_project and not args.json:
        sys.stderr.write(
            "solidseas: the catalog goes into the project's .solidseas folder, and with it the names, "
            "properties and stored paths of every file in the project\n"
        )
    location = "project" if args.in_project else "cache"
    with catalog.open(roots, location=location, name=args.catalog, db=args.db) as cat:
        # A folder given without an id keeps the one the catalog has for it (serve's, say).
        cat.keep_stored_ids(r.id for r in roots if not _named_root(r.id, args))
        if args.part_number_property is not None:
            cat.configure(part_number_property=args.part_number_property or None)
        if args.formats is not None:
            cat.configure(formats=args.formats)
        data = cat.scan(
            workers=args.workers,
            hash=args.hash,
            previews=not args.no_previews,
            verify=args.verify,
            file_timeout=args.file_timeout,
            max_seconds=args.timeout,
        )
    partial = data["counts"]["read_errors"] or data["truncated"] or data["cancelled"]
    code = EXIT_PARTIAL if partial else EXIT_OK
    if args.json:
        return _emit(args, "catalog_scan", data, code)
    _say(f"catalog {data['catalog']}: {_counts_line(data['counts'])} in {data['seconds']['total']:.1f} s")
    for r in data["roots"]:
        extra = f", stopped early ({r['truncated_reason']})" if r["truncated_reason"] else ""
        _say(f"  {r['id']}: {r['state']}, {r['documents']:,} documents{extra}")
    for root_id in data["removed_roots"]:
        _say(f"  {root_id}: removed with its rows")
    for e in data["errors"][:20]:
        _say(f"  {e['root']}:{e['path']}  {e['error']['code']}")
    if data["truncated"]:
        _say(f"stopped early ({data['truncated_reason']}); the next index carries on")
    return code


def _uses_text(uses: list[dict[str, Any]]) -> str:
    out = []
    for u in uses:
        cfg = u["user_configuration"] or "?"
        target = f" (its {u['configuration']})" if u["configuration"] else ""
        out.append(f"{cfg}: {u['instances']}{target}, {u['unsuppressed']} unsuppressed, {u['in_bom']} in BOM")
    return "; ".join(out)


def cmd_where_used(args: argparse.Namespace) -> int:
    with _open_catalog(args, os.path.dirname(os.path.abspath(args.file))) as cat:
        root, rel = cat.locate(args.file)
        data = cat.where_used(
            root, rel, configuration=args.configuration, indirect=not args.direct, max_depth=args.max_depth
        )
    if args.json:
        return _emit(args, "where_used", data)
    t = data["target"]
    when = f" (indexed {data['as_of']})" if data["as_of"] else ""
    _say(f"{t['path']}: used by {data['counts']['users']:,} documents{when}")
    if not data["complete"]:
        _say("  the index is not complete yet: rows are waiting to be read or resolved")
    for u in data["users"]:
        via = " via " + " > ".join(v["path"] or v["name"] for v in u["via"]) if u["via"] else ""
        detail = _uses_text(u["uses"]) if u["uses"] else ", ".join(
            f"{v['sheet']}/{v['view']} ({v['configuration']})" for v in u["views"]
        )
        _say(f"  {u['relation']:<20}{u['root']}:{u['path']}{via}  {detail}")
    for p in data["possible"]:
        _say(f"  possibly            {p['root']}:{p['path']} (ambiguous reference {p['file_name']})")
    for m in data["name_matches"]:
        stored = m["stored_path"] or m["file_name"]
        _say(f"  same name, not found {m['root']}:{m['path']} ({m['status']}: {stored})")
    return EXIT_OK


def _search_text(parts: list[str]) -> str:
    """The search text of ``search``'s arguments, each one unit as the shell gave it: one
    with spaces is a phrase, or a filter's whole value (``"desc:steel bracket"``)."""
    from .catalog.query import FILTERS

    out = []
    for a in parts:
        if '"' in a or not any(ch.isspace() for ch in a):
            out.append(a)
            continue
        head, sep, rest = a.partition(":")
        out.append(f'{head}:"{rest}"' if sep and head.lower() in FILTERS else f'"{a}"')
    return " ".join(out)


def cmd_search(args: argparse.Namespace) -> int:
    with _open_catalog(args, os.getcwd()) as cat:
        data = cat.search(_search_text(args.text), sort=args.sort, limit=args.limit, cursor=args.cursor)
    if args.json:
        return _emit(args, "catalog_search", data)
    for r in data["results"]:
        pn = f"  {r['part_number']}" if r["part_number"] else ""
        desc = f"  {r['description']}" if r["description"] else ""
        _say(f"{r['root']}:{r['path']}{pn}{desc}")
    more = f" (more with --cursor {data['next_cursor']})" if data["next_cursor"] else ""
    _say(f"{len(data['results']):,} results{more}")
    return EXIT_OK


def cmd_duplicates(args: argparse.Namespace) -> int:
    with _open_catalog(args, os.getcwd()) as cat:
        data = cat.duplicates(names=args.names, limit=args.limit, cursor=args.cursor)
    if args.json:
        return _emit(args, "duplicates", data)
    for g in data["groups"]:
        _say(f"{g['sha256'][:16]}  {g['size']:,} bytes x {len(g['files'])}")
        for f in g["files"]:
            _say(f"  {f['root']}:{f['path']}")
    for g in data["name_groups"] or ():
        _say(f"{g['name']}: {g['versions']} different files")
        for f in g["files"]:
            _say(f"  {f['root']}:{f['path']}")
    c = data["counts"]
    _say(f"{c['groups']:,} groups of identical files, {c['wasted_bytes']:,} bytes in the extra copies")
    if data["hash_pending"]:
        _say(f"{data['hash_pending']:,} files are not hashed yet: the list is partial")
    return EXIT_OK


def cmd_missing(args: argparse.Namespace) -> int:
    with _open_catalog(args, os.getcwd()) as cat:
        data = cat.missing_references(limit=args.limit, cursor=args.cursor)
    if args.json:
        return _emit(args, "missing_references", data)
    for d in data["documents"]:
        _say(f"{d['root']}:{d['path']}")
        for r in d["references"]:
            _say(f"  {r['status'] or '?':<20}{r['stored_path'] or r['file_name']}")
    c = data["counts"]
    _say(
        f"{c['documents']:,} documents: {c['missing']:,} missing, {c['ambiguous']:,} ambiguous, "
        f"{c['low_confidence']:,} low confidence (within the indexed folders)"
    )
    return EXIT_OK


def cmd_changes(args: argparse.Namespace) -> int:
    with _open_catalog(args, os.getcwd()) as cat:
        data = cat.changes(since=args.since, limit=args.limit, cursor=args.cursor)
    if args.json:
        return _emit(args, "catalog_changes", data)
    for e in data["events"]:
        before = f" (was {e['previous_root']}:{e['previous_path']})" if e["previous_path"] else ""
        _say(f"{e['time_utc']}  {e['kind']:<11}{e['root']}:{e['path']}{before}")
    return EXIT_OK


def cmd_catalogs(args: argparse.Namespace) -> int:
    from . import catalog

    data = model.build_catalog_list(catalog.list_catalogs(), cache_dir=catalog.cache_dir())
    if args.json:
        return _emit(args, "catalog_list", data)
    for c in data["catalogs"]:
        roots = ", ".join(f"{r['id']}={r['path']}" for r in c["roots"])
        _say(f"{c['name']}  {roots}  last scan {c['last_scan_utc'] or 'never'}")
    _say(f"{len(data['catalogs'])} catalogs in {data['cache_dir']}")
    return EXIT_OK


def cmd_clear_index(args: argparse.Namespace) -> int:
    from . import catalog
    from .catalog import store

    _check_in_project(args)
    if args.all:
        names = [c["name"] for c in catalog.list_catalogs()]
        removed = catalog.clear(all=True)
    elif args.db:
        db = os.path.abspath(args.db)
        names = [catalog.catalog_name(db) or os.path.splitext(os.path.basename(db))[0]]
        removed = catalog.clear(db=args.db)
    elif args.catalog:
        names = [args.catalog]
        removed = catalog.clear(args.catalog)
    else:
        folder = os.path.abspath(args.folder or os.getcwd())
        if args.in_project:
            # the nearest .solidseas folder at or above FOLDER, as the query commands find it
            db = _project_db(folder)
            names, removed = [], []
            if db is not None:
                project = os.path.dirname(os.path.dirname(db))
                names = [catalog.catalog_name(db) or store.default_name(project)]
                removed = catalog.clear(db=db)
        else:
            names = [store.default_name(folder)]
            removed = catalog.clear(names[0])
    data = model.build_catalog_cleared(removed, catalogs=names if removed else [])
    if args.json:
        return _emit(args, "catalog_cleared", data)
    _say(f"removed {len(removed)} files" if removed else "no catalog there")
    return EXIT_OK


def cmd_catalog(args: argparse.Namespace) -> int:
    with _open_catalog(args, os.path.abspath(args.folder or os.getcwd())) as cat:
        data = cat.status()
    if args.json:
        return _emit(args, "catalog", data)
    _say(f"catalog {data['name']} ({data['location']}): {data['state']}")
    for r in data["roots"]:
        _say(
            f"  {r['id']}  {r['path']}  {r['documents']:,} documents, {r['state']}, "
            f"last scan {r['last_scan_utc']}"
        )
    c = data["counts"]
    _say(
        f"  {c['parts']:,} parts, {c['assemblies']:,} assemblies, {c['drawings']:,} drawings; "
        f"{c['read_errors']:,} read errors, {c['pending']:,} waiting"
    )
    if data["formats"] != [registry.SOLIDWORKS]:
        read = ", ".join(f"{n:,} {f}" for f, n in c["formats"].items())
        _say(f"  indexes {', '.join(data['formats'])}" + (f"; read {read}" if read else ""))
    return EXIT_OK


# --------------------------------------------------------------------------- drawings (provisional)
# ``solidseas drawing ACTION`` (docs/DRAWINGS.md 14, docs/drawings/cli.md): one kind,
# drawing_result. The CLI never signs or releases a drawing.
DRAWING_EXTENSION = ".ssdrw"
THREAD_ANSWERS_BYTES = 64 * 1024  # a --confirm-threads file
THREAD_ANSWERS_MAX = 1000  # answers in it
TITLE_FLAGS = (
    ("title", "title"),
    ("number", "number"),
    ("part_number", "part-number"),
    ("revision", "revision"),
    ("material", "material"),
    ("finish", "finish"),
    ("drawn_by", "drawn-by"),
)
_FEATURE_ID = re.compile(r"f-[0-9]{1,9}")


def _scale_option(text: str) -> str | tuple[int, int]:
    if text == "auto":
        return "auto"
    m = re.fullmatch(r"([0-9]{1,4}):([0-9]{1,4})", text)
    if m is None:
        raise InvalidArgumentError(
            f"--scale is auto or sheet:model such as 1:2, not {text!r}", detail={"parameter": "scale"}
        )
    return int(m.group(1)), int(m.group(2))


def _drawing_options(args: argparse.Namespace):
    """The ``DrawingOptions`` the flags of ``drawing new`` name; each is checked by
    ``DrawingOptions`` itself (``invalid_argument`` naming the field)."""
    from .drawing.types import DrawingOptions

    views: str | tuple[str, ...] = "auto"
    if args.views != "auto":
        views = tuple(v.strip() for v in args.views.split(",") if v.strip())
    return DrawingOptions(
        process=args.process,
        scheme=args.scheme,
        detail=getattr(args, "detail", None) or "full",
        units=args.units,
        views=views,
        front=None if args.front == "auto" else args.front,
        turn=args.turn,
        sheet=args.sheet,
        scale=_scale_option(args.scale),
        configuration=args.configuration,
        view_sheets=(("isometric", 2),) if getattr(args, "isometric_sheet", False) else (),
    )


def _drawing_settings(path: str | None) -> tuple[Any, list[str], str, bool]:
    """(settings, the fallbacks, the file read, whether it was there): ``--settings FILE``,
    which must exist, or the user's Drawing.json, whose absence gives the defaults."""
    from .drawing import settings as settings_mod

    target = path if path is not None else settings_mod.settings_path()
    found = os.path.isfile(target)
    if path is not None and not found:
        raise FileNotFoundError(2, "no Drawing Settings file there", path)
    settings, problems = settings_mod.load_settings(target)
    return settings, list(problems), target, found


def _title_names(settings) -> tuple[str, ...]:
    """The property names the title block reads, as the pipeline gives them to the source."""
    groups = ("part_number", "number", "title", "revision", "model_revision", "material", "finish")
    return tuple(n for g in groups for n in getattr(settings.title_sources, g))


def _thread_answers(path: str) -> dict[str, tuple[str | None, float | None]]:
    """A ``--confirm-threads`` file: a JSON object from feature ids to a thread (its
    designation, ``M6 x 1``, or its tapped form, ``M6 x 1-6H``), to null for a plain
    hole, or to ``{"thread": ..., "depth_mm": N}`` (or ``depth_in``) for a blind hole's
    thread depth. Returns {id: (thread or None, depth in metres or None)}."""
    with open(path, "rb") as fh:
        raw = fh.read(THREAD_ANSWERS_BYTES + 1)
    if len(raw) > THREAD_ANSWERS_BYTES:
        raise InvalidArgumentError(
            f"--confirm-threads: the file is larger than {THREAD_ANSWERS_BYTES // 1024} KiB",
            detail={"parameter": "confirm-threads"},
        )
    data = model.loads(raw, parameter="confirm-threads")

    def bad(why: str) -> InvalidArgumentError:
        return InvalidArgumentError(f"--confirm-threads: {why}", detail={"parameter": "confirm-threads"})

    if not isinstance(data, dict):
        raise bad("the file must hold one JSON object from feature ids to threads")
    if len(data) > THREAD_ANSWERS_MAX:
        raise bad(f"more than {THREAD_ANSWERS_MAX:,} answers")
    out: dict[str, tuple[str | None, float | None]] = {}
    for fid, answer in data.items():
        if not _FEATURE_ID.fullmatch(fid):
            raise bad(f"{fid[:40]!r} is not a feature id such as f-3")
        depth = None
        if isinstance(answer, dict):
            unknown = set(answer) - {"thread", "depth_mm", "depth_in"}
            if unknown or "thread" not in answer or ("depth_mm" in answer and "depth_in" in answer):
                raise bad(f"{fid}: an answer object holds thread and at most one of depth_mm and depth_in")
            for key, scale in (("depth_mm", 0.001), ("depth_in", 0.0254)):
                if key in answer:
                    v = answer[key]
                    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 10_000:
                        raise bad(f"{fid}: {key} must be a positive number")
                    depth = float(v) * scale
            answer = answer["thread"]
        if answer is not None and (not isinstance(answer, str) or not answer.strip() or len(answer) > 64):
            raise bad(f"{fid}: the answer is a thread such as M6 x 1, or null for a plain hole")
        if answer is None and depth is not None:
            raise bad(f"{fid}: a plain hole has no thread depth")
        out[fid] = (answer.strip() if isinstance(answer, str) else None, depth)
    return out


def _live_thread_candidates(features) -> dict[str, tuple[str, ...]]:
    """{feature id: the threads its diameter is the tap drill of} for the holes and hole
    patterns of a run's ``FeatureSet`` (the holes a pattern holds answer through it)."""
    from .drawing.types import Hole, Pattern

    members = {k for f in features.features for k in (getattr(f, "members", ()) or ())}
    out: dict[str, tuple[str, ...]] = {}
    for i, f in enumerate(features.features):
        if i in members:
            continue
        hole = f
        if isinstance(f, Pattern):
            hole = features.features[f.members[0]] if f.members else None
        if isinstance(hole, Hole) and hole.thread:
            out[f"f-{i + 1}"] = tuple(hole.thread)
    return out


def _thread_decisions(answers, features) -> dict[str, dict[str, Any]]:
    """The planner's decisions for the answers of a ``--confirm-threads`` file, each checked
    against the part's thread candidates: a thread the hole's diameter is not the tap
    drill of, or a feature that is not a candidate, is refused."""
    from .drawing import standards

    candidates = _live_thread_candidates(features)
    by_name = {t.designation.casefold(): t for t in standards.THREADS}
    by_name.update({t.internal().casefold(): t for t in standards.THREADS})
    decisions: dict[str, dict[str, Any]] = {}
    for fid, (answer, depth) in answers.items():
        if fid not in candidates:
            raise InvalidArgumentError(
                f"--confirm-threads: {fid} is not a thread candidate of this part "
                "(drawing check PART lists them)",
                detail={"parameter": "confirm-threads"},
            )
        if answer is None:
            decisions[fid] = {"thread": None}
            continue
        thread = by_name.get(" ".join(answer.split()).casefold())
        if thread is None or thread.designation not in candidates[fid]:
            raise InvalidArgumentError(
                f"--confirm-threads: {fid} may be {', '.join(candidates[fid])}, not {answer[:40]!r}",
                detail={"parameter": "confirm-threads"},
            )
        decisions[fid] = {"thread": thread.internal()}
        if depth is not None:
            decisions[fid]["thread_depth"] = depth
    return decisions


def _with_decisions(drawing, decisions: dict[str, dict[str, Any]]):
    """``drawing`` with the user's thread answers kept on its features (13.4), so a
    regeneration keeps them."""
    if not decisions:
        return drawing
    records = []
    for rec in drawing.features:
        extra = decisions.get(rec.id)
        if extra:
            merged = dict(rec.decisions)
            merged.update(extra)
            rec = replace(rec, decisions=tuple(merged.items()))
        records.append(rec)
    return replace(drawing, features=tuple(records))


def _unit_unstated(options, settings, source) -> bool:
    """Whether the drawing's unit would be a guess: ``--units part`` (and Settings that
    follow the part) on a part that states no unit."""
    if options.units != "part" or settings.standard.units in ("in", "mm"):
        return False
    return getattr(getattr(source, "units", None), "origin", None) != "file"


@dataclass
class _Made:
    run: Any
    drawing: Any
    features: Any
    seconds: list[tuple[str, float]]
    warnings: list[str]


def _make(part: str, options, settings, fields: dict[str, str], *, answers=None, refuse_guess: bool) -> _Made:
    """A drawing of ``part`` in memory: the source read first (its unit checked: a guessed
    unit is refused with ``refuse_guess``, else said in a warning), then the stages of
    ``solidseas.drawing.pipeline.run``. Thread answers are given to the planner and kept
    on the features."""
    from .drawing import pipeline
    from .drawing.limits import DEFAULT_LIMITS
    from .drawing.source import open_source

    t0 = time.perf_counter()
    units = None if options.units == "part" else options.units
    src = open_source(
        part,
        configuration=options.configuration,
        bodies=options.bodies,
        units=units,
        title_names=_title_names(settings),
        limits=DEFAULT_LIMITS,
    )
    read = time.perf_counter() - t0
    warnings: list[str] = []
    if _unit_unstated(options, settings, src):
        guess = src.units.unit
        if refuse_guess:
            raise InvalidArgumentError(
                f"the part states no unit of length (its sizes look like {guess}); "
                "name one with --units in or --units mm",
                detail={"parameter": "units", "rule": "units_unstated"},
            )
        warnings.append(f"the part states no unit of length; {guess} was guessed from its sizes")
    stages: dict[str, Any] = {"source": lambda *_a, **_k: src}
    run = pipeline.run(part, options=options, fields=fields, settings=settings, stages=stages)
    seconds = [(name, read if name == "source" else took) for name, took in run.seconds]
    drawing = run.drawing
    if answers:
        # the answers are the user's decisions on the features, and the drawing is laid
        # out again with them, as the editor's Confirm Thread does
        from .drawing import edit

        t1 = time.perf_counter()
        decisions = _thread_decisions(answers, run.features)
        drawing, _checks = edit.relayout(_with_decisions(drawing, decisions))
        seconds = [*seconds, ("threads", time.perf_counter() - t1)]
    return _Made(run, drawing, run.features, seconds, warnings)


def _drawing_checks(drawing, run: Any = None) -> tuple[Any, ...]:
    """The checks of ``drawing`` (``docs/DRAWINGS.md`` 20.1) from ``checks.run_checks``;
    with ``run`` (a live run) the checks its pipeline already made, or every check when
    the run keeps the plan and layout. While this SolidSeas has no checks module, the
    checks the drawing carries."""
    from .drawing import pipeline

    if run is not None and (drawing.checks or getattr(run, "orchestrated", None) is not None):
        return tuple(drawing.checks)  # the pipeline checked the drawing as it made it
    try:
        run_checks = pipeline.resolve("checks", pipeline.ENTRY_POINTS["checks"])
    except UnsupportedOperationError:
        return tuple(drawing.checks)
    done = getattr(run, "orchestrated", None) if run is not None else None
    if done is not None:
        return tuple(run_checks(drawing, planned=done.planned, layout=done.result))
    return tuple(run_checks(drawing))


def _read_drawing(path: str):
    """A ``.ssdrw`` read as the library reads one (``document.read``); a path that is not
    a ``.ssdrw`` is a usage error."""
    from .drawing import document

    if not path.lower().endswith(DRAWING_EXTENSION):
        raise InvalidArgumentError(
            f"a drawing is a {DRAWING_EXTENSION} file: {path}", detail={"parameter": "drawing"}
        )
    return document.read(path)


def _out_folder(out: str, sources: Iterable[str], allow_source_dir: bool) -> str:
    """``--out DIR``: a folder that exists, that the 3D Print file's folder rules accept
    (12.6), and outside the sources' folders unless ``--allow-source-dir``."""
    from .drawing import document

    final = check_output_dir(
        out, [os.path.dirname(os.path.abspath(s)) for s in sources], allow_source_dir=allow_source_dir
    )
    if not os.path.isdir(final):
        raise _refused(f"the folder {out} does not exist", "output_folder")
    problem = document.folder_problem(final)
    if problem is not None:
        raise _refused(f"{problem}: {out}", "output_folder")
    return final


def _guarded(target, sources: Iterable[str], allow_source_dir: bool) -> str:
    """The write guards for one drawing file: a new name, or the drawing's own unchanged
    file (``target.replaces``), which the library checks again by its hash."""
    return check_output_file(
        target.path, list(sources), allow_source_dir=allow_source_dir, force=target.replaces is not None
    )


def _write_exports(drawing, out: str, kinds: Iterable[str], sources, allow_source_dir: bool):
    """Write the PDF and DXF of ``drawing`` into ``out`` (12.5, 12.6): a free name, or the
    drawing's own unchanged PRELIMINARY export rewritten; a released export never
    replaces anything. Returns the drawing with the exports recorded (unless it is
    RELEASED), the files' data, the words for warnings and the seconds."""
    from . import drawing as dwg
    from .drawing import document

    released = drawing.status == "RELEASED"
    files, words, seconds = [], [], []
    for kind in kinds:
        t0 = time.perf_counter()
        target = document.export_target(drawing, out, kind)
        path = _guarded(target, sources, allow_source_dir)
        writer = dwg.write_pdf if kind == "pdf" else dwg.write_dxf
        saved = document.write_output(
            path, lambda fh, w=writer, d=drawing: w(d, fh), replaces=target.replaces
        )
        if not released:
            drawing = document.record_output(drawing, kind, os.path.basename(saved.path), saved.sha256)
        files.append(
            model.drawing_file_data(
                saved.path,
                kind,
                saved.sha256,
                saved.size,
                replaced=target.replaces is not None,
                renamed=target.renamed,
                released=released,
            )
        )
        if target.renamed:
            words.append(target.words)
        seconds.append((kind, time.perf_counter() - t0))
    return drawing, files, words, seconds


def _release_record(drawing, path: str) -> list[str]:
    """For a RELEASED drawing: whether its released exports beside it are still the files
    released (17.2); empty otherwise."""
    from .drawing import document, release
    from .drawing.limits import DEFAULT_LIMITS

    folder = os.path.dirname(os.path.abspath(path))

    def look(name: str) -> str | None:
        return document.file_sha256(os.path.join(folder, name), DEFAULT_LIMITS.output_bytes)

    return list(release.check_release_record(drawing, look))


def _model_check(drawing, drawing_path: str, model_path: str) -> dict[str, Any]:
    """``check --model``: the model file against the drawing's MODEL reference: its SHA-256
    (the exact file), its geometry digest when the file differs, and whether the
    reference the drawing stores (relative or stored path) names this file."""
    from .drawing import document, locate, merge
    from .drawing.source import open_source

    if not os.path.isfile(model_path):
        raise FileNotFoundError(2, "the model file is not there", model_path)
    ref = drawing.model or {}
    sha = document.file_sha256(model_path)
    sha_ok = sha is not None and sha == ref.get("sha256")
    geometry_ok = None
    assembly = ref.get("format") == "sldasm"  # its parts are files of their own, which its geometry covers
    if (assembly or not sha_ok) and ref.get("geometry"):
        src = open_source(model_path, configuration=ref.get("configuration"))
        geometry_ok = src.geometry_digest == ref.get("geometry")
    parts_changed = assembly and sha_ok and geometry_ok is False
    sha_ok = sha_ok and not parts_changed
    where = locate.model_reference(model_path, drawing_path)
    same = False
    for key in ("relative", "stored"):
        mine, theirs = where.get(key), ref.get(key)
        if isinstance(mine, str) and isinstance(theirs, str):
            same = same or os.path.normcase(mine.replace("\\", "/")) == os.path.normcase(
                theirs.replace("\\", "/")
            )
    if sha_ok:
        words = (
            locate.MATCHES
            if same
            else "this is the drawing's model, at another place than the drawing records"
        )
    elif geometry_ok:
        words = merge.GEOMETRY_UNCHANGED
    elif parts_changed:
        words = "this is the drawing's assembly, but its parts have changed since the drawing was made"
    else:
        words = locate.CHANGED
    return {
        "path": os.path.abspath(model_path),
        "verified": sha_ok,
        "sha256_matches": sha_ok or parts_changed,
        "geometry_matches": geometry_ok,
        "reference_matches": same,
        "words": words,
    }


def _check_line(c: dict[str, Any]) -> str:
    where = "" if c["item"] == c["code"] else f" {c['item']}"
    return f"  {c['level']} {c['code']}{where}: {c['message']}"


def _say_drawing(data: dict[str, Any]) -> None:
    """``drawing_result`` in plain words."""
    d = data["drawing"]
    for f in data["files"]:
        how = " (its earlier version replaced)" if f["replaced"] else ""
        _say(f"wrote {f['path']}{how}")
    if d is not None:
        number = (d["title"].get("number") or {}).get("text") or d["model"]["name"] or d["id"]
        c = d["counts"]
        if d["model"].get("format") == "sldasm":
            items = f"{c['items']} item{'' if c['items'] == 1 else 's'}"
            balloons = f"{c['balloons']} balloon{'' if c['balloons'] == 1 else 's'}"
            what = f"assembly drawing {number}, revision {d['revision'] or '-'}: {items} and {balloons} in"
        else:
            what = f"drawing {number}, revision {d['revision'] or '-'}: {c['shown']} dimensions in"
        sheet = f"sheet {d['options']['sheet']} at {d['options']['scale']}"
        if c.get("sheets", 1) > 1:  # a parts list going on past the first sheet
            sheet = f"{c['sheets']} {d['options']['sheet']} sheets at {d['options']['scale']}"
        _say(f"{d['status']} {what} {c['views']} views, {sheet}")
        if data["action"] == "show":
            for key, field_ in d["title"].items():
                _say(f"  {key}: {field_['text']}")
            for s in d["signatures"]:
                _say(
                    f"  {s['row']}: {s['name']} {s['date']}"
                    + ("" if s["current"] else " (no longer current)")
                )
            for r in d["revisions"]:
                done = f", released {r['date']} by {r['approved']}" if r["date"] else ""
                _say(f"  revision {r['rev']}: {r['description']}{done}")
    if data["merge"] is not None:
        _say(f"update: {data['merge']['words']}")
        for item in data["merge"]["items"]:
            _say(f"  {item}")
        if data["dry_run"]:
            _say("dry run: nothing was written")
    if data["coverage"] is not None:
        _say(f"coverage: {data['coverage']['words']}")
    if data["action"] in ("new", "update", "check"):
        n = data["check_counts"]
        _say(f"checks: {n['error']} errors, {n['warning']} warnings, {n['information']} information")
        for c in data["checks"]:
            if c["level"] != "information":
                _say(_check_line(c))
    for t in data["thread_candidates"]:
        state = (t["confirmed"] or "plain") if t["answered"] else "not answered"
        threads = ", ".join(t["threads"])
        _say(f"thread candidate {t['feature']} ({t['count']}X {t['diameter_mm']:g} mm): {threads}; {state}")
    if data["model_check"] is not None:
        _say(f"model: {data['model_check']['words']}")
    s = data["settings"]
    if s is not None:
        _say(f"Drawing Settings: {s['path']}" + ("" if s["found"] else " (not there: the defaults)"))
        for f in s["fallbacks"]:
            _say(f"  fallback: {f}")
        for key in s["first_use"]:
            _say(f"  waiting for your answer: {key}")
    for w in data["warnings"]:
        _say(f"warning: {w}")


def _drawing_done(args: argparse.Namespace, data: dict[str, Any], code: int = EXIT_OK) -> int:
    if not args.json:
        _say_drawing(data)
    return _emit(args, "drawing_result", data, code)


def _total(seconds: list[tuple[str, float]], t0: float) -> list[tuple[str, float]]:
    return [*seconds, ("total", time.perf_counter() - t0)]


def _drawing_new(args: argparse.Namespace) -> int:
    from .drawing import document, locate

    t0 = time.perf_counter()
    out = _out_folder(args.out, [args.path], args.allow_source_dir)
    settings, problems, _where, _found = _drawing_settings(args.settings)
    if getattr(args, "detail", None) is None:
        args.detail = settings.defaults.detail
    options = _drawing_options(args)
    answers = _thread_answers(args.confirm_threads) if args.confirm_threads else None
    fields = {key: getattr(args, key) for key, _flag in TITLE_FLAGS if getattr(args, key) is not None}
    made = _make(args.path, options, settings, fields, answers=answers, refuse_guess=True)
    drawing = made.drawing
    t1 = time.perf_counter()
    checks = _drawing_checks(drawing, made.run)
    seconds = [*made.seconds, ("checks", time.perf_counter() - t1)]
    kinds = [k for k, asked in (("pdf", args.pdf), ("dxf", args.dxf)) if asked]
    drawing, files, words, more = _write_exports(drawing, out, kinds, [args.path], args.allow_source_dir)
    target = document.save_target(drawing, os.path.join(out, document.drawing_file_name(drawing)))
    path = _guarded(target, [args.path], args.allow_source_dir)
    drawing = locate.with_model_path(drawing, args.path, path)
    saved = document.save(drawing, path, replaces=target.replaces)
    drawing = saved.drawing
    files.insert(
        0,
        model.drawing_file_data(
            saved.path, "ssdrw", saved.sha256, saved.size, replaced=False, renamed=target.renamed
        ),
    )
    if target.renamed:
        words.insert(0, target.words)
    data = model.build_drawing_result(
        "new",
        drawing=drawing,
        files=files,
        checks=checks,
        coverage=drawing.coverage,
        thread_candidates=model.drawing_thread_candidates(drawing, made.features),
        seconds=_total([*seconds, *more], t0),
        warnings=[*(f"settings: {p}" for p in problems), *made.warnings, *drawing.warnings, *words],
    )
    return _drawing_done(args, data)


def _drawing_export(args: argparse.Namespace) -> int:
    t0 = time.perf_counter()
    loaded = _read_drawing(args.path)
    drawing = loaded.drawing
    if drawing.sheet is None:
        raise DrawingInvalidError(
            "the drawing's sheet is not one this SolidSeas reads, so it cannot be exported",
            detail={"parameter": "drawing", "rule": "drawing_invalid", "value": "sheet"},
        )
    out = _out_folder(args.out, [args.path], args.allow_source_dir)
    kinds = [k for k, asked in (("pdf", args.pdf), ("dxf", args.dxf)) if asked] or ["pdf", "dxf"]
    record = _release_record(drawing, args.path)
    _drawing, files, words, seconds = _write_exports(drawing, out, kinds, [args.path], args.allow_source_dir)
    data = model.build_drawing_result(
        "export",
        drawing=drawing,
        files=files,
        seconds=_total(seconds, t0),
        warnings=[*loaded.problems, *record, *words],
    )
    return _drawing_done(args, data)


def _drawing_update(args: argparse.Namespace) -> int:
    from . import drawing as dwg
    from .drawing import document, locate, release

    t0 = time.perf_counter()
    loaded = _read_drawing(args.path)
    drawing = loaded.drawing
    release.require_editable(drawing, "it must start a revision before Update from Model")
    try:
        merged, report = dwg.regenerate(drawing, args.model, drawing_path=loaded.path)
    except ModelNotFoundError as exc:  # a changed file is offered, never taken: --model takes it
        words = f"{exc}; name the model with --model to update from it"
        raise ModelNotFoundError(words, detail=exc.detail) from None
    seconds = [("regenerate", time.perf_counter() - t0)]
    t1 = time.perf_counter()
    checks = _drawing_checks(merged)
    seconds.append(("checks", time.perf_counter() - t1))
    files, words = [], []
    if not args.dry_run and not report.model_unchanged:
        problem = document.folder_problem(os.path.dirname(loaded.path))
        if problem is not None:
            raise _refused(f"{problem}: {args.path}", "output_folder")
        target = document.save_target(merged, final_path(loaded.path), loaded_sha256=loaded.sha256)
        path = check_output_file(target.path, [], allow_source_dir=True, force=target.replaces is not None)
        if args.model is not None:
            merged = locate.with_model_path(merged, args.model, path)
        saved = document.save(merged, path, replaces=target.replaces)
        merged = saved.drawing
        files.append(
            model.drawing_file_data(
                saved.path,
                "ssdrw",
                saved.sha256,
                saved.size,
                replaced=target.replaces is not None,
                renamed=target.renamed,
            )
        )
        if target.renamed:
            words.append(target.words)
    data = model.build_drawing_result(
        "update",
        drawing=merged,
        files=files,
        merge=report,
        checks=checks,
        coverage=None if report.model_unchanged or report.geometry_unchanged else merged.coverage,
        thread_candidates=model.drawing_thread_candidates(merged),
        seconds=_total(seconds, t0),
        warnings=[*loaded.problems, *words],
        dry_run=args.dry_run,
    )
    return _drawing_done(args, data)


def _failed(checks, strict: bool) -> bool:
    levels = {model.drawing_check_data(c)["level"] for c in checks}
    return "error" in levels or (strict and "warning" in levels)


def _drawing_check(args: argparse.Namespace) -> int:
    from .drawing.types import DrawingOptions

    t0 = time.perf_counter()
    if args.path.lower().endswith(DRAWING_EXTENSION):
        loaded = _read_drawing(args.path)
        drawing = loaded.drawing
        t1 = time.perf_counter()
        checks = _drawing_checks(drawing)
        seconds = [("read", t1 - t0), ("checks", time.perf_counter() - t1)]
        model_check = None if args.model is None else _model_check(drawing, loaded.path, args.model)
        data = model.build_drawing_result(
            "check",
            drawing=drawing,
            checks=checks,
            thread_candidates=model.drawing_thread_candidates(drawing),
            seconds=_total(seconds, t0),
            warnings=[*loaded.problems, *_release_record(drawing, loaded.path)],
            model_check=model_check,
        )
        failed = _failed(checks, args.strict) or (model_check is not None and not model_check["verified"])
        return _drawing_done(args, data, EXIT_PARTIAL if failed else EXIT_OK)
    if args.model is not None:
        raise InvalidArgumentError(
            "--model verifies a drawing's model; check a .ssdrw with it", detail={"parameter": "model"}
        )
    settings, problems, _where, _found = _drawing_settings(args.settings)
    made = _make(args.path, DrawingOptions(), settings, {}, refuse_guess=False)
    t1 = time.perf_counter()
    checks = _drawing_checks(made.drawing, made.run)
    seconds = [*made.seconds, ("checks", time.perf_counter() - t1)]
    data = model.build_drawing_result(
        "check",
        drawing=made.drawing,
        checks=checks,
        coverage=made.drawing.coverage,
        thread_candidates=model.drawing_thread_candidates(made.drawing, made.features),
        seconds=_total(seconds, t0),
        warnings=[*(f"settings: {p}" for p in problems), *made.warnings, *made.drawing.warnings],
    )
    return _drawing_done(args, data, EXIT_PARTIAL if _failed(checks, args.strict) else EXIT_OK)


def _drawing_show(args: argparse.Namespace) -> int:
    loaded = _read_drawing(args.path)
    drawing = loaded.drawing
    data = model.build_drawing_result(
        "show",
        drawing=drawing,
        checks=drawing.checks,
        thread_candidates=model.drawing_thread_candidates(drawing),
        warnings=[*loaded.problems, *_release_record(drawing, loaded.path)],
    )
    return _drawing_done(args, data)


def _drawing_settings_action(args: argparse.Namespace) -> int:
    settings, problems, where, found = _drawing_settings(args.settings)
    data = model.build_drawing_result(
        "settings",
        settings=model.drawing_settings_data(settings, problems, path=where, found=found),
    )
    return _drawing_done(args, data)


DRAWING_ACTIONS: dict[str, Callable[[argparse.Namespace], int]] = {
    "new": _drawing_new,
    "export": _drawing_export,
    "update": _drawing_update,
    "check": _drawing_check,
    "show": _drawing_show,
    "settings": _drawing_settings_action,
}


def cmd_drawing(args: argparse.Namespace) -> int:
    """``solidseas drawing ACTION`` (provisional): new, export, update, check, show and
    settings, each printing a ``drawing_result`` under ``--json``. It never signs or
    releases a drawing: approvals come from a person in the viewer."""
    return DRAWING_ACTIONS[args.action](args)


# --------------------------------------------------------------------------- other commands
def cmd_version(args: argparse.Namespace) -> int:
    data = model.build_version()
    if not args.json:
        _say(f"solidseas {data['solidseas']} (API {data['api']})")
    return _emit(args, "version", data)


def cmd_schema(args: argparse.Namespace) -> int:
    """Print a JSON Schema. It is JSON with or without ``--json``, and has no envelope."""
    if args.kind is None:
        _print_json(
            {
                "kinds": [
                    {
                        "kind": spec.name,
                        "schema_version": spec.schema_version,
                        "cli_commands": list(spec.cli_commands),
                        "rest_route": spec.rest_route,
                    }
                    for spec in model.KINDS.values()
                ]
            }
        )
        return EXIT_OK
    if args.kind not in model.KINDS:
        raise InvalidArgumentError(
            f"no kind named {args.kind!r}; run solidseas schema to list them", detail={"parameter": "kind"}
        )
    _print_json(model.KINDS[args.kind].schema if args.data else model.envelope_schema(args.kind))
    return EXIT_OK


def cmd_openapi(args: argparse.Namespace) -> int:
    """Print the REST service's OpenAPI description (provisional, ``docs/API.md`` 8.19), or
    write it to ``-o FILE`` under the write guards. It is JSON with or without ``--json``;
    with ``-o``, ``--json`` prints the ``file_written`` envelope."""
    from .serve.openapi import build_openapi

    if args.force and args.output is None:
        raise InvalidArgumentError("--force applies to -o FILE", detail={"parameter": "force"})
    if args.output is None:
        _print_json(build_openapi())
        return EXIT_OK
    out = check_output_file(args.output, [], allow_source_dir=False, force=args.force)
    data = (model.dumps(build_openapi(), pretty=True) + "\n").encode("utf-8")
    _write(out, data)
    if not args.json:
        _say(f"wrote the OpenAPI description ({len(data)} bytes) to {out}")
    return _emit(args, "file_written", model.build_file_written(out, len(data), mime="application/json"))


# --------------------------------------------------------------------------- versions
def _store_options(args: argparse.Namespace) -> dict[str, Any]:
    return {"project": args.project, "store": args.store}


def _when(text: str | None) -> str:
    return text[:16].replace("T", " ") if text else "-"


def _version_label(v: dict[str, Any]) -> str:
    return "working copy" if v["kind"] == "working" else v["id"][:12]


def _say_warnings(warnings: list[dict[str, Any]]) -> None:
    for w in warnings:
        _say(f"note: {w['message']}")


def cmd_history(args: argparse.Namespace) -> int:
    data = model.build_file_history(
        args.path,
        source=args.history_source,
        max_commits=args.max_commits,
        hashes=args.hashes,
        **_store_options(args),
    )
    if args.json:
        return _emit(args, "file_history", data)
    git = data["git"]
    if git is not None:
        branch = f"branch {git['branch']}" if git["branch"] else "no branch checked out"
        _say(f"{git['path']} in the Git repository at {git['work_tree']} ({branch})")
    else:
        _say(f"{data['file']['name']}: snapshots in {data['store']['path']}")
    working = {
        "changed": "changed, not committed" if git is not None else "changed since the newest snapshot",
        "new": "not committed yet" if git is not None else "no snapshot yet",
    }.get(data["working"]["state"], "")
    for v in data["versions"]:
        if v["kind"] == "working":
            _say(f"v{v['number']:<4}{'working copy':<14}{_when(v['time_utc'])}  {working}")
            continue
        who = f"{v['author']}: " if v["author"] else ""
        what = v["subject"] or ""
        extra = ""
        if v["status"] == "deleted":
            extra = " (deleted)"
        elif not v["available"]:
            extra = " (not on this machine)"
        _say(f"v{v['number']:<4}{_version_label(v):<14}{_when(v['time_utc'])}  {who}{what}{extra}".rstrip())
    if data["working"]["state"] == "missing":
        _say("the file does not exist now")
    if not data["versions"]:
        _say("no versions yet: take one with solidseas snapshot FILE, or commit the file")
    _say_warnings(data["warnings"])
    if data["truncated"]:
        _say(f"the history stops after {git['commits_walked']:,} commits (--max-commits)")
    return EXIT_OK


def cmd_snapshot(args: argparse.Namespace) -> int:
    data = model.build_snapshot_taken(args.path, note=args.note, **_store_options(args))
    if args.json:
        return _emit(args, "snapshot_taken", data)
    s = data["snapshot"]
    name = data["file"]["name"]
    if data["new"]:
        _say(f"took snapshot v{s['number']} ({s['id']}) of {name} in {data['store']['path']}")
    else:
        _say(f"{name} is unchanged since snapshot v{s['number']} ({s['id']}): nothing new was stored")
    return EXIT_OK


def _number(value: float) -> str:
    return f"{value:,.6g}" if abs(value) < 1e6 else f"{value:,.0f}"


def _say_geometry_change(c: dict[str, Any]) -> str:
    m = c["measure"]
    a, b = c["from"], c["to"]
    words = {
        "volume_mm3": ("volume", " mm3"),
        "area_mm2": ("area", " mm2"),
        "size_x_mm": ("size in x", " mm"),
        "size_y_mm": ("size in y", " mm"),
        "size_z_mm": ("size in z", " mm"),
        "min_x_mm": ("lowest x", " mm"),
        "min_y_mm": ("lowest y", " mm"),
        "min_z_mm": ("lowest z", " mm"),
    }
    label, unit = words.get(m, (m.replace("_", " "), ""))
    text = f"{label} {_number(a)}{unit} -> {_number(b)}{unit}"
    if m in ("volume_mm3", "area_mm2") and a:
        text += f" ({(b - a) / abs(a):+.2%})"
    return text


def _say_property(p: dict[str, Any] | None) -> str:
    if p is None:
        return "-"
    if p["type"] == "text":
        return f'"{p["value"] if p["value"] is not None else p["text"] or ""}"'
    return str(p["text"] if p["text"] is not None else p["value"])


def cmd_diff(args: argparse.Namespace) -> int:
    data = model.build_version_diff(
        args.path,
        args.older,
        args.newer,
        source=args.history_source,
        measure=not args.no_measures,
        max_seconds=args.timeout,
        **_store_options(args),
    )
    if args.json:
        return _emit(args, "version_diff", data)
    a, b = data["from"], data["to"]
    _say(
        f"{data['file']['name']}: v{a['number']} ({_version_label(a)}, {_when(a['time_utc'])}) to "
        f"v{b['number']} ({_version_label(b)}, {_when(b['time_utc'])})"
    )
    if data["same_content"]:
        _say("the two versions are the same file")
    props = data["properties"]
    if any(props.values()):
        _say("properties")
        for p in props["added"]:
            where = f" ({p['configuration']})" if p["configuration"] else ""
            _say(f"  + {p['name']}{where} = {_say_property(p['to'])}")
        for p in props["removed"]:
            where = f" ({p['configuration']})" if p["configuration"] else ""
            _say(f"  - {p['name']}{where} (was {_say_property(p['from'])})")
        for p in props["changed"]:
            where = f" ({p['configuration']})" if p["configuration"] else ""
            _say(f"  ~ {p['name']}{where}: {_say_property(p['from'])} -> {_say_property(p['to'])}")
    cfgs = data["configurations"]
    if cfgs["added"] or cfgs["removed"]:
        _say("configurations")
        for name in cfgs["added"]:
            _say(f"  + {name}")
        for name in cfgs["removed"]:
            _say(f"  - {name}")
    changes = [c for c in data["document"]["changes"] if c["field"] != "preview"]
    if changes:
        _say("document")
        for c in changes:
            where = f" ({c['configuration']})" if c["configuration"] else ""
            _say(f"  {c['field'].replace('_', ' ')}{where}: {c['from'] or '(none)'} -> {c['to'] or '(none)'}")
    g = data["geometry"]
    if g["compared"]:
        _say("geometry")
        for row in g["configurations"]:
            name = row["configuration"] or "the model"
            words = {
                "unchanged": "unchanged",
                "changed": "changed",
                "added": "added",
                "removed": "removed",
                "not_stored": "not stored in either version",
                "not_compared": "not compared: one version does not store its bodies",
            }.get(row["status"], row["status"])
            _say(f"  {name}: {words}")
            for c in row["changes"]:
                _say(f"    {_say_geometry_change(c)}")
            if row["status"] == "changed" and not row["changes"]:
                _say("    no difference in its counts or measures")
    elif g["reason"]:
        _say(f"geometry: not compared ({g['reason'].replace('_', ' ')})")
    _say_warnings(data["warnings"])
    return EXIT_OK


# --------------------------------------------------------------------------- command table
@dataclass(frozen=True)
class Command:
    """One CLI command: the JSON kind it prints under ``--json`` (None for ``schema``,
    which prints a schema), what it opens first and the function that runs it.
    ``models`` says whether it reads model files (3D files that are not SOLIDWORKS
    documents), and ``model_kind`` the kind it prints for one when that differs."""

    name: str
    kind: str | None
    # "file": the FILE argument is opened read-only first; "folder"; "path": a path the command
    # opens itself (drawing), reported as source {"file"}; "none"
    target: str
    run: Callable[..., int]
    models: bool = False
    model_kind: str | None = None


COMMANDS: dict[str, Command] = {
    c.name: c
    for c in (
        Command("info", "document_summary", "file", cmd_info, True, "model_summary"),
        Command("props", "properties", "file", cmd_props, True),
        Command("configurations", "configurations", "file", cmd_configurations, True),
        Command("components", "components", "file", cmd_components),
        Command("references", "references", "file", cmd_references),
        Command("bom", "bom", "file", cmd_bom),
        Command("paths", "path_report", "file", cmd_paths),
        Command("streams", "streams", "file", cmd_streams),
        Command("dump", "file_written", "file", cmd_dump),
        Command("preview", "file_written", "file", cmd_preview, True),
        Command("parasolid", "parasolid_result", "file", cmd_parasolid),
        Command("export", "export_result", "file", cmd_export, True),
        Command("convert", "file_written", "file", cmd_convert, True),
        Command("sldprt", "sldprt_written", "path", cmd_sldprt),
        Command("list", "listing", "folder", cmd_list),
        Command("batch", "batch_summary", "folder", cmd_batch),
        Command("index", "catalog_scan", "none", cmd_index),
        Command("where-used", "where_used", "none", cmd_where_used),
        Command("search", "catalog_search", "none", cmd_search),
        Command("duplicates", "duplicates", "none", cmd_duplicates),
        Command("missing", "missing_references", "none", cmd_missing),
        Command("changes", "catalog_changes", "none", cmd_changes),
        Command("catalog", "catalog", "none", cmd_catalog),
        Command("catalogs", "catalog_list", "none", cmd_catalogs),
        Command("clear-index", "catalog_cleared", "none", cmd_clear_index),
        Command("serve", "serve_started", "none", cmd_serve),
        Command("mcp", None, "none", cmd_mcp),  # speaks MCP on standard output: no envelope
        Command("drawing", "drawing_result", "path", cmd_drawing),
        Command("history", "file_history", "path", cmd_history),
        Command("snapshot", "snapshot_taken", "path", cmd_snapshot),
        Command("diff", "version_diff", "path", cmd_diff),
        Command("version", "version", "none", cmd_version),
        Command("schema", None, "none", cmd_schema),
        Command("openapi", "file_written", "none", cmd_openapi),
    )
}


# --------------------------------------------------------------------------- parser
class UsageError(Exception):
    """A command line argparse refused; ``usage`` is the usage text."""

    def __init__(self, message: str, usage: str) -> None:
        super().__init__(message)
        self.usage = usage


class HelpRequested(Exception):
    """``-h`` or ``--help`` was given; ``text`` is the help argparse would print."""

    def __init__(self, text: str) -> None:
        super().__init__("help was requested")
        self.text = text


class VersionRequested(Exception):
    """``--version`` was given."""


class _Parser(argparse.ArgumentParser):
    """An ArgumentParser whose errors, help and version requests come back to
    :func:`main` as exceptions, so that under ``--json`` they print JSON too."""

    def error(self, message: str):  # type: ignore[override]
        raise UsageError(message, self.format_usage().strip())

    def print_help(self, file=None) -> None:  # what -h and --help call before exiting
        raise HelpRequested(self.format_help())


class _VersionAction(argparse.Action):
    def __init__(self, option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS, help=None):
        super().__init__(option_strings=option_strings, dest=dest, default=default, nargs=0, help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        raise VersionRequested()


def _positive_int(text: str) -> int:
    if not text.isascii() or not text.isdigit() or text.startswith("0"):
        raise argparse.ArgumentTypeError(f"expected a positive whole number, not {text!r}")
    return int(text)


def _port(text: str) -> int:
    leading_zero = len(text) > 1 and text.startswith("0")
    if not text.isascii() or not text.isdigit() or leading_zero or int(text) > 65535:
        raise argparse.ArgumentTypeError(f"expected a port from 0 to 65535, not {text!r}")
    return int(text)


def _positive_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a number of seconds, not {text!r}") from None
    if not value > 0 or value == float("inf"):
        raise argparse.ArgumentTypeError(f"expected a positive number of seconds, not {text!r}")
    return value


def _chord_mm(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a chord tolerance in millimetres, not {text!r}") from None
    if not 0.0001 <= value <= 10.0:
        raise argparse.ArgumentTypeError(f"expected a chord tolerance from 0.0001 to 10 mm, not {text!r}")
    return value


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(
        prog="solidseas",
        description="Read SOLIDWORKS files without SOLIDWORKS (read-only).",
        epilog=DISCLAIMER,
    )
    p.add_argument("--version", action=_VersionAction, help="print the version and exit")
    p.add_argument("--json", action="store_true", default=False, help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="command", required=True, metavar="command")

    def add(
        name: str, help_: str, *, target: str, json_help: str | None = None, models: bool = False
    ) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_, description=help_)
        if target == "file" and models:
            sp.add_argument(
                "file",
                help="a .sldprt, .sldasm or .slddrw file, or another 3D file SolidSeas reads such as "
                ".stl (opened read-only)",
            )
        elif target == "file":
            sp.add_argument("file", help="a .sldprt, .sldasm or .slddrw file (opened read-only)")
        elif target == "folder":
            sp.add_argument("folder", help="the folder to read (never written to)")
        sp.add_argument(
            "--json",
            action="store_true",
            default=argparse.SUPPRESS,
            help=json_help or "print one JSON document on standard output and nothing on standard error",
        )
        return sp

    def add_examined(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--max-examined",
            type=_positive_int,
            default=DEFAULT_MAX_EXAMINED,
            help=f"stop after the walk has looked at this many directory entries, documents or not "
            f"(default {DEFAULT_MAX_EXAMINED:,})",
        )

    def add_worker_flags(sp: argparse.ArgumentParser, file_timeout: float) -> None:
        sp.add_argument(
            "--file-timeout",
            type=_positive_float,
            default=None,
            metavar="SECONDS",
            help=f"give up on a document after this many seconds: its worker process is stopped "
            f"and replaced, and the document is reported as failed (default {file_timeout:g})",
        )
        sp.add_argument(
            "--memory-mb",
            type=_positive_int,
            default=None,
            metavar="N",
            help=f"memory cap of each worker process in MiB; a document that needs more is reported "
            f"as failed (default {WORKER_MEMORY_MB})",
        )
        sp.add_argument(
            "--in-process",
            action="store_true",
            help="read the documents in this process instead of worker processes: about 0.3 s quicker "
            "to start, but a file that hangs, crashes or exhausts memory stops the whole run",
        )

    def add_write_flags(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--force", action="store_true", help="overwrite existing output files")
        sp.add_argument(
            "--allow-source-dir",
            action="store_true",
            help="allow writing into (or below) the folder that holds the source",
        )

    def add_assembly_parasolid_flags(sp: argparse.ArgumentParser, configuration_help: str) -> None:
        sp.add_argument("--configuration", help=configuration_help)
        sp.add_argument(
            "--allow-partial",
            action="store_true",
            help="an assembly: leave out the components that cannot be written, and say which, "
            "rather than write nothing",
        )
        sp.add_argument(
            "--other-configurations",
            action="store_true",
            help="an assembly: for a part that does not store the bodies of the configuration "
            "a component uses, write the bodies it does store, with a warning",
        )
        sp.add_argument(
            "--include-hidden",
            action="store_true",
            help="an assembly: also write the bodies SOLIDWORKS hides",
        )

    def add_max_mb(sp: argparse.ArgumentParser, what: str) -> None:
        sp.add_argument(
            "--max-mb",
            type=_positive_float,
            default=DEFAULT_MAX_TRANSMIT_BYTES / (1 << 20),
            metavar="MB",
            help=f"{what} (default {DEFAULT_MAX_TRANSMIT_BYTES >> 20})",
        )

    def add_nested(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--nested",
            metavar="STREAM",
            default=None,
            help="read the nested document in this stream instead (a virtual or imported "
            "component's nested name, as components and references list it)",
        )

    sp = add(
        "info",
        "format, saving version, document type, configurations, preview and counts",
        target="file",
        models=True,
    )
    add_nested(sp)
    add_max_mb(sp, "a Parasolid transmit file larger than this many MiB is refused")
    sp = add(
        "props",
        "custom properties as JSON: effective (default), file or one configuration",
        target="file",
        models=True,
    )
    add_nested(sp)
    sp.add_argument("--configuration", help="configuration name (default: the active configuration)")
    sp.add_argument(
        "--view",
        choices=model.PROPERTY_VIEWS,
        default="effective",
        help="effective: file properties with the configuration's own on top (default); "
        "file: file properties only; configuration: the configuration's own only",
    )
    add("configurations", "configurations with their materials and properties", target="file", models=True)
    sp = add("components", "the component tree of one assembly configuration", target="file")
    sp.add_argument("--configuration", help="configuration name (default: the active configuration)")
    sp.add_argument(
        "--max-nodes",
        type=_positive_int,
        default=DEFAULT_MAX_NODES,
        help=f"stop after this many instances (default {DEFAULT_MAX_NODES:,}, at most {MAX_NODES_LIMIT:,})",
    )
    sp.add_argument(
        "--max-depth",
        type=_positive_int,
        default=DEFAULT_MAX_DEPTH,
        help=f"deepest level of sub-assemblies to expand (default {DEFAULT_MAX_DEPTH}, "
        f"at most {MAX_DEPTH_LIMIT})",
    )
    sp.add_argument(
        "--flat", action="store_true", help="list every instance with its parent instead of nesting"
    )
    sp = add(
        "references",
        "every referenced file across all configurations; a drawing's models and sheets",
        target="file",
    )
    sp.add_argument(
        "--configuration", help="configuration whose instance counts to give (default: the active one)"
    )
    sp.add_argument(
        "--resolve",
        action="store_true",
        help="find each referenced file on this machine (default root: the document's folder)",
    )
    sp.add_argument(
        "--root",
        action="append",
        metavar="ID=DIR",
        help="a project folder to search, recursively; repeat for more, searched in order",
    )
    sp.add_argument(
        "--library",
        action="append",
        metavar="ID=DIR",
        help="a library folder to search after the project roots; repeat for more",
    )
    sp.add_argument(
        "--path-map",
        action="append",
        metavar="FROM=TO",
        help="read a stored path starting FROM (a drive or \\\\host\\share prefix) as starting TO here",
    )
    sp.add_argument(
        "--no-outside-roots",
        action="store_true",
        help="never look up a single path outside the roots, as the REST service never does",
    )
    sp = add(
        "bom",
        "the bill of materials of one assembly configuration, grouped and numbered as SOLIDWORKS BOM "
        "tables; each component file is found as references --resolve finds it",
        target="file",
    )
    sp.add_argument("--configuration", help="configuration name (default: the active configuration)")
    sp.add_argument(
        "--type",
        choices=bom_mod.BOM_TYPES,
        default=bom_mod.DEFAULT_TYPE,
        help="top: top-level only (default, as in SOLIDWORKS); parts: parts only; "
        "indented: each sub-assembly followed by its components",
    )
    sp.add_argument(
        "--format",
        choices=BOM_FORMATS,
        default=None,
        help="table (default), csv or json (the bom envelope); under --json, standard output takes json "
        "and another format needs -o",
    )
    sp.add_argument(
        "-o",
        "--output",
        default=None,
        help="write the BOM in --format to this file (CSV: UTF-8 with a byte order mark); refused in "
        "the folder of the assembly, of a --root or --library, or of a component file read outside them",
    )
    sp.add_argument(
        "--column",
        action="append",
        metavar="PROPERTY",
        help="add a column with this custom property, read like DESCRIPTION; repeat for more",
    )
    sp.add_argument(
        "--part-number-property",
        metavar="PROPERTY",
        default=None,
        help="take PART NUMBER from this property (the configuration's, then the file's) instead of "
        "the document name, where a file has it",
    )
    sp.add_argument(
        "--root",
        action="append",
        metavar="ID=DIR",
        help="a project folder to search for the component files (default: the assembly's folder); "
        "repeat for more",
    )
    sp.add_argument(
        "--library",
        action="append",
        metavar="ID=DIR",
        help="a library folder to search after the project roots; repeat for more",
    )
    sp.add_argument(
        "--path-map",
        action="append",
        metavar="FROM=TO",
        help="read a stored path starting FROM (a drive or \\\\host\\share prefix) as starting TO here",
    )
    sp.add_argument(
        "--no-outside-roots",
        action="store_true",
        help="never look up a single path outside the roots, as the REST service never does",
    )
    add_write_flags(sp)
    add(
        "paths",
        "every path and user name the file (and each nested document) would reveal to whoever "
        "receives it; SolidSeas never rewrites files",
        target="file",
    )
    add("streams", "list the streams inside the document, with sizes", target="file")
    sp = add("dump", "write one stream, decompressed, to a file", target="file")
    sp.add_argument("stream", help="stream name as listed by the streams command")
    sp.add_argument("-o", "--output", required=True, help="output file")
    sp.add_argument("--raw", action="store_true", help="write the stored bytes without decompressing")
    add_write_flags(sp)
    sp = add(
        "preview",
        "save the embedded preview image (PNG or BMP); for another 3D file, the one it stores, else one "
        "rendered from its model",
        target="file",
        models=True,
    )
    sp.add_argument("-o", "--output", required=True, help="output file (.png or .bmp) or an existing folder")
    sp.add_argument(
        "--prefer",
        choices=("png", "dib"),
        default="png",
        help="png: the 640 x 480 PNG (default); dib: the larger 256-colour bitmap",
    )
    sp.add_argument(
        "--render",
        action="store_true",
        help="another 3D file: always render the preview from its model, even when it stores one",
    )
    sp.add_argument(
        "--stored",
        action="store_true",
        help="another 3D file: only the image it stores; never render one",
    )
    add_nested(sp)
    add_max_mb(sp, "a Parasolid transmit file larger than this many MiB is refused")
    add_write_flags(sp)
    sp = add(
        "parasolid",
        "write a part's Parasolid bodies as .x_b (and .x_t) files, per configuration, or an "
        "assembly's placed parts as one .x_b (and .x_t) file",
        target="file",
    )
    sp.add_argument("-o", "--output", required=True, help="output folder")
    sp.add_argument("--text", action="store_true", help="also write text .x_t files")
    add_assembly_parasolid_flags(sp, "an assembly: configuration name (default: the active configuration)")
    sp.add_argument(
        "--raw", action="store_true", help="also write the raw partition (.p_b) and deltas (.d_b)"
    )
    sp.add_argument(
        "--local-bodies",
        choices=("fallback", "always", "never"),
        default="fallback",
        help="use Config-<n>-FeatureBodies/LocalBodies when a partition is empty (default)",
    )
    sp.add_argument(
        "--max-mb",
        type=float,
        default=DEFAULT_MAX_TRANSMIT_BYTES / (1 << 20),
        help="skip transmits larger than this many MiB (parsing needs about 6x in memory)",
    )
    add_write_flags(sp)
    sp = add(
        "export",
        "write a part or an assembly, or another 3D file, as 3MF or binary STL for 3D printing, or a "
        "part as STEP (AP214), "
        "in millimetres",
        target="file",
        models=True,
    )
    add_max_mb(sp, "a Parasolid transmit file larger than this many MiB is refused")
    sp.add_argument("--format", required=True, choices=EXPORT_FORMATS, help="3mf, step or stl")
    sp.add_argument(
        "-o",
        "--output",
        default=None,
        help="output file ending in .3mf, .stl, .step or .stp, or a folder that exists, for the document's "
        "name with the format's extension (default: that name in the current folder)",
    )
    sp.add_argument("--configuration", help="configuration name (default: the active configuration)")
    sp.add_argument(
        "--chord",
        type=_chord_mm,
        default=None,
        metavar="MM",
        help="chord tolerance in millimetres, the furthest a triangle may lie from the surface "
        "(default: a quarter of the 3D view's, at most 0.01 mm)",
    )
    sp.add_argument(
        "--merge", action="store_true", help="3MF: one object of every placed triangle, not one per component"
    )
    sp.add_argument("--sheets", action="store_true", help="STEP: write sheet (surface) bodies too")
    sp.add_argument(
        "--allow-partial",
        action="store_true",
        help="STEP: leave out, whole, the bodies that cannot be written without loss (exit 4), rather than "
        "write nothing",
    )
    sp.add_argument(
        "--exact-only",
        action="store_true",
        help="STEP: refuse geometry that would have to be approximated, rather than approximate it",
    )
    sp.add_argument(
        "--include-hidden",
        action="store_true",
        help="STEP: write the bodies SOLIDWORKS hides too (its own STEP leaves them out, and so does this "
        "by default)",
    )
    sp.add_argument(
        "--check",
        action="store_true",
        help="STEP: read the file back with Open CASCADE (the OCCT backend extension) and say whether it "
        "holds what was written, closed and valid (exit 1 when it does not)",
    )
    add_write_flags(sp)
    sp = add(
        "convert",
        "write an IGES, BREP or STEP file, a SOLIDWORKS part or assembly or a Parasolid file as IGES, "
        "BREP or STEP through the OCCT backend extension (Open CASCADE), in millimetres",
        target="file",
        models=True,
    )
    add_max_mb(sp, "a Parasolid transmit file larger than this many MiB is refused")
    sp.add_argument("--format", required=True, choices=("iges", "brep", "step"), help="iges, brep or step")
    sp.add_argument(
        "-o",
        "--output",
        default=None,
        help="output file ending in .igs, .iges, .brep, .step or .stp, or a folder that exists, for the "
        "document's name with the format's extension (default: that name in the current folder)",
    )
    add_write_flags(sp)
    sp = add(
        "sldprt",
        "write a SOLIDWORKS part from a SolidCraft design, a SolidSeas IR file or a CadQuery recording, "
        "without SOLIDWORKS (provisional)",
        target="none",
    )
    sp.add_argument(
        "path",
        metavar="DESIGN",
        help="a .solidcraft file, or a .json file with a SolidSeas IR document or a CadQuery recording "
        "(never changed)",
    )
    sp.add_argument(
        "-o",
        "--output",
        default=None,
        help="a new file ending in .sldprt, or a folder that exists, for the design's name with .SLDPRT "
        "(default: that name in the current folder); a file already there is never replaced",
    )
    sp.add_argument(
        "--allow-partial",
        action="store_true",
        help="leave out what a part cannot hold yet, and list it (exit 4), rather than write nothing",
    )
    sp.add_argument(
        "--property",
        action="append",
        metavar="NAME=VALUE",
        help="give the part a text file property, such as PartNo=SS-1001, replacing one of that name "
        "the design has (repeat for more)",
    )
    sp.add_argument(
        "--allow-source-dir",
        action="store_true",
        help="allow writing into (or below) the folder that holds the design",
    )
    sp = add(
        "list",
        "list the SOLIDWORKS documents in a folder, reading only what each entry needs",
        target="folder",
    )
    sp.add_argument("--recursive", action="store_true", help="walk subfolders too (links are never followed)")
    sp.add_argument(
        "--formats",
        default=registry.SOLIDWORKS,
        metavar="IDS",
        help="which files to list: solidworks (default), all, or comma-separated format ids such as "
        "stl,3mf,step; formats SolidSeas cannot read yet are listed as unsupported",
    )
    sp.add_argument(
        "--include", default="", help="comma-separated extras per entry: properties, configurations"
    )
    sp.add_argument(
        "--preview",
        choices=tuple(_PREVIEW_INCLUDE),
        default="meta",
        help="none; meta: what each preview is (default); inline: the image too, base64, up to 8 MiB in all",
    )
    sp.add_argument("--max-depth", type=_positive_int, default=32, help="deepest folder level (default 32)")
    sp.add_argument(
        "--limit",
        type=_positive_int,
        default=None,
        help="stop after this many entries (checked between entries; the walk still looks "
        "for one more entry, up to --max-examined)",
    )
    add_examined(sp)
    sp.add_argument(
        "--timeout",
        type=_positive_float,
        default=None,
        help="start no new entry after this many seconds (checked between entries: a slow file "
        "or a share that stops answering runs past it)",
    )
    add_worker_flags(sp, LIST_FILE_TIMEOUT_S)
    sp = add(
        "batch",
        "run info, preview and parasolid over a folder into an output folder, with a CSV report",
        target="folder",
    )
    sp.add_argument("-o", "--output", required=True, help="output folder (outside the scanned folder)")
    sp.add_argument("--no-recurse", action="store_true", help="do not descend into subfolders")
    sp.add_argument("--no-preview", action="store_true", help="skip preview images")
    sp.add_argument("--no-parasolid", action="store_true", help="skip Parasolid extraction")
    sp.add_argument("--text", action="store_true", help="also write text .x_t files")
    add_assembly_parasolid_flags(
        sp,
        "an assembly: the configuration to write (default: each assembly's active configuration); "
        "an assembly without it gets an error row",
    )
    sp.add_argument(
        "--max-mb",
        type=float,
        default=DEFAULT_MAX_TRANSMIT_BYTES / (1 << 20),
        help="skip Parasolid transmits larger than this many MiB",
    )
    sp.add_argument(
        "--jobs", type=_positive_int, default=1, help="worker processes reading documents at once (default 1)"
    )
    add_worker_flags(sp, BATCH_FILE_TIMEOUT_S)
    add_examined(sp)
    add_write_flags(sp)
    sp = add(
        "serve",
        "run the read-only REST service over the given roots (loopback, bearer token)",
        target="none",
        json_help="print the ready line as one compact JSON document; the log still goes to standard error",
    )
    sp.add_argument(
        "--config",
        default=None,
        metavar="FILE",
        help="read these settings from a TOML file; an option given here replaces the file's setting",
    )
    sp.add_argument(
        "--root", action="append", metavar="ID=DIR", help="a folder to serve, recursively; repeat for more"
    )
    sp.add_argument(
        "--library", action="append", metavar="ID=DIR", help="a library folder, searched after the roots"
    )
    sp.add_argument("--port", type=_port, default=None, help="TCP port (default 8765; 0 picks a free one)")
    sp.add_argument(
        "--bind",
        default=None,
        help="address to listen on (default 127.0.0.1; anything but loopback needs --allow-remote)",
    )
    sp.add_argument(
        "--token-file",
        default=None,
        help="the bearer-token file (name:token lines), created on first start readable by you alone; "
        "its folder must exist",
    )
    sp.add_argument(
        "--identity-key-file",
        default=None,
        metavar="PATH",
        help="the service's own secret for /v1/identity (default: beside the token file, under its name "
        "with .identity added), created on first start readable by you alone; its folder must exist",
    )
    sp.add_argument(
        "--allow-remote",
        action="store_true",
        default=None,
        help="allow a non-loopback --bind, over plain HTTP: only on a private network",
    )
    sp.add_argument(
        "--allowed-host",
        action="append",
        metavar="NAME",
        help="a Host header name clients use for a remote bind; repeat for more",
    )
    sp.add_argument(
        "--identity-address",
        action="append",
        metavar="ADDRESS:PORT",
        help="an address clients call that forwards to the service, such as a published container port: "
        "/v1/identity proves for it when the Host header names it; repeat for more",
    )
    sp.add_argument(
        "--allow-origin",
        action="append",
        metavar="ORIGIN",
        help="a web page's origin (https://intranet.example) that may call the service from a browser "
        "with a token (CORS); repeat for more",
    )
    sp.add_argument(
        "--workers", type=_positive_int, default=None, help="worker processes (default: up to 4, one per CPU)"
    )
    sp.add_argument(
        "--catalog",
        action="store_true",
        default=None,
        help="keep a catalog of the roots in your cache folder and answer /v1/catalog, /v1/where-used "
        "and /v1/search from it",
    )
    sp.add_argument(
        "--catalog-rescan",
        type=_positive_float,
        default=None,
        metavar="SECONDS",
        help="scan the roots for the catalog again after this many seconds (default 300)",
    )
    sp.add_argument(
        "--formats",
        default=None,
        metavar="IDS",
        help="which files the service reads: solidworks (default), all, or comma-separated format ids "
        "such as stl,3mf",
    )
    sp.add_argument(
        "--viewer",
        action="store_true",
        default=None,
        help="serve the reference web viewer at /viewer/ (provisional): the file list, a part or assembly in "
        "3D and the BOM, in a browser on this machine",
    )
    sp = add(
        "mcp",
        "let an MCP app (Claude Desktop, Claude Code...) read the files under the given roots, over "
        "standard input and output, read-only",
        target="none",
        json_help="changes nothing: standard output carries the protocol alone",
    )
    sp.add_argument(
        "--root", action="append", metavar="ID=DIR", help="a folder to read, recursively; repeat for more"
    )
    sp.add_argument(
        "--library", action="append", metavar="ID=DIR", help="a library folder, searched after the roots"
    )
    sp.add_argument(
        "--workers", type=_positive_int, default=None, help="worker processes reading documents (default 2)"
    )
    sp.add_argument(
        "--catalog",
        action="store_true",
        help="keep a catalog of the roots in your cache folder and offer search, where_used, duplicates, "
        "missing_references and recent_changes",
    )
    def add_catalog_choice(sp: argparse.ArgumentParser) -> None:
        g = sp.add_mutually_exclusive_group()
        g.add_argument("--catalog", metavar="NAME", help="the catalog of that name in the cache folder")
        g.add_argument("--db", metavar="FILE", help="the catalog database at FILE")
        g.add_argument(
            "--in-project",
            action="store_true",
            help="the catalog in the project's .solidseas folder (Windows; elsewhere use --db)",
        )

    def add_page(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--limit", type=_positive_int, default=100, help="results per page, 1 to 500 (default 100)"
        )
        sp.add_argument("--cursor", default=None, help="the next_cursor of the previous page")

    sp = add(
        "index",
        "build or update the catalog of one or more folders (in your cache folder unless told otherwise)",
        target="none",
    )
    sp.add_argument("folders", nargs="*", metavar="FOLDER", help="a project folder (never written to)")
    sp.add_argument("--root", action="append", metavar="ID=DIR", help="a project folder with its own root id")
    sp.add_argument(
        "--library",
        action="append",
        metavar="DIR",
        help="a library folder, searched after the projects (or ID=DIR)",
    )
    add_catalog_choice(sp)
    sp.add_argument(
        "--hash",
        choices=("all", "duplicates", "none"),
        default=None,
        help="which files get a SHA-256: all, only those whose size another shares, or none "
        "(default: all on a local drive, duplicates on a share)",
    )
    sp.add_argument("--no-previews", action="store_true", help="keep no preview images in the catalog")
    sp.add_argument(
        "--verify",
        action="store_true",
        help="hash every file that looks unchanged again, and read again one whose bytes differ",
    )
    sp.add_argument(
        "--formats",
        default=None,
        metavar="IDS",
        help="which files the catalog indexes from now on: solidworks (a new catalog's default), all (every "
        "format SolidSeas reads) or comma-separated format ids such as step,stl; files of a format left "
        "out are removed from it (default: as the catalog was told last)",
    )
    sp.add_argument(
        "--part-number-property",
        metavar="NAME",
        default=None,
        help="take each configuration's part number from this property (an empty name goes back to the "
        "document name)",
    )
    sp.add_argument(
        "--workers", type=_positive_int, default=2, help="worker processes reading documents (default 2)"
    )
    sp.add_argument(
        "--file-timeout",
        type=_positive_float,
        default=30.0,
        metavar="SECONDS",
        help="give up on a document after this many seconds (default 30)",
    )
    sp.add_argument(
        "--timeout",
        type=_positive_float,
        default=None,
        metavar="SECONDS",
        help="stop after this many seconds; the next index carries on where this one stopped",
    )
    sp = add(
        "where-used",
        "the assemblies and drawings that use a part or a sub-assembly, from the catalog",
        target="none",
    )
    sp.add_argument("file", help="the file, below a folder that was indexed (it is not opened)")
    sp.add_argument("--configuration", default=None, help="only uses of this configuration of the file")
    sp.add_argument("--direct", action="store_true", help="only the documents that use it themselves")
    sp.add_argument(
        "--max-depth", type=_positive_int, default=32, help="how many levels of assemblies up (default 32)"
    )
    add_catalog_choice(sp)
    sp = add("search", "find documents by name, part number, description or any property", target="none")
    sp.add_argument(
        "text",
        nargs="+",
        help="words (each a prefix) and filters such as type:part, pn:, desc:, prop:Name=value, "
        "folder:sub/path, root:ID and changed:7d; an argument with spaces is a phrase, or the whole "
        'value of a filter ("desc:steel bracket")',
    )
    sp.add_argument(
        "--sort", choices=("relevance", "name", "modified"), default="relevance", help="order of the results"
    )
    add_page(sp)
    add_catalog_choice(sp)
    sp = add("duplicates", "files with identical contents, by SHA-256", target="none")
    sp.add_argument("--names", action="store_true", help="also files that share a name but differ in content")
    add_page(sp)
    add_catalog_choice(sp)
    sp = add(
        "missing",
        "references that resolve to no file in the indexed folders, ambiguous or low-confidence ones",
        target="none",
    )
    add_page(sp)
    add_catalog_choice(sp)
    sp = add("changes", "files added, changed, moved and removed, newest first", target="none")
    sp.add_argument("--since", default=None, help="7d, 12h, 2w or a date such as 2026-09-01")
    add_page(sp)
    add_catalog_choice(sp)
    sp = add("catalog", "the state of a folder's catalog: its roots, counts and last scan", target="none")
    sp.add_argument("folder", nargs="?", help="the indexed folder (default: the current folder)")
    add_catalog_choice(sp)
    add("catalogs", "every catalog in your cache folder, with its roots and last scan", target="none")
    sp = add(
        "clear-index", "delete a folder's catalog (the files themselves are never touched)", target="none"
    )
    sp.add_argument("folder", nargs="?", help="the indexed folder (default: the current folder)")
    sp.add_argument("--all", action="store_true", help="delete every catalog in your cache folder")
    add_catalog_choice(sp)
    sp = add(
        "drawing",
        "make, export, update and check drawings of parts (provisional; never signs or releases)",
        target="none",
    )
    actions = sp.add_subparsers(dest="action", required=True, metavar="action")

    def action(name: str, help_: str) -> argparse.ArgumentParser:
        ap = actions.add_parser(name, help=help_, description=help_)
        ap.add_argument(
            "--json",
            action="store_true",
            default=argparse.SUPPRESS,
            help="print one drawing_result JSON document on standard output and nothing on standard error",
        )
        return ap

    def settings_flag(ap: argparse.ArgumentParser) -> None:
        ap.add_argument(
            "--settings",
            metavar="FILE",
            default=None,
            help="read Drawing Settings from FILE instead of your own (never written)",
        )

    ap = action("new", "make a PRELIMINARY drawing of a part: always the .ssdrw, the PDF and DXF on request")
    ap.add_argument(
        "path",
        metavar="PART",
        help="a SOLIDWORKS part or assembly, or a STEP, Parasolid or Alibre Design part (opened read-only)",
    )
    ap.add_argument("--configuration", metavar="C", default=None, help="the configuration to draw")
    ap.add_argument("--process", choices=("machined", "printed", "turned"), default="machined")
    ap.add_argument("--scheme", choices=("datum", "plusminus"), default=None, help="(default: the process's)")
    ap.add_argument(
        "--detail",
        choices=("simplified", "complex", "full"),
        default=None,
        help="how much the drawing says: the overall size and holes (simplified), every feature located "
        "(complex), or fully defined with datums and GD&T (full); default: Drawing Settings' default "
        "level, full unless changed",
    )
    ap.add_argument(
        "--units",
        choices=("part", "in", "mm"),
        default="part",
        help="the drawing's unit (default: the part's; a part that states none needs in or mm)",
    )
    ap.add_argument(
        "--views",
        default="auto",
        metavar="auto|LIST",
        help="auto, or views such as front,top,right,isometric",
    )
    ap.add_argument(
        "--front",
        choices=("auto", "+x", "-x", "+y", "-y", "+z", "-z"),
        default="auto",
        help="the direction the front view looks from (default: chosen)",
    )
    ap.add_argument(
        "--turn", type=int, choices=(0, 1, 2, 3), default=0, help="quarter turns of the front view"
    )
    ap.add_argument("--sheet", choices=("auto", "A", "B", "C", "D", "E"), default="auto")
    ap.add_argument("--scale", default="auto", metavar="auto|N:M", help="such as 1:2 (default: chosen)")
    ap.add_argument(
        "--isometric-sheet",
        action="store_true",
        help="draw the isometric on a sheet of its own after the first (with an assembly's balloons)",
    )
    for key, flag in TITLE_FLAGS:
        words = "drawn by (signs DRAWN with today's date)" if key == "drawn_by" else key.replace("_", " ")
        ap.add_argument(
            f"--{flag}", dest=key, default=None, metavar="TEXT", help=f"the title block's {words}"
        )
    ap.add_argument(
        "--confirm-threads",
        metavar="FILE",
        default=None,
        help='a JSON object of thread answers such as {"f-3": "M6 x 1", "f-5": null} (drawing check lists '
        "the candidates)",
    )
    settings_flag(ap)
    ap.add_argument("--out", metavar="DIR", required=True, help="the folder to write in (it must exist)")
    ap.add_argument("--pdf", action="store_true", help="also write the PDF")
    ap.add_argument("--dxf", action="store_true", help="also write the DXF")
    ap.add_argument(
        "--allow-source-dir", action="store_true", help="allow --out to be the part's folder or below it"
    )
    ap = action("export", "write a drawing's PDF and DXF from its sheet (both when neither is named)")
    ap.add_argument("path", metavar="DRAWING", help="a .ssdrw file (never changed)")
    ap.add_argument("--pdf", action="store_true", help="write the PDF")
    ap.add_argument("--dxf", action="store_true", help="write the DXF")
    ap.add_argument("--out", metavar="DIR", required=True, help="the folder to write in (it must exist)")
    ap.add_argument(
        "--allow-source-dir", action="store_true", help="allow --out to be the drawing's folder or below it"
    )
    ap = action("update", "update a drawing from its model, keeping your edits; refuses a released drawing")
    ap.add_argument(
        "path", metavar="DRAWING", help="a .ssdrw file, written over only if unchanged since read"
    )
    ap.add_argument(
        "--model", metavar="PART", default=None, help="the model (default: found from the drawing)"
    )
    ap.add_argument("--dry-run", action="store_true", help="report what would change and write nothing")
    ap = action("check", "the checklist and thread candidates of a drawing, or of a part's drawing")
    ap.add_argument(
        "path",
        metavar="DRAWING_OR_PART",
        help="a .ssdrw file, or a part as drawing new takes (never changed)",
    )
    ap.add_argument("--strict", action="store_true", help="warnings fail too (exit 4)")
    ap.add_argument(
        "--model",
        metavar="PART",
        default=None,
        help="verify a model file against the drawing's MODEL reference",
    )
    settings_flag(ap)
    ap = action("show", "a drawing's summary, status, signatures and revisions")
    ap.add_argument("path", metavar="DRAWING", help="a .ssdrw file (never changed)")
    ap = action("settings", "the effective Drawing Settings and every value that fell back to its default")
    settings_flag(ap)

    def add_store_choice(sp: argparse.ArgumentParser) -> None:
        where = sp.add_mutually_exclusive_group()
        where.add_argument(
            "--project",
            metavar="DIR",
            default=None,
            help="use the snapshot store of this project folder (DIR/.solidseas/history), which must "
            "hold the file",
        )
        where.add_argument(
            "--store",
            metavar="DIR",
            default=None,
            help="use the snapshot store in this folder instead of yours",
        )

    def add_source(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--source",
            dest="history_source",  # args.source is the envelope's
            choices=("auto", "git", "snapshots"),
            default="auto",
            help="where the history comes from: git inside a repository and snapshots elsewhere (auto, the "
            "default), or the one named",
        )

    sp = add(
        "history",
        "the versions of a file: from Git inside a repository, else from its snapshots",
        target="none",
    )
    sp.add_argument("path", metavar="FILE", help="the file (opened read-only)")
    add_source(sp)
    add_store_choice(sp)
    sp.add_argument(
        "--max-commits",
        type=_positive_int,
        default=20_000,
        metavar="N",
        help="stop looking through Git's history after this many commits (default 20,000)",
    )
    sp.add_argument(
        "--hashes", action="store_true", help="also give the SHA-256 of every Git version (reads each one)"
    )
    sp = add(
        "snapshot",
        "keep a copy of a file as it is now in your snapshot store, never beside the file unless "
        "--project names its project",
        target="none",
    )
    sp.add_argument("path", metavar="FILE", help="the file (opened read-only)")
    add_store_choice(sp)
    sp.add_argument("--note", metavar="TEXT", default=None, help="a note kept with the snapshot")
    sp = add(
        "diff",
        "what changed between two versions of a file: its properties, configurations, document and geometry",
        target="none",
    )
    sp.add_argument("path", metavar="FILE", help="the file (opened read-only)")
    sp.add_argument(
        "older",
        nargs="?",
        metavar="OLDER",
        help="a version: working, latest, vN or an id from solidseas history (default: the version "
        "before NEWER)",
    )
    sp.add_argument("newer", nargs="?", metavar="NEWER", help="a version (default: the newest one)")
    add_source(sp)
    add_store_choice(sp)
    sp.add_argument(
        "--no-measures",
        action="store_true",
        help="compare changed geometry by its counts alone, without measuring volume, area and size",
    )
    sp.add_argument(
        "--timeout",
        type=_positive_float,
        default=60.0,
        metavar="SECONDS",
        help="time for measuring the geometry of both versions (default 60)",
    )
    add("version", "the SolidSeas version, API version and each JSON kind's schema version", target="none")
    sp = add("schema", "print the JSON Schema of a kind's envelope, or list the kinds", target="none")
    sp.add_argument("kind", nargs="?", help="a JSON kind, such as document_summary or listing")
    sp.add_argument("--data", action="store_true", help="the schema of data alone, without the envelope")
    sp = add(
        "openapi",
        "print the OpenAPI 3.0.3 description of the REST service's routes (provisional)",
        target="none",
    )
    sp.add_argument("-o", "--output", default=None, help="write it to this file instead")
    sp.add_argument("--force", action="store_true", help="overwrite the -o file if it exists")
    return p


def _open_file(args: argparse.Namespace):
    """The FILE argument opened read-only: a SOLIDWORKS document exactly as
    ``open_document`` opens it, any other 3D file SolidSeas reads as a model document
    (:func:`solidseas.formats.open_any`), with ``--max-mb`` as its transmit bound."""
    limits = None
    max_mb = getattr(args, "max_mb", None)
    if max_mb is not None and getattr(args, "command", None) != "parasolid":
        limits = Limits().replace(xt_transmit_bytes=max(1, int(max_mb * (1 << 20))))
    return open_any(args.file, limits=limits)


def _source(cmd: Command, args: argparse.Namespace) -> dict[str, Any] | None:
    if cmd.target == "file":
        nested = getattr(args, "nested", None)
        return {"file": args.file} if nested is None else {"file": args.file, "nested": nested}
    if cmd.target == "folder":
        return {"folder": args.folder}
    if cmd.target == "path" and getattr(args, "path", None) is not None:
        return {"file": args.path}
    return None


def main(argv: list[str] | None = None) -> int:
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:  # pythonw.exe, or a task started without a console
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    argv = list(sys.argv[1:] if argv is None else argv)
    json_mode = "--json" in argv
    try:
        args = build_parser().parse_args(argv)
    except UsageError as exc:
        err = InvalidArgumentError(str(exc), detail={"usage": exc.usage})
        if json_mode:
            _print_json(model.error_envelope(err))
        else:
            sys.stderr.write(f"{exc.usage}\nsolidseas: {exc}\n")
        return EXIT_USAGE
    except HelpRequested as exc:
        if not json_mode:
            sys.stdout.write(exc.text)
            return EXIT_OK
        # Help is text; under --json it is an invalid_argument error that carries the text.
        err = InvalidArgumentError("--help prints text, not JSON", detail={"usage": exc.text.strip()})
        _print_json(model.error_envelope(err))
        return EXIT_USAGE
    except VersionRequested:
        if json_mode:
            _print_json(model.envelope("version", model.build_version()))
        else:
            _say(f"solidseas {__version__}")
        return EXIT_OK
    args.json = bool(getattr(args, "json", False)) or json_mode
    cmd = COMMANDS[args.command]
    args.source = _source(cmd, args)
    try:
        if cmd.target == "file":
            with _open_file(args) as doc:
                if isinstance(doc, ModelDocument) and not cmd.models:
                    raise UnsupportedOperationError(
                        f"{cmd.name} reads SOLIDWORKS documents, not {doc.format_name} files",
                        detail={"rule": "model_file", "value": doc.format},
                    )
                return cmd.run(args, doc)
        return cmd.run(args)
    except (Exception, KeyboardInterrupt) as exc:  # every failure becomes one error document
        return _failure(args.json, exc, args.source)
