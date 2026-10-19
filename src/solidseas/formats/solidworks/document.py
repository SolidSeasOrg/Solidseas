"""The public, read-only view of one SOLIDWORKS document."""

import datetime
import os
import re
import warnings
from collections.abc import Collection
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from ...errors import (
    ConfigurationNotFoundError,
    InvalidArgumentError,
    ReaderWarning,
    SolidSeasDeprecationWarning,
    StreamNotFoundError,
)
from .components import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_NODES,
    ComponentTree,
    DrawingSheet,
    ReferenceSet,
    component_tree,
    reference_set,
)
from .container import Container, PathOrBytes, StreamInfo, open_container
from .mesh import Mesh, read_display_mesh
from .metadata import Configuration, Metadata, Property, _parse_iso, read_metadata
from .parasolid import DEFAULT_MAX_TRANSMIT_BYTES, ParasolidResult, extract_parasolid, partition_streams
from .pathreport import (
    DEFAULT_MAX_DOCUMENTS,
    DEFAULT_MAX_PATHS,
    DEFAULT_MAX_TOTAL_BYTES,
    PathReport,
    path_report,
)
from .paths import DEFAULT_MAX_SCAN_BYTES, EmbeddedPath, find_embedded_paths
from .preview import Preview, preview_streams, read_preview
from .references import Reference, references_from_metadata
from .versions import SavedVersion, read_saved_version

_NESTED = re.compile(r"(VirtualComp|ImportedComp)/")
_EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.UTC)
_DOC_TYPE_SOURCE = {"Contents/Definition": "definition", "extension": "extension"}


