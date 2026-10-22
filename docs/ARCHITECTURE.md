# Architecture

SolidSeas is one Python codebase that ships as two things:

1. **The `solidseas` library.** Other systems (ERP, invoicing, project
   tracking, the online store) import it, or call its CLI or REST service, to
   preview and read metadata from SOLIDWORKS parts and assemblies. It needs no
   SOLIDWORKS installation and runs on Linux and Windows.
2. **SolidSeas Desktop.** A Windows application, built with Qt (PySide6), that
   manages a folder of CAD files: project structure, previews, properties,
   BOMs, version history, conversion, a 3D print button, and a modeling
   assistant that works alongside a locally installed SOLIDWORKS.

Everything the desktop app does is built on the library, so an integrating
system can take as much or as little as it needs.

## Decisions

| Decision | Choice | Date |
|---|---|---|
| Licence | Apache-2.0 | 2026-09-30 |
| Language and UI | Python, Qt via PySide6 | 2026-09-30 |
| Modeling assistant | Review mode (AI drafts code, user edits or approves it) and Automatic mode (AI plans a goal once from a closed set of checked operations and carries it out on one part) | 2026-09-30 |
| AI connector | Optional provider seam following the `ai-provider-seam` pattern; only the assistant needs it | 2026-09-30 |
| SOLIDWORKS bridge | A separate C# process, never loaded into the Python process | 2026-09-30 |
| Version tracking | git history inside git repositories, SolidSeas snapshots everywhere else | 2026-09-30 |
| Format work | Black-box analysis, published API, open-source prior art; no decompiling | 2026-09-30 |
| Drawings | Made by SolidSeas from the part's B-rep in pure Python (`solidseas.drawing`): its own drawing file, a PDF and a DXF first, a SOLIDWORKS drawing later through the bridge (`docs/DRAWINGS.md`) | 2026-10-04 |
| Open CASCADE | An opt-in test oracle, and the OCCT backend extension for IGES and BREP (`docs/EXTENSIONS.md` section 9), always in child processes; never in the core library, the viewer executable or the default install (`docs/OCCT.md`) | 2026-10-04 |

## Layers

### 1. Format readers: `solidseas.formats`

Pure Python, standard library plus `olefile`. No SOLIDWORKS, no Windows
dependency.

- `solidseas.formats.solidworks` reads `.sldprt`, `.sldasm` and `.slddrw`.
  Two containers exist: the legacy OLE compound file used before SOLIDWORKS
  2015, and the custom container used since. Readers expose the streams;
  decoders on top of them extract the preview image, the embedded Parasolid
  B-rep, custom and configuration properties, configurations, material, the
  saving version, and an assembly's component references.
- The byte-level specification lives in `docs/FORMAT.md`. Every claim in it is
  marked verified, hypothesis or unknown.

Public entry point:

```python
from solidseas.formats.solidworks import open_document

doc = open_document("part.sldprt")
doc.doc_type, doc.saved_version, doc.configurations, doc.properties
doc.preview()       # PNG or BMP bytes plus dimensions
doc.parasolid()     # embedded Parasolid transmit data, per configuration
doc.tessellate()    # triangles of a part's Parasolid bodies
doc.components()    # an assembly configuration's component tree
doc.references()    # component files, for assemblies (the 0.1 list)
doc.path_report()   # every path and user name the file would reveal
```

`solidseas.geometry` sits on top of the readers and reference resolution: it
places an assembly configuration's part instances in the top frame and takes
each component file's mesh from the assembly itself (`FaceTessellations`, or
an older assembly's own display lists, `formats/solidworks/facetess.py`), from
a document stored inside it, from the file that resolution finds, or from the
same meshes a sub-assembly keeps in its own document. A sub-assembly whose
components the top assembly's tree does not list is expanded from its own
document, read once a configuration, whose files are resolved in turn against
one index of the roots for the whole call. A part for which no display mesh is
stored anywhere is drawn from its own bodies by the last mesh source, `brep`,
which `solidseas.tessellate` serves; the geometry module imports it only when
that source runs.

`solidseas.tessellate` turns Parasolid bodies into triangles, in pure Python
with no numpy, like the rest of the library. `topology.py` is a read-only view
of a parsed transmit (fields by name, checked pointers, bounded walks);
`nurbs.py`, `curves.py` and `surfaces.py` evaluate and invert the geometry;
`edges.py` samples each edge once for both of its faces; `domain.py` turns a
face's loops into (u, v) polygons, across seams and poles; `triangulate.py` is
the 2D triangulator (an earcut port, a constrained Delaunay fallback and the
triangle mesh refinement works on), with no 3D in it; `_engine.py` runs the
faces and `__init__.py` holds the public calls. `blend.py` approximates a
rolling blend, which has no closed form, by a rational B-spline whose deviation
it measures, and `fit.py` holds the curve fitting and the feet on surfaces it
rests on; both are shared with `solidseas.step`, which writes the same surface,
so the tessellator draws a blend exactly as the export writes it. Every loop in
it is bounded and checks one clock, and a face that cannot be done fails alone.

`solidseas.export` writes what a slicer reads, binary STL and 3MF, from the
same triangles: a part's solid bodies tessellated at a print chord (a quarter
of the 3D view's, at most 0.01 mm), an assembly from `solidseas.geometry` with
the `brep` source first and the welded triangles kept, a stored display mesh
only as a labelled fallback. A 3MF holds one object per component file and a
build item with its transform per instance, or one merged object. Every
object is checked closed and oriented (each edge used twice, once each way, in
time n log(degree)). Slicers read coordinates as float32, so a triangle's
corners that float32 cannot tell apart are merged, an edge collapse that
keeps a solid closed, and a 3MF's numbers read back as the same float64. A
file is only ever created new, never through a link, a device or a stream,
with every write bounded. The 3MF package and its XML are written with
`zipfile` alone, no library of their own.

