# Versions

Status: being built. The library and the command line are built (provisional,
`solidseas.versions`, `docs/API.md` 3.26): a file's history from Git inside a
repository and from SolidSeas' own snapshots elsewhere, snapshots taken when asked,
and what changed between any two versions in the document, its properties, its
configurations and its geometry (`solidseas history`, `snapshot` and `diff`). The
viewer's timeline with previews, the Git LFS guidance and the rest of section 9 are
still to come. This is Phase 4 of `docs/ROADMAP.md`, and the decision of 2026-09-30 in
`docs/ARCHITECTURE.md`: Git's history inside Git repositories, SolidSeas' snapshots
everywhere else.

## 1. What it is for

A part changes many times before it is made. People want to know what it looked like
last week, what changed between the version a supplier quoted and the one on the
desk, and whether a re-save changed anything at all. SOLIDWORKS writes different
bytes at every save, so comparing files byte for byte says nothing useful: two saves
of an unchanged model differ (fixtures o02 and o03, `tests/fixtures/README.md`).
SolidSeas compares versions by what they hold.

## 2. Where a history comes from

| The file is | History comes from | Taken by |
|---|---|---|
| inside a Git repository's work tree, and Git has a version of it | Git: the commits that changed it | committing, as usual |
| anywhere else, or never committed | SolidSeas' snapshots | `solidseas snapshot`, or the library's `snapshot()` |

`source` chooses (`auto`, the default, picks as the table does; `git` and `snapshots`
force one). A file inside a repository can still have snapshots: `--source snapshots`
lists them. Either way the history lists the versions newest first, numbered from the
oldest (`v1`), and puts the working copy on top when it differs from the newest one.

## 3. Reading Git

### 3.1 SolidSeas reads the repository itself

SolidSeas never runs `git`. It reads the repository's own files, read-only, in pure
Python (`solidseas.versions.gitrepo`). Running `git` was the smaller program and the
weaker choice:

- A repository's configuration names programs that `git` runs for ordinary commands:
  `core.fsmonitor` for anything that looks at the work tree, `gpg.program` when
  `log.showSignature` is on, filter drivers, text conversions, pagers and credential
  helpers. A project folder copied from someone else, unzipped from an e-mail or
  checked out on a shared drive carries its configuration with it. A file manager
  that runs `git` in every folder it opens would run those programs.
  `tests/test_versions_git.py` names one in every such key, shows that `git status`
  runs it, and that SolidSeas' history, reading and comparison run none.
- Many SOLIDWORKS users have no `git` on their PATH: GitHub Desktop and other clients
  bring their own copy and keep it to themselves.
- `git` refuses a repository another account owns, which is common on removable and
  shared drives, and reaching for one partial clone's missing objects would fetch them
  over the network.

The reader runs no program and never reaches the network. What it does not read it
refuses by name (3.6).

### 3.2 What is read

- **The repository**, found from the file's folder upwards as Git finds it, without
  leaving the file system the file is on: a `.git` folder, or a `.git` file naming the
  folder of a linked worktree, a submodule or a separate git folder (`commondir` then
  names the shared one).
- **References**: `HEAD`, loose references and `packed-refs`. A reference is looked up
  as a file only when its name is one Git could have made; a `HEAD` that names a path
  outside the references (`ref: refs/../../config`) is a damaged repository.
- **Objects**, loose and in packs (pack index version 2, deltas by offset and by id),
  in the SHA-1 and the SHA-256 object formats, and in the object folders `alternates`
  names. Every object is checked as it is decoded: a delta that copies from beyond its
  base, an inflated size that differs from the one stored, a chain of deltas longer
  than 10,000.
- **`shallow`**, where a shallow clone's history stops.
- **Git LFS pointers** and the LFS objects already on this machine (3.5).

Every file is opened read-only below the folder that holds it, with no link below that
folder followed and no cloud placeholder recalled
(`solidseas.formats.solidworks._io.open_readonly`). A `.git` that is a link, or a link
inside the git folder, is refused, and the pack folder is checked before it is listed.
A `.git` file, `commondir`, `alternates` or `lfs.storage` that sends the reading to a
network location on another drive or share than the work tree's is refused before
anything there is touched: on Windows, opening a path on a server hands that server
this account's credentials.

