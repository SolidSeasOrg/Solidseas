"""Section 15.6 on the analysis side: the fixtures as ``ParametricDocumentIR`` designs, and
the rules that turn a design and its identity into the one slot dict.

:func:`fixture_design` writes down what o01, o02, o03, o04, o07 and o12 are, as the IR would
hold them (o04 is o02 with three file custom properties). :func:`design_slots` is the
analysis side's own implementation of section 15.6: every design and derived slot comes
from the IR by its rules; only the identity
and free slots (the paths of ``IDENTITY``, ``FEATURE_IDENTITY`` and ``BODY_IDENTITY``)
come from ``identity``. The test hands it the values read from a fixture
(:func:`.full.identity_of`) and compares every member with the fixture's, byte for byte.
:func:`generator_identity` gives the values the generator writes instead (15.6.6).
"""

from __future__ import annotations

import math
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from solidseas.nativewrite import ir

# ------------------------------------------------------------------ the identity and free slots (15.6.6)
FIXED_KEYS = (
    "comments", "favorites", "history", "selsets", "sensors", "binder", "annotations", "notes",
    "notes_end", "surface", "solid", "lights", "markups", "material", "front", "top", "right", "origin",
)
_BIO_PATHS = ("system", "windows", "work", "temp", "template")
IDENTITY = (
    "doc.name", "doc.unix", "doc.created", "doc.changed", "doc.stamp", "doc.stamp2", "doc.author",
    "tpl.unix", "tpl.unix2",
    "meta.created_iso", "meta.file_stem", "meta.company", "meta.total_time", "meta.utc_offset",
    "exch.front", "exch.top", "exch.right", "exch.doc", "exch.config", "exch.toc", "exch.time",
    "anim.guid", "lw.flag", "cmgr.created", "cmgr.texture",
    "bio.os.platform", "bio.os.major", "bio.os.minor", "bio.os.build", "bio.locale",
    *(f"bio.{g}.{k}" for g in ("made", "open", "save") for k in ("time", "tag", "x")),
    *(f"bio.{g}.{k}" for g in ("made", "open") for k in _BIO_PATHS),
    "bio.save.folder", "bio.save.file",
    "def.view.r", "def.view.c", "def.view.zoom",
    "config0.length_memo", "config0.curvature_time", "config0.sketch_blocks_time",
    "config0.mass_block", "config0.mass",
    *(f"fixed.{k}.time" for k in FIXED_KEYS), "fixed.origin.regen",
)
FEATURE_IDENTITY = ("created", "modified", "time", "cache_memo", "regen", "cache_text",
                    "counter_marks", "counter_favorite", "counter_face1", "counter_face2", "counter_end")
BODY_IDENTITY = ("regen", "time")

TEXTURE = "<SystemTexture>\\graphics\\materials\\color.p2m"
FILETIME_EPOCH = 11644473600  # seconds from 1601-01-01 to 1970-01-01


@dataclass(frozen=True)
class Identity:
    """The identity values of one file (15.6.6): the save instant, the container key's
    index (15.1.1.1), the six random GUIDs, and the file name at save."""

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
    def new(cls, file_stem: str | None = None) -> Identity:
        return cls(
            when=datetime.now(UTC).replace(microsecond=0),
            key_index=1 + secrets.randbelow(999),
            anim_guid="{" + str(uuid.uuid4()).upper() + "}",
            exch_front=str(uuid.uuid4()), exch_top=str(uuid.uuid4()), exch_right=str(uuid.uuid4()),
            exch_doc=str(uuid.uuid4()), exch_config=str(uuid.uuid4()),
            file_stem=file_stem,
        )


# ------------------------------------------------------------------ the fixtures as designs
def _rectangle(sid: str, name: str, x0: float, y0: float, x1: float, y1: float) -> ir.Sketch:
    """A corner rectangle with its relations: horizontal and vertical lines, shared corners,
    and the first corner coincident with the origin when it lies there."""
    pts = [ir.Point("p1", x0, y0), ir.Point("p2", x1, y0), ir.Point("p3", x1, y1), ir.Point("p4", x0, y1)]
    lines = [ir.Curve(f"l{k + 1}", "line", [f"p{k + 1}", f"p{(k + 1) % 4 + 1}"]) for k in range(4)]
    cons = [ir.Constraint("c1", "horizontal", curves=["l1"]), ir.Constraint("c2", "vertical", curves=["l2"]),
            ir.Constraint("c3", "horizontal", curves=["l3"]), ir.Constraint("c4", "vertical", curves=["l4"])]
    if (x0, y0) == (0.0, 0.0):
        cons.append(ir.Constraint("c5", "coincident", points=["p1", ir.ORIGIN]))
    return ir.Sketch(sid, name, ir.Plane.named("xy"), pts, lines, cons)


