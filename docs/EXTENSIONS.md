# Extensions

Status: being built. The catalog, the on/off state, the two policy values, the package checks, the Extensions page (Tools > Extensions) and the helper runner are built (`solidseas_app.extensions`, `solidseas.helpers`, `solidseas.policy`), with Gridfinity behind its switch, the CAD Bridge taken from its package, Play and Save Animation with the video helper, and the OCCT backend: its helper, the `occt` backend of `solidseas.convert` that finds it, and its package's build step (section 9), whose first Windows build is still to be run; the Windows packages and the release packaging are still to come. The user asked on 2026-10-14 for "an extensions section that
will allow us to integrate new modules like the tracefinity or video export so we can
pick/choose without making a gigantic app". They chose how a package gets onto a PC (a file
they download, added from the Extensions page, with a link in the program to where the
packages are) and the first four extensions: Gridfinity, video export, the OCCT backend and
the CAD Bridge (then called the SOLIDWORKS engine). On 2026-10-14 they asked for SolidCraft as a fifth (section 9).

## 1. Why

Optional features keep arriving, and some bring large or licence-bound dependencies: ffmpeg
for video, Open CASCADE for IGES, the SOLIDWORKS interop assemblies for the bridge. Built into the viewer
they would grow the executable for everyone and switch on features that most people never
use. An extension lets each person pick what they install and what is on, while the core
stays small and keeps every rule in `AGENTS.md`.

## 2. What an extension is

An extension has an id (`gridfinity`, `video`, `occt`, `cad-bridge`), a manifest (section 3)
and up to two parts. No id or name is made of another company's trademark: the CAD Bridge was
`solidworks` (the SOLIDWORKS engine) until it was renamed, and that former id still names it
(`solidseas.policy.RENAMED_EXTENSIONS`). A switch saved in `Extensions.json`, an
`AllowedExtensions` list, an `accepted.json` and a package added under the former id all keep
working; the next save writes the new id, and adding the new package removes the old folder.

- **Its front, in the core.** The code that adds menu items, export formats, readers, chat
  tools or a settings page. Fronts are small, ship inside the core executable and are
  reviewed and tested with it, and stay inert until the extension is on: no menu item, no
  tool, no settings, nothing started or reached. Code is never added to the core at run
  time: a frozen executable cannot take new Python code safely, and nothing loaded into the
  app could be kept from its memory.
- **Its package, outside the core.** Whatever is large or licence-bound: a helper program
  with its own dependencies, which the core starts as a child process and talks to over a
  fixed protocol (section 6). A package lives in its own folder and is added and removed as a
  whole.

An extension with no package is **built in**: the core carries all of it, and switching it on
is all it takes. An extension with a package is **packaged**: it needs its package added
before it can be switched on.

| Extension | Front, in the core | Package | Needs | Reaches |
|---|---|---|---|---|
| Gridfinity | the seven `gridfinity_*` chat tools and their settings | none (built in) | Tracefinity, on this PC or a server | loopback, and ssh to the server when one is named |
| CAD Bridge | the assistant's live mode and Automatic mode, the chat tools for SOLIDWORKS parts | `SolidSeas.SwBridge.exe` | SOLIDWORKS 2024 or later | SOLIDWORKS on this PC only |
| Video export | Save Animation in the 3D view | an encoder helper with ffmpeg | nothing else | nothing |
| OCCT backend | IGES and BREP files read and written through `solidseas.convert`'s `occt` backend | `solidseas-occt.exe`, a helper with its own Python and OCP | nothing else | nothing |

Playing the explode and the collapse as an animation in the 3D view stays in the core: it
needs nothing extra.

## 3. The manifest

Each extension has an `extension.json`: the core carries those of all first-party
extensions, and a package carries its own, which must match the core's.

- `id`, `name`, `version`, `publisher` (`SolidSeas`), `description`.
- `core`: the core versions it works with.
- `adds`: what the front adds when on (menu items, export formats, readers, chat tools,
  settings), so the Extensions page can say it before anything is on.
