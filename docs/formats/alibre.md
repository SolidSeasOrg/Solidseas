# Alibre Design and ACIS

SolidSeas reads Alibre Design parts (`.ad_prt`) and assemblies (`.ad_asm`)
without Alibre, in pure Python, and standalone ACIS SAB files (`.sab`) of the
version Alibre writes. `docs/API.md` 3.20.8 is the programming interface; this
document is what is known of the files.

**Evidence.** Everything here comes from the published ACIS chapter "SAT Format
7.0, Chapter 2: SAT Save File Format" (Spatial; a public copy is at
paulbourke.net/dataformats/sat/sat.pdf), the ezdxf ACIS notes (consulted, no
code adapted), [MS-CFB], ISO 10303-21 and ISO 10303-42, and black-box study of
**four sample files saved by one Alibre Design release**: three parts and one
assembly. No Alibre or Spatial program was installed, run, decompiled or
disassembled. Numbers about the samples are counts and ranges; no name, path,
GUID, property value or geometry from them is written here. Labels follow
`docs/formats/README.md`: **verified** (with its source), **hypothesis**,
**unknown**.

## 1. What is read, in one table

| Stream | Role | Read | Status |
|---|---|---|---|
| `VERSION` | the document's GUID and version | head | verified (4 of 4) |
| `PROP_DATA` | properties, fields, the thumbnail | head | verified (4 of 4) |
| `LIGHT_CONFIGURATION_DATA` | active configuration, part colour | head | verified, partly (4 of 4) |
| `STEP_DATA` | the design database (Part 21, `ALIBRE_SCHEMA`) | identification; inclusions of an assembly | verified (4 of 4) |
| `SAB_DATA` | the exact B-rep, ACIS SAB | header in the head; body for exports | verified (3 of 3 parts) |
| `MESH_DATA` | Alibre's display tessellation | dictionaries in the head; faces for previews | verified (3 of 3 parts) |
| `CONSTITUENTS` | the documents an assembly references | references | verified (1 of 1) |
| `IMPORT_DATA` | an imported body before any feature | never | verified role (2 of 3 parts hold one) |
| `AUTOGRAPH_DATA`, `DESIGN_PARAMETER_DATA`, `HOLE_OPERATIONS_DATA`, `EXTERNAL_THREAD_OPERATIONS_DATA`, `CUSTOM_ITEM_PROP_DATA`, `STANDARD_DESIGN_PROP_DATA` | feature and naming data; property streams empty in every sample | never | unknown |

What each caller gets:

| Caller | Part | Assembly |
|---|---|---|
| Listing, Preview tab | the stored bitmap, converted to PNG; without one, a preview rendered from `MESH_DATA` | the stored bitmap; without one, rendered from the resolved parts |
| Rendered previews and thumbnails, and the viewer's 3D view (`scene(prefer="display")`) | `MESH_DATA`; the B-rep when it is missing | each resolved part's `MESH_DATA`, placed |
| Export, 3D Print (`scene(prefer="bodies")`) | the B-rep tessellated (closed); `MESH_DATA` when the B-rep is missing, of an unverified version or gives no triangles | each part the same way, placed |
| `bodies()` | the B-rep as an in-memory Parasolid transmit | None |

## 2. Container and identification

A plain MS-CFB compound file, version 3, 512-byte sectors, root CLSID all zero,
every stream at the root, nothing compressed. Verified (4 of 4). SolidSeas opens
it with the same hardened `OleContainer` it uses for older SOLIDWORKS files,
reads at most `ole_streams` streams' directory entries, and reads each stream
only when needed, within its bound (`alibre_small_stream_bytes`,
`alibre_constituents_bytes`, `alibre_text_stream_bytes`,
`alibre_stream_bytes`).

