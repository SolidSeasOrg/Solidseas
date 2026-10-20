"""Section 15.6: from a ``ParametricDocumentIR`` part and an :class:`Identity` to the slot dict.

:func:`plan` follows 15.6.1 step by step: validate the IR, accept or refuse
each item of the timeline (15.6.2) and each file custom property (15.6.9),
build ``features``, ``bodies`` and the model, plane and header slots (15.6.3,
15.6.4), take or make the identity values and fill every identity and free
slot (15.6.6), then ``props`` and ``props_by_name`` (15.6.9) and the slots
derived from the identity values (15.6.5).

The slot dict is flat: each key is a slot's full dotted name as the
specification's tables write it (``"doc.name"``, ``"planes.front"``,
``"fixed.comments.time"``), and a slot with fields or items holds a dict or a
list (``"planes.front"`` holds ``hu``, ``hv``, ``min`` ...; ``"model.max"``
three floats; ``"features"`` one dict per item).
"""

import math
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from ...errors import SolidSeasError
from .. import ir

# spec question: 15.0.7 asks for "the dict of every slot, section by section" without saying
# whether it is flat or nested. The generator writes it flat by full slot name; the listing
# reader (listing.lookup) accepts flat, nested or mixed dicts, so either shape assembles.

# spec 15.6.7: a plain number: an optional sign, digits with at most one point, at most one unit
_PLAIN_NUMBER = re.compile(r"[+-]?(?=\.?\d)\d*\.?\d*(mm|cm|m|in|deg|\u00b0)?")
FIRST_ID = 26  # spec 15.6.2: the creation numbers count on from 26
GAP_FIRST_SKETCH = 6  # spec 15.6.2, 15.5.4: the part's first sketch takes the counter and adds 6
GAP_LATER_SKETCH = 7  # spec 15.6.2, 15.5.4: a later sketch, 7
FIRST_BODY = 101  # spec 15.6.2, 15.6.4: body ids from 101
EMPTY_PLANE_HALF = (0.08899, 0.05500000000000001)  # spec 15.6.3: the template's rectangle
PLANE_MARGIN = 0.1  # spec 15.6.3: half side e/2 + e/2*0.1
FILETIME_EPOCH = 11644473600  # spec 15.6.5: seconds from 1601-01-01 to 1970-01-01
FILETIME_UNIT = 10000000  # spec 15.6.5: 100 ns units per second
AUTHOR = "SolidSeas"  # spec 15.0.6, 15.6.6
COMPANY = "SolidSeas"  # spec 15.6.6 meta.company
DOC_NAME = "Part1"  # spec 15.6.6 doc.name
TEXTURE = "<SystemTexture>\\graphics\\materials\\color.p2m"  # spec 15.6.6 cmgr.texture
FIXED_KEYS = (
    "comments",
    "favorites",
    "history",
    "selsets",
    "sensors",
    "binder",
    "annotations",
    "notes",
    "notes_end",
    "surface",
    "solid",
    "lights",
    "markups",
    "material",
    "front",
    "top",
    "right",
    "origin",
)  # spec 15.6.6 fixed.<key>.time
ORIGIN_REGEN = 102  # spec 15.6.6 fixed.origin.regen
SKETCH_REGEN = 103  # spec 15.6.2 regen
BODY_REGEN = 1151  # spec 15.6.4 regen: 1151 + 2k
COUNTER_MARKS = 7  # spec 15.6.2 counter_marks
CIRCLE_REGEN = 102  # spec 15.6.2 regen of a circle, 15.5.9
CUT_COUNTER_MARKS = 14  # spec 15.6.2 counter_marks of a cut, 15.5.9
CUT_NAME = "Cut-Extrude1"  # spec 15.6.2 name of a hole's cut
# spec 15.6.2 ring, 15.5.13: (end, face) of side 4, end face 1, side 3, end face 0, side 1
RING = ((False, 4), (True, 1), (False, 3), (True, 0), (False, 1))
BUILD_BUCKETS = 17  # spec 15.6.5 builds, 15.2.7.5: a hash table of 17 buckets
OS_VERSION = (2, 10, 0, 0)  # spec 15.6.6 bio.os.platform, major, minor, build
LOCALE = 1033  # spec 15.6.6 bio.locale
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
FRONT = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))  # spec 15.6.2: the base plane xy
UNIT = 2**32
HASH_START = 5381  # spec 15.3.3: the key hash starts at 5381
HASH_FACTOR = 33  # spec 15.3.3
FIRST_PID = 3  # spec 15.6.9 pid: 3 + k
MAX_PROPERTIES = 65534  # spec 15.6.9, 15.2.4: the list's length is a u16
I4_RANGE = (-(2**31), 2**31 - 1)  # spec 15.6.9: a whole number is stored as a vt:i4
FIRST_DATE = date(1601, 1, 1)  # spec 15.6.9: a date is stored as a FILETIME
DATE_HOUR = 12  # spec 15.6.9: a date is stored at noon
CONTROL_BELOW = 0x20  # spec 15.6.9: no character below U+0020
SURROGATES = (0xD800, 0xDFFF)  # spec 15.6.9: no lone surrogate
NONCHARACTERS = (0xFFFE, 0xFFFF)  # spec 15.6.9: neither U+FFFE nor U+FFFF
PROPERTY_CODES = {"text": 0, "date": 1, "number": 2, "yesno": 3}  # spec 15.6.9 code
PROPERTY_TYPE_IDS = {"text": 30, "date": 64, "number": 3, "yesno": 11}  # spec 15.6.9 type_id
PROPERTY_VTS = {"text": "lpstr", "date": "filetime", "yesno": "bool"}  # spec 15.6.9 vt
_LINK = re.compile(r"\$prp", re.IGNORECASE | re.ASCII)  # spec 15.6.9: $PRP in any case


