"""``PROP_DATA``: an Alibre Design document's property bag and its thumbnail (provisional,
``docs/formats/alibre.md``).

The stream is a run of entries to its last byte. An entry is a key (a big-endian
16-bit length and its bytes), three little-endian 32-bit integers (flags, type,
count) and ``count`` values of the type: ``0x14`` a string (a big-endian 16-bit
length and its bytes), ``0x0A`` a 32-bit integer, ``0x1E`` a double, ``0x28`` a
blob (a little-endian 32-bit length and its bytes); type -1 with count 0 is an
empty entry. Lengths are big-endian and numbers little-endian, as the samples
show. The key ``snapshot`` holds the thumbnail, a whole Windows bitmap file.

:func:`read` keeps every bound (``prop_entries``, ``prop_values``, each length
against the bytes left) and returns the entries read before any damage with the
error, so a damaged bag still gives what it holds.
"""

import datetime
import re
import struct
from dataclasses import dataclass
from typing import Any

from ...errors import SldFormatError, SolidSeasError
from ..limits import Limits

T_STRING, T_INT, T_DOUBLE, T_BLOB, T_EMPTY = 0x14, 0x0A, 0x1E, 0x28, -1
SNAPSHOT = "snapshot"
# Keys that describe the file's own bookkeeping, not the document: not shown as properties.
INTERNAL = frozenset({"TotalSize", "TransferSize", "secureObjectType", "subType", SNAPSHOT})


@dataclass(frozen=True)
class PropEntry:
    key: str
    flags: int
    type: int
    values: tuple[Any, ...]


def read(data: bytes, limits: Limits) -> tuple[list[PropEntry], SolidSeasError | None]:
    """The entries of a ``PROP_DATA`` stream, and the error that stopped the read (None
    when it ended exactly at the end of the stream)."""
    out: list[PropEntry] = []
    i, n = 0, len(data)
    try:
        while i < n:
            if len(out) >= limits.prop_entries:
                raise limits.exceeded(
                    "prop_entries", f"PROP_DATA holds more than {limits.prop_entries:,} entries"
                )
            if i + 2 > n:
                raise SldFormatError("a PROP_DATA key is cut short", detail={"stream": "PROP_DATA"})
            (kl,) = struct.unpack_from(">H", data, i)
            if i + 2 + kl + 12 > n:
                raise SldFormatError("a PROP_DATA entry runs past the stream", detail={"stream": "PROP_DATA"})
            key = data[i + 2 : i + 2 + kl].decode("utf-8", "replace")
            i += 2 + kl
            flags, typ, count = struct.unpack_from("<iii", data, i)
            i += 12
            if typ == T_EMPTY:
                if count != 0:
                    raise SldFormatError(
                        "an empty PROP_DATA entry holds values", detail={"stream": "PROP_DATA"}
                    )
                out.append(PropEntry(key, flags, typ, ()))
                continue
            if count < 0 or count > limits.prop_values:
                raise limits.exceeded("prop_values", f"a PROP_DATA entry holds {count:,} values", count)
            values: list[Any] = []
            for _ in range(count):
                if typ == T_STRING:
                    if i + 2 > n:
                        raise SldFormatError(
                            "a PROP_DATA string is cut short", detail={"stream": "PROP_DATA"}
                        )
                    (sl,) = struct.unpack_from(">H", data, i)
                    if i + 2 + sl > n:
                        raise SldFormatError(
                            "a PROP_DATA string runs past the stream", detail={"stream": "PROP_DATA"}
                        )
                    values.append(data[i + 2 : i + 2 + sl].decode("utf-8", "replace"))
                    i += 2 + sl
                elif typ == T_INT:
                    if i + 4 > n:
                        raise SldFormatError(
                            "a PROP_DATA integer is cut short", detail={"stream": "PROP_DATA"}
                        )
                    values.append(struct.unpack_from("<i", data, i)[0])
                    i += 4
                elif typ == T_DOUBLE:
                    if i + 8 > n:
                        raise SldFormatError(
                            "a PROP_DATA number is cut short", detail={"stream": "PROP_DATA"}
                        )
                    values.append(struct.unpack_from("<d", data, i)[0])
                    i += 8
                elif typ == T_BLOB:
                    if i + 4 > n:
                        raise SldFormatError("a PROP_DATA blob is cut short", detail={"stream": "PROP_DATA"})
                    (bl,) = struct.unpack_from("<i", data, i)
                    if bl < 0 or i + 4 + bl > n:
                        raise SldFormatError(
                            "a PROP_DATA blob runs past the stream", detail={"stream": "PROP_DATA"}
                        )
                    values.append(data[i + 4 : i + 4 + bl])
                    i += 4 + bl
                else:
                    raise SldFormatError(
                        f"a PROP_DATA entry has the unknown type {typ}", detail={"stream": "PROP_DATA"}
                    )
            out.append(PropEntry(key, flags, typ, tuple(values)))
    except SolidSeasError as exc:
        return out, exc
    return out, None


def shown(key: str) -> bool:
    """Whether an entry is a property of the document, not the file's own bookkeeping
    (sizes, object types, hatching defaults, keys starting ``__``)."""
    return not (key in INTERNAL or key.startswith("__") or key.startswith("Hatch"))


_MONTHS = {
    m: k
    for k, m in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
    )
}
# Time zone abbreviations read, with their offsets from UTC in hours. Any other is not
# guessed: the time is then left out of the fields and kept as text.
ZONES = {
    "UTC": 0,
    "GMT": 0,
    "WET": 0,
    "WEST": 1,
    "BST": 1,
    "CET": 1,
    "CEST": 2,
    "EET": 2,
    "EEST": 3,
    "EST": -5,
    "EDT": -4,
    "CST": -6,
    "CDT": -5,
    "MST": -7,
    "MDT": -6,
    "PST": -8,
    "PDT": -7,
    "AKST": -9,
    "AKDT": -8,
    "HST": -10,
}
_TIME = re.compile(r"(\d{1,2}) ([A-Z][a-z]{2}) (\d{4}) (\d{2}):(\d{2}):(\d{2}) ([A-Z]{2,5})\Z")


def parse_time(text: str) -> datetime.datetime | None:
    """A stored time (``DD Mon YYYY HH:MM:SS ZZZ``, the one form seen) as an aware UTC
    datetime, or None for any other form or an unknown zone."""
    m = _TIME.match(text.strip())
    if m is None:
        return None
    day, mon, year, hh, mm, ss, zone = m.groups()
    month = _MONTHS.get(mon)
    offset = ZONES.get(zone)
    if month is None or offset is None:
        return None
    try:
        local = datetime.datetime(int(year), month, int(day), int(hh), int(mm), int(ss))
    except ValueError:
        return None
    return (local - datetime.timedelta(hours=offset)).replace(tzinfo=datetime.UTC)


_VERSION = re.compile(r"(\d+(?:,\d+){1,3})\s*\Z")


def application_version(text: str) -> str | None:
    """The version at the end of ``stepFileVersion`` (comma-separated numbers), dotted."""
    m = _VERSION.search(text.strip())
    return m.group(1).replace(",", ".") if m else None


__all__ = ["INTERNAL", "SNAPSHOT", "ZONES", "PropEntry", "application_version", "parse_time", "read", "shown"]
