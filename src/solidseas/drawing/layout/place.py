"""Layout: from a plan to a laid-out sheet (``docs/DRAWINGS.md`` 11).

:func:`layout` chooses the sheet and scale (:mod:`.sheet`), arranges the views
with their bands (:mod:`.arrange`), then places in 11.3's order (C22): obstacles
first (the views, the reserved areas), the linear and ordinate dimensions of each
band by track, the datum feature symbols bound to their faces, a circular
pattern's pitch circle and angle, then the callouts and other leader items, the
largest first, each by a cheapest-first candidate search against the index
(:mod:`.index`), and last the notes, the title block and the stamps. Nothing is
dropped silently: an item with no clear place is put at its best and reported.

The result is a :class:`~solidseas.drawing.display.Sheet` (geometry, annotations
and the painted layer) and the layout checks. Placement is deterministic: stable
sort keys and no randomness. An assembly's parts list too long for the sheet's
columns goes on to sheets after it (``docs/DRAWINGS.md`` 11.7), the sheet's
``continuation``: the title block, border, stamps and the rest of the list.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field, replace

from .. import display as D
from .. import standards
from ..limits import DEFAULT_LIMITS
from ..plan import Planned
from ..plan.gdt import frame_item
from ..plan.notes import upper
from ..plan.values import dim_text
from ..types import Hole, Pattern
from . import arrange as A
from . import checks as C
from . import dimension as DM
from . import notes as N
from . import partslist as PL
from . import patterns, sheet, stamps, titleblock
from .glyphs import Pen, text_width
from .index import DIMLINE, EXTLINE, HARD, Box, Index

VIEW = "view"
CENTRE = "centre"  # centre lines, marks and pitch circles: no text or symbol may cover them
# leader angles from the horizontal, 15 to 75 degrees in each quadrant, 45 first
_STEPS = (45.0, 37.5, 52.5, 30.0, 60.0, 22.5, 67.5, 15.0, 75.0)
ANGLES = tuple(
    dict.fromkeys(round(x % 360.0, 3) for a in _STEPS for x in (a, 180.0 - a, 360.0 - a, 180.0 + a))
)
LENGTHS = (6.0, 10.0, 15.0, 21.0, 28.0, 38.0, 50.0, 65.0, 85.0, 110.0, 140.0)
# tried only for an item with no clear place among those: the angles and lengths between
_FINE = tuple(15.0 + 2.5 * k for k in range(25) if (15.0 + 2.5 * k) not in _STEPS)
FINE_ANGLES = tuple(
    dict.fromkeys(round(x % 360.0, 3) for a in _FINE for x in (a, 180.0 - a, 360.0 - a, 180.0 + a))
)
FINE_LENGTHS = tuple((a + b) / 2 for a, b in zip(LENGTHS, LENGTHS[1:], strict=False))
ALL_LENGTHS = tuple(sorted(LENGTHS + FINE_LENGTHS))
ANGLE_RANK = {a: k for k, a in enumerate(ANGLES + FINE_ANGLES)}
ANGLE_RANK_MAIN = frozenset(ANGLES)
# where a datum feature symbol's foot may stand, as shares of its face's line from one end:
# along it, the middle first, then off its ends on an extension line of the face (10.5)
DATUM_SPOTS = (0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8, 0.1, 0.9, 0.05, 0.95, -0.12, 1.12, -0.25, 1.25, -0.4, 1.4)
DATUM_OFF = 5.0  # mm past the view: a datum symbol's foot on its face's line carried off the view
LEADER_ANCHORS = 8  # pattern members a callout's leader may start from, the outermost first
TINY_ARC = 1.5  # mm on paper: a radius leader may start anywhere on a circle this small, not only on its arc
FRAME_ROOM = 2.3  # text heights a feature control frame under a leader's lines takes
LEADER_RETRIES = 2  # passes of the leader items again, those with no clear place first
# the closer look and the further passes for leader items with no clear place stop once they
# have looked at this many places on a sheet, so that a sheet past help costs little more (a
# count, not a time, so that the layout stays the same on any machine)
LEADER_EXTRA = 30000


@dataclass
class LayoutResult:
    sheet: D.Sheet
    checks: list
    deep: frozenset[str]
    frame: sheet.SheetFrame
    seconds: float
    scale: tuple[int, int]
    # by dimension id, the view and sheet axis of a datum symbol the layout drew in
    # another view the plan offered, its own having no clear place (``orchestrate`` records it)
    views: dict[str, tuple[str, str]] = field(default_factory=dict)


def _score(costs: list[float]) -> tuple[int, float]:
    """How a pass of leader items went: how many found no clear place, then how badly."""
    return sum(1 for c in costs if c > 0.0), sum(costs)


def _natural(text: str) -> tuple:
    """``text`` ordered with its numbers as numbers: item 2 before item 10."""
    return tuple((0, int(t), "") if t.isdigit() else (1, 0, t) for t in re.findall(r"\d+|\D+", text))


# ---------------------------------------------------------------------- attach points


def _along(ctx, slot: A.Slot, axis: str, value: float) -> float | None:
    sa = ctx.sheet_axis(slot.spec, axis)
    if sa is None:
        return None
    return sa[1] * value


def attach(ctx, slot: A.Slot, pos, sheet_axis: str):
    """Where a position's extension line comes from in a view (view metres): its
    coordinate along ``sheet_axis``, the extent across it of the visible line or
    centre mark it starts at, and whether it is a centre (no gap, the mark's
    overshoot instead)."""
    along = _along(ctx, slot, pos.axis, pos.value)
    if along is None:
        along = 0.0
    if pos.kind == "face":
        w = slot.geom.witness_at(sheet_axis, along, max(ctx.tol, 1e-7))
        if w is not None:
            return along, w.low, w.high, False
    pts = pos.points or ((pos.point,) if pos.point is not None else ())
    if pts:
        across = []
        for q in pts:
            x, y = slot.spec.project(q)
            across.append(y if sheet_axis == "x" else x)
        return along, min(across) - pos.radius, max(across) + pos.radius, True
    vb = slot.vbox
    lo, hi = (vb.y0, vb.y1) if sheet_axis == "x" else (vb.x0, vb.x1)
    return along, lo, hi, False


def _moved(pd):
    """The user's placement of a dimension record, when the user moved it."""
    placement = getattr(pd, "placement", None)
    return placement if placement is not None and placement.moved else None


def _points(item) -> list[tuple[float, float]]:
    """A centre line or circle on the sheet as points along it: an arc in steps of at
    most 10 degrees (a spline's control points are no line on the sheet, so none)."""
    if isinstance(item, D.Segment):
        return [item.p0, item.p1]
    if isinstance(item, D.Arc):
        sweep = item.sweep()
        n = max(2, math.ceil(sweep / 10.0))
        return [item.point(item.start_deg + sweep * k / n) for k in range(n + 1)]
    if isinstance(item, D.EllipseArc):
        return [item.point(item.t0 + (item.t1 - item.t0) * k / 36) for k in range(37)]
    if isinstance(item, D.Polyline):
        pts = list(item.points)
        return pts + pts[:1] if item.closed else pts
    return []


def severity(index: Index, box: Box, start, elbow, cap: float = math.inf) -> float:
    """How far a leader item's place, its text block ``box`` and its leader from
    ``start`` to ``elbow``, is from clear (0): where no place is, the least bad is
    taken. Its text over other text is worst (4), as neither reads; its text over a
    view or a dimension line, a line through its text, or its leader through text
    cost 2 each; its leader across a dimension line or another leader least (1).
    Exact up to ``cap``; past it (a place worse than the best found) it stops looking."""
    out = 0.0
    if index.hits(box, (HARD, VIEW, DIMLINE), pad=0.8):
        out += 4.0 if index.hits(box, (HARD,), pad=0.8) else 2.0
        if out > cap:
            return out
    if index.segment_hits(box.grow(0.8), (DIMLINE, CENTRE)):
        out += 2.0
        if out > cap:
            return out
    if index.crosses(start, elbow, (DIMLINE, HARD)):
        out += 2.0 if index.crosses(start, elbow, (HARD,)) else 1.0
    return out