class NativeWriteUnsupported(SolidSeasError, ValueError):
    """The design needs something section 15.6 does not write; ``items`` says what, in words."""

    code = "not_representable"

    def __init__(self, items):
        self.items = list(items)
        super().__init__(
            "the design cannot be written as a native part: " + "; ".join(self.items),
            detail={"rule": self.items[0] if self.items else "", "value": len(self.items)},
        )


@dataclass(frozen=True)
class Identity:
    """The identity values of one file (15.6.6). Pass one to make the output reproducible."""

    when: datetime
    key_index: int
    anim_guid: str
    exch_front: str
    exch_top: str
    exch_right: str
    exch_doc: str
    exch_config: str
    file_stem: str | None = None

    @classmethod
    def new(cls, file_stem: str | None = None) -> "Identity":
        """The clock at the call (whole seconds, UTC) and a random source, as 15.6.6 says."""
        return cls(
            when=datetime.now(UTC).replace(microsecond=0),
            key_index=secrets.randbelow(999) + 1,
            anim_guid="{" + str(uuid.uuid4()).upper() + "}",
            exch_front=str(uuid.uuid4()),
            exch_top=str(uuid.uuid4()),
            exch_right=str(uuid.uuid4()),
            exch_doc=str(uuid.uuid4()),
            exch_config=str(uuid.uuid4()),
            file_stem=file_stem,
        )


@dataclass
class Plan:
    """What :func:`write_part` would write.

    ``slots`` is the dict of every slot; ``left_out`` each item of the design the
    part does not carry, in words for the person exporting; ``names`` maps each
    written IR feature's id and its name to the name it has in the part;
    ``identity`` is the identity the slots were filled from.
    """

    slots: dict[str, Any]
    left_out: list[str] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)
    identity: Identity | None = None


# ------------------------------------------------------------------ accepting the timeline (15.6.2)
@dataclass
class _Rect:
    corners: tuple[float, float, float, float]  # x0, y0, x1, y1
    lines: frozenset[str]
    corner_ids: dict[str, tuple[float, float]]
    min_corner: str
    origin_corner: str | None  # a corner (not the minimum) that lies on the origin


@dataclass
class _Circle:
    curve: str  # the circle's curve id
    centre_id: str  # its centre point's id (``origin`` for the sketch origin)
    centre: tuple[float, float]  # cx, cy
    radius: float


@dataclass
class _Pair:
    """One accepted pair of the timeline: a box (a rectangle and its extrusion) or the hole."""

    sketch: ir.Sketch
    extrude: ir.Extrude
    rect: _Rect | None = None
    circle: _Circle | None = None


def _number(v: float) -> str:
    """A number rounded to 8 decimals, trailing zeros and a trailing point removed (15.6.2)."""
    return f"{round(v, 8):.8f}".rstrip("0").rstrip(".")


def _mm(v: float) -> str:
    return _number(v * 1000)  # spec 15.6.2 depth_text: metres to millimetres


def _kept_expression(expression: str | None) -> bool:
    """Whether a parameter's expression is lost in the part: it is there and not a plain number."""
    return bool(expression) and not _PLAIN_NUMBER.fullmatch(expression.replace(" ", ""))


def _on_front_plane(s: ir.Sketch) -> bool:
    """Whether the sketch lies on the base plane ``xy``, SOLIDWORKS' Front Plane (15.6.2)."""
    return tuple(map(tuple, (s.plane.origin, s.plane.x_dir, s.plane.y_dir))) == FRONT and (
        s.plane.offset in (None, 0.0) and s.plane.face_point is None
    )


def _is_circle_sketch(s: ir.Sketch) -> bool:
    """Whether the sketch is read as a hole's (15.6.2): its curves are circles, and there is one.

    The specification calls the hole's sketch the one whose one curve is a circle, and
    refuses a sketch of several circles with its own reason; a sketch whose every curve is
    a circle is therefore read against the circle's table, and every other sketch against
    the rectangle's.
    """
    return bool(s.curves) and all(c.kind == "circle" for c in s.curves)


