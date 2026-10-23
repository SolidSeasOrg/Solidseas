# Drawings

Automatic drawings from 3D parts. `docs/DRAWINGS.md` is the design; these pages
describe what is built. Everything here is provisional until the first release.

| Page | Covers | Built |
|---|---|---|
| this page | the package, the contracts between the stages, open decisions | yes |
| [standards.md](standards.md) | the drafting rules, ranked (section 22) | yes |
| [REVIEW.md](REVIEW.md) | the engineer's review rubric (section 20.4) | yes |
| [views.md](views.md), [sections.md](sections.md) | views, hidden lines, sections, detail views | yes |
| [features.md](features.md) | feature recognition | yes |
| [dimensions.md](dimensions.md), [gdt.md](gdt.md), [layout.md](layout.md) | planning, datums and frames, layout | yes |
| [conventions.md](conventions.md) | the implied conventions the reconstruction oracle reads | yes |
| [pdf.md](pdf.md), [dxf.md](dxf.md) | the writers | yes |
| [file.md](file.md), [release.md](release.md) | the `.ssdrw`, regeneration, signing and revisions | yes |
| [email.md](email.md) | Email PDF | yes |
| [edit.md](edit.md) | editing a drawing, laying it out again from its records | yes |
| [checks.md](checks.md) | the automated checklist (section 20.1) | yes |
| [cli.md](cli.md) | the `drawing` command, the `drawing_result` kind and the error codes | yes |
| [goldens.md](goldens.md) | the golden drawings (section 19.4) and their open findings | yes |
| [viewer.md](viewer.md) | where drawings appear in the viewer, the drawing process and the sheet on screen, the self-test's dry run, packaging | yes |
| [wizard.md](wizard.md) | the New Drawing wizard | yes |
| [editor.md](editor.md) | the drawing editor | yes |
| [assemblies.md](assemblies.md) | drawings of assemblies: the parts list and item balloons | yes |
| [turned.md](turned.md) | turned (lathe) parts: which parts are turned, their profile view, datums, diameters and runout | in part (stage 2) |
| [iso.md](iso.md) | drawings to ISO as well as ASME: the switch, what differs, the six slices | design |

## What is built

The package `solidseas.drawing`, pure Python, with the library's rules: bounded
loops, one clock per stage, typed results, and only the public modules of
`solidseas.tessellate`.

| Module | Holds |
|---|---|
| `limits.py` | `DrawingLimits`: every bound of section 17.1 with its default and ceiling; `refuse()` says why a part is too large before work starts |
| `types.py` | the contracts of section 6: `DrawingOptions`, the feature types and `FeatureSet`, `ViewSpec` and `ViewGeometry`, `Requirement`, `PlannedDimension`, `Plan`, `Drawing` |
| `settings.py` | Drawing Settings (section 7): the groups of 7.2, the ASME presets, the file, per-value checks with fallbacks, first-use prompts, the logo check |
| `standards.py` | sheets, margins, zones, scales, lines, text heights, the tolerance blocks, ISO 2768-1, process figures, thread tables, revision and view letters, GD&T characteristics |
| `numbers.py` | values and tolerances as a sheet shows them (10.8), the rounding guard, bands, unit guessing |
| `fonts.py` | Helvetica and Helvetica-Bold widths in WinAnsi, `measure`, the cap-height rule |
| `source.py` | `DrawingSource` from a SOLIDWORKS part, or a STEP, Parasolid or Alibre Design part (6.2): identity, bodies, units and their origin, properties, hashes and digests |
| `assembly.py` | `DrawingSource` from a SOLIDWORKS assembly: its part instances placed, each part's bodies once, the parts list ([assemblies.md](assemblies.md)) |
| `facegraph.py` | `BrepModel` (6.3) from the tessellator's detail (`detail=True`) |
| `keys.py` | geometric signatures and feature descriptors (6.4.1) |
| `display.py` | the display list, the painted layer and the compact sheet (6.7) |
| `painter.py` | the painter interface, curves as Béziers, strokes from geometry |
| `svg.py` | the reference writer of the painted layer (12.3), internal |
| `pipeline.py` | `make_drawing`: the stages by dotted path, a missing one a capability gap (6.9) |

Every stage is built now, and the viewer offers drawings; a SolidSeas without
one still raises `not_implemented` with rule `stage_missing` and the stage's
name. `pipeline.run(part, until=..., stages=...)` runs the built stages and
takes a stage in place of one, so a new stage can be driven with real inputs
before the stages after it exist.

