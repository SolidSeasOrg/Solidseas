"""A small ISO 10303-21 reader for the design database in ``STEP_DATA``.

Interim: the design's shared Part 21 reader (``solidseas.formats.part21``) replaces
this module when it lands. It reads what an Alibre design database needs, within
the ``p21_*`` bounds: the header's schema names, and the data section's records
by id, parsed on demand.

:class:`Part21` first indexes the data section: every ``#id = TYPE(...);`` (or a
complex ``#id = (A(...) B(...));``) with its type and the span of its
parameters, quote-aware and skipping comments. :meth:`Part21.record` parses one
record's parameters into Python values: int, float, str (escapes ``''``, ``\\\\``,
``\\X\\hh``, ``\\X2\\...\\X0\\``, ``\\X4\\...\\X0\\``, ``\\S\\c`` decoded, ``\\P?\\``
dropped; a line break inside a string is not part of it), :class:`Enum`,
:class:`Ref`, None for ``$``, :data:`DERIVED` for ``*``, :class:`Typed` and lists.
"""

import re
from dataclasses import dataclass
from typing import Any

from ...errors import SldFormatError
from .._source import Clock
from ..limits import Limits


@dataclass(frozen=True)
class Ref:
    id: int


@dataclass(frozen=True)
class Enum:
    name: str


@dataclass(frozen=True)
class Typed:
    type: str
    params: tuple


class _Derived:
    def __repr__(self) -> str:
        return "DERIVED"


