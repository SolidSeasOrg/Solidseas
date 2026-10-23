"""The generation specification's listings give SOLIDWORKS' own bytes (docs/sldprt-spec 15.0.5).

Analysis side of the clean room (docs/CLEANROOM.md): these tests read the
SOLIDWORKS-made fixtures. Each case assembles a listing with one fixture's slot
values and compares the result with that fixture's member, byte for byte. Only the
verdict and a specification-level description of a difference go to the
implementation.
"""

import re
import struct
from pathlib import Path

import pytest

from solidseas.formats.solidworks import open_document
from solidseas.nativewrite import ir
from swnative import features as F_
from swnative import listing as L
from swnative import speccases as S
from swnative.speccases import cut as CUT
from swnative.speccases import design as D
from swnative.speccases import fillet as FIL
from swnative.speccases import full as F

SPEC = Path(__file__).resolve().parents[1] / "docs" / "sldprt-spec"
LISTINGS = SPEC / "listings"
CASES = S.all_cases()


def _table_listings() -> dict[str, str]:
    """Member name: listing file, from the member table of the specification's README."""
    out = {}
    readme = (SPEC / "README.md").read_text(encoding="utf-8")
    for m in re.finditer(r"^\| \d+ \| `([^`]+)` \| [\d.]+ \| `([^`]+\.srl)` \|", readme, re.M):
        out[m.group(1)] = m.group(2)
    return out


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_the_listing_gives_the_fixture_member(case):
    fx = S.fixture(case.fixture)
    slots = case.slots(fx)
    archive = None
    if case.before:
        archive = L.assemble(LISTINGS / case.before, slots).archive
    result = L.assemble(LISTINGS / case.listing, slots, archive)
    assert L.first_difference(result, fx[case.member]) is None, L.first_difference(result, fx[case.member])


def _assemble_all(slots: dict) -> dict[str, L.Result]:
    """Every member of the member table from one slot dict, as ``assemble(slots)`` of README
    15.0.7 does: the feature stream continues the archive of ``Contents/Config-0``."""
    out: dict[str, L.Result] = {}
    for member, listing in _table_listings().items():
        archive = None
        if member == "Contents/Config-0-ResolvedFeatures":
            archive = L.assemble(LISTINGS / "config-0.srl", slots).archive
        out[member] = L.assemble(LISTINGS / listing, slots, archive)
    return out


@pytest.mark.parametrize("part", F.PARTS)
def test_one_slot_dict_gives_every_member(part):
    fx = S.fixture(part)
    results = _assemble_all(F.full_slots(part))
    assert len(results) == 35
    wrong = {m: L.first_difference(r, fx[m]) for m, r in results.items() if r.data != fx[m]}
    assert wrong == {}


@pytest.mark.parametrize("part", F.PARTS)
def test_the_rules_of_15_6_give_every_member_from_the_design(part):
    """Section 15.6 on the analysis side: the design as an IR, and only the identity and
    free slots read from the fixture, give all 35 members byte for byte."""
    fx = S.fixture(part)
    slots = D.design_slots(D.fixture_design(part), F.identity_of(part))
    results = _assemble_all(slots)
    wrong = {m: L.first_difference(r, fx[m]) for m, r in results.items() if r.data != fx[m]}
    assert wrong == {}


@pytest.mark.parametrize("part", F.PARTS)
def test_the_generator_identity_gives_a_complete_slot_dict(part):
    """The values 15.6.6 says the generator writes fill every slot the listings read."""
    doc = D.fixture_design(part)
    slots = D.design_slots(doc, D.generator_identity(doc, D.Identity.new()))
    results = _assemble_all(slots)
    assert results["ModelStamps"].data[4:] == bytes.fromhex({0: "6600000065000000", 1: "7800000069000000",
                                                              2: "8c0000006f000000"}[len(slots["bodies"])])
    assert b"SolidSeas" in results["docProps/core.xml"].data


def _o14_slots() -> dict:
    """o14's slot dict for the property members alone: one box, and its five typed file
    properties by the rules of 15.6.9, with o14's own offset from UTC behind the date."""
    from swnative.speccases import text as T

    fx = S.fixture("o14")
    offset = T.read_identity(fx)["meta"]["utc_offset"]
    doc = ir.validate(ir.Document("box", properties=D.FIXTURE_PROPERTIES["o14"]))
    props = D.props_of(doc, offset)
    return {"features": D.features_of(D.fixture_design("o02")), "props": props,
            "props_by_name": D.props_by_name(props)}


def _loop_span(result: L.Result, listing: str) -> tuple[int, int]:
    """The bytes the listing's ``@for p in $props`` block gave: from its first run to its last."""
    lines = (LISTINGS / listing).read_text(encoding="utf-8").splitlines()
    first = next(n for n, t in enumerate(lines, 1) if t.startswith("@for p in $props") and "by_name" not in t)
    last = next(n for n, t in enumerate(lines, 1) if n > first and t.startswith("@endfor"))
    runs = [r for r in result.runs if first < r.line < last]
    return runs[0].offset, runs[-1].offset + runs[-1].size


