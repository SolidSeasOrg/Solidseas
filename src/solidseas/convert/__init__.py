"""Conversion: one job interface, several backends (``docs/ARCHITECTURE.md`` section 5,
provisional).

A backend declares the formats it reads and the formats it writes, and says whether it
can work here and now (:meth:`Backend.unavailable`). The native backend is the library
itself (:mod:`solidseas.export`, :mod:`solidseas.step`, the ``parasolid`` command) and
needs no entry here. The others work outside this process and are offered only when they
are there; otherwise a format only they read is a capability gap, said in words, as the AI
seam's gaps are:

* ``occt`` (:mod:`.occt`): Open CASCADE, through the helper of the OCCT backend extension
  (``docs/EXTENSIONS.md`` section 9, ``docs/OCCT.md`` tier 1). It reads IGES and OCCT's
  BREP into a STEP model that SolidSeas' own STEP reader then reads, so these files open
  wherever a STEP file opens, and it writes IGES, BREP and STEP.

The registry (:mod:`solidseas.formats.registry`) names, for each format no reader of
SolidSeas' own reads, the backend that does (``FormatSpec.backend``); the format is
readable exactly when that backend is available (:func:`unavailable`).

:func:`convert` writes a file of one format as another through the backend that can:
IGES, BREP and STEP files directly, a SOLIDWORKS part or assembly or a Parasolid file
through the STEP SolidSeas writes of it (:func:`solidseas.step.step_model`). The output is created new,
as every export is (:func:`solidseas.export.write_new`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from ..errors import FormatNotSupportedError, InvalidArgumentError, UnsupportedOperationError

# What ``convert`` writes, by the name a person gives it, and the registry id of each.
TARGETS = {"iges": "iges", "brep": "occt_brep", "step": "step"}
EXTENSIONS = {"iges": (".igs", ".iges"), "occt_brep": (".brep",), "step": (".step", ".stp")}
MIME_TYPES = {"iges": "model/iges", "occt_brep": "application/octet-stream", "step": "model/step"}


class Backend:
    """A conversion backend: its ``name``, the words a message calls it by (``title``), the
    registry ids it ``reads`` and the ones it ``writes``."""

    name: str = ""
    title: str = ""
    reads: frozenset[str] = frozenset()
    writes: frozenset[str] = frozenset()

    def unavailable(self) -> str | None:
        """Why the backend cannot work here now, in words for the person using SolidSeas;
        None when it can."""
        raise NotImplementedError

    def convert_bytes(
        self, data: bytes, format_id: str, target: str, *, name: str | None = None
    ) -> Converted:
        """The file ``data`` of ``format_id`` (one of :attr:`reads`) as a file of ``target``
        (one of :attr:`writes`), in memory; ``name`` is the product name it gets where the
        format has one."""
        raise NotImplementedError


@dataclass(frozen=True)
class Converted:
    """What a backend made: the file's ``data``, its ``format`` and the backend's
    ``report`` of what it read."""

    format: str
    data: bytes
    report: dict[str, Any] = field(default_factory=dict)


def _backends() -> dict[str, Backend]:
    from . import occt

    return {occt.BACKEND.name: occt.BACKEND}


def backend(name: str) -> Backend:
    """The backend called ``name``; ``KeyError`` for none."""
    return _backends()[name]


def backends() -> dict[str, Backend]:
    """Every backend this library has, by name."""
    return dict(_backends())


def unavailable(format_id: str) -> str | None:
    """Why no backend can read ``format_id`` here now (None when one can): the words of the
    backend the registry names for it, or that none reads it."""
    from ..formats import registry

    spec = registry.FORMATS.get(format_id)
    name = spec.backend if spec is not None else None
    if name is None:
        return f"SolidSeas has no backend that reads {spec.name if spec else format_id} files"
    return backend(name).unavailable()


def target_format(name: str) -> str:
    """The registry id ``convert`` writes for ``name`` (``iges``, ``brep`` or ``step``)."""
    fmt = TARGETS.get(str(name).lower()) if isinstance(name, str) else None
    if fmt is None:
        raise InvalidArgumentError(
            f"format is one of {', '.join(TARGETS)}", detail={"parameter": "format", "value": str(name)[:16]}
        )
    return fmt


@dataclass(frozen=True)
class ConvertResult:
    """A file :func:`convert` wrote: its ``path``, ``format`` (a registry id), size in
    ``bytes``, the ``backend`` that made it, the format it came from (``source_format``) and
    the backend's ``report``."""

    path: str
    format: str
    bytes: int
    backend: str
    source_format: str
    report: dict[str, Any]


