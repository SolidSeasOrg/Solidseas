"""The circle sketch and the cut through all (sections 15.5.12 and 15.5.13), proved on o10
and o11.

Neither fixture is a part the generator writes as a whole: o10 cuts a body imported from
STEP, and o11 rounds its box with fillets before its cut and after it. So the feature
stream's cases do not assemble whole members. They assemble the circle and cut listings
alone, with the archive seeded to the state the fixture's archive is in where its circle
sketch starts (the classes it has defined, their schemas, the next index and the objects
the listings refer to), and compare the result with the fixture's records from there,
byte for byte, except where a record names something the generator never writes (the
imported body's faces, the fillet's faces), which the tests name and check separately.
The members a cut changes whose other content the import and the fillets leave alone are
assembled whole from what each part is (:func:`design_items`).

The archive is read the way ``features.ObjectMap`` reads it, with two corrections the
tests check:

- o10's ``Contents/Config-0`` holds three u16s in the relation manager's data that read as
  references to ``moMaterial_c`` and are not; without them the count at its end is the
  feature stream's header, 109 (``docs/NATIVE_SLDPRT_WRITER.md`` 4.6 left the cause open);
- o11's ``Boss-Extrude1`` holds ``cache_text`` 0.008, whose bytes include ``62 80``, read as
  a reference to ``moSketchBlockMgr_c``; without it the count where ``Sketch2`` starts is
  the object the cut's child list names.

Identity and free values (times, session counters, caches) are read from the fixture the way
:func:`.archive.extract` reads them, at the first place the listing writes each; every other
place is compared. No value read from a fixture is stored in this file.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .. import features as F
from .. import listing as L
from . import Fixture, fixture
from .archive import _Probe, extract

FEATURES = "Contents/Config-0-ResolvedFeatures"
CONFIG = "Contents/Config-0"
MACROS = "config-0-macros.srl"
CIRCLE = "config-0-resolvedfeatures-circle.srl"
CUT = "config-0-resolvedfeatures-cut.srl"
IMPORT = "o02_boxA.step<1>"  # o10's imported body, a feature outside the generator's scope


# ------------------------------------------------------------------ the archive at an offset
def phantom_references(config: bytes, first: int) -> set[int]:
    """Offsets of the u16s in the relation manager's data that the scan would take for
    references to ``moMaterial_c`` and are not (o10): the u16 ``0x8000 | index`` of that
    class between the ``moRelMgr_c`` and ``moEnvFolder_c`` records, numbering from ``first``
    (2, or 3 in the parts with an imported body). Empty in the other fixtures."""
    lo, hi = config.find(b"moRelMgr_c"), config.find(b"moEnvFolder_c")
    if lo < 0 or hi < 0:
        return set()
    k = F.ObjectMap({}, first).walk(config, 0, lo).index_of("moMaterial_c")
    if k is None:
        return set()
    tag = struct.pack("<H", 0x8000 | k)
    return {i for i in range(lo, hi - 1) if config[i : i + 2] == tag}


def cache_phantoms(feats: bytes, x1: float) -> set[int]:
    """Offsets of the u16s inside the first extrusion's ``cache_text`` double (15.5.8, about
    ``x1 * 0.2``), which the scan would take for class references in o11."""
    d1 = F.parameters(feats)[0].value_offset
    for k in range(d1, d1 + 600):
        (v,) = struct.unpack_from("<d", feats, k)
        if v and abs(v - x1 * 0.2) <= 4 * math.ulp(x1 * 0.2):
            return set(range(k, k + 7))
    return set()


@dataclass
class Walk:
    classes: dict[str, int]  # class name: index
    schemas: dict[str, int]
    next: int  # the archive's next index at the offset
    objects: list[tuple[int, str, int]]  # (offset of the token, class, object index), feature stream
    config_objects: list[tuple[int, str, int]] = field(default_factory=list)  # the same, Config-0


def _walk_stream(data: bytes, start: int, end: int, classes: dict, schemas: dict, count: int,
                 skip: set[int], objects: list) -> int:
    names = {v: k for k, v in classes.items()}
    i = start
    while i < end - 1:
        if data[i] == 0xFF and data[i + 1] == 0xFF and i + 6 <= end:
            schema, n = struct.unpack_from("<HH", data, i + 2)
            name = data[i + 6 : i + 6 + n]
            if 3 <= n <= 64 and F._NAME.match(name):
                text = name.decode("ascii")
                classes[text], schemas[text], names[count] = count, schema, text
                objects.append((i, text, count + 1))
                count += 2
                i += 6 + n
                continue
        (v,) = struct.unpack_from("<H", data, i)
        if i not in skip and 0x8000 < v < 0xFFFF and (v & 0x7FFF) in names:
            objects.append((i, names[v & 0x7FFF], count))
            count += 1
            i += 2
            continue
        i += 1
    return count


def walk(fx: Fixture, offset: int, skip: set[int] = frozenset()) -> Walk:
    """The archive's classes and next index at ``offset`` of the feature stream, by the scan
    with o10's correction and ``skip``, offsets in the feature stream that are not references
    (:func:`cache_phantoms`)."""
    config, feats = fx[CONFIG], fx[FEATURES]
    first = F.name_tag(feats)[0] - 2
    classes: dict[str, int] = {}
    schemas: dict[str, int] = {}
    config_objects: list = []
    count = _walk_stream(config, 0, len(config), classes, schemas, first,
                         phantom_references(config, first), config_objects)
    assert count == F.header(feats)[0], "the scan of Contents/Config-0 does not reach the header"
    objects: list = []
    count = _walk_stream(feats, 6, offset, classes, schemas, count, set(skip), objects)
    return Walk(classes, schemas, count, objects, config_objects)


def class_token(data: bytes, node: int) -> int:
    """The offset of the class token before the named node at ``node``: a reference (two
    bytes whose second has the high bit; a class name is ASCII) or a new-class record."""
    if data[node - 1] & 0x80:
        return node - 2
    k = data.rfind(b"\xff\xff", 0, node)
    while k >= 0 and k + 6 + struct.unpack_from("<H", data, k + 4)[0] != node:
        k = data.rfind(b"\xff\xff", 0, k)
    return k


def _uid(feats: bytes) -> dict[str, int]:
    """Each named feature's creation number (the u32 after its flags, 15.4.2)."""
    return {n.name: struct.unpack_from("<I", feats, n.end + 8)[0] for n in F.named_nodes(feats)}