def test_cusprops_gives_o14s_typed_property_records():
    """15.2.4 on o14, which also holds a material, two linked properties and a configuration
    property (all outside the generator): its five typed properties are its first five
    records, and the listing gives those records byte for byte. Only the two counts that
    include the other three properties differ, the last index (7) and the list's length (7)."""
    fx = S.fixture("o14")
    result = L.assemble(LISTINGS / "cusprops.srl", _o14_slots())
    got, want = result.data, fx["Contents/CusProps"]
    start, end = _loop_span(result, "cusprops.srl")
    assert got[start:end] == want[start:end]
    assert got[:20] == want[:20] and got[24 : start - 2] == want[24 : start - 2]
    assert struct.unpack_from("<i", want, 20)[0] == 7 and struct.unpack_from("<H", want, start - 2)[0] == 7


def test_custom_xml_gives_o14s_typed_property_elements():
    """15.1.4 on o14: each of its five typed properties' elements, and their name dictionary
    entries in the order o14 holds them, are what the listing writes. o14 also holds two
    linked properties, and wrote the five before its dictionary because they were already
    saved once (15.1.4), so the member as a whole is not compared."""
    fx = S.fixture("o14")
    got = L.assemble(LISTINGS / "custom.srl", _o14_slots()).data.decode("utf-8")
    want = fx["docProps/custom.xml"].decode("utf-8")
    element = re.compile(r'<property name="[^"]+" pid="\d+".*?</property>')
    written = element.findall(got)
    assert len(written) == 5 and all(e in want for e in written)
    entry = re.compile(r'<propertyNameDictionaryElement name="([^"]+)" pid="(\d+)">')
    ours = entry.findall(got)
    assert ours == [e for e in entry.findall(want) if e in ours]


def test_the_property_rules_give_the_example_of_15_6_9():
    """Section 15.6.9's example and refusals, by the analysis side's reading of its rules."""
    P = ir.Property
    doc = ir.validate(ir.Document("box", properties=[
        P("PartNo", "BR-100 & <A>"), P("Qty", 12, "number"), P("Mass", 0.25, "number"),
        P("Due", "2025-01-07", "date"), P("Released", False, "yesno")]))
    props = D.props_of(doc, 0)
    assert props == [
        {"name": "PartNo", "pid": 3, "code": 0, "type_id": 30, "vt": "lpstr", "text": "BR-100 & <A>",
         "xml_text": "BR-100 &amp; &lt;A&gt;", "xml_value": "BR-100 &amp; &lt;A&gt;"},
        {"name": "Qty", "pid": 4, "code": 2, "type_id": 3, "vt": "i4", "text": "12", "xml_text": "12",
         "xml_value": "12"},
        {"name": "Mass", "pid": 5, "code": 2, "type_id": 3, "vt": "r8", "text": "0.25", "xml_text": "0.25",
         "xml_value": "0.250000"},
        {"name": "Due", "pid": 6, "code": 1, "type_id": 64, "vt": "filetime", "text": "1/7/2025",
         "xml_text": "1/7/2025", "xml_value": "2025-01-07T12:00:00Z"},
        {"name": "Released", "pid": 7, "code": 3, "type_id": 11, "vt": "bool", "text": "No", "xml_text": "No",
         "xml_value": "No"},
    ]
    assert [q["name"] for q in D.props_by_name(props)] == ["Due", "Mass", "PartNo", "Qty", "Released"]
    assert [D.real_text(v) for v in (3.25, 7.0, 1e-05, 1e16, -0.5)] == [
        "3.25", "7.0", "0.00001", "10000000000000000.0", "-0.5"]
    refused = [P("A", 'x "D1@Sketch1"'), P("B", "$prp:\"Qty\""), P("C", "two\nlines"), P("D\t", "x"),
               P("E", 2**31, "number"), P("F", "1600-12-31", "date")]
    assert all(D.property_refusal(q) for q in refused)
    kept = [P("G", 'a 1/2" bolt'), P("H", "a@b"), P("I", -(2**31), "number"), P("J", "1601-01-01", "date")]
    assert not any(D.property_refusal(q) for q in kept)


