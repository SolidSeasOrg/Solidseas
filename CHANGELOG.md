# Changelog

All notable changes to SolidSeas are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are pre-1.0
while the project takes shape.

## [Unreleased]

### Added

- **One checksum list for each release.** Every release now has a SHA256SUMS.txt
  that lists the installer under both its names, SolidSeasViewer.exe and the
  extension packages, so you can check any download against one file.

- **Read your CAD files from any MCP app.** `solidseas mcp --root ID=DIR` lets
  Claude Desktop, Claude Code and other apps that add Model Context Protocol
  servers read the SOLIDWORKS files in folders you choose, on Linux or Windows,
  without SOLIDWORKS and without changing a file: folder listings, summaries,
  custom properties, configurations, components, references, bills of materials,
  path reports and stored previews, and with `--catalog` search, where-used,
  duplicates, missing references and recent changes. Each answer is the same
  JSON the REST service gives, nothing outside the folders is read, and under
  the LocalProviderOnly machine policy every tool refuses. docs/MCP.md says how
  to set it up and what reaches the app's model.

- **The REST service describes itself in OpenAPI.** `GET /v1/openapi.json`, the
  new `solidseas openapi` command and `docs/openapi.json` give an OpenAPI 3.0.3
  description of every route, parameter, status code and error code, so an HTTP
  tool or code generator can connect without reading the prose docs
  (provisional, docs/API.md 8.19).

- **Drawings to ISO.** Drawing Settings > Standard and Units chooses ASME or
  ISO, and the projection angle. An ISO drawing places its views in first angle,
  shows the first-angle symbol and states TOLERANCING ISO 8015. Its sheets,
  title block and lettering still follow the ASME layout for now.

- **The isometric on a sheet of its own.** Drawing > Isometric on Its Own Sheet
  puts the isometric view, with an assembly's balloons, on a second sheet, and
  back again; `solidseas drawing new --isometric-sheet` does the same. When an
  isometric has no room on the sheet, the checklist now says so and offers the
  move.

- **Fillets in parts made without SOLIDWORKS.** The .sldprt export now writes a
  fillet of constant radius on all four edges of a box along its depth, and a
  fillet on the edge of a hole cut through the box, on its far face. Other
  fillets are still refused, each with a reason that says what is supported.
  Parts with a fillet have not been opened in SOLIDWORKS yet, and the command
  says so when it writes one.

- **Every sheet in the New Drawing preview.** The New Drawing preview pages
  through every sheet of a drawing with Previous Sheet and Next Sheet (Ctrl+Page
  Up and Ctrl+Page Down), in the preview and in View Larger's window.

- **A verifying catalog scan.** `solidseas index --verify` (and
  `Catalog.scan(verify=True)`) hashes files that look unchanged again and reads
  again any whose contents changed, which catches a file rewritten with its
  modification time put back.

- **Duplicates, missing references and changes over REST.** `solidseas serve
  --catalog` now answers /v1/duplicates, /v1/missing and /v1/changes, a page at
  a time.

- **Parts from a sub-assembly's own file on the Components tab.** When an
  assembly does not list a sub-assembly's components, the Components tab now
  lists the parts the 3D view read from the sub-assembly's own file, under its
  row: you can pick them, go to their files, print them and change their looks
  like any other row. If a part's file is not in the folder, the message offers
  to open the sub-assembly.

- **STEP from STEP, ACIS and Alibre parts.** `solidseas export --format step`
  writes STEP from parts read from STEP, ACIS SAB and Alibre Design files.
  Assemblies, bodies placed away from the part's origin, and bodies or items the
  reader could not read in full are refused with a reason (the last can be left
  out with `--allow-partial`).

- **Looks kept between runs.** What you hide or make transparent in an
  assembly's 3D view, and which sub-assemblies explode, are kept for each
  document: show another document and come back, or close the viewer and open it
  again, and the assembly looks as you left it until Reset appearance. They are
  kept in ViewerLooks.json beside Viewer.ini, for the 200 documents changed
  last, under a digest of each path.

- **Keep the viewer's reads inside the opened folder.** Settings > General has
  "Look for referenced files only in the opened folder", off by default. On, the
  viewer looks for the files an assembly or a drawing names only in the folder
  you opened and its subfolders, for the details tabs, the 3D view, 3D Print,
  both exports and drawings. A file found only outside is shown as not found,
  and the message says the setting is on.

- **A reference web viewer.** `solidseas serve --viewer` serves a web page that
  lists the folders and files, draws a part or an assembly in 3D, and shows an
  assembly's bill of materials and a file's properties. Everything it loads
  comes from the service itself. `GET /v1/mesh` answers a document's display
  meshes as a glTF binary, and `solidseas.gltf` writes the same from Python.

- **A settings file and named web origins for the REST service.** `solidseas
  serve --config FILE` reads the service's settings from a TOML file, an option
  on the command line replacing the file's setting, and refuses a file another
  account could change. `--allow-origin ORIGIN` lets web pages of exactly that
  origin call the service from a browser with a token; without it, pages from
  other sites are still refused.

- **The REST service behind a port mapping.** `solidseas serve
  --identity-address ADDRESS:PORT` lets clients behind a published container
  port or a proxy check the service with /v1/identity before they send their
  token.

- **Drawings of turned (lathe) parts.** Turned (lathe) is a manufacturing type
  for drawings, and the wizard suggests it when the part turns about one axis.
  The drawing shows the profile with the larger end on the left; each diameter
  is dimensioned across the outline (equal ones once with 2X), with circular
  runout to datum A on the longest diameter, and shoulders are measured from
  datum B on the end face. Turned parts use the machined entries of Drawing
  Settings. On the command line: `--process turned`.

- **Drawings of STEP, Parasolid and Alibre parts.** You can now make drawings of
  parts saved as STEP, Parasolid (.x_t, .x_b) or Alibre Design files, from the
  viewer's Make Drawing and New Drawing or with `solidseas drawing new`. Such a
  part has no configurations. A Parasolid file never says which unit its part
  was designed in, so SolidSeas guesses it and asks you to confirm. Assemblies
  and mesh files in those formats can't be drawn yet.

- **SOLIDWORKS parts from CadQuery models.** `solidseas sldprt` now writes a
  SOLIDWORKS part from a CadQuery model. Record the model in your CadQuery
  session with `solidseas.nativewrite.cqrecorder` and save the recording as a
  .json file; the part then needs neither CadQuery nor SOLIDWORKS to make. Each
  feature is listed by the CadQuery call that made it. Calls SolidSeas does not
  translate yet, such as fillet, are named, and `--allow-partial` leaves them
  out. From CadQuery a part can hold rectangles on the Front Plane extruded up
  and, on a part of a single box, one hole through all; CadQuery's fillet is
  not translated yet. CadQuery stays the optional cad extra.

- **A file's versions, and what changed between them.** `solidseas history FILE`
  lists a file's versions, newest first. Inside a Git repository these are the
  commits that changed it; SolidSeas reads them without running Git or any
  program the repository's settings name, and reads Git LFS files from what is
  already downloaded. Elsewhere they are snapshots you take with `solidseas
  snapshot FILE`, kept in your own data folder, or in the project's .solidseas
  folder with `--project DIR`, never beside the file. `solidseas diff FILE
  [OLDER] [NEWER]` says what changed between two versions: properties,
  configurations, material, units, the saving SOLIDWORKS version, and for a part
  each configuration's geometry. The library offers the same through
  `solidseas.versions` (provisional).

- **A second opinion on a STEP export.** `solidseas export FILE --format step
  --check` has Open CASCADE read the new STEP file back. It says whether the
  file holds what was written, closed and valid, and gives Open CASCADE's volume
  and area to compare with SOLIDWORKS' Mass Properties. It exits 1 when the file
  does not read as written; the file is kept. It needs the OCCT backend
  extension.

- **File > Convert in the viewer.** With the OCCT backend extension on, File >
  Convert writes the file shown as IGES, BREP or STEP: a SOLIDWORKS part or
  assembly, a Parasolid or STEP file as IGES or BREP, an IGES file as STEP or
  BREP, and a BREP file as STEP or IGES. The save dialog's file type picks the
  format.

- **Gridfinity bins laid out in words.** The chat now shows you a bin's layout
  before it is made, and you can change it in words: "turn the pliers 90
  degrees" keeps them turned while the rest are laid out around them, and "put
  the knife on the left" places the tools exactly where the chat says. A pocket
  that would go through the wall or sit too close to another is refused, saying
  which one and by how many millimetres, and a small tool can sit in the crook
  of a larger one. The bin made is the layout you were shown.

- **A machine policy an administrator can set.** Run as administrator,
  `SolidSeasViewer.exe --set-policy NAME=VALUE ...` writes the policy that
  restricts SolidSeas on a PC (`HKLM\SOFTWARE\Policies\SolidSeas`): it can turn
  Automatic mode off, keep the AI to an Ollama server on the PC or to approved
  hosts, stop pictures of a part being sent, and switch extensions off or limit
  them to a list. Every value is checked before any is written, who set it and
  when is recorded, and the policy is read back and shown as SolidSeas reads it.
  `--remove NAME` and `--remove-all` take values away. The program has no
  console of its own, so pipe its output (`| more`) to see it.

- **SOLIDWORKS parts from a design, without SOLIDWORKS.** `solidseas sldprt
  DESIGN -o FOLDER` writes a new `.SLDPRT` from a SolidCraft design or a
  SolidSeas design file (`.json`). Today it writes corner rectangles on the
  Front Plane, each extruded blind, with the features named as SOLIDWORKS names
  them and the extrusion depth editable in SOLIDWORKS; the command lists each
  feature with its name in your design. A part with one box can also have one
  round hole cut through it, and opens in SOLIDWORKS 2024 with the hole in
  place. Such a part can also have fillets on the box's edges along its depth
  and on the hole's far edge (see Fillets in parts made without SOLIDWORKS). The
  part also gets the design's file properties (text, numbers, dates and yes or
  no values), which SOLIDWORKS shows on the Custom tab of File > Properties, and
  `--property NAME=VALUE` adds a text property, such as a part number, as you
  write it. A design that needs anything else, such as a fillet on other edges
  or a second hole, is refused with every such item listed, and nothing is
  written. With `--allow-partial` the part is written without them, every item
  left out is listed, and the command exits 4. It never replaces a file, and
  `--json` prints the new `sldprt_written` result. SolidSeas reads each part
  back before writing it. Parts like these without a fillet open in SOLIDWORKS
  2024 with their feature tree and rebuild when you change a depth; other
  versions have not been tried, so check an important one there before you rely
  on it.

- **A run SolidSeas did not get to finish is offered again.** If SolidSeas
  closed during an Automatic run, or before you chose Keep or Revert, the
  assistant now shows that run the next time it opens: the part, your goal, the
  plan with each step marked done, failed or not run, how far it got, and where
  the safety copy is. You choose what happens to it. **Revert** takes the run's
  steps off the part in SOLIDWORKS, newest first, as Revert after a run does,
  but only when the part is open and still exactly as the run's last step left
  it; otherwise it changes nothing and says what is different, so you can open
  the safety copy instead. **Keep** leaves the part as it is and closes the
  run. **Decide Later** does nothing and asks again the next time, until the
  run's folder is removed 7 days after its last change, a date the offer gives.
  Neither choice saves the part. A run another SolidSeas window or program is
  still working on is never offered, and the MCP server leaves these runs to
  the assistant window.

- **A long parts list goes on to more sheets.** An assembly drawing whose parts
  list is longer than its columns on the first sheet hold used to stand those
  columns ever taller, often forcing a larger sheet. The list now fills the
  first sheet's columns and goes on to sheets of the same size after it, each
  with the title block, the border and the stamps, and the list in as many
  columns as the sheet holds, every column with its headings. Every title block
  says which sheet it is (SHEET 2 OF 3), the first sheet's too. The views,
  balloons, notes and revision block stay on the first sheet. The PDF has a
  page for each sheet; the DXF has the sheets side by side in one drawing, left
  to right, so every reader shows them all as soon as it opens the file. The
  drawing editor pages through the sheets with Drawing > Next Sheet and
  Previous Sheet (Ctrl+Page Down and Ctrl+Page Up), and the status bar says
  which one is shown. `solidseas drawing` reports the sheets in its summary and
  as `counts.sheets` in its JSON. A drawing of one sheet, and its file, PDF and
  DXF, are exactly as before, and drawing files from earlier versions open
  unchanged. Opened in an earlier version of SolidSeas, a drawing of several
  sheets opens without its laid-out sheet until it is laid out again.

- **IGES and BREP files, with the OCCT backend extension.** SolidSeas now reads
  IGES files (`.igs`, `.iges`) and Open CASCADE's BREP files (`.brep`) through
  the OCCT backend extension, a package you add in Tools > Extensions and switch
  on, when a release offers it. With it on, they open in the viewer and on the
  command line as STEP files do: the 3D view, thumbnails, Export for 3D
  Printing, 3D Print and the index all take them. An IGES file's loose surfaces
  are sewn into solids where they meet within 0.01 mm; the ones that stay open
  are shown as surfaces, and a warning says how many. The file's unit, the
  program that wrote it, its author and its date come from its own header.
  Without the extension these files are listed greyed, and the viewer, the
  command line and the error say what to add. Open CASCADE runs only in the
  extension's own program, on a copy of each file; a file that makes it stop
  fails on its own. The extension is marked In development.
- **`solidseas convert` writes IGES, BREP and STEP.** With the OCCT backend
  extension on (when a release offers it), `solidseas convert FILE --format
  iges|brep|step -o OUT` writes an IGES, BREP or STEP file, a SOLIDWORKS part or
  assembly, or a Parasolid file in another of those formats, in millimetres. A
  SOLIDWORKS document or a Parasolid file goes through the STEP SolidSeas writes
  of it. IGES is written in BRep mode, so solids stay solids, with a header that
  names no one. The output follows the export's rules (`--force`,
  `--allow-source-dir`), and `--json` prints a `file_written` document.

- **Assemblies in a batch get their Parasolid file too.** `solidseas batch`
  used to write Parasolid files for parts only. It now writes each assembly in
  the folder as `solidseas parasolid` does, one `.x_b` file (and an `.x_t` file
  with `--text`) named after the assembly, such as
  `frame.SLDASM_Default.x_b`. The same choices are there: `--configuration`,
  `--allow-partial`, `--other-configurations` and `--include-hidden`, applied
  to every assembly in the run. An assembly that cannot be written, because a
  component is missing or a part lacks the bodies of its configuration, now
  gets an error row in the report naming the components, and the run ends with
  exit code 4 while the rest of the folder is still written. With
  `--allow-partial` the report's new `parasolid_left_out` column counts the
  components each assembly left out, `report.jsonl` names them, and the summary
  adds them up. As with every file a batch writes, an existing file is only
  replaced with `--force`. Pass `--no-parasolid` to skip Parasolid files
  altogether, as before.

- **Assemblies as Parasolid files.** `solidseas parasolid` now takes an
  assembly too, and writes one `.x_b` file (and an `.x_t` file with `--text`)
  holding every part of a configuration where the assembly places it: each part
  once, placed by as many instances as use it, sub-assemblies kept as assemblies
  of their own, and every instance named as in the FeatureManager tree.
  Suppressed and hidden components are left out, and components excluded from
  the bill of materials are kept. When a component file is missing or a part
  does not store the bodies of the configuration the assembly uses, nothing is
  written and the message names the components; `--allow-partial` writes the
  rest, and `--other-configurations` writes such a part with the bodies it does
  store. In Python it is `solidseas.parasolid.assembly_parasolid` (or
  `Document.assembly_parasolid`) and `write_parasolid`. On the test assemblies
  every part lands on the box SOLIDWORKS reports for it, and the volume, mass
  and centre of mass match SOLIDWORKS' own. The files have not yet been opened
  in a Parasolid kernel. Names outside ASCII in a Parasolid file's name
  attributes are now read as UTF-8 when they are valid UTF-8.

- **Guided drawings.** Guided, the second way to make a drawing, is no longer
  coming soon. It asks a few plain questions, one at a time, each with a
  sentence on why it matters: what the drawing is for (to show a customer or get
  a quote, to 3D print the part, to make it from plain sizes, or to have it
  machined in a shop), which views to show, which unit, how much to dimension,
  whether holes the size of a tap drill are threaded and to which size (asked
  only when the part has such holes), and what the title block says. Each
  answer starts from the part and your Drawing Settings, Back and Next move
  between them, and the preview beside them shows the drawing as it takes
  shape. The last page says what will be made and where it goes, with a PDF
  beside it unless you untick it. Finish saves the drawing and opens it in the
  editor. Remember My Choice and Settings > Drawings offer Guided like the other
  two. Starting another drawing while Guided is open brings it forward and says
  a Guided drawing is already open.

- **Balloons on parts hidden behind others.** On an assembly drawing, a part
  that sits inside another, or behind other parts in every view, now has its
  hidden lines drawn dashed in the front, top and side views, and its balloon
  points at one of them, as a drafter would draw it. Before, it had no balloon
  and the checks warned about it. Only those parts' hidden lines are drawn, so
  an assembly whose parts all show is drawn as before.

- **The AI can look at the part after each step.** In Automatic mode, with the
  picture box ticked, a second box, Show it the part after each step, has the
  model look at a picture of the part after every step that passed SolidSeas'
  checks. SolidSeas saves a copy of the part as it is then, unsaved changes
  included, draws it, and asks whether the part looks the way that step should
  leave it. If the model says it does not, the run stops there and you choose
  Keep or Revert; the look never lets through a step the checks refused, and a
  look that cannot be made is noted in the log while the run goes on. It is
  off until you tick it, costs one more request per step, and is greyed out
  where your administrator has turned pictures off. A chat through SolidSeas'
  MCP server can ask run_plan for the same pictures, one after each step.

### Changed

- **Install guide covers checking a download and the SmartScreen warning.**
  Installing SolidSeas now explains, step by step, how to check a download's
  SHA-256 before running it, what Windows SmartScreen shows for the unsigned
  installer (More info, then Run anyway), and that Smart App Control blocks it
  outright where it is turned on.

- **Release viewers accept their own release's packages.** A release build now
  takes the extension packages attached to the release, checks each against the
  release's SHA256SUMS.txt, and builds the installer and the single-file viewer
  to accept exactly those packages, so a viewer downloaded from a release can
  add the packages published beside it. The installer also carries the packages,
  which the viewer adds, switched off, the first time it starts. A release with
  no packages attached still builds, and its viewer accepts none. The release
  also includes BUNDLED-FILES.txt, the list of every library inside the
  single-file viewer.

- **The web viewer is marked provisional.** The help for `solidseas serve
  --viewer` now says the reference web viewer is provisional.

- **The ISO choice says what it changes.** In Drawing Settings, the ISO standard
  reads "ISO (first angle views, ASME sheet)": so far it changes only the
  projection to first angle, and the sheet, title block and lettering still
  follow ASME.

- **Extension features say how finished they are.** File > Convert now shows
  "(In development)" and Save Animation shows "(Experimental)", the same tags
  the Extensions page gives the OCCT backend and the video extension.

- **Drawings move to a larger sheet when they would clash.** When a drawing's
  sheet size is automatic and the drawing still has text over text, or a
  dimension with no clear place, SolidSeas lays it out again on the next larger
  sheet, and on larger sizes after that until the drawing is clear or the
  largest size is reached. It keeps the sheet with the fewest conflicts, the
  smaller one when two are equal, and the drawing's checks say which sheet was
  used and why. A sheet size you chose in the drawing or in Drawing Settings is
  never changed.

- **A continuation title block on later sheets.** The sheets after a drawing's
  first carry a short continuation title block (size, CAGE, drawing number,
  revision, scale and SHEET n OF m) in place of the full one, so a long parts
  list fits more lines on each of them.

- **Identity reads count as files opened.** In display geometry and the BOM, the
  files reference resolution opens to read their identity now count toward
  `max_files` and `files_opened`. Large assemblies on Linux report sub-assembly
  files held open past the open-file limit as a limit (`max_files`), not as
  unreadable or missing, and the sub-assembly source no longer reads the tree of
  a sub-assembly that stores nothing for a part.

- **Faster explode switches and box drawing.** Switching a sub-assembly's
  explode, the Explode level or what is hidden recomputes up to four times
  faster on large compact assemblies, and switching back to an earlier choice is
  instant. With a component made transparent, the grey boxes wholly in front of
  or behind it are drawn together instead of one at a time.

- **Parts are tessellated once while the viewer runs.** Parts drawn from their
  own geometry are kept while the viewer runs: showing an assembly again,
  another configuration of it, another assembly with the same parts, or one of
  those parts on its own no longer tessellates them again, and a part saved
  again is read again. For library users, `display_geometry` takes `brep_cache`,
  a `solidseas.tesscache.TessellationCache` (provisional).

- **Stored paths through links.** A file named by a stored path that goes
  through a link, junction or cloud folder is no longer looked for through it;
  it is reported with the stored-path-refused warning.

- **When OpenGL starts.** The 3D View setting's note and the guide now say
  starting OpenGL holds the window when the setting is turned on, or when the
  viewer starts with it on, rather than at the first part.

- **Stable identity answers from the REST service.** The service keeps an
  identity key file beside its token file, so /v1/identity's answers for names
  without a token no longer change when the token file is edited. It is created
  on first start; a service whose folder it may not write to (the shared-machine
  recipe in the API guide) needs an administrator to create it once.

- **The REST service reads only what it was started for.** `serve --formats` now
  refuses a file whose content is a format it was not started with, whatever its
  name says, and reads model files within its own bounds (10 million triangles,
  30 million vertices, 512 MiB of named files). In a root served without its
  subfolders, a model file reads the files it names from its own folder only.

- **IGES and BREP through the REST service.** `solidseas serve` reads the tree,
  counts and preview of IGES and BREP files when it is started with `--formats`
  including them and the OCCT backend extension is on; its workers may then
  start Open CASCADE's helper. Before, it answered needs_extension on Windows.

- **Lighter 3D print preparation.** Preparing a 3D print, or an STL or 3MF
  export, joins a mesh's vertices with about 40 percent less memory, and faster
  for SOLIDWORKS display meshes.

- **3D Print Part for a part whose file was not found.** In an assembly's 3D
  view, right-clicking a part whose own file was not found (drawn from what its
  sub-assembly stores of it) now shows 3D Print Part greyed, with the reason and
  the stored path, instead of offering nothing for the part.

- **Batch conversion leaves your documents open.** Batch conversion with
  SolidSeas' own SOLIDWORKS (`python -m solidseas.swapi convert`) no longer ends
  that SOLIDWORKS while it shows a document SolidSeas did not open, such as one
  you opened in it while it ran. It shows that SOLIDWORKS on your screen
  instead, says so in the log, and ends it once you have saved and closed the
  document. This takes effect with the next CAD Bridge package, since the
  bridge built from this version has not been compiled or run yet.

