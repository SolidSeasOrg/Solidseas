"""The listing language of section 15.0.3: read a listing into operations, and run them.

A listing (``docs/sldprt-spec/listings/*.srl``) is the specification's own
account of a member's bytes. :func:`parse` turns one into a tuple of
operations, expanding ``@include`` and ``@use`` while it reads (both are
textual, so they never depend on a slot); :func:`run` executes operations with
a slot dict and gives the member's bytes. The generator ships the operations
compiled into :mod:`._listings` by ``scripts/compile-sldprt-spec.py`` and never
reads a listing while it runs.

Every operation is a plain tuple whose last element is its place in the
specification, ``"<section> <file>:<line>"``:

| Operation | Bytes |
|---|---|
| ``("put", TYPE, VALUES, loc)`` | each value as ``TYPE``, a line type of 15.0.3 |
| ``("hex", DIGITS, loc)`` | those bytes |
| ``("rep", N, BYTE, loc)`` | ``BYTE`` N times |
| ``("class", NAME, SCHEMA, LABEL, loc)`` | one MFC object (15.0.4); ``LABEL`` is ``None`` or a value |
| ``("objref", LABEL, loc)`` | a labelled object's archive index |
| ``("if", COND, THEN, ELSE, loc)`` | one of two blocks |
| ``("for", VAR, LIST, REVERSED, BODY, loc)`` | the block once per item |
| ``("sized", TYPE, NAME, BODY, loc)`` | the block's length, then the block |
| ``("zlb", LEVEL, BODY, loc)`` | the block in one ZLB wrapper |
| ``("text", ENC, EOL, FINAL, BOM, LINES, loc)`` | text lines; each line is a tuple of pieces |
| ``("archive", "start" or "continue" or "set", ARG, loc)`` | none: the archive's state |
| ``("let", NAME, VALUE, loc)`` | none: a value for later lines |

A value is a literal (``int``, ``float`` or ``str``), ``("$", path)`` for a
slot or ``("=", text)`` for an expression.

Paths follow README 15.0.2. A dotted path names a slot, a field of it, or an item
of a list by its position from 0 (``$f.corners.0``, ``$f.ring.4.face``). Inside
``@for x in $LIST`` the path ``$x`` is the current item, which is the value itself
when the list holds numbers or texts (``@for i in $b.from`` ... ``u32 $i``), and
``$x_index`` its position in the iteration. A ``@use`` argument is text put in
place of its parameter, so an argument that names an item, ``E=f.ring.0``, gives
``$f.ring.0.end`` where the block says ``$%E.end``.
"""

import ast
import json
import re
import struct
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, is_dataclass
from typing import Any


class ListingError(ValueError):
    """A listing that cannot be read, or that cannot be run with the slots given."""


# ------------------------------------------------------------------ types
# name: (size, signed, byte order)
INT_TYPES = {
    "u8": (1, False, "little"),
    "u16": (2, False, "little"),
    "u32": (4, False, "little"),
    "u64": (8, False, "little"),
    "i8": (1, True, "little"),
    "i16": (2, True, "little"),
    "i32": (4, True, "little"),
    "i64": (8, True, "little"),
    "u16be": (2, False, "big"),
    "u32be": (4, False, "big"),
    "u64be": (8, False, "big"),
}
FLOAT_TYPES = {"f32": "<f", "f64": "<d", "f64be": ">d"}
TEXT_TYPES = ("cstr", "astr", "utf8", "utf16", "latin1")
PUT_TYPES = frozenset(INT_TYPES) | frozenset(FLOAT_TYPES) | frozenset(TEXT_TYPES) | {"f64bits", "bytes"}
ENCODINGS = {"utf8": "utf-8", "utf16": "utf-16-le", "latin1": "latin-1"}
BOMS = {"utf8": b"\xef\xbb\xbf", "utf16": b"\xff\xfe"}  # spec 15.0.3 (@text bom=yes)
EOLS = {"lf": "\n", "crlf": "\r\n"}
ZLB_MAGIC = bytes.fromhex("231DD571DA8148A2A85898B21B89EF99")  # spec 15.0.3 @zlb, FORMAT.md 4.1
CSTRING_MARK = b"\xff\xfe\xff"  # spec 15.0.3 cstr: MFC's Unicode CString mark
BIG_INDEX = 0x7FFF  # spec 15.0.4: archive indices stay below it
CLASS_REF = 0x8000  # spec 15.0.4: a reference to a class already written
NEW_CLASS = b"\xff\xff"  # spec 15.0.4: a class's first object
MAX_DEPTH = 64

