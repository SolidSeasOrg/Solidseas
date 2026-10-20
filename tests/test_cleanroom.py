"""The clean-room rules of docs/CLEANROOM.md that a program can check.

The generator (``solidseas.nativewrite.generate``) is written from the
specification alone. These tests belong to the analysis side: they may read
the SOLIDWORKS-made fixtures, and they hold the generator to section 4 of the
rules. Until the generator exists the tests that run it are skipped; the
source and package checks run now.
"""

import importlib
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "solidseas" / "nativewrite"
GENERATE = PACKAGE / "generate"
FIXTURES = ROOT / "tests" / "fixtures"
RUN = 32  # bytes: the longest run the output may share with a SOLIDWORKS-made file
# Names the generator's source must not contain: fixtures, the research code, the readers.
FORBIDDEN_IN_GENERATOR = (
    "fixtures", "swnative", "research", "read_document", "open_container", "formats.solidworks",
    "o01_", "o02_", ".SLDPRT", "SEED", "seed",
)
# Names no shipped nativewrite module may contain.
FORBIDDEN_IN_PACKAGE = ("swnative", "tests/fixtures", "research/")


def _sources(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*.py")) if folder.exists() else []


def test_the_shipped_package_does_not_reach_the_research_code():
    for p in _sources(PACKAGE):
        text = p.read_text(encoding="utf-8")
        for name in FORBIDDEN_IN_PACKAGE:
            assert name not in text, f"{p.relative_to(ROOT)} names {name!r}"
    assert not (ROOT / "src" / "swnative").exists()


@pytest.mark.skipif(not GENERATE.exists(), reason="the generator is not written yet")
def test_the_generator_source_names_no_fixture_research_or_reader():
    for p in _sources(GENERATE):
        code = re.sub(r"#[^\n]*", "", p.read_text(encoding="utf-8"))
        for name in FORBIDDEN_IN_GENERATOR:
            assert name not in code, f"{p.relative_to(ROOT)} names {name!r}"


@pytest.mark.skipif(not GENERATE.exists(), reason="the generator is not written yet")
def test_every_generator_constant_cites_the_specification():
    """A hex or long numeric literal is a constant from the specification and needs ``# spec``."""
    literal = re.compile(r"(0x[0-9A-Fa-f]{3,}|bytes\.fromhex\(|b\"\\x|\b\d{4,}\b)")
    for p in _sources(GENERATE):
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if literal.search(code):
                where = f"{p.relative_to(ROOT)}:{n}"
                assert "# spec " in line, f"{where} has a constant with no '# spec' citation"


# ------------------------------------------------------------------ the generator's output
def _generate_sample():
    gen = importlib.import_module("solidseas.nativewrite.generate")
    from solidseas.nativewrite import solidcraft

    doc = solidcraft.read_ir(FIXTURES / "solidcraft" / "rect-extrude-40x30x10.solidcraft")
    return gen, doc


def _unlike_any_fixture(variant: int = 0):
    """A design and an identity no fixture has: a box of sizes no fixture has, saved in 2031
    with made-up GUIDs. ``variant`` 1 is the same shape with every value changed, so bytes
    the two outputs share are the generator's constants and nothing else."""
    from datetime import UTC, datetime

    from solidseas.nativewrite import ir

    gen = importlib.import_module("solidseas.nativewrite.generate")
    w, h, d = ((0.0373, 0.0217, 0.0139), (0.0291, 0.0446, 0.0287))[variant]
    pts = [ir.Point(f"p{k}", x, y) for k, (x, y) in enumerate(
        [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)], 1)]
    lines = [ir.Curve(f"l{k}", "line", [f"p{k}", f"p{k % 4 + 1}"]) for k in range(1, 5)]
    rels = [ir.Constraint("k1", "coincident", ["origin", "p1"]),
            ir.Constraint("k2", "horizontal", curves=["l1"]),
            ir.Constraint("k3", "horizontal", curves=["l3"]),
            ir.Constraint("k4", "vertical", curves=["l2"]),
            ir.Constraint("k5", "vertical", curves=["l4"])]
    sketch = ir.Sketch("s1", "Sketch1", ir.Plane.named("xy"), pts, lines, rels)
    doc = ir.Document(name="Bracket blank", features=[sketch, ir.Extrude("e1", "Extrude1", "s1", d)])
    guid = ("{:08x}-6d6e-4f70-8172-737475767778", "{:08x}-9a8b-4c7d-9e6f-a5b4c3d2e1f0")[variant]
    ident = gen.Identity(
        # Day and month names, hours and dates of the same lengths, so the members line up.
        when=(datetime(2031, 3, 7, 9, 41, 13, tzinfo=UTC),
              datetime(2033, 4, 8, 17, 5, 58, tzinfo=UTC))[variant],
        key_index=(613, 288)[variant],
        anim_guid="{" + guid.format(0xA1B2C3D4 + variant).upper() + "}",
        exch_front=guid.format(0xF1 + variant), exch_top=guid.format(0xE2 + variant),
        exch_right=guid.format(0xD3 + variant), exch_doc=guid.format(0xC4 + variant),
        exch_config=guid.format(0xB5 + variant),
    )
    return gen, doc, ident


