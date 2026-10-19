"""Parasolid transmit files: ``.x_t``, ``.x_b``, ``.xmt_txt`` and ``.xmt_bin`` (provisional,
``docs/formats/parasolid.md``).

A transmit file is an optional common header of ``keyword=value;`` records, then
one transmit in text (flag ``T``) or neutral binary (flag ``PS\\0\\0``), as the
publicly published Parasolid XT Format Reference describes them. The transmit is
read with the reader SolidSeas already has for the transmits inside SOLIDWORKS
documents (:mod:`solidseas.formats.solidworks.parasolid`, given the call's clock so
a parse keeps its deadline) and drawn with :mod:`solidseas.tessellate`.

The head (what a folder listing reads) is the common header and the first bytes
of the transmit: its modeller and schema strings and the type of its first node,
the root. The transmit itself is parsed only when the tree, the scene or the
bodies are asked for, at most ``xt_transmit_bytes`` of it, once.

A transmit holds one part: a BODY, or an ASSEMBLY whose INSTANCEs place bodies
and other assemblies by their TRANSFORMs (``x' = (R x + t) s``); a partition
(root WORLD) holds every part of a session. The document's ``doc_type`` is
``assembly`` when the root is an ASSEMBLY, and ``part`` otherwise. Each body
reached from the root is one mesh object, tessellated once and placed by every
instance path that reaches it. Instance paths are never stored: a few instances
can place a part billions of times, so the tree and the scene walk them one at a
time and a scene counts them, assembly by assembly, before it places any.
Colours come from the system attribute ``SDL/TYSA_COLOUR`` (the colour most of a
body's faces show, each face its own colour or else its body's) and names from
``SDL/TYSA_NAME`` and, for bodies SOLIDWORKS wrote, ``SWIMPLICITBODYNAME_ID_U``.

Refused with :class:`~solidseas.errors.FormatNotSupportedError`: a transmit that
does not embed its schema over the base SCH_13006 (rule
``schema_not_embedded``), a bare (platform) binary transmit (``bare_binary``), a
transmit with user fields (``user_fields``) and a deltas transmit
(``unsupported_variant``).
"""

import math
import struct
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import replace
from typing import Any

from ..errors import FormatNotSupportedError, SldFormatError, SldLimitError
from ._source import Clock, clip_text
from .base import (
    BodyRef,
    ModelDocument,
    ModelNode,
    ModelTree,
    Scene,
    SceneBuilder,
    _stem,
    _Truncated,
    make_property,
)
from .solidworks.components import IDENTITY, Placement
from .solidworks.parasolid import (
    BODY_TYPES,
    NULL_DOUBLE,
    Node,
    XtTransmit,
    parse_binary,
    parse_text,
)

REVISION = 1

ASSEMBLY, INSTANCE, BODY, SHELL, FACE = 10, 11, 12, 13, 14
ATTRIB_DEF, ATTRIBUTE, TRANSFORM, WORLD = 80, 81, 100, 101
INT_VALUES, REAL_VALUES, CHAR_VALUES, UNICODE_VALUES, ATT_DEF_ID = 82, 83, 84, 98, 79
BASE_SCHEMA = 13006
PREAMBLE = b"**ABCDEFGHIJ"
END_OF_HEADER = b"**END_OF_HEADER"
PEEK_BYTES = 4096  # the transmit's own header and first node type lie in its first bytes
COLOUR = "SDL/TYSA_COLOUR"
NAME = "SDL/TYSA_NAME"
SOLIDWORKS_BODY_NAME = "SWIMPLICITBODYNAME_ID_U"
_PARTS = ("**PART1;", "**PART2;", "**PART3;")
_UNSET = ("", "unknown")
# A display scene's tessellation stops this share of its time (at most this many seconds)
# before the scene's deadline, so the faces done can still be made into meshes.
DISPLAY_MARGIN = 0.15
DISPLAY_MARGIN_SECONDS = 2.0
# A bodies scene (the export) gives the tessellation all of its time, but its pass over
# the rolling blends, done last, ends this share of it (at most this many seconds) before
# the deadline: blends the time runs out on are left out, and the meshes of the rest can
# still be made in time.
BLEND_MARGIN = 0.1
BLEND_MARGIN_SECONDS = 2.0
# A transform whose determinant is no more than this share of the cube of its size (1 for
# a turn at any scale) flattens what it places: it is left out, not drawn as a sliver.
SINGULAR = 1e-9
# bodies() copies each body out with what it reaches. Bodies share only attribute
# definitions, so the copies hold about the transmit's own nodes; this many times them, and
# this many more, are allowed in all before the transmit is refused (limit xt_nodes).
COPY_FACTOR = 2
COPY_SLACK = 100_000
_SATURATE = 1 << 62  # path counts stop growing here (a few instances can multiply past any bound)


# --------------------------------------------------------------------------- the common header
def _unescape(value: str) -> str:
    """A header value with its escapes (``^n``, ``^_``, ``^;``, ``^^``) undone."""
    if "^" not in value:
        return value
    out = []
    i, n = 0, len(value)
    while i < n:
        c = value[i]
        if c == "^" and i + 1 < n:
            e = value[i + 1]
            out.append({"n": "\n", "_": " ", ";": ";", "^": "^"}.get(e, e))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _records(text: str) -> list[str]:
    """The ``;``-terminated records of a header part, an escaped ``^;`` kept inside its
    record (the escapes are undone later)."""
    out = []
    start = 0
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "^":
            i += 2
            continue
        if c == ";":
            out.append(text[start:i])
            start = i + 1
        i += 1
    tail = text[start:].strip("*").strip()
    if tail:
        out.append(tail)
    return out


def parse_header(raw: bytes) -> tuple[list[tuple[str, str, str]], int]:
    """The keywords of a common header (the bytes before ``**END_OF_HEADER``): a list of
    ``(part, keyword, value)``, part ``PART1``, ``PART2`` or ``PART3``, and the number of
    records that are not ``keyword=value``. Record breaks are not significant (an escape
    may be split by one), so they are removed first."""
    text = raw.decode("latin-1").replace("\r", "").replace("\n", "")
    first = text.find(_PARTS[0])
    if first < 0:
        return [], 1
    text = text[first:]
    out: list[tuple[str, str, str]] = []
    bad = 0
    marks = [(text.find(p), p) for p in _PARTS]
    marks = sorted((pos, p) for pos, p in marks if pos >= 0)
    for k, (pos, p) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(text)
        body = text[pos + len(p) : end]
        for rec in _records(body):
            rec = rec.strip()
            if not rec:
                continue
            name, eq, value = rec.partition("=")
            name = name.strip()
            if not eq or not name or len(name) > 80 or not all(c.isalnum() or c == "_" for c in name):
                bad += 1
                continue
            out.append((p.strip("*;"), name, _unescape(value)))
    return out, bad


