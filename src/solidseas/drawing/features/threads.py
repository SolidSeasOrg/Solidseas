"""Thread candidates (``docs/DRAWINGS.md`` 9, 10.9, 22 rule 7).

Geometry alone cannot prove a hole is threaded, and SOLIDWORKS keeps Hole Wizard
and cosmetic thread sizes in a stream SolidSeas has not decoded, so the files
almost never say. A hole's diameter is matched against the Unified and metric tap
drill tables, the clearance (ISO 273) table and the major diameters; the matches
are candidates the user confirms or not, and nothing becomes a thread note until
then.
"""

from __future__ import annotations

from ..standards import THREADS, clearance_for, threads_for_drill
from ..types import Hole

MAJOR_TOL = 1e-5  # metres


def candidates(diameter: float) -> tuple[str, ...]:
    """Every reading of a hole of ``diameter`` metres: tapped (by tap drill), clear
    for a thread (ISO 273), or at a thread's major diameter."""
    names = [f"tapped {t.internal()}" for t in threads_for_drill(diameter)]
    names += [f"clearance for {t.designation}" for t in clearance_for(diameter)]
    names += [
        f"major diameter of {t.designation}" for t in THREADS if abs(t.major / 1000.0 - diameter) <= MAJOR_TOL
    ]
    return tuple(names)


def tap_drill_matches(hole: Hole) -> tuple[str, ...]:
    """The thread designations a simple hole's diameter is the tap drill of."""
    if hole.kind != "simple":
        return ()
    return tuple(t.designation for t in threads_for_drill(hole.diameter))


__all__ = ["MAJOR_TOL", "candidates", "tap_drill_matches"]
