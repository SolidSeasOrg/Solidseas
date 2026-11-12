"""Custom properties, configurations, material, units and summary fields.

Carriers (stream names as the container reports them; ``docs/FORMAT.md`` has
the evidence for each):

* 2015+ files: ``docProps/custom.xml`` (file-level custom properties),
  ``docProps/Config-<n>-Properties.xml`` (configuration-specific properties),
  ``docProps/ISolidWorksInformation.xml`` (units, active configuration and
  SOLIDWORKS summary fields), ``docProps/core.xml`` and ``docProps/app.xml``
  (OPC core properties), plus the binary ``Contents/CusProps`` as a second
  signal for linked expressions.
* Legacy files: MS-OLEPS property sets ``\\x05SummaryInformation``,
  ``\\x05DocumentSummaryInformation`` (custom properties in the user-defined
  section), ``Config-<n>-Properties`` and ``ISolidWorksInformation``.
* Both: ``swXmlContents/KeyWords`` (byte 0x86 then UTF-8 XML: configurations,
  comments, material), ``swXmlContents/Features`` (parts) or
  ``swXmlContents/COMPINSTANCETREE`` (assemblies), ``swXmlContents/MATERIALTREE``
  (UTF-16 XML), ``Header2`` and ``Contents/Definition`` (document-type GUID).

Every per-carrier problem becomes an entry in ``Metadata.warnings``; nothing
here raises for a damaged metadata stream.
"""

import datetime
import os
import re
import struct
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from typing import Any

from . import propset
from .container import Container
from .errors import LockedFileError, ReaderWarning

MAX_META_STREAM = 64 << 20  # metadata streams are small; anything bigger is refused

# Public SOLIDWORKS API enumerations (swUnitSystem_e, swLengthUnit_e, swAngleUnit_e, swUnitsMassPropMass_e)
UNIT_SYSTEM = {1: "CGS", 2: "MKS", 3: "IPS", 4: "Custom", 5: "MMGS"}
LENGTH_UNIT = {
    0: "mm",
    1: "cm",
    2: "m",
    3: "in",
    4: "ft",
    5: "ft-in",
    6: "angstrom",
    7: "nm",
    8: "micron",
    9: "mil",
    10: "microinch",
}
ANGLE_UNIT = {0: "deg", 1: "deg-min", 2: "deg-min-sec", 3: "rad"}
MASS_UNIT = {1: "mg", 2: "g", 3: "kg", 4: "lb"}
# The value type comes from the vt:* element name (or the legacy VARIANT type). The
# TypeID attribute is often 0 or absent on real files, so it is reported but never
# used to type a value. Property.type is one of these tokens.
PROPERTY_TYPES = ("text", "number", "boolean", "date", "other")
_INTEGER_VTS = frozenset(("i1", "i2", "i4", "i8", "ui1", "ui2", "ui4", "ui8", "int", "uint"))
PROP_TYPE = {
    **dict.fromkeys(("lpstr", "lpwstr", "bstr"), "text"),
    **dict.fromkeys(_INTEGER_VTS, "number"),
    **dict.fromkeys(("r4", "r8", "decimal"), "number"),
    "bool": "boolean",
    "filetime": "date",
    "date": "date",
}
# How SOLIDWORKS names each type in its own dialogs, for human-readable output.
TYPE_LABEL = {"text": "Text", "number": "Number", "boolean": "Yes or no", "date": "Date", "other": "Other"}

# {83A33D3x-27C5-11CE-BFD4-00400513BB57}, little-endian, x = 0 part, 6 assembly, 4 drawing
_GUID_RE = re.compile(rb"([\x30-\x3f])\x3d\xa3\x83\xc5\x27\xce\x11\xbf\xd4\x00\x40\x05\x13\xbb\x57")
DOC_KIND = {0: "part", 6: "assembly", 4: "drawing"}
EXT_KIND = {
    ".sldprt": "part",
    ".sldasm": "assembly",
    ".slddrw": "drawing",
    ".prtdot": "part",
    ".asmdot": "assembly",
    ".drwdot": "drawing",
}
_VT_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes}"


def calendar_day(value: Any) -> datetime.date | None:
    """The calendar day of a date property's ``value``. SOLIDWORKS stores the day typed
    as noon, local time, in UTC (``docs/FORMAT.md`` 11.1), so an aware value's UTC date
    is that day for a file saved anywhere from UTC-11 to UTC+12; a naive value's date
    part is its day. None when ``value`` is not a datetime."""
    if not isinstance(value, datetime.datetime):
        return None
    if value.tzinfo is not None and value.utcoffset() is not None:
        try:
            value = value.astimezone(datetime.UTC)
        except OverflowError:  # an offset that pushes year 1 or 9999 out of range: its own date
            pass
    return value.date()


@dataclass
class Property:
    """A custom property, file-level or configuration-specific.

    ``type`` is a token: ``"text"``, ``"number"``, ``"boolean"``, ``"date"`` or
    ``"other"``. ``value`` follows it: ``str`` for text, ``int`` or ``float``
    for a number, ``bool`` for a boolean, ``datetime.datetime`` for a date
    (aware UTC when the source carries a zone, naive otherwise), and None for
    "other" or when the stored text does not parse as its type (with a
    ``property_value_unreadable`` warning). ``text`` is always the stored text.
    ``linked=True`` means ``value`` is SOLIDWORKS' cached evaluation of
    ``expression`` (a link such as ``"SW-Mass@Part1.SLDPRT"``), which can be stale.
    A property that is not linked can still have an ``expression`` that differs from
    ``text``: the value as it was typed, such as ``3/15/2024`` for a date or ``3.25``
    for a number stored as ``3.250000``.
    """

    name: str
    value: Any
    text: str | None  # the evaluated value as stored text
    type: str
    expression: str | None  # the stored expression, or the literal value when nothing else is stored
    linked: bool  # True when value is evaluated from a link or equation in expression (e.g. "SW-Mass@...")
    expression_source: str | None
    pid: int
    vt: str | None
    type_id: int | None = None
    is_equation: bool | None = None
    scope: str = "file"  # "file" or "configuration"
    configuration: str | None = None  # the configuration a "configuration" property belongs to

    @property
    def type_label(self) -> str:
        """The type as SOLIDWORKS names it in its dialogs ("Text", "Number", "Yes or no", "Date")."""
        return TYPE_LABEL.get(self.type, "Other")

    @property
    def date(self) -> datetime.date | None:
        """A date property's calendar day (:func:`calendar_day`), which is what the user
        typed; None for the other types and for a date that did not parse."""
        return calendar_day(self.value) if self.type == "date" else None