`solidseas.step` writes a part's Parasolid bodies as STEP AP214, the exact
B-rep, from the same `topology.py` view and evaluators the tessellator uses.
`mapper.py` maps each body's topology and geometry to the entities of
`entities.py` (adapted from sldprt2step's mapper), `bspline.py` clamps and
restricts B-splines by knot insertion, `iso.py` writes SP-curves that run
along an iso-line exactly, and `approx.py` and `blend.py` fit what STEP cannot
hold exactly (intersection curves, SP-curves, rolling blends; the fitting
itself and the blend's construction are the tessellator's `fit.py` and
`blend.py`), each fit measured against the true geometry and refused above its
limit. `checks.py` checks every body before anything is written, `split.py`
then cuts each face that goes all the way round a closed surface in two at its
seams, as SOLIDWORKS does, and checks each cut again (and that its halves tile
the face), and `part21.py` and `product.py` write the file and the product
structure SOLIDWORKS writes. Bodies SOLIDWORKS hides
(`formats/solidworks/parasolid.py`, `body_hidden`) are left out. A
body that cannot be written without loss refuses the export, or is left out
whole when asked; a face is never dropped from a solid.

The path report (`formats/solidworks/pathreport.py`) reads the structured
carriers first and then the byte scan of `paths.py` as a fallback, for the
document and each nested document in it. It only reads: SolidSeas never
rewrites a file to remove what the report lists.

**Every other 3D format** goes through one registry and one document interface
beside the SOLIDWORKS reader, which they leave as it is (`docs/API.md` 3.20,
`docs/formats/`):

- `formats/registry.py` lists every format SolidSeas knows (its extensions,
  family, capabilities, Home axis and the dotted path of its reader, or none
  for a format that is only listed) and tells a file's format from its first
  4 KiB, size and name, with every content test in one place so detection
  never imports a reader. A reader joins by its module appearing.
- `formats/base.py` holds `ModelDocument` (the read-only view of one file:
  head attributes read cheaply, then `tree`, `scene`, `bodies`, `preview` and
  `references`), the neutral types (`Scene` of `MeshObject`s in metres and
  `SceneItem`s that place them, `ModelTree`, `BodyRef`, `ExternalReference`),
  the `MeshBuilder` every reader makes its meshes with, and `open_model` and
  `open_any`. `formats/limits.py` holds every bound in one `Limits` object,
  and `formats/_source.py` the bounded building blocks readers share: a
  source of bytes, a clock, a zip reader that refuses bombs, expat XML without
  DTDs, strict JSON, files beside a document read only from its own folder,
  and PNG and bitmap checks that turn a stored image into a PNG SolidSeas
  wrote.
- `formats/stl.py` is the reference reader. The mesh formats, Parasolid
  transmit files, STEP and Alibre Design come as modules of their own; the
  B-rep formats will build Parasolid transmits in memory, so the tessellator
  above draws them and the existing writers save them.
- A `Scene` is the one hand-off: `solidseas.export` turns it into a print
  model, `solidseas.render` into a thumbnail (a z-buffer and flat shading in
  pure Python, cached in `thumbnails.sqlite`), and the viewer into its 3D
  view's buffers.

### 1a. Native writer research: `solidseas.nativewrite`

Pure Python, like the readers, and separate from them: the readers never
write. It lays out 2015+ containers, edits feature parameters in place,
holds `ParametricDocumentIR` and its source adapters (SolidCraft designs, and
CadQuery models through a recording of how they were built: `cqrecorder` in a
CadQuery session, `cqrecording` anywhere), and writes an IR part through a seed. It imports nothing from `solidseas.swapi`; SOLIDWORKS
only checks its output, through the bridge's `native_check` on the PC.
`docs/NATIVE_SLDPRT_WRITER.md` is its design and status.

### 2. Catalog: `solidseas.catalog`

Scans a folder, identifies every CAD file by content hash, and keeps an index
(SQLite) of documents, previews, properties and references. Both the desktop
app and integrations query the index instead of re-reading files. The index
lives in the user's cache folder by default (`%LOCALAPPDATA%\SolidSeas\catalogs`
on Windows, the XDG cache folder elsewhere), one per project folder; a
`.solidseas` folder beside the project is used only when the caller asks for
it by name, and never on a network location: on Windows a UNC path or a mapped
drive, on Linux and macOS a network file system's mount, told from the
kernel's mount table without asking the share anything (`solidseas.netfs`).
Where that table cannot be read, the library cannot refuse one and the command
line asks for `--db` instead of `--in-project`.

Built, provisionally (`docs/API.md` 3.18). One process at a time writes a
catalog (an OS lock beside the database) and it never parses a CAD file:
documents are read by the `catalog_document` job and hashed by `content_hash`
in a `solidseas.workers.WorkerPool`, folders are walked by `solidseas.walk`,
and every worker answer is checked field by field before it is stored. It
indexes SOLIDWORKS documents unless its `formats` setting names more: every
other format `solidseas.formats` reads is indexed from the file's head, as the
folder listing reads it (format, type, units, counts, stored preview,
properties). Of their references it follows an Alibre Design assembly's
components, resolved from rows by the GUID each Alibre file's record holds, as
the live resolver finds them; no other format's yet. A scan
walks and compares (an unchanged size and modification time means unchanged;
a vanished row is matched to a new path by file id, so moves are not read
again), reads what is new or changed, resolves references from the catalog's
rows with `solidseas.resolve` itself (a folder index and identities built from
rows, nothing outside the roots), and hashes. Which documents must be
resolved again is recorded with the change that asks for it, so a scan that
stops early loses nothing. Readers open the database read-only and never
block the writer. Where-used follows resolved references and the stored model
graph (quantities per configuration, through each sub-assembly's own
document, or the tree above it where that document cannot answer), with every
walk up bounded; search is FTS5 with a `LIKE` fallback. The CLI's
`index`, `where-used`, `search`, `duplicates`, `missing`, `changes` and
`catalog` commands, `serve --catalog` and the viewer's Where Used tab (fed by
an indexer process of its own) all query it.

### 3. BOM: `solidseas.bom`

Builds bills of materials from assembly references and component properties.
Produces flat and indented BOMs with quantities, and reports unresolved or
ambiguous references (two files with the same name are common in practice).
Output as JSON and CSV for ERP and invoicing. Finding each referenced file is
`solidseas.resolve`'s job (section 9).

Built, provisionally (`docs/API.md` 3.16): `solidseas.bom` groups one
configuration of the component tree into top-level, parts-only or indented
rows as SOLIDWORKS' BOM tables do (`docs/FORMAT.md` 12.7), then reads each
row's file once, through one reference resolution of the assembly, for its
properties: a document stored inside the assembly or a sub-assembly from
there, any other from the file resolution found, opened read-only within its
root and closed at once (but a sub-assembly that stores a document a row
needs, which stays open until the BOM is built). The `bom` kind is built in
`solidseas.model`, so
Python, the CLI's `bom` command and `/v1/bom` give the same data; the service
runs it as C10 has it, the resolution in its own process between two worker
jobs.

### 4. Versions: `solidseas.versions`

- Inside a git repository, history comes from git. SolidSeas recommends Git
  LFS for CAD files, because binary CAD files do not delta-compress and bloat
  ordinary repositories.
- Anywhere else, including cloud-synced folders, SolidSeas keeps its own
  content-addressed snapshots: in the user's data folder by default, and in the
  project's `.solidseas/history` only when the caller names the project, as the
  safety rules in `AGENTS.md` require of anything written beside a source.
- Either way a version carries its preview, properties and a geometry
  fingerprint, so the timeline can show what changed between two versions.

