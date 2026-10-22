"""Why layout placed an item where it is not clear: the drawing corpus sweep's measure
(``docs/drawings/layout.md``, "Measuring the conflicts").

With ``measure`` on, :func:`~.place.layout` gives each layout check of an item placed with
a conflict (``L.placement``) or of text over text (``L.overlap``) its ``facts``: numbers
and fixed words on how layout came to it, kept in memory only and never written. The
corpus sweep counts them (``tests/drawing_corpus_child.py``); they hold no text of the
drawing, no name and no file.

- ``step``, the step of layout that placed the item (:data:`STEPS`), a band's with the
  side of its view (``band.above``);
- for an item placed with no clear place: ``cost``, how far its place is from clear, as
  :func:`~.place.severity` counts it; ``breaks``, the rules that place breaks
  (:data:`RULES`), each with what it runs into, counted by kind (:data:`OBSTACLES`);
  ``room_mm``, the room on each side of its view past its bands, to the drawing area's
  edge or what stands there; and by item, the places a leader item looked at
  (``looked``, from ``anchors`` points, its text block ``text_mm``) or the spots a datum
  symbol or a frame tried and what stopped each (``spots``, by :data:`SPOT_REASONS`),
  with a datum symbol's ``reach_mm`` against the ``free_mm`` past its face, the ``views``
  that show its face, and whether the arrangement kept the symbols their room
  (``room_kept``);
- for text over text: both items' steps (``steps``), the ``overlap_mm`` across and up,
  and how they stand in their bands (``relation``, :data:`RELATIONS`).
"""

from __future__ import annotations

from collections import Counter

from .index import CENTRE, DIMLINE, EXTLINE, HARD, VIEW, Box

SIDES = ("below", "above", "left", "right")
# the steps of layout, in the order it places (docs/drawings/layout.md, Placement)
STEPS = (
    "band",
    "ordinate",
    "band_frame",
    "datum",
    "pattern_angle",
    "leader",
    "leader_frame",
    "balloon",
    "note",
    "furniture",
    "view_label",
    "build_arrow",
    "other",
)
# what a leader item's place may break, worst first, as severity counts them: its text over
# other text; over a view; over a dimension line; a line through its text; its leader
# through text; its leader across a dimension line or another leader
RULES = (
    "text_over_text",
    "text_over_view",
    "text_over_line",
    "line_through_text",
    "leader_through_text",
    "leader_across_line",
)
# what stopped a spot a datum symbol or a frame tried
SPOT_REASONS = (
    "off_sheet",
    "extension_through_text",
    "over_text",
    "over_view",
    "over_line",
    "over_extension_line",
    "over_leader",
    "over_centre_line",
)
# what a place runs into: the step that placed it, or one of these
OBSTACLES = ("own_view", "other_view", "centre_line", "reserved")
# how two texts that overlap stand: in one track of one band, in two tracks of one band, in
# two bands of one view, in two views, or not both in bands
RELATIONS = ("same_track", "same_band", "same_view", "other_view", "not_bands")
FURNITURE = ("title", "tolerance", "projection", "revisions", "border", "stamp", "plot", "logo", "parts")


