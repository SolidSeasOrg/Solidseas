# Test fixtures

Synthetic SOLIDWORKS documents with known contents. SOLIDWORKS 2024 SP1 made
them through its documented API, in a SOLIDWORKS instance of their own, one
controlled change at a time, so every difference between two files has a known
cause. While it made them, SOLIDWORKS also reported what each document
contains; `ground_truth.json` records that, and `generation.log` records each
API step.

## How they were made

The fixture kit (a PowerShell script driving a small C# helper, plus a checker
that compares its output with SolidSeas) lives outside this repository, with
the maintainers' private research tools. Nothing in the test suite needs it.
It starts its own SOLIDWORKS, attaches to that process only, and never touches
a SOLIDWORKS session that someone else is using.

These files come from one run on 2026-10-01 (kit version 2026-10-01.4) in
current-account mode: in the developer's own Windows account, with no setting
changed, rather than in a fresh account. What makes that safe is the choice of
templates, because a document inherits the folder history of the template it is
made from:

- Parts use the account's default part template, which the kit checked before
  the run: it names only that account's bare Temp and Desktop folders, the
  SOLIDWORKS data folder and Windows, and stores no user name but the
  account's.
- Assemblies (o08, o15, o16) use the MBD template
  `assembly 0250mm and smaller.asmdot` and drawings (o18, o19) use
  `ansi.drwdot`. Both are shipped by Dassault and put in place by the SOLIDWORKS
  installer. Their history names Dassault's own build machines and template
  authors and nothing of this project.
- 3D Interconnect was on and left on, so o09 imported its STEP file through 3D
  Interconnect (an `MBimport` feature) rather than as an `Imported1` feature.

The kit wrote everything to
`C:\Users\Public\Documents\SolidSeasFixtures\current-account\out`, the folder
the documents name as their own location.

## Documents

Lengths in mm, volumes in m^3, areas in m^2, as SOLIDWORKS reported them.