Built, provisionally (`docs/VERSIONS.md`, `docs/API.md` 3.26): the library and the
`history`, `snapshot` and `diff` commands. Git is read in pure Python from the
repository's own files (`gitrepo`): no program runs, whatever the repository's
configuration names, and nothing is fetched; a version's history is what
`git log -- <path>` lists. The snapshot store (`snapstore`) is plain files, an
object per distinct content and a record per snapshot, none ever rewritten, so it
needs no lock. Two versions are compared on what they hold (`versiondiff`): the
document summary every surface builds, properties, configurations, and per
configuration a canonical fingerprint of the B-rep that a re-save does not change,
with volume, area and box measured where the fingerprints differ. The viewer's
timeline, previews in it and the Git LFS guidance come next.

### 5. Conversion: `solidseas.convert`

One job interface, several backends. Each backend declares what it can read
and write, and the engine picks the best available one.

| Backend | Needs | Reads | Writes |
|---|---|---|---|
| native | nothing | SLDPRT, SLDASM, and every format `solidseas.formats` reads (STEP, Parasolid, STL, 3MF, OBJ, PLY, OFF, glTF, AMF, ACIS SAB, Alibre Design) | Parasolid extracted from a SOLIDWORKS file; STL and 3MF from any of them, tessellated from B-rep bodies or taken from the file's own triangles (`solidseas.export`); STEP of a part from its Parasolid bodies, a SOLIDWORKS part's or a Parasolid transmit file's (`solidseas.step`) |
| occt | the OCCT backend extension (Open CASCADE, in a helper program of its own) | IGES, OCCT's BREP, STEP | IGES, BREP, STEP |
| cadquery | CadQuery (OpenCASCADE) | STEP, CadQuery scripts; built so far: a CadQuery model's recording, which the native backend writes as an SLDPRT with no CadQuery present (`solidseas.nativewrite.cqrecording`) | STEP, STL, 3MF, glTF |
| solidworks | local SOLIDWORKS, Windows | SLDPRT, SLDASM, Parasolid, STEP | SLDPRT, SLDASM, Parasolid, STEP, STL, 3MF |

Two honest limits shape this table. OpenCASCADE cannot read or write
Parasolid, and no open implementation writes native SOLIDWORKS files. So
Parasolid to SLDPRT, and anything that must produce an editable SOLIDWORKS
document, goes through the `solidworks` backend.

**The conversion matrix (planned work).** Sources down, targets across. *Now*
is built; *CV-n* is a staged follow-up (below); *Never* is not possible without
the vendor's program, or has nothing to convert from.

| Source | STL, 3MF | OBJ, PLY, GLB | STEP (B-rep) | STEP (faceted or AP242 tessellated) | Parasolid `.x_t`, `.x_b` | Native (SLDPRT, AD_PRT) |
|---|---|---|---|---|---|---|
| Mesh formats (STL, 3MF, OBJ, PLY, OFF, glTF, AMF) | Now | CV-2 | Never (no surfaces to recover) | CV-6 | CV-6 (a body of planar faces; research) | Never |
| SOLIDWORKS part or assembly | Now | CV-2 | Now (parts), CV-5 (assemblies) | CV-6 | Now (`parasolid` command; an assembly as one transmit, `solidseas.parasolid`) | SOLIDWORKS backend |
| Parasolid file | Now | CV-2 | Now (parts), CV-5 (assemblies) | CV-6 | CV-3 (text to binary and back) | SOLIDWORKS backend |
| STEP | Now | CV-2 | CV-4 (through Parasolid) | CV-6 | CV-3 | SOLIDWORKS backend |
| Alibre part | Now (B-rep body, else the display mesh) | CV-2 | CV-4 (SAB to Parasolid to STEP) | CV-6 | CV-3 | Never |
| Alibre assembly | Now (found parts placed; 3MF keeps the items) | CV-2 | CV-5 | CV-6 | CV-3 per part | Never |
| Standalone ACIS SAB | Now | CV-2 | CV-4 | CV-6 | CV-3 | Never |

One command does every conversion, `solidseas export FILE --format F -o OUT`
with the CLI's write guards; the matrix becomes data
(`solidseas.convert.CONVERSIONS`) that `export` and the viewer's Convert dialog
both read. The stages, each a bead to file:

- **CV-1** (built): every readable format to STL and 3MF, through `export`, 3D
  Print and the viewer's Export for 3D Printing.
- **CV-2**: mesh writers for OBJ (with MTL colours), binary PLY and GLB (nodes,
  materials, Z up turned to Y up); `CONVERSIONS`; `export --format obj`, `ply`
  and `glb`; the viewer's Convert dialog.
- **CV-3**: Parasolid from any B-rep, through the transmit writer the readers'
  builder already feeds (`write_text`, `write_binary`, a common header,
  `validate()` checked); `export --format x_t` and `x_b`.
- **CV-4**: STEP from the other B-rep formats (STEP, standalone ACIS SAB and
  Alibre Design parts), through Parasolid bodies: `solidseas.step`'s
  `step_transmit` fed by `bodies()`, with names, colours and units, as a
  SOLIDWORKS part's and a Parasolid file's parts already are.
- **CV-5**: STEP assemblies (products, occurrences, placements) from
  SOLIDWORKS, Parasolid, STEP and Alibre assemblies (needs CV-4).
- **CV-6**: meshes to STEP, as AP242 tessellated geometry or a `FACETED_BREP`
  for AP214 readers.
- **CV-7**: colours and names kept across conversions (3MF materials, STEP
  styles, glTF materials).
- **CV-8**: the engine's other backends (bead SolidSeas-e2z): CadQuery (STEP
  and IGES through OpenCASCADE, an optional extra) and SOLIDWORKS (native
  outputs, in its own SOLIDWORKS process, on the bridge of section 6, whose
  `solidseas.swapi.batch` already converts SOLIDWORKS documents to STEP,
  Parasolid, STL and 3MF outside the engine).

Reading more formats is planned the same way: an IGES reader through the
readers' B-rep builder (trimmed NURBS surfaces, curves on surfaces, manifold
solids, subfigure assemblies, colours), ACIS SAT text and other ACIS versions,
Alibre drawings and packages, and black-box studies of Solid Edge, NX,
Inventor, Fusion and 3D XML files once samples are provided. For IGES the Open
CASCADE evaluation (`docs/OCCT.md`) proposed an optional backend under CV-8,
OCP only and offered only when it is installed. It is built as the `occt`
backend (`solidseas.convert`, `docs/EXTENSIONS.md` section 9): Open CASCADE runs
in the OCCT extension's helper program, IGES and BREP files are converted there
to STEP and read by SolidSeas' own STEP reader, and `solidseas convert` writes
IGES, BREP and STEP through it. The library's own readers stay pure Python.

### 6. SOLIDWORKS automation: `solidseas.swapi`

Drives a local SOLIDWORKS through its documented API. The SOLIDWORKS logic is a
small C# program, `SolidSeas.SwBridge.exe` (sources in `solidseas/swapi/SwBridge`),
compiled from source against the official interop assemblies that ship with
SOLIDWORKS, because typed calls with by-reference error codes are reliable from
C# and fragile through late-bound COM. It is built with the C# compiler of the
.NET Framework that ships with Windows (`scripts/build-bridge.ps1`), loads the
interop assemblies from the SOLIDWORKS installation at run time, and is never
committed or bundled with them.