def circle_sketch(sid: str, name: str, cx: float, cy: float, r: float) -> ir.Sketch:
    """A circle on the Front Plane, by its centre and radius (15.6.2)."""
    return ir.Sketch(sid, name, ir.Plane.named("xy"), [ir.Point("c", cx, cy)],
                     [ir.Curve("k1", "circle", ["c"], radius=r)])


def through_cut(eid: str, name: str, sketch: str) -> ir.Extrude:
    """A cut through all in both directions (15.6.2); the depth is not used."""
    return ir.Extrude(eid, name, sketch, 0.0, operation="cut", direction="midplane", end="through_all")


# The file custom properties each fixture was given (its kit instructions), as the IR holds them.
FIXTURE_PROPERTIES: dict[str, list[ir.Property]] = {
    "o04": [ir.Property("PartNo", "ORACLE-PN-123"), ir.Property("Description", "Oracle test box"),
            ir.Property("Qty", 42, "number")],
    # o14's five typed file properties; its configuration property and its two linked
    # properties (Mass, Material) are outside what the generator writes (15.6.9).
    "o14": [ir.Property("TextProp", "Plain text value"), ir.Property("DateProp", "2024-03-15", "date"),
            ir.Property("NumberProp", 7, "number"), ir.Property("DoubleProp", 3.25, "number"),
            ir.Property("YesNoProp", True, "yesno")],
}


def fixture_design(name: str) -> ir.Document:
    """What fixture ``name`` (o01, o02, o03, o04, o07 or o12) is, as a ParametricDocumentIR part."""
    boxes = {
        "o01": [],
        "o02": [((0.0, 0.0, 0.01, 0.02), 0.03)],
        "o03": [((0.0, 0.0, 0.01, 0.02), 0.03)],
        "o04": [((0.0, 0.0, 0.01, 0.02), 0.03)],
        "o07": [((0.0, 0.0, 0.01, 0.02), 0.031)],
        "o12": [((0.0, 0.0, 0.01, 0.02), 0.03), ((0.03, 0.0, 0.04, 0.02), 0.01)],
    }[name[:3]]
    features: list = []
    for k, (corners, depth) in enumerate(boxes):
        features.append(_rectangle(f"s{k + 1}", f"Sketch{k + 1}", *corners))
        features.append(ir.Extrude(f"e{k + 1}", f"Extrude{k + 1}", f"s{k + 1}", depth))
    props = list(FIXTURE_PROPERTIES.get(name[:3], []))
    return ir.validate(ir.Document("box", features, properties=props))


# ------------------------------------------------------------------ 15.6.9: file custom properties
_PROP_KINDS = {"text": (0, 30), "date": (1, 64), "number": (2, 3), "yesno": (3, 11)}  # code, TypeID
I4 = (-(2**31), 2**31 - 1)