@dataclass
class Configuration:
    name: str
    id: int | None = None
    comment: str | None = None
    material: str | None = None
    material_database: str | None = None
    material_assigned: bool | None = None
    active: bool = False
    most_recent: bool | None = None
    properties: list[Property] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


@dataclass
class Metadata:
    doc_type: str | None
    doc_type_source: str
    properties: list[Property] = field(default_factory=list)
    configurations: list[Configuration] = field(default_factory=list)
    active_configuration: str | None = None
    material: str | None = None
    material_database: str | None = None
    units: dict[str, Any] | None = None
    summary: dict[str, Any] = field(default_factory=dict)
    checks: dict[str, Any] = field(default_factory=dict)
    warnings: list[ReaderWarning] = field(default_factory=list)
    sources: dict[str, Any] = field(default_factory=dict)
    # every user name and save location each carrier stores, unmerged, for the path report:
    # dicts with field, value, stream and current (False for history: Header2 users, older saves)
    identity: list[dict[str, Any]] = field(default_factory=list, repr=False)
    # parsed carriers kept for the reference reader
    tree: dict[str, Any] = field(default_factory=dict, repr=False)
    tree_stream: str | None = None
    header2: dict[str, Any] = field(default_factory=dict, repr=False)
    own_file_ids: set[str] = field(default_factory=set, repr=False)
    # the id of the KeyWords root element: the document's own creation time (provisional)
    keywords_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("tree", "header2", "own_file_ids", "identity"):
            d.pop(k, None)
        return d


# --------------------------------------------------------------------------- helpers
def _read(c: Container, name: str, warnings: list[ReaderWarning]) -> bytes | None:
    """Read a metadata stream, None when absent. Errors become warnings."""
    if name not in c:
        return None
    try:
        info = c.info(name)
        if info.size > MAX_META_STREAM:
            msg = f"{info.size} bytes exceeds the metadata cap, skipped"
            warnings.append(ReaderWarning("stream_too_large", msg, name))
            return None
        return c.read(name, max_bytes=MAX_META_STREAM)
    except LockedFileError:
        raise  # a lock concerns the whole file, not this carrier
    except Exception as exc:  # SldError, KeyError: one bad carrier must not stop the rest
        warnings.append(ReaderWarning("stream_unreadable", f"read failed: {type(exc).__name__}: {exc}", name))
        return None


def xml_text(b: bytes | None) -> str | None:
    """XML stream bytes to str. Handles the 0x86 KeyWords prefix, UTF-16 with BOM and
    the mis-declared cp1252 bytes found in some ``docProps/app.xml`` streams."""
    if b is None:
        return None
    if b[:2] in (b"\xff\xfe", b"\xfe\xff"):
        t = b.decode("utf-16", "replace")
    else:
        i = b.find(b"<")
        if i < 0:
            return None
        b = b[i:]
        try:
            t = b.decode("utf-8")
        except UnicodeDecodeError:
            t = b.decode("cp1252", "replace")
    t = t.lstrip(chr(0xFEFF))  # byte-order mark
    return re.sub(r"^\s*<\?xml[^>]*\?>", "", t, count=1)  # the declared encoding no longer applies


def _parse_xml(b: bytes | None, name: str, warnings: list[ReaderWarning]):
    t = xml_text(b)
    if t is None:
        return None
    # SOLIDWORKS never writes a DTD. Refusing one blocks entity expansion on every
    # expat build, including old ones on Linux without the amplification limit.
    if re.search(r"<!(DOCTYPE|ENTITY)", t, re.I):
        warnings.append(
            ReaderWarning("xml_doctype_refused", "XML with a DOCTYPE or ENTITY declaration refused", name)
        )
        return None
    try:
        return ET.fromstring(t)
    except (ET.ParseError, ValueError) as exc:  # ValueError: text expat cannot take (a lone surrogate)
        warnings.append(ReaderWarning("xml_parse_error", f"XML parse error: {exc}", name))
        return None


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else str(tag)


def _iter_local(root, name: str):
    for el in root.iter():
        if _local(el.tag) == name:
            yield el


MAX_CSTRING_CHARS = 32_768  # names, expressions and paths are far shorter


def read_cstring(d: bytes, p: int, max_chars: int = MAX_CSTRING_CHARS) -> tuple[str | None, int]:
    """MFC CArchive Unicode CString: FF FE FF, u8 length (FF: u16, FFFF: u32), UTF-16LE.
    Returns ``(text, next_offset)`` or ``(None, p)``. A declared length over
    ``max_chars`` counts as no string, which keeps marker scans linear."""
    if d[p : p + 3] != b"\xff\xfe\xff" or p + 4 > len(d):
        return None, p
    n = d[p + 3]
    q = p + 4
    if n == 0xFF:
        if q + 2 > len(d):
            return None, p
        (n,) = struct.unpack_from("<H", d, q)
        q += 2
        if n == 0xFFFF:
            if q + 4 > len(d):
                return None, p
            (n,) = struct.unpack_from("<I", d, q)
            q += 4
    if n > max_chars or q + 2 * n > len(d):
        return None, p
    return d[q : q + 2 * n].decode("utf-16-le", "replace"), q + 2 * n


def basename_lower(p: str | None) -> str:
    return os.path.basename((p or "").replace("\\", "/")).lower()


def _parse_iso(s: str | None) -> datetime.datetime | None:
    """An ISO 8601 text as an aware UTC datetime (no offset is read as UTC), or None."""
    if not s or not isinstance(s, str):
        return None
    try:
        dt = datetime.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        return dt.astimezone(datetime.UTC) if dt.tzinfo else dt.replace(tzinfo=datetime.UTC)
    except (ValueError, OverflowError):  # OverflowError: an offset that moves year 1 or 9999 out of range
        return None


def _epoch_iso(t) -> str | None:
    try:
        return datetime.datetime.fromtimestamp(int(t), datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OverflowError, OSError):
        return None


