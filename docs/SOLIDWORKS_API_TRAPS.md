# SOLIDWORKS API traps

What SOLIDWORKS did through its API that the API help does not lead you to
expect, and what SolidSeas does about it. Read this before changing the bridge
(`src/solidseas/swapi/SwBridge`) or anything that sends it requests.

Every entry was seen in a run against a real SOLIDWORKS, 2024 SP1 unless the
entry says otherwise, and the Measured column says which run. Nothing here comes
from the API help alone. Where no fix is known yet, the entry says so and names
its bead. The longer accounts are in the [swapi README](../src/solidseas/swapi/README.md)
and, for live mode, in the spike's answers under "Confirm before building" in
[ASSISTANT.md](ASSISTANT.md). The measuring harness named below is the
read-only one that measured the fixtures and a sample of the development corpus
on 2026-10-04.

When you measure a new trap, add a row with the version, the date and the run or
test that showed it.

## Starting and hiding the instance

| Symptom | What to do | Measured |
|---|---|---|
| A new instance's splash and main window take the foreground for 6 to 7 s, so keys meant for the user's own SOLIDWORKS land in it | SOLIDWORKS ignores the show-window hint it is started with (`SW_SHOWMINNOACTIVE`), and nothing can hide it before it registers in the Running Object Table. Hide it (`Visible` and `UserControl` false) as soon as `SolidWorks_PID_<pid>` appears, and run long jobs off-hours (`OffHours`) | 2026-10-05, another SOLIDWORKS open: SolidSeas' instance held the foreground for 5.6 s of samples and `start_solidworks` returned after 6.2 s (`test_solidseas_solidworks_hides_its_journal_box_and_nothing_else`) |
| `UserControl` is true again after `NewDocument` | `NewDocument` hands the instance to the user. Set `UserControl` and `Visible` false after every call that makes or opens a document (`KeepHidden`) | SOLIDWORKS 2024 SP1, `new_document` from the MBD part template; `test_a_new_document_reports_its_own_close` checks it |
| With no other SOLIDWORKS running, the frame shows again after a new document, although it was hidden right after `NewDocument` returned | SOLIDWORKS shows it late. Hiding it three more times 100 ms apart (`KeepHiddenSettled`) still leaves it visible and minimized: a 160 x 28 window with a taskbar button. No fix yet (SolidSeas-okg) | 2026-10-14 and 2026-10-15, SolidSeas' instance alone (`test_a_new_document_reports_its_own_close` fails there) |
| With no other SOLIDWORKS running, the Welcome screen (`swWelcomeScreen`, 800 x 617) and a 600 x 402 `Afx` window are visible after every start while `Visible` reads false | They are top-level windows of their own, not the frame, and stay until the first document. No fix yet: hiding them as the journal box is hidden needs the user's yes, because the window watch hides only that box (SolidSeas-okg) | 2026-10-15, SolidSeas' instance alone |
| `ISldWorks.DocumentVisible(false)` keeps new documents hidden, but then `InsertImportedComponent` faults (`RPC_E_SERVERFAULT`), a STEP insert stops behind Open Progress for 600 s, and a new part is not the active document | Do not use it; hide the frame instead. `test_bridge_never_saves_a_document_or_changes_an_option` forbids the call | 2026-10-15, SolidSeas' instance alone; reverted the same day |
| `StartupProcessCompleted` never becomes true | A hidden instance never sets it. Do not wait for it: the COM message filter retries the calls SOLIDWORKS rejects while it is still starting | SOLIDWORKS 2024 SP1, SolidSeas' hidden instance |
| While another SOLIDWORKS runs, a message box titled SOLIDWORKS ("A journal file could not be created. Auto recover will not work...") appears, stays when the instance is hidden, and takes the foreground again as other windows come and go | It belongs to the new instance, the second session on the machine. Hide that one box with `ShowWindow(SW_HIDE)`; never click, close or activate it (`WindowWatch.cs`) | 2026-10-05, another SOLIDWORKS open: hidden 6.1 s after the start; in an earlier run it took the foreground again four times |
| Started on a desktop of its own (`CreateDesktop`), SOLIDWORKS never registers | It shows its splash and then the journal box on that desktop, where nobody can answer it, and sits idle (its CPU time did not move for two minutes). Start it on the user's desktop | SOLIDWORKS 2024 SP1, another SOLIDWORKS running |
| `start_solidworks` waits its whole timeout (15 minutes in one run) and the instance never registers | SOLIDWORKS is not activated on the PC: it starts `swactwiz.exe` and waits while the wizard asks. Watch the windows of every process in the job, report the wizard, never answer it, and fail at once with `solidworks_not_activated` | 2026-10-14, SOLIDWORKS not activated: the request failed after 2.2 s |

