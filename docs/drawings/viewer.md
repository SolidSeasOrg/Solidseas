# Drawings in the viewer

How the viewer offers drawings: where the entries are, what can be drawn, how the
New Drawing wizard hands its drawing to the editor, the window's one drawing
process and the sheet on screen, the self-test's dry run and what the packaged
viewer carries.
`docs/DRAWINGS.md` sections 15.1, 15.2, 15.6 and 19.6, as they are built in
`src/solidseas_app/viewer/drawingaction.py`, with the
`--drawing-dry-run` of `viewer/selftest.py` and `packaging/SolidSeasViewer.spec`.
Everything here is provisional until the first release that makes drawings.

## Where drawings appear (15.1)

| Entry | Where | Does |
|---|---|---|
| New Drawing... | File menu after 3D Print, Ctrl+D, and the Drawing button beside 3D Print on the toolbar | the choice of Express, Guided or Expert (DRAWINGS.md 10.4b), unless Settings > Drawings names one; Expert is the New Drawing wizard, Guided the same choices asked as plain questions (`drawingguided.GuidedWizard`), and Express a drawing made with no questions and opened in the editor, each of the part the details panel shows, in the configuration it shows, as 3D Print prints it |
| Make Drawing of NAME... | every right-click menu that offers 3D Print, right after each 3D Print entry | the wizard on what that 3D Print entry would print |
| Open Drawing... | File menu | a `.ssdrw` chosen in a file dialog, in the drawing editor |
| Drawing Settings... | Settings menu, after AI Settings | the dialog of `viewer/drawingsettings.py` (15.2) |

The right-click menus are those of the list's rows, the rows of the Components,
BOM and References tabs and of a drawing's sheets and models, the 3D view (an
instance's part and each sub-assembly it is in, and This Part or This Assembly on
empty space) and its legend. Make Drawing is built from the very resolve its 3D
Print entry has, so it draws the same `PrintTarget`: a component part is drawn from
its assembly, in the row's configuration. An assembly, a sub-assembly's row
included, is drawn with its parts list and balloons ([assemblies.md](assemblies.md)).

What cannot be drawn has its entry off, with the reason in a few words after it
and in full in its tooltip and status tip:

| Shown or chosen | Entry reads | Reason |
|---|---|---|
| a SOLIDWORKS drawing | (New Drawing off) | "The document shown is a SOLIDWORKS drawing. Drawings are made of SOLIDWORKS parts and assemblies, and of STEP, Parasolid and Alibre Design parts, in this release." |
| a 3D file of a format drawings are not made from (by what it holds, not its name) | `(not a format drawings are made from)` | "NAME is a 3D file of another format (STL). Drawings are made..." |
| a STEP, Parasolid or Alibre file under a SOLIDWORKS or other name | `(named as another format)` | "NAME holds a STEP file under the name of another format. Give it the extension of a STEP file to draw it." |
| a STEP or Alibre assembly | `(an assembly of another format)` | "NAME is a STEP assembly. Drawings of assemblies are made from SOLIDWORKS assemblies in this release." |
| a part or sub-assembly stored inside an assembly (virtual) | `(stored inside its assembly)` | it has no file of its own; save it as a part (an assembly) of its own in SOLIDWORKS to draw it |
| a component whose file was not found | `(not found)`, as its 3D Print entry | the 3D Print entry's reason, said of a drawing |

`drawingaction.refusal(target)` is that rule. The drawing process reads a part's or
an assembly's own SOLIDWORKS file, and a part's STEP, Parasolid or Alibre Design file
(`solidseas.drawing.source.MODEL_FORMATS`), which has no configurations: its probe
lists none, and the wizard offers none. A Parasolid file whose head says assembly
has its entry on, since SOLIDWORKS writes a multi-body part's `.x_b` that way; the
drawing process reads the whole transmit and refuses a real assembly with its
reason. The editor's Find the Model offers all of those part files.

On first use (no unit for parts that state none, no company name or no people),
New Drawing opens Drawing Settings on the first page that waits for an answer, once
a session, then the wizard.

## The controller

`DrawingController(window)` is owned by the window, as `PrintController` is. The
window's change is one block after its actions are built:

```python
self.drawings = DrawingController(self)
self.drawings.install(self.menuBar().actions()[0].menu(), self.settings_menu, self.toolbar)
```

`install` puts the entries in the File and Settings menus and on the toolbar, and
follows three things of the window rather than changing them:

- **The print controller's `add_action` and `add_unavailable`.** Each 3D Print entry
  a menu gets is noted, with its resolve, and the Make Drawing entries are put in
  right after their 3D Print entries when the menu opens (`fill(menu)`, on
  `aboutToShow`). A menu that gains a 3D Print entry later gains its Make Drawing
  too, with no change where the menu is built. Code that builds a menu and reads it
  without showing it, the print tests among it, sees the menu as the print
  controller made it; `fill` puts the entries in at once for a test.
- **The window's `_update_actions`.** After each of the window's own updates, New
  Drawing is turned on or off for the document shown, its tooltip saying why.