def _listing_slot_refs() -> tuple[set[str], set[str]]:
    """The slot paths the listings read, and the fields they read of list items (loop
    variables), with list indices dropped. Listing-local values (``@sized``, ``@let``,
    ``@archive set``) are left out."""
    paths, fields = set(), set()
    toks = [L._tokens(line) for p in LISTINGS.glob("*.srl")
            for line in p.read_text(encoding="utf-8").splitlines()]
    # Loop variables of all listings: an included listing reads its includer's.
    loops = {t[1] for t in toks if t[:1] == ["@for"]}
    local = {t[2] for t in toks if t[:1] == ["@sized"]} | {t[1] for t in toks if t[:1] == ["@let"]}
    local |= {f"{v}_index" for v in loops} | {"_archive"}
    for tok in (tok for t in toks for tok in t):
        for ref in re.findall(r"\$\{?=?([A-Za-z_][\w.]*)", tok):
            parts = [x for x in ref.rstrip(".").split(".") if not x.isdigit()]
            if parts[0] in local:
                continue
            if parts[0] in loops:
                if len(parts) > 1:  # the bare item, as in "utf8 $g", has no field
                    fields.add(parts[1])
            else:
                paths.add(".".join(parts))
    return paths, fields


def test_every_slot_a_listing_reads_is_named_in_15_6_or_the_readme():
    """Section 15.6 (or the shared table of README 15.0.2) names every slot and every
    list item field a listing reads, so an implementer can compute each one."""
    text = (SPEC / "15.6-design-to-slots.md").read_text(encoding="utf-8")
    text += (SPEC / "README.md").read_text(encoding="utf-8")
    named = set(re.findall(r"`([A-Za-z_][\w.<>]*)`", text))
    named |= {n.replace("<p>", p) for n in named for p in ("front", "top", "right")}
    paths, fields = _listing_slot_refs()

    def covered(path: str) -> bool:  # the path, or a prefix of two or more parts, is named
        parts = path.split(".")
        if parts[0] == "fixed" and parts[-1] == "time":
            return "fixed.<key>.time" in text
        return any(".".join(parts[:k]) in named for k in range(min(2, len(parts)), len(parts) + 1))

    assert sorted(p for p in paths if not covered(p)) == []
    assert sorted(f for f in fields if f not in named) == []


def test_every_member_the_generator_writes_has_a_listing_and_a_case():
    table = _table_listings()
    assert len(table) == 35
    proved = {c.listing for c in CASES}
    missing = [f for f in table.values() if not (LISTINGS / f).exists()]
    unproved = [f for f in table.values() if f not in proved]
    assert missing == [] and unproved == []


def test_every_listing_is_in_the_member_table_or_included():
    table = set(_table_listings().values())
    included = set()
    for p in LISTINGS.glob("*.srl"):
        included |= set(re.findall(r"^@include\s+(\S+)", p.read_text(encoding="utf-8"), re.M))
    stray = [p.name for p in LISTINGS.glob("*.srl") if p.name not in table | included]
    assert stray == []


def test_no_listing_or_section_carries_a_name_or_path_from_a_fixture():
    words: set[str] = set()
    for f in sorted(S.FIXTURES.glob("*.SLD*")):
        try:
            with open_document(f) as d:
                rep = d.path_report()
        except Exception:
            continue
        words |= {a.name for a in rep.accounts if len(a.name) >= 3}
        words |= {h.host for h in rep.hosts if len(h.host) >= 3}
        words |= {p.path for p in rep.paths if len(p.path) >= 4}
        words |= {f.value for f in rep.identity_fields if len(f.value or "") >= 3 and f.value != "SolidSeas"}
    texts = [p for p in SPEC.rglob("*") if p.is_file()]
    for p in texts:
        text = p.read_text(encoding="utf-8").lower()
        for w in words:
            assert w.lower() not in text, f"{p.name} carries a fixture's {w!r}"


# ------------------------------------------------------------------ the circle and the cut (15.5.12, 15.5.13)
def _box_with_hole(cx=0.005, cy=0.01, r=0.0025, corners=(0.0, 0.0, 0.01, 0.02), depth=0.03):
    """A corner rectangle extruded blind, then a circle cut through all in both directions."""
    return ir.validate(ir.Document("box", [
        D._rectangle("s1", "Sketch1", *corners), ir.Extrude("e1", "Extrude1", "s1", depth),
        D.circle_sketch("s2", "Sketch2", cx, cy, r), D.through_cut("e2", "Cut1", "s2")]))


def _uid(name: str) -> dict[str, int]:
    feats = S.fixture(name)[CUT.FEATURES]
    return {n.name: struct.unpack_from("<I", feats, n.end + 8)[0] for n in F_.named_nodes(feats)}


def test_the_scan_of_o10_and_o11_reaches_every_anchor():
    """cut.py's two corrections of the archive scan (docs/NATIVE_SLDPRT_WRITER.md 4.6): with
    o10's three false references skipped, the count at the end of Contents/Config-0 is the
    feature stream's header; with o11's false reference inside its box's cache double skipped,
    the count where Sketch2 starts is the object the cut's child list names."""
    fx = S.fixture("o10")
    assert len(CUT.phantom_references(fx[CUT.CONFIG], 3)) == 3
    CUT.walk(fx, 6)  # asserts the header
    fx = S.fixture("o11")
    feats = fx[CUT.FEATURES]
    nodes = {n.name: n for n in F_.named_nodes(feats)}
    start = CUT.class_token(feats, nodes["Sketch2"].offset)
    w = CUT.walk(fx, start, CUT.cache_phantoms(feats, 0.04))
    child = struct.unpack_from("<H", feats, nodes["Cut-Extrude1"].end + 28)[0]  # after the head (15.4.2)
    assert w.next == child