## Ending the instance

| Symptom | What to do | Measured |
|---|---|---|
| After the instance ends, about 230 values of the layout under `User Interface` in the user's registry have changed (40 added, 115 removed, 75 changed), and the next SOLIDWORKS reads them | `ExitApp`, SOLIDWORKS' own shutdown, writes the instance's layout. Close the bridge's own documents and terminate the instance's Job Object instead (exit code 21331) | SOLIDWORKS 2024 SP1, every value under `HKCU\Software\SolidWorks` hashed before and after; `ExitApp` ended the instance with exit code 45 in about 2 s. Ended through its job on 2026-10-05: no layout value changed |
| Values under `HKCU\Software\SolidWorks` change although the bridge sets none: `General\Last Splash Id` at each start, toolbar values under `User Interface\Custom API Toolbars`, and an entry in the recent documents list for every document opened | SOLIDWORKS writes them while it runs. Expect them; the bridge never sets an option | 2026-10-05, another SOLIDWORKS open: 99 values changed, 97 of them in the recent documents list (`test_ending_through_the_job_leaves_the_layout_lock_files_and_next_start_alone`) |
| With no other SOLIDWORKS running, an instance ended through its job still changes 148 values under `User Interface`: every CommandManager context tab, 74 in `PartContext\Tab26` and 74 in `AssyContext\Tab15`, with whole tab pairs swapped | SOLIDWORKS writes them while it runs as the only session. No fix yet (SolidSeas-l4mk) | 2026-10-14, SolidSeas' instance alone; with another SOLIDWORKS open on 2026-10-05 it wrote none |
| `close_document` of a part fails with `RPC_E_DISCONNECTED` (0x80010108) after an assembly that used it was closed | Seen when the part was opened before the assembly. Cause not known, no fix yet (SolidSeas-d30); ending the instance goes on regardless | 2026-10-05 overnight run, `test_mass_properties_of_fixture_copies_match_the_ground_truth` |

## Opening and saving documents

| Symptom | What to do | Measured |
|---|---|---|
| A `~$` lock file stays next to a document after the instance is ended | SOLIDWORKS makes one for a document opened for writing. Open documents read-only, always (`swOpenDocOptions_ReadOnly` with `Silent`) | SOLIDWORKS 2024 SP1; `test_save_copy_never_writes_an_open_document_under_another_name` checks no lock file is left |
| Opening an assembly read-only still writes in its folder: the folder's modification time changes while its entries stay the same | SOLIDWORKS creates something there and removes it again. Open a copy when the folder must stay untouched; parts and STEP imports left their folders alone | 2026-10-04, measuring harness: the copy of fixture o08, opened twice with `ReadOnly`, `Silent` and `OverrideDefaultLoadLightweight` |
| `SaveAs3` to a STEP name hard-linked to the open part emptied the part; to its `.SLDPRT` through a junction it overwrote it | Comparing paths does not see another name for the same file. Before replacing a file, compare its volume and file id (`GetFileInformationByHandleEx`) with those of every open document, and refuse a match or a file that cannot be identified | SOLIDWORKS 2024 SP1, before the check existed; `test_save_copy_never_writes_an_open_document_under_another_name` |
| `SaveAs3` writes `.STL` when asked for `.stl` and `o02_boxa.glb` for `o02_boxA.glb`, and puts a `.gltf` in a folder named after it, lowercased, with a `.bin` beside it | Report the name found on disk, and treat the glTF folder as the output | batch conversion of fixture copies: STL on 2026-10-05, glTF and GLB on 2026-10-14 |
| `SaveAs3` refused `.gltf` and `.glb` with `swFileSaveAsInvalidFileExtension` (256) on one day and wrote them on another, with the same SOLIDWORKS | Not known. Accept either result | refused 2026-10-05, written 2026-10-14 |

