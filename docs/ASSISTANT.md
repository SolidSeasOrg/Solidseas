# Modeling assistant and AI connector

This is the design for the modeling assistant in SolidSeas Desktop and for the
AI connector it uses, `solidseas.ai`. `docs/ARCHITECTURE.md` gives the summary;
this document holds the rules an implementation is checked against.

It was revised after three independent reviews: fidelity to the design patterns it follows
(`ai-provider-seam`, `fail-closed-machine-policy`, `ai-prompt-to-record`,
`untrusted-input-defaults`, `secrets-and-credentials`,
`desktop-app-security-review`, `windows-worker-job-object`,
`state-file-pattern`, `python-stuck-thread-exit`), safety, and feasibility
against the SOLIDWORKS 2024 API documentation. The SOLIDWORKS behaviour it
depends on was then measured in a spike on SOLIDWORKS 2024 SP1; the answers, and
what each one changed here, are under "Confirm before building" at the end. The
rules are written so that a failed check becomes a stop or a refusal, never a
silent guess.

## What the assistant is

An always-on-top window that works alongside the user while they model in
SOLIDWORKS, in one of two modes:

- **Review mode** (the default). The user describes a change in plain English
  or types code. The AI drafts code, the code appears in an editable console
  with an explanation, and nothing runs until the user approves it.
- **Automatic mode.** The user states a goal, for example "add M3 heat-set
  bosses at the four lid corners and shell the part to 2 mm", and turns
  Automatic on for that run. The assistant plans the steps once, from a closed
  vocabulary of checked operations, and carries them out on one part without
  asking at each step. Every step is checkpointed, verified and revertible.

Both modes are opt-in per session. The assistant does nothing in SOLIDWORKS
until the user opens it, picks a SOLIDWORKS session and picks a document.

## Processes and threads

Calls into SOLIDWORKS stay out of the app process. That keeps the window, the
log and Stop responsive while SOLIDWORKS is busy, and lets SolidSeas exit even
when a call into SOLIDWORKS never returns.

| Process | Role | Contained by |
|---|---|---|
| SolidSeas Desktop | Qt window, planning, validation, the run journal, verification decisions | |
| `SolidSeas.SwBridge.exe` | The only code that calls SOLIDWORKS | A Job Object with kill-on-job-close, owned by the app |
| Runner worker | Code a person approved in Review mode or the CadQuery workspace | A Job Object with memory and time limits |

The bridge is a small C# console program, compiled from source against the
interop assemblies that ship with SOLIDWORKS. Its main thread is a
single-threaded apartment (`[STAThread]`) that owns every SOLIDWORKS object.
It registers a COM message filter (`CoRegisterMessageFilter`), so a call that
SOLIDWORKS rejects while it is busy or showing a dialog (`RPC_E_CALL_REJECTED`)
is retried rather than failed, and it pumps messages whenever it waits.
Document notifications do not depend on that pumping: SOLIDWORKS calls the
bridge's event handlers on a COM worker thread, whether the main thread is idle,
busy or blocked, and waits for each handler's return value (answer 5). A handler
only records the event, or answers from state it can read without the main
thread, never calls SOLIDWORKS, and never blocks. Recording means appending the
event line to a bounded in-memory queue that a separate writer thread drains to
stdout; when the queue is full the event is dropped and counted, and the next
line says how many were lost, which the next binding check treats as a change
SolidSeas did not make. A handler that waited for the pipe would hold
SOLIDWORKS, the user's own in live mode, with no request pending for a timeout
to end: in a review rerun of the spike, a listener that stopped taking events
let 29 more rebuilds through until the pipe filled, and the 30th waited 5 s,
until the listener was released. For the same reason the app calls its event
listeners on a thread of their own, never on the thread that reads the bridge's
replies. The bridge reads one JSON request per line on stdin and writes one
JSON reply per line on stdout. It accepts only its own named operations with
validated arguments, never code. Batch mode uses the same program against its
own SOLIDWORKS instance.

Python never loads the SOLIDWORKS interop in-process. A COM call stuck inside a
busy SOLIDWORKS would hold the Qt thread or the GIL, and the process could not
exit (pythonnet issue 2272 shows the GIL case).

The app talks to the bridge from a worker thread, never from the Qt thread.
Every request has a timeout; on a hard timeout the app kills the bridge and
starts a new one, which re-attaches through the Running Object Table. On exit
the app flushes the run journal, joins its worker threads with a bound, then
calls `os._exit`, following `python-stuck-thread-exit`. If the app crashes,
kill-on-job-close ends the bridge, so no step can run without a Stop button in
front of it.

## Attaching to a live session

- SolidSeas never uses `GetActiveObject("SldWorks.Application")`, which returns
  whichever SOLIDWORKS registered first and may be a batch instance.
- It lists the `SLDWORKS.exe` processes in the user's own Windows session,
  leaves out the instances it started for batch work, and binds each one
  through the Running Object Table moniker `SolidWorks_PID_<pid>`. For each it
  shows the process id, the version (`ISldWorks::RevisionNumber`) and the open
  documents (`ISldWorks::GetDocuments`) with title and full path.
- A SOLIDWORKS started as administrator cannot be reached from a non-elevated
  SolidSeas. The picker says so instead of showing an empty list, and
  SolidSeas never runs elevated to get around it.
- The user picks the session, then the document.
- Live mode never ends the SOLIDWORKS process it attached to, even when it stops
  responding, because that process holds the user's other open documents. If a
  call fails because SOLIDWORKS has gone away (`RPC_E_DISCONNECTED`,
  `RPC_S_SERVER_UNAVAILABLE`), the run ends and the window says where the
  safety copy and the run journal are.

## One writer per SOLIDWORKS session

Before an Automatic run starts, and before approved Review mode code runs,
SolidSeas takes the named mutex `Local\SolidSeas-Live-<SOLIDWORKS pid>` and
holds it until the run or script ends. A second window, a second SolidSeas
process or Review mode code is refused with "Another SolidSeas run is working
in this SOLIDWORKS session." The Run control is disabled while a run is active,
and `start_run` takes the mutex itself, so a double click cannot start two
runs.

## Review mode

- The AI drafts CadQuery code, or Python against `solidseas.swapi.live`: a
  typed facade over the same bridge operations Automatic mode uses, plus
  read-only queries for features, dimensions, properties and mass properties.
  The drafting prompt asks for code that uses only this facade, and it is the
  one path to SOLIDWORKS the app gives the child; nothing enforces that, since
  the code runs with the user's rights and could import anything (below). The
  person reading it before Run is the check.
- The code appears in an editable console with its explanation. Nothing runs
  until the user presses Run.
- Approved code runs only through `solidseas_app/assistant/runner.py`, the one
  module that starts an interpreter for user or model code. It runs in a child
  Python process inside a Job Object with a memory cap and a time limit, as in
  `windows-worker-job-object`, and is killed and replaced on timeout or Stop.
  That caps resources and keeps the window alive. It is not a sandbox; the
  person's approval is the control. The CadQuery workspace uses the same
  runner.
- The child process reaches SOLIDWORKS only through the app, which forwards its
  named operations to the bridge, so the one-writer mutex applies to it too.
- What the child trusts: the runner starts it as SolidSeas's own program with
  `--assistant-child` (`SolidSeasViewer.exe --assistant-child`, or
  `python -m solidseas_app --assistant-child` from source), and it runs the code
  the first line on its standard input sends. It trusts whoever started it as
  fully as the person whose rights it runs with. That opens no way in for anyone
  who could not already start a program as that person, and a token on the pipe
  would not change it: whoever starts the child can hand it the token too. It
  listens on no port or named pipe and reads code from no file or command line.
  Where application allowlisting (AppLocker, App Control for Business) admits
  `SolidSeasViewer.exe`, the flag lets the executable run Python code as an
  allowed interpreter would; allow it only for people who may run scripts.
- Before approved code touches SOLIDWORKS, the bridge writes a safety copy (as
  for checkpoint 0 below) and opens one named undo entry, "SolidSeas script",
  which it closes even if the script is stopped. The script's SOLIDWORKS
  operations then come off with one Ctrl+Z, except custom property edits, which
  are not on the SOLIDWORKS undo list (answer 2).
- Anything an approved script does outside the SOLIDWORKS undo list, such as
  writing a file, changing an option or editing a custom property, cannot be
  reverted. The console says so beside the Run button.
- Built: `solidseas_app/assistant/live_sessions.py` over the bridge's live
  operations (the swapi README, "Live mode"). A script's vocabulary operations
  go through the plan validator, as one-step plans against the handles of the
  snapshot read when the person picked the part, and the bridge carries them
  out on the active part only. A profile is given in the frame the summary
  reports for its plane or planar face (`origin` or `point`, `sketch_x`,
  `normal`), and the bridge puts it into the sketch through the sketch's own
  transform. An extrude's `normal` direction is SOLIDWORKS' own: a boss along
  the plane's normal (out of the part from a face), a cut against it. The
  undo entry's opening is recorded in a state file, so a bridge ended
  mid-script leaves no entry open once another attaches.

## Automatic mode

### Starting a run

`solidseas_app/assistant/automatic.py:start_run` is the only entry to Automatic
mode. It refuses to start unless all of these hold:

1. The machine policy, read fresh, allows Automatic mode.
2. The one-writer mutex is free.
3. The chosen document is a part (`swDocPART`). Assemblies and drawings are
   refused in this version. Changing a component's dimension from inside an
   assembly edits the component's own file, which is then saved with the
   assembly, so an assembly run could not keep to one document.
4. The document is the active document in its session, nothing is being edited
   in it (`ISketchManager::ActiveSketch` is empty and no PropertyManager page is
   open), and it rebuilds without errors. Existing What's Wrong warnings are
   recorded as the baseline and are allowed; existing errors refuse the run.
5. Planning produced a valid plan, and the plan was confirmed if it needs
   confirming.
