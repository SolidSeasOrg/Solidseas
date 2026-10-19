"""ISO 10303-21 exchange structures (STEP Part 21 files), read bounded (provisional).

Written from ISO 10303-21:2016 (clause 5, the exchange structure; clause 6, the
encoding of strings), not adapted from any other reader. Pure Python, standard
library only.

* :func:`read_header` parses the header section alone: ``FILE_DESCRIPTION``,
  ``FILE_NAME`` and ``FILE_SCHEMA``, within ``p21_header_bytes``. A listing
  reads nothing else.
* :class:`Part21` indexes the data sections in one pass over the bytes: each
  entity instance's id, where its text starts and ends, and its entity name (a
  complex instance's names in order). The index is four arrays over a name
  table, about 28 bytes an instance, so a file of a million instances costs
  tens of megabytes, not a parsed object each. A record's parameters are parsed
  only when :meth:`Part21.record` asks for it, and a bounded number of parsed
  records are kept.

Values: ``int``, ``float``, ``str`` (the escapes ``''``, ``\\\\``, ``\\S\\``,
``\\P?\\``, ``\\X\\``, ``\\X2\\`` and ``\\X4\\`` decoded; carriage returns and
line feeds inside a string are not part of its value, so a string wrapped across
lines reads whole), :class:`Enum` (``.T.``, ``.MILLI.``), :class:`Ref`
(``#12``), None for ``$``, :data:`DERIVED` for ``*``, :class:`Typed` for a typed
parameter (``LENGTH_MEASURE(1.)``), :class:`Binary` and lists. Comments are
skipped wherever white space may stand.

Every bound comes from :class:`~solidseas.formats.limits.Limits`:
``p21_header_bytes``, ``p21_record_bytes``, ``p21_records``,
``p21_list_items``, ``p21_list_depth``, ``p21_string_bytes`` and
``p21_complex_parts``. Reaching one raises ``SldLimitError`` with
``detail["limit"]`` its name; anything malformed raises ``SldFormatError``
naming the instance. The clock is ticked once an instance, so ``seconds`` and
cancellation hold during the index.

This module is the STEP reader's own, written to the interface the design gives
the shared Part 21 reader (``open``, ``header``, ``schemas``, ``ids_of_type``,
``record``), so that it can move to ``solidseas.formats.part21`` unchanged.
"""

import codecs
import re
from array import array
from bisect import bisect_left
from dataclasses import dataclass
from typing import Any, NamedTuple

from ...errors import SldFormatError
from .._source import Clock
from ..limits import Limits

MAGIC = b"ISO-10303-21;"
RECORD_CACHE = 65_536  # parsed records kept (then the cache starts again)


# --------------------------------------------------------------------------- values
class Ref(int):
    """A reference to an entity instance, ``#n``."""

    __slots__ = ()

    def __repr__(self) -> str:
        return f"#{int(self)}"


class Enum(str):
    """An enumeration value or a logical, ``.NAME.`` (stored without the dots)."""

    __slots__ = ()

    def __repr__(self) -> str:
        return f".{str(self)}."