# --------------------------------------------------------------------------- the transmit's own header
class _Peek:
    """What the first bytes of a transmit say: ``flag`` (``text``, ``binary`` or ``bare``),
    ``modeller``, ``schema``, ``base``, ``usfld`` and ``root`` (the first node's type)."""

    def __init__(self) -> None:
        self.flag = ""
        self.modeller = ""
        self.schema = ""
        self.base: int | None = None
        self.usfld = 0
        self.root: int | None = None

    @property
    def kind(self) -> str:
        if "(deltas)" in self.modeller:
            return "deltas"
        if "(partition)" in self.modeller:
            return "partition"
        return "part"

    @property
    def modeller_version(self) -> int | None:
        tail = self.modeller.rsplit(" ", 1)[-1]
        return int(tail) if tail.isdigit() else None

    def schema_base(self) -> None:
        parts = self.schema.split("_")
        if len(parts) >= 4 and parts[0] == "SCH" and parts[3].isdigit():
            self.base = int(parts[3])


class _Text:
    """Tokens of a text transmit, as the reference writes them: numbers ended by one
    space, strings as a length and that many characters (``\\`` escapes)."""

    def __init__(self, s: str) -> None:
        self.s, self.p = s, 0

    def ch(self) -> str:
        if self.p >= len(self.s):
            raise SldFormatError("the text transmit ends inside its header")
        c = self.s[self.p]
        self.p += 1
        if c == "\\" and self.p < len(self.s):
            self.p += 1
        return c

    def int(self) -> int:
        j = self.s.find(" ", self.p)
        if j < 0 or j - self.p > 20:
            raise SldFormatError("the text transmit's header is not readable")
        tok = self.s[self.p : j]
        self.p = j + 1
        try:
            return int(tok)
        except ValueError:
            raise SldFormatError("the text transmit's header is not readable") from None

    def string(self) -> str:
        n = self.int()
        if not 0 <= n <= 1024:
            raise SldFormatError("the text transmit's header is not readable")
        return "".join(self.ch() for _ in range(n))


def peek_transmit(data: bytes) -> _Peek:
    """The transmit's own header and the type of its first node, from its first bytes
    (see :class:`_Peek`)."""
    pk = _Peek()
    lead = data.lstrip(b" \r\n")
    if data.startswith(b"PS"):
        if not data.startswith(b"PS\0\0"):
            raise SldFormatError("the binary transmit's flag is not PS followed by two zero bytes")
        pk.flag = "binary"
        short = SldFormatError("the binary transmit ends inside its header")
        try:
            p = 4
            (ml,) = struct.unpack_from(">h", data, p)
            p += 2
            if not 0 < ml < 1024:
                raise SldFormatError("the binary transmit's modeller string has a bad length")
            if p + ml > len(data):
                raise short
            pk.modeller = data[p : p + ml].decode("latin-1")
            p += ml
            (sl,) = struct.unpack_from(">i", data, p)
            p += 4
            if not 0 < sl < 1024:
                raise SldFormatError("the binary transmit's schema string has a bad length")
            if p + sl > len(data):
                raise short
            pk.schema = data[p : p + sl].decode("latin-1")
            p += sl
            parts = pk.schema.split("_")
            if len(parts) >= 4 and parts[0] == "SCH":
                p += 2  # the highest node type
            (pk.usfld,) = struct.unpack_from(">i", data, p)
            p += 4
            (pk.root,) = struct.unpack_from(">H", data, p)
        except struct.error:
            raise short from None
    elif lead.startswith(b"T"):
        pk.flag = "text"
        text = lead.decode("latin-1").replace("\r", "")
        joined = "".join(ln.rstrip(" ") for ln in text.split("\n"))
        r = _Text(joined)
        r.p = 1
        pk.modeller = r.string()
        pk.schema = r.string()
        parts = pk.schema.split("_")
        if len(parts) >= 4 and parts[0] == "SCH" and parts[3].isdigit():
            r.int()  # the highest node type
        pk.usfld = r.int()
        pk.root = r.int()
    elif lead.startswith(b"B"):
        pk.flag = "bare"
        return pk
    else:
        raise SldFormatError("the file holds no Parasolid transmit: no text or binary flag")
    pk.schema_base()
    return pk


# --------------------------------------------------------------------------- reading nodes
class _Fields:
    """Field access by name over one transmit, through its own schema (later schemas add
    fields), never raising: a field the schema lacks is ``default``."""

    def __init__(self, xt: XtTransmit) -> None:
        self.xt = xt
        self.idx = xt.by_index()
        self.pos: dict[tuple[int, str], int] = {}
        for t, lay in xt.layouts.items():
            for i, f in enumerate(lay):
                self.pos.setdefault((t, f[0]), i)

    def get(self, node: Node, name: str, default: Any = None) -> Any:
        i = self.pos.get((node.type, name))
        if i is None or i >= len(node.vals):
            return default
        return node.vals[i]

    def ref(self, node: Node, name: str, types: tuple[int, ...] | None = None) -> Node | None:
        v = self.get(node, name, 0)
        if not isinstance(v, int) or not v:
            return None
        target = self.idx.get(v)
        if target is None or (types is not None and target.type not in types):
            return None
        return target


def _text_of(f: _Fields, node: Node | None) -> str | None:
    """The text a CHAR_VALUES, UNICODE_VALUES or ATT_DEF_ID node holds."""
    if node is None:
        return None
    if node.type in (CHAR_VALUES, ATT_DEF_ID):
        v = f.get(node, "values" if node.type == CHAR_VALUES else "string")
        if not isinstance(v, str):
            return None
        if node.type == CHAR_VALUES and any(c >= "\x80" for c in v):
            # A string is bytes: one that is valid UTF-8 (as SolidSeas writes a name
            # outside ASCII) is read as UTF-8, any other as Latin-1.
            try:
                return v.encode("latin-1").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                return v
        return v
    if node.type == UNICODE_VALUES:
        v = f.get(node, "values")
        if not isinstance(v, list) or not all(isinstance(c, int) and 0 <= c < 0x10000 for c in v):
            return None
        return struct.pack(f">{len(v)}H", *v).decode("utf-16-be", "replace")
    return None


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    text = "".join(c if c >= " " else " " for c in text.split("\0", 1)[0]).strip()
    return text or None