- `needs`: what must be there and how the core checks it (a program it finds, a service that
  answers, SOLIDWORKS installed), each with what to tell the person when it is missing.
- `reaches`: the network (`none`, `loopback`, `ssh`) and the folders it reads or writes. This
  is a promise the review holds it to: nothing reaches more than its manifest says.
- `helper`: for a packaged extension, the program in the package, its protocol version, its
  memory and time limits, and the SHA-256 of every file in the package.
- `notices`: the licences of what the package carries (ffmpeg's, Open CASCADE's).

## 4. Getting, adding, removing and updating

The **Extensions** page (Tools > Extensions in the viewer, and a link from Settings) lists every
first-party extension the core knows, each with its status: built in, not added, added (with
its version), and whether what it needs is found ("SOLIDWORKS 2024 found", "Tracefinity is
not answering at http://127.0.0.1:3077"). Each has an on/off switch, Details (section 3's
lists and the notices) and, when added, Remove.

- **Get extensions** opens the project's releases page in the person's browser. The core
  itself reaches no network for it: Windows opens the address.
- **Add from file** takes the package the person downloaded (a zip). The core checks it before
  anything runs: the zip's SHA-256 must be one the core accepts for that extension (section 7);
  every entry must stay inside the extension's folder (no `..`, no absolute path, no link) and
  within size limits; the manifest must match the core's. Then it unpacks it into
  `%LOCALAPPDATA%\SolidSeas\extensions\<id>\`, writing a temporary folder first and renaming it
  into place, and asks whether to switch it on.
- **Packages that come with the viewer** are added when it starts: each zip in a
  `SolidSeas extensions` or `extensions` folder beside the executable that this core accepts
  and whose extension is not already added at that version (`extensions.add_beside`, on a
  thread of its own). They are checked as Add from file checks them and left off until
  switched on. A refused zip is skipped; nothing is added under `DisableExtensions` or
  outside `AllowedExtensions`. The installer, `SolidSeas-Setup-<version>.exe`, puts the
  packages it was built with (`scripts\build-installer.ps1 -ExtensionsFolder`) in the
  `SolidSeas extensions` folder beside the viewer, so they arrive this way; it replaces that
  folder's zips on each install that carries packages. The release installer carries none yet.
- **Remove** deletes that extension's own folder, after asking, and only that folder.
- **Update** is Add from file with a newer package: the new version is unpacked beside the old
  one, which is removed once the new helper has answered.

## 5. On and off

Which extensions are on is kept in `Extensions.json`, beside `Viewer.ini` and `AI.json`. Built
in and packaged extensions start off.

- **Off:** the front adds nothing and its helper never starts. A packaged extension whose
  package was removed is off.
- **On:** the front adds its items; a helper starts on first use, not with the app, and ends
  with the app.
- **The MCP server** reads the file at start and lists only the tools of extensions that are on
  (`gridfinity_*` for Gridfinity, `cad_sessions` and the part tools for the bridge). Switching one later
  takes effect when the MCP client next starts the server, or at once where the client takes
  the protocol's `tools/list_changed` notification.

## 6. Helpers

A helper is a program in the package. The core starts it with `solidseas.helpers.Helper`, the
runner the SOLIDWORKS bridge (`solidseas.swapi.bridge.Bridge`) is built on, through
`solidseas_app.extensions.start_helper`, which first checks that the extension is on and
that every file of its package still has the SHA-256 its manifest names. The drawing and
mesh children are Python worker processes of another kind and keep their own runner.

- Started suspended and placed in a Job Object (kill on close, a memory cap, die on an
  unhandled exception, so no error report or crash dump keeps a copy of a file) before it runs
  at all, so it runs no code outside the job and ends with the app however the app ends.
- JSON lines on standard input and output, the bridge's framing: a first line naming the
  helper, its version, its protocol and its operations; then requests and replies by id, with
  a time limit on every request and cancellation. Every reply is data.
- The core writes every file the person sees, by the rules it already keeps (never over a
  file, a temporary file renamed into place). A helper returns its result, or writes only into
  a temporary folder the core gives it, from which the core moves the file.
- A helper that crashes or stops answering ends that request with an error; the app goes on.

## 7. Trust and policy

- **First-party only.** The core accepts a package only when its SHA-256 is in the core's own
  list. A release builds the core and its packages together, and the release build writes the
  packages' hashes into the core, so each core accepts the packages of its own release. A
  package from another release, or altered, is refused with the reason. When the signed
  installer (bead SolidSeas-fg2) arrives, code signing adds a second check. Packages from
  anyone else are not part of this design.
- **Machine policy**, under `HKLM\SOFTWARE\Policies\SolidSeas` and read fail-closed like the
  existing values (`solidseas.policy`): `DisableExtensions` switches every extension off and the
  page says an administrator set it; `AllowedExtensions` (a list of ids, a former id counting as the one it became) allows only those. The
  existing `LocalProviderOnly`, `DisableAutomaticMode` and `DisableImages` keep their meaning
  inside each extension.
- **The review** treats a front like any other core code. A package is new code that runs on
  the PC: its helper, its manifest's `reaches` and its notices are reviewed when it is built,
  and the exchange's review hold list applies to them (`docs/TWO_MACHINES.md`).

## 8. Building and releasing

- `scripts/build-extensions.ps1` builds each package's folder and zips it with
  `python -m solidseas_app.extensions.package build` into `dist\extensions\<id>-<version>.zip`
  (the manifest, the helper and the notices), then writes `accepted.json`, the list of those
  packages' SHA-256s, beside the extensions module.
- Each package carries the licence texts of what it holds, as its notices and as files
  (`THIRD_PARTY_NOTICES.txt` section 3). The video package is refused for an ffmpeg
  configured with `--enable-gpl` or `--enable-nonfree`, and needs `-FfmpegSource`, where
  the exact source of that ffmpeg build is, which it carries with ffmpeg's configure flags.
  `packaging/ffmpeg/build.sh` makes that ffmpeg: run it in a `debian:trixie` container as its
  header says, then build with `-FfmpegFolder packaging\ffmpeg\out -FfmpegSource
  https://github.com/SolidSeas/SolidSeas/releases/tag/ffmpeg-9.0.2-source`, the release that
  holds its source tarball, signature and build script.