6. Every handle in the plan still resolves against a fresh baseline snapshot.
   If the user changed the part between planning and Run, the run is refused
   with "The part changed since the plan was made."
7. Checkpoint 0 was written and checked.

The run then records the bound document object, its full path (or its title,
for a document never saved), its active configuration and the baseline
snapshot. It never reads `ActiveDoc` to find its target again.

`start_run` asks the bridge for checks 3, 4, 6 and for checkpoint 0 through one
interface (`LiveTarget` in `automatic.py`) and refuses on the first check that
fails, with a code, giving the one-writer mutex back. A refused run leaves no
run folder. The mutex is a named mutex object used as a token: whoever creates
it holds the session, and finding it already there, or being denied it,
refuses. Because it is never waited on, any thread may release it, and Windows
removes it when the process holding it ends.

### Planning

- Each run makes exactly one planning call, `plan_steps(goal, model_summary)`,
  before step 1. The model is not asked to plan again during the run, so
  nothing read from the document after a step can change the run's direction.
  The one other call a run can make is the optional look after a step (below),
  whose answer can only end the run; it never adds, changes or skips a step.
- A network error, a 401, a 429 still failing after its retries, a timeout or
  an unparseable reply ends the run before anything has changed.
- The model summary refers to everything by handles that SolidSeas issues:
  `F12` (feature, sketches included), `D4` (dimension), `E37` (edge), `Fa9`
  (face), `P1` (plane), `A2` (axis). SolidSeas maps each handle to a persist
  reference (`GetPersistReference3`). The model never supplies a SOLIDWORKS
  name, id, persist reference, path or file name. SolidSeas builds names such
  as `D1@Sketch2` itself, so a name ending in `@<another document>` cannot be
  expressed. A handle that does not resolve to exactly one entity fails
  validation and is never matched again by name. Persist references are not
  always unique: in a new part, eight folder features return the same one
  (answer 6), so folders never get handles.
- The model does not name new features. They keep the names SOLIDWORKS gives
  them.
- The reply goes through `parse_json_response` and is validated against the
  plan schema for the current vocabulary version. The whole plan is validated
  before step 1. One invalid step refuses the whole plan, a plan longer than
  the step limit is refused rather than cut short, and values are never
  clamped.
- The reply is one JSON object,
  `{"vocabulary": 1, "steps": [{"op": ..., "args": {...}, "note": ...}], "notes": ...}`.
  `note` is the model's expected effect, kept for the log (at most 300
  characters, plain text); it never widens what verification allows. A reply
  with no steps is the model saying the goal cannot be done; its `notes` are
  shown and nothing runs. Unknown fields anywhere refuse the plan.
- Arguments are named in `solidseas/ai/prompts.py:OPERATIONS`: a length is
  `{"value": number, "unit": "mm" | "in"}`, an angle
  `{"value": number, "unit": "deg"}`, a handle a string and a list of handles a
  list. A profile is `{"unit": "mm" | "in", "segments": [...]}` in the sketch
  plane's own 2D coordinates, each segment a `line` (start, end), an `arc`
  (center, start, end, direction `ccw` or `cw`) or a `circle` (center, radius);
  lines and arcs must join end to end into closed loops within a micrometre,
  and the validator snaps each matched pair of end points to one point. The
  summary gives each plane and planar face its sketch X direction when the
  bridge reports it.

### Vocabulary, version 1

The vocabulary is a closed list, versioned together with the prompts in
`solidseas/ai/prompts.py` and the bridge. Adding an operation is a design
change: its schema, bounds, inverse and allowed differences go into this table
first.

| Operation | Arguments | Inverse recorded before the step | Allowed differences |
|---|---|---|---|
| `set_dimension` | dimension handle; value, as a length with unit or an angle in degrees | the dimension's value in the active configuration | that dimension's value in the active configuration, and geometry |
| `sketch_extrude_boss` | plane or planar face handle; closed profile of lines, arcs and circles, at most 64 segments; depth with unit; direction, normal or reversed; end condition blind | delete the new feature with its absorbed sketch | one new boss-extrude and its sketch; volume does not decrease; extents grow by at most the depth, along the extrude direction |
| `sketch_extrude_cut` | as for the boss; end condition blind or through all | delete the new feature with its absorbed sketch | one new cut-extrude and its sketch; volume does not increase; extents do not grow |
| `fillet` | 1 to 64 edge handles; radius | delete the new feature | one new fillet; extents do not grow; volume changes by at most radius² times the total length of the chosen edges |
| `chamfer` | 1 to 64 edge handles; equal distance | delete the new feature | one new chamfer; extents do not grow; volume changes by at most distance² times the total edge length |
| `shell` | 0 to 16 face handles to remove; thickness, inward | delete the new feature | one new shell; volume decreases; extents do not grow |
| `linear_pattern` | 1 to 8 seed feature handles; direction as an edge or axis handle; spacing with unit; count 2 to 50, seed included | delete the new feature | one new pattern; extents grow by at most (count minus 1) times the spacing, along the direction |
| `circular_pattern` | 1 to 8 seed feature handles; axis handle (an axis or a cylindrical face); count 2 to 50, equally spaced over 360 degrees | delete the new feature | one new pattern; extents stay inside the cylinder about the axis that reaches the seed's farthest point |
| `suppress`, `unsuppress` | 1 to 16 feature handles | the suppression state of each named feature and of its children (`IFeature::GetChildren`) | the suppression state, in the active configuration, of those features and their children, and geometry |
| `set_property` | property name; value of at most 64 printable characters; scope, file or active configuration | the property's previous value, or that it did not exist | that one property, and nothing else |

Rules that apply to every operation:

- Material, equations, configurations, the active configuration and custom
  properties (except for `set_property`) do not change. No dimension changes in
  any configuration except the one `set_dimension` names, and only in the
  active configuration.
- The number of solid bodies does not change, except that a boss in a part with
  no solid body yet creates the first one.
- Deleting a feature is part of an inverse even though delete is not in the
  vocabulary. The model can never ask for it, and SolidSeas only deletes
  features whose persist references it recorded creating in the same run. The
  inverse selects the feature by its persist reference and calls
  `IModelDocExtension::DeleteSelection2` with `swDelete_Absorbed`, so an
  extrude's sketch goes with it; without that option the sketch stays behind
  (answer 6).
- `set_property` never writes the properties downstream systems key on. The
  default list is part number and revision under their common names (`PartNo`,
  `Part Number`, `PartNumber`, `Number`, `Revision`, `Rev`), compared without
  case or spaces, and settings can add to it. It also refuses values that start
  with `=`, `+`, `-` or `@`, because those values end up in BOM CSV exports.

Never in the vocabulary: delete, save, open, close, insert part, derived or
mirrored part, anything that takes a path or file name, macros and macro
features, equation edits, material changes, adding or deleting
configurations, changes to SOLIDWORKS options, and anything that refers to
another document.

### Argument validation

All arguments go through one validator.

- JSON is parsed with a `parse_constant` that refuses `NaN`, `Infinity` and
  `-Infinity`, and every number must be finite after parsing, because `1e999`
  parses to infinity. A bool is refused wherever a number is expected. Range
  checks are written as `lo <= x <= hi`, so NaN fails them.
- Every length carries an explicit unit from an allowlist, `mm` or `in`, and
  SolidSeas converts it to the metres the API uses. Angles are in degrees.