def xml_escape_text(text: str) -> str:
    """15.6.9: element text as SOLIDWORKS writes it: ``&``, ``<`` and ``>`` escaped, ``"`` kept."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def real_text(v: float) -> str:
    """15.6.9: a real number as typed: the shortest decimal that reads back as ``v``, without
    an exponent, with at least one digit after the point."""
    text = repr(v)
    if "e" in text or "E" in text:
        text = format(Decimal(text), "f")
    return text if "." in text else text + ".0"


def property_refusal(p: ir.Property) -> str | None:
    """15.6.9: why the generator does not write property ``p``, or None when it does."""
    def bad(t: str) -> bool:
        return any(ord(c) < 0x20 or 0xD800 <= ord(c) <= 0xDFFF or c in "\ufffe\uffff" for c in t)

    stored = "a character a part cannot store (a control character such as a line break)"
    if bad(p.name):
        return f"property {p.name}: its name holds {stored}"
    if p.type == "text":
        if bad(p.value):
            return f"property {p.name}: its text holds {stored}"
        if "$prp" in p.value.lower() or ('"' in p.value and "@" in p.value):
            return f"property {p.name}: SOLIDWORKS would read this text as a link to another value"
    if p.type == "number" and isinstance(p.value, int) and not I4[0] <= p.value <= I4[1]:
        return f"property {p.name}: the whole number {p.value} is outside the range a part stores"
    if p.type == "date" and date.fromisoformat(p.value) < date(1601, 1, 1):
        return f"property {p.name}: a date before 1601-01-01 cannot be stored"
    return None


def props_of(doc: ir.Document, utc_offset: int) -> list[dict]:
    """The ``props`` items (15.6.9) of the properties the generator writes, in the design's order."""
    items = []
    for p in doc.properties:
        if property_refusal(p):
            continue
        code, type_id = _PROP_KINDS[p.type]
        if p.type == "text":
            vt, text, value = "lpstr", p.value, p.value
        elif p.type == "number" and isinstance(p.value, int):
            vt, text = "i4", str(p.value)
            value = text
        elif p.type == "number":
            vt, text, value = "r8", real_text(float(p.value)), f"{float(p.value):.6f}"
        elif p.type == "date":
            d = date.fromisoformat(p.value)
            at = datetime(d.year, d.month, d.day, 12, tzinfo=UTC) - timedelta(minutes=utc_offset)
            vt, text, value = "filetime", f"{d.month}/{d.day}/{d.year}", at.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            vt = "bool"
            text = value = "Yes" if p.value else "No"
        items.append({"name": p.name, "pid": 3 + len(items), "code": code, "type_id": type_id, "vt": vt,
                      "text": text, "xml_text": xml_escape_text(text), "xml_value": xml_escape_text(value)})
    return items


def props_by_name(items: list[dict]) -> list[dict]:
    """15.6.9: the name dictionary's order, by name compared without case."""
    return sorted(items, key=lambda q: (q["name"].lower(), q["name"]))


# ------------------------------------------------------------------ 15.6.2: the features
def _corners(s: ir.Sketch) -> tuple[list[float], bool]:
    """The sorted corners of a corner rectangle, and whether its minimum corner is the origin."""
    if s.plane.base != "xy" or s.suppressed:
        raise ValueError(f"{s.name}: sketch on a plane other than the Front Plane, or suppressed")
    pts = {p.id: (p.x, p.y) for p in s.points}
    pts[ir.ORIGIN] = (0.0, 0.0)
    if len(s.curves) != 4 or any(c.kind != "line" or c.construction for c in s.curves):
        raise ValueError(f"{s.name}: sketch is not a single corner rectangle")
    ends = [pts[q] for c in s.curves for q in c.points]
    corners = sorted(set(ends))
    if len(corners) != 4 or any(ends.count(p) != 2 for p in corners):
        raise ValueError(f"{s.name}: sketch is not a single corner rectangle")
    for c in s.curves:
        (ax, ay), (bx, by) = (pts[q] for q in c.points)
        if ax != bx and ay != by:
            raise ValueError(f"{s.name}: rectangle is not aligned with the sketch axes")
    xs, ys = [p[0] for p in corners], [p[1] for p in corners]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    if not (x1 > x0 and y1 > y0):
        raise ValueError(f"{s.name}: degenerate rectangle")
    return [x0, y0, x1, y1], (x0, y0) == (0.0, 0.0)


def is_circle(s) -> bool:
    """A sketch whose curves are exactly one circle (15.6.2). A sketch of several circles is
    refused before this is asked; one that mixes a circle with lines is a rectangle's."""
    return isinstance(s, ir.Sketch) and len(s.curves) == 1 and s.curves[0].kind == "circle"


