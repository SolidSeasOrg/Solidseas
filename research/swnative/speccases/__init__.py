"""The cases that prove the specification's listings (``docs/sldprt-spec``, section 15.0.5).

Each section's module here lists ``CASES``: a fixture, one of its members, the
listing that should give that member, and the function that returns the slot values
for that fixture. Every case uses the same function, :func:`slots`: the one slot dict
of :mod:`.full`, in the shape README 15.0.2 and section 15.6 define. Design slots are
written down from what the fixture is known to be; derived slots follow from them by
the sections' rules; identity and free slots are read from the fixture when the case
runs (each section's module holds its readers), so no value taken from a fixture (a
time, a name, a path) is stored in the repository. :mod:`.design` derives the same
dict from a ``ParametricDocumentIR`` design by section 15.6.
``tests/test_sldprt_spec.py`` runs every case.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from solidseas.nativewrite.container import read_document

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"


@dataclass(frozen=True)
class Fixture:
    name: str
    members: dict[str, bytes]

    def __getitem__(self, member: str) -> bytes:
        return self.members[member]


@cache
def fixture(name: str) -> Fixture:
    """A fixture part by file-name prefix (``o02`` or the whole name)."""
    parts = sorted(FIXTURES.glob("*.SLDPRT"))
    path = next(p for p in parts if p.name == name or p.name.startswith(name + "_"))
    doc = read_document(path.read_bytes())
    return Fixture(path.name, {m.name: (m.data or b"") for m in doc.members})


@dataclass(frozen=True)
class Case:
    fixture: str  # file-name prefix, such as "o02"
    member: str  # the member the listing must give
    listing: str  # file name in docs/sldprt-spec/listings
    slots: Callable[[Fixture], dict]
    before: str | None = None  # a listing assembled first, whose archive this one continues

    @property
    def id(self) -> str:
        return f"{self.fixture}:{self.listing}"


def slots(fx: Fixture) -> dict:
    """The one slot dict of fixture ``fx`` (:func:`.full.full_slots`)."""
    from .full import full_slots

    return full_slots(fx.name[:3])


def all_cases() -> list[Case]:
    out: list[Case] = []
    for info in pkgutil.iter_modules(__path__):
        mod = importlib.import_module(f"{__name__}.{info.name}")
        out.extend(getattr(mod, "CASES", ()))
    return out