- Default bounds, each adjustable in settings up to a hard ceiling: a length is
  more than 0.001 mm and at most 10 times the part's bounding-box diagonal (or
  1000 mm for a part with no solid body yet); an angle is more than 0 and less
  than 360 degrees; at most 200 new pattern instances per run; strings are at
  most 64 printable characters with no `@`, `"`, `\`, `/` or control
  characters. The ceilings are 50 steps, 1,000 new pattern instances, 100
  times the diagonal and 10,000 mm with no solid body; the smallest length can
  only be raised. Profile points lie within the same length bound of the
  sketch origin.
- A pattern's new instances are counted as (count minus 1) times the number of
  seed features, the most it can add.
- Every argument carries a source that the plan and the log show: "you said"
  when the value appears in the goal text (numbers compared after unit
  conversion, strings compared without case), otherwise "from the model".
  A number in the goal with no unit matches a value in the argument's own
  unit; "in" after a number counts as inches at the end of the goal, before
  punctuation or before a size word ("1.5 in wide"), and not before other
  words ("4 in each corner"); counts also match the words one to twenty.
  Handles and choices are always "from the model".

### When a plan starts by itself

The validated plan always appears in the window as a numbered list with every
argument and its source. Whether it then waits depends on what it would
overwrite:

- It starts by itself when its only steps that change something the user
  already has are `set_dimension` steps whose new value the user said. Adding
  and shaping operations (bosses, cuts, fillets, chamfers, shells, patterns)
  start by themselves, because verification bounds them and their inverses
  remove them cleanly.
- Any `suppress`, `unsuppress` or `set_property` step, and any `set_dimension`
  whose value came from the model, makes the run wait for one press of Run.
  That is the only point where Automatic mode stops to ask.
- The setting "Always confirm the plan before a run" makes every run wait. It
  is off by default.

Automatic mode is a deliberate, bounded exception to the
`untrusted-input-defaults` rule that a model never triggers a side effect
nobody confirmed. The user's goal, together with turning Automatic on, confirms
what the goal asks for. The gate above catches the overwrites the goal did not
spell out, which is where instructions planted in a vendor or customer part
would show up. The closed vocabulary, the one-part scope, verification and the
safety copy are the controls that hold whatever the model does.

### Executing a step

For each step, the bridge does the following in order:

1. **Check the binding.** The bound document is still open; it is the active
   document (if not, the run pauses until the user returns to it, and never
   acts on whatever is active); its active configuration is unchanged; nothing
   is being edited in it; no change notification arrived for it that SolidSeas
   did not cause; and its snapshot now equals the snapshot taken after the
   previous step (for step 1, the baseline). The snapshot comparison is the
   check and the notifications are an early warning, because `ModifyNotify`
   fires only when the document goes from saved to modified, and on a part
   that is already modified a dimension changed through the API raises nothing
   until a rebuild, which raises only `RegenPostNotify2` (answer 5).
   A notification counts as SolidSeas' own only when it arrives while the
   bridge's own call runs and is one that call is expected to raise:
   `AddItemNotify` for the step's new feature, `RegenPostNotify2` for its
   rebuild, `ModifyNotify` on the first change after a save, and, for the first
   checkpoint copy, `FileSavePostNotify` with the copy save type and the
   property notification for the internal property it sets. Timing alone is
   not enough, because another process's notifications arrive on a worker
   thread at any time, also during the bridge's own call (answer 5). Undo, save
   and close notifications (`UndoPostNotify`, `FileSaveNotify`, any other
   `FileSavePostNotify`, `DestroyNotify2`) are never SolidSeas' own: it never
   undoes, saves or closes the bound part. A lost-events line from the bridge
   counts as a change SolidSeas did not make. Stop, the step limit and the run
   deadline are checked here. `GetSaveFlag` is read on every other open
   document (`GetDocuments`).
2. **Record the inverse** in memory and append it to the journal, flushed and
   synced. If the inverse cannot be recorded, the step does not run.
3. **Hold SOLIDWORKS options.** Some options turn unattended API calls into
   interactive ones. With Input dimension value on
   (`swInputDimValOnCreate`), adding a dimension opens the Modify box and the
   call waits for the user. With Show errors every rebuild on
   (`swShowErrorsEveryRebuild`), a failed rebuild opens a dialog. With sketch
   inference and automatic relations on (`swSketchInference`,
   `swSketchAutomaticRelations`), sketched geometry snaps to nearby edges. The
   bridge reads each with `GetUserPreferenceToggle`, sets the value the step
   needs, sketches with `ISketchManager::AddToDB` set to true, and restores the
   user's values in a finally block. The original values are written to a
   state file at the start of the run, following `state-file-pattern`, so the
   next attach restores them if the bridge crashed or was killed.
4. **Lock the document** with `IModelDoc2::Lock`, and `UnLock` in a finally
   block. Lock stops modifying commands given in the SOLIDWORKS user
   interface: in the spike, Suppress and Edit, Undo did nothing while it was
   held, though `RunCommand` still returned true. It does not stop selection
   clicks, or API calls from any process, the bridge's own included (answer 3).
   It keeps the user from editing the part mid-step, but neither it nor step 6
   keeps a click from changing the selection the feature call uses; step 8
   checks what the new feature was built from.
5. **Open a named undo entry** with `StartRecordingUndoObject`, closed with
   `FinishRecordingUndoObject2` with Hidden false in a finally block, so the
   step is one entry on the SOLIDWORKS undo list, for example "SolidSeas step
   3: fillet". One pair around a sketch and its extrude made exactly one entry,
   where the same calls without a pair made four; Hidden true merges the entry
   into the one before it, which may be the user's (answer 4). The return value
   is journaled: false means nothing was recorded. That is always so for
   `set_property`, because custom property edits are not on the undo list
   (answer 2), so a `set_property` step opens no entry, and the plan and the log
   say Ctrl+Z does not undo it. For any other step, false fails the step: its
   inverse is applied and the run stops, because without the entry the user's
   Ctrl+Z takes the step apart piece by piece (answer 4 measured a sketch left
   behind its extrude, which matches no snapshot).
6. **Select by persist reference** when the step needs a selection: clear the
   selection, select each entity by its persist reference, and check the number
   and type of selected entities immediately before the feature call. A
   mismatch fails the step. The check narrows the window but cannot close it:
   it and the feature call are two calls from another process, and a click the
   user makes between them is handled first, so the feature would be built on
   what the user clicked (answer 3). Where the documented API builds a feature
   from a definition object whose entities are set explicitly
   (`IFeatureManager::CreateDefinition` and `CreateFeature`, for the feature
   types that support them), the bridge uses that instead of the selection;
   which vocabulary operations that covers is checked against the API
   documentation before they are built.
7. **Make the feature call.**
8. **Verify** (below). First, the new feature's inputs are read back and
   compared, by persist reference, with the plan: a fillet's or chamfer's
   edges, an extrude's sketch plane or face, a shell's removed faces, a
   pattern's seeds and direction or axis. Any difference applies the inverse
   and stops the run. On any other failure, apply the inverse and end the run.
9. **Check other documents.** If any other open document became dirty during
   the step, the step is reverted and the run stops.
10. **Journal the result**, with the persist references of any features the
    step created, flushed and synced.

### Verification

Verification compares structural snapshots taken before and after each step.
A snapshot holds:

- the feature tree: persist reference, name, type, suppression state in the
  active configuration, and error code of every feature;
- every dimension's value in every configuration, read with
  `IDimension::GetSystemValue3` for named configurations, which neither
  switches configurations nor raises a notification (answer 7);
- the active configuration name, the file and configuration custom properties,
  the material, the equations, and the number of solid bodies;
- the What's Wrong list (`IModelDocExtension::GetWhatsWrong`);
- after `ForceRebuild3(False)` returns true: volume and surface area from
  `CreateMassProperty2`, with `IMassProperty2.SelectedItems` set to the solid
  bodies from `IPartDoc::GetBodies2(swSolidBody, False)` so the user's
  selection is never touched; the face count; and extents from
  `IBody2::GetExtremePoint` along +X, -X, +Y, -Y, +Z and -Z for each body.

Bodies are matched as a set, not by position: `GetBodies2` returned the same
part's bodies in a different order after it was reopened from its copy. A new
extrude is recognised by its type together with the sketch it absorbs:
`IFeature::GetTypeName2` returned `Extrusion` for the boss that made the first
body and `ICE` for later bosses and cuts, and `GetTypeName` returned `Boss` for
those later bosses (answer 6).

`GetPartBox` and `GetBodyBox` are not used; their documentation says the values
are approximate and not for comparison. A part with no solid body yet is a
defined state (volume 0, no extents), not an error. Lengths are compared within
1 micrometre, and volume and area within one part in a million.

Before the snapshots are compared, the new feature's inputs are compared with
the plan (step 8), because a wrong but similar input, such as the neighbouring
edge of the one planned for a fillet, can stay inside the volume and extent
bounds below. What a step may change comes from the vocabulary table, applied
to the validated arguments by SolidSeas code. The model may describe the
effect it expects, for the log, but that never widens the limits. The step
fails, and its inverse is applied, on any other difference, any new What's
Wrong entry, a rebuild that returns false or does not finish, or any value
that cannot be read. When in doubt the run stops; it never guesses forward.

### A look after each step

An optional second look at the shape, beside verification and never instead of
it. The idea comes from Millwright's vision loop (github.com/raylanlin/Millwright);
none of its code is used.

- **Off until ticked.** The window's "Show it the part after each step" box
  shows in Automatic mode only, is usable only while "Show the AI a picture of
  the part" is ticked, and is unticked with it. Under `DisableImages` both are
  greyed out with "Set by your administrator", and the policy is read again
  before every picture, so a policy that arrives during a run stops the looks
  that follow.
- **When.** After a step passed verification and its result is in the
  journal, and only then. A step that failed is taken back without a look, and
  no look is taken once Stop was pressed.
- **The picture.** The bridge writes a copy of the part as it is now, unsaved
  changes included, with the same `live_checkpoint` call that writes checkpoint
  0 (`SaveAs3` with the copy and silent options, which leaves the open part, its
  path, its saved state and its undo list alone). The copy is
  `checkpoint-<run id>-step-<k>.sldprt` in the run folder, the only folder and
  the only names the bridge writes a copy under, and it stays there with
  checkpoint 0. SolidSeas draws it as it draws the picture sent with a plan
  (`solidseas_app.assistant.picture.drawn`: grey, front, right and above, no
  text, at most 800 pixels a side), captioned "the part after step k, drawn from
  a copy SolidSeas saved after the step". The user's own file is never drawn
  for a look: a run never saves, so it would show the part as it was before the
  run.
- **The call.** `check_step(goal, step, k, n, image)` on the person's provider,
  through the same call path as every other (`ModelProvider._run`: policy,
  budget, cancellation, parsing). The prompt (`prompts.look_prompt`,
  `LOOK_SYSTEM`) holds the goal as the planning call sent it, the step as the
  Plan panel shows it, and the picture: no summary, no names, no paths. The
  output cap is 512 tokens, and the looks share one run budget of the run token
  setting (30,000 by default). Stop cancels a look in flight.
- **The answer.** `{"as_expected": true | false | null, "reason": "..."}`,
  read by `prompts.parse_look`, which refuses any other field, a verdict that
  is not true, false or null, and control characters, and cuts the reason at
  300 characters. False ends the run with the status `looks_wrong` after that
  step: the step passed its checks and stays in the part, and the person
  chooses Keep or Revert as after any run. True, or null (the model cannot
  tell, or cannot see pictures), lets the run go on.
- **A look that cannot be made** (the copy, the drawing, the policy, the
  budget, the deadline, a provider error, a refused reply) is journaled as
  `look_failed`, said in the log, and the run goes on: verification decides a
  step, the look only adds evidence.
- **The journal** keeps each look as `step_looked`: the verdict, the reason,
  the picture's line, the prompt sent and the tokens.
- **Costs.** One more model call with a picture per step (about 1,000 input
  tokens for the picture), one more copy per step, which takes SOLIDWORKS a
  moment and raises `FileSavePostNotify` to add-ins as checkpoint 0 does, and a
  second or two to draw it.
- **Through the MCP server**, `run_plan` with `"pictures": true` makes the same
  copies and pictures after each step, asks no model, and returns the pictures
  to the chat, whose own model looks at them (`docs/MCP.md`).
- **Not built: SOLIDWORKS' own view.** A `live_capture` operation in the bridge
  would save the graphics view as a PNG into the bridge's temp folder, size
  capped, without a copy of the part. It needs SOLIDWORKS to build and measure.
  When it is built it becomes a second picture source
  (`picture.PictureSource`), tried first, with the drawn copy kept as the
  fallback.

### Checkpoints, journal and revert

- **Run folder.** `%LOCALAPPDATA%\SolidSeas\runs\<run id>\`, named by
  SolidSeas. No part of the path comes from the model, the goal or the document
  title, and the folder is outside the project folder and any PDM vault.
- **Checkpoint 0.** Before step 1, the bridge writes a safety copy of the
  document as it is now, unsaved edits included, with
  `IModelDocExtension::SaveAs3` and `swSaveAsOptions_Copy` plus
  `swSaveAsOptions_Silent`. That writes a copy and leaves the open document,
  its path and its unsaved state alone. The copy is named
  `checkpoint-<run id>.sldprt`, because SOLIDWORKS cannot open two documents
  with the same file name. The copy raises `FileSavePostNotify` with the copy
  save type to every listener, add-ins such as PDM included, which is one more
  reason the copy goes outside any vault. It raises no `FileSaveNotify`, so the
  save hold below does not stop it. The spike confirmed that the copy leaves
  the path, title, saved state, snapshot and undo list alone, for a part never
  saved and for one with a file, and that the copy holds the unsaved edits
  (answer 1). If checkpoint 0 cannot be written, or the copy is missing or
  empty when checked, the run does not start. The copy is never loaded back
  into the open document: no API does that without changing the document's
  path or discarding the user's unsaved edits. It can be opened as a separate
  document.
- **Journal.** `journal.jsonl` in the run folder gets one line per event: run
  started, checkpoint written, the prompt sent, the plan, confirmation, step
  started with its inverse, step result, revert, stop and end. Each line is
  flushed and synced to disk before the next action. The run's first line
  also names the part (the SOLIDWORKS process id, the document's key, title
  and path), holds the goal as it was sent when the window started the run,
  and holds the part's state before the run; each `step_done` line holds the
  state after the step (`run.state_of`: the feature tree, dimension values,
  face and edge references, bodies, volume, extents, configurations, custom
  properties, material and equations, which is what `run.differences`
  compares). A later start reads them to describe a run left open and to
  check the part before reverting it (Crashes and recovery, below). The
  journal stays on this PC and is never sent to a model.
- **Revert** works from the newest step backwards. "Revert to before step k"
  applies the inverses of the last step down to step k, because later features
  can depend on earlier ones; a middle step cannot be reverted alone. "Revert
  run" is revert to before step 1, one action. Revert never uses `EditUndo2`,
  which acts on the active session, counts undo entries that the user's own
  actions mix into, and in the spike removed one entry and then nothing more by
  any means (answer 4). It never closes and reopens the document, which would
  throw away edits the user had not saved.
- Before each inverse, SolidSeas checks that the document still matches the
  snapshot taken after that step. If it does not (the user undid, edited or
  closed it), SolidSeas stops, reverts nothing more, and offers to open
  checkpoint 0 as a separate document. After each inverse it compares the
  document with the snapshot taken before that step, and says so if they
  differ.
- Each step except `set_property` is also one named undo entry, so the user can
  Ctrl+Z it in SOLIDWORKS; Edit, Redo does not bring a recorded entry back
  (answer 4). An undo in the bound document that SolidSeas did not make
  (`UndoPostNotify`) stops the run, and the snapshots are re-checked before any
  revert is offered.
- **Retention.** The run folder is kept until the user chooses Keep or Revert,
  then for 7 days (`automatic.KEEP_DAYS`). While a run is open it holds a lock
  on `run.lock` in its folder, which the system lets go of when the process
  ends. When the assistant window or the MCP server starts,
  `automatic.clean_old_runs` removes, on a thread of its own, each folder in
  the runs folder that no run holds and in which nothing changed for 7 days:
  the journal's last line, Keep or Revert, starts the 7 days. A run whose
  process ended before Keep or Revert is offered when the assistant window
  next opens (Crashes and recovery, below); until the person chooses Keep or
  Revert it goes the same way, 7 days after its last change, and so does the
  safety copy of a Review mode script. Only folders
  directly in the runs folder and named like a run id are looked at. A link or
  junction, a folder on another drive, a folder whose real path is not in the
  runs folder, and a folder holding anything but plain files are left alone.
  Each file is removed by name, the safety copies first, and then the empty
  folder; nothing is removed through a link. A copy open in SOLIDWORKS cannot
  be removed, so that folder stays whole until the next start.

### Stop, limits and timeouts

- Limits per run, checked between steps: steps (20 by default, at most 50), a
  run deadline (15 minutes by default, planning included), a token budget
  (30,000 by default), and 200 new pattern instances.
- Stop is a button and a global hotkey (Ctrl+Alt+F12 by default) registered
  with Win32 `RegisterHotKey`, so it works while SOLIDWORKS has focus; a Qt
  shortcut fires only while the assistant has focus.
- Stop cancels a provider call in flight at once. Otherwise it takes effect at
  the next boundary between SOLIDWORKS calls: the current step finishes and is
  verified or rolled back, and no other step starts. A call from another
  process into SOLIDWORKS cannot be cancelled once it is running, and the
  window says "Stopping after the current step".
- A step that runs past its soft limit (60 seconds by default) is marked
  overdue in the log. When it returns, it is rolled back and the run ends.
- A single call that runs past the hard limit (10 minutes by default) makes the
  app kill the bridge and mark the run interrupted, with the document in an
  unknown state, and offer checkpoint 0 and the journal. SOLIDWORKS still
  finishes that call; SolidSeas never ends SOLIDWORKS.

### The user working at the same time

The user can watch, work in other programs, or work in other documents in the
same SOLIDWORKS. SolidSeas cannot lock the run's document between steps, so it
watches instead. The bridge listens to the bound document's change
(`AddItemNotify`, `DeleteItemNotify`, `RegenPostNotify2`, `ModifyNotify`, and
the custom property and configuration notifications), save (`FileSaveNotify`,
`FileSavePostNotify`), undo (`UndoPostNotify`) and close (`DestroyNotify2`)
notifications, and to the session's `ActiveDocChangeNotify`. The spike saw each
of them arrive from another process's changes while the bridge was idle
(answer 5).

- Switching to another document pauses the run until the user comes back,
  because selection and some feature calls act on the active document.
- Any change to the bound document that SolidSeas did not make stops the run
  after the current step. A notification shows it at once, and the snapshot
  comparison in the next binding check shows it in any case.
- Closing the bound document stops the run.
- A run will hold saves of the bound document, once the two cases below are
  measured; until then the hold is not built. While it holds, from the moment
  checkpoint 0 is written until no step or revert is running any more, the
  bridge's `FileSaveNotify` handler returns `S_FALSE` for that document, and
  SOLIDWORKS cancels the save: the file is not written and the document stays
  modified. The spike held File, Save, Save All and a `Save3` from another
  process this way (answer 8). Nothing saves it later: SOLIDWORKS does not
  repeat a cancelled save, and a run never saves the user's document. So the
  window says "Your save was not done; save again after the run", says where
  checkpoint 0 is, and offers Stop; the log records each cancelled save, and
  the run carries on. The hold lives in the bridge process, so it also ends if
  the bridge exits or is ended.
- Until the hold is built, a save of the bound document goes through. The
  bridge records it as a change SolidSeas did not make, the run stops after
  the current step, and the window says where checkpoint 0 is.
- Save As is not held. `SaveAs3` to another file raised neither
  `FileSaveNotify` nor `FileSaveAsNotify2`, wrote the new file and moved the
  document to it; the File, Save As command, which opens a file dialog, was not
  tried. The run sees `FileSavePostNotify` with the Save As type, or the
  changed path at the next binding check, and stops. The user's original file
  is untouched, and checkpoint 0 is the way back.
- Not yet measured, and the hold waits for both: what closing the part, or
  exiting SOLIDWORKS, with modified documents and "Save changes? Yes" does
  while a save is held, and whether a visible session tells the user that a
  save was cancelled. If SOLIDWORKS goes on closing after the cancelled save,
  the user's confirmed save silently does not happen and the open document is
  gone, recoverable only from checkpoint 0. Measuring needs that dialog
  answered in a visible session, which a hidden instance cannot give. When the
  hold is built, it is released as soon as a close or an exit starts (through
  a command pre-notification such as the application's `CommandOpenPreNotify`,
  if it fires for those commands), so a save the user confirms on closing
  always goes through. The close stops the run either way (`DestroyNotify2`).

### Crashes and recovery

The journal is synced at every event. A run is left open when its process
ends before the person chooses Keep or Revert: SolidSeas crashed or was ended,
during the steps or after them. (Closing the window or ending an MCP chat
keeps a finished run, so that does not leave one open.) Its journal then has
no `kept` or `reverted` line, and the lock on `run.lock` went with the
process.

`solidseas_app/assistant/unfinished.py` finds and offers such runs:

- **Finding them.** When the assistant window opens, a worker thread first
  removes old run folders (`clean_old_runs`) and then calls
  `find_unfinished`. It looks at the runs folder the way the clean does: only
  folders directly in it, named like a run id, that are plain folders whose
  real path is in it, with a plain `journal.jsonl`. It takes hold of each with
  `RunHold.claim`, the lock on the folder's existing `run.lock`. A folder a run
  still holds, in this process or another, cannot be claimed and is left
  alone, untouched; so is one with no `run.lock` (a Review mode script's, or a
  run's from before runs took a lock). A claimed folder whose journal does not
  start with `run_started`, or has a `kept` or `reverted` line, is let go
  again. The window keeps the hold until the person chooses or the window
  closes, so a second window does not offer the same run and nothing removes
  its folder meanwhile. Claiming writes nothing, so it does not move the day
  the folder is removed.
- **The offer.** A box at the top of the window shows the runs one at a time,
  oldest first, as plain text from the journal: the part's title and path,
  when the run started, the goal (or the plan's notes for a plan from a chat),
  each step as the Plan panel shows it with what became of it (done and
  checked, failed and taken back, reverted, running when SolidSeas closed, not
  run), how far it got and how it ended, where checkpoint 0 is, what each
  choice does, and the day the clean may remove the folder (7 days after its
  last change). Nothing is done to the run until the person presses one of
  three buttons.
- **Revert** goes through `AutomaticRun.revert`, the same path as Revert after
  a run, on a run put back together from the journal
  (`AutomaticRun.recovered`): each done step's inverse, newest first, with the
  check before each inverse and the comparison after it. Before that, and
  without changing anything, it refuses and says why when: the journal has no
  part states (a run from before they were journaled) or an inverse it cannot
  apply; there is no bridge; the part is not open in SOLIDWORKS (the same
  process and document key, or, for a part with a file, the same path in any
  SOLIDWORKS); the session is held by another run (the one-writer mutex); or
  the part's snapshot differs from the state after the run's last done step,
  or before the run when no step was done. That last check is what makes it
  safe after a crash in the middle of a step: if that step changed the part,
  the part no longer matches and Revert refuses, pointing at checkpoint 0. A
  refusal writes nothing, and the run stays on offer. A revert that starts
  closes the run as `reverted`, as after a run, even if it stops part way, and
  the log says where it stopped. With no step done and none running, Revert
  has nothing to take off and only closes the run. Checkpoint 0 is never
  copied over the part or loaded into it.
- **Keep** writes `kept` to the journal (with `after_restart`), which starts
  the folder's 7 days again, and changes nothing in SOLIDWORKS.
- **Decide Later** lets go of the folder and writes nothing; the run is offered
  again the next time the window opens, until the clean removes the folder.

The MCP server does not look for these runs and does not report them in a tool
result: a chat's model cannot see the person's screen, and the choice belongs
to the person. It never claims or touches their folders; the window offers
them when it next opens.

The SOLIDWORKS options are not held during a step yet (What is built, below),
so there are none to restore after a crash. The undo entry and the part's lock
of a step that was running are in the bridge's own state file, and a bridge
started after one that ended closes the entry and unlocks the part.

### Ending a run

A run never saves the user's document. It leaves the document modified and
unsaved, with the run folder. The user chooses Keep, which forgets the inverses
but keeps the folder for the retention period, or Revert. Saving stays the
user's decision, in SOLIDWORKS.

### What is built

`solidseas_app/assistant/run.py` carries a started run out: the binding check
(active, not editing, the snapshot as the last step left it), the inverse
journaled before each step, the step in its own undo entry with the part
locked (both recorded in a state file first, so a bridge started after one
that was ended closes the entry and unlocks the part), verification against
the vocabulary table, a failed step taken back at once, Stop between steps,
the run's deadline and the step's soft limit, and Keep and Revert. The window's
Automatic box plans the goal, shows the plan with every argument's source,
starts a plan the gate lets through and waits for Run plan otherwise.
Measured on 2026-10-11 in SolidSeas' own SOLIDWORKS (`tests/test_swapi_live.py`):
a four-step plan (a fillet, a boss on a face, a dimension, a property) carried
out and checked, each step but the property recording its undo entry, and
reverted to the state before the run exactly; a fillet SOLIDWORKS cannot make
leaves the part as it was and ends the run.

Found on the way: a step can give an entity a new persist reference while the
old one still resolves to it (the top face of a block after a fillet on its
edges), so the run maps a step's references to their present ones
(`live_current_refs`) before it records the inverse, runs the step and checks
it. Two checks are made another way than step 8 says, because reading a
feature's own inputs back needs `AccessSelections`, which rolls the part back
until it is released: an extrude's extents are bounded by the profile placed in
the frame the bridge used, and a fillet or chamfer must have consumed exactly
the planned edges, which a neighbouring edge cannot fake.

A run left open by a crash is offered when the window next opens, with Revert,
Keep and Decide Later (Crashes and recovery, above): `unfinished.py`, on the
part states and the part's identity the journal now keeps, and Revert through
`AutomaticRun.revert`. It is tested against the part held in memory only; a
recovered revert has not been measured in a real SOLIDWORKS, in particular
whether persist references still match after SOLIDWORKS was restarted and the
part reopened (if they do not, the state check refuses, and checkpoint 0 is the
way back).

The look after each step (above) is built on the bridge's existing copy, with
SolidSeas' own drawing of it. SOLIDWORKS' own view through the bridge
(`live_capture`) is not built.

Not built yet: the global Stop hotkey (the window's Stop button works), holding
the person's SOLIDWORKS options during a step, holding saves, pausing while the
part is not the active document (the run ends instead), the notifications as
an early warning between steps (the snapshot comparison is the check), and the
shell and pattern operations.

## SolidSeas as an MCP server

`SolidSeasViewer.exe --mcp` serves a chat in Claude Desktop, Claude Code or another MCP
client over standard input and output: the chat lists the SOLIDWORKS sessions, reads a
part's summary and hands over plans, which SolidSeas validates and carries out as Automatic
runs, with every rule above. A plan that would overwrite something the person has waits for
them in a box of SolidSeas' own on their PC. `docs/MCP.md` has how to connect a client, the
tools and what each returns.

## What leaves the machine

- Only `solidseas/ai/context.py:build_model_summary` puts document data into a
  prompt.
- It sends what planning needs: handles, feature types and parameters with
  units, dimension values, the units, the bounding box and volume, reference
  planes and axes, and the edges and faces of the solid bodies with a compact
  geometric description (type, end points or centre and radius, length or
  area), in millimetres and degrees.
- It copies those fields out of the bridge's snapshot one by one, so anything
  else the snapshot holds cannot reach a prompt. A feature parameter goes only
  as a number with its unit, a bool, or a word from a short allowlist of end
  conditions and directions; any other text, which could be a path or a name,
  is left out. A type name that is not a plain identifier goes as `Other`.
- It never sends file paths or file names, custom property values,
  configuration property values, author or company fields, the preview images
  stored in the file, sketch text or annotation text, the material, equations
  or persist references.
- A picture of the part goes only when the person ticks "Show the AI a picture
  of the part" for that request, which is off until they do, and never when
  the machine policy sets `DisableImages`. It is a PNG SolidSeas draws itself
  (`solidseas.render`): the part shaded in grey from the front, right and
  above, on a plain background, with no text, file name or dimension in it,
  at most 1568 pixels a side and 2 MB (`prompts.part_image` checks both). It
  shows the part's shape, which the summary already describes in numbers. A
  model that cannot see ignores it. The panel and the journal show a line in
  its place, with its size; the token estimate counts it before the call.
  It is drawn from the part's file as it was last saved
  (`solidseas_app.assistant.picture`, through the meshes 3D Print makes), so
  changes not yet saved in SOLIDWORKS are not in it, and its caption says so; a
  picture of SOLIDWORKS' own view, unsaved changes included, through the
  bridge, is still to come. One that cannot be made is said in the log, and the
  request goes without it. The chat server's `show_part` tool gives the same
  picture.
- With "Show it the part after each step" also ticked, an Automatic run sends
  one more request after each step that passed its checks: the goal, that step
  as the Plan panel shows it, and a picture drawn the same way from a copy of
  the part saved after the step ("A look after each step" above). "What the AI
  sees" says so under the planning prompt, and the journal keeps each request.
- Names the user typed (features, sketches, configurations, custom property
  names) are replaced by handles unless the user ticks "Send my feature and
  property names" for that run. When ticked, names go only as quoted strings in
  a separate JSON field marked as document data, each cut to 64 characters
  with control characters removed. SolidSeas cannot tell a default name from a
  typed one, so every name counts as typed: features and sketches, reference
  planes and axes, dimensions, configurations and custom property names (never
  their values). `<` and `>` in the summary are escaped, so nothing in it can
  close the `<document_data>` block.
- The summary is capped (20,000 characters by default) before the budget
  check. A part too large for the cap is refused with a message, not partly
  summarized.
- The request text is capped at 4,000 characters and redacted before sending:
  SSNs, EINs, bare nine-digit numbers and Luhn-valid card numbers, as in
  `ai-prompt-to-record`. A longer request is refused rather than cut, so what
  is sent never means less than what was typed, and control characters are
  removed.
- Document data goes into the prompt inside a delimited block, and the prompt
  tells the model it is data, not instructions. That helps, but the closed
  vocabulary, the one-part scope and the confirmation gate are the controls.
- The window's "What the AI sees" panel shows the exact prompt for the next
  call, and the run journal keeps the prompt that was sent.

## AI connector: `solidseas.ai`

Optional, installed with the `[ai]` extra. The format readers, catalog, BOM,
versions and integration surfaces never need it. When no provider is
configured, every AI control is hidden, so nothing is offered that cannot work;
the assistant window says so and offers the AI settings page instead. When a
provider is configured but the machine policy forbids it, or forbids Automatic
mode, the affected controls stay visible, disabled, with "Set by your
administrator".

It follows the `` pattern:

- `solidseas/ai/base.py` defines the `ModelProvider` interface and imports no
  provider SDK. Only `health_check` is abstract, and its result is cached for
  an hour. Every task method returns `None` by default, meaning the provider
  does not support that task; callers treat `None` as a capability gap and say
  so plainly, never as an error.
- Tasks: `draft_change(context, request)` returns code and an explanation for
  Review mode; `plan_steps(goal, model_summary)` returns a plan for Automatic
  mode; `check_step(goal, step, index, count, image)` returns the model's look
  at a picture of the part after a step ("A look after each step").
- `solidseas/ai/prompts.py` owns every prompt, every reply parser and the
  vocabulary version. All providers import them, so every provider is asked for
  identical JSON.
- Providers: Anthropic, OpenAI, Gemini, and Ollama for local use, each in its
  own module, plus a `noop` provider served, with its reason, when nothing is
  configured or a provider cannot be used. No provider SDK is used: each
  speaks HTTP through the standard library's `http.client`, in
  `solidseas/ai/http.py`, so the connector needs no package but the optional
  `truststore`. No model is chosen by default; the settings name one.
- `solidseas/ai/fake.py` holds the scripted provider tests use. It takes the
  same path as a real provider (the policy guard, the budget check, usage
  recording and the parsers).
- `solidseas/ai/factory.py` is the only place a provider is built. It caches
  the provider, is reset after any change to AI settings, and is one of the two
  places the machine policy is enforced. Every provider it builds carries a
  guard from the factory that reads the policy again before each call and
  health check, so the cache never outlives a policy change. A provider also
  makes the same check itself, from its own kind and address, so one built
  any other way still obeys the policy, and `health()` reads the policy before
  it looks at its cached result.
- Every reply goes through one `parse_json_response`, never bare `json.loads`,
  because models wrap JSON in code fences at random. It refuses non-finite
  numbers, and it reads a reply (at most 400,000 characters) in time linear in
  its length, so a hostile or broken reply cannot stall the app, whose threads
  all wait while a regular expression runs.
- Model replies are untrusted input. They are validated against a schema and
  allowlists, never allowed to choose a file path, URL or document id, and
  shown only as plain text.
- Budgets are enforced, not only checked. The request text and the summary are
  capped before the budget check, and each call is sent with an output cap no
  larger than the tokens left in the monthly budget and, in Automatic mode, the
  run budget. Usage is recorded in monthly buckets in
  `%LOCALAPPDATA%\SolidSeas\usage.json`, written under the cross-process lock
  from `state-file-pattern` with a write to a temp file then a replace, so two
  open SolidSeas windows cannot lose an increment. Recording usage never raises
  into the call path.
- The check and the hold are one step. Each call sets its input estimate plus
  its output cap aside, in the run's budget and, for a cloud provider, in
  `usage.json` under the same lock it was checked under, and the usage the
  provider reports replaces the hold when the call ends. Calls in flight at
  once, in one window or in two, therefore cannot each be granted the whole
  remainder. A hold left by a window that closed mid-call lapses after 10
  minutes, longer than any call can last.
- A call that fails after the request reached the provider (a timeout or Stop
  once it was sent, or a successful reply that could not be read) is charged
  its input estimate plus its output cap, because the provider may bill for it
  and reported nothing; a refusal the model sent counts its reported usage. A
  call the provider answered with an error status, or never received, costs
  nothing. Stop pressed while the reply arrives discards the reply.
- How the budgets work out: the input is estimated high (three characters a
  token), and a call that cannot get 256 output tokens is refused before it is
  sent. Months are calendar months in UTC. A monthly cost budget, in dollars,
  is optional: with prices per million input and output tokens set for the
  model it caps the output at what the remainder pays for, and without prices
  it refuses every cloud call, because it cannot be checked. The monthly
  budgets apply to cloud providers; Ollama runs locally and is counted but not
  limited. The run budget applies to every provider. A usage file that is not
  valid JSON is kept as `usage.damaged.json` and counting starts again; one that
  cannot be read refuses calls until it can.
- Every provider call has a connect timeout of 5 seconds and a read timeout of
  60 seconds for cloud providers or 180 seconds for Ollama, and must finish
  within the two together, so a reply that trickles in cannot hold a call
  open. An Automatic run also has its total deadline. The exchange runs on a
  worker thread that the caller stops waiting for the moment Stop is pressed,
  because a blocked socket read on Windows does not wake when its socket is
  shut down from another thread.
- On HTTP 429 the client honours Retry-After, backs off with jitter, and gives
  up after a few tries: four in all, and at once when Retry-After asks for more
  than 30 seconds or would pass the run's deadline. 503 and 529 (overloaded)
  are retried the same way. On 401, and on 403, it stops and tells the user.
  Spare keys exist for planned rotation, never for spreading load past a rate
  limit.
- **Keys.** API keys live in Windows Credential Manager, one generic
  credential per provider named `SolidSeas/<provider>`, never in settings
  files, the repository, the environment or the registry.
  `solidseas/ai/credentials.py` reads and writes them with `CredReadW` and
  `CredWriteW` through ctypes, with `CRED_PERSIST_LOCAL_MACHINE`, so a key stays
  on the PC it was entered on and does not roam with a roaming profile; on a
  second PC the user enters it again. A key read back is a `Secret` whose
  `repr` and `str` hide it. Each provider is constructed with its key passed
  explicitly and never reads an environment variable such as
  `ANTHROPIC_API_KEY`. Keys travel in a request header, never in a URL. The
  settings page (below) says only "A key is stored" or "No key is stored"; an
  empty field means unchanged, and Remove Key is a separate button. No key,
  and no request URL with a query string, is written to the live log, an
  error message or a support bundle; a
  provider's own error text is quoted only for statuses other than 401 and 403
  (a 401 body can echo part of the key), and the key and anything shaped like
  one are removed from the whole text before it is cut to 200 characters, so
  the cut cannot leave a piece of a key behind.
- **Managed networks.** The app's `main` calls `truststore.inject_into_ssl()`
  before anything builds an SSL context, so provider calls trust the Windows
  certificate store and work behind a TLS-inspecting proxy; the connector also
  builds its own context with `truststore.SSLContext` whenever `truststore` is
  installed, and with TLS 1.2 at least. Proxies come from the environment and
  the static WinINET setting (`urllib.request.getproxies`) and are passed to
  the HTTP client explicitly, through CONNECT; a user and password in the proxy
  URL are sent as Basic proxy authentication. PAC, WPAD and NTLM proxy
  authentication are not supported in the first release, and a connection
  failure says so plainly instead of reporting a bad key.

## Machine policy

On a managed PC an administrator can set values under
`HKLM\SOFTWARE\Policies\SolidSeas`:

| Value | Type | Meaning |
|---|---|---|
| `DisableAutomaticMode` | DWORD | 1 makes Automatic mode unavailable |
| `LocalProviderOnly` | DWORD | 1 restricts SolidSeas to a local Ollama provider |
| `AllowedProviderHosts` | REG_MULTI_SZ | Host names that also count as local, for an approved internal Ollama server |
| `DisableImages` | DWORD | 1 stops pictures of the part being sent to any provider or returned to a chat |

Reading it, in `solidseas/policy.py`, following `fail-closed-machine-policy`:

- The key is opened with `KEY_WOW64_64KEY`, so every build reads the same
  registry view. The reader opens the key and lets the exception decide; it
  never checks existence first.
- `FileNotFoundError` from `OpenKey` means no policy and no restriction. Any
  other `OSError` on the key, access denied included, means every restriction
  is on and no extra hosts are allowed.
- For each value, `FileNotFoundError` from `QueryValueEx` means that value is
  not set. A value of the wrong registry type, or a DWORD other than 0 or 1,
  means that restriction is on. `AllowedProviderHosts` of the wrong type counts
  as empty.
- The reader returns one frozen
  `Policy(automatic_disabled, local_only, allowed_hosts, images_disabled, locked, error)`. When
  `error` is set, the settings page shows it with the key path. `locked` is
  true when the key exists or could not be read: an administrator manages
  these settings. `AllowedProviderHosts` entries are compared in lower case
  without a trailing dot; an entry that is not a host name or an IP address
  is ignored, and at most 32 are used.
- A reader substituted with `set_reader` that raises, or returns something
  other than a `Policy`, means every restriction is on. Off Windows there is
  no registry and no policy, as when the key is absent.
- `policy.current()` reads the registry on every call, at the start of every
  run and before every model call, so a policy pushed by Group Policy while the
  app is open applies to the next call. Tests substitute the reader with
  `policy.set_reader()`.

Enforcement lives in two chokepoints and nowhere else: the provider factory,
which refuses any provider but a local Ollama under `LocalProviderOnly` and
serves `noop` with the reason, and `start_run`, which refuses under
`DisableAutomaticMode`. The UI only reflects the result. A search for provider
construction and for callers of `start_run` proves there is no other path, and
the security review records that command. Behind the factory, every provider
also applies `LocalProviderOnly` itself, from its own kind and address, before
each call and health check, so a provider built some other way would fail
closed rather than ignore the policy. `DisableImages` is applied in the same
place, the one call path every provider takes (`ModelProvider._run`): a prompt
that carries a picture is refused before anything is sent. The window and the
MCP server read it as well, so that under it no picture is made at all: the tick
boxes are greyed, a look after a step is not taken, `show_part` refuses and
`run_plan` returns no pictures.

Local means the Ollama base URL's host is `127.0.0.1`, `::1`, `localhost`, or
exactly one of `AllowedProviderHosts`; any other loopback literal
(127.0.0.0/8, or its IPv4-mapped IPv6 form) counts as loopback too.
`localhost` must resolve only to loopback addresses, the connection goes only
to the addresses that were checked (127.0.0.1 first), and the Ollama client
never uses a proxy, so a call to localhost cannot leave through one. This is
checked on every call. Any cloud provider is refused, and so is an Ollama host
that is neither loopback nor listed. Without the policy, Ollama may be any
host the user sets, over `http://` or `https://`; plain HTTP is allowed only
to that host, and every cloud provider must use HTTPS. Over `http://` to
another machine, each request, the part's summary included, crosses the
network unencrypted, where anyone on the way can read it: keep Ollama on this
machine, or put it behind a server that speaks HTTPS and give that address.