def _inside_length(a, b, box: Box) -> float:
    """How much of the segment ``a`` to ``b`` lies inside ``box``, sampled."""
    n = 16
    inside = 0
    for k in range(n):
        t = (k + 0.5) / n
        x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        if box.x0 < x < box.x1 and box.y0 < y < box.y1:
            inside += 1
    return math.dist(a, b) * inside / n


# ---------------------------------------------------------------------- the engine


class _Run:
    def __init__(
        self,
        planned: Planned,
        options,
        settings,
        *,
        logo,
        logo_sha,
        source,
        fields,
        revisions,
        status,
        signed,
        sheets=DEFAULT_LIMITS.sheets,
    ):
        self.sheets = sheets  # the most sheets the drawing may take
        self.planned = planned
        self.plan = planned.plan
        self.detail = planned.detail
        self.ctx = planned.detail.ctx
        self.options = options
        self.settings = settings
        self.logo = logo
        self.logo_sha = logo_sha
        self.source = source
        self.fields = fields
        self.revisions = revisions
        self.status = status
        self.signed = signed
        self.h = A.text_height(self.ctx.unit)
        self.dims_by_view: dict[str, list] = {}
        for pd in self.plan.dimensions:
            # a user dimension needing attention stays off the sheet until fixed (13.5)
            if pd.state == "shown" and "needs_attention" not in getattr(pd, "flags", ()):
                self.dims_by_view.setdefault(pd.view, []).append(pd)

    # ------------------------------------------------------------------ bands

    def band_inputs(self, slot: A.Slot):
        out = []
        for pd in self.dims_by_view.get(slot.spec.id, []):
            if pd.kind not in ("linear", "ordinate"):
                continue
            pa_pb = self.detail.positions.get(pd.id)
            sa = self.detail.sheet_axis.get(pd.id)
            if not pa_pb or len(pa_pb) < 2 or sa is None:
                continue
            a, b = pa_pb
            fa = attach(self.ctx, slot, a, sa)
            fb = attach(self.ctx, slot, b, sa)
            across = ((fa[1] + fa[2]) / 2 + (fb[1] + fb[2]) / 2) / 2
            out.append((pd, fa[0], fb[0], sa, across))
        return out

    def slots_at(self, factor: float) -> dict[str, A.Slot]:
        out = {}
        for spec in self.plan.views:
            geom = self.ctx.view(spec.id)[1]
            out[spec.id] = A.Slot(spec, geom, A.view_box(geom), factor * 1000.0)
        return out

    def smallest_span(self) -> float:
        spans = []
        for pd in self.plan.dimensions:
            if pd.state == "shown" and pd.kind in ("linear", "ordinate") and pd.value > 0:
                spans.append(pd.value)
        return min(spans) if spans else 0.0

    # ------------------------------------------------------------------ sheet and scale

    def choose(self):
        tried = []
        first_fit = None
        smallest = self.smallest_span()
        for name in sheet.sheet_order(self.options, self.settings):
            probe = sheet.frame(name, self.settings)
            parts = self.parts_shape(probe)
            nh = (
                N.height(self.plan.notes, probe.title.width - 2.0, self.h, self._frame_w)
                if self.plan.notes
                else 0.0
            )
            f = sheet.frame(
                name,
                self.settings,
                note_height=nh,
                revisions=len(self.revisions),
                parts_height=parts.height,
                parts_width=parts.total_width,
            )
            for sc in sheet.scale_order(self.options, self.settings):
                factor = standards.scale_factor(sc)
                slots = self.slots_at(factor)
                datums = self.datum_rooms(slots)
                bands = {
                    v: A.bands(self.ctx, s, self.band_inputs(s), datums.get(v)) for v, s in slots.items()
                }
                rooms = {v: A.leader_room(self.ctx, self.dims_by_view.get(v, [])) for v in slots}
                pads = self.balloon_pads()
                got = A.arrange(self.ctx, f, slots, bands, rooms, datums, pads=pads)
                if got is None and datums:  # room for the datum symbols is not worth a smaller scale
                    bands = {v: A.bands(self.ctx, s, self.band_inputs(s)) for v, s in slots.items()}
                    got = A.arrange(self.ctx, f, slots, bands, rooms, pads=pads)
                tried.append((name, sc))
                if got is None:
                    continue
                if (
                    factor >= 1.0
                    or smallest * factor * 1000.0 >= sheet.MIN_SPAN_MM
                    or self.options.scale != "auto"
                ):
                    return f, sc, got, None
                if first_fit is None:
                    first_fit = (f, sc, got)
                break  # a reduced scale cramps the smallest span: try the next sheet at full size
        if first_fit is not None:
            f, sc, got = first_fit
            paper = smallest * standards.scale_factor(sc) * 1000
            words = (
                f"the smallest dimensioned span is {paper:.1f} mm on paper at "
                f"{standards.scale_text(sc)}: add a detail view"
            )
            return f, sc, got, words
        # nothing fits: the largest sheet at the smallest scale, reported
        name = sheet.sheet_order(self.options, self.settings)[-1]
        parts = self.parts_shape(sheet.frame(name, self.settings))
        f = sheet.frame(name, self.settings, parts_height=parts.height, parts_width=parts.total_width)
        sc = sheet.scale_order(self.options, self.settings)[-1]
        slots = self.slots_at(standards.scale_factor(sc))
        bands = {v: A.bands(self.ctx, s, self.band_inputs(s)) for v, s in slots.items()}
        if self.options.sheet != "auto" or self.settings.sheets.size != "auto":
            words = (
                f"the views and their dimensions do not fit the {name} sheet at any scale: "
                "choose a larger sheet"
            )
        else:
            words = "the views do not fit the largest sheet at the smallest scale"
        return f, sc, A.Arrangement(slots, bands, Box(0, 0, 0, 0)), words

    def parts_rows(self):
        """The parts list's headings, narrow columns and rows as painted."""
        capitals = self.settings.standard.upper_case_notes
        rows = PL.cells(self.plan.bom, capitals=capitals)
        if self.plan.bom_columns:  # the BOM editor's columns
            heads = tuple(c.upper() for c in self.plan.bom_columns) if capitals else self.plan.bom_columns
            return heads, self.plan.bom_narrow, rows
        return PL.COLUMNS, None, rows

    def parts_shape(self, f) -> PL.Shape:
        """How the parts list stands on sheet frame ``f`` (:func:`.partslist.shape`)."""
        if not self.plan.bom:
            return PL.Shape()
        heads, narrow, rows = self.parts_rows()
        room = f.revision.y0 - f.title.y1
        more = self.sheets > 1
        return PL.shape(rows, self.h, f.title.width, room, f.border.width, heads, narrow, more=more)

    def continuation_shapes(self, name: str) -> list[PL.Shape]:
        """The parts list on the sheets after the first of size ``name``: each sheet's
        shape, for the lines the first does not hold (none when it holds them all)."""
        first = self.parts_shape(sheet.frame(name, self.settings))
        left = len(self.plan.bom) - first.lines
        out: list[PL.Shape] = []
        if left <= 0:
            return out
        f = sheet.continuation_frame(name, self.settings)
        room = sheet.continuation_room(f)
        while left > 0:
            last = len(out) + 2 >= self.sheets
            got = PL.continued(left, self.h, first.width, room, f.border.width, last=last)
            out.append(got)
            left -= got.lines
        return out

    def _frame_w(self, cell) -> float:
        return A.frame_width(self.ctx, cell)

    def balloon_pads(self) -> dict[str, float]:
        """Room round each view that carries balloons: a balloon and the shortest
        leader."""
        pads: dict[str, float] = {}
        for b in self.plan.balloons:
            room = 2 * PL.radius(b.item, self.h) + PL.REACH[1] + PL.CLEAR
            for view in (b.view, *(o[0] for o in b.others)):
                pads[view] = max(pads.get(view, 0.0), room)
        return pads

    # ------------------------------------------------------------------ the whole sheet

    def run(self) -> LayoutResult:
        t0 = time.perf_counter()
        f, sc, arr, cramped_words = self.choose()
        self.frame = f
        self.arr = arr
        self.pen = Pen()
        self.index = Index()
        self.annotations: list = []
        self.geometry: list = []
        self.layers: list[str] = []
        self.leaders: list = []
        self.unplaced: list = []
        self.cramped: list = []
        self.joined: set = set()
        self.views: dict[str, tuple[str, str]] = {}  # datum symbols drawn in another view than planned
        self.looked = 0  # places a leader item's text was tried at
        self.extra = 0  # of those, the ones beyond the first search of each leader item
        self.counting = False
        if cramped_words:
            self.cramped.append(("", cramped_words))
        placements = []
        for v, s in arr.slots.items():
            if s.spec.kind == "isometric" and arr.iso is None:
                continue
            k = s.k / 1000.0
            label = s.spec.name if s.spec.kind in ("section", "detail") else ""
            placements.append(D.ViewPlacement(v, s.origin, k, label))
            # the part's outline: the centre lines and circles past it are lines of their own
            self.index.add(VIEW, s.outline, v)
        for r in f.reserved:
            self.index.add(HARD, r, "reserved")
        more = self.continuation_shapes(f.name) if self.plan.bom else []
        self.sheet_count = 1 + len(more)
        self.paint_views()
        self.paint_bands()
        self.paint_datums()
        self.paint_leaders()
        self.paint_balloons()
        self.paint_furniture(sc)
        deep = self.deep_bands()
        painted = patterns.strokes(self.geometry, self.layers) + self.pen.items
        result_sheet = D.Sheet(
            f.name,
            f.width,
            f.height,
            sc,
            tuple(placements),
            tuple(self.geometry),
            tuple(self.annotations),
            tuple(painted),
            self.paint_continuation(sc, more),
        )
        found = C.run(self.pen, f, leaders=self.leaders, unplaced=self.unplaced, cramped=self.cramped)
        return LayoutResult(result_sheet, found, deep, f, time.perf_counter() - t0, sc, dict(self.views))

    # ------------------------------------------------------------------ views

    def paint_views(self) -> None:
        for v, s in self.arr.slots.items():
            if s.spec.kind == "isometric" and self.arr.iso is None:
                continue
            placement = D.ViewPlacement(v, s.origin, s.k / 1000.0, "")
            for run in s.geom.runs:
                prim = run.primitive
                try:
                    prim = replace(prim, style=run.style)
                except TypeError:
                    pass
                item = D.place(prim, placement)
                self.geometry.append(item)
                if run.source.kind == "hatch":
                    self.layers.append("hatch")
                elif run.style == "centre":
                    self.layers.append("centre")
                    pts = _points(item)
                    for a, b in zip(pts, pts[1:], strict=False):
                        self.index.add_segment(CENTRE, a, b, v)
                else:
                    self.layers.append(D.STYLE_LAYER.get(run.style, "visible"))
            centre = standards.LINES["centre"]
            for c, r in s.geom.centre_marks:
                cx, cy = s.sheet(c)
                reach = r * s.k + DM.OVERSHOOT
                for a, b in (((cx - reach, cy), (cx + reach, cy)), ((cx, cy - reach), (cx, cy + reach))):
                    dash = patterns.fit(centre.dash, reach * 2)
                    self.pen.line(a, b, width=centre.width, dash=dash, layer="centre", owner=v)
                    self.index.add_segment(CENTRE, a, b, v)
                self.annotations.append(D.CentreMark((cx, cy), r * s.k, v, DM.OVERSHOOT))
            for a, b in s.geom.centre_lines:
                pa, pb = s.sheet(a), s.sheet(b)
                d = math.dist(pa, pb)
                if d <= 1e-9:
                    continue
                ux, uy = (pb[0] - pa[0]) / d, (pb[1] - pa[1]) / d
                p0 = (pa[0] - ux * DM.OVERSHOOT, pa[1] - uy * DM.OVERSHOOT)
                p1 = (pb[0] + ux * DM.OVERSHOOT, pb[1] + uy * DM.OVERSHOOT)
                self.pen.line(
                    p0,
                    p1,
                    width=centre.width,
                    dash=patterns.fit(centre.dash, d + 2 * DM.OVERSHOOT),
                    layer="centre",
                    owner=v,
                )
                self.index.add_segment(CENTRE, p0, p1, v)
                self.annotations.append(D.CentreLine(p0, p1, v))
            if s.spec.kind in ("section", "detail") and s.spec.letter:
                word = "SECTION" if s.spec.kind == "section" else "DETAIL"
                text = (
                    f"{word} {s.spec.letter}-{s.spec.letter}"
                    if s.spec.kind == "section"
                    else f"{word} {s.spec.letter}"
                )
                b = s.box
                lh = standards.TEXT[self.ctx.unit].view_label
                tb = self.pen.text(
                    (b.x0 + b.x1) / 2,
                    b.y0 - self.arr.bands[v]["below"].depth - lh * 1.6,
                    lh,
                    text,
                    bold=True,
                    anchor="centre",
                    layer="notes",
                    owner=f"{v}-label",
                )
                self.index.add(HARD, tb, f"{v}-label")
                self.annotations.append(D.ViewLabel(v, (tb.x0, tb.y0), text, s.spec.letter))

    # ------------------------------------------------------------------ balloons

    def paint_balloons(self) -> None:
        """An assembly's item balloons, in item order (:mod:`.partslist`); one the user
        moved where they put it (the drawing's ``balloons`` option)."""
        h = self.h
        moved = {item: (dx, dy) for item, dx, dy in self.options.balloons}
        placed: dict[str, list] = {}  # the balloons drawn in each view, for stacking
        for b in sorted(self.plan.balloons, key=lambda b: (_natural(b.item), b.view)):
            owner = f"balloon-{b.item}"
            spot = None
            for view, _inst, at in ((b.view, b.instance, b.at), *b.others):
                s = self.arr.slots.get(view)
                if s is not None and not (s.spec.kind == "isometric" and self.arr.iso is None):
                    spot = (view, s, at)
                    break
            if spot is None:
                self.unplaced.append(
                    (owner, f"the balloon of item {b.item}, whose views are not on the sheet")
                )
                continue
            view, s, at = spot
            anchor = s.sheet(at)
            r = PL.radius(b.item, h)
            if b.item in moved:  # where the user put it, its leader following
                centre, end, clear = PL.moved_balloon(
                    self.index, self.frame.area, anchor, moved[b.item], r, owner, (HARD, VIEW, DIMLINE)
                )
                if not clear:
                    self.unplaced.append((owner, f"the balloon of item {b.item}, where it was moved,"))
            else:
                centre, end, clear = PL.place_balloon(
                    self.index, self.frame.area, s.box, anchor, r, ANGLES, owner, (HARD, VIEW, DIMLINE)
                )
                if not clear:  # stacked on a balloon of a part beside it, when one has room
                    stacked = None
                    for partner in placed.get(view, ()):
                        stacked = PL.stacked_balloon(
                            self.index, self.frame.area, partner, anchor, r, owner, (HARD, VIEW, DIMLINE)
                        )
                        if stacked is not None:
                            break
                    if stacked is not None:
                        centre, end = stacked, None
                    else:
                        self.unplaced.append((owner, f"the balloon of item {b.item}"))
            made = PL.paint_balloon(self.pen, b.item, centre, end, anchor, r, h, b.view, owner)
            self.annotations.append(made)
            placed.setdefault(view, []).append(made)
            self.index.add(HARD, Box(centre[0] - r, centre[1] - r, centre[0] + r, centre[1] + r), owner)
            if end is not None:
                self.index.add_segment(DIMLINE, anchor, end, owner)
                self.leaders.append((owner, anchor, end))

    # ------------------------------------------------------------------ bands

    def paint_bands(self) -> None:
        h = self.h
        gap = standards.DIMENSIONS.extension_gap
        for v, s in self.arr.slots.items():
            if s.spec.kind == "isometric":
                continue
            bands = self.arr.bands[v]
            vb = s.box
            for side, band in bands.items():
                horizontal = side in ("below", "above")
                outward = -1.0 if side in ("below", "left") else 1.0
                edge = {"below": vb.y0, "above": vb.y1, "left": vb.x0, "right": vb.x1}[side]
                ordinates = [d for d in band.dims if d.pd.kind == "ordinate"]
                if ordinates:
                    self._ordinates(s, v, side, horizontal, outward, edge, ordinates, band)
                for bd in sorted(
                    (d for d in band.dims if d.pd.kind != "ordinate"), key=lambda d: (d.track, d.pd.id)
                ):
                    pd = bd.pd
                    a, b = self.detail.positions[pd.id]
                    sa = self.detail.sheet_axis[pd.id]
                    fa = attach(self.ctx, s, a, sa)
                    fb = attach(self.ctx, s, b, sa)
                    self._centre_line(s, a, sa)
                    self._centre_line(s, b, sa)
                    ends = []
                    for f_ in (fa, fb):
                        along, lo, hi, centre = f_
                        sheet_along = s.origin[0 if horizontal else 1] + s.k * along
                        lo_s = s.origin[1 if horizontal else 0] + s.k * lo
                        hi_s = s.origin[1 if horizontal else 0] + s.k * hi
                        start = lo_s if outward < 0 else hi_s
                        if centre:
                            start += outward * DM.OVERSHOOT
                        ends.append((sheet_along, start, 0.0 if centre else gap))
                    at = edge + outward * band.offsets[bd.track]
                    moved = _moved(pd)
                    if moved is not None:
                        at += outward * moved.across_mm
                    text = dim_text(self.ctx, pd)
                    # a text too wide for its span may stand past the near end instead of the far
                    # one, where that keeps clear of the track's next dimension on that side
                    reach = (bd.text_w if horizontal else h) + h + 2.0
                    near_free = bd.outside and not any(
                        o is not bd and o.track == bd.track and o.lo < bd.lo and o.hi + 1.5 > bd.lo - reach
                        for o in band.dims
                        if o.pd.kind != "ordinate"
                    )
                    ann = DM.linear(
                        self.pen,
                        self.index,
                        did=pd.id,
                        kind="linear",
                        horizontal=horizontal,
                        a=ends[0][0],
                        b=ends[1][0],
                        start_a=ends[0][1],
                        start_b=ends[1][1],
                        gap_a=ends[0][2],
                        gap_b=ends[1][2],
                        at=at,
                        outward=outward,
                        h=h,
                        text=text,
                        value=pd.value,
                        refs=pd.features,
                        tolerance=pd.tolerance,
                        places=pd.places,
                        view=v,
                        shift=moved.along_mm if moved is not None else 0.0,
                        clear=self._free if near_free else None,
                        framed=pd.frame is not None,
                    )
                    self.annotations.append(ann)
                    if pd.frame is not None:
                        self._linear_frame(pd, ann, text)

    def _free(self, box: Box) -> bool:
        """Whether a dimension's text may stand at ``box``: no text or view there."""
        return not self.index.hits(box, (HARD, VIEW), pad=0.5)

    def _linear_frame(self, pd, ann, text) -> None:
        """A linear dimension's frame where it is clear: under its text, over it, then
        to either side, then further out."""
        h = self.h
        fw = A.frame_width(self.ctx, pd.frame)
        fh = h + 2.0
        tx, ty = ann.text_at
        below = ty - h / 2 - len(text.suffix) * h * DM.LINE_PITCH
        tw = A.dim_width(self.ctx, pd)
        spots = [
            (tx - fw / 2, below - fh - 1.2),
            (tx - fw / 2, ty + h * 0.9),
            (tx + tw / 2 + 2.0, ty - fh / 2),
            (tx - tw / 2 - 2.0 - fw, ty - fh / 2),
        ]
        for step in range(1, 7):
            spots += [
                (tx - fw / 2, below - fh - 1.2 - step * (fh + 1.2)),
                (tx - fw / 2, ty + h * 0.9 + step * (fh + 1.2)),
                (tx + tw / 2 + 2.0 + step * 6.0, ty - fh / 2),
                (tx - tw / 2 - 2.0 - fw - step * 6.0, ty - fh / 2),
            ]
        x, y = spots[0]
        for sx, sy in spots:
            box = Box(sx, sy, sx + fw, sy + fh)
            if (
                box.inside(self.frame.area)
                and not self.index.hits(box, (HARD, VIEW, DIMLINE), pad=0.5)
                and not self.index.segment_hits(box, (DIMLINE, CENTRE))
            ):
                x, y = sx, sy
                break
        else:
            self.unplaced.append((f"{pd.id}-frame", f"the frame of {DM.value_line(text)}"))
        _box, fann = DM.frame(
            self.pen,
            self.index,
            x=x,
            y=y,
            h=h,
            item=frame_item(self.ctx, pd.frame),
            anchor="left",
            owner=f"{pd.id}-frame",
        )
        self.annotations.append(fann)

    def _centre_line(self, s, pos, sheet_axis) -> None:
        """A centre line through holes in line, seen end on, so one dimension locates
        them all (the drawing shows them aligned)."""
        if len(pos.points) < 2 or pos.along is None or not self.ctx.looks_along(s.spec, pos.along):
            return
        key = (s.spec.id, pos.axis, round(pos.value, 9))
        if key in self.joined:
            return
        self.joined.add(key)
        pts = [s.sheet(s.spec.project(q)) for q in pos.points]
        k = 1 if sheet_axis == "x" else 0
        lo = min(pts, key=lambda q: q[k])
        hi = max(pts, key=lambda q: q[k])
        reach = pos.radius * s.k + DM.OVERSHOOT
        if k == 1:
            a, b = (lo[0], lo[1] - reach), (hi[0], hi[1] + reach)
        else:
            a, b = (lo[0] - reach, lo[1]), (hi[0] + reach, hi[1])
        centre = standards.LINES["centre"]
        self.pen.line(
            a,
            b,
            width=centre.width,
            dash=patterns.fit(centre.dash, math.dist(a, b)),
            layer="centre",
            owner=s.spec.id,
        )
        self.index.add_segment(CENTRE, a, b, s.spec.id)
        self.annotations.append(D.CentreLine(a, b, s.spec.id))

    def _ordinates(self, s, v, side, horizontal, outward, edge, ordinates, band) -> None:
        h = self.h
        gap = standards.DIMENSIONS.extension_gap
        row = edge + outward * standards.DIMENSIONS.first_row
        groups: dict[float, list] = {}
        for bd in ordinates:
            a, _b = self.detail.positions[bd.pd.id]
            groups.setdefault(round(a.value, 9), []).append(bd)
        for _key, items in sorted(groups.items()):
            a = self.detail.positions[items[0].pd.id][0]
            sa = self.detail.sheet_axis[items[0].pd.id]
            fa = attach(self.ctx, s, a, sa)
            k = 0 if horizontal else 1
            o_along = s.origin[k] + s.k * fa[0]
            o_lo = s.origin[1 - k] + s.k * (fa[1] if outward < 0 else fa[2])
            entries = []
            for bd in items:
                pd = bd.pd
                b = self.detail.positions[pd.id][1]
                fb = attach(self.ctx, s, b, sa)
                self._centre_line(s, b, sa)
                along = s.origin[k] + s.k * fb[0]
                start = s.origin[1 - k] + s.k * (fb[1] if outward < 0 else fb[2])
                if fb[3]:
                    start += outward * DM.OVERSHOOT
                entries.append(
                    (
                        pd.id,
                        along,
                        start,
                        0.0 if fb[3] else gap,
                        dim_text(self.ctx, pd),
                        pd.value,
                        pd.features,
                        pd.tolerance,
                        pd.places,
                    )
                )
            anns = DM.ordinate_band(
                self.pen,
                self.index,
                horizontal=horizontal,
                origin=o_along,
                origin_start=o_lo,
                items=entries,
                row=row,
                outward=outward,
                h=h,
                view=v,
                zero_id=f"{items[0].pd.id}-0",
            )
            self.annotations += anns

    def deep_bands(self) -> frozenset[str]:
        """View and axis pairs whose band of baseline locations is deeper than the
        Settings' share of the view (10.4): the planner draws them as ordinates."""
        from ..plan.schemes import too_deep

        out = set()
        for v, s in self.arr.slots.items():
            for side, band in self.arr.bands.get(v, {}).items():
                locs = [d for d in band.dims if d.pd.role == "feature_location" and d.pd.kind == "linear"]
                if not locs:
                    continue
                size = s.box.height if side in ("below", "above") else s.box.width
                if too_deep(self.ctx, band.depth, size):
                    out.add(f"{v}/{locs[0].pd.axis}")
        return frozenset(out)

    # ------------------------------------------------------------------ datums

    def _datum_out(self, pd, s, sa: str, along: float) -> int:
        """Which way along sheet axis ``sa`` a datum feature symbol stands out from its
        face, -1 or +1: away from the material, as the face's outward normal shows in
        the view, so the symbol is read against its own face and not a face behind it;
        toward the nearer side of the view when the face cannot say."""
        letter = pd.suffix[0] if pd.suffix else ""
        face = next((d.face for d in self.ctx.features.frame.datums if d.letter == letter), None)
        shown = self.ctx.sheet_axis(s.spec, pd.axis) if pd.axis else None
        faces = self.ctx.model.faces
        if face is not None and 0 <= face < len(faces) and shown is not None and shown[0] == sa:
            normal = getattr(faces[face].surface, "normal", None)
            if normal is not None:
                d = self.ctx.direction(pd.axis)
                c = normal[0] * d[0] + normal[1] * d[1] + normal[2] * d[2]
                if abs(c) > 0.5:
                    return shown[1] * (1 if c > 0 else -1)
        lo, hi = (s.vbox.x0, s.vbox.x1) if sa == "x" else (s.vbox.y0, s.vbox.y1)
        return -1 if abs(along - lo) <= abs(along - hi) else 1

    def _datum_side(self, pd, s) -> tuple[str, float, str, float] | None:
        """Where a datum feature symbol stands on its view: the sheet axis its face
        runs across, its coordinate there (view metres), the side of the view it stands
        out toward (:meth:`_datum_out`) and how far past the view it reaches there,
        sheet millimetres (0 when it stays within the view). None when the view cannot
        show it."""
        pos = self.detail.positions[pd.id][0]
        sa = self.detail.sheet_axis[pd.id]
        along = _along(self.ctx, s, pos.axis, pos.value)
        if along is None:
            return None
        vb = s.vbox
        lo, hi = (vb.x0, vb.x1) if sa == "x" else (vb.y0, vb.y1)
        out = self._datum_out(pd, s, sa, along)
        names = ("left", "right") if sa == "x" else ("below", "above")
        inside = (along - lo) if out < 0 else (hi - along)  # view metres from the face to that side
        return sa, along, names[0 if out < 0 else 1], max(0.0, DM.datum_reach(self.h) - inside * s.k)

    def datum_rooms(self, slots) -> dict[str, dict[str, float]]:
        """By view, the sides datum feature symbols stand out on and how far past the
        view, for the arrangement to leave room for them and their bands to start
        beyond them."""
        out: dict[str, dict[str, float]] = {}
        for pd in self.plan.dimensions:
            if pd.kind != "datum_feature" or pd.state != "shown" or pd.view not in slots:
                continue
            got = self._datum_side(pd, slots[pd.view])
            if got is not None and got[3] > 0.0:
                sides = out.setdefault(pd.view, {})
                sides[got[2]] = max(sides.get(got[2], 0.0), got[3])
        return out

    def paint_datums(self) -> None:
        """Each datum feature symbol at the first clear spot in its view, then in each
        other view the plan offers where its face shows as a line, in the plan's order;
        one moved to another view is recorded in ``self.views`` so that the drawing names
        the view it is drawn in. With no clear spot anywhere it goes in the middle of its
        face in the first view that shows the face, and is reported."""
        for pd in self.plan.dimensions:
            if pd.kind != "datum_feature" or pd.state != "shown":
                continue
            tries = ((pd.view, self.detail.sheet_axis[pd.id]), *self.detail.other_views.get(pd.id, ()))
            first = None  # the first view that shows the face, for a symbol with no clear spot
            drawn = False  # whether any of its views is on the sheet
            for v, sa in tries:
                s = self.arr.slots.get(v)
                if s is None or (s.spec.kind == "isometric" and self.arr.iso is None):
                    continue
                drawn = True
                at = self._datum_face(pd, s, sa)
                if at is None:
                    continue
                if first is None:
                    first = (v, s, sa, at)
                if self._datum_at(pd, v, s, sa, at):
                    if v != pd.view:
                        self.views[pd.id] = (v, sa)
                    break
            else:
                if not drawn:
                    continue  # none of its views is on the sheet
                letter = pd.suffix[0]
                self.unplaced.append((f"datum-{letter}", f"datum {letter}"))
                if first is None:
                    continue
                v, s, sa, (x_or_y, lo, hi, outward) = first
                if v != pd.view:
                    self.views[pd.id] = (v, sa)
                t = (lo + hi) / 2
                foot = (x_or_y, t) if sa == "x" else (t, x_or_y)
                _box, ann = DM.datum_symbol(
                    self.pen, letter=letter, foot=foot, outward=outward, h=self.h, view=v
                )
                self.annotations.append(ann)

    def _datum_face(self, pd, s, sa: str):
        """Where a datum's face is a line in view ``s`` running across sheet axis ``sa``:
        its sheet coordinate along ``sa``, the ends of the line across it and the way the
        symbol stands out, or None where the view shows no line there."""
        pos = self.detail.positions[pd.id][0]
        along = _along(self.ctx, s, pos.axis, pos.value)
        w = s.geom.witness_at(sa, along, max(self.ctx.tol, 1e-7)) if along is not None else None
        if w is None:
            return None
        out = self._datum_out(pd, s, sa, along)
        if sa == "x":
            return (
                s.origin[0] + s.k * along,
                s.origin[1] + s.k * w.low,
                s.origin[1] + s.k * w.high,
                (float(out), 0.0),
            )
        return (
            s.origin[1] + s.k * along,
            s.origin[0] + s.k * w.low,
            s.origin[0] + s.k * w.high,
            (0.0, float(out)),
        )

    def _datum_at(self, pd, v: str, s, sa: str, at) -> bool:
        """Paint a datum's symbol at the first clear spot on its face's line in view
        ``v`` (``at`` from :meth:`_datum_face`); False, painting nothing, when none is."""
        h = self.h
        letter = pd.suffix[0]
        x_or_y, lo, hi, outward = at
        vb = s.box
        ends = (vb.y0, vb.y1, "below", "above") if sa == "x" else (vb.x0, vb.x1, "left", "right")
        span = hi - lo
        spots = [lo + frac * span for frac in DATUM_SPOTS]
        # then off the view altogether, on the face's line carried past it: between the
        # view and the first row of the band there, then past that band
        bands = self.arr.bands.get(v, {})
        for k, edge in ((-1.0, ends[0]), (1.0, ends[1])):
            band = bands.get(ends[2] if k < 0 else ends[3])
            for c in (DATUM_OFF, DATUM_OFF + 1.0, (band.depth if band is not None else 0.0) + DATUM_OFF):
                spots.append(edge + k * c)
        for t in spots:
            foot = (x_or_y, t) if sa == "x" else (t, x_or_y)
            trial = Pen()
            if not lo <= t <= hi:
                # off the face's end: on an extension line of the face (10.5)
                sense = -1.0 if t < lo else 1.0
                end = lo if t < lo else hi
                start = end + sense * standards.DIMENSIONS.extension_gap
                stop = t + sense * 3.0
                a, b = ((x_or_y, start), (x_or_y, stop)) if sa == "x" else ((start, x_or_y), (stop, x_or_y))
                if self.index.crosses(a, b, (HARD,)):
                    continue
                trial.line(a, b, owner=f"datum-{letter}")
            _box, ann = DM.datum_symbol(trial, letter=letter, foot=foot, outward=outward, h=h, view=v)
            letter_box = Box(*ann.at, ann.at[0] + h + 2.5, ann.at[1] + h + 2.5)
            if (
                self.index.hits(letter_box, (HARD, VIEW, DIMLINE, EXTLINE), pad=0.4)
                or self.index.segment_hits(letter_box.grow(0.4), (CENTRE,))
                or not letter_box.inside(self.frame.area)
            ):
                continue
            self.pen.items += trial.items
            self.pen.texts += trial.texts
            self.index.add(HARD, letter_box, f"datum-{letter}")
            self.annotations.append(ann)
            return True
        return False

    # ------------------------------------------------------------------ leader items

    def paint_leaders(self) -> None:
        items = [pd for pd in self.plan.dimensions if pd.state == "shown" and pd.kind in A.LEADER_KINDS]
        basics = [pd for pd in items if pd.role == "pattern" and pd.kind in ("diameter", "angle")]
        rest = [pd for pd in items if pd not in basics]
        for pd in basics:
            if pd.kind == "angle":
                self._pattern_angle(pd)
            else:
                self._leader(pd)

        def size(pd) -> float:
            t = dim_text(self.ctx, pd)
            return (1 + len(t.suffix) + (1.5 if pd.frame else 0)) * max(
                10.0, text_width(DM.value_line(t), self.h)
            )

        order = sorted(rest, key=lambda pd: (-size(pd), pd.id))
        mark = self._mark()
        looked = self.looked
        costs = [self._leader(pd) for pd in order]
        first = self.looked - looked - self.extra  # what a pass costs, without a closer look
        # As a drafter starts over with the hard ones: the items that found no clear place
        # first, the rest after them in their order, then each of them alone first. An
        # order is kept when fewer items are left without a clear place (or as many, less
        # badly). A few passes at most, and none that would look at more places than the
        # sheet's allowance has left.
        seen = {tuple(pd.id for pd in order)}
        for _ in range(LEADER_RETRIES):
            failed = [pd for pd, cost in zip(order, costs, strict=True) if cost > 0.0]
            if not failed or self.extra + first > LEADER_EXTRA:
                break
            clear = [pd for pd, cost in zip(order, costs, strict=True) if cost == 0.0]
            again = next(
                (
                    o
                    for o in [failed + clear] + [[f] + [pd for pd in order if pd is not f] for f in failed]
                    if tuple(pd.id for pd in o) not in seen
                ),
                None,
            )
            if again is None:
                break
            seen.add(tuple(pd.id for pd in again))
            kept = self._rewind(mark)
            self.counting = True
            tried = [self._leader(pd) for pd in again]
            self.counting = False
            if _score(tried) < _score(costs):
                order, costs = again, tried
            else:
                self._rewind(mark)
                self._replay(kept)

    def _placed(self) -> tuple[list, ...]:
        """The lists placing a leader item adds to, besides the index."""
        pen = self.pen
        return (pen.items, pen.texts, pen.replaced, self.annotations, self.leaders, self.unplaced)

    def _mark(self) -> tuple:
        """How much has been placed so far, for :meth:`_rewind` to go back to."""
        return (self.index.mark(), *(len(got) for got in self._placed()))

    def _rewind(self, mark: tuple) -> tuple:
        """Take back everything placed since ``mark``; returns it for :meth:`_replay`."""
        at, *ns = mark
        lists = self._placed()
        tails = []
        for got, n in zip(lists, ns, strict=True):
            tails.append(got[n:])
            del got[n:]
        return (self.index.rewind(at), tails)

    def _replay(self, kept: tuple) -> None:
        """Put back what :meth:`_rewind` took, exactly as it was."""
        (items, segments), tails = kept
        for kind, box, owner in items:
            self.index.add(kind, box, owner)
        for kind, a, b, owner in segments:
            self.index.add_segment(kind, a, b, owner)
        lists = self._placed()
        for got, tail in zip(lists, tails, strict=True):
            got += tail

    def _anchors(self, pd, s: A.Slot):
        """Where a leader item may start, as (point, radius, centre, span): on the circle
        of that radius about the point (sheet millimetres), measured from the centre, in
        the directions ``span`` allows (the middle and half width, degrees; None, any).
        Each member of a pattern's callout, or of equal features stated once (up to
        :data:`LEADER_ANCHORS`), the nearest free space first. A radius starts on an arc:
        radially from its centre, over the arc's own span (the circle past it may lie far
        off the part), or from the arc's middle."""
        need = self.detail.needs.get(pd.id)
        fs = self.ctx.features

        def at(q):
            return s.sheet(s.spec.project(q))

        if need is not None and need.facing is not None and not self.ctx.looks_along(s.spec, need.facing):
            r = 0.0
        else:
            r = pd.radius * s.k
        out = []  # (where it starts, for the order), (point, radius, centre, span)
        if pd.kind == "hole_callout" and need is not None and need.features:
            f = fs.features[need.features[0]]
            members = f.members if isinstance(f, Pattern) else (need.features[0],)
            for m in members:
                hole = fs.features[m]
                if isinstance(hole, Hole):
                    p = at(hole.axis.point)
                    out.append((p, (p, r, p, None)))
        elif need is not None and need.on_face:
            for q, c, half in need.on_face:
                qs, cs = at(q), at(c)
                if r > 0.0:
                    mid = math.degrees(math.atan2(qs[1] - cs[1], qs[0] - cs[0]))
                    # a tiny arc's whole circle stays by it: any direction will do
                    out.append((qs, (cs, r, cs, None if r <= TINY_ARC else (mid, half))))
                out.append((qs, (qs, 0.0, cs, None)))
        elif pd.anchor is not None:
            p = at(pd.anchor)
            out.append((p, (p, r, p, None)))
            if need is not None:  # a statement for equal features may point at any of them
                out += [(at(q), (at(q), r, at(q), None)) for q in need.anchors]
        if not out:
            b = s.box
            p = ((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2)
            out.append((p, (p, r, p, None)))
        cx, cy = s.box.centre()
        out.sort(
            key=lambda e: (
                -(abs(e[0][0] - cx) / max(s.box.width, 1e-6) + abs(e[0][1] - cy) / max(s.box.height, 1e-6)),
                e[0],
                -e[1][1],
            )
        )
        return [entry for _where, entry in out[:LEADER_ANCHORS]]

    def _block(self, pd) -> tuple[DM.DimText | None, list[str], object]:
        t = dim_text(self.ctx, pd)
        if pd.kind == "leader_note":
            return None, [t.value, *t.suffix] if t.value else list(t.suffix), None
        return t, list(t.suffix), (frame_item(self.ctx, pd.frame) if pd.frame is not None else None)

    def _leader(self, pd) -> float:
        """Place a leader item at its best and return how far that is from clear (0)."""
        s = self.arr.slots.get(pd.view)
        if s is None:
            return 0.0
        h = self.h
        first, lines, fitem = self._block(pd)
        if first is not None:
            w = max(
                [text_width(DM.value_line(first), h) + (h if first.boxed else 0.0)]
                + [text_width(x, h) for x in lines]
            )
        else:
            w = max(text_width(x, h) for x in lines) if lines else 10.0
        rows = (1 if first is not None else 0) + len(lines)
        fw = A.frame_width(self.ctx, pd.frame) if pd.frame is not None else 0.0
        w = max(w, fw)
        height = rows * h * DM.LINE_PITCH + (h * FRAME_ROOM if pd.frame is not None else 0.0)
        area = self.frame.area
        vb = s.box
        anchors = self._anchors(pd, s)

        def candidate(p, r, span, ang, length):
            """A leader at ``ang`` of ``length`` from the anchor: its start, elbow,
            side and text block, or None where it may not go."""
            if span is not None and abs((ang - span[0] + 180.0) % 360.0 - 180.0) > span[1]:
                return None  # a radius leaves its arc, not the circle past it
            self.looked += 1
            if self.counting:
                self.extra += 1
            a = math.radians(ang)
            start = (p[0] + r * math.cos(a), p[1] + r * math.sin(a))
            elbow = (start[0] + length * math.cos(a), start[1] + length * math.sin(a))
            right = math.cos(a) > 0
            if pd.side in ("left", "right") and right != (pd.side == "right"):
                return None  # the user flipped it to the other side
            x0 = elbow[0] + 4.0 if right else elbow[0] - 4.0 - w
            top = elbow[1] + h * 0.8
            return start, elbow, right, Box(x0, top - height, x0 + w, top)

        def soft_cost(start, elbow, box, length, ang) -> float:
            soft = 0.0
            if self.index.hits(box, (EXTLINE,), pad=0.3):
                soft += 1.0
            if self.index.crosses(start, elbow, (EXTLINE,)):
                soft += 0.5
            if self.index.crosses(start, elbow, (VIEW,), ignore=pd.view):
                soft += 1.0  # a leader through another view, often the isometric
            inside = _inside_length(start, elbow, vb)
            return 10.0 * soft + 0.3 * inside + 0.05 * length + 0.01 * ANGLE_RANK[ang]

        # its own view's outline, as the index holds it: a text block over it is not clear
        own = None if s.spec.kind == "isometric" and self.arr.iso is None else s.outline

        def search(best):
            for n, (p, r, c, span) in enumerate(anchors):
                if n >= 3 and best is not None and best[0][0] == 0.0:
                    break  # the further members only while none of the first three has a clear place
                for length in LENGTHS:
                    for ang in ANGLES:
                        got = candidate(p, r, span, ang, length)
                        if got is None or not got[3].inside(area):
                            continue
                        start, elbow, right, box = got
                        cap = best[0][0] if best is not None else math.inf
                        if cap < 2.0 and own is not None and own.hits(box, 0.8):
                            continue  # over its own view, which costs more than the best found
                        hard = severity(self.index, box, start, elbow, cap)
                        if hard > cap:
                            continue  # worse than the best found
                        cost = (hard, soft_cost(start, elbow, box, length, ang))
                        if best is None or cost < best[0]:
                            best = (cost, start, elbow, right, p, r, c)
                    if best is not None and best[0][0] == 0.0 and length > math.dist(best[1], best[2]) + 40.0:
                        break
            return best

        def clear_search(best):
            """Only a clear place, among the angles and lengths between those tried. A
            leader that crosses a line or text at one length crosses it at every longer
            one, so each direction is followed outward only until it does."""
            for p, r, c, span in anchors:
                for ang in ANGLES + FINE_ANGLES:
                    if self.extra >= LEADER_EXTRA:
                        return best
                    if candidate(p, r, span, ang, 0.0) is None:
                        continue
                    reach = None  # the end of the leader as far as it has been found clear
                    for length in ALL_LENGTHS:
                        start, elbow, right, box = candidate(p, r, span, ang, length)
                        if self.index.crosses(reach or start, elbow, (DIMLINE, HARD)):
                            break  # and so at every longer length
                        reach = elbow
                        if own is not None and own.hits(box, 0.8):
                            continue  # over its own view, which is never clear: further out
                        if not box.inside(area) or (ang in ANGLE_RANK_MAIN and length in LENGTHS):
                            continue  # off the sheet, or tried already
                        if severity(self.index, box, start, elbow, 0.0) > 0.0:
                            continue
                        cost = (0.0, soft_cost(start, elbow, box, length, ang))
                        if cost < best[0]:
                            best = (cost, start, elbow, right, p, r, c)
            return best

        best = search(None)
        if best is not None and best[0][0] > 0.0 and self.extra < LEADER_EXTRA:
            # no clear place: a drafter looks between the angles and lengths tried for a way
            # out between the lines round a crowded view
            counting, self.counting = self.counting, True
            best = clear_search(best)
            self.counting = counting
        words = DM.value_line(first) if first is not None else (lines[0] if lines else pd.id)
        if best is None:
            p, r, c, _span = self._anchors(pd, s)[0]
            a = math.radians(45.0)
            start = (p[0] + r * math.cos(a), p[1] + r * math.sin(a))
            elbow = (start[0] + 20.0, start[1] + 20.0)
            best = ((9.0, 0.0), start, elbow, True, p, r, c)
        if best[0][0] > 0.0:
            self.unplaced.append((pd.id, words))
        _cost, start, elbow, right, p, r, c = best
        moved = _moved(pd)
        if moved is not None:  # the user's offset of the shoulder, along x and y on the sheet
            elbow = (elbow[0] + moved.along_mm, elbow[1] + moved.across_mm)

        def draw_frame(x, y, anchor):
            box, ann = DM.frame(
                self.pen,
                self.index,
                x=x,
                y=y - h * 1.2,
                h=h,
                item=fitem,
                anchor=anchor,
                owner=f"{pd.id}-frame",
            )
            self.annotations.append(ann)
            return box

        box, shoulder = DM.leader_block(
            self.pen,
            self.index,
            did=pd.id,
            start=start,
            elbow=elbow,
            right=right,
            h=h,
            lines=lines,
            first=first,
            frame_draw=draw_frame if fitem is not None else None,
            arrow=pd.kind != "leader_note" or r > 0,
        )
        self.index.add(HARD, box, pd.id)
        self.leaders.append((pd.id, start, elbow))
        text = first if first is not None else DM.DimText(lines[0] if lines else "", suffix=tuple(lines[1:]))
        if pd.kind == "radius":
            points = (c, start)  # the arc's own centre, which may lie far off the part
        elif pd.kind in ("hole_callout", "diameter"):
            ux, uy = (start[0] - p[0], start[1] - p[1])
            points = (start, (p[0] - ux, p[1] - uy))
        else:
            points = (start, elbow, shoulder)
        self.annotations.append(
            D.Dimension(
                pd.id,
                pd.kind,
                pd.view,
                points,
                (box.x0, (box.y0 + box.y1) / 2),
                pd.value,
                text,
                0.0,
                pd.features,
                pd.tolerance,
                pd.places,
                DM.flags(pd.tolerance),
            )
        )
        return best[0][0]

    def _pattern_angle(self, pd) -> None:
        s = self.arr.slots.get(pd.view)
        need = self.detail.needs.get(pd.id)
        if s is None or need is None or pd.anchor is None:
            return
        fs = self.ctx.features
        pattern = fs.features[need.features[0]]
        first = fs.features[pattern.members[0]] if isinstance(pattern, Pattern) else None
        if first is None or pattern.centre is None:
            return
        centre = pattern.centre
        c = s.sheet(s.spec.project(centre))
        m = s.sheet(s.spec.project(first.axis.point))
        a1 = math.degrees(math.atan2(m[1] - c[1], m[0] - c[0])) % 360.0
        if pd.key.split("/")[0] == "step":
            # an arc's step: from the first member to the second
            m2 = s.sheet(s.spec.project(fs.features[pattern.members[1]].axis.point))
            a0 = math.degrees(math.atan2(m2[1] - c[1], m2[0] - c[0])) % 360.0
        else:
            # measured from the frame axis the record names, as this view shows it, along
            # it whichever way gives the value (an arc's first end may lie past 90 degrees
            # from either)
            d0 = self.ctx.direction(pd.axis or "x")
            ax = s.sheet(s.spec.project(tuple(centre[k] + d0[k] for k in range(3))))
            a0 = math.degrees(math.atan2(ax[1] - c[1], ax[0] - c[0])) % 360.0
            apart = min((a1 - a0) % 360.0, (a0 - a1) % 360.0)
            if abs((180.0 - apart) - math.degrees(pd.value)) < abs(apart - math.degrees(pd.value)):
                a0 = (a0 + 180.0) % 360.0
        if (a1 - a0) % 360.0 > 180.0:
            a0, a1 = a1, a0
        text = dim_text(self.ctx, pd)
        ann = DM.angle(
            self.pen,
            self.index,
            did=pd.id,
            vertex=c,
            a0=a0,
            a1=a1,
            radius=pd.radius * s.k + 8.0,
            h=self.h,
            text=text,
            value=pd.value,
            refs=pd.features,
            tolerance=pd.tolerance,
            places=pd.places,
            view=pd.view,
        )
        self.annotations.append(ann)

    # ------------------------------------------------------------------ furniture

    def title_fields(self, sc, number: int) -> dict[str, str]:
        """The title block's fields on sheet ``number`` of the drawing's ``self.sheet_count``."""
        fields = {k: v for k, v in self.plan.title}
        fields["size"] = self.frame.name
        fields["scale"] = standards.scale_text(sc)
        fields["sheet"] = f"{number} OF {self.sheet_count}"
        fields["status"] = self.status
        fields.setdefault("cage", self.settings.company.cage)
        if self.settings.standard.upper_case_notes:
            # lettered in capitals as the notes are, what was typed too; the MODEL cell
            # names the model as its file does
            fields = {k: (v if k == "model" else upper(v)) for k, v in fields.items()}
        return fields

    def paint_title(self, pen: Pen, box: Box, sc, number: int) -> list:
        """The title block in ``box`` on sheet ``number``, painted with ``pen``."""
        return titleblock.title_block(
            pen,
            box,
            unit=self.ctx.unit,
            fields=self.title_fields(sc, number),
            tolerance_lines=self.plan.tolerance_block,
            rows=tuple(self.settings.people.rows),
            signed=self.signed,
            company=self.settings.company,
            logo=self.logo,
            logo_sha=self.logo_sha,
        )

    def paint_stamps(self, pen: Pen, f: sheet.SheetFrame) -> list:
        """The border, its zones and the stamps of sheet frame ``f``."""
        out = stamps.border(pen, f, self.settings.sheets.zones, stamped=self.status != "RELEASED")
        name = getattr(self.source, "name", "") or ""
        configuration = getattr(self.source, "configuration", None)
        out += stamps.stamps(
            pen, f, released=self.status == "RELEASED", file_name=name, configuration=configuration
        )
        return out

    def paint_furniture(self, sc) -> None:
        f = self.frame
        ctx = self.ctx
        self.annotations += self.paint_title(self.pen, f.title, sc, 1)
        self.annotations += titleblock.revision_block(self.pen, f.revision, self.revisions)
        if f.parts is not None:
            heads, narrow, rows = self.parts_rows()
            shape = self.parts_shape(sheet.frame(f.name, self.settings))
            self.annotations += PL.parts_list(
                self.pen, f.parts, rows[: shape.lines], self.h, heads, narrow, shape.per_column
            )
        self.annotations += N.notes_block(
            self.pen, self.index, ctx, f.notes, self.plan.notes, self.h, self._frame_w
        )
        self.annotations += self.paint_stamps(self.pen, f)
        if ctx.process == "printed":
            self._build_arrows()

    def paint_continuation(self, sc, shapes: list[PL.Shape]) -> tuple[D.Sheet, ...]:
        """The sheets after the first, one for each of ``shapes``: the rest of the parts
        list, each column with its headings, on the title block (its SHEET n OF m), in
        the border with its zones and stamps. No views, revision block or notes: the
        first sheet carries those for the drawing."""
        if not shapes:
            return ()
        heads, narrow, rows = self.parts_rows()
        start = self.parts_shape(sheet.frame(self.frame.name, self.settings)).lines
        out = []
        for number, shape in enumerate(shapes, 2):
            f = sheet.continuation_frame(
                self.frame.name, self.settings, parts_height=shape.height, parts_width=shape.total_width
            )
            pen = Pen()
            annotations = self.paint_title(pen, f.title, sc, number)
            if f.parts is not None:
                chunk = rows[start : start + shape.lines]
                annotations += PL.parts_list(pen, f.parts, chunk, self.h, heads, narrow, shape.per_column)
            start += shape.lines
            annotations += self.paint_stamps(pen, f)
            made = tuple(annotations)
            out.append(D.Sheet(f.name, f.width, f.height, sc, annotations=made, painted=tuple(pen.items)))
        return tuple(out)

    def _build_arrows(self) -> None:
        """The build-direction arrow on the isometric and on each view that carries Z
        dimensions (10.6)."""
        h = self.h
        for v, s in self.arr.slots.items():
            if s.spec.kind != "isometric" and not any(pd.axis == "z" for pd in self.dims_by_view.get(v, [])):
                continue
            if s.spec.kind == "isometric" and self.arr.iso is None:
                continue
            b = s.box
            reach = h + text_width("BUILD Z", h * 0.36 * 3)
            bases = []
            for off in (0.0, 4.0, 8.0, 12.0, 18.0):  # beside the view's corners, then further out
                bases += [
                    (b.x0 - 8.0 - off, b.y0),
                    (b.x1 + 4.0 + off, b.y0),
                    (b.x0 - 8.0 - off, b.y1 - 12.0),
                    (b.x1 + 4.0 + off, b.y1 - 12.0),
                ]
            for base in bases:
                probe = Box(base[0] - h, base[1], base[0] + reach, base[1] + 12.0)
                if (
                    probe.inside(self.frame.area)
                    and not self.index.hits(probe, (HARD, VIEW, DIMLINE))
                    and not self.index.segment_hits(probe, (CENTRE,))
                ):
                    box = self.pen.build_arrow(base, 12.0)
                    self.index.add(HARD, box, "build")
                    break
            else:  # said, never left out silently
                self.unplaced.append(("build", f"the build-direction arrow of {v}"))


def layout(
    planned: Planned,
    *,
    options,
    settings,
    source=None,
    fields=None,
    logo: bytes | None = None,
    logo_sha: str = "",
    revisions=(),
    status: str = "PRELIMINARY",
    signed: dict[str, tuple[str, str]] | None = None,
    sheets: int = DEFAULT_LIMITS.sheets,
) -> LayoutResult:
    """Lay a plan out on a sheet (11), and on the sheets after it an assembly's parts
    list too long for the first goes on to, at most ``sheets`` in all."""
    run = _Run(
        planned,
        options,
        settings,
        logo=logo,
        logo_sha=logo_sha,
        source=source,
        fields=dict(fields or {}),
        revisions=tuple(revisions),
        status=status,
        signed=dict(signed or {}),
        sheets=sheets,
    )
    return run.run()


__all__ = ["LayoutResult", "attach", "layout", "severity"]
