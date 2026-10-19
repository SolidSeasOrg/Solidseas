"""The Parasolid B-rep embedded in SOLIDWORKS documents.

Where it lives (``docs/FORMAT.md`` has the evidence):

* ``Contents/Config-<n>-Partition`` (same name in both container generations)
  is a ZLB chain. Block 0 is a Parasolid neutral-binary transmit
  ``TRANSMIT FILE (partition)`` whose root node is WORLD; block 1 is
  ``TRANSMIT FILE (deltas)``. The partition alone holds the configuration's
  bodies as saved; the deltas are not needed to rebuild them.
* When a partition holds no bodies (mostly imported geometry), the bodies are
  ready-made part transmits in ``Config-<n>-FeatureBodies/LocalBodies``
  (:mod:`.localbodies`).

This module reads and writes the neutral-binary and text transmit formats of
the publicly published Parasolid XT Format Reference, copies each BODY of a
partition into a standalone part transmit (root BODY at index 1, as the
reference prescribes for part files) and checks the result structurally.
Whether the written files load in a Parasolid kernel has not been tested.

Base node layouts: :mod:`.xt_schema` (from sldprt2step, Apache-2.0). The
binary reader follows the structure of sldprt2step's reader and keeps the raw
schema information so that files can be written back out.
"""

import functools
import math
import os
import re
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import xt_schema as S
from .container import Container
from .errors import ParasolidError, SldError, SldLimitError
from .localbodies import iter_local_body_blocks
from .zlb import iter_chain_blocks, peek_zlb, unwrap_zlb

VAR = S.VAR
NULL_INT = -32764
NULL_DOUBLE = -3.14158e13
MAX_NODES = 20_000_000
DEFAULT_MAX_TRANSMIT_BYTES = 64 << 20  # parsing costs about 6x this in memory
TYPE_WORLD, TYPE_BODY, TYPE_ATTRIB_DEF, TYPE_ATTRIBUTE = 101, 12, 80, 81
BODY_TYPES = {1: "solid", 2: "wire", 3: "sheet", 6: "general"}

# Node types flagged "identical to base" in real files but absent from the base table.
# HYPOTHESIS: layout inferred from data only. Type 150 occurs once in each of 4 corpus
# partitions, always referenced by SURFACE_DATA.analytic_form; a 48-byte body (point plus
# unit vector) makes all 4 parse to the terminator and validate. 41 bytes also parses.
INFERRED_BASE = {150: [("inferred_point", "v", 1), ("inferred_direction", "v", 1)]}


# --------------------------------------------------------------------------- data model
class FieldDef:
    """A field definition as transmitted inside embedded schema information."""

    __slots__ = ("name", "ptr_class", "n_elts", "type", "xmt_code")

    def __init__(self, name: str, ptr_class: int, n_elts: int, type_: str, xmt_code: int | None):
        self.name, self.ptr_class, self.n_elts, self.type, self.xmt_code = (
            name,
            ptr_class,
            n_elts,
            type_,
            xmt_code,
        )

    def layout(self) -> tuple[str, str, int]:
        kind = "p" if self.ptr_class else (self.type[-1] if self.type else "d")
        n = VAR if self.n_elts == 1 else (1 if self.n_elts == 0 else self.n_elts)
        return (self.name, kind, n)


class SchemaInfo:
    """Embedded schema information carried by the first node of a type."""

    __slots__ = ("mode", "nfields", "ops", "name", "desc", "defs")

    def __init__(self, mode: str, nfields: int = 0, ops=None, name: str = "", desc: str = "", defs=None):
        self.mode = mode  # "base", "edit" or "full"
        self.nfields = nfields
        self.ops = ops or []  # [(op_char, FieldDef | None)]
        self.name, self.desc = name, desc
        self.defs = defs or []


class Node:
    __slots__ = ("type", "index", "vals", "count")

    def __init__(self, ntype: int, index: int, vals: list, count: int | None):
        self.type, self.index, self.vals, self.count = ntype, index, vals, count

    @property
    def tname(self) -> str:
        return S.NODE_NAMES.get(self.type, f"TYPE_{self.type}")


