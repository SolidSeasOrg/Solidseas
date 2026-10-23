# The automated checklist

`solidseas.drawing.checks` (`docs/DRAWINGS.md` 20.1, 19.5 check 5), built in the
integration stage. Provisional until the first release that makes drawings.

```python
from solidseas.drawing import checks, orchestrate

done = orchestrate.run(source, model, features, views, options, settings, fields)
found = checks.run_checks(drawing, planned=done.planned, layout=done.result)  # a live run
found = checks.run_checks(drawing)                                             # the file alone
found = checks.run_checks(drawing, release=True)                               # release-time levels
```

- `run_checks(drawing, *, planned=None, layout=None, release=False)` returns a
  tuple of `Check(code, level, message, item, fixes)`, in a fixed order: by code,
  then item, then message, the numbers in ids compared as numbers (`d-2` before
  `d-10`). The pipeline reaches it as `pipeline.ENTRY_POINTS["checks"]`.
- `level` is `error`, `warning` or `information`. `item` names the dimension,
  feature, view, title field or note a check is about, or the code itself when it
  is about the drawing. `message` is in words a drafter reads and `fixes` are the
  editor's remedies in words, in the style of 10.12: "the Ø6.60 hole is not
  located along X" with Restore and Add; "d-98 ([12]) closes a loop with [12]"
  with Make Reference, Remove the Other and Link Instead.
- `CODES` lists every id of the 20.1 table with its severity there and whether
  the file alone answers it; `MODEL_ONLY` the ids only a live run answers;
  `skipped(planned=...)` the ids a call cannot answer; `LAYOUT_CODES` where the
  layout's own checks go. `release.release_problems(drawing, checks=...)` and
  `release.release(...)` read the result as they read any checks (`level`,
  `code`, `item`, `message`).
- What the table says of machined parts holds for turned parts too
  (`types.MACHINING`): a turned part is machined on a lathe.

## Two modes

**Live**, with the plan stage's `Planned` and `LayoutResult`: every check runs.
The checks that need the model read the plan's detail: the linear graphs and
the requirements (R4), the views' specifications and their witnesses (R1.aligned,
R5, R4.coincident, R18.datums), the features (R4.members, R5, R7.callouts) and
the location edges (R13.scheme). Each drawing dimension is matched to its planned
one by id and key (`new_drawing` numbers them in planning order); a user's
location dimension the plan does not know is matched to the graph's positions by
value. The layout's own checks are kept under the ids they belong to:

| Layout check | Id | Level |
|---|---|---|
| `L.overlap` (text over text, text over a frame) | R11.collisions | error |
| `L.placement` (placed with a conflict) | R11.collisions | error |
| `L.outside` (outside the border) | R8.sheet | error |
| `L.reserved` (in the title, revision or notes block) | R8.sheet | error |
| `L.leader` (outside 15 to 75 degrees) | R11.leaders | warning |
| `L.cramped` (Add Detail View) | R12.views | warning |
| `L.characters` (a character the font lacks) | R10.text | error |

A layout check this list does not know yet is kept under its own code and level,
never dropped.

**The file alone** (a `.ssdrw` read from disk, no model): the checks the file can
answer run on its records and its laid-out sheet, and the ids in `MODEL_ONLY`
(R1.aligned, R4.complete, R4.redundant, R4.members, R4.coincident, R5.visible,
R5.true_shape, R13.scheme) are skipped. Nothing is reported for a skipped check
and nothing is guessed; a caller that wants to say what was not checked reads
`skipped()`. Where the layout's checks are not at hand, the painted layer stands
in for them: text over text and over a frame's box, text outside the border or
in the title or revision block, and leader angles are measured from the painted
items. A drawing with no sheet at all gets one R8.sheet error and the record
checks.

## What each check looks at

Levels are the table's unless the row says otherwise. "File alone" says what the
file-only mode does without the model.

