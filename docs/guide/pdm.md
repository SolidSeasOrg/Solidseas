# A library's history (PDM)

SolidSeas can keep the history of a whole folder of CAD projects, the way a small
PDM does: every version of every CAD file, a note for the versions you check in, and
any version back when you need it. It works without SOLIDWORKS running, because
SolidSeas reads the files itself. This part is provisional: its commands and JSON
may still change. The design is in [PDM.md](../PDM.md).

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

## In the viewer

SolidSeas Desktop has a PDM menu while the opened folder lies in a library: Check
In (with the note, revision and state, after listing what changed), Changes,
Check Project and Restore Version, which puts back the version chosen on the
History tab. The History tab lists a library file's versions with their check-in
notes. Outside a library the menu offers Make This Folder a Library, which does
what `pdm init` does. See [The PDM menu](viewer.md#the-pdm-menu).

## What SolidSeas writes

Only the library's own `.solidseas` folder, and the file a restore puts back. Each
file is written under a temporary name and then renamed, never through a link. The
vault is plain JSON and content files, so a backup of the library folder is a backup
of its history, and it moves with the library.

Every command takes `--json` and prints one `pdm_result` document, described in
[API.md](../API.md).
