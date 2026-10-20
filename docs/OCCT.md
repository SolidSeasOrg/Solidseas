# Open CASCADE (OCCT) in SolidSeas

The question, asked on 2026-10-04: should SolidSeas use Open CASCADE
(github.com/Open-Cascade-SAS/OCCT)? This document records the answer and what
the evaluation found. It measured OCCT 7.9.3, through `cadquery-ocp` 7.9.3.1.1
(the OCP bindings), installed in a Python environment of its own on the PC,
against SolidSeas' STEP export, its readers and the drawings prototype. Four
research tracks (STEP export checks, the format readers, drawings, and
architecture and licence) were followed by a pass that re-ran every number the
verdict rests on that looked surprising.

Corpus results are counts. Where a defect needs a name, a private STEP file is
called `step#N`, its index among the STEP files of the corpus folders in
sorted-path order, which means nothing outside the PC; this document uses
eleven such keys, each for a defect it names. A part of the corpus is called by
its manifest row on the same terms.

## 1. Verdict

Use OCCT as a tool around SolidSeas, never inside it.

| Use | When | Evidence |
|---|---|---|
| Test oracle for the STEP export | now, development only | 162 corpus STEP files and 13 fixtures written by SolidSeas read with no crash and no failed transfer. Volume against SOLIDWORKS' own values (140 parts): median 1.8e-14, 90th percentile 7.8e-6, max 1.9e-4, as close as SOLIDWORKS' own STEP round trip (90th percentile 6.3e-6, max 3.1e-4) |
| Test oracle for the STEP reader and the tessellator | now, development only | exact area and volume per face and per shell; it found four kinds of reader defect (section 7) |
| Cross-check for drawings (`dwg-views`) | development only | a three-way vote between SolidSeas' engine and OCCT's two hidden-line algorithms shows which one is wrong (section 8) |
| IGES import and export | now: the OCCT backend extension (tier 1), with bead SolidSeas-e2z | SolidSeas lists IGES but cannot read it. Of 142 IGES files in the corpus folders (138 distinct) OCCT gets a shape from 134, 13 holding solids directly; of the 120 holding only surfaces, sewing at 0.01 mm closes 97 into solids, 6 partly, and 17 stay open. Fixture IGES files round-trip within 3.6e-11 |