- **The video package's ffmpeg, built from source.** The ffmpeg in the video
  export package is now built from FFmpeg 9.0.2's source, its signature
  checked, under the LGPL and with only what Save Animation uses: PNG frames
  in, GIF out, and MP4 out through Windows' own H.264 encoder (h264_mf) or as
  MPEG-4 part 2. It holds no GPL or nonfree part and no OpenH264. Its source,
  signature and build script are published as the `ffmpeg-9.0.2-source`
  release, and `THIRD_PARTY_NOTICES.txt` names what is linked into it.

### Fixed

- **The model-governs note names the model in capitals.** A reduced-dimension
  drawing of a part whose file name or number has lower case no longer fails the
  lettering check.

- **File > Convert follows Look for referenced files only in the opened
  folder.** With the setting on, converting an assembly no longer reads
  component files from outside the folder you opened.

- **The viewer's self-test leaves your cache folder alone.** The index it makes
  of the folder it tests and the thumbnails it draws now go to a temporary
  folder of its own, removed when it ends.

- **A half-written 3D print file is retried later.** If a stopped 3D Print
  export left a temporary .part file that could not be deleted, the next 3D
  Print now tries again to remove it.

- **Tessellation warnings are listed.** The warnings no_stored_bodies,
  configuration_assumed and bodies_unreadable are now in the list of warning
  codes and in the API reference.

- **Complete licence texts.** Help > Licences and the video package now carry
  the notices of the code Python itself incorporates (expat and others), and the
  video package carries the OpenSSL, mpdecimal and xz licences of what it holds.
  Help > Licences no longer lists texts for software the viewer does not carry.

- **Where to get the source of the LGPL software.** The notices pointed to
  source releases that do not exist. SOURCE.txt, in Help > Licences and in each
  package, now lists the source archives of Qt, Qt for Python, FFmpeg and
  SolidSeas itself that are published beside each release, and how to ask for
  one that is missing.

- **Saved MP4 clips are sharp.** A clip from Save Animation came out blurry and
  blocky, with trails behind the parts that move, because it was encoded at a
  very low bitrate whatever its size. MP4 clips now get a bitrate to suit their
  size and frame rate, and Windows' own encoder uses its High profile.

- **Save Animation no longer closes the viewer partway through.** On some NVIDIA
  graphics drivers the viewer quit while saving a video, after the first frame
  or two. Every frame is now drawn in the 3D view's own context, whatever the
  progress window redraws in between.

- **Checksum lists you can check anywhere.** A release's SHA256SUMS.txt and
  .sha256 files now end their lines the Unix way, so `sha256sum -c` on Linux or
  macOS verifies the downloads instead of failing on every line.

- **The same mesh on Windows and Linux.** A part's mesh, and the drawings, 3D
  views and exports made from it, now come out the same on both. A sine or
  cosine that the two systems rounded a hair differently could change a curved
  face's triangles, and with them a drawing's silhouette lines.

- **Out of time, not "no solid bodies".** Comparing two versions with a short
  time limit now says the time ran out when it stopped while reading a part's
  bodies, instead of saying the part has no solid bodies. This showed on
  Windows, whose clock moves in larger steps.

- **Security fixes from the desktop review.** A chat is no longer told the full
  path of a part's file when a picture of it cannot be made or a file call
  fails; a Gridfinity bin laid out by hand on a grid you give is held to the
  100-cell limit; the SSH tunnel to a Tracefinity server uses Windows' own ssh,
  never one in the current folder, and always refuses a server key it has not
  seen before; making a bin never writes through a temporary file already in the
  bins folder; a packaged SolidSeas no longer looks for the CAD Bridge in a dist
  folder under your temporary folder; and --set-policy writes the removal of
  AllowedProviderHosts with the restrictions, before anything that relaxes one.

- **The machine policy holds for checkouts' helpers and extension packages.** An
  administrator's DisableExtensions or AllowedExtensions now holds for a bridge
  named by SOLIDSEAS_SWBRIDGE and an OCCT helper named by
  SOLIDSEAS_OCCT_HELPER_PYTHON; the CAD Bridge's program is checked against its
  package before it runs, as every other extension's helper is; Add from file
  refuses a package for an extension your administrator has left off rather than
  unpacking it; and a drawing no longer finds its model through a link or
  junction on the model's stored path.

- **The projection symbol on ASME drawings.** ASME drawings showed the
  first-angle projection symbol in the title block. They now show the
  third-angle symbol.

- **Room for a datum feature symbol.** When a datum feature symbol has no room
  on the automatically chosen sheet, the drawing moves to the next sheet size if
  that clears it.

- **Position frames beside a dimension.** A position frame beside a dimension's
  value is no longer covered by a dimension in the next row.

- **A dimension's value and a datum symbol.** A dimension's value no longer
  stands on a datum feature symbol placed between its view and the dimensions on
  that side.

- **Indexing a folder that holds SolidSeas' cache.** Indexing a folder that
  holds SolidSeas' cache (a home folder, say) no longer walks or indexes the
  catalogs inside it.

- **Where Used notes.** A long Where Used note is cut at its end instead of its
  middle, and its tooltip shows all of it.

- **index and serve agree on root ids.** `solidseas index FOLDER` now keeps the
  root id `serve --catalog` gave the folder, so the two no longer rename each
  other's roots and resolve every document again.

- **Picking through transparent parts on OpenGL ES.** On OpenGL ES graphics, a
  click goes through a transparent part to what lies inside its box, as on other
  graphics, also where the driver lacks depth writes from shaders or high
  precision.

- **Watertight solids with a hole at an edge.** Solids with a hole that touches
  or almost touches an edge of a face now come out closed, so their 3D prints
  are watertight.

- **Domes and lemon shapes.** Domes and lemon shapes made by revolving an arc
  whose centre lies off the axis are drawn; they used to be left as holes.

- **Smooth shading along small fillets.** Small fillets along long curved edges
  are shaded smoothly: the triangles along their edges no longer tilt up to 60
  degrees away from the surface.

- **Time limits and memory while drawing from bodies.** Parts and assemblies
  drawn from their bodies keep to their time limit while the bodies are read,
  not only while they are tessellated, and in an assembly a part that runs out
  of memory is skipped with a reason while the rest are still drawn.

- **Faster STEP export of parts with many holes.** STEP export of parts with
  many round holes or other faces cut at their seams is faster: a plate of 900
  holes took 20 s and takes 2 s. The file written is the same.

- **Large STEP assemblies open faster.** An assembly that places each component
  both by its own placement and by a mapped item, or keeps its mapped items in
  one shared representation, took time that grew with the square of its
  components (4,000 components took 18 s); it now grows in proportion (2.5 s).

- **The Computed column.** The Properties tab's Computed column marks a property
  linked to another property (`$PRP:`), and no longer marks a typed value that
  only looks like a link.

- **Reader fixes.** The zip compression ratio is taken against the bytes
  actually read; a second scene of a 3MF no longer trips the zip total limit;
  3MF colour groups and AMF volumes and materials are bounded; OBJ material
  libraries are counted as they are named; a PLY comment mentioning end_header
  no longer ends the header; JSON numbers such as 1e999 are refused; glTF
  strips, fans and GLB chunks keep the time limit.

- **Crafted files that ask for too much memory.** A crafted 3MF or zipped AMF
  can no longer make SolidSeas build a central directory larger than its end
  record admits, a glTF accessor's sparse block is checked before any zeros are
  made, strided accessors are copied without an object per element, and the
  files a document names are bounded in total. Running out of memory while
  reading a model file reports limit_exceeded on every surface.

- **A frame under a vertical dimension.** A feature control frame under a
  vertical dimension's text no longer lands across the next dimension.

- **No slivers along holes in 3D print files.** STL and 3MF exports no longer
  contain zero-area slivers along the edge of a hole, which slicers counted as
  errors to repair.

- **3D prints on drives without hard links.** On Linux and macOS, a 3D print of
  a model on a FAT or exFAT drive, or on a share without hard links, goes to the
  temporary folder and says the folder's file system has no hard links, instead
  of saying permission was denied. Export STEP and Export for 3D Printing into
  such a folder say the same and suggest a folder on another drive.

- **Your SOLIDWORKS layout after a batch conversion.** After a batch conversion,
  SolidSeas puts back the toolbar and CommandManager tab settings (and the last
  splash screen shown) that its own SOLIDWORKS changed in your registry, as long
  as no other SOLIDWORKS ran meanwhile; run alone, for example overnight, it
  used to leave your CommandManager tabs rearranged. The recent documents list
  is not put back yet.

- **The assistant's page in the user guide.** It no longer says attaching to
  SOLIDWORKS is still to come: the assistant attaches through the CAD Bridge
  extension.

- **Names back in the documentation.** In fourteen places the documentation and
  the code's own notes showed an empty pair of backticks where the design
  pattern they follow should be named. They name it again.

- **Switching the OCCT backend extension on or off takes effect at once.**
  Before, switching it on while the viewer was open was not enough: IGES and
  BREP files were listed as readable but would not open, and the message said
  the extension was not added or not switched on, although it was, until the
  viewer was started again. Now the viewer follows the Extensions page as soon
  as you switch the extension on or off, or add or remove its package: the
  folder shown is read again, and its IGES and BREP files open, or say what
  they need, without a restart. A folder's saved index no longer outlives the
  switch either: a folder read with the extension off is read again once it is
  on, and the other way round, instead of keeping its old rows until you chose
  Re-index. If the extension is on but its program cannot start, the message
  now says that, rather than asking you to switch it on.
- **IGES and BREP files say what they need, even with Files SolidSeas Cannot
  Read off.** While the OCCT backend extension is off, these files used to be
  hidden with the formats SolidSeas cannot read at all, counted only as files
  of formats SolidSeas cannot read (hidden). They are now always listed,
  greyed, with Needs the OCCT backend in their Status column; their Overview
  and the quick filter's button point to Tools > Extensions, and the status bar
  counts them by format (1 IGES file needs the OCCT backend extension). Files
  of formats SolidSeas cannot read at all, such as Inventor or VRML, are still
  hidden unless View > Show > Files SolidSeas Cannot Read is on.
- **Old run folders are cleared away.** The assistant said a kept run's folder
  stays for 7 days, but nothing ever removed it, and with the look after each
  step on, every step added another copy of the part. Now, when the assistant
  or its MCP server starts, it removes the folder of each run that ended and in
  which nothing changed for 7 days, safety copy, step copies and journal
  included. A run still open, in this window or in another program, keeps its
  folder however old it is, and SolidSeas removes nothing outside its runs
  folder and never follows a link or junction there. A safety copy you have
  open in SOLIDWORKS keeps its folder until the next time.

- **A sheet too small for the drawing says so.** When you choose a sheet size
  and the views with their dimensions fit it at no scale, the drawing now says
  to choose a larger sheet and offers Sheet and Scale as a fix, instead of
  saying the views do not fit the largest sheet. With the sheet left on
  automatic, a larger sheet is picked as before.

- **Smoother noses on STEP models.** A nose cone or other shape made by
  revolving an arc is meshed as finely as the rest of the part. Its arc's whole
  circle, which reaches far past the part, had made the part look larger to the
  mesher, so the nose came out about three times coarser.

- **Hole callouts keep their space in SVG.** A callout such as "6X Ø4.50
  THRU" no longer runs together as "6X Ø4.50THRU" when a drawing is shown as
  SVG.

- **The exit code of an assistant script that ends its own process.** When a
  script you approved in the modeling assistant ended its own process, a slow
  PC could report exit code 0 whatever code the script ended with. The
  assistant now waits for the process to finish exiting and reports its real
  exit code.

### Security

- **An extension's settings file is checked before its helper starts.**
  SolidSeas now refuses to start an extension's helper when the package's
  extension.json in your profile is not the one its release recorded, so a
  helper and its manifest replaced together are no longer run.

- **Old copies of files sent to Open CASCADE are cleaned up.** When a conversion
  through the OCCT backend was stopped by force, its copy of your file stayed in
  the temporary folder; SolidSeas now removes such copies older than a day the
  next time it uses the backend.

- **SolidCraft's chat tools never look at a network share.** A path from the
  chat outside SolidCraft's folder is refused before Windows opens it, in any
  spelling of a share, so no sign-in is sent to a server the chat names.

- **Extension packages are added only as the file that was checked.** A package
  changed after SolidSeas checked it, for example on a file share or in a folder
  another account can change, is now refused instead of added.


## [0.2.361] - 2026-10-19

### Added

- **Native SOLIDWORKS part writing, first research steps.** The library has
  a new, experimental `solidseas.nativewrite` package that writes `.sldprt`
  files without SOLIDWORKS: it lays out the 2015+ container, changes a
  feature's driving dimension and a sketch's points in place, reads SolidCraft
  designs into a new source-independent description of a parametric part,
  and writes the simplest such part (one rectangle extruded) through a part
  SOLIDWORKS made, refusing anything it cannot carry. SOLIDWORKS 2024 opened
  every test part it wrote as a native sketch and extrusion, rebuilt it,
  took a change of the depth dimension and saved it. Sketch dimensions and
  most feature types are not written yet, so it is not offered in the app
  and is not for real work. docs/NATIVE_SLDPRT_WRITER.md explains what is known and what
  is still being measured.

- **Express drawings.** Pressing Drawing now asks how you would like to make the
  drawing. Express goes straight to the editor with a simple drawing for showing
  a customer: the views the part needs and an isometric, the overall length,
  width and height, each hole by size (4X and so on for patterns), and where the
  holes are, from the part's edges or as a pitch circle. It asks no questions:
  the title block comes from the part's properties, the first person in People
  and today's date. Expert opens the New Drawing wizard with every option, as
  before, and Guided is shown as coming soon. Tick Remember My Choice, or pick a
  mode under Settings > Drawings, to skip the question. Express drawings stay
  Express when you use Update from Model.

- **The preview on the Overview tab.** The Overview tab now shows the
  document's preview image above its summary when it has one. Click it, or
  select it and press Enter or Space, to open it on the Preview tab. This shows
  the image even when the tab is set to 3D, for that document only: the next
  document opens in Image or 3D as you last chose.

- **A short README and a user guide.** The README is now a short front page,
  and the full manual has moved to a user guide in docs/guide, one page per
  topic, which is also published as the project's GitHub wiki. Each release
  now carries the single-file SolidSeasViewer.exe beside the installer again.

- **A Windows installer.** Each release on GitHub now includes
  SolidSeas-Setup-<version>.exe, with its SHA-256 beside it. It installs
  SolidSeas Viewer for you alone by default, with no administrator rights; an
  administrator can install it for everyone on the PC instead. It adds a Start
  menu entry and, if you ask, a desktop shortcut, and you can remove it from
  Settings > Apps. Installing a newer version closes a running viewer first and
  keeps your settings, and uninstalling leaves your settings and caches in
  place. The installer installs the one-folder form of the viewer, which starts
  faster than the single executable, and its Qt libraries are ordinary files
  you can replace, as THIRD_PARTY_NOTICES.txt explains.

- **An independent project, said plainly.** SolidSeas now says at the top of
  the README, in NOTICE, in Help > About and at the end of `solidseas --help`
  and `SolidSeasViewer --help` that it is an independent project, not
  affiliated with, endorsed by or connected to Dassault Systèmes or Siemens,
  and credits each trademark to its owner. The extension that works with your
  own SOLIDWORKS installation is now called the CAD Bridge (id `cad-bridge`,
  package `cad-bridge-<version>.zip`). An existing install keeps working: its
  switch, an administrator's AllowedExtensions entry and an added package under
  the old `solidworks` id are all still recognised, and adding the new package
  replaces the old one. The chat tool `solidworks_sessions` is now
  `cad_sessions`, and the old name still answers.

- **The licences of everything SolidSeas Viewer carries.** Help > Licences
  shows them, the About box names Qt and the GNU LGPL, and
  THIRD_PARTY_NOTICES.txt explains each one, where Qt's source is and how to run
  the viewer with your own build of Qt. The extension packages carry their
  licence texts too, and the video package records which ffmpeg build it holds
  and where that build's source is.

- **Ready for contributors.** CONTRIBUTING, SECURITY, CODE_OF_CONDUCT and
  SUPPORT files, issue and pull request templates, and a short status section in
  the README saying what is stable, what is a preview and what is experimental.

- **Experimental features say so.** Drawings, the modeling assistant and the
  Gridfinity, video export, SolidCraft and CAD Bridge extensions carry a
  small Experimental tag beside their menu entries and on the Extensions page,
  and the OCCT backend says In development. Their Settings pages explain what
  that means: results may be incomplete or wrong, so check every drawing before
  you use it, and they may change between versions. Problems can be reported on
  the project's GitHub issues page. Drawings stay on by default, and a new
  switch on the Drawings page of Settings turns them off. A drawing that is not
  yet released still carries its PRELIMINARY stamp on every PDF and DXF.

- **Datum symbols in another view.** A datum symbol that finds no clear place
  in its view, often because a tall column of ordinate dimensions boxes it in,
  is now drawn in another view where its face shows as an edge, such as the end
  of a plate in the top view. The drawing, its file and its checks all name the
  view the symbol is drawn in, and it stays there when the drawing is laid out
  again.

- **Fewer crowded hole callouts.** On a crowded drawing, a hole callout or
  radius that finds no clear spot no longer gives up straight away. SolidSeas
  tries leader angles and lengths in between the usual ones, then places the
  hard callouts first and tries again. On plates with dozens of holes this
  clears most of the callouts that used to be placed with a conflict, for a
  little more time per drawing.

- **Labels on Gridfinity bins.** A bin made in a chat can carry a text label:
  the tool's name, or your own text, sunk into or raised from the top of the
  bin along its back edge, or each tool's name in the floor of its pocket. The
  label is made as large as fits, down to 4 mm tall letters, and the chat says
  when it had to shrink it or when it cannot fit. A labelled bin also comes as a
  3MF with the letters as their own body, so a slicer can print them in another
  colour.

- **Hole patterns on part of a circle.** Holes of the same size on part of a
  circle, spaced at an equal angle, are now dimensioned as one pattern instead
  of hole by hole: the hole callout with its count, the pitch circle's
  diameter, the angle to the first hole and the angle between holes with the
  number of spaces (for example 4X 30°). The pitch circle is drawn as a centre
  line arc over the holes.

- **Network shares on macOS.** SolidSeas now recognises SMB, NFS, AFP, WebDAV
  and FTP shares, and FUSE file systems such as sshfs, from the system's list of
  mounts without contacting the share. A catalog is never kept on one, reads
  outside your folders and 3D Print treat it as a network location, and
  `--in-project` now works on a local disk.

- **A checked Windows build.** The Windows executable is built from an exact,
  hash-checked list of its dependencies (requirements/build-windows.txt), so
  every build bundles the same PySide6, PyInstaller and truststore files and a
  tampered download is refused. scripts/lock-build-deps.sh updates the list.

- **Folders open at once, and recent folders.** The viewer keeps each folder's
  index, so opening it again shows the list straight away instead of reading
  every file. A bar says how old the index is, with Re-index (or F5). Settings
  > General can re-index automatically once an index is older than a time you
  choose, 1 day by default. File > Recent Folders lists the folders you opened
  last.

- **One Settings window.** Settings (Ctrl+,) now opens a single window with
  every setting in it, its pages listed on the left: General, 3D View, 3D
  Print, Drawings with each Drawing Settings page beneath it, AI Assistant and
  Extensions. OK and Apply save them all. AI Settings, Drawing Settings and
  Tools > Extensions open the same window on their own page.

- **Extensions that come with the viewer are added for you.** Packages in a
  SolidSeas extensions folder beside the viewer are added when it starts, so
  Tools > Extensions lists them as added and you only switch them on.

- **Progress in the chat.** A run carried out through SolidSeas' MCP server
  now says which step it is on as it goes, for chat programs that show
  progress, instead of waiting silently until it ends.

- **Show the AI a picture of the part.** The Modeling Assistant has a new tick
  box, off until you tick it, that sends a picture of the part with your
  request, so the model sees its shape as well as its features. The picture is
  drawn from the part as last saved, and What the AI sees says so. A chat
  through SolidSeas' MCP server can ask for the same picture with show_part.
  An administrator can turn pictures off.

- **Items not shown on assembly drawings.** An item of the parts list that no
  view draws (hidden in the assembly, its file not found, or with no solid
  bodies) is listed in a note, ITEMS 3, 7 NOT SHOWN, and the checks no longer
  warn that it has no balloon.

- **Stacked balloons on assembly drawings.** A balloon with no room of its
  own now stacks against the balloon of a part beside it, with no leader, as
  drafting standards allow, instead of being drawn on top of something.

- **Move balloons on assembly drawings.** In the drawing editor, drag an item
  balloon to where you want it; its leader follows, and Undo puts it back. It
  keeps its place when the drawing is laid out again, and the checks say if it
  ends up on top of something.

- **Long parts lists on assembly drawings.** A parts list too tall for the
  sheet continues in further columns to its left, each with its own headings.
  A list whose part numbers need more room than the title block's width grows
  leftward, so the numbers are no longer cut short.

- **Assembly drawings show the overall size.** An assembly's length, width and
  height are drawn as reference dimensions, in parentheses, on the views that
  show both ends. When an end is on a curved face, the size is given as one
  note, OVERALL SIZE (REF), instead.

- **Assembly drawings find their parts in the folder you have open.** A
  drawing of an assembly now looks for its parts throughout the folder the
  viewer has open, as 3D Print and the 3D view do, so an assembly whose parts
  are kept in another folder of the same project draws all of them.

- **STEP files of several bodies, and STEP assemblies, import in SolidSeas'
  own SOLIDWORKS** (provisional, Windows). The bridge's import has a third
  way: the file comes in as one component of a new assembly made from a
  template you give, through 3D Interconnect, and is moved to the assembly's
  origin, so measuring the assembly measures the file. A STEP of two or more
  bodies, which made SOLIDWORKS fault when it was inserted into a part, and a
  STEP assembly, which was refused, come in this way: SolidSeas' own STEP of a
  two-body part and of two assemblies measured exactly as SOLIDWORKS measures
  the originals. Inserting a STEP that may hold several bodies into a part is
  now refused before SOLIDWORKS is asked, while your import options make
  several bodies parts, and the refusal names the new way.

- **SolidCraft in the chat.** SolidCraft, a free parametric CAD program, is an
  extension. With it on, the assistant can model new parts in SolidCraft
  without SOLIDWORKS: sketches, features and parameters, measuring, screenshots,
  and STEP, 3MF or STL exports. Its files stay in a SolidCraft folder of
  SolidSeas' own.

- **Play the explode.** The 3D view's explode bar has Play beside Collapse: the
  assembly explodes all the way, holds a moment, and collapses again. Click
  again (Stop) to end it where it is heading.

- **Save Animation.** With the video extension on, the 3D view's menu has Save
  Animation...: choose the length, frame rate, size, how far the camera circles
  and which way, a zoom, how far the assembly explodes, the background, and MP4
  or an animated GIF. The frames are drawn at the size chosen and the clip is
  saved where you pick. An assembly that explodes stays in the picture: the
  clip zooms out once, as far as the most exploded frame needs.