def _rectangle(s: ir.Sketch) -> tuple[_Rect | None, str | None]:
    """The sketch's corner rectangle, or the reason it is refused."""
    if not _on_front_plane(s):
        return None, "sketch on a plane other than the Front Plane"
    if s.suppressed:
        return None, "suppressed sketch"
    not_rect = "sketch is not a single corner rectangle"
    if len(s.curves) != 4 or any(c.kind != "line" or c.construction for c in s.curves):
        return None, not_rect
    ends: dict[str, int] = {}
    for c in s.curves:
        for p in c.points:
            ends[p] = ends.get(p, 0) + 1
    if len(ends) != 4 or any(n != 2 for n in ends.values()):
        return None, not_rect
    # One closed loop: walk from one line through shared corners.
    left = list(s.curves)
    at = left.pop(0)
    start, here = at.points[0], at.points[1]
    while left:
        nxt = next((c for c in left if here in c.points), None)
        if nxt is None:
            return None, not_rect
        left.remove(nxt)
        here = nxt.points[1] if nxt.points[0] == here else nxt.points[0]
    if here != start:
        return None, not_rect
    xy = {p.id: (p.x, p.y) for p in s.points}
    xy[ir.ORIGIN] = (0.0, 0.0)
    corners = {p: xy[p] for p in ends}
    if len(set(corners.values())) != 4:
        return None, "degenerate rectangle"
    horizontal = vertical = 0
    for c in s.curves:
        (ax, ay), (bx, by) = xy[c.points[0]], xy[c.points[1]]
        if ay == by and ax != bx:
            horizontal += 1
        elif ax == bx and ay != by:
            vertical += 1
    if horizontal != 2 or vertical != 2:
        return None, "rectangle is not aligned with the sketch axes"
    xs = sorted({x for x, _ in corners.values()})
    ys = sorted({y for _, y in corners.values()})
    if len(xs) != 2 or len(ys) != 2 or not (xs[1] - xs[0] > 0 and ys[1] - ys[0] > 0):
        return None, "degenerate rectangle"
    x0, x1, y0, y1 = xs[0], xs[1], ys[0], ys[1]
    min_corner = next(p for p, v in corners.items() if v == (x0, y0))
    on_origin = [p for p, v in corners.items() if v == (0.0, 0.0) and p != min_corner]
    rect = _Rect((x0, y0, x1, y1), frozenset(c.id for c in s.curves), corners, min_corner, None)
    rect.origin_corner = on_origin[0] if on_origin else None
    return rect, None


def _circle(s: ir.Sketch) -> tuple[_Circle | None, str | None]:
    """The hole's circle, or the reason its sketch is refused (15.6.2's circle sketch table)."""
    if not _on_front_plane(s):
        return None, "sketch on a plane other than the Front Plane"
    if s.suppressed:
        return None, "suppressed sketch"
    if len(s.curves) != 1 or s.curves[0].kind != "circle" or s.curves[0].construction:
        return None, "a sketch with more than one circle is not written yet"
    c = s.curves[0]
    r = c.radius
    if r is None or not math.isfinite(r) or not r > 0:
        return None, "degenerate circle"
    xy = {p.id: (p.x, p.y) for p in s.points}
    xy[ir.ORIGIN] = (0.0, 0.0)
    centre = c.points[0]
    return _Circle(c.id, centre, (float(xy[centre][0]), float(xy[centre][1])), float(r)), None


def _extrusion_problem(e: ir.Extrude, rect: _Rect, k: int) -> str | None:
    """The reason the k-th box's extrusion, which follows its sketch at once, is refused, or None.

    A blind depth is positive and finite already: ``ir.validate`` requires it (15.6.2).
    """
    if e.end != "blind" or e.direction != "forward":
        return "only blind extrusions towards the sketch normal are written"
    if e.profile is not None and (
        len(e.profile) != 1 or len(e.profile[0]) != 4 or frozenset(e.profile[0]) != rect.lines
    ):
        return "profile is not the whole rectangle"
    if k == 0 and e.operation not in ("new_body", "join"):
        return "the first extrusion cannot cut"
    if k > 0 and e.operation != "new_body":
        return "a later extrusion that joins or cuts is not written yet (only merge off is proved)"
    if e.suppressed:
        return "suppressed extrusion"
    return None


def _cut_problem(e: ir.Extrude, circle: _Circle, boxes: list[_Rect], last: bool) -> str | None:
    """The reason the hole's cut, which follows its circle at once, is refused, or None.

    ``boxes`` are the boxes accepted before it and ``last`` says whether the cut is the
    last item of the timeline. The conditions are 15.6.2's cut table, in its order.
    """
    if e.operation != "cut":
        return "a circle is written only as the profile of a cut"
    if e.end != "through_all" or e.direction != "midplane":
        return "only a cut through all in both directions is written"
    if len(boxes) != 1 or not last:
        return "a cut is written only as the last feature of a part with one box"
    x0, y0, x1, y1 = boxes[0].corners
    (cx, cy), r = circle.centre, circle.radius
    if not (x0 < cx - r and cx + r < x1 and y0 < cy - r and cy + r < y1):
        return "the circle is not inside the box's rectangle"
    if e.profile is not None and (len(e.profile) != 1 or list(e.profile[0]) != [circle.curve]):
        return "profile is not the whole circle"
    if e.suppressed:
        return "suppressed extrusion"
    return None


_KIND_REFUSALS = {
    ir.Revolve: "revolves are not written yet",
    ir.Fillet: "fillets are not written yet",
    ir.Chamfer: "chamfers are not written yet",
    ir.Hole: "holes are not written yet",
    ir.Pattern: "patterns are not written yet",
    ir.Mirror: "mirrors are not written yet",
}


def _dimension_notes(s: ir.Sketch, params: dict[str, ir.Parameter], shape: str) -> list[str]:
    """15.6.7: one entry per sketch dimension, kept as geometry only; ``shape`` is what the part has."""
    notes = []
    for d in s.dimensions:
        if d.kind in ir.ANGLE_DIMENSIONS:
            value = f"{_number(math.degrees(d.value))} degrees"
        else:
            value = f"{_mm(d.value)} mm"
        p = params.get(d.parameter or "")
        entry = (
            f"{s.name}: dimension {p.name if p is not None else d.id} ({d.kind}, {value}) is kept as "
            f"geometry only; the {shape} has no driving dimensions in the part"
        )
        if p is not None and _kept_expression(p.expression):
            entry += f"; its expression {p.expression} is not kept"
        notes.append(entry)
    return notes


