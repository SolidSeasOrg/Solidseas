# Roadmap

Phases run in this order because each one is built on the last. A phase is
done when its "done when" list is true and the change is pushed.

## Phase 0: Format proof of concept (done)

Read SOLIDWORKS files without SOLIDWORKS.

Status: the oracle tests pass, the corpus sweep reports per-format rates
(`docs/FORMAT.md`, section 17), and an independent reader written from
`docs/FORMAT.md` alone agrees with the library on a 361-file holdout, after the
corrections it prompted. One gap remains: node-level Parasolid claims rest on
the base-schema table reused from sldprt2step, which no independent reader has
re-derived.

- Container readers for the legacy OLE format and the 2015+ format.
- Decoders for the preview image, embedded Parasolid, custom and configuration
  properties, configurations, material and saving version.
- `docs/FORMAT.md`, with every claim marked verified, hypothesis or unknown.
- Synthetic oracle fixtures generated through the SOLIDWORKS API, with exact
  expected values in tests.

Done when: oracle tests pass, a corpus sweep reports per-format success rates,
and an independent reader written from `docs/FORMAT.md` alone agrees with the
library.

## Phase 1: Library baseline for integrations (built in 0.2.0)

What an ERP or invoicing system needs.

Status: built, and released as 0.2.0, the first version under the stability
policy in `docs/API.md` section 9. The "done when" below passes on Windows. The
phase is done once the change is pushed and the first Linux CI run passes the
same tests (the Linux-only code paths have not run yet).

- `open_document()` public API, stable and documented: built. `docs/API.md`
  covers the Python API, the JSON every surface emits, the command line and the
  service, with recipes in Python, curl and TypeScript.
- Full assembly support: built. Component trees per configuration, with each
  instance's flags and its placement in the assembly; referenced files with
  per-configuration counts; virtual and imported components read as the
  documents nested in the assembly; a drawing's models and sheets. Moved and
  duplicate-named referenced files are found by `references --resolve` and
  checked against the creation time the assembly stored, for the top
  assembly's whole tree (sub-assemblies are not opened and resolved in turn).
- CLI with `--json` on every command: built, with stable exit codes.
- `solidseas serve`, a local REST service: built, reviewed in
  `docs/SECURITY_REVIEW.md` section 1.
- Path-leak report: built. It lists every path and user name a file, and every
  document nested in it, would reveal.

Done when: an integrating system can, without SOLIDWORKS, list a folder's parts
and assemblies with thumbnails and properties, and get an assembly's component
list; and, measured on the development corpus:

- reference resolution, on a seeded holdout of documents that played no part in
  choosing the rules, finds at least 70% of direct references with an identity
  match, with at most 1% ambiguous, 3% whose identity differs and 30% missing,
  both with the library's defaults and as the service runs it;
- the path report holds every path the structured carriers store (the
  component tree, `Header2` and the folder at save, of the document and of every
  nested document), and every path the 0.1 byte scan finds, except where that
  scan was wrong.

Result, on 2026-10-01:

- `tests/test_phase1_done.py` passes through the REST service, the CLI and
  Python: a folder of the fixture documents, a part with no stored preview and
  a damaged file is listed with properties and previews (the part without one
  says so, and the damaged file is one error entry), every preview the listing
  describes is the PNG the service serves, the assembly's component list names
  its part twice, 50 mm apart, and a fresh interpreter shows that neither it nor
  its worker loaded SOLIDWORKS automation. The opt-in corpus tests check the
  two measured items below and pass.
- Resolution, on the holdout (116 documents, 1,553 direct references): 73.21%
  found with an identity match by default and 73.08% as the service runs it;
  0% and 0.06% ambiguous; 0% and 0.06% with a differing identity; 26.21%
  missing in both. A missing file lies outside the folders searched: in another
  project's folder, or a library part the corpus does not hold.
- Path report, over the 3,501 corpus documents: none of the 26,700 structured
  paths is missing, and every path the 0.1 scan finds is there, except the 474
  it cut at a non-ASCII character and the 75 it ran past the end of a stored
  string.

Deferred from Phase 1: resolving each sub-assembly in its own context,
version stamps, refreshing and persisting folder indexes, TLS, CORS, a
service configuration file, quarantining files that keep crashing workers, a
`/parasolid` route, a command to manage service tokens, serving the previous
schema version of a kind, a result cache, generated TypeScript types, and a
path-risk summary in folder listings.

