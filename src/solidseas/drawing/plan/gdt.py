"""Datums and feature control frames (``docs/DRAWINGS.md`` 10.5).

Under the datum scheme, datum feature symbols A, B and C go on the datum faces,
each hole, slot and boss carries one position frame (Ø and the Settings value for
its role, at MMC by default, to A, B and C; a pattern one frame for the group),
locations from the datums are basic, and one general note gives every surface not
otherwise controlled a profile of a surface to A, B and C. Under plus/minus the
datums are drawn only when a model-governs note needs to name them.

Frame values are kept in metres, like every other value, and shown in the
drawing's unit by :func:`frame_item`.
"""

from __future__ import annotations

from .. import numbers
from ..display import FrameItem
from ..types import FrameCell
from .context import Context


def letters(ctx: Context) -> tuple[str, ...]:
    """The datum letters the frame has, in order."""
    return tuple(d.letter for d in ctx.features.frame.datums)


def _g(ctx: Context, name: str):
    return getattr(ctx.settings.gdt, f"{name}_{'in' if ctx.unit == 'in' else 'mm'}")


def position(ctx: Context, *, tapped: bool = False) -> FrameCell | None:
    """A hole's, slot's or boss's position frame, or None outside the datum scheme."""
    if ctx.scheme != "datum" or not letters(ctx):
        return None
    value = _g(ctx, "position")["tapped" if tapped else "clearance"]
    modifier = ctx.settings.gdt.position_modifier
    return FrameCell(
        "position",
        numbers.from_unit(value, ctx.unit),
        diameter=True,
        modifier=None if modifier == "none" else modifier,
        datums=letters(ctx),
    )


def axis_letter(ctx: Context) -> str | None:
    """The letter of the datum on a cylinder (a turned part's datum axis), or None."""
    from ..facegraph import Cylinder

    faces = ctx.model.faces
    for d in ctx.features.frame.datums:
        if 0 <= d.face < len(faces) and isinstance(faces[d.face].surface, Cylinder):
            return d.letter
    return None


def runout(ctx: Context) -> FrameCell | None:
    """A turned diameter's circular runout frame to the datum axis, with the Settings
    value (10.5), or None outside the datum scheme or without a datum axis."""
    letter = axis_letter(ctx)
    if ctx.scheme != "datum" or letter is None:
        return None
    return FrameCell("circular_runout", numbers.from_unit(_g(ctx, "runout"), ctx.unit), datums=(letter,))


def profile(ctx: Context, *, undimensioned: bool = False) -> FrameCell | None:
    """The general profile frame, or the model-governs note's frame for undimensioned
    surfaces (its own Settings value when one is set)."""
    if not letters(ctx):
        return None
    value = _g(ctx, "profile")
    if undimensioned and _g(ctx, "undimensioned") is not None:
        value = _g(ctx, "undimensioned")
    return FrameCell("profile_surface", numbers.from_unit(value, ctx.unit), datums=letters(ctx))


def zone_text(ctx: Context, value_m: float) -> str:
    """A frame's zone value as the sheet shows it: the places it needs, at least three
    in inches and one in millimetres."""
    v = numbers.in_unit(value_m, ctx.unit)
    least = 3 if ctx.unit == "in" else 1
    p = max(least, numbers.places_needed(v, 4))
    return numbers.number(v, p, ctx.unit)


def frame_item(ctx: Context, cell: FrameCell) -> FrameItem:
    """The display list's frame for a planned one."""
    return FrameItem(
        cell.characteristic,
        zone_text(ctx, cell.value),
        cell.diameter,
        cell.modifier or "",
        tuple(cell.datums),
    )


def draws_datums(ctx: Context, needs_model_note: bool) -> bool:
    """Whether datum feature symbols are drawn: always under the datum scheme; under
    plus/minus only when the model-governs note must reference them (10.5)."""
    return bool(letters(ctx)) and (ctx.scheme == "datum" or needs_model_note)


__all__ = [
    "axis_letter",
    "draws_datums",
    "frame_item",
    "letters",
    "position",
    "profile",
    "runout",
    "zone_text",
]
