"""ACIS SAB (Standard ACIS Binary): the header and a tag tokenizer (provisional,
``docs/formats/alibre.md``).

A SAB stream is ``ACIS BinaryFile`` (or ``ASM BinaryFile4``), four 32-bit
little-endian integers (version, record count, entity count, flags), three
tagged strings (product, ACIS version, date) and three tagged doubles
(millimetres per model unit, ``resabs``, ``resnor``), then records. Every value
in a record carries a one-byte tag, so a record can be read without knowing its
class: :func:`read` turns the stream into :class:`SabRecord` objects (a type
name, the tags and the values) and numbers the subtype definitions for ``ref
n`` (pre-order, from 0, in file order, ``ref`` blocks not counted). The data
ends with the record ``End-of-ACIS-data``; anything after it is damage.

The tags (the published SAT chapter, ezdxf's ACIS notes and every record of the
development samples agree): ``0x04`` int32, ``0x06`` double, ``0x07`` string with
an 8-bit length, ``0x0A`` and ``0x0B`` true and false, ``0x0C`` pointer (int32,
-1 null), ``0x0D`` identifier (the last part of a type name, or a keyword),
``0x0E`` an identifier prefix, ``0x0F`` and ``0x10`` subtype start and end,
``0x11`` record end, ``0x12`` string with a 32-bit length, ``0x13`` position and
``0x14`` vector (three doubles each), ``0x15`` enum (int32), ``0x17`` double. Any
other tag is damage.

Every bound is kept: records (``sab_records``), subtype nesting
(``sab_subtype_depth``), subtype definitions (``sab_subtypes``), string length
(``sab_string_bytes``), values (``sab_values``: each type name, number, pointer,
flag, string or bracket counts one and a position or vector three, so the bound
follows the memory the tokens take, about 40 bytes a value), and every length
against the bytes left. The clock is looked at every 4,096 values, inside a record
as well as between records, so one record of millions of values cannot outrun the
time bound.
"""

import struct
from dataclasses import dataclass

from ...errors import SldFormatError, SldLimitError
from .._source import Clock
from ..limits import Limits

SIGNATURE = b"ACIS BinaryFile"
ASM_SIGNATURE = b"ASM BinaryFile4"
VERIFIED_VERSIONS = frozenset({2100})  # the SAB versions whose record layouts are verified
END_MARKER = "End-of-ACIS-data"
HISTORY_MARKER = "Begin-of-ACIS-History-Data"

T_INT = 0x04
T_DOUBLE = 0x06
T_STR = 0x07
T_TRUE = 0x0A
T_FALSE = 0x0B
T_PTR = 0x0C
T_IDENT = 0x0D
T_IDENT_PREFIX = 0x0E
T_SUB_START = 0x0F
T_SUB_END = 0x10
T_END = 0x11
T_LSTR = 0x12
T_POS = 0x13
T_VEC = 0x14
T_ENUM = 0x15
T_DOUBLE2 = 0x17

_I32 = struct.Struct("<i")
_U32 = struct.Struct("<I")
_F64 = struct.Struct("<d")
_V3 = struct.Struct("<3d")


@dataclass(frozen=True)
class SabHeader:
    """The header of a SAB stream. ``mm_per_unit`` is millimetres per model unit
    (25.4 for inches); ``size`` the header's length in bytes."""

    signature: str
    version: int
    records: int
    entities: int
    flags: int
    product: str
    acis_version: str
    date: str
    mm_per_unit: float
    resabs: float
    resnor: float
    size: int

    @property
    def verified(self) -> bool:
        """Whether this stream's record layouts are the verified ones (SAB, version 2100)."""
        return self.signature == SIGNATURE.decode() and self.version in VERIFIED_VERSIONS


class SabRecord:
    """One record: its type name (``face``, ``cone-surface``, ``PersistentID-Alibre-attrib``),
    ``tags`` (one byte per value) and ``vals`` (the values: ints, floats, strings,
    booleans, position and vector triples, None for a subtype bracket)."""

    __slots__ = ("name", "tags", "vals")

    def __init__(self, name: str, tags: bytes, vals: list) -> None:
        self.name, self.tags, self.vals = name, tags, vals

    def __repr__(self) -> str:
        return f"<SabRecord {self.name} {len(self.vals)} values>"


