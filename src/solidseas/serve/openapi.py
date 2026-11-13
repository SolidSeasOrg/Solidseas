"""The service's OpenAPI 3.0.3 description (``docs/API.md`` 8.19, provisional).

:func:`build_openapi` makes it from :data:`.server.ROUTES`: every route, and each
query parameter with the type, choices, bounds, default and required flag the
route's allowlist (:class:`.query.Param`) enforces, so the description cannot
drift from the code. What the code does not hold, the words for a person and the
error codes each route can answer, is in the tables below, and building the
document refuses a route or a parameter the tables do not describe.

The document is the same whatever a service was started with: its deadlines and
size caps are the defaults, and ``info.version`` is the API line (major.minor of
:data:`solidseas.__version__`), never the patch version, which changes with every
commit. ``/v1/openapi.json``, ``solidseas openapi`` and ``docs/openapi.json`` give
it. It is OpenAPI 3.0.3 rather than 3.1 because more tools read it.
"""

from typing import Any

from .. import __version__, model
from ..formats import registry
from ..roots import ROOT_ID
from .paths import MAX_PATH_CHARS
from .query import MAX_CURSOR, MAX_FIELDS, MAX_NESTED, Param
from .server import DEFAULT_CAPS, DEFAULT_DEADLINES, DEFAULT_PORT, ROUTES, Route
from .tokens import NONCE_TEXT, TOKEN_NAME

OPENAPI_VERSION = "3.0.3"
OPENAPI_ROUTE = "/v1/openapi.json"
API_DOCS = "https://github.com/SolidSeasOrg/Solidseas/blob/main/docs/API.md"
# Text without the control characters the query parser refuses (C0 and DEL), in the
# ECMA-262 dialect OpenAPI uses.
NO_CONTROL = r"^[^\u0000-\u001f\u007f]*$"


def _anchored(pattern) -> str:
    """A ``re`` pattern the parser uses with ``match`` and a closing ``\\Z``, anchored for
    ECMA-262."""
    return "^" + pattern.pattern.removesuffix(r"\Z") + "$"


# --------------------------------------------------------------------------- what each route is
# The error codes every route can answer, before or around its own work: a request the
# service cannot read or will not take (Host, Origin, a body, a URL or headers too long, a
# malformed query, a parameter the route does not name), too many open connections, and
# an internal error.
_EVERY_ROUTE = (
    "busy",
    "forbidden_host",
    "forbidden_origin",
    "headers_too_large",
    "internal",
    "invalid_argument",
    "unknown_parameter",
    "uri_too_long",
)
_WITH_TOKEN = ("too_many_failures", "unauthorized")
# a root, a path below it and the reading that starts from them
_ROOTED = (
    "link_refused",
    "not_found",
    "path_refused",
    "permission_denied",
    "placeholder_file",
    "response_too_large",
    "root_not_found",
    "root_unavailable",
    "timeout",
)
# a document read in a worker
_READS = (
    *_ROOTED,
    "damaged_file",
    "file_too_large",
    "format_not_supported",
    "limit_exceeded",
    "locked",
    "unknown_format",
    "worker_crashed",
)
_CATALOG = ("catalog_incompatible", "feature_disabled", "response_too_large", "timeout")
# the PDM's routes: a root and a path, the library's vault read in a worker
_PDM = (*_ROOTED, "damaged_file", "feature_disabled", "not_a_library", "worker_crashed")
_PROVISIONAL_NOTE = (
    "Provisional: it may change in any release, with a note in the changelog (docs/API.md section 9)."
)

