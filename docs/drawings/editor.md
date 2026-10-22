# The drawing editor

The viewer's window for one drawing: `docs/DRAWINGS.md` section 15.4, with the edits
of 10.12, saving under 12.5 and 12.6, signing, release and revisions under 13, and
Email PDF under 15.5, built in `src/solidseas_app/viewer/drawingeditor.py`.
Everything here is provisional until
the first release that makes drawings.

`DrawingEditor(worker, path, *, settings=None, settings_path=None, parent=None)` is a
`QMainWindow` opened on a `.ssdrw` on disk. `worker` is the window's
`DrawingWorker` (`viewer/drawingproc.py`), shared with the New Drawing wizard and
never closed by the editor. `settings` are the current Drawing Settings (read from
`settings_path`, else the user's `Drawing.json`, when None), and `settings_path` is
where Drawing Settings... saves.

## The window

| Part | What it holds |
|---|---|
| Centre | the sheet in a `SheetView` of a `SheetScene` (`viewer/drawingscene.py`), picked and hovered by owner. Dragging a dimension moves it (`edit.move`) |
| Left: Dimensions | the dimensions grouped by view (Front view, Top view...), each with a tick box, its text as the sheet draws it, its kind, its band and its badges (new, changed, needs attention, reference, overridden, basic). Unticking removes a generated dimension and deletes one the user added; ticking restores. A dimension that needs attention is drawn amber, here and on the sheet |
| Right: Properties | for a dimension: the measured value (read-only, to more places than any drawing shows), precision ("from its role" or 0 to 4) and the band it falls in, prefix and suffix lines, a value override with its warning, the tolerance, the feature control frame (characteristic, zone, Ø, modifier, up to three datums; Apply, Remove, Reset), Reset Position and Flip. For a note: its text. With nothing selected: the title fields |
| Add Dimension (D) | the features picked on the sheet or ticked in a list, and the planner's candidates for them with their values |
| Bottom: Checks | the checklist of 20.1: level, code, whether it blocks release, the message. Selecting a row selects what it is about; its fixes are buttons |
| Status bar | the status and revision (`PRELIMINARY, revision A`), and the model: "Model unchanged", "The model has changed. Update Drawing", "Model not found. Find..."; the last two are buttons. For a drawing of several sheets, which is shown ("Sheet 2 of 3") |

A drawing of several sheets (an assembly's parts list going on past the first,
DRAWINGS.md 11.7) shows one sheet at a time. Drawing > Next Sheet and Previous
Sheet (Ctrl+Page Down and Ctrl+Page Up, on the toolbar too) page through them;
they are shown only for such a drawing (`show_sheet(n)`, `page`, `sheets`).
Every edit concerns the first sheet, where everything but the rest of the parts
list is, and selecting a dimension, a note or a view, from the lists or a check,
shows the first sheet again. An edit keeps the sheet shown when the drawing still
has it.

Every word a drawing carries is shown as plain text: a `.ssdrw` can arrive by email.

An assembly's drawing ([assemblies.md](assemblies.md)) shows its parts list and
balloons on the sheet and no dimensions: Add Dimension, Remove Dimension, Reset
Position and Tolerance Block are off, their tooltips saying "An assembly's drawing
has no dimensions: its parts list and balloons name its parts." Picking a balloon
or the parts list selects nothing to edit, and neither is dragged. The model is the
assembly with its parts: one whose parts changed under the same assembly file is a
changed model, which Update Drawing takes.

## Commands

| Menu | Command | What it does |
|---|---|---|
| File | Save, Save As..., Save a Copy to Send... | see Saving below |
| File | Export PDF..., Export DXF... | the sheet through the writers, into a folder the user chooses (the drawing's by default), named by 12.5, recorded in `outputs` |
| File | Email PDF... | see Email PDF below |
| Edit | Undo, Redo | the drawings before and after each edit |
| Edit | Add Dimension (D), Remove Dimension (Delete), Reset Position | as the panels do |
| Drawing | Update from Model, Find the Model... | see The model below |
| Drawing | Sheet and Scale..., Units..., Tolerance Block..., Notes... | `set_sheet` and `set_scale` (one undo step), `set_units`, `set_tolerance_block`, `edit_notes` |
| Drawing | Isometric on Its Own Sheet (a tick) | `set_view_sheet`: the isometric, with its balloons, on the sheet after the first, or back on the first; the sheet it went to is shown. On only for a drawing whose views include the isometric. The check that says an isometric had no room offers it as Move to Its Own Sheet |
| Drawing | Add Detail View, Add Section | disabled: coming in a later release (`edit.add_view` refuses them with rule `later_release`) |
| Drawing | Use Current Drawing Settings, Drawing Settings... | `edit.use_settings` with the current settings; the dialog of `viewer/drawingsettings.py`, whose saved settings become the editor's current ones |
| Status | Sign..., Release..., Start Revision... | see Signing, release and revisions below |

## Nothing on the UI thread

Every library request goes to the worker from a thread of the application's pool (a
pool of the window's own would make closing the window wait for it), one step at a
time in the order asked: an edit asked while another runs waits for it and
starts from the drawing it made, so two quick drags both count. Reading the
`.ssdrw` (`document.read`), looking for the model's file (`locate.find_model`, which
hashes it), saving and writing exports are file work on that thread too. The UI thread
only replays the sheet, fills the lists and asks the user. `DrawingEditor.wait()` lets
a test or the self-test run Qt until the steps asked so far have finished; the window
itself never waits.

## The model

Opening a drawing reads its file, shows its sheet at once, and attaches its model in
the child (`worker.attach` with the drawing's path, so the child looks for it as 13.6
says). Then:

- **Found:** "Model unchanged", and the drawing is editable. A model chosen with
  Find... that is another file with the same geometry is attached too; the bar says
  "The model has changed. Update Drawing", and Update from Model takes the new
  reference.
- **A changed file found:** "The model has changed. Update Drawing". The drawing is
  view-only until Update from Model, which takes that file because the user asked.
- **None found:** "Model not found. Find...". The drawing is view-only, shown from
  its sheet with the checks the file answers; Find... chooses the model's file.

An edit the child answers with `ModelNotFoundError` (it was started again) attaches
the model again and asks once more. The child lets go of the model after five idle
minutes (8.12, `worker.forget`, `IDLE_SECONDS`), and the next edit attaches it
again. Closing the editor lets the child drop it, without waiting.

Update from Model (`worker.regenerate`) merges the model into the drawing as 13.5
says, as one undo step, and shows the merge report (its sentence and its lines). Its
description goes into the next revision's pre-filled description. Undoing it brings
back the drawing that records the old model, which is then "The model has changed"
again.

A RELEASED drawing whose model has changed offers both Update Drawing and Start
Revision. Either asks for the new revision's row (pre-filled "UPDATED FROM MODEL"),
then `worker.regenerate(drawing, part, revision=..., drawn_by=..., today=...)` starts
the revision and merges the changed model in one step, so the new revision's sheet is
laid out from that model and carries the PRELIMINARY stamp. It is one undo step, as
Update from Model is.

## Saving (12.6)

- **Save** replaces only the drawing's own unchanged file. The editor keeps the
  SHA-256 of the file as it read it or last saved it and gives it to
  `document.save_target` as `loaded_sha256`; a file there that is another drawing, or
  this one changed behind the editor's back, is left as it is, and the drawing gets
  the next free name (`SS-1 (2).ssdrw`), with which the editor carries on.
- **With `replace_own_files` off** every save is a new file, and the earlier one stays.
- **Keep preliminary exports up to date** (on by default): Save rewrites each
  PRELIMINARY PDF and DXF that `outputs` lists under its current name, in the
  drawing's folder, when it is this drawing's own unchanged file (the hash recorded,
  and the PDF's `Producer` or the DXF's `999` comment says SolidSeas). Any other file
  is left alone; Export writes a new one under a free name.
- **Released exports are never replaced**: Export of a released drawing, and Release
  itself, write new files (`document.export_target`).
- **A refused folder** (`document.folder_problem`: a link or junction, a cloud
  placeholder, a network share outside the opened folder, a device or stream path)
  never sends a file elsewhere: Save opens Save As with the reason in its title, and
  an export asks for another folder with the reason.
- **Save As** writes to the name the user gives, under the same rules; the model's
  path in the drawing is set for the new folder (`locate.with_model_path`).
- **Save a Copy to Send** writes a new file, never over anything, without the model's
  absolute path (`locate.for_sending`); a drawing that is not RELEASED asks "This
  drawing is PRELIMINARY. Send it anyway?" first.

The two switches, `replace_own_files` and `keep_preliminary_current`, are read from
the current Drawing Settings, the user's answer, rather than from the drawing's
snapshot: turning them off in Drawing Settings holds for every drawing at once. The
rest of the files group (the name pattern) is the drawing's own.

## Undo and Redo

A `QUndoStack` holds the drawings before and after each edit; a save marks it clean,
and Undo keeps working after a save (the next Save replaces the file the editor saved,
by its recorded hash). The records of exported files (`outputs`) are facts about the
disk, not edits, so Undo keeps them. Release empties the stack: a RELEASED drawing is
read-only but for Start Revision. Undo and Redo are refused, with a word in the bar, while a step runs.

## Signing, release and revisions

- **Sign...**: a row the drawing's settings use (the rows not yet signed are
  offered) and a person from the People list of the drawing's settings snapshot, which
  is what `release.sign` checks against. With nobody in it the editor says to add the
  people in Drawing Settings and Use Current Drawing Settings. An edit that clears a
  signature says so in the bar.