- **Extensions.** Tools > Extensions lists what SolidSeas can add beyond its
  core: Gridfinity bins, the CAD Bridge, video export and the OCCT
  backend. Switch each on or off; one that comes as a package is added from a
  file you download (Get extensions... opens the page where they are), checked
  before anything in it is unpacked, and removed again from the same page.
  Gridfinity stays on until you switch it off, and its chat tools disappear
  from a chat when it is off. An administrator can switch extensions off with
  `DisableExtensions`, or allow only some with `AllowedExtensions`. The
  packages themselves come in later releases. Gridfinity's folders, its
  Tracefinity address and its server are set from its Settings... there; the
  environment variables a chat's settings name still come first. The CAD Bridge follows its switch too: once its package is added,
  live mode and the SOLIDWORKS chat tools are there only while it is on.

- **Simplified, complex or fully defined drawings.** The New Drawing wizard's
  Manufacturing page now asks how much a part's drawing should say. Simplified
  gives the overall size and each hole and boss by size, with a note that the
  model defines the rest: a quick print for the shop or the printer. Complex
  sizes and locates every feature with plus and minus tolerances and no GD&T.
  Fully defined is the complete drawing SolidSeas has always made, and stays the
  default; Drawing Settings > Dimensioning sets the level new drawings start at.
  `solidseas drawing new` takes `--detail` for the same choice.

- **A BOM editor.** On an assembly's BOM tab, Edit BOM... opens the bill of
  materials in a window of its own: choose top level, parts only or indented;
  choose the columns, their order and headings, any property of the parts
  included; move rows up and down and hide the ones you do not want, with the
  item numbers following; and type over any cell, which then shows in italics
  with the text it replaced in its tooltip, until Reset Cell puts it back. Save
  keeps it as a `.ssbom` file beside your files, and Export... writes CSV, an
  Excel workbook or a PDF. Building the BOM again keeps every edit whose part is
  still there and tells you about the rest. An assembly drawing's parts list
  is edited the same way: Drawing > Edit Parts List... in the drawing editor
  opens it, with a DWG NO. column for each item's own drawing, and the balloons
  follow the item numbers you end up with.

- **The AI connector can show the model a picture of the part.** A prompt can
  now carry a PNG that SolidSeas draws of the part, sent after the text to
  Anthropic, OpenAI, Gemini or Ollama in each one's own form, counted in the
  token estimate before the call, and shown as a line in "What the AI sees".
  Nothing sends one yet unless you choose to; an administrator can forbid it
  with the new `DisableImages` policy value.

- **Tab hides a part in the 3D view, as in SOLIDWORKS.** With the pointer on a
  part of an assembly, Tab hides it, and Shift+Tab shows everything hidden
  again. With nothing under the pointer, or nothing hidden, the keys move
  between the window's controls as they always did.

- **Gridfinity bins from photos of your tools** (`docs/GRIDFINITY.md`). Photograph
  tools lying on a sheet of A4, Letter, A3 or Tabloid paper, put the photo in
  `Pictures\Gridfinity`, and ask a Claude chat for a bin: Tracefinity, which you
  run in Docker on a server of yours (`scripts\tracefinity-server.ps1`, reached
  through an SSH tunnel SolidSeas opens itself) or on your PC
  (`scripts\tracefinity.ps1`), traces each tool to the millimetre with the paper
  as the scale, and SolidSeas saves the tools you name in its library, each with a
  finger scoop, lays them out in the smallest bin they fit (or the grid you ask
  for), and saves the STL in `Documents\Gridfinity bins`. The chat shows a drawing
  of the outlines and one of the bin from above; the bin opens in Tracefinity's
  editor exactly as laid out, to adjust by hand. Your photos go only to your
  Tracefinity, which listens on its own machine's loopback only; the chat gets
  sizes and drawings, never a photo.

- **Build in SOLIDWORKS from a Claude chat** (`docs/MCP.md`).
  `SolidSeasViewer.exe --mcp` is an MCP server that Claude Desktop or Claude Code
  starts: the chat lists the SOLIDWORKS sessions on your PC, reads a part's
  summary and hands SolidSeas plans in the assistant's closed vocabulary, which
  SolidSeas checks and carries out as Automatic mode runs, to keep or revert. A
  plan that would overwrite what you have waits for you to confirm it in a box of
  SolidSeas' own. It listens on no port, saves nothing, and sends no path or
  property value to the chat.

- **The modeling assistant works in the SOLIDWORKS you have open**
  (`docs/ASSISTANT.md`). It attaches to a running session you pick, reads the
  part, and carries out the vocabulary's operations there (sketched bosses and
  cuts, fillets, chamfers, dimension changes, suppression, custom properties).
  Automatic mode carries out a whole plan without asking at each step: a safety
  copy first, then each step in its own named undo entry with the part locked,
  checked against what that operation may change, and taken back at once if it
  fails; you then keep the run or revert it, newest step first. SolidSeas never
  closes, saves or ends anything of yours in SOLIDWORKS.

- **Drawings of assemblies** (provisional, `docs/drawings/assemblies.md`). A
  SOLIDWORKS assembly can now be drawn as a part is: from the command line
  (`solidseas drawing new frame.SLDASM --out DIR --pdf --dxf`), with File > New
  Drawing..., and with Make Drawing on an assembly's row, a sub-assembly's row
  of the Components tab or This Assembly in the 3D view. Its drawing has:
  - **Views:** front, top, right and an isometric, without hidden lines unless
    you ask, every part where the assembly puts it.
  - **A parts list** on the title block: ITEM, PART NO., DWG NO., DESCRIPTION
    and QTY., as SOLIDWORKS' default BOM table lists the assembly's top level,
    the headings at the bottom as ASME places a parts list there. DWG NO. is
    the number of each component's own drawing, as SolidSeas numbers one (its
    DwgNo property, else its file name), so the assembly drawing points to the
    drawings that dimension its parts.
  - **Item balloons:** one on a visible edge of each item, outside its view,
    their leaders kept short and clear of one another.
  - **The title block, revision block and files** as a part's: the drawing
    file, and the PDF and DXF stamped PRELIMINARY until it is released.

  An assembly drawing has no dimensions, so the wizard skips how a part is
  made and its dimensions, and asks no material or finish; in the drawing
  window, signing, release, revisions, notes and Update from Model work as for
  a part. A part changed under an unchanged assembly file counts as a changed
  model. A component whose file is not found, or whose part stores no bodies
  for the configuration used, is left out and named; the parts list still
  lists it, and the checklist says it has no balloon.

- **A date property's day, ready to show.** Every property in the JSON now has
  a `date` field: for a date property, the calendar day as `2024-03-15`, the
  day that was typed, and null for the other types. SOLIDWORKS stores a date
  as an instant at noon on the saving computer, which a web page formatting it
  in its own time zone could show as the day before or after; the new field
  needs no time zone at all. In Python, `Property.date` gives the same day.

- **STEP export of assemblies.** File > Export STEP, 3D Print sent as STEP and
  `solidseas export --format step` now write a SOLIDWORKS assembly: a product
  for each of its parts, written once however many times it is placed, and
  every instance placed where the assembly puts it, virtual parts and the parts
  of sub-assemblies included, and each sub-assembly an assembly of its own in
  the file. Read back, every instance of the test assemblies sits exactly where
  the 3D view draws it. A component that is not found, or whose part file stores no bodies of the
  configuration the assembly uses, refuses the export and is named; the viewer
  asks whether to write the file without it, and the command line leaves it out
  with `--allow-partial`. 3D Print sends such an assembly as 3MF and says why.
  A Parasolid file's assembly (`.x_t`, `.x_b`) is written the same way, each of
  its assemblies a product of its own, so it can go as STEP too; an instance
  placed mirrored or scaled, which a STEP placement cannot hold, is named and
  left out only when you ask.

- **More on the 3D view's right-click menu.** Besides 3D Print, the menu of the
  3D view, on a part or the empty space round it and on an assembly's
  components, now has Zoom to Fit, Standard Views (front, back, left, right,
  top, bottom and isometric), Go Home, Set Current View as Home and Copy Image,
  which puts the view as it is on the clipboard.

- **Make a drawing of a SOLIDWORKS part from the command line** (provisional,
  `docs/drawings/`). `solidseas drawing new bracket.SLDPRT --out DIR --pdf
  --dxf` makes a datum-referenced, dimensioned drawing of a machined or 3D
  printed part in ASME inch or millimetre:
  - **Views:** the front view chosen for you, the projected views and an
    isometric, with hidden and tangent lines as Drawing Settings say.
  - **Dimensions:** basic dimensions from datums A, B and C, hole callouts
    with position frames, and ordinate dimensions where a row of locations
    would stand too deep.
  - **The sheet:** notes, a title block with your company, material and
    finish, and the revision block.
  - **Files:** the drawing file (`.ssdrw`) is always written; the PDF and DXF
    are written as PRELIMINARY and stamped. Files go only where you say, and
    never over a file SolidSeas did not write.

  The other actions:
  - `drawing check` runs the drafting checklist on a part or a drawing and
    says what is wrong in plain words, with the fixes.
  - `drawing update` brings a drawing up to date with its changed part,
    keeping your edits, and says what changed.
  - `drawing export`, `drawing show` and `drawing settings` export the files,
    show the summary and show the effective settings.
  - `--json` gives the `drawing_result` kind.

  The command never signs or releases a drawing: approvals come from a person
  in the viewer (below). A part that states no unit of length must be given
  one with `--units`.
- **Make, edit, sign and release drawings in the viewer** (provisional,
  `docs/drawings/`). File > New Drawing... (Ctrl+D, or the Drawing button
  beside 3D Print) draws the part shown, and every right-click menu that
  offers 3D Print now offers Make Drawing of NAME... right after it, drawing
  what that 3D Print entry would print. File > Open Drawing... opens a
  drawing file, and Settings > Drawing Settings... sets your company, the
  people who sign, the standard and units, the sheets, the notes and where
  files go. A SOLIDWORKS drawing, a file of another format and a part stored
  inside its assembly cannot be drawn yet, and the entry says why.
  - **New Drawing:** six pages (the part, the title block, how it is made,
    views and sheet, dimensions and holes, and the files) with the sheet
    previewed beside them as you go. Nothing is written before Finish; then
    the drawing file and the PDF and DXF you ticked go next to the part, or
    to the folder Drawing Settings name, never over a file SolidSeas did not
    write.
  - **The drawing window:** the sheet, the dimensions by view with a tick box
    each, and Properties. Drag a dimension to move it; untick one to take it
    off the sheet; set its precision, tolerance, text or frame; add a
    dimension between features you pick. The checklist below says what is
    wrong and offers the fixes. Undo and Redo, Save, Export PDF, Export DXF,
    Email PDF and Save a Copy to Send are on its menus.
  - **The model:** the window finds the part the drawing was made from. When
    the part has changed, the drawing is view-only until Update Drawing,
    which brings it up to date, keeps your edits and says what changed. When
    the part is not found, Find... points the drawing at it.
  - **Sign, release and revise:** Sign... records who checked and approved
    the drawing from the people in Drawing Settings, Release... says what
    stands in the way or writes the released PDF and DXF as new files, and a
    released drawing is read-only until Start Revision. A released drawing
    whose part has changed starts its next revision and takes the changed
    part in one step.

  All the drawing work runs in a separate process, so the window keeps
  answering while a large part is drawn.
- **Open the modeling assistant from the viewer, and set up its AI in AI
  Settings.** Tools > Modeling Assistant (Ctrl+Shift+A) and the toolbar's
  Assistant button open the assistant's window, which stays on top as before;
  pressed again, they bring the open window forward rather than opening
  another. `SolidSeasViewer.exe --assistant` opens the window on its own.
  Settings > AI Settings (also under Tools, and the assistant's own AI
  Settings button) is where you choose the provider (none, Anthropic, OpenAI,
  Gemini or Ollama) and the model, which is filled in with a default you can
  change, the Ollama address, and the API key. The key is stored in Windows
  Credential Manager and never shown again: the page says only whether a key
  is stored, an empty field keeps it, and Remove Key removes it. Test
  Connection checks the provider in the background and says what it found.
  The page also sets the monthly token budget, and a cost budget with the
  model's prices, and shows this month's use. Settings your administrator
  restricts stay visible, greyed, with "Set by your administrator", and a
  problem with the machine policy is shown with its registry key. The
  settings other than the key are kept in `AI.json` beside the viewer's
  `Viewer.ini`. When drafting is not available, the assistant's window now
  says why and offers a button to AI Settings, and it picks up a change as
  soon as the page saves it. The executable now carries the AI connector and
  the TLS it needs to reach a cloud provider; nothing contacts the network
  until you set a provider up.
- **Open a file in its own program, or show it in File Explorer.** Open, on
  the toolbar, in the File menu and first on the right-click menu of a file in
  the list, opens the file in the program Windows opens it with: SOLIDWORKS
  for a SOLIDWORKS document, the default program for any other format. Show in
  File Explorer, beside it, opens its folder with the file selected. Both are
  on the right-click menu of every row that stands for a file too: the
  Components tab's instances and files, a drawing's views and models, BOM and
  References rows, Where Used rows in the opened folder, the 3D view's legend
  and its components. SolidSeas writes nothing and makes no command line; the
  system opens the file's URL. The program that opens the file may save over
  it, which the tooltip says. A link, a lock file or a file of no 3D format is
  never offered, and a component stored inside its assembly or not found has
  both greyed with the reason.
- **The index holds every 3D format SolidSeas reads, when asked.** A catalog
  indexes SOLIDWORKS documents until told otherwise; `solidseas index --formats
  all` (or format ids such as `step,stl`), `Catalog.configure(formats=...)` and
  the viewer, while View > Show > All 3D Files is on, make it index STEP,
  Parasolid, ACIS, Alibre Design and the mesh files too. Each is read from its
  head, as the folder listing reads it: its format, type, units, sizes, the
  image it stores and its properties, so search finds it by those and by its
  name, `format:step` finds the files of one format, and duplicates finds
  copies of it. Every file a catalog answer names says its format, and
  `catalog` counts the documents of each. The catalog does not follow what such
  a file uses yet (but for Alibre Design, below), so Where Used lists nothing for
  it and says why. A format
  left out later is removed from the catalog at once. The service's catalog
  indexes the formats the service reads, SOLIDWORKS documents only by default
  as before.
- **Where Used for Alibre Design parts and sub-assemblies.** With Alibre files
  indexed, Where Used lists the Alibre assemblies that place a part or a
  sub-assembly, directly and through sub-assemblies, and how many times. The
  components are found by the document GUID each file holds, as the References
  tab finds them, anywhere below the indexed folders; a second copy, a newer or
  older version and a part found by its name alone are marked, and
  `solidseas missing` lists the components found nowhere. A catalog made before
  this is brought up to date the next time it is opened for indexing, and reads
  its Alibre files again.
- **The modeling assistant's window, in Review mode** (preview,
  `python -m solidseas_app.assistant`). Pick a SOLIDWORKS session and a
  document, describe a change, and the AI model you set up drafts code into an
  editable console with its explanation; "What the AI sees" shows the exact
  request before it is sent, and nothing runs until you press Run. Beside Run
  the console says that anything the script does outside the SOLIDWORKS undo
  list cannot be reverted. Run takes the session for this window alone, has
  SOLIDWORKS write a safety copy and open one undo entry, and runs the script
  in a separate process with a memory cap and a time limit, which Stop ends
  at once; the script reaches SOLIDWORKS only through `solidseas.swapi.live`,
  whose requests SolidSeas checks and passes on. With no AI provider set up the
  drafting controls are hidden and typed code still runs; one your
  administrator does not allow stays visible, greyed, saying so. Attaching to a
  running SOLIDWORKS comes with the bridge's live operations, in a later
  stage; until then the window says so.
- **The core of automatic drawings** (provisional, `docs/drawings/`).
  `solidseas.drawing` now holds what every stage of a drawing builds on: the
  contracts between the stages, the bounds a drawing keeps to, Drawing Settings
  in `Drawing.json` (each value checked on its own, a bad one falling back to
  its default with the reason), the ASME numbers, values and tolerances as a
  sheet shows them, a part's source with a digest that survives a save that
  changed no geometry, the B-rep model the views and features read, the
  display list and an SVG reference writer. `make_drawing` runs the stages
  that are built and says which one is not yet (`not_implemented`, rule
  `stage_missing`).
- **The tessellator can return what a drawing's views need** (provisional).
  `tessellate_document`, `tessellate_body` and `tessellate_transmit` take
  `detail=True` and then return `Tessellation.detail`: each edge's samples with
  their curve parameters and both faces' normals at every sample, each vertex's
  (u, v) on its surface, and the points and normals in float64. Automatic
  drawings build on it (`docs/DRAWINGS.md`); the mesh is the same with or
  without it, and it costs about 45 bytes a triangle on a curved part.
- **SolidSeas checks its own meshes and says what it finds.** Every
  tessellation now checks, cheaply, that each solid uses every edge of its
  triangles once each way, that each closed shell faces the way its nesting
  says (the outside out, a hollow in), and that each face's triangles cover it
  once without stretching across it. What it finds is a warning on the scene
  and in `Tessellation.checks` (`solids_not_closed`, `shells_inside_out`,
  `faces_folded`, `faces_coarse`), so a STEP file that comes out open or
  folded says so. An STL or 3MF export now also turns round a closed shell
  that is plainly inside out (it lies in no other, or the whole object is),
  with the warning `shell_reoriented`, and warns `shells_inside_out` where a
  shell facing out sits inside another, which may be a body inside a body or
  a hollow turned inside out and is left as it is. Bodies that touch are
  judged right: one beside another is never taken to be inside it, and where
  two touch so closely that which lies inside which cannot be told, the
  warning says their facing was not checked rather than calling the print
  repaired. Nothing is refused: a slicer still gets the file.
- **3D Print and Export STEP for every 3D format, and one filter by type.**
  The STEP prints, the quick filter and the other 3D formats now work together.
  3D Print sends any 3D file SolidSeas reads as 3MF or STL, and as STEP a
  Parasolid file's part (`.x_t`, `.x_b`), written by the same STEP export as a
  SOLIDWORKS part's bodies, exact; every other file asked for as STEP goes as
  3MF and the status line says why (an STL holds triangles, not the exact faces
  a STEP is made of; SolidSeas writes STEP from Parasolid bodies only, so a
  STEP, ACIS or Alibre Design file goes as 3MF too). A
  file goes by what it holds, not its name: a STEP saved as `.SLDPRT` goes as
  3MF for being a STEP, a Parasolid file saved as `.step` as STEP, and the
  progress line names the format it is made in. With Open 3MF and STL Files As
  They Are on, a 3MF asked for as STEP, which goes as 3MF, is opened as it is,
  its slicer project kept, as when 3MF is chosen, and the status line says why
  it is not a STEP; a file whose name says another format than it holds (an STL
  saved as `.3mf`) is never handed over as it is, since the slicer would read it
  by its name, and a STEP is always a new file. File > Export STEP writes a
  Parasolid file's part too; for any other format it is off, and its tooltip
  says why, as it now does for an assembly. `solidseas export part.x_t --format
  step` writes it from the command line, and `export_result.source_format` says
  `parasolid`. The quick filter has a button for every format the folder holds,
  named after its format (ACIS binary and OFF included; ACIS text, which
  SolidSeas lists but does not read yet, on a grey button), and grey buttons
  for the formats SolidSeas lists but cannot read (IGES, Alibre Design drawings
  and packages, Inventor, Solid Edge, Fusion and eDrawings files by kind, 3D
  XML, VRML), offered only while View > Show > Files SolidSeas Cannot Read
  lists them; its tooltip says when SolidSeas cannot read a format, and
  counts a file whose geometry turned out unreadable among those that could not
  be read. It is the list's one filter by type: the type list that sat beside
  the name filter is gone, and a family of formats is several buttons on at
  once. Where Used now shows for a file of another format, to say the index
  holds SOLIDWORKS documents only. The 3D view's cube, Home, the turn about the
  point under the pointer and the camera kept through Back work for every
  format, and the formats self-test checks them and prints each sample as 3MF,
  STL and STEP. The self-test's `--export-step` expects File > Export STEP off,
  its tooltip saying why, for an assembly and for a part of a format the STEP
  export does not write, and fails a part it is off for without a reason.
- **A print says which file it came from when exports of each other sit
  together.** A 3D file of another format whose folder holds a document of the
  same name in another format gets its extension in its print's name,
  `frame (STL) 2026-10-03.3mf` beside `frame.SLDPRT`'s
  `frame 2026-10-03.3mf`, so prints of `frame.SLDPRT`, `frame.step` and
  `frame.stl` no longer share one name and one numbering; the mark counts on
  its own, as `(assembly)` does, and a SOLIDWORKS document keeps its plain name.
- **3D Print sends STEP, or STL, to any slicer that takes it.** Settings > 3D
  Print Program offers Send as 3MF, Send as STL and Send as STEP, only the
  formats the chosen program takes: Bambu Studio, OrcaSlicer and PrusaSlicer
  take all three, UltiMaker Cura 3MF and STL, and any other program you pick
  all three. Preferences shows the same formats beside the program and
  chooses among them. The choice is remembered in `Viewer.ini` with the
  program; switching to a program that does not take the format chosen gives
  it its first, 3MF, and the status line says so. A STEP is the
  part's exact geometry, written as File > Export STEP writes it and named as
  the other prints are, `bracket 2026-10-03.step`, next to the model, with the
  same fallback to the temporary folder and the same `(2)`, `(3)` numbering, a
  format's numbers its own. An assembly, which STEP export does not write yet,
  and a part it refuses (geometry STEP cannot hold without loss, an
  approximation past its 0.001 mm limit, its 300-second or file-size limit,
  nothing to write) are sent as 3MF, and the status line and the result say
  why; a STEP with bodies left out is never sent. A part that stores no bodies
  of the configuration asked for is sent in its active one, as its 3MF is. The
  button and every right-click 3D Print entry use the chosen format. README's
  3D Print section says which formats each slicer documents and which are
  assumed.
- **The self-test checks each print format and File > Export STEP.**
  `--print-format 3mf|stl|step` sends every print of `--print-dry-run` in that
  format and checks each file's extension and, for STEP, the file itself with
  the tests' own independent STEP checker, and that an assembly goes as 3MF
  with its reason; a run that finds no 3D print program, so sends nothing,
  fails rather than passing unchecked, and a STEP print is given the STEP
  export's 300 seconds and its 3MF's time on top. `--export-step` exports each selected part with File >
  Export STEP into a temporary folder and checks it with the same checker, so
  the packaged viewer's STEP export is checked without driving its window from
  outside: the executable now carries that checker for its self-test.
