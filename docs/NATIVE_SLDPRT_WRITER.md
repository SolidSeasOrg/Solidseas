# A standalone native SLDPRT writer

The aim: a part made entirely outside SOLIDWORKS, saved as `.sldprt`, that an
ordinary SOLIDWORKS opens with a native sketch and extrusion in its
FeatureManager tree, and whose dimensions the recipient can change, rebuild
and save. Geometry-only exchange already works through STEP and Parasolid;
this is about design intent.

The rule that runs through everything here: **making a file never needs
SOLIDWORKS; checking one may.** The writer is pure Python in
`solidseas.nativewrite` and runs on Linux. SOLIDWORKS on the PC is only the
oracle that says whether a file is right, through a fixed check
(section 7).

Evidence labels are those of `docs/FORMAT.md`: VERIFIED (n), HYPOTHESIS,
UNKNOWN. "Offline" below means checked by code with no SOLIDWORKS.

## 1. Status

| Question | State |
|---|---|
| Write a 2015+ container SolidSeas reads back member for member | VERIFIED offline (19 of 19 fixtures, two layouts) |
| SOLIDWORKS opens a container this writer laid out | VERIFIED: x1 (laid out again, no decoys) and x2 (patched) open with no error or warning (section 6.1) |
| Where a feature's driving value is stored | VERIFIED: `moLengthParameter_c` in `Config-<n>-ResolvedFeatures` (section 4.4) |
| SOLIDWORKS rebuilds to an edited parameter | VERIFIED: the parameter alone drives the rebuild (a1), and so do a sketch's points (s1, s2) |
| SOLIDWORKS with a stale, empty or missing partition | VERIFIED: missing, it builds the body when it opens the part; stale, it shows the old shape until a rebuild; empty, no body until a rebuild |
| A part needs only `Config-<n>` and its feature stream from a writer | VERIFIED for these candidates: o12's two features in o02 (b1, b2) and o02's box in the empty part o01 (b3, b4) rebuild to their features |
| A source-agnostic IR and a SolidCraft adapter | Done for sketches on any plane, extrusions, revolves, fillets, chamfers, holes, patterns and mirrors (sections 8, 9) |
| SolidCraft to IR to a native file | VERIFIED in SOLIDWORKS for one extruded rectangle (p1, p2: 40 x 30 x 10 mm, native, depth editable), through the seed (section 10) |
| The archive's object numbering, which new records must follow | VERIFIED offline (section 4.6) |
| Authoring new sketches, relations, dimensions and features | Not started: needs each class's field layout (4.6.1) and dimensioned fixtures |

On 2026-10-19 SOLIDWORKS 2024 SP1 (revision 32.1.0) opened all 17
candidates as native parts, a sketch (`ProfileFeature`) and an extrusion,
nothing imported, rebuilt each to the volume its features describe, took a
change of the depth dimension, saved a native copy and reopened it with the
change (section 6.1). So a part this writer makes, with no SOLIDWORKS, opens
in SOLIDWORKS with an editable native feature tree.

The milestone is reached only in part. The sketch the writer carries has no
driving dimensions of its own (it is the seed's: a corner rectangle with a
coincident, two horizontal and two vertical relations, under-defined), so
the recipient can change the depth by its dimension but the rectangle only
by dragging or dimensioning it themselves; and every part is built on the
seed's records rather than authored. Dimensioned sketches and authoring new
features are what remain (section 13).

## 2. Code

| Module | What it does |
|---|---|
| `src/solidseas/nativewrite/container.py` | Reads a document's members with their stored bytes and directory fields; `build_container` lays them out again; `patch_in_place` rewrites only changed members; `write_new_file` never replaces a file |
| `src/solidseas/nativewrite/ir.py` | `ParametricDocumentIR`: schema, validation, JSON |
| `src/solidseas/nativewrite/solidcraft.py` | SolidCraft's document (JSON or its ZIP container) into the IR |
| `src/solidseas/nativewrite/generate/` | To come: the clean-room generator, IR to `.sldprt` (`docs/CLEANROOM.md`, section 15) |
| `research/swnative/features.py` | Analysis: class records, named nodes, driving parameters, sketch points and the object map of a feature stream; edits doubles in place |
| `research/swnative/experiments.py` | Analysis: the candidate parts and `judge`, the verdict on a check's report |
| `research/swnative/objdiff.py` | Analysis: object-level differences of two parts' feature streams, each run classified (section 4.8) |
| `research/swnative/layouts.py` | Analysis: every class's field layout across all the part fixtures, from `Config-<n>` and its feature stream: constant runs, doubles, times, counters and `CString`s (`python -m swnative.layouts tests/fixtures/*.SLDPRT --class sgLineHandle`) |
| `research/swnative/typedump.py` | Analysis: a typed reading of an undecoded run (strings, lengths in mm, angles, small integers), the first step of decoding a block whose meaning is unknown (4.9) |
| `research/swnative/writer.py` | The seed writer of the first experiments (section 10); not shipped |
| `src/solidseas/swapi/SwBridge/NativeCheck.cs`, `TestSession.cs` | The bridge's `native_check` and test-session operations |
| `scripts/sw-checks/native-writer.py`, `native-writer-attached.py` | The PC checks that run the candidates through SOLIDWORKS |