def test_the_circle_and_cut_listings_give_o11s_records():
    """15.5.12 and 15.5.13 on o11, whose cut follows a box rounded by a fillet on its four edges
    along its depth: Sketch2 and Cut-Extrude1 byte for byte, the two faces of Fillet1 in each of
    the cut's two lists of its body's faces included (entries of kind 4, moFilletSurfIdRep_c)."""
    case = CUT.feature_case("o11")
    feats = S.fixture("o11")[CUT.FEATURES]
    uid = _uid("o11")
    assert case.got == case.want
    ring = case.slots["features"][1]["ring"]
    assert [(e["kind"], e["uid"], e["face"]) for e in ring] == [
        (1, uid["Boss-Extrude1"], 4), (2, uid["Boss-Extrude1"], 1), (4, uid["Fillet1"], 1),
        (2, uid["Boss-Extrude1"], 0), (4, uid["Fillet1"], 4)]
    assert ring[2]["created"] == CUT.history_created(feats, uid["Fillet1"])
    cut = case.slots["features"][1]
    box_time = CUT.history_created(feats, uid["Boss-Extrude1"])
    assert cut["target_created"] == box_time == cut["ring"][0]["created"] == cut["ring"][3]["created"]
    assert cut["created"] == CUT.history_created(feats, uid["Cut-Extrude1"])


def test_the_circle_and_cut_listings_give_o10s_records():
    """15.5.12 and 15.5.13 on o10, a cut through an imported body: Sketch1 byte for byte, and
    every record of Cut-Extrude1 but the entries naming the import's faces, each assembled with
    the archive o10 has where it starts. One field differs, as the specification says: after
    the first face list o10 writes its body's id and 33 where o11, whose body a boss extrusion
    made, writes 0 and 0 (15.5.13)."""
    sketch = CUT.feature_case("o10", cut=False)
    assert sketch.got == sketch.want
    for what, case in CUT.o10_segments():
        if what.startswith("the chooser"):
            k = next(r.offset for r in case.runs if r.source == CUT.CUT
                     and case.got[r.offset:r.offset + 4] == struct.pack("<I", 1)
                     and case.got[r.offset + 4:r.offset + 8] == struct.pack("<I", 101))
            assert case.want[k + 12:k + 20] == struct.pack("<II", 101, 33)
            assert case.got[k + 12:k + 20] == struct.pack("<II", 0, 0)
            assert case.got[:k + 12] + case.got[k + 20:] == case.want[:k + 12] + case.want[k + 20:], what
        else:
            assert case.got == case.want, what


@pytest.mark.parametrize("name,member", [(n, m) for n in CUT.WHOLE for m in CUT.WHOLE[n]])
def test_a_cut_parts_member_follows_its_design(name, member):
    """Members a cut changes, given whole by their listings from what o10 and o11 are: the
    bodies a cut makes and uses up (15.2.7.4, 15.4.6), the logs (15.2.2.2), the display state
    (15.2.6) and the stamps."""
    res = CUT.member_case(name, member, CUT.WHOLE[name][member])
    assert L.first_difference(res, S.fixture(name)[member]) is None


def test_config_0_gives_the_bodies_a_cut_leaves():
    """15.4.6: o11's Contents/Config-0 byte for byte up to its tail size, which counts what its
    fillets add further on, and its two bodies, the one the cut made and the one it used up;
    and o10's two bodies, but for the archive index of moAtom_c, one higher there because the
    import starts the numbering at 3 (docs/NATIVE_SLDPRT_WRITER.md 4.6)."""
    lines = (LISTINGS / "config-0.srl").read_text(encoding="utf-8").splitlines()
    for name in ("o11", "o10"):
        res = CUT.config0_case(name)
        c0 = S.fixture(name)[CUT.CONFIG]
        a, b = CUT.atoms(res.data)
        a2, b2 = CUT.atoms(c0)
        got, want = res.data[a:b], c0[a2:b2]
        if name == "o11":
            size = next(r.offset for r in res.runs
                        if r.source == "config-0.srl" and "tail_size" in lines[r.line - 1])
            assert res.data[:size] == c0[:size]
            assert got == want
        else:
            ref = 6 + len(b"moAtom_c") + 86  # the second atom's class reference
            index = struct.unpack_from("<H", got, ref)[0] & 0x7FFF
            assert got[:ref] + got[ref + 2:] == want[:ref] + want[ref + 2:]
            assert want[ref:ref + 2] == struct.pack("<H", 0x8000 | index + 1)


