# The command line and the REST service

The `solidseas` command reads SOLIDWORKS and other 3D files without SOLIDWORKS,
so any system that can run a program can use it, and `solidseas serve` offers
the same over HTTP to another service. [API.md](../API.md) is the reference for
both, and for [the Python library](python-library.md), with recipes in Python,
curl and TypeScript.

To install it, see [Installing SolidSeas](installing.md#the-library-and-command-line-from-source).
The library, the command line and the REST service are stable since 0.2.0: their
public names, JSON, exit codes and routes change only under the stability policy
in [API.md](../API.md) section 9, apart from what it marks provisional.

## Commands

Every command prints JSON with `--json` and has documented exit codes:

```bash
solidseas list D:\Jobs\Example --include properties --json
solidseas components D:\Jobs\Example\frame.SLDASM --json
solidseas bom D:\Jobs\Example\frame.SLDASM --type indented --format csv -o D:\Exports\frame.csv
solidseas paths D:\Jobs\Example\frame.SLDASM      # what the file would reveal if sent
solidseas export D:\Jobs\Example\frame.SLDASM --format 3mf -o D:\Prints\frame.3mf   # for a slicer
solidseas export D:\Jobs\Example\bracket.SLDPRT --format step -o D:\Out\bracket.step  # exact B-rep
solidseas index D:\Jobs\Example                  # a catalog of the folder, in your cache folder
solidseas where-used D:\Jobs\Example\parts\bracket.SLDPRT   # which assemblies and drawings use it
solidseas search "pn:BR-100" "prop:Vendor=ACME" "desc:steel bracket"   # an argument with spaces is one value
```

`solidseas export` writes the same 3MF, STL and STEP files the viewer's
[3D Print](3d-print.md) does (API.md sections 3.17, 3.19 and 7.1).
`--include-hidden` writes the bodies SOLIDWORKS hides into a STEP, and `--sheets`
writes surface bodies beside solids (see
[Exporting STEP](3d-print.md#exporting-step-for-other-cad-systems)).
`solidseas drawing new` makes a drawing ([Drawings](drawings.md#from-the-command-line)).

### Parasolid files

`solidseas parasolid` writes Parasolid files for another CAD system, with no
SOLIDWORKS needed:

```bash
solidseas parasolid D:\Jobs\Example\bracket.SLDPRT -o D:\Out --text   # each body, per configuration
solidseas parasolid D:\Jobs\Example\frame.SLDASM -o D:\Out --text     # the whole assembly in one file
```

For a part you get one `.x_b` file (and with `--text` an `.x_t` file) for each
body of each configuration the part stores. For an assembly you get one file,
`frame_Default.x_b`, that holds every part of the active configuration (or the
one `--configuration` names) where the assembly places it: each part once,
placed by as many instances as use it, sub-assemblies kept as assemblies of
their own, and every instance named as in the FeatureManager tree, such as
`bracket-2`. Suppressed and hidden components are left out, and so are bodies
SOLIDWORKS hides unless you add `--include-hidden`. A component excluded from
the bill of materials is still written.

The component files are looked for in the assembly's own folder. If one is
missing or cannot be read, or a part does not store the bodies of the
configuration the assembly uses, nothing is written and the message says which
components are the problem. `--allow-partial` writes the rest and lists what was
left out, and `--other-configurations` writes such a part with the bodies it
does store, with a warning that they may not be the configuration the assembly
uses. The files have not yet been opened in a Parasolid kernel such as
SOLIDWORKS itself, so check an important one there before you send it.

`solidseas batch` writes the same files for a whole folder, each assembly as
one file next to its preview, named after the assembly with its extension, such
as `frame.SLDASM_Default.x_b`:

```bash
solidseas batch D:\Jobs\Example -o D:\Exports --text --allow-partial
```

`--configuration`, `--allow-partial`, `--other-configurations` and
`--include-hidden` work as they do for one assembly and apply to every assembly
in the folder; parts are written as before. An assembly that cannot be written,
or that does not have the configuration you named, gets an error row in
`report.csv` that says which components or which configuration, and the rest of
the folder is still done. With `--allow-partial` the `parasolid_left_out` column
says how many components each assembly left out, and `report.jsonl` names them.
Either way the run ends with exit code 4, so a script can tell. A file that is
already in the output folder is never replaced unless you add `--force`.

### SOLIDWORKS parts from a design

`solidseas sldprt` writes a SOLIDWORKS part (`.SLDPRT`) from a SolidCraft design
or a SolidSeas IR file, with no SOLIDWORKS needed (provisional):

```bash
solidseas sldprt D:\Designs\plate.solidcraft -o D:\Parts                  # D:\Parts\plate.SLDPRT
solidseas sldprt D:\Designs\plate.solidcraft -o D:\Parts --allow-partial  # leave out what it cannot write
```

Today a part can hold corner rectangles on the Front Plane, each extruded blind
away from it: the first makes the part's body and each later one a body of its
own. The features get the names SOLIDWORKS gives them, such as `Sketch1` and
`Boss-Extrude1`, and the command lists each one with its name in your design.
The extrusion depth stays editable in SOLIDWORKS; the sketch's dimensions are
not carried over, so the rectangle is kept as geometry.

If the design needs anything else, such as a fillet, a cut or a sketch on
another plane, nothing is written and the message lists every item. With
`--allow-partial` the part is written without them, the command lists what was
left out, and it ends with exit code 4 so a script can tell. A file that is
already there is never replaced, and the part is not written next to the design
unless you add `--allow-source-dir`. SolidSeas reads each part back before it
writes it. Parts like these open in SOLIDWORKS 2024 with their feature tree and
rebuild when you change a depth; other versions have not been tried, so open an
important one there before you rely on it.

## Other 3D formats

SolidSeas also reads 3D files of other formats (provisional, API.md 3.20): STL,
3MF, OBJ, PLY, OFF, glTF and GLB, AMF, Parasolid, STEP, ACIS SAB and Alibre
Design files are read now, and every one of them exports to STL and 3MF.

```bash
solidseas info part.stl                     # a model summary
solidseas preview part.stl -o out           # a preview of a file that stores none
solidseas export part.stl --format 3mf      # written for a slicer
solidseas list FOLDER --formats all         # every 3D file, the ones not read yet as unsupported
```

`solidseas list FOLDER --formats all` lists every 3D file, showing the formats
SolidSeas cannot read yet as `unsupported`. [Every 3D format](formats.md) lists
what is read from each.

### IGES and BREP

IGES and BREP files are read, and written, through the OCCT backend extension
([Every 3D format](formats.md#iges-and-brep-files)). Once its package is added
and it is switched on in the viewer's Tools > Extensions, the command line reads
these files as it reads STEP files, and `solidseas convert` writes them:

```bash
solidseas info part.igs                                   # read through Open CASCADE
solidseas export part.igs --format 3mf -o D:\Prints       # sewn into solids, then printed
solidseas convert bracket.SLDPRT --format iges -o D:\Out  # IGES (BRep mode) of the part
solidseas convert part.igs --format step -o D:\Out\part.step
solidseas convert part.step --format brep -o D:\Out       # Open CASCADE's own BREP
```

`convert` takes an IGES, BREP or STEP file, a SOLIDWORKS part or assembly, or a
Parasolid file, and writes `--format iges`, `brep` or `step` in millimetres. A
SOLIDWORKS document or a Parasolid file goes through the STEP SolidSeas writes
of it first, so the same bodies are written. The output follows the export's
rules: never next to the source unless you add `--allow-source-dir`, never over
a file unless you add `--force`. Without the extension, these commands stop
with a message that says what to add (`format_not_supported`, rule
`needs_extension`).

## The REST service

From another service, over HTTP on 127.0.0.1, with a bearer token from a file
only the starting account can read:

```bash
solidseas serve --root jobs=D:\Jobs
```

[SECURITY_REVIEW.md](../SECURITY_REVIEW.md) reviews the service for whoever has
to approve it. The service's `/v1/bom`, the catalog routes (`--catalog`) and the
other formats (`--formats`) are provisional and may change.

## One answer, three ways

For a document the JSON is the same whichever way you ask: the Python library,
the command line or the REST service. Folder listings and reference resolution
differ a little between surfaces (where paths start, a few defaults), as
[API.md](../API.md) section 1.2 lists.
