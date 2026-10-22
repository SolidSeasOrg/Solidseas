# The drawing file

The `.ssdrw` file, where Save may write it, ids that survive a model change,
regeneration and finding the model: `docs/DRAWINGS.md` sections 12.5, 12.6, 13.1
and 13.4 to 13.6, as they are built. Everything here is
provisional until the first release that makes drawings.

| Module | Holds |
|---|---|
| `drawing/document.py` | the file (`dumps`, `loads`, `read`, `load`, `save`), the records the core types lack, a new drawing (`new_drawing`, the pipeline's `assemble` stage), names, what Save may replace, the folder check |
| `drawing/match.py` | matching features between two versions of a model (13.4), with the Hungarian method |
| `drawing/merge.py` | `regenerate` and `merge` (13.5) and the merge report |
| `drawing/locate.py` | finding the model (13.6), and the model's paths written into a drawing |
| `drawing/release.py` | status, signatures, release and revisions: [release.md](release.md) |

## The file

UTF-8 JSON without a byte order mark: one object, its members in a fixed order,
numbers in shortest round-trip form (Python's `repr` of a float), model
quantities in metres and radians, sheet quantities in millimetres, and the
laid-out sheet in the compact form of `display.to_compact` (integer
micrometres). The schema is `solidseas.drawing/1`. The same drawing always
writes the same bytes. Each record (a feature, a dimension, a note...) is on a
line of its own, so a change to one dimension is one changed line in git, and
the sheet is compact on a line of its own.

| Member | Holds |
|---|---|
| `schema` | `solidseas.drawing/1` |
| `id` | the drawing's id: a UUID, random, or derived from a seed so a test or the CLI can make the same drawing twice |
| `generator` | `{"name": "SolidSeas", "version": ...}` of the SolidSeas that wrote the file |
| `created`, `modified` | ISO 8601 times with the local offset; `save` sets `modified` |
| `model` | the model's name, its path relative to the drawing's folder, its absolute path only when there is no relative one, format, configuration, the file's SHA-256, the geometry digest, the properties digest, part number, model revision, units and their origin, and `extents` (the part's extents in the datum frame, which matching normalises by; an addition to 13.1's example) |
| `options` | frozen at creation: process, profile, units, scheme, arrangement, front direction and turn, the view set, sheet, scale, hidden and tangent modes, bodies, quality, configuration; and only when they are set, the parts list, the detail level, moved balloons, `mode` (`express` for an Express drawing, DRAWINGS.md 10.4b) and `view_sheets`, the views put on a sheet of their own (`{"isometric": 2}`, DRAWINGS.md 11.7) |
| `settings` | the Drawing Settings snapshot, as `settings.to_dict` writes it (the logo's SHA-256 is in it; the logo's PNG travels in the sheet's image item) |
| `title` | title fields by name, each with its text and origin (`part`, `list`, `typed`) |
| `features` | id, descriptor (type, size signature, adjacency, position) and the user's decisions (a datum letter, a thread confirmation...) |
| `datums` | the datum letters, their faces and why each was chosen (C28; an addition to 13.1's example) |
| `dimensions` | key, id, origin, state, view, placement, text (prefix, suffix lines, override), precision, tolerance, frame, then kind, role, axis, features, the requirement keys served, value, positions, anchor, radius, side and flags |
| `notes` | id, origin (`template` or `user`), text and inline frames |
| `status`, `signatures`, `accepted`, `revisions`, `outputs` | see [release.md](release.md); `accepted` lists what Release accepted with the typed reasons (an addition to 13.1's example) |
| `next_id` | the next free number of feature, dimension, note and view ids |
| `sheet` | the laid-out display list, so the drawing reopens view-only and exports without the model. A drawing of several sheets (an assembly's long parts list, DRAWINGS.md 11.7) keeps them all here: the first sheet's item has a ninth value listing the sheets after it, written only when there are any, so a drawing of one sheet writes what it always did. More sheets than `DrawingLimits.sheets` (16) leave the drawing without its sheet, written back as it came |

A removed generated dimension stays in `dimensions` with state `removed`, so the
editor can restore it and regeneration keeps it removed; a deleted user
dimension is gone.

### The records the core types do not hold

The core types (`drawing/types.py`) have no field for a dimension's placement,
text override or flags, a note's origin, or the file's times and accepted items.
`document.py` adds them as subclasses, so code that reads the core types reads
these too:

- `DimensionRecord(PlannedDimension)`: `placement` (a `Placement`: offsets along
  and across in paper millimetres, the track, and whether the user moved it),
  `override` (the user's text), and `flags`: `new`, `changed`,
  `needs_attention` and `placement_reset` set by regeneration, `user_tolerance`
  and `user_frame` set by the editor to say which overrides regeneration keeps.
- `NoteRecord(NoteLine)`: `origin`.
- `DrawingDocument(Drawing)`: `created`, `modified`, `accepted`.

`as_record` and `as_document` turn a core instance into these. A plain
`PlannedDimension` or `Drawing` is written and read back as one of them.

## Reading: hostile input

A `.ssdrw` can arrive by email, so `loads` reads it as hostile input (17.2).
Before anything else it checks, and refuses the whole file with the reason when
one fails:

- the size: at most `drawing_bytes` (16 MiB), checked before parsing;
- strict JSON: UTF-8 with no byte order mark, no member repeated in an object,
  no `NaN` or `Infinity`, no number too large to be finite, no whole number of
  more than 20 digits;
- nesting: at most `json_depth` (32) levels;
- the schema: `solidseas.drawing/1` (a minor such as `/1.3` is read); a higher
  major is refused with "the drawing was written by a newer SolidSeas
  (solidseas.drawing/2); update SolidSeas to open it", and anything else is "not
  a SolidSeas drawing";
- ids: the drawing's id, every feature, dimension and note id, every view a
  dimension names and every feature it refers to match `[a-z0-9-]{1,64}`, and no
  feature, dimension or note id is given twice;
- numbers: finite and at most 1e15 in size;
- strings: at most `string_chars` (4,096) characters outside the sheet, and
  valid Unicode (no lone surrogate);
- arrays: at most 10,000 entries and objects at most 2,000 members outside the
  sheet; features and dimensions at most `requirements` (5,000); notes 400,
  revisions and outputs 1,000; the sheet member at most `sheet_bytes` (12 MiB).

A refusal raises `DrawingFileError`, a subclass of `InvalidArgumentError` with
`detail["rule"] == "drawing_invalid"` and `detail["value"]` naming the check
(`bom`, `not_utf8`, `json`, `number_range`, `unicode`, `not_object`, `schema`,
`schema_newer`, `id`, `id_twice`, `members`, `array_bounds`), or `SldLimitError`
naming the bound (`drawing_bytes`, `json_depth`, `string_chars`,
`requirements`, `sheet_bytes`, `unknown_bytes`). Integration gives the first the
error code `drawing_invalid`.

After that every value is checked on its own. One that fails falls back to its
default, or its record is left out, and `loads` returns the reason with it
(`load` puts them in the drawing's `warnings`, which the editor lists): a bad
status becomes PRELIMINARY, a bad option its default, a bad placement none (the
layout places the dimension again), a record with a bad key or kind is left out,
an output whose name is not a plain file name is left out, and `next_id` is
never below an id the drawing uses. A sheet this SolidSeas cannot read leaves
the drawing without its sheet and is written back as it came.

**Unknown members** a newer SolidSeas wrote, at the top level or inside a record
(a dimension, a feature or its descriptor, a note, a datum, a signature, a
revision row, an output, a title field, the options, the model), are kept,
never interpreted, and written back where they were, at most `unknown_bytes`
(1 MiB) of them. They stay with their record: an edit that deletes a record
deletes its unknown members too.

## Saving: what Save may replace

The user decided where drawings go (Q8, section 12.6): next to the part by
default, under the 3D Print file's safety rules, never replacing a file
SolidSeas did not write, a setting choosing another folder. And what Save may
replace (Q14, answered 2026-10-05): the same drawing's own `.ssdrw`, and its
PRELIMINARY PDF and DXF to keep them current, when SolidSeas wrote them and they
are unchanged since. Every other file, and every released export, is never
replaced. The switch is the setting `files.replace_own_files`, on by default.

**`save(drawing, path, replaces=None)`** writes exactly `path` (a `.ssdrw`) and
never picks a name. A path that exists is refused (`OutputRefusedError`, rule
`exists`) unless `replaces` is given and equals the SHA-256 of the file there now
(else rule `changed`). A link (`link`), a folder, a device or anything but a
plain file (`not_a_file`) is refused either way, and on Windows a device name or
a stream. The file is written through a temporary name and a rename
(`export.write_new`), so a failed save leaves the old file. The hash is not kept
in the file, which cannot hold its own hash: `read` returns it with the drawing,
the editor keeps it for the file it has open, `save` returns the new one, and
the CLI's `drawing update` uses the hash of the file as it read it.

The decisions around `save` are helpers that return a `Target` (the path, what it
may replace, whether a numbered name was taken, and the words for the status
line):

- **`save_target(drawing, path, loaded_sha256=...)`**. With `replace_own_files`
  on, the file at `path` is replaced only when it is a SolidSeas drawing with the
  same id that still has `loaded_sha256`; anything else (another drawing's file,
  a changed file, a file SolidSeas did not write) gets the next free name. With
  it off every save is a new file (`1234-001 (2).ssdrw`, then `(3)`), and the
  earlier file stays as it was.
- **`export_target(drawing, folder, kind)`**. A released export is created new
  and never replaces anything. A PRELIMINARY export replaces its own earlier
  file only with `replace_own_files` and "keep preliminary exports up to date"
  both on, and only when `outputs` lists that name, unreleased, with the hash the
  file still has, and the file says SolidSeas wrote it: a PDF whose `/Producer`
  starts with `SolidSeas`, a DXF whose first line is `999` and second starts with
  `SolidSeas` (`says_solidseas`; the PDF and DXF writers must write these).
  Anything else gets the next free name.
- **`write_output(path, write, replaces=None)`** writes an export under the same
  rules as `save`, at most `output_bytes`, and returns its hash;
  **`record_output(drawing, kind, name, sha256)`** records it in `outputs`,
  replacing the record of an earlier write of the same unreleased file and
  never a released one.
- **`folder_problem(folder, opened)`** checks a folder as the viewer's
  `printing.folder_problem` checks a print's: a device or stream path, a network
  share or mapped drive outside the opened folder, a link, junction or cloud
  placeholder at the folder or above it, or not a folder is refused with the
  reason. A refused folder never sends the files elsewhere on its own: the
  wizard and the editor ask for another, the CLI fails and writes nothing.

## Names (12.5)

Exports are named by the settings' pattern (`{number} {revision}`, which may
also hold `{title}` and `{part_number}`) through the rules of the viewer's
`printing.safe_stem`, mirrored in `document.safe_stem` so the library never
imports the viewer: characters a file name cannot hold become `_`, at most 80
characters, never a Windows device name, never empty. Unreleased exports end in
` PRELIMINARY` (`1234-001 A PRELIMINARY.pdf`); released ones do not
(`1234-001 A.pdf`). The number falls back to the part number and then the
model's name. The `.ssdrw` is named by the number alone (`1234-001.ssdrw`),
since one file carries every revision. A name taken by a file SolidSeas may not
replace gets ` (2)`, ` (3)` and on (`next_free_name`), counted from the name
without its number.

## A new drawing and its ids (13.4)

`new_drawing(source, planned, options, settings, fields)` is the pipeline's
`assemble` stage. It makes a PRELIMINARY drawing:

- features get ids `f-1`, `f-2`... in recognition order, each with its
  descriptor and, for a feature that claims a datum's face, the datum's letter
  as a decision;
- dimensions get ids `d-1`, `d-2`... in planning order (the sheet's dimensions
  and their painted items are renamed to follow), notes `n-1`... with origin
  `template`, and `next_id` the next free numbers;
- title fields come from `fields` (origin `typed`; a material the settings' list
  maps, or a finish it names by name or callout, becomes its callout, origin
  `list`), else from the part's properties
  under the settings' names (origin `part`; the part's material as its callout
  when the list maps it);
- the model's identity comes from the source, its relative path the model's
  name (the drawing goes next to the part by default; `locate.with_model_path`
  sets the paths for another folder);
- the options are frozen as the run chose them: units, scheme, view set, sheet,
  scale and front direction;
- `fields["drawn_by"]` signs DRAWN with the date and the content digest; the first
  revision row is the typed or part revision when it is a revision mark, else
  the settings' first revision, described `INITIAL RELEASE`.

The plan stage returns `(Plan, Sheet)`, which carries no `FeatureSet`, so the
feature table needs the run's features passed as `features=` (or as a third
member of `planned`). The pipeline does not pass them yet; until it does, a
drawing it assembles has an empty feature table and says so in its warnings.

A fresh drawing from the same model, options and seed gets the same ids and the
same bytes.

## Matching features (13.4)

`match.match(old, new)` pairs the drawing's features with a new run's by their
descriptors, never by node ids, deterministically:

1. Within each type, features whose size signatures are equal are paired by an
   assignment problem on their positions.
2. What is left is paired the same way among features whose sizes are within
   half of each other (every numeric size value; everything else equal), and
   those pairs are marked changed size.

The assignment is the Hungarian method, implemented in `match.py` (the shortest
augmenting path form) and bounded: a group with more than 300 features on a side
is paired nearest first and named in the result. The cost is the distance
between positions in the datum frame, each axis normalised by the part's extent
along it, after carrying the old position into the new extent: a mid-plane
extrusion that grew moves its end faces proportionally rather than "far", and a
part whose origin moved keeps its features. Adjacency (the entry face's normal,
neighbouring kinds, member counts) only breaks ties. A pair further apart than a
full extent (equal size) or a quarter of it (changed size) is not a pair.
Unmatched old features are gone; unmatched new ones are new.

A descriptor's position of three numbers is a point; one number is an offset
along the axis its adjacency's `axis` or `normal` names; anything else is
compared as it is, normalised by the part's diagonal. The extents come from the
drawing's `model.extents`, else the box of the descriptors' positions. These are
the conventions the feature recogniser is asked to follow when
it builds descriptors.

The tests cover the four regeneration pairs of 19.1 (a mid-plane extrusion
lengthened, the origin moved, a hole added to a pattern, a datum face that is no
longer the largest) and the o02 to o07 change, as descriptor sets built by hand:
the feature recogniser is not merged yet.

## Regeneration (13.5)

`regenerate(drawing, source)` updates a drawing from its model:

- the model's file hash equal to the drawing's: "the model is unchanged" (for an
  assembly, whose parts are files of their own, its geometry digest must be equal
  too: `assembly.same_file`);
- the geometry digest unchanged: only the model reference changes ("model file
  changed, geometry unchanged"), with the title fields whose origin is `part`
  following the part; the result is offered to the user;
- otherwise the pipeline runs again with the drawing's frozen options and
  settings snapshot, and `merge` merges the run in. Until every stage is built
  this raises `UnsupportedOperationError` with rule `stage_missing` naming the
  first missing stage. `regenerate(drawing, new=other)` merges a run made
  elsewhere, and `merge(old, new)` is the merge itself.

The merge keeps the user's edits. Matched features keep their ids and the
user's decisions; new ones take the next free ids. Dimension keys are compared
in the drawing's own id space: an exact match inherits the id, state, placement
and overrides (a placement whose view or side changed is reset and reported); a
new requirement is added and marked `new`; a generated dimension whose
requirement is gone is dropped (a removed one forgotten, a shown one reported);
a user dimension whose features are gone is kept, marked `needs_attention`,
kept off the sheet and out of exports, and blocks release until fixed. A datum
follows its matched feature, even when the new run would pick another face; a
datum whose face is gone is reported ("choose a new datum A") and never
re-picked. Notes and title fields are never regenerated, except fields of
origin `part`. Options, settings snapshot, revisions and outputs stay; the
signatures the merge invalidates are cleared. The merged sheet is the new run's
with the merged ids and removed dimensions taken off; user placements and kept
user dimensions show when the layout stage lays it out again from the records.

The report (`MergeReport`) counts dimensions, "31 unchanged, 2 changed, 3 new, 1
dropped, 1 needs attention" (a datum whose face is gone counts as needing
attention), lists the features matched, resized, gone and new and the lines to
show, reads the same in the editor and in `drawing update --json`
(`to_dict`), and pre-fills the next revision row (`description`). A RELEASED
drawing must start a revision before it is updated.

## Finding the model (13.6)

The paths in a drawing are untrusted. `locate.find_model(drawing_path, model)`
looks, in order, at:

1. the relative path joined to the drawing's folder, only when it stays inside
   it (every component passes `solidseas.resolve`'s checks: no `..`, no stream,
   no device name; no anchor; no link on the way);
2. the stored path, only on a local drive: never a UNC path or a mapped network
   drive, and nothing there is touched;
3. the catalog, when one is given, by SHA-256 and then by name.

Each candidate carries its hash and whether it matches the drawing's. A file
whose hash differs is offered ("this file has changed since the drawing was
made") and never taken: `Lookup.found` is only ever a matching candidate. The
catalog is any callable `catalog(kind, value)` returning paths, and the hashing
and drive kind are callables too, so the lookup is pure and a Windows path is
judged from its text on any system.

`locate.model_reference` and `with_model_path` write the other way: the path
relative to the drawing's folder when the model is in it or below it, else the
absolute path. `for_sending` drops the absolute path, as Save a Copy to Send
does (section 18).

## Requests for the core

- `pipeline.run` calls the `assemble` stage as `new_drawing(source, planned,
  options, settings, fields)` without the run's `FeatureSet`; it should pass
  `features=made["features"]`, or the plan stage should return it, so the
  feature table has its descriptors.
- `types.PlannedDimension`, `types.NoteLine` and `types.Drawing` have no fields
  for a placement, a text override, flags, a note's origin, or the file's times
  and accepted items; `document.py` adds them as subclasses. The planned
  revision of the types (section 6) could take them in.
- `types.Datum` names a face index, which is the BrepModel's of one run; naming
  the datum's feature id would let a datum survive a regeneration without the
  feature table's decisions. Until then a merged datum keeps its letter on its
  feature, and its face is -1 when the new run did not make that feature a datum.
