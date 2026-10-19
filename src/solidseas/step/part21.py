# Part 21 text for the STEP export: numbers, strings, entity numbering and the header.
#
# Derived work. The number formatting (fmt, fmm, fpt, fdir), the entity writer
# (StepWriter) and the header written by write_step come from
#   BlinkingSun/sldprt2step, file sldprt2step_lib/step/mapper.py
#   https://github.com/BlinkingSun/sldprt2step, commit fa954124f4f126e0c465c8f96454978ac80b812e
#   Licensed under the Apache License, Version 2.0. sldprt2step is a port of
#   open-sld-to-step 0.1.0 (Apache-2.0). See NOTICE in the SolidSeas repository.
# Modified for SolidSeas (2026-10-03): numbers are written to 15 significant digits
# rather than the shortest round trip, so that a value read from Parasolid in metres
# and scaled to millimetres carries no binary noise; strings are encoded as ISO
# 10303-21 requires (apostrophes and backslashes doubled, other characters in \X2\
# or \X4\); the writer counts entities against a limit and keeps one id per written
# item; the header carries a time stamp, the originating system and SolidSeas'
# version, and a second description line for an incomplete export.
"""ISO 10303-21 (Part 21) text: numbers, strings, entities and the header section.

Lengths arrive in metres, as Parasolid stores them, and are written in
millimetres. Every real is written to 15 significant digits, as Parasolid's own
text format writes them (``docs/FORMAT.md`` 10.4), and in Part 21's form: always
a decimal point, ``E`` for the exponent, and ``0.`` for zero of either sign.
:func:`rounded` gives the value a reader gets back, so the writer's own checks
evaluate what is written, not what was meant.
"""

import datetime
import math

SCALE = 1000.0  # metres to millimetres
NONE = "'NONE'"  # the label SOLIDWORKS writes on every unnamed entity
MAX_STRING = 256  # FILE_NAME's name, and the longest label written


class EntityLimit(Exception):
    """More entities than the writer was allowed."""


def real(x: float) -> str:
    """``x`` as a Part 21 real to 15 significant digits. Raises ``ValueError`` for a
    value that is not finite."""
    if not math.isfinite(x):
        raise ValueError("a value to write is not finite")
    s = f"{x:.15G}"
    mant, _, exp = s.partition("E")
    if mant in ("0", "-0"):
        return "0."
    if "." not in mant:
        mant += "."
    return f"{mant}E{exp}" if exp else mant


def rounded(x: float) -> float:
    """The value a reader gets back from :func:`real` (``x`` to 15 significant digits)."""
    if not math.isfinite(x):
        raise ValueError("a value to write is not finite")
    v = float(f"{x:.15G}")
    return 0.0 if v == 0.0 else v


def mm(x: float) -> float:
    """A length in metres as written in millimetres."""
    return rounded(x * SCALE)


def triple(v) -> str:
    return f"({real(v[0])},{real(v[1])},{real(v[2])})"


def logical(b: bool) -> str:
    return ".T." if b else ".F."


def text(s: str, limit: int = MAX_STRING) -> str:
    """``s`` as a Part 21 string literal, quotes included, cut to ``limit`` characters:
    printable ASCII as it is (an apostrophe and a backslash doubled), any other
    character as ``\\X2\\`` UTF-16 code units ``\\X0\\`` (``\\X4\\`` for one outside the
    Basic Multilingual Plane), control characters dropped."""
    out: list[str] = []
    wide: list[str] = []  # \X2\ code units waiting to be closed
    wider: list[str] = []  # \X4\ code points waiting to be closed

    def close() -> None:
        if wide:
            out.append("\\X2\\" + "".join(wide) + "\\X0\\")
            wide.clear()
        if wider:
            out.append("\\X4\\" + "".join(wider) + "\\X0\\")
            wider.clear()

    for ch in s[:limit]:
        c = ord(ch)
        if 0x20 <= c <= 0x7E:
            close()
            out.append("''" if ch == "'" else "\\\\" if ch == "\\" else ch)
        elif c < 0x20 or 0x7F <= c <= 0x9F or 0xD800 <= c <= 0xDFFF:
            continue  # control characters and lone surrogates are not text
        elif c <= 0xFFFF:
            if wider:
                close()
            wide.append(f"{c:04X}")
        else:
            if wide:
                close()
            wider.append(f"{c:08X}")
    close()
    return "'" + "".join(out) + "'"


def refs(ids) -> str:
    return "(" + ",".join(f"#{i}" for i in ids) + ")"


class Writer:
    """The DATA section being built: one line of text an entity, numbered from 1 in the
    order added. ``memo`` keeps the id of each item written once (an edge used by two
    faces, a surface by several), keyed by the item itself."""

    def __init__(self, max_entities: int | None = None) -> None:
        self.lines: list[str] = []
        self.memo: dict = {}
        self.max_entities = max_entities

    def add(self, body: str) -> int:
        """Add an entity (``NAME(...)``, or a complex instance in parentheses); its id."""
        self.lines.append(body)
        n = len(self.lines)
        if self.max_entities is not None and n > self.max_entities:
            raise EntityLimit(n)
        return n

    def point(self, p) -> int:
        """A CARTESIAN_POINT of ``p``, already in millimetres and rounded."""
        return self.add(f"CARTESIAN_POINT({NONE},{triple(p)})")

    def direction(self, d) -> int:
        return self.add(f"DIRECTION({NONE},{triple(d)})")

    @property
    def count(self) -> int:
        return len(self.lines)

    def data(self):
        """The DATA section's lines, each ending in a new line."""
        for i, body in enumerate(self.lines, 1):
            yield f"#{i}={body};\n"


def time_stamp(when: datetime.datetime | None = None) -> str:
    """ISO 8601, to the second, in UTC: ``2026-10-03T14:05:09Z``."""
    when = when or datetime.datetime.now(datetime.UTC)
    return when.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


SCHEMA = "AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }"
DESCRIPTION = "STEP AP214"


def header(
    *, file_name: str, stamp: str, system: str, originating: str, incomplete: str | None = None
) -> str:
    """The exchange structure's start and its HEADER section: the description (and a
    second line saying what an incomplete export left out), the file's name, time
    stamp, empty author and organisation, the preprocessor (SolidSeas and its
    version), the originating system and the AP214 schema."""
    desc = [text(DESCRIPTION)] + ([text(incomplete)] if incomplete else [])
    return (
        "ISO-10303-21;\nHEADER;\n"
        f"FILE_DESCRIPTION(({','.join(desc)}),'2;1');\n"
        f"FILE_NAME({text(file_name)},{text(stamp)},(''),(''),{text(system)},{text(originating)},'');\n"
        f"FILE_SCHEMA(({text(SCHEMA)}));\n"
        "ENDSEC;\nDATA;\n"
    )


CLOSING = "ENDSEC;\nEND-ISO-10303-21;\n"
