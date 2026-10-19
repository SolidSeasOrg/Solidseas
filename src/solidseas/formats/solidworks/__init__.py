"""Read SOLIDWORKS parts, assemblies and drawings without SOLIDWORKS.

Pure Python (standard library plus ``olefile``), read-only, cross-platform::

    from solidseas.formats.solidworks import open_document

    with open_document("bracket.sldprt") as doc:
        doc.format, doc.doc_type, doc.saved_version.release
        [c.name for c in doc.configurations]
        {p.name: p.value for p in doc.properties}
        doc.preview()        # Preview(data, mime, width, height, stream) or None
        doc.parasolid()      # ParasolidResult: bodies per configuration, as .x_b / .x_t bytes
        doc.components()     # one assembly configuration's component tree
        doc.references()     # component references in the 0.1 shape
        doc.path_report()    # every path and user name the file would reveal

``docs/FORMAT.md`` is the byte-level specification behind every decoder, with
each claim marked verified, hypothesis or unknown.
"""

from ...errors import ConfigurationNotFoundError
from .components import (
    ComponentFile,
    ComponentNode,
    ComponentTree,
    ConfigurationCounts,
    DrawingSheet,
    DrawingView,
    Placement,
    ReferenceSet,
    Transform,
)
from .container import Container, StreamInfo, detect_format, open_container
from .document import Document, FileInfo, SummaryFields, open_document
from .errors import (
    FileTooLargeError,
    LockedFileError,
    ParasolidError,
    ReaderWarning,
    SldError,
    SldFormatError,
    SldIntegrityError,
    SldLimitError,
    StreamNotFoundError,
    UnknownFormatError,
)
from .mesh import Mesh
from .metadata import Configuration, Metadata, Property
from .parasolid import ParasolidBody, ParasolidResult, RawTransmit
from .pathreport import PathReport
from .paths import EmbeddedPath
from .preview import Preview
from .references import Instance, Reference
from .versions import SavedVersion, release_name

SOLIDWORKS_EXTENSIONS = (".sldprt", ".sldasm", ".slddrw")

__all__ = [
    "ComponentFile",
    "ComponentNode",
    "ComponentTree",
    "Configuration",
    "ConfigurationCounts",
    "ConfigurationNotFoundError",
    "Container",
    "Document",
    "DrawingSheet",
    "DrawingView",
    "EmbeddedPath",
    "FileInfo",
    "FileTooLargeError",
    "Instance",
    "LockedFileError",
    "Mesh",
    "Metadata",
    "ParasolidBody",
    "ParasolidError",
    "ParasolidResult",
    "PathReport",
    "Placement",
    "Preview",
    "Property",
    "RawTransmit",
    "ReaderWarning",
    "Reference",
    "ReferenceSet",
    "SOLIDWORKS_EXTENSIONS",
    "SavedVersion",
    "SldError",
    "SldFormatError",
    "SldIntegrityError",
    "SldLimitError",
    "StreamInfo",
    "StreamNotFoundError",
    "SummaryFields",
    "Transform",
    "UnknownFormatError",
    "detect_format",
    "open_container",
    "open_document",
    "release_name",
]