# path: (operationId, tag, summary, description, the route's own error codes, provisional,
# the section of docs/API.md that describes its answer)
_OPERATIONS: dict[str, tuple[str, str, str, str, tuple[str, ...], bool, str]] = {
    "/v1/health": (
        "getHealth",
        "service",
        "Check that the service is up",
        'Answers `{"status": "ok"}` without a token, for a monitor. While no worker process is '
        "running it answers 503 `busy` (rule `no_workers`) with `Retry-After` instead, since nothing "
        "can be read until one is back.",
        (),
        False,
        "5.12",
    ),
    "/v1/identity": (
        "getIdentity",
        "service",
        "Prove the service holds a client's token",
        "Call it before sending a token: the answer's `proof` is the HMAC-SHA256 of the client's name, "
        "your nonce and the address and port the connection reached, keyed with the client's token. "
        "Compute the same with your token and send the token only when the two match, on the same "
        "connection. Needs no token. docs/API.md 8.16 has the exact message and clients in Python, "
        "curl, PowerShell and TypeScript.",
        (),
        False,
        "5.12",
    ),
    "/v1/version": (
        "getVersion",
        "service",
        "Get the SolidSeas, API and schema versions",
        "The SolidSeas version that answers, the API version and the schema version of every JSON kind.",
        (),
        False,
        "5.5",
    ),
    "/v1/roots": (
        "listRoots",
        "service",
        "List the folders the service serves",
        "Each configured root by its id, never by its folder: its role, whether its subfolders are "
        "served, whether its folder index is `building`, `ready` or `unavailable`, and how many "
        "SOLIDWORKS documents it holds.",
        (),
        False,
        "5.12",
    ),
    OPENAPI_ROUTE: (
        "getOpenApi",
        "service",
        "Get this description of the service",
        "This OpenAPI 3.0.3 document, as plain JSON without the envelope every other route uses. "
        "`solidseas openapi` prints the same document without a running service.",
        (),
        True,
        "8.19",
    ),
    "/v1/list": (
        "listFolder",
        "files",
        "List a folder's documents",
        "The documents and folders in a folder of a root, a page at a time, each document read in a "
        "worker process: a file that fails becomes an entry with its error and the page goes on. "
        "Entry paths are relative to the root. When a page stops at `limit` or at its deadline, "
        "`next_cursor` gives the next page: send it back as `cursor` with the other parameters "
        "unchanged.",
        _ROOTED,
        False,
        "5.7",
    ),
    "/v1/document": (
        "getDocument",
        "files",
        "Get a document's summary",
        "A document's summary: its type, the release that saved it, configurations, custom "
        "properties, material, units, preview and counts. For a 3D file of another format the "
        "service reads (`serve --formats`), the `model_summary` kind instead.",
        (*_READS, "stream_not_found"),
        False,
        "5.1",
    ),
    "/v1/properties": (
        "getProperties",
        "files",
        "Get a document's custom properties",
        "The custom properties of the file, of one configuration, or both as SOLIDWORKS applies them "
        "(`view`), each with its type, typed value and stored text.",
        (*_READS, "configuration_not_found", "stream_not_found"),
        False,
        "5.3",
    ),
    "/v1/configurations": (
        "getConfigurations",
        "files",
        "Get a document's configurations",
        "Every configuration with its material and its own custom properties, and which is active.",
        (*_READS, "not_implemented"),
        False,
        "5.2",
    ),
    "/v1/components": (
        "getComponents",
        "files",
        "Get an assembly's component tree",
        "The component tree of an assembly configuration, with each component's file, configuration, "
        "placement and flags, as a tree or a flat list. A part gives an empty tree.",
        (*_READS, "configuration_not_found", "not_implemented"),
        False,
        "5.9",
    ),
    "/v1/references": (
        "getReferences",
        "files",
        "Get the files a document references",
        "Every file the document references, once each, with its instance counts per configuration. "
        "With `resolve`, each is looked for in the service's roots and the result says where it was "
        "found, or why not.",
        (*_READS, "configuration_not_found", "not_implemented"),
        False,
        "5.9",
    ),
    "/v1/bom": (
        "getBom",
        "files",
        "Get an assembly's bill of materials",
        "The bill of materials of an assembly configuration as SOLIDWORKS draws it, its component "
        "files found in the service's roots and read for their properties.",
        (*_READS, "configuration_not_found", "not_implemented"),
        True,
        "5.13",
    ),
    "/v1/preview": (
        "getPreview",
        "files",
        "Get a document's preview image",
        "The preview image the document stores, as a PNG or a BMP whose bytes the service checked "
        "itself. For a 3D file of another format, the image it stores, else one rendered from its "
        "model (`render`).",
        (*_READS, "no_preview", "not_implemented", "stream_not_found"),
        False,
        "8.6",
    ),
    "/v1/path-report": (
        "getPathReport",
        "files",
        "Get the paths and names a file would reveal",
        "Every path, account, host and user name the file, and each document nested in it, would "
        "reveal to whoever receives it. It holds exactly those values, so treat the answer as "
        "confidential.",
        (*_READS, "not_implemented"),
        False,
        "5.11",
    ),
    "/v1/mesh": (
        "getMesh",
        "files",
        "Get a document's 3D model as a glTF binary",
        "What the document shows, from the display data it stores, as a GLB file for a web page. At "
        "most two are read at once; more answer 503 `busy` (rule `mesh_in_flight`).",
        (*_READS, "configuration_not_found", "nothing_to_export", "not_implemented"),
        True,
        "3.28",
    ),
    "/v1/catalog": (
        "getCatalog",
        "catalog",
        "Get the state of the catalog",
        "The catalog's roots by id, its counts and its last scan, with no folder paths.",
        _CATALOG,
        True,
        "5.15",
    ),
    "/v1/where-used": (
        "getWhereUsed",
        "catalog",
        "Find the documents that use a file",
        "The assemblies and drawings that use a part or a sub-assembly, nearest first. An answer "
        "over the size cap keeps the nearest users that fit and says `truncated`.",
        (*_CATALOG, "configuration_not_found", "not_in_catalog", "path_refused", "root_not_found"),
        True,
        "5.15",
    ),
    "/v1/search": (
        "searchCatalog",
        "catalog",
        "Search the catalog",
        "Documents by name, part number, description or any property, with filters such as "
        "`type:part` and `changed:7d` (docs/API.md 3.18).",
        _CATALOG,
        True,
        "5.15",
    ),
    "/v1/duplicates": (
        "listDuplicates",
        "catalog",
        "List files with identical contents",
        "Groups of files with the same SHA-256, and with `names` also files that share a name but "
        "differ in content.",
        _CATALOG,
        True,
        "5.15",
    ),
    "/v1/missing": (
        "listMissingReferences",
        "catalog",
        "List references that resolve to no file",
        "References that resolve to no file in the roots, or only to an ambiguous or low-confidence one.",
        _CATALOG,
        True,
        "5.15",
    ),
    "/v1/changes": (
        "listChanges",
        "catalog",
        "List recent changes to the files",
        "Files added, changed, moved and removed, newest first.",
        _CATALOG,
        True,
        "5.15",
    ),
    "/v1/pdm/status": (
        "getPdmStatus",
        "pdm",
        "List the files changed since their last version",
        "The tracked files below a folder of the root (or one file) that are new, changed since their "
        "newest version in the PDM library, or gone, with counts of each. A file whose size and time "
        "match its newest version is not read.",
        _PDM,
        True,
        "5.21",
    ),
    "/v1/pdm/log": (
        "getPdmLog",
        "pdm",
        "Get a file's history",
        "Every version the library keeps of a file, newest first, each with the check-ins that name "
        "it (note, revision, state, who), the working copy on top when it differs from the newest "
        "version, and the Git commits that changed it when it sits in a Git repository. A file that is "
        "gone from the folder still has its history.",
        _PDM,
        True,
        "5.21",
    ),
    "/v1/pdm/version": (
        "getPdmVersion",
        "pdm",
        "Get one version of a file",
        "One version's facts, as `solidseas pdm show` gives them: the version, its document's format, "
        "type and release, its properties and configurations, and each configuration's geometry "
        "counts and fingerprint. The version is read in a worker from the library's store (or from "
        "Git).",
        (
            *_PDM,
            "file_too_large",
            "format_not_supported",
            "limit_exceeded",
            "unknown_format",
            "version_not_found",
            "version_unavailable",
        ),
        True,
        "5.21",
    ),
    "/v1/pdm/checkins": (
        "listPdmCheckins",
        "pdm",
        "List recent check-ins",
        "The check-ins that name a file below a folder of the root, newest first, each with its note, "
        "revision, state, who and its files below the root (at most 100 listed). Automatic scans are "
        "left out unless `scans` is given. A page over the size cap holds fewer check-ins, and "
        "`next_cursor` continues from where it stops.",
        _PDM,
        True,
        "5.21",
    ),
    "/v1/pdm/check": (
        "checkPdmProject",
        "pdm",
        "Check that a project holds every file it uses",
        "Reads every SOLIDWORKS document of the project that holds the folder, read-only, and resolves "
        "each reference the way SOLIDWORKS searches, from the document's folder up past the project "
        "(docs/PDM.md section 5). A file found in another of the service's roots is named by its root "
        "and path; one found outside every root only says so (`outside_roots`).",
        (*_PDM, "locked"),
        True,
        "5.21",
    ),
}