def history_created(feats: bytes, uid: int) -> int:
    """A feature's creation time from its history entry (15.5.3: u32 17000, its creation
    number, its time)."""
    k = feats.index(struct.pack("<II", 17000, uid))
    return struct.unpack_from("<I", feats, k + 8)[0]


# ------------------------------------------------------------------ what each fixture is
@dataclass(frozen=True)
class CutFixture:
    """What a fixture's circle sketch and cut are (its kit instructions), in metres."""

    name: str
    sketch: str
    cut: str
    centre: tuple[float, float]
    radius: float
    box: tuple[tuple[float, float, float], tuple[float, float, float]]  # the cut body's box


CUT_FIXTURES = {
    "o10": CutFixture("o10", "Sketch1", "Cut-Extrude1", (0.005, 0.01), 0.0025,
                      ((0.0, 0.0, 0.0), (0.01, 0.02, 0.03))),
    "o11": CutFixture("o11", "Sketch2", "Cut-Extrude1", (0.02, 0.015), 0.005,
                      ((0.0, 0.0, 0.0), (0.04, 0.03, 0.01))),
}


def _box(lo, hi) -> dict:
    return {"centre": [(a + b) / 2 for a, b in zip(lo, hi, strict=True)],
            "diagonal": math.sqrt(sum((b - a) ** 2 for a, b in zip(lo, hi, strict=True)))}


def _outside(name: str, uid: int) -> dict:
    """A feature outside the generator's scope, which ``features`` holds only to be counted
    and logged (created only, as the fixtures log it)."""
    return {"name": name, "sketch": False, "cut": False, "log_modified": False, "id": uid, "outside": True}