def _circle(s: ir.Sketch) -> tuple[float, float, float]:
    """The centre and radius of a circle sketch, or the reason it is refused (15.6.2)."""
    if s.plane.base != "xy" or s.suppressed:
        raise ValueError(f"{s.name}: sketch on a plane other than the Front Plane, or suppressed")
    c = s.curves[0]
    if c.construction:
        # 15.6.2 gives a construction circle the reason of a sketch of several circles
        raise ValueError(f"{s.name}: a sketch with more than one circle is not written yet")
    pts = {p.id: (p.x, p.y) for p in s.points}
    pts[ir.ORIGIN] = (0.0, 0.0)
    cx, cy = pts[c.points[0]]
    r = float(c.radius)
    if not r > 0:
        raise ValueError(f"{s.name}: degenerate circle")
    return float(cx), float(cy), r


def depth_text(depth: float) -> str:
    """15.1.2.2: the depth in millimetres, rounded to 8 decimals, without trailing zeros."""
    return f"{round(depth * 1000, 8):.8f}".rstrip("0").rstrip(".") or "0"


# 15.5.13 and 15.6.2: the box faces a cut's ring names, in order: (end face?, face number).
RING = ((False, 4), (True, 1), (False, 3), (True, 0), (False, 1))


def features_of(doc: ir.Document) -> list[dict]:
    """The design and derived fields of the ``features`` items (15.6.2): corner rectangles
    each extruded blind, then at most one circle cut through all in both directions."""
    items: list[dict] = []
    timeline = list(doc.features)
    if len(timeline) % 2:
        raise ValueError("sketch not followed by its extrusion")
    uid = 26
    boxes: list[dict] = []
    cuts = 0
    for k in range(len(timeline) // 2):
        s, e = timeline[2 * k], timeline[2 * k + 1]
        if not isinstance(s, ir.Sketch) or not isinstance(e, ir.Extrude) or e.sketch != s.id:
            raise ValueError(f"{s.name}: sketch not followed by its extrusion")
        if e.suppressed:
            raise ValueError(f"{e.name}: suppressed extrusion")
        n_sketch = k + 1
        if len(s.curves) > 1 and all(c.kind == "circle" for c in s.curves):
            raise ValueError(f"{s.name}: a sketch with more than one circle is not written yet")
        if is_circle(s):
            cx, cy, r = _circle(s)
            if e.operation != "cut":
                raise ValueError(f"{e.name}: a circle is written only as the profile of a cut")
            if e.end != "through_all" or e.direction != "midplane":
                raise ValueError(f"{e.name}: only a cut through all in both directions is written")
            if e.profile is not None and e.profile != [[s.curves[0].id]]:
                raise ValueError(f"{e.name}: profile is not the whole circle")
            if cuts or len(boxes) != 1 or 2 * k + 2 != len(timeline):
                raise ValueError(
                    f"{e.name}: a cut is written only as the last feature of a part with one box")
            box = boxes[0]
            x0, y0, x1, y1 = box["corners"]
            if not (x0 < cx - r and cx + r < x1 and y0 < cy - r and cy + r < y1):
                raise ValueError(f"{e.name}: the circle is not inside the box's rectangle")
            sketch = {"name": f"Sketch{n_sketch}", "sketch": True, "circle": True, "log_modified": False,
                      "id": uid,
                      "centre": [cx, cy], "radius": r, "start": [cx + r, cy], "at_origin": False}
            uid += 6 if n_sketch == 1 else 7
            cuts += 1
            ext = {
                "name": f"Cut-Extrude{cuts}", "sketch": False, "cut": True, "log_modified": False, "id": uid,
                "sketch_name": sketch["name"], "sketch_id": sketch["id"], "first": False, "merge": False,
                "centre": box["centre"], "diagonal": box["diagonal"],
                "body_id": 101 + len(boxes), "body_label": f"body{len(boxes) + 1}",
                "target_id": box["body_id"], "target_label": box["body_label"], "target_uid": box["id"],
                "ring": [{"end": end, "uid": box["id"], "face": face} for end, face in RING],
            }
            uid += 1
            items += [sketch, ext]
            continue
        corners, at_origin = _corners(s)  # the sketch first: its extrusion depends on it
        if e.end != "blind" or e.direction != "forward":
            raise ValueError(f"{e.name}: only blind extrusions towards the sketch normal are written")
        if k == 0 and e.operation == "cut" or k > 0 and e.operation != "new_body":
            raise ValueError(f"{e.name}: operation {e.operation} is not written")
        x0, y0, x1, y1 = corners
        sketch = {"name": f"Sketch{n_sketch}", "sketch": True, "circle": False, "log_modified": True,
                  "id": uid,
                  "corners": corners,
                  "at_origin": at_origin}
        uid += 6 if n_sketch == 1 else 7
        depth = float(e.depth)
        ext = {
            "name": f"Boss-Extrude{k + 1}", "sketch": False, "cut": False, "log_modified": False, "id": uid,
            "sketch_name": sketch["name"], "sketch_id": sketch["id"], "depth": depth,
            "depth_text": depth_text(depth), "corners": list(corners), "first": k == 0, "merge": k == 0,
            "centre": [(x0 + x1) / 2, (y0 + y1) / 2, depth / 2],
            "diagonal": math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2 + depth**2),
            "body_id": 101 + k, "body_label": f"body{k + 1}",
        }
        uid += 1
        boxes.append(ext)
        items += [sketch, ext]
    return items