## Importing

| Symptom | What to do | Measured |
|---|---|---|
| `LoadFile4` of a two-body STEP stops behind the New SOLIDWORKS Document template dialog (three hours in one run), although "always use default templates" is on and the templates exist | With 3D Interconnect on and Assembly Structure Mapping set to import multiple bodies as parts, the import becomes an assembly and asks for its template. Give the template (`insert`, `component`), and refuse `load` of a STEP that may hold several bodies | 2026-10-04 in the user's session (measuring harness, fixture o12); 2026-10-14 in SolidSeas' instance alone |
| `InsertImportedFeature` of a STEP with two or more solids, or several sheets, faults with `RPC_E_SERVERFAULT` (0x80010105) | Under that mapping. Refuse it (`several_bodies_insert`) and import into a new assembly with `InsertImportedComponent` instead | 2026-10-05: o12 and 21 of 162 corpus parts; 2026-10-14: o12 |
| `InsertImportedComponent` places the component 6 to 33 mm off the origin, differently each time, whatever point it is given | Set the component's `Transform2` to the identity afterwards | 2026-10-14, SolidSeas' instance alone, o02, o08, o12 and o15 |
| A STEP import that went through reports a dialog | SOLIDWORKS' "Open Progress..." window, and often an untitled empty box, come and go during the import and count as dialogs to the window watch. Judge an import by `errors` and `result_kind`, not `dialog_appeared` (SolidSeas-d30) | 2026-10-05 and 2026-10-14 |
| With no other SOLIDWORKS running, `LoadFile4` of a single-body STEP shows "Open Progress... Reading model" and never returns | Cause not known: with another SOLIDWORKS open the same loads went through. Use `insert` or `component`, which took 8.8 s and 5.8 s for the same files (SolidSeas-283j) | 2026-10-14, SolidSeas' instance alone: o02 and SolidSeas' STEP of o11, ended at the 600 s timeout |
| An import that brings in nothing returns success | No error comes back. Check `result_kind` (`empty`) | 2026-10-05, two corpus parts in the STEP round trip |
| A single-sheet STEP of 1,018 faces ran past five minutes behind a modal window while SOLIDWORKS used two cores, where a file of the same size and face count imported in 8 s | Cause not known. Give every import a timeout | 2026-10-04, the user's session, measuring harness |
| Face counts change in a STEP round trip: fixture o11 has 12 faces natively and 14 after one | The account's "split periodic faces" STEP option. Compare volume, area, centre of mass and boxes, not topology | 2026-10-04, measuring harness |

## Measuring

| Symptom | What to do | Measured |
|---|---|---|
| `IMassProperty2` gives volume, area and mass 0 for a part with a visible solid, with no warning | Seen on two corpus parts saved by SOLIDWORKS 2016, whose own STEP measured normally. Treat 0 with a visible solid as not valid (`mass_zero_with_visible_solids`) | 2026-10-04, measuring harness |
| A part whose bodies are all sheets reports a mass of 0 | It gets no `IMassProperty2`, and the older `IMassProperty` answers 0. Sum `IFace2.GetArea` for sheets | 2026-10-04, measuring harness |
| `PartDoc.GetPartBox` and `AssemblyDoc.GetBox` overshoot: for fixture o16, 0.13484 m where the bodies end at 0.12137 m | They are coarse. Use `IBody2.GetExtremePoint` along the six axis directions | 2026-10-04, measuring harness |
| A component's bodies come back in the wrong place | `Component2.GetBodies3` gives them in the part's own coordinates. Copy each body and apply the component's `Transform2` | 2026-10-04, measuring harness |
| A document reports itself changed after it was only measured | Showing another configuration (`ShowConfiguration2`) marks it changed while it is open; whether showing the active one again clears that is not measured. Read `GetSaveFlag` afterwards | 2026-10-04, measuring harness |
| Setting `IMassProperty2.SelectedItems` on a part faults inside SOLIDWORKS (`RPC_E_SERVERFAULT`), with the bodies as objects or as dispatch pointers | Measure each body with `IBody2.GetMassProperties` and add them up | SOLIDWORKS 2024 SP1, live mode in SolidSeas' own instance |

