"""Section 15.6 on the analysis side: the fixtures as ``ParametricDocumentIR`` designs, and
the rules that turn a design and its identity into the one slot dict.

:func:`fixture_design` writes down what o01, o02, o03, o07 and o12 are, as the IR would
hold them. :func:`design_slots` is the analysis side's own implementation of section
15.6: every design and derived slot comes from the IR by its rules; only the identity
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
from datetime import UTC, datetime, timedelta

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
    "exch.front", "exch.top", "exch.right", "exch.doc", "exch.config", "exch.toc",
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
                    "counter_marks", "counter_favorite", "counter_face1", "counter_face2")
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


def fixture_design(name: str) -> ir.Document:
    """What fixture ``name`` (o01, o02, o03, o07 or o12) is, as a ParametricDocumentIR part."""
    boxes = {
        "o01": [],
        "o02": [((0.0, 0.0, 0.01, 0.02), 0.03)],
        "o03": [((0.0, 0.0, 0.01, 0.02), 0.03)],
        "o07": [((0.0, 0.0, 0.01, 0.02), 0.031)],
        "o12": [((0.0, 0.0, 0.01, 0.02), 0.03), ((0.03, 0.0, 0.04, 0.02), 0.01)],
    }[name[:3]]
    features: list = []
    for k, (corners, depth) in enumerate(boxes):
        features.append(_rectangle(f"s{k + 1}", f"Sketch{k + 1}", *corners))
        features.append(ir.Extrude(f"e{k + 1}", f"Extrude{k + 1}", f"s{k + 1}", depth))
    return ir.validate(ir.Document("box", features))


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


def depth_text(depth: float) -> str:
    """15.1.2.2: the depth in millimetres, rounded to 8 decimals, without trailing zeros."""
    return f"{round(depth * 1000, 8):.8f}".rstrip("0").rstrip(".") or "0"


def features_of(doc: ir.Document) -> list[dict]:
    """The design and derived fields of the ``features`` items (15.6.2)."""
    items: list[dict] = []
    timeline = list(doc.features)
    if len(timeline) % 2:
        raise ValueError("sketch not followed by its extrusion")
    uid = 26
    for k in range(len(timeline) // 2):
        s, e = timeline[2 * k], timeline[2 * k + 1]
        if not isinstance(s, ir.Sketch) or not isinstance(e, ir.Extrude) or e.sketch != s.id:
            raise ValueError(f"{s.name}: sketch not followed by its extrusion")
        if e.end != "blind" or e.direction != "forward" or e.suppressed:
            raise ValueError(f"{e.name}: only blind extrusions towards the sketch normal are written")
        if k == 0 and e.operation == "cut" or k > 0 and e.operation != "new_body":
            raise ValueError(f"{e.name}: operation {e.operation} is not written")
        corners, at_origin = _corners(s)
        x0, y0, x1, y1 = corners
        sketch = {"name": f"Sketch{k + 1}", "sketch": True, "id": uid, "corners": corners,
                  "at_origin": at_origin}
        uid += 6 if at_origin else 7
        depth = float(e.depth)
        ext = {
            "name": f"Boss-Extrude{k + 1}", "sketch": False, "id": uid,
            "sketch_name": sketch["name"], "sketch_id": sketch["id"], "depth": depth,
            "depth_text": depth_text(depth), "corners": list(corners), "first": k == 0, "merge": k == 0,
            "centre": [(x0 + x1) / 2, (y0 + y1) / 2, depth / 2],
            "diagonal": math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2 + depth**2),
            "body_id": 101 + k, "body_label": f"body{k + 1}",
        }
        uid += 1
        items += [sketch, ext]
    return items


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
                 "toc": [ident.exch_front, ident.exch_top, ident.exch_right]},
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
            item.update(modified=unix, regen=103)
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
    bodies = [{"id": f["body_id"], "name": f["name"], "label": f["body_label"], "feature": f["id"]}
              for f in exts]
    for b, extra in zip(bodies, identity["bodies"], strict=True):
        b.update({k: extra[k] for k in BODY_IDENTITY})
    s["features"] = features
    s["sketches"] = [f for f in features if f["sketch"]]
    s["bodies"] = bodies

    # 15.6.3: the model box, the bounding sphere and the planes' display
    boxes = [([f["corners"][0], f["corners"][1], 0.0], [f["corners"][2], f["corners"][3], f["depth"]])
             for f in exts]
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
    x["time"] = {"year": saved.year, "month": saved.month, "day": saved.day,
                 "hour": saved.hour, "minute": saved.minute, "second": saved.second}
    x["hash"] = {k: _key_hash(x[k]) for k in ("front", "top", "right", "doc", "config")}
    return s
