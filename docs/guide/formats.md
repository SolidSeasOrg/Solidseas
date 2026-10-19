# Every 3D format

Besides SOLIDWORKS documents, SolidSeas reads STEP, Parasolid, Alibre Design,
ACIS, 3MF, STL, OBJ, PLY, OFF, glTF and AMF files. This page says what the
viewer reads from each, how such a file shows in the viewer, and which formats
are listed but not read yet. For the same formats on the command line, see
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

## Formats listed but not read yet

IGES, Inventor, Solid Edge, Fusion, 3D XML, eDrawings, VRML and Alibre Design
drawings and packages are recognised but not read yet: View > Show > Files
SolidSeas Cannot Read lists them, greyed, without opening them. ACIS text
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
SolidSeas cannot read (IGES...) is not indexed, which Where Used says.

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
