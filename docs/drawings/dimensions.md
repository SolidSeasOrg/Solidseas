# Dimensioning

`solidseas.drawing.plan` plans a drawing's dimensions (`docs/DRAWINGS.md` 10).
Provisional until the first release that makes drawings.

- `make_plan(ctx, source=None, fields=None, *, previous, deep, limits)` returns a
  `Planned`: the `Plan` (views, dimensions, datums, notes, title fields, the
  tolerance block, the graphs' verdicts, coverage and bands) and a `PlanDetail`
  beside it with what layout and the editor need (each dimension's positions,
  need and sheet axis, the location edges, what no view could draw).
- `Context(model, features, views, options, settings, unit=..., ids=..., decisions=...)`
  holds one run's inputs. Feature ids are `f-1`, `f-2`... in recognition order
  unless a drawing passes its own (13.4); `decisions` holds the user's per
  feature choices (a confirmed thread and its depth).
- `solidseas.drawing.orchestrate.plan_and_layout` is the pipeline's plan stage;
  `orchestrate.run` gives the same with every step's output kept.

## Requirements and positions

`plan.requirements` reads the feature set (10.1, 10.2) and gives:

| What | From |
|---|---|
| Positions along each frame axis | planar faces square to it (one a value), the axes of holes, bosses, slots and grooves, a circular pattern's centre, the meet lines of angled faces (joined to a face at the same value, whose plane the line lies in) |
| Implied links | widths (their two faces), depths (floor and open face), pattern pitches (members to the first), a slot's walls to its centre line, its two end centres, a full-round end's centre to the faces of its width (the derived R) |
| Needs | each size, callout, note or angle stated once, keyed by feature ids (`size/f-3`, `callout/f-5`, `pitch/f-19/x`, `pcd/f-21`); equal chamfers, fillets and angles (angled faces at one angle to one principal plane whose meet lines run along one axis, `requirements.ANGLE_STEP`) once with their count |

Faces a callout states (a hole's or groove's shoulders and floors) and blend and
chamfer faces are not positions. Centres at one value merge when they share an
axis line (a hole in a boss) or lie on parallel axes (holes in line, which the
drawing joins with a centre line), so one dimension locates them all.

## The graphs

`plan.graph.Graph` is one frame axis: positions contracted by the implied links
into nodes; the origin the datum face square to the axis. `check(edges)` says
whether the drawn locations reach every node (complete) and form a tree (not
redundant), naming the missing requirement keys and the dimensions of each
closed loop. `label(node)` names a node by its features ("the Ø6.60 hole"), not
its coordinates (C16).

`plan.graph.witnesses` answers where a position can carry an extension line
(C8): a face where a view shows a visible line at it; a hole's, boss's or slot's
axis where a view sees it end on and open (a blind hole only from its entry) or
its centre line side on; an angled face's meet line end on.

`plan.angular` checks each circular pattern: its members are one node through
the equal spacing; a first member off the principal axes needs its angle, measured
from the first frame axis square to the pattern's and anchored on that member
(`conventions.md` 8).

An arc pattern, holes on one circle at an equal step that do not go all the way
round, is dimensioned as a drafter would: the callout with its count (`5X Ø5.00
THRU`), the pitch circle's diameter, the angle from the frame axis to the first
end hole, and the step from the first hole to the second with the count of spaces
(`4X 30°`). The first end's angle is measured from whichever way along the axis is
nearer, so it is never more than 90 degrees, and an end on a principal axis needs
none. The step is required like a row's pitch: without it the arc's angular graph
is incomplete. The members get no locations of their own, and the pitch circle is
drawn as a centre-line arc from one end hole to the other.

## Schemes

`plan.graph.baseline` draws each node from the origin where one view sees both,
else by the cheapest drawable path, each step from the origin costing more so
stacks stay short; another face of the origin's node costs a little more than
the datum face itself, and a slot is located by its centre line rather than a
wall. Under the datum scheme the locations are basic.

`plan.schemes.arrangement` turns a view and axis to ordinate when the Settings'
default is ordinate, when the drawing's options say so (`v-1/x`), when baseline
would need more than the Settings' tracks on one side, or when layout found the
band deeper than the Settings' share of the view and there are three locations
or more.

## Views, assignment and the front

`plan.select.choose_front` scores the six directions and four turns (8.2):
features seen open in true shape, the planar area seen flat on, features that
would be hidden, the longest extent across the sheet, and a printed part's build
plate at the bottom; ties go in a fixed order, and the choice comes with its
reason. The orchestrator draws the views again when the chosen front differs
from the one drawn.

`plan.select.choose_views` keeps the front and adds projected views by greedy
coverage (8.3); the isometric stays when Settings ask for it.

`plan.assign.Assigner` puts each dimension in a view (10.7): witnesses visible in
it, the view already holding the feature's other dimensions, the less crowded
view, the front. Callouts go where the hole is seen end on and open; a
diameter with no end-on view goes where its axis is side on.

## Callouts, values and notes

`plan.callouts.hole` writes a hole's callout in manufacturing order: count and
diameter with THRU or its depth (to the full diameter), the counterbore or
spotface line (`⌴`, `⌴SF`), the countersink line (`⌵` with the diameter at the
surface and the included angle), a confirmed thread and its depth, an entry
round or chamfer larger than the edge break. Settings can ask for words
(CBORE, SPOTFACE, CSK, DEEP). In a planned callout `suffix[0]` is THRU or the
depth on the value's line and the rest are lines below.

`plan.values` gives precision by role from the Settings (inch: two places for
the envelope, steps and widths, three for hole sizes; millimetre: one and two),
basic values to the places they need, printed parts' nominals as needed, the
tolerance bands (`(("±0.2", 3), ("±0.05", 1))`) and the rounding guard (a value
shown more than a tenth of its band off the model's is flagged, its precision
never changed). A full-round end's radius is `tolerance="derived"` and reads
`R` alone.

`plan.notes` fills the note templates from the drawing and leaves out a template
whose token has no value; the general profile note comes first under the datum
scheme, a printed part's process tolerance note first under plus/minus, and the
model-governs note last on a reduced-dimension drawing. Capitals keep the micro
sign and its units (`µm`, `µin`). Title fields come from the wizard, then the
part's properties, then the file name; the material through the mapping table;
the weight from the volume and density.

## Key dimensions only

`plan.keep` (10.10) keeps a crowded drawing to its key dimensions.
`orchestrate.run` plans every requirement first; when the plan has more than
`keep.BUDGET` (60) dimensions, `keep.trim(ctx, full, budget)` returns the context
with the rest left to the model, and the drawing is planned again from it:

- kept whatever the count: the envelope widths and the faces at each end of each
  frame axis, the datum faces and each datum's feature (the first that claims
  its face, which the drawing records the letter on, so a re-plan that reads the
  letters keeps what the first plan kept), holes and patterns (and so their
  locations), every feature the user has made a choice about, and every feature
  the drawing's own dimensions name (`orchestrate.run(named=...)`, which the
  editor fills from the dimensions the user added, moved, overrode or removed,
  so a re-plan never leaves them to the model);
