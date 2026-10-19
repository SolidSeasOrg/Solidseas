"""Seeded mutation fuzzing of the readers of the other formats in the repository's own
fixtures: Parasolid text and binary, STEP, 3MF and STL (bead ddi, ``fuzz_support``).

Each case opens the mutated file and asks for its summary and its scene. These fixtures
are public, so this runs in every run of the suite, a fork's included.
``SOLIDSEAS_FUZZ_SECONDS=600 pytest tests/test_formats_fuzz.py`` runs longer.
"""

from pathlib import Path

import fuzz_support as FZ
from solidseas.formats import open_model

HERE = Path(__file__).parent
SEEDS = {
    p.name: p.read_bytes()
    for p in sorted(
        [*(HERE / "fixtures").glob("*.x_[tb]"), *(HERE / "fixtures").glob("*.step"),
         *(HERE / "fixtures").glob("*.3mf"), *(HERE / "fixtures").glob("*.STL"),
         *(HERE / "generated").glob("*.step")]
    )  # fmt: skip
}


def _read(name: str):
    def read(data: bytes) -> None:
        with open_model(data, name=name) as m:
            m.summary()
            m.scene(max_seconds=3.0)

    return read


def test_the_seeds_are_there():
    assert {".x_t", ".x_b", ".step", ".3mf", ".STL"} <= {Path(n).suffix for n in SEEDS}


def test_mutated_files_read_or_raise_a_documented_error():
    problems = []
    for name, k, data, what in FZ.cases(SEEDS, FZ.budget(15.0), FZ.start()):
        found = FZ.check(_read(name), data, f"{name} case {k} ({what})")
        if found:
            problems.append(found)
    assert problems == []
