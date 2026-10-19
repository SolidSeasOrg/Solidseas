# Golden drawings

The golden drawings of `docs/DRAWINGS.md` 19.4 and 19.5, and the review of 21,
stage 1 item 3. Provisional until the first release; the rules behind
the expected sets follow ASME practice as summarised in
[standards.md](standards.md), not a purchased copy of the standards.

| File | Holds |
|---|---|
| `tests/test_drawing_golden.py` | the tests: each golden's hand-written set, the 19.5 checks, the snapshots |
| `tests/drawing_golden_support.py` | how each golden is made, what the drawing shows in words, the snapshot summaries |
| `tests/goldens/drawings/<golden>.json` | one file a golden: `expected`, `findings`, `snapshot` |

## The goldens

Every golden is drawn with the ASME defaults of Drawing Settings and the
fictional company "Example Engineering Co.". The fixtures go through
`make_drawing`; the synthetic parts of `tests/drawing_parts.py` go through
`pipeline.run` with a stand-in for the `source` stage that hands the transmit on
as the part's one solid body (a real `DrawingSource`, so the model, features,
views, plan and assemble stages all run as they would on a file). The stand-in
gives the part the file hash it would have (a hash of its name and its geometry
digest), so the title block's MODEL and the model-governs note can name it. No
golden is given a person for DRAWN, a material or a finish.

| Golden | Part | Profile | Proves |
|---|---|---|---|
| `o02-mm`, `o02-in` | o02 box, 10 x 20 x 30 mm | ASME mm; ASME inch | envelope, title block with STATUS and MODEL, projection, minimal views (two and the isometric), PRELIMINARY stamp |
| `o07-from-o02` | o02's millimetre drawing, its 10.0 width removed (`edit.remove`) and its height moved (`edit.move`), saved and loaded, then `regenerate(load(o02), source=o07)` | ASME mm | the height keeps its id, removed stays removed, moved stays moved |
| `o11-mm`, `o11-in` | o11 block with four R3 edges and a hole with an R1 entry round | ASME mm; ASME inch | datum symbols, basic locations, the position frame in the callout, the entry round as a callout line, fillet note, centre marks; in inches the rounding guard (check 5) |
| `hole-kinds` | plate with one hole of each kind | ASME inch | callouts in manufacturing order (counterbore, spotface, countersinks, blind flat, drill point, stepped), frames, the ordinate switch on x |
| `patterns` | plate with a row, a grid and a pitch circle clocked 15 degrees | ASME inch | nX callouts, pitches, the pitch circle and its first angle, one frame a group |
| `arc-pattern` | plate with five holes 30 degrees apart from 20 degrees on a pitch circle round a bore | ASME mm | an arc pattern: the 5X callout, the pitch circle, the first end's angle and the step with its count of spaces (4X 30°), no hole located on its own |
| `four-holes` | plate with four holes at irregular places | ASME inch | scattered locations, eight of them, as ordinates where the band is deep |
| `link` | link with full-round ends and a hole at each | ASME inch | widths, the derived 2X R, holes fixed through the radius and tangent links |
| `boss` | block topped by a boss, a hole down through both | ASME inch | the boss's diameter and frame, a hole coaxial with its boss located once, the step |
| `pocket-tab` | block with a tab and a pocket | ASME inch | tab thickness and pocket width and length stated directly, the depth as a note |
| `sixteen-holes` | plate with sixteen holes | ASME inch | the ordinate switch |
| `inclined-face` | block cut at 45 degrees with a hole square to the cut | ASME inch | a reduced-dimension drawing; release blocked until COV.unclaimed is accepted (check 5) |
| `printed-bracket` | printed L-bracket | ASME mm, printed | process note, SEE NOTE in the block, build-direction arrows, plus/minus with nominals |
| `pair-midplane`, `pair-origin-moved`, `pair-pattern-grew`, `pair-datum-changes` | the four regeneration pairs | ASME mm | matching and merge: ids kept, values followed, the new hole numbered next, a datum following its face |

