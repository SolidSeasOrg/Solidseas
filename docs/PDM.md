# PDM: a history, a parts library and self-contained projects

SolidSeas manages a library folder of CAD projects the way a small PDM does. It keeps
every version of every CAD file, with a note for the versions you check in. It keeps a
library of common parts and copies them into projects rather than letting projects
point at them. It also checks that each project holds every file it references. All
of it works without SOLIDWORKS running, because SolidSeas reads the files itself.

This document is the design. The user guide (`docs/guide/pdm.md`) covers how to use
it.

Status: steps 1 to 5 of section 8 are built (provisional, `solidseas.pdm`,
`docs/API.md` 3.29): the vault, check-in, scan, status, log, show, diff and restore,
`pdm check` with `--plan` and `--fix`, and the library of common parts, on the
command line. Candidates are found from file sizes and the vault's newest versions,
not from the folder catalog. The viewer's part (step 4) is built too: the History
tab, the PDM menu, the Library of Common Parts window and Check Project's Make
Copies (`solidseas_app/viewer/pdmaction.py` and `pdmlibrary.py`). So is step 5:
`serve --pdm` and `mcp --pdm` answer status, logs, versions, check-ins and the
self-contained check, read-only (`docs/API.md` 8.6).

## 1. What it is for

- **History.** Every CAD file in the library has a history. You check files in with a
  note when a change matters, and a scan records any other saved change automatically,
  so a file saved in SOLIDWORKS and never checked in still has its earlier versions.
  Any version can be opened, compared with another, or restored.
- **Self-contained projects.** No project references a file outside its own folder. A
  part used by two unrelated projects is copied into each, and `pdm check` lists every
  reference that leaves its project, including one that SOLIDWORKS' search would find
  in a neighbouring project.
- **A library of common parts.** Parts used in many projects live once in the library
  section, with an item number and a description. Using one copies it into the
  project, and the vault remembers where the copy came from. When the library part
  changes, `pdm library updates` lists the projects whose copy is behind.

## 2. Decisions

