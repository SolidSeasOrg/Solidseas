# Building SolidSeas

This page is for people working on SolidSeas itself: setting up a checkout,
running the checks, building the Windows executable and installer, keeping the
build's lock file current, running the viewer's self-test, and copying this
guide to the GitHub wiki. Contributors and agents should read
[AGENTS.md](../../AGENTS.md) first, and [CONTRIBUTING.md](../../CONTRIBUTING.md)
says what helps a pull request.

## Setting up a checkout

Requires Python 3.11 or newer.

```bash
python -m venv .venv
.venv\Scripts\activate          # on Linux: source .venv/bin/activate
pip install -e ".[dev]"
scripts/install-git-hooks.sh    # once per clone, from Git Bash on Windows
python -m pytest -q
python -m ruff check .
```

[tests/README.md](../../tests/README.md) describes the opt-in tests, such as the
private corpus sweeps and the OCCT oracle that checks STEP files against Open
CASCADE. [OCCT.md](../OCCT.md) records how SolidSeas uses Open CASCADE: as a
test oracle, and in the OCCT backend extension, whose helper program reads and
writes IGES and BREP, never inside the library
or the viewer.

## Building the Windows executable

To build `dist\SolidSeasViewer.exe` (one file, about 25 MB, no console window),
from PowerShell:

```powershell
scripts\build-viewer.ps1 -Venv .venv
```

Make that environment from a Python installed from python.org (or by
`actions/setup-python`). A Python installed by uv carries a licence file without
the terms of libffi, which the executable bundles, and the build stops with "Not
built: it carries libffi-8.dll but ... has no terms for libffi".

The script installs the library's dependencies and the `build` extra
(PySide6-Essentials, PyInstaller and truststore) into that environment, then
runs `packaging\SolidSeasViewer.spec`. It installs them from
`requirements\build-windows.txt`, which pins every package the executable
bundles, their own dependencies included, to one version and lists the SHA-256
hash of each of its files. pip installs with `--require-hashes`, so a download
that does not match is refused and two builds from the same commit bundle the
same code. A development install (`pip install -e ".[dev]"`) does not use the
list.

