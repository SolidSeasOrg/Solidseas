# SolidSeas integration API

For systems that read SOLIDWORKS files through SolidSeas: ERP, invoicing,
project tracking and the online store. It covers the Python library, the JSON
every surface emits, and the rules behind both.

## Status

**Stable from 0.2.0.** This document describes SolidSeas 0.2.x, that is 0.2.0
and the 0.2 versions after it (`solidseas.__version__` gives the exact one).
0.2.0 was the first release under the stability policy in section 9: what this
document marks stable changes only as that policy allows, and what it marks
provisional may still change in any release, with a note in `CHANGELOG.md`.
Nothing released before 0.2.0 is covered.

What it covers:

- the Python API in section 3, including folder listings (`scan`, 3.6), the
  one folder walker every surface uses (3.7), component trees (3.8),
  reference resolution (3.10), roots (3.11), the path report (3.12), the
  worker processes that read untrusted documents (3.13), an assembly's
  display geometry (3.14), the triangles of a part's Parasolid bodies (3.15),
  bills of materials (3.16), exports for 3D printing, STL and 3MF (3.17),
  the catalog of project folders with where-used, search and duplicates
  (3.18, provisional), STEP exports of parts (3.19), 3D files of other formats
  than SOLIDWORKS, read by the readers of STEP, Parasolid, ACIS SAB, Alibre
  Design and the mesh formats (STL, 3MF, OBJ, PLY, OFF, glTF and GLB, AMF)
  (3.20, provisional), previews rendered from a model (3.21, provisional),
  conversion through SolidSeas' own SOLIDWORKS on Windows (3.22,
  provisional), the AI connector with the machine policy (3.23,
  provisional), and the drawing core (3.24, provisional);
- the JSON kinds `document_summary`, `properties`, `configurations`,
  `components`, `references` (with resolution results, 5.10), `bom`, `path_report`,
  `listing`, `streams`, `file_written`, `parasolid_result`, `export_result`, `batch_summary`,
  `version`, `health`, `identity`, `roots`, `serve_started` and `error`, built by
  `solidseas.model` (section 5), the catalog's kinds (5.15, provisional) and
  `model_summary` (5.16, provisional);
- the command line, with `--json` on every command and the exit codes
  (section 7);
- the REST service, `solidseas serve` (section 8), how to run it as a
  background service (8.14) and how a client checks it before sending its
  token (8.16);
- the error codes and warning codes;
- how to read the JSON from JavaScript (section 6), recipes in Python, curl
  and TypeScript (section 10), and troubleshooting (section 11).

`docs/SECURITY_REVIEW.md` reviews the service for whoever has to approve it,
and `docs/FORMAT.md` holds the evidence behind every value SolidSeas reads.

## 1. One definition, three surfaces

SolidSeas is reached three ways: `import solidseas` in Python, the
`solidseas` command with `--json`, and `solidseas serve`, a local REST
service. Every JSON shape is built once, in `solidseas.model`, and encoded by
`solidseas.model.dumps`. For a document (a summary, its properties,
configurations, components, references or path report) the surfaces differ
only in the envelope's `source` field, so `data` for the same file and the same
request is identical whichever surface produced it. Folder listings and
reference resolution differ in where paths start and in a few defaults, as
1.2 says.

```python
from solidseas import open_document

with open_document("D:/Jobs/Example/bracket.SLDPRT") as doc:
    print(doc.doc_type, doc.saved_version.release, doc.active_configuration)
    for p in doc.effective_properties():   # the active configuration
        print(p.name, p.type, p.value)
    data = doc.summary()                    # the document_summary JSON data
```

### 1.1 Install

- Python 3.11 or newer, on Linux or Windows (the CI runs both; macOS is
  untested). The only dependency is `olefile`. SOLIDWORKS is not needed, and
  nothing is configured or installed beyond the package.
- SolidSeas is not on PyPI yet. Install it from a checkout of the repository,
  into the environment the integration runs in:

  ```sh
  python -m pip install /path/to/SolidSeas      # the library and the solidseas command
  solidseas version --json
  ```

- `python -m solidseas ...` works wherever `solidseas ...` does.

### 1.2 Which surface to use

| The integration is | Use | Reference |
|---|---|---|
| Python code (an ERP module, a script) | `import solidseas` | section 3 |
| Anything that can run a program and read its output (a scheduled job, a shell or PowerShell script) | `solidseas <command> --json` | section 7 |
| A service in another language, or in another container (the TypeScript store) | `solidseas serve`, called over HTTP | section 8 |

The JSON kinds are the same on all three (section 4), and for a document the
`data` is identical. Three things differ, which matter when an integration
moves from one surface to another:

- **Listing paths.** The service lists below a root: an entry's `path` is
  relative to the root, and the listing names its `root` and `folder`. Python's
  `scan` and the CLI's `list` list the folder they are given: `root` is null,
  `folder` is `""` and each `path` is relative to that folder. An integration
  that keys records by entry path keys them differently on each, so pick one.
- **Listing defaults.** The service's `include` and Python's `include=` replace
  the default (`preview`): `include=properties` lists properties alone. The
  CLI's `--include` adds to its `--preview` option instead (`meta` unless
  given), so the same thing is `--include properties --preview none` (7.1).
- **Resolution.** Python and the CLI look up a single known path outside the
  roots on a local drive; the service never does. `--no-outside-roots` on the
  CLI, and `allow_outside_roots=False` in Python, give the service's rule. A
  root that does not exist stops the CLI (exit 1), while the service searches
  without it and says so (8.6).

Python also returns objects for code that does not want JSON. They carry the
same values, in a few places under other names or in another form, as 3.8
lists. Section 10 has worked recipes for each surface.

### 1.3 Quick start

```sh
solidseas info D:\Jobs\Example\bracket.SLDPRT --json          # a document summary
solidseas list D:\Jobs\Example --include properties --json     # a folder: thumbnails and properties
solidseas components D:\Jobs\Example\frame.SLDASM --json       # an assembly's component tree
```

```sh
solidseas serve --root jobs=D:\Jobs        # one line when it is ready; Ctrl+C stops it
```

The first start creates the token file (8.3), readable only by the account
that started the service, and never prints the token. A client sends a token
from that file as `Authorization: Bearer <token>` with every request, such as
`GET http://127.0.0.1:8765/v1/document?root=jobs&path=Example/bracket.SLDPRT`.
Section 8.15 shows how to do that from curl and PowerShell without putting the
token on a command line, 8.16 how a client first checks that it is talking to
the service and not to a program that took its port, and section 10 how to use
the answers.

## 2. Rules the code follows

These settle where the Phase 1 designs disagreed. C1 to C10 are the decision
numbers from the Phase 1 design review; code and tests refer to them. Most of
them govern code that later Phase 1 steps add (the folder walker, `Roots`,
reference resolution and the service). They are recorded first so that code
follows them from its first line.

### C1. Locations are root-relative

Every surface reports a location on disk as `{"root": <root id>, "path":
<relative path>}`, with `/` separators and the on-disk spelling. That keeps one
`data` on all three surfaces. Only the CLI and Python can report a match outside
every configured root (C2); such a match is `{"root": null, "path": <absolute
host path>}`. The REST service never returns an absolute path.

Paths stored inside documents are a different thing: they are reported as
stored (Windows form, backslashes) in fields named `stored_path`, and are never
used as a location on this machine without the checks in C2.

### C2. Where SolidSeas may look on disk

- **One gateway.** Every filesystem call reference resolution makes goes
  through `solidseas.resolve.gateway`, which applies the rules below; a test
  reads the package's source and fails if another module makes one.
- **Inside a root**, every lookup goes through the folder index built by the
  shared folder walker. Nothing behind a link or junction is ever indexed.
- **Outside every root**, a point lookup (one known path, never a search) is
  allowed in the library and the CLI, and only for a path on a local fixed or
  removable drive. The anchor is classified and compared before any filesystem
  call. The REST service never looks outside its roots. An assembly names its
  components' paths itself, so a crafted one can make `resolve_references`,
  `display_geometry`, `build_boms` and `print_model` read (never write) a
  SOLIDWORKS file at a local path it chooses. Code of your own that takes
  uploads from people it does not trust should pass
  `allow_outside_roots=False`, or explicit roots, as the service does.
- **Stored anchors** are classified into a closed set: a drive (`X:\`), a UNC
  share (`\\host\share\`), or a bare file name. Anything else is refused
  outright: `\\?\`, `\\.\`, a drive-relative `C:name` and a single leading
  backslash.
- **A stored UNC path or mapped network drive is never touched** on any
  surface: no `stat`, no `open`, no `realpath`. Touching it makes Windows
  connect over SMB and send the user's credentials to whatever host the file
  names. It is used only for string comparison with roots and the path map.
- **Cloud placeholders** (offline or recall-on-access attributes) are never
  opened. An outside-root point lookup checks the attribute before reading the
  file's identity, so a OneDrive file is never downloaded by a lookup.

### C3. Resolution over REST is a plain GET

`GET /v1/references?resolve=1` returns the `references` kind with each file's
`resolution` filled in. There is no POST and no job id: the service builds each
root's folder index when it starts, to find the documents requests name, and
answers 503 with `Retry-After` (error code `busy`) while that index is still
building. A resolution walks the roots again for its request, so it sees the
folders as they are now (8.6). Phase 1 resolution does not recurse into
sub-assemblies, so no request needs a long-running job.

### C4. One CLI command for references

```text
solidseas references FILE --resolve --root ID=DIR [--library ID=DIR] [--path-map FROM=TO]
```

Missing and ambiguous references are data, so they exit 0. The command exits 4
(partial) when the folder index was cut short by a limit (`index_partial`).

### C5. One `Roots` type

`solidseas.Roots` holds every folder SolidSeas may search or serve. Each entry
has `id` (matching `[a-z0-9_-]{1,32}`), `path`, `recursive` and `role`
(`project` or `library`). Resolution, the folder listing and the REST service
all use it; there is no second root type.

### C6. Which roots are accepted

A root is administrator configuration, not file content. A root that is a
junction or a UNC share is accepted. A WebDAV root (an `@` in the host, or
`DavWWWRoot`) is refused, because Windows reaches it over HTTP with the user's
credentials.

### C7. One key per referenced file

A referenced file's key is its `swFile` id in the assembly's component tree,
as a string. The same key means the same file in `components`, `references`
and every resolution result. A file known only from `Header2` (an assembly
without a component tree, or a drawing) gets the key `header2:<n>`, numbered
from 1 in stored order.

Phase 1 resolves the top document's own tree, in the top document's context:
files inside sub-assemblies are resolved from the paths the top assembly
stored, and carry the warning `from_parent_tree`. A file reached from more than
one parent document carries `context_varies`.

### C8. Enums are open, and every warning has one shape

Status values, error codes, warning codes, path categories and reasons are open
sets. A client treats a value it does not know as "other", and a REST client
falls back on the HTTP status class. Only `ok` and `kind` in the envelope are
closed.

Every warning, wherever it appears, is `{"code", "stream", "message"}`, the
JSON form of `ReaderWarning`. `stream` is null when the warning is not about one
stream.

### C9. The resolution object points at file keys

A resolution result describes one file, by its key. It carries no quantity and
no instance list; those belong to the component tree. `Reference.quantity` in
Python counted instances from every configuration together and is deprecated in
favour of the per-configuration counts on component files.

### C10. Where resolution runs in the service

The REST server process never opens a CAD file. Resolution runs in three
steps: the server process walks the roots and collects candidates from the
folder indexes it builds, one batched identity read runs in a worker process,
and the server process then applies the rules to the results.

### Corrections that shape the JSON

- A virtual or imported component found as a nested document has status
  `embedded` and names the stream in `nested`; when that stream is absent the
  status is `embedded_not_found`. Neither status claims a location.
- Several acceptable candidates with the same name are separated by the
  folder-suffix score, and otherwise reported as `ambiguous`. Phase 1 uses no
  version or update stamps to choose: they decided 4 of 3,225 direct references
  in measurement and disagreed with the ground truth too often. Confidence
  comes from each rule's measured precision (3.10).
- A stored creation time of 0, or one later than the current time plus one
  day, is unknown.
- Names are compared the way NTFS compares them: per character, by simple
  uppercase. "ß" and "ss" are different names. Two names equal only after NFC
  normalisation are a candidate with the warning `normalization_differs`.
- `configuration=None` means the active configuration everywhere it is
  accepted (section 3.4).
- The folder listing and the document summary describe a file with the same
  sub-objects (`file`, `saved_version`, `preview`, property and configuration).
- An account seen only in a template's history stays at severity `medium` in
  the path report, with a note, rather than being ranked lower (3.12).
- The path report gives no file-level rating: nearly every file would rate
  high. It counts paths per category and per role instead (3.12).

## 3. Python

### 3.1 `open_document`

```python
def open_document(
    src: str | os.PathLike | bytes | bytearray | memoryview,
    *,
    name: str | None = None,
    strict: bool = True,
    hold_open: bool = False,
    max_file_bytes: int | None = None,
    within: str | os.PathLike | None = None,
    refuse_hard_links: bool = False,
) -> Document
```

- **Read-only.** Nothing in the library writes to, locks or modifies a source
  document. On Windows the file is opened sharing read, write and delete.
- **Only regular files are read.** On Linux and macOS the file is opened
  non-blocking and `fstat` must report a regular file before anything is
  read; on Windows `GetFileType` must report a disk file. A FIFO, socket or
  device (such as `NUL` or `/dev/null`) raises `PathRefusedError` with
  `detail["rule"]` `not_regular_file`, at once: opening a FIFO would otherwise
  wait for a writer for ever.
- `within` (provisional) names a folder the file must lie below, and opens it
  the way the folder listing and `batch` open what the walker found. Nothing
  below that folder is followed: on Linux and macOS every folder on the way is
  opened with `O_NOFOLLOW`; on Windows the open handle's final path must be
  the folder's final path joined with the rest. A link, junction or symbolic
  link on the way raises `LinkRefusedError` (rule `link_in_path`), a path
  outside the folder raises `PathRefusedError` (rule `escapes_root`) before
  anything is opened, and on Windows the file is opened with
  `FILE_FLAG_OPEN_NO_RECALL` and a cloud placeholder raises
  `PlaceholderFileError` before any byte is read. The folder itself may be a
  link (C6).
- Files up to 512 MiB are read whole and the handle is closed before the call
  returns, so a `Document` never stops SOLIDWORKS from saving over the file.
  `hold_open=True` keeps a shared read-only handle instead.
- `name` is the display name, and for bytes input the extension hint used when
  the file stores no document-type GUID. It defaults to the file name of a path.
- `max_file_bytes` refuses a larger file with `FileTooLargeError`. The size
  comes from `fstat` on the open handle, before any byte is read.
- `refuse_hard_links` (provisional) refuses a file with more than one name
  (`st_nlink` above 1 on the open handle) with `LinkRefusedError`, rule
  `hard_link`, before any byte is read: another name for the same data may lie
  outside the folder a caller confines reads to. The REST service sets it.
- **What it raises**, and nothing else for any file content (the hostile-file
  tests enforce this): `FileNotFoundError`, `IsADirectoryError`,
  `PermissionError` (access denied, on every operating system),
  `LockedFileError` (another process holds the file, Windows) and the other
  `SolidSeasError` subclasses in 3.3. Any other exception from a crafted file is
  a bug.
- Values decode lazily. A damaged metadata carrier never raises: it becomes a
  warning. `preview()` raises only when preview streams exist and none decodes,
  and `read_stream()` raises `StreamNotFoundError` for an unknown stream.
- A `Document` is not thread-safe. Use one per thread, and close it or use
  `with`.

### 3.2 `Document`

| Member | Type | Notes |
|---|---|---|
| `path` | `str` or None | None for bytes input |
| `name` | `str` or None | New. `name=`, else the file name of `path`; None for bytes with no name |
| `file_info` | `FileInfo` or None | New. `size`, `mtime_ns`, `modified_utc` (aware UTC) from the open handle. None for bytes input |
| `format` | `"modern"` or `"ole"` | |
| `doc_type` | `"part"`, `"assembly"`, `"drawing"` or None | Changed: never another string. An unknown kind in the Definition GUID is the warning `unknown_document_kind`, and the type falls back to the extension |
| `doc_type_source` | `"definition"`, `"extension"` or `"none"` | New |
| `saved_version` | `SavedVersion` | `.release` is None for a version not in the table |
| `configurations` | `list[Configuration]` | Empty when the file has no carrier (all drawings) |
| `active_configuration` | `str` or None | None for drawings, which have no configurations (they store a date where parts store the configuration name) |
| `configuration(name=None)` | `Configuration` or None | New. Exact name, else a unique case-insensitive match; None means the active one. Unknown names raise `ConfigurationNotFoundError` |
| `properties` | `list[Property]` | File-level custom properties |
| `effective_properties(configuration=None, *, nested=None)` | `list[Property]` | New. File-level properties overridden by the configuration's own, compared case-insensitively; each carries `scope`. `nested` names a nested document to read instead (3.8) |
| `property_values(configuration=None, *, nested=None)` | `dict` | Changed: `{name: value}` of `effective_properties`, so None means the active configuration |
| `material` | `str` or None | The placeholder SOLIDWORKS stores for "no material" is never reported |
| `units` | `dict` or None | `system`, `length`, `mass`, `angle`, `length_decimal_places`; `raw` and `source` are provisional |
| `fields` | `SummaryFields` | New. `title`, `subject`, `author`, `keywords`, `comments`, `last_saved_by`, `created_utc`, `last_saved_utc` |
| `preview(prefer="png", *, nested=None)` | `Preview` or None | None when the file stores no preview |
| `components(configuration=None, *, max_nodes=10_000, max_depth=32)` | `ComponentTree` or None | New. One assembly configuration's component tree (3.8); None for parts and drawings |
| `references()` | `list[Reference]` | The 0.1 list: one per referenced file, with every configuration's instances together. Empty for parts. Each now has `key` (C7). `Reference.quantity` is deprecated (C9) and warns |
| `resolve_references(roots=None, **options)` | `Resolution` | New, provisional. Finds each referenced file on this machine (3.10); the same as `solidseas.resolve.resolve_references(doc, ...)` |
| `display_geometry(configuration=None, **options)` | `DisplayGeometry` or None | New, provisional. An assembly configuration's placed instances and the meshes they share (3.14); the same as `solidseas.geometry.display_geometry(doc, ...)` |
| `bom(configuration=None, **options)` | `Bom` or None | New, provisional. The bill of materials of one assembly configuration, as SOLIDWORKS' BOM tables group and number it (3.16); the same as `solidseas.bom.build_bom(doc, ...)`; None for parts and drawings |
| `tessellate(configuration=None, **options)` | `Tessellation` or None | New, provisional. The triangles of a part's Parasolid bodies in one configuration (3.15); the same as `solidseas.tessellate.tessellate_document(doc, ...)`; None for assemblies and drawings |
| `path_report(*, max_stream_bytes=16 MiB, max_paths=100_000, max_documents=1_000, max_total_bytes=1 GiB)` | `PathReport` | New. Every path and user name the file, and each nested document in it, would reveal to whoever receives it (3.12) |
| `nested(name)` | `Document` | New. The nested document in stream `name` (a virtual or imported component), opened once and closed with this one. An unknown name raises `StreamNotFoundError` |
| `warnings` | `list[ReaderWarning]` | Changed: each is a `str` (the 0.1 text) with `code`, `stream` and `message` |
| `summary(include=("properties", "configurations"), *, nested=None)` | `dict` | New. The `document_summary` data, exactly what the CLI and REST return |
| `info()` | `dict` | Deprecated in favour of `summary()`, and warns (`SolidSeasDeprecationWarning`) from 0.2.0; kept until 0.3 at the earliest |
| `reference_set(configuration=None)` | `ReferenceSet` | New. The `references` data as objects (3.8): every referenced file, keyed as in C7, with the counts of `configuration` (None: the active one; 0 for a file it does not use; None for a drawing's models) and `per_configuration`. The replacement for `Reference.quantity`. Its `sheets` is provisional, as `sheets()` is |
| `sheets()` | | Provisional. A drawing's sheets and their views |
| `metadata`, `container`, `streams()`, `read_stream()`, `nested_documents()`, `open_nested()`, `mesh()`, `parasolid()`, `embedded_paths()` | | Provisional. `parasolid()` also takes `max_total_bytes` and `configurations` (configuration ids, to read only those), and its result says how many bytes it inflated (`bytes_inflated`) |

`Property` has `name`, `value`, `text`, `type`, `expression`, `linked`, and the
new `scope` (`"file"` or `"configuration"`) and `configuration` (its
configuration's name, or None). `date` (new in 0.2.122) is a date property's
calendar day, a `datetime.date` (5.3 says how it is worked out), and None for
the other types. `type` changed from display labels to tokens:
`"text"`, `"number"`, `"boolean"`, `"date"` or `"other"`; `type_label` gives the
label SOLIDWORKS shows. `value` follows the token: `str`, `int` or `float`,
`bool`, `datetime.datetime`, or None for `"other"` and for stored text that does
not parse as its type (with the warning `property_value_unreadable`). Dates are
aware UTC when the source carries a zone (FILETIME, or text with an offset) and
naive otherwise; FILETIME 0 and anything at or before 1601 mean "not set" and
give None. `linked=True` means `value` is SOLIDWORKS' cached evaluation of
`expression`, which can be stale: the property is linked to a model value or
another property, such as `"SW-Mass@Part1.SLDPRT"`. A property that is not
linked can still have an `expression` other than its `text`: the value as it was
typed, which the file keeps beside the stored form. Fixture o14's date has
`expression` `3/15/2024` and its number `3.25` (stored as `3.250000`), and both
have `linked` false, as SOLIDWORKS reports them. `docs/FORMAT.md` 11.1 gives the
rule. `pid`, `vt`, `type_id`, `is_equation` and `expression_source` are
provisional.

### 3.3 Errors

Every exception SolidSeas raises on purpose derives from
`solidseas.SolidSeasError` and has `code`, the stable error code (section 5.6),
and `detail`, a dict of safe facts or None. Every 0.1 class keeps its name and
its bases, so existing `except` clauses catch exactly what they caught before.

| Class | Bases | `code` |
|---|---|---|
| `SolidSeasError` | `Exception` | `internal` |
| `InvalidArgumentError` | `SolidSeasError`, `ValueError` | `invalid_argument` |
| `SldError` | `SolidSeasError` | `damaged_file` |
| `UnknownFormatError` | `SldError` | `unknown_format` |
| `LockedFileError` | `SldError`, `OSError` | `locked` |
| `SldFormatError`, `SldIntegrityError`, `ParasolidError` | `SldError` (the last two through `SldFormatError`) | `damaged_file` |
| `SldLimitError` | `SldFormatError` | `limit_exceeded` |
| `FileTooLargeError` | `SldLimitError` | `file_too_large` |
| `StreamNotFoundError` | `SolidSeasError`, `KeyError` | `stream_not_found` |
| `ConfigurationNotFoundError` | `SolidSeasError`, `KeyError` | `configuration_not_found` |
| `NoPreviewError` | `SolidSeasError`, `LookupError` | `no_preview`: the caller needed a preview and the file stores none |
| `NothingToExportError` | `SolidSeasError`, `LookupError` | `nothing_to_export`: an export (3.17, 3.19) of a document with nothing to export; provisional |
| `NotRepresentableError` | `SolidSeasError`, `ValueError` | `not_representable`: a STEP export (3.19) refused geometry it cannot write without loss; `bodies` lists each body refused with its reason; provisional |
| `PathRefusedError` | `SolidSeasError`, `ValueError` | `path_refused`; `detail["rule"]` names the rule |
| `LinkRefusedError` | `PathRefusedError` | `link_refused` |
| `OutputRefusedError` | `PathRefusedError` | `output_refused`; `solidseas.cli.Refused` is the same class |
| `PlaceholderFileError` | `SolidSeasError`, `OSError` | `placeholder_file` |
| `WorkerTimeoutError` | `SolidSeasError`, `TimeoutError` | `timeout` |
| `WorkerCrashedError` | `SolidSeasError` | `worker_crashed` |
| `WorkerJobError` | `SolidSeasError` | the code of the error inside the worker process (3.13) |
| `BindRefusedError` | `SolidSeasError` | `bind_refused`: `solidseas serve` refused a non-loopback address (8.2) |
| `TokenFileError` | `SolidSeasError` | `token_file_refused`: the service's token file cannot be used (8.3) |
| `AddressUnavailableError` | `SolidSeasError` | `address_unavailable`: the service could not listen on its port (8.1) |
| `NotInCatalogError` | `SolidSeasError`, `LookupError` | `not_in_catalog`: the catalog holds no row for that file (3.18); provisional |
| `CatalogIncompatibleError` | `SolidSeasError` | `catalog_incompatible`: not a catalog, written by a newer SolidSeas, or damaged (`detail["rule"]` says which, 3.18); provisional |
| `BusyError` | `SolidSeasError` | `busy`: another process or scan is updating the catalog (3.18); provisional |
| `FormatNotSupportedError` | `SolidSeasError` | `format_not_supported`: a 3D format SolidSeas knows but cannot read (`detail["rule"]` `no_reader`), or a feature of one file that stops it being read (3.20); `detail["value"]` names the format or the feature; provisional |
| `UnsupportedOperationError` | `SolidSeasError`, `NotImplementedError` | `not_implemented`: an operation for SOLIDWORKS documents asked of another 3D file (`detail["rule"]` `model_file`, `detail["value"]` its format id, 3.20); provisional |
| `DrawingInvalidError` | `InvalidArgumentError` | `drawing_invalid`: a `.ssdrw` refused whole (not a SolidSeas drawing, not strict JSON, a newer schema, outside the bounds); `detail["rule"]` is `drawing_invalid` and `detail["value"]` names the check; `solidseas.drawing.document.DrawingFileError` derives from it (3.24); provisional |
| `DrawingTooComplexError` | `SldLimitError` | `drawing_too_complex`: a part or drawing past a bound of `DrawingLimits`, `detail["limit"]` naming it (3.24); provisional |
| `ModelNotFoundError` | `InvalidArgumentError` | `model_not_found`: a drawing's model is not where the drawing says, or only changed files were found (`detail["rule"]` `model_not_found`, 3.24); provisional |
| `DrawingReleasedError` | `InvalidArgumentError` | `drawing_released`: a RELEASED drawing refused a change until a revision is started (`detail["rule"]` `drawing_released`, 3.24); provisional |

Outside that tree, `FileNotFoundError`, `NotADirectoryError` and
`IsADirectoryError` map to `not_found`, `PermissionError` to
`permission_denied`, `TimeoutError` to `timeout`, `NotImplementedError` to
`not_implemented`, and anything else to `internal`.
`solidseas.model.error_info(exc)` is the one place that does this mapping.

The four drawing classes derive from the class the drawing code raised before
their codes existed, so `except InvalidArgumentError` and `except SldLimitError`
still catch them, and their `detail["rule"]` is unchanged.

`PermissionError` means access denied on every operating system. Only a Windows
sharing or byte-range lock raises `LockedFileError`; on Linux and macOS, which
have no mandatory share modes, a permission problem is never reported as a
lock. A folder passed as a file raises `IsADirectoryError` on Windows too, and
a pipe, socket or device raises `PathRefusedError`.

`detail["rule"]` of a `PathRefusedError` or `LinkRefusedError` raised while
opening a document is one of `not_regular_file`, `escapes_root`,
`link_in_path` and `hard_link`. An `OutputRefusedError` from the command line's write guards
names its rule as well: `source_folder`, `source_document`, `solidworks_file`,
`exists`, `link`, `hard_link`, `device_path`, `alternate_stream`,
`no_file_name`, `output_extension` or `output_folder`. Rules are an open set.

### 3.4 `None` and the active configuration

Wherever a configuration is optional (`configuration()`,
`effective_properties()`, `property_values()`, the `properties` kind), None
means the active configuration. When the file names no active configuration,
the effective properties are the file-level ones.

### 3.5 Warnings

`ReaderWarning` is a `str` subclass holding the readable text, so code written
for 0.1's string warnings keeps working. It also has `code`, `stream` and
`message`, and `to_dict()` gives the JSON warning object. Warning text can
quote document content, such as a configuration or material name; the service
never logs it. Reference resolution adds the codes listed in section 5.10.
The reader's codes (an open set):

| Code | Meaning |
|---|---|
| `container_name_not_utf8` | A stream name is not UTF-8 and was decoded as IBM437 |
| `container_header_mismatch` | A local header disagrees with its directory copy (`strict=False` only) |
| `container_crc_constant` | Every member declares the same CRC-32, so only sizes are checked |
| `ole_parsing_issue` | `olefile` reported a problem it worked around |
| `zlb_magic_missing` | A `__ZLB` stream lacks the ZLB magic and is exposed raw (`strict=False` only) |
| `stream_too_large` | A metadata stream is over its size cap and was skipped |
| `stream_unreadable` | A metadata stream could not be read |
| `xml_doctype_refused` | An XML stream declares a DOCTYPE or ENTITY and was refused |
| `xml_parse_error` | An XML stream could not be parsed |
| `property_set_error` | A legacy property set stream is malformed |
| `property_value_unreadable` | A property value does not parse as its declared type |
| `unknown_document_kind` | The Definition GUID names a kind other than part, assembly or drawing |
| `materialtree_unknown_configuration` | `MATERIALTREE` names a configuration no other carrier has |
| `material_mismatch` | `KeyWords` and `MATERIALTREE` name different materials |
| `version_prefix_ambiguous` | More than one `_MO_VERSION_<n>` prefix |
| `version_prefix_missing` | No `_MO_VERSION_<n>` prefix |
| `version_history_missing` | The `History` stream is missing |
| `version_history_unreadable` | The `History` stream could not be parsed |
| `version_history_mismatch` | `History` ends with another version than the prefix |
| `preview_undecodable` | Preview streams exist but none decodes |
| `value_not_representable` | An integer beyond 2^53 - 1 was sent as null; `text` keeps the digits |
| `non_finite_number` | A NaN or infinite number was sent as null |
| `transform_unreadable` | A stored component transform is not 16 finite numbers; the instance's `transform` and `placement` are null |
| `duplicate_instance_name` | Two instances under one parent share a name; later ids get `#2`, `#3`... |
| `component_model_missing` | An instance names a model the component tree does not hold; its `children_state` is `unknown` |
| `configuration_not_described` | The component tree holds no component list for the configuration asked for |
| `drawing_sheets_unreadable` | A drawing's list of sheet names could not be read; its sheets come from `KeyWords` |
| `bom_properties_unread` | A BOM row's file was not found or could not be read (or a limit stopped it): its description and property columns are unknown, and the row keeps what the assembly stores (3.16) |
| `bom_configuration_missing` | A BOM row's file lists configurations, but none of the name the assembly uses; its file-level properties are used |
| `bom_configurations_unknown` | SolidSeas finds no configuration at all in a BOM row's file, so the one the assembly uses could not be looked up; its file-level properties are used |
| `bom_children_missing` | A sub-assembly's components are missing from an indented or parts-only BOM: a limit or a cycle stopped the tree there, or the tree does not list them while its own file does or was not read to check |
| `bom_children_differ` | The instances of a sub-assembly in one configuration list different components (a damaged or crafted tree): an indented BOM lists the components of every instance under it |
| `bom_part_number_may_differ` | A BOM row's configuration stores an alternate name (`alternate_name`) that SOLIDWORKS shows as the part number when the configuration is set to; the document name is given (3.16) |
| `bom_limit_reached` | A limit of the BOM (`max_files`, `max_seconds`) stopped the reading of some files |

The catalog's where-used (3.18, provisional) adds these, besides the
resolution codes its references carry:

| Code | Meaning |
|---|---|
| `cycle` | A document is reached again through its own sub-assemblies; it is not followed twice |
| `low_confidence` | The reference was resolved with low confidence (an identity that differs): the use may be another file's |
| `quantity_unknown` | The assembly names the file but stores no component tree to count its instances; nothing above it is followed |

Exports for 3D printing (3.17, provisional) add theirs:

| Code | Meaning |
|---|---|
| `display_mesh_fallback` | A part, or an assembly's component, is exported from its saved display mesh because its solid bodies could not be had (none stored, its file not found, a limit); it may not be closed |
| `not_closed` | An exported object is not closed: some edge is not used twice, once each way |
| `bodies_left_out` | Bodies that are not solids (surfaces, wires) are left out of the export |
| `faces_left_out` | Faces that could not be tessellated leave holes in an exported object |
| `instances_left_out` | Instances of the assembly that could not be placed or meshed are left out |
| `shell_reoriented` | A closed shell of an exported object was inside out (it lay in no other shell, or every shell of the object faced the wrong way) and was turned round |
| `shells_not_judged` | An exported object has more closed shells than the 64 whose nesting is worked out, so which way they face was not checked |

The tessellator's self-checks (3.15, provisional) each give a warning of their
own code when they find something, on a `Tessellation` and on the scene of a
format whose B-rep it draws (3.20.7):

| Code | Meaning |
|---|---|
| `loops_reversed` | Faces whose loops all ran against them, on a surface that does not close (or on a closed one where those loops leave no surface outside them), are drawn facing the way the file says, their loops read the other way round (a repair, as other readers make it; a face that then disagrees with its neighbours is turned with them) |
| `faces_folded` | Faces whose triangles fold over one another: their absolute (u, v) areas add up to more than their polygon's, some have area in space but none in (u, v), or (where the (u, v) polygon touched itself) some stretch across the face, over ten times the surface's area over their (u, v) triangle |
| `faces_coarse` | Faces that reached `max_face_points` with triangles still farther from their surface than the chord tolerance |
| `solids_not_closed` | Solids whose triangles do not use every edge once each way (a face left out, a fold) |
| `shells_inside_out` | Closed shells that face the wrong way for how they nest: a solid inside out, or a void facing out (in an export, one facing outward inside another, or one that touches another so that which lies inside which cannot be told, left as it is) |

STEP exports (3.19, provisional) add theirs, and use `bodies_left_out` too, for
a body hidden in SOLIDWORKS, a sheet not asked for and a wire body, each said in
its own words:

| Code | Meaning |
|---|---|
| `step_approximated` | The file holds B-splines in place of curves or surfaces STEP cannot hold exactly, within the deviation it reports |
| `step_bodies_left_out` | Bodies that cannot be written without loss are left out whole, as `allow_partial` asked |
| `step_hidden_bodies_unknown` | The part has several solid bodies and every one is written, but it does not say whether some of them are hidden (imported bodies may carry no mark): SOLIDWORKS leaves hidden bodies out of its own STEP |
| `step_differs_from_display` | The bodies the part stores differ from what SOLIDWORKS last displayed (their boxes are more than 1% of the diagonal apart); the file holds the stored bodies |
| `step_tolerant_geometry` | Edges or vertices are tolerant, with gaps of 1e-3 mm or more and larger than the file's uncertainty; they are written as Parasolid holds them |

Model files (3.20, provisional) add these; each format's own codes are in its
subsection of 3.20:

| Code | Meaning |
|---|---|
| `units_assumed` | The file states no unit of length (an STL, an OBJ...); millimetres were assumed, and `units.source` is `assumed` |
| `extension_mismatch` | The file's content is another format than its extension says; it is read as what it holds |
| `non_rigid_transform` | A placement scales, shears or mirrors its object; it is kept as stored |
| `degenerate_triangles_dropped` | Triangles with a repeated corner, or a corner that is not a finite number, were left out |
| `indices_out_of_range` | Triangles naming a vertex the mesh does not have were left out |
| `coordinates_out_of_range` | Triangles with a corner more than 1,000 km from their object's origin were left out |
| `colors_ignored` | Colours the file stores were not kept: too many for one object, or a convention SolidSeas does not read |
| `text_truncated` | A name, property or metadata value was longer than `text_bytes` and was cut |
| `component_not_found` | A component the document places could not be found or read; it is left out of the scene |

### 3.6 Folder listings: `scan`

```python
from solidseas import scan

listing = scan("D:/Jobs/Example", include=("properties", "preview"))
for entry in listing:                          # plain JSON data, one entry per document
    if entry["error"]:
        print(entry["path"], entry["error"]["code"])    # one bad file never stops the scan
print(listing.counts)

data = scan("D:/Jobs/Example", recursive=True).listing()   # the whole listing kind at once
```

```python
def scan(
    folder: str | os.PathLike,
    *,
    recursive: bool = False,
    include: Collection[str] = ("preview",),
    max_depth: int = 32,
    max_entries: int | None = None,
    max_examined: int | None = 1_000_000,
    max_seconds: float | None = None,
    max_preview_data_bytes: int = 8 << 20,
    reader_message: bool = True,
    pool: WorkerPool | None = None,
    file_timeout: float | None = None,
    within: str | os.PathLike | None = None,
    root_id: str | None = None,
    folder_rel: str = "",
    after: str | None = None,
    formats: str | Iterable[str] = "solidworks",
    foreign_pool: WorkerPool | None = None,
    threads: int = 1,
) -> Scan
```

A `Scan` is iterated once, for the entries of section 5.7, or `listing()`
returns the whole `listing` data. Afterwards `counts`, `truncated_reason`,
`preview_data_capped` and `walk_stats` say what happened.

- `include` picks the optional parts of each entry: `properties` (the effective
  properties of the active configuration), `configurations`, `preview` (the
  summary's preview object; the default) and `preview_data` (the image itself,
  base64, at most `max_preview_data_bytes` of text in one listing). An unknown
  name raises `InvalidArgumentError`.
- `recursive=False` lists the folder itself, with each subfolder as an entry of
  its own. `recursive=True` walks the subfolders, at most `max_depth` levels
  deep; a folder at that depth is an entry with status `skipped` and reason
  `max_depth`.
- Three bounds stop the listing early, and `truncated_reason` then names the
  one that did: `max_entries` (entries listed), `max_examined` (directory
  entries the walker looked at, documents or not) and `max_seconds`
  (`deadline`). `max_entries` alone does not bound the walk: to report a
  listing as complete, the walk must look through the rest of the tree for
  one more document, so over a huge tree with few documents it is
  `max_examined` that bounds the work.
- **The bounds are checked between entries.** A document that is slow to read,
  or a folder listing that blocks on a share that stopped answering, runs past
  `max_seconds` until it returns. With a `pool` (section 3.13) each document is
  read in a worker process instead, with `file_timeout` as its own deadline: a
  file that hangs or crashes its worker becomes an error entry (`timeout`,
  `worker_crashed`) and the listing goes on. `pool` and `file_timeout` are
  provisional, as the worker pool is (section 9).
- `threads` (1 to 32, provisional) reads that many documents at once, in
  threads, a few ahead of the entry yielded. On a network share most of a
  document's time is the round trips to the server, and these then overlap.
  The entries, their order, the counts and the inline images are exactly those
  of `threads=1`; only the bounds are checked against the entries yielded, so a
  listing they stop may have read a few documents more than it lists.
- The other options are what the REST service pages with (provisional):
  `within` is the folder documents are opened below (the listed folder when not
  given; a pool with roots needs one of them), `root_id` and `folder_rel` give
  the listing's `root` and `folder` and prefix every entry's path, and `after`
  resumes after the entry with that path, in the walker's order.
  `Scan.fingerprint()` hashes what a listing would cover from the directory
  entries alone, without opening a file (the service's `ETag`).
- `formats` (provisional) chooses the files listed: `"solidworks"` (the
  default: SOLIDWORKS documents only, the listing exactly as before), `"all"`,
  or format ids of the registry (3.20.3), alone or comma-separated
  (`"stl,3mf"`). A file of a format SolidSeas reads is opened with `open_any`
  and becomes an entry with status `ok`, its SOLIDWORKS fields null and a
  `model` object (5.7); with a pool it is read by the job `model_entry`, in
  `foreign_pool` when one is given, else in `pool`. With a `foreign_pool` and no
  `pool` (a desktop application reading SOLIDWORKS documents in its own threads
  and everything else in workers), a file wearing a SOLIDWORKS extension over
  another format's content is read in `foreign_pool` too when `open_document`
  finds no SOLIDWORKS container in it: the caller's process then looks only at
  its first bytes. A compound file (an Alibre, Inventor or Solid Edge file
  renamed) or a 2015+ container is a SOLIDWORKS container to `open_document`:
  it is read in the caller's process as the SOLIDWORKS document its name says,
  its compound-file directory and streams parsed there as for any `.sldprt`,
  and listed as one (3.20.3: the extension picks among compound-file
  formats). A file of a format SolidSeas
  lists but cannot read yet is an entry with status `unsupported` and is never
  opened. A Solid Edge `.asm` is listed only when the file starts with the
  compound-file signature, and an NX `.prt` not at all, since other programs
  use those extensions. A file wearing a SOLIDWORKS extension whose content is
  another format SolidSeas reads, and is no compound file or 2015+ container,
  is read as that format when `formats` names it (warning
  `extension_mismatch`); in a default listing it stays an error entry, or
  `not_solidworks` for STEP, as before. An unknown id raises
  `InvalidArgumentError`.
- Only the folder argument raises: `FileNotFoundError`, `NotADirectoryError`
  or `PermissionError`. A problem with one file becomes that entry's `error`.
  `reader_message=False` leaves the exception text out of those error objects,
  as the REST service does.
- **What the walk found is what is read.** Each document is opened `within`
  the listed folder (section 3.1). A name that became a link after its folder
  was listed is refused (`link_refused`), and a file that became a placeholder
  is not recalled (`placeholder_file`); both are error entries.
- **Reading less.** Each document is opened with `hold_open=True` through an
  unbuffered handle, only the streams its entry needs are read (the directory,
  the metadata carriers, the version history and the preview image), and the
  handle is closed before the next file is opened. Measured on the development
  corpus with properties, configurations and previews, listing each of the 299
  folders that hold its 3,527 documents (3,823 entries: the documents and 296
  subfolders): the listing read 4.6% of the 2,983 MB of those documents
  (137 MB), against 100% for opening each file whole. It took 8.4 s on one
  thread with the file cache warm (7.9 s without the `within` check) and 21 s
  on a cold first pass, and held each file open for 2.7 ms at the median,
  12.6 ms at the 99th percentile and 50 ms at most. The preview image is most
  of what is read, because its `sha256` needs all of it.

### 3.7 The folder walker: `solidseas.walk`

`Walk(root, *, recursive=True, max_depth=32, max_examined=1_000_000,
max_seconds=None)` is the one walker behind `scan`, the `batch` command and
the reference-resolution index (3.10). Its Python API is provisional; its
rules are not:

- Breadth first, one `os.scandir` per folder, each folder's entries sorted
  case-folded, and every entry decided from
  `DirEntry.stat(follow_symlinks=False)`. On Windows that comes with the
  directory listing itself, with no extra call per entry, which matters on a
  file share. On Linux and macOS it costs one `lstat` per entry.
- **A link is never followed.** On Windows an entry is a link when it carries
  the reparse-point attribute and its reparse tag is a junction
  (`0xA0000003`), a symbolic link (`0xA000000C`), any other tag with the
  name-surrogate bit `0x20000000`, or 0 (an unreported tag fails closed). An
  entry for which `is_symlink()` or `is_junction()` is true is a link too.
  Deduplicated files (`0x80000013`) and cloud folders (`0x9000701A`) carry
  other tags and are ordinary entries. A link is reported with status `link`
  and a reason: `junction`, `symlink`, `name_surrogate` or `unreported_tag`.
- **A mount point is a link.** On Windows a volume mounted in a folder carries
  the junction tag. On Linux and macOS an entry whose `st_dev` differs from
  the root's lies on another filesystem (a bind, network or FUSE mount) and is
  reported as a link with reason `mount_point`, so the same tree lists the
  same way on every platform. A Linux btrfs subvolume has a device of its own
  and counts as one.
- **Only regular files are files.** On Linux and macOS a FIFO, socket or
  device is reported as skipped with reason `not_regular_file` and never
  opened, whatever its name.
- **A cloud placeholder is never opened.** An entry with
  `FILE_ATTRIBUTE_OFFLINE` (`0x1000`), `RECALL_ON_OPEN` (`0x40000`) or
  `RECALL_ON_DATA_ACCESS` (`0x400000`) has its data elsewhere, and opening it
  would start a download. It is reported with its name and size, status
  `placeholder` and the attribute as reason; a placeholder folder is not
  entered.
- **A SOLIDWORKS lock file** (`~$` before the document's name) is reported as
  skipped, reason `lock_file`, and never read.
- A folder that cannot be listed is an error entry, and the walk goes on. Only
  the root raises. The root may itself be a junction or a link: a root is the
  caller's configuration (C6).
- A file's entry carries `file_id` (`"<st_dev>:<st_ino>"` in hex) where the
  listing gives one, which is Linux and macOS: a Windows listing carries no file
  index. The catalog (3.18) follows a moved file by it.
- `stats` counts the folders listed, directory entries examined, files, links,
  placeholders, skipped entries, errors and folders left out by `max_depth`;
  `truncated` names the bound that stopped the walk early (`max_examined` or
  `deadline`), as `scan` and `batch` report it. Both bounds are
  checked between entries, so a listing call that blocks runs past the
  deadline until it returns.
- The walk classifies a folder's entries when it reaches them, and its
  callers read files after that. Anything that opens a file the walk found
  must therefore not trust it blindly: `scan` and `batch` open it `within` the
  root (section 3.1).

### 3.8 Component trees: `components()`

```python
with open_document("D:/Jobs/Example/frame.SLDASM") as doc:
    tree = doc.components()                    # the active configuration
    for node in tree.walk():                   # depth first, stored order
        f = tree.files[node.file] if node.file else None
        print("  " * node.depth, node.name, f and f.file_name, node.configuration,
              node.placement.translation_m if node.placement else None)
    lite = doc.components("Lite")              # another configuration: its own instances
    part = doc.nested(tree.files["29"].nested) # a virtual part stored inside the assembly
    print(part.property_values())
```

`components()` returns a `ComponentTree` for an assembly and None for a part
or a drawing. Its objects are frozen dataclasses holding what the `components`
JSON kind holds (section 5.9): `ComponentTree` (`configuration`,
`configuration_source`, `configurations_described`, `children_state`,
`files`, `children`, `truncated`, `node_count`, `depth`, `max_nodes`,
`max_depth`, `warnings`, and `walk()`), `ComponentNode`, `ComponentFile`,
`Transform` and `Placement`. `Placement.apply(point)` maps a point of the
component (metres) into the other frame and `Placement.then(inner)` composes
two placements.

The Python objects and the JSON carry the same values, but not always under
the same name or in the same form:

| Python | JSON |
|---|---|
| `ComponentTree.files`, `ReferenceSet.files`: a dict by file key | `files`: a list in first-seen order, each with its `key` |
| `ComponentTree.node_count`, `depth` | `counts.nodes`, `counts.depth` (and `counts.files`) |
| `ComponentTree.max_nodes`, `max_depth` | `limits.max_nodes`, `limits.max_depth` |
| `ComponentTree.walk()` | `instances` with `flat` (and `children` without) |
| `Document.material`: the name alone (the database is `Document.metadata.material_database`, provisional) | `material`: `{"name", "database"}` |
| `Resolution.allow_outside_roots` | `resolution.outside_roots` |
| `Location.host_path` (match and candidates) | never sent |
| `Property.value` of a date: a `datetime` | ISO 8601 text |
| `ComponentNode.alternate_name` | not in `components`; a `bom` row's `alternate_name` (3.16) |
| `Bom.columns`: the property columns only | `property_columns`; `columns` is the whole header, `ITEM NO.` to the last property column |
| `Bom.counts["seconds"]` | not sent (the `bom` kind's `counts` has the other six) |
| `BomRow.properties`, `values`, `notes`, `instances`, `nested`: tuples | lists |

- **Which configuration.** A name is matched exactly, then as a unique
  case-insensitive match. None means the active configuration, else the one
  the tree marks as most recently used, else the first the tree describes.
  `configuration_source` says which rule chose it. A name no carrier knows
  raises `ConfigurationNotFoundError`; a name the document knows but the tree
  has no component list for gives `children_state: "unknown"` and the warning
  `configuration_not_described`.
- **One tree per configuration.** The file stores a separate list of
  instances for each assembly configuration, so what differs between
  configurations (instances present, suppressed, referenced configuration,
  placement) is what differs between `components(a)` and `components(b)`;
  the `references` kind gives each file's counts in every configuration side
  by side.
- **Limits.** `max_nodes` (1 to 1,000,000) and `max_depth` (1 to 64) bound the
  expansion. A tree that reaches one is cut there, `truncated` is true and the
  node where it stopped has `children_state: "truncated"`; it never raises for
  size. A sub-assembly already on the path is not expanded again
  (`children_state: "cycle"`). Instance counts in a truncated tree are lower
  bounds. On the development corpus the largest tree has 725 instances and 6
  levels, and building it takes under 0.2 s.
- **Without a tree.** One corpus assembly has no component tree. Its
  `children_state` is `unknown`, `children` is empty and `files` are its
  `Header2` paths, keyed `header2:<n>`, with null instance counts.

### 3.9 What the stored values mean

`docs/FORMAT.md` sections 12.1 to 12.5 hold the evidence and the counts behind
each of these.

- **Transforms.** `swTransform` holds 16 numbers. Elements 0 to 2, 4 to 6 and
  8 to 10 are the images of the component's X, Y and Z axes in the parent's
  frame, which makes them the columns of the rotation `R` in
  `p_parent = R p + t`; elements 12 to 14 are `t` in metres; element 15 is a
  scale; elements 3, 7 and 11 are zero. Read as a 4 x 4 matrix stored row by
  row, it is the row-vector form `p_parent = p M`. `transform.rotation` is `R`
  row by row. Each stored transform is relative to the parent instance, and
  `placement` composes it with every parent's into the top assembly's frame,
  which is what SOLIDWORKS' `Component2.Transform2` reports. Verified against
  the `IMathTransform.ArrayData` SOLIDWORKS 2024 reported for every instance
  of the three fixture assemblies, to 6e-17: rotations of 90 degrees
  about X and about Z, 40 degrees about (1, 1, 1), and parts inside a rotated
  sub-assembly. On the development corpus all 8,688 stored transforms are
  proper rotations with elements 3, 7 and 11 zero and element 15 equal to 1;
  the scale is reported but never applied.
- **Hidden.** `swHidden` is `YES` on every suppressed instance (402 of 402 on
  the development corpus), so the flag means "hidden or suppressed". `hidden`
  is meant to be what SOLIDWORKS reports: a top-level part instance takes its
  configuration's display state (`swShowState` per instance) when that lists
  it, and any other instance, a sub-assembly instance included, is hidden when
  `swHidden` is `YES` and it is not suppressed, so a suppressed part is hidden
  only when the display state says so (16 suppressed top-level instances on the
  corpus). A sub-assembly's `swShowState` is `No` for sub-assemblies SOLIDWORKS
  draws, so it is not used: on the corpus, where it disagrees with the flag in
  the active configuration, the parts the flag shows fill the box SOLIDWORKS
  stores for the assembly in 6 of 6 assemblies, and those the display state
  shows in 2 (FORMAT 12.1). Only one case is checked against SOLIDWORKS itself:
  on fixture o16 a suppressed instance with `swHidden` `YES` is reported
  visible, whether its display state says `Yes` or the configuration has no
  display state. No fixture has a hidden instance, so that the display state
  decides for a part, and that `swHidden` hides an unsuppressed instance, are a
  HYPOTHESIS (FORMAT 12.1, with the controlled file that would settle it). For
  unsuppressed top-level instances the display state and the flag agree in
  3,922 of 3,933 corpus cases.
- **Suppressed and excluded parents.** The tree stores the children of a
  suppressed sub-assembly, and they are listed with their own flags; SOLIDWORKS
  itself lists no children of a suppressed component. `instances_unsuppressed`
  and `instances_in_bom` follow the parents: a child of a suppressed
  sub-assembly is not counted as unsuppressed, and a child of a suppressed or
  excluded one is not in the BOM. `instances_in_bom` counts every level, so it
  matches SOLIDWORKS' indented BOM table on fixture o19, the drawing of o16
  (per file, the quantities of all its rows added up). SOLIDWORKS' top-level
  BOM table there matches the top-level instances that are neither suppressed
  nor excluded, counted per file from `children`, not `instances_in_bom`
  (o02_boxA is 3 in BOM through every level and 2 at the top).
- **Virtual components** are stored inside the assembly as nested documents.
  A virtual file the top assembly uses directly is the stream
  `VirtualComp/<stored name before the caret>`, or that name followed by `-`
  and the extension without its dot (`VirtualComp/Part12-sldprt`, as
  SOLIDWORKS 2024 writes it). On the development corpus 125 of the 129 direct
  virtual files map this way (120 and 5), and each of the 125 opens as a
  document of the stored type with the creation time the tree stores for it;
  why the other 4 have no stream is unknown. A virtual file used only inside a
  sub-assembly is stored in that sub-assembly's own file (445 of the 446 the
  corpus lets one check) and is marked `embedded_in_subassembly` (511 on the
  corpus).
- **Imported components** carry `swImportedPath`. When the stream
  `ImportedComp/<stored file name>` exists (239 of 555 imported files on the
  corpus, each with the stored creation time) the file is `embedded` there;
  otherwise it is an ordinary file on disk, as reference resolution finds 228
  of the other 308 that are not virtual (HYPOTHESIS for the rest).
- **Drawings** have no component tree. Their models are the `Header2` paths,
  provisionally (`direct` is null). Their sheets are
  `SheetPreviews/SheetNames`, which agrees with the sheet count SOLIDWORKS
  stores in 22 of 22 corpus drawings, and each sheet's views (view name, the
  model's configuration and file name) come from `swXmlContents/KeyWords`.
  Sheets, view names and models are verified against SOLIDWORKS on the two
  fixture drawings, o18 and o19. A view's configuration is a HYPOTHESIS: every
  view on the fixtures shows `Default`, the model's active and first
  configuration (o16, which o19 shows, also has `Lite`, which no view shows),
  and every corpus view whose model could be checked shows `Default` of a
  model that has no other configuration, so a constant would match as well and
  the field stays unproven. The corpus has no drawing with more than one sheet
  or model, so those are untested too.
- **Not exposed.** Whether an instance belongs to a component pattern, and
  whether it is fixed, are not in the component tree (fixture o16 has a
  pattern), so neither is reported. `swFlexible` and `swComponentReference`
  stay unexposed until a fixture settles their meaning.

### 3.10 Reference resolution: `solidseas.resolve`

A document stores, for each file it references, the absolute path the file had
when the document was last saved, and the file's creation time. Folders get
moved, copied, synced and renamed, so the stored path is often stale.
`resolve_references` finds each referenced file on this machine the way
SOLIDWORKS' own search routine does, inside the folders it is given, and checks
every answer against the stored creation time. The Python API is provisional.

```python
from solidseas import Root, Roots, open_document
from solidseas.resolve import resolve_references

with open_document("D:/Jobs/Example/frame.SLDASM") as doc:
    res = resolve_references(doc)                     # root: the document's own folder
    roots = Roots([Root("jobs", "D:/Jobs"), Root("std", "E:/Library", role="library")])
    res = resolve_references(doc, roots, path_map=["S:\\=E:/Library"])
    for key, r in res.results.items():                # keys as in components and references (C7)
        print(key, r.status, r.rule, r.confidence, r.match and r.match.host_path)
```

```python
def resolve_references(
    doc,
    roots=None,
    *,
    path_map=(),                  # "FROM=TO" strings or (FROM, TO) pairs
    allow_outside_roots=True,     # point lookups outside the roots, local drives only
    max_examined=250_000,         # directory entries the walks of this call may examine
    max_seconds=15.0,             # for this call's walks and identity reads
    max_candidates=20,            # candidates read and reported per reference
    max_identity_reads=5_000,     # documents opened to read their identity
    cache=None,                   # an IndexCache shared by many calls
    skip_unavailable_roots=False, # search without a root that cannot be walked
) -> Resolution
```

- `roots` is a `Roots`, `Root` objects or `{id: folder}` (3.11). None searches
  the document's own folder, recursively, as root `document`. Roots are
  searched in the order given, so list project roots before library roots.
- `path_map` reads stored paths that start with FROM (a drive `S:\` or a share
  `\\host\share`, optionally with folders, compared case-insensitively at a
  component boundary) as starting with TO, an absolute folder on this machine
  (a relative TO raises `InvalidArgumentError`). The first mapping that matches
  applies. It is the only way to follow a changed drive
  letter, a share mapped to a letter or a Linux mount: 72 direct references on
  the development corpus store a drive or share other than their document's.
- `Resolution` has `results` (`{key: ResolvedReference}`, in the order of the
  `references` kind), `roots` (each with `index_partial` and
  `truncated_reason`), `index_partial`, `allow_outside_roots`, `truncated`
  (more than 100,000 referenced files: only the first were resolved) and
  `counts()`. `ResolvedReference` mirrors the JSON of section 5.10; its
  `match` and each candidate's `location` are a `Location(root, path,
  host_path)`, where `host_path`, the absolute path on this machine, is for
  Python callers and is never sent as JSON.
- `IndexCache` keeps folder indexes and identities between calls, for a batch.
  An index is a snapshot of its root: make a new cache to see later changes.
  Identities are keyed by path, size and modification time. Without a cache
  each call walks its roots afresh, as the REST service does for each request.
- `skip_unavailable_roots=True` searches without a root whose folder cannot be
  walked (gone, or access denied) instead of raising: that root is listed in
  `roots` with `index_partial` true and `truncated_reason` `unavailable`, and
  every result carries the warning `root_unavailable`. The REST service sets
  it, so a root that went missing never fails a resolution silently.

**The rules, in order.** A hit at rules 1 to 6 whose identity differs is
remembered and skipped.

| # | Rule | What it tries |
|---|---|---|
| 0 | `embedded` | A virtual component, or an imported one whose `ImportedComp/` stream exists, is stored inside the document: status `embedded` (with `nested`), `embedded_not_found` or `embedded_in_subassembly`. Never looked up on disk, even when a file of that name exists |
| 1 | `stored_unmoved` | The document is where it was saved (its folder equals `SW-Folder Name`) and the stored path exists |
| 2 | `path_map` | The first path mapping that matches the stored path |
| 3 | `rebased` | The stored path relative to the folder at save, from where the document is now |
| 4 | `same_folder` | The name in the document's folder |
| 5 | `suffix_probe` | SOLIDWORKS' probe: from the document's folder up to the root that holds it, never above it, the name under the stored folder's last 0, 1, 2... components |
| 6 | `stored_path` | The stored path, for a document that has moved |
| 7 | `name_index`, `name_index_suffix` | The name anywhere under each root, in root order. Files whose identity differs are dropped and identity matches preferred. One left is the match; of several, the one with the unique highest folder-suffix score against the stored folder, when above 0 (`name_index_suffix`); otherwise the result is `ambiguous` |
| 8 | | A file found earlier whose identity differs, with confidence `low` and the warning `identity_mismatch`; otherwise `missing` |

**Identity** compares the stored creation time (`swCreationTime` in the
component tree; for a drawing, its `Header2` reference record) with the one the
file carries about itself: `ModelStamps` element 0, else its own `swFile` in its
component tree, else the `KeyWords` root id, which agree wherever a corpus file
has more than one. The result is `match`, `differ`, or `unknown` when either
side is missing; a creation time of 0, a negative one, or one later than now
plus one day is missing. Save As keeps the creation time, so identity tells a
copy from an unrelated file of the same name, but not copies apart. A file that
cannot be read is `unknown`, with the warning `identity_read_failed`, and the
resolution goes on.

**Names** are compared as NTFS compares them, on every operating system: per
character, by simple uppercase, so "ß" and "ss" stay different names. A name
equal only after NFC normalisation is found with the warning
`normalization_differs`, and a name that differs only by case with
`case_differs`. On a case-sensitive folder two names that differ only by case
are two candidates, so the result is `ambiguous` unless identity decides.

**Where it looks** (C2), always through the one gateway:

- Inside a root, only the root's folder index, built by the shared walker (3.7)
  down to 64 folder levels; nothing behind a link is in it. A root that is not
  recursive covers its own folder only.
- Outside every root, only a point lookup of one known path, when
  `allow_outside_roots` is true and the drive is a local fixed or removable one
  (or the path is under a path mapping's target). The entry is read with
  `lstat` and decided with the walker's rules: a link is not followed, and a
  cloud placeholder is found but never opened (`placeholder_not_read`). A
  junction earlier on such a local path is resolved by the operating system,
  as for any local path: only the path's text is classified.
- A stored UNC path, or a path on a mapped network drive, is never touched
  (`stored_unc_not_checked`, `stored_network_drive_not_checked`). On Linux and
  macOS no stored path is a path on this machine except through a path
  mapping; a path on a network file system's mount (from the mount table)
  is refused outside the roots as a mapped network drive is, unless a path
  mapping's target holds it.
- An identity read opens a document read-only `within` its root, or within its
  own folder outside the roots, so no link below that folder is crossed and a
  placeholder is not recalled. The gateway opens only paths it found itself.
- A stored path whose anchor is not a drive, a share or a bare name, or one with
  a component that fails the `windows-path-confinement` checks (`..`, `:`, a
  device name, a control character, a name without a SOLIDWORKS extension), is
  not used as a location (`stored_path_refused`); a valid name is still
  searched for.

**Limits.** `max_examined` and `max_seconds` bound the walks. When one cuts an
index short, every result carries `index_partial`, a missing one also
`search_incomplete`, and the CLI exits 4. `max_identity_reads` and the deadline
stop identity reads: a file not read is `unknown`, and its result carries
`search_incomplete`.

**Phase 1 scope (C7).** Only the top document's own tree is resolved, in its own
context: files inside sub-assemblies are resolved from the paths the top
document stored (`from_parent_tree`), and a file used by more than one parent
document carries `context_varies`. Recursion into sub-assemblies, version
stamps and index refreshes are left for later.

**Measured on the development corpus** (the 351 documents that open: 325
assemblies and 26 drawings, with 3,199 direct references that are not virtual,
952 inside sub-assemblies, 26 drawing models and 640 virtual files), read-only,
with no file changed. All three configurations together took 12 s in one
process.

| Direct references | Resolved | Moved | Embedded | Ambiguous | Missing | Found, identity match |
|---|---|---|---|---|---|---|
| Default: the document's folder, outside lookups allowed | 20.98% | 60.27% | 0.59% | 0.03% | 18.13% | 78.02% |
| Corpus tree top, outside lookups allowed | 20.98% | 61.77% | 0.59% | 0.38% | 16.29% | 79.46% |
| Serve-like: the tree top, nothing outside it | 19.26% | 61.58% | 0.59% | 0.38% | 18.19% | 77.56% |

The design's simulation of the tree-top configuration, over 3,225 direct
references, gave resolved 21.8%, moved 61.5%, ambiguous 0.25% and missing 16.5%;
the 0.59% embedded here are imported components it did not separate. Of the
640 virtual files, 125 are `embedded` (all with an identity match), 4
`embedded_not_found` and 511 `embedded_in_subassembly`. The 39 references
with a stored UNC path reached the gateway in every configuration and were
refused on their anchor every time; none was touched.

**Confidence comes from measured precision.** The rules were fixed before this
measurement. A seeded third of the documents (116: 108 assemblies and 8
drawings) is held out, and the other two thirds set the confidence levels. For
each reference whose positional ground truth is known (the stored path of an
unmoved document, or the rebased path of a moved one, with an identity match),
each later rule was run on its own and its pick compared with that truth:

| Rule, identity match | Tuning set | Holdout | Confidence |
|---|---|---|---|
| `same_folder` | 1,024 of 1,027 (99.7%) | 484 of 485 | high |
| `suffix_probe` | 1,651 of 1,654 (99.8%) | 1,218 of 1,219 | high |
| `stored_path` | 694 of 732 (94.8%) | 239 of 250 (95.6%) | medium |
| `name_index`, one candidate | 1,389 of 1,389 | 812 of 812 | high |
| `name_index_suffix` | 154 of 200 (77.0%) | 379 of 388 (97.7%) | low |

High means 97% or more on the tuning set, medium 85% or more, low less.
`stored_unmoved` and `rebased` are the ground truth itself, and `path_map` is
configuration, so they are high. Without an identity there is no evidence
either way: `stored_unmoved`, `path_map`, `rebased` and `embedded` are medium,
the other rules low. A file kept although its identity differs is low;
`ambiguous` and `missing` are none.

On the holdout's 1,553 direct references, 73.21% are found with an identity
match in the default configuration and 73.08% in the serve-like one, 0% and
0.06% are ambiguous, 26.21% are missing in both, and no found file's identity
differs in the default configuration (1 in the serve-like one). The opt-in
corpus test asserts, for both configurations on that holdout, at least 70%
found with a match and at most 1% ambiguous, 3% differing and 30% missing.

### 3.11 Roots: `solidseas.Roots`

```python
from solidseas import Root, Roots

roots = Roots([Root("jobs", "D:/Jobs"), Root("std", "E:/Library", role="library")])
roots = Roots.from_mapping({"jobs": "D:/Jobs"})        # every root a recursive project root
```

One type for every folder SolidSeas may search or serve (C5).
`Root(id, path, recursive=True, role="project")`: `id` matches
`[a-z0-9_-]{1,32}`, `role` is `project` or `library`, and `path` must be
absolute; it is normalised as text. Constructing a root never touches the disk:
whether the folder exists is found out when something walks it. A junction, a
symbolic link or a UNC share is accepted (C6). Refused with `PathRefusedError`
and `detail["rule"]`: `device_path` (`\\?\`, `\\.\`), `webdav` (an `@` in the
host, or a `DavWWWRoot` share) and `not_absolute`. Two roots with the same id
raise `InvalidArgumentError`.

### 3.12 Path report: `path_report()`

```python
with open_document("frame.SLDASM") as doc:
    rep = doc.path_report()
    rep.complete, rep.counts()["by_category"]
    for p in rep.paths:
        print(p.severity, p.category, p.path, p.roles, p.account, p.host)
    [a.name for a in rep.accounts if a.inherited_likely]
```

Every path and name a document would reveal to anyone it is sent to, read from
the document and, recursively, from every nested document in it (virtual and
imported components). `solidseas paths FILE` and the `path_report` kind (5.11)
give the same thing. **SolidSeas never rewrites files.** Removing what the
report lists means saving a new document in SOLIDWORKS or sending a neutral
format; the report says so in `rewrite`.

**What it reads.** Structured carriers first, then a byte scan of every stream
as a fallback:

- the folder and file name at save (`SW-Folder Name`, `SW-File Name`);
- user names: the `Header2` user list, `SW-Author`, `SW-Last Saved By`, the
  creator and every `lastModifiedBy` in `docProps/core.xml`, and in legacy
  files the summary author and last author;
- the component tree's `swPath` and `swImportedPath`, and the reference paths
  in `Header2`;
- the stored strings (MFC CStrings) of the streams that hold paths by design:
  `_MO_VERSION_<n>/Biography` (one record per save session), `Header2`,
  `SwDocContentMgr/SwDocContentMgrInfo`, `Contents/Config-<n>-ModelHeader` and
  `Contents/DisplayLists`;
- the byte scan of every stream (provisional:
  `solidseas.formats.solidworks.paths.scan_bytes`): stored strings read to their
  stored length, then UTF-16LE text outside them, then counted 8-bit strings
  (a byte count, the text and a NUL, as legacy property sets store text) that
  hold a byte above ASCII and either are not UTF-8 or sit in a property set
  section that declares an 8-bit code page (a section that declares none is
  cp1252). Such a string is read whole in its section's code page, even where
  its bytes would also be valid UTF-8, as the property set reader reads it, and
  in cp1252 outside a property set. Then UTF-8 text. Each pass reads from a
  drive or UNC prefix to the first character a path cannot hold. A stored
  string holding control characters, a byte-order mark or unpaired surrogates
  is `FF FE FF` inside binary data and is skipped. 8-bit text without a count
  and a NUL is read as UTF-8, so binary noise never runs into a path. Outside
  stored strings, a match with no two letters or digits in a row after its
  prefix is noise and is dropped.

A nested document's own stream is opened as a document and read the same way,
not scanned as bytes; only one that does not open is scanned as stored bytes.
`Document.embedded_paths()` (provisional) is the byte scan of the document's own
streams alone, as in 0.1.

**Merging.** Paths are compared case-insensitively, with `/` read as `\` and a
trailing `\` ignored. The first spelling found is kept, so a structured
carrier's spelling wins over the scan's. Each path keeps every stream, and
nested document, it was found in.

**Each path** (`FoundPath`) has:

| Field | Meaning |
|---|---|
| `category` | Where on disk (an open set): `unc`; `temp` (an `AppData\Local\Temp` or `Local Settings\Temp` folder, `Windows\Temp`, a top-level `Temp` or `Tmp`); `desktop`; `profile` (anything else under `\Users\<name>` or `\Documents and Settings\<name>`); `windows`; `program` (`Program Files`, `Program Files (x86)`, `ProgramData`); `drive_root` (a drive, or one entry at its top); `project` (everything else: folders outside the standard places) |
| `roles` | Why the file stores it (an open set): `references` (a SOLIDWORKS document, named outside the save history, or a tree or `Header2` reference path); `imported_from` (`swImportedPath`); `save_location` (the folder at save, or the document's own path at a save); `resources` (any other file or folder in a stream that holds paths by design, such as an appearance or the STEP file a part was imported from); `history` (`Biography`); `other` |
| `account` | The profile name in `\Users\<name>` or `\Documents and Settings\<name>`, or None. Public, Default, Default User and All Users are not accounts |
| `host`, `share` | For a UNC path. `\\?\UNC\` is read as `\\`, and a WebDAV host such as `fs01@SSL@443` is `fs01` |
| `sources` | `tree`, `tree_imported`, `header2`, `save_folder`, `biography`, `content_manager`, `model_header`, `display_lists` (the structured carriers), and `scan` |
| `locations` | `Location(nested, stream)`: `nested` is the chain of nested-document streams from the top document, empty for the file itself |
| `history_only` | Found only in save-session records |
| `inherited_likely` | `history_only`, and its account is `inherited_likely` |
| `severity`, `reason` | See below |

**Severity**, for "sending this file to a customer"; the first rule that
matches wins:

| Severity | `reason` | Rule |
|---|---|---|
| high | `unc_share` | A UNC path: it names an internal server and share |
| high | `referenced_document` | Role `references` or `imported_from` |
| high | `save_location` | Role `save_location` |
| high | `folder_names` | Category `project`: folder names, which can name customers |
| medium | `account_name` | A path naming an account |
| medium | `inherited_template` | The same, for an account that is `inherited_likely` |
| medium | `profile_folder` | A profile, Desktop or temp path that names no account |
| low | `standard_folder` | Windows, the program folders or the top of a drive |

Severity labels each finding. There is no file-level rating: it would read
"high" for nearly every file (the save location alone is stored in 3,153 of the
3,501 corpus files), so the report counts paths per category and per role
instead (`counts()`).

**Accounts** (`Account`) come from the paths and from the user-name fields,
merged case-insensitively. `sources` lists `path` and the identity fields that
name the account. An account is `inherited_likely` when nothing current names
it: it appears only in save-session paths, the `Header2` user list or older
`core.xml` save records, and in no current field (the newest save, the
creator, `SW-Author`, `SW-Last Saved By`, the legacy summary). That is probably
an author of the template the document was made from (a HYPOTHESIS: true of
every such account on the fixtures). It stays at severity
`medium`: under-ranking is the dangerous direction for a report read before
sending a file. `history_only` says every path naming the account is in the
save history. **Hosts** (`Host`) list each UNC host with its shares.
**Identity fields** (`IdentityField`) are every user name and the file name at
save as each carrier stores it, with `current` false for history (a `Header2`
user list entry, an older save record).

**Completeness.** `complete` is false, and `incomplete` says why, with the
stream and the nested chain, when:

| `reason` | Cause |
|---|---|
| `stream_over_cap` | A stream is larger than `max_stream_bytes` (16 MiB): 48 streams in 38 of the 3,501 corpus files |
| `stream_unreadable` | A stream could not be read |
| `carrier_unreadable` | An identity carrier (`core.xml`, `ISolidWorksInformation`, `SummaryInformation`, `Header2`, the component tree) could not be read |
| `nested_unreadable` | A nested document does not open (its stored bytes are scanned for what they show) |
| `path_limit`, `document_limit`, `byte_limit` | `max_paths` distinct paths, `max_documents` documents (this one included) or `max_total_bytes` decoded bytes were reached |

The report never raises for what the file holds; only a lock on the whole file
(`LockedFileError`) propagates, and a limit outside 1 or more raises
`InvalidArgumentError`. It holds the values themselves, so the service will
serve it only to authenticated callers and never log it.

**Measured on the development corpus** (3,501 documents: 3,150 parts, 325
assemblies and 26 drawings, read-only through the library, 6 workers):

- 0.027 s per report at the median, 0.38 s at p95, 1.2 s at p99 and 4.2 s at
  most, at below-normal priority; the largest document read 79 MB of streams and listed 1,010 paths;
- 210,692 paths in all, 2,248 of them with non-ASCII characters; 681 nested
  documents read, none failing to open;
- every one of the 26,700 structured paths (tree, `Header2`, folder at save,
  nested documents included) is in its report, and so is every path the 0.1
  ASCII scan finds, in the documents' own streams and in their nested
  documents, except where that scan was wrong: it cut 474 paths at their first
  non-ASCII character and ran 75 past the end of their stored string into the
  bytes after it;
- of the 690,896 stored strings that end in a path, 38,036 (5.5%) are followed
  by a UTF-16 unit that reads as a letter, CJK or Hangul in 37,429 of them: a
  scan of "any letter" without the stored length would have appended them;
- no path comes from a counted 8-bit string, and reading those in a code page
  changed no path in any report: the legacy documents keep their non-ASCII
  paths in UTF-8 property sets, and none of the 1,688 runs of 8-bit text
  elsewhere that start like a path and are not UTF-8 (in bitmaps, partitions
  and display lists, mostly) is a counted string (`docs/FORMAT.md` 13);
- 26,906 accounts, in 2,361 files, are `inherited_likely`;
- no file changed size or modification time.

### 3.13 Worker processes: `solidseas.workers` (provisional)

A hostile or merely broken file can make a parser hang, run out of memory or
crash the process. The REST service reads every document in a worker pool, as
do the CLI's `list` and `batch` (7.1), and so can a Python integration that
reads files other people supply:

```python
from solidseas import Roots, scan
from solidseas.workers import WorkerPool


def main():
    roots = Roots.from_mapping({"jobs": "D:/Jobs"})
    with WorkerPool(2, timeout_s=30, memory_mb=2048, roots=roots) as pool:
        env = pool.run("document_summary", "D:/Jobs/Example/bracket.SLDPRT", within="D:/Jobs")
        if not env["ok"]:
            print(env["error"]["code"])        # timeout, worker_crashed, damaged_file...
        listing = scan("D:/Jobs/Example", pool=pool, file_timeout=10, within="D:/Jobs").listing()


if __name__ == "__main__":                     # required: see below
    main()
```

**The `__main__` guard is required in a script.** Workers are started with
`spawn` on every operating system, which runs the main module again in each
worker before the worker starts. A script that creates a pool at its top level
would create one in every worker too, and each worker fails as it starts; the
pool then raises `WorkerCrashedError` with a message that names the missing
`if __name__ == "__main__":`. Code imported as a module (an ERP plug-in, a
web service) needs nothing.

```python
class WorkerPool:
    def __init__(self, workers: int = 2, *, timeout_s: float = 30.0, memory_mb: int | None = 2048,
                 max_result_bytes: int = 64 << 20, roots: Roots | Iterable[str] | None = None,
                 reader_message: bool = True, refuse_hard_links: bool = False,
                 max_file_bytes: int | None = None, start_timeout_s: float = 60.0,
                 log: logging.Logger | None = None, priority: str = "normal",
                 jobs: Mapping[str, str] | None = None) -> None
    def run(self, kind: str, path, *, timeout: float | None = None, **params) -> dict
    def call(self, job: str, params: dict | None = None, *, timeout: float | None = None,
             max_result_bytes: int | None = None) -> WorkerResult
    def alive(self) -> int
    def worker_info(self) -> list[dict]
    def close(self) -> None
```

- `workers` processes (1 to 64) start at once with the `spawn` method and stay
  up; each job takes a free one. Each costs a few hundred milliseconds to start,
  so keep a pool for the life of the program rather than one per file.
- `run(kind, path, **params)` returns the envelope of `kind` for the document
  at `path`, read in a worker: `document_summary`, `properties`,
  `configurations`, `components`, `references` or `path_report`. `params` are
  the builder's options (`configuration`, `view`, `nested`, `max_nodes`,
  `max_depth`, `flat`) and `within` and `name` for `open_document`. A failure is
  an error envelope, never an exception: the job's own error (a damaged file, a
  missing configuration), `timeout` or `worker_crashed`.
- `call(job, params)` is the lower level: it returns a `WorkerResult` with the
  job's JSON `data` and, for an image, its bytes as `payload`, and raises
  `WorkerTimeoutError`, `WorkerCrashedError` or `WorkerJobError`, whose `code`
  and `detail` are those of the error inside the worker.
- `jobs` (provisional) adds entries to the pool's job table, each a job name
  and the dotted name (`module:function`) of a function a worker imports and
  calls with the call's `params`. It is set from Python only; no request and no
  configuration file can add a job. The viewer's own jobs
  (`solidseas_app.viewer.modeljobs`) and the tests' slow and crashing jobs come
  in this way. A job function returns JSON data, or `(data, payload)` for an
  image.
- **JSON only.** A job travels to its worker as JSON, and the answer comes back
  as one JSON frame read with `recv_bytes(max_result_bytes)`, plus one raw frame
  for an image. Nothing a worker sends is ever unpickled (`Connection.recv()`
  would run whatever a compromised parser packed into its answer); a test reads
  the module's source to keep it so.
- **A cap on each answer.** `max_result_bytes` is the longest answer the pool
  accepts, and `call(..., max_result_bytes=n)` lowers it for one call. The
  worker refuses a longer answer itself (`WorkerJobError`, code
  `response_too_large`) and lives on, so the over-long answer never crosses
  the pipe; a worker that sends one anyway is not read further and is
  replaced. The REST service gives each call its route's size cap.
- **A deadline per job.** `timeout` (the pool's `timeout_s` when not given)
  counts from the call, so time spent waiting for a free worker counts too.
  When it passes, the worker is killed and joined, and only then is a
  replacement started (critique 3.15: on Windows the Job Object allows one
  process per worker, and a replacement started early would be terminated). The
  call raises `WorkerTimeoutError`; the other workers carry on.
- **A crash is an answer.** A worker that dies (`os._exit`, a native crash) is
  joined and replaced, and the call raises `WorkerCrashedError`.
- **A lost worker is always replaced.** A replacement that fails to start
  (memory pressure, a slow start) is tried again with a wait that doubles from
  0.5 s up to 30 s, for as long as the pool is open, so the pool never shrinks
  for good. A killed worker that has not ended after its 10 s join (a read
  stuck on a file share) is waited for before its replacement starts.
  `alive()` counts the workers running; with `log`, each start, kill,
  replacement and failed start is logged, with that count.
- **A memory cap.** On Windows every worker is assigned, as it starts, to one
  Job Object with a per-process memory limit of `memory_mb`, an active-process
  limit equal to the worker count (a worker cannot start another process),
  kill-on-close (closing the pool, or the parent dying, ends every worker) and
  die-on-unhandled-exception, and the worker calls `SetErrorMode` so a crash
  never opens a dialog. On Linux the worker sets `RLIMIT_AS` to `memory_mb` and
  asks for `SIGKILL` when its parent dies; macOS may refuse `RLIMIT_AS`, and the
  cap is then best effort. An allocation over the cap fails inside the worker
  and comes back as `limit_exceeded` (`detail.limit` `memory`). `memory_mb=None`
  sets no cap.
- **Priority.** `priority="below_normal"` runs every worker below normal
  priority: the Job Object's priority class on Windows, `nice` 10 on Linux and
  macOS. A background job, such as a catalog scan (3.18), then never competes
  with the person at the computer.
- **What a job may open.** With `roots`, a document job must name one of them as
  `within` and the document must lie below it (`path_refused`, rule
  `outside_roots`, otherwise); `max_file_bytes` and `refuse_hard_links` apply to
  every document (section 3.1). Jobs read lazily (`hold_open=True`) and close the
  file when the job ends. `reader_message=False` leaves the exception text out of
  error objects, as the REST service does.
- Jobs come from a fixed table in `solidseas.jobs`. Nothing a request or a
  configuration file says can add one; tests add slow and crashing jobs through
  a Python-only argument, and the CLI's `batch` adds `batch_document`, the one
  job that writes (a document's preview and Parasolid files, under the CLI's
  write guards), which a pool built with the default table, such as the
  service's, cannot run. The table also holds the catalog's two read-only jobs
  (3.18): `catalog_document`, a document's catalog record, and `content_hash`,
  the SHA-256 of a file's bytes, read in 1 MiB chunks and kept only when the
  file did not change while it was read.
- `scan(..., pool=pool, file_timeout=10)` reads each listed document in the
  pool: a file that hangs or crashes its worker becomes an error entry
  (`timeout`, `worker_crashed`) and the listing goes on.

A worker caps resources; it is not a sandbox. It runs with the caller's account
and network access, which is why what it sends back is treated as data.

`solidseas.serve` (section 8) is the REST service built on it. Its Python
classes, `ServeConfig` and `Server`, are provisional too.

### 3.14 Display geometry: `solidseas.geometry` (provisional)

An assembly configuration ready to draw: every part instance SOLIDWORKS would
show, placed in the top assembly's frame, with one triangle mesh per component
file that all its instances share, and every instance that could not be placed
or meshed with the reason, its placement and the box its assembly stores for
it. A part for which no display mesh is stored anywhere is drawn from its own
Parasolid bodies, tessellated (3.15).

```python
from solidseas import open_document
from solidseas.geometry import display_geometry

with open_document("D:/Jobs/Example/frame.SLDASM") as doc:
    g = display_geometry(doc, "Default", roots={"jobs": "D:/Jobs"})
    for inst in g.instances:                       # one per part instance shown
        mesh = g.meshes[inst.mesh].mesh            # shared by every instance of that file
        print(inst.id, inst.placement.translation_m, mesh.n_triangles)
    for s in g.skipped:                            # not drawn, and why
        print(s.id, s.reason, s.message, g.placeholder(s))  # and a box where it would be
    print(g.counts, g.truncated, g.bbox())
```

```python
def display_geometry(
    doc,
    configuration: str | None = None,
    *,
    roots=None,                       # where component files are searched: Roots, Root objects or {id: folder}
    resolution=None,                  # a Resolution already made against the same roots
    sources=("assembly", "nested", "file", "subassembly", "brep"),
    path_map=(), allow_outside_roots=True, cache=None,   # passed to resolve_references (3.10)
    max_instances=100_000,            # component tree nodes expanded (components' max_nodes), and
                                      # as many again for the sub-assemblies' own trees looked up
    max_depth=32,
    max_files=2_000,                  # documents opened from disk
    max_triangles=20_000_000,         # triangles read, over every mesh
    max_bytes=2 << 30,                # display data decoded
    max_triangles_drawn=1_000_000_000,  # triangles of the placed instances, each counting its mesh
    max_brep_seconds=60.0,            # time spent tessellating parts' bodies, over the whole call
    brep_options=None,                # how the brep source tessellates (below)
    keep_welded=False,                # brep meshes also carry their shared-vertex triangles
) -> DisplayGeometry | None
```

`Document.display_geometry(configuration, **options)` is the same call. A part
or a drawing gives None.

- **Which instances.** The configuration is chosen as `components()` chooses
  it (3.8). An instance is drawn when it is a part (or a sub-assembly whose
  components cannot be listed, which is then skipped with a reason), neither it
  nor a parent is suppressed, and neither it nor a parent is hidden as 3.9
  reads `hidden`. Suppressed and hidden instances are counted, not listed.
- **Sub-assemblies the tree does not list.** The top assembly's tree normally
  describes every level. A sub-assembly whose components it does not list
  (`children_state` `described` with no children) is expanded from the
  sub-assembly's own document, found as the files are (on disk, or stored
  inside the top assembly or another sub-assembly), in the configuration the
  instance uses. Its instances get ids under the sub-assembly's id
  (`sub-1/part-1`), placements composed through the stored transforms exactly
  as `components()` composes them, and file keys `<sub-assembly key>/<key in
  its file>`, which `files` holds. The limits on instances and depth count
  across documents, and a document met again inside itself is not expanded
  (`cycle`). When the document cannot be found or read, has no such
  configuration or lists no components, the sub-assembly is skipped with the
  reason (`missing`, `unreadable`, `no_components` and so on), so nothing is
  dropped without a word. A suppressed or hidden one is counted once and not
  read. On the development corpus its three shown cases add no part: two are
  empty virtual sub-assemblies (`no_components`) and the third's file is not
  found (`missing`).
- **Placements** are the components' `placement`s: the stored transforms
  composed through every parent (3.9). On the three fixture assemblies, in
  every configuration, each placed instance's mesh in the top frame has the box
  SOLIDWORKS reported for it (`Component2.GetBox`) to 1e-6 m, from the
  assembly's own meshes and from the part files alike: parts turned 90 degrees
  about X and about Z, a sub-assembly turned 40 degrees about (1, 1, 1) and
  the parts inside it, and o16's `Lite`, which suppresses that sub-assembly.
  The assembly's own box is the union of its top-level components' boxes when
  each sub-assembly's box is built as SOLIDWORKS builds it (its own box carried
  into the top frame, so looser than its parts' once turned). VERIFIED;
  `tests/test_geometry.py` repeats it on every run.
- **Where each mesh comes from**, trying `sources` in order for each instance
  and going on to the next when one fails:
  - `assembly`: the mesh the assembly itself stores for that component, in
    the component's own coordinates (`docs/FORMAT.md` 12.3). Assemblies saved
    by SOLIDWORKS 2023 and later keep one per instance in `FaceTessellations`,
    shared between instances of the same file; older ones keep one per file in
    their own `Contents/DisplayLists`, used for a file that the tree uses in one
    configuration and whose stored path opens one section there, or several of
    which exactly one holds face tables (the others mention the path with no
    tables after it; two with tables are refused, since which configuration
    each shows is not stored). A section ends at the header of the next file
    the component tree names, whatever that file is (a sub-assembly, a part
    used in several configurations or only in another one, a path two files
    share), and at a header that names one of those files in another folder
    (where it was when that section was written), unless it is the section's
    own file, so it never takes in another file's tables. Both layouts are a
    HYPOTHESIS checked on the fixtures and the development corpus. Stored
    meshes describe the configuration active when the assembly was saved, so an
    instance of another configuration takes one only where that configuration
    has the same file in the same configuration at every level down to it.
  - `nested`: the display mesh of the document stored inside the assembly for
    a virtual or an embedded imported component (3.9), or inside the
    sub-assembly's own file for a virtual component used only there.
  - `file`: the display mesh of the component's file on disk, found by
    reference resolution (3.10) in `roots` (None: the document's own folder)
    and opened read-only `within` its root, or within its own folder outside
    the roots, as resolution's identity reads open it. A part stores the mesh of
    the configuration active when it was saved; when an instance uses another,
    the mesh source carries the warning `mesh_configuration_differs`. A file
    found for several instances, of the top assembly or of sub-assemblies read
    from their own files, is opened and read once, and its instances share one
    mesh.
  - `subassembly`: for an instance inside a sub-assembly, the mesh a
    sub-assembly above it stores in its own document, by the same rules with
    that sub-assembly's active configuration: the record of the instance's path
    below it, or the section of its file, used only where the sub-assembly's
    active configuration has the same files (compared by name) in the same
    configurations at every level down to the instance. The sub-assemblies
    above it are tried from the top down, and one whose stored mesh turns out
    empty or unreadable (a section with no face tables, a block that cannot be
    read) passes to the next, so a part three levels down comes from either
    sub-assembly above it. Its document is found and opened read-only as the
    files are, and counts against `max_files` when it is a file. It comes last:
    the part's own file is read first, so the files opened under `max_files`
    go to part files before sub-assemblies, and a part file saved since shows
    the part as it is now; the price is that a part file's mesh shows the
    configuration the part was saved in, where a sub-assembly's shows the one
    it uses. VERIFIED on the fixtures: o16 without its own meshes or part
    files draws o15's two parts from o15's, on SOLIDWORKS' boxes, and with o16
    as a sub-assembly of another assembly they come from o16.
  - `brep`: the part's own Parasolid bodies, tessellated (3.15): those of the
    configuration the instance uses, or, when the part stores no partition
    for it, of its active configuration, with the warning
    `mesh_configuration_differs` (which then says the part stores no bodies of
    the configuration the instances use, rather than speak of a display
    mesh). The document is the one the `nested` or
    `file` source would read: stored inside the assembly or a sub-assembly for
    a virtual or embedded component, otherwise the file reference resolution
    found, opened read-only `within` its root and counted against
    `max_files`; when the `file` source has just found no display mesh in that
    file, the brep source reads the same open document instead of opening it
    again, and a file the `file` source could not read is not opened again.
    One mesh is made for each document and configuration, however many
    instances use them, with the key `brep:<file key>#<configuration>`. It
    comes last by default, so that a stored mesh (what SOLIDWORKS last drew)
    always wins and only parts that store none are tessellated; an export
    (3.17) puts it first. `brep_options` sets how it tessellates: any of
    `chord_m`, `angle_deg`, `chord_fraction` and `max_chord_m` (3.15),
    `body_types` (solids and sheets by default), `max_seconds`, the time a
    part may take (30 s by default), and `include_hidden` (True by default:
    False leaves out the bodies hidden in SOLIDWORKS, as `tessellate_document`
    does, saying how many with `brep_bodies_hidden`, and a part whose bodies
    are all hidden fails as `bodies_not_asked`); a bad one raises `InvalidArgumentError`
    before any work. A brep `MeshSource` has the `chord_m` it was made at, and
    with `keep_welded` also `welded`, its triangles over shared vertices as
    `Tessellation.welded()` gives them, closed where the bodies are. `MeshSource.stream` names
    the partition or LocalBodies stream that held the bodies. Faces that could
    not be tessellated leave holes, and the mesh source says so with the
    warning `brep_faces_skipped` (with the count and the reasons); a body that
    could not be walked face by face is left out, with `brep_bodies_skipped`;
    `brep_not_closed` says a solid's mesh is not watertight. A part gets 30 s,
    reading its bodies included: tessellating gets what the read leaves and
    stops when that is spent. No part is started once `max_brep_seconds` is
    spent over the call, and a part whose bodies take the rest of it to read
    is skipped as `max_brep_seconds` without being tessellated. Reading a
    part's bodies, once started, runs to its end, so a part, or the call, can
    run past its limit by that one read. The triangles
    and the decompressed Parasolid bytes count against `max_triangles` and
    `max_bytes`. VERIFIED on the fixtures: o08, o15 and o16 (Default and Lite)
    drawn from `sources=("brep",)` alone place every instance on SOLIDWORKS'
    box of it to 1e-6 m, and the meshes' volumes and areas add up to the
    assembly's own to 0.5 percent; o16's virtual part, which stores no display
    mesh, is drawn from its bodies at the default order.
  Resolution runs only when a file is needed, once a document, and every
  document resolved in one call shares one index of the roots (the `cache`
  given, or one made for the call), so the roots are walked once however many
  sub-assemblies are read from their own files. A document opened from bytes
  has no folder: give `roots`, or its files are `missing`.
- **One mesh per source.** `meshes` maps a key to a `MeshSource` (`kind`, a
  source name and an open set like every enum here, `file`, `stream`, `path`,
  `nested`, `configuration`, `mesh`, `warnings`; for `subassembly`, `path` and
  `nested` say where the sub-assembly's document is, and for `brep` where the
  part's document is), and
  each `PlacedInstance` (`id`, `name`, `file`, `configuration`, `mesh`,
  `placement`, and `matrix()`, the placement as a column-major 4 x 4 matrix)
  names its mesh by key. Instances of one file share one mesh; on o16, the
  three top-level instances of o02_boxA and the one inside the turned
  sub-assembly share one.
- **What is not drawn**: `skipped` holds a `SkippedInstance` (`id`, `name`,
  `file`, `reason`, `message`, `code`, `placement`, `box`, and `matrix()`) for
  each instance that should be drawn and is not. `placement` is where it would
  be (None when a stored transform on the way is unreadable) and `box` the box
  its assembly stores for that component in that configuration, the
  `swBoundingBox` of its model (`docs/FORMAT.md` 12.1), in the component's own
  coordinates, metres: None when not stored, not six finite numbers, or two
  models of that file and configuration disagree. `placeholder(s)` places its
  eight corners: a box to draw in the instance's place, which on the fixtures
  is SOLIDWORKS' box of it. The reasons are an open set, each with its
  sentence in `geometry.REASONS`: `missing`, `ambiguous`, `embedded_not_found`,
  `unreadable` (with the error code), `no_mesh` (its document stores no display
  mesh; with the brep source, the message says it stores no Parasolid bodies
  either), `brep_failed` (its bodies gave no triangle, or took longer than a
  part may), `bodies_not_asked` (provisional: none of its bodies is of a type
  `brep_options`' `body_types` asks for, such as a part of surfaces when only
  solids are asked for), `not_part`, `no_source` (no source asked for applies),
  `no_components` (a sub-assembly whose own file lists no components for the
  configuration used), `no_placement`, `model_missing`, `cycle`, `truncated`
  and the five limits `max_files`, `max_triangles`, `max_bytes`,
  `max_brep_seconds` and `max_drawn`. When one source
  failed on a limit and the next for another reason (o16's virtual part under
  a low `max_triangles`: the assembly's mesh is past the limit, its nested
  document stores none), the reason is the limit, since a higher one would
  draw the instance. A part's bodies that failed (`brep_failed`,
  `bodies_not_asked`, or a `no_mesh` saying it stores no bodies either) are
  reported rather than a later source's finding no display mesh in the same
  document, whatever the order of the sources; otherwise a file's or a nested
  document's reason is given rather than the assembly's.
- **Limits.** Every read is bounded. `max_instances` and `max_depth` bound the
  tree, the sub-assemblies expanded from their own files counted in; the
  `subassembly` source reads each sub-assembly's own active tree to match an
  instance, out of an allowance of `max_instances` nodes more for all of them,
  and an instance it could not look up for want of it is skipped as
  `truncated` (a limit, so given rather than a later source's reason, with
  `max_instances` named). A sub-assembly's tree is read once for every
  instance of it in one configuration. `max_files`, `max_triangles` and
  `max_bytes` are checked before each read (a mesh that would pass
  `max_triangles` is read, then dropped); `max_bytes` counts every stream of
  display data read, a `FaceTessellations` directory included, and an instance
  whose stored mesh the limit kept from being read is skipped as `max_bytes`.
  Reads count each mesh once however many instances share it, so
  `max_triangles_drawn` bounds what a viewer would draw: an instance whose
  mesh would take the placed instances' triangles past it is skipped as
  `max_drawn`. An instance a limit stops is skipped with that limit as its
  reason, and `truncated` names each limit that stopped something. Searching a
  `FaceTessellations` stream for the blocks its directory names stops after
  four times the stream's size, so a directory naming many blocks a stream
  lacks costs time in proportion to the stream. When a stored path opens
  several sections, each is decoded once, inside the bytes already counted for
  the stream, and the decoding stops at `max_triangles`. `counts` has
  `instances` (the tree's, and those of the sub-assemblies expanded from their
  own files), `parts` (part instances, and each sub-assembly that could not be
  expanded counted once), `placed`, `suppressed`, `hidden`, `skipped`,
  `meshes`, `triangles_read`, `triangles_drawn` (each instance's triangles),
  `files_opened`, `bytes_read`, `meshes_tessellated` (meshes the brep source
  made) and `brep_seconds` (a float: the time it took); `placed + skipped +
  suppressed + hidden` always equals `parts`. `max_brep_seconds` bounds the
  brep source's time over the whole call: when it is spent, the parts left
  are skipped as `max_brep_seconds` (the call runs past it by at most one
  part's read of its bodies, above).
- **What it raises**: `InvalidArgumentError` for a bad argument (an unknown
  source, a limit out of range, roots that are not roots) and
  `ConfigurationNotFoundError` for an unknown configuration name. A component
  that cannot be read never raises: it is skipped with a reason. Nothing is
  ever written.
- `files` holds the component tree's files by key (3.8), with those of the
  sub-assemblies expanded from their own files (`direct` False, their instance
  counts None), and `resolution` the `Resolution` made for the top assembly's
  files read from disk, or None. `bbox()` measures
  each mesh's own box once (`mesh_box(key)`) and carries its eight corners
  through each placement, so it costs the meshes' vertices once plus eight
  points an instance; `bbox(exact=True)` places every vertex of every
  instance.

**Measured on the development corpus** with an earlier version and the four
stored mesh sources (its 328 assemblies, each with its own folder as the root,
read-only; on the 325 its manifest marks readable, which `tests/test_corpus.py`
measures, the current version's four stored sources place 5,473 of 6,779, and
all five 6,508, below): of 6,724 part instances to
show (`parts` 7,774, of which 404 suppressed and 646 hidden), 5,392 are placed
(80.2%), and every one in 250 of the assemblies; 48 place none. Before an
older assembly's file could take one section among
several, 4,571 of 6,721 were placed (68.0%): the 115 assemblies with
`FaceTessellations` placed every part inside their sub-assemblies (they skipped
15 at the top level), and the 213 older ones skipped 1,268 instances inside
sub-assemblies and 867 at the top level. Inside sub-assemblies 2,104 of 2,775
are now placed (1,507 before), at the top level 3,288 of 3,949 (3,064 before).
Of the placed instances, 5,016 take the assembly's own meshes (1,284
`FaceTessellations` blocks and 3,732 sections) and 376 their part files. The
1,332 still skipped are `no_mesh` (1,141: neither the assembly, a sub-assembly
nor the file stores a mesh; those part files mostly hold only Parasolid
bodies), `missing` (189) and `no_components` (2, empty virtual
sub-assemblies), and 1,306 of them have a placeholder box. The sub-assemblies'
own meshes alone (`sources=("subassembly",)`) place 564 instances: 563 of them
the top assembly's own meshes hold too, and the other one its part file gives,
so at the default order they add none. A call took 0.07 s at the median and
3.5 s at most; the most triangles read was 568,808 (1,008,938 drawn), and the
most display data 115 MB.

**With the `brep` source** (the 325 assemblies the manifest marks readable,
each with its own folder as the root, read-only, measured with the four stored
mesh sources alone and then with all five): of 6,779 part instances to show,
the stored meshes place 5,473 (80.7%) and leave 1,280 to placeholder boxes and
26 to nothing; with the `brep` source 6,508 are placed (96.0%), 1,035 of them
from their parts' bodies (435 meshes tessellated), and 245 are boxes. The
instances still not drawn from a mesh are `missing` (189), `brep_failed` (54,
in 4 assemblies: parts whose every face has no area), `no_mesh` (26: parts
that store no bodies either) and `no_components` (2). Every part is placed in
289 assemblies (248 before) and none in 12 (48 before). A call took 0.082 s at
the median and 32.3 s at most (0.067 s and 3.4 s without the `brep` source);
11 tessellated meshes carry `brep_not_closed` and 7 `brep_faces_skipped`.

### 3.15 Tessellation of a part's bodies: `solidseas.tessellate` (provisional)

Triangles of the Parasolid bodies a part stores (`parasolid()`, 3.2), for
parts saved without a display mesh, for the `brep` source of
`display_geometry` (3.14) and for exports such as STL and 3MF. Each edge is
sampled once and both of its faces use the same points, so a solid comes out
closed; each face is triangulated in its own (u, v), with seams cut and poles
opened, and curved faces get points inside until every triangle keeps within
the chord tolerance of the surface. A boundary edge's samples are chords that
lie off the surface by their sagitta, and the next face shares them, so they
are never split: points inside a face keep from each chord by its sagitta over
tan(angle), and the triangles on it do not stand up off the surface or face
back. Where a boundary is sampled coarsely for the surface's curvature across
it (a small fillet along a long arc), the triangles on it can turn by more
than the angle. A triangle of three points in a line is kept: it has no area,
but its edges are the next triangles' and the next face's. Vertex normals at a
pole are the mean of the triangles round it. `docs/FORMAT.md` 10.8 has the
conventions of the format this rests on.

A loop that runs along an edge and straight back (a seam run down to a pole and
back up, a slit) encloses nothing: the pair is taken out of the loop before its
polygon is built, round the loop's end as well, since kept it is a polygon side
of no width whose samples the triangulation fans across. A point that halving
an edge's segment puts within 1% of the chord tolerance, or within a
micrometre (the tessellator's point tolerance; at most half the chord
tolerance), of its neighbours is left out, and a segment that short is not
halved for its turn alone; the first samples, two a knot span, are all kept
(a small arc's few samples say which way it winds round a periodic surface).
At a knot where a curve stops dead and turns, the turn stays whatever the
length, and halving it to the depth bound piled up samples a billionth of a
millimetre apart; stopping that halving at 2% of the chord tolerance still
left points a ten-thousandth of a millimetre apart, closer than their (u, v)
on a face can be told apart (more so on an edge a few micrometres off its
face's surface), and such a run made one face's boundary cross itself in
(u, v) (that face came out half as large again, with no fold found). The
polyline keeps within the chord tolerance and that distance.
The STEP export's own sampler (3.19) keeps every sample. A torus's (u, v) is
scaled by its largest `|R + r cos v|` over the face, so a torus whose major
radius is under its minor one is triangulated where it
runs inside its axis. A boundary point taken (within ten chord tolerances) but
farther off its surface than the chord, as where a face's edge runs on past the
end of its surface, is carried past the edge of the surface's parameter range
by one unclamped Gauss-Newton step, so that such points do not all land on one
(u, v) point there (a step longer than the range is not taken: the surface
barely moves at that edge, and the point stays on it; the next point is
looked for from the edge, not from past it), and a triangle at it is judged by
where it falls on the surface: kept against it, the triangle could never come within the chord and
was split again and again into folds. Consecutive boundary points that still
fall on one (u, v) point (an edge standing off its surface along the surface's
own edge) are spread evenly towards the next point: points of different ids at
one place cannot be triangulated. A face all of whose loops run against it, on a surface
that does not close, or on a closed surface where those loops would leave no
surface outside them (a fillet on a torus stored with its loop reversed), keeps
the sense the file gives it and its loops are read the other way round, its largest loop the outer one (`loops_reversed`), as
other readers take such a face: the files met that store faces so face outward
by their sense, and some have no edge between faces by which a check could
turn them. Where such a face meets neighbours that disagree, a STEP scene's
check turns it to agree with them (3.20.7).

A rolling blend (BLENDED_EDGE, the surface a sphere sweeps as it rolls along two
faces, as a fillet does) has no closed form, and Parasolid's own (u, v) of it is
not known. It is drawn from the rational B-spline the STEP export writes for it
(3.19), built by the same code (`solidseas/tessellate/blend.py`): exact circular
sections between the sphere's feet on its two supports, lofted along its spine,
with sections added where it strays from the surface the sphere sweeps. The
export measures that at seven points along every span between sections and
nine across; the tessellator, for speed, at the middle of each span and three
across, until within 4% of the chord tolerance. Measured at the middle alone
the export found the true deviation up to 2.4 times the middle's
(`docs/FORMAT.md` 10.9), so a blend lies within about a tenth of the chord
tolerance of its approximation; one that cannot be brought within 40% of it, or
cannot be measured, is not drawn (`fit_failed`). A face's side on a blend comes
from its loops (its outer loop runs counter-clockwise about its outward normal,
and on a blend that does not close on itself it is the largest in the
approximation's (u, v)), and on a blend closed round its spine from a face it
meets tangentially, as the export takes it. A curve given only in a blend's
own (u, v) (an SP-curve) is refused rather than guessed (`unsupported_curve`),
and a tolerant edge beside a blend is sampled along its other fin's curve. An
offset of a blend goes along a normal that is not known, and is not drawn
(`unsupported_surface`). A blend costs far more than any other face, so every
body's other faces are done first and the blends after them, and one blend's
fit may take a tenth of `max_seconds`, at most 15 s. When that share runs out,
the best round of refinement measured so far is drawn if it is within 40% of
the chord tolerance, and the blend is refused (`fit_failed`) if it is not. The
time running out leaves out blends only, with the reason `max_seconds`, and the
result, whole but for them, is not `truncated`: a 3D print is then made with a
hole there, as it was before blends were drawn, rather than refused.
`blend_reserve_s` ends the blends' pass that long before the deadline, for a
caller that gave the tessellation all of its own time and must still use the
result: a Parasolid file's export scene asks for a tenth of its time, at most
2 s, so that it and its 3D print leave such blends out in the same way
(3.20.6). These bounds are times, so a blend near them is drawn, drawn less
refined, or left out depending on the machine's speed and load: on a busy
machine the same part can come out with a blend fewer, or slower.

```python
from solidseas import open_document
from solidseas.tessellate import tessellate_document

with open_document("D:/Jobs/Example/bracket.SLDPRT") as doc:
    t = tessellate_document(doc)                # the active configuration
    t.mesh                                      # a Mesh (3.2, mesh()), metres, outward normals
    t.counts, t.skipped, t.closed, t.truncated
    positions, triangles = t.welded()           # shared vertices, for STL or 3MF
    t.measures()                                # volume, area, centroid and box
```

```python
def tessellate_document(doc, configuration=None, *, body_types=("solid", "sheet"), **options)
    -> Tessellation | None
def tessellate_body(body: ParasolidBody, *, body_types=("solid", "sheet"), **options) -> Tessellation
def tessellate_transmit(xt: XtTransmit, *, body_types=("solid", "sheet"), **options) -> Tessellation

options:
    chord_m=None,          # largest distance from a triangle to its surface, and from an edge's
                           # polyline to its curve; None: 1e-3 of the bodies' box diagonal,
                           # kept from 1e-6 to 1e-3 m
    angle_deg=15.0,        # largest turn between edge segments, and between a triangle's normal
                           # and the surface's at its corners (on triangles longer than 4 chords)
    max_faces=200_000,
    max_triangles=5_000_000,
    max_face_points=50_000,     # points of one face, its boundary included
    max_edge_points=10_000,     # points of one edge
    max_seconds=30.0,
    chord_fraction=1e-3,        # with chord_m None: this fraction of the bodies' box diagonal,
    max_chord_m=1e-3,           # kept from 1e-6 m to this; an export (3.17) asks for 2.5e-4 and 1e-5
    blend_reserve_s=0.0,        # the rolling blends' pass ends this long before max_seconds
    detail=False                # also return Tessellation.detail, a TessDetail (drawings); new, provisional
```

`Document.tessellate(configuration, **options)` is `tessellate_document`.

- **Which bodies.** `tessellate_document` takes the bodies of one
  configuration (None: the active one), as `parasolid()` returns them:
  partition bodies, or the local bodies when the partition holds none. A
  configuration whose partition the document does not store gives an empty
  result with the warning `no_stored_bodies`; another configuration's bodies
  are never taken in its place. When the document does not say which stored
  configuration is which and stores only one, that one is used with the
  warning `configuration_assumed`; a stream that could not be read gives
  `bodies_unreadable`. Assemblies and drawings give None. Only the body types
  in `body_types` are tessellated (`solid`, `sheet`, `wire`, `general`); the
  others are counted as `bodies_left_out`. With `include_hidden=False`, the
  bodies hidden in SOLIDWORKS (the shown mark the STEP export reads, 3.19) are
  left out before anything is tessellated, with the warning `bodies_left_out`
  saying how many; a body whose state is not known is kept. `tessellate_transmit` takes every
  BODY of a parsed transmit, a SOLIDWORKS `.x_b` export of several bodies
  included.
- **`Tessellation`**: `mesh` (one `FaceTess` per face done, `offset` -1, its own
  vertices and normals, so faces are smooth inside and sharp at their edges;
  `Mesh.stream` is `brep`), `face_ids` (for each `FaceTess`, the index into
  `bodies` and the FACE's `node_id`), `configuration`, `bodies` (their names),
  `chord_m` and `angle_deg` used, `counts` (`bodies`, `bodies_skipped`,
  `bodies_left_out`, `faces`, `faces_done`, `faces_skipped`, `edges`,
  `triangles`), `skipped` (a `SkippedFace` for each face not done: `body`,
  `face`, `surface`, `reason`, `detail`; at most 1,000, while `reasons` counts
  them all by reason), `closed` (every solid body watertight: each directed
  edge of its triangles has its reverse; False when a solid has a face not
  done or could not be walked, or a limit stopped the work; None without
  solids), `truncated`, `warnings`, `seconds`, `checks` (the self-checks'
  counts, below) and `face_shells` (each face done's SHELL node index, in the
  order of `face_ids`). `welded()`
  gives the triangles over shared float64 vertices, closed where the bodies
  are, and `measures()` their volume (meaningful for closed solids), area,
  centroid and box.
- **Self-checks** (`solidseas.tessellate.checks`, pure Python, each one pass
  over the triangles). `checks` counts, by the codes of
  `solidseas.tessellate.CHECKS`: `loops_reversed` (faces whose loops were read
  the other way round, above), `faces_folded` (a face whose triangles' absolute (u, v)
  areas exceed its polygon's by more than 0.1%, or with more than 0.1% of its
  area in triangles that have area in space but none in (u, v); a face that
  fits within the chord tolerance, one thinner than it, and one whose (u, v)
  polygon has under a tenth of its area in space, its (u, v) collapsing, are
  not judged; a face whose (u, v) polygon touches or crosses itself, its
  triangles accepted loosely, also folds when more than 0.1% of its area is in
  triangles over ten times the surface's own area over their (u, v) triangle,
  `|Su x Sv|` at the middle: such a triangle stretches across the face in its
  tangent plane, covering its (u, v) once),
  `faces_coarse` (faces that reached `max_face_points` with triangles still off
  their surface by more than the chord tolerance), `solids_not_closed` (solids
  whose triangles do not use every edge exactly once each way) and
  `shells_inside_out` (in a closed solid, a shell whose signed volume disagrees
  with how it nests: inside an even number of other shells it must be
  positive, inside an odd number, a void, negative; for at most 64 closed
  shells). A shell can lie inside another only when its box does, so one beside
  another, touching it or not, is outside it without a ray; otherwise rays from
  four points inside its triangles (not from a vertex, which a shell touching
  it may share) are counted against the other's triangles. A probe within the
  chord tolerance of the other shell, or whose ray grazes an edge, says
  nothing, and the rest must agree; a shell with none left, or whose probes
  disagree, has a nesting that cannot be told and is not judged. The rays of
  every shell inside one shell's box are counted in one pass over its
  triangles.
  Each that is not nought adds a warning of its code to `warnings`. The module's
  functions take any mesh: `edge_use` (directed edges with no partner, and
  edges used twice the same way), `pieces` (triangles grouped by the vertices
  they share), `shells`, `nesting`, `inside_out`, `turn` and `Flat` (points of
  a flat xyz array).
- **What is not done.** A face fails alone, with a reason from an open set
  (`solidseas.tessellate.REASONS`): `unsupported_surface` (an offset of a
  rolling blend, a blend of a kind other than a rolling sphere or a cliff edge),
  `unsupported_curve`, `fit_failed` (a rolling blend not approximated within
  the chord tolerance, or not in its share of the time), `max_seconds` (a
  rolling blend the time ran out on), `orientation_conflict` (a face on a blend
  closed round its spine that meets no face tangentially to take its side from),
  `seam_configuration` (a boundary that wraps a closed surface in a way not
  handled: several loops round one way, a helix), `no_boundary` (a face with no
  loop on a surface that does not close, such as a plane), `inversion_failed`,
  `triangulation_failed`,
  `edge_too_long`, `max_face_points`, `bad_reference`, `bad_geometry`,
  `non_finite` and `degenerate` (a face with no area, a loop on a pole, a face
  thinner than the chord tolerance whose sides cross once sampled). Its
  triangles are left out and the rest of the body is done; the body is then
  not closed. A body whose own walk fails is skipped with the reason
  (`face` -1).
- **Limits.** Every walk is bounded by the transmit's node count and keeps a
  visited set; every pointer is checked to lead to a node of the right type.
  B-splines are checked before use (degree 1 to 32, at most 1,000,000 control
  points, knots of the right length that never decrease, positive finite
  weights), charts are at most 1,000,000 points, and every point is finite. A
  limit reached stops the work cleanly with the faces done so far and is
  named in `truncated` (`max_faces`, `max_triangles`, `max_seconds`; the time
  running out among blends aside, above); the time
  limit is checked inside faces too, so one face cannot run on, and
  `tessellate_document`'s counts reading the bodies (a read once started runs
  to its end). Memory follows `max_triangles` and `max_face_points`: the points
  kept, those of faces that failed included, are at most `max_triangles` plus
  twice `max_face_points`, and reaching that stops the work as `max_triangles`
  does. A face's polygon is checked against `max_face_points` before it is
  built, and damaged geometry the checks did not foresee costs that face
  (reason `degenerate`) or, when a body's faces cannot be listed, that body,
  never the call; the
  transmits themselves are capped by `parasolid()`'s `max_bytes`. A starting
  point on a B-spline surface of more than 65,536 control points is looked
  for every few rows and columns, then around the nearest of those.
- **Detail for drawings** (new, provisional). `detail=True` returns, in
  `Tessellation.detail`, a `TessDetail` of what the tessellator knew and the
  mesh does not keep, which a drawing's views need (`docs/DRAWINGS.md` 6.1);
  with `detail=False`, the default, `detail` is None, and the mesh, counts and
  checks are the same either way.
  - `edges` maps (index into `bodies`, EDGE `node_id`) to an `EdgeDetail` for
    every edge of a face done (an edge whose `node_id` is missing or repeats
    another's has -1 minus its node index instead). `points` holds its samples
    from its start vertex to its end vertex (float64, metres), the same points
    both faces' triangles use; `params` each one's parameter on the curve
    sampled (along an intersection curve, its position on the chart); `faces`
    the FACE `node_id` on each side that was done, once per fin; and, for each
    of those, `normals` the face's unit outward normal at every sample, from
    the surface itself, and `vertices` the mesh vertex there (-1 and a NaN
    normal where a sample at a pole is no corner of the face's triangles).
  - `face_uv` gives the (u, v) of every vertex of each mesh face, in the
    surface's own parameters as the tessellator evaluates it (a rolling blend's
    are those of its approximation), so a view can refine a silhouette by
    Newton from there; `points` and `normals` are the mesh's positions and
    corner normals in float64. At a pole the normal is the mean of the face's
    triangles there, as in the mesh.
  - What it costs: on o11 the detail holds 45 bytes a triangle beside the
    mesh, and the detailed call's peak traced memory is under 1 KB a triangle
    (`tests/test_tessellate_detail.py` holds it under 2.35 KB, half the drawing
    prototype's 4.7 KB for the whole drawing child).
- **What it raises**: `InvalidArgumentError` for a bad option and
  `ConfigurationNotFoundError` for an unknown configuration name. Nothing in
  a file raises.
- **Accuracy.** VERIFIED on the fixtures (`tests/test_tessellate.py`): every
  fixture part and configuration that stores a body (14) has SOLIDWORKS'
  volume and area to 0.5 percent (the planar ones exactly, o10 and o11 to
  0.13 percent), its box to the chord tolerance and its centre of mass to it
  too, with every solid closed; SOLIDWORKS' `.x_b` exports of o02, o07, o11 and
  o12 give the same triangles as the bodies inside the parts, and its STL and
  3MF exports of o02 the same box, area and volume. Synthetic whole spheres
  and tori, a cylinder, a hemisphere, a cone, a cylinder whose side is a
  rational B-spline and a sphere that is one rational B-spline face come out
  closed, within 0.5 percent of their volume and area at a chord of 1e-5 m,
  the last with every vertex normal within 15 degrees of its triangles' mean,
  poles included; boxes turned every way whose edges are runs of line edges
  end to end stay closed with their exact volume; and on a small fillet
  (a torus band of radii 1.35 and 0.2 mm at a chord of 31 um) no triangle
  turns more than 30 degrees from the surface. Synthetic rolling blends
  (`tests/test_tessellate_blend.py`) come out closed: a box with one edge
  rounded within 2e-4 of its exact volume and area at chords of 0.1 mm to 2 um,
  a cylinder whose top edge is rounded round a circular spine within 2e-4 of
  the same body with that face on the exact torus, and the rounds of a
  cylinder cut at 30 and 50 degrees (an elliptical spine) with every vertex
  within the chord tolerance of the surface the sphere sweeps and every triangle
  facing out of the material; their 3D print models and the STL and 3MF
  written from them are closed.

**Measured on the development corpus** (its 3,150 readable parts, read-only,
one worker process a part, the active configuration at the default options):
the 1,360 parts that store bodies but no usable display mesh (1,754 solids,
1,019 sheets and 224,139 faces: 188,707 planes, 16,543 B-spline surfaces,
16,123 cylinders, 1,293 tori, 607 spheres, 435 cones, 284 swept and 147 spun
surfaces) have 99.83% of their faces tessellated (223,761). 1,342 of them
are drawn (98.7%; the other 18 are single faces with no area), 1,323 with
every face, and 1,733 of the 1,754 solids come out closed: 17 of the other 21
have faces not done, and 4 a face whose boundary touches or crosses itself
within the chord tolerance, triangulated loosely. The 378 faces not
done are cylinders (130 `seam_configuration`, 32 `degenerate`, 1
`edge_too_long`), planes (108 `degenerate`, 36 `seam_configuration`), B-spline
surfaces (32 `seam_configuration`, 3 `edge_too_long`) and tori (26 with a point
on their axis, 10 `seam_configuration`), nearly all in a few parts whose
features are about as small as the chord tolerance. Reading the bodies and
tessellating them took 0.006 s at the median, 0.50 s at the 90th percentile,
5.8 s at the 99th and 30 s at most (26 parts over 3 s); the peak working set
above the interpreter's own was 3 MB at the median and 429 MB at most, most of
it the reading of the bodies. Over all 3,150 parts the median is 0.09 s. The
mesh keeps 1,490 triangles of three points in a line (of 2,805,145, in 50
parts), which close it where the points lie in a line.

The 1,761 parts that store a display mesh as well give a second reference: the
tessellation's box matches the stored mesh's to 1% of that box's diagonal in
93.5% of them, and its area matches the stored mesh's to 2% in 87.5% (93.7% and 91.0% of the 1,439 whose every face was done, 96.9% and 95.7%
of the 1,071 of those with one closed body). By the richest surface a part
has: planar 116 and 115 of 131, analytic 806 and 788 of 851, B-spline, swept
or spun 512 and 473 of 557, BLENDED_EDGE 212 and 165 of 222 (those faces are
not done). Of the 222 parts that disagree, 111 have several bodies (a stored
mesh leaves out the bodies SOLIDWORKS hides, and they are tessellated) and 92
have faces not done; the worst are six-face boxes whose stored mesh shows
another shape than their stored partition (`docs/FORMAT.md` 10.8). The
triangles number 1.16 times the stored mesh's at the median (0.70 at the 10th
percentile, 2.90 at the 90th), and 9,849 of their 10,423 solids come out
closed. On a sample of 500 parts, once points inside kept off the boundary
chords and a pole's normal became its triangles' mean, the triangles facing
against their vertices' normals fell from 9,770 to 2,304 on B-spline surfaces,
from 3,526 to 300 on tori and from 1,387 to 26 on cones, and the vertices
whose normal is more than 60 degrees from their triangles' mean from 12,330 to
5,417 on B-spline surfaces and from 4,211 to 257 on tori.

**Rolling blends, measured on the development corpus** (the 222 parts whose
active configuration has BLENDED_EDGE faces, 4,280 of their 131,754 faces;
read-only, one worker process a part at below-normal priority on a machine
shared with other work, the code before blends were drawn run alongside at the
same time): at the default options 3,185 of the blend faces are drawn where
none were, every solid of 129 parts comes out closed where no part's did, and
the 98 faces beside blends that tolerant edges took along are drawn too. Of the
blend faces not drawn, the time limit left 539 (blends come last), 423 were
refused `fit_failed` (a spine the sphere cannot be followed along, a fit that
cannot be measured, or one taking more than its 3 s share), 60 lie between two
blends along a tolerant edge (`unsupported_curve`), 12 on a blend resting on a
blend no face uses (`unsupported_surface`), 4 are `inversion_failed` and 1
`orientation_conflict`. Tessellating took 2.5 s at the median (1.3 s before),
23 s at the 90th percentile (7.9 s) and 30 s at most, 4 parts stopping at the
time limit before every face other than a blend was done (5 before); there are
3.46 million triangles (3.15 million). Against the display mesh SOLIDWORKS
stored, 212 of the 221 that have one match the tessellation's box to 1% of its
diagonal (208 before) and 184 its area to 2% (160). At the 3D print's chord
(3.17) 131 of the 222 print models are closed where none was, 81 STL and 3MF
files have an open edge where all 222 did, and a print took 6.4 s at the median
(4.4 s before), 51 s at the 90th percentile (29 s) and 140 s at most (113 s),
for 13.2 million triangles (12.5 million). SOLIDWORKS measured the mass of 14
of these parts (and returned none for 2 more): of the 12 whose prints are
closed, 10 have its volume within 3.3e-4, one within 1.0e-3 and one, a part a
few millimetres long whose volume still grows at the print's chord (SOLIDWORKS'
own display mesh agrees with the tessellation), within 5.5e-3, and all 12 its
area within 1.2e-3. Measured again once a blend's share was capped at 15 s and
its best round kept (the previous code run alongside, on a machine busy with
other work): at the default options the same parts come out closed, the blends
drawn differing only where the load moved the time limit; at the print's chord
the same 131 models are closed and the same 81 STL and 3MF files open, one blend
more is drawn (its first round was within the deviation allowed), and the
prints that had waited 30 s for each blend refused took 62 s instead of 122,
71 s instead of 158 and 39 s instead of 66, all 222 together 2,351 s instead of
2,532. SOLIDWORKS' 14 parts give the same volumes and areas.

### 3.16 Bills of materials: `solidseas.bom` (provisional)

A bill of materials of one assembly configuration, grouped, counted and
numbered as SOLIDWORKS groups, counts and numbers the rows of a BOM table, with
PART NUMBER and DESCRIPTION read as SOLIDWORKS' default BOM template reads
them, for ERP and invoicing. On fixture o16 the top-level and indented BOMs
equal, cell by cell, the two tables SOLIDWORKS itself put on its drawing o19
(`tests/test_bom.py`). `docs/FORMAT.md` 12.7 holds the evidence for each rule.

```python
from solidseas import Root, Roots, model, open_document
from solidseas.bom import csv_bytes

with open_document("D:/Jobs/Example/frame.SLDASM") as doc:
    bom = doc.bom()                                   # top-level only, the active configuration
    for row in bom.rows:
        print(row.item, row.part_number, row.description, row.quantity, row.configuration)
    parts = doc.bom("Lite", bom_type="parts", columns=["Material", "Vendor"])
    tree = doc.bom(bom_type="indented", roots=Roots([Root("jobs", "D:/Jobs")]))
    for row in tree.rows:                             # 3, then 3.1 and 3.2 under it
        print("  " * row.level, row.item, row.part_number, row.quantity, row.total_quantity)
    print(tree.table())                               # the cells SOLIDWORKS would draw
    data = model.build_bom(doc, bom_type="indented")  # the `bom` JSON data
    open("D:/Exports/frame.csv", "wb").write(csv_bytes(data))
```

```python
def build_bom(
    doc,
    configuration=None,               # chosen as components() chooses it (3.8)
    *,
    bom_type="top",                   # "top", "parts" or "indented"
    columns=(),                       # property names, one column each
    part_number_property=None,        # take PART NUMBER from this property instead
    read_properties=True,             # False: open no component file at all
    roots=None,                       # where component files are found (None: the document's folder)
    resolution=None,                  # a Resolution already made against the same roots
    path_map=(),                      # as resolve_references (3.10)
    allow_outside_roots=True,
    cache=None,
    max_instances=10_000,             # the component tree's max_nodes
    max_depth=32,
    max_files=2_000,                  # component files opened from disk
    max_seconds=60.0,                 # finding and reading them, resolution included
    max_file_bytes=None,              # refuse a larger component file
    opener=None,                      # opener(path, within) -> Document
) -> Bom | None
```

`Document.bom(configuration=None, **options)` is the same call. It returns None
for a part or a drawing; an unknown configuration raises
`ConfigurationNotFoundError` and a bad argument `InvalidArgumentError` (naming
it in `detail["parameter"]`: `bom_type` here, `bom_types` for `build_boms`,
and `type` for `model.build_bom`, the name the command line and the service
use). `roots`, `path_map`, `allow_outside_roots` and `cache` are checked
before any work by the rules `resolve_references` applies (3.10), and a root
folder that cannot be walked raises `OSError` (`FileNotFoundError` when it does
not exist) as `resolve_references` raises it, once a component file on disk is
looked for: a mistake in the call is never turned into a note on every row. `build_boms(doc, configuration,
bom_types=..., **options)` returns `{type: Bom}` for several types, reading
each component file once for all of them.

**Rows.**

- An instance is in the BOM when it is neither suppressed nor excluded from the
  BOM, and no sub-assembly above it is either: a sub-assembly excluded from the
  BOM takes its components with it.
- The instances under one parent that use the same file in the same
  configuration are one row, at the place the tree first lists one of them. A
  component pattern's instances, stored after everything else, join their
  seed's row. Two configurations of one part are two rows.
- `top` (top-level only) lists the top assembly's own instances, a
  sub-assembly as one row. `indented` follows each sub-assembly's row with its
  components' rows, one level deeper, numbered `3.1`, `3.2`... under item `3`;
  those rows gather the components of every instance of the sub-assembly.
  SOLIDWORKS keeps one component list per file and configuration, so every
  instance lists the same ones; a damaged tree where they differ gives the
  note `bom_children_differ` on the sub-assembly's row, each QTY. under it is
  the count under the first instance that has the row, and the totals still
  count every instance.
- `parts` (parts only) lists every part at every level once per file and
  configuration, depth first, and leaves sub-assemblies out. A sub-assembly
  that lists nothing in the tree and nothing in its own file is no part. One
  whose components the tree does not list (`bom_children_missing`) stays in as
  its own row, with `doc_type` `assembly`, so that what it stands for is not
  lost. No SOLIDWORKS parts-only table has been compared yet, so the order,
  grouping and quantities of this type are a HYPOTHESIS (FORMAT 12.7).
- `quantity` is the QTY. column: the row's instances under one instance of its
  parent. `total_quantity` is the count in the whole assembly (the quantity
  times its parents'), what purchasing needs; the two are equal at the top
  level and in a parts-only BOM. `instances` lists the component tree id of
  every instance the row stands for, under every instance of its parent.
- `table()` (and `table_cells(type, columns, rows)` for JSON rows) gives the
  cells: `ITEM NO.`, `PART NUMBER`, `DESCRIPTION`, `QTY.` and one column per
  property, as text. An indented table indents the part number by two spaces a
  level, as SOLIDWORKS writes the cell (`"  o02_boxA"`). An unknown description
  is an empty cell.

**Columns.**

- `part_number` is the document name: the file name without its extension, so
  a virtual part is `Part12^o16_asm_features`. SOLIDWORKS uses it by default
  and ignores custom properties such as `PartNo` or `Part Number` for this
  column. With `part_number_property`, the property of that name (the
  configuration's, then the file's, compared case-insensitively) is used where
  the file has it, and `part_number_source` says `property` instead of
  `document_name`.
- `alternate_name` is the alternate name the assembly's component tree stores
  for the row's configuration, or None. A configuration can tell SOLIDWORKS to
  show its configuration name or a name the user typed in BOMs instead of the
  document name, and that name is what the tree stores, but where the file
  keeps the choice to show it is not known (FORMAT 12.7). So `part_number`
  stays the document name, and a row whose `alternate_name` differs from it
  carries the note `bom_part_number_may_differ` and makes the BOM incomplete:
  check those rows against SOLIDWORKS, or use `part_number_property`. On the
  development corpus 82 of 4,819 component models store one, each equal to its
  configuration's name.
- `description` is the property `Description` of the row's file in the row's
  configuration, the configuration's own winning over the file's; `""` when the
  file has none, None when the file was not read.
- `values` holds one text per entry of `columns`, read the same way; None where
  the file has no such property or was not read.
- `properties` holds every effective property of the row's file in its
  configuration (3.2), the full list an ERP may map from, or None when the file
  was not read. A linked property's value is SOLIDWORKS' value at the last
  save (FORMAT 11.1).

**Where each row's file is read from.** A virtual component, or an imported one
stored in the assembly, is the nested document inside the assembly (`location`
None, `nested` its stream); a virtual component of a sub-assembly is read from
inside that sub-assembly's document (`location` the sub-assembly's file);
any other is the file reference resolution finds in `roots` (3.10), opened
read-only `within` its root (or its own folder outside the roots), reading only
the streams it needs, and closed at once. A sub-assembly that stores a document
a row needs stays open until the BOM is built, so the files open together are
those sub-assemblies and the file being read (on the development corpus at
most 3). `resolution` is that file's status
(`resolved`, `moved`, `ambiguous`, `missing`...), or `embedded`,
`embedded_in_subassembly` or `embedded_not_found` for a stored document. A
file that cannot be found or read keeps its row, with what the assembly stores
(part number, quantity, configuration, `stored_path`) and the note
`bom_properties_unread` saying why. A file that lists configurations but not
the row's gives its file-level properties and the note
`bom_configuration_missing`; a file in which SolidSeas finds no configuration
at all gives its file-level properties and `bom_configurations_unknown`. A
sub-assembly whose components are missing from an indented or parts-only BOM
(a limit or a cycle stopped the tree there, or the tree does not list them
while the sub-assembly's own file does, or its own file was not read to check)
carries `bom_children_missing`: SolidSeas does not yet expand a sub-assembly
from its own file, as the display geometry does (3.14).

**`Bom`** has `type`, `configuration`, `configuration_source`,
`children_state`, `columns` (the property columns), `part_number_property`,
`read_properties`, `rows`, `truncated` (the tree was cut by a limit, so
quantities are lower bounds), `complete`, `counts` (`rows`, `instances`,
`files`, `read`, `unread`, `files_opened`, `seconds`), `limits`, `resolution`
(the `Resolution` used, or None) and `warnings` (the tree's, and
`bom_limit_reached` naming a limit that stopped the reading of some files).
`complete` is true when nothing is missing or in doubt: the tree was not cut,
every row's file was read (when `read_properties`), no folder index was cut
short, no row carries `bom_children_missing`, `bom_children_differ` or
`bom_part_number_may_differ`.

**Export.** `model.build_bom(doc, ...)` gives the `bom` JSON data (5.13), the
same on every surface; `solidseas.bom.csv_text(data)` turns it into CSV, and
`csv_bytes(data)` into a file's bytes: UTF-8 after a byte order mark (so Excel
and most ERP imports read `o17_деталь` correctly), `\r\n` line ends, fields
quoted only where they need it (a comma, a quote or a line break), and an
apostrophe before any field that starts with `=`, `+`, `-`, `@`, a tab or a
carriage return, so a spreadsheet never runs a value from a file as a formula.
The columns are the table's, the part number without indentation, then the
property columns, then `LEVEL`, `TOTAL QTY.`, `CONFIGURATION`, `ALTERNATE
NAME`, `DOCUMENT TYPE`, `FILE NAME`, `STORED PATH`, `FOUND AT` (`root:path`,
then any nested streams) and `NOTES` (the note codes). A spreadsheet reads an item number such
as `3.10` as the number 3.1: import the column as text.

**Measured on the development corpus** (`tests/test_corpus.py`
`test_corpus_bom`, every assembly's active configuration, the corpus tree top
as the one root and nothing looked up outside it): 325 assemblies, 16.5 s in
all, 0.016 s per assembly at the median and 1.2 s at most, finding and reading
the files included. They give 2,603 top-level rows, 3,748 parts-only rows and
4,005 indented rows for 7,747 instances in the BOM. In all 325, for all three
types, the quantities add up to the component tree's instances in the BOM
(3.9). Of the 4,005 indented rows, 3,660 (91.4%) had their file read: 2,844
files on disk, 348 documents stored in the assembly and 468 stored in a
sub-assembly. The other 345 carry `bom_properties_unread` (322 missing, 11
ambiguous, 12 stored documents the assembly lost). 61 carry
`bom_configurations_unknown` and none `bom_configuration_missing`; 82 carry
`bom_part_number_may_differ` (81 of them on a file that was not read either),
1 sub-assembly `bom_children_missing`, and none `bom_children_differ`. 247 of
the 325 BOMs are complete. At most 3 files were open at once. 2,038 distinct
files were opened, and none changed.

#### Showing a BOM as edited: `solidseas.bomtable`, `bomexport`, `bomfile`

The viewer's BOM editor and an assembly drawing's parts list share one table
definition. `bomtable.spec(type, columns, order=, hidden=, overrides=)` makes a
`BomTableSpec`: the BOM type, the columns (`item`, `part_number`,
`description`, `quantity`, `total_quantity`, `configuration`, `file_name`, or
`property:<name>`, each with a heading), row keys in the order wanted, row keys
left out, and cell texts keyed by (row key, column id). `bomtable.row_keys(bom)`
gives each row's key: its file name (without regard to case) and configuration,
with the sub-assemblies above it in an indented BOM, so an edit holds when the
BOM is built again. `bomtable.apply(spec, bom)` takes a `Bom` or `bom` JSON and
returns the `ShownTable`: items numbered again as shown, each overridden cell
marked, and `unused` naming the edits whose row or column is gone.

`bomexport.csv_bytes`, `xlsx_bytes` and `pdf_bytes` write a `ShownTable`; the
workbook is written by the standard library, holds text as text (never a
formula) and is the same bytes for the same table. `bomfile.save` and `read`
keep a `ShownTable` and its spec in a `.ssbom` file, by the drawing file's
rules: created new, or written over only the file read or last saved
(`replaces`, its SHA-256).

### 3.17 Exports for 3D printing: `solidseas.export` (provisional)

A part, or one configuration of an assembly, as a binary STL or a 3MF for a
slicer: closed solids over shared vertices, consistently oriented, in
millimetres. The CLI's `export` command (7.1) and the viewer's 3D Print button
write them. The viewer (an application, not this API) writes its print file next
to the model it was made from, named after the document and the local date,
`bracket 2026-10-03.3mf`, and `bracket 2026-10-03 (2).3mf` for the next one that
day, the highest number of a name and extension being the newest; sent as STEP,
the same rules give `bracket 2026-10-03.step`. It writes a 3MF or an STL through
`write_export`, and a STEP through `solidseas.step.write_step` (3.19), to a
temporary name and claims the final name by a rename that never replaces a
file, falls back to a folder under the system's temporary folder where the
model's folder cannot take the file, and removes nothing next to a model but its
own unfinished file ([user guide, 3D Print](guide/3d-print.md#where-the-3d-print-file-goes-and-its-name)).

`print_model` also takes a model file (3.20): its scene is read with B-rep
bodies preferred (a mesh file's own triangles for a mesh format), each object
is welded by exact coordinates and checked as a part's mesh is, and the
scene's items place them; `configuration` must be None or the file's active
configuration, and the model's `source_format` is the file's format id
(`solidworks` for a SOLIDWORKS document). An object from a display
tessellation the file stores is named `(display mesh)` and warned
`display_mesh_fallback`, as for SOLIDWORKS; items that cannot be placed are
left out and counted (`out_of_range`, `no_mesh`, and the scene's own reasons),
with `instances_left_out`. The triangles the items place count against
`max_triangles` too, so a small mesh placed many times raises `SldLimitError`
(`detail.limit` `max_triangles`) rather than writing far past it. A model file
holding only open surfaces or wires, which the export leaves out (its body
types are solids only), raises `NothingToExportError` with `detail.rule`
`no_solid`, so the message says why where the 3D view draws the surfaces.

```python
from solidseas import open_document
from solidseas.export import print_model, write_export

with open_document("D:/Jobs/Example/frame.SLDASM") as doc:
    m = print_model(doc, "Default")            # one object per component file, one item per instance
    m.objects, m.items, m.counts, m.closed, m.warnings, m.skipped
res = write_export(m, "D:/Prints/frame.3mf", "3mf")   # never over an existing file
write_export(m, "D:/Prints/frame.stl", "stl")
write_export(m, "D:/Prints/frame-one.3mf", "3mf", merge=True)   # one object of every placed triangle
```

```python
def print_model(doc, configuration=None, *, name=None, chord_m=None, angle_deg=15.0,
                max_triangles=20_000_000, max_seconds=300.0,
                roots=None, path_map=(), allow_outside_roots=True, cache=None) -> PrintModel
def write_export(model, path, format="3mf", *, merge=False, overwrite=False,
                 max_bytes=2 << 30) -> ExportResult
def export_document(doc, path, format="3mf", *, merge=False, overwrite=False,
                    max_bytes=2 << 30, **options) -> ExportResult | StepResult
def write_new(path, write, *, overwrite=False) -> tuple[str, int]  # the file and its size
def write_stl(model, fh, *, max_bytes=2 << 30) -> int        # to an open binary file
def write_3mf(model, fh, *, merge=False, max_bytes=2 << 30) -> int
def export_bytes(model, format="3mf", *, merge=False, max_bytes=2 << 30) -> bytes
def oriented_closed(triangles, n_vertices) -> bool         # every edge used twice, once each way
```

`export_document` takes `format` from `EXPORT_FORMATS` (`3mf`, `step`, `stl`;
`FORMATS` holds the two print formats `write_export` writes): `print_model`'s
options for 3MF and STL, and for `step` those of `step_model`, returning the
`StepResult` of 3.19. `write_new` is the one way an export creates its file
(the rules of **Writing** below): it calls `write(fh)` with the new file open
for binary writing, which returns the bytes written, and gives back the path
written and that size; the STEP export writes through it too.

- **A part** is exported from its Parasolid bodies, the solids only (a
  surface or a wire cannot be printed; one left out says so with
  `bodies_left_out`) that SOLIDWORKS shows: a body hidden in SOLIDWORKS is left
  out, as SOLIDWORKS leaves it out of its own exports, with `bodies_left_out`,
  and a part whose bodies are all hidden raises `NothingToExportError`
  (`detail["rule"]` `hidden`). An assembly's components are printed the same
  way. The bodies are tessellated by `solidseas.tessellate` (3.15) in the
  configuration asked for. A configuration whose bodies the part does not
  store takes the active configuration's, with `mesh_configuration_differs`,
  as the `brep` source of 3.14 does. Faces that could not be tessellated leave
  holes, which `faces_left_out` says; rolling blends the time ran out on are
  among them (3.15), as they are in a Parasolid file's print (3.20.6). Only when
  the part has no solid body to tessellate is the display mesh SOLIDWORKS saved
  used instead, its vertices
  welded where they meet: its object's `source` is `display_mesh`, its name
  ends in ` (display mesh)`, and the warning `display_mesh_fallback` says that
  it may not be closed. A part whose bodies are all surfaces or wires, and
  whose display mesh is not closed either, raises `NothingToExportError`
  (`detail["rule"]` `no_solid`), as a model file of open surfaces does: a
  slicer cannot print it as a solid. A limit that stops the tessellation raises
  `SldLimitError` (`detail.limit` names it) rather than export part of a
  solid.
- **An assembly** is exported from `display_geometry` (3.14) with the `brep`
  source first: every unsuppressed, visible part instance of the
  configuration, each component file tessellated once from its own bodies
  and placed as the assembly places it, and a stored mesh used only where the
  bodies fail (the file is missing, stores no solid body, or a limit was
  reached), labelled as for a part. Instances that cannot be placed or meshed
  are left out, listed in `skipped` and counted by reason in the warning
  `instances_left_out`; an instance that would lie more than 1,000 km from
  the origin is left out as `out_of_range`, and one whose part holds only
  surfaces or wires and no display mesh was found for it as `surfaces_only`
  (3.14's `bodies_not_asked`, since the export asks for solids only).
  Component files are found as 3.14 finds them (`roots`; None: the
  document's own folder).
- **The chord tolerance.** `chord_m` is the furthest a triangle may lie from
  its surface, in metres (1e-7 to 1e-2). By default each part gets a quarter
  of the 3D view's tolerance (`CHORD_FRACTION`, 2.5e-4 of its bodies' box
  diagonal, where the view uses 1e-3) and never more than 0.01 mm
  (`MAX_CHORD_M`): the slicers simplify a layer's outline to about 0.0125 mm
  by default, so a finer mesh prints no differently. `angle_deg` is the
  tessellator's angle. The tessellator takes the quarter through two options
  of its own, `chord_fraction` and `max_chord_m` (3.15).
- **`PrintModel`**: `name` (the document's file name without its extension,
  or `name=`), `doc_type` (`part` or `assembly`), `configuration`, `objects`
  (each a `PrintObject`: `name`, from the component file's name, told apart
  by configuration and then by number when two share one; `file`, the
  component file key, None for a part; `configuration`; `source`, `bodies` or
  `display_mesh`; `positions` (float64 xyz, metres) and `triangles` (uint32
  index triples) over shared vertices; `closed`; `chord_m`; `warnings`; and
  `measures()`: volume, area and box), `items` (a `PrintItem` per placed
  instance: the object's index, the component tree id and the `Placement`),
  `chord_m` (as asked; None: automatic), `counts` (`objects`, `items`,
  `vertices`, `triangles` over the items, and for an assembly `parts`,
  `placed`, `skipped`, `suppressed` and `hidden`), `skipped`, `warnings`,
  `seconds`, `closed` (every object used is closed) and `measures()` (volume
  and area over the items).
- **Closed and oriented.** An object's `closed` is `oriented_closed` of its
  triangles: every edge used exactly twice, once each way, and no triangle
  repeating a vertex. It takes time n log(degree), each vertex's edges sorted
  and every reverse found by bisection, so a vertex shared by many triangles
  (a fan, which a display mesh can hold) costs no more than many vertices. An
  object that is not closed carries the warning `not_closed`, and its triangles
  are written as they are (a slicer repairs what it can).
- **Shells that face the wrong way.** A closed object's shells (its connected
  pieces) are then judged by how they nest (3.15, self-checks). One that lies
  inside no other and has a negative signed volume can only be a solid inside
  out, and when every shell of the object faces the wrong way the whole object
  is inside out: those are turned round, with the warning `shell_reoriented`.
  A shell facing outward inside another is either a body inside a body or a
  void turned inside out, which the mesh cannot tell apart: it is left as it is
  and warned `shells_inside_out`. So is a shell that touches another so that
  which lies inside which cannot be told (every probe of it lies on the other,
  within the chord tolerance), whichever way it faces: the warning says its
  facing was not checked, and the object is not said to be repaired. A shell
  whose box does not lie inside another's is outside it without a ray, so
  bodies side by side, touching or not, are each judged on their own. An object
  of more than 64 closed shells is not judged at all, and the warning
  `shells_not_judged` says so. Nothing is refused. The model's own
  `solids_not_closed` and `shells_inside_out` from the tessellation or the
  scene are not repeated: the object's are judged on the mesh written.
- **No corners a hair apart.** Slicers read a 3MF's coordinates, like an
  STL's, as float32, whose steps are about 4e-6 mm at 50 mm. Two vertices of a
  triangle closer than that are one point there, and the triangle has no area:
  a slicer counts it as an error and repairs it. So wherever a triangle's
  corners are one point in float32 millimetres, its vertices are merged and
  the triangles left with a repeated vertex dropped: an edge collapse, which
  keeps a closed solid closed (when merging would open one, as where the two
  vertices share a third neighbour, the object is kept as it was). It is done
  once for each object in its own frame, and again when an item is written
  placed (STL, `merge`, a mirroring placement) where the placement's float32
  steps are coarser. A triangle whose corners stay apart but lie on one line
  (a sliver flatter than float32, or float64, can show) cannot be dropped
  without opening the solid; instead its longest edge is flipped with the
  triangle across it, which its middle corner then cuts in two: nothing
  moves, no triangle goes, and both new triangles have area. That is done in
  the object's own frame where the edge is free to flip; a sliver left flat
  gets the normal (0, 0, 0) in an STL.
- **3MF.** The package holds the three parts the 3MF core specification
  requires: `[Content_Types].xml` (the `rels` and `model` content types),
  `_rels/.rels` (the start part relationship to `/3D/3dmodel.model`) and
  `3D/3dmodel.model`, with `unit="millimeter"`, the metadata `Application`
  and `Title`, an `<object type="model">` with its mesh per `PrintObject`,
  and a build `<item>` per `PrintItem`, whose `transform` is the placement
  (the 3 x 4 matrix a row vector is multiplied by, its translation in
  millimetres). With `merge` it holds one object of every placed triangle and
  one item. A placement that mirrors is written out placed, its triangles
  turned, as an object of its own. Numbers are the shortest text that reads
  back as the same float64 (nine digits made corners a hair apart one point,
  and slivers flat); names are escaped, and characters XML cannot hold are
  dropped. The zip
  entries are deflated and dated 1980-01-01, so the same model gives the
  same bytes.
- **STL** is binary: an 80-byte header that does not start with `solid`, the
  triangle count, and 50 bytes a triangle (the unit normal of its float32
  corners, (0, 0, 0) for one with no area, its three corners as float32
  millimetres, and a zero attribute), every item's triangles placed. Its size
  is `84 + 50 * triangles` (`stl_size`), less 50 bytes for each triangle an
  item placed far from the origin lost to the merge above (the count in the
  header is then put right, and `write_stl` returns the size written). STL
  has no objects, so it is always merged.
- **Coordinates** are the document's own, in millimetres: nothing is moved
  onto the build plate or turned to stand up; the slicer does that.
- **Writing.** `write_export` creates the file new (`O_EXCL`, and
  `O_NOFOLLOW` where the system has it): a file already there raises
  `OutputRefusedError` with rule `exists`, and with `overwrite` the export is
  written to a new file beside it and renamed over it, so the old one is
  never written through. A link or a junction at the path is refused (rule
  `link`) either way, and a folder is never replaced. A SOLIDWORKS document
  or template (`.sldprt`, `.sldasm`, `.slddrw`, `.prtdot`, `.asmdot`,
  `.drwdot`, `.sldlfp`, `.sldblk`, in any case) is never written, with
  `overwrite` or without (rule `solidworks_file`), so no export can replace
  a source document. On Windows a path that
  names a device is refused (rule `device_path`: `nul .x.3mf`, in any
  folder, is the NUL device, as is any device name followed by spaces and an
  extension; the reserved names `CON`, `PRN`, `AUX`, `NUL`, `CONIN$`,
  `CONOUT$`, and `COM` and `LPT` with a digit from 1 to 9 or a superscript
  1, 2 or 3, are refused by name, whatever follows the first dot, since newer
  Windows may open the device without naming it in the full path), as are
  the device and extended-length namespaces (`\\.\`,
  `\\?\`) and an alternate data stream (rule `alternate_stream`), which
  would write into a file that is there: the rules of the CLI's write guards
  (7.1). Every write is bounded
  by `max_bytes`: an STL's size is known before anything is written, and a
  3MF stops once it passes. A write that fails, for any reason, removes the
  file it created. `ExportResult` has `path`, `format`, `bytes`, `merged` and
  the `model`.
- **Limits.** `max_triangles` bounds the triangles tessellated or read and
  those placed, a part's display mesh included (checked before it is welded,
  which takes about 250 bytes a vertex); `max_seconds` the time spent
  tessellating (for an assembly, over the call and for each part). The reads
  are bounded as 3.14 and 3.15 say, and the closed check and the weld by the
  triangles.
- **What it raises**: `NothingToExportError` (`nothing_to_export`) for a
  drawing, a part with neither a solid body nor a display mesh, and an
  assembly none of whose instances could be placed; `SldLimitError` when a
  limit stopped a part; `ConfigurationNotFoundError`; `InvalidArgumentError`
  for a bad option or format; `OutputRefusedError` from `write_export`.
- **Verified** on the fixtures (`tests/test_export.py`): o02's STL and 3MF
  have SOLIDWORKS' own exports' box, volume and area to 1e-9 relative, and
  the STL its facet normals; every fixture part and configuration that stores
  a body has SOLIDWORKS' volume, area and box in both formats (the planar ones
  to 1e-9 in the 3MF and 1e-6 in the float32 STL, o10 and o11 within 0.5
  percent); the four fixture assembly configurations place every item on the
  box SOLIDWORKS gave its instance (to 1e-6 m, through the 3MF's own
  transforms) and add up to the assemblies' volume and area; every file is
  read back strictly (the 3MF's package and model structure, the STL byte by
  byte), every object in it is closed and oriented, no triangle has two
  corners at one point in float64 or in float32, and every STL normal is that
  of its stored corners. A synthetic tetrahedron whose edge is split 1e-9 mm
  from its end, 50 mm from the origin, is written as the tetrahedron in both
  formats, closed, merged or not, and so is one placed 100 m out with an edge
  of 1e-3 mm; one whose edge has a vertex 1e-9 mm off its middle, closed by a
  sliver flat in float32, is written with every triangle's area kept, in
  float64 and float32, and still closed.

**Measured on the development corpus** (a random sample of 300 parts and 80
assemblies, read-only, at the default options, each assembly with its own
folder as the root and nothing outside it looked up; every export was written
to a scratch folder, read back and deleted; measured on this release's code,
and the code before its float32 merges and flips measured on the same sample
for comparison): 281 parts were exported, 279 from their bodies and 2 from
their display mesh; 18 hold neither a solid body nor a display mesh
(`nothing_to_export`) and one passed the 300 s limit. 254 of the 281 (90.4%)
are closed and oriented. The 25 from bodies that are not have faces the
tessellator did not do then (BLENDED_EDGE rolling blends were 246 of the 258
faces left out; they are drawn now, 3.15), and every one of them is just as open at the 3D view's
chord: the finer print chord opens none. Building a part took 0.29 s at the
median, 3.4 s at the 90th percentile and 45 s at most; writing its 3MF
0.012 s and its STL 0.006 s at the median (2.1 s and 0.85 s at most). The 3MF
was 33 KB at the median and 8.6 MB at most (27 KB and 6.4 MB when it wrote
nine digits), the STL 106 KB and 20 MB, for 2,114 triangles at the median and
401,674 at most; the chord came out at 0.01 mm for most parts and 0.001 mm
for the smallest. 76 of the 80 assemblies were exported (4 place no
instance), with 1,488 of their 1,887 part instances (247 left out: 212 whose
file is missing, 24 of surfaces only, which were reported as storing no
display mesh before, 10 with no mesh and 1 with no components; 54
suppressed, 98 hidden). 477 of their 1,016 objects came from the parts'
bodies (419 of them closed) and 539 from the meshes the assemblies store,
used where a part's bodies could not be had, with only the assembly's own
folder searched for its files (359 of those closed once welded): 778 objects
(77%) are closed. An assembly took 4.1 s at the median, 42 s at the 90th
percentile and 181 s at most; its 3MF was 763 KB at the median and 31 MB at
most (605 KB and 24 MB with nine digits), its STL 2.6 MB and 86 MB. An
export's memory peaked at 24 MiB for a part at the median and 138 MiB at
most, and at 44 MiB for an assembly at the median, 240 MiB at the 90th
percentile and 1.25 GiB at most, inside the 4 GiB the viewer's export process
may use.

No triangle in any file read back has two corners at one point, read as
float64 or as float32; before, the parts' STLs held 1,173 such triangles (6
parts) and the assemblies' 4,431 (14). Triangles with no area at all: in the
parts' STLs 2,457 (71 parts) before and 201 (8 parts) now, in their 3MFs read
as float64 1,984 (69 parts) before and 1 now; in the assemblies' STLs 7,759
(49) before and 1,032 (23) now, in their 3MFs read as float64 4,692 (45)
before and 16 (2) now. The edge collapse merged corners in 6 parts and 13
assembly objects (4,535 triangles dropped), 2,912 flips gave area to 3,621 of
the 4,078 flat triangles found, and the STLs of 8 assemblies lost 1,068 more
triangles to the collapse where items are placed far from the origin. The
flat triangles left have no neighbour across their long edge (they border a
hole), or a flip there would leave a triangle flat or an edge doubled; in
the assemblies' STLs there are also slivers that placing flattens. Each has
the normal (0, 0, 0). Before, 4,011 STL normals in 81 parts and 72,209 in 59
assemblies disagreed with their float32 corners; none does now. Six closed
parts are still not closed when an STL reader joins vertices by position:
their bodies touch or overlap exactly (the same float64 points, faces
doubled once joined), which a slicer sees in any format. Every 3MF read back
with the objects, items and triangles written and the same objects closed,
every STL had exactly the size written, and no corpus file changed.

### 3.18 The catalog: `solidseas.catalog` (provisional)

A catalog is an index of the 3D files below a set of roots (SOLIDWORKS
documents, and when asked every other format SolidSeas reads), kept in
SQLite so the desktop app and integrations can ask questions without reading
the files again: which assemblies and drawings use a part (where-used), search
by name, part number, description or any property, files with identical
contents, references that resolve nowhere, and what changed recently. A
document is identified by its path below its root, its file id and the SHA-256
of its bytes.

```python
from solidseas import Root, Roots, catalog

if __name__ == "__main__":                    # documents are read in worker processes (3.13)
    roots = Roots([Root("project", "D:/Jobs/Example"), Root("parts", "D:/Library", role="library")])
    with catalog.open(roots) as cat:         # the catalog of D:/Jobs/Example, in your cache folder
        result = cat.scan()                  # catalog_scan data: what was added, changed, moved...
        used = cat.where_used("project", "frames/bracket.SLDPRT")
        for u in used["users"]:
            print(u["relation"], u["path"], [(x["user_configuration"], x["instances"]) for x in u["uses"]])
        hits = cat.search("pn:BR-100 type:part")
        dups = cat.duplicates()
    with catalog.open(roots, mode="r") as cat:  # read-only, from any process, while a scan runs
        print(cat.status()["counts"])
```

```python
catalog.open(roots=None, *, location="cache", name=None, db=None, cache_dir=None, mode="w") -> Catalog
Catalog.scan(*, pool=None, workers=2, hash=None, previews=True, file_timeout=30.0,
             max_seconds=None, max_file_bytes=None, progress=None, cancel=None) -> dict   # catalog_scan
Catalog.status(*, paths=True) -> dict                                                     # catalog
Catalog.where_used(root, path, *, configuration=None, indirect=True, max_depth=32,
                   max_seconds=None) -> dict                                              # where_used
Catalog.search(text, *, sort="relevance", limit=100, cursor=None) -> dict                 # catalog_search
Catalog.duplicates(*, names=False, limit=500, cursor=None) -> dict                        # duplicates
Catalog.missing_references(*, limit=500, cursor=None) -> dict                             # missing_references
Catalog.changes(*, since=None, limit=500, cursor=None) -> dict                            # catalog_changes
Catalog.preview(root, path) -> (mime, bytes) | None
Catalog.locate(host_path) -> (root id, path below it)
Catalog.configure(*, part_number_property=..., hash=..., events_days=None, formats=None)
Catalog.formats -> frozenset[str]                                                         # the format ids it indexes
Catalog.reader() -> Catalog                                                               # read-only, for another thread
catalog.cache_dir(); catalog.locate(...); catalog.list_catalogs(); catalog.find_catalog(path)
catalog.catalog_name(db_path) -> str | None                                               # the name it was made with
catalog.clear(name=None, *, db=None, roots=None, location="cache", cache_dir=None, all=False) -> list[str]
```

Every query returns the JSON data of its kind (section 5.15), identical from
Python, the command line (7.1) and the service (8.6). Locations are a root id
and a path below the root, `/`-separated, in the on-disk spelling (C1); the
roots' own paths appear only in `status()`, and only with `paths=True`.

**Where a catalog lives.** By default in your cache folder, one catalog per
project folder: `%LOCALAPPDATA%\SolidSeas\catalogs\<name>\` on Windows (the
folder the service's token file uses, which Windows does not roam) and
`$XDG_CACHE_HOME/solidseas/catalogs/<name>/` (`~/.cache/solidseas/...`)
elsewhere; `SOLIDSEAS_CACHE_DIR` replaces the base, and `cache_dir=` does for one
call. `<name>` is `folder-` and 16 hex digits of the SHA-256 of the first
project root's folded path, or the `name` given (`[a-z0-9_-]{1,32}`). The roots
given to `open` become the catalog's at the next scan: a root left out is
removed with its rows, and the scan says so (`removed_roots`). Roots that
overlap (one inside another) are refused (`invalid_argument`, rule
`overlapping_roots`).

- `location="project"` keeps it in `<first project root>\.solidseas\`, only when
  asked for by name. It is refused on a network location (`path_refused`, rule
  `network_location`), as is a `db=` there: SQLite's write-ahead log needs
  memory shared on one machine, and its locks are unreliable over SMB and NFS.
  On Windows that is a UNC path or a mapped network drive; on Linux a network
  file system's mount (NFS, SMB, and FUSE file systems such as sshfs and
  rclone: `solidseas.netfs.NETWORK_TYPES`), told from the path's text and the
  kernel's mount table (`/proc/self/mountinfo`) without asking the share
  anything, so a link from a local folder into a share is not seen. On macOS
  the table comes from `getfsstat` without waiting on any share, and a mount
  is a network one by its type (`smbfs`, `nfs`, `afpfs`, `webdav`, `ftp`) or
  when the system does not mark it local, as with a macFUSE file system such
  as sshfs. Where the table cannot be read, the caller keeps the catalog on a
  local disk, and the command line refuses `--in-project` and asks for `--db`. The folder then carries the names, properties and
  stored paths of every file in the project. A writer refuses a database,
  previews file, journal or lock that is a link or not a plain file, in any
  location (`path_refused`, rule `link` or `not_regular_file`), so a link
  planted in a project's `.solidseas` folder is never written through.
- `db=FILE` puts the database at FILE (its folder must exist; neither may be a
  link, and a SOLIDWORKS extension is refused); the previews and the lock go
  beside it as `FILE.previews.sqlite` and `FILE.lock`.
- Folders are made owner-only on Linux and macOS (0700). A catalog's folder that
  another account owns, or that lies inside a folder everyone may write to
  without the sticky bit (so that anyone could swap it for a link), is refused
  there (`path_refused`, rule `not_private`); Windows guards folders by their
  access lists. A scan never writes into a scanned folder unless the
  in-project location was asked for.
- A database that is not a catalog (another program's SQLite file, any other
  file) is refused before anything is written to it or made beside it
  (`catalog_incompatible`, rule `not_a_catalog`); its header is read from the
  file itself, without opening it as a database. One written by a newer
  SolidSeas is refused for writing (rule `too_new`) and read while its
  `min_reader_schema` allows. One written by an older SolidSeas is brought up to
  date in place by the next writer that opens it: schema version 2 added the
  Alibre GUID columns, which a version 1 reader passes over, and has the Alibre
  files read again. One SQLite finds damaged is `catalog_incompatible`
  with rule `damaged`, whose message says to clear it; a damaged catalog in
  the cache folder is deleted and made again by the next writer that opens or
  scans it (it is a cache of what the files say), while one at a location the
  caller named (`db=`, the project folder) is left for the caller to clear.
  `find_catalog` finds a catalog that cannot be read by its default name, so
  the command line says it is damaged instead of "index its folder first". A
  catalog SQLite cannot write (a read-only file) is `permission_denied`.
- SolidSeas never makes a view or a trigger in a catalog or its previews. A
  database holding one, which another account could have planted in a shared
  project's `.solidseas` folder to make a query hang or answer wrongly, is
  refused before any query reads a table, in every location
  (`catalog_incompatible`, rule `unexpected_schema`, `value` how many), and
  every connection runs with SQLite's `trusted_schema` off, so nothing in a
  database's schema runs a function that is not harmless.

**Which formats.** A catalog indexes SOLIDWORKS documents until
`configure(formats=...)` says otherwise: `"all"` for every format SolidSeas
reads (STEP, Parasolid, ACIS, Alibre Design and the mesh formats, 3.20), or
format ids (3.20.3), as a list or joined by commas. The setting is kept with the
catalog (`status()["formats"]`); a format SolidSeas lists but cannot read (IGES,
Inventor...) is never indexed, and naming only such formats, or an unknown id,
is `invalid_argument`. Files of a format the setting leaves out are removed
from the catalog at once, with what was read of them and no change event (the
files did not change), and those of a format it adds are indexed by the next
scan, as `added`. A model file is read as the folder listing reads it
(`open_any`, its head only, never its tree, scene, bodies or the files it
names): its format, type, units, header counts, the image it stores (as a PNG
SolidSeas wrote) and its properties. It has no configurations, so no part
number or description; search finds it by its name, folder and properties, and
`format:` (below) by its format. Of the model files' references the catalog
follows an Alibre Design assembly's components, so where-used finds the Alibre
assemblies that place an Alibre part or sub-assembly, directly and through
sub-assemblies, with each assembly's active configuration as
`user_configuration` and its inclusions as the counts (Alibre stores no
suppression or BOM flag the reader knows, so `unsuppressed` and `in_bom` equal
`instances`). The record holds the document GUID and version each Alibre file's
`VERSION` stream gives and, for an assembly, the GUID and version each inclusion
asks for, read from its design database alone (the files are never looked for
there). They are resolved from rows by GUID, as the live resolver does (3.20.8),
within the roots: one file of the GUID is `resolved` (rule `document_guid`,
confidence `high`); among several the nearest (the assembly's own folder, then
below it, then the fewest folders down) with confidence `low` and the warning
`component_ambiguous`, every one a candidate; a newer or older version than the
one asked for is warned `component_newer` or `component_older`; failing that, a
file of the stored name in the assembly's folder whose GUID could not be read is
`resolved` by rule `name`, confidence `low` (`component_found_by_name`); else the
reference is `missing`. Any Alibre file added, changed, moved or removed has every
Alibre assembly resolved again. No other model format's references are followed
yet (a STEP file's external documents, a glTF buffer, an OBJ material library),
so where-used of such a file lists no users. The command
line's `index --formats` sets it (7.1), the service indexes the formats it was
started to read (8.6), and the viewer what its list shows.

**One writer, any number of readers.** `mode="w"` takes an operating-system lock
on the catalog's lock file for as long as the catalog is open: a second writer
gets `busy` (rule `catalog_locked`) at once, and the lock goes with a process
that dies. `mode="r"` opens the database read-only; readers never block the
writer and each query sees one consistent snapshot, even mid-scan. A `Catalog`
is not thread-safe: open one per thread (`reader()`). `clear()` refuses with
`busy` while a writer holds the lock. A writer that dies leaves its scan marked
running; a reader that finds the lock free reports that scan `failed`, as the
next writer records it, and the catalog `ready` or `partial`, not `scanning`.

**What a scan does.** The process that holds the catalog never parses a CAD
file: every document is read by the `catalog_document` job and every hash by
`content_hash` in a `WorkerPool` (3.13), the scan's own pool running below
normal priority unless a `pool` is given (its roots must include the
catalog's), and every folder is walked by the one walker (3.7: links never
followed, cloud placeholders never opened, `~$` lock files skipped). The
writer checks each worker's answer as untrusted, field by field (types,
enumerations, ranges, text lengths, at most 10,000 configurations, 10,000
properties, 100,000 references, 200,000 model-graph rows and 10,000 views per
document); a record that fails is that file's error, `internal` with rule
`invalid_record`, and nothing of it is stored. The job itself keeps a real
document inside those limits, so a large one is indexed, not refused: longer
text is cut, properties and configurations past the limits are left out, and a
model graph or view list over them is left out whole (that document then adds
nothing to where-used). A preview image is kept only when it is the PNG or BMP
its record describes, by signature, size and SHA-256.
The phases, each committed in batches (64 documents or a quarter of a second)
so readers see rows as they arrive:

1. **Walk and compare.** A file is unchanged when its size and modification
   time from the directory listing equal what was stored and, where the listing
   gives a file id (Linux and macOS), its file id too; nothing else is looked
   at, and an unchanged file is never opened. So a file rewritten in place with
   its size and modification time put back is not noticed, its hash and what
   was read of it included, until either changes. A changed one is read again
   and its hash dropped. A file freed to a cloud placeholder, or brought back,
   with the same size and time keeps what was read of it (a placeholder is
   never read). A path new to the catalog is matched to a row that vanished in
   the same scan by file id, size and modification time, so a renamed or moved
   folder is not read again; the file id is taken with `lstat` after every
   folder from the root down was found to be a folder and not a link. On a
   filesystem without file ids a match by folded name, size and time keeps the
   row and its history, but the file is read again, since nothing proves it is
   the same file. A renamed document's part numbers that come from its name
   follow the new name, and its search words follow it. A vanished row is
   deleted when the folder that held it was listed completely, or when that
   folder is now a link; it is kept and marked stale when the walk could not
   tell (a folder that could not be listed, a depth-limited or placeholder
   folder, a root that is unavailable, a walk a limit or a cancel cut short),
   so a share that is offline never empties the catalog.
2. **Read.** Every new or changed document, in a worker with `file_timeout`
   and the pool's memory cap; one larger than `max_file_bytes` (default 2 GiB)
   is refused from the listing's size without a job. Locked, busy, timed-out
   and crashed reads are tried again at the next scan; a file that times out or
   crashes its worker twice at one size and time is `quarantined` until it
   changes. A read that never started because a `pool` shared with other work
   had no worker free in time is `busy` (rule `no_free_worker`): tried again,
   never counted toward quarantine. A STEP file wearing a SOLIDWORKS extension
   is `not_solidworks`. A model file SolidSeas cannot read after all (an ACIS
   text file, a damaged STL) is that file's error, `format_not_supported` or
   `damaged_file`, and is not read again until it changes.
   Rows read by an older version of the job are read again after the new ones.
3. **Resolve.** Each assembly and drawing read in this scan, those whose
   references name or found a file added, changed, moved or removed in it, one
   that was itself moved (what its references find depends on where it is),
   and every one when the roots changed, is resolved with `resolve_references`
   itself (3.10). Which ones is recorded in the transaction of the change that
   asks for it, so a scan cancelled or a process killed before this phase
   leaves them for the next scan, and the catalog is not `ready` meanwhile. It
   is resolved
   from rows: the folder index of each root is built from the catalog, an
   identity is the creation time stored for the candidate (only while the file
   is as it was read), and nothing outside the roots is looked at
   (`allow_outside_roots=False`). So "missing" means "not within the indexed
   folders": adding a library root is the answer for shared parts. On the
   development corpus the catalog's results equal live resolution's for 4,844
   of 4,844 references.
4. **Hash.** The SHA-256 of each file whose hash is missing or stale, by
   `hash`: `all`; `duplicates`, only the files whose size another file shares
   (which still finds every duplicate); or `none`, which finds none. The
   default is `all` on a local drive and `duplicates` on a share, where reading
   every byte costs most. Each root's policy is recorded (the `hash_policy` of
   its entry in `status()`), and `hash_pending` everywhere counts the files that
   policy wants hashed and that have no current hash. A hash is kept only when
   the file did not change while it was read.

`progress(phase, done, total)` is called as a scan goes (`walk`, `read`,
`resolve`, `hash`; `total` is 0 while the walk counts). `cancel` (a
`threading.Event`) and `max_seconds` stop it between folders and files: what
was committed stays, and the next scan carries on from the rows still waiting.
Error objects in the result never carry the reader's message (it can hold a
path).

**Where-used** follows resolved references, never names. `users` lists, for the
file at `path`:

- `component`, depth 1: an assembly whose own tree holds the file, with `uses`
  per configuration of the assembly (`user_configuration`) and of the file
  (`configuration`): `instances`, `unsuppressed` and `in_bom` at that level, as
  a top-level BOM counts them;
- `drawing_view`: a drawing whose views show the file (`views`: sheet, view,
  configuration);
- `component`, depth 2 and up: an assembly that holds it inside a
  sub-assembly, through the sub-assembly's own document (what SOLIDWORKS
  loads), with `via` the chain from the user down and the quantities multiplied
  along the configuration chain (`via_configurations`). Unsuppressed and in-BOM
  counts multiply only through unsuppressed and in-BOM links, so a sub-assembly
  left out of the BOM takes its components with it;
- `drawing_of_assembly`: a drawing that shows an assembly holding the file;
- `stored_tree`: an assembly whose sub-assembly's own document cannot answer
  (it resolves to no file of the catalog, or to one not read: an error, a
  cloud placeholder never read, a document cut for size, one with no
  component tree), from what the assembly's own tree stores inside it (warning
  `from_parent_tree`; `via` names the sub-assembly by its stored file name, or
  by the catalog's file when it resolves to one, with `stored: true`), so a
  part inside a missing or unreadable sub-assembly still shows its top
  assembly;
- an assembly with no component tree (an old file that names its components in
  its header alone) is a `component` with no `uses` and the warning
  `quantity_unknown`, and nothing above it is followed.

`possible` lists the ambiguous references among whose candidates the file is,
with the other candidates, and `name_matches` the missing or ambiguous
references whose file name is the file's: an assembly wants a file of that name
but resolution could not decide on this one. Neither is counted. A document
already on a chain is not followed again (warning `cycle`), and a low-confidence
resolution is marked `low_confidence`. `configuration` keeps only the uses of
that configuration of the file (`configuration_not_found` when the file has
none of that name); `indirect=False` keeps depth 1. Bounds: 32 levels, 10,000
users and 200,000 steps of the walk up (a reference followed, a chain of a
stored tree climbed, a configuration use composed), whatever the trees
stored, then `truncated` with what was found; `max_seconds` stops a longer
walk with `timeout`. `as_of` is the time of the last complete scan of the
file's root, and `complete` is false while rows wait to be read or resolved,
are stale, or a root is partial or unavailable. The warning
`unread_documents` says the catalog holds assemblies or drawings it could not
read (an error, a cloud placeholder never read, a document cut for size):
they may use the file too. A path the catalog does not hold raises
`not_in_catalog` (a spelling that differs only by case finds the one file it
matches).

**Search.** `text` holds words, each matched as a prefix of a word in the
document's name, part numbers, descriptions, property names and values,
configuration names or folder names; `"a phrase"`; and filters:
`type:part|assembly|drawing`, `format:ID` (a format id of 3.20.3, `solidworks`
for SOLIDWORKS documents), `root:ID`, `folder:sub/path`, `pn:` (part number),
`desc:` (description), `prop:Name` or `prop:Name=value` (exact,
case-insensitive), and `changed:7d`, `12h`, `2w` or a date such as
`changed:2026-09-01`. A filter value with spaces is quoted:
`prop:Description="Oracle test box"` or `desc:"test box"`; unquoted, the value
ends at the first space and the rest are words (the command line quotes each
argument that holds a space itself, 7.1). The text never reaches SQLite's
full-text syntax as written: each word is quoted, and a control character is
`invalid_argument`. `sort` is `relevance` (FTS5's rank), `name` or
`modified`; `limit` is 1 to 500, and `next_cursor` continues a page. Where the
SQLite library lacks FTS5, the same words are matched with `LIKE` and
`engine` says `like`. Each result carries the active configuration's part
number and description and the fields its words `matched`.

**Part numbers and descriptions** are worked out as `solidseas.bom` does
(3.16): the document name, or with `configure(part_number_property="PartNo")`
that property's value (the configuration's own, then the file's), recomputed at
once from the stored properties; the description is the effective
`Description` property of the configuration.

**Duplicates** are groups of files with one SHA-256, with the bytes the extra
copies take; `hash_pending` says how many files the hash policy wants hashed
that are not yet, and the answer is partial until it is 0 (with the policy
`none` nothing is hashed and no group is found). `names=True` adds the groups
of files that share a folded name but differ in content, which is what makes
resolution ambiguous; both lists are paged together (`limit` of each per page,
`next_cursor` while either has more), and `counts.name_groups` counts them
all. **Missing references** lists, per document, every reference that is
`missing`, `ambiguous` or `embedded_not_found`, and every low-confidence one,
with its candidates and how many files of its name the catalog holds.
**Changes** lists the events of the last scans, newest first: `added`,
`changed`, `moved` (with the previous path), `removed` and `read_error`, kept
90 days (`configure(events_days=...)`).

**What a catalog holds, and where it goes.** Every document's name and path
below its root, the roots' own paths, every custom and configuration property
(part numbers, descriptions, customer names, prices if a property holds them),
summary fields (author, last saved by), the stored paths of references
(absolute paths from other machines, with account and server names: the very
data the path report flags), preview images, hashes and 90 days of change
events, names of removed files included. It stays on this machine: the catalog
has no network code, the service serves it only when started with `--catalog`
and only as root ids and relative paths, the AI connector never reads it, and
the service logs counts, never names or values. `clear()` (the command line's
`clear-index`, the viewer's Settings > Clear Index) deletes a catalog's files.

**Measured** on the development corpus (3,527 documents in 38 roots, 117,018
directory entries, a local NVMe disk, two workers, warm cache): the first scan
took 17.9 s (the walk 2.6 s, reading 9.5 s or 2.7 ms a document, resolving 354
documents 2.4 s, hashing 2,979 MB 3.4 s); its rows appeared as the walk went,
and the first document's data 0.7 s after it, once the workers had started; a
scan with nothing changed took 2.3 s, all of it the walk, and read nothing;
`catalog.sqlite` took 2.9 MB and `previews.sqlite` 19.4 MB per 1,000
documents; where-used over every file took 0.6 ms median, 1.3 ms at the 99th
percentile and 15 ms at most; search took 43 ms at most; and no file's size or
modification time changed. A crafted assembly whose stored tree branches at
every level (2^24 chains) answers where-used in 1.3 s, truncated.
Every reference live resolution found in an assembly or drawing shows that
document in the where-used of its target, but for 3 of 3,637, where the
sub-assembly's own document names another file than the top document's tree
does.

`import solidseas.catalog` works without Python's `sqlite3` module; opening a
catalog then raises `not_implemented` and says why.

### 3.19 STEP export: `solidseas.step` (provisional)

A part's or an assembly's Parasolid bodies as a STEP file (ISO 10303-21,
application protocol AP214, schema `AUTOMOTIVE_DESIGN`), without SOLIDWORKS: the
exact B-rep, faces on their surfaces and edges on their curves, for suppliers,
customers and other CAD systems. The CLI's `export --format step` (7.1), the
viewer's File > Export STEP, and the viewer's 3D Print when it sends STEP write
it. 3D Print sends a document this export refuses or stops on at a limit as a
3MF instead and says why; it never sends a STEP with bodies or instances left
out ([user guide, 3D Print](guide/3d-print.md#what-goes-into-a-step)).

An assembly is one product for itself and one for each part and configuration it
places, written once however many instances place it; each instance is a
`NEXT_ASSEMBLY_USAGE_OCCURRENCE` whose `CONTEXT_DEPENDENT_SHAPE_REPRESENTATION`
maps the part's origin onto an axis placement in the assembly's frame (an
`ITEM_DEFINED_TRANSFORMATION`), as SOLIDWORKS writes it. Its instances, their
placements and the documents they are of come from `display_geometry` (3.14),
which finds the component files with `step_model`'s `roots`, `path_map`,
`allow_outside_roots` and `cache` as 3.14 says: a part's own file, or a virtual
part's document inside the assembly that stores it. A sub-assembly the
component tree lists is an assembly product of its own, its occurrences placing
its parts and sub-assemblies in its frame; sub-assemblies of one file and
configuration whose contents are placed alike share one product. A level the
tree does not list (one read from a sub-assembly's own file) is not a product:
its parts are placed in the nearest sub-assembly it does list. An instance whose component was not found or
could not be read, whose part this export refuses (another configuration's
geometry is never written in its place, as for a part), or that is placed
mirrored (an axis placement cannot mirror) raises `NotRepresentableError` (rule
`instances_left_out`, `value` how many, the message naming each and why);
with `allow_partial` those instances are left out, `skipped` lists them, the
file says it is incomplete, and the warning `step_instances_left_out` says why.
An assembly none of whose instances can be written raises
`NothingToExportError` (rule `no_instances`). `counts` has `products` (the
assembly, its sub-assemblies and its parts), `sub_assemblies` and `instances`
(the part instances written), and `instances` lists each written part
instance's id and the name of its part's product.

`step_model` also takes a model file (3.20) of the one format whose bodies are
Parasolid's: a Parasolid transmit file (`.x_t`, `.x_b`, `.xmt_txt`,
`.xmt_bin`, `MODEL_FILE_FORMATS`). Its transmit is read as the reader reads it
(3.20.6) and its bodies mapped as `step_transmit` maps them, one product named
after the file, in the file's one configuration (another name raises
`ConfigurationNotFoundError`); `source_format` is `parasolid` and the originating
system the program its header names. A transmit whose root is an assembly, or
that places bodies by instances is written as the transmit holds it: a part
product for each body, written once however many instances place it, an
assembly product for each of its assemblies, named after the file for the top
one, and an occurrence for each instance at its transform in its assembly's
frame. A partition whose several top-level parts include assemblies gets a top
product placing each at the identity. An instance the reader leaves out (3.20.6),
one placed mirrored, scaled or sheared (an axis placement holds a turn and a
move only) and one whose body the export refuses raise `NotRepresentableError`
(rule `instances_left_out`) unless `allow_partial` leaves them out, as for a
SOLIDWORKS assembly; a body of a type not asked for is left out with its
instances (warning `bodies_left_out`). The one exception is the transmit
SOLIDWORKS writes for a multi-body part: one assembly placing each of its
bodies once, at the identity, is that part, its bodies written as one product
(`solidseas.formats.xt.bodies_in_place`). Any other
model file raises `UnsupportedOperationError` (`not_implemented`,
`detail.rule` `model_file`, `detail.value` its format id): a mesh file holds
triangles, and a STEP, ACIS or Alibre Design file's bodies are not Parasolid's,
so the viewer's 3D Print sends such a file as 3MF, saying why, and its File >
Export STEP is off for it.

```python
from solidseas import open_document
from solidseas.step import step_configurations, step_model, write_step

with open_document("D:/Jobs/Example/bracket.SLDPRT") as doc:
    step_configurations(doc)                 # the configurations whose bodies the part stores
    m = step_model(doc, "Default")           # mapped and checked; nothing written yet
    m.exact, m.max_deviation_m, m.uncertainty_m, m.bodies, m.counts, m.warnings
res = write_step(m, "D:/Out/bracket.step")   # never over an existing file
```

```python
def step_model(doc, configuration=None, *, name=None, body_types=("solid",),
               allow_partial=False, exact_only=False, fit_tolerance_m=1e-7,
               max_deviation_m=1e-6, max_faces=200_000, max_entities=20_000_000,
               max_seconds=300.0, split_periodic=True, include_hidden=False) -> StepModel
def write_step(model, path, *, overwrite=False, max_bytes=2 << 30, time_stamp=None,
               file_name=None) -> StepResult
def step_bytes(model, *, file_name=None, max_bytes=2 << 30, time_stamp=None) -> bytes
def write_step_to(model, fh, *, file_name, max_bytes=2 << 30, time_stamp=None) -> int
def step_configurations(doc) -> list[str]
def step_transmit(xt, *, name="body", body_types=("solid",), **options) -> StepModel
def uncertainty(deviation_m) -> float
```

`export_document(doc, path, "step", **options)` (3.17) dispatches to them.
`step_transmit` maps a parsed .x_t or .x_b (or a sequence of them) as one
product. `StepModel.source_format` is the registry id of the file the bodies
came from (`solidworks`, `parasolid`), as `export_result.source_format` says. `write_step`'s `file_name` is the name the header gives (None: the
file's own), for a file written under another name and renamed afterwards.

- **What is written.** Every body of the configuration (None: the active
  one), read by `Document.parasolid()` as the tessellator reads them (3.15):
  each solid as a MANIFOLD_SOLID_BREP (a BREP_WITH_VOIDS when a solid region
  has cavities, each void an ORIENTED_CLOSED_SHELL whose faces point into the
  cavity), named with the body name SOLIDWORKS gives it
  (`docs/FORMAT.md` 10.9; else `Body`, `Body2`...).
  A body SOLIDWORKS hides (`docs/FORMAT.md` 10.9, Hidden bodies) is left out,
  as SOLIDWORKS' own STEP leaves it out, with `bodies_left_out` (reason
  `hidden`), whatever its type; `include_hidden=True` writes it. A part whose
  every body the export would write is hidden raises `NothingToExportError`
  (`detail.rule` `hidden`; its message names no option, as the viewer shows
  it). A part that shows sheets and nothing else the export would write, when
  only solids were asked for, raises `sheets_not_asked` (below) whatever it
  hides, so that asking again with sheets writes them, as File > Export STEP
  does. Where the part does not say whether a body is
  hidden (some imported bodies carry no mark) and it has several solids, all
  are written and `step_hidden_bodies_unknown` says so. A transmit's bodies
  (`step_transmit`, a Parasolid file) are all written.
  With `body_types=("solid", "sheet")` sheet bodies are written too, as
  SHELL_BASED_SURFACE_MODELs; a part of sheets only, without that, raises
  `NothingToExportError` saying to ask for sheets (`detail.rule`
  `sheets_not_asked`), and sheets beside solids are left out with
  `bodies_left_out` (reason `not_asked`). Wire bodies are left out with
  `bodies_left_out` (reason `unsupported_body`); neither refuses the export.
  A general (non-manifold) body, and a body whose type is damaged or unknown
  (`bad_reference`), is not representable.
- **No other configuration's geometry.** A configuration whose bodies the part
  does not store raises `NothingToExportError`, naming the configurations it
  does store (`step_configurations`): unlike the 3MF export, the active
  configuration's bodies are never taken in its place.
- **Exactly where STEP can.** Planes, cylinders, cones (a negative half angle
  written about the reversed axis, a zero one as a cylinder), spheres, tori
  (a ring as TOROIDAL_SURFACE, an apple and a lemon as
  DEGENERATE_TOROIDAL_SURFACE, the lemon with its x axis reversed and its
  orientation turned round, since Parasolid's (u, v) is ISO's (u, pi - v)
  there), B-spline surfaces (clamped by knot insertion, Parasolid's knots
  kept), swept surfaces (SURFACE_OF_LINEAR_EXTRUSION), spun surfaces
  (SURFACE_OF_REVOLUTION, whose u and v are Parasolid's the other way round,
  which turns its natural normal round; one whose profile is symmetric about
  its axis or crosses it covers itself twice, with opposite normals, so a
  reader could take its faces either way round, and is
  `unsupported_surface`), offset surfaces, lines (VECTOR
  magnitude 1000.0 so that the parameter stays in metres, as SOLIDWORKS
  writes it), circles, ellipses, B-spline curves (a trimmed one restricted to
  its range by knot insertion, across the seam of a periodic or closed one),
  SP-curves on a plane (the plane's affine map of their control points), and
  SP-curves along an iso-parameter line of an exactly written surface (lines,
  circles, B-spline iso-curves, a section moved or a profile turned into
  place). A face with no loop (a whole sphere or ring torus) gets exact seam
  edges.
- **Faces round a closed surface cut at their seams** (`split_periodic`, on
  by default, as SOLIDWORKS' own "split periodic faces" option): a face whose
  loops wind round a closed surface (a band of a cylinder, cone, ring torus,
  surface of revolution, extrusion of a closed curve or B-spline surface whose
  first and last rows of control points coincide, between two loops winding
  opposite ways, or a cap of a sphere, a cone or a revolved surface between one
  winding loop and a pole) is written as two faces, each with one outer bound,
  cut along the surface's own iso-parameter curves at u = 0 and u = half a
  period, as SOLIDWORKS cuts them (`docs/FORMAT.md` 10.9), so that a reader
  working in the surface's (u, v) needs no seam of its own. A seam that would
  pass through a hole, cross a loop more than once, pass within a micrometre
  of a vertex without meeting it or be shorter than a micrometre moves to the
  next of 16 evenly spaced pairs of values that does not, and failing those
  into the gaps the holes leave; a face no pair can cut is written whole. So
  is a cap whose loop passes within a micrometre of its pole, or within 15 %
  of the farthest the loop reaches from it: the pole would be a vertex
  of both halves that close to their other edges, and OCCT reads such halves
  badly (`docs/FORMAT.md` 10.9). The edges a seam crosses are cut there (a ring edge's
  vertex, which Parasolid does not have, goes; a piece of a B-spline edge gets
  the curve restricted to its own range), every face using a cut edge takes
  its pieces, and each seam is the surface's own iso-curve between its ends:
  a LINE, a CIRCLE, the profile turned into place, or the B-spline iso-curve.
  Every cut passes the export's own checks again (below), and the halves,
  their outer loops followed round the surface's (u, v), must each enclose an
  area on the side of the loop the face lies on and hold the holes given
  them; a face whose cut would not is written whole. Offset surfaces and
  apple and lemon tori are written whole.
- **Approximated where it cannot, deviation measured.** Intersection curves,
  other SP-curves on curved surfaces, and rolling blends (BLENDED_EDGE,
  for which STEP has no entity) are written as B-splines: curves through
  points refined onto the true geometry (an intersection's onto both
  surfaces at once by Newton's method), C1 cubic between them; a blend as
  exact circular sections between the sphere's feet on its supports, lofted
  cubically along its spine, its faces' boundaries the surface's own
  iso-curves, and its faces' orientation taken from the faces they meet
  tangentially. A blend whose faces go round a closed spine (a ring of blend
  bounded by two ring edges), or leave little of it uncovered, is lofted round
  the whole spine, its last section its first, so the surface closes on itself
  (`u_closed` true) rather than stopping short of its face. Each fit is
  measured against the true geometry (curves at the quarter points of every
  span; blends at seven points along every span, from 0.15 to 0.85 of it,
  each at nine points across, and the surface's two sides against the true
  lines where the sphere touches its supports, which the faces' edges follow)
  and refined until within `fit_tolerance_m` (1e-7 m); one that
  stays above `max_deviation_m` (1e-6 m) is not representable
  (`fit_failed`). The file's uncertainty is the larger of 1e-5 mm (as
  SOLIDWORKS writes it) and 1.5 times the largest deviation or accepted gap
  (below), rounded up to 1, 2 or 5 times a power of ten, so every vertex of
  the file lies on its curves and surfaces, and every edge on its faces,
  within it (tolerant geometry aside, below). `exact_only` refuses
  approximations instead (`approximation_refused`). The warning
  `step_approximated` counts what was approximated and gives the largest
  deviation.
- **Not representable: refused, never silently broken.** Reasons (an open
  set): `foreign_geometry` (PE surfaces and curves), `mesh_geometry`,
  `unsupported_surface`, `unsupported_curve`, `front_face_in_solid`,
  `non_manifold`, `fit_failed`, `orientation_conflict`, `bad_geometry`
  (values out of range: a ring edge on a trimmed curve that does not go round
  it, a trimmed range many periods from its curve's own), `bad_reference`,
  `check_failed`, `approximation_refused`; and `unsupported_body`, a wire
  body, and `hidden`, a body SOLIDWORKS hides, which are left out rather than
  refused. By default a body
  with any of them refuses the whole export:
  `NotRepresentableError` (`not_representable`), nothing written, its
  message naming each body and reason, its `bodies` the `StepBody` records.
  With `allow_partial` those bodies are left out whole (never a solid with a
  face missing): `partial` is true, the warning `step_bodies_left_out` says
  which and why, and the file says so in a second FILE_DESCRIPTION line
  (`incomplete: 1 of 3 bodies left out (fit_failed 1)`). Nothing left raises
  `NothingToExportError`.
- **Checked before writing.** Every body passes the export's own checks
  first: every loop closes, every edge of a closed shell is used exactly
  twice, once each way, every vertex lies on its edges' curves and its faces'
  surfaces as written (from the very numbers written), points sampled
  along each source edge lie on the written curve in order, from the start
  vertex to the end, the way `same_sense` says (which catches the wrong arc
  of a circle), a ring edge's curve begins and ends at its one vertex, and
  points along each edge as written (its samples and points between them,
  seven between each two on an approximated surface) lie on the surface of
  each face it bounds as written, which catches a surface that stops short of
  its face and an edge that leaves its faces between its vertices. The
  allowance is the larger of 2e-8 m (twice Parasolid's resolution), the
  source edge's (and for a vertex, the vertex's) own tolerance and twice an
  approximation's deviation. A vertex or a point of an edge that is off its
  curve or surface by more than that with no tolerance declared, but by no
  more than `max_deviation_m`, is accepted as the source's own gap:
  `max_gap_m` reports the largest and the uncertainty covers it. A body that
  fails is `check_failed`.
- **The file.** Header `FILE_DESCRIPTION(('STEP AP214'),'2;1')`,
  `FILE_NAME` with the file's own name, the time stamp (UTC, ISO 8601; fixed
  by `time_stamp`, as tests do, so a model always gives the same bytes),
  empty author and organisation, `SolidSeas <version>` and the release of
  SOLIDWORKS that saved the document, and `FILE_SCHEMA(('AUTOMOTIVE_DESIGN {
  1 0 10303 214 1 1 1 1 }'))`. The product structure is what SOLIDWORKS
  writes in its own STEP of fixture o02, in AP214 form: one PRODUCT named
  after the document (its file name without the extension, or `name=`),
  PRODUCT_DEFINITION `'UNKNOWN'`, the formation with specified source
  `'ANY'`/`.NOT_KNOWN.`, an ADVANCED_BREP_SHAPE_REPRESENTATION named after
  the document holding the solids and the origin, units millimetre, radian
  and steradian, `'NONE'` labels. Sheets go in a
  MANIFOLD_SURFACE_SHAPE_REPRESENTATION. Numbers have 15 significant digits;
  strings are escaped, other than printable ASCII written as `\X2\` or
  `\X4\`. No colours yet.
- **`StepModel`**: `name`, `doc_type`, `configuration`, `products`
  (`StepProduct`: name, kind, file, configuration, `uncertainty_m`),
  `bodies` (a `StepBody` each: product, name, configuration, kind,
  source, faces, edges and vertices as written, `split_faces` (its source
  faces written as two, cut at their seams) and `edges_added` (the seams and
  the extra pieces of cut edges), approximated faces and edges, by class,
  `max_deviation_m`, `max_tolerance_m`, `written`, `reason`, `message`),
  `counts` (`products`, `instances`, `bodies`, `solids`, `sheets`, `faces`,
  `edges`, `vertices`, `split_faces`, `edges_added`, `entities`,
  `bodies_left_out`), `uncertainty_m`,
  `max_deviation_m`, `max_tolerance_m` (the largest tolerance of a written
  edge or vertex), `max_gap_m`, `approximated`, `exact`, `partial`,
  `originating_system` (the release of SOLIDWORKS that saved the document,
  for the header), `incomplete` (the FILE_DESCRIPTION line of a partial
  export, else None), `instances` and `skipped` (empty for a part: reserved
  for assemblies), `warnings`, `seconds`, `closed` (a property: the file
  holds at least one solid; every solid written passed the closed-shell
  check, so it is false only for a file of sheets), and `face_map`,
  `edge_map` and `edge_pieces` (each written face's and edge's entity id to
  its body and its source FACE node id or EDGE node index, for checking it
  against the source: both halves of a cut face map to its source face,
  `edge_pieces` holds the pieces of cut edges and `edge_map` the edges written
  whole; seams are in neither). `StepResult`: `path`, `format` (`step`),
  `bytes`, `merged` (False), `model`.
- **Warnings** (3.5): `step_approximated`, `step_bodies_left_out`,
  `step_hidden_bodies_unknown` (a part with several solid bodies, some of
  which carry no mark saying whether SOLIDWORKS hides them: all are written,
  and SOLIDWORKS leaves hidden bodies out of its own STEP),
  `step_differs_from_display` (the stored bodies' box is more than 1% of its
  diagonal from the display mesh SOLIDWORKS last drew, for the active
  configuration), `step_tolerant_geometry` (tolerant edges or vertices with
  gaps of 1e-3 mm or more and larger than the file's uncertainty; written as
  Parasolid holds them, reported in `max_tolerance_m` and not folded into the
  uncertainty), and `bodies_left_out` (hidden bodies, sheets not asked for,
  wire bodies).
- **Writing** follows `write_export`'s rules (3.17): the file is created new,
  never through a link, never over a file unless `overwrite`, never a
  SOLIDWORKS file, a device or an alternate data stream, and removed when the
  write fails. The mapping
  is finished before the file is created, so a refusal or a limit never
  leaves a file.
- **Limits.** `max_faces` (the faces the bodies asked for would map, each
  body's counted, and the count stopped as soon as it passes the limit),
  `max_entities` (the DATA
  section), `max_seconds` (the whole mapping, checked by one clock in every
  loop) and `max_bytes` raise `SldLimitError` with `detail.limit`; reading is
  bounded as `parasolid()` bounds it. Each fit is bounded: 4,096 points a
  curve, 1,024 sections a blend, 16 halvings of a span.
- **What it raises**: `NotRepresentableError`, `NothingToExportError` (a
  drawing, a configuration not stored, a part with no body to write),
  `SldLimitError`,
  `ConfigurationNotFoundError`, `InvalidArgumentError`, and
  `OutputRefusedError` from `write_step`.
- **Verified** (`tests/test_step.py`, `tests/test_step_approx.py`), each file
  re-read by a Part 21 reader and checked by a topology and geometry checker
  written for the tests from ISO 10303-21 and -42, sharing no code with the
  writer: o02's STEP has exactly the entities of SOLIDWORKS' own STEP of it
  (`o02_boxA.step`) for every geometric and topological type, the same
  vertices, directed edges, planes, oriented loops, solid name and
  representation name, units and uncertainty, and only the listed AP203
  differences; o03 to o06, o13 and o17 match it the same way, o07 with its
  height 31 mm, o09 (imported from that file) as point sets and planes;
  every fixture part and configuration either converts (with the solids,
  body names, faces, edges and box the fixtures' ground truth lists) and
  passes every check, or is refused with its reason (o01, o06 OracleAlt);
  o11 converts exactly, its hole and the fillet round it cut at their seams:
  14 faces (6 planes, 6 cylinders, 2 tori), 34 edges, 22 vertices, genus 1,
  box 40 x 30 x 10 mm, the very counts and seam lines of SOLIDWORKS' own STEP of
  o11 (whose vertices, edges and faces the export's equal as point sets,
  `docs/FORMAT.md` 10.9), and o10 the same way (8 faces, 18 edges, 12
  vertices); each face round a closed surface of the synthetic bodies (a
  cylinder, a B-spline cylinder, a hemisphere, a cone, a band of a torus) is
  cut in two with one outer bound each, each seam on the arc of its curve that
  crosses the face (its middle point checked, o11's too), the pieces of every
  cut edge cover it once, the file read back by SolidSeas' own STEP reader has
  the shape's true area and volume, every window of a band lies in the half
  it was given, a cap whose rim passes near its pole is written whole, a seam
  that would be shorter than a micrometre moves, and a cut that fails its
  checks, or that was made wrong (a seam the wrong way round its circle, a
  hole given to the other half), leaves its face whole; a part with a
  hidden body writes the others only, `include_hidden` writes all, and one
  that shows only sheets beside a hidden solid asks for sheets, as File >
  Export STEP then writes them; the STEP of
  a part's partition bodies equals
  that of SOLIDWORKS' own .x_b or .x_t of them; every face's normal agrees
  with SolidSeas' tessellation of the source (itself verified against
  SOLIDWORKS' volumes), the lemon and apple tori and spun surfaces included,
  and every curved edge runs on its own arc, and points along every edge lie
  on its faces. A ring of blend round a circular spine closes on itself and
  lies within its reported deviation of the torus it rounds; on a cylinder
  cut by a tilted plane and rounded (an elliptical spine), the reported
  deviation is the true one, measured by the tests' own evaluators (measured
  at the middle of each span alone, it was less than half of it for a cut at
  50 degrees). On a sample of 400
  corpus parts the numbers are those of `docs/FORMAT.md` 10.9, which
  `test_corpus_step` measures again.

### 3.20 Model files: `solidseas.formats` (provisional)

Every 3D file that is not a SOLIDWORKS document goes through one registry and
one document interface, beside `open_document` and `Document`, which do not
change. STL is read today; the mesh formats, Parasolid transmit files, STEP and
Alibre Design arrive with their readers (3.20.5 to 3.20.8), each by its module
appearing: the registry already names them. `docs/formats/` holds what is
known of each format, each claim labelled verified, hypothesis or unknown.

```python
from solidseas.formats import open_model, open_any, detect, Limits

with open_model("D:/Jobs/Example/bracket.stl") as m:     # any readable non-SOLIDWORKS file
    m.format, m.variant, m.doc_type, m.kind, m.units, m.application
    m.fields, m.properties, m.active_configuration, m.counts()
    m.tree()          # ModelTree: components and objects, parents first, with placements
    m.scene()         # Scene: meshes in metres and the items that place them
    m.bodies()        # B-rep bodies as Parasolid transmits (None for a mesh format)
    m.preview()       # the image the file stores, as stored, or None
    m.references()    # the files it names
    m.summary()       # model_summary data (5.16), what the CLI and REST send

with open_any(path, within=folder) as doc:   # a SOLIDWORKS Document or a ModelDocument
    ...
```

#### 3.20.1 Opening, `ModelDocument` and `AnyDocument`

```python
open_model(src, *, name=None, format=None, within=None, max_file_bytes=None,
           refuse_hard_links=False, hold_open=False, limits=None) -> ModelDocument
open_any(src, *, ...the same...) -> Document | ModelDocument
```

- `src` is a path or the bytes of a whole file; `name` the display name and the
  extension hint (default: the path's file name). The file is opened as
  `open_document` opens one (3.1): read-only and share-tolerant, regular files
  only, `within` a folder with no link, junction or placeholder below it,
  `max_file_bytes` checked from `fstat` before any byte is read, `refuse_hard_links`
  on the open handle, and read whole (files up to 512 MiB) unless `hold_open`.
- The format comes from the content and the name (3.20.3); `format` forces a
  reader. `limits` (a `Limits`) overrides any bound of 3.20.2.
- Raises what `open_document` raises, plus `FormatNotSupportedError` for a
  format SolidSeas knows but cannot read (`detail.rule` `no_reader`,
  `detail.value` the format id) or a feature that stops one file (its reader's
  rules, 3.20.5 to 3.20.8). An unidentified file raises `UnknownFormatError`
  with `detail.rule` `unidentified` (its message is unchanged), and a
  SOLIDWORKS document `InvalidArgumentError` (rule `solidworks_document`): open
  it with `open_document` or `open_any`.
- `open_any` sends a file with a SOLIDWORKS extension to `open_document`,
  unchanged. Only when that finds no SOLIDWORKS container and the content is a
  format SolidSeas reads is the file read as that format, warned
  `extension_mismatch`; otherwise `open_document`'s `UnknownFormatError` stands.
  Any other file goes to `open_model`, and to `open_document` when its content
  is a SOLIDWORKS container.
- Content and extension that disagree: the content wins, with the warning
  `extension_mismatch`.
- **The files a document names are opened under its rules.** A glTF buffer, an
  OBJ material library and an Alibre component are opened read-only `within`
  the document's folder (no link, junction or placeholder on the way), with the
  `refuse_hard_links` and `max_file_bytes` the document was opened with: a
  buffer or library with a second name raises `LinkRefusedError` (rule
  `hard_link`, the library warned `material_library_unread`), and an Alibre
  component with one is no candidate (`component_not_found`), as is one larger
  than `max_file_bytes`. The REST service opens every document with
  `refuse_hard_links`, so it never reads a file outside a root through a hard
  link a document names.

| Member | Type | Notes |
|---|---|---|
| `path`, `name`, `file_info` | as `Document` | `FileInfo` from `fstat`; None for bytes |
| `format`, `format_name`, `variant` | `str`, `str`, `str` or None | the registry id and name, and the format's variant (`binary` or `ascii` for STL) |
| `doc_type` | `part`, `assembly` or None | from the file's structure: an assembly when it has product structure (components, instances, several placed documents); otherwise a part, however many objects it holds |
| `kind` | `mesh`, `brep` or `mixed` | what this document holds |
| `units` | dict | `length` (`mm`, `cm`, `m`, `in`, `ft`, `micron` or None), `scale_m` (metres per unit) and `source`: `file` (the file states it), `format` (the format fixes it) or `assumed` (warning `units_assumed`) |
| `application` | dict | `name` and `version` of the program that wrote the file, when the file says |
| `fields`, `properties` | `SummaryFields`, list of `Property` | as `Document`'s; every property has `scope` `file` |
| `configurations`, `active_configuration` | `[]`, str or None | a model file keeps no configurations; an Alibre Design file names its active one |
| `counts()` | dict | what the head tells of the model's size: `objects`, `items`, `bodies`, `faces`, `triangles`, `vertices`, `components`, `references`, `model_parts`; None where that needs a full read |
| `tree(*, max_nodes=10_000, max_depth=32)` | `ModelTree` | `nodes` (`ModelNode`: `id`, `parent`, `name`, `kind` `assembly`, `component`, `object` or `body`, `object` (its scene object), `file` (a reference key), `placement` relative to the parent, as the file stores it, `color` RGBA 0 to 1), parents before children; `truncated` when `max_nodes`, `max_depth`, `limits.tree_nodes` or `limits.depth` cut it. In JSON a placement that is not finite is null, warned `value_not_representable` (stream `tree`) |
| `scene(...)` | `Scene` | 3.20.4 |
| `bodies(*, max_seconds=30.0)` | list of `BodyRef` or None | `name`, `transmit` (an in-memory Parasolid `XtTransmit`), `color`, `node`, `body_type`; None for a format with no B-rep |
| `preview(prefer="png")` | `Preview` or None | the image the file stores, as stored (a bitmap stays a bitmap); `stream` names the package part or stream |
| `references()` | list of `ExternalReference` | `key`, `kind` (`component`, `buffer`, `material_library`), `stored` (the text the file stores, which can be a path from another machine), `name` and `resolution` (`status`, `path`, `found_by`, `version`) when it was looked for; `path` is relative to the document's folder (`/`-separated), absolute only for an Alibre component found under one of `scene(roots=...)` |
| `refuse_hard_links`, `max_file_bytes` | `bool`, int or None | those it was opened with, which the files it names are opened under |
| `warnings` | list of `ReaderWarning` | coded (3.5) |
| `summary(include=("properties", "tree"))` | dict | `model_summary` data; `include` takes `properties`, `tree` and `references` |
| `close()`, `with` | | closes a held handle |

`AnyDocument` is a `typing.Protocol` of what both classes offer: `path`,
`name`, `file_info`, `doc_type`, `fields`, `properties`, `warnings`,
`preview()`, `summary()`, `close()` and the context manager. `is_model(doc)`
tells them apart.

Where a stored image leaves SolidSeas for a listing, the service or the viewer,
it is a PNG SolidSeas wrote itself (`solidseas.formats._source.preview_png`):
a stored PNG has every chunk's length and checksum checked, its size within
`image_side`, its bit depth and colour type valid, and its pixel data inflated
to exactly the size its header implies, and is written again with only its
header, palette, transparency and pixels; a stored bitmap (`BM`, a 40-byte or
larger header, 24 or 32 bits, uncompressed, every offset inside the data) is
converted to PNG; any other image type is not passed on.

#### 3.20.2 Limits

`solidseas.formats.Limits` is one frozen dataclass of every bound a reader
keeps, with these defaults; `Limits().replace(name=value)` makes a variant.
Reaching a bound raises `SldLimitError` (`limit_exceeded`) with
`detail.limit` the field's name, unless the table says the result is cut
short. Every reader loop ticks a clock at least every 4,096 steps, so the time
bounds and `scene(cancelled=...)` are honoured; in a worker, the worker's
deadline is the hard stop.

| Field | Default | Bounds |
|---|---|---|
| `file_bytes` | None | the file, from `fstat` (`file_too_large`); the smaller of it and `max_file_bytes` |
| `whole_read_bytes` | 512 MiB | files read whole; larger ones through the held handle |
| `seconds` | 30 | each `tree`, `bodies` or `references` call (`scene` has its own `max_seconds`) |
| `triangles` | 20,000,000 | triangles read or tessellated in one document (the export's default) |
| `vertices` | 60,000,000 | vertices read in one document |
| `objects`, `items` | 100,000, 1,000,000 | mesh objects and placed items in one scene |
| `tree_nodes`, `depth` | 10,000, 32 | `tree()` nodes (then `truncated`), and the depth of trees, node hierarchies, sub-assemblies and references |
| `components` | 10,000 | component documents one scene opens |
| `text_bytes` | 64 KiB | one name, property or metadata value (then cut, `text_truncated`) |
| `properties`, `references` | 10,000 each | properties and external references of one document |
| `colors_per_object` | 256 | colour splits of one object (then merged, `colors_ignored`) |
| `siblings`, `sibling_bytes` | 1,000, 512 MiB | files beside the document that it names and that are read, and each one's size |
| `zip_members`, `zip_directory_bytes` | 10,000, 64 MiB | a zip's members and central directory, from its end records before the directory is read |
| `zip_member_bytes`, `zip_total_bytes`, `zip_ratio` | 1 GiB, 2 GiB, 200 | one member inflated, every member one document inflates, and inflated to stored size once a member passes 1 MiB, each counted as it inflates |
| `xml_depth`, `xml_attribute_bytes`, `xml_text_bytes` | 64, 64 KiB, 64 KiB | element nesting (`damaged_file`), one attribute value, one element's text |
| `json_bytes`, `json_depth` | 64 MiB, 64 | one JSON document and its nesting (`damaged_file`) |
| `image_side`, `image_bytes`, `png_chunks` | 4,096, 64 MiB, 10,000 | a stored or converted image's width and height, its bytes and inflated pixels, and a PNG's chunks (the image is refused, `preview_undecodable`) |
| `render_triangles`, `render_side`, `render_seconds` | 500,000, 4,096, 5 | 3.21 |
| `thumbnail_brep_seconds`, `thumbnail_cache_bytes` | 15, 256 MB | 3.21 |
| `stl_line_bytes`, `stl_name_bytes` | 4 KiB, 256 | one ASCII STL line and a solid's name |

The formats to come have their own fields, there from the start so a reader
never changes this table's module: `threemf_model_parts` (10,000),
`threemf_components` (1,000,000), `threemf_component_depth` (16),
`threemf_color_groups` (65,536), `threemf_metadata` (1,000),
`obj_line_bytes` (1 MiB), `polygon_corners` (1,024), `obj_materials` (10,000),
`obj_material_libraries` (16), `ply_header_bytes` (64 KiB), `ply_elements`
(32), `ply_properties` (64), `gltf_buffers` (1,000), `gltf_data_uri_bytes`
(256 MiB), `gltf_array_items` (100,000), `amf_constellation_depth` (16),
`xt_transmit_bytes` (64 MiB), `xt_nodes` (20,000,000), `xt_header_bytes`
(64 KiB), `p21_header_bytes` (1 MiB), `p21_record_bytes` (16 MiB),
`p21_records` (20,000,000), `p21_list_items` (10,000,000), `p21_list_depth`
(32), `p21_string_bytes` (1 MiB), `p21_complex_parts` (64), `brep_nodes`
(20,000,000), `bspline_knots` (100,000), `step_products` (100,000),
`step_occurrences` (1,000,000), `step_styled_items` (10,000,000),
`ole_streams` (256), `alibre_small_stream_bytes` (64 KiB),
`alibre_constituents_bytes` (1 MiB), `alibre_stream_bytes` (512 MiB),
`alibre_text_stream_bytes` (64 MiB), `prop_entries` (10,000), `prop_values`
(10,000), `mesh_dictionary_entries` (1,000), `mesh_key_bytes` (256),
`mesh_blocks` (10,000,000), `inclusions` (100,000), `resolve_depth` (8),
`resolve_examined` (50,000), `resolve_candidates` (5,000), `resolve_seconds`
(10), `sab_records` (20,000,000), `sab_subtype_depth` (64), `sab_subtypes`
(10,000,000), `sab_string_bytes` (64 KiB) and `sab_values` (20,000,000: the
values of one SAB stream, a position or vector counting three, about 40 bytes
of memory each). Lengths read from a file are
also always checked against the bytes that remain before anything is
allocated.

#### 3.20.3 The registry and detection

`solidseas.formats.registry.FORMATS` holds one `FormatSpec` per format: `id`
(an open set), `name`, `extensions`, `family` (`solidworks`, `mesh`,
`exchange`, `native`), `kind`, `capabilities` (`metadata`, `mesh`, `brep`,
`components`, `properties`, `stored_preview`, `units`, `colors`,
`external_references`), `reader` (the dotted path of the function that opens
a document, or None for a format that is listed and never read), `up_axis`
(`z` or `y`: the Home view of 3.21), `mime`, and for an extension other
programs share, `needs_signature` and `signature`.

| id | Extensions | Read | Up |
|---|---|---|---|
| `solidworks` | `.sldprt`, `.sldasm`, `.slddrw` | `open_document` | y |
| `stl` | `.stl` | yes | z |
| `3mf`, `obj`, `ply`, `off`, `gltf`, `amf` | `.3mf`, `.obj`, `.ply`, `.off`, `.gltf` and `.glb`, `.amf` | with their reader (3.20.5) | z |
| `parasolid` | `.x_t`, `.x_b`, `.xmt_txt`, `.xmt_bin` | with its reader (3.20.6) | y |
| `step` | `.step`, `.stp`, `.p21` | with its reader (3.20.7) | y |
| `alibre`, `acis` | `.ad_prt`, `.ad_asm`, `.ad_smp`; `.sab`, `.sat` | with their reader (3.20.8) | y |
| `iges`, `alibre_drawing`, `alibre_package`, `3dxml`, `fusion`, `inventor`, `solid_edge`, `nx`, `edrawings`, `vrml` | their extensions | never: listed as `unsupported` | |

`readable(id)` says whether a format's reader module is installed, without
importing it; `by_extension(name)`, `extensions(formats)` and
`select(formats)` (`"all"`, an id, comma-separated ids or a list) do what
their names say.

`detect(src, name=None, *, within=None)` reads at most the first 4 KiB and the
size and answers a `Detection`: `format` (None when nothing fits), `variant`,
`by` (`content`, `extension`, `both`, or `forced` when the caller named the
format) and `mismatch`. When the extension names a format whose content test
accepts the head, that format wins (`both`). Otherwise the content tests run in
this order, and the first that accepts wins (`content`; `mismatch` when the
extension named another format): a compound file or the SOLIDWORKS 2015+
container (the extension then chooses among SOLIDWORKS, Alibre Design,
Inventor, Solid Edge and eDrawings); a zip package (3MF by its first member
`[Content_Types].xml`, `_rels/.rels` or one under `3D/`, AMF by a `.amf`
member, Fusion and 3D XML by extension); GLB (`glTF`, version 2); STEP
(`ISO-10303-21;` after an optional byte order mark and white space); Parasolid
(the common header, a text transmit's `T<n> : TRANSMIT FILE` or a binary's
`PS`); ACIS SAB (`ACIS BinaryFile`, `ASM BinaryFile`); IGES (an 80-column first
line with `S` in column 73); PLY (`ply` and a line end); OFF (`OFF`, `COFF`,
`NOFF`, `CNOFF`, `STOFF` first); glTF JSON (`{` and `"asset"`); OBJ (with
`.obj` only); and STL, binary when the size is exactly 84 + 50 n for the count
`n` at bytes 80 to 83, whatever the header says, else ASCII when the text
starts with `solid`. Otherwise the extension decides (`extension`), and that
format's reader refuses content that is not its own.

#### 3.20.4 Scenes, and the contract a reader keeps

```python
scene(*, prefer="bodies", max_triangles=None, chord_m=None, chord_fraction=None,
      max_chord_m=None, angle_deg=15.0, max_seconds=30.0, body_types=("solid", "sheet"),
      roots=None, cancelled=None) -> Scene
```

A `Scene` is the one hand-off of geometry: the export (3.17), the renderer
(3.21) and the viewer's 3D view start from it.

- `objects`: `MeshObject`s, one mesh in its own frame each: `positions`
  (float64 x, y, z in metres), `triangles` (uint32 index triples), `normals`
  (float32 per vertex, when the file gives them), `color` (RGBA 0 to 1),
  `source` (`mesh` for a mesh file's own triangles, `bodies` for a tessellated
  B-rep, `display_mesh` for a display tessellation the file stores), `node` (its
  tree node) and `warnings`.
- `items`: `SceneItem(object, instance, placement)`, `placement` a `Placement`
  (3.8) from the object's frame to the model's. A placement that is not
  finite, or more than 1,000 km out, is skipped; one that scales, shears or
  mirrors is kept and warned `non_rigid_transform`.
- `counts` (`objects`, `items`, `vertices`, `triangles` placed, `bodies`,
  `faces`, `faces_done`, `components`), `truncated` (`max_triangles` when the
  call's cap stopped the read: what was finished is kept), `skipped`
  (`SkippedItem(instance, reason, message)`, and a tessellation's
  `SkippedFace`s) and `warnings`.
- `prefer` is `bodies` (the export: a B-rep tessellated, a stored display mesh
  only as the fallback) or `display` (the 3D view and thumbnails: a stored
  display mesh first). `chord_m`, `chord_fraction`, `max_chord_m`, `angle_deg`
  and `body_types` are the tessellation's options (3.15) for B-rep formats.
  `max_triangles` cuts the read short; `limits.triangles` raises instead.
  `cancelled` (a callable) stops the read with `interrupted`; `roots` are
  further folders where an assembly's component files may be found. One
  scene is cached per document, for the last options asked.

**Writing a reader.** A reader is a module whose
`open(source, *, name, path, file_info, limits, hold_open, detection)` returns
an instance of a `ModelDocument` subclass; the registry's `reader` already
names it. The subclass sets `format` (the registry id) as a class attribute,
fills the head attributes in its constructor from the file's head alone (so a
listing stays cheap), and implements the hooks `_tree(clock)` and
`_scene(scene_builder)`, and as they apply `_bodies(clock)`, `_preview()`,
`_references(clock)` and `_counts()`. The base class checks every argument,
keeps the clock and the cancellation, caches, builds the summary and keeps the
bounds of 3.20.2. Every mesh is built through `scene_builder.mesh(name=,
source=, scale_m=, color=, node=)`, a `MeshBuilder`: `add_vertices`,
`add_triangles` (indexed) or `add_soup` (three new vertices a triangle), then
`finish()`. It drops triangles naming a vertex the mesh lacks
(`indices_out_of_range`), those with a repeated or non-finite corner
(`degenerate_triangles_dropped`) and those with a corner more than 1,000 km
from the object's origin once scaled to metres (`coordinates_out_of_range`: no
part lies there, and no later sum or square of such a number overflows),
counts triangles and vertices against the bounds, and scales to metres. `scene_builder.add_item`, `skip`,
`missing_component` (warning `component_not_found`) and `warn` do the rest.
Bytes come through `solidseas.formats._source`: `Source` (bounded positioned
reads), `SafeZip` (members, directory, inflated sizes and ratio bounded;
encrypted members and unknown methods refused) with `opc_resolve` (a package
relationship's target, refused when it climbs out), `xml_events` and
`xml_tree` (expat, no DOCTYPE, entity or external entity; an encoding Python
lacks is `SldFormatError`), `load_json` (strict, bounded), `read_sibling` (a
file the document names, only from inside its own folder, never through a
link, under the document's `refuse_hard_links` and `max_file_bytes` through
`SiblingBudget.of(source, limits)`, counted), `sibling_resolution` (where such
a file is, without opening it: each folder on the way read with `lstat`, a
link, junction, placeholder or refused hard link `refused`, the path relative
to the document's folder), `sanitize_png`, `bmp_to_png`, `encode_png` and
`clip_text`. A zip directory asking for a zip version Python lacks is
`SldFormatError`; a member using a feature it declines (strong encryption) is
`FormatNotSupportedError` rule `encrypted`. A hook raises only `SldFormatError`,
`SldLimitError`, `FormatNotSupportedError` or the I/O errors `open_document`
documents; what a crafted file provokes besides (`ValueError`, `IndexError`,
`struct.error`, `RecursionError`...) becomes `SldFormatError` at the boundary.

**STL** is the reference reader (`docs/formats/stl.md`): binary and ASCII, the
binary size rule first, millimetres assumed (`units_assumed`), one object per
ASCII solid, triangles as a soup the export welds, the header as the property
`header` (an ASCII file's first solid name as `solid`), colours in the
attribute bits or a `COLOR=` header warned `colors_ignored`, and no stored
preview.

#### 3.20.5 Mesh formats: 3MF, OBJ, PLY, OFF, glTF and AMF

Each has a reader (`solidseas.formats.threemf`, `obj`, `ply`, `off`, `gltf`,
`amf`), opened by `open_model` and `open_any` like STL; `docs/formats/mesh.md`
holds what each reads, labelled verified, hypothesis or unknown. Every file
lists, previews (its stored image, else one rendered from its triangles), shows
in 3D, exports to STL and 3MF and goes through 3D Print.

| id | `variant` | `doc_type` assembly when | `units.source` | Stored preview | Colours |
|---|---|---|---|---|---|
| `3mf` | `core`, `production` | the build has several items, or a component object several components (None from a head that cannot tell, until a full read) | `file`, else `format` (mm) | the package thumbnail, else `Metadata/thumbnail.png`, else the first plate image (PNG) | base materials and colour groups, by triangle (`p1`, else the object's `pid` and `pindex`) |
| `obj` | None | never | `assumed` (mm) | none | MTL `Kd` (and `d`), by face |
| `ply` | `ascii`, `binary_le`, `binary_be` | never | `assumed` (mm) | none | face, else first corner's vertex colour |
| `off` | the keyword (`OFF`, `COFF`, `NOFF`, `CNOFF`, `STOFF`...; `OFF` when the file has none) | never | `assumed` (mm) | none | face, else first corner's vertex colour |
| `gltf` | `gltf`, `glb` | the scene places more than one mesh | `format` (m) | none | the material's `baseColorFactor`, by primitive |
| `amf` | `plain`, `zip` | it has constellations (None from a head that cannot tell, until a full read) | `file`, else `format` (mm) | none | triangle, else first corner's vertex, else volume, else object, else material |

- **Objects.** One scene object a colour of each mesh object (an OBJ group, a
  3MF mesh object, a glTF primitive, an AMF object, the whole of a PLY or OFF),
  `source` `mesh`, at most `colors_per_object` colours each (then one, in the
  colour most of its triangles have, warned `colors_ignored`). Faces of more than
  three corners are cut by ear clipping on their best-fit plane, a convex one as
  a fan. Normals are kept from PLY, OFF and glTF.
- **Placements and the tree.** 3MF build items and components, glTF nodes and AMF
  constellations become items with their placements composed, and the tree's
  nodes (an `assembly` node first for an assembly; `component` nodes for
  component objects, nodes without a mesh and constellations; `object` nodes
  for meshes, `object` the first of their scene objects). glTF's Y-up scene is
  turned Z up at its root (+90 degrees about X), as part of every placement.
  `tree()` costs a full read, as `scene()` does, and stops making nodes past
  `limits.tree_nodes`. Every placement 3MF components and AMF constellations
  expand to counts against `limits.items` and the time bound.
- **`max_triangles`.** A scene it cuts keeps the objects finished before the cut,
  placed as the file places them (3.20.4); the object being read is dropped, so
  the kept objects hold at most `max_triangles`. A 3MF's build and an AMF's
  constellations are still read for the placements; an OBJ keeps the groups it
  had left; a PLY or OFF, one object, keeps nothing, as a binary STL does.
- **Head.** Read from the file's head alone, so a listing stays cheap. 3MF:
  unit, required and recommended extensions, the root model's metadata
  (`Title`, `Designer`, `Description`, `CreationDate`, `ModificationDate`,
  `Application` into the fields and `application`; every unprefixed name a
  property) and `counts.model_parts`, and from a scan of the tags in the root
  model's first 64 KiB `doc_type`, `counts.objects` and `counts.items`: settled
  when the whole model is in those 64 KiB, else an assembly when they show one
  and otherwise None until `tree()` or `scene()` reads the model and settles
  them. glTF: the generator, copyright and `asset.extras` values, and every
  count from the JSON. PLY: the header (`comment` and `obj_info` properties,
  `counts.vertices`). OFF: the keyword and counts. AMF: unit, the metadata
  before the first object, and `doc_type` when the first 64 KiB settle it (a
  constellation in them, or the whole file in them without one), else None
  until a full read. OBJ: the comments it starts with.
- **Files beside the document.** An OBJ's material libraries and a glTF's buffer
  files are read only from inside the document's folder (`read_sibling`: no
  `..`, absolute path, drive, UNC path, scheme, alternate stream, device or
  link); a 3MF's parts only from inside its package. `references()` lists the
  libraries (`kind` `material_library`) and buffer files (`buffer`) with
  `resolution.status` `found`, `not_found` or `refused`, without opening them. A
  refused buffer URI raises `path_refused` when the scene is read; an unread
  library is warned `material_library_unread`.
- **Warnings** (codes): `part_reference_refused` (a non-root 3MF part names
  another part), `slicer_data_ignored` (a slicer's own settings and plates in a
  3MF), `extension_ignored` (a 3MF recommends, or a glTF uses, an extension that
  is not read), `compression_not_supported` (glTF primitives held only in Draco
  or meshopt form, left out), `primitives_skipped` (points, lines, free-form
  geometry, a PLY of points only), `textures_ignored`,
  `curved_triangles_flattened` (AMF), `material_library_unread` (OBJ); and the
  core's `units_assumed`, `colors_ignored`, `degenerate_triangles_dropped`,
  `indices_out_of_range`, `text_truncated`, `component_not_found` and
  `non_rigid_transform`. A 3MF item placing an object of type `other` is skipped
  with reason `other_object`.
- **Refusals** (`FormatNotSupportedError`, `format_not_supported`):
  `required_extension` (a 3MF requires an extension other than production,
  materials and triangle sets, or a glTF one the reader does not know;
  `detail.value` the namespace or name), `compression` (a glTF requires Draco or
  meshopt compression, or a zip member uses a method other than store and
  deflate), `binary_off`, `unsupported_variant` (`4OFF`, `nOFF`), `encrypted` (an
  encrypted zip member, or one in a zip form Python does not read). Damage is
  `damaged_file`: a package without a 3D model relationship, a part name or a
  relationship target that climbs out of the package, a component cycle, a glTF
  node cycle or node with two parents, an accessor past its buffer, counts the
  file cannot hold, a DOCTYPE or entity.
- **Bounds** (3.20.2): `threemf_model_parts`, `threemf_components`,
  `threemf_component_depth`, `threemf_color_groups` (groups refused past it,
  entries past it kept without colour), `threemf_metadata`, `obj_line_bytes`
  (also ASCII PLY and OFF lines and MTL lines), `polygon_corners`,
  `obj_materials`, `obj_material_libraries`, `ply_header_bytes`,
  `ply_elements`, `ply_properties`, `gltf_buffers`, `gltf_data_uri_bytes`,
  `gltf_array_items`, `amf_constellation_depth`; and the zip, XML, JSON,
  sibling, image, `triangles`, `vertices`, `objects`, `items` and `depth`
  bounds of the core. `zip_ratio` also bounds a glTF accessor without a buffer
  view, which is zeros: it may hold at most that many times the bytes of its
  sparse block, past 1 MiB, and a primitive whose positions or indices are such
  an accessor without a sparse block is left out (`primitives_skipped`).
  `polygon_corners` bounds an OBJ, PLY or OFF face; a PLY `tristrips` list is
  bounded by the bytes left and its triangles by `triangles`.

#### 3.20.6 Parasolid transmit files

`.x_t`, `.x_b`, `.xmt_txt` and `.xmt_bin` files (registry id `parasolid`) are
read by `solidseas.formats.xt` (provisional; `docs/formats/parasolid.md` has the
format and the evidence): the optional common header, then one transmit in text
or neutral binary, read with the transmit reader behind `parasolid()` (3.2,
`docs/FORMAT.md` section 10) and drawn with the tessellator of 3.15.

- **Head** (what a listing reads): the common header and the transmit's own
  header, nothing else. Every header keyword is a file property, in order, then
  `modeller_version` (a number); `APPL` is the `application` (name and version
  split at its last space when the last word starts with a digit), `USER` the
  `fields.last_saved_by`. `DATE` stays a property: it is local time with no
  zone, so `fields.last_saved_utc` is null. `variant` is `text` or `binary`,
  units metres (`source` `format`), `kind` `brep`. `doc_type` is `assembly`
  when the transmit's root is an ASSEMBLY (SOLIDWORKS writes a multi-body part
  that way), else `part` (a BODY, or a partition's WORLD). Head counts:
  `bodies` 1 for a BODY root.
- **Tree**: a node per top-level part (`1`, or `1`, `2`... for a partition's
  parts), a `component` node per instance path (`1.1`, `1.3.2`...), depth
  first, with its placement relative to its parent; bodies carry their scene
  object and colour. The paths are walked as the tree needs them, never stored:
  `tree_nodes` and nesting past `depth` cut the tree short (`truncated`).
- **Scene**: every body reached is one object (node order), tessellated once at
  the call's options and placed by every instance path that reaches it, `source`
  `bodies`. `prefer="bodies"` welds each body's triangles over shared vertices;
  `prefer="display"` keeps each face's vertices with its surface normals. A
  TRANSFORM acts as `x' = (R x + t) s`, R its nine numbers row by row. Items
  come in tree order. Instances that cannot be placed are skipped:
  `bad_reference`, `negative_instance`, `non_finite_placement` and
  `degenerate_placement` (a transform that flattens what it places to a plane,
  a line or a point). Before placing any, a scene counts the items it would
  place and the instances it would leave out, assembly by assembly, and either
  past `items`, or nesting past `depth`, raises `limit_exceeded` (`items`,
  `depth`) at once. When the tessellator's time runs out, or it reaches
  its face bound, a `bodies` scene raises `limit_exceeded` (`detail.limit`
  `seconds` or `max_faces`), while a `display` scene keeps the faces done and
  names the bound in `truncated` (`max_seconds`, `max_faces`), so a rendered
  preview of it is partial. Rolling blends are the exception (3.15): the
  tessellator does them after every other face and leaves out those the time
  runs out on (`max_seconds` in `skipped`). A `bodies` scene has their pass end
  a tenth of its time (at most 2 s) before its deadline (`blend_reserve_s`) and
  keeps them out as faces it could not draw (a 3D print is made with a hole
  there, as for a SOLIDWORKS part), and a `display` scene names `max_seconds` in
  `truncated` for them too. A body of a type not in `body_types` keeps an empty
  object (`bodies_left_out`).
- **Bodies**: `bodies()` gives one `BodyRef` per body, its `transmit` a part
  transmit of that body alone (the file's own transmit for a part; an assembly's
  or a partition's bodies copied out by
  `solidseas.formats.xt.extract_body(xt, body, clock=None, *, max_nodes=None)`
  under the call's clock), with its name, colour, type and first tree node.
  Copies holding more than twice the transmit's nodes and 100,000 more in all
  (or `xt_nodes`) raise `limit_exceeded` (`xt_nodes`).
- **Names and colours** come from the system attributes `SDL/TYSA_NAME` and
  `SDL/TYSA_COLOUR` and, for bodies SOLIDWORKS wrote, `SWIMPLICITBODYNAME_ID_U`.
  Each face shows its own colour, else its body's; a body is drawn in the colour
  most of its faces show (none when most show none), and `colors_ignored` says
  when its faces do not all show one.
- **Refused** with `format_not_supported`: `detail.rule` `schema_not_embedded`
  (no schema embedded over the base SCH_13006), `bare_binary`, `user_fields`
  (`USFLD_SIZE` not 0) and `unsupported_variant` (`detail.value` `deltas`), each
  with `detail.value` `parasolid` unless said. Damaged content is
  `damaged_file`.
- **Warnings**: `header_unreadable` (a header record that is not
  `keyword=value`), `layout_inferred` (a node type whose layout was inferred
  from files, `docs/FORMAT.md` 10.3), `trailing_data` (bytes after the
  transmit's end, a text transmit's next lines included); and the shared
  `colors_ignored`, `text_truncated`, `non_rigid_transform`, `bodies_left_out`
  and `extension_mismatch`.
- **Bounds**: `xt_header_bytes` (64 KiB), `xt_transmit_bytes` (64 MiB, the
  command line's `--max-mb`; the head is still read, the tree, scene and bodies
  refuse), `xt_nodes` (20 million), `depth`, `items`, `tree_nodes`, `triangles`,
  `text_bytes`, `properties` and the call's `max_seconds`, which the parse keeps
  too (text parses at about 3 MB/s and binary at about 3.5 MB/s, less for
  minimal nodes, so a transmit near the byte bound can need more than 30 s). A
  transmit is parsed once and kept, even when the call ran out of time just
  after; once a parse has run out of time, a later read with no larger time
  bound is refused at once with the same error.
- `solidseas.formats.xt` also has `ParasolidDocument` (whose
  `transmit(clock=None)` is the parsed transmit, read once), `parse_header(raw)`
  (the keywords of a common header) and `peek_transmit(data)` (a transmit's own
  header and root type from its first bytes), all provisional. The transmit
  parsers `parse_text` and `parse_binary` of
  `solidseas.formats.solidworks.parasolid` take an optional `tick`, called once
  a node, which may raise to stop the parse.

#### 3.20.7 STEP

`solidseas.formats.step` reads ISO 10303-21 files of AP203, AP214 and AP242
(`.step`, `.stp`, `.p21`), and a zip archive (ISO 10303-21's compressed form)
that holds one such file. `docs/formats/step.md` has the entities read, the
rules and the corpus measurements.

- **Head.** The header section and one pass of entity names over the data
  section: `variant` from `FILE_SCHEMA` (`AP203` for `CONFIG_CONTROL_DESIGN`
  and AP203's second edition, `AP214` for `AUTOMOTIVE_DESIGN`, `AP242` for
  `AP242_MANAGED_MODEL_BASED_3D_ENGINEERING`, any version suffix, else
  `other`), `doc_type` (`assembly` when the file has a
  `NEXT_ASSEMBLY_USAGE_OCCURRENCE`), `kind` (`brep`, `mesh` for faceted or
  AP242 tessellated geometry, `mixed` for both), the length unit, `fields`
  (`author` from `FILE_NAME`'s authors, `last_saved_utc` from its time stamp,
  naive as stored when it has no zone), `application.name` from its originating
  system, header properties (`file_name`, `time_stamp`, `description`,
  `implementation_level`, `organization`, `preprocessor_version`,
  `originating_system`, `authorization`, `schema`; `container` `zip` for an
  archive) and the counts `bodies`, `faces`, `components` and `references`.
  Nothing is indexed. A schema list naming `ALIBRE_SCHEMA` (Alibre Design's
  design history in Part 21) is refused, `FormatNotSupportedError` rule
  `private_schema`.
- **Full read** (`tree`, `scene`, `bodies`, `references`): the file is indexed
  once (each instance's id, span and entity names; parameters parsed when read),
  its product structure built and its objects planned. Then `units` come from
  the root product's representation context, `doc_type` from the placed
  occurrences, `fields.title` from the root product's name, and the properties
  gain `product_id`, `product_name`, `product_description` and the root
  product's user-defined properties (`DESCRIPTIVE_REPRESENTATION_ITEM`,
  `MEASURE_REPRESENTATION_ITEM`, `VALUE_REPRESENTATION_ITEM`).
- **Tree.** The root product (`assembly`, or `object` for a part), one
  `component` node for each assembly occurrence (named by the occurrence's
  name, else the child product's name or id, else the occurrence's id) with its
  placement in its parent, and one `body` node for each solid, surface-model
  shell, faceted B-rep and tessellated item, with its scene object, its
  placement in its product and its colour. A product placed twice shares its
  objects. The tree holds its first `tree_nodes` nodes and is then truncated;
  the occurrence paths past them are counted (`counts()` `items` and
  `components`) but not kept.
- **Scene.** One object per body: B-rep solids and sheets are built as
  Parasolid bodies in memory and tessellated by `solidseas.tessellate`
  (`source` `bodies`), at one chord tolerance for the whole model (`chord_m`, or
  `chord_fraction` of the model's box diagonal, at most `max_chord_m`); faceted
  and tessellated items are meshes as stored (`source` `mesh`). Faces left out
  are `SkippedFace`s in `skipped`, with the tessellator's reasons
  (`unsupported_surface`, `unsupported_curve`, `bad_geometry`, `non_finite`,
  `bad_reference`, `degenerate`...) and the STEP entity that stopped them. One
  item per occurrence path. `body_types` leaves sheets out (warning
  `bodies_left_out`); when `max_seconds` runs out while bodies are mapped or
  tessellated, the bodies not done are skipped items (reason `max_seconds`) and
  the scene is warned `faces_left_out`. A solid whose faces' triangles run
  against their neighbours' (a face's holes stored running the way of its outer
  bound, the faces lining them agreeing with that, or a face whose loops all
  ran against it and whose sense, kept, was the wrong one) has the faces covering the
  smaller part of the area turned round to agree, and the scene is warned
  `faces_reoriented`. In a solid with faces whose loops ran against them, faces
  whose points only lie at the same place (a file whose faces share no edge,
  each with its own) are neighbours too: a face thinner than the chord
  tolerance, which follows its loop whichever way the loop runs, is turned
  there to agree with the rest. Then each closed shell of a solid is turned to face the
  way the file's solid says, by its signed volume: the outer shell positive and
  each void of a `BREP_WITH_VOIDS` negative (`void_reoriented`, or
  `solid_reoriented` for an outer shell that faced in). A void is an
  `ORIENTED_CLOSED_SHELL` marked `.F.`, which ISO 10303-42 reads as its closed
  shell turned round; some writers' closed shells already face into the void,
  and read by the letter those voids came out inside out, their volume added.
  `bodies()` keeps the file's orientation. The tessellator's self-checks (3.15)
  are summed over the bodies drawn, judged after these repairs, and warned on
  the scene by their codes (`loops_reversed`, `faces_folded`, `faces_coarse`,
  `solids_not_closed`, `shells_inside_out`). `counts` gives `bodies`, `faces`,
  `faces_done` and `components`.
- **Bodies.** `bodies()` gives one `BodyRef` per B-rep body, its transmit built
  in memory (SCH_13006 base nodes; not loaded in a Parasolid kernel), its
  name, colour, tree node and type (`solid` or `sheet`).
- **References.** One `ExternalReference` (`kind` `component`) per
  `DOCUMENT_FILE`, its stored name as `stored`; never opened or resolved.
- **Colours.** A body's colour is its own style's (`STYLED_ITEM`,
  `OVER_RIDING_STYLED_ITEM`), else its shell's or surface model's, else the most
  common of its faces' (warning `colors_ignored` when its faces have several);
  RGB from `COLOUR_RGB` or a `DRAUGHTING_PRE_DEFINED_COLOUR`, alpha from a
  rendering's transparency.

Warnings of its own: `representation_skipped` (a representation holds items
that are not drawn, such as wireframe, or items whose records cannot be
parsed), `placement_unresolved` (an assembly occurrence has no usable placement
and is placed at the origin), `placement_ambiguous` (a mapped item places a
component whose occurrences already have placements of their own, somewhere
else; it is kept as a further occurrence), `assembly_cycle` (a product or a
representation leads back to itself and is not followed again) and, on a
scene, `faces_reoriented`, `void_reoriented` (void shells faced out of their
voids and were turned round) and `solid_reoriented` (solids whose outer shell
faced in were turned round), besides the self-checks' codes. It also gives
`units_assumed`, `colors_ignored`,
`text_truncated`, `bodies_left_out` and `faces_left_out`. A record that cannot
be parsed leaves out the face, shell or body that needs it (reason
`bad_reference`) rather than ending the read.

`FormatNotSupportedError` rules: `private_schema`; `archive` (a zip archive
that does not hold exactly one STEP file); and from the archive, `encrypted`
and `compression` as for every zip package.

Bounds (3.20.2): `p21_header_bytes`, `p21_record_bytes`, `p21_records`,
`p21_list_items`, `p21_list_depth`, `p21_string_bytes`, `p21_complex_parts`,
`brep_nodes`, `bspline_knots`, `step_products`, `step_occurrences`,
`step_styled_items`, `depth`, `tree_nodes`, `items` (placed items, and
`items` plus `tree_nodes` products reached along the occurrence paths),
`triangles`, `seconds` (ticked through every phase of the read, mapping
included), `whole_read_bytes` (the whole file is indexed in memory) and the zip
fields for an archive; the tessellator keeps its own (3.15).

Modules: `solidseas.formats.step.part21` reads the exchange structure
(`open`, `read_header`, `Part21` with `header`, `schemas`, `ids_of_type`,
`type_of`, `record`; values `Ref`, `Enum`, `Typed`, `Binary`, `DERIVED`, None
for `$`), and `solidseas.formats.step.builder.BrepBuilder` writes a body's
Parasolid nodes (`body`, `region`, `shell`, `face`, `loop`, `edge`, `vertex`,
the surfaces and curves, `transmit`). Both are written to the interface 3.20.9
plans for the shared Part 21 reader and B-rep builder, so they can move there
unchanged.

#### 3.20.8 Alibre Design and ACIS

`open_model` reads Alibre Design parts (`.ad_prt`) and assemblies (`.ad_asm`),
format `alibre`, and standalone ACIS SAB files (`.sab`), format `acis`, in pure
Python and without Alibre (`docs/formats/alibre.md` has the format and the
evidence; one Alibre release has been seen).

```python
with open_model("D:/Jobs/Example/bracket.AD_PRT") as m:
    m.variant, m.units            # "part"; {"length": "in", "scale_m": 0.0254, "source": "file"}
    m.active_configuration         # the configuration the file was saved in
    m.preview()                    # the stored thumbnail, a bitmap (image/bmp, stream PROP_DATA)
    m.scene(prefer="display")      # Alibre's own display mesh: fast, not closed
    m.scene(prefer="bodies")       # the exact ACIS B-rep, tessellated: closed
    m.bodies()                     # [BodyRef] whose transmit is the B-rep as Parasolid nodes
```

- **Variant and type:** `part`, `assembly` or `sheet_metal` (an `.ad_smp`, read
  as a part and warned `variant_unverified`); `doc_type` `part` or `assembly`
  from the streams. An Alibre file that is neither (a drawing renamed) raises
  `format_not_supported`, rule `unsupported_variant`. A compound file of another
  program with an Alibre extension raises `unknown_format`.
- **Head:** `fields` (`title`, `author`, `comments`, `last_saved_by`,
  `created_utc`, `last_saved_utc`), file-scope `properties` (strings as text,
  numbers as numbers; the file's bookkeeping, hatching defaults and the
  thumbnail left out), `application` (`Alibre Design` and the version the file
  stores), `active_configuration`, `units` (from the ACIS header; an
  assembly's are centimetres, `assumed`), `counts()` (a part: 1 object, its
  bodies and faces; an assembly: its components and the documents it
  references). A stream that cannot be read is warned `stream_unreadable` with
  its name and the rest of the document is still read.
- **Scenes of a part:** `prefer="display"` (rendered previews, thumbnails and
  the viewer's 3D view) uses the stored
  display mesh, `source` `display_mesh`, with its normals; `prefer="bodies"`
  (exports, 3D Print) tessellates the B-rep, `source` `bodies`, closed. Each
  falls back to the other when its source is missing or gives no triangles. ACIS
  data of a version other than the verified one (2100) is not decoded: the
  display mesh is used, warned `acis_version_unverified`. A face whose geometry
  is not mapped is left out (its `SkippedFace` in `Scene.skipped`,
  `faces_left_out` in an export); the scene's `counts` give `bodies`, `faces`
  and `faces_done`. `SAB_DATA` and `MESH_DATA` are read within the scene's
  `max_seconds` and `cancelled` as well as `limits.seconds`; running out of
  time raises `SldLimitError` and a cancel `ReadCancelledError`, rather than
  falling back to the other source.
- **Assemblies:** the design database's inclusions, each placing a document
  found by its GUID (never by opening the path the file stores): the assembly's
  folder is walked, then each folder in `scene(roots=...)`, and only the
  `VERSION` stream of each Alibre file there is read. `tree()` has the assembly
  node and one `component` node per inclusion (`file` the document GUID,
  `placement` relative to the assembly); `references()` one
  `ExternalReference` per document (`key` the GUID, `stored` the repository
  path the file stores, `name` its last part, `resolution` with `status`
  `found` or `not_found`, `path` relative to the assembly's folder,
  `found_by` `document_guid` or `name`, `version` the file's). A scene places
  each part's object once per inclusion, and sub-assemblies recursively; an
  inclusion that is not found or cannot be read is left out with
  `component_not_found`. A component file is opened `within` its folder under
  the assembly's own `refuse_hard_links` and `max_file_bytes` (3.20.1): with
  `refuse_hard_links` a file with a second name is no candidate, and a
  component over `max_file_bytes` is left out like an unreadable one.
  Placements are read in centimetres, warned `placement_unit_assumed` (a
  hypothesis from one assembly).
- **Standalone `.sab`:** one object per body, tessellated; no stored preview.
  A `.sat` text file raises `format_not_supported` rule `sat_text`, and a SAB
  file of another version (or an `ASM BinaryFile4` one) rule `acis_version`.

Warnings: `units_disagree` (the display mesh names another unit than the
B-rep; the B-rep's is used), `placement_unit_assumed`, `constituents_disagree`
(`CONSTITUENTS` lists other documents than the inclusions place),
`component_found_by_name` (a component whose own GUID could not be read was
found by its stored name), `component_ambiguous` (several files hold the
document; the nearest was used), `component_newer` and `component_older` (the
file's version against the one referenced), `acis_version_unverified`,
`transform_unverified` (an ACIS body transform applied as row vectors) and
`variant_unverified`; and the shared `stream_unreadable`,
`component_not_found`, `non_rigid_transform`, `faces_left_out`,
`bodies_left_out`, `instances_left_out`, `units_assumed` and `text_truncated`.

Rules of `format_not_supported`: `acis_version`, `sat_text`,
`unsupported_variant`. Bounds (3.20.2): `ole_streams`,
`alibre_small_stream_bytes`, `alibre_constituents_bytes`,
`alibre_stream_bytes`, `alibre_text_stream_bytes`, `prop_entries`,
`prop_values`, `mesh_dictionary_entries`, `mesh_key_bytes`, `mesh_blocks`,
`inclusions`, `resolve_depth`, `resolve_examined`, `resolve_candidates`,
`resolve_seconds`, `sab_records`, `sab_subtype_depth`, `sab_subtypes`,
`sab_string_bytes`, `sab_values`, `bspline_knots`, `brep_nodes`, the `p21_*`
fields for the design database, `components`, `depth`, `image_side`,
`image_bytes`, `triangles` and `seconds`.

The transmits `bodies()` returns are SolidSeas' own mapping of the ACIS body to
Parasolid nodes, made for SolidSeas' tessellator; they have not been loaded in
a Parasolid kernel.

#### 3.20.9 The B-rep builder and ISO 10303-21

The shared Part 21 reader and B-rep builder are still to come. Until they land
each reader that needs them carries its own: the STEP reader's
`solidseas.formats.step.part21` and `solidseas.formats.step.builder` (3.20.7),
written to this interface so they can move here unchanged, and the Alibre
reader's small Part 21 reader in `solidseas.formats.alibre._p21` and its
mapping of ACIS bodies to Parasolid nodes in `solidseas.formats.acis._xt`
(3.20.8), which the shared modules will replace.

### 3.21 Rendered previews: `solidseas.render` (provisional)

A model file that stores no preview image gets one drawn from its geometry, in
pure Python, with no Qt.

```python
from solidseas.formats import open_model
from solidseas.render import ThumbnailCache, render_preview

with open_model("D:/Jobs/Example/bracket.stl") as m:
    r = render_preview(m, width=256, height=192)   # Rendered: data (PNG), width, height, drawn, total, partial
```

`render_preview(scene_or_document, *, width=256, height=192, view="home",
background=None, up_axis=None, limits=None, cancelled=None)` draws a `Scene`,
or a model document's scene read with its display mesh preferred (a B-rep
tessellated coarsely: a chord of 1/150 of the box diagonal, 30 degrees, within
`thumbnail_brep_seconds`), from the Home view: orthographic, from the front,
the right and above, with Z up for the formats whose `up_axis` is `z` and a
Y-up model turned Z-up first. A z-buffer, flat Lambert shading with the light
over the viewer's shoulder, each object in its colour or a neutral grey, and a
dark outline where the depth steps, on a transparent background (`background`:
an RGB triple from 0 to 255 instead). The picture is framed on the placed
objects' boxes. Bounds: `render_side` for the size, `render_triangles` placed
triangles drawn (the largest items first, an even sample of what does not fit;
`drawn` and `total` say how many), `render_seconds` of drawing (then the image
as it stands); `partial` is true when any of these left triangles out or the
scene itself was cut short. A model with no triangle raises `NoPreviewError`.
The same model gives the same bytes.

Measured on the development PC: a 50,000-triangle mesh draws in 0.5 s at
256 x 192, 200,000 in 1.8 s, and a million-triangle STL, sampled to 500,000,
in 3.9 s after 2.4 s of reading it.

`ThumbnailCache(path=None, *, max_bytes=None)` keeps rendered PNGs in
`thumbnails.sqlite` in the cache folder of 3.18 (`application_id` `SSTH`),
keyed by the folded absolute path, size and modification time of the file,
the SolidSeas version and the render settings (`get(path, size, mtime_ns,
settings="")`, `put(...)`), at most `thumbnail_cache_bytes` (the least
recently used dropped). A damaged file is removed and made again; a database
another program wrote is never touched (the cache then answers nothing). Only
the parent process writes it, never a worker.

### 3.22 SOLIDWORKS: `solidseas.swapi` (provisional, Windows)

Everything else in this document works without SOLIDWORKS. On a Windows
machine with SOLIDWORKS installed, `solidseas.swapi` drives a SOLIDWORKS that
SolidSeas starts for itself, through `SolidSeas.SwBridge.exe`, a separate
process (`docs/ARCHITECTURE.md` section 6). Build the bridge once with
`scripts/build-bridge.ps1` or `python -m solidseas.swapi build`; nothing in this
section loads SOLIDWORKS into your process, and importing `solidseas.swapi`
starts nothing.

```python
from solidseas.swapi.batch import convert, write_report

rows = convert([r"D:\Copies\Bracket"], r"D:\Exports", ["step", "x_t", "stl", "3mf"], recurse=True)
write_report(rows, r"D:\Exports\report.tsv")
for r in rows:
    print(r.status, r.format, r.output or r.message)   # ok, fail or skip
```

```python
def convert(inputs, output_folder, formats=("step", "x_t", "stl", "3mf"), *, recurse=False,
            overwrite=False, allow_source_folder=False, solidworks_exe=None, bridge_exe=None,
            timeouts: Timeouts | None = None, max_restarts=3, log=None,
            off_hours: OffHours | None = None) -> list[ConversionRow]

@dataclass(frozen=True)
class OffHours:
    start: datetime.time = time(2, 0); end: datetime.time = time(7, 0)   # local time
    @classmethod
    def parse(cls, text: str) -> OffHours                                 # "22:00-05:30"

@dataclass(frozen=True)
class ConversionRow:
    input: str; status: str; format: str; output: str; code: str
    errors: int; warnings: int; seconds: float; message: str; step_ap: int | None
```

- `formats` from `step`, `x_t`, `x_b`, `stl`, `3mf`, `gltf` and `glb`; each
  is written by SOLIDWORKS' `SaveAs3` with its current export options, which
  this module never changes. `step_ap` says which STEP application protocol a
  STEP file has. SOLIDWORKS 2024 refuses `gltf` and `glb` (a `fail` row with
  `save_failed` and SOLIDWORKS' error code 256).
- `ValueError` for an unknown format, an output folder in a source folder
  (without `allow_source_folder`) or a timeout out of range, and
  `FileNotFoundError` for a missing input, come before anything starts. After
  that every outcome is a row: `fail` with the bridge's error `code`
  (`open_failed`, `save_failed`, `timeout`, `not_attempted` and others) and
  SOLIDWORKS' own `errors` and `warnings`, or `skip` for an output that exists
  and `overwrite` is false.
- Each step has a timeout (`Timeouts`: start 360 s, open 300 s, export 600 s,
  close 120 s, exit 180 s; each more than 0 and at most 86,400 s, or
  `Timeouts` raises `ValueError`). When one runs out, that SOLIDWORKS and its
  bridge are ended and the next document gets new ones, up to `max_restarts`
  times.
- Starting SOLIDWORKS takes the foreground of your desktop for 6 to 7 s, so a
  job you did not start yourself should pass `off_hours`, and SOLIDWORKS then
  runs only inside that window (02:00 to 07:00 by default; it may pass
  midnight): every start, a restart after a timeout included, waits until
  local time is inside it, and once it has closed, before the next document
  or export, the document in hand is closed, SOLIDWORKS is ended and the work
  goes on in the next window (not counted as a restart). Alone on the machine,
  SolidSeas' SOLIDWORKS holds the journal file, so one you started while it
  ran would have no auto-recover. Without `off_hours`, SOLIDWORKS starts at
  once and runs to the end. `log` says how long it waits and how each
  SOLIDWORKS ended, and also gets a line when the bridge hides the instance's
  journal file message box or leaves another dialog of it alone.
- Documents are opened read-only, and only export formats are written, never
  over the file of an open document under any name. Opening an assembly still
  makes SOLIDWORKS write briefly in its folder, creating something there and
  removing it again: the folder's time changes, and the same files are there
  before and after (measured on a copy of a fixture assembly). A network path
  is accepted for the documents and the output folder named. The instance is
  ended directly, through its Job Object, never through SOLIDWORKS' own
  shutdown.
- The command line is `python -m solidseas.swapi convert INPUT... -o DIR
  [--format step,stl] [--recurse] [--force] [--allow-source-folder]
  [--open-timeout S] [--export-timeout S] [--off-hours [HH:MM-HH:MM]] [--json]`;
  it writes `report.tsv` and exits 0, 4 when a row failed, and 2 for wrong
  arguments, a timeout or window out of range included.

`solidseas.swapi.bridge.Bridge` is the client underneath: `request(op, args,
timeout=...)` sends one of the bridge's named operations and returns its
result, raising `BridgeRequestError` (with `code`), `BridgeTimeoutError` (the
bridge and its SOLIDWORKS were ended) or `BridgeExitedError`, and
`ValueError`, sending nothing, for a timeout outside 0 to `MAX_TIMEOUT_S`
(86,400 s) or a request longer than `MAX_REQUEST_CHARS`. `on_event` listeners
run on a thread of their own, and get `window` events when the bridge hides
its instance's journal file message box. A `BridgeTimeoutError` names the
dialogs SOLIDWORKS showed while the request waited, in `details["dialogs"]`.
The operations, the protocol and the safety rules are in
`src/solidseas/swapi/README.md`.

Two of the operations measure and import:

```python
from solidseas.swapi.bridge import Bridge

template = r"C:\ProgramData\SolidWorks\SOLIDWORKS 2024\templates\MBD\part 0051mm to 0250mm.prtdot"
with Bridge() as b:
    b.request("start_solidworks")
    doc = b.request("import_file", {"path": r"D:\Copies\bracket.step", "template": template})
    print(doc["result_kind"], doc["solid_bodies"], doc["dialog_appeared"])      # solids 1 False
    m = b.request("mass_properties", {"doc": doc["doc"]})["measures"][0]
    print(m["mass"]["volume_m3"], m["mass"]["center_of_mass_m"], m["bbox_m"])  # SI units
    b.request("close_document", {"doc": doc["doc"]})
```

- `mass_properties` measures a document the bridge opened or made, in the
  active configuration, one named (`configuration`) or every one
  (`all_configurations`): solid and sheet bodies (hidden ones counted
  separately), faces, edges and vertices, volume, surface area, centre of mass
  and mass from SOLIDWORKS' `IMassProperty2`, the sheet area, a precise box of
  the bodies (an assembly's components moved into place) and `IBody2.Check3`
  faults. `mass.valid` is false when there is no visible solid or SOLIDWORKS
  reports zero volume for one (seen on parts from older versions), and
  `warnings` says why; it also names a mass or centre of mass set by hand in
  the document, and the other cases the README lists. Another configuration is
  shown to be measured and the active one shown again; nothing is saved, but
  SOLIDWORKS may keep the document marked changed while it is open, which the
  reply's `dirty` says.
- `import_file` imports a STEP file (IGES, `.x_t` and `.x_b` the same way)
  into a new document: by default into a part made from the `template` you
  give (pass one the SOLIDWORKS installer ships), through 3D Interconnect, or
  with `"method": "load"` as File Open imports it, from your default part
  template. It changes none of your SOLIDWORKS options; it reads and returns
  the import options in force (`preferences`) and refuses, before importing
  anything, a STEP assembly and the cases those options would turn into a
  template dialog (`refused` with `details["reason"]`). The reply says
  whether the result is solids or surfaces, how many bodies, SOLIDWORKS'
  error code, and which dialogs appeared (`dialogs`). A dialog that holds the
  import, such as the Import Diagnostics question, ends SolidSeas' SOLIDWORKS
  at the request's timeout (600 s by default).

#### `solidseas.swapi.live`: a Review mode script's SOLIDWORKS (new, provisional)

The typed interface a script the person approved in the modeling assistant has
to their open document (`docs/ASSISTANT.md`, Review mode). It works only inside
such a run, where SolidSeas runs the script in a child process and answers each
request for the document the person picked; anywhere else every function raises
`LiveUnavailableError`. Nothing in it imports win32com, comtypes or pythonnet.

```python
from solidseas.swapi import live

live.document()                 # title, type, active_configuration, configurations, feature_count
live.features(limit=10000)      # [{"name", "type", "id"}] in tree order
live.dimensions(limit=10000)    # [{"name", "value", "feature"}], metres or radians
live.properties()               # custom properties by name
live.mass_properties(configuration=None)
live.operation("fillet", edges=["E12"], radius={"value": 2, "unit": "mm"})
```

`operation` takes the Automatic mode vocabulary (`solidseas.ai.prompts.OPERATIONS`)
by name, with a plan step's arguments; the app refuses any other name
(`LiveError` with `code` `unknown_operation`) before it reaches SOLIDWORKS, and
arguments that are not plain JSON or are longer than 256 KB. A refusal or a
failure in SOLIDWORKS is a `LiveError` whose `code` says which. The draft prompt
(`DRAFT_SYSTEM`) names these functions and the vocabulary, so a model drafts
against them.

### 3.23 The AI connector: `solidseas.ai`, and the machine policy (provisional)

The connector the desktop app's modeling assistant uses to ask a model for
Review mode drafts and Automatic mode plans (`docs/ASSISTANT.md` holds the
rules it is checked against). Integrations do not need it. It is the standard
library only: each provider speaks HTTP through `http.client`, keys come from
Windows Credential Manager through ctypes, and `truststore` is used when it is
installed (`pip install solidseas[ai]`). Importing it builds no provider and
reaches no network. Everything in this section is provisional while the
assistant is built.

```python
from solidseas.ai import AISettings, CallOptions, Cancel, RunBudget, build_model_summary, get_provider

settings = AISettings(provider="anthropic", model="<a model id>")   # the key is in Credential Manager
provider = get_provider(settings)              # a NoopProvider, with .reason, when it cannot be used
summary = build_model_summary(snapshot)        # a PartSnapshot the bridge took of the part
stop = Cancel()                                # stop.cancel() from any thread stops the call at once
result = provider.plan_steps("shell the part to 2 mm", summary,
                             call=CallOptions(cancel=stop, run_budget=RunBudget(30_000)))
if result is None:
    ...                                        # this provider does not plan: a capability gap
plan = result.value                            # a validated Plan; result.prompt is exactly what was sent
```

```python
factory.get_provider(settings, *, credentials=None, ledger=None) -> ModelProvider   # also solidseas.ai.get_provider
factory.reset()                                           # after any change to the AI settings or a key
factory.refusal(settings, policy) -> str | None           # why the machine policy refuses settings' provider
AISettings(provider="none", model="", ollama_url="http://127.0.0.1:11434", monthly_tokens=2_000_000,
           monthly_cost=None, price_input_per_mtok=None, price_output_per_mtok=None, run_tokens=30_000,
           max_steps=20, max_new_instances=200, length_factor=10.0, no_body_length_mm=1000.0,
           min_length_mm=0.001, protected_properties=(), always_confirm=False)
AISettings.from_dict(data) / .to_dict() / .budget() -> Budget / .limits() -> PlanLimits
ModelProvider.name, .model, .local, .health(*, refresh=False) -> HealthResult (ok, message, checked_at)
ModelProvider.draft_change(context, request, *, call=None) -> TaskResult[Draft] | None
ModelProvider.plan_steps(goal, model_summary, *, call=None) -> TaskResult[Plan] | None
TaskResult.value, .prompt, .raw, .input_tokens, .output_tokens
CallOptions(cancel=None, deadline=None, run_budget=None)   # deadline: a time.monotonic() value
context.build_model_summary(snapshot, *, send_names=False, max_chars=20_000) -> ModelSummary
context.prepare_request(text, *, max_chars=4_000) -> PreparedRequest;  context.redact(text) -> (text, count)
prompts.plan_prompt(goal, summary, *, limits=None) -> Prompt;  prompts.draft_prompt(request, context=None) -> Prompt
prompts.parse_json_response(text);  prompts.parse_plan(text, summary, *, goal, limits=None) -> Plan
prompts.parse_draft(text) -> Draft (language, code, explanation)
credentials.default_store();  WindowsCredentialStore();  MemoryCredentialStore();  Secret(key).reveal()
usage.UsageLedger(path=None, *, budget=None);  Budget(monthly_tokens, monthly_cost, pricing);  Pricing
usage.RunBudget(limit=30_000).used / .held / .remaining
usage.reserve(ledger, *, input_tokens, output_cap, local=False, run=None) -> Hold   # .max_output, .settle(), .release()
AIError.code, .detail, .delivered                         # delivered: the provider had the request, so it is charged
fake.ScriptedProvider(replies)                            # for tests: answers from a queue, records every prompt
solidseas.policy.current() -> Policy;  read_policy(registry=None);  set_reader(reader)
solidseas_app.assistant.automatic.start_run(target, plan, *, confirmed=False, always_confirm=False) -> RunStart
solidseas_app.assistant.automatic.confirmation(plan, *, always_confirm=False) -> Gate (waits, reasons)
```

**Providers.** `get_provider` is the only place one is built. It reads the
machine policy first and serves `NoopProvider` with a `reason` instead of a
provider it may not use: `not_configured` (no provider or no model: the app
hides every AI control), `policy_refused` (the controls stay visible,
disabled, "Set by your administrator"), `no_key`, `credential_store` or
`invalid_setting`. A noop's tasks return None. The provider is cached until
`reset()`, and every provider it builds reads the policy again before each
call and health check, cached or not. A provider also makes that check itself,
from its own kind and address, so one built any other way is refused just the
same.

| Provider | Endpoint | Key | Request |
|---|---|---|---|
| `anthropic` | `https://api.anthropic.com` | `x-api-key` header | `POST /v1/messages` |
| `openai` | `https://api.openai.com` | `Authorization: Bearer` header | `POST /v1/chat/completions`, JSON object replies |
| `gemini` | `https://generativelanguage.googleapis.com` | `x-goog-api-key` header | `POST /v1beta/models/<model>:generateContent`, JSON replies |
| `ollama` | the `ollama_url` setting, `http://127.0.0.1:11434` by default | none | `POST /api/chat`, `"format": "json"` |

No model is chosen by default: model names change faster than SolidSeas
releases, so the settings must name one. A key never goes in a URL. Every
call has a connect timeout of 5 seconds and a read timeout of 60 (180 for
Ollama), and must finish within the two together and before the run's
deadline. 429, 503 and 529 are retried up to four tries in all, honouring
Retry-After up to 30 seconds and backing off with jitter otherwise; 401 and
403 stop at once. Cloud providers use the proxy from the environment or the
static Windows setting, through CONNECT; Ollama never uses a proxy, resolves
its host on every call and connects only to the addresses it resolved, and
`localhost` must resolve only to loopback addresses. `health()` checks the
key, the server and the model (`GET /v1/models/<model>` for Anthropic and
OpenAI, `GET /v1beta/models/<model>`, `GET /api/tags`) at most once an hour,
and says so plainly when the model is not there.

**What leaves the machine** is the prompt and nothing else: the system text
(`prompts.PLAN_SYSTEM` or `prompts.DRAFT_SYSTEM`), the request or goal,
capped at 4,000 characters (longer is refused, not cut) and redacted, and,
when a part is involved, the model summary inside `<document_data>`. The
summary is the only way document data reaches a prompt. It holds handles
(`F`, `D`, `E`, `Fa`, `P`, `A`), feature types and their numeric parameters
with units, dimension values, the document's length unit, the bounding box and
volume, reference planes and axes, and the solid bodies' faces and edges with
a compact geometric description, all in millimetres and degrees. It never
holds the path or title, custom or configuration property values, summary
fields, the material, equations, sketch or annotation text, or a persist
reference. Names a person typed (features, sketches, planes, axes, dimensions,
configurations and custom property names) go only with `send_names=True`,
only in its `document_names` field, each at most 64 characters with control
characters removed. A summary longer than 20,000 characters is refused with
`input_too_large`, never cut. `prompt.text()` is what the "What the AI sees"
panel shows.

**Replies.** Every reply goes through `parse_json_response`, which takes the
JSON out of a code fence or prose, in time linear in the reply's length, and
refuses `NaN`, `Infinity`, numbers that overflow (`1e999`) and repeated keys.
Stop pressed while a reply arrives discards it (`cancelled`). A plan is
`{"vocabulary": 1, "steps": [{"op": ..., "args": {...}, "note": ...}], "notes": ...}`
in the vocabulary of `docs/ASSISTANT.md`; `parse_plan` refuses the whole plan
for one bad step, a plan over the step limit, an unknown operation or field, a
handle that does not resolve to exactly one entity of the right kind, a value
out of range or without its unit, a bool where a number is expected, and a
protected or formula-like property, and it marks each argument "you said" or
"from the model". A draft is
`{"language": "python" | "cadquery", "code": ..., "explanation": ...}`.

**Budgets and usage.** Before each call the input is estimated (a deliberately
high three characters a token) and the output cap sent with the call is the
smallest of the task's cap (8,192 tokens), what the month's token budget
leaves, what the cost budget leaves at the configured prices, and, in
Automatic mode, what the run budget leaves; a call that cannot get 256 output
tokens is refused with `budget_exceeded` before anything is sent. A cost
budget with no prices refuses every cloud call. The monthly budgets apply to
cloud providers; Ollama is counted, not limited; the run budget applies to all.
Usage goes into `usage.json` beside the catalogs (`%LOCALAPPDATA%\SolidSeas`,
or `SOLIDSEAS_CACHE_DIR`) in UTC calendar months, under a lock that two
processes share, through a temporary file and a replace; recording never
raises. The check also holds what it grants (the input estimate plus the output
cap) in the run's budget and, for a cloud provider, in `usage.json` under the
same lock, until the call's reported usage replaces it, so calls in flight at
once cannot each be granted the whole remainder; a hold a closed window left
lapses after 10 minutes. A call that fails after the request reached the
provider (a timeout or Stop once it was sent, or a successful reply that
cannot be read; the error's `delivered` is true) is charged its input
estimate plus its output cap; one answered with an error status, or never
sent, costs nothing.

**Keys.** One generic credential per provider, `SolidSeas/<provider>`, written
with `CredWriteW` and `CRED_PERSIST_LOCAL_MACHINE`, so it stays on this PC and
does not roam. A key is a `Secret`, whose `repr` and `str` hide it; providers
take it explicitly and never read an environment variable. On a platform
without Credential Manager no key is found and none can be stored.

**Errors.** The connector raises `solidseas.ai.AIError` subclasses, each with
a `code` from `solidseas.ai.AI_ERROR_CODES` (`not_configured`,
`policy_refused`, `no_key`, `credential_store`, `unauthorized`,
`rate_limited`, `unavailable`, `network`, `timeout`, `cancelled`,
`budget_exceeded`, `input_too_large`, `reply_invalid`, `provider_error`,
`invalid_setting`) and a message for the person. They are not
`SolidSeasError`s and never reach the command line or the service, so 5.6 does
not list them. No message holds a key, a header or a query string; a provider's
own error text is quoted only for statuses other than 401 and 403, scrubbed of
the key and anything shaped like one, and only then cut to 200 characters.

**The machine policy.** `solidseas.policy.current()` reads
`HKLM\SOFTWARE\Policies\SolidSeas` in the 64-bit view on every call, fail-closed:
only `FileNotFoundError` means absent, any other error opening the key turns
every restriction on, and a value of the wrong type or a DWORD other than 0 or 1
turns its restriction on (`AllowedProviderHosts` of the wrong type counts as
empty). It returns `Policy(automatic_disabled, local_only, allowed_hosts,
locked, error)`; `locked` is true when the key exists or could not be read.
Off Windows there is no policy. It is enforced in two places only:
`get_provider` refuses any provider but an Ollama whose host is `localhost`, a
loopback address or exactly one of `AllowedProviderHosts` under
`LocalProviderOnly`, and `start_run` refuses under `DisableAutomaticMode`.

**Starting an Automatic run.** `start_run(target, plan)` is the only entry. It
makes the checks of `docs/ASSISTANT.md` in order (the policy, the one-writer
mutex `Local\SolidSeas-Live-<pid>`, a part, the document's state, a valid plan
confirmed when `confirmation(plan)` says it waits, its handles still resolving,
and checkpoint 0 written and not empty) and raises `RunRefused` with a `code`
on the first that fails, keeping nothing. `target` is the bridge's view of the
bound document (`sw_pid`, `document_kind()`, `document_problem()`,
`unresolved(refs)`, `write_checkpoint(path)`). It returns a `RunStart` with the
run id, the run folder `%LOCALAPPDATA%\SolidSeas\runs\<run id>`, the safety
copy `checkpoint-<run id>.sldprt` and the held session; the step loop comes
with the bridge's live mode (3.22 has its batch mode only).

### 3.24 Drawings: `solidseas.drawing` (provisional)

Automatic drawings from 3D parts (`docs/DRAWINGS.md`, `docs/drawings/`): a
SOLIDWORKS part becomes a datum-referenced, dimensioned drawing, kept as a
`.ssdrw` file and exported as PDF and DXF, stamped PRELIMINARY until it is
signed and released. Every stage is built: the part's source, its B-rep model,
feature recognition, the views, the plan and its layout, and the drawing file.
A SolidSeas without a stage raises `UnsupportedOperationError` (code
`not_implemented`) with `detail["rule"] == "stage_missing"` and
`detail["value"]` naming it. Everything in this section is provisional until
the first release that makes drawings.

```python
from solidseas import drawing

settings, problems = drawing.load_settings()       # Drawing.json, every value checked
d = drawing.make_drawing(
    "bracket.SLDPRT",
    options=drawing.DrawingOptions(process="machined", units="in"),
    fields={"title": "BRACKET, MOTOR MOUNT", "number": "1234-001", "drawn_by": "Ann Bee"},
    settings=settings,
)
d.status, d.checks, d.coverage                     # "PRELIMINARY", the checks of 20.1
drawing.save(d, "1234-001.ssdrw")
with open("1234-001 A PRELIMINARY.pdf", "xb") as fh:
    drawing.write_pdf(d, fh)

d2, checks = drawing.edit.remove(d, "d-12")        # every edit returns the drawing and its checks
d3, report = drawing.regenerate(d2, "bracket.SLDPRT")  # keeps removals, moves and overrides
```

**The run** (`solidseas.drawing.pipeline.run(part, *, options, fields,
settings, limits, stages=None, until=None)`): the stages in order, each with
its seconds; `Run` holds each stage's output, the drawing and `orchestrated`,
the plan stage's plan, layout and layout checks. A stage can be replaced by
name (`stages`) and the run stopped after one (`until`). `make_drawing` is
`run(...).drawing`.

**Editing** (`solidseas.drawing.edit`, `docs/drawings/edit.md`): `remove`,
`restore`, `delete`, `candidates` and `add`, `link`, `set_origin`,
`set_scheme`, `set_depth_reference`, `set_tolerance`, `set_precision`,
`set_prefix`, `set_suffix`, `override_value`, `set_frame`, `set_datum`, `move`,
`flip`, `reset_position`, `set_sheet`, `set_scale`, `set_units`, `add_view`,
`remove_view`, `edit_notes`, `set_title`, `set_tolerance_block`,
`use_settings`, `confirm_thread`, `confirm_end`, `sign`, `release_drawing` and
`start_revision`. Each takes a drawing and returns `(drawing, checks)`, never
changing the drawing given. Laying the sheet out again needs the model: the run
that made or regenerated a drawing is kept beside it in the process, and
`edit.attach(drawing, part)` opens the model of a drawing read from a file;
without either an edit raises `InvalidArgumentError` with rule
`model_not_found`. A RELEASED drawing refuses every edit but `start_revision`
with `DrawingReleasedError` (code `drawing_released`).

**Checks** (`solidseas.drawing.checks.run_checks(drawing, *, planned=None,
layout=None, release=False)`, `docs/drawings/checks.md`): the checklist of
`docs/DRAWINGS.md` 20.1 as `Check(code, level, message, item, fixes)` records
in a fixed order; with the plan and layout of a live run every check runs, and
on a drawing read from a file those the file can answer. `release=True` gives
the release-time levels.

**Errors.** `DrawingInvalidError` (code `drawing_invalid`, a `.ssdrw` refused),
`DrawingTooComplexError` (code `drawing_too_complex`, a `SldLimitError` with
`detail["limit"]` naming the bound), `ModelNotFoundError` (code
`model_not_found`) and `DrawingReleasedError` (code `drawing_released`); the
first, third and fourth are `InvalidArgumentError`s, so existing handlers keep
working.

**`DrawingOptions`** (frozen, checked when made, `InvalidArgumentError` naming
the field): `process` (`machined`, `printed`), `scheme` (`datum`, `plusminus`;
None takes the process's default), `units` (`part`, `in`, `mm`), `views`
(`auto` or names), `front` and `turn`, `hidden`, `tangent`, `sheet` (`auto`, `A`
to `E`), `scale` (`auto` or `(sheet, model)` such as `(1, 2)`), `arrangement`
(`(("v-1/x", "ordinate"),)`), `bodies`, `quality` (`normal`, `draft`, `fine`),
`configuration`.

**`DrawingLimits`** holds every bound of `docs/DRAWINGS.md` 17.1 (faces 50,000,
edges 150,000, triangles 400,000, 150 s in all, and the rest). A caller may
lower any bound, never raise one past its ceiling. A part over the face, edge
or body bound is refused from a topology walk before it is tessellated, with
`DrawingTooComplexError` (code `drawing_too_complex`) and `detail["limit"]`
naming the bound.

**Settings** (`solidseas.drawing.settings`): `load_settings(path=None)` returns
`(DrawingSettings, problems)`. The file is `Drawing.json` under
`%APPDATA%\SolidSeas` on Windows, `~/Library/Application Support/SolidSeas` on
macOS and `$XDG_CONFIG_HOME/solidseas` elsewhere, schema
`solidseas.drawing-settings/1`, at most 256 KiB, strict JSON (no repeated keys,
no NaN, 32 levels at most). A missing file gives the defaults; every value is
checked on its own and a bad one falls back to its default with a problem in
words; members a newer SolidSeas wrote are kept and written back.
`save_settings(settings, path=None)` writes through a temporary file and a
rename and refuses a link; `with_value(settings, group, key, value)` changes one
value with the same checks; `settings.first_use()` lists what still needs the
user's answer. The groups are those of `docs/DRAWINGS.md` 7.2: `company`,
`people`, `standard`, `sheets`, `title_sources`, `tolerances`, `gdt`, `printing`,
`notes`, `materials`, `defaults`, `files` (with `replace_own_files`, on by
default), `email` and `limits`.

**The source** (`solidseas.drawing.source.open_source(path_or_document, *,
configuration=None, bodies=None, units=None, title_names=(), limits)`): reads a
SOLIDWORKS part or assembly read-only. A drawing raises
`UnsupportedOperationError` with rule `drawing`; another format rule
`format_later`. An assembly (`solidseas.drawing.assembly.open_assembly`,
`docs/drawings/assemblies.md`) is read with its part instances placed, each
part's bodies once, and its top-level bill of materials: its source has
`format` `sldasm` and `assembly`, the instances, their placed bodies and the
parts list's lines; one none of whose instances can be drawn raises with rule
`no_instances`. Its drawing has views, a parts list and item balloons, and no
dimensions. It returns a `DrawingSource`: `name` (the file name only),
`format`, `kind`, `configuration`, `bodies` (name, type, face count, whether
drawn, whether hidden in SOLIDWORKS), `units` (`unit`, `origin` of `file`,
`guessed` or `user`, and for a guess the evidence of
`numbers.guess_units`), `material`, `properties`, `hints` (numbers in the
KeyWords field, for ranking only), `sha256` of the file, `geometry_digest` (the
SHA-256 of every face's signature at 1e-7 m: a save that changed no geometry
keeps it) and `properties_digest` (of the properties named in `title_names`).

**The model** (`solidseas.drawing.facegraph`): `from_document(doc,
configuration=None, *, quality, limits)`, `from_bodies(bodies, ...)` and
`from_transmit(xt, ...)` tessellate with `detail=True` (3.15) and return a
`BrepModel`: faces by their index in the mesh with typed surfaces (a plane's
outward normal and offset; a cylinder's or cone's axis, radius or half angle,
x and y, and whether it is concave; spheres and tori), area, loops, vertex and
triangle ranges and signature; edges by their detail key with their curve
(line, circle, ellipse, B-spline), samples, parameters, both faces and their
normals, length and kind (`convex`, `concave`, `tangent` within 1 degree,
`seam`, `open`); vertices with the faces that meet there; axis groups; the box,
diagonal and tolerance (1e-6 of the diagonal); and whether the shell is closed.
Normal quality tessellates at 1e-3 of the diagonal, Fine at 2.5e-4, Draft at
2e-3.

**Values** (`solidseas.drawing.numbers`): `show(value_m, unit, places,
tolerance=None, *, prefix="")` returns a `Shown` with the text parts kept apart
(prefix, value, what follows it, stacked upper and lower, boxed), following
`docs/DRAWINGS.md` 10.8: inch values without a leading zero and with the
precision's places, a zero deviation shown as `.000` with its sign; millimetre
values with a leading zero and a zero deviation as a lone `0`; ± for symmetric
tolerances, limits stacked, MAX and MIN after the value, basic values boxed
with the places they need, references in parentheses. `show_angle` does the
same for angles. `rounding_flagged(value_m, unit, places, band)` is the
rounding guard (more than a tenth of the band). `guess_units(sizes_m)` counts
sizes that are whole thousandths of an inch against whole hundredths of a
millimetre and returns inch, undecided, when they prove nothing.

**The display list** (`solidseas.drawing.display`): geometry (`Segment`, `Arc`,
`EllipseArc`, `Spline`, `Polyline`) in sheet millimetres, annotations, and the
painted layer (`Stroke`, `Fill`, `TextRun`, `ImageRun`) in a `Sheet`.
`to_compact(sheet)` and `from_compact(data)` give the `.ssdrw`'s compact
`sheet` member (lengths in integer micrometres, schema
`solidseas.drawing-sheet/1`). `solidseas.drawing.svg.to_svg(sheet)` draws the
painted layer as SVG, the reference the PDF writer is compared with; it is not
a user export.

**Also:** `standards` (sheets, scales, line widths, text heights, tolerance
blocks, ISO 2768-1 tables, process figures, thread and clearance tables,
revision letters, GD&T characteristics), `fonts` (Helvetica widths in WinAnsi
and `measure`), `keys` (signatures and descriptors) and `types` (the stage
contracts of `docs/DRAWINGS.md` 6).

## 4. JSON encoding

### 4.1 Envelope

Every JSON document has one envelope:

```json
{"ok": true, "kind": "document_summary", "schema_version": 1, "solidseas": "0.2.0",
 "source": {"root": "jobs", "path": "Example/bracket.SLDPRT"},
 "data": {}}
```

```json
{"ok": false, "kind": "error", "schema_version": 1, "solidseas": "0.2.0",
 "source": {"file": "bracket.SLDPRT"},
 "error": {"code": "damaged_file", "message": "The file is damaged or is not a complete SOLIDWORKS document.",
           "exception": "SldFormatError", "retryable": false, "detail": {}, "reader_message": "..."}}
```

`source` is the only part that differs by surface: null from Python, `{"file":
<the argument as given>}` from the CLI, and `{"root", "path"}` from REST.
`solidseas.model.envelope()` and `error_envelope()` build both forms.

### 4.2 Encoding rules

`solidseas.model.dumps` is the only encoder. It is strict: it refuses rather
than guesses, and the builders convert every value first, so what Python
callers get from `summary()` is exactly what a JSON client parses.

| Value | Rule |
|---|---|
| Integer | Exact up to 2^53 - 1, the largest integer JavaScript keeps exact. A larger value is null with the warning `value_not_representable`, and the field's `text` keeps the digits. Fields that are legitimately large are strings by schema: `mtime_ns` |
| Float | Finite only. NaN or infinity is null with the warning `non_finite_number` |
| String | Lone UTF-16 surrogates are replaced with U+FFFD. Output is ASCII, with every other character escaped by JSON |
| Date and time | ISO 8601, to the second, millisecond or microsecond, whichever keeps the value exact (a file's `modified_utc` usually has microseconds). Ends in `Z` when the zone is known; no offset means local time on the saving machine, zone unknown. A date-only field (`last_build_date`) is a calendar date. A `date` property is a calendar day stored as an instant, and its `date` field holds the day (5.3, section 6) |
| Bytes | Never in JSON. Images are separate binary responses |
| Anything else | The encoder raises `TypeError`: a builder must convert it |
| Order | Keys appear in builder order and lists in stored order, so two runs give byte-identical output |
| Paths | Stored paths stay as stored (backslashes); root-relative paths use `/` |

`dumps(..., pretty=True)` indents by two spaces (CLI `--json`); the default is
compact (`--jsonl` and REST).

### 4.3 Kinds and schema versions

Each kind has a schema version and a JSON Schema (2020-12) in
`solidseas.model.KINDS`. Adding a field does not change the version; removing,
renaming or retyping one, or changing its meaning, does. The API version is 1.

| Kind | Version | State | CLI | REST |
|---|---|---|---|---|
| `document_summary` | 1 | built | `info` | `/v1/document` |
| `properties` | 1 | built | `props` | `/v1/properties` |
| `configurations` | 1 | built | `configurations` | `/v1/configurations` |
| `components` | 1 | built | `components` | `/v1/components` |
| `references` | 1 | built | `references` | `/v1/references` |
| `bom` | 1 | built, provisional | `bom` | `/v1/bom` |
| `listing` | 1 | built | `list` | `/v1/list` |
| `streams` | 1 | built | `streams` | |
| `file_written` | 1 | built | `dump`, `preview` | |
| `parasolid_result` | 1 | built | `parasolid` | |
| `export_result` | 1 | built, provisional | `export` | |
| `batch_summary` | 1 | built | `batch` | |
| `version` | 1 | built | `version` | `/v1/version` |
| `error` | 1 | built | every command | every route |
| `path_report` | 1 | built | `paths` | `/v1/path-report` |
| `health` | 1 | built | | `/v1/health` |
| `identity` | 1 | built | | `/v1/identity` |
| `roots` | 1 | built | | `/v1/roots` |
| `serve_started` | 1 | built | `serve` | |
| `catalog` | 1 | built, provisional | `catalog` | `/v1/catalog` |
| `catalog_list` | 1 | built, provisional | `catalogs` | |
| `catalog_cleared` | 1 | built, provisional | `clear-index` | |
| `catalog_scan` | 1 | built, provisional | `index` | |
| `where_used` | 1 | built, provisional | `where-used` | `/v1/where-used` |
| `catalog_search` | 1 | built, provisional | `search` | `/v1/search` |
| `duplicates` | 1 | built, provisional | `duplicates` | |
| `missing_references` | 1 | built, provisional | `missing` | |
| `catalog_changes` | 1 | built, provisional | `changes` | |
| `model_summary` | 1 | built, provisional | `info` (a model file) | `/v1/document` (a model file) |
| `drawing_result` | 1 | built, provisional | `drawing` (every action) | |

`/v1/preview` is the one route that answers with an image instead of a kind.
`model_summary` stands in for `document_summary` on `info` and `/v1/document`
when the file is not a SOLIDWORKS document (its `KindSpec.alternate_of`), so
the envelope's `kind` says which one a client got.

Reference resolution has no kind of its own: its results are part of the
`references` kind (`references --resolve`, and `/v1/references?resolve=1` from
the service, C3), section 5.10.

`solidseas schema KIND` prints a kind's envelope schema (section 7.1).

## 5. JSON shapes that are built

### 5.1 `document_summary` (v1)

```json
{"file": {"name": "bracket.SLDPRT", "size": 144400, "modified_utc": "2026-09-30T14:02:11.123456Z",
          "mtime_ns": "1790292487123456789"},
 "format": "modern",
 "doc_type": "part",
 "doc_type_source": "definition",
 "saved_version": {"format_version": 17000, "release": "SOLIDWORKS 2024", "release_verified": true,
                   "last_build": 2024016, "last_build_date": "2024-01-16", "save_as_previous": false},
 "active_configuration": "Default",
 "configurations": [],
 "properties": [],
 "material": {"name": "1060 Alloy", "database": "SOLIDWORKS Materials"},
 "units": {"system": "MMGS", "length": "mm", "mass": "g", "angle": "deg", "length_decimal_places": 2},
 "fields": {"title": null, "subject": null, "author": null, "keywords": null, "comments": null,
            "last_saved_by": "example", "created_utc": "2026-09-30T13:58:40Z",
            "last_saved_utc": "2026-09-30T14:02:10Z"},
 "preview": {"available": true, "reason": null, "mime": "image/png", "width": 640, "height": 480,
             "bytes": 27570, "stream": "PreviewPNG", "sha256": "..."},
 "counts": {"streams": 41, "configurations": 1, "custom_properties": 3, "references": null,
            "nested_documents": 0, "parasolid_partitions": 1},
 "warnings": []}
```

| Field | Null when |
|---|---|
| `file` | Never; its four fields are null for bytes input (`name` too, unless `name=` was given). `mtime_ns` is a decimal string |
| `doc_type` | Neither the GUID nor the file name says |
| `active_configuration` | The file names none (1 assembly in the development corpus, and drawings) |
| `configurations`, `properties` | Left out with `include`. `properties` holds the file-level properties; configuration properties are inside each configuration |
| `material` | No material assigned |
| `units` | Unknown (all legacy files, and modern files without unit properties) |
| `fields.*` | No carrier holds the value |
| `counts.references` | Parts. Assemblies count referenced files; drawings count their models, provisionally |

`preview` never is null. When the file stores no preview (about a third of real
parts), it is `{"available": false, "reason": "not_stored"}` with the other
fields null. When preview streams exist but none decodes, the reason is
`"undecodable"` and a `preview_undecodable` warning is added. `sha256` is of the
image bytes the preview route and `Document.preview()` return.

### 5.2 `configuration` and the `configurations` kind (v1)

```json
{"name": "Default", "id": 0, "active": true, "most_recent": true, "comment": null,
 "material": {"name": "1060 Alloy", "database": "SOLIDWORKS Materials"}, "material_assigned": true,
 "properties": []}
```

`id` is null when no carrier gives one. `material_assigned` is true, false, or
null when the carriers do not say. `properties` holds that configuration's own
properties, each with `scope` `"configuration"`.

The `configurations` kind is `{"active_configuration", "configurations",
"warnings"}`.

### 5.3 `property` and the `properties` kind (v1)

```json
{"name": "Qty", "scope": "file", "configuration": null, "type": "number", "value": 42, "date": null,
 "text": "42", "expression": "42", "linked": false}
```

| `type` | `value` |
|---|---|
| `text` | a string |
| `number` | a number, or null (unparseable text, or a value JSON cannot carry exactly; see 4.2) |
| `boolean` | true, false or null |
| `date` | ISO 8601 text, or null; `date` holds its calendar day |
| `other` | null; `text` holds what the file stores |

`date` is a `date` property's calendar day as `YYYY-MM-DD` (new in 0.2.122),
null for the other types and for a date that did not parse. It is what the
user typed and what to show: the UTC date of `value`, which SOLIDWORKS stores
at noon local time, so right for a file saved anywhere from UTC-11 to UTC+12
(a day saved at UTC+13 or +14 comes out a day early), or the date part of a
`value` with no offset.

`text` is the stored text for every type but one: a date stored as a FILETIME
(`vt:filetime`) has no text of its own, and `text` is then the ISO form of
`value`; the date as the user typed it is in `expression`. A `date` property
is a calendar day, which SOLIDWORKS stores as an instant around noon, local
time, on the saving machine: fixture o14's `3/15/2024`, saved at UTC-4, is
`value` and `text` `2024-03-15T16:00:00Z` with `expression` `3/15/2024` and
`date` `2024-03-15`. Show the day, not the instant (section 6). Its `linked` is false: the file
keeps the typed value with an evaluated text equal to it, which links nothing
(3.2). Where a file keeps an expression in a hidden property beside a
different stored value, `linked` is false only when the expression is a number
that reads as the value (`3.25` for `3.250000`) or a yes or no that means it;
any other expression there reads as linked, a typed date or a number with a
decimal comma included. No file seen stores such a date or number that way
(`docs/FORMAT.md` 11.1).

The `properties` kind is `{"view", "configuration", "properties",
"warnings"}`, where `view` is:

- `file`: file-level properties only (`configuration` is null);
- `configuration`: that configuration's own properties only;
- `effective`: file-level properties overridden by the configuration's, each
  carrying its `scope`. This is the default, and what a bill of materials sees.

`configuration` in the result names the configuration used; when none was
requested it is the active one (section 3.4).

### 5.4 `warning`

`{"code": "xml_parse_error", "stream": "docProps/app.xml", "message": "XML parse error: ..."}`.
The codes are in section 3.5.

### 5.5 `version` (v1)

`{"solidseas": "0.2.0", "api": 1, "schemas": {"document_summary": 1, "properties": 1, ...}}`

### 5.6 `error` (v1)

```json
{"code": "locked", "message": "Another program holds the file locked. Try again shortly.",
 "exception": "LockedFileError", "retryable": true, "detail": {}, "reader_message": null}
```

- `message` is a fixed text per code, identical on every surface. A few rules
  have their own (`detail.rule`): `route` (an unknown REST route),
  `not_a_folder` (a file listed as a folder), `no_workers` (health with no
  worker running), `catalog_locked`, `catalog_scanning` and `no_free_worker`
  (`busy` from a catalog; the last a scan's read that found no worker free in
  a shared pool), and `not_a_catalog`, `too_new`, `damaged` and
  `unexpected_schema` (`catalog_incompatible`), `no_reader` (`format_not_supported`: a format
  SolidSeas knows but cannot read yet) and `model_file` (`not_implemented`: an
  operation for SOLIDWORKS documents asked of another 3D file). A `timeout`
  from a worker pool that had no worker free before the deadline carries the
  rule `no_free_worker` with the code's own message.
- `detail` holds only structured, safe facts, under these keys: `stream`,
  `parameter`, `rule`, `component_index`, `limit`, `value`, `usage`.
- `reader_message` is the exception's own text. It can contain an absolute
  path, so the REST service always sends null; the CLI and Python fill it.
- `retryable` is true where waiting can help.

| Code | HTTP | CLI exit | Retryable |
|---|---|---|---|
| `invalid_argument`, `unknown_parameter`, `duplicate_parameter` | 400 | 2 | no |
| `unauthorized` | 401 | | no |
| `forbidden_host`, `forbidden_origin` | 403 | | no |
| `path_refused`, `link_refused`, `feature_disabled` | 403 | 3 | no |
| `permission_denied` | 403 | 1 | no |
| `output_refused`, `bind_refused`, `token_file_refused` | | 3 | no |
| `address_unavailable` | | 1 | no |
| `nothing_to_export`, `not_representable` | | 1 | no |
| `not_found`, `configuration_not_found`, `stream_not_found`, `no_preview` | 404 | 1 | no |
| `root_not_found` | 404 | | no |
| `not_in_catalog` | 404 | 1 | no |
| `method_not_allowed` | 405 | | no |
| `uri_too_long` | 414 | | no |
| `placeholder_file` | 409 | 1 | no |
| `catalog_incompatible` | 409 | 3 | no |
| `unknown_format`, `format_not_supported`, `damaged_file`, `limit_exceeded`, `file_too_large` | 422 | 1 | no |
| `response_too_large`, `quarantined` | 422 | | no |
| `locked` | 423 | 1 | yes |
| `too_many_failures` | 429 | | yes |
| `headers_too_large` | 431 | | no |
| `internal`, `worker_crashed` | 500 | 1 | no |
| `not_implemented` | 501 | 1 | no |
| `busy`, `root_unavailable` | 503, with `Retry-After` | 1 | yes |
| `timeout` | 504 | 1 | no |
| `interrupted` | | 130 | no |
| `drawing_invalid`, `drawing_too_complex`, `model_not_found` | | 1 | no |
| `drawing_released` | | 3 | no |

The four drawing codes (`docs/DRAWINGS.md` 14, provisional) come only from the
library and the command line (`solidseas drawing`, `docs/drawings/cli.md`); the
service has no drawing route yet. `drawing_invalid`: a `.ssdrw` that is not a
SolidSeas drawing this version reads. `drawing_too_complex`: a part or drawing
past a bound of `DrawingLimits` (`detail.limit` names it). `model_not_found`:
the drawing's model is not where the drawing says, or only files changed since
the drawing was made were found. `drawing_released`: a RELEASED drawing refuses
a change until a revision is started; exit 3, as a refusal.

A test derives this table from `solidseas.model.ERROR_CODES`. Section 7.2 lists
the same exit codes by exit.

### 5.7 `listing` (v1) and its entries

```json
{"root": null, "folder": "", "recursive": false, "include": ["properties", "preview"],
 "entries": [{"path": "bracket.SLDPRT", "type": "file", "status": "ok", "reason": null, "detected": null,
              "file": {"name": "bracket.SLDPRT", "size": 144400,
                       "modified_utc": "2026-09-30T14:02:11.123456Z", "mtime_ns": "1790292487123456789"},
              "format": "modern", "doc_type": "part", "saved_version": {},
              "active_configuration": "Default", "configurations": null, "properties": [],
              "preview": {"available": true, "reason": null, "mime": "image/png", "width": 640, "height": 480,
                          "bytes": 27570, "stream": "PreviewPNG", "sha256": "...", "data_base64": null},
              "warnings": [], "error": null, "model": null},
             {"path": "fixtures", "type": "folder", "status": "ok", "reason": null, "detected": null,
              "file": null, "format": null, "doc_type": null, "saved_version": null,
              "active_configuration": null, "configurations": null, "properties": null, "preview": null,
              "warnings": [], "error": null, "model": null}],
 "counts": {"entries": 2, "ok": 2, "error": 0, "skipped": 0, "link": 0, "placeholder": 0,
            "not_solidworks": 0, "unsupported": 0, "folders": 1},
 "truncated": false, "truncated_reason": null, "next_cursor": null, "preview_data_capped": false}
```

(`saved_version` is shortened here; it is the summary's object.)

| Field | Meaning |
|---|---|
| `root` | The root id (C1). Null from Python and the CLI, which list a folder they were given |
| `folder` | The listed folder relative to the root; `""` for the folder itself |
| `recursive`, `include` | As requested; `include` in its canonical order |
| `counts` | `entries`, one count per status, and `folders`, the folders the walk listed |
| `truncated`, `truncated_reason` | Whether a limit stopped the listing early: `max_entries`, `max_examined` or `deadline` |
| `next_cursor` | Null from Python and the CLI. A REST listing page that stopped at its `limit` or its deadline gives the cursor for the next page (8.6) |
| `preview_data_capped` | True when inline image data reached its limit; the remaining entries keep their preview metadata and `data_base64` is null |

**Entry fields:**

| Field | Meaning |
|---|---|
| `path` | Relative to the listed folder, `/`-separated, in the on-disk spelling (root-relative from REST, C1) |
| `type` | `file` or `folder`. Folders are entries when the listing is not recursive, and when they are links, placeholders, unreadable or beyond `max_depth`. On Linux and macOS a symbolic link does not record what it leads to, so every symbolic link is an entry, of type `file` |
| `status` | `ok`, `error`, `skipped` (a SOLIDWORKS `~$` lock file, a FIFO, socket or device, or a folder beyond `max_depth`), `link` (a link or mount point, never followed), `placeholder` (a cloud file or folder, never opened), `not_solidworks` or `unsupported` (a 3D format SolidSeas lists but cannot read yet, listed with `formats`; never opened). An open set |
| `reason` | A token for `skipped` (`lock_file`, `max_depth`, `not_regular_file`), `link` (`junction`, `symlink`, `name_surrogate`, `unreported_tag`, `mount_point`) and `placeholder` (`recall_on_data_access`, `recall_on_open`, `offline`); else null. An open set |
| `detected` | For `not_solidworks`, what the file is instead: `step` for a STEP file wearing a SOLIDWORKS extension (`ISO-10303` after any leading whitespace); for `unsupported`, the format id; else null |
| `file` | The summary's `file` object: from the open handle when the file was read, from the directory listing otherwise (a placeholder keeps its size). Null for folders and links |
| `format`, `doc_type`, `saved_version`, `active_configuration` | The summary's values; null when the file was not read |
| `configurations` | Configuration objects when requested, else null |
| `properties` | The effective properties of the active configuration when requested, else null |
| `preview` | The summary's `preview` object plus `data_base64` (the image, only with `preview_data`); null when not requested or not read. A file with no stored preview has `available: false` and `reason: "not_stored"` |
| `warnings` | The summary's warnings for that file |
| `error` | The error object for an entry that failed, else null. A locked file has code `locked` and `retryable: true`: list it again later. A file that became a link or a placeholder after its folder was listed has `link_refused` or `placeholder_file` |
| `model` | Provisional. Null for SOLIDWORKS documents, folders and anything not read; for a model file (3.20) `{"format", "format_name", "variant", "kind", "readable", "units", "counts", "application", "preview_renderable"}`: the registry id and name, the variant, `mesh`, `brep` or `mixed`, whether SolidSeas reads the format, and the head's units, counts and writing program as `model_summary` gives them (5.16; null for an `unsupported` entry); `preview_renderable` says a preview can be rendered from the model (3.21) |

A model file's entry (status `ok`) has `format`, `saved_version` and
`configurations` null (they describe SOLIDWORKS containers; `configurations`
is `[]` when requested), its `doc_type`, `active_configuration`, file-scope
`properties` when requested, and in `preview` the image the file stores as a
PNG that SolidSeas wrote itself (3.20.1): `mime` `image/png`, and `bytes` and
`sha256` of that PNG. A file that stores none has `available: false`; the
viewer renders one afterwards.

Only SOLIDWORKS documents (`.sldprt`, `.sldasm`, `.slddrw`) and folders are
entries, unless `formats` names other formats (3.6); other files are not
listed. One bad file never stops a listing: its
entry carries the error and the walk goes on.

A test checks, for each of the fixtures o01 to o08, that each shared field of
an entry equals the same field of the document's summary. Since none of them
has a reader warning or an active configuration with properties of its own, crafted
files check the rest: an entry's `properties` are the active configuration's
effective ones while the summary keeps the file-level ones, and an entry
carries the summary's warnings. On the development corpus, every entry equals
a whole-file read of the same document for all 3,501 documents the corpus
manifest marks readable (of its 3,527; the other 26 were locked when the
manifest was made).

### 5.8 Command results

The CLI prints these kinds under `--json`; Python callers have the objects
they describe.

- `streams`: `{"format", "streams": [{"name", "size", "compressed_size",
  "codec"}]}`. Names are exact, so a legacy property set keeps its leading
  `\u0005`.
- `file_written` (`dump`, `preview`): `{"output", "bytes", "stream", "raw",
  "mime", "width", "height", "source"}`. `output` is the absolute path written;
  fields a command does not set are null. `source` (provisional) says where a
  preview came from: `stored` in the file, or `rendered` from a model file's
  geometry (3.21); null for `dump`.
- `parasolid_result`: `{"bodies", "written", "problems"}`. Each written file is
  `{"output", "kind", "bytes", "body", "configuration", "configuration_id",
  "source", "body_type", "schema", "valid", "transmit"}` (`kind` is `x_b`,
  `x_t`, `p_b` or `d_b`); each problem is `{"stream", "block", "feature",
  "error"}`. A document without bodies gives `bodies: 0`, which is a result,
  not an error.
- `batch_summary`: `{"files", "status_counts", "report_csv", "report_jsonl",
  "previews", "parasolid_files", "walk"}`, where `walk` holds the walker's
  counts (section 3.7). Row statuses are `ok`, `error`, `locked`, `refused`,
  `skipped` (a lock file, or a FIFO, socket or device), `placeholder` and
  `link` (a link or mount point). A placeholder or link row is never opened.

### 5.9 `components` and `references` (v1)

`components` is one assembly configuration's component tree; `references` is
every file a document references, across all its configurations. Both use
the same component file object, keyed by the `swFile` id (C7). Section 3.9
says what the stored values mean.

```json
{"configuration": "Default", "configuration_source": "active", "configurations_described": ["Default", "Lite"],
 "children_state": "described", "truncated": false, "limits": {"max_nodes": 10000, "max_depth": 32},
 "counts": {"nodes": 1, "depth": 1, "files": 1},
 "files": [{"key": "6", "stored_path": "D:\\Jobs\\Example\\bracket.SLDPRT", "file_name": "bracket.SLDPRT",
            "doc_type": "part", "direct": true, "virtual": false, "imported": false, "nested": null,
            "embedded": null, "embedded_in_subassembly": false, "configurations_used": ["Default"],
            "instances": 1, "instances_unsuppressed": 1, "instances_in_bom": 1, "per_configuration": null,
            "sources": ["swXmlContents/COMPINSTANCETREE", "Header2"], "resolution": null}],
 "children": [{"id": "bracket-2", "parent": null, "name": "bracket-2", "component": "bracket", "number": 2,
               "depth": 1, "file": "6", "doc_type": "part", "configuration": "Default", "suppressed": false,
               "hidden": false, "excluded_from_bom": false, "virtual": false,
               "transform": {"stored": [0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1, 0, 0.1, 0, 0, 1],
                             "rotation": [[0, -1, 0], [1, 0, 0], [0, 0, 1]], "translation_m": [0.1, 0, 0],
                             "scale": 1},
               "placement": {"rotation": [[0, -1, 0], [1, 0, 0], [0, 0, 1]], "translation_m": [0.1, 0, 0]},
               "children_state": "none", "children": []}],
 "instances": null,
 "warnings": []}
```

The instance is turned 90 degrees about Z (its X axis lies along the
assembly's Y axis) and moved 0.1 m along X. Numbers are written as integers
here for brevity; the JSON carries them as floats.

**The `components` kind:**

| Field | Meaning |
|---|---|
| `configuration` | The configuration described; null for a part or a drawing |
| `configuration_source` | How it was chosen: `requested`, `active`, `most_recent`, `first` or `none` |
| `configurations_described` | Every configuration the tree has a component list for, in stored order |
| `children_state` | `described`; `unknown` when the file has no component tree (`files` then come from `Header2`) or none for this configuration; `none` for a part or a drawing |
| `truncated`, `limits` | Whether `max_nodes` or `max_depth` cut the tree, and the limits used |
| `counts` | `nodes` (instances described), `depth` (deepest level) and `files` |
| `files` | The files the described instances use, in first-seen order |
| `children` | The top-level instances, each with its own `children`; null with `flat` |
| `instances` | With `flat`: every instance depth first, each with `children` null; else null |
| `warnings` | Warning objects (C8), including reader warnings about the tree and `Header2` |

**Component file**, one per referenced document:

| Field | Meaning |
|---|---|
| `key` | The file key (C7): the `swFile` id, or `header2:<n>` |
| `stored_path` | The path stored at the last save, Windows form, as stored |
| `file_name` | The last component of `stored_path` |
| `doc_type` | `part`, `assembly` or null, from `swDocType`; null when only `Header2` names the file |
| `direct` | True when the top document uses it directly, false only inside sub-assemblies, null when unknown (`Header2` only, and drawings, provisionally) |
| `virtual` | Stored inside an assembly rather than as its own file |
| `imported` | Carries `swImportedPath` |
| `nested` | The nested-document stream in this file that holds it (3.9), or null. Pass it as `nested` to read that document |
| `embedded` | `embedded` (found in `nested`), `embedded_not_found` (a direct virtual file whose stream is not there), `embedded_in_subassembly`, or null for a file stored on its own. An open set. Neither embedded status claims a location on disk |
| `embedded_in_subassembly` | A virtual file stored inside a sub-assembly's own file rather than this one |
| `configurations_used` | Configurations of this file that instances use, in first-seen order. In `components`, within the described configuration; in `references`, across all; for a drawing, the configurations its views show |
| `instances`, `instances_unsuppressed`, `instances_in_bom` | Counts in the described configuration, expanded through sub-assemblies. Unsuppressed means no suppressed instance on the way; in BOM also means nothing on the way is excluded from the BOM. Null when unknown (no component tree, and drawings). A count, not a BOM: the `bom` kind (3.16, 5.13; `/v1/bom?type=parts` or `type=indented`) groups and numbers the rows as SOLIDWORKS does |
| `per_configuration` | In `references`: `{configuration, instances, instances_unsuppressed, instances_in_bom}` for every configuration the tree describes. Null in `components` |
| `sources` | Streams the file was found in |
| `resolution` | Null unless resolution was requested; then a resolution result (5.10) |

**Component instance:**

| Field | Meaning |
|---|---|
| `id` | Instance names from the top joined by `/`. `%`, `/` and `#` inside a name are percent-encoded, and a name repeated under one parent (never seen on the corpus) gets `#2`, `#3`... with the warning `duplicate_instance_name`. Unique in the tree |
| `parent` | The parent instance's `id`, or null at the top |
| `name`, `component`, `number` | `bracket-2`, `bracket`, 2 (`number` null when not a number) |
| `depth` | 1 for an instance of the top assembly |
| `file` | Key into `files`, or null |
| `doc_type` | `part`, `assembly` or null |
| `configuration` | The configuration of the component file this instance uses |
| `suppressed`, `excluded_from_bom`, `virtual` | Flags as stored on this instance |
| `hidden` | What SOLIDWORKS reports as hidden (3.9); a suppressed part instance is not hidden unless its display state says so, and a sub-assembly instance follows `swHidden` |
| `transform` | The stored transform, relative to the parent instance: `stored` (16 numbers), `rotation` (3 x 3, row by row), `translation_m` and `scale`. Null with the warning `transform_unreadable` when the stored text is not 16 finite numbers |
| `placement` | `{rotation, translation_m}` in the top assembly's frame: the parents' transforms composed with this one. Null when a transform on the way is null |
| `children_state` | `none` (a part), `described`, `truncated` (a limit stopped here), `cycle` (the model is already on the path) or `unknown` (the tree names a model it does not hold). An open set |
| `children` | Child instances, or null in the flat form |

**The `references` kind** is `{"configuration", "configuration_source",
"configurations_described", "children_state", "truncated", "files",
"sheets", "resolution", "warnings"}`:

- For an assembly, `files` holds every `swFile` an instance uses, in stored
  order, with the counts of `configuration` (the active one unless another
  is requested; a file not used there counts 0) and `per_configuration`.
  An assembly without a tree lists its `Header2` files with null counts.
- For a drawing, `files` are its models from `Header2` (`direct` null,
  provisionally), `configuration` is null, `children_state` is `none` and
  `sheets` lists `{"name", "views": [{"name", "configuration", "file_name",
  "file"}]}`: each sheet in order, and each view with the model
  configuration it shows, the model's file name as the drawing stores it and
  that model's key (null when no `Header2` path has that name).
- For a part, `files` is empty and `sheets` null.
- `resolution` is null unless resolution was requested (5.10); each file's
  `resolution` is then its resolution result, and the kind's `resolution`
  summarises the search.

### 5.10 Resolution results (in `references`)

`solidseas references FILE --resolve` and `build_references(doc,
resolution=...)` fill each file's `resolution` with one result, and the
kind's top-level `resolution` with a summary. The schema version of
`references` stays 1: both fields existed as null. Section 3.10 describes the
rules.

```json
{"key": "6",
 "status": "moved",
 "stored_path": "D:\\Jobs\\Old\\bracket.SLDPRT",
 "match": {"root": "jobs", "path": "Example/bracket.SLDPRT"},
 "rule": "rebased",
 "confidence": "high",
 "identity": "match",
 "nested": null,
 "candidates": [{"root": null, "path": "D:\\Jobs\\Old\\bracket.SLDPRT", "found_by": "stored_path",
                 "identity": "match", "placeholder": false}],
 "warnings": [{"code": "stored_path_also_exists", "stream": null,
               "message": "another file still exists at the stored path"}]}
```

| Field | Meaning |
|---|---|
| `key` | The file key (C7). The result has no quantity or instances (C9) |
| `status` | `resolved` (the stored path, after the path map), `moved` (another path), `embedded` (a virtual or imported component stored as a nested document), `embedded_not_found` (a virtual file whose stream is not there), `embedded_in_subassembly` (a virtual file stored inside a sub-assembly's own file), `ambiguous` or `missing`. An open set |
| `stored_path` | As stored |
| `match` | `{"root", "path"}` (C1): a root id and the path below it, `/`-separated, in the on-disk spelling; `root` is null and `path` absolute for a file outside every root (CLI and Python only). Null unless the status is `resolved` or `moved` |
| `rule` | The rule that chose: `embedded`, `stored_unmoved`, `path_map`, `rebased`, `same_folder`, `suffix_probe`, `stored_path`, `name_index` or `name_index_suffix`; null when nothing was chosen. An open set |
| `confidence` | `high`, `medium`, `low` or `none`, from the rule's measured precision and the identity check (3.10) |
| `identity` | `match`, `differ` or `unknown`: the stored creation time against the file's own |
| `nested` | The nested stream for `embedded`, else null |
| `candidates` | At most 20 other files the rules looked at, each `{"root", "path", "found_by", "identity", "placeholder"}`: for `ambiguous` the files it could not choose between, otherwise files set aside (an identity that differs, another copy, the stored path when another file was chosen) |
| `warnings` | `{code, stream, message}` objects (C8), `stream` null |

| Rule | Identity match | Identity unknown |
|---|---|---|
| `embedded`, `stored_unmoved`, `path_map`, `rebased` | high | medium |
| `same_folder`, `suffix_probe`, `name_index` (one candidate) | high | low |
| `stored_path` | medium | low |
| `name_index_suffix` | low | low |
| A file kept although its identity differs (warning `identity_mismatch`) | low | |
| `ambiguous`, `missing`, `embedded_not_found`, `embedded_in_subassembly` | none | none |

Resolution warning codes (an open set):

| Code | Meaning |
|---|---|
| `identity_mismatch` | The file chosen has another creation time than the stored one |
| `stored_path_also_exists` | Another file still exists at the stored path (a copied project); it is among the candidates |
| `case_differs` | The file's name differs from the stored name only by case |
| `normalization_differs` | The name matches only after Unicode normalisation |
| `stored_unc_not_checked` | The stored path is on a network share and was never touched |
| `stored_network_drive_not_checked` | The stored path is on a mapped network drive and was never touched |
| `stored_path_refused` | The stored path is not used as a location (3.10) |
| `outside_roots` | The file chosen is outside every root |
| `index_partial` | A limit cut a root's folder index short |
| `root_unavailable` | A root could not be walked (gone, or access denied) and was searched without; its files are not among the candidates (REST, and `skip_unavailable_roots`) |
| `search_incomplete` | A limit stopped the search, or the identity reads, before they were complete |
| `placeholder_not_read` | A cloud placeholder was found and deliberately not opened |
| `identity_read_failed` | A file could not be read to check its identity |
| `from_parent_tree` | A sub-assembly's file, resolved from the path the top document stored (C7) |
| `context_varies` | The file is used by more than one parent document (C7) |

The summary, `references.resolution`:

```json
{"roots": [{"id": "jobs", "role": "project", "recursive": true, "index_partial": false,
            "truncated_reason": null}],
 "index_partial": false, "outside_roots": true, "truncated": false,
 "counts": {"resolved": 4, "moved": 2, "embedded": 1, "embedded_not_found": 0,
            "embedded_in_subassembly": 0, "ambiguous": 0, "missing": 1}}
```

`roots` lists the roots searched, in order, with `truncated_reason`
(`max_examined`, `deadline` or `max_depth`) when a limit cut that root's index
short, or `unavailable` (with `index_partial` true) for a root that could not
be walked at all. `outside_roots` says whether point lookups outside the roots were
allowed; `truncated` that the document has more than 100,000 referenced files
and only the first were resolved. `counts` has one entry per status (an open
set).

### 5.11 `path_report` (v1)

The paths and names a document, and every nested document in it, would reveal
to whoever receives it (section 3.12). Paths are sorted by severity, then
category, then path.

```json
{"complete": true, "incomplete": [],
 "counts": {"paths": 2, "accounts": 1, "hosts": 1, "identity_fields": 2, "documents": 2,
            "by_category": {"unc": 1, "project": 0, "profile": 0, "desktop": 0, "temp": 1,
                            "program": 0, "windows": 0, "drive_root": 0},
            "by_role": {"references": 1, "imported_from": 0, "save_location": 0, "resources": 0,
                        "history": 1, "other": 0}},
 "documents": [{"nested": [], "doc_type": "assembly", "streams": 41, "streams_scanned": 40,
                "bytes_scanned": 512000},
               {"nested": ["VirtualComp/Part1-sldprt"], "doc_type": "part", "streams": 38,
                "streams_scanned": 38, "bytes_scanned": 230000}],
 "accounts": [{"name": "example", "severity": "medium", "sources": ["path", "core_last_modified_by"],
               "paths": 1, "identity_fields": 1, "history_only": true, "inherited_likely": false}],
 "hosts": [{"host": "fs01", "shares": ["eng"], "severity": "high", "paths": 1}],
 "identity_fields": [{"field": "core_last_modified_by", "value": "example", "current": true,
                      "nested": [], "stream": "docProps/core.xml"},
                     {"field": "file_name_at_save", "value": "frame", "current": true,
                      "nested": [], "stream": "docProps/ISolidWorksInformation.xml"}],
 "paths": [{"path": "\\\\fs01\\eng\\Example\\bracket.SLDPRT", "category": "unc", "severity": "high",
            "reason": "unc_share", "account": null, "host": "fs01", "share": "eng",
            "roles": ["references"], "sources": ["tree", "header2", "model_header", "scan"],
            "locations": [{"nested": [], "stream": "swXmlContents/COMPINSTANCETREE"},
                          {"nested": [], "stream": "Header2"},
                          {"nested": [], "stream": "Contents/Config-0-ModelHeader"}],
            "history_only": false, "inherited_likely": false},
           {"path": "C:\\Users\\example\\AppData\\Local\\Temp\\", "category": "temp",
            "severity": "medium", "reason": "account_name", "account": "example", "host": null,
            "share": null, "roles": ["history"], "sources": ["biography"],
            "locations": [{"nested": ["VirtualComp/Part1-sldprt"], "stream": "_MO_VERSION_17000/Biography"}],
            "history_only": true, "inherited_likely": false}],
 "rewrite": {"supported": false,
             "note": "SolidSeas never rewrites files. Removing these values means saving a new document in SOLIDWORKS or sending a neutral format."},
 "warnings": []}
```

- `counts.by_category` and `counts.by_role` always hold every category and
  role in this order, with zeros; both are open sets.
- `documents` lists each document read: the file itself first, then each
  nested document, depth first, with its nested chain.
- `identity_fields[].field` is `header2_user`, `core_last_modified_by`,
  `core_creator`, `sw_author`, `sw_last_saved_by`, `summary_author`,
  `summary_last_author` or `file_name_at_save` (an open set); all but the last
  are user names and feed `accounts`.
- `incomplete[]` is `{"reason", "nested", "stream"}`; `reason` is one of the
  section 3.12 completeness reasons (an open set). The CLI exits 4 when
  `complete` is false.
- `warnings` holds the reader warnings about the document's own identity
  carriers.

### 5.12 Service kinds: `health`, `identity`, `roots` and `serve_started` (v1)

- `health` (`/v1/health`): `{"status": "ok"}` and nothing else, because it
  answers without a token. While no worker process is
  running (every worker lost, and no replacement started yet) it answers 503
  `busy` with `detail.rule` `no_workers` and `Retry-After` instead, so a
  monitor sees that the service cannot read anything.
- `identity` (`/v1/identity`, 8.16): the proof a client checks before it sends
  its token. It needs no token either.

  ```json
  {"scheme": "solidseas-identity-v1", "client": "erp",
   "nonce": "-8h1vVrkx4EHoqyRSEmKW5Zn7BiBj8YLNk35QCrAb2o", "address": "127.0.0.1",
   "port": 8765, "proof": "<64 lowercase hex digits>"}
  ```

  `scheme` names how `proof` is computed (an open set: a later scheme would
  get a new name); `client` and `nonce` are the query's; `address` and `port`
  are the service's side of the connection that asked.
- `roots` (`/v1/roots`): each configured root by its id, never by its folder:

  ```json
  {"roots": [{"id": "jobs", "role": "project", "recursive": true, "state": "ready",
              "index_partial": false, "documents": 3527}]}
  ```

  `state` is `building`, `ready` or `unavailable` (an open set);
  `index_partial` is true when a limit cut the root's folder index short;
  `documents` counts the SOLIDWORKS documents in the index, null until it is
  built.
- `serve_started` (the line `solidseas serve --json` prints when it is ready):

  ```json
  {"host": "127.0.0.1", "port": 8765, "url": "http://127.0.0.1:8765/v1/", "roots": ["jobs"],
   "workers": 4, "auth": "bearer", "token_file_created": false}
  ```

  `url` is the base of every route. The token itself is never printed.

### 5.13 `bom` (v1, provisional)

A bill of materials of one assembly configuration (section 3.16). Two rows of an
indented BOM, each with one of its properties:

```json
{"type": "indented", "configuration": "Default", "configuration_source": "active",
 "children_state": "described",
 "columns": ["ITEM NO.", "PART NUMBER", "DESCRIPTION", "QTY.", "PartNo"],
 "property_columns": ["PartNo"], "part_number_property": null, "read_properties": true,
 "rows": [{"item": "2", "level": 0, "parent": null, "part_number": "bracket",
           "part_number_source": "document_name", "alternate_name": null,
           "description": "Mounting bracket",
           "quantity": 1, "total_quantity": 1, "file": "11", "file_name": "bracket.SLDPRT",
           "stored_path": "D:\\Jobs\\Example\\bracket.SLDPRT", "doc_type": "part",
           "configuration": "Long", "virtual": false, "imported": false,
           "instances": ["bracket-1"], "resolution": "resolved",
           "location": {"root": "jobs", "path": "Example/bracket.SLDPRT"}, "nested": [],
           "properties": [{"name": "PartNo", "scope": "file", "configuration": null, "type": "text",
                           "value": "PN-123", "date": null, "text": "PN-123",
                           "expression": "PN-123", "linked": false}],
           "values": ["PN-123"], "notes": []},
          {"item": "3.1", "level": 1, "parent": "3", "part_number": "plate",
           "part_number_source": "document_name", "alternate_name": null,
           "description": null, "quantity": 2,
           "total_quantity": 4, "file": "6", "file_name": "plate.SLDPRT",
           "stored_path": "D:\\Jobs\\Example\\plate.SLDPRT", "doc_type": "part",
           "configuration": "Default", "virtual": false, "imported": false,
           "instances": ["frame-1/plate-1", "frame-1/plate-2", "frame-2/plate-1", "frame-2/plate-2"],
           "resolution": "missing", "location": null, "nested": [], "properties": null,
           "values": [null],
           "notes": [{"code": "bom_properties_unread", "stream": null,
                      "message": "its file's properties are unknown: its file was not found; the row keeps what the assembly stores"}]}],
 "truncated": false, "complete": false,
 "counts": {"rows": 9, "instances": 12, "files": 7, "read": 8, "unread": 1, "files_opened": 6},
 "limits": {"max_instances": 10000, "max_depth": 32, "max_files": 2000, "max_seconds": 60.0,
            "max_file_bytes": null},
 "resolution": {"roots": [{"id": "jobs", "role": "project", "recursive": true,
                           "index_partial": false, "truncated_reason": null}],
                "index_partial": false, "outside_roots": true, "truncated": false,
                "counts": {"resolved": 5, "moved": 0, "embedded": 1, "embedded_not_found": 0,
                           "embedded_in_subassembly": 0, "ambiguous": 0, "missing": 1}},
 "warnings": []}
```

- `columns` is the table's header: the four SOLIDWORKS columns, then
  `property_columns`. `table_cells` (3.16) turns `type`, `property_columns` and
  `rows` into the table's text cells.
- Rows come in table order. `item` is text (`3.1`); `parent` is the item of the
  row above in an indented BOM, null at level 0 and in the other types.
  `quantity` is per one instance of the parent, `total_quantity` in the whole
  assembly.
- `file` is the file key of the component tree and the `references` kind (C7);
  `stored_path` the path the assembly stored. `location` is where the file
  read was found (C1), null for a document stored in the assembly itself and
  for a file not found; `nested` lists the nested-document streams followed
  from there. `resolution` is the file's status (5.10), or `embedded`,
  `embedded_in_subassembly` or `embedded_not_found`.
- `properties` are the file's effective properties in the row's configuration
  (5.3), null when the file was not read; `values` holds one text per property
  column, null where the property is absent or unread; `description` is `""`
  when the file has no `Description` and null when it was not read.
- `alternate_name` is the alternate name the assembly stores for the row's
  configuration, which SOLIDWORKS may show as the part number, null when it
  stores none; a row where it differs from `part_number` carries the note
  `bom_part_number_may_differ` (3.16).
- `notes` are the row's warnings (`bom_properties_unread`,
  `bom_configuration_missing`, `bom_configurations_unknown`,
  `bom_children_missing`, `bom_children_differ`,
  `bom_part_number_may_differ`); `warnings` the tree's, and
  `bom_limit_reached`.
- `complete` is false when anything is missing or in doubt (3.16); the CLI then
  exits 4.
  `limits` is null for a part or a drawing, which have no rows and
  `children_state` `none`. `resolution` is null when no file was looked for
  (`read_properties` false).
- The `bom` kind and route are provisional while BOMs are new: their fields may
  still change, with a note in `CHANGELOG.md`.

### 5.14 `export_result` (v1, provisional)

What `solidseas export --json` wrote (3.17). Lengths are in millimetres.

```json
{"output": "D:\\Prints\\frame.3mf", "format": "3mf", "mime": "model/3mf", "bytes": 1486,
 "merged": false, "name": "frame", "doc_type": "assembly", "configuration": "Default",
 "chord_mm": null, "closed": true,
 "counts": {"objects": 6, "items": 12, "vertices": 48, "triangles": 144, "parts": 13,
            "placed": 12, "skipped": 0, "suppressed": 1, "hidden": 0},
 "objects": [{"name": "bracket", "file": "3", "configuration": "Default", "source": "bodies",
              "vertices": 8, "triangles": 12, "instances": 4, "closed": true, "chord_mm": 0.0094,
              "volume_mm3": 6000.0, "area_mm2": 2200.0, "warnings": []}],
 "skipped": [], "warnings": [], "seconds": 0.051, "step": null, "source_format": "solidworks"}
```

- `source_format` is the registry id of the file exported (3.20.3):
  `solidworks`, `stl`, `3mf`, `step`... (an open set).
- `chord_mm` at the top is the tolerance asked for (null: each part's
  automatic print chord), and each object's the one it was made at (null for
  a display mesh). `merged` is true for STL and for `--merge`.
- `source` is `bodies`, `display_mesh` or `mesh` (a mesh file's own
  triangles) and `doc_type` `part` or `assembly` (open sets). `instances` counts the build items that place the object.
- `skipped` lists the instances left out (`id`, `name`, `file`, `reason`,
  `message`, at most 1,000; `counts.skipped` counts them all), with the
  reasons of 3.14, `out_of_range` and `surfaces_only`.
- `counts` has the assembly keys only for an assembly.
- `step` is null for 3MF and STL. For a STEP export (3.19) it holds the
  export's own results, `objects` is empty, `chord_mm` null, `merged` false,
  `mime` `model/step`, and `counts` has `products`, `instances`, `bodies`
  (written), `solids`, `sheets`, `faces`, `edges`, `vertices` (as written),
  `split_faces`, `edges_added`, `entities` and `bodies_left_out`:

```json
"step": {"schema": "AP214", "exact": true, "partial": false, "uncertainty_mm": 1e-05,
         "max_deviation_mm": null, "max_tolerance_mm": null, "max_gap_mm": null,
         "approximated": {"faces": 0, "edges": 0, "by_class": {}},
         "bodies": [{"product": 0, "name": "Fillet2", "configuration": "Default", "kind": "solid",
                     "source": "partition", "faces": 14, "edges": 34, "vertices": 22,
                     "split_faces": 2, "approximated_faces": 0, "approximated_edges": 0,
                     "max_deviation_mm": null, "max_tolerance_mm": null, "written": true,
                     "reason": null, "message": null}]}
```

  `bodies` lists every body of the configuration (at most 1,000), written or
  not; `split_faces` counts its faces written as two, cut at their seams; a body
  not written has `reason` (the codes of 3.19: `hidden` for a body SOLIDWORKS
  hides, `not_asked` for a sheet when sheets were not asked for and
  `unsupported_body` for a wire body, all left out without refusing the export,
  or the reason it was refused) and `message`. `by_class` counts the faces and edges approximated by the
  Parasolid class they replace. The top-level `closed` of a STEP export is
  `StepModel.closed`: true when the file holds a solid (every solid written is
  closed), false for a file of sheets only.

### 5.15 The catalog's kinds (v1, provisional)

Section 3.18 says what each holds and how it is worked out; the schemas
(`solidseas schema KIND`) give every field. Locations are always a root id and a
path below it. Every file an answer names (the `where_used` target, its users,
`possible` and `name_matches`, a search result, a document with missing
references) carries `doc_type` and `format`: the format id it was read as
(`solidworks` for a SOLIDWORKS document), else the one its extension names.

- **`catalog`** (`catalog`, `/v1/catalog`): `name`, `location` (`cache`,
  `project` or `file`), `schema_version`, `state` (`empty`, `scanning`, `ready`
  or `partial`), `search_engine` (`fts5` or `like`), `hash_policy`,
  `part_number_property`, `formats` (the format ids it indexes), `last_scan` (`id`, `started_utc`, `finished_utc`,
  `state`; `failed` for a scan whose writer died), `roots` (`id`, `path` (null
  from REST), `role`, `recursive`, `state`, `partial`, `hash_policy` (what its
  last scan hashed), `last_scan_utc`, `last_complete_scan_utc`, `documents`,
  `files`), `counts` (files, documents, `formats` (documents read, by format
  id), parts, assemblies, drawings, pending,
  read errors, quarantined, not SOLIDWORKS, placeholders, stale, waiting to be
  resolved, waiting to be hashed, references by status, unresolved references,
  duplicate groups) and `sizes` (`catalog_bytes`, `previews_bytes`).
- **`catalog_list`** (`catalogs`): `cache_dir` and every catalog in it, with
  its roots, last scan, sizes and `error` (an error code, for one that cannot be
  read).
- **`catalog_cleared`** (`clear-index`): the names of the `catalogs` deleted
  and the `files` that went with them.
- **`catalog_scan`** (`index`): `catalog`, `scan` (its id), `state` (`done`,
  `cancelled`, `truncated` or `failed`), `roots` (`id`, `state`, `entries`
  walked, `documents`, `truncated_reason`), `removed_roots`, `counts` (`seen`,
  `added`, `changed`, `unchanged`, `moved`, `removed`, `stale`, `read_ok`,
  `read_errors`, `not_solidworks`, `pending`, `hashed`, `hash_pending`,
  `resolved_documents`), `seconds` per phase and in all, the first 100 `errors`
  (`root`, `path`, an error object), `truncated`, `truncated_reason` and
  `cancelled`.
- **`where_used`** (`where-used`, `/v1/where-used`):

  ```json
  {"target": {"root": "project", "path": "o02_boxA.SLDPRT", "name": "o02_boxA.SLDPRT",
              "doc_type": "part", "format": "solidworks", "state": "ok", "configurations": ["Default"],
              "sha256": "..."},
   "configuration": null, "indirect": true, "as_of": "2026-10-03T21:03:37Z", "complete": true,
   "users": [
     {"root": "project", "path": "o16_asm_features.SLDASM", "name": "o16_asm_features.SLDASM",
      "doc_type": "assembly", "format": "solidworks", "depth": 2, "relation": "component",
      "via": [{"root": "project", "path": "o15_sub_asm.SLDASM", "name": "o15_sub_asm.SLDASM", "stored": false}],
      "uses": [{"user_configuration": "Default", "configuration": "Default", "via_configurations": ["Default"],
                "instances": 1, "unsuppressed": 1, "in_bom": 1},
               {"user_configuration": "Lite", "configuration": "Default", "via_configurations": ["Default"],
                "instances": 1, "unsuppressed": 0, "in_bom": 0}],
      "views": [], "resolution": {"key": "14", "status": "moved", "rule": "rebased",
                                  "confidence": "high", "identity": "match"},
      "warnings": []}],
   "possible": [], "name_matches": [],
   "counts": {"users": 5, "direct": 3, "indirect": 1, "drawings": 2, "possible": 0, "name_matches": 0},
   "truncated": false, "warnings": []}
  ```

  One entry per user and chain: an assembly that holds the file directly and
  through a sub-assembly has an entry for each, so the total it needs is the
  sum of its entries' `instances` in one `user_configuration`. `resolution` is
  how the user's own reference was resolved (the reference to the sub-assembly
  it holds, for a chain). `possible` entries carry `key`, `file_name`,
  `stored_path`, `status` and the other `candidates`; `name_matches` entries
  `key`, `file_name`, `stored_path` and `status`. `counts` counts every user
  found; from REST an answer over the route's size cap lists the nearest users
  that fit, with `truncated` true.
- **`catalog_search`** (`search`, `/v1/search`): `query`, `engine`, `sort`,
  `results` (`root`, `path`, `name`, `doc_type`, `format`, `modified_utc`, `size`,
  `state`, the active `configuration` with its `part_number` and `description`,
  and `matched`: `name`, `numbers`, `properties`, `configurations` or `folder`
  for the words, and each filter used, such as `pn:`), `next_cursor` and
  `truncated`.
- **`duplicates`** (`duplicates`): `groups` (`sha256`, `size`, `wasted_bytes`,
  `files`), `name_groups` (null unless asked for: `name`, `versions`, `files`
  with their `sha256` and `size`, paged with the groups), `counts` (`groups`,
  `files`, `wasted_bytes`, `name_groups`: all of them, whatever the page),
  `hash_pending` and `next_cursor`.
- **`missing_references`** (`missing`): `documents` (the referencing
  document, and its `references`: `key`, `file_name`, `stored_path`, `status`,
  `rule`, `confidence`, `identity`, `candidates`, `name_matches` (how many
  files of that name the catalog holds) and `warnings`), `counts` (`documents`,
  `missing`, `ambiguous`, `embedded_not_found`, `low_confidence`),
  `within_roots` (always true: missing within the indexed folders) and
  `next_cursor`.
- **`catalog_changes`** (`changes`): `since` and `events` (`time_utc`, `scan`,
  `kind`, `root`, `path`, `previous_root`, `previous_path`, `size`, `sha256`,
  `previous_sha256`), newest first, and `next_cursor`.

### 5.16 `model_summary` (v1, provisional)

One model file (3.20): what `info` prints and `/v1/document` answers for a 3D
file that is not a SOLIDWORKS document, and `ModelDocument.summary()` returns.

```json
{"file": {"name": "frame.stl", "size": 684, "modified_utc": "2026-09-30T14:02:11Z", "mtime_ns": "1790000000000000000"},
 "format": "stl", "format_name": "STL", "variant": "binary",
 "doc_type": "part", "kind": "mesh",
 "units": {"length": "mm", "scale_m": 0.001, "source": "assumed"},
 "application": {"name": null, "version": null},
 "active_configuration": null,
 "fields": {"title": null, "subject": null, "author": null, "keywords": null, "comments": null,
            "last_saved_by": null, "created_utc": null, "last_saved_utc": null},
 "properties": [{"name": "header", "scope": "file", "configuration": null, "type": "text",
                 "value": "frame", "date": null, "text": "frame", "expression": null,
                 "linked": false}],
 "counts": {"objects": 1, "items": 1, "bodies": null, "faces": null, "triangles": 12, "vertices": 36,
            "components": null, "references": 0, "model_parts": null},
 "tree": {"nodes": [{"id": "1", "parent": null, "name": "frame", "kind": "object", "object": 0,
                     "file": null, "placement": null, "color": null}],
          "truncated": false},
 "references": [],
 "preview": {"available": false, "reason": "not_stored", "source": null, "mime": null, "width": null,
             "height": null, "bytes": null, "stream": null, "sha256": null, "renderable": true},
 "warnings": [{"code": "units_assumed", "stream": null,
               "message": "an STL file states no unit of length; millimetres were assumed"}]}
```

- `format` is the registry id (3.20.3) and `variant` the format's variant
  (open sets); `doc_type`, `kind`, `units`, `application` and `fields` are the
  document's (3.20.1). `file`, `fields`, `property`, `placement` and `warning`
  are the objects every kind uses.
- `counts` always has every key; a count the file's head does not give is null
  (a tessellation's count, an ASCII file's). With `references` included,
  `counts.references` is their number.
- `tree` and `references` are null unless included: `info` and `/v1/document`
  include `properties`, `tree` and `references`; `ModelDocument.summary()`
  `properties` and `tree` by default. A tree node is `{"id", "parent", "name",
  "kind", "object", "file", "placement", "color"}`; a reference
  `{"key", "kind", "name", "stored", "resolution"}`, where `stored` is the text
  the file stores (it can be an absolute path from another machine) and
  `resolution` `{"status", "path", "found_by", "version"}` or null, `path`
  relative to the document's folder (`/`-separated; from the REST service, null
  when it would not be). A node's `placement` that is not finite (a crafted
  transform) is null, with the warning `value_not_representable` (stream
  `tree`).
- `preview` describes the image the file stores, as stored (`source`
  `stored`), or `available: false` with `reason` `not_stored` (or
  `undecodable`, with `preview_undecodable`); `renderable` says a preview can
  be drawn from the model (3.21).

### 5.17 `drawing_result` (v1, provisional)

What `solidseas drawing ACTION --json` prints for every action (`new`, `export`,
`update`, `check`, `show`, `settings`; `docs/DRAWINGS.md` 14,
`docs/drawings/cli.md`). The kind is not called `drawing`, because `doc_type:
"drawing"` already means a SOLIDWORKS drawing. Members an action has nothing for
are null or empty, never left out.

```json
{"action": "new", "dry_run": false,
 "drawing": {"id": "8f0c1d2e-3b4a-4c5d-9e6f-708192a3b4c5", "status": "PRELIMINARY", "revision": "A",
             "title": {"title": {"text": "BRACKET, MOTOR MOUNT", "from": "typed"},
                       "number": {"text": "1234-001", "from": "typed"}},
             "signatures": [{"row": "DRAWN", "name": "Ann Bee", "date": "2026-10-07", "current": true}],
             "revisions": [{"rev": "A", "description": "INITIAL RELEASE", "zones": [], "date": null,
                            "approved": null}],
             "model": {"name": "bracket.SLDPRT", "format": "sldprt", "configuration": "Default",
                       "sha256": "...", "unit": "mm", "unit_origin": "file"},
             "options": {"process": "machined", "scheme": "datum", "units": "mm",
                         "views": ["front", "top", "isometric"], "sheet": "A", "scale": "2:1"},
             "counts": {"features": 3, "dimensions": 6, "shown": 6, "removed": 0, "needs_attention": 0,
                        "notes": 4, "views": 3, "items": 0, "balloons": 0},
             "outputs": [{"kind": "pdf", "name": "1234-001 A PRELIMINARY.pdf", "sha256": "...",
                          "revision": "A", "released": false}],
             "created": "2026-10-07T09:14:03-04:00", "modified": "2026-10-07T09:14:03-04:00"},
 "files": [{"path": "D:\\Drawings\\1234-001.ssdrw", "name": "1234-001.ssdrw", "kind": "ssdrw",
            "sha256": "...", "bytes": 35041, "replaced": false, "renamed": false, "released": false}],
 "merge": null,
 "checks": [{"code": "R9.lines", "level": "warning", "item": "v-1", "message": "...", "fixes": []}],
 "check_counts": {"error": 0, "warning": 1, "information": 0},
 "coverage": {"complete": true, "words": "every recognised face is dimensioned", "features": 3,
              "features_unclaimed": 0, "faces": 6, "faces_claimed": 6, "area_mm2": 2200.0,
              "area_claimed_mm2": 2200.0, "area_fraction": 1.0},
 "thread_candidates": [],
 "seconds": {"source": 0.008, "model": 0.002, "features": 0.001, "views": 0.044, "plan": 0.047,
             "assemble": 0.001, "checks": 0.0, "pdf": 0.004, "total": 0.11},
 "warnings": [], "settings": null, "model_check": null}
```

| Field | Meaning |
|---|---|
| `action`, `dry_run` | The action, and whether `update --dry-run` wrote nothing |
| `drawing` | The drawing's summary: id, status (`PRELIMINARY`, `CHECKED`, `RELEASED`), the current revision, the title fields with where each came from (`part`, `list`, `typed`), the signatures (`current`: the content has not changed since), the revision rows, the model's name, format (`sldprt`, or `sldasm` for an assembly), configuration, SHA-256 and unit, the frozen options, counts (an assembly's `items`, its parts list's lines, and `balloons`) and the recorded exports. No path. Null for `settings` |
| `files` | Every file written, in order: absolute path, name, kind (`ssdrw`, `pdf`, `dxf`), SHA-256 and size; `replaced` when it replaced the same drawing's own unchanged file (else it is new), `renamed` when a numbered name such as `1234-001 (2).ssdrw` was taken because the plain one was not free, `released` for a released export |
| `merge` | `update`'s merge report, the same words and counts the editor shows: `words` ("31 unchanged, 2 changed, 3 new, 1 dropped, 1 needs attention", or that the model or only its file changed), the counts, the features matched, resized, gone and new, and the items in words |
| `checks`, `check_counts` | The checklist of `docs/DRAWINGS.md` 20.1: each check's code, level (`error`, `warning`, `information`), the item it is about (its code when it is about the drawing), message and fixes; and how many there are at each level |
| `coverage` | Requirements claimed by features, faces and area (square millimetres), and the sentence; null for a drawing read from a file, which does not store it, and for an assembly's drawing, which has no features |
| `thread_candidates` | Holes and hole patterns whose diameter is a tap drill: feature id, `hole` or `pattern`, count, diameter in millimetres, the threads it may be, whether it was answered and the thread confirmed (null: plain) |
| `seconds` | Seconds per stage in the order they ran, and `total` |
| `warnings` | Problems worked around, in words: values of the file or of Drawing Settings that fell back to their defaults, a guessed unit (`check` of a part), a numbered name taken, a release record that no longer matches its files |
| `settings` | For `settings`: the file read, whether it was there, every value as `Drawing.json` holds it, the fallbacks and what still waits for the user's answer |
| `model_check` | For `check --model`: the file, whether it is verified (its SHA-256 is the drawing's), whether its geometry digest matches when the file differs, whether the drawing's MODEL reference names it, and the words |

## 6. Reading the JSON in JavaScript and TypeScript

`JSON.parse` turns every number into a double, which keeps an integer exactly
only up to 2^53 - 1. The encoding rules (4.2) are written so that nothing
SolidSeas sends changes on the way into a page or a Node service, but a client
has to keep three of them in mind (``):

- **`mtime_ns` is a string, and must stay one.** A file's modification time in
  nanoseconds is about 1.8e18, far past 2^53. `Number("1790292487225708352")` is
  `1790292487225708288`, and `JSON.stringify` writes that back as
  `1790292487225708300`: a client that stores the number and compares it later
  sees a change that never happened, and nothing raises on either side. Store
  and compare the text as it came (`a === b` says whether the file changed); to
  order two times, use `BigInt(a) < BigInt(b)`; to show one, use the
  `modified_utc` field beside it. Never pass it through `Number`, `parseInt` or
  `parseFloat`.
- **Integers above 2^53 - 1 are null.** A property value or a count that large
  is sent as null with the warning `value_not_representable`; a property's
  `text` keeps the stored digits. No corpus file has one.
- **`ETag` and `next_cursor` are opaque strings.** Send them back unchanged.

Everything else is plain JSON: floats are finite (transforms, translations),
dates are ISO 8601 text, and booleans are booleans. Dates need care, because
not every date is an instant:

- **Instants** end in `Z` and are UTC: a file's `modified_utc`, and
  `fields.created_utc` and `last_saved_utc`. `new Date(text)` is right for them.
- **A `date` property is a calendar day.** SOLIDWORKS stores the day the user
  typed as an instant around noon, local time, on the saving machine (5.3), so
  its `value` ends in `Z` but is not a moment anyone meant. Formatted in the
  client's own zone it can show another day: fixture o14's `3/15/2024`,
  saved at UTC-4, is `2024-03-15T16:00:00Z`, which
  `new Date(text).toLocaleDateString("en-US", {timeZone})` shows as 3/15/2024
  in America/New_York and UTC but as 3/16/2024 in Asia/Tokyo. Show `date`
  (`2024-03-15`), the day worked out for you, and split it rather than pass it
  to `new Date()` (next point); `expression` is the date as it was typed, in
  the saving machine's format.
- **Date-only fields are calendar dates.** `saved_version.last_build_date`
  (`2024-01-16`) is a day, and `new Date("2024-01-16")` reads it as UTC
  midnight, which prints as 1/15/2024 in the Americas. Split the text instead.

Fields are only ever added within a schema version, and enums are open (C8):
ignore fields you do not know, and give every `switch` on a status, a code or a
reason a default branch. `solidseas schema KIND --data` prints the JSON Schema
of a kind's `data`, which any JSON Schema to TypeScript generator turns into
types; SolidSeas ships no TypeScript of its own. Section 10 shows a typed
`fetch` client.

## 7. Command line

`solidseas <command> ...`, or `python -m solidseas <command> ...` without
installing. Every command opens documents read-only. Commands that write
refuse to write into the folder of a source file (or below it) unless given
`--allow-source-dir`, never write a SOLIDWORKS file or over a source file, and
never overwrite a file without `--force`. The folder check compares the folders
themselves as well as their paths, so another name for the same folder (an
administrative share such as `\\localhost\C$\...`, a second share of it, a
mount point) is refused too. An existing output that is a symbolic link or a
junction is never replaced, even with `--force`, because writing would follow
it.

### 7.1 Commands

| Command | Options | `--json` kind |
|---|---|---|
| `info FILE` | `--nested STREAM`, `--max-mb N` | `document_summary`; `model_summary` for another 3D file |
| `props FILE` | `--configuration NAME`, `--view effective` (default), `file` or `configuration`, `--nested STREAM` | `properties`; without `--json` it prints the `data` alone |
| `configurations FILE` | | `configurations` |
| `components FILE` | `--configuration NAME`, `--max-nodes N` (default 10,000), `--max-depth N` (default 32), `--flat` | `components`; without `--json` an indented tree |
| `references FILE` | `--configuration NAME` (whose counts to give), `--resolve`, `--root ID=DIR`, `--library ID=DIR`, `--path-map FROM=TO` (each repeatable), `--no-outside-roots` | `references` |
| `bom FILE` | `--configuration NAME`, `--type top` (default), `parts` or `indented`, `--format table` (default), `csv` or `json`, `-o FILE`, `--column PROPERTY` (repeatable), `--part-number-property PROPERTY`, `--root ID=DIR`, `--library ID=DIR`, `--path-map FROM=TO` (each repeatable), `--no-outside-roots`, `--force`, `--allow-source-dir` | `bom`; without `--json` the table, CSV or envelope `--format` names |
| `paths FILE` | | `path_report`; without `--json` the counts, accounts, hosts, user names and paths |
| `streams FILE` | | `streams` |
| `dump FILE STREAM -o OUT` | `--raw`, `--force`, `--allow-source-dir` | `file_written` |
| `preview FILE -o OUT` | `--prefer png` (default) or `dib`, `--nested STREAM`, `--render`, `--stored`, `--max-mb N`, `--force`, `--allow-source-dir` | `file_written` |
| `parasolid FILE -o DIR` | `--text`, `--raw`, `--local-bodies fallback` (default), `always` or `never`, `--max-mb N`, `--force`, `--allow-source-dir` | `parasolid_result` |
| `export FILE --format 3mf\|stl\|step` | `-o FILE` (or a folder that exists; default: the document's name in the current folder), `--configuration NAME`, `--chord MM` (0.0001 to 10) and `--merge` (3MF and STL), `--sheets`, `--allow-partial`, `--exact-only` and `--include-hidden` (STEP), `--max-mb N`, `--force`, `--allow-source-dir` | `export_result` (provisional) |
| `list FOLDER` | `--formats solidworks\|all\|IDS` (default `solidworks`), `--recursive`, `--include properties,configurations`, `--preview none`, `meta` (default) or `inline`, `--max-depth N`, `--limit N`, `--max-examined N`, `--timeout SECONDS`, `--file-timeout SECONDS` (default 30), `--memory-mb N` (default 2048), `--in-process` | `listing` |
| `batch FOLDER -o DIR` | `--no-recurse`, `--no-preview`, `--no-parasolid`, `--text`, `--max-mb N`, `--jobs N` (1 to 64, default 1), `--file-timeout SECONDS` (default 300), `--memory-mb N` (default 2048), `--in-process`, `--max-examined N`, `--force`, `--allow-source-dir` | `batch_summary` |
| `serve` | `--root ID=DIR` (repeatable), `--library ID=DIR`, `--port N` (default 8765; 0 picks a free port), `--bind ADDRESS` (default 127.0.0.1), `--token-file PATH`, `--workers N`, `--allow-remote`, `--allowed-host NAME`, `--catalog`, `--catalog-rescan SECONDS` (default 300), `--formats solidworks\|all\|IDS` (default `solidworks`) | `serve_started`, one compact line when it is ready; then it serves until stopped (section 8) |
| `index FOLDER...` | `--root ID=DIR`, `--library DIR` or `ID=DIR` (each repeatable), `--catalog NAME`, `--db FILE` or `--in-project`, `--formats IDS`, `--hash all\|duplicates\|none`, `--no-previews`, `--part-number-property NAME`, `--workers N` (default 2), `--file-timeout SECONDS` (default 30), `--timeout SECONDS` | `catalog_scan` (provisional) |
| `where-used FILE` | `--configuration NAME`, `--direct`, `--max-depth N` (default 32), `--catalog NAME`, `--db FILE` or `--in-project` | `where_used` (provisional) |
| `search TEXT...` | `--sort relevance\|name\|modified`, `--limit N` (1 to 500, default 100), `--cursor C`, `--catalog NAME`, `--db FILE` or `--in-project` | `catalog_search` (provisional) |
| `duplicates` | `--names`, `--limit N`, `--cursor C`, `--catalog NAME`, `--db FILE` or `--in-project` | `duplicates` (provisional) |
| `missing` | `--limit N`, `--cursor C`, `--catalog NAME`, `--db FILE` or `--in-project` | `missing_references` (provisional) |
| `changes` | `--since 7d\|12h\|2w\|DATE`, `--limit N`, `--cursor C`, `--catalog NAME`, `--db FILE` or `--in-project` | `catalog_changes` (provisional) |
| `catalog [FOLDER]` | `--catalog NAME`, `--db FILE` or `--in-project` | `catalog` (provisional) |
| `catalogs` | | `catalog_list` (provisional) |
| `clear-index [FOLDER]` | `--all`, `--catalog NAME`, `--db FILE` or `--in-project` | `catalog_cleared` (provisional) |
| `drawing ACTION` | `new PART`, `export DRAWING`, `update DRAWING`, `check DRAWING_OR_PART`, `show DRAWING`, `settings`, each with the options of `docs/drawings/cli.md`; `new`, `export` and `update` write under `--out DIR` (or next to the drawing) under the write guards | `drawing_result` (provisional, section 5.17) |
| `version` | | `version` |
| `schema [KIND]` | `--data` | none: prints the JSON Schema of the kind's envelope (of its `data` alone with `--data`), or with no KIND the list of kinds |

`list` is the folder listing of section 5.7, with the same defaults as `scan`:
not recursive, previews described but not inlined. Its `--include` adds to the
preview part, which `--preview` sets on its own, where `scan`'s `include=` and
the service's `include` replace the default: `--include properties` lists
properties and preview metadata, and `--include properties --preview none`
lists what `include=properties` does. Entry paths are relative to the listed
folder, as from `scan`; the service's are relative to the root (section 1.2).
`--limit`,
`--max-examined` and `--timeout` are `scan`'s `max_entries`, `max_examined`
and `max_seconds`, checked between entries as section 3.6 says: a slow file
or a share that stops answering runs past `--timeout`. `batch` walks with the
same walker (section 3.7), bounded by `--max-examined` and without a time
limit: placeholders and links get a report row and are never opened, lock
files and FIFOs, sockets or devices are skipped, and each document is opened
`within` the folder. Its `report.csv` puts an apostrophe before
any cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return, so a
spreadsheet never runs a value from a file as a formula; `report.jsonl` holds
one strict JSON line per document, with its `document_summary` data.

**`list` and `batch` read each document in a worker process** (section 3.13),
as the service does, so a hostile or broken file costs one entry, never the
run. A document still unread after `--file-timeout` seconds has its worker
stopped and replaced and becomes a failed entry with code `timeout`; one whose
reader crashes becomes `worker_crashed`; one that needs more memory than
`--memory-mb` becomes `limit_exceeded`. The run goes on and exits 4 (7.2). In a
`batch` report such a document has status `error` and an error that starts
with `WorkerTimeoutError`, `WorkerCrashedError` or `SldLimitError`; a file it
wrote before it stopped is not listed. The defaults leave a wide margin on the
development corpus: its slowest summary took 0.3 s (8.8), and the slowest of
its 400 largest documents took about 25 s through `batch` (preview and
Parasolid), 39 s with `--text`. `list` runs two workers, one reading and one
standing by while a stopped one is replaced; `batch` runs `--jobs` workers,
reads that many documents at once and still writes its report in walk order.
The output is what reading in the command's own process gives, down to the
error text of a document that fails, which names it as the folder was given; a
test compares the two, with the folder given relative and with forward
slashes.

Starting the workers costs about 0.3 s per command (measured on Windows 10)
and nothing measurable per document. `--in-process` reads in the command's own
process instead, as releases before 0.2.8 did: a little quicker for a few
files you trust, but with no deadline and no memory cap, so one file that hangs
or crashes stops the whole run. It cannot be combined with `--file-timeout`,
`--memory-mb` or a `--jobs` above 1 (exit 2).

The workers start with spawn, which runs the program's main module again in
each of them (3.13). `python -m solidseas` and the installed `solidseas`
command are ready for that; a Python script that calls `solidseas.cli.main`
to run `list` or `batch` must call it under `if __name__ == "__main__":`.

**The catalog commands** (3.18). `index` builds or updates the catalog of its
folders: the first FOLDER is root `project` (then `project2`...), `--library`
folders are `library1`... unless `ID=DIR` names them, and the catalog goes to
your cache folder unless `--catalog`, `--db` or `--in-project` says otherwise
(`--in-project` only on Windows, where a network drive can be told apart; it
says on standard error that the project folder now carries every file's names
and properties). `--formats` says what the catalog indexes from then on
(`solidworks`, a new catalog's default; `all`; or format ids such as
`step,stl`) and is kept with it, so a later `index` without it indexes the
same; `catalog` prints it when it is not SOLIDWORKS documents alone. Its
workers run below normal priority. It exits 4 when a file could not be read or
the run was cut short (7.2). The query commands open the
catalog read-only and never open a CAD file: `where-used FILE` looks the file
up in the catalog of the folder that holds it (the most recently scanned one
when several do), and `search`, `duplicates`, `missing`, `changes` and
`catalog` use the catalog whose root holds the current folder, unless
`--catalog`, `--db` or `--in-project` names one. A file or folder no catalog
holds exits 1 (`not_in_catalog`); a catalog that is damaged exits 3
(`catalog_incompatible`, rule `damaged`) until `clear-index` deletes it or the
next `index` of a catalog in the cache makes it again. `catalogs` lists every
catalog in the cache folder, and `clear-index` deletes one (`--all`: all of
them; `--in-project`: the nearest `.solidseas` folder at or above FOLDER, as
the query commands find it), refusing while `index` or a viewer is updating it
(`busy`); its result names the catalogs deleted by name. Each `search`
argument is one unit, as the shell gave it: one with spaces is a phrase, or
the whole value of a filter (`solidseas search "desc:steel bracket" type:part`).

**Other 3D files** (3.20, provisional). `info`, `props`, `configurations`,
`preview` and `export` read any 3D file SolidSeas reads, with no option: a
file whose name is not a SOLIDWORKS document's is opened with `open_any`.
`info` prints `model_summary` (5.16) with its properties, tree and references;
`props` the file-scope properties (an unknown `--configuration` exits 1);
`configurations` an empty list; `export` writes its scene (3.17), refusing to
replace the file it reads; and `preview` writes the image the file stores, or
with none one rendered from the model (3.21, PNG); `--render` always renders,
`--stored` never does (exit 1 `no_preview` without a stored image), and
`--render` on a SOLIDWORKS document exits 1 `not_implemented`. `--max-mb`
bounds a Parasolid transmit file (`xt_transmit_bytes`, 3.20.2). `components`,
`references`, `bom`, `paths`, `streams`, `dump` and `parasolid` exit 1 with
`not_implemented` (`detail.rule` `model_file`, `detail.value` the format id).
A format SolidSeas knows but cannot read yet exits 1 with
`format_not_supported` (rule `no_reader`), and an unidentified file with
`unknown_format`. A file with a SOLIDWORKS extension is read by
`open_document` exactly as before. `list --formats` is `scan`'s `formats`
(3.6), and `serve --formats` the formats the service reads (8.6).

`components` and `references` are the kinds of section 5.9; a part gives an
empty result, not an error, and an unknown `--configuration` exits 1
(`configuration_not_found`). `--nested STREAM` on `info`, `props` and
`preview` reads a nested document (a virtual or imported component) named as
`nested` in those results; an unknown name exits 1 (`stream_not_found`).

`bom` builds the bill of materials of section 3.16 for one assembly
configuration and prints it as SOLIDWORKS draws it: `--type top` (the default,
as in SOLIDWORKS), `parts` or `indented`. Each component file is found as
`references --resolve` finds it (the same `--root`, `--library`, `--path-map`
and `--no-outside-roots`; the document's own folder when no root is given) and
read for DESCRIPTION and each `--column PROPERTY`; `--part-number-property
PROPERTY` takes PART NUMBER from that property where a file has it.
`--format table` (the default) prints the table, then a summary and the notes;
`csv` prints the CSV of 3.16, as UTF-8 whatever the console's code page; `json`
prints the `bom` envelope. The table shows a control character in a value (a
line break, a carriage return, a tab) as its escape, `\r\n`, so every row
keeps to its line; the CSV and the JSON carry the value as it is. `-o FILE`
writes that format to a file instead, through the write guards of this section
(a CSV file starts with a byte order mark); besides the assembly's folder, the
guards refuse each `--root` and `--library` folder and, once the files are
found, the folder of a component file read outside them, each with what lies
below it, unless `--allow-source-dir`. Under `--json`, standard output holds
the `bom` envelope, so another `--format` needs `-o` (exit 2 without it). A
malformed `--path-map`, `--column` or `--part-number-property` exits 2, and a
`--root` or `--library` folder that does not exist exits 1 once a component
file is looked for there, as for `references --resolve`. The command exits 4 when the BOM is incomplete
(`complete` false: a file not found or not read, a sub-assembly whose
components are missing, a part number that may differ from SOLIDWORKS', a
limit reached) and 0 otherwise; a part or a drawing gives an empty BOM and
exits 0.

`export` writes a part or an assembly configuration for 3D printing, as 3.17
describes: 3MF (one object per component file, one build item per instance;
one object with `--merge`) or binary STL, in millimetres. `-o` names a file
ending in the format's extension or a folder that exists, where the file is
the document's name with that extension; anything else is refused
(`output_refused`: rule `output_extension` for a name with another extension
or none, never taken as a folder to be made, and `output_folder` for a
folder that is not there). Without `-o` the file goes to the current folder.
The write guards of this section
apply: an existing file is replaced only with `--force` (through a new file
renamed over it) and never when it is a link, and nothing is written next to
the document without `--allow-source-dir`. An assembly's files are looked for
in its own folder, as `references --resolve` does without roots. It exits 4
when instances of the assembly were left out, 1 with `nothing_to_export` for a
drawing or a document with nothing to print, and 1 with `limit_exceeded` when
a limit stopped a part.

`export --format step` writes the part as STEP AP214, as 3.19 describes: the
exact B-rep, not triangles. `-o` takes a file ending in `.step` or `.stp`, or a
folder (the document's name with `.step`). `--configuration` chooses whose
bodies are written; one the part does not store exits 1 with
`nothing_to_export`, never another configuration's geometry. `--sheets` writes
sheet (surface) bodies too; `--exact-only` refuses what would have to be
approximated. A body that cannot be written without loss refuses the export:
nothing is written and it exits 1 with `not_representable`, naming each body and
its reason; with `--allow-partial` such bodies are left out whole, the file says
so in its header, and it exits 4. `--chord` and `--merge` with `step`, and the
STEP options with `3mf` or `stl`, exit 2. An assembly is written with a
product for each part, its component files found as its 3MF and STL exports find
them (3.19); an instance that cannot be written exits 1 with
`not_representable` (rule `instances_left_out`), and with `--allow-partial` it
is left out, listed in `skipped`, and the export exits 4. A Parasolid transmit file's part
(`.x_t`, `.x_b`) is written the same way (3.19), `source_format` `parasolid`;
another 3D file exits 1 with `not_implemented` (`detail.rule` `model_file`).
The write guards are those above.

`paths` is the path report of section 3.12: every path and user name the
file, and each nested document in it, would reveal. It exits 4 when the report
is incomplete (a stream over the scan cap, a part that could not be read or a
limit reached), and says why. SolidSeas never rewrites the file; the output
ends by saying so.

`serve` runs the REST service of section 8 over its roots until SIGINT,
SIGTERM or Ctrl+Break. It prints one line when it is ready (with `--json`, one
compact `serve_started` envelope rather than indented JSON, so a supervising
program can read it as a line) and logs to standard error.

`references --resolve` finds each referenced file on this machine (C4,
section 3.10) and fills in the results of section 5.10. Each `--root` is a
recursive project root and each `--library` a recursive library root, searched
in the order given, project roots first; `ID` matches `[a-z0-9_-]{1,32}` and
`DIR` may be relative to the current folder. With neither, the document's own
folder is searched, as root `document`. Each `--path-map` reads stored paths
starting with `FROM` (a drive or `\\host\share` prefix, split from `TO` at the
first `=`) as starting with `TO` on this machine; unlike a root's `DIR`, `TO`
must be absolute. Point lookups of single paths outside the roots are allowed
on local drives, as in Python, unless `--no-outside-roots` is given: then
nothing outside the roots is looked up, a path mapping's target included, which
is the service's rule, so the same roots give the service's answer. Missing and
ambiguous files are results and exit 0; a folder index cut short by a limit
exits 4. `--root`, `--library`, `--path-map` or `--no-outside-roots` without
`--resolve`, a malformed `ID=DIR`, a malformed mapping or a relative `TO` exit
2; a refused root (a WebDAV share or a device path) exits 3 (`path_refused`),
and a root that does not exist exits 1 (`not_found`).

### 7.2 Exit codes

| Exit | Meaning | Error codes |
|---|---|---|
| 0 | Success | |
| 1 | Failed: the document could not be read, something asked for is absent, the service could not listen, or an internal error | `permission_denied`, `address_unavailable`, `not_found`, `configuration_not_found`, `stream_not_found`, `no_preview`, `not_in_catalog`, `nothing_to_export`, `not_representable`, `placeholder_file`, `unknown_format`, `format_not_supported`, `damaged_file`, `limit_exceeded`, `file_too_large`, `locked`, `internal`, `worker_crashed`, `not_implemented`, `busy`, `root_unavailable`, `timeout`, `drawing_invalid`, `drawing_too_complex`, `model_not_found` |
| 2 | Usage: the arguments are wrong | `invalid_argument`, `unknown_parameter`, `duplicate_parameter` |
| 3 | Refused by a safety rule | `path_refused`, `link_refused`, `feature_disabled`, `output_refused`, `bind_refused`, `token_file_refused`, `catalog_incompatible`, `drawing_released` |
| 4 | Partial: a folder listing or batch run finished, and at least one item failed (for a batch, also a folder that could not be read or a walk cut short by its limits); a reference resolution whose folder index a limit cut short; an incomplete path report; an incomplete bill of materials; an export that left out instances of an assembly; a STEP export that left bodies out (`--allow-partial`); a catalog index run in which a file could not be read, or that a limit or a cancel stopped; or a `drawing check` that found an error-level check (with `--strict`, a warning too) or a model that is not the drawing's | |
| 130 | Interrupted | `interrupted` |

The exit for a failure comes from its error code, through
`solidseas.model.ERROR_CODES`; a test checks this table against it. A partial
run still prints its result (`ok: true`): read `counts.error` in a listing or
`status_counts` in a batch summary for the failed items.

### 7.3 `--json`

- Standard output holds exactly one JSON document, indented by two spaces and
  ASCII-only, and standard error stays empty. A failure prints the error
  envelope (section 5.6) instead of the result. `serve` is the exception: its
  one document is the compact ready line, and its log lines still go to
  standard error.
- Usage errors are JSON too: `invalid_argument`, with the usage text in
  `detail.usage`, and exit 2.
- `--version` prints the `version` envelope and exits 0. `-h` or `--help`
  prints an `invalid_argument` error whose `detail.usage` holds the whole help
  text, and exits 2: help is text, not a result. Without `--json` both print
  text and exit 0, as usual.
- `--json` may come before or after the command.
- `source` is `{"file": <the argument as given>}` for a command on a document
  (plus `"nested"` when `--nested` was given), `{"folder": ...}` for `list` and
  `batch`, and null for `version`.
- `reader_message` is filled in: it is the exception's text, which can hold a
  path from this machine.
- Without `--json`, results are for people and their wording may change;
  messages go to standard error.

### 7.4 Examples

```text
solidseas info bracket.SLDPRT --json
solidseas props bracket.SLDPRT --configuration Long --json
solidseas list D:\Jobs\Example --recursive --include properties --json
solidseas list D:\Jobs\Example --preview inline --limit 100 --json
solidseas preview bracket.SLDPRT -o D:\Exports\bracket.png --json
solidseas components frame.SLDASM --configuration Lite --flat --json
solidseas references frame.SLDASM --json
solidseas references frame.SLDASM --resolve --root jobs=D:\Jobs --library std=E:\Library --json
solidseas references frame.SLDASM --resolve --path-map S:\=E:\Library --json
solidseas props frame.SLDASM --nested VirtualComp/Part12-sldprt --json
solidseas paths frame.SLDASM --json
solidseas bom frame.SLDASM --type indented
solidseas bom frame.SLDASM --type parts --column Material --format csv -o D:\Exports\frame-parts.csv
solidseas bom frame.SLDASM --configuration Lite --root jobs=D:\Jobs --json
solidseas batch D:\Jobs\Example -o D:\Exports --jobs 4 --json
solidseas export bracket.SLDPRT --format 3mf -o D:\Prints\bracket.3mf --json
solidseas export frame.SLDASM --format stl --configuration Lite --chord 0.005 -o D:\Prints\frame.stl
solidseas list D:\Incoming --recursive --file-timeout 10 --json
solidseas schema listing
solidseas serve --root jobs=D:\Jobs --library std=E:\Library
```

## 8. REST service

`solidseas serve` is a small, read-only HTTP service over folders an
administrator configures, for systems that are not written in Python, such as
the TypeScript store. It uses the standard library only
(`http.server.ThreadingHTTPServer`) and adds no dependency. Every JSON answer is
built by the same builder as Python and the CLI, so `data` for a file and a set
of options is identical on all three surfaces (section 1); a test compares them
for every fixture document. Its routes, parameters, status codes, headers and
error codes are stable from 0.2.0 (section 9); its Python classes are
provisional.

### 8.1 Starting and stopping

```text
solidseas serve --root ID=DIR [--root ID=DIR ...] [--library ID=DIR ...] [--port 8765]
                [--bind 127.0.0.1] [--token-file PATH] [--workers N]
                [--allow-remote --allowed-host NAME ...] [--catalog [--catalog-rescan SECONDS]]
                [--json]
```

- Each `--root` is a recursive project root and each `--library` a recursive
  library root (C5). `ID` matches `[a-z0-9_-]{1,32}`; `DIR` may be relative to
  the current folder and must exist (exit 1, `not_found`). Roots are searched in
  the order given, project roots first.
- When it is ready to answer, it prints one line on standard output: a sentence,
  or with `--json` one compact `serve_started` envelope (section 5.12) with the
  bound host and port, the base URL, the root ids, the number of workers and
  whether the token file was created just now. `--port 0` picks a free port,
  which that line reports. Log lines go to standard error.
- Each root's folder index is built in the background from the start; until a
  root's index is ready, requests for it answer 503 (8.5).
- It runs until SIGINT, SIGTERM or Ctrl+Break. It then stops accepting, waits up
  to 5 seconds for the requests in flight, closes the worker pool (a request
  still waiting for a worker answers 500 `worker_crashed`), logs where any
  request thread is still stuck (as module, function and line) and ends the
  process with `os._exit`: exit 0, or 1 when a thread was left behind. A stuck
  read therefore never keeps the process alive (``).
- Before it serves: exit 2 for bad arguments; exit 3 for a non-loopback `--bind`
  without its settings (`bind_refused`, 8.2) or a token file that cannot be
  created or read, or is unsafe or malformed (`token_file_refused`, 8.3; a
  `--token-file` in a folder that does not exist is `folder_missing`);
  exit 1 for a root that does not exist, or a port that is in use or an address
  that is not this machine's (`address_unavailable`). A refused bind is decided
  before the token file is touched and before anything listens.
- From Python, `solidseas.serve.ServeConfig` holds every setting below
  (provisional): `Server(config)` binds, `start()` starts the workers and the
  index builds, `serve_forever()` answers, and `shutdown()` stops it. The CLI
  exposes the roots, port, bind, token file and worker count; the other limits
  keep their defaults.

### 8.2 Binding and exposure

- The default address is `127.0.0.1:8765`. `localhost` means 127.0.0.1, and
  `::1` is accepted. Clients should call `http://127.0.0.1:8765/`, not
  `localhost`: on Windows a refused connection to the other address family of
  `localhost` costs about 2 seconds before the right one is tried.
- Any other address needs `--allow-remote` and at least one `--allowed-host`,
  the name clients put in the `Host` header; without them the start is refused
  (`bind_refused`, `detail.rule` `remote_not_allowed` or `no_allowed_hosts`).
  The service speaks plain HTTP only: bind beyond loopback only inside a private
  network, such as a compose network shared with the store, and publish no host
  port (or only `127.0.0.1:`). After deploying, check the exposure from both
  sides: a request from another machine must fail, and the listening sockets
  (`ss -ltnp`, `Get-NetTCPConnection`) must show only the address you chose.
- The listening socket is the only socket the service opens. It makes no
  outbound connection, not even the lookup of its own host name that
  `HTTPServer` makes by default. On Windows the port is bound exclusively, so
  another program cannot bind it alongside.
- **The port is only the service's while it runs.** Whenever it is stopped
  (between restarts, before it starts at boot, after a supervisor gives up),
  any program of any account on the machine can listen on 127.0.0.1:8765, and
  a client that calls then hands it its `Authorization` header, a token that
  reads every document under every root. A client tells the two apart with
  `/v1/identity` before it sends the token: the service proves it holds the
  client's token without sending it (8.16). On a machine other accounts use,
  have every client make that check, keep the service supervised so the port
  is never free for long (8.14), and have clients fail closed: on a failed
  check, a connection error or an answer that is not a SolidSeas envelope,
  stop and report rather than retry the same token in a loop. Security review
  finding 15.

### 8.3 Authentication

- Every route except `/v1/health` and `/v1/identity` needs
  `Authorization: Bearer <token>`, on loopback too: loopback is shared by every
  program and account on the machine, and a web page in a local browser can
  reach it. `/v1/identity` is how a client checks, before it sends its token,
  that it is talking to the service that holds it (8.16).
- **The token file** holds one `name:token` line per client; lines starting with
  `#` are comments. The default is `%LOCALAPPDATA%\SolidSeas\serve-tokens` on
  Windows and `$XDG_CONFIG_HOME/solidseas/serve-tokens`
  (`~/.config/solidseas/serve-tokens`) elsewhere; `--token-file` names another.
- **Created on first start** when it does not exist, holding one token named
  `default` from `secrets.token_urlsafe(32)`. It is readable by the current
  user alone from its first byte: on Windows it is created with a protected
  access list that grants only the current user; on Linux and macOS with mode
  0600, `O_EXCL` and `O_NOFOLLOW` (the default folder is created with mode
  0700). The token is never printed or logged: clients read it from the file.
- **Checked on every start, failing closed.** A token file that cannot be used
  refuses the start with `token_file_refused` (exit 3) and `detail.rule`:
  - `missing`, `unreadable`, `too_large` (over 64 KiB) or `empty`;
  - `malformed`: a line that is not `name:token`, a name not matching
    `[a-z0-9_-]{1,32}`, a token that is not 32 to 128 URL-safe characters, a
    name used twice, or more than 256 tokens;
  - `shared_access`: on Windows an allow entry on the file for any account
    other than the service's own, SYSTEM, Administrators and OWNER RIGHTS, or
    one Windows cannot read as an account; on Linux and macOS any group or
    other permission bit;
  - `not_owner`: the file, or the folder that holds it, is owned by an account
    other than the service's own, SYSTEM or Administrators (root on Linux and
    macOS, for the folder). An owner can rewrite the access list whatever it
    says, and an OWNER RIGHTS entry grants whoever owns the file;
  - `folder_writable`: another account may add files to the folder, delete or
    rename what is in it, or change its access list or owner (on Windows an
    allow entry with those rights, inherit-only entries aside; on Linux and
    macOS a group or other write bit without the sticky bit). Whoever can do
    that can put a token file of their own in place while the service is
    stopped;
  - `folder_missing`: a `--token-file` in a folder that does not exist. Only
    the default folder is created; create any other first, as 8.14 shows.

  Entries are compared as accounts, not as text, so a service running as LOCAL
  SERVICE recognises its own entry, which Windows writes as `LS`.
- **One token per client.** Give each client its own line with its own name;
  delete a line to revoke that client alone. Tokens are read at start, so
  restart the service after editing the file. The access log names the client
  by its token's name, never by the token.
- **Make every token with `secrets.token_urlsafe(32)`**, as the service makes
  the first one: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
  or `solidseas.serve.tokens.new_token()`. Never write one by hand:
  `/v1/identity` answers anyone with an HMAC under a client's token (8.16),
  which lets guesses at the token be tested offline, without the failure limit
  below, so only a random token is safe. The start-up check accepts any 32 to
  128 URL-safe characters and cannot tell a weak token from a strong one.
- A presented token is compared with every configured token in constant time
  (`hmac.compare_digest`). Only the `Authorization` header carries it: `token`
  or `access_token` in the query is an unknown parameter (400, and never taken
  as a credential), and a request with two `Authorization` headers is refused.
- A missing or wrong token answers 401 `unauthorized` with
  `WWW-Authenticate: Bearer realm="solidseas"`. More than 20 failures in a
  minute from one address answer 429 `too_many_failures`, with
  `Retry-After: 60`, even when the next request carries the right token.
- Keep tokens out of command lines and shell history: give `curl` a header file
  only you can read (`curl -H @file`), and give a service its token through a
  file or its secret store, never through a URL.

### 8.4 Requests from browsers: Host, Origin and Fetch Metadata

These checks run on every request before anything else, including the answer
405 to another method, a method the service has never heard of (`PROPFIND`, a
lower-case `get`) included:

- `Host` must name the bound address with the bound port: `127.0.0.1:<port>`,
  `localhost:<port>`, `[::1]:<port>` when bound there, or an `--allowed-host`
  name. It is parsed with `urlsplit`; a missing, repeated or unparseable `Host`,
  another name or another port answers 403 `forbidden_host`. This stops DNS
  rebinding, where a page's own host name is made to resolve to 127.0.0.1.
- Any `Origin` header, and any `Sec-Fetch-Site` other than `none` or
  `same-origin`, answers 403 `forbidden_origin`: such a request comes from a page
  in a browser. The service has no CORS; no response carries
  `Access-Control-Allow-Origin`.
- Server-side clients send neither header: curl, Python's `http.client` and
  `urllib`, and Node's own `fetch` (checked with Node 24, which sends
  `Sec-Fetch-Mode: cors` but no `Origin` or `Sec-Fetch-Site`; a test runs it
  when Node is installed). Call the service from the server side of the store,
  so that no token ever reaches a shopper's browser.

### 8.5 Roots and paths

A request names a root by its id (`root`) and a file or folder relative to it
(`path`), `/`-separated. The path travels as a query parameter, so a proxy that
normalises `%2F` or `..` in a URL path cannot change it, and it is
percent-decoded once, as strict UTF-8 (8.7). A `+` in a query means a space, as
in any form-encoded query: send a plus sign in a name as `%2B`.

**The text is checked first,** with no filesystem access and the same rules on
every operating system. A refusal answers 403 `path_refused` with
`detail.rule` and, when one component is at fault, `detail.component_index`
(from 0):

| Rule | Refused |
|---|---|
| `absolute` | A leading `/` (including `//host/share/...`) |
| `empty_component` | An empty path for a document, `//`, or a trailing `/` |
| `backslash` | A `\` anywhere |
| `colon` | A `:`, which names an alternate data stream (`a.SLDPRT:hidden`) or a drive (`C:x`) |
| `dot_component` | A component that is only dots and spaces: `.`, `..`, `...`, `. .` |
| `trailing_dot_or_space` | A component ending in a dot or a space, which Windows would strip |
| `control_character` | NUL, another C0 control character or DEL |
| `lone_surrogate` | Text that is not valid Unicode |
| `reserved_character` | `<`, `>`, `"`, `|`, `?` or `*` |
| `device_name` | A Windows device name before the first dot, with any extension and case: CON, PRN, AUX, NUL, COM0 to COM9, LPT0 to LPT9, and COM and LPT with a superscript 1 to 3 |
| `too_long`, `too_deep`, `component_too_long` | More than 1,024 characters, more than 64 components, or a component over 255 characters |
| `not_a_document` | On a document route, a name without a SOLIDWORKS extension (`.sldprt`, `.sldasm`, `.slddrw`), or the extension of another format the service was started to read (`serve --formats`) |

**Then the path is looked up, not joined** (critique 3.16, C3). The service
builds a folder index of each root with the shared walker (section 3.7) when it
starts, and finds each component among the names that index holds. No text from
a request is ever joined into a path: the path the service reads is built from
names the index, or a listing of a folder the index knows, returned.

- Names compare as NTFS compares them (section 2), and the answer carries the
  on-disk spelling. An exact spelling wins; a name that matches several entries
  only when case is ignored is not found.
- A file or folder added after the start is found by listing the deepest folder
  of the path that the index knows. One removed since is not found.
- 8.3 short names (`O06_BO~1.SLD`) are in no directory listing, so they are not
  found (404), just as opening a document `within` a folder refuses them
  (section 3.1).
- What the walker never follows is refused: a link, junction or mount point
  anywhere on the path answers 403 `link_refused` (rule `link_in_path`), and a
  cloud placeholder answers 409 `placeholder_file` and is never opened. A
  SOLIDWORKS lock file, a FIFO, socket or device answers 403 `path_refused`.
- The worker that reads the document opens it `within` the root (section 3.1),
  so a link that appears between the lookup and the read is not followed
  either, and on Windows a placeholder is never recalled. A file with more than
  one name (a hard link) is refused on the open handle, before any byte is
  read: 403 `link_refused` with rule `hard_link`, since another name for it may
  lie outside the root.
- The root itself may be a junction or a share (C6). A root configured without
  its subfolders (`recursive=False`, Python only) serves its own folder: paths
  below it are not found, and `recursive=1` on its listing answers 400.
- While a root's index is being built, requests for it answer 503 `busy` with
  `Retry-After: 2`. A root that could not be indexed, or whose folder has gone,
  answers 503 `root_unavailable` with `Retry-After: 30`. `/v1/roots` shows each
  root's state. `resolve=1` does not use the indexes built at start (8.6), so
  another root's index being built does not hold it up.
- Every component of a path is checked from the root down with `lstat` before
  the next is asked of the operating system, the folders the index holds
  included: a folder replaced by a link after the start is refused
  (`link_refused`) before any path through it is used, so a symbolic link to a
  share never makes the service, or its workers, connect there.

### 8.6 Routes

Every route is under `/v1` and answers `GET` and `HEAD`; `HEAD` does the same
work and sends the headers alone. Any other method answers 405
`method_not_allowed` with `Allow: GET, HEAD`. A request with a body (a
`Content-Length` other than 0, or any `Transfer-Encoding`) answers 400 with
`detail.rule` `body`, and the connection is closed. An unknown route answers 404
`not_found` with `detail.rule` `route` and the message "The service has no
route at that address.", after the token check. A request line without an
HTTP version (HTTP/0.9) answers 400 `invalid_argument`, rule `http_version`,
as HTTP/1.1 with every header of 8.11, and the connection is closed.

| Route | Parameters (\* required) | Answer | Deadline | Size cap |
|---|---|---|---|---|
| `/v1/health` | none | `health`; needs no token | | |
| `/v1/identity` | `client`\*, `nonce`\* | `identity`: the service's proof that it holds the client's token (8.16); needs no token | | |
| `/v1/version` | none | `version` | | |
| `/v1/roots` | none | `roots` | | |
| `/v1/list` | `root`\*, `path` (a folder; the root when left out), `recursive`, `include`, `limit` (1 to 500, default 100), `cursor`, `formats` | `listing` | 60 s per page, 10 s per file | 8 MiB |
| `/v1/document` | `root`\*, `path`\*, `nested` | `document_summary`; `model_summary` for a model file | 15 s | 1 MiB |
| `/v1/properties` | `root`\*, `path`\*, `configuration`, `view` (`effective`, `file` or `configuration`), `nested` | `properties` | 15 s | 1 MiB |
| `/v1/configurations` | `root`\*, `path`\* | `configurations` | 15 s | 1 MiB |
| `/v1/components` | `root`\*, `path`\*, `configuration`, `max_depth` (1 to 32, default 32), `max_nodes` (1 to 10,000, default 10,000), `flat` | `components` | 15 s | 8 MiB |
| `/v1/references` | `root`\*, `path`\*, `configuration`, `resolve` | `references` | 15 s | 8 MiB |
| `/v1/bom` | `root`\*, `path`\*, `configuration`, `type` (`top`, `parts` or `indented`; default `top`), `columns` (property names, comma-separated), `part_number_property` | `bom` (provisional) | 120 s | 8 MiB |
| `/v1/preview` | `root`\*, `path`\*, `prefer` (`png` or `dib`), `nested`, `render` (`auto`, `never` or `always`) | the image, `image/png` or `image/bmp` | 10 s | 16 MiB |
| `/v1/path-report` | `root`\*, `path`\* | `path_report` | 30 s | 8 MiB |
| `/v1/catalog` | none | `catalog` (provisional), with the roots' paths left out | 5 s | 1 MiB |
| `/v1/where-used` | `root`\*, `path`\*, `configuration`, `direct` | `where_used` (provisional) | 5 s | 1 MiB |
| `/v1/search` | `q`\* (the search text of 3.18, at most 1,000 characters), `limit` (1 to 500, default 100), `cursor`, `sort` (`relevance`, `name` or `modified`) | `catalog_search` (provisional) | 5 s | 1 MiB |

- `source` in the envelope is `{"root", "path"}`, the path in its on-disk
  spelling, plus `nested` when it was given. An error envelope's `source` names
  the root and path as requested, an error in the query itself included: each
  of `root`, `path` (and `nested`, on a route that takes it) that the query
  gives once, as valid text within its limits, else null; `source` is null when
  the query names neither. `reader_message` is always null (5.6).
- The parameters mean what the CLI's options mean (section 7.1):
  `/v1/document` is `info`, `/v1/properties` is `props`, and so on.
  `nested` reads a virtual or imported component's own document, named as in
  the `nested` field of the `components` and `references` results.
- `/v1/list` takes `include` members `properties`, `configurations`, `preview`
  and `preview_data`, as `scan` does (3.6); the default is `preview`. A `path`
  that names a file answers 400 `invalid_argument` with `detail`
  `{"parameter": "path", "rule": "not_a_folder"}` and the message "The path
  names a file, not a folder."
- `/v1/preview` answers 404 `no_preview` when the file stores no preview. An
  image is served only after the service checked its bytes itself: the PNG
  signature, or the BMP the reader built (`prefer=dib`). Nothing else is ever
  served as an image.
- **Model files** (3.20, provisional). The service reads the formats given to
  `serve --formats` (`ServeConfig.formats`; default `solidworks`, the service
  exactly as before): a document route takes their extensions, and every
  model file is read in a worker. `/v1/document` answers `model_summary`
  (5.16, with its properties, tree and references), `/v1/properties` the
  file-scope properties (job `model_properties`), and `/v1/preview` the image
  the file stores as a PNG the worker wrote itself, else one rendered from the
  model (`render=auto`, the default; `never`: the stored image or 404;
  `always`: rendered). The other document routes answer 501
  `not_implemented` with `detail.rule` `model_file`, and `render=always` for a
  SOLIDWORKS document answers 501 too. `/v1/list` lists SOLIDWORKS documents
  unless `formats` asks for more: `all` (every format the service reads) or
  ids among them; another id answers 400 `invalid_argument`
  (`detail.parameter` `formats`). A format the service was not started to read
  is not a document there (403 `path_refused`, rule `not_a_document`).
- **The catalog routes** answer only when the service runs with `--catalog`
  (403 `feature_disabled` otherwise). The service then keeps a catalog of its
  roots in the cache folder of the account it runs as (3.18), never under a
  root: a cache folder inside one (`SOLIDSEAS_CACHE_DIR` there, or a root at
  the home folder that holds the cache) stops the service from starting
  (`invalid_argument`, `detail.parameter` `catalog`). It scans the catalog when
  it starts and again every `--catalog-rescan` seconds in a thread of its own,
  reading documents with workers of its own (at most two, below normal
  priority, with the service's memory, size and hard-link limits), so a scan
  never waits for a worker busy with a request, nor a request for one busy
  with a scan; a request never starts a scan. The catalog indexes the formats
  the service reads (`--formats`, SOLIDWORKS documents by default), no more,
  and `/v1/where-used` accepts a path of those formats only. Until
  the first scan has finished they answer 503 `busy` (rule `catalog_scanning`)
  with `Retry-After: 2`. They answer from a read-only connection, interrupted at
  the route's deadline (504 `timeout`), the SQL and where-used's own walk up
  alike, with root ids and relative paths only:
  `/v1/catalog` leaves the roots' paths out, and a document's stored reference
  paths appear only where the `references` kind would give them too
  (`stored_path` in `possible` and `name_matches`). `/v1/where-used` checks
  `path` as text (8.5) and looks it up among the catalog's rows, exactly
  spelled or else the one row that matches case-insensitively (404
  `not_in_catalog` otherwise). A where-used answer over the size cap keeps the
  nearest users that fit, with `truncated` true and `counts` still counting
  them all, so a fastener used by thousands of assemblies still gets an
  answer. The ETag is taken from the answer.
- `/v1/path-report` holds the very values a file would reveal (account names,
  server names, project folders): it needs a token like every route but
  `/v1/health`, and none of it is logged.
- **`/v1/references?resolve=1`** finds each referenced file in the configured
  roots (C3, section 3.10), with the results in each file's `resolution` and the
  summary in `resolution`. The service never looks outside its roots and never
  touches a stored UNC path or mapped network drive (C2), and every location is
  `{"root", "path"}`.
  - **It sees the folders as they are now.** Each request walks every
    configured root again, as Python's `resolve_references` does on each call
    without a cache, so a project moved or copied while the service runs is
    resolved where it is now. The result equals Python's
    `resolve_references(doc, roots, allow_outside_roots=False,
    skip_unavailable_roots=True, max_examined=1_000_000)` run at the same moment
    over the same roots, with `max_seconds` the time left before the route's
    15 s deadline. The walk costs about a second per 85,000 directory entries on
    a local disk (development corpus); a root too large to walk in time gives
    `index_partial`, and a slow share costs more.
  - **A root that cannot be walked** (gone, access denied) is searched without:
    it is listed in `resolution.roots` with `index_partial` true and
    `truncated_reason` `unavailable`, and every result carries
    `root_unavailable`.
  - It runs as C10 says: a worker reads what resolution needs from the
    document; the server process walks the roots and collects candidates; one
    worker job reads the candidates' identities in a batch; and the server
    process applies the rules. Its ETag is computed from the answer itself
    (8.10).

- **`/v1/bom`** is the `bom` command (3.16) against the configured roots,
  with nothing looked up outside them. It runs in three steps, as C10 has it:
  a worker reads what resolution needs from the assembly, the server process
  resolves its references against every root (walked again for the request,
  as for `resolve=1`), and a worker builds the BOM from that resolution,
  opening each component file it found within its root and reading only its
  properties. A worker gives the reading of component files 60 s; the route's
  120 s covers that, the assembly's own reading and the resolution. The answer
  equals Python's `model.build_bom(doc, roots=..., allow_outside_roots=False)`
  over the same roots, and the CLI's `bom --root ... --no-outside-roots`; a
  test compares the three for every fixture document and BOM type. A property
  name in `columns` cannot hold a comma; two names equal but for case answer
  400 `invalid_argument` (`detail.parameter` `columns`), and a blank
  `part_number_property` answers 400 naming `part_number_property`, as Python
  does. Its ETag is computed from the answer itself (8.10).

**Listing pages.** A page holds at most `limit` entries, in the walker's order
(breadth first, each folder sorted case-folded). When a page stops at `limit`,
or at the page deadline, `truncated` is true, `truncated_reason` is
`max_entries` or `deadline`, and `next_cursor` is an opaque string: send it back
as `cursor`, with the other parameters unchanged, for the next page. A cursor
given with another query answers 400. A page resumes after the last entry of
the previous one, so an entry added before that point in the meantime appears
only in a new listing. Each document in a listing is read in a worker with its
own 10 s deadline: a file that hangs or crashes its worker becomes an error
entry (`timeout`, `worker_crashed`) and the page goes on. Inline images
(`preview_data`) stop when their base64 text would pass 6 MiB (the page cap
less 2 MiB): later entries keep their `preview` object with `data_base64` null,
and the listing says `preview_data_capped: true`. `next_cursor` is null from
Python and the CLI.

### 8.7 Query parameters

Each route accepts exactly the parameters in its row of 8.6
(`request-schema-allowlist` and `falsy-zero-defaults`):

- A parameter the route does not name answers 400 `unknown_parameter`, and one
  given twice 400 `duplicate_parameter`; `detail.parameter` names it. An empty
  value answers 400 `invalid_argument`: leave the parameter out instead. A query
  may hold at most 12 fields.
- Integers are ASCII digits, with no sign and no leading zero, within the range
  in 8.6. Booleans are `0`, `1`, `true` or `false`. Enumerations are exact and
  case-sensitive. `include` is a comma-separated list of its members, none
  twice. `root` and `client` match `[a-z0-9_-]{1,32}`, and `nonce`
  `[A-Za-z0-9_-]{32,128}`. `configuration` and `part_number_property` hold
  at most 256 characters, `nested` 512 and `columns` 4,096, with no control
  characters. `cursor` is what a
  listing page returned.
- The query is percent-decoded once, as strict UTF-8. An invalid or overlong
  sequence (`%C0%AE`), a `%` that does not start a two-digit escape, a `#`, an
  empty field (`&&`) or a field without `=` answers 400 `invalid_argument` with
  `detail.parameter` `query`. A path that decodes to `..%2F` is a name holding
  a `%`, not a traversal.

### 8.8 Limits and deadlines

| Limit | Default | Over it |
|---|---|---|
| Time for a request line and its headers to arrive | 10 s, however slowly the bytes trickle in | the connection is closed, and a line logged (8.12) |
| Time for the first byte of a request | 5 s (`idle_timeout`), on a new connection and between requests on a kept-alive one | the connection is closed; a new connection that sent nothing is logged |
| URL | 4 KiB | 414 `uri_too_long` |
| Headers | 16 KiB in all, at most 100. Reading stops at the limit, so no request makes the service hold more | 431 `headers_too_large` |
| Requests per connection | 100 | the connection is closed after the answer |
| Open connections | 64 | 503 `busy`, then closed after at most 0.1 s of reading what the client sent |
| Requests reading documents at once | 16 | 503 `busy`, `Retry-After: 2` |
| Worker processes | one per CPU, at most 4 (`--workers`) | requests wait for a free one, within their deadline |
| Memory per worker | 2 GiB | 422 `limit_exceeded` |
| Document size | 256 MiB | 422 `file_too_large` |
| Deadlines | per route, in 8.6; time spent waiting for a worker counts | 504 `timeout` |
| Response size | per route, in 8.6. A worker's answer may be that plus 64 KiB; a longer one is refused in the worker, before the service reads it | 422 `response_too_large` |
| Component tree | 10,000 nodes, 32 levels | the tree says `truncated` |

The limits were set against the development corpus, whose largest document is
133.6 MB, whose slowest summary took 0.31 s and slowest path scan 5.2 s, and
whose largest tree has 725 nodes and 6 levels (3,501 documents).

### 8.9 Worker processes

The server process never opens a CAD file; a test records every document open
in it while every route is exercised, and finds none. Every document is read
in a `WorkerPool` (section 3.13):

- spawn processes started with the service, each with its own pipe; a job
  travels as JSON and its answer comes back as one JSON frame read with a
  length limit, plus one raw frame for an image. Nothing a worker sends is
  ever unpickled;
- a job that misses its deadline gets its worker killed and joined, and only
  then replaced; the request answers 504 `timeout` and the other workers carry
  on. A worker that dies answers 500 `worker_crashed`;
- a replacement that fails to start is tried again, with a wait that grows to
  30 s, for as long as the service runs, so a worker slot is never lost for
  good; each failure is logged, and while no worker is running `/v1/health`
  answers 503 (5.12);
- a worker's answer may be its route's size cap plus 64 KiB: the worker
  refuses a longer one before sending it, so a small crafted document cannot
  make the service process read and parse a huge answer;
- on Windows every worker runs in one Job Object that caps its memory, allows
  no further processes, ends a crashing worker without a dialog and ends every
  worker when the service ends. On Linux each worker sets `RLIMIT_AS` and asks
  to be killed when the service dies;
- workers open documents only below the configured roots (a job naming another
  folder is refused), read only the parts of a file the answer needs, and close
  the file when the job ends.

### 8.10 ETags and caching

- Every answer about one document carries an `ETag` computed from a `stat` of
  the file (size and modification time), the route, its schema version, the
  SolidSeas version and the query. `If-None-Match` with that tag answers 304
  with no body, without the file being read.
- A listing's `ETag` comes from the directory entries the page covers (names,
  kinds, sizes and modification times), read without opening a file, so a 304
  still costs a walk of the folder. It says nothing about how reading each
  file went, so a page holding an entry that may read differently later (an
  error that is `retryable`, such as `locked`, or `timeout` or
  `worker_crashed`) is sent without an `ETag`: no client can turn it into a
  304, and the next request reads the page again.
- A resolved answer (`resolve=1`), and a BOM, depends on every file under the
  roots, not on the document alone, so its `ETag` is computed from the answer
  itself, after the search: `If-None-Match` saves sending an unchanged answer
  again, not the search.
- `Cache-Control: private, no-cache`: a client may keep an answer and should
  revalidate it with `If-None-Match`. The service keeps no cache of its own.

### 8.11 Response headers

Every response, errors and 304 included, carries a status line (an HTTP/0.9
request is answered as HTTP/1.1, 8.6) and:

- `X-Content-Type-Options: nosniff`
- `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; sandbox`
- `Cross-Origin-Resource-Policy: same-origin`, so another site cannot embed a
  preview in an `<img>` to find out whether a file exists
- `Referrer-Policy: no-referrer` and `X-Frame-Options: DENY`
- `Cache-Control: private, no-cache`
- `Server: solidseas`, with no Python version
- `X-Request-Id`, the id the log line carries

JSON is `application/json; charset=utf-8`, compact and ASCII-only. No route
serves HTML, SVG or XML.

### 8.12 Logging

One line per request on standard error, in UTC: request id, client (the
token's name), peer address, method, route, root id, status, error code, the
refusal rule and component index, duration and bytes sent. A connection
closed because no complete request head arrived in time logs a line too, with
its peer and the rule (`head_deadline` when part of a head arrived,
`idle_connection` when a new connection sent nothing), so a flood of idle or
trickling connections shows. The worker pool logs each worker started, killed,
replaced or failing to start, with the number running. A connection refused
over the cap logs `code=busy reason=connections`.

Never logged: the query or any path, the token or the `Authorization` header,
and anything read from a file (property values, stored paths, warnings, the
reader's exception text). An internal error logs the exception's type and where
it was raised, as module, function and line, without file names, and the
response carries only the code `internal` and its `X-Request-Id`. A test plants
a property value, an account name, a path and a token, sends a mix of requests
and errors, and checks that none of them reaches the log, and that all of them
reach the path report.

### 8.13 What the service never does

- Write, create, rename or delete anything under a root, or lock a file. Its
  only write is its own token file, on first start.
- Follow a link, junction, mount point or hard link out of a root, or go
  through one: every component of a path is checked before the next is used.
  Nor does it read a cloud placeholder. With `--formats`, this holds for the
  files a model file names too (a glTF buffer, an OBJ material library, an
  Alibre component): they are opened under the document's own rules (3.20.1),
  and where they are is found with `lstat` one component at a time, refusing a
  link before it is crossed.
- Open, `stat` or `realpath` a path taken from file content outside its roots,
  or any path not built from a root and its index. A path a model file names is
  joined to the document's own folder only after it is refused if it climbs
  out (`..`, a drive, a UNC path, a scheme, a stream, a device), and an Alibre
  assembly's components are found by walking its own folder below the root,
  never by opening the path the file stores.
- Make an outbound connection. Its tests refuse every connection and name lookup
  to anything but loopback in the process that runs the service.
- Return an absolute path, a token or the reader's exception text. A model
  file's `references` give where a file was found relative to the document's
  folder, and a path that is not is sent as null.
- Serve HTML, SVG or XML, send CORS headers, or accept a credential in a URL.
- Parse a CAD file in the server process, or unpickle anything from a worker.

`docs/SECURITY_REVIEW.md` section 1 reviews these claims, marks each verified
or by inspection, and gives the commands that repeat the checks.

### 8.14 Running it as a background service

The service runs in the foreground until it is stopped, so a service manager
starts it and keeps it running. Whatever starts it, run it as an account that
can read the roots and nothing more, and keep the token file where only that
account (and administrators) can read it. The test suite does not run the
recipes below; both Windows ones were run as written on Windows 10 (a client
listed a folder and fetched a preview with the token, a request without it was
refused, and ending the task ended the service and its workers), and the
systemd one has not been run yet. After setting one up, check the exposure as
8.2 says.

**Windows, one workstation** (the user's own folders). A Scheduled Task that
starts at log on, as the user, with `pythonw.exe` so no window opens. From a
PowerShell prompt as that user:

```powershell
$py = "C:\Path\To\Python\pythonw.exe"   # the environment SolidSeas is installed in
$action = New-ScheduledTaskAction -Execute $py -Argument '-m solidseas serve --root jobs=D:\Jobs'
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "SolidSeas serve" -Action $action -Trigger $trigger -Settings $settings
```

- The settings matter: by default Task Scheduler stops a task after 72 hours,
  and does not start one, or stops it, while a laptop runs on battery.
- The token file is the default one, `%LOCALAPPDATA%\SolidSeas\serve-tokens`,
  created on the first start; the user's own clients read it from there.
- With no window there is no output: the ready line and the log go nowhere.
  When it does not start, the task's last run result is the exit code (3: the
  token file or the bind was refused; 1: a root is missing or the port is in
  use). Run the same command with `python.exe` in a console to see why.
- Ending the task ends the service, and its Job Object ends the workers.

**Windows, shared machine.** A Scheduled Task at start-up as LOCAL SERVICE,
which has no rights on file shares and none on the roots until you grant read
access (`icacls D:\Jobs /grant "*S-1-5-19:(OI)(CI)RX"`); a root on a share
needs a dedicated domain account instead. Install Python for all users, and
SolidSeas in an environment where only administrators can write (under
`C:\Program Files`), and let an administrator create the token file, so that
administrators can read the token to give it to clients. From an elevated
PowerShell prompt:

```powershell
$py = "C:\Program Files\SolidSeas\venv\Scripts\python.exe"
$dir = "C:\ProgramData\SolidSeas"
# Any user may create folders in ProgramData, and its owner keeps the right to change it:
# refuse one that is already there rather than adopt it.
if (Test-Path -LiteralPath $dir) { throw "$dir exists already: find out who made it, then remove it" }
New-Item -ItemType Directory $dir | Out-Null
icacls $dir /setowner "*S-1-5-32-544"
icacls $dir /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-19:(OI)(CI)R"
$tokens = "$dir\serve-tokens"
& $py -c "import secrets,sys; open(sys.argv[1], 'x').write('erp:' + secrets.token_urlsafe(32) + '\n')" $tokens
$action = New-ScheduledTaskAction -Execute $py -Argument "-m solidseas serve --root jobs=D:\Jobs --token-file $tokens"
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "NT AUTHORITY\LOCAL SERVICE" -LogonType ServiceAccount
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 `
  -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "SolidSeas serve" -Action $action -Trigger $trigger `
  -Principal $principal -Settings $settings
```

Install SolidSeas into that environment with `pip`, or with uv's
`--link-mode=copy`: uv otherwise links its files on Windows from its cache in
the installing user's profile, they keep that folder's access list, and LOCAL
SERVICE cannot read them (the task ends with exit code 1 and a
`PermissionError` on `solidseas\__main__.py`).

The folder is new, owned by Administrators, and its access list is set before
the token file exists, so the file never grants anyone but SYSTEM,
Administrators and LOCAL SERVICE, which the start-up check accepts (8.3). The
check verifies it on every start: a folder or file another account owns, or a
folder another account could write to, refuses the start (`not_owner`,
`folder_writable`). Add a line per client to the file, as an administrator,
and restart the task. The task restarts the service three times a minute
apart; on a machine other accounts use, watch for it staying stopped, because
a stopped service's port is anyone's (8.2). The task runs with no window, so its log
goes nowhere; to keep it, run the command through `cmd.exe /c` with `2>>` and a
log file in a folder LOCAL SERVICE may write.

**Linux, systemd.** A system user that can read the roots, and a unit such as
`/etc/systemd/system/solidseas.service`:

```ini
[Unit]
Description=SolidSeas REST service

[Service]
User=solidseas
ExecStart=/opt/solidseas/venv/bin/python -m solidseas serve --root jobs=/srv/cad/jobs --token-file /var/lib/solidseas/serve-tokens
StateDirectory=solidseas
StateDirectoryMode=0700
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadOnlyPaths=/srv/cad/jobs
CapabilityBoundingSet=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
IPAddressDeny=any
IPAddressAllow=localhost
MemoryMax=9G
KillMode=control-group
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- The service creates its token file in its state folder on the first start,
  with mode 0600; read the token from there as root to give it to clients.
- `MemoryMax` is the workers times their 2 GiB cap plus 512 MiB (four workers
  here). `KillMode=control-group` ends the workers with the service.
- Its log goes to the journal: `journalctl -u solidseas`.
- `IPAddressAllow=localhost` with `IPAddressDeny=any` keeps it on loopback even
  if someone later adds `--bind`. Drop both only for a remote bind (8.2).

**Docker.** A non-root user, a read-only filesystem, the roots mounted `:ro`,
`--bind 0.0.0.0 --allow-remote --allowed-host solidseas` inside a private
compose network, and no published port (or only `127.0.0.1:8765:8765`, through
which a client's identity check fails, 8.16).

### 8.15 Examples

With curl on Linux or macOS, keep the token in a header file only you can
read, so it stays out of command lines and shell history:

```sh
umask 077
printf 'Authorization: Bearer %s\n' "$(sed -n 's/^default://p' ~/.config/solidseas/serve-tokens)" \
  > ~/.config/solidseas/default.header

curl -sS --fail-with-body -H @"$HOME/.config/solidseas/default.header" \
  "http://127.0.0.1:8765/v1/list?root=jobs&path=Example&include=properties,preview"
curl -sS --fail-with-body -H @"$HOME/.config/solidseas/default.header" -o bracket.png \
  "http://127.0.0.1:8765/v1/preview?root=jobs&path=Example%2Fbracket.SLDPRT"
```

With PowerShell on Windows, read the token into a variable:

```powershell
$line = Get-Content "$env:LOCALAPPDATA\SolidSeas\serve-tokens" | Where-Object { $_ -like 'default:*' }
$auth = @{ Authorization = "Bearer " + $line.Substring(8) }
Invoke-RestMethod -Headers $auth "http://127.0.0.1:8765/v1/document?root=jobs&path=Example/bracket.SLDPRT"
Invoke-WebRequest -UseBasicParsing -Headers $auth -OutFile bracket.png `
  "http://127.0.0.1:8765/v1/preview?root=jobs&path=Example%2Fbracket.SLDPRT"
```

These examples send the token without checking the service first; on a
machine other accounts use, check it as 8.16 shows. Section 10 has a
TypeScript client and recipes.

### 8.16 Checking the service before sending the token

Whenever the service is stopped, any program on the machine can listen on its
port, and a client that calls it then hands that program its token (8.2,
security review finding 15). `GET /v1/identity` lets a client tell the real
service from such a program before the token leaves the client: the service
proves that it holds the client's token without sending it.

- The client makes up a fresh random nonce, 32 to 128 characters from
  `A-Z`, `a-z`, `0-9`, `_` and `-` (32 random bytes in hex or base64url), and
  calls `/v1/identity?client=NAME&nonce=NONCE` without an `Authorization`
  header. `NAME` is the name of its line in the token file.
- The service answers 200 with an `identity` envelope (5.12). Its `proof` is
  the HMAC-SHA256, in lowercase hex, keyed with the client's token (its ASCII
  text), of five lines joined by `\n` with no newline at the end:
  `solidseas-identity-v1`, the name, the nonce, and the address and port the
  connection reached on the service's side. The address is written as IPv4
  (`127.0.0.1`) or compressed IPv6 (`::1`), an IPv4-mapped IPv6 address as
  IPv4.
- The client computes the same HMAC with its own token, its nonce and the
  address and port it connected to, and compares the two in constant time. It
  sends its token only when they match, and only on that same connection
  where its HTTP library allows (see When to check). Any other outcome (a
  connection error, another status, a body that is not this JSON, a proof that
  differs) means the token must not be sent: stop and report, as 8.2 says.

Why it holds. Only a holder of the token can compute the proof, and the HMAC
does not give the token away. A fresh nonce makes an answer recorded earlier
worthless, so a program cannot collect proofs while the service runs and
replay them once it has taken the port. And the proof covers the address and
port the connection reached, so a program listening elsewhere that forwards
the question to the real service (on `[::1]:8765` while the service holds
`127.0.0.1:8765`, say, for a client that calls `localhost`) gets back a proof
for the service's own address, which that client rejects. Call the service by
its address (`127.0.0.1`), not by a name, and compute with that address; a
client that does call a name computes with the peer address of the connection,
as the Python example does. For a remote bind (8.2), whose clients call it by a
name, add the service's address to its `--allowed-host` names, so that a client
that cannot see the peer address (Node's `fetch`) can call the address instead.
Behind a port mapping (a published container port, a proxy) the service sees
the forwarded connection, not the address the client called, so the check
fails, and fails closed: run such clients inside the container network.

The route needs no token, so it answers anyone: an unknown name gets a proof
too, under a stand-in key derived from all the configured tokens, which no
token matches and no one without them can compute. Like a real name's proof,
it stays the same across restarts for as long as the token file does, so the
answer does not tell which names exist. (Once the file is edited, every
unknown name's proof changes while a name whose line was kept keeps its own,
so someone who asked before and after an edit can tell which names it kept.)
It reads no document, its query is never logged, and it does not count toward
the failure limit of 8.3. Because anyone may ask, a proof also lets anyone
test guesses at a client's token offline, as fast as they can compute HMACs:
make every token with `secrets.token_urlsafe(32)` (8.3), which no amount of
guessing reaches.

**When to check.** A check covers the connection it was made on, and no
other. Send the token on that connection alone, and check a new connection for
the next request: the Python and TypeScript examples below do. Checking first
does not protect a client whose HTTP library keeps connections open and picks
one for each request, as Node's `fetch` and Windows PowerShell's
`Invoke-RestMethod` do. Its pool can hold a connection that another program
accepted while the service was stopped; once the service runs, that program
can forward the check over it to the service, which answers for the same address
and port, and then receive the token on the same connection. In a test here,
`fetch` in a long-running Node process sent its check over such a connection
and the check passed. A client that opens a new connection for every call, as
curl does and as PowerShell does with `-DisableKeepAlive` on every call to the
service, sends the check and then the token to whatever holds the port at
that moment; that leaves the moment between the two, which a program can use
only if the service happens to stop in it.

**Python**, standard library only:

```python
import hashlib
import hmac
import http.client
import ipaddress
import json
import secrets

SCHEME = "solidseas-identity-v1"


class NotTheService(Exception):
    """What answered could not prove it holds this client's token; the token was not sent."""


def checked_connection(host: str, port: int, client: str, token: str) -> http.client.HTTPConnection:
    """A connection to the service that proved it holds ``token``. Send the token on this
    connection alone: it never reconnects by itself, and a new one must be checked again."""
    conn = http.client.HTTPConnection(host, port, timeout=70)
    nonce = secrets.token_urlsafe(32)
    peer, proof, status = None, None, None
    try:
        conn.request("GET", f"/v1/identity?client={client}&nonce={nonce}")
        peer = conn.sock.getpeername()[:2]  # where this connection really went
        answer = conn.getresponse()
        status = answer.status
        proof = json.loads(answer.read(65536))["data"]["proof"]
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
        pass
    if peer is not None:
        ip = ipaddress.ip_address(peer[0].split("%")[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        message = "\n".join([SCHEME, client, nonce, str(ip), str(peer[1])]).encode("ascii")
        expected = hmac.new(token.encode("ascii"), message, hashlib.sha256).hexdigest()
        proved = isinstance(proof, str) and hmac.compare_digest(proof.encode(), expected.encode())
        if status == 200 and proved:
            conn.auto_open = 0  # a closed connection raises NotConnected instead of reconnecting
            return conn
    conn.close()
    raise NotTheService(f"{host}:{port} could not prove it holds the token for {client}")


if __name__ == "__main__":
    import os

    token = os.environ["SOLIDSEAS_TOKEN"]  # or read the client's line from the token file
    conn = checked_connection("127.0.0.1", 8765, "erp", token)
    conn.request("GET", "/v1/document?root=jobs&path=Example/bracket.SLDPRT",
                 headers={"Authorization": f"Bearer {token}"})
    print(json.loads(conn.getresponse().read())["data"]["doc_type"])
```

**curl**, on Linux or macOS, with the token file and header file of 8.15. The
HMAC is left to Python's standard library, which reads the token from the
token file: `openssl dgst -hmac` would need the token on its command line,
where other accounts can read it.

```sh
check_service() {  # $1 the client's name: succeeds only for the service holding its token
  nonce=$(openssl rand -hex 32)
  curl -sS --max-time 10 -w '\n%{remote_ip} %{remote_port}' \
      "http://127.0.0.1:8765/v1/identity?client=$1&nonce=$nonce" |
    python3 -c '
import hashlib, hmac, json, os, sys
client, nonce = sys.argv[1:]
tokens = os.path.expanduser("~/.config/solidseas/serve-tokens")
token = next((l.strip()[len(client) + 1:] for l in open(tokens) if l.startswith(client + ":")), "")
try:
    body, _, peer = sys.stdin.read().rpartition("\n")
    address, port = peer.split()
    proof = json.loads(body)["data"]["proof"]
except (ValueError, KeyError, TypeError):
    proof = None
message = "\n".join(["solidseas-identity-v1", client, nonce, address, port]) if proof else ""
expected = hmac.new(token.encode(), message.encode(), hashlib.sha256).hexdigest()
if not proof or not hmac.compare_digest(str(proof).encode(), expected.encode()):
    sys.exit("not the SolidSeas service that holds the token: nothing was sent")
' "$1" "$nonce"
}

check_service default &&
  curl -sS --fail-with-body -H @"$HOME/.config/solidseas/default.header" \
    "http://127.0.0.1:8765/v1/list?root=jobs&path=Example"
```

**PowerShell**, on Windows, with the token read as in 8.15. Pass
`-DisableKeepAlive` to every call to the service: Windows PowerShell 5.1 keeps
connections open between calls, and in a test here a call with
`-DisableKeepAlive` still went out on a connection that an earlier call
without it had left open.

```powershell
function Test-SolidSeasService([string]$Client, [string]$Token) {
  $bytes = New-Object byte[] 32
  [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $nonce = -join ($bytes | ForEach-Object { $_.ToString('x2') })
  try {
    $answer = Invoke-RestMethod -DisableKeepAlive -TimeoutSec 10 `
      "http://127.0.0.1:8765/v1/identity?client=$Client&nonce=$nonce"
  } catch { return $false }
  $message = "solidseas-identity-v1`n$Client`n$nonce`n127.0.0.1`n8765"
  $hmac = New-Object Security.Cryptography.HMACSHA256 (, [Text.Encoding]::ASCII.GetBytes($Token))
  $hash = $hmac.ComputeHash([Text.Encoding]::ASCII.GetBytes($message))
  return [string]$answer.data.proof -ceq (-join ($hash | ForEach-Object { $_.ToString('x2') }))
}

$token = (Get-Content "$env:LOCALAPPDATA\SolidSeas\serve-tokens" | Where-Object { $_ -like 'default:*' }).Substring(8)
if (-not (Test-SolidSeasService 'default' $token)) { throw "not the SolidSeas service: the token was not sent" }
Invoke-RestMethod -DisableKeepAlive -Headers @{ Authorization = "Bearer $token" } `
  "http://127.0.0.1:8765/v1/document?root=jobs&path=Example/bracket.SLDPRT"
```

**TypeScript**, for the client of 10.1, with Node's own `node:http` and no
package. Each request gets a `CheckedConnection`: one connection, opened once,
on which the check and then the request with the token go. `fetch` is not used,
because it picks a pooled connection for each request, which the check may
not have covered.

```ts
import { Agent, request } from "node:http";
import type { IncomingHttpHeaders } from "node:http";
import { createConnection } from "node:net";
import type { NetConnectOpts, Socket } from "node:net";
import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";

// One connection to the service, opened once. The check and the request that carries the
// token both go on it; if it closes in between, the request fails instead of going out on
// a new connection that the check never covered.
export class CheckedConnection extends Agent {
  #opened = false;

  constructor() {
    super({ keepAlive: true, maxSockets: 1 });
  }

  createConnection(options: NetConnectOpts, done: (err: Error | null, socket?: Socket) => void) {
    if (this.#opened) {
      done(new Error("the checked connection closed; the token was not sent"));
      return undefined;
    }
    this.#opened = true;
    return createConnection(options);
  }
}

export type Answer = { status: number; headers: IncomingHttpHeaders; body: Buffer };

export function send(conn: CheckedConnection, path: string, headers: Record<string, string>, ms: number) {
  return new Promise<Answer>((resolve, reject) => {
    const options = { host: HOST, port: PORT, path, headers, agent: conn, signal: AbortSignal.timeout(ms) };
    const req = request(options, (res) => {
      const chunks: Buffer[] = [];
      res.on("data", (chunk: Buffer) => chunks.push(chunk));
      res.on("error", reject);
      res.on("end", () => resolve({ status: res.statusCode ?? 0, headers: res.headers, body: Buffer.concat(chunks) }));
    });
    req.on("error", reject);
    req.end();
  });
}

export async function checkService(conn: CheckedConnection): Promise<void> {
  const nonce = randomBytes(32).toString("base64url");
  let proof = "";
  try {
    const res = await send(conn, `/v1/identity?client=${CLIENT}&nonce=${nonce}`, {}, 10_000);
    const body = JSON.parse(res.body.toString("utf8"));
    if (res.status === 200 && typeof body?.data?.proof === "string") proof = body.data.proof;
  } catch {
    // a connection error, or a body that is not JSON: no proof
  }
  const message = ["solidseas-identity-v1", CLIENT, nonce, HOST, String(PORT)].join("\n");
  const expected = Buffer.from(createHmac("sha256", TOKEN).update(message).digest("hex"));
  const got = Buffer.from(proof);
  if (got.length !== expected.length || !timingSafeEqual(got, expected)) {
    throw new Error(`${HOST}:${PORT} could not prove it holds the token; it was not sent`);
  }
}
```

From Python, `solidseas.serve.identity_proof(token, client=..., nonce=...,
address=..., port=...)` computes the proof (provisional, as the rest of
`solidseas.serve`'s Python API).

## 9. Stability policy and deprecations

This policy is in effect from 0.2.0. Releases before 0.2.0 were provisional
and are not covered.

**What is stable.**

- These Python names, with the signatures and behaviour this document gives
  them, except the parts it marks provisional:

  | Module | Stable names |
  |---|---|
  | `solidseas` | every name in its `__all__`: `open_document`, `Document`, `FileInfo`, `SummaryFields`, `ReaderWarning`, `scan`, `Scan`, `Root`, `Roots`, `SolidSeasDeprecationWarning`, `__version__` and the exception classes of 3.3 |
  | `solidseas.formats.solidworks` | `open_document`, `Document`, `FileInfo`, `SummaryFields`, `SavedVersion`, `Configuration`, `Property`, `Preview`, `ReaderWarning`, `Reference`, `Instance`, `ReferenceSet`, `ComponentTree`, `ComponentNode`, `ComponentFile`, `ConfigurationCounts`, `Transform`, `Placement`, `PathReport`, `SOLIDWORKS_EXTENSIONS` and the exception classes |
  | `solidseas.model` | `dumps`, `envelope`, `error_envelope`, `error_info`, `error_code`, `ERROR_CODES`, `KINDS` |

  The objects a stable call returns are stable in the fields this document
  lists, whether or not their class can be imported by name: the path report's
  `FoundPath`, `Account`, `Host`, `IdentityField` and their locations, for
  example.
- The JSON kinds, their fields and their schema versions (4.3), the error codes
  (5.6) and the warning codes (3.5, 5.10).
- CLI command names, options, `--json` output and exit codes (section 7).
- REST routes, parameters, status codes, headers and error codes (section 8).

A name in an `__all__` that the table does not list is provisional:
`Container`, `open_container`, `detect_format`, `release_name`, `Metadata`,
`Mesh`, `EmbeddedPath`, `ParasolidBody`, `ParasolidResult`, `RawTransmit`,
`StreamInfo`, `DrawingSheet` and `DrawingView` in
`solidseas.formats.solidworks`, and everything else in `solidseas.model`
(the builders, the field helpers and the constants).

**What is provisional** can change in any release, a patch release included,
with a note in `CHANGELOG.md`. Every commit is a patch release (below), so a
provisional item can change at any commit. It is:

- On `Document`: `metadata`, `container`, `streams()`, `read_stream()`,
  `nested_documents()`, `open_nested()`, `mesh()`, `parasolid()`,
  `embedded_paths()` (and `EmbeddedPath`), `sheets()` (and a `ReferenceSet`'s
  `sheets`), `resolve_references()`, `display_geometry()`, `tessellate()` and
  `bom()`;
  `Metadata` and
  its carriers; the `units` keys `raw` and `source`; the property internals
  `pid`, `vt`, `type_id`, `is_equation` and `expression_source`.
- The `export` command, its `export_result` kind, the error codes
  `nothing_to_export` with `NothingToExportError` and `not_representable` with
  `NotRepresentableError`, the warning codes of 3.17 and 3.19,
  the skip reasons `out_of_range` and `surfaces_only`, and 3.14's
  `bodies_not_asked`.
- `open_document`'s `within` and `refuse_hard_links`, and `scan`'s `pool`,
  `file_timeout`, `within`, `root_id`, `folder_rel` and `after`, with
  `Scan.fingerprint()`.
- The catalog (3.18), while it is new: `solidseas.catalog` and its modules;
  the commands `index`, `where-used`, `search`, `duplicates`, `missing`,
  `changes`, `catalog`, `catalogs` and `clear-index`; the kinds `catalog`,
  `catalog_list`, `catalog_cleared`, `catalog_scan`, `where_used`,
  `catalog_search`, `duplicates`, `missing_references` and `catalog_changes`;
  the routes `/v1/catalog`, `/v1/where-used` and `/v1/search` with `serve
  --catalog` and `--catalog-rescan`; the error codes `not_in_catalog` and
  `catalog_incompatible` with `NotInCatalogError`, `CatalogIncompatibleError`
  and `BusyError`; the rules `catalog_locked`, `catalog_scanning`,
  `no_free_worker`, `not_a_catalog`, `too_new`, `damaged` and
  `unexpected_schema`; and the warning
  codes `cycle`, `low_confidence`, `quantity_unknown` and `unread_documents`.
- Model files (3.20) and rendered previews (3.21), while they are new: the
  modules `solidseas.formats` (but `solidseas.formats.solidworks`),
  `solidseas.formats.registry`, `base`, `limits`, `_source` and `stl`, and
  `solidseas.render`; `FormatNotSupportedError` (in `solidseas.__all__`) and
  `UnsupportedOperationError` with the error code `format_not_supported` and
  the rules `no_reader` and `model_file`; the kind `model_summary`; the
  listing's `model` field, its `unsupported` status and count; `export_result`'s
  `source_format` and `file_written`'s `source`; the jobs `model_summary`,
  `model_entry`, `model_properties` and `model_preview`; `scan`'s `formats`
  and `foreign_pool`; the CLI's `list --formats`, `serve --formats`,
  `preview --render` and `--stored`, and `--max-mb` on `info`, `preview` and
  `export`; `ServeConfig.formats`, `/v1/list`'s `formats` and `/v1/preview`'s
  `render`; and the warning codes of 3.5's model-file table and 3.20.
- SOLIDWORKS through SolidSeas' own instance (3.22), while the bridge is new:
  `solidseas.swapi` and its modules, `python -m solidseas.swapi` with its
  options, exit codes and `report.tsv`, and the operations, protocol and error
  codes of `SolidSeas.SwBridge.exe`.
- The AI connector (3.23), while the assistant is built: `solidseas.ai` and
  its modules, `solidseas.policy`, `solidseas_app.assistant`, the
  `AI_ERROR_CODES`, the plan and draft reply shapes, and `usage.json`.
- The Python APIs of `solidseas.walk`, `solidseas.resolve`,
  `solidseas.workers`, `solidseas.jobs`, `solidseas.geometry`,
  `solidseas.tessellate`, `solidseas.bom`, `solidseas.export`, `solidseas.step` and
  `solidseas.serve`
  (`ServeConfig`, `Server`), and
  `solidseas.formats.solidworks.paths.scan_bytes` and
  `solidseas.formats.solidworks.facetess`. What they
  produce as JSON is stable: the listing, the `references` kind with its
  resolution results, and the service's answers, but for the `bom` kind, the
  `bom` command and `/v1/bom`, which are provisional while BOMs are new.

Internal, and never covered: warning text, the human-readable CLI output, the
service's log format, and every module and name this document does not
mention.

**Releases.**

- Every commit bumps at least the patch version, as `AGENTS.md` requires.
- A breaking change to a stable item bumps the minor version (0.2 to 0.3) in
  the same commit, with a `CHANGELOG.md` entry under "Changed" or "Removed"
  that says how to migrate. Patch releases never break a stable item.

**JSON.**

- Fields may be added in any release; consumers must ignore fields they do not
  know.
- Enums are open (C8).
- Removing, renaming or retyping a field, or changing its meaning, bumps that
  kind's `schema_version`. Phase 1 does not serve the previous version
  alongside the new one.

**Deprecation.**

- A deprecated Python name emits `solidseas.SolidSeasDeprecationWarning`, a
  `DeprecationWarning` subclass, when used. Python shows a
  `DeprecationWarning` only when it is raised by code in `__main__`, so a
  warning raised in an integration's own modules is silent by default: run its
  tests with `python -W default::DeprecationWarning` (pytest shows them in its
  summary) to see them. Removal comes no earlier than the next minor release
  and no earlier than 60 days after the deprecation shipped.
- `Document.embedded_paths()` and `EmbeddedPath` stay provisional:
  `path_report()` is the stable way to read the paths a file stores.
- Deprecated in 0.2.0, and warning: `Reference.quantity` and `Document.info()`
  (use `summary()`). Neither is removed before 0.3.0. For `quantity`, use
  `Document.reference_set(configuration).files[reference.key]`: its
  `instances` are the counts of that configuration, with 0 for a file it does
  not use and None for a drawing's models, and its `per_configuration` gives
  every configuration's counts side by side, as the `references` kind does.
  `Document.components(configuration).files` holds only the files that
  configuration uses, and `components()` is None for a drawing, so it is no
  replacement.
- No CLI command, option, REST route or parameter is deprecated.

**1.0** comes when Phase 1's "done when" passes, the three-surface identity test
passes on the development corpus, and one minor release has gone by without a
breaking change to a stable item.

## 10. Examples and recipes

Each recipe was run against the test fixtures (Python and the CLI) or a service
serving them (curl, PowerShell, and the TypeScript as written, run by Node 24,
which strips the types). File and folder names are examples.

### 10.1 A TypeScript client for the service

For the server side of the store or of any Node service. It never runs in a
shopper's browser: the service refuses browser requests (8.4), and a token in a
page would be anyone's.

```ts
// An address, not "localhost": on Windows a refused localhost connection costs seconds
// (8.2), and the identity check covers the address called (8.16).
const HOST = "127.0.0.1";
const PORT = 8765;
const CLIENT = "store"; // this client's line in the token file
const TOKEN = process.env.SOLIDSEAS_TOKEN ?? "";

type Envelope<T> =
  | { ok: true; kind: string; schema_version: number; data: T }
  | { ok: false; kind: "error"; error: { code: string; retryable: boolean; detail: object | null } };

export class SolidSeasError extends Error {
  status: number;
  code: string;
  retryable: boolean;
  retryAfter: number | null;
  constructor(status: number, code: string, retryable: boolean, retryAfter: number | null) {
    super(`${status} ${code}`);
    this.status = status;
    this.code = code;
    this.retryable = retryable;
    this.retryAfter = retryAfter;
  }
}

// One request on a new connection, sent only after the service proved on that connection
// that it holds the token (8.16). 70 s is longer than the longest deadline, a listing
// page's 60 s.
export async function call(
  route: string,
  params: Record<string, string>,
  headers: Record<string, string> = {},
  ms = 70_000,
) {
  const conn = new CheckedConnection();
  try {
    await checkService(conn);
    const path = `/v1/${route}?${new URLSearchParams(params)}`;
    return await send(conn, path, { Authorization: `Bearer ${TOKEN}`, ...headers }, ms);
  } finally {
    conn.destroy();
  }
}

export async function get<T>(route: string, params: Record<string, string>, etag?: string) {
  const res = await call(route, params, etag ? { "If-None-Match": etag } : {});
  if (res.status === 304) return { notModified: true as const, etag };
  const body = JSON.parse(res.body.toString("utf8")) as Envelope<T>;
  if (!body.ok) {
    const after = res.headers["retry-after"]; // 503 busy or root_unavailable, 429 too_many_failures
    throw new SolidSeasError(res.status, body.error.code, body.error.retryable, after === undefined ? null : Number(after));
  }
  return { notModified: false as const, data: body.data, etag: res.headers.etag };
}
```

`CheckedConnection`, `send` and `checkService` are the code of 8.16, which
goes in this module. `call` opens a new connection for each request, checks
the service on it, sends the token on it alone and closes it; `get` reads the
JSON answer. That costs a connection and one more round trip on loopback, and
keeps the token from a program that took the port while the service was
stopped, including through a connection that program accepted then and kept
open, which a pooled client such as `fetch` could pick for a later request.

Retry an error with a `retryAfter` after that many seconds, with some jitter,
and one that is `retryable` without it (`locked`) on a later pass; any other
error is an answer about the file or the request (5.6).

### 10.2 Keep an ERP's part list in step with a folder

Poll the listing with `If-None-Match`: a page whose entries have not changed
answers 304 at the cost of a directory walk, without a file being read (8.10).
Keep each page's `ETag`, `next_cursor` and paths by the cursor that fetched it,
and compare each file's `mtime_ns` as text (section 6). A page with an entry
that may read differently next time (a `retryable` error such as `locked`)
comes without an `ETag`, and its memo is dropped, so the next run reads it
again. A run that read every page removes from the ERP the files it no longer
saw.

```ts
type Entry = {
  path: string;
  type: "file" | "folder";
  status: string; // ok, error, skipped, link, placeholder, not_solidworks: an open set
  file: { name: string | null; size: number | null; mtime_ns: string | null } | null;
  properties: { name: string; type: string; value: unknown; text: string }[] | null;
  error: { code: string; retryable: boolean } | null;
};
type Listing = { entries: Entry[]; next_cursor: string | null; truncated_reason: string | null };
type Memo = { etag: string; next: string | null; paths: string[] };

export async function syncFolder(
  known: Map<string, string>, // path -> mtime_ns, kept by the ERP between runs
  pages: Map<string, Memo>, // by cursor, "" for the first page
  upsert: (path: string, properties: Record<string, string>) => void,
  remove: (path: string) => void,
) {
  const query = { root: "jobs", path: "Example", recursive: "1", include: "properties", limit: "500" };
  const seen = new Set<string>();
  let complete = true; // every page read to the end of the listing
  let cursor = "";
  for (;;) {
    const memo = pages.get(cursor);
    const page = await get<Listing>("list", cursor ? { ...query, cursor } : query, memo?.etag);
    let next: string | null;
    if (page.notModified) {
      next = memo!.next; // nothing on this page changed
      for (const p of memo!.paths) seen.add(p);
    } else {
      const paths: string[] = [];
      let again = false; // an entry to read again next run
      for (const e of page.data.entries) {
        if (e.type !== "file") continue;
        paths.push(e.path);
        seen.add(e.path);
        if (e.error?.retryable) again = true;
        if (e.status !== "ok" || !e.file?.mtime_ns) continue; // see below
        if (known.get(e.path) === e.file.mtime_ns) continue; // compared as text, never as a number
        upsert(e.path, Object.fromEntries((e.properties ?? []).map((p) => [p.name, p.text])));
        known.set(e.path, e.file.mtime_ns);
      }
      next = page.data.next_cursor;
      const cut = !next && page.data.truncated_reason !== null; // a limit ended the listing early
      if (cut) complete = false;
      if (page.etag && !again && !cut) pages.set(cursor, { etag: page.etag, next, paths });
      else pages.delete(cursor); // no tag (8.10), an entry to retry or a cut: read it again next time
    }
    if (!next) break;
    cursor = next;
  }
  if (complete) {
    for (const path of [...known.keys()]) {
      if (!seen.has(path)) {
        remove(path); // deleted, renamed or moved out of the folder
        known.delete(path);
      }
    }
  }
}
```

- `properties` are the active configuration's effective properties (5.7).
  `text` is what SOLIDWORKS stores; `value` is typed by `type` (5.3).
- An entry whose `error.retryable` is true (`locked`: SOLIDWORKS was saving it)
  is listed again on the next run: its page carries no `ETag` (8.10), and the
  loop keeps no memo of a page with such an entry. Other errors are about the
  file. `link` and `placeholder` entries were deliberately not read (3.7).
- Deletions: a file that is not on any page of a run that read the whole
  listing has gone, renamed or moved; the loop removes it. A run whose last
  page has no `next_cursor` but a `truncated_reason` (the walk's `max_examined`,
  or a deadline before the first entry) was cut short and removes nothing. A
  file renamed or moved shows as one removal and one new file.
- From the command line, `solidseas list D:\Jobs\Example --recursive --include
  properties --preview none --json` gives the same entries in one listing, but
  with paths relative to the listed folder (`o02_boxA.SLDPRT`) rather than to
  the root (`Example/o02_boxA.SLDPRT`): an integration that moves between the
  two must re-key its records (section 1.2).

With curl, the same check for a folder of up to 500 entries:

```sh
H="$HOME/.config/solidseas/default.header"
URL="http://127.0.0.1:8765/v1/list?root=jobs&path=Example&recursive=1&include=properties&limit=500"
curl -sS -D headers.txt -H @"$H" -o listing.json "$URL"
etag=$(sed -n 's/^[Ee][Tt][Aa][Gg]: //p' headers.txt | tr -d '\r')
curl -sS -o /dev/null -w '%{http_code}\n' -H @"$H" -H "If-None-Match: $etag" "$URL"   # 304 until it changes
```

### 10.3 Invoice from a configuration's properties

```python
from solidseas import open_document

def invoice_fields(path, configuration=None):
    """Part number, description and material of one configuration (the active one by default)."""
    with open_document(path) as doc:
        props = {p.name.casefold(): p for p in doc.effective_properties(configuration)}
        cfg = doc.configuration(configuration)
        number, description = props.get("partno"), props.get("description")
        return {
            "configuration": cfg.name if cfg else None,
            "part_number": number.text if number else None,
            "description": description.text if description else None,
            "material": cfg.material if cfg else doc.material,
        }
```

- Effective properties are the file's custom properties overridden by the
  configuration's own (3.4); names compare case-insensitively, as in
  SOLIDWORKS.
- A property with `linked=True` (such as a mass or material link) holds the
  value SOLIDWORKS computed at its last save, which can be stale (FORMAT 11.1).
- An unknown configuration name raises `ConfigurationNotFoundError`.
- From the command line: `solidseas props D:\Jobs\Example\bracket.SLDPRT
  --configuration Long --json`; over HTTP: `/v1/properties?root=jobs&path=...
  &configuration=Long`.

### 10.4 A store product page: thumbnail and component list

```ts
type ComponentFile = {
  file_name: string | null;
  doc_type: string | null;
  virtual: boolean;
  instances_in_bom: number | null;
};
type Components = { configuration: string | null; files: ComponentFile[]; truncated: boolean };

export async function productPage(path: string) {
  const res = await call("preview", { root: "jobs", path }, {}, 20_000); // 10.1: checked first
  let thumbnail: Buffer | null = null; // PNG bytes, checked by the service before sending
  if (res.status === 200) thumbnail = res.body;
  else {
    const { error } = JSON.parse(res.body.toString("utf8")); // errors are JSON envelopes on the preview route too
    if (error.code !== "no_preview") throw new SolidSeasError(res.status, error.code, error.retryable, null);
  }
  const tree = await get<Components>("components", { root: "jobs", path });
  if (tree.notModified) throw new Error("no ETag was sent");
  const components = tree.data.files
    .filter((f) => f.doc_type === "part" && (f.instances_in_bom ?? 0) > 0) // a parts list, every level
    .map((f) => {
      const name = (f.file_name ?? "").replace(/\.sld(prt|asm)$/i, "");
      return { name: f.virtual ? name.split("^")[0] : name, quantity: f.instances_in_bom }; // virtual: "Name^Assembly"
    });
  return { thumbnail, components, configuration: tree.data.configuration };
}
```

- About a third of real parts store no preview (`no_preview`, 404): show a
  placeholder.
- This is a parts list: every part at any level, with its count through every
  level (`instances_in_bom`, leaving out suppressed and excluded instances and
  their children), as the part rows of an indented BOM add up. Sub-assemblies
  are not listed themselves; without the `doc_type` filter the list would mix
  them with the parts inside them, counting a part once at the top and again
  inside its sub-assembly. For a top-level list instead (each direct
  component, sub-assemblies as one item), count the tree's `children` that are
  neither suppressed nor excluded, by `file` (3.9). Either is a count, not a
  bill of materials: for rows grouped, numbered and described as SOLIDWORKS'
  BOM tables, ask `/v1/bom?type=parts` (or `type=top`, `type=indented`) for
  the `bom` kind (3.16, 5.13).
- Show shoppers names and counts only: never `stored_path`, resolution results
  or a path report, which name folders, servers and people (3.12).

### 10.5 Check a file before sending it to a customer

```text
solidseas paths D:\Jobs\Example\frame.SLDASM
```

It lists every path and user name the file and the documents nested in it
would reveal, and exits 4 when something could not be read, so a script can
refuse to send a file it could not check. In Python:

```python
from solidseas import open_document

with open_document("frame.SLDASM") as doc:
    rep = doc.path_report()
if not rep.complete:
    print("not everything could be read:", [(i.reason, i.stream) for i in rep.incomplete])
for p in rep.paths:
    if p.severity == "high":
        print(p.reason, p.category, p.path)          # project folders, servers, references
print(sorted(a.name for a in rep.accounts))         # user names, template authors included
```

SolidSeas never rewrites the file: removing what the report lists means saving
a new document in SOLIDWORKS or sending a neutral format, such as the Parasolid
bodies `solidseas parasolid` writes.

## 11. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Every call takes about 2 seconds more on Windows | The client calls `localhost`, which tries the other address family first. Call `127.0.0.1` |
| 401 `unauthorized` | No `Authorization: Bearer` header, or a token not in the token file. The file is read at start: restart the service after editing it |
| 403 `forbidden_host` | The `Host` header names another name or port. Call the bound address, or start the service with `--allowed-host` for that name (8.2, 8.4) |
| 403 `forbidden_origin` | The request came from a page in a browser. Call the service from the server side |
| 429 `too_many_failures` | More than 20 failed tokens in a minute from that address. Fix the token and wait a minute |
| 503 `busy` just after the start | A root's folder index is still being built. Retry after `Retry-After` seconds; `/v1/roots` shows each root's state |
| 404 `not_found` for a file that exists | The path is an 8.3 short name, matches two names that differ only by case, or holds a `+` sent unescaped (send `%2B`). The service finds paths in its index, in the on-disk spelling (8.5) |
| 403 `link_refused` | A link, junction or mount point lies on the path, or the file has a second name (a hard link). The service never follows one (8.5) |
| 409 `placeholder_file` | A OneDrive or other cloud file that is online only. SolidSeas never downloads one: make it available offline |
| 423 `locked` | SOLIDWORKS, or another program, holds the file locked. Retry later |
| 504 `timeout` | Reading the file took longer than the route's deadline (8.8); the worker was replaced. A huge or damaged file |
| 422 `response_too_large` | A component tree or listing over its size cap (8.6). Lower `max_nodes` or `max_depth`, or `limit` for a listing |
| The CLI exits 4 | A partial result: some entries of a listing or batch failed, a resolution index was cut short, or a path report is incomplete. The JSON says which |
| `solidseas serve` exits 3 at start | The bind was refused (8.2) or the token file cannot be used (8.3); the error names the rule. `not_owner` or `folder_writable`: the file or its folder belongs to, or can be changed by, another account; `folder_missing`: create the `--token-file` folder first |
| 503 `busy` from `/v1/health`, rule `no_workers` | Every worker process was lost and none has started again yet (memory pressure, a read stuck on a share). The service keeps trying; its log says why each start failed |
| A resolution misses files on a share root, with `index_partial` | Each `resolve=1` walks the roots again within the route's 15 s deadline (8.6); a root too large or too slow to walk in time is cut short. Serve a smaller root, or resolve from Python with a longer `max_seconds` |
| `solidseas serve` exits 1 at start | A root does not exist, or the port is in use (`address_unavailable`) |