class XtTransmit:
    """A parsed transmit: header fields, node layouts, schema information and nodes."""

    def __init__(self) -> None:
        self.flag = b"PS\x00\x00"
        self.modeller = ""
        self.schema = ""
        self.base: int | None = None
        self.max_types: int | None = None
        self.usfld = 0
        self.nodes: list[Node] = []
        self.layouts: dict[int, list[tuple[str, str, int]]] = {}
        self.schema_info: dict[int, SchemaInfo] = {}
        self.trailing = 0
        self._by_index: dict[int, Node] | None = None
        self._hidden: dict[int, bool | None] | None = None  # hidden_bodies, worked out once

    @property
    def inferred_types(self) -> list[int]:
        """Node types whose layout came from INFERRED_BASE (hypothesis, not documentation)."""
        return sorted(t for t, i in self.schema_info.items() if i.desc == "INFERRED")

    @property
    def kind(self) -> str:
        if "(deltas)" in self.modeller:
            return "deltas"
        if "(partition)" in self.modeller:
            return "partition"
        return "part"

    @property
    def modeller_version(self) -> int:
        tail = self.modeller.rsplit(" ", 1)[-1]
        return int(tail) if tail.isdigit() else 0

    def by_index(self) -> dict[int, Node]:
        if self._by_index is None:
            self._by_index = {n.index: n for n in self.nodes}
        return self._by_index

    def field_names(self, ntype: int) -> list[str]:
        return [f[0] for f in self.layouts[ntype]]

    def get(self, node: Node, name: str):
        # An embedded schema may legally drop a field, so a missing one is a
        # format problem with this file, not a programming error.
        try:
            return node.vals[self.field_names(node.type).index(name)]
        except (ValueError, IndexError, KeyError):
            raise ParasolidError(f"{node.tname} has no field {name!r} in this file's schema") from None

    def census(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for n in self.nodes:
            out[n.tname] = out.get(n.tname, 0) + 1
        return out


# --------------------------------------------------------------------------- binary reader
def _as_parasolid_error(fn):
    """Report a malformed transmit as ParasolidError, never as an IndexError or struct.error."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except SldError:
            raise
        except (IndexError, ValueError, KeyError, struct.error, UnicodeDecodeError) as exc:
            raise ParasolidError(f"malformed transmit: {exc!r}") from None

    return wrapper


class _R:
    __slots__ = ("b", "p", "n")

    def __init__(self, b: bytes):
        self.b, self.p, self.n = b, 0, len(b)

    def need(self, k: int) -> None:
        if self.p + k > self.n:
            raise ParasolidError(f"truncated at offset {self.p} (need {k} bytes)")

    def u8(self) -> int:
        self.need(1)
        v = self.b[self.p]
        self.p += 1
        return v

    def i16(self) -> int:
        self.need(2)
        v = struct.unpack_from(">h", self.b, self.p)[0]
        self.p += 2
        return v

    def u16(self) -> int:
        self.need(2)
        v = struct.unpack_from(">H", self.b, self.p)[0]
        self.p += 2
        return v

    def i32(self) -> int:
        self.need(4)
        v = struct.unpack_from(">i", self.b, self.p)[0]
        self.p += 4
        return v

    def fs(self, k: int) -> tuple[float, ...]:
        self.need(8 * k)
        v = struct.unpack_from(f">{k}d", self.b, self.p)
        self.p += 8 * k
        return v

    def raw(self, k: int) -> bytes:
        self.need(k)
        v = self.b[self.p : self.p + k]
        self.p += k
        return v

    def index(self) -> int:
        r = self.i16()
        q = 0
        if r < 0:
            q = self.i16()
            r = -r
            if q <= 0:
                raise ParasolidError(f"bad big index at offset {self.p - 4}")
        return q * 32767 + r - 1

    def sstr(self) -> str:
        return self.raw(self.u8()).decode("latin-1")


def _read_fielddef(r: _R) -> FieldDef:
    name = r.sstr()
    ptr_class = r.u16()
    n_elts = r.index()
    type_ = "" if ptr_class else r.sstr()
    xmt = r.u8() if n_elts == 1 else None
    return FieldDef(name, ptr_class, n_elts, type_, xmt)


_OPS = frozenset(b"CDIAZ")


def _base_info(ntype: int, tname: str) -> tuple[SchemaInfo, list[tuple[str, str, int]]]:
    base = S.BASE.get(ntype)
    if base is not None:
        return SchemaInfo("base"), [tuple(f[:3]) for f in base]
    if ntype in INFERRED_BASE:
        return SchemaInfo("base", desc="INFERRED"), list(INFERRED_BASE[ntype])
    raise ParasolidError(
        f"node type {ntype} ({tname}) is flagged identical to the base schema, "
        "but its base layout is not known"
    )


def _read_schema_info(r: _R, ntype: int) -> tuple[SchemaInfo, list[tuple[str, str, int]]]:
    first = r.u8()
    base = S.BASE.get(ntype)
    tname = S.NODE_NAMES.get(ntype, f"TYPE_{ntype}")
    if first == 0xFF:
        return _base_info(ntype, tname)
    r.need(1)
    if base is not None and r.b[r.p] in _OPS:
        ops, out, bi = [], [], 0
        while True:
            op = chr(r.u8())
            if op == "Z":
                ops.append(("Z", None))
                break
            if op == "C":
                if bi >= len(base):
                    raise ParasolidError(f"{tname}: edit script copies past the base layout")
                out.append(tuple(base[bi][:3]))
                bi += 1
                ops.append(("C", None))
            elif op == "D":
                if bi >= len(base):
                    raise ParasolidError(f"{tname}: edit script deletes past the base layout")
                bi += 1
                ops.append(("D", None))
            elif op in "IA":
                fd = _read_fielddef(r)
                out.append(fd.layout())
                ops.append((op, fd))
            else:
                raise ParasolidError(f"{tname}: bad edit op 0x{ord(op):02x} at offset {r.p - 1}")
        if len(out) != first:
            raise ParasolidError(f"{tname}: edit script yields {len(out)} fields, header says {first}")
        return SchemaInfo("edit", first, ops), out
    if base is not None:
        raise ParasolidError(f"{tname}: schema info is neither 0xff nor an edit script")
    name = r.sstr()
    desc = r.sstr()
    defs = [_read_fielddef(r) for _ in range(first)]
    return SchemaInfo("full", first, name=name, desc=desc, defs=defs), [d.layout() for d in defs]


def _read_val(r: _R, kind: str, k: int):
    """``k`` is the element count (1 for scalars)."""
    if kind == "p":
        return [r.index() for _ in range(k)]
    if kind in "dt":
        return list(struct.unpack_from(f">{k}i", r.raw(4 * k))) if k else []
    if kind == "f":
        return list(r.fs(k))
    if kind in "vh":
        return [r.fs(3) for _ in range(k)]
    if kind == "i":
        return [r.fs(2) for _ in range(k)]
    if kind == "b":
        return [r.fs(6) for _ in range(k)]
    if kind in "ul":
        return list(r.raw(k))
    if kind == "c":
        return r.raw(k).decode("latin-1")
    if kind == "n":
        return list(struct.unpack_from(f">{k}h", r.raw(2 * k))) if k else []
    if kind == "w":
        return list(struct.unpack_from(f">{k}H", r.raw(2 * k))) if k else []
    raise ParasolidError(f"unknown field kind {kind!r}")


def _read_header(r: _R, xt: XtTransmit, *, require_base: bool = True) -> None:
    if r.raw(4) != b"PS\x00\x00":
        raise ParasolidError("no neutral-binary flag 'PS\\0\\0'")
    ml = r.i16()
    if not 0 < ml < 1024:
        raise ParasolidError(f"bad modeller-version length {ml}")
    xt.modeller = r.raw(ml).decode("latin-1")
    sl = r.i32()
    if not 0 < sl < 1024:
        raise ParasolidError(f"bad schema length {sl}")
    xt.schema = r.raw(sl).decode("latin-1")
    parts = xt.schema.split("_")
    if len(parts) >= 4 and parts[0] == "SCH":
        xt.base = int(parts[3]) if parts[3].isdigit() else None
        xt.max_types = r.i16()
    if require_base and xt.base != 13006:
        raise ParasolidError(
            f"transmit schema {xt.schema} has no SCH_13006 base: its layouts need the non-public schema file"
        )
    xt.usfld = r.i32()


def read_header(buf: bytes) -> XtTransmit:
    """Parse only the header of a neutral-binary transmit (no nodes, any schema)."""
    xt = XtTransmit()
    _read_header(_R(buf), xt, require_base=False)
    return xt


@_as_parasolid_error
def parse_binary(
    buf: bytes, *, max_nodes: int = MAX_NODES, tick: Callable[[], None] | None = None
) -> XtTransmit:
    """Parse one neutral-binary transmit (a part or a partition; deltas are not supported).
    ``tick``, when given, is called once a node and may raise to stop the parse (a
    deadline or a cancellation)."""
    r = _R(buf)
    xt = XtTransmit()
    _read_header(r, xt)
    if xt.usfld != 0:
        raise ParasolidError(f"user fields (USFLD_SIZE={xt.usfld}) are not supported")
    seen = set()
    while True:
        ntype = r.u16()
        if ntype == 1:
            if r.u16() != 1:
                raise ParasolidError(f"bad terminator at offset {r.p - 2}")
            break
        lay = xt.layouts.get(ntype)
        if lay is None:
            info, lay = _read_schema_info(r, ntype)
            xt.layouts[ntype] = lay
            xt.schema_info[ntype] = info
        count = None
        if any(f[2] == VAR for f in lay):
            count = r.i32()
            if count < 0 or count > len(buf):
                raise ParasolidError(f"bad variable length {count} at offset {r.p - 4}")
        idx = r.index()
        if idx in seen:
            raise ParasolidError(f"duplicate node index {idx}")
        seen.add(idx)
        vals = []
        try:
            for _name, kind, n in lay:
                v = _read_val(r, kind, count if n == VAR else n)
                if n == 1 and kind != "c":
                    v = v[0]
                vals.append(v)
        except ParasolidError as exc:
            raise ParasolidError(f"in {S.NODE_NAMES.get(ntype, ntype)} #{idx}: {exc}") from exc
        xt.nodes.append(Node(ntype, idx, vals, count))
        if len(xt.nodes) > max_nodes:
            raise SldLimitError(f"more than {max_nodes} nodes")
        if tick is not None:
            tick()
    xt.trailing = r.n - r.p
    return xt


# --------------------------------------------------------------------------- binary writer
def _w_index(out: bytearray, idx: int) -> None:
    if idx < 0:
        raise ParasolidError(f"negative index {idx}")
    if idx < 32767:
        out += struct.pack(">h", idx + 1)
    else:
        q, rem = divmod(idx, 32767)
        if q > 32767:
            raise ParasolidError(f"index {idx} too large")
        out += struct.pack(">hh", -(rem + 1), q)


def _w_sstr(out: bytearray, s: str) -> None:
    b = s.encode("latin-1")
    if len(b) > 255:
        raise ParasolidError("short string too long")
    out.append(len(b))
    out += b


def _w_fielddef(out: bytearray, fd: FieldDef) -> None:
    _w_sstr(out, fd.name)
    out += struct.pack(">H", fd.ptr_class)
    _w_index(out, fd.n_elts)
    if not fd.ptr_class:
        _w_sstr(out, fd.type)
    if fd.n_elts == 1:
        out.append(fd.xmt_code)


def _w_schema_info(out: bytearray, info: SchemaInfo) -> None:
    if info.mode == "base":
        out.append(0xFF)
        return
    out.append(info.nfields)
    if info.mode == "edit":
        for op, fd in info.ops:
            out.append(ord(op))
            if fd is not None:
                _w_fielddef(out, fd)
        return
    _w_sstr(out, info.name)
    _w_sstr(out, info.desc)
    for fd in info.defs:
        _w_fielddef(out, fd)


def _w_val(out: bytearray, kind: str, n: int, v) -> None:
    seq = v if (n != 1 or kind == "c") else [v]
    if kind == "p":
        for x in seq:
            _w_index(out, x)
    elif kind in "dt":
        out += struct.pack(f">{len(seq)}i", *seq)
    elif kind == "f":
        out += struct.pack(f">{len(seq)}d", *seq)
    elif kind in "vhib":
        for t in seq:
            out += struct.pack(f">{len(t)}d", *t)
    elif kind in "ul":
        out += bytes(seq)
    elif kind == "c":
        out += seq.encode("latin-1")
    elif kind == "n":
        out += struct.pack(f">{len(seq)}h", *seq)
    elif kind == "w":
        out += struct.pack(f">{len(seq)}H", *seq)
    else:
        raise ParasolidError(f"unknown kind {kind!r}")


def write_binary(xt: XtTransmit) -> bytes:
    """Serialise to neutral binary (without the text header)."""
    out = bytearray(b"PS\x00\x00")
    m = xt.modeller.encode("latin-1")
    out += struct.pack(">h", len(m)) + m
    s = xt.schema.encode("latin-1")
    out += struct.pack(">i", len(s)) + s
    if xt.base is not None:
        out += struct.pack(">h", xt.max_types)
    out += struct.pack(">i", xt.usfld)
    done = set()
    for nd in xt.nodes:
        out += struct.pack(">H", nd.type)
        lay = xt.layouts[nd.type]
        if nd.type not in done:
            _w_schema_info(out, xt.schema_info[nd.type])
            done.add(nd.type)
        if any(f[2] == VAR for f in lay):
            out += struct.pack(">i", nd.count)
        _w_index(out, nd.index)
        for (_name, kind, n), v in zip(lay, nd.vals, strict=True):
            _w_val(out, kind, n, v)
    out += b"\x00\x01\x00\x01"
    return bytes(out)


# --------------------------------------------------------------------------- text writer
def fmt_double(x: float) -> str:
    """Parasolid-style number text: 15 significant digits, no leading zero, short exponent.

    Matches SOLIDWORKS' own text export of the synthetic box token for token."""
    if x == NULL_DOUBLE:
        return "?"
    if x == 0:
        return "-0" if math.copysign(1.0, x) < 0 else "0"
    s = f"{x:.15g}"
    if "e" in s:
        mant, exp = s.split("e")
        s = f"{mant}e{int(exp)}"
    neg = s.startswith("-")
    body = s[1:] if neg else s
    if body.startswith("0."):
        body = body[1:]
    # integral values with trailing zeros are written in exponent form when shorter (1000 -> 1e3)
    if "." not in body and "e" not in body and body.endswith("0"):
        digits = body.rstrip("0")
        alt = f"{digits}e{len(body) - len(digits)}"
        if len(alt) < len(body):
            body = alt
    return ("-" if neg else "") + body


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("\0", "\\0").replace("\r", "\\n").replace("\n", "\\r")


class _T:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def num(self, v: int) -> None:
        self.parts.append("?" if v == NULL_INT else f"{v} ")

    def raw(self, s: str) -> None:
        self.parts.append(s)

    def sstr(self, s: str) -> None:
        self.parts.append(f"{len(s)} {_esc(s)}")


def _t_fielddef(t: _T, fd: FieldDef) -> None:
    t.sstr(fd.name)
    t.num(fd.ptr_class)
    t.num(fd.n_elts)
    if not fd.ptr_class:
        t.sstr(fd.type)
    if fd.n_elts == 1:
        t.raw("T" if fd.xmt_code else "F")  # HYPOTHESIS: never observed in a text file


def _t_val(t: _T, kind: str, n: int, v) -> None:
    seq = v if (n != 1 or kind == "c") else [v]
    if kind in "pdtnwu":
        for x in seq:
            if kind == "p":
                t.parts.append(f"{x} ")
            else:
                t.num(x)
    elif kind == "f":
        for x in seq:
            s = fmt_double(x)
            t.raw(s if s == "?" else s + " ")
    elif kind in "vhib":
        for tup in seq:
            if kind in "vh" and any(c == NULL_DOUBLE for c in tup):
                t.raw("?")
            else:
                for c in tup:
                    s = fmt_double(c)
                    t.raw(s if s == "?" else s + " ")
    elif kind == "l":
        t.raw("".join("T" if b else "F" for b in seq))
    elif kind == "c":
        t.raw(_esc(seq))
    else:
        raise ParasolidError(f"unknown kind {kind!r}")


def _wrap(stream: str, width: int = 80) -> str:
    """Split into records of at most ``width`` characters, never ending a record in
    a space (readers ignore trailing spaces). Leading spaces are significant."""
    lines, i, n = [], 0, len(stream)
    while i < n:
        j = min(i + width, n)
        if j < n:
            while j > i + 1 and stream[j - 1] == " ":
                j -= 1
        lines.append(stream[i:j])
        i = j
    return "\n".join(lines)


def write_text(xt: XtTransmit) -> str:
    """Serialise the transmit body in Parasolid text format (without the text header)."""
    t = _T()
    t.raw("T")
    t.sstr(xt.modeller)
    t.raw(f"{len(xt.schema)} {_esc(xt.schema)}")
    if xt.base is not None:
        t.num(xt.max_types)
    t.num(xt.usfld)
    done = set()
    for nd in xt.nodes:
        t.num(nd.type)
        lay = xt.layouts[nd.type]
        if nd.type not in done:
            info = xt.schema_info[nd.type]
            done.add(nd.type)
            if info.mode == "base":
                t.num(255)
            else:
                t.num(info.nfields)
                if info.mode == "edit":
                    for op, fd in info.ops:
                        t.raw(op)
                        if fd is not None:
                            _t_fielddef(t, fd)
                else:
                    t.sstr(info.name)
                    t.sstr(info.desc)
                    for fd in info.defs:
                        _t_fielddef(t, fd)
        if any(f[2] == VAR for f in lay):
            t.num(nd.count)
        t.parts.append(f"{nd.index} ")
        for (_name, kind, n), v in zip(lay, nd.vals, strict=True):
            _t_val(t, kind, n, v)
    t.raw("1 0 ")
    return _wrap("".join(t.parts))


# --------------------------------------------------------------------------- text reader
class _TR:
    """Text-format token reader over the record-joined stream."""

    def __init__(self, s: str):
        self.s, self.p, self.n = s, 0, len(s)

    def need(self, k: int) -> None:
        if self.p + k > self.n:
            raise ParasolidError(f"text transmit truncated at {self.p}")

    def ch(self) -> str:
        self.need(1)
        c = self.s[self.p]
        self.p += 1
        if c == "\\":
            self.need(1)
            e = self.s[self.p]
            self.p += 1
            return {"0": "\0", "n": "\r", "r": "\n", "\\": "\\", "9": " " * 9}.get(e, e)
        return c

    def chars(self, k: int) -> str:
        out: list[str] = []
        total = 0
        while total < k:
            c = self.ch()
            out.append(c)
            total += len(c)
        s = "".join(out)
        if len(s) != k:
            raise ParasolidError(f"bad escaped string at {self.p}")
        return s

    def tok(self) -> str:
        self.need(1)
        if self.s[self.p] == "?":
            self.p += 1
            return "?"
        j = self.s.find(" ", self.p)
        if j < 0:
            raise ParasolidError(f"unterminated number at {self.p}")
        t = self.s[self.p : j]
        self.p = j + 1
        return t

    def int(self) -> int:
        t = self.tok()
        if t == "?":
            return NULL_INT
        try:
            return int(t)
        except ValueError:
            raise ParasolidError(f"bad integer {t!r} at {self.p}") from None

    def dbl(self) -> float:
        t = self.tok()
        if t == "?":
            return NULL_DOUBLE
        try:
            return float(t)
        except ValueError:
            raise ParasolidError(f"bad real {t!r} at {self.p}") from None

    def sstr(self) -> str:
        return self.chars(self.int())

    def logical(self) -> int:
        c = self.ch()
        if c not in "TF":
            raise ParasolidError(f"bad logical {c!r} at {self.p - 1}")
        return 1 if c == "T" else 0


def _tr_fielddef(r: _TR) -> FieldDef:
    name = r.sstr()
    ptr_class = r.int()
    n_elts = r.int()
    type_ = "" if ptr_class else r.sstr()
    xmt = r.logical() if n_elts == 1 else None
    return FieldDef(name, ptr_class, n_elts, type_, xmt)


def _tr_val(r: _TR, kind: str, n: int):
    if kind in "pdtnwu":
        return [r.int() for _ in range(n)]
    if kind == "f":
        return [r.dbl() for _ in range(n)]
    if kind in "vh":
        v = []
        for _ in range(n):
            if r.s.startswith("?", r.p):
                r.p += 1
                v.append((NULL_DOUBLE,) * 3)
            else:
                v.append((r.dbl(), r.dbl(), r.dbl()))
        return v
    if kind == "i":
        return [(r.dbl(), r.dbl()) for _ in range(n)]
    if kind == "b":
        return [tuple(r.dbl() for _ in range(6)) for _ in range(n)]
    if kind == "l":
        return [r.logical() for _ in range(n)]
    if kind == "c":
        return r.chars(n)
    raise ParasolidError(f"unknown kind {kind!r}")


@_as_parasolid_error
def parse_text(
    body: str, *, max_nodes: int = MAX_NODES, tick: Callable[[], None] | None = None
) -> XtTransmit:
    """Parse a text transmit body (the part after the common header). Record breaks are ignored,
    so bytes on a line after the terminator (a DOS end-of-file byte, padding) join its
    ``0``; they are counted in ``trailing`` like any other bytes after it. ``tick`` as for
    :func:`parse_binary`."""
    s = "".join(ln.rstrip(" ") for ln in body.replace("\r", "").split("\n")) + " "
    r = _TR(s)
    while r.p < r.n and r.s[r.p] == " ":
        r.p += 1
    if r.ch() != "T":
        raise ParasolidError("no text flag 'T'")
    xt = XtTransmit()
    xt.flag = b"T"
    xt.modeller = r.sstr()
    xt.schema = r.sstr()
    parts = xt.schema.split("_")
    if not (len(parts) >= 4 and parts[0] == "SCH" and parts[3].isdigit()):
        raise ParasolidError(f"transmit without embedded schema ({xt.schema})")
    xt.base = int(parts[3])
    xt.max_types = r.int()
    xt.usfld = r.int()
    while True:
        ntype = r.int()
        if ntype == 1:
            end = r.tok()
            if end != "0":
                if end[:1] != "0" or end[1:2].isdigit():
                    raise ParasolidError("bad terminator")
                r.p -= len(end)  # just after the 0: what follows is trailing data
            break
        lay = xt.layouts.get(ntype)
        if lay is None:
            first = r.int()
            base = S.BASE.get(ntype)
            if first == 255:
                info, lay = _base_info(ntype, S.NODE_NAMES.get(ntype, f"TYPE_{ntype}"))
            elif base is not None:
                ops, lay, bi = [], [], 0
                while True:
                    op = r.ch()
                    if op == "Z":
                        ops.append(("Z", None))
                        break
                    if op == "C":
                        if bi >= len(base):
                            raise ParasolidError(f"type {ntype}: edit script copies past the base layout")
                        lay.append(tuple(base[bi][:3]))
                        bi += 1
                        ops.append(("C", None))
                    elif op == "D":
                        if bi >= len(base):
                            raise ParasolidError(f"type {ntype}: edit script deletes past the base layout")
                        bi += 1
                        ops.append(("D", None))
                    elif op in "IA":
                        fd = _tr_fielddef(r)
                        lay.append(fd.layout())
                        ops.append((op, fd))
                    else:
                        raise ParasolidError(f"bad edit op {op!r}")
                info = SchemaInfo("edit", first, ops)
            else:
                name, desc = r.sstr(), r.sstr()
                defs = [_tr_fielddef(r) for _ in range(first)]
                info, lay = (
                    SchemaInfo("full", first, name=name, desc=desc, defs=defs),
                    [d.layout() for d in defs],
                )
            xt.layouts[ntype], xt.schema_info[ntype] = lay, info
        count = r.int() if any(f[2] == VAR for f in lay) else None
        idx = r.int()
        vals = []
        for _name, kind, n in lay:
            v = _tr_val(r, kind, count if n == VAR else n)
            if n == 1 and kind != "c":
                v = v[0]
            vals.append(v)
        xt.nodes.append(Node(ntype, idx, vals, count))
        if len(xt.nodes) > max_nodes:
            raise SldLimitError("too many nodes")
        if tick is not None:
            tick()
    xt.trailing = len(r.s[r.p :].strip())
    return xt


# --------------------------------------------------------------------------- headers
_PRE1 = "**ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz**************************"
_PRE2 = "**PARASOLID !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~0123456789**************************"
_END = "**END_OF_HEADER*****************************************************************"


def _kw(v: str) -> str:
    """Escape a header keyword value; anything outside printable ASCII becomes ``_``."""
    v = "".join(ch if " " <= ch <= "~" or ch == "\n" else "_" for ch in v)
    return v.replace("^", "^^").replace(";", "^;").replace(" ", "^_").replace("\n", "^n")


def text_header(xt: XtTransmit, *, fmt: str, key: str, file: str, guise: str = "transmit") -> str:
    """The common text header of the XT Format Reference ("Physical Layout").

    PART2 SCH names the schema without the base-schema suffix, as Parasolid writes
    it. Machine, user and date fields are written as ``unknown``."""
    sch = "_".join(xt.schema.split("_")[:3])
    fru = _kw(xt.modeller.strip(": ").replace(" ", "_"))
    lines = [
        _PRE1,
        _PRE2,
        "**PART1;",
        "MC=unknown;",
        "MC_MODEL=unknown;",
        "MC_ID=unknown;",
        "OS=unknown;",
        "OS_RELEASE=unknown;",
        f"FRU=SolidSeas^_extraction^_from^_{fru};",
        "APPL=SolidSeas;",
        "SITE=;",
        "USER=unknown;",
        f"FORMAT={fmt};",
        f"GUISE={guise};",
        f"KEY={_kw(key)};",
        f"FILE={_kw(file)};",
        "DATE=unknown;",
        "**PART2;",
        f"SCH={sch};",
        f"USFLD_SIZE={xt.usfld};",
        "**PART3;",
        _END,
    ]
    out = []
    for ln in lines:  # records must not exceed 80 characters
        while len(ln) > 80:
            cut = 80
            if ln[cut - 1] == "^":
                cut -= 1
            out.append(ln[:cut])
            ln = ln[cut:]
        out.append(ln)
    return "\n".join(out) + "\n"


def split_header(data: bytes) -> tuple[bytes, bytes]:
    """``(header text, transmit body)`` for a file that starts with the common header."""
    i = data.find(b"**END_OF_HEADER")
    if i < 0:
        return b"", data
    j = data.find(b"\n", i)
    return data[: j + 1], data[j + 1 :]


def read_file(data: bytes) -> XtTransmit:
    """Parse a whole .x_b or .x_t file (header optional)."""
    _header, body = split_header(data)
    if body.startswith(b"PS"):
        return parse_binary(body)
    return parse_text(body.decode("latin-1"))


# --------------------------------------------------------------------------- partition to parts
_CUT = {TYPE_BODY: {"owner", "next", "previous"}, TYPE_ATTRIB_DEF: {"next"}}
_CHAIN_FIELDS = {TYPE_ATTRIBUTE: ("next_of_type", "previous_of_type")}


def _pointer_slots(xt: XtTransmit, ntype: int) -> list[tuple[int, str, int]]:
    return [(i, f[0], f[2]) for i, f in enumerate(xt.layouts[ntype]) if f[1] == "p"]


def _targets(xt: XtTransmit, nd: Node):
    for i, name, n in _pointer_slots(xt, nd.type):
        v = nd.vals[i]
        if n == 1:
            if v:
                yield i, name, None, v
        else:
            for k, x in enumerate(v):
                if x:
                    yield i, name, k, x


def partition_to_parts(px: XtTransmit) -> tuple[list[XtTransmit], list[dict[str, Any]]]:
    """Copy every BODY of a partition transmit into its own part transmit.

    Returns ``(parts, reports)``; each report lists what had to be cut."""
    if px.kind != "partition":
        raise ParasolidError("not a partition transmit")
    idx = px.by_index()
    parts, reports = [], []
    for body in (n for n in px.nodes if n.type == TYPE_BODY):
        rep: dict[str, Any] = {
            "body_index": body.index,
            "cut_to_world": 0,
            "cut_to_other_body": 0,
            "cut_dangling": 0,
            "cut_fields": {},
            "attrib_defs": 0,
        }
        # Breadth-first closure from the BODY, following pointer fields in layout order.
        # New indices follow discovery order, which reproduces SOLIDWORKS' own numbering
        # on the synthetic box export (BODY = 1, its pointer targets 2..n, ...).
        keep = {body.index}
        order = [body]
        qi = 0
        while qi < len(order):
            nd = order[qi]
            qi += 1
            cut = _CUT.get(nd.type, ())
            for _i, name, _k, x in _targets(px, nd):
                if name in cut or name in _CHAIN_FIELDS.get(nd.type, ()):
                    continue
                t = idx.get(x)
                if t is None or t.type == TYPE_WORLD or (t.type == TYPE_BODY and t is not body):
                    continue
                if x not in keep:
                    keep.add(x)
                    order.append(t)
        remap = {n.index: k + 1 for k, n in enumerate(order)}
        new_nodes = []
        for nd in order:
            vals = list(nd.vals)
            cut = _CUT.get(nd.type, ())
            for i, name, n in _pointer_slots(px, nd.type):
                v = vals[i]
                seq = [v] if n == 1 else list(v)
                for k, x in enumerate(seq):
                    if not x:
                        continue
                    if name in cut and nd.type != TYPE_ATTRIB_DEF:
                        seq[k] = 0
                        rep["cut_fields"][name] = rep["cut_fields"].get(name, 0) + 1
                        continue
                    if x in remap:
                        seq[k] = remap[x]
                        continue
                    t = idx.get(x)
                    if t is None:
                        rep["cut_dangling"] += 1
                    elif t.type == TYPE_WORLD:
                        rep["cut_to_world"] += 1
                    elif t.type == TYPE_BODY:
                        rep["cut_to_other_body"] += 1
                    else:
                        rep["cut_fields"][name] = rep["cut_fields"].get(name, 0) + 1
                    seq[k] = 0
                vals[i] = seq[0] if n == 1 else seq
            new_nodes.append(Node(nd.type, remap[nd.index], vals, nd.count))
        # re-chain the attribute definitions that were kept (ATTRIB_DEF.next)
        defs = [n for n in new_nodes if n.type == TYPE_ATTRIB_DEF]
        rep["attrib_defs"] = len(defs)
        if defs:
            ni = px.field_names(TYPE_ATTRIB_DEF).index("next")
            for a, b in zip(defs, [*defs[1:], None], strict=True):
                a.vals[ni] = b.index if b is not None else 0
        part = XtTransmit()
        part.modeller = px.modeller.replace("TRANSMIT FILE (partition)", "TRANSMIT FILE")
        part.schema, part.base, part.max_types, part.usfld = px.schema, px.base, px.max_types, px.usfld
        part.layouts = {t: px.layouts[t] for t in {n.type for n in new_nodes}}
        part.schema_info = {t: px.schema_info[t] for t in part.layouts}
        part.nodes = new_nodes
        rep["nodes"] = len(new_nodes)
        parts.append(part)
        reports.append(rep)
    return parts, reports


# --------------------------------------------------------------------------- validation
def validate(xt: XtTransmit) -> dict[str, Any]:
    """Structural checks that do not need a Parasolid kernel.

    ``ok`` means: parsed to the terminator with no trailing bytes, the root node
    has index 1 and the type the reference prescribes for the file kind, every
    non-null pointer resolves (except fields documented as ignorable), and the
    FACE, LOOP and fin back-pointers are consistent."""
    errs: list[str] = []
    idx = xt.by_index()
    if xt.trailing:
        errs.append(f"{xt.trailing} trailing bytes")
    root = idx.get(1)
    want = {"part": (TYPE_BODY, 10, 74), "partition": (TYPE_WORLD,)}.get(xt.kind, ())
    if root is None:
        errs.append("no node with index 1")
    elif want and root.type not in want:
        errs.append(f"root is {root.tname}")
    dangling = 0
    dangling_fields: dict[str, int] = {}
    # SOLIDWORKS' own x_b export carries dangling BODY.next and ATTRIB_DEF.next values,
    # which the reference documents as ignored in part files.
    ignore = {(TYPE_BODY, "next"), (TYPE_BODY, "previous"), (TYPE_BODY, "owner")}
    if xt.kind == "part":
        ignore.add((TYPE_ATTRIB_DEF, "next"))
    for nd in xt.nodes:
        for _i, name, _k, x in _targets(xt, nd):
            if x not in idx and (nd.type, name) not in ignore:
                dangling += 1
                key = f"{nd.tname}.{name}"
                dangling_fields[key] = dangling_fields.get(key, 0) + 1
    if dangling:
        errs.append(f"{dangling} dangling pointers {dangling_fields}")
    topo = 0
    # Every loop belongs to one face and every fin to one loop, so a valid walk
    # visits each at most once. A repeat means a pointer cycle in a damaged or
    # crafted file; stop there rather than loop forever.
    seen_loops: set[int] = set()
    seen_fins: set[int] = set()
    try:
        for nd in xt.nodes:
            if nd.tname == "FACE":
                lp = idx.get(xt.get(nd, "loop"))
                while lp is not None:
                    if lp.index in seen_loops:
                        errs.append(f"LOOP {lp.index} reached twice (pointer cycle)")
                        break
                    seen_loops.add(lp.index)
                    topo += 1
                    if xt.get(lp, "face") != nd.index:
                        errs.append(f"LOOP {lp.index} face pointer mismatch")
                        break
                    he0 = xt.get(lp, "halfedge")
                    he = idx.get(he0)
                    while he is not None:
                        if he.index in seen_fins:
                            errs.append(f"fin {he.index} reached twice (pointer cycle)")
                            break
                        seen_fins.add(he.index)
                        if xt.get(he, "loop") != lp.index:
                            errs.append(f"fin {he.index} loop mismatch")
                            break
                        nx = xt.get(he, "forward")
                        if nx == he0:
                            break
                        he = idx.get(nx)
                    nxt = xt.get(lp, "next")
                    lp = idx.get(nxt) if nxt else None
                if len(errs) >= 10:
                    break
            elif nd.tname == "HALFEDGE":
                oth = idx.get(xt.get(nd, "other"))
                if oth is not None and xt.get(oth, "other") != nd.index:
                    errs.append(f"fin {nd.index} other/other mismatch")
    except (KeyError, ValueError, IndexError, ParasolidError) as exc:
        errs.append(f"topology walk failed: {exc!r}")
    c = xt.census()
    return {
        "ok": not errs,
        "errors": errs[:10],
        "kind": xt.kind,
        "schema": xt.schema,
        "modeller_version": xt.modeller_version,
        "nodes": len(xt.nodes),
        "census": c,
        "bodies": c.get("BODY", 0),
        "faces": c.get("FACE", 0),
        "loops_checked": topo,
    }


# --------------------------------------------------------------------------- B-rep comparison
_MODEL_TYPES = {
    "BODY",
    "REGION",
    "SHELL",
    "FACE",
    "LOOP",
    "EDGE",
    "HALFEDGE",
    "VERTEX",
    "POINT",
    "LINE",
    "CIRCLE",
    "ELLIPSE",
    "PLANE",
    "CYLINDER",
    "CONE",
    "SPHERE",
    "TORUS",
    "B_SURFACE",
    "B_CURVE",
    "NURBS_SURF",
    "NURBS_CURVE",
    "SURFACE_DATA",
    "CURVE_DATA",
    "BSPLINE_VERTICES",
    "KNOT_MULT",
    "KNOT_SET",
    "INTERSECTION",
    "CHART",
    "LIMIT",
    "SP_CURVE",
    "TRIMMED_CURVE",
    "OFFSET_SURF",
    "SWEPT_SURF",
    "SPUN_SURF",
    "BLENDED_EDGE",
    "BLEND_BOUND",
    "PE_SURF",
    "PE_CURVE",
    "GEOMETRIC_OWNER",
    "TRANSFORM",
}
_SKIP_FIELDS = {
    "attributes_features",
    "attribute_chains",
    "highest_node_id",
    "next",
    "previous",
    "owner",
    "index_map_offset",
    "index_map",
    "node_id_index_map",
    "schema_embedding_map",
    "lowest_node_id",
    "mesh_offset_data",
}


def _model_keys(xt: XtTransmit) -> dict[int, tuple]:
    names = {t: xt.field_names(t) for t in xt.layouts}
    key: dict[int, tuple] = {}
    for n in xt.nodes:
        if "node_id" in names[n.type] and n.tname in _MODEL_TYPES:
            key[n.index] = (n.tname, n.vals[names[n.type].index("node_id")])
    for n in xt.nodes:
        if n.tname == "BODY":
            key[n.index] = ("BODY",)
    for n in xt.nodes:
        if n.tname == "HALFEDGE":
            key[n.index] = ("HALFEDGE", key.get(xt.get(n, "edge")), key.get(xt.get(n, "loop")))
    return key


def _close(a, b, tol: float) -> bool:
    if isinstance(a, (list, tuple)):
        return (
            isinstance(b, (list, tuple))
            and len(a) == len(b)
            and all(_close(x, y, tol) for x, y in zip(a, b, strict=True))
        )
    if isinstance(a, float) and isinstance(b, float):
        return a == b or bool(tol and abs(a - b) <= tol * max(abs(a), abs(b), 1e-300))
    return a == b


def compare_brep(xa: XtTransmit, xb: XtTransmit, *, tol: float = 0.0, max_report: int = 20) -> dict[str, Any]:
    """Compare the topology and geometry of two transmits, ignoring attributes and numbering.

    Nodes are matched by ``(type, node_id)`` and fins by ``(edge, loop)``. Pointer
    fields are compared through the matched keys, other fields exactly or within
    the relative tolerance ``tol``."""
    ka, kb = _model_keys(xa), _model_keys(xb)
    ra = {k: i for i, k in ka.items()}
    rb = {k: i for i, k in kb.items()}
    ia, ib = xa.by_index(), xb.by_index()
    only_a = sorted(set(ra) - set(rb), key=str)
    only_b = sorted(set(rb) - set(ra), key=str)
    diffs: list[tuple] = []
    n_diffs = 0
    compared = 0
    for k in set(ra) & set(rb):
        na, nb = ia[ra[k]], ib[rb[k]]
        fa = {f[0]: (f, v) for f, v in zip(xa.layouts[na.type], na.vals, strict=True)}
        fb = {f[0]: (f, v) for f, v in zip(xb.layouts[nb.type], nb.vals, strict=True)}
        for name, (f, va) in fa.items():
            if name in _SKIP_FIELDS or name not in fb:
                continue
            vb = fb[name][1]
            if f[1] == "p":
                ma = [
                    ka.get(x, ("<non-model>",) if x else None) for x in (va if isinstance(va, list) else [va])
                ]
                mb = [
                    kb.get(x, ("<non-model>",) if x else None) for x in (vb if isinstance(vb, list) else [vb])
                ]
                ok = ma == mb
            else:
                ok = _close(va, vb, tol)
            compared += 1
            if not ok:
                n_diffs += 1
                if len(diffs) < max_report:
                    diffs.append((k, name, va, vb))
    return {
        "matched_nodes": len(set(ra) & set(rb)),
        "only_a": only_a[:max_report],
        "n_only_a": len(only_a),
        "only_b": only_b[:max_report],
        "n_only_b": len(only_b),
        "fields_compared": compared,
        "n_diffs": n_diffs,
        "diffs": diffs,
        "identical": not only_a and not only_b and not n_diffs,
    }


# --------------------------------------------------------------------------- document access
_PARTITION = re.compile(r"(?i)Contents/Config-(\d+)-Partition(?:__ZLB)?")
_LOCAL = re.compile(r"(?i)Config-(\d+)-FeatureBodies/LocalBodies(?:__ZLB)?")


def body_type_name(xt: XtTransmit, body: Node) -> str:
    bt = xt.get(body, "body_type")
    return BODY_TYPES.get(bt, f"type{bt}")


# The BODY attribute whose integer field says whether SOLIDWORKS shows the body: 1 shown,
# 0 hidden (docs/FORMAT.md 10.9).
SHOWN_ATTRIBUTE = "BODY_IN_LIGHTWEIGHT_PERM"


def _text(xt: XtTransmit, node: Node | None) -> str | None:
    if node is None:
        return None
    try:
        s = xt.get(node, "string")
    except ParasolidError:
        return None
    if isinstance(s, list):
        # a code unit outside Unicode (a crafted value) is dropped: chr() would raise ValueError
        s = "".join(
            x if isinstance(x, str) else chr(x)
            for x in s
            if isinstance(x, str) or (isinstance(x, int) and 0 < x < 0x110000)
        )
    return s if isinstance(s, str) else None


def hidden_bodies(xt: XtTransmit) -> dict[int, bool | None]:
    """Whether SOLIDWORKS hides each body that carries a ``BODY_IN_LIGHTWEIGHT_PERM``
    attribute, by BODY index: True for 0 (hidden), False for 1 (shown), None for
    anything else (``docs/FORMAT.md`` 10.9). Worked out once per transmit, in two passes
    over its nodes, however many bodies ask (:func:`body_hidden`)."""
    cached = getattr(xt, "_hidden", None)
    if cached is not None:
        return cached
    out: dict[int, bool | None] = {}
    try:
        idx = xt.by_index()
        defs = set()
        for n in xt.nodes:
            if n.type == 80 and _text(xt, idx.get(xt.get(n, "identifier"))) == SHOWN_ATTRIBUTE:
                defs.add(n.index)
        found: dict[int, set] = {}
        for n in xt.nodes if defs else ():
            if n.type != 81 or xt.get(n, "definition") not in defs:
                continue
            owner = xt.get(n, "owner")
            got = found.setdefault(owner, set())
            fields = xt.get(n, "fields")
            for f in fields if isinstance(fields, list) else ():
                v = idx.get(f)
                if v is None or v.type != 82:
                    continue
                vals = xt.get(v, "values")
                got.add(vals[0] if isinstance(vals, list) and len(vals) == 1 and vals[0] in (0, 1) else None)
        for owner, values in found.items():
            out[owner] = values.pop() == 0 if len(values) == 1 and None not in values else None
    except (ParasolidError, TypeError, ValueError):
        out = {}
    xt._hidden = out
    return out


def body_hidden(xt: XtTransmit, body: Node) -> bool | None:
    """Whether SOLIDWORKS hides ``body``: its ``BODY_IN_LIGHTWEIGHT_PERM`` attribute's
    integer field, 0 for a hidden body and 1 for a shown one (``docs/FORMAT.md`` 10.9).
    None when the body has no such attribute (as most imported bodies have none) or it
    holds anything else: not known."""
    return hidden_bodies(xt).get(body.index)


def partition_streams(container: Container) -> list[tuple[int, str]]:
    """``[(configuration id, stream name)]`` for every ``Contents/Config-<n>-Partition``."""
    out = []
    for name in container.names():
        m = _PARTITION.fullmatch(name)
        if m:
            out.append((int(m.group(1)), name))
    return sorted(out)


def local_body_streams(container: Container) -> list[tuple[int, str]]:
    out = []
    for name in container.names():
        m = _LOCAL.fullmatch(name)
        if m:
            out.append((int(m.group(1)), name))
    return sorted(out)


def config_names_from_keywords(container: Container) -> dict[int, str]:
    """``{n: configuration name}`` from ``swXmlContents/KeyWords``.

    HYPOTHESIS, consistent with every sampled file: the ``id`` of a KeyWords
    ``<Configuration>`` element is the ``<n>`` of ``Config-<n>-Partition``."""
    import html

    out: dict[int, str] = {}
    if "swXmlContents/KeyWords" not in container:
        return out
    try:
        d = container.read("swXmlContents/KeyWords", max_bytes=64 << 20)
    except SldError:
        return out
    txt = d[1:].decode("utf-8", "replace") if d[:1] == b"\x86" else d.decode("utf-8", "replace")
    for attrs in re.findall(r"<Configuration\b([^>]*)>", txt):
        i = re.search(r'\bid="(\d+)"', attrs)
        n = re.search(r'\bName="([^"]*)"', attrs)
        if i and n:
            out[int(i.group(1))] = html.unescape(n.group(1))
    return out


def _safe(text: str, limit: int = 60) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in text)[:limit] or "_"


