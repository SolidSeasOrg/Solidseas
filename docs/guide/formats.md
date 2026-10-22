# Every 3D format

Besides SOLIDWORKS documents, SolidSeas reads STEP, Parasolid, Alibre Design,
ACIS, 3MF, STL, OBJ, PLY, OFF, glTF and AMF files, and IGES and BREP files with
the OCCT backend extension. This page says what the viewer reads from each, how
such a file shows in the viewer, and which formats are listed but not read yet. For the same formats on the command line, see
[The command line](command-line.md#other-3d-formats).

## In the file list

The list shows every 3D file SolidSeas reads beside the SOLIDWORKS documents
(View > Show > All 3D Files, on by default). Each has:

- its format in the Type column;
- its schema, variant or the program that wrote it under Saved with;
- a thumbnail: the image the file stores, or one SolidSeas draws from its
  geometry once the folder is listed, kept in a cache in your user folder for
  the next time.

The [quick filter's buttons](viewer.md#the-file-list-and-its-quick-filter) show
one format, or several, at a time, and File > Open File... opens one file of any
of these formats.

## What the viewer reads

| Format | Files | What the viewer reads |
|---|---|---|
| SOLIDWORKS | `.sldprt`, `.sldasm`, `.slddrw` | everything the [viewer pages](viewer.md) describe |
| STEP AP203, AP214, AP242 | `.step`, `.stp`, `.p21` | B-rep solids and shells (tessellated by SolidSeas), faceted and tessellated geometry, assemblies with their placements, product names, colours, units and user properties |
| Parasolid | `.x_t`, `.x_b`, `.xmt_txt`, `.xmt_bin` | bodies, assemblies by their instances, the header's fields as properties |
| Alibre Design | `.AD_PRT`, `.AD_ASM` | the stored thumbnail, properties and configuration, the display mesh for the 3D view and the exact ACIS body for exports; an assembly's components found by their document GUID in the assembly's folder and placed, their placements read in centimetres (an assumption from one sample assembly, which a warning says). Verified on one Alibre release (ACIS version 2100) |
| ACIS | `.sab` | bodies of the version Alibre Design writes |
| 3MF | `.3mf` | objects, components and build items with their transforms, units, colours, metadata and the stored thumbnail |
| STL | `.stl` | binary and ASCII; millimetres are assumed, as STL states no unit |
| OBJ | `.obj` | groups as objects, colours from MTL files in the same folder; millimetres assumed |
| PLY, OFF | `.ply`, `.off` | ASCII and binary PLY with colours and comments; OFF text files |
| glTF | `.gltf`, `.glb` | the node hierarchy, buffers embedded or in the same folder, base colours |
| AMF | `.amf` | plain and zipped, constellations and colours |
| IGES, with the OCCT backend extension | `.igs`, `.iges` | solids, and surfaces sewn into solids where they close; the unit, the program that wrote it, the author and the date from the file's header |
| BREP (Open CASCADE's own), with the OCCT backend extension | `.brep` | solids, shells and faces, text or binary; millimetres are assumed, as a BREP file states no unit |

## IGES and BREP files

SolidSeas reads IGES files, and the BREP files of Open CASCADE, through the OCCT
backend extension. It is a package you add once: get it from the releases page
(Tools > Extensions > Get extensions), choose Add from file, and switch it on.
Until then these files are listed greyed, whether or not View > Show > Files
SolidSeas Cannot Read is on: their Status says Needs the OCCT backend, their
Overview says what to add, and the status bar counts them. Once you switch it
on, the folder shown is read again and they read like STEP files: the 3D view,
thumbnails, Export for 3D Printing, 3D Print and the index all take them. There
is no need to restart the viewer. Switching the extension off works the same
way, and a folder's saved index is kept for each choice, so the list always
matches the switch.

The extension uses Open CASCADE Technology, the open-source geometry kernel, in
a program of its own beside the viewer. Each file goes to it as a copy, never
your own file, and comes back as a STEP model that SolidSeas reads with its own
STEP reader. An IGES file often holds loose surfaces rather than solids: they
are sewn together where they meet within 0.01 mm, and the ones that close become
solids. Surfaces that stay open are shown as surfaces, and the file's warnings
say how many. If Open CASCADE's own check finds faults in the shape, a warning
says that too. A file that makes Open CASCADE stop, or that takes it more than
ten minutes, fails on its own with a message, and the next file starts afresh.

The extension also writes these formats. In the viewer, **File > Convert**
writes the file shown as another of them: a SOLIDWORKS part or assembly, a
Parasolid file or a STEP file as IGES or BREP, an IGES file as STEP or BREP, and
a BREP file as STEP or IGES. Pick the format as the file type in the save dialog,
or type the name with its extension. A SOLIDWORKS document goes as the STEP that
File > Export STEP writes of it, in the configuration shown, so the same bodies
are written and the same questions asked; use Export STEP itself for a STEP file,
which keeps an assembly's structure. The file is written outside the folder you
opened, and an existing file is replaced only when the save dialog asked you.
Convert is in the File menu only while the extension is on. On the command line,
`solidseas convert` writes an IGES, BREP or STEP file, a SOLIDWORKS part or
assembly or a Parasolid file as IGES, BREP or STEP (see
[The command line](command-line.md#iges-and-brep)).

The OCCT backend extension is marked In development: check what it reads
before you rely on it, and report anything wrong. Its package carries the
licences of Open CASCADE Technology (the GNU LGPL 2.1 with the Open CASCADE
exception) and of everything else it holds, shown under Details on the
Extensions page and in its licenses folder, and says where their source is.

## Formats listed but not read yet

Inventor, Solid Edge, Fusion, 3D XML, eDrawings, VRML and Alibre Design
drawings and packages are recognised but not read yet: View > Show > Files
SolidSeas Cannot Read lists them, greyed, without opening them. IGES and BREP
files are listed greyed while the OCCT backend extension is not on, with that
setting on or off, since adding the extension opens them. ACIS text
(`.sat`) is listed as not read too. An NX `.prt` is not listed at all, since
other programs use that extension too.

A file that uses a feature SolidSeas lacks (a 3MF extension it does not
implement, Draco-compressed glTF, a Parasolid file that needs a schema it does
not carry) says so instead of being shown wrongly.

## How such a file shows

The details tabs fit the file's format:

- **Overview** gives the format and its schema or variant, the units (marked
  when the file states none), the program that wrote it, the objects, bodies,
  faces, triangles and vertices read, and the size and box of the model.
- **Preview** shows the stored image or the one drawn from the geometry, and
  with the 3D view on draws the model. A format that stands models on Z (STL,
  3MF, OBJ...) is turned upright.
- **Components** lists an assembly's instances with their positions (STEP,
  3MF, glTF, AMF, Parasolid, Alibre Design). In the 3D view a click picks one,
  the Explode bar moves them apart, and Hide, Isolate and Transparency work as
  for a SOLIDWORKS assembly.
- **References**, for an Alibre assembly, says where each component file was
  found; Go to file goes there and Back returns.
- **BOM** and **Paths** are about SOLIDWORKS documents and are hidden.

The index holds these files too while they are listed, so Where Used asks it
about them, and the filter box finds them by their properties as well as their
names. For an Alibre part or sub-assembly, Where Used lists the Alibre
assemblies that place it. The index does not yet follow what a file of the
other formats uses, so Where Used says so when nothing uses one. A format
SolidSeas cannot read (VRML...) is not indexed, which Where Used says, and nor
are IGES and BREP files while the OCCT backend extension is off.

The 3D view turns, pans and zooms as for a SOLIDWORKS document, with the view
cube, Home, the turn about the point under the pointer, and the camera kept when
you come Back (see [Settings and the 3D view](settings.md)).

## Exporting and printing them

- **Export Preview Image** writes the preview shown.
- **File > Export for 3D Printing...** writes the part or assembly as STL or 3MF
  into a folder you choose.
- **File > Export STEP** writes a Parasolid file's part as STEP. For any other
  format it is off, and its tooltip says why.
- **3D Print** works as for a SOLIDWORKS document, STEP included (see
  [3D Print](3d-print.md#other-3d-formats)).

Settings > Open 3MF and STL Files As They Are (off by default) has 3D Print open
a 3MF or STL file the program takes as it is, so a slicer project keeps its
plates. The slicer then has your own file open, and saving there replaces it;
[3D Print](3d-print.md#opening-3mf-and-stl-files-as-they-are) says when it
applies.

## How they are read

None of these files is read in the window's own process. Two worker processes
of the viewer's, below normal priority and with a memory limit, read the
listing's entries, the details and the thumbnails. The 3D view has its mesh
process and the exports their own process, and the window receives only JSON,
PNG images SolidSeas wrote and vertex buffers. The workers start the first time
such a file is listed and end with the window.

The one exception is a compound file wearing a SOLIDWORKS extension, such as a
renamed Alibre file: the listing reads it as the SOLIDWORKS document its name
says, as it always has.

The viewer's self-test checks every format end to end; see
[`--self-test-formats`](building.md#checking-every-format).
