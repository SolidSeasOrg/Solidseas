"""One slot dict per fixture: every slot of every listing, in the shape README 15.0.2 and
section 15.6 define.

``full_slots(fixture)`` returns the dict from which all 35 listings of the member table
(README 15.0.1) assemble their members, the feature stream after ``config-0.srl``. It is
built in three steps:

1. the design, written down from what each fixture is (its kit instructions: corner
   rectangles on the Front Plane, each extruded blind), and the slots derived from it by
   the sections' rules (the feature items' derived fields, the bodies, the model box and
   sphere, the planes' display, the keyword lists);
2. the identity and free slots, read from the fixture by each section's readers
   (``text``, ``exchange``, ``headers``, ``archive``);
3. the slots derived from identity and free ones (``doc.iso``, ``doc.filetime``, the date
   texts, the exchange time and key hashes, ``fixed.id_base``).

No value read from a fixture is stored in this file. :func:`identity_of` gives the part of
the dict that is identity and free (section 15.6.6), which ``tests/test_sldprt_spec.py``
hands to :func:`.design.design_slots`.
"""

from __future__ import annotations

import copy
import math
from datetime import UTC, datetime
from functools import cache

from . import Fixture, fixture
from . import archive as A
from . import exchange as E
from . import headers as H
from . import text as T

PARTS = ("o01", "o02", "o03", "o04", "o07", "o12")

# What each fixture is, in metres: the corners (x0, y0, x1, y1) of each corner rectangle on
# the Front Plane and the blind depth of the extrusion that follows it.
DESIGNS: dict[str, list[tuple[tuple[float, float, float, float], float]]] = {
    "o01": [],
    "o02": [((0.0, 0.0, 0.01, 0.02), 0.03)],
    "o03": [((0.0, 0.0, 0.01, 0.02), 0.03)],
    "o04": [((0.0, 0.0, 0.01, 0.02), 0.03)],
    "o07": [((0.0, 0.0, 0.01, 0.02), 0.031)],
    "o12": [((0.0, 0.0, 0.01, 0.02), 0.03), ((0.03, 0.0, 0.04, 0.02), 0.01)],
}

# The file custom properties each fixture was given, as (name, kind, the value as typed, the
# value as stored): two texts and the whole number 42 in o04 (o02 plus properties).
PROPERTIES: dict[str, list[tuple[str, str, str, str]]] = {
    "o04": [("PartNo", "text", "ORACLE-PN-123", "ORACLE-PN-123"),
            ("Description", "text", "Oracle test box", "Oracle test box"),
            ("Qty", "integer", "42", "42")],
}
# 15.2.4 and 15.1.4: per kind, the CusProps type code, the TypeID and the vt element.
_KINDS = {"text": (0, 30, "lpstr"), "date": (1, 64, "filetime"), "integer": (2, 3, "i4"),
          "real": (2, 3, "r8"), "yesno": (3, 11, "bool")}


# ------------------------------------------------------------------ 1. design and derived
def design_part(name: str) -> dict:
    """The design slots of fixture ``name`` and the slots derived from them alone."""
    features: list[dict] = []
    bodies: list[dict] = []
    uid = 26  # 15.5.4: the template's records use creation numbers 1 to 25
    for k, (corners, depth) in enumerate(DESIGNS[name]):
        x0, y0, x1, y1 = corners
        sketch = {"name": f"Sketch{k + 1}", "sketch": True, "circle": False, "log_modified": True, "id": uid,
                  "corners": list(corners), "at_origin": (x0, y0) == (0.0, 0.0)}
        uid += 6 if k == 0 else 7  # 15.5.4: the first sketch leaves 5 numbers unused, a later one 6
        ext = {
            "name": f"Boss-Extrude{k + 1}", "sketch": False, "cut": False, "fillet": False,
            "log_modified": False,
            "id": uid,
            "sketch_name": sketch["name"], "sketch_id": sketch["id"], "depth": depth,
            "depth_text": T.depth_text(depth * 1000), "corners": list(corners),
            "first": k == 0, "merge": k == 0,
            "centre": [(x0 + x1) / 2, (y0 + y1) / 2, depth / 2],
            "diagonal": math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2 + depth**2),
            "body_id": 101 + k, "body_label": f"body{k + 1}",
        }
        uid += 1
        features += [sketch, ext]
        bodies.append({"id": 101 + k, "name": ext["name"], "label": f"body{k + 1}", "feature": ext["id"],
                       "last": ext["id"], "changed": [], "live": True, "from": [], "into": []})
    boxes = [([f["corners"][0], f["corners"][1], 0.0], [f["corners"][2], f["corners"][3], f["depth"]])
             for f in features if not f["sketch"]]
    solid = bool(boxes)
    lo = [min(b[0][k] for b in boxes) for k in range(3)] if solid else [0.0] * 3
    hi = [max(b[1][k] for b in boxes) for k in range(3)] if solid else [0.0] * 3
    centre = [(a + b) / 2 for a, b in zip(lo, hi, strict=True)]
    props = []
    for k, (pname, kind, typed, stored) in enumerate(PROPERTIES.get(name, [])):
        code, type_id, vt = _KINDS[kind]
        props.append({"name": pname, "pid": 3 + k, "code": code, "type_id": type_id, "vt": vt,
                      "text": typed, "xml_text": typed, "xml_value": stored})
    return {
        "props": props,
        "props_by_name": sorted(props, key=lambda q: q["name"].lower()),
        "features": features,
        "sketches": [f for f in features if f["sketch"]],
        "bodies": bodies,
        "live_bodies": bodies,
        "body_links": [],
        "builds": [{"feature": b["feature"]} for _, _, b in
                   sorted((b["feature"] % 17, -k, b) for k, b in enumerate(bodies))],
        "model": {
            "solid": solid, "min": lo, "max": hi, "centre": centre, "back_view": False,
            "sphere": A.sphere(boxes) if solid else [0.0] * 4,
            "origin_refs": sum(1 for f in features if f["sketch"] and f["at_origin"]),
        },
        "planes": A.planes(lo, hi, centre, solid),
        "hdr": {
            "centre": H.header_centre(boxes) if solid else [0.0] * 3,
            "next_id": features[-1]["id"] + 1 if features else 26,
        },
        "meta": {"kw_extrusions": T.kw_extrusions(features), "kw_sketches": T.kw_sketches(features),
                 "kw_features": T.kw_features(features)},
    }


