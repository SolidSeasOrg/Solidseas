# The New Drawing wizard

The code this page describes is
`src/solidseas_app/viewer/drawingwizard.py`, tested in
`tests/test_viewer_drawing_wizard.py`. The design is `docs/DRAWINGS.md` section 15.3,
with 7 for the settings it reads and saves, 8.2 and 8.3 for the views, 10.6 for the
manufacturing types, 12.5 and 12.6 for names and folders, and 13.2 for what a new
drawing holds. Everything here is provisional until the first release that makes
drawings.

File > New Drawing... (and Make Drawing... in the right-click menus, wired by
`viewer/drawingaction.py`) opens `DrawingWizard`, a `QWizard` of six pages that
makes a PRELIMINARY drawing of one part and writes it. Nothing is written before
Finish.

## Making one

```python
from solidseas_app.viewer.drawingwizard import DrawingWizard

wizard = DrawingWizard(
    window,              # the parent widget
    worker,              # the window's drawingproc.DrawingWorker, shared and kept open
    "bracket.SLDPRT",    # the part
    configuration=None,  # the configuration drawn; None: the part's active one
    settings=None,       # the loaded DrawingSettings; None: read from settings_path
    settings_path=None,  # Drawing.json; None: the user's
    folder=None,         # the folder the viewer has open (folder_problem's "opened")
)
wizard.drawing_written.connect(open_editor_if_asked)  # (path, open_editor)
wizard.open()
```

`folder` is the folder the user opened in the viewer, as the 3D Print file's rules
take it: a folder on a network share is refused unless it is inside that one. The
wizard never closes the worker: the window owns it, and the editor uses it next.

`drawing_written(path, open_editor)` is emitted once, after the files are written,
with the `.ssdrw`'s path and whether "Open in the editor" was ticked; the wizard
then closes as accepted. `wizard.written` holds what was written (`Written`: the
path, every file in the order written, the words for names that were taken, and the
drawing as saved).

An assembly ([assemblies.md](assemblies.md)) is made the same way: page 1 lists
its part instances in place of bodies (`Instances drawn:`) and says how many items
its parts list has and which instances are left out; page 2 has no material or
finish, which are its parts'; pages 3 and 5, how a part is made and its dimensions,
are skipped (`nextId`); and page 4 starts from the assembly's own views (front, top,
right and the isometric, without hidden lines).

## The pages

1. **Part.** The file, its configuration (a list when the part has several; choosing
   another reads the part again) and its bodies, each with a tick box (the bodies
   ticked are `DrawingOptions.bodies` when they differ from those the part draws).
   The unit: "millimetre, stated in the part"; or, for a part that states none,
   "not stated; looks like inch (41 of 47 sizes are whole thousandths)" with Inch
   and Millimetre buttons, one of which must be clicked before Next is enabled. When
   Drawing Settings fix the unit (Standard and Units), that unit is said and nothing
   is asked, as the command line does. The overall size in millimetres and inches;
   the probe's warnings (rolling-sphere blends left unclaimed, the time a large part
   takes) and Draft quality for a part with more faces than Drawing Settings >
   Limits allow (the views are then drawn coarser). A part SolidSeas refuses (not a
   part, no solid body, over the bounds of 17.1) is refused here with the reason,
   and Next stays disabled. All of it comes from `DrawingWorker.probe`, which reads
   the part's topology without tessellating it.
