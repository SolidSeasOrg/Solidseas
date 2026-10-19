"""Feature recognition: ``recognise(model, frame_hint=None) -> FeatureSet``
(``docs/DRAWINGS.md`` 9), from the face graph and edge samples alone.

The recognisers run in a fixed order, each claiming the faces it explains so the
next does not take them again: the frame and datums, face grooves, holes and
bosses, patterns of the holes, slots, pockets and their depths, widths, steps,
blends, chamfers and angled faces, and last the accounting that turns the rest
into positions or unclaimed faces with their reasons. The features come out in a
fixed order too, which is the order the drawing gives their ids in: holes first
(so a pattern's members are their indices), then patterns, bosses, grooves,
slots, pockets, widths, steps, blends, chamfers and angled faces, each by
position.
"""

from __future__ import annotations

import time

from ..facegraph import BrepModel
from ..limits import DEFAULT_LIMITS, DrawingLimits
from ..types import FeatureSet, Frame
from ._common import Rays
from .accounting import account
from .blends import recognise_blends
from .chamfers import recognise_chamfers
from .frame import make_frame
from .grooves import recognise_grooves
from .holes import recognise_holes
from .inclined import recognise_angled
from .patterns import recognise_patterns
from .pockets import recognise_pockets, recognise_slots, recognise_steps
from .widths import recognise_widths


def recognise(
    model: BrepModel,
    frame_hint: Frame | None = None,
    *,
    limits: DrawingLimits = DEFAULT_LIMITS,
) -> FeatureSet:
    """The features of ``model``. ``frame_hint`` is a drawing's own frame (its datums
    follow their matched faces once a drawing exists, 13.4). Raises ``SldLimitError``
    past ``limits.seconds_features``."""
    start = time.perf_counter()

    def check(stage: str) -> None:
        if time.perf_counter() - start > limits.seconds_features:
            raise limits.exceeded(
                "seconds_features", f"recognising the part's features took too long ({stage})"
            )

    frame = make_frame(model, frame_hint)
    rays = Rays(model)
    claimed: dict[int, str] = {}
    grooves = recognise_grooves(model, frame, claimed)
    holes, bosses = recognise_holes(model, frame, rays, claimed)
    check("holes")
    patterns = recognise_patterns(holes, frame, model.diagonal, 0, tuple(b.axis for b in bosses))
    slots, slot_depths = recognise_slots(model, frame, claimed)
    pockets, pocket_depths = recognise_pockets(model, frame, claimed)
    check("pockets")
    widths = recognise_widths(model, frame, rays, claimed)
    check("widths")
    steps = recognise_steps(model, frame, claimed)
    blends = recognise_blends(model, frame, claimed)
    chamfers = recognise_chamfers(model, frame, claimed)
    angled = recognise_angled(model, frame, claimed)
    features = [
        *holes,
        *patterns,
        *bosses,
        *grooves,
        *slots,
        *pockets,
        *widths,
        *steps,
        *blends,
        *chamfers,
        *angled,
    ]
    if len(features) > limits.requirements:
        raise limits.exceeded("requirements", "the part has more features than a drawing takes")
    depths = []
    for depth in (*slot_depths, *pocket_depths):
        owner = next((i for i, f in enumerate(features) if depth.floor in f.faces), -1)
        depths.append(type(depth)(depth.floor, depth.open_face, depth.axis, depth.value, owner))
    unclaimed, coverage, warnings = account(model, frame, features, claimed)
    check("accounting")
    return FeatureSet(
        tuple(features), frame, tuple(depths), unclaimed, coverage, (*model.warnings, *warnings)
    )


__all__ = ["recognise"]
