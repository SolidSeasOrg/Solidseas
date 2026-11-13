# A library's history (PDM)

SolidSeas can keep the history of a whole folder of CAD projects, the way a small
PDM does: every version of every CAD file, a note for the versions you check in, and
any version back when you need it. It works without SOLIDWORKS running, because
SolidSeas reads the files itself. It also checks that each project holds every file
it uses, and keeps a library of common parts that projects copy from. This part is
provisional: its commands and JSON may still change. The design is in
[PDM.md](../PDM.md).

There is no check-out and no locking. A check-in is a note on a version, not a gate.

## Make a folder a library

```bash
solidseas pdm init D:\CAD
```

This writes `D:\CAD\.solidseas\vault` and changes nothing else. Every command after
that finds the library from any file or folder inside it, so you can run them from a
project folder.

By default each top-level folder is a section (such as `Jobs` or `Customers`), and
each folder directly under a section is a project. The `Library` section holds common
parts. To change that, edit `D:\CAD\.solidseas\vault\vault.json`:

| Setting | What it does |
|---|---|
| `sections` | the sections and how deep a project sits in each, such as `[{"folder": "Customers", "depth": 2}]` for `Customers\Acme\Job 12`. Empty means every top-level folder, depth 1. |
| `library` | the section that holds common parts (default `Library`) |
| `archive` | sections whose projects are history, not current work |
| `tracked` | extra extensions to keep versions of, such as `[".ext"]` |
| `ignore` | name patterns never tracked, such as `["*backup*"]` |
| `who` | the name check-ins carry when you do not give one |

## What is tracked

CAD files in every format SolidSeas lists (SOLIDWORKS, STEP, IGES, Parasolid, STL,
3MF and the rest) and drawings' PDF and DXF exports. Pictures, archives and other
files are not. Hidden folders such as `.git` are passed over, and so are SOLIDWORKS'
`~$` lock files. A file or folder that is a link (a symbolic link or a junction) is
never followed, and `status` lists it as skipped.

## See what changed

```bash
solidseas pdm status                 # the library, from anywhere inside it
solidseas pdm status D:\CAD\Jobs\1042
```

`status` lists files that are **new** (no version yet), **changed** since their
newest version, or **gone**. A file whose size and modified time match its newest
version is not read at all, so a status of a large library is quick.

## Check in

```bash
solidseas pdm checkin D:\CAD\Jobs\1042 -m "holes moved for the new bracket" --revision B
```

This stores a version of each new or changed file under the path and writes one
check-in with your note. Files that have not changed are listed in the check-in with
the version they already have, so a revision label covers the whole project. A file
that is gone is recorded as removed, and `status` stops listing it. `--state` adds a
label such as `released`, and `--who` a name.

A part that sits in two projects with the same content is stored once.

## Scan on a schedule

```bash
solidseas pdm scan D:\CAD
```

`scan` stores a version of every new or changed file with no note. It writes nothing
when nothing changed, so it is safe to run every hour from Task Scheduler. A file
saved in SOLIDWORKS and never checked in still gets its earlier versions this way.

The first scan of a large library stores every file and can take a while. It prints a
line every few seconds saying how many files it has stored so far. If it is stopped
part way, or the computer goes off, run it again: it carries on with the files it had
not stored, and nothing it stored is lost or left half-written.

## A file's history

```bash
solidseas pdm log D:\CAD\Jobs\1042\bracket.SLDPRT
solidseas pdm show D:\CAD\Jobs\1042\bracket.SLDPRT v2
solidseas pdm diff D:\CAD\Jobs\1042\bracket.SLDPRT v2 v3
```

`log` lists the file's versions, newest first, with the notes, revisions and states
of the check-ins that name them. When the file on disk differs from its newest
version it is listed on top as the working copy. When the project folder is also a
Git repository, the commits that changed the file are listed too.

