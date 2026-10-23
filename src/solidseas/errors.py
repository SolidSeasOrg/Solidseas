"""Exceptions and reader warnings shared by every SolidSeas surface.

Every exception SolidSeas raises on purpose derives from :class:`SolidSeasError`
and carries ``code``, a stable machine-readable error code. The JSON error
object, the CLI exit code and the REST status are all derived from that code
by :func:`solidseas.model.error_info` and ``solidseas.model.ERROR_CODES``.
``docs/API.md`` lists the codes.

The reader classes keep their names and bases from 0.1: ``SldError`` and its
subclasses are still importable from :mod:`solidseas.formats.solidworks` and
still catch exactly what they caught before. They now also derive from
``SolidSeasError``.

A :class:`ReaderWarning` is a problem the reader worked around. It is a ``str``
holding the human-readable text, so code written for the 0.1 string warnings
keeps working, and it also carries ``code``, ``stream`` and ``message``.
"""

from typing import Any


class SolidSeasError(Exception):
    """Base class for every error SolidSeas raises on purpose.

    ``code`` is the stable error code. ``detail`` holds structured, safe facts
    (a stream name, a parameter name, a refused rule, a limit), never document
    content or an absolute path; it is None when there is nothing to add.
    """

    code: str = "internal"
    detail: dict[str, Any] | None = None

    def __init__(self, *args: Any, detail: dict[str, Any] | None = None) -> None:
        super().__init__(*args)
        if detail is not None:
            self.detail = dict(detail)


class InvalidArgumentError(SolidSeasError, ValueError):
    """A caller passed an argument SolidSeas does not accept (``detail["parameter"]`` names it)."""

    code = "invalid_argument"


# --------------------------------------------------------------------------- reading documents
class SldError(SolidSeasError):
    """Base class for every error raised by the SOLIDWORKS readers."""

    code = "damaged_file"


class UnknownFormatError(SldError):
    """The data is neither a 2015+ SOLIDWORKS container nor an OLE compound file."""

    code = "unknown_format"


class LockedFileError(SldError, OSError):
    """Another process (usually SOLIDWORKS) holds the file with an incompatible share mode."""

    code = "locked"


class SldFormatError(SldError):
    """The container or a stream inside it is malformed or inconsistent."""


class SldIntegrityError(SldFormatError):
    """Decoded data does not match its declared size or checksum."""


class SldLimitError(SldFormatError):
    """A safety cap (stream size, directory size, nesting depth, node count) was exceeded."""

    code = "limit_exceeded"


class FileTooLargeError(SldLimitError):
    """The file is larger than the ``max_file_bytes`` the caller allowed. Nothing was read."""

    code = "file_too_large"


class ParasolidError(SldFormatError):
    """An embedded Parasolid transmit could not be read, converted or written."""


class _PlainMessageKeyError(SolidSeasError, KeyError):
    """A ``KeyError`` whose ``str()`` is its message, not the repr of its argument."""

    def __str__(self) -> str:
        return Exception.__str__(self)


class StreamNotFoundError(_PlainMessageKeyError):
    """The document has no stream by that name. Also a ``KeyError``."""

    code = "stream_not_found"


class ConfigurationNotFoundError(_PlainMessageKeyError):
    """The document has no configuration by that name. Also a ``KeyError``."""

    code = "configuration_not_found"


class NoPreviewError(SolidSeasError, LookupError):
    """The document stores no preview image, and the caller needed one."""

    code = "no_preview"


# --------------------------------------------------------------------------- model files
class FormatNotSupportedError(SolidSeasError):
    """A recognised file format SolidSeas cannot read, or a feature of one document that
    stops it being read (provisional). ``detail["rule"]`` says which (``no_reader``,
    ``required_extension``, ``compression``, ``encrypted``...) and ``detail["value"]``
    names the format id or the feature."""

    code = "format_not_supported"


