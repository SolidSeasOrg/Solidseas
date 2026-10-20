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
from swnative import listing as L
from swnative import speccases as S
from swnative.speccases import design as D
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