_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*")
_SLOT_IN_EXPR = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)")
_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|\S+')
_ARG = re.compile(r'\s*([A-Za-z_][A-Za-z0-9_]*)=("(?:[^"\\]|\\.)*"|\S*)')
_PARAM = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)")
_INTERPOLATION = re.compile(r"\$\{([^}]*)\}")
_HEX_INT = re.compile(r"[+-]?0[xX][0-9A-Fa-f]+")


# ------------------------------------------------------------------ CStrings (15.0.3)
def _length_prefix(n: int) -> bytes:
    """MFC's CString length: one byte below 255, else FF and a u16, else FF FF FF and a u32."""
    if n <= 254:
        return bytes([n])
    if n <= 65534:  # spec 15.0.3 cstr: the u16 form
        return b"\xff" + n.to_bytes(2, "little")  # spec 15.0.3 cstr
    return b"\xff\xff\xff" + n.to_bytes(4, "little")  # spec 15.0.3 cstr


def cstring(text: str) -> bytes:
    """``cstr``: MFC's Unicode CString, length in UTF-16 units, then UTF-16LE."""
    data = text.encode("utf-16-le")
    return CSTRING_MARK + _length_prefix(len(data) // 2) + data


def astring(text: str) -> bytes:
    """``astr``: MFC's narrow CString, the same length forms, then Latin-1."""
    data = text.encode("latin-1")
    return _length_prefix(len(data)) + data


# ------------------------------------------------------------------ expressions
_BINARY = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
}
_UNARY = {ast.USub: lambda a: -a, ast.UAdd: lambda a: +a, ast.Not: lambda a: not a}
_COMPARE = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
}
FUNCTIONS = {"len": len, "min": min, "max": max, "abs": abs, "int": int, "float": float, "round": round}
_EXPRESSIONS: dict[str, tuple[ast.expr, tuple[str, ...]]] = {}


def _check_expr(node: ast.AST, text: str) -> None:
    ok = (
        ast.Constant,
        ast.Name,
        ast.BinOp,
        ast.UnaryOp,
        ast.BoolOp,
        ast.Compare,
        ast.Call,
        ast.Load,
        ast.And,
        ast.Or,
        *_BINARY,
        *_UNARY,
        *_COMPARE,
    )
    for n in ast.walk(node):
        if not isinstance(n, ok):
            raise ListingError(f"expression {text!r}: {type(n).__name__} is not in the listing language")
        if isinstance(n, ast.Constant) and not isinstance(n.value, (int, float, str)):
            raise ListingError(f"expression {text!r}: literal {n.value!r}")
        if isinstance(n, ast.Call) and (
            not isinstance(n.func, ast.Name) or n.func.id not in FUNCTIONS or n.keywords
        ):
            raise ListingError(f"expression {text!r}: only {', '.join(FUNCTIONS)} may be called")
        if isinstance(n, ast.Name) and not (n.id in FUNCTIONS or n.id.startswith("_slot")):
            raise ListingError(f"expression {text!r}: {n.id!r} is neither a slot nor a function")


def compile_expression(text: str) -> tuple[ast.expr, tuple[str, ...]]:
    """An expression's syntax tree and the slot paths it reads (cached by text)."""
    hit = _EXPRESSIONS.get(text)
    if hit is not None:
        return hit
    paths: list[str] = []

    def slot(m: re.Match) -> str:
        paths.append(m.group(1))
        return f"_slot{len(paths) - 1}"

    try:
        tree = ast.parse(_SLOT_IN_EXPR.sub(slot, text), mode="eval").body
    except SyntaxError as e:
        raise ListingError(f"expression {text!r}: {e.msg}") from None
    _check_expr(tree, text)
    _EXPRESSIONS[text] = (tree, tuple(paths))
    return tree, tuple(paths)