A file is an Alibre Design document when it is a compound file with `VERSION`,
`PROP_DATA` and `STEP_DATA` at the root and the header of `STEP_DATA` names
`ALIBRE_SCHEMA` in its `FILE_SCHEMA`. Otherwise the reader raises
`unknown_format` (a SOLIDWORKS file renamed `.ad_prt`, say). The streams that
have one are checked against their content signature before use: `ACIS
BinaryFile` for `SAB_DATA`, `ISO-10303-21;` for `STEP_DATA`, and for
`MESH_DATA` an entry count followed by the key `SCHEMA_VERSION_KEY`. Verified
(4 of 4).

Which kind of document: a part has `SAB_DATA` or `MESH_DATA`, an assembly
`CONSTITUENTS` (verified, 3 and 1); a file with neither is a part or an assembly
by its design database's `DESIGNPART` or `DESIGNASSEMBLY`, and anything else
(a drawing renamed, say) is refused with `format_not_supported`, rule
`unsupported_variant`. A sheet metal part (`.ad_smp`) is read as a part, warned
`variant_unverified`: none was seen. Alibre drawings (`.ad_drw`) and packages
(`.ad_pkg`) have their own registry entries and are listed, not read.

## 3. `VERSION` and `CONSTITUENTS`

`VERSION` holds one string, a big-endian 16-bit length then the bytes: an XML
element `<Repository Guid=".." Name=".." V3Name=".." Type=".."/>`, then `:` and
the repository path (forward slashes, no extension), `|` and the document GUID
(36 characters, no braces), `||` and an integer, `|` and the document's version.
Verified (4 of 4, every stream parsed to its last byte). The element is parsed
with the safe XML reader; the rest by its separators. Any other shape is a
damaged stream: warning `stream_unreadable`, the document still opens.

`CONSTITUENTS` (assemblies) holds one such string per referenced document,
each followed by more text that is not read. Its GUIDs are the ones the design
database's inclusions reference (3 of 3); a disagreement is warned
`constituents_disagree`.

The repository path is the user's data: SolidSeas keeps it for
`references()` and never writes it into a warning.

## 4. `PROP_DATA`: properties, fields and the thumbnail

A run of entries to the stream's last byte (verified, 4 of 4): a key (big-endian
16-bit length and bytes), then three little-endian 32-bit integers (flags, type,
count), then `count` values of the type. Types: `0x14` string (big-endian 16-bit
length and bytes), `0x0A` 32-bit integer, `0x1E` double, `0x28` blob
(little-endian 32-bit length and bytes), and -1 with count 0, an empty entry.
Lengths are big-endian and numbers little-endian. Bounded by `prop_entries`,
`prop_values`, `text_bytes` and the bytes left; a damaged entry stops the read
with `stream_unreadable`, and the entries before it are kept.

- **Properties:** every entry except the file's own bookkeeping (`TotalSize`,
  `TransferSize`, `secureObjectType`, `subType`, keys starting `__`, the
  hatching defaults starting `Hatch`) and the thumbnail: strings as text,
  integers and doubles as numbers, all with scope `file`.
- **Fields:** `title` from `name`, `comments` from `description`, `author`
  from `Creation_Author`, `last_saved_by` from `Last_Modification_Author`,
  `created_utc` from `Creation_Time` and `last_saved_utc` from
  `Last_Modification_Time`. The times are strings of one form in every sample
  (verified, 8 of 8): two-digit day, three-letter English month, four-digit
  year, `hh:mm:ss`, a time zone abbreviation. A zone SolidSeas knows (UTC, GMT,
  the North American and the common European ones) gives a UTC time; any other
  form or zone leaves the field empty, and the text stays a property.
- **`application`:** `Alibre Design`, and the version at the end of
  `stepFileVersion` (comma-separated numbers, given with dots).
- **Thumbnail:** the blob under `snapshot`, a whole Windows bitmap file (256
  by 256, 24 bits, uncompressed, bottom-up in 3 of 4 samples; one small part
  stores none). `preview()` returns it as stored (`image/bmp`, stream
  `PROP_DATA`) after checking its header; listings, the viewer and the service
  receive it as a PNG SolidSeas writes (`docs/API.md` 3.20.1).

