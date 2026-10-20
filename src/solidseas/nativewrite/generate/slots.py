"""Section 15.6: from a ``ParametricDocumentIR`` part and an :class:`Identity` to the slot dict.

:func:`plan` follows 15.6.1 step by step: validate the IR, accept or refuse
each item of the timeline (15.6.2), build ``features``, ``bodies`` and the
model, plane and header slots (15.6.3, 15.6.4), take or make the identity
values and fill every identity and free slot (15.6.6), then the slots derived
from them (15.6.5).

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
from datetime import UTC, datetime, timedelta
from typing import Any

from ...errors import SolidSeasError
from .. import ir

# spec question: 15.0.7 asks for "the dict of every slot, section by section" without saying
# whether it is flat or nested. The generator writes it flat by full slot name; the listing
# reader (listing.lookup) accepts flat, nested or mixed dicts, so either shape assembles.

# spec 15.6.7: a plain number: an optional sign, digits with at most one point, at most one unit
_PLAIN_NUMBER = re.compile(r"[+-]?(?=\.?\d)\d*\.?\d*(mm|cm|m|in|deg|\u00b0)?")
FIRST_ID = 26  # spec 15.6.2: the creation numbers count on from 26
GAP_AT_ORIGIN = 6  # spec 15.6.2: a sketch on the origin takes the counter and adds 6
GAP_OFF_ORIGIN = 7  # spec 15.6.2: off the origin, 7
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


def _number(v: float) -> str:
    """A number rounded to 8 decimals, trailing zeros and a trailing point removed (15.6.2)."""
    return f"{round(v, 8):.8f}".rstrip("0").rstrip(".")


def _mm(v: float) -> str:
    return _number(v * 1000)  # spec 15.6.2 depth_text: metres to millimetres


def _kept_expression(expression: str | None) -> bool:
    """Whether a parameter's expression is lost in the part: it is there and not a plain number."""
    return bool(expression) and not _PLAIN_NUMBER.fullmatch(expression.replace(" ", ""))


def _rectangle(s: ir.Sketch) -> tuple[_Rect | None, str | None]:
    """The sketch's corner rectangle, or the reason it is refused."""
    if tuple(map(tuple, (s.plane.origin, s.plane.x_dir, s.plane.y_dir))) != FRONT or (
        s.plane.offset not in (None, 0.0) or s.plane.face_point is not None
    ):
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