def _members(blob: bytes) -> dict[str, bytes]:
    from solidseas.formats.solidworks.container import open_container

    with open_container(blob) as c:
        return {s.name: c.read(s.name) for s in c.streams()}


def _fixture_windows() -> set[bytes]:
    """Every RUN-byte window of every member of every SOLIDWORKS-made fixture, but runs of one byte."""
    from solidseas.formats.solidworks.container import open_container

    out: set[bytes] = set()
    for f in sorted(FIXTURES.glob("*.SLD*")):
        with open_container(f) as c:
            for s in c.streams():
                d = c.read(s.name)
                for i in range(0, max(0, len(d) - RUN + 1)):
                    w = d[i : i + RUN]
                    if w.count(w[0]) != RUN:
                        out.add(w)
    return out


@pytest.mark.skipif(not GENERATE.exists(), reason="the generator is not written yet")
def test_generation_opens_no_file():
    gen, doc = _generate_sample()
    gen.write_part(doc, allow_partial=True)  # warm up: imports and caches load now, before the hook
    opened: list[str] = []

    def hook(event, args):
        if event == "open" and args and isinstance(args[0], (str, bytes, Path)):
            opened.append(str(args[0]))

    sys.addaudithook(hook)
    before = len(opened)
    gen.write_part(doc, allow_partial=True)
    assert opened[before:] == []


@pytest.mark.skipif(not GENERATE.exists(), reason="the generator is not written yet")
def test_the_output_shares_no_long_run_with_a_solidworks_made_file():
    gen, doc, ident = _unlike_any_fixture(0)
    _, doc2, ident2 = _unlike_any_fixture(1)
    spec_constants = set(getattr(gen, "SPEC_CONSTANTS", ()))
    windows = _fixture_windows()
    other = _members(gen.write_part(doc2, identity=ident2))
    for name, data in _members(gen.write_part(doc, identity=ident)).items():
        assert len(other[name]) == len(data), f"{name} changed length with the values"
        for i in range(0, max(0, len(data) - RUN + 1)):
            w = data[i : i + RUN]
            # A window that differs between the two outputs holds a value of the design or of
            # the identity; it matching a fixture is the value being the same, not a copy.
            if w != other[name][i : i + RUN]:
                continue
            if w in windows and not any(w in c for c in spec_constants):
                pytest.fail(f"{name} at {i} repeats {RUN} bytes of a SOLIDWORKS-made fixture: {w.hex()}")


@pytest.mark.skipif(not GENERATE.exists(), reason="the generator is not written yet")
def test_the_output_carries_no_personal_information():
    from solidseas.formats.solidworks import open_document

    gen, doc = _generate_sample()
    with open_document(gen.write_part(doc, allow_partial=True)) as d:
        report = d.path_report()
    assert report.paths == () and report.hosts == ()
    assert {a.name for a in report.accounts} <= {"SolidSeas"}  # author fields may name SolidSeas (section 5)
    # The file name at save is the design's own name (15.6.6); every other identity field
    # is empty or names SolidSeas.
    allowed = {"SolidSeas", doc.name, doc.name + ".sldprt", doc.name + ".SLDPRT"}
    assert all(not f.value or f.value in allowed for f in report.identity_fields)