| Do not use for | Why |
|---|---|
| Replacing the STEP reader | Of 1,328 distinct corpus STEP files SolidSeas read 1,317 and OCCT 1,316; OCCT cannot open the 8 zip-compressed ones. On 124 damaged files SolidSeas never crashed or hung; OCCT did on 18. Median peak memory 26 MB against 131 MB, the largest 354 MB against 6.1 GB. OCCT is faster on most files (read and transfer 0.097 s median, against SolidSeas' open and scene at 0.865 s), but not on all of the largest |
| The drawing engine (stage 1) | The same quality over 120 views (visible lines precision 0.9999 and recall 0.9926, hidden lines 0.9894 and 0.9973), a worse tail (up to 91 s for one view, 274 s for four views of one part, two section cuts hung past 120 s), output edges with no link to their source edges, and a wrong result on o11 read from SolidSeas' STEP (section 6.1) |
| STL, OBJ, PLY, 3MF and glTF | On STL both read the same 59 of 60 files with volumes within 1e-12; this OCP build has no OBJ or PLY module and OCCT has no 3MF support at all |
| 3D-print repair and booleans | OCCT works on B-reps, not broken meshes, so it would need the STEP export first, which refuses about 7 % of corpus parts and takes up to 25 to 34 s on large ones. Revisit only if a B-rep boolean is needed, such as fusing touching bodies before printing |
| Parasolid, SLDPRT, SLDASM and feature history | OCCT reads and writes none of them; SolidSeas' readers and the SOLIDWORKS bridge keep that work |
| The core library, the viewer executable, the Linux default install | the footprint below, the crash behaviour (section 3) and the LGPL duties of bundling (section 4) |

Footprint, measured in the CadQuery environment:

| Package | Size |
|---|---|
| `OCP` | 94 MB |
| `cadquery_ocp.libs` | 65 MB |
| `vtk.libs` (`cadquery-ocp` requires `vtk` 9.6.2) | 277 MB |
| `vtkmodules` | 51 MB |
| the whole CadQuery environment (casadi 230 MB, llvmlite 122 MB and scipy 115 MB among it) | 1,198 MB |

`import OCP` takes 0.75 to 1.0 s and leaves 126 to 197 MB resident before any
work.

## 2. Integration tiers

### Tier 0, now: an opt-in test oracle, never a dependency

- **Gating.** Tests are marked `occt` and skip unless `SOLIDSEAS_OCCT_PYTHON`
  names an interpreter where `import OCP` works, the same pattern as the
  corpus-gated and SOLIDWORKS-gated tests. Linux CI stays green with nothing
  installed; an optional CI lane can install `cadquery-ocp` later (Linux wheels
  are not yet verified). The library never imports OCP, and a default test
  parses every module under `src` to keep it so.
- **Process model.** SolidSeas does its own work in-process. OCCT runs only in
  a child started with the OCP interpreter, importing the standard library and
  OCP alone: started suspended in a Job Object (kill on close, die on an
  unhandled exception, a memory cap, a process limit, below-normal priority),
  then resumed. The request goes in on standard input and one strict JSON line
  comes back; OCCT's own output goes to the null device, and of standard error
  only an exception's class name is kept.
- **Fixture tier** (5 to 10 s): read status done, every root transferred,
  every solid's shells closed, `BRepCheck_Analyzer` valid; "Missing seam-edge
  added" the only healing message allowed; Gauss-Kronrod volume, adaptive area
  and centre of mass within 1e-12 of `tests/fixtures/ground_truth.json`; the
  box within 1e-8 of the diagonal; OCCT's own fine mesh within 1e-4 of its
  integrators. SOLIDWORKS' STEP of o02 passes the same checks, as a control.
- **Reader tier:** SolidSeas' mesh of a STEP file against OCCT's reading of it,
  face by face (paired by centroid and area), shell by shell (signed volumes of
  the mesh's connected pieces) and in total, which pins a defect to one face
  and one surface type. Each reader defect is also reproduced in a synthetic
  file the tests write.
- **Corpus tier** (with `SOLIDSEAS_CORPUS_MANIFEST`, about 5 minutes for 175
  parts on 4 workers): the same structure checks, about 1e-3 on volume and
  area, parts with hidden bodies and degenerate sheets box-compared or skipped,
  and a list of parts known to be invalid.
- **Pin the OCP version** (`cadquery-ocp` 7.9.3.1.1, OCCT 7.9.3) and record it
  in every result.

This tier is built: `tests/occt_child.py` and `tests/occt_solidseas_child.py`
(the children), `tests/occt_support.py`, `tests/occt_shapes.py` (the synthetic
files), `tests/test_occt_oracle.py`, `tests/test_occt_corpus.py`,
`tests/test_occt_support.py`, `tests/README.md` (how to run the opt-in tests)
and section 11 of `docs/formats/step.md`. The reader defects its synthetic
files reproduced are fixed, and OCCT and the reader now agree on those files.

### Tier 1, with bead SolidSeas-e2z: an optional `occt` conversion backend

- Behind `solidseas.convert`'s backend seam. It reads IGES (STEP and OCCT's
  BREP as alternatives) and writes IGES and BREP. The engine offers it only
  when `import OCP` works; otherwise it is a capability gap, as the AI seam's
  are.
- It imports `OCP` directly, never `cadquery`: a converter has no use for
  casadi (LGPL-3.0-or-later), numba or scipy.
- It runs in a helper program of its own, the OCCT backend extension's
  (`docs/EXTENSIONS.md` section 9), started through `solidseas.helpers.Helper`:
  suspended, in a Job Object with kill on close, a memory cap and die on an
  unhandled exception, with `SetErrorMode` called in the helper; elsewhere than
  Windows the helper sets its own `RLIMIT_AS`, no core file and
  `PR_SET_PDEATHSIG`. (The plan was jobs in SolidSeas' own `WorkerPool`; a
  packaged helper keeps OCP and its 160 MB out of the viewer, which the worker
  processes share.)
- IGES: read, sew at 0.01 mm, run the validity check, and report the solids and
  any open shells that remain as they are. IGES manifold solids (entity 186)
  give solids directly. Export in BRep (MSBO) mode.
- The rules of section 3 apply to every file.

This tier is built: `solidseas_app/extensions/occt_helper.py` (the helper),
`solidseas/convert` (the seam and the `occt` backend), `solidseas/formats/occt.py`
(IGES and BREP documents: the IGES head read in pure Python, the geometry from
the helper's STEP model read by SolidSeas' own STEP reader), `solidseas convert`,
the package's build step in `scripts/build-extensions.ps1` and its notices
(`THIRD_PARTY_NOTICES.txt` section 3.4), and `tests/test_occt_backend.py`. It
differs from the plan above in three ways. It reads into STEP, not into
SolidSeas' own Parasolid bodies directly, so an IGES or BREP file is then read
exactly as a STEP file is. The package carries OCP from the `cadquery-ocp-novtk`
wheel, which drops VTK: the evaluation could not install it on the PC, but its
Windows wheel exists for 7.9.3.1.1. And it reads STEP only as a source to
convert (`solidseas convert part.step --format iges`); SolidSeas' own STEP reader
stays the one that opens STEP files. The first Windows build of the package, and
the security review of row 15 (section 9), are still to come.

### Tier 2, later and separate

- The CadQuery workspace (SolidSeas-03q) is a separate, heavier extra: the full
  `cadquery`, with casadi and VTK.
- OCCT's polygon-based hidden-line algorithm as an accelerator for drawings is
  a stage 4 question only (`docs/DRAWINGS.md` section 25).

### Never

- In the `solidseas` core import path.
- In `SolidSeasViewer.exe`, whose PyInstaller spec already excludes cadquery
  and numpy.
- In the default install on the Linux VM.

## 3. Rules for untrusted files

- Use the basic `STEPControl_Reader` only. The XCAF reader
  (`STEPCAFControl_Reader`) follows external references out of the file's
  folder and to absolute paths: on a test file it opened a `..\..` reference
  (2 solids when the target existed), and it opened a system file by absolute
  path. A UNC path would mean an SMB connection and a leaked NTLM hash. The
  basic reader did not follow the reference.
- Read a multi-file STEP only from a staged copy in an isolated folder.
- Never pass a network path.
- Keep a hard memory cap: under memory pressure OCCT dies with an access
  violation, not an exception that can be caught.
- Set a timeout on every call. Transfer took up to 75 s, and section cuts hung
  past 120 s.
- Never parse OCCT's own output, and treat every reply as data.
- Suppress crash dumps. Windows Error Reporting can be set to keep a local dump
  of every crashing program, and a dump of a process holding a private file is
  a copy of it. A child that may crash runs with die on an unhandled exception
  in its job, a quiet error mode (`SEM_NOGPFAULTERRORBOX`) inherited from the
  moment it is created, and is started suspended and placed in the job before
  it runs. Building the oracle found that a child in a job that faults without
  a quiet error mode of its own does not end: Windows Error Reporting waits for
  a `WerFault.exe` the job refuses, until the timeout kills it. The
  evaluation's first crash run, before these settings, left dumps of altered
  fixture copies (no customer data); they have been deleted.

What OCCT did with damaged input (fixture copies altered on purpose, and
hand-made files):

| Input | Crashed or hung | How |
|---|---|---|
| Altered STEP files | 16 of 120 | 13 access violations, 2 stack overflows, 1 hang |
| Hand-made STEP files | 2 of 4 | stack overflows on a self-referencing placement and on deep nesting |
| Altered IGES files | 39 of 120 | 38 access violations, 1 stack overflow; 36 of them from the BRep-mode IGES of one fixture |

54 crashes came while transferring the file into shapes and 2 in the parser.
On real corpus files OCCT ran 3,027 child runs without a crash.

## 4. Licence position

This is an engineering reading of the licence texts, not legal advice.

- OCCT is LGPL-2.1 with the Open CASCADE exception 1.0. The exception relaxes
  only LGPL section 5, for object code that includes OCCT header material
  (inline functions and templates); it changes nothing for the OCCT binaries
  (section 4) or for a combined work (section 6).
- SolidSeas is pure Python, calls OCP's bindings and uses no OCCT headers, so
  its code is a "work that uses the Library", never a derivative. Apache-2.0
  code using LGPL-2.1 code is compatible in this direction, and calling OCCT
  from a separate process over JSON removes any doubt.
- **`pip install solidseas[cad]`:** pip fetches `cadquery-ocp` from PyPI and
  SolidSeas ships no OCCT binary, so SolidSeas has no section 6 duty. Still
  name OCCT and its licence in `NOTICE`, and say that the extra pulls in LGPL
  code.
- **Bundling OCCT in the executable or an installer** makes SolidSeas
  distribute the combined work, and section 6 applies: ship the LGPL-2.1 text,
  the exception text, a prominent notice, and the OCCT 7.9.3 source or a
  written offer of it valid for three years. Dynamic linking is already
  satisfied (one `OCP` module and 71 `TK*.dll`). The wheel carries none of
  these texts: its only licence file is `cadquery_ocp\LICENSE` (Apache-2.0),
  and its metadata says Apache-2.0.
- **VTK and CadQuery:** VTK (BSD) is a hard dependency of `cadquery-ocp`. The
  proxy package names a `cadquery_ocp_novtk` variant (`[novtk]`) that would
  drop about 330 MB; it could not be installed here, so verify it before
  relying on it. Full CadQuery adds casadi under LGPL-3.0-or-later, one more
  reason to keep a converter extra (OCP only) apart from a CadQuery workspace
  extra.

## 5. Measurement settings that must be used

- OCCT's default `BRepGProp.VolumeProperties` and `SurfaceProperties` were
  wrong by up to 8.6 % on volume and 4.5 % on area on B-spline-heavy parts.
  Use `VolumePropertiesGK` (Gauss-Kronrod: eps 1e-9, span splitting, centre of
  gravity on) and the adaptive `SurfaceProperties(shape, props, 1e-9)`, and
  where it matters cross-check against a fine mesh.
- The Gauss-Kronrod volume can be slow: 340 s for one 215-face part, and slow
  on 3 corpus files whose sphere and cone caps the seam fix cut (its other
  measures and its meshing are not).
- Even the adaptive area at eps 1e-9 is 1.2 % high on the side of an elliptic
  prism (a `SURFACE_OF_LINEAR_EXTRUSION`), where OCCT's mesh and SolidSeas agree
  with the exact area. So a face agrees with OCCT when it agrees with either of
  OCCT's measures (the adaptive area or its mesh), and on a cylinder, sphere or
  torus it is also allowed its own chord error (the chord over the surface's
  smallest radius). The reader's defects put a face far from both.
- Some forms OCCT cannot referee: edges stored only as pcurves (OCCT removes
  them), `COMPOSITE_CURVE` edges (OCCT converts none), a `SEAM_CURVE` without
  its pcurves (OCCT translates nothing), and an assembly placed by
  `MAPPED_ITEM`s (OCCT transfers one of the two).
- Pin the OCP version and record it in every result.

## 6. What it showed about the STEP export

The export is in good shape: OCCT found no mapping error. Every disagreement
with SOLIDWORKS beyond 1e-6 traced to the source part, to OCCT's own import, to
hidden bodies, or most likely to SOLIDWORKS' mass-property accuracy. SOLIDWORKS
itself reads the export back as closely: imported into SolidSeas' own
SOLIDWORKS, 12 fixture parts come back exact and 130 corpus parts within 1.7e-4
of their volume (`docs/FORMAT.md` 10.9).

### 6.1 Closed faces written without seams

SolidSeas wrote a face that goes all the way round a closed surface (a hole's
cylinder, the round at its entry, a sphere's cap) as one face with no seam
edge; SOLIDWORKS splits such faces. o11 had 12 faces (1 torus, 5 cylinders)
where SOLIDWORKS' STEP has 14 (2 and 6). The file is valid either way, but
OCCT added 587 seam edges in 65 of 162 corpus files; its projected pcurves
strayed more than 1e-3 mm in 14 files (up to 0.16 mm), behind 3 of its 5
validity failures; and its exact hidden-line removal of o11 drew a hidden torus
outline as visible (1.57 mm in the top view, 3.14 mm in the right view) and
lost 1.5 to 3 mm of hidden outline, where on SOLIDWORKS' STEP it was right.

**Fixed:** `step/split.py` cuts such faces in two along the surface's own
iso-parameter curves, as SOLIDWORKS' split periodic faces option does, and
checks each cut again. o11 now has 14 faces, 34 edges and 22 vertices
and o10 8, 18 and 12, the same point sets as SOLIDWORKS' own STEP; OCCT added
no seam to the fixtures and 6 to 6 corpus files (one face each still written
whole: 3 bands whose edge crosses every line more than once, 1 whose holes
cover every line, 2 on apple tori, which are not cut); 553 faces were cut.
OCCT's front view of o11 now matches SOLIDWORKS' file. **Left:** its right view
of o11 still shows 3.1 mm of torus outline as visible; its pcurves still stray
in the same 14 files (its own projections of B-spline edges, unrelated to
seams); writing pcurves was tried and dropped (OCCT's default reader computes
its own); and what SOLIDWORKS does with caps, revolved and B-spline faces is
unknown without a fixture.

### 6.2 Hidden bodies were exported

SolidSeas could not tell which bodies SOLIDWORKS hides and wrote them all, so 4
of 175 corpus parts differed from SOLIDWORKS' volume by 37 %, 48 %, 58 % and
1,800 %. **Fixed:** the body mark SOLIDWORKS keeps
(`BODY_IN_LIGHTWEIGHT_PERM`, 1 shown, 0 hidden) found all 4 hidden bodies on
179 corpus parts, and none of the 280 marked shown is hidden; hidden bodies are
now left out (`include_hidden`, `--include-hidden` write them), and the four
parts match SOLIDWORKS within 1.5e-4. 20 imported bodies carry no mark; a part
with several solids, some unmarked, still writes them all and warns
`step_hidden_bodies_unknown`. **Left:** the fix is in the STEP export only. The
tessellator does not read the mark, so hidden bodies are still tessellated and
still appear in the 3D view and in 3MF and STL prints; only 3D Print's STEP
route sends just the shown bodies. A part that shows only sheets beside a
hidden solid is exported as its sheets, as SOLIDWORKS exports it; one such
part, of 19 sheets (manifest row 89), then stops at the export's 300 s limit.

### 6.3 Coverage

About 7 % of parts are refused: 13 of 175, all `not_representable`
(`fit_failed` 9, `check_failed` 2, `unsupported_surface` 2). Export time per
part: median 0.51 s, 90th percentile 4.6 s, max 25 s; a 2,061-face part took
33.6 s.

### 6.4 Smaller items

- **Tolerant edges.** In 17 files an edge curve lies off its surface by more
  than the file's declared uncertainty (up to 2.4e-3 mm against 1e-5 mm),
  always within the part's own Parasolid tolerance. The exporter warns
  (`step_tolerant_geometry`), and OCCT raised edge tolerances above 1e-3 mm in
  10 files. Whether the declared uncertainty should cover these tolerances is
  open.
- **Small differences.** Thirteen parts differ from SOLIDWORKS by 1.1e-6 to
  1.9e-5, where OCCT's two integrators and a divergence-theorem volume agree
  with each other: most likely SOLIDWORKS' default mass-property accuracy. One
  sheet part's area differs by 4.6e-6, unresolved (SolidSeas' mapping of
  parameter-space edge curves, or OCCT's area on that face).
- **Where the export did better than SOLIDWORKS.** Two parts keep their native
  box where SOLIDWORKS' own round trip loses a sliver (2.6e-3 and 5.9e-3 of
  the diagonal), and a part whose SOLIDWORKS import blocked a session reads in
  OCCT in 4.2 s and is valid.

## 7. What it showed about the readers

### 7.1 Void shells inside out (bug, high impact)

A `BREP_WITH_VOIDS` lists each void as an `ORIENTED_CLOSED_SHELL` marked `.F.`,
which the reader turned round, as ISO 10303-42 reads it. Some writers store
that shell already facing into the void, so the void faced out and its volume
was added: step#38 came out 24.6 % too large (its 7-face void shell exactly the
negative of OCCT's signed volume), step#1389 78 % too large, and a third file
had three small voids the wrong way. 21 of the 1,328 distinct corpus STEP files
have voids, all marked `.F.`. Area agrees, so the viewer looks right, but every
mass property is wrong and an STL or 3MF made from such a body has an
inside-out cavity. OCCT gets them right because its healing orients shells by
their geometry; the reader's `orient.py` could not, since a void shell is a
connected group of its own.

**Fixed:** after tessellation each closed shell of a solid is oriented by its
signed volume, the outer shell positive and every void negative, with the
warning `void_reoriented` (or `solid_reoriented` for an outer shell that faced
in). Of the 20 corpus STEP files with voids that OCCT measures, 14 had a void
inside out. 10 now read right, step#38 and step#1389 among them, which now
agree with OCCT throughout. 4 still have one: step#32, step#1098, step#1099
and step#1104, each of which also has faces skipped or folded or mesh edges
used twice the same way in the oracle's comparison.

### 7.2 Folded, overlapping triangles (bug)

In five files a face on a B-spline or sphere surface had more triangle area
than the whole surface it lies on (12 to 18 times OCCT's area in the worst), so
its triangles fold over each other, with mesh edges used twice the same way or
left open. In one more, two torus faces came out at 3.5 times their area in a
mesh that stays closed, the part's volume 19 % low. None of these surfaces is
closed or periodic. A cheap check without OCCT: per face, the triangles'
absolute (u, v) areas must add up to the area of the face's (u, v) polygon.

**Fixed:** four causes, each reproduced in a synthetic file: a seam run down
to a sphere's pole and straight back up, left in the loop as a slit of no
width; an edge whose curve stops dead at a knot, halved until its samples piled
up; a torus whose major radius is under its minor one, whose (u, v) scaling
made its triangles run the whole way round; and boundary points of a face whose
edges run past its surface's end, several landing on one (u, v) point. At a
0.01 mm chord every face of four of the six files is now within about 1 % of
OCCT's area, but for small faces whose difference is the chord's own sagitta.
**Left:** step#1175 and step#1271, whose plane faces have edges 0.14 to
0.36 mm off their surfaces, lose faces at a fine chord: they fail inversion
there and the solid is left open.

### 7.3 Faces whose loops all run against them (bug)

Every planar face of step#12 (36 of 36) was skipped as `seam_configuration`
with the detail "no loop runs the way of the face", and 8 small files opened
without an error and drew nothing; OCCT draws those faces. **Fixed:** on a
surface that does not close, such a face keeps the sense the file gives it and
its loops are read the other way round, its largest loop the outer one
(`loops_reversed`), as other readers read it; where it disagrees with the faces
round it, a STEP scene's check turns it to agree with them. A plane face with
no loop at all is reported as `no_boundary`, not as a seam problem. The 8 files
that drew nothing now draw all their faces; those faces share no edge, so each
file's solid stays open and says `solids_not_closed`.

### 7.4 Open meshes without a warning (weakness)

In 7 of the 12 files re-checked a solid's mesh was not closed (3 to 186 open
edges), and `scene()` said nothing. **Added:**
`solidseas.tessellate.checks`, cheap pure-Python invariants (every directed
edge used once each way; closed shells signed by their nesting; the per-face
(u, v) area check), counted in `Tessellation.checks` and given as warnings on
the tessellation and the scene (`solids_not_closed`, `shells_inside_out`,
`faces_folded`, `faces_coarse`), and a guard in the STL and 3MF export that
turns round a shell plainly inside out and warns, never refuses
(`shell_reoriented`, `shells_inside_out`, `not_closed`). These checks would
have caught 7.1 to 7.3 without OCCT. **Left:** over the 1,328 distinct corpus
STEP files, against the reader before these fixes, 13 files have more mesh
edges used twice the same way and 4 a few more edges with no partner
(`docs/formats/step.md` section 10), and the 3D prints of step#1149 and
step#1251 stay open, at boundaries a micrometre across that no sampling rule
tried closes.

### 7.5 A body only SolidSeas seemed to draw

In one file SolidSeas drew a 15-face body that OCCT appeared to leave out. The
reader work found that it is the second of two copies of a part
inside the product structure, which OCCT transfers too (the evaluation's
matching missed it), and that two of its B-spline faces had every loop running
against them and were dropped (7.3), leaving its mesh open. With them turned it
closes at 5,571.3 mm³ at a 0.01 mm chord, against OCCT's Gauss-Kronrod 5,571.0.

### 7.6 Flags that were not defects

Three files were flagged only because OCCT's default integrators were wrong
(section 5); with Gauss-Kronrod volume and adaptive area they agree with
SolidSeas.

### 7.7 Skipped faces and speed

- 122 of 1,317 files skip some faces. By reason: `degenerate` 3,643,
  `seam_configuration` 956, `triangulation_failed` 55, `edge_too_long` 53,
  `bad_reference` 32, `inversion_failed` 7. 16 files lose more than 1 % of their
  area (measured against OCCT's default area, so approximate), and 2 lose 90.9 %
  of their faces.
- Median open and scene: SolidSeas 0.865 s against OCCT's read and transfer
  0.097 s, 7.9 times slower (26 times at the 90th percentile; 3.7 times when
  OCCT also meshes). On the largest files the picture is mixed: a 57 MB file
  took SolidSeas 602 s in `scene()` against OCCT's 22 s; a 68 MB file 25 s and
  249 MB against 117 s and 2.4 GB; a 76 MB file 127 s and 354 MB against OCCT
  timing out at a 3 GB cap, then 341 s and 6.1 GB.

### 7.8 Strengths worth keeping

SolidSeas reads zip-compressed STEP (8 files OCCT cannot open); it never
follows external references (`references()` only reports them); and on 124
damaged STEP files it never crashed or hung, refusing 61 cleanly, the slowest in
1.24 s with a 26 MB peak.

### 7.9 Other readers and the tessellator

- IGES and VRML were registered with no reader; there are no VRML files in
  the corpus. OCCT's BREP format was unknown to SolidSeas (one corpus file).
  Both IGES and BREP are now read through the OCCT backend extension (tier 1).
- Parasolid blend faces (`BLENDED_EDGE`) were refused by the tessellator as
  `unsupported_surface`, in 4 of 34 sampled parts, leaving holes in the 3D
  view, in STL and 3MF, and in drawings. **Fixed:** the tessellator draws them
  from the surface the STEP export writes for them, built by the blend
  construction the export already had, now shared (`tessellate/blend.py`,
  `tessellate/fit.py`). On the 222 corpus parts with such blends, 3,185 of
  their 4,280 rolling-blend faces are drawn where none were, and every solid of
  129 of those parts comes out closed; the others are left out for time or
  refused with a reason (`docs/API.md` 3.15). Drawing them takes time: a 3D
  print of such a part now takes a median of 6.4 s, against 4.4 s.
- SolidSeas reads OCCT's own STL and GLB output correctly (o11 is 11,130.76
  mm³ both ways).

## 8. Drawings

On sampled corpus parts the drawings prototype and OCCT's two hidden-line
algorithms (`HLRBRep_Algo`, exact, and `HLRBRep_PolyAlgo`, polygon-based)
agreed on 99 to 100 % of the lines, but OCCT was slower in the tail and its
edges carry no link to their source edges, which dimensions need. As a
three-way vote it is a good development tool: the prototype was the odd one out
in 16 of 50 disagreements, and the vote found real misses (one part where the
prototype missed 17 to 21 % of the visible length, parts with missing hidden
lines, and parts with `BLENDED_EDGE` faces). `docs/DRAWINGS.md` section 25 says
how `dwg-views` uses it: gated like tier 0, never a dependency.

## 9. Where each finding stands

The numbers in the first column are those of the evaluation's proposed beads,
which the VM files after checking for duplicates. "Fixed" and "added" mean done
by the STEP fixes that merged with this document; what they left is said
beside each.

| # | Finding | Priority | Status |
|---|---|---|---|
| 1 | STEP reader: void shells inside out (7.1) | P1 | fixed: of the 20 corpus STEP files with voids OCCT measures, 14 had one inside out; 4 still do (step#32, step#1098, step#1099, step#1104) |
| 2 | STEP reader: folded triangles on B-spline, sphere and torus faces (7.2) | P2 | fixed: at a fine chord every face of four of the six files is within about 1 % of OCCT's area; step#1175 and step#1271 still lose faces there |
| 3 | STEP reader: faces whose loops all run against them dropped; 8 files draw nothing (7.3) | P2 | fixed: the 8 files draw (`loops_reversed`) |
| 4 | Mesh self-checks: closed solids, shell signs, folds (7.4) | P2 | added; the prints of step#1149 and step#1251 stay open, and 13 files have more mesh edges used twice the same way (4 a few more open ones) than before the fixes |
| 5 | Opt-in OCCT oracle tests (tier 0) | P2 | added |
| 6 | STEP export: split closed faces at their seams (6.1) | P2 | fixed: cut as SOLIDWORKS cuts them; the seams OCCT adds went from 587 in 65 corpus files to 6 in 6; the leftovers of 6.1 remain |
| 7 | STEP export: leave hidden bodies out (6.2) | P2 | fixed for the STEP export; unmarked imported bodies are still all written, with the warning; the tessellator still includes hidden bodies, so they still appear in the 3D view and in 3MF and STL prints; row 89, sheets beside a hidden solid and now exported as its sheets, stops at the export's 300 s limit |
| 8 | Tessellate Parasolid blend faces (7.9) | P2 | fixed: 3,185 of 4,280 rolling-blend faces drawn on 222 corpus parts; their prints are slower (median 6.4 s against 4.4 s) |
| 9 | IGES import and export through an optional OCCT backend (tier 1, under SolidSeas-e2z) | P2 | built (tier 1): IGES and BREP read and written through the OCCT backend extension; its package's first Windows build remains |
| 10 | Explain the body only SolidSeas seemed to draw (7.5) | P3 | answered (7.5) |
| 11 | Decide the OCCT extra and its notices: `[cad]` with `cadquery-ocp` only or its `novtk` variant, a separate CadQuery workspace extra, a `NOTICE` entry, never in the executable, Linux wheels checked; ties into hash-locked dependencies (SolidSeas-oib) | P3 | in part: the OCCT package carries `cadquery-ocp-novtk` 7.9.3.1.1, hash-pinned, with its notices (`THIRD_PARTY_NOTICES.txt` 3.4), never in the executable; its Linux wheel imports and passes the tests; the `[cad]` extra is unchanged |
| 12 | Profile the STEP reader on large files (7.7) | P3 | remains |
| 13 | Settle the remaining STEP export differences (6.4): re-measure the thirteen parts and the sheet part in SOLIDWORKS at its highest mass-property accuracy | P3 | remains; PC only, in SolidSeas' own SOLIDWORKS through the bridge, never the user's session; the bridge's `mass_properties` has no per-call accuracy setting yet (`src/solidseas/swapi/README.md`, known issues) |
| 14 | Drawings: keep the three-way OCCT cross-check as a development tool (section 8) | P3 | remains, with `dwg-views` |
| 15 | Security review of the OCCT backend (crash rates, the XCAF reader's external references, crashes under memory pressure, crash dumps, the rules of section 3), under SolidSeas-gc4 | P3 | remains, with tier 1 |
| | Tolerant edges against the declared uncertainty (6.4) | | remains, to consider; no bead proposed |
| | The STEP export's refusals, about 7 % of parts (6.3) | | remains, as the export's known coverage |

The oracle's own corpus run also found two more files that skip faces and
leave their solids open, and one more with torus faces drawn over the wrong part
of their surface (`docs/formats/step.md` section 11). The STEP fixes did not
settle them; the oracle's corpus test reads them on every run.