# --------------------------------------------------------------------------- document type
def detect_doc_type(
    c: Container, path: str | None, warnings: list[ReaderWarning]
) -> tuple[str | None, str]:
    """``(doc_type, source)`` from the ``Contents/Definition`` GUID, else the file extension.

    ``doc_type`` is ``"part"``, ``"assembly"``, ``"drawing"`` or None, never any
    other string. A GUID that names another kind adds an ``unknown_document_kind``
    warning, and the type falls back to the extension of ``path`` (which may be a
    bare file name).
    """
    d = _read(c, "Contents/Definition", warnings)
    if d:
        m = _GUID_RE.search(d[:256])
        if m:
            x = m.group(1)[0] - 0x30
            if x in DOC_KIND:
                return DOC_KIND[x], "Contents/Definition"
            warnings.append(
                ReaderWarning(
                    "unknown_document_kind",
                    f"document kind {x} in the Definition GUID is not part (0), assembly (6) or drawing (4)",
                    "Contents/Definition",
                )
            )
    by_ext = EXT_KIND.get(os.path.splitext(path or "")[1].lower())
    return by_ext, "extension" if by_ext else "none"


# --------------------------------------------------------------------------- property carriers
def _xml_props(root) -> list[dict]:
    """docProps custom or configuration XML to property dicts.

    Each ``UserDefinedProperties`` ``<property name pid [IsEquation] [TypeID]>`` holds one
    ``vt:*`` value (the evaluated value) and optionally ``<FPVals>``. A property with
    ``pid = 0x01000000 | p`` and an empty name carries the expression of property p."""
    props: dict[int, dict] = {}
    hidden: dict[int, str | None] = {}
    for sec in _iter_local(root, "propertySection"):
        if sec.get("name") != "UserDefinedProperties":
            continue
        for pr in sec:
            if _local(pr.tag) != "property":
                continue
            try:
                pid = int(pr.get("pid", "-1"))
            except ValueError:
                continue
            name = pr.get("name", "")
            vt, val = None, None
            for ch in pr:
                if isinstance(ch.tag, str) and ch.tag.startswith(_VT_NS) and vt is None:
                    vt, val = _local(ch.tag), ch.text or ""
            if pid >= 0x01000000:
                hidden[pid & 0xFFFFFF] = val
                continue
            if not name or pid < 2:
                continue
            type_id = pr.get("TypeID") or ""
            props[pid] = {
                "name": name,
                "pid": pid,
                "vt": vt,
                "type": PROP_TYPE.get(vt, "other"),
                "type_id": _int_or_none(type_id),
                "is_equation": {"True": True, "False": False}.get(pr.get("IsEquation")),
                "value": val,
            }
    out = []
    for pid in sorted(props):
        p = props[pid]
        p["expression"] = hidden.get(pid)
        p["expression_source"] = "pid|0x01000000" if pid in hidden else None
        out.append(p)
    return out


def _xml_named_values(root) -> dict[str, str]:
    """``docProps/ISolidWorksInformation.xml`` to ``{name: value}``."""
    vals = {}
    for pr in _iter_local(root, "property"):
        name = pr.get("name")
        if not name:
            continue
        for ch in pr:
            if isinstance(ch.tag, str) and ch.tag.startswith(_VT_NS):
                vals[name] = ch.text if ch.text is not None else ""
                break
    return vals


def _ole_props(secs: list[dict]) -> list[dict]:
    """MS-OLEPS user-defined section to property dicts (same shape as ``_xml_props``)."""
    out = []
    for s in secs:
        if s["fmtid"] != propset.FMTID_USERDEFINED:
            continue
        hidden = {pid & 0xFFFFFF: v[1] for pid, v in s["props"].items() if pid >= 0x01000000}
        for pid in sorted(s["props"]):
            if pid < 2 or pid >= 0x01000000:
                continue
            name = s["names"].get(pid)
            if not name:
                continue
            vt, val = s["props"][pid]
            if vt == "bool":
                val = "Yes" if val else "No"
            out.append(
                {
                    "name": name,
                    "pid": pid,
                    "vt": vt,
                    "type": PROP_TYPE.get(vt, "other"),
                    "type_id": None,
                    "is_equation": None,
                    "value": val,
                    "expression": hidden.get(pid),
                    "expression_source": "pid|0x01000000" if pid in hidden else None,
                }
            )
    return out


def _ole_named_values(secs: list[dict]) -> dict[str, Any]:
    """ISolidWorksInformation property set to ``{name: value}``. Localised names such as
    ``SW-Autor(Author)`` are normalised with the English text in parentheses. Every value
    seen for a normalised name is also kept under ``(name, "all")``, because a file can
    carry an English and a localised copy that disagree."""
    vals: dict[Any, Any] = {}
    for s in secs:
        for pid, (_vt, v) in s["props"].items():
            nm = s["names"].get(pid)
            if nm is None:
                continue
            m = re.match(r"^SW-.*\((.+)\)$", nm)
            key = "SW-" + m.group(1) if m else nm
            if key not in vals or not m:
                vals[key] = v
            vals.setdefault((key, "all"), []).append(v)
    return vals


def _named_all(vals: dict[Any, Any], key: str) -> list[str]:
    """Every distinct non-empty text stored for the ISolidWorksInformation name ``key``,
    including localised copies such as ``SW-Autor(Author)``."""
    every = vals.get((key, "all"))
    if not isinstance(every, list):
        loc = re.compile(r"SW-.*\(" + re.escape(key[3:]) + r"\)")
        every = [v for k, v in vals.items() if isinstance(k, str) and (k == key or loc.fullmatch(k))]
    out: list[str] = []
    for v in every:
        if isinstance(v, str) and v.strip() and v not in out:
            out.append(v)
    return out


def parse_cusprops(d: bytes | None) -> list[dict]:
    """``Contents/CusProps``: the recurring element ``u32 9, CString name, u32 kind,
    CString expression, CString evaluated``. Used only as a second signal: which
    configuration each element belongs to is unknown."""
    out: list[dict] = []
    if not d:
        return out
    done = 0  # markers inside an element already decoded are not elements
    for m in re.finditer(rb"\x09\x00\x00\x00\xff\xfe\xff", d):
        if m.start() < done:
            continue
        name, q = read_cstring(d, m.start() + 4)
        if name is None:
            continue
        done = q
        if q + 4 > len(d):
            continue
        (kind,) = struct.unpack_from("<I", d, q)
        expr, r = read_cstring(d, q + 4)
        if expr is None:
            continue
        done = r
        ev, e = read_cstring(d, r)
        if ev is None:
            continue
        done = e
        out.append({"name": name, "kind": kind, "expression": expr, "evaluated": ev})
    return out