By default the script builds one file, `dist\SolidSeasViewer.exe`, which unpacks
itself into a temporary folder each time it starts. With `-OneFolder` it builds
the one-folder form instead, `dist\SolidSeasViewer\`, with `SolidSeasViewer.exe`
beside an `_internal` folder that holds its libraries and licence texts as plain
files. That form starts faster, and its Qt and Qt for Python libraries can be
replaced in place, as `THIRD_PARTY_NOTICES.txt` section 2.2 explains.

## Updating the lock file

To move the build to newer releases, or after changing the dependencies or the
`build` extra in `pyproject.toml`, write the list again with
[uv](https://docs.astral.sh/uv/), from a Bash shell on Linux or Windows:

```bash
scripts/lock-build-deps.sh             # add what pyproject.toml now asks for, keep the rest
scripts/lock-build-deps.sh --upgrade-package pyside6-essentials   # one package to its newest release
scripts/lock-build-deps.sh --upgrade   # everything to its newest release
```

It resolves for 64-bit Windows and Python 3.12; every package in the list is a
wheel that also installs on Python 3.11 and later. Commit the new list with the
change that needed it, and build once on Windows before releasing.
`tests/test_build_lock.py` fails when the list is missing a dependency
`pyproject.toml` names, or a hash.

## Building the installer

Each release on GitHub carries `SolidSeas-Setup-<version>.exe`, an installer for
the one-folder build, with its SHA-256 in a `.sha256` file beside it.
[Installing SolidSeas](installing.md) says what it does on a user's PC.

To build the installer yourself, install
[Inno Setup 6](https://jrsoftware.org/isinfo.php) and run, from the repository
root:

```powershell
scripts\build-installer.ps1
```

It makes a build environment (`.venv-installer`, or the one you name with
`-Venv`) from `requirements\build-windows.txt` as above, builds the one-folder
viewer, and compiles `packaging\SolidSeas.iss` into
`dist\SolidSeas-Setup-<version>.exe` and its `.sha256` file. With
`-ExtensionsFolder dist\extensions` the installer also carries the extension
packages in that folder, which the viewer adds, switched off, the first time it
starts (see [EXTENSIONS.md](../EXTENSIONS.md)).

`.github/workflows/release.yml` runs the same script on GitHub's Windows runner
when a release is published. It first downloads the extension packages attached
to the release, checks each against the release's `SHA256SUMS.txt`, and builds
the viewer and the installer to accept exactly those packages. It then installs
the result, runs the self-test below on the installed viewer, uninstalls it, and
attaches the installer, the single-file viewer and `BUNDLED-FILES.txt` to the
release, with one `SHA256SUMS.txt` for the whole release in place of the list
attached with the packages: it names the installer under both its names, the
single-file viewer and the packages. It builds no extension packages: those are
built on a Windows PC and attached by hand, as the checklist below says. A
release with none attached gives a viewer that accepts none. The OCCT backend's
package is not offered yet.

## Making a release

1. Build the extension packages from the release's commit:
   `scripts\build-extensions.ps1 -Venv .venv` (with `-FfmpegFolder`, `-FfmpegSource` and,
   if you have it, `-SolidCraftZip`). It writes the zips and their
   `SHA256SUMS.txt` to `dist\extensions`.
2. Draft the release on GitHub for that commit's tag, and attach the zips and
   `dist\extensions\SHA256SUMS.txt`, which the workflow checks them against.
   Attach that file, which lists only the zips, rather than `dist\SHA256SUMS.txt`:
   the workflow builds its own viewer, so a viewer hash from your build would
   not match.
3. Publish the release. The release workflow checks the zips, builds the
   viewer and the installer to accept them, tests the installed viewer and
   attaches the installer, `SolidSeasViewer.exe` and `BUNDLED-FILES.txt`. It
   then replaces the `SHA256SUMS.txt` you attached with one list for the whole
   release: the installer under both its names, `SolidSeasViewer.exe` and the
   zips. Check that the release's `SHA256SUMS.txt` names the installer once the
   workflow has finished.
4. If you attach packages after publishing, replace the release's
   `SHA256SUMS.txt` with a `dist\extensions\SHA256SUMS.txt` that lists every
   zip the release carries (the workflow's list does not name the new ones).
   Then run the workflow again by hand for the tag (Actions > Release
   installer > Run workflow), so the viewer accepts them and the list covers
   them.
5. Attach to the same release, beside the program and the packages, the source
   archives that `licenses/SOURCE.txt` lists: the whole repository at the tag
   (`git archive --format=tar.gz --prefix=SolidSeas-<version>/ -o
   SolidSeas-<version>-source.tar.gz v<version>`, which a host that adds a
   source archive to each release, as GitHub does, makes for you; the sdist
   leaves out the build scripts and the spec, so it is not enough), the Qt and Qt for
   Python source archives, and, with the video package, `ffmpeg-<version>.tar.xz`
   and its `.asc` from `packaging\ffmpeg\out`. The LGPL asks for the source in
   the same place as the program, so every release carries them, wherever it is
   published. The release workflow attaches `SOURCE.txt` itself. When the bundled
   Qt or FFmpeg version changes, update `SOURCE.txt` and the notices to match.

## The viewer's self-test

```text
SolidSeasViewer.exe --self-test FOLDER --screenshot-dir DIR [--select NAME]
```

opens the folder, saves the Settings window's 3D Print page, the window with
each details tab showing and the preview zoomed in, and writes
`DIR\selftest.json`. From a checkout, `python -m solidseas_app` takes the same
options.

The self-test never reads or changes your settings: it runs with its own
`selftest-settings.ini` next to the report. Nor does it write to your cache
folder: the index it makes of `FOLDER` and the thumbnails it draws go to a
temporary folder of its own, removed when it ends, so an extension you added is
not used in the run either. Set `QT_QPA_PLATFORM=offscreen` to
run it without a screen (there is no OpenGL offscreen, so the 3D view then shows
its message). Its outputs pass the same write guards as the exports: `DIR` and a
`--report FILE` must lie outside `FOLDER`, and earlier screenshots, a report or
the settings file are replaced only with `--force`.

### The 3D view

| Option | What it does and checks |
|---|---|
| `--3d` | turns the 3D view on for the run and saves it too. Each document's 3D view is also turned 100 degrees over the top with a drag and saved, and the run fails unless free rotation went past straight above with the model still drawn, or the turntable stopped at straight above |
| `--configuration NAME` | after an assembly's `--select`, draws it in that configuration as well. It turns and zooms the view before choosing NAME, and `--configuration NAME,fitted` clicks a fitted corner view first; either way the run fails unless the camera stays, or is fitted from the same direction where the camera as it was would show none of NAME or be zoomed out to more than 50 times its size |
| `--explode PERCENT` | after an assembly's `--select` (or its `--configuration`), explodes it that far (at the level the Explode bar shows, or as `--explode PERCENT,top` or `--explode PERCENT,parts` says) and saves the view |
| `--pick NAME` | clicks the instance NAME (its component tree id, such as `o15_sub_asm-1/o07_boxB_h31-1`) where the view draws it, saves the view and the Components tab, turns the view and zooms in toward it, double-clicks it, saves the file it opens, goes Back and saves that, failing the run when it did not pick, open or come back as it should (the camera included); then it turns the camera back, so each pick starts from the same view. A part read from a sub-assembly's own file is picked with its row selected, the row the read gave it under the sub-assembly's; one past the rows the tab shows is picked with no row selected, and the report names the sub-assembly's row that stands for it |
| `--boxes` | checks, in every 3D view of an assembly and every explode, that each instance with no mesh but a stored box is drawn as that box where it belongs (a box too small to cover a pixel is counted, not failed), saves the view with the boxes picked and with them turned off, and fails the run when one is missing |
| `--open-component NAME` | after a `--select`, opens the file of that row of the document's Components tab, saves it (or the message saying why it cannot be opened), goes Back and saves that, and fails the run when Back did not return to the same row |
| `--rotation free` or `--rotation turntable` | sets how the 3D view turns for the run; free is the default |
| `--view-cube off`, `--pivot-at centre` | set those two settings for the run |

Each 3D view's record says where a fit may put the model, and the run fails when
the model is drawn under the legend.

### Appearance: transparency, hide, isolate, explode a sub-assembly

`--transparent NAME[,PERCENT]` (75 by default), `--hide NAME`, `--isolate NAME`
and `--explode-sub NAME,on|off`, after an assembly's `--select`, change how the
instance or sub-assembly NAME looks in its 3D view, or whether it explodes, in
the order given after the picks and with nothing picked. Each saves the window
and checks what is drawn by reading pixels back, failing the run when it does
not match. Edge pixels are blended by multisampling, so each check counts
shares:

- **Made transparent:** at least 90 percent of NAME's pixels must change, toward
  what is behind it where that differs (75 percent of those for a NAME of
  several instances, which is seen through several of its own layers where its
  parts overlap); at least 99 percent of the other pixels more than two pixels
  from NAME must stay exactly as they were; and a click must still pick it at 90
  percent of its pixels with nothing behind them.
- **Made 0 percent transparent:** 99 percent of all the pixels must be as they
  are with NAME opaque.
- **Hidden:** nothing of it may be picked.
- **Isolated:** nothing else may be picked.
- **Switched** (NAME must be a sub-assembly): the view is exploded (fully, if it
  was collapsed) and its parts must move as one or as their groups say, each
  drawn inside the box its offset moves it to.

After the last of them it saves the Components tab with its marks, and Reset
appearance must give back the picture from before the first, pixel for pixel.

### The view cube, the pivot and input

`--viewcube REGION` after a `--select` clicks that document's view cube (before
any `--select`, every document's) on REGION: a face (`front`), an edge
(`top-front`) or a corner (`front-top-right`), or `all` for the 26 in turn,
reaching the hidden half through what is drawn. It fails the run unless the view
ends looking from there, upright and fitted, on exactly the frame it draws when
set there at once, with nothing picked and no menu asked for, the legend's
column clear and the cube showing the region in its middle (a part whose mesh is
a box must also be drawn as large as its box from there). `home`, `set-home` and
`reset-home` (chosen from the cube's menu), the arrows `step-up`, `step-down`,
`step-left`, `step-right`, `roll-cw` and `roll-ccw`, and `drag` are checked the
same way.

`--pivot NAME` turns the model with a drag of the rotate button from where the
instance NAME is drawn (for a part, any NAME) and fails unless the point under
the pointer kept its pixel, or with `--pivot-at centre` unless it moved, which
shows the setting acts. `--pivot .` does it from empty space and fails unless
the model turned about the middle of the free area.

`--input-checks` checks, on every selected document, that a sideways scroll
turns the model as the arrow key does, that Ctrl and Shift pressed during a
SOLIDWORKS middle-drag switch it to panning and zooming, and that Page Up and
Page Down roll the view.

These run on the document's first 3D view, after the turn over the top, from
Home and back to it, with every click routed to the cube or the view as Qt
routes a real one.

### 3D Print and STEP export

`--print-dry-run` presses 3D Print twice for each selected part or assembly,
exporting as the button does but starting no program, and fails the run unless
each file is next to its model (or in the temporary folder with the reason
said), named after the document and today's date, with its full path in the
result, and the second numbered one higher than the first, `(2)` after the day's
first. It writes those files next to the models in `FOLDER`, so point it at a
copy. A model outside `FOLDER` (a component found elsewhere) gets its files in
the temporary folder instead, with that reason.

- `--print-row NAME` after an assembly's `--select` prints, twice and checked
  the same way, the file of that row of the Components or BOM tab through its
  context menu.
- `--print-view NAME` prints the part of the instance NAME through the 3D view's
  menu (`NAME,sub` the nearest sub-assembly it is in, and `--print-view .` the
  assembly itself, from empty space); with `--3d` and the view drawn, the view
  itself is right-clicked.
- `--print-format 3mf|stl|step` sends every print of the run in that format,
  chosen for the run's program as Settings > 3D Print Program chooses it. It
  fails the run when no 3D print program is found (the window would ask, so
  nothing is sent), the program does not take it, a file's extension is not its
  format's, a STEP fails the tests' own STEP checker (`tests/step_support.py`:
  its syntax, its topology, and its vertices and edges on their curves and
  surfaces), or a print asked for as STEP went as 3MF without saying why; an
  assembly must go as 3MF, for being one.
- `--export-step` exports each selected part with File > Export STEP, its save
  dialog answered with a folder the run makes in the system's temporary folder,
  checks the file with the same checker and removes the folder. A drawing must
  find the entry off, and an assembly, or a part of a 3D file the STEP export
  does not write (an STL or a STEP, say), off with its tooltip saying why. The
  packaged viewer carries the checker for this, so its STEP export is checked
  without driving its window from outside.

### The quick filter

`--quick-filter TYPES` (`sldprt,step`, repeatable, with or without `--select` but
not with `--select-all`) turns those types on in the list's
[quick filter](viewer.md#the-file-list-and-its-quick-filter) once the folder is
listed, checks that the list shows exactly their rows and that each tooltip
counts the rows of its type the list shows, saves the window in both views, and
turns them off again.

### Checking every format

```bash
python -m solidseas_app --self-test-formats --3d --screenshot-dir DIR
```

writes a synthetic file of every [3D format](formats.md) into a temporary folder
and checks that each lists, previews, shows its details, draws in 3D (its pixels
read back, an assembly picked, exploded and hidden, the view cube clicked and
Home pressed) and exports to STL and 3MF, and that 3D Print sends it as 3MF, STL
and STEP (a STEP from a Parasolid file's part, read back; 3MF with the reason for
any other), saving the window at each step and a report in `DIR`.

## Publishing this guide to the wiki

The pages in `docs/guide` are the source of the project's GitHub wiki.
`scripts/sync-wiki.sh` copies them into a checkout of the wiki and commits them
there.

Before the first sync, create the wiki's first page by hand in GitHub's web
interface: open the repository's Wiki tab (turn on Wikis under Settings >
General > Features if there is no tab), choose Create the first page and save
it as it is. GitHub makes the wiki's own repository only then, so until that
page exists there is nothing to clone or push to, and the sync stops at its
clone. The first sync replaces that page, `Home`, with the guide's own. Then:

```bash
scripts/sync-wiki.sh ../SolidSeas.wiki          # clone if needed, write, commit; no push
scripts/sync-wiki.sh ../SolidSeas.wiki --push   # the same, then push to the wiki
```

What it does:

- clones https://github.com/SolidSeas/SolidSeas.wiki.git into the
  folder you name when it does not exist yet, and refuses a checkout with
  uncommitted changes;
- writes each guide page under a wiki name made from its file name
  (`where-used-and-bom.md` becomes `Where-Used-and-BOM`, `3d-print.md` becomes
  `3D-Print`), with `index.md` as `Home`, and makes `_Sidebar.md` from the
  links in `index.md`;
- rewrites relative links for the wiki's flat page names: a link to another
  guide page goes to its wiki page, keeping its `#anchor`, and a link to any
  other file goes to it in the repository, as `blob/main/...` (`tree/main/...`
  for a folder); URLs, anchors on the same page and anything inside code stay as
  they are, and a link that leaves the repository stops the run;
- marks every page it writes with a comment naming its source, removes a marked
  page whose source is gone, and never touches a page made by hand on the wiki;
- commits only when something changed, as the repository's configured author,
  and pushes only with `--push` (pulling first, fast-forward only).

Running it again with an unchanged guide makes no commit. `scripts/wiki_sync.py`
does the work, with `--wiki-url`, `--repository` and `--branch` to point it
elsewhere, and `tests/test_wiki_sync.py` checks the link rewriting and that a
second run changes nothing.

Edit the pages here, not on the wiki: the next sync writes over a changed page.