The settings page is to offer "Lock for all users" (not built yet), which
starts `solidseas-app --set-policy` with the `runas` verb, so UAC asks for that
one step; the GUI itself never runs elevated. The entry point checks
`IsUserAnAdmin`, writes the values plus `SetBy` and `SetAt`, and exits. The
dialog shows the key path, since Group Policy or Intune is the usual way to
deploy it.

What the policy is not: it removes SolidSeas's own ability to send model data
off the machine and to run Automatic mode. It is not a sandbox. Code a person
approves in Review mode or the CadQuery workspace runs with the user's rights
and can open any connection, another local program could forward requests to
the internet, and anyone who can edit the key can undo it. Where a hard
guarantee is needed, pair the policy with an outbound firewall rule for the
SolidSeas executable.

## The window

- Always on top through `Qt.WindowStaysOnTopHint`. It is never owned by or
  parented to the SOLIDWORKS frame window: a cross-process owner attaches the
  two programs' input queues, so a busy SOLIDWORKS would freeze the assistant
  and its Stop button.
- When a bridge call has waited more than 3 seconds, the window drops its
  always-on-top flag and says SOLIDWORKS is busy or showing a dialog, so it
  never covers a SOLIDWORKS dialog the user has to answer. The flag comes back
  when the call returns.