### 3.3 Which commits are versions

The versions of a file are the commits reachable from `HEAD` that changed it, as
`git log -- <path>` lists them with its default history simplification: commits are
walked newest first by commit time, a commit whose file is the same as one of its
parents' is passed over and only that parent is followed, and a merge that changed the
file from every parent is listed with both sides followed. A commit that deleted the
file is listed as `deleted` and has no content. A change of mode alone is no new
version. A rename is not followed, as `git log` does not follow one without
`--follow`. The walk stops after 20,000 commits (`--max-commits`) and says so.

Checked against `git log` on repositories `git` 2.43 made: loose and packed objects,
aggressive repacks, merges that keep one side and merges that make a third version,
deleted and re-added files, renames, detached heads, `packed-refs`, branch names with a
slash, linked worktrees, separate git folders, the SHA-256 object format, shallow and
blobless clones. On a repository of 5,000 commits that each changed one of 200 files
beside the part (the part itself changed in 200 of them), made with `git fast-import`,
the history took 1.3 s on the development VM and matched `git log`. Every object a
delta chain passes through is kept decoded (32 MiB in all, objects of 4 MiB or less),
so the next object of the chain starts from the nearest one already decoded.

### 3.4 The working copy

The working copy is hashed once, read-only: its SHA-256, and its Git blob id in the
repository's object format. It is `unchanged` when the blob id is that of the newest
version (or, for an LFS file, its SHA-256 is the pointer's), `changed` otherwise, `new`
when Git has no version of it and `missing` when the file is gone. A changed or new
working copy is listed on top as `working`. A file that keeps changing while it is read
is `busy` (rule `file_changing`) after three tries.

### 3.5 Git LFS

A version whose blob is a Git LFS pointer is read from the LFS object folder
(`.git/lfs/objects`, or where `lfs.storage` says), checked against the pointer's
SHA-256 and size, and never fetched. A version whose object is not on this machine is
listed with `available` false and the warning `lfs_not_fetched`; reading it is
`version_unavailable` (rule `lfs_object_missing`), whose message says to run
`git lfs fetch`. A work tree without git-lfs holds the pointers themselves; the
working copy is then `unchanged` when its pointer is the newest version's.

### 3.6 What is refused, and what is missing

| Case | Answer |
|---|---|
| references in the reftable format (`extensions.refStorage`) | `format_not_supported`, rule `reftable` |
| repository format 1 with an extension SolidSeas does not know | `format_not_supported`, rule `repository_extension` (format 0 ignores extensions, as Git does) |
| a pack index of version 1 | `format_not_supported`, rule `pack_index_version` |
| an object that does not decode, a reference that is not one | `damaged_file`, rule `git_object` |
| a shallow clone | the history stops where its commits end: warning `history_incomplete` |
| a partial clone's missing objects | the versions are listed with `available` false; reading one is `version_unavailable`, rule `object_missing` |
| `--source git` for a file outside a repository | `invalid_argument` |

## 4. Snapshots

### 4.1 Where they are kept

| Location | Folder | When |
|---|---|---|
| `data` | `%LOCALAPPDATA%\SolidSeas\history` on Windows, `$XDG_DATA_HOME/solidseas/history` (`~/.local/share/solidseas/history`) elsewhere; `SOLIDSEAS_DATA_DIR` replaces the base | by default |
| `project` | `<project>\.solidseas\history` | only when the project is named (`--project DIR`, `project=`), and the file must lie inside it |
| `folder` | the folder named | only when named (`--store DIR`, `store=`) |

The default is the user's data folder, not the cache folder the catalogs use: a
catalog can be made again from the files, a snapshot cannot. Nothing is written beside
a source document unless its project was named, as `AGENTS.md` requires. A project's
store keeps paths below the project, so it keeps working when the project folder
moves, and it may sit on a network share with the project: unlike the catalog's
SQLite, it needs no lock that a share could break (4.2).

### 4.2 What a store holds

- `objects/<2 hex>/<64 hex>`: each distinct content once, named by its SHA-256.
- `files/<32 hex>/<time>-<id>.json`: one small record per snapshot, in the folder of the
  file's key, the SHA-256 of its path (folded as Windows compares names on Windows and
  macOS). A record holds the snapshot's id (12 hex digits), when it was taken (UTC), the
  content's SHA-256 and size, the path, the file's modification time, a note and the
  SolidSeas version that took it.