Python reaches the bridge as a separate process, never in-process. The bridge's
main thread is a single-threaded apartment that owns every SOLIDWORKS object,
registers a COM message filter so calls SOLIDWORKS rejects while busy are
retried until the request's deadline, and pumps messages whenever it waits.
Document notifications arrive on a COM worker thread whatever the apartment
thread is doing, and SOLIDWORKS waits for each handler (measured in the spike in
`docs/ASSISTANT.md`), so a handler only queues the event and returns, never
waiting for the pipe: a writer thread drains a bounded queue to standard
output, and when nobody reads, further events are dropped and counted rather
than holding SOLIDWORKS. A background thread reads standard input, one JSON
request per line with an id and a timeout; the apartment thread answers one
JSON reply per line on standard output, and events (document notifications)
are lines without an id. It accepts only its own named operations with checked
arguments, never code. The client calls its event listeners on a thread of
their own, so a slow listener holds neither the replies nor SOLIDWORKS.

`solidseas.swapi.bridge.Bridge` starts the bridge inside a Job Object with
kill-on-close before sending it anything, and gives every request a timeout.
When a timeout runs out it terminates the job, which ends the bridge and
everything it started, and raises; the caller starts a new bridge to go on.
A call stuck inside SOLIDWORKS therefore cannot hang SolidSeas or keep it from
exiting, and if SolidSeas itself dies the job ends with it.

Two modes, kept strictly apart:

- **Batch mode** (conversion now; thumbnails and validation later) starts its
  own `SLDWORKS.exe`: suspended, placed in a second Job Object of the bridge's
  with kill-on-close, then resumed, without inherited handles. It
  attaches only through the Running Object Table moniker
  `SolidWorks_PID_<pid>` of that process, hides the instance and takes it out of
  the user's hands (`Visible` and `UserControl` false), and runs one such
  instance per Windows session at a time (a named mutex). Until it registers it
  cannot be hidden, and for those 6 to 7 seconds it takes the foreground on the
  user's desktop; a desktop of its own does not work while the user's
  SOLIDWORKS runs (the swapi README has the measurements). So batch work that
  SolidSeas starts by itself, rather than the user, runs SOLIDWORKS only
  off-hours, 02:00 to 07:00 local time by default (`OffHours`): it starts it
  only inside that window and, once the window closes, ends it through its job
  before the next document or export and goes on in the next window. Alone on
  the machine, as off-hours, the instance holds the journal file, so a
  SOLIDWORKS the user started while it ran would be the second session, without
  auto-recover. Work the user starts runs at once and to its end. While another
  SOLIDWORKS runs, the instance also shows a journal file message box that
  hiding the instance leaves on the screen. A watch thread in the bridge hides
  that one box with `ShowWindow(SW_HIDE)` and sends it no message of its own,
  never clicking or closing it (if the box was the foreground window, Windows
  then activates another, normally the one the user was in): a visible dialog
  whose process is the one the bridge started and holds in its job, titled
  SOLIDWORKS, holding only static texts and buttons and the stable words of the
  journal message. It leaves every other window alone, and reads nothing of
  another process's windows past their process id. The bridge never touches
  the user's interactive session, sets no SOLIDWORKS option (they are shared
  with the user's session through the registry), opens documents read-only,
  writes copies in export formats only to output folders, never over the file
  of an open document under any name, and ends its instance by terminating its
  Job Object once the documents it opened or created are closed. It never calls
  `ExitApp`, SOLIDWORKS' own shutdown, which rewrites about 230 values of the
  layout in the registry the user's session shares; the README lists what
  ending it directly leaves behind. `solidseas.swapi.batch` converts to STEP,
  Parasolid, STL and 3MF on it, and starts a fresh bridge and SOLIDWORKS after
  a timeout. The bridge also measures the documents it opened or made
  (`mass_properties`: bodies, topology, volume, area, centre of mass, precise
  boxes and `Check3` faults, in SI units, per configuration) and imports STEP,
  IGES and Parasolid files into new documents (`import_file`), into a part made
  from a template the request names or as File Open does. It reads the
  account's import options, never sets them, and refuses up front the imports
  they would turn into a template dialog; a dialog it cannot foresee ends the
  instance at the request's timeout, and the client's error names it.
- **Live mode** exists only for the modeling assistant (`Live.cs`). It
  attaches only after the user opens the assistant and picks a session from a
  list of their running SOLIDWORKS processes, bound through the same moniker,
  then picks a document. It reads the part's snapshot, writes the safety copy,
  opens and closes the script's undo entry, answers a script's queries, and
  carries out the vocabulary's operations on the active part (shell and the
  patterns are not built yet). In Review mode every change is shown before it
  runs. In Automatic mode every step is checkpointed, verified and
  revertible (`solidseas_app/assistant/run.py`). The same runs serve a chat in
  Claude Desktop or Claude Code through SolidSeas' MCP server (`--mcp`,
  `docs/MCP.md`). Live mode never ends the
  SOLIDWORKS process it attached to, so the user's SOLIDWORKS is never in the
  bridge's job. See `docs/ASSISTANT.md`.

The protocol, the operations and what has been measured are in
`src/solidseas/swapi/README.md`.

### 7. AI connector: `solidseas.ai`

Optional, installed with the `[ai]` extra. The format readers, catalog, BOM,
versions and integration surfaces never need it. The modeling assistant does.
When no provider is configured every AI control is hidden, so nothing is
offered that cannot work. When the machine policy forbids a configured
provider, or forbids Automatic mode, the affected controls stay visible,
disabled, with "Set by your administrator".

It follows the provider seam used across related projects (the
`ai-provider-seam` skill in a skills library):

- `solidseas/ai/base.py` defines the `ModelProvider` interface and imports no
  provider SDK. Task methods return `None` when a provider does not support a
  task, and callers treat that as a capability gap. The tasks are
  `draft_change` for Review mode, and `plan_steps` and, when the person asks
  for a look at the part after each step, `check_step` for Automatic mode.
- `solidseas/ai/prompts.py` owns every prompt, every reply parser and the
  Automatic mode vocabulary version.
- Providers: Anthropic, OpenAI, Gemini, Ollama for local use, and a `noop`
  provider. No provider SDK is used: each speaks HTTP through the standard
  library (`solidseas/ai/http.py`), and keys are passed explicitly.
- `solidseas/ai/factory.py` is the only place a provider is built, and one of
  the two places the machine policy is enforced.
- `solidseas/ai/context.py:build_model_summary` is the only function that puts
  document data into a prompt. No file paths, custom property values or author
  fields leave the machine; the names the user typed are replaced by handles
  unless the user opts in; the request text is redacted. The window shows
  exactly what the AI sees.
- Every reply goes through `parse_json_response`. Replies are untrusted: they
  are validated against a schema and allowlists, never choose a file path, URL
  or document id, and are shown only as plain text.