`tests/test_nativewrite.py` holds the offline tests.

## 3. Writing the container

`docs/FORMAT.md` section 2 is the layout. The writer:

- keeps the source's key and signatures (a new key needs only
  `lcg_signatures`, but nothing is gained by changing it);
- writes local headers with version 20, flags 6, method 8, the source
  member's opaque time and date, the CRC-32 and both sizes, and a directory
  record with the source's internal attribute and local offsets relative to
  byte 8;
- compresses with zlib level 1, memLevel 8, raw deflate. On every member of
  the 19 fixtures this gives the stored bytes exactly (VERIFIED, 773
  members), so an unchanged member is byte-identical whichever way it is
  written;
- writes no decoys. 36 corpus files from early 2015 builds have none, but
  every file from version 9000 on has them (`docs/FORMAT.md` 2.8), so a
  container without them is a question for SOLIDWORKS (candidate x1).

`patch_in_place` keeps every byte of the source up to the old central
directory. A changed member whose stored bytes fit its old span is written
over it; one that grew goes after the last member. The directory and end
record are then written again and the old decoys after them are dropped
(candidate x2 asks whether SOLIDWORKS minds).

SWFormat (section 11) reports that SOLIDWORKS 2026 rejected files whose
offsets had been shifted and accepted members relocated to the end. Those are
its claims, not ours. Both of our layouts are tested by the check, and
neither shifts a member that did not change.

ZLB blocks inside members (the Parasolid partition) are one zlib level 1
chunk for small data, and wrapping the decoded blocks again that way gives
the stored bytes exactly (VERIFIED, 2 blocks of o02).

## 4. The feature stream

### 4.1 Where the feature tree is

`Contents/Config-<n>-ResolvedFeatures` holds the feature tree of
configuration n: every folder, the planes, the origin, each sketch with its
points and lines, each feature with its end conditions, dimensions and
parameters. VERIFIED (14 parts, 15 streams: o13 has one per configuration). The XML in
`swXmlContents/Features` holds only the document and configuration list, and
`swXmlContents/KeyWords` mirrors each feature's dimensions as display text
(`<Extrusion Name="Boss-Extrude1"><Dimension Name="D1">30</Dimension>`).

### 4.2 Framing

MFC `CArchive` output (`docs/FORMAT.md` 4.3), after a 6-byte header:

| Offset | Size | Field | Evidence |
|---|---|---|---|
| 0 | 4 | u32: the archive's next load-map index, carried over from `Config-<n>` (4.6): 101 in o01, 109 in o02, 111 in o11 | VERIFIED (13 streams) |
| 4 | 2 | number of top-level features: 17 in the empty part, 19 with a sketch and an extrusion, 21 with two of each, 23 in o11 | VERIFIED (6 parts) |
| 6 | | one object per feature, in tree order | VERIFIED |

Each feature object starts with its class (a new-class record or a class
reference) and a **named node**: a class reference, then the feature's name
as a `CString`. The reference is `04 80` in 12 parts and `05 80` in the two
with an imported body (o09, o10); it is the two bytes after the first class
record's name, and `features.name_tag` reads it from there. Driving
parameters are named nodes too (`D1`). Named nodes give the tree order:
Comments, Favorites, the history folder and so on, Front, Top and Right
Plane, Origin, Sketch1, Boss-Extrude1. VERIFIED (14 parts, 15 streams).

### 4.3 Classes of a sketch and an extrusion (o02)

In stream order: `moProfileFeature_c` (Sketch1) with `sgSketch`,
`sgPointHandle`, `moCompRefPlane_c` (the sketch plane), `sgLineHandle` (the
four lines and their points), `moSketchExtRef_w`, `moCompSketchEntHandle_c`,
`moPointBackedUpData_c`, `moSketchRegion_cR`, `moSketchChain_c`; then
`moExtrusion_c` (Boss-Extrude1) with `moPerBodyChooserData_c`,
`moFaceRef_c`, `moEndFaceSurfIdRep_c`, `moFromSktEntSurfIdRep_c`,
`moBBoxCenterData_c`, `moEndSpec_c`, `moDisplayDistanceDim_c`,
`moFeatureDimHandle_c`, `ParallelPlaneDistanceDim_c`,
`moLengthParameter_c`, `moFromEndSpec_c`. The empty part o01 has none of
these. Their field layouts are UNKNOWN except where 4.4 and 4.5 say.

### 4.4 Driving parameters