def _colour_of(f: _Fields, node: Node | None) -> tuple[float, float, float, float] | None:
    if node is None or node.type != REAL_VALUES:
        return None
    v = f.get(node, "values")
    if not isinstance(v, list) or len(v) < 3:
        return None
    r, g, b = v[:3]
    if not all(isinstance(c, float) and math.isfinite(c) and 0.0 <= c <= 1.0 for c in (r, g, b)):
        return None
    return (r, g, b, 1.0)


def _placement(f: _Fields, tf: Node | None) -> Placement | None:
    """An instance's TRANSFORM as a :class:`Placement`: ``x' = (R x + t) s`` with R the
    nine stored numbers row by row (the reference's ``rotation_matrix . x``); None when a
    value is unset or not a number. No transform is the identity."""
    if tf is None:
        return IDENTITY
    m = f.get(tf, "rotation_matrix")
    t = f.get(tf, "translation_vector")
    s = f.get(tf, "scale", 1.0)
    if s == NULL_DOUBLE:
        s = 1.0
    if not (isinstance(m, list) and len(m) == 9 and isinstance(t, tuple) and len(t) == 3):
        return None
    values = [*m, *t, s]
    if not all(isinstance(x, (int, float)) and math.isfinite(x) and x != NULL_DOUBLE for x in values):
        return None
    s = float(s)
    rot = tuple(tuple(float(m[3 * i + j]) * s for j in range(3)) for i in range(3))
    return Placement(rot, tuple(float(x) * s for x in t))  # type: ignore[arg-type]


def _is_identity(pl: Placement, tol: float = 1e-12) -> bool:
    return all(
        abs(pl.rotation[i][j] - (1.0 if i == j else 0.0)) <= tol for i in range(3) for j in range(3)
    ) and all(abs(x) <= tol for x in pl.translation_m)


def bodies_in_place(xt: XtTransmit) -> bool:
    """True when the transmit's one assembly only gathers its bodies where they are:
    every instance is a positive one placing a body at the identity, each body is placed
    once and no body is left out. SOLIDWORKS writes a multi-body part's .x_b this way,
    so its bodies are one part's, not the parts of an assembly."""
    f = _Fields(xt)
    assemblies = [n for n in xt.nodes if n.type == ASSEMBLY]
    instances = [n for n in xt.nodes if n.type == INSTANCE]
    bodies = {n.index for n in xt.nodes if n.type == BODY}
    if len(assemblies) != 1 or not instances or not bodies:
        return False
    placed: list[int] = []
    for it in instances:
        part = f.ref(it, "part", (BODY, ASSEMBLY))
        if part is None or part.type != BODY or f.get(it, "type", 1) != 1:
            return False
        tf = f.ref(it, "transform", (TRANSFORM,))
        if tf is None and f.get(it, "transform", 0):
            return False
        pl = _placement(f, tf)
        if pl is None or not _is_identity(pl):
            return False
        placed.append(part.index)
    return len(placed) == len(set(placed)) and set(placed) == bodies


def _then(outer: Placement, inner: Placement) -> Placement:
    """``outer.then(inner)`` without its generators, with the same sums (``sum`` rounds
    differently from ``+`` since Python 3.12) and so the same bits: a scene composes one
    for every instance path."""
    (a0, a1, a2), (a3, a4, a5), (a6, a7, a8) = outer.rotation
    (b0, b1, b2), (b3, b4, b5), (b6, b7, b8) = inner.rotation
    x, y, z = inner.translation_m
    tx, ty, tz = outer.translation_m
    r0 = sum((a0 * b0, a1 * b3, a2 * b6)), sum((a0 * b1, a1 * b4, a2 * b7)), sum((a0 * b2, a1 * b5, a2 * b8))
    r1 = sum((a3 * b0, a4 * b3, a5 * b6)), sum((a3 * b1, a4 * b4, a5 * b7)), sum((a3 * b2, a4 * b5, a5 * b8))
    r2 = sum((a6 * b0, a7 * b3, a8 * b6)), sum((a6 * b1, a7 * b4, a8 * b7)), sum((a6 * b2, a7 * b5, a8 * b8))
    t = (a0 * x + a1 * y + a2 * z + tx, a3 * x + a4 * y + a5 * z + ty, a6 * x + a7 * y + a8 * z + tz)
    return Placement((r0, r1, r2), t)


def _degenerate(rot) -> bool:
    """True when the 3 by 3 ``rot`` (a rotation times its scale) flattens space: its
    determinant is zero, or tiny beside the cube of its size, or too large to compute.
    A turn, a mirror or a uniform scale gives a ratio of 1."""
    (a, b, c), (d, e, g), (h, i, k) = rot
    det = a * (e * k - g * i) - b * (d * k - g * h) + c * (d * i - e * h)
    size = (a * a + b * b + c * c + d * d + e * e + g * g + h * h + i * i + k * k) / 3.0
    if not (math.isfinite(det) and math.isfinite(size)) or size == 0.0:
        return True
    return abs(det) <= SINGULAR * size**1.5


# one instance of an assembly: its place in the assembly's chain (from 1), the INSTANCE,
# the part it places and its placement
_Child = tuple[int, Node, Node, Placement]
# one instance path: id, parent id, INSTANCE (None for a top-level part), part, placement
# relative to the parent, placement in the model (when asked for)
_Path = tuple[str, str | None, Node | None, Node, Placement | None, Placement | None]


