"""The clean-room generator: a ``ParametricDocumentIR`` part to a native ``.sldprt``.

Written from the generation specification alone (``docs/sldprt-spec/``,
section 15 of ``docs/NATIVE_SLDPRT_WRITER.md``) under the rules of
``docs/CLEANROOM.md``. The interface is section 15.0.7:

- :func:`plan` turns a design into the slot dict (15.6), or refuses it;
- :func:`assemble` turns a slot dict into the 35 members of 15.0.1 by running
  the specification's listings, compiled into :mod:`._listings`;
- :func:`write_part` is ``plan``, then ``assemble``, then the container
  (15.1.1);
- ``SPEC_CONSTANTS`` is every constant run longer than 31 bytes the listings
  give, for the clean-room test.

Nothing here opens a file while it runs.
"""

from collections.abc import Mapping
from functools import cache

from .. import ir
from ..container import Member, build_container
from . import _listings, listing
from .listing import ListingError
from .slots import Identity, NativeWriteUnsupported, Plan, plan

__all__ = [
    "Identity",
    "ListingError",
    "NativeWriteUnsupported",
    "Plan",
    "SPEC_CONSTANTS",
    "assemble",
    "container_key",
    "internal_attr",
    "plan",
    "write_part",
]

MEMBERS = tuple(m for m, _section, _file in _listings.MEMBERS)  # spec 15.0.1
# The feature stream goes on with the archive Config-0 leaves (15.0.4, 15.6.1).
CONTINUES = {"Contents/Config-0-ResolvedFeatures": "Contents/Config-0"}  # spec 15.6.1
DOS_TIME = 0xB719  # spec 15.1.1.2: every member but Header2
DOS_TIME_HEADER2 = 0xB6C4  # spec 15.1.1.2: Header2
DOS_DATE = 0x1A6D  # spec 15.1.1.2: every member
RAND_MUL, RAND_ADD = 214013, 2531011  # spec 15.1.1.1, FORMAT.md 2.7: MSVC rand()
RAND_MASK = 0x7FFF  # spec 15.1.1.1: output (state >> 16) & 0x7FFF
KEY_INDICES = range(1, 1000)  # spec 15.1.1.1: k from 1 to 999
CONSTANT_RUN = 32  # spec 15.0.7, CLEANROOM.md 4: runs longer than 31 bytes
_BINARY_BYTES = frozenset([*range(0, 7), *range(14, 26), *range(28, 32)])  # spec 15.1.1.2
_TEXT_BYTES = frozenset([9, 10, 13, *range(32, 256)])  # spec 15.1.1.2


def is_xml(member: str) -> bool:
    """Whether ``member`` is one of the XML listings whose ``${...}`` are escaped (15.1.2)."""
    return member.endswith((".xml", ".rels")) or member.startswith("swXmlContents/")


def assemble(slots: Mapping) -> dict[str, bytes]:
    """Every member of section 15.0.1, by name and in table order, from a complete slot dict."""
    out: dict[str, bytes] = {}
    archives: dict[str, listing.Archive | None] = {}
    for name in MEMBERS:
        prev = archives.get(CONTINUES.get(name, ""))
        result = listing.run(_listings.LISTINGS[name], slots, archive=prev, xml=is_xml(name))
        out[name] = result.data
        archives[name] = result.archive
    return out


# ------------------------------------------------------------------ the container (15.1.1)
@cache
def _rand_low_bytes() -> bytes:
    """R[0] to R[16 * 999 + 15]: the low bytes of MSVC rand() from its default start, 1."""
    state = 1  # spec 15.1.1.1: the default seed of rand()
    out = bytearray()
    for _ in range(16 * KEY_INDICES[-1] + 16):
        state = (state * RAND_MUL + RAND_ADD) % 2**32
        out.append(((state >> 16) & RAND_MASK) & 0xFF)  # spec 15.1.1.1: the low byte of each output
    return bytes(out)


def container_key(k: int) -> tuple[bytes, tuple[bytes, bytes, bytes]]:
    """The key and the (local, directory, end) signatures for key index ``k`` (15.1.1.1)."""
    if k not in KEY_INDICES:
        raise ValueError(f"key index {k} is outside 1 to 999")
    r = _rand_low_bytes()
    b = 16 * k
    key = r[b : b + 4]
    sigs = (r[b + 4 : b + 8][::-1], r[b + 8 : b + 12][::-1], r[b + 12 : b + 16][::-1])
    return key, sigs


def internal_attr(data: bytes) -> int:
    """15.1.1.2: 1 when the member holds no binary control byte and at least one text byte."""
    seen = set(data)
    return int(bool(seen) and not seen & _BINARY_BYTES and bool(seen & _TEXT_BYTES))


def write_part(doc: ir.Document, *, identity: Identity | None = None, allow_partial: bool = False) -> bytes:
    """The whole ``.sldprt`` for ``doc``: :func:`plan`, :func:`assemble`, then the container."""
    p = plan(doc, identity=identity, allow_partial=allow_partial)
    members = assemble(p.slots)
    key, signatures = container_key(p.identity.key_index)
    return build_container(
        [
            Member(
                name=name,
                data=data,
                dos_time=DOS_TIME_HEADER2 if name == "Header2" else DOS_TIME,
                dos_date=DOS_DATE,
                internal_attr=internal_attr(data),
            )
            for name, data in members.items()
        ],
        key=key,
        signatures=signatures,
    )