A driving dimension's value is in its `moLengthParameter_c`: the named node
(`04 80`, `CString` `D1`), then the 22 bytes
`00 00 00 00 00 00 00 40 FF FF FF FF 00 00 00 00 FF FE FF 00 00 00`, then the
value as a little-endian double in metres. The feature it belongs to is the
last feature named before it, which gives SOLIDWORKS' full name
(`D1@Boss-Extrude1`). VERIFIED: 9 parameters in 6 parts (o02, o07, o11,
o12, both configurations of o13), and on every part fixture the parameters
found equal the KeyWords text in millimetres (`tests/test_nativewrite.py`):
extrusion depths, o11's two fillet radii and o12's second extrusion.

`moEndSpec_c` holds no copy of the depth: in o13 the 30 mm and 45 mm
configurations have identical end specs. That the parameter, not a copy, is
what a rebuild uses is the HYPOTHESIS that candidates a1 and a2 test.

### 4.5 Sketch points

A sketch point's coordinates are two doubles in metres, in the sketch
plane's frame, after the run `F0 3F 00 00 00 00 00 00 00 00 1E 00`. o02's
four corners are found this way: (0, 0), (10, 0), (10, 20) and (0, 20) mm.
o11's rectangle, circle centre and radius point, and both of o12's
rectangles, are found the same way. VERIFIED (3 parts). The point at the
origin sits in the sketch's own record, the others in their lines'.
Constraints and relations are not decoded: o02's sketch was made with no
dimensions.

### 4.6 The object map

`Contents/Config-<n>` and `Config-<n>-ResolvedFeatures` are one `CArchive`.
Its load-map numbering starts in `Config-<n>` and counts the way MFC does: a
new class takes the next index and its object the one after, and a reference
to a known class (`0x8000 | index`) takes one index for its new object. It
starts at 2 in the plain parts (so `moNodeName_c`, `Config-0`'s second class,
is index 4: the `04 80` of every named node) and at 3 in the two parts with
an imported body (`05 80`). The count reached at the end of `Config-<n>` is
exactly the feature stream's header u32, and every class reference in the
feature stream then names a class defined earlier in one of the two streams:
o01's `moRefPlane_c` and `moDefaultRefPlnData_c` for Top and Right Plane,
o02's 15 `sgLineHandle` references, and so on. VERIFIED (13 streams in 12
parts, `features.object_map`; `tests/test_nativewrite.py`). In o09 and o10
the scan of `Config-0` comes out 8 short of the header: it counts three
references inside the relation manager's data that are not references, or
misses a class record. UNKNOWN which; imported bodies are not what the writer
makes.

So a writer that appends objects knows each new index: a class the archive
has not defined yet is written as a new-class record, one it has as
`0x8000 | index`, and the count goes on from the feature stream's last
object. Nothing in the stream counts bytes, so records may grow or shrink.

### 4.6.1 A second sketch and extrusion

o12 is o02 with a second rectangle, (30, 0) to (40, 20) mm, extruded 10 mm
with merge off, made in the same session. Their feature streams differ in
two places only: the history folder grows by 239 bytes (entries for the two
new features), and 5,066 bytes are inserted before the stream's last 4 bytes.
Everything else is byte-identical. VERIFIED. The new records are not o02's
with new values: Sketch2 has no records tying a point to the origin (Sketch1
has `sgExtEnt_c`, `moSketchExtRef_w`, `moCompSketchEntHandle_c` and
`moPointBackedUpData_c` for its corner on the origin), the extrusion is a
`moICE_c` where the first is `moExtrusion_c`, and its face references are the
`3Int` classes (`moFromSktEnt3IntSurfIdRep_c`, `moEndFace3IntSurfIdRep_c`).
Writing a new feature therefore needs each class's field layout, which is the
next step of Experiment B; o02 to o12 is its offline oracle.

### 4.7 What a depth change touches

o13's two configurations (30 and 45 mm, one session, one save) differ in
their feature streams only in: the parameter's value; the dimension's
witness points and the values beside them (equal to the depth, either sign);
the reference planes' display sizes (`moDefaultRefPlnData_c`, sized to the
model); the box centre record (`moBBoxCenterData_c`: centre and diagonal);
two flag bytes (0x40 against 0xC0, 7 bytes after the sketch's and the
extrusion's names; the origin's is 0xC0 in both) and an index byte. VERIFIED.

Outside the feature stream, o02 (30 mm) and o07 (31 mm, the next document of
the same session) differ in the stored box (six doubles: centre and far
corner) of `Config-0`, `Config-0-LWDATA`, `Config-0-ModelHeader` and
`Header2`, in mass properties, the display lists, the previews and the
Parasolid partition. In the partition's first block, 31 mm replaces 30 mm at
the same 17 big-endian doubles, and with them changed the two blocks differ
in 50 bytes, where saving one model twice (o02 and o03) differs in 118.
VERIFIED.

