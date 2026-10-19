# Editing a drawing

The edits of `docs/DRAWINGS.md` 10.12, as integration built them in
`drawing/edit.py`. Everything here is provisional until the first release that
makes drawings.

## How an edit works

Every operation takes a drawing and returns `(drawing, checks)`: a new drawing and
the checks of 20.1 on it. The drawing given is never changed, so the viewer's undo
keeps the drawings it had. An operation:

1. changes the drawing's records: a dimension, a feature's decisions, the datums,
   the notes, the title, the frozen options or the settings snapshot;
2. lays the sheet out again from the model with the records applied
   (`edit.relayout`);
3. clears the signatures the change invalidated (`release.invalidate`, 13.2), so
   an edit after CHECKED goes back to PRELIMINARY;
4. runs the checks.

A RELEASED drawing refuses every operation but Start Revision, with rule
`drawing_released`. Start Revision lays the sheet out again, so it needs the
model too; for a released drawing whose model has changed (which `attach`
refuses), `drawing.regenerate(drawing, part, revision="HEIGHT CHANGED")` starts
the revision and updates the drawing from the changed model in one step, so the
revision's sheet is never left unstamped.

## The model

Laying a sheet out again needs the model. A drawing opened without it is
view-only (13.6); editing without the model needs the geometry cache, which is
stage 4.

- The run that made a drawing, or regenerated it, is kept beside it in the
  process, for at most 8 drawings, the most recently used kept.
- `edit.attach(drawing, part)` opens the model of a drawing read from a file. It
  refuses a model whose file hash and geometry digest both differ from the
  drawing's, with rule `model_changed`: Update from Model takes a changed model.
- Without either, an edit raises `InvalidArgumentError` with rule
  `model_not_found`.

The frozen options name every view the views stage drew, not only those the plan
kept, so drawing the views again gives each view the id it had. Adding a
principal view can renumber the views after it; a dimension whose view id
changed loses a placement the user gave it, and says so (`placement_reset`).

## Records applied

`edit.relayout` plans with the drawing's feature ids, decisions, datums and
frozen options. Each planned dimension takes the record with its key:

- From the record: its id, state, placement, side and value override.
- From the record where the user set them: precision (`places_source` is
  `user`), tolerance (flag `user_tolerance`), frame (flag `user_frame`), and
  prefix and suffix (flag `user_text`).
- Everything else comes from the new plan: the value, the view, the positions and
  the features.

Notes and title fields are the drawing's own, and the revision row and the
approval rows come from its records. The linear and angular graphs are checked
again with only the dimensions shown. A removed location is reported as missing,
and a user dimension that closes a loop as redundant.

| Record | What relayout does |
|---|---|
| A removed generated dimension | stays in the list, off the sheet |
| A user dimension | found again from its features; kept and marked `needs_attention`, off the sheet, when they no longer give it |
| A generated dimension whose requirement went away | dropped (for example a location an edit replaced with a link) |
| A requirement that is new | added with the next free id |

