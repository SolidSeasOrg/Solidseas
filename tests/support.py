"""Paths and names of the synthetic fixtures, and the slack of the tests' time bounds."""

import os
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

# How much slower than the development machines a run may be before a time bound fails:
# a loaded PC, a slow runner. A bound says that something stops or finishes in time,
# against a hang or a limit not kept; it is not a benchmark. SOLIDSEAS_TEST_SLACK sets
# more for a machine that needs it.
SLACK = max(1.0, float(os.environ.get("SOLIDSEAS_TEST_SLACK") or 3.0))


def within(seconds: float) -> float:
    """A test's time bound of ``seconds``, with the run's :data:`SLACK`."""
    return seconds * SLACK


PARTS = [
    "o01_empty.SLDPRT",
    "o02_boxA.SLDPRT",
    "o03_boxA_again.SLDPRT",
    "o04_boxA_props.SLDPRT",
    "o05_boxA_props_mat.SLDPRT",
    "o06_boxA_props_mat_cfg.SLDPRT",
    "o07_boxB_h31.SLDPRT",
]
ASSEMBLY = "o08_asm_2x_boxA.SLDASM"
NATIVE = [*PARTS, ASSEMBLY]
# Every SOLIDWORKS document in the fixtures folder: NATIVE and the eleven the kit added
# (o09 to o19). Tests that open the folder itself count these.
DOCUMENTS = sorted(
    p.name for p in FIXTURES.iterdir() if p.suffix.upper() in {".SLDPRT", ".SLDASM", ".SLDDRW"}
)


def fixture_path(name: str) -> Path:
    return FIXTURES / name


# The SOLIDWORKS documents the fixture kit made, and its two logs, carry the name of the
# account that ran it, so they live in a private repository and are copied here by
# scripts/fetch-fixtures.py (CI does it with a secret). Without them, every test module
# that needs them is left out of the run (conftest.py says how many).
PRIVATE_FIXTURES = ("*.SLDPRT", "*.SLDASM", "*.SLDDRW", "generation.log", "scrub_report.txt")
PRIVATE_PRESENT = (FIXTURES / "o02_boxA.SLDPRT").is_file()


def ground_truth() -> dict:
    """``ground_truth.json``, with the account fields the public copy leaves out merged
    back from ``ground_truth.private.json`` when the private fixtures are here."""
    import json

    gt = json.loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))
    private = FIXTURES / "ground_truth.private.json"
    if private.is_file():
        extra = json.loads(private.read_text(encoding="utf-8"))
        for key, value in extra.items():
            if isinstance(value, dict) and isinstance(gt.get(key), dict):
                gt[key] = {**gt[key], **value}
            else:
                gt[key] = value
    return gt


def parts_at_stored_paths(assembly) -> bool:
    """Whether any component file of the fixture ``assembly`` exists where the assembly
    stored its path: on the PC that ran the fixture kit (its output folder under
    C:\\Users\\Public\\Documents), where reference resolution rightly finds the parts at
    those paths even beside a lone copy of the assembly."""
    from solidseas import bom, open_document

    with open_document(fixture_path(assembly) if isinstance(assembly, str) else assembly) as doc:
        found = bom.build_bom(doc, read_properties=False)
    return any(r.stored_path and os.path.exists(r.stored_path) for r in (found.rows if found else ()))
