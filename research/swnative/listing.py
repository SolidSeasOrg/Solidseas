"""The analysis side's assembler for the specification's record listings.

``docs/sldprt-spec/README.md`` section 15.0.3 defines the listing language: one
line per field, typed (``u32 3``, ``f64 0.01``, ``cstr "Sketch1"``), MFC class
records counted the way ``CArchive`` counts them (``class moNodeName_c 1``),
slots for what a document supplies (``u32 $doc.created``), expressions for what
the specification derives (``u16 =17+2*len($features)``), loops and conditions
over the slots, length-prefixed blocks (``@sized``), and text members with ``${slot}``
substitution.

This module is the specification's own reference reading of that language. The
analysis side uses it to prove a listing right: assembled with a fixture's slot
values, a listing must give that fixture's member byte for byte
(``tests/test_sldprt_spec.py``). The generator never imports it: the
implementation reads the language's definition and writes its own.

``python -m swnative.listing LISTING --slots slots.json`` assembles one listing
and prints its bytes in hex with the listing line of each run.
"""

from __future__ import annotations

import ast
import json
import operator
import re
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

SPEC = Path(__file__).resolve().parents[2] / "docs" / "sldprt-spec"
LISTINGS = SPEC / "listings"
ZLB_MAGIC = bytes.fromhex("231DD571DA8148A2A85898B21B89EF99")

_INTS = {
    "u8": "<B", "u16": "<H", "u32": "<I", "u64": "<Q",
    "i8": "<b", "i16": "<h", "i32": "<i", "i64": "<q",
    "u16be": ">H", "u32be": ">I", "u64be": ">Q",
}
_FLOATS = {"f32": "<f", "f64": "<d", "f64be": ">d"}


class ListingError(ValueError):
    """A listing that does not parse or does not assemble; names the file and line."""


@dataclass
class Archive:
    """The load map of one MFC ``CArchive``: which class has which index, the next index,
    and the index of each labelled object."""

    next: int = 1
    classes: dict[str, int] = field(default_factory=dict)
    schemas: dict[str, int] = field(default_factory=dict)
    labels: dict[str, int] = field(default_factory=dict)

    def obj(self, name: str, schema: int, label: str | None) -> bytes:
        if name in self.classes:
            if self.schemas[name] != schema:
                raise ValueError(f"class {name} has schema {self.schemas[name]}, not {schema}")
            out = struct.pack("<H", 0x8000 | self.classes[name])
        else:
            enc = name.encode("ascii")
            out = b"\xff\xff" + struct.pack("<HH", schema, len(enc)) + enc
            self.classes[name], self.schemas[name] = self.next, schema
            self.next += 1
        if label:
            self.labels[label] = self.next
        self.next += 1
        return out


@dataclass(frozen=True)
class Run:
    """``size`` bytes at ``offset`` came from ``line`` of ``source`` in section ``section``."""

    offset: int
    size: int
    source: str
    line: int
    section: str
    kind: str  # "typed" (a constant field), "hex" (an opaque constant run) or "slot"


@dataclass
class Result:
    data: bytes
    runs: list[Run]
    archive: Archive


# ------------------------------------------------------------------ values
_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
}
_FUNCS = {"len": len, "min": min, "max": max, "abs": abs, "int": int, "float": float, "round": round}
_SLOT = re.compile(r"\$([A-Za-z_][\w.]*)")


def _lookup(slots: dict, path: str):
    cur = slots
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)]
        else:
            raise KeyError(path)
    return cur