def _merge(into: dict, more: dict) -> None:
    for k, v in more.items():
        if isinstance(v, dict) and isinstance(into.get(k), dict):
            _merge(into[k], v)
        else:
            into[k] = v


# ------------------------------------------------------------------ the one dict
@cache
def _full(name: str) -> dict:
    return read_part(fixture(name), design_part(name))


def _made(s: dict) -> None:
    """15.6.2: every face a cut or a fillet names carries the creation time of the feature
    that made it; a list's loop end (kind 0) carries zeros."""
    created = {f["id"]: f["created"] for f in s["features"]}

    def made(entries):
        for e in entries:
            e["created"] = created[e["uid"]] if e["kind"] else 0

    for f in s["features"]:
        if f["sketch"]:
            continue
        if f["cut"]:
            f["target_created"] = created[f["target_uid"]]
            made(f["ring"])
        if f.get("fillet"):
            for e in f["edges"]:
                made(e["faces"])
            for g in f["faces"]:
                made(g["ring"])


def read_part(fx: Fixture, s: dict) -> dict:
    """``s``, a part's design slots and the slots derived from them alone, with its identity
    and free slots read from fixture ``fx`` (step 2) and the slots derived from those (step 3)."""
    # 2. identity and free slots, section by section
    _merge(s, T.read_identity(fx))
    _merge(s, E.read_identity(fx))
    s["fixed"] = {"id_base": s["doc"]["stamp"] - 11 - len(s["features"])}  # 15.6.5: derived from doc.stamp
    H.read_identity(fx, s)
    for b in s["bodies"]:  # 15.2.7.5 gives each body's time, in the list of the features that built it
        b["time"] = next(x["time"] for x in s["builds"] if x["feature"] == b["feature"])
    _made(s)
    s = A.read_identity(fx, s)
    regen = {b["id"]: b["regen"] for b in s["bodies"]}
    for f in s["features"]:  # 15.5.14: a fillet's mark record holds its body's rebuild counter
        if not f["sketch"] and f.get("fillet"):
            f["body_regen"] = regen[f["body_id"]]
    # 3. derived from identity and free slots
    doc = s["doc"]
    doc["iso"] = datetime.fromtimestamp(doc["unix"], UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc["filetime"] = (doc["unix"] + 11644473600) * 10_000_000
    _merge(s["meta"], T.date_texts(doc["unix"], s["meta"]["created_iso"], s["meta"]["utc_offset"]))
    E.derive(s["exch"])
    return s


def full_slots(fixture_name: str | Fixture) -> dict:
    """The one slot dict of a fixture (``"o02"`` or its :class:`Fixture`)."""
    name = fixture_name.name if isinstance(fixture_name, Fixture) else fixture_name
    return copy.deepcopy(_full(name[:3]))


def identity_of(fixture_name: str | Fixture) -> dict:
    """The identity and free slots of a fixture, read from it: the paths section 15.6.6
    lists (``design.IDENTITY``), with the feature items' and bodies' own identity and free
    fields as lists in timeline order."""
    return identity_from(full_slots(fixture_name))


def identity_from(s: dict) -> dict:
    """The identity and free slots of one slot dict (:func:`identity_of`); a fillet's
    counters as the lists ``edge_counters`` and ``face_counters`` (``design.FILLET_IDENTITY``)."""
    from .design import BODY_IDENTITY, FEATURE_IDENTITY, IDENTITY

    out: dict = {}
    for path in IDENTITY:
        cur, box = s, out
        parts = path.split(".")
        for p in parts[:-1]:
            cur = cur[p]
            box = box.setdefault(p, {})
        box[parts[-1]] = cur[parts[-1]]
    out["features"] = []
    for f in s["features"]:
        item = {k: f[k] for k in FEATURE_IDENTITY if k in f}
        if not f["sketch"] and f.get("fillet"):
            item.update(edge_counters=[e["counter"] for e in f["edges"]],
                        face_counters=[g["counter"] for g in f["faces"]])
        out["features"].append(item)
    out["bodies"] = [{k: b[k] for k in BODY_IDENTITY} for b in s["bodies"]]
    return out