| File | How it was made | Ground truth |
|---|---|---|
| `o01_empty.SLDPRT` | New part from the part template, nothing added | No features, no body |
| `o02_boxA.SLDPRT` | Rectangle 10 x 20 sketched from the origin on the Front Plane, extruded 30 blind | One body `Boss-Extrude1`, 6 planar faces; volume 6.0e-6; area 0.0022 |
| `o03_boxA_again.SLDPRT` | The same open document as o02, saved again with no change | Same model as o02; the bytes differ because every save carries per-save state |
| `o04_boxA_props.SLDPRT` | o02 plus three custom properties | `PartNo` = `ORACLE-PN-123` (text); `Description` = `Oracle test box` (text); `Qty` = `42` (number) |
| `o05_boxA_props_mat.SLDPRT` | o04 plus a material | `1060 Alloy` from database `SOLIDWORKS Materials`; mass 0.0162 kg |
| `o06_boxA_props_mat_cfg.SLDPRT` | o05 plus a second configuration | Configurations `Default` (active) and `OracleAlt` (comment `oracle alt config`); `OracleAlt` carries configuration property `CfgOnly` = `ALT-VALUE`; only `Config-0-Partition` is stored |
| `o07_boxB_h31.SLDPRT` | Same as o02 but extruded 31 | Volume 6.2e-6; area 0.00226 |
| `o08_asm_2x_boxA.SLDASM` | New assembly from the MBD template with o02 inserted twice | Components `o02_boxA-1` and `o02_boxA-2`, both `o02_boxA.SLDPRT`. The API places a part's bounding-box centre, so the stored translations are (-5, -10, -15) and (45, -10, -15): exactly 50 apart in X |
| `o09_import_step.SLDPRT` | `o02_boxA.step` imported into a new part (`LoadFile4`) | Feature `o02_boxA.step<1>` (`MBimport`); volume 6.0e-6; area 0.0022. The partition holds no body; the body is in `Config-0-FeatureBodies/LocalBodies`. The import added five text properties from the STEP header: `Nomenclature` and `Part Number` = `o02_boxA`, `Source` = `NOT_KNOWN`, `Revision` = `ANY`, `Definition` = `UNKNOWN` |
| `o10_import_step_cut.SLDPRT` | o09 plus a 5 mm hole at (5, 10) on the Front Plane, cut through all both ways | Body `Cut-Extrude1`, 6 planar faces and 1 cylinder; volume 5.41095e-6; area 0.00263197; the body is in the partition |
| `o11_curved.SLDPRT` | Block 40 x 30 x 10, 3 mm fillets on the four edges parallel to Z, a 10 mm through hole at (20, 15), a 1 mm fillet on the hole's top edge | 12 faces: 6 planes, 5 cylinders, 1 torus; volume 1.11303e-5; area 0.00387708 |
| `o12_multibody.SLDPRT` | Box A, then a rectangle (30, 0) to (40, 20) extruded 10 with merge off | Two solid bodies, `Boss-Extrude1` and `Boss-Extrude2`; volume 8.0e-6; area 0.0032 |
| `o13_two_geometry_configs.SLDPRT` | Box A with a configuration `Tall` in which the extrusion is 45; both configurations rebuilt, `Default` active at save | `Default` 6.0e-6 and 0.0022, `Tall` 9.0e-6 and 0.0031; `Config-0-Partition` and `Config-1-Partition` both stored (a save as copy had stored only the first, so the kit saved the part again without Copy) |
| `o14_property_types.SLDPRT` | Box A with `1060 Alloy` and one property of each type | `TextProp` = `Plain text value` (TypeID 30), `DateProp` = `3/15/2024` entered in en-US (64), `NumberProp` = `7` (3), `DoubleProp` requested as Double 3.25 but stored as Number `3.250000` (3), `YesNoProp` = `Yes` (11), `Mass` linked to `"SW-Mass@o14_property_types.SLDPRT"` = `16.20`, `Material` linked to `"SW-Material@o14_property_types.SLDPRT"` = `1060 Alloy` (both 30); configuration property `CfgProp` = `Configuration value` on `Default` |
| `o15_sub_asm.SLDASM` | New assembly from the MBD template | `o02_boxA-1` at the origin; `o07_boxB_h31-1` turned +90 degrees about X and moved 30 along X |
| `o16_asm_features.SLDASM` | New assembly from the MBD template | `o02_boxA-1` at the origin; `o02_boxA-2` turned +90 degrees about Z at (100, 0, 0); `o02_boxA-3` excluded from the BOM; `o06_boxA_props_mat_cfg-1` showing configuration `OracleAlt`; `o15_sub_asm-1` turned 40 degrees about (1, 1, 1) at (0, 100, 0); `o07_boxB_h31-1` suppressed; `o07_boxB_h31-2` the seed of linear pattern `LocalLPattern1` (instances -3 and -4, 20 apart); `o09_import_step-1`; `o17_деталь-1`; virtual part `Part12^o16_asm_features-1`, stored as the nested document `VirtualComp/Part12-sldprt`. Configurations `Default` and `Lite` (`o15_sub_asm-1` suppressed in `Lite`); file property `PartNo` = `ORACLE-ASM-016`. SOLIDWORKS reopens it with a "needs rebuild" warning |
| `o17_деталь.SLDPRT` | Box A saved under a file name with Cyrillic letters | Same model as o02 |
| `o18_drw_boxA.SLDDRW` | New drawing from `ansi.drwdot` with one Front view of o02 | `Sheet1`, 420 x 297 mm; `Drawing View1` shows `o02_boxA.SLDPRT`, configuration `Default` |
| `o19_drw_asm.SLDDRW` | New drawing from `ansi.drwdot` with one Isometric view of o16 and two BOM tables | `Drawing View1` shows `o16_asm_features.SLDASM`, `Default`; a top-level BOM (8 rows by 4 columns with the header) and an indented one (10 rows) |

`ground_truth.json` has much more for every document: each configuration's
mass properties, bodies and face types, the full component list of every
assembly configuration with `IMathTransform.ArrayData`, and every BOM cell.

