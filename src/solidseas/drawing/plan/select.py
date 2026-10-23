"""Which way the front looks and which views the drawing keeps (``docs/DRAWINGS.md``
8.2, 8.3).

:func:`choose_front` scores the six directions and four turns: features seen in
true shape and open (holes, bosses, slots and pockets that face the viewer), the
planar area seen in true shape, features that would be hidden (their open side
away), the longest extent across the sheet, and for a printed part its build plate
at the bottom. Ties go in a fixed order. The choice comes with its reason in
words for the wizard.

:func:`choose_views` is greedy coverage over the views drawn: the front first,
then the projected view that lets most of the remaining requirements be drawn, until
no view adds any; the isometric stays when Settings ask for it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..numbers import plain_sum
from ..types import STANDARD_VIEWS as _STANDARD
from ..types import Boss, Hole, Pocket, Slot
from .context import Context, dot

# The front's direction and up for each choice, as solidseas.drawing.views.view_frames
# has them: a quarter turn turns the sheet's up about the front's direction.
DIRECTIONS = {
    "+z": ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    "-z": ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    "+y": ((0.0, 1.0, 0.0), (0.0, 0.0, -1.0)),
    "-y": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    "+x": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
    "-x": ((-1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
}
ORDER = ("+z", "-z", "+y", "-y", "+x", "-x")


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def frame_of(front: str, turn: int):
    """(right, up, direction) of the front view for a choice."""
    d, up = DIRECTIONS[front]
    for _ in range(turn % 4):
        up = _cross(d, up)
    return _cross(up, d), up, d


@dataclass(frozen=True)
class FrontChoice:
    front: str
    turn: int
    score: float
    reason: str


def _facing(ctx: Context):
    """(direction a feature is seen open from, weight, word) for each round or recessed
    feature: holes from their entry (and both ways when through), bosses from their
    free end, pockets and blind slots from their open side, through slots both ways."""
    out = []
    model = ctx.model
    for f in ctx.features.features:
        if isinstance(f, Hole):
            d = f.axis.direction
            out.append(((-d[0], -d[1], -d[2]), 1.0, "holes"))
            if f.through:
                out.append((d, 0.6, "holes"))
        elif isinstance(f, Boss):
            out.append((f.axis.direction, 1.0, "bosses"))
        elif isinstance(f, Pocket) and 0 <= f.floor < len(model.faces):
            out.append((model.faces[f.floor].surface.normal, 0.5, "pockets"))
        elif isinstance(f, Slot):
            by_axis: dict[str, list] = {}
            for face in f.faces:
                n = getattr(model.faces[face].surface, "normal", None)
                ax = ctx.axis_of(n) if n is not None else None
                if ax is not None:
                    by_axis.setdefault(ax, []).append(n)
            floors = [ns[0] for ns in by_axis.values() if len(ns) == 1]
            if floors:
                out.append((floors[0], 0.5, "slots"))
            else:
                along = ctx.axis_of(f.direction)
                depth = [a for a in "xyz" if a != along and a not in by_axis]
                if depth:
                    v = ctx.direction(depth[0])
                    out.append((v, 0.5, "slots"))
                    out.append(((-v[0], -v[1], -v[2]), 0.5, "slots"))
    return out


def profile_choices(ctx: Context) -> list[tuple[str, int]] | None:
    """For a turned part's drawing, the fronts and turns that show its profile (10.6):
    looking square to the axis, the axis across the sheet and the larger end on the
    left; None for any other drawing."""
    t = ctx.features.turned
    if ctx.process != "turned" or t is None:
        return None
    out = []
    for front in ORDER:
        for turn in range(4):
            right, _up, d = frame_of(front, turn)
            if abs(dot(d, t.axis.direction)) <= 1e-9 and dot(right, t.axis.direction) > 1.0 - 1e-9:
                out.append((front, turn))
    return out or None


def choose_front(ctx: Context) -> FrontChoice:
    """The front direction and turn with the best score (8.2); for a turned part, the
    best of those that show its profile (:func:`profile_choices`)."""
    model = ctx.model
    facing = _facing(ctx)
    planar_area = {}
    for face in model.faces:
        n = getattr(face.surface, "normal", None)
        if n is not None:
            planar_area[face.index] = (n, face.area)
    total_area = plain_sum(a for _n, a in planar_area.values()) or 1.0
    (lo, hi) = model.box
    extent = tuple(hi[k] - lo[k] for k in range(3))
    profile = profile_choices(ctx)
    choices = profile or [(front, turn) for front in ORDER for turn in range(4)]
    best: FrontChoice | None = None
    for front, turn in choices:
        right, up, d = frame_of(front, turn)
        seen = plain_sum(w for v, w, _word in facing if dot(v, d) > 0.999)
        hidden = plain_sum(w for v, w, _word in facing if dot(v, d) < -0.999)
        area = plain_sum(a for n, a in planar_area.values() if dot(n, d) > 0.999) / total_area
        across = abs(dot(right, extent))
        tall = abs(dot(up, extent))
        wide = 1.0 if across >= tall - 1e-9 else 0.0
        natural = 0.0
        if ctx.process == "printed" and dot(up, (0.0, 0.0, 1.0)) > 0.999:
            natural = 1.0  # the build plate at the bottom
        score = 2.0 * seen - 1.0 * hidden + 1.0 * area + 0.75 * wide + 1.5 * natural
        words = []
        if profile:
            words.append(
                "it shows the turned profile, the axis across the sheet and the larger end on the left"
            )
        kinds = sorted({word for v, _w, word in facing if dot(v, d) > 0.999})
        if kinds:
            words.append("it shows the " + " and ".join(kinds) + " in true shape")
        if area > 0.2:
            words.append("it sees the largest faces flat on")
        if wide and not profile:
            words.append("the longest side runs across the sheet")
        if natural:
            words.append("the build plate is at the bottom")
        reason = "; ".join(words) or "it is the first direction in the fixed order"
        choice = FrontChoice(front, turn, score, reason)
        if best is None or score > best.score + 1e-9:
            best = choice
    assert best is not None
    return best


def covers(ctx: Context, view_id: str, need, req) -> bool:
    """Whether a need can be drawn in a view: a linear size or location where both its
    positions are witnessed, a leader item where its circle or face is seen in true
    shape, an edge-on item where the view looks along its edge."""
    from .graph import witness_in

    spec, geom = ctx.view(view_id)
    if need.kind in ("linear", "ordinate") and need.a is not None and need.b is not None:
        a = req.position(need.axis, need.a)
        b = req.position(need.axis, need.b)
        wa, wb = witness_in(ctx, spec, geom, a), witness_in(ctx, spec, geom, b)
        return wa is not None and wb is not None and wa.sheet_axis == wb.sheet_axis
    if need.edge_on is not None:
        return ctx.looks_along(spec, need.edge_on)
    if need.facing is not None:
        return ctx.looks_along(spec, need.facing)
    return spec.kind == "base"


def choose_views(ctx: Context, req, locate_nodes) -> tuple[list[str], list]:
    """The views to keep (8.3), front first, and the needs no kept view can draw.
    ``locate_nodes`` lists (axis, positions) each location must reach."""
    from .graph import witness_in

    ortho = [s.id for s, _g in ctx.orthographic()]
    if not ortho:
        return [], list(req.needs)
    base = next((s.id for s, _g in ctx.views if s.kind == "base"), ortho[0])
    items: list[tuple[str, object]] = [("need", n) for n in req.needs]
    for axis, pids in locate_nodes:
        items.append(("loc", (axis, pids)))

    def can(view_id: str, item) -> bool:
        kind, obj = item
        if kind == "need":
            return covers(ctx, view_id, obj, req)
        axis, pids = obj
        spec, geom = ctx.view(view_id)
        return any(witness_in(ctx, spec, geom, req.position(axis, p)) is not None for p in pids)

    kept = [base]
    left = [it for it in items if not can(base, it)]
    candidates = [v for v in ortho if v != base]
    while left and candidates:
        gains = [(sum(1 for it in left if can(v, it)), -k, v) for k, v in enumerate(candidates)]
        gain, _k, v = max(gains)
        if gain == 0:
            break
        kept.append(v)
        candidates.remove(v)
        left = [it for it in left if not can(v, it)]
    iso = [s.id for s, _g in ctx.views if s.kind == "isometric"]
    order = {s.id: k for k, (s, _g) in enumerate(ctx.views)}
    kept.sort(key=lambda v: order[v])
    return kept + iso, [obj for kind, obj in left if kind == "need"]


def standard_view_name(direction) -> str | None:
    """A model-axes direction's standard name, for reports."""
    for name, (d, _up) in _STANDARD.items():
        if abs(dot(d, direction) - 1.0) < 1e-9:
            return name
    return None


__all__ = [
    "DIRECTIONS",
    "FrontChoice",
    "choose_front",
    "choose_views",
    "covers",
    "frame_of",
    "profile_choices",
]
