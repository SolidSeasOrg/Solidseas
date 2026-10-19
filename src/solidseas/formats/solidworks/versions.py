"""Which SOLIDWORKS version saved a document.

* Every document has exactly one stream-name prefix ``_MO_VERSION_<n>/``; ``n``
  is the internal document version of the last save (17000 for SOLIDWORKS
  2024, verified on the synthetic fixtures).
* ``_MO_VERSION_<n>/History`` is an MFC-serialised ``moVersionHistory_c`` with
  one entry per version the document was ever saved in, each with the build
  date codes (``YYYYDDD``) of the builds that saved it. The last code of the
  last entry is the build that last saved the file (2024016 for SOLIDWORKS
  2024 SP1, verified).
* The mapping from ``n`` to a release name is a hypothesis except for 17000,
  supported by the build dates found in the development corpus.
"""

import datetime
import re
import struct
from dataclasses import dataclass, field

from .container import Container
from .errors import ReaderWarning, SldError

MAX_HISTORY_BYTES = 8 << 20

# HYPOTHESIS except 17000 = SOLIDWORKS 2024 (verified): for every release version the
# earliest build date code seen in any History stream of the development corpus falls in
# August to October of the year before the release label.
_RELEASES = {
    1500: "2000",
    1750: "2001",
    1950: "2001Plus",
    2200: "2003",
    2500: "2004",
    2800: "2005",
    3100: "2006",
    3400: "2007",
    3800: "2008",
    4100: "2009",
    4400: "2010",
    4700: "2011",
    5000: "2012",
    6000: "2013",
    7000: "2014",
    8000: "2015",
}
VERIFIED_RELEASES = {17000: "SOLIDWORKS 2024"}

# At most 12 digits: a crafted name with thousands of digits must not reach int().
_MO = re.compile(r"_MO_VERSION_(-?\d{1,12})/")
_DL = re.compile(r"_DL_VERSION_(-?\d{1,12})/")


def release_name(version: int | None) -> str | None:
    """Release name for an internal document version, e.g. 17000 -> "SOLIDWORKS 2024".

    None for versions that are not main releases (pre-release builds such as
    16800 or 10191 occur only inside History streams)."""
    if not isinstance(version, int):
        return None
    if version in _RELEASES:
        return "SOLIDWORKS " + _RELEASES[version]
    if version >= 9000 and version % 1000 == 0:
        return f"SOLIDWORKS {2007 + version // 1000}"
    return None


def datecode_to_date(code: int) -> str | None:
    """HYPOTHESIS: a build date code is ``YYYY * 1000 + day of year``. Returns ISO date or None."""
    y, d = divmod(code, 1000)
    if not (1990 <= y <= 2100 and 1 <= d <= 366):
        return None
    try:
        return (datetime.date(y, 1, 1) + datetime.timedelta(days=d - 1)).isoformat()
    except ValueError:
        return None


@dataclass(frozen=True)
class HistoryEntry:
    version: int
    first_saved_utc: str | None  # when the document first reached this version
    datecodes: tuple[int, ...]  # builds that saved it in this version (low 24 bits)
    flags: tuple[int, ...]  # high byte of each date code word, meaning unknown


def _u16(b: bytes, o: int) -> int:
    return struct.unpack_from("<H", b, o)[0]


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def _cstring(b: bytes, o: int) -> tuple[str, int]:
    """MFC CString: FF FE FF, u8 length (FF: u16 length follows), UTF-16LE."""
    if b[o : o + 3] != b"\xff\xfe\xff":
        raise ValueError(f"no CString at {o}")
    o += 3
    n = b[o]
    o += 1
    if n == 0xFF:
        n = _u16(b, o)
        o += 2
    if o + 2 * n > len(b):
        raise ValueError("CString overruns the stream")
    return b[o : o + 2 * n].decode("utf-16-le", "replace"), o + 2 * n