- Budgets are enforced: input is capped before the budget check and output is
  capped to what is left, which the call holds until it ends, so two windows
  cannot both spend it; a call that fails after the provider had it is still
  charged. Every call has a timeout. On 429 the client backs off; on 401 it
  stops.
- Keys live in Windows Credential Manager, travel only in headers, and never
  appear in logs, errors or the settings page. `truststore` makes provider
  calls work behind TLS-inspecting proxies on managed PCs.
- Tests use a scripted fake provider, and the suite blocks sockets.

The full rules are in `docs/ASSISTANT.md`.

### 8. Desktop app: `solidseas_app`

PySide6, Windows first.

An early preview exists: `solidseas_app.viewer`, a read-only folder viewer
built only on the public library, shipped as `SolidSeasViewer.exe` ([user guide](guide/viewer.md)).
Every file read runs off the UI thread, documents are opened `within` the
opened folder as the listing opens them (a component's file that reference
resolution found outside it is opened within its own folder, as the
resolution's identity reads open it, and a virtual component is read as a
nested document of its assembly), and its exports of a document's own data
(Parasolid, preview image, BOM) go through the CLI's write guards with the
opened folder counted as a source folder, so they land only outside it. The one
file the viewer writes inside the opened folder is the 3D Print file, by
design: a new file next to the model it was made from, never over, through or
in place of one that is there (the 3D Print button below). A component that
reference resolution found outside the opened folder, on a drive of this
computer (a library folder, say), gets its print file next to its own file
there, so 3D Print may also add that one file to such a folder; never to a
network share or drive outside the opened folder. The
listing, details and previews are read in worker threads. With Settings >
Interactive 3D View on, a part's saved display mesh, or an assembly's display
geometry (`solidseas.geometry`, with its component files found by reference
resolution in the opened folder), is read in a child process
(`viewer.meshproc`; on Windows it runs in a job object with a memory ceiling,
at below-normal priority, and ends with the viewer), which a worker thread
waits on, and is drawn with OpenGL on the UI thread (`viewer.view3d`): each
mesh is uploaded once and drawn for every instance that uses it, in one
instanced draw call where the context allows. The 3D read resolves an
assembly's references exactly as the details panel does, `allow_outside_roots`
on by design: a component file found at its stored path on a local drive
outside the opened folder (never a network path) is the file the Components
and References tabs show as found and the one Go to file opens, so its mesh is
read too, read-only and within its own folder. The user's setting Look for
Referenced Files Only in the Opened Folder (`references_inside_only`, off by
default) turns `allow_outside_roots` off for every read the viewer makes: the
details panel's references and BOM, the 3D read, 3D Print, both exports and the
drawing process (`drawing.assembly.searching(..., outside=False)`), each told
through its own request; turning it on drops Back's places outside the opened
folder and closes one shown. The child keeps the
tessellations of the parts it drew from their bodies while it runs
(`solidseas.tesscache`, keyed by what each part's file holds and bounded in
bytes), so a part is tessellated again only when its file changes or the child
is ended. It is bounded like every 3D
read: the triangle cap and its byte budget over what is read, and a drawn
budget (twenty times the cap) over every instance's triangles, so a frame never
asks the GPU for more than that. An instance the geometry places without a
mesh but with the box its assembly stores is drawn as that box: one unit cube,
one more instanced mesh of the scene whose matrices (made in the mesh process)
take it to each box, drawn after the meshes with translucent faces and dark
edges. A box no model could have is dropped in the mesh process, so it never
takes the camera. An assembly's exploded view is
the viewer's own (`viewer.explode`): offsets made from the placements alone,
worked out for the level, the sub-assemblies the user chose to explode or keep
together and the instances hidden, uploaded when one of those changes and
scaled in the vertex shader, so it changes no placement and nothing in the
file. A click picks an instance with a second
pass of the same shaders, each instance in a colour that is its number, into
an offscreen framebuffer of the few pixels round the pointer, so a pick finds
what is drawn in front, exploded or not, for one small draw; of a box, that
pass draws the far side, so a box in front of a component is picked and a
component inside one is picked through it. What the user hid or made
transparent (`viewer.appearance`, kept by component tree id and file key, and
with the explode switches kept for each document by `viewer.lookstore`, from
one run to the next in `ViewerLooks.json` beside `Viewer.ini`, under a digest
of the document's path) is a per-instance attribute: the opaque instances are drawn first, then the
transparent ones and the boxes, blended without writing depth, each one's far
side placed at the far end of its bounding box and its near side at the near
end, farthest first, so one inside another lies between that one's two sides
(with nothing transparent the boxes need no sort and are drawn instanced);
a hidden one is left out of every pass and the exploded view, and a transparent
one is picked as a box is, at the far side of its own box. The view cube over the
view's corner is a child widget painted with QPainter (`viewer.cubewidget`, its
geometry in `viewer.viewcube`), not a pass of the OpenGL frame: it shares no
OpenGL state with the passes, Qt routes its clicks away from picking, and the
frame the self-test reads holds the model alone. A turn drag turns about the
surface under the pointer, read by a depth variant of the id pass that writes
each fragment's window depth as 24 bits of colour, since OpenGL ES cannot read
a depth buffer back. The camera's lens shift lets a fit centre the model in the
part of the view the legend leaves free, or beside the view cube. With Settings >
Interactive 3D View off the viewer never reads a mesh or starts OpenGL.

Files of the other formats `solidseas.formats` reads (STEP, Parasolid, STL,
3MF, OBJ, PLY, OFF, glTF, AMF, ACIS, Alibre Design) are listed and shown beside
SOLIDWORKS documents, and none is ever parsed in the window's process (a
compound file wearing a SOLIDWORKS extension is the listing's SOLIDWORKS
document, read in the window's threads as every `.sldprt` is). The
listing scans with `formats="all"` and the window's own `WorkerPool` as its
foreign pool (`viewer.modelpool`: two spawned workers below normal priority,
2 GiB each, started on the first such file and closed with the window). The
details panel's sections come from two jobs of the viewer's own in that pool
(`viewer.modeljobs`): the `model_summary`, with the Components tab's rows and
the References tab's files made from the model's tree and references, and then
the geometry read once as the 3D view reads it, for the Overview's measures
and, when the file stores no image, the rendered preview. Thumbnails of files
that store none come from the library's `model_preview` job, the rows on
screen first, one at a time (`viewer.thumbnailer`), kept in `thumbnails.sqlite`
(`ThumbnailCache`), which only the window writes. `viewer.modelview` names each
node of a model's tree as an instance id (the names on its path joined by `/`,
siblings of one name numbered), the same in the worker that makes the rows and
in the mesh process that places the instances (`mesh3d.read_model_scene`), so
picking, looks and the exploded view work as for a SOLIDWORKS assembly; a
format whose models stand on Z is turned into the view's Y-up frame through its
placements. The mesh process and the 3D Print export's process answer in JSON
frames, read with a length limit, followed by raw buffers checked against the
header, for SOLIDWORKS documents too; nothing a child sends is unpickled. 3D
Print and File > Export for 3D Printing open a model file with `open_any` in the
export's process; with the Open 3MF and STL Files As They Are setting on (off by
default, AGENTS.md's safety rules), a 3MF or STL the program takes is handed
over as it is when it goes in the format it holds and its name says: a 3MF asked
for as STEP goes as 3MF (`printing.sent_format`), so it is handed over too, and
an STL saved as `.3mf` never is. `viewer.samples` writes a synthetic file of
every format for the self-test of formats (`viewer.selftest_formats`).