- **The tests can check STEP files against Open CASCADE.** With
  `SOLIDSEAS_OCCT_PYTHON` naming a Python where the `cadquery-ocp` wheel is
  installed, tests marked `occt` have OCCT 7.9.3, an independent kernel, read
  the STEP files SolidSeas writes and the ones it reads; `tests/README.md` says
  how to set it up and run them.
  - **STEP export.** OCCT reads SolidSeas' STEP of every fixture part as
    valid, closed solids, and measures them within 1e-12 of SOLIDWORKS' own
    volume and area. A part with a cavity and a part made only of surfaces,
    built by code, are checked too, the cavity for facing the right way, which
    OCCT alone cannot see.
  - **STEP reader.** SolidSeas' reader is compared with OCCT face by face and
    shell by shell, on synthetic files and on those STEP files. Open solids,
    inside-out shells and folded faces are also looked for as the viewer draws
    a file and as 3D Print tessellates it, at their own coarser settings.
  - **Defects found.** Synthetic files reproduce the reader defects OCCT found:
    voids that come out inside out, and faces dropped because their loops run
    against them. Both are fixed (see Fixed), and OCCT and the reader now agree
    on those files.
  - **Corpus.** With the corpus manifest, the same checks run on private parts
    and STEP files. Parts are exported as File > Export STEP exports them, a
    part of surfaces as its surfaces, and each file is read back by SolidSeas
    too. The STEP files where the reader is known to be wrong are read on every
    run.
  - **Isolation.** OCCT runs only in a child process with a memory cap, a
    timeout and no crash dumps; SolidSeas itself never imports it.
- **Quick filter buttons for document types.** A row of small toggle buttons
  under the list's filter box shows only the types you turn on, as SOLIDWORKS'
  Open Recent dialog does: SOLIDWORKS parts, assemblies and drawings first, then
  every other 3D format the folder holds (listed under 3D Print and Export STEP
  for every 3D format, above, with the grey buttons of the formats SolidSeas
  cannot read), and any other type on a grey badge of its extension, each
  offered only when the folder has a file of
  it. Several at once show all of their types, All turns them off, and they
  narrow the folder tree, the name filter and the index's search like those
  narrow each other.
  Each button draws its own glyph, sharp at any display scaling and in light
  and dark themes, its tooltip counts the files of its type the list would
  show and how many of them could not be read, Tab and Space work them, and the
  row wraps instead of widening the pane. Reload and opening another folder
  keep the row as it was until the folder is listed, so it does not jump or
  lose the keyboard focus; then the types the folder has stay on and the others
  are dropped, though a cancelled listing keeps them all. Opening a file turns
  its type on when it would be hidden, Back restores the buttons, and the types
  on are remembered with the layout. A STEP file saved with a SOLIDWORKS
  extension counts as STEP, and the Type column calls it STEP too. The
  self-test's new `--quick-filter TYPES` turns types on, checks the rows shown
  and the tooltips' counts, saves the window and turns them off.
- **Conversion through SolidSeas' own SOLIDWORKS, on the new bridge**
  (provisional, Windows, `docs/API.md` 3.22). `SolidSeas.SwBridge.exe` is now
  the one program that calls SOLIDWORKS: build it with
  `scripts\build-bridge.ps1` (it needs only Windows and SOLIDWORKS, and
  `build-viewer.ps1 -WithBridge` puts it beside the viewer). It starts a hidden
  SOLIDWORKS of its own inside a Job Object, never attaches to the one you are
  working in, changes none of your SOLIDWORKS options, and every request to it
  has a timeout: a SOLIDWORKS call that never returns, for example behind a
  dialog in the hidden instance, ends that instance after its timeout instead
  of hanging SolidSeas. `python -m solidseas.swapi convert FOLDER -o DIR
  --format step,x_t,stl,3mf` converts parts and assemblies with it, writes
  `report.tsv`, and carries on with a fresh SOLIDWORKS after a document that
  timed out. STEP files now use the application protocol set in your own
  SOLIDWORKS export options (the report says which), because the setting is
  shared with your running session. SOLIDWORKS 2024 does not write glTF
  through its API, and the report says so. `Convert-WithSolidWorks.ps1`, which
  had never run end to end, is gone.
  While it starts, SOLIDWORKS cannot be hidden until it has registered, so for
  6 to 7 seconds its splash screen and window take the foreground, and keys
  you type into your own SOLIDWORKS then go to SolidSeas' instance. A
  conversion you start runs at once and to its end; add `--off-hours` to make
  a long one keep to 02:00 to 07:00, or to the hours you give
  (`--off-hours 22:00-05:30`). It then starts SOLIDWORKS only inside those
  hours and, once they are over, finishes the export in hand, ends its
  SOLIDWORKS and carries on in the next window, so it never runs on into your
  day. That matters most when your SOLIDWORKS is closed overnight: SolidSeas'
  instance is then the first on the machine and holds SOLIDWORKS' journal
  file, so a SOLIDWORKS you started while it ran would work without
  auto-recover. For the same reason, start your SOLIDWORKS before a long
  conversion you run yourself, not during it. The log says how each of
  SolidSeas' SOLIDWORKS instances ended. While your SOLIDWORKS runs, the
  instance also opens a box saying "A journal file could not be created". It
  belongs to SolidSeas' instance, and SolidSeas now hides it, and nothing
  else: no window of your SOLIDWORKS and no other dialog is touched. If the
  box had taken the foreground, Windows hands it on as the box goes, normally
  back to the window you were in. The log says what was hidden. When it is
  done, SolidSeas ends its SOLIDWORKS directly instead of through
  SOLIDWORKS' own shutdown, which rewrote about 230 toolbar and
  CommandManager layout settings that your SOLIDWORKS shares.
  It closes the documents it had open first; they were opened read-only or
  made by it and never saved, so no lock file is left next to your files.
  Conversion writes export formats only, and refuses to replace a file that
  is an open document under another name (a hard link or a junction, which
  SOLIDWORKS would otherwise write straight through). Network paths
  are accepted only for the documents and output folder you name. A timeout
  outside 0 to 86,400 seconds is refused before anything starts.
- **Measuring and importing in SolidSeas' own SOLIDWORKS** (provisional,
  Windows, `docs/API.md` 3.22). The bridge can now measure a document it
  opened or made, in one configuration or all of them: solid and sheet
  bodies, faces, edges and vertices, volume, surface area, centre of mass,
  mass, a precise bounding box of the bodies (an assembly's parts moved into
  place) and the faults SOLIDWORKS' own body check finds, all in metres and
  kilograms. It says when a mass cannot be trusted: a part with only surfaces
  has none, and SOLIDWORKS reported zero volume for some parts from older
  versions that do have a solid. It can also import a STEP file, and IGES and
  Parasolid files the same way, into a new document: into a part made from a
  template you give, through 3D Interconnect, or as File Open does. It changes
  none of your SOLIDWORKS options. It reports the import options in force and
  refuses, before importing anything, STEP assemblies and the imports those
  options would turn into SOLIDWORKS' template dialog, which held a two-body
  STEP import for three hours in an earlier test. The reply says whether the
  result is solids or surfaces, how many bodies, and whether a dialog
  appeared. A dialog that still holds an import, such as the question whether
  to run Import Diagnostics, ends only SolidSeas' SOLIDWORKS, at the
  request's timeout, and the error now names the dialog. Assemblies the
  bridge opens now load their parts fully, so their bodies can be measured.
  Opened that way, still read-only, an assembly was seen to make SOLIDWORKS
  write briefly in its folder: the folder's time changed, and the same files
  were in it before and after. Conversion opens your assemblies where they
  are, so this happens in your folders too. A night's run in SolidSeas' own
  SOLIDWORKS left five issues open, which `src/solidseas/swapi/README.md`
  lists: inserting a STEP of several bodies faults inside SOLIDWORKS,
  SOLIDWORKS' own Open Progress window is reported as a dialog, closing a part
  after the assembly that used it fails, an import that brings in nothing
  still succeeds (its result says `empty`), and a measurement has no accuracy
  setting of its own.
- **The AI connector, `solidseas.ai`** (provisional, `docs/API.md` 3.23,
  `docs/ASSISTANT.md`), the part of the modeling assistant that talks to a
  model. It asks Anthropic, OpenAI, Gemini or a local Ollama server for a
  Review mode draft or an Automatic mode plan, with no SDK: everything is the
  standard library, and `truststore` (the `[ai]` extra, which no longer pulls
  in `httpx` or `keyring`) makes it trust the Windows certificate store when it
  is installed. What leaves your PC is the prompt and nothing else: your
  request, capped at 4,000 characters and with SSNs, EINs, nine-digit numbers
  and card numbers redacted, and a summary of the part by handle (feature
  types, dimensions, faces, edges, planes, the box and the volume), never its
  path, property values, author, material or any name you typed unless you
  allow names for the run. Every reply is checked before anything uses it: a
  plan must use only the ten checked operations, with every value in range and
  carrying its unit, every handle naming exactly one entity, and no protected
  or formula-like property, or the whole plan is refused. Calls are bounded by
  token and, if you set prices, dollar budgets per month and per Automatic
  run, by timeouts and by a Stop that ends a call at once; usage is kept by
  month in `usage.json`. A call that fails after the provider received it
  still counts against the budgets, and two SolidSeas windows asking at once
  cannot both spend what is left of one. API keys go into Windows Credential
  Manager and stay on that PC. An administrator can turn Automatic mode off,
  or allow only a local Ollama server, under
  `HKLM\SOFTWARE\Policies\SolidSeas`; the policy is read on every call and
  every health check, and a key that cannot be read turns every restriction
  on. The assistant's window and its link to SOLIDWORKS come in
  later releases; `start_run`, the one way an Automatic run will start,
  already makes its checks before step 1.
- **A view cube in the 3D view, and Home.** A cube over the view's top-right
  corner turns with the model, as in Fusion 360, labelled with SOLIDWORKS's
  faces: Front looks along -Z, Top along -Y, and its front, top and right
  corner is SOLIDWORKS's isometric, so those seven give exactly what Ctrl+1 to
  Ctrl+7 give. Click any face, edge or corner to look from there, upright and
  fitted; looking at a face square on, arrows beside the cube step to the next
  face, two more roll the view to the next quarter turn (squaring up a view
  rolled part of the way), and dragging the cube turns the model.
  Its house, or the Home key, goes to the view the document opened with, which
  you can change from the cube's right-click menu for that document while the
  viewer runs. The cube's clicks, Home, R, the Isometric button and Ctrl+1 to
  Ctrl+7 now ease the view there in a fraction of a second instead of jumping;
  any other move takes over from wherever it got to, and pressed during a drag
  they act at once. The cube is translucent until you point at it, the legend
  moved down below it, a fit keeps the model clear of it where that costs at
  most a fifth of the model's size, and Settings > View Cube in the 3D View (or
  Preferences) hides it. The self-test's new `--viewcube REGION` (`all` for
  every face, edge and corner), `--pivot NAME` and `--input-checks` click the
  cube, turn about the pointer and try the wheel, the keys and the modifiers as
  a person does, and fail a run where the view does not end where it should;
  `--view-cube on|off` and `--pivot-at pointer|centre` set those two settings
  for a run; and `--configuration NAME` now turns and zooms the view before
  choosing NAME (`NAME,fitted`: a fitted corner view) and fails the run unless
  the camera is kept, or fitted again because it had lost the model.
- **The model turns about the point under the pointer.** A drag that turns the
  model turns it about the point of the model under the pointer where it
  starts, as Fusion 360 and SOLIDWORKS do, so whatever you zoomed in on stays
  put while you turn it; a small blue dot marks the point while you turn. Over
  empty space, or with Settings > Rotation in the 3D View > Turn About the
  Point Under the Pointer off, it turns as before about the point a fit
  centres it on: the middle of the view, or of the part of it the legend or
  the view cube leaves free.
- **Page Up and Page Down roll the model** 15 degrees about the line of sight
  (90 with Shift); a turntable only rolls looking straight down or up. Alt+Left
  stays Back.
- **A sideways touchpad swipe turns the model.** A two-finger swipe across (or
  a tilted wheel) was ignored; it now turns the model as the Left and Right
  keys do, a notch for each 15 degrees, its front following your fingers.
- **3D files of other formats than SOLIDWORKS** (provisional,
  `solidseas.formats`, `docs/API.md` 3.20). One registry knows every 3D format
  SolidSeas reads or lists, and tells a file's format from its content and its
  name, the content winning when they disagree. STL files, binary and ASCII,
  are read today: `solidseas info part.stl` prints a `model_summary` (format,
  units, counts, tree, properties), `props` and `configurations` work on
  them, and `export part.stl --format 3mf` writes them for a slicer, welded
  and checked closed as a SOLIDWORKS part is; the viewer's 3D Print export
  reads them the same way, and the viewer lists and shows them (below). STEP,
  Parasolid, Alibre Design, 3MF, OBJ, PLY, OFF, glTF and AMF files are read
  too (below); IGES, Inventor, Solid Edge, Fusion and the other formats
  SolidSeas knows of are listed but not read (an NX `.prt` is not listed, as
  other programs use that extension too). Commands that only make sense
  for SOLIDWORKS documents answer `not_implemented` for other files, and a
  format SolidSeas knows but cannot read answers the new error code
  `format_not_supported`. Every reader works within one set of limits on
  bytes, counts, nesting, decompressed sizes and time, reads XML without DTDs
  and zip packages without trusting their sizes, and reads a file a document
  names (a glTF buffer, an OBJ material library, an Alibre component) only
  from the document's own folder and under the rules the document was opened
  with: the REST service refuses such a file when it has a second name (a
  hard link), as it refuses the document itself. Where such a file was found
  is said relative to the document's folder, never as a path on the machine.
  A coordinate more than 1,000 km from its object's origin leaves its
  triangles out with a warning, so no export or view ever overflows on one,
  and a time a file stores without a zone is shown as stored, not moved to
  another day.
- **Listing every 3D file in a folder** (provisional). `solidseas list FOLDER
  --formats all` (and `scan(..., formats="all")`, and `/v1/list?formats=all`
  from a service started with `serve --formats`) lists every file of a format
  SolidSeas reads with its format, units and counts, and files of formats
  SolidSeas cannot read yet with the new status `unsupported`, without
  opening them. A listing without
  `formats` is exactly what it was.
- **Previews rendered from the model** (provisional, `solidseas.render`,
  `docs/API.md` 3.21). A 3D file that stores no preview gets one drawn from its
  geometry in pure Python, from the front, right and above, shaded and
  outlined on a transparent background: `solidseas preview part.stl -o
  out.png`, `--render` to draw one even when the file stores a preview, and
  `/v1/preview` from the service. A cache of rendered previews keeps them
  between runs for the viewer.
- **STEP files** (provisional, `solidseas.formats.step`, `docs/API.md`
  3.20.7). AP203, AP214 and AP242 files (`.step`, `.stp`, `.p21`, and a zip
  archive holding one) are read as parts and assemblies: B-rep solids and
  shells are drawn by SolidSeas' own tessellator, faceted and tessellated
  geometry is read as stored, and every occurrence in an assembly is placed
  where the file puts it, with colours, units, the product's name and its
  user-defined properties. `info`, `props`, `preview`, `export --format stl`
  or `3mf` and the viewer's 3D Print export take them, and a folder listing
  shows them as read. On the development corpus all 443 STEP files read and
  99.4 percent of their faces were drawn; a face the tessellator cannot draw
  is left out with its reason, and holes a file stores inside out are turned
  round in the mesh so the solid still closes. A file holding Alibre Design's
  own history (`ALIBRE_SCHEMA`) is refused rather than read as AP203.
- **3MF, OBJ, PLY, OFF, glTF and AMF files** (provisional, `docs/API.md`
  3.20.5). 3MF packages are read to the core specification, with components,
  build items, transforms, units, base materials and colour groups, and the
  parts the root model names are read only from inside the package; OBJ files
  with their groups and the colours of MTL libraries in the file's own folder;
  PLY files in their ASCII and binary encodings, with colours; OFF files in
  their keyword variants; glTF and GLB files with embedded buffers and
  buffers in the file's own folder (Draco and meshopt compression are refused
  with a reason); AMF files plain and zipped, with constellations and colours.
  They are listed, described, previewed, exported to STL or 3MF and sent
  through the viewer's 3D Print export as STL files are. On the development
  corpus all 87 3MF packages and the OBJ file read.
- **Parasolid transmit files** (provisional, `solidseas.formats.xt`,
  `docs/API.md` 3.20.6). `.x_t`, `.x_b`, `.xmt_txt` and `.xmt_bin` files are
  read with the transmit reader and tessellator SOLIDWORKS parts already use:
  a body is a part, and an assembly places its bodies and sub-assemblies by
  their transforms, with body names and colours, and every field of the
  file's header (the application, the last saver, the date) as a property. A
  folder listing reads only the headers. They are listed, described,
  previewed, exported to STL or 3MF and sent through the viewer's 3D Print
  export, and `bodies()` gives each body as a transmit of its own. A transmit
  of a newer schema that does not embed it, one with user fields and a deltas
  file are refused with their reasons.
- **Alibre Design parts and assemblies, without Alibre** (provisional,
  `solidseas.formats.alibre`, `docs/API.md` 3.20.8). `.AD_PRT` and `.AD_ASM`
  files are read in pure Python, with no Alibre program installed: a part's
  properties, active configuration, colour and stored thumbnail, and its
  exact ACIS body, which SolidSeas maps to a Parasolid body and tessellates
  closed for exports and 3D Print. Rendered previews and thumbnails use
  Alibre's own display mesh, and so does the viewer's 3D view. An assembly
  finds its components in its own folder by the identity each Alibre file
  stores, reading only that small stream of each file, and places them; the
  unit of those placements (centimetres) comes from a single sample assembly
  and is warned as unconfirmed. Everything was verified on the files of one
  Alibre release, whose ACIS data is version 2100. Standalone ACIS
  `.sab` files of the version Alibre writes are read too. On the sample parts
  every face was drawn, closed and facing the way Alibre's own display mesh
  faces. Other ACIS versions, SAT text, Alibre drawings and packages are not
  read.
- **Every 3D format in the viewer.** The viewer lists every 3D file SolidSeas
  reads beside the SOLIDWORKS documents of the folder you open (View > Show >
  All 3D Files, on): STEP, Parasolid, STL, 3MF, OBJ, PLY, OFF, glTF, AMF, ACIS
  and Alibre Design files, each with its format in the Type column (`STEP
  assembly`, `Alibre part`), its schema, variant or the program that wrote it
  under Saved with, and a thumbnail: the image the file stores (3MF, Alibre
  Design), else one drawn from its geometry in the background and kept in a
  cache for next time. The quick filter's buttons show each format on its own,
  or a family with several on at once, File > Open File... opens any of them,
  and View > Show > Files SolidSeas Cannot Read lists IGES, Inventor and the
  other formats SolidSeas recognises but cannot read yet, greyed and never
  opened.
  - The details fit the format: the Overview gives the format and its schema
    or variant, the units (marked when the file states none and millimetres are
    assumed), the program that wrote it, the objects, bodies, faces, triangles
    and vertices, and the size and box of the model; the Preview tab shows the
    stored image or one drawn from the geometry; then Properties, Raw JSON and,
    for an assembly (STEP, 3MF, glTF, AMF, Parasolid, Alibre Design), the
    Components tab with each instance's position and the objects or files it
    uses. An Alibre assembly's References tab says where each component file
    was found, by its document GUID; Open file goes there and Back returns.
    BOM and Paths, which are about SOLIDWORKS documents, are hidden, and Where
    Used says the file is not indexed: the index holds SOLIDWORKS documents only.
  - The 3D view draws them, a mesh format that stands on Z turned upright, and
    an assembly as its components: a click picks one and its row, the Explode
    bar moves them apart, and Hide, Isolate and Transparency work as for a
    SOLIDWORKS assembly. A STEP part placed twice is two part rows, and a
    glTF node's rotation reads as the same scene in 3MF reads; an object
    inside the file has no Open file, and nothing says a double-click opens
    one. A file listed as read whose geometry then turns out unreadable is
    marked Geometry not readable in the list.
  - File > Export for 3D Printing... writes the part or assembly shown as STL
    or 3MF into a folder you choose, and 3D Print sends any of them to your
    slicer, saved next to the model as before. With Settings > Open 3MF and
    STL Files As They Are turned on (it is off unless you turn it on), a 3MF
    or STL file your program takes is opened as it is, with nothing written,
    so a slicer project keeps its plates; the slicer then has your own file
    open, and saving there replaces it. Export Preview Image writes the stored
    or drawn preview. A file holding only open surfaces says so rather than
    that it holds no triangles.
  - A format SolidSeas cannot read, or a feature of a file it lacks (a 3MF
    extension, Draco compression, a Parasolid schema the file does not carry,
    Alibre Design's own database in a STEP-like file), is said in plain words.
  - None of these files is read in the window's own process (a compound file
    wearing a SOLIDWORKS extension, such as a renamed Alibre file, is read as
    the SOLIDWORKS document its name says, as before): the listing, the
    details and the thumbnails come from two worker processes of the viewer's,
    below normal priority and with a memory limit, started the first time such
    a file is listed; the 3D view comes from the mesh process and the exports
    from the export's process. What they send back is JSON, PNG images SolidSeas
    wrote and vertex buffers, never a pickle: the mesh process and the export's
    process now answer in JSON for SOLIDWORKS documents too.
  - `SolidSeasViewer --self-test-formats --3d --screenshot-dir DIR` writes a
    synthetic file of every format into a temporary folder of its own and
    checks that each lists, previews, shows its details, draws in 3D (its
    pixels read back, an assembly picked, exploded and hidden) and exports to
    STL and 3MF.
- **A catalog of your project folders, and where-used** (provisional,
  `solidseas.catalog`, `docs/API.md` 3.18). `solidseas index FOLDER` builds an
  index of every SOLIDWORKS document below a folder (and any library folders)
  in SQLite, in your cache folder: each document's type, saved version,
  configurations, custom properties, part numbers and descriptions, preview,
  SHA-256, the files it references and how each resolves, and an assembly's
  quantities per configuration. Running it again reads only what changed: an
  unchanged file is never opened, a renamed or moved folder is followed by its
  files' ids instead of being read again (a renamed part's part number and
  search words follow its new name), and a file OneDrive frees to an
  online-only placeholder keeps what was read of it. A run that is stopped or
  killed loses nothing: the next one picks up the files still to read and the
  references still to resolve. Documents are read in worker processes below
  normal priority, and nothing is written into the folders you index unless
  you ask for the catalog to live there (`--in-project`), where a link planted
  in its `.solidseas` folder is refused. A damaged catalog in your cache folder
  is made again by the next `index`.
  - `solidseas where-used FILE` lists the assemblies that use a part or a
    sub-assembly, directly or through sub-assemblies, with the quantity in each
    configuration (unsuppressed and in the BOM too), the drawings that show it
    or an assembly that holds it, and references that may name it, without
    opening any file. Where a sub-assembly is missing or cannot be read, the
    top assembly's own tree still counts what is inside it, and the answer says
    when some assemblies or drawings could not be read. However a file's trees
    branch, the answer comes back in bounded time.
  - `search` finds documents by name, part number, description or any property
    value, with filters such as `type:part`, `pn:`, `prop:Vendor=ACME` and
    `changed:7d` (an argument with spaces is one value: `"desc:steel
    bracket"`); `duplicates` lists files with identical contents; `missing`
    lists references that resolve to nothing in the indexed folders; `changes`
    lists what was added, changed, moved and removed; `catalog`, `catalogs` and
    `clear-index` show and delete catalogs.
  - `solidseas serve --catalog` keeps a catalog of the service's roots, read
    by two workers of its own below normal priority so scans and requests never
    wait for each other, and answers `/v1/catalog`, `/v1/where-used` and
    `/v1/search` from it; a where-used answer too large for one response lists
    the nearest users and says it was cut.
  - On the development corpus (3,527 documents) the first index took 18 s and
    one with nothing changed 2.3 s, the catalog took 2.9 MB per 1,000
    documents and its previews 19 MB, and its reference resolution agreed with
    a live resolution for all 4,844 references.