def test_keywords_name_a_cut_without_a_dimension():
    """15.1.5: the cut's element, and the circle sketch's, are SOLIDWORKS' own in o10 and o11."""
    for name in ("o10", "o11"):
        extrusions, sketches, kw = CUT.keyword_elements(name)
        assert extrusions in kw and sketches in kw
        assert 'Name="Cut-Extrude1" Dissectable="true"' in extrusions


def test_the_rules_of_15_6_give_a_box_with_a_hole():
    """15.6.2 to 15.6.6 for a box with a hole: the items, the bodies, the order of 15.2.7.5,
    and every member assembles from the slots the generator's identity gives."""
    doc = _box_with_hole()
    slots = D.design_slots(doc, D.generator_identity(doc, D.Identity.new()))
    sketch, cut = slots["features"][2:]
    assert (sketch["id"], cut["id"], sketch["circle"], cut["cut"]) == (33, 40, True, True)
    assert sketch["start"] == [0.0075, 0.01] and cut["target_uid"] == 32 and cut["body_id"] == 102
    assert [(e["kind"], e["face"]) for e in cut["ring"]] == [(1, 4), (2, 1), (1, 3), (2, 0), (1, 1)]
    assert [(b["id"], b["live"], b["from"], b["into"]) for b in slots["bodies"]] == [
        (101, False, [], [102]), (102, True, [101], [])]
    assert [b["feature"] for b in slots["builds"]] == [40, 32]
    assert slots["model"]["max"] == [0.01, 0.02, 0.03] and slots["hdr"]["next_id"] == 41
    results = _assemble_all(slots)
    assert len(results) == 35
    assert results["ModelStamps"].data[4:] == bytes.fromhex("8c0000006f000000")
    c0, feats = results["Contents/Config-0"].data, results["Contents/Config-0-ResolvedFeatures"].data
    assert F_.object_map(c0, feats)[0].count == F_.header(feats)[0]
    assert [n.name for n in F_.named_nodes(feats)][-4:] == ["Boss-Extrude1", "D1", "Sketch2", "Cut-Extrude1"]


@pytest.mark.parametrize("change, reason", [
    (lambda d: setattr(d.features[3], "direction", "forward"), "both directions"),
    (lambda d: setattr(d.features[3], "end", "blind"), "both directions"),
    (lambda d: setattr(d.features[2].curves[0], "radius", 0.006), "inside the box"),
    (lambda d: d.features[2].curves.append(ir.Curve("k2", "circle", ["c"], radius=0.001)),
     "more than one circle"),
    (lambda d: d.features.extend([D.circle_sketch("s3", "S3", 0.005, 0.01, 0.001),
                                  D.through_cut("e3", "Cut2", "s3")]), "last feature"),
    (lambda d: d.features.__setitem__(slice(2, 2), [D._rectangle("s9", "S9", 0.03, 0.0, 0.04, 0.02),
                                                    ir.Extrude("e9", "E9", "s9", 0.01)]), "one box"),
])
def test_the_rules_of_15_6_refuse_what_the_fixtures_do_not_show(change, reason):
    doc = _box_with_hole()
    change(doc)
    with pytest.raises(ValueError, match=reason):
        D.features_of(doc)


@pytest.mark.parametrize("change, reason", [
    (lambda d: d.features[2].curves.append(ir.Curve("k2", "circle", ["c"], radius=0.001)),
     "more than one circle"),
    (lambda d: d.features[2].curves.append(ir.Curve("l9", "line", ["c", ir.ORIGIN])),
     "not a single corner rectangle"),
    (lambda d: setattr(d.features[2].curves[0], "construction", True), "more than one circle"),
])
def test_15_6_2_routes_a_sketch_by_whether_its_curves_are_all_circles(change, reason):
    """15.6.2: a sketch of circles only goes to the circle table, one that mixes a circle
    with lines to the rectangle table."""
    doc = _box_with_hole()
    change(doc)
    with pytest.raises(ValueError, match=reason):
        D.features_of(doc)


def test_a_degenerate_circle_never_reaches_the_rules_of_15_6():
    """15.6.2's "degenerate circle" row: the IR's validation, step 1 of 15.6.1, refuses it first."""
    doc = _box_with_hole()
    doc.features[2].curves[0].radius = 0.0
    with pytest.raises(ir.IRError, match="positive radius"):
        ir.validate(doc)