class UnsupportedOperationError(SolidSeasError, NotImplementedError):
    """An operation that exists for SOLIDWORKS documents but not yet for this kind of
    file (provisional; code ``not_implemented``): ``detail["rule"]`` is ``model_file``
    and ``detail["value"]`` the file's format id."""

    code = "not_implemented"


# --------------------------------------------------------------------------- paths and locations
class NothingToExportError(SolidSeasError, LookupError):
    """The caller asked for an export (STL, 3MF) of a document that holds nothing to
    export: a drawing, a part with neither solid bodies nor a display mesh, an
    assembly none of whose instances could be placed."""

    code = "nothing_to_export"


class NotRepresentableError(SolidSeasError, ValueError):
    """An export (STEP) refused a document holding geometry the format cannot hold
    exactly and SolidSeas cannot approximate within its limits; nothing was written.
    ``bodies`` lists each body refused, with its reason; ``detail["rule"]`` is the
    first reason and ``detail["value"]`` how many bodies were refused."""

    code = "not_representable"

    def __init__(self, *args: Any, detail: dict[str, Any] | None = None, bodies=()) -> None:
        super().__init__(*args, detail=detail)
        self.bodies = tuple(bodies)


class PathRefusedError(SolidSeasError, ValueError):
    """A path was refused by a safety rule. ``detail["rule"]`` names the rule."""

    code = "path_refused"


class LinkRefusedError(PathRefusedError):
    """The path goes through a link, junction or mount point, which SolidSeas never follows."""

    code = "link_refused"


class OutputRefusedError(PathRefusedError):
    """An output location the command line will not write to (the 0.1 ``cli.Refused``)."""

    code = "output_refused"


class PlaceholderFileError(SolidSeasError, OSError):
    """The file is a cloud placeholder whose data is not on this machine; it was not opened."""

    code = "placeholder_file"


# --------------------------------------------------------------------------- worker isolation
class WorkerTimeoutError(SolidSeasError, TimeoutError):
    """An isolated worker did not finish before its deadline and was replaced."""

    code = "timeout"


class WorkerCrashedError(SolidSeasError):
    """An isolated worker process ended without returning a result."""

    code = "worker_crashed"


class WorkerJobError(SolidSeasError):
    """A job failed inside an isolated worker process.

    ``info`` is the error object the worker sent back (``code``, ``exception``,
    ``detail``, ``reader_message``...), so ``code`` and the class name of the
    original exception survive the process boundary. The worker sends JSON,
    never a pickled exception; :func:`solidseas.model.error_info` re-derives the
    message and ``retryable`` from the code, so nothing the worker wrote is
    trusted beyond the code, the class name and the safe ``detail`` keys.
    """

    code = "internal"

    def __init__(self, info: dict[str, Any]) -> None:
        info = dict(info) if isinstance(info, dict) else {}
        text = info.get("reader_message") or info.get("message") or "a job failed in a worker process"
        detail = info.get("detail")
        super().__init__(str(text), detail=detail if isinstance(detail, dict) and detail else None)
        self.info = info
        code = info.get("code")
        if isinstance(code, str):
            self.code = code


# --------------------------------------------------------------------------- the catalog
class NotInCatalogError(SolidSeasError, LookupError):
    """The catalog holds no row for that file: its folder was not indexed, or not yet."""

    code = "not_in_catalog"


class CatalogIncompatibleError(SolidSeasError):
    """The database is not a SolidSeas catalog (``detail["rule"]`` ``not_a_catalog``), a
    newer SolidSeas wrote it (``too_new``), or SQLite finds it damaged (``damaged``: clear
    it and index again; one in the cache folder is made again by the next scan)."""

    code = "catalog_incompatible"


class BusyError(SolidSeasError):
    """Another process holds what this one needs (a catalog's writer lock), or a first
    scan is still running; trying again later can succeed."""

    code = "busy"