def design_items(name: str) -> dict:
    """What fixture ``name`` is, as the slots of section 15.6 describe a part: its features
    (the import of o10 and the fillets of o11 as :func:`_outside` items), its sketches, its
    bodies (o11's fillets as features that changed them, 15.2.7.4), its model box and the
    planes' display. Identity values are not here: each case reads those from the member it
    proves."""
    from . import design as D

    cf = CUT_FIXTURES[name]
    uid = _uid(fixture(name)[FEATURES])
    lo, hi = cf.box
    cx, cy = cf.centre
    if name == "o10":
        made_by, changed = uid[IMPORT], ([], [])
        before, after = [_outside(IMPORT, made_by)], []
    else:
        made_by, changed = uid["Boss-Extrude1"], ([uid["Fillet1"]], [uid["Fillet2"]])
        rect = [0.0, 0.0, 0.04, 0.03]
        before = [
            {"name": "Sketch1", "sketch": True, "circle": False, "log_modified": True, "id": uid["Sketch1"],
             "corners": rect, "at_origin": True},
            {"name": "Boss-Extrude1", "sketch": False, "cut": False, "log_modified": False, "id": made_by,
             "depth": 0.01, "corners": rect, "depth_text": "10", "first": True, "merge": True,
             **_box(lo, hi), "body_id": 101, "body_label": "body1"},
            _outside("Fillet1", uid["Fillet1"]),
        ]
        after = [_outside("Fillet2", uid["Fillet2"])]
    sketch = {"name": cf.sketch, "sketch": True, "circle": True, "log_modified": False, "id": uid[cf.sketch],
              "centre": [cx, cy], "radius": cf.radius, "start": [cx + cf.radius, cy], "at_origin": False}
    cut = {"name": cf.cut, "sketch": False, "cut": True, "log_modified": False, "id": uid[cf.cut],
           "sketch_name": cf.sketch, "sketch_id": sketch["id"], "first": False, "merge": False,
           **_box(lo, hi), "body_id": 102, "body_label": "body2", "target_id": 101,
           "target_label": "body1", "target_uid": made_by}
    features = [*before, sketch, cut, *after]
    names = (IMPORT, cf.cut) if name == "o10" else ("Fillet1", "Fillet2")  # the last feature to build each
    bodies = [
        {"id": 101, "name": names[0], "label": "body1", "feature": made_by,
         "last": (changed[0] or [made_by])[-1], "changed": changed[0], "live": False, "from": [],
         "into": [102], "time": 0},
        {"id": 102, "name": names[1], "label": "body2", "feature": cut["id"],
         "last": (changed[1] or [cut["id"]])[-1], "changed": changed[1], "live": True, "from": [101],
         "into": [], "time": 0},
    ]
    builds = D.builds_of(bodies)
    for b in builds:  # the cases read each from the fixture
        del b["time"]
    sphere, hcentre = D.spheres([(list(lo), list(hi))])
    centre = [(a + b) / 2 for a, b in zip(lo, hi, strict=True)]
    return {
        "features": features, "sketches": [f for f in features if f["sketch"]],
        "bodies": bodies, "live_bodies": [b for b in bodies if b["live"]],
        "body_links": D.body_links(bodies), "builds": builds,
        "model": {"solid": True, "min": list(lo), "max": list(hi), "centre": centre, "sphere": sphere,
                  "origin_refs": sum(1 for f in features if f["sketch"] and f["at_origin"])},
        "planes": D.plane_slots(list(lo), list(hi), centre, True),
        "hdr": {"centre": hcentre, "next_id": max(f["id"] for f in features) + 1},
    }


