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