def _evaluate(node: ast.expr, slots: list, text: str) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if not node.id.startswith("_slot"):
            raise ListingError(f"expression {text!r}: {node.id} is only called, never read")
        return slots[int(node.id[5:])]
    if isinstance(node, ast.BinOp):
        a, b = _evaluate(node.left, slots, text), _evaluate(node.right, slots, text)
        try:
            return _BINARY[type(node.op)](a, b)
        except (ZeroDivisionError, TypeError) as e:
            raise ListingError(f"expression {text!r}: {e}") from None
    if isinstance(node, ast.UnaryOp):
        return _UNARY[type(node.op)](_evaluate(node.operand, slots, text))
    if isinstance(node, ast.BoolOp):
        is_and = isinstance(node.op, ast.And)
        value = None
        for v in node.values:
            value = _evaluate(v, slots, text)
            if bool(value) != is_and:
                return value
        return value
    if isinstance(node, ast.Compare):
        left = _evaluate(node.left, slots, text)
        for op, right_node in zip(node.ops, node.comparators, strict=True):
            right = _evaluate(right_node, slots, text)
            if not _COMPARE[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Call):
        args = [_evaluate(a, slots, text) for a in node.args]
        try:
            return FUNCTIONS[node.func.id](*args)  # type: ignore[attr-defined]
        except (TypeError, ValueError) as e:
            raise ListingError(f"expression {text!r}: {e}") from None
    raise ListingError(f"expression {text!r}: cannot evaluate")  # _check_expr keeps this out


# ------------------------------------------------------------------ reading a listing
def strip_comment(line: str) -> str:
    """The line without its comment: ``#`` outside a quoted string starts one."""
    quoted = escaped = False
    for i, ch in enumerate(line):
        if quoted:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quoted = False
        elif ch == '"':
            quoted = True
        elif ch == "#":
            return line[:i]
    return line


def parse_value(token: str, where: str = "") -> Any:
    """One value token: a quoted string, ``$slot``, ``=expression`` or a number."""
    if token.startswith('"'):
        try:
            text = json.loads(token)
        except ValueError:
            raise ListingError(f"{where}: bad string {token}") from None
        return text
    if token.startswith("$"):
        if not _PATH.fullmatch(token[1:]):
            raise ListingError(f"{where}: bad slot {token}")
        return ("$", token[1:])
    if token.startswith("="):
        compile_expression(token[1:])
        return ("=", token[1:])
    try:
        return int(token, 10)
    except ValueError:
        pass
    if _HEX_INT.fullmatch(token):
        return int(token, 16)
    try:
        return float(token)
    except ValueError:
        raise ListingError(f"{where}: {token!r} is not a value") from None


def _split(line: str) -> tuple[str, str]:
    parts = line.split(None, 1)
    return (parts[0], parts[1].strip()) if len(parts) > 1 else (parts[0] if parts else "", "")


def _substitute(text: str, params: Mapping[str, str]) -> str:
    return _PARAM.sub(lambda m: params.get(m.group(1), m.group(0)), text)


@dataclass
class _Macro:
    params: tuple[str, ...]
    body: list[tuple[str, str, int]]
    section: str | None


class _Expander:
    """Reads lines, following ``@include``, ``@define`` and ``@use``; leaves the rest in order."""

    def __init__(self, loader: Callable[[str], str]):
        self.loader = loader
        self.macros: dict[str, _Macro] = {}
        self.items: list[tuple[str, str, str, int, str | None]] = []

    def include(self, name: str, section: str | None, depth: int) -> None:
        if depth > MAX_DEPTH:
            raise ListingError(f"{name}: includes nested too deep")
        text = self.loader(name)
        self.expand([(raw, name, n) for n, raw in enumerate(text.splitlines(), 1)], section, None, depth)

    def expand(self, lines, section: str | None, params: Mapping[str, str] | None, depth: int) -> None:
        i = 0
        while i < len(lines):
            raw, f, n = lines[i]
            i += 1
            where = f"{f}:{n}"
            line = strip_comment(raw).strip()
            if params:
                line = _substitute(line, params)
            if not line:
                continue
            word, rest = _split(line)
            if word == "@section":
                section = rest
            elif word == "@define":
                names = rest.split()
                if not names:
                    raise ListingError(f"{where}: @define needs a name")
                body = []
                while True:
                    if i >= len(lines):
                        raise ListingError(f"{where}: @define {names[0]} has no @end")
                    if strip_comment(lines[i][0]).strip() == "@end":
                        i += 1
                        break
                    body.append(lines[i])
                    i += 1
                self.macros[names[0]] = _Macro(tuple(names[1:]), body, section)
            elif word == "@use":
                name, argtext = _split(rest)
                macro = self.macros.get(name)
                if macro is None:
                    raise ListingError(f"{where}: @use of {name!r}, which is not defined")
                args = _use_arguments(argtext, where)
                if set(args) != set(macro.params):
                    raise ListingError(f"{where}: @use {name} takes {', '.join(macro.params) or 'nothing'}")
                if depth > MAX_DEPTH:
                    raise ListingError(f"{where}: @use nested too deep")
                self.expand(macro.body, macro.section, args, depth + 1)
            elif word == "@include":
                self.include(rest, section, depth + 1)
            elif word == "@text":
                self.items.append(("line", line, f, n, section))
                while True:
                    if i >= len(lines):
                        raise ListingError(f"{where}: @text has no @endtext")
                    raw2, f2, n2 = lines[i]
                    i += 1
                    if strip_comment(raw2).strip() == "@endtext":
                        self.items.append(("line", "@endtext", f2, n2, section))
                        break
                    self.items.append(
                        ("text", _substitute(raw2, params) if params else raw2, f2, n2, section)
                    )
            else:
                self.items.append(("line", line, f, n, section))