- Text from the model, and text from the document, is shown only as plain
  text. Labels and message boxes use `setTextFormat(Qt.TextFormat.PlainText)`,
  the log uses `QPlainTextEdit.appendPlainText`, editors use `setPlainText`,
  and tooltips, which have no plain mode, get the text through `html.escape`.
  Qt's default `AutoText` renders anything that looks like HTML as rich text,
  which follows links and loads images by path; an image from a UNC path sends
  an SMB request with the user's NTLM credentials. No model or document string
  is ever passed to the WebEngine 3D viewer.
- A "What the AI sees" panel, a live log, the plan with each argument's
  source, and Stop.
- Beside "Send my feature and property names", "Show the AI a picture of the
  part", off until ticked, and in Automatic mode "Show it the part after each
  step", usable only while the first is ticked. Under `DisableImages` both are
  greyed out, with "Set by your administrator" as their tooltip. "What the AI
  sees" shows a line for each picture in its place, and for the looks after
  steps, what each of those requests holds.
- An AI Settings button that opens the AI settings page (below). Whenever
  drafting is not available (the factory served `noop`), the window says why
  in plain text, from the provider's reason, beside a button that opens the
  page: "No AI provider is set up" when none is, the provider's message (no
  key, a setting, the machine policy) otherwise. The window builds its
  provider from the saved AI settings through the factory, and again whenever
  the page saves a change.