19.4's "plate with hole kinds and patterns" is three goldens, as
`drawing_parts.py` builds three plates; "link plate, boss block, pocket and tab"
is three as well. Not built in `drawing_parts.py`, and so not drawn: the slot on
the inclined face (19.1 asks for a hole and a slot; the builder makes no
intersection curves). The other parts 19.1 lists that are not built (the cross
hole entering a cylinder, the manifold passage) are not 19.4 goldens.

## What a golden file holds

- **`expected`**, written by hand from the rules (sections 10 and 22 of
  `docs/DRAWINGS.md`, [conventions.md](conventions.md)), for the user to review
  once: the dimension set, one record a dimension, with its requirement key,
  kind, value as the sheet shows it in the drawing's unit (a basic value in
  brackets, `[.5906]`; a callout's further lines in `lines`; its frame), the
  tolerance kind, a datum symbol's letter and the axis of its face, and for a
  regeneration the dimension id, `state` and whether the user's move was kept.
  Some goldens add the view counts, what the sheet must and must not say, the
  features a regeneration resizes, loses and adds, and (`errors`) the error-level
  checks the rules give the drawing, such as o07's R4.complete for the width the
  user removed. The test compares it in full: a missing, extra or different
  record is a problem. Nothing rewrites it.
- **`findings`**, written by hand: where a golden shows the drawing is wrong by
  the rules, the finding in words and the exact problems the check reports.
- **`snapshot`**, recorded: the plan in short (one line a dimension, datums,
  notes, title fields, options, the graphs' verdicts, the bands and the drawing's
  checks at every level; for a regeneration the merge report), the SVG's numbers by layer
  (count, sum and a digest of them rounded to a hundredth of a millimetre,
  12.4), the PDF's inflated content (a digest, the operators counted, the
  optional content groups and the text in order) and the DXF's tags (a digest,
  the tag count and the entities counted by type and layer). The SolidSeas
  version, which the plot stamp, the PDF and the DXF's 999 comment carry, is
  written `{version}`, so a version bump changes no snapshot. A changed snapshot
  fails with the members that changed.

Where the rules leave a choice, the expected set takes the planner's when it is
one the rules allow, and says so here: the tab of `pocket-tab` is located by its
right face (either face would do); `inclined-face` locates the 45 degree face by
its meet line with the top (the one with the right face would do); an axis with
three or more locations is ordinate where layout measured the band too deep
(10.4); basic values carry the decimals they need, up to four in inches and three
in millimetres (10.8); a boss diameter takes the hole precision (three places in
inches); depths take two places in inches, as steps do.

## The checks (19.5)

One test a check a golden, all in `tests/test_drawing_golden.py`. Checks 1 to 3
read the plan stage's run the pipeline keeps (`Run.orchestrated`) for the part as
drawn (for a regeneration, of the new model); checks 4 and 5 read the drawing's
own checks, which the pipeline and regeneration attach to every drawing from
`checks.run_checks` on the sheet as finally laid out.

1. **Requirements:** every need the planner found and every location its graphs
   ask for is served by exactly one shown dimension, no key is shown twice, and
   no requirement is left without a view.
2. **Graphs:** every linear and angular graph complete and a tree.
3. **Oracle:** `tests/drawing_reconstruct.py` on the shown dimensions and the
   feature set finds nothing missing, redundant, wrong or unresolved. The planner
   has no centre lines of its own to give it yet (`Plan` holds none); holes in
   line are joined by one position naming them all.
4. **Layout:** no hard conflict on the sheet: what the checklist files under
   `R11.collisions` (text over text, an item layout could not place clear) and,
   under `R8.sheet`, the layout's own words for text outside the border or in the
   title, revision or notes block. A leader's angle and a cramped span are
   warnings and do not count.
