"""One definition of every JSON shape SolidSeas emits, used by every surface.

The Python API (``Document.summary()`` and friends), the CLI's ``--json``
output and the REST service all build their data here and encode it with
:func:`dumps`. A surface adds only the envelope's ``source``; ``data`` is
identical everywhere. ``docs/API.md`` documents each kind.

* :data:`KINDS` registers every kind: its schema version, its JSON Schema
  (2020-12), its builder, and the CLI command and REST route that serve it.
* :data:`ERROR_CODES` maps every error code to its fixed message, its HTTP
  status, its CLI exit code and whether a retry can help.
* :func:`dumps` is the only JSON encoder. It is strict: NaN, infinity,
  integers beyond 2**53 - 1, bytes and unknown types are refused, never
  guessed at. Builders send such values as null with a warning, or as strings
  where the schema says so (``mtime_ns``).
* :func:`envelope`, :func:`error_envelope` and :func:`error_info` wrap data and
  turn any exception into the one error object.

Builders return plain JSON data (dicts, lists, str, int, float, bool, None),
already passed through the encoder's rules, so what Python callers get is
exactly what a JSON client parses.
"""

import base64
import datetime
import hashlib
import json
import math
import os
import re
from collections import Counter
from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Any

from . import __version__
from .errors import (
    WARNING_CODES,
    InvalidArgumentError,
    ReaderWarning,
    SldFormatError,
    SolidSeasError,
    WorkerJobError,
)
from .formats.base import ModelDocument
from .formats.solidworks.components import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_NODES,
    _check_limits,
    component_tree,
    reference_set,
)
from .formats.solidworks.document import FileInfo
from .formats.solidworks.metadata import PROPERTY_TYPES, calendar_day
from .formats.solidworks.parasolid import partition_streams
from .formats.solidworks.pathreport import (
    CATEGORIES,
    DEFAULT_MAX_DOCUMENTS,
    DEFAULT_MAX_PATHS,
    DEFAULT_MAX_TOTAL_BYTES,
    REWRITE_NOTE,
    ROLES,
)
from .formats.solidworks.paths import DEFAULT_MAX_SCAN_BYTES

API_VERSION = 1
MAX_SAFE_INTEGER = 2**53 - 1  # the largest integer every JSON parser, JavaScript included, keeps exact
_MAX_DEPTH = 256


# --------------------------------------------------------------------------- strict encoding
_SURROGATE = re.compile("[\ud800-\udfff]")


def clean_text(s: str) -> str:
    """``s`` with every lone surrogate replaced by U+FFFD (a valid pair is joined into
    one character), so the text is valid Unicode on every surface."""
    if _SURROGATE.search(s) is None:
        return s
    return s.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


def iso8601(dt: datetime.datetime) -> str:
    """ISO 8601 text. An aware datetime is converted to UTC and ends in ``Z``; a naive
    one has no offset, which means "local time of the saving machine, zone unknown".
    Seconds, milliseconds or microseconds, whichever keeps the value exact."""
    suffix = ""
    if dt.tzinfo is not None and dt.utcoffset() is not None:
        try:
            dt = dt.replace(tzinfo=None) - dt.utcoffset()
            suffix = "Z"
        except OverflowError:  # an offset that pushes year 1 or 9999 out of range: keep the offset
            return dt.isoformat()
    if dt.microsecond == 0:
        spec = "seconds"
    elif dt.microsecond % 1000 == 0:
        spec = "milliseconds"
    else:
        spec = "microseconds"
    return dt.isoformat(timespec=spec) + suffix


def to_json_data(value: Any, _depth: int = 0) -> Any:
    """``value`` as plain JSON data under the encoding rules in ``docs/API.md``.

    Accepts dict (str keys), list, tuple (as a list), set (as a sorted list), str
    (lone surrogates replaced), int within 2**53 - 1, finite float, bool, None
    and datetime (as ISO 8601 text). Exact types only, so a subclass such as a
    :class:`~solidseas.errors.ReaderWarning` must be converted by its builder.
    Raises ``TypeError`` for any other type and ``ValueError`` for NaN, infinity
    or an integer beyond 2**53 - 1.
    """
    if _depth > _MAX_DEPTH:
        raise ValueError(f"data nested deeper than {_MAX_DEPTH} levels")
    t = type(value)
    if value is None or t is bool:
        return value
    if t is int:
        if -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            return value
        raise ValueError("an integer beyond 2**53 - 1 must be sent as a string or as null with a warning")
    if t is float:
        if math.isfinite(value):
            return value
        raise ValueError("NaN and infinity are not JSON; send null with a warning")
    if t is str:
        return clean_text(value)
    if t is dict:
        out: dict[str, Any] = {}
        for k, v in value.items():
            if type(k) is not str:
                raise TypeError(f"JSON object keys must be str, not {type(k).__name__}")
            key = clean_text(k)
            if key in out:
                raise ValueError("two keys are equal once lone surrogates are replaced")
            out[key] = to_json_data(v, _depth + 1)
        return out
    if t is list or t is tuple:
        return [to_json_data(v, _depth + 1) for v in value]
    if t is set or t is frozenset:
        return [to_json_data(v, _depth + 1) for v in sorted(value)]
    if t is datetime.datetime:
        return iso8601(value)
    raise TypeError(f"{t.__name__} is not JSON data; the builder must convert it")