def _header2_creation_time(d: bytes, q: int) -> int | None:
    """The creation time in the ``Header2`` reference record whose path CString ends at
    ``q``: an optional u16 class tag, a CString (the referenced document's name), 3
    bytes, then a u32 Unix time. ``docs/FORMAT.md`` 12.2 has the corpus figures: it
    equals the component tree's ``swCreationTime`` for the same path in most
    records, with 86 counter-examples whose cause is unknown. The fields after it
    are a HYPOTHESIS and are not read. None when the record does not have that
    shape or holds 0."""
    p = q
    if d[p : p + 3] != b"\xff\xfe\xff":
        p += 2  # the class tag
    name, r = read_cstring(d, p)
    if name is None or r + 7 > len(d):
        return None
    (value,) = struct.unpack_from("<I", d, r + 3)
    return value or None


def parse_header2(d: bytes | None) -> dict[str, Any]:
    """``Header2``: an ``su_CStringArray`` of user names (the last one is usually the last
    saver) and CStrings holding absolute paths of referenced documents.
    ``creation_times`` maps each path to the creation time its reference record
    stores (see :func:`_header2_creation_time`), when it has one."""
    res: dict[str, Any] = {"users": [], "ext_paths": [], "creation_times": {}}
    if not d:
        return res
    i = d.find(b"su_CStringArray")
    if i >= 0:
        p = i + len(b"su_CStringArray")
        if p + 2 <= len(d):
            (n,) = struct.unpack_from("<H", d, p)
            p += 2
            for _ in range(min(n, 1000)):
                s, q = read_cstring(d, p)
                if s is None:
                    break
                res["users"].append(s)
                p = q
    done = 0  # markers inside a string already decoded are not strings
    for m in re.finditer(rb"\xff\xfe\xff", d):
        if m.start() < done:
            continue
        s, q = read_cstring(d, m.start())
        if s is not None:
            done = q
        if (
            s
            and re.search(r"\.(sldprt|sldasm|slddrw|prtdot|asmdot)$", s, re.I)
            and ("\\" in s or "/" in s or ":" in s)
            and s not in res["ext_paths"]
        ):
            res["ext_paths"].append(s)
            ct = _header2_creation_time(d, q)
            if ct is not None:
                res["creation_times"][s] = ct
    return res


_BOOLEAN_TEXT = {"1": True, "-1": True, "true": True, "yes": True, "0": False, "false": False, "no": False}


def _date_value(vt: str | None, raw) -> tuple[datetime.datetime | None, bool]:
    """A stored date as a datetime: aware UTC for FILETIME or text with an offset, naive
    otherwise (the saving machine's local time, zone unknown). FILETIME 0 and anything at
    or before 1601 mean "not set" and give None. Never raises."""
    if not isinstance(raw, str):
        return None, False
    s = raw.strip()
    if not s:
        return None, True
    try:
        dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if vt == "filetime" and dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.UTC)  # a FILETIME is UTC by definition
        if dt.tzinfo is not None:
            dt = dt.astimezone(datetime.UTC)
    except (ValueError, OverflowError):  # windows-datetime-range-errors: both, not only ValueError
        return None, False
    if dt.year <= 1601:
        return None, True
    return dt, True


def _typed(ptype: str, vt: str | None, raw) -> tuple[Any, bool]:
    """``(value, parsed)``: the stored value as the Python value of its type token.
    ``parsed`` is False when stored text does not parse as that type (value None)."""
    if raw is None:
        return None, True
    if ptype == "text":
        return (raw if isinstance(raw, str) else str(raw)), True
    if ptype == "number":
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            return None, False
        if not isinstance(raw, str):
            return raw, True
        try:
            return (int(raw.strip()) if vt in _INTEGER_VTS else float(raw.strip())), True
        except ValueError:  # also an integer text over Python's 4,300-digit conversion limit
            return None, False
    if ptype == "boolean":
        if isinstance(raw, bool):
            return raw, True
        v = _BOOLEAN_TEXT.get(str(raw).strip().lower())
        return v, v is not None
    if ptype == "date":
        return _date_value(vt, raw)
    return None, True  # "other": the stored text is all there is


def _as_text(v) -> str | None:
    if v is None or isinstance(v, (bytes, bytearray)):
        return None
    return v if isinstance(v, str) else str(v)


def _is_literal(ptype: str, expression: str | None, value) -> bool:
    """True when ``expression`` is a plain value of the property's own type that gives
    ``value``: a number that parses to it (``3.25`` for 3.250000) or a yes or no that
    means it. Such an expression links nothing, however it is formatted. A date as
    typed is never taken for one, since its form follows the saving machine's locale,
    and neither is a number with a decimal comma (``docs/FORMAT.md`` 11.1)."""
    if expression is None or value is None:
        return False
    if ptype == "number":
        v, ok = _typed("number", "r8", expression)
        try:
            return ok and v is not None and float(v) == float(value)
        except OverflowError:  # an integer beyond the float range
            return False
    if ptype == "boolean":
        v, ok = _typed("boolean", None, expression)
        return ok and v is value
    return False


def _finish_props(
    props: list[dict], cus_bin: list[dict] | None, warnings: list[ReaderWarning]
) -> tuple[int, int]:
    """Type the values, fill in the expression, decide ``linked``, and cross-check against
    ``Contents/CusProps``. Returns ``(agreeing, compared)``.

    A property is linked when the carrier that stores its expression stores a different
    evaluated value beside it, and the expression is not a literal of the property's
    type (:func:`_is_literal`). For the hidden ``pid | 0x01000000`` property that is the
    visible property's text, in the same stream; for ``Contents/CusProps`` it is the
    element's own evaluated text. The expression from one carrier is never compared
    with the text of the other: CusProps keeps a value as it was typed (``3/15/2024``,
    ``3.25``), the XML in its stored form (``2024-03-15T16:00:00Z``, ``3.250000``), and
    that difference links nothing (``docs/FORMAT.md`` 11.1)."""
    by_name: dict[str, list[dict]] = {}
    for e in cus_bin or []:
        by_name.setdefault(e["name"], []).append(e)
    n_ok = n_tot = 0
    for p in props:
        raw = p["value"]
        p["text"] = _as_text(raw)
        p["expression"] = _as_text(p["expression"])
        p["value"], parsed = _typed(p["type"], p["vt"], raw)
        if not parsed:
            shown = (p["text"] or "")[:40]
            warnings.append(
                ReaderWarning(
                    "property_value_unreadable",
                    f"property {p['name']!r}: {shown!r} is not a valid {p['type']} value",
                    p.get("stream"),
                )
            )
        hits = by_name.get(p["name"])
        differs = p["expression"] is not None and p["expression"] != p["text"]
        if hits:
            n_tot += 1
            if any(e["evaluated"] == p["text"] or e["expression"] == p["text"] for e in hits):
                n_ok += 1
            if p["expression"] is None:
                exprs = {e["expression"] for e in hits}
                if len(exprs) == 1:
                    ex = next(iter(exprs))
                    if ex != p["text"]:
                        p["expression"] = ex
                        p["expression_source"] = "Contents/CusProps"
                        differs = any(e["evaluated"] != ex for e in hits)
        if p["expression"] is None:
            p["expression"] = p["text"]
            p["expression_source"] = None
        p["linked"] = differs and not _is_literal(p["type"], p["expression"], p["value"])
    return n_ok, n_tot