- The viewer opens the window from Tools > Modeling Assistant and its
  toolbar's Assistant button, one window at a time (pressed again, they bring
  it forward), and the executable opens it on its own with
  `SolidSeasViewer.exe --assistant`, as `python -m solidseas_app.assistant`
  does.

## The AI settings page

One page, `solidseas_app/assistant/settings_dialog.py`, opened from the
viewer's Settings > AI Settings and Tools > AI Settings and from the assistant
window's AI Settings button. It holds:

- **Provider**: none, Anthropic, OpenAI, Gemini or Ollama.
- **Model**, filled in when a provider is chosen from one table of defaults
  (`SUGGESTED_MODELS` in `solidseas_app/assistant/aisettings.py`), which the
  person can change; the page says to check it against the models the
  provider offers them. Each default passes the model name check.
- **Ollama address**, shown only for Ollama.
- **API key**, for the cloud providers: a masked field that is never filled
  in and never shows a stored key. The page says only "A key is stored" or "No
  key is stored". A key typed and saved is stored through
  `solidseas.ai.credentials` (Windows Credential Manager,
  `SolidSeas/<provider>`); an empty field leaves the stored key as it is;
  Remove Key removes it at once. A key that is not valid is refused without
  being repeated.
- **Test Connection**, which runs the provider's health check on a worker
  thread with what the page shows (a key typed and not yet saved included,
  held only in memory for the check) and says the result as plain text. Cancel
  stops waiting for it; the window never waits.
