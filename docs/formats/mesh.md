# Mesh formats: 3MF, OBJ, PLY, OFF, glTF and AMF

These formats describe surfaces as triangles (or polygons cut into triangles),
with no B-rep. SolidSeas reads them with one module each in
`solidseas.formats` (`threemf`, `obj`, `ply`, `off`, `gltf`, `amf`), behind the
model-file interface of `docs/API.md` 3.20 and its section 3.20.5. STL, the
reference reader, has its own document ([stl.md](stl.md)). Labels as in
[README.md](README.md): **verified** (with its source), **hypothesis**,
**unknown**.

Every reader turns a file into `MeshObject`s (in metres, through the shared
`MeshBuilder`, which drops triangles that name a missing vertex or repeat one)
and `SceneItem`s that place them. What they share:

- **Colours split objects.** A mesh object whose triangles carry several colours
  becomes one scene object a colour, each with only the vertices its triangles
  use, all placed by the same items and named alike. Past `colors_per_object`
  (256) colours the object stays whole, in the colour most of its triangles
  have, with the warning `colors_ignored`. (Verified: synthetic tests in
  `tests/test_formats_3mf.py`, `test_formats_ply.py`, `test_formats_off.py`,
  `test_formats_obj.py`.)
- **Polygons.** A face of more than three corners (OBJ, PLY, OFF) is cut as a
  fan when it is convex; otherwise it is projected onto its best-fit plane
  (Newell's normal) and cut by ear clipping
  (`solidseas.tessellate.triangulate.earcut`), which keeps the polygon's winding
  and cuts concave faces right. A face that crosses itself falls back to the fan.
  A face with more than `polygon_corners` (1,024) corners is refused
  (`limit_exceeded`), one with fewer than three is left out
  (`degenerate_triangles_dropped`). (Verified: `tests/test_formats_obj.py`, an
  L-shaped prism and a concave arrow.)
- **Units.** OBJ, PLY and OFF state none: millimetres are assumed
  (`units_assumed`). 3MF and AMF state theirs (millimetres when absent, as their
  specifications say: `units.source` `format`); glTF is metres by definition.
- **Tree and scene agree.** `tree()` reads the file as `scene()` does but keeps
  no vertex, so a tree node's `object` is the index its first scene object will
  have. Each costs one full read of the file. A tree stops making nodes once it
  has more than `limits.tree_nodes` (then `truncated`), so a 3MF or AMF whose
  components or constellations fan out costs a tree no more than its nodes.
- **A scene cut by `max_triangles`** keeps the objects finished before the cut
  and places them, as the STL reader keeps its finished solids (verified:
  `tests/test_formats_mesh_scenes.py`). Each object's triangles are counted
  before it is kept, so the kept objects hold at most `max_triangles`; the object
  being read when the cap was passed is dropped. A 3MF goes on reading its parts
  for their components and build only, and an AMF for its materials and
  constellations, so the finished objects are placed as the file places them;
  an instance of a dropped object is left out without a warning. An OBJ keeps
  the groups it had left, with the faces read until then, and stops reading
  (a material library named later is not read); glTF keeps the primitives
  finished, placed by every node that shows them. A PLY or OFF is one object,
  so it keeps nothing, as a binary STL does.
- **Parts and assemblies.** A file is an assembly when it places objects as
  structure (3MF build items or components, glTF node instances, AMF
  constellations); several objects alone (OBJ groups, a PLY's colours) are still
  one part.
- **Bounds** (`docs/API.md` 3.20.2): every count read from a file is checked
  against the bytes left before anything is allocated; text lines of OBJ, MTL,
  ASCII PLY and OFF share `obj_line_bytes` (1 MiB); triangles and vertices count
  against `triangles` and `vertices` as they are read, and a scene's
  `max_triangles` stops the read early. Every placement a 3MF's components or an
  AMF's constellations expand to counts against `items` and ticks the clock, so
  a file of a few kilobytes that nests ten placements six deep stops at `items`
  or at its time bound, its memory flat. Hostile files are tested in
  `tests/test_formats_mesh_hostile.py`: every cut point, flipped bytes, tight
  bounds, cycles, zip bombs, names and URIs that climb out, DOCTYPE and entities,
  encrypted and unknown zip members.

## 3MF

Sources: the 3MF Core Specification 1.3, the Production Extension 1.1 and the
Materials and Properties Extension 1.2 (3MF Consortium, published on GitHub),
and the Open Packaging Conventions (ECMA-376 Part 2).

- **Package** (verified: specifications, the fixture
  `tests/fixtures/o02_boxA.3mf` SOLIDWORKS wrote, synthetic tests). A zip read
  by `SafeZip`. `_rels/.rels` names the root model part by the relationship type
  `http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel`; no
  relationship, no model (`damaged_file`): the part is never assumed. A target
  that climbs out of the package, names another scheme or uses a backslash is
  refused.
- **Model** (verified: specifications, synthetic tests). XML in the core
  namespace, streamed through `xml_events`, never built as a tree. `unit` is
  `micron`, `millimeter`, `centimeter`, `inch`, `foot` or `meter` (another is
  `damaged_file`). A transform is twelve numbers `m00 m01 m02 m10 m11 m12 m20 m21
  m22 m30 m31 m32` applied to a row vector: the first three are where the x
  axis goes, the last three the translation in the model's unit. The reader
  writes it as a `Placement` whose rotation is that matrix transposed, the form
  SolidSeas' own 3MF writer reverses (verified: every fixture kind written by
  `solidseas.export.write_3mf` reads back with the same placements, objects and
  volumes, `tests/test_formats_3mf.py`).
- **Objects and the build** (verified: specifications, synthetic tests). An
  object holds a `<mesh>` or `<components>`; build items place objects with their
  transforms, components place objects inside objects, composed down to the
  meshes (depth `threemf_component_depth`, 16; a cycle is `damaged_file`).
  Objects of type `other` are never placed (`skipped` with reason
  `other_object`); `support` and `solidsupport` objects are placed under their
  names. An item or component naming an object the model lacks is skipped with
  `component_not_found`.
- **Production extension** (verified: the extension's text, synthetic tests).
  `p:path` on a component or a build item names another model part, an absolute
  part name; it is resolved inside the package only. Only the root model may
  name other parts: a non-root part's own `p:path` is refused for that
  component (`part_reference_refused`). Each part is read once and its objects
  placed as often as they are named. `p:UUID` is not read. The relationship from
  the root part to the others (`3D/_rels/3dmodel.model.rels`) is not required.
- **Required and recommended extensions** (verified: specifications, synthetic
  tests). `requiredextensions` lists namespace prefixes. The core, production,
  materials and triangle-sets namespaces are read; any other required one
  (slices, beam lattices, volumetric, implicit, secure content, displacement,
  production alternatives, or a namespace SolidSeas does not know) refuses the
  file: `format_not_supported`, rule `required_extension`, value the namespace.
  A non-root part's required extensions are checked the same way, from its own
  namespace declarations. A recommended one SolidSeas does not read is warned
  `extension_ignored`.
- **Colours** (verified: specifications, synthetic tests). `<basematerials>`
  (core) display colours and `<m:colorgroup>` colours. A triangle with `p1` takes
  entry `p1` of its `pid` group (its object's group when it has no `pid`; with
  `p2` and `p3`, which grade a property across the triangle, `p1` colours it
  whole, as the specification tells a consumer without gradients to do). A
  triangle without `p1` takes its object's `pid` and `pindex`, whatever its own
  `pid`: the core specification gives such a triangle the object's default
  property. Texture groups, composite materials and multi-properties give no
  colour (`textures_ignored` for textures). Past `threemf_color_groups` (65,536)
  group entries a part's further colours are not kept (`colors_ignored`); more
  groups than that are refused.
- **Metadata** (verified: specification). The root model's `<metadata>`
  elements with unprefixed names: `Title` (`fields.title`), `Designer`
  (`fields.author`), `Description` (`fields.comments`), `CreationDate` and
  `ModificationDate` (`fields.created_utc` and `last_saved_utc`; a date alone is
  its midnight and a time without a zone is kept as stored, both naive, so they
  show the day the file names; a time with a zone is aware UTC), `Application`
  (`application`, its version split off when it ends in one); every one is also a
  file property. Names in a vendor's namespace (slicers') are not read. A
  package with vendor namespaces on its model, or settings parts under
  `Metadata/` (`.config`, `.xml`, `.json`), is warned `slicer_data_ignored`:
  plates, print settings and painted colours stay in the slicer's own data.
  Only the first 64 KiB of the root model is read for this, as a head.
- **Stored preview** (verified: the fixture, corpus). The package's thumbnail
  relationship, else `Metadata/thumbnail.png`, else the lowest-numbered
  `Metadata/plate_<n>.png`; a PNG only (a JPEG thumbnail is passed over), at most
  `image_bytes`. Listings and workers pass it on only as the PNG `sanitize_png`
  writes again.
- **Document type and head counts** (verified: synthetic tests). An assembly
  when the build has more than one item or a components object of the root
  model places more than one component, else a part (so the SOLIDWORKS-written
  box, one item placing a wrapper of one component, is a part). The head reads
  the first 64 KiB of the root model alone, so a listing stays cheap however
  large the model: when the whole model is in them, a scan of their tags
  settles the type, `counts.objects` (objects the root model part defines) and
  `counts.items` (build items); otherwise more than one item, or more than one
  component in one object, seen there makes it an assembly, and the rest is
  None. The build follows the meshes, so for most models past 64 KiB `doc_type`
  and those counts are None until `tree()` or `scene()` reads the model, which
  settles them on the document. `counts.model_parts` is the package's `.model`
  parts, from the zip directory. Variant `production` when the root model
  declares or requires the production namespace, else `core`.
- **Not read**: slices, beam lattices and the other refused extensions;
  textures; `metadatagroup`; triangle sets (grouping only); object thumbnails;
  the package's digital signatures and other OPC parts.
- **Cost** (measured, development PC): a model of one million triangles takes
  about 10 s to read and about as long again for its tree; most of it is the
  XML parser's events in pure Python. The head of the same file (8.7 MB) takes
  0.006 s once the file is cached, as it reads 64 KiB of the model whatever its
  size (0.6 s when it scanned the whole model's tags).

## OBJ

Sources: Wavefront's "Object Files (.obj)" and "Material Library File (.mtl)"
descriptions, as published with the Advanced Visualizer manual.

- **Statements** (verified: the description, synthetic tests). `v x y z` (more
  numbers after the three are ignored), `f` with corners `v`, `v/vt`, `v//vn` or
  `v/vt/vn`, numbered from 1 over the whole file, a negative number counting
  back from the last vertex read; `o` and `g` start a group named by the rest of
  the line; `usemtl` and `mtllib`. `vt` and `vn` are not kept (normals are worked
  out from the triangles); `s`, `mg`, `lod` and the like are ignored; `l`, `p`,
  `curv`, `curv2` and `surf` are not read (`primitives_skipped`), nor the
  free-form statements around them. Statements no OBJ reader shares are ignored,
  as they are by others.
- **Comments and long statements** (verified: the description, synthetic
  tests). "Comments can appear anywhere in an .obj file" (the description, as
  Paul Bourke publishes it): `#` starts a comment wherever it stands, to the end
  of the line, and a line that is only a comment ends there (a backslash at its
  end continues nothing). On a line that names something (`o`, `g`, `usemtl`,
  `mtllib`, and `newmtl` in a library) a `#` starts a comment only after a space
  or tab, so a name such as `part#2` keeps its hash. A backslash at the end of a
  line continues the statement on the next line, as the description's examples
  do; the joined statement is bounded by `obj_line_bytes`. MTL lines take
  comments the same way.
- **Groups** (verified: synthetic tests). Every group with faces is one object,
  named by its `o` or `g` line; faces before any are the file's own object, named
  by the file; a name used again adds to its group. Each object keeps only the
  vertices its faces use.
- **Materials** (verified: synthetic tests). Each `mtllib` names libraries (the
  whole rest of the line when it is one name ending in `.mtl`, so a name may hold
  spaces; else its words), read only from inside the document's folder by
  `read_sibling` (no `..`, absolute path, drive, UNC, scheme, alternate stream or
  link, and no second name when the document was opened with
  `refuse_hard_links`; at most `obj_material_libraries`, 16). From a library: `newmtl`, `Kd`
  (diffuse colour, clamped to 0 to 1; a spectral or CIE XYZ `Kd` is not read),
  `d` (opacity) or `Tr` (one less the opacity); `map_` statements and `bump`,
  `disp`, `decal`, `refl` give `textures_ignored`. A library that cannot be read
  (missing, refused, or a document opened from bytes) gives
  `material_library_unread`. `references()` lists each library (`kind`
  `material_library`) with `found`, `not_found` or `refused`, without opening
  it.
- **Head**: the comments the file starts with (in its first 4 KiB, at most 16)
  are the property `comment`; no counts.

## PLY

Source: Greg Turk's "The PLY Polygon File Format", as published with the
Stanford 3D Scanning Repository.

- **Header** (verified: the description, synthetic tests). `ply`, `format ascii
  | binary_little_endian | binary_big_endian 1.0` (the variant `ascii`,
  `binary_le`, `binary_be`), `comment` and `obj_info` lines (the properties
  `comment` and `obj_info`), `element name count` and `property type name` or
  `property list count_type item_type name`, ending at `end_header` and its line
  feed (CR LF accepted). Types `char`, `uchar`, `short`, `ushort`, `int`, `uint`,
  `float`, `double` and their sized names (`int8`... `float64`). At most
  `ply_header_bytes` (64 KiB), `ply_elements` (32) and `ply_properties` (64) an
  element. Every element's rows must fit in what follows the header (each at
  least its fixed-size properties and list counts in binary, two bytes a
  property in ASCII), checked before anything is read.
- **Elements** (verified: synthetic tests). `vertex` (`x`, `y`, `z` required;
  `nx`, `ny`, `nz` kept as normals; `red`, `green`, `blue`, `alpha` or the
  `diffuse_` names as colours, integers scaled by their type's maximum), `face`
  (`vertex_indices` or `vertex_index`, an integer list; its own colour) or
  `tristrips` (strips separated by -1, every other triangle turned so all keep the
  strip's winding). Every other element is skipped by its size, a list longer
  than the file refused; the lists the reader does not use (in a skipped element,
  or a vertex's or face's other properties) are passed over without being read
  into memory. Binary rows of fixed size are unpacked in batches; ASCII values may
  run across lines.
- **Order and strips** (verified: the description, synthetic tests). Elements
  may come in any order: when the faces come before the vertices, the vertices
  are read first and the reader goes back for the faces, so polygons are cut and
  coloured with their vertices known. A face's list is bounded by
  `polygon_corners`; a `tristrips` list is not, since a strip file usually holds
  the whole mesh as one list in one row: it is read compactly (as an array of its
  binary type, or of 32-bit integers from ASCII), bounded by the bytes left, and
  its triangles are counted against `triangles` as they are made.
- **Colours**: a triangle takes its face's colour, else its first corner's.
- **No faces**: a point cloud, warned `primitives_skipped`, with nothing to draw.

## OFF

Source: the Geomview manual, "OFF Files".

- **Layout** (verified: the manual, synthetic tests). The keyword `OFF` with the
  prefixes `ST` (texture coordinates), `C` (colours), `N` (normals), then the
  vertex, face and edge counts on the keyword's line or the next; a vertex a line
  (`x y z`, the normal, the colour, the texture coordinate, as the keyword
  says); a face a line: its corner count, the vertex numbers from 0 and an
  optional colour. `#` starts a comment. The variant is the keyword.
- **The keyword is optional** (verified: the manual, synthetic tests). The
  manual calls the header keyword optional, for the many files that lack it: a
  file that starts with two or three whole numbers is read as plain `OFF` (variant
  `OFF`). Content alone cannot tell such a file from text, so it is read as OFF
  only by its `.off` name or a forced format. A keyword followed by the vertex
  count without a space (`OFF490 518 0`, as some shape collections write it) is
  read too, its variant the keyword.
- **Colours** (verified: the manual, synthetic tests): three or four numbers,
  from 0 to 1 when any is written with a decimal point or an exponent, else from
  0 to 255; one number alone is a colour-map index, not read. Normals are kept;
  texture coordinates are not (`textures_ignored`).
- **Refused**: `OFF BINARY` (`format_not_supported`, rule `binary_off`), and the
  four-dimensional and n-dimensional variants `4OFF` and `nOFF` (rule
  `unsupported_variant`, value the keyword). The counts must fit the file (six
  bytes a vertex, eight a face at least).
- **Hypothesis**: every writer puts one face on one line, as Geomview's own
  files do; a face split across lines is read as damaged.

## glTF 2.0 and GLB

Sources: the glTF 2.0 specification (Khronos) and the extension specifications
`KHR_mesh_quantization`, `KHR_draco_mesh_compression` and
`EXT_meshopt_compression`.

- **Containers** (verified: specification, synthetic tests). JSON (at most
  `json_bytes`, strict: no NaN or Infinity, depth `json_depth`) or GLB: `glTF`,
  version 2, the total length (not past the file), a JSON chunk first and an
  optional binary chunk, which is buffer 0 when that buffer has no `uri`. The
  variant is `gltf` or `glb`; `asset.version` must be 2.x.
- **Buffers** (verified: synthetic tests). The GLB chunk; `data:` URIs (base64,
  at most `gltf_data_uri_bytes`, 256 MiB, decoded); relative URIs naming a file
  inside the document's folder, through `read_sibling` (a URI that climbs out,
  is absolute, names a drive, a UNC path, a scheme, an alternate stream or a
  device is refused with `path_refused`, one with a second name, when the
  document was opened with `refuse_hard_links`, with `link_refused`, and one
  over its `max_file_bytes` with `file_too_large`; a missing file is
  `damaged_file`). Buffers are read only by `scene()`, each once; images never.
  `references()` lists the buffer files (`kind` `buffer`), with where each was
  found relative to the document's folder, or `refused` when a link, junction
  or placeholder lies on the way.
- **Accessors** (verified: specification, synthetic tests). Every component
  type, `normalized` (signed values clamped at -1), `byteStride`, sparse
  substitutions; every view inside its buffer and every accessor inside its view,
  computed in Python integers before a byte is read, and every count checked
  against what the scene may still take (`vertices` for positions, `triangles`
  for indices) before anything is allocated. Positions and normals are `VEC3`,
  indices unsigned `SCALAR`; normals whose count is not the positions' are not
  read. With `KHR_mesh_quantization` positions may be integers.
- **Accessors without a buffer view** (verified: specification, synthetic
  tests). The specification makes such an accessor zeros, its sparse values
  substituted. A primitive whose positions or indices are zeros with no sparse
  block has nothing to draw (every corner at the origin, or every index 0): it
  is left out at the head (`primitives_skipped`), so its claimed count costs
  nothing. Zero normals are not read. A zero-filled accessor with a sparse block
  may hold at most `zip_ratio` (200) times the bytes of that block, past 1 MiB,
  the bound a zip member's inflation keeps (`limit_exceeded`, limit
  `zip_ratio`), so its memory follows the file's size.
- **Primitives** (verified: specification, synthetic tests). Triangles (mode 4),
  strips (5: every other triangle turned) and fans (6) become one scene object a
  primitive, in mesh order, normals kept, coloured by the material's
  `baseColorFactor` (or the specular-glossiness extension's `diffuseFactor`); a
  material with only a texture has no colour (`textures_ignored`). Points and
  lines, and primitives without positions, are left out (`primitives_skipped`).
  A primitive held only in Draco form (its positions accessor has no buffer
  view) or only in meshopt form (its views' buffer is the extension's fallback,
  without data) is left out (`compression_not_supported`).
- **Nodes** (verified: specification, synthetic tests). The default scene, else
  the first; with no scenes, every node without a parent; with no nodes, each
  mesh once where it stands. A node's `matrix` (column-major) or translation,
  rotation (a unit quaternion) and scale, composed from the scene's roots down
  (depth `depth`, 32); a node that is its own child, two nodes' child, in a cycle,
  or a root that is also a child is `damaged_file`. Each node with a mesh places
  every object of that mesh once (`SceneItem.instance` the node's tree id).
- **Axes** (verified: specification, synthetic tests). glTF is metres with Y up.
  The reader turns the scene to Z up at its root (+90 degrees about X,
  `solidseas.formats.gltf.Z_UP`): objects keep glTF's own frame and every
  placement starts with the turn, so a print mesh and a glTF of it stand alike
  (the registry's `up_axis` for glTF is `z`).
- **Extensions** (verified: synthetic tests). An asset that requires
  `KHR_draco_mesh_compression` or `EXT_meshopt_compression` is refused
  (`format_not_supported`, rule `compression`); one that requires any other
  extension except `KHR_mesh_quantization`, the texture and material extensions
  (`KHR_texture_transform`, `KHR_texture_basisu`, `EXT_texture_webp`,
  `EXT_texture_avif`, `KHR_materials_*`), `KHR_lights_punctual`,
  `KHR_xmp_json_ld` and `KHR_animation_pointer` is refused (rule
  `required_extension`, value the name). `EXT_mesh_gpu_instancing` used but not
  required is warned `extension_ignored` (its instances are not placed).
  Animation, skins and morph targets are not read: the rest pose is drawn.
- **Head**: from the JSON alone: `asset.generator` (also `application`, its
  version split off), `copyright`, `version`, `minVersion` and the simple values
  of `asset.extras` (`title` and `author` there fill the fields) as properties;
  the counts of objects, placed items, placed triangles (from the accessors'
  counts) and vertices. An asset that places more than one mesh is an assembly,
  its tree the node hierarchy under an assembly node; one placed mesh is a part.
- **Bounds**: `gltf_buffers` (1,000) buffers; `gltf_array_items` (100,000) of
  each of accessors, buffer views, meshes, primitives (in all), nodes,
  materials, scenes, images and textures.

## AMF

Sources: the published descriptions of ISO/ASTM 52915 (the Additive Manufacturing
File format), such as its Wikipedia article; the standard's own text was not
consulted.

- **Container** (verified: synthetic tests). Plain XML (variant `plain`) or a
  zip holding an `.amf` member (variant `zip`; the first one when there are
  several), read by `SafeZip`. A zip without one is `damaged_file`.
- **Document** (verified: the published description, synthetic tests).
  `<amf unit>` (`millimeter`, `inch`, `feet`, `meter`, `micron`, and the spellings
  `millimetre`, `metre`, `foot`, `micrometer`; millimetres when absent);
  `<object>` with `<mesh><vertices><vertex><coordinates><x> <y> <z>` and
  `<volume>` elements of `<triangle><v1> <v2> <v3>`; `<material>` with a
  `<color>` (`<r> <g> <b> <a>`, 0 to 1); top-level `<metadata type>`: `name`
  (`fields.title`), `author` (`fields.author`), `description`
  (`fields.comments`), `cad` (`application`), every one a property. Namespaces
  on the elements are ignored.
- **Colours** (verified for the order: the published description; synthetic
  tests). A `<color>` may stand in a material, an object, a volume, a vertex or a
  triangle, and "takes priority in reverse order (triangle color is highest
  priority)" (the Wikipedia article on AMF). A triangle therefore takes its own
  colour, else its first corner's vertex colour (a mesh drawn one colour a
  triangle cannot blend corners), else its volume's colour, else its object's,
  else its volume's material's. A colour written as a formula (AMF allows them)
  is not read; textures and composite materials are not read.
- **Constellations** (verified for the order: the published description;
  synthetic tests). `<instance objectid>` with `<deltax> <deltay> <deltaz>` and
  `<rx> <ry> <rz>` in degrees, turned about x, then y, then z, then moved; an
  instance may name an object or another constellation, nested to
  `amf_constellation_depth` (16), a cycle `damaged_file`, a missing object
  `component_not_found`. The top-level constellations (those no instance names)
  place their instances under an assembly node; objects no constellation places
  are placed once where they stand. Without constellations the file is a part
  and every object stands once. Every placement, of an object or a
  constellation, counts against `items` and ticks the clock, empty
  constellations included.
- **Curved triangles**: vertex `<normal>`s and `<edge>` tangents are not used:
  triangles are drawn flat (`curved_triangles_flattened`).
- **Head**: the `amf` element and the metadata before the first object, from the
  first 64 KiB, and the document type when those 64 KiB settle it: an assembly
  when a constellation appears in them, a part when the whole file is in them
  without one. Constellations come after the objects, so a longer file's
  `doc_type` is None until `tree()` or `scene()` reads it.

## Measured on the development corpus

The folders that hold the development corpus's SOLIDWORKS documents also hold
mesh files (counted with `tests/test_formats_mesh_corpus.py`, numbers only,
below normal priority, every file's size and time unchanged):

- **3MF** (verified, measurement): 87 of 87 read, every one a slicer project; 51
  use the production extension, 36 the core alone; 61 are assemblies and 26
  parts once read, the type a scan of the whole model gave every one; the head
  alone settles 56 (39 assemblies, 17 parts) and leaves the 31 whose model runs
  past 64 KiB to the full read, which settles their counts too, equal to the
  whole-model scan's for all 87. All 87 thumbnails found and sanitised;
  triangles placed from 28,694 at the median to 971,328, the triangles, volumes
  and boxes equal to an independent parse's (the standard library's zip and XML
  readers) for every package; one package holds no object at all (an empty
  project: nothing to export or draw); 81 of 87 close once welded; 86 carry
  slicer settings (`slicer_data_ignored`) and 3 place items with a scale or
  mirror (`non_rigid_transform`). None uses base materials or colour groups.
  Over two runs a scene took from 0.26 s to 0.28 s at the median and 11.4 s at
  most (the largest model) and a tree about as long; the export (welding and
  checks) took 0.5 s at the median and 24 s at most. A head takes 0.002 s at
  the median and 0.12 s at most.
- **OBJ** (verified, measurement): 1 of 1 read, 179 groups and 204,047 triangles,
  in 1.4 s, its material library absent from the folder
  (`material_library_unread`).
- **STL**: 377 of 377, as [stl.md](stl.md) says.
- **PLY, OFF, glTF, GLB, AMF**: none in the corpus folders; synthetic tests only.

## Open questions

- 3MF painted colours and per-plate settings live in each slicer's own parts
  (`Metadata/*.config`); reading them would need a study of each slicer's format.
- AMF's rotation order comes from the standard's public description; a file
  written by a program that rotates in another order would place instances
  differently.
- OFF faces split across lines, PLY files with several face elements and OBJ
  files that use a vertex before defining it are read as described above but
  have not been seen in real files.