def bodies_of(features: list[dict]) -> list[dict]:
    """The ``bodies`` items (15.6.4), identity fields aside: one per extrusion; a cut's body
    is made from the body it cuts, which it uses up."""
    bodies: list[dict] = []
    by_id: dict[int, dict] = {}
    for f in features:
        if f["sketch"]:
            continue
        b = {"id": f["body_id"], "name": f["name"], "label": f["body_label"], "feature": f["id"],
             "last": f["id"], "changed": [], "live": True, "from": [], "into": []}
        if f["cut"]:
            old = by_id[f["target_id"]]
            old["live"], old["into"] = False, old["into"] + [b["id"]]
            b["from"] = [old["id"]]
        bodies.append(b)
        by_id[b["id"]] = b
    return bodies


def builds_of(bodies: list[dict]) -> list[dict]:
    """15.2.7.5: one item per feature that made or changed a body, with that body's time,
    ordered by the feature's creation number modulo 17, and of two with the same remainder
    the later first."""
    items = [(f, b["time"]) for b in bodies for f in [b["feature"], *b["changed"]]]
    order = sorted(range(len(items)), key=lambda k: (items[k][0] % 17, -k))
    return [{"feature": items[k][0], "time": items[k][1]} for k in order]


def body_links(bodies: list[dict]) -> list[dict]:
    """15.2.7.4: each body a cut made, with the body it was made from."""
    return [{"new": b["id"], "old": old} for b in bodies for old in b["from"]]


# ------------------------------------------------------------------ 15.6.3: the model box, sphere and planes
def _box_sphere(lo, hi):
    c = [(a + b) / 2 for a, b in zip(lo, hi, strict=True)]
    r = math.sqrt((hi[0] - lo[0]) ** 2 + (hi[1] - lo[1]) ** 2 + (hi[2] - lo[2]) ** 2) / 2
    return c, r


def spheres(boxes) -> tuple[list[float], list[float]]:
    """``model.sphere`` (centre and radius) and ``hdr.centre``, by the merge of 15.6.3."""
    c, r = _box_sphere(*boxes[0])
    h = c
    for lo, hi in boxes[1:]:
        c2, r2 = _box_sphere(lo, hi)
        d = math.sqrt((c2[0] - c[0]) ** 2 + (c2[1] - c[1]) ** 2 + (c2[2] - c[2]) ** 2)
        if d + r2 <= r:
            continue
        if d + r <= r2:
            c, h, r = c2, c2, r2
            continue
        big = (d + r + r2) / 2
        h = [q - (q - p) / d * (big - r2) for p, q in zip(h, c2, strict=True)]
        c = [p + (q - p) * (big - r) / d for p, q in zip(c, c2, strict=True)]
        r = big
    return c + [r], h


def plane_slots(lo, hi, centre, solid: bool) -> dict:
    axes = {"front": (0, 1), "top": (0, 2), "right": (2, 1)}
    out = {}
    for name, (u, v) in axes.items():
        if solid:
            eu, ev = hi[u] - lo[u], hi[v] - lo[v]
            hu, hv = eu / 2 + eu / 2 * 0.1, ev / 2 + ev / 2 * 0.1
        else:
            hu, hv = 0.08899, 0.05500000000000001
        mn, mx = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
        mn[u], mx[u], mn[v], mx[v] = centre[u] - hu, centre[u] + hu, centre[v] - hv, centre[v] + hv
        out[name] = {
            "hu": hu, "hv": hv, "min": mn, "max": mx,
            "centre": [(mn[k] + mx[k]) / 2 for k in range(3)],
            "radius": math.sqrt((mx[0] - mn[0]) ** 2 + (mx[1] - mn[1]) ** 2 + (mx[2] - mn[2]) ** 2) / 2,
        }
    return out


