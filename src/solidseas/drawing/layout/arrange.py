"""Bands, tracks and the arrangement of the views (``docs/DRAWINGS.md`` 11.1).

1. **Bands.** Each view's linear and ordinate dimensions go to a side: locations
   below and to the left, near the datums; the envelope above and to the right,
   outermost; other sizes on the side their feature lies. On each side they are
   coloured into tracks, shortest span first, a span widened by its text when the
   text goes outside. A horizontal band's tracks stand a row apart; a vertical
   band's tracks stand apart by their texts, since unidirectional text is
   horizontal (C19). Leader items reserve room to the view's right (C20).
2. **Arrangement.** Third angle: the front anchors; the top above it and the right
   to its right, aligned on their shared axis; the gap between two views the sum of
   their facing bands and two text heights. The group is centred in the drawing
   area beside the title column, or above it. The isometric goes in the free area
   left, at full scale or smaller (C25).
3. **Scale and sheet**: :mod:`.sheet`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import standards
from ..numbers import plain_sum
from ..plan.values import dim_text
from ..types import PlannedDimension, ViewGeometry, ViewSpec
from .dimension import frame_room
from .glyphs import text_width
from .index import Box
from .sheet import GAP, SheetFrame

LEADER_KINDS = ("hole_callout", "diameter", "radius", "chamfer", "leader_note", "angle")
SIDES = ("below", "above", "left", "right")
LEADER_ROOM = 16.0  # a leader and its shoulder, beside the widest text block
DATUM_CLEAR = 1.5  # mm between a datum feature symbol and the first row of dimensions past it


@dataclass
class Slot:
    """One view on the sheet: its geometry's box in view metres, its scale (sheet
    millimetres per view metre) and the sheet point its view origin sits at."""

    spec: ViewSpec
    geom: ViewGeometry
    vbox: Box
    k: float
    origin: tuple[float, float] = (0.0, 0.0)

    def sheet(self, p) -> tuple[float, float]:
        return (self.origin[0] + self.k * p[0], self.origin[1] + self.k * p[1])

    @property
    def box(self) -> Box:
        v = self.vbox
        return Box(*self.sheet((v.x0, v.y0)), *self.sheet((v.x1, v.y1)))

    @property
    def outline(self) -> Box:
        """The view's outline on the sheet: the box of its runs other than centre lines
        (:func:`outline_box`)."""
        v = outline_box(self.geom)
        return Box(*self.sheet((v.x0, v.y0)), *self.sheet((v.x1, v.y1)))

    @property
    def size(self) -> tuple[float, float]:
        return (self.vbox.width * self.k, self.vbox.height * self.k)


def view_box(geom: ViewGeometry) -> Box:
    """A view's box in view metres: its runs and centre marks."""
    b = geom.bounds()
    pts = []
    if b is not None:
        pts += [(b[0], b[1]), (b[2], b[3])]
    for c, r in geom.centre_marks:
        pts += [(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)]
    for a, c in geom.centre_lines:
        pts += [a, c]
    if not pts:
        return Box(0.0, 0.0, 1e-3, 1e-3)
    return Box.around(pts)


def outline_box(geom: ViewGeometry) -> Box:
    """A view's outline in view metres: the box of its runs other than centre lines,
    which may reach past the part (a pattern's pitch circle); the view's box when it
    has no other runs."""
    pts = []
    for r in geom.runs:
        bounds = getattr(r.primitive, "bounds", None)
        if r.style == "centre" or bounds is None:
            continue
        x0, y0, x1, y1 = bounds()
        pts += [(x0, y0), (x1, y1)]
    return Box.around(pts) if pts else view_box(geom)


@dataclass
class BandDim:
    pd: PlannedDimension
    side: str
    lo: float  # along the band, sheet mm from the view origin
    hi: float
    text_w: float
    track: int = 0
    outside: bool = False
    origin: float = 0.0  # where it is measured from and to along the band, sheet mm from the view origin
    at: float = 0.0