def _eval(expr: str, slots: dict):
    names: dict[str, object] = {}

    def sub(m: re.Match) -> str:
        key = f"_s{len(names)}"
        names[key] = _lookup(slots, m.group(1))
        return key

    tree = ast.parse(_SLOT.sub(sub, expr), mode="eval")

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str)):
            return node.value
        if isinstance(node, ast.Name) and node.id in names:
            return names[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            return _BINOPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            a, b = ev(node.left), ev(node.comparators[0])
            op = node.ops[0]
            table = {ast.Eq: a == b, ast.NotEq: a != b, ast.Lt: a < b, ast.LtE: a <= b,
                     ast.Gt: a > b, ast.GtE: a >= b}
            return table[type(op)]
        if isinstance(node, ast.BoolOp):
            vals = [ev(v) for v in node.values]
            return all(vals) if isinstance(node.op, ast.And) else any(vals)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not ev(node.operand)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise ValueError(f"not allowed in an expression: {ast.dump(node)}")

    return ev(tree)


def _value(tok: str, slots: dict):
    """A literal, ``$slot`` or ``=expression``; returns (value, constant?)."""
    if tok.startswith("$"):
        return _lookup(slots, tok[1:]), False
    if tok.startswith("="):
        return _eval(tok[1:], slots), False
    if tok.startswith('"'):
        return json.loads(tok), True
    if re.fullmatch(r"-?0[xX][0-9A-Fa-f]+", tok):
        return int(tok, 16), True
    if re.fullmatch(r"-?\d+", tok):
        return int(tok), True
    return float(tok), True


def cstring(text: str) -> bytes:
    """MFC's Unicode ``CString``: FF FE FF, the length in characters (a byte; FF then a
    u16; FF FF FF then a u32), then UTF-16LE."""
    enc = text.encode("utf-16-le")
    n = len(enc) // 2
    if n < 0xFF:
        size = struct.pack("<B", n)
    elif n < 0xFFFF:
        size = b"\xff" + struct.pack("<H", n)
    else:
        size = b"\xff\xff\xff" + struct.pack("<I", n)
    return b"\xff\xfe\xff" + size + enc


def astring(text: str) -> bytes:
    """MFC's narrow ``CString``: the length (as above, without the FF FE FF), then the bytes."""
    enc = text.encode("latin-1")
    n = len(enc)
    if n < 0xFF:
        size = struct.pack("<B", n)
    elif n < 0xFFFF:
        size = b"\xff" + struct.pack("<H", n)
    else:
        size = b"\xff\xff\xff" + struct.pack("<I", n)
    return size + enc


# ------------------------------------------------------------------ parsing
@dataclass
class Line:
    source: str
    number: int
    text: str


def _tokens(text: str) -> list[str]:
    """Whitespace-separated tokens; a double-quoted string is one token; ``#`` starts a comment."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c == "#":
            break
        elif c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i : j + 1])
            i = j + 1
        else:  # a bare token; a quoted part inside it (P="a b") stays in it
            j = i
            while j < n and not text[j].isspace():
                if text[j] == '"':
                    j += 1
                    while j < n and text[j] != '"':
                        j += 2 if text[j] == "\\" else 1
                j += 1
            out.append(text[i:j])
            i = j
    return out


def load(path: Path | str) -> list[Line]:
    path = Path(path)
    lines = []
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        lines.append(Line(path.name, n, raw))
    return lines


class _Assembler:
    def __init__(self, archive: Archive, base: Path):
        self.archive = archive
        self.base = base
        self.out = bytearray()
        self.runs: list[Run] = []
        self.section = ""
        self.defs: dict[str, tuple[list[str], list[Line]]] = {}

    def emit(self, data: bytes, line: Line, constant: bool, kind: str = "typed") -> None:
        if data:
            kind = kind if constant else "slot"
            self.runs.append(Run(len(self.out), len(data), line.source, line.number, self.section, kind))
            self.out += data

    def fail(self, line: Line, msg: str) -> ListingError:
        return ListingError(f"{line.source}:{line.number}: {msg}: {line.text.strip()}")

    # A block runs from the line after its opener to its closer at the same depth.
    _OPEN = ("@if", "@for", "@define", "@zlb", "@text", "@sized")
    _CLOSE = ("@endif", "@endfor", "@end", "@endzlb", "@endtext", "@endsized")

    def block(self, lines: list[Line], i: int, opener: str,
              closers: tuple[str, ...]) -> tuple[list[Line], int, str]:
        depth, body = 0, []
        while i < len(lines):
            toks = _tokens(lines[i].text)
            head = toks[0] if toks else ""
            if opener == "@text":
                if lines[i].text.strip() == "@endtext":
                    return body, i, "@endtext"
            elif depth == 0 and head in closers:
                return body, i, head
            elif head in self._OPEN:
                depth += 1
            elif head in self._CLOSE:
                depth -= 1
            body.append(lines[i])
            i += 1
        raise ListingError(f"{opener} has no {closers[-1]}")

    def run(self, lines: list[Line], slots: dict) -> None:
        i = 0
        while i < len(lines):
            line = lines[i]
            toks = _tokens(line.text)
            i += 1
            if not toks:
                continue
            head, args = toks[0], toks[1:]
            try:
                i = self.step(head, args, line, lines, i, slots)
            except ListingError:
                raise
            except (KeyError, ValueError, TypeError, struct.error, IndexError) as exc:
                raise self.fail(line, f"{type(exc).__name__}: {exc}") from exc

    def step(self, head: str, args: list[str], line: Line, lines: list[Line], i: int, slots: dict) -> int:
        if head in _INTS:
            for a in args:
                v, const = _value(a, slots)
                self.emit(struct.pack(_INTS[head], int(v)), line, const)
        elif head in _FLOATS:
            for a in args:
                v, const = _value(a, slots)
                self.emit(struct.pack(_FLOATS[head], float(v)), line, const)
        elif head == "f64bits":
            for a in args:
                v, const = _value(a, slots)
                self.emit(struct.pack("<Q", int(v)), line, const)
        elif head == "hex":
            self.emit(bytes.fromhex("".join(args)), line, True, "hex")
        elif head == "rep":
            n, c1 = _value(args[0], slots)
            b, c2 = _value(args[1] if args[1].startswith(("$", "=", "0x")) else "0x" + args[1], slots)
            self.emit(bytes([int(b)]) * int(n), line, c1 and c2)
        elif head in ("cstr", "astr", "utf8", "utf16", "latin1"):
            v, const = _value(args[0], slots)
            enc = {"cstr": cstring, "astr": astring,
                   "utf8": lambda s: s.encode("utf-8"), "utf16": lambda s: s.encode("utf-16-le"),
                   "latin1": lambda s: s.encode("latin-1")}[head]
            self.emit(enc(str(v)), line, const)
        elif head == "bytes":  # a slot holding bytes (a blob the specification computes elsewhere)
            v, _ = _value(args[0], slots)
            self.emit(bytes(v), line, False)
        elif head == "class":
            name, schema = args[0], int(args[1], 0)
            label = args[3] if len(args) > 3 and args[2] == "as" else None
            if label and label.startswith("$"):
                label = str(_lookup(slots, label[1:]))
            elif label and "%" in label:
                raise self.fail(line, "unbound label")
            self.emit(self.archive.obj(name, schema, label), line, True)
        elif head == "objref":
            label = args[0]
            if label.startswith("$"):
                label = str(_lookup(slots, label[1:]))
            self.emit(struct.pack("<H", self.archive.labels[label]), line, False)
        elif head == "@section":
            self.section = args[0]
        elif head == "@archive":
            if args[0] == "start":
                self.archive.next = int(args[1], 0)
                self.archive.classes.clear()
                self.archive.schemas.clear()
                self.archive.labels.clear()
            elif args[0] == "set":  # @archive set NAME: the current next index as a slot-like value
                slots.setdefault("_archive", {})[args[1]] = self.archive.next
            elif args[0] != "continue":
                raise self.fail(line, "unknown @archive form")
        elif head == "@let":  # @let name =expr  (visible to later lines)
            v, _ = _value(args[1], slots)
            slots[args[0]] = v
        elif head == "@include":
            self.run(load(self.base / args[0]), slots)
        elif head == "@define":
            body, i, _ = self.block(lines, i, "@define", ("@end",))
            self.defs[args[0]] = (args[1:], body)
            i += 1
        elif head == "@use":
            params, body = self.defs[args[0]]
            binds = dict(a.split("=", 1) for a in args[1:])
            missing = [p for p in params if p not in binds]
            if missing:
                raise self.fail(line, f"missing parameters {missing}")
            sub = []
            for bl in body:
                text = bl.text
                for k in sorted(binds, key=len, reverse=True):
                    text = text.replace("%" + k, binds[k])
                sub.append(Line(bl.source, bl.number, text))
            self.run(sub, slots)
        elif head == "@for":  # @for x in $list [reversed]
            var, _in, src, *order = args
            if order not in ([], ["reversed"]):
                raise self.fail(line, "unknown @for form")
            body, i, _ = self.block(lines, i, "@for", ("@endfor",))
            items, _ = _value(src, slots)
            if order:
                items = list(reversed(items))
            for k, item in enumerate(items):
                inner = dict(slots)
                inner[var] = item
                inner[var + "_index"] = k
                self.run(body, inner)
            i += 1
        elif head == "@if":
            cond, _ = _value(args[0], slots)
            then, j, closer = self.block(lines, i, "@if", ("@else", "@endif"))
            other: list[Line] = []
            if closer == "@else":
                other, j, _ = self.block(lines, j + 1, "@if", ("@endif",))
            self.run(then if cond else other, slots)
            i = j + 1
        elif head == "@text":
            opts = dict(a.split("=", 1) for a in args[1:])
            enc = args[0]
            body, i, _ = self.block(lines, i, "@text", ("@endtext",))
            eol = {"lf": "\n", "crlf": "\r\n"}[opts.get("eol", "lf")]
            text = eol.join(bl.text for bl in body)
            if opts.get("final", "yes") == "yes":
                text += eol
            constant = "${" not in text

            def sub(m: re.Match) -> str:  # every text listing is XML: 15.1.2's escaping, & first
                ref = m.group(1)
                value = str(_eval(ref[1:], slots) if ref.startswith("=") else _lookup(slots, ref))
                return (value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                        .replace('"', "&quot;"))

            text = re.sub(r"\$\{([^}]+)\}", sub, text)
            data = text.encode({"utf8": "utf-8", "utf16": "utf-16-le", "latin1": "latin-1"}[enc])
            if opts.get("bom") == "yes":
                data = {"utf8": b"\xef\xbb\xbf", "utf16": b"\xff\xfe"}[enc] + data
            self.emit(data, line, constant)
            i += 1
        elif head == "@zlb":  # @zlb level=N ... @endzlb: the block's bytes in a ZLB wrapper, one chunk
            opts = dict(a.split("=", 1) for a in args)
            body, i, _ = self.block(lines, i, "@zlb", ("@endzlb",))
            inner = _Assembler(self.archive, self.base)
            inner.defs = self.defs
            inner.run(body, slots)
            raw = bytes(inner.out)
            comp = zlib.compress(raw, int(opts.get("level", "1")))
            self.emit(ZLB_MAGIC + struct.pack("<II", len(raw), len(comp)) + comp + b"\0" * 8, line, False)
            i += 1
        elif head == "@sized":  # @sized TYPE NAME ... @endsized: the block's length as TYPE, then the block
            fmt = _INTS[args[0]]
            at = len(self.out)
            self.emit(struct.pack(fmt, 0), line, False)
            body, i, _ = self.block(lines, i, "@sized", ("@endsized",))
            self.run(body, slots)
            size = len(self.out) - at - struct.calcsize(fmt)
            self.out[at : at + struct.calcsize(fmt)] = struct.pack(fmt, size)
            slots[args[1]] = size
            i += 1
        elif head == "@member":
            pass  # a label for readers; the caller picks the member
        else:
            raise self.fail(line, "unknown directive")
        return i


def assemble(source: Path | str | list[Line], slots: dict | None = None,
             archive: Archive | None = None) -> Result:
    """Assemble a listing (a path or parsed lines) with ``slots``. Pass the ``archive`` of
    an earlier listing to continue its load map (``Config-<n>`` then its feature stream)."""
    lines = load(source) if not isinstance(source, list) else source
    base = Path(source).parent if not isinstance(source, list) else LISTINGS
    a = _Assembler(archive or Archive(), base)
    a.run(lines, dict(slots or {}))
    return Result(bytes(a.out), a.runs, a.archive)


def first_difference(result: Result, expected: bytes) -> str | None:
    """None when the assembled bytes are ``expected``; else where they part, by listing line."""
    got = result.data
    if got == expected:
        return None
    common = min(len(got), len(expected))
    n = next((k for k in range(common) if got[k] != expected[k]), common)
    where = next((r for r in result.runs if r.offset <= n < r.offset + r.size), None)
    at = f"{where.source}:{where.line} (section {where.section})" if where else "past the last run"
    return (f"differs at byte {n} of {len(expected)} (assembled {len(got)}), {at}: "
            f"assembled {got[n:n + 16].hex(' ')} expected {expected[n:n + 16].hex(' ')}")


def coverage(result: Result) -> dict[str, int]:
    """Bytes by how the listing gives them: typed constants, opaque hex, slots and expressions."""
    out = {"typed": 0, "hex": 0, "slot": 0}
    for r in result.runs:
        out[r.kind] += r.size
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("listing")
    ap.add_argument("--slots", help="a JSON file of slot values")
    args = ap.parse_args(argv)
    slots = json.loads(Path(args.slots).read_text(encoding="utf-8")) if args.slots else {}
    res = assemble(args.listing, slots)
    for r in res.runs:
        print(f"{r.offset:6d} {r.source}:{r.line:<5d} {res.data[r.offset:r.offset + r.size][:24].hex(' ')}")
    print(f"{len(res.data)} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