No file is ever rewritten. Two programs, or two people sharing a project's store, never
lose each other's snapshots, and no lock is needed.

### 4.3 Taking one

The file is opened read-only within its own folder (a file that is a link, a cloud
placeholder or not a regular file is refused) and copied to a temporary name in
`objects`, hashing as it goes. A file that changed while it was copied is not kept
(`busy`, rule `file_changing`). When its content is that of its newest snapshot, no
record is written (`new` false), and that snapshot's stored copy is put back if it is
damaged or gone. Otherwise the copy is renamed to its object name, an object already
there is kept only when its content hashes to its name, and the record is created. Every folder from the
store down is checked with `lstat` before it is used and made owner-only on Linux and
macOS; records and objects are created with `O_EXCL`, so never over an existing name and
never through a link planted under one.

Many files at once (a PDM check-in or scan) are taken in batches of 1,000, copied four
at a time, and flushed to disk once per batch rather than once per file. The order in a
batch is what keeps a crash harmless:

1. Each file is copied to its temporary name, unflushed.
2. Every copy that becomes an object is flushed (`fsync`, `FlushFileBuffers` on
   Windows), then renamed to its object name, then each object folder is flushed. A
   crash before this leaves only temporary copies, never a half-written object under its
   final name.
3. The records are created in the order the files were named, then flushed with their
   folders. A crash before this leaves at most records cut short, which do not parse and
   are passed over (4.4), and objects no record names yet.
4. Only then does the PDM write its check-in record, flushed with its folder.

So no record ever names an object that is not on disk, and a check-in never names a
record that is not. Running the check-in or scan again stores what the interrupted one
did not. The flushes of a batch run on 32 threads, which lets the disk commit flushes
that wait together in one go. On the development machine, a first scan of 30,000 new
files (3.8 GB) took 22.6 minutes with a flush per file and 4.0 minutes with batches,
about 41 to 49 ms a file against 5 to 7. A snapshot of one file (`versions snapshot`, a
restore) flushes the same way, as a batch of one.

### 4.4 Reading them back

Records are data from a folder others may write to: each is checked field by field and
passed over when it does not hold up or names another file. Every object is hashed
again before it is used; one that does not match is `damaged_file` (rule
`snapshot_object`), and one that is gone is `version_unavailable` (rule
`snapshot_missing`). Taking the snapshot again puts a missing copy back.

## 5. What a version tells

A version is read whole into memory (at most 512 MiB by default) and opened from its
bytes as any document is (`solidseas.formats.open_any`).

### 5.1 The document, properties and configurations

From the summary every surface builds (`document_summary`, `model_summary` for other
formats): the document's type and format, the SOLIDWORKS release that saved it, its
units, the summary fields (title, subject, author, keywords, comments, not who saved it
last), the active configuration, each configuration's comment and material, the stored
preview, and every file and configuration property with its type, value, text,
expression and link.

### 5.2 Geometry: counts and a fingerprint

For each configuration of a part (once for a model file that holds bodies): how many
bodies of each type (solid, sheet, wire, general) and how many are hidden, how many
faces, edges and vertices, and a fingerprint of the B-rep.

The fingerprint is the SHA-256 of the bodies' topology and geometry in a canonical form:
nodes keyed by type and node id as `compare_brep` matches them, every field but
attributes, the links of lists, numbering and index maps, nodes with no id of their own
(B-spline data) written in place, and the bodies' digests sorted. Measured on the
fixtures:

- o02, o03 (the same document saved again) and o17 (the same recipe under another
  name) have one fingerprint, although their stored partitions and even their bodies'
  bytes differ; o07 (a box 31 mm tall instead of 30) has another.