- **The window's close.** An event filter closes the wizard and every editor first;
  an editor that stays open (its user keeping unsaved changes) keeps the window
  open. Then the drawing process ends.

What a 3D Print entry would print is looked at when its menu opens, to know whether
Make Drawing is on. The window's one question there (which of several files a
reference means) is answered as cancelled for that look, so opening a menu never
asks anything; the entry asks when chosen.

| Member | Is |
|---|---|
| `new_action`, `open_action`, `settings_action` | the three window entries |
| `start(target)` | the one way every drawing starts: the refusal said, one wizard at a time (pressed again, the open one comes forward), the first-use dialog, then `DrawingWizard(window, worker, part, configuration=, settings=, settings_path=, folder=)` shown; `folder` is the opened folder (`PrintTarget.folder`), which the folder rules of 12.6 need |
| `new_drawing()`, `draw_resolved(resolve)` | New Drawing and a Make Drawing entry, through `start` |
| `mode_for(target)`, `start_express(target)`, `start_guided(target)`, `start_expert(target)` | the mode (`choose_mode` is the chooser, which tests replace), an Express drawing (`make_express`, an `ExpressRun` by default), the Guided wizard (`make_guided`, a `GuidedWizard` by default, made with the wizard's arguments and held as the one wizard open) and the wizard |
| `open_editor(path)` | `DrawingEditor(worker, path, settings=, settings_path=, parent=None)` shown, or the one already open on that file brought forward |
| `open_drawing()` | Open Drawing: a plain `.ssdrw` (`drawing_file_problem`), then `open_editor` |
| `edit_settings(page=None)` | Drawing Settings, saved to `settings_file()` |
| `ensure_worker(settings)` | the window's one `DrawingWorker`, made on first use, its child memory from Drawing Settings |
| `close_all()`, `shutdown()` | what the window's close does |
| `written(path)`, `opened(editor)` | signals: the wizard wrote a drawing; an editor opened |
| `last` | what the last New Drawing or Make Drawing did (`ok`, `cannot`, `busy`, `closed`, `first_use`) |

The wizard's `drawing_written(path, open_editor)` says the drawing file was written
and opens the editor on it when `open_editor` is true; the status line names the
file. Editors are top-level windows, kept by the controller per drawing file and
closed with the window.

`make_wizard`, `make_editor`, `make_settings_dialog` and `make_worker` (None: the
real class, imported when first wanted), `pick_drawing`, `message`,
`load_settings` and `settings_path` are attributes, so tests and the self-test stand
in for them. With `dry_run` no dialog or message is shown: what would be said is
kept in `said`. Without the wizard or the editor module, New Drawing and Open
Drawing say that it is not in this viewer.

The controller writes nothing and reads no part. The wizard and the editor write
the drawing file and its exports through `drawing.document`'s rules (12.6), and every
request to the library goes to the drawing process from their own threads.

## The drawing process and the sheet on screen

The drawing process and the sheet on screen have their design in their
modules' docstrings; in short:

- **`viewer/drawingproc.py`** runs the drawing library in a child process,
  `DrawingWorker`, started as the mesh reader's is (`meshproc._start`) the first
  time it is wanted and shared by the wizard and every editor. One request runs at a
  time, from a worker thread, never the UI thread. A request and its answer header
  are JSON frames, never a pickle; a drawing crosses as its `.ssdrw` bytes, read back
  with `document.loads` as hostile input, and a PDF or DXF as raw bytes, each frame
  checked against the size and SHA-256 its header gives. Errors cross as `{code,
  message, detail}` and are raised again as their own class. Every request has a
  time limit; on Windows the child runs in a job object at below-normal priority,
  held to `child_memory_mb`. The child opens parts read-only and writes nothing:
  saving and exports are written by the window's process under 12.6. It keeps the
  runs of the drawings it made beside them, at most 8 (`drawing.edit`), so an edit
  lays out again without reading the part; a child started again answers
  `model_not_found` and the window attaches the model and asks again.
- **`viewer/drawingscene.py`** shows a laid-out sheet. `QtPainter` implements the
  painter interface the PDF writer implements, so the screen draws what the PDF
  draws, text stretched to the PDF's Helvetica widths. `SheetScene` has one item per
  owner of the painted layer (a dimension, a view, the title block, a note, the
  stamp), picked, hovered and selected by owner, a dimension dragged and dropped
  reported in sheet millimetres; `set_sheet` rebuilds only the owners that changed.
  `SheetView` fits the sheet, zooms about the pointer and pans with the middle
  button. The PRELIMINARY stamp is red on screen. On the VM the 100-hole plate's
  scene builds in 25 to 60 ms, and `set_sheet` after one dimension moved takes
  about 1 ms.

## Where files go

AGENTS.md's safety rule names the files written next to a model: the 3D Print file
and, as the user decided in Q8 and Q14 (12.6), a drawing's file and its exports.
They go next to the part by default, under the 3D Print file's folder rules, or to
the folder Drawing Settings name; a refused folder or a failed write never sends
them elsewhere on its own. Save replaces only the same drawing's own unchanged files
while "Save may replace files SolidSeas wrote and nobody changed since"
(`replace_own_files`) is on, the default; with it off every write is a new file.
Released exports are never replaced.

## The self-test's dry run (15.6)

`SolidSeasViewer --self-test FOLDER --select NAME... --drawing-dry-run` makes a
drawing of each selected SOLIDWORKS part with File > New Drawing, as the menu does,
with the controller in its dry run and Drawing Settings of the run's own (the
fictional "Example Engineering Co.", two people to sign, millimetres for parts that
state no unit) in a folder the run makes in the system's temporary folder. The
user's settings are never read or changed.

