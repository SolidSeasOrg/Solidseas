"""A fillet of constant radius (section 15.5.14), proved on o11's Fillet1 and Fillet2.

o11 is a box 40 x 30 x 10 mm with its four edges along its depth rounded to 3 mm (Fillet1),
then a 10 mm hole cut through all (Sketch2, Cut-Extrude1), then the hole's edge on the box's
far end face rounded to 1 mm (Fillet2). Each fillet is assembled by the fillet listing alone,
with the archive seeded to the state o11's archive is in where the fillet starts (the scan of
:mod:`.cut`), and compared with o11's bytes from there.

The faces a fillet's records name are written down from what o11 is (its kit instructions):
the box's sides and end faces (15.5.13), the cut's cylinder, the fillet's own faces. Their
creation times are the history entries' of the features that made them (15.5.3), so every
place a face is named is compared. Identity and free values (the fillet's times, its session
counters, its body's rebuild counter) are read where the listing first writes them, the way
:func:`.archive.extract` reads them; no value read from a fixture is stored in this file.
"""

from __future__ import annotations

import struct

from .. import features as F
from .. import listing as L
from . import cut as C
from . import fixture

FILLET = "config-0-resolvedfeatures-fillet.srl"

# 15.5.13, 15.5.14: the kinds of entry of a list of faces.
GAP, SIDE, END, CUT, FILLET_FACE = 0, 1, 2, 3, 4

# 15.5.14: the four edges of a box along its depth, as the sides that meet there, in the order
# a fillet on all four lists them; the order its faces are written in after that; the order of
# its closing list; and which side meets which at the rectangle's first corner (sides 1 and 4).
BOX_EDGES = ((4, 3), (3, 2), (2, 1), (1, 4))
BOX_FACE_ORDER = (0, 3, 1, 2)
BOX_CLOSING_ORDER = (2, 3, 0, 1)

READ = ("f.time", "f.cache_memo", "f.created", "f.counter_marks", "f.body_regen", "e.counter",
        "g.counter")


def entry(kind: int, uid: int = 0, created: int = 0, face: int = 0) -> dict:
    """One entry of a list of faces (15.5.13): its kind, the creation number and time of the
    feature that made the face, and the face's number within that feature."""
    return {"kind": kind, "uid": uid, "created": created, "face": face}


def box_fillet(name: str, uid: int, created: int, box_uid: int, box_created: int, radius: float,
               corners: list[float], depth: float, body: tuple[str, int]) -> dict:
    """A fillet on the four edges of a box along its depth (15.5.14), the features item, with
    zero for its identity and free values."""
    x0, y0 = corners[0], corners[1]

    def side(k):
        return entry(SIDE, box_uid, box_created, k)

    def end(k):
        return entry(END, box_uid, box_created, k)

    edges = [{"label": f"{name}.e{k + 1}", "counter": 0, "faces": [side(a), side(b), end(1), end(0)]}
             for k, (a, b) in enumerate(BOX_EDGES)]
    faces = []
    for k in BOX_FACE_ORDER:
        a, b = BOX_EDGES[k]
        ring = [entry(FILLET_FACE, uid, created, k + 1), end(1), side(b), end(0), side(a)]
        faces.append({"counter": 0, "ring": ring, "edge": edges[k]["faces"]})
    return {
        "name": name, "sketch": False, "cut": False, "fillet": True, "hole": False, "id": uid,
        "radius": radius, "anchor": [x0 + radius, y0 + radius, depth],
        "body_label": body[0], "body_id": body[1], "body_regen": 0,
        "edges": edges, "faces": faces, "closing": [edges[k] for k in BOX_CLOSING_ORDER],
        "dim_edge": edges[-1]["label"],
        "created": created, "time": 0, "cache_memo": 0.0, "counter_marks": 0,
    }


def hole_fillet(name: str, uid: int, created: int, box_uid: int, box_created: int, cut_uid: int,
                cut_created: int, radius: float, centre: list[float], hole_radius: float, depth: float,
                body: tuple[str, int]) -> dict:
    """A fillet on the hole's edge on the box's far end face (15.5.14), the features item."""
    cx, cy = centre
    top = entry(END, box_uid, box_created, 1)
    wall = entry(CUT, cut_uid, cut_created, 1)
    edge = {"label": f"{name}.e1", "counter": 0, "faces": [wall, top, top, top]}
    ring = [entry(FILLET_FACE, uid, created, 1), top, entry(GAP), wall]
    return {
        "name": name, "sketch": False, "cut": False, "fillet": True, "hole": True, "id": uid,
        "radius": radius, "anchor": [cx - hole_radius - radius, cy, depth - radius],
        "body_label": body[0], "body_id": body[1], "body_regen": 0,
        "edges": [edge], "faces": [{"counter": 0, "ring": ring, "edge": edge["faces"]}],
        "closing": [edge], "dim_edge": edge["label"],
        "created": created, "time": 0, "cache_memo": 0.0, "counter_marks": 0,
    }