@dataclass
class Band:
    side: str
    dims: list[BandDim] = field(default_factory=list)
    offsets: list[float] = field(default_factory=list)
    depth: float = 0.0


def text_height(unit: str) -> float:
    return standards.TEXT[unit].dimension


def dim_width(ctx, pd: PlannedDimension) -> float:
    """The width of a dimension's value line as painted, the basic box included."""
    t = dim_text(ctx, pd)
    h = text_height(ctx.unit)
    w = text_width(t.prefix + t.value, h)
    if t.after:
        w += text_width(" " + t.after, h)
    if t.upper or t.lower:
        w += max(text_width(t.upper, h * 0.8), text_width(t.lower, h * 0.8)) + h * 0.3
    if t.boxed or pd.tolerance == "basic":
        w += h * 0.6
    return w


def side_of(pd: PlannedDimension, sheet_axis: str, across_mid: float, view_mid: float) -> str:
    horizontal = sheet_axis == "x"
    if pd.kind != "ordinate" and pd.side in (("below", "above") if horizontal else ("left", "right")):
        return pd.side  # the side the user flipped it to
    if pd.kind == "ordinate" or pd.role == "feature_location":
        return "below" if horizontal else "left"
    if pd.role == "envelope":
        return "above" if horizontal else "right"
    if horizontal:
        return "above" if across_mid > view_mid else "below"
    return "right" if across_mid > view_mid else "left"


def bands(
    ctx,
    slot: Slot,
    dims: list[tuple[PlannedDimension, float, float, str, float]],
    clear: dict[str, float] | None = None,
) -> dict[str, Band]:
    """The bands of one view. ``dims`` holds, for each linear or ordinate dimension,
    the dimension, its two ends along its sheet axis (view metres), that axis, and the
    middle of its witnesses across it (view metres). ``clear`` gives, by side, how far
    past the view a datum feature symbol stands (sheet mm): a first row of linear
    dimensions stands beyond it, so the symbol sits between the view and their lines
    and texts (an ordinate row's texts start past it as they are)."""
    clear = clear or {}
    h = text_height(ctx.unit)
    pre = standards.DIMENSIONS
    arrow = h
    out = {s: Band(s) for s in SIDES}
    mid_x = (slot.vbox.x0 + slot.vbox.x1) / 2
    mid_y = (slot.vbox.y0 + slot.vbox.y1) / 2
    for pd, a, b, sheet_axis, across in dims:
        side = side_of(pd, sheet_axis, across, mid_y if sheet_axis == "x" else mid_x)
        lo, hi = sorted((a * slot.k, b * slot.k))
        w = dim_width(ctx, pd)
        if pd.frame is not None:
            w = max(w, frame_width(ctx, pd.frame))  # the frame sits under the text
        bd = BandDim(pd, side, lo, hi, w, origin=a * slot.k, at=b * slot.k)
        if pd.kind != "ordinate":
            # a vertical line is broken below its text for a frame there (dimension.linear)
            below = frame_room(h) if pd.frame is not None and sheet_axis != "x" else 0.0
            need = (w if sheet_axis == "x" else h + below) + 2 * arrow + 3.0
            if hi - lo < need:
                bd.outside = True
                hi += (w if sheet_axis == "x" else h) + arrow + 2.0
        bd.lo, bd.hi = lo, hi
        out[side].dims.append(bd)
    for side, band in out.items():
        _jog(band, h)
        horizontal = side in ("below", "above")
        ords = [d for d in band.dims if d.pd.kind == "ordinate"]
        lins = [d for d in band.dims if d.pd.kind != "ordinate"]
        tracks: list[list[tuple[float, float]]] = []
        widths: list[float] = []
        for d in sorted(lins, key=lambda d: (d.hi - d.lo, d.pd.id)):
            for t, used in enumerate(tracks):
                if all(d.hi + 1.5 < u0 or d.lo - 1.5 > u1 for u0, u1 in used):
                    used.append((d.lo, d.hi))
                    widths[t] = max(widths[t], d.text_w)
                    d.track = t
                    break
            else:
                tracks.append([(d.lo, d.hi)])
                widths.append(d.text_w)
                d.track = len(tracks) - 1
        offsets: list[float] = []
        first = pre.first_row
        if ords:
            # the ordinate row comes first; its texts stand on its extension lines
            ow = max(d.text_w for d in ords)
            first = pre.first_row + ow + 2.0
            for d in ords:
                d.track = -1
        elif clear.get(side, 0.0) > 0.0:
            first = max(first, clear[side] + DATUM_CLEAR)
        framed = {d.track for d in lins if d.pd.frame is not None}
        for t, w in enumerate(widths):
            if horizontal:
                extra = plain_sum(h + 3.0 for u in framed if u < t)  # a framed track is a frame deeper
                # A horizontal dimension's text is centred on its line too: past a row of
                # ordinates, whose texts run out along their extension lines, it stands a
                # text height further out, its own half and a clearance, not across theirs.
                offsets.append(first + (h if ords else 0.0) + pre.row_spacing * t + extra)
            elif t == 0:
                # A vertical dimension's text is centred on its line: past a row of ordinates
                # or a datum feature symbol it stands half its width beyond where they end,
                # not across them.
                past = bool(ords) or clear.get(side, 0.0) > 0.0
                offsets.append(max(first + (w / 2 + 0.5 if past else 0.0), w / 2 + 3.0))
            else:
                offsets.append(offsets[-1] + max(pre.row_spacing, widths[t - 1] / 2 + w / 2 + 2.5))
        band.offsets = offsets
        if offsets:
            last = widths[-1]
            band.depth = offsets[-1] + (h / 2 + 1.5 if horizontal else last / 2 + 1.5)
            band.depth = max(band.depth, offsets[-1] + pre.extension_overrun)
        elif ords:
            band.depth = first
    return out