def _sketch_notes(s: ir.Sketch, rect: _Rect, params: dict[str, ir.Parameter]) -> list[str]:
    """15.6.7: what of an accepted rectangle's sketch the part does not carry."""
    notes = _dimension_notes(s, params, "rectangle")
    corners = set(rect.corner_ids)
    for c in s.constraints:
        if c.kind in ("horizontal", "vertical") and not c.points and set(c.curves) <= rect.lines:
            continue
        if c.kind == "coincident" and set(c.points) <= corners:
            continue
        if c.kind == "coincident" and ir.ORIGIN in c.points:
            other = [p for p in c.points if p != ir.ORIGIN]
            if other and other[0] == rect.min_corner and rect.corners[:2] == (0.0, 0.0):
                continue
            if other and other[0] == rect.origin_corner:
                continue  # reported once below, as the corner on the origin
        notes.append(
            f"{s.name}: relation {c.kind} on {', '.join([*c.points, *c.curves])} is not written; "
            "the rectangle keeps its horizontal, vertical and corner relations"
        )
    if rect.origin_corner is not None:
        notes.append(f"{s.name}: the corner on the origin is not tied to it")
    for p in s.points:
        if p.id not in corners:
            notes.append(f"{s.name}: point {p.id} is not written")
    return notes


def _circle_notes(s: ir.Sketch, circle: _Circle, params: dict[str, ir.Parameter]) -> list[str]:
    """15.6.7: what of an accepted circle's sketch the part does not carry.

    The part writes no relation of a circle sketch, so every constraint is reported, and
    every point but the centre.
    """
    notes = _dimension_notes(s, params, "circle")
    for c in s.constraints:
        notes.append(
            f"{s.name}: relation {c.kind} on {', '.join([*c.points, *c.curves])} is not written; "
            "the circle keeps its centre and radius"
        )
    for p in s.points:
        if p.id != circle.centre_id:
            notes.append(f"{s.name}: point {p.id} is not written")
    return notes


def _accept(doc: ir.Document) -> tuple[list[_Pair], list[str], list[str]]:
    """The accepted pairs, the refusals, and what is left out.

    ``left_out`` is in timeline order and holds the refusals too, as 15.6.7 lists them
    when ``allow_partial`` is given.
    """
    items = doc.features
    params = {p.name: p for p in doc.parameters}
    users: dict[str, list] = {}
    for f in items:
        if isinstance(f, (ir.Extrude, ir.Revolve)):
            users.setdefault(f.sketch, []).append(f)
    pairs: list[_Pair] = []
    boxes: list[_Rect] = []
    refused: list[str] = []
    left_out: list[str] = []
    dropped: set[str] = set()

    def _refuse(entry: str) -> None:
        refused.append(entry)
        left_out.append(entry)

    i = 0
    while i < len(items):
        f = items[i]
        nxt = items[i + 1] if i + 1 < len(items) else None
        i += 1
        if isinstance(f, ir.Sketch):
            hole = _is_circle_sketch(f)
            rect, circle, why = None, None, None
            if hole:
                circle, why = _circle(f)
            else:
                rect, why = _rectangle(f)
            mine = users.get(f.id, [])
            if why is None and not (len(mine) == 1 and mine[0] is nxt and isinstance(nxt, ir.Extrude)):
                why = "sketch not followed by its extrusion"
            if why is not None:
                _refuse(f"{f.name}: {why}")
                dropped.add(f.id)
                continue
            if hole:
                problem = _cut_problem(nxt, circle, boxes, i + 1 == len(items))
            else:
                problem = _extrusion_problem(nxt, rect, len(boxes))
            i += 1
            if problem is not None:
                _refuse(f"{nxt.name}: {problem}")
                dropped.update((f.id, nxt.id))
                # spec question: 15.6.2 writes sketches only in pairs, so a sketch whose extrusion
                # is refused cannot be written either; it is reported as left out with it.
                left_out.append(f"{f.name}: left out with {nxt.name}, which is not written")
                continue
            if hole:
                pairs.append(_Pair(f, nxt, circle=circle))
                # spec 15.6.7: a cut through all reads no depth, so its depth gives no entry.
                left_out.extend(_circle_notes(f, circle, params))
                continue
            pairs.append(_Pair(f, nxt, rect=rect))
            boxes.append(rect)
            left_out.extend(_sketch_notes(f, rect, params))
            p = params.get(nxt.depth_parameter or "")
            if p is not None and _kept_expression(p.expression):
                left_out.append(
                    f"{nxt.name}: depth {_mm(nxt.depth)} mm is written as a number; "
                    f"the expression {p.expression} is not kept"
                )
            if len(boxes) == 1 and nxt.operation == "join":
                left_out.append(f"{nxt.name}: written as a new body (there is nothing to join)")
        elif isinstance(f, ir.Extrude):
            if f.sketch in dropped:
                left_out.append(f"{f.name}: left out because its sketch is not written")
                dropped.add(f.id)
            else:
                _refuse(f"{f.name}: extrusion does not follow its sketch")
                dropped.add(f.id)
        elif isinstance(f, ir.Unsupported):
            _refuse(f"{f.name}: {f.reason}")
            dropped.add(f.id)
        else:
            _refuse(f"{f.name}: {_KIND_REFUSALS.get(type(f), 'not written yet')}")
            dropped.add(f.id)
    return pairs, refused, left_out


