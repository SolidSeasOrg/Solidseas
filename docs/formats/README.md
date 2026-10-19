# File formats other than SOLIDWORKS

`docs/FORMAT.md` is the byte-level specification of SOLIDWORKS documents. The
documents in this folder do the same for every other 3D format SolidSeas reads,
one document per group of formats, each written by the branch that reads them.
`docs/API.md` section 3.20 is the programming interface they share.

| Document | Formats | State |
|---|---|---|
| [stl.md](stl.md) | STL, binary and ASCII | read (the reference reader) |
| [mesh.md](mesh.md) | 3MF, OBJ, PLY, OFF, glTF and GLB, AMF | read |
| [parasolid.md](parasolid.md) | Parasolid transmit files (`.x_t`, `.x_b`, `.xmt_txt`, `.xmt_bin`) | read |
| [step.md](step.md) | STEP AP203, AP214 and AP242 | read |
| [alibre.md](alibre.md) | Alibre Design parts and assemblies, ACIS SAB | read |

The registry (`solidseas.formats.registry`) also knows IGES, Inventor, Solid
Edge, NX, Fusion, 3D XML, eDrawings and VRML files, and Alibre Design drawings
and packages: a folder listing shows them with the status `unsupported` and
SolidSeas opens none of them. Two extensions other programs share are listed
only by content: a Solid Edge `.asm` when it starts with the compound-file
signature, and an NX `.prt` never (NX has no signature SolidSeas checks yet).

## Evidence labels

Every claim about a format carries one of three labels, as in `FORMAT.md`:

- **verified**, with its source: the published specification (named, with its
  version), a synthetic test in `tests/` (named), or a measurement on files
  (a count over the private corpus or a set of sample files, never a name or
  a value from them);
- **hypothesis**: what the evidence suggests, with what would settle it;
- **unknown**: not yet looked at, or not settled.

## How a format is told apart

`solidseas.formats.registry.detect` looks at the first 4 KiB of a file, its
size and its name (`docs/API.md` 3.20.3). The extension's own format wins when
its content test accepts the head; otherwise the content tests run in a fixed
order (compound files, zip packages, GLB, STEP, Parasolid, ACIS, IGES, PLY, OFF,
glTF JSON, OBJ, STL) and the first that accepts decides, with the warning
`extension_mismatch` when the extension named another format; otherwise the
extension decides, and that format's reader refuses content that is not its
own. Each content test is written in the format's document.

## Rules every reader keeps

A file is untrusted input. Every reader works through
`solidseas.formats._source` and keeps every bound of
`solidseas.formats.Limits` (`docs/API.md` 3.20.2): bytes, counts, nesting,
decompressed sizes and time. XML is parsed without DTDs or entities, JSON
strictly, zip members against a size, a total and a ratio, and a file a
document names is read only from inside the document's own folder or package.
Untrusted documents are read in worker processes by the service, the viewer and
folder listings with a pool, never in a window's process.
