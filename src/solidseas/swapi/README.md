# SolidSeas SOLIDWORKS automation (`solidseas.swapi`)

This folder holds the parts of SolidSeas that need a local SOLIDWORKS. The
format readers in `solidseas.formats.solidworks` never do; use them first.

Every call into SOLIDWORKS goes through one program, `SolidSeas.SwBridge.exe`,
built from the C# sources in `SwBridge/`. Python never loads the SOLIDWORKS
interop: `solidseas.swapi.bridge` starts the bridge as a child process, talks
to it in JSON lines and keeps the timeouts, and `solidseas.swapi.batch`
converts documents on it. The bridge also measures documents
(`mass_properties`) and imports STEP, IGES and Parasolid files
(`import_file`). Batch mode uses a SOLIDWORKS that the bridge starts for
itself. Live mode attaches to the user's own session for the modeling
assistant, and never ends it (below).

[SOLIDWORKS API traps](../../../docs/SOLIDWORKS_API_TRAPS.md) lists, one row
each, what SOLIDWORKS was measured doing through its API that the code here has
to allow for, with the run that showed it. Read it before changing the bridge.

## The bridge: `SolidSeas.SwBridge.exe`

The main thread is a single-threaded apartment (`[STAThread]`) that owns every
SOLIDWORKS object. It registers a COM message filter
(`CoRegisterMessageFilter`) that retries a call SOLIDWORKS rejects while busy
(`SERVERCALL_RETRYLATER`) every 250 ms until the request's deadline, and it
dispatches window messages whenever it waits (`MsgWaitForMultipleObjectsEx`).
Document notifications do not depend on that: SOLIDWORKS calls the bridge's
handlers on a COM worker thread whatever the main thread is doing, blocked
included, and waits for each one to return (measured in the spike,
`docs/ASSISTANT.md` answer 5). A handler therefore only queues its event line
and returns. A background thread reads standard input, so requests arrive while
the apartment pumps, and another writes standard output, so neither a handler
nor the apartment thread ever waits for the pipe. Standard output carries
protocol lines only; diagnostics go to standard error.

Two Job Objects hold what runs:

- The Python client puts the bridge in a Job Object with kill-on-close as soon
  as it starts, and checks it is there before sending anything. The
  `SLDWORKS.exe` the bridge starts later inherits that job.