# --------------------------------------------------------------------------- the service
class BindRefusedError(SolidSeasError):
    """``solidseas serve`` refused an address: anything but loopback needs ``--allow-remote``
    and at least one ``--allowed-host`` (``detail["rule"]`` says which is missing)."""

    code = "bind_refused"


class AddressUnavailableError(SolidSeasError):
    """``solidseas serve`` could not listen on the address and port it was given: another
    program holds the port, or the address does not belong to this machine."""

    code = "address_unavailable"


class TokenFileError(SolidSeasError):
    """The service's token file is missing, unreadable, empty, malformed or readable by
    other accounts, so the service refuses to start (``detail["rule"]`` says which)."""

    code = "token_file_refused"


# --------------------------------------------------------------------------- drawings (provisional)
# The four codes of docs/DRAWINGS.md 14. Each class derives from the class the drawing code
# raised before the codes existed, so an ``except`` clause written for that class still
# catches it, and ``detail["rule"]`` keeps the rule it carried.
class DrawingInvalidError(InvalidArgumentError):
    """A ``.ssdrw`` refused whole: not a SolidSeas drawing, not strict JSON, written by a
    newer SolidSeas, or outside the bounds of a drawing file (``detail["rule"]`` is
    ``drawing_invalid`` and ``detail["value"]`` names the check).
    ``solidseas.drawing.document.DrawingFileError`` derives from it."""

    code = "drawing_invalid"


class DrawingTooComplexError(SldLimitError):
    """A part or a drawing passed a bound of ``solidseas.drawing.DrawingLimits``
    (``detail["limit"]`` names it): too many faces, edges or bodies before any work
    starts, a stage over its seconds, a file over its size."""

    code = "drawing_too_complex"


class ModelNotFoundError(InvalidArgumentError):
    """A drawing's model was not found where the drawing says it is, or the only files
    found have changed since the drawing was made (``detail["rule"]`` is
    ``model_not_found``); a changed file is offered, never taken."""

    code = "model_not_found"


class DrawingReleasedError(InvalidArgumentError):
    """A RELEASED drawing refused a change: it must start a revision first
    (``detail["rule"]`` is ``drawing_released``)."""

    code = "drawing_released"


# --------------------------------------------------------------------------- versions (provisional)
# A file's history and its versions (solidseas.versions, docs/VERSIONS.md).
class VersionNotFoundError(SolidSeasError, LookupError):
    """The file has no version by that name: a commit id, a snapshot id, ``vN`` or
    ``working`` that names none of the versions its history lists (``detail["parameter"]``
    names the argument)."""

    code = "version_not_found"


class VersionUnavailableError(SolidSeasError, LookupError):
    """A version's content is not on this machine (``detail["rule"]``): an LFS object that
    was not fetched (``lfs_object_missing``), an object a shallow or partial clone left out
    (``object_missing``), a snapshot whose stored copy is gone (``snapshot_missing``), or a
    commit that deleted the file (``deleted``). Nothing is ever fetched to find it."""

    code = "version_unavailable"


