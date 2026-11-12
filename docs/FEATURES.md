# What SolidSeas does

Every feature that ships in this release, what it needs and how far along it is.
Each line links to the page that explains it.

## How to read the status

| Status | Means |
|---|---|
| **Stable** | Its names, options, JSON, exit codes and routes change only under the stability policy in [API.md](API.md) section 9. |
| **Provisional** | It works, and is tested, but its names, options and output may still change in any release, with a note in the CHANGELOG. |
| **Preview** | A part of SolidSeas Viewer, the desktop app, which is an early, read-only preview as a whole. |
| **Experimental** | It works and is switched on, but its results may be incomplete or wrong, and it may change between versions. The viewer tags it "Experimental" beside its menu entries. Check what it makes before you rely on it. |
| **In development** | Parts of it are not built yet. The viewer tags it "In development". |

Nothing needs SOLIDWORKS unless the "Needs" column says so. Please report
problems at https://github.com/SolidSeasOrg/Solidseas/issues.

## The library and the command line

The `solidseas` Python package and its `solidseas` command read SOLIDWORKS files
without SOLIDWORKS, on Linux and Windows, with Python 3.11 or newer. Every
command opens files read-only and prints JSON with `--json`.

| Feature | What it does | Status | Needs | Guide |
|---|---|---|---|---|
| Reading documents | `info`, `props`, `configurations`, `components` and `references` give a part's, assembly's or drawing's summary, custom properties, configurations, component tree with positions and referenced files; `references --resolve` finds where each referenced file is now | Stable | | [The command line](guide/command-line.md) |
| Path report | `paths` lists every path and user name a file, and each document nested in it, would reveal to whoever receives it | Stable | | [The command line](guide/command-line.md#commands) |
| Folder listings | `list` lists the documents in a folder with their properties and previews | Stable | | [The command line](guide/command-line.md#commands) |
| Previews | `preview` saves the image a file stores; for another 3D format, one rendered from its model | Stable (rendering: Provisional) | | [API.md](API.md) 7.1 |
| Streams | `streams` and `dump` list and extract the raw streams inside a document | Stable | | [API.md](API.md) 7.1 |
| Parasolid export | `parasolid` writes a part's bodies as `.x_b` and `.x_t`, per configuration; an assembly as one file with every part placed | Stable (an assembly's file: Provisional) | | [Parasolid files](guide/command-line.md#parasolid-files) |
| Batch runs | `batch` writes summaries, previews and Parasolid files for a whole folder, with a CSV report | Stable | | [Parasolid files](guide/command-line.md#parasolid-files) |
| Bills of materials | `bom` gives an assembly's BOM, top level, parts only or indented, numbered as SOLIDWORKS numbers it, as a table, CSV or JSON | Provisional | | [Where Used and BOMs](guide/where-used-and-bom.md#bills-of-materials) |
| Export for 3D printing and STEP | `export` writes a part or assembly as 3MF or STL, and a part as STEP AP214 of its exact geometry | Provisional | | [3D Print and STEP export](guide/3d-print.md#from-the-command-line) |
| Other 3D formats | STEP, Parasolid, ACIS SAB, Alibre Design, 3MF, STL, OBJ, PLY, OFF, glTF and AMF files are read, listed, previewed and exported to STL and 3MF | Provisional | | [Every 3D format](guide/formats.md) |
| IGES and BREP | `convert` writes IGES, BREP or STEP, and IGES and BREP files are read | In development | the OCCT backend extension, not yet offered in a release | [IGES and BREP](guide/command-line.md#iges-and-brep) |
| Folder catalog | `index`, `where-used`, `search`, `duplicates`, `missing`, `changes`, `catalog`, `catalogs` and `clear-index` keep an index of project folders and answer which assemblies and drawings use a part | Provisional | | [API.md](API.md) 3.18 and 7.1 |
| A file's versions | `history`, `snapshot` and `diff` list a file's versions from Git or from snapshots, and say what changed between two of them | Provisional | | [A file's versions](guide/command-line.md#a-files-versions) |
| Drawings | `drawing new`, `export`, `update`, `check`, `show` and `settings` make and check drawings of parts; it never signs or releases one | Provisional | | [Drawings](guide/drawings.md#from-the-command-line) |
| Native SOLIDWORKS parts | `sldprt` writes a `.SLDPRT` from a SolidCraft design, a SolidSeas design file or a recorded CadQuery model: rectangles on the Front Plane extruded blind, one round hole through a single box, and a few fillets | Provisional | to record a CadQuery model, CadQuery (`solidseas[cad]`) | [SOLIDWORKS parts from a design](guide/command-line.md#solidworks-parts-from-a-design) |
| JSON schemas and versions | `version` prints the version and each JSON kind's schema version; `schema` prints a kind's JSON Schema | Stable | | [API.md](API.md) 7.1 |
| Python library | `open_document`, `scan` and the rest of the public API, with the same JSON as the command line | Stable, apart from what API.md marks provisional | | [The Python library](guide/python-library.md) |
| Conversion through SOLIDWORKS | `python -m solidseas.swapi convert` converts documents to STEP, Parasolid, STL and 3MF in a hidden SOLIDWORKS of SolidSeas' own, never your open session | Provisional | Windows, SOLIDWORKS, the bridge (`SolidSeas.SwBridge.exe`) | [API.md](API.md) 3.22 |

## The local API and connectors

| Feature | What it does | Status | Needs | Guide |
|---|---|---|---|---|
| REST service | `solidseas serve` answers the same reads over HTTP on 127.0.0.1, with a bearer token, for another program or service | Stable (`/v1/bom`, `/v1/mesh`, the catalog routes, `--formats`, `--config` and `--allow-origin`: Provisional) | | [The REST service](guide/command-line.md#the-rest-service) |
| Reference viewer | `serve --viewer` adds a web page that lists the folders, draws a part or assembly in 3D and shows a BOM | Provisional | | [The REST service](guide/command-line.md#the-rest-service) |
| OpenAPI description | `solidseas openapi`, `GET /v1/openapi.json` and `docs/openapi.json` describe the service for HTTP tools and code generators | Provisional | | [API.md](API.md) 8.19 |
| MCP server for files | `solidseas mcp` lets an AI app such as Claude Desktop or Claude Code read the folders you name, read-only | Provisional | an app that speaks MCP | [MCP.md](MCP.md#reading-your-cad-files-from-any-mcp-app) |
| Connector page | Settings > Connector in the viewer runs the local API for the open folder and shows the configuration an AI app needs | Preview | Windows | [Connect other apps](guide/connector.md) |
| The executable's command line | `SolidSeasViewer.exe --cli ...` runs any `solidseas` command without Python installed | Preview | Windows | [Connect other apps](guide/connector.md#ai-apps-mcp) |

## SolidSeas Viewer

The desktop app, for Windows. It is a read-only preview as a whole: it never
changes your files, and writes only the exports, prints and drawings you ask
for.

### Browsing and 3D

| Feature | What it does | Status | Needs | Guide |
|---|---|---|---|---|
| Folder browser | The folder tree, the file list as details or icons with thumbnails, the name filter and the quick filter's buttons, File > Open File... and Recent Folders | Preview | | [The viewer](guide/viewer.md) |
| Details tabs | Overview, Properties, Components (with positions), BOM, References, Where Used, History, Paths and Preview for the document selected, and Back to the document you came from | Preview | | [The viewer](guide/viewer.md#the-window) |
| Every 3D format | STEP, Parasolid, Alibre Design, ACIS, 3MF, STL, OBJ, PLY, OFF, glTF and AMF files listed, previewed and drawn in 3D beside the SOLIDWORKS documents | Preview | | [Every 3D format](guide/formats.md) |
| 3D view | Rotate, pan and zoom parts and assemblies, with a view cube, Home, exploding, picking, transparency, Hide and Isolate per component, kept for each document | Preview | a graphics card with OpenGL | [Settings and the 3D view](guide/settings.md#the-3d-view) |
| Open and Show in File Explorer | Opens a file in the program Windows opens it with, or shows it in its folder | Preview | | [Opening a file in its own program](guide/viewer.md#opening-a-file-in-its-own-program) |
| Open in F3D | Opens a STEP, IGES, STL, 3MF or other mesh file in the F3D viewer | Preview | F3D, installed by you | [Opening a file in F3D](guide/viewer.md#opening-a-file-in-f3d) |
| Settings window | Every setting in one window: General, 3D View, 3D Print, Drawings, AI Assistant, Extensions and Connector | Preview | | [The Settings window](guide/settings.md#the-settings-window) |

### BOMs, where-used and versions

| Feature | What it does | Status | Needs | Guide |
|---|---|---|---|---|
| BOM tab | An assembly's bill of materials, top level, parts only or indented, with File > Export BOM to CSV or JSON | Preview | | [Bills of materials](guide/where-used-and-bom.md#bills-of-materials) |
| BOM editor | Edit BOM... on the BOM tab: choose columns, reorder and hide rows, type over cells, save as a `.ssbom` file and export CSV, Excel or PDF | Preview | | [Bills of materials](guide/where-used-and-bom.md#bills-of-materials) |
| Where Used | Indexes each folder you open, then shows which assemblies and drawings use a document, and finds documents by part number or property | Preview | | [Where Used](guide/where-used-and-bom.md#where-used) |
| History tab | A file's Git commits or snapshots, newest first, with each one's preview and what changed in it; Take Snapshot and Compare with Working Copy | Provisional | | [A file's history](guide/viewer.md#a-files-history) |

### Conversion and export

| Feature | What it does | Status | Needs | Guide |
|---|---|---|---|---|
| Export STEP | File > Export STEP writes the part or assembly shown as STEP AP214 of its exact geometry | Preview | | [Exporting STEP](guide/3d-print.md#exporting-step-for-other-cad-systems) |
| Export Parasolid, Preview Image and for 3D Printing | File menu exports of the document's Parasolid bodies, its stored preview, and STL or 3MF | Preview | | [What the viewer writes](guide/viewer.md#what-the-viewer-writes) |
| Convert | File > Convert writes IGES, BREP or STEP, shown only while the OCCT backend is on | In development | the OCCT backend extension, not yet offered in a release | [IGES and BREP files](guide/formats.md#iges-and-brep-files) |

### 3D Print

| Feature | What it does | Status | Needs | Guide |
|---|---|---|---|---|
| 3D Print | One click exports the part or assembly shown as 3MF, STL or STEP, as a new dated file next to the model, and opens it in your slicer | Preview | a slicer: Bambu Studio, OrcaSlicer, PrusaSlicer, UltiMaker Cura, Creality Print, ElegooSlicer, Snapmaker Orca, QIDI Studio, Anycubic Slicer Next, Orca-Flashforge, SuperSlicer or any program you choose | [3D Print](guide/3d-print.md) |
| Open 3MF and STL Files As They Are | Sends your own 3MF or STL file to the slicer unexported; off by default, because the slicer may then save over it | Preview | | [Opening 3MF and STL files as they are](guide/3d-print.md#opening-3mf-and-stl-files-as-they-are) |

### Drawings

| Feature | What it does | Status | Needs | Guide |
|---|---|---|---|---|
| Drawings of parts | File > New Drawing and Make Drawing draw a SOLIDWORKS, STEP, Parasolid or Alibre Design part with views, dimensions and a title block, as a `.ssdrw` file with a PDF and a DXF stamped PRELIMINARY until released | Experimental | | [Drawings](guide/drawings.md) |
| Drawings of assemblies | Views, a parts list and item balloons, with no dimensions | Experimental | | [Making a drawing](guide/drawings.md#making-a-drawing) |
| Editing, signing and releasing | The drawing editor, its checks list, signatures, release and revisions, and Email PDF | Experimental | for Email PDF, webmail, classic Outlook or Thunderbird | [Editing a drawing](guide/drawings.md#editing-a-drawing) |

### The AI assistant

| Feature | What it does | Status | Needs | Guide |
|---|---|---|---|---|
| Modeling assistant, Review mode | Tools > Modeling Assistant drafts SOLIDWORKS API code from a plain description; you read it and press Run | Experimental | Windows, SOLIDWORKS, the CAD Bridge extension, and an AI key (Anthropic, OpenAI or Gemini) or an Ollama server | [The modeling assistant](guide/assistant.md) |
| Modeling assistant, Automatic mode | Plans a goal once and carries it out step by step from a closed set of checked operations, with Keep and Revert | Experimental | as Review mode | [Automatic mode](guide/assistant.md#automatic-mode) |
| The assistant in a chat app | `SolidSeasViewer.exe --mcp` lets Claude Desktop or Claude Code read the parts open in your SOLIDWORKS and build in them | Experimental | Windows, SOLIDWORKS, the CAD Bridge extension, an app that speaks MCP | [MCP.md](MCP.md#the-modeling-assistant-needs-solidworks-on-windows) |
| Machine policy | Lets an administrator turn off Automatic mode, pictures or extensions, or keep document data on the PC | Preview | Windows, an administrator | [For administrators](guide/assistant.md#for-administrators-restricting-solidseas-on-a-pc) |

### Extensions

Extensions are switched on under Tools > Extensions. The packaged ones are zip
files on each release's page.

| Feature | What it does | Status | Needs | Guide |
|---|---|---|---|---|
| CAD Bridge | Connects SolidSeas to your own SOLIDWORKS on this PC, for the assistant's live and Automatic modes and its chat tools | Experimental | Windows, SOLIDWORKS 2024 or later, its package | [Extension packages](guide/installing.md#extension-packages) |
| Video export | Save Animation in the 3D view: the model turning, exploding and collapsing, as an animated GIF or MP4 | Experimental | its package | [EXTENSIONS.md](EXTENSIONS.md#9-the-extensions) |
| Gridfinity | Gridfinity bins for your tools, made from photos of them, as STL files to print, through the assistant's chat tools | Experimental | Tracefinity, on this PC or a server of yours; an app that speaks MCP | [GRIDFINITY.md](GRIDFINITY.md) |
| SolidCraft | SolidCraft, a free parametric CAD program, in the chat: the assistant models, measures and exports new parts without SOLIDWORKS | Experimental | its package; an app that speaks MCP | [EXTENSIONS.md](EXTENSIONS.md#9-the-extensions) |
| OCCT backend | Reads IGES and BREP files and writes IGES, BREP and STEP through Open CASCADE | In development | its package, not yet offered in a release | [IGES and BREP files](guide/formats.md#iges-and-brep-files) |

## Windows only

These parts run only on Windows:

- SolidSeas Viewer, its installer and `SolidSeasViewer.exe`;
- everything that drives SOLIDWORKS: the CAD Bridge, the modeling assistant, its
  chat tools and conversion through SOLIDWORKS;
- AI keys, which are kept in Windows Credential Manager;
- the machine policy, which an administrator sets in the registry.

The library, the command line, the REST service and `solidseas mcp` run on
Linux and Windows.

## What comes next

[ROADMAP.md](ROADMAP.md) lists each phase, what is built and what is still to
come.
