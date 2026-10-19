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
    gen.write_part(doc)  # warm up: imports and caches load now, before the hook
    opened: list[str] = []

    def hook(event, args):
        if event == "open" and args and isinstance(args[0], (str, bytes, Path)):
            opened.append(str(args[0]))

    sys.addaudithook(hook)
    before = len(opened)
    gen.write_part(doc)
    assert opened[before:] == []


@pytest.mark.skipif(not GENERATE.exists(), reason="the generator is not written yet")
def test_the_output_shares_no_long_run_with_a_solidworks_made_file():
    gen, doc = _generate_sample()
    spec_constants = set(getattr(gen, "SPEC_CONSTANTS", ()))
    windows = _fixture_windows()
    for name, data in _members(gen.write_part(doc)).items():
        for i in range(0, max(0, len(data) - RUN + 1)):
            w = data[i : i + RUN]
            if w in windows and not any(w in c for c in spec_constants):
                pytest.fail(f"{name} at {i} repeats {RUN} bytes of a SOLIDWORKS-made fixture: {w.hex()}")


@pytest.mark.skipif(not GENERATE.exists(), reason="the generator is not written yet")
def test_the_output_carries_no_personal_information():
    from solidseas.formats.solidworks import open_document

    gen, doc = _generate_sample()
    with open_document(gen.write_part(doc)) as d:
        report = d.path_report()
    assert report.paths == () and report.accounts == ()
    assert all(not f.value or f.value == "SolidSeas" for f in report.identity_fields)