## 5. `LIGHT_CONFIGURATION_DATA`

Four bytes (zero in every sample), the active configuration's name (big-endian
16-bit length and bytes), four bytes and one byte (meaning unknown), then the
part's colour as red, green, blue and alpha bytes. The colour equals the
`color` of `MESH_DATA` (3 of 3) and the ACIS body's `rgb_color` attribute
(2 of 2 parts that carry one): verified. An assembly stores zeros there, read
as no colour.

## 6. `MESH_DATA`: the display tessellation

Little-endian throughout; verified on three parts, each parsed to its last byte.

1. Three typed dictionaries (integers, doubles, strings), each a 32-bit entry
   count and per entry a 32-bit key length, the key, a 32-bit element count and
   the elements (4 bytes an integer, 8 a double, a 32-bit length and bytes a
   string). Keys seen: `SCHEMA_VERSION_KEY`, `color` and `edgeColor` (RGBA
   bytes), `configId`, `reflectivity`, `stateID`; `density`, `extent` (a box
   round the B-rep, six doubles, model units: it contains the body but is not
   tight, up to 1.4 percent of the diagonal larger in the samples); `name`,
   `units`.
2. The face, edge and vertex counts, equal to the B-rep's (3 of 3).
3. One block per face, then one per edge: a 32-bit id, the index list's length
   L, the record count V, a 32-bit zero, a zero byte and the float32 -1.0, V
   records of eight float32, L 32-bit indices.
   - A face's records are x, y, z, a unit normal and the vertex's (u, v) on its
     surface; its indices are `3, a, b, c` per triangle, then 0.
     Counter-clockwise seen from outside: 16,671 of 16,716 triangles agree with
     their vertex normals.
   - An edge's first n records are its polyline's points; its indices are
     `n, 0, 1, ..., n-1, 0`. Edges are checked, not read.
   - Face ids run from 1 to the face count and edge ids after them; each equals
     the `PersistentID` attribute of its face or edge in the ACIS body (3 of 3).

Coordinates are float32 in the body's unit. The faces are independent meshes
and do not meet exactly: after welding, one sample part is closed and two keep
open edges at T-junctions. That is why a part is printed from its B-rep and
previewed from this mesh. Bounds: `mesh_dictionary_entries`, `mesh_key_bytes`,
`mesh_blocks`, every V and L against the bytes left, every index below its
block's V, triangles only, the terminator, and the declared counts against the
blocks. The clock is looked at once a block and every 4,096 records and
triangles inside one.

**Units.** The ACIS header's unit (section 7.1) is the part's; `MESH_DATA`'s
`units` string (`inches` and `cm` in the samples) agrees in 3 of 3. When they
disagree the B-rep's wins, warned `units_disagree`.

## 7. ACIS SAB (`SAB_DATA`, `.sab` files)

### 7.1 Header and tags

`ACIS BinaryFile` (15 bytes), four little-endian 32-bit integers (version,
record count, entity count, flags), three tagged strings (product, ACIS
version, date) and three tagged doubles (millimetres per model unit, `resabs`,
`resnor`). Verified against the published chapter and 3 of 3 samples (version
2100; units 25.4 in two parts and 10.0 in one).

Every value carries a one-byte tag: `0x04` 32-bit integer, `0x06` double,
`0x07` string with an 8-bit length, `0x0A` true, `0x0B` false (also reversed and
forward), `0x0C` pointer (32-bit record index, -1 null), `0x0D` identifier (the
last part of a type name; keywords inside subtypes), `0x0E` an identifier
prefix, `0x0F` and `0x10` subtype start and end, `0x11` record end, `0x13`
position and `0x14` vector (three doubles), `0x15` enum (32-bit). `0x12` (a
string with a 32-bit length) and `0x17` (a double) are documented elsewhere and
accepted; any other tag is damage. Type names join the prefixes and the final
identifier with `-` (`cone-surface`, `PersistentID-Alibre-attrib`). The data
ends with the record `End-of-ACIS-data`; bytes after it are damage. Verified on
every record of the samples' streams (27,376 records).