- A part and SOLIDWORKS' own Parasolid export of it have one fingerprint (o02 and
  `o02_boxA.x_b`, o07 and `o07_boxB_h31.x_b`).
- Renumbering every node and listing them in another order leaves it as it is.

A mesh file's fingerprint is that of its triangles and their placements.

### 5.3 Measures

When two fingerprints differ, both versions are measured: volume, area and box of the
shown solid bodies, from their tessellation (`solidseas.tessellate`) at its default
tolerance (a thousandth of the box's diagonal, from 1 um to 1 mm), as
`Tessellation.measures()` gives them; a model file's from its scene. The time for both
versions together is 60 s by default (`--timeout`). A version not measured whole in time
is not compared on its measures (warning `measures_incomplete`); its counts still are.
Measuring only where the fingerprints differ keeps a comparison of property changes
cheap: on the fixture parts a comparison takes well under a second.

## 6. Comparing two versions

`compare` (the `diff` command) opens both versions and reports:

- `document.changes`: each field that differs, with the configuration it belongs to.
- `properties`: added, removed and changed, each with both sides' property objects.
- `configurations`: added and removed, and the active one on each side.
- `geometry`: per configuration, `unchanged` (equal fingerprints), `changed` (with the
  counts and measures that differ: body counts, faces, edges, vertices, volume, area,
  the box's size and its lowest corner), `added`, `removed`, `not_stored` (neither
  version stores its bodies, as with o06's second configuration) or `not_compared` (one
  does not). Assemblies and drawings are not compared on geometry yet (`reason`).

On the fixture kit's differential pairs it reports exactly the change each pair
isolates (`tests/test_versions_diff.py`): nothing for o02 against o03, three file
properties for o04, the material (and the preview its colour changes) for o05, the
second configuration and its property for o06, and for o07 the volume (6,000 to
6,200 mm3), the area (2,200 to 2,260 mm2) and the height (30 to 31 mm) with no other
change.

## 7. Naming versions

| Name | Version |
|---|---|
| `working` | the file as it is now (the newest version when it is unchanged) |
| `latest` | the newest stored version: a commit or a snapshot |
| `vN` | number N in the history, `v1` the oldest |
| an id | a commit id or a snapshot id, or at least four of its leading hex digits that no other version of the file starts with |

Without names, `diff` compares the newest version with the one before it: the working
copy with the newest stored version when it differs, else the newest two stored
versions. With one name, that version is compared with the newest.

## 8. Safety

- Every source file and every repository file is opened read-only; nothing is written
  into a repository, and nothing beside a source document unless its project was named
  for the snapshots.
- Nothing is written through a link: every folder of a store is checked before use,
  and records and objects are created with `O_EXCL`.
- No program runs: not `git`, not anything a repository's configuration names.
- Nothing reaches the network: a missing LFS object or a partial clone's missing object
  is reported, never fetched.
- Tests keep every snapshot in a temporary data folder and fail the run if the user's
  store gained a file (`tests/conftest.py`).

## 9. Order of work

1. The library and the command line (this slice): history, snapshots, comparison.
2. The viewer's History tab: the timeline with each version's preview
   (`versions.open_version(...).preview()`), the differences between a version and the
   one before, Take Snapshot, and Compare with Working Copy.
3. Git LFS guidance: a page of the user guide on keeping CAD files in Git with LFS, and a
   note in the history when a repository keeps large CAD files as plain Git objects.
4. Snapshots taken automatically, by choice: at each catalog scan for files that
   changed, with a retention rule.
5. Assemblies compared on their components and quantities per configuration.
6. Features compared through the drawing feature matcher (`solidseas.drawing.match`): a
   hole added, a slot that changed size.
7. Each version's facts kept by content hash, so the timeline loads without reading
   every version again.
8. REST routes, after a security review of what they expose.

## 10. Open questions

- Should SolidSeas take snapshots on its own (at each scan, or when the viewer notices a
  save), and how many should it keep? Both cost disk space the person did not ask for.
- Should a file that moves keep its snapshots? The catalog knows moves by file id; the
  store keys snapshots by path.
- Should a file inside a repository show its commits and its snapshots in one timeline?