| Id | Looks at | Level | File alone |
|---|---|---|---|
| R1.aligned | each projected view's placement against its parent's: the shared sheet axis within 0.01 mm, the same scale, on the side the drawing's projection angle puts it (third angle for ASME, first for ISO, or as Drawing Settings choose) | error | skipped |
| R1.scale | the title block's SCALE against the sheet's scale; each orthographic view's scale, or a label that states its own | error | the title block only (which view is the isometric or a detail is the plan's to say) |
| R1.symbol | the projection symbol: present, once, of the drawing's projection angle | error | runs |
| R2.units | the units statement: present, once (the tolerance block and the notes), naming the drawing's unit | error | runs |
| R2.format | each shown value as painted: leading zeros by unit, decimals equal to the precision under the block, basic boxed with no tolerance, references in parentheses, angles with the degree sign, ±, deviations and limits by 10.8 | error | runs |
| R2.rounding | each value toleranced by the block or an explicit band: how far the value as shown is from the record's model value, as a share of the band; the message says whether the model value lies inside the band | warning above 10 %, error above 50 % | runs |
| R2.override | each record whose text override holds a number other than the measured value rounded to the override's places, or no number at all | error; information once the drawing records it as accepted | runs |
| R3.tolerance | each shown dimension has a known source of tolerance and a precision the block has a row for; the tolerance block gives the decimal rows and angles (machined) or points at a note (printed), and names Y14.5 | error | runs |
| R3.block | a block-toleranced value with more places than the block's last row | error | runs |
| R3.basic | each basic dimension governed by a frame on its feature or by the general profile note | error | runs |
| R3.roles | the dimensions whose precision comes from their role, counted by band | information until CHECKED is signed | runs |
| R4.complete | every graph node reached from the origin by the shown, toleranced locations; every size, callout, depth, radius and angle requirement stated by a shown dimension | error | skipped |
| R4.redundant | a location that joins nodes already joined (named with the loop it closes) or positions a size already joins; a requirement key stated twice | error | skipped |
| R4.members | a pattern's callout count against its members, a pitch's or an arc's step's count against its spaces, and each pattern located through its pitch, its pitch circle or an arc's step | error | skipped |
| R4.coincident | a location whose merged position meets more than one separate visible run in its view, with no count | error | skipped |
| R5.visible | each linear, ordinate and datum dimension's positions have a witness in its view; a hole's size is in a view that sees it open | error | skipped |
| R5.true_shape | a linear dimension along an axis its view foreshortens; a hole's size outside its circular view; a radius, angle or chamfer outside the view that shows it in true shape; Ø above 180 degrees of cover, R at or below | error | skipped |
| R6.title | company, title, drawing and part number, revision (and that it is the drawing's), size, scale, sheet, STATUS (and that it is the drawing's), MODEL (with the model's short hash, which its cell on the sheet shows whole), DRAWN with a date, material, finish, the tolerance block | error | runs (from the title records when there is no sheet) |
| R6.material | a heat-treatable material whose heat treatment is not said; a material the list gives no specification; a typed material not in the list | heat treatment: warning, error at release; the other two: warning | runs |
| R6.signatures | each row the Settings require is signed and its digest is the current content's; one person on two rows | unsigned: information, error at release; stale: warning, error at release; one person twice: warning or error as the Settings say | runs |
| R7.callouts | each hole callout: the count and Ø, THRU or a depth first, THRU only for a hole that goes through, the lines in manufacturing order, a thread only when confirmed and a confirmed thread present, no TYP; an `into_bore` end confirmed | error | runs; the ends come from the model, so `into_bore` and, for features recognised without a `through` in their descriptor, THRU are skipped |
| R8.sheet | the sheet size and orientation, the border's margin and zones, the title block in the lower right and the revision block in the upper right; text outside the border or in a block; each sheet of a drawing of several the first's size, with a title block saying SHEET n OF m and naming the first's drawing number and revision | error | runs |
| R9.lines | each geometry stroke's width and dashes against its style (thick 0.6, thin 0.3, 2:1); annotation strokes thin; a centre mark on every full circle | warning | runs |
| R10.text | lettering on the dimension and note layers at or above the unit's dimension height; view labels larger; the drawing number and title at least that height; capitals (µm and µin kept); no squeezed text; characters the font lacks | error | runs, except characters the font lacks (the painted layer shows them as `?`) |
| R11.collisions | text over text and over a frame; items placed with a conflict | error | the painted layer, as above |
| R11.spacing | each linear dimension's line at least 10 mm from its view and 6 mm from an overlapping row | warning | runs |
| R11.leaders | leaders at 15 to 75 degrees | warning | the painted layer: a line and its 3 mm horizontal shoulder |
| R12.views | section and detail labels (SECTION A-A, DETAIL B), letters without I, O, Q or X, never reused; a principal view labelled; a view with no dimension; a section beside the view it replaces; cramped features; an isometric left off for want of room, as information with the fixes Move to Its Own Sheet and Remove the View (on a sheet of its own already: Sheet and Scale). Views and labels are read on every sheet | warning | labels and letters only |
| R13.scheme | a location measured from another feature rather than the datum; a baseline band the layout found too deep, or with more locations than the ordinate tracks | warning | skipped |
| R13.plusminus | locations toleranced plus and minus; a turned part's shoulders and ends placed from its datum end face are left alone under the datum scheme, where they are toleranced on purpose ([turned.md](turned.md)) | warning, information on printed parts | runs |
| R14.notes | the fillet note's radius against the most common one; chamfers as leg X angle or two legs; the edge break note on machined parts; TYP in a note or dimension | warning | runs, except the fillet radius |
| R15.process | the type's fixed notes from the Settings' templates; a printed part's process note and the block pointing at it; the build-direction arrow on each view with Z dimensions (and on the isometric, live); a machined block that points at a note; the model-governs note on a reduced-dimension drawing, with the model's part number, revision and short hash, the precedence words and its profile frame | error | runs, except the arrow on the isometric |
| R18.datums | every datum a frame refers to defined once, with its symbol shown and on the sheet, on a face its view shows as a visible line | error | runs, except the visible line |
| R18.frames | frame grammar: a known characteristic, a positive zone, Ø and a material condition only where they apply, datums never, optional or required as the characteristic says, at most three, each once, capital letters | error | runs |
| COV.unclaimed | unclaimed geometry, counted with its reasons | warning, error at release; information once the drawing records it as accepted | runs: the counts when the drawing holds them, else the model-governs note's presence (a file does not keep the counts) |
| REL.stamp | an unreleased sheet carries the PRELIMINARY stamp, its exports would be named PRELIMINARY, and no recorded unreleased export is named otherwise | error | runs |
| ASM.parts | an assembly's sheet has its parts list | error | runs |
| ASM.balloons | every item of an assembly's parts list has a balloon on the sheet (a warning); a balloon names an item of the list (an error) | warning | runs |

An assembly's drawing ([assemblies.md](assemblies.md)) has no dimensions: the
checks of a part's dimensions, tolerances, material, notes, process, coverage and
schemes (R2.units, the R3 checks, R4.complete, R4.redundant, R4.members,
R4.coincident, R6.material, R13.scheme, R13.plusminus, R14.notes, R15.process
and COV.unclaimed) do not run on it, R6.title asks it for no material or finish,
and R12.views asks no view of it to carry a dimension. ASM.parts and
ASM.balloons are its own.

## Choices made here

These follow from the design and the code it meets; each is for the VM to
confirm or change.

- **An unmapped material is a warning, even at release.** Release refuses it
  itself until it is mapped or accepted as typed (13.2, `accepted["material"]`),
  and `release.ACCEPTABLE` does not hold R6.material, so as an error here no
  typed reason could accept it. Adding R6.material to `ACCEPTABLE` would let this
  check carry it at error level with the item `material`.
- **A material entry without a specification is a warning.** The default
  printed materials have none, and a drawing's settings are a snapshot that
  Drawing Settings do not change afterwards.
- **The model-governs note is checked under R15.process**, not COV.unclaimed, so
  the typed reason that accepts unclaimed geometry at release never accepts a
  missing or partial note.
- **The title block's STATUS is the drawing's.** Signing does not lay the sheet
  out again, so the editor lays it out with the new status and signed rows after
  Sign; until then R6.title says the STATUS is stale.
- **Stacked tolerances count as lettering** and are held to the 3 mm minimum,
  as Y14.2 is publicly summarised for tolerances and limits (verify). The letters
  inside a symbol (the spotface's SF, the M and L of the material modifiers) are
  part of the symbol and are not.
- **The isometric is not held to the sheet's scale** (C25 puts it at full scale
  or smaller); a detail view is, unless its label states its scale.
- **R11.spacing measures the first row and the row spacing**, from a view box of
  its geometry and centre marks, never larger than the box layout banded from.
  Extension line gaps and overruns are the painter's constants
  (`standards.DIMENSIONS`) and are not measured again.
- **An `into_bore` end is confirmed** by any of the decisions in `END_DECISIONS`
  (`end`, `into_bore`, `into_bore_note`) on the hole or its pattern, until the
  editor's `confirm_end` names its key.

## What it found at integration, and where each went

**Measured** on the VM when integration began, with the synthetic parts through
the real features and views stages and on the o11 fixture made with
`make_drawing`. Each is now fixed, or held as a golden's open finding
(`goldens.md`):

- **Notes lettered small.** Every drawing's notes were lettered at 0.9 of the
  dimension height (2.7 mm, 2.74 mm on inch drawings), below the 3 mm of 22 rule
  10. Fixed: the notes are lettered at full height.
- **The model-governs note's frame** overlapped its last line (`L.overlap`) on a
  reduced-dimension drawing. Fixed: the frame is placed after the continuation
  line's indent.
- **`hole_kinds`:** a callout the layout could not place clear (`L.placement`).
  No longer reported.
- **`printed_bracket`:** no build-direction arrow, and nothing said. Fixed: the
  arrow is tried at more places, and one that cannot be placed is reported.
- **`angled_round` and `inclined_hole`:** the angled face's angle is not stated
  (R4.complete). Fixed: the recogniser gave the face's meet line with an end face
  square to it; it now takes the neighbour the face is angled from, and the plan
  states the angle and locates the line (`goldens.md`, closed in the viewer
  stage).
- **The model-governs note** names the model by its file name as it is, which
  R10.text reports when it is in lower case. Open: the inclined-face golden's
  finding, for the review.
- **A drawing saved and read again** lost the features' descriptor types and the
  tolerance `derived`. Fixed in the file reader.
- **A long title or drawing number** was set below the lettering minimum to fit
  its cell, and R10.text blocked release. Fixed: a title goes on two lines, and a
  long number takes the CAGE cell's width when the company has no CAGE code
  (`layout.md`). A number too long even then is reported, with Set Sheet among the
  fixes.

**Speed (measured):** the 100-hole plate of `tests/test_drawing_layout.py` (210
dimensions, 1252 painted items) checks in about 6 ms live and 5 ms from the
file; the synthetic parts in 1 to 2 ms.

## Tests

`tests/test_drawing_checks.py`: the ids and severities against the 20.1 table in
`docs/DRAWINGS.md`; each id fires on a case built to break it (a placement moved,
a symbol taken off, a value overridden, a location removed, a loop closed, a
callout reordered, a witness split...) and a good drawing, signed and laid out
again, has nothing to say live or from its file; the layout's checks under their
ids; the file-only mode answering no model check; release-time levels; Release
blocked by unaccepted unclaimed geometry and passing with a typed reason, and not
passing a missing model-governs note; the fixed order; the o11 fixture; and the
100-hole plate under 0.3 s.