# --------------------------------------------------------------------------- warnings
# Every code a reader or builder emits, with what it means. Codes are an open set:
# a consumer treats an unknown code as "other". docs/API.md lists the same codes.
WARNING_CODES: dict[str, str] = {
    "container_name_not_utf8": "a stream name is not UTF-8 and was decoded as IBM437",
    "container_header_mismatch": "a local header disagrees with its directory copy (strict=False only)",
    "container_crc_constant": "every member declares the same CRC-32, so only sizes are checked",
    "ole_parsing_issue": "olefile reported a problem it worked around",
    "zlb_magic_missing": "a __ZLB stream lacks the ZLB magic and is exposed raw (strict=False only)",
    "stream_too_large": "a metadata stream is over its size cap and was skipped",
    "stream_unreadable": "a metadata stream could not be read",
    "xml_doctype_refused": "an XML stream declares a DOCTYPE or ENTITY and was refused",
    "xml_parse_error": "an XML stream could not be parsed",
    "property_set_error": "a legacy property set stream is malformed",
    "property_value_unreadable": "a property value does not parse as its declared type",
    "unknown_document_kind": "the Definition GUID names a document kind other than part, assembly or drawing",
    "materialtree_unknown_configuration": "MATERIALTREE names a configuration no other carrier has",
    "material_mismatch": "KeyWords and MATERIALTREE name different materials",
    "version_prefix_ambiguous": "more than one _MO_VERSION_<n> prefix",
    "version_prefix_missing": "no _MO_VERSION_<n> prefix",
    "version_history_missing": "the _MO_VERSION_<n>/History stream is missing",
    "version_history_unreadable": "the History stream could not be parsed",
    "version_history_mismatch": "the History stream ends with another version than the prefix",
    "preview_undecodable": "preview streams exist but none decodes",
    "value_not_representable": "an integer beyond 2**53 - 1 was sent as null; the text keeps the digits",
    "non_finite_number": "a NaN or infinite number was sent as null",
    "transform_unreadable": "a stored component transform is not 16 finite numbers; it is sent as null",
    "duplicate_instance_name": "two instances under one parent share a name; later ids get a #n suffix",
    "component_model_missing": "a component instance names a model the component tree does not hold",
    "configuration_not_described": "the component tree holds no component list for that configuration",
    "drawing_sheets_unreadable": "the drawing's list of sheet names could not be read",
    # reference resolution (docs/API.md section 5.10)
    "identity_mismatch": "the file chosen has another creation time than the one the document stored",
    "stored_path_also_exists": "another file still exists at the stored path",
    "case_differs": "the file's name differs from the stored name only by case",
    "normalization_differs": "the name matches the stored one only after Unicode normalisation",
    "stored_unc_not_checked": "the stored path is on a network share and was never touched",
    "stored_network_drive_not_checked": "the stored path is on a mapped network drive and was never touched",
    "stored_path_refused": "the stored path is not a usable location (device path, bad component...)",
    "outside_roots": "the file chosen is outside every root",
    "index_partial": "a limit cut a root's folder index short",
    "search_incomplete": "a limit stopped the search before it was complete",
    "placeholder_not_read": "a cloud placeholder was found and deliberately not opened",
    "identity_read_failed": "a candidate file could not be read to check its identity",
    "from_parent_tree": "a sub-assembly's file, resolved from the path the top document stored",
    "context_varies": "the file is used by more than one parent document",
    # bills of materials (docs/API.md section 3.16)
    "bom_properties_unread": "a BOM row's file was not found or not read: its description is unknown",
    "bom_configuration_missing": "a BOM row's file lacks that configuration; its file properties are used",
    "bom_configurations_unknown": "a BOM row's file names no configuration; its file properties are used",
    "bom_children_missing": "a sub-assembly's components are missing from the BOM",
    "bom_children_differ": "the instances of a sub-assembly list different components",
    "bom_part_number_may_differ": "a BOM row's configuration stores an alternate name SOLIDWORKS may show",
    "bom_limit_reached": "a limit of the BOM stopped the reading of some files",
    # exports for 3D printing (docs/API.md section 3.17)
    "display_mesh_fallback": "a part has no solid bodies to export; its saved display mesh is used instead",
    "not_closed": "an exported object is not closed: some edge is not used twice, once each way",
    "bodies_left_out": "bodies an export does not write (surfaces, wires, hidden bodies) are left out of it",
    "faces_left_out": "faces that could not be tessellated leave holes in an exported object",
    "instances_left_out": "instances of the assembly that could not be placed or meshed are left out",
    "shell_reoriented": "a closed shell of an exported object was inside out and was turned round",
    # the tessellator's self-checks (docs/API.md section 3.15)
    "loops_reversed": "faces whose loops all ran against them, drawn as the file faces them, loops reversed",
    "faces_folded": "faces whose triangles fold over one another (their (u, v) areas do not add up)",
    "faces_coarse": "faces that reached max_face_points with triangles still off their surface",
    "solids_not_closed": "solids whose triangles do not use every edge once each way",
    "shells_inside_out": "closed shells facing the wrong way for how they nest, or whose nesting is unknown",
    # the catalog (docs/API.md section 3.18)
    "cycle": "a document is reached again through its own sub-assemblies and is not expanded twice",
    "low_confidence": "the reference was resolved with low confidence; the use may be another file's",
    "quantity_unknown": "the assembly names the file but stores no component tree to count its instances",
    "unread_documents": "assemblies or drawings in the catalog could not be read; they may use the file too",
    # STEP exports (docs/API.md section 3.19)
    "step_approximated": "a STEP export holds B-splines in place of curves or surfaces STEP cannot hold",
    "step_bodies_left_out": "bodies that cannot be written are left out of a STEP export, as asked",
    "step_hidden_bodies_unknown": "several bodies are written; whether SOLIDWORKS hides some is not known",
    "step_differs_from_display": "the bodies a part stores differ from what SOLIDWORKS last displayed",
    "step_tolerant_geometry": "a STEP export holds edges or vertices with gaps larger than its uncertainty",
}