class _Derived:
    """``*``: a value derived from others, not stored."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "*"


DERIVED = _Derived()


class Typed(NamedTuple):
    """A typed parameter: ``LENGTH_MEASURE(1.)`` is ``Typed("LENGTH_MEASURE", 1.0)``."""

    name: str
    value: Any


class Binary(str):
    """A binary value, its hexadecimal text as stored (the first digit counts unused bits)."""

    __slots__ = ()


def as_bool(v: Any) -> bool | None:
    """A logical or boolean: ``.T.`` True, ``.F.`` False, anything else None."""
    if isinstance(v, Enum):
        if v == "T":
            return True
        if v == "F":
            return False
    return None


@dataclass(frozen=True, slots=True)
class Record:
    """One entity instance: ``types`` its entity name, or a complex instance's names in
    the order stored, and ``parts`` the parameters of each (a list each)."""

    id: int
    types: tuple[str, ...]
    parts: tuple[list, ...]
    complex: bool = False

    @property
    def type(self) -> str:
        return self.types[0]

    @property
    def params(self) -> list:
        """The parameters of a simple instance (a complex one's first record)."""
        return self.parts[0]

    def part(self, name: str) -> list | None:
        """The parameters of the record ``name`` of a complex instance (or of a simple
        instance of that name), or None."""
        for t, p in zip(self.types, self.parts, strict=True):
            if t == name:
                return p
        return None

    def has(self, name: str) -> bool:
        return name in self.types


@dataclass(frozen=True)
class Header:
    """The header section: ``FILE_DESCRIPTION``, ``FILE_NAME`` and ``FILE_SCHEMA``, each
    field None (or empty) when the file leaves it out or stores something else."""

    description: tuple[str, ...] = ()
    implementation_level: str | None = None
    name: str | None = None
    time_stamp: str | None = None
    author: tuple[str, ...] = ()
    organization: tuple[str, ...] = ()
    preprocessor_version: str | None = None
    originating_system: str | None = None
    authorization: str | None = None
    schemas: tuple[str, ...] = ()
    data_offset: int = 0  # where the header section ends


# --------------------------------------------------------------------------- tokens
# One token after any white space and comments. The groups say which kind it is.
_TOKEN = re.compile(
    rb"""(?:\s|/\*.*?\*/)*(?:
      '((?:[^']|'')*)'                                          # 1 string
     |\#(\d+)                                                   # 2 reference
     |([+-]?(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?|[+-]?\d+[eE][+-]?\d+)  # 3 real
     |([+-]?\d+)                                                # 4 integer
     |\.([A-Za-z_][A-Za-z0-9_]*)\.                              # 5 enumeration or logical
     |(!?[A-Za-z_][A-Za-z0-9_]*)                                # 6 keyword
     |"([0-9A-Fa-f]*)"                                          # 7 binary
     |([(),$*;=])                                               # 8 punctuation
    )""",
    re.X | re.S,
)
_SPACE = re.compile(rb"(?:\s|/\*.*?\*/)*", re.S)
_OPEN = re.compile(rb"(?:\s|/\*.*?\*/)*\(", re.S)
# Where an instance's text ends: a semicolon outside strings and comments.
_SCAN = re.compile(rb"'[^']*'|/\*.*?\*/|(;)|(')|(/\*)", re.S)
# The start of an instance: "#id = NAME" or "#id = (" for a complex one; or a keyword.
_HEAD = re.compile(
    rb"(?:\s|/\*.*?\*/)*(?:\#(\d+)\s*=\s*(?:(!?[A-Za-z_][A-Za-z0-9_]*)|(\())|([A-Za-z][A-Za-z0-9_\-]*))",
    re.S,
)
_MAX_ID_DIGITS = 18


def _keyword_text(raw: bytes) -> str:
    return raw.decode("ascii").upper()


# --------------------------------------------------------------------------- strings
_PAGES = {ord(c): f"iso8859-{i}" for i, c in enumerate("ABCDEFGHI", 1)}


def _plain(raw: bytes) -> str:
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        pass
    try:  # Part 21 strings are ASCII, but many writers store UTF-8 or Latin-1 as is
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def decode_string(raw: bytes) -> str:
    """The value of a string's stored text (between its quotes), escapes decoded."""
    if b"\\" not in raw and b"\r" not in raw and b"\n" not in raw:
        s = _plain(raw)
        return s.replace("''", "'") if "''" in s else s
    raw = raw.replace(b"\r", b"").replace(b"\n", b"")
    out: list[str] = []
    page = "iso8859-1"
    i, n = 0, len(raw)
    run = bytearray()

    def flush() -> None:
        if run:
            out.append(_plain(bytes(run)).replace("''", "'"))
            run.clear()

    while i < n:
        c = raw[i]
        if c != 0x5C:  # not a backslash
            run.append(c)
            i += 1
            continue
        if raw.startswith(b"\\\\", i):
            flush()
            out.append("\\")
            i += 2
        elif raw.startswith(b"\\S\\", i) and i + 3 < n:
            flush()
            ch = raw[i + 3]
            out.append(bytes([(ch + 0x80) & 0xFF]).decode(page, "replace"))
            i += 4
            if ch == 0x27 and i < n and raw[i] == 0x27:  # an apostrophe is stored twice
                i += 1
        elif raw.startswith(b"\\P", i) and i + 3 < n and raw[i + 3] == 0x5C and raw[i + 2] in _PAGES:
            flush()
            page = _PAGES[raw[i + 2]]
            i += 4
        elif raw.startswith(b"\\X\\", i) and i + 5 <= n and _is_hex(raw[i + 3 : i + 5]):
            flush()
            out.append(chr(int(raw[i + 3 : i + 5], 16)))
            i += 5
        elif raw.startswith(b"\\X2\\", i) or raw.startswith(b"\\X4\\", i):
            width = 4 if raw[i + 2] == 0x32 else 8
            # The escape's hex digits run up to \X0\. Reading just that run keeps a string
            # of many unclosed escapes linear: no search to the end of the string per escape.
            end = _HEX_RUN.match(raw, i + 4).end()
            body = raw[i + 4 : end]
            if not raw.startswith(b"\\X0\\", end) or not body or len(body) % width:
                run.append(c)  # not a valid escape: kept as stored
                i += 1
                continue
            flush()
            codec = "utf-16-be" if width == 4 else "utf-32-be"
            out.append(bytes.fromhex(body.decode("ascii")).decode(codec, "replace"))
            i = end + 4
        elif raw.startswith(b"\\N\\", i) or raw.startswith(b"\\F\\", i):
            i += 3  # print control directives: not part of the value
        else:
            run.append(c)
            i += 1
    flush()
    return "".join(out)


_HEX_RUN = re.compile(rb"[0-9A-Fa-f]*")


def _is_hex(b: bytes) -> bool:
    return bool(b) and all(ch in b"0123456789abcdefABCDEF" for ch in b)


# --------------------------------------------------------------------------- parameters
class _Parser:
    """Turns the text of one instance or header entry into values (see the module notes)."""

    __slots__ = ("lim", "what")

    def __init__(self, lim: Limits) -> None:
        self.lim = lim
        self.what = ""

    def fail(self, message: str) -> SldFormatError:
        return SldFormatError(f"{self.what}: {message}" if self.what else message)

    def values(self, text: bytes, pos: int, end: int) -> tuple[list, int]:
        """The list that starts after the ``(`` before ``pos``: its values and the position
        after its ``)``."""
        lim = self.lim
        max_items, max_depth, max_string = lim.p21_list_items, lim.p21_list_depth, lim.p21_string_bytes
        root: list = []
        stack: list[list] = [root]
        names: list[str | None] = [None]
        match = _TOKEN.match
        while True:
            m = match(text, pos, end)
            if m is None:
                rest = text[pos:end].strip()
                if not rest:
                    raise self.fail("a list is not closed")
                raise self.fail(f"unexpected text {rest[:12]!r}")
            pos = m.end()
            g = m.lastindex
            cur = stack[-1]
            if g == 6:  # a keyword: a typed parameter, NAME(value)
                o = _OPEN.match(text, pos, end)
                if o is None:
                    raise self.fail("a keyword is not followed by its value")
                pos = o.end()
                if len(stack) >= max_depth:
                    raise lim.exceeded("p21_list_depth", f"{self.what}: lists nest deeper than {max_depth}")
                stack.append([])
                names.append(_keyword_text(m.group(6)))
            elif g == 8:
                p = m.group(8)
                if p == b")":
                    done = stack.pop()
                    name = names.pop()
                    if len(done) > max_items:
                        raise lim.exceeded(
                            "p21_list_items", f"{self.what}: a list of more than {max_items:,} items"
                        )
                    if not stack:
                        return done, pos
                    if name is not None:
                        stack[-1].append(Typed(name, done[0] if len(done) == 1 else done))
                    else:
                        stack[-1].append(done)
                elif p == b",":
                    continue
                elif p == b"(":
                    if len(stack) >= max_depth:
                        raise lim.exceeded(
                            "p21_list_depth", f"{self.what}: lists nest deeper than {max_depth}"
                        )
                    stack.append([])
                    names.append(None)
                elif p == b"$":
                    cur.append(None)
                elif p == b"*":
                    cur.append(DERIVED)
                else:
                    raise self.fail(f"unexpected {p.decode()!r} inside a list")
            elif g == 2:
                digits = m.group(2)
                if len(digits) > _MAX_ID_DIGITS:
                    raise self.fail("an instance id is too long")
                cur.append(Ref(int(digits)))
            elif g == 3:
                cur.append(float(m.group(3)))
            elif g == 4:
                digits = m.group(4)
                if len(digits) > 40:
                    raise self.fail("an integer is too long")
                cur.append(int(digits))
            elif g == 1:
                raw = m.group(1)
                if len(raw) > max_string:
                    raise lim.exceeded(
                        "p21_string_bytes", f"{self.what}: a string longer than {max_string:,} bytes"
                    )
                cur.append(decode_string(raw))
            elif g == 5:
                cur.append(Enum(_keyword_text(m.group(5))))
            elif g == 7:
                cur.append(Binary(m.group(7).decode("ascii")))
            else:  # pragma: no cover - every group is handled above
                raise self.fail("unexpected token")

    def instance(self, text: bytes, rid: int) -> Record:
        """The record of one instance's text, ``#id = ...`` without its semicolon."""
        self.what = f"#{rid}"
        h = _HEAD.match(text)
        if h is None or h.group(1) is None:
            raise self.fail("not an entity instance")
        pos = h.end()
        end = len(text)
        if h.group(2) is not None:
            o = _OPEN.match(text, pos, end)
            if o is None:
                raise self.fail("the entity name is not followed by its parameters")
            vals, pos = self.values(text, o.end(), end)
            self._tail(text, pos, end)
            return Record(rid, (_keyword_text(h.group(2)),), (vals,), False)
        types: list[str] = []
        parts: list[list] = []
        while True:
            m = _TOKEN.match(text, pos, end)
            if m is None:
                raise self.fail("a complex instance is not closed")
            pos = m.end()
            if m.lastindex == 8 and m.group(8) == b")":
                break
            if m.lastindex != 6:
                raise self.fail("a complex instance holds something other than records")
            o = _OPEN.match(text, pos, end)
            if o is None:
                raise self.fail("a record of a complex instance has no parameters")
            vals, pos = self.values(text, o.end(), end)
            types.append(_keyword_text(m.group(6)))
            parts.append(vals)
            if len(types) > self.lim.p21_complex_parts:
                raise self.lim.exceeded(
                    "p21_complex_parts",
                    f"#{rid}: a complex instance of more than {self.lim.p21_complex_parts} records",
                )
        if not types:
            raise self.fail("an empty complex instance")
        self._tail(text, pos, end)
        return Record(rid, tuple(types), tuple(parts), True)

    def _tail(self, text: bytes, pos: int, end: int) -> None:
        s = _SPACE.match(text, pos, end)
        if s is None or s.end() != end:
            raise self.fail("text after the instance's parameters")

    def entry(self, text: bytes) -> tuple[str, list]:
        """A header entry, ``NAME(...)``."""
        self.what = "the header"
        m = _TOKEN.match(text)
        if m is None or m.lastindex != 6:
            raise self.fail("an entry is not NAME(...)")
        o = _OPEN.match(text, m.end())
        if o is None:
            raise self.fail("an entry has no parameters")
        vals, pos = self.values(text, o.end(), len(text))
        self._tail(text, pos, len(text))
        return _keyword_text(m.group(6)), vals


# --------------------------------------------------------------------------- the header
def _start(data: bytes) -> int:
    """Where ``ISO-10303-21;`` ends, after an optional byte order mark and white space."""
    i = 3 if data.startswith(b"\xef\xbb\xbf") else 0
    s = _SPACE.match(data, i)
    i = s.end() if s else i
    if not data.startswith(MAGIC, i):
        raise SldFormatError("the file does not start with ISO-10303-21;")
    return i + len(MAGIC)


def _statements(data: bytes, pos: int, end: int, clock: Clock | None):
    """``(start, end)`` of each statement (text up to a semicolon outside strings and
    comments) from ``pos``; the last one may be cut by ``end`` (then its end is None)."""
    start = pos
    for m in _SCAN.finditer(data, pos, end):
        g = m.lastindex
        if g is None:
            continue
        if g == 1:
            yield start, m.start()
            start = m.end()
            if clock is not None:
                clock.tick()
        elif g == 2:
            if end < len(data):  # the string may go on past what was read
                yield start, None
                return
            raise SldFormatError(f"a string that starts at byte {m.start()} is not closed")
        else:
            if end < len(data):
                yield start, None
                return
            raise SldFormatError(f"a comment that starts at byte {m.start()} is not closed")
    yield start, None


def _strs(v: Any) -> tuple[str, ...]:
    if isinstance(v, list):
        return tuple(x for x in v if isinstance(x, str) and not isinstance(x, Enum))
    if isinstance(v, str) and not isinstance(v, Enum):
        return (v,)
    return ()


def _str(v: Any) -> str | None:
    return v if isinstance(v, str) and not isinstance(v, (Enum, Binary)) else None


def read_header(data: bytes, limits: Limits, *, complete: bool = True) -> Header:
    """The header section of ``data``, which holds at least the file's first
    ``p21_header_bytes`` (or all of it). ``complete`` says ``data`` is the whole file.
    Raises ``SldFormatError`` for a file that is not Part 21, and ``SldLimitError``
    (``p21_header_bytes``) when the header section does not end in time."""
    cap = limits.p21_header_bytes
    pos = _start(data)
    end = min(len(data), pos + cap)
    parser = _Parser(limits)
    entries: dict[str, list] = {}
    seen_header = False
    for start, stop in _statements(data, pos, end, None):
        if stop is None:
            break
        text = data[start:stop].strip()
        if not seen_header:
            if _keyword(text) != "HEADER":
                raise SldFormatError("the file has no HEADER section")
            seen_header = True
            continue
        word = _keyword(text)
        if word == "ENDSEC":
            return _header(entries, stop + 1)
        if not text:
            continue
        name, vals = parser.entry(text)
        entries.setdefault(name, vals)
    if end < len(data) or not complete:
        raise limits.exceeded("p21_header_bytes", f"the header section is longer than {cap:,} bytes")
    raise SldFormatError("the header section does not end (ENDSEC;)")


_WORD = re.compile(rb"(?:\s|/\*.*?\*/)*([A-Za-z][A-Za-z0-9_\-]*)(?:\s|/\*.*?\*/)*\Z", re.S)
_DATA_WITH_PARAMETERS = re.compile(rb"(?:\s|/\*.*?\*/)*DATA\s*\(", re.S | re.I)


def _keyword(text: bytes) -> str:
    """The one keyword a statement is (``HEADER``, ``ENDSEC``...), or ``""``."""
    m = _WORD.match(text)
    return m.group(1).decode("ascii").upper() if m else ""


def _header(entries: dict[str, list], offset: int) -> Header:
    d = entries.get("FILE_DESCRIPTION") or []
    f = entries.get("FILE_NAME") or []
    s = entries.get("FILE_SCHEMA") or []

    def at(vals: list, i: int) -> Any:
        return vals[i] if i < len(vals) else None

    return Header(
        description=_strs(at(d, 0)),
        implementation_level=_str(at(d, 1)),
        name=_str(at(f, 0)),
        time_stamp=_str(at(f, 1)),
        author=_strs(at(f, 2)),
        organization=_strs(at(f, 3)),
        preprocessor_version=_str(at(f, 4)),
        originating_system=_str(at(f, 5)),
        authorization=_str(at(f, 6)),
        schemas=tuple(x.strip().upper() for x in _strs(at(s, 0))),
        data_offset=offset,
    )


# --------------------------------------------------------------------------- the data sections
class Part21:
    """The index of a Part 21 file's data sections (see the module notes). ``data`` is the
    whole file in memory."""

    def __init__(self, data: bytes, limits: Limits, clock: Clock | None = None) -> None:
        self.data = data
        self.limits = limits
        self.header = read_header(data, limits)
        self._parser = _Parser(limits)
        self._names: list[tuple[str, ...]] = []
        self._codes: dict[tuple[str, ...], int] = {}
        self.ids = array("q")
        self.starts = array("q")
        self.ends = array("q")
        self.types = array("I")
        self._by_type: dict[str, list[int]] | None = None
        self._cache: dict[int, Record] = {}
        self._dense = False
        self.sections = 0
        self._index(clock or Clock(limits.seconds))

    @property
    def schemas(self) -> tuple[str, ...]:
        return self.header.schemas

    def __len__(self) -> int:
        return len(self.ids)

    def _code(self, names: tuple[str, ...]) -> int:
        c = self._codes.get(names)
        if c is None:
            c = self._codes[names] = len(self._names)
            self._names.append(names)
        return c

    def _index(self, clock: Clock) -> None:
        data, lim = self.data, self.limits
        ids, starts, ends, types = self.ids, self.starts, self.ends, self.types
        head = _HEAD.match
        code = self._code
        simple: dict[bytes, int] = {}
        max_records, max_bytes = lim.p21_records, lim.p21_record_bytes
        state = "between"  # between sections, in a DATA section, or in another section
        ordered = True
        last = -1
        ended = False
        for start, stop in _statements(data, self.header.data_offset, len(data), clock):
            if stop is None:
                if data[start:].strip():
                    raise SldFormatError("the file ends inside an entity instance or a section")
                break
            if state == "data":
                h = head(data, start, stop)
                if h is None:
                    raise SldFormatError(f"the text at byte {start} is not an entity instance")
                if h.group(4) is not None:
                    if _keyword(data[start:stop]) != "ENDSEC":
                        raise SldFormatError(f"the text at byte {start} is not an entity instance")
                    state = "between"
                    continue
                if stop - start > max_bytes:
                    raise lim.exceeded(
                        "p21_record_bytes",
                        f"#{h.group(1).decode()}: an instance longer than {max_bytes:,} bytes",
                    )
                digits = h.group(1)
                if len(digits) > _MAX_ID_DIGITS:
                    raise SldFormatError("an instance id is too long")
                rid = int(digits)
                if h.group(2) is not None:
                    raw = h.group(2)
                    c = simple.get(raw)
                    if c is None:
                        c = simple[raw] = code((_keyword_text(raw),))
                else:
                    rec = self._parser.instance(data[start:stop], rid)
                    c = code(rec.types)
                if len(ids) >= max_records:
                    raise lim.exceeded("p21_records", f"the file holds more than {max_records:,} instances")
                if rid <= last:
                    ordered = False
                last = rid
                ids.append(rid)
                starts.append(start)
                ends.append(stop)
                types.append(c)
                continue
            word = _keyword(data[start:stop])
            if state == "skip":
                if word == "ENDSEC":
                    state = "between"
                continue
            # between sections
            if word == "END-ISO-10303-21":
                ended = True
                break
            text = data[start:stop].strip()
            if word == "DATA" or _DATA_WITH_PARAMETERS.match(text):
                state = "data"
                self.sections += 1
            elif word in ("ANCHOR", "REFERENCE", "SIGNATURE"):
                state = "skip"
            elif not text:
                continue
            else:
                raise SldFormatError(f"unexpected text at byte {start} between sections")
        if state != "between" or not ended:
            raise SldFormatError("the file does not end with END-ISO-10303-21;")
        if not ordered:
            self._sort()
        n = len(ids)
        self._dense = n > 0 and ids[-1] - ids[0] == n - 1

    def _sort(self) -> None:
        order = sorted(range(len(self.ids)), key=self.ids.__getitem__)
        for name in ("ids", "starts", "ends"):
            old = getattr(self, name)
            setattr(self, name, array("q", (old[i] for i in order)))
        self.types = array("I", (self.types[i] for i in order))
        ids = self.ids
        for i in range(1, len(ids)):
            if ids[i] == ids[i - 1]:
                raise SldFormatError(f"instance #{ids[i]} is defined twice")

    # lookups ---------------------------------------------------------------------------
    def _find(self, rid: int) -> int:
        ids = self.ids
        if self._dense:
            i = rid - ids[0]
            if 0 <= i < len(ids):
                return i
            return -1
        i = bisect_left(ids, rid)
        return i if i < len(ids) and ids[i] == rid else -1

    def __contains__(self, rid: int) -> bool:
        return self._find(rid) >= 0

    def type_of(self, rid: int) -> tuple[str, ...] | None:
        """The entity name(s) of instance ``rid``, or None when there is none."""
        i = self._find(rid)
        return None if i < 0 else self._names[self.types[i]]

    def is_a(self, rid: int, *names: str) -> bool:
        t = self.type_of(rid)
        return t is not None and any(n in t for n in names)

    def ids_of_type(self, name: str) -> list[int]:
        """The ids of every instance of entity ``name`` (simple, or one record of a complex
        instance), in id order."""
        if self._by_type is None:
            groups: dict[int, list[int]] = {}
            ids = self.ids
            for i, c in enumerate(self.types):
                groups.setdefault(c, []).append(ids[i])
            by: dict[str, list[int]] = {}
            for c, members in groups.items():
                for nm in self._names[c]:
                    by.setdefault(nm, []).extend(members)
            for members in by.values():
                members.sort()
            self._by_type = by
        return self._by_type.get(name, [])

    def count(self, name: str) -> int:
        return len(self.ids_of_type(name))

    def names(self) -> dict[str, int]:
        """How many instances there are of each entity name."""
        if self._by_type is None:
            self.ids_of_type("")
        return {k: len(v) for k, v in (self._by_type or {}).items()}

    def record(self, rid: int) -> Record:
        """The parsed record of instance ``rid``; ``SldFormatError`` when there is none."""
        got = self._cache.get(rid)
        if got is not None:
            return got
        i = self._find(rid)
        if i < 0:
            raise SldFormatError(f"#{rid} is referred to but not defined")
        rec = self._parser.instance(self.data[self.starts[i] : self.ends[i]], rid)
        if len(self._cache) >= RECORD_CACHE:
            self._cache.clear()
        self._cache[rid] = rec
        return rec

    def get(self, rid: Any) -> Record | None:
        """The record ``rid`` refers to, or None for anything that is not a reference to a
        defined instance."""
        if not isinstance(rid, Ref):
            return None
        i = self._find(rid)
        if i < 0:
            return None
        return self.record(int(rid))


def open(source: Any, *, limits: Limits, clock: Clock | None = None) -> Part21:
    """Index a Part 21 file: ``source`` is its bytes, or a
    :class:`~solidseas.formats._source.Source` (read whole, within ``whole_read_bytes``)."""
    if not isinstance(source, (bytes, bytearray, memoryview)):
        source = source.read_all(limits.whole_read_bytes, "whole_read_bytes")
    return Part21(bytes(source), limits, clock)


def text_codec_ok() -> bool:  # pragma: no cover - a guard for unusual Python builds
    return all(codecs.lookup(p) for p in _PAGES.values())


__all__ = [
    "DERIVED",
    "MAGIC",
    "Binary",
    "Enum",
    "Header",
    "Part21",
    "Record",
    "Ref",
    "Typed",
    "as_bool",
    "decode_string",
    "open",
    "read_header",
]