class Steps:
    """The step of layout that placed each item, by its owner, as layout places them, and
    where a band's dimensions stand (side, track, whether its text is outside)."""

    def __init__(self) -> None:
        self.step: dict[str, str] = {}
        self.band: dict[str, tuple[str, str, int, bool]] = {}  # owner: (view, side, track, outside)

    def add(self, owner: str, step: str) -> None:
        self.step[owner] = step

    def add_band(self, owner: str, view: str, side: str, track: int, outside: bool, ordinate: bool) -> None:
        self.step[owner] = f"{'ordinate' if ordinate else 'band'}.{side}"
        self.band[owner] = (view, side, track, outside)

    def of(self, owner: str) -> str:
        """The step that placed ``owner``'s item, or what the owner says it is."""
        got = self.step.get(owner)
        if got is not None:
            return got
        if owner == "reserved":
            return "reserved"
        if owner.endswith("-label"):
            return "view_label"
        if owner == "notes" or owner.startswith("n-"):
            return "note"
        if owner == "build":
            return "build_arrow"
        if owner.split("-")[0] in FURNITURE:
            return "furniture"
        return "other"

    def obstacle(self, kind: str, owner: str, view: str) -> str:
        """What a stored item of index ``kind`` is, seen from an item in ``view``."""
        if kind == VIEW:
            return "own_view" if owner == view else "other_view"
        if kind == CENTRE:
            return "centre_line"
        return self.of(owner)

    def relation(self, a: str, b: str) -> str:
        """How the items ``a`` and ``b`` stand in their bands (:data:`RELATIONS`)."""
        pa, pb = self.band.get(a), self.band.get(b)
        if pa is None or pb is None:
            return "not_bands"
        if pa[0] != pb[0]:
            return "other_view"
        if pa[1] != pb[1]:
            return "same_view"
        return "same_track" if pa[2] == pb[2] else "same_band"


def _count(steps: Steps, found, view: str) -> dict[str, int]:
    return dict(sorted(Counter(steps.obstacle(kind, owner, view) for kind, owner in found).items()))


def breaks(index, steps: Steps, box: Box, start, elbow, view: str) -> dict[str, dict[str, int]]:
    """The rules a leader item's place breaks (:data:`RULES`), each with what it runs into
    counted by kind: its text block ``box`` and its leader from ``start`` to ``elbow``, in
    ``view``, checked as :func:`~.place.severity` checks them."""
    out: dict[str, dict[str, int]] = {}
    over = index.owners_hit(box, (HARD, VIEW, DIMLINE), pad=0.8)
    found = {
        "text_over_text": [o for o in over if o[0] == HARD],
        "text_over_view": [o for o in over if o[0] == VIEW],
        "text_over_line": [o for o in over if o[0] == DIMLINE],
        "line_through_text": index.segment_owners(box.grow(0.8), (DIMLINE, CENTRE)),
    }
    crossed = index.owners_crossed(start, elbow, (DIMLINE, HARD))
    found["leader_through_text"] = [o for o in crossed if o[0] == HARD]
    found["leader_across_line"] = [o for o in crossed if o[0] == DIMLINE]
    for rule in RULES:
        if found[rule]:
            out[rule] = _count(steps, found[rule], view)
    return out


def box_breaks(index, steps: Steps, box: Box, view: str, pad: float) -> dict[str, dict[str, int]]:
    """What a symbol's or a frame's box runs into where it was put with no clear spot, by
    the same rules as a leader item's text (:func:`breaks`), extension lines too."""
    out: dict[str, dict[str, int]] = {}
    over = index.owners_hit(box, (HARD, VIEW, DIMLINE, EXTLINE), pad=pad)
    found = {
        "text_over_text": [o for o in over if o[0] == HARD],
        "text_over_view": [o for o in over if o[0] == VIEW],
        "text_over_line": [o for o in over if o[0] in (DIMLINE, EXTLINE)],
        "line_through_text": index.segment_owners(box.grow(pad), (DIMLINE, CENTRE)),
    }
    for rule in RULES[:4]:
        if found[rule]:
            out[rule] = _count(steps, found[rule], view)
    return out


_OVER = {HARD: "over_text", VIEW: "over_view", DIMLINE: "over_line", EXTLINE: "over_extension_line"}


def spot_reasons(
    index, box: Box, area: Box, *, kinds, pad: float, segments, grow: float, extension=None
) -> list[str]:
    """What stops a datum symbol's letter box or a frame at ``box`` (:data:`SPOT_REASONS`),
    tested as the placing code tests it: the stored boxes of ``kinds`` within ``pad``, the
    stored segments of ``segments`` through the box grown by ``grow``, the drawing
    ``area``, and for a datum symbol off its face's end the ``extension`` line it stands
    on. Every reason, where the placing code stops at the first."""
    out = []
    if not box.inside(area):
        out.append("off_sheet")
    if extension is not None and index.crosses(*extension, (HARD,)):
        out.append("extension_through_text")
    for kind in kinds:
        if index.hits(box, (kind,), pad=pad):
            out.append(_OVER[kind])
    for kind, _owner in index.segment_owners(box.grow(grow), segments):
        reason = "over_centre_line" if kind == CENTRE else "over_leader"
        if reason not in out:
            out.append(reason)
    return out