def _jog(band: Band, h: float) -> None:
    """Stretch each ordinate of ``band`` to where its value stands once values too close
    to stand at their own places are jogged apart along the row, as
    :func:`.dimension.ordinate_band` places them: the arrangement leaves room for the
    row's whole reach, which on a hole-dense part runs far past its view."""
    rows: dict[float, list[BandDim]] = {}
    for d in band.dims:
        if d.pd.kind == "ordinate":
            rows.setdefault(round(d.origin, 6), []).append(d)
    for origin, ds in rows.items():
        boxed = any(d.pd.tolerance == "basic" for d in ds)
        pitch = h * (1.9 if boxed else 1.0) + 1.4
        entries = [(origin, 0, None)] + [(d.at, 1, d) for d in ds]  # the row's 0 first
        last = last_at = None
        for at, _order, d in sorted(entries, key=lambda e: (e[0], e[1], e[2].pd.id if e[2] else "")):
            if last_at is not None and abs(at - last_at) < 0.01:
                continue  # the same value again: its extension line only
            last_at = at
            last = at if last is None else max(at, last + pitch)
            if d is not None:
                d.hi = max(d.hi, last + pitch / 2)


def leader_room(ctx, dims: list[PlannedDimension]) -> tuple[float, float]:
    """Room for a view's leader items: the widest text block plus a leader, and the
    tallest."""
    h = text_height(ctx.unit)
    widest = 0.0
    tallest = 0.0
    for pd in dims:
        if pd.kind not in LEADER_KINDS:
            continue
        t = dim_text(ctx, pd)
        lines = [t.prefix + t.value + ((" " + t.after) if t.after else ""), *t.suffix]
        w = max(text_width(line, h) for line in lines)
        rows = len(lines)
        if pd.frame is not None:
            w = max(w, frame_width(ctx, pd.frame))
            rows += 1.6
        widest = max(widest, w)
        tallest = max(tallest, rows * h * 1.7)
    if widest == 0.0:
        return 0.0, 0.0
    return widest + LEADER_ROOM, tallest + LEADER_ROOM / 2