class _Structure:
    """The parts of one parsed transmit: the top-level parts, every assembly's instances
    (the parts they place, or why they are left out), the bodies reached (the scene's
    objects, in node order), names and colours. Instance paths are not stored: a handful
    of instances can place a part billions of times. :meth:`walk` gives the paths one at a
    time, and :meth:`count` the paths a scene would place, assembly by assembly."""

    def __init__(self, xt: XtTransmit, limits, clock: Clock, warnings: list) -> None:
        f = self.f = _Fields(xt)
        self.limits = limits
        self.warnings = warnings
        root = f.idx.get(1)
        if root is None:
            raise SldFormatError("the transmit has no root node (index 1)")
        self.root = root
        instances = [n for n in xt.nodes if n.type == INSTANCE]
        self.n_instances = len(instances)
        placed = set()
        for inst in instances:
            part = f.ref(inst, "part", (BODY, ASSEMBLY))
            if part is not None:
                placed.add(part.index)
        if root.type in (BODY, ASSEMBLY):
            self.tops = [root]
        else:  # a partition (WORLD) or another root: every part no instance places
            self.tops = [n for n in xt.nodes if n.type in (BODY, ASSEMBLY) and n.index not in placed]
        self._attributes(xt, clock)
        single = len(self.tops) == 1
        self.top_ids = [("1" if single else str(k), top) for k, top in enumerate(self.tops, 1)]
        self.children: dict[int, list[_Child]] = {}
        self.skips: dict[int, list[tuple[int, str, str]]] = {}
        self._assemblies(clock)
        self._order(clock)
        self.too_deep = max((self._height(t) for t in self.tops), default=0) > limits.depth
        self.first_node = self._first_nodes(clock)
        self.bodies = [n for n in xt.nodes if n.type == BODY and n.index in self.first_node]
        self.object_of = {b.index: k for k, b in enumerate(self.bodies)}

    # -- attributes
    def _attributes(self, xt: XtTransmit, clock: Clock) -> None:
        f = self.f
        names: dict[int, str | None] = {}
        self.names: dict[int, str] = {}
        self.body_names: dict[int, str] = {}
        face_colour: dict[int, tuple] = {}
        own_colour: dict[int, tuple] = {}
        for nd in xt.nodes:
            clock.tick()
            if nd.type != ATTRIBUTE:
                continue
            d = f.ref(nd, "definition", (ATTRIB_DEF,))
            owner = f.ref(nd, "owner")
            if d is None or owner is None:
                continue
            if d.index not in names:
                names[d.index] = _text_of(f, f.ref(d, "identifier", (ATT_DEF_ID,)))
            what = names[d.index]
            fields = f.get(nd, "fields")
            first = f.idx.get(fields[0]) if isinstance(fields, list) and fields and fields[0] else None
            if what == COLOUR:
                c = _colour_of(f, first)
                if c is None:
                    continue
                if owner.type == BODY:
                    own_colour[owner.index] = c
                elif owner.type == FACE:
                    face_colour[owner.index] = c
            elif what == NAME:
                text = _clean(_text_of(f, first))
                if text:
                    self.names[owner.index] = clip_text(text, self.limits, self.warnings, "a name")
            elif what == SOLIDWORKS_BODY_NAME and owner.type == BODY:
                text = _clean(_text_of(f, first))
                if text:
                    self.body_names[owner.index] = clip_text(text, self.limits, self.warnings, "a name")
        # Each face shows its own colour, else its body's; a body is drawn in the colour most
        # of its faces show (no colour, when most show none), first seen first on a tie.
        votes: dict[int, Counter] = {}
        for nd in xt.nodes:
            clock.tick()
            if nd.type != FACE:
                continue
            shell = f.ref(nd, "shell", (SHELL,))
            body = f.ref(shell, "body", (BODY,)) if shell is not None else None
            if body is not None:
                c = face_colour.get(nd.index) or own_colour.get(body.index)
                votes.setdefault(body.index, Counter())[c] += 1
        self.colours: dict[int, tuple] = {b: c for b, c in own_colour.items() if b not in votes}
        self.mixed = 0
        for body, counts in votes.items():
            ranked = counts.most_common()
            if ranked[0][0] is not None:
                self.colours[body] = ranked[0][0]
            if len(ranked) > 1:
                self.mixed += 1

    def name(self, node: Node) -> str | None:
        return self.names.get(node.index) or (self.body_names.get(node.index) if node.type == BODY else None)

    # -- instances
    def _assemblies(self, clock: Clock) -> None:
        """Every assembly reached from the top-level parts, with its instances in chain
        order: those placed (``children``) and those left out, with why (``skips``). An
        instance in the chains of two assemblies is damage (no file has one, and each
        assembly would read every instance of the other)."""
        f = self.f
        chain_of: dict[int, int] = {}
        todo = [t for t in self.tops if t.type == ASSEMBLY]
        while todo:
            asm = todo.pop()
            if asm.index in self.children:
                continue
            kids: list[_Child] = []
            skips: list[tuple[int, str, str]] = []
            self.children[asm.index], self.skips[asm.index] = kids, skips
            n = 0
            it = f.ref(asm, "sub_instance", (INSTANCE,))
            while it is not None:
                clock.tick()
                held = chain_of.get(it.index)
                if held == asm.index:
                    break  # the chain comes back on itself: it ends there
                if held is not None:
                    raise SldFormatError("an instance of the transmit is in the instances of two assemblies")
                chain_of[it.index] = asm.index
                n += 1
                part, where = self._instance(it)
                if isinstance(part, str):
                    skips.append((n, part, str(where)))
                else:
                    kids.append((n, it, part, where))  # type: ignore[arg-type]
                    if part.type == ASSEMBLY and part.index not in self.children:
                        todo.append(part)
                it = f.ref(it, "next_in_part", (INSTANCE,))

    def _instance(self, it: Node) -> tuple[Node, Placement] | tuple[str, str]:
        """What one instance places and where, or why it is left out (a reason and a message)."""
        f = self.f
        child = f.ref(it, "part", (BODY, ASSEMBLY))
        if child is None:
            return "bad_reference", "the instance places no body or assembly"
        if f.get(it, "type", 1) != 1:
            return "negative_instance", "a negative instance is not drawn"
        tf = f.ref(it, "transform", (TRANSFORM,))
        if tf is None and f.get(it, "transform", 0):
            return "bad_reference", "the instance's transform is not a TRANSFORM"
        pl = _placement(f, tf)
        if pl is None:
            return "non_finite_placement", "its transform holds an unset value"
        if _degenerate(pl.rotation):
            return "degenerate_placement", "its transform flattens what it places to a plane, line or point"
        return child, pl

    def _order(self, clock: Clock) -> None:
        """Refuse an assembly that contains itself; then, children first, each assembly's
        height (its levels, itself included) and number of paths (itself and every path
        under it, at most ``_SATURATE``)."""
        state: dict[int, bool] = {}  # False while on the stack, True when done
        self.post: list[int] = []
        for top in self.tops:
            if top.type != ASSEMBLY or top.index in state:
                continue
            state[top.index] = False
            stack = [(top.index, 0)]
            while stack:
                clock.tick()
                a, k = stack[-1]
                kids = self.children[a]
                if k == len(kids):
                    stack.pop()
                    state[a] = True
                    self.post.append(a)
                    continue
                stack[-1] = (a, k + 1)
                c = kids[k][2]
                if c.type != ASSEMBLY:
                    continue
                s = state.get(c.index)
                if s is False:
                    raise SldFormatError("an assembly of the transmit contains itself")
                if s is None:
                    state[c.index] = False
                    stack.append((c.index, 0))
        self.height: dict[int, int] = {}
        self.paths: dict[int, int] = {}
        for a in self.post:
            clock.tick()
            h = p = 1
            for _n, _it, c, _pl in self.children[a]:
                if c.type == ASSEMBLY:
                    h = max(h, self.height[c.index] + 1)
                    p += self.paths[c.index]
                else:
                    h = max(h, 2)
                    p += 1
            self.height[a] = h
            self.paths[a] = min(p, _SATURATE)

    def _height(self, part: Node) -> int:
        return self.height[part.index] if part.type == ASSEMBLY else 1

    def components(self) -> int:
        """The instance paths (every tree node but the top-level ones), at most ``_SATURATE``."""
        return min(sum(self.paths[t.index] - 1 for t in self.tops if t.type == ASSEMBLY), _SATURATE)

    def _first_nodes(self, clock: Clock) -> dict[int, str]:
        """The first tree node of each body reached within ``depth``, in tree order. An
        assembly is opened again only at a level above any it was opened at before (the
        bodies under it were all met the first time), so this costs at most ``depth``
        passes over the instances, however many paths they make."""
        lim = self.limits
        first: dict[int, str] = {}
        best: dict[int, int] = {}
        stack = [(pid, top, 1) for pid, top in reversed(self.top_ids)]
        while stack:
            clock.tick()
            pid, part, d = stack.pop()
            if part.type == BODY:
                first.setdefault(part.index, pid)
                continue
            if d >= lim.depth or best.get(part.index, lim.depth + 1) <= d:
                continue
            best[part.index] = d
            for n, _it, child, _pl in reversed(self.children[part.index]):
                stack.append((f"{pid}.{n}", child, d + 1))
        return first

    def count(self, wanted: set[int]) -> tuple[int, int, dict[int, tuple[int, int]]]:
        """For a scene of the bodies ``wanted`` (BODY indices): the items it would place
        and the instances it would leave out over every path, and the same for the paths
        under each assembly, each at most ``_SATURATE``."""
        per: dict[int, tuple[int, int]] = {}
        for a in self.post:
            items, left = 0, len(self.skips[a])
            for _n, _it, c, _pl in self.children[a]:
                if c.type == ASSEMBLY:
                    i, s = per[c.index]
                    items += i
                    left += s
                elif c.index in wanted:
                    items += 1
            per[a] = (min(items, _SATURATE), min(left, _SATURATE))
        items = left = 0
        for top in self.tops:
            if top.type == ASSEMBLY:
                i, s = per[top.index]
                items += i
                left += s
            elif top.index in wanted:
                items += 1
        return min(items, _SATURATE), min(left, _SATURATE), per

    def walk(
        self,
        clock: Clock,
        *,
        world: bool = False,
        keep: Callable[[Node], bool] | None = None,
        skipped: Callable[[str, str, str], None] | None = None,
        cut: list[str] | None = None,
    ) -> Iterator[_Path]:
        """The instance paths one at a time, depth first, parents first (see ``_Path``;
        the placement in the model only when ``world``). Only parts ``keep`` accepts are
        followed. ``skipped(id, reason, message)`` hears of each instance left out under a
        path followed, and ``cut`` (a list) gets ``depth`` when instances past ``depth``
        were not followed."""
        lim = self.limits
        stack = [
            (pid, None, None, top, None, IDENTITY if world else None, 1)
            for pid, top in reversed(self.top_ids)
            if keep is None or keep(top)
        ]
        while stack:
            clock.tick()
            pid, parent, inst, part, local, placed, d = stack.pop()
            yield pid, parent, inst, part, local, placed
            if part.type != ASSEMBLY:
                continue
            kids = self.children[part.index]
            if d >= lim.depth:
                if kids and cut is not None:
                    cut.append("depth")
                continue
            if skipped is not None:
                for n, reason, message in self.skips[part.index]:
                    skipped(f"{pid}.{n}", reason, message)
            for n, it, child, pl in reversed(kids):
                if keep is None or keep(child):
                    there = _then(placed, pl) if placed is not None else None
                    stack.append((f"{pid}.{n}", pid, it, child, pl, there, d + 1))