`tests/test_ground_truth.py` checks the library against it for all 19
documents: type and version history, unit system, configurations and the
active one, file and configuration properties (type, value, and whether they
are linked), materials, solid bodies per stored partition, every component
instance of every assembly configuration with its flags and its placement
relative to its parent, virtual parts as nested documents, and the model each
drawing view shows. Where the library and SOLIDWORKS disagree the test is a
strict xfail, listed in its `KNOWN`, which is empty today. The deprecated
`Reference.quantity` counts o16's instances in both of its configurations
together on purpose, and is checked for that 0.1 meaning; its replacement,
`Document.reference_set`, is checked against SOLIDWORKS' count.
`tests/test_components_ground_truth.py` checks `Document.components()` instance
by instance in every configuration (flags, parent, depth, placement in the top
assembly's frame), the BOM counts against o19's tables, each drawing's sheets,
views and models, reference resolution of a moved copy, and the path report
against the kit's scrub expectations. With `SOLIDSEAS_FIXTURES_DIR` set to a new
kit output folder it checks that output instead, before it replaces these
files.

## Exports written by SOLIDWORKS from the same documents

| File | Format | Notes |
|---|---|---|
| `o02_boxA.x_t` | Parasolid text transmit | Ground truth for Parasolid extracted from o02 to o06 |
| `o02_boxA.x_b` | Parasolid binary transmit | The same model in binary |
| `o07_boxB_h31.x_b` | Parasolid binary transmit | Ground truth for o07 |
| `o11_curved.x_b` | Parasolid binary transmit | Ground truth for o11's curved body |
| `o12_multibody.x_b` | Parasolid binary transmit | Both bodies of o12 in one file |
| `o02_boxA.step` | STEP AP203 (ISO 10303-21) | The file o09 imports |
| `o02_boxA.STL` | Binary STL, millimetres | 12 triangles; mesh volume 6000 mm^3; bounding box 10 x 20 x 30 mm |
| `o02_boxA.3mf` | 3MF package | Contains `3D/3dmodel.model` and `Metadata/thumbnail.png` |

## The kit's records

| File | What it holds |
|---|---|
| `ground_truth.json` | What SOLIDWORKS reported about each document after the kit reopened it read-only, how the kit made it, the templates it used (paths, file hashes and counts; the SHA-256 of the paths and names stored in them, which include the generating account's own, are in the private fixtures' `ground_truth.private.json`, moved there by `scripts/split-ground-truth.py`), and the export settings |
| `generation.log` | Every API step, with SOLIDWORKS' return codes |
| `scrub_report.txt` | The kit's own audit of every path and user name in its output, and its verdict. The generating account's profile folder is written as `%USERPROFILE%`, and its line in `SHA256SUMS.txt` was updated to match |
| `SHA256SUMS.txt` | The hash of every file above except itself and this README |

All four are kept byte for byte (`.gitattributes` turns off line-ending
conversion for them), so `SHA256SUMS.txt` verifies on every platform;
`tests/test_fixtures.py` checks it.

## Differential pairs

| Pair | Isolates |
|---|---|
| o02 vs o03 | Per-save noise |
| o02 vs o04 | Custom properties |
| o04 vs o05 | Material |
| o05 vs o06 | Configurations and configuration properties |
| o02 vs o07 | Geometry only |
| o02 vs o08 | Part versus assembly |
| o09 vs o10 | An imported body alone, and after one more feature |
| o02 vs o13 | A second configuration with geometry of its own |
| o02 vs o17 | The same recipe under a non-ASCII file name |
| o08 vs o15 | Translated versus rotated components |

## Embedded paths

SOLIDWORKS writes the saving account's Temp and Desktop folders into every
document, and a document keeps the folder history of the template it was made
from (`docs/FORMAT.md` section 13). These fixtures therefore carry, and may
carry only:

- the generating account's name, its bare Temp and Desktop folders, and
  SOLIDWORKS' scratch folders inside that Temp folder
  (`swx<pid>\VC~~\o16_asm_features\Part<n>^o16_asm_features.SLDPRT` for o16's
  virtual part, a `~0x....tmp` file);
- the kit's output folder above, under the shared Public profile, and the
  committed file names in it;
- a few exact paths and the folders above them: the drawing template and the
  BOM template of the SOLIDWORKS installation, two of its appearance files, the
  part and MBD assembly templates in ProgramData, and the Windows system folder
  (the kit's records also name the account's default drawing template, which
  the kit did not use);
- in documents made from the shipped templates (o08, o15, o16, o18, o19), the
  build-drive folders, install folders, profile folders and user names of the
  Dassault employees who authored those templates (the MBD assembly template
  and `ansi.drwdot`). Their names are listed only in the private fixtures'
  `ground_truth.private.json`.

`tests/test_fixture_paths.py` reads every stream of every file, nested
documents included, as UTF-8 and as UTF-16 at both byte alignments, and fails
on anything else: a path in any script, also one written with `%TEMP%`-style
variables, `~` or `..`, a network path or URL in any form, an e-mail or IPv4
address, a Windows default host name or the host name of the machine running
the test, a stored user name that is neither the account nor a template
author, a filled-in title, subject, keywords, comments, company or manager
field, a name in `Header2` or `ModelHeader` that is neither SOLIDWORKS' own nor
a fixture's nor one SOLIDWORKS reported, and an author, site or organisation
in the exports. With `SOLIDSEAS_CORPUS_MANIFEST` set it also fails when a file
or folder name from the private development corpus occurs in any view of any
file. Other plain text (a feature name, a property value) is not checked by
code; review it when regenerating. The tests do not depend on these paths
otherwise.

## Regenerating

Run the kit, then replace every file here with its output under the same name.
Before committing, read the new `scrub_report.txt`, run
`tests/test_fixture_paths.py` with `SOLIDSEAS_CORPUS_MANIFEST` set (extend its
allowlists only after reviewing what is new), run `tests/test_ground_truth.py`
and `tests/test_components_ground_truth.py`,
and update the per-save values that `tests/test_model.py` pins for o04 and o06
(file size, creation and save times, preview size and hash).

The SOLIDWORKS-made fixtures were saved with a commercial SOLIDWORKS licence.

## Checking a new SOLIDWORKS release

SolidSeas reads SOLIDWORKS documents through layouts worked out from files
(`docs/FORMAT.md`), and a new release can change them: the container, a stream,
the Parasolid schema. A release counts as supported only after this check has
run on it and `docs/FORMAT.md` says what changed. The documents here stay the
SOLIDWORKS 2024 SP1 set, because the native part writer's specification is
proved byte for byte against them (`tests/test_sldprt_spec.py`), so the new
release's documents are checked beside them and never replace them.

1. On a Windows machine with the new release installed and activated, run the
   kit as for the documents here: current-account mode
   (`Generate-Fixtures.ps1 -CurrentAccount`), the same recipes, and templates
   that follow the rules under "How they were made". An upgrade can carry the
   old release's settings over, default template folders included, so check
   which templates the new release's defaults name before the run, and give
   the kit an output folder of its own.
2. Read the new `scrub_report.txt` and go on only if its verdict says the
   output is publishable, then run the kit's `check_fixtures.py` on the output
   folder with `PYTHONPATH` set to a checkout's `src`.
3. In a scratch worktree of `main`, replace every file in `tests/fixtures`
   that the kit writes with the new output, and delete
   `ground_truth.private.json` there (the kit's own `ground_truth.json` has
   the account fields). Run the whole suite, then
   `tests/test_fixture_paths.py` with `SOLIDSEAS_CORPUS_MANIFEST` set. The new
   release's shipped templates may name other template authors: review them
   before extending any allowlist. Nothing in that worktree is committed.
4. Sort the failures. Some are expected, and each of those is checked to be
   only what it seems: the version, build code and Parasolid schema key the
   tests pin for 2024 SP1, the per-save values `tests/test_model.py` pins, and
   the native part writer's byte-for-byte tests. Every other failure is a
   reader meeting a changed layout, and gets a bead and a fix proved on the
   new documents before the release is called supported.
5. Record in `docs/FORMAT.md` the release's internal version (section 7.1),
   build date code (7.3), its row in 7.4 marked VERIFIED, every layout change
   with the version it starts at (7.7), the Parasolid schema it writes (10.3),
   and any other claim the run contradicted, each with its evidence label.
   When the private corpus has files the new release saved, run the corpus
   sweep (`tests/test_corpus.py`) and add their counts to sections 7.1 and 17.
6. Keep the kit's output for that release with the private fixtures, in a
   folder named for the release, so the next release's check can be compared
   with it, and add a CHANGELOG entry saying which release SolidSeas now reads.

The SOLIDWORKS bridge is a separate check: `tests/test_swapi.py` and
`tests/test_swapi_live.py` name the 2024 templates folder, so they need the new
release's folder and their build check (`SOLIDSEAS_SWAPI_BUILD_CHECK=1`) before
the bridge is said to work with it. Whether the new release opens the parts
the native part writer makes is that writer's own check
(`docs/NATIVE_SLDPRT_WRITER.md`).

## Files made by script

`tests/generated/` holds files that a script in the same folder writes,
outside SOLIDWORKS and the fixture kit. They live beside this folder rather
than in it, because the viewer's tests open this folder as a project and count
what it lists. They name no account, machine or path: the
script fixes their header's name, time stamp, author and organisation.

| File | How it was made | What it is for |
|---|---|---|
| `../generated/rocket.step` | `../generated/make_rocket.py`, run with CadQuery 2.8.0 and `cadquery-ocp` 7.9.3.1.1 (OCCT 7.9.3): `uv run --with cadquery==2.8.0 python make_rocket.py` from that folder | A model rocket of 20 faces: a body cylinder, an ogive nose (a `SURFACE_OF_REVOLUTION` of a whole `CIRCLE` crossing its axis at the tip), a conical skirt with a torus fillet at its base, and three fins whose planes meet the cone along `HYPERBOLA` edges. OCCT measures it at 8,830.34 mm^2 and 30,819.80 mm^3. `tests/test_formats_step.py` and the OCCT oracle read it |

`tests/generated/SHA256SUMS.txt` has the hash of each file there but itself, and
`tests/test_fixtures.py` checks it. Running the script again with the same
versions writes the same bytes; with others, check the face types and OCCT's
measures before replacing the file and its hash.

## Private fixtures

The SOLIDWORKS documents (o01 to o19), `generation.log` and `scrub_report.txt` carry the
name of the Windows account that ran the kit, so they are kept in the private repository
SolidSeasOrg/SolidSeas-fixtures with `ground_truth.private.json`, the account fields and the
template authors' names this copy of `ground_truth.json` leaves out.
`scripts/fetch-fixtures.py --from <clone>` copies them here, checked against
`SHA256SUMS.txt`; without them the test modules that need them are left out of a run.
`ground_truth.json` differs from the kit's own only in those fields, and its line in
`SHA256SUMS.txt` is this copy's checksum.
