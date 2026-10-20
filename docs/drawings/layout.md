# Layout, sheet and title block

`solidseas.drawing.layout` lays a plan out on a sheet (`docs/DRAWINGS.md` 11).
Provisional until the first release that makes drawings.

- `layout(planned, *, options, settings, source=None, fields=None, logo=None,
  revisions=(), status="PRELIMINARY", signed=None)` returns a `LayoutResult`: the
  `display.Sheet` (placed geometry, annotations and the painted layer), the
  layout checks, the view and axis pairs whose baseline band was too deep, the
  sheet frame, the scale and the seconds it took.

## Sheet and scale

`layout.sheet` holds each size's border, zones and reserved areas: the title
block in the lower right (one layout for B to E, a compact one for A), the
revision block in the upper right, the notes above the title block, and the
plot stamp inside the border at the lower left.

**C24, the slice's answer and the default until the VM decides:** on each sheet,
smallest first, the largest preferred scale at which the views and their bands
fit; a reduced scale only while every dimensioned span stays at least 8 mm on
paper, else the next sheet. When no sheet does better the first fit is kept and
the cramped span is reported, with Add Detail View as the fix. A drawing's own
sheet or scale is kept as it is.

## Bands and arrangement

`layout.arrange` (11.1):

- Each view's linear and ordinate dimensions go to a side: locations below and
  to the left, near the datums; the envelope above and to the right; other sizes
  on the side their feature lies.
- On each side they are coloured into tracks, shortest span first, a span
  widened by its text when the text goes outside. A horizontal band's tracks
  stand a row apart; a vertical band's stand apart by their texts (C19). A
  framed dimension's track is a frame deeper. Ordinates come first, their values
  turned on their extension lines; values too close to stand at their own places
  are jogged apart along the row, and the row takes room as far as its last value
  reaches, which on a hole-dense part is far past its view. A dimension's text is centred on its line, so
  on a left or right side with ordinates the first track stands half its text
  beyond where the ordinates' texts end, and below or above them a text height
  further out, not across them.
- Leader items reserve room beside their view (C20).
- A datum feature symbol stands out from its face away from the material, the
  way the face's outward normal shows in the view, so it is read against its own
  face and not one behind it. Where it reaches past its view it reserves that
  reach (its triangle, leader and letter box, about 10.5 mm at 3 mm lettering) on
  that side, where no band is deeper, and a first row of linear dimensions there
  stands 1.5 mm beyond it, so the symbol sits between the view and their lines and
  texts (an ordinate row's texts start past it as they are). The room is not
  worth a smaller scale: when the views do not fit with it, they are arranged
  without it at the same scale, and the symbol finds what room it can.
- Third angle: the front anchors, the top above it and the right to its right on
  their shared axes, the gap between two views their facing bands (or datum
  symbols) and two text heights. The group is centred beside the title column, or above it. The
  isometric goes in the free area left, at full scale or smaller (C25).

## Placement

`layout.place` places in the slice's order (C22): the views and reserved areas
as obstacles, the bands track by track, the datum symbols on their faces, a
circular pattern's pitch circle and angle, then the callouts and other leader
items, the largest first, then the notes, the title block, the border and the
stamps.

`layout.index.Index` holds three kinds of obstacle (C21): hard boxes (views,
reserved areas, texts, frames), dimension lines and leaders, which no leader may
cross, and extension lines, which leaders may cross at a cost and datum symbols
may not. A view is the box of its outline, its runs but its centre lines: centre
lines, centre marks and a pattern's pitch circle, which may reach past the part,
are lines of their own that no text, frame or symbol may cover. The index can be
marked and rewound to the mark, handing back what came after so it can be added
again exactly as it was; the leader items' further passes use this.

A datum symbol's foot tries its face's line, the middle first and then towards
its ends, then off its ends on an extension line of the face (10.5), then off the
view altogether on the face's line carried past it: between the view and the
first row of the band there, then past that band. It takes the first spot whose
letter box meets no text, view, dimension line, extension line or centre line
and whose extension line crosses no text.

A datum's face often shows as a line in more than one view: the end of a plate
is an edge in the front and in the top. The plan names the view the symbol goes
in (the front first, then the least crowded) and offers the others where the
face is a line, in the same order. Where every spot in its own view is taken,
often by a tall column of ordinates, the symbol tries each offered view in turn
and goes in the first with a clear spot. The plan's dimension, the drawing's
record and the sheet then name the view it was drawn in, so the checks, the
drawing file and the sheet agree, and a layout after an edit tries the views in
the same order and draws it in the same place. With no clear spot in any of
them, it goes in the middle of its face in the first view that shows it and is
reported.

A leader item's candidates (up to eight members of a pattern, or of equal
features stated once, the outermost first, the last five only while the first three have no clear place; leader
angles from 15 to 75 degrees in each quadrant; lengths from 6 to 140 mm) are
scored on how far each is from clear, then on crossed extension lines and other
views, the length of leader inside its own view and the leader's length; the
best is taken. Where no place is clear the least bad is: text over other text is
worst, as neither reads; text over a view or a line, a line through the text and
the leader through text come next; a leader across a dimension line or another
leader is least. A callout's block reserves the full height of the feature
control frame under its lines.