- The OCCT package is built only when `-Only` names it (`-Only occt`), until its first
  Windows build is checked, and needs `-OcctSource`, where the exact source of the Open
  CASCADE, OCP and the libraries the OCP wheel carries is, as the video package needs
  `-FfmpegSource`. It installs OCP from the `cadquery-ocp-novtk` wheel (OCP without VTK),
  pinned by its SHA-256 in `requirements/occt-helper.txt`, into a folder of its own, never
  into the build environment; refuses a wheel that carries a DLL
  `packaging/occt/libraries.tsv` does not name with its licence; builds
  `occt_helper.py` with PyInstaller as a one-folder program (a one-file one would unpack
  about 200 MB at every start); checks that the program starts and names Open CASCADE
  7.9.3; and carries the licences (`THIRD_PARTY_NOTICES.txt` section 3.4) with
  `occt-build.txt`, which says what the package holds and where its source is. A package
  built this way stays in `dist\extensions`, so a later build of the others lists it in
  `accepted.json` too.
- The core build (`scripts/build-viewer.ps1 -WithExtensions`) runs it first and carries
  `accepted.json` inside the viewer, so a viewer accepts the packages of its own release and no
  others. The bridge is no longer copied beside the viewer: it ships in the CAD Bridge
  package (`-WithBridge` still builds the old layout, which the viewer still finds).
- A release publishes the core executable, one zip per extension and `SHA256SUMS.txt`.
- From a source checkout the same split is the package extras, as `[cad]` and `[swapi]` are
  today, with the helpers run from the checkout.

## 9. The extensions

**Gridfinity** (built in). The `gridfinity_*` tools, the photos and bins folders and where
Tracefinity runs (this PC, or a server through the SSH tunnel) move from environment variables
to the Extensions page; the variables still override, so today's Claude settings keep working.
`docs/GRIDFINITY.md` stays its guide.

