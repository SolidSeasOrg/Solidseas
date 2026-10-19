"""File-format readers. Pure Python; nothing here needs SOLIDWORKS or Windows.

``solidseas.formats.solidworks`` reads SOLIDWORKS documents. Every other 3D format
goes through one registry and one document interface (provisional,
``docs/API.md`` section 3.20)::

    from solidseas.formats import open_model, open_any, detect, Limits

    with open_model("bracket.stl") as m:
        m.format, m.variant, m.doc_type, m.kind, m.units
        m.scene()        # meshes in metres and the items that place them
        m.summary()      # the model_summary data the CLI and REST send

:mod:`.registry` lists every format and tells them apart, :mod:`.base` holds
:class:`ModelDocument` and the neutral types, :mod:`.limits` every bound and
:mod:`._source` the bounded building blocks the readers share. A format's
reader lives in its own module (``stl``, ``threemf``, ``step``...), imported
only when a document of that format is opened.
"""

from .base import (
    AnyDocument,
    BodyRef,
    ExternalReference,
    MeshBuilder,
    MeshObject,
    ModelDocument,
    ModelNode,
    ModelTree,
    Scene,
    SceneItem,
    SkippedItem,
    is_model,
    open_any,
    open_model,
)
from .limits import DEFAULT_LIMITS, Limits
from .registry import FORMATS, Detection, FormatSpec, by_extension, detect, extensions, readable

__all__ = [
    "DEFAULT_LIMITS",
    "FORMATS",
    "AnyDocument",
    "BodyRef",
    "Detection",
    "ExternalReference",
    "FormatSpec",
    "Limits",
    "MeshBuilder",
    "MeshObject",
    "ModelDocument",
    "ModelNode",
    "ModelTree",
    "Scene",
    "SceneItem",
    "SkippedItem",
    "by_extension",
    "detect",
    "extensions",
    "is_model",
    "open_any",
    "open_model",
    "readable",
]