# ------------------------------------------------------------------ fillets (15.5.14)
def filleted(corners=(0.0, 0.0, 0.04, 0.03), depth=0.01, r=0.003, hole=(0.02, 0.015, 0.005), r2=0.001,
             box_fillet=True, hole_fillet=True) -> ir.Document:
    """A box, a fillet on its four edges along its depth (each named by its middle), a hole cut
    through all and a fillet on the hole's edge on the far face (named by its point on +x):
    o11's form, with each part optional."""
    x0, y0, x1, y1 = corners
    feats = [D._rectangle("s1", "Sketch1", *corners), ir.Extrude("e1", "Extrude1", "s1", depth)]
    if box_fillet:
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        feats.append(ir.Fillet("f1", "Round", [ir.EdgeRef((x, y, depth / 2)) for x, y in pts], r))
    if hole is not None:
        cx, cy, rh = hole
        feats += [D.circle_sketch("s2", "Sketch2", cx, cy, rh), D.through_cut("e2", "Cut1", "s2")]
        if hole_fillet:
            feats.append(ir.Fillet("f2", "Rim", [ir.EdgeRef((cx + rh, cy, depth))], r2))
    return ir.validate(ir.Document("block", feats))


def _move_hole(doc: ir.Document, cx: float, cy: float, r: float) -> None:
    """Put the hole of :func:`filleted` elsewhere: inside the box's rectangle, but reaching into
    the square a 3 mm fillet rounds at the first corner."""
    circle = doc.features[3]
    circle.points[0].x, circle.points[0].y = cx, cy
    circle.curves[0].radius = r


def _change_count_at(result: L.Result) -> int:
    """The offset of the change count (15.2.3.2) in a member assembled by its listing."""
    for run in result.runs:
        line = (LISTINGS / run.source).read_text(encoding="utf-8").splitlines()[run.line - 1]
        if "=101+len($features)" in line:
            return run.offset
    raise AssertionError("no change count")


def _o11_gives_its_members(results: dict[str, L.Result]) -> None:
    """Every member of o11 byte for byte, but its change count (15.2.3.2), a session counter: 106
    where the rule gives 101 and one for each of its six features."""
    fx = S.fixture("o11")
    assert len(results) == 35
    wrong = {m for m, r in results.items() if r.data != fx[m]}
    assert wrong == {"Contents/CMgrHdr2", "Contents/Config-0"}
    for m in wrong:
        got, want = results[m].data, fx[m]
        k = _change_count_at(results[m])
        assert got[k:k + 4] == struct.pack("<I", 107) and want[k:k + 4] == struct.pack("<I", 106)
        assert got[:k] + got[k + 4:] == want[:k] + want[k + 4:]


@pytest.mark.parametrize("which", ["Fillet1", "Fillet2"])
def test_the_fillet_listing_gives_o11s_fillets(which):
    """15.5.14 on o11, each fillet byte for byte with the archive o11 has where it starts: Fillet1
    on the box's four edges along its depth, Fillet2 on the hole's edge on the far face. What is
    read from o11 agrees with the rest of the part: each fillet's creation time is its history
    entry's (15.5.3), and the counter of its mark record is its body's rebuild counter (15.4.6)."""
    case = FIL.feature_case(which)
    assert case.got == case.want
    f = case.slots["features"][0]
    feats = S.fixture("o11")[CUT.FEATURES]
    uid = _uid("o11")
    assert f["created"] == CUT.history_created(feats, uid[which])
    regen = {b["id"]: b["regen"] for b in FIL.o11_slots()["bodies"]}
    assert f["body_regen"] == regen[f["body_id"]]
    assert F_.parameter(feats, f"D1@{which}").value == f["radius"]
    owners = {e["uid"] for e in f["edges"][0]["faces"]}
    box, cut = uid["Boss-Extrude1"], uid["Cut-Extrude1"]
    assert owners == ({box} if which == "Fillet1" else {box, cut})


def test_one_slot_dict_gives_every_member_of_o11():
    """o11, a box, a fillet, a hole and a fillet, as a whole: one slot dict assembles all 35 of
    its members, the feature stream with its six features, the second annotation view of
    Contents/Config-0 (15.4.9) and the fillets' KeyWords elements (15.1.5) included."""
    _o11_gives_its_members(_assemble_all(FIL.o11_slots()))


def test_the_rules_of_15_6_give_o11_from_its_design():
    """Section 15.6 on o11 written as a design, with only its identity and free slots read from
    it: all 35 members, as for the boxes."""
    _o11_gives_its_members(_assemble_all(D.design_slots(FIL.o11_design(), FIL.o11_identity())))


@pytest.mark.parametrize("box_fillet, hole, hole_fillet", [
    (True, False, False), (True, True, False), (False, True, True), (True, True, True)])
