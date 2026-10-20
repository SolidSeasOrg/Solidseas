"""IGES files and Open CASCADE's BREP files, read through the ``occt`` conversion backend
(provisional, ``docs/OCCT.md`` tier 1, :mod:`solidseas.convert.occt`).

:func:`open` is the registry's reader for ``iges`` and ``occt_brep``, which the registry
offers only while the backend is available (``FormatSpec.backend``). An
:class:`OcctDocument` reads its head here, in pure Python: an IGES file's global section
(its unit, the program that wrote it, its product id, author, organisation and date), and
nothing for a BREP file, which states no unit (millimetres are assumed, as Open CASCADE
assumes them). Nothing is converted to open a file or to list it.

A full read (``tree``, ``scene``, ``bodies``) has the backend convert the file once to a
STEP model, Open CASCADE sewing an IGES file's loose faces into solids where they close,
and then reads that model with SolidSeas' own STEP reader
(:class:`~solidseas.formats.step.StepDocument`), so an IGES or BREP file draws, prints and
measures as a STEP file does. What the backend reports becomes warnings: surfaces that
stayed open, and a shape Open CASCADE's own check finds faults in.
"""

import dataclasses
import datetime
import re
from typing import Any

from ._source import Clock, Source, clip_text
from .base import ModelDocument, ModelNode, ModelTree, SceneBuilder, _stem, make_property

FORMATS = ("iges", "occt_brep")
GLOBAL_BYTES = 1 << 20  # the start and global sections are read from at most this much
_PRODUCT = "model"  # the product name the STEP model gets; its tree shows the file's name
# IGES unit flags (global parameter 14): the unit and its length in metres.
IGES_UNITS = {
    1: ("in", 0.0254),
    2: ("mm", 0.001),
    4: ("ft", 0.3048),
    5: (None, 1609.344),  # mile
    6: ("m", 1.0),
    7: (None, 1000.0),  # kilometre
    8: (None, 0.0000254),  # mil
    9: ("micron", 1e-6),
    10: ("cm", 0.01),
    11: (None, 0.0000000254),  # microinch
}
_NUMBERED = re.compile(rf"{_PRODUCT} \d+")
_HOLLERITH = re.compile(r"\s*(\d+)H")
_DATE = re.compile(r"\s*(\d{2}|\d{4})(\d{2})(\d{2})\.(\d{2})(\d{2})(\d{2})\s*\Z")


# --------------------------------------------------------------------------- the IGES head
def _records(head: bytes) -> list[bytes]:
    """An IGES file's 80-column records: lines, or fixed records when it has no line ends."""
    first = head.split(b"\n", 1)[0].rstrip(b"\r")
    if len(first) > 82:
        return [head[i : i + 80] for i in range(0, len(head) - 79, 80)]
    return [line.rstrip(b"\r") for line in head.split(b"\n")]


def global_section(head: bytes) -> str:
    """The text of an IGES file's global section (columns 1 to 72 of its ``G`` records)."""
    parts = []
    for rec in _records(head):
        if len(rec) >= 73 and rec[72:73] == b"G":
            parts.append(rec[:72].decode("latin-1"))
        elif parts and len(rec) >= 73 and rec[72:73] in (b"D", b"P", b"T"):
            break
    return "".join(parts)


def global_fields(text: str, count: int = 26) -> list[str | None]:
    """The first ``count`` parameters of a global section: strings as their text (a
    Hollerith ``nH...`` string read by its length, so delimiters inside it are text),
    other values stripped, an empty parameter None. The first two parameters name the
    parameter and record delimiters (``,`` and ``;`` by default)."""
    pd, rd = ",", ";"
    out: list[str | None] = []
    i, n = 0, len(text)
    while i <= n and len(out) < count:
        m = _HOLLERITH.match(text, i)
        if m is not None and int(m.group(1)) > 0:
            start = m.end()
            value: str | None = text[start : start + int(m.group(1))]
            k = start + int(m.group(1))
        else:
            k = i
            while k < n and text[k] not in (pd, rd):
                k += 1
            value = text[i:k].strip() or None
        out.append(value)
        if len(out) == 1 and value is not None and len(value) == 1:
            pd = value
        elif len(out) == 2 and value is not None and len(value) == 1:
            rd = value
        while k < n and text[k] == " ":
            k += 1
        if k >= n or text[k] == rd:
            break
        i = k + 1
    return out + [None] * (count - len(out))


def _date(text: str | None) -> datetime.datetime | None:
    """An IGES date (``YYYYMMDD.HHNNSS``, or ``YYMMDD.HHNNSS`` before 2000), as stored:
    naive, its zone unknown."""
    m = _DATE.match(text or "")
    if m is None:
        return None
    y, mo, d, h, mi, s = (int(g) for g in m.groups())
    if y < 100:
        y += 1900
    try:
        return datetime.datetime(y, mo, d, h, mi, s)
    except ValueError:
        return None