# ------------------------------------------------------------------ file custom properties (15.6.9)
def _storable(text: str) -> bool:
    """Whether XML can hold ``text`` as it is: none of the characters 15.6.9 refuses."""
    for ch in text:
        c = ord(ch)
        if c < CONTROL_BELOW or SURROGATES[0] <= c <= SURROGATES[1] or c in NONCHARACTERS:
            return False
    return True


def _property_problem(p: ir.Property) -> str | None:
    """The reason a file custom property is refused, or None; the first condition of 15.6.9 it fails."""
    text = p.value if p.type == "text" else ""
    if not _storable(p.name) or not _storable(text):
        return (
            "its name (or text) holds a character a part cannot store "
            "(a control character such as a line break)"
        )
    if _LINK.search(text) or ('"' in text and "@" in text):
        return "SOLIDWORKS would read this text as a link to another value"
    if p.type == "number" and isinstance(p.value, int) and not I4_RANGE[0] <= p.value <= I4_RANGE[1]:
        return f"the whole number {p.value} is outside the range a part stores"
    if p.type == "date" and date.fromisoformat(p.value) < FIRST_DATE:
        return f"a date before {FIRST_DATE.isoformat()} cannot be stored"
    return None


def _accept_properties(doc: ir.Document) -> tuple[list[ir.Property], list[str], list[str]]:
    """The accepted properties, the refusals, and what is left out (15.6.9, 15.6.7).

    Only accepted properties count towards the limit of 65,534; the ones after it are
    refused together, as one item for the design.
    """
    accepted: list[ir.Property] = []
    refused: list[str] = []
    left_out: list[str] = []
    over = False
    for p in doc.properties:
        why = _property_problem(p)
        if why is not None:
            entry = f"property {p.name}: {why}"
            refused.append(entry)
            left_out.append(f"{entry}; the part does not carry this property")
        elif len(accepted) < MAX_PROPERTIES:
            accepted.append(p)
        else:
            over = True
    if over:
        # spec question: 15.6.7's suffix names "this property", which one item for the design does
        # not have; the entry is the refusal's reason alone, as for any refused item.
        entry = f"more than {MAX_PROPERTIES:,} file custom properties"
        refused.append(entry)
        left_out.append(entry)
    return accepted, refused, left_out


def _element_text(text: str) -> str:
    """15.6.9's escaping for element text: ``&`` first, then ``<`` and ``>``; ``"`` stays."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _real_text(v: float) -> str:
    """A real number as typed (15.6.9): its repr, written out without an exponent, with a point."""
    text = repr(v)
    if "e" in text:
        text = format(Decimal(text), "f")
    return text if "." in text else text + ".0"


def _property_item(k: int, p: ir.Property, utc_offset: int) -> dict[str, Any]:
    """The k-th accepted property's item of ``props``, with exactly the fields of 15.6.9."""
    v = p.value
    vt = PROPERTY_VTS.get(p.type, "")
    if p.type == "number" and isinstance(v, int):
        text = stored = str(v)
        vt = "i4"  # spec 15.6.9 vt: a whole number
    elif p.type == "number":
        text, stored = _real_text(float(v)), f"{v:.6f}"  # spec 15.6.9: C's %f, six decimals
        vt = "r8"  # spec 15.6.9 vt: a real number
    elif p.type == "date":
        d = date.fromisoformat(v)
        text = f"{d.month}/{d.day}/{d.year}"
        noon = datetime(d.year, d.month, d.day, DATE_HOUR, tzinfo=UTC) - timedelta(minutes=utc_offset)
        stored = _iso(noon)
    elif p.type == "yesno":
        text = stored = "Yes" if v else "No"
    else:
        text = stored = v
    return {
        "name": p.name,
        "pid": FIRST_PID + k,
        "code": PROPERTY_CODES[p.type],
        "type_id": PROPERTY_TYPE_IDS[p.type],
        "vt": vt,
        "text": text,
        "xml_text": _element_text(text),
        "xml_value": _element_text(stored),
    }


def properties(accepted: list[ir.Property], utc_offset: int) -> tuple[list[dict], list[dict]]:
    """``props`` and ``props_by_name`` (15.6.9): the items in the design's order, and by name
    lower-cased, compared by code point, then by the name itself."""
    props = [_property_item(k, p, utc_offset) for k, p in enumerate(accepted)]
    return props, sorted(props, key=lambda item: (item["name"].lower(), item["name"]))


# ------------------------------------------------------------------ geometry (15.6.3)
def _sphere_merge(boxes: list[tuple[tuple, tuple]]) -> tuple[list[float], float, list[float]]:
    """The bounding sphere's centre and radius, and the centre Header2 computes (15.6.3)."""
    c: list[float] = []
    h: list[float] = []
    r = 0.0
    for n, (lo, hi) in enumerate(boxes):
        c2 = [(lo[a] + hi[a]) / 2 for a in range(3)]
        r2 = math.sqrt(_sq(hi[0] - lo[0]) + _sq(hi[1] - lo[1]) + _sq(hi[2] - lo[2])) / 2
        if n == 0:
            c, h, r = c2, list(c2), r2
            continue
        d = math.sqrt(_sq(c2[0] - c[0]) + _sq(c2[1] - c[1]) + _sq(c2[2] - c[2]))
        if d + r2 <= r:
            continue
        if d + r <= r2:
            c, h, r = c2, list(c2), r2
            continue
        big = (d + r + r2) / 2
        h = [c2[a] - (c2[a] - h[a]) / d * (big - r2) for a in range(3)]
        c = [c[a] + (c2[a] - c[a]) * (big - r) / d for a in range(3)]
        r = big
    return c, r, h


