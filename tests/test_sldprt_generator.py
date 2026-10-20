"""The clean-room generator held to the specification and to SOLIDWORKS' own parts.

Analysis side (docs/CLEANROOM.md section 1): these tests read the SOLIDWORKS-made
fixtures and the analysis side's reference reading of the specification, which the
generator's author never sees. Only the verdict, and a difference described in the
specification's terms, goes back to the implementation.

- ``assemble`` with the slot dict of a fixture gives every member of that fixture,
  byte for byte (README 15.0.7).
- ``plan`` of a fixture's design gives the slot dict the analysis side's reading of
  section 15.6 gives, with the same identity.
- A written part opens in SolidSeas' reader as the design: its features, its depth
  parameters, its sketch points, and nothing about a person.
"""

import importlib
import struct
from datetime import UTC, datetime

import pytest

import test_sldprt_spec as SPEC
from solidseas.formats.solidworks import open_document
from solidseas.formats.solidworks.container import open_container
from swnative import features as F
from swnative import speccases as S
from swnative.speccases import design as D
from swnative.speccases import full as FULL

try:
    gen = importlib.import_module("solidseas.nativewrite.generate")
except ImportError:  # the generator is not written yet
    gen = None

pytestmark = pytest.mark.skipif(gen is None, reason="the generator is not written yet")
WHEN = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)


def _identity(**kw):
    values = dict(
        when=WHEN, key_index=17, anim_guid="{0F1E2D3C-4B5A-4978-8695-A4B3C2D1E0F0}",
        exch_front="11111111-2222-4333-8444-555555555555", exch_top="21111111-2222-4333-8444-555555555555",
        exch_right="31111111-2222-4333-8444-555555555555", exch_doc="41111111-2222-4333-8444-555555555555",
        exch_config="51111111-2222-4333-8444-555555555555",
    )
    values.update(kw)
    return values


def _first_difference(a: bytes, b: bytes) -> str:
    n = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]), min(len(a), len(b)))
    return (f"byte {n} of {len(b)} (written {len(a)}): "
            f"wrote {a[n:n + 12].hex(' ')}, expected {b[n:n + 12].hex(' ')}")


@pytest.mark.parametrize("part", FULL.PARTS)
def test_assemble_gives_every_member_of_the_fixture(part):
    fx = S.fixture(part)
    members = gen.assemble(FULL.full_slots(part))
    assert len(members) == 35
    wrong = {m: _first_difference(data, fx[m]) for m, data in members.items() if data != fx[m]}
    assert wrong == {}


def _diff(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                out.append(f"{path}.{k}: only in {'reference' if k in b else 'generator'}")
            else:
                out += _diff(a[k], b[k], f"{path}.{k}")
        return out
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            return [f"{path}: {len(a)} items, expected {len(b)}"]
        return [d for i, (x, y) in enumerate(zip(a, b, strict=True)) for d in _diff(x, y, f"{path}[{i}]")]
    if isinstance(a, float) or isinstance(b, float):
        same = struct.pack("<d", float(a)) == struct.pack("<d", float(b))
        return [] if same else [f"{path}: {a!r}, expected {b!r}"]
    return [] if a == b else [f"{path}: {a!r}, expected {b!r}"]


def _comparable(slots: dict, prefix: str = "") -> dict:
    """The slot dict with nested dicts spelled as dotted names (the generator keeps a flat
    dict, the analysis side a nested one), lists kept whole."""
    out = {}
    for k, v in slots.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict):
            out.update(_comparable(v, f"{prefix}{k}."))
        else:
            out[f"{prefix}{k}"] = v
    return out


@pytest.mark.parametrize("part", FULL.PARTS)
def test_plan_gives_the_slots_section_15_6_gives(part):
    doc = D.fixture_design(part)
    plan = gen.plan(doc, identity=gen.Identity(**_identity()))
    expected = D.design_slots(doc, D.generator_identity(doc, D.Identity(**_identity())))
    assert _diff(_comparable(plan.slots), _comparable(expected)) == []


@pytest.mark.parametrize("part", FULL.PARTS)
def test_a_written_fixture_design_has_every_member_the_plan_assembles(part):
    doc = D.fixture_design(part)
    ident = gen.Identity(**_identity())
    slots = D.design_slots(doc, D.generator_identity(doc, D.Identity(**_identity())))
    expected = {m: r.data for m, r in SPEC._assemble_all(slots).items()}  # the analysis side's assembler
    with open_container(gen.write_part(doc, identity=ident)) as c:
        written = {s.name: c.read(s.name) for s in c.streams()}
    assert sorted(written) == sorted(expected)
    assert {m for m in written if written[m] != expected[m]} == set()


@pytest.mark.parametrize("part", ["o02", "o12"])
def test_a_written_part_reads_back_as_its_design(part):
    doc = D.fixture_design(part)
    ident = gen.Identity(**_identity())
    names = gen.plan(doc, identity=ident).names
    data = gen.write_part(doc, identity=ident)
    with open_document(data, name="written.SLDPRT") as d:
        assert d.doc_type == "part"
        summary = d.summary(include=("properties", "configurations"))
        assert summary is not None
        report = d.path_report()
    assert report.paths == () and report.hosts == ()
    assert {a.name for a in report.accounts} <= {"SolidSeas"}  # the author fields name SolidSeas (15.0.6)
    with open_container(data) as c:
        config, stream = c.read("Contents/Config-0"), c.read("Contents/Config-0-ResolvedFeatures")
    node_names = [n.name for n in F.named_nodes(stream)]
    extrudes = [f for f in doc.features if f.type == "extrude"]
    for f in extrudes:
        assert F.parameter(stream, f"D1@{names[f.id]}").value == f.depth
    written = [n for n in node_names if n.startswith(("Sketch", "Boss-Extrude"))]
    assert written == [names[f.id] for f in doc.features]
    a, b = F.object_map(config, stream)
    assert F.header(stream)[0] == a.count


def test_an_unsupported_design_is_refused_item_by_item():
    doc = D.fixture_design("o02")
    doc.features[0].plane = type(doc.features[0].plane).named("yz")
    with pytest.raises(gen.NativeWriteUnsupported) as err:
        gen.write_part(doc)
    assert err.value.items