5. **Automated checks:** no error-level check among the drawing's checks, apart
   from two kinds the rules give it. The empty DRAWN, MATERIAL and FINISH cells
   (`R6.title`) are right, as no golden is given a person, a material or a
   finish; the test leaves them out by name. Any other error the drawing rightly
   has is listed in the golden's `expected.errors`, written by hand (o07 is the
   one: the user removed the 10.0 width, so R4.complete says it is not stated).
   A reduced-dimension golden is also blocked from release by `COV.unclaimed`
   until that is accepted with a typed reason, and not once it is (the release
   checks run on the plan stage's run). Warnings and information do not count;
   the snapshot records them all. The test skips, saying why, when
   `pipeline.available()["checks"]` is false.
6. **Repeatable:** the `.ssdrw`, SVG, PDF and DXF written twice are the same
   bytes, and a fresh run writes the same SVG, PDF and DXF; regenerating against
   the unchanged model changes nothing, both as the hashes say so and when the
   model's hashes are made to differ so the pipeline runs again with the frozen
   options and merges (the dimensions, views and what the sheet draws stay as
   they were; the flags a merge sets afresh do not count).

## Findings, and how a finding closes

A check with a recorded finding is marked `xfail(strict=True)`. It is an
expected failure only while the check reports exactly the recorded problems. If
the problems change, the test fails outright and says how. When the drawing is
put right the check passes, which a strict xfail turns into a failure: take the
finding out of the golden's file (and refresh the snapshot, which will have
changed too).

## Refreshing the snapshots

```bash
SOLIDSEAS_REFRESH_GOLDENS=1 python -m pytest -q tests/test_drawing_golden.py -k snapshot
```

Each snapshot test then writes its golden's `snapshot` and passes; `expected`
and `findings` are written back unchanged, and a test checks that every file is
in the layout the refresh writes, so the diff is the snapshot alone. Review it
before committing. The hand-written sets are never refreshed: change them by
hand, after the user agrees the rules give something else.

## Open findings

The user's review items, measured on 0.2.151, after the integration stage's
fixes. Each names where it lies.

**Regeneration**

- `pair-datum-changes` (dimensions, merge, automated, repeatable): the datum
  widths change size by more than half (the 60 width along Y, datum B, becomes
  20; the 10 thickness along Z, datum A, becomes 80), so by `file.md`'s matching
  rule they do not pair, and the drawing asks for new datums A and B (13.4)
  instead of keeping them on the bottom and back faces, which still exist. The
  general profile note then names datums the drawing does not define, and
  regenerating again finds the new run's datum dimensions new each time.
  Whether a datum should follow its face when its width changes this much is
  for the review.

**The plan**

- `pocket-tab` (automated): R4.coincident: the block's top at Y .79 is two faces,
  either side of the tab, and the location .7874 and the .16 wall above the
  pocket reach them with one extension line and no count (10.2).
- `hole-kinds` (oracle): a hole callout is one record whose depth, counterbore,
  spotface, countersink and step are words in its suffix, where conventions.md 8
  asks for one record a value. The oracle reads the larger diameters as the
  bore's and finds the depths, shoulders and countersink angles missing. The
  callouts read right on the sheet.

**Notes, layout and sheet**

- `inclined-face` (automated): R10.text: the model-governs note names the model
  by its file name as it is, in lower case (inclined_hole_block), where notes are
  in capitals; whether a quoted file name may keep its case is for the review.

`four-holes`, `boss`, `sixteen-holes`, `patterns`, `arc-pattern`, `link`, `o02-mm`, `o02-in`,
`o11-mm`, `o11-in`, `o07-from-o02`, `pair-midplane` and `pair-origin-moved` pass
every check.

### Closed by the integration stage

- `o07-from-o02` (dimensions, merge): a saved drawing lost its feature
  descriptors, so regenerating the loaded o02 drawing matched nothing. The reader
  now takes capitalised types: the height keeps d-3 at 31.0, still moved, and the
  width stays removed.
- Regenerating against an unchanged model renamed the isometric v-4 to v-3 on
  eleven goldens; the frozen options now name every view drawn.
- `o02-mm`, `o02-in` (sheet): the proprietary statement printed `{company}` and
  lost its last words on an A sheet.
- `o02-in`, `o11-in`, `boss`, `inclined-face` (layout): the general profile
  note's frame on a row of its own reached into the words above it.
- `hole-kinds` (layout): two callouts could not be placed clear.
- `pair-datum-changes` (dimensions): the matcher paired widths across axes (the
  plate's thickness along Z, carrying datum A, with the block's width along Y),
  moving datum A to the block's largest face, the silent re-pick 13.4 forbids. A
  width's position now keeps its axis, so widths pair only along their own.