# Model files: the core (docs/API.md 3.20). Each reader branch adds its own codes in its own
# block below, and names them in its own subsection of docs/API.md 3.20.
WARNING_CODES.update(
    {
        "units_assumed": "the file states no unit of length; millimetres were assumed",
        "extension_mismatch": "the content is another format than the extension says; the content wins",
        "non_rigid_transform": "a placement scales, shears or mirrors; it is kept as stored",
        "degenerate_triangles_dropped": "triangles with a repeated or non-finite corner were left out",
        "indices_out_of_range": "triangles naming a vertex the mesh does not have were left out",
        "coordinates_out_of_range": "triangles with a corner more than 1,000 km out were left out",
        "colors_ignored": "colours the file stores were not kept (too many, or a convention not read)",
        "text_truncated": "a name, property or metadata value was longer than its limit and was cut",
        "component_not_found": "a component the document places could not be found or read; it is left out",
    }
)


# Model files: mesh formats, 3MF, OBJ, PLY, OFF, glTF and AMF (docs/API.md 3.20.5)
WARNING_CODES.update(
    {
        "part_reference_refused": "a non-root 3MF part names another part; those components are left out",
        "slicer_data_ignored": "the package carries a slicer's own settings and plates, which are not read",
        "extension_ignored": "the file uses an extension that is not read; the model is read without it",
        "compression_not_supported": "primitives held only in Draco or meshopt compression are left out",
        "primitives_skipped": "points, lines or free-form curves and surfaces are not read",
        "textures_ignored": "texture coordinates and texture maps are not read",
        "curved_triangles_flattened": "AMF curved triangles (normals, edge tangents) are drawn flat",
        "material_library_unread": "an OBJ material library could not be read; its colours are not shown",
    }
)


# Model files: Parasolid files (docs/API.md 3.20.6)
WARNING_CODES.update(
    {
        "header_unreadable": "records of a Parasolid file's common header are not keyword=value; skipped",
        "layout_inferred": "a node type of the transmit has a layout inferred from files, not published",
        "trailing_data": "bytes follow the end of the transmit; they were ignored",
    }
)


# Model files: STEP (docs/API.md 3.20.7)
WARNING_CODES.update(
    {
        "representation_skipped": "a STEP representation holds items that are not drawn (wireframe, points)",
        "placement_unresolved": "a STEP assembly occurrence has no usable placement and is put at the origin",
        "assembly_cycle": "a STEP product or representation leads back to itself and is not followed again",
        "faces_reoriented": "faces of a STEP solid ran against their neighbours and were turned round",
        "void_reoriented": "void shells of a STEP solid faced out of their voids and were turned round",
        "solid_reoriented": "STEP solids whose outer shell faced in were turned round",
    }
)