def _to_property(p: dict, scope: str = "file", configuration: str | None = None) -> Property:
    return Property(
        name=p["name"],
        value=p["value"],
        text=p["text"],
        type=p["type"],
        expression=p["expression"],
        linked=p["linked"],
        expression_source=p["expression_source"],
        pid=p["pid"],
        vt=p["vt"],
        type_id=p.get("type_id"),
        is_equation=p.get("is_equation"),
        scope=scope,
        configuration=configuration,
    )


# --------------------------------------------------------------------------- XML trees
def _display_state(cfg_el) -> dict[str, str] | None:
    """``{swID: swShowState}`` of a configuration's first display state, or None.

    ``swDisplayStateList/@swCompNameList`` lists the ``swID`` of each instance of
    the configuration's own model (top-level instances only; ids restart inside
    each sub-assembly) and ``swDisplayState/@swShowState`` says ``Yes`` or ``No``
    for each, in the same order. Where a configuration stores several display
    states they never differ on the development corpus (6 lists), so the first
    one is taken.
    """
    for dl in cfg_el:
        if _local(dl.tag) != "swDisplayStateList":
            continue
        ids = [x for x in (dl.get("swCompNameList") or "").split(",") if x]
        for ds in dl:
            if _local(ds.tag) != "swDisplayState":
                continue
            shows = [x for x in (ds.get("swShowState") or "").split(",") if x]
            if len(shows) != len(ids):
                return None
            return dict(zip(ids, shows, strict=True))
        return None
    return None


def parse_sw_tree(root) -> dict[str, Any]:
    """``swXmlContents/Features`` or ``COMPINSTANCETREE`` (swSolidWorks schema).

    Each reference's ``hidden`` is meant to be what SOLIDWORKS reports as hidden, not
    the raw ``swHidden`` flag (kept as ``hidden_flag``). ``swHidden`` is ``YES`` on
    every suppressed instance (402 of 402 on the development corpus) whatever its
    visibility, so it means "hidden or suppressed". A top-level part instance takes
    its configuration's display state when that lists it (``swShowState`` ``No`` is
    hidden); any other instance, a sub-assembly instance included, is hidden when
    ``swHidden`` is ``YES`` and it is not suppressed. A sub-assembly's
    ``swShowState`` does not say whether it is shown: ``No`` is stored for
    sub-assemblies SOLIDWORKS draws (each of the 11 such unsuppressed instances on the
    development corpus has something hidden inside it), and on the 6 corpus
    assemblies where it disagrees with ``swHidden`` in the active configuration, the
    parts drawn by ``swHidden`` fill the box SOLIDWORKS stores for the assembly (to
    0.1 percent of its diagonal) in all 6, by the display state in 2. Only one case
    is checked against SOLIDWORKS itself (fixture o16): a suppressed instance with
    ``swHidden`` ``YES`` is reported visible, both where its display state says
    ``Yes`` and where the configuration has no display state. That the display
    state decides for a part, and that ``swHidden`` hides an unsuppressed instance,
    are a HYPOTHESIS (``docs/FORMAT.md`` 12.1): the fixtures show every instance.
    """
    res: dict[str, Any] = {
        "files": {},
        "models": {},
        "configs": [],
        "refs": [],
        "ext_features": [],
        "sw_version": None,
    }
    if root is None:
        return res
    res["sw_version"] = root.get("swVersion")
    for el in _iter_local(root, "swFile"):
        res["files"][el.get("id")] = {
            "path": el.get("swPath"),
            "doc_type": el.get("swDocType"),
            "creation_time": el.get("swCreationTime"),
            "imported": el.get("swImportedPath") is not None,
            "imported_path": el.get("swImportedPath"),
        }
    for el in _iter_local(root, "swModel"):
        res["models"][el.get("id")] = {
            "name": el.get("swName"),
            "config": el.get("swConfigurationName"),
            "file_ref": el.get("swFileRef"),
            "bbox": el.get("swBoundingBox"),
            "id": el.get("id"),
            # The configuration's alternate name, which a BOM can show as its part number
            # (docs/FORMAT.md 12.7), and its flags, kept as stored: what they mean is unknown.
            "alternate_name": el.get("swConfigurationAlternateName"),
            "flags": el.get("swConfigurationFlags"),
        }
        for r in el:
            if _local(r.tag) == "swReference":
                res["refs"].append(
                    {
                        "parent_model": el.get("id"),
                        "name": r.get("swName"),
                        "number": r.get("swReferenceNumber"),
                        "component_name": r.get("swComponentName"),
                        "sw_id": r.get("swID"),
                        "model_ref": r.get("swModelRef"),
                        "config": r.get("swConfigurationName"),
                        "suppressed": r.get("swSuppressed") == "YES",
                        "hidden_flag": r.get("swHidden") == "YES",
                        "virtual": r.get("swIsVirtualComponent") == "YES",
                        "exclude_from_bom": r.get("swExcludeFromBOM") == "YES",
                        "transform": r.get("swTransform"),
                    }
                )
    # A part's features that use another file (swXmlContents/Features): each names the
    # model, and so the swFile, it uses, and its feature type says how (Stock for a base
    # part, MirrorStock for a mirrored one, MBimport for an imported body).
    for el in _iter_local(root, "swExtFeature"):
        res["ext_features"].append(
            {
                "name": el.get("swName"),
                "type": el.get("swFeatureType"),
                "model_ref": el.get("swModelRef"),
                "config": el.get("swConfigurationName"),
                "suppressed": el.get("swSuppressed") not in (None, "0", "NO"),
            }
        )
    shown_by_model: dict[str, dict[str, str]] = {}
    for el in _iter_local(root, "swConfiguration"):
        shown = _display_state(el)
        res["configs"].append(
            {
                "name": el.get("swName"),
                "id": el.get("swID"),
                "most_recent": el.get("swMostRecentConfiguration") == "YES",
                "model_ref": el.get("swModelRef"),
                "display_state": shown,
            }
        )
        if shown is not None:
            shown_by_model.setdefault(el.get("swModelRef"), shown)
    for r in res["refs"]:
        state = shown_by_model.get(r["parent_model"], {}).get(r["sw_id"]) if r["sw_id"] else None
        file = res["files"].get((res["models"].get(r["model_ref"]) or {}).get("file_ref")) or {}
        is_assembly = (file.get("doc_type") or "").upper() == "ASSEMBLY"
        if state in ("Yes", "No") and not is_assembly:
            r["hidden"], r["hidden_source"] = state == "No", "display_state"
        else:
            r["hidden"], r["hidden_source"] = r["hidden_flag"] and not r["suppressed"], "flag"
    return res