## Phase 2: Desktop shell

Status: the read-only viewer preview (`SolidSeasViewer.exe`, [user guide](guide/viewer.md)) has most
of the pieces below. The shell itself, a folder model built on the catalog, is
still to come (`docs/ARCHITECTURE.md` layer 8), and the "done when" has not
been measured.

- Folder scan into the catalog index. Built (provisional): `solidseas.catalog`,
  the `index`, `where-used`, `search`, `duplicates`, `missing` and `changes`
  commands, `serve --catalog`, and the viewer's background indexing, Where Used
  tab and filter by part number or property.
- Project tree with assemblies and nested components, thumbnail grid, details
  panel. Built in the viewer preview: the folder tree; the file list as
  details or icons, with thumbnails, the name filter and the quick filter's
  buttons, one per type of document the folder holds; the details panel's
  Overview, Properties, Components (with positions), BOM, References, Where
  Used, Paths and Preview tabs, with the 3D view; and opening a component's
  file, with Back.
- Path-leak warnings in the details panel. Built in the viewer preview: the
  Paths tab lists every path and user name a document would reveal.
- Every 3D format beside the SOLIDWORKS documents. Built (provisional,
  `docs/API.md` 3.20, `docs/formats/`): STEP, Parasolid, STL, 3MF, OBJ, PLY,
  OFF, glTF, AMF, ACIS SAB and Alibre Design files are read, listed, previewed
  and drawn in 3D; IGES, Inventor, Solid Edge, Fusion, 3D XML, eDrawings, VRML,
  ACIS text and Alibre Design drawings and packages are recognised and listed,
  not read yet.

Done when: pointing the app at a real project folder shows every CAD file with a
preview and its properties within seconds of the first scan.

## Phase 3: Conversion and 3D printing

- Conversion engine with native, CadQuery and SOLIDWORKS backends. The native
  work is built as `solidseas export`; the engine itself, its conversion table
  and stages CV-2 to CV-8 are planned (`docs/ARCHITECTURE.md` layer 5).
- `SolidSeas.SwBridge.exe`, the SOLIDWORKS bridge, as a separate process with
  a COM message filter, request timeouts and a Job Object. Batch mode is its
  first user. Built (provisional): the bridge, `solidseas.swapi.bridge` and
  batch conversion to STEP, Parasolid, STL and 3MF on SolidSeas' own
  SOLIDWORKS (`python -m solidseas.swapi convert`).
- SLDPRT and SLDASM to Parasolid, and Parasolid to SLDPRT through SOLIDWORKS.
- STEP, STL and 3MF export. Built (provisional): STL and 3MF from every format
  SolidSeas reads (CV-1), and STEP AP214 of a part's exact B-rep from a
  SOLIDWORKS part or a Parasolid file (`solidseas.step`, and File > Export
  STEP in the viewer), which Open CASCADE measures as close to the source as
  SOLIDWORKS' own STEP (`docs/OCCT.md`) and SOLIDWORKS itself reads back as
  closely (`docs/FORMAT.md` 10.9). Like SOLIDWORKS' own STEP it leaves hidden
  bodies out and cuts a face that goes round a closed surface at its seams.
  STEP from the other sources and of assemblies are CV-4 and CV-5.
- 3D Print button that sends to the remembered slicer, defaulting to Bambu
  Studio. Built in the viewer preview, for every format SolidSeas reads: 3MF,
  STL or STEP (for a part the STEP export writes), whichever the chosen
  program takes, written as a new dated file next to the model.
- 3D viewer in the app. Built in the viewer preview: an OpenGL view of every
  format with a view cube, Home, turning about the point under the pointer,
  picking, an exploded view, and hide, isolate and transparency per component.
  Whether the app's 3D viewer grows from it is not decided.
- Open CASCADE as an opt-in test oracle (tier 0 of `docs/OCCT.md`): it
  measures what the STEP export writes and what the STEP reader draws, in
  tests that skip unless an OCP interpreter is named, and is never a
  dependency. Built, with the STEP fixes it led to: the STEP reader's voids,
  folded faces and faces stored the wrong way round, the mesh self-checks,
  rolling blends drawn by the tessellator, and the STEP export's seams and
  hidden bodies. What they left, among it 4 files whose voids still come out
  inside out and hidden bodies still in STL and 3MF prints, is in section 9 of
  `docs/OCCT.md`.