For tests, `tests/drawing_parts.py` builds the synthetic parts of section 19.1
on `XtBuilder` with their ground truth, and `tests/drawing_support.py` holds
cached models of them and a hand-built sheet for the writers.

## What the contracts settle

A throwaway end-to-end prototype of the stages listed 28 things the contracts
had to say. They are settled as follows; the "C" numbers are the prototype's.

| Item | Where it is settled |
|---|---|
| C1 identity | `BrepModel` faces are mesh face indices and edges detail keys; node ids are attributes; each side of an edge is found through its sample vertices |
| C2 surface frames | `facegraph.Plane`, `Cylinder`, `Cone`, `Sphere`, `Torus` with axes, radii, x and y, outward sense and `concave` |
| C3 (u, v) triangles | each `Face` has its vertex and triangle ranges and `BrepModel.face_uv` |
| C4 faces at a vertex | `BrepModel.vertices` and `vertex_faces()`, points rounded to 1e-9 m |
| C5 view frames and axis maps | `ViewSpec.frame()`, `project()`, `axis_map()`; `types.STANDARD_VIEWS` |
| C6 runs | `Run` carries its display primitive, style and source |
| C8 the witness query | `ViewGeometry.witnesses` and `witness_at()` |
| C11 depths | `FeatureSet.depths`, records of their own |
| C12 entry rounds | `Hole.entry_break` holds the round or chamfer and its faces |
| C13 ordered members | `Pattern.members` in angle order from the first |
| C14 keys from feature ids | `requirement_key()`; requirements and dimensions keyed `loc/f-7/x` |
| C15 planned dimensions | `PlannedDimension` with axis, positions, anchor, radius, text parts and frame |
| C16 graph nodes name features | `Position.features` |
| C17 a depth no view shows | a `Requirement` lists `leader_note` among what can satisfy it |
| C18 basic places | `numbers.show(..., Tolerance("basic"))` shows the places a value needs |
| C19 text widths | `fonts.measure` with both weights; layout spaces tracks by the painted text |
| C20, C21, C22, C25 | the layout stage's; the types leave room (`Plan`, the painted layer's owners) |
| C23 centres | `Position.centre` and `radius` |
| C26 the painter | `painter.Painter`, Béziers of at most 90 degrees, bold widths |
| C27 notes with frames | `NoteLine` and `display.Note` hold words and inline frames |
| C28 datums | `Drawing.datums`, a member of its own |
| C7, C9 | no change (C7) and a speed matter for the views and features stages (C9) |

## Open decisions

Two items are decisions the design leaves open, and the code follows the
prototype's answers until they are decided:

- **C10, widths against the envelope.** Rank the envelope first, then spaces,
  then material widths, and treat a material pair touching an envelope extreme
  as positions. Section 9 ranks by overlap share and then smaller width, which
  took the walls beside a pocket as material widths.
- **C24, smaller scale or larger sheet.** Take a reduced scale only when every
  dimensioned span stays at least 8 mm on paper, else the next sheet at full
  size, and report a cramped feature when nothing fits. Section 11.1 takes the
  largest scale that fits.

## Checks still owed

- **Font widths.** `fonts.py` holds the Core 14 AFM widths transcribed by hand.
  Before the first release each width is compared with Adobe's AFM files for
  Helvetica and Helvetica-Bold; the files are not downloaded without the user's
  permission (`docs/DRAWINGS.md` section 2).
- **Verify items** in `standards.py`, marked there and in
  [standards.md](standards.md): the zone counts per sheet size, Y14.1-2020's A
  size margin, the dash patterns, the revision letter rule, and the symbol
  proportions. They are checked against purchased standards (Q10).
- **Process figures** are the design's service bureau figures (section 10.6);
  Settings tell a business to replace them.
- **Synthetic parts not built yet**, because the builder makes no intersection
  curves: a cross hole entering a cylinder, a manifold passage ending in a
  cross bore, and a slot on an inclined face. The features stage adds them with
  the curves they need.
- **The goldens' findings.** [goldens.md](goldens.md) lists what the golden
  drawings show the planner, layout and recognition still get wrong; each is
  a strict expected failure until it is fixed, and the user reviews each
  golden's expected set once (section 21, stage 1 item 3).
- **Not in stage 1 after all:** sections and detail views on request, and flag
  notes ([edit.md](edit.md)); section 3.3 lets on-request details slip first.