def test_the_rules_of_15_6_give_a_box_with_fillets(box_fillet, hole, hole_fillet):
    """15.6.2 to 15.6.6 for each combination o11's features allow: the items, the creation
    numbers (a fillet's radius dimension takes the number before the fillet's, 15.5.4), the bodies
    a fillet changes and renames, the second annotation view, and all 35 members assemble with
    the archive counted through (15.0.4)."""
    doc = filleted(corners=(0.012, 0.004, 0.052, 0.034), hole=(0.03, 0.02, 0.005) if hole else None,
                   box_fillet=box_fillet, hole_fillet=hole_fillet)
    slots = D.design_slots(doc, D.generator_identity(doc, D.Identity.new()))
    feats = slots["features"]
    names = [f["name"] for f in feats]
    ids = [f["id"] for f in feats]
    expect = {(True, False, False): (["Sketch1", "Boss-Extrude1", "Fillet1"], [26, 32, 34]),
              (True, True, False): (["Sketch1", "Boss-Extrude1", "Fillet1", "Sketch2", "Cut-Extrude1"],
                                    [26, 32, 34, 35, 42]),
              (False, True, True): (["Sketch1", "Boss-Extrude1", "Sketch2", "Cut-Extrude1", "Fillet1"],
                                    [26, 32, 33, 40, 42]),
              (True, True, True): (["Sketch1", "Boss-Extrude1", "Fillet1", "Sketch2", "Cut-Extrude1",
                                    "Fillet2"],
                                   [26, 32, 34, 35, 42, 44])}[(box_fillet, hole, hole_fillet)]
    assert (names, ids) == expect
    assert slots["hdr"]["next_id"] == ids[-1] + 1 and slots["model"]["back_view"] is box_fillet
    fillets = [f for f in feats if not f["sketch"] and f["fillet"]]
    assert [f["hole"] for f in fillets] == [False] * box_fillet + [True] * hole_fillet
    live = slots["live_bodies"][0]
    assert live["name"] == names[-1] if not feats[-1]["sketch"] else True
    assert live["changed"] == [f["id"] for f in fillets if f["body_id"] == live["id"]]
    if box_fillet:
        assert fillets[0]["anchor"] == [0.012 + 0.003, 0.004 + 0.003, 0.01]
    if hole and box_fillet:
        ring = next(f for f in feats if not f["sketch"] and f["cut"])["ring"]
        assert [(e["kind"], e["uid"], e["face"]) for e in ring] == [
            (1, 32, 4), (2, 32, 1), (4, 34, 1), (2, 32, 0), (4, 34, 4)]
    kw = [g["id"] for g in slots["meta"]["kw_features"]]
    assert kw == sorted(kw, key=str) and len(kw) == 23 + len(fillets)
    results = _assemble_all(slots)
    assert len(results) == 35
    c0, stream = results["Contents/Config-0"].data, results["Contents/Config-0-ResolvedFeatures"].data
    assert F_.object_map(c0, stream)[0].count == F_.header(stream)[0]
    assert [n.name for n in F_.named_nodes(stream) if n.name in names] == names
    assert [p.full_name for p in F_.parameters(stream)] == (
        ["D1@Boss-Extrude1"] + [f"D1@{f['name']}" for f in fillets])
    for f in fillets:
        assert F_.parameter(stream, f"D1@{f['name']}").value == f["radius"]
    # "*Back" is also a standard view's name in every Contents/Config-0; the annotation view adds one
    assert c0.count("*Back".encode("utf-16-le")) == 1 + int(box_fillet)


@pytest.mark.parametrize("change, reason", [
    (lambda d: d.features[2].edges.pop(), "all four of its edges"),
    (lambda d: setattr(d.features[2].edges[0], "point", (0.0, 0.0, 0.0)), "all four of its edges"),
    (lambda d: setattr(d.features[2].edges[0], "point", (0.0, 0.0, 0.0105)), "all four of its edges"),
    (lambda d: d.features[2].edges.append(ir.EdgeRef((0.0, 0.0, 0.002))), "all four of its edges"),
    (lambda d: setattr(d.features[2], "radius", 0.015), "half the box's shorter side"),
    (lambda d: setattr(d.features[2], "suppressed", True), "suppressed fillet"),
    (lambda d: d.features.insert(0, d.features.pop(2)), "right after the box's extrusion"),
    (lambda d: d.features.insert(3, ir.Fillet("f9", "Again", list(d.features[2].edges), 0.001)),
     "right after the box's extrusion"),
    (lambda d: d.features.insert(3, d.features.pop(5)), "right after the box's extrusion"),
    (lambda d: setattr(d.features[5].edges[0], "point", (0.025, 0.015, 0.0)),
     "hole's edge on the box's far face"),
    (lambda d: setattr(d.features[5].edges[0], "point", (0.026, 0.015, 0.01)),
     "hole's edge on the box's far face"),
    (lambda d: setattr(d.features[5], "radius", 0.01), "stay on the box's far face"),
    (lambda d: _move_hole(d, 0.008, 0.008, 0.0075), "rounded corner"),
    (lambda d: d.features.append(ir.Fillet("f9", "Again", list(d.features[5].edges), 0.0005)),
     "only as the last feature"),
    (lambda d: d.features.extend([D._rectangle("s9", "S9", 0.05, 0.0, 0.06, 0.01),
                                  ir.Extrude("e9", "E9", "s9", 0.01)]), "one box"),
])
def test_the_rules_of_15_6_refuse_a_fillet_the_fixtures_do_not_show(change, reason):
    doc = filleted()
    change(doc)
    with pytest.raises(ValueError, match=reason):
        D.features_of(doc)