| Decision | Choice | Why |
|---|---|---|
| Adopt a PDM product or build one | Build into SolidSeas | The open PLM products either reach SOLIDWORKS only through a client that needs it running (Odoo PLM, whose CAD connector is not open source), are not free for production (Aras), or are no longer maintained (DocDokuPLM, OpenPLM). Daily use here must work while the SOLIDWORKS seat is elsewhere. |
| Version engine | SolidSeas' snapshot store (`docs/VERSIONS.md` 4), one store for the whole library | It is content-addressed, so a part shared by 10 projects is stored once. Records are never rewritten, so it needs no lock and no server, and a backup is a plain copy of new files. It needs nothing installed on the PC. Git with LFS was the runner-up. It would need a newer Git, about twice the disk space, one repository per project, and changes to the project folders that are already Git repositories (whose history SolidSeas reads as it is, `docs/VERSIONS.md` 3). |
| What is tracked | CAD documents: SOLIDWORKS, STEP, IGES, Parasolid, STL, 3MF and the other formats SolidSeas lists, plus drawings' PDF and DXF exports | Pictures, archives and videos are most of the bytes and seldom change. The backup covers them. `vault.json` can add kinds. |
| Names that start with a dot | Tracked, except the folders tools keep for themselves (`pdm.settings.TOOL_FOLDERS`: `.solidseas`, `.git`, `.svn`, `.Trash` and the like) and `._` resource-fork files; `skip_hidden` in `vault.json` leaves out every dot name, and on Windows anything marked hidden | The real library had a project folder and 20 files whose names start with a dot (39 CAD files) that a rule against every dot name left out. A dot there is the user's naming, not a tool's. |
| Locking and check-out | None | There is one user. A check-in is a note on a version, not a gate. |
| Where data lives | `<library>\.solidseas\vault\` | It moves and backs up with the library, and paths in it are relative to the library. |

## 3. The vault

`solidseas pdm init FOLDER` makes FOLDER a library. Under it:

- `.solidseas/vault/vault.json`: the settings (format 1).
  - `sections`: the top-level folders that hold projects and how deep a project sits (default: every top-level folder is a section, and each folder directly under a section is a project).
  - `library`: the section that holds common parts (default `Library`).
  - `archive`: sections whose projects are history, not work (they are tracked but never checked for self-containment).
  - `tracked`: extra extensions to track.
  - `ignore`: glob patterns that are never tracked.
- `.solidseas/vault/store/`: the snapshot store, `objects/` and `files/`, as `docs/VERSIONS.md` 4.2 describes, keyed by the path relative to the library, and `marks/`, a note of the record folders each batch of versions changed (`docs/VERSIONS.md` 4.5).
- `.solidseas/vault/newest.json`: the newest version of every file, a cache that `status` reads instead of every file's records (`docs/VERSIONS.md` 4.5). It is made from the records and may be deleted at any time.
- `.solidseas/vault/checkins/<yyyy>/<time>-<id>.json`: one record per check-in. It holds the id, when, the note, an optional name for who (from the settings, empty by default), and for each file its relative path, SHA-256, size and snapshot id, with `new` when the check-in stored that version and `removed` when it recorded the file as gone. It may also carry a revision label and a state. A record names only the files it stored and the ones it records as removed, so a check-in of two changed files in a library of 20,000 stays under a kilobyte. With a revision or state it also names every unchanged file under its paths with the version it already has, so the label covers the whole set. Records written before this rule name every unchanged file in every check-in; they read the same. Records are never rewritten. A later record can supersede a label or state.

  A version's note is the note of the check-in that stored it: the earliest record that names that version with `new` true, or, when none does, the note the version was stored with. A later check-in that names the same version does not change its note. When it carries a revision or state, that is a label of the version, listed with its time and who, newest first. A later check-in with neither adds nothing to the version's history, so the old records that named every unchanged file in a whole-library check-in no longer give each file that check-in's note.
- `.solidseas/vault/library/items/<item id>.json`, `.../links/<time>-<id>.json` and `.../edits/<time>-<id>.json`: library items, the record of each copy made into a project, and the changes of an item's number or description (section 6). These are append-only like the rest.

Everything is plain JSON and content files. Nothing in the vault needs SQLite, so a
library may sit on a network share. The
folder catalog (`solidseas index`) is the fast index over it, and a vault can be read
with the catalog cleared.

## 4. Commands

| Command | What it does |
|---|---|
| `pdm init FOLDER` | Make FOLDER a library: writes `vault.json` and an empty store. Changes nothing else. |
| `pdm status [PATH]` | Tracked files that are new, changed since their newest version, or gone, for the library, a project or a folder. |
| `pdm checkin PATH... -m NOTE [--revision R] [--state S] [--list-unchanged]` | Store a version of each changed file under PATH and write one check-in record (section 3). Unchanged files are counted and not stored again; `--list-unchanged` lists them in the output. Nothing is written when nothing changed and no label is given. |
| `pdm scan [PATH]` | Store a version of every changed tracked file, as an automatic check-in with no note. Safe to run on a schedule. |
| `pdm log FILE` | The file's versions, newest first, each with the note of the check-in that stored it and its revision and state labels (section 3). Git history is included when the file sits in a Git repository. |
| `pdm show FILE VERSION` and `pdm diff FILE A B` | One version's facts, or what changed between two (`docs/VERSIONS.md` 5 and 6). |
| `pdm restore FILE VERSION [--as NAME]` | Put a version back. The current file is stored as a version first. Without `--as` it replaces the file. With `--as` it writes a new file. |
| `pdm check [PROJECT]` | References that leave the project, are missing, or are ambiguous (section 5). |
| `pdm library ...` | `candidates`, `add`, `list`, `use`, `updates`, `update`, `edit` (section 6). |

Every command takes `--json`, the same envelope as the rest of the command line.

## 5. Self-contained check

For each SOLIDWORKS document in a project, every reference is resolved in the
order the SOLIDWORKS help topic "Search Routine for Referenced Documents" gives
(`resolve_references(search="documented")`), taking each document as the one
opened:

1. the document's own folder: the bare name, then the stored folder's tails under
   it, shortest first (`p.SLDPRT`, `xx\p.SLDPRT`, `yy\xx\p.SLDPRT`);
2. each folder above it in turn, with tails of one or more components only: the
   bare name is not tried there;
3. the stored path.

There is no step for the old position relative to the document: a file there is
found only when the climb reaches the folder the two share. The climb continues
past the project folder to the drive root, because that is where a reference leaks
into a neighbouring project. Nothing of this has been tried in SOLIDWORKS itself
yet (bead SolidSeas-bx4q): the order is the help topic's worked example. A
reference that only the bare name in a folder above the document finds is reported
on its own, for the user to confirm in SOLIDWORKS.

The first file the search reaches decides. When it was made as another document (its
stored creation time differs), the reference is a different document and the search
does not go on past it, even when a later step would find the right file: that is the
file SOLIDWORKS would open. A file with no stored creation time to compare, such as an
import source, counts as found. SolidSeas' name index, which finds a file of that name
anywhere under the project or the library, is not part of this search: a file only it
finds leaves the reference missing (or Toolbox, for a Toolbox part), and is listed in
the finding's `candidates`.

A result is one of these:

- **ok**: found inside the project.
- **outside**: found only outside the project. The finding names the folder and whether it is the library, another project or elsewhere.
- **needs confirmation**: found only as the bare name in a folder above the document, a search SOLIDWORKS may not make. Confirm by opening the assembly in SOLIDWORKS. It counts as a problem, and the plan copies the file beside the document.
- **toolbox**: Toolbox hardware. This is reported, and it is ok when the installation loads Toolbox from its own folder. The ones found nowhere are counted on their own (`toolbox_not_found`), so a summary can say SOLIDWORKS needs them in its Toolbox.
- **inside the parent**: a virtual component, or one stored inside its assembly (an imported STEP assembly). An imported component whose stored name has no folder is looked for on disk first, by the same search, and is inside the parent only when no file of that name with its stored creation time is found.
- **missing**: not found where SOLIDWORKS looks. A file of that name that the search does not reach, elsewhere in the project or in the library, is listed in `candidates`.
- **different document**: the first file of that name the search reaches has another identity (stored creation time): it is another document.

A part's own external files (base part, mirrored part, in-context assembly, import
source) are checked like an assembly's components. `pdm check --plan` lists the
copies that would make a project self-contained without making them, and
`pdm check --fix` makes them: each copy goes beside each document that refers to the
file (once per folder), because the document's own folder is the only one where
SOLIDWORKS tries the bare name. Each copy is a new file in the project, never one
over an existing file, and is recorded as a library link when its source is a
library item.

The plan runs to closure (`plan_copies`, bead SolidSeas-lu3y.18). A copy that is a
document, such as a sub-assembly, has references of its own, and from its new folder
the search may not find them where it found them from the source's folder: on a real
library 6 of 20 copies were sub-assemblies whose parts were then found only by the
bare name one folder above. So each planned copy is read from its source and its
references are searched for as if it already sat at its destination, by the same
documented search, over the real files plus every copy planned so far (a planned
copy counts as a file at its destination with its source's identity). What it needs
is planned beside it in the next round. Rounds repeat until one adds nothing, at most
10 (`MAX_ROUNDS`). Each copy records its `round` (1 for the project's own documents)
and its `referenced_by`, which from round 2 on are planned copies at their
destinations; conflicts carry their round too. A reference of a planned copy that no
copy can place is listed in `unplaced` with a reason: `missing`,
`different_document` or `ambiguous` (the check's result from the copy's
destination), `unreadable` (the source could not be read) or `round_limit` (a copy
would be needed past the last round). `pdm check --fix` makes the whole set and
checks the project again.

The project's own documents are searched again too (bead SolidSeas-lu3y.22). A
document whose reference was missing, or found further away, may reach one of the new
copies first once they are made. So after each round, every project document that
refers to a file of the name of a copy planned in that round is searched again, by
the same search over the real files plus the planned copies, and only the references
whose result changes are acted on. One that now finds a copy only as the bare name in
a folder above gets a copy of its own beside the document in the next round, under
the same round limit. One that now reaches a copy made as another document is listed
in `unplaced` as `different_document`, with the project document as both its
`document` and its `source`.

## 6. The common-parts library

- `pdm library candidates` lists documents whose identical content sits in two or more projects, most widely shared first. Toolbox parts and parts already in the library are excluded.
- `pdm library add FILE [--item N] [--description D]` copies the file into the library section as a library item and stores its first version. The source file is not changed. Item numbers are given or made up in sequence (`SS-00001`).
- `pdm library use ITEM PROJECT [--to SUBFOLDER]` copies the item's current version into the project (the project's root folder by default, where SOLIDWORKS' search finds it from any folder below) and writes a link record. A file of that name that already exists in the project is never replaced. The command stops and says so instead.
- `pdm library updates` lists links whose library item has a newer version than the copy, and copies that were edited in the project since they were made.
- `pdm library update PROJECT ITEM` replaces the project's copy with the item's current version. It stores the current copy as a version first, and it refuses when the copy was edited in the project unless `--force` is given.
- `pdm library edit ITEM [--number N] [--description D]` changes an item's number or description by writing an edit record that names the item by the number its item record has; the item record itself is never rewritten. The edits apply oldest first. The numbers an item had stay its aliases: they still find it, so link records made under an old number keep their item, and no other item can be given one (an item may take back its own). An edit that would give an item a number another item has or had, or that names no item, is skipped when the records are read, like any record that does not hold up.

In SOLIDWORKS, insert a library part from the project's own copy, not from the
library folder. `pdm check` reports a reference into the library as **outside**.

## 7. What it writes

The PDM writes only where you ask it to:

- its own `.solidseas` folder in the library;
- the file a restore puts back;
- the copies `library add`, `library use`, `library update` and `check --fix` make.

Each write goes through a temporary name and a rename, never through a link, and
never over a file without storing that file as a version first. A copy never replaces
a file SolidSeas did not make for that purpose. It never edits the paths stored
inside a SOLIDWORKS document. Only SOLIDWORKS does that, when it saves.

## 8. Order of work

1. The vault, check-in, scan, status, log and restore on the command line.
2. The self-contained check, with a part's external files and imported components resolved correctly.
3. The library: candidates, add, use, updates.
4. In the viewer: a History tab, a PDM menu (Check In, Status, Check Project, Restore), and a Library panel.
5. Read-only REST routes and Connector tools for history and status.
6. Backup of the vault to a server (a later phase, chosen by the user).

## 9. Not decided

- Whether to re-save older documents in SOLIDWORKS 2024. A re-save rewrites the stored paths and converts the file for good.
- Where the library lives besides the PC.
