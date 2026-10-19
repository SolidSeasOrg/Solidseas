"""Seeded mutation fuzzing of the SOLIDWORKS readers (bead ddi, ``fuzz_support``).

Two kinds of case over every part, assembly and drawing fixture: the whole file mutated,
which mostly exercises the container; and one decoded stream mutated and the container
built again around it (``solidseas.nativewrite.container``), which reaches the stream
readers behind a valid container. Each case opens the document and asks it for
everything a viewer or the REST service would: the summary, the preview, references,
components, sheets, embedded paths, the path report, and for a part the Parasolid
bodies and a tessellation.

``SOLIDSEAS_FUZZ_SECONDS=600 pytest tests/test_formats_solidworks_fuzz.py`` runs longer.
"""

import random

import pytest

import fuzz_support as FZ
from solidseas.formats.solidworks import open_document
from solidseas.nativewrite.container import build_container, read_document, with_changes
from support import DOCUMENTS, fixture_path

SEEDS = {name: fixture_path(name).read_bytes() for name in DOCUMENTS}


def _read(name: str):
    def read(data: bytes) -> None:
        with open_document(data, name=name) as d:
            d.summary(include=("properties", "configurations"))
            d.preview()
            d.references()
            d.embedded_paths()
            d.path_report()
            d.nested_documents()
            kind = d.doc_type
            if kind == "assembly":
                d.components()
            elif kind == "drawing":
                d.sheets()
            elif kind == "part":
                d.parasolid()
                d.tessellate(max_seconds=3.0)

    return read


def _stream_case(name: str, k: int) -> tuple[bytes, str]:
    """The seed with one decoded stream mutated, in a container built again."""
    src = read_document(SEEDS[name])
    rng = random.Random(f"stream:{name}:{k}")
    member = rng.choice([m for m in src.members if m.data])
    data, what = FZ.mutate(member.data, rng)
    members = with_changes(src.members, {member.name: data})
    return build_container(members, key=src.key, signatures=src.signatures), f"{member.name}: {what}"


def test_mutated_documents_read_or_raise_a_documented_error():
    problems = []
    for name, k, data, what in FZ.cases(SEEDS, FZ.budget(15.0), FZ.start()):
        found = FZ.check(_read(name), data, f"{name} case {k} ({what})")
        if found:
            problems.append(found)
    assert problems == []


def test_documents_with_a_mutated_stream_read_or_raise_a_documented_error():
    problems = []
    for name, k, _data, _what in FZ.cases(SEEDS, FZ.budget(15.0), FZ.start()):
        data, what = _stream_case(name, k)
        found = FZ.check(_read(name), data, f"{name} stream case {k} ({what})")
        if found:
            problems.append(found)
    assert problems == []


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_a_case_is_the_same_mutation_every_time(seed):
    rng_a, rng_b = random.Random(f"x:{seed}"), random.Random(f"x:{seed}")
    data = bytes(range(256)) * 8
    assert FZ.mutate(data, rng_a) == FZ.mutate(data, rng_b)