The run stands in for the wizard and the editor (`DryRunWizard`, `DryRunEditor`):
the controller makes them with the real ones' arguments and hands the drawing from
one to the other as it does the real ones. They do what the wizard and the editor
do, in a thread of the run's own, through the window's drawing process and
`drawing.document`:

1. **Wizard.** `probe` (page 1, the unit the part states or the one it guesses);
   `make` with a title, the number `ST-001` (then `ST-002`...), revision A, a
   material of the settings' list, a finish and the first person as DRAWN (page 2),
   every other choice its default; the folder checked (`folder_problem`); the PDF,
   DXF and drawing file written there (page 6).
2. **Editor.** Remove a dimension, restore it, undo both; sign CHECKED and APPROVED;
   Save (its own file replaced, its PRELIMINARY PDF and DXF rewritten); Release (the
   items a release may accept accepted with a typed reason when it is first
   refused), the released PDF and DXF written new, Save; Start Revision B, Save;
   Email PDF after the PRELIMINARY question, with stand-ins for the mail program,
   the file manager and the browser, so nothing is started.

Then every PDF and DXF is read with the tests' own readers, `tests/pdf_reader.py`
and `tests/dxf_reader.py` (`check_pdf_file`, `check_dxf_file`): the whole file read,
SolidSeas named as its writer, and the PRELIMINARY stamp exactly on the unreleased
ones. The run also checks the names, that only the drawing's own unchanged files
were replaced, that the released files were never written again, the drawing file
read back (revision B, PRELIMINARY, each file in its record with the hash it has),
the arguments the controller gave the wizard and the editor, and that nothing was
written beside the part. The report's `drawing` gives each step, the files and the
checks; with screenshots it saves the sheet as the editor shows it. A failed check
fails the run and keeps the folder (`kept_in`); otherwise the folder is removed. An
assembly is drawn the same way, without a material or finish of its own; its
drawing has no dimension to remove, so the editor's steps start at signing, and its
sheet must carry the parts list and a balloon (the report's `parts`). A SOLIDWORKS
drawing or a file of another format must have New Drawing off with its tooltip
saying why, and is reported as not drawable.

On o02 the whole dry run takes under a second after the details are read.

## Packaging

`packaging/SolidSeasViewer.spec` lists as hidden imports the modules imported when
first wanted (`drawingaction`, `drawingwizard`, `drawingeditor`, `drawingsettings`,
`drawingscene`, `drawingproc`, `mail`, `mailproc`), every module of
`solidseas.drawing` (the pipeline imports its stages by name), and the two readers
the dry run uses. The library has no data files. No Qt module is added: the sheet is
drawn with QtWidgets and QtGui, the PDF and DXF are SolidSeas' own writers, and the
browser opens through QtGui.

## Tests

`tests/test_viewer_drawing_action.py`, offscreen, with stand-ins for the wizard, the
editor, the settings dialog, the file dialog and the drawing process:

- `refusal` for a part, an assembly, a virtual sub-assembly, a drawing, a file of
  another format (by its content), a virtual part; the entries' texts;
  `drawing_file_problem`.
- The entries in the File and Settings menus and on the toolbar; New Drawing on
  for a part and an assembly and off, with its reason, for a SOLIDWORKS drawing and
  an STL; the wizard's arguments; one wizard at a time.
- Make Drawing in the list's menus (only once a menu opens, an assembly's row
  drawing the assembly), a component row's (the part from its assembly, in the
  row's configuration), a sub-assembly's (on) and a virtual part's (off), the 3D
  view's instance and empty-space menus, and a component whose file is missing
  (off, with the reason said of a drawing).
- The wizard's `drawing_written` opening the editor, or not; the same drawing
  brought forward; Open Drawing; an editor that refuses a file.
- The window's close closing the wizard, the editors and the drawing process, and an
  editor that stays open keeping the window open.
- Drawing Settings, and the first-use prompt once a session.
- The self-test's `--drawing-dry-run` on o02 and the assembly o08 for real; and the
  PDF and DXF checks refusing a broken file.

## What needs the PC

- The packaged viewer's `--self-test` with `--drawing-dry-run` on copies of o02 and
  o11: the drawing process and the readers start from the frozen executable.
- Email PDF's Automatic route on the PC, from the real registry, in the dry run (it
  reads only, and the stand-ins start nothing).
- By hand, with the user: New Drawing, Make Drawing and Open Drawing with the real
  wizard and editor, and the window's close with an editor holding unsaved changes.