def _keywords(root) -> dict[str, Any]:
    """``swXmlContents/KeyWords``: ``<Keywords id Name>`` with ``<Configuration id Name
    [Comment] [Material]>`` children."""
    res: dict[str, Any] = {"configs": [], "root_id": None}
    if root is None:
        return res
    res["root_id"] = root.get("id")
    for el in root:
        if _local(el.tag) == "Configuration":
            res["configs"].append(
                {
                    "id": el.get("id"),
                    "name": el.get("Name"),
                    "comment": el.get("Comment"),
                    "material": el.get("Material"),
                }
            )
    return res


def _materialtree(root) -> dict[str, Any]:
    res: dict[str, Any] = {"materials": [], "config_material": {}}
    if root is None:
        return res
    for el in _iter_local(root, "material"):
        db, _, nm = (el.get("name") or "").rpartition("|")
        dens = None
        for pp in _iter_local(el, "DENS"):
            dens = pp.get("value")
        res["materials"].append(
            {"database": db or None, "name": nm, "matid": el.get("matid"), "density": dens}
        )
    for el in _iter_local(root, "configuration"):
        parts = (el.get("material") or "").split("|")
        res["config_material"][el.get("name")] = {
            "database": parts[0] if len(parts) > 1 else None,
            "name": parts[1] if len(parts) > 1 else (parts[0] or None),
        }
    return res


# --------------------------------------------------------------------------- main reader
def _int_or_none(v) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


_OLE_PROPERTY_SETS = ("SummaryInformation", "DocumentSummaryInformation", "ISolidWorksInformation")
_CFG_PROPS = re.compile(r"(?i)config-(\d{1,9})-properties$")