### 4.8 What differs between two first features

`python -m swnative.objdiff A B --from Sketch1 --to Boss-Extrude1` (with `research` on the path)
splits both spans into class tokens with the object map, aligns them by
class and classifies each differing run. Between o02 (10 x 20 x 30 mm) and
o11 (40 x 30 x 10 mm), two parts whose first features are both a corner
rectangle from the origin extruded blind, made in one session:

| Kind | Where | What |
|---|---|---|
| geometry | the line records' points, the depth parameter, the dimension's witness points, the box centre records | the model's numbers, in metres |
| counters | named nodes, `sgPointHandle`, `moFR_c`, `moFaceRef_c`, `moBBoxCenterData_c`, `moPMarkRecord_c` | document-wide sequence numbers and ids: feature ids (0x76 against 0x7C), the face ids of the body (0xEB against 0xF9, and lists of them), a mark count (7 against 18) |
| time | named nodes, `moCStringHandle_c`, every `moFR_c` | u32 Unix times of the session (1790900763 against 1790900778) and FILETIMEs stored high word first |
| text | `moCStringHandle_c` | the document's internal name (`Part3` against `Part7`) |
| structure | after the dimension | a `moSketchBlockMgr_c` object: o11 writes a new one, o02 refers to the one `Config-0` holds; and the next feature's class (o11 has a fillet) |

Nothing else differs: the class sequence, every flag and every other field
are the same bytes. VERIFIED (these two parts; o02 against o03, one model
saved twice, differs in counters and times only). So a template of a first
feature has these slots and no others, which is what an encoder for it needs
to fill. Two samples do not show which counters SOLIDWORKS checks against
the rest of the document, and the face ids are Parasolid's: a written part
without a partition has none to match.

### 4.9 How much of a part is the same in every part

`swnative.layouts` lines up one feature's span (its named node to the next
feature's) across every part, with `CString`s read as fields. The 18 features
every part starts with, Comments to Origin, are the same length in all 14
parts but the history folder and the Origin, and 87 to 99% of their bytes
are the same in all of them. What varies is a few slots: the name tag (`04`
or `05`), feature ids and other counters, two session stamps in every named
node, and the reference planes' display sizes and positions, which follow
the model's size (4.7). VERIFIED (14 parts, 15 streams).

`Contents/Config-0` is 24,240 bytes in the empty part and 24,794 to 25,444
in the others, and 99.4 to 99.8% of o01's bytes appear in the same order in
each of them. VERIFIED (13 parts).

Lined up against each of the other parts, only 185 of o01's 24,240 bytes ever
differ. They fall in a few places: the document's own name and times in
its first named node, `moVisualProperties_c` (66 bytes: the appearance and
material display), `gcXhatch_c` (the crosshatch pattern, 26), `uoModelData_c`
(11), `moTransRefPlaneData_c` (10), the last light (16), and
`moSketchBlockMgr_c`, `suObList` and `moCThreadRefMgr_c` at the end (about 15),
where the parts with features keep their managers' lists. Elsewhere one byte
differs at the start of each style block and view, where a class index
shifts. The rest, about 24 KB, is the same bytes in every part: the units
table, the drafting standard's defaults (its 16 KB middle: fonts such as
Century Gothic at 3.5 mm, CONTINUOUS line styles, arrow sizes and angles, as
`swnative.typedump` reads them), the lights and the ten standard views.
VERIFIED (13 parts).

So most of what a part holds is the same data in every part SOLIDWORKS
saves: defaults and settings whose meaning is not decoded. A generator
written from a specification of these streams either computes those fields
from what they mean, which needs each one decoded, or emits them as
constants the specification lists. Which, and how far each goes, is the
question section 13 item 6 records.

## 5. Authoritative records and caches

| Record | Role | Evidence |
|---|---|---|
| `moLengthParameter_c` value | driving value | 4.4; SOLIDWORKS rebuilds from it alone: VERIFIED (a1, 6.1) |
| sketch point doubles | sketch geometry with no dimensions | 4.5; they drive the profile: VERIFIED (s1, s2) |
| dimension witness points, `moBBoxCenterData_c`, plane display sizes | caches | left at the old depth in a1, which rebuilds correctly: VERIFIED |
| KeyWords dimension text | display mirror | stale in a1: VERIFIED that it does not drive |
| stored boxes, mass properties | caches | stale in a1, a2, b1 to b4: VERIFIED |
| `Config-<n>-Partition` | the evaluated body, shown as stored | absent: built on open (c1, b2, p2); stale: shown until a rebuild (a1); empty: no body until a rebuild (c2, b3): VERIFIED |
| `DisplayLists`, `Preview`, `PreviewPNG` | display caches | absent in c3, which opens and rebuilds: VERIFIED |

## 6. The candidates