- then the other features and the planar faces no feature claims, larger first,
  while the count keeps within the budget; past the first that does not fit only
  what brings no dimension of its own, and the walk is made again while one keeps
  something (a width kept late can join two nodes and free a location);
- a feature's size is the area of the faces that state or place it (a pocket's
  floor, a width's pair, every face of the others), a face several features share
  split between them; a pocket's walls are faces of their own, since they include
  whatever stands on its floor (ribs, bosses, the walls of embossed letters);
- a pocket is kept or left whole, with the gap widths across it: between two of
  its walls and spanning half its floor or more (`keep.ACROSS`), not the gap
  between two letters standing on it;
- what is left goes in `FeatureSet.model_defined` (features, which `of_type`
  skips) and in `unclaimed` with the reason `model_defined` (their faces, which
  are no positions); coverage counts them, so the model-governs note and
  `COV.unclaimed` follow as on any reduced-dimension drawing.

The count is the full plan's as drawn, not its requirements: a need only if the
full plan stated it, a location for each node of the kept graph holding a
position the full plan located (but the origin's), and the datum symbols it drew.
On the corpus sample it matches the trimmed plan to the dimension. After layout,
`keep.crowded` (more than three overlaps or unplaceable items, and a twentieth of
the dimensions or more) lays the drawing out once more with `keep.SHRINK` (three
fifths) of its dimensions, and keeps that layout when it collides less. It does so
only while both time bounds have at least as much left as was spent (the plan
stage's from its start, the layouts' from the first), since fewer dimensions
cost less, so that the retry keeps within both.

## Checks the planner reports

The plan's `graphs` hold one verdict per frame axis (`linear/x`), one per
circular pattern (`angular/f-21`), and `views` listing requirements no kept view
can draw. More requirements than `DrawingLimits.requirements` raise
`limit_exceeded`.

## Tests

`tests/test_drawing_plan.py` runs on hand-made feature sets and views
(`tests/drawing_plan_fixtures.py`) of the synthetic plates, so it needs neither
feature recognition nor the views: positions, links and origins; holes in line; the
baseline tree from the datums; the checker's words and loops; patterns' pitch,
pitch circle and angle; a depth no view shows; the view set and the front; every
callout form; frames by scheme; inch precision; printed nominals; bands and the
rounding guard; title fields and notes; the tolerance block; ordinate switching;
the requirement bound; determinism.

`tests/test_drawing_keep.py` runs the pockets plate (`drawing_parts.pockets_plate`,
six pockets of falling size and four corner holes) with a small budget: the
overall size, datums and holes kept, the larger pockets kept and the smaller left,
the note, coverage and `COV.unclaimed`; the count against the trimmed plan; a
feature left neither stated nor located; a pocket the user's own distance names
kept through a re-plan; the layout retry, kept only when it
collides less. The letters plate (`drawing_parts.letters_plate`, four pockets
0.5 mm deep in a row, given a font's free-form walls in the test) is lettering:
its pockets and the widths across them are left to the model and their depth is
one dimension, `4X` on a note; with plain walls they are pockets.