**CAD Bridge** (packaged, id `cad-bridge`). Its package is the bridge,
`SolidSeas.SwBridge.exe`, small but useful only where SOLIDWORKS is installed: it drives the
person's own licensed SOLIDWORKS through its published API. Off, the assistant shows no session
picker or Automatic mode and the MCP server no tools for SOLIDWORKS parts; the assistant still drafts code. On,
the Extensions page reports the SOLIDWORKS it finds.

**Video export** (packaged). The core plays the explode and the collapse. The extension adds
Save Animation: length, size, frame rate, a camera circling the model with optional pan and
zoom, when and how far to explode and collapse, and the background. The core renders the
frames off screen at a fixed size into a temporary folder of PNGs, and the helper
(`solidseas_app.extensions.video_helper`) encodes them into an animated GIF or an MP4 with the
ffmpeg in its package, into a second folder the core gives it; the core then saves the clip
where the person chose. For MP4 the helper takes Windows' own H.264 encoder or OpenH264 when
its ffmpeg has one, else MPEG-4 part 2, so the package needs no GPL encoder (bead
SolidSeas-kwl).

**OCCT backend** (packaged, id `occt`). Tier 1 of `docs/OCCT.md`: IGES and Open CASCADE's
BREP files read and written through `solidseas.convert`'s backend seam, run in the helper
under that document's section 3 rules unchanged, the package carrying its own Python, OCP
and Open CASCADE's notices (beads SolidSeas-3he, SolidSeas-7r8 and SolidSeas-e2z).

- **The helper** (`solidseas_app.extensions.occt_helper`, built as `solidseas-occt.exe`)
  imports the standard library and OCP only, and nothing in SolidSeas imports it. It takes
  `convert` requests: a staged copy of the file, its format (`iges`, `occt_brep` or `step`),
  the format to write (`step`, `iges` or `occt_brep`) and an empty folder to write into. It
  reads with the basic readers only, leaves out blanked IGES entities, sews an IGES file's
  loose faces at 0.01 mm and makes solids of the shells that close, keeps open shells and
  loose faces as they are, runs `BRepCheck_Analyzer`, and writes `model.step`,
  `model.igs` (BRep mode, a header that names no one) or `model.brep`, never over a file.
  Its reply reports what it read; an error carries a fixed message or a class name,
  never Open CASCADE's text. Its standard output points at the null device before OCP
  loads, it shows no error box and writes no dump, and elsewhere than Windows it caps its
  own memory (`--memory-mb`) and ends with its parent.
- **The backend** (`solidseas.convert.occt`) finds the helper: `SOLIDSEAS_OCCT_HELPER_PYTHON`
  in a source checkout (an interpreter where OCP imports, running the checkout's helper
  module with `-I`), else the package, through `start_helper`, only while the extension is
  on and allowed, and every file still has its SHA-256. It keeps one helper per process,
  started on first use, and a new one after a crash or a timeout. Each file goes as a copy
  in a new folder; the result is read only from the file the helper was told to write,
  bounded, and the folders are removed. Results are kept in memory by SHA-256, so a process
  that reads a file more than once (its details, then its preview) converts it once.