def member_slots(name: str) -> dict:
    """:func:`design_items` with section 15.1's identity slots read from the fixture, the
    internal document name as its keyword index has it (15.1.5), and the values derived from
    them (15.6.5)."""
    from . import text as T

    s = design_items(name)
    ident = T.read_identity(fixture(name))
    s["doc"], s["meta"] = ident["doc"], ident["meta"]
    kw = fixture(name)["swXmlContents/KeyWords"].decode("utf-8", "replace")
    d = s["doc"]
    d["name"] = kw.split('<Keywords id="', 1)[1].split('Name="', 1)[1].split('"', 1)[0]
    d["iso"] = datetime.fromtimestamp(d["unix"], UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    d["filetime"] = (d["unix"] + 11644473600) * 10_000_000
    return s


# ------------------------------------------------------------------ the feature stream's records
# Identity and free slots of the two items, read where the listings first write them. The
# box's creation time (target_created, and the ring's) is read too, because the box is not
# assembled here; the tests check it against the box's history entry.
FEATURE_READ = ("f.time", "f.cache*", "f.counter*", "f.regen", "f.created", "tpl.unix",
                "f.target_created", "f.ring.*.created")


def _ring(name: str) -> list[dict]:
    """The faces a fixture's cut names its body by (15.5.13). o11's: side 4 of Boss-Extrude1,
    its end face 1, face 1 of Fillet1, its end face 0 and face 4 of Fillet1, the fillet's
    faces written here as sides (the tests check that only their class differs). o10's are
    the import's faces 3, 1, 5, 2 and 0, which the o10 cases do not assemble."""
    uid = _uid(fixture(name)[FEATURES])
    if name == "o11":
        box, fil = uid["Boss-Extrude1"], uid["Fillet1"]
        faces = ((False, box, 4), (True, box, 1), (False, fil, 1), (True, box, 0), (False, fil, 4))
    else:
        faces = tuple((False, uid[IMPORT], k) for k in (3, 1, 5, 2, 0))
    return [{"end": end, "uid": u, "face": face, "created": 0} for end, u, face in faces]


def _items(name: str) -> tuple[list[dict], int]:
    """The circle sketch and cut items of fixture ``name``, and their place in its timeline."""
    s = design_items(name)
    sketch, cut = (dict(f) for f in s["features"] if f.get("circle") or f.get("cut"))
    place = next(k for k, f in enumerate(s["features"]) if f.get("circle"))
    cut["ring"] = _ring(name)
    for f in (sketch, cut):
        f.update(time=0, cache_memo=0.0, created=0)
    sketch.update(regen=0)
    cut.update(counter_marks=0, counter_face1=0, counter_face2=0, counter_end=0, target_created=0)
    return [sketch, cut], place


@dataclass
class FeatureCase:
    """Records assembled from an offset of the feature stream, and the fixture's bytes from
    the same place."""

    got: bytes
    want: bytes
    runs: list
    slots: dict
    start: int  # the first record's offset in the feature stream


def assemble_at(name: str, lines: list, slots: dict, at: int, labels: dict,
                skip: set[int] = frozenset(), read=FEATURE_READ) -> FeatureCase:
    """``lines`` assembled with the archive fixture ``name`` has at offset ``at`` of its
    feature stream (the scan's classes and next index, and ``labels``), its identity and free
    slots of ``read`` read from the fixture where the lines first write them."""
    fx = fixture(name)
    feats = fx[FEATURES]
    w = walk(fx, at, skip)

    def archive():
        return L.Archive(next=w.next, classes=dict(w.classes), schemas=dict(w.schemas), labels=dict(labels))

    def probe(sl, notes):
        a = _Probe(archive(), L.LISTINGS, notes)
        a.member = FEATURES
        a.run(lines, dict(sl))
        return {FEATURES: bytes(a.out)}

    slots = extract(Fixture(fx.name, {FEATURES: feats[at:]}), slots, [], assemble=probe, read=read)
    res = L.assemble(lines, slots, archive())
    return FeatureCase(res.data, feats[at : at + len(res.data)], res.runs, slots, at)


def _labels(fx: Fixture, start: int, skip: set[int]) -> dict:
    """The objects the listings refer to that come before ``start``: the bodies' atoms of
    ``Contents/Config-0``, newest first (15.4.6), and the first extrusion's ``moExtObject_c``."""
    w = walk(fx, start, skip)
    atoms = [k for _o, c, k in w.config_objects if c == "moAtom_c"]
    labels = {"body2": atoms[0], "body1": atoms[1]}
    ext = [k for _o, c, k in w.objects if c == "moExtObject_c"]
    if ext:
        labels["ext_obj"] = ext[0]
    return labels


_LOOP = ("@for f in $features", "@if $f.sketch", f"@include {CIRCLE}", "@else", f"@include {CUT}",
         "@endif", "@endfor")


def feature_case(name: str, cut: bool = True) -> FeatureCase:
    """o11's Sketch2 and Cut-Extrude1 (or o10's Sketch1, and its cut when ``cut``) assembled
    by the circle and cut listings after the archive the fixture's earlier records leave."""
    cf = CUT_FIXTURES[name]
    fx = fixture(name)
    feats = fx[FEATURES]
    nodes = {n.name: n for n in F.named_nodes(feats)}
    start = class_token(feats, nodes[cf.sketch].offset)
    skip = cache_phantoms(feats, cf.box[1][0]) if name == "o11" else set()
    items, place = _items(name)
    stamp = struct.unpack_from("<I", fx["ModelStamps"], 4)[0]
    n_items = len(design_items(name)["features"])
    # 15.5.4: ids are fixed.id_base + 11 + the item's place; the items are assembled alone, so
    # the base moves by the number of items before them.
    slots = {"features": items if cut else items[:1], "tpl": {"unix": 0},
             "fixed": {"id_base": stamp - 11 - n_items + place}}
    lines = L.load(L.LISTINGS / MACROS) + [L.Line("case", k + 1, t) for k, t in enumerate(_LOOP)]
    return assemble_at(name, lines, slots, start, _labels(fx, start, skip), skip)


# ------------------------------------------------------------------ o10's cut, record by record
def _line(lines: list, text: str, after: int = 0) -> int:
    return next(k for k in range(after, len(lines)) if lines[k].text.split("#")[0].strip() == text)


def o10_segments() -> list[tuple[str, FeatureCase]]:
    """o10's cut, compared record by record: every run of the cut listing but the face entries
    that name the imported body's faces (15.5.13), each run assembled with the archive the
    fixture has where it starts."""
    fx = fixture("o10")
    feats = fx[FEATURES]
    sketch = feature_case("o10", cut=False)
    cut_start = sketch.start + len(sketch.got)
    cut_item = _items("o10")[0][1]
    macros = L.load(L.LISTINGS / MACROS)
    lines = L.load(L.LISTINGS / CUT)
    a0 = _line(lines, "@use faceref KIND=6 FLAGS=0 COUNTER=0")
    a5 = _line(lines, "@use cutface E=f.ring.4 L=ringa4")
    cap0 = _line(lines, "class moEndFaceSurfIdRep_c 1 as cap0")
    cap1_end = _line(lines, "u32 1 0", _line(lines, "class moEndFaceSurfIdRep_c 1 as cap1"))
    c0 = _line(lines, "@use faceref KIND=6 FLAGS=768 COUNTER=$f.counter_face2")
    c5 = _line(lines, "@use cutface E=f.ring.4 L=ring4")
    w = walk(fx, len(feats))
    objects = {o: k for o, _c, k in w.objects}
    cut_objs = [(o, c, k) for o, c, k in w.objects if o >= cut_start]
    reps = [(o, k) for o, c, k in cut_objs if c.endswith("SurfIdRep_c")]
    frs = [o for o, c, _k in cut_objs if c == "moFR_c"]

    def entry_end(rep_offset: int) -> int:  # an imported face's entry: rep, u16 0, moFR_c, 14 bytes
        return next(o for o in frs if o > rep_offset) + 2 + 14

    labels = {**_labels(fx, cut_start, set()),
              "ext_obj": next(k for _o, c, k in w.objects if c == "moExtObject_c"),
              cut_item["name"]: objects[cut_start], cut_item["sketch_name"]: objects[sketch.start],
              "cyl": reps[5][1], "cap0": reps[6][1], "cap1": reps[7][1],
              **{f"ring{k}": reps[8 + k][1] for k in range(5)}}
    pieces = [("the head and the first list's head", 0, a0 + 1, cut_start),
              ("the chooser, the second list's head and the cut's own face", a5 + 1, cap0,
               entry_end(reps[4][0])),
              ("the second list's end and the third list's head", cap1_end + 1, c0 + 1,
               entry_end(reps[7][0])),
              ("the box records, the lists and the end conditions", c5 + 1, len(lines),
               entry_end(reps[12][0]))]
    fixed = {"id_base": sketch.slots["fixed"]["id_base"] - 1}  # the cut is the item after the sketch
    out = []
    for what, lo, hi, at in pieces:
        slots = {"f": cut_item, "f_index": 2, "fixed": fixed}
        out.append((what, assemble_at("o10", macros + lines[lo:hi], slots, at, labels,
                                      read=("f.time", "f.cache*", "f.counter*", "f.created",
                                            "f.target_created"))))
    return out


# ------------------------------------------------------------------ the other members
# Per listing, the identity and free slots a case reads from the member where the listing
# first writes them (15.6.6); every other field is assembled from the design and compared.
MEMBER_READS = {
    "cmgr.srl": {"cmgr.created", "cmgr.texture", "b.time"},
    "cmgrhdr2.srl": set(),
    "config-0-lwdata.srl": {"lw.flag"},
    "visualstates.srl": {"f.created", "tpl.unix"},
    "swdoccontentmgrinfo.srl": set(),
    "modelstamps.srl": set(),
    "dlupdatestamp.srl": set(),
    "header2.srl": {"tpl.unix", "tpl.unix2", "f.created", "f.modified"},
    "config-0-modelheader.srl": {"tpl.unix", "tpl.unix2", "f.created", "f.modified"},
    "config-0.srl": {"config0.length_memo", "config0.curvature_time", "config0.sketch_blocks_time",
                     "fixed.lights.time", "b.regen", "cmgr.texture",
                     *(f"config0.mass.{k}" for k in range(12))},
}

# The members each fixture gives whole by its design (:func:`design_items`): o10's import and
# o11's fillets leave them untouched, but for their place in the counts and o11's model
# header log, where the outside items stand for them.
WHOLE = {
    "o10": {"Contents/CMgr": "cmgr.srl", "Contents/CMgrHdr2": "cmgrhdr2.srl",
            "Contents/Config-0-LWDATA": "config-0-lwdata.srl",
            "ThirdPtyStore/VisualStates": "visualstates.srl",
            "SwDocContentMgr/SwDocContentMgrInfo": "swdoccontentmgrinfo.srl",
            "ModelStamps": "modelstamps.srl", "_DL_VERSION_17000/DLUpdateStamp": "dlupdatestamp.srl"},
    "o11": {"Contents/CMgr": "cmgr.srl", "Header2": "header2.srl",
            "Contents/Config-0-ModelHeader": "config-0-modelheader.srl",
            "Contents/Config-0-LWDATA": "config-0-lwdata.srl",
            "ThirdPtyStore/VisualStates": "visualstates.srl",
            "SwDocContentMgr/SwDocContentMgrInfo": "swdoccontentmgrinfo.srl",
            "ModelStamps": "modelstamps.srl", "_DL_VERSION_17000/DLUpdateStamp": "dlupdatestamp.srl"},
}


def member_case(name: str, member: str, listing: str, slots: dict | None = None) -> L.Result:
    """``listing`` assembled with fixture ``name``'s design and the identity slots read from
    ``member``."""
    from . import headers as H

    s = member_slots(name) if slots is None else slots
    s = H.read_slots(listing, fixture(name)[member], s, MEMBER_READS[listing])
    for key in ("_archive", "settings_size", "tail_size"):
        s.pop(key, None)
    return L.assemble(L.LISTINGS / listing, s)


def config0_case(name: str) -> L.Result:
    """``Contents/Config-0`` assembled with the fixture's design. o11 counts 106 changes, not
    101 + 6 (15.2.3.2), so its case leaves its last fillet out of the count."""
    fx = fixture(name)
    s = member_slots(name)
    s["fixed"] = {"id_base": s["doc"]["stamp"] - 11 - len(s["features"])}
    if name == "o11":
        s["features"] = s["features"][:-1]
    c0 = fx[CONFIG]
    at = c0.find(b"moCThreadRefMgr_c") + len("moCThreadRefMgr_c") + 23
    s["config0"] = {"mass_block": struct.unpack_from("<I", c0, at)[0] != 0}  # as archive.read_identity
    return member_case(name, CONFIG, "config-0.srl", s)


def atoms(data: bytes) -> tuple[int, int]:
    """The span of the bodies' ``moAtom_c`` objects in a ``Contents/Config-0`` (15.4.6): from
    the first one's class record to the end of the last (each 86 bytes after its class)."""
    start = data.index(b"moAtom_c") - 6
    count = struct.unpack_from("<I", data, start - 4)[0]
    return start, start + 6 + len(b"moAtom_c") + 86 + (count - 1) * (2 + 86)


def keyword_elements(name: str) -> tuple[str, str, str]:
    """The ``<Extrusion>`` elements ``keywords.srl`` writes for the fixture's extrusions (its
    box, if it has one, and its cut), its ``<Sketch>`` elements, and the fixture's keyword
    index (15.1.5)."""
    from . import text as T

    s = member_slots(name)
    real = [f for f in s["features"] if not f.get("outside")]
    s["meta"].update(kw_extrusions=T.kw_extrusions(real), kw_sketches=T.kw_sketches(real))
    got = L.assemble(L.LISTINGS / "keywords.srl", s).data[1:].decode("utf-8")  # after its first byte
    extrusions = got[got.index("<Extrusion ") : got.index("<Feature ")]
    sketches = got[got.index("<Sketch ") : got.index("</Keywords>")]
    return extrusions, sketches, fixture(name)["swXmlContents/KeyWords"][1:].decode("utf-8")