## Building features

| Symptom | What to do | Measured |
|---|---|---|
| A fillet built from a definition naming its edges (`CreateDefinition`, `CreateFeature`) makes no fillet, with the edges as objects or as dispatch pointers | Select the edges with mark 1, check the selection just before the call, then call `FeatureFillet3` | SOLIDWORKS 2024 SP1, live mode in SolidSeas' own instance |
| After a fillet on a block's edges, the block's top face has a new persist reference while the old one still resolves to it | Map a plan's references to their present ones before each step (`live_current_refs`) | 2026-10-11, `tests/test_swapi_live.py` |
| Deleting an extrude by its persist reference leaves its sketch behind | Delete with `swDelete_Absorbed` (`IModelDocExtension.DeleteSelection2`) | the spike, answer 6 |
| Eight folder features of a new part (Favorites, History, Selection Sets, Sensors, Markups, Lights and Cameras, Material, Tables) share one persist reference | Give folders no handle | the spike, answer 6 |
| `GetTypeName2` says `Extrusion` for the boss that made the first body and `ICE` for later bosses and cuts | Do not tell feature kinds apart by that name alone | the spike, answer 6 |
| `IModelDoc2.Lock` does not stop selection clicks or API calls from any process, and `RunCommand` returns true for a command it blocked | It stops only modifying commands given in the user interface. Check the selection just before each feature call, and the new feature's inputs after it | the spike, answer 3 |

## Undo, notifications and saves

| Symptom | What to do | Measured |
|---|---|---|
| A custom property edit is not on the undo list, and inside `StartRecordingUndoObject` it records nothing (`FinishRecordingUndoObject2` returns false) | Undo a property edit with `Set2` or `Delete2` | the spike, answer 2 |
| An undo entry finished with Hidden true merges into the one before it, which may be the user's; a recorded entry cannot be redone; `EditUndo2` removes the newest entry and then nothing more | Finish entries with Hidden false, and revert with inverses, never `EditUndo2` | the spike, answer 4 |
| A notification handler that waits holds SOLIDWORKS: with the event pipe full, a rebuild waited 5 s until the listener took events again | Handlers run on a COM worker thread and SOLIDWORKS waits for each to return. Queue the event and return; when nobody reads, drop events and count them | the spike, answer 5, and its review rerun |
| No `ModifyNotify` for a change to a part already modified; a dimension set with `SetSystemValue3` then raised nothing until the next rebuild | `ModifyNotify` fires only on the change from saved to modified. Do not count changes by it | the spike, answer 5 |
| The first `SaveAs3` copy of a part never saved raises `ChangeCustomPropertyNotify` for a property `GetNames` does not list, and `Add3` raises `AddCustomPropertyNotify` twice | Do not take every notification for a change someone made | the spike, answers 1 and 2 |
| `SaveAs3` of the part to another file raises neither `FileSaveNotify` nor `FileSaveAsNotify2`, cannot be cancelled, and moves the part to the new file | A `FileSaveNotify` handler that returns `S_FALSE` cancels Save, Save All and `Save3`, but not Save As | the spike, answer 8 |
| `GetSystemValue3` with `swAllConfiguration` gives the values in the order `GetConfigurationNames` lists the configurations, not by name | Pair values with names in that order | the spike, answer 7 |