class SabFile:
    """A tokenized SAB stream: ``header``, ``records`` (pointers are indices into it),
    ``subtypes`` (``(record, value index)`` of each subtype definition, numbered as
    ``ref n`` counts them) and ``history`` (a history section followed the model
    and was not read)."""

    def __init__(self, header: SabHeader, records: list[SabRecord], subtypes: list, history: bool) -> None:
        self.header, self.records, self.subtypes, self.history = header, records, subtypes, history


def _string(data: bytes, i: int, n: int, limit: int) -> tuple[str, int]:
    if n > limit:
        raise SldLimitError(
            f"an ACIS string is {n:,} bytes long, more than the {limit:,} allowed",
            detail={"limit": "sab_string_bytes", "value": n},
        )
    end = i + n
    if end > len(data):
        raise SldFormatError("an ACIS string runs past the end of the data")
    return data[i:end].decode("latin-1"), end


def read_header(data: bytes, limits: Limits) -> SabHeader:
    """The header of a SAB stream; :class:`SldFormatError` when it is not one."""
    if data.startswith(SIGNATURE):
        sig = SIGNATURE
    elif data.startswith(ASM_SIGNATURE):
        sig = ASM_SIGNATURE
    else:
        raise SldFormatError("not an ACIS SAB stream (no ACIS BinaryFile signature)")
    i = len(sig)
    if i + 16 > len(data):
        raise SldFormatError("the ACIS header is cut short")
    version, records, entities, flags = struct.unpack_from("<4i", data, i)
    i += 16
    texts = []
    for _ in range(3):
        if i + 2 > len(data):
            raise SldFormatError("the ACIS header is cut short")
        tag = data[i]
        if tag == T_STR:
            s, i = _string(data, i + 2, data[i + 1], limits.sab_string_bytes)
        elif tag == T_LSTR and i + 5 <= len(data):
            s, i = _string(data, i + 5, _U32.unpack_from(data, i + 1)[0], limits.sab_string_bytes)
        else:
            raise SldFormatError("the ACIS header's strings are not where they belong")
        texts.append(s)
    numbers = []
    for _ in range(3):
        if i + 9 > len(data) or data[i] not in (T_DOUBLE, T_DOUBLE2):
            raise SldFormatError("the ACIS header's numbers are not where they belong")
        numbers.append(_F64.unpack_from(data, i + 1)[0])
        i += 9
    return SabHeader(
        sig.decode(),
        version,
        records,
        entities,
        flags,
        texts[0],
        texts[1],
        texts[2],
        numbers[0],
        numbers[1],
        numbers[2],
        i,
    )