_TAGS = (
    (
        "service",
        "The service itself: whether it is up, its identity proof, versions, roots and this description.",
    ),
    (
        "files",
        "Folders and documents under the roots: listings, summaries, properties, configurations, "
        "component trees, references, bills of materials, previews, path reports and 3D models.",
    ),
    (
        "catalog",
        "Queries of the catalog the service keeps of its roots when started with `--catalog` "
        "(provisional). Without it they answer 403 `feature_disabled`, and before the first scan has "
        "finished 503 `busy`.",
    ),
    (
        "pdm",
        "The history of the PDM library that holds a root's files, when the service is started with "
        "`--pdm` (provisional): what changed, each file's versions with their check-in notes, one "
        "version's facts, recent check-ins and a project's self-contained check. Without it they "
        "answer 403 `feature_disabled`, and for a path in no library 404 `not_a_library`. Every path "
        "is relative to the root, and the library's files outside the root are left out.",
    ),
)

# Parameter descriptions: (route, name) first, then the name alone.
_PARAMETERS: dict[tuple[str, str] | str, str] = {
    "root": "The id of a root, as `/v1/roots` lists them.",
    "path": "The document, `/`-separated and relative to the root. It is checked as text first "
    "(403 `path_refused` with `detail.rule`) and looked up in the root's folder index, never joined "
    "into a path (docs/API.md 8.5). Send a `+` in a name as `%2B`.",
    ("/v1/list", "path"): "The folder, `/`-separated and relative to the root. Leave it out for the "
    "root's own folder. A path that names a file answers 400 (rule `not_a_folder`).",
    ("/v1/where-used", "path"): "The file, `/`-separated and relative to the root, as the catalog "
    "holds it. It is checked as text, and no file is opened.",
    "configuration": "A configuration name. Left out: the active configuration.",
    ("/v1/where-used", "configuration"): "Only the uses of this configuration of the file.",
    "nested": "Read a virtual or imported component's own document, named as in the `nested` field of "
    "the `components` and `references` answers.",
    "limit": "The most rows a page holds.",
    ("/v1/list", "limit"): "The most entries a page holds.",
    "cursor": "The `next_cursor` of the previous page, sent back as it was, with the other "
    "parameters unchanged. A cursor from another query answers 400.",
    "recursive": "List the subfolders too, breadth first. A root served without its subfolders answers 400.",
    "include": "What each document entry carries, replacing the default: `properties` (the active "
    "configuration's effective properties), `configurations`, `preview` (its description) and "
    "`preview_data` (the image inline, as base64).",
    "formats": "Provisional. The formats listed: `solidworks` (the default), `all` the formats the "
    "service reads, or comma-separated format ids among them. A format the service was not started "
    "to read answers 400. The ids SolidSeas knows: {formats}.",
    "view": "`effective` (the file's properties overridden by the configuration's, as a bill of "
    "materials sees them), `file` (the file's own) or `configuration` (the configuration's own).",
    "max_depth": "The most levels of the tree.",
    "max_nodes": "The most nodes of the tree; a larger tree is cut short and says `truncated`.",
    "flat": "Give the components as a flat list instead of a tree.",
    "resolve": "Find each referenced file in the service's roots (docs/API.md 3.10). Each request "
    "walks the roots again, so it sees the folders as they are now.",
    "type": "`top` (top-level components, as SOLIDWORKS draws it by default), `parts` (parts only) or "
    "`indented` (each sub-assembly followed by its components).",
    "columns": "Custom property names, comma-separated, each read like DESCRIPTION into a column of "
    "its own. Two names equal but for case answer 400.",
    "part_number_property": "Take PART NUMBER from this property where a file has it, instead of the "
    "document name.",
    "prefer": "`png`, or `dib` for the BMP SolidSeas builds from the stored bitmap.",
    "render": "Provisional, for 3D files of other formats: `auto` the stored image, else one rendered "
    "from the model; `never` the stored image or 404 `no_preview`; `always` rendered. `always` for a "
    "SOLIDWORKS document answers 501.",
    "direct": "Only the documents that use the file themselves, not the assemblies above them.",
    "q": "The search text of docs/API.md 3.18: words, each a prefix, and filters such as `type:part`, "
    "`pn:`, `desc:`, `prop:Name=value`, `folder:sub/path`, `root:ID` and `changed:7d`.",
    "sort": "`relevance`, `name` or `modified` (newest first).",
    "names": "Also list files that share a name but differ in content.",
    "since": "Only changes since then: `7d`, `12h`, `2w` or a date such as `2026-09-01`.",
    ("/v1/pdm/status", "path"): "A folder or one file, `/`-separated and relative to the root. Leave it out "
    "for the whole root. A file that is gone is named by its folder and its name.",
    ("/v1/pdm/log", "path"): "The file, `/`-separated and relative to the root. A file that is gone from "
    "its folder is found by its folder and its name, and still has its history.",
    ("/v1/pdm/version", "path"): "The file, `/`-separated and relative to the root, as for `/v1/pdm/log`.",
    ("/v1/pdm/checkins", "path"): "A folder, `/`-separated and relative to the root: only check-ins that "
    "name a file below it. Leave it out for the whole root.",
    ("/v1/pdm/check", "path"): "A project folder, or a folder inside one, `/`-separated and relative to "
    "the root. Leave it out when the root is the project.",
    "unchanged": "Also list the files that have not changed (they are always counted).",
    "version": "The version, as `/v1/pdm/log` lists it: `v1` (the oldest), `v2` and so on, `latest`, "
    "`working` (the file on disk) or the first characters of its id.",
    "source": "`vault` for the library's versions, `git` for the Git repository's.",
    "scans": "Also list the automatic scans, which have no note.",
    "copy_toolbox": "Treat Toolbox parts as files the project must hold, instead of ones SOLIDWORKS "
    "loads from its installation.",
    ("/v1/pdm/check", "plan"): "Also list the copies that would make the project self-contained, "
    "as `pdm check --plan` does. Nothing is copied: the service only lists them.",
    "client": "The name of the client's line in the service's token file.",
    "nonce": "A fresh random value for this check alone, such as 32 random bytes in hex or base64url.",
}
# The routes whose answers carry an ETag (and so answer 304 to If-None-Match): every one but
# these, which read nothing and change with no file.
_NO_ETAG = ("/v1/health", "/v1/identity", "/v1/version", "/v1/roots")
# The routes that answer with bytes rather than a JSON envelope, with their media types.
_MEDIA = {"/v1/preview": ("image/png", "image/bmp"), "/v1/mesh": ("model/gltf-binary",)}
_STATUS_TEXT = {
    400: "The request is not valid.",
    401: "No valid bearer token. The answer carries `WWW-Authenticate`.",
    403: "Refused.",
    404: "Not found.",
    409: "Not available as it is.",
    414: "The URL is longer than 4 KiB.",
    422: "The file, or the answer, is beyond what the service reads or sends.",
    423: "The file is locked.",
    429: "Too many failed attempts from this address; wait for `Retry-After`.",
    431: "The headers are too large or too many.",
    500: "The service failed. Quote `X-Request-Id`, which its log line carries.",
    501: "Not available for this file.",
    503: "Busy or unavailable; try again after `Retry-After`.",
    504: "Not finished within the route's deadline.",
}
_DETAIL = {
    "stream": ("string", "The stream or nested document concerned."),
    "parameter": ("string", "The query parameter at fault."),
    "rule": (
        "string",
        "Which case of the code it is, such as `route`, `not_a_folder` or `body` (an open set).",
    ),
    "component_index": ("integer", "The path component at fault, from 0."),
    "limit": (None, "The limit reached: a number of bytes, or the name of a bound."),
    "value": (None, "The value at fault, such as a format id."),
    "usage": ("string", "The usage text (the command line only)."),
}


