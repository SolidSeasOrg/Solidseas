"""A minimal reader for MS-OLEPS property set streams.

Written from Microsoft's public [MS-OLEPS] specification (PropertySetStream,
PropertySet, Dictionary, TypedPropertyValue). Legacy SOLIDWORKS documents keep
their summary, custom and configuration properties in such streams.
Read-only and bounds-checked: malformed input raises :class:`PropSetError`
and nothing is read outside the buffer.
"""

import datetime
import struct

from .errors import SldFormatError


class PropSetError(SldFormatError):
    """A property set stream is malformed."""


FMTID_SUMMARY = "{F29F85E0-4FF9-1068-AB91-08002B27B3D9}"
FMTID_DOCSUMMARY = "{D5CDD502-2E9C-101B-9397-08002B2CF9AE}"
FMTID_USERDEFINED = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}"

# Standard SummaryInformation property ids ([MS-OLEPS] and [MS-OSHARED])
SUMMARY_PIDS = {
    2: "title",
    3: "subject",
    4: "author",
    5: "keywords",
    6: "comments",
    7: "template",
    8: "last_author",
    9: "revision_number",
    10: "edit_time",
    11: "last_printed",
    12: "created",
    13: "last_saved",
    14: "page_count",
    15: "word_count",
    16: "char_count",
    18: "app_name",
    19: "security",
}


def guid_str(b: bytes) -> str:
    a, b1, c = struct.unpack_from("<IHH", b)
    return f"{{{a:08X}-{b1:04X}-{c:04X}-{b[8:10].hex().upper()}-{b[10:16].hex().upper()}}}"


def filetime_to_iso(ft: int) -> str | None:
    if not ft:
        return None
    try:
        dt = datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=ft // 10)
    except OverflowError:
        return None
    return dt.isoformat() + "Z"


def codepage_codec(cp: int) -> str:
    """The Python codec for a Windows code page: ``utf-8`` for 65001, ``utf-16-le`` for
    1200, ``cp<n>`` when Python knows it, and cp1252 for anything else."""
    if cp == 65001:
        return "utf-8"
    if cp == 1200:
        return "utf-16-le"
    name = f"cp{cp}"
    try:
        b"".decode(name)
    except LookupError:
        return "cp1252"
    return name


def _cpdecode(b: bytes, cp: int) -> str:
    if cp == 1200:
        s = b.decode("utf-16-le", "replace")
    else:
        s = b.split(b"\0", 1)[0].decode(codepage_codec(cp), "replace")
    return s.split("\0", 1)[0]


def _value(d: bytes, off: int, end: int, cp: int) -> tuple[str, object]:
    if off + 4 > end:
        raise PropSetError("value header out of bounds")
    (vt,) = struct.unpack_from("<H", d, off)
    p = off + 4

    def need(n: int) -> None:
        if p + n > end:
            raise PropSetError("value out of bounds")

    fixed = {
        2: ("i2", "<h", 2),
        0x12: ("ui2", "<H", 2),
        3: ("i4", "<i", 4),
        0x16: ("i4", "<i", 4),
        0x13: ("ui4", "<I", 4),
        0x17: ("ui4", "<I", 4),
        4: ("r4", "<f", 4),
        5: ("r8", "<d", 8),
        0x14: ("i8", "<q", 8),
        0x15: ("ui8", "<Q", 8),
    }
    if vt & 0x1000:
        return ("vector", None)
    if vt in fixed:
        name, fmt, size = fixed[vt]
        need(size)
        return (name, struct.unpack_from(fmt, d, p)[0])
    if vt == 0xB:
        need(2)
        return ("bool", struct.unpack_from("<H", d, p)[0] != 0)
    if vt == 7:
        need(8)
        x = struct.unpack_from("<d", d, p)[0]
        try:
            return ("date", (datetime.datetime(1899, 12, 30) + datetime.timedelta(days=x)).isoformat())
        except (OverflowError, ValueError):
            return ("date", None)
    if vt == 0x40:
        need(8)
        return ("filetime", filetime_to_iso(struct.unpack_from("<Q", d, p)[0]))
    if vt in (0x1E, 8):
        need(4)
        (n,) = struct.unpack_from("<I", d, p)
        need(4 + n)
        return ("lpstr", _cpdecode(d[p + 4 : p + 4 + n], cp))
    if vt == 0x1F:
        need(4)
        (n,) = struct.unpack_from("<I", d, p)
        need(4 + 2 * n)
        return ("lpwstr", d[p + 4 : p + 4 + 2 * n].decode("utf-16-le", "replace").split("\0", 1)[0])
    if vt == 0x41:
        need(4)
        (n,) = struct.unpack_from("<I", d, p)
        need(4 + n)
        return ("blob", bytes(d[p + 4 : p + 4 + n]))
    if vt == 0x48:
        need(16)
        return ("clsid", guid_str(d[p : p + 16]))
    if vt in (0, 1):
        return ("empty", None)
    return (f"vt_0x{vt:x}", None)


def parse(d: bytes) -> list[dict]:
    """Parse a PropertySetStream.

    Returns one dict per section: ``{"fmtid", "codepage", "props": {pid: (type, value)},
    "names": {pid: name}}``.
    """
    if len(d) < 28 or d[:2] != b"\xfe\xff":
        raise PropSetError("not a property set stream")
    (nsets,) = struct.unpack_from("<I", d, 24)
    if nsets > 16 or 28 + 20 * nsets > len(d):
        raise PropSetError("bad section count")
    out = []
    for i in range(nsets):
        fmtid = d[28 + 20 * i : 44 + 20 * i]
        (off,) = struct.unpack_from("<I", d, 44 + 20 * i)
        if off + 8 > len(d):
            raise PropSetError("section offset out of bounds")
        size, nprop = struct.unpack_from("<II", d, off)
        end = min(len(d), off + size)
        if nprop > 100000 or off + 8 + 8 * nprop > end:
            raise PropSetError("bad property count")
        ids = [struct.unpack_from("<II", d, off + 8 + 8 * k) for k in range(nprop)]
        cp = 1252
        for pid, po in ids:
            if pid == 1 and off + po + 6 <= end:
                cp = struct.unpack_from("<H", d, off + po + 4)[0]
        props: dict[int, tuple[str, object]] = {}
        names: dict[int, str] = {}
        for pid, po in ids:
            a = off + po
            if pid == 0:  # Dictionary
                if a + 4 > end:
                    raise PropSetError("dictionary out of bounds")
                (n,) = struct.unpack_from("<I", d, a)
                q = a + 4
                for _ in range(min(n, 100000)):
                    if q + 8 > end:
                        raise PropSetError("dictionary entry out of bounds")
                    k, ln = struct.unpack_from("<II", d, q)
                    q += 8
                    if cp == 1200:  # UTF-16 names are counted in characters and padded to 4 bytes
                        if q + 2 * ln > end:
                            raise PropSetError("dictionary name out of bounds")
                        names[k] = d[q : q + 2 * ln].decode("utf-16-le", "replace").split("\0", 1)[0]
                        q += 2 * ln
                        q += (-(q - a)) % 4
                    else:
                        if q + ln > end:
                            raise PropSetError("dictionary name out of bounds")
                        names[k] = _cpdecode(d[q : q + ln], cp)
                        q += ln
                continue
            if pid == 0x80000000:  # Locale
                continue
            props[pid] = _value(d, a, end, cp)
        out.append({"fmtid": guid_str(fmtid), "codepage": cp, "props": props, "names": names})
    return out