def room(slots, bands, frame, view: str, iso_drawn: bool) -> dict[str, int]:
    """The room on each side of ``view`` past its bands, whole millimetres: to the drawing
    area's edge, or to a reserved area or another view with its bands standing across
    that side, whichever is nearer."""
    s = slots[view]
    b = s.box

    def extent(v: str) -> Box:
        vb = slots[v].box
        got = bands.get(v, {})

        def d(side: str) -> float:
            return got[side].depth if side in got else 0.0

        return Box(vb.x0 - d("left"), vb.y0 - d("below"), vb.x1 + d("right"), vb.y1 + d("above"))

    own = extent(view)
    others = [
        extent(v)
        for v, o in slots.items()
        if v != view and not (o.spec.kind == "isometric" and not iso_drawn)
    ]
    others += list(frame.reserved)
    area = frame.area
    out = {}
    for side in SIDES:
        if side in ("below", "above"):
            across = [o for o in others if o.x1 > b.x0 and o.x0 < b.x1]
            if side == "above":
                limit = min([area.y1] + [o.y0 for o in across if o.y0 >= own.y1 - 1e-6])
                got = limit - own.y1
            else:
                limit = max([area.y0] + [o.y1 for o in across if o.y1 <= own.y0 + 1e-6])
                got = own.y0 - limit
        else:
            across = [o for o in others if o.y1 > b.y0 and o.y0 < b.y1]
            if side == "right":
                limit = min([area.x1] + [o.x0 for o in across if o.x0 >= own.x1 - 1e-6])
                got = limit - own.x1
            else:
                limit = max([area.x0] + [o.x1 for o in across if o.x1 <= own.x0 + 1e-6])
                got = own.x0 - limit
        out[side] = max(0, round(got))
    return out


def free_past(slots, frame, view: str, at: float, axis: str, sense: float, iso_drawn: bool) -> int:
    """How far past the line at ``at`` (a sheet coordinate along ``axis``, ``x`` or ``y``)
    in direction ``sense`` the drawing area reaches before its edge, a reserved area or
    another view stands in the way: the room a datum symbol has past its face, whole
    millimetres."""
    area = frame.area
    b = slots[view].box
    blocks = [
        o.box for v, o in slots.items() if v != view and not (o.spec.kind == "isometric" and not iso_drawn)
    ]
    blocks += list(frame.reserved)
    if axis == "y":
        across = [o for o in blocks if o.x1 > b.x0 and o.x0 < b.x1]
        if sense > 0:
            limit = min([area.y1] + [o.y0 for o in across if o.y0 >= at - 1e-6])
            return max(0, round(limit - at))
        limit = max([area.y0] + [o.y1 for o in across if o.y1 <= at + 1e-6])
        return max(0, round(at - limit))
    across = [o for o in blocks if o.y1 > b.y0 and o.y0 < b.y1]
    if sense > 0:
        limit = min([area.x1] + [o.x0 for o in across if o.x0 >= at - 1e-6])
        return max(0, round(limit - at))
    limit = max([area.x0] + [o.x1 for o in across if o.x1 <= at + 1e-6])
    return max(0, round(at - limit))


def overlap(a: Box, b: Box) -> tuple[float, float]:
    """How far two boxes overlap across and up, millimetres to a tenth."""
    return (
        round(max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0)), 1),
        round(max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0)), 1),
    )


__all__ = [
    "OBSTACLES",
    "RELATIONS",
    "RULES",
    "SPOT_REASONS",
    "STEPS",
    "Steps",
    "box_breaks",
    "breaks",
    "free_past",
    "overlap",
    "room",
    "spot_reasons",
]