def _use_arguments(text: str, where: str) -> dict[str, str]:
    args: dict[str, str] = {}
    pos, text = 0, text.rstrip()
    while pos < len(text):
        m = _ARG.match(text, pos)
        if not m:
            raise ListingError(f"{where}: cannot read the @use arguments {text[pos:]!r}")
        args[m.group(1)] = m.group(2)
        pos = m.end()
    return args


class _Builder:
    """Turns the expanded lines into the operation tree."""

    def __init__(self, items, default_section: str | None):
        self.items = items
        self.i = 0
        self.member: str | None = None
        self.default_section = default_section

    def loc(self, f: str, n: int, section: str | None) -> str:
        return f"{section or self.default_section or '15.0.3'} {f}:{n}"

    def values(self, text: str, where: str) -> tuple:
        return tuple(parse_value(t, where) for t in _TOKEN.findall(text))

    def block(self, ends: tuple[str, ...]) -> tuple[tuple, str | None]:
        ops: list[tuple] = []
        while self.i < len(self.items):
            kind, line, f, n, section = self.items[self.i]
            self.i += 1
            loc = self.loc(f, n, section)
            where = f"{f}:{n}"
            if kind != "line":
                raise ListingError(f"{where}: text outside @text")
            word, rest = _split(line)
            if word in ends:
                return tuple(ops), word
            if word == "@if":
                cond = parse_value(rest, where)
                then, end = self.block(("@else", "@endif"))
                other: tuple = ()
                if end == "@else":
                    other, _ = self.block(("@endif",))
                ops.append(("if", cond, then, other, loc))
            elif word == "@for":
                m = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s+in\s+(\S+)(\s+reversed)?", rest)
                if not m:
                    raise ListingError(f"{where}: @for X in $LIST [reversed]")
                body, _ = self.block(("@endfor",))
                ops.append(("for", m.group(1), parse_value(m.group(2), where), bool(m.group(3)), body, loc))
            elif word == "@sized":
                parts = rest.split()
                if len(parts) != 2 or parts[0] not in INT_TYPES:
                    raise ListingError(f"{where}: @sized TYPE NAME")
                body, _ = self.block(("@endsized",))
                ops.append(("sized", parts[0], parts[1], body, loc))
            elif word == "@zlb":
                m = re.fullmatch(r"level=(\d)", rest)
                if not m:
                    raise ListingError(f"{where}: @zlb level=N")
                body, _ = self.block(("@endzlb",))
                ops.append(("zlb", int(m.group(1)), body, loc))
            elif word == "@text":
                ops.append(self.text(rest, where, loc))
            elif word == "@archive":
                parts = rest.split()
                if parts[:1] == ["start"] and len(parts) == 2:
                    ops.append(("archive", "start", parse_value(parts[1], where), loc))
                elif parts == ["continue"]:
                    ops.append(("archive", "continue", None, loc))
                elif parts[:1] == ["set"] and len(parts) == 2:
                    ops.append(("archive", "set", parts[1], loc))
                else:
                    raise ListingError(f"{where}: @archive start N, continue or set NAME")
            elif word == "@let":
                name, _, value = rest.partition(" ")
                if not _PATH.fullmatch(name) or not value.strip():
                    raise ListingError(f"{where}: @let NAME =EXPR")
                ops.append(("let", name, parse_value(value.strip(), where), loc))
            elif word == "@member":
                self.member = rest
            elif word.startswith("@"):
                raise ListingError(f"{where}: {word} is not expected here")
            elif word in PUT_TYPES:
                ops.append(("put", word, self.values(rest, where), loc))
            elif word == "hex":
                digits = "".join(rest.split())
                try:
                    bytes.fromhex(digits)  # spec 15.0.3 hex: checked here, written by run()
                except ValueError:
                    raise ListingError(f"{where}: bad hex {rest!r}") from None
                ops.append(("hex", digits.upper(), loc))
            elif word == "rep":
                parts = rest.split()
                if len(parts) != 2 or not re.fullmatch(r"[0-9A-Fa-f]{2}", parts[1]):
                    raise ListingError(f"{where}: rep N BB")
                ops.append(("rep", int(parts[0]), int(parts[1], 16), loc))
            elif word == "class":
                parts = _TOKEN.findall(rest)
                if len(parts) == 2:
                    label = None
                elif len(parts) == 4 and parts[2] == "as":
                    label = parse_label(parts[3], where)
                else:
                    raise ListingError(f"{where}: class NAME SCHEMA [as LABEL]")
                ops.append(
                    ("class", parts[0], _as_int(parse_value(parts[1], where), "class", where), label, loc)
                )
            elif word == "objref":
                parts = _TOKEN.findall(rest)
                if len(parts) != 1:
                    raise ListingError(f"{where}: objref LABEL")
                ops.append(("objref", parse_label(parts[0], where), loc))
            else:
                raise ListingError(f"{where}: {word!r} is not a line of the listing language")
        if ends:
            raise ListingError(f"the listing ends inside a block that needs {' or '.join(ends)}")
        return tuple(ops), None

    def text(self, options: str, where: str, loc: str) -> tuple:
        parts = options.split()
        if not parts or parts[0] not in ENCODINGS:
            raise ListingError(f"{where}: @text utf8, utf16 or latin1")
        opts = {"eol": "lf", "final": "yes", "bom": "no"}  # spec question: 15.0.3 gives no default eol; lf
        for p in parts[1:]:
            k, _, v = p.partition("=")
            if (
                k not in opts
                or v not in {"eol": ("lf", "crlf"), "final": ("yes", "no"), "bom": ("yes", "no")}[k]
            ):
                raise ListingError(f"{where}: @text option {p!r}")
            opts[k] = v
        if opts["bom"] == "yes" and parts[0] not in BOMS:
            raise ListingError(f"{where}: latin1 text has no byte order mark")
        lines = []
        while True:
            kind, line, f, n, _section = self.items[self.i]
            self.i += 1
            if kind == "line":  # the expander only lets @endtext through here
                break
            lines.append(_text_pieces(line, f"{f}:{n}"))
        return (
            "text",
            parts[0],
            opts["eol"],
            opts["final"] == "yes",
            opts["bom"] == "yes",
            tuple(lines),
            loc,
        )