def o11_fillets() -> dict[str, tuple[dict, int]]:
    """o11's two fillets as features items, each with its place in o11's timeline."""
    feats = fixture("o11")[C.FEATURES]
    uid = C._uid(feats)
    made = {n: C.history_created(feats, uid[n])
            for n in ("Boss-Extrude1", "Cut-Extrude1", "Fillet1", "Fillet2")}
    box, cut = uid["Boss-Extrude1"], uid["Cut-Extrude1"]
    f1 = box_fillet("Fillet1", uid["Fillet1"], made["Fillet1"], box, made["Boss-Extrude1"], 0.003,
                    [0.0, 0.0, 0.04, 0.03], 0.01, ("body1", 101))
    f2 = hole_fillet("Fillet2", uid["Fillet2"], made["Fillet2"], box, made["Boss-Extrude1"], cut,
                     made["Cut-Extrude1"], 0.001, [0.02, 0.015], 0.005, 0.01, ("body2", 102))
    return {"Fillet1": (f1, 2), "Fillet2": (f2, 5)}


# ------------------------------------------------------------------ o11 as a whole part
def o11_design():
    """What o11 is, as a ParametricDocumentIR part: a rectangle (0, 0) to (40, 30) mm on the
    Front Plane extruded 10 mm, its four edges along its depth rounded to 3 mm (each named by
    its middle), a 10 mm circle at (20, 15) mm cut through all in both directions, and the
    hole's edge on the far end face rounded to 1 mm (named by its point on +x)."""
    from solidseas.nativewrite import ir

    from . import design as D

    edges = [ir.EdgeRef((x, y, 0.005)) for x, y in ((0.0, 0.0), (0.04, 0.0), (0.04, 0.03), (0.0, 0.03))]
    return ir.validate(ir.Document("o11", [
        D._rectangle("s1", "Sketch1", 0.0, 0.0, 0.04, 0.03), ir.Extrude("e1", "Extrude1", "s1", 0.01),
        ir.Fillet("f1", "Fillet1", edges, 0.003),
        D.circle_sketch("s2", "Sketch2", 0.02, 0.015, 0.005), D.through_cut("e2", "Cut1", "s2"),
        ir.Fillet("f2", "Fillet2", [ir.EdgeRef((0.025, 0.015, 0.01))], 0.001)]))


def design_part(doc) -> dict:
    """The design slots of design ``doc`` and the slots derived from them alone, by the rules of
    section 15.6 (:mod:`.design`), in the shape :func:`.full.design_part` gives for the boxes."""
    from . import archive as A
    from . import design as D
    from . import headers as H
    from . import text as T

    features = D.features_of(doc)
    bodies = D.bodies_of(features)
    for b in bodies:
        b["time"] = 0
    builds = [{"feature": x["feature"]} for x in D.builds_of(bodies)]
    for b in bodies:
        del b["time"]
    boxes = [([f["corners"][0], f["corners"][1], 0.0], [f["corners"][2], f["corners"][3], f["depth"]])
             for f in features if not f["sketch"] and not f["cut"] and not f["fillet"]]
    lo = [min(b[0][k] for b in boxes) for k in range(3)]
    hi = [max(b[1][k] for b in boxes) for k in range(3)]
    centre = [(a + b) / 2 for a, b in zip(lo, hi, strict=True)]
    return {
        "props": [], "props_by_name": [], "features": features,
        "sketches": [f for f in features if f["sketch"]], "bodies": bodies,
        "live_bodies": [b for b in bodies if b["live"]], "body_links": D.body_links(bodies), "builds": builds,
        "model": {"solid": True, "min": lo, "max": hi, "centre": centre, "sphere": A.sphere(boxes),
                  "origin_refs": sum(1 for f in features if f["sketch"] and f["at_origin"]),
                  "back_view": any(not f["sketch"] and f["fillet"] and not f["hole"] for f in features)},
        "planes": A.planes(lo, hi, centre, True),
        "hdr": {"centre": H.header_centre(boxes), "next_id": features[-1]["id"] + 1},
        "meta": {"kw_extrusions": T.kw_extrusions(features), "kw_sketches": T.kw_sketches(features),
                 "kw_features": T.kw_features(features)},
    }


_O11: dict = {}


def o11_slots() -> dict:
    """o11's one slot dict: its design by the rules of section 15.6, its identity and free slots
    read from o11 by each section's readers (:func:`.full.read_part`)."""
    import copy

    from . import full

    if not _O11:
        _O11["s"] = full.read_part(fixture("o11"), design_part(o11_design()))
    return copy.deepcopy(_O11["s"])


def o11_identity() -> dict:
    """o11's identity and free slots (:func:`.full.identity_from`)."""
    from . import full

    return full.identity_from(o11_slots())


_LOOP = ("@for f in $features", f"@include {FILLET}", "@endfor")


def feature_case(which: str) -> C.FeatureCase:
    """o11's ``Fillet1`` or ``Fillet2`` assembled by the fillet listing after the archive o11's
    earlier records leave."""
    fx = fixture("o11")
    feats = fx[C.FEATURES]
    nodes = {n.name: n for n in F.named_nodes(feats)}
    start = C.class_token(feats, nodes[which].offset)
    skip = C.cache_phantoms(feats, 0.04)
    item, place = o11_fillets()[which]
    stamp = struct.unpack_from("<I", fx["ModelStamps"], 4)[0]
    n_items = 6
    slots = {"features": [item], "fixed": {"id_base": stamp - 11 - n_items + place}}
    lines = L.load(L.LISTINGS / C.MACROS) + [L.Line("case", k + 1, t) for k, t in enumerate(_LOOP)]
    return C.assemble_at("o11", lines, slots, start, C._labels(fx, start, skip), skip, read=READ)