def read_metadata(c: Container, path: str | None = None) -> Metadata:
    """Read every metadata carrier of an open document. Never raises for a damaged carrier."""
    w: list[str] = []
    doc_type, doc_type_source = detect_doc_type(c, path, w)
    md = Metadata(doc_type=doc_type, doc_type_source=doc_type_source, warnings=w)
    checks = md.checks
    by_ext = EXT_KIND.get(os.path.splitext(path or "")[1].lower())
    if doc_type_source == "Contents/Definition" and by_ext:
        checks["doc_type_guid_vs_extension"] = doc_type == by_ext

    # ---- raw carriers
    core = app = None
    isw: dict[str, Any] = {}
    custom: list[dict] | None = None
    cfg_prop_streams: dict[int, tuple[str, list[dict]]] = {}
    summ_ole: dict[str, Any] = {}
    isw_stream = summ_stream = None
    if c.format == "modern":
        core = _parse_xml(_read(c, "docProps/core.xml", w), "docProps/core.xml", w)
        app = _parse_xml(_read(c, "docProps/app.xml", w), "docProps/app.xml", w)
        custom_root = _parse_xml(_read(c, "docProps/custom.xml", w), "docProps/custom.xml", w)
        isw_name = "docProps/ISolidWorksInformation.xml"
        isw_root = _parse_xml(_read(c, isw_name, w), isw_name, w)
        isw = _xml_named_values(isw_root) if isw_root is not None else {}
        isw_stream = isw_name if isw_root is not None else None
        custom = _xml_props(custom_root) if custom_root is not None else None
        custom_stream = "docProps/custom.xml"
        for n in c.names():
            m = re.match(r"docProps/Config-(\d{1,9})-Properties\.xml$", n)
            if m:
                r = _parse_xml(_read(c, n, w), n, w)
                if r is not None:
                    cfg_prop_streams[int(m.group(1))] = (n, _xml_props(r))
    else:
        custom_stream = "\x05DocumentSummaryInformation"
        for n in c.names():
            base = n.lstrip("\x05")
            # Only these property sets are used; checking the head of every other stream
            # would read (and decompress) the whole document for nothing.
            if base not in _OLE_PROPERTY_SETS and not _CFG_PROPS.match(base.split("/")[-1]):
                continue
            try:
                if c.peek(n, 2) != b"\xfe\xff":
                    continue
            except LockedFileError:
                raise
            except Exception as exc:  # a damaged stream must not stop the others
                w.append(ReaderWarning("stream_unreadable", f"{type(exc).__name__}: {exc}", n))
                continue
            d = _read(c, n, w)
            if not d:
                continue
            try:
                secs = propset.parse(d)
            except propset.PropSetError as exc:
                w.append(ReaderWarning("property_set_error", f"property set error: {exc}", n))
                continue
            if base == "SummaryInformation":
                summ_stream = n
                for s in secs:
                    if s["fmtid"] == propset.FMTID_SUMMARY:
                        summ_ole = {
                            propset.SUMMARY_PIDS.get(k, k): v[1] for k, v in s["props"].items() if k != 1
                        }
            elif base == "DocumentSummaryInformation":
                custom = _ole_props(secs)
                custom_stream = n
            elif base == "ISolidWorksInformation":
                isw = _ole_named_values(secs)
                isw_stream = n
            else:
                m = _CFG_PROPS.match(base.split("/")[-1])
                if m:
                    cfg_prop_streams[int(m.group(1))] = (n, _ole_props(secs))

    kw = _keywords(_parse_xml(_read(c, "swXmlContents/KeyWords", w), "swXmlContents/KeyWords", w))
    tree_name = (
        "swXmlContents/COMPINSTANCETREE"
        if "swXmlContents/COMPINSTANCETREE" in c
        else "swXmlContents/Features"
    )
    tree = parse_sw_tree(_parse_xml(_read(c, tree_name, w), tree_name, w))
    mt = _materialtree(_parse_xml(_read(c, "swXmlContents/MATERIALTREE", w), "swXmlContents/MATERIALTREE", w))
    h2 = parse_header2(_read(c, "Header2", w))
    cus_bin = parse_cusprops(_read(c, "Contents/CusProps", w)) if "Contents/CusProps" in c else None
    md.tree, md.tree_stream, md.header2 = tree, (tree_name if tree_name in c else None), h2
    md.keywords_id = kw["root_id"]

    # ---- summary
    summary: dict[str, Any] = {}
    src: dict[str, str] = {}
    ident: list[dict[str, Any]] = []

    def identity(fld: str, val, stream: str | None, current: bool = True) -> None:
        if isinstance(val, str) and val.strip():
            ident.append({"field": fld, "value": val, "stream": stream, "current": current})

    def put(key: str, val, source: str) -> None:
        if val not in (None, "") and summary.get(key) in (None, ""):
            summary[key] = val
            src[key] = source

    if core is not None:
        # core.xml can hold several (lastModifiedBy, created, modified) groups, one per earlier
        # save, in no reliable order: the newest 'modified' is the last save.
        saves: list[dict] = []
        cur: dict = {}
        for el in list(core):
            lt = _local(el.tag)
            if lt in ("lastModifiedBy", "created", "modified"):
                if lt in cur:
                    saves.append(cur)
                    cur = {}
                cur[lt] = el.text
            elif lt in ("title", "subject", "creator", "keywords", "description", "category", "revision"):
                put(
                    {"creator": "author", "description": "comments"}.get(lt, lt), el.text, "docProps/core.xml"
                )
                if lt == "creator":
                    identity("core_creator", el.text, "docProps/core.xml")
        if cur:
            saves.append(cur)
        for s in saves:
            dtc = _parse_iso(s.get("created"))
            if dtc is not None and dtc.year <= 1601:
                s["created"] = None  # FILETIME 0 written as 1601-01-01 means unset
        floor = datetime.datetime.min.replace(tzinfo=datetime.UTC)
        best = max(saves, key=lambda s: _parse_iso(s.get("modified")) or floor, default=None)
        for s in saves:
            identity("core_last_modified_by", s.get("lastModifiedBy"), "docProps/core.xml", s is best)
        if best:
            put("last_saved_by", best.get("lastModifiedBy"), "docProps/core.xml")
            put("last_saved_utc", best.get("modified"), "docProps/core.xml")
            created = [s["created"] for s in saves if s.get("created")]
            ceiling = datetime.datetime.max.replace(tzinfo=datetime.UTC)
            if created:
                put("created_utc", min(created, key=lambda s: _parse_iso(s) or ceiling), "docProps/core.xml")
        summary["core_save_records"] = len(saves)
    if summ_ole:
        for key, pkey in (
            ("title", "title"),
            ("subject", "subject"),
            ("author", "author"),
            ("keywords", "keywords"),
            ("comments", "comments"),
            ("last_saved_by", "last_author"),
            ("created_utc", "created"),
            ("last_saved_utc", "last_saved"),
        ):
            put(key, summ_ole.get(pkey), "SummaryInformation")
        identity("summary_author", summ_ole.get("author"), summ_stream)
        identity("summary_last_author", summ_ole.get("last_author"), summ_stream)
    isw_src = "docProps/ISolidWorksInformation.xml" if c.format == "modern" else "ISolidWorksInformation"
    for key, iname in (
        ("title", "SW-Title"),
        ("subject", "SW-Subject"),
        ("author", "SW-Author"),
        ("keywords", "SW-Keywords"),
        ("comments", "SW-Comments"),
        ("last_saved_by", "SW-Last Saved By"),
    ):
        put(key, isw.get(iname), isw_src)
    summary["created_local_text"] = isw.get("SW-Created Date")
    summary["last_saved_local_text"] = isw.get("SW-Last Saved Date")
    summary["file_name_at_save"] = isw.get("SW-File Name")
    summary["folder_at_save"] = isw.get("SW-Folder Name")
    if app is not None:
        for el in _iter_local(app, "AppVersion"):
            summary["app_version"] = el.text
    own_fids = {tree["models"].get(cf["model_ref"], {}).get("file_ref") for cf in tree["configs"]} - {None}
    md.own_file_ids = own_fids
    if len(own_fids) == 1:
        fi = tree["files"].get(next(iter(own_fids)), {})
        ct = fi.get("creation_time")
        summary["created_epoch_utc"] = _epoch_iso(ct) if ct and ct.lstrip("-").isdigit() else None
    summary["header2_users"] = h2["users"]
    for key, fld in (
        ("SW-Author", "sw_author"),
        ("SW-Last Saved By", "sw_last_saved_by"),
        ("SW-File Name", "file_name_at_save"),
        ("SW-Folder Name", "folder_at_save"),
    ):
        for v in _named_all(isw, key):
            identity(fld, v, isw_stream)
    for u in h2["users"]:
        identity("header2_user", u, "Header2", False)
    md.identity = ident
    md.summary = summary
    md.sources["summary"] = src
    lsb = []
    if src.get("last_saved_by") == "docProps/core.xml":
        lsb.append(summary["last_saved_by"])
    if summ_ole.get("last_author"):
        lsb.append(summ_ole["last_author"])
    if isw.get("SW-Last Saved By"):
        lsb.append(isw["SW-Last Saved By"])
    if len(lsb) >= 2:
        checks["last_saved_by_two_carriers"] = len(set(lsb)) == 1

    # ---- custom properties
    file_props = custom or []
    for p in file_props:
        p["stream"] = custom_stream
    for sname, props in cfg_prop_streams.values():
        for p in props:
            p["stream"] = sname
    all_cfg_props = [p for (_, props) in cfg_prop_streams.values() for p in props]
    agree, compared = _finish_props(file_props + all_cfg_props, cus_bin, w)
    if compared:
        checks["custom_properties_vs_cusprops"] = f"{agree}/{compared}"
    md.properties = [_to_property(p) for p in file_props]
    md.sources["properties"] = "docProps/custom.xml" if c.format == "modern" else "DocumentSummaryInformation"

    # ---- configurations
    cfgs: dict[str, Configuration] = {}

    def cfg(name: str) -> Configuration:
        if name not in cfgs:
            cfgs[name] = Configuration(name=name)
        return cfgs[name]

    for tc in tree["configs"]:
        if tc["name"] is None:
            continue
        x = cfg(tc["name"])
        x.id = _int_or_none(tc["id"]) if x.id is None else x.id
        x.most_recent = tc["most_recent"]
        x.sources.append(tree_name)
    for kc in kw["configs"]:
        if kc["name"] is None:
            continue
        x = cfg(kc["name"])
        if x.id is None:
            x.id = _int_or_none(kc["id"])
        x.comment = kc["comment"]
        if kc["material"]:
            x.material = kc["material"]
        x.sources.append("swXmlContents/KeyWords")
    def placeholder(m: str | None) -> bool:
        # With no material assigned, KeyWords stores the localised UI placeholder,
        # for example "Material <not specified>".
        return bool(m and re.search(r"<[^<>]+>\s*$", m))

    # MATERIALTREE only attaches materials. Configuration names come from the tree
    # and KeyWords; MATERIALTREE can list stale or differently cased names.
    by_lower = {k.lower(): k for k in cfgs}
    in_mt: set[str] = set()
    for name, mat in mt["config_material"].items():
        if name is None:
            continue
        key = name if name in cfgs else by_lower.get(name.lower())
        if key is None:
            if cfgs:
                w.append(
                    ReaderWarning(
                        "materialtree_unknown_configuration",
                        f"names configuration {name!r}, absent from the tree and KeyWords",
                        "swXmlContents/MATERIALTREE",
                    )
                )
                continue
            key = name  # no other source of configuration names: MATERIALTREE is all there is
        x = cfg(key)
        in_mt.add(key)
        x.material_database = mat["database"]
        if (x.material is None or placeholder(x.material)) and mat["name"]:
            x.material = mat["name"]
        elif mat["name"] and x.material != mat["name"]:
            w.append(
                ReaderWarning(
                    "material_mismatch",
                    f"material mismatch for {name!r}: "
                    f"KeyWords {x.material!r} vs MATERIALTREE {mat['name']!r}",
                )
            )
        x.sources.append("swXmlContents/MATERIALTREE")
    for x in cfgs.values():
        if x.name in in_mt and x.material and not placeholder(x.material):
            x.material_assigned = True
        elif placeholder(x.material) or not x.material:
            x.material_assigned = False
            x.material = None
        else:
            x.material_assigned = None
    by_id = {x.id: x for x in cfgs.values() if x.id is not None}
    unmatched = {}
    for n_id, (sname, props) in sorted(cfg_prop_streams.items()):
        if n_id in by_id:
            owner = by_id[n_id]
            owner.properties = [_to_property(p, "configuration", owner.name) for p in props]
            owner.sources.append(sname)
        elif props:
            unmatched[str(n_id)] = [_to_property(p, "configuration") for p in props]
    if unmatched:
        md.sources["configuration_properties_unmatched"] = {
            k: [asdict(p) for p in v] for k, v in unmatched.items()
        }
    active = isw.get("SW-Configuration Name")
    most_recent_names = [tc["name"] for tc in tree["configs"] if tc["most_recent"]]
    if most_recent_names and active not in most_recent_names:
        # An English and a localised copy can disagree; the one the tree marks as most
        # recently used is the current one.
        for cand in isw.get(("SW-Configuration Name", "all"), []):
            if cand in most_recent_names:
                active = cand
                break
    if md.doc_type == "drawing":
        # Drawings have no configurations. Their SW-Configuration Name holds the long date
        # (equal to SW-Long Date in 22 of 22 corpus drawings that store it, and in o18, o19).
        active = None
    md.active_configuration = active if isinstance(active, str) and active else None
    if md.active_configuration in cfgs:
        cfgs[md.active_configuration].active = True
    md.configurations = list(cfgs.values())
    most_recent = [tc["name"] for tc in tree["configs"] if tc["most_recent"]]
    if md.active_configuration and most_recent:
        checks["active_configuration_vs_tree_most_recent"] = md.active_configuration in most_recent
    if tree["configs"] and kw["configs"]:
        checks["configuration_names_tree_vs_keywords"] = {t["name"] for t in tree["configs"]} == {
            k["name"] for k in kw["configs"]
        }
    if tree["sw_version"]:
        md.sources["tree_sw_version"] = tree["sw_version"]

    # ---- material of the active configuration (or the only one in use)
    mats = []
    for x in md.configurations:
        if x.material and x.material not in mats:
            mats.append(x.material)
    act = cfgs.get(md.active_configuration) if md.active_configuration else None
    if act is not None:
        md.material, md.material_database = act.material, act.material_database
    elif len(mats) == 1:
        md.material = mats[0]
        md.material_database = next(
            (x.material_database for x in md.configurations if x.material == mats[0]), None
        )

    # ---- units
    us = _int_or_none(isw.get("SW_UnitSystem"))
    if us is not None:
        ul, ua, um = (
            _int_or_none(isw.get(k)) for k in ("SW_UnitsLinear", "SW_UnitsAngular", "SW_UnitsMassPropMass")
        )
        md.units = {
            "system": UNIT_SYSTEM.get(us, us),
            "length": LENGTH_UNIT.get(ul, ul),
            "angle": ANGLE_UNIT.get(ua, ua),
            "mass": MASS_UNIT.get(um, um),
            "length_decimal_places": _int_or_none(isw.get("SW_UnitsLinearDecimalPlaces")),
            "raw": {
                k: v
                for k, v in isw.items()
                if isinstance(k, str) and (k.startswith("SW_Units") or k == "SW_UnitSystem")
            },
            "source": isw_src,
        }
        expect = {1: ("cm", "g"), 2: ("m", "kg"), 3: ("in", "lb"), 5: ("mm", "g")}
        if us in expect:
            checks["unit_system_implies_length_and_mass"] = (md.units["length"], md.units["mass"]) == expect[
                us
            ]
    return md