def parse_label(token: str, where: str) -> Any:
    """A label: a bare name, or a value (``$slot`` or a quoted string) that gives the name."""
    if token.startswith(("$", '"', "=")):
        return parse_value(token, where)
    if not _PATH.fullmatch(token):
        raise ListingError(f"{where}: bad label {token!r}")
    return token


def _text_pieces(line: str, where: str) -> tuple:
    pieces: list[Any] = []
    pos = 0
    for m in _INTERPOLATION.finditer(line):
        if m.start() > pos:
            pieces.append(line[pos : m.start()])
        inner = m.group(1)
        if inner.startswith("="):
            compile_expression(inner[1:])
            pieces.append(("=", inner[1:]))
        elif _PATH.fullmatch(inner):
            pieces.append(("$", inner))
        else:
            raise ListingError(f"{where}: bad interpolation ${{{inner}}}")
        pos = m.end()
    if pos < len(line):
        pieces.append(line[pos:])
    return tuple(pieces)


@dataclass
class Parsed:
    """A listing read into operations: the member it names (``@member``) and its operations."""

    member: str | None
    ops: tuple


def parse(name: str, loader: Callable[[str], str], *, section: str | None = None) -> Parsed:
    """Read listing ``name``; ``loader`` gives the text of it and of every file it includes.

    ``section`` is cited for lines that come before the listing's first ``@section``.
    """
    ex = _Expander(loader)
    ex.include(name, section, 0)
    b = _Builder(ex.items, section)
    ops, _ = b.block(())
    return Parsed(b.member, ops)