- `pair-pattern-grew` (layout, automated): the 10.0 thickness in the top view lay
  in the revision block: the arrangement measured a view's bands by their depth
  but not by how far along them a short span's text stands outside its end; it
  now counts both, so views and their dimensions stay clear of the title and
  revision blocks (a forced A sheet for the four-holes plate now takes 1:4 rather
  than reach into the title block at 1:2).
- `printed-bracket` (sheet, automated): the process note was left out though the
  tolerance note named SLA (both now name the process the settings list first
  when none is given); the tolerance note gave its figures without a unit (now
  `±0.051 MM ALONG X AND Y`); and the front view's build-direction arrow was left
  out when its three places were taken (layout now tries more, near first, and
  reports one it cannot place).
- `printed-bracket` (repeatable): regenerating against the unchanged model drew
  three views where the first run drew four, because the frozen options kept
  the chosen front (+y) but not its two quarter turns; they now keep both.
- `pair-origin-moved` (layout): the 10.0 thickness lay in the revision block
  (the same now happens on `pair-pattern-grew`).

### Closed in the viewer stage

- `o11-mm`, `o11-in` (oracle): the R3 rounds are stated by the fillet note,
  which the oracle did not read, so their radii and axes came out missing. The
  oracle now takes the note's radius (conventions.md 3) and places the rounds
  by their tangency, and the planner gives the radius exactly, where it gave it
  rounded to its merge step.
- `link` (dimensions, oracle): `loc/f-1/y` was redundant: the holes are coaxial
  with the full-round ends, whose centres the width and the derived 2X R already
  fix (conventions 4 and 5, 10.2), and the graph had no link from a derived
  radius's centre to the faces it is tangent to. The planner now joins a
  full-round end's centre, which the hole on its axis shares, to the face of its
  width the radius away, so the width places the holes across it.
- `pair-datum-changes` (layout, and R8.sheet and R11.collisions under
  automated): datum C's symbol could not be placed clear and lay outside the
  border. The views were centred beside the title column with nothing on the
  left of the side view but its face, and the symbol needs about 10.5 mm there.
  The arrangement now leaves a datum symbol its reach on the side it stands out
  on, unless that would cost the scale. The note naming the datums A and B that
  are gone (R18.datums) stays open with the datums' finding.
- `patterns` (oracle): the pitch circle's first angle came without the frame
  axis it is measured from, which the oracle read as a countersink's angle, so
  the angle and every member of the circular pattern were missing. The planner
  now gives the record its axis (X, the first frame axis square to the pattern's)
  and an anchor on the member it measures (conventions.md 8), and layout draws
  the angle from that axis.
- `patterns` (dimensions, requirements, oracle): `loc/f-4/x` located the grid's
  second column, which the grid's 2X pitch from the first column already
  locates, and its third location turned x to ordinate. The planner joined the
  grid's members to their first one at new positions, without their axes, so the
  grid's first column did not merge with the centre the row of five already had
  at the same X: the grid became a node of its own. With their axes they merge,
  the grid and the row are located together at .7874, and x is baseline, as the
  expected set says.
- `inclined-face` (dimensions, requirements, graphs, and R4.complete under
  automated): the 45 degree face was neither angled nor located. The recogniser
  took the first principal face it met as the meet line's, here an end face
  square to it (direction (0.71, -0.71, 0)). It now takes the neighbour whose
  normal is nearest its own, the larger of two as near, so the line runs along Z
  where the face meets the top. The planner joins the line's position along Y to
  the top face, whose plane it lies in, so the face is stated by its 45 degree
  angle and the 1.7717 to its meet line, as the expected set says. The oracle now
  judges such a face too (conventions.md 2): its angle stated once and one of its
  meet lines located. Its R10.text finding on the model-governs note stays open.

## What needs the PC

The user's review of each expected set (21, stage 1 item 3), and the engineer's
review of the printed goldens (20.4). Opening the goldens' PDFs in Edge, Chrome
and Acrobat Reader and printing them to scale is the PC's too (21, item 8).