# ------------------------------------------------------------------ 15.6.6: the generator's identity values
def isometric() -> list[float]:
    """15.2.11.2: the isometric rotation by rows, in double precision."""
    s2, s3, s6 = math.sqrt(2.0), math.sqrt(3.0), math.sqrt(6.0)
    return [1 / s2, -1 / s6, 1 / s3, 0.0, 2 / s6, 1 / s3, -1 / s2, -1 / s6, 1 / s3]


def generator_identity(doc: ir.Document, ident: Identity) -> dict:
    """The identity and free slots the generator writes for ``doc`` (15.6.6)."""
    n = sum(1 for f in doc.features if isinstance(f, ir.Extrude))
    unix = int(ident.when.timestamp())
    ft = (unix + FILETIME_EPOCH) * 10_000_000
    iso = ident.when.strftime("%Y-%m-%dT%H:%M:%SZ")
    group = {"time": ft, "tag": 0, "x": 0}
    out = {
        "doc": {"name": "Part1", "unix": unix, "created": unix, "changed": unix,
                "stamp": 102 if n == 0 else 100 + 20 * n, "stamp2": 101 + n * (n + 3), "author": "SolidSeas"},
        "tpl": {"unix": unix, "unix2": unix},
        "meta": {"created_iso": iso, "file_stem": doc.name if ident.file_stem is None else ident.file_stem,
                 "company": "SolidSeas", "total_time": "0", "utc_offset": 0},
        "exch": {"front": ident.exch_front, "top": ident.exch_top, "right": ident.exch_right,
                 "doc": ident.exch_doc, "config": ident.exch_config,
                 "toc": [ident.exch_front, ident.exch_top, ident.exch_right],
                 "time": {"year": ident.when.year, "month": ident.when.month, "day": ident.when.day,
                          "hour": ident.when.hour, "minute": ident.when.minute, "second": ident.when.second}},
        "anim": {"guid": ident.anim_guid},
        "lw": {"flag": 0},
        "cmgr": {"created": ft, "texture": TEXTURE},
        "bio": {"os": {"platform": 2, "major": 10, "minor": 0, "build": 0}, "locale": 1033,
                "made": dict(group, **{k: "" for k in _BIO_PATHS}),
                "open": dict(group, **{k: "" for k in _BIO_PATHS}),
                "save": dict(group, folder="", file="")},
        "def": {"view": {"r": isometric(), "c": [0.0, 0.0, 0.0], "zoom": 1.0}},
        "config0": {"length_memo": 0.0, "curvature_time": ft, "sketch_blocks_time": ft,
                    "mass_block": False, "mass": [0.0] * 12},
        "fixed": {k: {"time": ft} for k in FIXED_KEYS},
    }
    out["fixed"]["origin"]["regen"] = 102
    feats = []
    for f in features_of(doc):
        item = {"created": unix, "time": ft, "cache_memo": 0.0}
        if f["sketch"]:
            item.update(modified=unix, regen=102 if f["circle"] else 103)
        elif f["cut"]:
            item.update(counter_marks=14, counter_face1=0, counter_face2=0, counter_end=0)
        else:
            item.update(cache_text=f["corners"][2] * 0.2, counter_marks=7, counter_favorite=0,
                        counter_face1=0, counter_face2=0)
        feats.append(item)
    out["features"] = feats
    out["bodies"] = [{"regen": 1151 + 2 * k, "time": ft} for k in range(n)]
    return out


# ------------------------------------------------------------------ 15.6: the whole dict
_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December")


def _long(t: datetime) -> str:
    return f"{_DAYS[t.weekday()]}, {_MONTHS[t.month - 1]} {t.day}, {t.year}"


def _long_time(t: datetime) -> str:
    return f"{_long(t)} {t.hour % 12 or 12}:{t.minute:02d}:{t.second:02d} {'AM' if t.hour < 12 else 'PM'}"


