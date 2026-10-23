"""SolidSeas: read, preview and manage SOLIDWORKS files, with or without SOLIDWORKS.

``import solidseas`` gives the library entry points: :func:`open_document`,
:class:`Document`, :class:`FileInfo`, :func:`scan` (folder listings),
:class:`Roots` (the folders SolidSeas may search), :class:`ReaderWarning` and
the exceptions, all deriving from :class:`SolidSeasError`. ``solidseas.model``
holds the JSON shapes every surface emits, ``solidseas.walk`` the one folder
walker, ``solidseas.resolve`` reference resolution, ``solidseas.workers`` the
worker processes that read untrusted documents and ``solidseas.serve`` the
REST service. ``solidseas.formats`` reads 3D files of other formats than
SOLIDWORKS (``open_model``, ``open_any``; provisional). ``docs/API.md``
documents them.
"""

__version__ = "0.2.442"

from .errors import (  # noqa: E402  (__version__ comes first: submodules may import it)
    AddressUnavailableError,
    BindRefusedError,
    BusyError,
    CatalogIncompatibleError,
    ConfigurationNotFoundError,
    DrawingInvalidError,
    DrawingReleasedError,
    DrawingTooComplexError,
    FileTooLargeError,
    FormatNotSupportedError,
    InvalidArgumentError,
    LinkRefusedError,
    LockedFileError,
    ModelNotFoundError,
    NoPreviewError,
    NothingToExportError,
    NotInCatalogError,
    NotRepresentableError,
    OutputRefusedError,
    ParasolidError,
    PathRefusedError,
    PlaceholderFileError,
    ReaderWarning,
    SldError,
    SldFormatError,
    SldIntegrityError,
    SldLimitError,
    SolidSeasDeprecationWarning,
    SolidSeasError,
    StreamNotFoundError,
    TokenFileError,
    UnknownFormatError,
    UnsupportedOperationError,
    VersionNotFoundError,
    VersionUnavailableError,
    WorkerCrashedError,
    WorkerJobError,
    WorkerTimeoutError,
)
from .formats.solidworks import Document, FileInfo, SummaryFields, open_document  # noqa: E402
from .listing import Scan, scan  # noqa: E402
from .roots import Root, Roots  # noqa: E402

__all__ = [
    "AddressUnavailableError",
    "BindRefusedError",
    "BusyError",
    "CatalogIncompatibleError",
    "ConfigurationNotFoundError",
    "Document",
    "DrawingInvalidError",
    "DrawingReleasedError",
    "DrawingTooComplexError",
    "FileInfo",
    "FileTooLargeError",
    "FormatNotSupportedError",
    "InvalidArgumentError",
    "LinkRefusedError",
    "LockedFileError",
    "ModelNotFoundError",
    "NoPreviewError",
    "NothingToExportError",
    "NotInCatalogError",
    "NotRepresentableError",
    "OutputRefusedError",
    "ParasolidError",
    "PathRefusedError",
    "PlaceholderFileError",
    "ReaderWarning",
    "Root",
    "Roots",
    "Scan",
    "SldError",
    "SldFormatError",
    "SldIntegrityError",
    "SldLimitError",
    "SolidSeasDeprecationWarning",
    "SolidSeasError",
    "StreamNotFoundError",
    "SummaryFields",
    "TokenFileError",
    "UnknownFormatError",
    "UnsupportedOperationError",
    "VersionNotFoundError",
    "VersionUnavailableError",
    "WorkerCrashedError",
    "WorkerJobError",
    "WorkerTimeoutError",
    "__version__",
    "open_document",
    "scan",
]