- **Release...**: a dialog listing why the drawing cannot be released as it is
  (`release.release_problems`), with a typed reason for each `COV.unclaimed` and
  `R2.override` error and for a material the list does not map. A refused release
  lists every reason. A release writes the released PDF and DXF beside the drawing as
  new files, records them, and saves the drawing.
- **Start Revision...**: the next revision's row, its description pre-filled (the
  merge reports' and the edits' words since the last revision, else what the model
  says has changed) and editable, DRAWN signed again by whoever signed it before
  unless the dialog says otherwise. When the model has changed since the release, the
  revision takes the changed model as it starts (The model, above).

A RELEASED drawing refuses every edit with "The drawing is RELEASED and read-only:
Start Revision to change it."; Save, the exports and Email PDF still work.

## Email PDF (15.5)

The released PDF of the current revision (checked against its recorded hash), or for a
drawing that is not RELEASED the stamped PRELIMINARY PDF, made current by exporting it
into the drawing's folder after the PRELIMINARY question. Then `mail.choose_route` on
the UI thread, `mail.attach_pdf` on a worker thread for the attach route, and
`mail.email_pdf` on the UI thread, whose status line the bar shows. Only the PDF is
ever offered.

## For the self-test and the drawing action

What asks the user goes through methods a test or the self-test replaces on the
instance: `ask_save_path(title, start)`, `ask_folder(title, start)`,
`ask_model_path(start)`, `ask_question(text)`, `ask_close()` (`save`, `discard` or
`cancel`), `tell(title, text)` and `run_dialog(dialog)`, which shows a command's
small dialog and says whether it was accepted (its fields are `dialog.fields`).
Every command also takes its answers as arguments:

| Method | Command |
|---|---|
| `remove(id)`, `restore(id)`, `delete(id)`, `move(id, along_mm, across_mm)`, `move_by(id, dx, dy)`, `reset_position(id)`, `flip(id)` | dimensions |
| `set_precision(id, places)`, `set_text(id, prefix, suffix_lines)`, `reset_text(id)`, `override_value(id, text)`, `set_tolerance(id, kind, upper, lower)`, `set_frame(id, frame)`, `reset_frame(id)` | Properties |
| `set_note(note_id, text)`, `set_title({key: text})` | a note, the title block |
| `toggle_add_dimension(on)`, `pick_feature(fid)`, `candidates`, `add_candidate(candidate)` | Add Dimension |
| `edit(op, args, words)`, `edits([(op, args)...], words)` | any operation of `drawing.edit`, as one undo step |
| `sheet_and_scale(sheet, scale)`, `set_units(units)`, `tolerance_block(rows)`, `edit_notes(texts)`, `use_current_settings()`, `open_drawing_settings()` | the Drawing menu |
| `sign(row, person)`, `release(accepted)`, `start_revision(description)` | the Status menu |
| `save()`, `save_as(path)`, `save_copy_to_send(path)`, `export_pdf(folder)`, `export_dxf(folder)`, `email_pdf()` | the File menu |
| `update_from_model()`, `find_model(path)` | the model |
| `undo()`, `redo()`, `wait(timeout)` | |