When nothing the plan reads changed (options other than sheet and scale, the
settings snapshot, the features' decisions, the datums), the last plan is laid
out again without planning.

A new drawing is laid out once more from its records as it is made: the plan stage
lays the sheet out before the drawing exists, so this fills the revision row and
DRAWN's date.

## Decisions on features

A feature carries the user's decisions (13.1 `features[].decisions`), which
regeneration keeps on its matched feature:

| Decision | Meaning |
|---|---|
| `datum` | its datum letter |
| `thread`, `thread_depth` | a confirmed thread and, for a blind hole, its depth in metres; `thread` null when the user answered that the hole is plain |
| `into_bore_note` | a confirmed end in a cross bore: the callout says INTO BORE |
| `depth_from` | `floor`: the floor measured from the far side of the part instead of the depth from the open face |
| `origin_x`, `origin_y`, `origin_z` | `centre` or a face index: that axis is measured from this feature |
| `link_x`, `link_y`, `link_z` | the feature this one is located from along that axis, instead of from the origin |

The planner reads them:
- `plan/requirements.py` reads the origins and depth references;
- `plan/graph.py` reads the links, through `fixed_links`;
- `plan/callouts.py` reads the threads and the ends;
- `plan/keep.py` keeps every feature with a decision on a key-dimensions drawing
  (10.10), and every feature the drawing's own dimensions name: one the user added,
  moved, overrode or removed (`edit._named`, passed as `orchestrate.run(named=...)`),
  so a re-plan never leaves them to the model and a user's distance never loses its
  features.

## Operations

| Operation | Effect |
|---|---|
| `remove(d, id)`, `restore(d, id)` | a generated dimension off the sheet and back; regeneration keeps it removed |
| `delete(d, id)` | a dimension the user added is gone |
| `candidates(d, features)`, `add(d, candidate)` | for one or two picked features: the removed dimensions to restore, and the distance between two features along each axis one view shows; adding one makes a user dimension (key `user/distance/f-a/f-b/axis`) |
| `link(d, a, b, axis)`, `unlink(d, b, axis)` | locate `b` from `a` instead of the origin, keeping the tree; a link that would close a loop is refused |
| `set_origin(d, axis, feature, face=None)` | that axis measured from the feature's centre plane or one of its faces; None goes back to the datum |
| `set_scheme(d, view, axis, scheme)` | baseline or ordinate |
| `set_depth_reference(d, feature, reference)` | `open` or `floor` |
| `set_tolerance(d, id, kind, upper, lower)` | block, basic, reference, or explicit; `block` goes back to the planner's choice |
| `set_precision(d, id, places)` | 0 to 4 decimals; None goes back to the role's |
| `set_prefix`, `set_suffix`, `reset_text` | kept apart from the value |
| `override_value(d, id, text)` | the user's text for the value, with R2.override |
| `set_frame`, `reset_frame` | a feature control frame; the datums it names must exist |
| `set_datum(d, letter, face)` | a datum on a face of a feature in the table, or off |
| `move(d, id, along_mm, across_mm)`, `flip(d, id)`, `reset_position(d, id)` | see Placement below |
| `set_sheet`, `set_scale`, `set_units` | for this drawing |
| `add_view(d, name)`, `remove_view(d, name)` | principal views; the front stays |
| `edit_notes(d, texts)` | notes in order; an unchanged note keeps its id and origin, others are the user's |
| `set_title(d, key, text)` | a typed title field; a material or finish in the list shows as its callout |
| `set_tolerance_block(d, rows)` | the block of the drawing's unit, in its settings snapshot |
| `use_settings(d, settings)` | Use Current Drawing Settings |
| `confirm_thread(d, feature, spec, depth)`, `clear_thread(d, feature)`, `confirm_end(d, feature)` | the user's decisions on a hole: a thread, or None for a plain hole (the question answered); `clear_thread` opens the question again |
| `sign`, `release_drawing`, `start_revision` | 13.2 and 13.3, laid out again: names in the title block, no stamp once released, the stamp back on a new revision; release runs the release-time checks |
| `checks(d, at_release=False)` | the checks of the drawing as it is |

## Placement

A placement is stored relative to the dimension's attach points, in paper
millimetres (13.4):

- **A linear dimension:** `move` shifts its text along its line and its line
  across, away from the view when positive. The line runs on to a text moved past
  its ends.
- **A leader item:** `move` shifts its shoulder by (along, across) as sheet x and
  y.
- **`flip`:** puts a linear dimension on the other side of its view, or a leader's
  text on the other side of its feature. An ordinate dimension stays in its row.
- **`reset_position`:** gives both back to layout.

## Not in stage 1

Each of these raises `not_implemented` with rule `later_release`:
- sections and detail views on request (3.3 lists on-request detail views first
  among what slips to stage 2);
- flag notes.

Free picking of arbitrary edges for Add Dimension is stage 4.

## Speed

On the VM, an edit of a seeded 100-hole plate (201 dimensions) lays out again in
about 0.25 s, against the 0.3 s target of section 21. The VM was shared with
other test runs when this was measured.

## Tests

`tests/test_drawing_edit.py` covers:
- a new drawing laid out from its records;
- an edit without the model, `attach` with the same model and with a changed one;
- the kept runs' bound;
- remove, restore and delete;
- link, origin and scheme;
- Add Dimension from the candidates;
- a depth from the floor;
- tolerance, precision, text and override;
- frames and datums;
- move, flip and reset;
- sheet, scale, units and views;
- notes, title and the tolerance block;
- a confirmed thread;
- signing, release and a new revision;
- edits that survive Update from Model (o02 to o07);
- determinism;
- the speed of an edit on the 100-hole plate;
- a released drawing refusing every edit.