- The bridge starts `SLDWORKS.exe` suspended, puts it in a second Job Object
  with kill-on-close of its own, and only then resumes it, so SOLIDWORKS never
  runs a single instruction outside a job. It inherits no handle from the
  bridge (its pipes stay the bridge's alone). It is asked to start minimized
  without taking the focus (`SW_SHOWMINNOACTIVE`), but SOLIDWORKS ignores that:
  see "Starting takes the foreground" below. The job is unnamed and holds
  nothing but that process and what it starts, and the bridge ends the
  instance by terminating it (`TerminateJobObject`).

Ending the bridge's job ends the bridge and its SOLIDWORKS together, and so
does the Python process dying, because its job handle closes with it. Ending
the bridge ends its SOLIDWORKS through the second job.

### Building it and finding it

```powershell
scripts\build-bridge.ps1                      # writes dist\SolidSeas.SwBridge.exe
python -m solidseas.swapi build -o D:\Tools   # the same command from Python
scripts\build-viewer.ps1 -Venv .venv -WithBridge   # the viewer and the bridge, side by side in dist\
```

Both compile with the C# compiler of the .NET Framework 4 that ships with
Windows (`%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe`, C# 5,
`/warnaserror+`) against `SolidWorks.Interop.sldworks.dll` and
`SolidWorks.Interop.swconst.dll` from `<SOLIDWORKS>\api\redist`, plus
`System.Web.Extensions.dll` (JSON). Nothing else is installed. The interop
assemblies are not copied anywhere, into the repository or next to the
program: the bridge loads them at
run time from the folder its `--interop` option names, which the client derives
from the `SLDWORKS.exe` it is given. The program carries the SolidSeas version
it was built from (`bridge_version`). `dist\` is not committed.

`solidseas.swapi.bridge.find_bridge()` looks, in order, at the path it is
given, the `SOLIDSEAS_SWBRIDGE` environment variable, the folder of the
running executable when SolidSeas is frozen (so `dist\SolidSeasViewer.exe`
finds `dist\SolidSeas.SwBridge.exe`), and `dist\` of a source checkout.

### Protocol (version 1)

When it is ready the bridge writes one line,
`{"event": "ready", "protocol": 1, "bridge_version": "0.2.42", "pid": ..., "apartment": "STA", "message_filter": true, "in_job": true, "test_ops": false, "ops": [...]}`.
After that, each request is one line of JSON on standard input and gets one
line in reply on standard output, in order:

```json
{"id": 7, "op": "save_copy", "args": {"doc": 1, "path": "D:\\Exports\\bracket.step"}, "timeout_s": 600}
{"id": 7, "ok": true, "result": {"doc": 1, "path": "D:\\Exports\\bracket.step", "bytes": 15843, "errors": 0, "warnings": 0, "step_ap": 203}}
{"id": 8, "ok": false, "error": {"code": "save_failed", "message": "SaveAs3 failed", "details": {"errors": 256, "warnings": 0, "error_names": ["swFileSaveAsInvalidFileExtension"]}}}
```

`id` is a whole number the caller chooses. `timeout_s` is the caller's
timeout, more than 0 and at most 86,400 s: the bridge ends its own waits
(start-up, exit, rejected-call retries) two seconds before it. A request field,
operation or argument the bridge does not know is refused, never ignored. Lines
without an `id` are events:
`{"event": "document", "doc": 2, "name": "DestroyNotify2", "data": {"destroy_type": 0}}`
for a watched document, and
`{"event": "window", "action": "hidden", "kind": "journal_box", "pid": 9120, "process": "SLDWORKS.exe", "hwnd": 591362, "class": "#32770", "title": "SOLIDWORKS", "text": "A journal file could not be created. ...", "again": false}`
when the bridge hides its instance's journal file message box, or
`"action": "left", "kind": "dialog"` once for any other dialog of its instance
or of a program it started, which it leaves as it is, and `"kind": "activation"`
for SOLIDWORKS Product Activation (below). `pid` and `process` are those of the
window's own process.
A request line is at most 1,048,576 characters (UTF-16 code units, as .NET
counts them); a reply line at most 64 MiB. The bridge answers requests one at a
time in the order it read them, so a line it could not read gets a `bad_request`
reply with `"id": null` in that request's turn.

At most 4,096 events wait to be written. When standard output is not being read
and more arrive, the bridge drops them, never waiting, and the next line it
queues is `{"event": "events_lost", "count": n}`; `hello` reports the total as
`events_lost`. A handler that waited for the pipe would hold SOLIDWORKS: in a
review rerun of the spike, once a client that had stopped taking events let
the pipe fill, the instance's next rebuild waited until the client took them
again.

Error codes: `bad_request`, `unknown_op`, `invalid_argument`, `not_found`,
`refused` (a safety rule, or an import the account's options would turn into
a dialog), `not_started`, `start_failed`, `solidworks_not_activated` (SOLIDWORKS
Product Activation is asking, below), `timeout` (the
bridge's own start-up wait), `open_failed`, `new_failed`, `save_failed`,
`import_failed`, `busy` (SOLIDWORKS still rejected the call at the deadline,
`RPC_E_CALL_REJECTED`), `cancelled`, `disconnected` (the SOLIDWORKS process went
away), `com_error` and `internal`. A COM failure also carries its `hresult`.

### Operations

| Operation | Arguments | Result |
|---|---|---|
| `hello` | | the ready fields, `events_lost`, and `solidworks`: the PID of the SOLIDWORKS it started, or null |
| `start_solidworks` | `exe` (default `C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe`; only a file named `SLDWORKS.exe`) | `pid`, `revision`, `visible`, `user_control`, `startup_completed`, `document_count`, `documents`, `window_watch`, `windows_hidden`, `step_ap`, `exe`, `in_job`; a failure's `details.dialogs` lists the dialogs the instance, and the programs it started, showed while it started, and `solidworks_not_activated`'s `details.activation` is the activation wizard's dialog |
| `solidworks_info` | | the same, without `exe` and `in_job` |
| `new_document` | `template` (a `.prtdot`, `.asmdot` or `.drwdot` path) | the document, as `document_info` gives it |
| `open_document` | `path` (`.sldprt`, `.sldasm`, `.slddrw`), `configuration`, `allow_network` (default false), `read_only` (true; false is refused) | the document, with `errors` and `warnings` from `OpenDoc6`; an assembly opens with its components resolved, and SOLIDWORKS writes briefly in its folder (side effects, below) |
| `document_info` | `doc` | `doc`, `title`, `path`, `type`, `read_only`, `dirty` (`GetSaveFlag`), `active_configuration`, `configurations`, `feature_count`, `watched` |
| `list_features` | `doc`, `limit` (default 10,000) | `features` (`name`, `type`, `id`) in tree order, `truncated` |
| `save_copy` | `doc`, `path` (an export format, below), `overwrite` (default false), `allow_network` (default false) | `path` as written on disk, `bytes`, `errors`, `warnings`, and `step_ap` for STEP |
| `close_document` | `doc` | `closed`, `title` |
| `watch_document` | `doc` (a part) | `events`: the notifications it now sends as event lines |
| `mass_properties` | `doc` (a part or an assembly), and `configuration` (a name) or `all_configurations` (true, at most `max_configurations`, default 50); neither measures the active one | `measures`: one per configuration (below), `active_configuration`, `configurations`, `units` (`SI`), `dirty`, `restored_active_configuration` when another one was shown, `configurations_skipped` |
| `import_file` | `path` (`.step`, `.stp`, `.igs`, `.iges`, `.x_t`, `.x_b`), `method` (`insert`, the default, `load` or `component`), `template` (a `.prtdot` path for `insert`, an `.asmdot` path for `component`, required for both; refused for `load`), `map_configuration_data` (STEP with `load` only), `allow_network` (default false) | the new document, as `document_info` gives it, and `method`, `format`, `source`, `errors` and `error_names` (`swFileLoadError_e`), `feature` (`insert`: `name`, `type`, `interconnect`), `component` (`component`: `name`, `children`, `document_extension`, `refers_to_source`, `virtual`, `placed`, `at_origin`), `feature_types`, `solid_bodies`, `sheet_bodies`, `result_kind`, `step_census`, `preferences`, `default_part_template`, `dialogs`, `dialog_appeared`, `window_watch`, `seconds` (below) |
| `native_check` | `doc` (a part `open_document` opened), `dimension` (a full name such as `D1@Boss-Extrude1`, optional) and `value` (metres or radians), `save_path` (a new `.sldprt` path, optional) | `opened` and `rebuilt` (after `ForceRebuild3`): `features` (`name`, `type`, `suppressed`, `error`, `error_is_warning`, `dimensions` with `name`, `value`, `driven`; a sketch's `segments`, `points`, `relations` and `constrained_status`; an extrusion's `end_condition`, `depth`, `both_directions`, `reverse`, `merge`), `whats_wrong` and `measure` (as `mass_properties` gives one); `force_rebuild`; `edit` (`found`, `before`, `status`, `rebuild`, `after`, `snapshot`) when a dimension is named; `saved` (`ok`, `path`, `bytes`, `errors`, `warnings`) when a copy is asked for, written with `swSaveAsOptions_Copy` and never over a file. The oracle for the native writer (`docs/NATIVE_SLDPRT_WRITER.md`): batch instance only, the document is never saved |
| `test_session_new_part`, `test_session_open`, `test_session_native_check`, `test_session_close`, `test_session_documents` | `template` (a `.prtdot`); `path` (a `.sldprt`); `document` and `native_check`'s arguments; `document`; none | offered only with `--test-session`, after `live_attach`: the opt-in tests' and the attached checks' way to work in a SOLIDWORKS the person started (agreed 2026-10-19, `TestSession.cs`). A new part from the template, or a part opened read-only (refused when the session has a document of that name open), keyed as `document`; `native_check` on one of them; and closing it with `QuitDoc`, which discards its changes. Only documents this bridge created or opened there are touched, and every one still open is closed when the bridge detaches |
| `unwatch_document` | `doc` | `was_watched` |
| `exit_solidworks` | | `ended`: `job_terminated`, `job_closed` (terminating failed and closing the job ended it), `already_exited` or `not_started`; `pid`, `exit_code` (21331, `0x5353`, when the bridge ended it), `documents_closed`, `documents_open` (open afterwards that the bridge did not open), `job_processes`, `windows_hidden` |
| `shutdown` | | as `exit_solidworks`, then the bridge exits |
| `list_sessions` | `pids` (only these processes; default every `SLDWORKS.exe` in the bridge's Windows session) | `sessions`, each with `pid`, `solidseas` (a SolidSeas bridge started it for batch work), `writer` (a SolidSeas window holds the session), `attached`, `reachable`, and, when reachable, `revision` and `documents` (`key`, `title`, `path`, `type`, `visible`, `active`, `dirty`); otherwise `note`: `administrator`, `not_registered`, `not_registered_or_administrator`, or the code of the COM error; and `attached`: the PID this bridge is attached to, or null |
| `live_attach` | `pid` | the session, as `list_sessions` gives it, and `undo_entry_closed`: whether a script's undo entry an ended bridge left open was closed |
| `live_detach` | | `was_attached`: the PID let go of, or null |
| `live_documents` | | `pid`, `documents` |
| `live_document_info` | `document` (a `key` from `documents`: the full path, or the title of a document never saved) | `document`, `title`, `type`, `dirty`, `read_only`, `active_configuration`, `configurations`, `feature_count`, `active`, `editing_sketch` |
| `live_snapshot` | `document` (a part), `limit` (faces and edges, default 5,000) | `live_document_info`'s fields, and `path`, `length_unit`, `features` (`ref`, `name`, `type`, `suppressed`, `parents`), `dimensions` (`ref`, `name`, `feature`, `kind`, `value`), `planes` (`ref`, `name`, `origin`, `sketch_x`, `normal`), `axes` (`ref`, `name`, `origin`, `direction`), `faces` (`ref`, `type`, `area`; a plane's `point`, `sketch_x` and `normal`; a cylinder's `point`, `axis` and `radius`), `edges` (`ref`, `type`, `start`, `end`, `center`, `radius`, `length`, `faces`), `truncated`, `solid_bodies`, `volume`, `box_min`, `box_max`, `custom_properties`, `configuration_properties`, `material`, `equations`, `whats_wrong` (`feature`, `code`, `warning`), `seconds`; SI units throughout |
| `live_features`, `live_dimensions` | `document`, `limit` (default 10,000) | `features` (`name`, `type`, `id`, `suppressed`) or `dimensions` (`name`, `feature`, `kind`, `value`), `truncated` |
| `live_properties` | `document` | `properties`, `configuration`, `configuration_properties` |
| `live_mass_properties` | `document` (a part), `configuration` (the active one only) | `volume_m3`, `surface_area_m2` and `center_of_mass_m` of the solid bodies, each measured on its own (`IBody2.GetMassProperties`), `solid_bodies`, `bbox_m`, `configuration` |
| `live_checkpoint` | `document` (a part), `path` (`checkpoint-<run id>.sldprt` in a folder directly in `<data dir>\runs`, not there yet) | `path`, `bytes`, `errors`, `warnings`, `path_unchanged`, `dirty_unchanged` |
| `live_begin_undo`, `live_end_undo` | `document` (a part, to begin), `name` (`SolidSeas script`, the default, `SolidSeas step <n>: <operation>` or `SolidSeas revert of step <n>`) | `name`; `live_begin_undo`: `left_entry_closed`; `live_end_undo`: `recorded` (what `FinishRecordingUndoObject2` returned), `open` |
| `live_operation` | `document` (the active part), `op`, the operation's arguments in SI units with persist references (below), and `undo_name` (an undo entry of its own, named as above) and `lock` (`IModelDoc2.Lock` while it runs), each recorded in a state file first | `feature` (the new feature's reference), `name`, `type`, `error`, `warning`, and `sketch` for an extrude; `before` and `after` for `set_dimension` and `set_property`; `features` for `suppress` and `unsuppress`; and `dirty` |
| `live_delete_feature` | `document`, `feature` (a reference `live_operation` returned in this bridge) | `deleted` |
| `live_restore_property` | `document`, `name`, `scope`, `value` (absent: delete the property) | the property as put back; only one this bridge set |
| `live_current_refs` | `document`, `refs` (at most 1,000) | `refs`: each reference's present one, or null when it names nothing now (a step can give an entity a new reference while the old one still resolves) |
| `sleep`, `exit`, `emit`, `classify_windows`, `watch_timing` | `ms`; `code`; `count`; `own_pid`, `job_pids`, `windows`; `fast_ms`, `slow_ms` | test operations, offered only with `--test-ops`: block the apartment thread without pumping, as a call stuck inside SOLIDWORKS does; exit at once, as a crash does; queue `count` event lines as notification handlers do, and report how many milliseconds that took (`emitted`, `ms`); apply the window rule below to `windows` described in the request (`hwnd`, `pid`, `class`, `title`, `visible`, `children` with `class` and `text`), with `job_pids` standing in for the Job Object, and return a `verdict` for each: `hide`, `leave`, `not_ours`, `not_a_dialog` or `not_shown`; or set the window watch of the next `start_solidworks` to end its fast phase `fast_ms` after it starts, registered or not, and then wait `slow_ms` (at least 100) between looks unless its WinEvent hook wakes it, so a test with a stand-in that never registers depends on the hook |

`doc` is a handle the bridge hands out for a document it opened, created or
imported; there is no way to name any other document. `watch_document` sends
`ModifyNotify`, `FileSaveNotify`, `FileSavePostNotify`, `UndoPostNotify`,
`RedoPostNotify`, `DestroyNotify2`, `AddItemNotify`, `DeleteItemNotify`,
`RegenPostNotify2`, `ChangeCustomPropertyNotify` and
`ActiveConfigChangePostNotify` of a part, each as an event line with the
document's handle, queued while the request that caused it is still running
and written before its reply.
`save_copy` writes the export format its extension names: `.step`, `.stp`,
`.x_t`, `.x_b`, `.stl`, `.3mf`, `.gltf` or `.glb`. SOLIDWORKS writes a `.gltf`
into a folder named after it, its name lowercased, with a `.bin` beside it
(`out\part\part.gltf`): the reply's `path` is that `.gltf`, `files` lists what
was written there, and an existing folder of that name is replaced only with
`overwrite`, as a file would be. It never writes a native
SOLIDWORKS file (`.sldprt`, `.sldasm`, `.slddrw`); an operation that needs to,
such as saving a new drawing, will come with checks of its own.
Every path is a full path on a drive (`C:\...`). A drive-relative path
(`C:file`) or a root-relative one (`\file`) would resolve against the bridge's
working directory, which no request names, so both are refused, as are device
and `\\?\` paths. A network path (`\\server\share\...`) is taken only by
`open_document` and `save_copy`, and only with `allow_network` true; batch
conversion sets it for the network paths the user named.
SOLIDWORKS' error and warning codes come with the names of the bits set, from
the enumerations the API documents (`swFileLoadError_e`, `swFileSaveError_e`
and their warnings).

### Measuring: `mass_properties`

```json
{"id": 9, "op": "mass_properties", "args": {"doc": 2, "all_configurations": true}, "timeout_s": 600}
{"id": 9, "ok": true, "result": {"doc": 2, "type": "part", "units": "SI", "active_configuration": "Default", "configurations": ["Default", "Tall"], "measures": [{"configuration": "Default", "active": true, "shown": false, "solid_bodies": 1, "sheet_bodies": 0, "hidden_solid_bodies": 0, "hidden_sheet_bodies": 0, "solid_topology": {"faces": 6, "edges": 12, "vertices": 8}, "sheet_topology": {"faces": 0, "edges": 0, "vertices": 0}, "check3": {"faults": 0, "bodies_with_faults": 0, "fault_codes": {}, "check_errors": 0}, "sheet_area_m2": 0.0, "bbox_m": [0, 0, 0, 0.01, 0.02, 0.03], "bbox_solids_m": [0, 0, 0, 0.01, 0.02, 0.03], "bbox_all_bodies_m": [0, 0, 0, 0.01, 0.02, 0.03], "bbox_method": "IBody2.GetExtremePoint", "bbox_errors": 0, "api_box_m": [0, 0, 0, 0.01, 0.02, 0.03], "mass": {"api": "IMassProperty2", "volume_m3": 6e-06, "surface_area_m2": 0.0022, "center_of_mass_m": [0.005, 0.01, 0.015], "mass_kg": 0.006, "density_kg_m3": 1000.0, "include_hidden": false, "use_system_units": true, "accuracy_level": 2, "overrides": {"mass": false, "center_of_mass": false, "moments_of_inertia": false}, "valid": true}, "warnings": [], "seconds": 0.05}, {"configuration": "Tall", "...": "..."}], "restored_active_configuration": true, "dirty": true}}
```

Units are SI throughout: metres, square metres, cubic metres, kilograms. Each
measure covers one configuration, and these bodies:

| Field | Bodies covered |
|---|---|
| `solid_bodies`, `sheet_bodies` | all bodies, hidden ones included |
| `hidden_solid_bodies`, `hidden_sheet_bodies` | hidden bodies: in a part, those hidden in it; in an assembly, those of hidden components or hidden in their part |
| `solid_topology`, `sheet_topology` (`faces`, `edges`, `vertices`) | visible solids, visible sheets |
| `check3` (`faults`, `bodies_with_faults`, `fault_codes` by `IBody2.Check3` error code, `check_errors`) | visible solids and sheets |
| `sheet_area_m2` | visible sheets: the sum of `IFace2.GetArea` |
| `bbox_m`, `bbox_solids_m` | visible solids and sheets; visible solids only |
| `bbox_all_bodies_m` | all bodies, hidden ones included (null when the hidden bodies of a part could not be told apart, `hidden_bodies_identified` false) |
| `mass` | what `IMassProperty2` covers with its defaults: hidden bodies and components left out (`include_hidden` false) |
| `assembly` (assemblies) | `components`, `suppressed`, `envelopes`, `part_components`, `hidden_part_components`, `subassemblies`, `unresolved`, `virtual`, `paths_under_document_folder`, `paths_elsewhere`, `lightweight_components` |

The measures, and what they cover, are those of the read-only harness that
measured the fixtures and a sample of the development corpus with SOLIDWORKS
2024 SP1, against which `tests/fixtures/ground_truth.json` was checked. What it
learned is kept:

- The boxes are precise: `IBody2.GetExtremePoint` along the six axis
  directions. `Component2.GetBodies3` returns a component's bodies in its
  part's own coordinates, so each is copied and moved by the component's
  `Transform2` first. `api_box_m` is the coarser `PartDoc.GetPartBox` or
  `AssemblyDoc.GetBox`, given for comparison: for fixture o16 it reaches
  0.13484 m where the bodies end at 0.12137 m.
- `mass.api` says which interface answered. A part whose bodies are all
  sheets gets no `IMassProperty2` at all; the older `IMassProperty` then
  reports 0. There is no mass for sheets: use `sheet_area_m2`.
- `IMassProperty2` returned volume, area and mass 0 for two corpus parts with
  a visible solid (saved by SOLIDWORKS 2016, no open warnings), while the
  import of their own STEP measured normal values. `mass.valid` is true only
  when `IMassProperty2` answered in SI units, a visible solid is there and the
  volume is more than 0. `warnings` names what to be careful of:
  `no_visible_solids`, `mass_zero_with_visible_solids` and `not_si_units`
  (each makes the mass not valid), `mass_overridden`,
  `center_of_mass_overridden` and `moments_of_inertia_overridden` (set by
  hand in the document, read from `IMassProperty2.GetOverrideOptions`, never
  set; volume and area are still the geometry's), `hidden_bodies_not_identified`,
  `bbox_errors`, `lightweight_components` and `unresolved_components`.
- Suppressed, envelope and unresolved components are left out of every body
  measure. An assembly `open_document` opens has its components resolved
  (`swOpenDocOptions_OverrideDefaultLoadLightweight`, a flag of that call,
  whatever the account's lightweight option says); under Large Assembly Mode
  some may still load lightweight, which `lightweight_components` counts.
  Opened so, an assembly makes SOLIDWORKS write briefly in its folder, as
  the side effects below say.
- Topology does not survive a STEP round trip: with the account's "split
  periodic faces" STEP option, fixture o11 has 12 faces natively and 14 after
  one. Compare volume, area, centre of mass and boxes instead.

Another configuration is measured by showing it (`ShowConfiguration2`), and
the active one is shown again afterwards (`restored_active_configuration`).
The document is never saved, but once another configuration was shown
SOLIDWORKS marks it changed, and the harness noted it changed for as long as
it stayed open. Whether showing the active one again clears the mark has not
been measured: the reply's `dirty` is read after that, so it says, and the
opt-in test prints it before and after. A watched part reports
`ActiveConfigChangePostNotify`. Nothing is rebuilt, selected or set; the mass
property object's options are read, never changed, because some are kept
with the document.

### Importing: `import_file`

```json
{"id": 4, "op": "import_file", "args": {"path": "D:\\Copies\\bracket.step", "template": "C:\\ProgramData\\SolidWorks\\SOLIDWORKS 2024\\templates\\MBD\\part 0051mm to 0250mm.prtdot"}, "timeout_s": 600}
{"id": 4, "ok": true, "result": {"doc": 3, "title": "Part1", "path": "", "type": "part", "read_only": false, "dirty": true, "method": "insert", "format": "step", "source": "D:\\Copies\\bracket.step", "errors": 0, "feature": {"name": "bracket.step<1>", "type": "MBimport", "interconnect": true}, "feature_types": {"MBimport": 1, "RefPlane": 3, "...": 1}, "solid_bodies": 1, "sheet_bodies": 0, "result_kind": "solids", "step_census": {"products": 1, "assembly_links": 0, "solids": 1, "surface_models": 0, "tessellated": 0, "free_curve_sets": 0, "shells": 1, "one_body": true, "entities": {"PRODUCT": 1, "...": 0}}, "preferences": {"swMultiCAD_Enable3DInterconnect": true, "swImportNeutralAssemblyStructureMapping": 1, "...": 0}, "default_part_template": {"exists": true, "extension_ok": true}, "dialogs": [], "dialog_appeared": false, "window_watch": true, "seconds": 2.4}}
```

`import_file` imports a STEP file into a new document of SolidSeas' own
instance; IGES and Parasolid (`.x_t`, `.x_b`) files go the same way. It never
changes an option. Three ways, named by `method`:

- `insert`, the default: a new part made from the template the request names,
  as `new_document` makes one, and the file inserted into it with
  `IPartDoc.InsertImportedFeature`, which goes through 3D Interconnect.
  SOLIDWORKS never picks a template and never makes an assembly. Give it a
  template the SOLIDWORKS installer ships, such as those in
  `C:\ProgramData\SolidWorks\SOLIDWORKS 2024\templates\MBD`. It needs 3D
  Interconnect on in the account's import options.
- `load`: `ISldWorks.LoadFile4(path, "r", data)`, as File Open imports a
  file, into a document SOLIDWORKS makes from the default part template the
  account's options name (read, never set). The one piece of per-call data
  is `IImportStepData.MapConfigurationData`, which overrides the account's
  "map configuration data" STEP option for that import alone, and only when
  the request gives `map_configuration_data`.
- `component`: a new assembly made from the template the request names (an
  `.asmdot`, such as the MBD folder's `assembly 0250mm and smaller.asmdot`),
  and the file inserted into it as one component with
  `IAssemblyDoc.InsertImportedComponent`, which also goes through 3D
  Interconnect and needs it on. The way for a STEP of several bodies or of an
  assembly, which the other two refuse: 3D Interconnect makes the component a
  sub-assembly of parts it makes in memory (two bodies, two parts; an
  assembly's parts and their placements), and a file of one body a part.
  SOLIDWORKS places the component wherever it likes, whatever point it is
  given (measured: 6 to 33 mm off the origin, differently each time),
  so the bridge then sets its transform to the identity: the file's
  coordinates are the assembly's, and `mass_properties` of the assembly gives
  the file's own measures. `component` says what came in: its `name`, how many
  `children` it has, the extension of the document 3D Interconnect made for it
  (`document_extension`, `.sldasm` or `.sldprt`; never its path, which may be
  in the account's own folders), whether that document is the source file
  (`refers_to_source`, false: 3D Interconnect makes a document of its own),
  whether it is `virtual`, the transform SOLIDWORKS `placed` it with (the
  rotation's nine numbers, then the translation in metres), and `at_origin`,
  whether it is at the origin now. Closing the assembly closes the documents
  3D Interconnect made for it too (measured).

The new document is the bridge's like any it made: `mass_properties`,
`save_copy`, `watch_document` and `close_document` take it, and it is never
saved. Its `path` is empty. `result_kind` is `solids`, `solids_and_surfaces`,
`surfaces_only` or `empty`; the body counts include hidden bodies. `feature`
is the feature `InsertImportedFeature` returned, and `feature_types` counts
the document's features by type (an import through 3D Interconnect makes an
`MBimport` feature). `dialogs` lists the dialogs of the instance the window
watch left alone while the import ran (`hwnd`, `class`, `title`, `text`), so
`dialog_appeared` says whether one came and went; it looks once more before
it answers. An import that brings nothing fails with `import_failed` and the
same details, and the document made for it is closed again.

What happened in the user's own SOLIDWORKS 2024 SP1 on 2026-10-04, through the
measuring harness and `LoadFile4(path, "r")`: a single-body STEP imported as a
part with one `MBimport` feature, with no dialog, every time. Fixture o12's
two-body STEP became an assembly, because 3D Interconnect is on and Assembly
Structure Mapping is set to "import multiple bodies as parts", and SOLIDWORKS
stopped behind its New SOLIDWORKS Document template dialog for three hours,
although "always use default templates" was on and the default templates
exist. A single-sheet STEP of 1,018 faces passed five minutes behind a modal
window while SOLIDWORKS used about two cores, where a file of the same size
and face count had imported in 8 s. In SolidSeas' own instance either would
only end that instance at the request's timeout, but `import_file` avoids
what can be foreseen:

- The template is given (`insert`, `component`), so SOLIDWORKS never asks for
  one. `insert` makes a part; a STEP of several bodies faulted there while the
  account's options make several bodies parts, so it is refused, and
  `component` takes it.
- The account's import options that decide what happens are read and
  returned in `preferences` (3D Interconnect and its links, "always use
  default templates", the Import Diagnostics options, the STEP/IGES/ACIS
  options, Assembly Structure Mapping, check and repair, units, "import
  multiple bodies as parts", "map configuration data", "show IGES levels"),
  and `default_part_template` says whether the default part template exists
  and is a `.prtdot` file, never its path.
- `step_census` counts the entities of a STEP file, outside strings and
  comments, without SOLIDWORKS. The cases the file or the options make
  predictable are refused (`refused`, with `details.reason`) before anything
  is imported:

| `reason` | When |
|---|---|
| `step_assembly` | `insert` or `load` of a STEP with more than one `PRODUCT`, or with `NEXT_ASSEMBLY_USAGE_OCCURRENCE` or `MAPPED_ITEM`: SOLIDWORKS would make an assembly of it, which `component` takes |
| `no_bodies` | a STEP with no solid, surface model or tessellated body (any method) |
| `interconnect_off` | `insert` or `component` while 3D Interconnect is off (SolidSeas never turns it on; use `load`) |
| `several_bodies_insert` | `insert` of a STEP that may hold more than one body (counted as for `several_bodies_as_assembly`) while 3D Interconnect makes several bodies parts (mapping "multiple parts"): SOLIDWORKS faulted with `RPC_E_SERVERFAULT` every time this was measured (o12 on 2026-10-05 and 2026-10-14, 21 corpus parts on 2026-10-05); use `component` |
| `default_templates_off` | `load` while "always use default templates" is off: SOLIDWORKS would ask for a template |
| `default_template_missing` | `load` while the default part template is not a `.prtdot` file that exists |
| `several_bodies_as_assembly` | `load` of a STEP that may hold more than one body (anything but exactly one body with exactly one shell) while the options make several bodies an assembly (3D Interconnect on and mapping "multiple parts", or 3D Interconnect off and "import multiple bodies as parts" on): the measured template dialog (in the user's session on 2026-10-04, and in SolidSeas' instance alone on 2026-10-14, once, with this refusal set aside: "New SOLIDWORKS Document" beside "Open Progress..." until the request's timeout ended the instance); use `component`. `load` of an IGES file, whose bodies are not counted, is refused only while 3D Interconnect is on with mapping "multiple parts": "import multiple bodies as parts" is for STEP and ACIS files only, the API help says |
| `iges_levels_dialog` | `load` of an IGES file while 3D Interconnect is off and "show IGES levels" is on |
| `title_open` | `load` of a file whose name is the title of a document open in the instance, which `LoadFile4` would hand back instead of a new one |

What can still raise a dialog, and then ends SolidSeas' instance at the
request's timeout (the client's `BridgeTimeoutError` names the dialog):

- The Import Diagnostics question. While
  `swImportAutoRunImportDiagnosticsPersist` is off, as it is on the test
  machine, users are asked whether Import Diagnostics should run, the API
  documentation of that option says. The single-body imports measured did not
  ask. Whether the question depends on faulty faces SOLIDWORKS finds in what it
  imported, known only after the import, and whether it comes through 3D
  Interconnect and `InsertImportedFeature`, has not been measured; the option
  is shared with the user's session, so it is reported, never changed.
- A long translation behind a progress or modal window, as the single-sheet
  STEP above; the request's timeout (600 s by default) bounds it.
- Every method for IGES files, and `component` for Parasolid files: not
  measured yet. A Parasolid or IGES file's bodies are not counted, so `load`
  of one with several bodies may still meet the template dialog if SOLIDWORKS
  makes an assembly of it, and `insert` of one may fault as a STEP of several
  bodies did (`several_bodies_insert`); `component` is the way for those.
- Anything SOLIDWORKS shows that does not depend on these options, such as a
  licence or add-in prompt.

An import changes nothing on disk: the source is only read, the new document
is never saved, and with 3D Interconnect links on it keeps a link to the
source file that ends with the document. SOLIDWORKS adds the file to the
account's recent documents. The imported document is changed and unsaved
while it is open, so when SolidSeas' instance runs alone (the off-hours case)
SOLIDWORKS could save an auto-recover copy of it if it stayed open past the
auto-recover interval; close it when done, as batch work does.

```python
from solidseas.swapi.bridge import Bridge, BridgeTimeoutError

with Bridge() as b:                              # finds the program, starts it in a Job Object
    b.request("start_solidworks")                # SolidSeas' own, hidden SOLIDWORKS
    doc = b.request("open_document", {"path": r"D:\Copies\bracket.SLDPRT"})
    b.request("save_copy", {"doc": doc["doc"], "path": r"D:\Exports\bracket.step"}, timeout=300)
    b.request("close_document", {"doc": doc["doc"]})
                                                 # leaving the block ends SOLIDWORKS, then the bridge
```

Call it from a worker thread, never from a Qt thread. The bridge answers one
request at a time, in order, so a request sent while another runs waits for it,
and that wait counts toward its timeout. Every request has a timeout: the
default for its operation (`DEFAULT_TIMEOUTS`, from 15 s for `hello` to 600 s
for `save_copy`), `HARD_LIMIT_S` (600 s) for any other, and never more than
`MAX_TIMEOUT_S` (86,400 s, the bridge's own limit). When it runs out, the client
terminates the bridge's job, waits until every process in it has gone, and
raises `BridgeTimeoutError`, which names the dialogs the bridge reported
while the request waited (`details["dialogs"]`, the `window` events); requests waiting at that moment, and any made
afterwards, raise `BridgeExitedError`, as they do when the bridge crashes. A
refusal or failure the bridge reports raises `BridgeRequestError` with its
`code`, `details` and `hresult`. A timeout out of range, or a request longer
than the bridge reads (`MAX_REQUEST_CHARS`), raises `ValueError` and is never
sent; a reply the bridge sends without an id answers the oldest request still
waiting, so it never waits out its timeout. `on_event` is called with every
event line, in order, on a thread of its own, never the one that reads replies,
so a slow listener holds neither the replies nor SOLIDWORKS. Past 10,000
events waiting for it, more are dropped and counted (`events_lost`), and it
then gets `{"event": "events_lost", "count": n, "where": "client"}`. `events`
keeps the last thousand. `close()` asks for `shutdown` and ends the job if that
has no answer in time. If the bridge cannot be put in its Job Object, the
client ends it by its own handle at once.

### Live mode: the person's own SOLIDWORKS

The `list_sessions` and `live_*` operations serve the modeling assistant
(`docs/ASSISTANT.md`, `solidseas_app.assistant.live_sessions`). They attach to a
SOLIDWORKS the person started, by its process id, through the moniker
`SolidWorks_PID_<pid>` and nothing else, and they never end it, close or save
one of its documents, or change a SOLIDWORKS option. A bridge in live mode
starts no SOLIDWORKS, so when the client ends the bridge's job after a
timeout, nothing of the person's goes with it.

- The session list reads each `SLDWORKS.exe` in the bridge's Windows session.
  One started elevated, while the bridge is not, is reported as
  `administrator`. One a SolidSeas bridge started for batch work carries the
  named object `Local\SolidSeas-Batch-<pid>` while it runs and is reported as
  `solidseas`; the app leaves those out, and tests attach to one in place of a
  person's session.
- A document is named by its `key`: its full path, or its title while it has
  never been saved. Entities are named by persist references
  (`GetPersistReference3`, base64); a dimension by `dim:<its feature's
  reference>:<its own name>`, from which the bridge builds the name
  `D1@Sketch2` itself, so no other document can be named.
- `live_checkpoint` writes the safety copy with `SaveAs3` and
  `swSaveAsOptions_Copy` (answer 1 of the spike), only as
  `checkpoint-<run id>.sldprt` in a run folder in `<data dir>\runs`, where
  `<data dir>` is `SOLIDSEAS_CACHE_DIR` or `%LOCALAPPDATA%\SolidSeas`, as for
  the app, and never over a file that is there.
- `live_begin_undo` records the document in `<data dir>\live-undo-<pid>.txt`
  before it opens the undo entry, and `live_end_undo` deletes it after closing
  it. A bridge that attaches while no SolidSeas window holds the session, or
  begins the next script, closes an entry an ended bridge left open.
- `live_operation` works on the active part only, never while a sketch is open
  for editing in it. `set_dimension` takes `dimension` and `value` (metres or
  radians) in the active configuration and rebuilds. `sketch_extrude_boss` and
  `sketch_extrude_cut` take `plane` (a reference plane or a planar face),
  `segments` (`line`: `start`, `end`; `arc`: `center`, `start`, `end`,
  `clockwise`; `circle`: `center`, `radius`; points in metres in the plane's
  frame), `depth`, `direction` (`normal` or `reversed`; `normal` is
  SOLIDWORKS' own: a boss along the plane's normal, a cut against it) and
  `end` (`blind`, or for a cut `through_all`). The frame is the one the
  snapshot reports: a reference plane's own transform, and for a planar face
  its outward normal, the model origin's foot on its plane as the origin, and
  the first of the model's X, Y and Z axes not nearly along the normal, made
  perpendicular to it, as x. The points go into the sketch through its own
  `ModelToSketchTransform`, and an arc's turn follows that transform, so a
  profile lands where the snapshot said, whatever axes SOLIDWORKS gives the
  sketch. `fillet` (`edges`, `radius`, constant, without tangent propagation)
  and `chamfer` (`edges`, `distance`, at 45 degrees) select their edges and
  check the selection just before the call (a fillet definition naming its
  edges made no fillet, below);
  `suppress` and `unsuppress` take `features`; `set_property` takes `name`,
  `value` and `scope` (`file` or `configuration`) and refuses the names
  downstream systems key on and values that start with `=`, `+`, `-` or `@`.
  `shell`, `linear_pattern` and `circular_pattern` answer `not_supported`
  for now.
- `live_delete_feature` deletes only a feature this bridge made, selected by
  its reference, with `swDelete_Absorbed`, so an extrude's sketch goes with it
  (answer 6). A failed extrude deletes the sketch it made in the same way.

### How it keeps away from the user's work

- In batch mode it starts its own `SLDWORKS.exe` and binds only to the Running
  Object Table moniker `SolidWorks_PID_<pid>` of that process, compared in
  full. It never calls `GetActiveObject`; live mode, above, is the only way it
  attaches to an instance it did not start. One SolidSeas-started SOLIDWORKS runs at a time in a Windows session:
  `start_solidworks` takes the named mutex `Local\SolidSeas-SwBridge-SolidWorks`
  and refuses when another bridge holds it.
- As soon as the instance registers, the bridge hides it and takes it out of the
  user's hands (`Visible = false`, `UserControl = false`), and again after every
  `new_document` and `open_document`, because `NewDocument` turns
  `UserControl` back on. Alone (no other SOLIDWORKS running) the frame still
  showed after a new document (2026-10-14), so after a new document and an
  import as a component the frame is hidden again three times 100 ms apart. That
  is not enough alone: the frame stays visible and minimized (a taskbar button),
  and SOLIDWORKS' Welcome screen shows after every start until the first
  document (SolidSeas-okg, measured 2026-10-15). Hiding new documents with
  `ISldWorks.DocumentVisible` kept them hidden but broke component imports
  (`RPC_E_SERVERFAULT`), STEP inserts (stopped behind Open Progress) and live
  mode (the new part not the active document), so it is not used. It does not wait for `StartupProcessCompleted`, which a
  hidden instance never sets; calls made while it is still busy starting are
  retried by the message filter. Until it registers it cannot be hidden, and
  its journal file message box is hidden separately: see "Starting takes the
  foreground" below.
- It sets no SOLIDWORKS option or user preference. Those live in the registry
  and are shared with every session of the Windows account, so a value set for
  an export would change the user's session too. It reads `swStepAP` to
  report which STEP application protocol a STEP file was written with, and
  `import_file` reads the import options it reports. Documents are created
  only from a template path given in the request, never through the
  default-template setting, except by `import_file` with `method` `load`,
  where SOLIDWORKS uses the default part template the account names, and
  which is refused when that would make SOLIDWORKS ask for one. SOLIDWORKS itself writes the add-ins'
  toolbar values to that registry when it starts. `ExitApp`, SOLIDWORKS' own
  shutdown, would also write the instance's layout there, which is why the
  bridge no longer calls it: see the side effects below.
- It opens documents read-only, always, and silently, so it never leaves a
  `~$` lock file behind, not even when a timeout ends the instance. Read-only
  is not write-free for an assembly: opening one makes SOLIDWORKS write
  briefly in its folder (see the side effects below). It refuses a document
  already open in the instance, writes with `IModelDocExtension.SaveAs3` and
  `swSaveAsOptions_Silent | swSaveAsOptions_Copy` to export formats only, and
  closes only the documents it opened or created. It never calls `Save`,
  `CloseAllDocuments` or `RunMacro`.
- It never writes over the file of a document open in the instance, whatever
  name the request uses for it. Comparing paths is not enough: a junction, a
  hard link, a mapped drive or a short name is another name for the same file.
  Before replacing an existing output, `save_copy` compares the file itself
  (volume and file id, `GetFileInformationByHandleEx`) with every open
  document's, and refuses a match, or a file it cannot identify. Measured
  before this check: `save_copy` to a `.step` name hard-linked to the open part
  emptied the part, and to its `.SLDPRT` through a junction overwrote it.
- It ends its instance directly: it closes the documents it opened or created,
  without saving any, and then terminates the instance's Job Object, which
  ends that `SLDWORKS.exe` and whatever it started with exit code 21331
  (`0x5353`), and nothing else. It never calls `ExitApp`, SOLIDWORKS' own
  shutdown, which rewrites about 230 values of the layout the user's session
  shares (see the side effects below). It holds no document of the user's and
  no unsaved work, short of a document a person opens in it in the seconds
  before it is hidden; what ending it this way leaves is listed under the side
  effects. If terminating fails, closing the job ends the instance all the
  same (kill-on-close).
- It sets `SetErrorMode` so a crash in the bridge never opens a dialog; the
  SOLIDWORKS it starts keeps its own error mode.

### Timeouts and a stuck SOLIDWORKS

A call into SOLIDWORKS that never returns, for example because a dialog opened
in the hidden instance, blocks the bridge's apartment thread and nothing in the
bridge can interrupt it. The caller's timeout is what ends it: the client
terminates the job, which ends the bridge, the SOLIDWORKS it started and any
dialog in it, and the caller goes on. Measured with SOLIDWORKS 2024 SP1 on
Windows 10 (the tests repeat each case):

| Case | Caller's timeout | Raised after | SOLIDWORKS gone after |
|---|---|---|---|
| The apartment thread blocked for ten minutes, no SOLIDWORKS | 1 s | 1.00 s | |
| `open_document` of a part, a real SOLIDWORKS call | 0.05 s | 0.09 s | 0.31 s |
| The apartment thread blocked with a part open in SOLIDWORKS | 2 s | 2.06 s | 2.28 s |

In every case the user's own SOLIDWORKS kept running and the job was empty
afterwards.

### Starting takes the foreground, and the journal file message box

SOLIDWORKS ignores the show-window hint it is started with, and the bridge can
hide it only once it has registered in the Running Object Table. Measured with
SOLIDWORKS 2024 SP1 while the user's SOLIDWORKS ran: from about 0.3 s after
`start_solidworks` was sent until 6 to 7 s after it, the new instance's splash
screen and then its main window were the foreground window, so keys and clicks
meant for the user's own SOLIDWORKS reached SolidSeas' instance instead. A
shortcut that opens a dialog there blocks the next request until its timeout
ends the instance. Nothing in the bridge shortens that, so long batch jobs run
off-hours: a job SolidSeas starts by itself passes an `OffHours` window,
02:00 to 07:00 local time by default, and runs SOLIDWORKS only inside it. It
starts SOLIDWORKS (the first time, and again after a timeout) only when local
time is inside the window, waiting otherwise, and looks again before every
document it opens and every export it asks for: once the window has closed, it
closes the document in hand, ends the instance through its job and goes on,
with that document's remaining formats, in the next window. The instance
therefore outlasts the window by at most the request it was in when the window
closed, one export and one close, each within its timeout (at least one export
of a document is made each time, so a window shorter than an open still gets
work done). A job the user starts runs at once and to its end;
`python -m solidseas.swapi convert --off-hours` makes one keep to the window
too.

While another SOLIDWORKS runs, the instance also opens a message box, titled
SOLIDWORKS, that reads "A journal file could not be created. Auto recover will
not work. Another session of SOLIDWORKS may already be running on this
machine." It looks as if it comes from the user's SOLIDWORKS, but it belongs to
SolidSeas' instance. Hiding the instance does not hide it, it stays until that
instance ends, and in one run it took the foreground again four times as
other programs' windows came and went. It does not stop the instance from
working.

The reverse is the off-hours case. When no other SOLIDWORKS runs, SolidSeas'
instance is the first session on the machine and makes the journal file
itself, so a SOLIDWORKS the user starts while it runs is the second session:
that SOLIDWORKS should show this same box, in the user's own process, where the
bridge leaves it, and run without auto-recover, presumably until it is
restarted. That has not been measured; it follows from the message and from
which session holds the journal file. It is why an off-hours job ends its
instance when the window closes instead of running on into the day. A job the
user starts and leaves running has the same effect if the user then starts
SOLIDWORKS, so start yours before such a job, not during it.

The bridge hides that box with one `ShowWindow(SW_HIDE)` call. It never clicks
it, closes it, activates it or sends it a message of its own, and the box goes
when the instance ends. Windows itself sends the box the notifications that
come with being hidden, and if the box was the foreground window, Windows
activates another one: during start-up most likely SolidSeas' splash or main
window, which hold the foreground then anyway, and after it the next visible
window, normally the one the user was in, which gets back the foreground the
box took. A window is hidden only when all of this holds:

- its process is the `SLDWORKS.exe` the bridge started, by process id, and that
  process is in the bridge's Job Object. The bridge holds a handle on the
  process, so the id cannot pass to another one, and a process never leaves a
  job. A window of a program that process started is looked at too, but never
  hidden, and a window of a process outside the job, the user's SOLIDWORKS
  included, is never read past its process id;
- it is a visible top-level dialog (window class `#32770`) whose title names
  SOLIDWORKS;
- everything inside it is a static text or a button, as in a message box, and
  one static text holds the stable words of the message ("journal file",
  "could not be created", "another session of SOLIDWORKS"), compared ignoring
  case and line breaks. A SOLIDWORKS in another language does not match, and
  its box stays.

The process id is checked again just before the call. The watch runs on a
thread of its own, so it works while a request is inside SOLIDWORKS: it looks
every 100 ms from the moment the process starts until a minute after the
instance registers, then every second and at once whenever a window of that
process is shown (a WinEvent hook limited to that process: in the window
check, a box shown again during the slow looks was hidden again within one
16 ms tick of the system clock, in five runs out of five). Each hide is a
`window` event and a line on standard error with the window's class, title and
text; if SOLIDWORKS shows the box again it is hidden again (`"again": true`).
Every other dialog of the instance, or of a program it started, is left as it
is and reported once (`"action": "left"`); a request it blocks is ended by its
timeout, as before. Batch conversion writes both to its log.

Starting SOLIDWORKS on a desktop of its own (`CreateDesktop`, then the desktop
in `STARTUPINFO`) would keep the splash and the box off the user's screen. It
was tried: there SOLIDWORKS showed its splash, then that message box, and then
sat idle (its CPU time did not move for two minutes) and never registered,
because nobody can answer a box on a desktop no one sees. So SolidSeas'
instance starts on the user's desktop.

### SOLIDWORKS not activated

A SOLIDWORKS that is not activated on the PC (a standalone licence moved to
another computer, or a grace period run out) starts SOLIDWORKS Product
Activation, `swactwiz.exe /primprod:solidworks /auto /expirycheck`, as it starts
up, and waits while the wizard asks what to do; measured with SOLIDWORKS 2024
SP1 on 2026-10-14, when the wizard said "There are 0 day(s) left in your grace
period" with the choice to activate later disabled. Its splash stays and it
never registers, so before this was understood `start_solidworks` waited its
whole timeout (15 minutes in that run) with nothing to say why.

The window watch therefore looks at the windows of every process in the
bridge's Job Object, the programs `SLDWORKS.exe` starts as well as its own,
each taken as one of the job only through a handle the watch opens on it and
checks to be in the job. A visible dialog of `swactwiz.exe` in the job is
reported as `"kind": "activation"` and left as it is: nothing SolidSeas runs
answers that wizard, since a wrong choice there can move a standalone licence
away. `start_solidworks` then fails at once, within a quarter of a second of the
watch seeing the wizard, with `solidworks_not_activated` ("SOLIDWORKS needs
product activation on this PC"), the wizard's dialog in `details.activation`,
and ends the instance through its job, which ends the wizard with it. A
SOLIDWORKS the user starts, and its wizard, are outside the job and never
looked at. Batch conversion does not start SOLIDWORKS again in that run: the
documents after it are not attempted, and their rows say why. Activate
SOLIDWORKS (in a SOLIDWORKS of the user's own) and start again.

## Batch conversion

```powershell
python -m solidseas.swapi convert D:\Jobs\Bracket -o D:\Exports --format step,x_t,stl,3mf --recurse
python -m solidseas.swapi convert D:\Jobs -o D:\Exports --recurse --off-hours        # runs only from 02:00 to 07:00
```

`solidseas.swapi.batch.convert()` does the same from Python and returns one
`ConversionRow` per document and format. It starts a bridge and its SOLIDWORKS
on the first document that needs one, and for each document opens it
read-only, writes one copy per format, and closes it, each step a request with
its own timeout (`Timeouts`: start 360 s, open 300 s, each export 600 s, close
120 s, exit 180 s). When a step times out, or SOLIDWORKS stops answering, the
bridge and that SOLIDWORKS are ended, the document's remaining formats are
reported as not attempted, and the next document gets a fresh bridge and
SOLIDWORKS, up to three restarts. A refusal or a failed open or export of one
document does not end the instance. Given `off_hours` (`--off-hours`, with an
optional `HH:MM-HH:MM` window), SOLIDWORKS runs only inside the window: every
start, a restart included, waits until local time is inside it, and once it
has closed, before the next document or export, the document in hand is
closed, SOLIDWORKS is ended through its job and the work goes on, with that
document's remaining formats, in the next window. That pause is not counted as
a restart. The log says how long it waits, and how each SOLIDWORKS ended
(`job_terminated` and exit code 21331 when the bridge ended it through its
job).

The output folder may not be, or lie in, a folder that holds an input document
unless `--allow-source-folder` is given; an existing output is kept (a `skip`
row) unless `--force`; two inputs with the same name never write the same
output. The command writes `report.tsv` to the output folder (input, status,
format, output, code, SOLIDWORKS error and warning codes, seconds, STEP
application protocol, message; a cell that starts with `=`, `+`, `-` or `@` gets
an apostrophe so a spreadsheet never runs it), refuses to replace an existing
one without `--force`, and exits 0 when every row is `ok` or `skip`, 4 when
any failed, 2 for wrong arguments, 3 when the report exists and 1 when the
bridge could not be used at all.

| `--format` | Output | Result with SOLIDWORKS 2024 SP1 |
|---|---|---|
| `step` | STEP (`.step`) | written, in the application protocol the account's SOLIDWORKS options name (203 on the test machine; the row's `step_ap` says which) |
| `x_t`, `x_b` | Parasolid text and binary | written |
| `stl` | STL | written with the account's STL options; SOLIDWORKS names it `.STL` |
| `3mf` | 3MF | written |
| `gltf`, `glb` | glTF | refused by `SaveAs3` with `swFileSaveAsInvalidFileExtension` (256) on 2026-10-05; written on 2026-10-14 (glTF 2, generator "SOLIDWORKS GLTF"), the `.gltf` into a folder named after it and the `.glb` with its name lowercased |

The earlier `Convert-WithSolidWorks.ps1` set the STEP application protocol to
242 for each export and restored it afterwards. The bridge does not, because
that preference is shared with the user's running session; choose AP242 in
SOLIDWORKS' own export options if you need it.

### What has and has not been checked

| Item | Status |
|---|---|
| The bridge builds with `csc.exe` (C# 5) against the SOLIDWORKS 2024 interop assemblies, from both build commands | verified |
| Protocol, refusals, the test operations, and a request stuck in the apartment thread ended within its timeout, without SOLIDWORKS | verified, `SOLIDSEAS_SWAPI_BUILD_CHECK=1` |
| Batch conversion end to end in SolidSeas' own SOLIDWORKS: four fixture parts (one with a Cyrillic name) to STEP, x_t, x_b, STL and 3MF; glTF and GLB fail as above | verified, `SOLIDSEAS_SWAPI_SOLIDWORKS=1` |
| A real SOLIDWORKS call given a timeout it cannot meet ends that SOLIDWORKS through the job; the user's SOLIDWORKS untouched | verified |
| `new_document` from the Dassault-shipped MBD part template, `watch_document`, and `DestroyNotify2` arriving at the bridge while `close_document` runs | verified |
| The window rule on described windows: only a visible `#32770` of the bridge's own process, in its job, titled SOLIDWORKS, holding only static texts and buttons and the journal words, is hidden | verified, `SOLIDSEAS_SWAPI_BUILD_CHECK=1` |
| Real windows: the bridge started a stand-in `SLDWORKS.exe` showing dialogs off screen, hid its journal box, and again when it was shown again, left its other two dialogs, and touched none of an identical stand-in outside its job | verified, `SOLIDSEAS_SWAPI_WINDOW_CHECK=1` |
| The WinEvent hook: with the fast phase cut to 1 s and slow looks 20 s apart (`watch_timing`), a stand-in's box shown again during the slow looks was hidden again within one 16 ms tick of the system clock (0 to 15 ms in five runs), which only the hook can do; with the hook call removed, the same test fails | verified, `SOLIDSEAS_SWAPI_WINDOW_CHECK=1` |
| The real journal file message box hidden while another SOLIDWORKS runs, no window of that SOLIDWORKS hidden, how long the splash holds the foreground, which window has the foreground right after each hide (never SolidSeas' once `start_solidworks` has returned), and the box staying hidden while a window of the test's own comes and goes five times | verified on 2026-10-05 with another SOLIDWORKS open (`SOLIDSEAS_SWAPI_SOLIDWORKS=1`): the journal box hidden 6.1 s after the start, no window of the other SOLIDWORKS hidden and no other dialog touched; SolidSeas' instance held the foreground for 5.6 s of samples, the last 5.9 s after the start, and `start_solidworks` returned after 6.2 s; the hide handed the foreground to another program, not to SolidSeas' instance; the box stayed hidden while the test's window came and went five times (Windows let it take the foreground once) |
| Ending through the job: exit code 21331, nothing written to the `User Interface` layout in the registry, no lock file, the source unchanged, and a second start showing no dialog the first did not | verified on 2026-10-05 with another SOLIDWORKS open (`SOLIDSEAS_SWAPI_SOLIDWORKS=1`): exit code 21331 both times; 99 values changed under `HKCU\Software\SolidWorks`, none of them in the `User Interface` layout (97 in the recent documents list, see below, the other two `General\Last Splash Id` and a value under `General\Addin Performance`); no lock file, the source unchanged, and no dialog at the second start that the first did not show |
| SolidSeas' instance alone, the off-hours case: ended through its job after opening a part and making a document, then by a timeout with the part open, then started again. What changed in `%APPDATA%\SolidWorks` (the journal file) and in the auto-recover and backup folders the options name, no auto-recover copy or backup made, no box hidden, and no dialog at the next start that the first did not show | verified on 2026-10-14 (`SOLIDSEAS_SWAPI_SOLIDWORKS=1`, `-k no_recovery_behind`, no other SOLIDWORKS running) |
| A SOLIDWORKS of the user's started while SolidSeas' instance runs alone: the journal box in the user's session, and no auto-recover there | not measured; an off-hours job ends its instance when the window closes, so it does not run into the day |
| Batch conversion keeping to the off-hours window: started only inside it, ended through its job once it closes, the rest of the work done in the next window, the batch log saying how each instance ended | verified with the stand-in bridge |
| `ExitApp`, before the bridge stopped using it: it ended the instance (exit code 45) within about 2 s, and wrote the layout described below. The bridge no longer calls it | measured; no longer how the instance ends |
| Assemblies: opening one loads its components through SOLIDWORKS' reference search, which may look in folders the account's options name | not run; the end-to-end run used parts only |
| Opening an assembly with the flags `open_document` uses (read-only, silent, resolved) changing its folder's modification time with the same entries before and after, a brief write; part opens and STEP imports leaving their folders alone | measured by the harness on the copy of o08, twice; the opt-in `mass_properties` test prints the folder's time again |
| A start-up dialog or a missing-reference prompt in the hidden instance | not provoked; a call it blocks is ended by its timeout as above |
| The window rule on described windows of the programs SOLIDWORKS starts: a dialog of `swactwiz.exe` in the job is `activation` (its program's name in any case, its title in any language), the same dialog outside the job not looked at, one of another program in the job left and never hidden, even with the journal words | verified, `SOLIDSEAS_SWAPI_BUILD_CHECK=1` |
| Real windows: a stand-in `SLDWORKS.exe` starting a stand-in `swactwiz.exe` that shows the wizard's dialog off screen; `start_solidworks` failing with `solidworks_not_activated` at once, the dialog reported and never touched, the stand-ins ended with the job, and an identical `swactwiz.exe` outside the job left as it was | verified, `SOLIDSEAS_SWAPI_WINDOW_CHECK=1` |
| A SOLIDWORKS that is not activated, the real wizard: `start_solidworks` failing with `solidworks_not_activated`, the wizard never answered, the instance and the wizard ended | verified on 2026-10-14 with SOLIDWORKS 2024 SP1 not activated on the PC and the user's own SOLIDWORKS open beside it: the request failed after 2.2 s with `swactwiz.exe`'s "SOLIDWORKS Product Activation" dialog in `details.activation` and as the one `activation` event, nothing hidden or answered, and afterwards no process of the job running and the user's SOLIDWORKS as it was; before this change the same start waited 15 minutes |
| `ModifyNotify`, `FileSaveNotify`, `UndoPostNotify` and the other notifications | subscribed, not yet seen; no operation changes a document |
| Events queued without waiting: 20,000 queued in 16 ms with nobody reading standard output, 4,265 written once read, the rest reported in `events_lost` | verified, `SOLIDSEAS_SWAPI_BUILD_CHECK=1` |
| `save_copy` refusing a hard link to the open part, and drive-relative, root-relative and network paths; `open_document` refusing to open for writing | verified |
| `import_file` and `mass_properties` checking their arguments, and the STEP census (strings, comments and header records ignored, entity names in any case) refusing STEP assemblies and STEPs without bodies, before SOLIDWORKS is asked anything | verified, `SOLIDSEAS_SWAPI_BUILD_CHECK=1` |
| The window watch keeping the dialogs it leaves: a stand-in that never registers fails `start_solidworks` with the two dialogs it left in `details.dialogs`, not the box it hid | verified, `SOLIDSEAS_SWAPI_WINDOW_CHECK=1` |
| A request held by a dialog: the client's `BridgeTimeoutError` names the dialogs that appeared while it waited, and only those | verified with the stand-in bridge |
| `mass_properties` of fixture copies (o01, o02, o06 by configuration name, o11, o12, o13 every configuration, the assembly o08) against `ground_truth.json`, the active configuration shown again, `dirty` before and after that printed, and, with no other SOLIDWORKS running, no auto-recover copy or backup | run on 2026-10-05 with another SOLIDWORKS open (`SOLIDSEAS_SWAPI_SOLIDWORKS=1`): every measure matches `ground_truth.json`, and the test then fails where it closes a part after the assembly that used it, before its last checks (known issues, below) |
| `import_file` of `o02_boxA.step`, `.x_t` and `.x_b` and of SolidSeas' own STEP of o11 and o12, `insert` and `load`, each in an instance of its own: no dialog, the measures against `ground_truth.json`, the source folder unchanged, and, with no other SOLIDWORKS running, no auto-recover copy; `load` of o12 refused as `several_bodies_as_assembly` under the account's options | run on 2026-10-05 with another SOLIDWORKS open (`SOLIDSEAS_SWAPI_SOLIDWORKS=1`; every test run writes SolidSeas' STEP of o11 and o12 with `solidseas.step`, without SOLIDWORKS): the Parasolid imports and o12's `load` pass; the STEP imports of o02 and o11 import with no error by both methods but fail on `dialog_appeared`, and o12's `insert` faults (known issues, below); run again on 2026-10-14 with SolidSeas' instance alone: the same, except that `load` of o02's and o11's STEP held behind "Open Progress..." until the 600 s timeout ended the instance |
| SolidSeas' STEP read back by SOLIDWORKS: `solidseas.step`'s STEP of the fixture parts and of 175 corpus parts, imported with `import_file` (`insert`) into SolidSeas' own SOLIDWORKS off-hours and measured with `mass_properties` against SOLIDWORKS' measures of the parts themselves | measured on 2026-10-05, numbers only (`docs/FORMAT.md` 10.9): 12 fixtures exact; the 130 corpus parts that came back as solids within 7.5e-15 of SOLIDWORKS' volume at the median, 1.3e-6 at the 90th percentile and 1.7e-4 at most, on most parts at least as close as SOLIDWORKS' own STEP round trip; with faces cut at their seams the imports have the face count of SOLIDWORKS' own round trip on 106 of 139 parts, against 78 before; 21 corpus imports and o12's faulted (known issues, below) |
| `import_file` with `component` of SolidSeas' own STEP of o12 (two solids), o08 (one part placed twice) and o15 (two parts), and of `o02_boxA.step`, each in an instance of its own: the component at the origin, the measures against `ground_truth.json`, closing the assembly closing what 3D Interconnect made, the source folder unchanged, and, with no other SOLIDWORKS running, no auto-recover copy | verified on 2026-10-14 with SolidSeas' instance alone (`SOLIDSEAS_SWAPI_SOLIDWORKS=1`): each import in 5 to 8 s, volume and area within 3e-16 and the centre of mass and box within 7e-18 m of the ground truth, no fault in Check3; SOLIDWORKS had placed each 6 to 33 mm off the origin; "Open Progress..." with each import, and mostly an untitled empty box too, both gone again when it answered (known issues, below) |
| SolidSeas' STEP read back with `component`: `solidseas.step`'s STEP of corpus parts of several bodies and of corpus assemblies, each imported into an instance of its own and measured against SOLIDWORKS' measures of the original, opened read-only in that instance just before | measured on 2026-10-14 with SolidSeas' instance alone, numbers only (`docs/FORMAT.md` 10.9): 25 parts of 2 to 17 solids and 12 assemblies of 1 to 74, every one imported at the origin with the original's count of shown solids; volume within 2.9e-9 of SOLIDWORKS' at the median, 4.5e-6 at the 90th percentile and 4.4e-5 at most for the parts, and 3.7e-6, 1.6e-4 and 3.5e-4 for the assemblies; the box of all bodies within 1.6e-7 m on every one; 3 to 17 s for an import, under 50 s for an item |
| SOLIDWORKS started on a desktop of its own | does not work while another SOLIDWORKS runs (above) |
| Live mode in SolidSeas' own hidden SOLIDWORKS, attached to by a second bridge as the assistant attaches to a person's: the session list (the batch mark), a new part's snapshot, the safety copy (the part's path and saved state unchanged), the undo entry recorded, bosses on each reference plane and on a face landing where the snapshot's frames say to a micrometre, a cut through all, a fillet, a chamfer, suppress and unsuppress, a dimension, a custom property, the queries, deleting only what the bridge made, and an undo entry an ended bridge left open closed by the next | verified on 2026-10-11 with the person's SOLIDWORKS open beside it, never touched (`tests/test_swapi_live.py`, `SOLIDSEAS_SWAPI_SOLIDWORKS=1`) |
| Steps that use an earlier step's geometry deleted newest first: a boss, a fillet on its edges, a cut sketched on its face and a chamfer on the cut's rim, each delete giving back the state before it exactly (features by reference, dimensions, faces and edges by reference, bodies, volume, extents) | verified on 2026-10-11, the same way |
| A fillet built from a definition naming its edges (`CreateDefinition`, `CreateFeature`), and `IMassProperty2.SelectedItems` set on a part, the edges and bodies as objects or as dispatch pointers | no fillet was made, and setting the bodies faulted inside SOLIDWORKS (`RPC_E_SERVERFAULT`); a fillet selects its edges instead, and a part's volume is measured body by body |
| An Automatic run (`solidseas_app.assistant.run`) in SolidSeas' own SOLIDWORKS: a fillet, a boss sketched on a face, a dimension and a property, each in its own undo entry (but the property) with the part locked, each checked, then reverted to the state before the run exactly; a fillet SOLIDWORKS cannot make leaves the part as it was | verified on 2026-10-11 (`tests/test_swapi_live.py`) |
| A step can give an entity a new persist reference while the old one still resolves to it: the top face of a block after a fillet on its edges. `live_current_refs` maps a plan's references before each step | measured on 2026-10-11 |

### Known issues

Found by the overnight run of 2026-10-05: the opt-in tests above, and
SolidSeas' STEP of the fixtures and 175 corpus parts imported and measured in
SolidSeas' own SOLIDWORKS. None of them touched the user's session.

- **`import_file` with `insert` of a STEP holding several bodies faults.** A
  STEP of two or more solids, or of several sheets, makes SOLIDWORKS fail the
  insert with `RPC_E_SERVERFAULT` (`0x80010105`), and the request fails with
  it: o12's two solids, and 21 of the 162 corpus parts written. The run ended
  that SOLIDWORKS after each and started a new one. Since 2026-10-14 the
  insert of a STEP that may hold several bodies is refused
  (`several_bodies_insert`) while the account's options make several bodies
  parts, and `component` imports it (measured, above).
- **SOLIDWORKS' own "Open Progress..." window is reported as a dialog.** It
  appeared during the STEP imports, and the window watch counts it, so an
  import that went through with no error still says `dialog_appeared` true and
  lists it in `dialogs`.
- **Closing a part after the assembly that used it raises
  `RPC_E_DISCONNECTED`** (`0x80010108`): `close_document` of a part opened
  before an assembly that uses it, called after that assembly was closed,
  fails with it.
- **An import that brings in nothing returns ok.** The reply's `result_kind`
  is then `empty`, with no error; check it rather than the reply's success (2
  corpus parts in the round trip).
- **`mass_properties` has no per-call accuracy setting.** It measures at the
  accuracy SOLIDWORKS' own options give, so the small differences against
  SolidSeas' STEP that `docs/OCCT.md` section 6.4 puts down to SOLIDWORKS'
  default accuracy cannot yet be measured again at its highest.

Side effects to know about:

- Starting the instance takes the foreground for 6 to 7 s (above), so long
  jobs run off-hours, and an off-hours job ends its instance when the window
  closes. While another SOLIDWORKS runs, the instance opens the journal file
  message box, which the bridge hides. While it runs alone, a SOLIDWORKS
  started then would be the one without the journal file and show that box
  itself (above).
- SOLIDWORKS writes to the registry the user's session shares, though the
  bridge sets nothing there (measured by comparing hashes of every value under
  `HKCU\Software\SolidWorks`; no value was stored). Starting the instance writes
  about 75 values under `User Interface\Custom API Toolbars` (the add-ins'
  toolbars) and changes `General\Last Splash Id`. `ExitApp`, SOLIDWORKS' own
  shutdown, then wrote the instance's layout under `User Interface`: about 40
  values added, 115 removed (those toolbar values among them) and 75 changed,
  in the CommandManager part and assembly context tabs and a few toolbar
  positions, which a SOLIDWORKS started afterwards would read. The bridge
  therefore no longer calls it: an instance ended through its job writes
  nothing there, so only what the start wrote remains, the same toolbar values
  every start writes. The user's own SOLIDWORKS writes its layout when it
  exits, as it always has.
- SOLIDWORKS adds every document it opens to the account's recent documents
  list, which the user's own session shares.
- Parasolid and STEP files written by SOLIDWORKS carry the Windows user name
  and a machine identifier in their headers (`USER=` and `MC_ID=` in a Parasolid
  file). SolidSeas' own Parasolid extraction writes `unknown` in those fields.
- Ending an instance through its job, as the bridge always does now, skips
  SOLIDWORKS' own shutdown. What that leaves:
  - Documents it opened: no `~$` lock file, because they are opened read-only
    only (SOLIDWORKS makes one for a document opened for writing, which the
    bridge refuses; measured), and the files are not changed. The bridge closes
    them before it ends the instance.
  - The folder of an assembly it opened: SOLIDWORKS writes there briefly,
    although the assembly is opened read-only. The measuring harness opened
    fixture o08's copy with the flags `open_document` uses for every assembly
    (`ReadOnly | Silent | OverrideDefaultLoadLightweight`), twice, on
    2026-10-04: the modification time of the folder holding it changed while
    the folder's entries were the same before and after, so SOLIDWORKS created
    something there and removed it again. Opening parts (copies of o02, o11
    and o12) and importing STEP files left their folders untouched. For an
    assembly opened in place, as batch conversion opens the ones it converts,
    that is a transient write in the user's folder; what SOLIDWORKS wrote,
    whether it does the same without `OverrideDefaultLoadLightweight`, and
    whether an instance ended while one is open leaves it behind, have not
    been measured. The opt-in `mass_properties` test prints that folder's
    modification time after the parts are opened, after the assembly is, and
    after the instance ended.
  - Documents it created: never saved, so they have no file; closed, unsaved,
    before the instance ends.
  - Auto-recover copies: SOLIDWORKS saves them for open documents with unsaved
    changes, at the interval its options set, and not at all in an instance
    that showed the journal message ("Auto recover will not work"). The
    bridge's documents are closed before `exit_solidworks`, `shutdown` or the
    bridge's exit ends the instance, so none is open then. An instance the
    client ends after a timeout may still have had one open: if SOLIDWORKS
    saved a copy of it, the next SOLIDWORKS start, the user's own included,
    may offer it under Document Recovery. The bridge's documents are opened
    read-only or made new, and two kinds of them are marked changed while
    open: one `import_file` made, and one of which `mass_properties` showed
    another configuration, which may stay so after the active one is shown
    again (not measured; the reply's `dirty` says). The opt-in check of the
    instance alone ends one by a timeout with a part open and fails if a copy
    or a backup appears, and the opt-in import and `mass_properties` tests
    compare the auto-recover and backup folders before and after. Whether
    SOLIDWORKS removes such a copy when a document is closed has not been
    measured.
  - A document a person opened in the instance in the seconds before it could
    be hidden is not saved and goes with it; `documents_open` counts it, and
    the bridge says so on standard error. Opened for writing, as SOLIDWORKS
    opens a document by default, it also leaves its `~$` lock file next to
    that person's file. The bridge does not close it, because it closes only
    the documents it opened or created.
  - SOLIDWORKS' embedded browser helpers (`swCefSubProc.exe`) are ended with
    the instance. Those of the user's SOLIDWORKS are its own processes and
    keep running, but both use the same cache folder under the account's
    Temp folder, and what skipping their clean shutdown does to that cache has
    not been measured.
  - Whatever SOLIDWORKS cleans up when it exits normally, such as its journal
    file when this instance made one (when it ran alone, as off-hours) and its
    temporary files, stays as it does after a crash. Two opt-in SOLIDWORKS
    checks start an instance again after one ended this way and fail if it
    shows a dialog the first did not: one while another SOLIDWORKS runs, and
    one with SolidSeas' instance alone, which also prints what changed in the
    journal, auto-recover and backup folders. Document Recovery is a task pane
    in the main window, not a dialog, so no window check sees it; the check of
    the instance alone stands in for it by failing when an auto-recover copy
    or a backup appears, since Document Recovery offers the copies in the
    auto-recover folder.
  - An export cut short by a timeout can leave part of its output file; its
    row says `timeout`, and a later run keeps that file as existing unless
    `--force` replaces it.

## Reading files without SOLIDWORKS: the Document Manager API

Dassault Systemes ships the SOLIDWORKS Document Manager API for reading
documents without running SOLIDWORKS. On a machine with SOLIDWORKS it is
registered as the COM class `SwDocumentMgr.SwDMClassFactory`, and the interop
assembly is `SolidWorks.Interop.swdocumentmgr.dll` in `api\redist`. It reads
custom and configuration properties, configurations, external references and
the saved preview bitmap, and is the vendor-supported way to do so.

Using it needs a Document Manager licence key, which subscription customers
request free of charge from the SOLIDWORKS Customer Portal. The key is tied to
the requesting organisation: keep it out of this repository and out of logs,
and pass it at run time.

SolidSeas does not use the Document Manager. It is Windows-only and needs the
key, while `solidseas.formats.solidworks` must run on Linux without either.
Where both are available, the Document Manager is a useful independent check
of what SolidSeas reads (properties, configurations, references). Run such a
comparison locally, with your own key, and never on files you may not process.

## What the extracted Parasolid can and cannot be converted with

`solidseas parasolid` (and `Document.parasolid()`) writes each body of a
configuration as a standalone Parasolid part transmit, `.x_b` binary or `.x_t`
text, copied from the partition SOLIDWORKS stores in the file.

What is known:

- On the box fixtures the extracted body is B-rep identical to the `.x_b`
  that SOLIDWORKS itself exports: same topology, the same geometry to the bit,
  the same embedded schema. Reading SOLIDWORKS' own `.x_t` and writing it
  back out with SolidSeas reproduces it record for record.
- On the development corpus, every extracted body passes structural checks
  (parses to the terminator, no dangling pointers, consistent topology), and
  an independent open-source XT-to-STEP mapper accepted 199 of 200 sampled
  bodies.

What can read it:

- Parasolid-based CAD systems (SOLIDWORKS itself, Siemens NX and Solid Edge,
  Onshape, and others built on the Parasolid kernel) import `.x_t` and `.x_b`.
  Whether they accept SolidSeas' files has not been tested yet: no Parasolid
  kernel has been run on them.
- `python -m solidseas.swapi convert --format x_t` gives a file written by
  SOLIDWORKS itself, if a kernel-verified file is needed.
- BlinkingSun/sldprt2step (Apache-2.0, pure Python) contains an XT-to-STEP
  AP214 mapper that converts analytic geometry exactly and approximates blends,
  intersection curves and SP-curves with B-splines. It reproduced SOLIDWORKS'
  STEP export of the box exactly. SolidSeas does not ship it yet.

What cannot:

- OpenCASCADE, and everything built on it (CadQuery, FreeCAD, `occt-import-js`),
  has no Parasolid reader. Use STEP from SOLIDWORKS (`--format step`) or from an
  XT-to-STEP converter instead.
- The `deltas` transmit stored next to each partition (`.d_b` with
  `solidseas parasolid --raw`) uses node layouts that are not in the public XT
  Format Reference, so nothing outside a Parasolid kernel can interpret it.
- Some legacy files store a few bodies with a schema that has no embedded
  definitions (one in the development corpus); those need the non-public
  schema files and are reported as problems.

For meshes, `Document.mesh()` returns the display tessellation SOLIDWORKS
cached at the last save. It is per face, usually not watertight, and not an
exact B-rep; for 3D printing prefer STL or 3MF exported by SOLIDWORKS.