An item with no clear place among those candidates gets a closer look: every
member it may start from, leader angles every 2.5 degrees from 15 to 75 and the
lengths halfway between those above, each direction followed outward only until
its leader would cross a line or a text (it would at every longer length too),
and only a clear place taken. Then, as a drafter starts over with the hard ones,
the leader items are placed again with those still lacking a clear place first,
then each of them alone first, at most two passes more; a pass is kept only when
fewer items are left without a clear place, or as many less badly. Both stop
once a sheet has looked at `LEADER_EXTRA` (30 000) places beyond each item's
first search, a count and not a time, so a sheet past help costs little more
and the layout is the same on any machine. Nothing is dropped: an item with no
clear place is put at its best and reported.

A radius's leader starts on its arc, not anywhere on the arc's circle, whose
centre may lie far off the part: radially from the centre within the arc's own
span (`Need.on_face` holds a point in the middle of each member's arc, its centre
and half the angle it spans), or from the arc's middle. A circle of
`TINY_ARC` (1.5 mm) radius or less on paper stays by its arc, so any direction
will do there. A torus fillet (one along a curved edge) is measured from the
centre of its cross-section, not the torus's own centre. The radius dimension's
definition points are that arc's centre and the leader's start.

## Painting

`layout.dimension` paints (11.2): extension lines with a gap from a face and none
from a centre mark, whose end they start at (C23); filled arrowheads three times
as long as wide; unidirectional text in a break of the dimension line, outside
with the arrows when cramped (past the far end, right or above; past the near
end when another text stands at the far one and the near one is free, as two
such texts meet at a tiny part's corner, and no dimension of the same track
stands there); basic values boxed; stacked tolerances; ordinates
from a 0, close values jogged and equal values sharing one; leaders with a
horizontal shoulder; feature control frames as cells; datum symbols. Holes in
line get a centre line joining them.

`layout.glyphs.Pen` measures text with the writers' fonts and draws the symbols
WinAnsi lacks as paths: counterbore, spotface, countersink and depth, the GD&T
characteristics and the MMC and LMC circles, the projection symbol, the datum
triangle and the build-direction arrow. A character the font lacks is shown as
`?` and reported.

`layout.patterns` fits each hidden, centre and phantom line's dashes so it
starts and ends with a dash (11.5).

Owners: every painted item belongs to its dimension's id, a frame to
`<id>-frame`, a datum symbol to `datum-<letter>`, a note to `n-<k>`. Definition
points follow `docs/drawings/dxf.md`: a linear dimension's two extension line
origins and a point on its line; a diameter's point on the circle and the
opposite point; a radius's centre and point; an angle's vertex, a point on each
side and one on the arc; an ordinate's origin, feature and leader end.

## The title block, notes and stamps

`layout.titleblock` paints the ASME block: company and logo, title, size, CAGE,
drawing number and revision, scale, calculated weight and sheet (SHEET n OF m:
`1 OF 1`, unless an assembly's parts list goes on to more sheets, each painted by
`place._Run.paint_continuation` with this block, its border, stamps and its part
of the list, DRAWINGS.md 11.7), status, the
model with its revision and short hash, material and finish; on the left the
tolerance block wrapped to fit, the projection symbol, the approval rows (empty
until signed, DRAWN signed when made), DO NOT SCALE DRAWING and the proprietary
statement. The logo keeps its own proportions (`images.png_size` reads them from
its header): as tall as the company cell less a millimetre above and below, at
most half the cell's width (`titleblock.LOGO_SHARE`; a wide logo is then less
tall, centred), against the cell's right side; the company's name and address
take the width left. Its values are lettered in capitals when the Settings letter notes
so (typed ones too; the record keeps them as typed), except the model's, which
names the file as it is. A value too long for its cell is set smaller, then cut with an
ellipsis; the model's is cut in its part number, so its revision and short hash
stay whole. The title and the drawing number are kept at the lettering minimum (22
rule 10) where they can be:
- a title that one line would set below it goes on two lines, broken between
  words, its row taller and the material row shorter;
- a drawing number that does not fit its cell at the minimum takes the CAGE
  cell's width when the company has no CAGE code (CAGE is optional, 11.4).

An assembly's parts list stands on the title block, the notes above it, and its
item balloons stand round their views (`layout.partslist`,
[assemblies.md](assemblies.md)).

`layout.notes` paints NOTES: and the numbered notes with their frames
after the words; the next note starts far enough down that its capitals stand a
millimetre clear of a frame above. `layout.stamps` paints the border with its zones, the
PRELIMINARY stamp in the top margin of every unreleased sheet (sized to stay
clear of the zone labels; a zone mark under it stops a millimetre short of it),
and the plot stamp: SolidSeas, its version, the
part's file name (never a folder) and its configuration.

## Checks

`layout.checks` (11.6): text over text, text outside the border, items in the
title, revision or notes block, leaders outside 15 to 75 degrees, characters the
font lacks, items placed with a conflict, cramped spans.

## Speed

On the VM a seeded plate with 100 holes (305 dimensions, about 200 of them basic
locations) plans in 0.02 s and lays out in about 1.1 s, against the 3 s target
of 11.3. Placement is deterministic: stable sort keys and no randomness.

## Tests

`tests/test_drawing_layout.py`: sheet and scale by C24, third-angle alignment,
every shown dimension drawn once with its definition points, frames and datum
symbols, WinAnsi text with owners, symbols as paths, ordinates, centre lines
through holes in line, leader angles, the title block and stamps, notes with
their frame, painting and the compact round trip, determinism, dash fitting, the
index and its rewind, symbols in text, a crowded plate whose callouts find a clear
place only with the closer look and the further passes, a datum boxed in on
the front that is drawn and recorded in the top, and the 100-hole benchmark.
`tests/test_drawing_orchestrate.py`: the pipeline's plan stage, a new front
drawing the views again, ordinates for a deep band, the time bounds and the logo.