# --------------------------------------------------------------------------- pieces
def _ref(group: str, name: str) -> dict[str, Any]:
    return {"$ref": f"#/components/{group}/{name}"}


def _camel(kind: str) -> str:
    return "".join(part.capitalize() for part in kind.split("_"))


def _deadline_text(route: Route) -> str:
    if route.path == "/v1/list":
        return (
            f"A page has {DEFAULT_DEADLINES['list_page']:g} s and each document "
            f"{DEFAULT_DEADLINES['list_file']:g} s by default; an answer over "
            f"{DEFAULT_CAPS[route.cap] >> 20} MiB answers 422 `response_too_large`."
        )
    if route.job is None and route.deadline == "document":
        return ""  # it reads nothing
    return (
        f"Deadline {DEFAULT_DEADLINES[route.deadline]:g} s by default (504 `timeout` past it); an "
        f"answer over {DEFAULT_CAPS[route.cap] >> 20} MiB answers 422 `response_too_large`."
    )


def _schema(name: str, spec: Param) -> dict[str, Any]:
    """The schema of one query parameter, as :func:`.query.parse_query` enforces it."""
    kind = spec.kind
    if kind == "root":
        return {"type": "string", "pattern": _anchored(ROOT_ID)}
    if kind == "client":
        return {"type": "string", "pattern": _anchored(TOKEN_NAME)}
    if kind == "nonce":
        return {"type": "string", "pattern": _anchored(NONCE_TEXT)}
    if kind == "path":
        # the query takes 4,096 characters, and the path's own check 1,024 (403 too_long)
        return {"type": "string", "minLength": 1, "maxLength": MAX_PATH_CHARS}
    if kind in ("text", "nested", "cursor"):
        most = {"nested": MAX_NESTED, "cursor": MAX_CURSOR}.get(kind, spec.max_len)
        return {"type": "string", "minLength": 1, "maxLength": most, "pattern": NO_CONTROL}
    if kind == "enum":
        return {"type": "string", "enum": list(spec.choices), "default": spec.default}
    if kind == "bool":
        return {"type": "boolean", "default": spec.default}
    if kind == "int":
        return {
            "type": "integer",
            "format": "int32",
            "minimum": spec.low,
            "maximum": spec.high,
            "default": spec.default,
        }
    if kind == "include":
        return {
            "type": "array",
            "items": {"type": "string", "enum": list(spec.choices)},
            "minItems": 1,
            "maxItems": len(spec.choices),
            "uniqueItems": True,
            "default": list(spec.default),
        }
    raise ValueError(f"no OpenAPI schema for the parameter kind {kind!r} of {name}")