def parse_text(text: str, *, files: Mapping[str, str] | None = None, section: str | None = None) -> Parsed:
    """Read a listing given as text; ``files`` holds the texts it may ``@include``."""
    files = dict(files or {})

    def loader(name: str) -> str:
        if name == "<text>":
            return text
        if name not in files:
            raise ListingError(f"@include {name}: not given")
        return files[name]

    return parse("<text>", loader, section=section)


# ------------------------------------------------------------------ running operations
@dataclass
class Archive:
    """One MFC ``CArchive``'s state (15.0.4): its next index, its classes and the labelled objects."""

    next_index: int = 1
    classes: dict[str, int] = field(default_factory=dict)
    labels: dict[str, int] = field(default_factory=dict)


@dataclass
class Result:
    """What :func:`run` gives: the bytes, the archive as the listing left it and, when tracked,
    a mask holding 1 for every byte that came from a value the tracker marks."""

    data: bytes
    archive: Archive | None
    mask: bytes | None = None


class _Missing(LookupError):
    pass


def _descend(value: Any, parts: Sequence[str]) -> Any:
    if not parts:
        return value
    if isinstance(value, Mapping):
        for i in range(len(parts), 0, -1):
            key = ".".join(parts[:i])
            if key in value:
                try:
                    return _descend(value[key], parts[i:])
                except _Missing:
                    continue
        raise _Missing
    if isinstance(value, (list, tuple)) and parts[0].isdigit():
        index = int(parts[0])
        if index >= len(value):
            raise _Missing
        return _descend(value[index], parts[1:])
    if is_dataclass(value) and not isinstance(value, type) and hasattr(value, parts[0]):
        return _descend(getattr(value, parts[0]), parts[1:])
    raise _Missing


def lookup(slots: Mapping, path: str) -> Any:
    """A slot's value by its dotted path, in a flat dict (``"doc.name"``), a nested one, or a mix."""
    try:
        return _descend(slots, path.split("."))
    except _Missing:
        raise KeyError(path) from None


def _as_int(v: Any, typ: str, loc: str) -> int:
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    raise ListingError(f"{loc}: {typ} needs an integer, not {v!r}")


def _as_text(v: Any, typ: str, loc: str) -> str:
    if not isinstance(v, str):
        raise ListingError(f"{loc}: {typ} needs text, not {v!r}")
    return v


def text_value(v: Any) -> str:
    """A value as ``${...}`` writes it: text as it is, numbers in decimal."""
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return str(int(v))
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    raise ListingError(f"{v!r} cannot be written as text")