2. **Title block.** Title, part number, drawing number, revision and model revision;
   an empty field takes the part's own value, shown greyed once the preview has been
   made. Material: typed, or chosen from the Drawing Settings list (sent as the
   entry's model name, so the drawing takes the callout from the list); one the list
   does not map is flagged ("prints as typed, and Release asks you to map it or
   accept it as typed"); a heat-treatable entry asks for its heat treatment, which
   becomes the `heat_treatment` title field the checks look for, and Next waits for
   it. Finish: None until the user picks one, or the part's own finish when it
   states one, so it never holds the drawing up; a finish of the list is sent as
   its callout. Drawn by: a person from People, whose name signs
   DRAWN with today's date. A revision must be a revision mark (A, B, ... without I,
   O, Q, S, X and Z). Checker and approver sign in the editor.
3. **Manufacturing.** Machined (milled), 3D printed or Turned (lathe); Sheet metal
   is shown disabled as "coming later". The suggestion and its reason: 3D printed
   when the material is a printing material in the list, Turned when the preview
   finds the part turned ([turned.md](turned.md); the drawing process's answer says
   why, as `Answer.turned`), else machined. It is taken until the user chooses, also
   when a preview that comes while the page shows finds the part turned. The
   tolerancing scheme (datum-referenced or plus and minus), starting at Drawing
   Settings' scheme for the type; a turned part takes the machined entries of Drawing
   Settings. The page says that datum faces A, B and C are chosen from the largest
   faces and changed by clicking faces on the editor's sheet, not here, in this
   release.
   For a printed part: the process, with its figures as 10.6 gives them and the
   settings' label ("Service bureau figures; replace them with your own."), the
   layer height (the `{layer_height}` of the printed notes), infill and walls,
   supports and post-processing (added to the notes as `INFILL AND WALLS: ...`,
   `SUPPORTS: ...` and `POST-PROCESSING: ...`), and the build direction, the model's
   +Z.
4. **Views and sheet.** The front direction (chosen by SolidSeas, or one of the six)
   and its quarter turn; tick boxes for the projected views and the isometric;
   hidden lines; tangent edges; scale (chosen, or one of the settings' scales) and
   sheet (chosen, or A to E). The controls start at Drawing Settings' Default Views
   for the manufacturing type, and follow the type until the user changes one; ticks
   equal to those defaults are sent as `views="auto"`. Once the preview is made the
   page says which front SolidSeas chose, and the sheet and scale. "Make these my
   defaults" saves the views, isometric, hidden lines, tangent edges and front
   direction as the type's Default Views, and the sheet size as Sheets' default,
   through `save_settings`; the turn and the scale stay with this drawing, and
   nothing else on any page changes the settings. Add Detail View and Add Section
   are shown disabled: "coming in a later release".
5. **Dimensions and holes.** The recognised features by type, with how many
   dimensions each has. The thread candidates (holes and patterns whose diameter is
   a tap drill): Not answered, Tapped (with the thread, and its depth for a blind
   hole), Clearance or Plain. Tapped becomes a `confirm_thread` edit with the
   thread's tapped designation (`M6 x 1-6H`) and the depth in metres; Clearance and
   Plain leave a plain hole, since a thread is called out only once confirmed. The
   holes whose ends need confirming (the checks that offer "Confirm the End") with a
   tick box each, which becomes a `confirm_end` edit. Coverage by features, faces and
   area, and "This is a reduced-dimension drawing: ..." said plainly when it is one.
   The checks: how many errors, warnings and notes, and each one.
6. **Output.** The folder: Drawing Settings > Files' folder, else next to the part;
   Choose... picks another. It is checked as the 3D Print file's folder is
   (`document.folder_problem`: no link or junction on the way, no cloud
   placeholder, no network share outside the opened folder, no device or stream
   path, a folder this account may write in), and a refused one is shown with its
   reason ("Refused: the folder, or one it is in, is a link or a junction, which
   SolidSeas never writes through. Choose another folder.") with Finish disabled. The
   names: the drawing by its number (`document.drawing_file_name`, `1234-001.ssdrw`)
   and the exports by the settings' pattern with ` PRELIMINARY`
   (`document.export_name`), and for a name another file has taken, the numbered one
   it will get. The files: the drawing always, PDF and DXF ticked. "Open in the
   editor", on.

## The preview

From page 1 on the side of the wizard shows the sheet: a `SheetView` on a
`SheetScene` made with `editable=False`, which never drags. The preview is made as
soon as the part is read, so page 1 never stands empty: while the part is read the
bar under the sheet says "Reading the part...", and while page 1 still needs an
answer (a unit the part does not state) the note under it says which. The PRELIMINARY stamp
is red on screen.

The wizard opens at `SCREEN_SHARE` (90 %) of the free area of its screen (at least
1240 by 780 where the screen has the room). The pages keep `PAGE_WIDTH` (640 px) and
the preview takes the rest: QWizard holds its side widget in a label of its own that
keeps one width, so the wizard makes that label expand ahead of the pages
(`PREVIEW_STRETCH`), and it still gives the room back as the window shrinks. View
Larger... opens the same sheet in a window of its own, as large as the screen, which
shows each new preview as it comes.

While a preview is made a progress bar under the sheet says each stage as it starts,
"Reading the part", "Meshing the part", "Recognising its features", "Drawing the
views", "Placing the dimensions", "Checking the drawing", then "Applying your
answers" for page 5's edits, at the share of the bar where it starts
(`STAGE_START`: the views and the dimensions take most of the time). The child says
the stages (`DrawingWorker.make(..., progress=)`); a stage of an older request is not
shown, and the bar goes once the preview is shown, fails or is cancelled.

The preview is made in the drawing child process: `DrawingWorker.make` with the
options, fields and settings the pages hold, then the edits of page 5 and a printed
part's extra notes. It runs in a worker thread of the wizard's own pool (one thread),
never on the UI thread, which only starts jobs and shows their answers. It is asked
for again `PREVIEW_DELAY_MS` (400 ms) after the last change, so typing a title makes
one drawing, not one a keystroke; reading the part, and entering any page,
asks at once. Two requests that
are equal (`Request`: the part, the options, the fields, the settings and the edits)
make the same drawing, and the same request is never made twice in a row.

A request in progress when a newer one starts is cancelled: its job stops before its
next request to the child, and when the child is working on one of the job's
requests, `DrawingWorker.cancel` ends it (and the child; the next request starts a
new one). The cancelled job's answer, if any arrives, is dropped. The child keeps the
run of the latest preview only: each new preview has the child forget the one before,
so a long session of changes does not fill the child's memory with runs.

An edit the child cannot lay out because it lost the model (it was started again)
raises `ModelNotFoundError`; the wizard attaches the part and asks again.

## What Finish writes

Finish checks the folder again and stops with the reason when it is refused. It then
takes the preview's drawing when the preview was made from the request the pages
make now, and makes it otherwise (the same `make` and edits). In a worker thread it
has the child export the PDF and DXF ticked, as bytes, and writes them in the
window's process under 12.5 and 12.6 (`write_drawing`):

1. the folder checked once more, just before writing (`document.folder_problem`;
   refused: `OutputRefusedError`, nothing written);
2. each export through `document.export_target` and `write_output`, then recorded in
   the drawing's `outputs` (`record_output`), so a later Save can keep them current;
3. the drawing through `document.save_target` and `save`, naming the part as seen
   from the drawing (`locate.with_model_path`: the relative path when the part is in
   the drawing's folder or below it).

Every file goes through a temporary name and a rename. A new drawing has no file of
its own yet, so a name any file has taken gets " (2)", " (3)" and so on, and the
page says so: a file SolidSeas did not write is never replaced. A failure (the child
stopped, a folder that became read-only) is shown on page 6 and the wizard stays
open; Finish can be pressed again.

## First use

When Drawing Settings still lack an answer only the user can give
(`drawingsettings.first_use_prompts`: the unit for parts that state none, the
company's name, the people who sign), the wizard asks, as it first opens, whether to
open Drawing Settings, on the page of the first missing answer. Settings saved there
are used from then on. Declined, page 1 keeps the list and an Open Drawing Settings...
button; the drawing can still be made, and its checks say what is missing. Values the
settings file could not read are listed on page 1 too.

## Tests

`tests/test_viewer_drawing_wizard.py`, offscreen, skipped without PySide6. A stand-in
for the child answers from canned answers (a probe built in the test, and o02's
drawing made by the library in the test process) and records what it is asked, so
the tests read the options, fields and edits each page sends:

- page 1: the probe shown, another configuration read again, the bodies drawn, Draft
  quality; a part that states no unit cannot go on until Inch or Millimetre is
  clicked, and is then drawn in that unit; settings that fix the unit ask nothing; a
  refused part and an unreadable one stop with the reason;
- page 2: every field reaching `make`, a material and finish from the list, the
  revision mark, the finish required, heat treatment asked for 4140, an unmapped
  material flagged, no people leaving DRAWN unsigned;
- page 3: the types offered and disabled, the datum note, the printed process with
  its figures and notes, the suggestion from a printing material;
- page 4: every option, and "Make these my defaults" saving Drawing Settings to the
  test's own file;
- page 5: Tapped, Clearance and Plain, the confirmed end, reduced coverage said
  plainly, the checks summary;
- page 6: the default folder, a refused folder (a link) and a missing one, nothing
  written before Finish, Finish writing through the document rules with the outputs
  recorded, names that never replace a file SolidSeas did not write, a failure
  keeping the wizard open;
- first use, accepted and declined; settings read from their file with a fallback;
- the preview: a newer request cancelling the one in progress while the window keeps
  answering, the pause before a preview, a preview that fails, the progress bar's
  stages (an older request's not shown), the preview taking the room past the pages
  and giving it back, View Larger showing the same sheet;
- the real `DrawingWorker` drawing a copy of o02 end to end into the test's folder.

## Not in this release, and what needs the PC

- Page 5's feature groups have no tick boxes and the tolerance bands are not shown;
  Remove and Restore, and the bands, are in the editor.
- The Turned suggestion comes with the first preview (from page 2), not with the
  probe of page 1, which reads no features; Guided and Express drawings do not use
  it yet.
- A printed part's tapped holes as "tap after printing" or heat-set inserts (10.6)
  are not offered yet.
- On the Windows PC: the wizard's look in the Windows style, the folder checks on
  real junctions, OneDrive placeholders and mapped drives, the child's job object
  limits while previews are made and cancelled, previews of large corpus parts, and
  the packaged viewer.