# --------------------------------------------------------------------------- one body as a part
_CUT = {BODY: {"owner", "next", "previous", "ref_instance"}, ATTRIB_DEF: {"next"}}
_CHAINS = {ATTRIBUTE: ("next_of_type", "previous_of_type")}
_OUTSIDE = (WORLD, ASSEMBLY, INSTANCE, TRANSFORM)


def _pointer_slots(xt: XtTransmit, ntype: int) -> list[tuple[int, str, int]]:
    return [(i, f[0], f[2]) for i, f in enumerate(xt.layouts[ntype]) if f[1] == "p"]


def extract_body(
    xt: XtTransmit, body: Node, clock: Clock | None = None, *, max_nodes: int | None = None
) -> XtTransmit:
    """``body`` of a transmit whose root is an ASSEMBLY or a WORLD (a partition), copied
    with everything it reaches into a part transmit of its own (the BODY at index 1).
    Pointers to the world, assemblies, instances, transforms and other bodies are cut, as
    :func:`~solidseas.formats.solidworks.parasolid.partition_to_parts` does for a
    partition. ``clock`` bounds the time; a body that reaches more than ``max_nodes``
    nodes raises :class:`SldLimitError` (``detail["limit"]`` ``xt_nodes``)."""
    idx = xt.by_index()
    keep = {body.index}
    order = [body]
    qi = 0
    while qi < len(order):
        if clock is not None:
            clock.tick()
        if max_nodes is not None and len(order) > max_nodes:
            raise SldLimitError(
                f"the body reaches more than {max_nodes:,} nodes", detail={"limit": "xt_nodes"}
            )
        nd = order[qi]
        qi += 1
        cut = _CUT.get(nd.type, ())
        chains = _CHAINS.get(nd.type, ())
        for i, name, n in _pointer_slots(xt, nd.type):
            if name in cut or name in chains:
                continue
            v = nd.vals[i]
            for x in [v] if n == 1 else v:
                if not x or x in keep:
                    continue
                t = idx.get(x)
                if t is None or t.type in _OUTSIDE or (t.type == BODY and t is not body):
                    continue
                keep.add(x)
                order.append(t)
    remap = {n.index: k + 1 for k, n in enumerate(order)}
    nodes = []
    for nd in order:
        vals = list(nd.vals)
        cut = _CUT.get(nd.type, ())
        for i, name, n in _pointer_slots(xt, nd.type):
            v = vals[i]
            seq = [v] if n == 1 else list(v)
            for k, x in enumerate(seq):
                if x and (name in cut and nd.type != ATTRIB_DEF or x not in remap):
                    seq[k] = 0
                elif x:
                    seq[k] = remap[x]
            vals[i] = seq[0] if n == 1 else seq
        nodes.append(Node(nd.type, remap[nd.index], vals, nd.count))
    defs = [n for n in nodes if n.type == ATTRIB_DEF]
    if defs:
        ni = xt.field_names(ATTRIB_DEF).index("next")
        for a, b in zip(defs, [*defs[1:], None], strict=True):
            a.vals[ni] = b.index if b is not None else 0
    if max_nodes is not None and len(order) > max_nodes:
        raise SldLimitError(f"the body reaches more than {max_nodes:,} nodes", detail={"limit": "xt_nodes"})
    part = XtTransmit()
    part.flag = xt.flag
    part.modeller = xt.modeller.replace("TRANSMIT FILE (partition)", "TRANSMIT FILE")
    part.schema, part.base, part.max_types, part.usfld = xt.schema, xt.base, xt.max_types, xt.usfld
    part.layouts = {t: xt.layouts[t] for t in {n.type for n in nodes}}
    part.schema_info = {t: xt.schema_info[t] for t in part.layouts}
    part.nodes = nodes
    return part