@dataclass
class ParasolidBody:
    """One body, as a standalone Parasolid part transmit."""

    name: str  # "Config-0/body1" or "Config-0/local/Imported1#0"
    configuration_id: int
    configuration_name: str | None
    source: str  # "partition" or "local-bodies"
    feature: str | None
    body_type: str  # "solid", "sheet", "wire" or "general"
    transmit: XtTransmit
    report: dict[str, Any] = field(default_factory=dict)

    @property
    def schema(self) -> str:
        return self.transmit.schema

    @property
    def valid(self) -> bool:
        return bool(self.report.get("valid", {}).get("ok"))

    def file_stem(self, document_stem: str) -> str:
        cfg = _safe(self.configuration_name) if self.configuration_name else f"Config-{self.configuration_id}"
        if self.source == "partition":
            return f"{document_stem}_{cfg}_{self.name.rsplit('/', 1)[-1]}"
        return (
            f"{document_stem}_{cfg}_local_{_safe(self.feature or 'body', 40)}_{self.name.rsplit('#', 1)[-1]}"
        )

    def x_b(self, key: str = "body") -> bytes:
        """The body as a binary Parasolid file (.x_b): text header plus neutral binary."""
        header = text_header(self.transmit, fmt="binary", key=key, file=key + ".x_b")
        return header.encode("ascii") + write_binary(self.transmit)

    def x_t(self, key: str = "body") -> bytes:
        """The body as a text Parasolid file (.x_t). Values are rounded to 15 significant digits."""
        header = text_header(self.transmit, fmt="text", key=key, file=key + ".x_t")
        return (header + write_text(self.transmit) + "\n").encode("latin-1")