# Model files: Alibre Design and ACIS (docs/API.md 3.20.8)
WARNING_CODES.update(
    {
        "units_disagree": "the display mesh names another unit of length than the B-rep; the B-rep's is used",
        "placement_unit_assumed": "an assembly's placements are read in centimetres, unconfirmed by the file",
        "constituents_disagree": "the assembly's list of documents differs from the documents it places",
        "component_found_by_name": "a component was found by its stored name; its identity was unreadable",
        "component_ambiguous": "several files hold the same component document; the nearest was used",
        "component_newer": "a component file is a newer version than the assembly references",
        "component_older": "a component file is an older version than the assembly references",
        "acis_version_unverified": "the ACIS data is not of a verified version; the display mesh is used",
        "transform_unverified": "an ACIS body's transform was applied by a convention not yet verified",
        "variant_unverified": "a kind of document is read as a part without verification (sheet metal)",
    }
)


# Versions (docs/VERSIONS.md, docs/API.md 3.26)
WARNING_CODES.update(
    {
        "history_incomplete": "the repository is a shallow or partial clone: its history stops early",
        "lfs_not_fetched": "versions stored with Git LFS whose content is not on this machine",
        "measures_incomplete": "a version's volume, area or box could not be measured whole in time",
    }
)


class SolidSeasDeprecationWarning(DeprecationWarning):
    """Emitted when a deprecated SolidSeas name is used. ``docs/API.md`` section 9 lists
    what is deprecated and what replaces it."""


class ReaderWarning(str):
    """A problem the reader worked around, as text with a machine-readable code.

    ``str(w)`` is the readable text (``"<stream>: <message>"`` when the warning
    belongs to a stream). ``code`` is one of :data:`WARNING_CODES` (an open
    set), ``stream`` the stream it concerns or None, and ``message`` the text
    without the stream. Warning text can quote document content, such as a
    configuration or material name, so it is never logged by the service.
    """

    code: str
    stream: str | None
    message: str

    def __new__(cls, code: str, message: str, stream: str | None = None) -> "ReaderWarning":
        if stream is None:
            text = message
        else:
            where = stream if stream.isprintable() else repr(stream)
            text = f"{where}: {message}"
        self = super().__new__(cls, text)
        self.code = code
        self.stream = stream
        self.message = message
        return self

    def __reduce__(self):
        return (ReaderWarning, (self.code, self.message, self.stream))

    def __repr__(self) -> str:
        return f"ReaderWarning({self.code!r}, {self.message!r}, stream={self.stream!r})"

    def to_dict(self) -> dict[str, Any]:
        """The JSON warning object: ``{"code", "stream", "message"}``."""
        return {"code": self.code, "stream": self.stream, "message": self.message}


__all__ = [
    "WARNING_CODES",
    "AddressUnavailableError",
    "BindRefusedError",
    "BusyError",
    "CatalogIncompatibleError",
    "ConfigurationNotFoundError",
    "DrawingInvalidError",
    "DrawingReleasedError",
    "DrawingTooComplexError",
    "FileTooLargeError",
    "FormatNotSupportedError",
    "InvalidArgumentError",
    "LinkRefusedError",
    "LockedFileError",
    "ModelNotFoundError",
    "NoPreviewError",
    "NotInCatalogError",
    "NotRepresentableError",
    "NothingToExportError",
    "OutputRefusedError",
    "ParasolidError",
    "PathRefusedError",
    "PlaceholderFileError",
    "ReaderWarning",
    "SldError",
    "SldFormatError",
    "SldIntegrityError",
    "SldLimitError",
    "SolidSeasDeprecationWarning",
    "SolidSeasError",
    "StreamNotFoundError",
    "TokenFileError",
    "UnknownFormatError",
    "UnsupportedOperationError",
    "VersionNotFoundError",
    "VersionUnavailableError",
    "WorkerCrashedError",
    "WorkerJobError",
    "WorkerTimeoutError",
]