- **Where Used in the viewer.** The viewer indexes each folder you open in the
  background, in a process of its own (the status bar shows how far it got),
  and the new Where Used tab shows which assemblies and drawings in the folder
  use the selected document, with quantities per configuration; a row opens
  its document, and Back returns. Once the folder is indexed, the name filter
  also finds documents by part number, description or property value.
  Settings > Index Opened Folders turns indexing off, and Settings > Clear
  Index deletes the opened folder's index.
- `WorkerPool(priority="below_normal")` runs a pool's workers below normal
  priority, and the walker's file entries carry a `file_id` where the listing
  gives one (Linux and macOS).
- **3D Print from a right-click, in SolidSeas Viewer.** Right-click a part or an
  assembly in the document list (details or icons) for 3D Print; a row of the
  Components tab (an instance or a file), of the BOM tab or of the References
  tab prints that row's file in the configuration the row uses, a drawing's
  views and models print their model (a view in the configuration it shows),
  and a file in the 3D view's legend prints that file. In the 3D view,
  right-clicking a component offers 3D Print Part for the part under the
  pointer, in its instance's configuration, and 3D Print Sub-assembly for each
  sub-assembly it is in, nearest first; empty space offers 3D Print This
  Assembly, in the configuration shown, and a part's view offers 3D Print This
  Part. Each goes through the same export, program and Cancel as the toolbar
  button: while an export runs, each menu has one Cancel 3D Print in their
  place. A virtual component prints from inside the assembly that stores it, or
  from inside the sub-assembly that does; a part the 3D view read from a
  sub-assembly's own file, which has no row on the Components tab, prints from
  the file its mesh came from. A component whose file was not found has its
  entry greyed with the reason, its tooltip giving the stored path. The
  self-test's `--print-row NAME` and `--print-view NAME[,sub]` (or
  `--print-view .`) print through these menus in its dry run, right-clicking
  the 3D view itself when it is drawn.
- **STEP export without SOLIDWORKS.** `solidseas.step` writes a part's
  Parasolid bodies as an ISO 10303-21 file in AP214, the exact B-rep, with the
  units, labels and product values SOLIDWORKS writes in its own (AP203) STEP
  of the box fixture, in AP214 form: `solidseas export FILE --format step` and
  `export_document(doc, path, "step")`. Its solid bodies are written, but for
  those SOLIDWORKS hides, which its own STEP leaves out too (see Fixed;
  `--include-hidden` writes them); surface bodies with `--sheets`; wire bodies
  never. A face that goes all the way round a hole or a shaft is cut in two at
  its seams, as SOLIDWORKS cuts it (see Fixed). Planes, cylinders, cones,
  spheres, tori, B-spline, swept, spun and offset surfaces, lines, circles,
  ellipses, B-curves and SP-curves on planes or along iso-lines are written
  exactly. Intersection curves, other SP-curves and rolling blends, which STEP
  cannot hold exactly, are written as B-splines refined onto the true geometry
  and measured against it along every span, at most 0.001 mm off (0.0001 mm
  aimed for), and the file's uncertainty covers the largest deviation. A blend
  that goes all the way round a closed spine is written as a surface that
  closes on itself. A body that cannot be written within that is never written
  broken: the export refuses with `not_representable` (exit 1), naming each
  body and why, and `--allow-partial` leaves such bodies out whole, says so in
  the file's header and exits 4. Every body passes its own checks before
  anything is written (loops closed, every edge used twice, once each way,
  every vertex on its curves and surfaces, every edge on the right arc and
  lying on its faces along its whole length), and tests re-read each file with
  a Part 21 reader and a topology and geometry checker of their own. The box
  fixture's STEP matches SOLIDWORKS' own STEP of it entity by entity, the
  curved fixture o11 converts exactly, and of a sample of 400 corpus parts the
  export writes 356, refuses 20 naming each body and why, finds nothing to
  export in 21 (surfaces only, or no stored bodies) and stops 3 at the 300 s
  limit, with the numbers in `docs/FORMAT.md` 10.9 (the corpus test
  `test_corpus_step` measures them again). SOLIDWORKS reads the files back as
  the parts: imported into SOLIDWORKS 2024, the export of 12 fixture parts
  comes back exact, and that of the 130 corpus parts that came back as solids
  within 1.7e-4 of their volume, 7.5e-15 at the median. The mapper is adapted
  from sldprt2step's (Apache-2.0, credited in `NOTICE`), with its lemon torus and
  spun surface orientation corrected. Assemblies and colours are not written
  yet. The API is provisional (`docs/API.md` 3.19).
- **SolidSeas Viewer exports STEP.** File > Export STEP, beside Export
  Parasolid, writes the part shown, in the configuration shown, to a STEP file
  you choose outside the opened folder. It runs in the export's own process,
  as 3D Print does, with a progress dialog whose Cancel ends it at once and
  leaves no file behind. When a body cannot be written without loss the viewer
  names it and why, and asks whether to write the file without it; the result
  says whether the file is exact or how far its approximations are from the
  geometry, and names the bodies not written and why. A part of surface bodies
  only is written as its surfaces. A name typed without an extension gets
  `.step`, and a file of that name is replaced only after asking.
- **Bills of materials, as SOLIDWORKS makes them.** `Document.bom()`, the
  `solidseas bom` command and the service's `/v1/bom` give an assembly
  configuration's BOM, top-level only (the default, as in SOLIDWORKS), parts
  only or indented, for ERP and invoicing. Rows are grouped, counted and
  numbered as SOLIDWORKS' own BOM tables: one row per file and configuration
  under each parent, in the order the assembly stores its components,
  suppressed and excluded components (and everything inside an excluded
  sub-assembly) left out, and `3.1`, `3.2` under a sub-assembly's item `3`.
  PART NUMBER is the document name, as SOLIDWORKS shows it by default, and
  DESCRIPTION the component's `Description` property in the configuration the
  assembly uses; ask for more property columns with `--column`, or take the
  part number from a property of your own with `--part-number-property`. For
  the test assembly o16 both tables match, cell by cell, the ones SOLIDWORKS
  put on its drawing o19, the virtual part, the sub-assembly and a part used in
  another configuration included. Each component file is found the way
  `references --resolve` finds it and read for its properties only; one that
  cannot be found or read keeps its row, with what the assembly knows and a
  note saying why, and the command then exits 4. A component configuration can
  tell SOLIDWORKS to show its configuration name or a typed name as the part
  number instead; where SolidSeas cannot yet tell whether it does, the row
  keeps the document name, gives the stored name (`ALTERNATE NAME` in the CSV)
  and says so in a note, and the BOM counts as incomplete. Each row also gives
  the total quantity in the whole assembly, the file, its configuration, where
  it was found and every property, and a BOM exports as CSV (UTF-8 with a byte
  order mark, so Excel reads accented and Cyrillic names, and formulas from a
  file never run) or as the `bom` JSON. A mistyped `--path-map` or a `--root`
  folder that does not exist stops the command with an error, as it stops
  `references`; `-o` never writes into a folder the BOM read files from
  (unless you pass `--allow-source-dir`); and
  the text table shows a line break inside a value as `\r\n`, so every row
  keeps to its line. On the development corpus all 325 assemblies' BOMs take
  about 17 s in all, with at most 3 files open at once, their quantities add
  up to the component trees' counts, and 91% of the rows find and read their
  file. The Python API, the `bom` kind and the route are provisional while
  BOMs are new.
- **SolidSeas Viewer has a BOM tab.** An assembly's bill of materials, top-level
  only, parts only or indented, as SOLIDWORKS draws it, in the configuration the
  Components tab shows (choosing one on either tab changes both). Each row goes
  to its file on a double-click, as an instance does, and says where its file
  was found or why it was not read. Export BOM, on the tab and in the File
  menu, writes the BOM shown as CSV or JSON into a folder you choose, under the
  same rules as the other exports; while another configuration's BOM is being
  read, or after it could not be read, there is nothing to export.
- **3D Print in SolidSeas Viewer.** Select a part or an assembly and press 3D
  Print (toolbar, File menu, Ctrl+P): the viewer exports it in the
  configuration shown and opens it in your slicer. The first time it uses
  Bambu Studio when installed, and otherwise asks; Settings > 3D Print Program
  lists the slicers found on this computer (Bambu Studio, OrcaSlicer,
  PrusaSlicer, UltiMaker Cura, from their install folders and the registry's
  App Paths, which are only read), lets you pick any other program file, and
  chooses the format from those the program takes: 3MF, STL or STEP (see 3D
  Print sends STEP above; UltiMaker Cura takes 3MF and STL). The choice is
  kept in `Viewer.ini` and shown in Preferences. The file (`.3mf`, `.stl` or
  `.step`) is saved in the folder of the part or assembly it was made from (a
  virtual component's: the assembly or sub-assembly that stores it; a
  component found outside the folder you opened, on a drive of this computer:
  next to its own file there), named after the document and today's date, `bracket 2026-10-03.3mf`, with
  the configuration exported when it is not the active one, `frame (Lite)
  2026-10-03.3mf`, and `(assembly)` after an assembly that has a part of the
  same name beside it. A second print the same day is `bracket 2026-10-03
  (2).3mf`, then `(3)`, always one past the highest number of that name and
  format there, so the highest number is the newest; a file that is there is
  never replaced, renamed or opened, and two prints at once never take one
  name. The status line gives the file's full path and says it was opened in
  the slicer. Where the model's folder cannot take the file (read-only,
  permission denied, a link or a junction there or above it, a cloud
  placeholder, a network share or drive outside the folder you opened, a
  device or stream path), or when Settings > Save 3D Print Files Next to the
  Model is off (also in Preferences, on by default, kept in `Viewer.ini`), it
  goes to a folder of your own in the system's temporary folder, and the
  status line says why; exports older than a week are removed from there, and
  only from there. The export runs in a process of its own, so the viewer
  keeps working, and while it runs the button reads Cancel 3D Print: pressing
  it, or closing the viewer, stops the export, removes its unfinished file and
  sends nothing; one left by a viewer that ended while writing it is removed
  by the next 3D Print. The program gets the file as its one argument, with no
  shell, and without the settings the packaged viewer made for itself (its DLL
  folder and Qt plugins, which a program built on Qt, such as Cura, could
  otherwise find first). A missing program, a program that has gone and a
  failed export each get a plain message, and the first time Bambu Studio is
  chosen for you the status line says so with the result. The self-test's
  `--print-dry-run` presses 3D Print twice for each selected document, exports
  as the button does and reports the program and arguments it would start,
  without starting anything; it writes its print files next to the models in
  the folder under test (so run it on a copy), never next to one outside it,
  and checks the folder, the name, the date and the `(2)`.