def _sq(x: float) -> float:
    return x * x  # spec 15.6 intro: x² is x * x


def _planes(solid: bool, lo: list[float], hi: list[float], m: list[float]) -> dict[str, dict]:
    # (u axis, v axis, normal axis) per plane, 15.6.3
    axes = {"front": (0, 1, 2), "top": (0, 2, 1), "right": (2, 1, 0)}
    half = [0.0, 0.0, 0.0]
    if solid:
        for a in range(3):
            e = hi[a] - lo[a]
            half[a] = e / 2 + e / 2 * PLANE_MARGIN
    out = {}
    for name, (u, v, _normal) in axes.items():
        hu, hv = (half[u], half[v]) if solid else EMPTY_PLANE_HALF
        pmin, pmax = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
        pmin[u], pmax[u] = m[u] - hu, m[u] + hu
        pmin[v], pmax[v] = m[v] - hv, m[v] + hv
        centre = [(pmin[a] + pmax[a]) / 2 for a in range(3)]
        radius = math.sqrt(_sq(pmax[0] - pmin[0]) + _sq(pmax[1] - pmin[1]) + _sq(pmax[2] - pmin[2])) / 2
        out[name] = {"hu": hu, "hv": hv, "min": pmin, "max": pmax, "centre": centre, "radius": radius}
    return out


# ------------------------------------------------------------------ dates and hashes
def key_hash(text: str) -> int:
    """UnQLite's key hash of 15.3.3 over the ASCII bytes of ``text``."""
    h = HASH_START
    for b in text.encode("ascii"):
        h = (h * HASH_FACTOR + b) % UNIT
    return h


def _clock(t: datetime) -> str:
    hour = t.hour % 12 or 12
    return f"{hour}:{t.minute:02d}:{t.second:02d} {'AM' if t.hour < 12 else 'PM'}"


def _long_date(t: datetime) -> str:
    return f"{WEEKDAYS[t.weekday()]}, {MONTHS[t.month - 1]} {t.day}, {t.year}"


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc(when: datetime) -> datetime:
    if when.tzinfo is None:
        return when.replace(tzinfo=UTC)
    return when.astimezone(UTC)


# ------------------------------------------------------------------ the hole's cut (15.6.2)
def _cut_item(uid: int, circle: dict, box: dict, boxes: int, unix: int, filetime: int) -> dict[str, Any]:
    """The features item of the hole's cut, by 15.6.2's second table.

    ``uid`` is its creation number, ``circle`` its sketch's item, ``box`` the box's
    extrusion item (the body it cuts) and ``boxes`` the number of boxes before it.
    """
    return {
        "name": CUT_NAME,
        "sketch": False,
        "cut": True,
        "log_modified": False,  # spec 15.6.2: no extrusion is logged modified
        "id": uid,
        "sketch_name": circle["name"],
        "sketch_id": circle["id"],
        "first": False,
        "merge": False,
        # The hole lies inside the box and leaves its box as it was (15.5.13).
        "centre": list(box["centre"]),
        "diagonal": box["diagonal"],
        "body_id": FIRST_BODY + boxes,
        "body_label": f"body{boxes + 1}",
        "target_id": box["body_id"],
        "target_label": box["body_label"],
        "target_uid": box["id"],
        "target_created": box["created"],
        "ring": [
            {"end": end, "uid": box["id"], "created": box["created"], "face": face} for end, face in RING
        ],
        "created": unix,
        "time": filetime,
        "cache_memo": 0.0,
        "counter_marks": CUT_COUNTER_MARKS,
        "counter_face1": 0,
        "counter_face2": 0,
        "counter_end": 0,
    }