def frame_width(ctx, cell) -> float:
    from ..plan.gdt import zone_text

    h = text_height(ctx.unit)
    box = h + 2.0
    w = box  # the characteristic's cell
    zone = ("Ø" if cell.diameter else "") + zone_text(ctx, cell.value)
    w += text_width(zone, h) + 2.4 + (box * 0.8 if cell.modifier else 0.0)
    for _d in cell.datums:
        w += box
    return w


@dataclass
class Arrangement:
    slots: dict[str, Slot]
    bands: dict[str, dict[str, Band]]
    group: Box  # the views with their bands, on the sheet
    iso: str | None = None
    iso_factor: float = 1.0


def _depth(bnds: dict[str, Band], datums: dict[str, float], side: str) -> float:
    """How far a view's furniture stands out on ``side``: its band, or a datum feature
    symbol standing on a face there, whichever is deeper."""
    return max(bnds[side].depth, datums.get(side, 0.0))


def _extent(
    slot: Slot,
    bnds: dict[str, Band],
    room: tuple[float, float],
    datums: dict[str, float] | None = None,
    pad: float = 0.0,
) -> Box:
    """A view with its bands and datum symbols: their depth across, and along each band
    as far as its dimensions reach (a short span's text stands outside its end);
    ``pad`` more all round where balloons go."""
    b = slot.box
    datums = datums or {}
    x0 = b.x0 - max(_depth(bnds, datums, "left"), pad)
    y0 = b.y0 - max(_depth(bnds, datums, "below"), pad)
    x1 = b.x1 + max(_depth(bnds, datums, "right"), room[0], pad)
    y1 = b.y1 + max(_depth(bnds, datums, "above"), room[1] * 0.5, pad)
    for side, band in bnds.items():
        k = 0 if side in ("below", "above") else 1
        for bd in band.dims:
            lo, hi = slot.origin[k] + bd.lo, slot.origin[k] + bd.hi
            if k == 0:
                x0, x1 = min(x0, lo), max(x1, hi)
            else:
                y0, y1 = min(y0, lo), max(y1, hi)
    return Box(x0, y0, x1, y1)


