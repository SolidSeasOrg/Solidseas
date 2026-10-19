"""KeyWords hints (``docs/DRAWINGS.md`` 9).

Many parts carry dimension values in their KeyWords field (1,463 of 3,081
measured). They rank alternatives, matched by value only: a distance equal to an
extrusion depth, a radius equal to a fillet's value. They never supply a value.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import TypeVar

T = TypeVar("T")
UNIT_SCALE = {"mm": 1000.0, "in": 1.0 / 0.0254}


def matches(value_m: float, hints: Iterable[float], unit: str, tol: float = 1e-6) -> bool:
    """Whether a value in metres equals a hint written in ``unit``."""
    scale = UNIT_SCALE.get(unit)
    if scale is None:
        return False
    v = value_m * scale
    return any(abs(v - h) <= max(tol * scale, 1e-9) for h in hints)


def rank(
    candidates: Sequence[T], hints: Iterable[float], unit: str, value_of: Callable[[T], float]
) -> list[T]:
    """``candidates`` with those whose value matches a hint first, order kept
    otherwise (a stable sort)."""
    hs = tuple(hints)
    return sorted(candidates, key=lambda c: 0 if matches(value_of(c), hs, unit) else 1)


__all__ = ["matches", "rank"]