The list's quick filter (`viewer.quickfilter`) draws one button per document
type from a single table (`viewer.filetypes`, no Qt), which also decides each
listing entry's type from what the listing reports, so a format the listing
learns to report needs a row there and no other change; a test holds the table
to the format registry, every format a listing can report having rows named as
the registry names it. It is the list's only filter by type, and offers only the
types of rows a setting does not hide (`DocumentFilter.listed`: lock files and
files of formats SolidSeas cannot read). 3D Print and File > Export STEP send a
Parasolid transmit file's part through `solidseas.step` as they send a
SOLIDWORKS part, and say why any other model file cannot go as STEP
(`viewer.printing.step_unavailable`); the catalog holds the formats the list
shows (its `formats` setting, which the indexer sets), so the Where Used tab
asks it about a model file too, and says so when the index follows no reference
of that format yet.

The viewer is the app: the Phase 2 shell grows inside it rather than beside
it, on the catalog it already indexes.

- Folder view: projects as folders, assemblies with their components nested,
  thumbnails, and a details panel with properties, configurations, material,
  references and BOM.
- 3D viewer: the viewer's own OpenGL view (`viewer.view3d`), grown as the
  app needs it. It replaced the earlier plan of a three.js view inside Qt
  WebEngine. A browser view for `solidseas serve` would be a separate page,
  not part of the desktop app.
- Version timeline with previews and diffs.
- **3D Print button.** Exports the selection in the format chosen for the
  slicer, from those it takes, and opens it in that slicer. It remembers the
  choice, defaults to Bambu Studio when installed, and lets the user pick
  another program. The preview has it (`viewer.printing`, which imports no
  Qt, and
  `viewer.printaction`): the toolbar's 3D Print and File > 3D Print export
  the part or assembly the details show, in the configuration shown, through
  `solidseas.export`, as 3MF (every program's default) or STL, or through
  `solidseas.step` as STEP (Bambu Studio, OrcaSlicer, PrusaSlicer or another
  program, when chosen; not Cura, which needs a plug-in for it). An assembly,
  which the STEP export does not write yet, and a part it refuses
  (`printing.step_for_print`) go as 3MF, and the result says why; a STEP with
  bodies left out is never sent. The export runs
  in a child process of its own, as the 3D view's mesh reads do (on Windows in
  a job object: a memory limit and below-normal priority), waited on from the
  controller's own thread pool, so the details panel never waits behind it;
  the button, and the 3D Print entry of each right-click menu, turns into
  Cancel 3D Print meanwhile, and Cancel or closing the window ends that
  process at once. The right-click menus of the document list, the rows of
  the Components, BOM and References tabs and of a drawing's sheets and
  models, the 3D view and its legend give the controller a `PrintTarget` (the
  file reference resolution found for the row, in the row's configuration; a
  virtual component from inside the assembly that stores it, or from inside
  the sub-assembly that does, found there by its stored name; a part the 3D
  view read from a sub-assembly's own file, which no row stands for, from the
  document its mesh came from) and every print, button or menu, goes through
  `PrintController.start`; a component whose file was not found has its entry
  off, with the reason. The file is written next to the model it was made from
  (`printing.model_folder`), under a temporary name, then claimed by a rename
  that refuses a name taken, as the document's name (a virtual component's
  own), the configuration exported when it is not the active one, and the
  local date, one number past the highest of that day's prints of that name
  and extension there (`bracket 2026-10-03 (2).3mf`), so the highest number is
  the newest; an assembly whose folder holds a part of its name is marked
  `(assembly)` so the two never share a numbering, and a 3D file of another
  format whose folder holds a document of its name in another format is marked
  with its extension (`frame (STL) 2026-10-03.3mf`), from the folder's names
  alone. `printing.folder_problem`
  refuses, from the path's text and `lstat` alone, a model folder that is a
  link or junction or lies below one (every folder from the drive's root down
  is looked at), a cloud placeholder, a device or stream path, a network
  share or drive outside the opened folder, or outside Windows a file system
  the mount table names as one without hard links (`vfat`, `msdos`, `exfat`),
  since there the file is named by a link (`printing.rename_new`); a refusal,
  a failed write (read-only, permission denied, a link the file system
  refuses, said as such) or Settings > Save 3D Print Files Next to the
  Model turned off sends the file to a folder of the user's own under the
  system's temporary folder instead, and the status line says why. Exports
  older than a week are removed from that temporary folder only, never from a
  model's folder; the one file ever removed next to a model is the export's
  own unfinished one, when it fails, is cancelled, or was being written when
  the viewer ended (a record of it in the temporary folder lets the next print
  find it by its random name). Programs are found in their usual install
  folders and the registry's App Paths, only read; Settings > 3D Print
  Program lists them with Choose Another Program... (an `.exe`, never a
  batch file or script) and the formats the program takes (Preferences
  offers them too), and `Viewer.ini`'s `[Print]` section remembers the
  choice; a format the next program chosen does not take falls back to its
  first, and the status line says so. The program is started by one function,
  `printing.launch`, with the file as its one argument and no shell, and
  without what the packaged viewer set for itself (PyInstaller's variables,
  its Qt plugin paths and DLL folder); a session-wide test guard replaces it,
  and the self-test's `--print-dry-run` exports as the button does (next to
  the model in the folder under test, which is why it runs on a copy, and
  never next to a model outside it, which goes to the temporary folder),
  records the program and arguments without starting anything and checks the
  folder and the name of two prints in a row; `--print-row` and `--print-view`
  print through the right-click menus the same way, and `--print-format`
  sends them all in one format and checks it, a STEP with the tests' own
  checker (`tests/step_support.py`).
- **Export STEP.** File > Export STEP (`viewer.stepaction`, the work in
  `viewer.stepexport`) writes the part the details panel shows, in its
  configuration, with `solidseas.step`, in the same export process and job
  object as 3D Print (`printing.export_in_process`, job `step`), waited on
  from a pool of its own behind a progress dialog whose Cancel ends that
  process. The file is written as a hidden `.part` file beside the target
  and renamed into place, over an existing file only when the save dialog
  (or, for a name typed without an extension, the viewer itself) asked; a
  stopped process leaves only the part file, which is removed. A part with
  no solid gets its surface bodies written. When a body cannot be written
  without loss, nothing is written and the viewer names the bodies and asks
  whether to write the file without them, which runs the export again with
  `allow_partial`. The self-test's `--export-step` presses it with the save
  dialog answered by a temporary folder and checks the file with the tests'
  own checker (an assembly, or a 3D file the STEP export does not write, must
  find the entry off with its reason in the tooltip), which the packaged viewer
  carries for that alone
  (`packaging/SolidSeasViewer.spec`), so the executable's STEP export is
  checked without window automation.