# --------------------------------------------------------------------------- the document
class ParasolidDocument(ModelDocument):
    """One Parasolid transmit file (see the module notes)."""

    format = "parasolid"

    def __init__(self, source, *, name, path, file_info, limits, detection=None) -> None:
        super().__init__(
            source, name=name, path=path, file_info=file_info, limits=limits, detection=detection
        )
        self.kind = "brep"
        self.set_units("m", "format")
        head = source.head(min(source.size, limits.xt_header_bytes + PEEK_BYTES))
        self.keywords: list[tuple[str, str, str]] = []
        self._offset = 0
        if head.startswith(PREAMBLE):
            end = head.find(END_OF_HEADER, 0, limits.xt_header_bytes)
            if end < 0:
                if source.size > limits.xt_header_bytes:
                    raise limits.exceeded(
                        "xt_header_bytes",
                        f"the common header is longer than {limits.xt_header_bytes:,} bytes",
                    )
                raise SldFormatError("the common header has no end (**END_OF_HEADER)")
            nl = head.find(b"\n", end)
            if nl < 0:
                if len(head) < source.size:
                    raise SldFormatError("the common header's last line has no end")
                nl = len(head) - 1
            self._offset = nl + 1
            self.keywords, bad = parse_header(head[:end])
            if bad:
                self.warn("header_unreadable", f"{bad} record(s) of the common header could not be read")
        peek_bytes = source.read_upto(self._offset, PEEK_BYTES)
        self.peek = peek_transmit(peek_bytes)
        pk = self.peek
        if pk.flag == "bare":
            raise FormatNotSupportedError(
                "a bare (platform) binary transmit is written in the byte order and number format "
                "of the machine that wrote it; only neutral binary and text are read",
                detail={"rule": "bare_binary", "value": "parasolid"},
            )
        if pk.base != BASE_SCHEMA:
            why = (
                "does not embed its schema"
                if pk.base is None
                else f"embeds its schema over base {pk.base}, not {BASE_SCHEMA}"
            )
            raise FormatNotSupportedError(
                f"the transmit {why}: its node layouts need the schema file Parasolid ships, which is "
                "not public",
                detail={"rule": "schema_not_embedded", "value": "parasolid"},
            )
        if pk.usfld:
            raise FormatNotSupportedError(
                f"the transmit carries user fields ({pk.usfld} words a node), which are not read",
                detail={"rule": "user_fields", "value": "parasolid"},
            )
        if pk.kind == "deltas":
            raise FormatNotSupportedError(
                "a deltas transmit holds changes to a partition, not a model",
                detail={"rule": "unsupported_variant", "value": "deltas"},
            )
        self.variant = pk.flag
        self.doc_type = "assembly" if pk.root == ASSEMBLY else "part"
        self._head_properties()
        self._xt: XtTransmit | None = None
        self._overrun: float | None = None  # the largest time bound a parse ran out of
        self._structure: _Structure | None = None
        self._bodies_cache: list[BodyRef] | None = None
        self._cut: str | None = None

    # -- head ---------------------------------------------------------------------------
    def _head_properties(self) -> None:
        lim = self.limits
        props = []
        values: dict[str, str] = {}
        for _part, key, value in self.keywords:
            if len(props) >= lim.properties:
                raise lim.exceeded(
                    "properties", f"the common header has more than {lim.properties:,} keywords"
                )
            value = clip_text(value, lim, self.warnings, f"the header keyword {key}")
            values.setdefault(key, value)
            props.append(make_property(key, value))
        version = self.peek.modeller_version
        if version is not None:
            props.append(make_property("modeller_version", version))
        self.properties = props
        appl = values.get("APPL", "").strip()
        if appl.lower() not in _UNSET:
            name, _sp, tail = appl.rpartition(" ")
            if name and tail[:1].isdigit():
                self.application = {"name": name, "version": tail}
            else:
                self.application = {"name": appl, "version": None}
        user = values.get("USER", "").strip()
        if user.lower() not in _UNSET:
            self.fields = replace(self.fields, last_saved_by=user)

    def _counts(self) -> dict[str, int | None]:
        if self.peek.root == BODY:
            return {"bodies": 1}
        return {}

    # -- the transmit ---------------------------------------------------------------------
    def transmit(self, clock: Clock | None = None) -> XtTransmit:
        """The parsed transmit (parsed once and kept; at most ``xt_transmit_bytes`` and
        ``xt_nodes``). The parse stops at ``clock``'s deadline; after it has, a call whose
        clock allows no more time is refused at once rather than parsing again."""
        if self._xt is not None:
            return self._xt
        lim = self.limits
        n = self.source.size - self._offset
        if n > lim.xt_transmit_bytes:
            raise lim.exceeded(
                "xt_transmit_bytes",
                f"the transmit is {n:,} bytes, more than the {lim.xt_transmit_bytes:,} allowed",
                value=n,
            )
        if clock is not None:
            clock.check()
            if self._overrun is not None and clock.seconds is not None and clock.seconds <= self._overrun:
                raise SldLimitError(
                    f"the transmit could not be parsed in {self._overrun:g} s, and this read allows no more",
                    detail={"limit": clock.limit},
                )
        data = self.source.read_at(self._offset, n)
        try:
            if self.variant == "binary":
                xt = parse_binary(data, max_nodes=lim.xt_nodes, tick=clock.tick if clock else None)
            else:
                text = data.decode("latin-1")
                del data
                xt = parse_text(text, max_nodes=lim.xt_nodes, tick=clock.tick if clock else None)
        except SldLimitError as exc:
            if exc.detail and exc.detail.get("limit"):
                left = clock.left() if clock is not None else None
                if clock is not None and clock.seconds is not None and left is not None and left <= 0:
                    self._overrun = max(self._overrun or 0.0, clock.seconds)
                raise
            raise lim.exceeded("xt_nodes", f"the transmit has more than {lim.xt_nodes:,} nodes") from None
        if xt.inferred_types:
            self.warn(
                "layout_inferred",
                f"node type(s) {', '.join(map(str, xt.inferred_types))} have no layout in the published base "
                "schema; the layout used was inferred from files",
            )
        if xt.trailing:
            self.warn(
                "trailing_data", f"{xt.trailing:,} bytes follow the transmit's terminator; they were ignored"
            )
        self._xt = xt  # kept even when the deadline has passed by now: later reads need not parse
        if clock is not None:
            clock.check()
        return xt

    def _analysed(self, clock: Clock | None = None) -> _Structure:
        """The transmit's parts, instance paths, names and colours (worked out once)."""
        if self._structure is None:
            clock = clock or Clock(self.limits.seconds)
            xt = self.transmit(clock)
            self._structure = _Structure(xt, self.limits, clock, self.warnings)
            if self._structure.mixed:
                self.warn(
                    "colors_ignored",
                    f"the faces of {self._structure.mixed} bodies do not all show one colour (or some show "
                    "none); each body is drawn in the colour most of its faces show",
                )
        return self._structure

    # -- full reads --------------------------------------------------------------------------
    def scene(self, **options: Any) -> Scene:
        """:meth:`ModelDocument.scene`, with one addition: a ``display`` scene (the 3D view,
        thumbnails) whose tessellation ran out of time, or reached the tessellator's face
        bound, keeps the faces done and names the bound in ``truncated``
        (``max_seconds``, ``max_faces``). A ``bodies`` scene (the export) raises instead:
        a solid with faces missing is not printed.

        Rolling blends are the exception. The tessellator does them after every other
        face and skips those the time runs out on (reason ``max_seconds``) rather than
        stop (``docs/API.md`` 3.15). A ``bodies`` scene has their pass end
        :data:`BLEND_MARGIN` of its time before its deadline and keeps them out as faces
        the tessellator could not draw, in ``skipped``, so a 3D print is made with a hole
        there as for a SOLIDWORKS part; a ``display`` scene names ``max_seconds`` in
        ``truncated`` for them too."""
        self._cut = None
        scene = super().scene(**options)
        if self._cut is not None and self._cut not in scene.truncated:
            scene = replace(scene, truncated=(*scene.truncated, self._cut))
            if self._scene_cache is not None:
                self._scene_cache = (self._scene_cache[0], scene)
        return scene

    def _tree(self, clock: Clock):
        st = self._analysed(clock)
        out: list[ModelNode] = []
        stem = _stem(self.name)
        cut: list[str] = []
        for pid, parent, inst, part, local, _placed in st.walk(clock, cut=cut):
            name = (st.name(inst) if inst is not None else None) or st.name(part)
            obj = st.object_of.get(part.index) if part.type == BODY else None
            color = st.colours.get(part.index) if part.type == BODY else None
            if inst is None:
                kind = "assembly" if part.type == ASSEMBLY else "body"
                if name is None and len(st.tops) == 1:
                    name = stem
                out.append(ModelNode(pid, None, name, kind, obj, None, None, color))
            else:
                out.append(ModelNode(pid, parent, name, "component", obj, None, local, color))
            if len(out) > self.limits.tree_nodes:
                return ModelTree(tuple(out), True)  # the walk stops here: the rest is never made
        return ModelTree(tuple(out), bool(cut))

    def _scene(self, sb: SceneBuilder) -> None:
        from ..tessellate import tessellate_transmit
        from ..tessellate.topology import Topology

        clock = sb.clock
        st = self._analysed(clock)
        xt = self.transmit(clock)
        opts = sb.options
        lim = self.limits
        if st.too_deep:
            raise lim.exceeded("depth", f"the transmit's assemblies nest deeper than {lim.depth}")
        wanted = set(opts.body_types)
        topo = Topology(xt)
        chosen = []  # the bodies tessellate_transmit draws, in its order
        types: dict[int, str] = {}
        for b in topo.bodies():
            code = topo.get(b, "body_type", 0)
            btype = BODY_TYPES.get(code, "unknown") if isinstance(code, int) else "unknown"
            types[b.index] = btype
            if btype in wanted:
                chosen.append(b)
        left_out = Counter(types[b.index] for b in st.bodies if types.get(b.index) not in wanted)
        drawn = {b.index for b in st.bodies if types.get(b.index) in wanted}
        # Count the paths before placing any: a few instances can place a part billions of times.
        n_items, n_left, per = st.count(drawn)
        if n_items > lim.items:
            raise lim.exceeded("items", f"the transmit places more than {lim.items:,} parts")
        if n_left > lim.items:
            raise lim.exceeded("items", f"the transmit leaves out more than {lim.items:,} instances")
        cap = opts.max_triangles
        binding_cap = cap is not None and cap < lim.triangles
        tri_cap = (cap if binding_cap else lim.triangles) + 1
        display = opts.prefer == "display"
        clock.check()
        left = clock.left()
        budget = max(left if left is not None else opts.max_seconds, 0.0)
        reserve = 0.0
        if display:  # leave time to build the meshes of the faces done
            budget -= min(DISPLAY_MARGIN_SECONDS, DISPLAY_MARGIN * budget)
        else:  # and of the faces done when the time runs out among the blends
            reserve = min(BLEND_MARGIN_SECONDS, BLEND_MARGIN * budget)
        t = None
        if any(b.index in st.object_of for b in chosen):
            t = tessellate_transmit(
                xt, max_triangles=tri_cap, max_seconds=budget, blend_reserve_s=reserve, **opts.tessellation()
            )
            stopped = [k for k in ("max_seconds", "max_faces") if k in t.truncated]
            if stopped and display:
                self._cut = stopped[0]  # a view or a thumbnail draws the faces done
            elif "max_seconds" in stopped:
                raise SldLimitError(
                    f"tessellating the bodies took longer than {opts.max_seconds:g} s",
                    detail={"limit": "seconds"},
                )
            elif stopped:
                raise SldLimitError(
                    "the bodies have more faces than the tessellator draws in one call",
                    detail={"limit": "max_faces"},
                )
            else:
                clock.check()
                if display and t.reasons.get("max_seconds"):
                    # Rolling blends the time ran out on (done last, the rest whole): left out
                    # in either kind of scene, and a view or a thumbnail is marked partial.
                    self._cut = "max_seconds"
            if "max_triangles" in t.truncated and not binding_cap:
                raise lim.exceeded("triangles", f"the model has more than {lim.triangles:,} triangles")
            sb.counts.update(
                bodies=t.counts["bodies"], faces=t.counts["faces"], faces_done=t.counts["faces_done"]
            )
            sb.skipped.extend(t.skipped)
        else:
            sb.counts.update(bodies=0, faces=0, faces_done=0)
        if st.n_instances:
            sb.counts["components"] = st.components()
        if left_out:
            what = ", ".join(f"{n} {k}" for k, n in sorted(left_out.items()))
            sb.warn("bodies_left_out", f"bodies of types not asked for are left out: {what}")
        meshes = _split(t, chosen, welded=opts.prefer == "bodies") if t is not None else {}
        made = 0  # objects finished: a scene cut short by max_triangles places only those
        cut_short = t is not None and "max_triangles" in t.truncated
        for body in st.bodies:
            clock.tick()
            got = meshes.get(body.index)
            mb = sb.mesh(
                name=st.name(body),
                source="bodies",
                color=st.colours.get(body.index),
                node=st.first_node.get(body.index),
            )
            try:
                if got is not None:
                    positions, triangles, normals = got
                    mb.add_vertices(positions)
                    mb.add_triangles(triangles)
                    if normals is not None:
                        mb.set_normals(normals)
                mb.finish()
            except _Truncated:
                cut_short = True
                break
            made += 1

        def keep(part: Node) -> bool:
            if part.type == BODY:
                return part.index in drawn and st.object_of[part.index] < made
            placed, left = per[part.index]
            return placed > 0 or left > 0

        paths = st.walk(clock, world=True, keep=keep, skipped=sb.skip)
        for pid, _parent, _inst, part, _local, placed in paths:
            if part.type == BODY and placed is not None:
                sb.add_item(st.object_of[part.index], pid, placed)
        if cut_short:
            raise _Truncated()

    def _bodies(self, clock: Clock) -> list[BodyRef]:
        if self._bodies_cache is not None:
            return self._bodies_cache
        st = self._analysed(clock)
        xt = self.transmit(clock)
        from ..tessellate.topology import Topology

        topo = Topology(xt)
        out = []
        whole = st.root.type == BODY  # the file's transmit is its one body
        lim = self.limits
        allowed = min(lim.xt_nodes, COPY_FACTOR * len(xt.nodes) + COPY_SLACK)
        left = allowed
        for body in st.bodies:
            clock.tick()
            if whole:
                transmit = xt
            else:
                try:
                    transmit = extract_body(xt, body, clock, max_nodes=left)
                except SldLimitError as exc:
                    if (exc.detail or {}).get("limit") != "xt_nodes":
                        raise
                    raise lim.exceeded(
                        "xt_nodes",
                        f"copying the bodies out as parts would take more than {allowed:,} nodes: "
                        "they share more than attribute definitions",
                    ) from None
                left -= len(transmit.nodes)
            code = topo.get(body, "body_type", 0)
            out.append(
                BodyRef(
                    st.name(body),
                    transmit,
                    st.colours.get(body.index),
                    st.first_node.get(body.index),
                    BODY_TYPES.get(code, "unknown") if isinstance(code, int) else "unknown",
                )
            )
        self._bodies_cache = out
        return out