def _parameter(route: Route, name: str, spec: Param) -> dict[str, Any]:
    text = _PARAMETERS.get((route.path, name), _PARAMETERS.get(name))
    if text is None:
        raise KeyError(f"{route.path}: the parameter {name} has no description in the OpenAPI tables")
    if name == "formats":
        text = text.format(formats=", ".join(f"`{f}`" for f in sorted(registry.FORMATS)))
    if spec.kind == "bool":
        text += " `true` or `false`; `1` and `0` are accepted too."
    out: dict[str, Any] = {"name": name, "in": "query", "required": spec.required, "description": text}
    out["schema"] = _schema(name, spec)
    if spec.kind == "include":
        out["style"], out["explode"] = "form", False
    if name in ("formats", "render"):
        out["x-solidseas-provisional"] = True
    return out


def route_kinds(route: Route) -> list[str]:
    """The JSON kinds a route answers with: its own, then any that stands in for it on the
    same route (``model_summary`` on ``/v1/document``)."""
    if route.kind is None:
        return []
    alternates = sorted(
        k for k, s in model.KINDS.items() if s.alternate_of == route.kind and s.rest_route == route.path
    )
    return [route.kind, *alternates]


def route_error_codes(route: Route) -> list[str]:
    """Every error code the route can answer, sorted."""
    codes = set(_EVERY_ROUTE) | set(_OPERATIONS[route.path][4])
    if route.auth:
        codes |= set(_WITH_TOKEN)
    if route.params:
        codes.add("duplicate_parameter")
    return sorted(codes)


