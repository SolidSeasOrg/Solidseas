"""Accounting: every face claimed by a feature, a position, or unclaimed with its
reason; coverage by feature count, face count and area (``docs/DRAWINGS.md`` 9,
10.10).

A planar face square to a frame axis that no feature claims is a position: its
offset is a node of the linear graph, located by the plan, so it is covered. The
rest is unclaimed: ``free_form`` (B-spline, swept, spun, offset and rolling-blend
faces), ``needs_auxiliary`` (features on angled faces and holes off the frame's
axes, stage 1), ``skipped`` (faces the tessellator left out, with no mesh) and
``unrecognised`` (anything else). Anything unclaimed makes a reduced-dimension
drawing with the model-governs note.
"""

from __future__ import annotations

from ..facegraph import BrepModel, Plane
from ..numbers import plain_sum
from ..types import Coverage, Feature, Frame, Hole, Unclaimed
from ._common import along

FREE_FORM = ("bspline", "swept", "spun", "offset", "blend", "other")


def account(
    model: BrepModel, frame: Frame, features: list[Feature], claimed: dict[int, str]
) -> tuple[tuple[Unclaimed, ...], Coverage, tuple[str, ...]]:
    """(unclaimed faces, coverage, warnings)."""
    auxiliary = {
        f for feat in features if isinstance(feat, Hole) and feat.needs_auxiliary for f in feat.faces
    }
    unclaimed: list[Unclaimed] = []
    for f in model.faces:
        if f.index in auxiliary:
            unclaimed.append(Unclaimed(f.index, f.area, "needs_auxiliary"))
            continue
        if f.index in claimed:
            continue
        if isinstance(f.surface, Plane) and along(f.surface.normal, frame.directions) is not None:
            claimed[f.index] = "position"
            continue
        reason = "free_form" if f.kind in FREE_FORM else "unrecognised"
        unclaimed.append(Unclaimed(f.index, f.area, reason))
    for _body, _face, _surface, _reason in model.skipped:
        unclaimed.append(Unclaimed(-1, 0.0, "skipped"))
    total_area = plain_sum(f.area for f in model.faces)
    lost_area = plain_sum(u.area for u in unclaimed)
    faces = len(model.faces) + len(model.skipped)
    features_aux = sum(1 for feat in features if isinstance(feat, Hole) and feat.needs_auxiliary)
    coverage = Coverage(
        features=len(features),
        features_unclaimed=features_aux,
        faces=faces,
        faces_claimed=faces - len(unclaimed),
        area=total_area,
        area_claimed=total_area - lost_area,
    )
    warnings = []
    counts: dict[str, int] = {}
    for u in unclaimed:
        counts[u.reason] = counts.get(u.reason, 0) + 1
    words = {
        "free_form": "free-form",
        "needs_auxiliary": "need an auxiliary view, which comes in release 1.1, and",
        "skipped": "were left out by the tessellator and",
        "unrecognised": "are not recognised as a feature and",
    }
    for reason, n in sorted(counts.items()):
        if reason == "free_form":
            warnings.append(f"{n} free-form face{'s are' if n != 1 else ' is'} defined by the model")
        else:
            warnings.append(f"{n} face{'s' if n != 1 else ''} {words[reason]} defined by the model")
    return tuple(unclaimed), coverage, tuple(warnings)


__all__ = ["FREE_FORM", "account"]