# --------------------------------------------------------------------------- the document
class OcctDocument(ModelDocument):
    """One IGES or BREP file (see the module notes). ``format`` is ``iges`` or
    ``occt_brep``; ``report`` is what the backend said of the file once it was
    converted (None before)."""

    def __init__(self, source, *, format, name, path, file_info, limits, detection=None) -> None:
        self.format = format
        super().__init__(
            source, name=name, path=path, file_info=file_info, limits=limits, detection=detection
        )
        self.doc_type = "part"
        self.report: dict[str, Any] | None = None
        self.step_bytes: bytes | None = None  # the STEP model the backend made, once it has
        self._step = None
        if format == "iges":
            self._iges_head()
        else:
            self.set_units("mm", "assumed")
            self.warn(
                "units_assumed",
                "a BREP file states no unit of length; millimetres were assumed, as Open CASCADE "
                "assumes them",
            )

    def _clip(self, text: str | None) -> str | None:
        if not text or not text.strip():
            return None
        return clip_text(text.strip(), self.limits, self.warnings, "an IGES global parameter")

    def _iges_head(self) -> None:
        g = global_fields(global_section(self.source.read_upto(0, GLOBAL_BYTES)))
        try:
            flag = int(float(g[13])) if g[13] else None
        except ValueError:
            flag = None
        unit = IGES_UNITS.get(flag) if flag is not None else None
        if unit is None:
            self.set_units("mm", "assumed")
            self.warn("units_assumed", "the file names no unit of length it uses; millimetres were assumed")
        elif unit[0] is not None:
            self.set_units(unit[0], "file")
        else:
            self.units = {"length": None, "scale_m": unit[1], "source": "file"}
        system, version = self._clip(g[4]), self._clip(g[5])
        self.application = {"name": system, "version": version}
        self.fields = dataclasses.replace(
            self.fields,
            title=self._clip(g[2]),
            author=self._clip(g[20]),
            last_saved_utc=_date(g[17]),
        )
        for key, value in (
            ("product_id", g[2]),
            ("file_name", g[3]),
            ("originating_system", g[4]),
            ("preprocessor_version", g[5]),
            ("unit_name", g[14]),
            ("organization", g[21]),
        ):
            clipped = self._clip(value)
            if clipped:
                self.properties.append(make_property(key, clipped))

    # -- the conversion ------------------------------------------------------------------
    def step_document(self):
        """The file as the STEP model the backend made of it (converted now, once)."""
        if self._step is not None:
            return self._step
        from ..convert import backend
        from .step import StepDocument

        data = self.source.read_all(self.limits.whole_read_bytes, "whole_read_bytes")
        made = backend("occt").convert_bytes(data, self.format, "step", name=_PRODUCT)
        self.step_bytes = made.data
        self._step = StepDocument(
            Source(made.data), name=self.name, path=None, file_info=None, limits=self.limits
        )
        self._after_conversion(made.report)
        return self._step

    def _after_conversion(self, report: dict[str, Any]) -> None:
        self.report = dict(report)
        left = int(report.get("open_shells") or 0) + int(report.get("free_faces") or 0)
        if left and self.format == "iges":
            self.warn(
                "surfaces_not_closed",
                f"{left} group(s) of surfaces did not close into a solid when sewn at 0.01 mm; "
                "they are shown as surfaces",
            )
        if report.get("valid") is False:
            self.warn(
                "check_failed",
                "Open CASCADE's check found faults in the shape, so parts of it may be missing or "
                "drawn wrong",
            )
        if report.get("solids_sewn"):
            self.properties.append(make_property("solids_sewn", int(report["solids_sewn"])))

    def _settle(self) -> None:
        inner = self._step
        if inner is not None and inner._model is not None:
            self.doc_type, self.kind = inner.doc_type, inner.kind

    # -- hooks ------------------------------------------------------------------------------
    def _counts(self) -> dict[str, int | None]:
        return self._step._counts() if self._step is not None else {}

    def _tree(self, clock: Clock) -> ModelTree | list[ModelNode]:
        got = self.step_document()._tree(clock)
        self._settle()
        # Open CASCADE names the product "model 1", "model 2"... as it counts the files a
        # helper has written; the tree shows the file's own name instead.
        stem = _stem(self.name) or _PRODUCT
        nodes = list(got.nodes if isinstance(got, ModelTree) else got)
        nodes = [dataclasses.replace(n, name=stem) if _NUMBERED.fullmatch(n.name or "") else n for n in nodes]
        return ModelTree(tuple(nodes), got.truncated) if isinstance(got, ModelTree) else nodes

    def _scene(self, sb: SceneBuilder) -> None:
        self.step_document()._scene(sb)
        self._settle()

    def _bodies(self, clock: Clock):
        got = self.step_document()._bodies(clock)
        self._settle()
        return got


def open(source, *, name, path, file_info, limits, hold_open=False, detection=None) -> OcctDocument:
    """Open an IGES or BREP file's :class:`~solidseas.formats._source.Source` (the
    registry's reader for ``iges`` and ``occt_brep``)."""
    fmt = detection.format if detection is not None and detection.format in FORMATS else None
    if fmt is None:
        from . import registry

        fmt = registry.detect_head(source.head(registry.HEAD_BYTES), source.size, name).format
        if fmt not in FORMATS:
            fmt = "iges"
    return OcctDocument(
        source, format=fmt, name=name, path=path, file_info=file_info, limits=limits, detection=detection
    )


__all__ = ["FORMATS", "OcctDocument", "global_fields", "global_section", "open"]
