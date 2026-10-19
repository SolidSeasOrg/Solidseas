# The drawing command, `drawing_result` and the drawing error codes

`solidseas drawing ACTION` is the command line of automatic drawings
(`docs/DRAWINGS.md` 14), built in the integration stage. It is
provisional until the first release that makes drawings, like the rest of
`solidseas.drawing`. Every action prints one `drawing_result` under `--json`
(`docs/API.md` 5.17) and plain words otherwise.

The command never signs or releases a drawing: approvals come from a person in the
viewer. It never writes a file it did not write, never replaces a released export,
writes a drawing over its own file only when that file is unchanged since it was
read, and never writes a part. The examples use the fictional part
`bracket.SLDPRT` of the fictional Example Engineering Co.

## Actions

| Action | Does | Exit |
|---|---|---|
| `drawing new PART --out DIR [options] [--pdf] [--dxf]` | makes a PRELIMINARY drawing; always the `.ssdrw`, the PDF and DXF on request | 0 |
| `drawing export DRAWING [--pdf] [--dxf] --out DIR` | writes the drawing's PDF and DXF from the file's sheet (both when neither is named); a released drawing exports its released revision | 0 |
| `drawing update DRAWING [--model PART] [--dry-run]` | regenerates and merges (13.5), keeping the user's edits; refuses a released drawing | 0 |
| `drawing check DRAWING_OR_PART [--strict] [--model PART]` | the checklist (20.1), coverage and thread candidates; `--model` verifies a model against the drawing's MODEL reference | 0, or 4 when a check failed |
| `drawing show DRAWING` | the summary, status, signatures and revisions | 0 |
| `drawing settings` | the effective Drawing Settings and every value that fell back to its default | 0 |

`new` and `check` of a part, and `settings`, read the user's `Drawing.json`
(`docs/API.md` 3.24), or the file `--settings FILE` names, which must exist. The
command line never writes Drawing Settings.

### `new`

```text
solidseas drawing new bracket.SLDPRT --out D:\Drawings --title "BRACKET, MOTOR MOUNT" --number 1234-001 --drawn-by "Ann Bee" --pdf --dxf
```

writes `1234-001.ssdrw`, `1234-001 A PRELIMINARY.pdf` and
`1234-001 A PRELIMINARY.dxf` in `D:\Drawings`. An assembly (`frame.SLDASM`) is drawn
the same way, with its views, parts list and item balloons and no dimensions
([assemblies.md](assemblies.md)); its summary line counts the parts list's items
and the balloons. The options are those of the table in 14:

| Option | Meaning |
|---|---|
| `--configuration C` | the configuration drawn (default: the active one) |
| `--process machined\|printed` | default `machined` |
| `--scheme datum\|plusminus` | default: the process's (datum machined, plus/minus printed) |
| `--detail simplified\|complex\|full` | how much the drawing says (`docs/DRAWINGS.md` 10.4a); default: Drawing Settings' default level, `full` unless changed |
| `--units part\|in\|mm` | default `part`: the part's unit. A part that states no unit is refused (`invalid_argument`, `detail.rule` `units_unstated`, exit 2) unless `--units` names `in` or `mm`, so an unattended run never guesses silently. Drawing Settings that fix the unit (`standard.units`) count as naming one |
| `--views auto\|LIST` | `auto`, or view names separated by commas: `front,top,right,isometric` |
| `--front auto\|+x\|-x\|+y\|-y\|+z\|-z`, `--turn 0..3` | the direction the front view looks from and its quarter turns (default: chosen, 8.2) |
| `--sheet auto\|A..E`, `--scale auto\|N:M` | such as `B` and `1:2` |
| `--title`, `--number`, `--part-number`, `--revision`, `--material`, `--finish`, `--drawn-by` | title fields typed by the user (origin `typed`; a material or finish in the Settings' list takes its callout, origin `list`); `--drawn-by` signs DRAWN with today's date, as the wizard's page 2 does. Fields not given come from the part's properties (origin `part`) |
| `--confirm-threads FILE` | the user's answers for thread candidates (below) |
| `--settings FILE` | Drawing Settings to use instead of the user's |
| `--out DIR` | the folder to write in; it must exist |
| `--pdf`, `--dxf` | also write the PRELIMINARY exports |
| `--allow-source-dir` | allow `--out` to be the part's folder or below it |

A bad value is a usage error (`invalid_argument`, exit 2) naming the option, and
nothing is written.

**Where files go (12.5, 12.6).** `--out` is checked as the 3D Print file's folder
is (`document.folder_problem`: no link or junction on the way, no cloud
placeholder, no network share or device path) and by the command line's write
guards (not the part's folder unless `--allow-source-dir`); a refused folder fails
with `output_refused` (exit 3) and writes nothing. The `.ssdrw` is named by the
drawing number (`document.drawing_file_name`) and the exports by the Settings'
pattern with ` PRELIMINARY` (`document.export_name`). A name already taken by a
file the drawing did not write gets ` (2)`, ` (3)` and so on (`save_target`,
`export_target`), and a warning says so: a new drawing never replaces anything.
Files are written through `document.save` and `write_output` (a temporary name and
a rename, never through a link), and the exports are recorded in the drawing's
`outputs` before the `.ssdrw` is saved, so a later export can keep them current.
The drawing records where the part is from where it was saved
(`locate.with_model_path`): the relative path when the part is in the drawing's
folder or below it, else the absolute path.

### `--confirm-threads FILE`

`drawing check bracket.SLDPRT --json` lists the thread candidates: holes and hole
patterns whose diameter is a tap drill. The answers are one JSON object from
feature ids to a thread (its designation, `M6 x 1`, or its tapped form,
`M6 x 1-6H`), to `null` for a plain hole, or to an object with the blind hole's
thread depth:

```json
{"f-1": "M6 x 1", "f-4": {"thread": "1/4-20 UNC", "depth_mm": 12}, "f-7": null}
```

Each answer is checked against the part's candidates: an id that is not a
candidate, or a thread the diameter is not the tap drill of, is a usage error
naming `confirm-threads`; so is a file that is not strict JSON (a key twice, NaN),
larger than 64 KiB or holding more than 1,000 answers. A fresh drawing of the same
part with the same options always gives its features the same ids (13.4), so the
ids of `check` are those of `new`. The planner draws the confirmed thread in the
hole's callout (`M6 x 1-6H THRU`, or with its depth), and the answers are kept on
the features' decisions, where regeneration keeps them.

Until the pipeline takes decisions itself, `new` with `--confirm-threads` runs the
plan stage through `orchestrate.run(..., decisions=...)`; without it, `new` runs
`pipeline.run` exactly as `drawing.make_drawing` does.

### `export`

```text
solidseas drawing export D:\Drawings\1234-001.ssdrw --pdf --out D:\Shop
```

writes from the sheet the file holds, without the model. A PRELIMINARY export
replaces the drawing's own earlier export only when the drawing records it
unreleased with the hash the file still has and the file says SolidSeas wrote it;
anything else gets a numbered name. A RELEASED drawing exports its released
revision (`1234-001 A.pdf`), always as a new file. `export` never changes the
`.ssdrw`, so it does not record what it wrote (`new`, and the viewer's Save and
Release, record theirs). Writing into the drawing's own folder needs
`--allow-source-dir`. A drawing whose sheet this SolidSeas cannot read is
`drawing_invalid`.

### `update`

```text
solidseas drawing update D:\Drawings\1234-001.ssdrw --model D:\Jobs\bracket.SLDPRT
```

runs `drawing.regenerate`: the model is the one `--model` names, else the one
`locate.find_model` finds from the drawing (its relative path, then its stored
path on a local drive), which takes only a file whose SHA-256 is the drawing's. A
file found changed is never taken: the error `model_not_found` says so and asks for
`--model`. The merge report is the editor's ("4 unchanged, 2 changed, 0 new,
0 dropped, 0 needs attention", or "model file changed, geometry unchanged").

A RELEASED drawing is refused with `drawing_released` (exit 3) before its model
is looked for. The merged drawing is written over its own file only through `replaces`
with the hash of the file as `update` read it: a file changed since then, or
Settings with `replace_own_files` off, gives a new name beside it
(`1234-001 (2).ssdrw`). An unchanged model writes nothing; `--dry-run` writes
nothing and reports what would change. With `--model`, the drawing records the
model where it is now.

### `check`

```text
solidseas drawing check bracket.SLDPRT
solidseas drawing check D:\Drawings\1234-001.ssdrw --strict --model D:\Jobs\bracket.SLDPRT
```

On a part it makes the drawing in memory, writes nothing, and reports the
checks, coverage and thread candidates; a part that states no unit is drawn with
the guessed unit and a warning. On a `.ssdrw` it reports the checks the file can
answer and the candidates from the feature table; coverage is null, since the file
does not store it. `--strict` makes warnings fail too. `--model` (a drawing only)
verifies a model file: `verified` when its SHA-256 is the drawing's, the geometry
digest compared when it is not ("model file changed, geometry unchanged"), and
whether the drawing's MODEL reference (relative or stored path) names that file.
An error-level check, a warning under `--strict` or a model not verified exits 4
with the result printed (`ok: true`).

The checks come from `checks.run_checks`, reached through
`pipeline.resolve("checks", pipeline.ENTRY_POINTS["checks"])`: on a drawing alone
for a file, and for a live run the checks the pipeline already made, or every
check when the run keeps its `orchestrated` plan and layout. While this SolidSeas
has no checks module, the checks the drawing carries are reported.

### `show` and `settings`

`show` prints the drawing's summary: title fields, status, signatures (and whether
each still matches the content), revisions and recorded exports. For a RELEASED
drawing both `show` and `check` compare the released exports beside the drawing
with their recorded hashes and warn "release record does not match the files"
when they differ (17.2).

`settings` prints where Drawing Settings were read from, whether the file was
there, every value, each value that fell back to its default and why, and what
still waits for the user's answer (`first_use`).

## The kind `drawing_result`

`docs/API.md` 5.17 documents every member; the schema is in
`solidseas.model.KINDS["drawing_result"]` (`solidseas schema drawing_result`). An
action fills what it has and leaves the rest null or empty: `files` for `new`,
`export` and `update`; `merge` for `update`; `coverage` for a live run of a part;
`settings` for `settings`; `model_check` for `check --model`. The drawing summary
carries no path; `files` carry absolute paths, as `file_written` does. Its
`model.format` is `sldprt` or `sldasm`, and an assembly's `counts.items` and
`counts.balloons` count its parts list's lines and balloons. `check --model` of
an assembly reads it with its parts: an assembly file whose parts have changed is
not the drawing's model.

```json
{"ok": true, "kind": "drawing_result", "schema_version": 1, "solidseas": "0.2.120",
 "source": {"file": "D:\\Drawings\\1234-001.ssdrw"},
 "data": {"action": "update", "dry_run": false, "drawing": {"...": "..."},
          "files": [{"path": "D:\\Drawings\\1234-001.ssdrw", "name": "1234-001.ssdrw", "kind": "ssdrw",
                     "sha256": "...", "bytes": 35041, "replaced": true, "renamed": false,
                     "released": false}],
          "merge": {"words": "4 unchanged, 2 changed, 0 new, 0 dropped, 0 needs attention",
                    "unchanged": 4, "changed": 2, "new": 0, "dropped": 0, "needs_attention": 0,
                    "forgotten": 0, "model_unchanged": false, "geometry_unchanged": false,
                    "features": {"matched": 3, "resized": ["f-2"], "gone": [], "new": []},
                    "items": []},
          "checks": [], "check_counts": {"error": 0, "warning": 0, "information": 0},
          "coverage": {"complete": true, "words": "every recognised face is dimensioned", "...": "..."},
          "thread_candidates": [], "seconds": {"regenerate": 0.16, "checks": 0.0, "total": 0.17},
          "warnings": [], "settings": null, "model_check": null}}
```

The builders are `model.build_drawing_result` and its parts
(`drawing_summary_data`, `drawing_check_data`, `drawing_coverage_data`,
`drawing_thread_candidates`, `drawing_file_data`, `drawing_settings_data`).
`model.loads` is the strict JSON reader `--confirm-threads` goes through.

## The four error codes

| Code | Class | Base (what was raised before) | Exit | When |
|---|---|---|---|---|
| `drawing_invalid` | `DrawingInvalidError` | `InvalidArgumentError` | 1 | a `.ssdrw` refused whole (17.2): not a SolidSeas drawing, not strict JSON, a newer schema, ids or values outside their bounds; `document.DrawingFileError` derives from it and keeps `detail.rule` `drawing_invalid` with `detail.value` naming the check |
| `drawing_too_complex` | `DrawingTooComplexError` | `SldLimitError` | 1 | a bound of `DrawingLimits` passed (`DrawingLimits.exceeded`): too many faces, edges or bodies before tessellating, a stage over its seconds, a file over its size; `detail.limit` names the bound |
| `model_not_found` | `ModelNotFoundError` | `InvalidArgumentError` | 1 | `regenerate` found no model whose hash is the drawing's (`detail.rule` `model_not_found`) |
| `drawing_released` | `DrawingReleasedError` | `InvalidArgumentError` | 3 | a change asked of a RELEASED drawing (`release.require_editable`, `detail.rule` `drawing_released`) |

The classes are in `solidseas.errors` and exported from `solidseas`. Each derives
from the class the drawing code raised before the codes existed, so an existing
`except InvalidArgumentError` or `except SldLimitError` still catches it. The codes
come from the library and the command line only; the service has no drawing
route yet (stage 4), so they have no HTTP status.

## Tests

`tests/test_drawing_cli.py` runs every action on copies of the o02, o03, o07 and
o10 fixtures under fictional names, validates every envelope strictly against its
schema, and checks the files and their names, the refusals (a released drawing,
a model not found, a file the command did not write, `--units part` on a part
crafted to state no unit), the exit codes and the four codes. The checks come from
a stand-in put where `pipeline.resolve` finds `run_checks`. An audit hook records
every file the commands open for writing, rename, make or remove, and the test
fails if one is outside pytest's temporary folder.

`tests/test_drawing_corpus.py` is the corpus sweep of 20.3, opt-in: it runs only
when `SOLIDSEAS_DRAWING_CORPUS` names a folder. Each `.sldprt` below it (links and
placeholders never followed) is drawn by `drawing check PART --json` in a child
process of its own (`tests/drawing_corpus_child.py`), at below-normal priority, with
a timeout (`SOLIDSEAS_DRAWING_CORPUS_TIMEOUT`, default 300 s);
`SOLIDSEAS_DRAWING_CORPUS_SAMPLE` draws a fixed sample and
`SOLIDSEAS_DRAWING_CORPUS_WORKERS` sets the children at a time (default 2). The
title block is filled as a user would fill it, so check R6.title is about the
drawing: number, title and part number from the file name, a company in the
sweep's Drawing Settings, and drawn by, material and finish typed. It counts
complete, reduced-dimension, errors (with the failing check ids), refused (with the
code and its rule, limit or parameter) and failed, hard conflicts
(`R11.collisions`), dimensions and views per drawing, seconds per stage and the
recognised-area fraction per size band. The hard conflicts are also counted by the
pair of item kinds that collide (`dimension-note`, or `datum-no_clear_place` for an
item laid out where nothing was clear), by the kinds of view the items are in, as a
table of drawings by dimensions against conflicts, and as rows of numbers for the ten
drawings with the most. It prints numbers and fixed words only, never a path or a
part's name. `SOLIDSEAS_DRAWING_CORPUS_STRICT=1` also holds the
stage 1 targets 20.3 confirms after the first measurement: nothing failed, and no
hard conflict below 100 dimensions. The sweep runs on the PC, over the private
corpus.
