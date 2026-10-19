"""The angular graph (``docs/DRAWINGS.md`` 10.3), stage 1: one for each circular
or arc pattern. A circle's members are joined by the equal spacing the callout
states (``EQ SP`` implied by ``nX`` on a pitch circle), so they are one node; an
arc's by its step, stated once with the count of spaces (``4X 30°``). The origin is
the datum plane through the centre. A first member on a principal axis (0, 90, 180
or 270 degrees) is joined by the drawing's centre lines; any other first member
needs its angle. The same complete-and-acyclic test as the linear graph: one angle
at most for the first member, and one step.
"""

from __future__ import annotations

import math

from ..types import GraphResult, Pattern, PlannedDimension, requirement_key
from .context import Context

ON_AXIS = 1e-6  # radians


def needs_angle(p: Pattern) -> bool:
    return abs(math.remainder(p.first_angle, math.pi / 2)) > ON_AXIS


def check(ctx: Context, dims: list[PlannedDimension]) -> list[GraphResult]:
    """One verdict per circular or arc pattern."""
    out = []
    for k, p in ctx.features.of_type(Pattern):
        if p.kind not in ("circular", "arc"):
            continue
        fid = ctx.ids[k]

        def shown(key):
            return [d.id for d in dims if d.state == "shown" and d.kind == "angle" and key in d.serves]

        key = requirement_key("angle", [fid])
        drawn = shown(key)
        missing = [] if (not needs_angle(p)) or drawn else [key]
        loops = [tuple(drawn)] if len(drawn) > 1 or (drawn and not needs_angle(p)) else []
        if p.kind == "arc":
            step_key = requirement_key("step", [fid])
            steps = shown(step_key)
            if not steps:
                missing.append(step_key)
            if len(steps) > 1:
                loops.append(tuple(steps))
        out.append(GraphResult(f"angular/{fid}", not missing, bool(loops), tuple(missing), tuple(loops)))
    return out


__all__ = ["check", "needs_angle"]