# ------------------------------------------------------------------ SPEC_CONSTANTS (15.0.7)
def _box(n: int, x0: float, y0: float, x1: float, y1: float, depth: float) -> list:
    pts = [ir.Point(f"p{n}{i}", x, y) for i, (x, y) in enumerate(((x0, y0), (x1, y0), (x1, y1), (x0, y1)))]
    lines = [ir.Curve(f"l{n}{i}", "line", [pts[i].id, pts[(i + 1) % 4].id]) for i in range(4)]
    sk = ir.Sketch(f"s{n}", f"Sketch{n}", ir.Plane.named("xy"), pts, lines)
    return [sk, ir.Extrude(f"e{n}", f"Extrude{n}", sk.id, depth)]


def _hole(n: int, cx: float, cy: float, r: float) -> list:
    """A circle on the Front Plane cut through all in both directions (15.6.2)."""
    centre = ir.Point(f"c{n}", cx, cy)
    circle = ir.Curve(f"k{n}", "circle", [centre.id], radius=r)
    sk = ir.Sketch(f"s{n}", f"Sketch{n}", ir.Plane.named("xy"), [centre], [circle])
    cut = ir.Extrude(f"e{n}", f"Cut{n}", sk.id, 0.0, operation="cut", end="through_all", direction="midplane")
    return [sk, cut]


def _shapes() -> list[tuple[tuple[ir.Document, Identity], ...]]:
    """The shapes SPEC_CONSTANTS is measured on, each in two variants.

    An empty part, one box, two boxes and one box with a hole (15.6.8's examples), each
    made once with 15.6.8's sizes and once with other sizes, and each with its own
    identity. The two identities give texts of the same lengths (the same weekday and
    month name lengths, one-digit hours), so the members line up byte for byte. The
    hole is a circle inside the box's rectangle, cut through all in both directions; in
    the two variants its centre and radius differ and the box's depth is written with
    the same number of digits, so its members line up too.

    The last shape is one box with five file custom properties, one of each form of
    15.6.9 in order: a text, a whole number, a real number, a date and yes or no. In
    the two variants each name and each value as typed has the same length and differs
    from the first character on, the yes or no property is true in both, and the names
    sort by ``props_by_name`` in the design's order.
    """
    from datetime import UTC, datetime

    def ident(when: datetime, k: int, digit: str, stem: str) -> Identity:
        guid = f"{digit * 8}-{digit * 4}-4{digit * 3}-8{digit * 3}-{digit * 12}"
        return Identity(when, k, "{" + guid.upper() + "}", *[guid] * 5, file_stem=stem)

    first = ident(datetime(2015, 6, 15, 9, 12, 34, tzinfo=UTC), 3, "a", "shapeA")  # spec 15.0.7
    second = ident(datetime(2018, 7, 27, 3, 45, 51, tzinfo=UTC), 4, "b", "shapeB")  # spec 15.0.7
    one_a, one_b = _box(1, 0.0, 0.0, 0.01, 0.02, 0.03), _box(1, 0.0, 0.0, 0.025, 0.05, 0.07)
    two_a, two_b = _box(2, 0.03, 0.0, 0.04, 0.02, 0.01), _box(2, 0.04, 0.005, 0.06, 0.03, 0.02)
    hole_a = _hole(2, 0.005, 0.01, 0.0025)  # spec 15.6.8: the box with a hole's circle
    hole_b = _hole(2, 0.0125, 0.03, 0.004)  # spec 15.0.7: another circle inside one_b's rectangle
    forms = ("text", "number", "number", "date", "yesno")  # spec 15.0.7: one of each form of 15.6.9
    names_a, names_b = ("Apex", "Bolt", "Core", "Dial", "Edge"), ("Knob", "Lens", "Mast", "Note", "Oval")
    values_a = ("Steel", 42, 3.25, "2015-06-15", True)  # spec 15.0.7
    values_b = ("Brass", 87, 6.81, "2018-07-27", True)  # spec 15.0.7
    props_a = [ir.Property(*x) for x in zip(names_a, values_a, forms, strict=True)]
    props_b = [ir.Property(*x) for x in zip(names_b, values_b, forms, strict=True)]
    return [
        ((ir.Document("empty"), first), (ir.Document("empty"), second)),
        ((ir.Document("one", one_a), first), (ir.Document("one", one_b), second)),
        ((ir.Document("two", one_a + two_a), first), (ir.Document("two", one_b + two_b), second)),
        ((ir.Document("hole", one_a + hole_a), first), (ir.Document("hole", one_b + hole_b), second)),
        (
            (ir.Document("props", one_a, properties=props_a), first),
            (ir.Document("props", one_b, properties=props_b), second),
        ),
    ]


def _agreeing_runs(a: bytes, b: bytes) -> list[bytes]:
    """The maximal runs of 32 or more bytes where ``a`` and ``b`` agree at the same offsets."""
    runs, start = [], 0
    n = min(len(a), len(b))
    for i in range(n + 1):
        if i == n or a[i] != b[i]:
            if i - start >= CONSTANT_RUN:
                runs.append(a[start:i])
            start = i + 1
    return runs


def _constant_runs() -> tuple[bytes, ...]:
    """Every run of 32 or more bytes that is the same whatever the design's values and the identity.

    Section 15.0.7: assemble each shape in its variants and keep, member by member,
    the runs that agree at the same offsets. A member whose variants differ in length
    is compared up to the shorter one.
    """
    seen: dict[bytes, None] = {}
    for (doc_a, id_a), (doc_b, id_b) in _shapes():
        ma = assemble(plan(doc_a, identity=id_a).slots)
        mb = assemble(plan(doc_b, identity=id_b).slots)
        for name in MEMBERS:
            for run in _agreeing_runs(ma[name], mb[name]):
                seen.setdefault(run)
    return tuple(seen)


@cache
def spec_constants() -> tuple[bytes, ...]:
    """``SPEC_CONSTANTS``, measured once on first use."""
    return _constant_runs()


def __getattr__(name: str):
    if name == "SPEC_CONSTANTS":
        return spec_constants()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
