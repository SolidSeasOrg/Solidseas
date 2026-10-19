# Drawings

The viewer makes a drawing of a SOLIDWORKS part: its views, datum-referenced
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
dimensions ([assemblies.md](../drawings/assemblies.md)). SOLIDWORKS drawings,
files of other formats and parts stored inside an assembly cannot be drawn yet;
the entry is off and says why.

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
- **Guided** will walk you through the drawing a step at a time. It is shown as
  coming soon.
- **Expert** opens the New Drawing wizard below, with every option.

Tick **Remember my choice** to skip the question next time. You can change it,
or go back to being asked, under Settings > Drawings, "When Drawing is
pressed". An Express drawing keeps being an Express drawing when you use
Update from Model.

## The New Drawing wizard

The wizard asks for:

- the part: its configuration, bodies and, when the part states none, its unit;
- the title block;
- how it is made (machined or 3D printed);
- the views and sheet;
- the dimensions and holes;
- the files to write.

The sheet is previewed beside the pages. **Finish** writes the drawing file and
the PDF and DXF you tick, next to the part or to the folder Drawing Settings
name. A file SolidSeas did not write is never replaced: a taken name gets
" (2)".

## Editing a drawing

**File > Open Drawing...** opens a `.ssdrw` in a window of its own: the sheet,
the dimensions by view, Properties, and the checklist with its fixes.

- Drag a dimension to move it, or untick it to take it off the sheet.
- Add one between features you pick.
- Change its precision, tolerance or text.
- Undo and Redo hold every edit.

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

## From the command line

```bash
solidseas drawing new bracket.SLDPRT --out DIR --pdf --dxf
```

makes the same drawing from the command line ([cli.md](../drawings/cli.md)).
The drawing work runs in a process of its own, so the window keeps answering
while a large part is drawn.