def xml_escape(text: str) -> str:
    """Section 15.1.2's escaping: ``&`` first, then ``<``, ``>`` and ``"``."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


class _Runner:
    def __init__(self, slots: Mapping, archive: Archive | None, xml: bool, tracker):
        self.slots = slots
        self.previous = archive
        self.archive: Archive | None = None
        self.xml = xml
        self.tracker = tracker  # a predicate on a slot path, or None
        self.buf = bytearray()
        self.mask: bytearray | None = bytearray() if tracker else None
        self.locals: dict[str, Any] = {}
        self.origin: dict[str, str] = {}  # a loop variable: the slot path of its list
        self.marked = False

    # values ---------------------------------------------------------
    def slot_path(self, path: str) -> str:
        """``path`` with a leading loop variable replaced by the slot path of its list.

        A loop over a field of another loop's item (``@for i in $b.from`` inside ``@for b
        in $bodies``) then traces back to the slot it reads, ``bodies.from``.
        """
        parts = path.split(".")
        for i in range(len(parts), 0, -1):
            key = ".".join(parts[:i])
            if key in self.origin:
                return ".".join([self.origin[key], *parts[i:]])
        return path

    def lookup(self, path: str, loc: str) -> Any:
        parts = path.split(".")
        for i in range(len(parts), 0, -1):
            key = ".".join(parts[:i])
            if key in self.locals:
                if self.tracker:
                    base = self.origin.get(key, key)
                    self.marked |= self.tracker(".".join([base, *parts[i:]]))
                try:
                    return _descend(self.locals[key], parts[i:])
                except _Missing:
                    raise ListingError(f"{loc}: ${path} has no such field") from None
        if self.tracker:
            self.marked |= self.tracker(path)
        try:
            return _descend(self.slots, parts)
        except _Missing:
            raise ListingError(f"{loc}: no slot ${path}") from None

    def value(self, node: Any, loc: str) -> Any:
        if isinstance(node, tuple):
            kind, arg = node
            if kind == "$":
                return self.lookup(arg, loc)
            tree, paths = compile_expression(arg)
            return _evaluate(tree, [self.lookup(p, loc) for p in paths], arg)
        return node

    def label(self, node: Any, loc: str) -> str:
        v = self.value(node, loc)
        if isinstance(v, bool) or not isinstance(v, (str, int)):
            raise ListingError(f"{loc}: label {v!r} is not a name")
        return str(v)

    # output ---------------------------------------------------------
    def write(self, data: bytes, marked: bool = False) -> None:
        self.buf += data
        if self.mask is not None:
            self.mask += bytes([marked]) * len(data)

    def put(self, typ: str, node: Any, loc: str) -> None:
        self.marked = False
        v = self.value(node, loc)
        if typ in INT_TYPES:
            size, signed, order = INT_TYPES[typ]
            try:
                data = _as_int(v, typ, loc).to_bytes(size, order, signed=signed)
            except OverflowError:
                raise ListingError(f"{loc}: {v!r} does not fit {typ}") from None
        elif typ in FLOAT_TYPES:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ListingError(f"{loc}: {typ} needs a number, not {v!r}")
            try:
                data = struct.pack(FLOAT_TYPES[typ], float(v))
            except (OverflowError, struct.error):
                raise ListingError(f"{loc}: {v!r} does not fit {typ}") from None
        elif typ == "f64bits":
            try:
                data = _as_int(v, typ, loc).to_bytes(8, "little")
            except OverflowError:
                raise ListingError(f"{loc}: {v!r} is not a 64-bit pattern") from None
        elif typ == "cstr":
            self.write(CSTRING_MARK)  # the mark is the same for every value
            data = cstring(_as_text(v, typ, loc))[len(CSTRING_MARK) :]
        elif typ == "astr":
            data = astring(_as_text(v, typ, loc))
        elif typ in ENCODINGS:
            data = _as_text(v, typ, loc).encode(ENCODINGS[typ])
        elif isinstance(v, (bytes, bytearray, memoryview)):
            data = bytes(v)
        else:
            raise ListingError(f"{loc}: bytes needs a bytes slot, not {v!r}")
        self.write(data, self.marked)

    def need_archive(self) -> Archive:
        if self.archive is None:
            self.archive = Archive(1)  # MFC's first index when no @archive start is given (15.0.4)
        return self.archive

    # operations -----------------------------------------------------
    def run(self, ops: tuple) -> None:
        for op in ops:
            kind, loc = op[0], op[-1]
            if kind == "put":
                for node in op[2]:
                    self.put(op[1], node, loc)
            elif kind == "hex":
                self.write(bytes.fromhex(op[1]))  # spec 15.0.3 hex
            elif kind == "rep":
                self.write(bytes([op[2]]) * op[1])
            elif kind == "class":
                self.class_object(op[1], op[2], op[3], loc)
            elif kind == "objref":
                a = self.need_archive()
                name = self.label(op[1], loc)
                if name not in a.labels:
                    raise ListingError(f"{loc}: objref {name!r} names no labelled object")
                self.write(a.labels[name].to_bytes(2, "little"))
            elif kind == "if":
                self.run(op[2] if self.value(op[1], loc) else op[3])
            elif kind == "for":
                self.loop(op[1], op[2], op[3], op[4], loc)
            elif kind == "sized":
                data, mask = self.capture(op[3])
                size, signed, order = INT_TYPES[op[1]]
                try:
                    self.write(len(data).to_bytes(size, order, signed=signed))
                except OverflowError:
                    raise ListingError(f"{loc}: {len(data)} bytes do not fit {op[1]}") from None
                self.append(data, mask)
                self.locals[op[2]] = len(data)
            elif kind == "zlb":
                data, mask = self.capture(op[2])
                packed = zlib.compress(data, op[1])
                body = len(data).to_bytes(4, "little") + len(packed).to_bytes(4, "little") + packed
                self.write(ZLB_MAGIC + body + bytes(8), bool(mask and any(mask)))
            elif kind == "text":
                self.text(op, loc)
            elif kind == "archive":
                if op[1] == "start":
                    self.archive = Archive(_as_int(self.value(op[2], loc), "@archive start", loc))
                elif op[1] == "continue":
                    if self.previous is None:
                        raise ListingError(f"{loc}: @archive continue with no archive left by a listing")
                    self.archive = self.previous
                else:
                    self.locals["_archive." + op[2]] = self.need_archive().next_index
            elif kind == "let":
                self.locals[op[1]] = self.value(op[2], loc)
            else:
                raise ListingError(f"{loc}: unknown operation {kind!r}")

    def class_object(self, name: str, schema: int, label: Any, loc: str) -> None:
        a = self.need_archive()
        index = a.classes.get(name)
        if index is None:
            raw = name.encode("ascii")
            self.write(NEW_CLASS + schema.to_bytes(2, "little") + len(raw).to_bytes(2, "little") + raw)
            a.classes[name] = a.next_index
            a.next_index += 1
        else:
            self.write((CLASS_REF | index).to_bytes(2, "little"))
        if a.next_index >= BIG_INDEX:
            raise ListingError(f"{loc}: the archive outgrew the 16-bit indices of 15.0.4")
        if label is not None:
            a.labels[self.label(label, loc)] = a.next_index
        a.next_index += 1

    def loop(self, var: str, listnode: Any, backwards: bool, body: tuple, loc: str) -> None:
        items = self.value(listnode, loc)
        if isinstance(items, (str, bytes)) or not isinstance(items, Sequence):
            raise ListingError(f"{loc}: @for needs a list, not {items!r}")
        index_name = var + "_index"
        saved = {k: self.locals[k] for k in (var, index_name) if k in self.locals}
        saved_origin = self.origin.get(var)
        if isinstance(listnode, tuple) and listnode[0] == "$":
            self.origin[var] = self.slot_path(listnode[1])
        order = list(reversed(items)) if backwards else list(items)
        for i, item in enumerate(order):
            self.locals[var] = item
            self.locals[index_name] = i
            self.run(body)
        for k in (var, index_name):
            self.locals.pop(k, None)
        self.locals.update(saved)
        if saved_origin is None:
            self.origin.pop(var, None)
        else:
            self.origin[var] = saved_origin

    def capture(self, body: tuple) -> tuple[bytes, bytes | None]:
        outer, outer_mask = self.buf, self.mask
        self.buf = bytearray()
        self.mask = bytearray() if outer_mask is not None else None
        try:
            self.run(body)
            return bytes(self.buf), (bytes(self.mask) if self.mask is not None else None)
        finally:
            self.buf, self.mask = outer, outer_mask

    def append(self, data: bytes, mask: bytes | None) -> None:
        self.buf += data
        if self.mask is not None and mask is not None:
            self.mask += mask

    def text(self, op: tuple, loc: str) -> None:
        _, enc, eol, final, bom, lines, _loc = op
        codec = ENCODINGS[enc]
        if bom:
            self.write(BOMS[enc])
        newline = EOLS[eol].encode(codec)
        for n, line in enumerate(lines):
            if n:
                self.write(newline)
            for piece in line:
                if isinstance(piece, str):
                    self.write(piece.encode(codec))
                    continue
                self.marked = False
                text = text_value(self.value(piece, loc))
                self.write((xml_escape(text) if self.xml else text).encode(codec), self.marked)
        if final and lines:
            self.write(newline)


def run(
    ops: tuple,
    slots: Mapping,
    *,
    archive: Archive | None = None,
    xml: bool = False,
    tracker: Callable[[str], bool] | None = None,
) -> Result:
    """Run ``ops`` with ``slots``.

    ``archive`` is the archive the previous listing left, for ``@archive continue``.
    ``xml`` escapes every ``${...}`` of a text block (15.1.2). ``tracker``, when given,
    is called with the path of every slot read; the bytes of a value that read a slot
    it returns true for are marked in :attr:`Result.mask`.
    """
    r = _Runner(slots, archive, xml, tracker)
    r.run(ops)
    return Result(bytes(r.buf), r.archive, bytes(r.mask) if r.mask is not None else None)
