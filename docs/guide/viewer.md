# The viewer

SolidSeas Viewer is an early, read-only preview of the desktop app. Open a
folder and browse its parts, assemblies and drawings: thumbnails, properties,
configurations, component trees with positions, bills of materials, drawing
sheets, where each referenced file is now, and the paths and user names each
file would reveal. STEP, Parasolid, STL, 3MF, OBJ, PLY, OFF, glTF, AMF, ACIS
and Alibre Design files in the folder are listed and shown too (see
[Every 3D format](formats.md)).

To get it, see [Installing SolidSeas](installing.md). From a checkout, run
`python -m solidseas_app [FOLDER]`.

## What the viewer writes

The viewer never changes a file. It writes only:

- the exports you ask for (Parasolid, STEP, a preview image, a BOM, and STL or
  3MF from File > Export for 3D Printing), into a folder you pick outside the
  one you opened;
- the files 3D Print sends to your slicer, each a new file next to the model it
  was made from, or in the system's temporary folder (see [3D Print](3d-print.md));
- drawings you make, next to the part or in a folder you choose (see
  [Drawings](drawings.md)).

The one way a file of yours can change is a setting you turn on yourself: with
Open 3MF and STL Files As They Are, your slicer opens your own 3MF or STL file,
and saving there replaces it. Open, which hands a file to its own program, is
the other: that program may save over it (see
[Opening a file in its own program](#opening-a-file-in-its-own-program)).

## Experimental features

Some features are on but not finished, and say so with a small Experimental or
In development tag beside their menu entries, with a note on their Settings
page. Their results may be incomplete or wrong, and they may change between
versions. Please report problems at
https://github.com/SolidSeas/SolidSeas/issues.

- **Experimental:** drawings (New Drawing, Open Drawing, Make Drawing and
  Drawing Settings, switched on by default; turn them off under Settings >
  Drawings, and check every drawing before you use it; until a drawing is
  released its PDF and DXF carry the PRELIMINARY stamp), the modeling
  assistant, and the Gridfinity, video export, SolidCraft and CAD Bridge
  extensions.
- **In development:** the OCCT backend extension, which reads IGES and BREP
  files ([Every 3D format](formats.md#iges-and-brep-files)).
- **On the command line,** `solidseas drawing`, `history`, `snapshot`,
  `diff`, `sldprt`, `convert` and `export` (with its `--check`), and the REST
  service's `/v1/bom`, `/v1/mesh`, the catalog routes (`--catalog`, among them
  `/v1/duplicates`, `/v1/missing` and `/v1/changes`), the other formats
  (`--formats`) and the reference viewer (`serve --viewer`) are provisional and
  may change too.

## The window

The folder tree on the left chooses which folder, and its subfolders, to show.
The middle pane lists the folder's documents, as details or as icons (View >
Details or Icons), with a filter box above that narrows them by name, and, once
the folder is indexed, by part number, description or property value (see
[Where Used](where-used-and-bom.md#where-used)). The details panel on the right
shows the selected document on a set of tabs:

| Tab | Shows |
|---|---|
| Overview | the document's preview image, when it has one, and its summary; for another format, its schema, units, writer, counts and size |
| Preview | the stored thumbnail, which pans and zooms, and the 3D view when it is on |
| Properties | the custom properties, each with its value, type and expression; Computed marks a value SOLIDWORKS worked out at the last save from a link to a model value or another property, or from an equation, which can be out of date |
| Components | an assembly's instances with their positions, and its Files table; a drawing's views and models |
| BOM | an assembly's bill of materials (see [Bills of materials](where-used-and-bom.md#bills-of-materials)) |
| References | where each referenced file was found |
| Paths | the paths and user names the file would reveal if sent |
| Where Used | the assemblies and drawings that use the document |
| Raw JSON | the document as the library's JSON |

To open a folder, use File > Open Folder... (Ctrl+O), or File > Recent Folders
for one you opened before. A folder opened before shows its last list at once
(see [Folders and their indexes](settings.md#folders-and-their-indexes)). File >
Open File... opens one file of any format SolidSeas reads.

## The file list and its quick filter

Under the filter box sits a row of small toggle buttons, one for each type of
document the opened folder holds, as the Open Recent dialog in SOLIDWORKS has
for parts, assemblies and drawings. It is the list's one filter by type: turn on
several buttons for a family of formats, the meshes say.

The buttons come in this order:

1. SOLIDWORKS parts, assemblies and drawings.
2. The formats SolidSeas reads: STEP, STL, 3MF, Parasolid text (X_T) and binary
   (X_B), ACIS binary (SAB), OBJ, PLY, OFF, glTF and GLB, AMF, and Alibre Design
   parts and assemblies. ACIS text (SAT) has a grey button beside SAB's:
   SolidSeas does not read those files yet, and lists them as not read.
3. Grey, as the list shows their files, the formats it lists but cannot read
   yet: IGES (`.igs` and `.iges` share a button) and BREP, listed while the OCCT
   backend extension is off and read once it is on (their buttons then take the
   colour of the formats it reads), and, with View > Show > Files SolidSeas
   Cannot Read on, Alibre Design drawings and packages, Inventor, Solid Edge,
   Fusion and eDrawings files by their kind, 3D XML and VRML.
4. Any other type, in alphabetical order, on a grey badge that shows its
   extension (on two lines when it has five or six letters, and its first six
   when it has more; the tooltip names it in full).

Each button is named after its format (Parasolid text, Alibre Design part,
Inventor assembly), in the words the [format list](formats.md) uses. A file
counts as what the folder listing found it to be: a STEP file saved with a
`.SLDPRT` name is under STEP, and the list's Type column calls it STEP too.
[Every 3D format](formats.md) says which files are listed.

How the buttons behave:

- With no button on, every type shows. Turn one on to show only that type; turn
  on several to show all of them. All turns every button off.
- The buttons narrow whatever the folder tree, the name filter and the index's
  search show, and those narrow the buttons' result in turn.
- A button's tooltip names its type and says how many files of it the list
  would show with the other filters as they are, and how many of those could
  not be read (a file that could not be read counts under the type its name
  says; so does one whose geometry turned out unreadable), or that SolidSeas
  cannot read the format yet, or, for IGES and BREP, that the OCCT backend
  extension opens them (Tools > Extensions).
- Tab reaches each button and Space turns it on or off; each has an accessible
  name for screen readers.
- When the pane is too narrow for the row, it wraps onto another line rather
  than widen the pane.
- Opening another folder keeps the types that are on where that folder has them
  and turns the others off; their buttons go. When none of them is there, the
  quick filter is off and the whole folder shows.
- While the folder is being listed (File > Reload included), the row keeps its
  buttons, so it does not jump and a button keeps the keyboard focus, and the
  buttons that are on keep filtering, so you can see why the list is filtered.
  A listing you cancel, or one that fails or stops early, does not show which
  types the folder lacks, so the types that are on stay on.
- A type that is on always has its button. Hiding the lock files (View > Show
  SOLIDWORKS Lock Files), or the files SolidSeas cannot read (View > Show >
  Files SolidSeas Cannot Read, which leaves IGES and BREP files listed), turns
  off a type that only they had, as opening
  a folder without it does; a type whose files are all hidden has no button.
- Opening a file, or a component's file from an assembly, turns its type on
  when the quick filter would hide it, and Back puts the buttons back as they
  were.
- With Settings > Remember Last Folder and Layout on, the types that are on are
  remembered with the layout.

## The preview

When a document has a preview image, the Overview tab shows it above the summary. Click it, or
select it and press Enter or Space, to see it on the Preview tab.

The Preview tab's image pans and zooms:

- roll the wheel to zoom toward the pointer;
- drag with the left or right button to pan;
- double-click or press Fit to fit;
- press 1:1 for one image pixel per screen pixel.

The bar shows the zoom. With Settings > Interactive 3D View on, the tab also
draws parts and assemblies in 3D; [Settings and the 3D view](settings.md#the-3d-view)
covers it.

## Opening a component's file

Double-click a part's instance on an assembly's Components tab (or a row of its
Files table, a drawing's view or model, or a file on the References tab) to go
to that file. A sub-assembly's row opens and closes on a double-click, as in
Explorer, so select it and press Enter to go to its file. Enter works on any of
these rows.

Right-click for:

- **Open** and **Show in File Explorer**, which open the file in its own
  program and show it in its folder (see the next section);
- **Go to file** and **Show in folder list**, which show it here. Show in
  folder list selects the file in the list and keeps the tab you are on.

The viewer goes where reference resolution found the file, searching the folder
you opened and its subfolders, and the stored path when it is on a drive of this
computer (unless Settings > General > Look for referenced files only in the
opened folder is on: see
[Where referenced files are looked for](settings.md#where-referenced-files-are-looked-for)):

- A file in the list is selected there. A part opens on its Preview tab, an
  assembly on its Components tab, in the configuration the instance uses. A
  part shows the configuration it was saved in: the status line says which one
  the instance uses, and when that is another one a note says so and the
  Overview and Properties tabs mark it. When the folder tree or the name filter
  hides the file, they widen just enough to show it.
- A file found outside the folder you opened is shown on its own in the details
  panel, with a note saying so; the list then has no selection.
- A virtual component opens as the document stored inside its assembly, with a
  note. With the 3D view on it opens in 3D, drawn from the mesh SOLIDWORKS
  keeps of it in the assembly. One stored inside a sub-assembly's own file
  offers to open that sub-assembly instead.
- When several files fit equally well, the viewer lists them and asks which one
  to open.
- A file that was not found is not opened: a message gives its stored path and
  why, for example that the path is on a network share, which SolidSeas never
  contacts.

**Back** (Alt+Left, the toolbar's Back button, the mouse's thumb Back button or
a keyboard's Back key) returns to the document you came from, with its tab,
configuration, selected row and list filters as they were, and its 3D view
exploded, turned and zoomed as you left it. Everything opened this way is
read-only, like the rest of the viewer.

## Opening a file in its own program

**Open**, on the toolbar, in the File menu and first on the right-click menu of
a file in the list, opens the file in the program Windows opens it with, as a
double-click in File Explorer does: SOLIDWORKS for a part, an assembly or a
drawing (a SOLIDWORKS already running is handed the document), the default
program for any other format. **Show in File Explorer**, beside it, opens the
folder that holds the file with the file selected (Show in Finder on a Mac).

Both are also on the right-click menu of every row that stands for a file: an
instance or a file on the Components tab, a drawing's views and models, a BOM
row, a reference, a Where Used row in the folder you opened, a file in the 3D
view's legend and a component in the 3D view. A row's file is the one reference
resolution found, as Go to file finds it; Go to file and Show in folder list,
under them, show the file here in the viewer instead.

SolidSeas writes nothing and starts no program for either: Windows does, as you
asked. The program that opens the file can change it, though. A document you
open in SOLIDWORKS and save there is saved over, as it would be from File
Explorer, and a cloud file not yet on this computer is downloaded by its service
as the program opens it.

Open is offered only for a file that is there, of a 3D format SolidSeas lists,
and never for a link or a SOLIDWORKS lock file. A component stored inside its
assembly, or one that was not found, has it greyed with the reason.

## More about the viewer

- [Every 3D format](formats.md): the formats the list shows and how.
- [Where Used and bills of materials](where-used-and-bom.md).
- [3D Print](3d-print.md) and [Drawings](drawings.md).
- [Settings and the 3D view](settings.md): settings, mouse and keyboard
  controls, the view cube and rotation.