- **Where it runs.** The viewer reads model files in worker processes whose Job Object lets
  no worker start a process; while the OCCT package is added and switched on, its model
  pool lets each worker start one (`WorkerPool(helpers_per_worker=1)`): the helper, which
  runs in its own Job Object inside the pool's, under the pool's memory cap too. The pool
  decides this when it starts, so without the package its workers still start nothing.
  A change on the Extensions page reaches the running viewer at once
  (`MainWindow.extensions_changed`): the backend is asked again, and when a pool started
  now would decide otherwise the running one is ended (`ModelPool.restart`) and the next
  file read starts one that decides again; a read caught on the old workers runs once
  more on the new ones. The window then reads the opened folder again when the formats it
  can read have changed. The saved folder index is kept per set of readable extension
  formats (`savedindex.extension_formats`), so a folder read with the backend on is not
  shown from its index once it is off, nor the other way round. The 3D view's and the
  export's processes have no such limit. The other pools (the REST service's, the catalog's, `solidseas
  list`) are left as they were, so on Windows they read an IGES or BREP file's head but
  not its geometry.
- **The front** is the registry's `backend` field: `iges` and `occt_brep` are readable
  exactly while the backend is available, and open as `solidseas.formats.occt` documents,
  whose head is read in pure Python and whose geometry is the backend's STEP model read by
  SolidSeas' own STEP reader. Off, they are listed as `unsupported`, and the viewer, the
  command line and the error (`format_not_supported`, rule `needs_extension`) say what to
  add. The viewer lists them even while View > Show > Files SolidSeas Cannot Read hides
  the formats SolidSeas cannot read at all, since one switch opens them: greyed, their
  Status saying they need the OCCT backend, their Overview and the quick filter naming
  Tools > Extensions, and the status bar counting them. A helper that is on but would not
  start is said as that, not as an extension switched off. `solidseas convert` writes IGES, BREP and STEP through it.
- **Not built yet:** STEP cross-checks through the helper, an IGES reader of SolidSeas' own,
  and Convert in the viewer.

**SolidCraft** (packaged). SolidCraft is a free parametric CAD program (MIT or Apache-2.0,
github.com/bherbruck/solidcraft). Its package carries `solidcraft-cli.exe` from SolidCraft's
portable Windows zip, at a release pinned in `scripts/build-extensions.ps1` and checked by that
zip's SHA-256, with its licence texts: MIT, Apache-2.0 and the NOTICE as notices, and the 800 KB
list of third-party licences as a file of the package the notices point to. On, SolidSeas' chat
server lists SolidCraft's MCP tools as `solidcraft_*`
(`solidseas_app.extensions.solidcraft`): it starts `solidcraft-cli mcp` as the helper
(`solidseas.helpers.McpHelper`, an MCP server on the same runner, Job Object and memory cap as
any helper) the first time the tools are listed, and passes each call on, screenshots
included. So the assistant can model, measure and export new parts without SOLIDWORKS.
SolidCraft's files stay in one folder of SolidSeas' own (`SolidCraft` in SolidSeas' data
folder): SolidCraft is started with that folder alone and refuses the rest, and SolidSeas
refuses first any call that names a path outside it, so SolidCraft never reads or writes beside
a SOLIDWORKS file. `crash_reports` is not listed, as it can show paths from anywhere on the PC.
Later: Open in SolidCraft, the shown model exported as STEP into that folder and opened in
SolidCraft's own program to edit a copy (its package would then carry `solidcraft.exe` too).

## 10. Order of work

Proposed beads, under one epic:

1. The framework: the manifest and its checks, the core's list of accepted packages, the
   Extensions page (status, switches, Details, Add from file, Remove, the link), the state file,
   the two policy values, the MCP server listing tools by extension, and one helper runner
   that the bridge, the drawing children and the packages share.
2. Gridfinity behind its switch: the built-in kind, with its settings on the page.
3. The CAD Bridge as a package: the packaged kind with a helper that already exists.
4. Video export, with Play in the core (bead SolidSeas-kwl rewritten).
5. The OCCT backend.
6. Releases with the packages and their checksums; the installer's checkboxes later (bead
   SolidSeas-fg2).
7. SolidCraft: its tools in the chat, then Open in SolidCraft.

## 11. Open questions

- Whether an extension that is not added shows anything outside the Extensions page (this
  design: no).
- The video encoder's licence: an LGPL ffmpeg with OpenH264 or Windows' own H.264 encoder,
  against the GPL x264, decided when the package is built.
- Whether a package may update between core releases (this design: no, a core accepts the
  packages of its own release).
- Whether SolidCraft, which reads and writes IGES and STEP under MIT or Apache-2.0, should
  be the IGES backend instead of OCCT (LGPL), now that it is a package anyway.
