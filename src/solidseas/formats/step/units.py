"""Units of a STEP file: each representation context's length and plane angle units and
its uncertainty (provisional).

ISO 10303-41 and -42: a ``GEOMETRIC_REPRESENTATION_CONTEXT`` is a complex instance
with ``GLOBAL_UNIT_ASSIGNED_CONTEXT`` (its units) and usually
``GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT`` (its distance accuracy). A unit is an
``SI_UNIT`` with an optional prefix (``( LENGTH_UNIT() NAMED_UNIT(*)
SI_UNIT(.MILLI.,.METRE.) )``) or a ``CONVERSION_BASED_UNIT`` whose factor is a
``MEASURE_WITH_UNIT`` of another unit (an inch is 25.4 millimetres). Every length
and position in a representation is in its context's length unit, and every
angle (a cone's semi-angle, a trimming parameter on a circle) in its plane angle
unit. A context with no length unit is read in millimetres (``assumed``), one
with no plane angle unit in radians.
"""

import math
from dataclasses import dataclass
from typing import Any

from .part21 import Enum, Part21, Record, Ref, Typed

SI_PREFIX = {
    "EXA": 1e18,
    "PETA": 1e15,
    "TERA": 1e12,
    "GIGA": 1e9,
    "MEGA": 1e6,
    "KILO": 1e3,
    "HECTO": 1e2,
    "DECA": 1e1,
    "DECI": 1e-1,
    "CENTI": 1e-2,
    "MILLI": 1e-3,
    "MICRO": 1e-6,
    "NANO": 1e-9,
    "PICO": 1e-12,
    "FEMTO": 1e-15,
    "ATTO": 1e-18,
}
# Length tokens of document units (solidseas.formats.base.UNIT_SCALE), metres per unit.
LENGTH_TOKENS = (("mm", 0.001), ("cm", 0.01), ("m", 1.0), ("in", 0.0254), ("ft", 0.3048), ("micron", 1e-6))
MAX_UNIT_DEPTH = 8


@dataclass(frozen=True)
class Context:
    """One representation context: metres per length unit, radians per plane angle unit,
    the uncertainty in metres (None when not stated), the length's token and whether
    the length unit was assumed."""

    length_m: float = 0.001
    angle_rad: float = 1.0
    uncertainty_m: float | None = None
    token: str | None = "mm"
    assumed: bool = True


ASSUMED = Context()


def length_token(scale_m: float | None) -> str | None:
    """The document unit token of ``scale_m`` metres per unit, or None."""
    if scale_m is None:
        return None
    for token, s in LENGTH_TOKENS:
        if abs(scale_m - s) <= 1e-9 * s:
            return token
    return None


def _number(v: Any) -> float | None:
    if isinstance(v, Typed):
        v = v.value
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = float(v)
    return v if math.isfinite(v) else None


class Units:
    """Unit and context resolution for one file, cached by instance id."""

    def __init__(self, p21: Part21) -> None:
        self.p21 = p21
        self._units: dict[int, tuple[str, float] | None] = {}
        self._contexts: dict[int, Context] = {}

    def unit(self, ref: Any, depth: int = 0) -> tuple[str, float] | None:
        """``(kind, factor)`` of a unit: ``length`` in metres, ``angle`` in radians, or
        another kind; None when it cannot be resolved."""
        rec = self.p21.get(ref)
        if rec is None or depth > MAX_UNIT_DEPTH:
            return None
        if rec.id in self._units:
            return self._units[rec.id]
        self._units[rec.id] = None  # a cycle reads as unresolved
        got = self._resolve(rec, depth)
        self._units[rec.id] = got
        return got

    def _resolve(self, rec: Record, depth: int) -> tuple[str, float] | None:
        kind = None
        if rec.has("LENGTH_UNIT"):
            kind = "length"
        elif rec.has("PLANE_ANGLE_UNIT"):
            kind = "angle"
        elif rec.has("SOLID_ANGLE_UNIT"):
            kind = "solid_angle"
        si = rec.part("SI_UNIT")
        if si is not None:
            prefix, name = (si[-2], si[-1]) if len(si) >= 2 else (None, si[-1] if si else None)
            factor = SI_PREFIX.get(str(prefix), 1.0) if isinstance(prefix, Enum) else 1.0
            if isinstance(name, Enum):
                if name == "METRE":
                    return ("length", factor)
                if name == "RADIAN":
                    return ("angle", factor)
                if name == "STERADIAN":
                    return ("solid_angle", factor)
            return (kind, factor) if kind else None
        conv = rec.part("CONVERSION_BASED_UNIT")
        if conv is not None and len(conv) >= 2:
            m = self.p21.get(conv[1])
            if m is None:
                return None
            got = self.measure(m, depth + 1)
            if got is None:
                return None
            k, value = got
            return (kind or k, value)
        return None

    def measure(self, rec: Record, depth: int = 0) -> tuple[str, float] | None:
        """``(kind, value in metres or radians)`` of a ``MEASURE_WITH_UNIT`` (or a
        subtype)."""
        params = None
        for t, p in zip(rec.types, rec.parts, strict=True):
            if t.endswith("MEASURE_WITH_UNIT") and len(p) >= 2:
                params = p
                break
        if params is None:
            return None
        value = _number(params[0])
        unit = self.unit(params[1], depth + 1)
        if value is None or unit is None:
            return None
        return unit[0], value * unit[1]

    def context(self, ref: Any) -> Context:
        """The :class:`Context` of a representation context instance."""
        if not isinstance(ref, Ref):
            return ASSUMED
        got = self._contexts.get(int(ref))
        if got is not None:
            return got
        rec = self.p21.get(ref)
        length = angle = None
        uncertainty = None
        if rec is not None:
            assigned = rec.part("GLOBAL_UNIT_ASSIGNED_CONTEXT")
            for u in assigned[0] if assigned and isinstance(assigned[0], list) else []:
                got_unit = self.unit(u)
                if got_unit is None:
                    continue
                if got_unit[0] == "length" and length is None:
                    length = got_unit[1]
                elif got_unit[0] == "angle" and angle is None:
                    angle = got_unit[1]
            unc = rec.part("GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT")
            for u in unc[0] if unc and isinstance(unc[0], list) else []:
                m = self.p21.get(u)
                if m is None:
                    continue
                got_m = self.measure(m)
                if got_m is not None and got_m[0] == "length" and got_m[1] > 0:
                    uncertainty = got_m[1] if uncertainty is None else min(uncertainty, got_m[1])
        ok_length = length is not None and length > 0
        ctx = Context(
            length_m=length if ok_length else 0.001,
            angle_rad=angle if angle is not None and angle > 0 else 1.0,
            uncertainty_m=uncertainty,
            token=length_token(length) if ok_length else "mm",
            assumed=not ok_length,
        )
        self._contexts[int(ref)] = ctx
        return ctx

    def of(self, rep: Record) -> Context:
        """The context of a representation (its third parameter)."""
        p = rep.params
        return self.context(p[2] if len(p) >= 3 else None)


__all__ = ["ASSUMED", "LENGTH_TOKENS", "SI_PREFIX", "Context", "Units", "length_token"]