- **The monthly budget**: tokens, and optionally dollars with the model's
  prices per million input and output tokens, with this month's use read from
  the usage file on a worker thread.
- **The machine policy**, read when the page opens. Under `LocalProviderOnly`
  the cloud providers and the key field stay visible, greyed, with "Set by
  your administrator", and an Ollama address that is not local or approved is
  said to be refused. When `Policy.error` is set, the page shows it with the
  key path, `HKLM\SOFTWARE\Policies\SolidSeas`. Remove Key stays available:
  removing a key sends nothing anywhere.

OK and Apply save what changed and store a typed key, then call
`solidseas.ai.factory.reset()`, and the windows build their provider again.
Remove Key resets the factory too. Every label is plain text and every tooltip
escaped.

The settings other than keys live in `AI.json`, beside the viewer's
`Viewer.ini` in the roaming SolidSeas folder (`%APPDATA%\SolidSeas`): the
fields of `AISettings`, under the schema `solidseas.ai-settings/1`. It is a file
of its own, not a section of `Viewer.ini`, because the viewer rewrites
`Viewer.ini` from its own copy whenever one of its settings changes, and an
assistant window in another SolidSeas process would then undo a change the
other made. It follows the rules of `Viewer.ini` and the drawing settings: at
most 64 KiB of strict JSON (no repeated key, `NaN`, `Infinity`, number too
large to be finite or nesting deeper than 8 levels); each value checked on
its own by `AISettings`, a bad one falling back to its default with the
reason shown on the page; a member that is not an AI setting ignored; written
through a temporary file beside it and a rename, never through a link. A save
reads the file again and changes only the fields the page changed, so two
windows that each change something keep both changes. A viewer whose own
settings are kept in memory (tests) keeps its AI settings in memory too, and
the self-test, which runs with a settings file of its own, never reads or
writes the user's `AI.json`.

## Files and settings SolidSeas writes