def dumps(value: Any, *, pretty: bool = False) -> str:
    """The one JSON encoder: strict, ASCII-only, keys in builder order.

    ``pretty=True`` indents by 2 (CLI ``--json``); otherwise the output is compact
    (``--jsonl`` and REST). See :func:`to_json_data` for what is refused.
    """
    data = to_json_data(value)
    if pretty:
        return json.dumps(data, indent=2, ensure_ascii=True, allow_nan=False)
    return json.dumps(data, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def loads(data: bytes | str, *, parameter: str = "data", max_depth: int = 32) -> Any:
    """Strict JSON in, the counterpart of :func:`dumps` for files a caller hands SolidSeas
    (``drawing new --confirm-threads``): UTF-8 text, no key twice in one object, no NaN
    or infinity, no number too large to be finite, at most ``max_depth`` levels deep.
    Anything else raises ``InvalidArgumentError`` naming ``parameter``."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in items:
            if k in out:
                raise ValueError(f"the key {k[:40]!r} appears twice")
            out[k] = v
        return out

    def constant(name: str) -> Any:
        raise ValueError(f"{name} is not a number JSON allows")

    def depth(value: Any, level: int) -> None:
        if level > max_depth:
            raise ValueError(f"it is nested more than {max_depth} levels deep")
        if isinstance(value, dict):
            for v in value.values():
                depth(v, level + 1)
        elif isinstance(value, list):
            for v in value:
                depth(v, level + 1)
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError("it holds a number too large to be finite")

    try:
        text = data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else data
        if text.startswith("\ufeff"):
            raise ValueError("it starts with a byte order mark")
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
        depth(value, 0)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise InvalidArgumentError(
            f"{parameter}: not strict JSON ({exc})", detail={"parameter": parameter}
        ) from None
    return value


# --------------------------------------------------------------------------- error codes
@dataclass(frozen=True)
class ErrorCode:
    """What one error code means on each surface."""

    code: str
    http_status: int | None  # None: the code never comes from the REST service
    cli_exit: int | None  # None: the code never comes from the CLI
    retryable: bool
    message: str  # fixed text, identical on every surface


def _codes(*rows: ErrorCode) -> dict[str, ErrorCode]:
    return {r.code: r for r in rows}


ERROR_CODES: dict[str, ErrorCode] = _codes(
    ErrorCode("invalid_argument", 400, 2, False, "An argument is missing or not valid."),
    ErrorCode("unknown_parameter", 400, 2, False, "The request has a parameter this route does not accept."),
    ErrorCode("duplicate_parameter", 400, 2, False, "A request parameter appears more than once."),
    ErrorCode("unauthorized", 401, None, False, "A valid bearer token is required."),
    ErrorCode(
        "forbidden_host", 403, None, False, "The Host header names a host this service does not serve."
    ),
    ErrorCode("forbidden_origin", 403, None, False, "Cross-site browser requests are refused."),
    ErrorCode("path_refused", 403, 3, False, "The path was refused by a safety rule."),
    ErrorCode(
        "link_refused", 403, 3, False, "The path goes through a link or junction, which is never followed."
    ),
    ErrorCode("feature_disabled", 403, 3, False, "This feature is switched off in the configuration."),
    ErrorCode("permission_denied", 403, 1, False, "The operating system denied access to the file."),
    ErrorCode("output_refused", None, 3, False, "The output location was refused by a write guard."),
    ErrorCode(
        "bind_refused", None, 3, False, "The service refuses that address without the remote-access settings."
    ),
    ErrorCode(
        "token_file_refused", None, 3, False, "The service's token file is missing, unsafe or malformed."
    ),
    ErrorCode(
        "identity_key_refused",
        None,
        3,
        False,
        "The service's identity key file cannot be created, or is unsafe or malformed.",
    ),
    ErrorCode(
        "address_unavailable",
        None,
        1,
        False,
        "The service could not listen there: the port is in use or the address is not this machine's.",
    ),
    ErrorCode("not_found", 404, 1, False, "The file or folder does not exist."),
    ErrorCode("root_not_found", 404, None, False, "No root has that id."),
    ErrorCode("not_in_catalog", 404, 1, False, "The file is not in the catalog: index its folder first."),
    ErrorCode("configuration_not_found", 404, 1, False, "The document has no configuration by that name."),
    ErrorCode("stream_not_found", 404, 1, False, "The document has no stream by that name."),
    ErrorCode("no_preview", 404, 1, False, "The document stores no preview image."),
    ErrorCode("nothing_to_export", None, 1, False, "The document holds no geometry that can be exported."),
    ErrorCode(
        "not_representable",
        None,
        1,
        False,
        "The geometry cannot be written to this format without loss; nothing was written.",
    ),
    ErrorCode("method_not_allowed", 405, None, False, "Only GET and HEAD are accepted."),
    ErrorCode("uri_too_long", 414, None, False, "The request URL is too long."),
    ErrorCode(
        "placeholder_file",
        409,
        1,
        False,
        "The file is a cloud placeholder whose data is not on this machine.",
    ),
    ErrorCode(
        "catalog_incompatible",
        409,
        3,
        False,
        "The database is not a SolidSeas catalog, a newer SolidSeas wrote it, or it is damaged.",
    ),
    ErrorCode("unknown_format", 422, 1, False, "The file is not a SOLIDWORKS document."),
    ErrorCode(
        "format_not_supported",
        422,
        1,
        False,
        "SolidSeas cannot read this file's format, or a feature this file uses.",
    ),
    ErrorCode("damaged_file", 422, 1, False, "The file is damaged or is not a complete SOLIDWORKS document."),
    ErrorCode("limit_exceeded", 422, 1, False, "The document exceeds a safety limit."),
    ErrorCode("file_too_large", 422, 1, False, "The file is larger than the configured maximum."),
    ErrorCode("response_too_large", 422, None, False, "The response would exceed its size limit."),
    ErrorCode("quarantined", 422, None, False, "The file stopped a worker repeatedly and is set aside."),
    ErrorCode("locked", 423, 1, True, "Another program holds the file locked. Try again shortly."),
    ErrorCode("too_many_failures", 429, None, True, "Too many failed authentication attempts."),
    ErrorCode("headers_too_large", 431, None, False, "The request headers are too large or too many."),
    ErrorCode("internal", 500, 1, False, "An internal error occurred."),
    ErrorCode("worker_crashed", 500, 1, False, "The worker reading the file stopped unexpectedly."),
    ErrorCode("not_implemented", 501, 1, False, "This operation is not implemented yet."),
    ErrorCode("busy", 503, 1, True, "The service is busy. Try again shortly."),
    ErrorCode("root_unavailable", 503, 1, True, "The root folder is not available right now."),
    ErrorCode("timeout", 504, 1, False, "Reading the file did not finish in time."),
    ErrorCode("interrupted", None, 130, False, "The command was interrupted."),
    # Drawings (docs/DRAWINGS.md 14), provisional: the command line only, no REST route yet.
    ErrorCode(
        "drawing_invalid", None, 1, False, "The drawing file is not a SolidSeas drawing this version reads."
    ),
    ErrorCode("drawing_too_complex", None, 1, False, "The part or the drawing is beyond a drawing's limits."),
    ErrorCode(
        "model_not_found", None, 1, False, "The drawing's model was not found, or the file found has changed."
    ),
    ErrorCode(
        "drawing_released", None, 3, False, "The drawing is released: start a revision before changing it."
    ),
    # Versions (docs/VERSIONS.md), provisional: the library and the command line, no REST route yet.
    ErrorCode("version_not_found", 404, 1, False, "The file has no version by that name."),
    ErrorCode("version_unavailable", 409, 1, False, "That version's content is not on this machine."),
)

# The only keys `detail` may carry: structured facts that are safe on every surface.
DETAIL_KEYS = ("stream", "parameter", "rule", "component_index", "limit", "value", "usage")

# Where a code covers cases a client would read differently, the message of a few rules
# (detail["rule"]) says which case it is; every other error has its code's message.
RULE_MESSAGES: dict[tuple[str, str], str] = {
    ("not_found", "route"): "The service has no route at that address.",
    ("invalid_argument", "not_a_folder"): "The path names a file, not a folder.",
    ("busy", "no_workers"): "No worker process is running. Try again shortly.",
    ("busy", "catalog_locked"): "Another process is updating the catalog. Try again shortly.",
    ("busy", "catalog_scanning"): "The catalog's first scan is still running. Try again shortly.",
    (
        "catalog_incompatible",
        "not_a_catalog",
    ): "The database is not a SolidSeas catalog; it was left as it is.",
    (
        "catalog_incompatible",
        "too_new",
    ): "A newer SolidSeas wrote this catalog: update SolidSeas or clear it.",
    (
        "catalog_incompatible",
        "damaged",
    ): "The catalog is damaged: clear it (solidseas clear-index) and index the folder again.",
    ("busy", "no_free_worker"): "No worker was free to read the file in time. It is read at the next scan.",
    (
        "format_not_supported",
        "no_reader",
    ): "SolidSeas recognises this file's format but cannot read it yet.",
    (
        "format_not_supported",
        "needs_extension",
    ): "SolidSeas reads this file's format through an extension that is not added or not switched on.",
    (
        "format_not_supported",
        "format_not_enabled",
    ): "The file holds a format this service or listing was not set to read, whatever its name says.",
    ("not_implemented", "model_file"): "This operation is not available for this file's format yet.",
    # versions (docs/VERSIONS.md)
    ("damaged_file", "git_object"): "The Git repository's objects or references are damaged.",
    ("damaged_file", "snapshot_object"): "A stored snapshot is damaged: its content does not match its hash.",
    (
        "format_not_supported",
        "reftable",
    ): "The Git repository keeps its references in the reftable format, which SolidSeas does not read yet.",
    (
        "format_not_supported",
        "repository_extension",
    ): "The Git repository uses a format or extension SolidSeas does not read.",
    (
        "format_not_supported",
        "pack_index_version",
    ): "The Git repository has a pack index SolidSeas does not read.",
    (
        "version_unavailable",
        "lfs_object_missing",
    ): "That version is stored with Git LFS and its content was not fetched to this machine.",
    (
        "version_unavailable",
        "object_missing",
    ): "That version is not in this clone of the repository (a shallow or partial clone).",
    ("version_unavailable", "snapshot_missing"): "That snapshot's stored copy is no longer in the store.",
    ("version_unavailable", "deleted"): "That commit deleted the file: the version has no content.",
    ("busy", "file_changing"): "The file changed while it was read. Try again once it is saved.",
}


_EXCEPTION_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,99}\Z")


def error_code(exc: BaseException) -> str:
    """The error code for any exception (``internal`` when nothing more specific fits)."""
    if isinstance(exc, SolidSeasError):
        return exc.code if exc.code in ERROR_CODES else "internal"
    if isinstance(exc, KeyboardInterrupt):
        return "interrupted"
    if isinstance(exc, (FileNotFoundError, NotADirectoryError, IsADirectoryError)):
        return "not_found"
    if isinstance(exc, PermissionError):
        return "permission_denied"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, NotImplementedError):
        return "not_implemented"
    return "internal"


def _safe_detail(detail: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not isinstance(detail, dict):
        return out
    for key in DETAIL_KEYS:
        v = detail.get(key)
        if v is None:
            continue
        if type(v) is int and abs(v) > MAX_SAFE_INTEGER:
            v = str(v)
        if type(v) in (str, int, bool):
            out[key] = v
    return out


def error_info(exc: BaseException, *, reader_message: bool = True) -> dict[str, Any]:
    """The error object for any exception: ``code``, the fixed ``message`` of that code
    (or of its rule, :data:`RULE_MESSAGES`), the ``exception`` class name,
    ``retryable``, ``detail`` and ``reader_message``.

    ``reader_message`` is the exception's own text. It can hold an absolute path,
    so the REST service passes ``reader_message=False`` and sends null.
    """
    code = error_code(exc)
    spec = ERROR_CODES[code]
    raw_detail = exc.info.get("detail") if isinstance(exc, WorkerJobError) else getattr(exc, "detail", None)
    rule = raw_detail.get("rule") if isinstance(raw_detail, dict) else None
    message = RULE_MESSAGES.get((code, rule), spec.message) if isinstance(rule, str) else spec.message
    if isinstance(exc, WorkerJobError):
        # The error object a worker process sent back: keep its code, class name, safe detail
        # and text; the message and retryable come from the code, as for any exception.
        name = exc.info.get("exception")
        text = exc.info.get("reader_message")
        info = {
            "code": code,
            "message": message,
            "exception": name if isinstance(name, str) and _EXCEPTION_NAME.match(name) else "Exception",
            "retryable": spec.retryable,
            "detail": _safe_detail(exc.info.get("detail")),
            "reader_message": text if reader_message and isinstance(text, str) else None,
        }
        return to_json_data(info)
    info = {
        "code": code,
        "message": message,
        "exception": type(exc).__name__,
        "retryable": spec.retryable,
        "detail": _safe_detail(getattr(exc, "detail", None) if isinstance(exc, SolidSeasError) else None),
        "reader_message": str(exc) if reader_message else None,
    }
    return to_json_data(info)


def envelope(kind: str, data: Any, *, source: dict[str, Any] | None = None) -> dict[str, Any]:
    """The document every surface sends: ``ok``, ``kind``, ``schema_version``,
    ``solidseas`` (the version), ``source`` and ``data``. ``source`` is None from
    Python, ``{"file"}`` from the CLI and ``{"root", "path"}`` from REST."""
    spec = KINDS[kind]
    return {
        "ok": True,
        "kind": kind,
        "schema_version": spec.schema_version,
        "solidseas": __version__,
        "source": source,
        "data": data,
    }


def error_envelope(
    exc: BaseException, *, source: dict[str, Any] | None = None, reader_message: bool = True
) -> dict[str, Any]:
    """The error document: like :func:`envelope` with ``ok: false``, kind ``error`` and
    ``error`` in place of ``data``."""
    return {
        "ok": False,
        "kind": "error",
        "schema_version": KINDS["error"].schema_version,
        "solidseas": __version__,
        "source": source,
        "error": error_info(exc, reader_message=reader_message),
    }


# --------------------------------------------------------------------------- sub-builders
class _Warnings:
    """Collects the warnings a builder adds while it converts values."""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, code: str, message: str, stream: str | None = None) -> None:
        self.items.append({"code": code, "stream": stream, "message": message})

    def extend_reader(self, warnings: list[ReaderWarning]) -> None:
        for w in warnings:
            if not isinstance(w, ReaderWarning):  # every reader site emits coded warnings
                raise TypeError(f"reader warning without a code: {type(w).__name__}")
            self.items.append(w.to_dict())


def _safe_int(v: Any, what: str, warn: _Warnings) -> int | None:
    if type(v) is not int:
        return None
    if abs(v) > MAX_SAFE_INTEGER:
        warn.add("value_not_representable", f"{what}: an integer beyond 2**53 - 1 was sent as null")
        return None
    return v


def _text(v: Any) -> str | None:
    if v is None or isinstance(v, (bytes, bytearray)):
        return None
    return v if isinstance(v, str) else str(v)


def file_object(name: str | None, size: int | None, mtime_ns: int | None) -> dict[str, Any]:
    """``file``: name, size, modification time (ISO 8601) and ``mtime_ns`` as a string
    (it exceeds 2**53). Any of them may be null."""
    modified = FileInfo.from_stat(size or 0, mtime_ns).modified_utc if type(mtime_ns) is int else None
    return {
        "name": name,
        "size": size if type(size) is int and 0 <= size <= MAX_SAFE_INTEGER else None,
        "modified_utc": iso8601(modified) if modified is not None else None,
        "mtime_ns": str(mtime_ns) if type(mtime_ns) is int else None,
    }


def file_data(doc) -> dict[str, Any]:
    """``file`` for an open document, from ``fstat`` on its handle; null fields for bytes."""
    fi = doc.file_info
    if fi is None:
        return file_object(doc.name, None, None)
    return file_object(doc.name, fi.size, fi.mtime_ns)


def saved_version_data(doc, warn: _Warnings) -> dict[str, Any]:
    sv = doc.saved_version
    return {
        "format_version": _safe_int(sv.format_version, "saved_version.format_version", warn),
        "release": sv.release,
        "release_verified": bool(sv.release_verified),
        "last_build": _safe_int(sv.last_build, "saved_version.last_build", warn),
        "last_build_date": sv.last_build_date,
        "save_as_previous": bool(sv.save_as_previous),
    }


def material_data(name: Any, database: Any) -> dict[str, Any] | None:
    name = _text(name)
    if not name:
        return None
    return {"name": name, "database": _text(database)}


def _unit(v: Any, what: str, warn: _Warnings) -> str | int | None:
    if isinstance(v, str):
        return v
    return _safe_int(v, what, warn)


def units_data(doc, warn: _Warnings) -> dict[str, Any] | None:
    u = doc.units
    if not u:
        return None
    return {
        "system": _unit(u.get("system"), "units.system", warn),
        "length": _unit(u.get("length"), "units.length", warn),
        "mass": _unit(u.get("mass"), "units.mass", warn),
        "angle": _unit(u.get("angle"), "units.angle", warn),
        "length_decimal_places": _safe_int(
            u.get("length_decimal_places"), "units.length_decimal_places", warn
        ),
    }


def fields_data(doc) -> dict[str, Any]:
    f = doc.fields
    return {
        "title": f.title,
        "subject": f.subject,
        "author": f.author,
        "keywords": f.keywords,
        "comments": f.comments,
        "last_saved_by": f.last_saved_by,
        "created_utc": iso8601(f.created_utc) if f.created_utc else None,
        "last_saved_utc": iso8601(f.last_saved_utc) if f.last_saved_utc else None,
    }


_NO_PREVIEW = {"mime": None, "width": None, "height": None, "bytes": None, "stream": None, "sha256": None}


def preview_and_bytes(doc, warn: _Warnings) -> tuple[dict[str, Any], bytes | None]:
    """The ``preview`` object and the image bytes it describes (None when there are none)."""
    try:
        pv = doc.preview()
    except SldFormatError as exc:
        warn.add("preview_undecodable", f"no preview stream could be decoded: {exc}")
        return {"available": False, "reason": "undecodable", **_NO_PREVIEW}, None
    if pv is None:
        return {"available": False, "reason": "not_stored", **_NO_PREVIEW}, None
    obj = {
        "available": True,
        "reason": None,
        "mime": pv.mime,
        "width": pv.width,
        "height": pv.height,
        "bytes": len(pv.data),
        "stream": pv.stream,
        "sha256": hashlib.sha256(pv.data).hexdigest(),
    }
    return obj, pv.data


def preview_data(doc, warn: _Warnings) -> dict[str, Any]:
    """``preview``: what the stored preview image is, without its bytes.

    ``available`` is false with ``reason`` ``"not_stored"`` when the file stores
    none (about a third of real parts), or ``"undecodable"`` with a warning when
    preview streams exist but none decodes."""
    return preview_and_bytes(doc, warn)[0]


def property_data(p, warn: _Warnings) -> dict[str, Any]:
    """One property: name, scope, configuration, type token, JSON value, stored text,
    expression and linked. A number JSON cannot carry exactly becomes null with a
    warning; ``text`` still holds what the file stores."""
    ptype = p.type if p.type in PROPERTY_TYPES else "other"
    v = p.value
    value: Any = None
    if ptype == "text":
        value = _text(v)
    elif ptype == "number":
        if type(v) is int:
            if abs(v) > MAX_SAFE_INTEGER:
                warn.add(
                    "value_not_representable",
                    f"property {p.name!r}: an integer beyond 2**53 - 1 was sent as null; "
                    "text keeps the digits",
                )
            else:
                value = v
        elif type(v) is float:
            if math.isfinite(v):
                value = v
            else:
                warn.add("non_finite_number", f"property {p.name!r}: {v!r} was sent as null")
    elif ptype == "boolean":
        value = v if type(v) is bool else None
    elif ptype == "date":
        value = iso8601(v) if isinstance(v, datetime.datetime) else None
    day = calendar_day(v) if ptype == "date" else None
    scope = getattr(p, "scope", "file")
    return {
        "name": p.name,
        "scope": scope if scope in ("file", "configuration") else "file",
        "configuration": getattr(p, "configuration", None),
        "type": ptype,
        "value": value,
        "date": day.isoformat() if day is not None else None,
        "text": _text(p.text),
        "expression": _text(p.expression),
        "linked": bool(p.linked),
    }


def configuration_data(c, warn: _Warnings) -> dict[str, Any]:
    return {
        "name": c.name,
        "id": _safe_int(c.id, f"configuration {c.name!r} id", warn),
        "active": bool(c.active),
        "most_recent": c.most_recent,
        "comment": _text(c.comment),
        "material": material_data(c.material, c.material_database),
        "material_assigned": c.material_assigned,
        "properties": [property_data(p, warn) for p in c.properties],
    }


def counts_data(doc) -> dict[str, Any]:
    return {
        "streams": doc.stream_count,
        "configurations": len(doc.configurations),
        "custom_properties": len(doc.properties),
        "references": len(doc.references()) if doc.doc_type in ("assembly", "drawing") else None,
        "nested_documents": len(doc.nested_documents()),
        "parasolid_partitions": len(partition_streams(doc.container)),
    }


# --------------------------------------------------------------------------- kind builders
SUMMARY_PARTS = ("properties", "configurations")
PROPERTY_VIEWS = ("file", "configuration", "effective")


def build_document_summary(
    doc, *, include: Collection[str] = SUMMARY_PARTS, nested: str | None = None
) -> dict[str, Any]:
    """``document_summary`` data. ``include`` names the optional parts; a part left
    out is null. ``properties`` holds the file-level properties; configuration
    properties are inside each configuration. ``nested`` names a nested document
    (a virtual or imported component's stream) to describe instead."""
    if nested is not None:
        doc = doc.nested(nested)
    if isinstance(include, str):
        include = (include,)
    unknown = [p for p in include if p not in SUMMARY_PARTS]
    if unknown:
        raise InvalidArgumentError(
            f"include accepts {', '.join(SUMMARY_PARTS)}", detail={"parameter": "include"}
        )
    warn = _Warnings()
    data: dict[str, Any] = {
        "file": file_data(doc),
        "format": doc.format,
        "doc_type": doc.doc_type,
        "doc_type_source": doc.doc_type_source,
        "saved_version": saved_version_data(doc, warn),
        "active_configuration": doc.active_configuration,
        "configurations": (
            [configuration_data(c, warn) for c in doc.configurations] if "configurations" in include else None
        ),
        "properties": [property_data(p, warn) for p in doc.properties] if "properties" in include else None,
        "material": material_data(doc.material, doc.metadata.material_database),
        "units": units_data(doc, warn),
        "fields": fields_data(doc),
        "preview": preview_data(doc, warn),
        "counts": counts_data(doc),
    }
    reader = _Warnings()
    reader.extend_reader(doc.warnings)
    data["warnings"] = reader.items + warn.items
    return to_json_data(data)


def build_properties(
    doc, *, view: str = "effective", configuration: str | None = None, nested: str | None = None
) -> dict[str, Any]:
    """``properties`` data for one view.

    * ``file``: the file-level properties only (``configuration`` must be None).
    * ``configuration``: that configuration's own properties only.
    * ``effective``: file-level properties overridden by the configuration's.

    ``configuration=None`` means the active configuration. An unknown name
    raises :class:`~solidseas.errors.ConfigurationNotFoundError`. ``nested`` names a
    nested document whose properties to give instead.
    """
    if isinstance(doc, ModelDocument):
        return build_model_properties(doc, view=view, configuration=configuration, nested=nested)
    if nested is not None:
        doc = doc.nested(nested)
    if view not in PROPERTY_VIEWS:
        raise InvalidArgumentError(
            f"view must be one of {', '.join(PROPERTY_VIEWS)}", detail={"parameter": "view"}
        )
    warn = _Warnings()
    if view == "file":
        if configuration is not None:
            raise InvalidArgumentError(
                "the file view takes no configuration", detail={"parameter": "configuration"}
            )
        cfg_name, props = None, doc.properties
    else:
        cfg = doc.configuration(configuration)
        cfg_name = cfg.name if cfg is not None else None
        if view == "configuration":
            props = cfg.properties if cfg is not None else []
        else:
            props = doc.effective_properties(cfg_name)
    data = {
        "view": view,
        "configuration": cfg_name,
        "properties": [property_data(p, warn) for p in props],
        "warnings": warn.items,
    }
    return to_json_data(data)


def build_configurations(doc) -> dict[str, Any]:
    """``configurations`` data: the active configuration's name and every configuration.
    A model file has none: its list is empty (``active_configuration`` is the one an
    Alibre Design file names)."""
    warn = _Warnings()
    data = {
        "active_configuration": doc.active_configuration,
        "configurations": [configuration_data(c, warn) for c in doc.configurations],
        "warnings": warn.items,
    }
    return to_json_data(data)


# --------------------------------------------------------------------------- model files
MODEL_SUMMARY_PARTS = ("properties", "tree", "references")
MODEL_SUMMARY_DEFAULT = ("properties", "tree")


def _model_check(doc, nested: str | None) -> None:
    if nested is not None:
        raise InvalidArgumentError(
            "nested documents belong to SOLIDWORKS assemblies", detail={"parameter": "nested"}
        )


def _model_configuration(doc, configuration: str | None) -> None:
    from .errors import ConfigurationNotFoundError

    if configuration is not None and configuration != doc.active_configuration:
        raise ConfigurationNotFoundError(f"the file has no configuration named {configuration!r}")


def build_model_properties(
    doc, *, view: str = "effective", configuration: str | None = None, nested: str | None = None
) -> dict[str, Any]:
    """``properties`` data of a model file: its file-scope properties for the ``file``
    and ``effective`` views, none for ``configuration`` (a model file keeps its
    properties for the whole file)."""
    _model_check(doc, nested)
    if view not in PROPERTY_VIEWS:
        raise InvalidArgumentError(
            f"view must be one of {', '.join(PROPERTY_VIEWS)}", detail={"parameter": "view"}
        )
    if view == "file" and configuration is not None:
        raise InvalidArgumentError(
            "the file view takes no configuration", detail={"parameter": "configuration"}
        )
    _model_configuration(doc, configuration)
    warn = _Warnings()
    props = [] if view == "configuration" else doc.properties
    data = {
        "view": view,
        "configuration": doc.active_configuration if view != "file" else None,
        "properties": [property_data(p, warn) for p in props],
        "warnings": warn.items,
    }
    return to_json_data(data)


def model_units_data(doc) -> dict[str, Any]:
    u = doc.units or {}
    scale = u.get("scale_m")
    return {
        "length": _text(u.get("length")),
        "scale_m": scale if type(scale) in (int, float) and math.isfinite(scale) else None,
        "source": _text(u.get("source")),
    }


def model_application_data(doc) -> dict[str, Any]:
    a = doc.application or {}
    return {"name": _text(a.get("name")), "version": _text(a.get("version"))}


def model_counts_data(doc, warn: _Warnings) -> dict[str, Any]:
    from .formats.base import HEAD_COUNTS

    got = doc.counts()
    return {k: _safe_int(got.get(k), f"counts.{k}", warn) for k in HEAD_COUNTS}


def _color(c: Any) -> list[float] | None:
    if c is None:
        return None
    out = [float(v) for v in c]
    return out if len(out) == 4 and all(math.isfinite(v) for v in out) else None


def model_node_data(n, warn: _Warnings | None = None) -> dict[str, Any]:
    """A model tree node. A placement that is not finite (a crafted transform) is sent
    as null, with the warning ``value_not_representable`` once in ``warn``."""
    placement = n.placement
    if placement is not None and not placement.is_finite():
        placement = None
        if warn is not None and not any(
            w["code"] == "value_not_representable" and w["stream"] == "tree" for w in warn.items
        ):
            warn.add("value_not_representable", "a placement in the tree is not finite; sent as null", "tree")
    return {
        "id": n.id,
        "parent": n.parent,
        "name": _text(n.name),
        "kind": n.kind,
        "object": n.object if type(n.object) is int else None,
        "file": _text(n.file),
        "placement": placement_data(placement),
        "color": _color(n.color),
    }


def model_reference_data(r) -> dict[str, Any]:
    res = r.resolution if isinstance(r.resolution, dict) else None
    return {
        "key": r.key,
        "kind": r.kind,
        "name": _text(r.name),
        "stored": _text(r.stored),
        "resolution": None
        if res is None
        else {
            "status": _text(res.get("status")),
            "path": _text(res.get("path")),
            "found_by": _text(res.get("found_by")),
            "version": _text(res.get("version")),
        },
    }


def _renderable(doc) -> bool:
    return doc.kind in ("mesh", "brep", "mixed")


def model_preview_data(doc, warn: _Warnings) -> dict[str, Any]:
    """``preview`` of a model file: what the image it stores is, as stored (``source``
    ``stored``), and whether a preview can be rendered from its geometry."""
    try:
        pv = doc.preview()
    except SldFormatError as exc:
        warn.add("preview_undecodable", f"the stored preview could not be read: {exc}")
        pv, reason = None, "undecodable"
    else:
        reason = "not_stored"
    if pv is None:
        return {
            "available": False,
            "reason": reason,
            "source": None,
            **_NO_PREVIEW,
            "renderable": _renderable(doc),
        }
    return {
        "available": True,
        "reason": None,
        "source": "stored",
        "mime": pv.mime,
        "width": pv.width,
        "height": pv.height,
        "bytes": len(pv.data),
        "stream": pv.stream,
        "sha256": hashlib.sha256(pv.data).hexdigest(),
        "renderable": _renderable(doc),
    }


def build_model_summary(doc, *, include: Collection[str] = MODEL_SUMMARY_DEFAULT) -> dict[str, Any]:
    """``model_summary`` data (v1, provisional; ``docs/API.md`` 5.16): one model file's
    format, variant, document type, units, application, fields, properties, header
    counts, tree, references and stored preview. ``include`` names the optional
    parts (``properties``, ``tree``, ``references``); a part left out is null."""
    if isinstance(include, str):
        include = (include,)
    unknown = [p for p in include if p not in MODEL_SUMMARY_PARTS]
    if unknown:
        raise InvalidArgumentError(
            f"include accepts {', '.join(MODEL_SUMMARY_PARTS)}", detail={"parameter": "include"}
        )
    warn = _Warnings()
    tree = doc.tree() if "tree" in include else None
    refs = doc.references() if "references" in include else None
    counts = model_counts_data(doc, warn)
    if refs is not None:
        counts["references"] = len(refs)
    data: dict[str, Any] = {
        "file": file_data(doc),
        "format": doc.format,
        "format_name": doc.format_name,
        "variant": doc.variant,
        "doc_type": doc.doc_type,
        "kind": doc.kind,
        "units": model_units_data(doc),
        "application": model_application_data(doc),
        "active_configuration": doc.active_configuration,
        "fields": fields_data(doc),
        "properties": [property_data(p, warn) for p in doc.properties] if "properties" in include else None,
        "counts": counts,
        "tree": None
        if tree is None
        else {"nodes": [model_node_data(n, warn) for n in tree.nodes], "truncated": bool(tree.truncated)},
        "references": None if refs is None else [model_reference_data(r) for r in refs],
        "preview": model_preview_data(doc, warn),
    }
    reader = _Warnings()
    reader.extend_reader(doc.warnings)
    data["warnings"] = reader.items + warn.items
    return to_json_data(data)


# --------------------------------------------------------------------------- components and references
def placement_data(p) -> dict[str, Any] | None:
    """``placement``: rotation (row by row) and translation in metres, or null."""
    if p is None:
        return None
    return {"rotation": [list(row) for row in p.rotation], "translation_m": list(p.translation_m)}


def transform_data(t) -> dict[str, Any] | None:
    """``transform``: the 16 stored numbers and what they decode to, or null."""
    if t is None:
        return None
    return {"stored": list(t.stored), **placement_data(t), "scale": t.scale}


def component_file_data(f) -> dict[str, Any]:
    """A component file: one referenced document, by its key (C7)."""
    per = f.per_configuration
    return {
        "key": f.key,
        "stored_path": f.stored_path,
        "file_name": f.file_name,
        "doc_type": f.doc_type,
        "direct": f.direct,
        "virtual": f.virtual,
        "imported": f.imported,
        "nested": f.nested,
        "embedded": f.embedded,
        "embedded_in_subassembly": f.embedded_in_subassembly,
        "configurations_used": list(f.configurations_used),
        "instances": f.instances,
        "instances_unsuppressed": f.instances_unsuppressed,
        "instances_in_bom": f.instances_in_bom,
        "per_configuration": None
        if per is None
        else [
            {
                "configuration": c.configuration,
                "instances": c.instances,
                "instances_unsuppressed": c.instances_unsuppressed,
                "instances_in_bom": c.instances_in_bom,
            }
            for c in per
        ],
        "sources": list(f.sources),
        "resolution": f.resolution,
    }


def component_node_data(n, *, flat: bool = False) -> dict[str, Any]:
    """One component instance; with ``flat`` its ``children`` is null."""
    return {
        "id": n.id,
        "parent": n.parent,
        "name": n.name,
        "component": n.component,
        "number": n.number,
        "depth": n.depth,
        "file": n.file,
        "doc_type": n.doc_type,
        "configuration": n.configuration,
        "suppressed": n.suppressed,
        "hidden": n.hidden,
        "excluded_from_bom": n.excluded_from_bom,
        "virtual": n.virtual,
        "transform": transform_data(n.transform),
        "placement": placement_data(n.placement),
        "children_state": n.children_state,
        "children": None if flat else [component_node_data(c) for c in n.children],
    }


def build_components(
    doc,
    *,
    configuration: str | None = None,
    max_nodes: int = DEFAULT_MAX_NODES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    flat: bool = False,
) -> dict[str, Any]:
    """``components`` data: the component tree of one assembly configuration.

    For a part or a drawing it is empty, with ``children_state`` ``"none"``.
    ``flat`` lists every instance in ``instances`` (depth first, each with its
    ``parent``) instead of nesting them in ``children``.
    """
    _check_limits(max_nodes, max_depth)
    if not isinstance(flat, bool):
        raise InvalidArgumentError("flat must be true or false", detail={"parameter": "flat"})
    limits = {"max_nodes": max_nodes, "max_depth": max_depth}
    if doc.doc_type != "assembly":
        if configuration is not None:
            doc.configuration(configuration)  # an unknown name is refused on every document type
        data: dict[str, Any] = {
            "configuration": None,
            "configuration_source": "none",
            "configurations_described": [],
            "children_state": "none",
            "truncated": False,
            "limits": limits,
            "counts": {"nodes": 0, "depth": 0, "files": 0},
            "files": [],
            "children": None if flat else [],
            "instances": [] if flat else None,
            "warnings": [],
        }
        return to_json_data(data)
    tree = component_tree(doc, configuration, max_nodes=max_nodes, max_depth=max_depth)
    data = {
        "configuration": tree.configuration,
        "configuration_source": tree.configuration_source,
        "configurations_described": list(tree.configurations_described),
        "children_state": tree.children_state,
        "truncated": tree.truncated,
        "limits": limits,
        "counts": {"nodes": tree.node_count, "depth": tree.depth, "files": len(tree.files)},
        "files": [component_file_data(f) for f in tree.files.values()],
        "children": None if flat else [component_node_data(n) for n in tree.children],
        "instances": [component_node_data(n, flat=True) for n in tree.walk()] if flat else None,
        "warnings": [w.to_dict() for w in tree.warnings],
    }
    return to_json_data(data)


def location_data(loc) -> dict[str, Any] | None:
    """A location (C1): ``{"root", "path"}``; ``root`` null for an absolute host path
    outside every root (CLI and Python only)."""
    if loc is None:
        return None
    return {"root": loc.root, "path": loc.path}


def resolution_result_data(r) -> dict[str, Any]:
    """One file's resolution result (``docs/API.md`` section 5.10)."""
    return {
        "key": r.key,
        "status": r.status,
        "stored_path": r.stored_path,
        "match": location_data(r.match),
        "rule": r.rule,
        "confidence": r.confidence,
        "identity": r.identity,
        "nested": r.nested,
        "candidates": [
            {
                "root": c.location.root,
                "path": c.location.path,
                "found_by": c.found_by,
                "identity": c.identity,
                "placeholder": c.placeholder,
            }
            for c in r.candidates
        ],
        "warnings": [w.to_dict() for w in r.warnings],
    }


def resolution_summary_data(res) -> dict[str, Any]:
    """The ``resolution`` object of the ``references`` kind: the roots searched, whether
    a limit cut an index short, and how many files have each status."""
    return {
        "roots": [
            {
                "id": s.id,
                "role": s.role,
                "recursive": s.recursive,
                "index_partial": s.index_partial,
                "truncated_reason": s.truncated_reason,
            }
            for s in res.roots
        ],
        "index_partial": res.index_partial,
        "outside_roots": res.allow_outside_roots,
        "truncated": res.truncated,
        "counts": res.counts(),
    }


def build_references(doc, *, configuration: str | None = None, resolution=None) -> dict[str, Any]:
    """``references`` data: every file the document references, across all its
    configurations, with the instance counts of ``configuration`` (None: the
    active one) and of each configuration the tree describes. A drawing lists its
    models (provisionally, from ``Header2``) and its sheets; a part lists nothing.

    ``resolution`` is a :class:`solidseas.resolve.Resolution` of this document
    (``solidseas.resolve.resolve_references``); with it each file carries its
    resolution result and ``resolution`` summarises the search. Without it both
    are null. :func:`attach_resolution` adds one to data built without it, as the
    REST service does after resolving in its own process (C10)."""
    if doc.doc_type != "assembly" and configuration is not None:
        doc.configuration(configuration)
    refs = reference_set(doc, configuration)
    files = [component_file_data(f) for f in refs.files.values()]
    data = {
        "configuration": refs.configuration,
        "configuration_source": refs.configuration_source,
        "configurations_described": list(refs.configurations_described),
        "children_state": refs.children_state,
        "truncated": refs.truncated,
        "files": files,
        "sheets": None
        if refs.sheets is None
        else [
            {
                "name": s.name,
                "views": [
                    {
                        "name": v.name,
                        "configuration": v.configuration,
                        "file_name": v.file_name,
                        "file": v.file,
                    }
                    for v in s.views
                ],
            }
            for s in refs.sheets
        ],
        "resolution": None,
        "warnings": [w.to_dict() for w in refs.warnings],
    }
    data = to_json_data(data)
    return attach_resolution(data, resolution) if resolution is not None else data


def attach_resolution(data: dict[str, Any], resolution) -> dict[str, Any]:
    """``references`` data with each file's resolution result and the summary filled in
    from ``resolution`` (a :class:`solidseas.resolve.Resolution`). ``data`` is built by
    :func:`build_references` without one; it is not changed."""
    results = resolution.results
    out = dict(data)
    files = []
    for item in data["files"]:
        r = results.get(item["key"])
        files.append({**item, "resolution": resolution_result_data(r) if r is not None else None})
    out["files"] = files
    out["resolution"] = resolution_summary_data(resolution)
    return to_json_data(out)


# --------------------------------------------------------------------------- bills of materials
def bom_row_data(r, warn: _Warnings) -> dict[str, Any]:
    """One BOM row (:class:`solidseas.bom.BomRow`)."""
    return {
        "item": r.item,
        "level": r.level,
        "parent": r.parent,
        "part_number": r.part_number,
        "part_number_source": r.part_number_source,
        "alternate_name": r.alternate_name,
        "description": r.description,
        "quantity": r.quantity,
        "total_quantity": r.total_quantity,
        "file": r.file,
        "file_name": r.file_name,
        "stored_path": r.stored_path,
        "doc_type": r.doc_type,
        "configuration": r.configuration,
        "virtual": r.virtual,
        "imported": r.imported,
        "instances": list(r.instances),
        "resolution": r.resolution,
        "location": location_data(r.location),
        "nested": list(r.nested),
        "properties": None if r.properties is None else [property_data(p, warn) for p in r.properties],
        "values": list(r.values),
        "notes": [w.to_dict() for w in r.notes],
    }


def bom_data(bom) -> dict[str, Any]:
    """``bom`` data from a :class:`solidseas.bom.Bom`."""
    from .bom import COLUMNS

    warn = _Warnings()
    rows = [bom_row_data(r, warn) for r in bom.rows]
    warn.extend_reader(list(bom.warnings))
    counts = {k: bom.counts[k] for k in ("rows", "instances", "files", "read", "unread", "files_opened")}
    data = {
        "type": bom.type,
        "configuration": bom.configuration,
        "configuration_source": bom.configuration_source,
        "children_state": bom.children_state,
        "columns": [*COLUMNS, *bom.columns],
        "property_columns": list(bom.columns),
        "part_number_property": bom.part_number_property,
        "read_properties": bom.read_properties,
        "rows": rows,
        "truncated": bom.truncated,
        "complete": bom.complete,
        "counts": counts,
        "limits": dict(bom.limits),
        "resolution": None if bom.resolution is None else resolution_summary_data(bom.resolution),
        "warnings": warn.items,
    }
    return to_json_data(data)


def build_bom(
    doc,
    *,
    configuration: str | None = None,
    bom_type: str | None = None,
    columns=(),
    part_number_property: str | None = None,
    **options: Any,
) -> dict[str, Any]:
    """``bom`` data: the bill of materials of one assembly configuration
    (:func:`solidseas.bom.build_bom`; ``options`` are its options, such as ``roots``
    and ``resolution``). For a part or a drawing it has no rows and
    ``children_state`` ``"none"``."""
    from . import bom as _bom

    kind = _bom.check_type(_bom.DEFAULT_TYPE if bom_type is None else bom_type)
    cols = _bom.check_columns(columns)
    bom = _bom.build_bom(
        doc,
        configuration,
        bom_type=kind,
        columns=cols,
        part_number_property=part_number_property,
        **options,
    )
    if bom is not None:
        return bom_data(bom)
    data: dict[str, Any] = {
        "type": kind,
        "configuration": None,
        "configuration_source": "none",
        "children_state": "none",
        "columns": [*_bom.COLUMNS, *cols],
        "property_columns": list(cols),
        "part_number_property": part_number_property,
        "read_properties": options.get("read_properties", True) is not False,
        "rows": [],
        "truncated": False,
        "complete": True,
        "counts": {"rows": 0, "instances": 0, "files": 0, "read": 0, "unread": 0, "files_opened": 0},
        "limits": None,
        "resolution": None,
        "warnings": [],
    }
    return to_json_data(data)


# --------------------------------------------------------------------------- path report
def _where(loc) -> dict[str, Any]:
    return {"nested": list(loc.nested), "stream": loc.stream}


def build_path_report(
    doc,
    *,
    max_stream_bytes: int = DEFAULT_MAX_SCAN_BYTES,
    max_paths: int = DEFAULT_MAX_PATHS,
    max_documents: int = DEFAULT_MAX_DOCUMENTS,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> dict[str, Any]:
    """``path_report`` data: the paths and names the document (and every nested
    document in it) would reveal to whoever receives it, with where each was found.
    SolidSeas never rewrites files; ``rewrite`` says so."""
    rep = doc.path_report(
        max_stream_bytes=max_stream_bytes,
        max_paths=max_paths,
        max_documents=max_documents,
        max_total_bytes=max_total_bytes,
    )
    data = {
        "complete": rep.complete,
        "incomplete": [
            {"reason": i.reason, "nested": list(i.nested), "stream": i.stream} for i in rep.incomplete
        ],
        "counts": rep.counts(),
        "documents": [
            {
                "nested": list(d.nested),
                "doc_type": d.doc_type,
                "streams": d.streams,
                "streams_scanned": d.streams_scanned,
                "bytes_scanned": d.bytes_scanned,
            }
            for d in rep.documents
        ],
        "accounts": [
            {
                "name": a.name,
                "severity": a.severity,
                "sources": list(a.sources),
                "paths": a.paths,
                "identity_fields": a.identity_fields,
                "history_only": a.history_only,
                "inherited_likely": a.inherited_likely,
            }
            for a in rep.accounts
        ],
        "hosts": [
            {"host": h.host, "shares": list(h.shares), "severity": h.severity, "paths": h.paths}
            for h in rep.hosts
        ],
        "identity_fields": [
            {"field": f.field, "value": f.value, "current": f.current, **_where(f.location)}
            for f in rep.identity_fields
        ],
        "paths": [
            {
                "path": p.path,
                "category": p.category,
                "severity": p.severity,
                "reason": p.reason,
                "account": p.account,
                "host": p.host,
                "share": p.share,
                "roles": list(p.roles),
                "sources": list(p.sources),
                "locations": [_where(loc) for loc in p.locations],
                "history_only": p.history_only,
                "inherited_likely": p.inherited_likely,
            }
            for p in rep.paths
        ],
        "rewrite": {"supported": False, "note": REWRITE_NOTE},
        "warnings": [w.to_dict() for w in rep.warnings],
    }
    return to_json_data(data)


# --------------------------------------------------------------------------- folder listings
LISTING_PARTS = ("properties", "configurations", "preview", "preview_data")
LISTING_DEFAULT = ("preview",)


def listing_entry(
    path: str,
    type_: str,
    status: str,
    *,
    reason: str | None = None,
    detected: str | None = None,
    file: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A ``listing`` entry that was not read as a document: every document field null
    (``model`` describes a model file of a format SolidSeas cannot read)."""
    return {
        "path": path,
        "type": type_,
        "status": status,
        "reason": reason,
        "detected": detected,
        "file": file,
        "format": None,
        "doc_type": None,
        "saved_version": None,
        "active_configuration": None,
        "configurations": None,
        "properties": None,
        "preview": None,
        "warnings": [],
        "error": error,
        "model": model,
    }


def document_entry(path: str, doc, include: Collection[str]) -> tuple[dict[str, Any], bytes | None]:
    """A ``listing`` entry for a document that opened, built from the same sub-builders
    as ``document_summary``, and the preview image bytes when ``include`` asks for
    the preview. ``properties`` are the effective properties of the active
    configuration; ``preview.data_base64`` is left null for the caller to fill."""
    warn = _Warnings()
    entry = listing_entry(path, "file", "ok", file=file_data(doc))
    entry.update(
        format=doc.format,
        doc_type=doc.doc_type,
        saved_version=saved_version_data(doc, warn),
        active_configuration=doc.active_configuration,
    )
    if "configurations" in include:
        entry["configurations"] = [configuration_data(c, warn) for c in doc.configurations]
    if "properties" in include:
        entry["properties"] = [property_data(p, warn) for p in doc.effective_properties()]
    image = None
    if "preview" in include or "preview_data" in include:
        obj, image = preview_and_bytes(doc, warn)
        entry["preview"] = {**obj, "data_base64": None}
    reader = _Warnings()
    reader.extend_reader(doc.warnings)
    entry["warnings"] = reader.items + warn.items
    return to_json_data(entry), image


def listing_model_data(doc, warn: _Warnings) -> dict[str, Any]:
    """A listing entry's ``model`` object for a model file that was read."""
    return {
        "format": doc.format,
        "format_name": doc.format_name,
        "variant": doc.variant,
        "kind": doc.kind,
        "readable": True,
        "units": model_units_data(doc),
        "counts": model_counts_data(doc, warn),
        "application": model_application_data(doc),
        "preview_renderable": _renderable(doc),
    }


def unsupported_entry(path: str, file: dict[str, Any] | None, spec) -> dict[str, Any]:
    """The ``listing`` entry of a file of a format SolidSeas lists but cannot read
    (``spec``, a :class:`~solidseas.formats.registry.FormatSpec`): status
    ``unsupported``, ``detected`` its format id. The file is not opened."""
    model = {
        "format": spec.id,
        "format_name": spec.name,
        "variant": None,
        "kind": spec.kind,
        "readable": False,
        "units": None,
        "counts": None,
        "application": None,
        "preview_renderable": False,
    }
    return listing_entry(path, "file", "unsupported", detected=spec.id, file=file, model=model)


def model_listing_entry(path: str, doc, include: Collection[str]) -> tuple[dict[str, Any], bytes | None]:
    """A ``listing`` entry for a model file that opened (status ``ok``, its SOLIDWORKS
    fields null and ``model`` filled), and the preview it stores as a PNG SolidSeas
    wrote (:func:`solidseas.formats._source.preview_png`) when ``include`` asks for the
    preview: ``preview`` describes that PNG."""
    from .formats._source import preview_png

    warn = _Warnings()
    entry = listing_entry(path, "file", "ok", file=file_data(doc))
    entry.update(doc_type=doc.doc_type, active_configuration=doc.active_configuration)
    if "configurations" in include:
        entry["configurations"] = []
    if "properties" in include:
        entry["properties"] = [property_data(p, warn) for p in doc.properties]
    image = None
    if "preview" in include or "preview_data" in include:
        obj: dict[str, Any] = {"available": False, "reason": "not_stored", **_NO_PREVIEW}
        try:
            got = preview_png(doc.preview(), doc.limits)
        except SldFormatError as exc:
            warn.add("preview_undecodable", f"the stored preview could not be read: {exc}")
            got, obj["reason"] = None, "undecodable"
        if got is not None:
            image, width, height, stream = got
            obj = {
                "available": True,
                "reason": None,
                "mime": "image/png",
                "width": width,
                "height": height,
                "bytes": len(image),
                "stream": stream,
                "sha256": hashlib.sha256(image).hexdigest(),
            }
        entry["preview"] = {**obj, "data_base64": None}
    entry["model"] = listing_model_data(doc, warn)
    reader = _Warnings()
    reader.extend_reader(doc.warnings)
    entry["warnings"] = reader.items + warn.items
    return to_json_data(entry), image


def inline_preview(entry: dict[str, Any], image: bytes) -> int:
    """Put the image into ``entry["preview"]["data_base64"]``; returns the characters added."""
    text = base64.b64encode(image).decode("ascii")
    entry["preview"]["data_base64"] = text
    return len(text)


def build_listing(folder, **options: Any) -> dict[str, Any]:
    """``listing`` data for ``folder``: :func:`solidseas.listing.scan` run to the end.
    The keyword options are those of ``scan``."""
    from .listing import scan

    return scan(folder, **options).listing()


# --------------------------------------------------------------------------- command results
def build_streams(doc) -> dict[str, Any]:
    """``streams`` data: every stream of the container with its sizes and codec."""
    return to_json_data(
        {
            "format": doc.format,
            "streams": [
                {"name": s.name, "size": s.size, "compressed_size": s.compressed_size, "codec": s.codec}
                for s in doc.streams()
            ],
        }
    )


def build_file_written(
    output: str,
    nbytes: int,
    *,
    stream: str | None = None,
    raw: bool | None = None,
    mime: str | None = None,
    width: int | None = None,
    height: int | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """``file_written`` data: one file the command line wrote (``dump``, ``preview`` and
    ``convert``). ``source`` says where a preview came from (``stored`` in the file, or
    ``rendered`` from its geometry), or which backend wrote a converted file (``occt``)."""
    return to_json_data(
        {
            "output": output,
            "bytes": nbytes,
            "stream": stream,
            "raw": raw,
            "mime": mime,
            "width": width,
            "height": height,
            "source": source,
        }
    )


def _problem(p: dict[str, Any]) -> dict[str, Any]:
    block = p.get("block")
    feature = p.get("feature")
    return {
        "stream": _text(p.get("stream")),
        "block": block if type(block) is int else None,
        "feature": _text(feature),
        "error": _text(p.get("error")) or "",
    }


def build_parasolid_result(
    bodies: int, written: list[dict[str, Any]], problems: list[dict], *, assembly: Any = None
) -> dict[str, Any]:
    """``parasolid_result`` data: bodies found, files written and the problems met, and for
    an assembly (``assembly``, a :class:`solidseas.parasolid.AssemblyParasolid`) what was
    placed and left out."""
    keys = (
        "output",
        "kind",
        "bytes",
        "body",
        "configuration",
        "configuration_id",
        "source",
        "body_type",
        "schema",
        "valid",
        "transmit",
    )
    return to_json_data(
        {
            "bodies": bodies,
            "written": [{k: w.get(k) for k in keys} for w in written],
            "problems": [_problem(p) for p in problems],
            "assembly": _parasolid_assembly(assembly) if assembly is not None else None,
        }
    )


def _parasolid_assembly(m: Any) -> dict[str, Any]:
    return {
        "name": m.name,
        "configuration": m.configuration,
        "counts": {k: int(v) for k, v in m.counts.items()},
        "instances": [
            {"id": i.id, "name": i.name, "file": i.file, "configuration": i.configuration, "bodies": i.bodies}
            for i in m.instances
        ],
        "skipped": [
            {"id": s.id, "name": s.name, "file": s.file, "reason": s.reason, "message": s.message}
            for s in m.skipped
        ],
        "warnings": [w.to_dict() for w in m.warnings],
        "seconds": round(m.seconds, 3),
    }


def build_batch_summary(
    *,
    files: int,
    status_counts: dict[str, int],
    report_csv: str,
    report_jsonl: str,
    previews: int,
    parasolid_files: int,
    walk: dict[str, Any],
    parasolid_left_out: int = 0,
) -> dict[str, Any]:
    """``batch_summary`` data: what a ``batch`` run did, and what its folder walk saw.
    ``parasolid_left_out`` counts the components the assemblies' Parasolid files left out
    (``--allow-partial``)."""
    return to_json_data(
        {
            "files": files,
            "status_counts": dict(sorted(status_counts.items())),
            "report_csv": report_csv,
            "report_jsonl": report_jsonl,
            "previews": previews,
            "parasolid_files": parasolid_files,
            "parasolid_left_out": parasolid_left_out,
            "walk": walk,
        }
    )


def _mm(metres: float | None, power: int = 1) -> float | None:
    return None if metres is None else metres * 1000.0**power


def _step_data(m: Any) -> dict[str, Any]:
    """The ``step`` object of a STEP export's ``export_result``."""
    faces = sum(b.approximated_faces for b in m.bodies)
    edges = sum(b.approximated_edges for b in m.bodies)
    return {
        "schema": "AP214",
        "exact": m.exact,
        "partial": m.partial,
        "uncertainty_mm": _mm(m.uncertainty_m),
        "max_deviation_mm": _mm(m.max_deviation_m),
        "max_tolerance_mm": _mm(m.max_tolerance_m),
        "max_gap_mm": _mm(m.max_gap_m),
        "approximated": {
            "faces": faces,
            "edges": edges,
            "by_class": {k: int(v) for k, v in sorted(m.approximated.items())},
        },
        "bodies": [
            {
                "product": b.product,
                "name": b.name,
                "configuration": b.configuration,
                "kind": b.kind,
                "source": b.source,
                "faces": b.faces,
                "edges": b.edges,
                "vertices": b.vertices,
                "split_faces": b.split_faces,
                "approximated_faces": b.approximated_faces,
                "approximated_edges": b.approximated_edges,
                "max_deviation_mm": _mm(b.max_deviation_m),
                "max_tolerance_mm": _mm(b.max_tolerance_m),
                "written": b.written,
                "reason": b.reason,
                "message": b.message,
            }
            for b in m.bodies[:1000]
        ],
    }


def build_export_result(result: Any, check: dict[str, Any] | None = None) -> dict[str, Any]:
    """``export_result`` data (provisional): a file ``solidseas.export`` or
    ``solidseas.step`` wrote, from its ``ExportResult`` or ``StepResult``, and ``check``,
    what Open CASCADE made of a STEP file when ``export --check`` asked (None
    otherwise). Lengths in millimetres."""
    from .export import MIME_TYPES

    m = result.model
    if result.format == "step":
        return to_json_data(
            {
                "output": result.path,
                "format": result.format,
                "mime": MIME_TYPES.get(result.format),
                "bytes": result.bytes,
                "merged": False,
                "name": m.name,
                "doc_type": m.doc_type,
                "configuration": m.configuration,
                "chord_mm": None,
                "closed": m.closed,
                "counts": {k: int(v) for k, v in m.counts.items()},
                "objects": [],
                "skipped": [
                    {"id": s.id, "name": s.name, "file": s.file, "reason": s.reason, "message": s.message}
                    for s in m.skipped
                ],
                "warnings": [w.to_dict() for w in m.warnings],
                "seconds": round(m.seconds, 3),
                "step": _step_data(m),
                "source_format": getattr(m, "source_format", "solidworks"),
                "check": check,
            }
        )
    uses = Counter(it.object for it in m.items)
    objects = []
    for i, o in enumerate(m.objects):
        measures = o.measures()
        objects.append(
            {
                "name": o.name,
                "file": o.file,
                "configuration": o.configuration,
                "source": o.source,
                "vertices": o.n_vertices,
                "triangles": o.n_triangles,
                "instances": uses[i],
                "closed": o.closed,
                "chord_mm": _mm(o.chord_m),
                "volume_mm3": _mm(measures["volume_m3"], 3),
                "area_mm2": _mm(measures["area_m2"], 2),
                "warnings": [w.to_dict() for w in o.warnings],
            }
        )
    return to_json_data(
        {
            "output": result.path,
            "format": result.format,
            "mime": MIME_TYPES.get(result.format),
            "bytes": result.bytes,
            "merged": result.merged,
            "name": m.name,
            "doc_type": m.doc_type,
            "configuration": m.configuration,
            "chord_mm": _mm(m.chord_m),
            "closed": m.closed,
            "counts": {k: int(v) for k, v in m.counts.items()},
            "objects": objects,
            "skipped": [
                {"id": s.id, "name": s.name, "file": s.file, "reason": s.reason, "message": s.message}
                for s in m.skipped
            ],
            "warnings": [w.to_dict() for w in m.warnings],
            "seconds": round(m.seconds, 3),
            "step": None,
            "source_format": getattr(m, "source_format", "solidworks"),
            "check": check,
        }
    )


def build_sldprt_written(
    output: str,
    nbytes: int,
    *,
    design_name: str,
    design_format: str,
    features: Collection[dict[str, str]] = (),
    properties: Collection[dict[str, Any]] = (),
    left_out: Collection[str] = (),
    unsupported: Collection[str] = (),
) -> dict[str, Any]:
    """``sldprt_written`` data (provisional): the native part ``solidseas sldprt`` wrote
    from a design. ``features`` are the design's features the part holds, each with its
    id and name in the design and its name in the part; ``properties`` the file custom
    properties it holds, each with its name, type and value; ``left_out`` is everything of the
    design the part does not carry, in words; ``unsupported`` the items among them that
    were left out only because ``--allow-partial`` was given."""
    return to_json_data(
        {
            "output": output,
            "bytes": nbytes,
            "design": {"name": design_name, "format": design_format},
            "features": [{"id": f["id"], "name": f["name"], "part_name": f["part_name"]} for f in features],
            "properties": [{"name": p["name"], "type": p["type"], "value": p["value"]} for p in properties],
            "left_out": list(left_out),
            "unsupported": list(unsupported),
            "partial": bool(unsupported),
        }
    )


def build_version() -> dict[str, Any]:
    """``version`` data: the package version, the API version and each kind's schema version."""
    return {
        "solidseas": __version__,
        "api": API_VERSION,
        "schemas": {name: spec.schema_version for name, spec in KINDS.items()},
    }


# --------------------------------------------------------------------------- the service
def build_health() -> dict[str, Any]:
    """``health`` data: the service answers. It says nothing else, because it needs no
    token."""
    return {"status": "ok"}


def build_identity(
    *, scheme: str, client: str, nonce: str, address: str, port: int, proof: str
) -> dict[str, Any]:
    """``identity`` data: the service's proof that it holds ``client``'s token, for the
    client to check before it sends that token (``docs/API.md`` 8.16). ``proof`` is
    the HMAC of ``scheme``, ``client``, ``nonce``, ``address`` and ``port`` under the
    token; ``address`` and ``port`` are those the connection reached on the service's
    side, sent so a client whose check fails can say where it was answered from."""
    return {
        "scheme": scheme,
        "client": client,
        "nonce": nonce,
        "address": address,
        "port": port,
        "proof": proof,
    }


ROOT_STATES = ("building", "ready", "unavailable")


def build_roots(states) -> dict[str, Any]:
    """``roots`` data: each configured root by id, never by its path, with the state of
    its folder index. ``states`` holds objects with ``id``, ``role``, ``recursive``,
    ``state`` (``building``, ``ready`` or ``unavailable``), ``index_partial`` and
    ``documents`` (None until the index is built)."""
    return to_json_data(
        {
            "roots": [
                {
                    "id": s.id,
                    "role": s.role,
                    "recursive": s.recursive,
                    "state": s.state,
                    "index_partial": s.index_partial,
                    "documents": s.documents,
                }
                for s in states
            ]
        }
    )


def build_serve_started(
    *, host: str, port: int, roots: list[str], workers: int, token_file_created: bool
) -> dict[str, Any]:
    """``serve_started`` data: the one line ``solidseas serve`` prints when it is ready.
    ``url`` is the base of every route; the token itself is never printed."""
    shown = f"[{host}]" if ":" in host else host
    return to_json_data(
        {
            "host": host,
            "port": port,
            "url": f"http://{shown}:{port}/v1/",
            "roots": list(roots),
            "workers": workers,
            "auth": "bearer",
            "token_file_created": token_file_created,
        }
    )


# --------------------------------------------------------------------------- the catalog (provisional)
# The catalog (solidseas.catalog) builds its kinds' data in its query and scan modules, from
# its own rows; these builders are the registry's entry points, given an open Catalog.
def build_catalog(cat, *, paths: bool = True) -> dict[str, Any]:
    """``catalog`` data: a catalog's roots, counts and last scan (``Catalog.status``)."""
    return cat.status(paths=paths)


def build_catalog_list(catalogs: list[dict[str, Any]], *, cache_dir: str) -> dict[str, Any]:
    """``catalog_list`` data: every catalog in the cache folder (``catalog.list_catalogs``)."""
    return to_json_data(
        {
            "cache_dir": cache_dir,
            "catalogs": [
                {
                    "name": c["name"],
                    "folder": c["folder"],
                    "roots": [{"id": r["id"], "path": r["path"], "role": r["role"]} for r in c["roots"]],
                    "last_scan_utc": c.get("last_scan_utc"),
                    "last_scan_state": c.get("last_scan_state"),
                    "catalog_bytes": c.get("catalog_bytes"),
                    "previews_bytes": c.get("previews_bytes"),
                    "error": c.get("error"),
                }
                for c in catalogs
            ],
        }
    )


def build_catalog_cleared(removed: list[str], *, catalogs: list[str]) -> dict[str, Any]:
    """``catalog_cleared`` data: the catalogs deleted and the files that went with them."""
    return to_json_data({"catalogs": list(catalogs), "files": list(removed)})


def build_catalog_scan(cat, **options: Any) -> dict[str, Any]:
    """``catalog_scan`` data: what one scan did (``Catalog.scan``)."""
    return cat.scan(**options)


def build_where_used(cat, root: str, path: str, **options: Any) -> dict[str, Any]:
    """``where_used`` data (``Catalog.where_used``)."""
    return cat.where_used(root, path, **options)


def build_catalog_search(cat, text: str, **options: Any) -> dict[str, Any]:
    """``catalog_search`` data (``Catalog.search``)."""
    return cat.search(text, **options)


def build_duplicates(cat, **options: Any) -> dict[str, Any]:
    """``duplicates`` data (``Catalog.duplicates``)."""
    return cat.duplicates(**options)


def build_missing_references(cat, **options: Any) -> dict[str, Any]:
    """``missing_references`` data (``Catalog.missing_references``)."""
    return cat.missing_references(**options)


def build_file_history(path, **options: Any) -> dict[str, Any]:
    """``file_history`` data (provisional, ``docs/API.md`` 3.26): the versions of the file
    at ``path``, from Git or from snapshots (:func:`solidseas.versions.history`)."""
    from . import versions

    return to_json_data(versions.history(path, **options))


def build_snapshot_taken(path, **options: Any) -> dict[str, Any]:
    """``snapshot_taken`` data (provisional): :func:`solidseas.versions.snapshot`."""
    from . import versions

    return to_json_data(versions.snapshot(path, **options))


def build_version_diff(path, older=None, newer=None, **options: Any) -> dict[str, Any]:
    """``version_diff`` data (provisional): what changed between two versions of the file
    at ``path`` (:func:`solidseas.versions.compare`)."""
    from . import versions

    return to_json_data(versions.compare(path, older, newer, **options))


def build_catalog_changes(cat, **options: Any) -> dict[str, Any]:
    """``catalog_changes`` data (``Catalog.changes``)."""
    return cat.changes(**options)


# --------------------------------------------------------------------------- drawings (provisional)
DRAWING_ACTIONS = ("new", "export", "update", "check", "show", "settings")
CHECK_LEVELS = ("error", "warning", "information")
DRAWING_FILE_KINDS = ("ssdrw", "pdf", "dxf")


def _attr(obj: Any, *names: str) -> Any:
    """The first of ``names`` that ``obj`` has (a mapping's key or an attribute) and is not
    None or empty."""
    for n in names:
        v = obj.get(n) if isinstance(obj, dict) else getattr(obj, n, None)
        if v is not None and v != "" and v != ():
            return v
    return None


def drawing_check_data(check: Any) -> dict[str, Any]:
    """One check of a drawing (``docs/DRAWINGS.md`` 20.1) as ``{"code", "level", "item",
    "message", "fixes"}``: from a ``checks.Check``, a layout check (``severity`` and
    ``owner``) or a mapping. ``item`` is the code itself when the check is about the
    drawing as a whole."""
    code = _attr(check, "code", "rule")
    code = clean_text(code) if isinstance(code, str) else "unknown"
    level = _attr(check, "level", "severity")
    level = level.lower() if isinstance(level, str) else "warning"
    item = _attr(check, "item", "owner", "id", "key")
    message = _attr(check, "message", "words", "text")
    fixes = _attr(check, "fixes") or ()
    if isinstance(fixes, str):
        fixes = (fixes,)
    return {
        "code": code,
        "level": level,
        "item": clean_text(item) if isinstance(item, str) else code,
        "message": clean_text(message) if isinstance(message, str) else code,
        "fixes": [clean_text(f if isinstance(f, str) else str(f)) for f in fixes],
    }


def check_counts(checks: list[dict[str, Any]]) -> dict[str, int]:
    """How many checks there are at each level (``error``, ``warning``, ``information``)."""
    counts = dict.fromkeys(CHECK_LEVELS, 0)
    for c in checks:
        if c["level"] in counts:
            counts[c["level"]] += 1
    return counts


def drawing_coverage_data(coverage: Any) -> dict[str, Any] | None:
    """A drawing's coverage (``docs/DRAWINGS.md`` 20.2) by features, faces and area (square
    millimetres), whether it is complete and the sentence that says it; None when there
    is none (a drawing read from a file, which does not store it)."""
    if coverage is None:
        return None
    area = float(coverage.area) * 1e6
    claimed = float(coverage.area_claimed) * 1e6
    return to_json_data(
        {
            "complete": bool(coverage.complete),
            "words": clean_text(coverage.words()),
            "features": int(coverage.features),
            "features_unclaimed": int(coverage.features_unclaimed),
            "faces": int(coverage.faces),
            "faces_claimed": int(coverage.faces_claimed),
            "area_mm2": area,
            "area_claimed_mm2": claimed,
            "area_fraction": claimed / area if area > 0 else None,
        }
    )


def _scale_text(scale: Any) -> str:
    if isinstance(scale, (tuple, list)) and len(scale) == 2:
        return f"{scale[0]}:{scale[1]}"
    return str(scale)


def drawing_summary_data(drawing: Any) -> dict[str, Any]:
    """The summary of a drawing (``solidseas.drawing.types.Drawing``) that
    ``drawing_result`` carries: id, status, revision, title fields, signatures (and
    whether each still matches the content), revisions, the model's identity, the frozen
    options, counts and the recorded outputs. Never a path."""
    from .drawing import display, release

    digest = release.content_digest(drawing)
    model = drawing.model or {}
    units = model.get("units") if isinstance(model.get("units"), dict) else {}
    options = drawing.options
    sheet = drawing.sheet if isinstance(drawing.sheet, display.Sheet) else None
    views = list(options.views) if isinstance(options.views, tuple) else []
    states = [getattr(d, "state", "shown") for d in drawing.dimensions]
    attention = sum(1 for d in drawing.dimensions if "needs_attention" in getattr(d, "flags", ()))
    annotations = sheet.annotations if sheet is not None else ()
    pages = display.sheets_of(sheet)
    lists = [a for page in pages for a in page.annotations if isinstance(a, display.PartsList)]
    items = sum(len(a.rows) for a in lists)
    balloons = sum(1 for a in annotations if isinstance(a, display.Balloon))
    created = getattr(drawing, "created", None)
    modified = getattr(drawing, "modified", None)
    return to_json_data(
        {
            "id": drawing.id,
            "status": drawing.status,
            "revision": drawing.revisions[-1].rev if drawing.revisions else None,
            "title": {key: {"text": clean_text(f.text), "from": f.source} for key, f in drawing.title},
            "signatures": [
                {"row": s.row, "name": clean_text(s.name), "date": s.date, "current": s.digest == digest}
                for s in drawing.signatures
            ],
            "revisions": [
                {
                    "rev": r.rev,
                    "description": clean_text(r.description),
                    "zones": list(r.zones),
                    "date": r.date,
                    "approved": None if r.approved is None else clean_text(r.approved),
                }
                for r in drawing.revisions
            ],
            "model": {
                "name": _text(model.get("name")),
                "format": _text(model.get("format")),
                "configuration": _text(model.get("configuration")),
                "sha256": _text(model.get("sha256")),
                "unit": _text(units.get("unit")),
                "unit_origin": _text(units.get("origin")),
            },
            "options": {
                "process": options.process,
                "scheme": options.effective_scheme,
                "detail": options.detail,
                "units": options.units,
                "views": views,
                "sheet": sheet.name if sheet is not None else options.sheet,
                "scale": _scale_text(sheet.scale if sheet is not None else options.scale),
            },
            "counts": {
                "features": len(drawing.features),
                "dimensions": len(drawing.dimensions),
                "shown": sum(1 for s in states if s != "removed"),
                "removed": sum(1 for s in states if s == "removed"),
                "needs_attention": attention,
                "notes": len(drawing.notes),
                "views": len(sheet.views) if sheet is not None else len(views),
                "items": items,
                "balloons": balloons,
                "sheets": len(pages),
            },
            "outputs": [
                {
                    "kind": o.kind,
                    "name": clean_text(o.name),
                    "sha256": o.sha256,
                    "revision": o.revision,
                    "released": o.released,
                }
                for o in drawing.outputs
            ],
            "created": created if isinstance(created, str) else None,
            "modified": modified if isinstance(modified, str) else None,
        }
    )


def drawing_thread_candidates(drawing: Any, features: Any = None) -> list[dict[str, Any]]:
    """The holes and hole patterns of a drawing whose diameter is a tap drill (thread
    candidates, ``docs/DRAWINGS.md`` 9 and 10.9): the feature's id, ``hole`` or
    ``pattern``, how many holes, the diameter in millimetres, the threads it may be, and
    the user's answer (``answered``; ``confirmed`` the thread, or None for a plain hole).
    With ``features`` (the run's ``FeatureSet``, whose order is the feature table's) the
    holes a pattern holds are left out, since the callout is the pattern's; from a file
    the table's descriptors are read alone."""
    from .drawing import standards

    found: list[dict[str, Any]] = []
    members: set[int] = set()
    live = features is not None and len(getattr(features, "features", ())) == len(drawing.features)
    if live:
        for f in features.features:
            members.update(getattr(f, "members", ()) or ())
    for i, rec in enumerate(drawing.features):
        size = dict(rec.descriptor.size)
        if rec.descriptor.type == "Hole":
            kind, count, diameters = "hole", 1, size.get("diameters")
            if size.get("kind") != "simple":
                continue
        elif rec.descriptor.type == "Pattern":
            kind, count, diameters = "pattern", size.get("count"), size.get("hole")
        else:
            continue
        if live:
            if i in members:
                continue
            f = features.features[i]
            hole = features.features[f.members[0]] if kind == "pattern" and f.members else f
            if not getattr(hole, "thread", ()):
                continue
        if not isinstance(diameters, (tuple, list)) or len(diameters) != 1:
            continue
        try:
            diameter = float(diameters[0])
        except (TypeError, ValueError):
            continue
        threads = standards.threads_for_drill(diameter)
        if not threads:
            continue
        decided = dict(rec.decisions)
        confirmed = decided.get("thread")
        found.append(
            {
                "feature": rec.id,
                "kind": kind,
                "count": count if isinstance(count, int) and not isinstance(count, bool) else 1,
                "diameter_mm": round(diameter * 1000.0, 6),
                "threads": [t.designation for t in threads],
                "answered": "thread" in decided,
                "confirmed": clean_text(confirmed) if isinstance(confirmed, str) else None,
            }
        )
    return to_json_data(found)


def drawing_file_data(
    path: str, kind: str, sha256: str, size: int, *, replaced: bool, renamed: bool, released: bool = False
) -> dict[str, Any]:
    """A file the drawing command wrote: its path, name, kind (``ssdrw``, ``pdf`` or
    ``dxf``), SHA-256 and size, whether it replaced the same drawing's own earlier file
    (else it is new), whether a numbered name was taken because the plain one was not
    free, and whether it is a released export."""
    if kind not in DRAWING_FILE_KINDS:
        raise InvalidArgumentError("kind is ssdrw, pdf or dxf", detail={"parameter": "kind"})
    return to_json_data(
        {
            "path": path,
            "name": os.path.basename(path),
            "kind": kind,
            "sha256": sha256,
            "bytes": size,
            "replaced": bool(replaced),
            "renamed": bool(renamed),
            "released": bool(released),
        }
    )


def drawing_settings_data(settings: Any, problems: Collection[str], *, path: str | None, found: bool):
    """Drawing Settings as ``drawing settings`` prints them: the file read (or None), whether
    it was there, every value as the file holds it, the fallbacks (each value that failed
    its check and the default used instead) and what still waits for the user's answer."""
    from .drawing import settings as settings_mod

    return to_json_data(
        {
            "path": path,
            "found": bool(found),
            "values": settings_mod.to_dict(settings),
            "fallbacks": [clean_text(str(p)) for p in problems],
            "first_use": list(settings.first_use()),
        }
    )


def build_drawing_result(
    action: str,
    *,
    drawing: Any = None,
    files: Collection[dict[str, Any]] = (),
    merge: Any = None,
    checks: Collection[Any] = (),
    coverage: Any = None,
    thread_candidates: Collection[dict[str, Any]] = (),
    seconds: Any = (),
    warnings: Collection[str] = (),
    settings: dict[str, Any] | None = None,
    model_check: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """``drawing_result`` data, what ``solidseas drawing ACTION --json`` prints
    (``docs/DRAWINGS.md`` 14): the action, the drawing's summary, the files written, the
    merge report of an update, the checks and their counts, coverage, thread candidates,
    seconds per stage, warnings, and for ``settings`` the settings, for ``check --model``
    the model's verification."""
    if action not in DRAWING_ACTIONS:
        raise InvalidArgumentError(
            f"action must be one of {', '.join(DRAWING_ACTIONS)}", detail={"parameter": "action"}
        )
    from .drawing.assembly import is_assembly

    checked = [drawing_check_data(c) for c in checks]
    pairs = seconds.items() if isinstance(seconds, dict) else seconds
    if drawing is not None and is_assembly(drawing):
        coverage = None  # an assembly's drawing has no features to cover
    return to_json_data(
        {
            "action": action,
            "dry_run": bool(dry_run),
            "drawing": None if drawing is None else drawing_summary_data(drawing),
            "files": list(files),
            "merge": None if merge is None else merge.to_dict(),
            "checks": checked,
            "check_counts": check_counts(checked),
            "coverage": drawing_coverage_data(coverage),
            "thread_candidates": list(thread_candidates),
            "seconds": {str(k): float(v) for k, v in pairs},
            "warnings": [clean_text(str(w)) for w in warnings],
            "settings": settings,
            "model_check": model_check,
        }
    )


# --------------------------------------------------------------------------- JSON Schemas
_STR = {"type": "string"}
_STR_N = {"type": ["string", "null"]}
_INT = {"type": "integer"}
_INT_N = {"type": ["integer", "null"]}
_BOOL = {"type": "boolean"}
_BOOL_N = {"type": ["boolean", "null"]}


def _obj(props: dict[str, Any], *, nullable: bool = False, description: str | None = None) -> dict[str, Any]:
    s: dict[str, Any] = {"type": ["object", "null"] if nullable else "object"}
    if description:
        s["description"] = description
    s["properties"] = props
    s["required"] = list(props)
    return s


def _ref(name: str) -> dict[str, Any]:
    return {"$ref": f"#/$defs/{name}"}


def _ref_n(name: str) -> dict[str, Any]:
    return {"anyOf": [_ref(name), {"type": "null"}]}


def _arr(items: dict[str, Any], *, nullable: bool = False) -> dict[str, Any]:
    return {"type": ["array", "null"] if nullable else "array", "items": items}


_DEFS: dict[str, dict[str, Any]] = {
    "warning": _obj({"code": _STR, "stream": _STR_N, "message": _STR}),
    "file": _obj(
        {
            "name": _STR_N,
            "size": _INT_N,
            "modified_utc": _STR_N,
            "mtime_ns": {"type": ["string", "null"], "pattern": "^-?[0-9]+$"},
        },
        description="Null fields for a document opened from bytes. mtime_ns is a string: it exceeds 2**53.",
    ),
    "material": _obj({"name": _STR, "database": _STR_N}),
    "saved_version": _obj(
        {
            "format_version": _INT_N,
            "release": _STR_N,
            "release_verified": _BOOL,
            "last_build": _INT_N,
            "last_build_date": _STR_N,
            "save_as_previous": _BOOL,
        }
    ),
    "units": _obj(
        {
            "system": {"type": ["string", "integer", "null"]},
            "length": {"type": ["string", "integer", "null"]},
            "mass": {"type": ["string", "integer", "null"]},
            "angle": {"type": ["string", "integer", "null"]},
            "length_decimal_places": _INT_N,
        },
        nullable=True,
    ),
    "fields": _obj(
        {
            "title": _STR_N,
            "subject": _STR_N,
            "author": _STR_N,
            "keywords": _STR_N,
            "comments": _STR_N,
            "last_saved_by": _STR_N,
            "created_utc": _STR_N,
            "last_saved_utc": _STR_N,
        }
    ),
    "preview": _obj(
        {
            "available": _BOOL,
            "reason": _STR_N,
            "mime": _STR_N,
            "width": _INT_N,
            "height": _INT_N,
            "bytes": _INT_N,
            "stream": _STR_N,
            "sha256": {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"},
        }
    ),
    "property": _obj(
        {
            "name": _STR,
            "scope": {"enum": ["file", "configuration"]},
            "configuration": _STR_N,
            "type": {"type": "string", "description": "text, number, boolean, date or other (an open set)"},
            "value": {"type": ["string", "number", "boolean", "null"]},
            "date": {"type": ["string", "null"], "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
            "text": _STR_N,
            "expression": _STR_N,
            "linked": _BOOL,
        }
    ),
    "configuration": _obj(
        {
            "name": _STR,
            "id": _INT_N,
            "active": _BOOL,
            "most_recent": _BOOL_N,
            "comment": _STR_N,
            "material": _ref_n("material"),
            "material_assigned": _BOOL_N,
            "properties": _arr(_ref("property")),
        }
    ),
    "counts": _obj(
        {
            "streams": _INT,
            "configurations": _INT,
            "custom_properties": _INT,
            "references": _INT_N,
            "nested_documents": _INT,
            "parasolid_partitions": _INT,
        }
    ),
    "error": _obj(
        {
            "code": _STR,
            "message": _STR,
            "exception": _STR,
            "retryable": _BOOL,
            "detail": {"type": "object"},
            "reader_message": _STR_N,
        }
    ),
}
_DEFS["model_units"] = _obj(
    {
        "length": {"type": ["string", "null"], "description": "mm, cm, m, in, ft or micron (an open set)"},
        "scale_m": {"type": ["number", "null"]},
        "source": {"type": ["string", "null"], "description": "file, format or assumed (an open set)"},
    },
    description="The unit of length: metres per unit, and whether the file states it.",
)
_DEFS["model_application"] = _obj({"name": _STR_N, "version": _STR_N})
_DEFS["model_counts"] = _obj(
    {
        k: _INT_N
        for k in (
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
    },
    description="What the file's head tells of its size; null where that needs a full read.",
)
_DEFS["listing_model"] = _obj(
    {
        "format": _STR,
        "format_name": _STR,
        "variant": _STR_N,
        "kind": {"type": "string", "description": "mesh, brep or mixed (an open set)"},
        "readable": _BOOL,
        "units": _ref_n("model_units"),
        "counts": _ref_n("model_counts"),
        "application": _ref_n("model_application"),
        "preview_renderable": _BOOL,
    },
    description="A model file (not a SOLIDWORKS document): its format, and what its head says.",
)
_DEFS["listing_preview"] = _obj(
    {**_DEFS["preview"]["properties"], "data_base64": _STR_N},
    description="The summary's preview object plus data_base64, the image when inline data was requested.",
)
_DEFS["listing_entry"] = _obj(
    {
        "path": _STR,
        "type": {"enum": ["file", "folder"]},
        "status": {
            "type": "string",
            "description": "ok, error, skipped, link, placeholder, not_solidworks or unsupported",
        },
        "reason": _STR_N,
        "detected": _STR_N,
        "file": _ref_n("file"),
        "format": {"enum": ["modern", "ole", None]},
        "doc_type": {"enum": ["part", "assembly", "drawing", None]},
        "saved_version": _ref_n("saved_version"),
        "active_configuration": _STR_N,
        "configurations": _arr(_ref("configuration"), nullable=True),
        "properties": _arr(_ref("property"), nullable=True),
        "preview": _ref_n("listing_preview"),
        "warnings": _arr(_ref("warning")),
        "error": _ref_n("error"),
        "model": _ref_n("listing_model"),
    }
)
_NUM = {"type": "number"}
_DEFS["placement"] = _obj(
    {"rotation": _arr(_arr(_NUM)), "translation_m": _arr(_NUM)},
    description="A point p of the component is at rotation @ p + translation_m (rows, metres).",
)
_DEFS["transform"] = _obj(
    {"stored": _arr(_NUM), **_DEFS["placement"]["properties"], "scale": _NUM},
    description="The stored swTransform, relative to the parent instance, and what it decodes to.",
)
_DEFS["configuration_counts"] = _obj(
    {"configuration": _STR, "instances": _INT, "instances_unsuppressed": _INT, "instances_in_bom": _INT}
)
_DEFS["location"] = _obj(
    {"root": _STR_N, "path": _STR},
    description="A root id and a /-separated path relative to it; root null: an absolute path on this "
    "machine outside every root (CLI and Python only).",
)
_DEFS["resolution_candidate"] = _obj(
    {
        "root": _STR_N,
        "path": _STR,
        "found_by": {"type": "string", "description": "the rule that found the file (an open set)"},
        "identity": {"type": "string", "description": "match, differ or unknown"},
        "placeholder": _BOOL,
    }
)
_DEFS["reference_resolution"] = _obj(
    {
        "key": _STR,
        "status": {
            "type": "string",
            "description": "resolved, moved, embedded, embedded_not_found, embedded_in_subassembly, "
            "ambiguous or missing (an open set)",
        },
        "stored_path": _STR_N,
        "match": _ref_n("location"),
        "rule": {
            "type": ["string", "null"],
            "description": "embedded, stored_unmoved, path_map, rebased, same_folder, suffix_probe, "
            "stored_path, name_index or name_index_suffix (an open set)",
        },
        "confidence": {"type": "string", "description": "high, medium, low or none"},
        "identity": {"type": "string", "description": "match, differ or unknown"},
        "nested": _STR_N,
        "candidates": _arr(_ref("resolution_candidate")),
        "warnings": _arr(_ref("warning")),
    }
)
_DEFS["resolution_summary"] = _obj(
    {
        "roots": _arr(
            _obj(
                {
                    "id": _STR,
                    "role": {"type": "string", "description": "project or library"},
                    "recursive": _BOOL,
                    "index_partial": _BOOL,
                    "truncated_reason": _STR_N,
                }
            )
        ),
        "index_partial": _BOOL,
        "outside_roots": _BOOL,
        "truncated": _BOOL,
        "counts": {"type": "object", "additionalProperties": _INT},
    },
    nullable=True,
)
_DEFS["component_file"] = _obj(
    {
        "key": _STR,
        "stored_path": _STR_N,
        "file_name": _STR_N,
        "doc_type": {"enum": ["part", "assembly", None]},
        "direct": _BOOL_N,
        "virtual": _BOOL,
        "imported": _BOOL,
        "nested": _STR_N,
        "embedded": {
            "type": ["string", "null"],
            "description": "embedded, embedded_not_found or embedded_in_subassembly (an open set)",
        },
        "embedded_in_subassembly": _BOOL,
        "configurations_used": _arr(_STR_N),
        "instances": _INT_N,
        "instances_unsuppressed": _INT_N,
        "instances_in_bom": _INT_N,
        "per_configuration": _arr(_ref("configuration_counts"), nullable=True),
        "sources": _arr(_STR),
        "resolution": _ref_n("reference_resolution"),
    }
)
_DEFS["component_node"] = _obj(
    {
        "id": _STR,
        "parent": _STR_N,
        "name": _STR,
        "component": _STR_N,
        "number": _INT_N,
        "depth": _INT,
        "file": _STR_N,
        "doc_type": {"enum": ["part", "assembly", None]},
        "configuration": _STR_N,
        "suppressed": _BOOL,
        "hidden": _BOOL,
        "excluded_from_bom": _BOOL,
        "virtual": _BOOL,
        "transform": _ref_n("transform"),
        "placement": _ref_n("placement"),
        "children_state": {
            "type": "string",
            "description": "none, described, truncated, cycle or unknown (an open set)",
        },
        "children": _arr(_ref("component_node"), nullable=True),
    }
)
_DEFS["drawing_sheet"] = _obj(
    {
        "name": _STR,
        "views": _arr(_obj({"name": _STR_N, "configuration": _STR_N, "file_name": _STR_N, "file": _STR_N})),
    }
)
_DEFS["walk"] = _obj(
    {
        "folders": _INT,
        "entries": _INT,
        "files": _INT,
        "links": _INT,
        "placeholders": _INT,
        "skipped": _INT,
        "errors": _INT,
        "depth_limited": _INT,
        "truncated": _STR_N,
    }
)


def _schema(
    kind: str, version: int, title: str, body: dict[str, Any], defs: tuple[str, ...]
) -> dict[str, Any]:
    s = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"urn:solidseas:schema:{kind}:v{version}",
        "title": title,
        **body,
    }
    if defs:
        s["$defs"] = {name: _DEFS[name] for name in defs}
    return s


_DEFS["model_node"] = _obj(
    {
        "id": _STR,
        "parent": _STR_N,
        "name": _STR_N,
        "kind": {"type": "string", "description": "assembly, component, object or body (an open set)"},
        "object": _INT_N,
        "file": _STR_N,
        "placement": _ref_n("placement"),
        "color": {"type": ["array", "null"], "items": {"type": "number"}},
    }
)
_DEFS["model_reference"] = _obj(
    {
        "key": _STR,
        "kind": {"type": "string", "description": "component, buffer or material_library (an open set)"},
        "name": _STR_N,
        "stored": _STR_N,
        "resolution": _obj(
            {
                "status": _STR_N,
                "path": _STR_N,
                "found_by": _STR_N,
                "version": _STR_N,
            },
            nullable=True,
        ),
    }
)
_DEFS["model_preview"] = _obj(
    {
        **_DEFS["preview"]["properties"],
        "source": {"type": ["string", "null"], "description": "stored (an open set)"},
        "renderable": _BOOL,
    },
    description="The image the file stores, as stored; renderable: a preview can be drawn from the model.",
)
_MODEL_SUMMARY_SCHEMA = _obj(
    {
        "file": _ref("file"),
        "format": {
            "type": "string",
            "description": "the registry's format id: stl, 3mf, step... (an open set)",
        },
        "format_name": _STR,
        "variant": _STR_N,
        "doc_type": {"enum": ["part", "assembly", None]},
        "kind": {"type": "string", "description": "mesh, brep or mixed (an open set)"},
        "units": _ref("model_units"),
        "application": _ref("model_application"),
        "active_configuration": _STR_N,
        "fields": _ref("fields"),
        "properties": _arr(_ref("property"), nullable=True),
        "counts": _ref("model_counts"),
        "tree": _obj({"nodes": _arr(_ref("model_node")), "truncated": _BOOL}, nullable=True),
        "references": _arr(_ref("model_reference"), nullable=True),
        "preview": _ref("model_preview"),
        "warnings": _arr(_ref("warning")),
    }
)
_SUMMARY_SCHEMA = _obj(
    {
        "file": _ref("file"),
        "format": {"enum": ["modern", "ole"]},
        "doc_type": {"enum": ["part", "assembly", "drawing", None]},
        "doc_type_source": {"enum": ["definition", "extension", "none"]},
        "saved_version": _ref("saved_version"),
        "active_configuration": _STR_N,
        "configurations": _arr(_ref("configuration"), nullable=True),
        "properties": _arr(_ref("property"), nullable=True),
        "material": _ref_n("material"),
        "units": _ref("units"),
        "fields": _ref("fields"),
        "preview": _ref("preview"),
        "counts": _ref("counts"),
        "warnings": _arr(_ref("warning")),
    }
)
_PROPERTIES_SCHEMA = _obj(
    {
        "view": {"enum": list(PROPERTY_VIEWS)},
        "configuration": _STR_N,
        "properties": _arr(_ref("property")),
        "warnings": _arr(_ref("warning")),
    }
)
_CONFIGURATIONS_SCHEMA = _obj(
    {
        "active_configuration": _STR_N,
        "configurations": _arr(_ref("configuration")),
        "warnings": _arr(_ref("warning")),
    }
)
_VERSION_SCHEMA = _obj(
    {
        "solidseas": {"type": "string", "pattern": "^[0-9]+\\.[0-9]+\\.[0-9]+$"},
        "api": _INT,
        "schemas": {"type": "object", "additionalProperties": _INT},
    }
)
_ERROR_SCHEMA = _DEFS["error"]
_HEALTH_SCHEMA = _obj({"status": {"const": "ok"}})
_IDENTITY_SCHEMA = _obj(
    {
        "scheme": {"type": "string", "description": "solidseas-identity-v1 (an open set)"},
        "client": _STR,
        "nonce": _STR,
        "address": _STR,
        "port": _INT,
        "proof": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    }
)
_ROOTS_SCHEMA = _obj(
    {
        "roots": _arr(
            _obj(
                {
                    "id": _STR,
                    "role": {"type": "string", "description": "project or library"},
                    "recursive": _BOOL,
                    "state": {
                        "type": "string",
                        "description": "building, ready or unavailable (an open set)",
                    },
                    "index_partial": _BOOL,
                    "documents": _INT_N,
                }
            )
        )
    }
)
_SERVE_STARTED_SCHEMA = _obj(
    {
        "host": _STR,
        "port": _INT,
        "url": _STR,
        "roots": _arr(_STR),
        "workers": _INT,
        "auth": {"type": "string", "description": "bearer (an open set)"},
        "token_file_created": _BOOL,
    }
)
_LISTING_SCHEMA = _obj(
    {
        "root": _STR_N,
        "folder": _STR,
        "recursive": _BOOL,
        "include": _arr({"enum": list(LISTING_PARTS)}),
        "entries": _arr(_ref("listing_entry")),
        "counts": _obj(
            {
                "entries": _INT,
                "ok": _INT,
                "error": _INT,
                "skipped": _INT,
                "link": _INT,
                "placeholder": _INT,
                "not_solidworks": _INT,
                "unsupported": _INT,
                "folders": _INT,
            }
        ),
        "truncated": _BOOL,
        "truncated_reason": _STR_N,
        "next_cursor": _STR_N,
        "preview_data_capped": _BOOL,
    }
)
_COMPONENTS_SCHEMA = _obj(
    {
        "configuration": _STR_N,
        "configuration_source": {
            "type": "string",
            "description": "requested, active, most_recent, first or none (an open set)",
        },
        "configurations_described": _arr(_STR),
        "children_state": {"type": "string", "description": "described, unknown or none (an open set)"},
        "truncated": _BOOL,
        "limits": _obj({"max_nodes": _INT, "max_depth": _INT}),
        "counts": _obj({"nodes": _INT, "depth": _INT, "files": _INT}),
        "files": _arr(_ref("component_file")),
        "children": _arr(_ref("component_node"), nullable=True),
        "instances": _arr(_ref("component_node"), nullable=True),
        "warnings": _arr(_ref("warning")),
    }
)
_REFERENCES_SCHEMA = _obj(
    {
        "configuration": _STR_N,
        "configuration_source": _COMPONENTS_SCHEMA["properties"]["configuration_source"],
        "configurations_described": _arr(_STR),
        "children_state": _COMPONENTS_SCHEMA["properties"]["children_state"],
        "truncated": _BOOL,
        "files": _arr(_ref("component_file")),
        "sheets": _arr(_ref("drawing_sheet"), nullable=True),
        "resolution": _ref("resolution_summary"),
        "warnings": _arr(_ref("warning")),
    }
)
_DEFS["bom_row"] = _obj(
    {
        "item": {"type": "string", "description": "the item number as SOLIDWORKS writes it: 3, 3.1..."},
        "level": _INT,
        "parent": _STR_N,
        "part_number": _STR,
        "part_number_source": {"type": "string", "description": "document_name or property (an open set)"},
        "alternate_name": {
            "type": ["string", "null"],
            "description": "the alternate name the assembly stores for the row's configuration, which "
            "SOLIDWORKS may show as the part number (note bom_part_number_may_differ); null when none",
        },
        "description": _STR_N,
        "quantity": _INT,
        "total_quantity": _INT,
        "file": _STR_N,
        "file_name": _STR_N,
        "stored_path": _STR_N,
        "doc_type": _STR_N,
        "configuration": _STR_N,
        "virtual": _BOOL,
        "imported": _BOOL,
        "instances": _arr(_STR),
        "resolution": {
            "type": ["string", "null"],
            "description": "the file's resolution status, or embedded, embedded_in_subassembly or "
            "embedded_not_found for a document stored inside an assembly (an open set)",
        },
        "location": _ref_n("location"),
        "nested": _arr(_STR),
        "properties": _arr(_ref("property"), nullable=True),
        "values": _arr(_STR_N),
        "notes": _arr(_ref("warning")),
    },
    description="quantity: per one instance of the parent assembly (the QTY. column); total_quantity: in "
    "the whole assembly. properties null: the file was not read (notes say why).",
)
_BOM_SCHEMA = _obj(
    {
        "type": {"type": "string", "description": "top, parts or indented"},
        "configuration": _STR_N,
        "configuration_source": _COMPONENTS_SCHEMA["properties"]["configuration_source"],
        "children_state": _COMPONENTS_SCHEMA["properties"]["children_state"],
        "columns": _arr(_STR),
        "property_columns": _arr(_STR),
        "part_number_property": _STR_N,
        "read_properties": _BOOL,
        "rows": _arr(_ref("bom_row")),
        "truncated": _BOOL,
        "complete": _BOOL,
        "counts": _obj(
            {
                "rows": _INT,
                "instances": _INT,
                "files": _INT,
                "read": _INT,
                "unread": _INT,
                "files_opened": _INT,
            }
        ),
        "limits": _obj(
            {
                "max_instances": _INT,
                "max_depth": _INT,
                "max_files": _INT,
                "max_seconds": {"type": "number"},
                "max_file_bytes": _INT_N,
            },
            nullable=True,
        ),
        "resolution": _ref("resolution_summary"),
        "warnings": _arr(_ref("warning")),
    }
)
_DEFS["path_location"] = _obj(
    {"nested": _arr(_STR), "stream": _STR_N},
    description="nested: the chain of nested-document streams from the top document, outermost first; "
    "empty for the file itself.",
)
_OPEN_SEVERITY = {"type": "string", "description": "high, medium or low (an open set)"}
_PATH_REPORT_SCHEMA = _obj(
    {
        "complete": _BOOL,
        "incomplete": _arr(
            _obj(
                {
                    "reason": {
                        "type": "string",
                        "description": "stream_over_cap, stream_unreadable, carrier_unreadable, "
                        "nested_unreadable, path_limit, document_limit or byte_limit (an open set)",
                    },
                    "nested": _arr(_STR),
                    "stream": _STR_N,
                }
            )
        ),
        "counts": _obj(
            {
                "paths": _INT,
                "accounts": _INT,
                "hosts": _INT,
                "identity_fields": _INT,
                "documents": _INT,
                "by_category": {
                    "type": "object",
                    "description": "paths per category: " + ", ".join(CATEGORIES) + " (an open set)",
                    "additionalProperties": _INT,
                },
                "by_role": {
                    "type": "object",
                    "description": "paths per role: " + ", ".join(ROLES) + " (an open set)",
                    "additionalProperties": _INT,
                },
            }
        ),
        "documents": _arr(
            _obj(
                {
                    "nested": _arr(_STR),
                    "doc_type": {"enum": ["part", "assembly", "drawing", None]},
                    "streams": _INT,
                    "streams_scanned": _INT,
                    "bytes_scanned": _INT,
                }
            )
        ),
        "accounts": _arr(
            _obj(
                {
                    "name": _STR,
                    "severity": _OPEN_SEVERITY,
                    "sources": _arr(_STR),
                    "paths": _INT,
                    "identity_fields": _INT,
                    "history_only": _BOOL,
                    "inherited_likely": _BOOL,
                }
            )
        ),
        "hosts": _arr(_obj({"host": _STR, "shares": _arr(_STR), "severity": _OPEN_SEVERITY, "paths": _INT})),
        "identity_fields": _arr(
            _obj(
                {
                    "field": {
                        "type": "string",
                        "description": "header2_user, core_last_modified_by, core_creator, sw_author, "
                        "sw_last_saved_by, summary_author, summary_last_author or file_name_at_save "
                        "(an open set)",
                    },
                    "value": _STR,
                    "current": _BOOL,
                    "nested": _arr(_STR),
                    "stream": _STR_N,
                }
            )
        ),
        "paths": _arr(
            _obj(
                {
                    "path": _STR,
                    "category": {"type": "string", "description": ", ".join(CATEGORIES) + " (an open set)"},
                    "severity": _OPEN_SEVERITY,
                    "reason": {
                        "type": "string",
                        "description": "unc_share, referenced_document, save_location, folder_names, "
                        "account_name, inherited_template, profile_folder or standard_folder (an open set)",
                    },
                    "account": _STR_N,
                    "host": _STR_N,
                    "share": _STR_N,
                    "roles": _arr({"type": "string", "description": ", ".join(ROLES) + " (an open set)"}),
                    "sources": _arr(_STR),
                    "locations": _arr(_ref("path_location")),
                    "history_only": _BOOL,
                    "inherited_likely": _BOOL,
                }
            )
        ),
        "rewrite": _obj({"supported": {"const": False}, "note": _STR}),
        "warnings": _arr(_ref("warning")),
    }
)
_COMPONENT_DEFS = (
    "component_file",
    "configuration_counts",
    "reference_resolution",
    "location",
    "resolution_candidate",
    "component_node",
    "transform",
    "placement",
    "warning",
)
_STREAMS_SCHEMA = _obj(
    {
        "format": {"enum": ["modern", "ole"]},
        "streams": _arr(
            _obj({"name": _STR, "size": _INT, "compressed_size": _INT_N, "codec": _STR}),
        ),
    }
)
_FILE_WRITTEN_SCHEMA = _obj(
    {
        "output": _STR,
        "bytes": _INT,
        "stream": _STR_N,
        "raw": _BOOL_N,
        "mime": _STR_N,
        "width": _INT_N,
        "height": _INT_N,
        "source": {
            "type": ["string", "null"],
            "description": "stored or rendered for a preview, the backend for convert (an open set)",
        },
    }
)
_PARASOLID_SCHEMA = _obj(
    {
        "bodies": _INT,
        "written": _arr(
            _obj(
                {
                    "output": _STR,
                    "kind": {"enum": ["x_b", "x_t", "p_b", "d_b"]},
                    "bytes": _INT,
                    "body": _STR_N,
                    "configuration": _STR_N,
                    "configuration_id": _INT_N,
                    "source": _STR_N,
                    "body_type": _STR_N,
                    "schema": _STR_N,
                    "valid": _BOOL_N,
                    "transmit": _STR_N,
                }
            )
        ),
        "problems": _arr(_obj({"stream": _STR_N, "block": _INT_N, "feature": _STR_N, "error": _STR})),
        "assembly": _obj(
            {
                "name": _STR,
                "configuration": _STR_N,
                "counts": {"type": "object", "additionalProperties": _INT},
                "instances": _arr(
                    _obj({"id": _STR, "name": _STR, "file": _STR_N, "configuration": _STR_N, "bodies": _INT})
                ),
                "skipped": _arr(
                    _obj({"id": _STR, "name": _STR, "file": _STR_N, "reason": _STR, "message": _STR})
                ),
                "warnings": _arr(_ref("warning")),
                "seconds": {"type": "number"},
            },
            nullable=True,
            description="an assembly's one transmit: what it places and leaves out (null for a part)",
        ),
    }
)
_NUM_N = {"type": ["number", "null"]}
_STEP_SCHEMA = _obj(
    {
        "schema": {"type": "string", "description": "AP214"},
        "exact": _BOOL,
        "partial": _BOOL,
        "uncertainty_mm": _NUM,
        "max_deviation_mm": _NUM_N,
        "max_tolerance_mm": _NUM_N,
        "max_gap_mm": _NUM_N,
        "approximated": _obj(
            {"faces": _INT, "edges": _INT, "by_class": {"type": "object", "additionalProperties": _INT}}
        ),
        "bodies": _arr(
            _obj(
                {
                    "product": _INT,
                    "name": _STR,
                    "configuration": _STR_N,
                    "kind": {"type": "string", "description": "solid, sheet, wire or general (an open set)"},
                    "source": {"type": "string", "description": "partition, local-bodies or transmit"},
                    "faces": _INT,
                    "edges": _INT,
                    "vertices": _INT,
                    "split_faces": {
                        "type": "integer",
                        "description": "the body's faces written as two, cut at their seams",
                    },
                    "approximated_faces": _INT,
                    "approximated_edges": _INT,
                    "max_deviation_mm": _NUM_N,
                    "max_tolerance_mm": _NUM_N,
                    "written": _BOOL,
                    "reason": {"type": ["string", "null"], "description": "why not written (an open set)"},
                    "message": _STR_N,
                }
            )
        ),
    },
    nullable=True,
    description="a STEP export's own results; null for 3MF and STL",
)
_EXPORT_SCHEMA = _obj(
    {
        "output": _STR,
        "format": {"type": "string", "description": "3mf, stl or step (an open set)"},
        "mime": _STR_N,
        "bytes": _INT,
        "merged": _BOOL,
        "name": _STR,
        "doc_type": {"type": "string", "description": "part or assembly"},
        "configuration": _STR_N,
        "chord_mm": {
            "type": ["number", "null"],
            "description": "the chord tolerance asked for; null: each part's automatic print chord",
        },
        "closed": _BOOL,
        "counts": {"type": "object", "additionalProperties": _INT},
        "objects": _arr(
            _obj(
                {
                    "name": _STR,
                    "file": _STR_N,
                    "configuration": _STR_N,
                    "source": {
                        "type": "string",
                        "description": "bodies, display_mesh or mesh (an open set)",
                    },
                    "vertices": _INT,
                    "triangles": _INT,
                    "instances": _INT,
                    "closed": _BOOL,
                    "chord_mm": {"type": ["number", "null"]},
                    "volume_mm3": {"type": "number"},
                    "area_mm2": {"type": "number"},
                    "warnings": _arr(_ref("warning")),
                }
            )
        ),
        "skipped": _arr(_obj({"id": _STR, "name": _STR, "file": _STR_N, "reason": _STR, "message": _STR})),
        "warnings": _arr(_ref("warning")),
        "seconds": {"type": "number"},
        "step": _STEP_SCHEMA,
        "source_format": {
            "type": "string",
            "description": "the format id of the file exported: solidworks, stl, 3mf, step... (an open set)",
        },
        "check": _obj(
            {
                "sound": {
                    "type": "boolean",
                    "description": "Open CASCADE read every root into what was written, closed and valid",
                },
                "findings": _arr(_STR),
                "occt": _STR_N,
                "roots": _INT_N,
                "roots_transferred": _INT_N,
                "shapes": _INT_N,
                "solids": _INT_N,
                "sheets": _INT_N,
                "free_faces": _INT_N,
                "faces": _INT_N,
                "open_solid_shells": _INT_N,
                "free_edges": _INT_N,
                "nonmanifold_edges": _INT_N,
                "valid": _BOOL_N,
                "volume_mm3": _NUM_N,
                "area_mm2": _NUM_N,
                "box_mm": _arr(_NUM, nullable=True),
            },
            nullable=True,
            description="what Open CASCADE made of a STEP file read back (export --check); null otherwise",
        ),
    }
)
_SLDPRT_WRITTEN_SCHEMA = _obj(
    {
        "output": _STR,
        "bytes": _INT,
        "design": _obj(
            {
                "name": _STR,
                "format": {"type": "string", "description": "solidcraft, ir or cadquery (an open set)"},
            }
        ),
        "features": _arr(_obj({"id": _STR, "name": _STR, "part_name": _STR})),
        "properties": _arr(
            _obj(
                {
                    "name": _STR,
                    "type": {"type": "string", "description": "text, number, date or yesno"},
                    "value": {"type": ["string", "number", "boolean"]},
                }
            )
        ),
        "left_out": _arr(_STR),
        "unsupported": _arr(_STR),
        "partial": _BOOL,
    }
)
_BATCH_SCHEMA = _obj(
    {
        "files": _INT,
        "status_counts": {"type": "object", "additionalProperties": _INT},
        "report_csv": _STR,
        "report_jsonl": _STR,
        "previews": _INT,
        "parasolid_files": _INT,
        "parasolid_left_out": _INT,
        "walk": _ref("walk"),
    }
)


_DOC_TYPE = {"enum": ["part", "assembly", "drawing", None]}
_CATALOG_ROOT = _obj(
    {
        "id": _STR,
        "path": {
            "type": ["string", "null"],
            "description": "Python and the command line only; null from REST.",
        },
        "role": _STR,
        "recursive": _BOOL,
        "state": {"type": "string", "description": "new, ready, partial or unavailable (an open set)"},
        "partial": _STR_N,
        "hash_policy": {
            "type": ["string", "null"],
            "description": "all, duplicates or none: what the root's last scan hashed",
        },
        "last_scan_utc": _STR_N,
        "last_complete_scan_utc": _STR_N,
        "documents": _INT,
        "files": _INT,
    }
)
_CATALOG_SCHEMA = _obj(
    {
        "name": _STR,
        "location": {"type": "string", "description": "cache, project or file"},
        "schema_version": _INT,
        "state": {"type": "string", "description": "empty, scanning, ready or partial (an open set)"},
        "search_engine": {"type": "string", "description": "fts5 or like"},
        "hash_policy": _STR_N,
        "part_number_property": _STR_N,
        "formats": {"type": "array", "items": _STR, "description": "the format ids the catalog indexes"},
        "last_scan": _obj(
            {"id": _INT, "started_utc": _STR, "finished_utc": _STR_N, "state": _STR}, nullable=True
        ),
        "roots": _arr(_CATALOG_ROOT),
        "counts": _obj(
            {
                **{
                    k: _INT
                    for k in (
                        "files",
                        "documents",
                        "parts",
                        "assemblies",
                        "drawings",
                        "pending",
                        "read_errors",
                        "quarantined",
                        "not_solidworks",
                        "placeholders",
                        "stale",
                        "resolve_pending",
                        "hash_pending",
                    )
                },
                "formats": {
                    "type": "object",
                    "additionalProperties": _INT,
                    "description": "documents read, by format id",
                },
                "references": {"type": "object", "additionalProperties": _INT},
                "references_unresolved": _INT,
                "duplicate_groups": _INT,
            }
        ),
        "sizes": _obj({"catalog_bytes": _INT_N, "previews_bytes": _INT_N}),
    }
)
_CATALOG_LIST_SCHEMA = _obj(
    {
        "cache_dir": _STR,
        "catalogs": _arr(
            _obj(
                {
                    "name": _STR,
                    "folder": _STR,
                    "roots": _arr(_obj({"id": _STR, "path": _STR, "role": _STR})),
                    "last_scan_utc": _STR_N,
                    "last_scan_state": _STR_N,
                    "catalog_bytes": _INT_N,
                    "previews_bytes": _INT_N,
                    "error": _STR_N,
                }
            )
        ),
    }
)
_CATALOG_CLEARED_SCHEMA = _obj({"catalogs": _arr(_STR), "files": _arr(_STR)})
_SCAN_COUNTS = (
    "seen",
    "added",
    "changed",
    "unchanged",
    "moved",
    "removed",
    "stale",
    "read_ok",
    "read_errors",
    "not_solidworks",
    "pending",
    "hashed",
    "hash_pending",
    "resolved_documents",
)
_CATALOG_SCAN_SCHEMA = _obj(
    {
        "catalog": _STR,
        "scan": _INT,
        "state": {"type": "string", "description": "done, cancelled, truncated or failed"},
        "roots": _arr(
            _obj(
                {
                    "id": _STR,
                    "state": {"type": "string", "description": "ready, partial, unavailable or not_scanned"},
                    "entries": _INT,
                    "documents": _INT,
                    "truncated_reason": _STR_N,
                }
            )
        ),
        "removed_roots": _arr(_STR),
        "counts": _obj({k: _INT for k in _SCAN_COUNTS}),
        "seconds": _obj({k: _NUM for k in ("walk", "read", "resolve", "hash", "total")}),
        "errors": _arr(_obj({"root": _STR_N, "path": _STR, "error": _ref("error")})),
        "truncated": _BOOL,
        "truncated_reason": _STR_N,
        "cancelled": _BOOL,
    }
)
_CATALOG_FILE = {
    "root": _STR,
    "path": _STR,
    "name": _STR,
    "doc_type": _DOC_TYPE,
    "format": {
        "type": ["string", "null"],
        "description": (
            "the format id the file was read as (solidworks for a SOLIDWORKS document), else the one "
            "its extension names"
        ),
    },
}
_WHERE_USED_SCHEMA = _obj(
    {
        "target": _obj(
            {**_CATALOG_FILE, "state": _STR, "configurations": _arr(_STR), "sha256": _STR_N},
        ),
        "configuration": _STR_N,
        "indirect": _BOOL,
        "as_of": _STR_N,
        "complete": _BOOL,
        "users": _arr(
            _obj(
                {
                    **_CATALOG_FILE,
                    "depth": _INT,
                    "relation": {
                        "type": "string",
                        "description": (
                            "component, drawing_view, drawing_of_assembly or stored_tree (an open set)"
                        ),
                    },
                    "via": _arr(_obj({"root": _STR_N, "path": _STR_N, "name": _STR, "stored": _BOOL})),
                    "uses": _arr(
                        _obj(
                            {
                                "user_configuration": _STR_N,
                                "configuration": _STR_N,
                                "via_configurations": _arr(_STR_N),
                                "instances": _INT,
                                "unsuppressed": _INT,
                                "in_bom": _INT,
                            }
                        )
                    ),
                    "views": _arr(_obj({"sheet": _STR_N, "view": _STR_N, "configuration": _STR_N})),
                    "resolution": _obj(
                        {"key": _STR, "status": _STR, "rule": _STR_N, "confidence": _STR, "identity": _STR},
                        nullable=True,
                    ),
                    "warnings": _arr(_ref("warning")),
                }
            )
        ),
        "possible": _arr(
            _obj(
                {
                    **_CATALOG_FILE,
                    "key": _STR,
                    "file_name": _STR_N,
                    "stored_path": _STR_N,
                    "status": _STR,
                    "candidates": _arr(_obj({"root": _STR, "path": _STR})),
                }
            )
        ),
        "name_matches": _arr(
            _obj({**_CATALOG_FILE, "key": _STR, "file_name": _STR_N, "stored_path": _STR_N, "status": _STR})
        ),
        "counts": _obj(
            {k: _INT for k in ("users", "direct", "indirect", "drawings", "possible", "name_matches")}
        ),
        "truncated": _BOOL,
        "warnings": _arr(_ref("warning")),
    }
)
_CATALOG_SEARCH_SCHEMA = _obj(
    {
        "query": _STR,
        "engine": {"type": "string", "description": "fts5 or like"},
        "sort": {"type": "string", "description": "relevance, name or modified"},
        "results": _arr(
            _obj(
                {
                    **_CATALOG_FILE,
                    "modified_utc": _STR_N,
                    "size": _INT_N,
                    "state": _STR,
                    "configuration": _STR_N,
                    "part_number": _STR_N,
                    "description": _STR_N,
                    "matched": _arr(_STR),
                }
            )
        ),
        "next_cursor": _STR_N,
        "truncated": _BOOL,
    }
)
_DUPLICATE_FILE = {"root": _STR, "path": _STR, "name": _STR, "modified_utc": _STR_N}
_DUPLICATES_SCHEMA = _obj(
    {
        "groups": _arr(
            _obj({"sha256": _STR, "size": _INT_N, "wasted_bytes": _INT, "files": _arr(_obj(_DUPLICATE_FILE))})
        ),
        "name_groups": _arr(
            _obj(
                {
                    "name": _STR,
                    "versions": _INT,
                    "files": _arr(_obj({**_DUPLICATE_FILE, "sha256": _STR_N, "size": _INT_N})),
                }
            ),
            nullable=True,
        ),
        "counts": _obj({"groups": _INT, "files": _INT, "wasted_bytes": _INT, "name_groups": _INT_N}),
        "hash_pending": _INT,
        "next_cursor": _STR_N,
    }
)
_MISSING_SCHEMA = _obj(
    {
        "documents": _arr(
            _obj(
                {
                    **_CATALOG_FILE,
                    "references": _arr(
                        _obj(
                            {
                                "key": _STR,
                                "file_name": _STR_N,
                                "stored_path": _STR_N,
                                "status": _STR_N,
                                "rule": _STR_N,
                                "confidence": _STR_N,
                                "identity": _STR_N,
                                "candidates": _arr(
                                    _obj({"root": _STR, "path": _STR, "found_by": _STR, "identity": _STR})
                                ),
                                "name_matches": _INT,
                                "warnings": _arr(_ref("warning")),
                            }
                        )
                    ),
                }
            )
        ),
        "counts": _obj(
            {k: _INT for k in ("documents", "missing", "ambiguous", "embedded_not_found", "low_confidence")}
        ),
        "within_roots": _BOOL,
        "next_cursor": _STR_N,
    }
)
_CHANGES_SCHEMA = _obj(
    {
        "since": _STR_N,
        "events": _arr(
            _obj(
                {
                    "time_utc": _STR,
                    "scan": _INT,
                    "kind": {"type": "string", "description": "added, changed, moved, removed or read_error"},
                    "root": _STR_N,
                    "path": _STR_N,
                    "previous_root": _STR_N,
                    "previous_path": _STR_N,
                    "size": _INT_N,
                    "sha256": _STR_N,
                    "previous_sha256": _STR_N,
                }
            )
        ),
        "next_cursor": _STR_N,
    }
)

_SHA256 = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_DRAWING_SCHEMA = _obj(
    {
        "action": {"enum": list(DRAWING_ACTIONS)},
        "dry_run": _BOOL,
        "drawing": _obj(
            {
                "id": _STR,
                "status": {"enum": ["PRELIMINARY", "CHECKED", "RELEASED"]},
                "revision": _STR_N,
                "title": {
                    "type": "object",
                    "description": "title fields by key (title, number, part_number, revision, material...)",
                    "additionalProperties": _obj(
                        {"text": _STR, "from": {"type": "string", "description": "part, list or typed"}}
                    ),
                },
                "signatures": _arr(_obj({"row": _STR, "name": _STR, "date": _STR, "current": _BOOL})),
                "revisions": _arr(
                    _obj(
                        {
                            "rev": _STR,
                            "description": _STR,
                            "zones": _arr(_STR),
                            "date": _STR_N,
                            "approved": _STR_N,
                        }
                    )
                ),
                "model": _obj(
                    {
                        "name": _STR_N,
                        "format": {
                            "type": ["string", "null"],
                            "description": "sldprt for a part, sldasm for an assembly (an open set)",
                        },
                        "configuration": _STR_N,
                        "sha256": _STR_N,
                        "unit": _STR_N,
                        "unit_origin": {
                            "type": ["string", "null"],
                            "description": "file, guessed or user (an open set)",
                        },
                    }
                ),
                "options": _obj(
                    {
                        "process": _STR,
                        "scheme": _STR,
                        "detail": _STR,
                        "units": _STR,
                        "views": _arr(_STR),
                        "sheet": _STR,
                        "scale": _STR,
                    }
                ),
                "counts": _obj(
                    {
                        "features": _INT,
                        "dimensions": _INT,
                        "shown": _INT,
                        "removed": _INT,
                        "needs_attention": _INT,
                        "notes": _INT,
                        "views": _INT,
                        "items": _INT,
                        "balloons": _INT,
                        "sheets": {
                            "type": "integer",
                            "description": "the drawing's sheets: 1, more when its parts list goes on "
                            "past the first, 0 when it has no laid-out sheet",
                        },
                    }
                ),
                "outputs": _arr(
                    _obj({"kind": _STR, "name": _STR, "sha256": _STR, "revision": _STR, "released": _BOOL})
                ),
                "created": _STR_N,
                "modified": _STR_N,
            },
            nullable=True,
            description="the drawing's summary; null for the settings action",
        ),
        "files": _arr(
            _obj(
                {
                    "path": _STR,
                    "name": _STR,
                    "kind": {"enum": list(DRAWING_FILE_KINDS)},
                    "sha256": _SHA256,
                    "bytes": _INT,
                    "replaced": _BOOL,
                    "renamed": _BOOL,
                    "released": _BOOL,
                }
            )
        ),
        "merge": _obj(
            {
                "words": _STR,
                "unchanged": _INT,
                "changed": _INT,
                "new": _INT,
                "dropped": _INT,
                "needs_attention": _INT,
                "forgotten": _INT,
                "model_unchanged": _BOOL,
                "geometry_unchanged": _BOOL,
                "features": _obj(
                    {"matched": _INT, "resized": _arr(_STR), "gone": _arr(_STR), "new": _arr(_STR)}
                ),
                "items": _arr(_STR),
            },
            nullable=True,
            description="the merge report of an update (MergeReport.to_dict()); null otherwise",
        ),
        "checks": _arr(
            _obj(
                {
                    "code": _STR,
                    "level": {"type": "string", "description": "error, warning or information"},
                    "item": _STR,
                    "message": _STR,
                    "fixes": _arr(_STR),
                }
            )
        ),
        "check_counts": _obj({"error": _INT, "warning": _INT, "information": _INT}),
        "coverage": _obj(
            {
                "complete": _BOOL,
                "words": _STR,
                "features": _INT,
                "features_unclaimed": _INT,
                "faces": _INT,
                "faces_claimed": _INT,
                "area_mm2": _NUM,
                "area_claimed_mm2": _NUM,
                "area_fraction": _NUM_N,
            },
            nullable=True,
            description="null for a drawing read from a file, which does not store it",
        ),
        "thread_candidates": _arr(
            _obj(
                {
                    "feature": _STR,
                    "kind": {"enum": ["hole", "pattern"]},
                    "count": _INT,
                    "diameter_mm": _NUM,
                    "threads": _arr(_STR),
                    "answered": _BOOL,
                    "confirmed": _STR_N,
                }
            )
        ),
        "seconds": {
            "type": "object",
            "description": "seconds per stage, in the order the stages ran",
            "additionalProperties": _NUM,
        },
        "warnings": _arr(_STR),
        "settings": _obj(
            {
                "path": _STR_N,
                "found": _BOOL,
                "values": {"type": "object", "description": "every value, as Drawing.json holds it"},
                "fallbacks": _arr(_STR),
                "first_use": _arr(_STR),
            },
            nullable=True,
        ),
        "model_check": _obj(
            {
                "path": _STR,
                "verified": _BOOL,
                "sha256_matches": _BOOL,
                "geometry_matches": _BOOL_N,
                "reference_matches": _BOOL,
                "words": _STR,
            },
            nullable=True,
            description="check --model: the model file against the drawing's MODEL reference",
        ),
    }
)

# --------------------------------------------------------------------------- versions (provisional)
# docs/VERSIONS.md and docs/API.md 5.19: a file's history, a snapshot taken, and the
# differences between two versions.
_SHA256_N = {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"}
_DEFS["version"] = _obj(
    {
        "number": _INT,
        "id": _STR,
        "kind": {"type": "string", "description": "commit, snapshot or working (an open set)"},
        "status": {"type": ["string", "null"], "description": "a commit's: added, modified or deleted"},
        "time_utc": _STR_N,
        "authored_utc": _STR_N,
        "author": _STR_N,
        "subject": _STR_N,
        "size": _INT_N,
        "sha256": _SHA256_N,
        "git_blob": _STR_N,
        "lfs": _obj({"oid": _SHA256, "size": _INT}, nullable=True),
        "available": _BOOL,
    },
    description="One version of a file: a commit that changed it, a snapshot, or the working copy.",
)
_DEFS["versioned_file"] = _obj({"name": _STR, "path": _STR})
_DEFS["geometry_summary"] = _obj(
    {
        "stored": _BOOL,
        "bodies": _obj({k: _INT for k in ("solid", "sheet", "wire", "general")}, nullable=True),
        "hidden_bodies": _INT_N,
        "faces": _INT_N,
        "edges": _INT_N,
        "vertices": _INT_N,
        "triangles": _INT_N,
        "fingerprint": _SHA256_N,
        "measures": _obj(
            {
                "measured": _BOOL,
                "reason": _STR_N,
                "volume_mm3": _NUM_N,
                "area_mm2": _NUM_N,
                "box_mm": _obj(
                    {"min": _arr(_NUM), "max": _arr(_NUM), "size": _arr(_NUM)},
                    nullable=True,
                ),
                "closed": _BOOL_N,
                "complete": _BOOL,
                "chord_mm": _NUM_N,
            },
            nullable=True,
        ),
    },
    nullable=True,
)
_FILE_HISTORY_SCHEMA = _obj(
    {
        "file": _ref("versioned_file"),
        "source": {"type": "string", "description": "git or snapshots"},
        "git": _obj(
            {
                "work_tree": _STR,
                "path": _STR,
                "branch": _STR_N,
                "head": _STR_N,
                "object_format": _STR,
                "shallow": _BOOL,
                "partial": _BOOL,
                "commits_walked": _INT,
            },
            nullable=True,
        ),
        "store": _obj({"location": _STR, "path": _STR}, nullable=True),
        "working": _obj(
            {
                "state": {"type": "string", "description": "unchanged, changed, new or missing"},
                "size": _INT_N,
                "modified_utc": _STR_N,
                "mtime_ns": {"type": ["string", "null"], "pattern": "^-?[0-9]+$"},
                "sha256": _SHA256_N,
            }
        ),
        "versions": _arr(_ref("version")),
        "truncated": _BOOL,
        "warnings": _arr(_ref("warning")),
    }
)
_SNAPSHOT_TAKEN_SCHEMA = _obj(
    {
        "file": _ref("versioned_file"),
        "store": _obj({"location": _STR, "path": _STR}),
        "new": _BOOL,
        "snapshot": _ref_n("version"),
        "versions": _INT,
    }
)
_DEFS["document_brief"] = _obj(
    {"format": _STR_N, "type": _STR_N, "saved_version": _STR_N, "configurations": _INT, "properties": _INT}
)
_VERSION_DIFF_SCHEMA = _obj(
    {
        "file": _ref("versioned_file"),
        "source": _STR,
        "from": _ref("version"),
        "to": _ref("version"),
        "same_content": _BOOL,
        "document": _obj(
            {
                "from": _ref("document_brief"),
                "to": _ref("document_brief"),
                "changes": _arr(_obj({"field": _STR, "configuration": _STR_N, "from": _STR_N, "to": _STR_N})),
            }
        ),
        "properties": _obj(
            {
                k: _arr(
                    _obj(
                        {
                            "configuration": _STR_N,
                            "name": _STR,
                            "from": _ref_n("property"),
                            "to": _ref_n("property"),
                        }
                    )
                )
                for k in ("added", "removed", "changed")
            }
        ),
        "configurations": _obj(
            {"added": _arr(_STR), "removed": _arr(_STR), "active": _obj({"from": _STR_N, "to": _STR_N})}
        ),
        "geometry": _obj(
            {
                "compared": _BOOL,
                "reason": _STR_N,
                "configurations": _arr(
                    _obj(
                        {
                            "configuration": _STR_N,
                            "status": {
                                "type": "string",
                                "description": "unchanged, changed, added, removed, not_stored or "
                                "not_compared",
                            },
                            "from": _ref("geometry_summary"),
                            "to": _ref("geometry_summary"),
                            "changes": _arr(_obj({"measure": _STR, "from": _NUM, "to": _NUM})),
                        }
                    )
                ),
            }
        ),
        "warnings": _arr(_ref("warning")),
    }
)


@dataclass(frozen=True)
class KindSpec:
    """One JSON kind: the shape of ``data`` in an envelope with this ``kind``."""

    name: str
    schema_version: int
    title: str
    schema: dict[str, Any]
    build: Callable[..., Any]
    cli_commands: tuple[str, ...]  # the CLI commands that print it under --json
    rest_route: str | None  # the REST route that answers with it
    # Another kind the same command and route print for another kind of file: model_summary
    # stands in for document_summary when the file is not a SOLIDWORKS document.
    alternate_of: str | None = None


def _kind(
    name: str,
    title: str,
    body: dict[str, Any],
    defs: tuple[str, ...],
    build: Callable[..., Any],
    cli: tuple[str, ...],
    route: str | None,
    version: int = 1,
    alternate_of: str | None = None,
) -> KindSpec:
    return KindSpec(
        name, version, title, _schema(name, version, title, body, defs), build, cli, route, alternate_of
    )


_SUMMARY_DEFS = (
    "file",
    "saved_version",
    "material",
    "property",
    "configuration",
    "units",
    "fields",
    "preview",
    "counts",
    "warning",
)

KINDS: dict[str, KindSpec] = {
    k.name: k
    for k in (
        _kind(
            "document_summary",
            "SolidSeas document summary",
            _SUMMARY_SCHEMA,
            _SUMMARY_DEFS,
            build_document_summary,
            ("info",),
            "/v1/document",
        ),
        _kind(
            "model_summary",
            "SolidSeas model file summary",
            _MODEL_SUMMARY_SCHEMA,
            (
                "file",
                "fields",
                "property",
                "model_units",
                "model_application",
                "model_counts",
                "model_node",
                "model_reference",
                "model_preview",
                "placement",
                "warning",
            ),
            build_model_summary,
            ("info",),
            "/v1/document",
            alternate_of="document_summary",
        ),
        _kind(
            "properties",
            "SolidSeas custom properties",
            _PROPERTIES_SCHEMA,
            ("property", "warning"),
            build_properties,
            ("props",),
            "/v1/properties",
        ),
        _kind(
            "configurations",
            "SolidSeas configurations",
            _CONFIGURATIONS_SCHEMA,
            ("configuration", "property", "material", "warning"),
            build_configurations,
            ("configurations",),
            "/v1/configurations",
        ),
        _kind(
            "listing",
            "SolidSeas folder listing",
            _LISTING_SCHEMA,
            (
                "listing_entry",
                "file",
                "saved_version",
                "configuration",
                "property",
                "material",
                "listing_preview",
                "listing_model",
                "model_units",
                "model_counts",
                "model_application",
                "warning",
                "error",
            ),
            build_listing,
            ("list",),
            "/v1/list",
        ),
        _kind(
            "components",
            "SolidSeas component tree",
            _COMPONENTS_SCHEMA,
            _COMPONENT_DEFS,
            build_components,
            ("components",),
            "/v1/components",
        ),
        _kind(
            "references",
            "SolidSeas referenced files",
            _REFERENCES_SCHEMA,
            (*_COMPONENT_DEFS, "drawing_sheet", "resolution_summary"),
            build_references,
            ("references",),
            "/v1/references",
        ),
        _kind(
            "bom",
            "SolidSeas bill of materials",
            _BOM_SCHEMA,
            ("bom_row", "location", "property", "resolution_summary", "warning"),
            build_bom,
            ("bom",),
            "/v1/bom",
        ),
        _kind(
            "path_report",
            "SolidSeas path-leak report",
            _PATH_REPORT_SCHEMA,
            ("path_location", "warning"),
            build_path_report,
            ("paths",),
            "/v1/path-report",
        ),
        _kind("streams", "SolidSeas streams", _STREAMS_SCHEMA, (), build_streams, ("streams",), None),
        _kind(
            "file_written",
            "SolidSeas file written",
            _FILE_WRITTEN_SCHEMA,
            (),
            build_file_written,
            ("dump", "preview", "convert"),
            None,
        ),
        _kind(
            "parasolid_result",
            "SolidSeas Parasolid export",
            _PARASOLID_SCHEMA,
            ("warning",),
            build_parasolid_result,
            ("parasolid",),
            None,
        ),
        _kind(
            "export_result",
            "SolidSeas export for 3D printing",
            _EXPORT_SCHEMA,
            ("warning",),
            build_export_result,
            ("export",),
            None,
        ),
        _kind(
            "sldprt_written",
            "SolidSeas native part written",
            _SLDPRT_WRITTEN_SCHEMA,
            (),
            build_sldprt_written,
            ("sldprt",),
            None,
        ),
        _kind(
            "batch_summary",
            "SolidSeas batch run",
            _BATCH_SCHEMA,
            ("walk",),
            build_batch_summary,
            ("batch",),
            None,
        ),
        _kind(
            "version", "SolidSeas version", _VERSION_SCHEMA, (), build_version, ("version",), "/v1/version"
        ),
        _kind("health", "SolidSeas service health", _HEALTH_SCHEMA, (), build_health, (), "/v1/health"),
        _kind(
            "identity", "SolidSeas service identity", _IDENTITY_SCHEMA, (), build_identity, (), "/v1/identity"
        ),
        _kind("roots", "SolidSeas service roots", _ROOTS_SCHEMA, (), build_roots, (), "/v1/roots"),
        _kind(
            "serve_started",
            "SolidSeas service started",
            _SERVE_STARTED_SCHEMA,
            (),
            build_serve_started,
            ("serve",),
            None,
        ),
        _kind(
            "catalog", "SolidSeas catalog", _CATALOG_SCHEMA, (), build_catalog, ("catalog",), "/v1/catalog"
        ),
        _kind(
            "catalog_list",
            "SolidSeas catalogs in the cache",
            _CATALOG_LIST_SCHEMA,
            (),
            build_catalog_list,
            ("catalogs",),
            None,
        ),
        _kind(
            "catalog_cleared",
            "SolidSeas catalogs cleared",
            _CATALOG_CLEARED_SCHEMA,
            (),
            build_catalog_cleared,
            ("clear-index",),
            None,
        ),
        _kind(
            "catalog_scan",
            "SolidSeas catalog scan",
            _CATALOG_SCAN_SCHEMA,
            ("error",),
            build_catalog_scan,
            ("index",),
            None,
        ),
        _kind(
            "where_used",
            "SolidSeas where-used",
            _WHERE_USED_SCHEMA,
            ("warning",),
            build_where_used,
            ("where-used",),
            "/v1/where-used",
        ),
        _kind(
            "catalog_search",
            "SolidSeas catalog search",
            _CATALOG_SEARCH_SCHEMA,
            (),
            build_catalog_search,
            ("search",),
            "/v1/search",
        ),
        _kind(
            "duplicates",
            "SolidSeas duplicate files",
            _DUPLICATES_SCHEMA,
            (),
            build_duplicates,
            ("duplicates",),
            None,
        ),
        _kind(
            "missing_references",
            "SolidSeas missing references",
            _MISSING_SCHEMA,
            ("warning",),
            build_missing_references,
            ("missing",),
            None,
        ),
        _kind(
            "catalog_changes",
            "SolidSeas recent changes",
            _CHANGES_SCHEMA,
            (),
            build_catalog_changes,
            ("changes",),
            None,
        ),
        _kind(
            "drawing_result",
            "SolidSeas drawing command result",
            _DRAWING_SCHEMA,
            (),
            build_drawing_result,
            ("drawing",),
            None,
        ),
        _kind(
            "file_history",
            "SolidSeas file history",
            _FILE_HISTORY_SCHEMA,
            ("versioned_file", "version", "warning"),
            build_file_history,
            ("history",),
            None,
        ),
        _kind(
            "snapshot_taken",
            "SolidSeas snapshot taken",
            _SNAPSHOT_TAKEN_SCHEMA,
            ("versioned_file", "version"),
            build_snapshot_taken,
            ("snapshot",),
            None,
        ),
        _kind(
            "version_diff",
            "SolidSeas differences between two versions",
            _VERSION_DIFF_SCHEMA,
            ("versioned_file", "version", "document_brief", "property", "geometry_summary", "warning"),
            build_version_diff,
            ("diff",),
            None,
        ),
        _kind("error", "SolidSeas error", _ERROR_SCHEMA, (), error_info, (), None),
    )
}


def envelope_schema(kind: str) -> dict[str, Any]:
    """A JSON Schema for a whole envelope of ``kind``, with the kind's schema inside."""
    spec = KINDS[kind]
    inner = {k: v for k, v in spec.schema.items() if k not in ("$schema", "$id", "title", "$defs")}
    payload_key = "error" if kind == "error" else "data"
    body = {
        "type": "object",
        "properties": {
            "ok": {"const": kind != "error"},
            "kind": {"const": kind},
            "schema_version": {"const": spec.schema_version},
            "solidseas": _STR,
            "source": {"type": ["object", "null"]},
            payload_key: inner,
        },
        "required": ["ok", "kind", "schema_version", "solidseas", "source", payload_key],
    }
    s = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"urn:solidseas:schema:{kind}-envelope:v{spec.schema_version}",
        "title": f"{spec.title} (envelope)",
        **body,
    }
    if "$defs" in spec.schema:
        s["$defs"] = spec.schema["$defs"]
    return s


__all__ = [
    "API_VERSION",
    "CHECK_LEVELS",
    "DETAIL_KEYS",
    "DRAWING_ACTIONS",
    "DRAWING_FILE_KINDS",
    "ERROR_CODES",
    "KINDS",
    "LISTING_DEFAULT",
    "LISTING_PARTS",
    "MAX_SAFE_INTEGER",
    "MODEL_SUMMARY_DEFAULT",
    "MODEL_SUMMARY_PARTS",
    "PROPERTY_TYPES",
    "PROPERTY_VIEWS",
    "REWRITE_NOTE",
    "ROOT_STATES",
    "SUMMARY_PARTS",
    "WARNING_CODES",
    "ErrorCode",
    "KindSpec",
    "attach_resolution",
    "bom_data",
    "bom_row_data",
    "build_batch_summary",
    "build_catalog",
    "build_catalog_changes",
    "build_catalog_cleared",
    "build_catalog_list",
    "build_catalog_scan",
    "build_catalog_search",
    "build_duplicates",
    "build_missing_references",
    "build_where_used",
    "build_bom",
    "build_components",
    "build_configurations",
    "build_document_summary",
    "build_drawing_result",
    "build_export_result",
    "build_file_history",
    "build_file_written",
    "build_health",
    "build_identity",
    "build_listing",
    "build_model_properties",
    "build_model_summary",
    "build_parasolid_result",
    "build_path_report",
    "build_properties",
    "build_references",
    "build_roots",
    "build_serve_started",
    "build_sldprt_written",
    "build_snapshot_taken",
    "build_streams",
    "build_version",
    "build_version_diff",
    "clean_text",
    "component_file_data",
    "component_node_data",
    "drawing_check_data",
    "drawing_coverage_data",
    "drawing_file_data",
    "drawing_settings_data",
    "drawing_summary_data",
    "drawing_thread_candidates",
    "dumps",
    "envelope",
    "envelope_schema",
    "error_code",
    "error_envelope",
    "error_info",
    "file_object",
    "iso8601",
    "listing_entry",
    "listing_model_data",
    "loads",
    "location_data",
    "model_listing_entry",
    "placement_data",
    "resolution_result_data",
    "resolution_summary_data",
    "to_json_data",
    "transform_data",
    "unsupported_entry",
]
