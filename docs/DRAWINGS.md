# Automatic drawings from 3D parts

Status: specification, nothing built yet (2026-10-04).

This is the build specification for SolidSeas' automatic drawings: from a 3D
part, a SolidSeas drawing file, a PDF and a DXF, dimensioned to ASME practice,
which the user then edits, has signed, releases, emails and updates when the
part changes. It condenses a design that went through two reviews (a drafting
review asking whether the drawings would pass a drawing check, and a
feasibility review asking whether the plan could be built in this order and at
this speed), the user's answers to its questions, research on the drafting
standards, and measurements of prototypes on the fixtures and on the private
corpus. The prototypes and the research notes are not in the repository;
everything a builder needs from them is in this document, and corpus results
are counts only.

Labels used below:

- **measured**: a number from a prototype or a corpus run;
- **decided**: chosen by this design; a build may change it when measurement
  gives a reason, and records the change here;
- **target**: a goal not yet measured;
- **verify**: rests on documentation nobody has tested, on a standard not yet
  bought, or on a reading of a user answer the user has not yet confirmed;
- **user**: answered by the user. Section 2 lists these answers; do not reopen
  them.

## 1. What the first release does

In the order the user meets it:

1. **Settings > Drawing Settings...** holds, once per Windows user and outside
   every project folder: the company (name, address, phone, web, logo,
   proprietary statement), the people who may sign drawings and which approval
   rows the company uses, units (including the unit for parts that state none,
   asked on first use), sheets, the general tolerance block, the default
   position and profile tolerances, note templates, the material and finish
   lists, the default views per manufacturing type, where files go and how
   email works.
2. **File > New Drawing...** (Ctrl+D), a Drawing toolbar button beside 3D
   Print, and **Make Drawing...** on every right-click menu that offers 3D
   Print run a six-page wizard: part and units; title block and material;
   manufacturing type and datums; views and sheet; dimensions and holes
   (including confirming threads); output. A live preview of the sheet shows
   from page 2 on.
3. The result is a **fully dimensioned drawing** in the sense a drawing checker
   accepts: the part is located on datum features A, B and C; every recognised
   feature has its size once and its location once per axis (and angularly
   where it is clocked) from those datums; every value has a stated tolerance
   (the title block, an explicit one, or a feature control frame or the
   general profile note for basic dimensions); every dimension sits on a
   visible edge in a true-shape view without collisions; and anything the
   generator cannot recognise or show in true shape is listed by name and
   reason. A drawing with such leftovers is a **reduced-dimension drawing**:
   its model-governs note names the model and its revision and gives the
   undimensioned surfaces a profile tolerance to A, B and C, and it cannot be
   released until the user accepts that. Datums and tolerance values are
   proposals the wizard shows and the editor changes: design intent stays with
   the engineer.
4. **The drawing editor** opens on Finish. Dimensions can be removed and
   restored, added from the candidates the planner offers for one or two picked
   features, re-linked to measure between two features directly, moved, and
   given their own tolerance, precision or feature control frame. Notes, title
   fields, the tolerance block, sheet, scale and units can be changed for this
   drawing, and detail and section views added. A checks list re-runs after
   every edit and says what became missing or redundant. Undo covers
   everything.
5. **Status, signing and revisions.** A new drawing is PRELIMINARY, carries
   only the DRAWN name and date, and every PDF and DXF of it is stamped
   "PRELIMINARY - NOT FOR MANUFACTURE". A person signs CHECKED and APPROVED
   with an explicit Sign... action; Release fixes the revision, writes the
   released PDF and DXF once and makes the drawing read-only. Any later change
   starts a new revision (B, C and so on) with its own row in the revision block
   and new file names.
6. **Files**, next to the part by default: the SolidSeas drawing (`.ssdrw`,
   JSON), which reopens in the editor with every edit and holds the laid-out
   sheet so a released drawing reopens exactly; a vector PDF; and a DXF (R2000)
   that opens in AutoCAD-family programs and LibreCAD with measuring, not
   associative, dimensions, hole and thread callout lines beyond the diameter
   being text.
7. **Email PDF** saves the PDF, shows it selected in the file manager and opens
   the webmail compose page (Gmail by default) in the default browser; with
   classic Outlook or Thunderbird present it attaches the PDF in their compose
   window instead. The user presses Send; SolidSeas never holds a mail password.
8. **Update from Model** follows a changed part and keeps the user's edits,
   because dimensions are tied to recognised features, not to coordinates. It
   lists anything it could not match.
9. **The command line** makes the same drawing for ERP use
   (`solidseas drawing new PART ...`), but never signs or releases.

Stage 1 scope: SOLIDWORKS parts; the ASME profile in inch and millimetre;
machined (milled) and 3D printed parts.

## 2. Decisions already made

| Topic | Decision | Source |
|---|---|---|
| Editable output | Both. Stage 1 writes SolidSeas' own drawing file (`.ssdrw`), a DXF and a PDF. A SOLIDWORKS `.SLDDRW` comes in stage 3, made through the bridge in SolidSeas' own SOLIDWORKS, never in the user's session | user |
| Manufacturing types | Machined (milled) and 3D printed in stage 1; turned (lathe) in release 1.1 (stage 2); sheet metal later | user (Q5) |
| Locations on machined parts | Datums A, B, C with basic locations and position tolerances, as ASME Y14.5-2018 expects; plain plus/minus available per drawing | user (Q1) |
| Email | Email PDF saves the PDF, shows it selected in the file manager and opens the webmail compose page in the default browser: Gmail by default, the subject pre-filled from the drawing number and title only, with a setting to turn pre-filling off or to give another webmail compose URL. Classic Outlook and Thunderbird get the PDF attached automatically when present. SolidSeas never stores a mail password and never sends mail itself | user (Q7) |
| Where files go | Next to the part by default, under the same safety rules as the 3D Print file, never replacing a file SolidSeas did not write; a setting chooses another folder. Save may replace the same drawing's own `.ssdrw` and rewrite its PRELIMINARY PDF and DXF to keep them current, but only files SolidSeas wrote that are unchanged since; released exports are never replaced (section 12.6) | user (Q8, Q14) |
| General tolerances | Inch: .X ±.030, .XX ±.010, .XXX ±.005, angles ±0.5°. Millimetre: a decimal block, X ±0.5, X.X ±0.2, X.XX ±0.05, angles ±0.5°, with ISO 2768-m as an option | default stands (Q2) |
| Unit when the part states none | Guessed from round numbers and always confirmed in the wizard; inch when it cannot tell | default stands (Q3) |
| Sign-off | Rows DRAWN, CHECKED, APPROVED; CHECKED and APPROVED required to release; one person may sign two rows with a warning; first revision A | default stands (Q4) |
| ISO drawings | Later (stage 4); ASME only at first | default stands (Q6) |
| DXF checking programs | The user installs LibreCAD and DWG TrueView on the PC if they want the DXFs checked there. No session downloads or installs anything without the user's explicit permission | default stands (Q9) |
| Standards | Buying ASME Y14.5-2018, Y14.1-2020 and Y14.35 is the user's decision. Until then every verify item stays marked, and the docs say "follows ASME practice as summarised", never "conforms to" | default stands (Q10) |
| Small items | The Adobe font-metrics notice (APAFML) goes in `NOTICE`; the drawing file extension is `.ssdrw` | default stands (Q11) |

Design decisions that shape every branch:

| Topic | Decision |
|---|---|
| Library home | `solidseas.drawing`: pure Python, standard library only, no Qt, so an ERP process on Linux makes the same drawing as the viewer |
| First step | A thin end-to-end slice on o11 and three synthetic parts before any contract is frozen |
| Views | Exact B-rep edges; visibility by ray casting against the tessellation with the own-face test; analytic silhouettes for cylinders and cones, refined mesh silhouettes elsewhere; edge normals computed once per part; silhouette Newton started from the tessellator's (u, v) |
| Sections | Stage 1: full sections through a hole axis or a mid-plane, automatic only when a callout cannot state a hole's shape; a section replaces the projected view looking the same way; details on request |
| Completeness | A per-axis linear graph with size, radius and pattern links, an angular graph per pitch circle, one checker for planner and editor, and an independent reconstruction test written by another owner |
| Arrangement | Baseline, switching to ordinate per view and axis when stacks get deep; chain later |
| Layout | One library layout engine with Helvetica metrics; cheapest-first candidate search with early exit; incremental re-layout after an edit |
| Release flow | PRELIMINARY, CHECKED, RELEASED; Sign...; Start Revision; released files never overwritten |
| Identity | Features matched between model versions; a dimension's key is feature ids plus role plus axis; ids assigned once and inherited; view set, sheet and scale frozen at first save |
| Outputs | One display list; PDF and DXF R2000 written by hand; SVG internal for tests and previews; the viewer paints the same display list through a QPainter adapter |
| Settings | `%APPDATA%\SolidSeas\Drawing.json` (roaming, per user), every value checked and falling back on its own |
| Speed | Targets per size band, fixed after core 1 is measured; Draft quality above about 2,000 faces; parts over the bounds refused before any work starts |

## 3. Stages and build order

| Stage | Release | Contents |
|---|---|---|
| 1 | first release | SOLIDWORKS parts; ASME inch and millimetre; machined and 3D printed; the wizard, editor, signing and revisions; `.ssdrw`, PDF and DXF; Email PDF; Update from Model; the CLI |
| 2 | 1.1 | Turned parts, auxiliary views, automatic detail views, broken-out sections, and STEP, Parasolid and Alibre sources |
| 3 | 2 | The SOLIDWORKS `.SLDDRW` through the bridge; `.ssdrw` files in listings and the catalog |
| 4 | later, a bead each | ISO, chain dimensioning, hole tables, mesh sources, sheet metal, assemblies and the rest of section 3.7 |

### 3.1 Rules for every stage

- A branch owns its modules, its tests and its pages under `docs/drawings/`.
  Shared files (`src/solidseas/__init__.py`, `cli.py`, `model.py`,
  `errors.py`, `docs/API.md`, `docs/ARCHITECTURE.md`, `README.md`,
  `CHANGELOG.md`, `NOTICE`, `AGENTS.md`, the viewer's `window.py` and
  `selftest.py`, `packaging/SolidSeasViewer.spec`) change only in the core
  commits, integration and the viewer commit.
- The branch names below are the design's; a session may prefix them (for
  example `cloud/dwg-views`). Wave branches merge into an integration branch,
  `drawings`, which reaches `main` the way `docs/TWO_MACHINES.md` describes,
  through the VM.
- The version line is the one expected conflict, resolved at each merge by
  taking the higher version.
- Wave branches are provisional library internals without CHANGELOG entries;
  integration and the viewer write the user-facing ones.
- The VM files a bead per branch, per open question and per deferred item.
- Work that needs the PC (section 24) goes there as a request through the
  exchange; it is never assumed done.

### 3.2 Stage 1, in order

Useful on its own: a user picks a SOLIDWORKS part, answers the wizard, gets a
datum-referenced, dimensioned PDF and DXF stamped PRELIMINARY, edits it, has it
signed and released, emails the PDF, and updates it when the part changes.

1. **Base.** `drawings` from `main` once it holds the integ-oct5 handoff (every
   3D format, the quick filter, STEP export, the bridge, the AI connector, the
   STEP fixes and this document). Test parts are built on `tests/xt_bodies.py`'s
   `XtBuilder`, which writes synthetic Parasolid bodies node by node.
2. **Core 1, "Keep the tessellator's edge samples, normals and surface
   parameters for drawings"** (section 6.1): `src/solidseas/tessellate/__init__.py`,
   `_engine.py`, `edges.py`; `tests/test_tessellate_detail.py`; `docs/API.md`
   (the `detail` option). Then the PC measures views with the two fixes on the
   13 drawn parts and the size-band sample (with the design-stage prototype,
   which stays on the PC, or with `dwg-views` once it draws), and the targets
   of section 8.12 are fixed from the numbers.
3. **The slice, `dwg-slice`** (one owner, never merged): o11 and three
   synthetic parts (four equal holes at irregular positions, a block with a
   pocket and a tab, a pitch circle clocked 15°) through a minimal hidden-line
   engine and recognition written from sections 8 and 9, the datum scheme with
   baseline basic dimensions, a simple layout (tracks, text, callouts at a
   fixed leader angle, a frame and datum glyphs), a plain PDF writer, a minimal
   `.ssdrw`, and remove and restore with the checker. Exit: four PDFs the user
   glances at as a starting point, layout timings for section 11.3, and a
   written list of what the contracts must say, which core 2 takes.
4. **Core 2, "Add the drawing core"** (sections 5 to 7, 12.3):
   `src/solidseas/drawing/__init__.py`, `limits.py`, `settings.py`,
   `standards.py`, `numbers.py`, `fonts.py`, `source.py`, `facegraph.py`,
   `keys.py`, `types.py`, `display.py`, `painter.py`, `svg.py`, `pipeline.py`;
   `tests/drawing_parts.py`, `tests/drawing_support.py`,
   `tests/test_drawing_core.py`, `test_drawing_settings.py`,
   `test_drawing_numbers.py`, `test_drawing_source.py`,
   `test_drawing_facegraph.py`, `test_drawing_svg.py`;
   `docs/drawings/README.md`, `docs/drawings/standards.md` (section 22 of this
   document, with its two corrections), stub pages, `docs/drawings/REVIEW.md`;
   `docs/API.md` (a provisional section), `docs/ARCHITECTURE.md`, `NOTICE`
   (APAFML), `src/solidseas/__init__.py`.
5. **Wave one: five streams, eight branches, in parallel from core 2.**

| Stream | Branch | Owns | Needs | Code lines (estimate) |
|---|---|---|---|---|
| Geometry | `dwg-views` | `drawing/views/__init__.py`, `hlr.py`, `silhouettes.py`, `curves.py`, `cleanup.py`, `centres.py`; `drawing/sections.py`; `tests/test_drawing_views.py`, `test_drawing_views_oracle.py`, `test_drawing_sections.py`; `docs/drawings/views.md`, `sections.md` | core 1, core 2 | 3,400 |
| Geometry | `dwg-features` | `drawing/features/__init__.py`, `holes.py`, `grooves.py`, `patterns.py`, `widths.py`, `blends.py`, `chamfers.py`, `pockets.py`, `inclined.py`, `frame.py`, `threads.py`, `hints.py`, `accounting.py`; `tests/test_drawing_features*.py`; `docs/drawings/features.md` | core 2 | 3,000 |
| Plan and layout (one owner) | `dwg-plan` | `drawing/plan/*.py` (`requirements`, `graph`, `angular`, `schemes`, `gdt`, `select`, `assign`, `values`, `callouts`, `notes`, `candidates`); `drawing/layout/*.py` (`sheet`, `arrange`, `dimension`, `place`, `index`, `titleblock`, `notes`, `glyphs`, `patterns`, `stamps`, `checks`); `drawing/orchestrate.py`; `tests/test_drawing_plan*.py`, `test_drawing_layout*.py`, `test_drawing_orchestrate.py`; `docs/drawings/dimensions.md`, `gdt.md`, `layout.md` | core 2 (hand-made feature sets and views in its tests) | 8,200 |
| Plan and layout (another owner) | `dwg-oracle` | `tests/drawing_reconstruct.py`, `tests/test_drawing_reconstruct.py`; `docs/drawings/conventions.md` (the implied conventions the oracle reads) | core 2 | 700 (tests) |
| Writers | `dwg-pdf` | `drawing/pdf.py`, `drawing/images.py`; `tests/pdf_reader.py`, `tests/test_drawing_pdf.py`; `docs/drawings/pdf.md` | core 2 | 1,200 |
| Writers | `dwg-dxf` | `drawing/dxf/__init__.py`, `tags.py`, `tables.py`, `entities.py`, `dimensions.py`; `tests/dxf_reader.py`, `tests/test_drawing_dxf.py`; `docs/drawings/dxf.md` | core 2 (the external audit is a separate PC bead, section 12.2) | 1,600 |
| File and release | `dwg-file` | `drawing/document.py`, `release.py`, `match.py`, `merge.py`, `locate.py`; `tests/test_drawing_file*.py`, `test_drawing_release.py`, `test_drawing_match.py`; `docs/drawings/file.md`, `release.md` | core 2 | 2,600 |
| Settings and mail | `dwg-mail` | `src/solidseas_app/viewer/mail.py`, `mailproc.py`, `drawingsettings.py`; `tests/test_viewer_drawing_mail.py`, `test_viewer_drawing_settings.py`; `docs/drawings/email.md` | core 2 settings | 2,000 |

   `dwg-plan` is the critical path. Its first milestone, o11 end to end on the
   real types using the work in progress of `dwg-views` and `dwg-features`, is
   the one planned revision of the contracts (section 6).
6. **Integration, `dwg-integrate`** (the longest stage, planned as such):
   `drawing/__init__.py` and `pipeline.py` wired; `drawing/edit.py`,
   `drawing/checks.py`; `cli.py` (the `drawing` command), `model.py`
   (`drawing_result` and the file schemas), `errors.py` (four codes);
   `tests/test_drawing_golden.py` with `tests/goldens/drawings/`,
   `test_drawing_checks.py`, `test_drawing_edit.py`, `test_drawing_cli.py`,
   `test_drawing_corpus.py` (opt-in); docs brought up to date.
7. **Viewer, `dwg-viewer`:** `viewer/drawingaction.py`, `drawingwizard.py`,
   `drawingeditor.py`, `drawingscene.py`, `drawingproc.py`; a few hook lines
   in `window.py`; `--drawing-dry-run` in `selftest.py`;
   `packaging/SolidSeasViewer.spec`; `tests/test_viewer_drawing*.py`;
   CHANGELOG and README entries; and the AGENTS.md safety rule widened to the
   drawing files written next to the part (section 12.6), which records the
   user's answers to Q8 and Q14.
8. **On the PC:** the corpus sweep (section 20.3), the Windows checks, the DXF
   audit once its programs are installed, Email PDF with the user present, and
   the user's review (section 20.4). Each problem becomes a bead and a
   synthetic part, fixed on a short branch that owns the module it changes.

Size: about 24,000 lines of library code and 7,000 of viewer code in stage 1,
and about as much again in tests (estimate).

### 3.3 What slips to stage 2 first

If stage 1 runs long, these move to stage 2, in this order, without making
stage 1 useless:

1. Update from Model's merge. Fallback: "remake with your choices", which
   pre-fills the wizard from the drawing file.
2. The Simple MAPI attach route. The webmail route stays.
3. On-request detail views.
4. The ordinate switch. Baseline with the deep-stack warning stays.

### 3.4 Not in stage 1

Turned parts, auxiliary views, other source formats, automatic details,
broken-out sections, chain dimensioning, hole tables, ISO, mesh sources,
`BLENDED_EDGE` recognition as blends, DXF R12, SVG export, REST routes,
free-pick Add Dimension, Settings import and export, Key coverage and critical
flags, the geometry cache, several sheets (built since for an assembly's long
parts list alone, 11.7), `.SLDDRW`.

### 3.5 Stage 2: release 1.1

Branches from the stage 1 release, each owning the files listed:

| Branch | Owns | Notes |
|---|---|---|
| `dwg-turned` | `drawing/features/turned.py`, `drawing/plan/turned.py`, `drawing/plan/angular.py` (axes of revolution), `drawing/sections.py` (half and removed sections), `drawing/views/broken.py`, `drawing/layout/dimension.py` (one-arrowhead half-section diameters, across flats), `drawing/layout/glyphs.py` (surface texture symbols); tests; `docs/drawings/turned.md` | runout to A; section 10.6 |
| `dwg-auxiliary` | `drawing/views/auxiliary.py`, `drawing/plan/auxiliary.py`, `drawing/layout/arrange.py` (aligned and moved auxiliary views), `drawing/features/inclined.py` (claiming instead of reporting); tests; `docs/drawings/auxiliary.md` | section 8.11 |
| `dwg-details` | `drawing/orchestrate.py` (automatic details and the re-plan loop), `drawing/layout/sheet.py`; broken-out sections in `drawing/views/brokenout.py`; tests | section 8.10 |
| `dwg-sources` | `drawing/source.py` (STEP, `.x_t`, `.x_b`, Alibre); tests on the formats fixtures | the readers are merged already |