def _extrusion_problem(e: ir.Extrude, rect: _Rect, k: int) -> str | None:
    """The reason the k-th extrusion, which follows its sketch at once, is refused, or None.

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


_KIND_REFUSALS = {
    ir.Revolve: "revolves are not written yet",
    ir.Fillet: "fillets are not written yet",
    ir.Chamfer: "chamfers are not written yet",
    ir.Hole: "holes are not written yet",
    ir.Pattern: "patterns are not written yet",
    ir.Mirror: "mirrors are not written yet",
}


def _sketch_notes(s: ir.Sketch, rect: _Rect, params: dict[str, ir.Parameter]) -> list[str]:
    """15.6.7: what of an accepted sketch the part does not carry."""
    notes = []
    for d in s.dimensions:
        if d.kind in ir.ANGLE_DIMENSIONS:
            value = f"{_number(math.degrees(d.value))} degrees"
        else:
            value = f"{_mm(d.value)} mm"
        p = params.get(d.parameter or "")
        entry = (
            f"{s.name}: dimension {p.name if p is not None else d.id} ({d.kind}, {value}) is kept as "
            "geometry only; the rectangle has no driving dimensions in the part"
        )
        if p is not None and _kept_expression(p.expression):
            entry += f"; its expression {p.expression} is not kept"
        notes.append(entry)
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


def _accept(doc: ir.Document) -> tuple[list, list[str], list[str]]:
    """The accepted pairs (sketch, extrusion, rectangle), the refusals, and what is left out.

    ``left_out`` is in timeline order and holds the refusals too, as 15.6.7 lists them
    when ``allow_partial`` is given.
    """
    items = doc.features
    params = {p.name: p for p in doc.parameters}
    users: dict[str, list] = {}
    for f in items:
        if isinstance(f, (ir.Extrude, ir.Revolve)):
            users.setdefault(f.sketch, []).append(f)
    pairs: list = []
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
            rect, why = _rectangle(f)
            mine = users.get(f.id, [])
            if why is None and not (len(mine) == 1 and mine[0] is nxt and isinstance(nxt, ir.Extrude)):
                why = "sketch not followed by its extrusion"
            if why is not None:
                _refuse(f"{f.name}: {why}")
                dropped.add(f.id)
                continue
            problem = _extrusion_problem(nxt, rect, len(pairs))
            i += 1
            if problem is not None:
                _refuse(f"{nxt.name}: {problem}")
                dropped.update((f.id, nxt.id))
                # spec question: 15.6.2 writes sketches only in pairs, so a sketch whose extrusion
                # is refused cannot be written either; it is reported as left out with it.
                left_out.append(f"{f.name}: left out with {nxt.name}, which is not written")
                continue
            pairs.append((f, nxt, rect))
            left_out.extend(_sketch_notes(f, rect, params))
            p = params.get(nxt.depth_parameter or "")
            if p is not None and _kept_expression(p.expression):
                left_out.append(
                    f"{nxt.name}: depth {_mm(nxt.depth)} mm is written as a number; "
                    f"the expression {p.expression} is not kept"
                )
            if len(pairs) == 1 and nxt.operation == "join":
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


# ------------------------------------------------------------------ plan (15.6.1)
def plan(doc: ir.Document, *, identity: Identity | None = None, allow_partial: bool = False) -> Plan:
    """The slot dict, what is left out and the feature names, by the steps of 15.6.1."""
    ir.validate(doc)  # step 1: an IRError passes through
    pairs, refused, left_out = _accept(doc)  # step 2
    if refused and not allow_partial:
        raise NativeWriteUnsupported(refused)
    if identity is None:  # step 4's values, made now so step 3 can use the times
        identity = Identity.new()
    if not 1 <= identity.key_index <= 999:
        raise ValueError(f"key_index {identity.key_index} is outside 1 to 999 (15.1.1.1)")
    stem = identity.file_stem if identity.file_stem is not None else doc.name
    if "/" in stem or "\\" in stem:
        raise ValueError("file_stem is a file name without a folder (15.6.6)")
    when = _utc(identity.when)
    unix = int(when.timestamp())
    filetime = (unix + FILETIME_EPOCH) * FILETIME_UNIT  # spec 15.6.5 doc.filetime

    # Step 3: features, bodies, the model, the planes and the header (15.6.2 to 15.6.4).
    features: list[dict] = []
    bodies: list[dict] = []
    names: dict[str, str] = {}
    counter = FIRST_ID
    for k, (sk, ex, rect) in enumerate(pairs):
        x0, y0, x1, y1 = rect.corners
        at_origin = x0 == 0.0 and y0 == 0.0
        sname, ename = f"Sketch{k + 1}", f"Boss-Extrude{k + 1}"
        sketch = {
            "name": sname,
            "sketch": True,
            "id": counter,
            "corners": [x0, y0, x1, y1],
            "at_origin": at_origin,
            "created": unix,
            "modified": unix,
            "time": filetime,
            "cache_memo": 0.0,
            "regen": SKETCH_REGEN,
        }
        counter += GAP_AT_ORIGIN if at_origin else GAP_OFF_ORIGIN
        depth = float(ex.depth)
        extrusion = {
            "name": ename,
            "sketch": False,
            "id": counter,
            "corners": [x0, y0, x1, y1],
            "sketch_name": sname,
            "sketch_id": sketch["id"],
            "depth": depth,
            "depth_text": _mm(depth),
            "first": k == 0,
            "merge": k == 0,
            "centre": [(x0 + x1) / 2, (y0 + y1) / 2, depth / 2],
            "diagonal": math.sqrt(_sq(x1 - x0) + _sq(y1 - y0) + _sq(depth)),
            "body_id": FIRST_BODY + k,
            "body_label": f"body{k + 1}",
            "created": unix,
            "time": filetime,
            "cache_memo": 0.0,
            "cache_text": x1 * 0.2,  # spec 15.6.2 cache_text
            "counter_marks": COUNTER_MARKS,
            "counter_favorite": 0,
            "counter_face1": 0,
            "counter_face2": 0,
        }
        counter += 1
        features += [sketch, extrusion]
        bodies.append(
            {
                "id": FIRST_BODY + k,
                "name": ename,
                "label": f"body{k + 1}",
                "feature": extrusion["id"],
                "regen": BODY_REGEN + 2 * k,
                "time": filetime,
            }
        )
        for f, part_name in ((sk, sname), (ex, ename)):
            names[f.id] = part_name
            names[f.name] = part_name

    n = len(bodies)
    solid = n > 0
    boxes = [
        ((f["corners"][0], f["corners"][1], 0.0), (f["corners"][2], f["corners"][3], f["depth"]))
        for f in features
        if not f["sketch"]
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

    # Step 4: identity and free slots (15.6.6).
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
    derive(s)  # step 5
    return Plan(slots=s, left_out=left_out, names=names, identity=identity)


def derive(s: dict[str, Any]) -> dict[str, Any]:
    """Step 5: the slots of 15.6.5 that follow from the identity values and ``features``."""
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
    s["exch.time"] = {
        "year": saved.year,
        "month": saved.month,
        "day": saved.day,
        "hour": saved.hour,
        "minute": saved.minute,
        "second": saved.second,
    }
    for key in ("front", "top", "right", "doc", "config"):
        s[f"exch.hash.{key}"] = key_hash(s[f"exch.{key}"])
    feats = s["features"]
    s["meta.kw_extrusions"] = sorted((f for f in feats if not f["sketch"]), key=lambda f: str(f["id"]))
    origin = {"id": 5, "name": "Origin", "origin": True}  # spec 15.6.5 meta.kw_sketches
    kw = [origin] + [{"id": f["id"], "name": f["name"], "origin": False} for f in feats if f["sketch"]]
    s["meta.kw_sketches"] = sorted(kw, key=lambda f: str(f["id"]))
    return s
