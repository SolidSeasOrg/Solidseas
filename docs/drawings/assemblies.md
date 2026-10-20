# Assembly drawings

A drawing of a SOLIDWORKS assembly has its views, a parts list (the bill of
materials as a table, each item with the number of its own drawing), an item
balloon on each part the list names, the title block and the revision block,
written as the same `.ssdrw`, PDF and DXF as a part's drawing. It has no
dimensions: it references its components, whose own drawings carry theirs. `docs/DRAWINGS.md` puts assemblies in
stage 4; this page says what is built ahead of it.

`solidseas drawing new frame.SLDASM --out DIR --pdf --dxf` makes one, and so do
File > New Drawing... and every Make Drawing entry of the viewer on an assembly
of its own file (a sub-assembly's row of the Components tab included).

| Module | Holds |
|---|---|
| `drawing/assembly.py` | `open_assembly`: what an assembly drawing is made from; `PlacedBody`, `AssemblyInstance`, `AssemblyContents`; `assembly_options`; `is_assembly` |
| `drawing/facegraph.py` | `place`: a part's model where an instance puts it; `from_bodies` taking placed bodies; `placed_box` |
| `drawing/plan/assembly.py` | the plan: views, title fields, the parts list's lines and the balloons |
| `drawing/layout/partslist.py` | the parts list and the balloons on the sheet |
| `drawing/types.py` | `BomLine` and `Balloon`, and the plan's `bom` and `balloons` |
| `drawing/display.py` | the sheet's `PartsList` and `Balloon` annotations (compact tags `parts` and `balloon`) |

## What is read

`open_source` hands an assembly (a `.SLDASM` path, or an open assembly
document) to `assembly.open_assembly`, which reads one configuration:

- **The instances**, each placed in the assembly's frame, as the viewer's 3D view
  and the STEP export place them: `solidseas.geometry.display_geometry` with the
  sources `nested`, `file` and `brep`, so each part is read from its own file,
  found by reference resolution, or from the document a virtual part is stored
  in. Resolution searches the assembly's own folder, as SOLIDWORKS does; inside
  `assembly.searching(folders)` it searches those folders first, and the
  assembly's folder as well when none of them holds it. The viewer's drawing
  process passes the folder the window has open with every request, so an
  assembly opened from a project folder finds parts kept elsewhere in it, as 3D
  Print and the 3D view find them.
- **Each part's bodies**, read once for each file and configuration used however
  many instances use it: the solid bodies SOLIDWORKS shows. Each instance gets a
  `PlacedBody` per body, named `INSTANCE/BODY` (`o02_boxA-1/Config-0/body1`).
- **The bill of materials**, top level only, SOLIDWORKS' default
  (`solidseas.bom.build_bom`, with the resolution the instances were found by):
  each row's item, PART NUMBER, DESCRIPTION and QTY., and the instances it stands
  for. A part inside a sub-assembly is counted in the sub-assembly's line.

The source has format `sldasm`, the assembly's own name, units, properties, file
hash and properties digest, and no material. Its geometry digest covers each
drawn instance's id, its part's face signatures and its placement, so moving a
component or changing a part changes it.

**What is left out**, with the reason in the warnings (`INSTANCE is not drawn:
...`), the first 20 by name: an instance `display_geometry` skips (its file not
found, a cycle, a limit), one whose part stores no solid body for the
configuration it uses (o16's o06 in OracleAlt), and one placed scaled or sheared.
A mirrored instance is drawn. When nothing can be drawn the assembly is refused
with `not_implemented`, rule `no_instances`, naming the first three. An instance
excluded from the bill of materials is drawn and gets no balloon.

**`bodies`** (the option) names what to draw by instance id or by body name;
none named is every instance.

**Limits.** `DrawingLimits.instances` (1,000, at most 10,000) bounds the
instances read. A part's bodies count once against `bodies`; their faces and
edges count for every instance, since every instance is drawn.

## The model

`facegraph.from_bodies` takes placed bodies: each part body is tessellated once,
at the chord of the whole assembly (its quality's share of the assembly's
diagonal, from the parts' boxes placed), and `facegraph.place` moves the model
for every instance: points, normals, every surface and curve, boxes and
vertices, with the face and edge signatures and the axis groups worked out again
in the assembly's frame. A mirrored placement keeps each face's outward normal,
reverses the triangles' winding and turns each circle's and ellipse's normal
round, so (u, v) and curve parameters still name the same points. The merged
model's body `k` is placed body `k`, which the views' runs carry, so a visible
edge on the sheet is known to belong to its instance.

## Options, features and views

`assembly_options` fills what the user left to SolidSeas with the assembly's
defaults: the front, top and right views and the isometric, hidden lines off,
and the front seen from the assembly's own front (+Z, SOLIDWORKS' Front view).
What the user chose stays. There are no features: the features stage gives an
empty `FeatureSet`. The views stage draws the views as for a part; the plan adds the
hidden lines of a part hidden behind others (below).

## The plan

`plan.assembly.make_plan`, which the plan stage calls for an assembly:

- the views as drawn, all kept;
- the assembly's overall size (`plan.assembly.overall_size`): its length, width
  and height along the frame's axes, from the extent of every placed body, each
  a reference dimension (in parentheses, role `envelope`) in a view that shows
  both its ends as lines, the main view first. When an end is on a curved face,
  so no straight line ends there in any view, the size is stated whole in a
  note instead, `OVERALL SIZE (REF): 220.0 X 241.4 X 60.0`;
- no other dimensions, no datums and no tolerance block;
- the title fields as a part's, from the assembly's properties and what was
  typed: an assembly's title block has no material or finish of its own;
- the parts list's lines (`plan.bom`), each with the number of the item's own
  drawing (`plan.assembly.drawing_number`), as SolidSeas numbers a drawing of
  that part or sub-assembly: its property among Drawing Settings' drawing number
  names (`title_sources.number`: DwgNo, Drawing Number, DrawingNo, Number), else
  its file name without the extension. A component stored inside the assembly (a
  virtual or embedded one) has no file, so no drawing, of its own, and none is
  given;
- a balloon for each line (`plan.balloons`). It goes in the first view, in this
  order, where one of its instances shows a visible edge: the isometric, the
  front, then the other views; the other views that show it are kept in order
  (`Balloon.others`), for a layout that leaves the first out (an isometric with
  no room). Its leader ends at the middle of a visible run of the line's
  instances: of the runs at least a quarter as long as the instance's longest,
  the one nearest the view's outline going out from the view's centre, so the
  leader is short and the leaders fan out;
- a part hidden behind others (`plan.assembly.show_hidden`): a line drawn in some
  view none of whose instances shows a visible run in any (on the corpus, 11 of
  295 items, each inside another instance's box) has its instances' hidden lines
  drawn, dashed on the hidden layer, in every view that draws no hidden lines of
  its own; the isometric draws none. Only those instances go through the
  hidden-line engine again (`views.with_hidden`), and a hidden run lying along a
  line the view already draws is left out, as in a view drawn whole with hidden
  lines on. Its balloon then goes as above on those hidden runs: in the front,
  then the other views, its leader's arrowhead on the middle of a dashed line, as
  a drafter points at a part seen only through hidden lines. The views stage
  itself is unchanged, so a drawing with no hidden part draws no hidden line and
  is the same as before;
- a line none of whose instances shows a run at all, visible or hidden, gets no
  balloon, and the plan says so. A line none of whose instances is drawn at all
  (hidden in the assembly, its file not found, no solid bodies) is named in one
  note, `ITEMS 3, 7 NOT SHOWN`, and the check `ASM.balloons` says it as
  information rather than as a warning; one drawn with no edge in any view stays a
  warning.

## The layout

**The parts list** stands on the title block, its right edge the title block's,
as ASME Y14.34 places a parts list on the field of a drawing: the column
headings at the bottom, next to the title block, and the items above them from
1 upward. Its columns are ITEM, PART NO., DWG NO., DESCRIPTION and QTY.: SOLIDWORKS' default
BOM table's, their headings shortened to fit an A sheet's title block, with the
drawing number after the part number, so the reader goes from an item to its
own drawing. It is lettered at the notes' height, in capitals when Drawing
Settings letter notes so, each row twice the text height. ITEM and QTY. are as
wide as their headings; the others share the rest by what they hold. The list is
as wide as the title block, or wider, growing leftward, when its texts need the
room (up to 1.6 times the title block's width, `partslist.MAX_GROW`); a text too
long even then is cut with an ellipsis. The notes stand above it. The sheet
frame reserves it (`SheetFrame.parts`), so the views keep clear of it and a long
list takes a larger sheet.

**A long parts list** (`partslist.shape`) continues in columns to its left when it
would stand taller than 60% of the field above the title block
(`partslist.PARTS_SHARE`): each column has its own headings at the bottom, the
first stands on the title block and the items go on, column by column,
leftward. As many columns stand side by side as three quarters of the border's
width holds. Each column is a parts list annotation of its own, and the checks
read them all.

**A list longer than those columns hold** goes on to more sheets
(`partslist.continued`, `docs/DRAWINGS.md` 11.7). The first sheet's columns are
filled, and the rest of the list goes on sheets of the same size after it: each
with the title block, the border and the stamps, and the list standing on the
title block as on the first, in as many columns as the border's width holds,
each as tall as the field above the title block and each with its headings, so
a reader picking up any sheet sees what the columns are. The last sheet's
columns share its lines evenly. Every title block says SHEET n OF m, the first
sheet's too. The views, balloons, notes and revision block stay on the first
sheet. A drawing goes to at most `DrawingLimits.sheets` sheets (16), its last
taking every line left; one held to a single sheet (`sheets=1`) stands its
columns taller instead.

**A stacked balloon.** A balloon with no clear place of its own stacks on a balloon
already drawn in its view whose part's point is within 20 mm of its own
(`partslist.stacked_balloon`), as ASME Y14.34 allows for items that sit together:
touching it, beyond it along its leader, or else to one side, with no leader of its
own (its annotation's leader holds only the point on its part). Only when none of
those is clear is it drawn where it does not fit and reported.

**A balloon** is a circle round its item number, at the notes' height, on a
leader ending in an arrowhead on the edge the plan chose (a hidden one for a
part hidden behind others). Views that
carry balloons get room all round for a balloon and the shortest leader, the
isometric too. Each balloon goes outside its view in the direction from the
view's centre through the edge where it can, its leader at 15 to 75 degrees as
every leader is, the circle clear of the views, texts, dimension lines and other
balloons, and the leader crossing no hard item or other leader; a degree away
from straight out counts as a millimetre of leader. A balloon with no clear
place is put at the first place on the sheet and reported (`R11.collisions`),
never left out; one whose views are all off the sheet is reported.

## A parts list of your own

Drawing > Edit Parts List... opens the BOM editor (the one the BOM tab's Edit BOM...
opens) on the assembly's bills of materials: top level only, parts only or
indented; the columns, their order and headings (a DWG NO. column holds each item's
drawing number, and any property of the parts can be a column); rows moved or
hidden; and any cell typed over. Apply makes it the drawing's parts list, as one
step Undo takes back. The lines are numbered as shown and the balloons carry those
numbers; a hidden row has no balloon. The table definition is kept in the
`.ssdrw` options as `parts_list` (written only when set, so other drawings' files
are as before), and Update from Model applies it to the BOM read again, keeping
every edit whose part is still there and reporting the rest
(`solidseas.bomtable`).

## The file and the writers

The drawing's `model.format` is `sldasm`. The sheet carries the `PartsList`
annotation (its box, the headings and each line's cells) and a `Balloon` for
each balloon (its item, circle and leader), with the compact tags `parts` and
`balloon`; a SolidSeas from before them cannot read such a sheet. The PDF, the
DXF and the screen draw the painted layer, so the parts list and balloons are
lines, circles and text in each (the DXF on the `TITLE` and `NOTES` layers).

A drawing whose list goes on to more sheets keeps them in the same `sheet`
member, as the first sheet's `continuation`; a drawing of one sheet is written
exactly as before. The PDF has a page for each sheet, in order. The DXF is one
file with the sheets side by side in model space, left to right, an inch of
paper apart, each with its own border and title block, since model space is what
every DXF reader shows. The SVG writer gives a file for each sheet
(`svg.to_svgs`).

## The checks

An assembly's drawing has no dimensions, so the checks of a part's dimensions,
tolerances, material, notes and process do not run on it: `R2.units`,
`R3.tolerance`, `R3.block`, `R3.basic`, `R3.roles`, `R6.material`,
`R13.plusminus`, `R13.scheme`, `R14.notes`, `R15.process`, `COV.unclaimed` and
the `R4` graphs. `R6.title` asks for no material or finish, and `R12.views` asks
no view to carry a dimension. Its own:

| Id | Says | Level |
|---|---|---|
| `ASM.parts` | the sheet has no parts list (the first sheet always carries its start) | error |
| `ASM.balloons` | an item of the parts list, on any of its sheets, has no balloon (no view on the sheet shows an edge of it, visible or hidden); a balloon names no item of the list (an error) | warning |

## Editing and Update from Model

The edits that are not about dimensions work as for a part: the title fields,
notes, sheet and scale, units, views added and removed, Drawing Settings,
signing, release and revisions. Every one lays the sheet out again with the
parts list and balloons. Update from Model reads the assembly again, its parts
included; a drawing whose assembly and parts are unchanged reports the model
unchanged.

## The command line and the JSON

`drawing new`, `check`, `update`, `export` and `show` take an assembly as a part.
The summary says `PRELIMINARY assembly drawing NUMBER, revision A: 7 items and 6
balloons in 4 views, sheet C at 1:1`, and for a list on more sheets `... in 4
views, 3 A sheets at 1:4`. In `drawing_result` the drawing's
`model.format` is `sldasm` (`sldprt` for a part), `counts.items` and
`counts.balloons` count the parts list's lines (on every sheet) and the
balloons, `counts.sheets` the sheets, and `coverage`
is null, since an assembly has no features to cover.

## The viewer

- **Make Drawing** and **New Drawing** are on for an assembly of its own file,
  a sub-assembly's row included; one stored inside its assembly is refused, as a
  virtual part is.
- **The wizard** reads the assembly on page 1 (the drawing process's probe gives
  its instances in place of bodies, how many items its parts list has and which
  instances are left out); page 2 has no material or finish; pages 3 and 5, how
  a part is made and its dimensions, are skipped; page 4 starts from the
  assembly's views.
- **The editor** shows the sheet; Add Dimension, Remove Dimension, Reset Position
  and Tolerance Block are off, their tooltips saying why. Picking the parts list
  selects nothing to edit. A balloon is dragged to a new place, its leader
  following, as one undoable step (`edit.move_balloon`; `edit.reset_balloon` puts
  it back where layout places it). The drawing keeps where it was put as its
  offset from the point its leader ends on (the `balloons` option, in the file
  only when one was moved), so it follows its part when the views move; one put
  on something, or with its leader outside 15 to 75 degrees, is reported by the
  checks as a balloon layout places would be. A drawing of several sheets is
  paged through with Drawing > Next Sheet and Previous Sheet (Ctrl+Page Down and
  Ctrl+Page Up, also on the toolbar), the status bar saying which sheet is shown;
  edits are made on the first sheet, which a selected dimension, note or view
  brings back.
- **The self-test's dry run** draws an assembly as it draws a part, leaving out
  removing a dimension, and checks that the sheet carries the parts list and a
  balloon.

## Not yet

- A balloon's own edits beyond moving it (a second leader, stacking by hand).
- Exploded views, sections of assemblies.
- Views on a second sheet: only the parts list goes on to more sheets.
- The wizard's preview shows the first sheet alone.
- A reference dimension to the tip of a curved face (the overall size is then a
  note).
