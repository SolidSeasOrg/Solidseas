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


# ------------------------------------------------------------------ a box with a hole (15.5.12, 15.5.13)
# Each is a corner rectangle extruded blind and a circle inside it cut through all in both
# directions; the second's box is off the origin and the third's at another size. They
# fail until the generator writes holes; each difference is described in specification
# terms by the assertion.
HOLES = {
    "o10-like": ((0.0, 0.0, 0.01, 0.02), 0.03, (0.005, 0.01), 0.0025),
    "off-origin": ((0.012, 0.004, 0.052, 0.034), 0.01, (0.03, 0.02), 0.005),
    "o11-like": ((0.0, 0.0, 0.04, 0.03), 0.01, (0.02, 0.015), 0.005),
}


def _hole(key):
    corners, depth, (cx, cy), r = HOLES[key]
    from solidseas.nativewrite import ir

    return ir.validate(ir.Document("plate", [
        D._rectangle("s1", "Sketch1", *corners), ir.Extrude("e1", "Extrude1", "s1", depth),
        D.circle_sketch("s2", "Sketch2", cx, cy, r), D.through_cut("e2", "Cut1", "s2")]))


@pytest.mark.parametrize("key", HOLES)
def test_plan_gives_the_slots_section_15_6_gives_for_a_box_with_a_hole(key):
    doc = _hole(key)
    plan = gen.plan(doc, identity=gen.Identity(**_identity()))
    expected = D.design_slots(doc, D.generator_identity(doc, D.Identity(**_identity())))
    assert _diff(_comparable(plan.slots), _comparable(expected)) == []


@pytest.mark.parametrize("key", HOLES)
def test_a_written_box_with_a_hole_has_every_member_the_specification_gives(key):
    doc = _hole(key)
    ident = gen.Identity(**_identity())
    slots = D.design_slots(doc, D.generator_identity(doc, D.Identity(**_identity())))
    expected = {m: r.data for m, r in SPEC._assemble_all(slots).items()}
    with open_container(gen.write_part(doc, identity=ident)) as c:
        written = {s.name: c.read(s.name) for s in c.streams()}
    assert sorted(written) == sorted(expected)
    wrong = {m: _first_difference(written[m], expected[m]) for m in written if written[m] != expected[m]}
    assert wrong == {}


def test_a_written_box_with_a_hole_reads_back_as_its_design():
    doc = _hole("o10-like")
    ident = gen.Identity(**_identity())
    data = gen.write_part(doc, identity=ident)
    with open_container(data) as c:
        config, stream = c.read("Contents/Config-0"), c.read("Contents/Config-0-ResolvedFeatures")
    names = [n.name for n in F.named_nodes(stream)]
    assert names[-4:] == ["Boss-Extrude1", "D1", "Sketch2", "Cut-Extrude1"]
    assert [p.full_name for p in F.parameters(stream)] == ["D1@Boss-Extrude1"]  # a cut through all has no D1
    a, _b = F.object_map(config, stream)
    assert F.header(stream) == (a.count, 21)
    with open_document(data, name="written.SLDPRT") as d:
        report = d.path_report()
    assert report.paths == () and report.hosts == ()


@pytest.mark.parametrize("change", [
    "forward", "blind", "two circles", "outside", "a second box", "a second cut", "join",
])
def test_a_cut_the_specification_does_not_give_is_refused(change):
    """15.6.2: what the fixtures do not show is refused item by item, never written."""
    from solidseas.nativewrite import ir

    doc = _hole("o10-like")
    sketch, cut = doc.features[2], doc.features[3]
    if change == "forward":
        cut.direction = "forward"
    elif change == "blind":
        cut.end, cut.depth = "blind", 0.005
    elif change == "two circles":
        sketch.curves.append(ir.Curve("k2", "circle", ["c"], radius=0.001))
    elif change == "outside":
        sketch.curves[0].radius = 0.006
    elif change == "a second box":
        doc.features[2:2] = [D._rectangle("s9", "Sketch9", 0.03, 0.0, 0.04, 0.02),
                             ir.Extrude("e9", "E9", "s9", 0.01)]
    elif change == "a second cut":
        doc.features += [D.circle_sketch("s3", "Sketch3", 0.005, 0.015, 0.001),
                         D.through_cut("e3", "Cut2", "s3")]
    else:
        cut.operation = "join"
    with pytest.raises(gen.NativeWriteUnsupported) as err:
        gen.write_part(doc)
    assert err.value.items


@pytest.mark.parametrize("change, reason", [
    ("two circles", "more than one circle"),
    ("a circle and a line", "not a single corner rectangle"),
])
def test_a_sketch_goes_to_the_circle_table_only_when_its_curves_are_all_circles(change, reason):
    """15.6.2: circles only go to the circle table; a circle mixed with lines to the rectangle's."""
    from solidseas.nativewrite import ir

    doc = _hole("o10-like")
    curves = doc.features[2].curves
    if change == "two circles":
        curves.append(ir.Curve("k2", "circle", ["c"], radius=0.001))
    else:
        curves.append(ir.Curve("l9", "line", ["c", ir.ORIGIN]))
    with pytest.raises(gen.NativeWriteUnsupported) as err:
        gen.plan(doc)
    assert len(err.value.items) == 1 and reason in err.value.items[0]


def test_a_written_box_with_a_hole_carries_solidworks_own_display_settings():
    """15.4.7: the generated hole part of o11's size holds o11's drafting settings, curvature
    object and stored box, so none of them is a coarser image quality than SOLIDWORKS'."""
    doc = _hole("o11-like")
    with open_container(gen.write_part(doc, identity=gen.Identity(**_identity()))) as c:
        config, header = c.read("Contents/Config-0"), c.read("Header2")
    o11 = S.fixture("o11")
    assert SPEC.relmgr(config) == SPEC.relmgr(o11["Contents/Config-0"])

    def curvature(data: bytes) -> bytes:
        k = data.find(b"gcCurvatureObject_c") + len(b"gcCurvatureObject_c")
        return data[k:k + 40]

    assert curvature(config) == curvature(o11["Contents/Config-0"])
    box = struct.pack("<6d", 0.04, 0.03, 0.01, 0.0, 0.0, 0.0)  # model.max, then model.min
    assert box in header and box in o11["Header2"]