`python -m swnative.experiments --out <new folder>` (with `research` on the path) writes
them, with `manifest.json`, from o02 (and o01's partition for c2). Each
lists what it changed, dropped and left as the source had it, the box its
features describe and the volumes a rebuild and the check's depth edit
(to 33 mm) should give.

| Name | Question | What it is |
|---|---|---|
| x0-source | control | o02 itself |
| x1-rebuilt-container | container | o02 laid out again from byte 8, no decoys |
| x2-patched-container | container | o02 with its directory written again |
| a1-depth-parameter-only | parameters | D1 = 31 mm and nothing else |
| a2-depth-with-mirrors | parameters | D1, its dimension's copies, the KeyWords text |
| a3-depth-consistent | parameters | a2, the box centre, the stored boxes and the partition's geometry |
| c1-no-partition | geometry | a2 with no partition streams |
| c2-empty-partition | geometry | a2 with o01's empty partition |
| c3-no-display-lists | geometry | a2 with no display lists or previews |
| s1-sketch-width-12 | parameters | the two corners at x = 10 moved to x = 12 |
| s2-width-and-depth | parameters | s1 and a2 together |
| b1-features-from-o12 | authoring | o02 with o12's `Config-0` and feature stream (a second box), every other stream o02's |
| b2-features-from-o12-no-partition | authoring | b1 with no partition |
| b3-o02-features-in-o01 | authoring | the empty part o01 with o02's `Config-0` and feature stream: its caches describe no body |
| b4-o02-features-in-o01-40x30x10 | authoring | b3 with the box moved to 40 x 30 x 10 mm |
| m00-no-partition, then `m-<member>` for each of the other 39 members | members | o02 with no partition, and the same with one more member left out |
| g1-core, g2-core | members | o02 with only a guessed core of 9 or 16 members |
| p1-solidcraft-rect | the pipeline | SolidCraft sample to IR to the seed writer, geometry left stale |
| p2-solidcraft-rect-no-partition | the pipeline | the same, partition dropped |

How to read the results: x1 or x2 refused means the container needs its
decoys or the original layout. a1 rebuilding to 6.2e-6 m³ means the
parameter is authoritative; a1 failing and a2 passing means a copy matters;
only a3 passing means SOLIDWORKS trusts its caches over the parameter.
c1, c2 or c3 passing means that cache may be left out of a written part.
b1 or b2 rebuilding to o12's two bodies (8.0e-6 m³) means a writer needs to
author only `Config-<n>` and its feature stream; the other streams are
caches SOLIDWORKS remakes. b3 and b4 ask the same of an empty part, which is
where a writer that authors from scratch would start. The M candidates (Experiment M) find the smallest
set of members SOLIDWORKS opens and rebuilds, which is what the clean-room
generator has to write; the attached check refuses to start while the
person's session has a document open, in case a candidate makes SOLIDWORKS
fail.

### 6.1 Results (2026-10-19)

`native-writer-attached` ran in the user's own SOLIDWORKS 2024 SP1
(revision 32.1.0) through the bridge's test-session operations, 176 s.
Every candidate opened read-only with no open error and is native, with 0
feature errors, 0 What's Wrong items and 0 Check faults after a forced
rebuild; every one took `D1@Boss-Extrude1` = 33 mm (status 0), saved a
native copy with no error and reopened with depth 33 mm and the edited
volume. All 17 are `editable` by `judge`.

| Candidate | Volume as opened (mm³) | After rebuild | Expected | Opened with |
|---|---|---|---|---|
| x0-source, x1-rebuilt-container, x2-patched-container | 6,000 | 6,000 | 6,000 | no warning |
| a1-depth-parameter-only, a2-depth-with-mirrors | 6,000 (stale) | 6,200 | 6,200 | no warning |
| a3-depth-consistent | 6,200 | 6,200 | 6,200 | no warning |
| c1-no-partition | 6,200 | 6,200 | 6,200 | no warning |
| c2-empty-partition | 0 | 6,200 | 6,200 | `swFileLoadWarning_NeedsRegen` |
| c3-no-display-lists | 6,000 (stale) | 6,200 | 6,200 | no warning |
| s1-sketch-width-12 | 6,000 (stale) | 7,200 | 7,200 | no warning |
| s2-width-and-depth | 6,000 (stale) | 7,440 | 7,440 | no warning |
| b1-features-from-o12 | 6,000 (one body of two) | 8,000 | 8,000 | no warning |
| b2-features-from-o12-no-partition | 8,000 | 8,000 | 8,000 | no warning |
| b3-o02-features-in-o01 | 0 | 6,000 | 6,000 | no warning |
| b4-o02-features-in-o01-40x30x10 | 0 | 12,000 | 12,000 | no warning |
| p1-solidcraft-rect | 6,000 (stale) | 12,000 | 12,000 | no warning |
| p2-solidcraft-rect-no-partition | 12,000 | 12,000 | 12,000 | no warning |

What it settles:

- **The container.** SOLIDWORKS opens a container laid out again from byte
  8 with no decoys (x1) and one patched in place (x2). Decoys, the key's
  slot and the opaque time and date fields do not matter to it.
- **Parameters are authoritative.** Changing only the stored `D1` (a1)
  rebuilds to the new depth; the dimension's copies, the box records and the
  KeyWords text are caches. A sketch's stored points drive its profile (s1).
- **Leave the partition out.** With no partition stream SOLIDWORKS builds
  the body from the features as it opens the part (c1, b2, p2), so the
  recipient sees the right shape at once. A stale partition is shown as it
  is until the next rebuild, and an empty one shows no body. The writer
  drops the partition by default.
- **Two streams make a part.** `Config-<n>` and its feature stream carried
  into another part, the empty o01 included, rebuild to their features
  whatever the other streams say (b1 to b4).
- **Display lists and previews** may be left stale (c3).

The bridge reports the measured volume as `measure.mass.volume_m3`; `judge`
read the wrong key on the PC, so the check's own summary said `native` for
all 17 until the reading was fixed. The full report is kept with the
result (`20261019T074854Z-83dc0c13ba7c`).

## 7. The check on the PC

`solidworks-check` with `check` = `native-writer` (`docs/TWO_MACHINES.md`):

1. Writes the candidates in a process of its own with no SOLIDWORKS; the
   generator fails if it loaded a module that reaches SOLIDWORKS (the
   bridge client, `win32com`, `pythoncom`, `comtypes`, `clr`).
2. Builds the bridge in the worktree and starts SolidSeas' own SOLIDWORKS
   (`start_solidworks`): never the user's session.
3. For each candidate: `open_document` read-only; `native_check`, which
   reports the feature tree (types, suppression, error codes, dimensions,
   the sketch's segments, relations and constrained state, the extrusion's
   end condition and depth), the What's Wrong list and the measures as
   opened, again after `ForceRebuild3`, again after setting
   `D1@Boss-Extrude1` to 33 mm and rebuilding, and saves a native copy to a
   new file; then the same for the copy.
4. `judge` gives each candidate a verdict: `editable` when it is native
   (a `ProfileFeature` and an `Extrusion`, nothing imported), rebuilds to
   its features' volume, takes the edit, saves, and the copy reopens with
   the edit; `native` when it is native but one of those fails; `not-native`
   or `refused` otherwise.

The full report is `build/native-writer-check/report.json` in the
worktree; the result carries a summary of numbers.

`native_check` is the one bridge operation that calls `ForceRebuild3`, on a
part opened read-only in the bridge's own instance, and it saves only a copy
to a path that does not exist (`tests/test_swapi.py` holds it to that).

## 8. ParametricDocumentIR

`solidseas.nativewrite.ir`, format `solidseas-parametric-ir/1`. SI units
throughout (metres, radians). JSON through `to_json` and `from_json`;
`validate` checks ids, references, vocabularies and numbers.

| Object | Fields |
|---|---|
| `Document` | `name`, `features` (timeline order), `parameters`, `source` (system, format, file) |
| `Parameter` | `name`, `value`, `unit` (length, angle, number), `expression` (the source's text), `driving` |
| `Sketch` | `id`, `name`, `plane`, `points`, `curves`, `constraints`, `dimensions`, `suppressed` |
| `Plane` | `origin`, `x_dir`, `y_dir` (model frame), `base` (`xy`, `xz`, `yz` for a base plane) |
| `Point` | `id`, `x`, `y`; the sketch origin is the id `origin` and is never listed |
| `Curve` | `id`, `kind` (line: a, b; circle: centre and `radius`; arc: centre, a, b, counter-clockwise), `construction` |
| `Constraint` | `id`, `kind` (coincident, horizontal, vertical, horizontal_points, vertical_points, parallel, perpendicular, collinear, tangent, equal, concentric, midpoint, point_on_curve, symmetric, fix), `points`, `curves` |
| `Dimension` | `id`, `kind` (length, distance, distance_x, distance_y, point_line_distance, radius, diameter, angle), `value`, `points`, `curves`, `parameter`, `driven` |
| `Extrude` | `id`, `name`, `sketch`, `depth`, `operation` (new_body, join, cut), `direction` (forward, reverse, midplane: total depth), `end` (blind, through_all), `profile` (loops of curve ids, or every closed region), `depth_parameter`, `suppressed` |
| `Revolve` | `id`, `name`, `sketch`, `axis` (`sketch_line` with `curve`, `sketch_x`, `sketch_y`, or `model` with `origin` and `direction`), `angle`, `operation`, `direction` (forward or midplane), `profile`, `angle_parameter` |
| `EdgeRef` | `point` on the edge (model metres), `name` (the source's persistent name, when it has one) |
| `Fillet` | `id`, `name`, `edges`, `radius` (constant), `radius_parameter` |
| `Chamfer` | `id`, `name`, `edges`, `distance`, `distance2` or `angle`, `distance_parameter` |
| `Hole` | `id`, `name`, `positions`, `direction` (into the material), `diameter`, `depth` (none: through all), `kind` (simple, counterbore with `cb_diameter` and `cb_depth`, countersink with `cs_diameter` and `cs_angle`) |
| `Pattern` | `id`, `name`, `features`, `kind` linear (`direction1`, `count1`, `spacing1`, optional second direction) or circular (`origin`, `axis`, `count1`, `angle`) |
| `Mirror` | `id`, `name`, `features`, `plane` |
| `Unsupported` | `id`, `name`, `source_type`, `reason` |

A `Plane` that is not a base plane carries what a writer needs to recreate
it: `parent` and `offset` for a plane offset from a base plane, or
`face_point` and `face_name` for a sketch on a face of an earlier feature.

A source feature with no faithful IR form is an `Unsupported` entry in its
place in the timeline, never dropped. Edges and faces are found again by a
point on them; the source's persistent names travel along, but only a writer
with the source's own topology could match them exactly. Not in the IR yet:
sketch links (edges projected from the model), splines, two-sided and Up To
options, path patterns, shells, sweeps, lofts, configurations and equations.

## 9. SolidCraft

SolidCraft is MIT or Apache-2.0. `solidseas.nativewrite.solidcraft` reads its
saved document (plain JSON, or the ZIP with `container.json` and
`document.json`) with the standard library, from its documented field names;
no SolidCraft code is used and no MCP server is needed. Lossless input is the
document itself: SolidCraft's `timeline.export_script` embeds the same feature
JSON but leaves out configurations.

| SolidCraft | IR |
|---|---|
| `params[]` (`expr` in mm or degrees) | `Parameter`, value evaluated (numbers, units, + - * /, parameter names, sqrt and trigonometry; nothing else), expression kept |
| `features[]` before `marker` | the timeline |
| `sketch`, `plane {type: origin, name: XY, XZ, YZ}` | `Sketch` on base plane `xy`, `xz` (x = +X, y = -Z) or `yz` (x = +Y, y = +Z); an XZ sketch from before format 6 is refused |
| `points[i].pos` (mm), point 0 | `Point` in metres; index 0 is the sketch origin |
| `curves[i]` line, circle, arc, `construction` | `Curve` |
| constraint operands (array indices) | point and curve ids |
| geometric constraints | `Constraint` of the same kind |
| `length`, `distance`, `radius`, `angle` and the others with `param` | `Dimension` driven by that `Parameter` |
| `extrude`: `sketch`, `profiles` all or curve loops, `extent.distance`, `direction` positive, negative, symmetric, `convention`, `through_all`, `operation` | `Extrude`; a negative distance flips the direction; a symmetric `legacy_per_side` distance is doubled to the total |
| `param_names[0]` | the depth's parameter |
| `plane` `offset` (from a base plane), `custom`, `face` | a `Plane` frame, with `parent` and `offset`, or `face_point` and `face_name` |
| `revolve` | `Revolve`; a partial revolve is `Unsupported` unless it is symmetric or uses the `sketch_normal` convention, because which side SolidCraft's legacy convention turns to is not mapped yet |
| `fillet` (constant), `chamfer` (not flipped), `edges` and `edge_names` | `Fillet`, `Chamfer` with `EdgeRef` points and names |
| `hole` at a position (simple, counterbore, countersink) | `Hole` |
| `pattern` rectangular or circular of features | `Pattern` linear or circular |
| `mirror` of features about a base plane | `Mirror` |
| anything else (sketch links, boxes and other primitives, shells, moves, path patterns, thin or targeted extrusions) | `Unsupported` with the reason |

Every SolidCraft file in its repository's corpus and test folders translates
or is refused with a reason (assemblies and configurations are refused
whole for now). `tests/fixtures/solidcraft/rect-extrude-40x30x10.solidcraft` is
SolidSeas' own sample in that format: a 40 x 30 mm rectangle from the origin,
dimensioned through parameters (`width` = 40 mm, `d1` = `width`), extruded
10 mm, and a 2 mm fillet. On SolidCraft's own corpus and test designs (19
files) the adapter gives 22 sketches, 18 extrusions, 16 fillets and 4
chamfers, 82 `Unsupported` entries (most of them sketch links and the
features built on them, and primitives such as boxes) and refuses 2
assemblies.

## 10. The seed writer

`writer.write_sldprt(doc)` writes an IR part that is one rectangle from the
origin on the Front Plane, extruded blind, into the native records of o02:
the far corner into the sketch's points and the depth dimension's witness
points, the depth into `D1@Boss-Extrude1` and its copies, and its text into
KeyWords. It refuses, item by item, everything else: any `Unsupported`
feature, a second sketch or feature, another plane, another profile, a
relation o02 does not have, and every sketch dimension (o02 has none, so it
would arrive as geometry only). `allow_partial=True` writes the rest and
returns those items in `WriteReport.left_out`, which the caller must show.
Feature names are o02's (`Sketch1`, `Boss-Extrude1`); the report maps them.
By default (`geometry="drop"`) the part has no Parasolid partition, so
SOLIDWORKS builds the body when it opens it (section 6.1); `"stale"` keeps
the seed's, which shows the seed's shape until a rebuild.

This is a narrow result: it changes values in records SOLIDWORKS wrote and
does not author new ones. It is the pipe that general authoring will plug
into, and its output goes through the same check (p1, p2).

Shipping a seed part in the product is a question for the user: o02 was
made from the part template SOLIDWORKS installs, and it is already published
as a test fixture, but a seed that every exported file is built from is a
different use (bead).

## 11. Prior art

| Project | Licence | Used |
|---|---|---|
| [KenM76/swformat](https://github.com/KenM76/swformat) | Apache-2.0 | **No code and no format description used.** Its container reader is ported from openswx, which SolidSeas excludes for its disassembly provenance (`docs/FORMAT.md` 18), and its own docs say it is not clean-room. Its reports of SOLIDWORKS behaviour (offset shifts rejected, members relocated to the end accepted, stale CRCs accepted, a drawing sketch re-solved from an edited `moLengthParameter_c`) are treated as claims to test, and the check tests the first two. It has no part feature-tree decoding |
| [tangency-labs/solidcraft](https://github.com/tangency-labs/solidcraft) | MIT OR Apache-2.0 | Its documented document format is read; no code used |
| SOLIDWORKS API documentation | | The oracle's calls: `ForceRebuild3`, `GetWhatsWrong`, `IExtrudeFeatureData2`, `IDimension.SetSystemValue3`, `SaveAs3` with `swSaveAsOptions_Copy` |

Everything above was worked out from fixtures made through the published
API, diffs between them, and SolidSeas' own reader. No SOLIDWORKS binary was
disassembled, decompiled, debugged or hooked.

## 12. Compatibility

| Item | State |
|---|---|
| Format version | Only what the fixtures are: SOLIDWORKS 2024 SP1 (`_MO_VERSION_17000`). No other version is claimed |
| Configurations | One per stream (o13); writing more than one is not started |
| Sketch entities | Lines found; circles and arcs located (o11) but not edited |
| Relations | Not decoded |
| Dimensions | Driving length parameters read and set; angles, radii and diameters not yet seen in a fixture's stream layout beyond o11's fillets |
| Features | Extrusion depth edited; nothing created. The IR holds extrusions, revolves, fillets, chamfers, holes, linear and circular patterns and mirrors; the seed writer takes only the first |
| Equations, expressions | Not decoded; an IR expression is written as its value and reported |
| Assemblies | Not started; nothing here assumes parts only except the seed |

## 13. Open questions, by how much they block

1. Dimensioned sketches: fixtures through the API with one change each (a
   corner rectangle with two driving dimensions, the same with one changed,
   with a relation removed, a centre rectangle, a circle with a diameter),
   to decode the relation and dimension records and carry an IR sketch's
   dimensions as SOLIDWORKS sketch dimensions.
2. The field layouts of the sketch and extrusion classes (4.6.1, 4.8), with
   o02 to o12 as the offline oracle, to author new features rather than
   carry the seed's: first a second extrusion, then cut, revolve, hole,
   fillet, chamfer and patterns, each through the check.
3. Which of the counters, session times and face ids SOLIDWORKS checks
   against the rest of a part (4.8). Without a partition there are no face
   ids to match, and b3 and b4 show it accepts records whose bookkeeping
   came from another document.
4. The meaning of the 0x40 and 0xC0 flag bytes and of the unexplained double
   in `moExtrusion_c`.
5. Whether a seed part may ship (section 10).
6. How much opaque data the generator may carry. About 30 KB of `Config-0`
   and of the first 18 features is the same in every part (4.9). Listing it
   as specification constants makes the generator a template under another
   name; decoding it field by field is the clean way and the long one. Experiment
   M and per-run tests in SOLIDWORKS can show which of it SOLIDWORKS needs at all.

## 14. Reproducing

```sh
python -m pytest tests/test_nativewrite.py          # offline, any machine
PYTHONPATH=src:research python -m swnative.experiments --out /tmp/cands
python scripts/exchange/xchg.py request --kind solidworks-check --ref main --param check=native-writer   # VM, when SOLIDWORKS is active
```

On a Windows machine with a licensed SOLIDWORKS and no other SOLIDWORKS
session that matters, `python scripts/sw-checks/native-writer.py --json`
from a fresh checkout runs the whole check by itself.