Every record is tokenized whatever its class, so a reader of a newer file still
finds every record's end; only the classes below are decoded. A history section
(`Begin-of-ACIS-History-Data`) ends the model's records (unseen).

The tokenizer keeps `sab_records`, `sab_string_bytes` and `sab_values`: every
type name, number, pointer, flag, string or bracket counts one value and a
position or vector three, so the bound follows the memory the tokens take
(37 to 49 bytes a value in the samples' streams, whose largest has 279,181
values and whose longest record 3,652). It looks at the clock every 4,096
values, inside a record as well as between records, under the caller's own
time and cancel as well as `limits.seconds`.

**Versions.** Record layouts are decoded only for version 2100 of `ACIS
BinaryFile`, the one seen. Inside an Alibre file, another version (or an `ASM
BinaryFile4` stream) is not decoded: the display mesh is used for everything,
warned `acis_version_unverified`. A standalone `.sab` of another version is
refused, `format_not_supported` rule `acis_version`; a `.sat` text file, rule
`sat_text`, until its reader exists.

### 7.2 Subtypes and `ref n`

Subtype definitions are numbered from 0 in file order as they start
(pre-order, nested ones included, `ref` blocks not counted); `ref n` names
definition n. Verified: under this rule all 834 references of the samples land
on an `exactsur` definition; the post-order rule fails. Nesting is bounded by
`sab_subtype_depth`, the table by `sab_subtypes`, and `n` out of range is
damage.

### 7.3 Record layouts at version 2100

Every topology and geometry record starts with an attribute pointer, two
integers (-1 in every sample) and a pointer; a transform with an attribute
pointer and one integer; an attribute with an attribute pointer, an integer,
then its `next`, `previous` and `owner` pointers. Verified on every record of
the classes below in the samples (each layout has the same tags in every
record of its class, apart from the documented variants).