@dataclass(frozen=True)
class FileInfo:
    """Size and modification time of the source file, from ``fstat`` on the open handle.

    ``mtime_ns`` is exact. ``modified_utc`` is the same instant as an aware UTC
    datetime (microsecond precision), or None when the file system reports a
    time outside the range Python can represent.
    """

    size: int
    mtime_ns: int
    modified_utc: datetime.datetime | None

    @classmethod
    def from_stat(cls, size: int, mtime_ns: int) -> "FileInfo":
        try:
            modified = _EPOCH + datetime.timedelta(microseconds=mtime_ns // 1000)
        except OverflowError:
            modified = None
        return cls(size=size, mtime_ns=mtime_ns, modified_utc=modified)


@dataclass(frozen=True)
class SummaryFields:
    """Title, author and save information, merged from every carrier that holds them.

    Each field is None when no carrier holds it. The two dates are aware UTC
    datetimes.
    """

    title: str | None = None
    subject: str | None = None
    author: str | None = None
    keywords: str | None = None
    comments: str | None = None
    last_saved_by: str | None = None
    created_utc: datetime.datetime | None = None
    last_saved_utc: datetime.datetime | None = None


def _text_or_none(v: Any) -> str | None:
    if v is None or isinstance(v, (bytes, bytearray)):
        return None
    s = v if isinstance(v, str) else str(v)
    return s or None


class Document:
    """A SOLIDWORKS part, assembly or drawing opened read-only.

    Create one with :func:`open_document`. Values are decoded lazily and cached.
    By default the file is read into memory and its handle closed when the
    document opens; see :func:`open_document`. A ``Document`` is not
    thread-safe: use one per thread, and close it or use ``with``.
    """

    def __init__(self, container: Container, path: str | None = None, *, name: str | None = None):
        self._c = container
        self.path = path
        #: Display name: ``name=`` when given, else the file name of ``path``; None for
        #: bytes opened without a name. Its extension is the type hint when the file
        #: stores no document-type GUID.
        self.name: str | None = name if name is not None else (os.path.basename(path) if path else None)
        self._nested: dict[str, Document] = {}

    # lifecycle ----------------------------------------------------------------
    def close(self) -> None:
        for nd in self._nested.values():
            nd.close()
        self._nested.clear()
        self._c.close()

    def __enter__(self) -> "Document":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<Document {self.doc_type} {self.format} {self.name or '<memory>'!r}>"

    # container -----------------------------------------------------------------
    @property
    def container(self) -> Container:
        return self._c

    @property
    def format(self) -> str:
        """``"modern"`` (SOLIDWORKS 2015 and later) or ``"ole"`` (legacy compound file)."""
        return self._c.format

    @property
    def file_size(self) -> int:
        return self._c.file_size

    @cached_property
    def file_info(self) -> FileInfo | None:
        """Size and modification time of the source file, taken from the open handle.
        None for a document opened from bytes or nested in another document."""
        if self._c.file_stat is None:
            return None
        return FileInfo.from_stat(*self._c.file_stat)

    def streams(self) -> list[StreamInfo]:
        return self._c.streams()

    @property
    def stream_count(self) -> int:
        return len(self._c.streams())

    def read_stream(self, name: str, *, raw: bool = False) -> bytes:
        """A stream with the container compression removed, or as stored with ``raw=True``.
        An unknown name raises :class:`~solidseas.errors.StreamNotFoundError` (a ``KeyError``)."""
        return self._c.read_raw(name) if raw else self._c.read(name)

    @property
    def warnings(self) -> list[ReaderWarning]:
        """Problems the readers worked around. Each is a ``str`` with ``code``, ``stream`` and
        ``message`` attributes; the text can quote document content."""
        return list(self._c.warnings) + self.metadata.warnings + self.saved_version.warnings

    # decoded values ----------------------------------------------------------------
    @cached_property
    def metadata(self) -> Metadata:
        return read_metadata(self._c, self.name)

    @property
    def doc_type(self) -> str | None:
        """``"part"``, ``"assembly"``, ``"drawing"``, or None when neither the document-type
        GUID nor the file name says. Never any other string."""
        return self.metadata.doc_type

    @property
    def doc_type_source(self) -> str:
        """Where :attr:`doc_type` came from: ``"definition"`` (the GUID in
        ``Contents/Definition``), ``"extension"`` or ``"none"``."""
        return _DOC_TYPE_SOURCE.get(self.metadata.doc_type_source, "none")

    @cached_property
    def saved_version(self) -> SavedVersion:
        return read_saved_version(self._c)

    @property
    def configurations(self) -> list[Configuration]:
        return self.metadata.configurations

    @property
    def active_configuration(self) -> str | None:
        return self.metadata.active_configuration

    def configuration(self, name: str | None = None) -> Configuration | None:
        """The configuration called ``name`` (exact match first, then a unique
        case-insensitive one), or with None the active configuration, which is None
        when the file names none. An unknown name raises
        :class:`~solidseas.errors.ConfigurationNotFoundError` (a ``KeyError``)."""
        if name is None:
            active = self.active_configuration
            return next((c for c in self.configurations if c.name == active), None) if active else None
        if not isinstance(name, str):
            raise InvalidArgumentError(
                "a configuration name is a string", detail={"parameter": "configuration"}
            )
        for c in self.configurations:
            if c.name == name:
                return c
        folded = [c for c in self.configurations if c.name.casefold() == name.casefold()]
        if len(folded) == 1:
            return folded[0]
        raise ConfigurationNotFoundError(f"no configuration named {name!r}")

    @property
    def properties(self) -> list[Property]:
        """File-level custom properties. Configuration-specific ones are on each configuration."""
        return self.metadata.properties

    def effective_properties(
        self, configuration: str | None = None, *, nested: str | None = None
    ) -> list[Property]:
        """File-level properties overridden by a configuration's own, as a bill of
        materials sees them.

        ``configuration=None`` means the active configuration; when the file names
        none, the result is the file-level properties. A configuration property
        replaces the file-level property of the same name (compared
        case-insensitively, as SOLIDWORKS does) in place; the others follow in
        stored order. Each property's ``scope`` says where it came from.

        ``nested`` names a nested document (:meth:`nested`) whose properties to
        return instead; ``configuration`` is then one of its configurations.
        """
        if nested is not None:
            return self.nested(nested).effective_properties(configuration)
        cfg = self.configuration(configuration)
        props = list(self.properties)
        if cfg is None:
            return props
        index = {p.name.casefold(): i for i, p in enumerate(props)}
        for cp in cfg.properties:
            i = index.get(cp.name.casefold())
            if i is None:
                index[cp.name.casefold()] = len(props)
                props.append(cp)
            else:
                props[i] = cp
        return props

    def property_values(
        self, configuration: str | None = None, *, nested: str | None = None
    ) -> dict[str, Any]:
        """``{name: value}`` of :meth:`effective_properties`: ``None`` means the active
        configuration, a name means that configuration."""
        return {p.name: p.value for p in self.effective_properties(configuration, nested=nested)}

    @property
    def material(self) -> str | None:
        return self.metadata.material

    @property
    def units(self) -> dict[str, Any] | None:
        return self.metadata.units

    @cached_property
    def fields(self) -> SummaryFields:
        """Title, subject, author, keywords, comments, last saver and the two dates."""
        s = self.metadata.summary
        return SummaryFields(
            title=_text_or_none(s.get("title")),
            subject=_text_or_none(s.get("subject")),
            author=_text_or_none(s.get("author")),
            keywords=_text_or_none(s.get("keywords")),
            comments=_text_or_none(s.get("comments")),
            last_saved_by=_text_or_none(s.get("last_saved_by")),
            created_utc=_parse_iso(_text_or_none(s.get("created_utc"))),
            last_saved_utc=_parse_iso(_text_or_none(s.get("last_saved_utc"))),
        )

    def preview(self, *, prefer: str = "png", nested: str | None = None) -> Preview | None:
        """The saved preview image (PNG, or BMP for the DIB), or None when the file stores none.
        ``nested`` names a nested document (:meth:`nested`) whose preview to return instead."""
        if nested is not None:
            return self.nested(nested).preview(prefer=prefer)
        return read_preview(self._c, prefer=prefer)

    def parasolid(
        self,
        *,
        local_bodies: str = "fallback",
        include_raw: bool = False,
        max_bytes: int = DEFAULT_MAX_TRANSMIT_BYTES,
        max_total_bytes: int | None = None,
        configurations=None,
    ) -> ParasolidResult:
        """The embedded Parasolid bodies, per configuration, as standalone part transmits.
        ``configurations`` (configuration ids) limits the reading to those."""
        names = {c.id: c.name for c in self.configurations if c.id is not None}
        return extract_parasolid(
            self._c,
            local_bodies=local_bodies,
            include_raw=include_raw,
            max_bytes=max_bytes,
            max_total_bytes=max_total_bytes,
            config_names=names,
            configurations=configurations,
        )

    def tessellate(self, configuration: str | None = None, **options: Any):
        """Triangles of the part's Parasolid bodies in ``configuration`` (None: the active
        one), or None for an assembly or a drawing. Provisional: the same as
        :func:`solidseas.tessellate.tessellate_document` (``docs/API.md`` section 3.15)."""
        from ...tessellate import tessellate_document

        return tessellate_document(self, configuration, **options)

    def references(self) -> list[Reference]:
        """Component references of an assembly (models of a drawing, as a hypothesis), in
        the 0.1 shape: one per referenced file with the instances of every configuration
        together. :meth:`components` gives one configuration's tree and counts."""
        return references_from_metadata(self.metadata, self.name)

    def components(
        self,
        configuration: str | None = None,
        *,
        max_nodes: int = DEFAULT_MAX_NODES,
        max_depth: int = DEFAULT_MAX_DEPTH,
    ) -> ComponentTree | None:
        """The component tree of one assembly configuration, or None for a part or a drawing.

        ``configuration=None`` means the active configuration (else the most recently
        used one the tree describes, else the first). An unknown name raises
        :class:`~solidseas.errors.ConfigurationNotFoundError`. The expansion stops at
        ``max_nodes`` instances (1 to 1,000,000) or ``max_depth`` levels (1 to 64) and
        then says ``truncated``; it never raises for size. An assembly without a
        component tree gives ``children_state == "unknown"`` and its ``Header2`` files.
        ``docs/API.md`` sections 3.8, 3.9 and 5.9 describe every field.
        """
        if self.doc_type != "assembly":
            return None
        return component_tree(self, configuration, max_nodes=max_nodes, max_depth=max_depth)

    def reference_set(self, configuration: str | None = None) -> ReferenceSet:
        """Every file the document references, across all its configurations, with the
        counts of ``configuration`` (None: the active one): the ``references`` JSON kind.
        Provisional."""
        return reference_set(self, configuration)

    def resolve_references(self, roots=None, **options: Any):
        """Find each referenced file on this machine: a
        :class:`solidseas.resolve.Resolution` with one result per file key. ``roots``
        defaults to this document's folder; ``options`` are those of
        :func:`solidseas.resolve.resolve_references`. Provisional."""
        from ...resolve import resolve_references

        return resolve_references(self, roots, **options)

    def display_geometry(self, configuration: str | None = None, **options: Any):
        """One assembly configuration ready to draw: every unsuppressed, visible part
        instance placed in the top assembly's frame, with the meshes they share, and
        each instance that could not be placed or meshed with the reason; None for a
        part or a drawing. ``options`` are those of
        :func:`solidseas.geometry.display_geometry`. Provisional."""
        from ...geometry import display_geometry

        return display_geometry(self, configuration, **options)

    def bom(self, configuration: str | None = None, **options: Any):
        """The bill of materials of one assembly configuration: a
        :class:`solidseas.bom.Bom` whose rows are grouped, counted and numbered as
        SOLIDWORKS' BOM tables, with PART NUMBER and DESCRIPTION read as its default
        template reads them; None for a part or a drawing. ``options`` are those of
        :func:`solidseas.bom.build_bom` (``bom_type`` ``top``, ``parts`` or
        ``indented``; ``roots`` to find the component files...). Provisional."""
        from ...bom import build_bom

        return build_bom(self, configuration, **options)

    def sheets(self) -> list[DrawingSheet] | None:
        """A drawing's sheets with their views (name, the model's configuration and file
        name), or None for a part or an assembly. Provisional: verified against
        SOLIDWORKS on two single-sheet drawings only."""
        if self.doc_type != "drawing":
            return None
        sheets = reference_set(self).sheets
        return list(sheets) if sheets is not None else []

    def mesh(self) -> Mesh | None:
        """The cached display tessellation (not an exact B-rep), or None when absent."""
        return read_display_mesh(self._c)

    def embedded_paths(self) -> tuple[list[EmbeddedPath], list[str]]:
        """Absolute paths the byte scan finds in this document's own streams, and the
        streams too large to scan. Provisional: :meth:`path_report` is the full report."""
        return find_embedded_paths(self._c)

    def path_report(
        self,
        *,
        max_stream_bytes: int = DEFAULT_MAX_SCAN_BYTES,
        max_paths: int = DEFAULT_MAX_PATHS,
        max_documents: int = DEFAULT_MAX_DOCUMENTS,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    ) -> PathReport:
        """Every path and name this document, and every nested document in it, reveals to
        whoever receives it: the structured carriers first, then a byte scan of every
        stream. ``complete`` is false when a stream was larger than ``max_stream_bytes``
        (16 MiB), a part could not be read or a limit stopped the report: at most
        ``max_paths`` distinct paths, ``max_documents`` documents (this one included) and
        ``max_total_bytes`` decoded bytes read. Never raises for what the file holds.
        SolidSeas never rewrites a file to remove them. ``docs/API.md`` section 5.11
        describes every field."""
        for value, what in (
            (max_stream_bytes, "max_stream_bytes"),
            (max_paths, "max_paths"),
            (max_documents, "max_documents"),
            (max_total_bytes, "max_total_bytes"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise InvalidArgumentError(f"{what} must be a positive integer", detail={"parameter": what})
        return path_report(
            self,
            max_stream_bytes=max_stream_bytes,
            max_paths=max_paths,
            max_documents=max_documents,
            max_total_bytes=max_total_bytes,
        )

    def nested_documents(self) -> list[str]:
        """Streams that hold complete embedded documents (virtual and imported components)."""
        return [n for n in self._c.names() if _NESTED.match(n)]

    def open_nested(self, name: str) -> "Document":
        return Document(self._c.open_nested(name), None, name=name.rsplit("/", 1)[-1])

    def nested(self, name: str) -> "Document":
        """The nested document in stream ``name`` (one of :meth:`nested_documents`, such as
        a component file's ``nested``), opened once and closed with this document. An
        unknown name raises :class:`~solidseas.errors.StreamNotFoundError`."""
        if not isinstance(name, str):
            raise InvalidArgumentError("a nested document name is a string", detail={"parameter": "nested"})
        doc = self._nested.get(name)
        if doc is None:
            if name not in self.nested_documents():
                raise StreamNotFoundError(
                    f"no nested document named {name!r}", detail={"parameter": "nested"}
                )
            doc = self._nested[name] = self.open_nested(name)
        return doc

    # summaries ------------------------------------------------------------------------
    def summary(
        self, *, include: Collection[str] = ("properties", "configurations"), nested: str | None = None
    ) -> dict[str, Any]:
        """The ``data`` of the ``document_summary`` JSON kind: exactly what the CLI and
        the REST service return for this document. ``include`` picks the optional
        parts, ``"properties"`` and ``"configurations"``; a left-out part is None.
        ``nested`` names a nested document (:meth:`nested`) to summarise instead."""
        from ...model import build_document_summary

        return build_document_summary(self, include=include, nested=nested)

    def info(self) -> dict[str, Any]:
        """A JSON-ready summary in the 0.1 shape. Deprecated since 0.2.0, and warns: use
        :meth:`summary`, whose shape is documented in ``docs/API.md``. Kept until the
        0.3 minor release at the earliest."""
        warnings.warn(
            "Document.info() is deprecated; use Document.summary(), the document_summary "
            "data every surface returns",
            SolidSeasDeprecationWarning,
            stacklevel=2,
        )
        sv = self.saved_version
        units = {k: v for k, v in (self.units or {}).items() if k in ("system", "length", "mass", "angle")}
        return {
            "file": os.path.basename(self.path) if self.path else None,
            "format": self.format,
            "doc_type": self.doc_type,
            "saved_version": {
                "format_version": sv.format_version,
                "release": sv.release,
                "release_verified": sv.release_verified,
                "last_build": sv.last_build,
                "last_build_date": sv.last_build_date,
                "save_as_previous": sv.save_as_previous,
            },
            "configurations": [
                {"id": c.id, "name": c.name, "active": c.active, "material": c.material}
                for c in self.configurations
            ],
            "active_configuration": self.active_configuration,
            "material": self.material,
            "units": units or None,
            "custom_property_count": len(self.properties),
            "stream_count": self.stream_count,
            "file_size": self.file_size,
            "preview_streams": preview_streams(self._c),
            "partition_streams": [name for _, name in partition_streams(self._c)],
            "nested_documents": len(self.nested_documents()),
            "warnings": [str(w) for w in self.warnings],
        }


def open_document(
    src: PathOrBytes,
    *,
    name: str | None = None,
    strict: bool = True,
    hold_open: bool = False,
    max_file_bytes: int | None = None,
    within: str | os.PathLike | None = None,
    refuse_hard_links: bool = False,
) -> Document:
    """Open a SOLIDWORKS document (``.sldprt``, ``.sldasm`` or ``.slddrw``) read-only.

    ``src`` is a path or the bytes of a whole document. ``name`` is the display
    name, and for bytes input also the extension hint used when the file stores
    no document-type GUID; it defaults to the file name of a path.

    Raises only ``FileNotFoundError``, ``IsADirectoryError``, ``PermissionError``
    (access denied, on every operating system),
    :class:`~solidseas.errors.LockedFileError` (another process holds the file
    exclusively, Windows) and the other :class:`~solidseas.errors.SolidSeasError`
    subclasses, such as :class:`~solidseas.errors.UnknownFormatError` and
    :class:`~solidseas.errors.SldFormatError`. Any other exception from a crafted
    file is a bug. Only a regular file is read: a pipe, socket or device raises
    :class:`~solidseas.errors.PathRefusedError` (rule ``not_regular_file``)
    without blocking.

    Files up to 512 MiB are read whole and the file handle is closed before this
    returns, so holding a ``Document`` never stops SOLIDWORKS from saving over
    the file. Pass ``hold_open=True`` to read lazily from a shared read-only
    handle instead; larger files always do. ``max_file_bytes`` refuses a larger
    file with :class:`~solidseas.errors.FileTooLargeError` before reading any of it.

    ``within`` (provisional) names a folder ``src`` must lie below. Nothing below
    that folder is followed: a link, junction or symbolic link on the way raises
    :class:`~solidseas.errors.LinkRefusedError`, a cloud placeholder raises
    :class:`~solidseas.errors.PlaceholderFileError` before any byte is read, and a
    path outside the folder raises :class:`~solidseas.errors.PathRefusedError`.
    The folder listing opens every document it lists this way.

    ``refuse_hard_links`` (provisional) refuses a file with more than one name
    with :class:`~solidseas.errors.LinkRefusedError` (rule ``hard_link``), checked
    on the open handle before any byte is read. The REST service sets it.
    """
    if name is not None and not isinstance(name, str):
        raise InvalidArgumentError("name must be a string", detail={"parameter": "name"})
    if max_file_bytes is not None and (
        isinstance(max_file_bytes, bool) or not isinstance(max_file_bytes, int) or max_file_bytes < 0
    ):
        raise InvalidArgumentError(
            "max_file_bytes must be a non-negative integer", detail={"parameter": "max_file_bytes"}
        )
    path = None if isinstance(src, (bytes, bytearray, memoryview)) else os.fspath(src)
    container = open_container(
        src,
        strict=strict,
        hold_open=hold_open,
        max_file_bytes=max_file_bytes,
        within=within,
        refuse_hard_links=bool(refuse_hard_links),
    )
    return Document(container, path, name=name)