- **Convert.** File > Convert (`viewer.convertaction`, the work in
  `viewer.convertfile`) is the OCCT backend extension's front, in the File
  menu only while that backend is available: it writes the part, assembly,
  Parasolid, IGES, BREP or STEP file shown as another of those formats through
  `solidseas.convert`, a SOLIDWORKS document or a Parasolid file through the
  STEP model Export STEP writes of it (`stepexport.step_of`). Its controller is
  Export STEP's with its own dialog (the file type chooses the format), words
  and result, so it runs in the same export process (job `convert`), writes the
  same hidden `.part` file and asks the same question about bodies; the export
  process starts the OCCT helper itself, which the process's job object allows.
- **Open and Show in File Explorer** (`viewer.opening`). Open, on the toolbar,
  the File menu and first on the right-click menu of a file (the list, every
  row of the details panel that stands for a file, a Where Used row in the
  opened folder, the 3D view's legend and components), hands the file to the
  program the system opens it with through `QDesktopServices.openUrl` with its
  file URL, the shell's open verb on Windows, so SOLIDWORKS gets a SOLIDWORKS
  document and the default program any other; no command line is made. Show
  in File Explorer selects it in its folder through the shell's
  `SHOpenFolderAndSelectItems` (`open -R` with the path as one argument on
  macOS, the folder elsewhere). In the packaged viewer both run without what
  the packaging set for itself, as `printing.launch` does. A row's file is the
  one reference resolution found, as Go to file (the in-app navigation,
  `viewer.navigate`) finds it, and Open is offered only for a plain file of a
  3D format the registry lists, never a link, a lock file or another kind of
  file; the window looks the two functions up each time, so a session-wide
  test guard replaces them.
- **Drawings** (being built, `docs/DRAWINGS.md`). `solidseas.drawing`, a
  library module with no Qt, recognises a part's features from its B-rep, draws
  its hidden-line views, dimensions them on datums and writes the SolidSeas
  drawing file, a PDF and a DXF; an assembly's drawing has its views, a parts
  list from `solidseas.bom` and item balloons, its parts placed as
  `solidseas.geometry` places them for the 3D view and the STEP export; the CLI's `drawing` command makes the same
  drawing for ERP use. The viewer adds Drawing Settings, a New Drawing wizard
  and a drawing editor, runs the library in a child process as the 3D view's
  mesh reads run, paints its display list with QPainter, and writes the drawing
  files next to the part under the 3D Print file's rules. The library is
  built: the tessellator's detail for drawings, the core's contracts, bounds,
  settings and display list, feature recognition, views,
  planning and layout, the PDF and DXF writers, the drawing file with release
  and regeneration, the checklist, the edits (each laying the sheet out again
  from the model with the drawing's records applied) and the `drawing`
  command. `make_drawing` finds each stage by its dotted path, so a stage a
  build lacks is a capability gap (`not_implemented`, rule `stage_missing`).
  The viewer's entries, the New Drawing wizard, the drawing editor, the
  drawing process (`viewer/drawingproc.py`) and the sheet on screen
  (`viewer/drawingscene.py`) are built too; `docs/drawings/` describes what is
  built, page by page.
- **Modeling assistant.** An always-on-top window that works alongside the
  user while they model. It attaches to a live SOLIDWORKS session only after
  the user opens it and picks the session and the document, and only one
  SolidSeas run works in a session at a time. The full design, including the
  operation vocabulary, the verification rules, the process layout and what
  must still be confirmed against SOLIDWORKS, is in `docs/ASSISTANT.md`.

  **Review mode** (the default). The user describes a change in plain English
  or types code. The AI drafts CadQuery code, or Python against
  `solidseas.swapi.live`, a typed facade over the bridge. The code appears in
  an editable console and runs only when the user approves it, in a worker
  process the user can stop.

  Built so far (`solidseas_app/assistant/`): the window (`window.py`), with the
  session and document pickers, the draft through the provider on a worker
  thread, "What the AI sees", the console and its warning, the log, and the
  always-on-top rule that lets go while a SOLIDWORKS call waits; the runner
  (`runner.py`), the one module that starts an interpreter for approved code,
  a child Python (`child.py`) in a Job Object with a memory cap on Windows,
  its own process group and `RLIMIT_AS` elsewhere, a time limit, Stop, and
  JSON lines through which the script's `solidseas.swapi.live` requests reach
  the app, which passes on only the read-only queries and the vocabulary's
  operations; and the session interface (`session.py`) the window asks for
  sessions, snapshots, the safety copy and undo entry around a script, and
  the script's operations, which `live_sessions.py` implements over the
  bridge's live operations: it lists the person's SOLIDWORKS sessions without
  SolidSeas' own batch instances, reads a picked part's snapshot, writes the
  safety copy and opens the undo entry before a script runs, and checks each of
  the script's operations with the plan validator before the bridge carries it
  out. Where the bridge is not built the window says so and runs scripts that
  do not use SOLIDWORKS. The viewer opens it from Tools > Modeling Assistant and its
  toolbar, and `SolidSeasViewer.exe --assistant` or
  `python -m solidseas_app.assistant` opens it on its own. The AI settings page
  (`settings_dialog.py`) chooses the provider and model, stores the key through
  `solidseas.ai.credentials`, tests the connection on a worker thread and sets
  the budget; the settings other than keys live in `AI.json` beside
  `Viewer.ini` (`aisettings.py`, no Qt), and the window builds its provider from
  them through the factory.

  **Automatic mode.** The user states a goal, for example "add M3 heat-set
  bosses at the four lid corners and shell the part to 2 mm", and switches
  Automatic on for that run. The assistant plans once, using only a closed
  vocabulary of checked operations, shows the plan, and carries it out on one
  part document without asking at each step. It asks once before starting only
  when the plan would overwrite or hide something the goal did not spell out.
  Guardrails:

  - One part document, bound at the start. Assemblies are refused in this
    version.
  - A safety copy of the document, unsaved edits included, before step 1, and
    an inverse recorded for every step, so the run reverts from any step back
    to the start without touching the shared SOLIDWORKS undo stack.
  - Verification after every step against what that operation may change,
    taken from SolidSeas's own table, never from the model. When in doubt the
    run stops; it never guesses forward.
  - Limits per run on steps, time and tokens, a live log, and a Stop button and
    global hotkey that take effect between steps.
  - It never runs free generated code and never saves the user's document.

  **Machine policy.** On a managed PC an administrator can disable Automatic
  mode or restrict the assistant to a local provider, under
  `HKLM\SOFTWARE\Policies\SolidSeas`. The policy is read fail-closed, following
  the `fail-closed-machine-policy` pattern: a missing policy means no
  restriction, and a policy that cannot be read means the restriction is on.
  Group Policy or Intune deploys it; on one PC, `SolidSeasViewer.exe
  --set-policy`, run as administrator as a step of its own
  (`solidseas_app/setpolicy.py`), writes it, the only code in SolidSeas that
  does.
- **CadQuery workspace.** Write or generate CadQuery models and send them to
  STEP or Parasolid, or into SOLIDWORKS as a native part through the
  `solidworks` backend. Generated code runs through the same worker process as
  Review mode.
- **Gridfinity bins from photos** (`solidseas_app/gridfinity/`,
  `docs/GRIDFINITY.md`), served by the MCP server beside the SOLIDWORKS tools.
  Tracefinity, run by the user in Docker on a server or on this PC, traces tools
  photographed on a sheet of paper and makes the bin's STL; SolidSeas reaches it
  at a loopback address only, through `solidseas.ai.http` with the address
  pinned (`tracefinity.py`), a server's through an SSH tunnel it opens with the
  system's ssh and a forward-only key, in a Job Object so it ends with the
  server (`tunnel.py`), lays the tools out in the smallest bin they fit, placed
  the way Tracefinity's editor rebuilds them (`layout.py`), places and sizes a
  text label for Tracefinity to draw, along the bin's back edge or in each
  pocket's floor, from font widths it keeps (`labels.py`), draws outlines and
  layouts as PNG with the standard library (`png.py`, `drawings.py`), and
  writes files only into the bins folder, never over one (`connector.py`).
  Photos go to Tracefinity alone; the chat gets sizes and drawings.
- **Extensions** (design, not built: `docs/EXTENSIONS.md`). Optional features
  become extensions the person adds and switches on from an Extensions page:
  a small front inside the core, inert until on, and for the large or
  licence-bound part a package outside the core executable whose helper runs as
  a child process. The first four: Gridfinity, the CAD Bridge (to SOLIDWORKS), video
  export and the OCCT backend; then SolidCraft, whose MCP server gives the chat
  a free parametric CAD program.

### 9. Integration surfaces

- Python: `import solidseas`.
- CLI: `solidseas <command> --json`, for any language that can run a process.
- REST: `solidseas serve`, a small local HTTP service for systems written in
  other languages, such as the TypeScript store.

Status: all three are built (Phase 1, released as 0.2.0), and their names,
JSON kinds, exit codes and routes are stable under `docs/API.md` section 9.
Phase 1's "done when" passes on Windows: `tests/test_phase1_done.py` lists a
folder with thumbnails and properties and reads an assembly's component list
through the service, the CLI and Python, without SOLIDWORKS automation
loaded. `docs/ROADMAP.md` has the measured results, and
`docs/SECURITY_REVIEW.md` section 1 reviews the service.

All three emit the same JSON. `solidseas.model` defines every shape once: a
registry of kinds, each with its builder, schema version and JSON Schema, one
strict encoder, and one function that turns any exception into the error
object. `solidseas.errors` holds the exception tree with its stable error codes
and the coded reader warnings. `docs/API.md` documents both for integrators.

`solidseas.walk` is the one folder walker. The folder listing
(`solidseas.listing.scan`), the CLI's `batch` and the reference resolution
index all walk with it, so they agree on what a link, a mount
point, a cloud placeholder, a SOLIDWORKS lock file and a FIFO are: links and
mount points are never followed, and placeholders and FIFOs never opened. A
listing opens each document `within` the walked folder (no link below it is
crossed, even one that appeared after the walk), with a held, unbuffered
handle, reads only the streams its entry needs and closes the handle before
the next file. The CLI's command table (`solidseas.cli.COMMANDS`)
maps each command to the kind it prints.

`solidseas.resolve` finds the file each stored reference names, inside the
caller's roots (`solidseas.Roots`, one type for every surface). Its modules
split by what they may touch: `names` handles stored Windows paths and name
folding as strings, `index` keeps a root's documents as the walker found them,
`identity` compares creation times, and `core` applies the rules. Only
`gateway` touches the filesystem, and a test checks the source of the others:
it builds the indexes, makes the point lookups outside the roots after
classifying the anchor (a UNC path or mapped network drive is never touched)
and opens candidates `within` their root. The rules collect candidates, read
their identities in one batch and then decide, so the REST service can run the
identity reads in a worker process (`docs/API.md` C10).

`solidseas.workers` reads documents nobody vetted in a fixed set of spawn
worker processes: a job goes to a worker as JSON and its answer comes back as
JSON read with a length limit, never unpickled; a job that misses its deadline
gets its worker killed, joined and only then replaced; and each worker has a
memory cap, a Job Object on Windows and `RLIMIT_AS` on Linux. `solidseas.jobs`
is the fixed table of what a worker runs: each job opens one document read-only
`within` its root and calls the same `solidseas.model` builder as the other
surfaces. The REST service and the CLI's `list` and `batch` read every document
this way; `batch` adds one job of its own, which also writes the document's
preview and Parasolid files under the CLI's write guards, and which the
service's pool never has.

`solidseas.serve` is the REST service, standard library only. `server` holds the
`ThreadingHTTPServer`, the guards in the order a request meets them (Host,
Origin and Fetch Metadata, method, token, query, path) and the routes, which are
the kind registry's REST routes; `query` holds one parameter allowlist per
route; `paths` checks a request path as text and finds it in the root's folder
index, so no text from a request is ever joined into a path; and `tokens` keeps
the bearer-token file and computes the proof `/v1/identity` gives a client
that checks the service before sending its token. The server process never opens a CAD file: documents are
read by the worker pool, and for reference resolution the server process
collects candidates from the indexes it built at start and applies the rules,
while one worker job reads the candidates' identities.

## Packaging

- `pip install solidseas`: library and CLI only.
- Extras: `[app]` for the desktop UI, `[cad]` for CadQuery, `[swapi]` for
  SOLIDWORKS automation on Windows, `[ai]` for the AI connector, `[dev]` for
  tests and lint. `[cad]` installs CadQuery, which brings in Open CASCADE
  (LGPL) through `cadquery-ocp`; what the extra should hold is still to decide
  (`docs/OCCT.md` section 9), and the viewer executable never bundles it
  (section 4 there).
- The desktop app will later ship as a signed Windows installer.

## Prior art

The format work is checked against open-source projects that read SOLIDWORKS
files: cadmpeg (Apache-2.0, Rust), openswx (C++), sldprt2step (Python),
model_viewer (TypeScript) and the sldprt-format-research notes. Anything reused
is credited in `NOTICE` with its licence. Code under licences incompatible with
Apache-2.0 is consulted, not copied.