def _epoch_iso(t: int) -> str | None:
    try:
        return datetime.datetime.fromtimestamp(t, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None


def parse_history(b: bytes) -> list[HistoryEntry]:
    """Parse ``_MO_VERSION_<n>/History``. Raises ``ValueError`` on an unexpected layout.

    Layout: MFC new-class tag ``FF FF, u16 schema, u16 length, "moVersionHistory_c"``,
    u32 count, then per entry ``u16, u16, u16`` (meaning unknown), ``u32`` Unix time,
    a CString (always empty), ``u32`` version, then a ``moDateCodeHistory_c`` object
    (class definition the first time, a 2-byte back-reference after that) holding
    ``u32 m`` and ``m`` u32 words whose low 24 bits are build date codes.
    """
    try:
        if b[0:2] != b"\xff\xff":
            raise ValueError("no class tag")
        ln = _u16(b, 4)
        cls = b[6 : 6 + ln].decode("latin-1")
        if cls != "moVersionHistory_c":
            raise ValueError(f"class {cls}")
        o = 6 + ln
        count = _u32(b, o)
        o += 4
        if count > 1000:
            raise ValueError(f"count {count}")
        entries = []
        dc_class_seen = False
        for _ in range(count):
            o += 6  # three u16 of unknown meaning
            ts = _u32(b, o)
            o += 4
            _note, o = _cstring(b, o)
            ver = _u32(b, o)
            o += 4
            tag = _u16(b, o)
            if tag == 0xFFFF:
                ln2 = _u16(b, o + 4)
                cname = b[o + 6 : o + 6 + ln2].decode("latin-1")
                if cname != "moDateCodeHistory_c":
                    raise ValueError(f"date-code class {cname}")
                o += 6 + ln2
                dc_class_seen = True
            elif tag & 0x8000 and dc_class_seen:
                o += 2
            else:
                raise ValueError(f"date-code tag {tag:04x} at {o}")
            m = _u32(b, o)
            o += 4
            if m > 10000 or o + 4 * m > len(b):
                raise ValueError(f"date-code count {m}")
            raw = struct.unpack_from(f"<{m}I", b, o)
            o += 4 * m
            entries.append(
                HistoryEntry(
                    ver, _epoch_iso(ts), tuple(x & 0xFFFFFF for x in raw), tuple(x >> 24 for x in raw)
                )
            )
        return entries
    except (struct.error, IndexError) as exc:
        raise ValueError(f"truncated History stream: {exc}") from exc


@dataclass
class SavedVersion:
    """The version that last saved a document, and its history."""

    format_version: int | None  # n of _MO_VERSION_<n>
    release: str | None  # e.g. "SOLIDWORKS 2024"; hypothesis except 17000
    release_verified: bool
    last_build: int | None  # date code of the build that last saved it, e.g. 2024016
    last_build_date: str | None  # the date code read as YYYYDDD (hypothesis)
    save_as_previous: bool  # History goes back to an older version after a newer one
    display_list_version: int | None  # n of _DL_VERSION_<n>
    history: list[HistoryEntry] = field(default_factory=list)
    warnings: list[ReaderWarning] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "format_version": self.format_version,
            "release": self.release,
            "release_verified": self.release_verified,
            "last_build": self.last_build,
            "last_build_date": self.last_build_date,
            "save_as_previous": self.save_as_previous,
            "display_list_version": self.display_list_version,
            "history": [
                {"version": e.version, "first_saved_utc": e.first_saved_utc, "datecodes": list(e.datecodes)}
                for e in self.history
            ],
        }


def read_saved_version(container: Container) -> SavedVersion:
    names = container.names()
    mos = sorted({int(m.group(1)) for n in names if (m := _MO.match(n))})
    dls = sorted({int(m.group(1)) for n in names if (m := _DL.match(n))})
    warnings: list[ReaderWarning] = []
    if len(mos) > 1:
        warnings.append(ReaderWarning("version_prefix_ambiguous", f"several _MO_VERSION prefixes: {mos}"))
    mo = mos[-1] if mos else None
    sv = SavedVersion(
        format_version=mo,
        release=release_name(mo),
        release_verified=mo in VERIFIED_RELEASES,
        last_build=None,
        last_build_date=None,
        save_as_previous=False,
        display_list_version=dls[-1] if dls else None,
        warnings=warnings,
    )
    if mo is None:
        warnings.append(ReaderWarning("version_prefix_missing", "no _MO_VERSION_<n> stream prefix"))
        return sv
    name = f"_MO_VERSION_{mo}/History"
    if name not in container:
        warnings.append(ReaderWarning("version_history_missing", "missing", name))
        return sv
    try:
        sv.history = parse_history(container.read(name, max_bytes=MAX_HISTORY_BYTES))
    except (SldError, ValueError) as exc:
        warnings.append(ReaderWarning("version_history_unreadable", str(exc), name))
        return sv
    if sv.history and sv.history[-1].datecodes:
        sv.last_build = sv.history[-1].datecodes[-1]
        sv.last_build_date = datecode_to_date(sv.last_build)
    versions = [e.version for e in sv.history]
    sv.save_as_previous = any(versions[i] < max(versions[:i]) for i in range(1, len(versions)))
    if versions and versions[-1] != mo:
        warnings.append(
            ReaderWarning(
                "version_history_mismatch",
                f"History ends with {versions[-1]}, storage prefix says {mo}",
                name,
            )
        )
    return sv