def _key_hash(text: str) -> int:
    h = 5381
    for b in text.encode("ascii"):
        h = (h * 33 + b) & 0xFFFFFFFF
    return h


def _get(d: dict, path: str):
    for p in path.split("."):
        d = d[p]
    return d


def _put(d: dict, path: str, value) -> None:
    parts = path.split(".")
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = value


def design_slots(doc: ir.Document, identity: dict) -> dict:
    """Every slot of section 15.6 for design ``doc``: design and derived slots by the rules,
    identity and free slots from ``identity`` (the shape :func:`generator_identity` gives)."""
    ir.validate(doc)
    features = features_of(doc)
    s: dict = {}
    for path in IDENTITY:
        _put(s, path, _get(identity, path))
    for f, extra in zip(features, identity["features"], strict=True):
        f.update({k: extra[k] for k in FEATURE_IDENTITY if k in extra})
    exts = [f for f in features if not f["sketch"]]
    by_id = {f["id"]: f for f in features}
    for f in exts:  # 15.6.2: a cut names its box's faces by the box's own creation time
        if f["cut"]:
            f["target_created"] = by_id[f["target_uid"]]["created"]
            for e in f["ring"]:
                e["created"] = by_id[e["uid"]]["created"]
    bodies = bodies_of(features)
    for b, extra in zip(bodies, identity["bodies"], strict=True):
        b.update({k: extra[k] for k in BODY_IDENTITY})
    s["features"] = features
    s["sketches"] = [f for f in features if f["sketch"]]
    s["bodies"] = bodies
    s["live_bodies"] = [b for b in bodies if b["live"]]
    s["body_links"] = body_links(bodies)
    s["builds"] = builds_of(bodies)

    # 15.6.3: the model box, the bounding sphere and the planes' display: the boxes alone
    boxes = [([f["corners"][0], f["corners"][1], 0.0], [f["corners"][2], f["corners"][3], f["depth"]])
             for f in exts if not f["cut"]]
    solid = bool(boxes)
    lo = [min(b[0][k] for b in boxes) for k in range(3)] if solid else [0.0, 0.0, 0.0]
    hi = [max(b[1][k] for b in boxes) for k in range(3)] if solid else [0.0, 0.0, 0.0]
    centre = [(lo[k] + hi[k]) / 2 for k in range(3)]
    sphere, hcentre = spheres(boxes) if solid else ([0.0] * 4, [0.0] * 3)
    s["model"] = {"solid": solid, "min": lo, "max": hi, "centre": centre, "sphere": sphere,
                  "origin_refs": sum(1 for f in s["sketches"] if f["at_origin"])}
    s["planes"] = plane_slots(lo, hi, centre, solid)
    s["hdr"] = {"centre": hcentre, "next_id": features[-1]["id"] + 1 if features else 26}
    s["fixed"]["id_base"] = s["doc"]["stamp"] - 11 - len(features)

    # 15.6.9: the file custom properties
    s["props"] = props_of(doc, s["meta"]["utc_offset"])
    s["props_by_name"] = props_by_name(s["props"])

    # 15.6.4: the slots derived from identity values
    d = s["doc"]
    saved = datetime.fromtimestamp(d["unix"], UTC)
    d["iso"] = saved.strftime("%Y-%m-%dT%H:%M:%SZ")
    d["filetime"] = (d["unix"] + FILETIME_EPOCH) * 10_000_000
    m = s["meta"]
    shift = timedelta(minutes=m["utc_offset"])
    local = saved + shift
    made = datetime.strptime(m["created_iso"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) + shift
    m.update(short_date=f"{local.month}/{local.day}/{local.year}", long_date=_long(local),
             created_text=_long_time(made), saved_text=_long_time(local),
             kw_extrusions=sorted(exts, key=lambda f: str(f["id"])),
             kw_sketches=sorted([{"id": 5, "name": "Origin", "origin": True}]
                                + [{"id": f["id"], "name": f["name"], "origin": False}
                                   for f in s["sketches"]], key=lambda k: str(k["id"])))
    x = s["exch"]
    x["hash"] = {k: _key_hash(x[k]) for k in ("front", "top", "right", "doc", "config")}
    return s