def _headers(*names: str) -> dict[str, Any]:
    return {n: _ref("headers", n) for n in names}


def _responses(route: Route) -> dict[str, Any]:
    etag = route.path not in _NO_ETAG
    ok_headers = _headers("Cache-Control", *(("ETag",) if etag else ()), "X-Request-Id")
    kinds = route_kinds(route)
    if route.path in _MEDIA:
        content = {m: {"schema": {"type": "string", "format": "binary"}} for m in _MEDIA[route.path]}
        what = "The file's bytes, checked by the service before it sends them."
    elif route.path == OPENAPI_ROUTE:
        content = {"application/json": {"schema": _ref("schemas", "OpenApiDocument")}}
        what = "This OpenAPI document, without an envelope."
    elif len(kinds) == 1:
        content = {"application/json": {"schema": _ref("schemas", _camel(kinds[0]) + "Envelope")}}
        what = f"The `{kinds[0]}` envelope."
    else:
        refs = {k: f"#/components/schemas/{_camel(k)}Envelope" for k in kinds}
        schema = {
            "oneOf": [{"$ref": r} for r in refs.values()],
            "discriminator": {"propertyName": "kind", "mapping": refs},
        }
        content = {"application/json": {"schema": schema}}
        what = "The " + " or ".join(f"`{k}`" for k in kinds) + " envelope, as `kind` says."
    if route.path == "/v1/list":
        what += " A page holding an entry that may read differently later (`locked`, `timeout`) has no ETag."
    out: dict[str, Any] = {"200": {"description": what, "headers": ok_headers, "content": content}}
    if etag:
        out["304"] = {
            "description": "Not modified since the ETag sent in `If-None-Match`; no body.",
            "headers": _headers("Cache-Control", "ETag", "X-Request-Id"),
        }
    by_status: dict[int, list[str]] = {}
    for code in route_error_codes(route):
        by_status.setdefault(model.ERROR_CODES[code].http_status, []).append(code)
    for status in sorted(by_status):
        lines = [_STATUS_TEXT[status], ""]
        lines += [f"- `{c}`: {model.ERROR_CODES[c].message}" for c in by_status[status]]
        names = ["X-Request-Id"]
        if status == 401:
            names.append("WWW-Authenticate")
        if status in (429, 503):
            names.append("Retry-After")
        out[str(status)] = {
            "description": "\n".join(lines),
            "headers": _headers(*sorted(names)),
            "content": {"application/json": {"schema": _ref("schemas", "ErrorEnvelope")}},
        }
    return out


def _operation(route: Route) -> dict[str, Any]:
    op_id, tag, summary, text, _codes, provisional, section = _OPERATIONS[route.path]
    parts = [text]
    deadline = _deadline_text(route)
    if deadline:
        parts.append(deadline)
    if provisional:
        parts.append(_PROVISIONAL_NOTE)
    parts.append(f"HEAD is answered too, with the headers alone. Reference: docs/API.md section {section}.")
    op: dict[str, Any] = {
        "operationId": op_id,
        "tags": [tag],
        "summary": summary,
        "description": "\n\n".join(parts),
    }
    params = [_parameter(route, name, spec) for name, spec in route.params.items()]
    if route.path not in _NO_ETAG:
        params.append(_ref("parameters", "IfNoneMatch"))
    if params:
        op["parameters"] = params
    op["responses"] = _responses(route)
    if not route.auth:
        op["security"] = []
    if provisional:
        op["x-solidseas-provisional"] = True
    return op