def read(data: bytes, limits: Limits, clock: Clock | None = None) -> SabFile:
    """Tokenize a whole SAB stream (see the module notes). Raises :class:`SldFormatError`
    for anything that is not well-formed and ``SldLimitError`` past a bound."""
    header = read_header(data, limits)
    if header.signature != SIGNATURE.decode():
        raise SldFormatError("an ASM SAB stream is not tokenized: its integer sizes are not verified")
    n = len(data)
    i = header.size
    records: list[SabRecord] = []
    subtypes: list[tuple[int, int]] = []
    max_records, max_depth, max_subtypes = limits.sab_records, limits.sab_subtype_depth, limits.sab_subtypes
    max_str = limits.sab_string_bytes
    max_values = limits.sab_values
    # Values counted so far (a position or vector three), and the count at which the
    # clock and the values bound are next looked at.
    used = 0
    next_check = _CHECK_EVERY
    unpack_i, unpack_u, unpack_f, unpack_v = (
        _I32.unpack_from,
        _U32.unpack_from,
        _F64.unpack_from,
        _V3.unpack_from,
    )
    history = False
    while True:
        used += 1  # the type name
        if used >= next_check:
            next_check = used + _CHECK_EVERY
            _check(used, max_values, limits, clock)
        # the type name: identifier prefixes, then the final identifier
        parts = []
        while True:
            if i + 2 > n:
                raise SldFormatError("the ACIS data ends without its end marker")
            t = data[i]
            if t not in (T_IDENT, T_IDENT_PREFIX):
                raise SldFormatError(f"an ACIS record starts with tag {t:#04x}, not its type name")
            s, i = _string(data, i + 2, data[i + 1], max_str)
            parts.append(s)
            if t == T_IDENT:
                break
            if len(parts) > 64:
                raise SldFormatError("an ACIS type name has too many parts")
        name = "-".join(parts)
        if name == END_MARKER:
            if i != n:
                raise SldFormatError(f"{n - i} bytes follow the ACIS end marker")
            break
        if name == HISTORY_MARKER:
            history = True  # entities of the history follow; the model's records are complete
            break
        if len(records) >= max_records:
            raise limits.exceeded("sab_records", f"the ACIS data has more than {max_records:,} records")
        index = len(records)
        tags = bytearray()
        vals: list = []
        depth = 0
        while True:
            if i >= n:
                raise SldFormatError("an ACIS record runs past the end of the data")
            t = data[i]
            i += 1
            if t == T_END:
                if depth:
                    raise SldFormatError("an ACIS record ends inside a subtype")
                break
            used += 1
            if used >= next_check:
                next_check = used + _CHECK_EVERY
                _check(used, max_values, limits, clock)
            if t in (T_INT, T_PTR, T_ENUM):
                if i + 4 > n:
                    raise SldFormatError("an ACIS record is cut short")
                v = unpack_i(data, i)[0]
                i += 4
            elif t in (T_DOUBLE, T_DOUBLE2):
                if i + 8 > n:
                    raise SldFormatError("an ACIS record is cut short")
                v = unpack_f(data, i)[0]
                i += 8
            elif t in (T_POS, T_VEC):
                if i + 24 > n:
                    raise SldFormatError("an ACIS record is cut short")
                v = unpack_v(data, i)
                i += 24
                used += 2  # three numbers
            elif t in (T_STR, T_IDENT, T_IDENT_PREFIX):
                if i >= n:
                    raise SldFormatError("an ACIS record is cut short")
                v, i = _string(data, i + 1, data[i], max_str)
            elif t == T_LSTR:
                if i + 4 > n:
                    raise SldFormatError("an ACIS record is cut short")
                v, i = _string(data, i + 4, unpack_u(data, i)[0], max_str)
            elif t == T_TRUE:
                v = True
            elif t == T_FALSE:
                v = False
            elif t == T_SUB_START:
                depth += 1
                if depth > max_depth:
                    raise limits.exceeded("sab_subtype_depth", f"ACIS subtypes nest deeper than {max_depth}")
                # A definition is a subtype that does not start with the keyword "ref".
                if not (
                    i + 5 <= n and data[i] == T_IDENT and data[i + 1] == 3 and data[i + 2 : i + 5] == b"ref"
                ):
                    if len(subtypes) >= max_subtypes:
                        raise limits.exceeded(
                            "sab_subtypes", f"the ACIS data has more than {max_subtypes:,} subtypes"
                        )
                    subtypes.append((index, len(vals)))
                v = None
            elif t == T_SUB_END:
                depth -= 1
                if depth < 0:
                    raise SldFormatError("an ACIS subtype ends that never started")
                v = None
            else:
                raise SldFormatError(f"unknown ACIS tag {t:#04x}")
            tags.append(t)
            vals.append(v)
        records.append(SabRecord(name, bytes(tags), vals))
    _check(used, max_values, limits, None)
    return SabFile(header, records, subtypes, history)


_CHECK_EVERY = 4096  # values between looks at the clock and the values bound


def _check(used: int, max_values: int, limits: Limits, clock: Clock | None) -> None:
    if used > max_values:
        raise limits.exceeded("sab_values", f"the ACIS data has more than {max_values:,} values", used)
    if clock is not None:
        clock.check()


__all__ = [
    "ASM_SIGNATURE",
    "END_MARKER",
    "SIGNATURE",
    "VERIFIED_VERSIONS",
    "SabFile",
    "SabHeader",
    "SabRecord",
    "read",
    "read_header",
]