Name a version as `log` lists it: `v1` is the oldest, `latest` the newest, `working`
the file on disk, or the first few characters of its id. `show` gives one version's
properties, configurations and geometry, and `diff` what changed between two, as
`solidseas diff` does (see [a file's versions](command-line.md#a-files-versions)).
Add `--source git` to read Git's versions instead of the library's.

## Put a version back

```bash
solidseas pdm restore D:\CAD\Jobs\1042\bracket.SLDPRT v2
solidseas pdm restore D:\CAD\Jobs\1042\bracket.SLDPRT v2 --as "bracket v2.SLDPRT"
```

Before anything is written, the file as it is now is stored as a version, so a
restore never loses work. Without `--as`, the file is replaced by that version. With
`--as`, the version is written as a new file of that name in the same folder, and an
existing file of that name is never replaced. Either way the restored file is
checked in with a note that says which version it came from.

## Check that a project holds everything it uses

```bash
solidseas pdm check D:\CAD\Jobs\1042
solidseas pdm check                  # every project in the library
```

`check` reads every SOLIDWORKS document in the project and looks for each file it
references in the order the SOLIDWORKS help describes: in the document's own folder
first, then in each folder above it under the folders the reference was saved in,
then at the saved path. It keeps climbing past the project folder, because that is
how a part in a neighbouring project ends up in an assembly without anyone noticing.
The first file of that name the search reaches is the one SOLIDWORKS opens, so `check`
stops there too, even when the right file sits further on. Each reference that is not
found inside the project is listed:

| Result | What it means |
|---|---|
| outside | found only outside the project: in the library, in another project, or elsewhere |
| to confirm | found only by its name in a folder above the document, where SOLIDWORKS may not look; open the assembly in SOLIDWORKS to confirm |
| Toolbox | Toolbox hardware not in the project; fine when SOLIDWORKS loads Toolbox from its own folder |
| missing | not found where SOLIDWORKS looks; a file of that name elsewhere in the project or the library is named after it, as out of SOLIDWORKS' search |
| another document | the first file of that name the search reaches is a different document |
| ambiguous | several files could be it |

Toolbox parts found nowhere on the computer are not listed, but the summary says how
many there are: SOLIDWORKS needs them in its Toolbox to open the project.

Without a project, `check` goes through every project in the library and says which
are self-contained. Projects in the archive sections are left out.

```bash
solidseas pdm check D:\CAD\Jobs\1042 --plan
solidseas pdm check D:\CAD\Jobs\1042 --fix
```

`--plan` lists the copies that would make the project self-contained: each file found
outside, or only by a search to confirm, goes beside each document that uses it,
because the document's own folder is the only one where SOLIDWORKS looks for the
file by its name alone. A copied sub-assembly has parts of its own, and from its new
folder it may not find them where it did before, so the plan also looks at each copy
from where it will be and adds what it needs beside it, and again for those, until
nothing more is needed (at most 10 rounds). Each copy in the plan says which round
added it and which document needs it, and anything the plan cannot place (not
found, another document of that name in the way, or past the last round) is listed.
`--fix` makes the whole set of copies at once and checks the project again. A copy
is always a new file. When a file of that name is already
there, nothing is copied and `check` says why. A file copied from the library is
remembered as a copy of that library item, so `pdm library updates` can tell you
when the library part changes. Add `--copy-toolbox` when this installation does not
load Toolbox parts from their own folder and they should be copied too.

Missing files and other documents of the same name cannot be fixed by a copy. Open
the assembly in SOLIDWORKS to point it at the right file.

## The library of common parts

Parts used in many projects, such as hardware or standard brackets, can live once in
the library's `Library` section, each with an item number and a description. A
project never points into the library: using a part copies it into the project, and
the vault remembers which version went where.

```bash
solidseas pdm library candidates
```

`candidates` lists parts and assemblies whose identical content sits in two or more
projects, the most widely shared first. Toolbox parts and parts the library already
holds are left out. Only files that share a size with another file are read, so it
is quick on a large library.

```bash
solidseas pdm library add D:\CAD\Jobs\1042\bolt.SLDPRT -d "M6 x 20 bolt"
solidseas pdm library add D:\CAD\Library\Hardware\nut.SLDPRT --item NUT-M6
solidseas pdm library list
```

`add` copies the file into the `Library` folder and makes it a library item. The
file you named is not changed. A file of that name already in `Library` is never
replaced. A file that already sits in the library section is made an item where it
is. Items are numbered `SS-00001`, `SS-00002` and so on, unless you give a number
with `--item`. `list` shows every item with its current version and how many
projects have a copy.

```bash
solidseas pdm library use SS-00001 D:\CAD\Jobs\1050
solidseas pdm library use SS-00001 D:\CAD\Jobs\1050 --to parts\hardware
```

`use` copies the item's current version into the project's top folder, where
SOLIDWORKS finds it from any folder below, or into the folder `--to` names. When the
project already has a file of that name, nothing is copied. In SOLIDWORKS, insert
the part from the project's copy, not from the `Library` folder.

```bash
solidseas pdm library updates
solidseas pdm library update D:\CAD\Jobs\1050 SS-00001
```

`updates` lists the copies whose library item has changed since they were made, and
the copies that were edited in their project. `update` replaces the project's copy
with the item's current version. The copy is kept as a version first, so `pdm log`
and `pdm restore` can bring it back. A copy that was edited in the project is not
replaced unless you add `--force`.

```bash
solidseas pdm library edit SS-00001 -d "M6 x 20 bolt, zinc"
solidseas pdm library edit SS-00001 --number BOLT-M6-20
```

`edit` changes an item's description, its number, or both. The number it had stays
with it as an alias: `SS-00001` still finds the item, the copies made under it stay
linked to it, and no other item can take it. `list` shows each item's earlier
numbers. The change is kept as a new record beside the item's own, which is never
rewritten, like the rest of the vault.

## In the viewer

SolidSeas Desktop has a PDM menu while the opened folder lies in a library: Check
In (with the note, revision and state, after listing what changed), Changes,
Check Project, Library of Common Parts and Restore Version, which puts back the
version chosen on the History tab. The History tab lists a library file's
versions with their check-in notes. Outside a library the menu offers Make This
Folder a Library, which does what `pdm init` does.

Check Project's Make Copies does what `check --plan` and `check --fix` do: it
lists the copies, asks, makes them and shows the project checked again. The
Library of Common Parts window does what `pdm library` does: it lists the items
with a search box, and Use in Project, Show Copies, Update Copies, Edit and Add
to Library work on the chosen item. Its Candidates tab lists the parts that several
projects share. A file in the list that is not an item yet has Add to the
Library on its right-click menu. See [The PDM menu](viewer.md#the-pdm-menu).

## What SolidSeas writes

Only the library's own `.solidseas` folder, the file a restore puts back, and the
copies that `library add`, `library use`, `library update` and `check --fix` make.
Each file is written under a temporary name and then renamed, never through a link.
A copy never replaces a file, except that `library update` replaces a copy it made
itself, after keeping it as a version. SolidSeas never changes the paths stored
inside a SOLIDWORKS document. The vault is plain JSON and content files, so a backup
of the library folder is a backup of its history, and it moves with the library.

Every command takes `--json` and prints one `pdm_result` document, described in
[API.md](../API.md).

## Read the history from another program

The REST service and the MCP server can answer from a library too, read-only, when
you start them with `--pdm`:

```bash
solidseas serve --root jobs=D:\CAD\Jobs --pdm
solidseas mcp --root jobs=D:\CAD\Jobs --pdm
```

They then answer what `status`, `log` and `show` print, the recent check-ins and
`pdm check`'s findings for a project, for the library that holds each root (the root
itself, a folder above it or one inside it). Every path in an answer is relative to the
root, and the history of files outside the root is left out. The routes are off unless
you ask for them, because they send your check-in notes and the facts of earlier
versions, deleted files included, to whoever holds a token or uses the app. The routes
and their answers are in [API.md](../API.md) (8.6 and 5.21), and the MCP tools in
[MCP.md](../MCP.md).