Integration and viewer commits follow as in stage 1 (the wizard's Turned
option; auxiliary and removed-section kinds in the editor's Add View).

### 3.6 Stage 3: release 2, the SOLIDWORKS drawing

`dwg-sldrw` (section 16): `drawing/sldrw.py`; the bridge operations it needs in
`src/solidseas/swapi/SwBridge` and their client calls; the Make SOLIDWORKS
Drawing command in `viewer/drawingaction.py` and `drawingeditor.py`; the
SOLIDWORKS page of `viewer/drawingsettings.py`; `tests/test_drawing_sldrw.py`;
`docs/drawings/sldrw.md`. `dwg-catalog`: `.ssdrw` files in listings and
where-used, thumbnails from the sheet. Stage 3 can run beside stage 2 (disjoint
files) but needs SOLIDWORKS free, the user's permission for a verification run,
and questions Q12 and Q13 answered.

### 3.7 Stage 4: later, a bead each

The ISO profile (first angle, ISO 7200 with STATUS, ISO 2768 with ISO 8015,
aligned text, comma decimals, the ISO 13715 edge symbol); chain dimensioning;
hole tables; mesh sources with "REFERENCE ONLY - NOT FOR MANUFACTURE";
`dwg-blends` (recognising `BLENDED_EDGE` faces as blends with a radius);
DXF R12; SVG export; REST routes and `ssdrw_summary`; free-pick Add Dimension;
Settings import and export and a Presentation page; Key coverage, critical and
inspection marks, and the print file named in printed notes; the geometry
cache; the DXF TOLERANCE entity; dual dimensions; several sheets (views on a
second sheet; a long parts list's sheets are built, 11.7); PDF/A with an
embedded single-stroke font; the Windows Share sheet; email routes for the CLI;
Hole Wizard records; STEP AP242 PMI; sheet metal; assemblies (views, balloons,
the BOM table); and the OCCT hidden-line accelerator question (section 25).

## 4. Where it sits

- **Library, `solidseas.drawing`.** Imports `solidseas.formats` (opening a
  document), `solidseas.tessellate`, `solidseas.errors` and `solidseas.model`.
  Nothing in it imports Qt, opens a network connection or writes outside the
  paths it is given.
- **Surfaces.** The CLI's `drawing` command, and the viewer, which calls the
  library in a child process and paints the display list with QPainter. REST
  routes are stage 4.
- **SOLIDWORKS, stage 3.** `solidseas.swapi` through the bridge, in the batch
  mode instance SolidSeas starts; never the user's session.

`make_drawing` runs these steps. Each is a module with a typed result, so each
can be built and tested alone:

1. **Source** (`drawing.source`): open read-only, pick the configuration and
   bodies, read units, material and properties, compute the file hash and the
   geometry digest (`DrawingSource`).
2. **B-rep model** (`drawing.facegraph`): tessellate once with the detail the
   views need, and build the face and edge graph (`BrepModel`).
3. **Features** (`drawing.features`): recognise features and the datum frame;
   account for every face (`FeatureSet`).
4. **Requirements** (`drawing.plan.requirements`): sizes, locations and angles
   for the manufacturing type and tolerancing scheme.
5. **View choice** (`drawing.plan.select`): front direction, projected views
   that cover the requirements, sections, requested details, isometric
   (`ViewSpec` list). A frozen view set from the drawing file takes precedence.
6. **Projection** (`drawing.views`, `drawing.sections`): hidden-line views,
   sections with hatching, centre marks and lines (`ViewGeometry`).
7. **Plan** (`drawing.plan`): the graphs, dimensions, callouts, frames, notes,
   title fields, view assignment and completeness (`Plan`).
8. **Layout** (`drawing.layout`): sheet, scale, arrangement, placement,
   furniture and stamps (`Sheet`, the painted display list, layout checks).
9. **Orchestration** (`drawing.orchestrate`): the loop between 7 and 8 when
   layout cannot place something: another view the planner listed, the other
   side, ordinate for a deep stack, a larger sheet (automatic sheet only), the
   key dimensions only when text still lands on text (10.10).
   Bounded to three rounds; its own module, owner and tests.
10. **Checks** (`drawing.checks`): the checklist of section 20.1 over plan and
    sheet.
11. **Writers:** PDF, DXF and SVG from the sheet; `.ssdrw` from the `Drawing`.

An edit changes the `Drawing` and re-runs the plan for the axis touched, the
layout for the view side touched, and the checks. A model change re-runs steps
1 to 10 with the frozen options and merges (section 13.5).

## 5. Package layout

| Module | Holds | Built by | Lines (estimate) |
|---|---|---|---|
| `drawing/__init__.py` | public API: `make_drawing`, `DrawingOptions`, `load`, `save`, `regenerate`, `write_pdf`, `write_dxf`, `load_settings`, `save_settings` | core 2, filled by integration | 200 |
| `drawing/limits.py` | every bound in `DrawingLimits` (section 17) | core 2 | 150 |
| `drawing/settings.py` | `DrawingSettings`, presets, the JSON file, per-value checks | core 2 | 750 |
| `drawing/standards.py` | sheet sizes, margins, zones, scales, line and text presets, the decimal blocks, ISO 2768-1 tables (for the millimetre option), AM process tolerances, thread, tap-drill and clearance tables, the revision letter sequence, the GD&T characteristic table | core 2 | 650 |
| `drawing/numbers.py` | value and tolerance formatting per unit and precision (section 10.8); unit guessing | core 2 | 450 |
| `drawing/fonts.py` | Helvetica and Helvetica-Bold widths (Adobe Core 14 AFM, APAFML notice), `measure` | core 2 | 300 |
| `drawing/source.py` | `DrawingSource` from a SOLIDWORKS `Document`; hashes and digests | core 2 | 250 |
| `drawing/facegraph.py` | `BrepModel` | core 2 | 550 |
| `drawing/keys.py` | geometric signatures and feature descriptors for matching | core 2 | 250 |
| `drawing/types.py` | the stage contracts (section 6) | core 2 | 650 |
| `drawing/display.py` | the display list and painted layer | core 2 | 500 |
| `drawing/painter.py` | the painter protocol; arcs, ellipses and B-splines to Béziers | core 2 | 250 |
| `drawing/svg.py` | the reference writer, internal (tests, previews) | core 2 | 300 |
| `drawing/pipeline.py` | `make_drawing`; stages by dotted path, a missing one a capability gap | core 2 | 200 |
| `drawing/views/` | `hlr.py`, `silhouettes.py`, `curves.py`, `cleanup.py`, `centres.py` | `dwg-views` | 2,500 |
| `drawing/sections.py` | full sections, snapping, hatching, detail clipping | `dwg-views` | 900 |
| `drawing/features/` | `holes.py`, `grooves.py`, `patterns.py`, `widths.py`, `blends.py`, `chamfers.py`, `pockets.py`, `inclined.py`, `frame.py`, `threads.py`, `hints.py`, `accounting.py` | `dwg-features` | 3,000 |
| `drawing/plan/` | `requirements.py`, `graph.py`, `angular.py`, `schemes.py`, `gdt.py`, `select.py`, `assign.py`, `values.py`, `callouts.py`, `notes.py`, `candidates.py` | `dwg-plan` | 4,300 |
| `drawing/layout/` | `sheet.py`, `arrange.py`, `dimension.py`, `place.py`, `index.py`, `titleblock.py`, `notes.py`, `glyphs.py`, `patterns.py`, `stamps.py`, `checks.py` | `dwg-plan` | 3,600 |
| `drawing/orchestrate.py` | the plan and layout loop | `dwg-plan` | 300 |
| `drawing/pdf.py`, `drawing/images.py` | the PDF writer; the narrow PNG reader | `dwg-pdf` | 1,200 |
| `drawing/dxf/` | `tags.py`, `tables.py`, `entities.py`, `dimensions.py`, `__init__.py` | `dwg-dxf` | 1,600 |
| `drawing/document.py`, `release.py`, `match.py`, `merge.py`, `locate.py` | `.ssdrw` read, write and bounds; status, signatures and revisions; feature matching; the regeneration merge; finding the model | `dwg-file` | 2,600 |
| `drawing/edit.py`, `drawing/checks.py` | edit operations; the checklist runner | integration | 1,300 |

The library's rules apply throughout: bounded loops, one clock, typed results,
and no private imports from `solidseas.tessellate`.

## 6. Data model

The parallel branches of stage 1 work at once only because the types between
stages are fixed first. **Decided:** they are fixed after the slice (section
3.2 step 3), not before, and revised once, when `dwg-plan` first draws o11 end
to end on the real types. Outside that checkpoint a branch may add optional
fields to a type it produces, and no branch changes or removes an existing
field.

### 6.1 What the tessellator adds (core 1)

Additive and opt-in:

- `tessellate_transmit(..., detail=True)` (and `tessellate_body`,
  `tessellate_document`) return a `Tessellation` whose new `detail` member is a
  `TessDetail`; with the default `detail=False` nothing changes.
- `TessDetail.edges`: for each `(body index, EDGE node id)`, the shared samples
  both faces used, float64 points in metres with the curve parameter of each,
  the two faces, and each sample's two face normals from the tessellator's
  exact normals. The edge classification of every view (front or back facing,
  the outline rule) needs these normals; inverting the surface at every sample
  in every view was 80 % of view time on a profiled 542-face part (measured,
  4.15 s a view for edge curves). Computed once per part.
- `TessDetail.face_uv`: the (u, v) of every vertex of each face, so silhouette
  refinement starts Newton there (refined mesh silhouettes took 0.86 to 3.0 s
  a view on free-form parts without it, measured).
- `TessDetail.points` and corner normals in float64, stored in `array('d')`.

Tests: `detail=False` output byte-identical to today's; edge samples on both
faces' triangles; (u, v) evaluating back to the stored point; edge normals
against surface evaluation; the bytes per triangle of the detailed call
(**target:** half the prototype's measured 4.7 KB a triangle for the whole
drawing child).

### 6.2 `DrawingSource`

`open_source(path_or_document, *, configuration=None, bodies=None, settings,
limits)` returns a frozen `DrawingSource`:

- `name` (file name only), `format`, `kind` (`brep`), `configuration`;
- `bodies`: name, type, face count, volume, selected;
- `units` with their origin (`file`, `guessed`, `user`) and, when guessed, the
  evidence: counts of sizes that are whole thousandths of an inch and whole
  hundredths of a millimetre;
- `material`; `properties` (effective, bounded); `hints` (KeyWords values, for
  ranking only);
- `sha256` of the file's bytes, `geometry_digest` (face signatures rounded to
  1e-7 m) and `properties_digest`;
- `warnings`.

Stage 1 accepts SOLIDWORKS parts, and assemblies ahead of stage 4
(`docs/drawings/assemblies.md`: views, the parts list and item balloons).
Drawings are refused with `not_implemented` (rule `drawing`); other formats with
rule `format_later`.

### 6.3 `BrepModel`

Faces with typed primitives, outward sense, area, loops, their triangles and
(u, v), and a signature. Edges with curve kind and parameters, samples with
parameters and normals, length, kind (`convex`, `concave`, `tangent` within 1
degree, `seam`, `open`) and signature. Vertices; axis groups (revolved faces
whose axis lines coincide within 1e-6 of the part's size); box, diagonal,
tolerance (1e-6 of the size); whether the shell is closed; and the skipped
faces with their reasons.

### 6.4 `FeatureSet`

Every feature has a descriptor (6.4.1), the face ids it claims, values in
metres and radians, and `exact` (false when a value came from a fit). Ids are
not part of the feature: the drawing assigns them (section 13.4).

| Type | Fields |
|---|---|
| `Hole` | axis; entry face and its kind (planar square, planar oblique, curved); ordered segments (`cylinder`, `cone`, `annulus`, `flat_bottom`, `drill_point`); kind (simple, counterbore, spotface, countersink, stepped, tapered and combinations); each end's state (`open`, `blind`, `into_bore`); full-diameter depth and its reference; angular cover; entry edge break if any; `thread` candidate; `needs_auxiliary` |
| `Pattern` | kind (`linear`, `grid`, `circular`, `arc`, `scattered`); member hole ids; count; pitches, or the pitch circle's centre, diameter and step; the first member's angle |
| `Boss` | axis, diameter, length |
| `Width` | the two faces; `material` (tab, rib, wall, thickness) or `gap` (pocket, slot, keyseat, groove); the size; the overlap share; what it is symmetric about, if anything |
| `Groove` | face groove: axis, inner and outer diameter, width, depth, the face it opens on |
| `Blend` | faces, radius, fillet or round, `derived` (a full-round end: radius equal to half a width), part of a hole entry |
| `Chamfer` | face, legs, angle, planar or conical |
| `Slot` | width, centre distance, end centres, direction, depth or through |
| `Pocket` | floor, walls, depth from the open face, corner radius, open sides |
| `Step` | planar face, axis, offset |
| `AngledFace` | face, angle to its principal plane, the meet line, whether the meet line is a virtual sharp (on a blend or chamfer) |
| `Frame` | three directions; datum faces A, B, C with the reason for each; extents |
| `FeatureSet` | all of the above; `unclaimed` (faces with area and reason: `free_form`, `needs_auxiliary`, `skipped`, `unrecognised`); coverage by feature count, face count and area; warnings |

`TurnedProfile` is added in stage 2.

#### 6.4.1 Descriptors

A descriptor is what matching compares between two versions of a model: the
type; the **size signature** (diameters, depth, segment kinds, through or
blind, width, radius); the **adjacency pattern** (the entry face's normal in
the datum frame, the kinds of neighbouring faces, member count); and the
**position** in the datum frame (axis point or face offset), in metres. It
never contains a Parasolid node id, because node numbers change on every save
and STEP and ACIS have no persistent ids.

Geometric signatures of single entities, used inside descriptors and by
`source.geometry_digest`:

| Entity | Signature |
|---|---|
| Plane face | unit normal (canonical sign) and offset along it, rounded to the model's tolerance |
| Cylinder or cone face | axis line (canonical point and direction), radius or half angle |
| Sphere, torus | centre, axis, radii |
| Straight edge | the two end points, unordered |
| Circular edge | centre, normal, radius |
| Vertex | its point |
| Other edges and faces | type, bounding box, length or area |

### 6.5 `ViewSpec` and `ViewGeometry`

`ViewSpec`: id; kind (`base`, `projected`, `section`, `detail`, `isometric`;
stage 2 adds `auxiliary`, `removed_section`, `broken`, `broken_out`);
direction and up; parent; letter; its own scale; hidden mode; tangent mode;
cutting plane or circle; `replaces` (the projected view a section stands in
for).

`ViewGeometry`: runs of curve with their source (edge or face id and curve
parameter range) and visibility; centre marks and lines; hatch loops;
`edge_visible`; `faces_true_shape`; `axes_end_on`; `axes_side_on`; and
`virtual_sharps` (construction points for meet lines on blends).

### 6.6 `Requirement`, `PlannedDimension`, `Plan`

- `Requirement`: key (section 13.4); kind (`size`, `location`, `angle`,
  `note`); the features it serves; the axis or angular graph; the value; the
  candidate dimension kinds; role (`envelope`, `feature_size`,
  `feature_location`, `pattern`, `form`); tolerance class (`block`, `basic`,
  `frame`).
- `PlannedDimension`: key and id; kind (`linear`, `diameter`, `radius`,
  `angle`, `ordinate`, `chamfer`, `hole_callout`, `leader_note`,
  `datum_feature`, `frame`); view (an attribute, not part of the key);
  references (feature ids and the faces or axes used); attach points; value;
  text parts (count, symbol, value, suffix lines, kept apart); precision and
  its source (`role`, `user`); tolerance (`block`, `basic`, explicit with type,
  or `reference`); the frame attached, if any; role; preferred side; the
  requirement keys it serves.
- `Plan`: views, dimensions, frames and datum symbols, centre items, notes,
  title fields, tolerance block text, the graphs and their results, coverage,
  and the tolerance-band summary.

### 6.7 The display list, the painted layer and the painter

One set of plain dataclasses in `solidseas.drawing.display` (no Qt, no I/O),
in sheet millimetres, origin at the sheet's lower left, y up. Model geometry
reaches the sheet through each view's transform (an orthographic rotation, the
view scale and the view's origin on the sheet).

Geometry primitives, each with `style` and `src`:

| Primitive | Fields | Exact for |
|---|---|---|
| `Segment` | `p0`, `p1` | lines; straight silhouettes of cylinders and cones |
| `Arc` | `centre`, `radius`, `start_deg`, `end_deg` (counter-clockwise) | circles and arcs in planes parallel to the view |
| `EllipseArc` | `centre`, `major` (a vector), `ratio`, `t0`, `t1` | circles in planes oblique to the view |
| `Spline` | `degree`, `knots`, control points, weights or none | B-spline edges: an orthographic projection is affine, so projecting the control points gives the exact projected curve, and a visibility split is a knot insertion |
| `Polyline` | `points`, `closed` | intersection curves, SP-curves, offsets, refined silhouettes, sampled to the chord tolerance |

`style` is one of `visible`, `hidden`, `tangent`, `centre`, `phantom`,
`border`, `thin`; writers map it to a layer, line type and weight from the
preset. `src` holds the body index, the edge or face signature and the view
id, so the editor can pick a feature.

Annotations (semantic, before layout): `Dimension` (id, kind, view, refs,
definition points as a DXF DIMENSION needs them, text position, value, text,
tolerance, precision, prefix, suffix, flags), `CentreMark`, `CentreLine`,
`Note`, `ViewLabel`, `DatumFeature`, `FeatureControlFrame`, `BasicBox` (a
style of `Dimension`), `Stamp`, `PlotStamp`, `VirtualSharp`; sheet furniture:
`Border`, `TitleBlock`, `Image` (the logo), `ProjectionSymbol`,
`ToleranceBlock`, `NotesBlock`.

The **painted layer** is what layout makes of the annotations: `Stroke`,
`Fill` and `TextRun` items with measured widths, each with its owner (the
dimension, note or view it belongs to). Layout also fits dash patterns per
primitive, so a hidden line starts and ends with a dash.

The **painter interface** that PDF, SVG and the viewer implement:
`begin_page(w, h)`, `set_stroke(width_mm, dash_mm, cap, join, colour)`,
`path(ops)` with `move`, `line`, `cubic` and `close`, `stroke()`, `fill()`,
`text(x, y, size_mm, angle_deg, string, font, anchor)`,
`image(x, y, w, h, data)`, `group(name)` and `end_group()` for layers,
`end_page()`. Arcs reach a painter as cubic Béziers (four per full circle,
error about 0.03 % of the radius), except the viewer's, which gets `arcTo`.
PDF, SVG and the screen draw only the painted layer, so they agree to a
hundredth of a millimetre; the DXF writer reads the semantic layer and replays
a dimension's painted items into its block.

### 6.8 The `Drawing`

The in-memory `.ssdrw`: options (frozen after the first save: manufacturing
type, profile, units, tolerancing scheme, schemes per view and axis, front
direction, view set, sheet, scale); the settings snapshot; title fields with
their origin (`part`, `list`, `typed`); the feature table (id, descriptor, and
decisions such as thread confirmations, depth references and datum letters);
dimension records (key, id, origin `generated` or `user`, state `shown` or
`removed`, placement relative to attach points, overrides, tolerance, frame);
notes; status, signatures and revision history; the source's identity; the
outputs written; and the laid-out sheet.

### 6.9 The pipeline and capability gaps

Stages are named by dotted path. A missing one answers `not_implemented` with
rule `stage_missing`, so core 2 is complete and testable alone and each branch
drives its own stage with hand-built inputs.

## 7. Settings

### 7.1 Where they live and how they are read

`%APPDATA%\SolidSeas\Drawing.json` on Windows (beside `Viewer.ini`), the XDG
and macOS equivalents elsewhere; schema `solidseas.drawing-settings/1`; at most
256 KiB; the library's strict JSON rules (no duplicate keys, no NaN); every
value checked on its own, falling back to its default with a problem listed;
written only by `save_settings`, through a temporary file and a rename.
`load_settings()`, `save_settings()` and `default_settings(profile)` are the
calls. The CLI takes `--settings FILE` and never writes settings.

**The logo.** The viewer's Choose... reads the image through `QImage`, scales
it to at most 1,200 pixels on the long side and writes an 8-bit RGB or RGBA,
non-interlaced PNG to `%APPDATA%\SolidSeas\Drawing\logo.png`, at most 512 KiB,
and the settings record its SHA-256. The library embeds only a PNG of that
narrow form whose hash matches; anything else is ignored with a problem, never
decoded further. On Linux the CLI accepts a logo in that form only.

### 7.2 What they hold

| Group | Values |
|---|---|
| Company | legal name, up to four address lines, phone, email or web, logo, CAGE code (optional), proprietary statement (an editable default in our own words), whether DO NOT SCALE DRAWING is printed |
| People and approvals | a list of people (name and initials, typed; nothing read from Windows); the approval rows the company uses (default DRAWN, CHECKED, APPROVED; ENGR, MFG and QA available); which rows Release requires (default CHECKED and APPROVED); whether one person may sign two rows (default yes, with a warning); date format (ISO 2026-10-04 or US 10/04/2026); the first revision mark (default A) |
| Standard | profile (ASME in stage 1); units (the part's own, inch, millimetre); the unit for parts that state none (asked on first use); upper-case notes |
| Sheets | default size (automatic, A to E), orientation, zones, the scales offered |
| Title block sources | the property names read for part number, drawing number, title, revision, model revision, material and finish (preset to common names); title style (noun first); weight shown or not |
| Tolerances | inch block (.X, .XX, .XXX, angles); millimetre block (X, X.X, X.XX, angles) or an ISO 2768 class; the precision per role (envelope, step, width, hole size, hole location, basic); the bands shown to the user |
| Geometric tolerances | the default scheme per manufacturing type (datum-referenced or plus/minus); position for holes and slots per role (clearance, tapped): inch Ø.010 at MMC, millimetre Ø0.25 at MMC; the general profile to A, B, C: inch .020, millimetre 0.4; for stage 2, runout .005 or 0.1 |
| Printing | per process, the fixed amount and rate in X and Y and in Z, labelled "service bureau figures; replace with your own" (section 10.6) |
| Notes | per manufacturing type, an ordered list of note templates with tokens (`{material}`, `{finish}`, `{process}`, `{layer_height}`, `{model}`, `{model_rev}`, `{model_hash}`, `{fillet_radius}`, `{profile}`); the edge-break text; the default surface finish (125 µin, 3.2 µm) |
| Materials | entries of: model names matched, callout, specification, density, manufacturing types, heat-treatable (asks for treatment and hardness) |
| Finishes | name, callout, manufacturing types, whether dimensions apply after it |
| Default views | per manufacturing type: views ticked, isometric, hidden lines, tangent edges, front direction |
| Dimensioning | per manufacturing type: scheme (baseline, ordinate); the ordinate switch (six tracks, 25 % of the view); hole callouts; thread suggestions; chamfer style (`leg X angle` or two legs) |
| Files | where drawings are saved (next to the part by default, or a folder the user chooses); the name pattern (`{number} {revision}`); whether Save keeps the preliminary PDF and DXF current (default on; the user allowed Save to replace the drawing's own files in Q14, section 12.6) |
| Email | method (Automatic, Webmail, Just show me the file; section 15.5); the webmail compose URL (default Gmail's); whether the subject is pre-filled (default on) |
| Limits | the drawing child's memory limit (3 GB by default, at most half the PC's memory); the face count above which Draft quality is used (2,000) |

A material matches when the model's material name, case-folded and with spaces
collapsed, equals one of an entry's model names; the first match wins. An
unmatched name is shown as it is, and is an error at release unless the user
accepts it as typed.

### 7.3 ASME presets (stage 1)

| Item | Inch | Millimetre |
|---|---|---|
| Projection | third angle | third angle |
| Sheets | A to E (A landscape by default) | same |
| Margins | A and B 0.38 in; C to E 0.50 in | same |
| Zones | letters up from the bottom, numbers leftward from the right, on every size (a setting) | same |
| Lines, thick and thin | 0.6 and 0.3 mm | same |
| Dimension and note text | 0.12 in (3.0 mm) | 3.0 mm |
| View labels; their letters | 0.18 in; 0.24 in | 4.5 mm; 6 mm |
| Title; drawing number; block labels | 0.18 in; 0.24 in; at least 0.10 in | 4.5; 6; 2.5 mm |
| Text direction | unidirectional, value in a break of the dimension line | same |
| Arrowheads | filled, length equal to the text height, 3:1 | same |
| First row; row spacing | 10 mm; 6 mm | same |
| Extension gap; overrun | 1.5 mm; 3 mm | same |
| Number format | no leading zero; decimals per tolerance class, trailing zeros kept | leading zero; trailing zeros kept where they select the tolerance under the decimal block |
| General tolerance | .X ±.030, .XX ±.010, .XXX ±.005, ±0.5° | X ±0.5, X.X ±0.2, X.XX ±0.05, ±0.5° (ISO 2768-m as an option) |
| Interpretation | DIMENSIONING AND TOLERANCING PER ASME Y14.5-2018, once, in the block | same |
| Count prefix | `4X` | `4X` |
| Labels | SECTION A-A; DETAIL B SCALE 4:1 | same |
| Scales | 1:1, 1:2, 1:4, 1:10, 1:20; 2:1, 4:1, 10:1, 20:1 | same |
| Edge breaks | BREAK SHARP EDGES .005-.015 | BREAK SHARP EDGES 0.1-0.4 |
| Revision letters | A, B, ... skipping I, O, Q, S, X, Z; after Y comes AA | same |

### 7.4 The snapshot in a drawing

A drawing keeps the settings it was made with, logo included, so a released
drawing reproduces exactly after the company changes its logo or block. "Use
Current Drawing Settings" is an explicit editor action that shows what changes;
on a released drawing it needs Start Revision first.

## 8. Views (`dwg-views`; view choice in `dwg-plan`)

### 8.1 Frame and directions

Front looks from +Z, Top from +Y, Right from +X, as in SOLIDWORKS. The frame
is the model axes when the largest planar faces align with them (89 % of
sampled parts and all 13 drawn parts, measured), otherwise the frame of those
faces.

### 8.2 Choosing the front view

Six directions times four turns, scored on true shape (features seen in true
shape), hidden features (one occluder query per feature centre), the longest
extent horizontal, and the natural position (a printed part's build plate at
the bottom); ties broken in a fixed order. The wizard shows the choice and its
reason, and the user can pick any of the six directions and a 90-degree turn.
After the first save the choice is frozen.

### 8.3 Which views

Greedy coverage: the front first; a requirement is covered in a view where its
feature is visible and in true shape, or where its axis lies in the view plane
with visible witnesses at both ends; add the projected view that covers most;
an internal feature asks for a section; the isometric when Settings say so.
Also:

- A section **replaces** the projected view that looks the same way, in the
  same position.
- Hidden lines for **one blind feature** are accepted instead of a section when
  its callout states its depth and nothing attaches to the hidden lines.
- Features on **inclined faces** are not covered by any principal view in true
  shape; stage 1 lists them as `needs_auxiliary` (section 8.11).

The view choice lives in `dwg-plan` with the coverage logic, because both use
the same witness rules.

### 8.4 The hidden-line engine

For each view direction `d` (from the part toward the viewer) with an up
vector:

1. **Curves to draw:** every B-rep edge, sampled on its exact curve (the
   tessellator's shared samples); the silhouettes of curved faces; tangent
   edges kept or left out by the setting, except where the tangent edge's
   normal is square to `d` (8.6).
2. **Occluder:** every triangle projected onto the view plane and binned in a
   uniform grid of about three triangles a cell; edge-on triangles dropped.
3. **Visibility:** points along each curve every 1/400 of the part's diagonal
   in the view plane. A point is hidden when a triangle covers it in front by
   more than a tolerance. Each change of visibility is bisected 12 times (to
   1/1.6 million of the diagonal).
4. **The own-face test.** A point on an edge lies on its own faces'
   triangles, so a naive ray hits them. Each curve carries the set of faces
   whose tessellation passes through it (for an edge, its two faces and every
   face at its end vertices; for a silhouette, its face and that face's
   neighbours). Hits on those faces count only when they lie more than 3
   chords in front; hits on any other face count from 1e-7 of the diagonal.
   A curved own face hiding the far rim of a hole is far deeper than 3 chords
   and is still found, and a concave silhouette is correctly hidden. This beat
   pushing the ray start off the surface, which fails wherever a feature is
   about as wide as the push.
5. **2D cleanup:** drop pieces shorter than 0.02 % of the diagonal; drop any
   piece lying within that distance of, and parallel within 3 degrees to, a
   kept piece of higher rank (visible before hidden). This removes back edges
   that project onto front edges, the edges of faces seen edge-on, and hidden
   lines under visible ones.
6. **Output:** each surviving run keeps its source edge or face and parameter
   range, so the writers emit the exact entity (8.8) and dimensions attach to
   real geometry.

The isometric uses the same engine with `d = (1, 1, 1)/√3`, visible runs only.
Hidden lines are off by default in every view; a view turns them on only when
a feature would otherwise be invisible in every view and no section is made.
On an assembly drawing, a part hidden behind others in every view has its own
hidden lines drawn, and no other part's, so its balloon has a line to point at
(`docs/drawings/assemblies.md`).

**Correctness tests use independent oracles:** synthetic `XtBuilder` parts
whose hidden-line drawings are known analytically (a box with a through hole,
a stepped block, a cylinder on a plate, a sphere on a block), compared run by
run; the fixture benchmarks (o02, o07, o11, o12); and, when SOLIDWORKS is
free, its own DXF views of the same synthetic parts, numbers only. Entity
shares are quoted per part (median and 10th percentile), never pooled.

### 8.5 Silhouettes

- **Cylinders and cones, analytic:** solve `n(u)·d = 0` in closed form for the
  generator angles, then clip each generator line against the face's boundary
  polygon in (u, v), counting crossings with a half-open rule so a boundary
  sample lying exactly on the generator is not counted twice (a real bug the
  prototype hit on o11). A cylinder seen along its axis has no silhouette; its
  circles are its outline.
- **Everything else, from the mesh:** on each triangle, find where
  `g = n·d` changes sign along its edges using the exact corner normals,
  interpolate, and chain the pieces by mesh edge.
- **Refinement**, for output only: one to three Newton steps on the exact
  surface, started from the vertex's stored (u, v).

### 8.6 Tangent edges

A setting: hidden (ASME default), thin, or phantom. **Rule found by
measurement:** wherever a tangent edge's common normal is square to the view
direction (within 2 degrees) it is part of the outline and is drawn visible
whatever the setting. Without the rule o11's right view lost 10 mm (12 %) of
its visible outline.

### 8.7 Centre marks and centre lines

From the axis groups, an axis whose faces cover at least 180 degrees of a circle
(a hole, a boss, a full round): seen end-on it gets a centre mark extending the
feature's radius plus an overshoot, seen side-on a centre line over its faces'
axial extent plus the overshoot (a setting, about 3 mm on paper). A fillet or a
broad curve covers less and gets neither: its axis may lie far off the part (a
curved face of some 300 mm radius once put a centre line that far from the part,
and its views went onto an E sheet). Circular patterns add a pitch-circle centre
line through the hole centres. The isometric gets none.

### 8.8 Output entities

Weighted by projected length on 183 sampled parts (measured): lines 98.6 %,
circle arcs 0.6 %, ellipse arcs 0.2 %, splines 0.5 %. 61 % of parts are drawable
entirely in lines, arcs and ellipses, 80 % at least 90 % so, and the 10th
percentile part 60 % so. So the DXF writer emits `LINE`, `ARC`, `CIRCLE` and
`ELLIPSE` for nearly everything, plus `SPLINE` or `LWPOLYLINE` for the rest.

### 8.9 Sections

Stage 1:

- A **full section** through a hole's axis when a callout cannot state its
  shape (stepped bores, internal grooves, holes that end in another bore),
  automatically; through a hole axis or a mid-plane on request.
- **Method.** (1) Cut the welded mesh with the plane: classify each vertex by
  signed distance, zero or more counting as the removed side everywhere, key
  each crossing by the mesh edge it lies on and chain pieces from where a
  triangle leaves the removed side to where it enters it, so on a closed mesh
  every loop closes without tolerance-based joining. (2) Snap each piece to the
  exact plane and surface intersection where a closed form exists (plane and
  plane: a line; a cylinder square to the plane: a circle; a cylinder with its
  axis in the plane: two lines; a cone or sphere square to its axis: a circle;
  otherwise the polyline with each point projected onto the intersection).
  (3) Hatch with thin parallel lines at 45 degrees, clipped to the loops by the
  even-odd rule, spacing a paper distance, the angle turned away from 45 when
  an outline runs at 45. (4) Draw what lies behind the plane with the same
  engine; the occluder keeps the triangles with any vertex behind the plane,
  and the cap hides what projects inside it; no hidden lines in a section.
- A loop that does not close (a mesh with a face missing) refuses the hatch and
  falls back to hidden lines, with the reason.
- Labels and cutting-plane lines per ASME; letters from one sequence for
  sections and details, without I, O, Q and X, never reused on a drawing.

Stage 2 adds half sections of hollow turned parts, removed sections through
cross features, broken views of long shafts and broken-out sections.

### 8.10 Detail views

Stage 1: on request in the wizard's views page and the editor, and suggested by
the checks when layout reports a cramped feature. A thin circle and letter on
the parent; the enlarged view at a preferred scale near it, not rotated. Only
size requirements, and locations whose witnesses all lie inside the circle,
move into the detail; other locations stay on the parent. Automatic details
(the layout asking for one) are stage 2.

### 8.11 Inclined features: auxiliary views in stage 2, reported in stage 1

Stage 2 adds the `auxiliary` kind: a primary auxiliary view projected normal
to an inclined planar face, aligned with its parent along the projection
direction, drawn as a partial view of that face and its features, labelled
VIEW A-A with an arrow when it must be moved; the planner gets a local 2D frame
on the face.

Stage 1 detects the same cases (a planar face square to no frame axis carrying
holes, slots or pockets; a hole whose axis is not a frame axis: 4.8 % of
sampled parts, measured), lists each as `needs_auxiliary` with its reason,
makes the drawing a reduced-dimension drawing, and says so on wizard page 1
before generating. The inclined face's own angle and meet line are dimensioned
in stage 1, with a **virtual sharp** (thin extension lines from both faces
crossing, with a dot) when the meet line lies on a blend or chamfer.

### 8.12 Speed and memory

**Measured** before the core 1 fixes: on a 34-part sample of parts up to 4 MB,
four views took 0.70 s median and 4.83 s at the 90th percentile, and read plus
tessellation plus four views 0.88 s median and 7.2 s at the 90th percentile.
Larger parts took much longer: free-form parts of 460 and 542 faces, 25.8 s and
29.1 s in all; 1,381 and 2,247 faces, 88.5 s and 103.7 s; 2,862 and 3,668
faces, 28.8 s and 15.9 s; 19,064 faces, 185.6 s with a 1,125 MB peak. The 13
distinct parts that the corpus's own 26 drawings reference (6 to 463 faces)
took 1.0 s median and 7.2 s at most from read to four views, with no face
skipped.

**Decided:** targets are set per size band (up to 100 faces, 100 to 500, 500 to
3,000, over 3,000) after core 1 is measured on the same parts. Until then these
**targets** stand:

| Set | Read to four views |
|---|---|
| the 13 drawn parts (primary acceptance set, PC only) | each under 5 s, median under 1 s |
| up to 100 faces | 90th percentile under 1 s |
| 100 to 500 faces | 90th percentile under 5 s |
| 500 to 3,000 faces (Draft above 2,000) | 90th percentile under 20 s |
| over 3,000 faces | finished within the 150 s cap in Draft, or refused before work starts with `drawing_too_complex` |

**Draft quality** (no silhouette refinement, a coarser visibility step, chord
2e-3 of the diagonal) is chosen automatically above the Settings face count.
Normal quality uses a chord of 1e-3 of the diagonal, and Fine 2.5e-4 (1.12
times the triangles at the median and 3.5 times at most, measured). The wizard
estimates the time from face and triangle counts before it starts and says so
for anything above 20 s.

**Memory:** about 4.7 KB a triangle in the prototype (1,125 MB at 235,551
triangles; 218 MB at 46,530; measured). The drawing child runs under a Job
Object limit of 3 GB (at most half the PC's memory). Triangles are capped at
400,000 in Normal quality; Draft coarsens the chord to stay under the cap; a
part still over it is refused. The editor's child releases its `BrepModel`
after five idle minutes and reloads it when a geometric edit needs it.

### 8.13 Bodies

All solid bodies of the configuration are drawn as one part. The wizard lists
them with names, face counts and volumes so a tooling body can be left out.
Sheet bodies are off. SolidSeas reads SOLIDWORKS' mark of a hidden body
(`body_hidden` in `formats/solidworks/parasolid.py`, which the STEP export
uses), so the wizard leaves hidden bodies unticked where the part says which
they are.

## 9. Feature recognition (`dwg-features`)

`features.recognise(model, frame_hint=None) -> FeatureSet`, from the face graph
and edge samples alone (no tessellation needed):

- **Holes.** A hole is a connected set of concave revolved faces on one axis,
  joined through the planar faces square to that axis that touch them
  (shoulders, flat bottoms). Coaxial cylinders of one diameter are merged (STEP
  and other sources split cylinders into seam halves), and the hole is complete
  when the union of their angular covers leaves no gap over 31 degrees (circle
  samples are at most 15 degrees apart). Classification: simple (one diameter);
  counterbore (two or more diameters with an annular planar shoulder); spotface
  (a shallow counterbore); stepped (diameters with no planar annulus);
  countersink (a cone of 60, 82, 90, 100, 110 or 120 degrees included);
  tapered (another cone); drill point (a 118-degree cone, within 6 degrees, at
  a closed end).
- **Hole ends.** Each axial end is classified by the faces across its end loop:
  a flat bottom or drill point is `blind`; a concave revolved face of another
  hole is `into_bore`; anything else is `open` only if a point just beyond the
  end on the axis lies outside the solid and a ray onward along the axis
  travels at least one hole diameter before meeting a face of another internal
  feature. THRU needs both ends `open`. An `into_bore` hole gets its
  full-diameter depth and a "confirm" flag. A hole entering a curved face is
  measured to where the full diameter starts, and flagged. A partial hole gets
  Ø above 180 degrees of cover and R at or below; concave revolved faces under
  180 degrees are fillets and slot ends, not holes.
- **Face grooves:** an annular planar floor with a coaxial concave outer wall
  and convex inner wall, opening on a planar face, is a `Groove` (inner and
  outer diameter, width, depth), never a hole or counterbore.
- **Patterns:** full holes grouped by signature (kind, diameters, depth,
  through or blind, axis direction), then tested in order: circular (centres
  equidistant from the circle through three of them, within 1e-5 of the size),
  linear (collinear), grid (an axis-aligned lattice), otherwise scattered.
  Every member of a scattered group is located.
- **Widths:** for each frame axis, pairs of antiparallel planar faces whose
  projected footprints overlap and which face each other directly (a ray from
  sample points of one meets the other first over at least half of the
  overlap). Normals pointing apart bound material (tab, rib, wall, flange,
  thickness, and the envelope itself); pointing toward each other they bound
  space (pocket, keyseat, open slot, groove). Pairs are ranked by overlap share
  and then by smaller width, and accepted greedily while the implied links stay
  a forest, so stepped interlocks cannot make a cycle; the rest stay plain
  positions. A pair symmetric about a datum plane or another feature's centre
  plane records it.
- **Bosses and shafts:** convex cylinders grouped by axis.
- **Blends:** a curved face (cylinder, torus, sphere, cone or B-spline) with at
  least two tangent edges to different faces that is not a complete cylinder.
  The radius is exact for cylinders, tori and spheres, a circle fit across the
  face for B-spline blends. A blend whose radius is half the width between its
  two tangent parallel faces is a full-round end, `derived`. Entry rounds and
  chamfers belong to their hole.
- **Chamfers:** planar, a narrow planar face (under 10 % of the part's size)
  between two planar faces, with both long edges sharp and convex and angles to
  its neighbours summing to 90 degrees within 1 degree; conical, a complete cone
  of 20 to 70 degrees half angle between convex edges.
- **Slots:** two concave half-cylinders (150 to 210 degrees) of equal radius
  with parallel axes, joined by two planar walls tangent to both and facing
  each other 2r apart. (A looser rule, any tangent plane between two equal
  concave cylinders, mostly found fillets in pocket corners.)
- **Pockets and steps:** a pocket floor is a planar face whose sharp edges are
  all concave; a step or open pocket is a planar face with both concave and
  convex edges. A pocket's depth is from its open face.
- **Angled faces:** planar faces square to no frame axis; the angle to the
  nearest principal plane; the meet line, marked as a virtual sharp when it
  falls on a blend or chamfer.
- **Inclined features:** holes, slots and pockets on an angled face, and holes
  whose axis is not a frame axis, are marked `needs_auxiliary`; in stage 1
  their faces count as unclaimed with that reason.
- **Frame and datums:** model axes or the face frame; A the largest planar
  face, B the largest square to it, C the largest square to both, each with its
  reason recorded so the wizard can say it. Once a drawing exists its datums
  follow matched faces, never "the largest" again.
- **Threads:** candidates only, from Unified and metric tap-drill,
  major-diameter and clearance (ISO 273) tables. Nothing becomes a thread note
  until the user confirms it. SOLIDWORKS keeps Hole Wizard and cosmetic thread
  sizes in a binary feature stream SolidSeas has not decoded, so the files
  almost never say.
- **Hints:** KeyWords dimension values rank alternatives (a distance equal to
  an extrusion depth, a radius equal to a fillet's value), matched by value
  only; they never supply a value.
- **Accounting:** every face is claimed by a feature, is a position (a step or
  envelope face), or is unclaimed with a reason. Coverage is reported by
  feature count, face count and area.

`BLENDED_EDGE` faces: the tessellator draws most of them now (`docs/API.md`
3.15; 3,185 of the 4,280 rolling-blend faces on the corpus, `docs/OCCT.md`
7.9), and views and sections no longer leak through the ones it draws. A blend
it leaves out for time (`max_seconds`) or refuses with a reason (`fit_failed`,
`unsupported_curve`) still leaves a gap there, which the wizard warns about as
it does any skipped face. Recognising them as blends with a radius is
`dwg-blends` (stage 4); until then they stay unclaimed and the wizard warns
before generating. **Target:** recognition within the measured median of 7 ms
and a 20 s cap (worst measured 13 s).

## 10. Dimensioning (`dwg-plan`)

### 10.1 Requirements

`plan.requirements(features, process, scheme, options) -> [Requirement]`:

| Feature | Size requirements | Location requirements | Where drawn |
|---|---|---|---|
| Envelope | the overall size per axis (a `Width` of material) | its walls are positions | views with that axis in their plane |
| Width or gap | its size, once | one wall, or its centre plane when symmetric | where both walls are edge-on and visible |
| Step | none | the face's offset | where the face is edge-on |
| Hole or hole group | one callout (count, Ø, THRU or depth, counterbore or spotface, countersink, confirmed thread); under the datum scheme a position frame | the axis on both frame axes square to it, for every member of a scattered group, and the first member of a linear, grid or circular pattern | callout and locations in the circular view |
| Linear or grid pattern | pitch per direction with its count | first member | with the callout |
| Circular pattern | pitch-circle Ø, equal spacing or the step | the centre; the first member's angle to a datum plane (angular graph) | circular view |
| Boss | Ø (a position frame under the datum scheme); equal bosses on one axis once, `nX Ø`, on the first of them | its axis | side view on the generators, or circular view by leader |
| Slot | width (`2X R` without a value at the ends when derived), centre distance, depth when blind | centre line across, one end centre along | the view square to its depth |
| Pocket | corner radius, depth from the open face (flip per feature); equal depths between the same two planes once, `nX` on a note, on the first of them | its walls, through its `Width` features | plan view; depth in an edge view |
| Face groove | inner or outer Ø, width, depth | its axis | where it is circular; depth in a section or edge view |
| Fillets and rounds | the most common radius in one note; others `nX R`; derived full-round ends "R" without a value | none | where the blend's axis is end-on |
| Chamfer | `leg X angle` or two legs, grouped | none | where it is a line at its angle |
| Angled face | its angle; equal angles to one principal plane whose meet lines run along one axis once, `nX`, on the first of them | the meet line, with a virtual sharp when needed | where the face is edge-on |
| Sphere | SØ or SR | centre | |
| Needs auxiliary | none in stage 1 | none in stage 1 | listed, covered by the model-governs note |

### 10.2 Completeness and non-redundancy: the linear graph

For each frame axis:

- **Positions:** distinct offsets of planar faces square to the axis; axes of
  holes, bosses and pattern representatives (every member of a scattered
  group); slot and width centre planes; angled-face meet lines; sphere and arc
  centres; and tangent and silhouette extremes of cylinders, spheres and arcs.
  Each records its witnesses (the views where it is a visible line). Positions
  merge within the model tolerance, but hole axes of different features merge
  only when a drawn centre line joins them.
- **Implied links** (contracted into one node): counterbore and blind depths;
  slot widths; `Width` sizes; pocket depth from the open face; pattern pitches
  and pitch circles; each centre to its tangent extremes by r.
- **Drawn edges:** candidate linear dimensions between two nodes where both
  ends have visible witnesses. Cost: 1, plus a small amount for a view other
  than the front, plus extension length over the diagonal, plus 0.2 for a
  silhouette witness, minus a little for a KeyWords match, **times 0.5 for an
  edge the previous plan used** (hysteresis, for regeneration). The user's own
  dimensions are fixed edges.
- **Origin:** the datum B or C plane for its axis (A for the axis square to
  it), or the user's choice, a centre plane included.

**Complete** means every node is connected to the origin. **Not redundant**
means the drawn toleranced dimensions form a tree over the contracted nodes. A
closing dimension is a reference in parentheses, or is not drawn. An overall
dimension to a tangent extreme whose centre is located elsewhere is a
reference. Sizes that are not edges (Ø, R, angles, chamfers, callouts) appear
exactly once per requirement key, a group once with `nX`; the duplicate check is
keyed on requirement keys, never on equal values. A merged position whose faces
are not one continuous visible line gets a count or an extension line to each.

This graph is the planner's tool and the editor's checker. It is not the
tests' only oracle: the reconstruction test (section 19.3) is written
separately.

### 10.3 The angular graph

`plan/angular.py`, stage 1: for each pitch circle, a node per member angle and
one angular origin (a datum plane through the centre, or a flat); implied links
for equal spacing; 0°, 90° and 180° implied only where the drawing shows the
relationship (a member on a centre line parallel to a datum); the same
complete-and-acyclic test. A first member off the principal axes gets its
angle. An arc pattern, which does not close its circle, also needs its step,
stated once with the count of spaces. Stage 2 extends it to axes of revolution (cross holes, flats, keyseats)
and angled-face sets.

### 10.4 Arrangement schemes

- **Baseline (default):** each node joined to the origin when drawable, else by
  the cheapest drawable path (Dijkstra); a tree. Baseline limits the stack
  between two features to the sum of their two tolerances; it does not remove
  accumulation altogether.
- **Ordinate:** the baseline tree drawn as ordinate dimensions from a `0`
  origin in one view per pair of axes. The planner switches a view and axis to
  ordinate when one side would need more than six tracks or a band deeper than
  25 % of the view (both Settings values), and the wizard previews it.
- **Chain:** stage 4. **Hole table:** stage 4, offered after ordinate for more
  than about 20 holes.

Under the datum scheme both baseline and ordinate dimensions are basic.

### 10.4a Detail level

A part's drawing says as much as the person asks, chosen beside the tolerancing
scheme in the wizard (`DrawingOptions.detail`, `--detail` on the command line):

| Level | What is drawn | What is checked |
|---|---|---|
| Simplified | the views the part needs, its overall size, and each hole, boss and hole pattern by size (with its count, such as 4X); nothing located; no datums or GD&T; the reduced-dimension note saying the model defines what is not dimensioned (10.10) | sizes as for any drawing; `R4.complete`, `R4.members` and `COV.unclaimed` are information |
| Complex | every feature sized and located, plus and minus tolerances (the scheme defaults to plus/minus) | as for Simplified |
| Fully defined | everything 10 asks: every feature sized and located, datums and GD&T as the scheme says | everything, and the reconstruction proves the part fully defined (the default) |

The level is kept in the `.ssdrw` options as `detail`, written only when it is not
`full`, so a fully defined drawing's file is as it always was. A new drawing starts
at Drawing Settings' default level (`defaults.detail`, on the Dimensioning page;
`full` unless changed), in the wizard and on the command line when `--detail` is
not given. A person who chooses a scheme keeps it at any level. An assembly's
drawing has no level: its only dimensions are its overall size, for reference
(`docs/drawings/assemblies.md`).

### 10.4b Drawing modes

The viewer's Drawing button and Make Drawing entries ask how the drawing starts
(`solidseas_app/viewer/drawingmode.py`), unless the viewer's `drawing_mode`
setting already names one ("Remember my choice", or Settings > Drawings):

| Mode | What it does |
|---|---|
| Express | Makes the drawing with no questions and opens it in the editor (`solidseas.drawing.express`) |
| Guided | Asks the wizard's main choices as plain questions, one at a time, then writes the drawing and opens it in the editor (`solidseas_app/viewer/drawingguided.py`) |
| Expert | The New Drawing wizard of 15.3, unchanged |

An Express drawing is the simplified level with `DrawingOptions.mode` set to
`express`. It draws:

- the views the part needs for what it states, and the isometric;
- the overall length, width and height;
- each hole and hole pattern by size, with its count (`express_keeps`);
- a pattern's pitches, pitch circle and clocking angle;
- each hole, and each pattern by its first member or its centre, located from
  the datum edges (`express_graphs`: the location graph cut down to the origin
  and the hole centres, joined by the links the patterns imply).

It has no datums or GD&T, no sizes of bosses, slots, steps, chamfers or
fillets, and no notes but the model-governs note of 10.10, which names the
model in capitals (and, on a printed part, the process note its tolerance block
points at). Its title fields come from the part (`notes.title_fields`), with
DRAWN signed by the first person of the People list (`express_fields`) and the
finish list's NONE where the part names no finish. The viewer writes only the
`.ssdrw`, next to the part or in the Drawing Settings folder under 12.6's rules.

Checks: on an Express drawing, before release, `R13.plusminus`, the edge-break
and fillet findings of `R14.notes` and a missing template note of `R15.process`
are information, and an empty MATERIAL, FINISH or DRAWN (`R6.title`) is a
warning (`checks.EXPRESS_INFORMATION`). At release every check has its usual
level. The other modes' checks are unchanged.

The mode is kept in the `.ssdrw` options as `mode`, written only for an Express
drawing, so every other drawing's file is as it was. A SolidSeas that does not
know the member keeps it as an unknown option and draws the simplified level;
a value this SolidSeas does not know falls back to `expert` with a problem
reported. Update from Model keeps the mode. An assembly's Express drawing is
its usual drawing.

A Guided drawing is the wizard of 15.3 with its own pages: `GuidedWizard` is a
`DrawingWizard` that shows one question a page, each with a sentence on why it
matters, and keeps the wizard's other pages, unshown, as the store of the
answers, so the request, the preview beside the pages, first use and Finish are
the wizard's. The questions, in order:

| Question | What the answer sets |
|---|---|
| What is the drawing for? | the manufacturing type and the detail level: to show a customer or get a quote, machined and Simplified; to have it 3D printed, printed and Simplified, with the printing process chosen from Drawing Settings (off, with the reason, when Settings list none); to have it made from plain sizes, machined and Complex; to have it machined in a shop, machined and Fully defined. It starts at the purpose of Drawing Settings' default level (`defaults.detail`) |
| Which views should the sheet show? | the projected views and the isometric, starting from Drawing Settings' Default Views for the manufacturing type; a change is the user's choice, kept when the purpose changes, as in the wizard |
| Which unit should the sizes be in? | `units`: Inch or Millimetre, starting at Drawing Settings' fixed unit, else the unit the part states, else the guess when its evidence leans one way (`UnitGuess.decided`); an unclear guess waits for a click, and no preview is made before it. The unit the part or Settings give anyway is sent as `part` |
| How much should the drawing dimension? | `detail`, as the first answer set it; the scheme is `plusminus` below Fully defined and Drawing Settings' scheme for the manufacturing type at Fully defined |
| Are any of these holes threaded? | the thread answers of the wizard's page 5, for the thread candidates the preview finds (`drawing_thread_candidates`: holes and hole patterns whose diameter is a tap drill). Each hole is "No, a plain hole" or "Yes" with one of the threads its drill taps, written to the wizard's own thread table as Plain or Tapped, so the request carries the same `confirm_thread` edits (with no thread depth) as the wizard's. Asked only when the preview shows a candidate: before the first preview the page waits, saying so, and once a preview shows none it is skipped. If the preview fails, the page says the holes could not be checked and lets the user go on |
| What should the title block say? | the wizard's own title block page |
| Ready to make the drawing | nothing: it says what will be made (the answers, and the title block as the preview shows it), where the files go, with a button for another folder, and ticks for a PDF (on) and a DXF (off) beside the `.ssdrw`. Finish writes them under 12.6's rules and opens the drawing in the editor |

An assembly is not asked what it is for, how much to dimension or about
threads: its drawing has its views, its parts list and balloons, and its overall
size for reference. Hidden lines, tangent edges, the front, the sheet and the
scale are left to Drawing Settings and SolidSeas, as for Express. Of the wizard's
page 5, Guided asks only the thread question: a thread's depth is not asked (the
callout gives none), and a hole end that needs confirming is confirmed from the
editor's checklist. The summary lists the holes answered as threaded. A Guided
drawing's options carry no mode: it is an ordinary drawing, and its file is the
one the wizard would write for the same choices.

The viewer has one New Drawing wizard open at a time, Expert or Guided. Starting
another drawing while one is open brings it forward and says which is open: "A
New Drawing wizard is already open" for Expert, "A Guided drawing is already
open" for Guided.

### 10.5 Tolerancing schemes

**Datum-referenced** (the default for machined parts, the user's answer to Q1):

- Datum feature symbols A, B and C on the datum faces, attached in a view where
  each face is edge-on and visible (or on an extension line), placed by layout
  like a leader item.
- Locations of holes, slots, bosses, widths and steps from the datums are
  **basic** dimensions (boxed).
- Each hole or slot callout carries one position frame: Ø (for round holes) and
  the Settings value for its role, at MMC by default, to A, B and C. A
  pattern's callout carries one frame for the group.
- Sizes (hole Ø, widths, boss Ø, pocket depth) keep their own tolerance, from
  the block or explicit.
- One general note governs every surface not otherwise controlled: in our
  wording, UNLESS OTHERWISE SPECIFIED, ALL SURFACES followed by a profile of a
  surface frame with the Settings value to A, B and C. It also gives the
  model-governs note its tolerance.
- **Verify** with the user's review of the goldens: how the general profile
  interacts with a planar width whose size is toleranced separately. Default:
  the size tolerance governs size and the profile governs location.

**Plus/minus** (an option per drawing): baseline or ordinate locations
toleranced by the block. `R13.plusminus` warns that Y14.5-2018 discourages
plus/minus tolerances for relationships between features (a public summary
reports that the 2018 edition removed them from its figures and kept them only
in an appendix showing their ambiguity). When the drawing needs a
model-governs note, datum symbols A, B and C are added anyway so the note can
reference them.

**3D printed parts:** plus/minus under the process note by default, because a
service bureau's accuracy is a size-dependent plus/minus that one profile value
cannot state; the datum scheme is an option.

**Turned parts (stage 2):** datum A on the diameter the user picks (default the
longest cylindrical segment), B on the datum end face; circular runout to A on
every other diameter from Settings (total runout as an option).

**In the editor:** a frame editor in Properties (characteristic among position,
profile of a surface, perpendicularity, parallelism, flatness, circular and
total runout; value; Ø; MMC, LMC or none; up to three datum references with
modifiers) and `set_datum(face, letter)`.

**Checks:** `R3.basic`, `R18.datums`, `R18.frames`, `R13.plusminus` (section
20.1).

### 10.6 Strategies by manufacturing type

- **Machined (milled), stage 1:** frame datums as A, B, C; the datum scheme;
  baseline with the ordinate switch; hole callouts with frames; precision by
  role (inch: two places for envelope, steps and non-critical widths, three for
  hole sizes and bores; millimetre: one and two), shown as bands; notes from
  the machined set (edge break, fillet note, default finish, finish and
  coating, dimensions apply after finish). The interpretation and units
  statements live in the block only.
- **3D printed, stage 1:** views as machined; the build-direction arrow on the
  isometric and on every orthographic view that carries Z dimensions; the
  title block's table replaced by "GENERAL TOLERANCES: SEE NOTE n" with the
  units statement kept; values shown as nominals (inch to three places or as
  needed, millimetre as needed); the process note names Z as the build
  direction; full coverage (the machined rules); notes: the process in
  ISO/ASTM 52900 terms, material, layer height, infill and walls (recommended
  or required), orientation, supports, post-processing, dimensions apply after
  post-processing; tapped holes become "tap after printing" or heat-set insert
  notes by the user's choice. Default process figures, labelled as service
  bureau figures for the business to replace: SLA ±.002 in in X and Y and
  ±.005 in in Z, each plus 0.1 % of the nominal; PolyJet ±.005 in plus 0.1 %;
  SLS ±.010 in plus 0.1 %; MJF ±.012 in plus 0.1 %; metal powder bed X and Y
  ±.003 in plus 0.1 %; FDM about ±0.5 % with a ±0.5 mm floor.
- **Turned (lathe), stage 2:** the profile view, axis horizontal, larger end
  left; one size requirement per cylindrical segment, "2X Ø" only when the
  dimension visibly attaches to both; diameters stacked largest outermost;
  axial positions from the datum end face; external diameters and shoulders at
  three places; half sections for bores with the one-arrowhead diameter style;
  removed sections for keyseats, flats and cross holes; keyseat depth from the
  opposite side in its section; broken views above a length-to-diameter
  setting (about 8); across flats on hex and square ends; runout to A; surface
  texture symbols on bearing and seal diameters; notes from the turned set.
- **Mixed (stage 2):** turned rules for the revolved faces, machined for the
  rest.

The wizard suggests a type from the geometry and says why. In stage 1 a part
that looks turned (every revolved face on one axis and every plane square to
it: 6.9 % of sampled parts and none of the 13 drawn parts, measured) gets the
machined rules with a message that turned drawings come in release 1.1.

### 10.7 Which view each dimension goes in

True shape with visible witnesses first; then the view already holding the
feature's other dimensions; then the less crowded side; then the front.
Callouts go in the circular view at the instance whose leader is shortest and
clear. Nothing attaches to a hidden run. The view is an attribute of the
dimension, so moving it to another view keeps its identity.

### 10.8 Values, precision and tolerance display

Values are exact from the B-rep, converted from metres (1 in = 25.4 mm exactly)
and formatted by `drawing.numbers`.

- **Nominals:** inch without a leading zero, decimals equal to the precision
  (which selects the tolerance under the block); millimetre with a leading
  zero, trailing zeros kept under the decimal block where they select the
  tolerance, dropped under ISO 2768 or a process note, where the nominal is
  shown to the precision needed to state it exactly.
- **Explicit tolerances**, in our words: inch values and their tolerances carry
  the same number of decimals, a zero deviation included (".500 +.005 -.000");
  in millimetres a zero deviation is a single 0 with no sign and the other
  deviation keeps its sign and decimals; limits are stacked with the upper
  limit above; symmetric tolerances use ±; MAX and MIN follow the value;
  angles carry the degree sign on value and tolerance; basic values are boxed
  and carry no tolerance; references are in parentheses.
- **The rounding guard:** when a toleranced value as shown differs from the
  model by more than 10 % of its band, the precision is **not** changed;
  `R2.rounding` offers: keep (the drawing governs, and the model value lies
  inside the band, which the check states); increase the precision (showing
  the tighter band that brings); or give an explicit tolerance. More decimals
  than the block's last row need an explicit tolerance (`R3.block`, an error).
  Basic dimensions gain decimals automatically, up to four (inch) or three
  (millimetre), because their decimals select no tolerance.
- **Bands:** the wizard's page 5 and the editor show how many dimensions fall in
  each band ("23 at ±.010, 14 at ±.005") and each value's band; `R3.roles`
  lists role-assigned precisions until CHECKED is signed.

### 10.9 Callouts and notes

Hole callouts in manufacturing order: count and Ø, THRU or depth; the
counterbore or spotface line; the countersink line (diameter at the surface and
included angle); a confirmed thread line with its depth; then, under the datum
scheme, the position frame. For example, in ASME practice: `4X Ø.266 THRU`
with a second line for the counterbore, its Ø.438 and depth .250; or
`2X Ø.201 ↧ .62` with `1/4-20 UNC-2B ↧ .50` below. Blind depth is to the full
diameter, never the drill point. A hole's entry round or chamfer larger than
the edge-break range is an extra callout line or a local note, never a reason
for a section. An `into_bore` hole shows its depth and, if the user picks it,
a note that it runs through to the bore. Symbols are glyphs, with `CBORE`,
`CSK` and `DEEP` text as a setting for DXF readers whose fonts lack them.
Thread depth is suggested as the drill depth less three pitches, rounded down,
and confirmed by the user. The generator never writes TYP: repetition is `nX`.

`plan.notes` fills the note list from the type's templates, computes the fillet
note's radius, adds the general profile note under the datum scheme, adds the
model-governs note when needed, and derives the title fields: from the wizard,
else the part's properties under the configured names, else the file name;
material through the mapping table; weight from the volume and the material's
density, labelled CALC WT with its unit.

### 10.10 The model-governs note and coverage

When anything is unclaimed (free-form, needs auxiliary, skipped,
unrecognised, model defined), the drawing is a **reduced-dimension drawing** and
carries a note that, in our wording:

1. identifies the model by part number, model revision (from its property or
   typed in the wizard) and the first 16 hex digits of the file's SHA-256,
   which also appear in the title block's MODEL field;
2. says that the dimensions shown take precedence over the model;
3. gives every undimensioned surface a profile tolerance to A, B and C (the
   general profile value, or a separate Settings value for undimensioned
   surfaces).

`COV.unclaimed` is a warning that blocks Release until the user accepts it with
a typed reason. The wizard and editor say "reduced-dimension drawing: 7 faces
(3 % of the area, 2 features) are defined by the model" rather than "fully
dimensioned". A resave of the model that leaves the geometry unchanged still
changes the hash; the drawing then says "model file changed, geometry
unchanged" and the fix is a new revision or keeping the old reference.

**Key dimensions only** (`plan/keep.py`). A part whose plan asks for more
dimensions than a sheet shows clearly (more than 60, about what the corpus's
sheets show clear of each other) gets a drawing of its key dimensions: the
overall size, the datums, the holes and their patterns with their locations,
every feature the user has made a choice about and every feature the drawing's
own dimensions name (one the user added, moved, overrode or removed, so a
re-plan never leaves it to the model), whatever the count; then the other
features and the planar faces no feature claims, larger first by the area of the
faces that state or place them (a pocket's floor, not the walls standing on it;
a pocket goes with the widths across it), while the count keeps within the
budget. What is left is unclaimed as **model defined**: the planner neither
states nor locates it, and the drawing is a reduced-dimension drawing like any
other. The count is the full plan's, as drawn: a need it stated, a location to a
node it reached, a datum symbol it drew. A layout that still puts text on text
(more than three collisions, and a twentieth of its dimensions or more) is laid out
once more with three fifths of its dimensions, kept when it collides less.

**Engraved lettering** is left to the model whatever the budget: three or more
pockets cut to one depth from one plane, at least half of them with a free-form
wall (a font's outline), none the user has chosen anything about or named, none
holding a datum's face, and the features standing only on their faces (the
strokes' widths, steps and slopes). Their walls are unclaimed as model defined;
their floors stay planes, so the depth they share is stated once with their count
(`16X ↧ 0.4` on a note in the plan view), not a leader to every letter.

### 10.11 What the planner refuses or flags

More than the requirement bound stops adding dimensions, suggests ordinate and
lists what was left. A requirement no view can show visibly is listed with its
reason. The planner never invents a value, a tolerance value the Settings do
not hold, a datum the user has not seen, or a thread.

### 10.12 Editing (`drawing.edit`)

Each operation returns a new `Drawing` and its checks:

| Operation | Effect |
|---|---|
| `remove(id)`, `restore(id)` | a generated dimension's state; kept in the file so regeneration keeps it removed |
| `delete(id)` | a user dimension is gone |
| `candidates(features)`, `add(candidate)` | the planner's candidate dimensions for one or two picked features (distance, diameter, radius, angle, depth, width), and adding one as a user dimension; free picking of arbitrary edges is stage 4 |
| `link(a, b)` | replace feature b's link to the datum with a direct dimension from a, keeping the tree; shows the resulting stack |
| `set_origin(axis, face or centre plane)` | re-plans that axis from a new origin |
| `set_scheme(view, axis, scheme)` | baseline or ordinate |
| `set_depth_reference(feature, face)` | pocket or blind depth from the open face or the floor |
| `set_tolerance`, `set_precision` | per dimension; precision changes show the new band |
| `set_prefix`, `set_suffix` | count, notes and suffix lines, kept apart from the value |
| `override_value(id, text)` | allowed with `R2.override` (an error until acknowledged, blocks release) and a badge |
| `set_frame(id, frame)`, `set_datum(face, letter)` | the GD&T layer |
| `move`, `flip`, `reset_position` | placement relative to attach points |
| `set_sheet`, `set_scale`, `set_units` | for this drawing; re-lays out |
| `add_view(detail or section)`, `remove_view` | sections 8.9 and 8.10 |
| `set_tolerance_block`, `edit_notes`, `add_flag_note(note, items)` | per drawing; the settings snapshot otherwise unchanged |
| `confirm_thread(feature, spec)`, `confirm_end(feature)` | user decisions stored on the feature |
| `sign(row, person)`, `release()`, `start_revision(description)` | section 13 |

After each operation the checker recomputes the graph touched (milliseconds)
and reports in words, with fixes: "4X Ø.266 holes are no longer located along
X" (Restore, Add); "This dimension closes a loop with 2.000 and .750" (Make
Reference, Remove the Other, Link Instead). A redundant dimension the user
insists on stays, flagged as an error.

## 11. Layout, sheet and title block (`dwg-plan`)

### 11.1 Sheet, scale and arrangement

1. **Bands.** For each view and side, the planned dimensions are coloured into
   tracks (span widened by the text box); band depth is the first offset, plus
   the row spacing per extra track, plus a text height. A side over the
   ordinate threshold goes back to the planner.
2. **Arrangement.** Third angle: the front anchors; projected views aligned on
   their shared axis; the gap between views the sum of the facing bands plus
   two text heights. The isometric goes in the free area above the title block,
   clear of the revision block. Reserved areas: title block (lower right),
   revision block (upper right), notes block, projection symbol, the stamp band
   in the border.
3. **Scale and sheet.** The largest preferred scale at which the views and
   their bands fit the drawing area. With an automatic sheet, sizes are tried
   smallest first and the first that fits wins; the smallest-feature test counts
   only features dimensioned with extension lines (leader-dimensioned chamfers,
   radii and callouts are left out). Features that stay cramped are reported
   with "Add Detail View" and "Sheet and Scale" as the fixes; on a sheet the
   user chose, views that fit at no scale are reported as needing a larger
   sheet. Frozen after the first save.

### 11.2 Painting

Extension lines with gap and overrun; filled arrowheads; unidirectional text in
a break of the dimension line; arrows and text outside when cramped; radial
leaders on circles; linear Ø on profile views; arcs for angles; ordinates with
jogs; callouts at a leader's shoulder; leaders inclined 15 to 75 degrees. Plus:
datum feature symbols (a framed letter on a leader to a triangle on the face or
its extension); feature control frames (cells for characteristic, zone and
modifiers, datum references); basic boxes; virtual sharps; the simplified
thread representation for confirmed threads (the major diameter hidden in the
end view of a tapped hole); the build-direction arrow; and the PRELIMINARY
stamp.

### 11.3 Placement without collisions, and its speed

A spatial index of hard and soft conflicts. Placement order: obstacles first,
then user-moved dimensions, then callouts and radial dimensions most
constrained first, then linear dimensions per side shortest span first, then
angular and ordinate, then the notes block. A dimension is never dropped
silently. For speed:

- candidates are generated in order of their cheapest possible soft cost; the
  search stops at the first candidate with no hard conflict and zero soft cost,
  and a candidate is rejected on the first hard conflict found;
- for a pattern, only the two or three instances nearest free space are tried;
- a leader item with no clear place gets a closer look (finer angles and lengths)
  and the leader items up to two passes more, those without a clear place first,
  both bounded by a count of places looked at, not by time;
- a datum symbol with no clear spot in its view tries the other views the plan
  offers where its face is a line, and the drawing records the view it is drawn in;
- after an edit only the view side touched is re-laid out.

**Measured** (synthetic benchmark): an exhaustive callout candidate cost 411 µs
and a linear one 193 µs, about 8 s for 200 dimensions. **Targets:** an edit
re-laid out under 0.3 s; a full layout of 200 dimensions under 3 s; both
measured in the slice and on the goldens. Placement is deterministic: stable
sort keys, no randomness, coordinates rounded to a micrometre.

### 11.4 Sheet furniture and the title block

- **Border:** frame, margins and zones per the presets; the stamp band in the
  margin.
- **ASME title block** (B to E one layout, A a compact one): company name,
  address and logo; TITLE; DWG NO; PART NO (its own property, defaulting to the
  drawing number); REV; SIZE; CAGE (optional); SCALE; CALC WT with unit; SHEET
  n OF m; **STATUS**; **MODEL** and **MODEL REV** (part number, model revision
  and the short file hash); the approval rows as configured, each with its own
  name and date, empty until signed except DRAWN; MATERIAL; FINISH; the
  tolerance block (units statement, the decimal table or "SEE NOTE n" on
  printed parts, angles, the interpretation statement, once); the projection
  symbol; the proprietary statement; DO NOT SCALE DRAWING; optional NEXT ASSY
  and USED ON.
- **Plot stamp** in the lower margin: "SolidSeas <version>, <file name>
  (<configuration>)", the file name only when Settings allow it.
- **Revision block** (upper right): one row per revision with zone, letter,
  description, date and approver.
- **Stamp:** "PRELIMINARY - NOT FOR MANUFACTURE" in the border on every
  unreleased PDF and DXF.
- **Notes block:** "NOTES:" with numbered notes and UNLESS OTHERWISE SPECIFIED
  where it applies; flag notes referenced by a numbered flag.
- **Glyphs** (`layout/glyphs.py`, as paths): counterbore, spotface,
  countersink, depth, square, the projection symbol, the build-direction
  arrow, the datum feature symbol, the GD&T characteristic symbols, MMC and LMC
  modifiers, and the basic box. Proportions of the projection symbol and the
  GD&T symbols are **verify** items. Surface texture symbols come in stage 2.

### 11.5 Lines

Two widths in a 1:2 ratio by role; dash arrays fitted to each primitive's
length for PDF, SVG and the screen; named line types and `$LTSCALE` in DXF.

### 11.6 Layout checks

Per item: text overlaps, dimension lines crossing, leaders crossing, extension
lines crossing (a warning), row spacing, items outside the drawing area or in
reserved areas, text under the minimum height, leaders outside 15 to 75
degrees, moved placements that had to be reset, cramped features.

### 11.7 More than one sheet

A drawing has one sheet, except an assembly's whose parts list is longer than
the columns its first sheet holds (`docs/drawings/assemblies.md`). The first
sheet then fills those columns and the list goes on to sheets of the same size
after it, as many as it needs and at most `DrawingLimits.sheets` in all. Each of
those sheets has the border with its zones, the PRELIMINARY stamp while the
drawing is unreleased, the plot stamp, the title block and the rest of the list
in columns standing on the title block, each column with its headings, as many
columns as the border's width holds, each as tall as the field above the title
block; the last sheet's columns share its lines evenly. The views, balloons,
notes and revision block stay on the first sheet. Every title block says SHEET n
OF m, the first sheet's too (`1 OF 3`); a drawing of one sheet says `1 OF 1` as
before. A drawing at the limit puts every line left on its last sheet, its
columns taller than the field when they must be, and a drawing held to one sheet
(`DrawingLimits(sheets=1)`) stands its columns taller instead, as every drawing
did before.

The sheets after the first are `display.Sheet.continuation` of the first
(`display.sheets_of` lists them all), so everything that carries a drawing's
sheet carries them, and a layout lays them out again with the first. `R8.sheet`
checks each is the first's size with a title block numbering it among the rest.

## 12. Writers and where files go

### 12.1 PDF (`dwg-pdf`)

PDF 1.7 in pure Python; FlateDecode; base-14 Helvetica with WinAnsi encoding;
symbols outside WinAnsi (every GD&T symbol included) drawn as paths; exact
Béziers; optional content groups (Visible, Hidden, Centre lines, Dimensions,
Notes, Title block, Stamp); the logo as an image XObject with a soft mask;
metadata without paths or user names; a deterministic `/ID`; nothing active (no
JavaScript, actions or forms). Typed text outside WinAnsi is refused at entry.
PDF/A is stage 4. A page for each sheet, in order (11.7); a drawing of one sheet
is the one page it always was, byte for byte.

### 12.2 DXF (`dwg-dxf`)

R2000 (AC1015), written by hand (group codes, handles, tables, entities,
dimension blocks). Views at true size in model space with the furniture scaled
by 1/scale, so DIMENSION entities measure their true values with `DIMLFAC` 1;
one DIMSTYLE per unit; layers by role (VISIBLE, HIDDEN, CENTER, PHANTOM, DIM,
HATCH, BORDER, TITLE, NOTES); line types matching `acad.lin`.

A drawing of several sheets (11.7) is one file with the sheets side by side in
model space, left to right from the first, an inch of paper apart, each with its
border and title block, and the header's extents and the opening view taking
them all in. Model space is the one place every DXF reader shows: LibreCAD and
most viewers show only model space, and a program that shows layouts opens on
one of them, so a sheet in a paper space layout of its own is easily missed.
Side by side, every sheet is on screen the moment the file opens. A drawing of
one sheet is written as before, byte for byte.

What a user gets, said in these words in the docs and the UI:

- **Measuring, non-associative dimensions.** Linear, aligned, radial, diameter,
  angular and ordinate DIMENSION entities carry measured text (`<>`), so
  stretching geometry together with a dimension updates its value in
  AutoCAD-family programs and LibreCAD. Nothing is associative: moving geometry
  alone does not move the dimension. The model-driven route is the `.ssdrw`.
- **A single-size hole's Ø** is a diameter DIMENSION with its count prefix and
  THRU or depth suffix around `<>` (`4X %%c<> THRU`); counterbore,
  countersink, depth and thread lines are MTEXT beside it.
- **Feature control frames and datum symbols** are lines and text in one block
  per annotation (the TOLERANCE entity is a stage 4 option once tested in the
  readers).
- **Basic boxes** are drawn around measured text by the dimension's block.
- **Detail-view dimensions** carry explicit text and a per-dimension
  `DIMLFAC`, which LibreCAD shows as fixed text.
- **The PRELIMINARY stamp** is TEXT on its own layer.
- Strings are cleaned of control characters and MTEXT codes are escaped.

`dwg-dxf` is done, and merges, when its output passes its own test reader
(`tests/dxf_reader.py`, the checks of section 19.2) on every synthetic part and
fixture, with nothing needed from the PC. The audit in LibreCAD and in DWG
TrueView or the ODA File Converter is a PC acceptance item, filed as a bead of
its own and blocked until the user installs those programs, which is the
user's choice (Q9). Release does not wait for it: if they are never installed,
stage 1 ships with the DXF checked only by SolidSeas' own reader,
`docs/drawings/dxf.md` and the release notes say so plainly, and the bead stays
open; an audit error found later is fixed on a short branch that owns
`drawing/dxf/`. Whether SOLIDWORKS' DXF import keeps DIMENSION entities as
measuring dimensions is another bead, blocked until SOLIDWORKS is free; until
it passes, the UI says that inside SOLIDWORKS the editable route is the stage 3
`.SLDDRW`. R12 is stage 4.

### 12.3 SVG (core 2, internal)

The reference writer of the painted layer, used for previews, docs and goldens.
Not offered as a user export in stage 1. SVG has no pages, so it writes a file
for each sheet: `svg.to_svg` draws the one sheet it is given (a drawing's first
alone), and `svg.to_svgs` gives every sheet's, in order (11.7).

### 12.4 Determinism and goldens

The same `Drawing` writes the same bytes on one machine. Across machines the
tests compare the PDF's inflated content, the SVG's numbers within 0.01 mm and
the DXF's tags, not raw bytes.

### 12.5 Names

Exports are named by the Settings pattern (`{number} {revision}`) through the
rules of the viewer's `printing.safe_stem`. Unreleased exports add
" PRELIMINARY" to the stem (`1234-001 A PRELIMINARY.pdf`), and Save may
rewrite them under the rule in section 12.6 (Q14);
released exports (`1234-001 A.pdf`) are written once, at release, created new,
and never replaced by SolidSeas. A name taken by a file SolidSeas may not
replace gets " (2)", " (3)" and so on, and the status line says so.

### 12.6 Where files go (the user's answer to Q8)

Next to the part by default, under the 3D Print file's safety rules; a setting
chooses another folder. Settled by the user (Q8):

- The folder is checked as `printing.folder_problem` checks a print's folder: a
  folder that is a link or junction or lies below one, a cloud placeholder, a
  device or stream path, or a network share or drive outside the opened folder
  is refused. A folder chosen in the setting, in the wizard or in Save As is
  checked the same way.
- A refused folder or a failed write never sends the files somewhere else on
  its own. A print file falls back to the temporary folder because a slicer
  reads it once; a drawing is kept, so it never goes there. Wizard page 6
  shows the folder, and any refusal with its reason, before anything is
  written, and asks for another folder; in the editor, Save and the exports
  open Save As with the reason; the CLI fails with the error and writes
  nothing.
- Every file is written through a temporary name and a rename, never through a
  link, device or stream, and never over a file SolidSeas did not write.
- Released exports are never replaced.
- The CLI writes to its `--out DIR` under the CLI's existing write guards.

Settled (Q14, answered by the user on 2026-10-05). The 3D Print file never
replaces any existing file. A drawing goes one step further, as the user
allowed: Save may replace the same drawing's own `.ssdrw`, and keep its
PRELIMINARY exports current by rewriting them, but only files SolidSeas wrote
that are unchanged since. Every other file, and every released export, is
never replaced. `dwg-file` builds this behind one switch, `replace_own_files`,
which is on by default; a setting can turn it off:

- **On, the default: Save replaces only the same drawing's own files.** The
  `.ssdrw` is replaced only when the file on disk has the same
  drawing id, is a SolidSeas drawing, and still has the SHA-256 recorded when
  it was last loaded or saved. That hash is not kept in the file, which cannot
  hold its own hash: the editor keeps it in memory for the file it has open,
  and the CLI's `drawing update` uses the hash of the file as it read it. The
  library's `drawing.save(d, path, replaces=None)` refuses a path that exists
  unless `replaces` is given and equals the file's current hash, and never
  picks a name itself. With "Keep preliminary exports up to date on Save"
  (default on), the PRELIMINARY PDF and DXF listed in `outputs` are rewritten
  only when the files on disk still have the hashes recorded in `outputs` and
  say SolidSeas wrote them (the PDF `Producer`, the DXF `999` comment).
  Anything else gets a new name.
- **Off, when the user turns the setting off: every write is a new file.**
  Save writes the `.ssdrw` to the next free name (`1234-001 (2).ssdrw` and so
  on, as for a taken name) and the editor carries on with that file; the
  earlier one stays as it was. "Keep preliminary exports up to date on Save" is
  not offered: the PDF and DXF are written only by Export and Release, each to
  a new name. The CLI's `drawing update` writes the merged drawing to a new
  name beside the old one.

AGENTS.md says the 3D Print file is the one file written next to a model. The
viewer commit widens that rule to the drawing files, as the user decided in Q8
and Q14, in the same words as this section.

## 13. The drawing file, release and regeneration (`dwg-file`)

### 13.1 The file

`.ssdrw`: UTF-8 JSON without a byte order mark, one object, members in a fixed
order, numbers in shortest round-trip form, model quantities in metres, sheet
quantities in millimetres (the compact sheet in integer micrometres). Plain JSON
rather than a zip package: it diffs in git, an ERP script reads the title block
with any JSON parser, and the only binary member (the logo) is small. The JSON
Schema lives with the kind registry in `solidseas.model`.

```json
{
  "schema": "solidseas.drawing/1",
  "id": "8f0c1d2e-3b4a-4c5d-9e6f-708192a3b4c5",
  "generator": {"name": "SolidSeas", "version": "0.3.0"},
  "created": "2026-10-04T14:05:00-04:00",
  "modified": "2026-10-04T14:20:12-04:00",
  "model": {"name": "bracket.SLDPRT", "relative": "bracket.SLDPRT", "stored": null,
            "format": "sldprt", "configuration": "Default",
            "sha256": "<file hash>", "geometry": "<geometry digest>",
            "properties": "<digest of the properties the title block uses>",
            "part_number": "1234-001", "model_revision": "A",
            "units": {"unit": "in", "origin": "user"}},
  "options": {"process": "machined", "profile": "asme", "units": "in",
              "scheme": "datum", "arrangement": {"v-1/x": "baseline"},
              "front": {"direction": "+z", "turn": 0},
              "views": ["<frozen view set>"], "sheet": "B", "scale": [1, 1]},
  "settings": {"<snapshot, logo included>": "..."},
  "title": {"title": {"text": "BRACKET, MOTOR MOUNT", "from": "typed"},
            "number": {"text": "1234-001", "from": "part"},
            "material": {"text": "ALUMINUM 6061-T6", "from": "list"}},
  "features": [{"id": "f-7", "descriptor": {"<type, size, adjacency, position>": "..."},
                "decisions": {"thread": null, "datum": null}}],
  "dimensions": [{"key": "loc/f-7/x", "id": "d-12", "origin": "generated",
                  "state": "shown", "view": "v-1",
                  "placement": {"along_mm": 0.0, "across_mm": 12.0, "track": 1,
                                "moved": true},
                  "text": {"prefix": "4X", "suffix": ["THRU"], "override": null},
                  "precision": {"places": 3, "source": "role"},
                  "tolerance": {"type": "basic"}, "frame": null}],
  "notes": [{"id": "n-1", "origin": "template", "text": "BREAK SHARP EDGES .005-.015"}],
  "status": "PRELIMINARY",
  "signatures": [{"row": "DRAWN", "name": "AB", "date": "2026-10-04",
                  "digest": "<content digest>"}],
  "revisions": [{"rev": "A", "zones": [], "description": "INITIAL RELEASE",
                 "date": null, "approved": null}],
  "outputs": [{"kind": "pdf", "name": "1234-001 A PRELIMINARY.pdf",
               "sha256": "<hash>", "revision": "A", "released": false}],
  "next_id": {"f": 31, "d": 58},
  "sheet": {"<laid-out display list, compact>": "..."}
}
```

Members:

- `model`: the name; the path relative to the drawing's folder; the absolute
  path only when no relative path exists, and never in Save a Copy to Send;
  the file's SHA-256 (the exact file), the geometry digest (tells a geometry
  change from a save that only touched properties), the properties digest
  (tells that a title block refresh is due); configuration, part number, model
  revision, units.
- `options`: frozen at the first save (section 6.8).
- `settings`: the snapshot.
- `features`: id, descriptor and the user's decisions.
- `dimensions`: key, id, origin, state, placement, overrides, tolerance, frame.
  A removed generated dimension stays in the list, so the editor can restore it
  and regeneration keeps it removed; a deleted user dimension is gone.
- `notes`, `title`, `status`, `signatures`, `revisions`, `outputs` (kind, name,
  hash, revision, released or not), `next_id`.
- `sheet`: the laid-out display list in compact form, so the drawing reopens
  view-only and exports without the model, and a released revision reproduces
  exactly in later SolidSeas versions. The geometry cache for editing without
  the model is stage 4. A drawing of several sheets (11.7) keeps them all in
  this one member: the first sheet's item takes a ninth value, the list of the
  sheets after it, each a `sheet` item of its own without one. The ninth value is
  written only when there are more sheets, so a drawing of one sheet writes the
  eight values it always did, and a file from before reads as a drawing of one
  sheet. The schema stays `solidseas.drawing/1`: nothing a reader of one-sheet
  files needs has changed, and a SolidSeas from before multi-sheet drawings
  meets a sheet item with nine values as it meets a compact tag it does not know
  (the parts list's, for one), opening the drawing without its laid-out sheet and
  writing that member back as it came. A file with more sheets than
  `DrawingLimits.sheets` opens the same way, the reason in its problems.

A reader accepts schema major 1, refuses a higher major with a clear message,
keeps unknown members (bounded) and never interprets them, so a newer
SolidSeas's additions survive an edit in an older one.

### 13.2 Status and signatures

- **PRELIMINARY** at creation: DRAWN holds the name chosen on wizard page 2
  (from the People list) and the generation date; every other approval row is
  empty.
- **Sign...** (editor only, never the CLI): the user picks a row and a person
  from the People list; SolidSeas records the name, today's date and the digest
  of the drawing's content at that moment. An edit after signing clears the
  signatures it invalidates (all but DRAWN) and says so. Signing CHECKED moves
  the status to **CHECKED**. The same person on two rows is a warning when
  Settings allow it, an error otherwise.
- **Release...** needs every row Settings require signed; no error-level check,
  except `COV.unclaimed` and `R2.override` items the user accepted with a typed
  reason; and the material mapped or accepted as typed. It sets **RELEASED**,
  fills the revision row's date and approver, writes the released PDF and DXF
  without the stamp, and records their hashes.
- A signature is a record of who approved what and when, not a cryptographic
  signature; the docs say so.
- **Email PDF** and **Save a Copy to Send** on a drawing that is not RELEASED
  ask "This drawing is PRELIMINARY. Send it anyway?" and send the stamped PDF.

### 13.3 Revisions

- A RELEASED drawing is read-only: the editor shows it, exports its released
  files and offers **Start Revision**. The library's edit operations refuse it
  with the error code `drawing_released`.
- **Start Revision** takes the next letter (skipping I, O, Q, S, X and Z;
  after Y comes AA), adds a revision row whose description is pre-filled from
  the edit log and the merge report and is editable, records the zones of
  changed items, clears signatures and sets PRELIMINARY.
- Released exports are never overwritten: each revision has its own file names.
- Before the first release a drawing can be saved and exported freely.

### 13.4 Identity and stable ids

- **Features** get ids `f-1`, `f-2`... at creation, in recognition order, and
  keep them. On regeneration `match.py` pairs old and new features: equal type
  and size signature first (or within a small tolerance, marked "changed
  size"); then an assignment problem (the Hungarian method) on positions in the
  datum frame, each axis normalised by the change in the part's extent along
  it, so a mid-plane extrusion that grew moves its end faces proportionally
  rather than "far"; adjacency patterns break ties. Unmatched old features are
  gone; unmatched new ones are new.
- **Datums** are features. Once a drawing exists they follow their matched
  faces; if a datum face is gone, the drawing asks for a new one and never
  silently re-picks the largest face.
- **Dimension keys** are the requirement role, the feature ids and the axis or
  angular graph, for example `loc/f-7/x` or `size/f-3`. The view is an
  attribute, not part of the key.
- **Dimension ids** are `d-1`, `d-2`... assigned once at creation in planning
  order (`next_id`) and inherited through matching; new dimensions take the
  next free number. A fresh drawing from the same model and options always gets
  the same ids.
- **Placements** are stored relative to the dimension's attach points (offset
  along and across, in paper millimetres, and the track index); a placement
  whose view or side changed is reset and reported.

### 13.5 Regeneration that keeps the user's edits

When the model's file hash differs from the drawing's, `regenerate(drawing,
source)`:

1. If the geometry digest is unchanged, only the model reference changes: the
   drawing says "model file changed, geometry unchanged" and offers to take the
   new reference (a new revision when released).
2. Otherwise it re-runs the pipeline with the frozen options, the matched
   features and their decisions, the user's dimensions as fixed graph edges,
   and the previous plan's edges at reduced cost, so the planner keeps its
   earlier choices unless they became impossible.
3. It merges: exact key matches inherit state, placement and overrides; new
   requirements are added and marked new; requirements whose features are gone
   are dropped (a removed one is forgotten, a shown one reported); a user
   dimension whose features are gone is kept, marked "needs attention", drawn in
   a warning colour and left out of exports until fixed. Notes and title fields
   are never regenerated, except fields whose origin is `part`, which follow the
   part's properties unless the user overrode them.
4. It reports ("31 unchanged, 2 changed, 3 new, 1 dropped, 1 needs attention")
   identically in the editor and `solidseas drawing update --json`, and the
   report pre-fills the next revision row.

A RELEASED drawing must Start Revision before Update from Model. A frozen scale
that no longer fits is reported with "Change Scale" as the fix, never changed
silently.

### 13.6 Finding the model

A `.ssdrw` can arrive by email, so the paths in it are untrusted. The model is
looked for, through `solidseas.resolve`'s rules, at: the relative path joined to
the drawing's folder and opened within it; the stored path only on a local
drive (never a UNC path or a mapped network drive); the catalog, by SHA-256 and
then by name, inside its roots. A candidate whose hash differs is offered ("this
file has changed since the drawing was made"), never taken silently. With no
model the drawing opens view-only from its sheet, with "Find the model..." in
the bar.

## 14. API, command line and JSON kinds

```python
from solidseas import drawing

settings, problems = drawing.load_settings()
d = drawing.make_drawing(
    "bracket.SLDPRT",
    options=drawing.DrawingOptions(process="machined", scheme="datum"),
    fields={"title": "BRACKET, MOTOR MOUNT", "number": "1234-001", "revision": "A"},
    settings=settings,
)
d.checks, d.coverage, d.status          # "PRELIMINARY"
with open("1234-001 A PRELIMINARY.pdf", "xb") as fh:
    drawing.write_pdf(d, fh)
drawing.save(d, "1234-001.ssdrw")
d2, report = drawing.regenerate(drawing.load("1234-001.ssdrw"))
d3, checks = drawing.edit.remove(d2, "d-12")
```

`DrawingOptions`: process (`machined`, `printed`; `turned` in stage 2), scheme
(`datum`, `plusminus`), units, views, front and turn, hidden and tangent modes,
sheet and scale, arrangement per axis, bodies, quality (`normal`, `draft`,
`fine`). Arguments are checked with `InvalidArgumentError`. The API is
provisional until the first release and documented in a new `docs/API.md`
section.

**CLI** (`solidseas drawing ACTION`, one kind `drawing_result`):

| Action | Does |
|---|---|
| `drawing new PART [--configuration C] [--process machined\|printed] [--scheme datum\|plusminus] [--units part\|in\|mm] [--views auto\|LIST] [--front ...] [--sheet auto\|A..E] [--scale auto\|N:M] [--title T] [--number N] [--part-number P] [--revision R] [--material M] [--finish F] [--drawn-by NAME] [--confirm-threads FILE] [--settings FILE] --out DIR [--pdf] [--dxf] [--json]` | makes a PRELIMINARY drawing; always the `.ssdrw` |
| `drawing export DRAWING [--pdf] [--dxf] --out DIR` | exports from the file's sheet; a released drawing exports its released revision |
| `drawing update DRAWING [--model PART] [--dry-run]` | regenerates and merges; refuses a released drawing |
| `drawing check DRAWING_OR_PART [--strict] [--model PART]` | the checklist and thread candidates; `--model` verifies a model against the drawing's MODEL reference |
| `drawing show DRAWING` | the summary, status and revisions |
| `drawing settings` | the effective settings and their fallbacks |

The CLI never signs or releases: approvals come from a person in the viewer.
`--units part` on a part that states no unit fails unless `--units` names one,
so an unattended run never guesses silently.

**Kinds:** `drawing_result` (action; a drawing summary with status, revision
and signatures; files; merge report; checks; coverage by features, faces and
area; thread candidates; seconds per stage; warnings). The kind is not called
`drawing`, because `doc_type: "drawing"` already means a SOLIDWORKS drawing.
`ssdrw_summary` and REST routes are stage 4. **New error codes:**
`drawing_invalid`, `drawing_too_complex`, `model_not_found`,
`drawing_released`.

## 15. The viewer

### 15.1 Where it appears

File > New Drawing... (Ctrl+D) and a Drawing toolbar button beside 3D Print;
Make Drawing... in every right-click menu that offers 3D Print, built from the
same `PrintTarget` objects, so a component part can be drawn from its assembly;
File > Open Drawing...; Settings > Drawing Settings.... An assembly is drawn
with its parts list and balloons (`docs/drawings/assemblies.md`); SOLIDWORKS
drawings and (in stage 1) other formats show the entry disabled with the
reason. `viewer/drawingaction.py` keeps the change to `window.py` to a handful
of lines.

### 15.2 Drawing Settings

One dialog with pages: Company, People and Approvals, Standard and Units,
Sheets, Title Block, Tolerances, Geometric Tolerances, Printing, Notes,
Materials and Finishes, Default Views, Dimensioning, Files, Email (and
SOLIDWORKS in stage 3). OK, Apply, Cancel, and Restore Defaults per page, as
Preferences has. Fallbacks are listed at the top. On first use (no company
name, or no unit for unstated parts) New Drawing opens this dialog on the
missing page. The Tolerances pages label the values "your company's
tolerances", and the printing values "service bureau figures; replace with your
own".

### 15.3 The New Drawing wizard

A `QWizard` of six pages, with the sheet preview from page 2, generated in a
child process (`viewer/drawingproc.py`, following `viewer/meshproc.py`: a Job
Object memory limit, below-normal priority, a time limit, cancellation):

1. **Part:** file, configuration, bodies. Units: "stated in the part", or "not
   stated; looks like inch (41 of 47 sizes are whole thousandths)" with inch
   and millimetre buttons one of which must be clicked; the overall size in both
   units. Warnings before generating: the estimated time for large parts, Draft
   quality, skipped or `BLENDED_EDGE` faces, features that need an auxiliary
   view, a part over the bounds (refused here, with the reason).
2. **Title block:** title, part number, drawing number, revision, model
   revision, material (from the part, the list, or typed; unmapped flagged;
   heat treatment asked for heat-treatable entries), finish (explicit), drawn
   by (from People). No checker or approver here.
3. **Manufacturing:** Machined (milled) and 3D printed; Turned (lathe) shown
   with "coming in 1.1"; Sheet metal "coming later". The suggestion and its
   reason. Machined: the scheme (datum-referenced or plus/minus) and datum
   faces A, B, C, changeable by clicking faces in the preview. Printed: process,
   layer height, infill, walls, build direction, supports, post-processing.
4. **Views and sheet:** front direction and turn; tick boxes for the projected
   views and the isometric; detail and section requests; hidden lines; tangent
   edges; scale and sheet. "Make these my defaults" saves them.
5. **Dimensions and holes:** recognised features in groups with tick boxes;
   thread candidates (Tapped, Clearance, Plain) and holes whose ends need
   confirming; tolerance bands; coverage by features, faces and area, with
   "reduced-dimension drawing" said plainly when it applies; the checks
   summary.
6. **Output:** folder (next to the part by default) and name, with a refused
   folder shown with its reason and another asked for (section 12.6); the
   files (the drawing file always; PDF and DXF ticked); "Open in the editor"
   (on). Files are written as PRELIMINARY.

### 15.4 The drawing editor

A `QMainWindow` per drawing, with the operations of section 10.12:

- **Centre:** the sheet in a `QGraphicsView`, items per owner from the painted
  layer (`viewer/drawingscene.py`), pick and hover by owner; views drag with
  their dimensions and keep alignment.
- **Left:** Dimensions grouped by view with tick boxes, text, kind, band and
  badges (new, changed, needs attention, reference, overridden, basic).
- **Right:** Properties: the measured value (read-only), precision and band,
  prefix and suffix, value override (with its warning), tolerance, the frame
  editor, Reset Position; note text; title fields; view label, scale, display.
- **Add Dimension (D):** pick one or two features (hover highlights them); the
  list shows the planner's candidates with values; choose one.
- **Checks:** the list of section 20.1, each row selecting what it is about and
  offering fixes; release-blocking rows marked.
- **Status bar:** status and revision; "Model unchanged", "The model has
  changed. Update Drawing", "Model not found. Find...".
- **Commands:** Save, Save As, Save a Copy to Send, Export PDF..., Export
  DXF..., Email PDF, Update from Model, Sign..., Release..., Start Revision,
  Sheet and Scale, Units, Tolerance Block, Notes, Add Detail View, Add Section,
  Use Current Drawing Settings, Drawing Settings, Undo and Redo (`QUndoStack`).
- **Sheets:** a drawing of several sheets (11.7) shows one at a time, the status
  bar saying which ("Sheet 2 of 3"); Next Sheet and Previous Sheet (Ctrl+Page
  Down, Ctrl+Page Up, on the Drawing menu and the toolbar, shown only for such a
  drawing) page through them. Every edit is about the first sheet, which holds
  everything but the rest of the parts list, and selecting a dimension, a note or
  a view shows it again.

Nothing geometric runs on the UI thread.

### 15.5 Email PDF (the user's answer to Q7)

1. **The PDF.** The released PDF, or the stamped preliminary one after the
   PRELIMINARY warning, made current first. Only the PDF is ever offered, never
   the `.ssdrw`, DXF or SLDDRW, which can carry folder names.
2. **The route**, chosen before anything is called, from Drawing Settings >
   Email > Method:
   - **Automatic** (default): attach when the default Simple MAPI client is
     classic Outlook or Thunderbird and is really there, otherwise webmail. The
     check reads the registry only and fails closed to webmail: the
     `Software\Clients\Mail` default (HKCU, else HKLM) names the client; for
     classic Outlook its `OUTLOOK.EXE` must be found through App Paths or
     Office's install root (new Outlook does not implement MAPI); for
     Thunderbird its registered MAPI DLL must exist. Anything else is webmail.
   - **Webmail**, always.
   - **Just show me the file:** the PDF selected in the file manager, nothing
     more.
3. **Attach route** (classic Outlook, Thunderbird). Simple MAPI in a child
   process (`viewer/mailproc.py`), because a mail program's DLL is loaded into
   the calling process and can crash or hang it, and the packaged viewer would
   otherwise search its own bundle's DLLs first. The child restores the default
   DLL search order (`SetDllDirectoryW(NULL)`), loads `mapi32.dll` from System32
   by full path, and calls `MAPISendMailW` with `MAPI_DIALOG | MAPI_LOGON_UI`
   (no recipient needed with `MAPI_DIALOG`; the attachment a `MapiFileDescW`
   with `nPosition` -1, the PDF's full path and the display name), falling back
   to `MAPISendMail` with an ASCII-named temporary copy when the W function is
   missing or fails. It writes the return code to its pipe and exits. The
   viewer waits on its thread pool, not the UI thread, since the call blocks
   while the compose window is open. Return code 0 is success and 1 means the
   user closed the compose window (said nothing); anything else falls to the
   webmail route with a line saying why.
4. **Webmail route.** The PDF is shown selected in the file manager (Explorer
   with `/select,` and one argument), and the compose page opens in the default
   browser through `QDesktopServices.openUrl`. The default is Gmail's compose
   URL, `https://mail.google.com/mail/?view=cm&fs=1&su={subject}` (**verify**
   on the PC with the user). The subject is the drawing number and title only,
   percent-encoded; no path, company, customer, body or other field. With
   pre-filling off the URL carries no subject. Another webmail is a URL
   template the user types: it must be `https://`, `{subject}` is its only
   placeholder, and it is checked when saved. The status line says what to do:
   "Gmail opened a new message in your browser. Drag the selected PDF from the
   folder window into it."
5. SolidSeas never sends mail, never sees or stores a password, and opens no
   network connection of its own; the browser opens the page.

On the user's PC today Automatic gives the webmail route, which is how the user
sends mail. Linux and macOS get the webmail route only.

### 15.6 Self-test and packaging

`--drawing-dry-run`: drawings of o11 and o02 through the wizard's code path; PDF
and DXF to a temporary folder, checked by the writers' structure checks; the
editor's remove, restore, undo, sign, release and start revision; save; and
Email PDF with stand-ins that start nothing. No new Qt module.

## 16. The SOLIDWORKS drawing (stage 3, `dwg-sldrw`)

Through the bridge, in the batch-mode SOLIDWORKS that SolidSeas starts (hidden,
in its Job Object, bound only through its own `SolidWorks_PID_<pid>` moniker,
never the user's session; `src/solidseas/swapi/README.md` has the protocol,
the off-hours rule for work SolidSeas starts by itself, and how the instance
ends). The bridge accepts only named operations with checked arguments, so
stage 3 adds the drawing operations it needs: a new drawing from a template
(`new_document` already takes a `.drwdot`), views at SolidSeas' directions and
positions, dimensions from SolidSeas' plan as reference dimensions on edges
matched by geometry (Parasolid node ids are not SOLIDWORKS persistent ids, so
each face is found again by a point on it), hole callouts, centre marks, datum
feature symbols and frames through the published annotation calls (**verify**
each against the API help before use), title fields as the drawing's own
custom properties, the STATUS and revision fields, the PRELIMINARY stamp as a
note on unreleased drawings, a save through `SaveAs3`, and a read-back with
`Document.sheets()`. Requests and replies are data checked against one JSON
Schema. Documents open read-only; only SolidSeas' own documents and instance
are closed. DimXpert stays out, because it saves into the part (Q12), and
whether the run may relink a model-linked title field in the new drawing's own
copy of the sheet format is asked each time (Q13).

## 17. Bounds and hostile input

### 17.1 `DrawingLimits`

| Bound | Default | Basis |
|---|---|---|
| bodies | 64 | an assembly's part counts once however many instances use it |
| instances | 1,000 (at most 10,000) | an assembly's part instances read |
| faces | 50,000 | corpus maximum 34,863, 99th percentile 6,114 |
| edges | 150,000 | corpus maximum 78,706 |
| triangles (Normal; Draft coarsens to stay under) | 400,000 | about 4.7 KB a triangle in the prototype |
| child memory | 3 GB, at most half the PC's memory | |
| visibility queries a view | 2,000,000 | measured maximum 50,438 on the sample; re-measure in core 1 |
| seconds | source 30, tessellation 30, features 20, views 90 in all, plan 20, layout 20; 150 in total | worst measured before the fixes: 185.6 s for a 19,064-face part |
| model extent | 1 µm to 100 m | |
| requirements; generated dimensions | 5,000; 2,000 | |
| views a sheet; sheets | 12; 16 (at most 64) | the corpus drawings have at most 6 views and one sheet; more sheets hold only a long parts list (11.7) |
| title field; note; any string | 256; 2,000; 4,096 characters | |
| settings file; drawing file; its sheet; unknown members | 256 KiB; 16 MiB; 12 MiB; 1 MiB | |
| logo stored | 512 KiB, 1,200 px a side | |
| output file | 64 MiB | |
| JSON nesting | 32 | |

A part over the face, edge or triangle bound is refused before tessellating,
from a topology walk's counts, with `drawing_too_complex`; the wizard says so
on page 1.

### 17.2 What hostile input meets

Bad B-rep values are refused per face by the tessellator. Properties are
cleaned and bounded. A `.ssdrw` is checked for size, strict JSON, nesting,
schema major, id patterns (`[a-z0-9-]{1,64}`), finite in-range numbers, and
string and array bounds before anything else; a file outside the bounds is
refused whole with the reason, and a value failing its own check falls back to
its default with the editor listing what was reset. Paths inside a drawing are
never trusted; names go through `safe_stem`'s rules; control characters are
removed and MTEXT escaped for DXF; PDF strings and XML are escaped; the webmail
URL is built from a template the user saved, with the subject percent-encoded;
MAPI runs in a child; Explorer gets `/select,` and one argument. Signatures,
revisions and statuses in a `.ssdrw` are data, checked like any member; a file
claiming RELEASED whose recorded export hashes do not match the files is shown
as "release record does not match the files" and never re-exported over them.

## 18. Privacy

Company details and the logo live only in the roaming profile and in the
drawings that carry them. People are typed names; nothing is read from Windows,
Office or SOLIDWORKS. The `.ssdrw` holds the model's name and relative path
(absolute only when unavoidable, never in Save a Copy to Send). PDF and DXF hold
no folder path or user name. The plot stamp shows the file name only when
Settings allow it, since a file name can name a customer. The short file hash
in MODEL reveals nothing about the file's content. Email attaches or offers
only the PDF, puts only the drawing number and title in a webmail URL (or
nothing, with pre-filling off), and SolidSeas never handles a mail password.
Drawings never reach an AI provider. Tests use the fictional "Example
Engineering Co." and synthetic parts; corpus sweeps print counts only.

## 19. Tests

### 19.1 Synthetic parts (core 2, `tests/drawing_parts.py`)

Built on `XtBuilder`: `prism(profile, height)`, `cut_hole(part, at, axis,
stack)` (entering and leaving planar faces), `cut_pocket`, `add_boss`,
`revolve(profile, bore=None)` (for stage 2), each returning the transmit and
its ground truth (features, values, expected requirement keys and the expected
dimension set). Stage 1 parts:

- a plate with each hole kind (simple, counterbore, spotface, countersink at 82
  and 90 degrees, blind flat, drill point, stepped);
- linear, grid and circular patterns, and a pitch circle clocked 15°;
- four equal holes at irregular positions (eight locations or ordinates);
- a link plate with full-round ends ("2X R" without a value);
- a block topped by a boss (centre and tangent links);
- a block with a pocket and a tab (width and thickness stated directly);
- a slot, a step, chamfered edges, and an angled face meeting its plane at a
  round (virtual sharp);
- an inclined face carrying a hole and a slot (reported as needing an auxiliary
  view in stage 1; in true shape in stage 2);
- a manifold block whose drilled passage ends in a cross bore (not THRU);
- a face O-ring groove (a groove, not a hole);
- a cross hole entering a cylinder (depth reference flagged);
- a plate with 16 holes (the ordinate switch);
- a printed L-bracket (process note, arrows, "SEE NOTE");
- regeneration pairs: a mid-plane extrusion lengthened, the origin moved, a
  hole added to a pattern, a datum face that stops being the largest;
- seeded random plates with holes and patterns kept apart.

### 19.2 Per branch

| Branch | Tests |
|---|---|
| core 1 | `detail=False` unchanged; samples on both faces; (u, v) round trip; edge normals against surface evaluation; bytes per triangle |
| core 2 | settings round trip and fallback; first-use prompts; number and tolerance formatting; unit guessing; font widths; source on the o02 to o12 SLDPRT fixtures; `BrepModel` against ground truth; signatures stable over a save that changed no geometry; SVG; capability gaps |
| `dwg-views` | analytic hidden-line oracles on synthetic parts; the fixture benchmarks; exact entity kinds; the outline rule; centre marks; sections (closed loops, snapping, hatch, open-mesh refusal); detail clipping; per-part entity shares |
| `dwg-features` | every synthetic part's ground truth exactly; o10 (one Ø5 through hole) and o11 (one Ø10 through hole with an R1 edge-break torus, and four R3 rounds); THRU, `into_bore`, curved entry, face groove, widths with stepped interlocks, scattered patterns, derived full-round ends, inclined features; thread candidates |
| `dwg-plan` | requirements; linear and angular graphs complete and acyclic; radius links; the datum scheme (basic, frames, profile note) and plus/minus; the ordinate switch; view choice; assignment; callouts; notes; the rounding guard as a check; layout tracks, nesting, staggering, leaders, every hard conflict on constructed overlaps; arrangement; scale and sheet; title block fields; stamps; glyph paths; the speed targets of section 11.3 |
| `dwg-oracle` | the reconstruction test (19.3) on every synthetic part, written without reading `plan/` |
| `dwg-pdf` | a test PDF reader; no path or user name; determinism; PNG cases; GD&T glyphs as paths |
| `dwg-dxf` | a test DXF tag reader: handles, owners, every DIMENSION with its block, tables complete, measured text, hole Ø as a DIMENSION, frames as blocks, injection strings |
| `dwg-file` | round trip; bounds and fuzzing; unknown members kept; ids assigned and inherited; matching on the four regeneration pairs and o02 to o07; status, signing, content digest invalidation, release, start revision, export naming, never overwriting released files; Save with `replace_own_files` off and on, the hash check and `replaces`; model lookup |
| `dwg-mail` | route choice from a fake registry; the MAPI child against a stub DLL (Windows); webmail URL building, escaping and template checks; the status text; settings dialog round trip; first-use prompts |

### 19.3 The reconstruction oracle

`tests/drawing_reconstruct.py`, written by an owner other than `dwg-plan`'s and
without importing `drawing.plan`: from the shown dimensions (values,
references, kinds), the implied conventions written in
`docs/drawings/conventions.md` (90° where drawn square, coaxiality where drawn
so, equal spacing, `nX`, derived radii) and the datum frame, it rebuilds every
recognised face's offset, every axis and every radius, and compares with the
B-rep. A face it cannot recover is **missing**; one recovered twice through
toleranced dimensions is **redundant**; one recovered with a different value is
**wrong**. It runs on every golden and synthetic part and, counts only, in the
corpus sweep.

### 19.4 Golden drawings (integration)

| Part | Profile | Proves |
|---|---|---|
| o02 box | ASME mm and inch | envelope, title block with STATUS and MODEL, projection, minimal views, PRELIMINARY stamp |
| o07 box | ASME mm | regeneration from o02's drawing: the height keeps its id, removed stays removed, moved stays moved |
| o11 block | ASME mm and inch | datum symbols, basic locations, the position frame in the callout, the R1 entry round as a callout line (no section), fillet note, tangent outline, centre marks, the rounding guard on a millimetre model drawn in inches |
| synthetic plate with hole kinds and patterns | ASME inch | callouts, frames, pitch circle angle, scattered locations |
| synthetic link plate, boss block, pocket and tab | ASME inch | widths, radius and tangent links |
| synthetic 16-hole plate | ASME inch | the ordinate switch |
| synthetic inclined face | ASME inch | reduced-dimension drawing, release blocked until accepted |
| printed L-bracket | ASME mm | process note, "SEE NOTE", arrows, plus/minus scheme |
| regeneration pairs | ASME mm | matching and merge |

The expected dimension set of each golden is written by hand from the rules and
reviewed once by the user. Each golden is compared as a plan summary (JSON), SVG
numbers, PDF content and DXF tags.

### 19.5 Checks every golden and synthetic part must pass

1. Every requirement covered by exactly one shown dimension or callout, or an
   implied link; no requirement key twice.
2. Every linear and angular graph complete and acyclic.
3. The reconstruction oracle finds nothing missing, redundant or wrong.
4. No hard layout conflict.
5. Every automated P0 and P1 check passes, apart from expected, accepted
   release blockers.
6. Writing twice gives the same bytes; regenerating against an unchanged model
   changes nothing.

### 19.6 Hostile input, viewer, corpus and manual

Every case of section 17.2 is a test. The viewer's dialog, wizard, editor,
signing, release and Email PDF are tested with stand-ins. The corpus sweep is
opt-in, in child processes, counts only. By hand on the PC, with the user's
permission where it installs or starts something: PDFs in Edge, Chrome and
Acrobat Reader and printed to scale; DXFs in LibreCAD and DWG TrueView or ODA
once the user has installed them; Email PDF with the user's webmail.

## 20. Judging quality

### 20.1 The automated checklist

| Id | Check | Severity |
|---|---|---|
| R1.aligned, R1.scale, R1.symbol | projection, alignment within 0.01 mm, one scale stated, the symbol | error |
| R2.units | units statement present, once | error |
| R2.format | values and explicit tolerances formatted per unit and type (10.8) | error |
| R2.rounding | a toleranced value as shown within 10 % of its band of the model | warning; error above 50 % |
| R2.override | a value differs from the measured value | error until acknowledged |
| R3.tolerance | every dimension has a source of tolerance; block and standard on the sheet | error |
| R3.block | no toleranced value with more decimals than the block's last row without an explicit tolerance | error |
| R3.basic | every basic dimension governed by a frame or the general profile note | error |
| R3.roles | role-assigned precisions listed for review | information until CHECKED is signed |
| R4.complete | every linear and angular graph connected; every size present | error |
| R4.redundant | no cycle among toleranced dimensions; no requirement key twice | error |
| R4.members | every pattern member located directly or through its pattern's pitch or pitch circle; `nX` equals the count | error |
| R4.coincident | merged positions over separate surfaces carry a count or extension lines to each | error |
| R5.visible, R5.true_shape | no dimension on a hidden run; sizes in true shape; Ø above 180°, R at or below | error |
| R6.title | company, title, drawing and part number, revision, size, scale, sheet, STATUS, MODEL, DRAWN with date, material, finish, units and block, projection symbol | error |
| R6.material | material mapped to an entry with callout and specification, or accepted as typed; finish explicit; heat treatment answered when asked | error at release |
| R6.signatures | rows Settings require are signed at release; signatures match the current content | error at release |
| R7.callouts | callout grammar and order; THRU only with both ends open; a thread only when confirmed; `into_bore` ends confirmed | error |
| R8.sheet | size, margins, frame, zones, block positions; every sheet the first's size and numbered SHEET n OF m | error |
| R9.lines | two widths 2:1; styles by role; centre marks and lines | warning |
| R10.text | heights at or above the minimum; labels larger; upper case; no compressed text | error |
| R11.collisions | no hard conflict | error |
| R11.spacing, R11.leaders | spacing, gap and overrun; leaders 15 to 75 degrees | warning |
| R12.views | no idle view; sections replace their projected view; labels and letters | warning |
| R13.scheme | locations from the datums; ordinate where stacks are deep | warning |
| R13.plusminus | plus/minus locations between features under Y14.5-2018 | warning (information on printed parts) |
| R14.notes | fillet note radius; chamfers `leg X angle`; edge break note | warning |
| R15.process | the type's notes; printed: block and note agree, arrows on views with Z dimensions | error |
| R18.datums, R18.frames | referenced datums exist and attach to visible geometry; frame grammar (characteristic, zone shape, modifiers, datum order) | error |
| COV.unclaimed | unclaimed geometry listed and covered by a complete model-governs note | warning that blocks release until accepted |
| REL.stamp | an unreleased export carries the stamp and "PRELIMINARY" in its name | error |
| ASM.parts | an assembly's sheet has its parts list | error |
| ASM.balloons | every item of an assembly's parts list has a balloon; a balloon naming no item is an error | warning |

### 20.2 Coverage, said plainly

Every drawing reports requirements found and dimensioned, references, and
unclaimed geometry by feature count, face count and area, with reasons. A
drawing with unclaimed geometry is called a reduced-dimension drawing
everywhere it is described.

### 20.3 The corpus sweep (PC)

Opt-in, numbers only, below-normal priority, one part per child with a timeout.
Before targets are fixed it measures the recognised-area fraction per size band
(up to 100, 100 to 500, 500 to 3,000, over 3,000 faces) and on the 13 drawn
parts. Outcomes are counted separately: **complete**, **reduced-dimension**,
**errors** (with the failing check ids), **refused** (with the reason),
**failed**. It also counts hard conflicts, the reconstruction oracle's
findings, dimensions and views per drawing, and time and peak memory per stage.

**Targets for stage 1**, to confirm after the first measurement: no crash or
hang; every one of the 13 drawn parts complete or reduced-dimension with no
error-level check; at least 90 % of machined-style parts (all faces analytic
and on three square directions, 47 % of parts) complete with no error-level
check; a recognised-area median of at least 0.95 on analytic machined-style
parts; no hard layout conflict in any drawing below 100 dimensions; the speed
targets of section 8.12.

### 20.4 The engineer's review (PC)

`docs/drawings/REVIEW.md` holds an eight-item rubric, scored 0, 1 or 2 on
printed drawings: could a shop make and inspect the part from the sheet alone;
views; origins and datums; callouts, frames and threads; missing or extra
dimensions; readability; title block, material and finish; notes. The first
review covers the stage 1 goldens and about ten of the user's own parts chosen
by the user, on the user's machine; only scores leave it, and each problem
becomes a synthetic part. **Target:** every golden scores 2 on items 1, 4, 6
and 7; eight of ten user parts score at least 1 on every item after at most
five edits each.

## 21. Acceptance checks per stage

### Stage 1

1. **Core 1:** `detail=False` byte-identical; the two fixes in; the views
   re-measured on the PC; the speed targets of section 8.12 written down from
   the numbers.
2. **Slice:** four parts end to end; layout timings recorded; the contract list
   written.
3. **Goldens** (19.4) pass 19.5, the reconstruction oracle included, and the
   user has reviewed each once.
4. **Release flow:** a generated drawing has only DRAWN filled and is stamped;
   Sign records name, date and digest; an edit clears the signatures it
   invalidates; Release refuses with an unaccepted blocker, writes
   `{number} {revision}.pdf` once and makes the drawing read-only; Start
   Revision adds a row with the next letter; no test can make SolidSeas
   overwrite a released export. Save follows the answer to Q14: with
   `replace_own_files` on (the default) only the drawing's own unchanged files
   are replaced, and with it off no write replaces any existing file.
5. **Regeneration:** the four regeneration pairs and o02 to o07 keep every
   removal, move and override; datum faces follow their match; a user dimension
   whose feature is gone is "needs attention", not lost.
6. **Speed and memory:** the 13 drawn parts and the size-band sample meet the
   targets fixed after core 1 (PC); an edit re-lays out under 0.3 s and 200
   dimensions lay out under 3 s on the goldens; the drawing child stays under
   its memory limit on every corpus part or refuses it up front (PC).
7. **Corpus sweep** (PC): the targets of section 20.3, outcomes reported
   separately.
8. **Files on the PC:** PDFs open in Edge, Chrome and Acrobat Reader and print
   to scale; the external DXF audit bead and the SOLIDWORKS DXF import bead are
   filed, blocked. The audit (no errors in LibreCAD and DWG TrueView or ODA) is
   run once the user has installed them; release does not wait for it
   (section 12.2).
9. **Email:** the MAPI route against a stub; the webmail route with the user
   present, Gmail's compose page opening with the subject and the PDF
   selected; the PRELIMINARY warning for unreleased drawings.
10. **Review:** the rubric targets of section 20.4.
11. **Docs and security:** `docs/drawings/` describes what was built with each
    claim labelled, and says "follows ASME practice as summarised" until the
    standards are bought; `docs/SECURITY_REVIEW.md` covers the child processes,
    the files written next to the part, signatures and the mail routes;
    AGENTS.md's safety rule names the drawing files.

### Stage 2

1. Turned goldens: a solid shaft; a bored shaft (half section, one-arrowhead
   diameters); two equal bearing seats (each dimensioned, or `2X Ø` with
   attachments to both); a keyseat (removed section, depth from the opposite
   side); a long shaft (broken view); a hex end (across flats); a flat and a
   cross hole at 30° (angular graph); runout to A on every diameter but A.
2. Auxiliary goldens: the inclined face with a hole and a slot is complete (no
   longer reduced-dimension); virtual sharps where needed.
3. The same part as SLDPRT, STEP and `.x_t` gives the same plan summary.
4. Automatic details move only sizes and inside-circle locations.
5. The corpus sweep's turned-style parts: at least 85 % complete with no
   error-level check (a target, set after measuring).

### Stage 3

1. Request and reply schemas tested on both sides; the bridge builds with its
   operations.
2. In SolidSeas' own SOLIDWORKS, with the user's permission and their session
   untouched: the SLDDRW of every stage 1 golden opens, its views match the
   plan's directions and positions, the reply reports each dimension placed or
   why not, and the read-back agrees.

### Stage 4

Each bead carries its own checks, written when it is filed.

## 22. Drafting rules, ranked

The ASME and ISO standards are copyrighted. These rules are in our own words,
with clause references where we are confident of them; nothing is quoted. A
value from common practice rather than a standard is marked (practice); a
detail not confirmed from a public source is marked (verify) and is checked
against a purchased copy before SolidSeas claims conformance. The public-domain
NASA Goddard Engineering Drawing Standards Manual (X-673-64-1F, 1994), built on
the ANSI and ASME Y14 series, is the main public source for values. Core 2
copies this section into `docs/drawings/standards.md`.

**Which documents govern what (ASME profile):** sheet size, format, zones and
title block, Y14.1-2020; drawing practice, Y14.100 (a single part is a detail
drawing, Y14.24); lines and lettering, Y14.2; views, projection and sections,
Y14.3; dimensioning and tolerancing, Y14.5-2018 (its fundamental rules in
section 4.1); threads, B1.1 (Unified), B1.13M (metric) and Y14.6
(representation); surface texture, Y14.36 and B46.1; revisions, Y14.35;
reduced-dimension drawings, Y14.41; additive manufacturing, Y14.46-2022 with
ISO/ASTM 52900 (terms and process categories) and 52901 (what a buyer
specifies). The ISO profile (stage 4) uses ISO 5457, 7200, 128-2 and 128-3,
5456-2, 129-1, 8015 and 2768-1 (ISO 22081 replaced 2768-2 in 2021, and a new
single-part ISO 2768 reached publication in June 2026).

**P0: without these the drawing is wrong or misleading**

1. True orthographic projection with the profile's projection angle (third
   angle for ASME, Y14.3), views aligned with their parent at one scale, and the
   projection symbol shown.
2. A units statement once, and numbers formatted per unit: inch without a
   leading zero, its decimals tied to the tolerance; millimetre with a leading
   zero (Y14.5 section 4). Displayed values must equal the model within a
   fraction of the tolerance, or be flagged.
3. Every dimension toleranced, directly or through the general block or a note;
   only reference, MAX, MIN, stock and basic dimensions (the last with a frame)
   are exempt (Y14.5-2018 4.1). Block values are the company's choice.
4. A complete, non-redundant set: every feature's size, form and location
   determined with nothing to scale or assume, and each characteristic
   dimensioned once, a derivable one only as a reference in parentheses
   (Y14.5-2018 4.1). As a check: per axis the positions form a connected graph
   (complete) with no cycle (not redundant); sizes appear once, patterns once
   with nX.
5. Dimensions on visible geometry in true-shape views: Ø for full circles and
   cylinders, R for arcs of 180 degrees or less, hole sizes in the circular view
   by leader, turned diameters on the profile view, nothing dimensioned to a
   hidden line (Y14.5-2018 4.1; NASA 3.5).
6. A title block with company (the design activity), title, drawing number,
   revision, size, scale, sheet n of m, dates, approvals, material, finish, the
   tolerance block, the projection symbol and the governing standard (Y14.1;
   NASA 1.4).
7. Hole and thread callouts in the standard grammar: count, Ø, THRU or depth,
   the counterbore, spotface and countersink symbols, a thread designation per
   B1.1 or B1.13M with its depth; threads only after the user confirms them,
   since geometry alone cannot prove a hole is threaded (Y14.5 symbols; Y14.6).

**P1: standard-conformant presentation**

8. Sheet format: size, border, margins (A and B 0.38 in, C to E 0.50 in, NASA
   1.1; verify Y14.1-2020's A size), zones (letters up from the bottom, numbers
   leftward from the right), the title block lower right and the revision block
   upper right (Y14.1, Y14.35).
9. Line widths about 2:1, thick 0.6 mm and thin 0.3 mm at least (Y14.2 as
   publicly summarised); visible thick; hidden, centre, dimension and hatch
   thin; centre marks and axes on every round feature; visible lines win over
   hidden, hidden over centre (practice).
10. Lettering at least 3 mm (0.12 in) for dimensions and notes, larger for
    labels, title and drawing number, upper case, no squeezed or stretched text
    (Y14.2; NASA 3.3.2 forbids fitted text).
11. Dimension layout: the first dimension line at least 10 mm from the outline
    and rows at least 6 mm apart (Y14.5 figure 4-6 as publicly summarised);
    extension lines with a visible gap of about 1.5 mm and an overrun of about
    3 mm (practice); filled arrows about as long as the text height at 3:1
    (practice); shorter dimensions inside longer ones; no dimension line crosses
    another; unidirectional text; inclined leaders ending in a short shoulder,
    radial on circles; nothing crosses dimension text.
12. View choice: the fewest views that define the part; the most descriptive
    front (most true shape, fewest hidden lines, natural or machining position,
    longest dimension horizontal); principal views not labelled; sections for
    hidden internal features, detail views for small ones; preferred scales;
    labels SECTION A-A and DETAIL B SCALE 4:1; letters without I, O, Q (and X,
    after NASA 3.5.5), never reused (Y14.3; NASA 3.5).
13. Arrangement: baseline from the origins by default, chain only where
    functional, ordinate as an option, turned lengths from one datum face
    (Y14.5 section 4). Baseline limits the stack between two features to the
    sum of their two tolerances (corrected: an earlier note said baseline had no
    accumulation at all).
14. General notes for the most common fillet radius, edge breaks and the
    default finish; chamfers as `leg X angle` or two legs (practice; NASA
    title block). Never TYP for repetition: Y14.5 states repetition with nX.
15. Note sets per manufacturing type (machined; turned; 3D printed with
    process, material, layer height, build direction, post-processing,
    critical dimensions and model-governs, per Y14.46 and ISO/ASTM 52901), and
    the material and finish mapping.

**P2: later or optional** (with what this design moved into stage 1)

16. The revision block's history with Y14.35 lettering and an explicit release
    action. Moved to stage 1 (signing and revisions).
17. Dual dimensioning, off by default, primary unit first and the secondary in
    brackets, converted limits rounded inward (ISO 370 principle). Stage 4.
18. Datum feature symbols and GD&T. **Corrected:** an earlier note treated
    datums as optional drafter items; stage 1 has the minimal layer of section
    10.5 (datums A, B, C, basic locations, position on holes and slots, one
    general profile note, a frame editor), as the user decided.
19. Surface texture symbols per face (Y14.36). Stage 2, with turned parts.
20. Simplified thread graphics (stage 1 for confirmed threads), broken views
    and half sections (stage 2), hole tables (stage 4), knurls, centre holes
    and undercuts (drafter items).
21. Exact symbol proportions (the projection symbol, GD&T symbols, the ISO
    13715 edge symbol, the surface texture symbol), checked against purchased
    standards (verify).

**What "fully dimensioned" means here.** For the features the generator
recognises: every one has its size once (once per pattern with nX) and its
location once per axis from the chosen origins; every dimension is toleranced;
every dimension is on a visible edge in a true-shape view, legible at the sheet
scale and clear of other annotation; and anything not dimensioned is listed and
covered by the model-governs note. It does not promise functional correctness:
the generator cannot know which faces mate or how the part is inspected.

**ISO profile parameters (stage 4), for reference:** first angle by default
(third selectable); A4 to A0; a 20 mm left border and 10 mm elsewhere; 50 mm
zone fields; lines 0.5 and 0.25 mm (A4, A3) or 0.7 and 0.35 mm (A2 up); text
3.5 mm, letters 7 mm; aligned text above the line; count prefix `4×`; ISO 2768
class m with ISO 8015; labels "A-A" and "B (5:1)"; preferred scales 1:1, 1:2,
1:5, 1:10, 2:1, 5:1, 10:1; row spacing 7 mm, extension gap and overrun 1 and 2
mm (practice); the ISO 13715 edge symbol.

**ISO 2768-1 permissible deviations** (numeric facts, needed in stage 1 for the
millimetre ISO 2768-m option; `drawing/standards.py` holds them). Under ISO
2768 the number of decimals does not select the tolerance.

| Linear size, mm | f | m | c | v |
|---|---|---|---|---|
| 0.5 to 3 | ±0.05 | ±0.1 | ±0.2 | none |
| over 3 to 6 | ±0.05 | ±0.1 | ±0.3 | ±0.5 |
| over 6 to 30 | ±0.1 | ±0.2 | ±0.5 | ±1 |
| over 30 to 120 | ±0.15 | ±0.3 | ±0.8 | ±1.5 |
| over 120 to 400 | ±0.2 | ±0.5 | ±1.2 | ±2.5 |
| over 400 to 1000 | ±0.3 | ±0.8 | ±2 | ±4 |
| over 1000 to 2000 | ±0.5 | ±1.2 | ±3 | ±6 |
| over 2000 to 4000 | none | ±2 | ±4 | ±8 |

| External radius or chamfer height, mm | f, m | c, v |
|---|---|---|
| 0.5 to 3 | ±0.2 | ±0.4 |
| over 3 to 6 | ±0.5 | ±1 |
| over 6 | ±1 | ±2 |

| Angle, by the shorter side, mm | f, m | c | v |
|---|---|---|---|
| up to 10 | ±1° | ±1°30' | ±3° |
| over 10 to 50 | ±0°30' | ±1° | ±2° |
| over 50 to 120 | ±0°20' | ±0°30' | ±1° |
| over 120 to 400 | ±0°10' | ±0°15' | ±0°30' |
| over 400 | ±0°5' | ±0°10' | ±0°20' |

## 23. Measured geometry numbers

From the prototypes, on the fixtures and on seeded samples of the private
corpus (376 parts with solids for recognition and orientation, 34 parts and 136
views for hidden lines, 183 parts for output entities, 122 section cuts).
Counts only.

| Measure | Value |
|---|---|
| B-rep sources | SOLIDWORKS parts, Parasolid files, STEP and Alibre all end as one in-memory Parasolid transmit in metres; o02 read as STEP, `.x_t` and `.x_b`, and o11 as `.x_b`, gave the same faces, edges, box and holes as the SLDPRT |
| Tessellator coverage | 99.83 % of the faces of 1,360 parts tessellated; 1,733 of 1,754 solids closed |
| Faces by surface (376 parts) | plane 70,330; cylinder 14,990; swept 4,783; B-spline 4,667; torus 1,853; cone 1,390; sphere 302; spun 216; `BLENDED_EDGE` 342 in 37 parts (9.8 %) |
| Parts by richest surface | planar only 34 %; analytic 36 %; free-form 20 %; with `BLENDED_EDGE` faces 10 % |
| Tangent edges | 15 % of 239,592 edges; 2.8 % of projected edge length in the principal views |
| Units stated (376 SLDPRT) | millimetre 144, inch 20, none 212 (56 %); among the 13 drawn parts 5 inch, 6 millimetre, 2 none |
| Alignment | largest planar faces on the model axes in 89 %; a face-frame box smaller in 5 % |
| Longest extent | X 45 %, Y 32 %, Z 24 % |
| Flat parts | 38 % have their smallest extent under 25 % of the largest; of those only 54 % are thin along Z |
| Hole axes | 1,627 of 1,665 full holes along a model axis; 45 of 172 parts with holes have holes in more than one direction |
| Needs an auxiliary view | 18 of 376 parts (4.8 %) |
| Datum frame | three square planes in 78.7 %, two in 10.1 %, fewer in 11.2 % (33 of those 80 are turned); complete in all 13 drawn parts |
| Turned | 5.3 % wholly turned, 6.4 % at least 80 %; the "looks turned" rule 6.9 %; none of the 13 drawn parts |
| Machined-style | all faces analytic on three square directions: 47 % of parts |
| Holes | 1,665 full holes in 172 parts: simple 1,361, countersink 153, counterbore 49, stepped 33, stepped and countersink 26, counterbore and countersink 23, other combinations 20; through 1,420, blind flat 225, drill point 20; countersinks 188 at 90°, 13 at 60°, the 82° inch countersink nearly absent; 587 partial holes; 384 stacks with an edge-break torus |
| Threads | 88 of 1,361 simple holes match a standard tap drill (metric coarse M3 to M16, UNC and UNF #4 to 1/2, within 0.01 mm); 74 an ISO 273 clearance; 11 of 261 hole and thread features name a designation |
| Patterns | circular 53, linear 103, grid 16, scattered 51; in 21 % of parts, 818 holes |
| Slots | 138 in 29 parts (7.7 %) by the strict rule; length over width 1.3 to 6.0 |
| Pockets and steps | pocket floors in 35 % of parts; steps in 60 % |
| Blends | 14,586 in 51 % of parts; radius exact for 79 %; 3 distinct radii at the median, 13 at the 90th percentile; one radius in 23 % |
| Chamfers | 548 planar, 240 conical, in 26 % of parts |
| KeyWords | 1,463 of 3,081 parts carry a dimension value; used as a hint only |
| Recognition time | median 7 ms, 90th percentile 0.30 s, max 13 s |
| Hidden-line accuracy | against a 4x finer reference, within 0.25 % of the diagonal: visible precision and recall 0.9993 and 0.9998 (mean); hidden recall 0.997 weighted by length; time per view 0.17 s median, 1.40 s at the 90th percentile, 5.2 s max |
| Mesh-only hidden lines | hidden precision 0.53 to 0.63 on o11: a fallback for mesh formats only |
| Z-buffer | as accurate as ray casting, 30 to 50 times slower in pure Python |
| Silhouette refinement | 0.020 s on o11; 0.93 s on a B-spline-heavy part when every point was re-inverted without a (u, v) start |
| Output entities | lines 98.6 %, arcs 0.6 %, ellipse arcs 0.2 %, splines 0.5 % of projected length; 61 % of parts all exact entities, 80 % at least 90 %, 10th percentile 60 % |
| Sections | 444 loops, 392 closed, open only on the 5 meshes that were not closed; cut 2 ms median (30 ms max); hatch 1 ms median (0.35 s max); view behind 0.10 s median, 1.6 s at the 90th percentile, 6.1 s max; points within 1.8 chords of curved surfaces |
| Chord | Normal 1e-3 of the diagonal; Fine 2.5e-4 (1.12 times the triangles at the median, 3.5 at most; 1.2 times the time at the median, 3.6 at most); Draft 2e-3 |
| Memory | about 4.7 KB a triangle in the prototype |
| Layout | an exhaustive callout candidate 411 µs, a linear one 193 µs |
| Corpus drawings | 26 drawings referencing 13 distinct parts (6 to 463 faces); at most 6 views and one sheet each |
| Corpus bounds | faces at most 34,863 (99th percentile 6,114); edges at most 78,706 |

## 24. What needs the PC

The cloud and the VM build and test stage 1 from the repository's fixtures and
synthetic parts. These checks need the Windows PC, the private corpus,
SOLIDWORKS or the user, and go there as requests through the exchange:

1. **Core 1's speed and memory** on the 13 drawn parts and the size-band
   sample, which fix the targets of section 8.12.
2. **The corpus sweep** of section 20.3, counts only.
3. **The SOLIDWORKS import of the DXF** (whether DIMENSION entities stay
   measuring dimensions): a separate bead, blocked until SOLIDWORKS is free; in
   SolidSeas' own SOLIDWORKS through the bridge once it has an operation for
   it, or by hand with the user's permission.
4. **SOLIDWORKS' own DXF views** of the synthetic hidden-line fixtures, for the
   independent comparison of section 8.4, numbers only.
5. **The DXF audit** in LibreCAD and DWG TrueView or the ODA File Converter,
   once the user has installed them: a bead of its own, which neither
   `dwg-dxf` nor the release waits for (section 12.2).
6. **PDFs** in Edge, Chrome and Acrobat Reader, and printed to scale.
7. **Email PDF** with the user present: Gmail's compose page, and the attach
   route if a classic Outlook or Thunderbird is ever installed.
8. **The engineer's review** of section 20.4 on about ten of the user's parts;
   only scores leave the PC.
9. **The packaged viewer's** `--drawing-dry-run`.
10. **All of stage 3**, in SolidSeas' own SOLIDWORKS.

## 25. OCCT cross-check, for development only

Open CASCADE is not part of the drawing engine (`docs/OCCT.md`). On sampled
corpus parts its two hidden-line algorithms and the prototype agreed on the
same lines (120 views: visible precision 0.9999 and recall 0.9926, hidden
precision 0.9894 and recall 0.9973), but OCCT was slower in the tail (up to 91 s
for one view, two section cuts hung past 120 s), its output edges carry no link
to their source edges, and its exact algorithm drew part of a hidden torus
outline of o11 as visible when it read SolidSeas' own STEP of it (`docs/OCCT.md`
says how much of that the seam fix removed).

As a development tool it is useful: a three-way vote between `dwg-views`,
OCCT's exact hidden-line algorithm (`HLRBRep_Algo`) and its polygon-based one
(`HLRBRep_PolyAlgo`) shows which engine is wrong where they disagree (in the
evaluation the prototype was the odd one out in 16 of 50 disagreements, and
the vote found real misses). It runs only in the opt-in OCCT tier: tests marked
`occt`, skipped unless `SOLIDSEAS_OCCT_PYTHON` names an interpreter where
`import OCP` works, OCCT only in a child process in a Job Object with a memory
cap and a timeout, as the STEP oracle runs. Never a dependency of
`solidseas.drawing`, never in the viewer executable. Whether OCCT's
polygon-based algorithm could accelerate hidden lines is a stage 4 question; it
would need a direct geometry hand-off and source-edge mapping, not a route
through STEP.

The harness is built (`tests/test_occt_drawings.py`, `tests/drawing_occt.py`
and the child `tests/occt_hlr_child.py`; `tests/README.md` says how to run it).
It votes on each of the six principal views of a part, with hidden lines, and
checks the drawing SolidSeas plans for it: every linear dimension must measure
between places where OCCT draws a line in that view, a round feature by both its
sides, and every diameter a circle OCCT draws. Since OCCT's edges carry no link
to their source edges, this is how a dimension is checked against it. On the
fixtures o02, o07, o10, o11 and o12 the engine is never the odd one out in the
thirty views and every dimension checked is on OCCT's lines; OCCT's exact
algorithm is the odd one out in o11's right and left views (2.5 mm of hidden
torus outline drawn visible, `docs/OCCT.md` 6.1). `python tests/drawing_occt.py
PART` runs it on any part, the corpus included.

## 26. Questions and their defaults

| # | Question | Status and answer |
|---|---|---|
| Q1 | How hole and feature locations are toleranced on machined parts | **Answered:** datums A, B, C with basic locations and position tolerances (Ø.010 at MMC, Ø0.25 mm) on holes and slots, and a general profile of .020 (0.4 mm) to A, B, C; plus/minus available per drawing; printed parts plus/minus under the process note |
| Q2 | General tolerance values; decimal block or ISO 2768-m for millimetre drawings | Default stands: the inch block of section 7.3; the millimetre decimal block with ISO 2768-m as an option |
| Q3 | The unit for parts that state none | Default stands: guessed from round numbers and confirmed every time; inch when it cannot tell |
| Q4 | Approval rows, which must sign before release, one person on two rows, first revision | Default stands: DRAWN, CHECKED, APPROVED; CHECKED and APPROVED required; yes with a warning; A |
| Q5 | Turned parts in the first release or in 1.1 | **Answered:** 1.1 (stage 2) |
| Q6 | ISO drawings | Default stands: later (stage 4) |
| Q7 | Which mail program | **Answered:** Gmail or other webmail in a browser; section 15.5 |
| Q8 | Saving next to the part | **Answered:** yes, next to the part under the 3D Print file's safety rules, never replacing a file SolidSeas did not write; a setting for another folder. Q14 settles what Save may replace |
| Q9 | Installing DXF checkers on the PC | Default stands: the user installs LibreCAD and DWG TrueView if wanted; nothing is downloaded without explicit permission |
| Q10 | Buying ASME Y14.5-2018, Y14.1-2020 and Y14.35 | Default stands: the user's purchase decision; verify items stay marked until then |
| Q11 | The APAFML notice and the `.ssdrw` extension | Default stands: yes to both |
| Q12 | (Before stage 3) Keep DimXpert out of the SOLIDWORKS drawing, since it saves into the part | Recommended: keep it out; ask before stage 3 |
| Q13 | (Before stage 3) May the run relink a model-linked title field in the new drawing's own copy of the sheet format | Recommended: ask each time; ask before stage 3 |
| Q14 | May Save replace the drawing's own `.ssdrw`, and rewrite its PRELIMINARY PDF and DXF to keep them current, when SolidSeas wrote them and they are unchanged since? The 3D Print file never replaces any file, so this goes beyond its rule | **Answered (2026-10-05):** yes, for SolidSeas' own unchanged files only (section 12.6). `replace_own_files` is on by default; a setting turns it off, and then every write is a new file |

## 27. Risks

- **Automatic datums and tolerances are not design intent.** The wizard shows
  the datums and why they were chosen, the values come from the company's
  Settings, the drawing stays PRELIMINARY until a person signs it, and the
  review rubric judges function.
- **GD&T done partly is worse than none.** The layer is deliberately small,
  every frame is checked for grammar and datum references, and the planar-width
  interaction is a verify item for the user's review.
- **The plan and layout stream is long and critical.** The slice measures it
  first, the contracts wait for it, it has one owner, and the slip order of
  section 3.3 protects the release.
- **Speed on free-form parts.** Core 1's fixes are expected to remove most of
  the per-view cost; targets are set only after measuring them; Draft quality
  and an up-front refusal protect the user's time.
- **Regeneration matching is heuristic.** Unmatched items are reported, never
  silently re-assigned; four regeneration goldens and the o02 to o07 pair test
  it.
- **DXF in SOLIDWORKS** is unverified until SOLIDWORKS is free; the docs say so.
- **Standards wording** until the standards are bought, and the font:
  Helvetica is not the single-stroke lettering Y14.2 describes, though common
  CAD practice accepts it.
- **Merges:** `window.py` and `selftest.py` change on other branches; the
  drawing hooks stay a few lines.