| What | Where | Kept |
|---|---|---|
| Run folder: checkpoint 0, the copy after each step when the look after each step is on, `journal.jsonl` and `run.lock` | `%LOCALAPPDATA%\SolidSeas\runs\<run id>\` | Until Keep or Revert, then 7 days; removed when the assistant or the MCP server next starts. A run left open by a crash is offered by the assistant window until the person chooses, or until 7 days after its last change |
| SOLIDWORKS options held during a run | `%LOCALAPPDATA%\SolidSeas\sw-options.json` | Until the options are restored |
| Usage | `%LOCALAPPDATA%\SolidSeas\usage.json`, with `usage.json.lock` beside it | Monthly buckets, the last 24 months; a call's hold until it ends, at most 10 minutes |
| AI settings: provider, model, Ollama address, budgets and limits, never a key | `%APPDATA%\SolidSeas\AI.json`, beside the viewer's `Viewer.ini` | Until changed on the AI settings page; roams with a roaming profile |
| API keys | Windows Credential Manager, `SolidSeas/<provider>` | Until cleared; stays on this PC and does not roam |
| Machine policy | `HKLM\SOFTWARE\Policies\SolidSeas` | Read only, except through `--set-policy` |

## Tests the design requires

- The suite runs with an autouse fixture that makes `socket.socket.connect` and
  `socket.getaddrinfo` raise, so no test can reach a network. Loopback stays
  open, because the HTTP layer is tested against a fake server on 127.0.0.1;
  the run fails if anything tried another host. No test calls a real provider,
  writes the real Credential Manager or reads the PC's own policy key to decide
  a result.
- A scripted fake provider answers from a queue and records each prompt. Tests
  assert that no path, custom property value, unticked typed name or redacted
  digit string reaches it.
- A 401 path with a known key asserts the key appears nowhere in the log or the
  error shown.
- The plan validator refuses `NaN`, `Infinity`, `1e999`, a bool where a number
  is expected, a value out of range, an unknown operation, an unresolved
  handle, a plan over the step limit, and a protected or formula-like property.
- The confirmation gate: which plans start by themselves and which wait.
- Every policy branch: key absent, key access denied, value absent, wrong type,
  out-of-range value, a read that raises, and `AllowedProviderHosts` of the
  wrong type; and both chokepoints honour each result.
- A reply containing `<a href=...>` and `<img src=...>` is shown as literal
  text in every widget that can show model text.
- The settings page never shows a stored key; storing and removing a key go
  through the credential store it is given, and an empty field leaves the key
  as it is; every saved change resets the factory; Test Connection runs off
  the Qt thread; the policy greys what it restricts; and `AI.json` round-trips
  and falls back value by value. The tests give the page a memory store,
  temporary files, the scripted provider and a substituted policy reader.
- Two processes recording usage at once lose no increment, and two windows
  calling at once cannot both spend the same remainder of a budget.
- A call that fails after the provider received it (a timeout, Stop, a reply
  that cannot be read) is charged to the monthly and run budgets.
- A reply shaped to make the parser backtrack (a code fence followed by
  200,000 blanks, thousands of fences) is read or refused in well under a
  second.
- The verification table, against snapshots recorded from the oracle part
  fixtures, including the wrong-but-similar fillet edge and a change in another
  configuration.
- The look after each step: offered only with the picture ticked and greyed
  under `DisableImages`; taken only after a step that passed its checks; a
  doubtful look ends the run with the step kept; a look that cannot be made is
  said and the run goes on; Stop cancels one in flight; the copy is written
  only under the names the bridge accepts, in the run folder; the prompt holds
  no summary, name or path; and the reply parser refuses any other shape.
- A run left open: found and described from its journal; Revert takes its
  steps off through the existing revert path when the part is as the last step
  left it, and refuses, writing nothing, when the part changed, is not open, the
  session is busy, a step was running when the process ended and changed the
  part, or the journal has no part states; Keep writes `kept` and touches
  nothing else; Decide Later writes nothing and the run is offered again; kept
  and reverted runs, folders without `run.lock` and folders held by this
  process or another are never offered; and the journaled state compares as the
  snapshot it was taken from.

## Confirm before building

These eight questions were answered by a spike on SOLIDWORKS 2024 SP1, in an
instance SolidSeas started for the purpose, hidden, in a Job Object and bound
only through its `SolidWorks_PID_<pid>` moniker; never in the user's session.
Every part was made new from the Dassault-shipped MBD part template. A second
process bound to the same instance by the same moniker played the user, so the
bridge saw each change come from outside while it sat idle. Commands the user
gives from the menu or the keyboard (Edit, Undo; Edit, Redo; File, Save; Save
All; Suppress) were run through `ISldWorks::RunCommand`, and a click was posted
to the model view window (`IModelView::GetViewHWnd`). The harness was a scratch
build of the bridge with extra operations and is not in the repository; the
operations the assistant needs are added to the bridge when it is built. Each
answer says what was measured and what it changed above.

1. **`SaveAs3` with `swSaveAsOptions_Copy` leaves the open document's path,
   dirty flag and undo list unchanged.** Confirmed. For a part never saved and
   for one with a file, both modified, the copy left the path, title and dirty
   flag as they were, and a full snapshot (feature tree with persist
   references, dimensions in every configuration, properties, bodies, volume
   and area) did not change. After the copy, two Ctrl+Z removed the two steps
   made before it, newest first. The copy, opened read-only as a separate
   document, matched the live part, unsaved steps included, except for the
   order of its bodies. The copy raises `FileSavePostNotify` with the copy save
   type and no `FileSaveNotify`; the first copy of a part never saved also
   raised `ChangeCustomPropertyNotify` for an internal property that
   `GetNames` does not list. Writing the copy does not add it to SOLIDWORKS'
   recent documents; opening it does. Changed above: checkpoint 0, the binding
   check, and bodies matched as a set in verification.
2. **Whether custom property edits through `ICustomPropertyManager` land on the
   undo list.** They do not. After `Add3`, `Set2` or `Delete2` on a file
   property, and `Add3` on a configuration property, one Ctrl+Z removed the step
   made before the edit and left the edit in place, and a second removed
   nothing more. Inside a `StartRecordingUndoObject` pair the edit recorded
   nothing: `FinishRecordingUndoObject2` returned false, and Ctrl+Z again
   removed the step before. `EditUndo2` behaved the same. The inverse, `Set2`
   with the previous value or `Delete2` for a property that did not exist,
   restored the snapshot exactly. `Add3` raises `AddCustomPropertyNotify`
   twice. Changed above: a `set_property` step opens no undo entry and says
   Ctrl+Z does not undo it, and Review mode names property edits among what
   Ctrl+Z does not undo.
3. **Whether `IModelDoc2::Lock` blocks the user's selection clicks or only
   modifying commands.** Only modifying commands given in the user interface.
   A click posted to the model view selected a face with the part locked, as
   it did unlocked. Suppress and Edit, Undo, run as commands by the other
   process, did nothing while the lock was held (`RunCommand` still returned
   true), and Suppress worked after `UnLock`. API calls were not blocked from
   either process: the other process selected a feature by its persist
   reference and made a sketch and a boss-extrude while the bridge held the
   lock, and the bridge's own step ran under its own lock. So the selection
   check just before the feature call narrows the window but is not a guard:
   in a review rerun with the lock held, the bridge selected Boss-Extrude1 by
   its persist reference and the check read one entity of type 22 (a body
   feature); a click was then posted to the model view, and the very next
   bridge call read one entity of type 2 (a face). In six more trials, three
   locked and three unlocked, a click posted with nothing selected left a face
   selected. Changed above: step 4 says what Lock does and does not stop, step
   6 says what the selection check cannot do, and step 8 checks the new
   feature's inputs against the plan.
4. **How many undo entries one `StartRecordingUndoObject` and
   `FinishRecordingUndoObject2` pair produces for a sketch plus extrude made
   from another process.** One. One Ctrl+Z removed the sketch and the extrude
   together and returned the part to the before snapshot exactly, and two
   recorded steps came off with two Ctrl+Z, one each. Without a pair the same
   calls took four Ctrl+Z: the first removed the extrude, the fourth the
   sketch, and the two between changed nothing in the feature tree. Finished
   with Hidden true, the entry merged into the one before it: one Ctrl+Z
   removed both the earlier step and the hidden one. A recorded entry cannot be
   redone: Edit, Redo and `EditRedo2` left the part unchanged, where an
   unrecorded entry could be redone. `EditUndo2` removed only the newest entry;
   after it, neither `EditUndo2` nor Edit, Undo removed anything more, and
   `EditUndo2` with a count of 2 removed one. Changed above: step 5 (Hidden
   false, the return value journaled, and false failing any step but
   `set_property`), the undo bullet under revert, and why revert never uses
   `EditUndo2`.
5. **That the change, save, undo and destroy notifications arrive at an
   out-of-process client.** Confirmed, by another mechanism than the one
   assumed. With the other process changing the part and the bridge idle, the
   bridge received `ModifyNotify`, `AddItemNotify` and `RegenPostNotify2` for a
   new feature; `FileSaveNotify` then `FileSavePostNotify` for a save;
   `UndoPostNotify` for Edit, Undo; `DestroyNotify2` when the other process
   closed a watched part; the custom property and configuration notifications;
   and `ActiveDocChangeNotify` and `ActiveModelDocChangeNotify` when the other
   process made and activated documents. Each arrived before the other
   process's call returned. They arrive on a COM worker thread (MTA), not on
   the bridge's STA thread: they kept arriving, and a Save by the other process
   was not delayed, while the STA thread was blocked in a Win32 `Sleep` that
   dispatches nothing. SOLIDWORKS waits for each handler's return value, which
   is what answer 8 relies on, and it means a handler that blocks holds
   SOLIDWORKS: in a review rerun, a listener that stopped taking the bridge's
   events let 29 more rebuilds through, until the pipe filled, and the 30th
   rebuild waited 5 s, until the listener was released. Notifications caused by
   another process arrive at any time, also while the bridge's own call runs:
   the rerun saw the other process's `FileSaveNotify`, `FileSavePostCancelNotify`
   and `CommandCloseNotify` arrive during one. Two limits: `ModifyNotify` fires
   only when the document goes from saved to modified, and a dimension changed
   through `SetSystemValue3` on a part already modified raised nothing until
   the next rebuild, which raised only `RegenPostNotify2`; on a saved part, the
   set call itself raised `ModifyNotify` (the rerun). Changed above: the
   bridge's threads (handlers never block), the binding check (notifications
   attributed by kind as well as timing), and the user working at the same
   time.
6. **That deleting a feature by persist reference, as an inverse, restores the
   before snapshot exactly, including a sketch absorbed by an extrude.**
   Confirmed, when the delete passes `swDelete_Absorbed`.
   `IModelDocExtension::DeleteSelection2` with that option, on the feature
   selected by its persist reference, restored the before snapshot exactly
   (feature ids and persist references, dimensions, bodies, faces, extents,
   volume, area and properties) for a boss that made the first body, a boss
   that merged, a cut through all, a boss that made a second body, and two
   geometrically overlapping steps reverted newest first: a boss, and a cut
   through all, sketched on another reference plane, that cuts into it. Steps
   whose features reference an earlier step's geometry were not tried: a
   sketch on a face the step made, a fillet or chamfer on its edges, a pattern
   seeded by it. Revert depends on them, so they are measured, reverted newest
   first, before Automatic mode is built. Without the option the sketch stayed
   behind; deleting it by its own persist reference then gave the same exact
   result. Name counters do not go back: the next boss after the inverses was
   `Boss-Extrude6`. Two related findings: in a new part, eight folder features
   (Favorites, History, Selection Sets, Sensors, Markups, Lights and Cameras,
   Material and Tables) return the same persist reference, and `GetTypeName2`
   returned `Extrusion` for the boss that made the first body but `ICE` for
   later bosses and cuts (`GetTypeName` returned `Boss` for those bosses).
   Changed above: the inverses in the vocabulary table, the delete rule,
   handles, and verification. Measured afterwards (2026-10-11, live mode,
   `tests/test_swapi_live.py`): steps that use an earlier step's geometry,
   a boss, a fillet on its edges, a cut sketched on its face and a chamfer
   on the cut's rim, deleted newest first the same way, each gave back the
   snapshot before it exactly (features by reference, dimensions, faces and
   edges by reference, bodies, volume and extents). A pattern seeded by an
   earlier step is not measured yet, because the patterns are not built.
7. **That `GetSystemValue3` reads a dimension's value in a named configuration
   without switching configurations.** Confirmed. With a dimension at 10 mm in
   the active configuration and 25 mm in a second one, `GetSystemValue3` with
   `swSpecifyConfiguration` returned 25 mm for the second and 10 mm for the
   active one, and `swAllConfiguration` returned both in the order
   `GetConfigurationNames` lists the configurations (Default, then Alt), not
   in alphabetical order. The active configuration did not change, no
   notification of any kind arrived, and the snapshot, dirty flag included,
   stayed the same. The same held after the
   part was saved, closed and opened read-only, when the second configuration
   had not been active in that session. This confirms the snapshot as
   designed.
8. **Whether a `FileSaveNotify` handler can cancel the user's Save of the bound
   document.** It can. With the bridge's handler returning `S_FALSE` (1),
   File, Save and Save All run as commands by the other process, and `Save3`
   called by it, were cancelled: the file was not written, the part stayed
   modified, `Save3` returned false with `swGenericSaveError`, and
   `FileSavePostCancelNotify` followed. `E_FAIL` cancelled `Save3` the same
   way. The commands returned in about a second, and no new window appeared in
   the hidden instance (checked after Save All). SolidSeas' own checkpoint copy
   was not affected. Save As is different: `SaveAs3` to another file raised
   neither `FileSaveNotify` nor `FileSaveAsNotify2` on the part, only
   `FileSavePostNotify` with the Save As type, was not cancelled, and moved the
   part to the new file. Not measured: whether a visible session tells the
   user that a save was cancelled, and what closing the part, or exiting
   SOLIDWORKS, with "Save changes? Yes" does while a save is held. Changed
   above: a run will hold saves of the bound document once those are measured,
   the window then says the save was not done, and Save As stops the run.
