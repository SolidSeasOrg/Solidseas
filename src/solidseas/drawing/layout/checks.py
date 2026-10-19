"""Layout checks (``docs/DRAWINGS.md`` 11.6): text over text, items outside the
border or in a reserved area, leaders outside 15 to 75 degrees, characters the
font lacks, items that could not be placed clear, and cramped features. Each is
a :class:`LayoutCheck` naming the item it is about.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .index import Box, Index

LEADER_MIN, LEADER_MAX = 15.0, 75.0
FURNITURE = ("title", "tolerance", "projection", "revisions", "notes", "border", "stamp", "plot", "logo")


@dataclass(frozen=True)
class LayoutCheck:
    code: str
    message: str
    owner: str = ""
    severity: str = "warning"
    other: str = ""  # L.overlap: the item whose text the owner's text overlaps


def _furniture(owner: str) -> bool:
    return owner.split("-")[0] in FURNITURE or owner.startswith("n-")


def run(pen, frame, *, leaders, unplaced, cramped) -> list[LayoutCheck]:
    out: list[LayoutCheck] = []
    index = Index()
    texts = [(t, b, o) for t, b, o in pen.texts]
    for k, (_t, b, _o) in enumerate(texts):
        index.add("text", b, str(k))
    reported: set[tuple[int, int]] = set()
    for k, (t, b, o) in enumerate(texts):
        for _kind, _other, ok in index.near(b.grow(-0.2)):
            j = int(ok)
            if j <= k or (k, j) in reported:
                continue
            t2, b2, o2 = texts[j]
            if o2 == o or not b.hits(b2, -0.2):
                continue
            reported.add((k, j))
            out.append(LayoutCheck("L.overlap", f"{t!r} overlaps {t2!r}", o, other=o2))
    border = frame.border
    for t, b, o in texts:
        if not b.inside(border.grow(0.01)) and o not in ("stamp", "plot", "border"):
            out.append(LayoutCheck("L.outside", f"{t!r} lies outside the border", o))
        elif not _furniture(o) and any(b.hits(r) for r in (frame.title, frame.revision, frame.notes)):
            out.append(LayoutCheck("L.reserved", f"{t!r} lies in the title, revision or notes block", o))
    for owner, start, elbow in leaders:
        dx, dy = elbow[0] - start[0], elbow[1] - start[1]
        if math.hypot(dx, dy) < 1e-9:
            continue
        a = math.degrees(math.atan2(abs(dy), abs(dx)))
        if not LEADER_MIN - 1e-6 <= a <= LEADER_MAX + 1e-6:
            out.append(
                LayoutCheck("L.leader", f"a leader stands at {a:.0f} degrees, outside 15 to 75", owner)
            )
    for owner, words in unplaced:
        out.append(
            LayoutCheck(
                "L.placement", f"{words} could not be placed clear of the views and dimensions", owner
            )
        )
    for owner, words in cramped:
        out.append(LayoutCheck("L.cramped", words, owner))
    for ch in sorted(set(pen.replaced)):
        out.append(
            LayoutCheck(
                "L.characters",
                f"the character U+{ord(ch):04X} is not one the drawing's font has; it shows as ?",
                "",
                "error",
            )
        )
    return out


def outside(box: Box, area: Box) -> bool:
    return not box.inside(area)


__all__ = ["LayoutCheck", "outside", "run"]