def arrange(
    ctx,
    frame: SheetFrame,
    slots: dict[str, Slot],
    all_bands: dict[str, dict[str, Band]],
    rooms: dict[str, tuple[float, float]],
    datum_rooms: dict[str, dict[str, float]] | None = None,
    *,
    pads: dict[str, float] | None = None,
) -> Arrangement | None:
    """The views placed on ``frame`` (their scale already set), or None when they do
    not fit. ``datum_rooms`` gives, by view, the sides a datum feature symbol stands
    out on and how far; ``pads`` the room all round a view that carries balloons."""
    datum_rooms = datum_rooms or {}
    pads = pads or {}
    h = text_height(ctx.unit)
    names = {s.spec.name: v for v, s in slots.items() if s.spec.kind != "isometric"}
    base = next((v for v, s in slots.items() if s.spec.kind == "base"), None)
    if base is None:
        return None
    for s in slots.values():
        s.origin = (0.0, 0.0)

    def ext(v: str) -> Box:
        return _extent(slots[v], all_bands[v], rooms.get(v, (0.0, 0.0)), datum_rooms.get(v), pads.get(v, 0.0))

    def depth(v: str, side: str) -> float:
        return _depth(all_bands[v], datum_rooms.get(v, {}), side)

    # the front at the origin, the others around it on their shared axes
    placed = {base}
    order = [("top", "above"), ("bottom", "below"), ("right", "right"), ("left", "left")]
    for name, where in order:
        v = names.get(name)
        if v is None or v in placed:
            continue
        s = slots[v]
        b = s.box
        if where == "above":
            y = ext(base).y1 + depth(v, "below") + 2 * h - b.y0
            s.origin = (0.0, y)
        elif where == "below":
            y = ext(base).y0 - depth(v, "above") - 2 * h - b.y1
            s.origin = (0.0, y)
        elif where == "right":
            x = ext(base).x1 + depth(v, "left") + 2 * h - b.x0
            s.origin = (x, 0.0)
        else:
            x = ext(base).x0 - max(depth(v, "right"), rooms.get(v, (0.0, 0.0))[0]) - 2 * h - b.x1
            s.origin = (x, 0.0)
        placed.add(v)
    back = names.get("back")
    if back is not None and names.get("right") is not None:
        r = names["right"]
        s = slots[back]
        s.origin = (ext(r).x1 + depth(back, "left") + 2 * h - s.box.x0, 0.0)
        placed.add(back)
    for v, s in slots.items():
        if v not in placed and s.spec.kind not in ("isometric",):
            # sections and details: to the right of everything placed so far
            right = max(ext(p).x1 for p in placed)
            s.origin = (right + depth(v, "left") + 2 * h - s.box.x0, 0.0)
            placed.add(v)
    group = None
    for v in placed:
        e = ext(v)
        group = e if group is None else group.union(e)
    assert group is not None
    area = frame.area
    column = frame.title.union(frame.notes)
    # beside the title column, centred; else above it
    spots = []
    beside = Box(area.x0, area.y0, column.x0 - GAP, frame.revision.y0 - GAP)
    if group.width <= beside.width and group.height <= area.height:
        top = min(area.y1, frame.revision.y0 - GAP) if group.x1 - group.x0 > beside.width - 1 else area.y1
        spots.append(
            (
                (beside.x0 + beside.x1) / 2 - (group.x0 + group.x1) / 2,
                (area.y0 + top) / 2 - (group.y0 + group.y1) / 2,
            )
        )
    above = Box(area.x0, column.y1 + GAP, area.x1, frame.revision.y0 - GAP)
    if group.width <= area.width and group.height <= above.height:
        spots.append(
            (
                (above.x0 + above.x1) / 2 - (group.x0 + group.x1) / 2,
                (above.y0 + above.y1) / 2 - (group.y0 + group.y1) / 2,
            )
        )
    shifted = None
    for dx, dy in spots:
        g = Box(group.x0 + dx, group.y0 + dy, group.x1 + dx, group.y1 + dy)
        if g.inside(area) and not any(g.hits(r) for r in frame.reserved):
            shifted = (dx, dy, g)
            break
    if shifted is None:
        return None
    dx, dy, g = shifted
    for v in placed:
        s = slots[v]
        s.origin = (s.origin[0] + dx, s.origin[1] + dy)
    out = Arrangement(slots, all_bands, g)
    iso = next((v for v, s in slots.items() if s.spec.kind == "isometric"), None)
    if iso is not None:
        out.iso, out.iso_factor = iso, _place_iso(frame, slots[iso], [g], pads.get(iso, 0.0))
        if out.iso_factor == 0.0:
            out.iso = None
    return out


def _place_iso(frame: SheetFrame, s: Slot, taken: list[Box], pad: float = 0.0) -> float:
    """Find room for the isometric, at full scale or smaller (C25), with ``pad`` more
    all round where its balloons go: its factor, or 0 when it fits nowhere. Tried
    from the top right, clear of the revision block."""
    area = frame.area
    blocked = taken + frame.reserved
    base_k = s.k
    margin = max(GAP, pad)
    for f in (1.0, 0.75, 0.5, 0.35):
        s.k = base_k * f
        s.origin = (0.0, 0.0)
        b = s.box
        w, hgt = b.width + 2 * margin, b.height + 2 * margin
        step = 4.0
        y = area.y1 - hgt
        while y >= area.y0:
            x = area.x1 - w
            while x >= area.x0:
                cand = Box(x, y, x + w, y + hgt)
                if not any(cand.hits(o) for o in blocked):
                    s.origin = (x + margin - b.x0, y + margin - b.y0)
                    return f
                x -= step
            y -= step
    s.k = base_k
    return 0.0


__all__ = [
    "LEADER_KINDS",
    "Arrangement",
    "Band",
    "BandDim",
    "Slot",
    "arrange",
    "bands",
    "dim_width",
    "frame_width",
    "leader_room",
    "outline_box",
    "side_of",
    "text_height",
    "view_box",
]