# ------------------------------------------------------------------ flags and memo (15.4.2)
_ALWAYS_HIGH = {"Front Plane", "Top Plane", "Right Plane", "Origin"}


def test_bit_31_of_a_node_is_set_on_design_records_only_in_an_inactive_configuration():
    """15.4.2: in every part fixture, bit 31 of the flags is set on the planes and the origin in
    every stream, and on a design record only in o13's Config-1 (Tall, not active at save)."""
    high = {}
    for path in sorted(S.FIXTURES.glob("*.SLDPRT")):
        fx = S.fixture(path.name)
        for member in (m for m in fx.members if m.endswith("-ResolvedFeatures")):
            for n in F_.named_nodes(fx[member]):
                if n.name == "D1":
                    continue
                flags = struct.unpack_from("<I", fx[member], n.end + 4)[0]
                if n.name in _ALWAYS_HIGH:
                    assert flags & 0x80000000, (path.name, member, n.name)
                elif flags & 0x80000000:
                    high.setdefault((path.name[:3], member), []).append(n.name)
    assert high == {("o13", "Contents/Config-1-ResolvedFeatures"): ["Sketch1", "Boss-Extrude1"]}


def test_the_double_o02_and_o07_differ_in_is_the_extrusion_memo():
    """15.4.2: the double at offset 8716 of the feature stream, 0 in o02 and 0.016 in o07, is the
    MEMO of Boss-Extrude1's tail, the slot cache_memo the cases read there."""
    for part, value in (("o02", 0.0), ("o07", 0.016)):
        feats = S.fixture(part)[CUT.FEATURES]
        assert struct.unpack_from("<d", feats, 8716)[0] == value
        extrusion = F.full_slots(part)["features"][1]
        assert extrusion["name"] == "Boss-Extrude1" and extrusion["cache_memo"] == value
    result = L.assemble(LISTINGS / "config-0-resolvedfeatures.srl", F.full_slots("o07"),
                        L.assemble(LISTINGS / "config-0.srl", F.full_slots("o07")).archive)
    memo = [r for r in result.runs if r.offset == 8716]
    assert memo and memo[0].source == "config-0-macros.srl" and memo[0].size == 8


# ------------------------------------------------------------------ shaded image quality (15.4.7)
def relmgr(config: bytes) -> bytes:
    """The run of ``Contents/Config-0`` from ``moRelMgr_c`` to ``moEnvFolder_c`` (15.4.7)."""
    return config[config.find(b"moRelMgr_c"):config.find(b"moEnvFolder_c")]


def hole_facets(name: str, cx: float, cy: float, r: float) -> int:
    """The number of facets SOLIDWORKS' own display list draws round a hole's wall: the
    distinct angles of the positions of the one face whose every point lies on the hole."""
    import math

    from solidseas.formats.solidworks.mesh import parse_tess_tables

    found = []
    for t in parse_tess_tables(S.fixture(name)["Contents/DisplayLists"]):
        pos = t["positions"]
        pts = [pos[i:i + 3] for i in range(0, len(pos), 3)]
        if pts and all(abs(math.hypot(p[0] - cx, p[1] - cy) - r) < 2e-5 for p in pts):
            found.append({round(math.degrees(math.atan2(p[1] - cy, p[0] - cx)), 3) % 360 for p in pts})
    assert len(found) == 1
    return len(found[0])


def test_every_part_fixture_carries_the_same_drafting_settings():
    """15.4.7: no fixture saves another image quality or drafting setting; o09 and o10 differ
    only in class references one higher (the import starts the archive at 3)."""
    base = relmgr(S.fixture("o02")[CUT.CONFIG])
    assert len(base) == 17326
    for name in ("o01", "o03", "o04", "o05", "o06", "o07", "o11", "o12", "o13", "o14", "o17"):
        assert relmgr(S.fixture(name)[CUT.CONFIG]) == base, name
    o10 = relmgr(S.fixture("o10")[CUT.CONFIG])
    assert len(o10) == len(base)
    assert {(base[i], o10[i]) for i in range(len(base)) if base[i] != o10[i]} == {(10, 11)}


def test_solidworks_own_display_lists_draw_a_hole_with_few_facets():
    """15.4.7: with the template's settings, o10's 2.5 mm hole has 8 facets, o11's 5 mm hole 18."""
    assert hole_facets("o10", 0.005, 0.01, 0.0025) == 8
    assert hole_facets("o11", 0.02, 0.015, 0.005) == 18