@dataclass
class RawTransmit:
    """An embedded transmit exactly as stored (partition or deltas)."""

    configuration_id: int
    kind: str  # "partition" or "deltas"
    data: bytes

    def p_b(self, key: str = "partition") -> bytes:
        """A partition as a .p_b file (standard text header added). Deltas get no header."""
        if self.kind != "partition":
            return self.data
        hdr = text_header(
            read_header(self.data), fmt="binary", key=key, file=key + ".p_b", guise="transmit_partition"
        )
        return hdr.encode("ascii") + self.data


@dataclass
class ParasolidResult:
    bodies: list[ParasolidBody] = field(default_factory=list)
    raw: list[RawTransmit] = field(default_factory=list)
    problems: list[dict[str, Any]] = field(default_factory=list)
    bytes_inflated: int = 0  # transmit bytes decompressed, against max_total_bytes

    def __iter__(self):
        return iter(self.bodies)

    def __len__(self) -> int:
        return len(self.bodies)

    def configurations(self) -> list[int]:
        return sorted({b.configuration_id for b in self.bodies})


def extract_parasolid(
    container: Container,
    *,
    local_bodies: str = "fallback",
    include_raw: bool = False,
    max_bytes: int = DEFAULT_MAX_TRANSMIT_BYTES,
    max_total_bytes: int | None = None,
    config_names: dict[int, str] | None = None,
    configurations=None,
) -> ParasolidResult:
    """Extract the Parasolid bodies of a document, per configuration.

    * Partition bodies: body k of ``Contents/Config-<n>-Partition``, converted to a
      standalone part transmit. On the synthetic boxes these are B-rep identical
      to SOLIDWORKS' own .x_b export.
    * Local bodies: with ``local_bodies="fallback"`` (the default) the bodies of
      ``Config-<n>-FeatureBodies/LocalBodies`` are returned only for configurations
      whose partition holds no bodies (imported geometry; that they are the final
      bodies is a hypothesis). ``"always"`` returns them for every configuration
      and ``"never"`` disables them.
    * ``include_raw`` also returns each partition and deltas transmit as stored.
    * Transmits larger than ``max_bytes`` decoded are not parsed and get a problem
      entry; parsing costs roughly six times the transmit size in memory.
    * ``max_total_bytes`` (default four times ``max_bytes``) caps everything
      inflated for this document. Declared sizes are checked before anything is
      inflated, so a small crafted file cannot claim gigabytes of memory.
      ``bytes_inflated`` of the result says how much was.
    * ``configurations``, a collection of configuration ids, limits the reading to
      those configurations' streams (None: every one).
    """
    if local_bodies not in ("fallback", "always", "never"):
        raise ValueError("local_bodies must be 'fallback', 'always' or 'never'")
    names = config_names if config_names is not None else config_names_from_keywords(container)
    res = ParasolidResult()
    budget = [max_total_bytes if max_total_bytes is not None else 4 * max_bytes]

    def take(size: int, where: dict[str, Any]) -> bool:
        if size > budget[0]:
            res.problems.append(
                {
                    **where,
                    "error": f"SldLimitError: {size} more bytes would exceed this document's "
                    f"decompression budget ({budget[0]} bytes left)",
                }
            )
            return False
        budget[0] -= size
        return True

    def over_cap(size: int, where: dict[str, Any]) -> bool:
        if size <= max_bytes:
            return False
        res.problems.append(
            {**where, "error": f"SldLimitError: a transmit of {size} bytes exceeds the cap {max_bytes}"}
        )
        return True

    wanted = None if configurations is None else set(configurations)
    total = budget[0]
    bodies_per_cfg: dict[int, int] = {}
    unread: set[int] = set()  # configurations whose partition could not be read: no fallback for them
    for cfg_id, stream in partition_streams(container):
        if wanted is not None and cfg_id not in wanted:
            continue
        bodies_per_cfg.setdefault(cfg_id, 0)
        try:
            blocks = list(iter_chain_blocks(container.read(stream, max_bytes=budget[0])))
        except SldError as exc:
            res.problems.append({"stream": stream, "error": f"{type(exc).__name__}: {exc}"})
            unread.add(cfg_id)
            continue
        for bi, (size, zblock) in enumerate(blocks):
            if not size:
                continue
            where = {"stream": stream, "block": bi}
            try:
                head = peek_zlb(zblock, 96)
            except SldError as exc:
                res.problems.append({**where, "error": f"{type(exc).__name__}: {exc}"})
                unread.add(cfg_id)
                continue
            if not head.startswith(b"PS\x00\x00"):
                res.problems.append({**where, "error": "block is not neutral binary"})
                continue
            deltas = b"(deltas)" in head[:90]
            if deltas and not include_raw:
                continue  # never parsed, so never inflated unless asked for
            too_big = not deltas and over_cap(size, where)
            if too_big:
                unread.add(cfg_id)
                if not include_raw:
                    continue
            if not take(size, where):
                if not deltas:
                    unread.add(cfg_id)
                continue
            try:
                blk = unwrap_zlb(zblock, max_bytes=size)
            except SldError as exc:
                res.problems.append({**where, "error": f"{type(exc).__name__}: {exc}"})
                if not deltas:
                    unread.add(cfg_id)
                continue
            if include_raw:
                res.raw.append(RawTransmit(cfg_id, "deltas" if deltas else "partition", blk))
            if deltas or too_big:
                continue
            try:
                px = parse_binary(blk)
                if px.kind != "partition":
                    continue
                parts, reports = partition_to_parts(px)
            except SldError as exc:
                res.problems.append({**where, "error": f"{type(exc).__name__}: {exc}"})
                unread.add(cfg_id)
                continue
            bodies_per_cfg[cfg_id] += len(parts)
            for k, (part, rep) in enumerate(zip(parts, reports, strict=True), 1):
                rep.update(stream=stream, inferred_types=px.inferred_types, valid=validate(part))
                res.bodies.append(
                    ParasolidBody(
                        name=f"Config-{cfg_id}/body{k}",
                        configuration_id=cfg_id,
                        configuration_name=names.get(cfg_id),
                        source="partition",
                        feature=None,
                        body_type=_body_type_or_unknown(part, part.nodes[0]),
                        transmit=part,
                        report=rep,
                    )
                )
    if local_bodies == "never":
        res.bytes_inflated = total - budget[0]
        return res
    for cfg_id, stream in local_body_streams(container):
        if wanted is not None and cfg_id not in wanted:
            continue
        if local_bodies == "fallback":
            if bodies_per_cfg.get(cfg_id, 0) > 0:
                continue
            if cfg_id in unread:
                # The partition might hold the real bodies; LocalBodies are feature inputs then.
                res.problems.append({"stream": stream, "error": "not used: the partition could not be read"})
                continue
        try:
            entries = list(iter_local_body_blocks(container.read(stream, max_bytes=budget[0])))
        except SldError as exc:
            res.problems.append({"stream": stream, "error": f"{type(exc).__name__}: {exc}"})
            continue
        for feature, k, size, zblock in entries:
            where = {"stream": stream, "feature": feature}
            if over_cap(size, where) or not take(size, where):
                continue
            try:
                part = parse_binary(unwrap_zlb(zblock, max_bytes=size))
            except SldError as exc:
                res.problems.append({**where, "error": f"{type(exc).__name__}: {exc}"})
                continue
            if part.kind != "part":
                res.problems.append({**where, "error": "not a part transmit"})
                continue
            root = part.by_index().get(1)
            res.bodies.append(
                ParasolidBody(
                    name=f"Config-{cfg_id}/local/{feature}#{k}",
                    configuration_id=cfg_id,
                    configuration_name=names.get(cfg_id),
                    source="local-bodies",
                    feature=feature,
                    body_type=_body_type_or_unknown(part, root)
                    if root is not None and root.type == TYPE_BODY
                    else "unknown",
                    transmit=part,
                    report={"stream": stream, "inferred_types": part.inferred_types, "valid": validate(part)},
                )
            )
    res.bytes_inflated = total - budget[0]
    return res


def _body_type_or_unknown(xt: XtTransmit, node: Node) -> str:
    try:
        return body_type_name(xt, node)
    except SldError:
        return "unknown"


def document_stem(path: str | None) -> str:
    return os.path.splitext(os.path.basename(path))[0] if path else "document"
