"""Express drawings (``docs/DRAWINGS.md``, "Drawing modes"): a part's key sizes with no
questions asked.

An Express drawing is made from what is already known. :func:`express_options` gives
its options: the ``express`` mode on the simplified detail level, the views the part
needs and its isometric, an automatic sheet and scale, and the unit the part states
(or the one SolidSeas guessed for a part that states none). :func:`express_fields`
gives the title fields the person would otherwise type: who drew it, the first person
of Drawing Settings' People list, and nothing else, so the part's own properties fill
the part number, description and material and the finish is NONE where the part
names none (``plan.notes.title_fields``).

What the planner draws for it (``plan.express_keeps`` and ``plan.express_graphs``):
the overall length, width and height; each hole and hole pattern by size, with its
count (such as 4X); a pattern's pitches, pitch circle and clocking angle; and each hole
located from the datum edges. No datums or GD&T, no chamfers, fillets, bosses, slots
or steps, and no notes but the model-governs note (and a printed part's process note,
which its general tolerances are). The checks treat what Express leaves out on purpose
as information (``checks.EXPRESS_INFORMATION``). An assembly's Express drawing is its
usual one: the overall size, the views and the parts list with balloons.
"""

from __future__ import annotations

from .settings import DrawingSettings
from .types import DrawingOptions

MODES = ("express", "guided", "expert")  # as the viewer offers them


def express_options(
    *,
    units: str = "part",
    configuration: str | None = None,
    quality: str = "normal",
    bodies: tuple[str, ...] | None = None,
) -> DrawingOptions:
    """The options of an Express drawing: the express mode on the simplified level,
    everything else left to SolidSeas (the views, front, sheet and scale chosen as for
    any drawing). ``units`` is ``part``, ``in`` or ``mm``."""
    return DrawingOptions(
        mode="express",
        detail="simplified",
        units=units,
        configuration=configuration,
        quality=quality,
        bodies=bodies,
    )


def express_fields(settings: DrawingSettings) -> dict[str, str]:
    """The title fields an Express drawing sends: ``drawn_by``, the first person of the
    People list when there is one. The rest come from the part."""
    people = [p["name"] for p in settings.people.people if str(p.get("name", "")).strip()]
    return {"drawn_by": people[0]} if people else {}


__all__ = ["MODES", "express_fields", "express_options"]
