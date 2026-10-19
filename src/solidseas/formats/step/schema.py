"""Which STEP a file is, and what a quick look at its data section shows (provisional).

The variant comes from ``FILE_SCHEMA``: ``CONFIG_CONTROL_DESIGN`` and AP203's
second edition (``AP203_CONFIGURATION_CONTROLLED_3D_DESIGN...``) are ``AP203``,
``AUTOMOTIVE_DESIGN`` ``AP214``, ``AP242_MANAGED_MODEL_BASED_3D_ENGINEERING``
``AP242``, whatever the version suffix; anything else is ``other`` and is read by
the same rules. A schema list that names ``ALIBRE_SCHEMA`` is Alibre Design's
design history, not a model (it holds no geometry and would pass as AP203), and
is refused.

:func:`census` is what a listing reads besides the header: one pass of a regular
expression over the data section counting the entity names that say what the
file holds (assembly occurrences, solids, surface models, faces, faceted and
tessellated geometry, products) and picking out the few unit records, without
building the index. Its counts can differ from a full read's where an entity
name appears inside a string; the full read is the reference.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from ...errors import FormatNotSupportedError, SldFormatError
from .._source import Clock
from .part21 import Ref, _Parser
from .units import Units, length_token

PRIVATE_SCHEMAS = ("ALIBRE_SCHEMA",)
CENSUS_NAMES = (
    "NEXT_ASSEMBLY_USAGE_OCCURRENCE",
    "MANIFOLD_SOLID_BREP",
    "BREP_WITH_VOIDS",
    "SHELL_BASED_SURFACE_MODEL",
    "FACETED_BREP",
    "ADVANCED_FACE",
    "FACE_SURFACE",
    "TESSELLATED_SOLID",
    "TESSELLATED_SHELL",
    "TRIANGULATED_FACE",
    "COMPLEX_TRIANGULATED_FACE",
    "TRIANGULATED_SURFACE_SET",
    "COMPLEX_TRIANGULATED_SURFACE_SET",
    "PRODUCT_DEFINITION",
    "MAPPED_ITEM",
    "DOCUMENT_FILE",
    "STYLED_ITEM",
)
_NAMES = re.compile(rb"(?<![A-Z0-9_])(" + b"|".join(n.encode() for n in CENSUS_NAMES) + rb")\s*\(")
_UNIT_WORDS = re.compile(
    rb"LENGTH_UNIT|PLANE_ANGLE_UNIT|MEASURE_WITH_UNIT|GLOBAL_UNIT_ASSIGNED_CONTEXT|SI_UNIT"
)
_RECORD_ID = re.compile(rb"(?:\s|/\*.*?\*/)*#(\d+)\s*=", re.S)
CHUNK = 8 << 20
MAX_UNIT_RECORDS = 1_000


def variant(schemas: tuple[str, ...]) -> str:
    """``AP203``, ``AP214``, ``AP242`` or ``other`` (see the module notes)."""
    for s in schemas:
        word = s.split("{", 1)[0].strip().upper()
        if word.startswith("AP242_MANAGED_MODEL_BASED_3D_ENGINEERING"):
            return "AP242"
        if word.startswith("AUTOMOTIVE_DESIGN"):
            return "AP214"
        if word.startswith("CONFIG_CONTROL_DESIGN") or word.startswith("AP203_CONFIGURATION_CONTROLLED"):
            return "AP203"
    return "other"


def refuse_private(schemas: tuple[str, ...]) -> None:
    """Refuse a schema list that names a private schema (rule ``private_schema``)."""
    for s in schemas:
        word = s.split("{", 1)[0].strip().upper()
        if word in PRIVATE_SCHEMAS:
            raise FormatNotSupportedError(
                "the file is Alibre Design's design history in Part 21, not a STEP model",
                detail={"rule": "private_schema", "value": word},
            )


@dataclass
class Census:
    """What :func:`census` counted, and the length unit it found (metres per unit)."""

    names: Counter = field(default_factory=Counter)
    length_m: float | None = None
    token: str | None = None
    complete: bool = True

    @property
    def assembly(self) -> bool:
        return self.names["NEXT_ASSEMBLY_USAGE_OCCURRENCE"] > 0

    @property
    def brep(self) -> int:
        n = self.names
        return n["MANIFOLD_SOLID_BREP"] + n["BREP_WITH_VOIDS"] + n["SHELL_BASED_SURFACE_MODEL"]

    @property
    def mesh(self) -> int:
        n = self.names
        return n["FACETED_BREP"] + sum(
            n[k]
            for k in (
                "TESSELLATED_SOLID",
                "TESSELLATED_SHELL",
                "TRIANGULATED_FACE",
                "COMPLEX_TRIANGULATED_FACE",
                "TRIANGULATED_SURFACE_SET",
                "COMPLEX_TRIANGULATED_SURFACE_SET",
            )
        )


class _Snippets:
    """A Part21 stand-in over the few unit records the census picked out."""

    def __init__(self, records: dict) -> None:
        self.records = records

    def get(self, ref: Any):
        return self.records.get(int(ref)) if isinstance(ref, Ref) else None


def census(source: Any, start: int, limits: Any, clock: Clock | None = None) -> Census:
    """Count the entity names of the data section (from byte ``start``) and find its
    length unit (see the module notes)."""
    out = Census()
    parser = _Parser(limits)
    unit_texts: dict[int, bytes] = {}
    carry = b""
    pos = start
    size = source.size
    while pos < size or carry:
        chunk = source.read_upto(pos, CHUNK) if pos < size else b""
        pos += len(chunk)
        buf = carry + chunk
        if pos < size:
            cut = buf.rfind(b";") + 1
            if cut == 0:
                if len(buf) > limits.p21_record_bytes:
                    out.complete = False
                    break
                carry = buf
                continue
            body, carry = buf[:cut], buf[cut:]
        else:
            body, carry = buf, b""
        for m in _NAMES.finditer(body):
            out.names[m.group(1).decode("ascii")] += 1
        # Each record is read once: after a unit word, the search goes on past the end of
        # its record, so a record full of unit words costs one pass, not one per word.
        at = 0
        while len(unit_texts) < MAX_UNIT_RECORDS:
            m = _UNIT_WORDS.search(body, at)
            if m is None:
                break
            s = body.rfind(b";", 0, m.start()) + 1
            e = body.find(b";", m.end())
            if e < 0:
                break  # no record ends after this word, so none after it does either
            h = _RECORD_ID.match(body, s, e)
            if h is not None:
                unit_texts.setdefault(int(h.group(1)), body[s:e])
            at = e + 1
            if clock is not None:
                clock.tick()
        if clock is not None:
            clock.tick(Clock.EVERY)
        if not chunk and not carry:
            break
    records = {}
    for rid, text in unit_texts.items():
        try:
            records[rid] = parser.instance(text.strip(), rid)
        except SldFormatError:  # a record the census cannot read: the full read will say why
            continue
    _length(out, records)
    return out


def _length(out: Census, records: dict) -> None:
    units = Units(_Snippets(records))  # type: ignore[arg-type]
    votes: Counter = Counter()
    for rec in records.values():
        assigned = rec.part("GLOBAL_UNIT_ASSIGNED_CONTEXT")
        if assigned and isinstance(assigned[0], list):
            for u in assigned[0]:
                got = units.unit(u)
                if got is not None and got[0] == "length" and got[1] > 0:
                    votes[got[1]] += 1
    if not votes:
        for rec in records.values():
            if rec.has("LENGTH_UNIT"):
                got = units.unit(Ref(rec.id))
                if got is not None and got[0] == "length" and got[1] > 0:
                    votes[got[1]] += 1
    if votes:
        scale = votes.most_common(1)[0][0]
        out.length_m = scale
        out.token = length_token(scale)


__all__ = ["CENSUS_NAMES", "Census", "census", "refuse_private", "variant"]