| Class | After the prefix |
|---|---|
| `body` | lump, wire, transform, a logical |
| `lump` | next, shell, body, a logical |
| `shell` | next, subshell, first face, wire, lump, a logical |
| `face` | next, first loop, shell, subshell, surface, sense (true: reversed), double-sided, then a box |
| `loop` | next, first coedge, face, a box, a loop type (types other than 0 add a pointer and a logical; meaning unknown) |
| `coedge`, `tcoedge-coedge` | next, previous, partner, edge, sense, loop, pcurve |
| `edge`, `tedge-edge` | start vertex, start parameter, end vertex, end parameter, coedge, curve (null for a degenerate edge), sense, convexity string, a box (a `tedge`'s further fields, its tolerance among them, are not read) |
| `vertex`, `tvertex-vertex` | edge, point (a `tvertex` adds its tolerance) |
| `point` | position |
| `transform` (after attribute and integer) | three rows, translation, scale, rotate, reflect, shear |
| `plane-surface` | root, normal, u direction, reverse-v, four range bounds |
| `cone-surface` | base ellipse (centre, axis, major axis, ratio, curve range), sine, cosine, u scale, reverse-u, four range bounds |
| `sphere-surface` | centre, radius, u direction, pole, reverse-v, ranges |
| `torus-surface` | centre, axis, major radius, minor radius, u direction, reverse-v, ranges |
| `spline-surface` | sense, a subtype (`exactsur`, or `ref n`), ranges |
| `straight-curve` | root, direction, range |
| `ellipse-curve` | centre, normal, major axis (its length the radius), ratio, range |
| `intcurve-curve` | sense, a subtype (`surfcur`, `surfintcur`; `exactcur` and `parcur` read the same way), range |

A range bound is false (unbounded) or true and a double. Attributes read:
`rgb_color-st-attrib` (three doubles; owner the lump) and
`PersistentID-Alibre-attrib` (its last integer is the face's or edge's id in
`MESH_DATA`). The body name attribute is user text and is not read.

### 7.4 B-splines

After `{ exactsur` comes an enum (0 in every sample; meaning unknown), then the
surface: the form `nurbs`, `nubs` or `nullbs`, the u and v degrees, for `nurbs`
a rational keyword (`both`, `u` or `v`), the closure of u and of v (0 open, 1
closed, 2 periodic per the chapter), the singularity of u and of v, the numbers
of distinct u and v knots, (value, multiplicity) pairs for u then v, the
control points (x, y, z, then the weight when rational, not premultiplied, with
**u varying fastest**) and the fit tolerance. A curve block is the same in one
direction with no rational keyword. The end knots carry multiplicity equal to
the degree, so the clamped vector gets one knot more at each end. Verified
numerically on the samples: every interior display-mesh vertex of every spline
face lies on the decoded surface at its own (u, v) (medians 1.6e-5 and 1.6e-6
mm in the two parts that have spline faces), and the display polylines of the
intcurve edges lie within a micrometre of the decoded curves. Every closure is
0, and every end multiplicity equals the degree, except two periodic
intersection curves (closure 2) whose ends are still clamped; a spline whose
end multiplicities are not the degree is not mapped (its face is left out).
Knot and point counts are checked against the values left in the record and
`bspline_knots`.

### 7.5 Sign and parameter conventions

Measured on the samples against the stored display normals (counts of display
vertices that agree), each face's normal with its sense applied:

| Surface | Rule | Agree |
|---|---|---|
| plane | the stored normal | 4,730 of 4,730 |
| cone, sine 0 (cylinder) | away from the axis when the cosine is positive, whatever reverse-u | 6,336 of 6,336 (72 with reverse-u set) |
| cone | away from the axis when the cosine is positive, towards it when negative; the radius grows by sine over cosine per unit along the axis | 300 of 300 on 10 faces (50 vertices near an apex not counted) |
| sphere | out of the sphere (radius positive in every sample) | 207 of 207 |
| torus | away from its centre circle (radii positive), whatever reverse-v | 1,783 of 1,783 (170 with reverse-v set) |
| spline | `Su x Sv` (every spline surface forward) | 2,087 of 2,087 |

Curves: a straight's point is `root + t direction` (the direction is not of
unit length) and its edge's parameters are those of its vertices (1,408 of
1,408); an ellipse's point is `centre + cos t major + ratio sin t (normal x
major)` and its edges run from the start parameter up to the end one (454 of
454, by the angles of their display polylines); an intcurve's stored B-spline
starts and ends at its edge's vertices in 560 of 575 edges. A display polyline
starts at its edge's start vertex in 2,437 of 2,437 edges.

Unseen, read by the published rules and marked hypothesis: a negative sphere
radius or torus minor radius (normal into the surface), a reversed spline
surface or intcurve (normal or direction turned round), a reversed edge that is
not closed, a body transform (applied as row vectors, warned
`transform_unverified`; one that reflects or shears is not applied, and the
display mesh is used).

### 7.6 To a Parasolid transmit, and the tessellator

`solidseas.formats.acis.geometry` maps a body to an in-memory Parasolid
transmit, which `solidseas.tessellate` draws (the design's shared B-rep builder
will replace its node writer). Topology: a face to a FACE (sense `-` when
reversed), a loop to a LOOP, a coedge to a fin (sense `-` when reversed; its
end vertex the edge's end, or its start), the coedges of an edge to partner
fins, an edge to an EDGE on a curve of its own (sense `-` when the edge runs
against its curve), a vertex to a VERTEX. A degenerate edge (no curve, one
vertex, at an apex: 1 in the samples) is left out of its loop. Geometry: plane
to PLANE; cone to CYLINDER (sine 0), CONE (ratio 1) or, for an elliptic
cylinder, a swept ellipse (SWEPT_SURF); sphere and torus to their XT forms;
an `exactsur` to a B_SURFACE (control points reordered to v fastest);
straight to LINE, ellipse to CIRCLE or ELLIPSE, an intcurve to a B_CURVE
through its stored B-spline. Each surface takes the sense that gives its
natural normal the ACIS direction (7.5). Lengths are scaled to metres.

A tolerant edge (`tedge-edge`, with its `tcoedge-coedge`s; none in the samples)
is read as an ordinary edge on its curve: its tolerance is not read, so its XT
EDGE carries none, and nothing is left out or warned. A `tvertex` keeps its
tolerance.

A sphere keeps its stored pole as the XT sphere's axis, except where one of its
faces has a loop of one closed circle through both poles (a solid sphere, or a
revolve about the pole's axis, cut by a plane through that axis): SolidSeas'
tessellator draws such a face wrongly, closed but with about a third too much
area, so the circle's normal becomes the axis and the loop the XT sphere's
equator. The surface is the same; only its parameters change. A loop through
both poles made otherwise (an intcurve ring, or arcs that pass a pole between
their vertices) keeps the stored pole.

Not mapped, and so left out of the body with the face reported skipped
(`faces_left_out`): an elliptic cone, a torus with a non-positive major
radius, a spline surface or intcurve of another subtype (blend surfaces,
offsets, sweeps, lofts and law surfaces are procedural in ACIS; when they store
no B-spline approximation SolidSeas cannot draw them), a spline whose knots are
not finite and increasing, a number that is not finite once scaled, and
anything else that fails its checks. A face is decoded and its loops followed
before any of its nodes is written, so one that fails there costs the body its
closure (it is read as a sheet); one that fails while its nodes are written
leaves the body a solid with that face missing.

**On the samples:** 3 of 3 parts mapped and tessellated **closed**, 907 of 907
faces done, no face left out. Each part's tessellated box equals its display
mesh's to within a ten-millionth of the diagonal, and lies inside the stored
`extent`; the tessellated area is within 0.15 percent of the display mesh's
(0.14, 0.02 and 0.05 percent). Face by face, matched by `PersistentID`: 907 of
907 faces face the same way as their display faces (the normals of the nearest
triangles, at five places a face); 840 of 907 have their area within 2 percent
of their display faces'; the other 67 (curved fillets and blends, mostly small,
under 2 percent of the area together) have their boxes within 5 percent of their
display faces', the difference being the display mesh's coarser facets.
`tests/test_formats_alibre_samples.py` repeats these checks when
`SOLIDSEAS_ALIBRE_SAMPLES` names a list of sample files. Pure Python on the
development PC: tokenizing 0.01 to 0.24 s, mapping up to 0.44 s, tessellating
0.01 to 4.5 s; reading a display mesh under 0.1 s.

## 8. The design database and assemblies

### 8.1 `STEP_DATA`

ISO 10303-21 text (CRLF lines wrapped near 90 characters, inside strings
too; `\X\` escapes), schemas `('ALIBRE_SCHEMA','CONFIG_CONTROL_DESIGN')`.
AP203-style product, person and organisation records and Alibre's design
history; no B-rep. Verified (4 of 4). `CONFIG_CONTROL_DESIGN` is AP203's schema
name, so a STEP reader must refuse a file whose schemas name `ALIBRE_SCHEMA`:
it holds no geometry. SolidSeas reads it with a small Part 21 reader inside
the Alibre package (the design's shared one will replace it), within the
`p21_*` bounds; person and organisation records are never read.

### 8.2 Inclusions

Verified on one assembly:

- `DESIGNASSEMBLY(..., (#inclusion, ...), ..., configuration)`: the list of
  inclusions.
- `DESIGNINCLUSION((), (#member), path, #reference, $, #placement, $, .F., $,
  instance-guid, .F., #profile, 0, $, configuration-name)`, read by position;
  a record of another shape is skipped (`component_not_found`). At most
  `inclusions`.
- `REPOSITORYVERSIONREFERENCE(version, drive-letter, repository-path,
  document-guid, '', '', 1, 1, $)`: the document GUID equals the GUID in the
  part's own `VERSION` and the version its version (3 of 3).
- `CARTESIAN_TRANSFORMATION_OPERATOR_3D($, $, $, axis1, axis2, local_origin,
  scale, axis3)`, the ISO 10303-42 order, with `DIRECTION($, (x, y, z))` and
  `CARTESIAN_POINT($, (x, y, z))`. The axes are completed by ISO 10303-42's
  `base_axis` rules. Two inclusions may share one placement record (seen). A
  scale other than 1 or a left-handed result is kept and warned
  `non_rigid_transform`. Every rotation in the sample assembly is the identity,
  so a turned placement is verified only on synthetic files.

**Placement unit: hypothesis.** The translations are read in centimetres,
warned `placement_unit_assumed`. Evidence: in the one assembly, read in
centimetres every component's box overlaps another's or lies within 1 mm of it;
read in inches one component lies more than 200 mm from the others. The
design database's length formats name 10 mm as their internal unit in all four
files, which fits, but which record states the placements' unit is unknown, and
the inch parts' feature dimensions did not settle it. An assembly's `units` are
reported as centimetres, `assumed`.

### 8.3 Finding the components

An assembly names each document by GUID; for 2 of the 3 samples' components
the stored name differs from the file's name on disk, while the GUID matches
(3 of 3). So the stored path is never opened. SolidSeas walks the assembly's
folder (then each folder in `scene(roots=...)`) with `solidseas.walk` (no link
followed, no cloud placeholder opened, lock files skipped; `resolve_depth`,
`resolve_examined`, `resolve_seconds`), reads only `VERSION` of each Alibre file
found (at most `resolve_candidates`, opened read-only within its folder), and:

1. a file of that document GUID is `found` (`found_by` `document_guid`); among
   several, the one in the assembly's own folder, then the shortest relative
   path, then the version referenced, warned `component_ambiguous`; a newer
   version than the one referenced is used and warned `component_newer`, an
   older one `component_older`;
2. otherwise a file in the assembly's folder named as the stored name, whose
   own GUID could not be read, is used, warned `component_found_by_name`; one
   whose GUID differs is another document;
3. otherwise `not_found`: the inclusion is left out with `component_not_found`.

A component file is opened under the rules the assembly was opened with: when
that was with `refuse_hard_links` (as the REST service opens every document), a
file with a second name is no candidate, since that name may lie outside the
folder, and a component over the assembly's `max_file_bytes` is left out as an
unreadable one is.

On the sample assembly: 3 of 3 components found by GUID (by name alone, 1 of 3
would have been). A sub-assembly is placed recursively, its own components
looked for near it first; cycles (by GUID) are refused, depth is bounded by
`depth` and the documents one scene opens by `components`.

## 9. Open questions

- Other Alibre releases: one release and one ACIS version (2100) were seen.
  Other versions may add fields to the records decoded here.
- Multi-body parts, several configurations in one file, sheet metal parts,
  drawings and packages: unseen.
- The placements' unit (8.2), turned, mirrored and scaled placements, and
  sub-assemblies: unseen or a hypothesis.
- Custom properties: `CUSTOM_ITEM_PROP_DATA` and `STANDARD_DESIGN_PROP_DATA`
  are empty in every sample.
- The meaning of the two integers in every record's prefix, the enum after
  `exactsur`, the loop types, the constant fields of `MESH_DATA` blocks and of
  `LIGHT_CONFIGURATION_DATA`.
- Procedural ACIS surfaces and curves without a stored approximation.

The single most useful step would be STEP or STL exports of the same parts made
by Alibre on another computer: they would check the B-rep reading end to end.