- **STL and 3MF exports for 3D printing, from Python and the command line.**
  `solidseas.export` (provisional, `docs/API.md` section 3.17) and `solidseas
  export FILE --format 3mf|stl [-o FILE] [--configuration NAME] [--chord MM]
  [--merge]` write a part from its solid bodies, tessellated at a print chord
  (a quarter of the 3D view's tolerance, never coarser than 0.01 mm), and an
  assembly from its placed instances: a 3MF with one object per component file
  and a build item per instance (or one merged object), or a binary STL, in
  millimetres. Every object is checked to be closed and consistently oriented,
  each edge used twice, once each way. Slicers read coordinates as float32, so
  a triangle's corners float32 cannot tell apart are merged, and a sliver
  float32 shows flat has its long edge flipped, rather than written as a
  triangle with no area for the slicer to repair; a 3MF's numbers read back
  exactly. A part with no solid body falls back to its saved
  display mesh, labelled and with a warning that it may not be closed, and so
  does an assembly's component whose file is not found; a part of surfaces
  only is left out and said to be one. A file is only ever created new, never
  through a link, a device such as `nul .x.3mf` or a stream; `--force`
  replaces one through a new file renamed over it, and `-o` names a file with
  the format's extension or a folder that exists. On the fixtures, o02's
  exports match SOLIDWORKS' own STL and 3MF to 1e-9 in box, volume and area,
  every part has SOLIDWORKS' volume and area, and the assemblies place every
  instance on SOLIDWORKS' box and add up to their mass properties. The JSON
  kind `export_result` and the error code `nothing_to_export` come with it.
- `display_geometry` takes `brep_options` (how the `brep` source tessellates:
  chord, angle, body types, the time a part may take) and `keep_welded`
  (each brep mesh keeps its shared-vertex triangles), and a brep
  `MeshSource` has its `chord_m`; the tessellator takes `chord_fraction` and
  `max_chord_m` for its automatic chord. An instance whose part's bodies are
  all of types not asked for is skipped as `bodies_not_asked`, and a part's
  failed bodies are reported rather than a later source's missing display
  mesh. All provisional.
- **SolidSeas Viewer can make a component see-through, hide it or isolate it.**
  To look at the parts inside a housing, right-click the housing in an
  assembly's 3D view and choose Transparency (Opaque, 25, 50, 75 or 90
  percent); choose Opaque to put it back. The same menu has Hide, Isolate
  (hide everything else), Show all and Reset appearance, and a part's menu
  has them for each sub-assembly it is in too. A row of the Components tab, a
  file of the Files table and a file of the legend (every instance of that
  file, and for a sub-assembly's file every part of every instance of it)
  offer the same, greyed with the reason where the view draws none of it, and
  right-clicking empty space in the view offers Show all and Reset
  appearance. Choosing a look lets go of the pick the right-click made, so the
  rest of the assembly is not drawn faded round it. The latest choice that
  covers a component decides how it looks. A transparent component is drawn
  after the opaque ones together with the grey boxes for missing meshes, each
  blended over what is behind it, its far side placed at the far end of its
  bounding box and its near side at the near end, farthest first: a part
  inside a see-through housing shows between the housing's two walls from any
  side, and a box's edges show through a transparent part in front of them;
  a grey box made transparent fades its edges with its faces.
  It can still be picked and right-clicked: as with a box, it ranks at the far
  side of its bounding box, so a click goes through it to anything within that
  box or in front of it. A hidden one is neither drawn nor picked, the view
  fits what is shown, and the exploded view spreads only what is shown; with
  everything hidden the view says so. The Components tab greys the rows of
  hidden instances with an eye struck through and marks transparent ones, and
  the legend greys a file that is all hidden. The choices last while the
  document is shown, through explodes, picks, configuration switches (for the
  components still there) and Back, on both drawing paths. The self-test
  takes `--transparent NAME[,PERCENT]`, `--hide NAME` and `--isolate NAME`,
  checks what is drawn by reading pixels back, and fails the run unless Reset
  appearance then gives the first picture back pixel for pixel. On 60
  assemblies of the development corpus that have sub-assemblies (up to 710
  instances, 18 of them with grey boxes), a frame with half the instances
  transparent, turning, took 0.6 ms at the median and 6.0 ms at most (6.3 ms
  drawing one instance at a time), against 0.5 and 1.7 ms all opaque (3.6 ms
  one at a time); sorting them took 0.02 ms at the median and 0.8 ms at most.
  With nothing transparent the grey boxes need no sort, and are drawn as
  before, in one call for all of them where the graphics driver draws
  instances.
- **You choose which sub-assemblies explode.** Right-click a part of a
  sub-assembly in the 3D view, or the sub-assembly's row on the Components tab,
  for a check item that explodes it or keeps it together whatever the Explode
  bar's level says: a connector panel can spread out while the circuit board
  assembly next to it moves as one piece. The bar's level is the default for
  every sub-assembly you have not chosen for, and a nested sub-assembly has a
  switch of its own: switched on inside one that stays together only by the
  bar's level, it is pulled out of that one, whose rest moves as one piece;
  inside one you switched off, it moves with that one, and its switch is
  greyed and names it. The bar counts the groups as your choices make them
  and names the choices that hold in the configuration shown. They hold for
  the document while the viewer runs, through configuration switches and
  Back, until Reset appearance. Parts still inside one another when fully
  exploded are parted as before, and the view keeps the whole assembly in
  sight. On those 60 corpus assemblies, 4,872 combinations of switches on each
  drawing path (every one for up to six sub-assemblies, at both levels, with
  and without half the parts hidden) drew without an error and grouped as
  they should; a change took 0.5 ms at the median and up to 104 ms on the
  largest (87 ms drawing one instance at a time; an earlier run gave 93 and
  97 ms), as the offsets are worked out again on the window's thread. The
  self-test takes `--explode-sub NAME,on|off` for a sub-assembly and checks
  where each part is drawn.
- **Parts saved without a display mesh are drawn from their own geometry.**
  Every part keeps its bodies as a Parasolid B-rep, and the new
  `solidseas.tessellate` (provisional, `docs/API.md` 3.15) turns them into
  triangles, in pure Python: each edge is sampled once for both of its faces,
  so solids come out closed, and curved faces are refined until the triangles
  keep within a chord tolerance (by default a thousandth of the part's size).
  `Document.tessellate()` gives a part's triangles with outward normals, and
  `Tessellation.welded()` the shared-vertex mesh STL and 3MF want. On the
  fixtures the volume, area, box and centre of mass match what SOLIDWORKS
  reported (planar parts exactly, curved ones to 0.13 percent), and SOLIDWORKS'
  own STL, 3MF and Parasolid exports agree. `display_geometry` uses it as a
  fifth, last mesh source, `brep`, for parts that store no display mesh
  anywhere, so the 3D view of an assembly draws them as they are instead of as
  grey boxes: on the development corpus 96 percent of the part instances to
  show are now drawn from a mesh, up from 81 percent, and the boxes drop from
  1,280 to 245. A part with no display mesh, opened on its own in SolidSeas
  Viewer, is drawn from its bodies too, and the line under the view says so;
  bodies over the triangle limit are refused as a large saved mesh is, and a
  virtual part whose assembly keeps a mesh of it over the limit now says that,
  where it said it had no mesh. Faces
  on BLENDED_EDGE surfaces (rolling blends) are drawn from the surface the STEP
  export writes for them, within a time limit (see Fixed); the parts without a
  display mesh on the corpus have none.
  Solids stay closed where boundary points lie in a line, where a face is
  thinner than the tolerance and where a B-spline surface narrows to a point,
  so 1,733 of the 1,754 solids of those parts come out watertight; triangles
  along a curved boundary keep to the surface instead of standing up off it or
  facing back, and the normals at the tip of a B-spline dome are smooth.
  Alongside it, `Document.parasolid()` takes `configurations` (the
  configuration ids to read, and no others) and `max_total_bytes` (a cap over
  every stream it decompresses), and
  its result's new `bytes_inflated` says how much it decompressed.
  `display_geometry` (provisional) takes `max_brep_seconds` (60 seconds over
  the call by default; a part gets 30, reading its bodies included, and the
  call can run past the limit by one part's read), counts
  `meshes_tessellated` and `brep_seconds`, gives the skip reasons
  `brep_failed` and `max_brep_seconds`, and warns `brep_faces_skipped`,
  `brep_bodies_skipped` and `brep_not_closed` on a mesh it made. Because the
  `brep` source is in the default order, a call on an assembly whose parts
  store no display mesh now opens and tessellates those parts: on the
  development corpus the slowest call took 32 seconds where it took 3.5, and
  the median went from 0.067 to 0.082 seconds. `sources=geometry.SOURCES[:4]`
  keeps the stored meshes alone, as before.
- **The 3D view turns freely, to any view, as SOLIDWORKS does.** It used to
  turn only like a turntable: about the model's Y axis, tilting no further than
  straight above or below and never rolling, so a model whose natural up is not
  Y turned about a line slanting across the screen, and views from past
  straight above or below, or upside down, could not be reached. Free rotation,
  now the default, turns the model about the screen's own axes: a drag across
  about the screen's vertical axis, a drag up or down about its horizontal
  axis, with no limit, and the arrow keys the same way, 15 degrees at a time
  (90 with Shift). Settings > Rotation in the 3D View and Preferences choose
  Free or Turntable, which turns by the same yaw and pitch as before (only the
  point it turns about is new, as under Fixed); choosing Turntable sets a
  view turned upside down upright again, from the same side. The standard
  views (Ctrl+1 to Ctrl+7, R) are the same in both, the help under the view
  says how the chosen mode turns, Back puts back a free view upside down
  included, and the choice is kept in `Viewer.ini`. The self-test takes
  `--rotation free` or `--rotation turntable` and turns each 3D view over the
  top, failing the run unless free rotation goes past straight above with the
  model still drawn, or the turntable stops there.
- **Clients can check the service before they send their token.** While the
  service is stopped, any program on the machine can listen on its port and
  collect the token a client sends (security review finding 15). The new route
  `GET /v1/identity?client=NAME&nonce=NONCE` needs no token and answers with an
  HMAC-SHA256, under that client's token, of the client's fresh nonce and of
  the address and port the connection reached. A client computes the same and
  sends its token only on a match, so neither a program that took the port, nor
  one that replays an earlier answer or forwards the question to the real service
  from another address or port, ever receives it. `docs/API.md` 8.16 explains
  it, with clients in Python, curl, PowerShell and TypeScript. A check covers
  only the connection it was made on, so a client sends its token on the
  checked connection alone: the TypeScript client of 10.1, and the store recipe
  of 10.4 through it, now send each request on a new connection that they
  check first and close after, with Node's `node:http` instead of `fetch`,
  whose pool could reuse a connection another program accepted while the
  service was stopped. The PowerShell example passes `-DisableKeepAlive` for
  the same reason. A name the token file does not hold gets a proof that looks
  like a real one and, like it, stays the same across restarts while the file
  does. Because the route answers anyone, it also lets anyone test guesses at a
  token offline: make every token with `secrets.token_urlsafe(32)`, as the
  service makes the first one (8.3). The route comes with a new JSON kind,
  `identity`; `solidseas.serve.identity_proof` computes the proof in Python
  (provisional). A client that does not check is as exposed as before.
- **SolidSeas Viewer draws a box where an assembly's component has no mesh.**
  A component whose file is not found, or that stores no display data, left a
  hole in the 3D view, often a whole sub-assembly. It is now drawn as the box
  SOLIDWORKS stored for it in the assembly, in translucent grey with dark
  edges, so it never passes for real geometry: on the development corpus,
  1,306 of the 1,332 instances still without a mesh. A box explodes,
  picks, opens its file through its row on the Components tab, and comes back
  with Back like any other component; hovering over one says it has no mesh
  and why. The legend's last row stands for the boxes and picks them all, and
  the line under the view counts them by reason, keeping its names for the
  components not drawn at all. Settings > Boxes for Missing Meshes (also in
  Preferences, kept in `Viewer.ini`) turns them off. A box in front of a
  component is picked where it covers it, and a component inside a box is
  picked through it. A stored box no model could have (more than 10 km from
  the origin, or far outside the assembly's own box) is taken as damaged and
  not drawn, so it cannot take the camera away from the model; the line under
  the view says so. The self-test's new `--boxes` fails a run where a
  component with a box is not drawn as one, and counts a box too small to
  cover a pixel without failing.
- **SolidSeas Viewer picks the parts read from a sub-assembly's own file.**
  They have no row on the Components tab: clicking one picks it without
  selecting a row, the note names the sub-assembly whose row stands for it, a
  double-click or the right-click menu opens that sub-assembly, and Back puts
  the pick back. The self-test's `--pick` checks such a part too, and its
  report names the row that stands for it.
- **`display_geometry` reads a sub-assembly's own meshes.** For a part inside
  a sub-assembly that the top assembly keeps no mesh of, the new `subassembly`
  source looks in the sub-assembly's own file (on disk, or stored inside the
  assembly), at any depth, with the same rules for configurations as the top
  assembly's meshes, and goes on to the next sub-assembly down when one holds
  no usable mesh. It is the last of the default `sources`, after the part's
  own file, so a tight `max_files` goes to part files first.
- **A box for each component that cannot be drawn.** Each `SkippedInstance`
  now carries its `placement` and the `box` its assembly stores for that
  component (in the component's own coordinates), and
  `DisplayGeometry.placeholder()` places that box in the assembly. On the test
  files it is exactly SOLIDWORKS' box of the component; on the development
  corpus 1,306 of the 1,332 components still not drawn have one, and
  SolidSeas Viewer draws them (above).
- **The mouse's Back button goes back in SolidSeas Viewer.** The thumb button
  most mice have, and a keyboard's Back key, now do what Alt+Left does,
  wherever the pointer is.
- **`display_geometry` bounds the triangles drawn.** The new
  `max_triangles_drawn` (default 1,000,000,000) counts each placed instance's
  triangles; an instance past it is skipped with the new reason `max_drawn`.
  Provisional, like the rest of `solidseas.geometry`.
- **SolidSeas Viewer: pick a component in the 3D view.** Click a component of
  an assembly in 3D to pick it: it turns a selection blue while the others
  fade, a note in the corner of the view names it, and the Components tab
  selects its row. Selecting a row there picks it in the view, a
  sub-assembly's row all its parts and a row of the Files table every instance
  of that file. Double-click a component to open its file, just as
  double-clicking its row does; right-click it for Open file, Show in folder
  list and Show on Components tab; hover over it to see its name; Esc or a
  click on empty space lets go. Picking works on an exploded assembly too, the
  pick stays while you switch configurations, and Back now also puts back how
  far the assembly was exploded. The self-test's new `--pick NAME` clicks an
  instance in the view, opens its file and comes back, then turns the view
  back as it was, so a later pick does not fail because Back left the view
  zoomed in on the one before.
- **SolidSeas Viewer: an exploded view of an assembly.** In 3D, an assembly
  now has an Explode bar: drag its slider and the components ease apart, away
  from the assembly's centre, each twice as far out at 100 percent, either each
  top-level component as one (a sub-assembly keeps its parts together) or every
  part on its own. Components at the very centre slide apart along the
  assembly's longest side, the largest staying put. Collapse brings everything
  back. The view keeps the whole assembly in sight while it moves, unless you
  have turned or zoomed it. The explode is the viewer's own and changes
  nothing: SOLIDWORKS' saved exploded views are not read, because where the
  file keeps their steps is not decoded yet (`docs/FORMAT.md` 12.6 has what was
  found). The amount stays while you switch configurations; the next document
  starts collapsed. The self-test's new `--explode PERCENT[,parts]` saves the
  exploded view of the assembly selected before it.
- **SolidSeas Viewer: assemblies in 3D.** With Interactive 3D View on, an
  assembly is now drawn on the Preview tab too, from the meshes SOLIDWORKS
  saved of its components: from the assembly itself where it keeps them (it
  does for most components, in older versions as well as 2023 and 2024), and
  otherwise from each component's own file, found in the folder you opened as
  the References tab finds it. Each component file is read once and drawn for
  every instance of it, in a colour of its own; the Legend button shows or
  hides which colour is which file. It turns, pans, zooms and fits like a part,
  with the same mouse styles and keys, and fits the whole assembly. The bar has
  the assembly's configurations, and that list is the Components tab's:
  choosing one in either shows it in both. A line under the view names the
  instances that could not be shown and why (a file not found, a component
  saved without a display mesh, the triangle limit), and the triangle limit now
  counts every component file's mesh once over the whole assembly, so a large
  assembly is drawn as far as the limit goes, and raising the limit draws the
  rest. On the development corpus every assembly fits under the default limit,
  takes 0.08 s to read at the median and 3.1 s at most, and draws in at most
  about 2 ms a frame. Drawings still show their stored image. The self-test's
  `--3d` now draws assemblies, and `--configuration NAME` draws the one
  selected before it in another configuration as well.
- **An assembly's display geometry in the library**, provisional:
  `solidseas.geometry.display_geometry(doc, configuration, roots=...)`, and
  `Document.display_geometry()`, give every part instance SOLIDWORKS would
  show, placed in the assembly, with one mesh per component file that all its
  instances share, and every instance that could not be placed or meshed with
  the reason. Each instance's box matches the one SOLIDWORKS reports for it on
  the test assemblies, rotated parts, a turned sub-assembly and another
  configuration included. The reads are bounded (instances, files opened,
  triangles and bytes read), nothing is written, and a component that cannot
  be read is reported rather than raised. `docs/API.md` 3.14 describes it, and
  `docs/FORMAT.md` 12.3 the two places an assembly keeps its components' meshes.
- `solidseas references --resolve --no-outside-roots` resolves the way the REST
  service does, never looking outside the given roots, so a command line run
  can reproduce a service answer.
- `resolve_references(..., skip_unavailable_roots=True)`, `WorkerPool(log=...)`,
  `WorkerPool.alive()` and a per-call `max_result_bytes`, all provisional.
- **SolidSeas Viewer: open a component's file from an assembly or a drawing,
  and go back.** Double-click an instance on the Components tab, a row of the
  Files table, a drawing's view or model, or a file on the References tab, to go
  to that file; right-click for Open file and Show in folder list. The viewer
  goes where reference resolution found the file in the folder you opened (or at
  its stored path on a drive of this computer). A file in the list is selected
  there, widening the folder tree and the name filter only as far as needed; a
  part opens on its Preview tab, and an assembly on its Components tab in the
  configuration the instance uses. A file found outside the opened folder, and a
  virtual component, which is stored inside its assembly, are shown on their own
  with a note saying where they come from, still read-only, and can be exported
  like any other document. When several files fit equally well you choose one
  from a list; a file that was not found is not opened, and a message gives its
  stored path and why (a network share is never contacted, for example). A
  virtual component stored inside a sub-assembly offers to open that
  sub-assembly. Back (Alt+Left, or the new toolbar button) returns to the
  document you came from with its tab, configuration, selected row and list
  filters. The self-test's new `--open-component NAME` does the same for a row
  of the document selected before it and saves both views.
- **SolidSeas Viewer: settings, a zoomable preview and an optional 3D view.**
  A new Settings menu holds Preferences (Ctrl+,) and quick toggles. You can
  choose the mouse style, reverse the wheel zoom, set the thumbnail size and
  whether the list starts as details or icons, show SOLIDWORKS lock files, and
  have the viewer reopen the last folder at the same window size. Settings are
  kept in `%APPDATA%\SolidSeas\Viewer.ini`; a damaged, hand-edited or
  deliberately crafted value goes back to its default instead of stopping the
  viewer, and Restore Defaults puts everything back. With Remember Last Folder
  off, the viewer also puts back the record of the last folder that Qt's
  folder dialogs keep. A remembered folder on a server that has gone away no
  longer delays a folder you open meanwhile. The Preview tab's image now zooms
  toward the pointer with the wheel, pans when you drag with the left or right
  button, fits on a double-click and shows the zoom level. Turn on Interactive
  3D View to rotate, pan and zoom a part's saved display mesh: left-drag
  rotates, right-drag pans and rolling the wheel away from you zooms in, or, in
  the SOLIDWORKS mouse style, middle-drag rotates, Ctrl+middle-drag pans and
  rolling the wheel toward you zooms in, as SOLIDWORKS does. Double-click or F
  fits, the arrow keys turn the model and Ctrl+1 to Ctrl+7 give the standard
  views as in SOLIDWORKS, so a touchpad can turn it too. A part fills the view
  however the panel is shaped, and refits when you resize it until you move
  it. It is off by default because it costs time: the first part shown in 3D
  holds the window for about 0.6 seconds while OpenGL starts, which the view
  says first, and a very large part takes a few seconds to read. The mesh is
  read in a separate process, so the window keeps responding and choosing
  another document stops a read at once; a part whose saved display data is
  too large for the triangle limit you set is not read at all. Image or 3D is
  your choice and holds from one document to the next; drawings show their
  stored preview with a note, and a computer without OpenGL gets a message
  instead of the view. The document list's Status column, and the
  automatic column widths, no longer stop following the folder after a column
  is hidden.
- **Two plans written down.** `docs/DRAWINGS.md` specifies the next feature,
  drawings made from 3D parts (a SolidSeas drawing file, a PDF and a DXF), with
  the decisions taken for it so far, and `docs/OCCT.md` records how SolidSeas
  uses Open CASCADE: as a test oracle now and as an optional IGES backend
  later, never inside the library or the viewer.

### Changed

- **A new home.** SolidSeas now lives in the SolidSeas organisation on GitHub,
  at https://github.com/SolidSeas/SolidSeas, starting from a fresh history. Releases
  and issues are there. The SOLIDWORKS test documents, which carry the
  name of the account that made them, are kept in a private repository and are
  fetched for the tests that need them.

- **The modeling assistant says plainly what a script can do.** A script runs
  in a separate process with a memory cap and a time limit, but with your own
  rights, so it can do anything you can. The console's note beside Run and
  the README now say so, and no longer suggest that a script can reach
  SOLIDWORKS only through the operations SolidSeas offers: that is what the AI
  is asked to write, not something enforced. Read a script before you run it.

- **Another configuration keeps the 3D view's camera.** Choosing another
  configuration reset the view to the isometric fit. Now a view you turned,
  panned or zoomed stays as it is, and a fitted one fits the new configuration
  from the same direction; only when none of the new configuration would be in
  view, or the view is zoomed out to more than 50 times its size, is it
  fitted, from the same direction. Turning Boxes for Missing Meshes
  on or off, and reading an assembly again under a higher triangle limit, keep
  it the same way.
- **The 3D view fits the model beside the legend.** With the legend shown, a
  fit centred the model in the whole view, and the legend could cover its
  corner. A fit now centres it in the part of the view the legend leaves free,
  left of it or below it, whichever shows it larger, and the model still turns
  about its own centre there. Without the legend, a fit that would put the
  model under the view cube puts it beside the cube instead, unless that would
  draw it more than a fifth smaller.
- **Ctrl or Shift pressed during a middle-drag switches it,** in the SOLIDWORKS
  mouse style, as SOLIDWORKS does: a middle-drag that has started turning pans
  from where the pointer is once you press Ctrl, zooms with Shift, and turns
  again when you let go. Before, the keys counted only when held as the drag
  began.
- **Preferences shows the note on remembering the last folder as that
  checkbox's tooltip,** which keeps the dialog within a 1080p screen at 125
  percent now that it also has Save 3D print files next to the model.
- **`solidseas list` and `solidseas batch` read each document in a worker
  process,** as the REST service does. A file that hangs, crashes its reader or
  needs more memory than allowed used to stall or end the whole run; now it is
  one failed entry (`timeout`, `worker_crashed` or `limit_exceeded` in a
  listing, an `error` row in a batch report) and the run goes on, exiting 4 as
  for any failed item. New options set the limits: `--file-timeout` (30
  seconds per document for `list`, 300 for `batch`, where the slowest of the
  development corpus's 400 largest documents took about 25 s, 39 s with
  `--text`) and `--memory-mb` (2048 per worker).
  `batch --jobs N` now runs N such workers instead of a plain process pool. The
  JSON output, the report and the files written are the same as before.
  Starting the workers adds about 0.3 s to each command; `--in-process` reads
  in the command's own process as before, without the limits. A Python script
  that calls `solidseas.cli.main` for `list` or `batch` must do so under
  `if __name__ == "__main__":`; `python -m solidseas` and the installed command
  need nothing.
- `Document.reference_set()` is now stable, and is what the `Reference.quantity`
  deprecation warning points to: unlike `components()`, it answers for a file a
  configuration does not use (0) and for a drawing's models (no count).
- `docs/API.md` section 9 now lists the stable Python names one by one, says
  that provisional items can change in any release, patch releases included,
  and says how to see deprecation warnings.
- The documentation is corrected where it claimed more than the code or the
  evidence supports: dates in JavaScript (a date property is a calendar day,
  and its `text` is not the stored text when it is stored as a FILETIME), what
  differs between the three surfaces, the BOM counts, the store and ERP
  recipes, and in `docs/FORMAT.md` the hidden rule and a drawing view's
  configuration (now marked hypotheses, with the files that would settle them)
  and a drawing's identity, which is the one its template stores.
- **Test files with known answers.** Nineteen small SOLIDWORKS documents,
  replacing the seven parts and one assembly of 0.2.0, made through the
  SOLIDWORKS API: parts (among them curved, multibody, STEP-imported and
  two-configuration parts, one with a property of each type
  SOLIDWORKS stores (text, number, yes or no and date) and two linked ones, and
  one with a Cyrillic file name), assemblies with rotated, suppressed,
  patterned, excluded and virtual components, and drawings with a bill of
  materials. What SOLIDWORKS itself reported about each one (properties,
  materials, configurations, volumes, component placements, BOM cells) comes
  with them, and the tests check the format readers against it for every
  document: configurations, properties, units, bodies, each component's flags
  and placement, and the models, sheets and views a drawing shows. A place
  where the readers disagree with SOLIDWORKS is marked as known in those
  tests; none is left.
  The documents were made from templates that name no project, so besides the
  bare Temp and Desktop folders SOLIDWORKS writes into every file they name
  only SOLIDWORKS, Windows, their own folder and the history of Dassault's
  shipped templates. A test fails if any other path, a stored user name, an
  e-mail or network address, a host name, a filled-in title or company field,
  or a document name that is not SOLIDWORKS' own or a fixture's ever appears
  in them, and, on a machine that has the private development corpus, if any of
  its file or folder names does.

### Fixed

- **The same drawing on Windows and Linux.** A drawing now orders lines of
  equal length, such as a cone's two outline lines, the same way on every
  computer, so its PDF, DXF and SVG come out identical on Windows and Linux.

- **STEP models with turned and filleted faces draw whole.** A model rocket
  made with CadQuery and saved as STEP now draws whole in the 3D view. Its nose,
  made by turning an arc round the axis, its fins where they meet the conical
  skirt, and the rounded edge at its base used to be left out. Faces on
  hyperbolas and parabolas, which appear wherever a flat face meets a cone, are
  now drawn too. When some faces of a model still cannot be drawn, the 3D view
  now says how many and why, instead of showing the holes without a word.

- **Upgrading while the viewer is open.** The installer now closes a running
  SolidSeas Viewer it installed before replacing its files, as you would by
  closing its window, instead of failing to close its background workers and
  rolling back. A copy of the viewer running from anywhere else is left alone.

- **Pitch circles with a hole on a centre line.** Holes spaced evenly round a
  full circle with one on a centre line no longer get an angle dimension: the
  hole on the line is taken as the first. Five holes starting at 0 degrees used
  to be given a 72 degree angle, and circles starting at 90, 180 or 270 degrees
  an 18 or 36 degree one.

- **A rare crash while a folder is read.** Python's garbage collection could run
  on a thread reading a document and free parts of the window there, which on
  Windows can end the viewer with an access violation. The viewer now collects
  only on its own window thread.

- **glTF exports from SOLIDWORKS.** SOLIDWORKS writes a glTF into a folder
  named after the part; batch conversion now finds it there, reports it as
  written, and leaves it alone next time unless you choose to overwrite.

- **A SOLIDWORKS that needs product activation is said so at once.** When
  SOLIDWORKS is not activated on the PC, it shows its activation wizard as it
  starts and waits, and SolidSeas' own SOLIDWORKS used to sit at its splash
  screen until a 15 minute timeout, with nothing to say why. Batch conversion
  and the other SOLIDWORKS jobs now stop within a second with "SOLIDWORKS needs
  product activation on this PC", end that SOLIDWORKS and its wizard, and do
  not start it again in the same run. SolidSeas never answers the wizard:
  activate SOLIDWORKS yourself, then start again.

- **Ctrl+Tab in the 3D view moves on again on Windows.** It showed every
  hidden part, as Shift+Tab does, because of how the Windows build of the
  toolkit turns a key modifier inside out.

- **Right-click menus show their hints in the status bar.** Pointing at an
  entry of a right-click menu, on the file list, the Components and Where Used
  tabs, the 3D view or the view cube, now says what it does at the bottom of
  the window, as the menus at the top always did.

- **A self-test of a folder that is not there stops at once.** It used to wait
  out the whole listing time, up to an hour, before failing.

- **The assistant's AI settings warn about an Ollama server reached over plain
  HTTP.** The README and the design notes now say that a request to Ollama on
  another computer over `http://`, the part's summary included, crosses the
  network unencrypted, and to use an `https://` address there. A request
  built outside SolidSeas' own checks is now checked again before any prompt
  holds it.

- **A print of many separate pieces says when their facing was not checked.**
  3D Print turns round a closed piece that faces inside out, but it judges at
  most 64 pieces of one object; past that it checked nothing and said
  nothing. It now says the facing was not checked.

- **Where Used no longer reports an unreadable index while the first one is
  made.** Opening a document just as the background indexing began writing a
  folder's first index could show "The index could not be read" instead of
  saying the file is not in the index yet. The status line's word on how a
  3D print went now also goes when you select another document, instead of
  staying under the new one.

- **Every Settings item has its own access key.** In the Settings menu, R went
  to both Reverse Wheel Zoom and Remember Last Folder and Layout, and A to both
  AI Settings and Open 3MF and STL Files As They Are, so the key alone could not
  reach them. Reverse Wheel Zoom is now W and Open 3MF and STL Files As They
  Are is O.

- **A damaged part's 3D view and print keep going.** A few kinds of damage in a
  part's geometry could stop drawing it with an error instead of leaving out
  the one face affected, and a part with a great many faces that cannot be
  drawn could fill memory with their points. Such a face is now left out and
  named, and the points kept are bounded like the triangles.

- **An indented BOM of a damaged assembly no longer takes minutes.** When the
  instances of a sub-assembly each listed different components, which a
  damaged or crafted assembly can, working out each row's quantity looked
  through every instance again, so a large tree could keep the BOM busy for
  minutes. It now counts each instance once.

- **Network shares are recognized on Linux.** A folder on an NFS or SMB share,
  or on a FUSE file system such as sshfs or rclone, is now treated as Windows
  treats a network drive: a catalog is never kept there, a file outside the
  opened folder is never read from one, and 3D Print does not put a print file
  into one outside the opened folder. SolidSeas tells a share from the
  system's own list of mounted file systems, without contacting the server. With that,
  `solidseas index --in-project` works on Linux; macOS still asks for `--db`.

- **The STEP export keeps to its time limit on bodies with many seams, and
  says why a damaged part fails.** Cutting a body's closed faces at their seams
  checked the whole body again after every cut without counting that work, so
  a body with a great many such faces could run past the export's time limit;
  it now stops there. Which of a part's bodies SOLIDWORKS hides is now worked
  out once per part rather than once per body. A crafted part whose attribute
  names hold impossible characters no longer makes the export fail with an
  unexplained error.

- **A catalog from someone else cannot hang or mislead a search.** A catalog
  holding a view or a trigger, which SolidSeas never makes but which could be
  planted in a shared project's `.solidseas` folder, is no longer opened. On
  Linux and macOS a catalog folder another account owns, or one inside a
  folder anyone may write to, is refused. `solidseas serve --catalog` will
  not start when its catalog would be kept inside one of the roots it serves,
  as the service never writes under a root.

- **The list's columns fit again once its scroll bar appears.** The columns
  were sized to the list's width before a long folder's rows filled it; when
  the scroll bar then came up, the columns ran past the list's edge and a
  sideways scroll bar appeared. They are now fitted again whenever the list
  changes width.

- **Lettered type badges at their full size on Linux.** The quick filter's
  small badges (AD on the Alibre types, for one) came out a size smaller than
  designed on Linux, where the fonts snap capitals to whole pixels. Their
  letters are now drawn at the height they were designed for.

- **A crafted face can no longer outrun the time limit.** When a face's
  outline has many points in a line or at one place, the slower way of filling
  it in could keep working past the tessellation's time limit, because some of
  its searches did not count their work. Every one of them now does, so such a
  face stops at the limit like any other.

- **3D Print refuses a part made only of open surfaces.** A part whose bodies
  are all surfaces printed as a 3MF or STL of its open display mesh, which a
  slicer cannot print as a solid. It is now refused with that reason, as a 3D
  file of open surfaces already was. A part whose surfaces close up still
  prints.

- **The viewer no longer seems to close and reopen when the 3D view first
  opens.** Windows makes a window again when it first draws with OpenGL. With
  3D on, the viewer now sets up its 3D view before its window first appears
  (and at once when 3D is turned on), so showing a part in 3D only switches to
  the view.
- **Folders fill in faster when the viewer opens.** The viewer read one file at
  a time, so a folder of many SOLIDWORKS documents, above all on a network
  drive, took a long time to list. It now reads eight documents at once and
  makes their thumbnails four at a time, and lists them in the same order as
  before. With a simulated network delay of 30 ms a file, a folder of 380
  documents listed in 1.6 s instead of 12.2 s.

- **A multi-body part in a STEP assembly is one part on the Components tab.**
  A component whose part has several bodies showed as a sub-assembly, with a
  part row for each body under it. It is now one part row and one entry in the
  Files table, its bodies drawn in one colour, and a click on any of them in
  the 3D view selects that row. Objects a 3MF or glTF file places apart are
  still rows of their own.

- **3D Print leaves out bodies hidden in SOLIDWORKS.** A multi-body part with
  a hidden body printed every body, so the slicer got solids that SOLIDWORKS
  does not show. STL and 3MF prints now leave hidden bodies out, of a part and
  of each part an assembly places, as SOLIDWORKS and the STEP export already
  did, and say how many were left out. A part whose bodies are all hidden is
  refused with that reason.

- **A multi-body Parasolid file from SOLIDWORKS exports and prints as STEP.**
  SOLIDWORKS writes a multi-body part's .x_b as an assembly that places each
  body where it is, so Export STEP refused it and 3D Print sent it as a 3MF. A
  transmit whose one assembly only gathers its bodies in place is now that part:
  its STEP is one product holding a solid per body, as SOLIDWORKS' own STEP of
  the part is. A transmit that moves, turns, repeats or nests what it places is
  still an assembly, which the STEP export does not write yet.

- **The folder tree no longer counts files it is hiding.** While View > Show >
  Files SolidSeas Cannot Read was off, each folder's count still included those
  files, so a folder of ten parts and two IGES files read "10 of 12" with only
  ten rows to show. They now count only while that setting lists them, as lock
  files already did, and the Status column no longer appears just for them.

- **Export STEP says why it is off for a drawing.** Its tooltip used to describe
  writing a part, with the action greyed out and no reason. It now says that
  STEP holds 3D models, not drawings, and to export the model the drawing shows.

- **STEP parts with hollows inside are no longer read inside out.** A STEP file
  marks each hollow (a void) as a shell turned round. Some programs store that
  shell already facing into the hollow and turn it round all the same, and
  SolidSeas took the mark at its word: the hollow faced outward, its volume
  was added to the part's instead of taken away (up to 78 percent too much),
  and a 3D print or STL of the part had a cavity turned inside out. Each shell
  of a STEP solid is now turned by its own volume, the outside facing out and
  every hollow facing in, and the scene says so (`void_reoriented`, or
  `solid_reoriented` for a solid that was inside out as a whole). Shells that
  already faced the right way are left alone.
- **Curved STEP faces no longer fold over themselves.** Some faces came out
  with triangles folded over one another, covering more area than the whole
  surface they lie on, which threw off a part's area and volume and spoiled
  prints. Four causes are gone: a seam run down to a sphere's or cone's point
  and straight back up is no longer a slit the triangles fan across; an edge
  whose curve stops dead at a corner is no longer sampled into a pile of
  points a billionth of a millimetre apart (which also left such faces out as
  `edge_too_long`), and no edge is split into points closer together than a
  micrometre or a hundredth of the mesh's tolerance, which a face cannot tell
  apart; a torus that runs through its own axis is meshed the right size
  where it does; and a face whose edges run on past the end of its surface is
  no longer split again and again into folds.
- **STEP files whose faces are stored the wrong way round now draw.** A face
  whose every loop runs against it was left out, said to be a seam problem even
  on a flat face; files stored that way drew nothing at all. Such a face is now
  drawn facing the way the file says, its loops read the other way round, as
  other CAD programs read it (`loops_reversed`); where it disagrees with the
  faces round it, it is turned to agree with them. Files whose faces share no
  edges, as these do, therefore draw facing outward.
- **Rounded parts no longer have holes where their fillets are.** A fillet that
  Parasolid stores as a rolling blend (`BLENDED_EDGE`, the surface a sphere sweeps
  as it rolls along two faces) was left out of the triangles SolidSeas makes
  from a part's bodies, so the 3D view of a part saved without a display mesh
  or of a Parasolid file (`.x_t` or `.x_b`), and the STL and 3MF that 3D Print
  and Export write, had a hole at every such fillet, and the print said the
  part was not closed. Those faces are now drawn from the same surface the
  STEP export writes for them, within about a tenth of the chord tolerance, and
  a tolerant edge beside a blend is sampled along the other face's curve, which
  also brings back the face next to the blend that such an edge used to take
  with it. On the 222 parts of the development corpus that have such fillets,
  every solid of 129 now comes out closed where none did, and 131 of their 3D
  print models are closed where none were; on the 12 whose mass SOLIDWORKS
  measured and whose prints are closed, the print's volume is within 0.04% of
  SOLIDWORKS' for 10 and within 0.6% for all. Drawing blends takes time (a
  median of 2.5 s for such a part instead of 1.3 s, and 6.4 s instead of 4.4 s
  for its print), so they are done after every other face, one blend may take
  a tenth of the time allowed and at most 15 s (when that runs out, its best
  approximation so far is kept if it is close enough), and blends the time runs
  out on are left out with the reason `max_seconds` instead of the whole part
  being cut short. A Parasolid file's 3D view, thumbnail and 3D print leave them
  out the same way, the view and the thumbnail then saying they are partial.
  These limits are times, so on a busy computer a blend near them can be drawn
  less finely or left out. A blend that cannot be approximated is still left
  out, with its reason (`fit_failed`, and `unsupported_curve` between two blends
  along a tolerant edge).
- **A STEP leaves out the bodies SOLIDWORKS hides, as SOLIDWORKS' own STEP
  does.** A multibody part's STEP held every body, hidden ones too, so a STEP
  for a supplier or the 3D printer could carry a tool body or an old version
  of the part inside or beside the real one: on four parts measured against
  SOLIDWORKS the volume was 37 % to 1,800 % too large. A body SOLIDWORKS hides
  is now left out, and the export says so (`bodies_left_out`, reason
  `hidden`); the four parts then match SOLIDWORKS' volume to 1.5e-4 or better.
  The part says which bodies are hidden in the same place for every body made
  in SOLIDWORKS; only where it does not (some imported bodies) does the export
  still warn that it cannot tell (`step_hidden_bodies_unknown`), now only then.
  `include_hidden=True`, or `--include-hidden` on the command line, writes the
  hidden bodies too. A part whose every body is hidden has nothing to export,
  and says so. File > Export STEP lists the hidden bodies it left out. A part
  that shows only surface bodies beside a hidden solid is exported as its
  surfaces, as a part of surfaces only is, and 3D Print says it is surfaces.
- **A STEP face that goes all the way round a hole or a shaft is written as
  two, as SOLIDWORKS writes it.** A hole's cylinder, a fillet round a hole, a
  sphere's cap or a cone's tip went into the STEP as one face with no edge
  where its surface closes on itself. That is valid STEP, but readers that
  work in the surface's own coordinates had to add the missing edge themselves
  (OCCT, the kernel of FreeCAD and many other programs, added 587 such edges to
  65 of 162 measured parts) and some then drew or measured the face wrongly.
  Such a face is now cut in two along its surface's own lines at 0 and 180
  degrees, as SOLIDWORKS' "split periodic faces" option does: the fixture with
  a filleted hole now has the same 14 faces, 34 edges and 22 vertices as
  SOLIDWORKS' own STEP of it, OCCT adds no edge to any fixture, and on those 162
  parts it adds 6, one to each face still written whole (a band whose edge winds
  back and forth across every line, holes all round, an apple-shaped torus).
  Every cut is checked again before it is written, its two halves among the
  checks (each must cover its side of the face, and hold the holes given it),
  and a face whose cut would not check is written whole as before. So is the
  cap of a sphere or a cone whose edge passes close to the point the cap
  closes round (within a micrometre, or 15 % of the cap's size): cut there,
  one half would be a sliver, and OCCT read two such parts with faces of no
  area, one of them as broken. `split_periodic=False` writes such faces whole.
- **A crafted STEP file can no longer stall SolidSeas for minutes.** Two scans
  in the STEP reader took time that grew with the square of what they read: the
  search for the length unit, which every open and every folder listing runs, and
  the decoding of escaped text in strings. A file built to exploit them could hold
  the viewer, the command line or a script for minutes or hours. Both now read
  each byte once, and the unit search checks the time limit as it goes.
- **The library refuses to write a SOLIDWORKS file.** Exporting STEP or a mesh from
  Python with a SOLIDWORKS extension as the target, even with `overwrite=True`,
  is now refused with the `solidworks_file` rule, as the command line and the
  viewer already did, so no export can replace a source document.
- **Exports refuse Windows device names on every Windows.** A target such as
  `nul .x.3mf` or `COM1 .3mf` was refused only where Windows itself turned the name
  into the device; newer Windows leaves the path alone. The reserved names are now
  refused by name.
- **A remembered folder or program whose name holds an unusual line break no
  longer resets every setting.** A folder or program path with U+2028, U+2029
  or U+0085 in its name was written into `Viewer.ini` as it is, and the file
  was then read as damaged: every preference went back to its default. Those
  three characters are now written escaped, and read back unchanged.
- **A note under the Explode bar no longer widens the details panel.** A note
  such as "There is only one top-level component, so nothing moves" asked the
  details panel for its full width, so the window's splitter moved each time
  a note came or went. The note is now cut short in a narrow panel, and its
  tooltip has it whole.
- **A sub-assembly is no longer hidden by its display state.** SOLIDWORKS
  stores `No` in the display state of a sub-assembly it draws when something
  inside it is hidden, and `components()` read that as hidden, so
  `display_geometry` and the viewer's 3D view left out every part of such a
  sub-assembly without saying so. A sub-assembly instance's `hidden` now
  follows its own `swHidden` flag, as an instance inside a sub-assembly already
  did; a part's display state still decides for the part. On the development
  corpus this shows 124 more part instances in 6 assemblies, and the parts
  shown now fill the box SOLIDWORKS stores for each of them.
- **Turning the 3D view after panning and zooming keeps the model in view.**
  The view turned about a point in the middle of the view that a pan or zoom
  moved only across the screen. After a pan and a turn that point lay in front
  of or behind the model, a later pan or zoom kept it there, and the next turn
  swung the model round it: panned, turned a quarter and zoomed in four times,
  a turn of 30 degrees could carry the model's centre out of the view. A pan
  or a zoom now also moves that point along the line of sight to the depth of
  the model's centre, which changes nothing on screen, and turning leaves it
  where it is, so a drag turns the model the same however fast you make it and
  turning back undoes a turn. A detail in front of or behind that depth still
  moves sideways as the model turns.
  Panning itself was measured on the display as well, after it was reported to
  move in one direction only: the model follows the pointer exactly, across and
  down at once, with either mouse style and with Ctrl+arrows, so it is
  unchanged.
- **On Linux and macOS, writing an output into a folder fails as it should.**
  Asking `dump -o` to write to an existing folder used to be refused as a hard
  link, because a folder's link count there counts its subfolders. It now ends
  with `not_found`, as on Windows.
- **On Linux and macOS, folder listings show symbolic links to folders.** A
  symbolic link does not record whether it leads to a folder, so a link with
  no SOLIDWORKS name was left out of a listing. Every symbolic link is now
  listed with status `link` and type `file`, and is still never followed.
- **The parts inside an older assembly's sub-assemblies are drawn.** An
  assembly saved before SOLIDWORKS 2023 keeps each component file's mesh in a
  section of its own display lists, and often writes a file's path there more
  than once, the extra copies with nothing after them. SolidSeas used a file's
  section only when its path appeared once, so those parts fell back to their
  own part files, which for parts inside sub-assemblies mostly store no mesh,
  and the 3D view showed an exploded assembly with its sub-assemblies empty.
  Of the sections, the one that holds the mesh is now used, and a file whose
  path opens two sections with meshes is still refused. On the development
  corpus the parts drawn rise from 4,571 to 5,392 of 6,724 (68% to 80%);
  inside sub-assemblies from 1,507 to 2,104 of 2,775. Where a part file still
  matches what the assembly recorded of it, the mesh taken has that file's
  size and place to within 1% in every case, and is its mesh exactly in 304 of
  342.
- **A sub-assembly whose components the assembly does not list is no longer
  left out without a word.** It was skipped silently, and its parts were not
  even counted. It is now read from the sub-assembly's own file, in the
  configuration the assembly uses, and its parts are drawn like the others;
  when that file is not found, cannot be read or lists no components, the
  sub-assembly is drawn as the box the assembly stores for it and counted on
  the status line with the reason (its tooltip names it), or named on the line
  when it has no box. A suppressed or hidden one is counted once and not read.
  A file it shares with the assembly is one file in the 3D view: one colour,
  one row of the legend, and its row of the Files table picks every instance
  of it.
- **An older assembly's component no longer takes in another file's
  triangles from where that file used to be.** Some older display lists hold a
  header naming a file of the assembly under the folder it was in before, with
  that file's triangles after it, inside the section of another component.
  Those triangles were drawn as part of that other component: 2 instances on
  the development corpus, one drawn with 22,069 triangles instead of its
  11,779. Such a header now ends the section before it, and both come out the
  size SOLIDWORKS recorded for them.
- **An older assembly's component no longer takes in the next file's
  triangles.** In an assembly saved before SOLIDWORKS 2023, each component
  file's stored mesh is a section of the assembly's display lists that ends
  where the next file's section starts. SolidSeas only noticed the start of a
  section it meant to use, so when the next file was a sub-assembly, a part used
  in several configurations or a path two files share, the section ran on
  through that file's tables and the component was drawn with another part's
  geometry at its place: 75 sections on the development corpus, 20 instances
  drawn with 20,722 triangles that were not theirs. Every stored path in the
  component tree now ends the section before it.
- **A component held back by the triangle limit says so.** When the limit
  stopped the read of a component's mesh and the next place to look had none
  (o16's virtual part), the 3D view's status line blamed "no saved display
  mesh", although a higher limit would draw it. The limit is now the reason
  given. The same goes for the limit on display data: a component whose mesh
  is in display lists the limit kept from being read, the assembly's or a
  sub-assembly's, was named as a file not found, and is now named as stopped
  by the limit. A sub-assembly's `FaceTessellations` directory now counts
  against that limit too, and when the limit on instances stops the look-up
  of a part in a sub-assembly's own tree, the part is named as stopped by it.
- **An assembly that uses a sub-assembly many times reads much faster.** A
  sub-assembly whose components the assembly does not list was read again for
  each instance of it, its folder searched again for each such sub-assembly
  when no cache was given, and a part file several of them name opened again
  for each: 200 instances of one whose file describes 20,000 instances in
  another configuration took 2.9 s, and 20 sub-assemblies stored in the
  assembly, each naming the same part, in a folder of 20,000 files took 5 s.
  Each is now read once, and they take 0.5 s and 0.3 s.
- **A crafted assembly can no longer keep the 3D view reading for minutes.**
  Each block a `FaceTessellations` directory names but its stream lacks sent a
  search to the end of the stream again: an assembly of a few hundred kilobytes
  kept the mesh process busy for 47 seconds per thousand such records. The
  searches now stop at four times the stream's size, and the same file reads in
  well under a second.
- **Assemblies with many instances of a detailed part read much faster in 3D.**
  The box of the whole assembly passed over a mesh's vertices once for every
  instance of it (5 seconds for 2,000 instances of a 20,000-triangle part); each
  mesh's box is now measured once.
- **The 3D view no longer asks the graphics card for unbounded work.** The
  triangle limit counts each component file once, so thousands of instances of
  a part just under it could ask for billions of triangles a frame, enough for
  Windows to reset the graphics driver. An assembly now draws at most twenty
  times the limit in all (20 million triangles by default); the instances past
  that are named on the status line, and a higher limit draws more.
- **The view keeps up with the Explode slider.** Every step of the slider used
  to start a new half-second ease from rest, so while you dragged it the
  assembly hardly moved (at 20 percent when the handle reached 100) and then
  jumped there. The view now follows a drag, the arrow keys and the wheel
  closely, a few points behind at most, and still eases for a page step,
  Collapse and Back.
- **Back keeps the 3D view as you left it.** Coming back from a component's
  file put the assembly back turned to the isometric view and fitted, and kept
  the explode level chosen in the file you had opened. The camera and the level
  now come back too, so you can zoom in, open a small part, come back and open
  the next without zooming in again.
- **Components no longer stay inside one another when exploded.** Moving each
  component away from the assembly's centre separates two of them only by the
  distance between their centres, so a part in a housing or a pin in a bore
  stayed inside it: on the development corpus a fifth of the overlapping pairs
  still overlapped at 100 percent. A component still inside another is now
  moved out of it the shortest way, and 1 pair in about 5,000 still overlaps.
- **An assembly with a single top-level component explodes.** Grouped by
  top-level component it could not move at all, and only a tooltip said why.
  Such an assembly now starts at Every part, the Explode bar says so in words,
  and with a single part the slider is off.
- **The legend no longer hides the model.** It could take nearly half the view
  and its full height and catch the clicks meant for the components under it.
  It now keeps to a third of the view's height and scrolls, an assembly of more
  than twelve files starts with it hidden until you choose, and clicking a file
  in it picks every instance of that file.
- **A double-click on a sub-assembly's row opens and closes it again.** It had
  started to replace the document with the sub-assembly's file, which neither
  Windows nor SOLIDWORKS does. Press Enter, or use Open file on its menu, to go
  to its file; a double-click on a part's row still goes to the part.
- **A virtual part opened from its assembly is drawn in 3D.** SOLIDWORKS keeps a
  virtual part's display mesh in its assembly, and the part's Preview tab said
  it had none, although the assembly had just drawn it. It now opens on the
  Preview tab with that mesh.
- **A part opened from an instance says which configuration the instance
  uses.** The status line names it; when it is not the configuration the part
  was saved in, a note says that the preview and the 3D view show the saved
  one, and the Overview and Properties tabs mark the instance's.
- **Reference resolution over REST sees the folders as they are now.** The
  service used to resolve against the folder indexes it built when it started,
  so a project moved or copied while it ran was found at its old place, with
  high confidence, until a restart, and a client revalidating with its ETag kept
  getting that stale answer. Each `resolve=1` request now walks the roots
  again, as Python's `resolve_references` does on each call, and gives the same
  answer Python gives at that moment. Its ETag now comes from the answer
  itself. A root that cannot be walked is no longer left out without a word:
  it is listed with `truncated_reason` `unavailable` and every result carries
  the new warning `root_unavailable`.
- **A listing page with a file that could not be read for now has no ETag.** A
  page holding a locked file (or one whose read timed out or crashed its
  worker) used to carry the same ETag as the clean page, so a client
  revalidating it got 304 and never read that file again. Such a page now comes
  without an ETag. The ERP sync recipe in `docs/API.md` 10.2 also keeps no memo
  of such a page, and now removes files that are gone after a complete pass.
- **The service's token file can no longer be swapped by another account.** On
  Windows the start-up check did not look at who owns the token file, and on
  every system it did not look at the folder. It now refuses a file or folder
  owned by anyone but the service's account, SYSTEM or Administrators
  (`not_owner`), and a folder another account could add to, delete from or
  re-permission (`folder_writable`). A `--token-file` in a folder that does not
  exist is now refused as `folder_missing` instead of `unreadable`. The
  shared-machine recipe in `docs/API.md` 8.14 refuses a ProgramData folder that
  exists already and sets the new folder's owner.
- **A folder swapped for a link is refused before anything goes through it.**
  The service, and the worker that opens a document, now check every folder of
  a path from the root down before using the next one, so a folder replaced by
  a symbolic link to a file share never makes Windows connect to that share.
- **A lost worker is always replaced.** After three failed attempts the pool
  used to give a worker slot up for good, silently; with every slot gone, every
  document request timed out until a restart. The pool now keeps trying, with a
  wait that grows to 30 seconds, waits for a killed worker to end before
  replacing it, logs what happens, and `/v1/health` answers 503 while no worker
  is running.
- **The service no longer reads what it is about to refuse.** Request headers
  past the 16 KiB limit are not read at all (a client could make the service
  hold 6 MB per connection), and a worker's answer may be no longer than its
  route's size cap plus 64 KiB: the worker refuses a longer one before sending
  it, so a small crafted document cannot make the service parse hundreds of
  megabytes.
- **Idle connections no longer hold the service up for long.** A connection
  must send its first byte within 5 seconds, a connection refused over the cap
  is closed after at most 0.1 s, and a connection closed because its request
  never arrived is logged.
- **Every answer has a status line and the security headers.** A request line
  without an HTTP version was answered with a bare body, and a method the
  service did not know answered 405 before the Host check; both now go through
  the same checks as any request.
- **Clearer REST errors.** Listing a file answers 400 `invalid_argument` ("The
  path names a file, not a folder.") instead of saying it does not exist; an
  unknown route says so (`detail.rule` `route`); and an error in the query
  names the root and path that were asked for in `source`.
- **A script that starts a worker pool without a main guard is told why it
  failed.** Workers start with spawn on every system, so a pool created at the
  top level of a script is created again in each worker; the pool now notices
  a worker that ended as it started and names the missing
  `if __name__ == "__main__":` instead of waiting a minute and saying only that
  the worker did not start.
- **A date or number typed into a property no longer reads as linked.** A
  date, and a number SOLIDWORKS stores in another form than it was typed (`3.25`
  stored as `3.250000`), came with `linked` true when the file also kept the
  value as typed, although nothing links them and SOLIDWORKS reports them as
  not linked. `linked` is now true only for a link or an equation: the file
  stores the expression with a different evaluated value beside it, and the
  expression is not a number that reads as the value or a yes or no that means
  it. A typed date or a number with a decimal comma kept in the hidden
  expression property would still read as linked; no file seen stores one
  there. For integrators: `linked` keeps the meaning `docs/API.md` 3.2 has
  always given it (the value is SOLIDWORKS' cached evaluation of the
  expression), so under the stability policy this is a bug fix, not a change to
  a stable field, and the `property` JSON kind stays at schema version 1. Such
  a property still has the value as it was typed in `expression` (`3/15/2024`,
  `3.25`), so code that took "expression differs from text" to mean linked
  should read `linked` instead.
  On the development corpus no property changes: its 45 linked properties are
  the same before and after.
- **The path report reads legacy 8-bit text past an accented letter.** Older
  documents keep the folder at save and their properties as 8-bit text in a
  code page. Where that text is not UTF-8, as a cp1252 folder named "Café" is
  not, the report cut the path at its first accented or non-Latin letter and
  listed the stub next to the whole folder. It now reads such a string whole,
  in the code page its property set declares (cp1252, cp1251 for Cyrillic,
  cp932 for Japanese and so on) or in cp1252 when none is declared, and only
  where the file stores the string's length and its end, so binary data next to
  a path is never read as part of it. A string with an accented or non-Latin
  letter in a property set that declares an 8-bit code page is read in that
  code page even where its bytes would also be valid UTF-8, as the property set
  reader reads it. `scan_bytes` (provisional) reports these paths with the new
  encoding `ansi`. On the development corpus no path changes: its legacy
  documents keep their non-ASCII paths in UTF-8.

## [0.2.0] - 2026-10-01

The first release under the stability policy in `docs/API.md` section 9: from
here on, what that document marks stable changes only in a minor release, with
a note here on how to move to it.

### Added

- **Project foundation.** SolidSeas now has its plan written down: what the
  library and the desktop app will do, the order they will be built in, and
  the rules every change follows. Start with `docs/ARCHITECTURE.md` and
  `docs/ROADMAP.md`.
- **Automatic mode for the modeling assistant is in the plan.** Besides
  reviewing each AI-drafted change before it runs, you will be able to hand the
  assistant a goal and let it carry the goal out on the part you have open. It
  plans once, using only a fixed set of checked operations, and shows you the
  plan. It asks you once before starting only if the plan would change or hide
  something your goal did not spell out. It keeps a safety copy of your part,
  checks every step against what that kind of step is allowed to change, stops
  at the first sign of trouble, can be stopped between any two steps with a
  hotkey, and never saves over your file. By default your file paths, property
  values and feature names are not sent to the AI provider, and a "What the AI
  sees" panel shows exactly what is. A company can switch Automatic mode off,
  or keep the AI on the local machine, on managed PCs. The full design is in
  `docs/ASSISTANT.md`.
- **Test parts with known answers.** A set of small SOLIDWORKS parts and one
  assembly, made through the SOLIDWORKS API, with exact expected properties,
  material, configurations and volumes. Every format reader is checked against
  them.
- **Read SOLIDWORKS files without SOLIDWORKS.** `open_document()` in
  `solidseas.formats.solidworks` opens parts, assemblies and drawings saved by
  any SOLIDWORKS version in the development corpus (2006 to 2024), read-only,
  on Windows or Linux, with nothing but Python and `olefile`. It tells you the
  document type, which SOLIDWORKS version saved it, the configurations, custom
  and configuration properties, material and units, and gives you the saved
  preview image, the Parasolid bodies of each configuration as `.x_b` or `.x_t`
  files, the display mesh, an assembly's components with their positions, and
  the folder paths the file would reveal to anyone you send it to. On 3,501 real
  files every one opened, two thirds carry a preview, and 99% of parts give up
  their Parasolid bodies. The Parasolid files it writes for the test parts load
  in SOLIDWORKS with the exact volume and area of the original. The file is read
  into memory and closed straight away, so an integration holding a document
  open never stops SOLIDWORKS from saving over it. `docs/FORMAT.md` explains the
  file format and marks every claim as verified, hypothesis or unknown.
- **Safe on hostile files.** A damaged or deliberately crafted file cannot hang
  the reader, make it use gigabytes of memory, or stop a batch run: every case
  found in review now fails or finishes within a fraction of a second, and the
  batch report records the bad file and moves on. That includes a 4 KB legacy
  file claiming to hold terabytes of small streams in a loop of sectors, which
  used to keep a folder listing busy for seconds or for good.
- **Command line.** Every command opens files read-only, accepts `--json`, and
  refuses to write into the folder of the file it reads unless you pass
  `--allow-source-dir`. It never writes a SOLIDWORKS file or over a source
  file, including through Windows path aliases (trailing dots or spaces,
  alternate data streams) and hard links, and a batch never follows folder
  junctions. Usage, from the repository root (set `PYTHONPATH=src`,
  or run `pip install -e .` once and call `solidseas` instead of
  `python -m solidseas`):

  ```text
  python -m solidseas info part.sldprt               format, version, type, configurations
  python -m solidseas props part.sldprt              custom properties as JSON
  python -m solidseas configurations part.sldprt     configurations, materials, properties
  python -m solidseas components asm.sldasm          the component tree of one configuration
  python -m solidseas references asm.sldasm          every referenced file, per configuration
  python -m solidseas streams part.sldprt            streams and their sizes
  python -m solidseas dump part.sldprt PreviewPNG -o out\preview.png
  python -m solidseas preview part.sldprt -o out\    preview image (PNG, or BMP with --prefer dib)
  python -m solidseas parasolid part.sldprt -o out\ --text   .x_b and .x_t per configuration
  python -m solidseas list D:\Jobs --recursive       every document in a folder, with previews
  python -m solidseas batch D:\Jobs -o D:\Exports    info, preview and parasolid for a folder
  python -m solidseas version                        versions of the tool and its JSON
  python -m solidseas schema listing                 the JSON Schema of a command's output
  ```
- **Batch conversion through SOLIDWORKS, on Windows.**
  `src/solidseas/swapi/Convert-WithSolidWorks.ps1` converts parts and assemblies
  to STEP AP242, Parasolid, STL, 3MF and glTF through its own hidden
  SOLIDWORKS instance, which ends when the script ends. It cannot be pointed at
  the session you are working in, and it never closes a document it did not
  open. It compiles against the SOLIDWORKS 2024 API but has not been run end to
  end yet; see its `README.md` before using it.
- **An integration guide, `docs/API.md`.** It is written for the ERP, invoicing
  and store code that reads SOLIDWORKS files through SolidSeas: how to install
  it and which of its three ways in to use, what the Python API returns and
  raises, the exact JSON every surface sends and how to read it from
  JavaScript without losing digits, the command line and the REST service in
  full, the error codes with their HTTP status and exit code, and the rules
  for locations, references and roots. It shows how to run the service in the
  background on Windows (a Scheduled Task, as the user or as LOCAL SERVICE)
  and on Linux (a systemd unit). Recipes in Python, curl and TypeScript keep an
  ERP's part list in step with a folder using ETags, fill invoice fields from
  a configuration's properties, build a store product page from the thumbnail
  and the component list, and check what a file would reveal before it is
  sent; a troubleshooting table covers the usual errors. Its stability policy
  says what may change between releases and how deprecations work.
- **A security review of the service, `docs/SECURITY_REVIEW.md`.** For whoever
  approves `solidseas serve` on a managed PC or server: the findings with their
  severity and status, the complete network surface (one listening socket on
  127.0.0.1 and no outbound connection), what the service stores (its token
  file and nothing else), the commands that repeat every check, and a
  recommendation with its conditions. The desktop app's sections follow with
  Phase 5.
- **What the format work established, in `docs/FORMAT.md`.** How a
  component's stored position and rotation read, checked against what
  SOLIDWORKS 2024 reports; that SOLIDWORKS marks every suppressed component
  hidden, and that the configuration's display state decides what is shown;
  the three places a document stores its creation time, which always agree;
  where virtual and imported components are kept, including the virtual parts
  stored inside sub-assemblies; and the creation time a drawing keeps for its
  model. Each finding carries its evidence label and its counts.
- **One JSON summary of a document.** `doc.summary()` returns the file's name,
  size and modification time, type, saving version, configurations,
  properties, material, units, title and author fields, what preview it stores
  and a few counts, as plain JSON data. The command line and the REST service
  will send exactly the same data. `solidseas.model.dumps` encodes it strictly:
  a value JavaScript would change, such as a NaN or an integer beyond 2^53, is
  sent as null with a warning instead, and the file's nanosecond modification
  time travels as a string.
- **Document details for integrations.** `open_document()` takes `name=` (the
  display name, and the extension hint for bytes) and `max_file_bytes=`, which
  refuses a larger file before reading any of it. A document now has
  `file_info` (size and modification time), `fields` (title, author, last
  saved by and the dates), `doc_type_source`, `configuration(name)` and
  `effective_properties()`, which applies a configuration's own properties
  over the file's, as a bill of materials sees them.
- **Every error has a stable code.** All of SolidSeas' exceptions now derive
  from `solidseas.SolidSeasError` and carry a code such as `locked`,
  `damaged_file` or `file_too_large`, so an integration can react to the code
  instead of the message. Every 0.1 exception keeps its name and still catches
  what it caught before. `import solidseas` now gives `open_document` and the
  exceptions directly.
- **Checks on Linux and Windows.** Every push runs the linter and the tests on
  Ubuntu and Windows with Python 3.11 and 3.12.
- **Folder listings.** `solidseas.scan(folder)` and `solidseas list FOLDER`
  list every SOLIDWORKS document in a folder with its type, saving version,
  active configuration and preview, and on request its properties,
  configurations and the preview image itself, in the same JSON as a document
  summary. Each file is held open only while it is read, a few milliseconds,
  and only the parts the listing needs are read: listing the folders that hold
  3,527 real files (2,983 MB) read 4.6% of their bytes and took 8.4 seconds. A
  damaged or locked file gets an error in its own entry and the listing goes
  on; a locked one says it is worth trying again.
- **Links and cloud files are left alone.** One folder walker now serves the
  listing and `batch`. It never follows a symbolic link, junction or other link
  out of the folder, and never opens a cloud file whose data is not on this
  machine, so listing a OneDrive or SharePoint folder never starts a download.
  It reports both, and SOLIDWORKS lock files, instead of hiding them. A
  deduplicated file on a Windows file server counts as an ordinary file again.
  A folder that is another mounted filesystem on Linux or macOS is reported as
  a link and not entered, as a mounted volume already was on Windows.
- **A pipe named like a part cannot hang a listing.** On Linux and macOS a
  FIFO, socket or device named, say, `bracket.SLDPRT` is listed as skipped and
  never opened; opening a FIFO used to wait for ever. Opening any file that is
  not a regular file, `NUL` and `/dev/null` included, is refused at once with
  the error code `path_refused`.
- **A file swapped after the folder was listed is not followed.** `list`,
  `scan` and `batch` open each document they found without crossing a link
  below the folder, so a name replaced by a link to somewhere else in the
  moment between listing a folder and reading the file gets a `link_refused`
  error instead of describing the other file, and a file that has just become
  a cloud placeholder gets `placeholder_file` instead of being downloaded.
  `open_document(..., within=folder)` gives an integration the same check.
- **Bounding a listing of a huge folder tree.** `scan(max_examined=...)`, and
  `--max-examined` on `list` and `batch`, stop the walk after it has looked at
  that many directory entries, documents or not (one million by default). The
  entry limit alone cannot: to call a listing complete, the walk has to look
  through the rest of the tree. All the limits, the listing's time limit
  included, are checked between files, so one slow file or a share that stops
  answering can run past them.
- **JSON from every command.** With `--json`, every command prints exactly one
  JSON document, errors, mistyped arguments, `--version` and `--help` included,
  and nothing on standard error. New commands: `configurations`, `list`,
  `version`, and `schema`, which prints the JSON Schema of what a command
  returns. Exit codes say what happened: 0 success, 1 failed, 2 wrong
  arguments, 3 refused by a safety rule, 4 partial (a listing or batch in
  which some files failed) and 130 interrupted. `docs/API.md` section 7
  describes them.
- **Assembly component trees.** `doc.components()` and `solidseas components`
  give the components of one assembly configuration as a tree: for each
  instance its file, the configuration of that file it uses, whether it is
  suppressed, hidden, excluded from the bill of materials or virtual, where it
  sits relative to its parent sub-assembly, and where it sits in the whole
  assembly as a rotation and a position in metres. Each referenced file has a
  count of its instances, of those not suppressed and of those in the bill of
  materials, through every level of sub-assembly. The positions were checked
  against what SOLIDWORKS itself reports for test assemblies with rotated
  parts and rotated sub-assemblies, to within 1e-16 m, and the counts against
  the bill-of-materials tables SOLIDWORKS made for one of them. Pick another
  configuration with `--configuration`; a very large or looping tree stops at
  a limit (10,000 instances and 32 levels by default) and says so instead of
  running away.
- **Every referenced file, per configuration.** `solidseas references` and
  the `references` JSON list every file an assembly uses in any of its
  configurations, with the counts for each configuration side by side, under
  the same file keys the component tree uses. For a drawing it lists the
  models it shows, its sheets and each view with the model configuration it
  shows (provisional: checked on two single-sheet drawings).
- **Virtual and imported components can be read.** A component stored inside
  the assembly (a virtual part, or an imported one) says which nested document
  holds it, and `--nested` on `info`, `props` and `preview` (`nested=` in
  Python) reads that document's summary, properties and preview, so part
  numbers of virtual parts are no longer out of reach. On the development
  corpus 125 of the 129 virtual files used directly by their assembly are
  found this way.
- **Finding referenced files that moved.** `solidseas references FILE
  --resolve` (and `doc.resolve_references()` in Python) says where each file
  an assembly or drawing references is on this machine now, even after the
  project was moved, copied or renamed. It searches the document's own folder,
  or the folders you name with `--root` and `--library`, the way SOLIDWORKS
  itself searches, and checks every answer against the creation time the
  assembly stored, so an unrelated file that happens to share a name is not
  taken for the real one. Each file comes back as resolved, moved, embedded in
  the assembly, ambiguous (with the candidates) or missing, with a confidence
  and the rule that found it, and its location is given relative to the
  folder it was found in. `--path-map S:\=/mnt/eng` reads paths saved under
  another drive letter or share. A path saved on a network share or mapped
  drive is never contacted, a link inside a searched folder is never followed,
  and a cloud file is found but never downloaded. On the development corpus,
  with the project folders as roots, 83% of the files assemblies use directly
  are found and 0.4% are ambiguous; the rest are library parts that are not in
  the corpus.
- **`solidseas.Roots`**, one way to name the folders SolidSeas may search: an
  id, a folder, whether to search below it, and whether it is a project or a
  library. A share or a junction is a fine root; a WebDAV address is refused.
- **See what a file would reveal before you send it.** `solidseas paths FILE`
  (and `doc.path_report()` in Python) lists every folder path and user name
  stored in a part, assembly or drawing, including those inside virtual and
  imported components, which a plain scan of the file never sees. Each path
  says where it points (a network share, a project folder, a user profile, the
  Desktop, a temp folder, Windows or the program folders), why the file keeps
  it (a referenced file, the folder it was saved in, the save history, an
  appearance or imported file), which account or server it names, and how much
  it matters when the file goes to a customer. Accounts that appear only in the
  save history, probably the authors of the template the file was made from,
  are marked but not played down. The report says when it is incomplete, for
  example because one stream was too large to read, and the command then exits
  4. SolidSeas never rewrites the file; removing these values means saving a
  new document in SOLIDWORKS or sending a neutral format.
- **A local REST service.** `solidseas serve --root jobs=D:\Jobs` gives
  systems written in other languages, such as the online store, the same JSON
  as Python and the command line, over HTTP: folder listings with thumbnails and
  properties, document summaries, properties, configurations, component trees,
  referenced files (with `resolve=1`, where each one is now within the served
  folders), preview images and the path report. It listens on 127.0.0.1 only,
  unless you allow another address explicitly, and every request but the
  health check needs a bearer token, which it creates on first start in a file
  only you can read and never prints. It turns away requests a web page in a
  browser could make (another Host, an Origin, a cross-site fetch), accepts only
  GET and HEAD with a fixed list of parameters per route, and never uses a path
  from a request as a path: each one is looked up among the files the service
  indexed in its folders. It never follows a link out of a folder, never
  downloads a cloud file and never writes anything. Every document is read in a
  separate worker process with a time limit and a memory cap, so a file that
  hangs or crashes the reader costs one answer, not the service. Answers carry
  ETags, so polling a document costs a directory lookup until it changes. The
  log says who asked for what and how it went, never which file or what was in
  it. `docs/API.md` section 8 describes it all.
- **Worker processes for files you did not make.**
  `solidseas.workers.WorkerPool` reads documents in a few separate processes,
  each file with a deadline and each process with a memory cap (a Job Object on
  Windows, an address-space limit on Linux). A file that hangs is reported as
  `timeout`, one that exhausts the memory as `limit_exceeded` and one that
  crashes the reader as `worker_crashed`, and the next file is read as usual.
  Answers come back as JSON, never as pickled Python objects. `scan(...,
  pool=pool)` lists a folder this way. Provisional, like the service's own
  Python classes.
- **Refusing hard links.** `open_document(..., refuse_hard_links=True)` refuses
  a file that has another name elsewhere on the disk, checked on the open file
  before anything is read, since that other name may lie outside the folder you
  meant to read. The REST service always sets it.
- **A first look at the desktop app: SolidSeas Viewer (preview).** A small
  Windows program, `SolidSeasViewer.exe`, that opens a folder and lists every
  SOLIDWORKS document in it and below it with a thumbnail, the version that
  saved it and when it changed, in a list or as icons. Pick a document to see
  its type, version, configurations, material and units, the stored preview,
  its custom properties as typed values, an assembly's components with where
  each one sits and how many of each file it uses (in any configuration), a
  drawing's sheets and views, where each referenced file is now within the
  folder you opened, the paths and user names the file would reveal, and the
  same JSON the command line prints. It can save a part's Parasolid bodies or
  any document's preview image into a folder you choose, and copy the summary
  JSON. It is read-only: it never writes to, locks or changes a file or
  folder it reads, refuses to write into the folder you opened, and never
  uses the network. A damaged or unreadable file shows its error code and
  message instead of stopping anything. Run it from a checkout with
  `python -m solidseas_app`, or build the executable with
  `scripts\build-viewer.ps1`; the README says how.

### Changed

- **SolidSeas Viewer (preview), after its first review.** Text from a document
  is now always shown as plain text, tooltips included: a custom property or a
  stored path holding an `<img>` tag used to be drawn as a picture, and hovering
  it could make Windows connect to a server the file named. The children of a
  suppressed sub-assembly are greyed and marked "suppressed (parent)", as
  SOLIDWORKS treats them. The document list puts Status next to Type, shows
  the Status and Folder columns only when they have something to say, gives
  way with Size and then Modified when the name would get too narrow, keeps
  each name's extension in view, and lets you show or hide columns from the
  header's right-click menu. SOLIDWORKS lock files are hidden unless you ask for
  them under View, folder counts count documents that were read, and the status
  bar says "assemblies" and "could not be read". Errors and statuses read as
  sentences ("Damaged or incomplete", "The file is empty", "This is a STEP file
  with a SOLIDWORKS extension") with the code kept under "Technical details",
  and an export the write guards refuse is explained in the window's own terms
  instead of naming command-line options; Export stays off until a folder is
  given. A date property shows its day only. A document that was locked when
  the folder was listed is read again when you select it. A document with
  thousands of properties or instances no longer holds the window: each list
  shows the first 2,000 rows and says how many more there are, the Raw JSON
  tab shows the first million characters (Copy Summary JSON copies them all),
  and large previews are decoded off the window's thread. The self-test's
  screenshots and report go through the same write guards as the exports.
- **The output guards recognise another name for the same folder.** The
  command line refused to write in or below a source folder by comparing path
  text, so the same folder reached as `\\localhost\C$\...`, `\\127.0.0.1\C$\...`
  or through the machine's own name got through. The guards now also compare
  the folders themselves, which catches administrative shares, a second share
  of one folder and mount points. An existing output that is a symbolic link
  or a junction is no longer replaced even with `--force`, since writing would
  follow it, and every refusal names its rule in the error's `detail`.
- **Paths with accents and other scripts are found whole.** The path scan
  behind `doc.embedded_paths()` used to see only ASCII, so it cut a path such
  as one through a folder named "Größe" or "Детали" at its first non-ASCII
  character. It now reads stored strings to their stored length and other
  text as UTF-16 or UTF-8, so it finds such paths whole and no longer runs on
  into the bytes after a string. Matches with no name in them, such as `f:\!`
  inside compressed data, are no longer reported.
- **Property types are machine tokens.** `Property.type` is now `"text"`,
  `"number"`, `"boolean"`, `"date"` or `"other"` instead of the labels
  SOLIDWORKS shows ("Text", "Yes or no"); `Property.type_label` still gives
  the label. Date properties now come back as dates rather than text, and a
  value that does not parse as its type is None with a warning instead of the
  raw text.
- **`property_values()` with no configuration uses the active one.** It used to
  return only the file-level properties. Now it applies the active
  configuration's own properties on top, like `effective_properties()`. Pass a
  configuration name to choose another; an unknown name raises
  `ConfigurationNotFoundError`.
- **An unknown document kind is None, never "unknown(n)".** If a file's type
  marker names something other than a part, assembly or drawing, the type falls
  back to the file extension and a warning says so.
- **"Permission denied" is no longer reported as "locked" on Linux.** A file
  you may not read raises `PermissionError` on every operating system; only a
  Windows sharing or byte-range lock raises `LockedFileError`. A folder passed
  as a document raises `IsADirectoryError` on Windows too.
- **Warnings carry codes.** Each entry in `doc.warnings` is still a string you
  can show, and now also has a `code`, the `stream` it concerns and the
  `message`.
- **Crafted files with absurdly long numbers in stream names or attributes**
  are read as data instead of raising a Python `ValueError`.
- **Command-line JSON has a new shape.** Every `--json` result is now an
  envelope, `{"ok", "kind", "schema_version", "solidseas", "source", "data"}`,
  whose `data` is exactly what the Python API returns; a failure has `error`,
  an object with a stable code, in place of `data`. `info` prints the document
  summary, and `props` prints the properties as a bill of materials sees them
  for the active configuration (`--configuration` and `--view` choose others).
- **A safety refusal exits 3 instead of 2**, so exit 2 always means the
  arguments were wrong. `batch` exits 4 instead of 1 when some files failed,
  and `parasolid` exits 0 with `bodies: 0` instead of 1 when a document holds
  no body.
- **Batch reports.** Cloud placeholders and linked documents get a row of their
  own instead of being opened or silently left out. `report.jsonl` holds each
  document's summary JSON, and `report.csv` puts an apostrophe before any cell
  that starts with `=`, `+`, `-` or `@`, so a value taken from a file never runs
  as a spreadsheet formula.
- **Hidden means what SOLIDWORKS shows.** SOLIDWORKS marks every suppressed
  component as hidden in the file, whatever its visibility, so suppressed
  components used to come back hidden. `hidden` now follows the
  configuration's display state, and a suppressed component is hidden only
  when that says so, as SOLIDWORKS itself reports it.
- **A drawing has no active configuration.** Drawings store the save date
  where parts and assemblies store the active configuration's name, and that
  date used to be reported as the active configuration. It is now None.
- **The stability policy is in effect.** `docs/API.md` is no longer
  provisional. Its stable parts (the public Python names, the JSON kinds and
  their schema versions, the error and warning codes, the command line's
  commands, options and exit codes, and the service's routes and parameters)
  change only in a minor release, with a migration note here; the parts it
  marks provisional may still change in any minor release.
- **`Document.info()` is deprecated and warns.** Use `doc.summary()`, the same
  document summary the command line and the service return. `info()` keeps
  answering in its 0.1 shape until 0.3.0 at the earliest.
- **`Reference.quantity` is deprecated and warns.** It counts the instances of
  every configuration and every sub-assembly together, which is no
  bill-of-materials quantity. Use the per-configuration counts of
  `doc.components()` or of the `references` JSON. `doc.references()` keeps
  working as before, and each reference now also carries its file `key`.
- **Documents held open read less.** With `hold_open=True` a document reads
  only what it is asked for: opening a 2015+ file reads its directory, and a
  legacy file no longer reads and unpacks every compressed stream to learn its
  size. The results are the same as before for every file in the development
  corpus.

- **Licence is now Apache-2.0.** The repository started with an MIT licence;
  it now uses Apache-2.0, which adds an explicit patent grant and lets
  SolidSeas build on other Apache-2.0 CAD projects.

### Fixed

- **The service runs under a Windows service account.** Started as LOCAL
  SERVICE or NETWORK SERVICE, `solidseas serve` refused its own token file,
  because Windows names those accounts by a short alias (`LS`, `NS`) in a
  file's access list. It now compares the accounts themselves, so the service
  can run from a Scheduled Task under LOCAL SERVICE. A token file that any
  other account can read still stops the start.
- **Running without a console window.** Under `pythonw.exe`, for example from
  a Scheduled Task that should not open a window, every command ended at its
  first line of output, because there was nowhere to write it, and the service
  never started. Output and log lines now go nowhere instead; exit codes are
  unchanged.
