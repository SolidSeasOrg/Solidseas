# Signing, release and revisions

Status, signatures, release and revisions: `docs/DRAWINGS.md` sections 13.2,
13.3 and 17.2, as they are built in `drawing/release.py`.
Everything here is provisional until the first release that makes drawings.

## Status

| Status | When |
|---|---|
| PRELIMINARY | a new drawing, a drawing whose CHECKED signature an edit cleared, and every new revision until it is released. Its PDF and DXF are stamped "PRELIMINARY - NOT FOR MANUFACTURE" and named with ` PRELIMINARY` |
| CHECKED | once someone signs the CHECKED row |
| RELEASED | after Release; read-only |

A new drawing carries only the DRAWN row: the name chosen in the wizard (the
CLI's `--drawn-by`) and the date it was made.

## Signatures are records

A signature is a record of who approved what and when: the row, the person's
name from the People list of Drawing Settings, the date (always stored as
`YYYY-MM-DD`; the settings' date format is how it is shown), and the digest of
the drawing's content at that moment. **It is not a cryptographic signature.**
Anyone who can edit the file can edit a signature; the digest only lets
SolidSeas notice that the content no longer matches what was signed.

`release.content_digest(drawing)` is the SHA-256 of what a signature covers: the
drawing's id, the model's identity (name, format, configuration, file hash,
geometry and properties digests, part number, model revision, units; not where
the model was found), the frozen options, the settings snapshot, the title
fields, the features and their decisions, the datums, the dimensions, the notes,
and the revision rows' marks, zones and descriptions. It does not cover the
status, the signatures, the accepted items, the outputs, the ids still free, the
laid-out sheet or the file's times: the sheet shows the signatures and the
stamp, and Release fills the revision row's date and approver, and neither may
undo what was signed.

## Signing

`release.sign(drawing, row, person, today)` is the editor's Sign...; the
command line never signs. It records a signature on `row` with today's date and
the content digest, and returns the drawing and any warnings.

- Only a row the settings use may be signed (DRAWN, CHECKED and APPROVED by
  default; ENGR, MFG and QA when the company adds them).
- Only a person in the People list may sign, named by name or initials; with an
  empty list nobody can, and the editor says to add the people first.
- A row is signed once; signing it again needs an edit to have cleared it.
- The same person on a second row is a warning when the settings allow it (the
  default) and an error (rule `same_person`) otherwise.
- Signing CHECKED moves the status to CHECKED.

## An edit clears what it invalidates

After every edit the editor calls `release.invalidate(drawing)`. It clears every
signature whose digest no longer matches the content, except DRAWN, sets the
status back to PRELIMINARY when CHECKED was cleared, and returns what it cleared
in words ("the edit cleared the CHECKED signature of Carl Dee"). An edit that
changed no content clears nothing. Regeneration does the same.

## Release

`release.release(drawing, today, accepted)` needs:

- every row the settings require (CHECKED and APPROVED by default) signed, and
  each signature's digest the current content's;
- no error-level check, except `COV.unclaimed` and `R2.override` items the user
  accepted with a typed reason (`accepted` maps a check's item, or its code, to
  the reason);
- the material in the settings' list, or accepted as typed (`accepted` names
  `material`);
- no dimension marked `needs_attention`.

Otherwise it raises `ReleaseRefusedError` (an `InvalidArgumentError` with rule
`release_refused`) whose `reasons` list every reason; `release_problems` gives
the same list without raising, for the editor to show before the user tries.
The checks it reads are the drawing's own (`Drawing.checks`) or those passed in,
each a mapping or object with `level`, `code`, `item` and `message`.

Release sets RELEASED, fills the revision row's date and approver (the APPROVED
signer, else the last required row's), and records the accepted items with their
reasons in the drawing's `accepted` member. The released PDF and DXF are then
written without the stamp, as new files (`document.export_target`, which never
replaces anything for a released drawing), and recorded with their hashes
(`document.record_output`). The command line never releases.

## A released drawing is read-only

The library's operations that change a drawing refuse a RELEASED one with
`DrawingReleasedError` (code `drawing_released`, a subclass of
`InvalidArgumentError`), `detail == {"parameter": "drawing", "rule":
"drawing_released"}` (`release.require_editable`). `sign`, `invalidate`,
`merge`, `regenerate` and every edit of `drawing.edit` but Start Revision refuse
it this way ([edit.md](edit.md)). `regenerate(drawing, part, revision=...)`
starts the next revision of a released drawing first and then updates it from
its changed model.

A file claiming RELEASED is data like any other member. `check_release_record`
compares it with the files: when a released export of the current revision is
missing or has another hash than its record, the first problem is "release
record does not match the files", and those files are never exported over; when
a required signature's digest no longer matches the content, it adds "the
signatures do not match the drawing's content".

## Revisions

`release.start_revision(drawing, description, zones)` opens a RELEASED drawing
for its next revision:

- the next mark, A, B, ... skipping I, O, Q, S, X and Z, with AA after Y
  (`standards.next_revision`; the rule is marked verify there until the
  standard is bought);
- a revision row with the description (the editor pre-fills it from the edit log
  and the merge report's `description`) and the zones of the changed items;
- every signature cleared, and DRAWN signed again when a name is given;
- PRELIMINARY.

The released row keeps its date and approver. Released files are never
overwritten: each revision's exports have their own names (`1234-001 B
PRELIMINARY.pdf`, then `1234-001 B.pdf`). Before the first release a drawing is
saved and exported freely, and Start Revision is refused (rule `not_released`).