DERIVED = _Derived()
_NAME = re.compile(rb"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(rb"[+-]?(?:\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)")
_ID = re.compile(rb"#(\d+)\s*=\s*")
_REF = re.compile(rb"#(\d+)")


def _bad(msg: str) -> SldFormatError:
    return SldFormatError(msg, detail={"stream": "STEP_DATA"})


class Part21:
    """One Part 21 text (see the module notes)."""

    def __init__(self, data: bytes, limits: Limits, clock: Clock | None = None) -> None:
        self.data = data
        self.limits = limits
        self.clock = clock
        head_end = data.find(b"ENDSEC")
        start = data.find(b"DATA;", head_end if head_end >= 0 else 0)
        if head_end < 0 or start < 0:
            raise _bad("the design database has no data section")
        if head_end > limits.p21_header_bytes:
            raise limits.exceeded("p21_header_bytes", "the design database's header is too long")
        self.header_text = data[:start]
        self.index: dict[int, tuple[str, int, int]] = {}  # id -> (type, start, end of params)
        self._by_type: dict[str, list[int]] = {}
        self._parsed: dict[int, tuple[str, tuple]] = {}
        self._scan(start + 5)

    # -- index ----------------------------------------------------------------------------
    def _skip(self, i: int) -> int:
        """Past white space and comments."""
        d, n = self.data, len(self.data)
        while i < n:
            c = d[i]
            if c in b" \t\r\n":
                i += 1
            elif d.startswith(b"/*", i):
                j = d.find(b"*/", i + 2)
                if j < 0:
                    raise _bad("a comment never ends")
                i = j + 2
            else:
                break
        return i

    def _end_of_record(self, i: int) -> int:
        """The index of the ``;`` that ends the record whose text starts at ``i``."""
        d, n = self.data, len(self.data)
        lim = self.limits.p21_record_bytes
        start = i
        while i < n:
            c = d[i]
            if c == 0x27:  # a string: '' is a quote inside it
                j = i + 1
                while True:
                    j = d.find(b"'", j)
                    if j < 0:
                        raise _bad("a string never ends")
                    if j + 1 < n and d[j + 1] == 0x27:
                        j += 2
                        continue
                    break
                i = j + 1
            elif c == 0x2F and i + 1 < n and d[i + 1] == 0x2A:
                j = d.find(b"*/", i + 2)
                if j < 0:
                    raise _bad("a comment never ends")
                i = j + 2
            elif c == 0x3B:
                return i
            else:
                i += 1
            if i - start > lim:
                raise self.limits.exceeded("p21_record_bytes", f"a record is longer than {lim:,} bytes")
        raise _bad("a record never ends")

    def _scan(self, i: int) -> None:
        d, n = self.data, len(self.data)
        while True:
            if self.clock is not None:
                self.clock.tick()
            i = self._skip(i)
            if i >= n:
                raise _bad("the data section never ends")
            if d.startswith(b"ENDSEC", i):
                return
            m = _ID.match(d, i)
            if m is None:
                raise _bad("a record does not start with its #id")
            rid = int(m.group(1))
            j = m.end()
            end = self._end_of_record(j)
            if len(self.index) >= self.limits.p21_records:
                raise self.limits.exceeded("p21_records", f"more than {self.limits.p21_records:,} records")
            body = d[j:end].rstrip()
            t = _NAME.match(body)
            if t is not None:
                name = t.group(0).decode("ascii").upper()
            elif body.startswith(b"("):
                name = ""  # a complex instance: parsed when asked for
            else:
                raise _bad("a record has no type")
            if rid in self.index:
                raise _bad("two records share an id")
            self.index[rid] = (name, j, j + len(body))
            self._by_type.setdefault(name, []).append(rid)
            i = end + 1

    # -- queries --------------------------------------------------------------------------
    @property
    def schemas(self) -> list[str]:
        m = re.search(rb"FILE_SCHEMA\s*\(\s*\(([^)]*)\)", self.header_text, re.S)
        if m is None:
            return []
        return [s.decode("latin-1").upper() for s in re.findall(rb"'((?:[^']|'')*)'", m.group(1))]

    def ids_of_type(self, name: str) -> list[int]:
        return list(self._by_type.get(name.upper(), ()))

    def type_of(self, rid: int) -> str | None:
        hit = self.index.get(rid)
        return hit[0] if hit else None

    def record(self, rid: int) -> tuple[str, tuple]:
        """``(type, parameters)`` of record ``rid``; a complex instance's type is ``""``
        and its parameters its parts as :class:`Typed` values."""
        hit = self._parsed.get(rid)
        if hit is not None:
            return hit
        got = self.index.get(rid)
        if got is None:
            raise _bad("a reference names a record that does not exist")
        name, start, end = got
        p = _Parser(self.data, start, end, self.limits)
        if name:
            p.i += len(name)
            p.skip()
            params = p.list_()
        else:
            p.expect(b"(")
            parts = []
            while True:
                p.skip()
                if p.peek() == b")":
                    p.i += 1
                    break
                tname = p.name()
                p.skip()
                parts.append(Typed(tname, p.list_()))
                if len(parts) > self.limits.p21_complex_parts:
                    raise self.limits.exceeded("p21_complex_parts", "a complex instance has too many parts")
            params = tuple(parts)
        p.skip()
        if p.i != end:
            raise _bad("a record has text after its parameters")
        out = (name, params)
        if len(self._parsed) < 100_000:
            self._parsed[rid] = out
        return out


class _Parser:
    def __init__(self, data: bytes, i: int, end: int, limits: Limits) -> None:
        self.d, self.i, self.end, self.limits = data, i, end, limits
        self.depth = 0

    def skip(self) -> None:
        d, i, end = self.d, self.i, self.end
        while i < end:
            c = d[i]
            if c in b" \t\r\n":
                i += 1
            elif d.startswith(b"/*", i):
                j = d.find(b"*/", i + 2, end)
                if j < 0:
                    raise _bad("a comment never ends")
                i = j + 2
            else:
                break
        self.i = i

    def peek(self) -> bytes:
        return self.d[self.i : self.i + 1] if self.i < self.end else b""

    def expect(self, ch: bytes) -> None:
        self.skip()
        if self.peek() != ch:
            raise _bad(f"expected {ch.decode()!r} in a record")
        self.i += 1

    def name(self) -> str:
        m = _NAME.match(self.d, self.i, self.end)
        if m is None:
            raise _bad("expected a name in a record")
        self.i = m.end()
        return m.group(0).decode("ascii").upper()

    def list_(self) -> tuple:
        self.depth += 1
        if self.depth > self.limits.p21_list_depth:
            raise self.limits.exceeded("p21_list_depth", "lists nest too deeply")
        self.expect(b"(")
        out: list[Any] = []
        self.skip()
        if self.peek() == b")":
            self.i += 1
            self.depth -= 1
            return ()
        while True:
            out.append(self.value())
            if len(out) > self.limits.p21_list_items:
                raise self.limits.exceeded("p21_list_items", "a list has too many items")
            self.skip()
            c = self.peek()
            self.i += 1
            if c == b")":
                break
            if c != b",":
                raise _bad("a list's items are not separated by commas")
        self.depth -= 1
        return tuple(out)

    def value(self) -> Any:
        self.skip()
        d, i = self.d, self.i
        c = self.peek()
        if c == b"$":
            self.i += 1
            return None
        if c == b"*":
            self.i += 1
            return DERIVED
        if c == b"#":
            m = _REF.match(d, i, self.end)
            if m is None:
                raise _bad("a reference is not #digits")
            self.i = m.end()
            return Ref(int(m.group(1)))
        if c == b"'":
            return self.string()
        if c == b".":
            j = d.find(b".", i + 1, self.end)
            if j < 0:
                raise _bad("an enumeration never ends")
            self.i = j + 1
            return Enum(d[i + 1 : j].decode("ascii", "replace").upper())
        if c == b"(":
            return self.list_()
        if c == b'"':
            j = d.find(b'"', i + 1, self.end)
            if j < 0:
                raise _bad("a binary value never ends")
            self.i = j + 1
            return d[i + 1 : j].decode("ascii", "replace")
        m = _NUMBER.match(d, i, self.end)
        if m is not None and m.end() > i:
            text = m.group(0)
            self.i = m.end()
            if b"." in text or b"e" in text or b"E" in text:
                return float(text)
            return int(text)
        if _NAME.match(d, i, self.end):
            tname = self.name()
            self.skip()
            return Typed(tname, self.list_())
        raise _bad("a value of a record is not one Part 21 knows")

    def string(self) -> str:
        d, n = self.d, self.end
        j = self.i + 1
        parts = []
        while True:
            k = d.find(b"'", j, n)
            if k < 0:
                raise _bad("a string never ends")
            parts.append(d[j:k])
            if k + 1 < n and d[k + 1] == 0x27:
                parts.append(b"'")
                j = k + 2
                continue
            self.i = k + 1
            break
        raw = b"".join(parts).replace(b"\r", b"").replace(b"\n", b"")
        if len(raw) > self.limits.p21_string_bytes:
            raise self.limits.exceeded("p21_string_bytes", "a string is too long")
        return decode_string(raw)


_ESC = re.compile(
    rb"\\X2\\((?:[0-9A-Fa-f]{4})*)\\X0\\|\\X4\\((?:[0-9A-Fa-f]{8})*)\\X0\\|\\X\\([0-9A-Fa-f]{2})|\\S\\(.)|\\P[A-I]\\|\\\\",
    re.S,
)


def decode_string(raw: bytes) -> str:
    """A Part 21 string's text (the escapes of the module notes decoded; other bytes
    as ISO 8859-1)."""

    def sub(m: re.Match) -> str:
        if m.group(1) is not None:
            h = m.group(1).decode()
            return (
                "".join(chr(int(h[k : k + 4], 16)) for k in range(0, len(h), 4))
                .encode("utf-16", "surrogatepass")
                .decode("utf-16", "replace")
            )
        if m.group(2) is not None:
            h = m.group(2).decode()
            out = []
            for k in range(0, len(h), 8):
                cp = int(h[k : k + 8], 16)
                out.append(chr(cp) if cp <= 0x10FFFF else "\ufffd")
            return "".join(out)
        if m.group(3) is not None:
            return chr(int(m.group(3), 16))
        if m.group(4) is not None:
            return chr(m.group(4)[0] + 128)
        if m.group(0) == b"\\\\":
            return "\\"
        return ""

    out = []
    pos = 0
    for m in _ESC.finditer(raw):
        out.append(raw[pos : m.start()].decode("latin-1"))
        out.append(sub(m))
        pos = m.end()
    out.append(raw[pos:].decode("latin-1"))
    return "".join(out)


__all__ = ["DERIVED", "Enum", "Part21", "Ref", "Typed", "decode_string"]