def _kind_section(kind: str) -> str:
    """The section of docs/API.md that describes a kind's ``data``."""
    for section, kinds in _KIND_SECTIONS.items():
        if kind in kinds:
            return section
    raise KeyError(f"the kind {kind} has no section in the OpenAPI tables")


_KIND_SECTIONS = {
    "5.1": ("document_summary",),
    "5.2": ("configurations",),
    "5.3": ("properties",),
    "5.5": ("version",),
    "5.7": ("listing",),
    "5.9": ("components", "references"),
    "5.11": ("path_report",),
    "5.12": ("health", "identity", "roots"),
    "5.13": ("bom",),
    "5.15": (
        "catalog",
        "where_used",
        "catalog_search",
        "duplicates",
        "missing_references",
        "catalog_changes",
    ),
    "5.16": ("model_summary",),
    "5.21": ("pdm_status", "pdm_log", "pdm_version", "pdm_checkins", "pdm_check"),
}


def _components(kinds: list[str]) -> dict[str, Any]:
    schemas: dict[str, Any] = {
        "Source": {
            "type": "object",
            "nullable": True,
            "description": "What the answer is about: the root and the path in its on-disk spelling, "
            "plus `nested` when it was given; in an error, the root and path as requested, each null "
            "when the query did not give it as valid text. Null when the route names no file.",
            "properties": {
                "root": {"type": "string", "nullable": True},
                "path": {"type": "string", "nullable": True},
                "nested": {"type": "string"},
            },
            "required": ["root", "path"],
        },
        "Envelope": {
            "type": "object",
            "description": "Every JSON answer but this description's (docs/API.md 4.1). Ignore fields "
            "you do not know: fields may be added in any release (section 9).",
            "properties": {
                "ok": {"type": "boolean", "description": "True for an answer, false for an error."},
                "kind": {"type": "string", "description": "What `data` holds."},
                "schema_version": {"type": "integer", "description": "The kind's schema version (4.3)."},
                "solidseas": {"type": "string", "description": "The SolidSeas version that answered."},
                "source": _ref("schemas", "Source"),
                "data": {"type": "object"},
            },
            "required": ["ok", "kind", "schema_version", "solidseas", "source", "data"],
        },
        "ErrorEnvelope": {
            "type": "object",
            "description": "Every error answer (docs/API.md 4.1 and 5.6).",
            "properties": {
                "ok": {"type": "boolean", "description": "Always false."},
                "kind": {"type": "string", "enum": ["error"]},
                "schema_version": {"type": "integer"},
                "solidseas": {"type": "string", "description": "The SolidSeas version that answered."},
                "source": _ref("schemas", "Source"),
                "error": _ref("schemas", "Error"),
            },
            "required": ["ok", "kind", "schema_version", "solidseas", "source", "error"],
        },
        "Error": {
            "type": "object",
            "description": "docs/API.md 5.6. Decide on `code`, and on the HTTP status for a code you "
            "do not know: the codes are an open set.",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The error code (an open set).",
                    "x-extensible-enum": sorted({c for r in ROUTES.values() for c in route_error_codes(r)}),
                },
                "message": {"type": "string", "description": "A fixed text per code (or per rule)."},
                "exception": {"type": "string", "description": "The exception's class name."},
                "retryable": {"type": "boolean", "description": "True where waiting can help."},
                "detail": _ref("schemas", "ErrorDetail"),
                "reader_message": {
                    "type": "string",
                    "nullable": True,
                    "description": "Always null from the service: a reader's own text can hold a path.",
                },
            },
            "required": ["code", "message", "exception", "retryable", "detail", "reader_message"],
        },
        "ErrorDetail": {
            "type": "object",
            "description": "Structured, safe facts about the error, under these keys only.",
            "properties": {},
        },
        "OpenApiDocument": {"type": "object", "description": "An OpenAPI 3.0.3 document."},
    }
    for key in model.DETAIL_KEYS:
        kind, text = _DETAIL[key]
        prop: dict[str, Any] = {"description": text}
        if kind is not None:
            prop["type"] = kind
        schemas["ErrorDetail"]["properties"][key] = prop
    for kind in kinds:
        spec = model.KINDS[kind]
        name = _camel(kind)
        schemas[name] = {
            "type": "object",
            "description": f"The `{kind}` kind, schema version {spec.schema_version}: docs/API.md "
            f"section {_kind_section(kind)}. `solidseas schema {kind}` prints its full JSON Schema.",
            "additionalProperties": True,
        }
        schemas[name + "Envelope"] = {
            "allOf": [
                _ref("schemas", "Envelope"),
                {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": [kind]},
                        "data": _ref("schemas", name),
                    },
                },
            ]
        }
    headers = {
        "Cache-Control": "`private, no-cache`: keep the answer if you like, and revalidate it with "
        "`If-None-Match`.",
        "ETag": "The answer's tag, for `If-None-Match` (docs/API.md 8.10).",
        "Retry-After": "Seconds to wait before trying again.",
        "WWW-Authenticate": '`Bearer realm="solidseas"`.',
        "X-Request-Id": "The id the service's log line for this request carries.",
    }
    return {
        "securitySchemes": {
            "bearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "description": "A token from the service's token file, as `Authorization: Bearer "
                "<token>` (docs/API.md 8.3). Check the service with `/v1/identity` before sending it "
                "(8.16). Never put a token in the URL.",
            }
        },
        "parameters": {
            "IfNoneMatch": {
                "name": "If-None-Match",
                "in": "header",
                "required": False,
                "description": "The ETag of an answer you kept: an unchanged answer is 304 with no body.",
                "schema": {"type": "string"},
            }
        },
        "headers": {
            name: {
                "description": text,
                "schema": {"type": "integer" if name == "Retry-After" else "string"},
            }
            for name, text in headers.items()
        },
        "schemas": dict(sorted(schemas.items())),
    }