def body_slots(bodies: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """``live_bodies``, ``body_links`` and ``builds`` from ``bodies`` (15.6.5).

    ``builds`` holds, per body, the feature that made it and then each feature that
    changed it, all with the body's ``time``, in the order of a hash table of 17 buckets
    keyed by the feature's node id: by the id modulo 17, and of two with the same
    remainder the one later in the list first (15.2.7.5).
    """
    live = [b for b in bodies if b["live"]]
    links = [{"new": b["id"], "old": old} for b in bodies for old in b["from"]]
    built = [{"feature": f, "time": b["time"]} for b in bodies for f in (b["feature"], *b["changed"])]
    order = sorted(range(len(built)), key=lambda i: (built[i]["feature"] % BUILD_BUCKETS, -i))
    return live, links, [built[i] for i in order]


# ------------------------------------------------------------------ plan (15.6.1)
def plan(doc: ir.Document, *, identity: Identity | None = None, allow_partial: bool = False) -> Plan:
    """The slot dict, what is left out and the feature names, by the steps of 15.6.1."""
    ir.validate(doc)  # step 1: an IRError passes through
    pairs, refused, left_out = _accept(doc)  # step 2
    accepted, prop_refused, prop_left_out = _accept_properties(doc)  # step 3
    refused += prop_refused
    left_out += prop_left_out
    if refused and not allow_partial:
        raise NativeWriteUnsupported(refused)
    if identity is None:  # step 5's values, made now so step 4 can use the times
        identity = Identity.new()
    if not 1 <= identity.key_index <= 999:
        raise ValueError(f"key_index {identity.key_index} is outside 1 to 999 (15.1.1.1)")
    stem = identity.file_stem if identity.file_stem is not None else doc.name
    if "/" in stem or "\\" in stem:
        raise ValueError("file_stem is a file name without a folder (15.6.6)")
    when = _utc(identity.when)
    unix = int(when.timestamp())
    filetime = (unix + FILETIME_EPOCH) * FILETIME_UNIT  # spec 15.6.5 doc.filetime

    # Step 4: features, bodies, the model, the planes and the header (15.6.2 to 15.6.4).
    features: list[dict] = []
    bodies: list[dict] = []
    names: dict[str, str] = {}
    counter = FIRST_ID
    box_items: list[dict] = []  # the boxes' extrusion items, in timeline order
    for k, pair in enumerate(pairs):
        sk, ex = pair.sketch, pair.extrude
        sname = f"Sketch{k + 1}"
        sketch = {
            "name": sname,
            "sketch": True,
            "circle": pair.circle is not None,
            "log_modified": pair.circle is None,  # spec 15.6.2, 15.2.2.2: a rectangle's sketch only
            "id": counter,
            "at_origin": False,
            "created": unix,
            "modified": unix,
            "time": filetime,
            "cache_memo": 0.0,
            "regen": SKETCH_REGEN,
        }
        counter += GAP_FIRST_SKETCH if k == 0 else GAP_LATER_SKETCH
        if pair.circle is not None:
            (cx, cy), r = pair.circle.centre, pair.circle.radius
            sketch.update({"centre": [cx, cy], "radius": r, "start": [cx + r, cy], "regen": CIRCLE_REGEN})
            extrusion = _cut_item(counter, sketch, box_items[0], len(box_items), unix, filetime)
            ename = extrusion["name"]
            target = bodies[0]
            target["live"] = False
            target["into"] = [extrusion["body_id"]]
            made_from = [target["id"]]
        else:
            x0, y0, x1, y1 = pair.rect.corners
            n = len(box_items)
            sketch["corners"] = [x0, y0, x1, y1]
            sketch["at_origin"] = x0 == 0.0 and y0 == 0.0
            ename = f"Boss-Extrude{n + 1}"
            depth = float(ex.depth)
            extrusion = {
                "name": ename,
                "sketch": False,
                "cut": False,
                "log_modified": False,  # spec 15.6.2: no extrusion is logged modified
                "id": counter,
                "corners": [x0, y0, x1, y1],
                "sketch_name": sname,
                "sketch_id": sketch["id"],
                "depth": depth,
                "depth_text": _mm(depth),
                "first": n == 0,
                "merge": n == 0,
                "centre": [(x0 + x1) / 2, (y0 + y1) / 2, depth / 2],
                "diagonal": math.sqrt(_sq(x1 - x0) + _sq(y1 - y0) + _sq(depth)),
                "body_id": FIRST_BODY + n,
                "body_label": f"body{n + 1}",
                "created": unix,
                "time": filetime,
                "cache_memo": 0.0,
                "cache_text": x1 * 0.2,  # spec 15.6.2 cache_text
                "counter_marks": COUNTER_MARKS,
                "counter_favorite": 0,
                "counter_face1": 0,
                "counter_face2": 0,
            }
            box_items.append(extrusion)
            made_from = []
        counter += 1
        features += [sketch, extrusion]
        b = len(bodies)
        bodies.append(
            {
                "id": FIRST_BODY + b,
                "name": ename,
                "label": f"body{b + 1}",
                "feature": extrusion["id"],
                "last": extrusion["id"],  # spec 15.6.4: nothing written changes a body after it is made
                "changed": [],
                "live": True,
                "from": made_from,
                "into": [],
                "regen": BODY_REGEN + 2 * b,
                "time": filetime,
            }
        )
        for f, part_name in ((sk, sname), (ex, ename)):
            names[f.id] = part_name
            names[f.name] = part_name

    # Every extrusion counts towards the stamps, a cut included (15.6.6); only boxes give
    # the model its box, its sphere and its planes (15.6.3).
    n = len(bodies)
    solid = bool(box_items)
    boxes = [
        ((f["corners"][0], f["corners"][1], 0.0), (f["corners"][2], f["corners"][3], f["depth"]))
        for f in box_items
    ]
    if solid:
        lo = [min(b[0][a] for b in boxes) for a in range(3)]
        hi = [max(b[1][a] for b in boxes) for a in range(3)]
        c, r, h = _sphere_merge(boxes)
        sphere, hdr_centre = [*c, r], h
    else:
        lo, hi = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
        sphere, hdr_centre = [0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    centre = [(lo[a] + hi[a]) / 2 for a in range(3)]
    planes = _planes(solid, lo, hi, centre)

    # The change stamps count extrusions only, a cut among them; file custom properties do not
    # change them (15.6.6).
    stamp = 102 if n == 0 else 100 + 20 * n  # spec 15.6.6 doc.stamp
    stamp2 = 101 + n * (n + 3)  # spec 15.6.6 doc.stamp2
    sketches = [f for f in features if f["sketch"]]
    s: dict[str, Any] = {
        "doc.name": DOC_NAME,
        "doc.unix": unix,
        "doc.filetime": filetime,
        "doc.created": unix,
        "doc.changed": unix,
        "doc.author": AUTHOR,
        "doc.stamp": stamp,
        "doc.stamp2": stamp2,
        "tpl.unix": unix,
        "tpl.unix2": unix,
        "features": features,
        "sketches": sketches,
        "bodies": bodies,
        "model.solid": solid,
        "model.min": lo,
        "model.max": hi,
        "model.centre": centre,
        "model.sphere": sphere,
        "model.origin_refs": sum(1 for f in sketches if f["at_origin"]),
        "hdr.centre": hdr_centre,
        "hdr.next_id": features[-1]["id"] + 1 if features else FIRST_ID,
        "fixed.id_base": stamp - 11 - len(features),  # spec 15.6.5 fixed.id_base
        "fixed.origin.regen": ORIGIN_REGEN,
    }
    for name, plane in planes.items():
        s[f"planes.{name}"] = plane
    for key in FIXED_KEYS:
        s[f"fixed.{key}.time"] = filetime

    # Step 5: identity and free slots (15.6.6).
    saved = datetime.fromtimestamp(unix, UTC)
    s.update(
        {
            "meta.created_iso": _iso(when),
            "meta.file_stem": stem,
            "meta.company": COMPANY,
            "meta.total_time": "0",
            "meta.utc_offset": 0,
            "exch.front": identity.exch_front,
            "exch.top": identity.exch_top,
            "exch.right": identity.exch_right,
            "exch.doc": identity.exch_doc,
            "exch.config": identity.exch_config,
            "exch.toc": [identity.exch_front, identity.exch_top, identity.exch_right],
            # spec 15.3.2, 15.6.6: an identity slot; the generator writes doc.unix's UTC fields
            "exch.time": {
                "year": saved.year,
                "month": saved.month,
                "day": saved.day,
                "hour": saved.hour,
                "minute": saved.minute,
                "second": saved.second,
            },
            "anim.guid": identity.anim_guid,
            "lw.flag": 0,
            "cmgr.created": filetime,
            "cmgr.texture": TEXTURE,
            "bio.os.platform": OS_VERSION[0],
            "bio.os.major": OS_VERSION[1],
            "bio.os.minor": OS_VERSION[2],
            "bio.os.build": OS_VERSION[3],
            "bio.locale": LOCALE,
            "config0.length_memo": 0.0,
            "config0.curvature_time": filetime,
            "config0.sketch_blocks_time": filetime,
            "config0.mass_block": False,
            "config0.mass": [0.0] * 12,
        }
    )
    for group in ("made", "open", "save"):
        s[f"bio.{group}.time"] = filetime
        s[f"bio.{group}.tag"] = 0
        s[f"bio.{group}.x"] = 0
    for group in ("made", "open"):
        for folder in ("system", "windows", "work", "temp", "template"):
            s[f"bio.{group}.{folder}"] = ""
    s["bio.save.folder"] = ""
    s["bio.save.file"] = ""
    s2, s3, s6 = math.sqrt(2.0), math.sqrt(3.0), math.sqrt(6.0)
    s["def.view.r"] = [1 / s2, -1 / s6, 1 / s3, 0.0, 2 / s6, 1 / s3, -1 / s2, -1 / s6, 1 / s3]
    s["def.view.c"] = [0.0, 0.0, 0.0]
    s["def.view.zoom"] = 1.0
    s["props"], s["props_by_name"] = properties(accepted, s["meta.utc_offset"])  # step 6
    derive(s)  # step 6
    return Plan(slots=s, left_out=left_out, names=names, identity=identity)


def derive(s: dict[str, Any]) -> dict[str, Any]:
    """Step 6: the slots of 15.6.5 that follow from the identity values, ``features`` and ``bodies``."""
    unix = s["doc.unix"]
    saved = datetime.fromtimestamp(unix, UTC)
    offset = timedelta(minutes=s.get("meta.utc_offset", 0))
    local = saved + offset
    created = datetime.strptime(s["meta.created_iso"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) + offset
    s["doc.iso"] = _iso(saved)
    s["meta.short_date"] = f"{local.month}/{local.day}/{local.year}"
    s["meta.long_date"] = _long_date(local)
    s["meta.created_text"] = f"{_long_date(created)} {_clock(created)}"
    s["meta.saved_text"] = f"{_long_date(local)} {_clock(local)}"
    for key in ("front", "top", "right", "doc", "config"):
        s[f"exch.hash.{key}"] = key_hash(s[f"exch.{key}"])
    s["live_bodies"], s["body_links"], s["builds"] = body_slots(s["bodies"])
    feats = s["features"]
    s["meta.kw_extrusions"] = sorted((f for f in feats if not f["sketch"]), key=lambda f: str(f["id"]))
    origin = {"id": 5, "name": "Origin", "origin": True}  # spec 15.6.5 meta.kw_sketches
    kw = [origin] + [{"id": f["id"], "name": f["name"], "origin": False} for f in feats if f["sketch"]]
    s["meta.kw_sketches"] = sorted(kw, key=lambda f: str(f["id"]))
    return s
