"""The generation specification's listings give SOLIDWORKS' own bytes (docs/sldprt-spec 15.0.5).

Analysis side of the clean room (docs/CLEANROOM.md): these tests read the
SOLIDWORKS-made fixtures. Each case assembles a listing with one fixture's slot
values and compares the result with that fixture's member, byte for byte. Only the
verdict and a specification-level description of a difference go to the
implementation.
"""

import re
from pathlib import Path

import pytest

from solidseas.formats.solidworks import open_document
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
