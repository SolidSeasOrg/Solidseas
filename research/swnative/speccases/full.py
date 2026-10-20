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

PARTS = ("o01", "o02", "o03", "o07", "o12")

# What each fixture is, in metres: the corners (x0, y0, x1, y1) of each corner rectangle on
# the Front Plane and the blind depth of the extrusion that follows it.
DESIGNS: dict[str, list[tuple[tuple[float, float, float, float], float]]] = {
    "o01": [],
    "o02": [((0.0, 0.0, 0.01, 0.02), 0.03)],
    "o03": [((0.0, 0.0, 0.01, 0.02), 0.03)],
    "o07": [((0.0, 0.0, 0.01, 0.02), 0.031)],
    "o12": [((0.0, 0.0, 0.01, 0.02), 0.03), ((0.03, 0.0, 0.04, 0.02), 0.01)],
}


# ------------------------------------------------------------------ 1. design and derived
def design_part(name: str) -> dict:
    """The design slots of fixture ``name`` and the slots derived from them alone."""
    features: list[dict] = []
    bodies: list[dict] = []
    uid = 26  # 15.5.4: the template's records use creation numbers 1 to 25
    for k, (corners, depth) in enumerate(DESIGNS[name]):
        x0, y0, x1, y1 = corners
        sketch = {"name": f"Sketch{k + 1}", "sketch": True, "id": uid, "corners": list(corners),
                  "at_origin": (x0, y0) == (0.0, 0.0)}
        uid += 6 if sketch["at_origin"] else 7
        ext = {
            "name": f"Boss-Extrude{k + 1}", "sketch": False, "id": uid,
            "sketch_name": sketch["name"], "sketch_id": sketch["id"], "depth": depth,
            "depth_text": T.depth_text(depth * 1000), "corners": list(corners),
            "first": k == 0, "merge": k == 0,
            "centre": [(x0 + x1) / 2, (y0 + y1) / 2, depth / 2],
            "diagonal": math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2 + depth**2),
            "body_id": 101 + k, "body_label": f"body{k + 1}",
        }
        uid += 1
        features += [sketch, ext]
        bodies.append({"id": 101 + k, "name": ext["name"], "label": f"body{k + 1}", "feature": ext["id"]})
    boxes = [([f["corners"][0], f["corners"][1], 0.0], [f["corners"][2], f["corners"][3], f["depth"]])
             for f in features if not f["sketch"]]
    solid = bool(boxes)
    lo = [min(b[0][k] for b in boxes) for k in range(3)] if solid else [0.0] * 3
    hi = [max(b[1][k] for b in boxes) for k in range(3)] if solid else [0.0] * 3
    centre = [(a + b) / 2 for a, b in zip(lo, hi, strict=True)]
    return {
        "features": features,
        "sketches": [f for f in features if f["sketch"]],
        "bodies": bodies,
        "model": {
            "solid": solid, "min": lo, "max": hi, "centre": centre,
            "sphere": A.sphere(boxes) if solid else [0.0] * 4,
            "origin_refs": sum(1 for f in features if f["sketch"] and f["at_origin"]),
        },
        "planes": A.planes(lo, hi, centre, solid),
        "hdr": {
            "centre": H.header_centre(boxes) if solid else [0.0] * 3,
            "next_id": features[-1]["id"] + 1 if features else 26,
        },
        "meta": {"kw_extrusions": T.kw_extrusions(features), "kw_sketches": T.kw_sketches(features)},
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
    fx = fixture(name)
    s = design_part(name)
    # 2. identity and free slots, section by section
    _merge(s, T.read_identity(fx))
    _merge(s, E.read_identity(fx))
    s["fixed"] = {"id_base": s["doc"]["stamp"] - 11 - len(s["features"])}  # 15.6.5: derived from doc.stamp
    H.read_identity(fx, s)
    s = A.read_identity(fx, s)
    # 3. derived from identity and free slots
    doc = s["doc"]
    doc["iso"] = datetime.fromtimestamp(doc["unix"], UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc["filetime"] = (doc["unix"] + 11644473600) * 10_000_000
    _merge(s["meta"], T.date_texts(doc["unix"], s["meta"]["created_iso"], s["meta"]["utc_offset"]))
    E.derive(s["exch"], doc["unix"])
    return s


def full_slots(fixture_name: str | Fixture) -> dict:
    """The one slot dict of a fixture (``"o02"`` or its :class:`Fixture`)."""
    name = fixture_name.name if isinstance(fixture_name, Fixture) else fixture_name
    return copy.deepcopy(_full(name[:3]))


def identity_of(fixture_name: str | Fixture) -> dict:
    """The identity and free slots of a fixture, read from it: the paths section 15.6.6
    lists (``design.IDENTITY``), with the feature items' and bodies' own identity and free
    fields as lists in timeline order."""
    from .design import BODY_IDENTITY, FEATURE_IDENTITY, IDENTITY

    s = full_slots(fixture_name)
    out: dict = {}
    for path in IDENTITY:
        cur, box = s, out
        parts = path.split(".")
        for p in parts[:-1]:
            cur = cur[p]
            box = box.setdefault(p, {})
        box[parts[-1]] = cur[parts[-1]]
    out["features"] = [{k: f[k] for k in FEATURE_IDENTITY if k in f} for f in s["features"]]
    out["bodies"] = [{k: b[k] for k in BODY_IDENTITY} for b in s["bodies"]]
    return out
