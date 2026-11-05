# Drawings

The viewer makes a drawing of a part (a SOLIDWORKS part, or a STEP, Parasolid or
Alibre Design one): its views, datum-referenced
dimensions, hole callouts, notes and title block, as a SolidSeas drawing file
(`.ssdrw`) with a PDF and a DXF. Drawings are experimental, and everything
about them is provisional until the first release that makes them. Check every
drawing before you use it: until a drawing is released, its PDF and DXF carry
the PRELIMINARY stamp. They are switched on by default; turn them off under
Settings > Drawings.

This page is the user's side. [DRAWINGS.md](../DRAWINGS.md) is the
specification, and [the drawings pages](../drawings/README.md) describe what is
built, including [the viewer's entries](../drawings/viewer.md) and
[the command line](../drawings/cli.md).

## Making a drawing

- **File > New Drawing...** (Ctrl+D, or the Drawing button beside 3D Print)
  draws the part or assembly shown.
- **Make Drawing of NAME...** follows every 3D Print entry in the right-click
  menus and draws what that entry would print.

An assembly's drawing has its views, a parts list on the title block giving
each item's own drawing number, and an item balloon on each part, and no
dimensions ([assemblies.md](../drawings/assemblies.md)). A parts list too long
for the first sheet goes on to more sheets of the same size, each with the list's
headings and a short title block giving the drawing number, revision, size and
scale, and every title block says which sheet it is (SHEET 2 OF 3). The PDF then
has a page for each sheet, and the DXF has the sheets side by side.

Parts saved as STEP (`.step`, `.stp`), Parasolid (`.x_t`, `.x_b`) or Alibre Design
(`.AD_PRT`) files are drawn as SOLIDWORKS parts are. Such a file has no
configurations. A Parasolid file never says which unit its part was designed in,
so SolidSeas guesses it from the part's sizes and asks you to confirm it, as it
does for a SOLIDWORKS part that states no unit. SOLIDWORKS drawings, assemblies
saved in those formats, mesh files (STL, 3MF and the like) and parts stored inside
an assembly cannot be drawn yet; the entry is off and says why.

## Express, Guided and Expert

When you press Drawing, SolidSeas asks how you would like to make it:

- **Express**: a simple drawing with the key sizes, straight to the editor. It
  asks no questions. You get the views the part needs and an isometric, the
  overall length, width and height, each hole by size (with a count such as 4X
  for a pattern), and where the holes are: measured from the part's edges, or a
  pitch circle for a bolt pattern. There are no tolerances beyond the title
  block's general ones, no GD&T, and no chamfer, fillet or other small feature
  sizes. The title block is filled from what is known: the part number,
  description and material from the part's properties, the finish NONE when the
  part names none, the first person in Drawing Settings > People as the person
  who drew it, today's date and the scale. A note says the model defines what is
  not dimensioned. Use it to show a customer the size of a part and where its
  holes go. The drawing file is written next to the part (or in your Drawing
  Settings folder) and opens in the editor, where you can export the PDF and
  DXF, add dimensions, or fill in anything left empty. An assembly's Express
  drawing has its overall size, its views and its parts list with balloons.
- **Guided**: a few plain questions, one at a time, each with a sentence on
  why it matters. The preview beside the questions shows the drawing as your
  answers shape it. See [Guided drawings](#guided-drawings) below.
- **Expert** opens the New Drawing wizard below, with every option.

Tick **Remember my choice** to skip the question next time. You can change it,
or go back to being asked, under Settings > Drawings, "When Drawing is
pressed". An Express drawing keeps being an Express drawing when you use
Update from Model.

## Guided drawings

Guided asks, in this order:

1. **What is the drawing for?** To show a customer or get a quote, you get the
   overall size and the holes. To have it 3D printed, you get the same key
   sizes with the tolerances of the printing process you pick from Drawing
   Settings > Printing. To have it made from plain sizes, every feature is sized
   and located with plus and minus tolerances. To have it machined in a shop,
   you get the complete drawing, with datums and GD&T, checked to define the
   part fully. The answer starts at your usual level from Drawing Settings.
2. **Which views should the sheet show?** The front is always drawn. Tick the
   top, the sides, the bottom, the back and the isometric (a 3D picture) as you
   need them. They start as your Default Views.
3. **Which unit should the sizes be in?** It starts at the unit the part is
   modelled in, or the one Drawing Settings use for every drawing. A part that
   does not say gets SolidSeas' guess, with the reason, when the guess is clear;
   otherwise you choose.
4. **How much should the drawing dimension?** The first answer chose this;
   change it here if you need more or fewer sizes.
5. **Are any of these holes threaded?** Asked only when the part has holes the
   size of a tap drill, which may be meant to take a screw. Each is listed with
   its size, and you choose "No, a plain hole" or the thread it is tapped to,
   such as M6 x 1. The drawing calls out a thread only when you choose one, and
   a thread cannot be added in the editor later, so check with whoever designed
   the part if you are not sure. If the preview is still being made, the page
   waits for it.
6. **What should the title block say?** The same title block fields as the
   wizard. Leave one empty to use the part's own value.
7. **Ready to make the drawing.** What will be made, including any threaded
   holes, the title block as the preview shows it, and where the files go, with
   a button to choose another folder. A PDF is saved beside the drawing unless
   you untick it, and a DXF if you tick it. **Finish** saves them and opens the
   drawing in the editor.

An assembly is asked only about its views, unit and title block: its drawing
has its views, a parts list and balloons. Guided leaves the rest (hidden lines,
the sheet, the scale) to your Drawing Settings. A threaded hole's callout gives
no depth; use Expert to give one.

Only one drawing can be set up at a time. If you start another while Guided is
open, SolidSeas brings it forward and says a Guided drawing is already open.

## The New Drawing wizard

The wizard asks for:

- the part: its configuration, bodies and, when the part states none, its unit;
- the title block;
- how it is made (machined, 3D printed or turned on a lathe);
- the views and sheet;
- the dimensions and holes;
- the files to write.

The sheet is previewed beside the pages. When the drawing has more than one
sheet, **Previous Sheet** and **Next Sheet** under the preview (or Ctrl+Page Up
and Ctrl+Page Down) show the others. **Finish** writes the drawing file and
the PDF and DXF you tick, next to the part or to the folder Drawing Settings
name. A file SolidSeas did not write is never replaced: a taken name gets
" (2)".

### Turned parts

When the preview finds that the part is turned (its round faces share one axis and
its flat faces are square to it, or nearly all of it is so), the wizard suggests
**Turned (lathe)** and says why. A turned part's drawing shows its profile with the
axis across the sheet and the larger end on the left. Each diameter is dimensioned
across the outline, equal diameters once with their count (2X), and the shoulders
are measured from the end face at the larger end. Datum A is the longest diameter
and datum B that end face; under datum-referenced tolerancing every other diameter
carries a circular runout to A, with the value on Drawing Settings' GD&T page. A
turned part uses the machined entries of Drawing Settings, so its notes are those
under "Machined and turned parts". Choosing another diameter for A, half sections of
bores, keyseats, flats and tapers are not offered yet; a taper is left to the model,
and the drawing says so.

## Editing a drawing

**File > Open Drawing...** opens a `.ssdrw` in a window of its own: the sheet,
the dimensions by view, Properties, and the checklist with its fixes.

- Drag a dimension to move it, or untick it to take it off the sheet.
- Add one between features you pick.
- Change its precision, tolerance or text.
- Undo and Redo hold every edit.
- On a drawing of more than one sheet, **Drawing > Next Sheet** and **Previous
  Sheet** (Ctrl+Page Down and Ctrl+Page Up) page through them, and the status
  bar says which one you are looking at. You make your edits on the first
  sheet; choosing a dimension or a note takes you back to it.
- **Drawing > Isometric on Its Own Sheet** moves the isometric view to a second
  sheet, at the drawing's scale or smaller to fit, and back again. On an
  assembly its balloons go with it. When the isometric has no room on the
  sheet, the checklist says so and offers the same move.

**The model:** the status bar says whether the part has changed. A changed part
leaves the drawing view-only until **Update Drawing**, which keeps your edits and
says what changed. **Find...** points a drawing at a part that moved.

## Signing, releasing and revising

- **Sign...** records who checked and approved it.
- **Release...** writes the released PDF and DXF as new files. A released
  drawing is read-only until **Start Revision**, and exports of a released
  drawing are never replaced.
- **Email PDF** offers only the PDF, never the drawing file.

## Drawing Settings

**Settings > Drawing Settings...** holds your company and logo, the people who
sign, the standard and units, the sheets, the tolerance block, the notes, the
materials, where files go and how Email PDF sends. The first drawing asks for
what only you can answer. The pages sit under Drawings in the
[Settings window](settings.md).

**Standard and Units** chooses ASME (the default) or ISO, and the projection:
as the standard says (third angle for ASME, first angle for ISO), or first or
third angle whichever standard you use. An ISO drawing places its views in first
angle, shows the first-angle symbol and says TOLERANCING ISO 8015 in its
tolerance block. Its sheets, title block, lettering and tolerance notes still
follow the ASME layout; the ISO forms of those come later.

**Tolerances** holds the inch and millimetre tolerance blocks your drawings
use. Millimetre General Tolerance is shown greyed out: millimetre drawings use
the millimetre block for now, and an ISO 2768 class will be offered there once
drawings apply it.

## From the command line

```bash
solidseas drawing new bracket.SLDPRT --out DIR --pdf --dxf
```

makes the same drawing from the command line ([cli.md](../drawings/cli.md)).
The drawing work runs in a process of its own, so the window keeps answering
while a large part is drawn.