- IGES import and export through an optional Open CASCADE conversion backend
  (tier 1 of `docs/OCCT.md`, with bead SolidSeas-e2z): OCP only, in worker
  processes, offered only when it is installed.

Done when: one click sends a selected part or assembly to Bambu Studio, and the
app remembers that choice.

Status: in the viewer preview, one click on 3D Print sends the selected part or
assembly to the remembered slicer, Bambu Studio by default when it is
installed. The conversion engine, SLDPRT from Parasolid and the CadQuery and
Open CASCADE backends remain.

## Phase 4: BOM and versions

- Flat and indented BOMs from assemblies, exported as CSV and JSON. Built
  (provisional): `solidseas.bom`, the `bom` command and `/v1/bom` match
  SOLIDWORKS' own top-level and indented tables on fixture o19, and the
  viewer's BOM tab shows and exports them.
- Git-aware history, with snapshots for folders outside git. Built
  (provisional, `docs/VERSIONS.md`): `solidseas.versions` and the `history` and
  `snapshot` commands, Git read in pure Python with no program run, and
  snapshots kept in the user's data folder, or in a project's folder when it is
  named.
- Version timeline with previews and property and geometry diffs. The
  differences are built (provisional): `diff` and `versions.compare` report
  properties, configurations, the document and each configuration's geometry
  (a B-rep fingerprint, and volume, area and size where it changed). The
  viewer's timeline with previews is to come.
- Git LFS guidance for repositories that store CAD files. LFS files are read
  from the local LFS objects; the guidance itself is to come.

Done when: the app shows an assembly's BOM and a part's version history with
what changed between versions.

## Phase 5: Modeling assistant and CadQuery

The full design is in `docs/ASSISTANT.md`.

- A spike, first, on a SOLIDWORKS instance SolidSeas starts for the purpose,
  answering every item under "Confirm before building" in `docs/ASSISTANT.md`.
  Each answer confirms the design or turns into a stop or refusal in it.
  Done: the eight answers are recorded there.