_DESCRIPTION = """\
`solidseas serve` is a read-only HTTP service over folders an administrator configures \
(roots). It listens on 127.0.0.1 by default. docs/API.md section 8 is its reference.

- **Token.** Every route but `/v1/health` and `/v1/identity` needs `Authorization: Bearer \
<token>`, a token from the service's token file. Before sending it, check with `/v1/identity` \
that the service holds it.
- **Methods.** Every route answers GET and HEAD; HEAD does the same work and sends the headers \
alone. Any other method answers 405.
- **Locations.** A file or folder is named by a root id (`root`) and a `/`-separated path \
relative to it (`path`), both query parameters.
- **Queries.** A parameter a route does not name answers 400 `unknown_parameter`, one given twice \
400 `duplicate_parameter`, and an empty value 400 `invalid_argument`: leave the parameter out \
instead. A query holds at most {fields} fields.
- **Answers.** Every JSON answer is an envelope whose `kind` says what `data` holds, and every \
error one whose `error` holds a `code`. Ignore fields you do not know, and treat enumerations and \
error codes as open sets.
- **Caching.** An answer about a file or folder carries an `ETag`; send it back in \
`If-None-Match` to get 304 when nothing changed.
- **Provisional** operations and parameters (`x-solidseas-provisional`) may change in any \
release. The rest is stable within this API version.
"""


# --------------------------------------------------------------------------- the document
def build_openapi() -> dict[str, Any]:
    """The OpenAPI 3.0.3 description of every route in :data:`.server.ROUTES`, as plain JSON
    data. Raises ``KeyError`` or ``ValueError`` for a route, a parameter or a kind the
    tables of this module do not describe."""
    missing = [p for p in ROUTES if p not in _OPERATIONS]
    stale = [p for p in _OPERATIONS if p not in ROUTES]
    if missing or stale:
        raise KeyError(f"the OpenAPI tables and ROUTES differ: missing {missing}, stale {stale}")
    paths = {path: {"get": _operation(route)} for path, route in ROUTES.items()}
    kinds = sorted({k for r in ROUTES.values() for k in route_kinds(r)})
    return {
        "openapi": OPENAPI_VERSION,
        "info": {
            "title": "SolidSeas REST service",
            "version": ".".join(__version__.split(".")[:2]),
            "description": _DESCRIPTION.format(fields=MAX_FIELDS),
            "license": {"name": "Apache-2.0", "url": "https://www.apache.org/licenses/LICENSE-2.0"},
        },
        "externalDocs": {"description": "docs/API.md, section 8", "url": API_DOCS},
        "servers": [
            {
                "url": "http://127.0.0.1:{port}",
                "description": "The service on this machine, at its default address.",
                "variables": {
                    "port": {
                        "default": str(DEFAULT_PORT),
                        "description": "The port `solidseas serve` listens on (`--port`).",
                    }
                },
            }
        ],
        "security": [{"bearerAuth": []}],
        "tags": [{"name": name, "description": text} for name, text in _TAGS],
        "paths": paths,
        "components": _components(kinds),
    }


__all__ = ["OPENAPI_ROUTE", "OPENAPI_VERSION", "build_openapi", "route_error_codes", "route_kinds"]