def _writer(target: str) -> Backend:
    found = [b for b in _backends().values() if target in b.writes]
    if not found:
        raise UnsupportedOperationError(f"SolidSeas has no backend that writes {target} files")
    usable = [b for b in found if b.unavailable() is None]
    if not usable:
        reason = found[0].unavailable() or ""
        raise FormatNotSupportedError(reason, detail={"rule": "needs_extension", "value": target})
    return usable[0]


def _source_step(doc, stem: str) -> bytes:
    """The STEP SolidSeas writes of a SOLIDWORKS document or a Parasolid file ``doc``."""
    from ..step import step_bytes, step_model

    return step_bytes(step_model(doc, name=stem, body_types=("solid", "sheet")))


def convert(
    src: str | os.PathLike,
    out: str | os.PathLike,
    format: str,
    *,
    overwrite: bool = False,
    within: Any = None,
    max_file_bytes: int | None = None,
) -> ConvertResult:
    """Write the file ``src`` as ``format`` (``iges``, ``brep`` or ``step``) to ``out``
    (module notes): :func:`convert_document` of ``src`` opened read-only as
    ``open_any`` opens it, with ``within`` and ``max_file_bytes``."""
    from ..formats import open_any

    target_format(format)
    with open_any(os.fspath(src), within=within, max_file_bytes=max_file_bytes) as doc:
        return convert_document(doc, out, format, overwrite=overwrite)


def convert_document(doc, out: str | os.PathLike, format: str, *, overwrite: bool = False) -> ConvertResult:
    """Write the open document ``doc`` as ``format`` (``iges``, ``brep`` or ``step``) to
    ``out``. Raises ``FormatNotSupportedError`` (rule ``needs_extension``) when the
    backend that writes the format is not available, ``UnsupportedOperationError`` (rule
    ``model_file``) for a document no backend converts (a mesh, say, has no surfaces to
    write), what :func:`solidseas.step.step_model` raises for a part it cannot write, and
    what the export raises for the output (``OutputRefusedError`` for a file that exists,
    unless ``overwrite``)."""
    from ..export import write_new
    from ..formats import registry
    from ..formats._source import Source
    from ..formats.base import ModelDocument

    target = target_format(format)
    writer = _writer(target)
    stem = os.path.splitext(
        os.path.basename(getattr(doc, "name", None) or getattr(doc, "path", None) or "model")
    )[0]
    fmt = doc.format if isinstance(doc, ModelDocument) else registry.SOLIDWORKS
    if fmt in writer.reads:
        source = getattr(doc, "source", None)
        if not isinstance(source, Source):  # pragma: no cover - every model document has one
            raise UnsupportedOperationError("the document's bytes cannot be read")
        data = source.read_all(doc.limits.whole_read_bytes, "whole_read_bytes")
    elif fmt in (registry.SOLIDWORKS, "parasolid"):
        data, fmt = _source_step(doc, stem), "step"
    else:
        spec = registry.FORMATS.get(fmt)
        raise UnsupportedOperationError(
            f"{spec.name if spec else fmt} files cannot be converted to {target_name(target)}: "
            "only IGES, BREP and STEP files, SOLIDWORKS parts and assemblies and Parasolid files can",
            detail={"rule": "model_file", "value": fmt},
        )
    made = writer.convert_bytes(data, fmt, target, name=_product_name(stem))

    def write(fh) -> int:
        fh.write(made.data)
        return len(made.data)

    path, size = write_new(out, write, overwrite=overwrite)
    return ConvertResult(path, target, size, writer.name, fmt, dict(made.report))


def _product_name(stem: str) -> str | None:
    """The product name a file written gets: the source's name when it is plain ASCII
    (Open CASCADE writes it as it is), else the backend's default."""
    clean = stem.strip()
    if clean and len(clean) <= 120 and all(32 <= ord(c) < 127 and c != "'" for c in clean):
        return clean
    return None


def target_name(format_id: str) -> str:
    """The name a person knows ``format_id`` by: IGES, BREP, STEP."""
    return {"iges": "IGES", "occt_brep": "BREP", "step": "STEP"}.get(format_id, format_id)


__all__ = [
    "EXTENSIONS",
    "MIME_TYPES",
    "TARGETS",
    "Backend",
    "ConvertResult",
    "Converted",
    "backend",
    "backends",
    "convert",
    "convert_document",
    "target_format",
    "target_name",
    "unavailable",
]