- AI connector (`solidseas.ai`) following the `ai-provider-seam` pattern:
  provider interface, shared prompts and parsers, Anthropic, OpenAI, Gemini and
  Ollama providers, `solidseas/ai/context.py:build_model_summary` as the only
  way document data reaches a prompt, enforced budgets and timeouts, keys in
  Windows Credential Manager, `truststore` for managed networks, and a scripted
  fake provider for tests.
  Built (provisional, `docs/API.md` 3.23): the connector on the standard
  library's HTTP with no SDK, token and cost budgets with the usage file,
  cancellation, keys through `CredReadW` and `CredWriteW`, the machine policy
  read fail-closed with both chokepoints (the provider factory, and
  `start_run`'s checks before step 1), and the plan validator for vocabulary
  version 1. The window, the bridge's live mode and the step loop come next.
- CadQuery workspace: write or generate models, export STEP, or build a native
  SOLIDWORKS part through the SOLIDWORKS backend.
  It brings Open CASCADE in as tier 2 of `docs/OCCT.md`: a separate, heavier
  extra (the full CadQuery, with casadi and VTK), never in the core library or
  the viewer executable. The bridge can already make a new document and import
  STEP, IGES and Parasolid into it (`new_document`, `import_file`); writing a
  native SLDPRT still needs a save operation.
- Always-on-top assistant window with a script console, a live log, and a
  "What the AI sees" panel.
- Review mode: plain English to drafted code against `solidseas.swapi.live`,
  editable, run on approval in a worker process inside a Job Object.
- Automatic mode: a plain-English goal to one validated plan from the closed
  vocabulary, carried out on one bound part with a safety copy, an inverse per
  step, structural verification, per-run limits, a global Stop hotkey and crash
  recovery from the run journal. It never runs free generated code and never
  saves the user's document.
- Live attachment through a session and document picker, opt-in per session,
  with one writer per SOLIDWORKS session.
- Machine policy that can disable Automatic mode or restrict providers to
  local only, read fail-closed and enforced in two chokepoints, with an
  elevated `--set-policy` entry point for administrators.
  Built: the reader, both chokepoints and `--set-policy`
  (`solidseas_app/setpolicy.py`); the AI settings page's "Lock for all users"
  button, which would start it, is not.
- `docs/SECURITY_REVIEW.md`, written to the `desktop-app-security-review`
  skill: a findings table with severity and status; the complete set of
  outbound connections, each marked verified or by inspection with the command
  that repeats the check; the code execution surface (the runner module and the
  bridge); what is stored, including Credential Manager entries, the usage
  file, run folders and checkpoints; that the app reads but never writes the
  policy key outside `--set-policy`; and a recommendation with its conditions.

Done when: while modeling in SOLIDWORKS, the user can ask for a change in plain
English, review the generated code, run it and undo it; can hand the assistant
a goal in Automatic mode, watch it carry the goal out step by step, stop it
between any two steps, and revert the whole run in one action; and
`docs/SECURITY_REVIEW.md` covers the AI connector, the runner, the bridge and
the machine policy with repeatable checks.

## Phase 6: Drawings from 3D parts

The full specification, with the user's decisions, the build order and the
acceptance checks, is in `docs/DRAWINGS.md`. This phase runs beside Phases 4
and 5: it needs only the format readers, the tessellator and the viewer.

- Stage 1, the first release: SOLIDWORKS parts, machined (milled) and 3D
  printed, drawn to ASME practice in inch or millimetre and located on datums
  A, B and C with position tolerances; a six-page wizard, an editor with a
  checks list, signing, release and revisions; the SolidSeas drawing file
  (`.ssdrw`), a PDF and a DXF written next to the part; Email PDF through the
  user's webmail, or attached by classic Outlook or Thunderbird; Update from
  Model keeping the user's edits; and the `solidseas drawing` command for ERP
  use.
- Stage 2, release 1.1: turned (lathe) parts, auxiliary views, automatic
  detail views, broken-out sections, and STEP, Parasolid and Alibre parts.
- Stage 3, release 2: a SOLIDWORKS drawing (`.SLDDRW`) made through the bridge
  in SolidSeas' own SOLIDWORKS, never the user's session; drawing files in
  listings and the catalog.
- Stage 4, later, a bead each: ISO drawings, chain dimensions, hole tables,
  mesh sources, sheet metal, assemblies and the rest of `docs/DRAWINGS.md`
  section 3.7.
- Open CASCADE stays a development cross-check for the hidden-line engine
  (`docs/OCCT.md`), never a dependency of the drawing library; whether its
  polygon-based algorithm could speed hidden lines up is a stage 4 question.

Done when: from a SOLIDWORKS part, a user gets a datum-referenced, dimensioned
PDF and DXF stamped PRELIMINARY, edits the drawing, has it signed and released,
emails the PDF and updates the drawing when the part changes; and the stage 1
acceptance checks of `docs/DRAWINGS.md` section 21 pass, those that need the PC
included, apart from the DXF audit in programs the user may choose not to
install (section 12.2 there).

## Phase 7: Native SOLIDWORKS parts from open CAD tools (research)

The full design, the evidence and the status are in
`docs/NATIVE_SLDPRT_WRITER.md`. The aim is a `.sldprt` made with no SOLIDWORKS
that opens with a native, editable feature tree, so that open, agent-driven
CAD programs such as SolidCraft can hand SOLIDWORKS users a part they can work
on. SOLIDWORKS on the PC only checks the results. This phase runs beside the
others: it needs the format readers and the bridge, nothing else.

Status: the container writer, the feature-stream reader, the experiment
candidates, `ParametricDocumentIR`, the SolidCraft adapter and a seed-based
writer for one extruded rectangle are built. On 2026-10-19 SOLIDWORKS 2024
opened all 17 test parts as native, editable sketches and extrusions,
including a SolidCraft design written with no SOLIDWORKS; a part without a
Parasolid partition is rebuilt as it opens.

- Step 1 (done): SOLIDWORKS' verdict on the candidates: it opens a container
  this writer laid out, rebuilds from an edited parameter, and builds the body
  when the partition is missing.
- Step 2: dimensioned-sketch fixtures through the API, then decoding relations
  and dimensions, and the object map the feature stream shares with other
  streams.
- Step 3: authoring a new sketch and extrusion into an empty part, then cut,
  revolve, hole, fillet, chamfer and patterns, one at a time, each through the
  same check.
- Step 4: `solidseas export model.solidcraft --format sldprt`, offered only for
  what has passed the check, with every left-out feature named to the user.

Done when: a SolidCraft part with a dimensioned rectangle sketch and a blind
extrusion, written with no SOLIDWORKS, opens in SOLIDWORKS as a native sketch
and extrusion, takes a change of each dimension, rebuilds, saves and reopens
with the change, on the PC's check.