def _split(t, chosen: list[Node], *, welded: bool) -> dict[int, tuple[list, list, list | None]]:
    """The tessellation's triangles body by body: ``{BODY index: (positions, triangles,
    normals)}``, each body's vertices numbered from 0. ``welded``: over the shared float64
    points (faces meet on the same vertices, as an export wants); otherwise each face's
    own vertices with their surface normals (as a view wants)."""
    if welded:
        pos, tris = t.welded()
        nrm = None
    else:
        pos, tris, nrm = t.mesh.positions, t.mesh.triangles, t.mesh.normals
    per: dict[int, list[int]] = {}
    for i, (k, _fid) in enumerate(t.face_ids):
        per.setdefault(k, []).append(i)
    out = {}
    for k, faces in per.items():
        local: dict[int, int] = {}
        triangles: list[int] = []
        for i in faces:
            face = t.mesh.faces[i]
            a = 3 * face.first_triangle
            for v in tris[a : a + 3 * face.n_triangles]:
                j = local.get(v)
                if j is None:
                    j = local[v] = len(local)
                triangles.append(j)
        order = sorted(local, key=local.__getitem__)
        positions = [float(pos[3 * v + c]) for v in order for c in range(3)]
        normals = [float(nrm[3 * v + c]) for v in order for c in range(3)] if nrm is not None else None
        out[chosen[k].index] = (positions, triangles, normals)
    return out


def open(source, *, name, path, file_info, limits, hold_open=False, detection=None) -> ParasolidDocument:
    """Open a Parasolid transmit file's :class:`~solidseas.formats._source.Source` (the
    registry's reader for ``parasolid``)."""
    return ParasolidDocument(
        source, name=name, path=path, file_info=file_info, limits=limits, detection=detection
    )


__all__ = [
    "REVISION",
    "ParasolidDocument",
    "bodies_in_place",
    "extract_body",
    "open",
    "parse_header",
    "peek_transmit",
]
