"""Arrangement schemes (``docs/DRAWINGS.md`` 10.4).

**Baseline** (the default): every node joined to the origin where one view sees
both, else by the cheapest drawable path; a tree. **Ordinate**: the same tree drawn
as ordinate dimensions from a 0 at the origin. A view and axis switch to ordinate
when the Settings' default is ordinate, when the drawing's options say so for that
view and axis (``v-1/x``), or when baseline would need more than the Settings'
number of tracks on one side; layout asks again when a band would be deeper than
the Settings' share of the view (:func:`too_deep`).
"""

from __future__ import annotations

from .context import Context

MIN_DEEP = 3  # a band too deep switches to ordinate only with this many locations or more


def forced(ctx: Context) -> dict[str, str]:
    return dict(ctx.options.arrangement)


def arrangement(ctx: Context, view_id: str, axis: str, count: int, deep: frozenset[str] = frozenset()) -> str:
    """``baseline`` or ``ordinate`` for the locations along ``axis`` in a view, given
    how many there are and the view/axis pairs layout found too deep."""
    key = f"{view_id}/{axis}"
    chosen = forced(ctx).get(key)
    if chosen is not None:
        return chosen
    dim = ctx.dimensioning
    if dim.get("scheme") == "ordinate":
        return "ordinate"
    if count > int(dim.get("ordinate_tracks", 6)) or (key in deep and count >= MIN_DEEP):
        return "ordinate"
    return "baseline"


def too_deep(ctx: Context, band_depth_mm: float, view_size_mm: float) -> bool:
    """Whether a band of baseline dimensions is deeper than the Settings' share of the
    view it stands beside (10.4)."""
    share = float(ctx.dimensioning.get("ordinate_share", 0.25))
    return view_size_mm > 0 and band_depth_mm > share * view_size_mm


__all__ = ["arrangement", "forced", "too_deep"]