`drawing`, `path`, `model_state` (`looking`, `unchanged`, `geometry`, `changed`,
`missing`), `model_path`, `editable`, `busy`, `messages` and `last_message` (what the
bar said), `release_reasons`, `last_report` and `last_delivery` are there to read. The
`changed` signal says the drawing shown changed.

## Tests

`tests/test_viewer_drawing_editor.py`, offscreen with PySide6 and skipped without it,
on a real `DrawingWorker` and copies of o02, o07 and o11 under fictional names in
pytest's temporary folders: opening (the sheet, the lists, the checks and their
fixes, the model); remove and restore by the tick boxes, undo and redo; a drag on the
sheet and two quick ones; every Properties control; Add Dimension on the four-holes
plate; view-only without the model, then Find...; Update from Model o02 to o07 with
the report, and undoing it; the idle model let go and attached again, and a child
started again; sign, release refused then allowed, a released export not replaced,
Start Revision; release with typed reasons for an override and an unmapped material,
a fix button, Email PDF of the released PDF and Start Revision's dialog; a released
drawing whose model changed revised with it from Update Drawing, and undoing it; save
and save
again by the hash rule, undo after a save, a file changed behind the editor's back,
closing with Save; save with `replace_own_files` off, Save As and Save a Copy to Send;
a refused folder opening Save As with the reason; Export PDF and DXF kept up to date
by Save; Email PDF with stand-ins that start nothing; Sheet and Scale, Units, the
Tolerance Block, Notes, Use Current Drawing Settings and the Drawing Settings dialog;
and that the children wrote nothing at all and the window nothing outside the
temporary folders, the parts unchanged.

Add Dimension needs a part with holes to measure between, and none of the fixtures
has two. The tests' worker starts its children with a stand-in for the source and
model stages that reads a part named `FOUR-HOLES.SLDPRT` as the synthetic
four-holes plate of `tests/drawing_parts.py`; every other stage is the real one.

## What needs the PC

- The editor on Windows with a real mouse and a high-DPI screen: picking, hover and
  dragging dimensions, the docks' sizes, the Add Dimension shortcut (D) while a field
  has the focus.
- Email PDF from the editor on the user's PC (the webmail route opens Gmail, File
  Explorer shows the PDF selected), with `docs/drawings/email.md`'s checks.
- Save and the exports to a folder on a mapped network drive, in OneDrive and through a
  junction: refused with the reason, Save As offered.
- The editor in the packaged viewer: the child started from the frozen executable.

## Requests for the library

- **A view's placement.** 15.4 says views drag with their dimensions and keep
  alignment, and Properties shows a view's label, scale and display. `drawing.edit`
  has no operation for a view's position or label, so the editor offers neither yet.
