"""Which view each dimension goes in (``docs/DRAWINGS.md`` 10.7).

True shape with visible witnesses first; then the view already holding the
feature's other dimensions; then the less crowded view; then the front. Callouts
go in the circular view, where the hole is seen end on and open. Nothing attaches
to a hidden run: a view qualifies only when the witnesses are visible lines (or a
centre seen open). The view is an attribute of the dimension, so moving it to
another view keeps its identity.
"""

from __future__ import annotations

from .context import Context, dot
from .graph import witness_in
from .requirements import Need, Pos

HOLDS_BONUS = 0.3  # the view already holds the feature's other dimensions
CROWD_COST = 0.02  # a dimension already in the view


class Assigner:
    """Keeps count of what each view holds, so later choices follow 10.7's order."""

    def __init__(self, ctx: Context, view_ids: list[str]) -> None:
        self.ctx = ctx
        self.views = [v for v in view_ids if ctx.view(v)[0].kind != "isometric"]
        self.count = {v: 0 for v in self.views}
        self.features: dict[str, set[str]] = {v: set() for v in self.views}

    def _score(self, view: str, base: float, feats: tuple[str, ...]) -> tuple:
        holds = any(f in self.features[view] for f in feats)
        spec = self.ctx.view(view)[0]
        return (
            base - (HOLDS_BONUS if holds else 0.0) + CROWD_COST * self.count[view],
            0 if spec.kind == "base" else 1,
            self.views.index(view),
        )

    def take(self, view: str, feats: tuple[str, ...]) -> None:
        self.count[view] += 1
        self.features[view].update(feats)

    def linear(self, a: Pos, b: Pos, feats: tuple[str, ...]) -> tuple[str, str] | None:
        """The view (and sheet axis) for a dimension between two positions: both seen
        along the same sheet axis, cheapest first."""
        best = None
        for v in self.views:
            spec, geom = self.ctx.view(v)
            wa, wb = witness_in(self.ctx, spec, geom, a), witness_in(self.ctx, spec, geom, b)
            if wa is None or wb is None or wa.sheet_axis != wb.sheet_axis:
                continue
            key = self._score(v, wa.cost + wb.cost, feats)
            if best is None or key < best[0]:
                best = (key, v, wa.sheet_axis)
        if best is None:
            return None
        return best[1], best[2]

    def facing(self, need: Need, feats: tuple[str, ...], seen=()) -> str | None:
        """The view for a leader item: one that looks along its edge (a chamfer, an
        angled face) or sees its circle in true shape, from an open side when that
        is known."""
        best = None
        for v in self.views:
            spec, _geom = self.ctx.view(v)
            _r, _u, d = spec.frame()
            if need.edge_on is not None:
                ok = self.ctx.looks_along(spec, need.edge_on)
            elif need.facing is not None:
                ok = self.ctx.looks_along(spec, need.facing)
                if ok and seen:
                    ok = any(dot(s, d) > 0.5 for s in seen)
            else:
                ok = spec.kind == "base"
            if not ok:
                continue
            key = self._score(v, 0.0, feats)
            if best is None or key < best[0]:
                best = (key, v)
        return None if best is None else best[1]

    def side(self, need: Need, feats: tuple[str, ...]) -> str | None:
        """A view that sees a round feature side on: the fall-back for a diameter when
        no view sees it end on."""
        if need.facing is None:
            return None
        best = None
        for v in self.views:
            spec, _geom = self.ctx.view(v)
            _r, _u, d = spec.frame()
            if abs(dot(d, need.facing)) > 1e-6:
                continue
            key = self._score(v, 0.2, feats)
            if best is None or key < best[0]:
                best = (key, v)
        return None if best is None else best[1]


__all__ = ["Assigner"]
